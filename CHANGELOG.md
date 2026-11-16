# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Fixed

- **`bcm cartridge install --from` never worked** — install looked the name up
  in the registry before honoring `--from` (and no registry index ships), then
  wrote to `installed/`, which activation, state and the resolver never read.
  `--from <git-url>` now skips the registry, takes the cartridge name from the
  repository's `manifest.json` (`bcm cartridge install --from <url>` needs no
  name), checks dependencies from that manifest, and installs the clone,
  `.git` included, into `cartridges/`. The `installed/` directory is retired.
  Covered by `tests/test_install.bash` (fresh `$HOME` → install → plug → new
  shell).

- **Cartridges never activated in a shell whose rc hook only sources
  `boot/shell-init.bashcmdr`** — the boot block read `BASHCMDR_ROOT_DIR`,
  which `__bashcmdr_boot_poweron` declares function-locally, so it sourced
  `/bin/bashcmdr` and skipped power-on. Existing hosts only worked because
  their `.bashrc` pre-sets that variable. Boot now uses
  `BASHCMDR_BOOT_ROOT_DIR`.

- **Path library data-loss bugs** (`lib/path.bashcmdr`) — `delpath DIR`
  deleted every entry *matching DIR as a regex* (e.g. `/usr/bin` also removed
  `/usr/bin/x` and `/opt/usr/bin`); it is now exact by default. `edpath -p VAR`
  edited `$PATH` instead of `VAR`, and `edpath -h` opened the editor, because
  `options()` used `declare -g`, which the caller's locals shadowed; `options()`
  now assigns in the caller's scope. Also adds Collyer's `addpath -b`,
  `delpath -e` (regex) and `-n` (drop nonexistent dirs), `-h` on every
  function, `-p` missing-argument errors, path-variable name validation (no
  more `eval` of caller input), and `set -u` safety. Behavior is pinned by the
  Collyer conformance suite `tests/test_path.bash`; the one intentional
  divergence is that `delpath` without `-e` matches literally.

- **Dependency resolver: topological sort was inverted** — Kahn's algorithm in
  `lib/resolver.bashcmdr` incremented `in_degree[dep]` instead of
  `in_degree[cartridge]`, causing dependents to activate before their
  dependencies. Fixed by correcting the in-degree counting direction and
  rewriting the processing loop to scan all cartridges for dependents of the
  current node rather than iterating the current node's own dependency list.
  Discovered during first real-world use of cartridge dependencies
  (`termux-env-openclaw` → `termux-env`).

- **Dependency resolver: `declare -gA` arrays not persisting across calls on
  bash 5.3/aarch64 (Termux/Android)** — `[[ -v ARRAY ]]` returns false for
  globally-declared associative arrays inside functions on this platform,
  causing the dependency graph to be re-initialized on every call and losing
  previously stored entries. Fixed by replacing all `[[ -v ]]` checks with
  `declare -p ARRAY &>/dev/null` and removing `local -n` nameref aliases in
  favor of direct global array access throughout `lib/resolver.bashcmdr`.
