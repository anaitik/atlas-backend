"""
Compliance map service.

Given a workspace's company profile, determines which ESRS disclosures
are mandatory, conditional, or deferred — and checks data coverage from
existing metrics.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.models.metric import Metric
from app.models.workspace import Workspace

_CATALOG_PATH = Path(__file__).parent.parent / "data" / "esrs_catalog.json"


def _load_catalog() -> list[dict[str, Any]]:
    return json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))


def _csrd_phase(workspace: Workspace) -> int | None:
    """Derive CSRD phase from workspace profile. Returns 1, 2, 3, or None (exempt/unknown)."""
    employees = workspace.employee_count_range or ""
    listed = workspace.is_listed

    large_employees = employees in ("500-1999", "2000+")
    medium_large_employees = employees in ("250-499", "500-1999", "2000+")
    sme_employees = employees in ("50-249")

    if listed and large_employees:
        return 1
    if medium_large_employees:
        return 2
    if listed and sme_employees:
        return 3
    if large_employees:
        return 2
    return None


def _profile_complete(workspace: Workspace) -> tuple[bool, list[str]]:
    missing = []
    if not workspace.nace_sector:
        missing.append("nace_sector")
    if not workspace.employee_count_range:
        missing.append("employee_count_range")
    if not workspace.turnover_range_eur:
        missing.append("turnover_range_eur")
    return len(missing) == 0, missing


def _obligation_status(
    disclosure: dict[str, Any],
    phase: int | None,
    is_first_time: bool,
    reporting_year: int | None,
) -> tuple[str, bool]:
    """Returns (obligation_status, deferred)."""
    req_type = disclosure.get("requirement_type", "conditional")
    phase_from = disclosure.get("phase_mandatory_from", 2)
    defer_years = disclosure.get("first_reporter_defer_years", 0)

    if phase is None:
        # Profile incomplete — cannot determine
        return "unknown", False

    if req_type == "mandatory":
        if phase > phase_from:
            # Company is in a later phase than when this became mandatory — still mandatory
            pass
        elif phase < phase_from:
            return "not_applicable", False

        if is_first_time and defer_years > 0:
            return "deferred", True

        return "mandatory", False

    # conditional — only required if material topic was selected
    return "conditional", False


async def build_compliance_map(workspace: Workspace) -> dict[str, Any]:
    catalog = _load_catalog()
    phase = _csrd_phase(workspace)
    profile_ok, missing_fields = _profile_complete(workspace)

    # Load existing approved/pending metrics for data coverage check
    metrics = await Metric.find({
        "company_id": workspace.company_id,
        "workspace_id": workspace.id,
    }).to_list()

    approved_codes = {m.metric_code for m in metrics if m.status == "approved"}
    pending_codes = {m.metric_code for m in metrics if m.status == "pending"}

    disclosures_out: list[dict[str, Any]] = []
    pillar_stats: dict[str, dict[str, int]] = {
        "environmental": {"required": 0, "complete": 0, "partial": 0, "not_started": 0},
        "social": {"required": 0, "complete": 0, "partial": 0, "not_started": 0},
        "governance": {"required": 0, "complete": 0, "partial": 0, "not_started": 0},
    }

    total_required = 0
    total_complete = 0
    total_partial = 0
    total_not_started = 0

    material_topics_lower = {t.lower() for t in (workspace.material_topics or [])}

    for disc in catalog:
        obligation, deferred = _obligation_status(
            disc, phase, workspace.is_first_time_reporter, workspace.reporting_year
        )

        # For conditional disclosures, check if the relevant material topic was selected
        if obligation == "conditional":
            topic_lower = disc.get("topic", "").lower()
            if not any(topic_lower in mt or mt in topic_lower for mt in material_topics_lower):
                obligation = "not_applicable"

        # Data coverage
        metric_codes: list[str] = disc.get("metric_codes", [])
        if not metric_codes:
            # No metric codes — data status is text-only (manual entry required)
            data_status = "not_started"
        else:
            codes_set = set(metric_codes)
            has_approved = bool(codes_set & approved_codes)
            has_pending = bool(codes_set & pending_codes)
            if has_approved:
                data_status = "complete"
            elif has_pending:
                data_status = "partial"
            else:
                data_status = "not_started"

        pillar = disc.get("pillar", "governance")
        is_required = obligation in ("mandatory", "deferred")

        if is_required:
            total_required += 1
            ps = pillar_stats.get(pillar, pillar_stats["governance"])
            ps["required"] += 1
            if data_status == "complete":
                total_complete += 1
                ps["complete"] += 1
            elif data_status == "partial":
                total_partial += 1
                ps["partial"] += 1
            else:
                total_not_started += 1
                ps["not_started"] += 1

        disclosures_out.append({
            "id": disc["id"],
            "standard": disc["standard"],
            "topic": disc["topic"],
            "title": disc["title"],
            "pillar": pillar,
            "obligation_status": obligation,
            "data_status": data_status,
            "metric_codes": metric_codes,
            "description": disc.get("description", ""),
            "input_guidance": disc.get("input_guidance", ""),
            "deferred": deferred,
        })

    completion_pct = round((total_complete / total_required) * 100) if total_required > 0 else 0

    pillar_completion: dict[str, Any] = {}
    for p, ps in pillar_stats.items():
        req = ps["required"]
        comp = ps["complete"]
        pillar_completion[p] = {
            "required": req,
            "complete": comp,
            "partial": ps["partial"],
            "not_started": ps["not_started"],
            "pct": round((comp / req) * 100) if req > 0 else 0,
        }

    return {
        "workspace_id": str(workspace.id),
        "csrd_phase": phase,
        "total_required": total_required,
        "total_complete": total_complete,
        "total_partial": total_partial,
        "total_not_started": total_not_started,
        "completion_pct": completion_pct,
        "disclosures": disclosures_out,
        "profile_complete": profile_ok,
        "profile_missing_fields": missing_fields,
        "pillar_completion": pillar_completion,
    }
