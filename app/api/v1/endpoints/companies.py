from typing import Annotated
from fastapi import APIRouter, Depends
from app.core.errors import AppError, ErrorCode
from app.core.pagination import PaginationParams
from app.core.responses import SuccessResponse, PaginatedSuccessResponse, api_response, paginated_response
from app.dependencies.auth import require_admin, require_owner, require_role, TokenData
from app.models.company import Company
from app.models.workspace import Workspace
from app.schemas.company import CompanyCreate, CompanyOut, CompanyListPage
from app.schemas.workspace import WorkspaceCreate, WorkspaceOut
from app.services import tenant_service

router = APIRouter()

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

# ── Workspaces ─────────────────────────────────────────────────
@router.post("/{company_id}/workspaces", response_model=SuccessResponse[WorkspaceOut])
async def create_workspace(
    company_id: str,
    data: WorkspaceCreate,
    owner: Annotated[TokenData, Depends(require_owner)]
):
    if owner.role != "system_admin" and owner.company_id != company_id:
        raise AppError(ErrorCode.FORBIDDEN, "Cross-tenant access denied")

    ws = await tenant_service.create_workspace(company_id, data, owner.user_id)
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
