"""Service layer for application settings (key-value store)."""

from __future__ import annotations

import logging
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from monitor_bot.db_models import AppSetting, UserSetting

logger = logging.getLogger(__name__)

SYSTEM_DEFAULTS: dict[str, str] = {
    "scheduler_enabled": "1",
    "scheduler_day": "1",
    "scheduler_hour": "2",
    "pipeline_timeout_minutes": "60",
    "notification_emails": "marcello.gomitoni@abstract.it",
}

USER_DEFAULTS: dict[str, str] = {
    "relevance_threshold": "6",
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


def _split_payload(data: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    user_data: dict[str, str] = {}
    system_data: dict[str, str] = {}
    for key, value in data.items():
        if key in USER_DEFAULTS:
            user_data[key] = str(value)
        elif key in SYSTEM_DEFAULTS:
            system_data[key] = str(value)
    return user_data, system_data


def _as_enabled(value: str | None) -> bool:
    return str(value).strip().lower() not in {"0", "false", "off", "no", ""}


async def get_all(
    db: AsyncSession,
    *,
    user_id: int | None = None,
    include_system: bool = True,
) -> dict[str, str]:
    settings: dict[str, str] = {}

    if include_system:
        settings.update(SYSTEM_DEFAULTS)
        result = await db.execute(select(AppSetting))
        global_values = {s.key: s.value for s in result.scalars().all()}
        for key in SYSTEM_DEFAULTS:
            if key in global_values:
                settings[key] = global_values[key]

    if user_id is not None:
        settings.update(USER_DEFAULTS)
        user_result = await db.execute(
            select(UserSetting).where(UserSetting.user_id == user_id),
        )
        for row in user_result.scalars().all():
            if row.key in USER_DEFAULTS:
                settings[row.key] = row.value

    return settings


async def get_value(
    db: AsyncSession,
    key: str,
    *,
    user_id: int | None = None,
    include_system: bool = True,
) -> str | None:
    settings = await get_all(db, user_id=user_id, include_system=include_system)
    return settings.get(key)


async def update_all(
    db: AsyncSession,
    data: dict[str, str],
    *,
    user_id: int,
    is_admin: bool = False,
) -> dict[str, str]:
    old_settings = await get_all(db, user_id=user_id, include_system=True)
    user_data, system_data = _split_payload(data)

    for key, value in user_data.items():
        stmt = select(UserSetting).where(
            UserSetting.user_id == user_id,
            UserSetting.key == key,
        )
        setting = (await db.execute(stmt)).scalar_one_or_none()
        if setting:
            setting.value = value
        else:
            db.add(UserSetting(user_id=user_id, key=key, value=value))

    if system_data and not is_admin:
        raise PermissionError("Only admin users can update system settings")

    for key, value in system_data.items():
        setting = await db.get(AppSetting, key)
        if setting:
            setting.value = value
        else:
            db.add(AppSetting(key=key, value=value))

    await db.commit()

    new_enabled = system_data.get("scheduler_enabled", old_settings.get("scheduler_enabled", "1"))
    new_day = system_data.get("scheduler_day", old_settings.get("scheduler_day", ""))
    new_hour = system_data.get("scheduler_hour", old_settings.get("scheduler_hour", ""))
    old_enabled = old_settings.get("scheduler_enabled", "1")
    old_day = old_settings.get("scheduler_day", "")
    old_hour = old_settings.get("scheduler_hour", "")
    if (new_enabled != old_enabled or new_day != old_day or new_hour != old_hour) and new_day and new_hour:
        await _sync_cloud_scheduler(
            int(new_day),
            int(new_hour),
            enabled=_as_enabled(new_enabled),
        )

    return await get_all(db, user_id=user_id, include_system=True)


async def _sync_cloud_scheduler(day: int, hour: int, *, enabled: bool) -> None:
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
            schedule_resp = await client.patch(
                f"https://cloudscheduler.googleapis.com/v1/{job_name}",
                json={"schedule": cron},
                params={"updateMask": "schedule"},
                headers={"Authorization": f"Bearer {credentials.token}"},
            )
            if schedule_resp.is_success:
                logger.info("Cloud Scheduler schedule updated to '%s'", cron)
            else:
                logger.warning(
                    "Cloud Scheduler schedule update failed: %s %s",
                    schedule_resp.status_code,
                    schedule_resp.text,
                )
                return

            job_resp = await client.get(
                f"https://cloudscheduler.googleapis.com/v1/{job_name}",
                headers={"Authorization": f"Bearer {credentials.token}"},
            )
            if not job_resp.is_success:
                logger.warning(
                    "Cloud Scheduler state read failed: %s %s",
                    job_resp.status_code,
                    job_resp.text,
                )
                return

            current_state = str(job_resp.json().get("state", "")).upper()
            desired_paused = not enabled
            if desired_paused and current_state != "PAUSED":
                state_resp = await client.post(
                    f"https://cloudscheduler.googleapis.com/v1/{job_name}:pause",
                    headers={"Authorization": f"Bearer {credentials.token}"},
                )
                if state_resp.is_success:
                    logger.info("Cloud Scheduler paused")
                else:
                    logger.warning(
                        "Cloud Scheduler pause failed: %s %s",
                        state_resp.status_code,
                        state_resp.text,
                    )
            if not desired_paused and current_state == "PAUSED":
                state_resp = await client.post(
                    f"https://cloudscheduler.googleapis.com/v1/{job_name}:resume",
                    headers={"Authorization": f"Bearer {credentials.token}"},
                )
                if state_resp.is_success:
                    logger.info("Cloud Scheduler resumed")
                else:
                    logger.warning(
                        "Cloud Scheduler resume failed: %s %s",
                        state_resp.status_code,
                        state_resp.text,
                    )
    except Exception:
        logger.warning("Failed to sync Cloud Scheduler", exc_info=True)
