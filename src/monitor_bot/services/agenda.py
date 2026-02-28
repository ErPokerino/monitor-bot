"""Service layer for AgendaItem management."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from monitor_bot.db_models import AgendaItem, AgendaShare, Evaluation, SearchResult, User, _now_rome


async def upsert_from_results(
    db: AsyncSession,
    run_id: int,
    owner_user_id: int,
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

        stmt = select(AgendaItem).where(
            and_(
                AgendaItem.owner_user_id == owner_user_id,
                AgendaItem.source_url == url_key,
            ),
        )
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
            if r.event_format and not existing.event_format:
                existing.event_format = r.event_format
            if r.event_cost and not existing.event_cost:
                existing.event_cost = r.event_cost
            if r.city and not existing.city:
                existing.city = r.city
            if r.sector and not existing.sector:
                existing.sector = r.sector
        else:
            item = AgendaItem(
                owner_user_id=owner_user_id,
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
                event_format=r.event_format,
                event_cost=r.event_cost,
                city=r.city,
                sector=r.sector,
                is_seen=False,
                first_run_id=run_id,
            )
            db.add(item)
            new_count += 1

    await db.commit()
    return new_count


async def list_agenda(
    db: AsyncSession,
    owner_user_id: int,
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
        AgendaItem.owner_user_id == owner_user_id,
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


async def get_stats(db: AsyncSession, owner_user_id: int) -> dict:
    """Return counts for the notification badge."""
    today = date.today()

    unseen_stmt = select(func.count()).select_from(AgendaItem).where(
        and_(
            AgendaItem.owner_user_id == owner_user_id,
            AgendaItem.is_seen.is_(False),
            or_(AgendaItem.evaluation != Evaluation.REJECTED, AgendaItem.evaluation.is_(None)),
            or_(AgendaItem.deadline.is_(None), AgendaItem.deadline >= today),
        ),
    )
    pending_stmt = select(func.count()).select_from(AgendaItem).where(
        and_(
            AgendaItem.owner_user_id == owner_user_id,
            AgendaItem.evaluation.is_(None),
            or_(AgendaItem.deadline.is_(None), AgendaItem.deadline >= today),
        ),
    )
    expiring_stmt = select(func.count()).select_from(AgendaItem).where(
        and_(
            AgendaItem.owner_user_id == owner_user_id,
            or_(AgendaItem.evaluation != Evaluation.REJECTED, AgendaItem.evaluation.is_(None)),
            AgendaItem.deadline.is_not(None),
            AgendaItem.deadline >= today,
            AgendaItem.deadline <= today + timedelta(days=30),
        ),
    )

    unseen = (await db.execute(unseen_stmt)).scalar() or 0
    pending = (await db.execute(pending_stmt)).scalar() or 0
    expiring = (await db.execute(expiring_stmt)).scalar() or 0
    shared_unseen = await get_shared_unseen_count(db, owner_user_id)

    return {
        "unseen_count": unseen,
        "pending_count": pending,
        "expiring_count": expiring,
        "shared_unseen_count": shared_unseen,
    }


async def list_unseen_notifications(
    db: AsyncSession,
    owner_user_id: int,
    *,
    limit: int = 10,
) -> list[AgendaItem]:
    """Return latest unseen agenda items for notification dropdowns."""
    today = date.today()
    stmt = (
        select(AgendaItem)
        .where(
            and_(
                AgendaItem.owner_user_id == owner_user_id,
                AgendaItem.is_seen.is_(False),
                or_(AgendaItem.evaluation != Evaluation.REJECTED, AgendaItem.evaluation.is_(None)),
                or_(AgendaItem.deadline.is_(None), AgendaItem.deadline >= today),
            ),
        )
        .order_by(AgendaItem.first_seen_at.desc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())


async def get_expiring(db: AsyncSession, owner_user_id: int, *, days: int = 30) -> list[AgendaItem]:
    """Items with deadline within the given number of days."""
    today = date.today()
    cutoff = today + timedelta(days=days)
    stmt = (
        select(AgendaItem)
        .where(
            and_(
                AgendaItem.owner_user_id == owner_user_id,
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


async def evaluate_item(
    db: AsyncSession,
    owner_user_id: int,
    item_id: int,
    evaluation: Evaluation,
) -> AgendaItem | None:
    stmt = select(AgendaItem).where(
        and_(AgendaItem.id == item_id, AgendaItem.owner_user_id == owner_user_id),
    )
    item = (await db.execute(stmt)).scalar_one_or_none()
    if not item:
        return None
    item.evaluation = evaluation
    item.evaluated_at = _now_rome()
    await db.commit()
    await db.refresh(item)
    return item


async def set_enrollment(
    db: AsyncSession,
    owner_user_id: int,
    item_id: int,
    *,
    is_enrolled: bool,
) -> AgendaItem | None:
    stmt = select(AgendaItem).where(
        and_(AgendaItem.id == item_id, AgendaItem.owner_user_id == owner_user_id),
    )
    item = (await db.execute(stmt)).scalar_one_or_none()
    if not item:
        return None
    item.is_enrolled = is_enrolled
    await db.commit()
    await db.refresh(item)
    return item


async def set_feedback(
    db: AsyncSession,
    owner_user_id: int,
    item_id: int,
    *,
    recommend: bool,
    return_next_year: bool,
) -> AgendaItem | None:
    stmt = select(AgendaItem).where(
        and_(AgendaItem.id == item_id, AgendaItem.owner_user_id == owner_user_id),
    )
    item = (await db.execute(stmt)).scalar_one_or_none()
    if not item:
        return None
    item.feedback_recommend = recommend
    item.feedback_return = return_next_year
    await db.commit()
    await db.refresh(item)
    return item


async def mark_seen(
    db: AsyncSession,
    owner_user_id: int,
    *,
    ids: list[int] | None = None,
    all_items: bool = False,
) -> int:
    """Mark agenda items as seen. Returns count of updated rows."""
    if all_items:
        stmt = select(AgendaItem).where(
            and_(
                AgendaItem.owner_user_id == owner_user_id,
                AgendaItem.is_seen.is_(False),
            ),
        )
    elif ids:
        stmt = select(AgendaItem).where(
            and_(
                AgendaItem.owner_user_id == owner_user_id,
                AgendaItem.id.in_(ids),
            ),
        )
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


async def get_excluded_urls(db: AsyncSession, owner_user_id: int) -> set[str]:
    """URLs to exclude from future pipeline runs (rejected + expired)."""
    today = date.today()

    stmt = select(AgendaItem.source_url).where(
        and_(
            AgendaItem.owner_user_id == owner_user_id,
            or_(
                AgendaItem.evaluation == Evaluation.REJECTED,
                and_(AgendaItem.deadline.is_not(None), AgendaItem.deadline < today),
            ),
        ),
    )
    result = await db.execute(stmt)
    return {row[0] for row in result.all()}


async def backfill_from_existing_results(
    db: AsyncSession,
    owner_user_id: int,
    *,
    threshold: int = 6,
) -> int:
    """Populate agenda from existing SearchResults that are not yet in the agenda.

    Called at app startup. Inserts any result above threshold whose source_url
    is not already present in agenda_items.
    Returns count of newly inserted items.
    """
    import logging
    log = logging.getLogger(__name__)

    agenda_count_stmt = select(func.count()).select_from(AgendaItem).where(
        AgendaItem.owner_user_id == owner_user_id,
    )
    agenda_count = (await db.execute(agenda_count_stmt)).scalar() or 0

    results_count_stmt = select(func.count()).select_from(SearchResult).where(
        SearchResult.relevance_score >= threshold,
    )
    results_count = (await db.execute(results_count_stmt)).scalar() or 0

    log.info(
        "Agenda backfill check: %d agenda items, %d eligible search results (threshold=%d)",
        agenda_count, results_count, threshold,
    )

    if results_count == 0:
        return 0

    existing_urls_stmt = select(AgendaItem.source_url).where(
        AgendaItem.owner_user_id == owner_user_id,
    )
    existing_urls = {row[0] for row in (await db.execute(existing_urls_stmt)).all()}

    all_results_stmt = (
        select(SearchResult)
        .where(SearchResult.relevance_score >= threshold)
        .order_by(SearchResult.run_id.asc())
    )
    all_results = list((await db.execute(all_results_stmt)).scalars().all())

    new_count = 0
    seen_urls: set[str] = set(existing_urls)
    for r in all_results:
        url_key = r.source_url.strip().lower()
        if not url_key:
            continue

        if url_key in seen_urls:
            existing_stmt = select(AgendaItem).where(AgendaItem.source_url == url_key)
            existing_stmt = existing_stmt.where(AgendaItem.owner_user_id == owner_user_id)
            existing = (await db.execute(existing_stmt)).scalar_one_or_none()
            if existing and r.relevance_score > existing.relevance_score:
                existing.relevance_score = r.relevance_score
                existing.ai_reasoning = r.ai_reasoning
                existing.category = r.category
                existing.key_requirements = r.key_requirements
            if existing and r.deadline and (existing.deadline is None or r.deadline > existing.deadline):
                existing.deadline = r.deadline
            if existing and r.event_format and not existing.event_format:
                existing.event_format = r.event_format
            if existing and r.event_cost and not existing.event_cost:
                existing.event_cost = r.event_cost
            if existing and r.city and not existing.city:
                existing.city = r.city
            if existing and r.sector and not existing.sector:
                existing.sector = r.sector
            continue

        seen_urls.add(url_key)
        item = AgendaItem(
            owner_user_id=owner_user_id,
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
            event_format=r.event_format,
            event_cost=r.event_cost,
            city=r.city,
            sector=r.sector,
            is_seen=True,
            first_run_id=r.run_id,
        )
        db.add(item)
        new_count += 1

    if new_count:
        await db.commit()

    log.info("Agenda backfill complete: inserted %d new items", new_count)
    return new_count


async def share_item(
    db: AsyncSession,
    *,
    owner_user_id: int,
    item_id: int,
    recipient_user_id: int,
    note: str | None = None,
) -> AgendaShare | None:
    if owner_user_id == recipient_user_id:
        raise ValueError("Cannot share an item with yourself")

    item_stmt = select(AgendaItem).where(
        and_(AgendaItem.id == item_id, AgendaItem.owner_user_id == owner_user_id),
    )
    item = (await db.execute(item_stmt)).scalar_one_or_none()
    if item is None:
        return None

    share_stmt = select(AgendaShare).where(
        and_(
            AgendaShare.agenda_item_id == item_id,
            AgendaShare.sender_user_id == owner_user_id,
            AgendaShare.recipient_user_id == recipient_user_id,
        ),
    )
    share = (await db.execute(share_stmt)).scalar_one_or_none()
    if share is None:
        share = AgendaShare(
            agenda_item_id=item_id,
            sender_user_id=owner_user_id,
            recipient_user_id=recipient_user_id,
            note=note,
            is_seen=False,
        )
        db.add(share)
    else:
        share.note = note
        share.is_seen = False
        share.created_at = _now_rome()

    await db.commit()
    await db.refresh(share)
    return share


async def list_shared_with_me(
    db: AsyncSession,
    *,
    recipient_user_id: int,
    only_unseen: bool = False,
    limit: int = 200,
    offset: int = 0,
) -> list[dict]:
    conditions = [AgendaShare.recipient_user_id == recipient_user_id]
    if only_unseen:
        conditions.append(AgendaShare.is_seen.is_(False))

    stmt = (
        select(AgendaShare, AgendaItem, User)
        .join(AgendaItem, AgendaItem.id == AgendaShare.agenda_item_id)
        .join(User, User.id == AgendaShare.sender_user_id)
        .where(and_(*conditions))
        .order_by(AgendaShare.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(stmt)).all()
    return [
        {
            "share_id": share.id,
            "shared_by_username": sender.username,
            "shared_by_display_name": sender.display_name,
            "note": share.note,
            "shared_at": share.created_at,
            "is_seen": share.is_seen,
            "item": item,
        }
        for share, item, sender in rows
    ]


async def get_shared_unseen_count(db: AsyncSession, recipient_user_id: int) -> int:
    stmt = select(func.count(AgendaShare.id)).where(
        and_(AgendaShare.recipient_user_id == recipient_user_id, AgendaShare.is_seen.is_(False)),
    )
    return (await db.execute(stmt)).scalar() or 0


async def mark_shared_seen(
    db: AsyncSession,
    *,
    recipient_user_id: int,
    ids: list[int] | None = None,
    all_items: bool = False,
) -> int:
    if all_items:
        stmt = select(AgendaShare).where(
            and_(
                AgendaShare.recipient_user_id == recipient_user_id,
                AgendaShare.is_seen.is_(False),
            ),
        )
    elif ids:
        stmt = select(AgendaShare).where(
            and_(
                AgendaShare.recipient_user_id == recipient_user_id,
                AgendaShare.id.in_(ids),
            ),
        )
    else:
        return 0

    shares = list((await db.execute(stmt)).scalars().all())
    count = 0
    for share in shares:
        if not share.is_seen:
            share.is_seen = True
            count += 1
    if count:
        await db.commit()
    return count
