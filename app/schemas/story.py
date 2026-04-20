from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class StoryEventOut(BaseModel):
    id: str
    event_type: str
    created_at: datetime
    headline: str
    detail: str
    payload: Dict[str, Any] = Field(default_factory=dict)


class PipelineStoryOut(BaseModel):
    workspace_id: str
    story: str
    events: List[StoryEventOut] = Field(default_factory=list)
    generated_at: datetime
    sha256_hash: Optional[str] = None
    blockchain_tx_id: Optional[str] = None
