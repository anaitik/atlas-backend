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


# ── Isolated, non-hierarchy role: Atlas-side question reviewer ──────
# `system_audit_officer` is intentionally NOT in the role hierarchy above, so it
# resolves to level 0 and is denied every existing role-gated endpoint. It can
# ONLY reach endpoints that explicitly depend on `require_audit_officer` — i.e.
# the blueprint review queue. This keeps the role's visibility to questions only.
AUDIT_OFFICER_ROLE = "system_audit_officer"


def require_audit_officer(
    current_user: Annotated[TokenData, Depends(get_current_user)],
) -> TokenData:
    if current_user.role not in (AUDIT_OFFICER_ROLE, "system_admin"):
        raise AppError(ErrorCode.FORBIDDEN, "Audit officer access required")
    return current_user


def require_app_user(
    current_user: Annotated[TokenData, Depends(get_current_user)],
) -> TokenData:
    """Authenticated tenant user, but NOT the audit officer.

    Use on endpoints gated only by bare authentication (no hierarchy role check),
    so the isolated `system_audit_officer` can reach ONLY the blueprint queue.
    """
    if current_user.role == AUDIT_OFFICER_ROLE:
        raise AppError(ErrorCode.FORBIDDEN, "Not available for this role")
    return current_user
