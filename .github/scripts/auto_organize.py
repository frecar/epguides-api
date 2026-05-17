#!/usr/bin/env python3
"""Auto-organize a freshly-touched issue (asgard#836).

Implementation of the contract documented in ~/.claude/CLAUDE.md
"Filing checklist" section. Called by `.github/workflows/auto-organize.yml`.

Reads issue state from env (set by the workflow), does in order:

1. Verify 3-axis labels (type/severity/status). Missing → pin a warning
   comment + add status:triage + EXIT NON-ZERO (hard fail). The comment
   is keyed off the issue's current label-state hash so re-triggers
   with no state change are no-op.
2. Look up the right project by scanning user-scoped projects for a
   `scope: <owner>/<repo>` token in their shortDescription.
3. Add the issue to that project (idempotent — already-added → no-op).
4. Set Priority + Effort defaults if those fields are empty. Severity
   → Priority: critical=P0, high=P1, medium=P2, low=P3. Effort = M.
5. If body has `Parent: <owner>/<repo>#N` (or bare `Parent: #N` for
   same-repo), call addSubIssue GraphQL mutation.

Project + field ops use PROJECT_PAT. Missing/expired → emit
::warning:: annotation and skip those steps (soft-fail). Sentinel
detection of silent rot covered by a workflow_run rule.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from string import Template

# ---------- env-bound state ----------

GH_TOKEN = os.environ["GH_TOKEN"]
PROJECT_PAT = os.environ.get("PROJECT_PAT") or ""
REPO = os.environ["REPO"]  # e.g. "frecar/asgard"
OWNER = REPO.split("/")[0]
ISSUE_NUMBER = int(os.environ["ISSUE_NUMBER"])
ISSUE_NODE_ID = os.environ["ISSUE_NODE_ID"]
ISSUE_BODY = os.environ.get("ISSUE_BODY") or ""
ISSUE_LABELS = json.loads(os.environ["ISSUE_LABELS"])

AXES = ("type", "severity", "status")
SEVERITY_TO_PRIORITY = {
    "critical": "P0",
    "high": "P1",
    "medium": "P2",
    "low": "P3",
}
DEFAULT_EFFORT = "M"
PIN_MARKER_PREFIX = "<!-- auto-organize:v1"


# ---------- GitHub API helpers ----------


def _gh_api(path: str, token: str | None = None, method: str = "GET", body: dict | None = None) -> dict:
    """Call the REST API via `gh api`."""
    cmd = ["gh", "api"]
    if method != "GET":
        cmd.extend(["-X", method])
    cmd.append(path)
    if body is not None:
        cmd.extend(["-f", "_body=" + json.dumps(body)])
    env = os.environ.copy()
    if token:
        env["GH_TOKEN"] = token
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        raise RuntimeError(f"gh api {path} failed: {result.stderr.strip()[:500]}")
    return json.loads(result.stdout) if result.stdout.strip() else {}


def _gh_graphql(query: str, token: str | None = None) -> dict:
    """Call the GraphQL API via `gh api graphql`."""
    env = os.environ.copy()
    if token:
        env["GH_TOKEN"] = token
    result = subprocess.run(
        ["gh", "api", "graphql", "-f", f"query={query}"],
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh api graphql failed: {result.stderr.strip()[:500]}")
    data = json.loads(result.stdout)
    if "errors" in data:
        raise RuntimeError(f"GraphQL errors: {json.dumps(data['errors'])[:500]}")
    return data["data"]


# ---------- step 1: label axis check ----------


def axis_state() -> dict[str, str | None]:
    """Return {axis: chosen-value | None} for the current label set."""
    state: dict[str, str | None] = dict.fromkeys(AXES)
    for lab in ISSUE_LABELS:
        name = lab["name"]
        for axis in AXES:
            prefix = f"{axis}:"
            if name.startswith(prefix):
                state[axis] = name[len(prefix) :]
                break
    return state


def missing_axes(state: dict[str, str | None]) -> list[str]:
    return [a for a in AXES if state[a] is None]


def label_state_hash() -> str:
    """Hash the issue's label set for idempotency. Same labels →
    same hash → skip comment edit (avoids gratuitous updates)."""
    names = sorted(lab["name"] for lab in ISSUE_LABELS)
    return hashlib.sha256(",".join(names).encode()).hexdigest()[:12]


def build_warning_body(missing: list[str]) -> str:
    """The pinned-comment text. Marker on first line includes the state
    hash so we can detect no-op re-fires."""
    h = label_state_hash()
    return (
        f"{PIN_MARKER_PREFIX} hash={h} -->\n"
        f"> [!IMPORTANT]\n"
        f"> **This issue is missing required labels: "
        f"{', '.join(f'`{a}:*`' for a in missing)}.**\n"
        f">\n"
        f"> The cluster issue-hygiene system requires exactly one label "
        f"from each of three axes:\n"
        f">\n"
        f"> | Axis | Valid values | Picking rule |\n"
        f"> |---|---|---|\n"
        f"> | `type:` | `bug` \\| `feature` \\| `chore` \\| `docs` \\| `infra` | What KIND of change |\n"
        f"> | `severity:` | `critical` \\| `high` \\| `medium` \\| `low` | How bad if untouched |\n"
        f"> | `status:` | `triage` \\| `ready` \\| `in-progress` \\| `blocked` \\| `burn-in` | Where in flow |\n"
        f">\n"
        f"> See [CLAUDE.md filing checklist](https://github.com/frecar/dotfiles/blob/main/claude/CLAUDE.md#filing-checklist--4-mechanical-steps-every-time-no-exceptions) for picking rules.\n"
        f">\n"
        f"> I've added `status:triage` as a hint. Please add the missing axes."
    )


def find_existing_warning_comment() -> dict | None:
    """Return the pinned warning comment dict if it exists, else None."""
    comments = _gh_api(f"repos/{REPO}/issues/{ISSUE_NUMBER}/comments")
    if isinstance(comments, list):
        for c in comments:
            if PIN_MARKER_PREFIX in (c.get("body") or ""):
                return c
    return None


def upsert_warning_comment(missing: list[str]) -> None:
    """Edit-or-create the pinned warning comment. Skip-if-current-hash-matches."""
    new_body = build_warning_body(missing)
    existing = find_existing_warning_comment()
    if existing is None:
        subprocess.run(
            ["gh", "issue", "comment", str(ISSUE_NUMBER), "--repo", REPO, "--body", new_body],
            check=True,
            env={**os.environ, "GH_TOKEN": GH_TOKEN},
        )
        print("  ✓ pinned warning comment created")
        return
    # Existing comment — check the hash in its first line. If unchanged,
    # skip the edit to avoid notification churn.
    first_line = existing["body"].splitlines()[0] if existing["body"] else ""
    new_first_line = new_body.splitlines()[0]
    if first_line == new_first_line:
        print("  · pinned warning unchanged (hash match), skipping edit")
        return
    subprocess.run(
        ["gh", "api", "-X", "PATCH", f"repos/{REPO}/issues/comments/{existing['id']}", "-f", f"body={new_body}"],
        check=True,
        env={**os.environ, "GH_TOKEN": GH_TOKEN},
    )
    print("  ✓ pinned warning comment updated")


def clear_warning_comment_if_present() -> None:
    """Once all axes present, delete the warning comment if it exists."""
    existing = find_existing_warning_comment()
    if existing is None:
        return
    subprocess.run(
        ["gh", "api", "-X", "DELETE", f"repos/{REPO}/issues/comments/{existing['id']}"],
        check=True,
        env={**os.environ, "GH_TOKEN": GH_TOKEN},
    )
    print("  ✓ cleared warning comment (axes now complete)")


def add_triage_label() -> None:
    """Add `status:triage` as a hint when status axis is missing.
    Idempotent — gh issue edit doesn't error on duplicate labels."""
    subprocess.run(
        ["gh", "issue", "edit", str(ISSUE_NUMBER), "--repo", REPO, "--add-label", "status:triage"],
        check=False,
        env={**os.environ, "GH_TOKEN": GH_TOKEN},
    )


