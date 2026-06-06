"""
Epguides API - High-performance TV show metadata API.

This module configures the FastAPI application with all routes,
middleware, and exception handlers.
"""

import asyncio
import logging.config
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, Response

from app.api.endpoints import mcp, shows
from app.core.cache import close_redis_pool, get_cache_stats, refresh_cache_age_gauges
from app.core.config import settings
from app.core.constants import VERSION
from app.core.metrics import init_ingest_freshness, mark_worker_dead, render_metrics
from app.core.middleware import RequestIDMiddleware, RequestLoggingMiddleware, SecurityHeadersMiddleware, get_request_id
from app.core.observability import init_observability
from app.exceptions import EpguidesAPIException, ExternalServiceError

# =============================================================================
# Logging Setup
# =============================================================================


def _initialize_logging() -> None:
    """Initialize logging with fallback to basic config."""
    try:
        from app.core.logging_config import setup_logging

        setup_logging()
    except Exception:
        # Fallback to basic config if custom setup fails
        logging.basicConfig(level=logging.INFO)


_initialize_logging()

logger = logging.getLogger(__name__)

# =============================================================================
# Observability (opt-in via env vars)
# =============================================================================

init_observability(release=os.environ.get("GIT_SHA", VERSION))


# =============================================================================
# Application Lifespan
# =============================================================================


async def _cache_age_refresh_loop() -> None:
    """Background task: update the cache-age gauge every 5 minutes.

    Runs in every uvicorn worker but only one worker actually scans Redis
    per interval (NX lock inside refresh_cache_age_gauges). CancelledError
    from task.cancel() propagates out of asyncio.sleep naturally.
    """
    while True:
        await refresh_cache_age_gauges()
        await asyncio.sleep(300)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """
    Application lifespan context manager.

    Handles startup and shutdown events.
    """
    logger.info("Application startup")
    # Seed the per-source ingest-freshness gauges to 0 so the series are
    # continuously present from boot (avoids an absence-paging false alarm
    # before the first successful upstream fetch). See app.core.metrics.
    init_ingest_freshness()
    task = asyncio.create_task(_cache_age_refresh_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    # Clean up multiprocess prometheus state for this worker so the
    # next scrape doesn't double-count dead worker's counters. No-op
    # in single-process mode (env var unset).
    mark_worker_dead(os.getpid())
    await close_redis_pool()
    logger.info("Application shutdown complete")


# =============================================================================
# Application Instance
# =============================================================================

# Tag metadata for Swagger UI grouping
OPENAPI_TAGS = [
    {
        "name": "Shows",
        "description": "📺 **Browse and search TV shows** - List, search, and get detailed metadata for thousands of TV shows.",
    },
    {
        "name": "MCP",
        "description": "🤖 **Model Context Protocol** - JSON-RPC 2.0 endpoint for AI assistant integration (Claude, ChatGPT, etc.).",
    },
    {
        "name": "Health",
        "description": "💚 **Health checks** - Monitor API and LLM service status.",
    },
]

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="""
**Free REST API for TV show data, episode lists, air dates, and plot summaries.**

No API key required. Just start making requests!

---

## Quick Start

```bash
# Search for shows
curl "https://epguides.frecar.no/shows/search?query=breaking"

# Get show details
curl "https://epguides.frecar.no/shows/BreakingBad"

# Get episodes
curl "https://epguides.frecar.no/shows/BreakingBad/episodes?season=5"

# Get next episode
curl "https://epguides.frecar.no/shows/Severance/episodes/next"
```

---

## Features

- 📺 **TV Database** — Thousands of shows with metadata
- 🔍 **Search** — Find shows by title
- 📅 **Episodes** — Full lists with air dates and summaries
- 🖼️ **Posters** — Show and season images from TVMaze
- ⏭️ **Tracking** — Get next/latest episodes
- 🤖 **MCP Server** — JSON-RPC for AI assistants
- ⚡ **Smart Cache** — 7 days ongoing, 1 year finished

---

## Resources

| | |
|---|---|
| 📖 **Documentation** | [epguides-api.readthedocs.io](https://epguides-api.readthedocs.io) |
| 💻 **GitHub** | [github.com/frecar/epguides-api](https://github.com/frecar/epguides-api) |
| 🤖 **MCP** | `POST /mcp` (JSON-RPC 2.0) |
""",
    version=VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
    license_info={"name": "MIT", "url": "https://opensource.org/licenses/MIT"},
    contact={"name": "GitHub", "url": "https://github.com/frecar/epguides-api"},
    openapi_tags=OPENAPI_TAGS,
)


# =============================================================================
# Middleware
# =============================================================================

# Request ID tracking (outermost - runs first, available to all other middleware)
app.add_middleware(RequestIDMiddleware)

# Request logging (if enabled)
if settings.LOG_REQUESTS:
    app.add_middleware(RequestLoggingMiddleware)

# Security headers on all responses
app.add_middleware(SecurityHeadersMiddleware)

