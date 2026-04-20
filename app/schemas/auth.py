from pydantic import BaseModel, EmailStr, Field
from app.schemas.user import UserOut

class TokenData(BaseModel):
    user_id: str
    role: str
    company_id: str | None = None

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class AuthLoginData(BaseModel):
    user: UserOut
    access_token: str
    token_type: str = "bearer"

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class RegisterRequest(BaseModel):
    full_name: str
    email: EmailStr
    password: str = Field(..., min_length=8)
