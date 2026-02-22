"""Standalone entry point for Cloud Run Job pipeline execution.

Runs the full pipeline outside of FastAPI, reading configuration from
the database and writing progress + results back to the database.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from monitor_bot.config import Settings
from monitor_bot.database import async_session, init_db
from monitor_bot.db_models import RunStatus
from monitor_bot.pipeline import run_pipeline
from monitor_bot.routes.api_runs import DBProgress
from monitor_bot.services import queries as query_svc
from monitor_bot.services import runs as run_svc
from monitor_bot.services import settings as settings_svc
from monitor_bot.services import sources as source_svc
from monitor_bot.services.email import _render_report_html, send_run_notification

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


async def _run() -> None:
    await init_db()

    async with async_session() as db:
        run = await run_svc.create_run(db, config_snapshot={"trigger": "cloud_run_job"})
        run_id = run.id
    logger.info("Job started – run_id=%d", run_id)

    progress = DBProgress(run_id)

    try:
        settings = Settings()

        async with async_session() as db:
            active_sources = await source_svc.list_sources(db, active_only=True)
            active_queries = await query_svc.list_queries(db, active_only=True)
            all_settings = await settings_svc.get_all(db)

        settings.apply_db_overrides(active_sources, active_queries)

        threshold_str = all_settings.get("relevance_threshold")
        if threshold_str is not None:
            settings.relevance_threshold = int(threshold_str)

        profile_parts: list[str] = []
        if all_settings.get("company_name"):
            profile_parts.append(f"Azienda: {all_settings['company_name']}")
        if all_settings.get("company_sector"):
            profile_parts.append(f"Settore: {all_settings['company_sector']}")
        if all_settings.get("company_competencies"):
            profile_parts.append(f"Competenze: {all_settings['company_competencies']}")
        budget_min = all_settings.get("company_budget_min", "")
        budget_max = all_settings.get("company_budget_max", "")
        if budget_min or budget_max:
            profile_parts.append(f"Budget target: {budget_min} - {budget_max} EUR")
        if all_settings.get("company_regions"):
            profile_parts.append(f"Regioni operative: {all_settings['company_regions']}")
        if all_settings.get("company_description"):
            profile_parts.append(f"\n{all_settings['company_description']}")
        if all_settings.get("search_scope_description"):
            profile_parts.append(f"Ambito ricerca: {all_settings['search_scope_description']}")
        if profile_parts:
            settings.company_profile = "\n".join(profile_parts)

        logger.info(
            "Pipeline using %d sources, %d queries, threshold=%d",
            len(active_sources), len(active_queries), settings.relevance_threshold,
        )

        result = await run_pipeline(settings, progress=progress, use_cache=False)

        async with async_session() as db:
            if result.classified:
                await run_svc.save_results(db, run_id, result.classified)
            await run_svc.complete_run(
                db, run_id,
                status=RunStatus.COMPLETED,
                total_collected=result.opportunities_collected,
                total_classified=result.opportunities_classified,
                total_relevant=result.opportunities_relevant,
                elapsed_seconds=result.elapsed_seconds,
            )

        progress.on_finish(
            f"Completato: {result.opportunities_relevant} rilevanti "
            f"su {result.opportunities_collected} analizzati"
        )
        logger.info("Job completed successfully – run_id=%d", run_id)

        email_raw = all_settings.get("notification_emails", "")
        email_list = [e.strip() for e in email_raw.split(",") if e.strip()]
        if email_list:
            import os
            app_url = os.environ.get("APP_URL", "")
            report_html = None
            async with async_session() as db:
                run_obj = await run_svc.get_run(db, run_id)
                if run_obj and run_obj.results:
                    report_html = _render_report_html(run_id, run_obj.results)
            await send_run_notification(
                run_id=run_id,
                total_collected=result.opportunities_collected,
                total_classified=result.opportunities_classified,
                total_relevant=result.opportunities_relevant,
                elapsed_seconds=result.elapsed_seconds,
                recipients=email_list,
                app_url=app_url or None,
                report_html=report_html,
            )

    except Exception:
        logger.exception("Job failed – run_id=%d", run_id)
        async with async_session() as db:
            await run_svc.complete_run(db, run_id, status=RunStatus.FAILED)
        progress.on_finish("Errore durante l'esecuzione")
        sys.exit(1)


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