# CORS - public read-only API, allow all origins but no credentials
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)


# =============================================================================
# Exception Handlers
# =============================================================================


@app.exception_handler(EpguidesAPIException)
async def epguides_exception_handler(
    request: Request,
    exc: EpguidesAPIException,
) -> JSONResponse:
    """Handle custom API exceptions."""
    request_id = get_request_id(request)
    logger.error("API error: %s (request_id=%s)", exc, request_id, exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "An internal error occurred. Please try again later.",
            "request_id": request_id,
        },
    )


@app.exception_handler(ExternalServiceError)
async def external_service_exception_handler(
    request: Request,
    exc: ExternalServiceError,
) -> JSONResponse:
    """Handle external service failures."""
    request_id = get_request_id(request)
    logger.error("External service error: %s (request_id=%s)", exc, request_id, exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "detail": "External service temporarily unavailable.",
            "request_id": request_id,
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Handle request validation errors with clean details."""
    request_id = get_request_id(request)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "detail": "Validation error",
            "errors": exc.errors(),
            "request_id": request_id,
        },
    )


@app.exception_handler(404)
async def not_found_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Handle 404 Not Found errors with a clean JSON response."""
    request_id = get_request_id(request)
    detail = getattr(exc, "detail", "The requested resource was not found.")
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={
            "detail": detail,
            "request_id": request_id,
        },
    )


@app.exception_handler(500)
async def internal_error_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Handle unexpected 500 errors with a clean JSON response."""
    request_id = get_request_id(request)
    logger.error("Unhandled error: %s (request_id=%s)", exc, request_id, exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "An unexpected error occurred.",
            "request_id": request_id,
        },
    )


# =============================================================================
# Routers
# =============================================================================

app.include_router(shows.router, prefix="/shows", tags=["Shows"])
app.include_router(mcp.router, tags=["MCP"])


# =============================================================================
# Root Endpoints
# =============================================================================


@app.get("/", include_in_schema=False)
def root_redirect() -> RedirectResponse:
    """Redirect root to API documentation."""
    return RedirectResponse(url="/docs")


@app.get("/health", tags=["Health"], summary="💚 API health check")
def health_check() -> dict[str, str]:
    """
    **Check API health status.**

    Use for load balancer health checks, monitoring, and verifying the API is operational.

    ### Response
    ```json
    {
      "status": "healthy",
      "service": "epguides-api",
      "version": "123"
    }
    ```
    """
    return {"status": "healthy", "service": "epguides-api", "version": VERSION}


@app.get("/health/llm", tags=["Health"], summary="🤖 LLM health check")
def llm_health_check() -> dict[str, str | bool]:
    """
    **Check LLM configuration status.**

    The LLM powers the `nlq` (natural language query) parameter for AI-powered episode filtering.

    ### Response when configured
    ```json
    {
      "enabled": true,
      "configured": true,
      "api_url": "https://your-llm-server.example.com/v1"
    }
    ```

    ### Response when not configured
    ```json
    {
      "enabled": false,
      "configured": false,
      "api_url": "not configured"
    }
    ```

    **Note:** When LLM is not configured, the `nlq` parameter is silently ignored and all episodes are returned.
    """
    return {
        "enabled": settings.LLM_ENABLED,
        "configured": bool(settings.LLM_API_URL),
        "api_url": settings.LLM_API_URL or "not configured",
        "model": settings.LLM_MODEL_NAME,
        "allow_external": settings.LLM_ALLOW_EXTERNAL,
    }


@app.get("/health/cache", tags=["Health"], summary="📊 Cache statistics")
async def cache_health_check() -> dict:
    """
    **View Redis cache statistics.**

    Monitor cache health, see what's cached, and check memory usage.

    ### Response
    ```json
    {
      "status": "connected",
      "total_keys": 42,
      "cached_items": {
        "shows": 15,
        "episodes": 12,
        "seasons": 8,
        "searches": 5
      },
      "master_caches": {
        "show_list": true,
        "show_index": true
      },
      "ttl_seconds": {
        "shows_list": 2592000,
        "show_index": 2592000
      },
      "ttl_config": {
        "ongoing_shows": "604800 (7 days)",
        "finished_shows": "31536000 (1 year)",
        "show_list": "2592000 (30 days)"
      },
      "memory": {
        "used": "18.45M",
        "peak": "20.12M"
      }
    }
    ```
    """
    return await get_cache_stats()


@app.get("/metrics", include_in_schema=False)
async def prometheus_metrics() -> Response:
    """Prometheus-formatted metrics endpoint.

    Returns the current value of all counters defined in `app.core.metrics`.
    Scraped by a Prometheus server to monitor cache efficiency and (in
    follow-up work) upstream health.

    Not part of the public API — hidden from the OpenAPI schema so it
    doesn't clutter the docs. Stable URL convention for Prometheus tooling.
    """
    body, content_type = render_metrics()
    return Response(content=body, media_type=content_type)
