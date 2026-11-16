#!/usr/bin/env python3
"""State replacement, failure reporting, relocation and integrity accounting."""
import json
import os
import pathlib
import select
import signal
import shutil
import subprocess
import tempfile
import unittest

REPO = pathlib.Path(os.environ.get('STATE_TEST_REPO', pathlib.Path(__file__).resolve().parent.parent))
STATES = ['active', 'inactive', 'broken', 'quarantine']
PREFIX = r'''
source "$TEST_CONSOLE/bin/bashcmdr"
__bashcmdr_init_state || exit $?
declare -gA BASHCMDR_CARTRIDGES_STATE=()
declare -gA BASHCMDR_DEPENDENCY_GRAPH=()
'''


class StateResultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bcm-state-results-')
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.home = self.root / 'home'
        self.console = self.home / 'console'
        self.console.mkdir(parents=True)
        for name in ['bin', 'lib', 'boot']:
            shutil.copytree(REPO / name, self.console / name)
        shutil.copyfile(REPO / 'VERSION', self.console / 'VERSION')
        cart = self.console / 'cartridges/demo'
        cart.mkdir(parents=True)
        (cart / 'manifest.json').write_text(json.dumps({'name': 'demo', 'version': '1.0.0'}))
        (cart / 'main.bashcmdr').write_text(r'''
cartridge_dispatch() { printf '%s\n' "$1" >> "$TRACE"; export STATE_HOOK=present; }
''')
        self.trace = self.root / 'hooks.log'
        self.trace.write_text('')
        self.env = {'HOME': str(self.home), 'PATH': '/usr/bin:/bin', 'TMPDIR': str(self.root),
                    'TERM': 'dumb', 'LC_ALL': 'C', 'BASHCMDR_ROOT_DIR': str(self.console),
                    'TEST_CONSOLE': str(self.console), 'TRACE': str(self.trace),
                    'BASHCMDR_VERBOSITY': '2', 'BASHCMDR_QUIET_BOOT': '1'}
        self.assert_ok(self.shell(':'))

    def shell(self, body, strict=False):
        return subprocess.run(['/bin/bash', '--noprofile', '--norc', '-c',
                               PREFIX + ('set -euo pipefail\n' if strict else '') + body],
                              cwd=self.root, env=self.env, text=True, capture_output=True, timeout=7)

    def assert_ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def seed(self, state):
        self.assert_ok(self.shell('__bashcmdr_set_cartridge_state demo ' + state))

    def links(self):
        return {s: os.readlink(self.console / 'console' / s / 'demo')
                for s in STATES if (self.console / 'console' / s / 'demo').is_symlink()}

    def assert_no_lock(self):
        self.assertFalse((self.console / 'console/.state-demo.lock').exists())

    def test_all_state_pairs_produce_one_relative_link_and_truthful_cache(self):
        for old in STATES:
            for new in STATES:
                with self.subTest(old=old, new=new):
                    self.seed(old)
                    result = self.shell('BASHCMDR_CARTRIDGES_STATE[demo]=' + old + '\n'
                                        '__bashcmdr_set_cartridge_state demo ' + new + ' || exit $?\n'
                                        '[[ ${BASHCMDR_CARTRIDGES_STATE[demo]} == ' + new + ' ]]')
                    self.assert_ok(result)
                    self.assertEqual(self.links(), {new: '../../cartridges/demo'})
                    self.assert_no_lock()

    def test_failed_link_publication_restores_every_prior_state(self):
        for old in STATES:
            with self.subTest(old=old):
                self.seed(old)
                before = self.links()
                result = self.shell('BASHCMDR_CARTRIDGES_STATE[demo]=' + old + '\n'
                                    'ln() { return 73; }\n'
                                    'if __bashcmdr_set_cartridge_state demo inactive; then exit 88; fi\n'
                                    '[[ ${BASHCMDR_CARTRIDGES_STATE[demo]} == ' + old + ' ]]')
                self.assert_ok(result)
                self.assertEqual(self.links(), before)
                self.assert_no_lock()

    def test_second_staging_failure_restores_all_original_links(self):
        self.seed('active')
        (self.console / 'console/inactive/demo').symlink_to('../../cartridges/demo')
        before = self.links()
        result = self.shell(r'''
mv() { if [[ $1 == */inactive/demo ]]; then return 73; else command mv "$@"; fi; }
__bashcmdr_set_cartridge_state demo broken
''')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.links(), before)
        self.assert_no_lock()

    def test_failed_replacement_restores_dangling_link_text_exactly(self):
        link = self.console / 'console/broken/demo'
        link.symlink_to('../missing\n')
        result = self.shell('ln() { return 73; }; __bashcmdr_set_cartridge_state demo broken')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(os.readlink(link), '../missing\n')
        self.assert_no_lock()

    def test_foreign_directory_or_file_is_preserved_before_any_removal(self):
        self.seed('active')
        target = self.console / 'console/inactive/demo'
        for kind in ['file', 'directory']:
            with self.subTest(kind=kind):
                if kind == 'file':
                    target.write_text('preserve\n')
                else:
                    target.mkdir()
                    (target / 'sentinel').write_text('preserve\n')
                before = self.links()
                result = self.shell('__bashcmdr_set_cartridge_state demo inactive')
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.links(), before)
                self.assertEqual((target if kind == 'file' else target / 'sentinel').read_text(), 'preserve\n')
                self.assert_no_lock()
                if kind == 'file': target.unlink()
                else: shutil.rmtree(target)

    def test_missing_cartridge_cannot_remove_existing_state(self):
        self.seed('active')
        shutil.rmtree(self.console / 'cartridges/demo')
        before = self.links()
        result = self.shell('__bashcmdr_set_cartridge_state demo inactive')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.links(), before)

    def test_busy_lock_is_preserved_and_prevents_change(self):
        self.seed('active')
        lock = self.console / 'console/.state-demo.lock'
        lock.mkdir()
        (lock / 'sentinel').write_text('other transaction\n')
        result = self.shell('__bashcmdr_set_cartridge_state demo inactive')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.links(), {'active': '../../cartridges/demo'})
        self.assertEqual((lock / 'sentinel').read_text(), 'other transaction\n')

    def test_two_cooperating_processes_do_not_interleave_state_changes(self):
        self.seed('active')
        first = subprocess.Popen(['/bin/bash', '--noprofile', '--norc', '-c', PREFIX + r'''
ln() { printf 'READY\n'; IFS= read -r permission || return 73; command ln "$@"; }
__bashcmdr_set_cartridge_state demo inactive
'''], cwd=self.root, env=self.env, text=True, stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        try:
            ready, _, _ = select.select([first.stdout], [], [], 3)
            self.assertTrue(ready, 'first transaction did not reach controlled publication')
            self.assertEqual(first.stdout.readline(), 'READY\n')
            second = self.shell('__bashcmdr_set_cartridge_state demo quarantine')
            self.assertNotEqual(second.returncode, 0)
            out, err = first.communicate('\n', timeout=5)
            self.assertEqual(first.returncode, 0, out + err)
            self.assertEqual(self.links(), {'inactive': '../../cartridges/demo'})
            self.assert_no_lock()
        finally:
            if first.poll() is None:
                os.killpg(first.pid, signal.SIGKILL)
                first.communicate(timeout=3)

    def test_failed_rollback_retains_backup_and_reports_recovery(self):
        self.seed('active')
        result = self.shell(r'''
mv() { if [[ $1 == */.state-demo.lock/* ]]; then return 73; else command mv "$@"; fi; }
ln() { return 73; }
__bashcmdr_set_cartridge_state demo inactive
''')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('State transaction needs recovery at:', result.stderr)
        self.assertIn('committed=0', result.stderr)
        backup = self.console / 'console/.state-demo.lock/active'
        self.assertTrue(backup.is_symlink())
        self.assertEqual(os.readlink(backup), '../../cartridges/demo')

    def test_post_commit_cleanup_failure_reports_applied_state_and_retains_lock(self):
        self.seed('active')
        result = self.shell(r'''
BASHCMDR_CARTRIDGES_STATE[demo]=active
rmdir() { return 73; }
if __bashcmdr_set_cartridge_state demo inactive; then exit 88; fi
[[ ${BASHCMDR_CARTRIDGES_STATE[demo]} == inactive ]]
''')
        self.assert_ok(result)
        self.assertEqual(self.links(), {'inactive': '../../cartridges/demo'})
        self.assertIn('committed=1', result.stderr)
        self.assertTrue((self.console / 'console/.state-demo.lock').is_dir())

    def test_term_rolls_back_before_releasing_lock(self):
        self.seed('active')
        result = self.shell('ln() { kill -TERM "$BASHPID"; }; __bashcmdr_set_cartridge_state demo inactive')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.links(), {'active': '../../cartridges/demo'})
        self.assert_no_lock()

    def test_callers_traps_and_cleanup_function_are_preserved(self):
        self.seed('active')
        result = self.shell(r'''
__bashcmdr_finish_state_transaction() { printf 'ambient\n'; }
trap ':' EXIT INT TERM
before=$(trap -p EXIT INT TERM)
binding=$(declare -f __bashcmdr_finish_state_transaction)
__bashcmdr_set_cartridge_state demo inactive || exit $?
[[ $(trap -p EXIT INT TERM) == "$before" && $(declare -f __bashcmdr_finish_state_transaction) == "$binding" ]]
''', strict=True)
        self.assert_ok(result)

    def test_readonly_cleanup_binding_fails_before_state_change(self):
        self.seed('active')
        result = self.shell('__bashcmdr_finish_state_transaction() { :; }\n'
                            'readonly -f __bashcmdr_finish_state_transaction\n'
                            '__bashcmdr_set_cartridge_state demo inactive')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.links(), {'active': '../../cartridges/demo'})
        self.assert_no_lock()

    def test_wrappers_propagate_failed_transition_without_success_messages(self):
        for action, old, hooks in [('plug', 'inactive', []), ('unplug', 'active', ['deactivate']),
                                   ('quarantine', 'inactive', []), ('release', 'quarantine', [])]:
            with self.subTest(action=action):
                self.seed(old)
                self.trace.write_text('')
                result = self.shell('BASHCMDR_CARTRIDGES_STATE[demo]=' + old + '\n'
                                    '__bashcmdr_set_cartridge_state() { return 73; }\n'
                                    'bashcmdr_' + action + '_cartridge demo')
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('Successfully', result.stdout)
                self.assertNotIn('Cartridge quarantined:', result.stdout)
                self.assertNotIn('Cartridge released:', result.stdout)
                self.assertEqual(self.trace.read_text().splitlines(), hooks)
                self.assertFalse((self.console / 'logs/quarantine/demo.log').exists())

    def test_failed_reason_log_reports_partial_quarantine(self):
        self.seed('inactive')
        (self.console / 'logs/quarantine/demo.log').mkdir(parents=True)
        result = self.shell('bashcmdr_quarantine_cartridge demo fixture-reason')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.links(), {'quarantine': '../../cartridges/demo'})
        self.assertIn('is quarantined, but its reason could not be logged', result.stderr)
        self.assertNotIn('Cartridge quarantined:', result.stdout)

    def test_documented_broken_recovery_and_reason_data(self):
        self.seed('broken')
        result = self.shell(r'''
BASHCMDR_CARTRIDGES_STATE[demo]=broken
bashcmdr_quarantine_cartridge demo 'repair\reason' || exit $?
bashcmdr_release_cartridge demo || exit $?
bashcmdr_plug_cartridge demo || exit $?
[[ ${BASHCMDR_CARTRIDGES_STATE[demo]} == active && $STATE_HOOK == present ]]
''')
        self.assert_ok(result)
        self.assertEqual(self.links(), {'active': '../../cartridges/demo'})
        self.assertIn(r'repair\reason', (self.console / 'logs/quarantine/demo.log').read_text())

    def test_new_discovery_links_survive_root_relocation(self):
        self.assert_ok(self.shell('__bashcmdr_sync_physical_state'))
        self.assertEqual(self.links(), {'inactive': '../../cartridges/demo'})
        moved = self.home / 'moved console'
        self.console.rename(moved)
        link = moved / 'console/inactive/demo'
        self.assertTrue(link.resolve().samefile(moved / 'cartridges/demo'))

    def test_failed_discovery_does_not_claim_inactive(self):
        result = self.shell('ln() { return 73; }\n'
                            'if __bashcmdr_sync_physical_state; then exit 88; fi\n'
                            '[[ ! ${BASHCMDR_CARTRIDGES_STATE[demo]-} ]]')
        self.assert_ok(result)
        self.assertEqual(self.links(), {})

    def test_missing_discovery_directory_retains_logical_state(self):
        result = self.shell('mv "$BASHCMDR_ROOT/cartridges" "$HOME/cartridges-away"\n'
                            'BASHCMDR_CARTRIDGES_STATE[demo]=active\n'
                            'if __bashcmdr_sync_physical_state; then exit 88; fi\n'
                            '[[ ${BASHCMDR_CARTRIDGES_STATE[demo]} == active ]]')
        self.assert_ok(result)

    def test_registry_status_includes_broken(self):
        self.seed('broken')
        result = self.shell('bashcmdr_save_cartridge_metadata demo >/dev/null || exit $?\n'
                            'bashcmdr_get_cartridge_status demo')
        self.assert_ok(result)
        self.assertEqual(result.stdout, 'broken\n')

    def test_doctor_reports_real_orphan_then_clean_followup(self):
        (self.console / 'console/active/orphan').symlink_to('../../cartridges/absent')
        first = self.shell('bashcmdr_doctor_check')
        self.assertEqual(first.returncode, 1)
        self.assertIn('Found 1 integrity issues;', first.stderr)
        self.assertFalse((self.console / 'console/active/orphan').is_symlink())
        second = self.shell('bashcmdr_doctor_check')
        self.assert_ok(second)
        self.assertIn('System integrity verified', second.stdout)

    def test_doctor_moves_mispointed_existing_cartridge_to_broken(self):
        (self.console / 'console/active/demo').symlink_to('../missing')
        result = self.shell('bashcmdr_doctor_check')
        self.assertEqual(result.returncode, 1)
        self.assertIn('Found 1 integrity issues;', result.stderr)
        self.assertEqual(self.links(), {'broken': '../../cartridges/demo'})

    def test_exclusivity_counts_and_precedence_use_all_original_states(self):
        for states, winner in [(STATES, 'quarantine'), (['inactive', 'broken', 'quarantine'], 'quarantine')]:
            with self.subTest(states=states):
                for state in STATES:
                    link = self.console / 'console' / state / 'demo'
                    if link.is_symlink(): link.unlink()
                    if state in states: link.symlink_to('../../cartridges/demo')
                result = self.shell('bashcmdr_doctor_check')
                self.assertEqual(result.returncode, 1)
                self.assertIn('Found ' + str(len(states) - 1) + ' integrity issues;', result.stderr)
                self.assertEqual(self.links(), {winner: '../../cartridges/demo'})
                self.assert_no_lock()

    def test_counts_over_255_are_preserved_without_zero_status_wrap(self):
        for mode in ['helper', 'doctor']:
            for index in range(257):
                (self.console / 'console/active' / ('orphan-' + str(index))).symlink_to('../../absent')
            if mode == 'helper':
                result = self.shell('count=0\nif __bashcmdr_validate_symlinks active count; then status=0; else status=$?; fi\n'
                                    'printf "COUNT:%s STATUS:%s\\n" "$count" "$status"')
                self.assert_ok(result)
                self.assertIn('COUNT:257 STATUS:255', result.stdout)
            else:
                result = self.shell('bashcmdr_doctor_check')
                self.assertEqual(result.returncode, 1)
                self.assertIn('Found 257 integrity issues;', result.stderr)

    def test_doctor_preserves_failure_when_repair_is_denied(self):
        (self.console / 'console/active/orphan').symlink_to('../../absent')
        result = self.shell('rm() { return 73; }; bashcmdr_doctor_check')
        self.assertEqual(result.returncode, 1)
        self.assertIn('Could not remove orphaned link:', result.stderr)
        self.assertNotIn('auto-repaired', result.stderr)
        self.assertTrue((self.console / 'console/active/orphan').is_symlink())

    def test_doctor_cli_preserves_integrity_failure_after_summary(self):
        result = self.shell('bashcmdr_doctor_check() { return 1; }; doctor_cmd')
        self.assertEqual(result.returncode, 1)
        self.assertIn('System integrity issues detected', result.stdout)

    def test_clean_doctor_works_in_strict_shell(self):
        self.assert_ok(self.shell('bashcmdr_doctor_check', strict=True))


if __name__ == '__main__':
    unittest.main(verbosity=2)
