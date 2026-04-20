"""
Base document model with shared fields for all Beanie documents.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from beanie import Document
from pydantic import Field


class BaseDocument(Document):
    """
    Base document for all SustainabilityAI models.
    Provides a stable string ID and UTC timestamps.
    """
    id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        use_state_management = True

    async def save_with_timestamp(self, **kwargs):
        """Update the updated_at timestamp before saving."""
        self.updated_at = datetime.now(timezone.utc)
        return await self.save(**kwargs)


class SoftDeleteDocument(BaseDocument):
    """
    Extends BaseDocument with soft-delete capability.
    Only use when explicitly documented by the owning domain pack.
    """
    deleted_at: Optional[datetime] = None

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    async def soft_delete(self):
        self.deleted_at = datetime.now(timezone.utc)
        return await self.save_with_timestamp()
