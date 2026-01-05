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

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="API for accessing TV show metadata and episode lists from epguides.com",
    version=VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
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
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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


@app.get("/health", tags=["Health"])
def health_check() -> dict[str, str]:
    """
    Health check endpoint.

    Use for load balancer health checks and monitoring.
    """
    return {"status": "healthy", "service": "epguides-api", "version": VERSION}


@app.get("/health/llm", tags=["Health"])
def llm_health_check() -> dict[str, str | bool]:
    """
    LLM service health check.

    Returns the LLM configuration status. The LLM is used for
    natural language episode queries via the `nlq` parameter.
    """
    return {
        "enabled": settings.LLM_ENABLED,
        "configured": bool(settings.LLM_API_URL),
        "api_url": settings.LLM_API_URL or "not configured",
    }