# ---------- step 2-4: project ops (soft-fail if PROJECT_PAT missing) ----------


def project_pat_or_warn() -> str | None:
    if not PROJECT_PAT:
        print(
            "::warning::PROJECT_PAT not set; skipping project + field + sub-issue steps. "
            "Set the secret to enable full auto-organize."
        )
        return None
    return PROJECT_PAT


def resolve_project(token: str) -> tuple[str, int] | None:
    """Find the project for REPO via scope: <owner>/<repo> in shortDescription.
    Fallback: project whose shortDescription mentions `scope: default` or whose
    title is 'Cluster work'."""
    query = Template("""
    { user(login: "$owner") {
        projectsV2(first: 50) {
          nodes { id number title shortDescription closed }
        }
      } }
    """).substitute(owner=OWNER)
    data = _gh_graphql(query, token=token)
    projects = data.get("user", {}).get("projectsV2", {}).get("nodes", []) or []
    fallback = None
    for p in projects:
        if p.get("closed"):
            continue
        desc = (p.get("shortDescription") or "").lower()
        if f"scope: {REPO.lower()}" in desc:
            return p["id"], p["number"]
        if "scope: default" in desc or p.get("title") == "Cluster work":
            fallback = (p["id"], p["number"])
    return fallback


def add_to_project(token: str, project_id: str) -> str:
    """Add issue to project. Returns the project item ID (idempotent —
    already-added returns the existing item)."""
    query = Template("""
    mutation {
      addProjectV2ItemById(input: {projectId: "$pid", contentId: "$cid"}) {
        item { id }
      }
    }
    """).substitute(pid=project_id, cid=ISSUE_NODE_ID)
    data = _gh_graphql(query, token=token)
    return data["addProjectV2ItemById"]["item"]["id"]


