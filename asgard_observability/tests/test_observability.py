"""Tests for the shared asgard_observability module (asgard#588).

The module is a thin facade over sentry_sdk + python logging, so tests
exercise:

- Public API surface (setup_observability accepts what callers pass).
- The before_send cluster-noise filter logic (no Sentry SDK needed).
- The JSON formatter shape (matches what Loki ingestion keys off).
- Sample-rate range validation.
- Idempotent re-init.
- Lazy import of sentry_sdk (logging works without it on path).
- Wiring: setup_observability invokes sentry_sdk.init with the right args.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

from asgard_observability import (
    CLUSTER_TRACE_PROPAGATION_TARGETS,
    DEFAULT_PROFILES_SAMPLE_RATE,
    DEFAULT_TRACES_SAMPLE_RATE,
    JSONFormatter,
    chain_before_send,
    default_before_send,
    setup_logging,
    setup_observability,
)

# ---------------------------------------------------------------------------
# default_before_send — cluster noise filter
# ---------------------------------------------------------------------------


def test_default_before_send_keeps_normal_events() -> None:
    """Real application errors pass through unchanged."""
    event = {
        "exception": {
            "values": [
                {
                    "value": "KeyError: 'missing'",
                    "stacktrace": {
                        "frames": [
                            {"filename": "/app/views.py", "lineno": 42},
                        ],
                    },
                },
            ],
        },
    }
    assert default_before_send(event, {}) is event


def test_default_before_send_drops_inline_python_strings() -> None:
    """`python -c` diagnostic invocations have <string> frames → drop."""
    event = {
        "exception": {
            "values": [
                {
                    "value": "django.core.exceptions.ImproperlyConfigured",
                    "stacktrace": {
                        "frames": [
                            {"filename": "<string>", "lineno": 1},
                            {"filename": "/app/django/db/models/base.py", "lineno": 100},
                        ],
                    },
                },
            ],
        },
    }
    assert default_before_send(event, {}) is None


def test_default_before_send_keeps_chained_when_only_inner_is_inline() -> None:
    """Chained exception with a real outer error must survive even if inner is inline."""
    event = {
        "exception": {
            "values": [
                {
                    # Inner (chained-from) is the inline-python one
                    "value": "ImproperlyConfigured",
                    "stacktrace": {"frames": [{"filename": "<string>"}]},
                },
                {
                    # Outer is a real bug in real code → must keep
                    "value": "RuntimeError: middleware blew up",
                    "stacktrace": {"frames": [{"filename": "/app/middleware.py"}]},
                },
            ],
        },
    }
    assert default_before_send(event, {}) is event


def test_default_before_send_drops_postgres_shutdown_noise() -> None:
    """Postgres FATAL during planned reboot → drop (Prometheus alerts handle pg health)."""
    event = {
        "exception": {
            "values": [
                {
                    "value": "FATAL: the database system is shutting down",
                    "stacktrace": {"frames": [{"filename": "/app/db.py"}]},
                },
            ],
        },
    }
    assert default_before_send(event, {}) is None


def test_default_before_send_drops_disallowed_host_via_hint() -> None:
    """Django DisallowedHost detected via hint (scanners pinging bare IPs)."""

    class DisallowedHost(Exception):
        pass

    event = {"exception": {"values": [{"value": "Invalid HTTP_HOST header"}]}}
    hint = {"exc_info": (DisallowedHost, DisallowedHost("bad"), None)}
    assert default_before_send(event, hint) is None


def test_default_before_send_handles_internal_bug_without_silencing_sentry() -> None:
    """If our hook itself bugs out, the event must still flow to Sentry."""
    # Sentry passes well-formed dicts in practice; simulate a malformed
    # event that would trip the hook's internal logic.
    event: dict = {"exception": None}  # type: ignore[var-annotated]  # malformed on purpose
    result = default_before_send(event, {})
    assert result is event  # hook bug → event survives


def test_default_before_send_no_exception_values_returns_event() -> None:
    """Events without exception.values (e.g. log breadcrumbs) pass through."""
    event = {"message": "info-level breadcrumb"}
    assert default_before_send(event, {}) is event


# ---------------------------------------------------------------------------
# chain_before_send — composition helper
# ---------------------------------------------------------------------------


def test_chain_before_send_composes_left_to_right() -> None:
    """Each hook sees the result of the previous; final return wins."""
    calls: list[str] = []

    def hook_a(event: dict, hint: dict) -> dict:
        calls.append("a")
        event["touched_by_a"] = True
        return event

    def hook_b(event: dict, hint: dict) -> dict:
        calls.append("b")
        event["touched_by_b"] = True
        return event

    chained = chain_before_send(hook_a, hook_b)
    result = chained({}, {})

    assert calls == ["a", "b"]
    assert result == {"touched_by_a": True, "touched_by_b": True}


def test_chain_before_send_short_circuits_on_none() -> None:
    """First hook returning None drops the event; subsequent hooks not called."""
    calls: list[str] = []

    def drop(event: dict, hint: dict) -> None:
        calls.append("drop")
        return None

    def never_called(event: dict, hint: dict) -> dict:
        calls.append("never_called")
        return event

    chained = chain_before_send(drop, never_called)
    assert chained({}, {}) is None
    assert calls == ["drop"]


def test_chain_before_send_skips_none_entries() -> None:
    """Passing None in the hook list is fine — useful for optional service hooks."""
    chained = chain_before_send(None, default_before_send, None)
    # Real event should pass through default_before_send untouched
    event = {"exception": {"values": [{"value": "real bug"}]}}
    assert chained(event, {}) is event


# ---------------------------------------------------------------------------
# JSONFormatter
# ---------------------------------------------------------------------------


def test_json_formatter_emits_standard_fields() -> None:
    """Standard fields (timestamp/level/logger/message/service/pid) always present."""
    formatter = JSONFormatter("portal")
    record = logging.LogRecord(
        name="portal.access",
        level=logging.INFO,
        pathname="x.py",
        lineno=1,
        msg="request done",
        args=(),
        exc_info=None,
    )
    out = json.loads(formatter.format(record))
    assert out["service"] == "portal"
    assert out["level"] == "INFO"
    assert out["logger"] == "portal.access"
    assert out["message"] == "request done"
    assert out["pid"] == record.process
    assert "timestamp" in out


def test_json_formatter_includes_extra_fields() -> None:
    """Keys in extra= that aren't LogRecord builtins appear in JSON output."""
    formatter = JSONFormatter("potato")
    record = logging.LogRecord(
        name="search",
        level=logging.INFO,
        pathname="x.py",
        lineno=1,
        msg="hit",
        args=(),
        exc_info=None,
    )
    # Simulate `logger.info(..., extra={"query": "...", "duration_ms": 150})`
    record.query = "inception"  # type: ignore[attr-defined]
    record.duration_ms = 150  # type: ignore[attr-defined]
    out = json.loads(formatter.format(record))
    assert out["query"] == "inception"
    assert out["duration_ms"] == 150


