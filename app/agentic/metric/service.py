"""Metric agent orchestration service."""

from __future__ import annotations

from typing import Any

from app.core.errors import AppError, ErrorCode
from app.llm_factory import create_llm
from app.models.extraction import ExtractedData, SchemaTemplate
from app.models.metric import Metric
from app.models.workspace import Workspace

from .catalog import _load_metric_definitions, list_metric_definitions
from .constants import MAX_ATTEMPTS, METRIC_PRIORITY
from .fields import (
    _collect_numeric_fields,
    _extract_response_text,
    _field_aliases,
    _field_catalog,
    _parse_json_response,
)
from .persistence import _append_derived_metric, _metric_source_ids, _upsert_metric
from .recommendation import (
    _default_metric_targets,
    _default_metric_targets_from_keys,
    recommend_metric_targets_for_extractions,
)
from .routing import _friendly_metric_error, _normalize_route, _route_metric
from .tools import _run_tool


async def _build_gold_records(
    extractions: list[ExtractedData],
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    template_ids = {extraction.template_id for extraction in extractions}
    template_map: dict[str, SchemaTemplate] = {}
    for template_id in template_ids:
        template = await SchemaTemplate.get(template_id)
        if template:
            template_map[template.id] = template

    gold_records: dict[str, Any] = {}
    source_index: dict[str, set[str]] = {}

    for extraction in extractions:
        template = template_map.get(extraction.template_id)
        template_name = template.name if template else ""
        fields: dict[str, Any] = {}

        audit_context = {
            "invoice_number": extraction.payload.get("invoice_number") or extraction.payload.get("rechnungsnummer"),
            "invoice_date": extraction.payload.get("invoice_date") or extraction.payload.get("datum"),
            "vendor_name": extraction.payload.get("vendor_name") or extraction.payload.get("lieferant"),
            "document_id": extraction.document_id,
            "extraction_id": extraction.id,
        }
        audit_context = {key: value for key, value in audit_context.items() if value}

        for path, numeric, unit in _collect_numeric_fields(extraction.payload):
            aliases = _field_aliases(path, unit, template_name) or {path.split(".")[-1]}
            for alias in aliases:
                fields[alias] = {
                    "value": numeric,
                    "unit": unit,
                    "path": path,
                    "audit": audit_context,
                }
                source_index.setdefault(alias, set()).add(extraction.id)

        if not fields:
            continue

        gold_records[extraction.id] = {
            "label": template_name or extraction.template_id,
            "template_name": template_name,
            "document_id": extraction.document_id,
            "company_id": extraction.company_id,
            "fields": fields,
        }

    return gold_records, {key: sorted(value) for key, value in source_index.items()}


async def recommend_metric_targets_for_workspace(
    company_id: str,
    workspace_id: str,
    actor_company_id: str | None = None,
) -> dict[str, Any]:
    if actor_company_id and actor_company_id != company_id:
        raise AppError(ErrorCode.FORBIDDEN, "Cross-tenant access denied")

    extractions = await ExtractedData.find(
        {
            "company_id": company_id,
            "workspace_id": workspace_id,
            "status": "approved",
        }
    ).to_list()
    return await recommend_metric_targets_for_extractions(
        extractions,
        llm_factory=create_llm,
        schema_template_cls=SchemaTemplate,
    )


async def run_metric_agent_for_workspace(
    company_id: str,
    workspace_id: str,
    actor_id: str,
    actor_company_id: str | None = None,
    metric_targets: list[str] | None = None,
) -> list[Metric]:
    if actor_company_id and actor_company_id != company_id:
        raise AppError(ErrorCode.FORBIDDEN, "Cross-tenant access denied")

    extractions = await ExtractedData.find(
        {
            "company_id": company_id,
            "workspace_id": workspace_id,
            "status": "approved",
        }
    ).to_list()
    if not extractions:
        raise AppError(ErrorCode.BAD_REQUEST, "No approved extraction data is available for this workspace")
    workspace = await Workspace.get(workspace_id)
    workspace_region = (workspace.region if workspace else "EU") or "EU"
    workspace_reporting_year = workspace.reporting_year if workspace else None
    workspace_scope2_method = workspace.scope2_method if workspace else None

    gold_records, source_index = await _build_gold_records(extractions)
    if not gold_records:
        raise AppError(ErrorCode.BAD_REQUEST, "Approved extractions do not contain numeric data for metric derivation")

    definitions = _load_metric_definitions(company_id)
    if metric_targets is None:
        recommendations = await recommend_metric_targets_for_extractions(
            extractions,
            llm_factory=create_llm,
            schema_template_cls=SchemaTemplate,
        )
        targets = recommendations["metric_targets"]
        if not targets:
            raise AppError(
                ErrorCode.BAD_REQUEST,
                "No confident metric recommendations could be derived from the approved JSON structure. Choose targets manually.",
            )
    else:
        targets = metric_targets
        if not targets:
            raise AppError(ErrorCode.BAD_REQUEST, "No metric targets were supplied.")

    unknown_targets = [target for target in targets if target not in definitions]
    if unknown_targets:
        raise AppError(ErrorCode.BAD_REQUEST, f"Unknown metric targets: {', '.join(sorted(unknown_targets))}")
    targets = sorted(dict.fromkeys(targets), key=lambda key: (METRIC_PRIORITY.get(key, 999), key))

    metrics: list[Metric] = []
    for metric_key in targets:
        definition = definitions[metric_key]
        previous_error: str | None = None
        record: dict[str, Any] | None = None

        for _ in range(MAX_ATTEMPTS):
            route = await _route_metric(
                metric_key,
                definition,
                gold_records,
                previous_error,
                llm_factory=create_llm,
            )
            route = _normalize_route(metric_key, definition, gold_records, route)
            if route.get("tool_name") == "apply_emission_factor":
                route.setdefault("arguments", {})
                route["arguments"].setdefault("region", workspace_region)
                route["arguments"].setdefault("reporting_year", workspace_reporting_year)
                route["arguments"].setdefault("scope2_method", workspace_scope2_method)
            try:
                record = _run_tool(route["tool_name"], gold_records, metric_key, route["arguments"])
                break
            except Exception as exc:
                previous_error = str(exc)

        if record is None:
            record = {
                "metric_key": metric_key,
                "value": None,
                "unit": definition.get("unit", "value"),
                "tool_used": None,
                "input_keys": [],
                "status": "MANUAL_REQUIRED",
                "error_detail": _friendly_metric_error(metric_key, previous_error),
            }

        source_ids = _metric_source_ids(source_index, record.get("input_keys", []))
        metric = await _upsert_metric(
            company_id,
            workspace_id,
            actor_id,
            definition,
            record,
            source_ids,
            gold_records,
        )
        metrics.append(metric)

        if record.get("status") == "OK":
            _append_derived_metric(gold_records, source_index, metric_key, record, source_ids)

    return metrics


async def preview_metric_agent_for_extractions(
    extractions: list[ExtractedData],
    metric_targets: list[str] | None = None,
) -> list[dict[str, Any]]:
    if not extractions:
        raise AppError(ErrorCode.BAD_REQUEST, "No extraction data is available for metric preview")

    gold_records, source_index = await _build_gold_records(extractions)
    if not gold_records:
        return []

    company_id = getattr(extractions[0], "company_id", None) if extractions else None
    definitions = _load_metric_definitions(company_id)
    if metric_targets is None:
        recommendations = await recommend_metric_targets_for_extractions(
            extractions,
            llm_factory=create_llm,
            schema_template_cls=SchemaTemplate,
        )
        targets = recommendations.get("metric_targets", [])
    else:
        targets = metric_targets

    targets = [target for target in (targets or []) if target in definitions]
    targets = sorted(dict.fromkeys(targets), key=lambda key: (METRIC_PRIORITY.get(key, 999), key))
    if not targets:
        targets = _default_metric_targets_from_keys(set(_field_catalog(gold_records)))
        targets = [target for target in targets if target in definitions]

    preview: list[dict[str, Any]] = []
    workspace_region = "EU"
    workspace_reporting_year = None
    workspace_scope2_method = None
    workspace_id = getattr(extractions[0], "workspace_id", None) if extractions else None
    if workspace_id:
        workspace = await Workspace.get(workspace_id)
        if workspace:
            workspace_region = workspace.region or "EU"
            workspace_reporting_year = workspace.reporting_year
            workspace_scope2_method = workspace.scope2_method

    for metric_key in targets:
        definition = definitions[metric_key]
        previous_error: str | None = None
        record: dict[str, Any] | None = None
        for _ in range(MAX_ATTEMPTS):
            route = await _route_metric(
                metric_key,
                definition,
                gold_records,
                previous_error,
                llm_factory=create_llm,
            )
            route = _normalize_route(metric_key, definition, gold_records, route)
            if route.get("tool_name") == "apply_emission_factor":
                route.setdefault("arguments", {})
                route["arguments"].setdefault("region", workspace_region)
                route["arguments"].setdefault("reporting_year", workspace_reporting_year)
                route["arguments"].setdefault("scope2_method", workspace_scope2_method)
            try:
                record = _run_tool(route["tool_name"], gold_records, metric_key, route["arguments"])
                break
            except Exception as exc:
                previous_error = str(exc)

        if record is None:
            record = {
                "metric_key": metric_key,
                "value": None,
                "unit": definition.get("unit", "value"),
                "tool_used": None,
                "input_keys": [],
                "status": "MANUAL_REQUIRED",
                "error_detail": _friendly_metric_error(metric_key, previous_error),
            }
        else:
            record["status"] = record.get("status", "OK")

        record["name"] = definition.get("description", metric_key)
        record["metric_label"] = record["name"]
        record["pillar"] = definition.get("pillar", "environmental")
        record["source_extracted_data_ids"] = _metric_source_ids(source_index, record.get("input_keys", []))
        preview.append(record)

        if record.get("status") == "OK":
            _append_derived_metric(gold_records, source_index, metric_key, record, record["source_extracted_data_ids"])

    return preview
