"""
Epguides API - High-performance TV show metadata API.

This module configures the FastAPI application with all routes,
middleware, and exception handlers.
"""

import asyncio
import logging.config
import os
import time
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping
from contextlib import AsyncExitStack, asynccontextmanager, suppress
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from app.api.endpoints import mcp, shows
from app.core.cache import (
    close_redis_pool,
    get_cache_stats,
    get_upstream_last_success,
    probe_redis_round_trip,
    refresh_cache_age_gauges,
)
from app.core.config import settings
from app.core.constants import VERSION, release_name
from app.core.metrics import init_ingest_freshness, mark_worker_dead, render_metrics
from app.core.middleware import RequestIDMiddleware, RequestLoggingMiddleware, SecurityHeadersMiddleware, get_request_id
from app.core.observability import init_observability
from app.exceptions import EpguidesAPIException, ErrorCode, ExternalServiceError
from app.services.show_service import refresh_search_catalogue


def _initialize_logging() -> None:
    """Initialize logging with fallback to basic config."""
    try:
        from app.core.logging_config import setup_logging

        setup_logging()
    except Exception as e:
        logging.basicConfig(level=logging.INFO)
        logging.getLogger(__name__).exception(
            "Structured logging setup failed (%s: %s); using basic INFO logging. Check LOG_LEVEL and LOG_FORMAT.",
            type(e).__name__,
            e,
        )


_initialize_logging()

logger = logging.getLogger(__name__)

_PROCESS_START_TIME = time.time()

_READINESS_UPSTREAM = "epguides"


init_observability(release=release_name())


async def _run_cache_refresh(name: str, refresh: Callable[[], Awaitable[object]]) -> None:
    try:
        await refresh()
    except Exception:
        logger.exception("Failed to refresh %s; retrying at the next scheduled interval", name)


async def _refresh_worker_caches() -> None:
    """Refresh the search catalogue and cache-age gauge every five minutes."""
    while True:
        await asyncio.gather(
            _run_cache_refresh("search catalogue", refresh_search_catalogue),
            _run_cache_refresh("cache-age gauges", refresh_cache_age_gauges),
        )
        await asyncio.sleep(300)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """
    Application lifespan context manager.

    Handles startup and shutdown events.
    """
    logger.info("Application startup")
    init_ingest_freshness()
    async with AsyncExitStack() as cleanup:
        cleanup.push_async_callback(close_redis_pool)
        cleanup.callback(mark_worker_dead, os.getpid())
        task = asyncio.create_task(_refresh_worker_caches())
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
    logger.info("Application shutdown complete")


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


app.add_middleware(RequestIDMiddleware)

if settings.LOG_REQUESTS:
    app.add_middleware(RequestLoggingMiddleware)

app.add_middleware(SecurityHeadersMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)


def _error_log_fields(exc: EpguidesAPIException, request_id: str) -> dict[str, object]:
    return {"error_code": exc.code.value, "request_id": request_id, **exc.context}


@app.exception_handler(EpguidesAPIException)
async def epguides_exception_handler(
    request: Request,
    exc: EpguidesAPIException,
) -> JSONResponse:
    """Render a typed API error as ``{detail, code, hint, context, request_id}``."""
    request_id = get_request_id(request)
    log_fields = _error_log_fields(exc, request_id)
    if not exc.is_client_visible:
        logger.error("API error: %s (request_id=%s)", exc, request_id, exc_info=True, extra=log_fields)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": f"An internal error occurred. Retry later and quote request_id {request_id} if it persists.",
                "code": ErrorCode.INTERNAL_ERROR.value,
                "request_id": request_id,
            },
        )
    if isinstance(exc, ExternalServiceError):
        logger.error("External service error: %s (request_id=%s)", exc, request_id, exc_info=True, extra=log_fields)
    else:
        logger.info("%s: %s", exc.code.value, exc.message, extra=log_fields)
    return JSONResponse(status_code=exc.status_code, content={**exc.to_payload(), "request_id": request_id})


