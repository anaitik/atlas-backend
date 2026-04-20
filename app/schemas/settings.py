from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class WorkspaceSettings(BaseModel):
    models: List[str] = Field(default_factory=lambda: ["gpt-4o", "claude-3-5-sonnet"])
    temperature: float = 0.7
    max_retries: int = 10
    streaming: bool = True
    default_pillar_logic: str = "fuzzy_match"
    require_metric_approval: bool = True
    export_formats: List[str] = Field(default_factory=lambda: ["pdf", "docx", "xhtml"])


class WorkspaceSettingsUpdate(BaseModel):
    models: Optional[List[str]] = None
    temperature: Optional[float] = None
    max_retries: Optional[int] = None
    streaming: Optional[bool] = None
    default_pillar_logic: Optional[str] = None
    require_metric_approval: Optional[bool] = None
    export_formats: Optional[List[str]] = None
