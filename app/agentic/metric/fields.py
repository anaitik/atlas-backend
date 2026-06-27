"""Field parsing, aliasing, and record utilities for metric derivation."""

from __future__ import annotations

import json
import re
from typing import Any

from .constants import GENERIC_FIELD_NAMES


def _coerce_numeric(value: Any) -> float | None:
    from app.services.numeric_utils import coerce_activity_numeric

    return coerce_activity_numeric(value)


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _normalize_unit(value: str | None) -> str:
    if not value:
        return ""
    normalized = _normalize_key(value)
    normalized = normalized.replace("co_2", "co2")
    normalized = normalized.replace("liters", "litres")
    normalized = normalized.replace("liter", "litre")
    return normalized


def _extract_company_id(gold_records: dict[str, Any]) -> str | None:
    for record in gold_records.values():
        return record.get("company_id")
    return None


def _extract_response_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, list):
        return " ".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        ).strip()
    return str(content).strip()


def _parse_json_response(raw: str) -> dict[str, Any]:
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("No JSON object found in router response")
        text = text[start : end + 1]
    return json.loads(text)


def _collect_numeric_fields(payload: Any, prefix: str = "") -> list[tuple[str, float, str | None]]:
    items: list[tuple[str, float, str | None]] = []
    if isinstance(payload, dict):
        sibling_units = {
            _normalize_key(key[:-5]): str(value)
            for key, value in payload.items()
            if isinstance(key, str) and key.endswith("_unit") and value is not None
        }
        for raw_key, value in payload.items():
            if not isinstance(raw_key, str) or raw_key.endswith("_unit"):
                continue
            key = _normalize_key(raw_key)
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                nested_value = _coerce_numeric(value.get("value"))
                nested_unit = value.get("unit") or value.get("uom") or value.get("measurement_unit")
                if nested_value is not None:
                    items.append((path, nested_value, str(nested_unit) if nested_unit else None))
                items.extend(_collect_numeric_fields(value, path))
                continue
            if isinstance(value, list):
                for index, entry in enumerate(value):
                    items.extend(_collect_numeric_fields(entry, f"{path}_{index}"))
                continue

            numeric = _coerce_numeric(value)
            if numeric is None:
                continue
            unit = sibling_units.get(key)
            if not unit and key == "value" and isinstance(payload.get("unit"), (str, int, float)):
                unit = str(payload.get("unit"))
            items.append((path, numeric, unit))
    return items


def _collect_structure_fields(payload: Any, prefix: str = "") -> list[tuple[str, str | None]]:
    items: list[tuple[str, str | None]] = []
    if isinstance(payload, dict):
        sibling_units = {
            _normalize_key(key[:-5]): str(value)
            for key, value in payload.items()
            if isinstance(key, str) and key.endswith("_unit") and value is not None
        }
        for raw_key, value in payload.items():
            if not isinstance(raw_key, str) or raw_key.endswith("_unit"):
                continue
            key = _normalize_key(raw_key)
            path = f"{prefix}.{key}" if prefix else key
            unit = sibling_units.get(key)
            if not unit and key == "value" and isinstance(payload.get("unit"), (str, int, float)):
                unit = str(payload.get("unit"))

            if isinstance(value, dict):
                nested_unit = value.get("unit") or value.get("uom") or value.get("measurement_unit")
                if nested_unit and not unit:
                    unit = str(nested_unit)
                items.append((path, unit))
                items.extend(_collect_structure_fields(value, path))
                continue

            if isinstance(value, list):
                items.append((path, unit))
                for index, entry in enumerate(value[:3]):
                    items.extend(_collect_structure_fields(entry, f"{path}_{index}"))
                continue

            items.append((path, unit))
    return items


def _path_tokens(value: str) -> set[str]:
    return {token for token in _normalize_key(value).split("_") if token}


