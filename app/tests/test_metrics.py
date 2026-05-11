"""Tests for prometheus metrics module."""

from app.core.metrics import (
    CACHE_HITS,
    CACHE_MISSES,
    cache_type_from_key,
    record_cache_hit,
    record_cache_miss,
    render_metrics,
)


class TestCacheTypeFromKey:
    """Resource-type extraction from cache keys."""

    def test_extracts_show_type(self) -> None:
        assert cache_type_from_key("show:bigbangtheory") == "show"

    def test_extracts_episodes_type(self) -> None:
        assert cache_type_from_key("episodes:dexter") == "episodes"

    def test_extracts_search_type(self) -> None:
        assert cache_type_from_key("search:walking-dead") == "search"

    def test_unknown_for_keys_without_colon(self) -> None:
        assert cache_type_from_key("standalone") == "unknown"

    def test_extracts_first_segment_only(self) -> None:
        # Key like "season:show_id:5" should still classify as "season".
        assert cache_type_from_key("season:show_id:5") == "season"

    def test_empty_key_returns_unknown(self) -> None:
        # No colon at all → unknown bucket (don't crash on edge case).
        assert cache_type_from_key("") == "unknown"


class TestRecordCacheHitMiss:
    """Counter increment helpers."""

    def test_hit_increments_typed_counter(self) -> None:
        before = CACHE_HITS.labels(type="show")._value.get()
        record_cache_hit("show:abc")
        after = CACHE_HITS.labels(type="show")._value.get()
        assert after == before + 1

    def test_miss_increments_typed_counter(self) -> None:
        before = CACHE_MISSES.labels(type="episodes")._value.get()
        record_cache_miss("episodes:xyz")
        after = CACHE_MISSES.labels(type="episodes")._value.get()
        assert after == before + 1

    def test_different_types_are_separate_series(self) -> None:
        before_show = CACHE_HITS.labels(type="show")._value.get()
        record_cache_hit("episodes:abc")  # different type
        after_show = CACHE_HITS.labels(type="show")._value.get()
        assert after_show == before_show, "Recording an episodes hit should not bump the show counter"

    def test_unknown_type_records_to_unknown_bucket(self) -> None:
        before = CACHE_HITS.labels(type="unknown")._value.get()
        record_cache_hit("no-colon-here")
        after = CACHE_HITS.labels(type="unknown")._value.get()
        assert after == before + 1


class TestRenderMetrics:
    """Prometheus exposition format rendering."""

    def test_returns_bytes_and_content_type(self) -> None:
        body, content_type = render_metrics()
        assert isinstance(body, bytes)
        assert isinstance(content_type, str)

    def test_includes_cache_hit_metric_name(self) -> None:
        record_cache_hit("show:test-render")
        body, _ = render_metrics()
        text = body.decode("utf-8")
        assert "epguides_cache_hits_total" in text

    def test_includes_cache_miss_metric_name(self) -> None:
        record_cache_miss("episodes:test-render-miss")
        body, _ = render_metrics()
        text = body.decode("utf-8")
        assert "epguides_cache_misses_total" in text

    def test_includes_type_label_in_exposition(self) -> None:
        # Use a unique type marker so this test is hermetic regardless of
        # other tests' side effects on shared counters.
        record_cache_hit("uniqkey:test-label")
        body, _ = render_metrics()
        text = body.decode("utf-8")
        assert 'type="uniqkey"' in text