def _describe_validation_error(error: Mapping[str, Any]) -> str:
    location = ".".join(str(part) for part in error.get("loc", ()))
    return f"{location}={error.get('input')!r}: {error.get('msg', 'invalid value')}"


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Reject invalid parameters with one message per field and the offending value."""
    request_id = get_request_id(request)
    errors = exc.errors()
    summary = "; ".join(_describe_validation_error(error) for error in errors)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=jsonable_encoder(
            {
                "detail": f"Validation error: {summary}. See /docs for each parameter's accepted values.",
                "code": ErrorCode.VALIDATION_ERROR.value,
                "errors": errors,
                "request_id": request_id,
            }
        ),
    )


@app.exception_handler(404)
async def not_found_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Handle unknown routes with the method, path and where to find valid routes."""
    request_id = get_request_id(request)
    detail = getattr(exc, "detail", None)
    if detail in (None, "Not Found"):
        detail = f"No route matches {request.method} {request.url.path}. See /docs for the available endpoints."
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={
            "detail": detail,
            "code": ErrorCode.ROUTE_NOT_FOUND.value,
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
            "detail": f"An unexpected error occurred. Retry later and quote request_id {request_id} if it persists.",
            "code": ErrorCode.INTERNAL_ERROR.value,
            "request_id": request_id,
        },
    )


app.include_router(shows.router, prefix="/shows", tags=["Shows"])
app.include_router(mcp.router, tags=["MCP"])


@app.get("/", include_in_schema=False)
def root_index() -> dict[str, str]:
    """Return a terminal API index for browsers and seconds_since_process_start probes."""
    return {
        "status": "ok",
        "service": "epguides-api",
        "name": settings.PROJECT_NAME,
        "version": VERSION,
        "docs_url": "/docs",
        "openapi_url": "/openapi.json",
        "health_url": "/health",
        "ready_url": "/health/ready",
        "shows_url": "/shows",
    }


@app.head("/", include_in_schema=False)
def root_head() -> Response:
    """Return a terminal success for HEAD probes against the API root."""
    return Response(status_code=status.HTTP_200_OK)


