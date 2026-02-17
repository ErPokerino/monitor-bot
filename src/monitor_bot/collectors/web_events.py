"""Collector for IT events from web pages (non-RSS) via two-phase crawling.

Phase 1 – **Discovery**: each configured *seed page* (e.g.
``cloud.google.com/events?hl=it``) is fetched and all ``<a href>`` links are
extracted.  Gemini is asked to filter those links to keep only the ones
pointing to specific IT event pages relevant to EMEA / Italy.

Phase 2 – **Extraction**: every discovered event link is fetched individually
and Gemini extracts structured event details (title, date, location, etc.).
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
_MAX_LINKS_TO_GEMINI = 200
_MAX_EVENT_PAGES = 30
_RATE_LIMIT_DELAY = 1.0

# ------------------------------------------------------------------ #
# Prompts                                                              #
# ------------------------------------------------------------------ #

_DISCOVERY_PROMPT = """\
Sei un assistente specializzato nell'identificazione di link a pagine di eventi IT.

Ti viene fornita una lista di URL estratti da una pagina web "seed" (un portale \
eventi o la sezione eventi di un vendor tecnologico). Il tuo compito è filtrare \
questa lista e restituire SOLO gli URL che puntano a **pagine di singoli eventi \
IT specifici** rilevanti, con attenzione particolare a:

- Eventi in Italia o in area EMEA
- Eventi relativi a: AI, Cloud, Data, SAP, innovazione digitale, cybersecurity, \
  DevOps, machine learning, pubblica amministrazione digitale
- Conferenze, summit, workshop, webinar, meetup, hackathon

ESCLUDI:
- Link a pagine generiche (home, about, privacy policy, terms, login, careers)
- Link a blog post o articoli di notizie (NON eventi)
- Link a documentazione o prodotti
- Link a social media o risorse esterne non correlate
- Link a pagine già nella lista seed (directory pagine eventi)

Restituisci un array JSON di oggetti con questa struttura:
[
  {
    "url": "https://...",
    "reason": "breve motivazione per cui è un evento rilevante"
  }
]

Se nessun link è rilevante, restituisci un array vuoto [].
Seleziona al massimo 15 URL per seed page.
"""

_EXTRACTION_PROMPT = """\
Sei un assistente specializzato nell'estrazione di informazioni sugli eventi IT \
da pagine web. Analizza il testo della pagina web fornita ed estrai tutti gli \
eventi IT rilevanti.

Per ogni evento trovato, restituisci un oggetto JSON con questi campi:
- "title" (stringa): il nome dell'evento
- "description" (stringa): una breve descrizione dell'evento (2-3 frasi)
- "event_date" (stringa o null): la data dell'evento in formato ISO (YYYY-MM-DD). \
  Se l'evento dura più giorni, usa la data di inizio. Se non trovi la data, null.
- "location" (stringa o null): il luogo dell'evento (città, sede, online, etc.)
- "url" (stringa o null): URL specifico dell'evento, se diverso dall'URL della pagina

Restituisci un array JSON di eventi. Se la pagina non contiene eventi IT rilevanti, \
restituisci un array vuoto [].

