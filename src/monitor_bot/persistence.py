"""Persistent cache for intermediate pipeline results.

Saves after each stage so the pipeline can resume from the last successful
checkpoint if interrupted (network failure, Gemini quota, Ctrl+C, etc.).

Cache layout (``output/.cache/``)::

    run_<timestamp>/
        collected.json          # raw opportunities after collection + dedup
        classified.json         # incrementally appended during classification
        classified_ids.json     # set of opportunity IDs already classified
        metadata.json           # run info: settings hash, stage, counts
"""

from __future__ import annotations

import json
import logging
import zoneinfo
from datetime import datetime
from pathlib import Path

_ROME = zoneinfo.ZoneInfo("Europe/Rome")

from monitor_bot.models import ClassifiedOpportunity, Opportunity

logger = logging.getLogger(__name__)

CACHE_DIR = Path("output") / ".cache"


class PipelineCache:
    """Read/write intermediate results to disk for resilience."""

    def __init__(self, run_id: str | None = None) -> None:
        if run_id:
            self._run_dir = CACHE_DIR / run_id
        else:
            self._run_dir = CACHE_DIR / f"run_{datetime.now(_ROME).strftime('%Y%m%d_%H%M%S')}"
        self._run_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Cache directory: %s", self._run_dir)

    @property
    def run_id(self) -> str:
        return self._run_dir.name

    # ------------------------------------------------------------------
    # Collected opportunities
    # ------------------------------------------------------------------

    def save_collected(self, opportunities: list[Opportunity]) -> None:
        path = self._run_dir / "collected.json"
        data = [opp.model_dump(mode="json") for opp in opportunities]
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Cache: saved %d collected opportunities", len(data))

    def load_collected(self) -> list[Opportunity] | None:
        path = self._run_dir / "collected.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        opportunities = [Opportunity.model_validate(d) for d in data]
        logger.info("Cache: loaded %d collected opportunities from disk", len(opportunities))
        return opportunities

    # ------------------------------------------------------------------
    # Classified opportunities (incremental)
    # ------------------------------------------------------------------

    def save_classified_one(self, item: ClassifiedOpportunity) -> None:
        """Append a single classified opportunity to the cache."""
        path = self._run_dir / "classified.json"
        # Append to a JSON-lines file (one JSON object per line)
        with path.open("a", encoding="utf-8") as f:
            f.write(item.model_dump_json() + "\n")

        # Also track the ID
        self._add_classified_id(item.opportunity.id)

    def load_classified(self) -> list[ClassifiedOpportunity]:
        """Load all previously classified opportunities."""
        path = self._run_dir / "classified.json"
        if not path.exists():
            return []
        results: list[ClassifiedOpportunity] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                results.append(ClassifiedOpportunity.model_validate_json(line))
            except Exception:
                logger.warning("Cache: skipping corrupt classified entry")
        logger.info("Cache: loaded %d classified opportunities from disk", len(results))
        return results

    def get_classified_ids(self) -> set[str]:
        """Return the set of opportunity IDs already classified."""
        path = self._run_dir / "classified_ids.json"
        if not path.exists():
            return set()
        return set(json.loads(path.read_text(encoding="utf-8")))

    def _add_classified_id(self, opp_id: str) -> None:
        ids = self.get_classified_ids()
        ids.add(opp_id)
        path = self._run_dir / "classified_ids.json"
        path.write_text(json.dumps(sorted(ids), ensure_ascii=False), encoding="utf-8")

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    def save_metadata(self, stage: str, **extra: object) -> None:
        path = self._run_dir / "metadata.json"
        data = {"stage": stage, "updated_at": datetime.now(_ROME).isoformat(), **extra}
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_metadata(self) -> dict | None:
        path = self._run_dir / "metadata.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # Discovery: find the most recent run to resume
    # ------------------------------------------------------------------

    @staticmethod
    def find_latest_run() -> PipelineCache | None:
        """Find the most recent cache run that can be resumed."""
        if not CACHE_DIR.exists():
            return None
        runs = sorted(CACHE_DIR.iterdir(), reverse=True)
        for run_dir in runs:
            if not run_dir.is_dir():
                continue
            meta_path = run_dir / "metadata.json"
            if meta_path.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                stage = meta.get("stage", "")
                if stage != "complete":
                    logger.info("Cache: found resumable run %s (stage=%s)", run_dir.name, stage)
                    return PipelineCache(run_id=run_dir.name)
        return None
