"""Service layer for application settings (key-value store)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from monitor_bot.db_models import AppSetting

DEFAULTS: dict[str, str] = {
    "relevance_threshold": "6",
    "company_name": "",
    "company_sector": "IT Consulting & Services",
    "company_competencies": "SAP,Data Engineering,AI / Machine Learning,Cloud Infrastructure",
    "company_certifications": "Certificazioni e track record per appalti pubblici in Italia e UE",
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
    for key, value in data.items():
        setting = await db.get(AppSetting, key)
        if setting:
            setting.value = str(value)
        else:
            db.add(AppSetting(key=key, value=str(value)))
    await db.commit()
    return await get_all(db)
