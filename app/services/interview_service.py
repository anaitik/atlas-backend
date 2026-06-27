"""
VSME guided interview service — answer submission, AI interpretation, metric approval.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.models.interview_response import InterviewResponse
from app.models.metric import Metric, MetricStatus

QUESTIONS_FILE = Path(__file__).parent.parent / "data" / "vsme_questions.json"

_QUESTIONS: Optional[List[Dict]] = None


def _load_questions() -> List[Dict]:
    global _QUESTIONS
    if _QUESTIONS is None:
        with open(QUESTIONS_FILE) as f:
            _QUESTIONS = json.load(f)
    return _QUESTIONS


def get_questions() -> List[Dict]:
    return _load_questions()


def get_question_by_id(question_id: str) -> Optional[Dict]:
    return next((q for q in get_questions() if q["id"] == question_id), None)


async def get_active_questions(workspace_id: str) -> tuple[List[Dict], bool]:
    """Active interview question set for a workspace.

    Returns (questions, locked). Delegates to the approved blueprint; falls back
    to the canonical default set for legacy workspaces or when no DB is available.
    """
    from app.services import blueprint_service
    return await blueprint_service.get_active_questions(workspace_id)


async def resolve_question(workspace_id: str, question_id: str) -> Optional[Dict]:
    """Find a question in the workspace's active set, falling back to the static catalogue."""
    try:
        questions, _ = await get_active_questions(workspace_id)
        found = next((q for q in questions if q["id"] == question_id), None)
        if found:
            return found
    except Exception:
        pass
    return get_question_by_id(question_id)


async def get_responses(workspace_id: str) -> List[InterviewResponse]:
    return await InterviewResponse.find(
        InterviewResponse.workspace_id == workspace_id
    ).to_list()


async def get_response(workspace_id: str, question_id: str) -> Optional[InterviewResponse]:
    return await InterviewResponse.find_one(
        InterviewResponse.workspace_id == workspace_id,
        InterviewResponse.question_id == question_id,
    )


async def submit_answer(
    company_id: str,
    workspace_id: str,
    question_id: str,
    answer_mode: str,
    document_id: Optional[str] = None,
    raw_value: Optional[float] = None,
    raw_unit: Optional[str] = None,
    raw_text: Optional[str] = None,
    skipped_reason: Optional[str] = None,
) -> InterviewResponse:
    # Resolve against the workspace's active (approved-blueprint) question set,
    # and refuse answers while the blueprint is still locked for officer review.
    active_questions, locked = await get_active_questions(workspace_id)
    if locked:
        from app.core.errors import AppError, ErrorCode
        raise AppError(ErrorCode.FORBIDDEN,
                       "This interview is being finalized and isn't open for answers yet.")
    question = next((q for q in active_questions if q["id"] == question_id), None) \
        or get_question_by_id(question_id)
    if not question:
        from app.core.errors import AppError, ErrorCode
        raise AppError(ErrorCode.NOT_FOUND, f"Question '{question_id}' not found")

    resp = await get_response(workspace_id, question_id)
    if not resp:
        resp = InterviewResponse(
            company_id=company_id,
            workspace_id=workspace_id,
            question_id=question_id,
        )

    resp.answer_mode = answer_mode
    resp.document_id = document_id
    resp.raw_value = raw_value
    resp.raw_unit = raw_unit
    resp.raw_text = raw_text
    resp.skipped_reason = skipped_reason

    if answer_mode == "skipped":
        resp.status = "skipped"
    elif answer_mode == "value" and raw_value is not None:
        # Direct numeric entry — auto-interpret, no LLM needed
        default_unit = (question.get("value_schema") or {}).get("unit", "")
        resp.interpreted_metric_code = question["metric_code"]
        resp.interpreted_value = raw_value
        resp.interpreted_unit = raw_unit or default_unit
        resp.interpretation_confidence = 1.0
        resp.interpretation_reasoning = "Direct numeric entry by user"
        resp.status = "pending"
    else:
        resp.status = "pending"

    await resp.save_with_timestamp()
    return resp


