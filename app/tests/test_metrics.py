"""Tests for prometheus metrics module."""

import os
from unittest.mock import patch

from app.core.metrics import (
    CACHE_HITS,
    CACHE_MISSES,
    cache_type_from_key,
    mark_worker_dead,
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


class TestMultiprocessMode:
    """Multi-worker mode is gated on PROMETHEUS_MULTIPROC_DIR being set.

    These tests verify the fallback behavior (env var unset → use default
    REGISTRY) and the gating logic. The actual multiprocess collection
    happens across real worker processes in production — covering that
    via unit tests would require spawning subprocesses, which is out of
    scope. The gating logic is what matters for correctness here.
    """

    def test_render_falls_back_to_default_registry_when_env_var_unset(self) -> None:
        # Ensure PROMETHEUS_MULTIPROC_DIR is NOT set in the test environment.
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PROMETHEUS_MULTIPROC_DIR", None)
            body, content_type = render_metrics()
            assert isinstance(body, bytes)
            assert isinstance(content_type, str)
            # In single-process mode the cache counters defined at module
            # import time should be visible in the exposition output.
            assert "epguides_cache_hits_total" in body.decode("utf-8")

    def test_render_uses_multiprocess_collector_when_env_var_set(self, tmp_path) -> None:
        # Point at a temp dir so MultiProcessCollector can read whatever
        # mmap files exist (likely none, but the code path executes).
        with patch.dict(os.environ, {"PROMETHEUS_MULTIPROC_DIR": str(tmp_path)}):
            body, content_type = render_metrics()
            # Body may be empty (no .db files in the temp dir), but the
            # call must succeed without raising.
            assert isinstance(body, bytes)
            assert isinstance(content_type, str)

    def test_mark_worker_dead_noop_when_env_var_unset(self) -> None:
        # Should not raise when multiproc mode is not active.
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PROMETHEUS_MULTIPROC_DIR", None)
            mark_worker_dead(99999)  # arbitrary PID, no-op

    def test_mark_worker_dead_invokes_multiprocess_cleanup(self, tmp_path) -> None:
        with patch.dict(os.environ, {"PROMETHEUS_MULTIPROC_DIR": str(tmp_path)}):
            with patch("app.core.metrics.multiprocess.mark_process_dead") as mock_mark:
                mark_worker_dead(12345)
                mock_mark.assert_called_once_with(12345)

    def test_ensure_multiproc_dir_creates_missing_path(self, tmp_path) -> None:
        """The directory used by prometheus_client's multiprocess collector
        must be created before any Counter mutation writes its .db file.
        `_ensure_multiproc_dir` is called on module import; this exercises
        the create-when-missing branch directly without re-importing
        (re-import would re-register Counters and fail with a duplicate-
        timeseries error)."""
        from app.core.metrics import _ensure_multiproc_dir

        target = tmp_path / "metrics_initdir"
        assert not target.exists()
        with patch.dict(os.environ, {"PROMETHEUS_MULTIPROC_DIR": str(target)}):
            _ensure_multiproc_dir()
            assert target.is_dir()

    def test_ensure_multiproc_dir_noop_when_env_unset(self) -> None:
        """No-op (no exception, no directory created) when the env var
        is unset. Called on every import even in single-worker mode."""
        from app.core.metrics import _ensure_multiproc_dir

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PROMETHEUS_MULTIPROC_DIR", None)
            _ensure_multiproc_dir()  # no exception
