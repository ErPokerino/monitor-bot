"""User management service layer."""

from __future__ import annotations

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from monitor_bot.auth import hash_password
from monitor_bot.db_models import (
    AgendaItem,
    AgendaShare,
    AuditLog,
    AuthSession,
    MonitoredSource,
    SearchQuery,
    SearchResult,
    SearchRun,
    User,
    UserRole,
    UserSetting,
    _now_rome,
)


async def get_user(db: AsyncSession, user_id: int) -> User | None:
    return await db.get(User, user_id)


async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    stmt = select(User).where(User.username == username).limit(1)
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_users(db: AsyncSession, *, include_inactive: bool = True) -> list[User]:
    stmt = select(User).order_by(User.created_at.asc())
    if not include_inactive:
        stmt = stmt.where(User.is_active.is_(True))
    return list((await db.execute(stmt)).scalars().all())


async def search_active_users(
    db: AsyncSession,
    *,
    query: str | None = None,
    exclude_user_id: int | None = None,
    limit: int = 20,
) -> list[User]:
    stmt = select(User).where(User.is_active.is_(True))
    if exclude_user_id is not None:
        stmt = stmt.where(User.id != exclude_user_id)
    if query:
        q = f"%{query.strip()}%"
        stmt = stmt.where(or_(User.username.ilike(q), User.display_name.ilike(q)))
    stmt = stmt.order_by(User.display_name.asc(), User.username.asc()).limit(limit)
    return list((await db.execute(stmt)).scalars().all())


async def create_user(
    db: AsyncSession,
    *,
    username: str,
    password: str,
    display_name: str | None = None,
    role: UserRole = UserRole.USER,
    must_reset_password: bool = False,
) -> User:
    existing = await get_user_by_username(db, username)
    if existing is not None:
        raise ValueError("Username already exists")

    user = User(
        username=username.strip(),
        display_name=(display_name or username).strip(),
        password_hash=hash_password(password),
        role=role,
        is_active=True,
        must_reset_password=must_reset_password,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def set_user_password(db: AsyncSession, user_id: int, password: str) -> User | None:
    user = await db.get(User, user_id)
    if user is None:
        return None
    user.password_hash = hash_password(password)
    user.must_reset_password = False
    user.failed_login_attempts = 0
    user.locked_until = None
    user.updated_at = _now_rome()
    await db.commit()
    await db.refresh(user)
    return user


async def deactivate_user(db: AsyncSession, user_id: int) -> User | None:
    user = await db.get(User, user_id)
    if user is None:
        return None
    user.is_active = False
    user.updated_at = _now_rome()
    await db.commit()
    await db.refresh(user)
    return user


async def activate_user(db: AsyncSession, user_id: int) -> User | None:
    user = await db.get(User, user_id)
    if user is None:
        return None
    user.is_active = True
    user.updated_at = _now_rome()
    await db.commit()
    await db.refresh(user)
    return user


async def delete_user_permanently(db: AsyncSession, user_id: int) -> User | None:
    user = await db.get(User, user_id)
    if user is None:
        return None

    await db.execute(
        delete(AgendaShare).where(
            or_(
                AgendaShare.sender_user_id == user_id,
                AgendaShare.recipient_user_id == user_id,
            ),
        ),
    )
    await db.execute(delete(AgendaItem).where(AgendaItem.owner_user_id == user_id))
    await db.execute(delete(SearchResult).where(SearchResult.owner_user_id == user_id))
    await db.execute(delete(SearchRun).where(SearchRun.owner_user_id == user_id))
    await db.execute(delete(SearchQuery).where(SearchQuery.owner_user_id == user_id))
    await db.execute(delete(MonitoredSource).where(MonitoredSource.owner_user_id == user_id))
    await db.execute(delete(UserSetting).where(UserSetting.user_id == user_id))
    await db.execute(delete(AuthSession).where(AuthSession.user_id == user_id))
    await db.execute(delete(AuditLog).where(AuditLog.actor_user_id == user_id))
    await db.delete(user)
    await db.commit()
    return user


async def count_active_admins(db: AsyncSession) -> int:
    stmt = select(func.count(User.id)).where(
        and_(User.role == UserRole.ADMIN, User.is_active.is_(True)),
    )
    return (await db.execute(stmt)).scalar_one()


async def ensure_bootstrap_admin(
    db: AsyncSession,
    *,
    username: str,
    password: str,
    display_name: str = "Administrator",
) -> User:
    existing_admin = (
        await db.execute(
            select(User)
            .where(User.role == UserRole.ADMIN)
            .order_by(User.id.asc())
            .limit(1),
        )
    ).scalar_one_or_none()
    if existing_admin is not None:
        return existing_admin

    existing_user = await get_user_by_username(db, username)
    if existing_user is not None:
        existing_user.role = UserRole.ADMIN
        existing_user.is_active = True
        if not existing_user.display_name:
            existing_user.display_name = display_name
        await db.commit()
        await db.refresh(existing_user)
        return existing_user

    return await create_user(
        db,
        username=username,
        password=password,
        display_name=display_name,
        role=UserRole.ADMIN,
        must_reset_password=False,
    )

