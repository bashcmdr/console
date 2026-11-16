# Cartridge source, return and repeated-call contract

The console treats a cartridge as trusted Bash code plus manifest.json. This document describes the selected implementation; it is not a promise that arbitrary script effects can be rolled back. See [the console guide](../README.md) for root selection and startup.

## Standard dispatch boundary

For setup, activate, deactivate, diagnose and help, the interface verifies the cartridge/path, supplies path helpers, saves the caller's cartridge_dispatch binding, clears it, sources main.bashcmdr, requires that file to define its own dispatcher, calls the dispatcher with the action and remaining arguments, then restores the caller's dispatcher. A missing dispatcher cannot reuse an ambient one. Readonly dispatchers, source failure and restoration failure are errors. Nested calls use their own saved frame.

The __bashcmdr_cartridge_call boundary preserves the source/callback status when restoration succeeds. Outer commands can aggregate failure (for example plug returns1 for a failed activation). Print data intended for resolver consumers only on stdout; send diagnostics through the documented framework helpers/stderr as appropriate. A source file must define functions and avoid auto-dispatching a sourced positional action, because the interface dispatches separately.

Functions and global bindings created by a hook can remain in that process. The dispatcher is isolated; arbitrary other variables/functions/files are not. Shared associative context needed by later public helpers must have global lifetime, for example a deliberately named declare -gA table, rather than a declaration local to the source callback. Keep names cartridge-specific and handle existing/readonly caller bindings deliberately. A loaded marker inherited by a child does not prove that functions or PATH were initialized in that child.

## Minimal source-only cartridge

Save this JSON as manifest.json and the Bash block as main.bashcmdr in the same cartridge source directory. The example's state is intentionally small; it is an interface example, not certification of every failure/readonly/upstream-runtime case.

```json
{
  "name": "docs-demo",
  "version": "1.0.0",
  "requires": {"bashcmdr": ">=1.0.0", "cartridges": {}},
  "execution": {"mode": "SOURCE_ONLY", "guard_variable": "BASHCMDR_DOCS_DEMO_LOADED", "allow_reload": true}
}
```

```bash
docs_demo_activate() {
    if [[ ${BASHCMDR_DOCS_DEMO_LOADED-} == 1 ]] && declare -F docs_demo_hello >/dev/null; then
        return 0
    fi
    docs_demo_hello() { printf 'hello from docs-demo\n'; }
    export BASHCMDR_DOCS_DEMO_LOADED=1
}
docs_demo_deactivate() {
    unset BASHCMDR_DOCS_DEMO_LOADED
    unset -f docs_demo_hello
}
cartridge_dispatch() {
    local action=${1:-help}
    if (($#)); then shift; fi
    case $action in
        setup|help) printf 'docs-demo: setup activate deactivate diagnose help\n';;
        activate) docs_demo_activate;;
        deactivate) docs_demo_deactivate;;
        diagnose) return "${1:-0}";;
        *) return 2;;
    esac
}
if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
    cartridge_dispatch "$@"
fi
```

The framework sources before each standard call. Re-sourcing/repeated activation must preserve or revalidate owned state rather than erase its cleanup snapshot. Directly executing this file acts in a child process; sourcing it with an argument only defines functions. The hello function is available in the process that successfully activated it, and the deactivation helper removes only its own marker/function. The example checks both marker and function so an inherited marker alone cannot suppress repair.

## Activation, cleanup and state

Declared dependencies, valid names and quarantine policy are checked before activation code. Plug records the pre-state of each planned entry, activates in dependency order and rolls back newly activated entries in reverse order after later failure. A hook that fails activation owns cleanup of its own partial effects; it is not automatically deactivated as a successful hook. Rollback attempts remaining entries even when one cleanup fails and reports failure.

Deactivation must release only owned state and preserve later caller edits where the cartridge's contract promises that behavior. Trusted upstream initialization can have other effects. The framework does not snapshot every variable, function, file or external resource and cannot reverse readonly changes or arbitrary service/network actions. Concurrent external state changes require coordination.

Persistent active/inactive/quarantine/broken links live under the selected console root and differ from current-process loaded functions. An external plug/unplug/reset cannot update an existing parent shell. Startup sourcing applies the explicitly active set in that new/current process; check boot outcome rather than the initializer's deliberately nonfatal return status.

## Verification

Run python3 tests/test_hook_context.py for dispatcher restoration, source/callback statuses, repeat/source contexts and first-party fixtures. Run python3 tests/test_docs.py --first-party-root /path/to/selected/first-party-root to execute this exact example with owned fixtures. These are current commands; historical reports are not substitutes for their actual run artifacts.
