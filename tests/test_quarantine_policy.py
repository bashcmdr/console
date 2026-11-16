#!/usr/bin/env python3
"""Quarantine survives boot, plug, repair and non-release lifecycle actions."""
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

REPO = pathlib.Path(os.environ.get('QUARANTINE_TEST_REPO', pathlib.Path(__file__).resolve().parent.parent))
ESSENTIALS = ['pyenv-loader', 'nvm-loader', 'fabric-loader']
STATES = ['active', 'inactive', 'broken', 'quarantine']
PREFIX = r'''
source "$TEST_CONSOLE/bin/bashcmdr"
__bashcmdr_init_state || exit $?
declare -gA BASHCMDR_CARTRIDGES_STATE=()
'''


class QuarantinePolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bcm-quarantine-')
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.home = self.root / 'home'
        self.console = self.home / 'console'
        self.console.mkdir(parents=True)
        for part in ['bin', 'lib', 'boot']:
            shutil.copytree(REPO / part, self.console / part)
        shutil.copyfile(REPO / 'VERSION', self.console / 'VERSION')
        self.trace = self.root / 'hooks.log'
        self.trace.write_text('')
        self.env = {'HOME': str(self.home), 'TEST_CONSOLE': str(self.console),
                    'BASHCMDR_ROOT_DIR': str(self.console), 'TRACE': str(self.trace),
                    'PATH': '/usr/bin:/bin', 'TMPDIR': str(self.root), 'TERM': 'dumb',
                    'LC_ALL': 'C', 'BASHCMDR_VERBOSITY': '1', 'BASHCMDR_QUIET_BOOT': '1'}
        self.assert_ok(self.shell(':'))

    def cartridge(self, name, deps=None):
        cart = self.console / 'cartridges' / name
        # Importing the CLI no longer creates package directories implicitly.
        cart.mkdir(parents=True, exist_ok=True)
        (cart / 'manifest.json').write_text(json.dumps({'name': name, 'version': '1.0.0',
            'requires': {'cartridges': dict.fromkeys(deps or [], '>=1.0.0')}}))
        (cart / 'main.bashcmdr').write_text('printf "SOURCE:' + name + '\\n" >> "$TRACE"\n'
            'cartridge_dispatch() { printf "' + name + ':%s\\n" "$1" >> "$TRACE"; }\n')

    def shell(self, body, strict=False):
        return subprocess.run(['/bin/bash', '--noprofile', '--norc', '-c', PREFIX +
                               ('set -euo pipefail\n' if strict else '') + body],
                              cwd=self.root, env=self.env, capture_output=True, text=True, timeout=7)

    def assert_ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def state(self, name, state):
        self.assert_ok(self.shell('__bashcmdr_set_cartridge_state ' + name + ' ' + state))

    def links(self, name):
        return {state: os.readlink(self.console / 'console' / state / name)
                for state in STATES if (self.console / 'console' / state / name).is_symlink()}

    def test_boot_essentials_stay_dormant_unless_explicitly_active(self):
        for name in ESSENTIALS:
            self.cartridge(name)
        for state in ['inactive', 'broken', 'quarantine', 'untracked']:
            with self.subTest(state=state):
                for name in ESSENTIALS:
                    for directory in STATES:
                        link = self.console / 'console' / directory / name
                        if link.is_symlink(): link.unlink()
                    if state != 'untracked': self.state(name, state)
                self.trace.write_text('')
                before = {name: self.links(name) for name in ESSENTIALS}
                self.assert_ok(self.shell('console_poweron'))
                self.assertEqual(self.trace.read_text(), '')
                self.assertEqual({name: self.links(name) for name in ESSENTIALS}, before)

    def test_boot_active_essentials_and_generic_are_allowed(self):
        for name in ESSENTIALS + ['demo']:
            self.cartridge(name)
            self.state(name, 'active')
        self.assert_ok(self.shell('console_poweron'))
        self.assertEqual(self.trace.read_text().splitlines(),
            [line for name in ESSENTIALS + ['demo'] for line in ['SOURCE:' + name, name + ':activate']])

    def test_boot_quarantine_wins_over_duplicate_active_flags(self):
        for name in ['pyenv-loader', 'demo']:
            self.cartridge(name)
            self.state(name, 'quarantine')
            (self.console / 'console/active' / name).symlink_to('../../cartridges/' + name)
        self.assert_ok(self.shell('console_poweron'))
        self.assertEqual(self.trace.read_text(), '')
        for name in ['pyenv-loader', 'demo']:
            self.assertIn('quarantine', self.links(name))

    def test_explicit_plug_quarantine_is_denied_at_all_verbosity_levels(self):
        self.cartridge('demo')
        self.state('demo', 'quarantine')
        for level in range(4):
            with self.subTest(verbosity=level):
                self.env['BASHCMDR_VERBOSITY'] = str(level)
                result = self.shell('bashcmdr_plug_cartridge demo')
                self.assertEqual(result.returncode, 1)
                self.assertEqual(self.trace.read_text(), '')
                self.assertEqual(self.links('demo'), {'quarantine': '../../cartridges/demo'})
                if level: self.assertIn('is quarantined', result.stderr)
                else: self.assertEqual(result.stderr, '')

    def chain(self):
        self.cartridge('dep')
        self.cartridge('middle', ['dep'])
        self.cartridge('app', ['middle'])
        self.state('dep', 'quarantine')
        self.state('middle', 'inactive')
        self.state('app', 'inactive')

    def test_plug_checks_all_transitive_dependencies_before_any_effect(self):
        self.chain()
        before = {name: self.links(name) for name in ['dep', 'middle', 'app']}
        result = self.shell('bashcmdr_plug_cartridge app')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.trace.read_text(), '')
        self.assertEqual({name: self.links(name) for name in before}, before)

    def test_boot_blocks_target_with_quarantined_dependency(self):
        self.chain()
        self.state('app', 'active')
        self.assertEqual(self.shell('console_poweron').returncode, 1)
        self.assertEqual(self.trace.read_text(), '')
        self.assertIn('is quarantined', (self.console / 'logs/console-poweron.log').read_text())

    def test_shared_activation_boundary_blocks_source_for_target_and_dependency(self):
        self.chain()
        for target in ['dep', 'app']:
            with self.subTest(target=target):
                result = self.shell('__bashcmdr_cartridge_call ' + target + ' activate')
                self.assertEqual(result.returncode, 1)
                self.assertEqual(self.trace.read_text(), '')

    def test_diagnose_help_and_deactivate_remain_available(self):
        self.cartridge('demo')
        self.state('demo', 'quarantine')
        for action in ['diagnose', 'help', 'deactivate']:
            self.assert_ok(self.shell('__bashcmdr_cartridge_call demo ' + action))
        self.assertEqual(self.trace.read_text().splitlines(),
                         [line for action in ['diagnose', 'help', 'deactivate']
                          for line in ['SOURCE:demo', 'demo:' + action]])

    def test_explicit_release_allows_dependency_and_target_activation(self):
        self.chain()
        result = self.shell('bashcmdr_release_cartridge dep || exit $?\nbashcmdr_plug_cartridge app')
        self.assert_ok(result)
        self.assertEqual([x for x in self.trace.read_text().splitlines() if not x.startswith('SOURCE:')],
                         ['dep:activate', 'middle:activate', 'app:activate'])

    def test_unplug_preserves_quarantine(self):
        self.cartridge('demo')
        self.state('demo', 'quarantine')
        self.assert_ok(self.shell('bashcmdr_unplug_cartridge demo'))
        self.assertEqual(self.links('demo'), {'quarantine': '../../cartridges/demo'})
        self.assertEqual(self.shell('bashcmdr_plug_cartridge demo').returncode, 1)
        self.assertNotIn('demo:activate', self.trace.read_text())

    def test_reset_does_not_release_or_activate_quarantined_essential(self):
        self.cartridge('pyenv-loader')
        self.state('pyenv-loader', 'quarantine')
        self.assert_ok(self.shell('__bashcmdr_sync_physical_state || exit $?\nconsole_reset'))
        self.assertEqual(self.trace.read_text(), '')
        self.assertEqual(self.links('pyenv-loader'), {'quarantine': '../../cartridges/pyenv-loader'})

    def test_doctor_preserves_quarantine_precedence_and_status(self):
        self.cartridge('demo')
        self.state('demo', 'quarantine')
        (self.console / 'console/active/demo').symlink_to('../../cartridges/demo')
        result = self.shell('bashcmdr_doctor_check')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.links('demo'), {'quarantine': '../../cartridges/demo'})
        self.assertEqual(self.trace.read_text(), '')
        self.assert_ok(self.shell('bashcmdr_save_cartridge_metadata demo >/dev/null || exit $?\n'
                                  '[[ $(bashcmdr_get_cartridge_status demo) == quarantine ]]'))

    def test_doctor_repairs_bad_quarantine_link_without_releasing(self):
        self.cartridge('demo')
        (self.console / 'console/quarantine/demo').symlink_to('../wrong')
        result = self.shell('bashcmdr_doctor_check')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.links('demo'), {'quarantine': '../../cartridges/demo'})
        self.assertEqual(self.shell('bashcmdr_plug_cartridge demo').returncode, 1)

    def test_orphan_quarantine_is_retained_until_explicit_release(self):
        self.cartridge('demo')
        self.state('demo', 'quarantine')
        shutil.rmtree(self.console / 'cartridges/demo')
        result = self.shell('bashcmdr_doctor_check')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.links('demo'), {'quarantine': '../../cartridges/demo'})
        self.assert_ok(self.shell('bashcmdr_release_cartridge demo'))
        self.assertEqual(self.links('demo'), {})
        self.cartridge('demo')
        self.assert_ok(self.shell('bashcmdr_plug_cartridge demo'))

    def test_stale_cache_does_not_override_physical_quarantine_or_release(self):
        self.cartridge('demo')
        self.state('demo', 'quarantine')
        result = self.shell('BASHCMDR_CARTRIDGES_STATE[demo]=active\nbashcmdr_plug_cartridge demo')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.trace.read_text(), '')
        self.state('demo', 'inactive')
        result = self.shell('BASHCMDR_CARTRIDGES_STATE[demo]=quarantine\nbashcmdr_plug_cartridge demo')
        self.assert_ok(result)

    def test_empty_constraint_cannot_hide_declared_quarantined_dependency(self):
        self.chain()
        manifest = self.console / 'cartridges/app/manifest.json'
        data = json.loads(manifest.read_text())
        data['requires']['cartridges'] = {'dep': ''}
        manifest.write_text(json.dumps(data))
        self.assertEqual(self.shell('bashcmdr_plug_cartridge app').returncode, 1)
        self.assertEqual(self.trace.read_text(), '')

    def test_dependency_cycle_does_not_hide_quarantine_or_loop(self):
        self.chain()
        manifest = self.console / 'cartridges/dep/manifest.json'
        data = json.loads(manifest.read_text())
        data['requires']['cartridges'] = {'app': '>=1.0.0'}
        manifest.write_text(json.dumps(data))
        self.assertEqual(self.shell('__bashcmdr_cartridge_call app activate').returncode, 1)
        self.assertEqual(self.trace.read_text(), '')

    def test_bad_or_missing_dependency_metadata_fails_before_source(self):
        self.cartridge('demo')
        manifest = self.console / 'cartridges/demo/manifest.json'
        for value in ['{', '[]', '{"requires":{"cartridges":false}}',
                      '{"requires":{"cartridges":[]}}', '{"requires":{"cartridges":{"bad name":""}}}',
                      '{"requires":{"cartridges":{"demo\\n":""}}}']:
            with self.subTest(value=value):
                manifest.write_text(value)
                self.assertEqual(self.shell('__bashcmdr_cartridge_call demo activate').returncode, 1)
                self.assertEqual(self.trace.read_text(), '')
        manifest.unlink()
        self.assertEqual(self.shell('__bashcmdr_cartridge_call demo activate').returncode, 1)
        self.assertEqual(self.trace.read_text(), '')

    def test_failed_jq_check_cannot_silently_allow_activation(self):
        self.cartridge('demo')
        result = self.shell('jq() { return 127; }; __bashcmdr_cartridge_call demo activate')
        self.assertEqual(result.returncode, 1)
        self.assertIn('refusing activation', result.stderr)
        self.assertEqual(self.trace.read_text(), '')

    def test_rollback_does_not_clear_a_new_quarantine_marker(self):
        self.cartridge('dep')
        self.cartridge('app', ['dep'])
        self.state('dep', 'inactive')
        self.state('app', 'inactive')
        (self.console / 'cartridges/app/main.bashcmdr').write_text(r'''
cartridge_dispatch() {
    __bashcmdr_set_cartridge_state app quarantine || return $?
    return 41
}
''')
        result = self.shell('bashcmdr_plug_cartridge app')
        self.assertEqual(result.returncode, 1)
        self.assertIn('Quarantine retained during rollback', result.stderr)
        self.assertEqual(self.links('app'), {'quarantine': '../../cartridges/app'})
        self.assertEqual(self.links('dep'), {'inactive': '../../cartridges/dep'})

    def test_direct_cli_denies_quarantined_target(self):
        self.cartridge('demo')
        self.state('demo', 'quarantine')
        result = subprocess.run(['/bin/bash', '--noprofile', '--norc', str(self.console / 'bin/bashcmdr'),
                                 'cartridge', 'plug', 'demo'], cwd=self.root, env=self.env,
                                capture_output=True, text=True, timeout=7)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.trace.read_text(), '')


if __name__ == '__main__':
    unittest.main(verbosity=2)
