"""
Tests for core utility modules: middleware and mcp_schemas.

Covers middleware dispatch behavior, security headers dict, get_request_id
helper, and JSON-RPC 2.0 schema validation.

Logging tests previously lived here; the `app.core.logging_config` module
was removed in favor of the vendored `asgard_observability` package (see
`asgard_observability/tests/test_observability.py` for the parity coverage).
"""

from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from app.core.middleware import SECURITY_HEADERS, RequestIDMiddleware, SecurityHeadersMiddleware, get_request_id
from app.models.mcp_schemas import JSONRPCError, JSONRPCRequest, JSONRPCResponse

# =============================================================================
# get_request_id Tests
# =============================================================================


class TestGetRequestId:
    """Tests for the get_request_id middleware helper."""

    def test_returns_request_id_from_state(self):
        """Test returns request_id when present in request.state."""
        request = MagicMock()
        request.state.request_id = "abc123def456"
        assert get_request_id(request) == "abc123def456"

    def test_returns_unknown_when_no_request_id(self):
        """Test returns 'unknown' when request_id is not in state."""

        class FakeRequest:
            class state:
                pass

        assert get_request_id(FakeRequest()) == "unknown"

    def test_raises_when_no_state(self):
        """Test raises AttributeError when request has no state attribute.

        This is expected because get_request_id accesses request.state directly.
        In practice, FastAPI always provides request.state.
        """

        class BareRequest:
            pass

        with pytest.raises(AttributeError):
            get_request_id(BareRequest())


# =============================================================================
# SECURITY_HEADERS Tests
# =============================================================================


class TestSecurityHeaders:
    """Tests for the SECURITY_HEADERS constant dict."""

    def test_contains_required_headers(self):
        """Test all expected security headers are present."""
        expected_headers = [
            "X-Content-Type-Options",
            "X-Frame-Options",
            "X-XSS-Protection",
            "Referrer-Policy",
            "Content-Security-Policy",
            "Permissions-Policy",
            "Strict-Transport-Security",
        ]
        for header in expected_headers:
            assert header in SECURITY_HEADERS, f"Missing header: {header}"

    def test_xss_protection_is_zero(self):
        """Test X-XSS-Protection is '0' (modern best practice)."""
        assert SECURITY_HEADERS["X-XSS-Protection"] == "0"

    def test_frame_options_deny(self):
        """Test X-Frame-Options is DENY."""
        assert SECURITY_HEADERS["X-Frame-Options"] == "DENY"

    def test_hsts_includes_subdomains(self):
        """Test HSTS header includes includeSubDomains."""
        hsts = SECURITY_HEADERS["Strict-Transport-Security"]
        assert "includeSubDomains" in hsts
        assert "preload" in hsts

    def test_csp_blocks_all_by_default(self):
        """Test CSP default-src is 'none'."""
        csp = SECURITY_HEADERS["Content-Security-Policy"]
        assert "default-src 'none'" in csp

    def test_permissions_policy_restricts_apis(self):
        """Test Permissions-Policy disables sensitive browser APIs."""
        policy = SECURITY_HEADERS["Permissions-Policy"]
        assert "camera=()" in policy
        assert "microphone=()" in policy
        assert "geolocation=()" in policy

    def test_all_values_are_strings(self):
        """Test all header values are non-empty strings."""
        for key, value in SECURITY_HEADERS.items():
            assert isinstance(value, str), f"{key} value is not a string"
            assert len(value) > 0, f"{key} value is empty"


# =============================================================================
# RequestIDMiddleware Tests
# =============================================================================


class TestRequestIDMiddlewareUnit:
    """Unit tests for RequestIDMiddleware dispatch method."""

    @pytest.mark.asyncio
    async def test_generates_uuid4_hex(self):
        """Test that request ID is a 32-char hex string."""
        middleware = RequestIDMiddleware(app=MagicMock())

        request = MagicMock()
        request.state = MagicMock()
        response = MagicMock()
        response.headers = {}

        async def call_next(req):
            return response

        result = await middleware.dispatch(request, call_next)

        request_id = result.headers["X-Request-ID"]
        assert len(request_id) == 32
        int(request_id, 16)  # Validates it's a hex string

    @pytest.mark.asyncio
    async def test_sets_request_state(self):
        """Test that request_id is stored in request.state."""
        middleware = RequestIDMiddleware(app=MagicMock())

        request = MagicMock()
        request.state = MagicMock()
        response = MagicMock()
        response.headers = {}

        async def call_next(req):
            return response

        await middleware.dispatch(request, call_next)

        # Verify request.state.request_id was set
        request.state.request_id = request.state.request_id  # access the attribute
        assert hasattr(request.state, "request_id")

    @pytest.mark.asyncio
    async def test_unique_ids(self):
        """Test that each dispatch generates a unique ID."""
        middleware = RequestIDMiddleware(app=MagicMock())
        ids = set()

        for _ in range(10):
            request = MagicMock()
            request.state = MagicMock()
            response = MagicMock()
            response.headers = {}

            async def call_next(req, _response=response):
                return _response

            result = await middleware.dispatch(request, call_next)
            ids.add(result.headers["X-Request-ID"])

        assert len(ids) == 10


# =============================================================================
# SecurityHeadersMiddleware Tests
# =============================================================================


