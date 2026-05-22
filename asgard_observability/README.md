# asgard_observability

Shared cluster observability — Sentry + logging boilerplate that services
should use instead of copy-pasting their own `sentry_sdk.init` + JSON
formatter. Tracked under [asgard#588](https://github.com/frecar/asgard/issues/588).

## Why

Audit on 2026-05-21 found 8 services each defining their own:

- `sentry_sdk.init(dsn=..., traces_sample_rate=0.1, profiles_sample_rate=0.1, trace_propagation_targets=["sentry.carlsen.io", "localhost"], release=os.environ["GIT_SHA"], environment="production", ...)`
- `before_send` filter — 3 services (portal, soldprice, elfai) reimplement the same `<string>` inline-python frame filter and the postgres-shutdown noise filter
- `JSONFormatter` — 3 services (llm-router, potato, epguides-api) reimplement an almost-identical JSON formatter for Loki ingestion

Cross-cutting changes — new SDK version, sample-rate adjustment, common log
filter — currently require touching 5+ settings files. The drift evidence
is in `feedback_sentry_token_event_write.md`,
`feedback_sentinel_llm_router_silence.md`, and portal#199 (filter present in
one service, absent in two siblings that had the same noise problem).

## Public API

```python
from asgard_observability import setup_observability

setup_observability(
    service_name="portal",
    # All other args have cluster-baseline defaults; override per service.
)
```

That's it. The function:

1. Configures JSON / text logging (`setup_logging`).
2. Calls `sentry_sdk.init(...)` with the cluster baseline, with a chained
   `before_send` (cluster default + the service's optional extra hook).
3. Skips Sentry init if no `SENTRY_DSN` is set (matches every service's
   existing `if SENTRY_DSN:` guard).

## What's codified

| Setting | Default | Source |
|---|---|---|
| `traces_sample_rate` | `0.1` | asgard#585 audit |
| `profiles_sample_rate` | `0.1` | asgard#585 audit |
| `trace_propagation_targets` | `("sentry.carlsen.io", "localhost")` | matches 6/8 services today |
| `release` | `GIT_SHA` env / `"unknown"` | docker-compose ships this on every service |
| `environment` | `"production"` | services override via env-file |
| `before_send` | drops `<string>` inline-python + postgres-shutdown + `DisallowedHost` | extracted from portal/soldprice/elfai |
| Log format | JSON (text when `LOG_LEVEL=DEBUG`) | matches llm-router/potato/epguides existing pattern |
| `service` field | injected into every JSON log line | Loki queries key off it |

## Extending: service-specific noise filters

Services with extra `before_send` logic (portal's ADFS filter, soldprice's
"too many clients" fingerprint, elfai's similar) pass their hook via
`extra_before_send=`. It runs AFTER the cluster default, so cluster noise
short-circuits before the service-specific code runs.

```python
def _portal_adfs_filter(event, hint):
    # ... drop AADSTS54005 / AADSTS9002313 events ...
    return event

setup_observability(
    service_name="portal",
    extra_before_send=_portal_adfs_filter,
    integrations=[DjangoIntegration(), CeleryIntegration()],
)
```

## Distribution model

`asgard_observability/` is installable as a Python subpackage from the asgard
git repo. Services should pin an asgard revision and install the
`asgard_observability` subdirectory instead of vendor-copying this module.

With `uv`, add a dependency and source entry like:

```toml
[project]
dependencies = [
    "asgard-observability",
]

[tool.uv.sources]
asgard-observability = { git = "https://github.com/frecar/asgard.git", subdirectory = "asgard_observability", rev = "main" }
```

For non-`uv` consumers, pip can install the same package shape:

```sh
pip install "asgard-observability @ git+https://github.com/frecar/asgard.git@main#subdirectory=asgard_observability"
```

The package version lives in `asgard_observability/pyproject.toml`; bump it
deliberately when the public API changes.

## Migration plan

The 8 service migrations are N follow-up PRs (one per service), not this PR.
Per asgard#588 sub-issues:

1. **llm-router** — simplest (no integrations, custom propagation list). Good first migration.
2. **potato** — also simple (no integrations).
3. **epguides-api** — custom propagation list (`epguides.com`, `api.tvmaze.com`).
4. **sentinel** — two callsites (settings.py + app.py); collapse to one in app.py.
5. **soldprice** — `DjangoIntegration` + `before_send` for pg-shutdown (now in cluster default — verify service-side filter can be removed).
6. **elfai** — `DjangoIntegration` + `CeleryIntegration` + `OpenAIIntegration`; service-specific `<string>` filter (now in cluster default — remove from service).
7. **portal** — heaviest: ADFS filter + secret scrubbing + grouping fingerprint stay in service-specific `extra_before_send=`.
8. **beam** — check if it uses Sentry at all; the file appeared in the grep but may be the agent rather than the server.

Each migration PR:
- Removes the duplicated init code.
- Calls `setup_observability(...)` instead.
- Asserts via test that the equivalent sentry kwargs / log format is preserved.
- Bumps the asgard pin (whatever distribution mechanism we land on).
