"""
Optional observability wiring.

Everything in this module is disabled unless the deployment sets the
corresponding environment variables.
"""

from app.core.config import settings


def init_observability(release: str) -> None:
    """Initialise optional error tracking and tracing."""
    if not settings.SENTRY_DSN:
        return

    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        profiles_sample_rate=settings.SENTRY_PROFILES_SAMPLE_RATE,
        # Propagate Sentry traces to the upstream HTTP services this API
        # talks to so distributed traces span the API -> upstream boundary
        # cleanly. Sentry itself receives traces via the DSN HTTP endpoint;
        # it does NOT belong in this list (it's not a downstream service
        # the API calls in the request path).
        trace_propagation_targets=["epguides.com", "api.tvmaze.com", "localhost"],
        release=release,
        environment=settings.SENTRY_ENVIRONMENT,
    )
