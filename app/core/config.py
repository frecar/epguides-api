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
    REDIS_MAX_CONNECTIONS: int = 100  # ~10 per uvicorn worker

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
    # Set LLM_API_URL to your OpenAI-compatible gateway (e.g. a local Ollama,
    # vLLM, llama.cpp server, or any hosted endpoint). Empty/unset disables
    # natural-language queries; structured filters always work.
    #
    # Optional `ALLOWED_LLM_HOSTS` (comma-separated hostnames) gates which
    # hosts the URL may resolve to. Empty (default) means no host enforcement.
    LLM_API_URL: str | None = None
    LLM_API_KEY: str | None = None
    LLM_ENABLED: bool = False  # Disabled by default for performance
    LLM_MODEL_NAME: str = "auto"
    LLM_ALLOW_EXTERNAL: bool = False

    # -------------------------------------------------------------------------
    # HTTP Configuration
    # -------------------------------------------------------------------------
    HTTP_TIMEOUT_SECONDS: float = 5.0  # Timeout for external HTTP requests

    # -------------------------------------------------------------------------
    # Readiness / Deep-Health Configuration
    # -------------------------------------------------------------------------
    # /health/ready flips to a degraded (HTTP 503) state when no successful
    # upstream (epguides.com) fetch has happened within this many hours. The
    # cache hides upstream outages for up to its TTL, so a longer-than-cadence
    # gap without a single success means the data is silently going stale.
    # Default 24h: comfortably longer than a healthy scrape cadence, short
    # enough to surface a multi-hour upstream regression before users notice.
    UPSTREAM_STALENESS_HOURS: float = 24.0

    # Grace window after process start during which an *absent* freshness
    # marker (no upstream fetch recorded yet) is reported as "bootstrapping"
    # (HTTP 200) instead of "stale" (HTTP 503). Without this, a freshly
    # deployed instance fails its readiness probe immediately — before it has
    # had a chance to serve a single upstream fetch — which would block the
    # rollout. Default 15 minutes.
    UPSTREAM_FRESHNESS_COLD_START_GRACE_SECONDS: float = 900.0

    # Upper bound on the Redis round-trip the readiness probe performs, so a
    # sick Redis cannot make the probe itself hang. Kept short — readiness
    # probes are called frequently and must answer fast.
    READINESS_REDIS_TIMEOUT_SECONDS: float = 2.0

    # -------------------------------------------------------------------------
    # Logging Configuration
    # -------------------------------------------------------------------------
    LOG_LEVEL: str = "INFO"  # pragma: no cover - class body; covered at import time
    LOG_FORMAT: str = "json"  # "json" for structured output, "text" for human-readable
    LOG_REQUESTS: bool = True

    # -------------------------------------------------------------------------
    # Observability (Optional)
    # -------------------------------------------------------------------------
    SENTRY_DSN: str | None = None
    SENTRY_TRACES_SAMPLE_RATE: float = 0.0
    SENTRY_PROFILES_SAMPLE_RATE: float = 0.0
    SENTRY_ENVIRONMENT: str = "production"

    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_file=".env",
        env_file_encoding="utf-8",
    )


# Global settings instance - loaded once at import time
settings = Settings()  # pragma: no cover - executed before coverage starts