def _has_structure_numeric_hint(field_path: str, unit: str | None, template_name: str | None) -> bool:
    if _normalize_unit(unit):
        return True

    field_haystack = _normalize_key(field_path)
    field_tokens = _path_tokens(field_path)
    template_tokens = _path_tokens(template_name or "")

    numeric_tokens = {
        "amount",
        "avg",
        "average",
        "cases",
        "case",
        "consumption",
        "count",
        "frequency",
        "fte",
        "headcount",
        "hour",
        "hours",
        "incidents",
        "injury",
        "injuries",
        "kwh",
        "litres",
        "litre",
        "mwh",
        "number",
        "percent",
        "pct",
        "quantity",
        "rate",
        "ratio",
        "reading",
        "score",
        "scope1",
        "scope2",
        "scope3",
        "total",
        "usage",
        "value",
        "volume",
    }
    if field_tokens & numeric_tokens:
        return True

    if field_haystack in {"employees", "employee_total", "employee_count", "headcount", "workforce_total"}:
        return True

    utility_template_tokens = {
        "electric",
        "electricity",
        "gas",
        "fuel",
        "diesel",
        "petrol",
        "gasoline",
        "lpg",
        "strom",
        "erdgas",
    }
    if template_tokens & utility_template_tokens and field_tokens & {"value", "amount", "quantity", "total", "usage", "consumption", "reading"}:
        return True

    return False


def _structure_field_aliases(field_path: str, unit: str | None, template_name: str | None) -> set[str]:
    if not _has_structure_numeric_hint(field_path, unit, template_name):
        return set()

    aliases: set[str] = set()
    unit_key = _normalize_unit(unit)
    field_haystack = _normalize_key(field_path)
    combined_haystack = _normalize_key(f"{template_name or ''}_{field_path}")
    field_tokens = _path_tokens(field_path)

    energy_measure = bool(field_tokens & {"consumption", "usage", "reading", "kwh", "mwh", "litres", "litre", "volume", "fuel", "gas"})

    if any(token in combined_haystack for token in ("electric", "electricity", "power", "strom")) and (
        unit_key in {"kwh", "mwh"} or energy_measure or any(token in field_haystack for token in ("electric", "electricity", "power", "strom"))
    ):
        if unit_key in {"kwh", "mwh"}:
            aliases.add("electricity_kwh" if unit_key == "kwh" else "electricity_mwh")
        aliases.add("electricity_consumption")

    if any(token in combined_haystack for token in ("natural_gas", "erdgas", "gas")) and (
        unit_key == "kwh" or energy_measure or any(token in field_haystack for token in ("gas", "natural_gas", "erdgas"))
    ):
        if unit_key == "kwh":
            aliases.add("gas_kwh")
        aliases.add("natural_gas")

    if any(token in combined_haystack for token in ("fuel", "diesel", "petrol", "gasoline", "lpg")) and (
        unit_key in {"litres", "litre"} or energy_measure or any(token in field_haystack for token in ("fuel", "diesel", "petrol", "gasoline", "lpg"))
    ):
        aliases.add("fuel_litres")
        if "diesel" in combined_haystack:
            aliases.add("diesel_litres")
        if "petrol" in combined_haystack or "gasoline" in combined_haystack:
            aliases.add("petrol_litres")
        if "lpg" in combined_haystack:
            aliases.add("lpg_litres")

    if (
        field_haystack in {"employees", "employee_total", "employee_count", "headcount", "workforce_total", "fte"}
        or (
            any(token in field_haystack for token in ("employee", "employees", "workforce", "fte"))
            and any(token in field_haystack for token in ("count", "number", "total", "headcount", "fte"))
        )
    ):
        aliases.add("headcount")

    if (
        any(token in field_haystack for token in ("board", "independent", "independence"))
        and any(token in field_haystack for token in ("independent", "independence", "pct", "percent", "ratio"))
    ):
        aliases.add("board_independence_pct")

    if (
        any(token in field_haystack for token in ("whistle", "hotline", "ethic"))
        and any(token in field_haystack for token in ("case", "cases", "count", "number", "incident", "incidents"))
    ):
        aliases.add("whistleblower_cases")

    if "training" in field_haystack and any(token in field_haystack for token in ("hour", "hours")):
        aliases.add("training_hours")

    if "ltifr" in field_haystack or (
        any(token in field_haystack for token in ("injury", "injuries", "lost_time"))
        and any(token in field_haystack for token in ("rate", "frequency"))
    ):
        aliases.add("lost_time_injury_rate_raw")

    if "hours_worked" in field_haystack or (any(token in field_haystack for token in ("hours", "hour")) and "worked" in field_haystack):
        aliases.add("hours_worked")

    if unit_key in {"kgco2e", "tco2e"} and "scope2" in field_haystack:
        aliases.add("scope2_kgco2e" if unit_key == "kgco2e" else "scope2_tco2e")
    if unit_key in {"kgco2e", "tco2e"} and "scope1" in field_haystack:
        aliases.add("scope1_kgco2e" if unit_key == "kgco2e" else "scope1_tco2e")

    return aliases


