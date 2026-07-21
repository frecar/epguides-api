from unittest.mock import Mock, patch

import sentry_sdk
import sentry_sdk.transport as transport_mod
from sentry_sdk.transport import Transport

from app.core import observability


def test_observability_is_noop_without_sentry_dsn(monkeypatch):
    sentry_sdk_mock = Mock()
    monkeypatch.setattr(observability.settings, "SENTRY_DSN", None)

    with patch.dict("sys.modules", {"sentry_sdk": sentry_sdk_mock}):
        observability.init_observability(release="test-release")

    sentry_sdk_mock.init.assert_not_called()


def test_observability_initialises_sentry_when_configured(monkeypatch):
    sentry_sdk_mock = Mock()
    monkeypatch.setattr(observability.settings, "SENTRY_DSN", "https://example.invalid/1")
    monkeypatch.setattr(observability.settings, "SENTRY_TRACES_SAMPLE_RATE", 0.25)
    monkeypatch.setattr(observability.settings, "SENTRY_PROFILES_SAMPLE_RATE", 0.05)
    monkeypatch.setattr(observability.settings, "SENTRY_ENVIRONMENT", "test")

    with patch.dict("sys.modules", {"sentry_sdk": sentry_sdk_mock}):
        observability.init_observability(release="test-release")

    # Assert against the exact kwargs the app really passes to
    # sentry_sdk.init, not a constant defined elsewhere in this file --
    # this is what actually proves include_local_variables can't be
    # silently dropped or re-inherited from the SDK default.
    sentry_sdk_mock.init.assert_called_once_with(
        dsn="https://example.invalid/1",
        traces_sample_rate=0.25,
        profiles_sample_rate=0.05,
        trace_propagation_targets=["epguides.com", "api.tvmaze.com", "localhost"],
        release="test-release",
        environment="test",
        include_local_variables=False,
        send_default_pii=False,
    )


class _CapturingTransport(Transport):
    """A real (non-mocked) Sentry transport that records envelopes in memory
    instead of sending them over the network, so a test can inspect the
    exact payload the SDK would have shipped to Sentry."""

    def __init__(self, options=None):
        super().__init__(options)
        self.envelopes = []

    def capture_envelope(self, envelope):
        self.envelopes.append(envelope)


def _frames_with_vars(envelopes):
    found = []
    for envelope in envelopes:
        for item in envelope.items:
            payload = item.payload.json
            if not payload or "exception" not in payload:
                continue
            for exc in payload["exception"]["values"]:
                for frame in exc.get("stacktrace", {}).get("frames", []):
                    if "vars" in frame:
                        found.append(frame)
    return found


def test_real_captured_event_has_no_frame_locals(monkeypatch):
    """End-to-end check using the real sentry_sdk (not mocked): run the
    actual init_observability() call, trigger a real exception with a
    sensitive-looking local variable, and inspect the literal event payload
    the SDK builds. This proves the *behavior* -- no `vars` block on any
    stack frame -- rather than just asserting a flag, which a downstream
    override could silently defeat.
    """
    monkeypatch.setattr(transport_mod, "HttpTransport", _CapturingTransport)
    monkeypatch.setattr(observability.settings, "SENTRY_DSN", "https://public@sentry.example.invalid/1")
    monkeypatch.setattr(observability.settings, "SENTRY_TRACES_SAMPLE_RATE", 0.0)
    monkeypatch.setattr(observability.settings, "SENTRY_PROFILES_SAMPLE_RATE", 0.0)
    monkeypatch.setattr(observability.settings, "SENTRY_ENVIRONMENT", "test")

    observability.init_observability(release="test-release")
    client = sentry_sdk.get_client()
    transport = client.transport
    assert isinstance(transport, _CapturingTransport)

    def _raises():
        api_token = "should-never-be-shipped-to-sentry"  # noqa: F841
        raise ValueError("boom")

    try:
        _raises()
    except ValueError:
        sentry_sdk.capture_exception()
    sentry_sdk.flush()

    assert transport.envelopes, "expected at least one captured envelope"
    leaked = _frames_with_vars(transport.envelopes)
    assert not leaked, f"frame locals leaked into the Sentry event: {leaked}"
