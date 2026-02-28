"""REST API routes for MonitoredSource CRUD."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from monitor_bot.auth import AuthPrincipal, get_current_principal
from monitor_bot.database import get_session
from monitor_bot.db_models import SourceCategory
from monitor_bot.schemas import SourceCreate, SourceOut, SourceUpdate
from monitor_bot.services import sources as svc

router = APIRouter(prefix="/api/sources", tags=["sources"])


@router.get("", response_model=list[SourceOut])
async def list_sources(
    category: SourceCategory | None = None,
    active_only: bool = False,
    db: AsyncSession = Depends(get_session),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    return await svc.list_sources(
        db,
        owner_user_id=principal.id,
        category=category,
        active_only=active_only,
    )


@router.post("", response_model=SourceOut, status_code=201)
async def create_source(
    data: SourceCreate,
    db: AsyncSession = Depends(get_session),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    if await svc.source_url_exists(db, data.url, owner_user_id=principal.id):
        raise HTTPException(400, "URL already exists")
    return await svc.create_source(db, principal.id, data)


@router.post("/toggle-all")
async def toggle_all_sources(
    body: dict,
    db: AsyncSession = Depends(get_session),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    active = bool(body.get("active", True))
    count = await svc.set_all_active(db, owner_user_id=principal.id, active=active)
    return {"updated": count, "active": active}


@router.get("/{source_id}", response_model=SourceOut)
async def get_source(
    source_id: int,
    db: AsyncSession = Depends(get_session),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    source = await svc.get_source(db, source_id, owner_user_id=principal.id)
    if not source:
        raise HTTPException(404, "Source not found")
    return source


@router.patch("/{source_id}", response_model=SourceOut)
async def update_source(
    source_id: int,
    data: SourceUpdate,
    db: AsyncSession = Depends(get_session),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    source = await svc.update_source(db, source_id, data, owner_user_id=principal.id)
    if not source:
        raise HTTPException(404, "Source not found")
    return source


@router.post("/{source_id}/toggle", response_model=SourceOut)
async def toggle_source(
    source_id: int,
    db: AsyncSession = Depends(get_session),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    source = await svc.toggle_source(db, source_id, owner_user_id=principal.id)
    if not source:
        raise HTTPException(404, "Source not found")
    return source


@router.delete("/{source_id}", status_code=204)
async def delete_source(
    source_id: int,
    db: AsyncSession = Depends(get_session),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    if not await svc.delete_source(db, source_id, owner_user_id=principal.id):
        raise HTTPException(404, "Source not found")