async def interpret_text(workspace_id: str, question_id: str, raw_text: str) -> Dict[str, Any]:
    """
    Use the configured LLM to extract a numeric metric value from free-form text.
    Resolves the question against the workspace's active blueprint so AI-added
    questions work too. Returns {value, unit, confidence, reasoning}.
    """
    from app.llm_factory import create_llm
    from langchain_core.messages import HumanMessage, SystemMessage

    question = await resolve_question(workspace_id, question_id)
    if not question:
        return {"value": None, "unit": None, "confidence": 0.0, "reasoning": "Unknown question"}

    vs = question.get("value_schema") or {}
    expected_unit = vs.get("unit", "appropriate units")
    is_boolean = expected_unit == "boolean"

    llm = create_llm(temperature=0.0, max_tokens=256)

    system = SystemMessage(content=(
        "You are an ESG data extraction specialist helping banks assess MSME sustainability. "
        "Extract numeric values from user answers. Respond with valid JSON only — no markdown."
    ))

    boolean_note = (
        "For this yes/no question: use value=1 for yes/have one, value=0 for no/don't have one."
        if is_boolean else
        f"If the user says 'no', 'none', or 'not applicable' → value=0, confidence=0.9. "
        f"Convert to {expected_unit} if a different unit is given."
    )

    human = HumanMessage(content=(
        f'Question: "{question["question_text"]}"\n'
        f"Metric: {question['metric_name']} ({question['metric_code']})\n"
        f"Expected unit: {expected_unit}\n"
        f'User answer: "{raw_text}"\n\n'
        f"{boolean_note}\n"
        "Return JSON:\n"
        '{"value": <number or null>, "unit": "<unit>", "confidence": <0.0-1.0>, "reasoning": "<one sentence>"}'
    ))

    try:
        result = await llm.ainvoke([system, human])
        content = result.content.strip()
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
        parsed = json.loads(content)
        return {
            "value": parsed.get("value"),
            "unit": parsed.get("unit", expected_unit),
            "confidence": float(parsed.get("confidence", 0.0)),
            "reasoning": parsed.get("reasoning", ""),
        }
    except Exception as exc:
        return {
            "value": None,
            "unit": expected_unit,
            "confidence": 0.0,
            "reasoning": f"Interpretation could not be completed: {exc}",
        }


async def store_interpretation(
    workspace_id: str,
    question_id: str,
    interpretation: Dict[str, Any],
) -> Optional[InterviewResponse]:
    resp = await get_response(workspace_id, question_id)
    if not resp:
        return None
    question = await resolve_question(workspace_id, question_id)
    resp.interpreted_metric_code = question["metric_code"] if question else None
    resp.interpreted_value = interpretation.get("value")
    resp.interpreted_unit = interpretation.get("unit")
    resp.interpretation_confidence = interpretation.get("confidence", 0.0)
    resp.interpretation_reasoning = interpretation.get("reasoning", "")
    await resp.save_with_timestamp()
    return resp


async def approve_answer(
    workspace_id: str,
    question_id: str,
    company_id: str,
    override_value: Optional[float] = None,
    override_unit: Optional[str] = None,
    override_reason: Optional[str] = None,
) -> Optional[InterviewResponse]:
    resp = await get_response(workspace_id, question_id)
    if not resp:
        return None
    question = await resolve_question(workspace_id, question_id)
    if not question:
        return None

    # Editing a value that Atlas auto-filled/AI-interpreted requires a reason
    # (recorded for the audit trail).
    changing = override_value is not None and override_value != resp.interpreted_value
    was_suggested = bool(resp.autofill_source) or (resp.interpretation_confidence or 0) < 1.0
    if changing and was_suggested and not (override_reason and override_reason.strip()):
        from app.core.errors import AppError, ErrorCode
        raise AppError(ErrorCode.VALIDATION_ERROR,
                       "A reason is required to change an auto-filled or AI-interpreted value.")
    if changing and override_reason:
        resp.override_reason = override_reason.strip()

    final_value = override_value if override_value is not None else resp.interpreted_value
    final_unit = override_unit or resp.interpreted_unit
    metric_code = resp.interpreted_metric_code or question["metric_code"]

    if final_value is None:
        from app.core.errors import AppError, ErrorCode
        raise AppError(ErrorCode.BAD_REQUEST, "No value to approve — interpret the answer first")

    existing = await Metric.find_one(
        Metric.workspace_id == workspace_id,
        Metric.metric_code == metric_code,
    )

    if existing:
        existing.value = final_value
        existing.unit = final_unit or ""
        existing.status = "approved"
        existing.metadata = {
            **existing.metadata,
            "input_mode": "interview",
            "question_id": question_id,
            "human_override": True,
        }
        await existing.save_with_timestamp()
        metric_id = str(existing.id)
    else:
        metric = Metric(
            company_id=company_id,
            workspace_id=workspace_id,
            metric_code=metric_code,
            name=question["metric_name"],
            value=final_value,
            unit=final_unit or "",
            pillar=question["pillar"],
            status="approved",
            metadata={
                "input_mode": "interview",
                "question_id": question_id,
                "human_override": True,
                "source": "vsme_interview",
            },
        )
        await metric.insert()
        metric_id = str(metric.id)

    if override_value is not None:
        resp.interpreted_value = override_value
    if override_unit is not None:
        resp.interpreted_unit = override_unit
    resp.status = "approved"
    resp.approved_metric_id = metric_id
    await resp.save_with_timestamp()

    # Auto-estimate GHG if energy question was just approved
    try:
        await _try_calculate_ghg(workspace_id, company_id, question_id)
    except Exception:
        pass

    return resp


