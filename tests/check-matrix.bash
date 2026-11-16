#!/usr/bin/env bash
# Recompute the result against the reviewed case oracle; no record is executable.
set -euo pipefail
SCRIPT_DIR=$(CDPATH='' cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
readonly SCRIPT_DIR
manifest="$SCRIPT_DIR/rapid-cases.json"

validate_manifest() {
    jq -es '
        length == 1 and (.[0] |
          .schema == "bashcmdr.rapid-cases.v1" and (.cases | type) == "array" and (.cases | length) > 0
          and ([.cases[].id] == [range(1; (.cases | length) + 1)])
          and all(.cases[];
            (.expected_exit == 0 or .expected_exit == 1)
            and (.argv | type) == "array" and (.argv | length) > 0
            and all(.argv[]; type == "string" and (contains("\u0000") | not))))
    ' "$manifest" >/dev/null
}

if ! validate_manifest; then
    printf 'Invalid rapid case manifest: %s\n' "$manifest" >&2; exit 1
fi
if [[ ${1-} == --manifest-only && $# == 1 ]]; then exit 0; fi

if (($# == 0)); then
    shopt -s nullglob
    set -- "$SCRIPT_DIR"/results/factorial.*/rapid_test_results.json
fi
if (($# == 0)); then printf 'No factorial results found\n' >&2; exit 1; fi
failed=0
for result in "$@"; do
    if [[ ! -f "$result" || -L "$result" ]]; then
        printf 'Missing or linked result file: %s\n' "$result" >&2; failed=1; continue
    fi
    if ! jq -es --slurpfile oracle "$manifest" '
        length == 1 and (.[0] as $data | $oracle[0].cases as $cases |
          $data.metadata.schema == "bashcmdr.rapid-results.v1"
          and ($data.metadata.executable | type) == "string" and ($data.metadata.executable | length) > 0
          and $data.metadata.case_count == ($cases | length)
          and ($data.results | type) == "array" and ($data.results | length) == ($cases | length)
          and ([$data.results[].test_id] | sort) == [$cases[].id]
          and all($data.results[];
            . as $row | ($cases[] | select(.id == $row.test_id)) as $case |
            ($row.argv | type) == "array" and ($row.argv | length) == (($case.argv | length) + 1)
            and $row.argv[0] == $data.metadata.executable
            and $row.argv[1:] == $case.argv and $row.expected_exit == $case.expected_exit
            and ($row.exit_code | type) == "number" and $row.exit_code == $case.expected_exit
            and $row.passed == true
            and $row.classification == (if $case.expected_exit == 0 then "success" else "expected_failure" end)
            and ($row.command | type) == "string" and ($row.command | length) > 0 and ($row.output | type) == "string"
            and $row.output_log == ("case-" + ($case.id | tostring) + ".output.log")))
    ' "$result" >/dev/null; then
        printf 'Matrix has incomplete, invalid or mismatched results: %s\n' "$result" >&2
        failed=1; continue
    fi
    # The JSON predicate constrains these names to generated local case files.
    while IFS= read -r log; do
        if [[ ! -f "${result%/*}/$log" || -L "${result%/*}/$log" ]]; then
            printf 'Missing case diagnostic: %s/%s\n' "${result%/*}" "$log" >&2; failed=1
        fi
    done < <(jq -r '.results[].output_log' "$result")
    printf 'Checked matrix: %s\n' "$result"
done
exit "$failed"
