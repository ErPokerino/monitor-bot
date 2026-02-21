"""Dashboard stats API endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from monitor_bot.database import get_session
from monitor_bot.schemas import DashboardOut
from monitor_bot.services import queries as query_svc
from monitor_bot.services import runs as run_svc
from monitor_bot.services import sources as source_svc

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardOut)
async def dashboard_stats(db: AsyncSession = Depends(get_session)):
    active_sources = await source_svc.count_sources(db, active_only=True)
    total_sources = await source_svc.count_sources(db)
    active_queries = await query_svc.count_queries(db, active_only=True)
    total_queries = await query_svc.count_queries(db)
    last_run = await run_svc.get_latest_run(db)
    recent_runs = await run_svc.list_runs(db, limit=5)
    running = await run_svc.get_running(db)

    return DashboardOut(
        active_sources=active_sources,
        total_sources=total_sources,
        active_queries=active_queries,
        total_queries=total_queries,
        last_run=last_run,
        recent_runs=list(recent_runs),
        is_running=running is not None,
    )
