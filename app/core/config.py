"""
Application configuration using Pydantic Settings.

All configuration is loaded from environment variables with sensible defaults.
Configuration is validated at application startup.
"""

from enum import StrEnum

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LogFormat(StrEnum):
    JSON = "json"
    TEXT = "text"
    AUTO = "auto"


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    All settings can be overridden via environment variables.
    The .env file is loaded automatically if present.
    """

    PROJECT_NAME: str = "Epguides API"

    REDIS_HOST: str = "redis"
    REDIS_PORT: int = Field(default=6379, ge=1, le=65535)
    REDIS_DB: int = Field(default=0, ge=0)
    REDIS_PASSWORD: str | None = None
    REDIS_MAX_CONNECTIONS: int = Field(default=100, ge=1)

    CACHE_TTL_SECONDS: int = Field(default=604800, gt=0)

    API_BASE_URL: str = "http://localhost:3000/"

    LLM_API_URL: str | None = None
    LLM_API_KEY: str | None = None
    LLM_ENABLED: bool = False
    LLM_MODEL_NAME: str = "auto"
    LLM_ALLOW_EXTERNAL: bool = False

    HTTP_TIMEOUT_SECONDS: float = Field(default=5.0, gt=0)

    UPSTREAM_STALENESS_HOURS: float = Field(default=24.0, gt=0)

    UPSTREAM_FRESHNESS_COLD_START_GRACE_SECONDS: float = Field(default=900.0, ge=0)

    READINESS_REDIS_TIMEOUT_SECONDS: float = Field(default=2.0, gt=0)

    LOG_LEVEL: LogLevel = LogLevel.INFO  # pragma: no cover - class body; covered at import time
    LOG_FORMAT: LogFormat = LogFormat.JSON
    LOG_REQUESTS: bool = True

    SENTRY_DSN: str | None = None
    SENTRY_TRACES_SAMPLE_RATE: float = Field(default=0.0, ge=0.0, le=1.0)
    SENTRY_PROFILES_SAMPLE_RATE: float = Field(default=0.0, ge=0.0, le=1.0)
    SENTRY_ENVIRONMENT: str = "production"

    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_file=".env",
        env_file_encoding="utf-8",
    )

    @field_validator("LOG_LEVEL", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("LOG_FORMAT", mode="before")
    @classmethod
    def _normalize_log_format(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value


settings = Settings()  # pragma: no cover - executed before coverage starts
