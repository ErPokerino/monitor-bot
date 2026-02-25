"""Reusable pipeline engine, decoupled from CLI.

Extracted from main.py so it can be invoked both from the CLI entry point
and from the web application with different progress-reporting strategies.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import defaultdict
from datetime import date, datetime
from typing import Protocol

from monitor_bot.classifier import GeminiClassifier
from monitor_bot.collectors.anac import ANACCollector
from monitor_bot.collectors.events import EventsCollector
from monitor_bot.collectors.ted import TEDCollector
from monitor_bot.collectors.web_events import WebEventsCollector
from monitor_bot.collectors.web_search import WebSearchCollector
from monitor_bot.collectors.web_tenders import WebTendersCollector
from monitor_bot.config import Settings
from monitor_bot.date_enricher import enrich_missing_dates
from monitor_bot.models import ClassifiedOpportunity, Opportunity, OpportunityType
from monitor_bot.persistence import PipelineCache

logger = logging.getLogger(__name__)

TOTAL_STAGES = 6


# ------------------------------------------------------------------
# Progress callback protocol
# ------------------------------------------------------------------

class ProgressCallback(Protocol):
    """Minimal interface for pipeline progress reporting."""

    def on_stage_begin(self, stage: int, total_stages: int, detail: str) -> None: ...
    def on_stage_end(self, stage: int, total_stages: int, summary: str) -> None: ...
    def on_item_progress(self, current: int, total: int, label: str) -> None: ...
    def on_finish(self, summary: str) -> None: ...


class NullProgress:
    """No-op progress callback."""

    def on_stage_begin(self, stage: int, total_stages: int, detail: str) -> None:
        pass

    def on_stage_end(self, stage: int, total_stages: int, summary: str) -> None:
        pass

    def on_item_progress(self, current: int, total: int, label: str) -> None:
        pass

    def on_finish(self, summary: str) -> None:
        pass


class CLIProgressAdapter:
    """Adapts the new ProgressCallback protocol to the existing ProgressTracker."""

    def __init__(self, tracker) -> None:
        self._tracker = tracker

    def on_stage_begin(self, stage: int, total_stages: int, detail: str) -> None:
        self._tracker.begin_stage(stage, detail)

    def on_stage_end(self, stage: int, total_stages: int, summary: str) -> None:
        self._tracker.end_stage(stage, summary)

    def on_item_progress(self, current: int, total: int, label: str) -> None:
        self._tracker.update(current, total, label)

    def on_finish(self, summary: str) -> None:
        self._tracker.finish(summary)


# ------------------------------------------------------------------
# Pipeline result
# ------------------------------------------------------------------

class PipelineResult:
    """Holds the outcome of a pipeline run."""

    def __init__(self) -> None:
        self.opportunities_collected: int = 0
        self.opportunities_classified: int = 0
        self.opportunities_relevant: int = 0
        self.classified: list[ClassifiedOpportunity] = []
        self.elapsed_seconds: float = 0.0
        self.error: str | None = None


# ------------------------------------------------------------------
# Deduplication / filtering helpers (extracted from main.py)
# ------------------------------------------------------------------

def _deduplicate(opportunities: list[Opportunity]) -> list[Opportunity]:
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    unique: list[Opportunity] = []
    for opp in opportunities:
        url_key = opp.source_url.strip().lower()
        title_key = opp.title.strip().lower()
        if url_key and url_key in seen_urls:
            continue
        if title_key in seen_titles:
            continue
        if url_key:
            seen_urls.add(url_key)
        seen_titles.add(title_key)
        unique.append(opp)
    return unique


def _filter_future(opportunities: list[Opportunity]) -> list[Opportunity]:
    today = date.today()
    future: list[Opportunity] = []
    for opp in opportunities:
        if opp.opportunity_type == OpportunityType.EVENTO:
            future.append(opp)
        elif opp.deadline is None or opp.deadline >= today:
            future.append(opp)
    return future


def _filter_past_after_enrichment(
    classified: list[ClassifiedOpportunity],
) -> list[ClassifiedOpportunity]:
    today = date.today()
    return [
        item for item in classified
        if item.opportunity.deadline is None or item.opportunity.deadline >= today
    ]


def _normalise_event_title(title: str) -> str:
    t = title.strip().lower()
    t = re.sub(r"\b20\d{2}\b", "", t)
    t = re.sub(r"\b\d+(st|nd|rd|th|a|°)\b", "", t)
    t = re.sub(r"\b(edizione|edition|ed\.)\b", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\b(i{1,3}|iv|vi{0,3}|ix|xi{0,3})\b", "", t)
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _titles_are_similar(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    if len(a) > 8 and len(b) > 8 and (a in b or b in a):
        return True
    tokens_a, tokens_b = set(a.split()), set(b.split())
    if tokens_a and tokens_b:
        shorter = tokens_a if len(tokens_a) <= len(tokens_b) else tokens_b
        longer = tokens_b if len(tokens_a) <= len(tokens_b) else tokens_a
        if len(shorter) >= 2 and len(shorter & longer) / len(shorter) >= 0.7:
            return True
    return False


def _dedup_events_by_date(
    classified: list[ClassifiedOpportunity],
) -> list[ClassifiedOpportunity]:
    events = [c for c in classified if c.opportunity.opportunity_type == OpportunityType.EVENTO]
    non_events = [c for c in classified if c.opportunity.opportunity_type != OpportunityType.EVENTO]
    if len(events) <= 1:
        return classified

    date_groups: dict[str, list[ClassifiedOpportunity]] = defaultdict(list)
    no_date_events: list[ClassifiedOpportunity] = []
    for evt in events:
        dl = evt.opportunity.deadline
        if dl:
            date_groups[dl.isoformat()].append(evt)
        else:
            no_date_events.append(evt)

    kept_events: list[ClassifiedOpportunity] = []
    for group in date_groups.values():
        if len(group) == 1:
            kept_events.append(group[0])
            continue
        clusters: list[list[ClassifiedOpportunity]] = []
        for evt in group:
            norm = _normalise_event_title(evt.opportunity.title)
            merged = False
            for cluster in clusters:
                if _titles_are_similar(norm, _normalise_event_title(cluster[0].opportunity.title)):
                    cluster.append(evt)
                    merged = True
                    break
            if not merged:
                clusters.append([evt])
        for cluster in clusters:
            kept_events.append(max(cluster, key=lambda c: c.score))

    kept_norms = [_normalise_event_title(e.opportunity.title) for e in kept_events]
    for evt in no_date_events:
        norm = _normalise_event_title(evt.opportunity.title)
        if not any(_titles_are_similar(norm, kn) for kn in kept_norms):
            kept_events.append(evt)
            kept_norms.append(norm)

    return non_events + kept_events


def _patch_extracted_dates(classified: list[ClassifiedOpportunity]) -> None:
    for item in classified:
        if item.opportunity.deadline is not None:
            continue
        raw = item.classification.extracted_date
        if not raw:
            continue
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y"):
            try:
                item.opportunity.deadline = datetime.strptime(raw.strip()[:19], fmt).date()
                break
            except ValueError:
                continue


# ------------------------------------------------------------------
# Collection
# ------------------------------------------------------------------

async def _collect(settings: Settings, progress: ProgressCallback) -> list[Opportunity]:
    total_items = (
        (1 if settings.enable_ted else 0)
        + (1 if settings.enable_anac else 0)
        + (len(settings.event_feeds) if settings.enable_events else 0)
        + (len(settings.event_web_pages) if settings.enable_web_events else 0)
        + (len(settings.web_tender_pages) if settings.enable_web_tenders else 0)
        + (len(settings.web_search_queries) if settings.enable_web_search else 0)
    )

    completed_items = 0

    def _on_item(label: str) -> None:
        nonlocal completed_items
        completed_items += 1
        progress.on_item_progress(completed_items, total_items, label)

    collectors: list[tuple[str, asyncio.coroutines]] = []
    if settings.enable_ted:
        collectors.append(("TED", TEDCollector(settings, on_item_done=_on_item).collect()))
    if settings.enable_anac:
        collectors.append(("ANAC", ANACCollector(settings, on_item_done=_on_item).collect()))
    if settings.enable_events:
        collectors.append(("Events", EventsCollector(settings, on_item_done=_on_item).collect()))
    if settings.enable_web_events:
        collectors.append(("WebEvents", WebEventsCollector(settings, on_item_done=_on_item).collect()))
    if settings.enable_web_tenders:
        collectors.append(("WebTenders", WebTendersCollector(settings, on_item_done=_on_item).collect()))
    if settings.enable_web_search:
        collectors.append(("WebSearch", WebSearchCollector(settings, on_item_done=_on_item).collect()))

    if not collectors:
        logger.warning("All collectors are disabled")
        return []

    names = [c[0] for c in collectors]
    progress.on_stage_begin(1, TOTAL_STAGES, " + ".join(names))

    async def _run_one(name: str, coro) -> list[Opportunity]:
        try:
            return await coro
        except Exception as exc:
            logger.error("Collector %s failed: %s", name, exc)
            return []

    wrapped = [_run_one(name, coro) for name, coro in collectors]
    results = await asyncio.gather(*wrapped)

    opportunities: list[Opportunity] = []
    source_counts: list[str] = []
    for i, result in enumerate(results):
        if result:
            opportunities.extend(result)
            source_counts.append(f"{names[i]}: {len(result)}")

    summary = ", ".join(source_counts) if source_counts else "none"
    progress.on_stage_end(1, TOTAL_STAGES, f"{len(opportunities)} raccolti ({summary})")
    return opportunities


# ------------------------------------------------------------------
# Main pipeline
# ------------------------------------------------------------------

async def run_pipeline(
    settings: Settings,
    *,
    progress: ProgressCallback | None = None,
    use_cache: bool = True,
    excluded_urls: set[str] | None = None,
) -> PipelineResult:
    """Execute the full pipeline: collect -> deduplicate -> classify -> report.

    This is the main reusable entry point, called by both CLI and web app.
    ``excluded_urls`` contains normalised source URLs of items previously
    rejected by the user or already expired, so they are skipped.
    """
    if progress is None:
        progress = NullProgress()

    result = PipelineResult()
    start = time.monotonic()

    cache: PipelineCache | None = None
    resumed = False
    opportunities: list[Opportunity] = []

    if use_cache:
        cache = PipelineCache.find_latest_run()
        if cache:
            collected = cache.load_collected()
            if collected:
                logger.info("Resuming from cached run %s", cache.run_id)
                opportunities = collected
                resumed = True

    if not resumed:
        cache = PipelineCache()

        # 1. Collect
        opportunities = await _collect(settings, progress)
        if not opportunities:
            progress.on_finish("no data")
            result.elapsed_seconds = time.monotonic() - start
            return result

        # 2. Deduplicate + exclude rejected/expired agenda items
        progress.on_stage_begin(2, TOTAL_STAGES, "deduplicazione")
        before = len(opportunities)
        opportunities = _deduplicate(opportunities)
        dedup_removed = before - len(opportunities)
        if excluded_urls:
            before_excl = len(opportunities)
            opportunities = [
                o for o in opportunities
                if o.source_url.strip().lower() not in excluded_urls
            ]
            agenda_removed = before_excl - len(opportunities)
        else:
            agenda_removed = 0
        progress.on_stage_end(
            2, TOTAL_STAGES,
            f"{len(opportunities)} unici, {dedup_removed} duplicati rimossi"
            + (f", {agenda_removed} esclusi da agenda" if agenda_removed else ""),
        )

        # 3. Filter expired
        progress.on_stage_begin(3, TOTAL_STAGES, "rimozione scaduti")
        before = len(opportunities)
        opportunities = _filter_future(opportunities)
        progress.on_stage_end(
            3, TOTAL_STAGES,
            f"{len(opportunities)} attivi, {before - len(opportunities)} scaduti rimossi",
        )

        if not opportunities:
            progress.on_finish("no future items")
            result.elapsed_seconds = time.monotonic() - start
            return result

        cache.save_collected(opportunities)
        cache.save_metadata("collected", count=len(opportunities))
    else:
        for stage in (1, 2, 3):
            progress.on_stage_begin(stage, TOTAL_STAGES, "ripresa da cache")
            progress.on_stage_end(stage, TOTAL_STAGES, f"{len(opportunities)} dalla cache")

    result.opportunities_collected = len(opportunities)

    # 4. Classify
    progress.on_stage_begin(4, TOTAL_STAGES, f"classificazione con Gemini {settings.gemini_model}")

    class _ItemProgressAdapter:
        """Bridge classifier's progress to the pipeline callback."""
        def __init__(self, cb: ProgressCallback):
            self._cb = cb
        def update(self, current: int, total: int, label: str = "") -> None:
            self._cb.on_item_progress(current, total, label)

    classifier = GeminiClassifier(settings)
    item_adapter = _ItemProgressAdapter(progress)
    classified = await classifier.classify_all(
        opportunities, cache=cache, progress=item_adapter,
    )
    cache.save_metadata("classified", count=len(classified))
    _patch_extracted_dates(classified)
    progress.on_stage_end(4, TOTAL_STAGES, f"{len(classified)} classificati")

    # 5. Enrich dates
    missing_before = sum(1 for c in classified if c.opportunity.deadline is None)
    if missing_before:
        progress.on_stage_begin(
            5, TOTAL_STAGES, f"{missing_before} date mancanti da recuperare",
        )
        patched = await enrich_missing_dates(classified, settings, progress=item_adapter)
        progress.on_stage_end(5, TOTAL_STAGES, f"{patched} date estratte")
    else:
        progress.on_stage_begin(5, TOTAL_STAGES, "tutte le date presenti")
        progress.on_stage_end(5, TOTAL_STAGES, "nessun arricchimento")

    classified = _filter_past_after_enrichment(classified)
    classified = _dedup_events_by_date(classified)

    relevant = [c for c in classified if c.score >= settings.relevance_threshold]

    result.classified = classified
    result.opportunities_classified = len(classified)
    result.opportunities_relevant = len(relevant)

    # 6. Done (report generation is handled by the caller)
    progress.on_stage_begin(6, TOTAL_STAGES, "finalizzazione")
    result.elapsed_seconds = time.monotonic() - start
    cache.save_metadata("complete", count=len(classified), relevant=len(relevant))
    progress.on_stage_end(6, TOTAL_STAGES, f"{len(relevant)} rilevanti su {len(opportunities)}")
    progress.on_finish(f"{len(relevant)} rilevanti su {len(opportunities)} analizzati")

    return result
