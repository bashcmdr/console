#!/usr/bin/env bash
# shellcheck disable=SC2030,SC2031  # PATH changes are deliberately subshell-local
# bashcmdr Path Library Conformance Tests
# Pins lib/path.bashcmdr to the interface of Stephen Collyer's original path
# functions (addpath delpath edpath listpath makepath uniqpath options Usage
# realpath_filter colon2line space2line).
#
# Run: bash tests/test_path.bash
#
# Intentional divergence from the originals: delpath without -e matches
# <dirspec> literally (the originals used an anchored regexp, so
# "delpath /a.b" also deleted "/axb").

set -euo pipefail

# The private child entry is issued only by harness.bash's clean environment.
if [[ ${1-} != --bcm-test-child ]]; then
    __bcm_suite_env=("PATH=$PATH")
    [[ ! ${TMPDIR+x} ]] || __bcm_suite_env+=("TMPDIR=$TMPDIR")
    [[ ! ${BASHCMDR_TEST_RESULTS_DIR+x} ]] || __bcm_suite_env+=("BASHCMDR_TEST_RESULTS_DIR=$BASHCMDR_TEST_RESULTS_DIR")
    __bcm_suite_file="${BASH_SOURCE[0]}"
    [[ "$__bcm_suite_file" == */* ]] || __bcm_suite_file="./$__bcm_suite_file"
    exec env -i "${__bcm_suite_env[@]}" "$BASH" --noprofile --norc "${__bcm_suite_file%/*}/harness.bash" path "$__bcm_suite_file" "$@"
fi
shift
: "${BCM_TEST_TEMP:?run through harness.bash}"

# ── Setup ────────────────────────────────────────────────────────────────────

TEST_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; readonly TEST_SCRIPT_DIR
BASHCMDR_REPO_ROOT="$(dirname "$TEST_SCRIPT_DIR")";                readonly BASHCMDR_REPO_ROOT
readonly TEST_TEMP_DIR="$BCM_TEST_TEMP"
readonly TEST_LOG="$BCM_TEST_ARTIFACTS/test_results.log"


echo "Test session started: $(date)" > "$TEST_LOG"

# shellcheck disable=SC1091
source "$BASHCMDR_REPO_ROOT/lib/path.bashcmdr"

# A Bash command fixture needs no platform-specific interpreter shebang.
bcm_fixture_editor() { printf '%s\n' /EDITED > "$1"; }
readonly FAKE_EDITOR=bcm_fixture_editor

# ── Test framework (pattern from tests/test_resolver.bash) ───────────────────

readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly NC='\033[0m'

declare -i TESTS_TOTAL=0
declare -i TESTS_PASSED=0
declare -i TESTS_FAILED=0
declare -a FAILED_TESTS=()

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

# run_on <initial X> <command...>
# Runs a path command against X in a subshell (so PATH and X never leak) and
# prints "<rc>|<X>|<PATH changed: yes/no>".
run_on() {
    local initial="$1"; shift
    (
        export X="$initial"
        local p0="$PATH" rc=0
        "$@" </dev/null >/dev/null 2>&1 || rc=$?
        local changed=no
        [[ "$PATH" == "$p0" ]] || changed=yes
        export PATH="$p0"
        printf '%s|%s|%s' "$rc" "$X" "$changed"
    )
}

# out_of <command...> — combined stdout+stderr of a command, in a subshell
out_of() {
    ( "$@" </dev/null 2>&1 ) || true
}

# has_usage <fn> — "yes" if "<fn> -h" prints its usage line
has_usage() {
    [[ "$(out_of "$1" -h)" == *"Usage: $1"* ]] && echo yes || echo no
}

# ── addpath ──────────────────────────────────────────────────────────────────

test_addpath() {
    printf '\n%b%s%b\n' "$YELLOW" addpath "$NC"
    assert_equals "addpath -p X /c appends"            "$(run_on /a:/b addpath -p X /c)"    "0|/a:/b:/c|no"
    assert_equals "addpath -f -p X /c prepends"        "$(run_on /a:/b addpath -f -p X /c)" "0|/c:/a:/b|no"
    assert_equals "addpath --front matches -f" \
        "$(run_on /a:/b addpath --front -p X /c)" "0|/c:/a:/b|no"
    assert_equals "addpath --front after -p X matches -f" \
        "$(run_on /a:/b addpath -p X --front /c)" "0|/c:/a:/b|no"
    assert_equals "addpath --front after attached -pX matches -f" \
        "$(run_on /a:/b addpath -pX --front /c)" "0|/c:/a:/b|no"
    assert_equals "addpath --front after clustered -bp X matches -f" \
        "$(run_on /a:/b addpath -bp X --front /c)" "0|/c:/a:/b|no"
    assert_equals "addpath -- preserves a literal --front directory" \
        "$(run_on /a:/b addpath -p X -- --front)" "0|/a:/b:--front|no"
    assert_equals "addpath preserves a --front -p operand in diagnostics" \
        "$(out_of addpath -p --front /c)" "invalid path variable name: --front"
    assert_equals "addpath -b -p X /c appends"         "$(run_on /a:/b addpath -b -p X /c)" "0|/a:/b:/c|no"
    assert_equals "addpath -p X /a is idempotent"      "$(run_on /a:/b addpath -p X /a)"    "0|/a:/b|no"
    assert_equals "addpath -p X /ab is prefix-safe"    "$(run_on /abc addpath -p X /ab)"    "0|/abc:/ab|no"
    assert_equals "addpath -p X on empty var"          "$(run_on '' addpath -p X /only)"    "0|/only|no"
    assert_equals "addpath keeps spaces and \$ literal" \
        "$(run_on '/a b' addpath -p X "/c\$HOME\"x")" "0|/a b:/c\$HOME\"x|no"
    assert_equals "addpath -p with no argument fails"  "$(run_on /a addpath -p)"            "1|/a|no"
    assert_equals "addpath with no dir fails"          "$(run_on /a addpath -p X)"          "1|/a|no"
    assert_equals "addpath rejects empty PATH operand without changing PATH" \
        "$(run_on /a addpath '')" "1|/a|no"
    assert_equals "addpath rejects an empty named-variable operand" \
        "$(run_on /a:/b addpath -p X '')" "1|/a:/b|no"
    assert_equals "addpath rejects empty input for an empty variable" \
        "$(run_on '' addpath -p X '')" "1||no"
    assert_equals "addpath rejects empty input when an empty element exists" \
        "$(run_on /a: addpath -p X '')" "1|/a:|no"
    assert_equals "addpath -z (unknown) fails"         "$(run_on /a addpath -z -p X /c)"    "1|/a|no"
    assert_equals "addpath rejects invalid var names"  "$(run_on /a addpath -p 'X;id' /c)"  "1|/a|no"
    assert_equals "addpath -h prints usage, rc 0"      "$(run_on /a addpath -h)"            "0|/a|no"
    assert_equals "addpath -h output is usage" "$(has_usage addpath)" "yes"

    local added
    added=$( unset NEWVAR; addpath -p NEWVAR /x; printf '%s' "$NEWVAR" )
    assert_equals "addpath -p NEWVAR creates the var"  "$added" "/x"
    added=$( unset NEWVAR; set -u; addpath -p NEWVAR /x; printf '%s' "$NEWVAR" )
    assert_equals "addpath works under set -u"         "$added" "/x"
    added=$( addpath -f /bcm-test-dir; printf '%s' "${PATH%%:*}" )
    assert_equals "addpath defaults to PATH"           "$added" "/bcm-test-dir"
}

# ── delpath ──────────────────────────────────────────────────────────────────

test_delpath() {
    printf '\n%b%s%b\n' "$YELLOW" delpath "$NC"
    assert_equals "delpath -p X /usr/bin is exact (regression)" \
        "$(run_on /usr/bin:/usr/bin/x:/opt/usr/bin delpath -p X /usr/bin)" "0|/usr/bin/x:/opt/usr/bin|no"
    assert_equals "delpath removes every exact copy" \
        "$(run_on /a:/b:/a delpath -p X /a)" "0|/b|no"
    assert_equals "delpath -p X /a.b matches literally" \
        "$(run_on /a.b:/axb delpath -p X /a.b)" "0|/axb|no"
    assert_equals "delpath -e -p X s.in (regex)" \
        "$(run_on /bin:/sbin:/usr/bin delpath -e -p X 's.in')" "0|/bin:/usr/bin|no"
    assert_equals "delpath -e -p X ^/opt (anchored regex)" \
        "$(run_on /opt/a:/usr/opt delpath -e -p X '^/opt')" "0|/usr/opt|no"
    assert_equals "delpath -n -p X drops nonexistent dirs" \
        "$(run_on "/:$TEST_TEMP_DIR/no/such/dir" delpath -n -p X)" "0|/|no"
    assert_equals "delpath -n with dirspec applies both" \
        "$(run_on "/:$TEST_TEMP_DIR:/nope" delpath -n -p X /)" "0|$TEST_TEMP_DIR|no"
    assert_equals "delpath -en combined flags" \
        "$(run_on "/bin:/sbin:/nope" delpath -en -p X 's.in')" "0|/bin|no"
    assert_equals "delpath of absent dir is a no-op" \
        "$(run_on /a:/b delpath -p X /c)" "0|/a:/b|no"
    assert_equals "delpath -p X does not touch PATH" \
        "$(run_on /a delpath -p X /usr/bin)" "0|/a|no"
    assert_equals "delpath with no dirspec fails" \
        "$(run_on /a delpath -p X)" "1|/a|no"
    assert_equals "delpath -p with no argument fails" \
        "$(run_on /a delpath -p)" "1|/a|no"
    assert_equals "delpath -z (unknown) fails" \
        "$(run_on /a delpath -z -p X /a)" "1|/a|no"
    assert_equals "delpath -h prints usage, rc 0" \
        "$(run_on /a delpath -h)" "0|/a|no"
    assert_equals "delpath -h output is usage" "$(has_usage delpath)" "yes"
}

# ── uniqpath / listpath / makepath / realpath_filter ─────────────────────────

test_uniq_list_make() {
    printf '\n%b%s%b\n' "$YELLOW" 'uniqpath / listpath / makepath / realpath_filter' "$NC"
    assert_equals "uniqpath -p X keeps first occurrence" \
        "$(run_on /a:/b:/a:/c:/b uniqpath -p X)" "0|/a:/b:/c|no"
    assert_equals "uniqpath drops empty elements" \
        "$(run_on /a::/b: uniqpath -p X)" "0|/a:/b|no"
    assert_equals "uniqpath -h prints usage, rc 0" \
        "$(run_on /a:/a uniqpath -h)" "0|/a:/a|no"

    assert_equals "listpath -p X one per line" \
        "$(X=/a:/b; listpath -p X | tr '\n' ',')" "/a,/b,"
    assert_equals "listpath -h output is usage" "$(has_usage listpath)" "yes"

    assert_equals "makepath from stdin"          "$(printf 'a\nb\n\nc\n' | makepath)" "a:b:c"
    assert_equals "makepath from arguments"      "$(makepath a b c)"                   "a:b:c"
    assert_equals "realpath_filter keeps dirs" \
        "$(printf '/\n/no/such/dir\n' | realpath_filter | tr '\n' ',')" "/,"
    assert_equals "colon2line" "$(echo a:b | colon2line | tr '\n' ',')" "a,b,"
    assert_equals "space2line" "$(echo 'a b' | space2line | tr '\n' ',')" "a,b,"
}

# ── options ──────────────────────────────────────────────────────────────────

test_options() {
    printf '\n%b%s%b\n' "$YELLOW" options "$NC"
    _opts_probe() {
        local opt_a opt_b opt_c options_shift_val options_missing_arg options_unknown_option options_num_args_left
        options "abc:" "$@"
        shift "$options_shift_val"
        printf '%s|%s|%s|%s|%s|%s|%s' "${opt_a:-}" "${opt_b:-}" "${opt_c:-}" \
            "$options_unknown_option" "$options_missing_arg" "$options_num_args_left" "$*"
    }
    assert_equals "options sets caller-local opt_* and shifts" \
        "$(_opts_probe -a -c fred bill pete)" "1||fred|||2|bill pete"
    assert_equals "options reports unknown option" \
        "$(_opts_probe -a -z x)" "1|||z||1|x"
    assert_equals "options reports missing argument" \
        "$(_opts_probe -c)" "||||c|0|"
    assert_equals "options does not leak opt_* globals" \
        "$(_opts_probe -a -b >/dev/null; echo "${opt_a-unset}${opt_b-unset}")" "unsetunset"
}

# ── edpath ───────────────────────────────────────────────────────────────────

test_edpath() {
    printf '\n%b%s%b\n' "$YELLOW" edpath "$NC"
    export EDITOR="$FAKE_EDITOR"
    assert_equals "edpath -p X edits X, not PATH (regression)" \
        "$(run_on /a:/b edpath -p X)" "0|/EDITED|no"
    assert_equals "edpath -p X saves OLDX" \
        "$(X=/a:/b; edpath -p X >/dev/null 2>&1; printf '%s' "$OLDX")" "/a:/b"
    assert_equals "edpath -h does not open the editor" \
        "$(run_on /a edpath -h)" "0|/a|no"
    assert_equals "edpath -h output is usage" "$(has_usage edpath)" "yes"
    assert_equals "edpath -z (unknown) does not open the editor" \
        "$(run_on /a edpath -z -p X)" "1|/a|no"
    assert_equals "edpath -p with no argument fails" \
        "$(run_on /a edpath -p)" "1|/a|no"
    assert_equals "edpath with extra arguments fails" \
        "$(run_on /a edpath -p X extra)" "1|/a|no"
    assert_equals "edpath leaves X unchanged if the editor fails" \
        "$(EDITOR=false run_on /a edpath -p X)" "1|/a|no"
    assert_equals "edpath without -p edits PATH" \
        "$( ( edpath >/dev/null 2>&1; printf '%s' "$PATH" ) )" "/EDITED"
}

main() {
    printf '%b%s%b\n' "$YELLOW" 'bashcmdr Path Library Conformance Suite' "$NC"
    printf "Repo root:  %s\n" "$BASHCMDR_REPO_ROOT"
    printf "bash version: %s\n" "$BASH_VERSION"

    test_addpath
    test_delpath
    test_uniq_list_make
    test_options
    test_edpath

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
