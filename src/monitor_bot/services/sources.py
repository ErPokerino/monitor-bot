"""CRUD operations for MonitoredSource."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from monitor_bot.db_models import MonitoredSource, SourceCategory
from monitor_bot.schemas import SourceCreate, SourceUpdate


async def list_sources(
    db: AsyncSession,
    *,
    category: SourceCategory | None = None,
    active_only: bool = False,
) -> list[MonitoredSource]:
    stmt = select(MonitoredSource).order_by(MonitoredSource.category, MonitoredSource.name)
    if category:
        stmt = stmt.where(MonitoredSource.category == category)
    if active_only:
        stmt = stmt.where(MonitoredSource.is_active.is_(True))
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_source(db: AsyncSession, source_id: int) -> MonitoredSource | None:
    return await db.get(MonitoredSource, source_id)


async def create_source(db: AsyncSession, data: SourceCreate) -> MonitoredSource:
    source = MonitoredSource(
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
    db: AsyncSession, source_id: int, data: SourceUpdate,
) -> MonitoredSource | None:
    source = await db.get(MonitoredSource, source_id)
    if not source:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(source, field, value)
    await db.commit()
    await db.refresh(source)
    return source


async def toggle_source(db: AsyncSession, source_id: int) -> MonitoredSource | None:
    source = await db.get(MonitoredSource, source_id)
    if not source:
        return None
    source.is_active = not source.is_active
    await db.commit()
    await db.refresh(source)
    return source


async def delete_source(db: AsyncSession, source_id: int) -> bool:
    source = await db.get(MonitoredSource, source_id)
    if not source:
        return False
    await db.delete(source)
    await db.commit()
    return True


async def count_sources(db: AsyncSession, *, active_only: bool = False) -> int:
    stmt = select(func.count(MonitoredSource.id))
    if active_only:
        stmt = stmt.where(MonitoredSource.is_active.is_(True))
    result = await db.execute(stmt)
    return result.scalar_one()


async def source_url_exists(db: AsyncSession, url: str) -> bool:
    stmt = select(func.count(MonitoredSource.id)).where(MonitoredSource.url == url)
    result = await db.execute(stmt)
    return result.scalar_one() > 0
