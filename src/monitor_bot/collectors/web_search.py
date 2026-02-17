"""Collector that discovers tenders and events via Google Search.

Uses Gemini with Google Search grounding to execute configurable search
queries (e.g. "bandi innovazione digitale Italia 2026"), then fetches
each result page and extracts structured opportunity data.

This allows the bot to discover opportunities beyond the pre-configured
seed pages and RSS feeds.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from datetime import date, datetime
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from google import genai
from google.genai import types

from monitor_bot.collectors.base import BaseCollector
from monitor_bot.config import Settings
from monitor_bot.models import Opportunity, OpportunityType, Source

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
}

_MAX_TEXT_LENGTH = 15_000
_RATE_LIMIT_DELAY = 1.5

# ------------------------------------------------------------------ #
# Prompts                                                              #
# ------------------------------------------------------------------ #

_SEARCH_SYSTEM_PROMPT = """\
Sei un assistente specializzato nella ricerca di bandi pubblici ed eventi IT \
in Italia e in Europa.

Ti viene fornita una query di ricerca. Usa Google Search per trovare \
risultati pertinenti e recenti. Per ogni risultato rilevante, restituisci \
un oggetto JSON con:

- "url": l'URL della pagina trovata
- "title": il titolo del risultato
- "snippet": breve descrizione dal risultato di ricerca
- "type": "bando" oppure "evento"

Restituisci un array JSON con i risultati piu' rilevanti (massimo {max_results}).
Escludi:
- Risultati di Wikipedia, dizionari, enciclopedie
- Risultati di social media (Facebook, Twitter, LinkedIn)
- Risultati troppo generici (homepage senza bandi/eventi specifici)
- Risultati che puntano a PDF o file scaricabili

Concentrati su:
- Pagine di bandi pubblici (gare, appalti, finanziamenti, PNRR)
- Pagine di eventi IT (conferenze, summit, workshop, webinar)
- Portali istituzionali, regioni, agenzie
"""

_EXTRACTION_PROMPT = """\
Sei un assistente specializzato nell'estrazione di informazioni da pagine web \
relative a bandi pubblici o eventi IT.

Analizza il testo della pagina web fornita e determina se contiene un bando \
pubblico oppure un evento IT. Restituisci un singolo oggetto JSON con:

- "type" (stringa): "bando" oppure "evento" oppure "non_rilevante"
- "title" (stringa): titolo del bando o evento
- "description" (stringa): descrizione sintetica (3-5 frasi)
- "deadline" (stringa o null): scadenza/data in formato ISO (YYYY-MM-DD)
- "contracting_authority" (stringa): ente che pubblica (per bandi) o organizzatore (per eventi)
- "estimated_value" (numero o null): valore in EUR, se indicato (solo per bandi)
- "location" (stringa o null): luogo (solo per eventi)
- "country" (stringa): codice paese ISO a 2 lettere (default "IT")

