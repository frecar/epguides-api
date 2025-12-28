"""
Application configuration using Pydantic Settings.

All configuration is loaded from environment variables with sensible defaults.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    PROJECT_NAME: str = "Epguides API"

    # Redis Configuration
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str | None = None

    # Cache Configuration
    CACHE_TTL_SECONDS: int = 3600  # 1 hour default

    # API Configuration
    API_BASE_URL: str = "http://localhost:3000/"

    # LLM Configuration (optional, for smart natural language queries)
    LLM_API_URL: str | None = None  # e.g., "https://localhost/v1"
    LLM_API_KEY: str | None = None
    LLM_ENABLED: bool = False  # Disabled by default for performance

    # Logging Configuration
    LOG_LEVEL: str = "INFO"
    LOG_REQUESTS: bool = True

    model_config = SettingsConfigDict(case_sensitive=True, env_file=".env")


settings = Settings()
