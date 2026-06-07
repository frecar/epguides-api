#!/usr/bin/env bash
set -uo pipefail

# Local OSV-Scanner dependency-CVE check (epguides-api#324).
#
# Runs the SAME OSV verdict CI runs (`--lockfile=uv.lock
# --config=.osv-scanner.toml`) so a vulnerable lockfile bump is caught at
# `git push` instead of after the push round-trip. The online CI
# "Security Audit" OSV-Scanner job remains the authoritative backstop;
# this is a shift-left convenience, not a replacement — so it must NEVER
# hard-block a push for any reason other than a real, un-ignored
# vulnerability the scan actually found.
#
# Exit-code contract (the whole point of the wrapper):
#   0  -> clean, OR a warn-skip (binary absent / no lockfile / offline /
#         osv.dev unreachable). A push is NEVER blocked by a warn-skip.
#   1  -> the scan RAN and reported an un-ignored vulnerability. Push blocked.
#
# osv-scanner's own exit codes (v2): 0 = no vuln, 1 = vuln found, and
# other non-zero (e.g. 127/128) for tool/arg/runtime errors including a
# failure to reach the osv.dev advisory API. We map 1 -> block, treat a
# RECOGNISED transient/offline error as a warn-skip, and fail loudly on
# any OTHER unexpected error (bad config / bad args) rather than silently
# skipping — a broken config must not masquerade as "offline".

# Resolve repo root so the script works from any CWD (pre-commit invokes
# hooks from the repo root, but `make` / a manual call may not).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}" || {
    printf 'audit_osv: WARN-SKIP: could not cd to repo root %s.\n' "${REPO_ROOT}" >&2
    exit 0
}

LOCKFILE="uv.lock"
CONFIG=".osv-scanner.toml"

warn_skip() {
    # Print to stderr so the message is visible in the pre-push output
    # but the hook still exits 0 (push proceeds).
    printf 'audit_osv: WARN-SKIP: %s\n' "$1" >&2
    printf 'audit_osv: CI runs the authoritative online OSV-Scanner check on this push.\n' >&2
    exit 0
}

# --- Prerequisite gates: any missing prerequisite is a warn-skip, never
#     a block. An offline / fresh / non-Python dev box must be able to
#     push. ---

if ! command -v osv-scanner >/dev/null 2>&1; then
    warn_skip "osv-scanner binary not found on PATH (install: https://google.github.io/osv-scanner/installation/)."
fi

if [[ ! -f "${LOCKFILE}" ]]; then
    warn_skip "no ${LOCKFILE} found in ${REPO_ROOT} — nothing to scan."
fi

# --- Run the scan, capturing combined output so we can classify a
#     non-{0,1} exit as transient (warn-skip) vs a genuine tool error
#     (hard-fail). ---

config_arg=()
[[ -f "${CONFIG}" ]] && config_arg=(--config="${CONFIG}")

# The top of this script uses `set -uo pipefail` but NOT `set -e`, so a
# non-zero scanner exit does not terminate the script — we capture and
# classify `rc` ourselves below. (A `grep -q` no-match later must not kill
# the script either, which is another reason `-e` stays off.)
scan_output="$(osv-scanner --lockfile="${LOCKFILE}" "${config_arg[@]}" 2>&1)"
rc=$?

# Always surface the scanner's own output so a developer sees the detail.
[[ -n "${scan_output}" ]] && printf '%s\n' "${scan_output}"

case "${rc}" in
    0)
        printf 'audit_osv: OK — no un-ignored vulnerabilities in %s.\n' "${LOCKFILE}"
        exit 0
        ;;
    1)
        # Documented "vulnerabilities found" path. NEVER text-match around
        # this — exit 1 is exactly the condition the hook exists to block.
        printf 'audit_osv: FAIL — OSV-Scanner found un-ignored vulnerabilities in %s.\n' "${LOCKFILE}" >&2
        printf 'audit_osv: Fix: bump the affected dependency in pyproject.toml + refresh %s.\n' "${LOCKFILE}" >&2
        printf 'audit_osv: Only ignore via a justified, dated %s entry (CVSS-tiered ignoreUntil + reason + reviewer).\n' "${CONFIG}" >&2
        exit 1
        ;;
    *)
        # Non-{0,1}: tool/arg/runtime error. Warn-skip ONLY when the output
        # matches a recognised transient/offline network failure — otherwise
        # fail loudly so a broken config/args isn't silently skipped.
        # Match case-insensitively against the common offline/API signatures
        # osv-scanner emits when it can't reach the osv.dev advisory API.
        transient_re='api\.osv\.dev|osv\.dev|no such host|temporary failure|connection refused|connection reset|i/o timeout|tls handshake timeout|network is unreachable|deadline exceeded|context deadline|dial tcp|server misbehaving|could not (resolve|reach)|name resolution|(^| )50[234]( |$)|too many requests|429'
        if printf '%s' "${scan_output}" | grep -qiE "${transient_re}"; then
            warn_skip "OSV-Scanner could not reach the osv.dev advisory API (offline / transient, exit ${rc})."
        fi
        printf 'audit_osv: ERROR — OSV-Scanner exited %d with an unrecognised error (NOT a clean offline skip).\n' "${rc}" >&2
        printf 'audit_osv: This is a tool/config/args problem, not a network blip — fix it rather than skipping.\n' >&2
        exit 1
        ;;
esac
