"""Routing logic for selecting deterministic metric tools."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.llm_factory import create_llm

from .catalog import _load_emission_factors
from .constants import ROUTER_SYSTEM, TOOL_REGISTRY
from .fields import (
    _default_emission_factor,
    _extract_company_id,
    _extract_response_text,
    _field_catalog,
    _field_unit,
    _find_best_field,
    _matching_entries,
    _parse_json_response,
)


def _build_router_prompt(
    metric_key: str,
    metric_definition: dict[str, Any],
    gold_records: dict[str, Any],
    previous_error: str | None = None,
) -> str:
    catalog = _field_catalog(gold_records)
    available_fields = [
        {
            "key": key,
            "unit": value.get("unit"),
            "records": value.get("records", []),
        }
        for key, value in sorted(catalog.items())
    ]
    company_id = _extract_company_id(gold_records)
    available_factors = sorted(_load_emission_factors(company_id).get("factors", {}).keys())
    tools_description = "\n".join(f"- {name}: {tool['description']} | args={tool['args']}" for name, tool in TOOL_REGISTRY.items())
    retry_note = f"\nPrevious attempt failed with: {previous_error}. Choose a different tool or arguments." if previous_error else ""
    return (
        f"Metric key: {metric_key}\n"
        f"Metric definition: {json.dumps(metric_definition)}\n"
        f"Available fields: {json.dumps(available_fields)}\n"
        f"Available emission factors: {json.dumps(available_factors)}\n"
        f"Available tools:\n{tools_description}\n"
        f"{retry_note}\n"
        "Return JSON only in this shape:\n"
        '{"tool_name": "<tool name>", "arguments": {"arg": "value"}}'
    )


def _heuristic_route(metric_key: str, metric_definition: dict[str, Any], gold_records: dict[str, Any]) -> dict[str, Any]:
    unit = metric_definition.get("unit", "value")
    suggested_tool = metric_definition.get("suggested_tool", "direct_read")
    catalog_keys = list(_field_catalog(gold_records).keys())

    def _score(catalog_key: str) -> int:
        ck_words = set(catalog_key.lower().replace("_", " ").split())
        m_words = set(metric_key.lower().replace("_", " ").split())
        return len(ck_words & m_words)

    best_key = None
    if catalog_keys:
        candidates = sorted(catalog_keys, key=_score, reverse=True)
        if _score(candidates[0]) > 0:
            best_key = candidates[0]

    if metric_key in ("scope1_kgco2e", "scope1_tco2e", "scope2_kgco2e", "scope2_tco2e"):
        scope_prefix = "scope1" if "scope1" in metric_key else "scope2"
        direct_key = next((key for key in catalog_keys if key == metric_key), None)
        
        if not direct_key:
            alt_key = f"{scope_prefix}_kgco2e" if "tco2e" in metric_key else f"{scope_prefix}_tco2e"
            direct_key = next((key for key in catalog_keys if key == alt_key), None)
            if direct_key:
                from_unit = "kgCO2e" if "kgco2e" in alt_key else "tCO2e"
                return {
                    "tool_name": "unit_convert",
                    "arguments": {
                        "source_key": direct_key,
                        "from_unit": _field_unit(gold_records, direct_key) or from_unit,
                        "to_unit": unit,
                        "mapping_confidence": 0.95
                    }
                }

        if direct_key:
            return {
                "tool_name": "aggregate_period",
                "arguments": {"source_keys": [direct_key], "operation": "sum", "unit": unit, "mapping_confidence": 0.95},
            }
        if scope_prefix == "scope2":
            emission_source = _find_best_field(
                gold_records,
                include_terms=("electricity", "electric", "power", "strom", "kwh", "mwh"),
            )
        else:
            emission_source = _find_best_field(
                gold_records,
                include_terms=("gas", "fuel", "diesel", "petrol", "gasoline", "lpg", "litre", "litres", "kwh"),
            )
        if emission_source:
            return {
                "tool_name": "apply_emission_factor",
                "arguments": {
                    "source_key": emission_source,
                    "ef_key": _default_emission_factor(metric_key, emission_source, gold_records),
                    "result_unit": unit,
                    "mapping_confidence": 0.8,
                },
            }

    if metric_key == "total_ghg_tco2e":
        available_scopes = [key for key in catalog_keys if "scope1" in key or "scope2" in key or "scope3" in key]
        if available_scopes:
            return {"tool_name": "scope_total", "arguments": {"scope_keys": available_scopes, "unit": unit}}

    if best_key:
        if suggested_tool == "aggregate_period":
            return {
                "tool_name": "aggregate_period",
                "arguments": {"source_keys": [best_key], "operation": "sum", "unit": unit, "mapping_confidence": 0.85},
            }
        if suggested_tool == "apply_emission_factor":
            return {
                "tool_name": "apply_emission_factor",
                "arguments": {
                    "source_key": best_key,
                    "ef_key": _default_emission_factor(metric_key, best_key, gold_records),
                    "result_unit": unit,
                    "mapping_confidence": 0.75,
                },
            }
        return {"tool_name": "direct_read", "arguments": {"source_key": best_key, "unit": unit, "mapping_confidence": 0.85}}

    raise ValueError(f"No heuristic route found dynamically for {metric_key}")


def _normalize_route(
    metric_key: str,
    metric_definition: dict[str, Any],
    gold_records: dict[str, Any],
    route: dict[str, Any] | None,
) -> dict[str, Any]:
    if not route or route.get("tool_name") not in TOOL_REGISTRY:
        return _heuristic_route(metric_key, metric_definition, gold_records)

    tool_name = route["tool_name"]
    arguments = route.get("arguments") or {}
    normalized = {"tool_name": tool_name, "arguments": dict(arguments)}
    unit = metric_definition.get("unit", "value")

    if tool_name == "direct_read":
        source_key = normalized["arguments"].get("source_key")
        if metric_key.endswith("_total"):
            return _heuristic_route(metric_key, metric_definition, gold_records)
        if not source_key or not _matching_entries(gold_records, source_key):
            return _heuristic_route(metric_key, metric_definition, gold_records)
        normalized["arguments"]["unit"] = normalized["arguments"].get("unit") or _field_unit(gold_records, source_key) or unit
        return normalized

    if tool_name == "aggregate_period":
        source_keys = normalized["arguments"].get("source_keys")
        if isinstance(source_keys, str):
            source_keys = [source_keys]
        if not source_keys:
            return _heuristic_route(metric_key, metric_definition, gold_records)
        source_keys = [key for key in source_keys if _matching_entries(gold_records, key)]
        if not source_keys:
            return _heuristic_route(metric_key, metric_definition, gold_records)
        normalized["arguments"]["source_keys"] = source_keys
        normalized["arguments"]["operation"] = normalized["arguments"].get("operation") or "sum"
        normalized["arguments"]["unit"] = normalized["arguments"].get("unit") or unit
        return normalized

    if tool_name == "apply_emission_factor":
        source_key = normalized["arguments"].get("source_key")
        if not source_key or not _matching_entries(gold_records, source_key):
            return _heuristic_route(metric_key, metric_definition, gold_records)
        ef_key = normalized["arguments"].get("ef_key")
        company_id = _extract_company_id(gold_records)
        if ef_key not in _load_emission_factors(company_id).get("factors", {}):
            ef_key = _default_emission_factor(metric_key, source_key, gold_records)
        if not ef_key:
            return _heuristic_route(metric_key, metric_definition, gold_records)
        normalized["arguments"]["ef_key"] = ef_key
        normalized["arguments"]["result_unit"] = normalized["arguments"].get("result_unit") or unit
        return normalized

    if tool_name == "unit_convert":
        source_key = normalized["arguments"].get("source_key")
        if not source_key or not _matching_entries(gold_records, source_key):
            return _heuristic_route(metric_key, metric_definition, gold_records)
        normalized["arguments"]["from_unit"] = normalized["arguments"].get("from_unit") or _field_unit(gold_records, source_key)
        normalized["arguments"]["to_unit"] = normalized["arguments"].get("to_unit") or unit
        if not normalized["arguments"]["from_unit"]:
            return _heuristic_route(metric_key, metric_definition, gold_records)
        return normalized

    if tool_name == "calc_intensity":
        absolute_key = normalized["arguments"].get("absolute_key")
        denominator_key = normalized["arguments"].get("denominator_key")
        if not absolute_key or not denominator_key:
            return _heuristic_route(metric_key, metric_definition, gold_records)
        if not _matching_entries(gold_records, absolute_key) or not _matching_entries(gold_records, denominator_key):
            return _heuristic_route(metric_key, metric_definition, gold_records)
        normalized["arguments"]["unit"] = normalized["arguments"].get("unit") or unit
        return normalized

    if tool_name == "scope_total":
        scope_keys = normalized["arguments"].get("scope_keys")
        if isinstance(scope_keys, str):
            scope_keys = [scope_keys]
        if not scope_keys:
            return _heuristic_route(metric_key, metric_definition, gold_records)
        scope_keys = [key for key in scope_keys if _matching_entries(gold_records, key)]
        if not scope_keys:
            return _heuristic_route(metric_key, metric_definition, gold_records)
        normalized["arguments"]["scope_keys"] = scope_keys
        normalized["arguments"]["unit"] = normalized["arguments"].get("unit") or unit
        return normalized

    if tool_name == "yoy_delta":
        current_key = normalized["arguments"].get("current_key")
        previous_key = normalized["arguments"].get("previous_key")
        if not current_key or not previous_key:
            return _heuristic_route(metric_key, metric_definition, gold_records)
        if not _matching_entries(gold_records, current_key) or not _matching_entries(gold_records, previous_key):
            return _heuristic_route(metric_key, metric_definition, gold_records)
        normalized["arguments"]["unit"] = normalized["arguments"].get("unit") or unit
        return normalized

    return normalized


def _friendly_metric_error(metric_key: str, raw_error: str | None) -> str:
    if not raw_error:
        return "The metric agent could not match this metric to the approved extraction structure."

    lowered = raw_error.lower()
    if "source_key" in lowered or "not found in gold records" in lowered or "no values available for aggregation" in lowered:
        return "No matching source field was found for this metric in the approved extraction data."
    if "absolute_key" in lowered or "denominator_key" in lowered:
        return "The required numerator or denominator fields were not found for this metric in the approved extraction data."
    if "zero" in lowered:
        return "The required denominator was zero, so this metric could not be calculated automatically."
    if "emission factor" in lowered:
        return "A matching emission factor could not be selected for this metric automatically."
    if "conversion defined" in lowered:
        return "The metric was found, but the required unit conversion is not configured."
    return "The metric agent could not derive this metric confidently from the approved extraction structure."


async def _route_metric(
    metric_key: str,
    metric_definition: dict[str, Any],
    gold_records: dict[str, Any],
    previous_error: str | None,
    *,
    llm_factory=create_llm,
) -> dict[str, Any]:
    try:
        llm = llm_factory(temperature=0.0)
        response = await llm.ainvoke(
            [
                SystemMessage(content=ROUTER_SYSTEM),
                HumanMessage(content=_build_router_prompt(metric_key, metric_definition, gold_records, previous_error)),
            ]
        )
        raw = _parse_json_response(_extract_response_text(response))
        return _normalize_route(metric_key, metric_definition, gold_records, raw)
    except Exception:
        return _heuristic_route(metric_key, metric_definition, gold_records)
