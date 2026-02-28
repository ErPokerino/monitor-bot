"""FastAPI application factory and entry point for the API server."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, update

from monitor_bot.config import Settings
from monitor_bot.database import async_session, init_db
from monitor_bot.auth import principal_from_user, validate_token
from monitor_bot.db_models import RunStatus, SearchRun, User, UserRole, _now_rome
from monitor_bot.routes.api_admin import router as admin_router
from monitor_bot.routes.api_agenda import router as agenda_router
from monitor_bot.routes.api_auth import router as auth_router
from monitor_bot.routes.api_chat import router as chat_router
from monitor_bot.routes.api_voice import router as voice_router
from monitor_bot.routes.api_dashboard import router as dashboard_router
from monitor_bot.routes.api_queries import router as queries_router
from monitor_bot.routes.api_runs import router as runs_router
from monitor_bot.routes.api_settings import router as settings_router
from monitor_bot.routes.api_sources import router as sources_router
from monitor_bot.seed import seed_defaults

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
STATIC_DIR = Path(os.environ.get("STATIC_DIR", PROJECT_ROOT / "static"))


def _configure_logging() -> None:
    """Set up root logger with stream handler (and file handler in local dev)."""
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

    if os.environ.get("LOG_TO_FILE", "1") == "1":
        log_dir = PROJECT_ROOT / "data"
        log_dir.mkdir(parents=True, exist_ok=True)
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
        await _backfill_agenda(db)

    port = os.environ.get("PORT", "8000")
    logger.info("Opportunity Radar API ready on port %s", port)
    yield

    from monitor_bot.routes.api_runs import _current_task
    if _current_task is not None:
        _current_task.cancel()
        logger.info("Cancelling running pipeline for shutdown…")
        try:
            await _current_task
        except Exception:
            pass


async def _backfill_agenda(db) -> None:
    """Populate agenda from existing search results that are not yet present."""
    try:
        from monitor_bot.services import agenda as agenda_svc
        from monitor_bot.services import settings as settings_svc

        users = list(
            (await db.execute(select(User).where(User.is_active.is_(True)))).scalars().all(),
        )
        if not users:
            return

        total = 0
        for user in users:
            all_settings = await settings_svc.get_all(db, user_id=user.id, include_system=False)
            threshold = int(all_settings.get("relevance_threshold", "6"))
            logger.info(
                "Running agenda backfill for user=%s (threshold=%d) …",
                user.username,
                threshold,
            )
            count = await agenda_svc.backfill_from_existing_results(
                db,
                user.id,
                threshold=threshold,
            )
            total += count
        logger.info("Agenda backfill finished: %d new item(s)", total)
    except Exception:
        logger.exception("Agenda backfill failed – continuing startup")


async def _cleanup_orphaned_runs(db) -> None:
    """Mark any runs left in RUNNING state (from a previous crash) as CANCELLED."""
    stmt = (
        update(SearchRun)
        .where(SearchRun.status == RunStatus.RUNNING)
        .values(status=RunStatus.CANCELLED, completed_at=_now_rome())
    )
    result = await db.execute(stmt)
    if result.rowcount:
        await db.commit()
        logger.info("Cleaned up %d orphaned running task(s)", result.rowcount)


def _verify_gcp_oidc(token: str) -> bool:
    """Verify a Google OIDC token (used by Cloud Scheduler)."""
    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token

        id_token.verify_oauth2_token(token, google_requests.Request())
        return True
    except Exception:
        return False


def create_app() -> FastAPI:
    app = FastAPI(
        title="Opportunity Radar",
        description="Enterprise monitoring for tenders, events, and funding opportunities",
        version="0.4.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def _auth_middleware(request: Request, call_next):
        path = request.url.path
        if (
            not path.startswith("/api")
            or path.startswith("/api/auth/login")
            or path.startswith("/api/docs")
            or path.startswith("/api/openapi")
            or path == "/api/chat/voice"
            or request.method == "OPTIONS"
        ):
            return await call_next(request)
        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)
        token = auth_header.removeprefix("Bearer ").strip()
        async with async_session() as db:
            principal = await validate_token(db, token)
        if principal:
            request.state.auth_principal = principal
            return await call_next(request)
        if path == "/api/runs/start" and _verify_gcp_oidc(token):
            async with async_session() as db:
                admin_user = (
                    await db.execute(
                        select(User)
                        .where(User.role == UserRole.ADMIN, User.is_active.is_(True))
                        .order_by(User.id.asc())
                        .limit(1),
                    )
                ).scalar_one_or_none()
                if admin_user is not None:
                    request.state.auth_principal = principal_from_user(admin_user)
            return await call_next(request)
        return JSONResponse({"detail": "Invalid or expired token"}, status_code=401)

    app.include_router(auth_router)
    app.include_router(admin_router)
    app.include_router(agenda_router)
    app.include_router(dashboard_router)
    app.include_router(sources_router)
    app.include_router(queries_router)
    app.include_router(runs_router)
    app.include_router(settings_router)
    app.include_router(chat_router)
    app.include_router(voice_router)

    if STATIC_DIR.is_dir():
        _mount_frontend(app)

    return app


def _mount_frontend(app: FastAPI) -> None:
    """Serve the Vite production build and provide SPA-style HTML fallback."""
    html_files = {f"/{f.name}" for f in STATIC_DIR.glob("*.html")}

    @app.middleware("http")
    async def _spa_fallback(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api") or path.startswith("/docs") or path.startswith("/openapi"):
            return await call_next(request)
        file = STATIC_DIR / path.lstrip("/")
        if file.is_file():
            resp = FileResponse(file)
            if file.suffix == ".html":
                resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            return resp
        if path in html_files or path == "/":
            target = "index.html" if path == "/" else path.lstrip("/")
            resp = FileResponse(STATIC_DIR / target)
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            return resp
        return await call_next(request)

    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="static-assets")


app = create_app()


def main() -> None:
    """Entry point for ``uv run monitor-web``."""
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(
        "monitor_bot.app:app",
        host="0.0.0.0",
        port=port,
        reload=os.environ.get("ENV", "development") == "development",
    )


if __name__ == "__main__":
    main()
