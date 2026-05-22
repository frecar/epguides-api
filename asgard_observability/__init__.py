"""Shared cluster observability — Sentry + logging boilerplate.

Eliminates the duplicated `sentry_sdk.init(...)` + JSON logging setup currently
copy-pasted across 8 services (sentinel, soldprice, potato, elfai, portal,
llm-router, epguides-api, beam). See asgard#588 for the audit that found this.

## Usage (target API services migrate to)

    from asgard_observability import setup_observability

    setup_observability(
        service_name="portal",
        # All other args have cluster-baseline defaults.
        # Pass `extra_before_send=` if a service has its own noise filter
        # to chain after the cluster defaults.
    )

## Cluster baseline this codifies

- `traces_sample_rate=0.1` and `profiles_sample_rate=0.1` (asgard#585 audit).
- `trace_propagation_targets=["sentry.carlsen.io", "localhost"]` — matches
  every service except llm-router (no localhost) and epguides-api (custom
  upstream list). Both override via kwargs.
- `release` from `GIT_SHA` env (falls back to caller's value or `"unknown"`).
- `environment="production"` default (services override per env-file).
- JSON logging via `JSONFormatter` for Loki ingestion; switches to
  human-readable when `LOG_LEVEL=DEBUG` for dev convenience.
- `before_send` drops common cluster noise: `<string>` inline-python frames
  (from `python -c` diagnostic sessions) and postgres shutdown FATAL.
  Services chain their own filters via `extra_before_send=`.

## Distribution model (operator decides during review)

This module ships INSIDE the asgard repo so it's owned by infra. Services
consume it via one of three mechanisms (NOT decided in this PR):

1. **Vendor copy** — services drop a copy in their tree (small file, low
   churn, simplest first iteration).
2. **Git submodule** — services pin a specific asgard commit. Aligns with
   how `sentinel/` already references asgard runbooks.
3. **Local PyPI publish** — a Devpi/registry on the cluster serves
   `asgard-observability==X.Y.Z`. Highest fidelity, most setup.

Migration of the 8 services is N follow-up PRs (one per service), tracked
under asgard#588 sub-issues — not in scope here.
"""

from asgard_observability._before_send import (
    CLUSTER_TRACE_PROPAGATION_TARGETS,
    DEFAULT_PROFILES_SAMPLE_RATE,
    DEFAULT_TRACES_SAMPLE_RATE,
    chain_before_send,
    default_before_send,
)
from asgard_observability._logging import JSONFormatter, setup_logging
from asgard_observability._setup import setup_observability

__all__ = [
    "CLUSTER_TRACE_PROPAGATION_TARGETS",
    "DEFAULT_PROFILES_SAMPLE_RATE",
    "DEFAULT_TRACES_SAMPLE_RATE",
    "JSONFormatter",
    "chain_before_send",
    "default_before_send",
    "setup_logging",
    "setup_observability",
]

__version__ = "0.1.0"
