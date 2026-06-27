"""
Audit-officer endpoints — the ONLY surface the `system_audit_officer` role can
reach. Cross-tenant queue of interview blueprints awaiting review; edit/delete
questions (reason required) and approve the blueprint (unlocks the MSME interview).

The officer sees question text/metadata and company name/sector for context only —
no metrics, documents, reports or financials.
"""

from typing import Annotated, List

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.errors import AppError, ErrorCode
from app.core.responses import SuccessResponse, api_response
from app.dependencies.auth import require_audit_officer, TokenData
from app.models.company import Company
from app.models.interview_blueprint import InterviewBlueprint
from app.services import blueprint_service

router = APIRouter()

Officer = Annotated[TokenData, Depends(require_audit_officer)]


class QuestionEdit(BaseModel):
    reason: str = Field(..., min_length=3)
    patch: dict


class QuestionDelete(BaseModel):
    reason: str = Field(..., min_length=3)


def _question_out(q) -> dict:
    return {
        "local_id": q.local_id,
        "metric_code": q.metric_code,
        "metric_name": q.metric_name,
        "pillar": q.pillar,
        "category": q.category,
        "question_text": q.question_text,
        "help_text": q.help_text,
        "answer_modes": q.answer_modes,
        "requirement": q.requirement,
        "grounding_citation": q.grounding_citation,
        "bank_relevance": q.bank_relevance,
        "source": q.source,
        "status": q.status,
        "edit_history": q.edit_history,
    }


async def _blueprint_out(bp: InterviewBlueprint, include_questions: bool = True) -> dict:
    company = await Company.get(bp.company_id)
    profile = (company.profile_data if company else {}) or {}
    active = [q for q in bp.questions if q.status != "rejected"]
    out = {
        "id": bp.id,
        "workspace_id": bp.workspace_id,
        "company_name": company.name if company else "—",
        "sector": profile.get("nace_sector"),
        "status": bp.status,
        "generated_by": bp.generated_by,
        "grounding_refs": bp.grounding_refs,
        "question_count": len(active),
        "ai_added_count": len([q for q in active if q.source == "ai_added"]),
        "created_at": bp.created_at,
    }
    if include_questions:
        out["questions"] = [_question_out(q) for q in bp.questions]
    return out


@router.get("/blueprints", response_model=SuccessResponse[List[dict]])
async def list_pending_blueprints(_: Officer):
    """Cross-tenant queue of blueprints awaiting review."""
    pending = await blueprint_service.list_pending()
    return api_response([await _blueprint_out(bp, include_questions=False) for bp in pending])


@router.get("/blueprints/{blueprint_id}", response_model=SuccessResponse[dict])
async def get_blueprint_detail(blueprint_id: str, _: Officer):
    bp = await InterviewBlueprint.get(blueprint_id)
    if not bp:
        raise AppError(ErrorCode.NOT_FOUND, "Blueprint not found")
    return api_response(await _blueprint_out(bp))


@router.patch("/blueprints/{blueprint_id}/questions/{local_id}", response_model=SuccessResponse[dict])
async def edit_question(blueprint_id: str, local_id: str, body: QuestionEdit, officer: Officer):
    bp = await blueprint_service.edit_question(blueprint_id, local_id, body.patch, body.reason, officer.user_id)
    return api_response(await _blueprint_out(bp))


@router.post("/blueprints/{blueprint_id}/questions/{local_id}/delete", response_model=SuccessResponse[dict])
async def delete_question(blueprint_id: str, local_id: str, body: QuestionDelete, officer: Officer):
    bp = await blueprint_service.delete_question(blueprint_id, local_id, body.reason, officer.user_id)
    return api_response(await _blueprint_out(bp))


@router.post("/blueprints/{blueprint_id}/approve", response_model=SuccessResponse[dict])
async def approve_blueprint(blueprint_id: str, officer: Officer):
    bp = await blueprint_service.approve_blueprint(blueprint_id, officer.user_id)
    return api_response(await _blueprint_out(bp))
