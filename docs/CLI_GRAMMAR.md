# CLI grammar and implemented command routes

Use canonical bashcmdr; bcm is a compatibility shortcut when it resolves to that installation. An external command runs in its own process. The [entry guide](../README.md) supplies acquisition, prerequisites, root selection and current-shell startup; the [cartridge contract](CARTRIDGE_CONTRACT.md) describes hooks.

## Grammar

```text
bashcmdr version
bashcmdr help [noun] [verb]
bashcmdr doctor
bashcmdr alias <shortcut> <command...>
bashcmdr alias list
bashcmdr alias remove <shortcut>
bashcmdr console <verb> [arguments]
bashcmdr cartridge <verb> [arguments]
bashcmdr registry <verb> [arguments]
```

Noun/verb help and -h/--help requests inspect usage without running mutating verbs. Bare nouns show their help. Aliases are saved shortcuts, not preinstalled top-level install/plug commands; first-reader examples do not assume an operator-defined alias.

## Console

Implemented routes are poweron, poweroff, status, reset, log and shortcut. Log accepts --lines; shortcut inspection is read-only and --install explicitly creates its user shortcut. Reset power-cycles hooks in the invoking process while retaining activation choices. It is not generic integrity repair or injection of functions into a parent shell.

Console upgrade and console uninstall are recognized unimplemented routes: they report not implemented and return1. They are not installation/update/removal workflows.

## Cartridge

Implemented routes include install, uninstall, plug, unplug, quarantine, release, list, search/find, show, deps, plan, graph, why and diagnose. Installation accepts an explicit --from Git source, with an optional requested name constrained by the manifest. Name-only installation requires a usable local registry index. No remote registry sync is available to populate a fresh index.

List filters are all, active, inactive, quarantine and broken. List outdated is a recognized stub which currently returns0 without outdated-version data. Its informational not-implemented notice follows verbosity and may be silent at low verbosity; neither outcome is an implemented query. Cartridge upgrade reports not implemented and returns1.

Plug resolves declared dependencies and runs hooks in this process. Persistent activation and current-shell functions are different. Unplug checks active dependents; quarantine prevents activation; release returns a retained quarantine entry to inactive. Uninstall protects active dependents and has its own retained-state/--purge semantics. Inspect those explicit choices before removing an installation.

Deps, plan, graph and why inspect installed manifest dependency data without installing or invoking activation hooks. They do not guarantee future remote availability. Search/find --local and show --local read installed manifests; default discovery uses the configured registry rather than inventing a remote index. See the README for complete flags and failure behavior.

## Registry

Registry list and status inspect the configured local index/state. Registry sync is a recognized unimplemented route and returns1. There is no signed-index provisioning or verification guarantee implied by those names.

## Results and trust

Unknown nouns/verbs and invalid arguments fail; contextual help can still succeed for a recognized unimplemented verb. A zero status from help or the outdated-list stub does not mean the operation was implemented. Inspect the actual operation output and documented status.

Doctor inspects/repairs selected-root integrity and returns failure when it finds issues, including unsuccessful repair attempts. A rerun can show the repaired state; reset is not a replacement for doctor. Activation sources trusted cartridge Bash, and Git provenance is not a signature/sandbox guarantee. Boot records aggregate outcome while startup sourcing remains nonfatal.

The exact command surface and statuses are exercised by alias/help, options, inspection, local-info, state, reset, install, provider and documentation suites under tests/. Historical installation plans and reports do not extend this grammar.
