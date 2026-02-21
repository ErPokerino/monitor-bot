"""FastAPI application factory and entry point for the API server."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import update

from monitor_bot.config import Settings
from monitor_bot.database import async_session, init_db
from monitor_bot.db_models import RunStatus, SearchRun
from monitor_bot.routes.api_dashboard import router as dashboard_router
from monitor_bot.routes.api_queries import router as queries_router
from monitor_bot.routes.api_runs import router as runs_router
from monitor_bot.routes.api_settings import router as settings_router
from monitor_bot.routes.api_sources import router as sources_router
from monitor_bot.seed import seed_defaults

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _configure_logging() -> None:
    """Set up root logger with both stream and file handlers."""
    log_dir = PROJECT_ROOT / "data"
    log_dir.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)

    fh = logging.FileHandler(str(log_dir / "server.log"), encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_logging()
    await init_db()

    settings = Settings()
    async with async_session() as db:
        await seed_defaults(db, settings)
        await _cleanup_orphaned_runs(db)

    logger.info("Monitor Bot API ready at http://localhost:8000")
    yield

    from monitor_bot.routes.api_runs import _current_task
    if _current_task is not None:
        _current_task.cancel()
        logger.info("Cancelling running pipeline for shutdown…")
        try:
            await _current_task
        except Exception:
            pass


async def _cleanup_orphaned_runs(db) -> None:
    """Mark any runs left in RUNNING state (from a previous crash) as CANCELLED."""
    stmt = (
        update(SearchRun)
        .where(SearchRun.status == RunStatus.RUNNING)
        .values(status=RunStatus.CANCELLED, completed_at=datetime.utcnow())
    )
    result = await db.execute(stmt)
    if result.rowcount:
        await db.commit()
        logger.info("Cleaned up %d orphaned running task(s)", result.rowcount)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Monitor Bot",
        description="Enterprise monitoring for tenders, events, and funding opportunities",
        version="0.3.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(dashboard_router)
    app.include_router(sources_router)
    app.include_router(queries_router)
    app.include_router(runs_router)
    app.include_router(settings_router)

    return app


app = create_app()


def main() -> None:
    """Entry point for ``uv run monitor-web``."""
    import uvicorn
    uvicorn.run(
        "monitor_bot.app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )


if __name__ == "__main__":
    main()
