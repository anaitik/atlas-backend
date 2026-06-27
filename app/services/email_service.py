"""
Email notification service using stdlib smtplib (no extra dependencies).
Configure via SMTP_HOST/PORT/USER/PASSWORD env vars.
All functions are fire-and-forget: failures are logged, never raised.
"""

from __future__ import annotations

import asyncio
import smtplib
import structlog
from concurrent.futures import ThreadPoolExecutor
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

logger = structlog.get_logger()
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="email")


def _build_html(title: str, body: str, cta_label: str, cta_url: Optional[str]) -> str:
    cta_block = ""
    if cta_url:
        cta_block = f"""
        <a href="{cta_url}" style="display:inline-block;background:#1d4ed8;color:white;
           padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:600;
           font-size:14px;margin-top:16px">{cta_label} →</a>
        """
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f8fafc;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f8fafc;padding:40px 16px">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0" style="background:white;border-radius:16px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.08)">
        <tr><td style="background:#0f172a;padding:24px 32px">
          <span style="color:white;font-size:18px;font-weight:800;letter-spacing:-.5px">Atlas ESG</span>
          <span style="color:#64748b;font-size:11px;margin-left:8px">Sustainability Reporting</span>
        </td></tr>
        <tr><td style="padding:32px">
          <p style="font-size:20px;font-weight:700;color:#111827;margin:0 0 10px">{title}</p>
          <p style="font-size:14px;color:#6b7280;margin:0;line-height:1.6">{body}</p>
          {cta_block}
        </td></tr>
        <tr><td style="padding:20px 32px;border-top:1px solid #f1f5f9">
          <p style="font-size:11px;color:#94a3b8;margin:0">
            You're receiving this from Atlas ESG because you have notifications enabled.
            This is an automated message — please do not reply.
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _send_sync(
    to_email: str,
    subject: str,
    html: str,
    text: str,
    host: str,
    port: int,
    user: Optional[str],
    password: Optional[str],
    from_addr: str,
    use_tls: bool,
) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_email
    if text:
        msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP(host, port, timeout=15) as smtp:
        smtp.ehlo()
        if use_tls:
            smtp.starttls()
            smtp.ehlo()
        if user and password:
            smtp.login(user, password)
        smtp.sendmail(from_addr, to_email, msg.as_string())


async def send_email(
    to: str,
    subject: str,
    title: str,
    body: str,
    cta_label: str = "Open Atlas",
    cta_url: Optional[str] = None,
    app_base_url: str = "https://atlas-esg.com",
) -> bool:
    from app.config import get_settings
    s = get_settings()
    if not s.SMTP_HOST:
        return False

    full_cta_url = f"{app_base_url}{cta_url}" if cta_url and not cta_url.startswith("http") else cta_url
    html = _build_html(title, body, cta_label, full_cta_url)

    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(
            _executor,
            _send_sync,
            to, subject, html, body,
            s.SMTP_HOST, s.SMTP_PORT,
            s.SMTP_USER, s.SMTP_PASSWORD,
            f"{s.SMTP_FROM_NAME} <{s.SMTP_FROM_EMAIL}>",
            s.SMTP_USE_TLS,
        )
        logger.info("email_sent", to=to, subject=subject)
        return True
    except Exception as exc:
        logger.warning("email_send_failed", to=to, error=str(exc))
        return False
