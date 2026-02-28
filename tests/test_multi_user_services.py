from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from monitor_bot.database import Base
from monitor_bot.db_models import AgendaItem, SourceCategory, SourceType, UserRole
from monitor_bot.schemas import QueryCreate, SourceCreate
from monitor_bot.services import agenda as agenda_svc
from monitor_bot.services import queries as query_svc
from monitor_bot.services import runs as run_svc
from monitor_bot.services import sources as source_svc
from monitor_bot.services import users as user_svc


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_sources_and_queries_are_isolated_by_owner(db_session):
    user_a = await user_svc.create_user(
        db_session,
        username="alice",
        password="alice-pass-123",
        display_name="Alice",
    )
    user_b = await user_svc.create_user(
        db_session,
        username="bob",
        password="bob-pass-123",
        display_name="Bob",
    )

    await source_svc.create_source(
        db_session,
        user_a.id,
        SourceCreate(
            name="Feed A",
            url="https://example.com/feed",
            category=SourceCategory.EVENTI,
            source_type=SourceType.RSS_FEED,
        ),
    )
    await source_svc.create_source(
        db_session,
        user_b.id,
        SourceCreate(
            name="Feed B",
            url="https://example.com/feed",
            category=SourceCategory.EVENTI,
            source_type=SourceType.RSS_FEED,
        ),
    )
    await query_svc.create_query(
        db_session,
        user_a.id,
        QueryCreate(query_text="bandi sap", category=SourceCategory.BANDI, max_results=5),
    )
    await query_svc.create_query(
        db_session,
        user_b.id,
        QueryCreate(query_text="bandi sap", category=SourceCategory.BANDI, max_results=5),
    )

    a_sources = await source_svc.list_sources(db_session, owner_user_id=user_a.id)
    b_sources = await source_svc.list_sources(db_session, owner_user_id=user_b.id)
    a_queries = await query_svc.list_queries(db_session, owner_user_id=user_a.id)
    b_queries = await query_svc.list_queries(db_session, owner_user_id=user_b.id)

    assert len(a_sources) == 1
    assert len(b_sources) == 1
    assert a_sources[0].name == "Feed A"
    assert b_sources[0].name == "Feed B"
    assert len(a_queries) == 1
    assert len(b_queries) == 1


@pytest.mark.asyncio
async def test_shared_items_visible_only_to_recipient(db_session):
    sender = await user_svc.create_user(
        db_session,
        username="sender",
        password="sender-pass-123",
        display_name="Sender",
    )
    recipient = await user_svc.create_user(
        db_session,
        username="recipient",
        password="recipient-pass-123",
        display_name="Recipient",
    )
    outsider = await user_svc.create_user(
        db_session,
        username="outsider",
        password="outsider-pass-123",
        display_name="Outsider",
    )

    run = await run_svc.create_run(db_session, sender.id, config_snapshot={"scope": "test"})
    item = AgendaItem(
        owner_user_id=sender.id,
        source_url="https://example.com/opportunity/1",
        opportunity_id="opp-1",
        title="Bando test",
        source="web",
        opportunity_type="Bando",
        relevance_score=9,
        category="AI",
        first_run_id=run.id,
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)

    shared = await agenda_svc.share_item(
        db_session,
        owner_user_id=sender.id,
        item_id=item.id,
        recipient_user_id=recipient.id,
        note="Molto interessante",
    )
    assert shared is not None

    recipient_items = await agenda_svc.list_shared_with_me(db_session, recipient_user_id=recipient.id)
    outsider_items = await agenda_svc.list_shared_with_me(db_session, recipient_user_id=outsider.id)

    assert len(recipient_items) == 1
    assert recipient_items[0]["item"].id == item.id
    assert recipient_items[0]["shared_by_username"] == "sender"
    assert recipient_items[0]["note"] == "Molto interessante"
    assert outsider_items == []

    unseen_before = await agenda_svc.get_shared_unseen_count(db_session, recipient.id)
    assert unseen_before == 1
    updated = await agenda_svc.mark_shared_seen(db_session, recipient_user_id=recipient.id, all_items=True)
    assert updated == 1
    unseen_after = await agenda_svc.get_shared_unseen_count(db_session, recipient.id)
    assert unseen_after == 0


