"""REST API routes for Agenda management."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from monitor_bot.database import get_session
from monitor_bot.schemas import (
    AgendaEnrollRequest,
    AgendaEvaluateRequest,
    AgendaFeedbackRequest,
    AgendaItemOut,
    AgendaMarkSeenRequest,
    AgendaStatsOut,
)
from monitor_bot.services import agenda as agenda_svc

router = APIRouter(prefix="/api/agenda", tags=["agenda"])


@router.get("", response_model=list[AgendaItemOut])
async def list_agenda(
    tab: str = "pending",
    type: str | None = None,
    category: str | None = None,
    enrolled: bool | None = None,
    search: str | None = None,
    sort: str = "first_seen_at",
    limit: int = 200,
    offset: int = 0,
    db: AsyncSession = Depends(get_session),
):
    return await agenda_svc.list_agenda(
        db,
        tab=tab,
        opp_type=type,
        category=category,
        enrolled=enrolled,
        search=search,
        sort=sort,
        limit=limit,
        offset=offset,
    )


@router.get("/stats", response_model=AgendaStatsOut)
async def agenda_stats(db: AsyncSession = Depends(get_session)):
    return await agenda_svc.get_stats(db)


@router.get("/expiring", response_model=list[AgendaItemOut])
async def agenda_expiring(
    days: int = 30,
    db: AsyncSession = Depends(get_session),
):
    return await agenda_svc.get_expiring(db, days=days)


@router.get("/past-events", response_model=list[AgendaItemOut])
async def agenda_past_events(db: AsyncSession = Depends(get_session)):
    return await agenda_svc.list_agenda(db, tab="past_events")


@router.patch("/{item_id}/evaluate", response_model=AgendaItemOut)
async def evaluate_item(
    item_id: int,
    body: AgendaEvaluateRequest,
    db: AsyncSession = Depends(get_session),
):
    item = await agenda_svc.evaluate_item(db, item_id, body.evaluation)
    if not item:
        raise HTTPException(404, "Item not found")
    return item


@router.patch("/{item_id}/enroll", response_model=AgendaItemOut)
async def enroll_item(
    item_id: int,
    body: AgendaEnrollRequest,
    db: AsyncSession = Depends(get_session),
):
    item = await agenda_svc.set_enrollment(db, item_id, is_enrolled=body.is_enrolled)
    if not item:
        raise HTTPException(404, "Item not found")
    return item


@router.patch("/{item_id}/feedback", response_model=AgendaItemOut)
async def feedback_item(
    item_id: int,
    body: AgendaFeedbackRequest,
    db: AsyncSession = Depends(get_session),
):
    item = await agenda_svc.set_feedback(
        db, item_id,
        recommend=body.recommend,
        return_next_year=body.return_next_year,
    )
    if not item:
        raise HTTPException(404, "Item not found")
    return item


@router.post("/mark-seen")
async def mark_seen(
    body: AgendaMarkSeenRequest,
    db: AsyncSession = Depends(get_session),
):
    count = await agenda_svc.mark_seen(db, ids=body.ids, all_items=body.all)
    return {"updated": count}
