from typing import Annotated, List
from fastapi import APIRouter, Depends, Query

from app.core.responses import SuccessResponse, api_response
from app.dependencies.auth import require_manager, require_role, TokenData
from app.models.metric import Metric
from app.schemas.metric import (
    ManualMetricEntry,
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


@router.post("/manual-entry", response_model=SuccessResponse[MetricOut])
async def manual_metric_entry(
    data: ManualMetricEntry,
    manager: Annotated[TokenData, Depends(require_manager)],
):
    """Create or update a metric via direct human entry (no document extraction required)."""
    if manager.company_id and manager.company_id != data.company_id:
        from app.core.errors import AppError, ErrorCode
        raise AppError(ErrorCode.FORBIDDEN, "Cross-tenant access denied")

    from app.models.metric import Metric
    from app.services import audit_service

    metadata: dict = {
        "input_mode": "manual",
        "human_override": True,
        "source_type": "manual_entry",
        "pillar": data.pillar,
    }
    if data.evidence_note:
        metadata["evidence_note"] = data.evidence_note
    if data.evidence_document_id:
        metadata["evidence_document_id"] = data.evidence_document_id

    existing = await Metric.find_one({
        "company_id": data.company_id,
        "workspace_id": data.workspace_id,
        "metric_code": data.metric_code,
    })

    if existing:
        existing.name = data.name
        existing.value = data.value
        existing.unit = data.unit
        existing.pillar = data.pillar
        existing.metadata = metadata
        existing.status = "approved"
        existing.reviewer = manager.user_id
        await existing.save_with_timestamp()
        metric = existing
    else:
        metric = Metric(
            company_id=data.company_id,
            workspace_id=data.workspace_id,
            metric_code=data.metric_code,
            name=data.name,
            value=data.value,
            unit=data.unit,
            pillar=data.pillar,
            metadata=metadata,
            source_extracted_data_ids=[],
            status="approved",
            reviewer=manager.user_id,
        )
        await metric.insert()

    # Sync to interview: if this metric matches a VSME question, auto-fill the response
    try:
        from app.services.interview_service import sync_metric_to_interview
        await sync_metric_to_interview(data.workspace_id, data.company_id, data.metric_code, data.value, data.unit)
    except Exception:
        pass  # Non-fatal

    await audit_service.emit(
        event_type="METRIC_MANUAL_ENTRY",
        actor_user_id=manager.user_id,
        company_id=data.company_id,
        workspace_id=data.workspace_id,
        entity_table="metrics",
        entity_id=metric.id,
        payload={"metric_code": data.metric_code, "value": data.value, "unit": data.unit},
    )
    return api_response(MetricOut(**metric.model_dump()))


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
    if data.action == "approve":
        try:
            from app.services.interview_service import sync_metric_to_interview
            await sync_metric_to_interview(res.workspace_id, res.company_id, res.metric_code, res.value, res.unit)
        except Exception:
            pass
    return api_response(MetricOut(**res.model_dump()))
