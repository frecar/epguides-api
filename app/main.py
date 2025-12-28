"""
Epguides API - High-performance TV show metadata API.

This module provides the main FastAPI application with all routes and middleware configured.
"""

import logging.config
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from app.api.endpoints import shows
from app.core.cache import close_redis_pool
from app.core.config import settings
from app.core.constants import VERSION
from app.core.middleware import RequestLoggingMiddleware
from app.exceptions import EpguidesAPIException, ExternalServiceError

# Setup logging
try:
    from app.core.logging_config import setup_logging

    setup_logging()
except Exception:
    # Fallback to basic logging config
    logging.config.fileConfig("logging.conf", disable_existing_loggers=False)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events."""
    # Startup
    logger.info("Application startup")
    yield
    # Shutdown
    await close_redis_pool()
    logger.info("Application shutdown complete")


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="API for accessing TV show metadata and episode lists from epguides.com",
    version=VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# Request Logging Middleware (if enabled)
if settings.LOG_REQUESTS:
    app.add_middleware(RequestLoggingMiddleware)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(EpguidesAPIException)
async def epguides_exception_handler(request: Request, exc: EpguidesAPIException):
    """Handle custom Epguides API exceptions."""
    logger.error(f"Epguides API error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal error occurred. Please try again later."},
    )


@app.exception_handler(ExternalServiceError)
async def external_service_exception_handler(request: Request, exc: ExternalServiceError):
    """Handle external service errors."""
    logger.error(f"External service error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "External service temporarily unavailable. Please try again later."},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle request validation errors with detailed messages."""
    errors = exc.errors()
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": "Validation error",
            "errors": errors,
        },
    )


# Register Routers
app.include_router(shows.router, prefix="/shows", tags=["Shows"])


@app.get("/", include_in_schema=False)
def root_redirect():
    """Redirects the root URL to the API documentation."""
    return RedirectResponse(url="/docs")


@app.get("/health", tags=["Health"])
def health_check():
    """
    Health check endpoint for monitoring.

    Returns service status. Use this endpoint for load balancer health checks
    and monitoring systems.
    """
    return {"status": "healthy", "service": "epguides-api", "version": VERSION}
