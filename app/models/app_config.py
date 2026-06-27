"""
Runtime configuration store — DB-backed, admin-editable policy/business config.

Holds everything that used to be hardcoded in code (scoring weights, sector
benchmarks, the default interview blueprint, grounding sources, profile field
definitions, thresholds). Secrets/deployment values stay in `.env` and are NOT
stored here.
"""

from __future__ import annotations

from typing import Any, Optional
from pymongo import IndexModel

from app.models.base import BaseDocument


class AppConfig(BaseDocument):
    """One configurable policy value, addressed by (namespace, key)."""

    namespace: str            # e.g. "scoring.rubric", "company_profile.fields"
    key: str                  # e.g. "pillar_weights"
    value: Any = None         # arbitrary JSON-serialisable value
    updated_by: Optional[str] = None

    class Settings:
        name = "app_config"
        indexes = [
            IndexModel([("namespace", 1), ("key", 1)], unique=True),
        ]
