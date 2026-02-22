"""Collector for IT-related events from RSS/Atom feeds.

Fetches events from configurable RSS feeds covering Italian public-sector
innovation, EU digital events, and major IT conferences/expos.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import date, datetime

import feedparser
import httpx

from monitor_bot.collectors.base import BaseCollector
from monitor_bot.config import Settings
from monitor_bot.models import Opportunity, OpportunityType, Source

logger = logging.getLogger(__name__)

# Default RSS/Atom feeds relevant to an Italian IT company.
# Users can override via EVENT_FEEDS in .env (comma-separated URLs).
DEFAULT_EVENT_FEEDS: list[dict[str, str]] = [
    {
        "url": "https://www.forumpa.it/feed/",
        "name": "ForumPA",
        "desc": "Italian public-sector innovation events & news",
    },
    {
        "url": "https://www.agid.gov.it/it/rss.xml",
        "name": "AgID",
        "desc": "Agenzia per l'Italia Digitale",
    },
    {
        "url": "https://innovazione.gov.it/feed.xml",
        "name": "Innovazione Italia",
        "desc": "Dipartimento per la Trasformazione Digitale",
    },
    {
        "url": "https://digital-strategy.ec.europa.eu/en/rss.xml",
        "name": "EU Digital Strategy",
        "desc": "European Commission digital strategy events & news",
    },
    {
        "url": "https://community.sap.com/khhcw49343/rss/board?board.id=technology-blog-sap",
        "name": "SAP Community",
        "desc": "SAP technology blog and events",
    },
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
}

# Keywords that hint an RSS entry is about an event vs. a generic news article
_EVENT_KEYWORDS = [
    "evento", "event", "conferenza", "conference", "summit", "forum",
    "workshop", "webinar", "hackathon", "meetup", "expo", "fiera",
    "seminario", "seminar", "convegno", "call", "bando", "award",
    "challenge", "premio", "concorso", "innovation", "innovazione",
    "digitale", "digital", "cloud", "data", "AI", "SAP", "kubernetes",
    "devops", "machine learning", "trasformazione",
]


class EventsCollector(BaseCollector):
    """Fetch IT-relevant events from RSS/Atom feeds."""

    def __init__(self, settings: Settings, **kwargs) -> None:
        super().__init__(settings, **kwargs)
        self._client = httpx.AsyncClient(
            timeout=30.0, follow_redirects=True, headers=_HEADERS,
        )
        self._feeds = self._resolve_feeds(settings)

    async def collect(self) -> list[Opportunity]:
        logger.info("Events: starting collection from %d feeds", len(self._feeds))
        max_results = self.settings.max_results

        async def _fetch_and_report(feed):
            try:
                result = await self._fetch_feed(feed)
                self._report_item(f"Feed: {len(result)} elementi")
                return result
            except Exception as e:
                self._report_item(f"Feed: errore")
                raise e

        tasks = [_fetch_and_report(feed) for feed in self._feeds]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        opportunities: list[Opportunity] = []
        for result in results:
            if isinstance(result, BaseException):
                logger.warning("Events: a feed failed: %s", result)
            else:
                opportunities.extend(result)

        await self._client.aclose()

        if max_results and len(opportunities) > max_results:
            opportunities = opportunities[:max_results]
            logger.info("Events: capped to %d results (max_results)", max_results)

        logger.info("Events: collected %d events total", len(opportunities))
        return opportunities

    # ------------------------------------------------------------------
    # Feed fetching
    # ------------------------------------------------------------------

    async def _fetch_feed(self, feed: dict[str, str]) -> list[Opportunity]:
        """Fetch and parse a single RSS/Atom feed."""
        url = feed["url"]
        name = feed.get("name", url)
        try:
            resp = await self._client.get(url)
            resp.raise_for_status()
            raw_xml = resp.text
        except Exception:
            logger.warning("Events: failed to fetch feed %s (%s)", name, url)
            return []

        # feedparser works on strings synchronously – run in thread to stay async
        parsed = await asyncio.to_thread(feedparser.parse, raw_xml)

        if parsed.bozo and not parsed.entries:
            logger.warning("Events: feed %s returned no parseable entries", name)
            return []

        opportunities: list[Opportunity] = []
        for entry in parsed.entries:
            opp = self._entry_to_opportunity(entry, feed)
            if opp is not None:
                opportunities.append(opp)

        logger.info("Events: %s -> %d events (from %d entries)", name, len(opportunities), len(parsed.entries))
        return opportunities

    # ------------------------------------------------------------------
    # Entry conversion
    # ------------------------------------------------------------------

    def _entry_to_opportunity(
        self, entry: feedparser.FeedParserDict, feed: dict[str, str]
    ) -> Opportunity | None:
        """Convert an RSS entry to an Opportunity if it looks event-relevant."""
        title = entry.get("title", "").strip()
        summary = entry.get("summary", "").strip()
        link = entry.get("link", "")
        published = self._parse_feedparser_date(entry)

        if not title:
            return None

        # Date filter: skip entries older than lookback window
        if published:
            since = date.today().toordinal() - self.settings.lookback_days
            if published.toordinal() < since:
                return None

        # Relevance heuristic: check if the entry is about an event / IT topic
        text_blob = f"{title} {summary}".lower()
        if not any(kw in text_blob for kw in _EVENT_KEYWORDS):
            return None

        # Build a stable ID from the link or title
        id_source = link or title
        short_hash = hashlib.sha256(id_source.encode()).hexdigest()[:12]
        feed_name = feed.get("name", "RSS")

        return Opportunity(
            id=f"EVT-{feed_name}-{short_hash}",
            title=title,
            description=summary[:500] if summary else "",
            contracting_authority=feed.get("name", ""),
            deadline=None,
            estimated_value=None,
            currency="EUR",
            country="IT",
            source_url=link,
            source=Source.EVENT,
            opportunity_type=OpportunityType.EVENTO,
            publication_date=published,
            cpv_codes=[],
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_feeds(settings: Settings) -> list[dict[str, str]]:
        """Use configured feeds if provided, otherwise defaults."""
        if settings.event_feeds:
            return [{"url": u.strip(), "name": u.strip()} for u in settings.event_feeds]
        return DEFAULT_EVENT_FEEDS

    @staticmethod
    def _parse_feedparser_date(entry: feedparser.FeedParserDict) -> date | None:
        """Extract publication date from a feedparser entry."""
        for field in ("published_parsed", "updated_parsed"):
            ts = entry.get(field)
            if ts:
                try:
                    return date(ts.tm_year, ts.tm_mon, ts.tm_mday)
                except (AttributeError, ValueError):
                    continue
        # Try raw string fallback
        for field in ("published", "updated"):
            raw = entry.get(field, "")
            if raw:
                for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
                    try:
                        return datetime.strptime(raw[:25].strip(), fmt).date()
                    except ValueError:
                        continue
        return None
