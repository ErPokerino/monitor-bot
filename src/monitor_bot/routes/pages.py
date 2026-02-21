"""Server-rendered HTML page routes."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from monitor_bot.database import get_session
from monitor_bot.services import queries as query_svc
from monitor_bot.services import runs as run_svc
from monitor_bot.services import sources as source_svc

router = APIRouter(tags=["pages"])


@router.get("/")
async def dashboard(request: Request, db: AsyncSession = Depends(get_session)):
    active_sources = await source_svc.count_sources(db, active_only=True)
    total_sources = await source_svc.count_sources(db)
    active_queries = await query_svc.count_queries(db, active_only=True)
    total_queries = await query_svc.count_queries(db)
    last_run = await run_svc.get_latest_run(db)
    runs = await run_svc.list_runs(db, limit=5)
    running = await run_svc.get_running(db)
    return request.app.state.templates.TemplateResponse("dashboard.html", {
        "request": request,
        "active_sources": active_sources,
        "total_sources": total_sources,
        "active_queries": active_queries,
        "total_queries": total_queries,
        "last_run": last_run,
        "recent_runs": runs,
        "is_running": running is not None,
    })


@router.get("/sources")
async def sources_page(request: Request, db: AsyncSession = Depends(get_session)):
    sources = await source_svc.list_sources(db)
    return request.app.state.templates.TemplateResponse("sources.html", {
        "request": request,
        "sources": sources,
    })


@router.get("/queries")
async def queries_page(request: Request, db: AsyncSession = Depends(get_session)):
    queries = await query_svc.list_queries(db)
    return request.app.state.templates.TemplateResponse("queries.html", {
        "request": request,
        "queries": queries,
    })


@router.get("/run")
async def run_page(request: Request, db: AsyncSession = Depends(get_session)):
    running = await run_svc.get_running(db)
    return request.app.state.templates.TemplateResponse("run.html", {
        "request": request,
        "is_running": running is not None,
        "current_run_id": running.id if running else None,
    })


@router.get("/history")
async def history_page(request: Request, db: AsyncSession = Depends(get_session)):
    runs = await run_svc.list_runs(db)
    return request.app.state.templates.TemplateResponse("history.html", {
        "request": request,
        "runs": runs,
    })


@router.get("/history/{run_id}")
async def run_detail_page(
    run_id: int,
    request: Request,
    db: AsyncSession = Depends(get_session),
):
    run = await run_svc.get_run(db, run_id)
    if not run:
        return request.app.state.templates.TemplateResponse("404.html", {
            "request": request,
        }, status_code=404)
    return request.app.state.templates.TemplateResponse("run_detail.html", {
        "request": request,
        "run": run,
        "today": date.today(),
    })
