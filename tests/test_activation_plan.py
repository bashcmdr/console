#!/usr/bin/env python3
"""Activation-plan streams/status and pre-activation failure in owned fixtures."""
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

REPO = pathlib.Path(os.environ.get('PLAN_TEST_REPO', pathlib.Path(__file__).resolve().parent.parent))
PREFIX = r'''
source "$TEST_CONSOLE/bin/bashcmdr"
'''


class ActivationPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bcm-plan-')
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.home = self.root / 'home'
        self.console = self.home / 'console'
        self.console.mkdir(parents=True)
        for name in ['bin', 'lib', 'boot']:
            shutil.copytree(REPO / name, self.console / name)
        shutil.copyfile(REPO / 'VERSION', self.console / 'VERSION')
        (self.console / 'cartridges').mkdir()
        for state in ['active', 'inactive', 'quarantine', 'broken']:
            (self.console / 'console' / state).mkdir(parents=True)
        self.trace = self.root / 'hooks.log'
        self.trace.write_text('')

    def cartridge(self, name, deps=None):
        directory = self.console / 'cartridges' / name
        directory.mkdir()
        (directory / 'manifest.json').write_text(json.dumps({
            'name': name, 'version': '1.0.0',
            'requires': {'cartridges': dict.fromkeys(deps or [], '>=1.0.0')}}))
        (directory / 'main.bashcmdr').write_text(r'''
cartridge_dispatch() {
    printf '%s:%s\n' "${BASH_SOURCE[0]%/main.bashcmdr}" "$1" >> "$TRACE"
    export PLAN_HOOK_PERSIST=present
}
''')
        (self.console / 'console/inactive' / name).symlink_to('../../cartridges/' + name)

    def shell(self, body, verbosity=1, strict=False, direct=False):
        env = {'HOME': str(self.home), 'PATH': '/usr/bin:/bin', 'TMPDIR': str(self.root),
               'TERM': 'dumb', 'LC_ALL': 'C', 'TRACE': str(self.trace),
               'BASHCMDR_ROOT_DIR': str(self.console), 'TEST_CONSOLE': str(self.console),
               'BASHCMDR_VERBOSITY': str(verbosity), 'BASHCMDR_QUIET_BOOT': '1'}
        if direct:
            argv = ['/bin/bash', '--noprofile', '--norc', str(self.console / 'bin/bashcmdr'),
                    'cartridge', 'plug', 'app']
        else:
            argv = ['/bin/bash', '--noprofile', '--norc', '-c',
                    PREFIX + ('\nset -euo pipefail\n' if strict else '\n') + body]
        return subprocess.run(argv, cwd=self.root, env=env, text=True,
                              capture_output=True, timeout=5)

    def assert_no_activation(self):
        self.assertEqual(self.trace.read_text(), '')
        self.assertEqual(list((self.console / 'console/active').iterdir()), [])

    def chain(self):
        self.cartridge('base')
        self.cartridge('dep', ['base'])
        self.cartridge('app', ['dep'])

    def test_exact_plan_streams_at_all_verbosity_levels(self):
        self.chain()
        for level in range(4):
            with self.subTest(verbosity=level):
                result = self.shell('bashcmdr_get_activation_plan app', level)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, 'base\ndep\napp\n')
                expected = ('' if level < 2 else
                            'ℹ️  bashcmdr: Resolving dependencies for: app\n'
                            '✓ bashcmdr: Dependency resolution complete\n'
                            'ℹ️  bashcmdr: Activation order: base dep app\n')
                self.assertEqual(result.stderr, expected)
        self.assert_no_activation()

    def test_real_resolver_failures_have_no_plan_or_activation(self):
        for scenario in ['missing-target', 'missing-dependency', 'cycle', 'constraint']:
            for level in range(4):
                with self.subTest(scenario=scenario, verbosity=level):
                    shutil.rmtree(self.console / 'cartridges')
                    (self.console / 'cartridges').mkdir()
                    for entry in (self.console / 'console/inactive').iterdir():
                        entry.unlink()
                    if scenario == 'missing-dependency':
                        self.cartridge('app', ['missing'])
                    elif scenario == 'cycle':
                        self.cartridge('app', ['dep'])
                        self.cartridge('dep', ['app'])
                    elif scenario == 'constraint':
                        self.cartridge('app', ['dep'])
                        self.cartridge('dep')
                        manifest = self.console / 'cartridges/dep/manifest.json'
                        data = json.loads(manifest.read_text())
                        data['version'] = '0.1.0'
                        manifest.write_text(json.dumps(data))
                    errors = {'missing-target': ['Manifest not found for cartridge: app'],
                              'missing-dependency': ['Manifest not found for cartridge: missing'],
                              'cycle': ['Dependency cycle detected:', 'Path: app dep -> app'],
                              'constraint': ['Version constraint failed:', '  Cartridge: app',
                                             '  Requires: dep >=1.0.0', '  Found: dep 0.1.0']}[scenario]
                    expected_stderr = ('' if level < 2 else
                                       'ℹ️  bashcmdr: Resolving dependencies for: app\n')
                    if level > 0:
                        expected_stderr += ''.join('⚠️  bashcmdr: ' + line + '\n' for line in errors)
                    plan = self.shell('bashcmdr_get_activation_plan app', level)
                    self.assertEqual(plan.returncode, 1)
                    self.assertEqual(plan.stdout, '')
                    self.assertEqual(plan.stderr, expected_stderr)
                    plug = self.shell('bashcmdr_plug_cartridge app', level)
                    self.assertEqual(plug.returncode, 1, plug.stdout + plug.stderr)
                    self.assertNotIn('Successfully plugged', plug.stdout)
                    self.assertEqual(plug.stderr, expected_stderr +
                                     ('' if level == 0 else
                                      '⚠️  bashcmdr: Failed to resolve dependencies for: app\n'))
                    self.assert_no_activation()

    def test_get_plan_preserves_resolver_status_and_redirects_output(self):
        for level in range(4):
            with self.subTest(verbosity=level):
                result = self.shell(r'''
bashcmdr_resolve_dependencies() { printf 'resolver-diagnostic\n'; return 42; }
bashcmdr_get_activation_plan app
''', level)
                self.assertEqual(result.returncode, 42)
                self.assertEqual(result.stdout, '')
                self.assertEqual(result.stderr, 'resolver-diagnostic\n')

    def test_failed_producer_output_is_discarded_before_any_effect(self):
        self.cartridge('app')
        for output in ['', 'app\n', 'app\ninvalid name\n']:
            for status in [1, 42, 127]:
                with self.subTest(output=output, status=status):
                    body = ('bashcmdr_get_activation_plan() { printf %s ' +
                            "'" + output + "'; printf 'producer-diagnostic\\n' >&2; return " +
                            str(status) + '; }\nbashcmdr_plug_cartridge app')
                    result = self.shell(body)
                    self.assertEqual(result.returncode, status, result.stdout + result.stderr)
                    self.assertEqual(result.stdout, '')
                    self.assertEqual(result.stderr, 'producer-diagnostic\n'
                                     '⚠️  bashcmdr: Failed to resolve dependencies for: app\n')
                    self.assert_no_activation()

    def test_successful_empty_producer_is_rejected(self):
        self.cartridge('app')
        for output in ['', '\n']:
            with self.subTest(output=output):
                result = self.shell("bashcmdr_get_activation_plan() { printf %s '" + output +
                                    "'; }; bashcmdr_plug_cartridge app")
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, '')
                self.assertEqual(result.stderr, '⚠️  bashcmdr: Empty activation plan for: app\n')
                self.assert_no_activation()

    def test_entire_successful_plan_is_validated_before_activation(self):
        self.cartridge('app')
        for output in ['app\ninvalid name\n', 'app\n\ndep\n']:
            with self.subTest(output=output):
                result = self.shell("bashcmdr_get_activation_plan() { printf %s '" + output +
                                    "'; }; bashcmdr_plug_cartridge app")
                self.assertEqual(result.returncode, 1)
                self.assertIn('Invalid cartridge name:', result.stderr)
                self.assert_no_activation()

    def test_single_cartridge_and_chain_plug_at_all_verbosity_levels(self):
        self.chain()
        for target, expected in [('base', ['base']), ('app', ['base', 'dep', 'app'])]:
            for level in range(4):
                with self.subTest(target=target, verbosity=level):
                    self.trace.write_text('')
                    result = self.shell('bashcmdr_plug_cartridge ' + target +
                                        '\nstatus=$?\n[[ $status == 0 && $PLAN_HOOK_PERSIST == present ]]', level)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual(self.trace.read_text().splitlines(),
                                     [str(self.console / 'cartridges' / name) + ':activate'
                                      for name in expected])
                    for name in expected:
                        self.assertTrue((self.console / 'console/active' / name).is_symlink())
                    self.assertNotIn('Resolving dependencies', result.stdout)
                    if level < 2:
                        self.assertEqual(result.stdout, '')
                        self.assertEqual(result.stderr, '')
                    else:
                        self.assertIn('Successfully plugged cartridge: ' + target, result.stdout)
                        self.assertIn('Activation order: ' + ' '.join(expected), result.stderr)

    def test_strict_shell_keeps_producer_status(self):
        self.cartridge('app')
        result = self.shell('bashcmdr_get_activation_plan() { printf "app\\n"; return 42; }\n'
                            'bashcmdr_plug_cartridge app', strict=True)
        self.assertEqual(result.returncode, 42, result.stdout + result.stderr)
        self.assert_no_activation()

    def test_direct_cli_returns_failure_and_success(self):
        missing = self.shell('', direct=True)
        self.assertEqual(missing.returncode, 1, missing.stdout + missing.stderr)
        self.assert_no_activation()
        self.cartridge('app')
        valid = self.shell('', direct=True)
        self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)
        self.assertEqual(len(self.trace.read_text().splitlines()), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
