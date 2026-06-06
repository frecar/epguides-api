"""Prometheus metrics for the epguides API.

Exposes cache hit/miss counters that tools (Grafana, Prometheus, etc.)
can scrape from the `/metrics` endpoint to monitor cache efficiency.

Documented in CLAUDE.md "Observability gaps" section.

## Ingest freshness heartbeat

`epguides_ingest_last_success_timestamp{source}` is a per-source freshness
gauge: the unix epoch of the most recent *successful* upstream fetch from
each data source (epguides.com, tvmaze). It lets a monitoring system page
when an upstream source stops returning fresh data while requests are still
arriving — a silently-stale scrape would otherwise be invisible.

Two design points keep this honest for a request-driven (pull) API:

* **Pre-initialised to 0 at startup** (`init_ingest_freshness`). A labelled
  Prometheus gauge does not appear in the exposition until `.labels(...)` is
  touched; without pre-init, a freshly-booted process that hasn't served a
  successful fetch yet would have the series *absent*, which an
  absence-paging staleness rule reads as a dead producer (false page). The 0
  placeholder makes the series continuously present from boot: it means "no
  successful fetch since this process started", which a demand-aware
  staleness rule correctly ignores (there is no recent successful traffic to
  be stale *relative to*).
* **Demand-aware alerting lives downstream.** Because there is no guaranteed
  import cadence here, the gauge ageing during a quiet period is not a fault
  — only "recent successful traffic, then it stopped" is. The producer's job
  is just to emit the timestamp honestly; the threshold + demand guard are
  the alert rule's concern.

## Multi-worker mode

uvicorn runs with `--workers 5` in production (one process per CPU core).
Each worker has its own in-memory `prometheus_client` registry — without
coordination, `/metrics` only returns one worker's view and the
aggregated counters are 5x under-reported.

When `PROMETHEUS_MULTIPROC_DIR` is set in the environment, the
`prometheus_client` library writes counter state to memory-mapped files
in that directory, one per process. The `/metrics` endpoint aggregates
across all files via `MultiProcessCollector` to return the correct sum.

In dev (single-worker), the env var is unset and we fall back to the
default in-process registry — same behavior as before.
"""

import os
import time

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    CollectorRegistry,
    Counter,
    Gauge,
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
    # with ~50% relative error in exactly the range we care most about.
    # See issue #211 for the dashboard interpolation analysis.
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 7.5, 10.0, 30.0),
)

# Age of the oldest live cache entry per resource type. Updated every 5 minutes
# by a background task that scans Redis TTLs. In multiprocess mode (5 uvicorn
# workers), each worker independently computes the same value from the same
# Redis — max collapses all workers to a single representative value.
# Known limitation: finished-show entries whose remaining TTL has burned below
# the 30-day threshold are classified as the 30-day class, underreporting age
# for very old (>11 months) finished shows. Acceptable — these are the
# lowest-concern population (finished shows don't change).
CACHE_OLDEST_ENTRY_AGE = Gauge(
    "epguides_cache_oldest_entry_age_seconds",
    "Age in seconds of the oldest live cache entry, per resource type (TTL-math derived)",
    labelnames=["type"],
    multiprocess_mode="max",
)

# Per-source ingest freshness heartbeat — unix epoch of the most recent
# *successful* upstream fetch per source. See module docstring for the
# pre-init / demand-aware-alerting rationale. `multiprocess_mode="max"` is the
# correct collapse for a timestamp gauge across uvicorn workers: the freshest
# success across all workers is the true last-success time (a worker that
# served an older success must not drag the aggregate backwards).
INGEST_LAST_SUCCESS = Gauge(
    "epguides_ingest_last_success_timestamp",
    "Unix epoch of the most recent successful upstream fetch per source "
    "(epguides, tvmaze). Pre-initialised to 0 at startup so the series is "
    "continuously present (0 = no successful fetch since process start).",
    labelnames=["source"],
    multiprocess_mode="max",
)

# Sources whose ingest freshness we track. Pre-initialised at startup so the
# gauge series exist from boot (see init_ingest_freshness).
INGEST_SOURCES = ("epguides", "tvmaze")


def init_ingest_freshness() -> None:
    """Pre-initialise the ingest-freshness gauge for every known source to 0.

    A labelled Prometheus gauge is absent from the exposition until its
    label-set is first touched. Without this, a freshly-booted process that
    hasn't yet served a successful upstream fetch would expose *no* series —
    which an absence-paging staleness rule reads as a dead producer and
    false-pages. Seeding 0 makes the series continuously present from boot.

    Idempotent: setting 0 again on an already-set label is harmless. Called
    once from the FastAPI lifespan startup. Must NOT overwrite a real
    timestamp, so this only runs at startup before any fetch has happened;
    `.set(0)` here races nothing because lifespan startup precedes request
    handling.
    """
    for source in INGEST_SOURCES:
        INGEST_LAST_SUCCESS.labels(source=source).set(0)


def record_ingest_success(source: str) -> None:
    """Stamp the ingest-freshness gauge with the current time for `source`.

    Called on every successful upstream fetch. `multiprocess_mode="max"`
    ensures the aggregate across workers reflects the freshest success.
    """
    INGEST_LAST_SUCCESS.labels(source=source).set(time.time())


def update_cache_age_gauge(type_ages: dict[str, float]) -> None:
    """Set the cache age gauge for each resource type. Called by the background task."""
    for cache_type, age_seconds in type_ages.items():
        CACHE_OLDEST_ENTRY_AGE.labels(type=cache_type).set(age_seconds)


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
    """Increment the upstream request counter for the given source and outcome.

    On a `success` outcome, also stamp the per-source ingest-freshness gauge
    so every successful-fetch callsite updates the heartbeat for free.
    """
    UPSTREAM_REQUESTS.labels(source=source, outcome=outcome).inc()
    if outcome == "success":
        record_ingest_success(source)


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
