from datetime import datetime, timezone
from typing import Annotated
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from app.core.errors import AppError, ErrorCode
from app.core.responses import SuccessResponse, api_response
from app.dependencies.auth import require_admin
from app.schemas.auth import TokenData
from app.models.bank_access import BankAccess
from app.models.company import Company
from app.models.user import User
from app.models.workspace import Workspace
from app.models.audit_event import AuditEvent
from app.services import config_service

router = APIRouter()

Admin = Annotated[TokenData, Depends(require_admin)]


class CompanyStatusUpdate(BaseModel):
    status: str  # "active" | "suspended"


class ConfigUpdate(BaseModel):
    values: dict  # key -> value pairs to upsert within a namespace


# ── Runtime config (admin-editable policy/business config) ───────

@router.get("/config", response_model=SuccessResponse[dict])
async def get_all_config(_: Admin):
    """Return every runtime-config namespace (defaults overlaid with overrides)."""
    return api_response(config_service.all_namespaces())


@router.get("/config/{namespace}", response_model=SuccessResponse[dict])
async def get_config_namespace(namespace: str, _: Admin):
    return api_response(config_service.get(namespace))


@router.put("/config/{namespace}", response_model=SuccessResponse[dict])
async def update_config_namespace(namespace: str, body: ConfigUpdate, actor: Admin):
    """Upsert one or more keys within a config namespace."""
    if not body.values:
        raise AppError(ErrorCode.VALIDATION_ERROR, "No config values provided")
    await config_service.set_namespace(namespace, body.values, updated_by=actor.user_id)
    return api_response(config_service.get(namespace))


@router.get("/stats", response_model=SuccessResponse[dict])
async def get_system_stats(_: Annotated[bool, Depends(require_admin)]):
    tenant_count = await Company.count()
    active_companies = await Company.find({"status": "active"}).count()
    user_count = await User.count()
    pending_users = await User.find({"status": "pending"}).count()
    workspace_count = await Workspace.count()
    active_bank_tokens = await BankAccess.find({"is_active": True}).count()

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    events_today = await AuditEvent.find({"created_at": {"$gte": today_start}}).count()

    return api_response({
        "tenant_count": tenant_count,
        "active_companies": active_companies,
        "active_user_count": user_count,
        "pending_user_count": pending_users,
        "workspace_count": workspace_count,
        "active_bank_token_count": active_bank_tokens,
        "events_today": events_today,
    })


@router.get("/audit-logs", response_model=SuccessResponse[list])
async def get_audit_logs(
    _: Annotated[bool, Depends(require_admin)],
    limit: int = Query(50, le=200),
    skip: int = Query(0),
):
    logs = await AuditEvent.find_all().sort("-created_at").skip(skip).limit(limit).to_list()

    actor_ids = {log.actor_user_id for log in logs if log.actor_user_id}
    actors: dict[str, str] = {}
    if actor_ids:
        users = await User.find({"_id": {"$in": list(actor_ids)}}).to_list()
        actors = {u.id: u.full_name for u in users}

    result = []
    for log in logs:
        d = log.model_dump()
        d["actor_name"] = actors.get(log.actor_user_id) if log.actor_user_id else None
        result.append(d)

    return api_response(result)


@router.get("/company-summaries", response_model=SuccessResponse[list])
async def get_company_summaries(_: Annotated[bool, Depends(require_admin)]):
    companies = await Company.find_all().sort("-created_at").to_list()

    result = []
    for company in companies:
        workspace_count = await Workspace.find({"company_id": company.id}).count()
        user_count = await User.find({"company_id": company.id, "status": "active"}).count()
        result.append({
            **company.model_dump(),
            "workspace_count": workspace_count,
            "user_count": user_count,
        })

    return api_response(result)


@router.patch("/companies/{company_id}/status", response_model=SuccessResponse[dict])
async def update_company_status(
    company_id: str,
    data: CompanyStatusUpdate,
    _: Annotated[bool, Depends(require_admin)],
):
    if data.status not in ("active", "suspended"):
        raise AppError(ErrorCode.VALIDATION_ERROR, "Status must be 'active' or 'suspended'")

    company = await Company.get(company_id)
    if not company:
        raise AppError(ErrorCode.NOT_FOUND, "Company not found")

    company.status = data.status
    await company.save_with_timestamp()
    return api_response({"id": company.id, "status": company.status})
