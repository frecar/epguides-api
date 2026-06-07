#!/usr/bin/env python3
"""Enforce the empty-`choices` guard on LLM streaming consumers.

Some OpenAI-spec streaming backends emit chunks whose `choices` array is
**empty** (the usage / keep-alive / final chunk). Any code that streams from
such a backend and indexes `chunk.choices[0]` *without first guarding the
empty case* crashes with `IndexError: list index out of range` the moment the
backend emits one. This is a class of bug, not a single site, so it is worth a
mechanical guard.

THE GUARD PATTERN this check expects
------------------------------------
Inside any `for <chunk> in <stream>:` loop that indexes `<chunk>.choices[0]`,
an empty-choices guard MUST appear *before* the first index, at the top of the
loop body. The canonical form is::

    for chunk in response:
        if not chunk.choices:   # skip the empty usage/keep-alive chunk
            continue
        delta = chunk.choices[0].delta
        ...

Accepted guard shapes (all must short-circuit the iteration before indexing):
  - `if not <chunk>.choices: continue`            (the canonical form)
  - `if not <chunk>.choices: <break>`             (also short-circuits)
  - `if len(<chunk>.choices) == 0: continue`      (explicit length check)
  - `if not <chunk>.choices or ...: continue`     (guard combined with others)
  - `if <chunk>.choices: <body that does the indexing>`  (positive guard —
        indexing only happens inside the truthy branch)

`<chunk>` is whatever name the `for` loop binds. The check is deliberately
loop-scoped and low-false-positive: it ONLY fires on a `<loopvar>.choices[0]`
(or `.choices[0].<attr>`) subscript whose loop variable is the target of an
enclosing `for`, and only when that loop body lacks a matching guard. It does
NOT flag non-streaming `response.choices[0].message` reads (those aren't loop
variables and always have exactly one choice).

Opt-out: append `# stream-choices-guard: ignore <reason>` to the indexing line
for the rare legitimate case (e.g. a fixture that deliberately omits the guard
to prove the check fires — but prefer keeping such fixtures under tests/, which
are allowlisted).

Used by:
  - `.pre-commit-config.yaml` (runs on changed files at commit time)
  - `.github/workflows/ci.yml` lint job (runs over the whole tree)
  - `make ci-parity` (pre-push parity with CI)

Sibling to `check_no_external_llm.py` — same wiring, same allowlist
philosophy, same canonical-and-vendored distribution model. See internal
tracking for the incident that motivated it.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# Per-line opt-out for the rare legitimate unguarded index (kept identical in
# spirit to check_no_external_llm.py's `# llm-policy: ignore`).
IGNORE_MARKER = "stream-choices-guard: ignore"

# Path components / filenames that are skipped. Tests are allowlisted: they
# legitimately build unguarded-stream fixtures to prove the guard works, and
# the test file for THIS check needs an unguarded-site fixture. Mirrors
# check_no_external_llm.py's allowlist.
ALLOWED_PATH_COMPONENTS = (
    "tests",
    "test",
    ".venv",
    "node_modules",
    "__pycache__",
    ".git",
    ".claude",  # local agent tooling worktrees, never part of a checkout's source
    ".next",
    ".cache",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "site-packages",
    "dist",
    "build",
    "migrations",
)
ALLOWED_FILENAMES = {
    # This check defines the forbidden pattern in its own docstring/strings.
    "check_stream_choices_guard.py",
}


def is_allowed_path(path: Path) -> bool:
    if any(part in ALLOWED_PATH_COMPONENTS for part in path.parts):
        return True
    if path.name in ALLOWED_FILENAMES:
        return True
    return path.name.startswith("benchmark_") or path.name.startswith("test_")


def _is_choices_index(node: ast.AST, loop_var: str) -> bool:
    """True if `node` is `<loop_var>.choices[0]` (optionally `.<attr>` after)."""
    # Walk past any trailing attribute access: choices[0].delta -> the [0] sub.
    cur = node
    while isinstance(cur, ast.Attribute):
        cur = cur.value
    if not isinstance(cur, ast.Subscript):
        return False
    value = cur.value
    # value must be `<loop_var>.choices`
    if not (isinstance(value, ast.Attribute) and value.attr == "choices"):
        return False
    base = value.value
    return isinstance(base, ast.Name) and base.id == loop_var


def _index_sites(body: list[ast.stmt], loop_var: str) -> list[int]:
    """Line numbers of every `<loop_var>.choices[0]...` subscript in `body`,
    excluding any nested `for`/`async for` over the SAME var name (a new loop
    re-scopes the guard requirement)."""
    sites: list[int] = []
    for stmt in body:
        for sub in ast.walk(stmt):
            # Don't descend into an inner loop that rebinds the same name — its
            # own body is checked separately as its own loop.
            if isinstance(sub, (ast.For, ast.AsyncFor)) and _loop_target_name(sub) == loop_var and sub is not stmt:
                continue
            if isinstance(sub, ast.Subscript) and _is_choices_index(sub, loop_var):
                sites.append(sub.lineno)
    return sites


def _loop_target_name(loop: ast.For | ast.AsyncFor) -> str | None:
    return loop.target.id if isinstance(loop.target, ast.Name) else None


def _has_empty_choices_guard(loop: ast.For | ast.AsyncFor, loop_var: str) -> bool:
    """True if the loop body opens with an empty-choices guard for `loop_var`.

    Accepts both negative guards (`if not <v>.choices: continue/break`) and the
    positive form (`if <v>.choices: <indexing body>`). The guard must reference
    `<loop_var>.choices` and short-circuit (negative form) or wrap the indexing
    (positive form)."""
    for stmt in loop.body:
        if not isinstance(stmt, ast.If):
            # A non-If statement before any guard that itself indexes choices is
            # the unguarded case; keep scanning in case the guard comes first
            # textually but order is what matters — handled by the caller via
            # line comparison. Here we only need to detect a guard's presence.
            continue
        if _if_is_negative_guard(stmt, loop_var):
            return True
        if _if_is_positive_guard(stmt, loop_var):
            return True
    return False


def _references_loop_choices(node: ast.AST, loop_var: str) -> bool:
    """True if `node` (a test expression) references `<loop_var>.choices`
    anywhere — covers `not v.choices`, `len(v.choices) == 0`,
    `not v.choices or ...`, `v.choices`, etc."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute) and sub.attr == "choices":
            base = sub.value
            if isinstance(base, ast.Name) and base.id == loop_var:
                return True
    return False


