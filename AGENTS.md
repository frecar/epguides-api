# epguides-api — Agent Guidance

<!-- AGENTS-CORE:BEGIN — generated from frecar/dotfiles agent-harness/policy/AGENTS-CORE-public.md. Do NOT edit inline; run agent-harness/policy/sync-agents-core.sh. -->
## Cross-agent core rules

These rules bind **every** agent working in this repo — Claude, Codex, OpenCode — regardless of tool. They are the shared contract; your tool-specific file (`CLAUDE.md` / `AGENTS.md` / your config) adds only tool mechanics on top. This block is machine-synced — do not edit it inline.

### Worktrees
- Create worktrees **only** under `/tmp/wt-<branch-slug>-<instance>/<repo>` (branch with `/`→`-`; `<instance>` = `$$`+epoch or a harness dispatch id — never omit it). **Never** derive the path from the issue number, agent name, or branch alone: each is constant across concurrent dispatches, so two agents on one issue land in the same directory and silently interleave edits. **Never** nest a worktree inside the main clone directory — that pollutes the workspace.
- Base off fresh `origin/main`: `git fetch origin` immediately before `git worktree add "/tmp/wt-<slug>-<instance>/<repo>" origin/main -b <branch>`.
- Name the worktree by the branch, not the issue. **Tear it down** on completion or hand-off: `git worktree remove <path>` + `rm -rf` the parent.
- **Leave every worktree RECOVERABLE-FROM-REMOTE before you stop — for ANY reason** (task done, context exhausted, timeout, error, hand-off). "On completion" is not enough: most stranded worktrees come from agents that stopped *without* completing. Before your last turn, your work must be in one of these states, and you must say which:
  - **pushed + PR open** → the normal done state; remove the worktree after the PR merges.
  - **pushed, no PR yet** → say so explicitly and name the branch. Commits are safe on the remote, so the worktree is disposable — but nothing tracks the work, and it is invisible to every `gh pr list` and backlog query.
  - **nothing pushed** → push it (a draft PR is fine) **or** state in one line that you are discarding it and why. Never leave uncommitted or unpushed work as your final state: automated cleanup can evict the worktree and that is the only copy.
  - **throwaway** (a worktree you made for a quick check) → remove it in the same breath you finish the check.
- **Removing someone else's worktree: check state first, never blanket-clean.** Safe to remove only when the work is recoverable from the remote — its PR is merged, **or** the branch is pushed with no unpushed commits and a clean tree. Verify with `git -C <wt> status --porcelain` (must be empty) and `git -C <wt> log --oneline origin/<branch>..HEAD` (must be empty). A worktree holding the only copy of something is *never* debris, however old it looks. Find stranded work by walking `git worktree list` against `git ls-remote` — a pushed branch with no PR appears in no other query.
- **Cross-clone edit leak (most damaging):** Only Edit/Write/`sed -i` paths **inside your worktree**. Verify with `git -C <worktree> status` — your edits must appear there, never in the main clone. Shell-outs and non-Claude agents bypass any edit hooks; this written rule is the only guard for all agents.
- **Worktrees isolate the directory, not the branch ref.** Two agents in separate worktrees can still commit to the same branch. If you detect a foreign commit on your branch: escape to a fresh distinctly-named branch, preserve the foreign commit, never force-push-war.
- **`refs/stash` is shared across every worktree of a clone, not scoped to yours.** Never `git stash` in an agent worktree — a push/pop can silently discard another agent's WIP. Save/restore via a scratch diff instead: `git diff > /tmp/<slug>.patch` → `git apply`.
- **git records when a commit landed, never who wrote it.** No AI-attribution trailer is added, so author == committer on every agent commit. "I don't remember writing this" is not evidence someone else did — provenance doubt alone is never grounds to revert, reset, or force-push; verify with diff/log, not memory.
- **A vanished or silent worktree is NOT a dead agent.** A quiet output file, missing `/tmp/wt-*` dir, or a failed process-grep are NOT done-signals — the worktree reaper can evict a live worktree mid-run. Done = the **completion notification only**. Never take over another agent's worktree based on mtime or absence.
- **Deploy from a clean on-main clone.** A detached-HEAD, dirty, or behind-main worktree is fine for a PR merge but may be rejected by the deploy-currency guard. Always deploy from a clean main clone, not a worktree.
- **Pre-commit shared-cache stash collision.** Concurrent agents sharing the pre-commit cache collide on the stash. Always push with a **clean working tree** — no staged or uncommitted changes at push time.
- **Resuming an aged worktree (hand-off / idle / post-crash reattach):** Run `git -C <worktree> fetch origin` then `git rebase origin/main` before continuing. Its base is stale; building on it un-synced causes conflicts and duplicates already-merged work. If the rebase is non-trivial or the branch is badly diverged, open a fresh worktree off `origin/main` and cherry-pick instead.