async def get_progress(workspace_id: str) -> Dict[str, Any]:
    from app.models.workspace import Workspace
    from app.services import esg_score_service

    questions, _locked = await get_active_questions(workspace_id)
    responses = await get_responses(workspace_id)
    workspace = await Workspace.get(workspace_id)

    approved = sum(1 for r in responses if r.status == "approved")
    skipped = sum(1 for r in responses if r.answer_mode == "skipped")
    answered = sum(1 for r in responses if r.answer_mode not in ("skipped",) and r.status != "skipped")
    total = len(questions)
    completion_pct = round(approved / total * 100) if total > 0 else 0

    # Atlas ESG Score v2 — real performance, completeness and data-trust
    # (replaces the legacy "score = % of questions answered").
    atlas_score = esg_score_service.compute_score(workspace, responses, questions)

    # Legacy fields are now backed by the real engine, so every existing
    # consumer (bank portal, gap page, report) shows the performance score —
    # not completion. pillar_scores carry pillar performance (None -> 0).
    pillar_scores: Dict[str, int] = {
        p: (s or 0) for p, s in atlas_score["pillar_performance"].items()
    }
    overall_esg_score = atlas_score["performance_score"] or 0
    data_quality_score = atlas_score["data_trust_score"]

    return {
        "workspace_id": workspace_id,
        "total_questions": total,
        "answered": answered,
        "approved": approved,
        "skipped": skipped,
        "completion_pct": completion_pct,
        "pillar_scores": pillar_scores,
        "overall_esg_score": overall_esg_score,
        "data_quality_score": data_quality_score,
        "atlas_score": atlas_score,
        "responses": responses,
    }


async def _try_calculate_ghg(workspace_id: str, company_id: str, approved_question_id: str) -> None:
    """
    When electricity (vsme-e1) or fuel (vsme-e3) is approved,
    auto-estimate total GHG (vsme-e4) using EU emission factors.
    Only fills vsme-e4 if it wasn't answered by a human.
    Scope 2: kWh × 0.276 kgCO2e/kWh (EEA EU27 avg 2023)
    Scope 1: litres × 2.688 kgCO2e/L (diesel combustion, DESNZ 2024)
    """
    if approved_question_id not in ("vsme-e1", "vsme-e3"):
        return

    e1 = await get_response(workspace_id, "vsme-e1")
    e3 = await get_response(workspace_id, "vsme-e3")

    kwh = (e1.interpreted_value or 0.0) if (e1 and e1.status == "approved") else 0.0
    litres = (e3.interpreted_value or 0.0) if (e3 and e3.status == "approved") else 0.0

    if kwh == 0.0 and litres == 0.0:
        return

    scope2_kg = kwh * 0.276
    scope1_kg = litres * 2.68784
    total_t = round((scope1_kg + scope2_kg) / 1000, 4)

    # Don't overwrite a human-entered vsme-e4 answer
    existing_e4 = await get_response(workspace_id, "vsme-e4")
    if existing_e4 and existing_e4.status == "approved":
        reasoning = existing_e4.interpretation_reasoning or ""
        if not reasoning.startswith("Atlas estimated"):
            return

    reasoning = (
        f"Atlas estimated from {kwh:,.0f} kWh electricity "
        f"(Scope 2: {scope2_kg/1000:.3f} tCO2e, EU avg 0.276 kgCO2e/kWh) "
        f"+ {litres:,.0f} L fuel "
        f"(Scope 1: {scope1_kg/1000:.3f} tCO2e, diesel 2.688 kgCO2e/L). "
        f"Total: {total_t} tCO2e."
    )

    resp = existing_e4 or InterviewResponse(
        company_id=company_id,
        workspace_id=workspace_id,
        question_id="vsme-e4",
    )
    resp.answer_mode = "value"
    resp.raw_value = total_t
    resp.raw_unit = "tCO2e"
    resp.interpreted_metric_code = "GHG_TOTAL_EMISSIONS"
    resp.interpreted_value = total_t
    resp.interpreted_unit = "tCO2e"
    resp.interpretation_confidence = 0.85
    resp.interpretation_reasoning = reasoning
    resp.status = "approved"
    await resp.save_with_timestamp()

    # Create / update the Metric record (only if not human-entered)
    existing_metric = await Metric.find_one(
        Metric.workspace_id == workspace_id,
        Metric.metric_code == "GHG_TOTAL_EMISSIONS",
    )
    if existing_metric and existing_metric.status == "approved":
        if not (existing_metric.metadata or {}).get("atlas_estimated"):
            return

    if existing_metric:
        existing_metric.value = total_t
        existing_metric.unit = "tCO2e"
        existing_metric.metadata = {
            **(existing_metric.metadata or {}),
            "atlas_estimated": True,
            "scope1_tco2e": round(scope1_kg / 1000, 4),
            "scope2_tco2e": round(scope2_kg / 1000, 4),
        }
        await existing_metric.save_with_timestamp()
    else:
        metric = Metric(
            company_id=company_id,
            workspace_id=workspace_id,
            metric_code="GHG_TOTAL_EMISSIONS",
            name="Total GHG Emissions",
            value=total_t,
            unit="tCO2e",
            pillar="environmental",
            status="approved",
            metadata={
                "atlas_estimated": True,
                "scope1_tco2e": round(scope1_kg / 1000, 4),
                "scope2_tco2e": round(scope2_kg / 1000, 4),
                "calculation_basis": "EU avg grid + diesel factor",
                "input_mode": "interview",
                "question_id": "vsme-e4",
                "human_override": False,
            },
        )
        await metric.insert()


