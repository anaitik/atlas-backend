"""
Bank access service — creates and validates bank portal access tokens.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe
from typing import Any, Dict, List, Optional

from app.models.bank_access import BankAccess
from app.models.metric import Metric
from app.models.workspace import Workspace
from app.models.company import Company
from app.models.report import Report
from app.services import interview_service


async def create_bank_access(
    workspace_id: str,
    company_id: str,
    created_by_id: str,
    institution_name: str,
    allowed_pillars: List[str],
    allow_document_access: bool,
    expires_days: Optional[int],
) -> BankAccess:
    token = token_urlsafe(32)
    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=expires_days)
        if expires_days else None
    )
    access = BankAccess(
        workspace_id=workspace_id,
        company_id=company_id,
        institution_name=institution_name,
        created_by_id=created_by_id,
        allowed_pillars=allowed_pillars,
        allow_document_access=allow_document_access,
        access_token=token,
        expires_at=expires_at,
    )
    await access.insert()
    return access


async def list_bank_access(workspace_id: str) -> List[BankAccess]:
    return await BankAccess.find(
        BankAccess.workspace_id == workspace_id,
        BankAccess.is_active == True,
    ).to_list()


async def revoke_bank_access(access_id: str, workspace_id: str) -> bool:
    access = await BankAccess.find_one(
        BankAccess.id == access_id,
        BankAccess.workspace_id == workspace_id,
    )
    if not access:
        return False
    access.is_active = False
    await access.save_with_timestamp()
    return True


async def get_bank_portfolio_batch(tokens: List[str]) -> List[Dict[str, Any]]:
    """Return portal summaries for multiple tokens — used by the bank portfolio dashboard."""
    results = []
    for token in tokens[:25]:  # hard cap to prevent abuse
        try:
            portal = await get_bank_portal(token)
            portal["_access_token"] = token  # preserve source token for frontend
            results.append(portal)
        except Exception:
            pass  # skip invalid / expired / revoked tokens
    return results


async def get_bank_portal(access_token: str) -> Dict[str, Any]:
    """
    Load and return all data for the public bank verification portal.
    Validates the token, increments usage counter, and assembles the payload.
    """
    from app.core.errors import AppError, ErrorCode

    access = await BankAccess.find_one(BankAccess.access_token == access_token)
    if not access or not access.is_active:
        raise AppError(ErrorCode.NOT_FOUND, "Invalid or revoked bank access link")

    if access.expires_at and access.expires_at < datetime.now(timezone.utc):
        raise AppError(ErrorCode.FORBIDDEN, "This bank access link has expired")

    # Record usage
    first_view = access.access_count == 0
    access.last_accessed_at = datetime.now(timezone.utc)
    access.access_count += 1
    await access.save_with_timestamp()

    workspace = await Workspace.get(access.workspace_id)
    company = await Company.find_one(Company.id == access.company_id)

    # Notify workspace owner on first bank view (fire-and-forget)
    if first_view:
        try:
            from app.services import notification_service
            ws_name = workspace.name if workspace else "your workspace"
            await notification_service.notify(
                recipient_user_id=access.created_by_id,
                event_type="BANK_PORTAL_VIEWED",
                title=f"{access.institution_name} viewed your ESG report",
                body=f"{access.institution_name} just accessed the ESG verification portal for {ws_name}.",
                resource_url=f"/w/{access.workspace_id}/bank-access",
            )
        except Exception:
            pass

    # Load approved metrics filtered to allowed pillars
    all_metrics = await Metric.find(
        Metric.workspace_id == access.workspace_id,
        {"pillar": {"$in": access.allowed_pillars}},
    ).to_list()
    approved_metrics = [m for m in all_metrics if m.status == "approved"]

    # Interview progress + unanswered questions
    progress = await interview_service.get_progress(access.workspace_id)
    all_questions, _locked = await interview_service.get_active_questions(access.workspace_id)

    # Re-score restricted to the pillars this institution was granted, so the
    # portal never leaks sub-scores or flags for pillars outside the grant.
    from app.services import esg_score_service
    scoped_score = esg_score_service.compute_score(
        workspace, progress.get("responses", []), all_questions,
        allowed_pillars=access.allowed_pillars,
    )
    approved_q_ids = {r.question_id for r in progress.get("responses", []) if r.status == "approved"}
    unanswered = [
        {
            "id": q["id"],
            "category": q["category"],
            "metric_name": q["metric_name"],
            "pillar": q["pillar"],
            "bank_relevance": q.get("bank_relevance", ""),
        }
        for q in all_questions
        if q["id"] not in approved_q_ids and q["pillar"] in access.allowed_pillars
    ]

    # Latest published report for blockchain proof
    report = await Report.find_one(
        Report.workspace_id == access.workspace_id,
        Report.status == "published",
        sort=[("created_at", -1)],
    )

    metrics_out = [
        {
            "metric_code": m.metric_code,
            "metric_name": m.name,
            "pillar": m.pillar,
            "value": m.value,
            "unit": m.unit,
            "status": m.status,
        }
        for m in approved_metrics
    ]

    return {
        "company_name": company.name if company else access.company_id,
        "workspace_name": workspace.name if workspace else access.workspace_id,
        "reporting_year": workspace.reporting_year if workspace else None,
        "nace_sector": workspace.nace_sector if workspace else None,
        "employee_count_range": workspace.employee_count_range if workspace else None,
        "turnover_range_eur": workspace.turnover_range_eur if workspace else None,
        "interview_completion_pct": progress["completion_pct"],
        "total_approved": progress["approved"],
        "total_questions": progress["total_questions"],
        "pillar_scores": {p: (s or 0) for p, s in scoped_score["pillar_performance"].items()},
        "overall_esg_score": scoped_score["performance_score"] or 0,
        "data_quality_score": scoped_score["data_trust_score"],
        "atlas_score": scoped_score,
        "metrics": metrics_out,
        "unanswered_questions": unanswered,
        "blockchain_verified": bool(report and report.blockchain_tx_id),
        "blockchain_tx_id": report.blockchain_tx_id if report else None,
        "report_id": str(report.id) if report else None,
        "sha256_hash": report.sha256_hash if report else None,
        "institution_name": access.institution_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "atlas_verified": True,
    }
