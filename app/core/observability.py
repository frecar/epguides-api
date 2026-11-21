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
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.httpx import HttpxIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration
    from sentry_sdk.scrubber import EventScrubber

    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        profiles_sample_rate=settings.SENTRY_PROFILES_SAMPLE_RATE,
        integrations=[
            FastApiIntegration(),
            StarletteIntegration(),
            HttpxIntegration(),
        ],
        trace_propagation_targets=["epguides.com", "api.tvmaze.com", "localhost"],
        release=release,
        environment=settings.SENTRY_ENVIRONMENT,
        include_local_variables=False,
        send_default_pii=False,
        event_scrubber=EventScrubber(recursive=True),
        max_request_body_size="never",
    )
