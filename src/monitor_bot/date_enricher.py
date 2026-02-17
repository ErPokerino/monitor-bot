"""Enrich opportunities with missing dates by fetching their source pages.

When the API or RSS feed doesn't provide a deadline/event date, this module
fetches the actual web page at ``source_url``, extracts readable text, and
asks Gemini Flash to find the relevant date.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import date, datetime

import httpx
from bs4 import BeautifulSoup
from google import genai
from google.genai import types

from monitor_bot.config import Settings
from monitor_bot.models import ClassifiedOpportunity

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from monitor_bot.progress import ProgressTracker

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_MAX_TEXT_LENGTH = 12_000
_RATE_LIMIT_DELAY = 1.0

_DATE_EXTRACTION_PROMPT = """\
Sei un assistente specializzato nell'estrazione di date da pagine web.

Ti viene fornito il testo di una pagina web relativa a un bando di gara, un concorso \
pubblico o un evento IT. Il tuo compito è trovare la DATA PIÙ RILEVANTE tra:

- Per bandi/gare/concorsi: la SCADENZA per la presentazione delle offerte/domande \
  (cerca frasi come "deadline", "scadenza", "termine di presentazione", \
  "deadline for receipt of tenders", "termine ultimo", etc.)
- Per eventi/conferenze: la DATA DELL'EVENTO (cerca frasi come "data evento", \
  "si terrà il", "when", la data indicata nell'intestazione, etc.)

Restituisci SOLO un oggetto JSON con questo formato:
{
  "date": "YYYY-MM-DD",
  "confidence": "high" | "medium" | "low",
  "source_text": "il frammento di testo da cui hai estratto la data"
}

