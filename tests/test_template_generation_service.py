from app.services import template_generation_service


def test_parse_generation_response_accepts_fenced_json():
    raw = """```json
    {
      "template": {
        "template_id": "utility_bill",
        "label": "Utility Bill",
        "measurement_type": "electricity_kwh",
        "output_unit": "kWh",
        "fields": [
          {"key": "value", "label": "Consumption", "type": "float", "required": true}
        ]
      },
      "rules": {
        "normalize_units": {
          "description": "Convert MWh to kWh",
          "rule": "Multiply by 1000 when the bill reports MWh."
        }
      }
    }
    ```"""

    template, rules = template_generation_service.parse_generation_response(raw)

    assert template["template_id"] == "utility_bill"
    assert "normalize_units" in rules


def test_validate_and_normalize_generated_template():
    template = {
        "template_id": "utility_bill",
        "label": "Utility Bill",
        "measurement_type": "electricity_kwh",
        "output_unit": "kWh",
        "document_types": ["pdf"],
        "fields": [
            {
                "key": "value",
                "label": "Consumption",
                "type": "float",
                "unit": "kWh",
                "required": True,
                "hint": "Use the billed electricity consumption figure.",
            },
            {
                "key": "period_start",
                "label": "Period Start",
                "type": "date",
                "required": True,
                "hint": "Extract the billing period start date.",
            },
        ],
    }
    rules = {
        "normalize_units": {
            "description": "Convert MWh to kWh",
            "rule": "Multiply by 1000 when necessary.",
        }
    }

    errors = template_generation_service.validate_generated_template(template)
    normalized = template_generation_service.normalize_generated_template(template, rules, "workspace-1")

    assert errors == []
    assert normalized["name"] == "Utility Bill"
    assert normalized["workspace_id"] == "workspace-1"
    assert normalized["schema_definition"] == {"value": "float", "period_start": "date"}
    assert "Primary output unit target: kWh." in normalized["system_prompt"]
    assert "normalize_units" in normalized["system_prompt"]


def test_extract_document_preview_reads_plain_text():
    preview = template_generation_service.extract_document_preview(
        b"meter,value\nA,42\nB,43\n",
        "sample.csv",
    )

    assert "meter,value" in preview
