from typing import Annotated
from fastapi import APIRouter, BackgroundTasks, Depends
from app.core.errors import AppError, ErrorCode
from app.core.pagination import PaginationParams
from app.core.responses import SuccessResponse, PaginatedSuccessResponse, api_response, paginated_response
from app.dependencies.auth import require_admin, require_owner, require_role, TokenData
from app.models.company import Company
from app.models.workspace import Workspace
from app.schemas.company import (
    CompanyCreate, CompanyOut, CompanyListPage,
    CompanyProfileOut, CompanyProfileUpdate,
)
from app.schemas.workspace import ComplianceMapOut, WorkspaceCreate, WorkspaceOut, WorkspaceProfileUpdate
from app.services import tenant_service, company_profile_service, blueprint_service
from app.services.compliance_service import build_compliance_map

router = APIRouter()


async def _load_company_for_user(company_id: str, user: TokenData) -> Company:
    if user.role != "system_admin" and user.company_id != company_id:
        raise AppError(ErrorCode.FORBIDDEN, "Cross-tenant access denied")
    company = await Company.get(company_id)
    if not company:
        raise AppError(ErrorCode.NOT_FOUND, "Company not found")
    return company

# ── Companies ──────────────────────────────────────────────────
@router.post("", response_model=SuccessResponse[CompanyOut])
async def create_company(
    data: CompanyCreate,
    admin: Annotated[TokenData, Depends(require_admin)]
):
    company = await tenant_service.create_company(data, admin.user_id)
    return api_response(CompanyOut(**company.model_dump()))

@router.get("", response_model=CompanyListPage)
async def list_companies(
    _admin: Annotated[TokenData, Depends(require_admin)],
    pagination: Annotated[PaginationParams, Depends()]
):
    skip = pagination.skip
    limit = pagination.page_size
    total = await Company.count()
    items = await Company.find().sort("-created_at").skip(skip).limit(limit).to_list()
    
    return paginated_response(
        [CompanyOut(**i.model_dump()) for i in items],
        total, pagination.page, limit
    )

@router.get("/{company_id}", response_model=SuccessResponse[CompanyOut])
async def get_company(
    company_id: str,
    user: Annotated[TokenData, Depends(require_role("report_viewer"))]
):
    if user.role != "system_admin" and user.company_id != company_id:
        raise AppError(ErrorCode.FORBIDDEN, "Cross-tenant access denied")

    company = await Company.get(company_id)
    if not company:
        raise AppError(ErrorCode.NOT_FOUND, "Company not found")
        
    return api_response(CompanyOut(**company.model_dump()))

# ── Company general-info intake ────────────────────────────────
@router.get("/{company_id}/profile", response_model=SuccessResponse[CompanyProfileOut])
async def get_company_profile(
    company_id: str,
    user: Annotated[TokenData, Depends(require_role("report_viewer"))],
):
    company = await _load_company_for_user(company_id, user)
    complete, missing = company_profile_service.evaluate(company.profile_data or {})
    return api_response(CompanyProfileOut(
        company_id=company.id,
        sections=company_profile_service.get_field_sections(),
        profile_data=company.profile_data or {},
        profile_complete=complete,
        missing_required=missing,
    ))


@router.put("/{company_id}/profile", response_model=SuccessResponse[CompanyProfileOut])
async def update_company_profile(
    company_id: str,
    data: CompanyProfileUpdate,
    owner: Annotated[TokenData, Depends(require_owner)],
):
    company = await _load_company_for_user(company_id, owner)
    company.profile_data = {**(company.profile_data or {}), **data.profile_data}
    complete, missing = company_profile_service.evaluate(company.profile_data)
    company.profile_complete = complete
    await company.save_with_timestamp()
    return api_response(CompanyProfileOut(
        company_id=company.id,
        sections=company_profile_service.get_field_sections(),
        profile_data=company.profile_data,
        profile_complete=complete,
        missing_required=missing,
    ))


