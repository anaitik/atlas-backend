"""
Orchestrates LangChain/LangGraph extraction via the configured LLM provider.
"""

from datetime import date
from types import SimpleNamespace
from typing import Dict, Any

from app.core.errors import AppError, ErrorCode
from app.models.document import Document
from app.models.extraction import ExtractedData, SchemaTemplate
from app.services import audit_service
from app.config import get_settings


def _fallback_value(field_hint: Any) -> Any:
    if isinstance(field_hint, dict):
        return {key: _fallback_value(value) for key, value in field_hint.items()}
    if isinstance(field_hint, list):
        return []

    hint = str(field_hint).strip().lower()
    if hint in {"float", "number", "decimal"}:
        return 0.0
    if hint in {"int", "integer"}:
        return 0
    if hint in {"bool", "boolean"}:
        return False
    if hint == "date":
        return date.today().isoformat()
    return ""


def _extract_llm_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, list):
        return " ".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        ).strip()
    return str(content).strip()


def _assess_prerun_quality(
    template: SchemaTemplate,
    payload: dict[str, Any],
    projected_metrics: list[dict[str, Any]],
    confidence_score: float,
    extraction_failed: bool,
) -> dict[str, Any]:
    required_fields = [str(key) for key in (template.schema_definition or {}).keys()]
    missing_fields = [
        key
        for key in required_fields
        if payload.get(key) in (None, "")
    ]
    ok_metrics = [m for m in projected_metrics if m.get("status") == "OK"]
    failed_metrics = [m for m in projected_metrics if m.get("status") != "OK"]

    blockers: list[str] = []
    suggestions: list[str] = []

    if extraction_failed:
        blockers.append("Extraction failed for this sample document.")
        suggestions.append("Try a clearer sample document or add feedback guidance.")
    if missing_fields:
        blockers.append(f"Missing extracted fields: {', '.join(missing_fields[:6])}")
        suggestions.append("Add field-level hints or feedback NLP and rerun pre-run.")
    if not ok_metrics:
        blockers.append("No projected metrics could be computed confidently.")
        suggestions.append("Ensure numeric source fields and units are present in schema.")
    if confidence_score < 0.75:
        blockers.append("Model confidence is low for this pre-run.")
        suggestions.append("Provide stronger feedback NLP to prioritize the right values.")
    if failed_metrics:
        suggestions.append("Review failed projected metrics and update schema/feedback.")

    if not blockers:
        status = "ready"
        headline = "Ready to Use"
    elif ok_metrics:
        status = "review"
        headline = "Needs Quick Review"
    else:
        status = "blocked"
        headline = "Blocked"

    return {
        "status": status,
        "headline": headline,
        "blockers": blockers,
        "suggestions": suggestions[:4],
        "missing_fields": missing_fields,
        "ok_metric_count": len(ok_metrics),
        "failed_metric_count": len(failed_metrics),
    }


async def _execute_extraction(
    doc: Document,
    template: SchemaTemplate,
    feedback_nlp: str | None = None,
) -> dict[str, Any]:
    from app.services import storage_service, template_generation_service

    path = storage_service.get_file_path(doc.storage_path)
    if not path.exists():
        raise AppError(ErrorCode.NOT_FOUND, f"Physical file missing for document {doc.id}")

    file_bytes = path.read_bytes()
    document_text = template_generation_service.extract_document_preview(file_bytes, doc.filename)
    import json
    from langchain_core.prompts import ChatPromptTemplate
    from app.llm_factory import create_llm

    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            "You are an expert Sustainability ESG Data analyst.\n"
            "Follow these instructions: {system_prompt}\n"
            "NEVER invent or hallucinate data. If a field is not present in the document, return null or an empty value.\n"
            "Strictly map regional/language-specific terms (e.g. Strom to electricity) if required by the schema.\n"
            "You must output ONLY valid JSON exactly matching this structure:\n"
            "{{\n"
            '  "confidence_score": <float between 0.0 and 1.0 representing your confidence in the extraction>,\n'
            '  "exception_reason": <string explaining any low confidence or missing critical data, or null>,\n'
            '  "payload": {schema_definition}\n'
            "}}"
        ),
        (
            "human",
            "Here is the raw document text:\n{document_text}\n\n"
            "Operator feedback for this run (if any):\n{feedback_nlp}"
        ),
    ])

    llm = create_llm(temperature=0.1)
    resolved_system_prompt = (template.system_prompt or "").strip()
    if not resolved_system_prompt:
        resolved_system_prompt = template_generation_service.build_compact_system_prompt(
            template_name=template.name,
            schema_definition=template.schema_definition or {},
            target_metrics_nlp=template.target_metrics_nlp,
        )

    try:
        chain = prompt | llm
        llm_response = await chain.ainvoke(
            {
                "system_prompt": resolved_system_prompt,
                "schema_definition": json.dumps(template.schema_definition, indent=2),
                "document_text": document_text,
                "feedback_nlp": (feedback_nlp or "No additional feedback provided.").strip(),
            }
        )
        content = _extract_llm_text(llm_response)
        if content.startswith("```json"):
            content = content[7:-3].strip()
        elif content.startswith("```"):
            content = content[3:-3].strip()

        llm_response_json = json.loads(content)
        final_payload = llm_response_json.get("payload")
        if not isinstance(final_payload, dict):
            final_payload = {}
        confidence_score = float(llm_response_json.get("confidence_score", 0.0))
        exception_reason = llm_response_json.get("exception_reason")
        extraction_failed = False
    except Exception as e:
        import structlog

        structlog.get_logger().error("llm_extraction_failed", error=str(e))
        final_payload = {}
        confidence_score = 0.0
        exception_reason = f"Extraction failed: {str(e)}"
        extraction_failed = True

    return {
        "payload": final_payload,
        "confidence_score": confidence_score,
        "exception_reason": exception_reason,
        "extraction_failed": extraction_failed,
    }


