"""Email notification service for pipeline completion reports."""

from __future__ import annotations

import logging
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


def _smtp_config():
    host = os.environ.get("SMTP_HOST")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    return host, port, user, password


def _table_row(label, value, highlight, last=False):
    border = "" if last else "border-bottom:1px solid #f3f4f6;"
    if highlight:
        val_style = "font-weight:700;color:#059669;font-size:18px"
    else:
        val_style = "font-weight:600;color:#1e3a5f"
    return (
        '<tr><td style="padding:10px 0;' + border + 'color:#6b7280">' + label + '</td>'
        '<td style="padding:10px 0;' + border + 'text-align:right;' + val_style + '">' + value + '</td></tr>'
    )


def _render_html(run_id, total_collected, total_classified, total_relevant, elapsed_seconds, app_url):
    mins = int(elapsed_seconds) // 60
    secs = int(elapsed_seconds) % 60
    elapsed_str = f"{mins}m {secs}s" if mins else f"{secs}s"
    now = datetime.now().strftime("%d/%m/%Y %H:%M")

    link_block = ""
    if app_url:
        href = app_url + "/dettaglio.html?id=" + str(run_id)
        link_block = (
            '<div style="margin-top:24px;text-align:center">'
            '<a href="' + href + '" style="display:inline-block;padding:10px 24px;'
            'background:#1e3a5f;color:#fff;border-radius:8px;text-decoration:none;'
            'font-weight:600;font-size:14px">Visualizza dettagli</a></div>'
        )

    rows = (
        _table_row("Raccolte", str(total_collected), False)
        + _table_row("Classificate", str(total_classified), False)
        + _table_row("Rilevanti", str(total_relevant), True)
        + _table_row("Durata", elapsed_str, False, last=True)
    )

    return (
        '<!DOCTYPE html><html><head><meta charset="UTF-8"></head>'
        '<body style="margin:0;padding:0;background:#f3f4f6;'
        'font-family:Inter,system-ui,sans-serif">'
        '<div style="max-width:560px;margin:32px auto;background:#fff;'
        'border-radius:12px;overflow:hidden;border:1px solid #e5e7eb">'
        '<div style="background:linear-gradient(135deg,#1e3a5f,#0ea5e9);'
        'padding:28px 32px;color:#fff">'
        '<h1 style="margin:0;font-size:20px;font-weight:600">Opportunity Radar</h1>'
        '<p style="margin:6px 0 0;opacity:.85;font-size:14px">'
        'Report esecuzione automatica</p></div>'
        '<div style="padding:28px 32px">'
        '<p style="color:#6b7280;font-size:13px;margin:0 0 20px">' + now + '</p>'
        '<table style="width:100%;border-collapse:collapse;font-size:14px">'
        + rows +
        '</table>'
        + link_block +
        '</div>'
        '<div style="background:#f9fafb;padding:16px 32px;text-align:center;'
        'font-size:12px;color:#9ca3af">'
        'Opportunity Radar - Notifica automatica</div>'
        '</div></body></html>'
    )


