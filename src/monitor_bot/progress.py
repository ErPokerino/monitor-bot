"""Lightweight progress tracking for pipeline stages.

Prints a progress bar to stderr and logs milestones. Works in both
interactive terminals (in-place updates) and non-interactive environments
(periodic log lines).
"""

from __future__ import annotations

import logging
import sys
import time

logger = logging.getLogger(__name__)

# How many steps in the overall pipeline
TOTAL_STAGES = 6
_STAGE_NAMES = {
    1: "Collecting",
    2: "Deduplicating",
    3: "Filtering past items",
    4: "Classifying",
    5: "Enriching dates",
    6: "Generating report",
}

_BAR_WIDTH = 30


class ProgressTracker:
    """Track and display pipeline progress."""

    def __init__(self) -> None:
        self._current_stage = 0
        self._is_tty = hasattr(sys.stderr, "isatty") and sys.stderr.isatty()
        self._start_time = time.monotonic()
        self._stage_start = self._start_time

    # ------------------------------------------------------------------
    # Stage-level progress
    # ------------------------------------------------------------------

    def begin_stage(self, stage: int, detail: str = "") -> None:
        """Mark the start of a pipeline stage (1-based)."""
        self._current_stage = stage
        self._stage_start = time.monotonic()
        name = _STAGE_NAMES.get(stage, f"Stage {stage}")
        msg = f"[{stage}/{TOTAL_STAGES}] {name}"
        if detail:
            msg += f" – {detail}"
        logger.info(">>> %s", msg)
        self._print_stage_bar(stage, 0, "starting...")

    def end_stage(self, stage: int, summary: str = "") -> None:
        elapsed = time.monotonic() - self._stage_start
        name = _STAGE_NAMES.get(stage, f"Stage {stage}")
        msg = f"[{stage}/{TOTAL_STAGES}] {name} done in {elapsed:.1f}s"
        if summary:
            msg += f" – {summary}"
        self._print_stage_bar(stage, 100, "done")
        self._write("\n")  # move past the progress line
        logger.info("<<< %s", msg)

    # ------------------------------------------------------------------
    # Item-level progress (for classification loop)
    # ------------------------------------------------------------------

    def update(self, current: int, total: int, label: str = "") -> None:
        """Update the item-level progress within the current stage."""
        if total == 0:
            return
        pct = current * 100 // total
        short = label[:50] if label else ""
        self._print_stage_bar(self._current_stage, pct, f"{current}/{total} {short}")

        # Also log every 10% milestone (for non-TTY environments)
        if total >= 10 and current % max(1, total // 10) == 0:
            logger.info(
                "  progress: %d/%d (%d%%) %s",
                current, total, pct, short,
            )

    # ------------------------------------------------------------------
    # Overall summary
    # ------------------------------------------------------------------

    def elapsed_total(self) -> float:
        """Return total elapsed seconds since pipeline start."""
        return time.monotonic() - self._start_time

    def finish(self, summary: str = "") -> float:
        """Mark pipeline as complete and return total elapsed seconds."""
        elapsed = time.monotonic() - self._start_time
        msg = f"Pipeline complete in {elapsed:.1f}s"
        if summary:
            msg += f" – {summary}"
        logger.info("=== %s ===", msg)
        return elapsed

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _print_stage_bar(self, stage: int, pct: int, detail: str) -> None:
        """Print an in-place progress bar to stderr."""
        if not self._is_tty:
            return

        pct = max(0, min(100, pct))
        overall_pct = ((stage - 1) * 100 + pct) * 100 // (TOTAL_STAGES * 100)

        filled = _BAR_WIDTH * pct // 100
        bar = "█" * filled + "░" * (_BAR_WIDTH - filled)

        line = f"\r  [{bar}] {pct:3d}% | Overall {overall_pct:2d}% | {detail}"
        # Pad to clear previous longer lines
        self._write(line.ljust(100))

    @staticmethod
    def _write(text: str) -> None:
        try:
            sys.stderr.write(text)
            sys.stderr.flush()
        except OSError:
            pass
