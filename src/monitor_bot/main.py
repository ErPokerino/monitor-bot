"""CLI entry point – preserved for backward compatibility.

Uses the refactored pipeline engine from pipeline.py.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from monitor_bot.config import DEFAULT_CONFIG_PATH, ITALIA_CONFIG_PATH, TEST_CONFIG_PATH, Settings
from monitor_bot.notifier import Notifier
from monitor_bot.pipeline import CLIProgressAdapter, run_pipeline
from monitor_bot.progress import ProgressTracker

logger = logging.getLogger("monitor_bot")


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="monitor-bot",
        description="Tender & Event Monitor – collects, classifies and reports IT opportunities",
    )
    parser.add_argument(
        "--config", type=str, default=None,
        help="Path to a TOML config file (default: config.toml)",
    )
    parser.add_argument(
        "--test", action="store_true",
        help="Use config.test.toml (minimal scope for quick testing)",
    )
    parser.add_argument(
        "--italia", action="store_true",
        help="Use config.italia.toml (Italian-only scope)",
    )
    parser.add_argument(
        "--no-resume", action="store_true",
        help="Ignore cached runs, start fresh",
    )
    return parser.parse_args(argv)


def _resolve_config_path(args: argparse.Namespace) -> Path:
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
        logger.warning("Test config not found, falling back to %s", DEFAULT_CONFIG_PATH)
    if args.italia:
        if ITALIA_CONFIG_PATH.exists():
            logger.info("ITALIA MODE – loading %s", ITALIA_CONFIG_PATH)
            return ITALIA_CONFIG_PATH
        logger.warning("Italia config not found, falling back to %s", DEFAULT_CONFIG_PATH)
    return DEFAULT_CONFIG_PATH


async def run(args: argparse.Namespace) -> None:
    config_path = _resolve_config_path(args)
    settings = Settings(config_path)
    logger.info("Search scope: %s", settings.scope_summary())

    tracker = ProgressTracker()
    progress = CLIProgressAdapter(tracker)

    result = await run_pipeline(
        settings,
        progress=progress,
        use_cache=not args.no_resume,
    )

    if result.classified:
        notifier = Notifier(settings)
        report_path = notifier.notify(
            result.classified,
            total_analyzed=result.opportunities_collected,
            elapsed_seconds=result.elapsed_seconds,
        )
        if report_path:
            logger.info("Report saved to %s", report_path)


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
