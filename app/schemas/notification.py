from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel


class NotificationOut(BaseModel):
    id: str
    event_type: str
    title: str
    body: str
    resource_url: Optional[str]
    is_read: bool
    created_at: datetime


class NotificationListOut(BaseModel):
    items: List[NotificationOut]
    total: int
    unread_count: int
