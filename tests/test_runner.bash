#!/usr/bin/env bash
# bashcmdr Unit Test Runner
# Comprehensive test suite for all bashcmdr commands and edge cases
# Updated for v1.1.0 noun-verb grammar: bcm [noun] <verb> [args] [flags]

set -euo pipefail

# The private child entry is issued only by harness.bash's clean environment.
if [[ ${1-} != --bcm-test-child ]]; then
    __bcm_suite_env=("PATH=$PATH")
    [[ ! ${TMPDIR+x} ]] || __bcm_suite_env+=("TMPDIR=$TMPDIR")
    [[ ! ${BASHCMDR_TEST_RESULTS_DIR+x} ]] || __bcm_suite_env+=("BASHCMDR_TEST_RESULTS_DIR=$BASHCMDR_TEST_RESULTS_DIR")
    __bcm_suite_file="${BASH_SOURCE[0]}"
    [[ "$__bcm_suite_file" == */* ]] || __bcm_suite_file="./$__bcm_suite_file"
    exec env -i "${__bcm_suite_env[@]}" "$BASH" --noprofile --norc "${__bcm_suite_file%/*}/harness.bash" unit "$__bcm_suite_file" "$@"
fi
shift
: "${BCM_TEST_TEMP:?run through harness.bash}"

# Test framework configuration
TEST_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly TEST_ROOT
readonly TEST_TEMP_DIR="$BCM_TEST_TEMP"
export TEST_TEMP_DIR
readonly TEST_LOG="$BCM_TEST_ARTIFACTS/test_results.log"
# shellcheck source=tests/assertions.bash
source "${BASH_SOURCE[0]%/*}/assertions.bash"
export TEST_BASHCMDR_ROOT="$BCM_TEST_CONSOLE"
printf -v BCM_COMMAND '%q' "$TEST_BASHCMDR_ROOT/bin/bashcmdr"
printf -v BCM_SHORT_COMMAND '%q' "$TEST_BASHCMDR_ROOT/bin/bcm"
readonly BCM_COMMAND BCM_SHORT_COMMAND

# Test counters
declare -i TESTS_TOTAL=0
declare -i TESTS_PASSED=0
declare -i TESTS_FAILED=0

# Test result tracking
declare -a FAILED_TESTS=()

# Colors for output
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly NC='\033[0m' # No Color

# Setup test environment
setup_test_env() {
    mkdir -p "$TEST_TEMP_DIR"
    echo "Test session started: $(date)" > "$TEST_LOG"

    # Code-only fixture supplied by the parent; runtime/user payloads are excluded.
    export BASHCMDR_QUIET_BOOT=1
    # shellcheck disable=SC2016 # The clean child expands its fixture root.
    "$BCM_TEST_BASH" --noprofile --norc -c '
        source "$BASHCMDR_ROOT/lib/state.bashcmdr"
        __bashcmdr_init_state
    '
    # Always exercise dependency assertions with an inert synthetic leaf.
    mkdir -p "$TEST_BASHCMDR_ROOT/cartridges/fixture-leaf"
    printf '%s\n' '{"name":"fixture-leaf","version":"1.0.0"}' > "$TEST_BASHCMDR_ROOT/cartridges/fixture-leaf/manifest.json"
    printf '%s\n' 'cartridge_dispatch() { return 0; }' > "$TEST_BASHCMDR_ROOT/cartridges/fixture-leaf/main.bashcmdr"
    mkdir -p "$HOME/.bashcmdr/registry"
    printf '%s\n' '{"version":"fixture","cartridges":{}}' > "$HOME/.bashcmdr/registry/index.json"

    # Read dynamic version
    TEST_VERSION="$(cat "$TEST_BASHCMDR_ROOT/VERSION" 2>/dev/null)" || TEST_VERSION="unknown"
    TEST_VERSION="${TEST_VERSION//[$'\r\n ']/}"
}

# Test assertion functions
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
    local expected_status="${4-0}"

    TESTS_TOTAL+=1

    local output
    local command_status=0
    output=$(eval "$command" 2>&1) || command_status=$?
    bcm_test_note_command "$command" "$command_status" "$output"

    if [[ -n "$expected_text" && "$command_status" == "$expected_status" && "$output" == *"$expected_text"* ]]; then
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
            echo "Expected exit: $expected_status; got: $command_status"
            echo "Got: $output"
        } >> "$TEST_LOG"
    fi
}

assert_silent_success() {
    local description="$1" command="$2" command_status=0 output_file
    TESTS_TOTAL+=1
    output_file="$BCM_TEST_ARTIFACTS/quiet-${TESTS_TOTAL}.output.log"
    eval "$command" > "$output_file" 2>&1 || command_status=$?
    bcm_test_note_command "$command" "$command_status" "$(cat -- "$output_file")"
    if [[ "$command_status" == 0 && ! -s "$output_file" ]]; then
        TESTS_PASSED+=1
        printf "${GREEN}✓${NC} %s\n" "$description"
        printf 'PASS: %s\n' "$description" >> "$TEST_LOG"
    else
        TESTS_FAILED+=1
        FAILED_TESTS+=("$description")
        printf "${RED}✗${NC} %s\n" "$description"
        printf 'FAIL: %s (expected exit 0 and zero output bytes; got exit %s)\nOutput file: %s\n' \
            "$description" "$command_status" "$output_file" >> "$TEST_LOG"
    fi
}

# ===== Test suites =====

test_basic_commands() {
    printf '%b%s%b\n' "$BLUE" '=== Basic Commands Tests ===' "$NC"

    assert_success "bashcmdr shows version" "$BCM_COMMAND version"
    assert_success "bcm symlink works" "$BCM_SHORT_COMMAND version"
    assert_output_contains "help shows usage" "$BCM_COMMAND help" "USAGE"
    assert_output_contains "version shows dynamic version" "$BCM_COMMAND version" "$TEST_VERSION"
}

test_console_commands() {
    printf '%b%s%b\n' "$BLUE" '=== Console Management Tests ===' "$NC"

    assert_success "console poweron works" "$BCM_COMMAND console poweron"
    assert_output_contains "console status shows info" "$BCM_COMMAND console status" "Console Status"
    assert_success "console poweroff works" "$BCM_COMMAND console poweroff"
}

test_cartridge_commands() {
    printf '%b%s%b\n' "$BLUE" '=== Cartridge Management Tests ===' "$NC"

    assert_output_contains "cartridge list shows cartridges" "$BCM_COMMAND cartridge list" "All Cartridges"
    assert_output_contains "cartridge list all works" "$BCM_COMMAND cartridge list all" "All Cartridges"
    assert_failure "cartridge list invalid filter fails" "$BCM_COMMAND cartridge list invalid"
}

test_help_cascading() {
    printf '%b%s%b\n' "$BLUE" '=== Help Cascading Tests ===' "$NC"

    # Top-level help
    assert_output_contains "help lists nouns" "$BCM_COMMAND help" "console"

    # Noun-level help
    assert_output_contains "help console lists verbs" "$BCM_COMMAND help console" "poweron"
    assert_output_contains "help cartridge lists verbs" "$BCM_COMMAND help cartridge" "install"
    assert_output_contains "help registry lists verbs" "$BCM_COMMAND help registry" "list"

    # Verb-level help
    assert_output_contains "help cartridge install shows usage" "$BCM_COMMAND help cartridge install" "install"

    # --help flag interception
    assert_output_contains "cartridge install --help works" "$BCM_COMMAND cartridge install --help" "install"
    assert_output_contains "console --help works" "$BCM_COMMAND console --help" "poweron"
}

test_help_flags() {
    printf '%b%s%b\n' "$BLUE" '=== Help Flag Tests ===' "$NC"

    assert_output_contains "cartridge plug --help shows usage" "$BCM_COMMAND cartridge plug --help" "plug"
    assert_output_contains "cartridge plug -h shows usage" "$BCM_COMMAND cartridge plug -h" "plug"
}

test_error_conditions() {
    printf '%b%s%b\n' "$BLUE" '=== Error Condition Tests ===' "$NC"

    assert_failure "cartridge plug without args fails" "$BCM_COMMAND cartridge plug"
    assert_failure "cartridge unplug without args fails" "$BCM_COMMAND cartridge unplug"
    assert_failure "unknown command fails" "$BCM_COMMAND nonexistent"
    assert_output_contains "cartridge plug nonexistent warns" "$BCM_COMMAND cartridge plug nonexistent" "not found" 1
}

test_noun_verb_dispatch() {
    printf '%b%s%b\n' "$BLUE" '=== Noun-Verb Dispatch Tests ===' "$NC"

    # Unknown nouns produce errors
    assert_failure "unknown noun fails" "$BCM_COMMAND foobar status"

    # Unknown verbs produce errors
    assert_failure "unknown console verb fails" "$BCM_COMMAND console foobar"
    assert_failure "unknown cartridge verb fails" "$BCM_COMMAND cartridge foobar"
    assert_failure "unknown registry verb fails" "$BCM_COMMAND registry foobar"
}

test_doctor_command() {
    printf '%b%s%b\n' "$BLUE" '=== Doctor Command Tests ===' "$NC"

    assert_output_contains "doctor shows health check" "$BCM_COMMAND doctor" "System Health Check"
    assert_output_contains "doctor shows version" "$BCM_COMMAND doctor" "Version:"
    assert_output_contains "doctor shows library checks" "$BCM_COMMAND doctor" "Libraries:"
}

test_registry_commands() {
    printf '%b%s%b\n' "$BLUE" '=== Registry Commands Tests ===' "$NC"

    # The fixture supplies a local empty index; list must actually succeed.
    assert_output_contains "registry list runs without crash" "$BCM_COMMAND registry list" "Registry"
    assert_success "registry status runs" "$BCM_COMMAND registry status"
}

test_dependency_resolution() {
    printf '%b%s%b\n' "$BLUE" '=== Dependency Resolution Tests ===' "$NC"

    assert_success "cartridge deps command works" "$BCM_COMMAND cartridge deps fixture-leaf"
    assert_success "cartridge plan command works" "$BCM_COMMAND cartridge plan fixture-leaf"

    assert_failure "cartridge deps without args fails" "$BCM_COMMAND cartridge deps"
    assert_failure "cartridge plan without args fails" "$BCM_COMMAND cartridge plan"
}

test_sourcing_functions() {
    printf '%b%s%b\n' "$BLUE" '=== BIOS Sourcing Functions Tests ===' "$NC"

    # Create test files for sourcing
    mkdir -p "$TEST_TEMP_DIR/source_tests"
    echo 'export TEST_VAR1="value1"' > "$TEST_TEMP_DIR/source_tests/test1.sh"
    echo 'export TEST_VAR2="value2"' > "$TEST_TEMP_DIR/source_tests/test2.sh"
    echo 'export TEST_VAR3="value3"' > "$TEST_TEMP_DIR/source_tests/test3.txt"
    echo 'invalid bash syntax {{{' > "$TEST_TEMP_DIR/source_tests/invalid.sh"

    # Test basic sourcing
    assert_success "bc.source basic functionality" "bash -c 'source \"\$TEST_BASHCMDR_ROOT/boot/shell-init.bashcmdr\"; bc.source \"\$TEST_TEMP_DIR/source_tests/test1.sh\"; [[ \$TEST_VAR1 == \"value1\" ]]'"

    # Test help functionality
    assert_output_contains "bc.source help works" "bash -c 'source \"\$TEST_BASHCMDR_ROOT/boot/shell-init.bashcmdr\"; bc.source --help'" "Usage: bc.source"
    assert_output_contains "bc.source-once help works" "bash -c 'source \"\$TEST_BASHCMDR_ROOT/boot/shell-init.bashcmdr\"; bc.source-once --help'" "Usage: bc.source-once"
    assert_output_contains "bc.source-dir help works" "bash -c 'source \"\$TEST_BASHCMDR_ROOT/boot/shell-init.bashcmdr\"; bc.source-dir --help'" "Usage: bc.source-dir"

    # Test re-sourcing protection
    assert_output_contains "bc.source-once prevents re-sourcing" "bash -c 'source \"\$TEST_BASHCMDR_ROOT/boot/shell-init.bashcmdr\"; bc.source-once \"\$TEST_TEMP_DIR/source_tests/test1.sh\"; bc.source-once \"\$TEST_TEMP_DIR/source_tests/test1.sh\"'" "already sourced"

    # Test directory sourcing - sh mode
    assert_success "bc.source-dir --sh mode works" "bash -c 'source \"\$TEST_BASHCMDR_ROOT/boot/shell-init.bashcmdr\"; bc.source-dir --sh \"\$TEST_TEMP_DIR/source_tests\"; [[ \$TEST_VAR1 == \"value1\" && \$TEST_VAR2 == \"value2\" && -z \$TEST_VAR3 ]]'"

    # Test directory sourcing - all mode
    assert_success "bc.source-dir --all mode works" "bash -c 'source \"\$TEST_BASHCMDR_ROOT/boot/shell-init.bashcmdr\"; bc.source-dir --all \"\$TEST_TEMP_DIR/source_tests\"; [[ \$TEST_VAR1 == \"value1\" && \$TEST_VAR2 == \"value2\" && \$TEST_VAR3 == \"value3\" ]]'"

    # Test error conditions
    assert_failure "bc.source-dir requires mode" "bash -c 'source \"\$TEST_BASHCMDR_ROOT/boot/shell-init.bashcmdr\"; bc.source-dir \"\$TEST_TEMP_DIR/source_tests\"'"
    assert_failure "bc.source handles missing files" "bash -c 'source \"\$TEST_BASHCMDR_ROOT/boot/shell-init.bashcmdr\"; bc.source \"\$TEST_TEMP_DIR/source_tests/missing.sh\"'"
    assert_failure "bc.source handles invalid syntax" "bash -c 'source \"\$TEST_BASHCMDR_ROOT/boot/shell-init.bashcmdr\"; bc.source \"\$TEST_TEMP_DIR/source_tests/invalid.sh\"'"

    # Test quiet mode
    assert_silent_success "bc.source --quiet suppresses messages" "bash -c 'source \"\$TEST_BASHCMDR_ROOT/boot/shell-init.bashcmdr\"; bc.source --quiet \"\$TEST_TEMP_DIR/source_tests/test1.sh\" 2>&1'"

    # Test BIOS validation
    assert_success "BIOS sourcing functions loaded" "bash -c 'source \"\$TEST_BASHCMDR_ROOT/boot/shell-init.bashcmdr\"; [[ \$BASHCMDR_SOURCING_FUNCTIONS_LOADED == \"1\" ]]'"
}

test_symlink_path_integrity() {
    printf '%b%s%b\n' "$BLUE" '=== Symlink Path Integrity Tests ===' "$NC"

    # Test broken symlink handling creates correct paths
    # Create a broken symlink in active directory
    mkdir -p "$TEST_TEMP_DIR/fake_cartridges"
    echo "fake cartridge" > "$TEST_TEMP_DIR/fake_cartridges/test-cartridge"
    ln -sf "../../fake_cartridges/test-cartridge" "$TEST_BASHCMDR_ROOT/console/active/test-cartridge"

    # Remove the target to make it broken
    rm -rf "$TEST_TEMP_DIR/fake_cartridges"

    # Run integrity check which should move broken symlink to broken/ with correct path
    assert_failure "integrity check reports detected broken symlinks" "$BCM_COMMAND doctor"

    # Verify orphaned symlink was removed (cartridge dir doesn't exist)
    assert_success "orphaned broken symlink was cleaned up" "[[ ! -L \"\$TEST_BASHCMDR_ROOT/console/active/test-cartridge\" ]]"
}

test_state_exclusivity() {
    printf '%b%s%b\n' "$BLUE" '=== State Exclusivity Tests ===' "$NC"

    # Create test cartridge
    mkdir -p "$TEST_BASHCMDR_ROOT/cartridges/test-exclusive"
    echo "test cartridge" > "$TEST_BASHCMDR_ROOT/cartridges/test-exclusive/main.bashcmdr"

    # Create violation by placing cartridge in multiple states
    ln -sf "../../cartridges/test-exclusive" "$TEST_BASHCMDR_ROOT/console/active/test-exclusive"
    ln -sf "../../cartridges/test-exclusive" "$TEST_BASHCMDR_ROOT/console/broken/test-exclusive"
    ln -sf "../../cartridges/test-exclusive" "$TEST_BASHCMDR_ROOT/console/inactive/test-exclusive"

    # Test automatic resolution (active should win by precedence)
    assert_failure "doctor reports detected state exclusivity violations" "$BCM_COMMAND doctor"
    assert_success "cartridge remains only in active after resolution" "[[ -L \"\$TEST_BASHCMDR_ROOT/console/active/test-exclusive\" ]] && [[ ! -L \"\$TEST_BASHCMDR_ROOT/console/broken/test-exclusive\" ]] && [[ ! -L \"\$TEST_BASHCMDR_ROOT/console/inactive/test-exclusive\" ]]"

    # Test state transition function (run in subshell to avoid set -e conflicts)
    assert_success "state transition function works" "bash -c 'source \"\$TEST_BASHCMDR_ROOT/lib/state.bashcmdr\"; __bashcmdr_set_cartridge_state test-exclusive inactive'"
    assert_success "cartridge moved to inactive state" "[[ -L \"\$TEST_BASHCMDR_ROOT/console/inactive/test-exclusive\" ]] && [[ ! -L \"\$TEST_BASHCMDR_ROOT/console/active/test-exclusive\" ]]"

    # Test that doctor resolves multi-state violations to a single state
    ln -sf "../../cartridges/test-exclusive" "$TEST_BASHCMDR_ROOT/console/quarantine/test-exclusive"
    ln -sf "../../cartridges/test-exclusive" "$TEST_BASHCMDR_ROOT/console/broken/test-exclusive"
    ln -sf "../../cartridges/test-exclusive" "$TEST_BASHCMDR_ROOT/console/inactive/test-exclusive"

    # After doctor, cartridge should be in exactly one state
    assert_failure "doctor reports detected multi-state issues" "$BCM_COMMAND doctor"
    local state_count=0
    for sd in active inactive quarantine broken; do
        [[ -L "$TEST_BASHCMDR_ROOT/console/$sd/test-exclusive" ]] && state_count=$((state_count + 1))
    done
    assert_success "doctor enforces single-state after multi-violation" "[[ $state_count -eq 1 ]]"

    # Cleanup
    rm -rf "$TEST_BASHCMDR_ROOT/cartridges/test-exclusive"
    for state_dir in active inactive broken quarantine; do
        rm -f "$TEST_BASHCMDR_ROOT/console/$state_dir/test-exclusive" 2>/dev/null
    done
}

# Main test execution
main() {
    printf '%b%s%b\n' "$YELLOW" 'bashcmdr Unit Test Suite' "$NC"
    printf "Test root: %s\n" "$TEST_ROOT"
    printf "bashcmdr root: %s\n" "$BASHCMDR_ROOT"
    echo

    setup_test_env

    # Run all test suites
    test_basic_commands
    test_console_commands
    test_cartridge_commands
    test_help_cascading
    test_help_flags
    test_error_conditions
    test_noun_verb_dispatch
    test_doctor_command
    test_registry_commands
    test_dependency_resolution
    test_sourcing_functions
    test_symlink_path_integrity
    test_state_exclusivity

    # Test summary
    echo
    printf '%b%s%b\n' "$YELLOW" '=== Test Summary ===' "$NC"
    printf "Total tests: %d\n" "$TESTS_TOTAL"
    printf "${GREEN}Passed: %d${NC}\n" "$TESTS_PASSED"
    printf "${RED}Failed: %d${NC}\n" "$TESTS_FAILED"

    if [[ $TESTS_FAILED -gt 0 ]]; then
        echo
        printf '%b%s%b\n' "$RED" 'Failed tests:' "$NC"
        for test in "${FAILED_TESTS[@]}"; do
            printf "  - %s\n" "$test"
        done

        echo
        printf "Full test log: %s\n" "$TEST_LOG"
    fi


    # Exit with error code if any tests failed
    exit $((TESTS_FAILED > 0 ? 1 : 0))
}

# Run tests if executed directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
