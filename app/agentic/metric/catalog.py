"""Catalog and factor loading for the metric agent."""

from __future__ import annotations

import json
from typing import Any

from pymongo import MongoClient

from .constants import DATA_DIR


def _get_sync_db():
    from app.config import get_settings

    settings = get_settings()
    client = MongoClient(settings.MONGODB_CONNECTION_STRING)
    return client[settings.MONGODB_DATABASE_NAME]


def _load_metric_definitions(company_id: str | None = None) -> dict[str, Any]:
    db = _get_sync_db()

    if db.metric_definitions.count_documents({"company_id": None}) == 0:
        path = DATA_DIR / "metric_definitions.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        docs = []
        for key, val in raw.items():
            docs.append(
                {
                    "key": key,
                    "company_id": None,
                    "description": val.get("description", key),
                    "pillar": val.get("pillar", "environmental"),
                    "unit": val.get("unit", "value"),
                    "suggested_tool": val.get("suggested_tool", "direct_read"),
                    "tags": val.get("tags", []),
                }
            )
        if docs:
            db.metric_definitions.insert_many(docs)

    definitions = {}
    for doc in db.metric_definitions.find({"$or": [{"company_id": None}, {"company_id": company_id}]}):
        definitions[doc["key"]] = doc
    return definitions


def _load_emission_factors(company_id: str | None = None) -> dict[str, Any]:
    db = _get_sync_db()

    if db.emission_factors.count_documents({"company_id": None}) == 0:
        path = DATA_DIR / "emission_factors.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        docs = []
        for key, val in raw.get("factors", {}).items():
            docs.append(
                {
                    "key": key,
                    "company_id": None,
                    "value": float(val["value"]),
                    "unit": val["unit"],
                    "source": val["source"],
                    "scope": int(val["scope"]),
                    "region": val.get("region"),
                    "year": val.get("year"),
                    "unit_basis": val.get("unit_basis"),
                    "status": "active",
                    "version": raw.get("version", "dynamic"),
                }
            )
        if docs:
            db.emission_factors.insert_many(docs)

    factors = {}
    for doc in db.emission_factors.find({"$or": [{"company_id": None}, {"company_id": company_id}]}):
        factors[doc["key"]] = doc
    return {"version": "dynamic", "factors": factors}


def resolve_emission_factor(
    *,
    company_id: str | None,
    factor_key: str,
    region: str | None = None,
    year: int | None = None,
    allow_global_fallback: bool = True,
) -> dict[str, Any]:
    payload = _load_emission_factors(company_id)
    factors = payload.get("factors", {})
    quality_flags: list[str] = []

    # Priority 1/2: explicit key resolution (company overrides already win by key map overwrite).
    direct = factors.get(factor_key)
    if direct:
        return {
            "factor": direct,
            "factor_key": factor_key,
            "quality_flags": quality_flags,
            "used_fallback_factor": False,
        }

    normalized_region = (region or "").strip().lower()
    # Priority 3/4 fallback: scope 2 regional grid substitutions.
    if factor_key.startswith("electricity_grid"):
        regional_candidates: list[str] = []
        if normalized_region in {"de", "germany"}:
            regional_candidates.append("electricity_grid_de")
        if normalized_region in {"uk", "gb", "great_britain", "united_kingdom"}:
            regional_candidates.append("electricity_grid_uk")
        regional_candidates.append("electricity_grid_eu_avg")

        for candidate in regional_candidates:
            factor = factors.get(candidate)
            if factor:
                quality_flags.append("used_fallback_factor")
                if year is not None and factor.get("year") not in (None, year):
                    quality_flags.append("year_mismatch_fallback")
                return {
                    "factor": factor,
                    "factor_key": candidate,
                    "quality_flags": quality_flags,
                    "used_fallback_factor": True,
                }

    if allow_global_fallback:
        for candidate in ("electricity_grid_eu_avg", "natural_gas", "diesel_combustion"):
            factor = factors.get(candidate)
            if factor:
                quality_flags.append("used_fallback_factor")
                return {
                    "factor": factor,
                    "factor_key": candidate,
                    "quality_flags": quality_flags,
                    "used_fallback_factor": True,
                }

    raise KeyError(f"Emission factor '{factor_key}' not found")


def list_metric_definitions(company_id: str | None = None) -> list[dict[str, Any]]:
    definitions = _load_metric_definitions(company_id)
    items = [
        {
            "key": key,
            "description": value.get("description", key),
            "pillar": value.get("pillar", "environmental"),
            "unit": value.get("unit", "value"),
            "suggested_tool": value.get("suggested_tool"),
            "tags": value.get("tags", []),
        }
        for key, value in definitions.items()
    ]
    return sorted(items, key=lambda item: (item["pillar"], item["key"]))
