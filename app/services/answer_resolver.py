"""
Auto-fill resolver — the "memory & relations" layer.

For each active interview question it tries to answer from data Atlas already
holds, attaching provenance so the value is traceable and edits can require a
reason. Crucially it BRIDGES the three metric vocabularies that otherwise never
meet:

  * interview/VSME codes   e.g. ENERGY_ELEC_CONSUMPTION
  * ESG-engine codes       e.g. electricity_kwh_total, scope2_tco2e
  * raw extraction codes   e.g. "<template>:value:<extractionId>" (unit-tagged)

Resolution per question (config-driven via `interview.metric_aliases`):
  1. an APPROVED metric whose code == the question code   -> filled & approved
  2. an APPROVED metric via alias code / unit match        -> filled & approved
  3. a PENDING metric (e.g. fresh document extraction)     -> filled as a
     SUGGESTION (interview response stays "pending") so the user sees the value
     from their upload and confirms it — without bypassing the review gate
  4. an approved metric from a PRIOR reporting period       -> suggestion

All matches carry `autofill_source` provenance (document, prior period, etc.).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.models.interview_response import InterviewResponse
from app.models.metric import Metric
from app.models.workspace import Workspace
from app.services import config_service
from app.services.metric_service import (
    _coerce_numeric, _normalize_unit, _to_kwh, _to_tco2e,
)


def _convert(value: float, unit: Optional[str], domain: str) -> Optional[float]:
    """Convert a metric value into the question's expected unit by domain."""
    if domain == "kwh":
        return _to_kwh(value, unit)
    if domain == "tco2e":
        return _to_tco2e(value, unit)
    if domain == "m3":
        return value if _normalize_unit(unit) == "m3" else None
    if domain == "litres":
        return value if _normalize_unit(unit) in ("l", "litre", "litres") else None
    if domain == "count":
        return value
    return value


def _resolve_from_metrics(metrics: List[Metric], alias: Dict[str, Any]) -> Optional[Tuple[float, Metric, bool]]:
    """Return (value_in_target_unit, source_metric, is_approved) or None.

    Matches by alias code first, then by unit within the domain (catches raw
    composite extraction codes). Prefers approved over pending; aggregates
    same-unit electricity by summing.
    """
    codes = set(alias.get("codes", []))
    domain = alias.get("domain", "")

    def candidates(approved_only: bool) -> List[Tuple[float, Metric]]:
        out: List[Tuple[float, Metric]] = []
        for m in metrics:
            if approved_only and m.status != "approved":
                continue
            if not approved_only and m.status not in ("approved", "pending"):
                continue
            raw = _coerce_numeric(m.value)
            if raw is None:
                continue
            matched = m.metric_code in codes
            converted = _convert(raw, m.unit, domain) if (matched or domain in ("kwh", "tco2e", "m3", "litres")) else None
            # code match wins; otherwise accept a clean unit match (raw extractions)
            if matched and converted is None:
                converted = raw
            if converted is None:
                continue
            out.append((converted, m))
        return out

    # 1) approved, exact alias code preferred
    approved = candidates(approved_only=True)
    exact_approved = [(v, m) for v, m in approved if m.metric_code in codes]
    if exact_approved:
        v, m = exact_approved[0]
        return (v, m, True)
    if approved:
        # sum same-domain approved values (e.g. multiple electricity bills)
        total = sum(v for v, _ in approved)
        return (total, approved[0][1], True)

    # 2) pending (fresh extractions) -> suggestion
    pending = [c for c in candidates(approved_only=False) if c[1].status == "pending"]
    if pending:
        exact_pending = [(v, m) for v, m in pending if m.metric_code in codes]
        chosen = exact_pending or pending
        total = sum(v for v, _ in chosen)
        return (total, chosen[0][1], False)

    return None


