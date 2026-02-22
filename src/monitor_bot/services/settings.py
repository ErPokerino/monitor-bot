"""Service layer for application settings (key-value store)."""

from __future__ import annotations

import logging
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from monitor_bot.db_models import AppSetting

logger = logging.getLogger(__name__)

DEFAULTS: dict[str, str] = {
    "relevance_threshold": "6",
    "scheduler_day": "1",
    "scheduler_hour": "2",
    "pipeline_timeout_minutes": "60",
    "company_name": "",
    "company_sector": "IT Consulting & Services",
    "company_competencies": "SAP,Data Engineering,AI / Machine Learning,Cloud Infrastructure",
    "company_budget_min": "100000",
    "company_budget_max": "50000000",
    "company_regions": "Italia,EMEA",
    "company_description": (
        "Siamo un'azienda IT di medie-grandi dimensioni operante in Italia e nell'area EMEA.\n\n"
        "Competenze principali:\n"
        "1. SAP: Implementazione, migrazione (S/4HANA), integrazione e supporto ecosistemi SAP "
        "inclusi SAP BTP, SAP Analytics Cloud e sviluppo ABAP.\n"
        "2. Data Engineering: Progettazione e implementazione di piattaforme dati, pipeline ETL/ELT, "
        "data lake, data warehouse (Snowflake, Databricks, BigQuery) e soluzioni BI.\n"
        "3. AI / Machine Learning: Sviluppo modelli ML, soluzioni NLP, computer vision, MLOps "
        "e applicazioni di AI Generativa per casi d'uso enterprise.\n"
        "4. Cloud Infrastructure: Architettura cloud, migrazione e servizi gestiti su AWS, Azure "
        "e Google Cloud. DevOps, Kubernetes, IaC (Terraform) e pratiche SRE.\n\n"
        "Operiamo tipicamente su progetti tra 100.000 EUR e 50.000.000 EUR, "
        "collaborando con pubbliche amministrazioni, grandi imprese e utility."
    ),
    "search_scope_description": "",
}


async def get_all(db: AsyncSession) -> dict[str, str]:
    result = await db.execute(select(AppSetting))
    settings = {s.key: s.value for s in result.scalars().all()}
    for key, default in DEFAULTS.items():
        settings.setdefault(key, default)
    return settings


async def get_value(db: AsyncSession, key: str) -> str | None:
    setting = await db.get(AppSetting, key)
    if setting:
        return setting.value
    return DEFAULTS.get(key)


async def update_all(db: AsyncSession, data: dict[str, str]) -> dict[str, str]:
    old_settings = await get_all(db)
    for key, value in data.items():
        setting = await db.get(AppSetting, key)
        if setting:
            setting.value = str(value)
        else:
            db.add(AppSetting(key=key, value=str(value)))
    await db.commit()

    new_day = data.get("scheduler_day", old_settings.get("scheduler_day", ""))
    new_hour = data.get("scheduler_hour", old_settings.get("scheduler_hour", ""))
    old_day = old_settings.get("scheduler_day", "")
    old_hour = old_settings.get("scheduler_hour", "")
    if (new_day != old_day or new_hour != old_hour) and new_day and new_hour:
        await _sync_cloud_scheduler(int(new_day), int(new_hour))

    return await get_all(db)


async def _sync_cloud_scheduler(day: int, hour: int) -> None:
    """Update the Cloud Scheduler cron expression via REST API (GCP only)."""
    project_id = os.environ.get("GCP_PROJECT_ID")
    region = os.environ.get("GCP_REGION")
    if not project_id or not region:
        logger.debug("Not in GCP environment, skipping scheduler sync")
        return

    cron = f"0 {hour} * * {day}"
    job_name = f"projects/{project_id}/locations/{region}/jobs/opportunity-radar-weekly"

    try:
        import google.auth
        import google.auth.transport.requests
        import httpx

        credentials, _ = google.auth.default()
        credentials.refresh(google.auth.transport.requests.Request())

        async with httpx.AsyncClient() as client:
            resp = await client.patch(
                f"https://cloudscheduler.googleapis.com/v1/{job_name}",
                json={"schedule": cron},
                params={"updateMask": "schedule"},
                headers={"Authorization": f"Bearer {credentials.token}"},
            )
            if resp.is_success:
                logger.info("Cloud Scheduler updated to '%s'", cron)
            else:
                logger.warning("Cloud Scheduler update failed: %s %s", resp.status_code, resp.text)
    except Exception:
        logger.warning("Failed to sync Cloud Scheduler", exc_info=True)
