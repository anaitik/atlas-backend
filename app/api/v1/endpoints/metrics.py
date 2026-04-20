from typing import Annotated, List
from fastapi import APIRouter, Depends, Query

from app.core.responses import SuccessResponse, api_response
from app.dependencies.auth import require_manager, require_role, TokenData
from app.models.metric import Metric
from app.schemas.metric import (
    MetricAgentRunRequest,
    MetricCreate,
    MetricDefinitionOut,
    MetricOut,
    MetricRecommendationOut,
    MetricReview,
    MetricSummaryOut,
)
from app.services import metric_agent_service, metric_service

router = APIRouter()

@router.post("", response_model=SuccessResponse[MetricOut])
async def create_metric(
    company_id: str,
    workspace_id: str,
    data: MetricCreate,
    manager: Annotated[TokenData, Depends(require_manager)]
):
    """(Usually called internally by the UI/Agent, but exposed via API for integrations)"""
    if manager.company_id and manager.company_id != company_id:
        from app.core.errors import AppError, ErrorCode
        raise AppError(ErrorCode.FORBIDDEN, "Cross-tenant access denied")

    res = await metric_service.compute_and_store_metric(company_id, workspace_id, data, manager.user_id)
    return api_response(MetricOut(**res.model_dump()))


@router.get("", response_model=SuccessResponse[List[MetricOut]])
async def list_metrics(
    company_id: str,
    workspace_id: str,
    manager: Annotated[TokenData, Depends(require_manager)],
    include_fallback: bool = Query(True, description="Deprecated: No longer triggers side-effects."),
):
    if manager.company_id and manager.company_id != company_id:
        from app.core.errors import AppError, ErrorCode
        raise AppError(ErrorCode.FORBIDDEN, "Cross-tenant access denied")
        
    items = await Metric.find({"company_id": company_id, "workspace_id": workspace_id}).to_list()
    return api_response([MetricOut(**i.model_dump()) for i in items])


@router.get("/summary", response_model=SuccessResponse[MetricSummaryOut])
async def metrics_summary(
    company_id: str,
    workspace_id: str,
    manager: Annotated[TokenData, Depends(require_manager)],
):
    if manager.company_id and manager.company_id != company_id:
        from app.core.errors import AppError, ErrorCode

        raise AppError(ErrorCode.FORBIDDEN, "Cross-tenant access denied")

    items = await Metric.find({"company_id": company_id, "workspace_id": workspace_id}).to_list()
    summary = metric_service.build_workspace_metric_summary(items, company_id, workspace_id)
    return api_response(MetricSummaryOut(**summary))


@router.post("/sync", response_model=SuccessResponse[List[MetricOut]])
async def sync_workspace_metrics(
    company_id: str,
    workspace_id: str,
    manager: Annotated[TokenData, Depends(require_manager)],
):
    if manager.company_id and manager.company_id != company_id:
        from app.core.errors import AppError, ErrorCode
        raise AppError(ErrorCode.FORBIDDEN, "Cross-tenant access denied")
        
    await metric_service.sync_workspace_metrics(
        company_id,
        workspace_id,
        manager.user_id,
        manager.company_id,
    )
    items = await Metric.find({"company_id": company_id, "workspace_id": workspace_id}).to_list()
    return api_response([MetricOut(**i.model_dump()) for i in items])


@router.get("/targets", response_model=SuccessResponse[List[MetricDefinitionOut]])
async def list_metric_targets(
    manager: Annotated[TokenData, Depends(require_manager)]
):
    items = metric_agent_service.list_metric_definitions(manager.company_id)
    return api_response([MetricDefinitionOut(**item) for item in items])


@router.get("/recommendations", response_model=SuccessResponse[MetricRecommendationOut])
async def recommend_metric_targets(
    company_id: str,
    workspace_id: str,
    manager: Annotated[TokenData, Depends(require_manager)]
):
    if manager.company_id and manager.company_id != company_id:
        from app.core.errors import AppError, ErrorCode
        raise AppError(ErrorCode.FORBIDDEN, "Cross-tenant access denied")

    recommendation = await metric_agent_service.recommend_metric_targets_for_workspace(
        company_id,
        workspace_id,
        manager.company_id,
    )
    return api_response(MetricRecommendationOut(**recommendation))


@router.post("/run-agent", response_model=SuccessResponse[List[MetricOut]])
async def run_metric_agent(
    company_id: str,
    workspace_id: str,
    data: MetricAgentRunRequest,
    manager: Annotated[TokenData, Depends(require_manager)]
):
    if manager.company_id and manager.company_id != company_id:
        from app.core.errors import AppError, ErrorCode
        raise AppError(ErrorCode.FORBIDDEN, "Cross-tenant access denied")

    items = await metric_agent_service.run_metric_agent_for_workspace(
        company_id,
        workspace_id,
        manager.user_id,
        manager.company_id,
        data.metric_targets,
    )
    return api_response([MetricOut(**item.model_dump()) for item in items])


@router.post("/{metric_id}/review", response_model=SuccessResponse[MetricOut])
async def review_metric(
    metric_id: str,
    data: MetricReview,
    reviewer: Annotated[TokenData, Depends(require_role("data_reviewer"))]
):
    res = await metric_service.review_metric(
        metric_id,
        data.action,
        reviewer.user_id,
        data.override_value,
        data.override_rationale,
        reviewer.company_id,
    )
    return api_response(MetricOut(**res.model_dump()))
