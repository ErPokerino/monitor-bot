"""REST API routes for application settings."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from monitor_bot.database import get_session
from monitor_bot.services import settings as svc

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
async def get_settings(db: AsyncSession = Depends(get_session)):
    return await svc.get_all(db)


@router.put("")
async def update_settings(
    data: dict[str, str],
    db: AsyncSession = Depends(get_session),
):
    return await svc.update_all(db, data)
