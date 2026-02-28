"""CRUD operations for MonitoredSource."""

from __future__ import annotations

from sqlalchemy import func, select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from monitor_bot.db_models import MonitoredSource, SourceCategory
from monitor_bot.schemas import SourceCreate, SourceUpdate


async def list_sources(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    include_all: bool = False,
    category: SourceCategory | None = None,
    active_only: bool = False,
) -> list[MonitoredSource]:
    stmt = select(MonitoredSource).order_by(MonitoredSource.category, MonitoredSource.name)
    if owner_user_id is not None:
        stmt = stmt.where(MonitoredSource.owner_user_id == owner_user_id)
    elif not include_all:
        stmt = stmt.where(MonitoredSource.owner_user_id.is_not(None))
    if category:
        stmt = stmt.where(MonitoredSource.category == category)
    if active_only:
        stmt = stmt.where(MonitoredSource.is_active.is_(True))
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_source(
    db: AsyncSession,
    source_id: int,
    *,
    owner_user_id: int | None = None,
    include_all: bool = False,
) -> MonitoredSource | None:
    stmt = select(MonitoredSource).where(MonitoredSource.id == source_id)
    if owner_user_id is not None:
        stmt = stmt.where(MonitoredSource.owner_user_id == owner_user_id)
    elif not include_all:
        stmt = stmt.where(MonitoredSource.owner_user_id.is_not(None))
    return (await db.execute(stmt)).scalar_one_or_none()


async def create_source(db: AsyncSession, owner_user_id: int, data: SourceCreate) -> MonitoredSource:
    source = MonitoredSource(
        owner_user_id=owner_user_id,
        name=data.name,
        url=data.url,
        category=data.category,
        source_type=data.source_type,
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return source


async def update_source(
    db: AsyncSession,
    source_id: int,
    data: SourceUpdate,
    *,
    owner_user_id: int | None = None,
    include_all: bool = False,
) -> MonitoredSource | None:
    source = await get_source(
        db,
        source_id,
        owner_user_id=owner_user_id,
        include_all=include_all,
    )
    if not source:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(source, field, value)
    await db.commit()
    await db.refresh(source)
    return source


async def toggle_source(
    db: AsyncSession,
    source_id: int,
    *,
    owner_user_id: int | None = None,
    include_all: bool = False,
) -> MonitoredSource | None:
    source = await get_source(
        db,
        source_id,
        owner_user_id=owner_user_id,
        include_all=include_all,
    )
    if not source:
        return None
    source.is_active = not source.is_active
    await db.commit()
    await db.refresh(source)
    return source


async def delete_source(
    db: AsyncSession,
    source_id: int,
    *,
    owner_user_id: int | None = None,
    include_all: bool = False,
) -> bool:
    source = await get_source(
        db,
        source_id,
        owner_user_id=owner_user_id,
        include_all=include_all,
    )
    if not source:
        return False
    await db.delete(source)
    await db.commit()
    return True


async def count_sources(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    include_all: bool = False,
    active_only: bool = False,
) -> int:
    stmt = select(func.count(MonitoredSource.id))
    if owner_user_id is not None:
        stmt = stmt.where(MonitoredSource.owner_user_id == owner_user_id)
    elif not include_all:
        stmt = stmt.where(MonitoredSource.owner_user_id.is_not(None))
    if active_only:
        stmt = stmt.where(MonitoredSource.is_active.is_(True))
    result = await db.execute(stmt)
    return result.scalar_one()


async def set_all_active(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    include_all: bool = False,
    active: bool,
) -> int:
    stmt = sa_update(MonitoredSource).values(is_active=active)
    if owner_user_id is not None:
        stmt = stmt.where(MonitoredSource.owner_user_id == owner_user_id)
    elif not include_all:
        stmt = stmt.where(MonitoredSource.owner_user_id.is_not(None))
    result = await db.execute(
        stmt,
    )
    await db.commit()
    return result.rowcount


async def source_url_exists(
    db: AsyncSession,
    url: str,
    *,
    owner_user_id: int | None = None,
    include_all: bool = False,
) -> bool:
    stmt = select(func.count(MonitoredSource.id)).where(MonitoredSource.url == url)
    if owner_user_id is not None:
        stmt = stmt.where(MonitoredSource.owner_user_id == owner_user_id)
    elif not include_all:
        stmt = stmt.where(MonitoredSource.owner_user_id.is_not(None))
    result = await db.execute(stmt)
    return result.scalar_one() > 0
