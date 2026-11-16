#!/usr/bin/env bash
# bashcmdr Cartridge Install Integration Tests
# Fresh $HOME and console copy, no registry index:
#   bcm cartridge install --from <git-url> -> plug -> new shell has the functions
#
# Run: bash tests/test_install.bash
# (Uses local file:// fixture repositories; no network access required)

set -euo pipefail

# The private child entry is issued only by harness.bash's clean environment.
if [[ ${1-} != --bcm-test-child ]]; then
    __bcm_suite_env=("PATH=$PATH")
    [[ ! ${TMPDIR+x} ]] || __bcm_suite_env+=("TMPDIR=$TMPDIR")
    [[ ! ${BASHCMDR_TEST_RESULTS_DIR+x} ]] || __bcm_suite_env+=("BASHCMDR_TEST_RESULTS_DIR=$BASHCMDR_TEST_RESULTS_DIR")
    __bcm_suite_file="${BASH_SOURCE[0]}"
    [[ "$__bcm_suite_file" == */* ]] || __bcm_suite_file="./$__bcm_suite_file"
    exec env -i "${__bcm_suite_env[@]}" "$BASH" --noprofile --norc "${__bcm_suite_file%/*}/harness.bash" install "$__bcm_suite_file" "$@"
fi
shift
: "${BCM_TEST_TEMP:?run through harness.bash}"

# ── Setup ────────────────────────────────────────────────────────────────────

TEST_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; readonly TEST_SCRIPT_DIR
BASHCMDR_REPO_ROOT="$(dirname "$TEST_SCRIPT_DIR")";                readonly BASHCMDR_REPO_ROOT
readonly TEST_TEMP_DIR="$BCM_TEST_TEMP"
readonly TEST_LOG="$BCM_TEST_ARTIFACTS/test_results.log"


readonly FAKE_HOME="$HOME"
# shell-init.bashcmdr boots the console from $HOME/.local/bin/bashcmdr
readonly ROOT="$BCM_TEST_CONSOLE"
readonly REPOS="$TEST_TEMP_DIR/repos"

echo "Test session started: $(date)" > "$TEST_LOG"

# Isolated console copy with no cartridges or runtime state
mkdir -p "$ROOT" "$REPOS"
mkdir -p "$ROOT/cartridges" "$ROOT/config"

# ── Test framework (pattern from tests/test_resolver.bash) ───────────────────

readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly NC='\033[0m'

declare -i TESTS_TOTAL=0
declare -i TESTS_PASSED=0
declare -i TESTS_FAILED=0
declare -a FAILED_TESTS=()

_pass() {
    TESTS_PASSED+=1
    printf "${GREEN}✓${NC} %s\n" "$1"
    echo "PASS: $1" >> "$TEST_LOG"
}

_fail() {
    TESTS_FAILED+=1
    FAILED_TESTS+=("$1")
    printf "${RED}✗${NC} %s\n" "$1"
    printf 'FAIL: %s\n%s\n' "$1" "${2:-}" >> "$TEST_LOG"
}

assert_success() {
    local description="$1"; shift
    TESTS_TOTAL+=1
    local output
    if output=$("$@" 2>&1); then _pass "$description"; else _fail "$description" "$output"; fi
}

assert_failure() {
    local description="$1"; shift
    TESTS_TOTAL+=1
    local output
    if output=$("$@" 2>&1); then _fail "$description" "unexpected success: $output"; else _pass "$description"; fi
}

assert_output_contains() {
    local description="$1" expected="$2"; shift 2
    TESTS_TOTAL+=1
    local output
    output=$("$@" 2>&1) || true
    if [[ "$output" == *"$expected"* ]]; then _pass "$description"; else _fail "$description" "expected '$expected' in: $output"; fi
}

# ── Fixtures ─────────────────────────────────────────────────────────────────

# bcm <args...> — run the console CLI as a fresh user with no registry
bcm() {
    "$BCM_TEST_BASH" --noprofile --norc "$ROOT/bin/bashcmdr" "$@"
}

# new_shell <command> — run a command in a fresh interactive-style shell that
# boots the console the way ~/.bashrc does
new_shell() {
    # shellcheck disable=SC2016 # Positional arguments are expanded by the child Bash.
    "$BCM_TEST_BASH" --noprofile --norc -c 'source "$1/boot/shell-init.bashcmdr" >/dev/null 2>&1; eval "$2"' fixture "$ROOT" "$1"
}

# make_repo <dir> <manifest-name> [<required-cartridge>]
# Creates a git repository holding a minimal cartridge
make_repo() {
    local dir="$REPOS/$1" name="$2" requires="${3:-}"
    local fn="${name//[^A-Za-z0-9]/_}"
    mkdir -p "$dir"
    local requires_json='{"bashcmdr": ">=1.0.0"}'
    [[ -n "$requires" ]] && requires_json="{\"bashcmdr\": \">=1.0.0\", \"cartridges\": {\"$requires\": \">=1.0.0\"}}"
    cat > "$dir/manifest.json" <<EOF
{
  "name": "$name",
  "version": "1.0.0",
  "description": "Test fixture cartridge",
  "requires": $requires_json
}
EOF
    cat > "$dir/main.bashcmdr" <<EOF
#!/usr/bin/env bash
${fn}_hello() { echo "hello from $name"; }
cartridge_dispatch() { case "\${1:-help}" in activate|setup|deactivate|diagnose|help) return 0 ;; *) return 2 ;; esac; }
if [[ \${BASH_SOURCE[0]} == "\$0" ]]; then cartridge_dispatch "\$@"; fi
EOF
    git -C "$dir" init --quiet
    git -C "$dir" add -A
    git -C "$dir" -c user.name=test -c user.email=test@example.invalid commit --quiet -m fixture
}

make_repo demo-cart demo-cart
make_repo needs-dep needs-dep demo-cart
make_repo evil-name '../evil'
mkdir -p "$REPOS/no-manifest" && git -C "$REPOS/no-manifest" init --quiet &&
    touch "$REPOS/no-manifest/README" && git -C "$REPOS/no-manifest" add -A &&
    git -C "$REPOS/no-manifest" -c user.name=test -c user.email=test@example.invalid commit --quiet -m fixture

# ── Tests ────────────────────────────────────────────────────────────────────

test_fresh_layout() {
    assert_failure "fixture starts without any console state directory" test -e "$ROOT/console"
    assert_success "fresh CLI initializes its runtime layout" bcm version
    local state
    for state in active inactive broken quarantine; do
        assert_success "production created console/$state" test -d "$ROOT/console/$state"
    done
}

test_install_argument_errors() {
    printf '\n%b%s%b\n' "$YELLOW" 'Argument handling' "$NC"
    assert_failure "install with no arguments fails"         bcm cartridge install
    assert_failure "install --from without a URL fails"      bcm cartridge install --from
    assert_failure "install with an unknown option fails"    bcm cartridge install demo-cart --bogus
    assert_output_contains "registry miss suggests --from" "--from" \
        bcm cartridge install demo-cart
}

test_install_rejects_bad_repos() {
    printf '\n%b%s%b\n' "$YELLOW" 'Repository validation' "$NC"
    assert_failure "repo without manifest.json is rejected" \
        bcm cartridge install --from "file://$REPOS/no-manifest"
    assert_failure "manifest name '../evil' is rejected" \
        bcm cartridge install --from "file://$REPOS/evil-name"
    assert_failure "name that disagrees with manifest is rejected" \
        bcm cartridge install other-name --from "file://$REPOS/demo-cart"
    assert_failure "unreachable URL fails" \
        bcm cartridge install --from "file://$REPOS/does-not-exist"
    assert_success "nothing was installed by rejected attempts" \
        test -z "$(ls -A "$ROOT/cartridges")"
}

test_install_from_url() {
    printf '\n%b%s%b\n' "$YELLOW" 'install --from (no registry)' "$NC"
    assert_failure "dependent cartridge fails while its dependency is missing" \
        bcm cartridge install --from "file://$REPOS/needs-dep"
    assert_success "install --from <url> succeeds without a registry" \
        bcm cartridge install --from "file://$REPOS/demo-cart"
    assert_success "cartridge lands in cartridges/<manifest name>" \
        test -f "$ROOT/cartridges/demo-cart/manifest.json"
    assert_success "install keeps the git checkout" \
        test -d "$ROOT/cartridges/demo-cart/.git"
    assert_failure "no installed/ directory is created" \
        test -e "$ROOT/installed"
    assert_output_contains "metadata records cartridges/ location" '"cartridges/demo-cart"' \
        cat "$FAKE_HOME/.bashcmdr/registry/installed/demo-cart.json"
    assert_failure "reinstalling the same cartridge fails" \
        bcm cartridge install --from "file://$REPOS/demo-cart"
    assert_success "install <name> --from <url> with matching name succeeds" \
        bcm cartridge install needs-dep --from "file://$REPOS/needs-dep"
}

test_plug_and_new_shell() {
    printf '\n%b%s%b\n' "$YELLOW" 'plug -> new shell' "$NC"
    assert_success "plug installed cartridge" bcm cartridge plug demo-cart
    assert_success "plugged cartridge is in console/active" \
        test -L "$ROOT/console/active/demo-cart"
    assert_output_contains "new shell has the cartridge's functions" "hello from demo-cart" \
        new_shell "demo_cart_hello"
    assert_output_contains "cartridge list shows the installed cartridge" "demo-cart" \
        bcm cartridge list
}

test_uninstall() {
    printf '\n%b%s%b\n' "$YELLOW" uninstall "$NC"
    assert_success "uninstall removes the dependent cartridge" bcm cartridge uninstall needs-dep
    assert_failure "dependent's directory is gone" test -e "$ROOT/cartridges/needs-dep"
}

main() {
    printf '%b%s%b\n' "$YELLOW" 'bashcmdr Cartridge Install Integration Suite' "$NC"
    printf "Repo root:   %s\n" "$BASHCMDR_REPO_ROOT"
    printf "Fixture dir: %s\n" "$TEST_TEMP_DIR"

    test_fresh_layout
    test_install_argument_errors
    test_install_rejects_bad_repos
    test_install_from_url
    test_plug_and_new_shell
    test_uninstall

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
        printf "Full test log:\n"
        cat "$TEST_LOG"
    fi

    exit $(( TESTS_FAILED > 0 ? 1 : 0 ))
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