Se la data è un intervallo (es. "19-20 maggio 2026"), usa la data di INIZIO.
Se NON trovi alcuna data rilevante, restituisci:
{"date": null, "confidence": "none", "source_text": null}
"""


async def enrich_missing_dates(
    classified: list[ClassifiedOpportunity],
    settings: Settings,
    progress: ProgressTracker | None = None,
) -> int:
    """Fetch source pages for items missing dates and extract via Gemini.

    Returns the number of opportunities that were patched.
    """
    missing = [
        item for item in classified
        if item.opportunity.deadline is None and item.opportunity.source_url
    ]

    if not missing:
        logger.info("DateEnricher: all opportunities already have dates, skipping")
        return 0

    logger.info(
        "DateEnricher: %d/%d opportunities missing dates, fetching source pages",
        len(missing), len(classified),
    )

    gemini_client = genai.Client(api_key=settings.gemini_api_key)
    model = settings.gemini_model

    async with httpx.AsyncClient(
        timeout=30.0, follow_redirects=True, headers=_HEADERS,
    ) as http_client:
        patched = 0
        for idx, item in enumerate(missing):
            url = item.opportunity.source_url
            try:
                extracted = await _extract_date_from_page(
                    http_client, gemini_client, model, url,
                )
                if extracted:
                    item.opportunity.deadline = extracted
                    patched += 1
                    logger.info(
                        "DateEnricher: [%d/%d] %s -> %s",
                        idx + 1, len(missing), url[:80], extracted.isoformat(),
                    )
                else:
                    logger.debug(
                        "DateEnricher: [%d/%d] %s -> no date found",
                        idx + 1, len(missing), url[:80],
                    )
            except Exception:
                logger.warning(
                    "DateEnricher: [%d/%d] failed for %s",
                    idx + 1, len(missing), url[:80],
                    exc_info=True,
                )

            if progress:
                progress.update(idx + 1, len(missing), item.opportunity.title[:40])

            if idx < len(missing) - 1:
                await asyncio.sleep(_RATE_LIMIT_DELAY)

    logger.info("DateEnricher: patched %d/%d opportunities", patched, len(missing))
    return patched


async def _extract_date_from_page(
    http_client: httpx.AsyncClient,
    gemini_client: genai.Client,
    model: str,
    url: str,
) -> date | None:
    """Fetch a single page and ask Gemini to extract the relevant date.

    For TED notices, use the XML endpoint directly (the HTML page is a
    JavaScript SPA that yields no content via plain HTTP).
    """
    # TED-specific: fetch the notice XML which always has the deadline
    if "ted.europa.eu" in url:
        ted_date = await _extract_date_from_ted_xml(http_client, url)
        if ted_date:
            return ted_date
        logger.debug("DateEnricher: TED XML fallback failed for %s, trying HTML", url)

    resp = await http_client.get(url)
    resp.raise_for_status()

    page_text = _html_to_text(resp.text)
    if not page_text or len(page_text.strip()) < 30:
        return None

    user_prompt = f"URL: {url}\n\nTesto della pagina:\n{page_text}"

    response = await asyncio.to_thread(
        gemini_client.models.generate_content,
        model=model,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=_DATE_EXTRACTION_PROMPT,
            response_mime_type="application/json",
            temperature=0.0,
        ),
    )

    text = response.text
    if not text:
        return None

    data = json.loads(text)
    raw_date = data.get("date")
    confidence = data.get("confidence", "none")

    if not raw_date or confidence == "none":
        return None

    return _parse_date(raw_date)


# TED publication number pattern: digits-digits (e.g. "94915-2026", "104696-2026")
_TED_PUB_RE = re.compile(r"(\d{4,}-\d{4})")


async def _extract_date_from_ted_xml(
    http_client: httpx.AsyncClient,
    url: str,
) -> date | None:
    """Extract the deadline from a TED notice via its XML endpoint.

    TED HTML pages are JavaScript SPAs that return no useful content.
    The XML endpoint at ``/en/notice/{pub_number}/xml`` always contains
    the structured eForms data including deadline dates.
    """
    pub_match = _TED_PUB_RE.search(url)
    if not pub_match:
        return None

    pub_number = pub_match.group(1)
    xml_url = f"https://ted.europa.eu/en/notice/{pub_number}/xml"

    try:
        resp = await http_client.get(xml_url)
        resp.raise_for_status()
        xml_text = resp.text

        # Look for deadline fields in the eForms XML.
        # ParticipationRequestReceptionPeriod > EndDate (for restricted procedures)
        # TenderSubmissionDeadlinePeriod > EndDate (for open procedures)
        # Generic cbc:EndDate patterns
        for pattern in (
            r"<cac:TenderSubmissionDeadlinePeriod>\s*<cbc:EndDate>([^<]+)</cbc:EndDate>",
            r"<cac:ParticipationRequestReceptionPeriod>\s*<cbc:EndDate>([^<]+)</cbc:EndDate>",
            r"SubmissionDeadlinePeriod>\s*<cbc:EndDate>([^<]+)</cbc:EndDate>",
            r"ReceptionPeriod>\s*<cbc:EndDate>([^<]+)</cbc:EndDate>",
        ):
            m = re.search(pattern, xml_text, re.DOTALL)
            if m:
                raw = m.group(1).strip()
                raw = re.sub(r"[Z]$|[+-]\d{2}:\d{2}$", "", raw)
                parsed = _parse_date(raw)
                if parsed:
                    logger.info(
                        "DateEnricher: TED XML %s -> %s (from %s)",
                        pub_number, parsed.isoformat(), m.group(0)[:80],
                    )
                    return parsed

    except Exception:
        logger.debug("DateEnricher: TED XML fetch failed for %s", xml_url, exc_info=True)

    return None


def _html_to_text(html: str) -> str:
    """Extract readable text from HTML, stripping navigation/boilerplate."""
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "noscript", "iframe"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    clean = "\n".join(lines)

    if len(clean) > _MAX_TEXT_LENGTH:
        clean = clean[:_MAX_TEXT_LENGTH]

    return clean


def _parse_date(value: str) -> date | None:
    """Parse a date string in various formats."""
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(str(value).strip()[:19], fmt).date()
        except ValueError:
            continue
    return None