def _provenance(metric: Metric, kind: str, label: str, approved: bool, workspace_id: Optional[str] = None) -> Dict[str, Any]:
    prov: Dict[str, Any] = {"type": kind, "label": label, "metric_id": str(metric.id),
                            "confidence": 0.95 if approved else 0.75}
    if workspace_id:
        prov["workspace_id"] = workspace_id
    ids = getattr(metric, "source_extracted_data_ids", None) or []
    if ids:
        prov["type"] = "document"
        prov["extracted_data_ids"] = [str(i) for i in ids]
        prov["label"] = "Extracted from your uploaded document"
    return prov


async def autofill(workspace_id: str, company_id: str) -> int:
    """Populate unanswered interview questions from existing evidence. Returns count filled."""
    from app.services import interview_service

    questions, locked = await interview_service.get_active_questions(workspace_id)
    if locked:
        return 0

    aliases = config_service.get("interview.metric_aliases")
    existing = {r.question_id: r for r in await interview_service.get_responses(workspace_id)}
    ws_metrics = await Metric.find(Metric.workspace_id == workspace_id).to_list()

    prior_workspaces: List[Workspace] = [
        w for w in await Workspace.find(Workspace.company_id == company_id).sort("-created_at").to_list()
        if w.id != workspace_id
    ]

    filled = 0
    for q in questions:
        qid = q["id"]
        metric_code = q.get("metric_code")
        if not metric_code:
            continue
        current = existing.get(qid)
        if current and current.status == "approved":
            continue  # never overwrite a confirmed answer

        value: Optional[float] = None
        unit = (q.get("value_schema") or {}).get("unit", "")
        source_metric: Optional[Metric] = None
        approved = False
        prov: Optional[Dict[str, Any]] = None

        # (a) exact-code metric in this workspace
        exact = [m for m in ws_metrics if m.metric_code == metric_code and _coerce_numeric(m.value) is not None]
        exact_appr = [m for m in exact if m.status == "approved"]
        if exact_appr:
            source_metric = exact_appr[0]; value = _coerce_numeric(source_metric.value); approved = True
            prov = _provenance(source_metric, "approved_metric", source_metric.name or metric_code, True)
        elif metric_code in aliases:
            # (b/c) alias / unit bridge across engine + raw extraction codes
            hit = _resolve_from_metrics(ws_metrics, aliases[metric_code])
            if hit:
                value, source_metric, approved = hit
                unit = aliases[metric_code].get("unit", unit)
                prov = _provenance(source_metric, "approved_metric" if approved else "document",
                                   source_metric.name or metric_code, approved)
        if value is None and exact:  # exact but pending
            source_metric = exact[0]; value = _coerce_numeric(source_metric.value); approved = False
            prov = _provenance(source_metric, "document", source_metric.name or metric_code, False)

        # (d) prior reporting period fallback (approved only -> suggestion)
        if value is None:
            for pw in prior_workspaces:
                pm = await Metric.find_one(Metric.workspace_id == pw.id, Metric.metric_code == metric_code)
                if pm and pm.status == "approved" and _coerce_numeric(pm.value) is not None:
                    source_metric = pm; value = _coerce_numeric(pm.value); approved = False
                    prov = _provenance(pm, "prior_period", f"Prior period · {pw.name}", False, pw.id)
                    break

        if value is None or source_metric is None:
            continue

        resp = current or InterviewResponse(company_id=company_id, workspace_id=workspace_id, question_id=qid)
        resp.answer_mode = "value"
        resp.raw_value = value
        resp.raw_unit = unit
        resp.interpreted_metric_code = metric_code
        resp.interpreted_value = value
        resp.interpreted_unit = unit
        resp.interpretation_confidence = prov.get("confidence", 0.8) if prov else 0.8
        resp.autofill_source = prov
        if approved:
            resp.interpretation_reasoning = f"Auto-filled — {prov['label']}"
            resp.status = "approved"
            resp.approved_metric_id = str(source_metric.id)
        else:
            # Unreviewed evidence: show it as a suggestion the user confirms.
            resp.interpretation_reasoning = f"Suggested from {prov['label']} — review and confirm"
            resp.status = "pending"
        await resp.save_with_timestamp()
        filled += 1

    return filled
