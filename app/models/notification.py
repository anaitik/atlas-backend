"""
Notification document.
Owned by Pack 03.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from beanie import Document
from pydantic import Field
from pymongo import IndexModel


class Notification(Document):
    """
    User notification.
    Created by workflow events, marked read by the recipient.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    recipient_user_id: str
    event_type: str                                # e.g. "BATCH_APPROVED", "REPORT_PENDING"
    title: str
    body: str = ""
    resource_url: Optional[str] = None             # Deep link into the frontend
    read_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "notifications"
        indexes = [
            IndexModel([("recipient_user_id", 1), ("read_at", 1), ("created_at", -1)]),
        ]

    @property
    def is_read(self) -> bool:
        return self.read_at is not None
