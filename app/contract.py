"""epguides-api registry for the in-process route-contract CI gate.

The engine lives in ``app.contract_engine`` (a deliberate vendored copy of the
shared OpenAPI contract engine — see its module docstring for why this public
repo carries a copy instead of a dependency). This module owns only the
per-app floor below, so engine fixes and failure semantics cannot drift.
"""

# The floor: every path here MUST stay an anonymous, no-required-param, no-path-
# template GET in the generated schema. These are the routes whose 500 / schema-
# drift / disappearance is the regression we refuse to let merge. Listing them
# explicitly is what makes "a route silently vanished from the schema" a hard
# failure rather than a quiet pass (the generated schema alone can't catch its
# own omission). Routes added to the public anonymous surface should be added
# here too.
MUST_COVER: tuple[str, ...] = (
    "/shows/",
    "/health",
    "/health/ready",
    "/health/llm",
    "/health/cache",
)
