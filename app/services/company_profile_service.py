"""
Company general-info intake — field definitions come from runtime config
(`company_profile.fields`), so admins control which fields exist and which are
mandatory without a deploy. Mandatory fields gate workspace creation.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from app.services import config_service


def get_field_sections() -> List[Dict[str, Any]]:
    return config_service.get("company_profile.fields").get("sections", [])


def _all_fields() -> List[Dict[str, Any]]:
    fields: List[Dict[str, Any]] = []
    for section in get_field_sections():
        fields.extend(section.get("fields", []))
    return fields


def _is_filled(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    return True


def missing_required(profile_data: Dict[str, Any]) -> List[str]:
    """Return the keys of required fields that are not yet filled."""
    return [
        f["key"] for f in _all_fields()
        if f.get("required") and not _is_filled(profile_data.get(f["key"]))
    ]


def is_complete(profile_data: Dict[str, Any]) -> bool:
    return len(missing_required(profile_data)) == 0


def evaluate(profile_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    miss = missing_required(profile_data)
    return (len(miss) == 0, miss)
