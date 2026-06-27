"""
Notification service — create and manage user notifications.
Owned by Pack 03.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from app.models.notification import Notification

logger = structlog.get_logger()


async def notify(
    recipient_user_id: str,
    event_type: str,
    title: str,
    body: str = "",
    resource_url: Optional[str] = None,
) -> Notification:
    """Create an in-app notification and attempt an email if SMTP is configured."""
    notification = Notification(
        recipient_user_id=recipient_user_id,
        event_type=event_type,
        title=title,
        body=body,
        resource_url=resource_url,
    )
    await notification.insert()

    logger.info("notification_created", recipient=recipient_user_id, event_type=event_type)

    # Fire-and-forget email (non-blocking, fails silently)
    try:
        from app.models.user import User
        from app.services.email_service import send_email
        user = await User.find_one({"id": recipient_user_id})
        if user and user.email:
            await send_email(
                to=user.email,
                subject=title,
                title=title,
                body=body or title,
                cta_label="Open Atlas",
                cta_url=resource_url,
            )
    except Exception:
        pass

    return notification


async def mark_read(notification_id: str) -> Optional[Notification]:
    """Mark a single notification as read."""
    notif = await Notification.get(notification_id)
    if notif and notif.read_at is None:
        notif.read_at = datetime.now(timezone.utc)
        await notif.save()
    return notif


async def mark_all_read(user_id: str) -> int:
    """Mark all unread notifications for a user as read."""
    now = datetime.now(timezone.utc)
    result = await Notification.find(
        Notification.recipient_user_id == user_id,
        Notification.read_at == None,  # noqa: E711
    ).update_many({"$set": {"read_at": now}})
    return result.modified_count if result else 0


async def get_notifications(
    user_id: str,
    unread_only: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Notification], int]:
    """Get notifications for a user with optional unread filter."""
    filters: dict[str, Any] = {"recipient_user_id": user_id}
    if unread_only:
        filters["read_at"] = None

    skip = (page - 1) * page_size
    total = await Notification.find(filters).count()
    items = await (
        Notification.find(filters)
        .sort("-created_at")
        .skip(skip)
        .limit(page_size)
        .to_list()
    )
    return items, total


async def unread_count(user_id: str) -> int:
    """Count unread notifications for a user."""
    return await Notification.find(
        Notification.recipient_user_id == user_id,
        Notification.read_at == None,  # noqa: E711
    ).count()
