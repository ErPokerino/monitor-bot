"""Collector for Italian regional tenders from web portals.

Scrapes regional tender listing pages (e.g. bandi.regione.lombardia.it,
bandi.regione.lazio.it, etc.) using a two-phase approach:

Phase 1 – **Discovery**: fetches each seed page, extracts links, and asks
Gemini to filter those pointing to specific IT/innovation tender pages.

Phase 2 – **Extraction**: fetches each discovered tender page and uses
Gemini to extract structured tender information (title, deadline, value,
description, contracting authority).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from datetime import date, datetime
from urllib.parse import urljoin, urlparse

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
_MAX_LINKS_TO_GEMINI = 150
_MAX_TENDER_PAGES = 20
_RATE_LIMIT_DELAY = 1.0

# ------------------------------------------------------------------ #
# Prompts                                                              #
# ------------------------------------------------------------------ #

_DISCOVERY_PROMPT = """\
Sei un assistente specializzato nell'identificazione di bandi pubblici \
italiani relativi a IT, innovazione, digitale e tecnologia.

Ti viene fornita una lista di URL estratti da un portale di bandi regionali \
italiano (es. bandi.regione.lombardia.it, bandi.regione.lazio.it, ecc.). \
Il tuo compito è filtrare questa lista e restituire SOLO gli URL che \
puntano a **bandi specifici** rilevanti per un'azienda IT, con focus su:

- Bandi per innovazione, ricerca e sviluppo tecnologico
- Bandi per digitalizzazione, transizione digitale, Industria 4.0
- Bandi per servizi IT, consulenza informatica, sviluppo software
- Bandi per intelligenza artificiale, cloud, data, cybersecurity
- Bandi legati a fondi PNRR, FESR, FSE per ambiti digitali/IT
- Bandi per cluster tecnologici, smart city, PA digitale

ESCLUDI:
- Bandi per settori non IT (agricoltura, edilizia, sanità generica, turismo, cultura)
- Link a pagine generiche (home, FAQ, login, normativa, privacy)
- Link a documenti PDF, allegati, moduli
- Link a pagine di altri siti non correlati

Restituisci un array JSON:
[
  {
    "url": "https://...",
    "reason": "breve motivazione per cui è un bando IT rilevante"
  }
]

Se nessun link è rilevante, restituisci [].
Seleziona al massimo 10 URL per pagina seed.
"""

_EXTRACTION_PROMPT = """\
Sei un assistente specializzato nell'estrazione di informazioni da pagine \
web di bandi pubblici italiani (regionali, nazionali, PNRR, FESR, ecc.).

Analizza il testo della pagina web fornita ed estrai le informazioni del \
bando. Restituisci un singolo oggetto JSON con questi campi:

- "title" (stringa): il titolo completo del bando
- "description" (stringa): descrizione sintetica (3-5 frasi) del bando, \
  obiettivi e ambito
- "deadline" (stringa o null): data di scadenza in formato ISO (YYYY-MM-DD). \
  Cerca "scade il", "scadenza", "termine presentazione domande", ecc. \
  Se non trovi la data, null.
- "contracting_authority" (stringa): l'ente che pubblica il bando (es. \
  "Regione Lombardia", "Regione Lazio", ecc.)
- "estimated_value" (numero o null): dotazione finanziaria in EUR, se indicata
- "requirements" (lista di stringhe): requisiti principali per partecipare \
  (max 5 punti)
- "url" (stringa): URL DIRETTO alla pagina del bando specifico. \
  IMPORTANTE: Se la pagina è un elenco/catalogo con più bandi, devi \
  restituire l'URL della pagina di DETTAGLIO del bando, NON l'URL \
  della pagina di elenco. Cerca tra i link forniti quello che punta \
  alla scheda specifica del bando estratto. L'URL deve permettere \
  all'utente di arrivare direttamente alla pagina del bando.

