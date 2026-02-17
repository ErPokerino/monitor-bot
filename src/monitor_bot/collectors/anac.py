"""Collector for Italian public procurement data from ANAC Open Data (OCDS format).

The ANAC portal publishes monthly bulk JSON files that can be hundreds of MB each.
This collector streams the download and parses OCDS releases incrementally, filtering
by CPV code and date on-the-fly so we never need the full file in memory.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import date, datetime, timedelta

import httpx

from monitor_bot.collectors.base import BaseCollector
from monitor_bot.config import Settings
from monitor_bot.models import Opportunity, Source

logger = logging.getLogger(__name__)

ANAC_BASE = "https://dati.anticorruzione.it/opendata"
ANAC_API = f"{ANAC_BASE}/api/3"
ANAC_PACKAGE_PREFIX = "ocds-appalti-ordinari"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
}

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 4.0

# Limits for bulk file streaming
_MAX_DOWNLOAD_MB = 200          # skip files larger than this (by Content-Length)
_STREAM_TIMEOUT = 120.0         # max seconds for streaming a single file
_MAX_RELEASES_PER_FILE = 500    # stop parsing a file after this many IT-matching releases


class ANACCollector(BaseCollector):
    """Fetch IT-related procurement notices from ANAC Open Data (OCDS)."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, read=_STREAM_TIMEOUT),
            follow_redirects=True,
            headers=_HEADERS,
        )

    async def collect(self) -> list[Opportunity]:
        logger.info("ANAC: starting collection")
        try:
            releases = await self._fetch_releases()
            opportunities = self._normalise(releases)
            logger.info("ANAC: collected %d opportunities", len(opportunities))
            return opportunities
        except Exception:
            logger.exception("ANAC: collection failed")
            return []
        finally:
            await self._client.aclose()

    # ------------------------------------------------------------------
    # Small-JSON helper (for CKAN metadata calls)
    # ------------------------------------------------------------------

    async def _get_json(self, url: str, **kwargs: object) -> dict | None:
        """GET a small JSON endpoint. Retries on WAF blocks / transient errors.

        Does NOT retry on 404 (permanent -- dataset doesn't exist).
        """
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                resp = await self._client.get(url, **kwargs)  # type: ignore[arg-type]

                # Permanent errors -- don't retry
                if resp.status_code == 404:
                    logger.info("ANAC: 404 not found (won't retry): %s", url)
                    return None

                ct = resp.headers.get("content-type", "")
                if "json" not in ct and "Request Rejected" in resp.text[:200]:
                    delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
                    logger.warning(
                        "ANAC: WAF blocked (attempt %d/%d), retrying in %.0fs: %s",
                        attempt, _MAX_RETRIES, delay, url,
                    )
                    await asyncio.sleep(delay)
                    await self._refresh_client()
                    continue

                resp.raise_for_status()
                return resp.json()

            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    logger.info("ANAC: 404 not found (won't retry): %s", url)
                    return None
                delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning(
                    "ANAC: HTTP %d (attempt %d/%d), retrying in %.0fs: %s",
                    exc.response.status_code, attempt, _MAX_RETRIES, delay, url,
                )
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(delay)

            except httpx.RequestError as exc:
                delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning(
                    "ANAC: request error (attempt %d/%d), retrying in %.0fs: %s",
                    attempt, _MAX_RETRIES, delay, exc,
                )
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(delay)

        logger.error("ANAC: all retries exhausted for %s", url)
        return None

    async def _refresh_client(self) -> None:
        """Close and recreate the HTTP client for a fresh TLS session."""
        await self._client.aclose()
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, read=_STREAM_TIMEOUT),
            follow_redirects=True,
            headers=_HEADERS,
        )

    # ------------------------------------------------------------------
    # Resource discovery
    # ------------------------------------------------------------------

    async def _fetch_releases(self) -> list[dict]:
        year = date.today().year
        resource_urls = await self._get_resource_urls(year)
        if not resource_urls:
            logger.info("ANAC: no resources for %d, trying %d", year, year - 1)
            resource_urls = await self._get_resource_urls(year - 1)

        if not resource_urls:
            logger.warning("ANAC: no JSON resources found at all")
            return []

        # Only download the most recent file(s) -- they're sorted chronologically
        # and each is a monthly dump. Take only the last one to keep it fast.
        urls_to_fetch = resource_urls[-1:]
        logger.info(
            "ANAC: found %d JSON resources, downloading most recent %d",
            len(resource_urls), len(urls_to_fetch),
        )

        all_releases: list[dict] = []
        for url in urls_to_fetch:
            releases = await self._stream_and_filter(url)
            all_releases.extend(releases)

        return all_releases

    async def _get_resource_urls(self, year: int) -> list[str]:
        package_id = f"{ANAC_PACKAGE_PREFIX}-{year}"
        url = f"{ANAC_API}/action/package_show"
        data = await self._get_json(url, params={"id": package_id})
        if data is None:
            return []

        resources = data.get("result", {}).get("resources", [])
        json_urls = [
            r["url"]
            for r in resources
            if r.get("format", "").upper() == "JSON" and r.get("url")
        ]
        logger.info("ANAC: found %d JSON resources for %s", len(json_urls), package_id)
        return json_urls

    # ------------------------------------------------------------------
    # Streaming download with incremental JSON parsing
    # ------------------------------------------------------------------

    async def _stream_and_filter(self, url: str) -> list[dict]:
        """Stream a bulk OCDS JSON file and extract matching releases on-the-fly.

        Strategy: download the file in chunks, accumulate into a buffer, and use
        a simple state machine to extract individual release objects from the
        ``"releases": [...]`` array without loading the full file into memory.

        Falls back to full-download if the file is small enough (< 10 MB).
        """
        logger.info("ANAC: streaming %s", url)
        since = date.today() - timedelta(days=self.settings.lookback_days)

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                return await self._do_stream(url, since)
            except (httpx.RequestError, httpx.StreamError) as exc:
                delay = _RETRY_BASE_DELAY * attempt
                logger.warning(
                    "ANAC: stream error (attempt %d/%d), retrying in %.0fs: %s",
                    attempt, _MAX_RETRIES, delay, exc,
                )
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(delay)
                    await self._refresh_client()

        logger.error("ANAC: all stream retries exhausted for %s", url)
        return []

    async def _do_stream(self, url: str, since: date) -> list[dict]:
        """The actual streaming + parsing logic."""
        async with self._client.stream("GET", url) as resp:
            resp.raise_for_status()

            # Check Content-Length if available
            content_length = resp.headers.get("content-length")
            if content_length:
                size_mb = int(content_length) / (1024 * 1024)
                logger.info("ANAC: file size %.0f MB", size_mb)
                if size_mb > _MAX_DOWNLOAD_MB:
                    logger.warning(
                        "ANAC: file too large (%.0f MB > %d MB limit), skipping: %s",
                        size_mb, _MAX_DOWNLOAD_MB, url,
                    )
                    return []

            # Stream and accumulate the full content (up to _MAX_DOWNLOAD_MB)
            chunks: list[bytes] = []
            total_bytes = 0
            max_bytes = _MAX_DOWNLOAD_MB * 1024 * 1024

            async for chunk in resp.aiter_bytes(chunk_size=256 * 1024):
                chunks.append(chunk)
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    logger.warning(
                        "ANAC: download exceeded %d MB limit, stopping",
                        _MAX_DOWNLOAD_MB,
                    )
                    break

        logger.info("ANAC: downloaded %.1f MB, parsing...", total_bytes / (1024 * 1024))
        raw = b"".join(chunks)

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("ANAC: failed to parse JSON (possibly truncated)")
            # Try to salvage: find the releases array and parse what we can
            return self._salvage_releases(raw, since)

        releases = data.get("releases", [])
        if not releases and isinstance(data, list):
            releases = data

        return self._filter_releases(releases, since)

    def _filter_releases(self, releases: list[dict], since: date) -> list[dict]:
        """Apply CPV + date filters and enforce the per-file cap."""
        filtered: list[dict] = []
        for release in releases:
            if len(filtered) >= _MAX_RELEASES_PER_FILE:
                logger.info(
                    "ANAC: reached %d-release cap, stopping early",
                    _MAX_RELEASES_PER_FILE,
                )
                break
            if not self._matches_cpv(release):
                continue
            pub_date = self._get_publication_date(release)
            if pub_date and pub_date < since:
                continue
            filtered.append(release)

        logger.info(
            "ANAC: %d releases matched CPV + date filters (out of %d total)",
            len(filtered), len(releases),
        )
        return filtered

    def _salvage_releases(self, raw: bytes, since: date) -> list[dict]:
        """Best-effort extraction from a truncated JSON download."""
        text = raw.decode("utf-8", errors="replace")
        idx = text.find('"releases"')
        if idx == -1:
            return []
        # Find the opening bracket of the releases array
        bracket = text.find("[", idx)
        if bracket == -1:
            return []
        # Try to find complete release objects by looking for "}," patterns
        # This is a heuristic for truncated files
        array_text = text[bracket:]
        # Close the array if truncated
        if not array_text.rstrip().endswith("]"):
            last_brace = array_text.rfind("}")
            if last_brace > 0:
                array_text = array_text[: last_brace + 1] + "]"

        try:
            releases = json.loads(array_text)
            logger.info("ANAC: salvaged %d releases from truncated download", len(releases))
            return self._filter_releases(releases, since)
        except json.JSONDecodeError:
            logger.warning("ANAC: could not salvage any releases from truncated file")
            return []

    # ------------------------------------------------------------------
    # Filtering helpers
    # ------------------------------------------------------------------

    def _matches_cpv(self, release: dict) -> bool:
        cpv_codes = self._extract_cpv_codes(release)
        for cpv in cpv_codes:
            for prefix in self.settings.cpv_codes:
                if cpv.startswith(prefix):
                    return True
        return False

    # ------------------------------------------------------------------
    # Normalisation
    # ------------------------------------------------------------------

    def _normalise(self, releases: list[dict]) -> list[Opportunity]:
        results: list[Opportunity] = []
        for release in releases:
            try:
                tender = release.get("tender", {})
                buyer = release.get("buyer", {})
                ocid = release.get("ocid", "")

                value_obj = tender.get("value", {})
                period = tender.get("tenderPeriod", {})

                opp = Opportunity(
                    id=f"ANAC-{ocid}",
                    title=tender.get("description", ""),
                    description=self._build_description(tender, tender.get("items", [])),
                    contracting_authority=buyer.get("name", ""),
                    deadline=self._parse_date(period.get("endDate")),
                    estimated_value=self._parse_float(value_obj.get("amount")),
                    currency=value_obj.get("currency", "EUR"),
                    country="IT",
                    source_url="https://dati.anticorruzione.it/opendata/ocds_it",
                    source=Source.ANAC,
                    publication_date=self._parse_date(period.get("startDate")),
                    cpv_codes=self._extract_cpv_codes(release),
                )
                results.append(opp)
            except Exception:
                logger.warning(
                    "ANAC: failed to normalise release %s",
                    release.get("ocid", "?"),
                )
        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_cpv_codes(release: dict) -> list[str]:
        codes: list[str] = []
        for item in release.get("tender", {}).get("items", []):
            cpv_id = item.get("classification", {}).get("id", "")
            if cpv_id:
                codes.append(cpv_id)
        return codes

    @staticmethod
    def _build_description(tender: dict, items: list[dict]) -> str:
        parts: list[str] = []
        desc = tender.get("description", "")
        if desc:
            parts.append(desc)
        for item in items:
            item_desc = item.get("description", "")
            if item_desc and item_desc != desc:
                parts.append(item_desc)
            cpv_desc = item.get("classification", {}).get("description", "")
            if cpv_desc:
                parts.append(f"CPV: {cpv_desc}")
        return " | ".join(parts) if parts else ""

    @staticmethod
    def _get_publication_date(release: dict) -> date | None:
        raw = release.get("tender", {}).get("tenderPeriod", {}).get("startDate")
        if not raw:
            raw = release.get("date")
        return ANACCollector._parse_date(raw)

    @staticmethod
    def _parse_date(value: str | None) -> date | None:
        if not value:
            return None
        raw = str(value).strip()
        raw = re.sub(r"[Z]$|[+-]\d{2}:\d{2}$", "", raw)
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(raw[:19], fmt).date()
            except ValueError:
                continue
        return None

    @staticmethod
    def _parse_float(value: float | str | None) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None
