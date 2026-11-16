#!/usr/bin/env bash
# bashcmdr shell completion for Bash
# Auto-loaded by BIOS during shell startup (boot/shell-init.bashcmdr)
#
# Provides tab completion for:
#   bcm [noun] <verb> [arguments] [flags]
#   bashcmdr [noun] <verb> [arguments] [flags]

__bcm_completions() {
    local cur prev cword completion_quote='' completion_word_prefix=''
    local -a words=()
    COMPREPLY=()
    if declare -F _init_completion >/dev/null; then
        _init_completion || return 0
    else
        # Bash supplies this state even without the optional bash-completion package.
        [[ ${COMP_CWORD-} =~ ^[0-9]{1,9}$ ]] || return 0
        declare -p COMP_WORDS >/dev/null 2>&1 || return 0
        words=("${COMP_WORDS[@]}")
        cword=$((10#$COMP_CWORD))
        ((cword >= 1 && cword < ${#words[@]})) || return 0
        cur="${words[cword]}"
        prev="${words[cword-1]}"
    fi
    if [[ ${COMP_LINE+x} ]]; then
        # COMP_WORDS retains typed quoting. Remove only shell quoting, never
        # perform expansions or evaluate the unfinished command line.
        local raw="$cur" dequoted='' quote='' char next i
        for ((i=0; i<${#raw}; i++)); do
            char=${raw:i:1}
            case "$quote" in
                "'")
                    if [[ "$char" == "'" ]]; then quote=''; else dequoted+=$char; fi
                    ;;
                '"')
                    if [[ "$char" == '"' ]]; then
                        quote=''
                    elif [[ "$char" == "\\" ]]; then
                        next=${raw:i+1:1}
                        case "$next" in
                            '$'|'`'|'"'|\\) dequoted+=$next; i=$((i + 1)) ;;
                            $'\n') i=$((i + 1)) ;;
                            *) dequoted+=$char ;;
                        esac
                    else
                        dequoted+=$char
                    fi
                    ;;
                *)
                    case "$char" in
                        "'"|'"') completion_word_prefix=$dequoted; quote=$char ;;
                        \\) i=$((i + 1)); dequoted+=${raw:i:1} ;;
                        *) dequoted+=$char ;;
                    esac
                    ;;
            esac
        done
        cur=$dequoted
        completion_quote=$quote
    fi

    # Metadata is data, never a compgen -W program. NUL framing preserves
    # whitespace/newlines; Bash cannot represent NUL inside a candidate.
    __bcm_json_keys() {
        local file="$1" field="$2" values
        [[ -f "$file" ]] && command -v jq >/dev/null 2>&1 || return 0
        # Capture a complete successful document before presenting any names.
        values=$(jq -c -s --arg field "$field" '
            if length != 1 then [] else
                .[0] | if type != "object" then [] else
                    (if $field == "" then . else .[$field] end) |
                    if type != "object" then [] else
                        [keys[] | select(length > 0 and (contains("\u0000") | not))]
                    end
                end
            end' "$file" 2>/dev/null) || return 0
        jq -j '.[] | ., "\u0000"' <<< "$values" 2>/dev/null
    }

    __bcm_registry_index() {
        __bcm_json_keys "${BASHCMDR_REGISTRY_INDEX:-${HOME}/.bashcmdr/registry/index.json}" cartridges
    }

    __bcm_directory_names() (
        # Subshell scope keeps caller glob/IFS settings intact, including failglob.
        set +f
        unset GLOBIGNORE
        shopt -u failglob dotglob
        shopt -s nullglob
        local dir="$1" entry name
        [[ -d "$dir" ]] || return 0
        for entry in "$dir"/*/; do
            [[ -d "$entry" ]] || continue
            name=${entry%/}; name=${name##*/}
            printf '%s\0' "$name"
        done
    )

    __bcm_installed_cartridges() {
        __bcm_directory_names "${BASHCMDR_ROOT_DIR:-${HOME}/.local/bin/bashcmdr}/cartridges"
    }

    __bcm_active_cartridges() {
        __bcm_directory_names "${BASHCMDR_ROOT_DIR:-${HOME}/.local/bin/bashcmdr}/console/active"
    }

    __bcm_quarantined_cartridges() {
        __bcm_directory_names "${BASHCMDR_ROOT_DIR:-${HOME}/.local/bin/bashcmdr}/console/quarantine"
    }

    __bcm_all_cartridge_names() {
        # Preserve the sorted registry/installed union without GNU sort -z or
        # associative-array subscripts that can evaluate keys on older Bash.
        local item existing position
        local -a names=()
        while IFS= read -r -d '' item; do
            if ((${#names[@]} == 0)); then
                names=("$item")
                continue
            fi
            position=0
            for existing in "${names[@]}"; do
                [[ "$item" == "$existing" ]] && continue 2
                [[ "$item" < "$existing" ]] && break
                position=$((position + 1))
            done
            names=("${names[@]:0:position}" "$item" "${names[@]:position}")
        done < <(__bcm_registry_index; __bcm_installed_cartridges)
        ((${#names[@]} == 0)) || printf '%s\0' "${names[@]}"
        return 0
    }

    __bcm_alias_shortcuts() {
        __bcm_json_keys "${HOME}/.bashcmdr/aliases.json" ''
    }

    __bcm_offer() {
        local candidate quoted existing
        for candidate in "$@"; do
            [[ "$candidate" == "$cur"* ]] || continue
            # Readline replaces only the suffix after an open quote.
            if [[ -n "$completion_quote" ]]; then
                candidate=${candidate:${#completion_word_prefix}}
            fi
            # Readline inserts COMPREPLY as shell text. Quote for the current
            # context so pressing Enter cannot reinterpret metadata either.
            case "$completion_quote" in
                '"')
                    quoted=${candidate//\\/\\\\}
                    quoted=${quoted//\"/\\\"}
                    quoted=${quoted//\$/\\\$}
                    quoted=${quoted//\`/\\\`}
                    quoted+='"'
                    ;;
                "'") quoted=${candidate//\'/\'\\\'\'}; quoted+="'" ;;
                *) printf -v quoted '%q' "$candidate" ;;
            esac
            for existing in ${COMPREPLY[@]+"${COMPREPLY[@]}"}; do
                [[ "$quoted" == "$existing" ]] && continue 2
            done
            COMPREPLY+=("$quoted")
        done
        return 0
    }

    __bcm_offer_stream() {
        local item
        while IFS= read -r -d '' item; do
            __bcm_offer "$item"
        done
        return 0
    }

    # --- Resolve aliases so completion works after expansion ---

    # Normalize the argument array and cursor together after prefix expansion.
    # A two-word alias consumes one typed word, moving its argument cursor by one.
    local noun="" verb=""
    local alias_file="${HOME}/.bashcmdr/aliases.json" expansion=""
    if ((cword > 1)) && [[ -f "$alias_file" ]] && command -v jq >/dev/null 2>&1; then
        expansion=$(jq -r --arg shortcut "${words[1]:-}" '.[$shortcut] // empty' "$alias_file" 2>/dev/null) || expansion=''
    fi
    if [[ -n "$expansion" ]]; then
        local -a expanded=()
        read -ra expanded <<< "$expansion"
        if ((${#expanded[@]})); then
            words=("${words[0]}" "${expanded[@]}" "${words[@]:2}")
            cword=$((cword + ${#expanded[@]} - 1))
            prev="${words[cword-1]:-}"
        fi
    fi
    case "${words[1]:-}" in
        console|cartridge|registry)
            noun="${words[1]}"
            verb="${words[2]:-}" ;;
    esac

    # --- Position 1: top-level completions ---

    if [[ $cword -eq 1 ]]; then
        __bcm_offer console cartridge registry version help doctor alias
        __bcm_offer_stream < <(__bcm_alias_shortcuts)
        return
    fi

    # --- Firmware commands (no noun) ---

    case "${words[1]}" in
        help)
            # bcm help <noun> [verb]
            if [[ $cword -eq 2 ]]; then
                __bcm_offer console cartridge registry alias version doctor help
            elif [[ $cword -eq 3 ]]; then
                case "${words[2]}" in
                    console)
                        __bcm_offer poweron poweroff status shortcut reset upgrade uninstall log
                        ;;
                    cartridge)
                        __bcm_offer install uninstall upgrade plug unplug quarantine release show list search deps plan graph why diagnose
                        ;;
                    registry)
                        __bcm_offer sync list status
                        ;;
                    alias)
                        __bcm_offer list remove
                        ;;
                esac
            fi
            return
            ;;
        version|doctor)
            # No further arguments
            return
            ;;
        alias)
            if [[ $cword -eq 2 ]]; then
                __bcm_offer list remove
            elif [[ $cword -eq 3 && "${words[2]}" == "remove" ]]; then
                __bcm_offer_stream < <(__bcm_alias_shortcuts)
            fi
            return
            ;;
    esac

    # --- Noun dispatch ---

    # If noun wasn't set (e.g. user typed an alias), it was resolved above.
    # If still empty and we're past the firmware commands, nothing to complete.
    [[ -z "$noun" ]] && return

    case "$noun" in
        console)
            if [[ -z "$verb" || $cword -eq 2 ]]; then
                __bcm_offer poweron poweroff status shortcut reset upgrade uninstall log
            else
                # Flag completion per verb
                case "$verb" in
                    shortcut)
                        __bcm_offer --install --help
                        ;;
                    upgrade)
                        __bcm_offer --force
                        ;;
                    uninstall)
                        __bcm_offer --keep-config
                        ;;
                    log)
                        __bcm_offer --lines
                        ;;
                esac
            fi
            ;;

        cartridge)
            if [[ -z "$verb" || $cword -eq 2 ]]; then
                __bcm_offer install uninstall upgrade plug unplug quarantine release show list search deps plan graph why diagnose
            else
                # Argument/flag completion per verb
                case "$verb" in
                    # Verbs that take a cartridge name (all known)
                    install|show|deps|plan|graph)
                        if [[ "$prev" == "--from" ]]; then
                            # URL argument — no completion
                            return
                        fi
                        if [[ "$cur" == -* ]]; then
                            case "$verb" in
                                install) __bcm_offer --from --help ;;
                                *)       __bcm_offer --help ;;
                            esac
                        else
                            __bcm_offer_stream < <(__bcm_all_cartridge_names)
                        fi
                        ;;

                    # Verbs that take an installed cartridge name
                    uninstall|plug)
                        if [[ "$cur" == -* ]]; then
                            case "$verb" in
                                uninstall) __bcm_offer --purge --help ;;
                                *)         __bcm_offer --help ;;
                            esac
                        else
                            __bcm_offer_stream < <(__bcm_installed_cartridges)
                        fi
                        ;;

                    # Verbs that take an active cartridge name
                    unplug|why|diagnose)
                        if [[ "$cur" == -* ]]; then
                            __bcm_offer --help
                        else
                            __bcm_offer_stream < <(__bcm_active_cartridges)
                        fi
                        ;;

                    # Quarantine takes installed name
                    quarantine)
                        if [[ "$cur" == -* ]]; then
                            __bcm_offer --help
                        else
                            __bcm_offer_stream < <(__bcm_installed_cartridges)
                        fi
                        ;;

                    # Release takes quarantined name
                    release)
                        if [[ "$cur" == -* ]]; then
                            __bcm_offer --help
                        else
                            __bcm_offer_stream < <(__bcm_quarantined_cartridges)
                        fi
                        ;;

                    # Upgrade takes name or --all
                    upgrade)
                        if [[ "$cur" == -* ]]; then
                            __bcm_offer --all --help
                        else
                            __bcm_offer_stream < <(__bcm_installed_cartridges)
                        fi
                        ;;

                    # List takes a filter keyword
                    list)
                        __bcm_offer all active inactive quarantine broken outdated
                        ;;

                    # Search takes flags
                    search)
                        if [[ "$cur" == -* ]]; then
                            __bcm_offer --tag --author --installed --active --help
                        fi
                        ;;
                esac
            fi
            ;;

        registry)
            if [[ -z "$verb" || $cword -eq 2 ]]; then
                __bcm_offer sync list status
            fi
            ;;
    esac
}

if [[ $(type -t complete) == builtin ]]; then
    complete -F __bcm_completions bcm
    complete -F __bcm_completions bashcmdr
fi
