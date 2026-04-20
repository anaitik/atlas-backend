"""
Dynamic Metric Definition model.
"""

from __future__ import annotations

from typing import Optional, List
from pydantic import Field
from pymongo import IndexModel

from app.models.base import BaseDocument

class MetricDefinition(BaseDocument):
    """
    A definition for a sustainable metric. Can be globally defined (company_id=None)
    or custom per tenant.
    """
    key: str
    company_id: Optional[str] = None
    description: str
    pillar: str = "environmental"
    unit: str
    suggested_tool: str = "direct_read"
    tags: List[str] = Field(default_factory=list)

    class Settings:
        name = "metric_definitions"
        indexes = [
            IndexModel([("key", 1), ("company_id", 1)], unique=True),
        ]
