from datetime import datetime
from typing import Optional
from pydantic import BaseModel

class WorkspaceCreate(BaseModel):
    name: str
    description: Optional[str] = ""
    require_extraction_review: bool = True
    require_metric_approval: bool = True
    require_publish_approval: bool = True
    require_review_on_fallback_factor: bool = True
    region: str = "EU"
    reporting_year: Optional[int] = None
    scope2_method: str = "location_based"

class WorkspaceOut(BaseModel):
    id: str
    name: str
    description: str
    company_id: str
    status: str
    require_extraction_review: bool
    require_metric_approval: bool
    require_publish_approval: bool
    require_review_on_fallback_factor: bool
    region: str
    reporting_year: Optional[int]
    scope2_method: str
    created_at: datetime
    updated_at: datetime
