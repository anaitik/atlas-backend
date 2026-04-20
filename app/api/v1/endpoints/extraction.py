from collections import defaultdict
from typing import Annotated, Any, List
from fastapi import APIRouter, Depends

from app.core.responses import SuccessResponse, api_response
from app.dependencies.auth import require_manager, require_role, TokenData
from app.models.document import Document
from app.models.extraction import ExtractedData
from app.models.extraction import SchemaTemplate
from app.schemas.extraction import (
    AuditEventOut,
    BlueprintInsightOut,
    EvidenceDocumentOut,
    ExtractionInsightsOut,
    ExtractionPreRunOut,
    ExtractionPreRunRequest,
    ExtractionRunRequest,
    ExtractedDataOut,
    InsightAggregateOut,
    InsightIssueOut,
    ReviewRequest,
)
from app.services import audit_service, extraction_agent

router = APIRouter()


def _to_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "")
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    if isinstance(value, dict):
        for key in ("value", "amount", "total"):
            candidate = value.get(key)
            converted = _to_float(candidate)
            if converted is not None:
                return converted
    return None


def _build_out(
    run: ExtractedData,
    document_name_by_id: dict[str, str],
    template_name_by_id: dict[str, str],
) -> ExtractedDataOut:
    payload = run.model_dump()
    payload["document_filename"] = document_name_by_id.get(run.document_id)
    payload["template_name"] = template_name_by_id.get(run.template_id)
    return ExtractedDataOut(**payload)

@router.get("", response_model=SuccessResponse[List[ExtractedDataOut]])
async def list_extraction_runs(
    user: Annotated[TokenData, Depends(require_role("data_reviewer"))],
    workspace_id: str | None = None
):
    """Lists recent extraction runs for review."""
    query: dict[str, str] = {}
    if workspace_id:
        query["workspace_id"] = workspace_id
    if user.company_id:
        query["company_id"] = user.company_id

    runs = await ExtractedData.find(query).sort("-created_at").to_list()
    document_ids = list({run.document_id for run in runs if run.document_id})
    template_ids = list({run.template_id for run in runs if run.template_id})

    documents = await Document.find({"id": {"$in": document_ids}}).to_list() if document_ids else []
    templates = await SchemaTemplate.find({"id": {"$in": template_ids}}).to_list() if template_ids else []
    document_name_by_id = {doc.id: doc.filename for doc in documents}
    template_name_by_id = {tpl.id: tpl.name for tpl in templates}

    return api_response([_build_out(run, document_name_by_id, template_name_by_id) for run in runs])


@router.get("/insights", response_model=SuccessResponse[ExtractionInsightsOut])
async def extraction_insights(
    user: Annotated[TokenData, Depends(require_role("data_reviewer"))],
    workspace_id: str,
):
    query: dict[str, str] = {"workspace_id": workspace_id}
    if user.company_id:
        query["company_id"] = user.company_id

    runs = await ExtractedData.find(query).sort("-created_at").to_list()
    if not runs:
        return api_response(
            ExtractionInsightsOut(
                workspace_id=workspace_id,
                total_documents=0,
                total_blueprints=0,
                needs_review_count=0,
                low_confidence_count=0,
                blueprints=[],
                evidence_documents=[],
            )
        )

    document_ids = list({run.document_id for run in runs if run.document_id})
    template_ids = list({run.template_id for run in runs if run.template_id})
    documents = await Document.find({"id": {"$in": document_ids}}).to_list() if document_ids else []
    templates = await SchemaTemplate.find({"id": {"$in": template_ids}}).to_list() if template_ids else []
    document_name_by_id = {doc.id: doc.filename for doc in documents}
    template_by_id = {tpl.id: tpl for tpl in templates}

    grouped_runs: dict[str, list[ExtractedData]] = defaultdict(list)
    for run in runs:
        grouped_runs[run.template_id].append(run)

    blueprint_cards: list[BlueprintInsightOut] = []
    low_confidence_count = 0
    needs_review_count = 0
    evidence_documents: list[EvidenceDocumentOut] = []

    for run in runs:
        if run.confidence_score < 0.85:
            low_confidence_count += 1
        if run.status in {"pending_review", "failed"}:
            needs_review_count += 1

        template_name = template_by_id.get(run.template_id).name if template_by_id.get(run.template_id) else run.template_id
        evidence_documents.append(
            EvidenceDocumentOut(
                extraction_id=run.id,
                document_id=run.document_id,
                document_filename=document_name_by_id.get(run.document_id, f"Document {run.document_id[:8]}"),
                template_id=run.template_id,
                template_name=template_name,
                status=run.status,
                confidence_score=run.confidence_score,
                created_at=run.created_at,
                payload=run.payload or {},
            )
        )

    for template_id, template_runs in grouped_runs.items():
        template = template_by_id.get(template_id)
        template_name = template.name if template else template_id
        required_fields = list((template.schema_definition or {}).keys()) if template else []
        approved_count = sum(1 for item in template_runs if item.status == "approved")
        pending_count = sum(1 for item in template_runs if item.status in {"pending_review", "failed"})
        rejected_count = sum(1 for item in template_runs if item.status == "rejected")
        average_confidence = (
            sum(item.confidence_score for item in template_runs) / len(template_runs)
            if template_runs
            else 0.0
        )
        low_confidence_template = sum(1 for item in template_runs if item.confidence_score < 0.85)

        missing_required_count = 0
        issues: list[InsightIssueOut] = []
        numeric_by_field: dict[str, list[float]] = defaultdict(list)
        invoice_seen: dict[str, str] = {}

        for item in template_runs:
            payload = item.payload or {}
            for field in required_fields:
                value = payload.get(field)
                if value in (None, ""):
                    missing_required_count += 1
                    issues.append(
                        InsightIssueOut(
                            extraction_id=item.id,
                            document_id=item.document_id,
                            document_filename=document_name_by_id.get(item.document_id, f"Document {item.document_id[:8]}"),
                            field=field,
                            issue_type="missing_required",
                            detail=f"{field} is empty.",
                        )
                    )
            for key, raw_value in payload.items():
                numeric = _to_float(raw_value)
                if numeric is not None:
                    numeric_by_field[key].append(numeric)
                if key in {"invoice_number", "invoice_no", "invoice_id"}:
                    text_value = str(raw_value).strip()
                    if text_value:
                        previous_doc = invoice_seen.get(text_value)
                        if previous_doc and previous_doc != item.document_id:
                            issues.append(
                                InsightIssueOut(
                                    extraction_id=item.id,
                                    document_id=item.document_id,
                                    document_filename=document_name_by_id.get(item.document_id, f"Document {item.document_id[:8]}"),
                                    field=key,
                                    issue_type="duplicate_invoice_candidate",
                                    detail=f"Potential duplicate invoice number: {text_value}",
                                )
                            )
                        else:
                            invoice_seen[text_value] = item.document_id

        aggregates: list[InsightAggregateOut] = []
        for key, values in numeric_by_field.items():
            if not values:
                continue
            aggregates.append(
                InsightAggregateOut(
                    key=key,
                    label=key.replace("_", " ").title(),
                    value=round(sum(values), 4),
                    unit=None,
                )
            )
        aggregates = sorted(aggregates, key=lambda item: abs(item.value), reverse=True)[:6]

        blueprint_cards.append(
            BlueprintInsightOut(
                template_id=template_id,
                template_name=template_name,
                documents_processed=len(template_runs),
                approved_count=approved_count,
                pending_count=pending_count,
                rejected_count=rejected_count,
                average_confidence=round(average_confidence, 4),
                low_confidence_count=low_confidence_template,
                missing_required_count=missing_required_count,
                aggregates=aggregates,
                top_issues=issues[:10],
            )
        )

    blueprint_cards.sort(key=lambda item: (item.pending_count, item.low_confidence_count), reverse=True)
    evidence_documents.sort(key=lambda item: item.created_at, reverse=True)

    return api_response(
        ExtractionInsightsOut(
            workspace_id=workspace_id,
            total_documents=len(runs),
            total_blueprints=len(grouped_runs),
            needs_review_count=needs_review_count,
            low_confidence_count=low_confidence_count,
            blueprints=blueprint_cards,
            evidence_documents=evidence_documents,
        )
    )

