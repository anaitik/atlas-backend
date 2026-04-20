"""
Workspace for sub-dividing company workflows. Part of Pack 02.
"""

from __future__ import annotations

from typing import Optional
from pymongo import IndexModel

from app.models.base import BaseDocument


class Workspace(BaseDocument):
    """
    Isolates data for a specific audit or operational unit within a company.
    """
    name: str
    description: Optional[str] = ""
    company_id: str
    status: str = "active"         # active, archived
    
    # Approval Gates configuration
    require_extraction_review: bool = True
    require_metric_approval: bool = True
    require_publish_approval: bool = True
    require_review_on_fallback_factor: bool = True

    # ESG emissions governance defaults
    region: str = "EU"
    reporting_year: Optional[int] = None
    scope2_method: str = "location_based"  # location_based | market_based

    class Settings:
        name = "workspaces"
        indexes = [
            IndexModel([("company_id", 1), ("status", 1)]),
            IndexModel([("company_id", 1), ("name", 1)]),
        ]
