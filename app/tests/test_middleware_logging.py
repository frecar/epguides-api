"""
Tests for RequestLoggingMiddleware dispatch behavior.

Covers request/response logging, timing headers, exception handling,
and edge cases like missing client info.
"""

import logging
from unittest.mock import MagicMock

import pytest

from app.core.middleware import RequestLoggingMiddleware


class TestRequestLoggingMiddleware:
    """Tests for the RequestLoggingMiddleware dispatch method."""

    def _make_request(self, method="GET", path="/health", query_params=None, client_host="127.0.0.1"):
        """Create a mock request with standard attributes."""
        request = MagicMock()
        request.method = method
        request.url.path = path
        request.query_params = query_params or {}
        if client_host:
            request.client.host = client_host
        else:
            request.client = None
        return request

    @pytest.mark.asyncio
    async def test_adds_process_time_header(self):
        """Response should include X-Process-Time header."""
        middleware = RequestLoggingMiddleware(app=MagicMock())
        request = self._make_request()
        response = MagicMock()
        response.status_code = 200
        response.headers = {}

        async def call_next(req):
            return response

        result = await middleware.dispatch(request, call_next)
        assert "X-Process-Time" in result.headers

    @pytest.mark.asyncio
    async def test_process_time_is_numeric(self):
        """X-Process-Time header value should be a parseable float."""
        middleware = RequestLoggingMiddleware(app=MagicMock())
        request = self._make_request()
        response = MagicMock()
        response.status_code = 200
        response.headers = {}

        async def call_next(req):
            return response

        result = await middleware.dispatch(request, call_next)
        process_time = float(result.headers["X-Process-Time"])
        assert process_time >= 0

    @pytest.mark.asyncio
    async def test_logs_request_info(self, caplog):
        """Middleware should log request method and path."""
        middleware = RequestLoggingMiddleware(app=MagicMock())
        request = self._make_request(method="POST", path="/shows/test")
        response = MagicMock()
        response.status_code = 200
        response.headers = {}

        async def call_next(req):
            return response

        with caplog.at_level(logging.INFO, logger="app.core.middleware"):
            await middleware.dispatch(request, call_next)

        log_messages = [r.message for r in caplog.records]
        assert any("POST" in msg and "/shows/test" in msg for msg in log_messages)

    @pytest.mark.asyncio
    async def test_logs_response_status_code(self, caplog):
        """Middleware should log response status code."""
        middleware = RequestLoggingMiddleware(app=MagicMock())
        request = self._make_request()
        response = MagicMock()
        response.status_code = 404
        response.headers = {}

        async def call_next(req):
            return response

        with caplog.at_level(logging.INFO, logger="app.core.middleware"):
            await middleware.dispatch(request, call_next)

        log_messages = [r.message for r in caplog.records]
        assert any("404" in msg for msg in log_messages)

    @pytest.mark.asyncio
    async def test_handles_missing_client(self, caplog):
        """Middleware should handle requests with no client info."""
        middleware = RequestLoggingMiddleware(app=MagicMock())
        request = self._make_request(client_host=None)
        response = MagicMock()
        response.status_code = 200
        response.headers = {}

        async def call_next(req):
            return response

        with caplog.at_level(logging.INFO, logger="app.core.middleware"):
            result = await middleware.dispatch(request, call_next)

        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_exception_is_reraised(self):
        """Middleware should re-raise exceptions after logging."""
        middleware = RequestLoggingMiddleware(app=MagicMock())
        request = self._make_request()

        async def call_next(req):
            raise RuntimeError("handler failed")

        with pytest.raises(RuntimeError, match="handler failed"):
            await middleware.dispatch(request, call_next)

    @pytest.mark.asyncio
    async def test_exception_is_logged(self, caplog):
        """Middleware should log errors when call_next raises."""
        middleware = RequestLoggingMiddleware(app=MagicMock())
        request = self._make_request(method="GET", path="/broken")

        async def call_next(req):
            raise ValueError("something broke")

        with caplog.at_level(logging.ERROR, logger="app.core.middleware"):
            with pytest.raises(ValueError):
                await middleware.dispatch(request, call_next)

        error_messages = [r.message for r in caplog.records if r.levelno >= logging.ERROR]
        assert any("GET" in msg and "/broken" in msg for msg in error_messages)

    @pytest.mark.asyncio
    async def test_log_extra_fields_on_success(self, caplog):
        """Log records should contain structured extra fields for monitoring."""
        middleware = RequestLoggingMiddleware(app=MagicMock())
        request = self._make_request(method="GET", path="/shows/test")
        response = MagicMock()
        response.status_code = 200
        response.headers = {}

        async def call_next(req):
            return response

        with caplog.at_level(logging.INFO, logger="app.core.middleware"):
            await middleware.dispatch(request, call_next)

        response_records = [r for r in caplog.records if hasattr(r, "status_code")]
        assert len(response_records) >= 1
        record = response_records[0]
        assert record.method == "GET"
        assert record.path == "/shows/test"
        assert record.status_code == 200
        assert hasattr(record, "process_time_seconds")

    @pytest.mark.asyncio
    async def test_log_extra_fields_on_error(self, caplog):
        """Error log records should contain method, path, and error details."""
        middleware = RequestLoggingMiddleware(app=MagicMock())
        request = self._make_request(method="POST", path="/mcp")

        async def call_next(req):
            raise TypeError("bad type")

        with caplog.at_level(logging.ERROR, logger="app.core.middleware"):
            with pytest.raises(TypeError):
                await middleware.dispatch(request, call_next)

        error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert len(error_records) >= 1
        record = error_records[0]
        assert record.method == "POST"
        assert record.path == "/mcp"
        assert hasattr(record, "error")

    @pytest.mark.asyncio
    async def test_query_params_logged(self, caplog):
        """Request log should include query parameters."""
        middleware = RequestLoggingMiddleware(app=MagicMock())
        request = self._make_request(path="/shows", query_params={"page": "2", "limit": "10"})
        response = MagicMock()
        response.status_code = 200
        response.headers = {}

        async def call_next(req):
            return response

        with caplog.at_level(logging.INFO, logger="app.core.middleware"):
            await middleware.dispatch(request, call_next)

        request_records = [r for r in caplog.records if hasattr(r, "query_params") and not hasattr(r, "status_code")]
        assert len(request_records) >= 1
        assert request_records[0].query_params == {"page": "2", "limit": "10"}