@router.post("/run", response_model=SuccessResponse[ExtractedDataOut])
async def extract_document(
    data: ExtractionRunRequest,
    manager: Annotated[TokenData, Depends(require_manager)]
):
    """Triggers the AI agent to map the document text into the template schema."""
    result = await extraction_agent.run_extraction(
        data.document_id,
        data.template_id,
        manager.user_id,
        manager.company_id,
    )
    
    return api_response(ExtractedDataOut(**result.model_dump()))


@router.post("/prerun", response_model=SuccessResponse[ExtractionPreRunOut])
async def prerun_extraction(
    data: ExtractionPreRunRequest,
    manager: Annotated[TokenData, Depends(require_manager)]
):
    """
    Preview extraction and metric derivation without persisting extraction records or metrics.
    Optionally provide feedback_nlp to steer the agent and rerun quickly.
    """
    result = await extraction_agent.run_extraction_prerun(
        data.document_id,
        data.template_id,
        manager.company_id,
        data.feedback_nlp,
    )
    return api_response(ExtractionPreRunOut(**result))

@router.post("/{extraction_id}/review", response_model=SuccessResponse[ExtractedDataOut])
async def review_extraction(
    extraction_id: str,
    data: ReviewRequest,
    reviewer: Annotated[TokenData, Depends(require_role("data_reviewer"))]
):
    """Human-in-the-loop review. Approve or reject an AI extraction, optionally providing payload overrides."""
    result = await extraction_agent.submit_review(
        extraction_id,
        data.action,
        reviewer.user_id,
        data.overrides,
        reviewer.company_id,
    )
    
    return api_response(ExtractedDataOut(**result.model_dump()))


@router.get("/{extraction_id}/audit", response_model=SuccessResponse[List[AuditEventOut]])
async def extraction_audit_timeline(
    extraction_id: str,
    reviewer: Annotated[TokenData, Depends(require_role("data_reviewer"))],
):
    record = await ExtractedData.get(extraction_id)
    if not record:
        from app.core.errors import AppError, ErrorCode

        raise AppError(ErrorCode.NOT_FOUND, "Extraction record not found")
    if reviewer.company_id and reviewer.company_id != record.company_id:
        from app.core.errors import AppError, ErrorCode

        raise AppError(ErrorCode.FORBIDDEN, "Cross-tenant access denied")

    extraction_events, _ = await audit_service.get_audit_log(
        company_id=record.company_id,
        workspace_id=record.workspace_id,
        entity_table="extracted_data",
        entity_id=extraction_id,
        page=1,
        page_size=100,
    )
    metric_events, _ = await audit_service.get_audit_log(
        company_id=record.company_id,
        workspace_id=record.workspace_id,
        entity_table="metrics",
        page=1,
        page_size=200,
    )
    linked_metric_events = [
        event
        for event in metric_events
        if (event.payload or {}).get("extraction_id") == extraction_id
    ]
    all_events = sorted(
        [*extraction_events, *linked_metric_events],
        key=lambda item: item.created_at,
        reverse=True,
    )
    return api_response([AuditEventOut(**event.model_dump()) for event in all_events[:80]])