Concentrati su eventi futuri o recenti relativi a tecnologia, IT, AI, cloud, \
dati, SAP, innovazione digitale, pubblica amministrazione digitale.\
"""


class WebEventsCollector(BaseCollector):
    """Fetch IT events from HTML web pages using two-phase crawling."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._http_client = httpx.AsyncClient(
            timeout=30.0, follow_redirects=True, headers=_HEADERS,
        )
        self._gemini_client = genai.Client(api_key=settings.gemini_api_key)
        self._model = settings.gemini_model
        self._pages = settings.event_web_pages

    async def collect(self) -> list[Opportunity]:
        if not self._pages:
            logger.info("WebEvents: no web pages configured, skipping")
            return []

        logger.info(
            "WebEvents: starting two-phase collection from %d seed page(s)",
            len(self._pages),
        )

        try:
            # Phase 1: discover event links from seed pages
            event_links = await self._phase_discovery()
            logger.info(
                "WebEvents: phase 1 complete – %d event link(s) discovered",
                len(event_links),
            )

            if not event_links:
                # Fallback: treat seed pages themselves as event pages
                logger.info("WebEvents: no links discovered, using seed pages directly")
                event_links = list(self._pages)

            # Phase 2: extract event details from each discovered page
            all_opportunities = await self._phase_extraction(event_links)

        finally:
            await self._http_client.aclose()

        max_results = self.settings.max_results
        if max_results and len(all_opportunities) > max_results:
            all_opportunities = all_opportunities[:max_results]

        logger.info("WebEvents: collected %d events total", len(all_opportunities))
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
                    "WebEvents: discovery failed for seed %s", seed_url,
                    exc_info=True,
                )

            if idx < len(self._pages) - 1:
                await asyncio.sleep(_RATE_LIMIT_DELAY)

        if len(all_discovered) > _MAX_EVENT_PAGES:
            all_discovered = all_discovered[:_MAX_EVENT_PAGES]

        return all_discovered

    async def _discover_from_seed(self, seed_url: str) -> list[str]:
        """Fetch a seed page and use Gemini to identify event links."""
        resp = await self._http_client.get(seed_url)
        resp.raise_for_status()

        links = self._extract_links(resp.text, seed_url)
        if not links:
            logger.debug("WebEvents: no links found on seed %s", seed_url)
            return []

        logger.debug(
            "WebEvents: extracted %d links from %s, sending to Gemini for filtering",
            len(links), seed_url,
        )

        # Send links to Gemini for intelligent filtering
        links_for_prompt = links[:_MAX_LINKS_TO_GEMINI]
        user_prompt = (
            f"Seed page URL: {seed_url}\n\n"
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
                "WebEvents: Gemini link filtering failed for %s", seed_url,
                exc_info=True,
            )
            return []

    @staticmethod
    def _extract_links(html: str, base_url: str) -> list[str]:
        """Extract all unique http(s) links from an HTML page."""
        soup = BeautifulSoup(html, "html.parser")
        base_domain = urlparse(base_url).hostname or ""

        seen: set[str] = set()
        links: list[str] = []

        for tag in soup.find_all("a", href=True):
            href = tag["href"].strip()
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue

            absolute = urljoin(base_url, href)

            # Strip fragments
            absolute = re.sub(r"#.*$", "", absolute)
            if not absolute.startswith("http"):
                continue

            normalised = absolute.rstrip("/").lower()
            if normalised in seen:
                continue
            seen.add(normalised)

            # Skip obvious non-event links
            parsed = urlparse(absolute)
            path_lower = (parsed.path or "").lower()
            if any(skip in path_lower for skip in (
                "/login", "/signup", "/register", "/cart", "/checkout",
                "/privacy", "/terms", "/cookie", "/legal",
                ".pdf", ".zip", ".png", ".jpg", ".svg",
            )):
                continue

            links.append(absolute)

        return links

    # ------------------------------------------------------------------ #
    # Phase 2: Extraction                                                  #
    # ------------------------------------------------------------------ #

    async def _phase_extraction(self, event_urls: list[str]) -> list[Opportunity]:
        """Fetch each event page and extract structured event data."""
        all_opportunities: list[Opportunity] = []

        for idx, url in enumerate(event_urls):
            try:
                opps = await self._extract_from_page(url)
                all_opportunities.extend(opps)
                logger.info(
                    "WebEvents: [%d/%d] %s -> %d event(s)",
                    idx + 1, len(event_urls), url[:80], len(opps),
                )
            except Exception:
                logger.warning(
                    "WebEvents: [%d/%d] extraction failed for %s",
                    idx + 1, len(event_urls), url[:80],
                    exc_info=True,
                )

            if idx < len(event_urls) - 1:
                await asyncio.sleep(_RATE_LIMIT_DELAY)

        return all_opportunities

    async def _extract_from_page(self, url: str) -> list[Opportunity]:
        """Fetch a single event page and use Gemini to extract events."""
        resp = await self._http_client.get(url)
        resp.raise_for_status()

        text = self._extract_text(resp.text)
        if not text or len(text.strip()) < 50:
            logger.debug("WebEvents: page %s yielded too little text", url)
            return []

        events_data = await self._call_gemini_extraction(text, url)
        return self._build_opportunities(events_data, url)

    @staticmethod
    def _extract_text(html: str) -> str:
        """Extract readable text from HTML, stripping scripts/styles."""
        soup = BeautifulSoup(html, "html.parser")

        for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
            tag.decompose()

        text = soup.get_text(separator="\n", strip=True)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        clean = "\n".join(lines)

        if len(clean) > _MAX_TEXT_LENGTH:
            clean = clean[:_MAX_TEXT_LENGTH]

        return clean

    async def _call_gemini_extraction(
        self, page_text: str, source_url: str,
    ) -> list[dict]:
        """Send page text to Gemini and get structured event data back."""
        user_prompt = (
            f"URL della pagina: {source_url}\n\n"
            f"Testo della pagina:\n{page_text}"
        )

        try:
            response = await asyncio.to_thread(
                self._gemini_client.models.generate_content,
                model=self._model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=_EXTRACTION_PROMPT,
                    response_mime_type="application/json",
                    temperature=0.1,
                ),
            )
            text = response.text
            if not text:
                logger.warning("WebEvents: Gemini returned empty for %s", source_url)
                return []

            data = json.loads(text)
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and "events" in data:
                return data["events"]
            logger.warning(
                "WebEvents: unexpected Gemini response structure for %s", source_url,
            )
            return []

        except Exception:
            logger.exception("WebEvents: Gemini extraction failed for %s", source_url)
            return []

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _build_opportunities(
        self, events_data: list[dict], page_url: str,
    ) -> list[Opportunity]:
        """Convert Gemini-extracted event data into Opportunity objects."""
        opportunities: list[Opportunity] = []

        for evt in events_data:
            title = evt.get("title", "").strip()
            if not title:
                continue

            description = evt.get("description", "").strip()
            location = evt.get("location", "") or ""
            event_url = evt.get("url") or page_url

            deadline = self._parse_date(evt.get("event_date"))

            short_hash = hashlib.sha256(
                f"{page_url}:{title}".encode(),
            ).hexdigest()[:12]

            if location:
                description = (
                    f"{description}\n📍 {location}" if description
                    else f"📍 {location}"
                )

            opp = Opportunity(
                id=f"WEB-{short_hash}",
                title=title,
                description=description[:500],
                contracting_authority=self._domain_name(page_url),
                deadline=deadline,
                estimated_value=None,
                currency="EUR",
                country="IT",
                source_url=event_url,
                source=Source.EVENT,
                opportunity_type=OpportunityType.EVENTO,
                publication_date=date.today(),
                cpv_codes=[],
            )
            opportunities.append(opp)

        return opportunities

    @staticmethod
    def _parse_date(value: str | None) -> date | None:
        """Parse an ISO date string into a date object."""
        if not value:
            return None
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y"):
            try:
                return datetime.strptime(str(value).strip()[:19], fmt).date()
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
