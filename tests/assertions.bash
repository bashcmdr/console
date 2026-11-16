#!/usr/bin/env bash
# Keep eval-based legacy assertions observable without changing their predicates.
bcm_test_note_command() {
    printf '\nCommand: %s\nExit: %s\nOutput:\n%s\n' "$1" "$2" "$3" >> "$TEST_LOG"
}

bcm_test_eval() {
    local command="$1" status=0
    printf '\nCommand: %s\nOutput:\n' "$command" >> "$TEST_LOG"
    # Bash 4.3 can exit inside eval despite the caller testing its status.
    # Put the conditional in the evaluated text, preserving parent mutations
    # and the actual result while retaining the caller's strict-mode options.
    eval "if {
:
$command
}; then
    status=0
else
    status=\$?
fi" >> "$TEST_LOG" 2>&1 || status=$?
    printf 'Exit: %s\n' "$status" >> "$TEST_LOG"
    return "$status"
}
