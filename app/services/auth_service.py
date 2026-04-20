from datetime import timedelta
from typing import Tuple

from app.core.errors import AppError, ErrorCode
from app.core.security import verify_password, get_password_hash, create_jwt_token
from app.config import get_settings
from app.models.user import User
from app.repositories.user_repo import UserRepository
from app.schemas.auth import LoginRequest, RegisterRequest

user_repo = UserRepository()

async def authenticate(creds: LoginRequest) -> Tuple[User, str]:
    """Verify credentials and return User + JWT token."""
    user = await user_repo.get_by_email(creds.email)
    
    if not user or not verify_password(creds.password, user.hashed_password):
        raise AppError(ErrorCode.UNAUTHORIZED, "Invalid email or password")
        
    if user.status != "active":
        raise AppError(ErrorCode.FORBIDDEN, f"Account is {user.status}")

    token = create_jwt_token(
        data={"user_id": user.id, "role": user.role, "company_id": user.company_id},
        expires_delta=timedelta(minutes=get_settings().JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    
    return user, token

async def register(data: RegisterRequest) -> User:
    """Create a new pending user."""
    if await user_repo.get_by_email(data.email):
        raise AppError(ErrorCode.CONFLICT, "Email already registered")

    user = User(
        email=data.email.lower(),
        hashed_password=get_password_hash(data.password),
        full_name=data.full_name,
        role="report_viewer", # Default safe role
        status="pending"
    )
    return await user_repo.create(user)
