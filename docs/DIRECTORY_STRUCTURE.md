# Source layout and runtime-created state

This map describes the selected current tree. It distinguishes tracked source, runtime directories, user configuration, generated run artifacts and historical display fixtures. See [README.md](../README.md) for installation and [the cartridge contract](CARTRIDGE_CONTRACT.md) for source/return behavior.

## Tracked source inventory

### bin

- `bin/bashcmdr`
- `bin/bcm`

### boot

- `boot/completions.bash`
- `boot/shell-init.bashcmdr`

### lib

- `lib/core.bashcmdr`
- `lib/guards.bashcmdr`
- `lib/inspection.bashcmdr`
- `lib/interface.bashcmdr`
- `lib/path.bashcmdr`
- `lib/registry.bashcmdr`
- `lib/resolver.bashcmdr`
- `lib/root.bashcmdr`
- `lib/sourcing.bashcmdr`
- `lib/state.bashcmdr`

### scripts

- `scripts/bump-version.sh`

### docs

- `docs/CARTRIDGE_CONTRACT.md`
- `docs/CLI_GRAMMAR.md`
- `docs/DIRECTORY_STRUCTURE.md`

## Roles

bin/bashcmdr is the CLI entry; bin/bcm is its compatibility entry. boot/shell-init.bashcmdr selects/initializes an installation in the current shell and boot/completions.bash supplies completion. They do not install external runtimes or edit profiles. VERSION is the source version; scripts/bump-version.sh is developer tooling and does not decide a release.

lib/core provides shared configuration/logging and loads the implemented libraries; root selects installations, state handles physical links and quarantine, resolver handles declared dependency/version planning, inspection supplies nonactivating dependency views, interface manages scoped cartridge dispatch/state transitions, path manages Bash PATH helpers, sourcing manages named source helpers, guards validates cartridge activation, and registry reads the configured index. Only these shipped files are listed; old proposals for separate error/context/manifest compiler files are not a directory contract.

Cartridges are independent repositories installed into the selected root's cartridges/ directory. The source clone contains its .gitkeep placeholder, not bundled operational cartridges or an installed/ tree. Manifests/lifecycle code belong inside each installed cartridge.

## Runtime-created directories

The console creates console/active, console/inactive, console/quarantine and console/broken when needed. Their symlinks represent persistent state, not proof that an existing parent shell has loaded functions. A code-only clone need not ship those directories. Quarantine reason logs use logs/quarantine separately; legacy regular files are not silently adopted/deleted. Console logs and runtime links are ignored output, not source prerequisites.

User configuration and installed-source metadata live under the configured user configuration location; they are not a copied source subtree or proof of signature verification. Source-root selection and user configuration are distinct; use the README for the relevant environment variables.

## Test artifacts and historical material

The unit/resolver/path/install/factorial suites use an owned temporary installation and emit unique directories under tests/results/ or the explicitly configured result root. Current factorial results live under a unique factorial.* run directory; the runner does not overwrite tests/results/rapid_test_results.json. Inspect the printed actual run directory and full exit/output/cleanup records.

tests/results/rapid_test_results.json is a tracked historical display fixture with generalized command paths and provenance metadata. Its old observations/classifications are not current expectations or acceptance evidence. It remains tracked despite general ignore rules; new result files do not inherit that status. Tests/final_report.md and tests/mission_completion_report.md are historical summaries, as are INSTALL_REPORT.md and RESOLUTION_PLAN.md. Their exact earlier blobs remain in development Git; these presentation edits do not erase history.

README.md, CLI_GRAMMAR.md and CARTRIDGE_CONTRACT.md describe current interfaces. CLAUDE.md is a current working summary; TODO.md lists remaining work without turning plans into implemented features. CI fixtures under .test-inputs/ and compiler/tool test data are dependencies, not shipped cartridge/runtime state.

## Development entry points

Run bash tests/test_runner.bash, bash tests/test_resolver.bash, bash tests/test_path.bash and bash tests/test_install.bash for the ordinary owned shell suites. Factorial, semantic, analyzer, hook/provider and documentation suites are listed in the README. Pinned first-party inputs come from tests/first-party-inputs.json; their verification labels commit-and-content versus content-only exports honestly. Local fixture success does not certify hosted/native-platform support or a public release.

## Exact tracked path list

This inventory includes repository metadata, tests and historical fixtures, not ignored runtime outputs. The two new contract/documentation-test paths are part of this candidate.

```text
.gitignore
.shellcheckrc
CHANGELOG.md
CLAUDE.md
DEVELOPMENT_CREDITS.md
INSTALL_REPORT.md
LICENSE
NOTICE
README.md
RESOLUTION_PLAN.md
THIRD_PARTY_NOTICES.md
TODO.md
VERSION
bin/bashcmdr
bin/bcm
boot/completions.bash
boot/shell-init.bashcmdr
cartridges/.gitkeep
console/active/.gitkeep
console/quarantine/.gitkeep
docs/CARTRIDGE_CONTRACT.md
docs/CLI_GRAMMAR.md
docs/DIRECTORY_STRUCTURE.md
docs/SUPPORT.md
lib/core.bashcmdr
lib/guards.bashcmdr
lib/inspection.bashcmdr
lib/interface.bashcmdr
lib/path.bashcmdr
lib/registry.bashcmdr
lib/resolver.bashcmdr
lib/root.bashcmdr
lib/sourcing.bashcmdr
lib/state.bashcmdr
scripts/bump-version.sh
tests/analyzer.jq
tests/assertions.bash
tests/check-matrix.bash
tests/ci-first-party.json
tests/ci.bash
tests/ci_driver.py
tests/command_matrix_generator.bash
tests/factorial_test_runner.bash
tests/final_report.md
tests/first-party-inputs.json
tests/harness.bash
tests/matrix-catalog.jq
tests/mission_completion_report.md
tests/provider_inputs.py
tests/rapid-cases.json
tests/results/rapid_test_results.json
tests/test_activation_plan.py
tests/test_alias_help.py
tests/test_analyzer.bash
tests/test_analyzer_contracts.py
tests/test_boot_order.py
tests/test_boot_status.py
tests/test_cartridge_names.py
tests/test_cli_options.py
tests/test_completion_data.py
tests/test_dependency_inspection.py
tests/test_docs.py
tests/test_harness_isolation.py
tests/test_hook_context.py
tests/test_install.bash
tests/test_install_source_policy.py
tests/test_jq_inputs.py
tests/test_local_info.py
tests/test_matrix_generator.py
tests/test_path.bash
tests/test_path_edge_contracts.py
tests/test_plug_rollback.py
tests/test_provider_contracts.py
tests/test_quarantine_logs.py
tests/test_quarantine_policy.py
tests/test_reset.py
tests/test_resolver.bash
tests/test_root_selection.py
tests/test_runner.bash
tests/test_runtime_preflight.py
tests/test_semantic_gates.py
tests/test_shell_hygiene.py
tests/test_sourcing_contracts.py
tests/test_startup_footprint.py
tests/test_state_layout.py
tests/test_state_results.py
tests/test_tool_portability.py
tests/test_uninstall_deps.py
tests/test_version_comparison.py
```