@pytest.mark.asyncio
async def test_search_active_users_and_activate(db_session):
    admin = await user_svc.create_user(
        db_session,
        username="admin",
        password="admin-pass-123",
        display_name="Admin",
        role=UserRole.ADMIN,
    )
    mario = await user_svc.create_user(
        db_session,
        username="mario.rossi",
        password="user-pass-123",
        display_name="Mario Rossi",
    )
    await user_svc.create_user(
        db_session,
        username="luigi.verdi",
        password="user-pass-123",
        display_name="Luigi Verdi",
    )

    visible = await user_svc.search_active_users(db_session, query="ross", exclude_user_id=admin.id)
    assert [u.username for u in visible] == ["mario.rossi"]

    await user_svc.deactivate_user(db_session, mario.id)
    hidden_after_deactivate = await user_svc.search_active_users(
        db_session,
        query="ross",
        exclude_user_id=admin.id,
    )
    assert hidden_after_deactivate == []

    await user_svc.activate_user(db_session, mario.id)
    visible_after_activate = await user_svc.search_active_users(
        db_session,
        query="ross",
        exclude_user_id=admin.id,
    )
    assert [u.username for u in visible_after_activate] == ["mario.rossi"]


@pytest.mark.asyncio
async def test_hard_delete_user_removes_owned_data_and_shares(db_session):
    sender = await user_svc.create_user(
        db_session,
        username="to-delete",
        password="delete-pass-123",
        display_name="To Delete",
    )
    recipient = await user_svc.create_user(
        db_session,
        username="recipient2",
        password="recipient-pass-123",
        display_name="Recipient 2",
    )

    await source_svc.create_source(
        db_session,
        sender.id,
        SourceCreate(
            name="Delete Feed",
            url="https://example.com/delete-feed",
            category=SourceCategory.EVENTI,
            source_type=SourceType.RSS_FEED,
        ),
    )
    await query_svc.create_query(
        db_session,
        sender.id,
        QueryCreate(query_text="delete me", category=SourceCategory.BANDI, max_results=3),
    )

    run = await run_svc.create_run(db_session, sender.id, config_snapshot={"scope": "test"})
    item = AgendaItem(
        owner_user_id=sender.id,
        source_url="https://example.com/opportunity/delete",
        opportunity_id="opp-delete",
        title="Bando da eliminare",
        source="web",
        opportunity_type="Bando",
        relevance_score=8,
        category="AI",
        first_run_id=run.id,
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    await agenda_svc.share_item(
        db_session,
        owner_user_id=sender.id,
        item_id=item.id,
        recipient_user_id=recipient.id,
        note="da eliminare",
    )

    deleted_user = await user_svc.delete_user_permanently(db_session, sender.id)
    assert deleted_user is not None

    sender_after = await user_svc.get_user(db_session, sender.id)
    assert sender_after is None

    sender_sources = await source_svc.list_sources(db_session, owner_user_id=sender.id)
    sender_queries = await query_svc.list_queries(db_session, owner_user_id=sender.id)
    assert sender_sources == []
    assert sender_queries == []

    run_check = await run_svc.get_run(db_session, run.id, owner_user_id=sender.id)
    assert run_check is None

    shared_for_recipient = await agenda_svc.list_shared_with_me(db_session, recipient_user_id=recipient.id)
    assert shared_for_recipient == []

    orphan_items = list((await db_session.execute(select(AgendaItem).where(AgendaItem.owner_user_id == sender.id))).scalars().all())
    assert orphan_items == []
