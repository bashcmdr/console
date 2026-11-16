#!/usr/bin/env bash
# bump-version.sh — SemVer version management for bashcmdr
#
# Usage:
#   ./scripts/bump-version.sh major    # X.Y.Z → X+1.0.0
#   ./scripts/bump-version.sh minor    # X.Y.Z → X.Y+1.0
#   ./scripts/bump-version.sh patch    # X.Y.Z → X.Y.Z+1
#   ./scripts/bump-version.sh show     # Print current version
#   ./scripts/bump-version.sh check    # Verify VERSION matches git tag
#
# Options:
#   --dry-run    Show what would happen without making changes
#   --no-tag     Bump and commit but don't create a git tag
#   --no-commit  Only update the VERSION file (no git operations)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION_FILE="${REPO_ROOT}/VERSION"

# Verify git is available
command -v git >/dev/null 2>&1 || { echo "Error: git is required but not found in PATH" >&2; exit 1; }

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

die()  { echo -e "${RED}Error:${RESET} $*" >&2; exit 1; }
info() { echo -e "${CYAN}→${RESET} $*"; }
ok()   { echo -e "${GREEN}✓${RESET} $*"; }
warn() { echo -e "${YELLOW}⚠${RESET} $*"; }

# --- Parse current version ---

read_version() {
    [[ -f "$VERSION_FILE" ]] || die "VERSION file not found: $VERSION_FILE"
    local ver
    ver="$(cat "$VERSION_FILE")"
    ver="${ver//[$'\r\n ']/}"
    echo "$ver"
}

parse_semver() {
    local ver="$1"
    if [[ ! "$ver" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+)$ ]]; then
        die "Invalid semver: $ver (expected MAJOR.MINOR.PATCH)"
    fi
    MAJOR="${BASH_REMATCH[1]}"
    MINOR="${BASH_REMATCH[2]}"
    PATCH="${BASH_REMATCH[3]}"
}

# --- Bump logic ---

bump_version() {
    local part="$1"
    case "$part" in
        major) MAJOR=$(( MAJOR + 1 )); MINOR=0; PATCH=0 ;;
        minor) MINOR=$(( MINOR + 1 )); PATCH=0 ;;
        patch) PATCH=$(( PATCH + 1 )) ;;
        *)     die "Invalid bump target: $part (use major, minor, or patch)" ;;
    esac
    echo "${MAJOR}.${MINOR}.${PATCH}"
}

# --- Check command ---

check_version() {
    local current
    current="$(read_version)"
    parse_semver "$current"

    info "VERSION file: ${BOLD}${current}${RESET}"

    # Check if tag exists
    if git rev-parse "v${current}" >/dev/null 2>&1; then
        local tag_commit head_commit
        tag_commit="$(git rev-list -n1 "v${current}")"
        head_commit="$(git rev-parse HEAD)"
        if [[ "$tag_commit" == "$head_commit" ]]; then
            ok "Tag v${current} exists and points to HEAD"
        else
            local ahead
            ahead="$(git rev-list "v${current}..HEAD" --count)"
            warn "Tag v${current} exists but HEAD is ${ahead} commit(s) ahead"
            warn "Consider bumping the version"
        fi
    else
        warn "No git tag v${current} found"
        warn "Create one with: git tag -a v${current} -m 'v${current}'"
    fi

    # Check for uncommitted changes (staged and unstaged)
    if ! git diff --quiet 2>/dev/null || ! git diff --cached --quiet 2>/dev/null; then
        warn "Working tree has uncommitted changes"
    fi

    return 0
}

# --- Main ---

main() {
    local action=""
    local dry_run=false
    local no_tag=false
    local no_commit=false

    # Parse arguments
    for arg in "$@"; do
        case "$arg" in
            major|minor|patch|show|check) action="$arg" ;;
            --dry-run)   dry_run=true ;;
            --no-tag)    no_tag=true ;;
            --no-commit) no_commit=true; no_tag=true ;;
            -h|--help)
                echo "Usage: $(basename "$0") {major|minor|patch|show|check} [--dry-run] [--no-tag] [--no-commit]"
                echo
                echo "Commands:"
                echo "  major      Bump major version (X.Y.Z → X+1.0.0)"
                echo "  minor      Bump minor version (X.Y.Z → X.Y+1.0)"
                echo "  patch      Bump patch version (X.Y.Z → X.Y.Z+1)"
                echo "  show       Print current version"
                echo "  check      Verify VERSION matches git state"
                echo
                echo "Options:"
                echo "  --dry-run    Show what would happen without changes"
                echo "  --no-tag     Bump and commit but skip git tag"
                echo "  --no-commit  Only update VERSION file"
                exit 0
                ;;
            *) die "Unknown argument: $arg" ;;
        esac
    done

    [[ -z "$action" ]] && die "No action specified. Use: major, minor, patch, show, or check"

    cd "$REPO_ROOT"

    local current
    current="$(read_version)"

    case "$action" in
        show)
            echo "$current"
            return 0
            ;;
        check)
            check_version
            return 0
            ;;
    esac

    # Bump
    parse_semver "$current"
    local new_version
    new_version="$(bump_version "$action")"

    # Pre-bump safety checks
    if ! $no_commit; then
        if ! git diff --cached --quiet 2>/dev/null; then
            die "Staging area has changes. Commit or stash them first."
        fi
    fi

    if ! $no_tag; then
        if git rev-parse "v${new_version}" >/dev/null 2>&1; then
            die "Tag v${new_version} already exists. Delete it first or choose a different bump."
        fi
    fi

    echo
    info "Current version: ${BOLD}${current}${RESET}"
    info "Bump type:       ${BOLD}${action}${RESET}"
    info "New version:     ${BOLD}${new_version}${RESET}"
    echo

    if $dry_run; then
        warn "Dry run — no changes made"
        echo
        echo "Would:"
        echo "  1. Write ${new_version} to VERSION"
        $no_commit || echo "  2. Commit: chore: Bump version to ${new_version}"
        $no_tag    || echo "  3. Tag: v${new_version}"
        return 0
    fi

    # Write VERSION file
    echo "$new_version" > "$VERSION_FILE"
    ok "Updated VERSION: ${current} → ${new_version}"

    if $no_commit; then
        warn "Skipping commit (--no-commit)"
        return 0
    fi

    # Commit
    git add "$VERSION_FILE"
    git commit -m "chore: Bump version to ${new_version}"
    ok "Committed version bump"

    if $no_tag; then
        warn "Skipping tag (--no-tag)"
        return 0
    fi

    # Tag
    git tag -a "v${new_version}" -m "v${new_version}"
    ok "Created tag: v${new_version}"

    echo
    local branch
    branch="$(git symbolic-ref --short HEAD 2>/dev/null || echo 'main')"
    ok "Version ${BOLD}${new_version}${RESET} is ready"
    info "Push with: git push origin ${branch} v${new_version}"
}

main "$@"
