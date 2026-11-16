> **Compatibility ancestor only.** This commit supplies Console runtime for cartridge development checks. It is not the accepted Console release. Full Console CI requires the final descendant with immutable cartridge inputs; missing inputs fail closed.

# Bash Commander (`bashcmdr`)

A lightweight, symlink-based cartridge management system for Bash. Organize scripts into installable, versioned, activatable cartridges with automatic dependency resolution.

**Status:** Preparing the first public prerelease as an official OAS FOSS
project. Support will cover only exact configurations and flows that pass final
release acceptance. Current private evidence covers the Linux baseline and a
historical Bash compatibility build; final acceptance and public availability are
still pending. See [prerelease support policy](docs/SUPPORT.md) for observed tools,
unverified platforms, required acceptance and unavailable features. Examples need
matching Console/cartridge revisions made available for review or publication;
a default-branch checkout may not yet contain them.

Use canonical `bashcmdr`; `bcm` is an optional shortcut when it resolves to the selected installation. The framework is Bash-centric: supply supported Bash and ordinary tools through the environment, without assuming a Linux distribution, package manager or `sudo`. Cartridge upstream runtimes have their own requirements.

### Runtime requirements

The current implementation needs **Bash 4.3 or newer**, including associative
arrays, `mapfile` and namerefs. The CLI checks this before loading its libraries
and returns 12 with an explicit diagnostic on older Bash. BIOS sourcing keeps
shell startup nonfatal, returning 0 while recording both boot outcome variables
as 12. This feature threshold does not itself certify a native platform.

`jq` is required for JSON-backed cartridge, dependency, registry and saved-alias
operations; Git is required for cartridge installation. Prerequisite checks run
before those commands create runtime state, fetch code or run hooks. Supply the
tools through your environment's normal installation method and PATH; the
framework does not invoke privilege escalation to install them.

Help, version display and empty or wholly quarantined boot remain useful without
jq or Git. Local state listing/status and provider diagnostics do not globally
require Git. `doctor` checks both jq and Git before repairs and returns 1 without
repairing state if either is missing. Ordinary missing-tool diagnostics follow
the existing verbosity setting; failure status remains nonzero at level 0.
Actual JSON reads check producer status before publishing dependency data, and
failed inspection blocks dependent removal/deactivation decisions.

Bash's optional `bash-completion` package is not required. When `_init_completion`
is absent, completion uses Bash's own word/cursor state. Static verbs and installed
names remain available; saved shortcuts and registry names need jq and are quietly
omitted when it is unavailable or their JSON query fails. A Bash build without
programmable completion skips registration without breaking startup.

### Numeric dependency versions

Dependency comparisons accept one to three dot-separated decimal components,
each from 0 through 999999999. Leading zeros are invalid except for the single
digit `0`; missing minor/patch components compare as zero (`1` equals `1.0.0`).
Whitespace, suffixes, prerelease/build metadata and extra components are rejected
before arithmetic. This is a numeric contract, not full SemVer support.

Manifest constraints accept a bare version (equality), `=`, `==`, `>`, `>=`, `<`,
`<=`, `~` or `^` followed immediately by a valid numeric version. `~1.2` means
at least 1.2.0 with the same major/minor; `^1.2` means at least 1.2.0 with the
same major. The existing caret rule also applies to major zero (`^0.2` admits
0.9.0); it does not implement SemVer's special zero-major ranges. The direct
comparison helper additionally accepts `!=`; manifest constraints do not.
Malformed versions/constraints fail plans and prevent activation rather than
being treated as a successful match. Boot uses the same numeric limits.

### Path helper arguments and editors

Omitting `-p` selects `PATH`; an explicit empty `-p ''` is an invalid variable
name and leaves `PATH` unchanged. Generic option values retain explicit empty
strings. `delpath -e` returns 2 for an invalid extended regular expression before
changing or exporting the selected variable, including when it is empty or
unset. A valid pattern with no match remains successful.

Path values use colon delimiters. A colon in an add operand introduces additional
elements; it does not encode one filesystem name containing a colon. Empty add
operands fail without changing the value. Existing `delpath`/`uniqpath` behavior
on an unset named variable creates an exported empty value; these calls do not
leave it unset.

`edpath` accepts a single editor executable/path, including spaces, or an editor
command with arguments such as `EDITOR='code --wait'`. Quotes and backslashes
group words, so `EDITOR='"/path with spaces/editor" --wait'` also works. An exact
executable name/path takes precedence over word parsing. Variable expansion,
command substitution, shell operators and glob expansion are not evaluated;
use an editor wrapper script when those behaviors are needed. An empty or unset
`EDITOR` keeps the `vi` default.

The selected variable and its `OLD<name>` binding must be writable scalar
strings. Invalid editor words, missing executables and incompatible bindings
fail before temporary-file creation. The editor, input listing, reconstruction
and temporary-file removal must succeed before edited values are published.
Handled input/editor/formatting/cleanup failures leave the selected value and
previous-value binding unchanged. An inability to remove the temporary file
returns failure and identifies the retained file. Arbitrary side effects of a
trusted editor function or executable are outside this contract.

### Sourcing helper operands

BIOS keeps the selected root and runtime maps for the lifetime of the firmware
functions it loads. Boot-only error/power-on/report wrappers are removed after
initialization. The `bc.source*`, path helpers, `console_reset` and
`bashcmdr_require_cartridge` remain usable in that shell; the latter reads the
selected installation's state markers and rejects ambiguous state. Use the executable CLI or a fresh shell when
you need changes made by another process reflected in your environment.

Other firmware functions and variables are implementation or compatibility
namespaces, rather than standalone public APIs. This includes `main`,
`help_cmd`, `console_*`, `bashcmdr_*`, `__bashcmdr_*`, `BASHCMDR_*`,
`__BASHCMDR_*`, `__sf_*` and `__SF_*`. Generic `Usage`/`options` and legacy
`__bashcmdr_add_to_path`/`__bashcmdr_discover_cartridge_root` remain for
compatibility. Loading firmware can define these names in the caller shell;
there is no promise of a function-count limit or complete namespace teardown.
Prefer the documented commands/helpers over direct internal function calls.

Core configuration is evaluated once for the established root during a source
chain, including nested core loads. Re-sourcing core for that same selection
retains its initialization status; it does not repeat a failed configuration.
Files added or edited afterward require a fresh shell to load. Direct core
loading with a changed root selection initializes that selection separately;
BIOS continues to keep its original installation and boot outcome. Configuration
is trusted Bash code, and its arbitrary side effects are not rolled back.
The source-once guard also survives re-importing the sourcing helper library.

`bc.source` and `bc.source-once` require at least one file operand;
`bc.source-dir --sh|--all` requires at least one path operand after selecting
its mode. A missing operand returns usage status 2, including after flags or
`--`; help remains successful without operands. Missing, nonregular,
unreadable or failed source files return status 1. Quiet mode suppresses helper
messages while preserving failure status.

A literal `~/` prefix in a quoted argument or a value read from configuration
expands to `$HOME`, including paths with spaces. Other tilde forms and embedded
tildes remain literal; path data is not evaluated as shell code. Sourcing runs
trusted script contents in the caller shell. `--sh` selects direct regular
`*.sh` files and `--all` selects direct regular files in sorted order; an empty
directory succeeds without sourcing anything.

