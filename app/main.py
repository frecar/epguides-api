"""
Epguides API - High-performance TV show metadata API.

This module configures the FastAPI application with all routes,
middleware, and exception handlers.
"""

import logging.config
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from app.api.endpoints import mcp, shows
from app.core.cache import close_redis_pool
from app.core.config import settings
from app.core.constants import VERSION
from app.core.middleware import RequestLoggingMiddleware
from app.exceptions import EpguidesAPIException, ExternalServiceError

# =============================================================================
# Logging Setup
# =============================================================================

try:
    from app.core.logging_config import setup_logging

    setup_logging()
except Exception:
    # Fallback to basic config if custom setup fails
    logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)


# =============================================================================
# Application Lifespan
# =============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan context manager.

    Handles startup and shutdown events.
    """
    logger.info("Application startup")
    yield
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

# Request logging (if enabled)
if settings.LOG_REQUESTS:
    app.add_middleware(RequestLoggingMiddleware)

# CORS - allow all origins (configure appropriately for production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
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
    logger.error("API error: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal error occurred. Please try again later."},
    )


@app.exception_handler(ExternalServiceError)
async def external_service_exception_handler(
    request: Request,
    exc: ExternalServiceError,
) -> JSONResponse:
    """Handle external service failures."""
    logger.error("External service error: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "External service temporarily unavailable."},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Handle request validation errors with details."""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": "Validation error", "errors": exc.errors()},
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
      "api_url": "https://api.openai.com/v1"
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
    }