### Multi-agent coordination (several agents run concurrently as the same GitHub user)
- Before starting an issue, sweep for an existing branch touching it (`git ls-remote --heads origin "*<issue>*"`). If one exists, another agent has it — back off.
- Claim atomically: assign yourself, flip `status:ready`→`status:in-progress`, push an agent-name-prefixed branch, and post a claim comment. Then **wait ~60s and re-read** — if another agent's claim landed in the gap, back off and undo yours.
- One issue per agent. Never edit, review, or push to another agent's claimed issue / PR / branch. Stamp your agent identity on branches and comments so ownership is visible.
- **Branch names are `<agent>/<kebab-slug>` and contain a `/` — never embed a raw branch name in a file path, container name, or metric label.** Sanitize first (`${branch##*/}`, or `tr '/' '-'`), the same class of hazard as the worktree-path rules above. Trigger incident: a scratchpad log path derived from `push-$branch.log` embedded the slash, producing an invalid path; a failed `>` redirect **aborts the whole zsh command line** rather than erroring loudly, so `npm ci` and `git push` silently never ran while the loop printed misleading return codes — two hot-path pushes looked attempted-and-failed when they were never attempted at all. Cross-ref the scratchpad unique-naming rule above (issue number + a literal token, never a raw branch name) for the same reason.

### Engineering autonomy and PM boundary
- Engineers own the ordinary end-to-end delivery loop: `claim -> inspect -> implement -> focused/full tests as appropriate -> commit -> normal pre-push -> push -> PR -> fix exact-head CI -> green review outcome`. Those offline development steps are autonomous and do not require PM approval between them; fix directly in-scope failures without waiting for another permission comment.
- PM owns prioritization, backlog/dependency state, and outcome/risk review; PM-only sessions do not implement code. An explicitly required causal design checkpoint may be appropriate once for a named high-risk shared-infrastructure/performance boundary. Once accepted, it releases the normal delivery loop; it is not a standing or repeated approval gate.
- An issue-specific checkpoint constrains only its named boundary. Continue normal development unless an instruction explicitly and justifiably holds a later live/merge action. Stop and escalate only for a material scope/architecture expansion, secrets/security/legal/policy judgment, destructive/live action, an active incident/machine/review blocker, or a genuinely unresolvable blocker — not for routine edits, commits, pushes, PRs, or in-scope CI fixes.
- **A PM session specifically does NOT**: author or edit implementation code or config, create implementation branches/worktrees/commits, claim or self-assign an engineering issue as implementer, merge implementation PRs, deploy, restart services, rotate secrets, or mutate production. Findings become scoped issues with evidence, acceptance criteria and an engineer handoff. "Ensure X works", "follow up", "unblock engineering", urgency, or a high `priority:` label does **not** implicitly authorize a PM to implement the fix.

### Agent authority — default to doing the thing
- **You operate with full authority over this project.** Routine work does not need a confirmation round-trip — do it.
- **The narrow set that genuinely needs the operator, and nothing else:** minting a *new* external credential that has no creation API (you can still store the resulting value yourself; only the minting is external); physical-world actions; and genuine human/policy judgment — irreversible disclosure, money, legal.
- **Never manufacture an operator-blocker.** Before writing "needs operator", ask: *can I do this with the access I already have?* Check whether an existing credential already carries the needed scope before declaring a new one is required, and specify the **minimum** truly-external dependency. Over-specifying invents work for the operator.

### Estate policy (binds you outside any single repo)
- **Deploys are AUTOMATIC — do not hand-deploy after a merge.** Merged code reaches production by itself. Run a manual deploy only for an active incident needing immediate rollout, and verify afterwards: CI green, error tracker clean, container health.
- **Security findings are never closed by renewing an ignore.** An `ignoreUntil`-style suppression date is a forcing function, not a lifecycle: remove the dependency, upgrade to a patched version, or document a compensating control. Maintenance is a cycle, not chance discovery, and covers vendor advisories and config/supply-chain risk, not just CVE feeds.
- **Scratchpad names must be unique from the moment of creation — and re-readable later.** A session's scratch directory is shared by every agent in that session, so two agents choosing the same obvious name silently overwrite each other — no error, the loser's bytes are simply gone. Bake the issue number *and* a short literal token you choose once into any file you will read back (`scratchpad/pr-body-1234-k3f.md`, never `pr_body.md`). **Do not use `$$` for this.** Each shell tool call runs in a NEW shell, so `$$` differs between the call that writes the file and the call that reads it — measured at four distinct PIDs inside one session. `$$` therefore buys uniqueness at the cost of ever finding the file again: `git commit -F .../msg-$$.txt` fails with `could not read log file`, and a mutation script written under `$$` silently never runs, which reads exactly like a mutation that survived. If you have lost the token, recover by globbing (`ls scratchpad/pr-body-1234-*.md`), never by regenerating `$$`. After publishing via `--body-file`, **re-fetch the live object** and confirm it matches. Renaming at cleanup is too late.
- **Where a durable fact belongs:** can a fresh clone rediscover it by reading the code? Then it goes in the repo's committed `AGENTS.md`. If not, it goes in the harness's own memory layer. Never both.
- **Prefer editing an existing file over creating a new one**, and use your harness's plan mode for a non-trivial feature before writing code.
- **Tooling conventions:** `gh` for every GitHub operation rather than the web UI; `make` targets are uniform across repos (`dev`, `test`, `lint`, `build`). Consultation protocols are harness-specific — do not claim you consulted one your harness does not have.

