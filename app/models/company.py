"""
Company layout for multi-tenancy. Part of Pack 02.
"""

from __future__ import annotations

from typing import Any, Dict

from pydantic import Field
from pymongo import IndexModel

from app.models.base import BaseDocument


class Company(BaseDocument):
    """
    Root tenant entity. All data belongs to a company.
    """
    name: str
    status: str = "active"  # active, suspended

    # General-info intake (field definitions live in config: company_profile.fields).
    # Mandatory fields must be complete before any workspace can be created.
    profile_data: Dict[str, Any] = Field(default_factory=dict)
    profile_complete: bool = False

    class Settings:
        name = "companies"
        indexes = [
            IndexModel([("name", 1)], unique=True),
            IndexModel([("status", 1)]),
        ]
