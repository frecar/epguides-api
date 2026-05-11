"""Prometheus metrics for the epguides API.

Exposes cache hit/miss counters that tools (Grafana, Prometheus, etc.)
can scrape from the `/metrics` endpoint to monitor cache efficiency.

Documented in CLAUDE.md "Observability gaps" section.
"""

from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, Counter, generate_latest

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


def render_metrics() -> tuple[bytes, str]:
    """Return the current metrics in Prometheus exposition format.

    Returns a (body, content_type) pair. The endpoint handler is expected
    to wrap this in a Response with the content type set to the value
    returned here (the python prometheus_client library defines the exact
    media type, which has evolved across versions).
    """
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