def _field_aliases(field_path: str, unit: str | None, template_name: str | None, include_raw: bool = True) -> set[str]:
    aliases: set[str] = set()
    unit_key = _normalize_unit(unit)
    field_key = field_path.split(".")[-1]
    template_key = _normalize_key(template_name or "")
    haystack = f"{template_key}_{field_key}".strip("_")

    if include_raw and field_key and field_key not in GENERIC_FIELD_NAMES:
        aliases.add(field_key)
    if include_raw and template_key and field_key and field_key not in GENERIC_FIELD_NAMES:
        aliases.add(f"{template_key}_{field_key}")

    electricity_tokens = ("electric", "electricity", "power", "strom", "verbrauch", "zahlerstand", "winema", "transfer")
    gas_tokens = ("gas", "erdgas", "natural_gas")
    fuel_tokens = ("fuel", "diesel", "petrol", "gasoline", "lpg")
    water_tokens = ("water", "wasser", "m3", "cubic")
    waste_tokens = ("waste", "abfall", "mull", "kg", "tonne")
    employee_tokens = ("employee", "employees", "headcount", "workforce", "fte")
    board_tokens = ("board", "independence", "independent")
    whistle_tokens = ("whistle", "hotline", "ethic")
    training_tokens = ("training", "learning")
    safety_tokens = ("injury", "lost_time", "ltifr", "safety")
    co2_tokens = ("co2", "emissions", "carbon", "greenhouse")

    if any(token in haystack for token in electricity_tokens):
        if unit_key in {"kwh", "mwh"}:
            aliases.add("electricity_kwh" if unit_key == "kwh" else "electricity_mwh")
            if "winema" in haystack:
                aliases.add("electricity_kwh_winema")
            elif "transfer" in haystack:
                aliases.add("electricity_kwh_transfer")
        aliases.add("electricity_consumption")

    if any(token in haystack for token in co2_tokens):
        if "scope2" in haystack or any(token in haystack for token in electricity_tokens):
            aliases.add("scope2_kgco2e" if unit_key != "tco2e" else "scope2_tco2e")
        elif "scope1" in haystack or any(token in haystack for token in fuel_tokens + gas_tokens):
            aliases.add("scope1_kgco2e" if unit_key != "tco2e" else "scope1_tco2e")
        else:
            aliases.add("total_ghg_kgco2e")
    if any(token in haystack for token in gas_tokens):
        if unit_key == "kwh":
            aliases.add("gas_kwh")
        aliases.add("natural_gas")
    if any(token in haystack for token in fuel_tokens):
        aliases.add("fuel_litres")
        if "diesel" in haystack:
            aliases.add("diesel_litres")
        if "petrol" in haystack or "gasoline" in haystack:
            aliases.add("petrol_litres")
        if "lpg" in haystack:
            aliases.add("lpg_litres")
    if any(token in haystack for token in water_tokens):
        aliases.add("water_consumption")
    if any(token in haystack for token in waste_tokens):
        aliases.add("waste_generated")
    if any(token in haystack for token in employee_tokens):
        aliases.add("headcount")
    if any(token in haystack for token in board_tokens):
        aliases.add("board_independence_pct")
    if any(token in haystack for token in whistle_tokens):
        aliases.add("whistleblower_cases")
    if any(token in haystack for token in training_tokens):
        aliases.add("training_hours")
    if any(token in haystack for token in safety_tokens):
        aliases.add("lost_time_injury_rate_raw")
        aliases.add("hours_worked")

    if unit_key in {"kgco2e", "tco2e"} and "scope2" in haystack:
        aliases.add("scope2_kgco2e" if unit_key == "kgco2e" else "scope2_tco2e")
    if unit_key in {"kgco2e", "tco2e"} and "scope1" in haystack:
        aliases.add("scope1_kgco2e" if unit_key == "kgco2e" else "scope1_tco2e")

    return {alias for alias in aliases if alias}