async def sync_metric_to_interview(
    workspace_id: str,
    company_id: str,
    metric_code: str,
    value: float,
    unit: str,
) -> Optional[InterviewResponse]:
    """
    Called when a metric is approved via manual entry or metric agent.
    If it maps to a VSME question, auto-fills the interview response (without
    overwriting an already-approved answer from the interview flow itself).
    """
    question = next((q for q in get_questions() if q["metric_code"] == metric_code), None)
    if not question:
        return None

    current = await get_response(workspace_id, question["id"])
    if current and current.status == "approved":
        return current  # Don't overwrite

    resp = current or InterviewResponse(
        company_id=company_id,
        workspace_id=workspace_id,
        question_id=question["id"],
    )
    resp.answer_mode = "value"
    resp.raw_value = value
    resp.raw_unit = unit
    resp.interpreted_metric_code = metric_code
    resp.interpreted_value = value
    resp.interpreted_unit = unit
    resp.interpretation_confidence = 1.0
    resp.interpretation_reasoning = "Pre-filled from approved metric"
    resp.status = "approved"
    await resp.save_with_timestamp()
    return resp


async def prefill_from_existing_metrics(workspace_id: str, company_id: str) -> int:
    """
    Scan approved metrics and pre-fill interview responses for matching questions.
    Returns number of responses pre-filled.
    """
    questions = get_questions()
    metric_codes = [q["metric_code"] for q in questions]

    existing = await Metric.find(
        Metric.workspace_id == workspace_id,
        {"metric_code": {"$in": metric_codes}},
    ).to_list()
    approved = [m for m in existing if m.status == "approved"]
    metric_map = {m.metric_code: m for m in approved}
    count = 0

    for question in questions:
        metric = metric_map.get(question["metric_code"])
        if not metric:
            continue

        current = await get_response(workspace_id, question["id"])
        if current and current.status == "approved":
            continue

        resp = current or InterviewResponse(
            company_id=company_id,
            workspace_id=workspace_id,
            question_id=question["id"],
        )
        resp.answer_mode = "value"
        resp.raw_value = metric.value
        resp.raw_unit = metric.unit
        resp.interpreted_metric_code = metric.metric_code
        resp.interpreted_value = metric.value
        resp.interpreted_unit = metric.unit
        resp.interpretation_confidence = 1.0
        resp.interpretation_reasoning = "Pre-filled from existing approved metric"
        resp.status = "approved"
        resp.approved_metric_id = str(metric.id)
        await resp.save_with_timestamp()
        count += 1

    return count
