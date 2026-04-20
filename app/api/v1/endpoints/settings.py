from typing import Annotated, List, Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.dependencies.auth import get_current_user, require_role, require_manager, require_owner
from app.core.responses import api_response, SuccessResponse
from app.schemas.auth import TokenData
from app.schemas.settings import WorkspaceSettings, WorkspaceSettingsUpdate
from app.models.metric_definition import MetricDefinition
from app.models.emission_factor import EmissionFactor
from app.core.errors import AppError, ErrorCode

router = APIRouter()

class MetricDefinitionOut(BaseModel):
    key: str
    description: str
    pillar: str
    unit: str
    suggested_tool: str
    tags: List[str]
    company_id: Optional[str] = None

class EmissionFactorOut(BaseModel):
    key: str
    value: float
    unit: str
    source: str
    scope: int
    region: Optional[str] = None
    year: Optional[int] = None
    unit_basis: Optional[str] = None
    version: Optional[str] = None
    status: Optional[str] = None
    company_id: Optional[str] = None

class MetricDefinitionCreate(BaseModel):
    key: str
    description: str
    pillar: str = "environmental"
    unit: str
    suggested_tool: str = "direct_read"
    tags: List[str] = []

class EmissionFactorCreate(BaseModel):
    key: str
    value: float
    unit: str
    source: str
    scope: int
    region: Optional[str] = None
    year: Optional[int] = None
    unit_basis: Optional[str] = None
    version: Optional[str] = "custom"
    status: Optional[str] = "active"

@router.get("/", response_model=SuccessResponse[WorkspaceSettings])
async def get_settings(
    user: Annotated[TokenData, Depends(get_current_user)],
):
    """
    Get workspace settings.
    """
    # Placeholder: In a real app, this would fetch from DB for user.company_id
    return api_response(WorkspaceSettings())

@router.patch("/", response_model=SuccessResponse[WorkspaceSettings])
async def update_settings(
    settings_in: WorkspaceSettingsUpdate,
    user: Annotated[TokenData, Depends(require_role("owner"))],
):
    """
    Update workspace settings.
    """
    # Placeholder: In a real app, this would update the DB for user.company_id
    settings = WorkspaceSettings(**settings_in.model_dump(exclude_unset=True))
    return api_response(settings)

@router.get("/metrics", response_model=SuccessResponse[List[MetricDefinitionOut]])
async def list_metric_definitions(
    company_id: str,
    manager: Annotated[TokenData, Depends(require_manager)]
):
    if manager.company_id and manager.company_id != company_id:
        raise AppError(ErrorCode.FORBIDDEN, "Cross-tenant access denied")
        
    items = await MetricDefinition.find(
        {"$or": [{"company_id": None}, {"company_id": company_id}]}
    ).to_list()
    return api_response([MetricDefinitionOut(**i.model_dump()) for i in items])

@router.post("/metrics", response_model=SuccessResponse[MetricDefinitionOut])
async def create_metric_definition(
    company_id: str,
    data: MetricDefinitionCreate,
    manager: Annotated[TokenData, Depends(require_manager)]
):
    if manager.company_id and manager.company_id != company_id:
        raise AppError(ErrorCode.FORBIDDEN, "Cross-tenant access denied")
        
    existing = await MetricDefinition.find_one(
        {"key": data.key, "$or": [{"company_id": None}, {"company_id": company_id}]}
    )
    if existing:
        raise AppError(ErrorCode.VALIDATION_ERROR, f"Metric key '{data.key}' already exists.")
        
    metric = MetricDefinition(
        company_id=company_id,
        **data.model_dump()
    )
    await metric.save()
    return api_response(MetricDefinitionOut(**metric.model_dump()))

@router.delete("/metrics/{key}", response_model=SuccessResponse[dict])
async def delete_metric_definition(
    company_id: str,
    key: str,
    manager: Annotated[TokenData, Depends(require_manager)]
):
    if manager.company_id and manager.company_id != company_id:
        raise AppError(ErrorCode.FORBIDDEN, "Cross-tenant access denied")
        
    metric = await MetricDefinition.find_one({"key": key, "company_id": company_id})
    if not metric:
        raise AppError(ErrorCode.NOT_FOUND, "Custom metric not found or you cannot delete a global metric.")
        
    await metric.delete()
    return api_response({"deleted": True})

@router.get("/factors", response_model=SuccessResponse[List[EmissionFactorOut]])
async def list_emission_factors(
    company_id: str,
    manager: Annotated[TokenData, Depends(require_manager)]
):
    if manager.company_id and manager.company_id != company_id:
        raise AppError(ErrorCode.FORBIDDEN, "Cross-tenant access denied")
        
    items = await EmissionFactor.find(
        {"$or": [{"company_id": None}, {"company_id": company_id}]}
    ).to_list()
    return api_response([EmissionFactorOut(**i.model_dump()) for i in items])

@router.post("/factors", response_model=SuccessResponse[EmissionFactorOut])
async def create_emission_factor(
    company_id: str,
    data: EmissionFactorCreate,
    manager: Annotated[TokenData, Depends(require_manager)]
):
    if manager.company_id and manager.company_id != company_id:
        raise AppError(ErrorCode.FORBIDDEN, "Cross-tenant access denied")
        
    existing = await EmissionFactor.find_one(
        {"key": data.key, "$or": [{"company_id": None}, {"company_id": company_id}]}
    )
    if existing:
        if existing.company_id is None:
            raise AppError(ErrorCode.VALIDATION_ERROR, f"Cannot overwrite global factor '{data.key}'. Override using a different key.")
        else:
            existing.value = data.value
            existing.unit = data.unit
            existing.source = data.source
            existing.scope = data.scope
            existing.region = data.region
            existing.year = data.year
            existing.unit_basis = data.unit_basis
            existing.version = data.version or existing.version
            existing.status = data.status or existing.status
            await existing.save()
            return api_response(EmissionFactorOut(**existing.model_dump()))
            
    factor = EmissionFactor(
        company_id=company_id,
        **data.model_dump()
    )
    await factor.save()
    return api_response(EmissionFactorOut(**factor.model_dump()))

@router.delete("/factors/{key}", response_model=SuccessResponse[dict])
async def delete_emission_factor(
    company_id: str,
    key: str,
    manager: Annotated[TokenData, Depends(require_manager)]
):
    if manager.company_id and manager.company_id != company_id:
        raise AppError(ErrorCode.FORBIDDEN, "Cross-tenant access denied")
        
    factor = await EmissionFactor.find_one({"key": key, "company_id": company_id})
    if not factor:
        raise AppError(ErrorCode.NOT_FOUND, "Custom factor not found or you cannot delete a global factor.")
        
    await factor.delete()
    return api_response({"deleted": True})
