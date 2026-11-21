#!/usr/bin/env bash
set -uo pipefail

#
#
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}" || {
    printf 'audit_osv: WARN-SKIP: could not cd to repo root %s.\n' "${REPO_ROOT}" >&2
    exit 0
}

LOCKFILE="uv.lock"
CONFIG=".osv-scanner.toml"

warn_skip() {
    printf 'audit_osv: WARN-SKIP: %s\n' "$1" >&2
    printf 'audit_osv: CI runs the authoritative online OSV-Scanner check on this push.\n' >&2
    exit 0
}


if ! command -v osv-scanner >/dev/null 2>&1; then
    warn_skip "osv-scanner binary not found on PATH (install: https://google.github.io/osv-scanner/installation/)."
fi

if [[ ! -f "${LOCKFILE}" ]]; then
    warn_skip "no ${LOCKFILE} found in ${REPO_ROOT} — nothing to scan."
fi


config_arg=()
[[ -f "${CONFIG}" ]] && config_arg=(--config="${CONFIG}")

scan_output="$(osv-scanner --lockfile="${LOCKFILE}" "${config_arg[@]}" 2>&1)"
rc=$?

[[ -n "${scan_output}" ]] && printf '%s\n' "${scan_output}"

case "${rc}" in
    0)
        printf 'audit_osv: OK — no un-ignored vulnerabilities in %s.\n' "${LOCKFILE}"
        exit 0
        ;;
    1)
        printf 'audit_osv: FAIL — OSV-Scanner found un-ignored vulnerabilities in %s.\n' "${LOCKFILE}" >&2
        printf 'audit_osv: Fix: bump the affected dependency in pyproject.toml + refresh %s.\n' "${LOCKFILE}" >&2
        printf 'audit_osv: Only ignore via a justified, dated %s entry (CVSS-tiered ignoreUntil + reason + reviewer).\n' "${CONFIG}" >&2
        exit 1
        ;;
    *)
        transient_re='api\.osv\.dev|osv\.dev|no such host|temporary failure|connection refused|connection reset|i/o timeout|tls handshake timeout|network is unreachable|deadline exceeded|context deadline|dial tcp|server misbehaving|could not (resolve|reach)|name resolution|(^| )50[234]( |$)|too many requests|429'
        if printf '%s' "${scan_output}" | grep -qiE "${transient_re}"; then
            warn_skip "OSV-Scanner could not reach the osv.dev advisory API (offline / transient, exit ${rc})."
        fi
        printf 'audit_osv: ERROR — OSV-Scanner exited %d with an unrecognised error (NOT a clean offline skip).\n' "${rc}" >&2
        printf 'audit_osv: This is a tool/config/args problem, not a network blip — fix it rather than skipping.\n' >&2
        exit 1
        ;;
esac
