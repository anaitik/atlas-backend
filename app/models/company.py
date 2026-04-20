"""
Company layout for multi-tenancy. Part of Pack 02.
"""

from __future__ import annotations

from pydantic import Field
from pymongo import IndexModel

from app.models.base import BaseDocument


class Company(BaseDocument):
    """
    Root tenant entity. All data belongs to a company.
    """
    name: str
    status: str = "active"  # active, suspended
    
    class Settings:
        name = "companies"
        indexes = [
            IndexModel([("name", 1)], unique=True),
            IndexModel([("status", 1)]),
        ]
