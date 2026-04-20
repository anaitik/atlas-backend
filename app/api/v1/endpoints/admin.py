from typing import Annotated
from fastapi import APIRouter, Depends
from app.core.responses import SuccessResponse, api_response
from app.dependencies.auth import require_admin
from app.models.company import Company
from app.models.user import User
from app.models.audit_event import AuditEvent

router = APIRouter()

@router.get("/stats", response_model=SuccessResponse[dict])
async def get_system_stats(_: Annotated[bool, Depends(require_admin)]):
    """
    Returns platform-level counts for the admin dashboard.
    """
    tenant_count = await Company.count()
    user_count = await User.count()
    
    # Simple load heuristic (real systems use Redis/Prometheus here)
    pending_users = await User.find(User.status == "pending").count()
    
    return api_response({
        "tenant_count": tenant_count,
        "active_user_count": user_count,
        "pending_user_count": pending_users
    })

@router.get("/audit-logs", response_model=SuccessResponse[list])
async def get_audit_logs(_: Annotated[bool, Depends(require_admin)]):
    """
    Returns recent system audit logs.
    """
    logs = await AuditEvent.find_all().sort("-created_at").limit(10).to_list()
    return api_response([log.model_dump() for log in logs])