def _field_catalog(gold_records: dict[str, Any]) -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}
    for record in gold_records.values():
        for key, field in record.get("fields", {}).items():
            item = catalog.setdefault(
                key,
                {
                    "key": key,
                    "unit": field.get("unit"),
                    "records": [],
                },
            )
            if not item["unit"] and field.get("unit"):
                item["unit"] = field.get("unit")
            label = record.get("label") or "record"
            if label not in item["records"]:
                item["records"].append(label)
    return catalog


def _matching_entries(gold_records: dict[str, Any], key: str) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for record in gold_records.values():
        field = record.get("fields", {}).get(key)
        if field and field.get("value") is not None:
            matches.append(field)
    return matches


def _sum_key(gold_records: dict[str, Any], key: str) -> float:
    matches = _matching_entries(gold_records, key)
    if not matches:
        raise KeyError(f"Key '{key}' not found in gold records")
    return sum(float(match["value"]) for match in matches)


def _first_key_value(gold_records: dict[str, Any], key: str) -> float:
    matches = _matching_entries(gold_records, key)
    if not matches:
        raise KeyError(f"Key '{key}' not found in gold records")
    return float(matches[0]["value"])


def _field_unit(gold_records: dict[str, Any], key: str) -> str | None:
    matches = _matching_entries(gold_records, key)
    if not matches:
        return None
    return matches[0].get("unit")


def _score_field(key: str, unit: str | None, include_terms: tuple[str, ...], preferred_unit: str | None) -> int:
    haystack = f"{key} {_normalize_unit(unit)}"
    score = 0
    for term in include_terms:
        if term in haystack:
            score += 3
    if preferred_unit and _normalize_unit(unit) == _normalize_unit(preferred_unit):
        score += 2
    if key in GENERIC_FIELD_NAMES:
        score -= 5
    return score


def _find_best_field(
    gold_records: dict[str, Any],
    include_terms: tuple[str, ...],
    preferred_unit: str | None = None,
) -> str | None:
    catalog = _field_catalog(gold_records)
    scored = [
        (key, _score_field(key, data.get("unit"), include_terms, preferred_unit))
        for key, data in catalog.items()
    ]
    scored = [item for item in scored if item[1] > 0]
    if not scored:
        return None
    scored.sort(key=lambda item: (-item[1], item[0]))
    return scored[0][0]


def _default_grid_factor(gold_records: dict[str, Any]) -> str:
    hints = " ".join(
        f"{record.get('label', '')} {record.get('template_name', '')}"
        for record in gold_records.values()
    ).lower()
    if any(token in hints for token in ("uk", "britain", "london", "england", "scotland", "wales")):
        return "electricity_grid_uk"
    if any(token in hints for token in ("de", "deutsch", "german", "germany", "strom", "berlin", "munich")):
        return "electricity_grid_de"
    return "electricity_grid_eu_avg"


def _default_emission_factor(metric_key: str, source_key: str, gold_records: dict[str, Any]) -> str | None:
    haystack = f"{metric_key} {source_key}".lower()
    if "electric" in haystack or "scope2" in haystack:
        return _default_grid_factor(gold_records)
    if "gas" in haystack:
        return "natural_gas"
    if "diesel" in haystack:
        return "diesel_combustion"
    if "petrol" in haystack or "gasoline" in haystack:
        return "petrol_combustion"
    if "lpg" in haystack:
        return "lpg_combustion"
    if "fuel" in haystack:
        return "diesel_combustion"
    return None
