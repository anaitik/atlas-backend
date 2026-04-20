"""
Dynamic Emission Factor model.
"""

from __future__ import annotations

from typing import Optional
from pymongo import IndexModel

from app.models.base import BaseDocument

class EmissionFactor(BaseDocument):
    """
    A numeric factor used to convert activity data into GHG emissions.
    Can be globally defined (company_id=None) or custom per tenant.
    """
    key: str
    company_id: Optional[str] = None
    value: float
    unit: str
    source: str
    scope: int
    region: Optional[str] = None
    year: Optional[int] = None
    unit_basis: Optional[str] = None
    version: str = "custom"
    status: str = "active"

    class Settings:
        name = "emission_factors"
        indexes = [
            IndexModel([("key", 1), ("company_id", 1)], unique=True),
        ]
