"""SQLAlchemy async engine, session factory, and declarative base."""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool


def _get_database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if url:
        return url
    db_path = Path("data") / "monitor.db"
    return f"sqlite+aiosqlite:///{db_path.as_posix()}"


DATABASE_URL = _get_database_url()
_is_sqlite = DATABASE_URL.startswith("sqlite")


class Base(DeclarativeBase):
    pass


_engine_kwargs: dict = {"echo": False}
if _is_sqlite:
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
    _engine_kwargs["poolclass"] = NullPool

engine = create_async_engine(DATABASE_URL, **_engine_kwargs)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

if _is_sqlite:
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def _add_missing_columns(connection) -> None:
    """Add columns that exist in ORM models but not yet in the database tables."""
    import logging
    log = logging.getLogger(__name__)
    dialect_name = connection.dialect.name

    for table in Base.metadata.sorted_tables:
        if dialect_name == "sqlite":
            existing = {
                row[1]
                for row in connection.execute(text(f"PRAGMA table_info('{table.name}')"))
            }
        else:
            rows = connection.execute(text(
                "SELECT column_name FROM information_schema.columns "
                f"WHERE table_schema = 'public' AND table_name = '{table.name}'"
            ))
            existing = {row[0] for row in rows}

        if not existing:
            log.info("Table %s not found in schema – skipping migration", table.name)
            continue

        for col in table.columns:
            if col.name not in existing:
                col_type = col.type.compile(dialect=connection.dialect)
                default = ""
                if col.default is not None and col.default.is_scalar:
                    val = col.default.arg
                    if isinstance(val, bool):
                        default = f" DEFAULT {'true' if val else 'false'}"
                    elif isinstance(val, str):
                        default = f" DEFAULT {val!r}"
                    else:
                        default = f" DEFAULT {val}"
                elif col.nullable:
                    default = " DEFAULT NULL"
                stmt = f"ALTER TABLE {table.name} ADD COLUMN {col.name} {col_type}{default}"
                log.info("Schema migration: %s", stmt)
                connection.execute(text(stmt))


async def init_db() -> None:
    """Create all tables if they don't exist, then add any missing columns."""
    if _is_sqlite:
        db_path = Path("data") / "monitor.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)


async def get_session() -> AsyncSession:  # noqa: D401 – FastAPI dependency
    """Yield a DB session for FastAPI dependency injection."""
    async with async_session() as session:
        yield session  # type: ignore[misc]