def test_json_formatter_includes_exception_traceback() -> None:
    """Exception logging produces an `exception` field with the formatted traceback."""
    formatter = JSONFormatter("sentinel")
    try:
        raise ValueError("boom")
    except ValueError:
        exc_info = sys.exc_info()
    record = logging.LogRecord(
        name="sentinel.app",
        level=logging.ERROR,
        pathname="x.py",
        lineno=1,
        msg="failed",
        args=(),
        exc_info=exc_info,
    )
    out = json.loads(formatter.format(record))
    assert "exception" in out
    assert "ValueError: boom" in out["exception"]


# ---------------------------------------------------------------------------
# setup_logging
# ---------------------------------------------------------------------------


def test_setup_logging_idempotent_no_handler_duplication() -> None:
    """Re-init replaces handlers; never accumulates duplicates."""
    setup_logging("test-svc", force_format="json")
    setup_logging("test-svc", force_format="json")
    root = logging.getLogger()
    assert len(root.handlers) == 1


def test_setup_logging_json_format_emits_service_name() -> None:
    """JSON format embeds the service_name argument."""
    setup_logging("elfai", force_format="json")
    root = logging.getLogger()
    handler = root.handlers[0]
    formatter = handler.formatter
    assert isinstance(formatter, JSONFormatter)
    assert formatter.service_name == "elfai"


