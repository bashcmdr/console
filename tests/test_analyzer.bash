#!/usr/bin/env bash
# Analyze current rapid result records without executing their command/output data.

__bcm_analyzer_source_directory() (
    local file="${BASH_SOURCE[0]}"
    [[ "$file" == */* ]] || file="./$file"
    CDPATH='' cd -P -- "${file%/*}" && pwd -P
)

if ! __BCM_ANALYZER_DIRECTORY=$(__bcm_analyzer_source_directory); then
    printf 'Cannot resolve analyzer source directory\n' >&2
    if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then exit 1; else return 1; fi
fi
unset -f __bcm_analyzer_source_directory
__bcm_analyzer_directory() { printf '%s\n' "$__BCM_ANALYZER_DIRECTORY"; }

__bcm_analyzer_percentage() {
    command -v jq >/dev/null || { printf 'Analyzer percentages require jq\n' >&2; return 1; }
    jq -nr --argjson numerator "$1" --argjson denominator "$2" '
        if ($numerator | type) != "number" or ($denominator | type) != "number"
           or $numerator < 0 or $denominator < 0 then error("invalid percentage counts")
        elif $denominator == 0 then 0
        else (($numerator * 1000 / $denominator) | floor) / 10 end'
}

__bcm_analyzer_model() {
    local input="${1-}" directory model
    command -v jq >/dev/null || { printf 'Analyzer requires jq on PATH\n' >&2; return 1; }
    if [[ ! -f "$input" || ! -r "$input" ]]; then
        printf 'Readable results file required: %s\n' "$input" >&2
        return 1
    fi
    directory=$(__bcm_analyzer_directory) || return 1
    if ! model=$(jq -cs -f "$directory/analyzer.jq" -- "$input") || [[ -z "$model" ]]; then
        printf 'Analyzer input validation or jq producer failed: %s\n' "$input" >&2
        return 1
    fi
    printf '%s\n' "$model"
}

__bcm_analyzer_format() {
    local kind="$1" model="$2" text
    if ! text=$(jq -r --arg kind "$kind" '
      if $kind == "summary" then
        "=== Test Results Analysis ===",
        "  Total tests: \(.summary.total)",
        "  Successful: \(.summary.successful) (\(.summary.success_percentage)%)",
        "  Expected failures: \(.summary.expected_failures) (\(.summary.expected_percentage)%)",
        "  Mismatches: \(.summary.mismatches) (\(.summary.mismatch_percentage)%)",
        "  Errors: \(.summary.errors) (\(.summary.error_percentage)%)",
        "  Matched expectations: \(.summary.matched)/\(.summary.total)",
        "", "Command categories (matched expectations / attempts):",
        (.categories | to_entries[] | "  \(.key): \(.value.matched)/\(.value.total) matched expectations")
      elif $kind == "failure" then
        "=== Test Failure Analysis Report ===",
        "Expected negative outcomes are counted separately from failures.",
        "Failures: \(.failures | length)",
        (.failures[] | "  #\(.test_id) \(.args | tojson): \(.classification), exit \(.exit_code), expected \(.expected_exit); output \(.output | tojson)"),
        "", "Failure output patterns:",
        (.patterns[] | "  \(.count) occurrences: \(.output | tojson)"),
        "", "Performance (seconds):",
        "  Clock: \(.timing.clock | tojson); resolution: \(.timing.resolution_seconds // "unspecified")",
        "  Average: \(.timing.average // "unavailable")",
        "  Maximum: \(.timing.maximum // "unavailable")",
        "  Minimum: \(.timing.minimum // "unavailable")",
        (.slowest[] | "  #\(.test_id) \(.args | tojson): \(.duration)s")
      elif $kind == "coverage" then
        "=== Observed Command Coverage Report ===",
        "Observed argv requests: \(.coverage | length)",
        "Total attempts: \(.summary.total); matched expectations: \(.summary.matched)",
        "This lists observed requests; it does not establish coverage of untested commands.",
        (.coverage[] | "  \(.args | tojson): \(.statistics.matched)/\(.statistics.total) matched expectations; success \(.statistics.successful), expected failure \(.statistics.expected_failures), mismatch \(.statistics.mismatches), error \(.statistics.errors)")
      else error("unknown report format") end
    ' <<< "$model") || [[ -z "$text" ]]; then
        printf 'Analyzer report query failed: %s\n' "$kind" >&2
        return 1
    fi
    printf '%s\n' "$text"
}

# Buffer/validate producers before touching a report; stage the write beside it.
__bcm_analyzer_write() (
    local target="$1" text="$2" parent stage=''
    [[ -n "$target" ]] || { printf 'Report destination is required\n' >&2; return 1; }
    if [[ -L "$target" || ( -e "$target" && ! -f "$target" ) ]]; then
        printf 'Report destination must be an ordinary file or absent: %s\n' "$target" >&2
        return 1
    fi
    parent="${target%/*}"; [[ "$parent" != "$target" ]] || parent='.'
    [[ -d "$parent" ]] || { printf 'Report parent unavailable: %s\n' "$parent" >&2; return 1; }
    stage=$(mktemp "$parent/.analyzer-report.XXXXXXXX") || return 1
    trap '[[ -z "$stage" ]] || rm -f -- "$stage"' EXIT
    printf '%s\n' "$text" > "$stage" || return 1
    mv -f -- "$stage" "$target" || return 1
    stage=''
)

analyze_results() {
    local model text
    model=$(__bcm_analyzer_model "${1-}") || return 1
    text=$(__bcm_analyzer_format summary "$model") || return 1
    printf '%s\n' "$text"
}

generate_failure_report() {
    local model text
    model=$(__bcm_analyzer_model "${1-}") || return 1
    text=$(__bcm_analyzer_format failure "$model") || return 1
    __bcm_analyzer_write "${2-}" "$text"
}

generate_coverage_report() {
    local model text
    model=$(__bcm_analyzer_model "${1-}") || return 1
    text=$(__bcm_analyzer_format coverage "$model") || return 1
    __bcm_analyzer_write "${2-}" "$text"
}

__bcm_analyzer_main() (
    local input='' output='' directory model summary failure coverage reports
    while (($#)); do
        case "$1" in
            -h|--help)
                printf '%s\n' 'Usage: bash test_analyzer.bash [--output-dir DIR] [--] RESULTS.json'
                printf '%s\n' 'Input: current rapid-results.v1 JSON with structured argv and consistent outcomes.'
                printf '%s\n' 'Default output: a unique analysis.* directory under ignored tests/results/.'
                return 0 ;;
            --output-dir)
                if (($# < 2)) || [[ -z "$2" ]]; then printf '%s\n' '--output-dir requires a nonempty directory' >&2; return 1; fi
                output="$2"; shift 2 ;;
            --)
                shift
                if (($# != 1)) || [[ -n "$input" ]]; then printf 'Exactly one RESULTS.json is required\n' >&2; return 1; fi
                input="$1"; shift ;;
            -*) printf 'Unknown analyzer option: %s\n' "$1" >&2; return 1 ;;
            *)
                [[ -z "$input" ]] || { printf 'Exactly one RESULTS.json is required\n' >&2; return 1; }
                input="$1"; shift ;;
        esac
    done
    [[ -n "$input" ]] || { printf 'Provide RESULTS.json from the rapid runner; use --help for usage\n' >&2; return 1; }
    model=$(__bcm_analyzer_model "$input") || return 1
    summary=$(__bcm_analyzer_format summary "$model") || return 1
    failure=$(__bcm_analyzer_format failure "$model") || return 1
    coverage=$(__bcm_analyzer_format coverage "$model") || return 1
    if [[ -z "$output" ]]; then
        directory=$(__bcm_analyzer_directory) || return 1
        output="$directory/results"
    fi
    if [[ -L "$output" || ( -e "$output" && ! -d "$output" ) ]]; then
        printf 'Analyzer output root must be an ordinary directory or absent: %s\n' "$output" >&2
        return 1
    fi
    mkdir -p -- "$output" || return 1
    reports=$(mktemp -d "$output/analysis.XXXXXXXX") || return 1
    if ! __bcm_analyzer_write "$reports/analysis.json" "$model" ||
       ! __bcm_analyzer_write "$reports/summary.txt" "$summary" ||
       ! __bcm_analyzer_write "$reports/failure_analysis.txt" "$failure" ||
       ! __bcm_analyzer_write "$reports/coverage_report.txt" "$coverage"; then
        printf 'Analyzer output failed; incomplete files retained at: %s\n' "$reports" >&2
        return 1
    fi
    printf '%s\n' "$summary"
    printf 'Reports written: %s\n' "$reports" >&2
)

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    set -euo pipefail
    __bcm_analyzer_main "$@"
fi
