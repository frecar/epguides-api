"""
HTTP middleware for request/response logging and timing.

Provides detailed request logging with timing information for monitoring.
"""

import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


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
