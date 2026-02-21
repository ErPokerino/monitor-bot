"""REST API routes for SearchRun management + WebSocket progress."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from monitor_bot.config import Settings
from monitor_bot.database import async_session, get_session
from monitor_bot.db_models import RunStatus
from monitor_bot.pipeline import ProgressCallback, run_pipeline
from monitor_bot.schemas import BatchDeleteRequest, BatchDeleteResponse, RunDetailOut, RunOut
from monitor_bot.services import queries as query_svc
from monitor_bot.services import runs as run_svc
from monitor_bot.services import settings as settings_svc
from monitor_bot.services import sources as source_svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/runs", tags=["runs"])

_active_connections: list[WebSocket] = []
_current_run_id: int | None = None
_current_task: asyncio.Task[None] | None = None

_message_queue: asyncio.Queue[str] = asyncio.Queue()
_recent_messages: list[str] = []


class WebSocketProgress(ProgressCallback):
    """Sends pipeline progress events via a shared message queue.

    Tracks per-stage timing and buffers messages so that late-joining
    WebSocket clients can catch up on missed progress updates.
    """

    def __init__(self, run_id: int) -> None:
        self._run_id = run_id
        self._stage_starts: dict[int, float] = {}
        _recent_messages.clear()

    def _enqueue(self, data: dict[str, Any]) -> None:
        data["run_id"] = self._run_id
        message = json.dumps(data, ensure_ascii=False)
        _recent_messages.append(message)
        try:
            _message_queue.put_nowait(message)
        except asyncio.QueueFull:
            logger.warning("WebSocket message queue full, dropping message")

    def on_stage_begin(self, stage: int, total_stages: int, detail: str) -> None:
        self._stage_starts[stage] = time.monotonic()
        self._enqueue({
            "type": "stage_begin",
            "stage": stage,
            "total_stages": total_stages,
            "detail": detail,
        })

    def on_stage_end(self, stage: int, total_stages: int, summary: str) -> None:
        start = self._stage_starts.get(stage, time.monotonic())
        elapsed = round(time.monotonic() - start, 1)
        self._enqueue({
            "type": "stage_end",
            "stage": stage,
            "total_stages": total_stages,
            "summary": summary,
            "elapsed_seconds": elapsed,
        })

    def on_item_progress(self, current: int, total: int, label: str) -> None:
        self._enqueue({
            "type": "item_progress",
            "current": current,
            "total": total,
            "label": label,
        })

    def on_finish(self, summary: str) -> None:
        self._enqueue({
            "type": "finished",
            "summary": summary,
        })


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

    progress = WebSocketProgress(run_id)

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
        if all_settings.get("company_certifications"):
            profile_parts.append(f"Certificazioni: {all_settings['company_certifications']}")
        budget_min = all_settings.get("company_budget_min", "")
        budget_max = all_settings.get("company_budget_max", "")
        if budget_min or budget_max:
            profile_parts.append(f"Budget target: {budget_min} - {budget_max} EUR")
        if all_settings.get("company_regions"):
            profile_parts.append(f"Regioni operative: {all_settings['company_regions']}")
        if all_settings.get("search_scope_description"):
            profile_parts.append(f"Ambito ricerca: {all_settings['search_scope_description']}")
        if profile_parts:
            settings.company_profile = "\n".join(profile_parts)

        logger.info("Pipeline using %d active sources, %d active queries, threshold=%d",
                     len(active_sources), len(active_queries), settings.relevance_threshold)

        result = await run_pipeline(settings, progress=progress, use_cache=False)

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

    except asyncio.CancelledError:
        logger.info("Pipeline run %d was cancelled by user", run_id)
        async with async_session() as db:
            await run_svc.complete_run(db, run_id, status=RunStatus.CANCELLED)
        progress.on_finish("Esecuzione interrotta dall'utente")

    except Exception:
        logger.exception("Pipeline run %d failed", run_id)
        async with async_session() as db:
            await run_svc.complete_run(db, run_id, status=RunStatus.FAILED)
        progress.on_finish("errore durante l'esecuzione")

    finally:
        _current_run_id = None
        _current_task = None
        _recent_messages.clear()


# ------------------------------------------------------------------
# WebSocket broadcaster
# ------------------------------------------------------------------

async def _ws_broadcaster() -> None:
    """Background task that drains the message queue and pushes to all WS clients."""
    logger.info("WS broadcaster started")
    while True:
        message = await _message_queue.get()
        if not _active_connections:
            continue
        disconnected: list[WebSocket] = []
        for ws in _active_connections:
            try:
                await ws.send_text(message)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            _active_connections.remove(ws)


_broadcaster_task: asyncio.Task[None] | None = None


def _ensure_broadcaster() -> None:
    """Start the broadcaster coroutine if not already running."""
    global _broadcaster_task
    if _broadcaster_task is None or _broadcaster_task.done():
        _broadcaster_task = asyncio.get_running_loop().create_task(_ws_broadcaster())


@router.websocket("/ws")
async def progress_websocket(websocket: WebSocket):
    """WebSocket endpoint for real-time pipeline progress."""
    await websocket.accept()
    _active_connections.append(websocket)
    _ensure_broadcaster()
    logger.info("WebSocket client connected (total: %d)", len(_active_connections))

    for msg in list(_recent_messages):
        try:
            await websocket.send_text(msg)
        except Exception:
            break

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in _active_connections:
            _active_connections.remove(websocket)
        logger.info("WebSocket client disconnected (total: %d)", len(_active_connections))
