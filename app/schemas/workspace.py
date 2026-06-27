from datetime import datetime
from typing import Any, Dict, List, Optional
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
    # Company profile
    nace_sector: Optional[str] = None
    employee_count_range: Optional[str] = None
    turnover_range_eur: Optional[str] = None
    is_listed: bool = False
    is_first_time_reporter: bool = True
    material_topics: List[str] = []


class WorkspaceProfileUpdate(BaseModel):
    nace_sector: Optional[str] = None
    employee_count_range: Optional[str] = None
    turnover_range_eur: Optional[str] = None
    is_listed: Optional[bool] = None
    is_first_time_reporter: Optional[bool] = None
    material_topics: Optional[List[str]] = None
    reporting_year: Optional[int] = None
    region: Optional[str] = None
    scope2_method: Optional[str] = None


class WorkspaceOut(BaseModel):
    id: str
    name: str
    description: Optional[str] = ""
    company_id: str
    status: str
    require_extraction_review: bool
    require_metric_approval: bool
    require_publish_approval: bool
    require_review_on_fallback_factor: bool
    region: str
    reporting_year: Optional[int]
    scope2_method: str
    nace_sector: Optional[str] = None
    employee_count_range: Optional[str] = None
    turnover_range_eur: Optional[str] = None
    is_listed: bool = False
    is_first_time_reporter: bool = True
    material_topics: List[str] = []
    created_at: datetime
    updated_at: datetime


class DisclosureOut(BaseModel):
    id: str
    standard: str
    topic: str
    title: str
    pillar: str
    obligation_status: str   # "mandatory" | "conditional" | "deferred" | "not_applicable"
    data_status: str          # "complete" | "partial" | "not_started"
    metric_codes: List[str]
    description: str
    input_guidance: str
    deferred: bool = False


class ComplianceMapOut(BaseModel):
    workspace_id: str
    csrd_phase: Optional[int]
    total_required: int
    total_complete: int
    total_partial: int
    total_not_started: int
    completion_pct: int
    disclosures: List[DisclosureOut]
    profile_complete: bool
    profile_missing_fields: List[str]
    pillar_completion: Dict[str, Any]
