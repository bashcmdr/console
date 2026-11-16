#!/usr/bin/env python3
"""Fresh code-only installs must create their own state layout."""
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

REPO = pathlib.Path(os.environ.get('LAYOUT_TEST_REPO', pathlib.Path(__file__).resolve().parent.parent))
STATES = ['active', 'inactive', 'broken', 'quarantine']


class StateLayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bcm-layout-')
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.home = self.root / 'home'
        self.console = self.home / '.local/bin/bashcmdr'
        self.console.mkdir(parents=True)
        for name in ['bin', 'lib', 'boot']:
            shutil.copytree(REPO / name, self.console / name)
        for name in ['VERSION', '.gitignore']:
            shutil.copyfile(REPO / name, self.console / name)
        self.env = {'HOME': str(self.home), 'PATH': '/usr/bin:/bin', 'TMPDIR': str(self.root),
                    'TERM': 'dumb', 'LC_ALL': 'C', 'BASHCMDR_ROOT': str(self.console),
                    'BASHCMDR_ROOT_DIR': str(self.console), 'BASHCMDR_QUIET_BOOT': '1',
                    'BASHCMDR_VERBOSITY': '1', 'GIT_CONFIG_NOSYSTEM': '1',
                    'GIT_CONFIG_GLOBAL': os.devnull}
        self.assertFalse((self.console / 'console').exists())

    def cartridge(self, name='demo'):
        path = self.console / 'cartridges' / name
        path.mkdir(parents=True)
        (path / 'manifest.json').write_text(json.dumps({'name': name, 'version': '1.0.0'}))
        (path / 'main.bashcmdr').write_text('cartridge_dispatch() { export LAYOUT_ACTIVATED=1; }\n')

    def shell(self, body, library='state', strict=False):
        prefix = 'source "$BASHCMDR_ROOT/lib/' + library + '.bashcmdr"\n'
        if library == 'cli':
            prefix = 'source "$BASHCMDR_ROOT/bin/bashcmdr"\n'
        return subprocess.run(['/bin/bash', '--noprofile', '--norc', '-c',
                               prefix + ('set -euo pipefail\n' if strict else '') + body],
                              cwd=self.root, env=self.env, text=True, capture_output=True, timeout=5)

    def assert_ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def assert_layout(self):
        for state in STATES:
            self.assertTrue((self.console / 'console' / state).is_dir(), state)

    def test_fresh_library_sync_creates_layout_and_discovers_cartridge(self):
        self.cartridge()
        result = self.shell('__bashcmdr_sync_physical_state || exit $?\n'
                            '[[ ${BASHCMDR_CARTRIDGES_STATE[demo]} == inactive ]]')
        self.assert_ok(result)
        self.assertEqual(result.stderr, '')
        self.assert_layout()
        self.assertTrue((self.console / 'console/inactive/demo').resolve().samefile(
            self.console / 'cartridges/demo'))

    def test_direct_transitions_create_missing_layout_for_every_state(self):
        self.cartridge()
        for state in STATES:
            with self.subTest(state=state):
                if (self.console / 'console').exists():
                    shutil.rmtree(self.console / 'console')
                result = self.shell('__bashcmdr_set_cartridge_state demo ' + state)
                self.assert_ok(result)
                self.assert_layout()
                link = self.console / 'console' / state / 'demo'
                self.assertTrue(link.is_symlink())
                self.assertEqual(os.readlink(link), '../../cartridges/demo')
                self.assertTrue(link.resolve().samefile(self.console / 'cartridges/demo'))
                self.assertEqual(sum((self.console / 'console' / x / 'demo').is_symlink()
                                     for x in STATES), 1)

    def test_fresh_cli_initializes_without_fixture_state_directories(self):
        result = subprocess.run(['/bin/bash', '--noprofile', '--norc',
                                 str(self.console / 'bin/bashcmdr'), 'version'],
                                cwd=self.root, env=self.env, capture_output=True, text=True, timeout=5)
        self.assert_ok(result)
        self.assert_layout()

    def test_poweron_initializes_without_implicitly_activating_essential(self):
        self.cartridge('pyenv-loader')
        result = self.shell('console_poweron || exit $?\n[[ ! ${LAYOUT_ACTIVATED-} ]]', 'cli')
        self.assert_ok(result)
        self.assertEqual(result.stderr, '')
        self.assert_layout()
        self.assertFalse((self.console / 'console/active/pyenv-loader').is_symlink())

    def test_repeated_initialization_preserves_runtime_links(self):
        self.cartridge()
        result = self.shell('__bashcmdr_set_cartridge_state demo active || exit $?\n'
                            '__bashcmdr_init_state || exit $?\n__bashcmdr_init_state')
        self.assert_ok(result)
        self.assert_layout()
        self.assertEqual(os.readlink(self.console / 'console/active/demo'), '../../cartridges/demo')

    def test_failed_creation_prevents_removal_of_existing_state(self):
        self.cartridge()
        self.assert_ok(self.shell('__bashcmdr_set_cartridge_state demo active'))
        shutil.rmtree(self.console / 'console/inactive')
        result = self.shell('mkdir() { printf "mkdir-denied\\n" >&2; return 73; }\n'
                            '__bashcmdr_set_cartridge_state demo inactive')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('mkdir-denied', result.stderr)
        self.assertIn('Cannot initialize state directory: inactive', result.stderr)
        self.assertTrue((self.console / 'console/active/demo').is_symlink())
        self.assertFalse((self.console / 'console/inactive').exists())

    def test_file_collision_is_reported_and_does_not_run_hooks(self):
        self.cartridge('pyenv-loader')
        (self.console / 'console').write_text('preserve-file\n')
        result = self.shell('console_poweron\nstatus=$?\n'
                            '[[ ! ${LAYOUT_ACTIVATED-} ]] || exit 88\nexit "$status"', 'cli')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotEqual(result.returncode, 88)
        self.assertIn('Cannot initialize state directory:', result.stderr)
        self.assertEqual((self.console / 'console').read_text(), 'preserve-file\n')
        self.assertFalse((self.console / 'logs').exists())

    def test_failed_cli_initialization_stops_before_command(self):
        (self.console / 'console').write_text('preserve-file\n')
        result = self.shell('version_cmd() { printf "UNEXPECTED-COMMAND\\n"; }\nmain version', 'cli')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('UNEXPECTED-COMMAND', result.stdout)

    def test_failed_sync_retains_existing_logical_arrays(self):
        result = self.shell('declare -gA BASHCMDR_CARTRIDGES_STATE=([demo]=active)\n'
                            'declare -gA BASHCMDR_CARTRIDGES_PATHS=([demo]=preserve)\n'
                            'mkdir() { return 73; }\n'
                            'if __bashcmdr_sync_physical_state; then exit 88; fi\n'
                            '[[ ${BASHCMDR_CARTRIDGES_STATE[demo]} == active && '
                            '${BASHCMDR_CARTRIDGES_PATHS[demo]} == preserve ]]')
        self.assert_ok(result)

    def test_initializer_rejects_missing_root(self):
        result = self.shell('BASHCMDR_ROOT="$HOME/not-a-console"\n__bashcmdr_init_state')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Console root is unavailable', result.stderr)
        self.assertFalse((self.home / 'not-a-console').exists())

    def test_initializer_works_in_strict_shell(self):
        result = self.shell('__bashcmdr_init_state\n__bashcmdr_init_state', strict=True)
        self.assert_ok(result)
        self.assert_layout()

    def test_initializer_needs_no_sudo_or_platform_tools(self):
        tools = self.root / 'tools'
        tools.mkdir()
        for name in ['dirname', 'mkdir']:
            (tools / name).symlink_to(shutil.which(name))
        self.env['PATH'] = str(tools)
        result = self.shell('if command -v sudo >/dev/null; then exit 88; fi\n'
                            '__bashcmdr_init_state')
        self.assert_ok(result)
        self.assert_layout()

    def test_runtime_state_is_ignored_and_source_checkout_stays_clean(self):
        def git(*args):
            return subprocess.run(['git', '-C', str(self.console), *args],
                                  env=self.env, capture_output=True, text=True, timeout=5)
        self.assert_ok(git('init', '--quiet'))
        self.assert_ok(git('add', '.'))
        self.assert_ok(git('-c', 'user.name=fixture', '-c', 'user.email=fixture@example.invalid',
                           'commit', '--quiet', '-m', 'fixture source'))
        self.cartridge()
        self.assert_ok(self.shell('__bashcmdr_init_state'))
        for state in STATES:
            self.assert_ok(self.shell('__bashcmdr_set_cartridge_state demo ' + state))
            self.assert_ok(git('check-ignore', '--quiet', 'console/' + state + '/demo'))
            self.assertEqual(git('check-ignore', '--quiet', '--no-index',
                                 'console/' + state + '/.gitkeep').returncode, 1)
        result = git('status', '--porcelain')
        self.assert_ok(result)
        self.assertEqual(result.stdout, '')


if __name__ == '__main__':
    unittest.main(verbosity=2)