async def run_extraction(
    document_id: str,
    template_id: str,
    actor_id: str,
    actor_company_id: str | None = None,
) -> ExtractedData:
    doc = await Document.get(document_id)
    template = await SchemaTemplate.get(template_id)

    if not doc or not template:
        raise AppError(ErrorCode.NOT_FOUND, "Document or Template not found")
    if actor_company_id and actor_company_id != doc.company_id:
        raise AppError(ErrorCode.FORBIDDEN, "Cross-tenant access denied")
    if template.company_id != doc.company_id and template.company_id != "platform":
        raise AppError(ErrorCode.BAD_REQUEST, "Template and document belong to different companies")
    if template.workspace_id and template.workspace_id != doc.workspace_id:
        raise AppError(ErrorCode.BAD_REQUEST, "Template is not available for this workspace")

    extraction_result = await _execute_extraction(doc, template)
    final_payload = extraction_result["payload"]
    confidence_score = extraction_result["confidence_score"]
    exception_reason = extraction_result["exception_reason"]
    extraction_failed = extraction_result["extraction_failed"]

    from app.services.workflow_service import get_workflow_policy

    policy = await get_workflow_policy(doc.workspace_id)

    auto_approve = False
    if not extraction_failed and not policy.require_extraction_review:
        auto_approve = confidence_score >= get_settings().EXTRACTION_CONFIDENCE_THRESHOLD

    initial_status = "failed" if extraction_failed else ("approved" if auto_approve else "pending_review")

    result = ExtractedData(
        company_id=doc.company_id,
        workspace_id=doc.workspace_id,
        document_id=doc.id,
        template_id=template.id,
        payload=final_payload,
        confidence_score=confidence_score,
        exception_reason=exception_reason,
        status=initial_status,
        reviewer="system_auto" if auto_approve else None,
    )

    await result.insert()
    await audit_service.emit(
        event_type="EXTRACTION_CREATED",
        actor_user_id=actor_id,
        company_id=doc.company_id,
        workspace_id=doc.workspace_id,
        entity_table="extracted_data",
        entity_id=result.id,
        payload={"document_id": doc.id, "template_id": template.id, "auto_approved": auto_approve},
    )

    if auto_approve:
        from app.services import esg_calculation_service, metric_service, metric_agent_service

        try:
            await metric_service.sync_metrics_from_approved_extraction(
                result,
                actor_id,
                actor_company_id,
            )
            await metric_agent_service.run_metric_agent_for_workspace(
                doc.company_id,
                doc.workspace_id,
                actor_id,
                actor_company_id,
                None,
            )
            await esg_calculation_service.run_workspace_esg_calculations(
                doc.company_id,
                doc.workspace_id,
                actor_id,
                actor_company_id,
            )
        except Exception as e:
            import structlog

            structlog.get_logger().error("auto_metric_computation_failed", error=str(e))

    return result


