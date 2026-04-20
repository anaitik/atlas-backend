from typing import Annotated

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError

from app.core.errors import AppError, ErrorCode
from app.core.security import decode_jwt_token
from app.schemas.auth import TokenData

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]) -> TokenData:
    """Dependency: Extract and validate JWT."""
    try:
        payload = decode_jwt_token(token)
        user_id: str | None = payload.get("user_id")
        role: str | None = payload.get("role")
        if user_id is None or role is None:
            raise AppError(ErrorCode.UNAUTHORIZED, "Invalid token structure")
        return TokenData(
            user_id=user_id, 
            role=role, 
            company_id=payload.get("company_id")
        )
    except JWTError:
        raise AppError(ErrorCode.UNAUTHORIZED, "Could not validate credentials")

def require_role(min_role: str):
    """Dependency factory: Enforce minimum RBAC role."""
    # Match frontend hierarchy
    hierarchy = {
        "system_admin": 100,
        "company_owner": 80,
        "sustainability_manager": 60,
        "data_reviewer": 40,
        "report_viewer": 20
    }
    def role_checker(current_user: Annotated[TokenData, Depends(get_current_user)]) -> TokenData:
        user_level = hierarchy.get(current_user.role, 0)
        req_level = hierarchy.get(min_role, 999)
        if user_level < req_level:
            raise AppError(ErrorCode.FORBIDDEN, "Insufficient permissions")
        return current_user
    return role_checker

# Pre-configured helpers
require_admin = require_role("system_admin")
require_owner = require_role("company_owner")
require_manager = require_role("sustainability_manager")
