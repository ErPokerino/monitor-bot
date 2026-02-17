"""Collector for TED (Tenders Electronic Daily) via the Search API v3."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime, timedelta

import httpx

from monitor_bot.collectors.base import BaseCollector
from monitor_bot.config import Settings
from monitor_bot.models import Opportunity, OpportunityType, Source

logger = logging.getLogger(__name__)

TED_SEARCH_URL = "https://api.ted.europa.eu/v3/notices/search"

# Rate-limiting / retry settings
_PAGE_DELAY = 0.5        # seconds between consecutive page requests
_MAX_RETRIES = 4         # retries on 429 / 5xx
_RETRY_BASE_DELAY = 3.0  # seconds (multiplied by attempt number)

# Notice types that represent OPEN opportunities (calls for competition).
# Everything else (can-*, veat, compl, can-modif, …) is a result or closed notice.
_OPEN_NOTICE_TYPES = (
    "cn-standard",       # Contract notice – standard regime
    "cn-social",         # Contract notice – light regime
    "cn-desg",           # Design contest notice
    "pin-cfc-standard",  # PIN used as call for competition – standard
    "pin-cfc-social",    # PIN used as call for competition – light
)

# Keywords that identify already-awarded/closed notices (safety net for normalisation)
_CLOSED_KEYWORDS = (
    "result", "award", "awarded", "winner", "aggiudicazione", "esito",
    "modification", "completion", "voluntary ex-ante", "veat",
)

# Fields we request from the TED API (human-readable search-field names)
REQUESTED_FIELDS = [
    "publication-number",
    "notice-title",
    "description-proc",
    "description-lot",
    "buyer-name",
    "buyer-country",
    "deadline-receipt-tender-date-lot",
    "estimated-value-proc",
    "estimated-value-lot",
    "classification-cpv",
    "notice-type",
    "dispatch-date",
]

# TED uses 3-letter ISO country codes. Map from 2-letter (used in config) to 3-letter.
_COUNTRY_MAP: dict[str, str] = {
    "AT": "AUT", "BE": "BEL", "BG": "BGR", "HR": "HRV", "CY": "CYP",
    "CZ": "CZE", "DK": "DNK", "EE": "EST", "FI": "FIN", "FR": "FRA",
    "DE": "DEU", "GR": "GRC", "HU": "HUN", "IE": "IRL", "IT": "ITA",
    "LV": "LVA", "LT": "LTU", "LU": "LUX", "MT": "MLT", "NL": "NLD",
    "PL": "POL", "PT": "PRT", "RO": "ROU", "SK": "SVK", "SI": "SVN",
    "ES": "ESP", "SE": "SWE", "IS": "ISL", "LI": "LIE", "NO": "NOR",
    "CH": "CHE", "GB": "GBR", "TR": "TUR", "IL": "ISR", "AE": "ARE",
    "SA": "SAU", "ZA": "ZAF",
}


class TEDCollector(BaseCollector):
    """Fetch IT-related procurement notices from TED."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._client = httpx.AsyncClient(timeout=60.0)

    async def collect(self) -> list[Opportunity]:
        logger.info("TED: starting collection (lookback=%d days)", self.settings.lookback_days)
        try:
            raw_notices = await self._search_notices()
            opportunities = self._normalise(raw_notices)
            logger.info("TED: collected %d opportunities", len(opportunities))
            return opportunities
        except Exception:
            logger.exception("TED: collection failed")
            return []
        finally:
            await self._client.aclose()

    # ------------------------------------------------------------------
    # Query building
    # ------------------------------------------------------------------

    def _build_query(self) -> str:
        """Build an expert-search query for the TED Search API.

        Uses the human-readable field names and short-hand aliases documented at
        https://docs.ted.europa.eu/ODS/latest/reuse/field-list.html
        and the notice-type codelist from
        https://docs.ted.europa.eu/eforms/latest/reference/code-lists/notice-type.html
        """
        since = date.today() - timedelta(days=self.settings.lookback_days)

        # Only OPEN opportunities (calls for competition, not results/awards)
        # Field is "notice-type" (not the alias "TD" which doesn't support eForms values)
        td_clauses = " OR ".join(f"notice-type = {nt}" for nt in _OPEN_NOTICE_TYPES)
        td_filter = f"({td_clauses})"

        # CPV filter (PC = classification-cpv)
        cpv_clauses = " OR ".join(f"PC = {cpv}*" for cpv in self.settings.cpv_codes)
        cpv_filter = f"({cpv_clauses})"

        # Country filter (CY = buyer-country) – use 3-letter codes
        ted_countries = [
            _COUNTRY_MAP.get(c, c) for c in self.settings.countries
        ]
        country_clauses = " OR ".join(f"buyer-country = {c}" for c in ted_countries)
        country_filter = f"({country_clauses})"

        # Date filter (PD = publication date, format YYYYMMDD)
        date_filter = f"PD >= {since.strftime('%Y%m%d')}"

        return f"{td_filter} AND {cpv_filter} AND {country_filter} AND {date_filter}"

    # ------------------------------------------------------------------
    # API interaction
    # ------------------------------------------------------------------

    async def _post_with_retry(self, body: dict) -> httpx.Response:
        """POST to TED Search API with retry on 429 / transient errors."""
        for attempt in range(1, _MAX_RETRIES + 1):
            resp = await self._client.post(TED_SEARCH_URL, json=body)
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else _RETRY_BASE_DELAY * attempt
                logger.warning(
                    "TED: rate-limited (429), waiting %.1fs (attempt %d/%d)",
                    delay, attempt, _MAX_RETRIES,
                )
                await asyncio.sleep(delay)
                continue
            if resp.status_code >= 500:
                delay = _RETRY_BASE_DELAY * attempt
                logger.warning(
                    "TED: server error %d, waiting %.1fs (attempt %d/%d)",
                    resp.status_code, delay, attempt, _MAX_RETRIES,
                )
                await asyncio.sleep(delay)
                continue
            resp.raise_for_status()
            return resp
        # Final attempt – let it raise if it fails
        resp = await self._client.post(TED_SEARCH_URL, json=body)
        resp.raise_for_status()
        return resp

    async def _search_notices(self) -> list[dict]:
        """Page through TED Search results and return raw notice dicts."""
        query = self._build_query()
        logger.info("TED query: %s", query[:200])

        max_results = self.settings.max_results
        all_notices: list[dict] = []
        page = 1
        limit = 100

        while True:
            body = {
                "query": query,
                "fields": REQUESTED_FIELDS,
                "page": page,
                "limit": limit,
                "scope": "ALL",
                "paginationMode": "PAGE_NUMBER",
            }
            resp = await self._post_with_retry(body)
            data = resp.json()

            notices = data.get("notices", [])
            all_notices.extend(notices)

            total = data.get("totalNoticeCount", 0)
            logger.info("TED: page %d – fetched %d / %d total", page, len(all_notices), total)

            # Stop if we have enough results (max_results cap)
            if max_results and len(all_notices) >= max_results:
                all_notices = all_notices[:max_results]
                logger.info("TED: reached max_results cap (%d), stopping", max_results)
                break

            if len(all_notices) >= total or not notices:
                break
            page += 1
            # Polite delay between pages to avoid 429
            await asyncio.sleep(_PAGE_DELAY)

        return all_notices

    # ------------------------------------------------------------------
    # Normalisation
    # ------------------------------------------------------------------

    def _normalise(self, raw_notices: list[dict]) -> list[Opportunity]:
        results: list[Opportunity] = []
        skipped = 0
        for notice in raw_notices:
            try:
                # Safety net: skip notices that look like results/awards
                if self._is_closed(notice):
                    skipped += 1
                    continue

                pub_number = notice.get("publication-number", "")
                opp = Opportunity(
                    id=f"TED-{pub_number}",
                    title=self._extract_text(notice, "notice-title")
                    or self._extract_text(notice, "description-lot")
                    or self._extract_text(notice, "description-proc")
                    or "Untitled",
                    description=self._extract_text(notice, "description-lot")
                    or self._extract_text(notice, "description-proc")
                    or "",
                    contracting_authority=self._extract_text(notice, "buyer-name") or "",
                    deadline=self._parse_date(
                        self._extract_first(notice, "deadline-receipt-tender-date-lot")
                    ),
                    estimated_value=self._parse_float(
                        self._extract_first(notice, "estimated-value-lot")
                        or notice.get("estimated-value-proc")
                    ),
                    currency="EUR",
                    country=self._extract_country(notice),
                    source_url=(
                        f"https://ted.europa.eu/udl?uri=TED:NOTICE:{pub_number}:DATA:EN:HTML"
                        if pub_number
                        else ""
                    ),
                    source=Source.TED,
                    opportunity_type=self._detect_type(notice),
                    publication_date=self._parse_date(
                        self._extract_first(notice, "dispatch-date")
                    ),
                    cpv_codes=notice.get("classification-cpv", []),
                )
                results.append(opp)
            except Exception:
                logger.warning(
                    "TED: failed to normalise notice %s",
                    notice.get("publication-number", "?"),
                )
        if skipped:
            logger.info("TED: skipped %d closed/awarded notices during normalisation", skipped)
        return results

    @staticmethod
    def _is_closed(notice: dict) -> bool:
        """Return True if the notice is a result/award (not an open opportunity)."""
        notice_type = str(notice.get("notice-type", "")).lower().strip()

        # Check against open types whitelist (if we got a TD value back)
        if notice_type and notice_type not in {nt.lower() for nt in _OPEN_NOTICE_TYPES}:
            # Notice type is set but not in our open list — likely a result
            return True

        # Keyword-based fallback: check notice-type and title for closed indicators
        title = str(notice.get("notice-title", ""))
        if isinstance(title, dict):
            title = str(next(iter(title.values()), ""))
        blob = f"{notice_type} {title}".lower()
        return any(kw in blob for kw in _CLOSED_KEYWORDS)

    @staticmethod
    def _detect_type(notice: dict) -> OpportunityType:
        """Detect if a TED notice is a 'bando' or 'concorso'."""
        notice_type = str(notice.get("notice-type", "")).lower()
        title = str(notice.get("notice-title", "")).lower()
        _contest_keywords = ("design contest", "concorso", "contest", "competition")
        if any(kw in notice_type for kw in _contest_keywords):
            return OpportunityType.CONCORSO
        if any(kw in title for kw in _contest_keywords):
            return OpportunityType.CONCORSO
        return OpportunityType.BANDO

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_text(notice: dict, field: str) -> str | None:
        """Extract a human-readable text from a TED language-keyed field.

        TED returns fields like ``{"ita": ["some text"], "eng": ["other text"]}``.
        We prefer English, then Italian, then take the first available language.
        """
        value = notice.get(field)
        if value is None:
            return None
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return value[0] if value else None
        if isinstance(value, dict):
            for lang in ("eng", "ENG", "ita", "ITA"):
                if lang in value:
                    texts = value[lang]
                    if isinstance(texts, list) and texts:
                        return texts[0]
                    return str(texts)
            # Fallback: first available language
            for texts in value.values():
                if isinstance(texts, list) and texts:
                    return texts[0]
                return str(texts)
        return None

    @staticmethod
    def _extract_first(notice: dict, field: str) -> str | None:
        """Extract the first scalar value from a field (list or dict)."""
        value = notice.get(field)
        if value is None:
            return None
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return value[0] if value else None
        if isinstance(value, dict):
            for v in value.values():
                if isinstance(v, list) and v:
                    return v[0]
                return str(v)
        return str(value)

    @staticmethod
    def _extract_country(notice: dict) -> str:
        value = notice.get("buyer-country")
        if not value:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return value[0] if value else ""
        if isinstance(value, dict):
            for v in value.values():
                if isinstance(v, list) and v:
                    return v[0]
                return str(v)
        return ""

    @staticmethod
    def _parse_date(value: str | None) -> date | None:
        if not value:
            return None
        raw = str(value).strip()
        # Strip timezone offsets like "+01:00", "+02:00", "Z" that the TED API
        # appends to dates (e.g. "2026-03-03+01:00").
        raw = re.sub(r"[Z]$|[+-]\d{2}:\d{2}$", "", raw)
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%Y%m%d"):
            try:
                return datetime.strptime(raw[:19], fmt).date()
            except ValueError:
                continue
        return None

    @staticmethod
    def _parse_float(value: str | list | None) -> float | None:
        if not value:
            return None
        if isinstance(value, list):
            value = value[0] if value else None
        try:
            return float(str(value).replace(",", "").replace(" ", ""))
        except (ValueError, TypeError):
            return None