async def run_extraction_prerun(
    document_id: str,
    template_id: str,
    actor_company_id: str | None = None,
    feedback_nlp: str | None = None,
) -> dict[str, Any]:
    doc = await Document.get(document_id)
    template = await SchemaTemplate.get(template_id)

    if not doc or not template:
        raise AppError(ErrorCode.NOT_FOUND, "Document or Template not found")
    if actor_company_id and actor_company_id != doc.company_id:
        raise AppError(ErrorCode.FORBIDDEN, "Cross-tenant access denied")
    if template.company_id != doc.company_id and template.company_id != "platform":
        raise AppError(ErrorCode.BAD_REQUEST, "Template and document belong to different companies")
    if template.workspace_id and template.workspace_id != doc.workspace_id:
        raise AppError(ErrorCode.BAD_REQUEST, "Template is not available for this workspace")

    extraction_result = await _execute_extraction(doc, template, feedback_nlp=feedback_nlp)
    final_payload = extraction_result["payload"]
    confidence_score = extraction_result["confidence_score"]
    exception_reason = extraction_result["exception_reason"]
    extraction_failed = extraction_result["extraction_failed"]

    preview_extraction = SimpleNamespace(
        id=f"preview:{doc.id}:{template.id}",
        document_id=doc.id,
        template_id=template.id,
        payload=final_payload,
        company_id=doc.company_id,
    )

    from app.services import metric_service, metric_agent_service

    metric_candidates = metric_service._metric_candidates(preview_extraction, template, doc.filename)
    metric_recommendation = await metric_agent_service.recommend_metric_targets_for_extractions([preview_extraction])
    projected_metrics = await metric_agent_service.preview_metric_agent_for_extractions(
        [preview_extraction],
        metric_recommendation.get("metric_targets", []),
    )
    readiness_summary = _assess_prerun_quality(
        template,
        final_payload,
        projected_metrics,
        confidence_score,
        extraction_failed,
    )

    return {
        "document_id": doc.id,
        "template_id": template.id,
        "payload": final_payload,
        "confidence_score": confidence_score,
        "exception_reason": exception_reason,
        "status": "failed" if extraction_failed else "preview_ready",
        "feedback_nlp_applied": (feedback_nlp or "").strip() or None,
        "metric_candidates": [candidate.model_dump() for candidate in metric_candidates],
        "metric_recommendation": metric_recommendation,
        "projected_metrics": projected_metrics,
        "readiness_summary": readiness_summary,
    }


async def submit_review(
    extraction_id: str,
    action: str,
    actor_id: str,
    overrides: Dict[str, Any] | None = None,
    actor_company_id: str | None = None,
) -> ExtractedData:
    record = await ExtractedData.get(extraction_id)
    if not record:
        raise AppError(ErrorCode.NOT_FOUND, "Extraction record not found")
    if actor_company_id and actor_company_id != record.company_id:
        raise AppError(ErrorCode.FORBIDDEN, "Cross-tenant access denied")

    if action not in ["approve", "reject"]:
        raise AppError(ErrorCode.BAD_REQUEST, "Action must be approve or reject")

    if record.status not in ["pending_review", "failed"]:
        raise AppError(
            ErrorCode.CONFLICT,
            f"Only records in pending_review or failed can be reviewed. Current status: {record.status}"
        )

    if action == "approve" and not record.payload:
        raise AppError(ErrorCode.BAD_REQUEST, "Cannot approve a record with an empty payload")

    record.status = "approved" if action == "approve" else "rejected"
    record.reviewer = actor_id

    if overrides:
        record.payload.update(overrides)

    await record.save()
    from app.services import metric_service

    if action == "approve":
        await metric_service.sync_metrics_from_approved_extraction(
            record,
            actor_id,
            actor_company_id,
        )
        from app.services import esg_calculation_service, metric_agent_service
        try:
            await metric_agent_service.run_metric_agent_for_workspace(
                record.company_id,
                record.workspace_id,
                actor_id,
                actor_company_id,
                None
            )
            await esg_calculation_service.run_workspace_esg_calculations(
                record.company_id,
                record.workspace_id,
                actor_id,
                actor_company_id,
            )
        except Exception as e:
            import structlog
            structlog.get_logger().error("manual_review_auto_metric_computation_failed", error=str(e))
    else:
        await metric_service.reject_metrics_from_extraction(
            record.id,
            actor_id,
            actor_company_id,
        )

    await audit_service.emit(
        event_type="RECORD_APPROVED" if action == "approve" else "RECORD_REJECTED",
        actor_user_id=actor_id,
        company_id=record.company_id,
        workspace_id=record.workspace_id,
        entity_table="extracted_data",
        entity_id=record.id,
    )
    return record
