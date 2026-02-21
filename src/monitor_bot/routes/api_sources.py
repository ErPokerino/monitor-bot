"""REST API routes for MonitoredSource CRUD."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

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
):
    return await svc.list_sources(db, category=category, active_only=active_only)


@router.post("", response_model=SourceOut, status_code=201)
async def create_source(
    data: SourceCreate,
    db: AsyncSession = Depends(get_session),
):
    if await svc.source_url_exists(db, data.url):
        raise HTTPException(400, "URL already exists")
    return await svc.create_source(db, data)


@router.get("/{source_id}", response_model=SourceOut)
async def get_source(
    source_id: int,
    db: AsyncSession = Depends(get_session),
):
    source = await svc.get_source(db, source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    return source


@router.patch("/{source_id}", response_model=SourceOut)
async def update_source(
    source_id: int,
    data: SourceUpdate,
    db: AsyncSession = Depends(get_session),
):
    source = await svc.update_source(db, source_id, data)
    if not source:
        raise HTTPException(404, "Source not found")
    return source


@router.post("/{source_id}/toggle", response_model=SourceOut)
async def toggle_source(
    source_id: int,
    db: AsyncSession = Depends(get_session),
):
    source = await svc.toggle_source(db, source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    return source


@router.delete("/{source_id}", status_code=204)
async def delete_source(
    source_id: int,
    db: AsyncSession = Depends(get_session),
):
    if not await svc.delete_source(db, source_id):
        raise HTTPException(404, "Source not found")
