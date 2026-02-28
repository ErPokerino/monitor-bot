"""Admin-only API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from monitor_bot.auth import AuthPrincipal, require_admin, revoke_all_user_sessions
from monitor_bot.database import get_session
from monitor_bot.db_models import AuthSession, RunStatus, SearchRun, User, _now_rome
from monitor_bot.schemas import AdminOverviewOut, AdminUserCreateRequest, AdminUserOut
from monitor_bot.services import audit as audit_svc
from monitor_bot.services import users as user_svc

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
)


@router.get("/users", response_model=list[AdminUserOut])
async def list_users(
    db: AsyncSession = Depends(get_session),
    _: AuthPrincipal = Depends(require_admin),
):
    return await user_svc.list_users(db, include_inactive=True)


@router.post("/users", response_model=AdminUserOut, status_code=201)
async def create_user(
    body: AdminUserCreateRequest,
    db: AsyncSession = Depends(get_session),
    principal: AuthPrincipal = Depends(require_admin),
):
    try:
        user = await user_svc.create_user(
            db,
            username=body.username.strip(),
            password=body.password,
            display_name=body.name,
            role=body.role,
            must_reset_password=body.must_reset_password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await audit_svc.log_action(
        db,
        actor_user_id=principal.id,
        action="admin.user.create",
        target_type="user",
        target_id=str(user.id),
        payload={"username": user.username, "role": user.role.value},
    )
    return user


@router.delete("/users/{user_id}")
async def deactivate_user(
    user_id: int,
    db: AsyncSession = Depends(get_session),
    principal: AuthPrincipal = Depends(require_admin),
):
    if user_id == principal.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account")

    user = await user_svc.get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if user.role.value == "admin":
        admins = await user_svc.count_active_admins(db)
        if admins <= 1 and user.is_active:
            raise HTTPException(status_code=400, detail="At least one active admin is required")

    user = await user_svc.deactivate_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    await revoke_all_user_sessions(db, user_id)
    await audit_svc.log_action(
        db,
        actor_user_id=principal.id,
        action="admin.user.deactivate",
        target_type="user",
        target_id=str(user_id),
    )
    return {"status": "ok"}


@router.post("/users/{user_id}/activate")
async def activate_user(
    user_id: int,
    db: AsyncSession = Depends(get_session),
    principal: AuthPrincipal = Depends(require_admin),
):
    user = await user_svc.get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    user = await user_svc.activate_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    await audit_svc.log_action(
        db,
        actor_user_id=principal.id,
        action="admin.user.activate",
        target_type="user",
        target_id=str(user_id),
    )
    return {"status": "ok"}


@router.delete("/users/{user_id}/hard")
async def hard_delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_session),
    principal: AuthPrincipal = Depends(require_admin),
):
    if user_id == principal.id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")

    existing = await user_svc.get_user(db, user_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="User not found")
    deleted_username = existing.username

    if existing.role.value == "admin":
        admins = await user_svc.count_active_admins(db)
        if existing.is_active and admins <= 1:
            raise HTTPException(status_code=400, detail="At least one active admin is required")

    user = await user_svc.delete_user_permanently(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    await audit_svc.log_action(
        db,
        actor_user_id=principal.id,
        action="admin.user.delete",
        target_type="user",
        target_id=str(user_id),
        payload={"username": deleted_username},
    )
    return {"status": "ok"}


@router.get("/overview", response_model=AdminOverviewOut)
async def overview(
    db: AsyncSession = Depends(get_session),
    _: AuthPrincipal = Depends(require_admin),
):
    total_users = (
        await db.execute(select(func.count(User.id)))
    ).scalar_one()
    active_users = (
        await db.execute(select(func.count(User.id)).where(User.is_active.is_(True)))
    ).scalar_one()
    active_sessions = (
        await db.execute(
            select(func.count(AuthSession.id)).where(
                and_(
                    AuthSession.revoked_at.is_(None),
                    AuthSession.expires_at > _now_rome(),
                ),
            ),
        )
    ).scalar_one()
    running_runs = (
        await db.execute(
            select(func.count(SearchRun.id)).where(SearchRun.status == RunStatus.RUNNING),
        )
    ).scalar_one()
    return AdminOverviewOut(
        total_users=total_users,
        active_users=active_users,
        active_sessions=active_sessions,
        running_runs=running_runs,
    )

