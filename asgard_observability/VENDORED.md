# Vendored copy of `asgard_observability`

This is a vendored copy of [`asgard_observability/`](https://github.com/frecar/asgard/tree/main/asgard_observability)
from the upstream repo. It centralises Sentry init + JSON logging boilerplate
across services per the upstream issue tracked in
[frecar/asgard#588](https://github.com/frecar/asgard/issues/588).

## Source

- **Repo**: `frecar/asgard`
- **Path**: `asgard_observability/`
- **Synced from commit**: `a70c62b`
- **Synced on**: 2026-05-22 (epguides-api PR for issue #254)

## Why vendored?

Per the upstream `README.md`, three distribution mechanisms were on the table:
vendor copy, git submodule, or local PyPI publish. **Vendor copy** was picked
as the first-cut here (matching the prior service migrations) because:

- No new infra needed (no local PyPI mirror yet).
- Submodule UX is awkward for a small set of files.
- epguides-api builds in Docker from a flat repo checkout; vendoring keeps the
  build self-contained.

The maintainer can flip to a different mechanism in a follow-up; this PR
validates the migration pattern, not the distribution model.

## Drift mitigation

`scripts/check_asgard_observability_drift.py` compares the vendored copy
against the upstream sibling checkout (`~/code/asgard/asgard_observability/`)
and fails if they diverge. Runs locally; not gated in CI (CI doesn't have the
upstream repo checked out).

Re-vendor with:

```
python scripts/check_asgard_observability_drift.py --update
# then update the "Synced from commit" SHA above
```

## Local edits

None — only this `VENDORED.md` marker is added. Module code is byte-for-byte
identical to the upstream commit.
