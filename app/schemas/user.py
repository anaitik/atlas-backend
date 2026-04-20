from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr

class UserOut(BaseModel):
    id: str
    email: EmailStr
    full_name: str
    role: str
    status: str
    company_id: Optional[str]
    created_at: datetime
    updated_at: datetime

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = None
    status: Optional[str] = None
    company_id: Optional[str] = None