# ── Workspaces ─────────────────────────────────────────────────
@router.post("/{company_id}/workspaces", response_model=SuccessResponse[WorkspaceOut])
async def create_workspace(
    company_id: str,
    data: WorkspaceCreate,
    owner: Annotated[TokenData, Depends(require_owner)],
    background: BackgroundTasks,
):
    company = await _load_company_for_user(company_id, owner)

    # Gate: mandatory company general-info must be complete first.
    complete, missing = company_profile_service.evaluate(company.profile_data or {})
    if not complete:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "Complete the required company information before creating a workspace.",
            details=[{"missing_required": missing}],
        )

    ws = await tenant_service.create_workspace(company_id, data, owner.user_id)

    # Seed the blueprint SYNCHRONOUSLY (canonical, no LLM) so a pending_review
    # blueprint always exists at t=0 — this is what makes the full gate hold (no
    # window where the interview is reachable before review). The slower AI
    # augmentation then runs in the background and updates the same blueprint.
    try:
        await blueprint_service.create_for_workspace(ws.id, company_id, use_ai=False)
    except Exception:
        pass
    background.add_task(blueprint_service.create_for_workspace, ws.id, company_id, True)

    return api_response(WorkspaceOut(**ws.model_dump()))

@router.get("/{company_id}/workspaces", response_model=SuccessResponse[list[WorkspaceOut]])
async def list_workspaces(
    company_id: str,
    user: Annotated[TokenData, Depends(require_role("report_viewer"))]
):
    if user.role != "system_admin" and user.company_id != company_id:
        raise AppError(ErrorCode.FORBIDDEN, "Cross-tenant access denied")

    # Short-cutting pagination as workspaces per company are typically very low.
    items = await Workspace.find({"company_id": company_id}).sort("-created_at").to_list()
    return api_response([WorkspaceOut(**i.model_dump()) for i in items])


@router.patch("/{company_id}/workspaces/{workspace_id}/profile", response_model=SuccessResponse[WorkspaceOut])
async def update_workspace_profile(
    company_id: str,
    workspace_id: str,
    data: WorkspaceProfileUpdate,
    owner: Annotated[TokenData, Depends(require_owner)],
):
    if owner.role != "system_admin" and owner.company_id != company_id:
        raise AppError(ErrorCode.FORBIDDEN, "Cross-tenant access denied")

    ws = await Workspace.get(workspace_id)
    if not ws or ws.company_id != company_id:
        raise AppError(ErrorCode.NOT_FOUND, "Workspace not found")

    update_data = data.model_dump(exclude_none=True)
    for field, value in update_data.items():
        setattr(ws, field, value)
    await ws.save_with_timestamp()
    return api_response(WorkspaceOut(**ws.model_dump()))


@router.get("/{company_id}/workspaces/{workspace_id}/compliance-map", response_model=SuccessResponse[ComplianceMapOut])
async def get_compliance_map(
    company_id: str,
    workspace_id: str,
    user: Annotated[TokenData, Depends(require_role("report_viewer"))],
):
    if user.role != "system_admin" and user.company_id != company_id:
        raise AppError(ErrorCode.FORBIDDEN, "Cross-tenant access denied")

    ws = await Workspace.get(workspace_id)
    if not ws or ws.company_id != company_id:
        raise AppError(ErrorCode.NOT_FOUND, "Workspace not found")

    result = await build_compliance_map(ws)
    return api_response(ComplianceMapOut(**result))


@router.delete("/{company_id}/workspaces/{workspace_id}", response_model=SuccessResponse[dict])
async def delete_workspace(
    company_id: str,
    workspace_id: str,
    owner: Annotated[TokenData, Depends(require_owner)]
):
    if owner.role != "system_admin" and owner.company_id != company_id:
        raise AppError(ErrorCode.FORBIDDEN, "Cross-tenant access denied")

    result = await tenant_service.delete_workspace(company_id, workspace_id, owner.user_id)
    return api_response(result)