def _esc(text):
    """Minimal HTML escape for table cells (replace &, <, >)."""
    if not text:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _render_report_html(run_id, results):
    """Build a standalone HTML report with the full results table."""
    now = datetime.now().strftime("%d/%m/%Y %H:%M")

    rows_html = ""
    for r in results:
        deadline_str = ""
        if hasattr(r, "deadline") and r.deadline:
            deadline_str = r.deadline.strftime("%d/%m/%Y") if hasattr(r.deadline, "strftime") else str(r.deadline)

        value_str = ""
        if hasattr(r, "estimated_value") and r.estimated_value is not None:
            currency = getattr(r, "currency", "EUR") or "EUR"
            val = r.estimated_value
            value_str = f"{val:,.2f} {currency}" if isinstance(val, (int, float)) else ""

        score = getattr(r, "relevance_score", "")
        score_bg = "#059669" if isinstance(score, (int, float)) and score >= 7 else "#d97706" if isinstance(score, (int, float)) and score >= 5 else "#6b7280"

        source_url = getattr(r, "source_url", "") or ""
        title_val = getattr(r, "title", "") or ""
        title_cell = f'<a href="{source_url}" style="color:#1e3a5f;text-decoration:none">{_esc(title_val)}</a>' if source_url else _esc(title_val)

        rows_html += (
            "<tr>"
            f'<td style="padding:10px 12px;border-bottom:1px solid #e5e7eb">{title_cell}</td>'
            f'<td style="padding:10px 12px;border-bottom:1px solid #e5e7eb">{_esc(getattr(r, "opportunity_type", ""))}</td>'
            f'<td style="padding:10px 12px;border-bottom:1px solid #e5e7eb">{_esc(getattr(r, "category", ""))}</td>'
            f'<td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;text-align:center">'
            f'<span style="display:inline-block;padding:2px 8px;border-radius:6px;color:#fff;'
            f'background:{score_bg};font-weight:700;font-size:13px">{score}</span></td>'
            f'<td style="padding:10px 12px;border-bottom:1px solid #e5e7eb">{deadline_str}</td>'
            f'<td style="padding:10px 12px;border-bottom:1px solid #e5e7eb">{_esc(getattr(r, "contracting_authority", ""))}</td>'
            f'<td style="padding:10px 12px;border-bottom:1px solid #e5e7eb">{value_str}</td>'
            "</tr>"
        )

    return (
        '<!DOCTYPE html><html><head><meta charset="UTF-8">'
        "<title>Opportunity Radar - Report #" + str(run_id) + "</title></head>"
        '<body style="margin:0;padding:24px;background:#f3f4f6;font-family:Inter,system-ui,sans-serif">'
        '<div style="max-width:1100px;margin:0 auto;background:#fff;border-radius:12px;'
        'overflow:hidden;border:1px solid #e5e7eb">'
        '<div style="background:linear-gradient(135deg,#1e3a5f,#0ea5e9);padding:24px 32px;color:#fff">'
        '<h1 style="margin:0;font-size:22px;font-weight:600">Opportunity Radar</h1>'
        '<p style="margin:6px 0 0;opacity:.85;font-size:14px">'
        f"Report esecuzione #{run_id} &mdash; {now}</p></div>"
        '<div style="padding:16px 24px;overflow-x:auto">'
        '<table style="width:100%;border-collapse:collapse;font-size:13px">'
        "<thead><tr style=\"background:#f9fafb\">"
        '<th style="padding:10px 12px;text-align:left;font-weight:600;border-bottom:2px solid #e5e7eb">Titolo</th>'
        '<th style="padding:10px 12px;text-align:left;font-weight:600;border-bottom:2px solid #e5e7eb">Tipo</th>'
        '<th style="padding:10px 12px;text-align:left;font-weight:600;border-bottom:2px solid #e5e7eb">Categoria</th>'
        '<th style="padding:10px 12px;text-align:center;font-weight:600;border-bottom:2px solid #e5e7eb">Score</th>'
        '<th style="padding:10px 12px;text-align:left;font-weight:600;border-bottom:2px solid #e5e7eb">Scadenza</th>'
        '<th style="padding:10px 12px;text-align:left;font-weight:600;border-bottom:2px solid #e5e7eb">Ente</th>'
        '<th style="padding:10px 12px;text-align:left;font-weight:600;border-bottom:2px solid #e5e7eb">Valore</th>'
        "</tr></thead><tbody>"
        + rows_html +
        "</tbody></table></div>"
        '<div style="background:#f9fafb;padding:12px 32px;text-align:center;font-size:11px;color:#9ca3af">'
        "Opportunity Radar &mdash; Report automatico</div>"
        "</div></body></html>"
    )


async def send_run_notification(
    *,
    run_id,
    total_collected,
    total_classified,
    total_relevant,
    elapsed_seconds,
    recipients,
    app_url=None,
    report_html=None,
):
    """Send an email summary of a completed pipeline run, optionally with an HTML report attachment."""
    host, port, user, password = _smtp_config()
    if not host or not user or not password:
        logger.info("SMTP not configured, skipping email notification")
        return

    recipients = [r.strip() for r in recipients if r.strip()]
    if not recipients:
        logger.info("No notification recipients configured, skipping email")
        return

    body_html = _render_html(
        run_id, total_collected, total_classified,
        total_relevant, elapsed_seconds, app_url,
    )

    subject = "Opportunity Radar: " + str(total_relevant) + " opportunita rilevanti trovate"

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = ", ".join(recipients)

    body_part = MIMEMultipart("alternative")
    body_part.attach(MIMEText(body_html, "html"))
    msg.attach(body_part)

    if report_html:
        attachment = MIMEText(report_html, "html")
        attachment.add_header(
            "Content-Disposition", "attachment",
            filename=f"report_run_{run_id}.html",
        )
        msg.attach(attachment)

    try:
        with smtplib.SMTP(host, port) as server:
            server.ehlo()
            server.starttls()
            server.login(user, password)
            server.sendmail(user, recipients, msg.as_string())
        logger.info("Notification email sent to %s", ", ".join(recipients))
    except Exception:
        logger.exception("Failed to send notification email")
