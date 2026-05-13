"""
MongoDB connection via Motor + Beanie ODM initialization.
Supports MongoDB Atlas (cloud) and local MongoDB.
"""

from __future__ import annotations

from typing import Optional

from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import get_settings

_client: Optional[AsyncIOMotorClient] = None
_database: Optional[AsyncIOMotorDatabase] = None


async def connect_db() -> AsyncIOMotorDatabase:
    """Initialize Motor client and Beanie ODM."""
    global _client, _database

    settings = get_settings()
    import structlog
    logger = structlog.get_logger()
    logger.info("connecting_to_mongodb", uri=settings.MONGODB_CONNECTION_STRING.split("@")[-1]) # Log only host part for security
    
    _client = AsyncIOMotorClient(
        settings.MONGODB_CONNECTION_STRING,
        serverSelectionTimeoutMS=30000,  # Increased timeout for slower environments
        connectTimeoutMS=10000,
    )
    _database = _client[settings.MONGODB_DATABASE_NAME]

    # Import all document models for Beanie registration
    from app.models.audit_event import AuditEvent
    from app.models.notification import Notification
    from app.models.user import User
    from app.models.company import Company
    from app.models.workspace import Workspace
    from app.models.document import Document
    from app.models.extraction import SchemaTemplate, ExtractedData
    from app.models.metric import Metric
    from app.models.metric_definition import MetricDefinition
    from app.models.emission_factor import EmissionFactor
    from app.models.report import Report

    await init_beanie(
        database=_database,
        document_models=[
            AuditEvent,
            Notification,
            User,
            Company,
            Workspace,
            Document,
            SchemaTemplate,
            ExtractedData,
            Metric,
            MetricDefinition,
            EmissionFactor,
            Report,
        ],
    )

    return _database


async def close_db() -> None:
    """Close the Motor client."""
    global _client
    if _client:
        _client.close()
        _client = None


def get_database() -> AsyncIOMotorDatabase:
    """Return the active database instance."""
    if _database is None:
        raise RuntimeError("Database not initialized. Call connect_db() first.")
    return _database


def get_client() -> AsyncIOMotorClient:
    """Return the active Motor client."""
    if _client is None:
        raise RuntimeError("Database client not initialized.")
    return _client