Se la pagina NON contiene un bando pubblico rilevante, restituisci:
{"title": null}
"""


class WebTendersCollector(BaseCollector):
    """Fetch Italian regional tenders from web portals using two-phase crawling."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._http_client = httpx.AsyncClient(
            timeout=30.0, follow_redirects=True, headers=_HEADERS,
        )
        self._gemini_client = genai.Client(api_key=settings.gemini_api_key)
        self._model = settings.gemini_model
        self._pages = settings.web_tender_pages

    async def collect(self) -> list[Opportunity]:
        if not self._pages:
            logger.info("WebTenders: no tender pages configured, skipping")
            return []

        logger.info(
            "WebTenders: starting two-phase collection from %d seed page(s)",
            len(self._pages),
        )

        try:
            # Phase 1: discover tender links from seed pages
            tender_links = await self._phase_discovery()
            logger.info(
                "WebTenders: phase 1 complete – %d tender link(s) discovered",
                len(tender_links),
            )

            if not tender_links:
                logger.info("WebTenders: no links discovered, using seed pages directly")
                tender_links = list(self._pages)

            # Phase 2: extract tender details from each discovered page
            all_opportunities = await self._phase_extraction(tender_links)

        finally:
            await self._http_client.aclose()

        max_results = self.settings.max_results
        if max_results and len(all_opportunities) > max_results:
            all_opportunities = all_opportunities[:max_results]

        logger.info("WebTenders: collected %d tenders total", len(all_opportunities))
        return all_opportunities

    # ------------------------------------------------------------------ #
    # Phase 1: Discovery                                                   #
    # ------------------------------------------------------------------ #

    async def _phase_discovery(self) -> list[str]:
        """Fetch each seed page, extract links, and ask Gemini to filter."""
        all_discovered: list[str] = []
        seen_urls: set[str] = set()

        for idx, seed_url in enumerate(self._pages):
            try:
                links = await self._discover_from_seed(seed_url)
                for link in links:
                    normalised = link.rstrip("/").lower()
                    if normalised not in seen_urls:
                        seen_urls.add(normalised)
                        all_discovered.append(link)
            except Exception:
                logger.warning(
                    "WebTenders: discovery failed for seed %s", seed_url,
                    exc_info=True,
                )

            if idx < len(self._pages) - 1:
                await asyncio.sleep(_RATE_LIMIT_DELAY)

        if len(all_discovered) > _MAX_TENDER_PAGES:
            all_discovered = all_discovered[:_MAX_TENDER_PAGES]

        return all_discovered

    async def _discover_from_seed(self, seed_url: str) -> list[str]:
        """Fetch a seed page and use Gemini to identify tender links."""
        resp = await self._http_client.get(seed_url)
        resp.raise_for_status()

        links = self._extract_links(resp.text, seed_url)
        if not links:
            logger.debug("WebTenders: no links found on seed %s", seed_url)
            return []

        logger.debug(
            "WebTenders: extracted %d links from %s, filtering with Gemini",
            len(links), seed_url,
        )

        links_for_prompt = links[:_MAX_LINKS_TO_GEMINI]
        user_prompt = (
            f"Portale bandi seed: {seed_url}\n\n"
            f"Lista di {len(links_for_prompt)} URL trovati nella pagina:\n"
            + "\n".join(f"- {url}" for url in links_for_prompt)
        )

        try:
            response = await asyncio.to_thread(
                self._gemini_client.models.generate_content,
                model=self._model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=_DISCOVERY_PROMPT,
                    response_mime_type="application/json",
                    temperature=0.0,
                ),
            )
            text = response.text
            if not text:
                return []

            data = json.loads(text)
            if isinstance(data, list):
                return [
                    item["url"] for item in data
                    if isinstance(item, dict) and item.get("url")
                ]
            return []
        except Exception:
            logger.warning(
                "WebTenders: Gemini link filtering failed for %s", seed_url,
                exc_info=True,
            )
            return []

    @staticmethod
    def _extract_links(html: str, base_url: str) -> list[str]:
        """Extract all unique http(s) links from an HTML page."""
        soup = BeautifulSoup(html, "html.parser")

        seen: set[str] = set()
        links: list[str] = []

        for tag in soup.find_all("a", href=True):
            href = tag["href"].strip()
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue

            absolute = urljoin(base_url, href)
            absolute = re.sub(r"#.*$", "", absolute)
            if not absolute.startswith("http"):
                continue

            normalised = absolute.rstrip("/").lower()
            if normalised in seen:
                continue
            seen.add(normalised)

            parsed = urlparse(absolute)
            path_lower = (parsed.path or "").lower()
            if any(skip in path_lower for skip in (
                "/login", "/signup", "/register", "/cart", "/checkout",
                "/privacy", "/terms", "/cookie", "/legal",
                ".pdf", ".zip", ".png", ".jpg", ".svg", ".xlsx", ".docx",
            )):
                continue

            links.append(absolute)

        return links

    # ------------------------------------------------------------------ #
    # Phase 2: Extraction                                                  #
    # ------------------------------------------------------------------ #

    async def _phase_extraction(self, tender_urls: list[str]) -> list[Opportunity]:
        """Fetch each tender page and extract structured tender data."""
        all_opportunities: list[Opportunity] = []

        for idx, url in enumerate(tender_urls):
            try:
                opp = await self._extract_from_page(url)
                if opp:
                    all_opportunities.append(opp)
                    logger.info(
                        "WebTenders: [%d/%d] %s -> %s",
                        idx + 1, len(tender_urls), url[:80],
                        opp.title[:60],
                    )
                else:
                    logger.debug(
                        "WebTenders: [%d/%d] %s -> no relevant tender found",
                        idx + 1, len(tender_urls), url[:80],
                    )
            except Exception:
                logger.warning(
                    "WebTenders: [%d/%d] extraction failed for %s",
                    idx + 1, len(tender_urls), url[:80],
                    exc_info=True,
                )

            if idx < len(tender_urls) - 1:
                await asyncio.sleep(_RATE_LIMIT_DELAY)

        return all_opportunities

    async def _extract_from_page(self, url: str) -> Opportunity | None:
        """Fetch a single tender page and use Gemini to extract details."""
        resp = await self._http_client.get(url)
        resp.raise_for_status()

        html = resp.text
        text = self._extract_text(html)
        if not text or len(text.strip()) < 50:
            logger.debug("WebTenders: page %s yielded too little text", url)
            return None

        # Also extract links so Gemini can identify the specific tender URL
        page_links = self._extract_links(html, url)

        tender_data = await self._call_gemini_extraction(text, url, page_links)
        if not tender_data or not tender_data.get("title"):
            return None

        return self._build_opportunity(tender_data, url)

    @staticmethod
    def _extract_text(html: str) -> str:
        """Extract readable text from HTML."""
        soup = BeautifulSoup(html, "html.parser")

        for tag in soup(["script", "style", "nav", "noscript"]):
            tag.decompose()

        text = soup.get_text(separator="\n", strip=True)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        clean = "\n".join(lines)

        if len(clean) > _MAX_TEXT_LENGTH:
            clean = clean[:_MAX_TEXT_LENGTH]

        return clean

    async def _call_gemini_extraction(
        self, page_text: str, source_url: str,
        page_links: list[str] | None = None,
    ) -> dict | None:
        """Send page text to Gemini and get structured tender data back."""
        links_section = ""
        if page_links:
            # Include up to 80 links so Gemini can find specific tender URLs
            relevant_links = page_links[:80]
            links_section = (
                "\n\nLink trovati nella pagina (usa questi per il campo 'url'):\n"
                + "\n".join(f"- {lnk}" for lnk in relevant_links)
            )

        user_prompt = (
            f"URL della pagina: {source_url}\n\n"
            f"Testo della pagina:\n{page_text}"
            f"{links_section}"
        )

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
            text = response.text
            if not text:
                return None

            data = json.loads(text)
            if isinstance(data, dict):
                return data
            return None

        except Exception:
            logger.exception("WebTenders: Gemini extraction failed for %s", source_url)
            return None

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _build_opportunity(self, data: dict, page_url: str) -> Opportunity | None:
        """Convert Gemini-extracted tender data into an Opportunity object."""
        title = (data.get("title") or "").strip()
        if not title:
            return None

        description = (data.get("description") or "").strip()
        authority = (data.get("contracting_authority") or self._domain_name(page_url)).strip()

        # Prefer the specific URL returned by Gemini over the page URL
        gemini_url = (data.get("url") or "").strip()
        if gemini_url and gemini_url.startswith("http"):
            tender_url = gemini_url
        else:
            tender_url = page_url
        deadline = self._parse_date(data.get("deadline"))
        value = data.get("estimated_value")

        if isinstance(value, str):
            value = re.sub(r"[^\d.,]", "", value)
            try:
                value = float(value.replace(".", "").replace(",", "."))
            except ValueError:
                value = None

        requirements = data.get("requirements", [])
        if requirements and isinstance(requirements, list):
            req_text = "\n".join(f"• {r}" for r in requirements[:5])
            if description:
                description = f"{description}\n\n{req_text}"
            else:
                description = req_text

        short_hash = hashlib.sha256(
            f"{page_url}:{title}".encode(),
        ).hexdigest()[:12]

        return Opportunity(
            id=f"REG-{short_hash}",
            title=title,
            description=description[:500],
            contracting_authority=authority,
            deadline=deadline,
            estimated_value=value if isinstance(value, (int, float)) else None,
            currency="EUR",
            country="IT",
            source_url=tender_url,
            source=Source.REGIONALE,
            opportunity_type=OpportunityType.BANDO,
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