def test_setup_logging_text_format_uses_plain_formatter() -> None:
    """Text format = stdlib Formatter, not JSONFormatter."""
    setup_logging("dev", force_format="text")
    handler = logging.getLogger().handlers[0]
    assert not isinstance(handler.formatter, JSONFormatter)


def test_setup_logging_silences_noisy_third_party_loggers() -> None:
    """uvicorn.access + httpx are bumped to WARNING (cluster baseline)."""
    # Pre-condition: set them to INFO to verify the function lowers them.
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.INFO)
    setup_logging("test-svc")
    assert logging.getLogger("uvicorn.access").level == logging.WARNING
    assert logging.getLogger("httpx").level == logging.WARNING


def test_setup_logging_respects_log_level_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """LOG_LEVEL env sets root logger level."""
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    setup_logging("test-svc", force_format="json")
    assert logging.getLogger().level == logging.WARNING


def test_setup_logging_debug_defaults_to_text_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LOG_LEVEL=DEBUG → text format unless LOG_FORMAT overrides."""
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    setup_logging("test-svc")
    handler = logging.getLogger().handlers[0]
    assert not isinstance(handler.formatter, JSONFormatter)


# ---------------------------------------------------------------------------
# setup_observability — public single-call API
# ---------------------------------------------------------------------------


def test_setup_observability_skips_sentry_when_no_dsn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No SENTRY_DSN in env + no kwarg → Sentry init is not called."""
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    fake_sdk = MagicMock()
    with patch.dict(sys.modules, {"sentry_sdk": fake_sdk}):
        setup_observability("test-svc")
    fake_sdk.init.assert_not_called()


def test_setup_observability_calls_sentry_init_with_cluster_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify the cluster baseline ends up in the sentry_sdk.init call."""
    monkeypatch.setenv("SENTRY_DSN", "https://example@sentry.carlsen.io/1")
    monkeypatch.setenv("GIT_SHA", "abc1234")
    fake_sdk = MagicMock()
    with patch.dict(sys.modules, {"sentry_sdk": fake_sdk}):
        setup_observability("portal")
    fake_sdk.init.assert_called_once()
    kwargs = fake_sdk.init.call_args.kwargs
    assert kwargs["dsn"] == "https://example@sentry.carlsen.io/1"
    assert kwargs["traces_sample_rate"] == DEFAULT_TRACES_SAMPLE_RATE
    assert kwargs["profiles_sample_rate"] == DEFAULT_PROFILES_SAMPLE_RATE
    assert kwargs["environment"] == "production"
    assert kwargs["release"] == "abc1234"
    assert kwargs["trace_propagation_targets"] == list(CLUSTER_TRACE_PROPAGATION_TARGETS)
    assert kwargs["server_name"] == "portal"
    # before_send is chained — verify it's a callable, not the raw default
    # (we composed it through chain_before_send even when no extra hook).
    assert callable(kwargs["before_send"])


def test_setup_observability_validates_traces_sample_rate_lower_bound() -> None:
    """Negative sample rate is rejected at the boundary."""
    with pytest.raises(ValueError, match="traces_sample_rate"):
        setup_observability("test-svc", traces_sample_rate=-0.1)


def test_setup_observability_validates_traces_sample_rate_upper_bound() -> None:
    """Sample rate >1.0 is rejected."""
    with pytest.raises(ValueError, match="traces_sample_rate"):
        setup_observability("test-svc", traces_sample_rate=1.5)


def test_setup_observability_validates_profiles_sample_rate() -> None:
    """profiles_sample_rate gets the same validation."""
    with pytest.raises(ValueError, match="profiles_sample_rate"):
        setup_observability("test-svc", profiles_sample_rate=2.0)


def test_setup_observability_chains_extra_before_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A service-supplied extra_before_send runs AFTER the cluster default."""
    monkeypatch.setenv("SENTRY_DSN", "https://example@sentry.carlsen.io/1")
    call_order: list[str] = []

    def extra(event: dict, hint: dict) -> dict:
        call_order.append("extra")
        return event

    fake_sdk = MagicMock()
    with patch.dict(sys.modules, {"sentry_sdk": fake_sdk}):
        setup_observability("portal", extra_before_send=extra)

    chained = fake_sdk.init.call_args.kwargs["before_send"]
    # Real event survives default + extra; we should see extra invoked.
    chained({"exception": {"values": [{"value": "real bug"}]}}, {})
    assert call_order == ["extra"]


