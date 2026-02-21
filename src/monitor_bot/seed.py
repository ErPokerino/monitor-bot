"""Seed the database with default sources and queries from config.toml on first run."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from monitor_bot.config import Settings
from monitor_bot.db_models import SourceCategory, SourceType
from monitor_bot.schemas import QueryCreate, SourceCreate
from monitor_bot.services import queries as query_svc
from monitor_bot.services import sources as source_svc

logger = logging.getLogger(__name__)

BUILTIN_BANDI_SOURCES: list[tuple[str, str, SourceType]] = [
    ("TED - Tenders Electronic Daily", "https://ted.europa.eu/", SourceType.TENDER_PORTAL),
    ("ANAC Open Data", "https://dati.anticorruzione.it/opendata", SourceType.TENDER_PORTAL),
]

REGIONAL_TENDER_SOURCES: list[tuple[str, str]] = [
    ("Bandi Regione Lombardia", "https://www.bandi.regione.lombardia.it/servizi/home"),
    ("Bandi Regione Lazio", "https://www.regione.lazio.it/cittadini/attivita-produttive-e-commercio"),
    ("Bandi Emilia-Romagna", "https://imprese.regione.emilia-romagna.it/Finanziamenti/finanziamenti-in-corso"),
    ("Bandi Regione Piemonte", "https://bfrancesi.regione.piemonte.it/bandi-piemonte"),
    ("Bandi Regione Veneto", "https://www.regione.veneto.it/web/programmi-comunitari/fesr-2021-2027"),
    ("PNRR Italia Domani", "https://www.italiadomani.gov.it/content/sogei-ng/it/it/Avvisi.html"),
]


def _guess_query_category(text: str) -> SourceCategory:
    """Infer category from query text using simple keyword matching."""
    lower = text.lower()
    bandi_kw = ("bandi", "gare", "appalti", "tender", "procurement", "pnrr")
    fondi_kw = ("fondi", "finanziament", "funding", "grant")
    if any(kw in lower for kw in fondi_kw):
        return SourceCategory.FONDI
    if any(kw in lower for kw in bandi_kw):
        return SourceCategory.BANDI
    return SourceCategory.EVENTI


def _domain_label(url: str) -> str:
    """Extract a readable label from a URL."""
    from urllib.parse import urlparse
    try:
        host = urlparse(url).hostname or url
        return host.removeprefix("www.")
    except Exception:
        return url[:60]


async def _create_source_if_new(
    db: AsyncSession,
    name: str,
    url: str,
    category: SourceCategory,
    source_type: SourceType,
) -> bool:
    if await source_svc.source_url_exists(db, url):
        return False
    await source_svc.create_source(db, SourceCreate(
        name=name, url=url, category=category, source_type=source_type,
    ))
    return True


async def seed_defaults(db: AsyncSession, settings: Settings) -> None:
    """Insert default sources and queries if the DB is empty."""
    existing_sources = await source_svc.count_sources(db)
    existing_queries = await query_svc.count_queries(db)

    if existing_sources > 0 or existing_queries > 0:
        logger.info("Database already seeded (%d sources, %d queries)", existing_sources, existing_queries)
        return

    logger.info("Seeding database with defaults from config.toml...")
    created_sources = 0
    created_queries = 0

    for url in settings.event_feeds:
        if await _create_source_if_new(
            db, _domain_label(url), url, SourceCategory.EVENTI, SourceType.RSS_FEED,
        ):
            created_sources += 1

    for url in settings.event_web_pages:
        if await _create_source_if_new(
            db, _domain_label(url), url, SourceCategory.EVENTI, SourceType.WEB_PAGE,
        ):
            created_sources += 1

    for name, url, stype in BUILTIN_BANDI_SOURCES:
        if await _create_source_if_new(db, name, url, SourceCategory.BANDI, stype):
            created_sources += 1

    for name, url in REGIONAL_TENDER_SOURCES:
        if await _create_source_if_new(
            db, name, url, SourceCategory.BANDI, SourceType.TENDER_PORTAL,
        ):
            created_sources += 1

    for url in settings.web_tender_pages:
        if await _create_source_if_new(
            db, _domain_label(url), url, SourceCategory.BANDI, SourceType.TENDER_PORTAL,
        ):
            created_sources += 1

    for text in settings.web_search_queries:
        if not await query_svc.query_text_exists(db, text):
            cat = _guess_query_category(text)
            await query_svc.create_query(db, QueryCreate(
                query_text=text,
                category=cat,
                max_results=settings.web_search_max_per_query,
            ))
            created_queries += 1

    logger.info("Seeded %d sources and %d queries", created_sources, created_queries)