def get_field_metadata(token: str, project_id: str) -> dict:
    """Return {field_name: {'id': ..., 'options': {option_name: option_id}}}."""
    query = Template("""
    { node(id: "$pid") { ... on ProjectV2 {
        fields(first: 50) { nodes {
          ... on ProjectV2SingleSelectField { id name options { id name } }
        } }
      } } }
    """).substitute(pid=project_id)
    data = _gh_graphql(query, token=token)
    result = {}
    for n in data["node"]["fields"]["nodes"]:
        if n and n.get("name") in ("Priority", "Effort"):
            result[n["name"]] = {
                "id": n["id"],
                "options": {o["name"]: o["id"] for o in n["options"]},
            }
    return result


def get_item_field_values(token: str, project_id: str, item_id: str) -> dict:
    """Return {field_name: current_value} for the project item."""
    query = Template("""
    { node(id: "$iid") { ... on ProjectV2Item {
        fieldValues(first: 30) { nodes {
          ... on ProjectV2ItemFieldSingleSelectValue { name field {
            ... on ProjectV2SingleSelectField { name }
          } }
        } }
      } } }
    """).substitute(iid=item_id)
    data = _gh_graphql(query, token=token)
    result = {}
    for v in data["node"]["fieldValues"]["nodes"]:
        if v and v.get("field", {}).get("name"):
            result[v["field"]["name"]] = v.get("name")
    return result


def set_field(token: str, project_id: str, item_id: str, field_id: str, option_id: str) -> None:
    query = Template("""
    mutation { updateProjectV2ItemFieldValue(input: {
      projectId: "$pid", itemId: "$iid", fieldId: "$fid",
      value: { singleSelectOptionId: "$oid" }
    }) { projectV2Item { id } } }
    """).substitute(pid=project_id, iid=item_id, fid=field_id, oid=option_id)
    _gh_graphql(query, token=token)


