#!/usr/bin/env bash
# Managed CI helper. Build production Compose recipes and scan their exact images.
set -euo pipefail
umask 077
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
operation=${1:-build}
case "$operation" in
  scan)
    ids_file=$(mktemp "${RUNNER_TEMP}/compose-image-ids.XXXXXX")
    trap 'rm -f -- "$ids_file"' EXIT
    printf '%s' "${IMAGE_IDS:?immutable image IDs required}" > "$ids_file"
    python3 "$script_dir/scan_images.py" --image-ids "$ids_file" --severity "${2:?severity required}" --ignorefile .trivyignore.image
    exit
    ;;
  cleanup)
    python3 "$script_dir/images.py" cleanup --tags-json "${IMAGE_TAGS:-[]}"
    exit
    ;;
  build) ;;
  *) echo "operation must be build, scan or cleanup" >&2; exit 2 ;;
esac
# The co-published library is checked by the consumer-bundle runtime controls.
# shellcheck source=/dev/null
source "$script_dir/compose_build_command.sh"
export GIT_SHA
GIT_SHA=$(git rev-parse HEAD)
# BEGIN GENERATED security refresh epoch — DO NOT EDIT BY HAND.
OS_SECURITY_EPOCH="$(date -u +%Y%m%d)" || OS_SECURITY_EPOCH=""; case "$OS_SECURITY_EPOCH" in [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]) : ;; *) echo "OS_SECURITY_EPOCH_INVALID: refusing to build without a valid UTC refresh epoch" >&2; false ;; esac
# END GENERATED security refresh epoch.
# BEGIN GENERATED production Compose build flags — DO NOT EDIT BY HAND.
build_flags="--build-arg OS_SECURITY_EPOCH=$OS_SECURITY_EPOCH"
# END GENERATED production Compose build flags.
export OS_SECURITY_EPOCH
plan_dir=$(mktemp -d "${RUNNER_TEMP}/compose-plan.XXXXXX")
trap 'rm -rf -- "$plan_dir"' EXIT
namespace=$(python3 -c 'import uuid; print("ci-" + uuid.uuid4().hex)')
python3 - "$plan_dir" <<'PY'
import json
import os
import pathlib
import sys

directory = pathlib.Path(sys.argv[1])
prefix = ["docker", "compose"]
for filename in os.environ.get("COMPOSE_FILES", "docker-compose.prod.yml").split():
    prefix.extend(["-f", filename])
(directory / "prefix.json").write_text(json.dumps(prefix))
(directory / "profiles.json").write_text(json.dumps(os.environ.get("COMPOSE_PROFILES_INPUT", "").split()))
PY
python3 "$script_dir/images.py" prepare --directory "$plan_dir" --namespace "$namespace" \
    --prefix-json "$plan_dir/prefix.json" --profiles-json "$plan_dir/profiles.json" > /dev/null
# Publish owned tags before building, so a partial failure can still clean up.
compose_cmd=$(python3 - "$plan_dir/state.json" <<'PY'
import json
import os
import pathlib
import shlex
import sys

state = json.loads(pathlib.Path(sys.argv[1]).read_text())
tags = list(dict.fromkeys(state["service_tags"].values()))
with open(os.environ["GITHUB_OUTPUT"], "a") as output:
    output.write("image-tags=" + json.dumps(tags, separators=(",", ":")) + "\n")
print(shlex.join(state["prefix"]))
PY
)
set -f
services=()
targets=$(compose_dedup_build_targets "$compose_cmd")
for service in $targets; do services+=("$service"); done
compose_build_command "$compose_cmd" true "$build_flags" "${services[@]}"
python3 "$script_dir/images.py" capture --directory "$plan_dir" > "$plan_dir/images.json"
python3 - "$plan_dir/images.json" <<'PY'
import json
import os
import pathlib
import sys

values = json.loads(pathlib.Path(sys.argv[1]).read_text())
with open(os.environ["GITHUB_OUTPUT"], "a") as output:
    for name, value in values.items():
        output.write(f"{name}={json.dumps(value, separators=(',', ':'))}\n")
PY