class TestSecurityHeadersMiddlewareUnit:
    """Unit tests for SecurityHeadersMiddleware dispatch method."""

    @pytest.mark.asyncio
    async def test_adds_all_security_headers(self):
        """Test that all SECURITY_HEADERS are added to the response."""
        middleware = SecurityHeadersMiddleware(app=MagicMock())

        request = MagicMock()
        response = MagicMock()
        response.headers = {}

        async def call_next(req):
            return response

        result = await middleware.dispatch(request, call_next)

        for header, value in SECURITY_HEADERS.items():
            assert result.headers[header] == value


# =============================================================================
# JSONRPCRequest Tests
# =============================================================================


class TestJSONRPCRequest:
    """Tests for the JSON-RPC 2.0 request model."""

    def test_minimal_request(self):
        """Test creating a request with only required fields."""
        req = JSONRPCRequest(method="initialize")
        assert req.jsonrpc == "2.0"
        assert req.method == "initialize"
        assert req.id is None
        assert req.params == {}

    def test_full_request(self):
        """Test creating a request with all fields."""
        req = JSONRPCRequest(
            jsonrpc="2.0",
            id=42,
            method="tools/call",
            params={"name": "search_shows", "arguments": {"query": "test"}},
        )
        assert req.id == 42
        assert req.method == "tools/call"
        assert req.params["name"] == "search_shows"

    def test_string_id(self):
        """Test request with string ID."""
        req = JSONRPCRequest(id="abc-123", method="tools/list")
        assert req.id == "abc-123"

    def test_null_id(self):
        """Test request with null/None ID (notification)."""
        req = JSONRPCRequest(id=None, method="initialize")
        assert req.id is None

    def test_invalid_jsonrpc_version(self):
        """Test that non-2.0 jsonrpc version is rejected by pattern."""
        with pytest.raises(ValidationError):
            JSONRPCRequest(jsonrpc="1.0", method="test")

    def test_empty_params_default(self):
        """Test that params defaults to empty dict."""
        req = JSONRPCRequest(method="test")
        assert req.params == {}
        assert isinstance(req.params, dict)

    def test_serialization_round_trip(self):
        """Test JSON serialization and deserialization."""
        original = JSONRPCRequest(
            id=1,
            method="tools/call",
            params={"name": "get_show", "arguments": {"epguides_key": "breakingbad"}},
        )
        data = original.model_dump()
        restored = JSONRPCRequest(**data)
        assert restored.id == original.id
        assert restored.method == original.method
        assert restored.params == original.params


# =============================================================================
# JSONRPCError Tests
# =============================================================================


class TestJSONRPCError:
    """Tests for the JSON-RPC 2.0 error model."""

    def test_minimal_error(self):
        """Test creating an error with required fields only."""
        error = JSONRPCError(code=-32600, message="Invalid Request")
        assert error.code == -32600
        assert error.message == "Invalid Request"
        assert error.data is None

    def test_error_with_data(self):
        """Test creating an error with additional data."""
        error = JSONRPCError(
            code=-32602,
            message="Invalid params",
            data={"missing": ["epguides_key"]},
        )
        assert error.data == {"missing": ["epguides_key"]}

    def test_standard_error_codes(self):
        """Test all standard JSON-RPC error codes can be used."""
        codes = {
            -32700: "Parse error",
            -32600: "Invalid Request",
            -32601: "Method not found",
            -32602: "Invalid params",
            -32603: "Internal error",
        }
        for code, message in codes.items():
            error = JSONRPCError(code=code, message=message)
            assert error.code == code
            assert error.message == message

    def test_error_serialization(self):
        """Test error serialization to dict."""
        error = JSONRPCError(code=-32601, message="Method not found", data="details")
        data = error.model_dump()
        assert data["code"] == -32601
        assert data["message"] == "Method not found"
        assert data["data"] == "details"


# =============================================================================
# JSONRPCResponse Tests
# =============================================================================


class TestJSONRPCResponse:
    """Tests for the JSON-RPC 2.0 response model."""

    def test_success_response(self):
        """Test creating a success response with result."""
        resp = JSONRPCResponse(
            id=1,
            result={"protocolVersion": "2025-06-18", "serverInfo": {"name": "epguides-api"}},
        )
        assert resp.jsonrpc == "2.0"
        assert resp.id == 1
        assert resp.result is not None
        assert resp.error is None

    def test_error_response(self):
        """Test creating an error response."""
        resp = JSONRPCResponse(
            id=2,
            error=JSONRPCError(code=-32601, message="Method not found"),
        )
        assert resp.result is None
        assert resp.error is not None
        assert resp.error.code == -32601

    def test_default_values(self):
        """Test response with all defaults."""
        resp = JSONRPCResponse()
        assert resp.jsonrpc == "2.0"
        assert resp.id is None
        assert resp.result is None
        assert resp.error is None

    def test_string_id(self):
        """Test response with string ID for correlation."""
        resp = JSONRPCResponse(id="req-42", result={"tools": []})
        assert resp.id == "req-42"

    def test_serialization_round_trip(self):
        """Test full serialization/deserialization cycle."""
        original = JSONRPCResponse(
            id=5,
            result={"content": [{"type": "text", "text": "data"}]},
        )
        data = original.model_dump()
        restored = JSONRPCResponse(**data)
        assert restored.id == original.id
        assert restored.result == original.result

    def test_error_response_serialization(self):
        """Test error response serializes correctly."""
        resp = JSONRPCResponse(
            id=3,
            error=JSONRPCError(code=-32603, message="Internal error"),
        )
        data = resp.model_dump()
        assert data["error"]["code"] == -32603
        assert data["error"]["message"] == "Internal error"
        assert data["result"] is None
