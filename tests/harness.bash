#!/usr/bin/env bash
# Parent process for the five shell suites. The child receives an explicit
# environment and only code directories; caller runtime/configuration is excluded.
set -euo pipefail

suite="${1:?suite required}"
script="${2:?script required}"
shift 2
case "$suite" in unit|resolver|path|install|factorial) ;; *) exit 2 ;; esac
script_dir=$(CDPATH='' cd -P -- "$(dirname -- "$script")" && pwd -P)
source_root="${script_dir%/*}"
result_base="${BASHCMDR_TEST_RESULTS_DIR:-$source_root/tests/results}"
mkdir -p -- "$result_base"
result_base=$(CDPATH='' cd -P -- "$result_base" && pwd -P)
result_dir=$(mktemp -d "$result_base/$suite.XXXXXXXX")
temp_root=''

# shellcheck disable=SC2317 # Invoked by EXIT, INT and TERM trap handling.
cleanup() {
    local status=$?
    trap - EXIT
    if [[ -n "$temp_root" ]]; then
        if ! rm -rf -- "$temp_root" || [[ -e "$temp_root" ]]; then
            printf 'failed\n' > "$result_dir/cleanup.status"
            printf 'Cannot remove test fixture: %s\n' "$temp_root" >&2
            status=1
        else
            printf 'removed\n' > "$result_dir/cleanup.status"
        fi
    else
        printf 'not_created\n' > "$result_dir/cleanup.status"
    fi
    printf '%s\n' "$status" > "$result_dir/status.txt"
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Let mktemp choose its platform default when TMPDIR is unset. HOME/tmp is never
# a prerequisite; callers can select a platform-specific parent using TMPDIR.
temp_root=$(mktemp -d -t bashcmdr-test.XXXXXXXX)
temp_root=$(CDPATH='' cd -P -- "$temp_root" && pwd -P)
printf '%s\n' "$temp_root" > "$result_dir/temp-root.txt"
console="$temp_root/console"
if ! {
    mkdir -p -- "$console" "$temp_root/home" "$temp_root/tmp" "$temp_root/empty-hooks" &&
    cp -RP -- "$source_root/bin" "$source_root/boot" "$source_root/lib" "$source_root/VERSION" "$console/" &&
    mkdir -p -- "$console/config" "$console/cartridges"
} > "$result_dir/setup.log" 2>&1; then
    cat -- "$result_dir/setup.log" >&2
    exit 1
fi

# env -i drops inherited roots, registry/verbosity/guard variables, Git settings,
# exported functions and child-shell startup hooks. PATH selects the caller's
# toolchain; the known running Bash is first, without an FHS search-path guess.
test_path="${BASH%/*}:$PATH"
printf 'Test artifacts: %s\n' "$result_dir" >&2
status=0
env -i PATH="$test_path" HOME="$temp_root/home" TMPDIR="$temp_root/tmp" \
    XDG_CONFIG_HOME="$temp_root/home/.config" XDG_DATA_HOME="$temp_root/home/.local/share" \
    XDG_CACHE_HOME="$temp_root/home/.cache" LC_ALL=C TERM=dumb \
    GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null GIT_TERMINAL_PROMPT=0 \
    GIT_ALLOW_PROTOCOL=file GIT_CONFIG_COUNT=2 \
    GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0="$temp_root/empty-hooks" \
    GIT_CONFIG_KEY_1=commit.gpgsign GIT_CONFIG_VALUE_1=false \
    BASHCMDR_ROOT="$console" BASHCMDR_ROOT_DIR="$console" \
    BASHCMDR_QUIET_BOOT=1 \
    BCM_TEST_CONSOLE="$console" BCM_TEST_TEMP="$temp_root" \
    BCM_TEST_ARTIFACTS="$result_dir" BCM_TEST_BASH="$BASH" \
    "$BASH" --noprofile --norc "$script_dir/${script##*/}" --bcm-test-child "$@" \
    > "$result_dir/stdout.log" 2> "$result_dir/stderr.log" || status=$?
cat -- "$result_dir/stdout.log"
cat -- "$result_dir/stderr.log" >&2
exit "$status"
