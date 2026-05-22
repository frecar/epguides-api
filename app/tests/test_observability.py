from unittest.mock import Mock, patch

from app.core import observability


def test_observability_is_noop_without_sentry_dsn(monkeypatch):
    sentry_sdk = Mock()
    monkeypatch.setattr(observability.settings, "SENTRY_DSN", None)

    with patch.dict("sys.modules", {"sentry_sdk": sentry_sdk}):
        observability.init_observability(release="test-release")

    sentry_sdk.init.assert_not_called()


def test_observability_initialises_sentry_when_configured(monkeypatch):
    sentry_sdk = Mock()
    monkeypatch.setattr(observability.settings, "SENTRY_DSN", "https://example.invalid/1")
    monkeypatch.setattr(observability.settings, "SENTRY_TRACES_SAMPLE_RATE", 0.25)
    monkeypatch.setattr(observability.settings, "SENTRY_PROFILES_SAMPLE_RATE", 0.05)
    monkeypatch.setattr(observability.settings, "SENTRY_ENVIRONMENT", "test")

    with patch.dict("sys.modules", {"sentry_sdk": sentry_sdk}):
        observability.init_observability(release="test-release")

    sentry_sdk.init.assert_called_once_with(
        dsn="https://example.invalid/1",
        traces_sample_rate=0.25,
        profiles_sample_rate=0.05,
        trace_propagation_targets=["epguides.com", "api.tvmaze.com", "localhost"],
        release="test-release",
        environment="test",
    )
