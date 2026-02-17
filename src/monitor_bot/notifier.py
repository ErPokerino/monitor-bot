"""Generate an HTML report and optionally send it via email."""

from __future__ import annotations

import logging
import smtplib
from collections import Counter
from datetime import date, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from monitor_bot.config import Settings
from monitor_bot.models import ClassifiedOpportunity

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).resolve().parent.parent.parent / "templates"


class Notifier:
    """Build the HTML report and deliver it (email or local file)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._jinja_env = Environment(
            loader=FileSystemLoader(str(TEMPLATE_DIR)),
            autoescape=True,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def notify(
        self,
        classified: list[ClassifiedOpportunity],
        total_analyzed: int,
        elapsed_seconds: float | None = None,
    ) -> Path | None:
        """Filter, render and deliver the report. Returns the local path if saved."""
        threshold = self._settings.relevance_threshold
        relevant = sorted(
            [c for c in classified if c.score >= threshold],
            key=lambda c: c.score,
            reverse=True,
        )

        html = self._render(relevant, total_analyzed, threshold, elapsed_seconds)

        if self._settings.smtp_configured:
            self._send_email(html, len(relevant))
            return None
        else:
            return self._save_local(html)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render(
        self,
        opportunities: list[ClassifiedOpportunity],
        total_analyzed: int,
        threshold: int,
        elapsed_seconds: float | None = None,
    ) -> str:
        category_counts: dict[str, int] = Counter()
        type_counts: dict[str, int] = Counter()
        for item in opportunities:
            category_counts[item.category.value] += 1
            type_counts[item.opportunity.opportunity_type.value] += 1

        # Format elapsed time as "X min Y sec" or "Y sec"
        elapsed_display = None
        if elapsed_seconds is not None:
            mins = int(elapsed_seconds) // 60
            secs = int(elapsed_seconds) % 60
            if mins > 0:
                elapsed_display = f"{mins} min {secs} sec"
            else:
                elapsed_display = f"{secs} sec"

        template = self._jinja_env.get_template("report.html")
        return template.render(
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
            lookback_days=self._settings.lookback_days,
            total_analyzed=total_analyzed,
            relevant_count=len(opportunities),
            threshold=threshold,
            category_counts=dict(category_counts),
            type_counts=dict(type_counts),
            opportunities=opportunities,
            today=date.today(),
            elapsed_display=elapsed_display,
        )

    # ------------------------------------------------------------------
    # Delivery
    # ------------------------------------------------------------------

    def _send_email(self, html: str, relevant_count: int) -> None:
        s = self._settings
        subject = f"Monitor Bandi: {relevant_count} opportunità rilevanti trovate"

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = s.email_from  # type: ignore[arg-type]
        msg["To"] = s.email_to  # type: ignore[arg-type]
        msg.attach(MIMEText(html, "html"))

        logger.info("Sending email to %s via %s:%s", s.email_to, s.smtp_host, s.smtp_port)
        try:
            with smtplib.SMTP(s.smtp_host, s.smtp_port) as server:  # type: ignore[arg-type]
                server.ehlo()
                server.starttls()
                server.login(s.smtp_user, s.smtp_password)  # type: ignore[arg-type]
                server.sendmail(s.email_from, [s.email_to], msg.as_string())  # type: ignore[arg-type]
            logger.info("Email sent successfully")
        except Exception:
            logger.exception("Failed to send email – saving report locally as fallback")
            self._save_local(html)

    def _save_local(self, html: str) -> Path:
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = output_dir / f"report_{timestamp}.html"
        path.write_text(html, encoding="utf-8")
        logger.info("Report saved to %s", path)
        return path
