"""REST API routes for SearchQuery CRUD."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from monitor_bot.database import get_session
from monitor_bot.db_models import SourceCategory
from monitor_bot.schemas import QueryCreate, QueryOut, QueryUpdate
from monitor_bot.services import queries as svc

router = APIRouter(prefix="/api/queries", tags=["queries"])


@router.get("", response_model=list[QueryOut])
async def list_queries(
    category: SourceCategory | None = None,
    active_only: bool = False,
    db: AsyncSession = Depends(get_session),
):
    return await svc.list_queries(db, category=category, active_only=active_only)


@router.post("", response_model=QueryOut, status_code=201)
async def create_query(
    data: QueryCreate,
    db: AsyncSession = Depends(get_session),
):
    if await svc.query_text_exists(db, data.query_text):
        raise HTTPException(400, "Query already exists")
    return await svc.create_query(db, data)


@router.get("/{query_id}", response_model=QueryOut)
async def get_query(
    query_id: int,
    db: AsyncSession = Depends(get_session),
):
    query = await svc.get_query(db, query_id)
    if not query:
        raise HTTPException(404, "Query not found")
    return query


@router.patch("/{query_id}", response_model=QueryOut)
async def update_query(
    query_id: int,
    data: QueryUpdate,
    db: AsyncSession = Depends(get_session),
):
    query = await svc.update_query(db, query_id, data)
    if not query:
        raise HTTPException(404, "Query not found")
    return query


@router.post("/{query_id}/toggle", response_model=QueryOut)
async def toggle_query(
    query_id: int,
    db: AsyncSession = Depends(get_session),
):
    query = await svc.toggle_query(db, query_id)
    if not query:
        raise HTTPException(404, "Query not found")
    return query


@router.delete("/{query_id}", status_code=204)
async def delete_query(
    query_id: int,
    db: AsyncSession = Depends(get_session),
):
    if not await svc.delete_query(db, query_id):
        raise HTTPException(404, "Query not found")