### Merge discipline
- `main` is protected on every repo: **never** `git push` to it, **never** raw `gh pr merge` or web-merge.
- Merge **only** via the project's gated merge wrapper, which refuses unless every required check has concluded `success`.
- **The gated merge wrapper lives in its own home repo, not necessarily this one** — if this checkout has no such wrapper, `cd` into the repo that owns it before invoking it, and always pass an explicit repo target rather than relying on cwd auto-detection (an implicit target can silently resolve to the wrong repo's identically-numbered PR).
- Prefer the wrapper's wait-for-green flag (merge-when-green in one command) over hand-rolling a poll loop; `gh pr checks <n> --watch` is a read-only status-poll fallback — it never merges anything.
- **Same-owner review blockers:** when the environment provides a machine-readable merge-blocker helper, use it for blocking agent/PM findings instead of prose-only comments. Resolve blockers only with the matching machine-readable receipt after reviewing the current head; do not merge around unresolved blockers except through the wrapper's explicit audited override.
- Before an autonomous merge, deploy, converge, or live probe, run the configured incident guard when the operator environment provides one and stop on HALT. Deliberate exceptions must be explicit and auditable in the same shell command as the guarded action.
- **Never merge red.** A failing/missing required check or a change-requesting review is a signal to FIX, not to merge. Branch off latest `origin/main` → worktree-isolate → wait for CI green → merge via the gate.
- **Verify the merge actually happened.** A gate run from the wrong cwd/repo is a silent no-merge — it can exit 0 while nothing merges. After the wrapper returns, confirm the PR reached `state == MERGED`: `gh pr view <n> --json state -q .state` (expect `MERGED`) or `gh api repos/<owner>/<repo>/pulls/<n> -q .merged` (expect `true`). Do not treat gate exit 0 alone as proof.

### Commits & conventions
- **Never** add `Co-Authored-By` or any AI-attribution line — commits are the operator's own work.
- **Never** fix production by ad-hoc SSH. Fix in the repo, commit, deploy. Ad-hoc SSH creates drift that the next deploy overwrites.
- **Manage estate state declaratively, through the project's IaC layer — not by hand.** DNS, containers/services, secrets, and network/cert config each have a config home — edit there and converge/deploy, never by hand-editing a vendor dashboard or console, hand-curling a mutation API, or an ad-hoc host edit, whenever an IaC path exists or can reasonably be added. Same principle as the ad-hoc-SSH rule above, generalized from hosts to all estate state. **Exception:** vendor state with no IaC path (e.g. an OAuth consent screen) — file an operator-action issue to track the manual step, don't silently skip it.
- Docker-first — run tooling in containers, not on the host. Keep secrets in environment variables or a secrets manager, never committed to the repo.
- Do not hard-code external LLM API endpoints (OpenAI, Anthropic, etc.) in source. Route model calls through the endpoint configured via environment variable.
- **Ad-hoc Python via a shell tool:** do NOT backslash-escape quotes inside a heredoc f-string (`peak[\"run\"]` → `SyntaxError: unexpected character after line continuation character`). Prefer (a) writing the script to a file and running it, (b) single-quoted dict keys inside a double-quoted f-string (`f"{d['k']}"`), or (c) `%`/`.format()`. **Never put backticks or `$(...)` inside a double-quoted `python3 -c "…"`** — zsh command-substitutes them *before* Python sees the string, silently splicing command output into your source, which then commits cleanly and passes lint. Prose containing shell metacharacters must go through a **quoted** heredoc (`<<'PYEOF'`) or a file, never `-c "…"`.
- **`until ! pgrep -f PATTERN` NEVER exits — it matches itself.** `pgrep -f` tests every process's full command line, and the waiting shell's own command line contains the literal pattern, so the loop spins forever after the job is long gone. Prefer your harness's completion signal or the task's output file. If you must check a process: `pgrep -x <binary>`, a PID captured at launch (`kill -0 "$pid"`), or a lock file — never a pattern that also appears in the waiting command. Bound every wait with a timeout so a mistake degrades into a late check, not an indefinite stall.
- **The interactive/Bash-tool shell here is zsh, not bash — it does NOT word-split unquoted `$vars`.** `flags="--a --b"; cmd $flags` passes ONE argument in zsh (bash would split it), so `gh issue create $flags` fails `unknown flag: --a --b` — a multi-step script can silently do nothing before anyone notices. Pass flags explicitly, or build an **array** (`args=(--label a --label b); cmd "${args[@]}"`), or force one split with `cmd ${=flags}`. Also: an unquoted empty `$x` expands to nothing (no empty-string arg), and unmatched globs **error** (`no matches found`) rather than passing through literally — quote literal globs, or `setopt NULL_GLOB` locally. Prefer `[[ … ]]` over `[ … ]`.
- **A hook that reformats files ABORTS the commit — verify the commit landed.** pre-commit rewrites a staged file (a formatter is the common case) and then *fails* the commit, but its output still ends in a wall of `Passed` lines, so it reads as success. The commit does not exist and the tree is left dirty, so the next `git push` ships the **base** commit. After every commit, confirm `git log --oneline -1` shows your message AND `git status --porcelain` is empty, before pushing. Re-stage the formatter's changes and commit again; never `--no-verify`.
- **No `vN` version suffixes on production identifiers** (classes, feature flags, components, functions, endpoints, UI labels, service names). Name *the current thing* — `UserDashboard`, not `UserDashboard v2`; a `checkout` flag, not `checkout_v2`. Version suffixes are iteration scaffolding: iterate behind a feature flag or branch, then ship under the canonical name (and retire the flag). **Exception — genuine compatibility-contract versions stay:** a suffix encoding a wire-format/schema/API contract a consumer depends on is not cruft and must not be renamed (crypto key-scheme tags where a v1 row must still decrypt, `/api/v1/...` REST paths a client is pinned to, Django `migrations/000N_*`, third-party API paths like `orders/v6`). The test: does the suffix encode a contract a consumer depends on (keep) or just "the 2nd attempt at building X" (rename)?
- **Never write scratch into `$HOME` root.** Temporary files, one-off scripts, dumps, and logs go in the session scratch dir or a repo-local gitignored path — never `~/`. If your cwd is `$HOME`, that is a bug: change directory first.

### GitHub issues
- Any non-trivial plan or task becomes a GH issue, before or as you start — the issue is the durable record. Apply **exactly one each** of `type:` (bug/feature/chore/docs/infra), `severity:` (critical/high/medium/low), `status:` (triage/ready/in-progress/blocked/burn-in), `priority:` (p0..p3) and `effort:` (s/m/l/xl) at file time — **five axes, all of them**. The backlog-hygiene check requires all five and flags a missing one on arrival; filing three produces an issue that is immediately non-conforming.
- Self-filed issue → `Closes #N` in the PR. **External-reporter** issue → `Refs #N` (never auto-close on merge; the reporter verifies first).
- **GitHub does not parse negation.** `Closes #N` / `Fixes #N` / `Resolves #N` anywhere in a commit or PR body closes #N on merge — even inside "this does **not** close #N". Never put a closing keyword next to an issue number you are not closing; write `Refs #N` or spell the number out ("issue N") instead.
- This is a public repo — never reference internal hostnames, IPs, private repos, or private deployment details in issues/PRs/comments.
- **Check `state` before editing an issue.** `gh issue view <N> --json state` first. A CLOSED issue is a resolved historical record: capture new work in a **new** issue or a comment, never by rewriting a closed issue's title/body — nobody reads a closed issue, so the work becomes invisible.
- **Parent/child uses the native sub-issue API**, not prose. A `Refs #N` / `Blocked by #N` line is documentation; it is invisible to board rollups and to every programmatic query. Both is fine, prose alone is not.
- **`priority:` is the ONLY ordering signal.** `priority:p0..p3` decides what to work on next. `severity:` describes **impact if the thing occurs** and must never be read as urgency. `severity:high` + `priority:p3` is a **valid, expected** combination meaning "high impact, deliberately deferred" — it is not an error and must not be auto-corrected. Set priority/effort **once, as labels**; the board's Priority/Effort fields are derived views — never hand-edit them.
- **Never write ad-hoc GraphQL against ProjectV2** (project/field/item IDs) — use the operator tooling, which resolves projects and fields by name and is quota-budgeted. Projects V2 field IDs **and** single-select option IDs are unique **per board**: a hardcoded or cross-board ID fails *silently*, leaving the field empty rather than erroring. Board routing is decided by repo, with a milestone override taking precedence — resolve it from the tooling, never from a hardcoded id.

### Quality gates
- Detail behind these rules — measured numbers, worked examples, the reasoning — is in `agent-harness/docs/estate-conventions.md`. It adds no rules; if it disagrees with this block, this block wins.
- **Every fact gets ONE authoritative home.** A second appearance must use the weakest mechanism its consumer supports: **refer** (a pointer) → **link** (symlink, or an `@import` where the harness supports one) → **generate** (a marker-delimited block, byte-identical-gated) — and generate ONLY where the consumer physically cannot follow a reference. A hand-maintained copy is banned even with a "keep in lockstep" note, and a test asserting two hand-written copies agree is the same ban in test form: it preserves N copies and merely makes their divergence a merge blocker.
- **A trailing pipe discards the exit status you care about.** `cmd | tail`, `cmd | grep …` report the LAST command's status, so a reported "exit code 0" on a piped invocation is evidence of nothing. Observed: `uv run pytest -q | tail -6` surfaced as exit 0 while the output itself said `1 failed, 3751 passed`, and the failure was a real defect in the change under test; separately a piped `git commit` masked a pre-commit abort. Never conclude a suite, build, push or commit succeeded from a piped run — run it unpiped and redirect to a file, or capture `${pipestatus[1]}` (zsh) / `${PIPESTATUS[0]}` (bash), or grep the output for the real verdict line.
- Pre-commit and pre-push run automatically; **never** `--no-verify`. Fix the failure instead.
- Wait for CI green before merging. The coverage floor is a fixed **95%** — never lower a gate to pass, and never RAISE it above 95 either — a climbing floor manufactures razor-thin reds on rounding artifacts rather than catching regressions.
- **A prober being down is not the probed thing being down.** An alert derived from a probe must distinguish "the target failed" from "the check could not run" — otherwise one dead host manufactures a wall of false critical alerts about healthy services and stalls unrelated work. Emit an explicit unknown/stale state and alert on it separately; "cannot verify" is never "verified broken".
- **Correlation over a handful of events is not a root cause — find the variable that CHANGED.** Before asserting cause from a small series, enumerate every candidate rather than the memorable one, check for a confound that makes the correlation near-tautological, and confirm n is what you think it is. A theory built on 3 events collapsed on all three counts: the sample was 4, the "cause" was downstream of the effect, and the one variable nobody checked was the real candidate.
- **Never sync or mirror another repo's state captured during an incident.** A snapshot taken while the source is degraded bakes the degradation in and outlives it. Re-take it after recovery, or gate the sync on the source being healthy.
- **A checker must be validated against the failure mode it claims to detect** — including the **absent/empty** case, not only the wrong-value case. Test any drift/audit tool against a deliberately injected instance of each mode it claims to cover; one that only compares non-empty values silently certifies its own blind spot. This is distinct from the coverage floor, which is line coverage of code under test, not failure-mode coverage of a checker.
- **A registry/catalog CI guard rejecting your push is the guard working, not a bug to route around.** Many guards enumerate a governed artifact class (a script, config unit, workflow step, collector) against a companion registry; a red run here almost always means "go add the entry," not "fight the check." If you are the one *writing* such a guard, derive membership from the authoritative source (a template, generator, or import closure) rather than hand-enumerating literal string occurrences — a literal match is blind to templated/generated instances of the same real artifact.

- **Adding or promoting a CI/test gate is a budgeted decision, not a free win.** Before you add one, state four things in the PR: the **failure class** it catches, its **measured** runtime, whether it is **required / advisory / scheduled**, and the **change classes** that should run it. Measure before you claim — the critical path is often image scan, browser smoke or a vulnerability scanner rather than the test suite, so "tests are slow" is a conclusion to earn from job timings, not an assumption. Prefer a **contract/failure-mode test** over tests written only to move a coverage number: the coverage floor and the never-merge-red rule are not negotiable, but neither is satisfied by a gate whose failures nobody can attribute. Prefer focused, change-aware lanes for Docker/image/browser work where that does not drop a required context. If a gate is expected to be temporary, write its **retirement condition** down with it — an incident-driven rule with no exit condition never gets one.
- **README files are agent-facing operational documentation — update them in the SAME PR** that changes commands, paths, the merge or deploy flow, package consumption, or onboarding. A README must never teach an ungated merge, a direct deploy, or point a reader at `CLAUDE.md` as the deeper project doc (those are `@AGENTS.md` shims, and some agents treat `@import` as literal text — the canonical agent guidance is `AGENTS.md`). Defer agent rules to `AGENTS.md` rather than restating them; a second copy drifts.

> Detail and rationale live in this repo's own `AGENTS.md` below. This CORE is the non-negotiable shared minimum.
<!-- AGENTS-CORE:END -->


Canonical agent instructions for this repository. Compatibility files (`CLAUDE.md`, `.github/copilot-instructions.md`) point here.

REST API for TV show metadata, episodes, air dates, and summaries. Also provides an MCP server for AI assistants.

## Overview

REST API for TV show metadata, episodes, air dates, and summaries. Also
provides an MCP server for AI assistants.

Canonical agent instructions for this repository. Compatibility files
(`CLAUDE.md`, `.github/copilot-instructions.md`) point here.

## LLM Policy
- Natural-language queries are routed through whatever OpenAI-compatible gateway is set in `LLM_API_URL` (local Ollama, vLLM, llama.cpp server, hosted endpoint, ...).
- Do not add Claude/OpenAI/Anthropic external API endpoints or runtime fallbacks to committed code paths. `scripts/check_no_external_llm.py` enforces this in pre-commit and CI.
- Optional `ALLOWED_LLM_HOSTS` env var (comma-separated hostnames) gates which hosts the gateway URL may resolve to. Empty/unset (default) means no host enforcement — any configured URL is accepted.

## Architecture

```
app/
├── api/endpoints/       # REST routes
│   ├── shows.py         # /shows/* endpoints
│   └── mcp.py           # /mcp JSON-RPC endpoint
├── core/
│   ├── cache.py         # Redis caching, @cached decorator
│   ├── config.py        # Pydantic settings
│   └── constants.py     # TTLs, version, URLs
├── models/
│   ├── schemas.py       # ShowSchema, EpisodeSchema
│   └── responses.py     # PaginatedResponse
├── services/
│   ├── show_service.py  # Business logic
│   ├── epguides.py      # External API calls
│   └── llm_service.py   # Natural language queries
└── tests/               # 95% coverage floor
```

**Flow:** Endpoints -> Services -> External APIs, with Redis caching at service layer.

## Git Workflow (Standard)
- **Commit Messages:** Use descriptive prefixes (`feat:`, `fix:`, `refactor:`, `chore:`, `docs:`).
- **Branching:** Work on feature branches from latest `origin/main`; never push directly to `main`.
- **Merge:** Follow the synced CORE merge discipline above: merge only through the project's gated path after required checks are green.
- **Pre-commit:** Ensure pre-commit hooks pass before pushing.

## Deployment Workflow

All changes flow through git. Deployment automation is operator-side and
not part of this project's published surface — contributors merge a PR
and the public instance picks up the change on the next rebuild (daily).

For local runs see "Quick Start" below.

## Tech Stack

- **Framework:** FastAPI (async)
- **Caching:** Redis with TTL-based invalidation
- **Data Sources:** epguides.com (primary), TVMaze API (fallback)
- **Python:** 3.14+
- **Public API:** https://epguides.frecar.no

## Quality baseline

This repo defines and adheres to a Python-service quality baseline:

- **Dependency manager:** `uv` with `uv.lock` committed. Docker builds use `uv sync --frozen --no-dev` so any lockfile drift fails the build instead of silently re-resolving.
- **Lint + format:** `ruff` (target `py314`, matching the committed `.python-version` and `requires-python = ">=3.14"`).
- **Type-check:** `mypy` with `check_untyped_defs` + `warn_unused_ignores` + `strict_optional` floor; strict mode opt-in per module.
- **Tests:** `pytest` + `pytest-cov`. **95% coverage floor** at the pre-commit + CI gate (`fail_under = 95` in `pyproject.toml`). Commits below the floor are rejected.
- **API contract gate:** `app/tests/test_api_contract.py` (driven by the `app/contract.py` engine) is a per-PR regression gate over the *published OpenAPI contract*. It boots the app in-process (FastAPI `TestClient`, no network) and asserts every anonymous, no-required-param GET route (`/shows/`, `/health`, `/health/ready`, `/health/llm`, `/health/cache`) still returns `200` with a body that validates against its **declared** OpenAPI `200` response schema. A route that starts `500`ing, serves a non-JSON error stub, drifts its response shape, or disappears from the schema (the `MUST_COVER` floor in `app/contract.py`) fails the test — and so the PR — before merge. The contract definition (anonymous-GET eligibility filter + `MUST_COVER` floor + declared-200-schema validation) is the single source of truth: the same engine shape can be pointed at the deployed `/openapi.json` for an out-of-band post-deploy probe, so the pre-merge gate and any deployed check cannot disagree on "the contract". Add a new public anonymous GET route → add it to `MUST_COVER`.
- **Security:** CVE coverage is layered in CI — `pip-audit --strict --require-hashes` against the exported (hashed) transitive dependency set, plus a Trivy filesystem scan (reads `uv.lock`) and a Trivy image scan of the built runtime. CRITICAL findings gate the merge; HIGH surface as annotations. Unfixable findings with no upstream patch are suppressed via `.trivyignore` / `ignore-unfixed` with a tracking trail — never silenced silently.
- **Public surface:** `scripts/check-no-internal-refs.sh` runs in pre-commit and CI. Keep source, docs, and examples standalone; use runtime configuration for private deployment values.
- **Error tracking:** `app.core.observability` initialises `sentry-sdk[fastapi]` only when `SENTRY_DSN` env var is set; traces and profiles default to `0.0` unless configured.
- **Observability:** `/metrics` endpoint exposes Prometheus exposition format (cache hits/misses by type, upstream request totals by source/outcome, upstream latency histogram, per-source ingest-freshness heartbeat). `/health` (cheap liveness), `/health/ready` (deep readiness — Redis round-trip + upstream freshness, structured `status` field, `503` when data is silently stale), `/health/llm`, `/health/cache` return structured JSON.
- **Docker hardening:** multi-stage build (compile in builder, ship runtime only), non-root user (UID 1000), `no-new-privileges`, healthcheck, log rotation, pinned `python:3.14-slim` base, pinned `ghcr.io/astral-sh/uv:0.11.3` for the uv binary.
- **Backup tier:** **N/A.** All persistent state is in upstream APIs (epguides.com, TVMaze); cache is Redis-resident and ephemeral. No DB to back up. Documented as a baseline-contract row even when the answer is "nothing to do here."
- **Makefile contract:** `make help / dev / stop / lint / fix / test / ci / build` — same surface as other Python services I maintain (aliases `up`/`down`/`deploy-prod` retained for existing muscle memory).
- **Deploy:** auto-update timer rebuilds the container daily.

## CI latency baseline — this repo is the fast reference point

Measured 2026-08-17 over the last four successful `ci.yml` runs (mean per job):

| job | mean | note |
|---|---|---|
| Trivy image scan | **48s** | the critical path |
| Test | 39s | pytest + 95% coverage floor |
| Security Audit | 38s | `pip-audit --strict --require-hashes` |
| Docker build | 21s | multi-stage |
| Trivy fs scan | 17s | reads `uv.lock` |
| Type Check | 16s | mypy |
| Lint | 12s | ruff |
| gitleaks | 6s | |
| ci-gate | 4s | |

Jobs run in parallel, so wall-clock is the slowest lane: **~48s, and it is the
image scan — not the test suite.** That is worth stating plainly, because "CI is
slow, cut tests" is the reflex and it would buy nothing here. AGENTS-CORE makes
the same point generally: measure before claiming, because in sampled runs the
critical path is usually image scan, browser smoke or Trivy.

**What actually keeps it fast** — none of it is "fewer gates". This repo runs
pytest with a 95% floor, an OpenAPI contract gate, two Trivy scans, pip-audit,
mypy, ruff and gitleaks:

- **Small dependency graph**, installed from a committed `uv.lock` with
  `--frozen`, so no resolution happens at build time.
- **No frontend and no browser lane.** No npm install, no Playwright download,
  no browser smoke — the single biggest cost class in the heavier repos.
- **Small app surface**, so the test suite is genuinely short rather than
  trimmed.
- **GitHub-hosted runners.** As a public repo it cannot depend on private
  reusable workflows or a privately-hosted registry mirror, which turns out to
  cost less than it saves: no self-hosted queueing, and the tool cache is warm.

That last one is a **constraint, not a choice**, and it cuts both ways. Do not
"fix" this repo by importing a private-repo CI pattern: private reusable
workflows and internal mirrors are unavailable here by construction, and a
change that assumes them will fail for outside contributors, not just for us.

### Adding a gate here has a budget

AGENTS-CORE already requires four things in the PR for any new CI gate: the
failure class it catches, its **measured** runtime, whether it is
required/advisory/scheduled, and the change classes that should run it. In this
repo, two more:

- **State the expected latency against the ~48s wall-clock**, and say which lane
  it lands in. A 10s addition to `Lint` (12s) is free; the same 10s on `Trivy
  image scan` moves the critical path and is the only lane where it shows up.
- **Say how it comes back out.** If it regresses the baseline, what gets
  reverted, or demoted to advisory, or moved to a schedule. An incident-driven
  gate with no exit condition never acquires one.

Nothing above is licence to weaken the existing gates. The 95% floor, both Trivy
scans, pip-audit and the contract gate stay; the point is that this repo is fast
*with* them, so a proposal to drop one to buy latency is answering the wrong
question — measure the lane first.

## Commands

```bash
make help          # Show all commands
make up            # Start dev environment (Docker + hot reload)
make down          # Stop all services
make test          # Run tests (95% coverage floor)
make fix           # Format + lint with ruff
make doctor        # Check environment health
make urls          # Show service URLs
make clean         # Remove cache files
```

Run single test:
```bash
pytest app/tests/test_endpoints.py::test_function -v
```

## REST ↔ MCP coverage matrix

Both surfaces share the same service layer; only the wire format differs.
Last verified 2026-05-10 (#197).

| Capability | REST (`/shows/*`) | MCP tool | Status |
|---|---|---|---|
| Search shows | `GET /search?q=` | `search_shows` | ✅ parity |
| Get show metadata | `GET /{key}` | `get_show` | ✅ parity |
| List seasons | `GET /{key}/seasons` | `get_seasons` | ✅ parity |
| Get episodes (with filters) | `GET /{key}/episodes` (season, episode, year, title_search, nlq, refresh) | `get_episodes` (season, episode, year, title_search, nlq) | ✅ parity (refresh deliberately omitted — MCP clients shouldn't need cache busting) |
| Next unreleased episode | `GET /{key}/episodes/next` | `get_next_episode` | ✅ parity |
| Latest released episode | `GET /{key}/episodes/latest` | `get_latest_episode` | ✅ parity |
| List ALL shows | `GET /` | `epguides://shows` resource | 🟨 different surface (resource, not tool — MCP clients should browse this rather than dump-then-filter) |
| Season-specific episode listing | `GET /{key}/seasons/{n}/episodes` | use `get_episodes` with `season=n` | ✅ folded into `get_episodes` |

### MCP-side conventions

- Tools always return JSON text content via `content: [{type: "text", text: ...}]` per the MCP spec; clients deserialize.
- `nlq` falls back to all matching episodes when the LLM is unavailable, matching REST behavior.
- Tool input schemas live in `app/mcp/server.py` `_TOOLS`. CI parity test: every REST endpoint adds a comment naming the corresponding MCP tool (or a deliberate-difference rationale).

## Code Patterns

### Caching

```python
@cached("show:{show_id}", ttl=TTL_7_DAYS, model=ShowSchema, key_transform=normalize_show_id)
async def get_show(show_id: str) -> ShowSchema | None: ...
```

TTL constants (`app/core/cache.py`):
- `TTL_7_DAYS` - Ongoing shows, seasons, episodes
- `TTL_30_DAYS` - Show list, indexes
- `TTL_1_YEAR` - Finished shows (`show.end_date is not None`) — promoted automatically by `_get_show_ttl()` / `_get_episodes_ttl()`

### Data freshness SLA (#196)

What clients can assume about how recent the data is.

| Resource | Worst case | Why |
|---|---|---|
| Show metadata (ongoing series) | 7 days | `TTL_7_DAYS` cache + `?refresh=true` invalidation supported |
| Show metadata (finished series) | 1 year | `_get_show_ttl()` extends to `TTL_1_YEAR` once `end_date` is set — these don't change |
| Episode list (ongoing) | 7 days | `TTL_7_DAYS`. Smart-invalidation on `GET /{key}/episodes/next` if the cached "next" date has passed (see `shows.py:405`) — bounds staleness for the most-asked-about episode to ≤24h after release |
| Episode list (finished) | 1 year | promoted automatically via `_get_episodes_ttl()` when all episodes are released |
| Show list (master index) | 30 days | rebuilt on demand via `extend_cache_ttl` |
| Search results | 7 days | derived from the show list |

### Upstream sources (epguides.com primary, TVMaze fallback)

- Primary: `https://epguides.com/` master list + per-show CSVs.
- Fallback: TVMaze API (used for episode data when epguides parse fails).

The cache hides upstream outages — once warmed, the API serves stale-but-bounded data even if both upstreams are down. Expected downsides:

- A scrape regression (e.g. epguides.com changes their HTML) won't surface as user-visible failures until the cache expires for a given show. Catch this with active probes (#196 fix items 2-4).
- New episodes for an ongoing series take up to `TTL_7_DAYS` to appear unless a client passes `?refresh=true` or hits `/episodes/next` past the prior cached "next" date.

### Observability gaps (open work — #196 follow-ups)

- No metric for cache hit/miss ratio per type. Add `epguides_cache_hits_total{type}` / `epguides_cache_misses_total{type}` in the `@cached` decorator.
- Upstream-staleness signal: `epguides_upstream_request_total{source,outcome}` + `epguides_ingest_last_success_timestamp{source}` heartbeat are exported, and `/health/ready` now flips to a `503` when no successful epguides.com fetch has landed within `UPSTREAM_STALENESS_HOURS` (default 24h). Remaining open work is operator-side monitoring config (the external Grafana/probe alert wiring), out of this repo's scope.
- No measurement of upstream latency. Add `epguides_upstream_response_age_seconds{source}` histogram.

These are kept intentionally separate from the SLA section above so the docs reflect today's truth — the gaps don't lie about coverage that doesn't exist yet.

### Schema Factory

```python
# Use factory function (handles defaults)
show = create_show_schema(epguides_key="test", title="Test")

# Not direct instantiation
show = ShowSchema(...)  # Don't do this
```

### Async Parallel

```python
results = await asyncio.gather(
    epguides.get_episodes_data(show_id),
    epguides.get_maze_id_for_show(show_id),
)
```

## Testing

95% coverage floor enforced by pre-commit. Commits below the floor are rejected.

Mock patterns:
```python
@patch("app.core.cache.cache_get", return_value=None)  # Cache miss
@patch("app.services.show_service.get_show")           # Service layer
```

Performance tests: < 50ms hard limit, < 20ms target.

If code can't be tested, remove it.

## Pre-commit Hooks

Runs automatically on commit:
1. Trailing whitespace, YAML check, large files, merge conflicts, private keys
2. Ruff lint + format
3. Version update
4. Tests with 95% coverage floor

Setup: `make setup` (runs `uv sync` to create `.venv` from `uv.lock`, then installs pre-commit hooks). Requires `uv` — install via https://docs.astral.sh/uv/.

## Style

- Line length: 120
- Python 3.14 (pinned via committed `.python-version`; `requires-python = ">=3.14"`)
- All I/O async
- Ruff for linting and formatting
## Operational Rules

The shared rules are in the AGENTS-CORE block above and are the authority — do
not restate them here. What is specific to this repo:

- **This repository is public.** Never reference private repositories, internal
  hostnames, IP addresses, or infrastructure details in code, comments, issues,
  PRs, or commit messages.
- **Deployment is automatic** — see `Deployment Workflow` above. Do not deploy
  by hand except for an active incident needing immediate rollout.
