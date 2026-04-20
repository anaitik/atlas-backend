"""
User model with RBAC extensions. Part of Pack 02.
"""

from __future__ import annotations

from typing import Optional
from pymongo import IndexModel

from app.models.base import BaseDocument


class User(BaseDocument):
    """
    User entity managing authentication and authorization.
    """
    email: str
    hashed_password: str
    full_name: str
    role: str = "report_viewer"                   # RBAC matrix role
    status: str = "pending"                       # pending, active, suspended
    company_id: Optional[str] = None              # Tenancy isolation
    
    class Settings:
        name = "users"
        indexes = [
            IndexModel([("email", 1)], unique=True),
            IndexModel([("company_id", 1), ("status", 1)]),
        ]
