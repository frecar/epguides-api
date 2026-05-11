"""Prometheus metrics for the epguides API.

Exposes cache hit/miss counters that tools (Grafana, Prometheus, etc.)
can scrape from the `/metrics` endpoint to monitor cache efficiency.

Documented in CLAUDE.md "Observability gaps" section.

## Multi-worker mode

uvicorn runs with `--workers 5` in production (one process per CPU core).
Each worker has its own in-memory `prometheus_client` registry — without
coordination, `/metrics` only returns one worker's view and the cluster-
wide counters are 5x under-reported.

When `PROMETHEUS_MULTIPROC_DIR` is set in the environment, the
`prometheus_client` library writes counter state to memory-mapped files
in that directory, one per process. The `/metrics` endpoint aggregates
across all files via `MultiProcessCollector` to return the correct sum.

In dev (single-worker), the env var is unset and we fall back to the
default in-process registry — same behavior as before.
"""

import os

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
    multiprocess,
)


def _ensure_multiproc_dir() -> None:
    """prometheus_client requires PROMETHEUS_MULTIPROC_DIR to exist before any
    Counter/Gauge/etc. writes to it — the library opens <dir>/counter_<pid>.db
    files lazily on the first metric mutation. Create the dir if missing so
    record_cache_hit/miss don't crash with FileNotFoundError on a fresh
    container (tmpfs starts empty)."""
    multiproc_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if multiproc_dir:
        os.makedirs(multiproc_dir, exist_ok=True)


_ensure_multiproc_dir()

CACHE_HITS = Counter(
    "epguides_cache_hits_total",
    "Cache hits broken down by resource type (show, episodes, seasons, search, ...)",
    labelnames=["type"],
)

CACHE_MISSES = Counter(
    "epguides_cache_misses_total",
    "Cache misses broken down by resource type",
    labelnames=["type"],
)

UPSTREAM_REQUESTS = Counter(
    "epguides_upstream_request_total",
    "Upstream HTTP requests by source (epguides, tvmaze) and outcome (success, http_error, timeout, parse_error)",
    labelnames=["source", "outcome"],
)

UPSTREAM_RESPONSE_AGE = Histogram(
    "epguides_upstream_response_age_seconds",
    "Round-trip time for successful upstream HTTP requests (fetch start → response received)",
    labelnames=["source"],
    # 7.5 added between 5.0 and 10.0 because observed epguides.com p95 sits
    # in that range — without an intermediate bucket, histogram_quantile()
    # linearly interpolates across a 5-second-wide gap and reports a p95
    # with ~50% relative error (asgard PR #677 Grafana panel, issue #211).
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 7.5, 10.0, 30.0),
)


def cache_type_from_key(cache_key: str) -> str:
    """Extract the resource type from a cache key.

    Cache keys follow the pattern `<type>:<id>` (e.g. `show:bigbangtheory`,
    `episodes:dexter`, `search:walking-dead`). The portion before the first
    `:` is the type label. Falls back to `"unknown"` for malformed keys so
    the counter still records something rather than crashing.
    """
    if ":" not in cache_key:
        return "unknown"
    return cache_key.split(":", 1)[0]


def record_cache_hit(cache_key: str) -> None:
    """Increment the cache-hit counter for the resource type in this key."""
    CACHE_HITS.labels(type=cache_type_from_key(cache_key)).inc()


def record_cache_miss(cache_key: str) -> None:
    """Increment the cache-miss counter for the resource type in this key."""
    CACHE_MISSES.labels(type=cache_type_from_key(cache_key)).inc()


def record_upstream_request(source: str, outcome: str) -> None:
    """Increment the upstream request counter for the given source and outcome."""
    UPSTREAM_REQUESTS.labels(source=source, outcome=outcome).inc()


def observe_upstream_response_age(source: str, duration_seconds: float) -> None:
    """Record an upstream response latency observation."""
    UPSTREAM_RESPONSE_AGE.labels(source=source).observe(duration_seconds)


def render_metrics() -> tuple[bytes, str]:
    """Return the current metrics in Prometheus exposition format.

    Returns a (body, content_type) pair. When `PROMETHEUS_MULTIPROC_DIR`
    is set, aggregates across all worker processes via
    `MultiProcessCollector`. Otherwise reads from the default in-process
    registry (single-worker or test mode).
    """
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        return generate_latest(registry), CONTENT_TYPE_LATEST
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


def mark_worker_dead(pid: int) -> None:
    """Clean up multiprocess metric files for a terminated worker.

    Called on uvicorn worker shutdown to prevent indefinite accumulation
    of `gauge_*.db` files in `PROMETHEUS_MULTIPROC_DIR`. No-op when
    multiproc mode is not active.
    """
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        multiprocess.mark_process_dead(pid)
