"""REST API routes for application settings."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from monitor_bot.auth import AuthPrincipal, get_current_principal
from monitor_bot.database import get_session
from monitor_bot.db_models import UserRole
from monitor_bot.services import settings as svc

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
async def get_settings(
    db: AsyncSession = Depends(get_session),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    return await svc.get_all(db, user_id=principal.id, include_system=True)


@router.put("")
async def update_settings(
    data: dict[str, str],
    db: AsyncSession = Depends(get_session),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    try:
        return await svc.update_all(
            db,
            data,
            user_id=principal.id,
            is_admin=principal.role == UserRole.ADMIN,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
