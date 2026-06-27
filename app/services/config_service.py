"""
Runtime config service.

Policy/business configuration that used to live as literals in code now lives
here, addressable by (namespace, key). Defaults are defined in-process so the
system behaves identically to before until an admin overrides a value — and so
pure/sync code (e.g. the scoring engine) and unit tests can read config without
any DB round-trip.

Lifecycle:
  * Import time → cache seeded from DEFAULTS (always available, test-safe).
  * App startup → `await load_from_db()` overlays admin overrides from Mongo.
  * Admin edit → `await set_value(...)` writes Mongo + updates the cache.

Secrets/deployment values are NOT stored here — those remain in `.env`/Settings.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, Optional

_DATA_DIR = Path(__file__).parent.parent / "data"


def _load_json(name: str) -> Any:
    return json.loads((_DATA_DIR / name).read_text(encoding="utf-8"))


def _build_defaults() -> Dict[str, Dict[str, Any]]:
    """Seed defaults — the single source of truth for out-of-the-box behaviour."""
    sector_benchmarks = _load_json("sector_benchmarks.json")
    vsme_questions = _load_json("vsme_questions.json")

    return {
        # ---- Scoring rubric (was hardcoded in esg_score_service) -------------
        "scoring.rubric": {
            "pillar_weights": {"environmental": 0.40, "social": 0.30, "governance": 0.30},
            "environmental_weights": {"carbon_intensity": 0.45, "renewable": 0.30, "recycling": 0.25},
            "social_weights": {"min_wage": 0.35, "gender": 0.30, "safety": 0.35},
            "governance_weight_each": 0.20,
            "safety_anchors": [[0, 100], [1, 70], [3, 40], [8, 0]],
            "gender_balance_center": 45,
            "gender_balance_slope": 2.5,
            "trust_penalties": {"critical": 25, "warn": 10, "info": 3},
            "trust_mix": {"confidence": 0.5, "plausibility": 0.5},
            "provisional_completeness_below": 50,
            "carbon_outlier_ratio": 5,
            "extreme_per_capita_tco2e": 1000,
            # EU averages for the energy-based GHG plausibility cross-check
            "elec_kgco2e_per_kwh": 0.276,
            "diesel_kgco2e_per_litre": 2.68784,
        },
        # ---- Sector benchmarks (was sector_benchmarks.json) -----------------
        "scoring.sector_benchmarks": sector_benchmarks,
        # ---- Default interview blueprint seed (the VSME-15) ------------------
        "interview.default_blueprint": {"questions": vsme_questions},
        # ---- Grounding corpus for AI question generation --------------------
        "interview.grounding": {
            "sources": [
                {
                    "id": "efrag-vsme",
                    "label": "EFRAG VSME (Voluntary SME) standard — Module A basic disclosures",
                    "type": "framework",
                    "text": (
                        "The EFRAG Voluntary SME standard (VSME) defines basic ESG disclosures "
                        "for non-listed micro-, small- and medium-sized undertakings: energy & "
                        "GHG emissions (Scope 1/2), pollution, water, biodiversity, resource use & "
                        "waste, workforce (headcount, diversity, pay, health & safety), and business "
                        "conduct/governance. Questions must map to these disclosure areas and stay "
                        "proportionate to an MSME's capacity."
                    ),
                },
                {
                    "id": "esrs-catalog",
                    "label": "ESRS disclosure catalogue",
                    "type": "framework_ref",
                    "data_file": "esrs_catalog.json",
                },
            ],
        },
        # ---- AI generation policy/prompt/params -----------------------------
        "interview.generation": {
            "model": None,            # None → use DEFAULT_LLM_MODEL
            "temperature": 0.2,
            "max_questions": 25,
            "require_metric_binding": True,
            "system_prompt": (
                "You are an ESG reporting specialist designing a proportionate, standard-grounded "
                "interview for an MSME so a bank can assess its sustainability. Tailor questions to "
                "the company profile and sector. Every question MUST bind to a canonical metric_code "
                "from the provided catalogue; if a needed metric is missing, propose a new one and "
                "flag it. Ground every question in a provided source. Never invent regulatory "
                "requirements. Keep language plain and answerable by a non-expert."
            ),
        },
        # ---- Company profile intake field definitions (tabs) ----------------
        "company_profile.fields": {
            "sections": [
                {
                    "id": "identity",
                    "label": "Company identity",
                    "fields": [
                        {"key": "legal_name", "label": "Registered legal name", "type": "text", "required": True},
                        {"key": "country", "label": "Country of registration", "type": "text", "required": True},
                        {"key": "registration_no", "label": "Company registration number", "type": "text", "required": False},
                        {"key": "website", "label": "Website", "type": "text", "required": False},
                    ],
                },
                {
                    "id": "classification",
                    "label": "Business classification",
                    "fields": [
                        {"key": "nace_sector", "label": "Industry sector (NACE)", "type": "select", "required": True,
                         "options": [
                             {"value": "A", "label": "Agriculture, Forestry & Fishing"},
                             {"value": "B", "label": "Mining & Quarrying"},
                             {"value": "C", "label": "Manufacturing"},
                             {"value": "D", "label": "Electricity, Gas & Steam"},
                             {"value": "E", "label": "Water Supply, Sewerage & Waste"},
                             {"value": "F", "label": "Construction"},
                             {"value": "G", "label": "Wholesale & Retail Trade"},
                             {"value": "H", "label": "Transport & Storage"},
                             {"value": "I", "label": "Accommodation & Food Service"},
                             {"value": "J", "label": "Information & Communication"},
                             {"value": "K", "label": "Financial & Insurance"},
                             {"value": "L", "label": "Real Estate"},
                             {"value": "M", "label": "Professional, Scientific & Technical"},
                             {"value": "N", "label": "Administrative & Support"},
                             {"value": "Q", "label": "Human Health & Social Work"},
                             {"value": "OTHER", "label": "Other"},
                         ]},
                        {"key": "employee_count_range", "label": "Number of employees", "type": "select", "required": True,
                         "options": [
                             {"value": "1-9", "label": "1 – 9"},
                             {"value": "10-49", "label": "10 – 49"},
                             {"value": "50-249", "label": "50 – 249"},
                             {"value": "250-499", "label": "250 – 499"},
                             {"value": "500+", "label": "500+"},
                         ]},
                        {"key": "turnover_range_eur", "label": "Annual turnover", "type": "select", "required": True,
                         "options": [
                             {"value": "<2M", "label": "Under €2M"},
                             {"value": "2M-10M", "label": "€2M – €10M"},
                             {"value": "10M-40M", "label": "€10M – €40M"},
                             {"value": "40M-150M", "label": "€40M – €150M"},
                             {"value": "150M+", "label": "Over €150M"},
                         ]},
                        {"key": "is_listed", "label": "Publicly listed?", "type": "boolean", "required": False},
                    ],
                },
                {
                    "id": "reporting",
                    "label": "Reporting context",
                    "fields": [
                        {"key": "reporting_framework", "label": "Target framework", "type": "select", "required": False,
                         "options": [
                             {"value": "vsme", "label": "EFRAG VSME"},
                             {"value": "csrd", "label": "CSRD / ESRS"},
                             {"value": "gri", "label": "GRI"},
                         ]},
                        {"key": "primary_contact_name", "label": "Sustainability contact name", "type": "text", "required": False},
                        {"key": "primary_contact_email", "label": "Sustainability contact email", "type": "text", "required": False},
                    ],
                },
            ],
        },
        # ---- Extraction thresholds (mirrors Settings defaults) --------------
        "extraction.thresholds": {
            "confidence_threshold": 0.90,
            "auto_approve_min_confidence": 0.85,
        },
        # ---- Auto-fill bridge: VSME interview metric_code -> engine/extraction
        # codes + unit, so values extracted from uploaded documents populate the
        # matching interview question. `domain` selects the unit converter.
        "interview.metric_aliases": {
            "ENERGY_ELEC_CONSUMPTION": {"codes": ["electricity_kwh_total"], "unit": "kWh", "domain": "kwh"},
            "ENERGY_FUEL_CONSUMPTION": {"codes": ["fuel_litres_total"], "unit": "litres", "domain": "litres"},
            "GHG_TOTAL_EMISSIONS": {"codes": ["total_ghg_tco2e", "scope2_tco2e", "scope1_tco2e"], "unit": "tCO2e", "domain": "tco2e"},
            "WATER_TOTAL_CONSUMPTION": {"codes": ["water_consumption_m3_total"], "unit": "m3", "domain": "m3"},
            "WORKFORCE_TOTAL_FTE": {"codes": ["headcount"], "unit": "FTE", "domain": "count"},
        },
    }


# In-process cache, seeded from defaults at import (always available / test-safe).
_cache: Dict[str, Dict[str, Any]] = _build_defaults()


def get(namespace: str, key: Optional[str] = None, default: Any = None) -> Any:
    """Synchronous read returning a deep copy — safe for callers that may mutate.

    Returns the whole namespace dict when `key` is None, else the value for `key`.
    """
    ns = _cache.get(namespace, {})
    if key is None:
        return copy.deepcopy(ns)
    return copy.deepcopy(ns.get(key, default))


def peek(namespace: str, key: Optional[str] = None, default: Any = None) -> Any:
    """Non-copying read for trusted read-only hot paths (e.g. the scoring engine).

    Returns live references — callers MUST NOT mutate the result.
    """
    ns = _cache.get(namespace, {})
    if key is None:
        return ns
    return ns.get(key, default)


def all_namespaces() -> Dict[str, Dict[str, Any]]:
    return copy.deepcopy(_cache)


async def load_from_db() -> None:
    """Overlay admin overrides from Mongo onto the in-memory cache.

    Tolerant of a not-yet-initialised DB (defaults stay in effect), but logs real
    errors so a genuine query/schema bug is not silently mistaken for 'no overrides'.
    """
    try:
        from app.models.app_config import AppConfig
        docs = await AppConfig.find_all().to_list()
    except Exception as exc:  # DB unreachable / Beanie not initialised
        import structlog
        structlog.get_logger().warning("config_load_skipped", error=str(exc))
        return
    for doc in docs:
        _cache.setdefault(doc.namespace, {})
        _cache[doc.namespace][doc.key] = doc.value


async def set_value(namespace: str, key: str, value: Any, updated_by: Optional[str] = None) -> None:
    """Upsert a single config value (DB + cache)."""
    from app.models.app_config import AppConfig

    existing = await AppConfig.find_one(AppConfig.namespace == namespace, AppConfig.key == key)
    if existing:
        existing.value = value
        existing.updated_by = updated_by
        await existing.save_with_timestamp()
    else:
        await AppConfig(namespace=namespace, key=key, value=value, updated_by=updated_by).insert()
    _cache.setdefault(namespace, {})
    _cache[namespace][key] = value


async def set_namespace(namespace: str, values: Dict[str, Any], updated_by: Optional[str] = None) -> None:
    """Bulk upsert every key in a namespace."""
    for key, value in values.items():
        await set_value(namespace, key, value, updated_by)


def reset_cache_for_tests() -> None:
    """Restore pristine defaults — used by tests to isolate config edits."""
    global _cache
    _cache = _build_defaults()