Permission tests create an owned mode-000 file and first verify that both Bash
and the test process cannot read it. If the current identity bypasses those
permissions, that case is explicitly skipped and cannot certify unreadability.
The source library already rejects unreadable files; these controls verify that
behavior alongside distinct missing-file and syntax-failure paths.

### Cartridge source and provenance

Installation uses the selected repository's default HEAD. It records the source
operand and exact cloned commit in installed metadata under `source.repository`
and `source.commit`; a failed or malformed commit read stops installation before
the package is moved. The metadata records the effective `source.allowed_protocols`
for that clone; source-only helper calls omit the protocol field when unspecified.
Existing metadata-only helper calls omit source provenance when none is supplied.

Git clone receives an explicit option boundary and a per-invocation transport
allowlist: `https`, `http`, `ssh`, `git` and `file`, including local paths and
scp-style SSH sources. This ceiling is intersected with an inherited
`GIT_ALLOW_PROTOCOL`, preserving caller restrictions; an empty intersection stops
before clone or temporary state creation. It constrains configured URL rewrites
too. Custom remote-helper protocols,
including `ext`, are excluded. Leading-dash and control-character source operands
are rejected; prefix a local leading-dash name with `./`.

The operator chooses trusted repositories. Activation sources cartridge Bash
code in the current shell. Recording a commit and selecting transports does not
verify signatures, checksums or publisher identity, or sandbox Git configuration,
checkout filters, SSH or cartridge execution. HTTP and Git transports themselves
provide no encrypted connection. Revision selection and signature/checksum
verification remain unavailable; later installs may select a different default
HEAD. Installation reports metadata-write failure even when the package has
already been moved, so inspect that reported partial outcome before retrying.

### Tool metadata and report timing

Registry status tries GNU/BusyBox-style `stat -c %Y` and BSD-style `stat -f %m`
for index modification time. It accepts canonical nonnegative decimal epochs
up to twelve digits before arithmetic. Unsupported/failed/malformed stat or
`date +%s` output, or a future modification time, yields an explicit unavailable
age while retaining the other registry fields. No operating-system guess is used.
BIOS POST errors report their root, executable and outcome without needing date.

The rapid test runner measures elapsed time with Bash `SECONDS` and records
`duration_clock: "bash_SECONDS"` and `duration_resolution_seconds: 1`. Durations
are integer seconds, so short commands can correctly measure zero. Report
timestamps use checked `date -u +%Y-%m-%dT%H:%M:%SZ`; an unavailable or malformed
timestamp stops report generation explicitly. GNU nanosecond/ISO date options
and bc are unnecessary. Analyzer percentages use jq, with zero for empty totals;
the deterministic command catalog needs neither date nor bc.

The analyzer takes an explicit current-format results file:

```bash
bash tests/test_analyzer.bash /path/to/rapid_test_results.json
bash tests/test_analyzer.bash --output-dir "$HOME/test-analysis" /path/to/rapid_test_results.json
```

Use `rapid_test_results.json` from the runner's reported results directory.
The analyzer validates one `bashcmdr.rapid-results.v1` document, structured argv,
metadata counts and consistent exit/expectation/classification records before
displaying statistics. Categories use argv noun/verb tokens. Coverage lists
observed argv requests and their outcomes; expected negative cases count as
matched expectations and remain separate from mismatches/errors.

Each invocation writes `analysis.json`, `summary.txt`, `failure_analysis.txt`
and `coverage_report.txt` in a unique `analysis.*` directory. The default is
under ignored `tests/results/`; `--output-dir` selects another report root.
Input/query failures stop before reports are created, and write failures identify
the incomplete directory. Direct report helpers check complete producers and
stage writes before replacing ordinary files. Result fields remain data; analysis
does not rerun commands or establish the authenticity of supplied results.

---

## Install the console

Supply Bash 4.3+, Git and `jq` before this flow; the filesystem must support the directory/symlink operations used by the console. Use a new destination. For an existing console, select its existing root rather than cloning over it. This acquisition step does not install external runtimes or edit shell profiles.

```bash
git clone https://github.com/bashcmdr/console.git "$HOME/.local/bin/bashcmdr"
export BASHCMDR_ROOT_DIR="$HOME/.local/bin/bashcmdr"
export PATH="$BASHCMDR_ROOT_DIR/bin:$PATH"
bashcmdr version
bashcmdr help
```

To initialize this installation in the current shell, start a fresh Bash process and run:

```bash
export BASHCMDR_ROOT_DIR="$HOME/.local/bin/bashcmdr"
export PATH="$BASHCMDR_ROOT_DIR/bin:$PATH"
source "$BASHCMDR_ROOT_DIR/boot/shell-init.bashcmdr"
printf 'Bash Commander boot status: %s\n' "$BASHCMDR_BOOT_EXIT_CODE"
bashcmdr console status
```

Boot status must be `0` before continuing. Sourcing the initializer is nonfatal, so its return status alone does not establish boot success. Initialization runs once per shell; use a fresh shell after correcting startup or changing roots. Empty active state is a valid boot and supplies no cartridge-specific functions. Make persistent profile changes yourself only after checking this path.

## Install a first-party cartridge

Use the already-selected root/PATH from the console flow. BIOS makes its selected-root binding readonly; do not reassign it in that initialized shell. To select another installation, start a fresh shell first.