def test_setup_observability_skips_extra_when_cluster_default_drops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cluster default drops first → extra_before_send isn't called."""
    monkeypatch.setenv("SENTRY_DSN", "https://example@sentry.carlsen.io/1")
    extra_called = False

    def extra(event: dict, hint: dict) -> dict:
        nonlocal extra_called
        extra_called = True
        return event

    fake_sdk = MagicMock()
    with patch.dict(sys.modules, {"sentry_sdk": fake_sdk}):
        setup_observability("portal", extra_before_send=extra)

    chained = fake_sdk.init.call_args.kwargs["before_send"]
    # postgres-shutdown noise → cluster default drops, extra never runs
    event = {"exception": {"values": [{"value": "FATAL: the database system is shutting down"}]}}
    assert chained(event, {}) is None
    assert extra_called is False


def test_setup_observability_passes_through_integrations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Integrations kwarg flows into sentry_sdk.init untouched."""
    monkeypatch.setenv("SENTRY_DSN", "https://example@sentry.carlsen.io/1")
    fake_django_integration = MagicMock(name="DjangoIntegration")
    fake_sdk = MagicMock()
    with patch.dict(sys.modules, {"sentry_sdk": fake_sdk}):
        setup_observability(
            "elfai",
            integrations=[fake_django_integration],
        )
    assert fake_sdk.init.call_args.kwargs["integrations"] == [fake_django_integration]


def test_setup_observability_extra_sentry_kwargs_merged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """extra_sentry_kwargs escape hatch reaches the SDK (e.g. send_default_pii=False)."""
    monkeypatch.setenv("SENTRY_DSN", "https://example@sentry.carlsen.io/1")
    fake_sdk = MagicMock()
    with patch.dict(sys.modules, {"sentry_sdk": fake_sdk}):
        setup_observability(
            "soldprice",
            extra_sentry_kwargs={"send_default_pii": False, "enable_tracing": True},
        )
    kwargs = fake_sdk.init.call_args.kwargs
    assert kwargs["send_default_pii"] is False
    assert kwargs["enable_tracing"] is True


def test_setup_observability_configure_sentry_false_skips_init(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """configure_sentry=False skips Sentry even when DSN is set (logging-only mode)."""
    monkeypatch.setenv("SENTRY_DSN", "https://example@sentry.carlsen.io/1")
    fake_sdk = MagicMock()
    with patch.dict(sys.modules, {"sentry_sdk": fake_sdk}):
        setup_observability("admin-tool", configure_sentry=False)
    fake_sdk.init.assert_not_called()


def test_setup_observability_configure_logging_false_skips_logging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """configure_logging=False leaves root logger handlers untouched (Django-style)."""
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    root = logging.getLogger()
    # Establish a known state and a sentinel handler.
    for h in root.handlers[:]:
        root.removeHandler(h)
    sentinel = logging.StreamHandler()
    root.addHandler(sentinel)
    try:
        setup_observability("django-svc", configure_logging=False)
        assert sentinel in root.handlers
    finally:
        root.removeHandler(sentinel)


def test_setup_observability_explicit_dsn_overrides_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sentry_dsn kwarg wins over SENTRY_DSN env."""
    monkeypatch.setenv("SENTRY_DSN", "https://from-env@sentry.carlsen.io/1")
    fake_sdk = MagicMock()
    with patch.dict(sys.modules, {"sentry_sdk": fake_sdk}):
        setup_observability(
            "test-svc",
            sentry_dsn="https://from-kwarg@sentry.carlsen.io/2",
        )
    assert fake_sdk.init.call_args.kwargs["dsn"] == "https://from-kwarg@sentry.carlsen.io/2"


