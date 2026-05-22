"""Single-call entry point for service-side observability bootstrap.

Calling code:

    from asgard_observability import setup_observability

    setup_observability(
        service_name="portal",
        # Defaults below match the cluster baseline; override per service.
    )

This:

1. Configures JSON / text logging via :func:`setup_logging`.
2. Calls ``sentry_sdk.init(...)`` with the cluster baseline (DSN from env,
   traces/profiles=0.1, sentry.carlsen.io trace propagation, env-fetched
   GIT_SHA release), with the cluster default ``before_send`` chained with
   the caller's optional ``extra_before_send``.

If no ``SENTRY_DSN`` env var is set (or one is passed via kwarg), Sentry
init is skipped — matches every existing service's pattern of guarding the
init behind a DSN-truthy check. Logging is still configured.

The Sentry SDK is a soft dependency: imported lazily so unit tests / repos
that don't ship it don't get an ImportError just from importing this module.
"""

from __future__ import annotations

import os
from typing import Any

from asgard_observability._before_send import (
    CLUSTER_TRACE_PROPAGATION_TARGETS,
    DEFAULT_PROFILES_SAMPLE_RATE,
    DEFAULT_TRACES_SAMPLE_RATE,
    BeforeSendHook,
    chain_before_send,
    default_before_send,
)
from asgard_observability._logging import setup_logging


def _validate_sample_rate(name: str, value: float) -> None:
    """Sentry SDK silently accepts out-of-range rates; we don't."""
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name}={value!r} out of range [0.0, 1.0]")


def setup_observability(
    service_name: str,
    *,
    environment: str = "production",
    traces_sample_rate: float = DEFAULT_TRACES_SAMPLE_RATE,
    profiles_sample_rate: float = DEFAULT_PROFILES_SAMPLE_RATE,
    sentry_dsn: str | None = None,
    release: str | None = None,
    trace_propagation_targets: tuple[str, ...] | list[str] | None = None,
    integrations: list[Any] | None = None,
    extra_before_send: BeforeSendHook | None = None,
    extra_sentry_kwargs: dict[str, Any] | None = None,
    log_level: str | None = None,
    log_format: str | None = None,
    configure_logging: bool = True,
    configure_sentry: bool = True,
) -> None:
    """One-call bootstrap for cluster observability.

    Args:
        service_name: Required. Surfaces as the ``service`` field in JSON
            logs and as Sentry's ``server_name`` tag for dashboard grouping.
            Must match the service identity in ``cluster.py`` /
            ``containers.py`` so Grafana queries align across signals.
        environment: Passed to Sentry. Default ``"production"`` matches
            every service today; pass ``"development"`` / ``"staging"`` as
            needed.
        traces_sample_rate: Sentry traces ratio (0.0-1.0). Default 0.1
            (cluster baseline per asgard#585).
        profiles_sample_rate: Sentry profiles ratio (0.0-1.0). Default 0.1.
        sentry_dsn: Override the DSN. Default reads ``SENTRY_DSN`` env;
            if empty/missing, Sentry init is skipped.
        release: Override the release tag. Default reads ``GIT_SHA`` env
            (every service deploys with this set in docker-compose), or
            falls back to ``"unknown"``.
        trace_propagation_targets: Override the propagation list. Default:
            ``("sentry.carlsen.io", "localhost")``.
        integrations: Sentry integration objects (DjangoIntegration,
            CeleryIntegration, OpenAIIntegration, etc.). Optional — caller
            ships the imports.
        extra_before_send: Optional service-specific before_send hook.
            Chained AFTER the cluster default; cluster default drops common
            noise first to short-circuit.
        extra_sentry_kwargs: Escape hatch for one-off SDK kwargs (e.g.
            ``send_default_pii=False``, ``enable_tracing=True``). Merged
            into the init call.
        log_level: Override log level. Default reads ``LOG_LEVEL`` env.
        log_format: ``"json"`` or ``"text"``. Default: text when level is
            DEBUG, otherwise JSON. Honours ``LOG_FORMAT`` env.
        configure_logging: Set False to skip logging setup (e.g. Django
            settings already configures ``LOGGING`` dict). Default True.
        configure_sentry: Set False to skip Sentry init (rare — e.g.
            cluster admin scripts that share logging but don't need
            error reporting). Default True.

    Raises:
        ValueError: If sample rates are outside ``[0.0, 1.0]``.

    Idempotent: re-calling replaces existing log handlers and re-runs Sentry
    init (the SDK itself is idempotent: a second ``init()`` replaces the
    previous client).
    """
    _validate_sample_rate("traces_sample_rate", traces_sample_rate)
    _validate_sample_rate("profiles_sample_rate", profiles_sample_rate)

    if configure_logging:
        setup_logging(
            service_name,
            log_level=log_level,
            force_format=log_format,
        )

    if not configure_sentry:
        return

    dsn = sentry_dsn if sentry_dsn is not None else os.environ.get("SENTRY_DSN", "")
    if not dsn:
        # Mirrors every service's existing `if SENTRY_DSN:` guard. Local
        # dev / test runs ship without a DSN; that's not an error.
        return

    # Lazy import — sentry_sdk is a soft dep; tests/repos w/o it can still
    # `import asgard_observability` for the logging helpers.
    import sentry_sdk

    propagation: list[str] = list(
        trace_propagation_targets if trace_propagation_targets is not None else CLUSTER_TRACE_PROPAGATION_TARGETS
    )
    resolved_release = release if release is not None else os.environ.get("GIT_SHA", "unknown")

    init_kwargs: dict[str, Any] = {
        "dsn": dsn,
        "environment": environment,
        "release": resolved_release,
        "traces_sample_rate": traces_sample_rate,
        "profiles_sample_rate": profiles_sample_rate,
        "trace_propagation_targets": propagation,
        "before_send": chain_before_send(default_before_send, extra_before_send),
        "server_name": service_name,
    }
    if integrations is not None:
        init_kwargs["integrations"] = integrations
    if extra_sentry_kwargs:
        init_kwargs.update(extra_sentry_kwargs)

    sentry_sdk.init(**init_kwargs)
