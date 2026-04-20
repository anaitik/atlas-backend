"""
Verification helpers for signed report verification URLs and QR payloads.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
from urllib.parse import quote

from app.config import get_settings
from app.models.report import Report


def _signing_secret() -> str:
    settings = get_settings()
    return settings.VERIFICATION_SIGNING_SECRET or settings.JWT_SECRET_KEY


def build_verification_signature(report: Report) -> str:
    payload = f"{report.id}:{report.sha256_hash}:{report.version}:{report.reporting_year}"
    digest = hmac.new(_signing_secret().encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return digest


def build_report_content_hash(report: Report) -> str:
    payload = {
        "report_id": str(report.id),
        "company_id": report.company_id,
        "workspace_id": report.workspace_id,
        "reporting_year": report.reporting_year,
        "version": report.version,
        "output_format": report.output_format,
        "exec_summary": report.exec_summary,
        "sections": report.sections,
        "data_lineage": report.data_lineage,
        "interview_answers": report.interview_answers,
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_report_signature(report: Report, signature: str | None) -> bool:
    if not signature:
        return False
    expected = build_verification_signature(report)
    return hmac.compare_digest(expected, signature)


def build_verification_url(report: Report, signature: str) -> str:
    settings = get_settings()
    base_url = settings.VERIFICATION_BASE_URL
    if not base_url:
        base_url = f"http://localhost:8000{settings.API_V1_PREFIX}"
    base_url = base_url.rstrip("/")
    return f"{base_url}/reports/public/verify/{report.id}?sig={quote(signature)}"


def build_qr_data_url(content: str) -> str:
    try:
        import qrcode

        qr = qrcode.QRCode(box_size=6, border=2)
        qr.add_data(content)
        qr.make(fit=True)
        image = qr.make_image(fill_color="black", back_color="white")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/png;base64,{encoded}"
    except Exception:
        # Transparent 1x1 PNG fallback to keep verification payload rendering safe.
        return "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8Xw8AAoMBgUCG2l8AAAAASUVORK5CYII="
