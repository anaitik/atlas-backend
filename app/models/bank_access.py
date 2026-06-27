"""
Bank access token — grants a named institution read access to an MSME workspace's ESG data.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from pymongo import IndexModel

from app.models.base import BaseDocument


class BankAccess(BaseDocument):
    workspace_id: str
    company_id: str
    institution_name: str
    created_by_id: str

    # Permission scope
    allowed_pillars: List[str] = ["environmental", "social", "governance"]
    allow_document_access: bool = False

    # Access token (opaque, URL-safe)
    access_token: str

    # Lifecycle
    expires_at: Optional[datetime] = None
    is_active: bool = True

    # Usage audit
    last_accessed_at: Optional[datetime] = None
    access_count: int = 0

    class Settings:
        name = "bank_access"
        indexes = [
            IndexModel([("access_token", 1)], unique=True),
            IndexModel([("workspace_id", 1), ("is_active", 1)]),
        ]
