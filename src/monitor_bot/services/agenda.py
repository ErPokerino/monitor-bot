"""Service layer for AgendaItem management."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from monitor_bot.db_models import AgendaItem, Evaluation, SearchResult, _now_rome


async def upsert_from_results(
    db: AsyncSession,
    run_id: int,
    results: list[SearchResult],
    *,
    threshold: int = 6,
) -> int:
    """Insert new agenda items or update existing ones from search results.

    Only items with relevance_score >= threshold are included.
    Returns count of newly inserted items.
    """
    new_count = 0
    for r in results:
        if r.relevance_score < threshold:
            continue
        url_key = r.source_url.strip().lower()
        if not url_key:
            continue

        stmt = select(AgendaItem).where(AgendaItem.source_url == url_key)
        existing = (await db.execute(stmt)).scalar_one_or_none()

        if existing is not None:
            if existing.evaluation == Evaluation.REJECTED:
                continue
            if r.relevance_score > existing.relevance_score:
                existing.relevance_score = r.relevance_score
                existing.ai_reasoning = r.ai_reasoning
                existing.category = r.category
                existing.key_requirements = r.key_requirements
            if r.deadline and (existing.deadline is None or r.deadline > existing.deadline):
                existing.deadline = r.deadline
            if r.description and len(r.description) > len(existing.description or ""):
                existing.description = r.description
        else:
            item = AgendaItem(
                source_url=url_key,
                opportunity_id=r.opportunity_id,
                title=r.title,
                description=r.description,
                contracting_authority=r.contracting_authority,
                deadline=r.deadline,
                estimated_value=r.estimated_value,
                currency=r.currency,
                country=r.country,
                source=r.source,
                opportunity_type=r.opportunity_type,
                relevance_score=r.relevance_score,
                category=r.category,
                ai_reasoning=r.ai_reasoning,
                key_requirements=r.key_requirements,
                is_seen=False,
                first_run_id=run_id,
            )
            db.add(item)
            new_count += 1

    await db.commit()
    return new_count


async def list_agenda(
    db: AsyncSession,
    *,
    opp_type: str | None = None,
    category: str | None = None,
    enrolled: bool | None = None,
    search: str | None = None,
    sort: str = "first_seen_at",
    tab: str = "pending",
    limit: int = 200,
    offset: int = 0,
) -> list[AgendaItem]:
    """Return active agenda items (not rejected, not expired)."""
    today = date.today()

    conditions = [
        or_(AgendaItem.evaluation != Evaluation.REJECTED, AgendaItem.evaluation.is_(None)),
    ]

    if tab == "pending":
        conditions.append(AgendaItem.evaluation.is_(None))
        conditions.append(
            or_(AgendaItem.deadline.is_(None), AgendaItem.deadline >= today),
        )
    elif tab == "interested":
        conditions.append(AgendaItem.evaluation == Evaluation.INTERESTED)
        conditions.append(
            or_(AgendaItem.deadline.is_(None), AgendaItem.deadline >= today),
        )
    elif tab == "past_events":
        conditions.append(AgendaItem.is_enrolled.is_(True))
        conditions.append(AgendaItem.opportunity_type == "Evento")
        conditions.append(AgendaItem.deadline.is_not(None))
        conditions.append(AgendaItem.deadline < today)

    if opp_type:
        conditions.append(AgendaItem.opportunity_type == opp_type)
    if category:
        conditions.append(AgendaItem.category == category)
    if enrolled is not None:
        conditions.append(AgendaItem.is_enrolled.is_(enrolled))
    if search:
        like = f"%{search}%"
        conditions.append(
            or_(AgendaItem.title.ilike(like), AgendaItem.description.ilike(like)),
        )

    order_col = {
        "relevance_score": AgendaItem.relevance_score.desc(),
        "deadline": AgendaItem.deadline.asc().nulls_last(),
        "first_seen_at": AgendaItem.first_seen_at.desc(),
    }.get(sort, AgendaItem.first_seen_at.desc())

    stmt = (
        select(AgendaItem)
        .where(and_(*conditions))
        .order_by(order_col)
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_stats(db: AsyncSession) -> dict:
    """Return counts for the notification badge."""
    today = date.today()

    unseen_stmt = select(func.count()).select_from(AgendaItem).where(
        and_(
            AgendaItem.is_seen.is_(False),
            or_(AgendaItem.evaluation != Evaluation.REJECTED, AgendaItem.evaluation.is_(None)),
            or_(AgendaItem.deadline.is_(None), AgendaItem.deadline >= today),
        ),
    )
    pending_stmt = select(func.count()).select_from(AgendaItem).where(
        and_(
            AgendaItem.evaluation.is_(None),
            or_(AgendaItem.deadline.is_(None), AgendaItem.deadline >= today),
        ),
    )
    expiring_stmt = select(func.count()).select_from(AgendaItem).where(
        and_(
            or_(AgendaItem.evaluation != Evaluation.REJECTED, AgendaItem.evaluation.is_(None)),
            AgendaItem.deadline.is_not(None),
            AgendaItem.deadline >= today,
            AgendaItem.deadline <= today + timedelta(days=30),
        ),
    )

    unseen = (await db.execute(unseen_stmt)).scalar() or 0
    pending = (await db.execute(pending_stmt)).scalar() or 0
    expiring = (await db.execute(expiring_stmt)).scalar() or 0

    return {"unseen_count": unseen, "pending_count": pending, "expiring_count": expiring}


async def get_expiring(db: AsyncSession, *, days: int = 30) -> list[AgendaItem]:
    """Items with deadline within the given number of days."""
    today = date.today()
    cutoff = today + timedelta(days=days)
    stmt = (
        select(AgendaItem)
        .where(
            and_(
                or_(AgendaItem.evaluation == Evaluation.INTERESTED, AgendaItem.evaluation.is_(None)),
                AgendaItem.deadline.is_not(None),
                AgendaItem.deadline >= today,
                AgendaItem.deadline <= cutoff,
            ),
        )
        .order_by(AgendaItem.deadline.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def evaluate_item(db: AsyncSession, item_id: int, evaluation: Evaluation) -> AgendaItem | None:
    item = await db.get(AgendaItem, item_id)
    if not item:
        return None
    item.evaluation = evaluation
    item.evaluated_at = _now_rome()
    await db.commit()
    await db.refresh(item)
    return item


async def set_enrollment(db: AsyncSession, item_id: int, *, is_enrolled: bool) -> AgendaItem | None:
    item = await db.get(AgendaItem, item_id)
    if not item:
        return None
    item.is_enrolled = is_enrolled
    await db.commit()
    await db.refresh(item)
    return item


async def set_feedback(
    db: AsyncSession,
    item_id: int,
    *,
    recommend: bool,
    return_next_year: bool,
) -> AgendaItem | None:
    item = await db.get(AgendaItem, item_id)
    if not item:
        return None
    item.feedback_recommend = recommend
    item.feedback_return = return_next_year
    await db.commit()
    await db.refresh(item)
    return item


async def mark_seen(db: AsyncSession, *, ids: list[int] | None = None, all_items: bool = False) -> int:
    """Mark agenda items as seen. Returns count of updated rows."""
    if all_items:
        stmt = select(AgendaItem).where(AgendaItem.is_seen.is_(False))
    elif ids:
        stmt = select(AgendaItem).where(AgendaItem.id.in_(ids))
    else:
        return 0

    result = await db.execute(stmt)
    items = list(result.scalars().all())
    count = 0
    for item in items:
        if not item.is_seen:
            item.is_seen = True
            count += 1
    if count:
        await db.commit()
    return count


async def get_excluded_urls(db: AsyncSession) -> set[str]:
    """URLs to exclude from future pipeline runs (rejected + expired)."""
    today = date.today()

    stmt = select(AgendaItem.source_url).where(
        or_(
            AgendaItem.evaluation == Evaluation.REJECTED,
            and_(AgendaItem.deadline.is_not(None), AgendaItem.deadline < today),
        ),
    )
    result = await db.execute(stmt)
    return {row[0] for row in result.all()}


async def backfill_from_existing_results(db: AsyncSession, *, threshold: int = 6) -> int:
    """One-time migration: populate agenda from all existing SearchResults.

    Skips results already present in the agenda. Should be called at app startup.
    Returns count of newly inserted items.
    """
    import logging
    log = logging.getLogger(__name__)

    existing_urls_stmt = select(AgendaItem.source_url)
    existing_urls = {row[0] for row in (await db.execute(existing_urls_stmt)).all()}

    if existing_urls:
        return 0

    all_results_stmt = (
        select(SearchResult)
        .where(SearchResult.relevance_score >= threshold)
        .order_by(SearchResult.run_id.asc())
    )
    all_results = list((await db.execute(all_results_stmt)).scalars().all())

    if not all_results:
        return 0

    new_count = 0
    seen_urls: set[str] = set()
    for r in all_results:
        url_key = r.source_url.strip().lower()
        if not url_key or url_key in seen_urls:
            if url_key in seen_urls:
                stmt = select(AgendaItem).where(AgendaItem.source_url == url_key)
                existing = (await db.execute(stmt)).scalar_one_or_none()
                if existing and r.relevance_score > existing.relevance_score:
                    existing.relevance_score = r.relevance_score
                    existing.ai_reasoning = r.ai_reasoning
                    existing.category = r.category
                    existing.key_requirements = r.key_requirements
                if existing and r.deadline and (existing.deadline is None or r.deadline > existing.deadline):
                    existing.deadline = r.deadline
            continue

        seen_urls.add(url_key)
        item = AgendaItem(
            source_url=url_key,
            opportunity_id=r.opportunity_id,
            title=r.title,
            description=r.description,
            contracting_authority=r.contracting_authority,
            deadline=r.deadline,
            estimated_value=r.estimated_value,
            currency=r.currency,
            country=r.country,
            source=r.source,
            opportunity_type=r.opportunity_type,
            relevance_score=r.relevance_score,
            category=r.category,
            ai_reasoning=r.ai_reasoning,
            key_requirements=r.key_requirements,
            is_seen=True,
            first_run_id=r.run_id,
        )
        db.add(item)
        new_count += 1

    if new_count:
        await db.commit()
        log.info("Agenda backfill: inserted %d items from existing search results", new_count)

    return new_count
