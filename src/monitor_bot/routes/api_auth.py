"""Authentication routes."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from monitor_bot.auth import (
    LOCK_MINUTES,
    MAX_FAILED_ATTEMPTS,
    SESSION_TTL_HOURS,
    AuthPrincipal,
    extract_bearer_token,
    get_current_principal,
    issue_session,
    revoke_session,
    verify_password,
)
from monitor_bot.database import get_session
from monitor_bot.db_models import User, UserRole, _now_rome
from monitor_bot.schemas import UserDirectoryItemOut
from monitor_bot.services import users as user_svc

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=255)


class LoginResponse(BaseModel):
    token: str
    username: str
    display_name: str
    role: UserRole
    expires_in_seconds: int
    must_reset_password: bool


class MeResponse(BaseModel):
    username: str
    display_name: str
    role: UserRole
    must_reset_password: bool


class LogoutResponse(BaseModel):
    status: str = "ok"


async def _get_user_by_username(db: AsyncSession, username: str) -> User | None:
    stmt = select(User).where(User.username == username).limit(1)
    return (await db.execute(stmt)).scalar_one_or_none()


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_session),
) -> LoginResponse:
    now = _now_rome()
    user = await _get_user_by_username(db, body.username.strip())
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if user.locked_until is not None and user.locked_until > now:
        raise HTTPException(
            status_code=429,
            detail=f"Too many attempts. Retry in {LOCK_MINUTES} minutes.",
        )

    if not verify_password(body.password, user.password_hash):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
            user.failed_login_attempts = 0
            user.locked_until = now + timedelta(minutes=LOCK_MINUTES)
        await db.commit()
        raise HTTPException(status_code=401, detail="Invalid credentials")

    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = now
    token = await issue_session(db, user)
    return LoginResponse(
        token=token,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        expires_in_seconds=SESSION_TTL_HOURS * 3600,
        must_reset_password=user.must_reset_password,
    )


@router.get("/me", response_model=MeResponse)
async def me(
    principal: AuthPrincipal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_session),
) -> MeResponse:
    user = await db.get(User, principal.id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return MeResponse(
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        must_reset_password=user.must_reset_password,
    )


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    _: AuthPrincipal = Depends(get_current_principal),
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_session),
) -> LogoutResponse:
    token = extract_bearer_token(authorization)
    if token:
        await revoke_session(db, token)
    return LogoutResponse()


@router.get("/users", response_model=list[UserDirectoryItemOut])
async def list_directory_users(
    q: str | None = None,
    limit: int = 20,
    principal: AuthPrincipal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_session),
):
    safe_limit = max(1, min(limit, 50))
    users = await user_svc.search_active_users(
        db,
        query=q,
        exclude_user_id=principal.id,
        limit=safe_limit,
    )
    return users
