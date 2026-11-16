#!/usr/bin/env python3
"""Exercise real shell suites with disposable contaminated callers and code copies."""
import json
import os
import pathlib
import shlex
import shutil
import subprocess
import tempfile
import unittest

REPO = pathlib.Path(os.environ.get('ISOLATION_TEST_REPO', pathlib.Path(__file__).resolve().parent.parent))
SUITES = {'unit': 'test_runner.bash', 'resolver': 'test_resolver.bash', 'path': 'test_path.bash',
          'install': 'test_install.bash', 'factorial': 'factorial_test_runner.bash'}


class HarnessIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bcm-harness-controls-')
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.repo = self.root / 'source copy'
        for part in ['bin', 'boot', 'lib', 'tests']:
            shutil.copytree(REPO / part, self.repo / part, symlinks=True,
                            ignore=shutil.ignore_patterns('results', '__pycache__'))
        shutil.copyfile(REPO / 'VERSION', self.repo / 'VERSION')
        self.home = self.root / 'caller home'
        self.home.mkdir()
        self.tmp = self.root / 'temp parent'
        self.tmp.mkdir()
        self.artifacts = self.root / 'retained artifacts'
        self.trace = self.root / 'canary.log'
        self.trace.write_text('')
        self.bash = pathlib.Path(shutil.which('bash'))
        self.env = {'HOME': str(self.home), 'PATH': os.environ.get('PATH', os.defpath),
                    'TMPDIR': str(self.tmp), 'LC_ALL': 'C', 'TERM': 'dumb',
                    'BASHCMDR_TEST_RESULTS_DIR': str(self.artifacts),
                    'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
                    'GIT_ALLOW_PROTOCOL': 'file', 'GIT_TERMINAL_PROMPT': '0'}

    def canary(self, console):
        for part in ['bin', 'boot', 'lib']:
            shutil.copytree(REPO / part, console / part, symlinks=True)
        shutil.copyfile(REPO / 'VERSION', console / 'VERSION')
        cart = console / 'cartridges/canary'
        cart.mkdir(parents=True)
        (cart / 'manifest.json').write_text('{"name":"canary","version":"1.0.0"}')
        (cart / 'main.bashcmdr').write_text('printf "CANARY_SOURCE\\n" >> ' + shlex.quote(str(self.trace)) + '\n'
            'cartridge_dispatch() { printf "CANARY_ACTION\\n" >> ' + shlex.quote(str(self.trace)) + '; }\n')
        active = console / 'console/active'
        active.mkdir(parents=True)
        (active / 'canary').symlink_to('../../cartridges/canary')

    def snapshot(self, root):
        return {str(p.relative_to(root)): ('link:' + os.readlink(p) if p.is_symlink()
                else p.read_bytes() if p.is_file() else None) for p in root.rglob('*')}

    def contaminate(self):
        console = self.home / '.local/bin/bashcmdr'
        self.canary(console)
        config = self.home / '.gitconfig'
        hook = self.root / 'hooks/pre-commit'
        hook.parent.mkdir()
        hook.write_text('#!' + str(self.bash) + '\nprintf "CANARY_GIT\\n" >> ' + shlex.quote(str(self.trace)) + '\nexit 73\n')
        hook.chmod(0o755)
        config.write_text('[core]\n\thooksPath = "' + str(hook.parent) + '"\n[commit]\n\tgpgsign = true\n')
        self.env.update({'BASHCMDR_ROOT_DIR': str(console), 'BASHCMDR_ROOT': str(console),
                         'BASHCMDR_BOOT_ROOT_DIR': str(console),
                         'BASHCMDR_BOOT_CONSOLE_EXE': str(console / 'bin/bashcmdr'),
                         'BASHCMDR_REGISTRY_DIR': str(self.home / '.bashcmdr/registry'),
                         'BASHCMDR_VERBOSITY': 'invalid', 'BASHCMDR_QUIET_BOOT': 'invalid',
                         'GIT_CONFIG_GLOBAL': str(config), 'GIT_CONFIG_COUNT': '1',
                         'GIT_CONFIG_KEY_0': 'core.hooksPath', 'GIT_CONFIG_VALUE_0': str(hook.parent),
                         'GIT_DIR': str(self.root / 'wrong-git-dir'),
                         'GIT_WORK_TREE': str(self.home), 'XDG_CONFIG_HOME': str(self.home / 'private-xdg')})
        return console

    def run_suite(self, suite, *, cwd=None, bash=None, body=None, cleanup='removed'):
        script = self.repo / 'tests' / SUITES[suite]
        before = set(self.artifacts.glob(suite + '.*')) if self.artifacts.exists() else set()
        argv = [str(bash or self.bash), '--noprofile', '--norc']
        if body:
            argv += ['-c', body, 'fixture', str(script)]
        else:
            argv += [script.name if cwd == script.parent else str(script)]
        p = subprocess.run(argv, cwd=cwd or self.repo, env=self.env, text=True,
                           capture_output=True, timeout=25)
        after = set(self.artifacts.glob(suite + '.*')) if self.artifacts.exists() else set()
        new = after - before
        self.assertEqual(len(new), 1, p.stdout + p.stderr)
        artifact = new.pop()
        self.assertEqual(int((artifact / 'status.txt').read_text()), p.returncode)
        self.assertEqual((artifact / 'cleanup.status').read_text().strip(), cleanup)
        fixture = pathlib.Path((artifact / 'temp-root.txt').read_text().strip())
        self.assertEqual(fixture.exists(), cleanup == 'failed')
        evidence = os.environ.get('ISOLATION_TEST_EVIDENCE_DIR')
        if evidence:
            destination = pathlib.Path(evidence) / self.id().split('.')[-1] / artifact.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(artifact, destination)
        return p, artifact

    def ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unit_clean_has_unconditional_dependency_assertions(self):
        p, a = self.run_suite('unit')
        self.ok(p)
        log = (a / 'test_results.log').read_text()
        self.assertIn('PASS: cartridge deps command works', log)
        self.assertIn('PASS: cartridge plan command works', log)
        self.assertIn('Total tests: 56', p.stdout)

    def test_resolver_without_home_tmp_parent(self):
        self.env.pop('TMPDIR')
        p, _ = self.run_suite('resolver')
        self.ok(p)
        self.assertFalse((self.home / 'tmp').exists())
        self.assertIn('Total:  92', p.stdout)

    def test_path_uses_known_bash_at_nonstandard_spaced_location(self):
        binary = self.root / 'tool chain/bash'
        binary.parent.mkdir()
        binary.symlink_to(self.bash)
        p, _ = self.run_suite('path', bash=binary)
        self.ok(p)
        self.assertIn('Passed: 64', p.stdout)

    def test_install_clean_retains_diagnostics(self):
        p, a = self.run_suite('install')
        self.ok(p)
        self.assertIn('Passed: 29', p.stdout)
        self.assertTrue((a / 'stdout.log').is_file())
        self.assertTrue((a / 'stderr.log').is_file())

    def test_install_uses_known_bash_at_nonstandard_spaced_location(self):
        binary = self.root / 'tool chain/bash'
        binary.parent.mkdir()
        binary.symlink_to(self.bash)
        p, _ = self.run_suite('install', bash=binary)
        self.ok(p)
        self.assertIn('Passed: 29', p.stdout)

    def test_factorial_clean_saves_full_matrix_outside_fixture(self):
        p, a = self.run_suite('factorial')
        self.ok(p)
        data = json.loads((a / 'rapid_test_results.json').read_text())
        self.assertEqual(len(data['results']), 35)
        self.assertTrue(all('command' in row and 'exit_code' in row for row in data['results']))
        self.assertTrue(all((a / row['output_log']).is_file() for row in data['results']))

    def test_factorial_retains_complete_multiline_case_output(self):
        firmware = self.repo / 'bin/bashcmdr'
        firmware.write_text(firmware.read_text().replace('version_cmd() {',
            'version_cmd() {\n    printf "FIRST_LINE\\nRETAINED_MATRIX_SECOND_LINE\\n"\n    return 0\n', 1))
        p, a = self.run_suite('factorial')
        self.ok(p)
        data = json.loads((a / 'rapid_test_results.json').read_text())
        version = next(row for row in data['results'] if row['command'].endswith(' version'))
        self.assertEqual(version['output'], 'FIRST_LINE')
        self.assertIn('RETAINED_MATRIX_SECOND_LINE', (a / version['output_log']).read_text())

    def test_contaminated_unit_preserves_inherited_installation_and_home(self):
        self.contaminate()
        before = self.snapshot(self.home)
        p, _ = self.run_suite('unit')
        self.ok(p)
        self.assertEqual(self.snapshot(self.home), before)
        self.assertEqual(self.trace.read_text(), '')

    def test_contaminated_factorial_preserves_inherited_installation(self):
        self.contaminate()
        before = self.snapshot(self.home)
        p, _ = self.run_suite('factorial')
        self.ok(p)
        self.assertEqual(self.snapshot(self.home), before)
        self.assertEqual(self.trace.read_text(), '')

    def test_contaminated_git_install_ignores_hooks_signing_and_git_directory(self):
        self.contaminate()
        before = self.snapshot(self.home)
        p, _ = self.run_suite('install')
        self.ok(p)
        self.assertEqual(self.snapshot(self.home), before)
        self.assertEqual(self.trace.read_text(), '')

    def test_contaminated_resolver_uses_owned_config(self):
        self.contaminate()
        before = self.snapshot(self.home)
        p, _ = self.run_suite('resolver')
        self.ok(p)
        self.assertEqual(self.snapshot(self.home), before)
        self.assertEqual(self.trace.read_text(), '')

    def test_contaminated_path_uses_owned_context(self):
        self.contaminate()
        before = self.snapshot(self.home)
        p, _ = self.run_suite('path')
        self.ok(p)
        self.assertEqual(self.snapshot(self.home), before)

    def test_checkout_runtime_cartridges_and_config_are_excluded(self):
        cart = self.repo / 'cartridges/pyenv-loader'
        cart.mkdir(parents=True)
        (cart / 'main.bashcmdr').write_text('printf "CHECKOUT_PAYLOAD\\n" >> ' + shlex.quote(str(self.trace)) + '\n')
        config = self.repo / 'config/bashcmdr.conf'
        config.parent.mkdir()
        config.write_text('printf "CHECKOUT_CONFIG\\n" >> ' + shlex.quote(str(self.trace)) + '\n')
        active = self.repo / 'console/active'
        active.mkdir(parents=True)
        (active / 'pyenv-loader').symlink_to('../../cartridges/pyenv-loader')
        p, _ = self.run_suite('unit')
        self.ok(p)
        self.assertEqual(self.trace.read_text(), '')
        self.assertIn('Total tests: 56', p.stdout)

    def test_failed_assertion_keeps_command_stderr_after_cleanup(self):
        script = self.repo / 'tests/test_runner.bash'
        text = script.read_text().replace('    test_basic_commands\n',
            '    assert_success "injected failure" "printf RETAINED_ASSERTION_DIAGNOSTIC >&2; false"\n    test_basic_commands\n')
        script.write_text(text)
        p, a = self.run_suite('unit')
        self.assertEqual(p.returncode, 1)
        log = (a / 'test_results.log').read_text()
        self.assertIn('RETAINED_ASSERTION_DIAGNOSTIC', log)
        self.assertIn('Exit: 1', log)
        self.assertIn('FAIL: injected failure', log)

    def test_early_child_failure_keeps_stderr_and_cleans_fixture(self):
        script = self.repo / 'tests/test_install.bash'
        script.write_text(script.read_text().replace('make_repo demo-cart demo-cart\n',
            'printf "RETAINED_SETUP_DIAGNOSTIC\\n" >&2\nexit 73\nmake_repo demo-cart demo-cart\n'))
        p, a = self.run_suite('install')
        self.assertEqual(p.returncode, 73)
        self.assertIn('RETAINED_SETUP_DIAGNOSTIC', (a / 'stderr.log').read_text())

    def test_parent_copy_failure_keeps_setup_diagnostics_and_cleans(self):
        tool = self.root / 'tools/cp'
        tool.parent.mkdir()
        tool.write_text('#!' + str(self.bash) + '\nprintf "RETAINED_COPY_DIAGNOSTIC\\n" >&2\nexit 73\n')
        tool.chmod(0o755)
        self.env['PATH'] = str(tool.parent) + ':' + self.env['PATH']
        p, a = self.run_suite('path')
        self.assertEqual(p.returncode, 1)
        self.assertIn('RETAINED_COPY_DIAGNOSTIC', (a / 'setup.log').read_text())

    def test_children_drop_startup_hooks_and_exported_functions(self):
        hook = self.root / 'child-startup.bash'
        hook.write_text('printf "CHILD_STARTUP\\n" >> ' + shlex.quote(str(self.trace)) + '\n')
        self.env['TEST_CHILD_HOOK'] = str(hook)
        self.env['TEST_TRACE'] = str(self.trace)
        body = r'''
export BASH_ENV="$TEST_CHILD_HOOK"
cp() { printf 'EXPORTED_FUNCTION\n' >> "$TEST_TRACE"; return 73; }
export -f cp
source "$1"
'''
        p, _ = self.run_suite('path', body=body)
        self.ok(p)
        self.assertEqual(self.trace.read_text(), '')

    def test_noop_cleanup_is_nonzero_with_retained_fixture_path(self):
        tool = self.root / 'tools/rm'
        tool.parent.mkdir()
        tool.write_text('#!' + str(self.bash) + '\nexit 0\n')
        tool.chmod(0o755)
        self.env['PATH'] = str(tool.parent) + ':' + self.env['PATH']
        p, a = self.run_suite('resolver', cleanup='failed')
        self.assertEqual(p.returncode, 1)
        self.assertIn('Cannot remove test fixture', p.stderr)
        self.assertTrue((a / 'stdout.log').is_file())

    def test_entry_from_tests_directory_with_bare_filename(self):
        p, _ = self.run_suite('resolver', cwd=self.repo / 'tests')
        self.ok(p)

    def test_quoted_temp_parent_does_not_become_shell_source(self):
        parent = self.root / "temp with 'quote' and $literal"
        parent.mkdir()
        self.env['TMPDIR'] = str(parent)
        p, _ = self.run_suite('unit')
        self.ok(p)
        self.assertEqual(list(parent.iterdir()), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
