from datetime import datetime
from pydantic import BaseModel, Field
from app.core.responses import PaginatedSuccessResponse

class CompanyCreate(BaseModel):
    name: str = Field(..., min_length=2)

class CompanyOut(BaseModel):
    id: str
    name: str
    status: str
    created_at: datetime
    updated_at: datetime

class CompanyListPage(PaginatedSuccessResponse[CompanyOut]):
    pass
