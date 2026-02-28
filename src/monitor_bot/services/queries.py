"""CRUD operations for SearchQuery."""

from __future__ import annotations

from sqlalchemy import func, select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from monitor_bot.db_models import SearchQuery, SourceCategory
from monitor_bot.schemas import QueryCreate, QueryUpdate


async def list_queries(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    include_all: bool = False,
    category: SourceCategory | None = None,
    active_only: bool = False,
) -> list[SearchQuery]:
    stmt = select(SearchQuery).order_by(SearchQuery.category, SearchQuery.query_text)
    if owner_user_id is not None:
        stmt = stmt.where(SearchQuery.owner_user_id == owner_user_id)
    elif not include_all:
        stmt = stmt.where(SearchQuery.owner_user_id.is_not(None))
    if category:
        stmt = stmt.where(SearchQuery.category == category)
    if active_only:
        stmt = stmt.where(SearchQuery.is_active.is_(True))
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_query(
    db: AsyncSession,
    query_id: int,
    *,
    owner_user_id: int | None = None,
    include_all: bool = False,
) -> SearchQuery | None:
    stmt = select(SearchQuery).where(SearchQuery.id == query_id)
    if owner_user_id is not None:
        stmt = stmt.where(SearchQuery.owner_user_id == owner_user_id)
    elif not include_all:
        stmt = stmt.where(SearchQuery.owner_user_id.is_not(None))
    return (await db.execute(stmt)).scalar_one_or_none()


async def create_query(db: AsyncSession, owner_user_id: int, data: QueryCreate) -> SearchQuery:
    query = SearchQuery(
        owner_user_id=owner_user_id,
        query_text=data.query_text,
        category=data.category,
        max_results=data.max_results,
    )
    db.add(query)
    await db.commit()
    await db.refresh(query)
    return query


async def update_query(
    db: AsyncSession,
    query_id: int,
    data: QueryUpdate,
    *,
    owner_user_id: int | None = None,
    include_all: bool = False,
) -> SearchQuery | None:
    query = await get_query(
        db,
        query_id,
        owner_user_id=owner_user_id,
        include_all=include_all,
    )
    if not query:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(query, field, value)
    await db.commit()
    await db.refresh(query)
    return query


async def toggle_query(
    db: AsyncSession,
    query_id: int,
    *,
    owner_user_id: int | None = None,
    include_all: bool = False,
) -> SearchQuery | None:
    query = await get_query(
        db,
        query_id,
        owner_user_id=owner_user_id,
        include_all=include_all,
    )
    if not query:
        return None
    query.is_active = not query.is_active
    await db.commit()
    await db.refresh(query)
    return query


async def delete_query(
    db: AsyncSession,
    query_id: int,
    *,
    owner_user_id: int | None = None,
    include_all: bool = False,
) -> bool:
    query = await get_query(
        db,
        query_id,
        owner_user_id=owner_user_id,
        include_all=include_all,
    )
    if not query:
        return False
    await db.delete(query)
    await db.commit()
    return True


async def count_queries(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    include_all: bool = False,
    active_only: bool = False,
) -> int:
    stmt = select(func.count(SearchQuery.id))
    if owner_user_id is not None:
        stmt = stmt.where(SearchQuery.owner_user_id == owner_user_id)
    elif not include_all:
        stmt = stmt.where(SearchQuery.owner_user_id.is_not(None))
    if active_only:
        stmt = stmt.where(SearchQuery.is_active.is_(True))
    result = await db.execute(stmt)
    return result.scalar_one()


async def set_all_active(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    include_all: bool = False,
    active: bool,
) -> int:
    stmt = sa_update(SearchQuery).values(is_active=active)
    if owner_user_id is not None:
        stmt = stmt.where(SearchQuery.owner_user_id == owner_user_id)
    elif not include_all:
        stmt = stmt.where(SearchQuery.owner_user_id.is_not(None))
    result = await db.execute(
        stmt,
    )
    await db.commit()
    return result.rowcount


async def query_text_exists(
    db: AsyncSession,
    text: str,
    *,
    owner_user_id: int | None = None,
    include_all: bool = False,
) -> bool:
    stmt = select(func.count(SearchQuery.id)).where(SearchQuery.query_text == text)
    if owner_user_id is not None:
        stmt = stmt.where(SearchQuery.owner_user_id == owner_user_id)
    elif not include_all:
        stmt = stmt.where(SearchQuery.owner_user_id.is_not(None))
    result = await db.execute(stmt)
    return result.scalar_one() > 0