Se la pagina NON contiene un bando o evento rilevante, restituisci:
{"type": "non_rilevante"}
"""


class WebSearchCollector(BaseCollector):
    """Discover tenders and events via Google Search using Gemini grounding."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._gemini_client = genai.Client(api_key=settings.gemini_api_key)
        self._model = settings.gemini_model
        self._queries = settings.web_search_queries
        self._max_per_query = settings.web_search_max_per_query
        self._http_client = httpx.AsyncClient(
            timeout=30.0, follow_redirects=True, headers=_HEADERS,
        )

    async def collect(self) -> list[Opportunity]:
        if not self._queries:
            logger.info("WebSearch: no search queries configured, skipping")
            return []

        logger.info(
            "WebSearch: executing %d search quer%s",
            len(self._queries),
            "y" if len(self._queries) == 1 else "ies",
        )

        try:
            # Phase 1: search and discover URLs
            discovered_urls = await self._phase_search()
            logger.info(
                "WebSearch: discovered %d unique URL(s) from search",
                len(discovered_urls),
            )

            if not discovered_urls:
                return []

            # Phase 2: fetch and extract from each discovered URL
            all_opportunities = await self._phase_extraction(discovered_urls)

        finally:
            await self._http_client.aclose()

        max_results = self.settings.max_results
        if max_results and len(all_opportunities) > max_results:
            all_opportunities = all_opportunities[:max_results]

        logger.info("WebSearch: collected %d opportunities total", len(all_opportunities))
        return all_opportunities

    # ------------------------------------------------------------------ #
    # Phase 1: Search via Gemini with Google Search grounding              #
    # ------------------------------------------------------------------ #

    async def _phase_search(self) -> list[dict]:
        """Execute each configured query via Gemini + Google Search."""
        all_results: list[dict] = []
        seen_urls: set[str] = set()

        for idx, query in enumerate(self._queries):
            try:
                results = await self._execute_search_query(query)
                for result in results:
                    url = result.get("url", "").strip()
                    if not url:
                        continue
                    normalised = url.rstrip("/").lower()
                    if normalised not in seen_urls:
                        seen_urls.add(normalised)
                        all_results.append(result)
                logger.info(
                    "WebSearch: [%d/%d] query '%s' -> %d result(s)",
                    idx + 1, len(self._queries), query[:50], len(results),
                )
            except Exception:
                logger.warning(
                    "WebSearch: [%d/%d] search failed for '%s'",
                    idx + 1, len(self._queries), query[:50],
                    exc_info=True,
                )

            if idx < len(self._queries) - 1:
                await asyncio.sleep(_RATE_LIMIT_DELAY)

        return all_results

    async def _execute_search_query(self, query: str) -> list[dict]:
        """Use Gemini with Google Search grounding to execute a query."""
        search_tool = types.Tool(google_search=types.GoogleSearch())
        prompt = (
            f"Cerca su Google: {query}\n\n"
            f"Restituisci i {self._max_per_query} risultati più rilevanti "
            f"come array JSON."
        )

        system_prompt = _SEARCH_SYSTEM_PROMPT.replace(
            "{max_results}", str(self._max_per_query),
        )

        response = await asyncio.to_thread(
            self._gemini_client.models.generate_content,
            model=self._model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                tools=[search_tool],
                response_mime_type="application/json",
                temperature=0.0,
            ),
        )

        text = response.text
        if not text:
            return []

        data = json.loads(text)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "results" in data:
            return data["results"]
        return []

    # ------------------------------------------------------------------ #
    # Phase 2: Fetch and extract from discovered URLs                      #
    # ------------------------------------------------------------------ #

    async def _phase_extraction(self, results: list[dict]) -> list[Opportunity]:
        """Fetch each discovered URL and extract opportunity data."""
        all_opportunities: list[Opportunity] = []

        for idx, result in enumerate(results):
            url = result.get("url", "")
            if not url:
                continue

            try:
                opp = await self._extract_from_page(url, result)
                if opp:
                    all_opportunities.append(opp)
                    logger.info(
                        "WebSearch: [%d/%d] %s -> %s",
                        idx + 1, len(results), url[:80], opp.title[:60],
                    )
                else:
                    logger.debug(
                        "WebSearch: [%d/%d] %s -> not relevant",
                        idx + 1, len(results), url[:80],
                    )
            except Exception:
                logger.warning(
                    "WebSearch: [%d/%d] extraction failed for %s",
                    idx + 1, len(results), url[:80],
                    exc_info=True,
                )

            if idx < len(results) - 1:
                await asyncio.sleep(_RATE_LIMIT_DELAY)

        return all_opportunities

    async def _extract_from_page(
        self, url: str, search_result: dict,
    ) -> Opportunity | None:
        """Fetch a page and use Gemini to extract opportunity data."""
        resp = await self._http_client.get(url)
        resp.raise_for_status()

        text = self._extract_text(resp.text)
        if not text or len(text.strip()) < 50:
            return None

        user_prompt = f"URL: {url}\n\nTesto della pagina:\n{text}"

        try:
            response = await asyncio.to_thread(
                self._gemini_client.models.generate_content,
                model=self._model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=_EXTRACTION_PROMPT,
                    response_mime_type="application/json",
                    temperature=0.0,
                ),
            )
            resp_text = response.text
            if not resp_text:
                return None

            data = json.loads(resp_text)
            if not isinstance(data, dict):
                return None

            opp_type = data.get("type", "non_rilevante")
            if opp_type == "non_rilevante" or not data.get("title"):
                return None

            return self._build_opportunity(data, url, search_result)

        except Exception:
            logger.warning(
                "WebSearch: Gemini extraction failed for %s", url[:80],
                exc_info=True,
            )
            return None

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _extract_text(html: str) -> str:
        """Extract readable text from HTML."""
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        clean = "\n".join(lines)
        if len(clean) > _MAX_TEXT_LENGTH:
            clean = clean[:_MAX_TEXT_LENGTH]
        return clean

    def _build_opportunity(
        self, data: dict, page_url: str, search_result: dict,
    ) -> Opportunity | None:
        """Convert extracted data into an Opportunity object."""
        title = (data.get("title") or "").strip()
        if not title:
            return None

        opp_type_str = data.get("type", "bando")
        if opp_type_str == "evento":
            opp_type = OpportunityType.EVENTO
        else:
            opp_type = OpportunityType.BANDO

        description = (data.get("description") or "").strip()
        authority = (data.get("contracting_authority") or self._domain_name(page_url)).strip()
        deadline = self._parse_date(data.get("deadline"))
        country = data.get("country", "IT") or "IT"
        location = data.get("location")

        value = data.get("estimated_value")
        if isinstance(value, str):
            value = re.sub(r"[^\d.,]", "", value)
            try:
                value = float(value.replace(".", "").replace(",", "."))
            except ValueError:
                value = None

        if location and opp_type == OpportunityType.EVENTO:
            description = f"{description}\n📍 {location}" if description else f"📍 {location}"

        short_hash = hashlib.sha256(
            f"{page_url}:{title}".encode(),
        ).hexdigest()[:12]

        return Opportunity(
            id=f"SEARCH-{short_hash}",
            title=title,
            description=description[:500],
            contracting_authority=authority,
            deadline=deadline,
            estimated_value=value if isinstance(value, (int, float)) else None,
            currency="EUR",
            country=country,
            source_url=page_url,
            source=Source.WEB_SEARCH,
            opportunity_type=opp_type,
            publication_date=date.today(),
            cpv_codes=[],
        )

    @staticmethod
    def _parse_date(value: str | None) -> date | None:
        """Parse a date string in various formats."""
        if not value:
            return None
        raw = str(value).strip()
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(raw[:19], fmt).date()
            except ValueError:
                continue
        return None

    @staticmethod
    def _domain_name(url: str) -> str:
        """Extract a human-readable domain name from a URL."""
        try:
            host = urlparse(url).hostname or ""
            host = host.removeprefix("www.")
            return host
        except Exception:
            return url
