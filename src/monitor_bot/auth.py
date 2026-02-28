"""Authentication and authorization utilities."""

from __future__ import annotations

import hashlib
import os
import secrets
from dataclasses import dataclass
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from monitor_bot.database import get_session
from monitor_bot.db_models import AuthSession, User, UserRole, _now_rome

_password_hasher = PasswordHasher()

SESSION_TTL_HOURS = int(os.environ.get("AUTH_SESSION_TTL_HOURS", "12"))
MAX_FAILED_ATTEMPTS = int(os.environ.get("AUTH_MAX_FAILED_ATTEMPTS", "5"))
LOCK_MINUTES = int(os.environ.get("AUTH_LOGIN_LOCK_MINUTES", "15"))


@dataclass(slots=True)
class AuthPrincipal:
    id: int
    username: str
    display_name: str
    role: UserRole


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def create_session_token() -> str:
    return secrets.token_urlsafe(48)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    if not authorization.startswith("Bearer "):
        return None
    token = authorization.removeprefix("Bearer ").strip()
    return token or None


def principal_from_user(user: User) -> AuthPrincipal:
    return AuthPrincipal(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
    )


async def validate_token(db: AsyncSession, token: str) -> AuthPrincipal | None:
    now = _now_rome()
    token_hash = hash_session_token(token)
    stmt = (
        select(AuthSession, User)
        .join(User, User.id == AuthSession.user_id)
        .where(
            and_(
                AuthSession.token_hash == token_hash,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > now,
                User.is_active.is_(True),
            ),
        )
        .limit(1)
    )
    row = (await db.execute(stmt)).first()
    if row is None:
        return None

    session, user = row
    if session.last_seen_at < now - timedelta(minutes=5):
        session.last_seen_at = now
        await db.commit()
    return principal_from_user(user)


async def issue_session(db: AsyncSession, user: User) -> str:
    token = create_session_token()
    now = _now_rome()
    session = AuthSession(
        user_id=user.id,
        token_hash=hash_session_token(token),
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(hours=SESSION_TTL_HOURS),
    )
    db.add(session)
    await db.commit()
    return token


async def revoke_session(db: AsyncSession, token: str) -> bool:
    now = _now_rome()
    token_hash = hash_session_token(token)
    stmt = select(AuthSession).where(
        and_(AuthSession.token_hash == token_hash, AuthSession.revoked_at.is_(None)),
    )
    session = (await db.execute(stmt)).scalar_one_or_none()
    if session is None:
        return False
    session.revoked_at = now
    await db.commit()
    return True


async def revoke_all_user_sessions(db: AsyncSession, user_id: int) -> int:
    now = _now_rome()
    stmt = select(AuthSession).where(
        and_(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)),
    )
    sessions = list((await db.execute(stmt)).scalars().all())
    for item in sessions:
        item.revoked_at = now
    if sessions:
        await db.commit()
    return len(sessions)


async def get_current_principal(
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> AuthPrincipal:
    principal = getattr(request.state, "auth_principal", None)
    if principal is not None:
        return principal

    token = extract_bearer_token(request.headers.get("authorization"))
    if token is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    principal = await validate_token(db, token)
    if principal is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    request.state.auth_principal = principal
    return principal


async def require_admin(
    principal: AuthPrincipal = Depends(get_current_principal),
) -> AuthPrincipal:
    if principal.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return principal

