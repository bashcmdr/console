#!/usr/bin/env bash
# shellcheck disable=SC2031 # Output probes use subshells; state-mutating assertion calls stay in the parent, verified below.
# bashcmdr Resolver Unit Tests
# Direct unit tests for lib/resolver.bashcmdr functions
#
# Run: bash tests/test_resolver.bash
# (No cartridge-loading preconditions required — uses synthetic fixture manifests)

set -euo pipefail

# The private child entry is issued only by harness.bash's clean environment.
if [[ ${1-} != --bcm-test-child ]]; then
    __bcm_suite_env=("PATH=$PATH")
    [[ ! ${TMPDIR+x} ]] || __bcm_suite_env+=("TMPDIR=$TMPDIR")
    [[ ! ${BASHCMDR_TEST_RESULTS_DIR+x} ]] || __bcm_suite_env+=("BASHCMDR_TEST_RESULTS_DIR=$BASHCMDR_TEST_RESULTS_DIR")
    __bcm_suite_file="${BASH_SOURCE[0]}"
    [[ "$__bcm_suite_file" == */* ]] || __bcm_suite_file="./$__bcm_suite_file"
    exec env -i "${__bcm_suite_env[@]}" "$BASH" --noprofile --norc "${__bcm_suite_file%/*}/harness.bash" resolver "$__bcm_suite_file" "$@"
fi
shift
: "${BCM_TEST_TEMP:?run through harness.bash}"

# ── Setup ────────────────────────────────────────────────────────────────────

TEST_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; readonly TEST_SCRIPT_DIR
BASHCMDR_REPO_ROOT="$(dirname "$TEST_SCRIPT_DIR")";                readonly BASHCMDR_REPO_ROOT
readonly TEST_TEMP_DIR="$BCM_TEST_TEMP"
readonly TEST_LOG="$BCM_TEST_ARTIFACTS/test_results.log"
# shellcheck source=tests/assertions.bash
source "${BASH_SOURCE[0]%/*}/assertions.bash"


# Point resolver at our fixture cartridge tree
export BASHCMDR_ROOT="$BCM_TEST_CONSOLE"
# Suppress info/success/error output from the library under test
export BASHCMDR_VERBOSITY=0

# Create an empty config dir so core.bashcmdr init finds no stray config
mkdir -p "$BASHCMDR_ROOT/config" "$BASHCMDR_ROOT/cartridges"

echo "Test session started: $(date)" > "$TEST_LOG"

# Source resolver (which sources core.bashcmdr internally)
# shellcheck disable=SC1090
source "$BASHCMDR_REPO_ROOT/lib/resolver.bashcmdr"

# ── Test framework (pattern from tests/test_runner.bash) ─────────────────────

readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly NC='\033[0m'

declare -i TESTS_TOTAL=0
declare -i TESTS_PASSED=0
declare -i TESTS_FAILED=0
declare -a FAILED_TESTS=()

assert_success() {
    local description="$1"
    local command="$2"
    TESTS_TOTAL+=1
    if bcm_test_eval "$command"; then
        TESTS_PASSED+=1
        printf "${GREEN}✓${NC} %s\n" "$description"
        echo "PASS: $description" >> "$TEST_LOG"
    else
        TESTS_FAILED+=1
        FAILED_TESTS+=("$description")
        printf "${RED}✗${NC} %s\n" "$description"
        echo "FAIL: $description" >> "$TEST_LOG"
        echo "Command: $command" >> "$TEST_LOG"
    fi
}

assert_failure() {
    local description="$1"
    local command="$2"
    TESTS_TOTAL+=1
    if ! bcm_test_eval "$command"; then
        TESTS_PASSED+=1
        printf "${GREEN}✓${NC} %s\n" "$description"
        echo "PASS: $description" >> "$TEST_LOG"
    else
        TESTS_FAILED+=1
        FAILED_TESTS+=("$description")
        printf "${RED}✗${NC} %s\n" "$description"
        echo "FAIL: $description (expected failure but command succeeded)" >> "$TEST_LOG"
        echo "Command: $command" >> "$TEST_LOG"
    fi
}

assert_output_contains() {
    local description="$1"
    local command="$2"
    local expected_text="$3"
    TESTS_TOTAL+=1
    local output
    local command_status=0
    output=$(eval "$command" 2>&1) || command_status=$?
    bcm_test_note_command "$command" "$command_status" "$output"
    if [[ "$output" == *"$expected_text"* ]]; then
        TESTS_PASSED+=1
        printf "${GREEN}✓${NC} %s\n" "$description"
        echo "PASS: $description" >> "$TEST_LOG"
    else
        TESTS_FAILED+=1
        FAILED_TESTS+=("$description")
        printf "${RED}✗${NC} %s\n" "$description"
        {
            echo "FAIL: $description"
            echo "Command: $command"
            echo "Expected: $expected_text"
            echo "Got: $output"
        } >> "$TEST_LOG"
    fi
}

# New helper: compare two pre-evaluated values for equality
assert_equals() {
    local description="$1"
    local got="$2"
    local expected="$3"
    TESTS_TOTAL+=1
    if [[ "$got" == "$expected" ]]; then
        TESTS_PASSED+=1
        printf "${GREEN}✓${NC} %s\n" "$description"
        echo "PASS: $description" >> "$TEST_LOG"
    else
        TESTS_FAILED+=1
        FAILED_TESTS+=("$description")
        printf "${RED}✗${NC} %s (expected '%s', got '%s')\n" "$description" "$expected" "$got"
        printf "FAIL: %s (expected '%s', got '%s')\n" "$description" "$expected" "$got" >> "$TEST_LOG"
    fi
}

# ── Fixture helpers ───────────────────────────────────────────────────────────

# Helpers for array inspection (avoid single-quoted eval strings flagged by SC2016)
_dep_graph()    { echo "${BASHCMDR_DEPENDENCY_GRAPH[$1]:-}"; }
_constraint()   { echo "${BASHCMDR_DEPENDENCY_CONSTRAINTS[$1]:-}"; }
_dep_graph_empty() { [[ "${BASHCMDR_DEPENDENCY_GRAPH[$1]:-}" == "" ]]; }

# make_manifest <name> <version> [<dep>:<constraint> ...]
# Creates $BASHCMDR_ROOT/cartridges/<name>/manifest.json
make_manifest() {
    local name="$1" version="$2"
    shift 2
    local dir="$BASHCMDR_ROOT/cartridges/$name"
    mkdir -p "$dir"

    local deps_json="" pair dep constraint
    for pair in "$@"; do
        dep="${pair%%:*}"
        constraint="${pair#*:}"
        [[ -n "$deps_json" ]] && deps_json+=","
        deps_json+="\"${dep}\":\"${constraint}\""
    done

    printf '{"name":"%s","version":"%s","requires":{"cartridges":{%s}}}\n' \
        "$name" "$version" "$deps_json" > "$dir/manifest.json"
}

# Unset all three global arrays the resolver populates
reset_resolver_state() {
    unset BASHCMDR_DEPENDENCY_GRAPH BASHCMDR_DEPENDENCY_CONSTRAINTS BASHCMDR_ACTIVATION_ORDER
}

# ── Test: __bashcmdr_parse_version_constraint ─────────────────────────────────

# Helper: echo parsed field from a constraint string
_echo_parse_field() {
    local constraint="$1" field="$2"
    local -A parsed
    __bashcmdr_parse_version_constraint "$constraint" parsed || return 1
    echo "${parsed[$field]}"
}

test_parse_version_constraint() {
    printf '\n%b%s%b\n' "$BLUE" '=== Version Constraint Parsing Tests ===' "$NC"

    # Valid: explicit operators
    assert_success  "parse >=1.0.0 succeeds"   "_echo_parse_field '>=1.0.0'  operator"
    assert_output_contains ">=1.0.0 operator"  "_echo_parse_field '>=1.0.0'  operator"  ">="
    assert_output_contains ">=1.0.0 version"   "_echo_parse_field '>=1.0.0'  version"   "1.0.0"

    assert_output_contains "<=2.3.4 operator"  "_echo_parse_field '<=2.3.4'  operator"  "<="
    assert_output_contains ">1.0 operator"     "_echo_parse_field '>1.0'     operator"  ">"
    assert_output_contains "<0.9 operator"     "_echo_parse_field '<0.9'     operator"  "<"
    assert_output_contains "=3.0.0 operator"   "_echo_parse_field '=3.0.0'   operator"  "="
    assert_output_contains "~1.2.3 operator"   "_echo_parse_field '~1.2.3'   operator"  "~"
    assert_output_contains "^2.0 operator"     "_echo_parse_field '^2.0'     operator"  "^"

    # Valid: bare version → default operator "="
    assert_output_contains "bare version operator defaults to =" \
        "_echo_parse_field '1.0.0' operator" "="
    assert_output_contains "bare version value" \
        "_echo_parse_field '1.0.0' version" "1.0.0"

    # Valid: 2-part and 1-part versions
    assert_success "2-part version parses" "_echo_parse_field '>=1.2' version"
    assert_success "1-part version parses" "_echo_parse_field '^1'    version"

    # Invalid
    assert_failure "non-version string fails"  "_echo_parse_field 'not-valid' operator"
    assert_failure "empty string fails"        "_echo_parse_field '' operator"
    assert_failure "letters-only fails"        "_echo_parse_field 'latest' operator"
}

# ── Test: __bashcmdr_version_compare ─────────────────────────────────────────

test_version_compare() {
    printf '\n%b%s%b\n' "$BLUE" '=== Version Comparison Tests ===' "$NC"

    # = equality
    assert_success  "1.0.0 = 1.0.0"           "__bashcmdr_version_compare 1.0.0 '='  1.0.0"
    assert_failure  "1.0.1 = 1.0.0 fails"     "__bashcmdr_version_compare 1.0.1 '='  1.0.0"

    # != inequality
    assert_success  "1.0.1 != 1.0.0"          "__bashcmdr_version_compare 1.0.1 '!=' 1.0.0"
    assert_failure  "1.0.0 != 1.0.0 fails"    "__bashcmdr_version_compare 1.0.0 '!=' 1.0.0"

    # > greater-than
    assert_success  "1.0.1 > 1.0.0"           "__bashcmdr_version_compare 1.0.1 '>'  1.0.0"
    assert_success  "2.0.0 > 1.9.9"           "__bashcmdr_version_compare 2.0.0 '>'  1.9.9"
    assert_failure  "1.0.0 > 1.0.0 fails"     "__bashcmdr_version_compare 1.0.0 '>'  1.0.0"
    assert_failure  "0.9.9 > 1.0.0 fails"     "__bashcmdr_version_compare 0.9.9 '>'  1.0.0"

    # >= greater-or-equal
    assert_success  "1.0.0 >= 1.0.0"          "__bashcmdr_version_compare 1.0.0 '>=' 1.0.0"
    assert_success  "1.0.1 >= 1.0.0"          "__bashcmdr_version_compare 1.0.1 '>=' 1.0.0"
    assert_failure  "0.9.9 >= 1.0.0 fails"    "__bashcmdr_version_compare 0.9.9 '>=' 1.0.0"

    # < less-than
    assert_success  "1.0.0 < 1.0.1"           "__bashcmdr_version_compare 1.0.0 '<'  1.0.1"
    assert_failure  "1.0.0 < 1.0.0 fails"     "__bashcmdr_version_compare 1.0.0 '<'  1.0.0"
    assert_failure  "1.0.1 < 1.0.0 fails"     "__bashcmdr_version_compare 1.0.1 '<'  1.0.0"

    # <= less-or-equal
    assert_success  "1.0.0 <= 1.0.0"          "__bashcmdr_version_compare 1.0.0 '<=' 1.0.0"
    assert_success  "0.9.0 <= 1.0.0"          "__bashcmdr_version_compare 0.9.0 '<=' 1.0.0"
    assert_failure  "1.0.1 <= 1.0.0 fails"    "__bashcmdr_version_compare 1.0.1 '<=' 1.0.0"

    # ~ tilde: same major.minor, ver1 >= ver2
    assert_success  "1.2.5 ~ 1.2.0 (patch compatible)"    "__bashcmdr_version_compare 1.2.5 '~' 1.2.0"
    assert_success  "1.2.0 ~ 1.2.0 (same patch)"          "__bashcmdr_version_compare 1.2.0 '~' 1.2.0"
    assert_failure  "1.3.0 ~ 1.2.0 (diff minor fails)"    "__bashcmdr_version_compare 1.3.0 '~' 1.2.0"
    assert_failure  "2.2.0 ~ 1.2.0 (diff major fails)"    "__bashcmdr_version_compare 2.2.0 '~' 1.2.0"
    assert_failure  "1.1.9 ~ 1.2.0 (older fails)"         "__bashcmdr_version_compare 1.1.9 '~' 1.2.0"

    # ^ caret: same major, ver1 >= ver2
    assert_success  "1.5.3 ^ 1.2.0 (minor bump OK)"       "__bashcmdr_version_compare 1.5.3 '^' 1.2.0"
    assert_success  "1.2.0 ^ 1.2.0 (same version)"        "__bashcmdr_version_compare 1.2.0 '^' 1.2.0"
    assert_failure  "2.0.0 ^ 1.2.0 (diff major fails)"    "__bashcmdr_version_compare 2.0.0 '^' 1.2.0"
    assert_failure  "1.1.0 ^ 1.2.0 (older minor fails)"   "__bashcmdr_version_compare 1.1.0 '^' 1.2.0"

    # Version padding: 2-part and 1-part
    assert_success  "1.0 treated as 1.0.0 (>= compare)"   "__bashcmdr_version_compare 1.0  '>=' 1.0.0"
    assert_success  "1 treated as 1.0.0 (= compare)"      "__bashcmdr_version_compare 1    '='  1.0.0"

    # Unknown operator
    assert_failure  "unknown operator fails"               "__bashcmdr_version_compare 1.0.0 'bogus' 1.0.0"
}

# ── Test: __bashcmdr_load_dependencies ───────────────────────────────────────

test_load_dependencies() {
    printf '\n%b%s%b\n' "$BLUE" '=== Dependency Loading Tests ===' "$NC"
    reset_resolver_state

    # Cartridge with two dependencies
    make_manifest "ld-a" "1.0.0" "ld-b:>=1.0.0" "ld-c:^2.0.0"
    make_manifest "ld-b" "1.5.0"
    make_manifest "ld-c" "2.3.0"

    assert_success "load manifest with 2 deps" "__bashcmdr_load_dependencies ld-a"
    assert_success "BASHCMDR_DEPENDENCY_GRAPH is declared" \
        "declare -p BASHCMDR_DEPENDENCY_GRAPH &>/dev/null"
    assert_output_contains "dep graph for ld-a contains ld-b" \
        "_dep_graph ld-a" "ld-b"
    assert_output_contains "dep graph for ld-a contains ld-c" \
        "_dep_graph ld-a" "ld-c"
    assert_output_contains "constraint ld-a:ld-b stored" \
        "_constraint ld-a:ld-b" ">=1.0.0"
    assert_output_contains "constraint ld-a:ld-c stored" \
        "_constraint ld-a:ld-c" "^2.0.0"

    reset_resolver_state

    # Cartridge with no dependencies
    make_manifest "ld-nodeps" "3.0.0"
    assert_success "load manifest with no deps" "__bashcmdr_load_dependencies ld-nodeps"
    assert_success "dep graph entry is empty string for no-dep cartridge" \
        "_dep_graph_empty ld-nodeps"

    reset_resolver_state

    # Missing manifest
    assert_failure "missing manifest returns error" \
        "__bashcmdr_load_dependencies nonexistent-cart-xyz"
}

# ── Test: __bashcmdr_detect_cycles ────────────────────────────────────────────

test_cycle_detection() {
    printf '\n%b%s%b\n' "$BLUE" '=== Cycle Detection Tests ===' "$NC"

    # Linear chain: no cycle
    reset_resolver_state
    declare -gA BASHCMDR_DEPENDENCY_GRAPH
    BASHCMDR_DEPENDENCY_GRAPH["cy-a"]="cy-b"
    BASHCMDR_DEPENDENCY_GRAPH["cy-b"]="cy-c"
    BASHCMDR_DEPENDENCY_GRAPH["cy-c"]=""
    assert_success "linear chain A→B→C: no cycle" "__bashcmdr_detect_cycles cy-a"

    # Direct cycle: A → B → A
    reset_resolver_state
    declare -gA BASHCMDR_DEPENDENCY_GRAPH
    BASHCMDR_DEPENDENCY_GRAPH["cy-a"]="cy-b"
    BASHCMDR_DEPENDENCY_GRAPH["cy-b"]="cy-a"
    assert_failure "direct cycle A→B→A detected" "__bashcmdr_detect_cycles cy-a"

    # Self-loop: A → A
    reset_resolver_state
    declare -gA BASHCMDR_DEPENDENCY_GRAPH
    BASHCMDR_DEPENDENCY_GRAPH["cy-a"]="cy-a"
    assert_failure "self-loop A→A detected" "__bashcmdr_detect_cycles cy-a"

    # Single node, no deps
    reset_resolver_state
    declare -gA BASHCMDR_DEPENDENCY_GRAPH
    BASHCMDR_DEPENDENCY_GRAPH["cy-solo"]=""
    assert_success "single node: no cycle" "__bashcmdr_detect_cycles cy-solo"
}

# ── Test: __bashcmdr_topological_sort ────────────────────────────────────────

test_topological_sort() {
    printf '\n%b%s%b\n' "$BLUE" '=== Topological Sort Tests ===' "$NC"

    # Linear chain: ts-a depends on ts-b, ts-b depends on ts-c
    # Expected activation order: ts-c, ts-b, ts-a (deps first)
    reset_resolver_state
    declare -gA BASHCMDR_DEPENDENCY_GRAPH
    BASHCMDR_DEPENDENCY_GRAPH["ts-a"]="ts-b"
    BASHCMDR_DEPENDENCY_GRAPH["ts-b"]="ts-c"
    BASHCMDR_DEPENDENCY_GRAPH["ts-c"]=""
    assert_success "linear chain sorts without error" \
        "__bashcmdr_topological_sort ts-a ts-b ts-c"
    assert_equals "linear: ts-c activates first" \
        "${BASHCMDR_ACTIVATION_ORDER[0]:-}" "ts-c"
    assert_equals "linear: ts-b activates second" \
        "${BASHCMDR_ACTIVATION_ORDER[1]:-}" "ts-b"
    assert_equals "linear: ts-a activates last" \
        "${BASHCMDR_ACTIVATION_ORDER[2]:-}" "ts-a"

    # Diamond: ts-a → {ts-b, ts-c}, ts-b → ts-d, ts-c → ts-d
    # ts-d must be first; ts-a must be last; ts-b and ts-c are middle (order non-deterministic)
    reset_resolver_state
    declare -gA BASHCMDR_DEPENDENCY_GRAPH
    BASHCMDR_DEPENDENCY_GRAPH["ts-a"]="ts-b ts-c"
    BASHCMDR_DEPENDENCY_GRAPH["ts-b"]="ts-d"
    BASHCMDR_DEPENDENCY_GRAPH["ts-c"]="ts-d"
    BASHCMDR_DEPENDENCY_GRAPH["ts-d"]=""
    assert_success "diamond deps sort without error" \
        "__bashcmdr_topological_sort ts-a ts-b ts-c ts-d"
    assert_equals "diamond: ts-d activates first" \
        "${BASHCMDR_ACTIVATION_ORDER[0]:-}" "ts-d"
    assert_equals "diamond: ts-a activates last" \
        "${BASHCMDR_ACTIVATION_ORDER[3]:-}" "ts-a"
    assert_equals "diamond: 4 entries in result" \
        "${#BASHCMDR_ACTIVATION_ORDER[@]}" "4"

    # Single node
    reset_resolver_state
    declare -gA BASHCMDR_DEPENDENCY_GRAPH
    BASHCMDR_DEPENDENCY_GRAPH["ts-solo"]=""
    assert_success "single node sorts" "__bashcmdr_topological_sort ts-solo"
    assert_equals "single node is only entry" \
        "${BASHCMDR_ACTIVATION_ORDER[0]:-}" "ts-solo"

    # Cycle: Kahn's algorithm detects incomplete sort
    reset_resolver_state
    declare -gA BASHCMDR_DEPENDENCY_GRAPH
    BASHCMDR_DEPENDENCY_GRAPH["ts-a"]="ts-b"
    BASHCMDR_DEPENDENCY_GRAPH["ts-b"]="ts-a"
    assert_failure "cyclic graph fails topo sort" \
        "__bashcmdr_topological_sort ts-a ts-b"
}

# ── Test: __bashcmdr_validate_constraints ────────────────────────────────────

test_constraint_validation() {
    printf '\n%b%s%b\n' "$BLUE" '=== Constraint Validation Tests ===' "$NC"

    # Satisfied: vc-a requires vc-b@>=1.0.0; vc-b is 1.5.0
    reset_resolver_state
    make_manifest "vc-a" "1.0.0" "vc-b:>=1.0.0"
    make_manifest "vc-b" "1.5.0"
    declare -gA BASHCMDR_DEPENDENCY_CONSTRAINTS
    BASHCMDR_DEPENDENCY_CONSTRAINTS["vc-a:vc-b"]=">=1.0.0"
    assert_success "satisfied >= constraint passes" "__bashcmdr_validate_constraints vc-a"

    # Violated: vc-a requires vc-b@>=2.0.0 but vc-b is 1.5.0
    reset_resolver_state
    declare -gA BASHCMDR_DEPENDENCY_CONSTRAINTS
    BASHCMDR_DEPENDENCY_CONSTRAINTS["vc-a:vc-b"]=">=2.0.0"
    assert_failure "violated >= constraint fails" "__bashcmdr_validate_constraints vc-a"

    # Multiple constraints: all satisfied
    reset_resolver_state
    make_manifest "vc-c" "3.1.0"
    declare -gA BASHCMDR_DEPENDENCY_CONSTRAINTS
    BASHCMDR_DEPENDENCY_CONSTRAINTS["vc-a:vc-b"]=">=1.0.0"
    BASHCMDR_DEPENDENCY_CONSTRAINTS["vc-a:vc-c"]="^3.0.0"
    assert_success "multiple satisfied constraints pass" "__bashcmdr_validate_constraints vc-a"

    # Multiple constraints: one violated
    reset_resolver_state
    declare -gA BASHCMDR_DEPENDENCY_CONSTRAINTS
    BASHCMDR_DEPENDENCY_CONSTRAINTS["vc-a:vc-b"]=">=1.0.0"
    BASHCMDR_DEPENDENCY_CONSTRAINTS["vc-a:vc-c"]="^4.0.0"    # vc-c is 3.1.0 — violated
    assert_failure "one violated among multiple constraints fails" "__bashcmdr_validate_constraints vc-a"

    # Missing dependency manifest
    reset_resolver_state
    declare -gA BASHCMDR_DEPENDENCY_CONSTRAINTS
    BASHCMDR_DEPENDENCY_CONSTRAINTS["vc-a:missing-dep"]=">=1.0.0"
    assert_failure "missing dep manifest fails" "__bashcmdr_validate_constraints vc-a"
}

# ── Test: bashcmdr_resolve_dependencies (public) ──────────────────────────────

test_full_resolution() {
    printf '\n%b%s%b\n' "$BLUE" '=== Full Resolution Tests ===' "$NC"

    # Valid linear graph: fr-a → fr-b → fr-c
    reset_resolver_state
    make_manifest "fr-a" "1.0.0" "fr-b:>=1.0.0"
    make_manifest "fr-b" "2.0.0" "fr-c:>=1.0.0"
    make_manifest "fr-c" "1.5.0"
    assert_success "resolve 3-cartridge linear graph" \
        "bashcmdr_resolve_dependencies fr-a"
    assert_equals "activation order has 3 entries" \
        "${#BASHCMDR_ACTIVATION_ORDER[@]}" "3"
    assert_equals "fr-c activates first" \
        "${BASHCMDR_ACTIVATION_ORDER[0]:-}" "fr-c"
    assert_equals "fr-a activates last" \
        "${BASHCMDR_ACTIVATION_ORDER[2]:-}" "fr-a"

    # Cyclic graph
    reset_resolver_state
    make_manifest "cyc-a" "1.0.0" "cyc-b:>=1.0.0"
    make_manifest "cyc-b" "1.0.0" "cyc-a:>=1.0.0"
    assert_failure "cyclic graph resolution fails" \
        "bashcmdr_resolve_dependencies cyc-a"

    # Single cartridge, no deps
    reset_resolver_state
    make_manifest "fr-solo" "1.0.0"
    assert_success "single cartridge with no deps resolves" \
        "bashcmdr_resolve_dependencies fr-solo"
    assert_equals "single-entry activation order" \
        "${#BASHCMDR_ACTIVATION_ORDER[@]}" "1"
    assert_equals "single cartridge is fr-solo" \
        "${BASHCMDR_ACTIVATION_ORDER[0]:-}" "fr-solo"
}

# ── Test: bashcmdr_get_activation_plan (public) ───────────────────────────────

test_activation_plan() {
    printf '\n%b%s%b\n' "$BLUE" '=== Activation Plan Tests ===' "$NC"

    # Valid graph: ap-a → ap-b → ap-c
    reset_resolver_state
    make_manifest "ap-a" "1.0.0" "ap-b:>=1.0.0"
    make_manifest "ap-b" "1.5.0" "ap-c:>=1.0.0"
    make_manifest "ap-c" "2.0.0"

    assert_success "activation plan succeeds" \
        "bashcmdr_get_activation_plan ap-a"
    assert_output_contains "plan output includes ap-c" \
        "bashcmdr_get_activation_plan ap-a" "ap-c"
    assert_output_contains "plan output includes ap-b" \
        "bashcmdr_get_activation_plan ap-a" "ap-b"
    assert_output_contains "plan output includes ap-a" \
        "bashcmdr_get_activation_plan ap-a" "ap-a"

    # Failure case
    reset_resolver_state
    assert_failure "plan fails for nonexistent cartridge" \
        "bashcmdr_get_activation_plan nonexistent-cart-xyz"
}

# ── Test: Current-interpreter capability and resolver initialization checks ─────────────────────────

test_interpreter_capabilities() {
    printf '\n%b%s%b\n' "$BLUE" '=== Current Bash capability checks (no native-platform certification) ===' "$NC"

    # declare -p on a truly unset variable must return non-zero
    assert_failure "declare -p on unset var is non-zero" \
        "declare -p __bashcmdr_test_sentinel_xyz &>/dev/null"

    # declare -gA inside a function must be visible via declare -p in caller scope
    _test_gA_inside_fn() {
        declare -gA __bashcmdr_test_gA_array=()
    }
    _test_gA_inside_fn
    assert_success "declare -gA inside fn is visible via declare -p" \
        "declare -p __bashcmdr_test_gA_array &>/dev/null"
    unset __bashcmdr_test_gA_array
    unset -f _test_gA_inside_fn

    # __bashcmdr_load_dependencies creates arrays via declare -gA
    reset_resolver_state
    make_manifest "compat-a" "1.0.0"
    assert_success "load_dependencies creates BASHCMDR_DEPENDENCY_GRAPH via declare -gA" \
        "__bashcmdr_load_dependencies compat-a && declare -p BASHCMDR_DEPENDENCY_GRAPH &>/dev/null"
    assert_success "load_dependencies creates BASHCMDR_DEPENDENCY_CONSTRAINTS via declare -gA" \
        "declare -p BASHCMDR_DEPENDENCY_CONSTRAINTS &>/dev/null"

    # __bashcmdr_topological_sort creates activation order array via declare -ga
    reset_resolver_state
    declare -gA BASHCMDR_DEPENDENCY_GRAPH
    BASHCMDR_DEPENDENCY_GRAPH["compat-a"]=""
    assert_success "topological_sort creates BASHCMDR_ACTIVATION_ORDER via declare -ga" \
        "__bashcmdr_topological_sort compat-a && declare -p BASHCMDR_ACTIVATION_ORDER &>/dev/null"
}

# ── Main ──────────────────────────────────────────────────────────────────────

main() {
    printf '%b%s%b\n' "$YELLOW" 'bashcmdr Resolver Unit Test Suite' "$NC"
    printf "Repo root:  %s\n" "$BASHCMDR_REPO_ROOT"
    printf "Fixture dir: %s\n" "$TEST_TEMP_DIR"
    printf "bash version: %s\n" "$BASH_VERSION"
    echo

    test_parse_version_constraint
    test_version_compare
    test_load_dependencies
    test_cycle_detection
    test_topological_sort
    test_constraint_validation
    test_full_resolution
    test_activation_plan
    test_interpreter_capabilities

    echo
    printf '%b%s%b\n' "$YELLOW" '=== Test Summary ===' "$NC"
    printf "Total:  %d\n" "$TESTS_TOTAL"
    printf "${GREEN}Passed: %d${NC}\n" "$TESTS_PASSED"
    printf "${RED}Failed: %d${NC}\n" "$TESTS_FAILED"

    if (( TESTS_FAILED > 0 )); then
        echo
        printf '%b%s%b\n' "$RED" 'Failed tests:' "$NC"
        for t in "${FAILED_TESTS[@]}"; do
            printf "  - %s\n" "$t"
        done
        echo
        printf "Full test log: %s\n" "$TEST_LOG"
    fi

    exit $(( TESTS_FAILED > 0 ? 1 : 0 ))
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
