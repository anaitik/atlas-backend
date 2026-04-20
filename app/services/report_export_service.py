"""
Service for exporting reports to various formats.
Note: PDF and DOCX conversion usually requires additional system-level 
dependencies (like wkhtmltopdf or pandoc) or specialized python libraries 
(xhtml2pdf, python-docx). For this wave, we provide the XHTML snapshot 
and stubs for other formats.
"""
from typing import Literal
from app.models.report import Report

ReportExportFormat = Literal["xhtml", "pdf", "docx"]

async def export_report(report: Report, format: ReportExportFormat) -> bytes:
    if not report.canonical_xhtml:
        # Fallback if XHTML wasn't generated at approval
        from app.services import report_render_service
        report.canonical_xhtml = await report_render_service.render_xhtml(report)
        await report.save()

    if format == "xhtml":
        return report.canonical_xhtml.encode("utf-8")
    
    if format == "pdf":
        # In a real production environment, we would use xhtml2pdf or weasyprint
        # For now, we return a text-based marker with the report content
        return f"PDF_STUB: {report.exec_summary}".encode("utf-8")
        
    if format == "docx":
        # In a real production environment, we would use python-docx
        return f"DOCX_STUB: {report.exec_summary}".encode("utf-8")

    raise ValueError(f"Unsupported export format: {format}")
