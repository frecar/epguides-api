"""
HTTP middleware for request/response logging, timing, security headers, and request ID tracking.

Provides detailed request logging with timing information for monitoring,
adds security headers to all responses, and generates a unique request ID
per request for traceability.
"""

import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Middleware to generate a unique request ID for each request.

    - Generates a UUID4 hex string (32 chars) per request
    - Stores it in request.state.request_id for use by exception handlers
    - Adds X-Request-ID header to every response
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Generate request ID and add to response headers."""
        request_id = uuid.uuid4().hex
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


def get_request_id(request: Request) -> str:
    """Extract request ID from request state, with fallback."""
    return getattr(request.state, "request_id", "unknown")


# Security headers applied to every response
SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "0",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add security headers to all HTTP responses.

    Headers added:
    - X-Content-Type-Options: nosniff
    - X-Frame-Options: DENY
    - X-XSS-Protection: 0 (modern best practice - rely on CSP instead)
    - Referrer-Policy: strict-origin-when-cross-origin
    - Content-Security-Policy: default-src 'none'; frame-ancestors 'none'
    - Permissions-Policy: disallow camera, microphone, geolocation
    - Strict-Transport-Security: 2 years with includeSubDomains and preload
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Add security headers to the response."""
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers[header] = value
        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware to log all HTTP requests and responses.

    Logs:
    - Request method, path, query params, client IP
    - Response status code and processing time
    - Adds X-Process-Time header to responses
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Process request and log details."""
        start_time = time.perf_counter()

        # Extract request info once
        method = request.method
        path = request.url.path
        client_host = request.client.host if request.client else None

        logger.info(
            "Request: %s %s",
            method,
            path,
            extra={
                "method": method,
                "path": path,
                "query_params": dict(request.query_params),
                "client": client_host,
            },
        )

        try:
            response = await call_next(request)
            process_time = time.perf_counter() - start_time

            logger.info(
                "Response: %s %s - %d (%.3fs)",
                method,
                path,
                response.status_code,
                process_time,
                extra={
                    "method": method,
                    "path": path,
                    "status_code": response.status_code,
                    "process_time_seconds": process_time,
                },
            )

            response.headers["X-Process-Time"] = f"{process_time:.3f}"
            return response

        except Exception as e:
            process_time = time.perf_counter() - start_time
            logger.error(
                "Request failed: %s %s (%.3fs) - %s",
                method,
                path,
                process_time,
                e,
                extra={
                    "method": method,
                    "path": path,
                    "error": str(e),
                    "process_time_seconds": process_time,
                },
                exc_info=True,
            )
            raise
