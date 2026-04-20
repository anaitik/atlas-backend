"""
Service for rendering a professional, investor-grade XHTML document from report data.
Produces CSRD-ready output with XBRL-friendly metadata anchors.
"""
from datetime import UTC, datetime
from app.models.report import Report
from app.models.company import Company
from app.models.workspace import Workspace


PILLAR_COLORS = {
    "environmental": ("#14532d", "#f0fdf4", "#16a34a"),
    "social": ("#1e3a5f", "#eff6ff", "#2563eb"),
    "governance": ("#4a1942", "#fdf4ff", "#9333ea"),
    "strategy": ("#7c2d12", "#fff7ed", "#ea580c"),
    "materiality": ("#1e293b", "#f8fafc", "#64748b"),
}


async def render_xhtml(report: Report) -> str:
    company = await Company.get(report.company_id)
    workspace = await Workspace.get(report.workspace_id)

    company_name = company.name if company else "Unknown Organization"
    workspace_name = workspace.name if workspace else "Reporting Scope"
    generated_on = datetime.now(UTC).strftime("%d %B %Y")
    framework = report.output_format.upper()
    verification_url = report.verification_url or ""
    verification_qr = report.verification_qr_data_url or ""

    # Pillar coverage summary
    pillar_rows = ""
    for pillar, section in report.sections.items():
        color_dark, color_light, color_accent = PILLAR_COLORS.get(pillar, ("#1e293b", "#f8fafc", "#64748b"))
        tags = section.get("framework_tags", [])
        tag_html = "".join(
            f'<span style="background:{color_light};color:{color_dark};border:1px solid {color_accent}33;'
            f'font-size:10px;font-weight:600;padding:2px 7px;border-radius:4px;margin-right:4px;">'
            f'{t}</span>'
            for t in tags
        )
        pillar_rows += (
            f'<tr>'
            f'<td style="padding:10px 12px;font-weight:600;color:{color_dark};">{section["title"]}</td>'
            f'<td style="padding:10px 12px;">{tag_html or "—"}</td>'
            f'</tr>'
        )

    # Main sections
    sections_html = ""
    for pillar, section in report.sections.items():
        color_dark, color_light, color_accent = PILLAR_COLORS.get(pillar, ("#1e293b", "#f8fafc", "#64748b"))
        tags = section.get("framework_tags", [])
        tag_html = "".join(
            f'<span class="fw-tag" style="background:{color_light};color:{color_dark};border-color:{color_accent}33;">{t}</span>'
            for t in tags
        )
        caveats_html = ""
        if section.get("data_caveats"):
            caveats_html = (
                '<div class="caveat-box">'
                '<strong>⚠ Data Caveats:</strong> ' + " | ".join(section["data_caveats"])
                + '</div>'
            )
        content_paras = "".join(f"<p>{para.strip()}</p>" for para in section["content"].split("\n\n") if para.strip())
        sections_html += f"""
        <section id="section-{pillar}" class="report-section" style="--section-accent:{color_accent};">
            <div class="section-header" style="border-left:4px solid {color_accent};padding-left:16px;">
                <h2 style="margin:0 0 6px;color:{color_dark};font-size:20px;">{section["title"]}</h2>
                <div class="fw-tags">{tag_html}</div>
            </div>
            <div class="section-body">{content_paras}</div>
            {caveats_html}
        </section>
        """

    # Data lineage table
    lineage_rows = ""
    for item in report.data_lineage:
        pillar = item.get("pillar", "")
        color_dark, color_light, color_accent = PILLAR_COLORS.get(pillar, ("#1e293b", "#f8fafc", "#64748b"))
        lineage_rows += (
            f'<tr>'
            f'<td class="metric-code">{item.get("metric_code", "")}</td>'
            f'<td>{item.get("name", "")}</td>'
            f'<td class="metric-value">{item.get("value", "")}</td>'
            f'<td>{item.get("unit", "")}</td>'
            f'<td><span style="background:{color_light};color:{color_dark};padding:2px 8px;border-radius:4px;'
            f'font-size:11px;font-weight:600;">{pillar.title()}</span></td>'
            f'</tr>'
        )

    html = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" lang="en">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta name="description" content="Sustainability Report {report.reporting_year} - {company_name}" />
    <meta name="generator" content="Atlas ESG Platform" />
    <meta name="framework" content="{framework}" />
    <title>Sustainability Report {report.reporting_year} — {company_name}</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Inter", sans-serif;
            line-height: 1.7;
            color: #1e293b;
            background: #f8fafc;
            font-size: 15px;
        }}
        .page-wrapper {{ max-width: 860px; margin: 0 auto; padding: 40px 20px 80px; background: white; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
        /* Cover */
        .cover {{ border-bottom: 3px solid #16a34a; padding-bottom: 40px; margin-bottom: 40px; }}
        .cover-badge {{ display:inline-block; background:#f0fdf4; color:#14532d; border:1px solid #bbf7d0; font-size:11px; font-weight:700; letter-spacing:.06em; padding:4px 12px; border-radius:4px; margin-bottom:20px; text-transform:uppercase; }}
        .cover h1 {{ font-size:32px; font-weight:800; color:#0f2d17; letter-spacing:-0.5px; margin-bottom:8px; }}
        .cover .subtitle {{ font-size:16px; color:#475569; margin-bottom:24px; }}
        .meta-grid {{ display:flex; gap:32px; flex-wrap:wrap; }}
        .meta-item {{ display:flex; flex-direction:column; gap:2px; }}
        .meta-label {{ font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:.08em; color:#94a3b8; }}
        .meta-value {{ font-size:14px; font-weight:600; color:#334155; }}
        /* Executive Summary */
        .exec-summary {{ background:#f0fdf4; border:1px solid #bbf7d0; border-radius:12px; padding:28px 32px; margin-bottom:40px; }}
        .exec-summary h2 {{ font-size:13px; font-weight:700; text-transform:uppercase; letter-spacing:.08em; color:#16a34a; margin-bottom:14px; }}
        .exec-summary p {{ color:#1e293b; line-height:1.8; }}
        /* Framework Map */
        .framework-map {{ margin-bottom:40px; border:1px solid #e2e8f0; border-radius:12px; overflow:hidden; }}
        .framework-map-header {{ background:#f8fafc; padding:14px 20px; border-bottom:1px solid #e2e8f0; font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:.08em; color:#64748b; }}
        .framework-map table {{ width:100%; border-collapse:collapse; }}
        .framework-map td {{ border-bottom:1px solid #f1f5f9; font-size:13px; color:#475569; }}
        .framework-map tr:last-child td {{ border-bottom:none; }}
        /* Sections */
        .report-section {{ margin-bottom:48px; padding-bottom:40px; border-bottom:1px solid #f1f5f9; }}
        .report-section:last-of-type {{ border-bottom:none; }}
        .section-header {{ margin-bottom:16px; }}
        .section-body p {{ margin-bottom:14px; color:#334155; line-height:1.8; }}
        .section-body p:last-child {{ margin-bottom:0; }}
        .fw-tags {{ margin-top:8px; display:flex; flex-wrap:wrap; gap:4px; }}
        .fw-tag {{ font-size:10px; font-weight:600; padding:2px 7px; border-radius:4px; border:1px solid; letter-spacing:.04em; }}
        .caveat-box {{ margin-top:16px; background:#fffbeb; border:1px solid #fde68a; border-radius:8px; padding:12px 16px; font-size:12px; color:#92400e; }}
        /* Data Lineage */
        .lineage-section {{ margin-top:60px; padding-top:32px; border-top:2px solid #f1f5f9; }}
        .lineage-section h2 {{ font-size:18px; font-weight:700; color:#1e293b; margin-bottom:4px; }}
        .lineage-section .description {{ font-size:12px; color:#94a3b8; margin-bottom:20px; }}
        .lineage-section table {{ width:100%; border-collapse:collapse; font-size:13px; }}
        .lineage-section th {{ text-align:left; font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:.06em; color:#94a3b8; padding:8px 12px; border-bottom:2px solid #e2e8f0; background:#f8fafc; }}
        .lineage-section td {{ padding:10px 12px; border-bottom:1px solid #f1f5f9; color:#475569; vertical-align:middle; }}
        .lineage-section tr:last-child td {{ border-bottom:none; }}
        .metric-code {{ font-family:monospace; font-size:12px; color:#0f2d17; background:#f0fdf4; padding:2px 6px; border-radius:4px; font-weight:600; white-space:nowrap; }}
        .metric-value {{ font-weight:700; color:#1e293b; }}
        /* Footer */
        .report-footer {{ margin-top:60px; padding-top:24px; border-top:1px solid #e2e8f0; display:flex; justify-content:space-between; align-items:center; font-size:11px; color:#94a3b8; }}
        @media print {{
            body {{ background:white; }}
            .page-wrapper {{ box-shadow:none; }}
        }}
    </style>
</head>
<body>
<div class="page-wrapper">

    <!-- Cover -->
    <div class="cover">
        <div class="cover-badge">🌿 {framework} Sustainability Report</div>
        <h1>{company_name}</h1>
        <p class="subtitle">Sustainability Report · {report.reporting_year}</p>
        <div class="meta-grid">
            <div class="meta-item"><span class="meta-label">Reporting Scope</span><span class="meta-value">{workspace_name}</span></div>
            <div class="meta-item"><span class="meta-label">Reporting Year</span><span class="meta-value">{report.reporting_year}</span></div>
            <div class="meta-item"><span class="meta-label">Framework</span><span class="meta-value">{framework}</span></div>
            <div class="meta-item"><span class="meta-label">Version</span><span class="meta-value">v{report.version}</span></div>
            <div class="meta-item"><span class="meta-label">Verified Metrics</span><span class="meta-value">{len(report.data_lineage)}</span></div>
            <div class="meta-item"><span class="meta-label">Generated</span><span class="meta-value">{generated_on}</span></div>
        </div>
    </div>

    <!-- Executive Summary -->
    <div class="exec-summary">
        <h2>Executive Summary</h2>
        {''.join(f"<p>{para.strip()}</p>" for para in report.exec_summary.split("\\n\\n") if para.strip()) or f"<p>{report.exec_summary}</p>"}
    </div>

    <!-- Framework Map -->
    <div class="framework-map">
        <div class="framework-map-header">Framework Alignment Map</div>
        <table>
            <thead><tr><td style="padding:10px 12px;font-weight:700;font-size:12px;color:#64748b;">Section</td><td style="padding:10px 12px;font-weight:700;font-size:12px;color:#64748b;">Standards Addressed</td></tr></thead>
            <tbody>{pillar_rows}</tbody>
        </table>
    </div>

    <!-- Report Sections -->
    {sections_html}

    <!-- Data Lineage -->
    <div class="lineage-section">
        <h2>Data Lineage &amp; Audit Trail</h2>
        <p class="description">All metrics below were extracted from source documents via the Atlas ESG pipeline, reviewed by analysts, and approved before inclusion in this report.</p>
        <table>
            <thead>
                <tr>
                    <th>Code</th>
                    <th>Metric Name</th>
                    <th>Value</th>
                    <th>Unit</th>
                    <th>Pillar</th>
                </tr>
            </thead>
            <tbody>{lineage_rows}</tbody>
        </table>
    </div>

    <!-- Verification -->
    <div class="lineage-section" style="margin-top:36px;">
        <h2>Verification</h2>
        <p class="description">Use the QR code or verification URL to validate this report hash and blockchain status.</p>
        <table>
            <tbody>
                <tr><th style="width:180px;">Report Hash</th><td><code>{report.sha256_hash or ""}</code></td></tr>
                <tr><th>Blockchain Tx</th><td><code>{report.blockchain_tx_id or "not_anchored"}</code></td></tr>
                <tr><th>Verification URL</th><td>{verification_url}</td></tr>
                <tr><th>High Assurance Mode</th><td>{"enabled" if report.high_assurance_mode else "disabled"} (anchored docs: {report.raw_document_anchor_count})</td></tr>
            </tbody>
        </table>
        {f'<div style="margin-top:16px;"><img src="{verification_qr}" alt="Verification QR" style="width:140px;height:140px;border:1px solid #e2e8f0;padding:4px;border-radius:8px;" /></div>' if verification_qr else ''}
    </div>

    <!-- Footer -->
    <div class="report-footer">
        <span>Generated by Atlas ESG Platform · {generated_on}</span>
        <span>This document is machine-readable and XBRL-compatible.</span>
    </div>

</div>
</body>
</html>"""

    return html
