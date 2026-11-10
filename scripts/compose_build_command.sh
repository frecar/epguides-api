#!/usr/bin/env bash
# Shared by the deploy renderer and the deploy-build-parity composite action.
# The caller owns retry, logging, locking, preflight and image scanning.

build_service_log() {
    local message="$*"
    local service_name="${BUILD_SERVICE_NAME:-compose}"
    if [ -n "${DEPLOY_LOG_FILE:-}" ]; then
        printf '%s: [build-dedup] %s for %s\n' "$(date)" "$message" "$service_name" \
            >> "$DEPLOY_LOG_FILE" 2>/dev/null || true
    else
        printf '%s: [build-dedup] %s for %s\n' "$(date)" "$message" "$service_name" >&2
    fi
}

# Print the smallest service list that builds every distinct image exactly
# once. Empty output means build all services; any missing tool or invalid
# Compose config therefore fails open to the historical build-everything path.
compose_dedup_build_targets() {
    local compose_prefix="${1:-}"
    local config lines lines_rc total_count canon_names canon_count config_rc

    if ! command -v jq >/dev/null 2>&1; then
        build_service_log "jq unavailable; skipping shared-image build dedup (fail-open: building every service, same as before)"
        return 0
    fi

    set +e
    config=$(python3 - "$compose_prefix" 2>/dev/null <<'PY'
import shlex
import subprocess
import sys

try:
    prefix = shlex.split(sys.argv[1])
except ValueError:
    raise SystemExit(2)
if not prefix:
    raise SystemExit(2)
result = subprocess.run(
    [*prefix, "config", "--format", "json"],
    check=False,
    capture_output=True,
    text=True,
)
if result.returncode:
    raise SystemExit(result.returncode)
sys.stdout.write(result.stdout)
PY
)
    config_rc=$?
    set -e
    if [ "$config_rc" -ne 0 ] || [ -z "$config" ] || ! printf '%s' "$config" | jq -e . >/dev/null 2>&1; then
        build_service_log "compose config unavailable/unparseable; skipping shared-image build dedup (fail-open: building every service, same as before)"
        return 0
    fi

    set +e
    lines=$(printf '%s' "$config" | jq -r '
        .services
        | to_entries[]
        | select(.value.build != null)
        | [
            ([
              (.value.image // .key),
              (.value.build.context // ""),
              (.value.build.dockerfile // ""),
              (.value.build.target // ""),
              (.value.build.args // {} | to_entries | sort_by(.key)),
              (.value.build.additional_contexts // {} | to_entries | sort_by(.key)),
              (.value.build.secrets // [] | sort),
              (.value.build.ssh // [] | sort),
              (.value.build.platform // .value.build.platforms // "")
            ] | @json | @base64),
            .key
          ]
        | @tsv
    ' 2>/dev/null)
    lines_rc=$?
    set -e
    if [ "$lines_rc" -ne 0 ] || [ -z "$lines" ]; then
        return 0
    fi

    total_count=$(printf '%s\n' "$lines" | wc -l | tr -d '[:space:]')
    canon_names=$(printf '%s\n' "$lines" | awk -F'\t' '!seen[$1]++ { printf "%s ", $2 }')
    canon_names=$(printf '%s' "$canon_names" | sed 's/[[:space:]]*$//')
    if [ -z "$canon_names" ]; then
        return 0
    fi
    canon_count=$(printf '%s' "$canon_names" | wc -w | tr -d '[:space:]')

    if [ -z "$total_count" ] || [ -z "$canon_count" ]; then
        return 0
    fi
    if [ "$canon_count" -ge "$total_count" ] 2>/dev/null; then
        return 0
    fi

    build_service_log "narrowed compose build from $total_count service(s) to $canon_count distinct-image build(s): $canon_names"
    printf '%s' "$canon_names"
    return 0
}

# Execute the common first-attempt build argv without evaluating a shell
# string. Prefix and build flags are trusted renderer outputs; service names
# arrive as distinct positional arguments. The `--` separator is present only
# when a deduped service list exists.
compose_build_command() {
    local compose_prefix="${1:-}"
    local pull="${2:-}"
    local build_flags="${3:-}"
    shift 3
    python3 - "$compose_prefix" "$pull" "$build_flags" "$@" <<'PY'
import shlex
import subprocess
import sys

try:
    prefix = shlex.split(sys.argv[1])
    flags = shlex.split(sys.argv[3])
except ValueError as exc:
    print(f"compose_build_command: invalid command arguments: {exc}", file=sys.stderr)
    raise SystemExit(2)
if not prefix:
    print("compose_build_command: empty Compose command prefix", file=sys.stderr)
    raise SystemExit(2)
pull = sys.argv[2]
if pull not in {"true", "false"}:
    print("compose_build_command: pull must be true or false", file=sys.stderr)
    raise SystemExit(2)
services = sys.argv[4:]
command = [*prefix, "build", *flags]
if pull == "true":
    command.append("--pull")
if services:
    command.extend(["--", *services])
result = subprocess.call(command)
raise SystemExit(128 - result if result < 0 else result)
PY
}
