"""Service layer for SearchRun and SearchResult persistence."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from monitor_bot.db_models import RunStatus, SearchResult, SearchRun, _now_rome
from monitor_bot.models import ClassifiedOpportunity
from monitor_bot.services import agenda as agenda_svc
from monitor_bot.services import settings as settings_svc


async def create_run(
    db: AsyncSession,
    owner_user_id: int,
    config_snapshot: dict | None = None,
) -> SearchRun:
    run = SearchRun(
        owner_user_id=owner_user_id,
        config_snapshot=json.dumps(config_snapshot, ensure_ascii=False) if config_snapshot else None,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


async def complete_run(
    db: AsyncSession,
    run_id: int,
    *,
    status: RunStatus = RunStatus.COMPLETED,
    total_collected: int = 0,
    total_classified: int = 0,
    total_relevant: int = 0,
    elapsed_seconds: float = 0.0,
) -> SearchRun | None:
    run = await db.get(SearchRun, run_id)
    if not run:
        return None
    run.status = status
    run.completed_at = _now_rome()
    run.total_collected = total_collected
    run.total_classified = total_classified
    run.total_relevant = total_relevant
    run.elapsed_seconds = elapsed_seconds
    await db.commit()
    await db.refresh(run)
    return run


async def save_results(
    db: AsyncSession,
    run_id: int,
    owner_user_id: int,
    classified: list[ClassifiedOpportunity],
) -> int:
    """Persist classified opportunities as SearchResult rows. Returns count."""
    count = 0
    saved_results: list[SearchResult] = []
    for item in classified:
        opp = item.opportunity
        cls = item.classification
        result = SearchResult(
            run_id=run_id,
            owner_user_id=owner_user_id,
            opportunity_id=opp.id,
            title=opp.title,
            description=opp.description,
            contracting_authority=opp.contracting_authority,
            deadline=opp.deadline,
            estimated_value=opp.estimated_value,
            currency=opp.currency,
            country=opp.country,
            source_url=opp.source_url,
            source=opp.source.value,
            opportunity_type=opp.opportunity_type.value,
            relevance_score=cls.relevance_score,
            category=cls.category.value,
            ai_reasoning=cls.reason,
            key_requirements=json.dumps(cls.key_requirements, ensure_ascii=False),
            event_format=cls.event_format.value if cls.event_format else None,
            event_cost=cls.event_cost.value if cls.event_cost else None,
            city=cls.city,
            sector=cls.sector,
        )
        db.add(result)
        saved_results.append(result)
        count += 1
    await db.commit()

    all_settings = await settings_svc.get_all(db, user_id=owner_user_id, include_system=False)
    threshold = int(all_settings.get("relevance_threshold", "6"))
    await agenda_svc.upsert_from_results(
        db,
        run_id,
        owner_user_id,
        saved_results,
        threshold=threshold,
    )

    return count


async def list_runs(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    include_all: bool = False,
    limit: int = 50,
) -> list[SearchRun]:
    stmt = (
        select(SearchRun)
        .order_by(SearchRun.started_at.desc())
        .limit(limit)
    )
    if owner_user_id is not None:
        stmt = stmt.where(SearchRun.owner_user_id == owner_user_id)
    elif not include_all:
        stmt = stmt.where(SearchRun.owner_user_id.is_not(None))
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_run(
    db: AsyncSession,
    run_id: int,
    *,
    owner_user_id: int | None = None,
    include_all: bool = False,
) -> SearchRun | None:
    stmt = (
        select(SearchRun)
        .where(SearchRun.id == run_id)
        .options(selectinload(SearchRun.results))
    )
    if owner_user_id is not None:
        stmt = stmt.where(SearchRun.owner_user_id == owner_user_id)
    elif not include_all:
        stmt = stmt.where(SearchRun.owner_user_id.is_not(None))
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_latest_run(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    include_all: bool = False,
) -> SearchRun | None:
    stmt = select(SearchRun).order_by(SearchRun.started_at.desc()).limit(1)
    if owner_user_id is not None:
        stmt = stmt.where(SearchRun.owner_user_id == owner_user_id)
    elif not include_all:
        stmt = stmt.where(SearchRun.owner_user_id.is_not(None))
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_running(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    include_all: bool = False,
) -> SearchRun | None:
    """Return the currently running search, if any."""
    stmt = select(SearchRun).where(SearchRun.status == RunStatus.RUNNING).limit(1)
    if owner_user_id is not None:
        stmt = stmt.where(SearchRun.owner_user_id == owner_user_id)
    elif not include_all:
        stmt = stmt.where(SearchRun.owner_user_id.is_not(None))
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def delete_run(
    db: AsyncSession,
    run_id: int,
    *,
    owner_user_id: int | None = None,
    include_all: bool = False,
) -> bool:
    run = await get_run(db, run_id, owner_user_id=owner_user_id, include_all=include_all)
    if not run:
        return False
    await db.delete(run)
    await db.commit()
    return True


async def delete_runs(
    db: AsyncSession,
    run_ids: list[int],
    *,
    owner_user_id: int | None = None,
    include_all: bool = False,
) -> int:
    """Delete multiple runs by ID. Returns count of deleted rows."""
    count = 0
    for run_id in run_ids:
        run = await get_run(
            db,
            run_id,
            owner_user_id=owner_user_id,
            include_all=include_all,
        )
        if run:
            await db.delete(run)
            count += 1
    if count:
        await db.commit()
    return count
