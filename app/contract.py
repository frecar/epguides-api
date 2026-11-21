"""epguides-api registry for the in-process route-contract CI gate.

The engine lives in ``app.contract_engine`` (a deliberate vendored copy of the
shared OpenAPI contract engine — see its module docstring for why this public
repo carries a copy instead of a dependency). This module owns only the
per-app floor below, so engine fixes and failure semantics cannot drift.
"""

MUST_COVER: tuple[str, ...] = (
    "/shows/",
    "/health",
    "/health/ready",
    "/health/llm",
    "/health/cache",
)
