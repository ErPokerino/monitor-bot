"""REST API routes for Agenda management."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from monitor_bot.auth import AuthPrincipal, get_current_principal
from monitor_bot.database import get_session
from monitor_bot.schemas import (
    AgendaEnrollRequest,
    AgendaEvaluateRequest,
    AgendaFeedbackRequest,
    AgendaItemOut,
    AgendaShareMarkSeenRequest,
    AgendaShareRequest,
    AgendaMarkSeenRequest,
    AgendaNotificationsOut,
    AgendaStatsOut,
    SharedAgendaItemOut,
)
from monitor_bot.services import agenda as agenda_svc
from monitor_bot.services import audit as audit_svc
from monitor_bot.services import users as user_svc

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
    principal: AuthPrincipal = Depends(get_current_principal),
):
    return await agenda_svc.list_agenda(
        db,
        principal.id,
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
async def agenda_stats(
    db: AsyncSession = Depends(get_session),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    return await agenda_svc.get_stats(db, principal.id)


@router.get("/expiring", response_model=list[AgendaItemOut])
async def agenda_expiring(
    days: int = 30,
    db: AsyncSession = Depends(get_session),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    return await agenda_svc.get_expiring(db, principal.id, days=days)


@router.get("/past-events", response_model=list[AgendaItemOut])
async def agenda_past_events(
    db: AsyncSession = Depends(get_session),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    return await agenda_svc.list_agenda(db, principal.id, tab="past_events")


@router.patch("/{item_id}/evaluate", response_model=AgendaItemOut)
async def evaluate_item(
    item_id: int,
    body: AgendaEvaluateRequest,
    db: AsyncSession = Depends(get_session),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    item = await agenda_svc.evaluate_item(db, principal.id, item_id, body.evaluation)
    if not item:
        raise HTTPException(404, "Item not found")
    return item


@router.patch("/{item_id}/enroll", response_model=AgendaItemOut)
async def enroll_item(
    item_id: int,
    body: AgendaEnrollRequest,
    db: AsyncSession = Depends(get_session),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    item = await agenda_svc.set_enrollment(
        db,
        principal.id,
        item_id,
        is_enrolled=body.is_enrolled,
    )
    if not item:
        raise HTTPException(404, "Item not found")
    return item


@router.patch("/{item_id}/feedback", response_model=AgendaItemOut)
async def feedback_item(
    item_id: int,
    body: AgendaFeedbackRequest,
    db: AsyncSession = Depends(get_session),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    item = await agenda_svc.set_feedback(
        db,
        principal.id,
        item_id,
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
    principal: AuthPrincipal = Depends(get_current_principal),
):
    count = await agenda_svc.mark_seen(
        db,
        principal.id,
        ids=body.ids,
        all_items=body.all,
    )
    return {"updated": count}


@router.post("/{item_id}/share")
async def share_item(
    item_id: int,
    body: AgendaShareRequest,
    db: AsyncSession = Depends(get_session),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    recipient = await user_svc.get_user_by_username(db, body.recipient_username.strip())
    if recipient is None or not recipient.is_active:
        raise HTTPException(404, "Recipient not found")

    try:
        share = await agenda_svc.share_item(
            db,
            owner_user_id=principal.id,
            item_id=item_id,
            recipient_user_id=recipient.id,
            note=body.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if share is None:
        raise HTTPException(404, "Item not found")

    await audit_svc.log_action(
        db,
        actor_user_id=principal.id,
        action="agenda.share.create",
        target_type="agenda_item",
        target_id=str(item_id),
        payload={"recipient_user_id": recipient.id},
    )
    return {"status": "ok", "share_id": share.id}


@router.get("/shared", response_model=list[SharedAgendaItemOut])
async def list_shared(
    limit: int = 200,
    offset: int = 0,
    db: AsyncSession = Depends(get_session),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    return await agenda_svc.list_shared_with_me(
        db,
        recipient_user_id=principal.id,
        limit=limit,
        offset=offset,
    )


@router.get("/notifications", response_model=AgendaNotificationsOut)
async def list_notifications(
    limit: int = 10,
    db: AsyncSession = Depends(get_session),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    safe_limit = max(1, min(limit, 50))
    agenda_unseen = await agenda_svc.list_unseen_notifications(
        db,
        principal.id,
        limit=safe_limit,
    )
    shared_unseen = await agenda_svc.list_shared_with_me(
        db,
        recipient_user_id=principal.id,
        only_unseen=True,
        limit=safe_limit,
    )
    return {
        "agenda_unseen": agenda_unseen,
        "shared_unseen": shared_unseen,
    }


@router.get("/shared/stats")
async def shared_stats(
    db: AsyncSession = Depends(get_session),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    count = await agenda_svc.get_shared_unseen_count(db, principal.id)
    return {"shared_unseen_count": count}


@router.post("/shared/mark-seen")
async def mark_shared_seen(
    body: AgendaShareMarkSeenRequest,
    db: AsyncSession = Depends(get_session),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    updated = await agenda_svc.mark_shared_seen(
        db,
        recipient_user_id=principal.id,
        ids=body.ids,
        all_items=body.all,
    )
    return {"updated": updated}
