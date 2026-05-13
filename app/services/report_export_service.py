"""
Service for exporting reports to various formats.
Note: PDF and DOCX conversion usually requires additional system-level
dependencies (like wkhtmltopdf or pandoc) or specialized python libraries
(xhtml2pdf, python-docx). This service currently supports XHTML only.
"""
from typing import Literal
from app.models.report import Report
from app.core.errors import AppError, ErrorCode

ReportExportFormat = Literal["xhtml", "pdf", "docx"]

async def export_report(report: Report, format: ReportExportFormat) -> bytes:
    if not report.canonical_xhtml:
        # Fallback if XHTML wasn't generated at approval
        from app.services import report_render_service
        report.canonical_xhtml = await report_render_service.render_xhtml(report)
        await report.save()

    if format == "xhtml":
        return report.canonical_xhtml.encode("utf-8")

    if format in {"pdf", "docx"}:
        raise AppError(
            ErrorCode.CONFLICT,
            f"{format.upper()} export is not enabled in this environment. Use XHTML export.",
        )

    raise AppError(ErrorCode.VALIDATION_ERROR, f"Unsupported export format: {format}")
