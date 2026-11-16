#!/usr/bin/env python3
"""Root coherence using owned installations and otherwise empty tool state."""
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

REPO = pathlib.Path(os.environ.get('ROOT_SELECTION_TEST_REPO', pathlib.Path(__file__).resolve().parent.parent))
PREFIX = r'''
git() { printf 'unexpected-git\n' >> "$TRACE"; return 99; }
curl() { printf 'unexpected-curl\n' >> "$TRACE"; return 99; }
wget() { printf 'unexpected-wget\n' >> "$TRACE"; return 99; }
sudo() { printf 'unexpected-sudo\n' >> "$TRACE"; return 99; }
service() { printf 'unexpected-service\n' >> "$TRACE"; return 99; }
assert_origins() {
    local expected="$1" definition function
    shopt -s extdebug
    for function in addpath bc_source __bashcmdr_info main console_poweron; do
        definition=$(declare -F "$function") || return 81
        [[ "$definition" == *" $expected/"* ]] || { printf '%s\n' "$definition" >&2; return 82; }
    done
}
'''


class RootSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bcm-root-controls-')
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.home = self.root / 'home'
        self.home.mkdir()
        self.alternate = self.root / 'alternate console'
        self.default = self.home / '.local/bin/bashcmdr'
        self.install(self.alternate)
        self.trace = self.root / 'operations.log'
        self.trace.write_text('')

    def install(self, target):
        for name in ['bin', 'lib', 'boot']:
            shutil.copytree(REPO / name, target / name)
        shutil.copyfile(REPO / 'VERSION', target / 'VERSION')
        (target / 'cartridges').mkdir()

    def probe(self, body, **extra):
        env = {'HOME': str(self.home), 'PATH': '/usr/bin:/bin', 'TERM': 'dumb', 'LC_ALL': 'C',
               'ALT': str(self.alternate), 'DEFAULT': str(self.default), 'TRACE': str(self.trace),
               'BASHCMDR_QUIET_BOOT': '1', 'TMPDIR': str(self.root)}
        env.update(extra)
        p = subprocess.run(['/bin/bash', '--noprofile', '--norc', '-c', PREFIX + body],
                           env=env, cwd=self.root, capture_output=True, text=True, timeout=8)
        self.assertEqual(self.trace.read_text(), '', p.stdout + p.stderr)
        return p

    def assert_ok(self, body, **extra):
        result = self.probe(body, **extra)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_default_unset_root_boot(self):
        self.install(self.default)
        self.assert_ok(r'''
source "$DEFAULT/boot/shell-init.bashcmdr"
[[ $BASHCMDR_BOOT_BASIC_EXIT_CODE == 0 && $BASHCMDR_BOOT_EXIT_CODE == 0 && $BASHCMDR_ROOT_DIR == "$DEFAULT" && $BASHCMDR_CONSOLE_EXE == "$DEFAULT/bin/bashcmdr" ]] || exit 80
assert_origins "$DEFAULT"
''')

    def test_alternate_only_unset_root_boot(self):
        self.assert_ok(r'''
source "$ALT/boot/shell-init.bashcmdr"
[[ $BASHCMDR_BOOT_EXIT_CODE == 0 && $BASHCMDR_ROOT_DIR == "$ALT" ]] || exit 80
assert_origins "$ALT"
''')

    def test_alternate_only_preset_root_boot(self):
        self.assert_ok(r'''
BASHCMDR_ROOT_DIR="$ALT"
source "$ALT/boot/shell-init.bashcmdr"
[[ $BASHCMDR_BOOT_EXIT_CODE == 0 && $BASHCMDR_CONSOLE_EXE == "$ALT/bin/bashcmdr" ]] || exit 80
assert_origins "$ALT"
''')

    def test_two_roots_unset_uses_source_installation(self):
        self.install(self.default)
        self.assert_ok('source "$ALT/boot/shell-init.bashcmdr"\nassert_origins "$ALT"')
        self.assertFalse((self.default / 'logs').exists())
        self.assertTrue((self.alternate / 'logs/console-poweron.log').is_file())

    def test_inherited_alternate_selects_complete_bios(self):
        self.install(self.default)
        self.assert_ok(r'''
export BASHCMDR_ROOT_DIR="$ALT"
source "$DEFAULT/boot/shell-init.bashcmdr"
[[ $BASHCMDR_BOOT_EXIT_CODE == 0 && $BASHCMDR_ROOT_DIR == "$ALT" ]] || exit 80
assert_origins "$ALT"
shopt -s extdebug
! declare -F __bashcmdr_boot_output_success >/dev/null || exit 81
[[ $(declare -F __bashcmdr_report_boot) == *" $ALT/"* ]] || exit 82
[[ $BASHCMDR_BOOT_ROOT_DIR == "$ALT" && $BASHCMDR_BOOT_CONSOLE_EXE == "$ALT/bin/bashcmdr" ]]
''')
        self.assertFalse((self.default / 'logs').exists())

    def test_paired_internal_overrides_select_complete_bios(self):
        self.install(self.default)
        self.assert_ok(r'''
BASHCMDR_ROOT_DIR="$ALT"; BASHCMDR_BOOT_ROOT_DIR="$ALT"; BASHCMDR_BOOT_CONSOLE_EXE="$ALT/bin/bashcmdr"
source "$DEFAULT/boot/shell-init.bashcmdr"
[[ $BASHCMDR_BOOT_EXIT_CODE == 0 ]] || exit 80
assert_origins "$ALT"
''')

    def test_boot_root_alone_selects_complete_bios(self):
        self.install(self.default)
        self.assert_ok('BASHCMDR_BOOT_ROOT_DIR="$ALT"\nsource "$DEFAULT/boot/shell-init.bashcmdr"\nassert_origins "$ALT"')

    def test_global_promotion_survives_post_and_caller_function(self):
        self.assert_ok(r'''
initialize() { source "$ALT/boot/shell-init.bashcmdr"; }
initialize
[[ $BASHCMDR_ROOT_DIR == "$ALT" && $BASHCMDR_CONSOLE_EXE == "$ALT/bin/bashcmdr" ]] || exit 80
[[ $(declare -p BASHCMDR_ROOT_DIR) == 'declare -r '* && $(declare -p BASHCMDR_CONSOLE_EXE) == 'declare -r '* ]]
''')

    def test_matching_readonly_root_and_executable_are_accepted(self):
        self.assert_ok(r'''
readonly BASHCMDR_ROOT_DIR="$ALT" BASHCMDR_CONSOLE_EXE="$ALT/bin/bashcmdr"
source "$ALT/boot/shell-init.bashcmdr"
[[ $BASHCMDR_BOOT_EXIT_CODE == 0 ]] || exit 80
assert_origins "$ALT"
''')

    def test_matching_readonly_paired_boot_overrides_are_accepted(self):
        self.assert_ok(r'''
readonly BASHCMDR_ROOT_DIR="$ALT" BASHCMDR_BOOT_ROOT_DIR="$ALT" BASHCMDR_BOOT_CONSOLE_EXE="$ALT/bin/bashcmdr"
source "$ALT/boot/shell-init.bashcmdr"
[[ $BASHCMDR_BOOT_EXIT_CODE == 0 && $BASHCMDR_BOOT_ERR_VALIDATION_FAILED == 12 ]] || exit 80
assert_origins "$ALT"
''')

    def test_conflicting_paired_overrides_fail_before_loading(self):
        self.install(self.default)
        result = self.assert_ok(r'''
BASHCMDR_ROOT_DIR="$ALT"; BASHCMDR_BOOT_ROOT_DIR="$DEFAULT"
source "$ALT/boot/shell-init.bashcmdr"
[[ $BASHCMDR_BOOT_BASIC_EXIT_CODE == 12 && $BASHCMDR_BOOT_EXIT_CODE == 12 && $BASHCMDR_ROOT_DIR == "$ALT" ]] || exit 80
! declare -F main >/dev/null
''')
        self.assertIn('conflicts', result.stderr)
        self.assertFalse((self.alternate / 'logs').exists())

    def test_conflicting_readonly_executable_fails_without_promotion(self):
        self.install(self.default)
        result = self.assert_ok(r'''
BASHCMDR_ROOT_DIR="$ALT"; readonly BASHCMDR_CONSOLE_EXE="$DEFAULT/bin/bashcmdr"
source "$ALT/boot/shell-init.bashcmdr"
[[ $BASHCMDR_BOOT_EXIT_CODE == 12 && $BASHCMDR_CONSOLE_EXE == "$DEFAULT/bin/bashcmdr" && $BASHCMDR_ROOT_DIR == "$ALT" ]] || exit 80
[[ $(declare -p BASHCMDR_ROOT_DIR) == 'declare -- '* ]]
''')
        self.assertIn('conflicts', result.stderr)

    def test_readonly_empty_and_specialized_roots_fail_cleanly(self):
        for prelude in ['readonly BASHCMDR_ROOT_DIR=""', 'declare -a BASHCMDR_ROOT_DIR=("$ALT")',
                        'declare -n BASHCMDR_ROOT_DIR=ALT']:
            with self.subTest(prelude=prelude):
                result = self.assert_ok(prelude + r'''
source "$ALT/boot/shell-init.bashcmdr"
[[ $BASHCMDR_BOOT_EXIT_CODE == 12 ]] || exit 80
! declare -F main >/dev/null
''')
                self.assertNotEqual(result.stderr, '')

    def test_missing_selected_root_is_visible_and_never_falls_back(self):
        self.install(self.default)
        result = self.assert_ok(r'''
BASHCMDR_ROOT_DIR="$HOME/absent"
source "$DEFAULT/boot/shell-init.bashcmdr"
[[ $BASHCMDR_BOOT_EXIT_CODE == 12 && $BASHCMDR_ROOT_DIR == "$HOME/absent" ]] || exit 80
! declare -F main >/dev/null
''')
        self.assertIn('unavailable', result.stderr)
        self.assertFalse((self.default / 'logs').exists())

    def test_missing_selected_bios_has_explicit_failure(self):
        self.install(self.default)
        (self.alternate / 'boot/shell-init.bashcmdr').unlink()
        result = self.assert_ok(r'''
BASHCMDR_ROOT_DIR="$ALT"
source "$DEFAULT/boot/shell-init.bashcmdr"
[[ $BASHCMDR_BOOT_EXIT_CODE == 11 ]] || exit 80
! declare -F main >/dev/null
''')
        self.assertIn('no readable BIOS', result.stderr)

    def test_missing_executable_retains_selected_helpers_and_reports_failure(self):
        (self.alternate / 'bin/bashcmdr').chmod(0o644)
        result = self.assert_ok(r'''
source "$ALT/boot/shell-init.bashcmdr"
[[ $BASHCMDR_BOOT_EXIT_CODE == 10 && $BASHCMDR_BOOT_BASIC_EXIT_CODE == 10 ]] || exit 80
declare -F addpath >/dev/null && declare -F bc_source >/dev/null
''')
        self.assertIn('not executable', result.stderr)

    def test_missing_helper_library_is_not_hidden_by_an_ambient_function(self):
        (self.alternate / 'lib/path.bashcmdr').unlink()
        result = self.assert_ok(r'''
addpath() { :; }
source "$ALT/boot/shell-init.bashcmdr"
[[ $BASHCMDR_BOOT_EXIT_CODE == 11 ]] || exit 80
! declare -F main >/dev/null
''')
        self.assertIn('Failed to load', result.stderr)

    def test_failed_firmware_source_is_visible(self):
        with (self.alternate / 'bin/bashcmdr').open('a') as f:
            f.write('\nreturn 37\n')
        result = self.assert_ok(r'''
source "$ALT/boot/shell-init.bashcmdr"
[[ $BASHCMDR_BOOT_BASIC_EXIT_CODE == 0 && $BASHCMDR_BOOT_EXIT_CODE == 11 ]]
''')
        self.assertIn('Failed to load selected console firmware', result.stderr)

    def test_repeat_source_is_idempotent_across_another_entry(self):
        self.install(self.default)
        self.assert_ok(r'''
source "$ALT/boot/shell-init.bashcmdr"
before=$(declare -pf main)
source "$DEFAULT/boot/shell-init.bashcmdr"
[[ $BASHCMDR_BOOT_EXIT_CODE == 0 && $(declare -pf main) == "$before" ]] || exit 80
assert_origins "$ALT"
''')

    def test_direct_cli_discovers_itself_without_root_override(self):
        result = self.assert_ok('"$ALT/bin/bashcmdr" version')
        self.assertIn('Root directory: ' + str(self.alternate), result.stdout)
        self.assertEqual(result.stderr, '')

    def test_external_absolute_and_relative_symlink_chains(self):
        links = self.root / 'external bin'
        links.mkdir()
        (links / 'absolute').symlink_to(self.alternate / 'bin/bashcmdr')
        (links / 'relative').symlink_to('../alternate console/bin/bashcmdr')
        (links / 'chain').symlink_to('relative')
        for name in ['absolute', 'relative', 'chain']:
            with self.subTest(name=name):
                result = self.assert_ok('"$LINK" version', LINK=str(links / name))
                self.assertEqual(result.stderr, '')
                self.assertIn('Root directory: ' + str(self.alternate), result.stdout)

    def test_symlinked_bios_uses_actual_installation(self):
        alias = self.root / 'external bios'
        alias.symlink_to(self.alternate / 'boot/shell-init.bashcmdr')
        self.assert_ok('source "$LINK"\n[[ $BASHCMDR_BOOT_EXIT_CODE == 0 ]] || exit 80\nassert_origins "$ALT"', LINK=str(alias))

    def test_inherited_root_redirects_sourced_cli_and_full_definitions(self):
        self.install(self.default)
        self.assert_ok(r'''
BASHCMDR_ROOT_DIR="$ALT"
source "$DEFAULT/bin/bashcmdr"
shopt -s extdebug
[[ $(declare -F main) == *" $ALT/"* && $(declare -F __bashcmdr_info) == *" $ALT/"* && $BASHCMDR_ROOT == "$ALT" ]]
''')

    def test_inherited_root_redirects_executed_cli(self):
        self.install(self.default)
        with (self.alternate / 'bin/bashcmdr').open('a') as f:
            f.write('\nprintf "alternate-entry-reached\\n"\n')
        result = self.assert_ok('BASHCMDR_ROOT_DIR="$ALT" "$DEFAULT/bin/bashcmdr" version')
        self.assertIn('alternate-entry-reached', result.stdout)
        self.assertEqual(result.stderr, '')

    def test_symlink_resolution_failure_is_bounded_and_visible(self):
        alias = self.root / 'alias'
        alias.symlink_to(self.alternate / 'bin/bashcmdr')
        result = self.assert_ok(r'''
readlink() { return 37; }
source "$LINK"
status=$?
[[ $status == 12 ]] || exit 80
! declare -F main >/dev/null
''', LINK=str(alias))
        self.assertIn('cannot resolve', result.stderr)

    def test_readlink_is_not_needed_for_an_unlinked_entry(self):
        self.assert_ok(r'''
readlink() { printf 'unexpected-readlink\n' >> "$TRACE"; return 37; }
source "$ALT/boot/shell-init.bashcmdr"
[[ $BASHCMDR_BOOT_EXIT_CODE == 0 ]] || exit 80
assert_origins "$ALT"
''')

    def test_symlink_cycle_has_a_finite_resolution_limit(self):
        (self.root / 'loop-a').symlink_to('loop-b')
        (self.root / 'loop-b').symlink_to('loop-a')
        result = self.assert_ok(r'''
source "$ALT/bin/bashcmdr"
__bashcmdr_entry_root "$LOOP"
[[ $? == 12 ]]
''', LOOP=str(self.root / 'loop-a'))
        self.assertIn('symlink loop', result.stderr)

    def test_relative_root_and_cdpath_use_physical_installation(self):
        result = self.assert_ok(r'''
CDPATH="$HOME:/"
BASHCMDR_ROOT_DIR='alternate console'
source "$ALT/boot/shell-init.bashcmdr"
[[ $BASHCMDR_ROOT_DIR == "$ALT" && $BASHCMDR_BOOT_EXIT_CODE == 0 ]] || exit 80
assert_origins "$ALT"
''')
        self.assertEqual(result.stderr, '')

    def test_matching_readonly_directory_alias_preserves_binding(self):
        alias = self.root / 'root alias'
        alias.symlink_to(self.alternate, target_is_directory=True)
        self.assert_ok(r'''
readonly BASHCMDR_ROOT_DIR="$ALIAS" BASHCMDR_ROOT="$ALIAS"
source "$ALT/boot/shell-init.bashcmdr"
[[ $BASHCMDR_ROOT_DIR == "$ALIAS" && $BASHCMDR_BOOT_EXIT_CODE == 0 ]]
''', ALIAS=str(alias))

    def test_readonly_legacy_root_conflict_is_rejected_before_firmware(self):
        self.install(self.default)
        result = self.assert_ok(r'''
BASHCMDR_ROOT_DIR="$ALT"; readonly BASHCMDR_ROOT="$DEFAULT"
source "$ALT/boot/shell-init.bashcmdr"
[[ $BASHCMDR_BOOT_EXIT_CODE == 12 && $BASHCMDR_ROOT == "$DEFAULT" ]] || exit 80
! declare -F main >/dev/null
''')
        self.assertIn('readonly BASHCMDR_ROOT conflicts', result.stderr)

    def test_missing_firmware_library_fails_boot_and_cli(self):
        (self.alternate / 'lib/registry.bashcmdr').unlink()
        result = self.assert_ok(r'''
source "$ALT/boot/shell-init.bashcmdr"
[[ $BASHCMDR_BOOT_BASIC_EXIT_CODE == 0 && $BASHCMDR_BOOT_EXIT_CODE == 11 ]]
''')
        self.assertIn('Failed to load selected console firmware', result.stderr)
        result = self.probe('"$ALT/bin/bashcmdr" version')
        self.assertEqual(result.returncode, 11, result.stdout + result.stderr)

    def test_missing_root_policy_does_not_claim_boot_success(self):
        (self.alternate / 'lib/root.bashcmdr').unlink(missing_ok=True)
        result = self.assert_ok(r'''
source "$ALT/boot/shell-init.bashcmdr"
[[ $BASHCMDR_BOOT_EXIT_CODE == 12 ]] || exit 80
! declare -F main >/dev/null
''')
        self.assertNotEqual(result.stderr, '')


if __name__ == '__main__':
    unittest.main(verbosity=2)
