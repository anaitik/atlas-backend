"""
Background task abstraction.
Local mode: uses FastAPI BackgroundTasks (in-process).
Production mode: switches to Celery + Redis.

To switch, set TASK_BACKEND=celery and CELERY_BROKER_URL in env.
"""

from __future__ import annotations

from typing import Any, Callable

from app.config import TaskBackend, get_settings


def get_task_runner():
    """
    Returns the appropriate task runner based on config.
    In local mode, returns a simple wrapper around BackgroundTasks.
    In prod mode, returns Celery task dispatch.
    """
    settings = get_settings()

    if settings.TASK_BACKEND == TaskBackend.CELERY:
        # Import Celery app only when needed
        from celery import Celery

        celery_app = Celery(
            "sustainability_ai",
            broker=settings.CELERY_BROKER_URL,
            backend=settings.CELERY_RESULT_BACKEND,
        )
        celery_app.conf.update(
            task_serializer="json",
            result_serializer="json",
            accept_content=["json"],
            timezone="UTC",
            enable_utc=True,
            task_track_started=True,
        )
        return celery_app

    return None  # Local mode uses FastAPI BackgroundTasks directly
