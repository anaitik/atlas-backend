"""
Shared FastAPI dependencies.
Injected via Depends() in route handlers.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db.session import get_database


async def get_db() -> AsyncIOMotorDatabase:
    """Dependency: returns the active MongoDB database."""
    return get_database()
