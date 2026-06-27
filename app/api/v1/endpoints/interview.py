"""
VSME guided interview endpoints — data collection for MSME bank reporting.
"""

from typing import Annotated, List

from fastapi import APIRouter, Depends

from app.core.responses import SuccessResponse, api_response
from app.core.errors import AppError, ErrorCode
from app.dependencies.auth import require_manager, require_role, TokenData
from app.schemas.interview import (
    ApproveAnswerRequest,
    InterpretTextRequest,
    InterpretedValueOut,
    InterviewAnswerSubmit,
    InterviewProgressOut,
    InterviewQuestionOut,
    InterviewResponseOut,
    ValueSchemaOut,
)
from app.services import interview_service

router = APIRouter()

Reviewer = Annotated[TokenData, Depends(require_role("data_reviewer"))]
Manager = Annotated[TokenData, Depends(require_manager)]


def _response_out(r) -> InterviewResponseOut:
    return InterviewResponseOut(
        id=str(r.id),
        question_id=r.question_id,
        answer_mode=r.answer_mode,
        document_id=r.document_id,
        raw_value=r.raw_value,
        raw_unit=r.raw_unit,
        raw_text=r.raw_text,
        interpreted_metric_code=r.interpreted_metric_code,
        interpreted_value=r.interpreted_value,
        interpreted_unit=r.interpreted_unit,
        interpretation_confidence=r.interpretation_confidence,
        interpretation_reasoning=r.interpretation_reasoning,
        status=r.status,
        approved_metric_id=r.approved_metric_id,
        autofill_source=getattr(r, "autofill_source", None),
        override_reason=getattr(r, "override_reason", None),
    )


@router.get(
    "/workspace/{workspace_id}/questions",
    response_model=SuccessResponse[List[InterviewQuestionOut]],
)
async def get_questions(workspace_id: str, actor: Reviewer):
    questions, _locked = await interview_service.get_active_questions(workspace_id)
    return api_response([
        InterviewQuestionOut(
            id=q["id"],
            question_number=q.get("question_number", 0),
            disclosure_id=q.get("disclosure_id", ""),
            pillar=q.get("pillar", "environmental"),
            category=q.get("category", ""),
            question_text=q["question_text"],
            help_text=q.get("help_text", ""),
            answer_modes=q.get("answer_modes", ["value", "text"]),
            metric_code=q.get("metric_code") or "",
            metric_name=q.get("metric_name", ""),
            bank_relevance=q.get("bank_relevance", ""),
            value_schema=ValueSchemaOut(**q["value_schema"]) if q.get("value_schema") else None,
        )
        for q in questions
    ])


@router.get("/workspace/{workspace_id}/status", response_model=SuccessResponse[dict])
async def interview_status(workspace_id: str, actor: Reviewer):
    """Whether the tailored questionnaire is ready or still pending officer review."""
    questions, locked = await interview_service.get_active_questions(workspace_id)
    return api_response({
        "locked": locked,
        "question_count": len(questions),
        "message": "Your tailored questionnaire is being finalized by our review team."
        if locked else "Ready",
    })


@router.get(
    "/workspace/{workspace_id}/progress",
    response_model=SuccessResponse[InterviewProgressOut],
)
async def get_progress(workspace_id: str, actor: Reviewer):
    progress = await interview_service.get_progress(workspace_id)
    return api_response(InterviewProgressOut(
        workspace_id=workspace_id,
        total_questions=progress["total_questions"],
        answered=progress["answered"],
        approved=progress["approved"],
        skipped=progress["skipped"],
        completion_pct=progress["completion_pct"],
        pillar_scores=progress.get("pillar_scores", {}),
        overall_esg_score=progress.get("overall_esg_score", 0),
        data_quality_score=progress.get("data_quality_score", 0),
        atlas_score=progress.get("atlas_score"),
        responses=[_response_out(r) for r in progress["responses"]],
    ))


@router.post(
    "/workspace/{workspace_id}/questions/{question_id}/answer",
    response_model=SuccessResponse[InterviewResponseOut],
)
async def submit_answer(
    workspace_id: str,
    question_id: str,
    body: InterviewAnswerSubmit,
    actor: Manager,
):
    resp = await interview_service.submit_answer(
        company_id=actor.company_id or "",
        workspace_id=workspace_id,
        question_id=question_id,
        answer_mode=body.answer_mode,
        document_id=body.document_id,
        raw_value=body.raw_value,
        raw_unit=body.raw_unit,
        raw_text=body.raw_text,
        skipped_reason=body.skipped_reason,
    )
    return api_response(_response_out(resp))


@router.post(
    "/workspace/{workspace_id}/questions/{question_id}/interpret",
    response_model=SuccessResponse[InterpretedValueOut],
)
async def interpret_answer(
    workspace_id: str,
    question_id: str,
    body: InterpretTextRequest,
    actor: Manager,
):
    interpretation = await interview_service.interpret_text(workspace_id, question_id, body.raw_text)
    await interview_service.store_interpretation(workspace_id, question_id, interpretation)
    return api_response(InterpretedValueOut(
        value=interpretation["value"],
        unit=interpretation.get("unit"),
        confidence=interpretation["confidence"],
        reasoning=interpretation["reasoning"],
    ))


@router.post(
    "/workspace/{workspace_id}/questions/{question_id}/approve",
    response_model=SuccessResponse[InterviewResponseOut],
)
async def approve_answer(
    workspace_id: str,
    question_id: str,
    body: ApproveAnswerRequest,
    actor: Manager,
):
    resp = await interview_service.approve_answer(
        workspace_id=workspace_id,
        question_id=question_id,
        company_id=actor.company_id or "",
        override_value=body.override_value,
        override_unit=body.override_unit,
        override_reason=body.override_reason,
    )
    if not resp:
        raise AppError(ErrorCode.NOT_FOUND, "Interview response not found")
    return api_response(_response_out(resp))


@router.post(
    "/workspace/{workspace_id}/prefill",
    response_model=SuccessResponse[dict],
)
async def prefill_from_metrics(workspace_id: str, actor: Manager):
    """Auto-fill interview answers from existing evidence (this workspace's approved
    metrics, uploaded-document extractions, and prior reporting periods) with provenance."""
    from app.services import answer_resolver
    count = await answer_resolver.autofill(workspace_id, actor.company_id or "")
    return api_response({"prefilled_count": count})
