"""Cluster-baseline ``before_send`` filter + composition helpers.

Three patterns drop here (extracted from portal/soldprice/elfai duplication
audited in asgard#588):

1. **Inline ``python -c "..."`` invocations** — diagnostic shell sessions that
   import Django modules without ``django.setup()``. Stack contains
   ``<string>`` frames. Real request/task/management-command code never has
   these. Drops when EVERY exception value's stack matches (avoids hiding a
   real wrapping bug behind an inner shell-driven error).

2. **Postgres FATAL during deliberate shutdown** — libpq emits
   ``the database system is shutting down`` while SIGTERM is in flight
   during planned reboots. Postgres health is alerted via Prometheus
   separately; Sentry shouldn't double-alert.

3. **DisallowedHost** — Django's signal for unmatched ``Host:`` headers is
   noise from internet scanners hitting bare IPs / wrong hostnames. Not
   actionable for any of our services.

Services with their own filter (portal's ADFS scrub, soldprice's
``too many clients`` fingerprint) call :func:`chain_before_send` to compose
their callable after the cluster default — order matters because the cluster
filter drops first and short-circuits.

The filter is wrapped in ``try/except`` so a bug here never silences Sentry.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

# Cluster baselines (derived from the asgard#585 sample-rate audit).
# These match what every service had hard-coded; codified here so a future
# cluster-wide tune is one config change.
DEFAULT_TRACES_SAMPLE_RATE: float = 0.1
DEFAULT_PROFILES_SAMPLE_RATE: float = 0.1
CLUSTER_TRACE_PROPAGATION_TARGETS: tuple[str, ...] = ("sentry.carlsen.io", "localhost")

# Postgres-shutdown noise marker (substring match on exc value).
_POSTGRES_SHUTDOWN_MARKER = "the database system is shutting down"

BeforeSendHook = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any] | None]


def _is_inline_python(exc_value: dict[str, Any]) -> bool:
    """True if ``exc_value`` has any ``<string>`` frame in its stack.

    Matches a frame's ``filename`` field exactly. Sentry's stack frames
    carry ``filename`` as the source descriptor; for ``python -c "..."``
    invocations Python sets this to the literal string ``"<string>"``.
    """
    stacktrace = exc_value.get("stacktrace") or {}
    frames: list[dict[str, Any]] = stacktrace.get("frames") or []
    return any(f.get("filename") == "<string>" for f in frames)


def _is_postgres_shutdown(exc_value: dict[str, Any]) -> bool:
    """True if ``exc_value`` is the libpq shutdown-while-SIGTERM message."""
    msg = exc_value.get("value") or ""
    return _POSTGRES_SHUTDOWN_MARKER in msg


def _is_disallowed_host(hint: dict[str, Any]) -> bool:
    """True if the exception is Django's ``DisallowedHost``.

    Inspects ``hint["exc_info"]`` (a ``(exc_type, exc, tb)`` tuple Sentry
    populates from ``sys.exc_info()``); does not import Django.
    """
    if not hint:
        return False
    exc_info = hint.get("exc_info")
    if not exc_info:
        return False
    exc_type = exc_info[0]
    if exc_type is None:
        return False
    return getattr(exc_type, "__name__", "") == "DisallowedHost"


def default_before_send(
    event: dict[str, Any],
    hint: dict[str, Any],
) -> dict[str, Any] | None:
    """Cluster-baseline before_send: drop common noise patterns.

    Returns ``None`` (drop event) or ``event`` (keep). Always returns ``event``
    on any internal exception so a hook bug can't silence Sentry entirely.

    Drop conditions (ALL exception values in chain must match for drop):

    - ``DisallowedHost`` from hint
    - Inline ``python -c`` invocation (``<string>`` stack frame)
    - Postgres shutdown FATAL (``the database system is shutting down``)
    """
    try:
        if _is_disallowed_host(hint):
            return None
        values: list[dict[str, Any]] = event.get("exception", {}).get("values") or []
        if not values:
            return event
        # chained-exception safety: drop only when EVERY value in the chain
        # matches a noise pattern. If a real wrapping bug includes a benign
        # inner exception we still want the outer one in Sentry.
        if all(_is_inline_python(v) for v in values):
            return None
        if all(_is_postgres_shutdown(v) for v in values):
            return None
    except Exception:
        return event
    return event


def chain_before_send(*hooks: BeforeSendHook | None) -> BeforeSendHook:
    """Compose multiple ``before_send`` hooks left-to-right; first ``None`` wins.

    Use this to extend :func:`default_before_send` with a service-specific
    filter::

        from asgard_observability import (
            chain_before_send,
            default_before_send,
            setup_observability,
        )

        def _portal_adfs_filter(event, hint):
            ...  # drop ADFS callback noise
            return event

        setup_observability(
            service_name="portal",
            extra_before_send=_portal_adfs_filter,
        )

    Equivalent to ``chain_before_send(default_before_send, _portal_adfs_filter)``.
    ``setup_observability`` does this composition automatically when
    ``extra_before_send=`` is passed.

    ``None`` entries are skipped (lets callers pass an optional hook without
    a guard). Each hook receives the result of the previous hook; if any hook
    returns ``None``, subsequent hooks are not called and the event is dropped.
    """
    real_hooks = [h for h in hooks if h is not None]

    def _chained(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
        current: dict[str, Any] | None = event
        for hook in real_hooks:
            if current is None:
                return None
            current = hook(current, hint)
        return current

    return _chained
