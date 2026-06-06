"""Shared numeric coercion helpers for activity metrics (not dates or identifiers)."""

from __future__ import annotations

import re
from typing import Any

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_DATETIME_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}[T\s]")


def looks_like_iso_date(text: str) -> bool:
    stripped = text.strip()
    if _ISO_DATE.match(stripped):
        return True
    return bool(_ISO_DATETIME_PREFIX.match(stripped))


def coerce_activity_numeric(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text or looks_like_iso_date(text):
        return None

    candidate = text.replace(" ", "")

    if not re.match(r"^[^\dA-Za-z\-+]*[-+]?\d", candidate):
        return None

    if "," in candidate and "." in candidate:
        if candidate.rfind(",") > candidate.rfind("."):
            candidate = candidate.replace(".", "").replace(",", ".")
        else:
            candidate = candidate.replace(",", "")
    elif "," in candidate:
        candidate = candidate.replace(",", ".")

    match = re.search(r"-?\d+(?:\.\d+)?", candidate)
    if not match:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None
