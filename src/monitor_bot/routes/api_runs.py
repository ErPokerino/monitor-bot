"""REST API routes for SearchRun management + progress polling."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from monitor_bot.config import Settings
from monitor_bot.database import async_session, get_session
from monitor_bot.db_models import RunStatus, SearchRun
from monitor_bot.pipeline import ProgressCallback, run_pipeline
from monitor_bot.schemas import BatchDeleteRequest, BatchDeleteResponse, RunDetailOut, RunOut
from monitor_bot.services import queries as query_svc
from monitor_bot.services import runs as run_svc
from monitor_bot.services import settings as settings_svc
from monitor_bot.services import sources as source_svc
from monitor_bot.services.email import _render_report_html, send_run_notification

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/runs", tags=["runs"])

_current_run_id: int | None = None
_current_task: asyncio.Task[None] | None = None


class DBProgress(ProgressCallback):
    """Writes progress events to the search_runs.progress_json column.

    Works across process boundaries (Cloud Run Job writes, Service reads).
    """

    def __init__(self, run_id: int) -> None:
        self._run_id = run_id
        self._stage_starts: dict[int, float] = {}
        self._state: dict[str, Any] = {"stages": [], "finished": False}
        self._dirty = False

    async def _flush(self) -> None:
        if not self._dirty:
            return
        self._dirty = False
        try:
            async with async_session() as db:
                await db.execute(
                    sa_update(SearchRun)
                    .where(SearchRun.id == self._run_id)
                    .values(progress_json=json.dumps(self._state, ensure_ascii=False))
                )
                await db.commit()
        except Exception:
            logger.warning("Failed to flush progress for run %d", self._run_id, exc_info=True)

    def on_stage_begin(self, stage: int, total_stages: int, detail: str) -> None:
        self._stage_starts[stage] = time.monotonic()
        self._state["current_stage"] = stage
        self._state["total_stages"] = total_stages
        self._state["stage_detail"] = detail
        stage_entry = {"id": stage, "status": "running", "detail": detail}
        existing = {s["id"] for s in self._state["stages"]}
        if stage not in existing:
            self._state["stages"].append(stage_entry)
        self._state.pop("item_current", None)
        self._state.pop("item_total", None)
        self._state.pop("item_label", None)
        self._dirty = True
        asyncio.ensure_future(self._flush())

    def on_stage_end(self, stage: int, total_stages: int, summary: str) -> None:
        start = self._stage_starts.get(stage, time.monotonic())
        elapsed = round(time.monotonic() - start, 1)
        for s in self._state["stages"]:
            if s["id"] == stage:
                s["status"] = "done"
                s["summary"] = summary
                s["elapsed_seconds"] = elapsed
        self._dirty = True
        asyncio.ensure_future(self._flush())

    def on_item_progress(self, current: int, total: int, label: str) -> None:
        self._state["item_current"] = current
        self._state["item_total"] = total
        self._state["item_label"] = label
        self._dirty = True
        asyncio.ensure_future(self._flush())

    def on_finish(self, summary: str) -> None:
        self._state["finished"] = True
        self._state["finish_summary"] = summary
        self._dirty = True
        asyncio.ensure_future(self._flush())


# ------------------------------------------------------------------
# REST endpoints
# ------------------------------------------------------------------

@router.get("", response_model=list[RunOut])
async def list_runs(
    limit: int = 50,
    db: AsyncSession = Depends(get_session),
):
    return await run_svc.list_runs(db, limit=limit)


@router.get("/status")
async def run_status():
    """Check whether a pipeline is currently running."""
    return {"running": _current_run_id is not None, "run_id": _current_run_id}


@router.get("/{run_id}", response_model=RunDetailOut)
async def get_run(
    run_id: int,
    db: AsyncSession = Depends(get_session),
):
    run = await run_svc.get_run(db, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return run


@router.get("/{run_id}/progress")
async def get_run_progress(
    run_id: int,
    db: AsyncSession = Depends(get_session),
):
    """Poll endpoint for real-time pipeline progress."""
    run = await db.get(SearchRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    progress = json.loads(run.progress_json) if run.progress_json else {}
    return {
        "run_id": run_id,
        "status": run.status.value,
        "progress": progress,
    }


@router.post("/start", response_model=RunOut)
async def start_run(db: AsyncSession = Depends(get_session)):
    """Launch a new pipeline run in the background."""
    global _current_run_id, _current_task

    if _current_run_id is not None:
        raise HTTPException(409, "A pipeline is already running")

    settings = Settings()
    run = await run_svc.create_run(db, config_snapshot={"scope": settings.scope_summary()})
    _current_run_id = run.id
    _current_task = asyncio.create_task(_execute_pipeline(run.id, settings))
    logger.info("Background task created for run %d", run.id)
    return run


@router.post("/stop")
async def stop_run():
    """Cancel the currently running pipeline."""
    global _current_run_id, _current_task

    if _current_run_id is None or _current_task is None:
        raise HTTPException(404, "No pipeline is currently running")

    run_id = _current_run_id
    _current_task.cancel()
    logger.info("Cancellation requested for pipeline run %d", run_id)
    return {"cancelled": True, "run_id": run_id}


@router.delete("/{run_id}", status_code=204)
async def delete_run(
    run_id: int,
    db: AsyncSession = Depends(get_session),
):
    if not await run_svc.delete_run(db, run_id):
        raise HTTPException(404, "Run not found")


@router.post("/delete-batch", response_model=BatchDeleteResponse)
async def delete_runs_batch(
    body: BatchDeleteRequest,
    db: AsyncSession = Depends(get_session),
):
    deleted = await run_svc.delete_runs(db, body.ids)
    return BatchDeleteResponse(deleted=deleted)


# ------------------------------------------------------------------
# Pipeline execution
# ------------------------------------------------------------------

async def _execute_pipeline(run_id: int, settings: Settings) -> None:
    """Background task that runs the full pipeline and persists results."""
    global _current_run_id, _current_task
    logger.info("Pipeline task started for run %d", run_id)

    await asyncio.sleep(0.1)

    progress = DBProgress(run_id)

    try:
        async with async_session() as db:
            active_sources = await source_svc.list_sources(db, active_only=True)
            active_queries = await query_svc.list_queries(db, active_only=True)
            all_settings = await settings_svc.get_all(db)

        settings.apply_db_overrides(active_sources, active_queries)

        threshold_str = all_settings.get("relevance_threshold")
        if threshold_str is not None:
            settings.relevance_threshold = int(threshold_str)

        profile_parts: list[str] = []
        if all_settings.get("company_name"):
            profile_parts.append(f"Azienda: {all_settings['company_name']}")
        if all_settings.get("company_sector"):
            profile_parts.append(f"Settore: {all_settings['company_sector']}")
        if all_settings.get("company_competencies"):
            profile_parts.append(f"Competenze: {all_settings['company_competencies']}")
        budget_min = all_settings.get("company_budget_min", "")
        budget_max = all_settings.get("company_budget_max", "")
        if budget_min or budget_max:
            profile_parts.append(f"Budget target: {budget_min} - {budget_max} EUR")
        if all_settings.get("company_regions"):
            profile_parts.append(f"Regioni operative: {all_settings['company_regions']}")
        if all_settings.get("company_description"):
            profile_parts.append(f"\n{all_settings['company_description']}")
        if all_settings.get("search_scope_description"):
            profile_parts.append(f"Ambito ricerca: {all_settings['search_scope_description']}")
        if profile_parts:
            settings.company_profile = "\n".join(profile_parts)

        timeout_minutes = int(all_settings.get("pipeline_timeout_minutes", "60"))

        logger.info("Pipeline using %d active sources, %d active queries, threshold=%d, timeout=%dmin",
                     len(active_sources), len(active_queries), settings.relevance_threshold, timeout_minutes)

        result = await asyncio.wait_for(
            run_pipeline(settings, progress=progress, use_cache=False),
            timeout=timeout_minutes * 60,
        )

        async with async_session() as db:
            if result.classified:
                await run_svc.save_results(db, run_id, result.classified)
            await run_svc.complete_run(
                db, run_id,
                status=RunStatus.COMPLETED,
                total_collected=result.opportunities_collected,
                total_classified=result.opportunities_classified,
                total_relevant=result.opportunities_relevant,
                elapsed_seconds=result.elapsed_seconds,
            )

        email_raw = all_settings.get("notification_emails", "")
        email_list = [e.strip() for e in email_raw.split(",") if e.strip()]
        if email_list:
            import os
            app_url = os.environ.get("APP_URL", "")
            report_html = None
            async with async_session() as db:
                run_obj = await run_svc.get_run(db, run_id)
                if run_obj and run_obj.results:
                    report_html = _render_report_html(run_id, run_obj.results)
            await send_run_notification(
                run_id=run_id,
                total_collected=result.opportunities_collected,
                total_classified=result.opportunities_classified,
                total_relevant=result.opportunities_relevant,
                elapsed_seconds=result.elapsed_seconds,
                recipients=email_list,
                app_url=app_url or None,
                report_html=report_html,
            )

    except asyncio.CancelledError:
        logger.info("Pipeline run %d was cancelled by user", run_id)
        async with async_session() as db:
            await run_svc.complete_run(db, run_id, status=RunStatus.CANCELLED)
        progress.on_finish("Esecuzione interrotta dall'utente")

    except TimeoutError:
        logger.warning("Pipeline run %d timed out", run_id)
        async with async_session() as db:
            await run_svc.complete_run(db, run_id, status=RunStatus.FAILED)
        progress.on_finish("Timeout: esecuzione interrotta per superamento del limite di tempo")

    except Exception:
        logger.exception("Pipeline run %d failed", run_id)
        async with async_session() as db:
            await run_svc.complete_run(db, run_id, status=RunStatus.FAILED)
        progress.on_finish("errore durante l'esecuzione")

    finally:
        _current_run_id = None
        _current_task = None
