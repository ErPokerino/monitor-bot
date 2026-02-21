"""Application configuration.

Secrets (API keys, SMTP credentials) are loaded from ``.env``.
All other parameters (search scope, company profile, feeds, etc.)
are loaded from ``config.toml`` (or a custom path via ``--config``).
"""

from __future__ import annotations

import logging
import tomllib
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# Default paths (relative to CWD)
DEFAULT_CONFIG_PATH = Path("config.toml")
TEST_CONFIG_PATH = Path("config.test.toml")
ITALIA_CONFIG_PATH = Path("config.italia.toml")


# ---------------------------------------------------------------------------
# Secrets – loaded from .env only
# ---------------------------------------------------------------------------

class Secrets(BaseSettings):
    """API keys and credentials. Loaded exclusively from .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    gemini_api_key: str = Field(description="Google Gemini API key")
    smtp_host: str | None = Field(default=None)
    smtp_port: int = Field(default=587)
    smtp_user: str | None = Field(default=None)
    smtp_password: str | None = Field(default=None)


# ---------------------------------------------------------------------------
# Parameters – loaded from config.toml
# ---------------------------------------------------------------------------

class Settings:
    """Merged configuration from .env (secrets) and config.toml (parameters)."""

    def __init__(self, config_path: Path = DEFAULT_CONFIG_PATH) -> None:
        # Load secrets from .env
        self._secrets = Secrets()  # type: ignore[call-arg]

        # Load parameters from TOML
        self._cfg = self._load_toml(config_path)

        # --- Secrets ---
        self.gemini_api_key: str = self._secrets.gemini_api_key
        self.smtp_host: str | None = self._secrets.smtp_host
        self.smtp_port: int = self._secrets.smtp_port
        self.smtp_user: str | None = self._secrets.smtp_user
        self.smtp_password: str | None = self._secrets.smtp_password

        # --- Gemini ---
        gemini = self._cfg.get("gemini", {})
        self.gemini_model: str = gemini.get("model", "gemini-3-flash-preview")

        # --- Classification ---
        classification = self._cfg.get("classification", {})
        self.relevance_threshold: int = classification.get("relevance_threshold", 6)

        # --- Search scope ---
        scope = self._cfg.get("scope", {})
        self.lookback_days: int = scope.get("lookback_days", 7)
        self.max_results: int = scope.get("max_results", 0)
        self.cpv_codes: list[str] = scope.get("cpv_codes", ["72", "48", "62", "64.2"])
        self.countries: list[str] = scope.get("countries", ["IT"])

        # --- Collectors ---
        collectors = self._cfg.get("collectors", {})
        self.enable_ted: bool = collectors.get("ted", True)
        self.enable_anac: bool = collectors.get("anac", True)
        self.enable_events: bool = collectors.get("events", True)
        self.enable_web_events: bool = collectors.get("web_events", True)
        self.enable_web_tenders: bool = collectors.get("web_tenders", False)
        self.enable_web_search: bool = collectors.get("web_search", False)

        # --- Events ---
        events = self._cfg.get("events", {})
        self.event_feeds: list[str] = events.get("feeds", [])
        self.event_web_pages: list[str] = events.get("web_pages", [])

        # --- Regional tenders ---
        regional = self._cfg.get("regional_tenders", {})
        self.web_tender_pages: list[str] = regional.get("web_pages", [])

        # --- Web search ---
        web_search = self._cfg.get("web_search", {})
        self.web_search_queries: list[str] = web_search.get("queries", [])
        self.web_search_max_per_query: int = web_search.get("max_results_per_query", 5)

        # --- Company profile ---
        company = self._cfg.get("company", {})
        self.company_profile: str = company.get("profile", "").strip()

        # --- Email addresses (from TOML, credentials from .env) ---
        email = self._cfg.get("email", {})
        self.email_from: str | None = email.get("from") or None
        self.email_to: str | None = email.get("to") or None

    @staticmethod
    def _load_toml(path: Path) -> dict:
        if not path.exists():
            logger.warning("Config file not found: %s – using defaults", path)
            return {}
        logger.info("Loading config from %s", path)
        with open(path, "rb") as f:
            return tomllib.load(f)

    # --- Derived properties ---

    @property
    def smtp_configured(self) -> bool:
        return all([
            self.smtp_host, self.smtp_user, self.smtp_password,
            self.email_from, self.email_to,
        ])

    def apply_db_overrides(self, active_sources: list, active_queries: list) -> None:
        """Replace TOML-driven source lists and collector flags with DB state.

        Only active (toggled-on) sources and queries are passed in.
        This ensures the pipeline respects the web UI toggles.
        """
        self.event_feeds = []
        self.event_web_pages = []
        self.web_tender_pages = []
        self.web_search_queries = []

        self.enable_ted = False
        self.enable_anac = False
        self.enable_events = False
        self.enable_web_events = False
        self.enable_web_tenders = False
        self.enable_web_search = False

        for src in active_sources:
            url_lower = src.url.lower()
            stype = src.source_type.value if hasattr(src.source_type, "value") else src.source_type

            if "ted.europa.eu" in url_lower:
                self.enable_ted = True
            elif "anticorruzione.it" in url_lower:
                self.enable_anac = True
            elif stype == "rss_feed":
                self.event_feeds.append(src.url)
                self.enable_events = True
            elif stype == "web_page":
                self.event_web_pages.append(src.url)
                self.enable_web_events = True
            elif stype == "tender_portal":
                self.web_tender_pages.append(src.url)
                self.enable_web_tenders = True

        max_per_query = 5
        for q in active_queries:
            text = q.query_text if hasattr(q, "query_text") else str(q)
            mr = q.max_results if hasattr(q, "max_results") else 5
            self.web_search_queries.append(text)
            max_per_query = max(max_per_query, mr)

        if self.web_search_queries:
            self.enable_web_search = True
            self.web_search_max_per_query = max_per_query

    def scope_summary(self) -> str:
        """Human-readable summary of the current search scope."""
        collectors = []
        if self.enable_ted:
            collectors.append("TED")
        if self.enable_anac:
            collectors.append("ANAC")
        if self.enable_events:
            collectors.append("Events")
        if self.enable_web_events:
            collectors.append("WebEvents")
        if self.enable_web_tenders:
            collectors.append("WebTenders")
        if self.enable_web_search:
            collectors.append("WebSearch")

        parts = [
            f"collectors={'+'.join(collectors) or 'none'}",
            f"countries={len(self.countries)}",
            f"CPV={','.join(self.cpv_codes)}",
            f"lookback={self.lookback_days}d",
        ]
        if self.max_results:
            parts.append(f"max={self.max_results}/collector")
        return " | ".join(parts)
