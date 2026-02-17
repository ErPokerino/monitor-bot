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
    progress.end_stage(1, f"{len(opportunities)} total ({summary})")
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
    progress.end_stage(2, f"{len(unique)} unique, {removed} duplicates removed")
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
    progress.begin_stage(3, "filtering past items")
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
    progress.end_stage(3, f"{len(future)} current, {removed} expired items removed")
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


def _dedup_events_by_date(classified: list[ClassifiedOpportunity]) -> list[ClassifiedOpportunity]:
    """Remove duplicate events that refer to the same underlying event.

    Multiple RSS articles from the same source often announce the same event.
    After date enrichment, we can detect these: if two events share the same
    (deadline date, source feed) they're almost certainly about the same event.
    We keep the one with the highest relevance score.

    For events without a date, we also check if one title is a substring of
    another (e.g. "FORUM PA 2026" appears in both titles).
    """
    events = [c for c in classified if c.opportunity.opportunity_type == OpportunityType.EVENTO]
    non_events = [c for c in classified if c.opportunity.opportunity_type != OpportunityType.EVENTO]

    if len(events) <= 1:
        return classified

    # Group events by (date, source_feed/authority)
    from collections import defaultdict
    groups: dict[tuple, list[ClassifiedOpportunity]] = defaultdict(list)
    no_date_events: list[ClassifiedOpportunity] = []

    for evt in events:
        dl = evt.opportunity.deadline
        src = evt.opportunity.contracting_authority.strip().lower()
        if dl:
            groups[(dl.isoformat(), src)].append(evt)
        else:
            no_date_events.append(evt)

    kept_events: list[ClassifiedOpportunity] = []
    removed = 0

    for key, group in groups.items():
        if len(group) == 1:
            kept_events.append(group[0])
        else:
            best = max(group, key=lambda c: c.score)
            kept_events.append(best)
            removed += len(group) - 1

    # For events without dates, check title-substring duplicates against kept events
    kept_titles_lower = [e.opportunity.title.strip().lower() for e in kept_events]
    for evt in no_date_events:
        title_lower = evt.opportunity.title.strip().lower()
        is_dup = False
        for kept_title in kept_titles_lower:
            if len(title_lower) > 10 and len(kept_title) > 10:
                if title_lower in kept_title or kept_title in title_lower:
                    is_dup = True
                    break
        if is_dup:
            removed += 1
        else:
            kept_events.append(evt)
            kept_titles_lower.append(title_lower)

    if removed:
        logger.info("Event dedup: removed %d duplicate event(s) about the same event", removed)

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
        progress.begin_stage(1, "skipped (resumed from cache)")
        progress.end_stage(1, f"{len(opportunities)} loaded from cache")
        progress.begin_stage(2, "skipped (resumed from cache)")
        progress.end_stage(2, f"{len(opportunities)} opportunities")
        progress.begin_stage(3, "skipped (resumed from cache)")
        progress.end_stage(3, f"{len(opportunities)} opportunities")

    # 4. Classify
    progress.begin_stage(4, f"Gemini {settings.gemini_model}")
    classifier = GeminiClassifier(settings)
    classified = await classifier.classify_all(
        opportunities,
        cache=cache,
        progress=progress,
    )
    cache.save_metadata("classified", count=len(classified))
    _patch_extracted_dates(classified)
    progress.end_stage(4, f"{len(classified)} classified")

    # 5. Enrich missing dates by fetching source pages
    missing_before = sum(1 for c in classified if c.opportunity.deadline is None)
    if missing_before:
        progress.begin_stage(5, f"enriching {missing_before} missing dates via page fetch")
        patched = await enrich_missing_dates(classified, settings)
        progress.end_stage(5, f"{patched} dates extracted from source pages")
    else:
        progress.begin_stage(5, "all dates already present")
        progress.end_stage(5, "nothing to enrich")

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
        progress.end_stage(6, f"report saved to {result_path}")
    else:
        progress.end_stage(6, "report sent via email")

    cache.save_metadata("complete", count=len(classified), relevant=len(relevant))
    progress.finish(f"{len(relevant)} relevant out of {len(opportunities)} analyzed")


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