def test_setup_observability_release_fallback_to_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No GIT_SHA env, no release kwarg → 'unknown' (matches existing service pattern)."""
    monkeypatch.setenv("SENTRY_DSN", "https://example@sentry.carlsen.io/1")
    monkeypatch.delenv("GIT_SHA", raising=False)
    fake_sdk = MagicMock()
    with patch.dict(sys.modules, {"sentry_sdk": fake_sdk}):
        setup_observability("test-svc")
    assert fake_sdk.init.call_args.kwargs["release"] == "unknown"


def test_setup_observability_release_kwarg_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """release kwarg overrides GIT_SHA env (services that compute their own)."""
    monkeypatch.setenv("SENTRY_DSN", "https://example@sentry.carlsen.io/1")
    monkeypatch.setenv("GIT_SHA", "from-env")
    fake_sdk = MagicMock()
    with patch.dict(sys.modules, {"sentry_sdk": fake_sdk}):
        setup_observability("test-svc", release="1.2.3")
    assert fake_sdk.init.call_args.kwargs["release"] == "1.2.3"


def test_setup_observability_idempotent_re_init(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Calling setup_observability twice is safe — handlers don't accumulate."""
    monkeypatch.setenv("SENTRY_DSN", "https://example@sentry.carlsen.io/1")
    fake_sdk = MagicMock()
    with patch.dict(sys.modules, {"sentry_sdk": fake_sdk}):
        setup_observability("test-svc")
        setup_observability("test-svc")
    # Sentry SDK init called twice (which is idempotent by SDK contract).
    assert fake_sdk.init.call_count == 2
    # Logging never accumulated handlers.
    assert len(logging.getLogger().handlers) == 1


def test_setup_observability_custom_trace_propagation_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """epguides-api / llm-router pass a custom propagation list — must reach SDK."""
    monkeypatch.setenv("SENTRY_DSN", "https://example@sentry.carlsen.io/1")
    custom = ["epguides.com", "api.tvmaze.com", "localhost"]
    fake_sdk = MagicMock()
    with patch.dict(sys.modules, {"sentry_sdk": fake_sdk}):
        setup_observability("epguides-api", trace_propagation_targets=custom)
    assert fake_sdk.init.call_args.kwargs["trace_propagation_targets"] == custom


def test_setup_observability_logs_after_init_emit_service_name(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """End-to-end: after setup, a logger call produces JSON tagged with service."""
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    setup_observability("portal", log_format="json")
    logging.getLogger("portal.test").info("hello", extra={"path": "/health"})
    captured = capsys.readouterr()
    # Last line is the log line we just emitted (or the only line).
    lines = [line for line in captured.out.strip().splitlines() if line.strip()]
    assert lines, "expected a log line on stdout"
    payload = json.loads(lines[-1])
    assert payload["service"] == "portal"
    assert payload["message"] == "hello"
    assert payload["path"] == "/health"


# ---------------------------------------------------------------------------
# Hygiene
# ---------------------------------------------------------------------------


def teardown_function(_fn: object) -> None:
    """Reset root logger between tests so handler counts stay deterministic."""
    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)
    root.setLevel(logging.WARNING)
    # Re-enable propagation defaults on third-party loggers we tweaked.
    for name in ("uvicorn.access", "httpx"):
        logger = logging.getLogger(name)
        logger.setLevel(logging.NOTSET)
    # Don't leak env state from monkeypatch.setenv usage in earlier tests.
    os.environ.pop("LOG_LEVEL", None)
    os.environ.pop("LOG_FORMAT", None)
