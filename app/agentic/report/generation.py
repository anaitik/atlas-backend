"""
Report generation service — Atlas ESG Platform.

Generates investor-grade sustainability reports aligned with CSRD/ESRS,
GRI Standards, and TCFD recommendations from verified workspace metrics
and structured management commentary.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.errors import AppError, ErrorCode
from app.llm_factory import create_llm
from app.models.metric import Metric
from app.models.report import Report
from app.services import audit_service
from app.config import get_settings


# ─── Framework Alignment Maps ────────────────────────────────────────────────

ESRS_TAGS: dict[str, list[str]] = {
    "environmental": ["ESRS E1", "ESRS E2", "ESRS E3", "ESRS E4", "ESRS E5", "GRI 302", "GRI 305", "TCFD Metrics"],
    "social": ["ESRS S1", "ESRS S2", "ESRS S3", "ESRS S4", "GRI 401", "GRI 403", "GRI 405", "GRI 413"],
    "governance": ["ESRS G1", "GRI 205", "GRI 206", "TCFD Governance", "TCFD Risk Management"],
    "strategy": ["ESRS 2 SBM", "TCFD Strategy", "GRI 3-1", "GRI 3-2"],
    "materiality": ["ESRS 2 IRO", "GRI 3-1", "Double Materiality"],
}

SECTION_TITLES: dict[str, str] = {
    "environmental": "Environmental Performance",
    "social": "Social & People Performance",
    "governance": "Governance & Ethics",
    "strategy": "Strategy & Business Model",
    "materiality": "Materiality & Risk",
}

FRAMEWORK_INSTRUCTIONS: dict[str, str] = {
    "csrd": (
        "Structure the narrative to satisfy CSRD/ESRS disclosure requirements. "
        "Reference specific ESRS topics (e.g. ESRS E1-6 for GHG emissions, ESRS S1-14 for own workforce) "
        "where data supports it. Use the ESRS double materiality lens: describe both the company's impacts "
        "on people and planet (impact materiality) and how ESG risks affect the company's financial performance "
        "(financial materiality). Include transition plan elements for climate disclosures. "
        "Mention XBRL-ready datapoints for key metrics."
    ),
    "gri": (
        "Structure the narrative according to GRI Standards (2021). "
        "Map each data point to its GRI disclosure number (e.g. GRI 305-1 for Scope 1 emissions, "
        "GRI 302-1 for energy, GRI 401-1 for new hires). "
        "Follow GRI's topic management approach: explain why each topic is material, "
        "how impacts are managed, and report evaluation of management approach effectiveness."
    ),
    "tcfd": (
        "Structure disclosures around TCFD's four pillars: Governance, Strategy, Risk Management, "
        "and Metrics & Targets. Address physical and transition climate risks. "
        "Include scenario analysis references (e.g. 1.5°C and 4°C pathways). "
        "Align climate metrics with IFRS S2 where applicable."
    ),
    "integrated": (
        "Produce an integrated disclosure narrative combining CSRD/ESRS, GRI, and TCFD. "
        "Cross-reference standards inline (e.g. [ESRS E1 | GRI 305-1 | TCFD Metrics]). "
        "Use value-creation logic: describe how ESG performance links to financial outcomes, "
        "strategy execution, and stakeholder value. "
        "Include year-over-year trend commentary for all quantitative metrics."
    ),
}


# ─── Interview Questions ──────────────────────────────────────────────────────

INTERVIEW_QUESTIONS: list[dict[str, str]] = [
    # ── Environmental ────────────────────────────────────────────────
    {
        "id": "e_emissions_strategy",
        "pillar": "environmental",
        "category": "Climate & Emissions",
        "text": "What is the company's GHG reduction strategy and net-zero target? Include Scope 1, 2, and material Scope 3 categories.",
        "hint": "ESRS E1-1 | GRI 305-1/2/3 | TCFD Strategy",
    },
    {
        "id": "e_energy_mix",
        "pillar": "environmental",
        "category": "Energy",
        "text": "Describe the current energy mix (renewable vs. fossil) and any certification schemes (e.g. EACs, PPAs, RECs) in place.",
        "hint": "ESRS E1-5 | GRI 302-1",
    },
    {
        "id": "e_climate_risks",
        "pillar": "environmental",
        "category": "Climate Risk",
        "text": "What physical and transition climate risks has the company identified, and how are they managed? Reference scenario analysis if conducted.",
        "hint": "ESRS E1-9 | TCFD Risk Management | IFRS S2",
    },
    {
        "id": "e_initiatives",
        "pillar": "environmental",
        "category": "Initiatives",
        "text": "What were the main environmental initiatives, capital expenditure, and operational improvements undertaken this reporting year?",
        "hint": "ESRS E1-3 | GRI 3-3",
    },
    {
        "id": "e_water_biodiversity",
        "pillar": "environmental",
        "category": "Water & Nature",
        "text": "Describe water consumption practices, wastewater management, and any biodiversity or land-use impacts relevant to operations.",
        "hint": "ESRS E3 | ESRS E4 | GRI 303 | GRI 304",
    },
    {
        "id": "e_circular_economy",
        "pillar": "environmental",
        "category": "Waste & Circularity",
        "text": "How does the company manage waste and transition toward a circular economy? Describe material recovery rates and reduction programmes.",
        "hint": "ESRS E5 | GRI 306",
    },
    # ── Social ───────────────────────────────────────────────────────
    {
        "id": "s_workforce_dei",
        "pillar": "social",
        "category": "Workforce & DEI",
        "text": "Describe diversity, equity, and inclusion data and programmes. Include gender pay gap status, leadership diversity, and hiring targets.",
        "hint": "ESRS S1-6/7 | GRI 405-1/2",
    },
    {
        "id": "s_health_safety",
        "pillar": "social",
        "category": "Health & Safety",
        "text": "Report on occupational health and safety performance: TRIR, LTIFR, fatalities (if any), and key safety improvement measures implemented.",
        "hint": "ESRS S1-14 | GRI 403-9/10",
    },
    {
        "id": "s_training_development",
        "pillar": "social",
        "category": "Learning & Development",
        "text": "Describe training hours, upskilling programmes, and workforce capability investment. Any links to green skills or digital transformation?",
        "hint": "ESRS S1-13 | GRI 404-1",
    },
    {
        "id": "s_supply_chain",
        "pillar": "social",
        "category": "Value Chain",
        "text": "How is human rights due diligence conducted across the supply chain? Are suppliers screened for labour standards and ESG criteria?",
        "hint": "ESRS S2 | GRI 408 | GRI 414-1",
    },
    {
        "id": "s_community",
        "pillar": "social",
        "category": "Community Impact",
        "text": "Describe community investment, local economic impact, and stakeholder engagement with affected communities.",
        "hint": "ESRS S3 | GRI 413-1",
    },
    # ── Governance ───────────────────────────────────────────────────
    {
        "id": "g_board_oversight",
        "pillar": "governance",
        "category": "Board & Oversight",
        "text": "Describe board-level oversight of sustainability: committee structure, ESG expertise on the board, and links to executive compensation.",
        "hint": "ESRS 2 GOV-1/2 | TCFD Governance | GRI 2-9",
    },
    {
        "id": "g_ethics_conduct",
        "pillar": "governance",
        "category": "Business Conduct",
        "text": "Were any anti-corruption, whistleblowing, or ethics-related cases recorded this year? What policies and training are in place?",
        "hint": "ESRS G1-1/3/4 | GRI 205-3 | GRI 206",
    },
    {
        "id": "g_risk_management",
        "pillar": "governance",
        "category": "Risk Management",
        "text": "How does the company integrate sustainability and climate-related financial risks into the enterprise risk management framework?",
        "hint": "ESRS 2 SBM-3 | TCFD Risk Management | GRI 2-12",
    },
    {
        "id": "g_data_assurance",
        "pillar": "governance",
        "category": "Data Integrity",
        "text": "Has any sustainability data or the report itself been externally assured or verified? Describe the assurance scope and methodology.",
        "hint": "CSRD mandatory assurance | GRI 2-5",
    },
    # ── Strategy & Materiality ───────────────────────────────────────
    {
        "id": "m_double_materiality",
        "pillar": "materiality",
        "category": "Double Materiality",
        "text": "Describe the double materiality assessment process: which topics are material from an impact and financial perspective, and who were the key stakeholders consulted?",
        "hint": "ESRS 2 IRO-1 | GRI 3-1 | CSRD mandatory",
    },
    {
        "id": "m_strategy_integration",
        "pillar": "strategy",
        "category": "Strategy",
        "text": "How is sustainability integrated into the core business strategy and long-term value creation model? Any transition plan or science-based targets?",
        "hint": "ESRS 2 SBM-1/2 | TCFD Strategy | GRI 2-22",
    },
    {
        "id": "m_targets_progress",
        "pillar": "strategy",
        "category": "Targets & KPIs",
        "text": "List the company's key sustainability targets, target years, and progress made during this reporting period. Include interim milestones.",
        "hint": "ESRS 2 MDR-T | GRI 2-24 | TCFD Metrics & Targets",
    },
]

QUESTION_INDEX = {q["id"]: q for q in INTERVIEW_QUESTIONS}


# ─── System Prompts ──────────────────────────────────────────────────────────

BASE_SECTION_SYSTEM_PROMPT = (
    "You are a senior sustainability report writer with expertise in CSRD/ESRS, GRI Standards 2021, "
    "TCFD recommendations, and IFRS S1/S2. "
    "Write clear, evidence-based narrative using ONLY the verified metrics and management commentary provided. "
    "NEVER invent numbers, extrapolate data, or make assumptions beyond what is given. "
    "If data for a topic is missing, state it is not yet reported for this period rather than omitting silently. "
    "Maintain a polished, audit-ready, investor-grade tone. "
    "Avoid generic sustainability language — every claim must be grounded in the provided data. "
    "Where metrics are quantitative, always include the unit. "
    "CRITICAL FORMATTING RULES — MUST FOLLOW: "
    "(1) Output PLAIN TEXT ONLY. Absolutely NO markdown syntax of any kind. "
    "(2) Do NOT use #, ##, ###, or any heading markers. "
    "(3) Do NOT use ** or * for bold or italic — write emphasis in natural language instead. "
    "(4) Do NOT use bullet points, dashes, or numbered lists. "
    "(5) Write exclusively in well-structured prose paragraphs separated by blank lines. "
    "(6) Do NOT repeat or restate the section title — dive straight into content. "
    "Structure the content logically: context → performance data → management approach → forward-looking commitments."
)

SUMMARY_SYSTEM_PROMPT = (
    "You are a Chief Sustainability Officer communications lead preparing an executive summary "
    "for an investor-grade sustainability report. "
    "Write a concise, compelling executive summary that: "
    "(1) frames the company's sustainability positioning, "
    "(2) highlights the most significant verified metrics with year context, "
    "(3) references material risks and opportunities identified, and "
    "(4) sets reader expectations for the sections that follow. "
    "Reference ONLY the supplied metrics and section summaries. NEVER invent data. "
    "Maximum 300 words. Professional, confident tone. "
    "CRITICAL FORMATTING RULES — MUST FOLLOW: "
    "Output PLAIN TEXT ONLY. No markdown syntax (#, **, *, -, bullets). "
    "Write in clean prose paragraphs only. Do NOT use any heading markers."
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def list_interview_questions() -> list[dict[str, str]]:
    return INTERVIEW_QUESTIONS


def _assign_pillar(metric: Metric) -> str:
    metadata_pillar = metric.metadata.get("pillar") if isinstance(metric.metadata, dict) else None
    if metadata_pillar and str(metadata_pillar).lower() in SECTION_TITLES:
        return str(metadata_pillar).lower()

    haystack = f"{metric.metric_code} {metric.name}".lower()
    env_tokens = ("scope", "emission", "co2", "ghg", "energy", "fuel", "water", "waste", "electric", "kwh", "mwh", "carbon")
    soc_tokens = ("employee", "training", "safety", "injury", "trir", "ltif", "diversity", "community", "people", "gender", "hire")
    gov_tokens = ("board", "governance", "ethics", "compliance", "policy", "whistle", "risk", "audit", "corruption")

    if any(t in haystack for t in env_tokens):
        return "environmental"
    if any(t in haystack for t in soc_tokens):
        return "social"
    if any(t in haystack for t in gov_tokens):
        return "governance"
    return "environmental"


def _get_dynamic_pillars(metrics: list[Metric]) -> list[str]:
    """Return pillars present in metrics, guaranteed to include E/S/G at minimum."""
    found = {_assign_pillar(m) for m in metrics}
    # Always include the core ESG pillars — sections without metrics will say data is pending
    found.update(["environmental", "social", "governance"])
    # Ordered CSRD-logical sequence
    order = ["materiality", "strategy", "environmental", "social", "governance"]
    return [p for p in order if p in found]


def _select_metrics(metrics: list[Metric]) -> list[Metric]:
    approved = [m for m in metrics if m.status == "approved"]
    if not approved:
        return []
    agent_approved = [
        m for m in approved
        if isinstance(m.metadata, dict) and m.metadata.get("source_type") == "metric_agent"
    ]
    if not agent_approved:
        return approved
    agent_codes = {m.metric_code for m in agent_approved}
    supplemental = [
        m for m in approved
        if m.metric_code not in agent_codes
        and (not isinstance(m.metadata, dict) or m.metadata.get("source_type") != "metric_agent")
    ]
    return agent_approved + supplemental


def _normalize_interview_answers(interview_answers: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in interview_answers:
        raw = item.model_dump() if hasattr(item, "model_dump") else dict(item)
        question = QUESTION_INDEX.get(raw.get("question_id", ""))
        if not question:
            continue
        answer = (raw.get("answer") or "").strip()
        normalized.append(
            {
                "question_id": question["id"],
                "question": question["text"],
                "pillar": question["pillar"],
                "category": question.get("category", ""),
                "hint": question.get("hint", ""),
                "answer": answer or None,
                "skipped": not bool(answer),
            }
        )
    return normalized


def _build_metric_summary(metrics: list[Metric], pillar: str | None = None) -> str:
    selected = [m for m in metrics if pillar is None or _assign_pillar(m) == pillar]
    if not selected:
        return "No verified metrics were available for this category."
    lines: list[str] = []
    for m in selected:
        src_count = len(m.source_extracted_data_ids)
        lines.append(
            f"- [{m.metric_code}] {m.name}: {m.value} {m.unit} "
            f"(status={m.status}, sources={src_count})"
        )
    return "\n".join(lines)


def _build_interview_context(interview_answers: list[dict[str, Any]], pillar: str) -> str:
    answered = [a for a in interview_answers if a["pillar"] == pillar and not a["skipped"] and a["answer"]]
    if not answered:
        return "No management commentary was provided for this pillar."
    lines = []
    for a in answered:
        category = a.get("category", "")
        hint = a.get("hint", "")
        lines.append(
            f"[{category}] Q: {a['question']}\n"
            f"  A: {a['answer']}"
            + (f"\n  Standards: {hint}" if hint else "")
        )
    return "\n\n".join(lines)


def _extract_llm_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, list):
        return " ".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        ).strip()
    return str(content).strip()


def _fallback_section(pillar: str, metrics: list[Metric], interview_answers: list[dict[str, Any]]) -> str:
    selected = [m for m in metrics if _assign_pillar(m) == pillar]
    if not selected:
        return (
            f"No verified {pillar.title()} metrics are currently available for this workspace. "
            "The sustainability team should complete metric review before publishing this section. "
            "This section will be populated once quantitative data has been extracted, verified, and approved."
        )
    metric_sentences = [
        f"{m.name} recorded {m.value} {m.unit}"
        for m in selected[:5]
    ]
    commentary = [
        a["answer"]
        for a in interview_answers
        if a["pillar"] == pillar and not a["skipped"] and a["answer"]
    ]
    base = f"This {pillar.title()} section reflects {len(selected)} verified metrics from the workspace. "
    base += ". ".join(metric_sentences) + "."
    if commentary:
        base += " Management has noted that " + " ".join(commentary[:2])
    return base


def _fallback_exec_summary(metrics: list[Metric], reporting_year: int) -> str:
    if not metrics:
        return f"No verified metrics were available to assemble the {reporting_year} sustainability report summary."
    highlights = [f"{m.name}: {m.value} {m.unit}" for m in metrics[:6]]
    return (
        f"This sustainability report covers the {reporting_year} reporting period and consolidates "
        f"{len(metrics)} verified metrics across the workspace. "
        f"Key performance highlights include: {'; '.join(highlights)}. "
        "The report has been prepared using data extracted and validated through the Atlas ESG data pipeline."
    )


def _build_data_lineage(metrics: list[Metric]) -> list[dict[str, Any]]:
    return [
        {
            "metric_id": str(m.id),
            "metric_code": m.metric_code,
            "name": m.name,
            "value": m.value,
            "unit": m.unit,
            "status": m.status,
            "sources": [str(s) for s in m.source_extracted_data_ids],
            "pillar": _assign_pillar(m),
            "metadata": m.metadata,
        }
        for m in metrics
    ]


# ─── Core Generation ─────────────────────────────────────────────────────────

async def _generate_section(
    pillar: str,
    metrics: list[Metric],
    interview_answers: list[dict[str, Any]],
    output_format: str,
) -> dict[str, Any]:
    title = SECTION_TITLES.get(pillar, pillar.title().replace("_", " ") + " Performance")
    framework_instruction = FRAMEWORK_INSTRUCTIONS.get(output_format, FRAMEWORK_INSTRUCTIONS["csrd"])
    framework_tags = ESRS_TAGS.get(pillar, [])

    system_prompt = (
        BASE_SECTION_SYSTEM_PROMPT
        + f"\n\nFramework alignment ({output_format.upper()}): {framework_instruction}"
    )

    prompt = (
        f"Section: {title}\n"
        f"Reporting framework: {output_format.upper()}\n"
        f"Framework tags for this section: {', '.join(framework_tags)}\n\n"
        f"=== VERIFIED METRICS ===\n{_build_metric_summary(metrics, pillar)}\n\n"
        f"=== MANAGEMENT COMMENTARY ===\n{_build_interview_context(interview_answers, pillar)}\n\n"
        "Write a professional, audit-ready narrative section for this report. "
        "Include: (1) a brief context statement, (2) quantitative metric discussion with units, "
        "(3) management approach and key initiatives, (4) data gaps acknowledged if any, "
        "(5) forward-looking targets or commitments if mentioned in commentary. "
        "Where relevant, cite the specific framework standard inline in parentheses, e.g. (ESRS E1-6), (GRI 305-1). "
        "STRICT OUTPUT FORMAT: plain prose paragraphs only. "
        "No markdown. No # headers. No ** bold markers. No bullet lists. No dashes. "
        "Do NOT restate the section title. Start immediately with substantive content."
    )

    model_used = "fallback"
    try:
        llm = create_llm(temperature=0.2)
        response = await llm.ainvoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=prompt),
            ]
        )
        content = _extract_llm_text(response)
        if not content:
            raise RuntimeError("Empty section response from LLM")
        model_used = llm.__class__.__name__
    except Exception:
        content = _fallback_section(pillar, metrics, interview_answers)

    selected = [m for m in metrics if _assign_pillar(m) == pillar]
    caveats = [
        f"{m.name} is still pending review."
        for m in selected
        if m.status != "approved"
    ]

    return {
        "pillar": pillar,
        "title": title,
        "content": content,
        "data_caveats": caveats,
        "framework_tags": framework_tags,
        "model_used": model_used,
        "generated_at": datetime.now(UTC).isoformat(),
    }


async def _generate_exec_summary(
    metrics: list[Metric],
    sections: dict[str, dict[str, Any]],
    reporting_year: int,
    output_format: str = "csrd",
) -> str:
    section_summaries = "\n".join(
        f"- {s['title']}: {s['content'][:300]}"
        for s in sections.values()
    )
    prompt = (
        f"Reporting year: {reporting_year}\n"
        f"Framework: {output_format.upper()}\n\n"
        f"=== KEY VERIFIED METRICS ===\n{_build_metric_summary(metrics)}\n\n"
        f"=== SECTION SUMMARIES ===\n{section_summaries}\n\n"
        "Write a professional executive summary for this sustainability report. "
        "Be specific about the most significant verified metrics, material topics, and strategic commitments. "
        "Maximum 300 words. Plain prose only — no markdown, no headers, no bullet points."
    )
    try:
        llm = create_llm(temperature=0.2)
        response = await llm.ainvoke(
            [
                SystemMessage(content=SUMMARY_SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ]
        )
        content = _extract_llm_text(response)
        if not content:
            raise RuntimeError("Empty summary response")
        return content
    except Exception:
        return _fallback_exec_summary(metrics, reporting_year)


# ─── Public API ──────────────────────────────────────────────────────────────

def render_report_markdown(report: Report) -> str:
    lines = [
        f"# Sustainability Report — {report.reporting_year}",
        "",
        "## Executive Summary",
        report.exec_summary,
    ]
    for section in report.sections.values():
        tags = section.get("framework_tags", [])
        tag_str = f" _{' | '.join(tags)}_" if tags else ""
        lines.extend(["", f"## {section['title']}{tag_str}", section["content"]])
        if section.get("data_caveats"):
            lines.extend(["", "> **Data caveats:** " + " | ".join(section["data_caveats"])])
    return "\n".join(lines)


async def list_reports(company_id: str, workspace_id: str, actor_company_id: str | None = None) -> list[Report]:
    if actor_company_id and actor_company_id != company_id:
        raise AppError(ErrorCode.FORBIDDEN, "Cross-tenant access denied")
    return await Report.find({"company_id": company_id, "workspace_id": workspace_id}).sort("-created_at").to_list()


async def get_report(report_id: str, actor_company_id: str | None = None) -> Report:
    report = await Report.get(report_id)
    if not report:
        raise AppError(ErrorCode.NOT_FOUND, "Report not found")
    if actor_company_id and actor_company_id != report.company_id:
        raise AppError(ErrorCode.FORBIDDEN, "Cross-tenant access denied")
    return report


async def generate_report(
    company_id: str,
    workspace_id: str,
    actor_id: str,
    actor_company_id: str | None,
    output_format: str,
    reporting_year: int | None,
    interview_answers: list[Any],
) -> Report:
    if actor_company_id and actor_company_id != company_id:
        raise AppError(ErrorCode.FORBIDDEN, "Cross-tenant access denied")

    final_year = reporting_year or datetime.now(UTC).year

    metrics = await Metric.find({
        "company_id": company_id,
        "workspace_id": workspace_id,
        "status": "approved",
    }).sort("metric_code").to_list()

    selected_metrics = _select_metrics(metrics)
    if not selected_metrics:
        raise AppError(
            ErrorCode.CONFLICT,
            "Report generation requires at least one approved metric. "
            "Please approve metrics in the Metrics Dashboard before generating a report.",
        )

    latest_report = await Report.find({
        "workspace_id": workspace_id,
        "reporting_year": final_year,
    }).sort("-version").first_or_none()
    new_version = (latest_report.version + 1) if latest_report else 1

    normalized_answers = _normalize_interview_answers(interview_answers)

    sections: dict[str, dict[str, Any]] = {}
    for pillar in _get_dynamic_pillars(selected_metrics):
        sections[pillar] = await _generate_section(pillar, selected_metrics, normalized_answers, output_format)

    exec_summary = await _generate_exec_summary(selected_metrics, sections, final_year, output_format)

    report = Report(
        company_id=company_id,
        workspace_id=workspace_id,
        reporting_year=final_year,
        version=new_version,
        output_format=output_format,
        status="draft",
        exec_summary=exec_summary,
        sections=sections,
        data_lineage=_build_data_lineage(selected_metrics),
        interview_answers=normalized_answers,
        generated_by_id=actor_id,
    )
    await report.insert()

    await audit_service.emit(
        event_type="REPORT_GENERATED",
        actor_user_id=actor_id,
        company_id=company_id,
        workspace_id=workspace_id,
        entity_table="reports",
        entity_id=report.id,
        payload={
            "output_format": output_format,
            "reporting_year": final_year,
            "version": new_version,
            "metric_count": len(selected_metrics),
        },
    )
    return report


async def regenerate_section(
    report_id: str,
    pillar: str,
    actor_id: str,
    actor_company_id: str | None,
    output_format: str | None,
    interview_answers: list[Any],
) -> Report:
    if pillar not in SECTION_TITLES:
        raise AppError(ErrorCode.VALIDATION_ERROR, f"Unknown report pillar: '{pillar}'. Valid pillars: {list(SECTION_TITLES)}")

    report = await get_report(report_id, actor_company_id)
    if report.status != "draft":
        raise AppError(ErrorCode.CONFLICT, f"Cannot regenerate sections on a report in '{report.status}' status.")

    metrics = await Metric.find({
        "company_id": report.company_id,
        "workspace_id": report.workspace_id,
        "status": "approved",
    }).sort("metric_code").to_list()

    selected_metrics = _select_metrics(metrics)
    if not selected_metrics:
        raise AppError(ErrorCode.CONFLICT, "No approved metrics found. Cannot regenerate section.")

    normalized_answers = (
        _normalize_interview_answers(interview_answers)
        if interview_answers
        else report.interview_answers
    )
    final_format = output_format or report.output_format

    report.sections[pillar] = await _generate_section(pillar, selected_metrics, normalized_answers, final_format)
    report.exec_summary = await _generate_exec_summary(selected_metrics, report.sections, report.reporting_year, final_format)
    report.output_format = final_format
    report.interview_answers = normalized_answers
    report.data_lineage = _build_data_lineage(selected_metrics)

    await report.save_with_timestamp()

    await audit_service.emit(
        event_type="REPORT_SECTION_REGENERATED",
        actor_user_id=actor_id,
        company_id=report.company_id,
        workspace_id=report.workspace_id,
        entity_table="reports",
        entity_id=report.id,
        payload={"pillar": pillar, "output_format": final_format},
    )
    return report


async def submit_for_review(report_id: str, actor_id: str, actor_company_id: str | None) -> Report:
    report = await get_report(report_id, actor_company_id)
    if report.status != "draft":
        raise AppError(ErrorCode.CONFLICT, f"Report is in '{report.status}' status and cannot be submitted for review.")
    report.status = "review"
    report.submitted_at = datetime.now(UTC)
    report.submitted_by_id = actor_id
    await report.save_with_timestamp()
    return report


async def approve_report(report_id: str, actor_id: str, actor_company_id: str | None) -> Report:
    report = await get_report(report_id, actor_company_id)
    if report.status != "review":
        raise AppError(ErrorCode.CONFLICT, f"Report is in '{report.status}' status and cannot be approved.")

    from app.services.workflow_service import get_workflow_policy
    from app.models.user import User

    actor_user = await User.get(actor_id)
    policy = await get_workflow_policy(report.workspace_id)

    can_approve = False
    if actor_user and actor_user.role in ["system_admin", "company_owner"]:
        can_approve = True
    elif actor_user and not policy.require_publish_approval and actor_user.role == "sustainability_manager":
        can_approve = True

    if not can_approve:
        raise AppError(ErrorCode.FORBIDDEN, "Insufficient permissions to approve this report.")

    report.status = "approved"
    report.approved_at = datetime.now(UTC)
    report.approved_by_id = actor_id

    from app.services import report_render_service
    report.canonical_xhtml = await report_render_service.render_xhtml(report)

    if report.canonical_xhtml:
        import structlog
        from app.models.document import Document
        from app.models.extraction import ExtractedData
        from app.services import blockchain_service, verification_service
        
        logger = structlog.get_logger()
        report_hash = verification_service.build_report_content_hash(report)
        report.sha256_hash = report_hash
        
        try:
            tx_id = await blockchain_service.anchor_document_hash(report_hash)
            report.blockchain_tx_id = tx_id
            if tx_id:
                logger.info("report_anchored_on_blockchain", tx_id=tx_id, report_id=report_id)
        except Exception as exc:
            logger.warning("report_blockchain_anchoring_failed", error=str(exc))

        # Optional high-assurance mode: anchor source raw document hashes referenced by lineage.
        settings = get_settings()
        if settings.ESG_HIGH_ASSURANCE_RAW_DOC_ANCHORING:
            extraction_ids: set[str] = set()
            for row in report.data_lineage:
                for source_id in row.get("sources", []):
                    extraction_ids.add(str(source_id))
            extraction_ids = set(list(extraction_ids)[: settings.ESG_HIGH_ASSURANCE_MAX_DOCS])
            if extraction_ids:
                extractions = await ExtractedData.find({"id": {"$in": list(extraction_ids)}}).to_list()
                document_ids = [e.document_id for e in extractions if getattr(e, "document_id", None)]
                if document_ids:
                    docs = await Document.find({"id": {"$in": document_ids}}).to_list()
                    anchored = 0
                    for doc in docs[: settings.ESG_HIGH_ASSURANCE_MAX_DOCS]:
                        if doc.blockchain_tx_id:
                            anchored += 1
                            continue
                        try:
                            tx_id = await blockchain_service.anchor_document_hash(doc.sha256_hash)
                            if tx_id:
                                doc.blockchain_tx_id = tx_id
                                await doc.save()
                                anchored += 1
                        except Exception as exc:
                            logger.warning("raw_document_blockchain_anchoring_failed", document_id=str(doc.id), error=str(exc))
                    report.raw_document_anchor_count = anchored
                    report.high_assurance_mode = True

        signature = verification_service.build_verification_signature(report)
        report.verification_signature = signature
        report.verification_url = verification_service.build_verification_url(report, signature)
        report.verification_qr_data_url = verification_service.build_qr_data_url(report.verification_url)
        # Re-render with verification block now populated.
        report.canonical_xhtml = await report_render_service.render_xhtml(report)

    await report.save_with_timestamp()
    return report


async def reject_report(report_id: str, actor_id: str, reason: str, actor_company_id: str | None) -> Report:
    report = await get_report(report_id, actor_company_id)
    if report.status != "review":
        raise AppError(ErrorCode.CONFLICT, f"Report is in '{report.status}' status and cannot be rejected.")
    report.status = "rejected"
    report.rejected_at = datetime.now(UTC)
    report.rejected_by_id = actor_id
    report.rejection_reason = reason
    await report.save_with_timestamp()
    return report


async def publish_report(report_id: str, actor_id: str, actor_company_id: str | None) -> Report:
    report = await get_report(report_id, actor_company_id)
    if report.status != "approved":
        raise AppError(ErrorCode.CONFLICT, f"Report must be approved before publishing. Current status: '{report.status}'.")
    previous_published = await Report.find(
        {
            "company_id": report.company_id,
            "workspace_id": report.workspace_id,
            "reporting_year": report.reporting_year,
            "status": "published",
            "id": {"$ne": report.id},
        }
    ).to_list()
    for old in previous_published:
        old.superseded_by_report_id = str(report.id)
        await old.save_with_timestamp()
    report.status = "published"
    report.published_at = datetime.now(UTC)
    report.published_by_id = actor_id
    await report.save_with_timestamp()
    return report
