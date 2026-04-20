"""
Application configuration using Pydantic Settings.
All settings load from environment variables or .env files.
Designed for local-first development with production switchover.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from typing import Optional

from pydantic import AliasChoices, Field
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    LOCAL = "local"
    STAGING = "staging"
    PRODUCTION = "production"


class StorageBackend(str, Enum):
    LOCAL = "local"
    S3 = "s3"


class TaskBackend(str, Enum):
    LOCAL = "local"          # FastAPI BackgroundTasks
    CELERY = "celery"        # Celery + Redis (production)


class Settings(BaseSettings):
    """
    Central configuration. Local-first defaults with production overrides.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Environment ──────────────────────────────────────────────
    ENVIRONMENT: Environment = Environment.LOCAL
    APP_NAME: str = "Atlas"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"

    # ── MongoDB ──────────────────────────────────────────────────
    MONGODB_CONNECTION_STRING: str = "mongodb://localhost:27017"
    MONGODB_DATABASE_NAME: str = "sustainability_ai"

    # ── Auth / JWT ───────────────────────────────────────────────
    JWT_SECRET_KEY: str = "dev-secret-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ── CORS ─────────────────────────────────────────────────────
    # Origins are scheme + host (+ port), never paths (e.g. /login is not part of the origin).
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "https://atlas-backend-beta.vercel.app",
        "https://atlas-frontend-lake.vercel.app",
    ]

    # ── Storage (switchable) ─────────────────────────────────────
    STORAGE_BACKEND: StorageBackend = StorageBackend.LOCAL
    LOCAL_STORAGE_PATH: str = "./storage"
    # S3 / MinIO settings — enable when switching to prod
    S3_ENDPOINT_URL: Optional[str] = None
    S3_ACCESS_KEY: Optional[str] = None
    S3_SECRET_KEY: Optional[str] = None
    S3_BUCKET_NAME: str = "sustainability-ai"
    S3_REGION: str = "us-east-1"

    # ── Task Queue (switchable) ──────────────────────────────────
    TASK_BACKEND: TaskBackend = TaskBackend.LOCAL
    # Redis / Celery — enable when switching to prod
    REDIS_URL: Optional[str] = None
    CELERY_BROKER_URL: Optional[str] = None
    CELERY_RESULT_BACKEND: Optional[str] = None

    # ── LLM Providers ────────────────────────────────────────────
    GOOGLE_API_KEY: Optional[str] = None
    DEEPSEEK_API_KEY: Optional[str] = None
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    GROQ_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    DEFAULT_LLM_PROVIDER: str = "deepseek"
    DEFAULT_LLM_MODEL: str = "deepseek-chat"
    EXTRACTION_CONFIDENCE_THRESHOLD: float = 0.90
    ESG_SCOPE2_DEFAULT_METHOD: str = "location_based"
    ESG_AUTO_APPROVE_MIN_CONFIDENCE: float = 0.85
    ESG_ALLOW_GLOBAL_FACTOR_FALLBACK: bool = True
    ESG_REQUIRE_REVIEW_ON_FALLBACK_FACTOR: bool = True
    ESG_HIGH_ASSURANCE_RAW_DOC_ANCHORING: bool = False
    ESG_HIGH_ASSURANCE_MAX_DOCS: int = 100
    VERIFICATION_BASE_URL: Optional[str] = None
    VERIFICATION_SIGNING_SECRET: Optional[str] = None

    # ── Extraction & OCR ─────────────────────────────────────────
    TESSERACT_CMD: Optional[str] = None
    TESSERACT_LANG: str = "eng+deu"
    TESSERACT_PSM: int = 3

    # ── Blockchain ───────────────────────────────────────────────
    BLOCKCHAIN_ENABLED: bool = False
    POLYGON_RPC_URL: Optional[str] = None
    POLYGON_CHAIN_ID: int = 80002
    HASHSTORE_CONTRACT_ADDRESS: Optional[str] = None
    SIGNER_PRIVATE_KEY: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("SIGNER_PRIVATE_KEY", "HASHCHAIN_PRIVATE_KEY"),
    )

    # ── Logging ──────────────────────────────────────────────────
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"  # "json" or "console"

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == Environment.PRODUCTION

    @property
    def is_local(self) -> bool:
        return self.ENVIRONMENT == Environment.LOCAL

    @field_validator("DEBUG", mode="before")
    @classmethod
    def parse_debug(cls, value):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on", "debug", "dev"}:
                return True
            if normalized in {"0", "false", "no", "off", "release", "prod", "production"}:
                return False
        return bool(value)


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
