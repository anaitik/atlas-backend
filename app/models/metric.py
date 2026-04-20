"""
Computed metrics model. Part of Pack 06.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Literal
from pydantic import Field
from pymongo import IndexModel

from app.models.base import BaseDocument

MetricStatus = Literal["pending", "approved", "manual_required", "rejected"]

class Metric(BaseDocument):
    """
    A single standardized metric (e.g. Scope 1 GHG in metric tons)
    derived from one or more extraction runs.
    """
    company_id: str
    workspace_id: str
    
    # Core Definition
    metric_code: str               # e.g., "GRI-305-1-a"
    name: str                      # e.g., "Scope 1 GHG Emissions"
    unit: str                      # e.g., "MT CO2e"
    pillar: str = "environmental"  # environmental, social, governance
    
    # The actual numerical or qualitative value
    value: float
    metadata: Dict[str, Any] = Field(default_factory=dict)  # E.g., confidence interval, method used
    
    # Provenance
    source_extracted_data_ids: list[str] = Field(default_factory=list)
    
    # Human Review
    status: MetricStatus = "pending"
    reviewer: Optional[str] = None
    
    class Settings:
        name = "metrics"
        indexes = [
            IndexModel([("company_id", 1), ("workspace_id", 1), ("metric_code", 1)]),
            IndexModel([("company_id", 1), ("workspace_id", 1), ("status", 1)]),
        ]