This example uses the [Go cartridge](https://github.com/bashcmdr/cartridge-go). It integrates an existing Go bootstrap; it installs no Go toolchain. A missing Go bootstrap leaves it dormant. Choose trusted sources: activating a cartridge sources its Bash code, and source/commit metadata is provenance rather than signature verification.

```bash
bashcmdr cartridge install go-loader --from https://github.com/bashcmdr/cartridge-go.git
bashcmdr cartridge plug go-loader
bashcmdr cartridge list active
```

External `plug` changes persistent state and its own process. It cannot change its parent shell's PATH or functions. Start a fresh Bash process before this current-shell check:

```bash
export BASHCMDR_ROOT_DIR="$HOME/.local/bin/bashcmdr"
export PATH="$BASHCMDR_ROOT_DIR/bin:$PATH"
source "$BASHCMDR_ROOT_DIR/boot/shell-init.bashcmdr"
printf 'Bash Commander boot status: %s\n' "$BASHCMDR_BOOT_EXIT_CODE"
go_diagnose
```

A successful boot with Go available sets `BASHCMDR_GO_LOADED=1`; a dormant cartridge does not. An already-available executable `go` or an active state link alone does not establish current-shell activation. Other selected guides cover [NVM](https://github.com/bashcmdr/cartridge-nvm), [Pyenv](https://github.com/bashcmdr/cartridge-pyenv) and [Fabric](https://github.com/bashcmdr/cartridge-fabric). Their external runtimes must be available separately. The matching NVM/Fabric candidates have no unrelated Pyenv cartridge prerequisite; a general dependency graph still requires every dependency actually declared by a selected manifest.

Use an explicit Git source on a fresh installation. Name-only installation needs a usable local registry index; remote registry synchronization is not implemented and is not a remedy for a missing index.

## Inspect and get help

Run these commands in the selected/initialized shell from the earlier flow; no root reassignment is needed.

```bash
bashcmdr help cartridge install
bashcmdr cartridge show go-loader
bashcmdr cartridge diagnose go-loader
bashcmdr console log --lines 50
```

Inspection reports selected installed data and the command's own process. Logs and manifests are not proof that trusted initializer code has no other effects; review logs before sharing them. See the implementation limits below for recognized commands that remain stubs.

---

## Project Layout

```
bashcmdr-console/
├── bin/           Console firmware (bashcmdr CLI)
├── boot/          BIOS bootstrap and shell completion
├── lib/           Shared libraries (core, resolver, registry, etc.)
├── cartridges/    Cartridge install target (empty in repo; populated at runtime)
├── console/       Runtime-created state (not required in a source clone)
├── scripts/       Developer tooling (bump-version.sh)
├── tests/         Test suite
├── docs/          Developer documentation
└── VERSION        SemVer single source of truth
```

For a detailed explanation of the directory structure, see [**DIRECTORY_STRUCTURE.md**](docs/DIRECTORY_STRUCTURE.md).

---

## Core Concepts

### Cartridges
A cartridge is a self-contained Bash module with:
- **Main script** (`main.bashcmdr`) - entry point defining lifecycle hooks
- **Manifest** (`manifest.json`) - metadata, version, dependencies
- **Functions** - available in the shell/process where activation runs; child inheritance requires the cartridge to export them explicitly

Cartridges live in their own repos under the `bashcmdr` GitHub org. They are never embedded in the console repo. Users install them via `bcm cartridge install`.

### States
Each cartridge can be in one of four states:
- **Active** (`✓`) - selected for activation by a framework call/startup; this persistent state alone says nothing about an already-running parent shell
- **Inactive** (`○`) - installed but not activated
- **Quarantine** (`⚠`) - installed but disabled (troubleshooting)
- **Broken** (`✗`) - symlink corruption detected

### Dependencies
Cartridges declare requirements in `manifest.json`:
- Other cartridges must be installed first
- `bcm cartridge plug` resolves and activates the full dependency tree
- Cycles are detected and rejected

Activation requires `jq` and readable manifests for the target and its declared
cartridge dependencies. Dependency inspection fails before cartridge code loads
when metadata cannot be read. Boot loads only explicitly active cartridges,
including Pyenv, NVM, and Fabric; installing an essential does not activate it.
Quarantine blocks activation of both the cartridge and targets that depend on it.
Use `bcm cartridge release <name>` before plugging it again. Unplug, reset, doctor,
and rollback preserve quarantine. Doctor repairs a bad quarantine link in place
and retains an orphaned quarantine marker while the cartridge is missing.
Quarantine takes precedence over active, broken, and inactive markers during
state repair and status reporting. Explicit release can also clear an orphaned
marker for a cartridge that is no longer installed.

---

## CLI Grammar

Every command follows one pattern:

```
bcm [noun] <verb> [arguments] [flags]
```

| Noun | Domain |
|------|--------|
| *(none)* | Firmware-level commands |
| `console` | Console runtime management |
| `cartridge` | Cartridge lifecycle |
| `registry` | Cartridge registry |

For implemented routes, prerequisites and stub results, see [**CLI_GRAMMAR.md**](docs/CLI_GRAMMAR.md).

---

## Command Reference

### Firmware Commands (no noun)

| Command | Purpose |
|---------|---------|
| `bcm version` | Show version |
| `bcm help [noun] [verb]` | Contextual help |
| `bcm doctor` | Inspect/repair selected installation state; found issues return failure even when repaired |
| `bcm alias <shortcut> <cmd>` | Create command shortcut |
| `bcm alias list` | List all aliases |
| `bcm alias remove <shortcut>` | Remove an alias |

### Console Commands

| Command | Purpose |
|---------|---------|
| `bcm console poweron` | Initialize the explicitly active cartridge set |
| `bcm console poweroff` | Deactivate all cartridges |
| `bcm console status` | Show console state |
| `bashcmdr console shortcut [--install]` | Inspect or explicitly create the bcm shortcut |
| `bcm console reset` | Restart hook context while retaining activation choices |
| `bcm console log [--lines <n>]` | View operation log |

### Cartridge Commands

| Command | Purpose |
|---------|---------|
| `bcm cartridge install <name> [--from <url>]` | Install into `cartridges/`; name-only lookup needs a usable registry index |
| `bcm cartridge install --from <url>` | Install from Git; no registry lookup |
| `bcm cartridge uninstall <name> [--purge]` | Remove a cartridge |
| `bcm cartridge plug <name>` | Mark active and run hooks in this process with declared dependencies |
| `bcm cartridge unplug <name>` | Run deactivation in this process and update persistent state |
| `bcm cartridge quarantine <name> [reason]` | Disable for troubleshooting |
| `bcm cartridge release <name>` | Release from quarantine |
| `bcm cartridge list [filter]` | List cartridges (all/active/inactive/quarantine/broken) |
| `bcm cartridge search [keyword] [flags]` | Search by keyword, tag, or author |
| `bcm cartridge show <name>` | Detailed cartridge info |
| `bcm cartridge deps <name>` | Show dependencies |
| `bcm cartridge plan <name>` | Show activation order |
| `bcm cartridge graph <name>` | Visualize dependency tree |
| `bcm cartridge why <name>` | Explain why a cartridge is needed |
| `bcm cartridge diagnose <name>` | Run cartridge self-check |

### Registry Commands

| Command | Purpose |
|---------|---------|
| `bcm registry list` | List registry cartridges |
| `bcm registry status` | Show registry state |

---

## Help System

Help cascades by specificity:

```bash
bcm help                          # List nouns and firmware commands
bcm help console                  # List console verbs
bcm help cartridge                # List cartridge verbs
bcm help cartridge install        # Detailed usage for cartridge install

# Any command also accepts --help / -h:
bcm cartridge install --help      # Same as bcm help cartridge install
bashcmdr cartridge install go-loader --from https://github.com/bashcmdr/cartridge-go.git --help  # Help without installing
bcm doctor --help                 # Help without checking or repairing state
```

Help runs before runtime-directory creation and state repair, including help
reached through a saved shortcut. A `-h` or `--help` argument token is reserved
for help; it does not run the requested operation. Recognized topics and verbs
return 0 with usage text; unknown topics/verbs return 1. Firmware topics include
`version`, `doctor`, `alias` and `help`. Detailed help for Phase 1 stubs states
that their operations are unimplemented and return 1; requesting their help
still returns 0. This does not make arbitrary cartridge lifecycle help a
framework CLI command.

---

## Alias System

Create shortcuts for frequently used commands:

```bash
bcm alias ci 'cartridge install'
bcm alias cs 'cartridge show'

# Now these are equivalent:
bashcmdr cartridge install go-loader --from https://github.com/bashcmdr/cartridge-go.git
bcm ci go-loader --from https://github.com/bashcmdr/cartridge-go.git
```

Aliases persist in `~/.bashcmdr/aliases.json`. They cannot shadow built-in nouns or firmware commands.
`bcm alias remove NAME` returns 1 without rewriting the store when NAME is absent
or the store is invalid; successful removal retains all other entries. Bash
completion resolves shortcut prefixes and adjusts the argument position, so
`bcm cs <Tab>` offers cartridge names just like `bcm cartridge show <Tab>`.

---

## Configuration

### Environment Variables

**Set by bashcmdr automatically:**
- `BASHCMDR_ROOT_DIR` - Root directory of bashcmdr installation
- `BASHCMDR_CONSOLE_EXE` - Console executable in that installation
- `BASHCMDR_VERSION` - Current version (read from VERSION file)

**Optional overrides:**
```bash
export BASHCMDR_QUIET_BOOT=1      # Suppress poweron messages
export BASHCMDR_FORCE_BCM_ALIAS=1 # Force bcm alias creation
```

By default, boot preserves an existing shell `bcm` alias, command or function.
The selected installation's own `bin/bcm` executable needs no extra alias and
produces no conflict advice. Set `BASHCMDR_FORCE_BCM_ALIAS=1` before boot to
explicitly create `bcm='bashcmdr'` in that shell, shadowing an existing binding.
This changes shell command lookup only; it does not delete functions, overwrite
executables or install a shortcut file. Other force values leave the default
preservation policy in effect. Use `bcm console shortcut --install` for the
separate missing-only shortcut installation operation.

### Selecting an installation

Without an override, both the CLI and `boot/shell-init.bashcmdr` discover the installation containing their actual entry file. External executable links and relative symlink chains resolve to that installation; a symlinked entry requires `readlink`, without GNU-specific `-f` behavior. Ordinary entries do not need `readlink` for root discovery.

To select a different complete installation, set `BASHCMDR_ROOT_DIR` before loading Bash Commander. The selected installation supplies BIOS, firmware, libraries, version and cartridge data together:

```bash
export BASHCMDR_ROOT_DIR="$HOME/tools/bashcmdr"
source "$BASHCMDR_ROOT_DIR/boot/shell-init.bashcmdr"
```

Legacy `BASHCMDR_BOOT_ROOT_DIR` and `BASHCMDR_BOOT_CONSOLE_EXE` overrides must agree with the selected root. Conflicting paths, specialized variable types and readonly empty paths are rejected. Matching readonly root/executable values, including aliases of the same physical files, are accepted. BIOS promotes the validated canonical root and executable to global readonly bindings without adding export attributes; preexisting exports remain exported. Standalone CLI discovery keeps its normal exported root behavior.

BIOS initialization runs once per shell, including failed attempts. Re-sourcing keeps that installation and outcome; start a fresh shell after correcting failed initialization or when switching installations. Shell startup remains nonfatal: sourcing the BIOS returns 0, while `BASHCMDR_BOOT_BASIC_EXIT_CODE` records POST and `BASHCMDR_BOOT_EXIT_CODE` records the subsequent console result. Inspect those variables and diagnostics rather than using the source command's status as proof of boot success. Root/override validation failures use code 12, an unavailable executable uses 10, and failed library/firmware loading uses 11. Missing selected installations never fall back silently to a different copy. Boot dependency behavior is described below; per-cartridge result accounting has separate release checks.

These checks cover owned fixtures on Linux Bash; they do not certify a native platform matrix. No privilege escalation or system installation prefix is needed for root discovery.

### Boot dependency ordering

Boot runs only explicitly active, nonquarantined cartridges. Every declared cartridge dependency must also be active and eligible. Use an explicit `bcm cartridge plug NAME` when you intend to activate an inactive dependency; boot does not change persistent activation state to satisfy a dependency automatically. Quarantine takes precedence over an overlapping active marker.

Before sourcing any cartridge, boot validates the complete active graph, manifests, versions, constraints and main scripts. A missing/ineligible dependency, cycle or invalid plan stops cartridge activation for that boot, including otherwise independent cartridges. `console_poweron` returns failure for a planning error and records details in `logs/console-poweron.log`; BIOS still keeps shell startup nonfatal. Correct the configuration and initialize in a fresh shell. An empty active set needs no dependency queries.

Successful plans put dependencies before dependents and activate a shared dependency once. The historical Pyenv/NVM/Fabric preference applies to independent ready nodes; it cannot place a dependent before a generic dependency. Boot currently accepts numeric versions with one to three decimal components, no leading zeroes except `0`, and components up to `999999999`. Supported constraint operators are `=`, `==`, `>`, `>=`, `<`, `<=`, `~`, and `^`, or an omitted operator. Other forms, including prerelease/range expressions, produce a planning error.

If a hook fails after planning, its dependents are blocked while independent cartridges may continue. A declared loaded marker that remains unset or differs from `1` identifies a dormant hook; a dormant dependency also blocks its dependents. A completed hook without a declared marker remains eligible as a dependency, with its result labeled `succeeded` rather than claiming it is loaded. State is checked again before each hook, so an earlier hook cannot make a later cartridge inactive or quarantined and still have it sourced by this plan. Arbitrary trusted hook effects are not rolled back, and boot does not undo already successful independent hooks.

### Boot results and output

`console_poweron` returns nonzero for failed/blocked hooks, invalid plans, invalid configuration, path-setup failures and detected logging failures. BIOS still returns 0 from its source command to keep shell startup nonfatal; `BASHCMDR_BOOT_EXIT_CODE` records the console outcome. This also holds when the caller uses `set -e`. A dormant cartridge by itself is not a boot failure. Initialization and results are observations of the current shell, not proof that an external service is healthy.

The latest `console_poweron` call publishes two associative arrays:

- `BASHCMDR_BOOT_RESULTS[NAME]` is `loaded`, `dormant`, `succeeded`, `failed`, `blocked`, `quarantined`, or `not_attempted`.
- `BASHCMDR_BOOT_SUMMARY` contains counts under those keys, plus `selected`, `status` (`ok` or `failed`), failure flags `planning_failed`, `configuration_failed`, `setup_failed`, `log_failed`, and the log path under `log` when logging was initialized.

`loaded` means the manifest's optional `execution.guard_variable` is observed as `1` after a successful hook. This is the provider's declared marker, not independent verification. `dormant` means that declared marker is unset or has another value after a successful hook. Without a marker, a successful hook is `succeeded`. Failed return status takes precedence over a set marker. Markers must be scalar variables with ordinary Bash identifiers; names beginning with `__` are reserved for framework internals. Array/nameref markers and invalid metadata fail visibly. Ordinary custom marker names and nonexported/readonly scalar markers are supported.

Counts exclude path setup and do not interpret persistent active links as successful loading. Quarantined markers are recorded once, including overlapping active markers; late state changes can block a planned cartridge. A planning error leaves enumerated eligible targets `not_attempted`. An error before target enumeration is represented by its failure flag, without inventing per-cartridge outcomes. Repeated direct console calls reset these maps; the BIOS exit variables retain their once-per-shell initialization result. Do not overwrite or lock framework bookkeeping.

Successful noninteractive BIOS sourcing emits no framework banner. Interactive BIOS summaries and explicit `console_poweron` summaries use stderr; failure summaries remain observable on stderr when enabled. Source/activation hook stdout and stderr, along with alias advice, are retained in `logs/console-poweron.log` rather than mixed with pipeline data. Explicit cartridge `plug` output is unchanged. User configuration files and arbitrary trusted shell code retain their own output/effect responsibilities.

`BASHCMDR_VERBOSITY` accepts exactly `0`, `1`, `2`, or `3`, defaulting to `1` when unset. Level 0 suppresses framework logger/summary messages; level 1 gives a concise outcome, and levels 2–3 add detail/log location. Invalid values produce one clear configuration diagnostic and boot result 12 before hooks, without rewriting the caller's setting. `BASHCMDR_QUIET_BOOT=1` suppresses routine boot messages and summaries, while explicit framework errors still honor the underlying verbosity level. Configuration-validation diagnostics remain visible. Quiet mode preserves logs and failure status.

### Reset while retaining activation choices

`bcm console reset` restarts the currently eligible active cartridge hooks without changing persistent activation markers. It validates the complete dependency plan and loaded-marker metadata first, deactivates dependents before their dependencies, then calls normal poweron to reactivate in dependency order. Generic cartridges, essentials and shared dependencies retain their choices; inactive, broken, untracked and quarantined entries stay outside the restart set. Original link targets are preserved. Reset has no fixed sleep or implicit activation of defaults.

A deactivation failure stops reset before further dependencies are deactivated and returns nonzero. Earlier successful deactivations may leave partial hook context, while activation choices remain recorded. Correct the provider and initialize a fresh shell to restore context. Source/activation failures are reported rather than treated as a successful reset. An unsuccessful poweron after deactivation propagates its result. If reset stops before poweron, boot result maps still describe the previous poweron; inspect reset's own return status and diagnostic.

Reset rechecks the eligible active set before each deactivation and before restarting. A newly added active choice, newly inactive target or new quarantine causes it to stop while retaining those changes. It does not overwrite concurrent or hook-written choices. These checks are not a cross-process filesystem transaction and do not undo arbitrary trusted hook effects. Deactivation output stays with the explicit reset operation; reactivation output follows normal boot logging.

Hook environment changes affect the executing shell process. An external `bcm` process cannot reload its parent shell's environment. Initialize a fresh shell when the parent needs refreshed context; a sourced console's `console_reset` function operates in that shell and resolves its canonical root after BIOS cleanup. General standalone `console poweroff` retains its separate behavior of unplugging active choices.

### Uninstall protection and retained state

`bcm cartridge uninstall NAME` checks dependency keys in all other installed manifests, including inactive, broken, untracked and quarantined packages. It does not rely on a registry index or cached activation state. Any installed dependent blocks removal, even if its constraint is currently unsupported or unsatisfied. An unreadable, missing or structurally invalid installed manifest also stops removal; output from a failed inspection is never used as permission to delete. Remove or repair the dependent package first. The target's own damaged manifest does not prevent removing it when no other package depends on it.

Successful plain uninstall removes the package directory, matching installed metadata and ordinary active/inactive/broken state links. A quarantine marker is deliberately retained as a tombstone, and reinstalling that name remains quarantined. Choose explicit `--purge` during uninstall to clear the target's framework state, including that marker. For a name already uninstalled, the existing `cartridge release` operation clears its retained quarantine. Purge retains installed dependency protection. Neither mode deletes provider-owned configuration, runtimes or other user data.

An active, nonquarantined package is deactivated before removal; quarantined code is not sourced, including when active and quarantine markers overlap. A deactivation failure stops removal. State, dependency and storage changes made by deactivation are checked before files are deleted. Installed package roots/directories must be ordinary directories; linked installed entries, foreign state files or unexpected link targets require inspection. Existing metadata must be a regular, nonlinked package record identifying the selected name. Missing metadata is allowed. Unknown or extra uninstall options are rejected.

Removal, state cleanup and metadata cleanup are checked separately. An error is nonzero and reports the failed stage; a filesystem failure can leave partial package files, orphan state or retained metadata. Runtime caches reflect observed remaining markers when reconciliation is possible. Inspect the reported paths and repair the incomplete operation before retrying; doctor/release can address state markers but do not restore package files. These checks are cooperative and are not an atomic transaction against concurrent filesystem changes or arbitrary trusted hook effects. As with reset, an external process cannot deactivate its parent shell's environment.

---

### Installation shortcut

Boot never creates or replaces `bin/bcm`. `BASHCMDR_BOOT_SUMMARY[shortcut]` records `ready`, `missing` or `conflict` when firmware poweron starts. Shortcut absence/conflict does not prevent the `bashcmdr` firmware from booting or add noninteractive startup output.

Use `bashcmdr console shortcut` to inspect the selected installation and see a quoted repair command. Add `--install` to create a missing relative `bcm -> bashcmdr` link. A correct link is an idempotent success; existing files, directories and conflicting/dangling links are preserved and an install request returns failure. Inspect and move a conflict manually before requesting installation. Use the selected installation's full `bin/bashcmdr` path if it is not on PATH.

This route, including aliases and `console shortcut --help`, skips runtime directory initialization. Inspection works on a read-only installation; explicit creation needs `ln` and writable ordinary `bin/` storage, with failures reported. No sudo is used. Full firmware boot still needs writable runtime state/log locations and can fail on a fully read-only tree; inspection does not imply that deployment mode is supported. Creation uses checked ordinary filesystem operations, not a transaction against concurrent directory changes.

### Dependency inspection

`cartridge deps NAME` reads direct declarations from the installed manifest. Missing or invalid manifests return failure rather than “No dependencies.” Each declared direct package is also checked for a readable dependency map. Constraints are displayed as text, with control characters/backslashes escaped; inspection does not certify version compatibility or an activation plan.

`cartridge graph NAME` reads the complete reachable installed graph in a fresh traversal and renders an indented tree. Repeated shared nodes are labeled `(shared)`. Actual recursion cycles are labeled `(cycle)` and return failure; missing or malformed descendant manifests are shown as unavailable and also return failure. Other branches are still rendered. A valid leaf prints its name and “No dependencies.”

`cartridge why NAME` scans installed manifests and reports other direct and transitive dependents, with one deterministic example path per transitive dependent. Its traversal is cycle-safe; use `graph` to diagnose graph cycles. A missing queried target can still have incoming declarations, so an empty installation is a successful “target not installed / no installed dependents” result. Malformed installed manifests, linked package entries or missing non-target dependencies make the scan incomplete and return failure before results. The output describes declarations, not why a package is currently active or whether removal is safe; uninstall performs its own current checks.

Inspection runs no provider hooks and leaves activation resolver caches and caller helpers/options unchanged. Direct calls to these inspection helpers write no runtime state; invoking them through the CLI retains the main-dispatch initialization described below.

### Offline discovery and directory creation

`cartridge show NAME` reads an installed package's manifest before consulting the registry. A damaged or missing installed manifest fails visibly; it does not silently substitute remote information. `cartridge search --installed` enumerates ordinary package directories, including manual installs, and reads their local manifests. `--active` selects packages with a matching active link and excludes quarantine. Linked package entries and orphan active links are excluded from local search. These queries work with a missing, stale or invalid registry index and do not source provider hooks.

Local search combines keyword, tag and author filters as case-insensitive regular expressions. Combining `--installed` with `--active` selects the active subset. Invalid patterns or unreadable selected manifests fail without partial result rows. Search without a local selector still uses the registry.

Registry status uses `BASHCMDR_REGISTRY_INDEX`, which defaults to `index.json` under `BASHCMDR_REGISTRY_DIR` (default `~/.bashcmdr/registry`). Status validates an existing index and reports a missing one without creating it. Registry synchronization remains unimplemented.

Importing the registry library or CLI creates no directories. Other CLI routes, including general help/version/discovery, explicitly initialize `cartridges/` and the four runtime state directories and may add an inactive link for a discovered untracked package; the `console shortcut` route described above is exempt. These runtime routes therefore require a writable installation. Importing and directly calling discovery helpers avoids main-dispatch initialization. Registry metadata directories are created on demand when recording an installation; a failure to record metadata returns failure even if the package has already been installed. These changes do not certify native OpenWrt, Termux or Git Bash execution.

## Troubleshooting

### "Cartridge not found in registry"
1. Name-only lookup needs a usable local registry index. Search/status do not fetch one.
2. Use the selected repository URL explicitly: `bashcmdr cartridge install --from <trusted-git-source>`.
3. `registry sync` is a recognized unimplemented command and cannot repair a missing index.

### "Missing dependencies"
Inspect the selected manifest and install each actually declared cartridge dependency from its own trusted Git source before plugging the dependent. For example, substitute real trusted sources in `bashcmdr cartridge install <dependency> --from <git-source>`. A name-only retry does not supply a registry index or an external runtime. Do not add unrelated dependencies merely because an older example named them.

### "Doctor shows broken symlinks"
1. Run `bcm doctor` to repair state links or remove orphaned links. A run that finds
   issues returns failure even when repairs succeed; rerun it to check the result.
2. Restore or reinstall a missing cartridge before attempting activation.
3. For an installed cartridge retained in `broken`, inspect and repair its files,
   then use `bcm cartridge quarantine name repaired`, `bcm cartridge release name`,
   and `bcm cartridge plug name`. Release moves quarantine to inactive; it does not
   directly clear a broken entry. Reset power-cycles the console; use this explicit
   recovery flow for generic broken entries.

### Quarantine reason files

New reasons are stored in `logs/quarantine/<name>.log`, separate from state links.
Current-format files begin with `# Bash Commander quarantine reason log v1`.
The writer appends only to this recognized format and rejects incompatible files
or symlinks. If logging fails, quarantine remains applied and the command returns
failure. A partial write can leave a partial record; retained data is not truncated.

Older reason files in `console/quarantine/<name>.log` are preserved in place.
For example, the old reason for `demo` occupies the state pathname for the valid
cartridge `demo.log`. If that collision blocks CLI startup, inspect the regular
file and relocate only a confirmed legacy reason to a backup directory you choose.
Keep symlink state entries in place. This example is for an inspected legacy reason:

```bash
console_root='/path/to/your/bashcmdr'
legacy_reason="$console_root/console/quarantine/demo.log"
legacy_backup="$HOME/bashcmdr-legacy-reasons"
if [[ -f "$legacy_reason" && ! -L "$legacy_reason" ]]; then
    mkdir -p "$legacy_backup" &&
        mv -i "$legacy_reason" "$legacy_backup/demo.reason.log"
fi
```

Then retry `bcm doctor` and the requested cartridge command. No automatic migration,
renaming, adoption, or deletion of legacy/unknown files is performed. This supports
cooperating use of the configured root; concurrent filesystem replacement requires
coordination. Run `python3 tests/test_quarantine_logs.py` for namespace and file
preservation regressions.

### Functions not available after activation
1. Inspect persistent activation with `bashcmdr console status` and the cartridge diagnostic.
2. An external CLI invocation cannot inject functions into its parent shell. Open a fresh Bash process and source the selected `boot/shell-init.bashcmdr`, checking BASHCMDR_BOOT_EXIT_CODE.
3. A missing upstream runtime can leave a cartridge dormant after a successful boot. Follow that cartridge's guide. Reset is a power-cycle of the invoking process and does not repair arbitrary broken links or reload an existing parent shell.

---

## Development

### Cartridge hook contract

For standard lifecycle actions (`setup`, `activate`, `deactivate`, `diagnose`,
and `help`), `main.bashcmdr` must define its own `cartridge_dispatch` function
when loaded. Keep that function replaceable so the framework can restore the
caller's binding. The framework supplies Bash path helpers and returns the hook's
status. Missing dispatchers and load failures are errors. The caller's dispatcher
binding is restored after each call, including nested calls and hook failures. This status preservation describes `__bashcmdr_cartridge_call`; outer commands such as plug/boot may aggregate a hook failure.

Sourcing must define the dispatcher rather than auto-dispatch a positional action. The interface sources the file, then calls its newly defined dispatcher with the action/arguments. Do not make the dispatcher readonly. Hook functions must tolerate repeated source/call cycles; exported loaded markers are not proof of valid child context. Public functions can outlive the source callback: shared associative context needed later must have global lifetime (for example `declare -gA`), not a declaration local to that callback. Keep private names cartridge-specific; the framework isolates the dispatcher, not arbitrary Bash globals.

A complete executable example and return/repeated-source contract is in [CARTRIDGE_CONTRACT.md](docs/CARTRIDGE_CONTRACT.md).

Hooks run in the calling shell so activation can retain PATH, exported variables,
and functions. An external CLI process retains these changes in that process;
activation during shell startup retains them in the shell loading the console.

Run `python3 tests/test_hook_context.py` for local hook regressions. Set
`HOOK_TEST_FIRST_PARTY_ROOT` to a directory containing the Go, NVM, Pyenv, and
Fabric cartridge checkouts to enable the additional cross-repository fixtures.

`bashcmdr_get_activation_plan` prints one cartridge name per line on stdout and
sends resolver diagnostics to stderr, according to the configured verbosity.
Plug checks the producer's exit status before using its output; failed or empty
plans never start activation. Run `python3 tests/test_activation_plan.py` for
stream, status, and activation-order regressions.

State synchronization, transitions, and power-on create the four runtime state
directories (`active`, `inactive`, `broken`, and `quarantine`) when needed. Code-only
installations do not need placeholder directories copied from a checkout.
Directory-creation failure stops these operations before existing links are
removed or startup hooks run. Runtime state links are ignored by Git; source
placeholders remain eligible for tracking. Run `python3 tests/test_state_layout.py`
for fresh-layout and initialization-failure regressions.

New and replaced state links use relative targets so the console can be relocated.
State replacement serializes cooperating operations per cartridge and stages prior
links for rollback on failure. A recovery diagnostic names the retained transaction
directory if rollback or cleanup fails. `committed=0` means inspect the saved prior
links; `committed=1` means the replacement applied but cleanup failed. Preserve that
directory for inspection before retrying. Uncatchable termination and filesystem
failures during rollback require operator recovery; concurrent external writers
are outside the transaction contract.

Plug snapshots each planned cartridge's physical state before activation and
refreshes those cache entries. Already-active hooks still load to provide context
in a fresh process; plug preserves their state and never deactivates them during
rollback. On hook or state-write failure, it restores the failed entry's prior
state and reverses earlier successful activations owned by that attempt, in
reverse order. An original absence of state links is restored as absence.
Duplicate plan entries, ambiguous states and non-symlink state collisions fail
before hooks run.

Activation hooks must clean up their own partial changes before returning failure;
plug does not call deactivate for an activation that failed. Deactivate hooks undo
successful owned activations. Cleanup errors remain visible and nonzero while
rollback attempts the remaining entries. Arbitrary hook changes to files, functions
or the environment are not automatically snapshotted, and concurrent plug attempts
or external state changes require coordination. Run `python3 tests/test_plug_rollback.py`
for pre-state, ownership, failure and fresh-context regressions.

The shared activation boundary checks declared dependencies before sourcing any
cartridge code. Diagnosis, help, and deactivation remain available during quarantine.
This policy applies to cooperating framework calls; cartridge scripts are trusted
Bash code. Run `python3 tests/test_quarantine_policy.py` for boot, plug, dependency,
release, repair, and dormant-essential regression controls. Boot ordering and its
aggregate status have separate acceptance work.

Doctor counts detected integrity issues, including unsuccessful repair attempts,
and returns nonzero when any were found. Its helpers accept an optional count
variable for the full total; their nonzero exit counts saturate at 255. Run
`python3 tests/test_state_results.py` for replacement, recovery, status, relocation,
and integrity-accounting regressions.

### Version Management

The version is stored in `VERSION` at the repo root. Use the bump script:

```bash
./scripts/bump-version.sh show     # Print current version
./scripts/bump-version.sh patch    # Bump patch version
./scripts/bump-version.sh minor    # Bump minor version
./scripts/bump-version.sh check    # Verify VERSION matches git tag
```

### Running Tests

```bash
bash tests/test_runner.bash              # Unit tests
bash tests/test_resolver.bash            # Resolver contracts
bash tests/test_path.bash                # Path helpers
bash tests/test_install.bash             # Owned Git-source installation
python3 tests/test_docs.py --first-party-root .. # Executable console guide and documentation controls
bash tests/factorial_test_runner.bash    # Matrix tests
python3 tests/test_harness_isolation.py  # Clean/contaminated harness controls
python3 tests/test_semantic_gates.py     # Deliberately faulty behavior/results
python3 tests/test_matrix_generator.py   # Expanded catalog generation/failure paths
python3 tests/test_alias_help.py         # Read-only help, alias state and completion
python3 tests/test_provider_contracts.py --first-party-root ..  # Pinned sibling cartridges
python3 tests/test_runtime_preflight.py   # Missing tools, fail-closed JSON and completion
python3 tests/test_version_comparison.py  # Numeric operators, rejection and plan/boot consumers
python3 tests/test_install_source_policy.py # Owned Git operands, transports and commit records
python3 tests/test_sourcing_contracts.py    # Owned sourcing paths, operands and real permissions
python3 tests/test_shell_hygiene.py         # Owned helper state and config initialization lifetime
python3 tests/test_path_edge_contracts.py   # Owned regex, empty options and literal editor argv
python3 tests/test_tool_portability.py   # Tool fallbacks, timestamps and honest timing
python3 tests/test_analyzer_contracts.py # Structured categories, errors and report outputs
```

The unit, resolver, path, install and factorial shell suites launch through
`tests/harness.bash`. Each invocation gets an owned temporary HOME, configuration,
cartridge tree and framework copy containing only `bin`, `boot`, `lib` and
`VERSION`. Checkout runtime cartridges/config/state and inherited Bash Commander
roots are excluded. Fixture Git operations ignore caller/system configuration,
hooks, signing and Git-directory overrides; only local file transport is enabled.
Unit dependency checks always run against an inert synthetic leaf.

The parent retains the selected PATH/toolchain, optional TMPDIR and explicit
`BASHCMDR_TEST_RESULTS_DIR`, then starts clean parent/child Bash processes. The
known running Bash supplies integration shells, and the editor fixture is a Bash
function, avoiding fixed interpreter/search-path assumptions. The initial Bash
invocation remains the caller's responsibility; startup code already executed by
that interpreter cannot be undone by a test file. The private child entry is an
internal harness interface, not a sandbox for untrusted test source or tools.

Each run prints its unique artifact directory under `tests/results/` (or
`BASHCMDR_TEST_RESULTS_DIR`). Complete child stdout/stderr, assertion diagnostics,
setup failures, exit status and cleanup status remain there after EXIT cleanup of
the temporary installation. Matrix runs also save every case's combined output
and reference it from `rapid_test_results.json`. CI uploads the whole results tree.
Abnormal termination that bypasses EXIT traps may require fixture cleanup.
Matrix semantic expectations and native platform certification remain separate
release checks; these isolation controls alone do not certify those outcomes.

### Test and CI semantic gates

`tests/rapid-cases.json` defines the 35 rapid cases as argument arrays with explicit
expected exits. The fixture has no installed cartridges and supplies an owned
empty registry index so valid search/list commands can succeed. Deliberate
missing-cartridge and invalid-command cases expect exit 1; positive cases expect
exit 0. The runner executes arguments directly and records actual/expected exits,
pass status, classification and complete case output. It returns failure after
collecting all cases if any result differs from the reviewed expectation.

`tests/check-matrix.bash` validates both runner output and CI results against that
same oracle. It rejects missing, empty, malformed or incomplete records, duplicate
or changed cases, forged expectations/pass flags, mismatched exits/classifications
and missing or linked diagnostic files. CI invokes this gate even after earlier
failures. Invoke it with a printed per-run `rapid_test_results.json` path to select
one result, or without arguments to validate all discovered factorial results.
Older saved result schemas also fail validation rather than being silently
accepted as current proof.

Unit output assertions check the expected status as well as the text. The
missing-plug diagnostic explicitly expects exit 1; a matching message with exit 0
or another status fails. Quiet-source checks require exit 0 and zero raw output
bytes across stdout/stderr, including newline-only noise. The negative regression
suite mutates owned copies of real commands and exercises the actual CI shell
block; a normal green run alone is not proof that a gate detects failures.
These rapid cases do not cover every supported CLI combination or certify native
platforms, and local checks do not constitute a remote GitHub workflow run.

### Expanded command catalog

`bash tests/command_matrix_generator.bash` generates a complete JSON document at
`tests/results/full_factorial_matrix.json`, an ignored artifact uploaded by CI.
Use `--output -` for JSON on stdout, or `--output FILE` for a different destination.
Generation finishes and validates its JSON before replacing an existing regular
output file. It rejects linked or nonregular outputs; failed generation or a
failed final move leaves the previous file intact. Coordinate concurrent changes
to destination directories; this is not protection against hostile filesystem
replacement. Temporary files are cleaned on normal exit and handled signals.

The default catalog contains 296 cases using neutral `demo` and `dependency`
template names, without scanning the checkout or inherited runtime roots. Repeat
`--cartridge NAME` to replace those defaults. Optional `--root DIR` adds names
from ordinary directories in `DIR/cartridges/`; it excludes symlink entries,
files and the retired `installed/` layout. It does not read cartridge manifests
or execute providers. Generation requires Bash, jq, mktemp and ordinary file
utilities; it uses no privilege escalation, date, bc or GNU find/sort features.

The schema `bashcmdr.command-catalog.v2` stores authoritative `argv` arrays and
shell-quoted display strings, current noun/verb forms, negative syntax cases,
Phase 1 stub failures and search-option combinations. Names and quoted query
values remain data. Output is deterministic and contains no local installation
paths or timestamps. The old malformed tracked matrix is removed; regenerate
the ignored artifact rather than treating historical output as current proof.

This catalog is command data, never execution results. `classification` describes
syntax; a valid command can still fail. Fixed `expected_exit_code` values describe
the CLI contract in a usable owned runtime, including exit 1 for Phase 1 stubs.
Context-dependent commands have `expected_exit_code: null` and explicit fixture
requirements. An executor must supply that fixture and bind an exact expectation
before running them. Detailed help rows retain the documented help contract;
separately tracked help defects are not resolved by generating this catalog.
The 296 rows sample supported grammar and selected option cross-products; they
do not exhaust every value/combination, replace the executable 35-case rapid
oracle, prove all commands pass or certify native platforms. CI checks generation
and failure handling without executing the expanded catalog.

### First-party lifecycle contracts

`tests/first-party-inputs.json` pins the Go, NVM, Pyenv and Fabric cartridge
revisions and SHA-256 hashes of their actual main scripts/manifests. Supply a
directory containing those four `bashcmdr-cartridge-*` checkouts:

```bash
python3 tests/provider_inputs.py --verify ../first-party
python3 tests/test_provider_contracts.py --first-party-root ../first-party
```

The suite admits those exact inputs before any cartridge hook runs. Missing or
changed inputs fail; they do not turn the required lane into skipped success.
Git checkouts must match the pinned HEAD and content. Matching two-file source
exports are labeled as content verification without inventing Git HEAD evidence.
When intentionally changing a first-party candidate, update its pins and rerun
the composed tests. This prevents an unrelated moving branch from silently
changing the contract inputs.

Tests copy actual cartridge code into owned HOME/runtime trees and supply inert
Go, Pyenv, NVM and Fabric interfaces. They exercise real lifecycle dispatch,
path/environment coupling, diagnose status, new-versus-preexisting activation
rollback, verbose public plan data, quarantine during full BIOS boot, shared
dependencies, cycles, version conflicts and help without loading provider code.
The public `bashcmdr_get_activation_plan` API emits names on stdout; the user CLI
`bcm cartridge plan` retains its human-readable display. Test commands and owned
logs can be retained with `PROVIDER_TEST_EVIDENCE_DIR`.

CI reads the pin file, checks out the four requested revisions into ignored
`.test-inputs/first-party/`, then runs this required contract lane. The workflow
uses a read-only contents token and does not persist checkout credentials. Each
referenced commit must be available to the workflow's credentials; local tests
alone do not establish hosted checkout or CI success. This repository does not
embed the cartridges or automatically fetch them when running local tests.

The resolver suite distinguishes checks of the current Bash interpreter's
variable capabilities from actual resolver behavior. Its label does not claim
a Bash 5.3/aarch64 run. These owned-tool fixtures do not install upstream version
managers or certify native platforms; declared-platform and full-candidate checks
remain separate release gates.

For an additional already available test interpreter, set `RUNTIME_TEST_BASH`:

```bash
RUNTIME_TEST_BASH=/path/to/bash-4.3 python3 tests/test_runtime_preflight.py
RUNTIME_TEST_BASH=/path/to/bash-3.2 RUNTIME_EXPECT_REJECTION=1 \
    python3 tests/test_runtime_preflight.py BashAdmissionTests
```

The first command runs all prerequisite/completion controls with that interpreter.
The second tests explicit CLI/sourced-CLI rejection and nonfatal BIOS failure for
an interpreter below the current feature threshold. It does not claim that old
Bash runs the framework. Each invocation retains calls, stdout/stderr and inert
operation traces in a unique `tests/results/runtime-preflight.*` directory or
`RUNTIME_TEST_EVIDENCE_DIR`. Alternate interpreter tests do not establish native
macOS, OpenWrt, Termux or Git Bash certification.

---

## Current behavior and limits

- `registry sync`, `console upgrade`, `console uninstall` and `cartridge upgrade` are recognized stubs that report not implemented and return failure. Do not use them as installation, repair or update recipes.
- `cartridge list outdated` currently returns status0 without outdated-version data. Its informational not-implemented notice follows verbosity and can be hidden at low verbosity; zero status or silence is not an implemented query.
- Explicit Git-source install and usable local-index lookup are separate paths. There is no shipped remote-sync/index provisioning workflow in this guide.
- Signing/checksum verification, a final support/native-platform matrix, hosted release checks and exact publication operations are not established by local fixtures or old reports. Git commit metadata records source provenance, not authenticity or sandboxing.
- Historical installation/planning/test documents are labeled as such. The tracked rapid JSON is a historical display fixture, not the live result destination or a current acceptance oracle. Current suites write unique owned result directories and CI uploads those actual runs.
- Cartridges execute trusted Bash. Failures/rollback preserve only the explicitly implemented state/owned bindings; there is no rollback of arbitrary script effects or coordination guarantee for external concurrent writers.

## Required development checks

Run `bash --noprofile --norc tests/ci.bash /path/to/first-party` from the checkout, with Bash4.3 or newer, Python3.14, Git, jq and the pinned official Linux x86_64 ShellCheck0.10.0 available on PATH. For an alternate installed Bash, invoke that interpreter with the same arguments. The four directories under the input root must match `tests/first-party-inputs.json`; CI also verifies the guide/test hashes in `tests/ci-first-party.json` before execution. Missing tools, files, content pins or tests fail the run. The payload installs no runtimes and needs no sudo.

The shared payload runs all33 current Console Python suites, all26 shell syntax/lint targets, the five shell suites, actual current rapid-result gating/analysis, the296-row non-executed command catalog, composed hooks/provider/guide contracts and the applicable Go/NVM/Pyenv/Fabric runtime and guide suites (including NVM hook coverage). External installers, API tools and privileged operations in those suites use owned fixtures. Passing these checks does not certify native platforms or external runtimes.

Every invocation creates a fresh `tests/results/ci/run.*` directory with a summary, actual tool/interpreter/input hashes, per-phase stdout/stderr/exit status and current records. The tracked historical rapid JSON is preserved; actual rapid analysis receives the one result created by this invocation. Required failures stop later phases, and diagnostic evidence remains available after failure.

The workflow proposes Ubuntu24.04/Python3.14 for development, uses immutable action references and exact first-party revisions, verifies the official ShellCheck archive/binary checksums, grants contents:read, disables persisted checkout credentials and always retains the current CI evidence for14 days. The Linux-specific tool bootstrap is confined to that runner; it is not a product-platform requirement. Referenced commits must be available and readable to the runner before hosted execution; private cross-repository checkout can require separately authorized access. Local fixture results do not establish hosted execution, select the release support matrix or approve publication.

## License

Copyright 2026 Eric Milgram. Original project code is licensed under [Apache-2.0](LICENSE); see [NOTICE](NOTICE). Bash Commander is an official OAS FOSS project.

See [third-party notices](THIRD_PARTY_NOTICES.md) for the Collyer/Netspinner path-utility origin and published permission statement. Individual cartridges and upstream runtimes retain their applicable terms. No production/readiness or release promise follows from passing local fixture tests.
