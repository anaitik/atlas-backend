from datetime import datetime
from typing import Any, Dict, List
from pydantic import BaseModel, Field
from app.core.responses import PaginatedSuccessResponse

class CompanyCreate(BaseModel):
    name: str = Field(..., min_length=2)

class CompanyOut(BaseModel):
    id: str
    name: str
    status: str
    profile_complete: bool = False
    created_at: datetime
    updated_at: datetime

class CompanyListPage(PaginatedSuccessResponse[CompanyOut]):
    pass


# ── Company general-info intake ──────────────────────────────────

class CompanyProfileUpdate(BaseModel):
    profile_data: Dict[str, Any]

class CompanyProfileOut(BaseModel):
    company_id: str
    sections: List[Dict[str, Any]]      # field definitions (tabs) from config
    profile_data: Dict[str, Any]
    profile_complete: bool
    missing_required: List[str]
