#!/usr/bin/env bash
# Generate a portable command catalog, never execute its command data.
generate_matrix_catalog() (
    set -euo pipefail
    local script_dir output='' root='' entry name names_json work='' staged='' parent
    local explicit_names=0
    local -a names=(demo dependency)
    script_dir=$(CDPATH='' cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
    output="$script_dir/results/full_factorial_matrix.json"
    while (($#)); do
        case "$1" in
            -h|--help)
                printf '%s\n' 'Usage: bash command_matrix_generator.bash [--output FILE|-] [--cartridge NAME]... [--root DIR]'
                printf '%s\n' 'Default: portable demo/dependency fixture templates, output under tests/results/.'
                printf '%s\n' '--root adds ordinary cartridges/ names only; no commands or provider code run.'
                return 0 ;;
            --output|--root|--cartridge)
                if (($# < 2)) || [[ -z "$2" ]]; then printf '%s requires a nonempty value\n' "$1" >&2; return 1; fi
                case "$1" in
                    --output) output="$2" ;;
                    --root)
                        [[ -z "$root" ]] || { printf 'Specify --root once\n' >&2; return 1; }
                        root="$2" ;;
                    --cartridge)
                        if ((explicit_names == 0)); then names=(); explicit_names=1; fi
                        names+=("$2") ;;
                esac
                shift 2 ;;
            *) printf 'Unknown generator argument: %s\n' "$1" >&2; return 1 ;;
        esac
    done
    for name in jq mktemp; do
        command -v "$name" >/dev/null || { printf 'Matrix generation requires %s\n' "$name" >&2; return 1; }
    done
    set +f
    shopt -u failglob dotglob
    shopt -s nullglob
    if [[ -n "$root" ]]; then
        [[ -d "$root" ]] || { printf 'Discovery root is unavailable\n' >&2; return 1; }
        [[ ! -L "$root/cartridges" ]] || { printf 'Linked cartridge storage is not discovered\n' >&2; return 1; }
        for entry in "$root/cartridges"/*; do
            [[ -d "$entry" && ! -L "$entry" ]] || continue
            names+=("${entry##*/}")
        done
    fi
    local LC_ALL=C
    for name in "${names[@]}"; do
        [[ "$name" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || {
            printf 'Invalid cartridge template name: %q\n' "$name" >&2; return 1;
        }
    done
    # Invoked by traps, which ShellCheck cannot see inside this subshell function.
    # shellcheck disable=SC2317
    cleanup() {
        local status=$?
        trap - EXIT
        [[ -z "$staged" ]] || rm -f -- "$staged" || status=1
        [[ -z "$work" ]] || rm -rf -- "$work" || status=1
        exit "$status"
    }
    trap cleanup EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    work=$(mktemp -d -t bashcmdr-matrix.XXXXXXXX) || return 1
    names_json=$(printf '%s\0' "${names[@]}" | jq -Rs 'split("\u0000") | map(select(length > 0)) | unique') || return 1
    jq -n --argjson names "$names_json" -f "$script_dir/matrix-catalog.jq" > "$work/catalog.json" || return 1
    [[ -s "$work/catalog.json" ]] || { printf 'Generator produced no catalog\n' >&2; return 1; }
    jq -e '.metadata.schema == "bashcmdr.command-catalog.v2" and
        .metadata.total_combinations == (.test_matrix | length) and
        (.test_matrix | length) > 0 and .metadata.execution == "not_executed"' "$work/catalog.json" >/dev/null || return 1
    if [[ "$output" == - ]]; then cat -- "$work/catalog.json"; return; fi
    if [[ -L "$output" || ( -e "$output" && ! -f "$output" ) ]]; then
        printf 'Output must be a regular file or missing path\n' >&2; return 1
    fi
    parent=$(dirname -- "$output")
    mkdir -p -- "$parent" || return 1
    staged=$(mktemp "$parent/.bashcmdr-matrix.XXXXXXXX") || return 1
    cat -- "$work/catalog.json" > "$staged" || return 1
    mv -- "$staged" "$output" || return 1
    staged=''
    printf 'Command catalog saved to: %s\n' "$output" >&2
)

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then generate_matrix_catalog "$@"; fi
