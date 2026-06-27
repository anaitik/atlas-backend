"""
Bank verification portal endpoints.
Private: manage access tokens (authenticated).
Public: bank views MSME ESG data via token (no auth required).
"""

from datetime import datetime, timedelta, timezone
from typing import Annotated, List

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.responses import SuccessResponse, api_response
from app.core.errors import AppError, ErrorCode
from app.core.rate_limit import is_allowed
from app.dependencies.auth import require_manager, TokenData
from app.schemas.interview import (
    AtlasScoreOut,
    BankAccessCreate,
    BankAccessOut,
    BankMetricOut,
    BankPortalOut,
    RenewBankAccessRequest,
    UnansweredQuestionOut,
)
from app.services import bank_service

router = APIRouter()

Manager = Annotated[TokenData, Depends(require_manager)]


def _access_out(access, base_url: str = "") -> BankAccessOut:
    return BankAccessOut(
        id=str(access.id),
        institution_name=access.institution_name,
        access_token=access.access_token,
        access_url=f"{base_url}/verify/{access.access_token}",
        allowed_pillars=access.allowed_pillars,
        allow_document_access=access.allow_document_access,
        expires_at=access.expires_at,
        is_active=access.is_active,
        access_count=access.access_count,
        created_at=access.created_at,
    )


def _portal_out(d: dict) -> BankPortalOut:
    return BankPortalOut(
        company_name=d["company_name"],
        workspace_name=d["workspace_name"],
        reporting_year=d.get("reporting_year"),
        nace_sector=d.get("nace_sector"),
        employee_count_range=d.get("employee_count_range"),
        turnover_range_eur=d.get("turnover_range_eur"),
        interview_completion_pct=d["interview_completion_pct"],
        total_approved=d["total_approved"],
        total_questions=d["total_questions"],
        pillar_scores=d.get("pillar_scores", {}),
        overall_esg_score=d.get("overall_esg_score", 0),
        data_quality_score=d.get("data_quality_score", 0),
        atlas_score=AtlasScoreOut(**d["atlas_score"]) if d.get("atlas_score") else None,
        metrics=[BankMetricOut(**m) for m in d["metrics"]],
        unanswered_questions=[UnansweredQuestionOut(**q) for q in d.get("unanswered_questions", [])],
        blockchain_verified=d["blockchain_verified"],
        blockchain_tx_id=d.get("blockchain_tx_id"),
        report_id=d.get("report_id"),
        sha256_hash=d.get("sha256_hash"),
        institution_name=d["institution_name"],
        generated_at=d["generated_at"],
        atlas_verified=True,
    )


# ── Authenticated: token management ─────────────────────────────

@router.post(
    "/workspace/{workspace_id}/access",
    response_model=SuccessResponse[BankAccessOut],
    status_code=201,
)
async def create_bank_access(
    workspace_id: str,
    body: BankAccessCreate,
    actor: Manager,
):
    """Generate a secure bank access link for a workspace."""
    access = await bank_service.create_bank_access(
        workspace_id=workspace_id,
        company_id=actor.company_id or "",
        created_by_id=actor.user_id,
        institution_name=body.institution_name,
        allowed_pillars=body.allowed_pillars,
        allow_document_access=body.allow_document_access,
        expires_days=body.expires_days,
    )
    return api_response(_access_out(access))


@router.get(
    "/workspace/{workspace_id}/access",
    response_model=SuccessResponse[List[BankAccessOut]],
)
async def list_bank_access(workspace_id: str, actor: Manager):
    """List all active bank access tokens for a workspace."""
    tokens = await bank_service.list_bank_access(workspace_id)
    return api_response([_access_out(t) for t in tokens])


@router.patch(
    "/workspace/{workspace_id}/access/{access_id}/renew",
    response_model=SuccessResponse[BankAccessOut],
)
async def renew_bank_access(
    workspace_id: str,
    access_id: str,
    body: RenewBankAccessRequest,
    actor: Manager,
):
    """Renew or reactivate an expired bank access token."""
    from app.models.bank_access import BankAccess
    access = await BankAccess.find_one(
        BankAccess.id == access_id,
        BankAccess.workspace_id == workspace_id,
    )
    if not access:
        raise AppError(ErrorCode.NOT_FOUND, "Bank access token not found")
    access.expires_at = datetime.now(timezone.utc) + timedelta(days=body.expires_days)
    access.is_active = True
    await access.save_with_timestamp()
    return api_response(_access_out(access))


@router.delete(
    "/workspace/{workspace_id}/access/{access_id}",
    response_model=SuccessResponse[dict],
)
async def revoke_bank_access(
    workspace_id: str,
    access_id: str,
    actor: Manager,
):
    """Revoke a bank access token immediately."""
    ok = await bank_service.revoke_bank_access(access_id, workspace_id)
    if not ok:
        raise AppError(ErrorCode.NOT_FOUND, "Bank access token not found")
    return api_response({"revoked": True})


# ── Public: bank portal (rate-limited) ──────────────────────────

def _rate_check(request: Request, max_calls: int = 30, window: int = 60) -> None:
    ip = request.client.host if request.client else "unknown"
    allowed, retry_after = is_allowed(f"bank:{ip}", max_calls, window)
    if not allowed:
        raise AppError(
            ErrorCode.FORBIDDEN,
            f"Rate limit exceeded. Retry in {retry_after}s.",
        )


class PortfolioBatchRequest(BaseModel):
    tokens: List[str]


@router.post(
    "/public/portfolio/batch",
    response_model=SuccessResponse[List[BankPortalOut]],
)
async def portfolio_batch(request: Request, body: PortfolioBatchRequest):
    """
    Public endpoint — no authentication required.
    Accepts up to 25 access tokens and returns all valid portals.
    Rate limited: 30 requests / 60 seconds per IP.
    """
    _rate_check(request, max_calls=30, window=60)
    results = await bank_service.get_bank_portfolio_batch(body.tokens)
    return api_response([_portal_out(d) for d in results])


@router.get(
    "/public/portal/{access_token}",
    response_model=SuccessResponse[BankPortalOut],
)
async def bank_portal(request: Request, access_token: str):
    """
    Public endpoint — no authentication required.
    Banks call this to view an MSME's verified ESG data.
    Rate limited: 60 requests / 60 seconds per IP.
    """
    _rate_check(request, max_calls=60, window=60)
    data = await bank_service.get_bank_portal(access_token)
    return api_response(_portal_out(data))
