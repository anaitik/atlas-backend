from types import SimpleNamespace

import pytest

from app.services import metric_agent_service, report_service


def test_parse_json_response_handles_fenced_payloads():
    raw = """
    ```json
    {"tool_name": "direct_read", "arguments": {"source_key": "headcount", "unit": "employees"}}
    ```
    """

    parsed = metric_agent_service._parse_json_response(raw)

    assert parsed["tool_name"] == "direct_read"
    assert parsed["arguments"]["source_key"] == "headcount"


def test_field_aliases_map_generic_value_from_template_name():
    aliases = metric_agent_service._field_aliases(
        "value",
        "kWh",
        "German Electricity Invoice - WINEMA Transfer Machines",
    )

    assert "electricity_kwh" in aliases
    assert "electricity_consumption" in aliases


def test_aggregate_period_sums_repeated_record_values():
    gold_records = {
        "ex-1": {"fields": {"electricity_kwh": {"value": 125.5, "unit": "kWh"}}},
        "ex-2": {"fields": {"electricity_kwh": {"value": 98.25, "unit": "kWh"}}},
    }

    record = metric_agent_service._run_tool(
        "aggregate_period",
        gold_records,
        "electricity_kwh_total",
        {"source_keys": ["electricity_kwh"], "operation": "sum", "unit": "kWh"},
    )

    assert record["value"] == 223.75
    assert record["status"] == "OK"


def test_select_metrics_prefers_agent_outputs_when_present():
    metrics = [
        SimpleNamespace(metric_code="scope2_kgco2e", status="approved", metadata={"source_type": "extraction_sync"}),
        SimpleNamespace(metric_code="scope2_kgco2e", status="approved", metadata={"source_type": "metric_agent"}),
        SimpleNamespace(metric_code="headcount", status="approved", metadata={"source_type": "extraction_sync"}),
        SimpleNamespace(metric_code="training_hours_per_employee", status="manual_required", metadata={"source_type": "metric_agent"}),
    ]

    selected = report_service._select_metrics(metrics)

    assert len(selected) == 2
    assert selected[0].metadata["source_type"] == "metric_agent"
    assert selected[0].metric_code == "scope2_kgco2e"
    assert selected[1].metric_code == "headcount"


class FakeQuery:
    def __init__(self, items):
        self.items = items

    async def to_list(self):
        return list(self.items)


@pytest.mark.asyncio
async def test_recommend_metric_targets_uses_json_structure_without_values(monkeypatch):
    extractions = [
        SimpleNamespace(
            template_id="tpl-electricity",
            payload={
                "value": "redacted",
                "unit": "kWh",
            },
            document_id="doc-1",
        ),
        SimpleNamespace(
            template_id="tpl-headcount",
            payload={
                "employee_count": "hidden",
            },
            document_id="doc-2",
        ),
    ]

    templates = [
        SimpleNamespace(id="tpl-electricity", name="Electricity Invoice"),
        SimpleNamespace(id="tpl-headcount", name="Employee Register"),
    ]

    template_map = {template.id: template for template in templates}
    async def fake_get(template_id):
        return template_map.get(template_id)
    monkeypatch.setattr(metric_agent_service.SchemaTemplate, "get", fake_get)
    monkeypatch.setattr(metric_agent_service, "create_llm", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("llm offline")))

    recommendation = await metric_agent_service.recommend_metric_targets_for_extractions(extractions)

    assert "electricity_kwh_total" in recommendation["metric_targets"]
    assert "headcount" in recommendation["metric_targets"]
    assert recommendation["explanation"].startswith("Recommended from approved extraction structure only")


@pytest.mark.asyncio
async def test_recommend_metric_targets_does_not_infer_headcount_from_non_numeric_employee_fields(monkeypatch):
    extractions = [
        SimpleNamespace(
            template_id="tpl-employee-register",
            payload={
                "employee_name": "redacted",
                "department": "operations",
            },
            document_id="doc-1",
        ),
    ]
    templates = [
        SimpleNamespace(id="tpl-employee-register", name="Employee Register"),
    ]

    template_map = {template.id: template for template in templates}
    async def fake_get(template_id):
        return template_map.get(template_id)
    monkeypatch.setattr(metric_agent_service.SchemaTemplate, "get", fake_get)

    recommendation = await metric_agent_service.recommend_metric_targets_for_extractions(extractions)

    assert recommendation["metric_targets"] == []


@pytest.mark.asyncio
async def test_recommend_metric_targets_limits_llm_choices_to_allowed_targets(monkeypatch):
    extractions = [
        SimpleNamespace(
            template_id="tpl-electricity",
            payload={
                "value": "hidden",
                "unit": "kWh",
            },
            document_id="doc-1",
        ),
    ]
    templates = [
        SimpleNamespace(id="tpl-electricity", name="Electricity Invoice"),
    ]

    class FakeLlm:
        async def ainvoke(self, messages):
            return '{"metric_targets": ["lost_time_injury_rate", "electricity_kwh_total", "scope2_kgco2e"]}'

    template_map = {template.id: template for template in templates}
    async def fake_get(template_id):
        return template_map.get(template_id)
    monkeypatch.setattr(metric_agent_service.SchemaTemplate, "get", fake_get)
    monkeypatch.setattr(metric_agent_service, "create_llm", lambda **kwargs: FakeLlm())

    recommendation = await metric_agent_service.recommend_metric_targets_for_extractions(extractions)

    assert recommendation["metric_targets"] == ["electricity_kwh_total", "scope2_kgco2e", "scope2_tco2e"]


def test_default_metric_targets_from_keys_falls_back_to_small_core_set():
    targets = metric_agent_service._default_metric_targets_from_keys(set())

    assert targets == []


def test_friendly_metric_error_hides_internal_argument_names():
    message = metric_agent_service._friendly_metric_error("headcount", "'source_key'")

    assert "source_key" not in message
    assert "No matching source field" in message
