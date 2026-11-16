# Prerelease support policy

Bash Commander is an official OAS FOSS project preparing its first public
prerelease: Console plus the Go, NVM, Pyenv and Fabric cartridges. The release
policy is approved; final candidate acceptance and publication are still pending.

## Bash-centric core

The core uses Bash capabilities and user-owned paths. It does not assume Linux,
a distribution package manager or `sudo`. Supply a maintained, patched Bash from
your environment's provider. The current language-feature threshold is Bash 4.3,
including associative arrays, `mapfile` and namerefs; that threshold is not a
security-maintenance recommendation or certification of every newer shell.

Git and jq are needed for the advertised installation flow. Individual commands
have the narrower prerequisites described in the Console README. Applicable
filesystem permissions, directory and symbolic-link operations must work in the
chosen environment. External cartridge runtimes have their own requirements.

## Verified targets and acceptance

Support for a published prerelease is limited to the exact configurations and
flows that pass its final acceptance checks and appear in its release record.
No configuration has completed that final release acceptance yet. Current private
verification identifies the following baseline, rather than promising universal
native support:

| Configuration | Evidence and limit |
| --- | --- |
| Linux Mint 22.3, x86_64, Bash 5.2.21 | Required local development checks and owned native tool integration have passed; final accepted-source and public-user acquisition/use remain required. |
| Private historical Bash 4.3 build on that Linux host | Local compatibility checks and owned native integration; not a maintained-shell recommendation, a separate OS target or proof for every Bash version. |
| Ubuntu 24.04 development workflow | Prepared CI runner configuration; a workflow declaration is not a successful hosted run or product support certification. |
| Git Bash on Windows, macOS/BSD, OpenWrt, Termux/Android, Linux ARM and other configurations | Portability targets without native release acceptance. They become supported only after their exact configuration and required flows pass acceptance. |

Observed Git 2.43.0 and jq 1.7 are test-environment versions, not established
minimum versions. Python and ShellCheck used by development checks are separate
from the Console runtime requirements. Release acceptance does not require an
additional non-Linux target for this first prerelease. Keep capability-based
behavior and investigate applicable portability defects as support expands.

## Separately supplied tools

Owned native integration has been exercised with the following specific tools
on the Linux baseline and the private Bash 4.3 compatibility interpreter:

| Cartridge | Observed tools | Bounded verification |
| --- | --- | --- |
| Go | Go 1.27.0 | Existing bootstrap discovery, fresh-shell activation, repeated activation, cleanup and real invalid-root failure. |
| NVM | NVM 0.40.7, Node.js 24.19.0, npm 12.0.2 | Existing NVM sourcing, fresh-shell activation, user-local links and failure boundaries; deactivation retains upstream NVM functions/configuration and created links. |
| Pyenv | Pyenv 2.8.14, pyenv-virtualenv commit `7d821a62d6eeae21a451141c41898be1ed4ed147`, existing Python 3.12.3 | Real initialization, shim dispatch, shell selection, repeated activation and owned cleanup in tested discovery contexts. No Python build, package install or virtual-environment creation certification. |
| Fabric | Fabric 1.4.470, Go 1.27.0 | Existing tool discovery/version, lifecycle, helper wiring and owned cleanup. No provider/model request, credentials, patterns or live video/network operation certification. |

These are observations, not new upstream version floors or certification of all
versions and features. The cartridges integrate separately provided tools and do
not install them. The source release does not bundle those runtime distributions.
Upstream licenses and support policies remain separate. Final release evidence
must bind the actual accepted source and tools; older native results are not
silently relabeled as a new candidate run. Fixture tests establish only their
tested interfaces and cannot establish native platform support.

## Working flows and limits

Use explicit trusted Git sources when no usable local registry index exists.
Activation sources trusted cartridge code. An external `plug` command records
persistent activation but cannot change its parent shell's functions or PATH.
Initialize in a fresh Bash and require `BASHCMDR_BOOT_EXIT_CODE=0`; sourcing alone
has a nonfatal return and does not prove boot success. Missing external tools may
leave a cartridge dormant even after a successful Console boot.

`console upgrade`, `console uninstall`, `cartridge upgrade` and `registry sync`
are unimplemented and return 1. `cartridge list outdated` returns 0 with a
placeholder; it does not compute an update inventory. Registry synchronization
is not a recovery instruction. Use the documented available flows and retain
failure diagnostics when reporting an issue.

Acceptance covers the exact source/tool configuration, acquisition, fresh-shell
boot, documented installation/lifecycle/diagnosis and cleanup, expected failures
and required tests. Public acquisition/use is checked after publication. Required
defects in the supported scope remain release gates. This policy creates no paid
support arrangement, staffing commitment, SLA or response deadline.
