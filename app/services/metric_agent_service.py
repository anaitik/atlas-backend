"""Compatibility shim for the metric agent service."""

from __future__ import annotations

from app.agentic.metric import recommendation as recommendation_module
from app.agentic.metric import service as service_module
from app.agentic.metric.fields import _field_aliases, _parse_json_response
from app.agentic.metric.recommendation import _default_metric_targets_from_keys
from app.agentic.metric.routing import _friendly_metric_error
from app.agentic.metric.tools import _run_tool
from app.llm_factory import create_llm
from app.models.extraction import ExtractedData, SchemaTemplate
from app.models.metric import Metric


def list_metric_definitions(company_id: str | None = None) -> list[dict]:
    return service_module.list_metric_definitions(company_id)


async def recommend_metric_targets_for_extractions(extractions: list[ExtractedData]) -> dict:
    return await recommendation_module.recommend_metric_targets_for_extractions(
        extractions,
        llm_factory=create_llm,
        schema_template_cls=SchemaTemplate,
    )


async def recommend_metric_targets_for_workspace(
    company_id: str,
    workspace_id: str,
    actor_company_id: str | None = None,
) -> dict:
    service_module.create_llm = create_llm
    return await service_module.recommend_metric_targets_for_workspace(
        company_id,
        workspace_id,
        actor_company_id,
    )


async def run_metric_agent_for_workspace(
    company_id: str,
    workspace_id: str,
    actor_id: str,
    actor_company_id: str | None = None,
    metric_targets: list[str] | None = None,
) -> list[Metric]:
    service_module.create_llm = create_llm
    return await service_module.run_metric_agent_for_workspace(
        company_id,
        workspace_id,
        actor_id,
        actor_company_id,
        metric_targets,
    )


async def preview_metric_agent_for_extractions(
    extractions: list[ExtractedData],
    metric_targets: list[str] | None = None,
) -> list[dict]:
    service_module.create_llm = create_llm
    return await service_module.preview_metric_agent_for_extractions(
        extractions,
        metric_targets,
    )


__all__ = [
    "SchemaTemplate",
    "create_llm",
    "list_metric_definitions",
    "recommend_metric_targets_for_extractions",
    "recommend_metric_targets_for_workspace",
    "run_metric_agent_for_workspace",
    "preview_metric_agent_for_extractions",
    "_parse_json_response",
    "_field_aliases",
    "_run_tool",
    "_default_metric_targets_from_keys",
    "_friendly_metric_error",
]
