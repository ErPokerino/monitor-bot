"""CRUD operations for SearchQuery."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from monitor_bot.db_models import SearchQuery, SourceCategory
from monitor_bot.schemas import QueryCreate, QueryUpdate


async def list_queries(
    db: AsyncSession,
    *,
    category: SourceCategory | None = None,
    active_only: bool = False,
) -> list[SearchQuery]:
    stmt = select(SearchQuery).order_by(SearchQuery.category, SearchQuery.query_text)
    if category:
        stmt = stmt.where(SearchQuery.category == category)
    if active_only:
        stmt = stmt.where(SearchQuery.is_active.is_(True))
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_query(db: AsyncSession, query_id: int) -> SearchQuery | None:
    return await db.get(SearchQuery, query_id)


async def create_query(db: AsyncSession, data: QueryCreate) -> SearchQuery:
    query = SearchQuery(
        query_text=data.query_text,
        category=data.category,
        max_results=data.max_results,
    )
    db.add(query)
    await db.commit()
    await db.refresh(query)
    return query


async def update_query(
    db: AsyncSession, query_id: int, data: QueryUpdate,
) -> SearchQuery | None:
    query = await db.get(SearchQuery, query_id)
    if not query:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(query, field, value)
    await db.commit()
    await db.refresh(query)
    return query


async def toggle_query(db: AsyncSession, query_id: int) -> SearchQuery | None:
    query = await db.get(SearchQuery, query_id)
    if not query:
        return None
    query.is_active = not query.is_active
    await db.commit()
    await db.refresh(query)
    return query


async def delete_query(db: AsyncSession, query_id: int) -> bool:
    query = await db.get(SearchQuery, query_id)
    if not query:
        return False
    await db.delete(query)
    await db.commit()
    return True


async def count_queries(db: AsyncSession, *, active_only: bool = False) -> int:
    stmt = select(func.count(SearchQuery.id))
    if active_only:
        stmt = stmt.where(SearchQuery.is_active.is_(True))
    result = await db.execute(stmt)
    return result.scalar_one()


async def query_text_exists(db: AsyncSession, text: str) -> bool:
    stmt = select(func.count(SearchQuery.id)).where(SearchQuery.query_text == text)
    result = await db.execute(stmt)
    return result.scalar_one() > 0
