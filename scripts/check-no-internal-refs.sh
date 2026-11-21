#!/usr/bin/env bash
set -euo pipefail

forbidden_regex='a[s]gard|s[e]ntinel|carlsen[.]io|10[.]168|10[.]88|cluster'

is_allowlisted_match() {
    local file="$1"
    local line="$2"
    local remaining="$line"

    if [[ "$file" == "pyproject.toml" ]]; then
        remaining="${remaining//fredrik@carlsen.io/}"
    fi

    if [[ "$remaining" != "$line" ]] && ! grep -Eiq "$forbidden_regex" <<<"$remaining"; then
        return 0
    fi

    return 1
}

files=()
if (($#)); then
    files=("$@")
else
    while IFS= read -r -d '' file; do
        files+=("$file")
    done < <(git ls-files -z)
fi

violations=0
for file in "${files[@]}"; do
    [[ -f "$file" ]] || continue

    [[ "$file" == "scripts/check-no-internal-refs.sh" ]] && continue

    while IFS= read -r match; do
        [[ -n "$match" ]] || continue
        line_no="${match%%:*}"
        line="${match#*:}"
        if is_allowlisted_match "$file" "$line"; then
            continue
        fi

        printf '%s:%s: private deployment reference: %s\n' "$file" "$line_no" "$line"
        violations=$((violations + 1))
    done < <(grep -nEIi "$forbidden_regex" -- "$file" || true)
done

if ((violations)); then
    printf '\nFAIL: %d private deployment reference(s) found in tracked files.\n' "$violations"
    printf 'Keep public code/docs standalone. Move deployment-specific values to runtime configuration.\n'
    exit 1
fi
