"""Shape/regression tests for the uv-lock-refresh auto-PR workflow (#344).

`.github/workflows/uv-lock-refresh.yml` opens a weekly auto-PR that refreshes
`uv.lock`. It originally created that PR with `${{ secrets.GITHUB_TOKEN }}` —
but GitHub's anti-recursion rule means a PR created by `GITHUB_TOKEN` does NOT
trigger any `on: pull_request` workflow, so the refresh PR got ZERO CI checks
and could never pass the merge gate (which requires every required context to
conclude success; a MISSING context blocks forever — PR #341 sat BLOCKED with
no checks until it was re-pushed under a real user identity). The fix is to
create the PR with an existing PAT (PAT-authored PRs fire `on: pull_request`
like a normal user PR).

This test is the **recurrence-preventer**: a future edit reverting the token to
`GITHUB_TOKEN` re-breaks CI-on-refresh-PRs silently (the PR would still open,
just with no checks), and these assertions catch it. It is a static YAML-shape
contract, not a workflow execution.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "uv-lock-refresh.yml"

# The cross-repo PAT secret the create-pull-request step must use. It is the
# established create-pull-request PAT already consumed by every sibling repo's
# uv-lock-refresh workflow and is available as a repo Actions secret here.
EXPECTED_TOKEN = "${{ secrets.CARLSEN_PRIVATE_REPO_TOKEN }}"
CREATE_PR_ACTION = "peter-evans/create-pull-request"


def _load_workflow(path: Path) -> dict:
    """Load a workflow file. PyYAML parses ``on:`` (the trigger key) as the
    Python boolean ``True``, so callers needing that key index with ``True``,
    not the string ``"on"``."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{path} is not a YAML mapping"
    return data


def _create_pr_step(data: dict) -> dict:
    steps = data["jobs"]["refresh"]["steps"]
    matches = [s for s in steps if CREATE_PR_ACTION in s.get("uses", "")]
    assert len(matches) == 1, f"expected exactly one {CREATE_PR_ACTION} step, found {len(matches)}"
    return matches[0]


def test_workflow_is_valid_yaml() -> None:
    """A corrupt file would silently stop the weekly lock refresh."""
    assert WORKFLOW.exists(), "uv-lock-refresh workflow missing"
    data = _load_workflow(WORKFLOW)
    assert data["name"], "workflow must have a name"


def test_create_pr_uses_pat_not_github_token() -> None:
    """#344 — the core fix + recurrence guard.

    The create-pull-request step MUST use the cross-repo PAT so the PR fires
    `on: pull_request` and gets CI. It must NOT use GITHUB_TOKEN — a PR created
    by GITHUB_TOKEN never triggers `pull_request` workflows (GitHub
    anti-recursion), leaving the PR with no checks and un-mergeable.
    """
    step = _create_pr_step(_load_workflow(WORKFLOW))
    token = step["with"]["token"]
    assert token == EXPECTED_TOKEN, f"create-pull-request token must be the PAT, got: {token!r}"
    # Explicit negative assertion: a revert to GITHUB_TOKEN re-breaks CI silently.
    assert "GITHUB_TOKEN" not in token, (
        "create-pull-request must NOT use GITHUB_TOKEN — anti-recursion means the "
        "refresh PR would get ZERO CI checks and be un-mergeable (#344)"
    )


def test_create_pr_restricts_to_uv_lock_path() -> None:
    """#344 — the job only ever regenerates uv.lock, so `add-paths` pins it to
    that file. Keeps the PAT-scope reasoning tight (no `workflow` scope needed)
    and stops any stray working-tree change from riding along."""
    step = _create_pr_step(_load_workflow(WORKFLOW))
    assert step["with"].get("add-paths") == "uv.lock", (
        "create-pull-request must restrict commits to uv.lock (add-paths)"
    )


def test_workflow_has_least_privilege_permissions() -> None:
    """#344 — once the PAT opens the PR, the job's own GITHUB_TOKEN no longer
    needs write. Checkout is the only GITHUB_TOKEN consumer, so `contents: read`
    is the correct ceiling and no other permission should be elevated."""
    data = _load_workflow(WORKFLOW)
    perms = data.get("permissions", {})
    assert perms.get("contents") == "read", "contents must be read-only after the PAT swap"
    extras = set(perms.keys()) - {"contents"}
    assert not extras, f"unexpected elevated permissions after the PAT swap: {extras}"