@app.get("/health", tags=["Health"], summary="💚 Liveness check")
def health_check() -> dict[str, str]:
    """
    **Liveness check — is the process up and accepting connections?**

    Deliberately cheap and dependency-free: it never touches Redis or an
    upstream, so a container liveness probe (and load balancers) can call it
    frequently without adding load. It proves the process is alive, nothing
    more — for "is the service actually able to serve good data?", use
    [`/health/ready`](#operations-Health-readiness_check_health_ready_get).

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


async def _build_readiness_report() -> tuple[str, int, dict[str, object]]:
    """Run the deep dependency checks and return (status, http_code, body).

    Two independent sub-checks feed an overall status:

    * **redis** — a write/read round-trip. A failure is *degraded, not fatal*:
      the API still serves by fetching upstreams live when the cache is down,
      so we stay ``200`` and just flag the sub-status.
    * **upstream** — freshness of the last successful epguides.com fetch. If no
      success has landed within ``UPSTREAM_STALENESS_HOURS`` the data is
      silently going stale behind the cache, so the service is **not ready**:
      ``503`` with a reason. During the post-deploy cold-start grace window an
      *absent* marker is reported as ``bootstrapping`` (``200``) so a fresh
      rollout is not failed before it serves its first request.

    Overall: ``ok`` when both pass; ``unready`` (``503``) when the upstream is
    stale; ``degraded`` (``200``) when only Redis is unhealthy.

    The body also carries a top-level ``overall_ok`` boolean — ``True`` exactly
    when the overall status is ``ok``. It exists because the nested per-check
    objects have their own ``status`` fields, so a substring/regex body
    assertion on ``"status": "ok"`` can false-pass against a degraded body (a
    healthy sub-check still matches). ``overall_ok`` appears only at the top
    level, making it the collision-proof marker for such monitors.
    """
    threshold_seconds = settings.UPSTREAM_STALENESS_HOURS * 3600.0

    redis_ok, round_trip_ms = await probe_redis_round_trip()
    redis_check: dict[str, object] = {"status": "ok" if redis_ok else "unavailable"}
    if redis_ok and round_trip_ms is not None:
        redis_check["round_trip_ms"] = round(round_trip_ms, 2)

    last_success = await get_upstream_last_success(_READINESS_UPSTREAM)
    upstream_check: dict[str, object] = {
        "source": _READINESS_UPSTREAM,
        "threshold_seconds": threshold_seconds,
    }
    upstream_stale = False

    if last_success is None:
        seconds_since_process_start = time.time() - _PROCESS_START_TIME
        if seconds_since_process_start <= settings.UPSTREAM_FRESHNESS_COLD_START_GRACE_SECONDS:
            upstream_check["status"] = "bootstrapping"
            upstream_check["reason"] = "no upstream fetch yet (within cold-start grace window)"
        else:
            upstream_check["status"] = "stale"
            upstream_check["reason"] = "no successful upstream fetch recorded since startup"
            upstream_stale = True
    else:
        age_seconds = max(0.0, time.time() - last_success)
        upstream_check["last_success_age_seconds"] = round(age_seconds, 1)
        if age_seconds > threshold_seconds:
            upstream_check["status"] = "stale"
            upstream_check["reason"] = (
                f"no successful {_READINESS_UPSTREAM} fetch in "
                f"{age_seconds / 3600.0:.1f}h (threshold {settings.UPSTREAM_STALENESS_HOURS:.1f}h)"
            )
            upstream_stale = True
        else:
            upstream_check["status"] = "ok"

    if upstream_stale:
        overall, http_code = "unready", status.HTTP_503_SERVICE_UNAVAILABLE
    elif not redis_ok:
        overall, http_code = "degraded", status.HTTP_200_OK
    else:
        overall, http_code = "ok", status.HTTP_200_OK

    body: dict[str, object] = {
        "status": overall,
        "overall_ok": overall == "ok",
        "service": "epguides-api",
        "version": VERSION,
        "checks": {"redis": redis_check, "upstream": upstream_check},
    }
    return overall, http_code, body


@app.get("/health/ready", tags=["Health"], summary="🩺 Readiness check (deep)")
async def readiness_check() -> JSONResponse:
    """
    **Readiness check — is the service actually able to serve good data?**

    Unlike [`/health`](#operations-Health-health_check_health_get) (cheap
    liveness), this exercises the real dependency path so an "up but broken"
    instance is visible:

    * **Redis** — a write/read round-trip (not just a ping), so a read-only
      replica or an eviction-storming instance is caught. A Redis failure is
      **degraded, not fatal** (HTTP 200): the API still serves by fetching
      upstreams live, so the instance stays in rotation.
    * **Upstream freshness** — the age of the last successful epguides.com
      fetch. If nothing has succeeded within the staleness threshold the cache
      is masking a silent upstream regression, so the instance is **not ready**
      (HTTP 503) with a reason. A freshly deployed instance gets a cold-start
      grace window before this fires.

    Assert on the body, not just the HTTP code. A synthetic probe wanting
    "everything healthy" should assert the top-level **`overall_ok`** boolean
    (e.g. regex `"overall_ok"\\s*:\\s*true`) — it is `true` exactly when
    `status == "ok"` and the key never appears inside nested check objects, so
    it cannot false-pass. Matching on `"status": "ok"` instead is unsound: a
    *degraded* body still contains that substring via a healthy sub-check
    (e.g. `checks.upstream.status == "ok"` while Redis is down). The
    human-readable tri-state lives in `status` (`ok` / `degraded` / `unready`).

    ### Response (healthy)
    ```json
    {
      "status": "ok",
      "overall_ok": true,
      "service": "epguides-api",
      "version": "123",
      "checks": {
        "redis": {"status": "ok", "round_trip_ms": 1.2},
        "upstream": {
          "source": "epguides",
          "status": "ok",
          "last_success_age_seconds": 812.0,
          "threshold_seconds": 86400.0
        }
      }
    }
    ```

    ### Response (degraded — note the still-present `"status": "ok"` substring)
    ```json
    {
      "status": "degraded",
      "overall_ok": false,
      "service": "epguides-api",
      "version": "123",
      "checks": {
        "redis": {"status": "unavailable"},
        "upstream": {
          "source": "epguides",
          "status": "ok",
          "last_success_age_seconds": 812.0,
          "threshold_seconds": 86400.0
        }
      }
    }
    ```

    ### Status codes
    - `200` — `ok` (all healthy) or `degraded` (Redis down, still serving).
    - `503` — `unready` (no fresh upstream data; the cache is masking staleness).
    """
    _, http_code, body = await _build_readiness_report()
    return JSONResponse(status_code=http_code, content=body)


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