def apply_field_defaults(token: str, project_id: str, item_id: str, state: dict[str, str | None]) -> None:
    fields = get_field_metadata(token, project_id)
    if "Priority" not in fields or "Effort" not in fields:
        print("::warning::Project missing Priority/Effort field; skipping defaults.")
        return
    current = get_item_field_values(token, project_id, item_id)
    severity = state.get("severity")
    desired_priority = SEVERITY_TO_PRIORITY.get(severity or "", "P2")
    if not current.get("Priority"):
        opt = fields["Priority"]["options"].get(desired_priority)
        if opt:
            set_field(token, project_id, item_id, fields["Priority"]["id"], opt)
            print(f"  ✓ set Priority={desired_priority} (from severity:{severity})")
    if not current.get("Effort"):
        opt = fields["Effort"]["options"].get(DEFAULT_EFFORT)
        if opt:
            set_field(token, project_id, item_id, fields["Effort"]["id"], opt)
            print(f"  ✓ set Effort={DEFAULT_EFFORT}")


# ---------- step 5: native sub-issue parent link ----------


_PARENT_RE = re.compile(r"^[-*]?\s*Parent:\s*(?:([\w.-]+/[\w.-]+))?#(\d+)\s*$", re.MULTILINE | re.IGNORECASE)


def parse_parent(body: str) -> tuple[str, int] | None:
    m = _PARENT_RE.search(body)
    if not m:
        return None
    parent_repo = m.group(1) or REPO
    parent_num = int(m.group(2))
    return parent_repo, parent_num


def add_sub_issue(token: str, parent_repo: str, parent_num: int) -> None:
    """Create native parent/sub-issue link. Idempotent —
    already-linked → noop with informational message."""
    parent_info = _gh_api(f"repos/{parent_repo}/issues/{parent_num}", token=token)
    parent_node_id = parent_info["node_id"]
    query = Template("""
    mutation { addSubIssue(input: {issueId: "$pid", subIssueId: "$cid"}) {
      subIssue { number }
    } }
    """).substitute(pid=parent_node_id, cid=ISSUE_NODE_ID)
    try:
        _gh_graphql(query, token=token)
        print(f"  ✓ linked as sub-issue of {parent_repo}#{parent_num}")
    except RuntimeError as e:
        msg = str(e).lower()
        if "already linked" in msg or "already exists" in msg:
            print(f"  · sub-issue link to {parent_repo}#{parent_num} already exists")
        else:
            print(f"::warning::sub-issue link failed: {e}")


# ---------- main flow ----------


def main() -> int:
    print(f"==> {REPO}#{ISSUE_NUMBER}")
    state = axis_state()
    missing = missing_axes(state)

    if missing:
        print(f"  ✗ missing axes: {missing}")
        upsert_warning_comment(missing)
        if "status" in missing:
            add_triage_label()
        # Hard fail — labels are reporter-fixable, surface red check.
        return 1

    # All axes present — clear any stale warning comment.
    clear_warning_comment_if_present()
    print(f"  ✓ axes complete: {state}")

    token = project_pat_or_warn()
    if token is None:
        # Soft-fail path: labels are fine, project/field/parent ops skipped.
        return 0

    proj = resolve_project(token)
    if proj is None:
        print(
            f"::warning::No project matched for {REPO}; skipping project + field steps. "
            f"Set 'scope: {REPO}' or 'scope: default' in a project's shortDescription."
        )
        return 0
    project_id, project_num = proj
    print(f"  → project #{project_num}")

    try:
        item_id = add_to_project(token, project_id)
        print(f"  ✓ added to project (item {item_id[:24]}...)")
    except Exception as e:
        print(f"::warning::Project add failed: {e}")
        return 0

    try:
        apply_field_defaults(token, project_id, item_id, state)
    except Exception as e:
        print(f"::warning::Field default apply failed: {e}")

    parent = parse_parent(ISSUE_BODY)
    if parent:
        parent_repo, parent_num = parent
        try:
            add_sub_issue(token, parent_repo, parent_num)
        except Exception as e:
            print(f"::warning::Sub-issue link failed: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
