"""Service layer for application settings (key-value store)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from monitor_bot.db_models import AppSetting

DEFAULTS: dict[str, str] = {
    "relevance_threshold": "6",
    "company_name": "",
    "company_sector": "",
    "company_competencies": "SAP,Data,AI,Cloud",
    "company_certifications": "",
    "company_budget_min": "100000",
    "company_budget_max": "50000000",
    "company_regions": "Italia,EMEA",
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
    for key, value in data.items():
        setting = await db.get(AppSetting, key)
        if setting:
            setting.value = str(value)
        else:
            db.add(AppSetting(key=key, value=str(value)))
    await db.commit()
    return await get_all(db)
