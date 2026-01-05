"""
Application configuration using Pydantic Settings.

All configuration is loaded from environment variables with sensible defaults.
Configuration is validated at application startup.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    All settings can be overridden via environment variables.
    The .env file is loaded automatically if present.
    """

    # -------------------------------------------------------------------------
    # Application
    # -------------------------------------------------------------------------
    PROJECT_NAME: str = "Epguides API"

    # -------------------------------------------------------------------------
    # Redis Configuration
    # -------------------------------------------------------------------------
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str | None = None

    # -------------------------------------------------------------------------
    # Cache Configuration
    # Episode data changes at most weekly, cache aggressively
    # -------------------------------------------------------------------------
    CACHE_TTL_SECONDS: int = 604800  # 7 days - episodes air weekly at most

    # -------------------------------------------------------------------------
    # API Configuration
    # -------------------------------------------------------------------------
    API_BASE_URL: str = "http://localhost:3000/"

    # -------------------------------------------------------------------------
    # LLM Configuration (Optional - for smart natural language queries)
    # -------------------------------------------------------------------------
    LLM_API_URL: str | None = None  # e.g., "https://localhost/v1"
    LLM_API_KEY: str | None = None
    LLM_ENABLED: bool = False  # Disabled by default for performance

    # -------------------------------------------------------------------------
    # Logging Configuration
    # -------------------------------------------------------------------------
    LOG_LEVEL: str = "INFO"
    LOG_REQUESTS: bool = True

    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_file=".env",
        env_file_encoding="utf-8",
    )


# Global settings instance - loaded once at import time
settings = Settings()
