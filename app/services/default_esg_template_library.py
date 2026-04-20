"""
Default ESG evidence template library.

This module provides source-backed baseline templates so users do not need to
manually templatize common ESG evidence documents each time.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.agentic.template.generation import build_compact_system_prompt


def _template(
    *,
    key: str,
    name: str,
    measurement_type: str,
    output_unit: str | None,
    schema_definition: dict[str, str],
    target_metrics_nlp: str,
    evidence_required: list[str],
    standards_basis: list[str],
) -> dict[str, Any]:
    return {
        "key": key,
        "name": name,
        "measurement_type": measurement_type,
        "output_unit": output_unit,
        "schema_definition": schema_definition,
        "target_metrics_nlp": target_metrics_nlp,
        "evidence_required": evidence_required,
        "standards_basis": standards_basis,
    }


DEFAULT_ESG_TEMPLATE_LIBRARY: list[dict[str, Any]] = [
    _template(
        key="scope2_electricity",
        name="ESG Evidence - Scope 2 Electricity",
        measurement_type="electricity_kwh",
        output_unit="kWh",
        schema_definition={
            "reporting_period_start": "date",
            "reporting_period_end": "date",
            "facility_name": "string",
            "country": "string",
            "supplier_name": "string",
            "value": "float",
            "unit": "string",
            "meter_id": "string",
            "invoice_number": "string",
            "evidence_doc_type": "string",
        },
        target_metrics_nlp="Calculate purchased electricity activity data for Scope 2 emissions, preserving supplier and location evidence.",
        evidence_required=["Utility invoice", "Meter reading export", "Supplier contract/tariff"],
        standards_basis=["GHG Protocol Corporate Standard", "IFRS S2", "ESRS E1"],
    ),
    _template(
        key="scope1_stationary_mobile_fuel",
        name="ESG Evidence - Scope 1 Fuel Combustion",
        measurement_type="fuel_litres",
        output_unit="litres",
        schema_definition={
            "reporting_period_start": "date",
            "reporting_period_end": "date",
            "facility_or_fleet": "string",
            "fuel_type": "string",
            "value": "float",
            "unit": "string",
            "supplier_name": "string",
            "invoice_number": "string",
            "evidence_doc_type": "string",
        },
        target_metrics_nlp="Calculate direct fuel combustion activity data for Scope 1 and retain auditable source references.",
        evidence_required=["Fuel purchase invoice", "Fuel card statement", "Tank log or meter reading"],
        standards_basis=["GHG Protocol Corporate Standard", "GRI 305", "ESRS E1"],
    ),
    _template(
        key="scope1_refrigerants",
        name="ESG Evidence - Scope 1 Refrigerants",
        measurement_type="generic",
        output_unit="kg",
        schema_definition={
            "reporting_period_start": "date",
            "reporting_period_end": "date",
            "facility_name": "string",
            "refrigerant_type": "string",
            "value": "float",
            "unit": "string",
            "leakage_event": "string",
            "maintenance_vendor": "string",
            "evidence_doc_type": "string",
        },
        target_metrics_nlp="Capture refrigerant top-up and leakage quantities for Scope 1 fugitive emissions calculations.",
        evidence_required=["HVAC maintenance logs", "Gas cylinder purchase records", "Leak test reports"],
        standards_basis=["GHG Protocol Corporate Standard", "IFRS S2", "ESRS E1"],
    ),
    _template(
        key="scope3_business_travel",
        name="ESG Evidence - Scope 3 Business Travel",
        measurement_type="generic",
        output_unit="km",
        schema_definition={
            "reporting_period_start": "date",
            "reporting_period_end": "date",
            "employee_or_department": "string",
            "travel_mode": "string",
            "value": "float",
            "unit": "string",
            "route_or_region": "string",
            "booking_provider": "string",
            "evidence_doc_type": "string",
        },
        target_metrics_nlp="Aggregate business travel activity data by mode and distance for Scope 3 category reporting.",
        evidence_required=["Travel agency export", "Expense claim with receipts", "Corporate card statement"],
        standards_basis=["GHG Protocol Scope 3 Standard", "IFRS S2", "ESRS E1"],
    ),
    _template(
        key="scope3_waste",
        name="ESG Evidence - Scope 3 Waste Generated",
        measurement_type="waste_kg",
        output_unit="kg",
        schema_definition={
            "reporting_period_start": "date",
            "reporting_period_end": "date",
            "facility_name": "string",
            "waste_stream": "string",
            "treatment_method": "string",
            "value": "float",
            "unit": "string",
            "waste_vendor": "string",
            "evidence_doc_type": "string",
        },
        target_metrics_nlp="Capture waste quantities and treatment pathways for Scope 3 and waste performance tracking.",
        evidence_required=["Waste manifest", "Hauler invoice", "Weighbridge tickets"],
        standards_basis=["GHG Protocol Scope 3 Standard", "GRI 306", "ESRS E5"],
    ),
    _template(
        key="water_withdrawal_discharge",
        name="ESG Evidence - Water Withdrawal and Discharge",
        measurement_type="water_m3",
        output_unit="m3",
        schema_definition={
            "reporting_period_start": "date",
            "reporting_period_end": "date",
            "facility_name": "string",
            "source_type": "string",
            "discharge_destination": "string",
            "value": "float",
            "unit": "string",
            "supplier_or_utility": "string",
            "evidence_doc_type": "string",
        },
        target_metrics_nlp="Track water withdrawal and discharge volumes by source and destination for water stewardship reporting.",
        evidence_required=["Water bill", "Extraction permit and meter logs", "Discharge lab/permit reports"],
        standards_basis=["GRI 303", "ESRS E3"],
    ),
    _template(
        key="workforce_headcount_diversity",
        name="ESG Evidence - Workforce and Diversity",
        measurement_type="generic",
        output_unit=None,
        schema_definition={
            "reporting_period_start": "date",
            "reporting_period_end": "date",
            "entity_or_region": "string",
            "employee_count": "int",
            "gender_breakdown": "string",
            "employment_type_breakdown": "string",
            "turnover_rate_pct": "float",
            "evidence_doc_type": "string",
        },
        target_metrics_nlp="Capture own-workforce demographic and employment composition evidence for social disclosures.",
        evidence_required=["HRIS export", "Payroll register", "Organization structure report"],
        standards_basis=["GRI 2/401/405", "ESRS S1"],
    ),
    _template(
        key="health_safety_incidents",
        name="ESG Evidence - Health and Safety Incidents",
        measurement_type="generic",
        output_unit=None,
        schema_definition={
            "reporting_period_start": "date",
            "reporting_period_end": "date",
            "site_or_operation": "string",
            "incident_count": "int",
            "lost_time_injuries": "int",
            "fatalities": "int",
            "contractor_included": "bool",
            "evidence_doc_type": "string",
        },
        target_metrics_nlp="Capture occupational health and safety incident counts and severity indicators with clear population boundaries.",
        evidence_required=["Incident register", "EHS system export", "Regulatory incident filings"],
        standards_basis=["GRI 403", "ESRS S1"],
    ),
    _template(
        key="board_governance_oversight",
        name="ESG Evidence - Board Governance and Oversight",
        measurement_type="generic",
        output_unit=None,
        schema_definition={
            "reporting_period_start": "date",
            "reporting_period_end": "date",
            "board_committee_name": "string",
            "esg_oversight_mandate": "string",
            "meeting_count": "int",
            "exec_pay_linked_to_esg": "bool",
            "evidence_doc_type": "string",
        },
        target_metrics_nlp="Capture governance evidence for board-level ESG oversight, accountability, and incentives.",
        evidence_required=["Board charter", "Committee minutes", "Remuneration policy"],
        standards_basis=["IFRS S1/S2 Governance", "ESRS 2 GOV"],
    ),
    _template(
        key="assurance_and_methodology",
        name="ESG Evidence - Assurance and Methodology",
        measurement_type="generic",
        output_unit=None,
        schema_definition={
            "reporting_period_start": "date",
            "reporting_period_end": "date",
            "assurance_provider": "string",
            "assurance_standard": "string",
            "assurance_level": "string",
            "scope_of_assurance": "string",
            "methodology_reference": "string",
            "evidence_doc_type": "string",
        },
        target_metrics_nlp="Capture assurance scope, criteria, and methodology references to strengthen auditability and controls.",
        evidence_required=["Independent assurance statement", "Methodology memo", "Control narrative"],
        standards_basis=["ISAE 3000", "ISO 14064-3", "ESRS 2"],
    ),
]


def list_default_templates() -> list[dict[str, Any]]:
    """Returns a deep copy of the default ESG template library."""
    return deepcopy(DEFAULT_ESG_TEMPLATE_LIBRARY)


def build_template_create_payload(template: dict[str, Any], workspace_id: str | None) -> dict[str, Any]:
    """Converts a library item into a SchemaTemplate creation payload."""
    schema_definition = dict(template["schema_definition"])
    return {
        "name": str(template["name"]),
        "workspace_id": workspace_id,
        "schema_definition": schema_definition,
        "system_prompt": build_compact_system_prompt(
            template_name=str(template["name"]),
            schema_definition=schema_definition,
            target_metrics_nlp=str(template.get("target_metrics_nlp") or ""),
            measurement_type=str(template.get("measurement_type") or "generic"),
            output_unit=str(template["output_unit"]) if template.get("output_unit") else None,
        ),
        "target_metrics_nlp": str(template.get("target_metrics_nlp") or ""),
    }
