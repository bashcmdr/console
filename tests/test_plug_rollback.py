#!/usr/bin/env python3
"""Failed plugs reverse only successful activations owned by that attempt."""
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

REPO = pathlib.Path(os.environ.get('ROLLBACK_TEST_REPO', pathlib.Path(__file__).resolve().parent.parent))
NAMES = ['dep1', 'dep2', 'app']
STATES = ['active', 'inactive', 'broken', 'quarantine']
PREFIX = r'''
source "$TEST_CONSOLE/bin/bashcmdr"
__bashcmdr_init_state || exit $?
declare -gA BASHCMDR_CARTRIDGES_STATE=()
'''
FOOTER = r'''
if bashcmdr_plug_cartridge app; then plug_status=0; else plug_status=$?; fi
for name in dep1 dep2 app; do printf 'CACHE:%s=%s\n' "$name" "${BASHCMDR_CARTRIDGES_STATE[$name]-untracked}"; done
exit "$plug_status"
'''


class PlugRollbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bcm-plug-rollback-')
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.home = self.root / 'home'
        self.console = self.home / 'console'
        self.console.mkdir(parents=True)
        for name in ['bin', 'lib', 'boot']:
            shutil.copytree(REPO / name, self.console / name)
        shutil.copyfile(REPO / 'VERSION', self.console / 'VERSION')
        for index, name in enumerate(NAMES):
            path = self.console / 'cartridges' / name
            path.mkdir(parents=True)
            (path / 'manifest.json').write_text(json.dumps({'name': name, 'version': '1.0.0',
                'requires': {'cartridges': {NAMES[index - 1]: '>=1.0.0'} if index else {}}}))
            dependency = ('[[ ${READY_' + NAMES[index - 1] + '-} == yes ]] || return 67\n') if index else ''
            (path / 'main.bashcmdr').write_text('cartridge_dispatch() {\n'
                'printf "' + name + ':%s\\n" "$1" >> "$TRACE"\n'
                'case "$1" in\nactivate)\n' + dependency +
                'if [[ ${FAIL_CART-} == ' + name + ' ]]; then printf "fixture-activate-failed\\n" >&2; return 41; fi\n'
                'export READY_' + name + '=yes ;;\n'
                'deactivate) if [[ ${FAIL_DEACTIVATE-} == ' + name + ' ]]; then return 73; fi\n'
                'unset READY_' + name + ' ;;\nesac\n}\n')
        self.trace = self.root / 'hooks.log'
        self.trace.write_text('')

    def probe(self, initial=None, extra='', fail='app', verbosity=1, direct=False, footer=FOOTER,
              allow_recovery=False):
        initial = initial or dict.fromkeys(NAMES, 'inactive')
        for state in STATES:
            parent = self.console / 'console' / state
            if parent.exists():
                for entry in parent.iterdir():
                    if entry.is_symlink(): entry.unlink()
        self.trace.write_text('')
        setup = ''.join('__bashcmdr_set_cartridge_state ' + name + ' ' + state + ' || exit $?\n'
                        for name, state in initial.items() if state != 'untracked')
        env = {'HOME': str(self.home), 'PATH': '/usr/bin:/bin', 'TMPDIR': str(self.root),
               'TERM': 'dumb', 'LC_ALL': 'C', 'TEST_CONSOLE': str(self.console),
               'BASHCMDR_ROOT_DIR': str(self.console), 'BASHCMDR_VERBOSITY': str(verbosity),
               'BASHCMDR_QUIET_BOOT': '1', 'TRACE': str(self.trace), 'FAIL_CART': fail}
        if direct:
            seed = subprocess.run(['/bin/bash', '--noprofile', '--norc', '-c', PREFIX + setup],
                                  cwd=self.root, env=env, capture_output=True, text=True, timeout=7)
            self.assertEqual(seed.returncode, 0, seed.stderr)
            argv = ['/bin/bash', '--noprofile', '--norc', str(self.console / 'bin/bashcmdr'),
                    'cartridge', 'plug', 'app']
        else:
            argv = ['/bin/bash', '--noprofile', '--norc', '-c', PREFIX + setup + extra + '\n' + footer]
        result = subprocess.run(argv, cwd=self.root, env=env, capture_output=True, text=True, timeout=7)
        if not allow_recovery:
            self.assertFalse(list((self.console / 'console').glob('.state-*.lock')),
                             'transaction lock unexpectedly retained')
        return result

    def memberships(self):
        return {name: {s: os.readlink(self.console / 'console' / s / name)
                       for s in STATES if (self.console / 'console' / s / name).is_symlink()}
                for name in NAMES}

    def expected(self, states):
        return {name: {} if states[name] == 'untracked' else
                {states[name]: '../../cartridges/' + name} for name in NAMES}

    def assert_restored(self, result, initial):
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(self.memberships(), self.expected(initial))
        for name, state in initial.items():
            self.assertIn('CACHE:' + name + '=' + state, result.stdout)
        self.assertNotIn('Successfully plugged', result.stdout)

    def test_hook_failure_preserves_prior_states_at_every_verbosity(self):
        for previous in ['inactive', 'active']:
            for verbosity in range(4):
                with self.subTest(previous=previous, verbosity=verbosity):
                    initial = {'dep1': previous, 'dep2': 'inactive', 'app': 'inactive'}
                    result = self.probe(initial, verbosity=verbosity)
                    self.assert_restored(result, initial)
                    self.assertEqual(self.trace.read_text().splitlines(),
                        ['dep1:activate', 'dep2:activate', 'app:activate', 'dep2:deactivate'] +
                        (['dep1:deactivate'] if previous == 'inactive' else []))

    def test_state_write_failure_rolls_back_only_completed_owned_hooks(self):
        for failed in ['dep2', 'app']:
            for previous in ['inactive', 'active']:
                with self.subTest(failed=failed, previous=previous):
                    initial = {'dep1': previous, 'dep2': 'inactive', 'app': 'inactive'}
                    extra = ('ln() { if [[ ${3-} == */active/' + failed +
                             ' ]]; then return 73; else command ln "$@"; fi; }')
                    result = self.probe(initial, extra=extra, fail='')
                    self.assert_restored(result, initial)
                    expected = ['dep1:activate'] + (['dep2:activate', 'dep2:deactivate'] if failed == 'app' else [])
                    if previous == 'inactive': expected.append('dep1:deactivate')
                    self.assertEqual(self.trace.read_text().splitlines(), expected)

    def test_first_state_write_failure_runs_no_hook(self):
        initial = dict.fromkeys(NAMES, 'inactive')
        result = self.probe(initial, extra=r'''
ln() { if [[ ${3-} == */active/dep1 ]]; then return 73; else command ln "$@"; fi; }
''', fail='')
        self.assert_restored(result, initial)
        self.assertEqual(self.trace.read_text(), '')

    def test_committed_state_cleanup_failure_is_reported_and_prior_cleanup_continues(self):
        result = self.probe(extra=r'''
rmdir() { if [[ $1 == */.state-app.lock ]]; then return 73; else command rmdir "$@"; fi; }
''', fail='', allow_recovery=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('committed=1', result.stderr)
        self.assertIn('Could not restore failed state write for: app', result.stderr)
        self.assertEqual(self.memberships(), self.expected({'dep1': 'inactive', 'dep2': 'inactive', 'app': 'active'}))
        self.assertTrue((self.console / 'console/.state-app.lock').is_dir())
        self.assertNotIn('app:activate', self.trace.read_text())

    def test_success_keeps_existing_dependencies_loaded_for_fresh_context(self):
        for previous in ['active', 'inactive', 'untracked']:
            with self.subTest(previous=previous):
                initial = {'dep1': previous, 'dep2': previous, 'app': 'inactive'}
                result = self.probe(initial, fail='')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.memberships(), self.expected(dict.fromkeys(NAMES, 'active')))
                self.assertEqual(self.trace.read_text().splitlines(), [x + ':activate' for x in NAMES])

    def test_all_preexisting_active_states_survive_failed_context_refresh(self):
        initial = dict.fromkeys(NAMES, 'active')
        result = self.probe(initial)
        self.assert_restored(result, initial)
        self.assertEqual(self.trace.read_text().splitlines(), [x + ':activate' for x in NAMES])

    def test_physical_snapshot_overrides_stale_cache_in_both_directions(self):
        for actual, stale in [('active', 'inactive'), ('inactive', 'active')]:
            with self.subTest(actual=actual):
                initial = {'dep1': actual, 'dep2': 'inactive', 'app': 'inactive'}
                result = self.probe(initial, extra='BASHCMDR_CARTRIDGES_STATE[dep1]=' + stale)
                self.assert_restored(result, initial)
                self.assertEqual('dep1:deactivate' in self.trace.read_text(), actual == 'inactive')

    def test_untracked_states_are_restored_without_inventing_inactive_links(self):
        initial = dict.fromkeys(NAMES, 'untracked')
        result = self.probe(initial)
        self.assert_restored(result, initial)

    def test_prior_broken_state_is_restored_for_dependency_and_failed_target(self):
        initial = {'dep1': 'inactive', 'dep2': 'broken', 'app': 'broken'}
        result = self.probe(initial)
        self.assert_restored(result, initial)

    def test_failed_hook_gets_no_deactivate_call(self):
        result = self.probe(fail='dep2')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(self.trace.read_text().splitlines(), ['dep1:activate', 'dep2:activate', 'dep1:deactivate'])
        self.assertEqual(self.memberships(), self.expected(dict.fromkeys(NAMES, 'inactive')))

    def test_load_failure_restores_state_and_earlier_owned_activations(self):
        (self.console / 'cartridges/app/main.bashcmdr').write_text('return 61\n')
        initial = dict.fromkeys(NAMES, 'inactive')
        result = self.probe(initial)
        self.assert_restored(result, initial)
        self.assertIn('Failed to load cartridge', result.stderr)
        self.assertEqual(self.trace.read_text().splitlines(),
                         ['dep1:activate', 'dep2:activate', 'dep2:deactivate', 'dep1:deactivate'])

    def test_deactivation_failure_stays_visible_and_cleanup_continues(self):
        initial = dict.fromkeys(NAMES, 'inactive')
        result = self.probe(initial, extra='export FAIL_DEACTIVATE=dep2')
        self.assert_restored(result, initial)
        self.assertIn('Rollback deactivation failed for: dep2', result.stderr)
        self.assertIn('Plug rollback was incomplete', result.stderr)
        self.assertEqual(self.trace.read_text().splitlines()[-2:], ['dep2:deactivate', 'dep1:deactivate'])

    def test_state_restoration_failure_is_reported_and_other_cleanup_continues(self):
        result = self.probe(extra=r'''
ln() { if [[ ${3-} == */inactive/dep2 ]]; then return 73; else command ln "$@"; fi; }
''')
        self.assertEqual(result.returncode, 1)
        self.assertIn('Rollback state restoration failed for: dep2', result.stderr)
        self.assertIn('Plug rollback was incomplete', result.stderr)
        self.assertEqual(self.memberships(), self.expected({'dep1': 'inactive', 'dep2': 'active', 'app': 'inactive'}))
        self.assertIn('CACHE:dep2=active', result.stdout)

    def test_failed_target_restoration_is_reported_without_skipping_prior_cleanup(self):
        result = self.probe(extra=r'''
ln() { if [[ ${3-} == */inactive/app ]]; then return 73; else command ln "$@"; fi; }
''')
        self.assertEqual(result.returncode, 1)
        self.assertIn('Could not restore state after failed hook: app', result.stderr)
        self.assertEqual(self.memberships(), self.expected({'dep1': 'inactive', 'dep2': 'inactive', 'app': 'active'}))

    def test_duplicate_plan_is_rejected_before_effects(self):
        result = self.probe(extra="bashcmdr_get_activation_plan() { printf '%s\\n' dep1 dep1 app; }")
        self.assertEqual(result.returncode, 1)
        self.assertIn('Duplicate cartridge', result.stderr)
        self.assertEqual(self.trace.read_text(), '')
        self.assertEqual(self.memberships(), self.expected(dict.fromkeys(NAMES, 'inactive')))

    def test_ambiguous_state_is_rejected_before_any_hook(self):
        result = self.probe(extra='ln -s ../../cartridges/dep2 "$BASHCMDR_ROOT/console/broken/dep2"')
        self.assertEqual(result.returncode, 1)
        self.assertIn('Ambiguous state', result.stderr)
        self.assertEqual(self.trace.read_text(), '')
        self.assertEqual(set(self.memberships()['dep2']), {'inactive', 'broken'})

    def test_foreign_state_entry_is_rejected_before_any_hook(self):
        result = self.probe(extra='printf preserve > "$BASHCMDR_ROOT/console/broken/dep2"')
        self.assertEqual(result.returncode, 1)
        self.assertIn('Non-symlink state entry', result.stderr)
        self.assertEqual(self.trace.read_text(), '')
        self.assertEqual((self.console / 'console/broken/dep2').read_text(), 'preserve')

    def test_direct_cli_preserves_already_active_dependency(self):
        initial = {'dep1': 'active', 'dep2': 'inactive', 'app': 'inactive'}
        result = self.probe(initial, direct=True)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(self.memberships(), self.expected(initial))
        self.assertNotIn('dep1:deactivate', self.trace.read_text())

    def test_strict_shell_and_caller_loop_index_are_preserved(self):
        initial = dict.fromkeys(NAMES, 'inactive')
        result = self.probe(initial, extra='set -euo pipefail\ni=47', footer=r'''
if bashcmdr_plug_cartridge app; then exit 88; fi
[[ $i == 47 ]] || exit 89
exit 1
''')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(self.memberships(), self.expected(initial))


if __name__ == '__main__':
    unittest.main(verbosity=2)
