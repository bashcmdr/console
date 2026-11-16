#!/usr/bin/env bash
# Full Factorial Test Runner for bashcmdr
# Executes comprehensive command matrix validation
# Updated for v1.1.0 noun-verb grammar: bcm [noun] <verb> [args] [flags]

set -euo pipefail

# The private child entry is issued only by harness.bash's clean environment.
if [[ ${1-} != --bcm-test-child ]]; then
    __bcm_suite_env=("PATH=$PATH")
    [[ ! ${TMPDIR+x} ]] || __bcm_suite_env+=("TMPDIR=$TMPDIR")
    [[ ! ${BASHCMDR_TEST_RESULTS_DIR+x} ]] || __bcm_suite_env+=("BASHCMDR_TEST_RESULTS_DIR=$BASHCMDR_TEST_RESULTS_DIR")
    __bcm_suite_file="${BASH_SOURCE[0]}"
    [[ "$__bcm_suite_file" == */* ]] || __bcm_suite_file="./$__bcm_suite_file"
    exec env -i "${__bcm_suite_env[@]}" "$BASH" --noprofile --norc "${__bcm_suite_file%/*}/harness.bash" factorial "$__bcm_suite_file" "$@"
fi
shift
: "${BCM_TEST_TEMP:?run through harness.bash}"

TEST_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly TEST_ROOT
readonly RESULTS_DIR="$BCM_TEST_ARTIFACTS"
readonly BCM="$BCM_TEST_CONSOLE/bin/bashcmdr"

# Positive search/list cases use a known local empty index. Deliberate missing
# cartridge/invalid command cases retain their explicit rejection expectations.
mkdir -p "$HOME/.bashcmdr/registry"
printf '%s\n' '{"version":"fixture","cartridges":{}}' > "$HOME/.bashcmdr/registry/index.json"

run_test_case() {
    local test_id="$1" expected_exit="$2"
    shift 2
    local -a argv=("$@")
    local start_time end_time duration cmd first_line=''
    local exit_code=0 passed=false classification output_log="case-${test_id}.output.log"
    start_time=$SECONDS
    "${argv[@]}" > "$RESULTS_DIR/$output_log" 2>&1 || exit_code=$?
    end_time=$SECONDS
    duration=$((end_time - start_time))
    if [[ "$exit_code" == "$expected_exit" ]]; then
        passed=true
        [[ "$expected_exit" == 0 ]] && classification=success || classification=expected_failure
    elif [[ "$exit_code" == 0 || "$exit_code" == 1 ]]; then
        classification=mismatch
    else
        classification=error
    fi
    printf -v cmd '%q ' "${argv[@]}"
    cmd="${cmd% }"
    IFS= read -r first_line < "$RESULTS_DIR/$output_log" || true
    jq -cn --argjson id "$test_id" --arg command "$cmd" --argjson status "$exit_code" \
        --argjson expected "$expected_exit" --argjson passed "$passed" \
        --arg classification "$classification" --argjson duration "$duration" \
        --arg output "$first_line" --arg output_log "$output_log" --args '
        {test_id:$id,command:$command,argv:$ARGS.positional,exit_code:$status,
         expected_exit:$expected,passed:$passed,classification:$classification,
         duration:$duration,output:$output,output_log:$output_log}' -- "${argv[@]}"
}

generate_rapid_matrix() {
    local case_id expected argc arg i timestamp
    local -a argv=()
    if ! timestamp=$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null) ||
       [[ ! "$timestamp" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]]; then
        printf '%s\n' 'Cannot produce UTC report timestamp: date -u with the standard date/time format is required' >&2
        return 1
    fi
    "$BCM_TEST_BASH" "$TEST_ROOT/check-matrix.bash" --manifest-only
    # Check the complete producer before executing any case. NUL boundaries keep
    # argument data out of shell source and preserve spaces/quotes/backslashes.
    jq -j '.cases[] | (.id|tostring), "\u0000", (.expected_exit|tostring), "\u0000",
        (.argv|length|tostring), "\u0000", (.argv[] | ., "\u0000")' \
        "$TEST_ROOT/rapid-cases.json" > "$RESULTS_DIR/case-arguments.bin"
    : > "$RESULTS_DIR/case-records.jsonl"
    while IFS= read -r -d '' case_id; do
        IFS= read -r -d '' expected || return 1
        IFS= read -r -d '' argc || return 1
        argv=("$BCM")
        for ((i=0; i<argc; i++)); do
            IFS= read -r -d '' arg || return 1
            argv+=("$arg")
        done
        run_test_case "$case_id" "$expected" "${argv[@]}" >> "$RESULTS_DIR/case-records.jsonl"
    done < "$RESULTS_DIR/case-arguments.bin"
    jq -s --arg timestamp "$timestamp" --arg executable "$BCM" --slurpfile oracle "$TEST_ROOT/rapid-cases.json" '
        {metadata:{schema:"bashcmdr.rapid-results.v1",generated_at:$timestamp,
                   duration_clock:"bash_SECONDS",duration_resolution_seconds:1,
                   test_type:"rapid_factorial",grammar:"noun-verb v1.1.0",
                   executable:$executable,
                   case_count:($oracle[0].cases|length)},results:.}
    ' "$RESULTS_DIR/case-records.jsonl" > "$RESULTS_DIR/rapid_test_results.json"
}

main() {
    printf '=== bashcmdr Factorial Test Runner ===\nResults directory: %s\n' "$RESULTS_DIR" >&2
    mkdir -p "$RESULTS_DIR"
    generate_rapid_matrix
    "$BCM_TEST_BASH" "$TEST_ROOT/check-matrix.bash" "$RESULTS_DIR/rapid_test_results.json"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then main "$@"; fi
