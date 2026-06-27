"""
Notifications endpoints — in-app alerts for workflow events.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.responses import SuccessResponse, api_response
from app.dependencies.auth import require_app_user, TokenData
from app.schemas.notification import NotificationListOut, NotificationOut
from app.services import notification_service

router = APIRouter()
CurrentUser = Annotated[TokenData, Depends(require_app_user)]


@router.get("", response_model=SuccessResponse[NotificationListOut])
async def list_notifications(
    user: CurrentUser,
    unread_only: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
):
    items, total = await notification_service.get_notifications(
        user.user_id, unread_only, page, page_size
    )
    unread = await notification_service.unread_count(user.user_id)
    return api_response(NotificationListOut(
        items=[
            NotificationOut(
                id=n.id,
                event_type=n.event_type,
                title=n.title,
                body=n.body,
                resource_url=n.resource_url,
                is_read=n.is_read,
                created_at=n.created_at,
            )
            for n in items
        ],
        total=total,
        unread_count=unread,
    ))


@router.get("/unread-count", response_model=SuccessResponse[dict])
async def get_unread_count(user: CurrentUser):
    count = await notification_service.unread_count(user.user_id)
    return api_response({"count": count})


@router.post("/read-all", response_model=SuccessResponse[dict])
async def mark_all_read(user: CurrentUser):
    count = await notification_service.mark_all_read(user.user_id)
    return api_response({"marked": count})


@router.post("/{notification_id}/read", response_model=SuccessResponse[dict])
async def mark_read(notification_id: str, user: CurrentUser):
    await notification_service.mark_read(notification_id)
    return api_response({"ok": True})