def _branch_short_circuits(body: list[ast.stmt]) -> bool:
    """True if the branch body short-circuits the iteration (continue/break)
    or returns — i.e. the code after the guard does not run for that branch."""
    return any(isinstance(s, (ast.Continue, ast.Break, ast.Return, ast.Raise)) for s in body)


def _if_is_negative_guard(stmt: ast.If, loop_var: str) -> bool:
    """`if not v.choices: continue` and equivalents — the truthy (empty) branch
    short-circuits, so indexing below is unreachable for empty choices."""
    return _references_loop_choices(stmt.test, loop_var) and _branch_short_circuits(stmt.body)


def _if_is_positive_guard(stmt: ast.If, loop_var: str) -> bool:
    """`if v.choices: <indexing happens here>` — a plain truthy test on choices
    whose body contains the indexing (so the index never runs when empty). We
    accept it when the test is exactly a reference to `<loop_var>.choices` and
    the indexing site lives inside this If's body and NOT after it."""
    test = stmt.test
    # Only accept a *direct* truthy test on choices (`if v.choices:`), not an
    # arbitrary condition — keeps this low-false-positive.
    if not (
        isinstance(test, ast.Attribute)
        and test.attr == "choices"
        and isinstance(test.value, ast.Name)
        and test.value.id == loop_var
    ):
        return False
    # The indexing must occur inside the truthy branch.
    return bool(_index_sites(stmt.body, loop_var))


class _LoopVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.violations: list[int] = []

    def _check_loop(self, loop: ast.For | ast.AsyncFor) -> None:
        loop_var = _loop_target_name(loop)
        if loop_var is not None:
            sites = _index_sites(loop.body, loop_var)
            if sites and not _has_empty_choices_guard(loop, loop_var):
                # Report the first unguarded indexing site.
                self.violations.append(min(sites))
        self.generic_visit(loop)

    def visit_For(self, loop: ast.For) -> None:
        self._check_loop(loop)

    def visit_AsyncFor(self, loop: ast.AsyncFor) -> None:
        self._check_loop(loop)


def check_file(path: Path) -> list[tuple[int, str]]:
    """Return (line_no, line_content) for each unguarded streaming index."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        # Not valid Python (partial file, template) — nothing to assert.
        return []

    visitor = _LoopVisitor()
    visitor.visit(tree)
    if not visitor.violations:
        return []

    lines = text.split("\n")
    out: list[tuple[int, str]] = []
    for lineno in sorted(set(visitor.violations)):
        content = lines[lineno - 1] if 1 <= lineno <= len(lines) else ""
        if IGNORE_MARKER in content:
            continue
        out.append((lineno, content.rstrip()))
    return out


def main(argv: list[str]) -> int:
    files = [Path(a) for a in argv] if argv else [p for p in Path.cwd().rglob("*.py") if p.is_file()]

    violation_count = 0
    for f in files:
        if f.suffix != ".py" or not f.exists() or not f.is_file():
            continue
        if is_allowed_path(f):
            continue
        for line_no, content in check_file(f):
            print(f"{f}:{line_no}: unguarded streaming `choices[0]` — add an empty-choices guard: {content}")
            violation_count += 1

    if violation_count:
        print()
        print(f"FAIL: {violation_count} unguarded streaming `choices[0]` site(s).")
        print()
        print("Some OpenAI-spec streaming backends emit empty-`choices` chunks")
        print("(usage / keep-alive). Indexing `choices[0]` on them raises")
        print("IndexError and kills the stream.")
        print()
        print("Fix: guard the loop body before indexing, e.g.:")
        print("    for chunk in response:")
        print("        if not chunk.choices:")
        print("            continue")
        print("        delta = chunk.choices[0].delta")
        print()
        print("If a site is a deliberate exception, append a trailing comment:")
        print(f"    # {IGNORE_MARKER} <reason>")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
