"""Pipeline orchestrator and CLI entry point."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date, datetime
from pathlib import Path

from monitor_bot.classifier import GeminiClassifier
from monitor_bot.collectors.anac import ANACCollector
from monitor_bot.collectors.events import EventsCollector
from monitor_bot.collectors.ted import TEDCollector
from monitor_bot.collectors.web_events import WebEventsCollector
from monitor_bot.collectors.web_search import WebSearchCollector
from monitor_bot.collectors.web_tenders import WebTendersCollector
from monitor_bot.config import DEFAULT_CONFIG_PATH, ITALIA_CONFIG_PATH, TEST_CONFIG_PATH, Settings
from monitor_bot.date_enricher import enrich_missing_dates
from monitor_bot.models import ClassifiedOpportunity, Opportunity, OpportunityType
from monitor_bot.notifier import Notifier
from monitor_bot.persistence import PipelineCache
from monitor_bot.progress import ProgressTracker

logger = logging.getLogger("monitor_bot")


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


# ------------------------------------------------------------------
# CLI argument parsing
# ------------------------------------------------------------------

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="monitor-bot",
        description="Tender & Event Monitor – collects, classifies and reports IT opportunities",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to a TOML config file (default: config.toml)",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Use config.test.toml (minimal scope for quick testing)",
    )
    parser.add_argument(
        "--italia",
        action="store_true",
        help="Use config.italia.toml (Italian-only scope: TED IT, ANAC, regional tenders, Italian events)",
    )
    parser.add_argument(
        "--no-resume", action="store_true", help="Ignore cached runs, start fresh",
    )
    return parser.parse_args(argv)


def _resolve_config_path(args: argparse.Namespace) -> Path:
    """Determine which config file to use based on CLI flags."""
    if args.config:
        p = Path(args.config)
        if not p.exists():
            logger.error("Config file not found: %s", p)
            sys.exit(1)
        return p
    if args.test:
        if TEST_CONFIG_PATH.exists():
            logger.info("TEST MODE – loading %s", TEST_CONFIG_PATH)
            return TEST_CONFIG_PATH
        logger.warning("Test config %s not found, falling back to %s", TEST_CONFIG_PATH, DEFAULT_CONFIG_PATH)
    if args.italia:
        if ITALIA_CONFIG_PATH.exists():
            logger.info("ITALIA MODE – loading %s", ITALIA_CONFIG_PATH)
            return ITALIA_CONFIG_PATH
        logger.warning("Italia config %s not found, falling back to %s", ITALIA_CONFIG_PATH, DEFAULT_CONFIG_PATH)
    return DEFAULT_CONFIG_PATH


# ------------------------------------------------------------------
# Pipeline steps
# ------------------------------------------------------------------

async def _collect(settings: Settings, progress: ProgressTracker) -> list[Opportunity]:
    """Run enabled collectors concurrently and merge results."""
    collector_names: list[str] = []
    tasks = []

    if settings.enable_ted:
        tasks.append(TEDCollector(settings).collect())
        collector_names.append("TED")
    if settings.enable_anac:
        tasks.append(ANACCollector(settings).collect())
        collector_names.append("ANAC")
    if settings.enable_events:
        tasks.append(EventsCollector(settings).collect())
        collector_names.append("Events")
    if settings.enable_web_events:
        tasks.append(WebEventsCollector(settings).collect())
        collector_names.append("WebEvents")
    if settings.enable_web_tenders:
        tasks.append(WebTendersCollector(settings).collect())
        collector_names.append("WebTenders")
    if settings.enable_web_search:
        tasks.append(WebSearchCollector(settings).collect())
        collector_names.append("WebSearch")

    if not tasks:
        logger.warning("All collectors are disabled – nothing to collect")
        return []

    progress.begin_stage(1, " + ".join(collector_names))
    results = await asyncio.gather(*tasks, return_exceptions=True)

    opportunities: list[Opportunity] = []
    source_counts: list[str] = []
    for result in results:
        if isinstance(result, BaseException):
            logger.error("A collector failed: %s", result)
        else:
            opportunities.extend(result)
            if result:
                src = result[0].source.value
                source_counts.append(f"{src}: {len(result)}")

    summary = ", ".join(source_counts) if source_counts else "none"
    progress.end_stage(1, f"{len(opportunities)} raccolti ({summary})")
    return opportunities


def _deduplicate(
    opportunities: list[Opportunity], progress: ProgressTracker
) -> list[Opportunity]:
    """Remove duplicates based on source URL or normalised title."""
    progress.begin_stage(2)

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

    removed = len(opportunities) - len(unique)
    progress.end_stage(2, f"{len(unique)} unici, {removed} duplicati rimossi")
    return unique


def _filter_future(
    opportunities: list[Opportunity], progress: ProgressTracker
) -> list[Opportunity]:
    """Keep only items that are still current/open.

    Rules:
    - Bando / Concorso: keep if deadline >= today, or if no deadline is set
      (we can't determine expiry, so we keep them to be safe).
    - Evento: always kept – the events collector already applies a lookback
      filter, and event articles are inherently forward-looking announcements.
    """
    progress.begin_stage(3, "rimozione bandi/eventi scaduti")
    today = date.today()
    future: list[Opportunity] = []

    for opp in opportunities:
        if opp.opportunity_type == OpportunityType.EVENTO:
            # Events are always kept (already filtered by lookback in collector)
            future.append(opp)
        else:
            # Tenders: keep if deadline is in the future, or no deadline set
            if opp.deadline is None or opp.deadline >= today:
                future.append(opp)

    removed = len(opportunities) - len(future)
    progress.end_stage(3, f"{len(future)} attivi, {removed} scaduti rimossi")
    return future


def _filter_past_after_enrichment(
    classified: list[ClassifiedOpportunity],
) -> list[ClassifiedOpportunity]:
    """Remove any item (including events) whose deadline is in the past.

    This runs *after* date enrichment so that events that now have a concrete
    past date are correctly discarded.
    """
    today = date.today()
    kept: list[ClassifiedOpportunity] = []
    removed = 0
    for item in classified:
        dl = item.opportunity.deadline
        if dl is not None and dl < today:
            removed += 1
            logger.debug(
                "Dropping past item: %s (deadline %s)",
                item.opportunity.title[:60], dl.isoformat(),
            )
        else:
            kept.append(item)
    if removed:
        logger.info(
            "Post-enrichment filter: removed %d expired item(s)", removed,
        )
    return kept


def _normalise_event_title(title: str) -> str:
    """Reduce an event title to key words for fuzzy matching.

    Strips common noise (edition numbers, year, punctuation, case) so that
    "AI WEEK 2026" and "AI WEEK - 7th Edition" compare as similar.
    """
    import re as _re
    t = title.strip().lower()
    # Remove year patterns like "2025", "2026"
    t = _re.sub(r"\b20\d{2}\b", "", t)
    # Remove edition patterns like "7th", "7a", "VII", "edizione", "edition"
    t = _re.sub(r"\b\d+(st|nd|rd|th|a|°)\b", "", t)
    t = _re.sub(r"\b(edizione|edition|ed\.)\b", "", t, flags=_re.IGNORECASE)
    # Remove Roman numerals standing alone
    t = _re.sub(r"\b(i{1,3}|iv|vi{0,3}|ix|xi{0,3})\b", "", t)
    # Remove punctuation and collapse whitespace
    t = _re.sub(r"[^a-z0-9\s]", " ", t)
    t = _re.sub(r"\s+", " ", t).strip()
    return t


def _titles_are_similar(a: str, b: str) -> bool:
    """Check if two normalised titles are similar enough to be the same event."""
    if not a or not b:
        return False
    # Exact match after normalisation
    if a == b:
        return True
    # Substring containment (at least 10 chars to avoid false positives)
    if len(a) > 8 and len(b) > 8:
        if a in b or b in a:
            return True
    # Token overlap: if >=70% of the shorter title's tokens are in the longer one
    tokens_a = set(a.split())
    tokens_b = set(b.split())
    if tokens_a and tokens_b:
        shorter = tokens_a if len(tokens_a) <= len(tokens_b) else tokens_b
        longer = tokens_b if len(tokens_a) <= len(tokens_b) else tokens_a
        if len(shorter) >= 2:
            overlap = len(shorter & longer) / len(shorter)
            if overlap >= 0.7:
                return True
    return False


def _dedup_events_by_date(classified: list[ClassifiedOpportunity]) -> list[ClassifiedOpportunity]:
    """Remove duplicate events that refer to the same underlying event.

    Uses a multi-strategy approach:
    1. Events with the same date are grouped together (regardless of source).
       Within each date group, titles are compared with fuzzy matching to
       detect duplicates like "AI WEEK 2026" vs "AI WEEK - 7th Edition".
    2. Events without dates are checked via title similarity against all kept events.
    The event with the highest relevance score is kept in each duplicate group.
    """
    events = [c for c in classified if c.opportunity.opportunity_type == OpportunityType.EVENTO]
    non_events = [c for c in classified if c.opportunity.opportunity_type != OpportunityType.EVENTO]

    if len(events) <= 1:
        return classified

    from collections import defaultdict
    date_groups: dict[str, list[ClassifiedOpportunity]] = defaultdict(list)
    no_date_events: list[ClassifiedOpportunity] = []

    for evt in events:
        dl = evt.opportunity.deadline
        if dl:
            date_groups[dl.isoformat()].append(evt)
        else:
            no_date_events.append(evt)

    kept_events: list[ClassifiedOpportunity] = []
    removed = 0

    for date_key, group in date_groups.items():
        if len(group) == 1:
            kept_events.append(group[0])
            continue

        # Within this date group, cluster by title similarity
        clusters: list[list[ClassifiedOpportunity]] = []
        for evt in group:
            norm = _normalise_event_title(evt.opportunity.title)
            merged = False
            for cluster in clusters:
                representative_norm = _normalise_event_title(cluster[0].opportunity.title)
                if _titles_are_similar(norm, representative_norm):
                    cluster.append(evt)
                    merged = True
                    break
            if not merged:
                clusters.append([evt])

        for cluster in clusters:
            best = max(cluster, key=lambda c: c.score)
            kept_events.append(best)
            removed += len(cluster) - 1

    # For events without dates, check title similarity against all kept events
    kept_norms = [_normalise_event_title(e.opportunity.title) for e in kept_events]
    for evt in no_date_events:
        norm = _normalise_event_title(evt.opportunity.title)
        is_dup = any(_titles_are_similar(norm, kn) for kn in kept_norms)
        if is_dup:
            removed += 1
        else:
            kept_events.append(evt)
            kept_norms.append(norm)

    if removed:
        logger.info("Event dedup: rimossi %d evento/i duplicato/i", removed)

    return non_events + kept_events


def _patch_extracted_dates(classified: list[ClassifiedOpportunity]) -> None:
    """Populate missing deadlines from Gemini-extracted dates.

    For opportunities where `deadline` is None but the classifier found
    a date in the text, parse and set it on the opportunity.
    """
    patched = 0
    for item in classified:
        if item.opportunity.deadline is not None:
            continue
        raw = item.classification.extracted_date
        if not raw:
            continue
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y"):
            try:
                item.opportunity.deadline = datetime.strptime(raw.strip()[:19], fmt).date()
                patched += 1
                break
            except ValueError:
                continue
    if patched:
        logger.info("Patched %d opportunities with Gemini-extracted dates", patched)


async def run(args: argparse.Namespace) -> None:
    """Execute the full pipeline: collect -> deduplicate -> classify -> notify."""
    config_path = _resolve_config_path(args)
    settings = Settings(config_path)

    logger.info("Search scope: %s", settings.scope_summary())

    progress = ProgressTracker()

    # Check for a resumable run
    cache: PipelineCache | None = None
    resumed = False
    opportunities: list[Opportunity] = []

    if not args.no_resume:
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
            logger.warning("No opportunities collected – nothing to do.")
            progress.finish("no data")
            return

        # 2. Deduplicate
        opportunities = _deduplicate(opportunities, progress)

        # 2b. Filter past items
        opportunities = _filter_future(opportunities, progress)

        if not opportunities:
            logger.warning("All opportunities are in the past – nothing to classify.")
            progress.finish("no future items")
            return

        # Save checkpoint
        cache.save_collected(opportunities)
        cache.save_metadata("collected", count=len(opportunities))
    else:
        # Fast-forward stage display for resumed runs
        progress.begin_stage(1, "saltata (ripresa da cache)")
        progress.end_stage(1, f"{len(opportunities)} caricati da cache")
        progress.begin_stage(2, "saltata (ripresa da cache)")
        progress.end_stage(2, f"{len(opportunities)} opportunità")
        progress.begin_stage(3, "saltata (ripresa da cache)")
        progress.end_stage(3, f"{len(opportunities)} opportunità")

    # 4. Classify
    progress.begin_stage(4, f"classificazione con Gemini {settings.gemini_model}")
    classifier = GeminiClassifier(settings)
    classified = await classifier.classify_all(
        opportunities,
        cache=cache,
        progress=progress,
    )
    cache.save_metadata("classified", count=len(classified))
    _patch_extracted_dates(classified)
    progress.end_stage(4, f"{len(classified)} classificati")

    # 5. Enrich missing dates by fetching source pages
    missing_before = sum(1 for c in classified if c.opportunity.deadline is None)
    if missing_before:
        progress.begin_stage(5, f"{missing_before} date mancanti da recuperare")
        patched = await enrich_missing_dates(classified, settings, progress=progress)
        progress.end_stage(5, f"{patched} date estratte dalle pagine sorgente")
    else:
        progress.begin_stage(5, "tutte le date già presenti")
        progress.end_stage(5, "nessun arricchimento necessario")

    # 5b. Remove items that now have a past deadline after enrichment
    classified = _filter_past_after_enrichment(classified)

    # 5c. Deduplicate events that refer to the same underlying event
    classified = _dedup_events_by_date(classified)

    relevant = [c for c in classified if c.score >= settings.relevance_threshold]
    logger.info(
        "%d opportunities above relevance threshold (%d)",
        len(relevant),
        settings.relevance_threshold,
    )

    # 6. Notify
    progress.begin_stage(6)
    notifier = Notifier(settings)
    elapsed_seconds = progress.elapsed_total()
    result_path = notifier.notify(
        classified,
        total_analyzed=len(opportunities),
        elapsed_seconds=elapsed_seconds,
    )
    if result_path:
        progress.end_stage(6, f"report salvato in {result_path}")
    else:
        progress.end_stage(6, "report inviato via email")

    cache.save_metadata("complete", count=len(classified), relevant=len(relevant))
    progress.finish(f"{len(relevant)} rilevanti su {len(opportunities)} analizzati")


def cli() -> None:
    """CLI entry point (called by ``uv run monitor-bot``)."""
    _configure_logging()
    args = _parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        logger.info("Interrupted by user – partial results are cached for resume")
        sys.exit(130)
    except Exception:
        logger.exception("Pipeline failed – partial results are cached for resume")
        sys.exit(1)


if __name__ == "__main__":
    cli()
