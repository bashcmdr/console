# Bash Commander working summary

This file describes the current development candidate; it is not a source of authority to publish, change licenses or alter user installations. Start with [README.md](README.md), [CLI grammar](docs/CLI_GRAMMAR.md), [directory map](docs/DIRECTORY_STRUCTURE.md) and the [cartridge contract](docs/CARTRIDGE_CONTRACT.md).

The console uses Bash4.3+, ordinary shell utilities, Git for installs and jq for JSON-backed operations. It does not supply a POSIX-shell tier or infer native OS support from Bash availability. Prefer environment-provided tools without sudo/package-manager assumptions. Cartridges are independent repositories and are installed with canonical `bashcmdr cartridge install <name> --from <trusted-git-source>` into the selected root's `cartridges/` directory.

Persistent active state and current-process initialization are different. BIOS sourcing checks the selected root and records boot outcome while keeping startup nonfatal. Hooks define a replaceable cartridge_dispatch; the interface sources then dispatches, restores the caller's dispatcher and preserves boundary status. Use owned fixtures for source/return/repeat, state/rollback and cross-repository contracts. Cartridges are trusted Bash code, not sandboxed declarative data.

The actual manifest is manifest.json. Implemented dependency/version behavior is documented in the README and executable resolver controls; old proposals for alternate manifest formats, replacement/conflict solvers, signing or compiled indexes are not implemented contracts. Registry synchronization and upgrade/uninstall stub routes remain explicitly identified in the command guide. Git source/commit records do not establish signature verification.

Runtime state directories are created when needed. Source code, runtime state, user configuration, tracked historical display fixtures and newly generated test results have different roles; see the directory map. Run the documented owned test entry points and retain actual failure/output artifacts. Old reports and project plans are historical context, not acceptance evidence.

Licensing, owner/privacy/history rulings, supported native targets and exact release/publication approval remain separate decisions. No domain purchase, external message, privileged host change, history rewrite or publication is implied by this working summary. The complete original planning text remains in development Git history; this current summary does not erase it.
