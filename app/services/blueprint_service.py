"""
Interview blueprint service — seeds a per-workspace question set from the canonical
config, augments it with AI-tailored questions, and exposes the audit-officer
curation flow (edit/delete with reason, approve). The MSME interview reads the
APPROVED blueprint; until approval the interview is locked (full gate).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.models.interview_blueprint import BlueprintQuestion, InterviewBlueprint
from app.services import config_service


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_questions() -> List[BlueprintQuestion]:
    """Canonical questions from config (the scored backbone), pre-approved."""
    defaults = config_service.get("interview.default_blueprint").get("questions", [])
    out: List[BlueprintQuestion] = []
    for q in defaults:
        out.append(BlueprintQuestion(
            local_id=q["id"],
            metric_code=q.get("metric_code"),
            metric_name=q.get("metric_name", ""),
            pillar=q.get("pillar", "environmental"),
            category=q.get("category", ""),
            question_text=q["question_text"],
            help_text=q.get("help_text", ""),
            answer_modes=q.get("answer_modes") or ["value", "text"],
            value_schema=q.get("value_schema"),
            requirement="mandatory",
            skip_condition=q.get("skip_condition"),
            grounding_citation="efrag-vsme",
            bank_relevance=q.get("bank_relevance", ""),
            source="canonical",
            status="approved",
        ))
    return out


def question_to_dict(q: BlueprintQuestion) -> Dict[str, Any]:
    """Shape a blueprint question like the legacy get_questions() dicts."""
    return {
        "id": q.local_id,
        "pillar": q.pillar,
        "category": q.category,
        "question_text": q.question_text,
        "help_text": q.help_text,
        "answer_modes": q.answer_modes,
        "value_schema": q.value_schema,
        "metric_code": q.metric_code,
        "metric_name": q.metric_name,
        "skip_condition": q.skip_condition,
        "bank_relevance": q.bank_relevance,
        "requirement": q.requirement,
        "source": q.source,
        "grounding_citation": q.grounding_citation,
    }


async def get_blueprint(workspace_id: str) -> Optional[InterviewBlueprint]:
    return await InterviewBlueprint.find_one(InterviewBlueprint.workspace_id == workspace_id)


async def create_for_workspace(workspace_id: str, company_id: str, use_ai: bool = True) -> InterviewBlueprint:
    """Seed (canonical) + AI-augment a blueprint and submit it for officer review."""
    from app.models.company import Company

    existing = await get_blueprint(workspace_id)
    bp = existing or InterviewBlueprint(workspace_id=workspace_id, company_id=company_id)
    bp.questions = _seed_questions()
    bp.grounding_refs = [s.get("id") for s in config_service.get("interview.grounding").get("sources", [])]
    bp.generated_by = "seed"

    if use_ai:
        try:
            from app.agentic.interview.generation import generate_tailored_questions
            company = await Company.get(company_id)
            profile = (company.profile_data if company else {}) or {}
            tailored = await generate_tailored_questions(profile)
            seen_codes = {q.metric_code for q in bp.questions if q.metric_code}
            for i, t in enumerate(tailored):
                # Don't duplicate a canonical metric already covered by the seed.
                if t.get("metric_code") and t["metric_code"] in seen_codes:
                    continue
                bp.questions.append(BlueprintQuestion(
                    local_id=f"ai-{i+1}",
                    metric_code=t.get("metric_code"),
                    pillar=t.get("pillar", "environmental"),
                    category=t.get("category", ""),
                    question_text=t["question_text"],
                    help_text=t.get("help_text", ""),
                    answer_modes=t.get("answer_modes") or ["value", "text"],
                    requirement=t.get("requirement", "optional"),
                    grounding_citation=t.get("grounding_citation"),
                    bank_relevance=t.get("bank_relevance", ""),
                    source="ai_added",
                    status="pending",
                ))
            if tailored:
                bp.generated_by = "ai"
        except Exception:
            pass  # AI is additive; canonical seed still stands

    bp.status = "pending_review"
    if existing:
        await bp.save_with_timestamp()
    else:
        await bp.insert()
    return bp


async def get_active_questions(workspace_id: str) -> Tuple[List[Dict[str, Any]], bool]:
    """
    Returns (questions, locked).
      * Approved blueprint  → its non-rejected questions, locked=False.
      * Blueprint awaiting review → ([], locked=True).
      * No blueprint at all (legacy workspace) → config default questions, locked=False.
      * Any error / no DB → config default questions, locked=False (safe fallback).
    """
    try:
        bp = await get_blueprint(workspace_id)
    except Exception:
        bp = None
        return (config_service.get("interview.default_blueprint").get("questions", []), False)

    if bp is None:
        return (config_service.get("interview.default_blueprint").get("questions", []), False)
    if bp.status != "approved":
        return ([], True)
    qs = [question_to_dict(q) for q in bp.questions if q.status != "rejected"]
    return (qs, False)


# ── Audit-officer curation ───────────────────────────────────────

async def list_pending() -> List[InterviewBlueprint]:
    """Cross-tenant queue of blueprints awaiting officer review."""
    return await InterviewBlueprint.find(
        InterviewBlueprint.status == "pending_review"
    ).sort("+created_at").to_list()


def _find_q(bp: InterviewBlueprint, local_id: str) -> Optional[BlueprintQuestion]:
    return next((q for q in bp.questions if q.local_id == local_id), None)


async def edit_question(blueprint_id: str, local_id: str, patch: Dict[str, Any],
                        reason: str, actor_id: str) -> InterviewBlueprint:
    from app.core.errors import AppError, ErrorCode
    from app.services import audit_service

    bp = await InterviewBlueprint.get(blueprint_id)
    if not bp:
        raise AppError(ErrorCode.NOT_FOUND, "Blueprint not found")
    q = _find_q(bp, local_id)
    if not q:
        raise AppError(ErrorCode.NOT_FOUND, "Question not found")

    editable = {"question_text", "help_text", "pillar", "category", "metric_code",
                "requirement", "answer_modes", "bank_relevance", "value_schema"}
    changes = {}
    for k, v in patch.items():
        if k in editable and getattr(q, k, None) != v:
            changes[k] = {"from": getattr(q, k, None), "to": v}
            setattr(q, k, v)
    q.edit_history.append({"actor_id": actor_id, "action": "edit", "reason": reason,
                           "ts": _now(), "changes": changes})
    await bp.save_with_timestamp()
    await audit_service.emit(
        event_type="BLUEPRINT_QUESTION_EDITED", actor_user_id=actor_id,
        company_id=bp.company_id, workspace_id=bp.workspace_id,
        entity_table="interview_blueprints", entity_id=bp.id,
        payload={"local_id": local_id, "reason": reason, "changes": changes},
    )
    return bp


async def delete_question(blueprint_id: str, local_id: str, reason: str, actor_id: str) -> InterviewBlueprint:
    from app.core.errors import AppError, ErrorCode
    from app.services import audit_service

    bp = await InterviewBlueprint.get(blueprint_id)
    if not bp:
        raise AppError(ErrorCode.NOT_FOUND, "Blueprint not found")
    q = _find_q(bp, local_id)
    if not q:
        raise AppError(ErrorCode.NOT_FOUND, "Question not found")
    q.status = "rejected"
    q.edit_history.append({"actor_id": actor_id, "action": "delete", "reason": reason, "ts": _now()})
    await bp.save_with_timestamp()
    await audit_service.emit(
        event_type="BLUEPRINT_QUESTION_DELETED", actor_user_id=actor_id,
        company_id=bp.company_id, workspace_id=bp.workspace_id,
        entity_table="interview_blueprints", entity_id=bp.id,
        payload={"local_id": local_id, "reason": reason},
    )
    return bp


async def approve_blueprint(blueprint_id: str, actor_id: str) -> InterviewBlueprint:
    from app.core.errors import AppError, ErrorCode
    from app.services import audit_service

    bp = await InterviewBlueprint.get(blueprint_id)
    if not bp:
        raise AppError(ErrorCode.NOT_FOUND, "Blueprint not found")
    for q in bp.questions:
        if q.status == "pending":
            q.status = "approved"
    bp.status = "approved"
    bp.approved_by = actor_id
    bp.approved_at = _now()
    await bp.save_with_timestamp()
    await audit_service.emit(
        event_type="BLUEPRINT_APPROVED", actor_user_id=actor_id,
        company_id=bp.company_id, workspace_id=bp.workspace_id,
        entity_table="interview_blueprints", entity_id=bp.id,
        payload={"question_count": len([q for q in bp.questions if q.status != 'rejected'])},
    )
    return bp
