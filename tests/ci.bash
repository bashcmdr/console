#!/usr/bin/env bash
# Required development checks; the release support matrix is a separate decision.
set -euo pipefail
entry=${BASH_SOURCE[0]}
[[ $entry == */* ]] || entry="./$entry"
root=$(CDPATH='' cd -- "${entry%/*}/.." && pwd -P)
mkdir -p "$root/tests/results/ci"
if [[ ! -f "$root/tests/ci_driver.py" ]]; then
    printf '%s\n' 'Required CI driver is missing: tests/ci_driver.py' > "$root/tests/results/ci/bootstrap-failure.log"
    cat "$root/tests/results/ci/bootstrap-failure.log" >&2
    exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
    printf '%s\n' 'Console development checks require python3 on PATH.' > "$root/tests/results/ci/bootstrap-failure.log"
    cat "$root/tests/results/ci/bootstrap-failure.log" >&2
    exit 127
fi
exec python3 "$root/tests/ci_driver.py" --bash "$BASH" "$@"
