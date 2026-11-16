#!/usr/bin/env python3
"""CLI value regressions in disposable console copies; all Git/network sinks inert."""
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

REPO = pathlib.Path(os.environ.get('OPTION_TEST_REPO', pathlib.Path(__file__).resolve().parent.parent))
CLI = pathlib.Path(os.environ.get('OPTION_TEST_CLI', REPO / 'bin/bashcmdr'))
PREFIX = r'''
source "$BASHCMDR_ROOT_DIR/bin/bashcmdr"
__bashcmdr_sync_physical_state() { :; }
resolve_alias() { return 1; }
bashcmdr_is_installed() { return 1; }
bashcmdr_load_registry_index() { printf 'registry-load\n' >> "$TRACE"; return 0; }
bashcmdr_get_registry_version() { printf 'registry-version\n' >> "$TRACE"; printf '1.0.0\n'; }
bashcmdr_get_cartridge_info() { printf 'registry-info\n' >> "$TRACE"; printf 'fixture://registry/cart\n'; }
bashcmdr_search_cartridges() { printf 'registry-search\n' >> "$TRACE"; }
git() { { printf 'git'; printf '<%s>' "$@"; printf '\n'; } >> "$TRACE"; return 73; }
curl() { printf 'unexpected-curl\n' >> "$TRACE"; return 99; }
wget() { printf 'unexpected-wget\n' >> "$TRACE"; return 99; }
sudo() { printf 'unexpected-sudo\n' >> "$TRACE"; return 99; }
main "$@"
'''


class OptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bcm-cli-values-')
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.home = self.root / 'home with spaces'
        self.home.mkdir()
        self.console = self.home / 'console with spaces'
        self.console.mkdir()
        shutil.copytree(REPO / 'lib', self.console / 'lib')
        (self.console / 'bin').mkdir()
        shutil.copyfile(CLI, self.console / 'bin/bashcmdr')
        shutil.copyfile(REPO / 'VERSION', self.console / 'VERSION')
        (self.console / 'logs').mkdir()
        self.log = self.console / 'logs/console-poweron.log'
        self.log.write_text(''.join(f'line-{i:02d}\n' for i in range(1, 31)))
        self.trace = self.root / 'operations.log'
        self.trace.write_text('')
        self.tools = self.root / 'inert tools'
        self.tools.mkdir()
        for name in ['git', 'curl', 'wget', 'sudo']:
            tool = self.tools / name
            tool.write_text('#!/bin/bash\nprintf "unexpected-' + name + '\\n" >> "$TRACE"\nexit 99\n')
            tool.chmod(0o755)
        self.registry = self.root / 'index.json'
        self.registry.write_text('''{"cartridges": {
          "alpha": {"version":"1.0.0","description":"Alpha fixture","tags":["blue"],"author":"Alice"},
          "beta": {"version":"2.0.0","description":"Beta fixture","tags":["green"],"author":"Bob"}
        }}''')

    def run_cli(self, *args, strict=False, direct=False):
        env = {'HOME': str(self.home), 'TMPDIR': str(self.root), 'PATH': str(self.tools) + ':/usr/bin:/bin',
               'TERM': 'dumb', 'LC_ALL': 'C', 'TRACE': str(self.trace),
               'BASHCMDR_ROOT_DIR': str(self.console), 'BASHCMDR_REGISTRY_INDEX': str(self.registry),
               'GIT_TERMINAL_PROMPT': '0', 'GIT_ALLOW_PROTOCOL': 'file'}
        prefix = ('set -u\n' if strict else '') + PREFIX
        command = ['/bin/bash', '--noprofile', '--norc', str(self.console / 'bin/bashcmdr'), *args] if direct else [
            '/bin/bash', '--noprofile', '--norc', '-c', prefix, 'fixture', *args]
        return subprocess.run(command,
                              cwd=self.root, env=env, text=True, capture_output=True, timeout=3)

    def assert_rejected(self, args, diagnostic, strict=False, direct=False):
        result = self.run_cli(*args, strict=strict, direct=direct)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(diagnostic, result.stderr)
        self.assertEqual(self.trace.read_text(), '', 'invalid arguments reached a backend')

    def test_log_missing_value(self):
        self.assert_rejected(['console', 'log', '--lines'], '--lines requires')

    def test_log_empty_value(self):
        self.assert_rejected(['console', 'log', '--lines', ''], '--lines requires')

    def test_log_invalid_value_before_absent_log(self):
        self.log.unlink()
        self.assert_rejected(['console', 'log', '--lines', 'abc'], '--lines requires')

    def test_log_default(self):
        result = self.run_cli('console', 'log')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([s for s in result.stdout.splitlines() if s.startswith('line-')],
                         [f'line-{i:02d}' for i in range(11, 31)])

    def test_log_explicit_counts(self):
        for count, expected in [('2', ['line-29', 'line-30']), ('0', []), ('01', ['line-30'])]:
            with self.subTest(count=count):
                result = self.run_cli('console', 'log', '--lines', count)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual([s for s in result.stdout.splitlines() if s.startswith('line-')], expected)

    def test_search_missing_tag(self):
        self.assert_rejected(['cartridge', 'search', '--tag'], '--tag requires')

    def test_search_missing_author(self):
        self.assert_rejected(['cartridge', 'search', '--author'], '--author requires')

    def test_search_empty_values(self):
        for option in ['--tag', '--author']:
            with self.subTest(option=option):
                self.assert_rejected(['cartridge', 'search', option, ''], option + ' requires')

    def test_search_valid_filters(self):
        for option, value, included, excluded in [('--tag', 'blue', 'alpha', 'beta'),
                                                 ('--author', 'Bob', 'beta', 'alpha')]:
            with self.subTest(option=option):
                result = self.run_cli('cartridge', 'search', option, value)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(included, result.stdout)
                self.assertNotIn(excluded, result.stdout)
                self.assertNotIn('git', self.trace.read_text())

    def test_install_missing_from_value(self):
        self.assert_rejected(['cartridge', 'install', 'fixture-cart', '--from'], '--from requires')

    def test_install_empty_spaced_from_value(self):
        self.assert_rejected(['cartridge', 'install', 'fixture-cart', '--from', ''], '--from requires')

    def test_install_empty_equals_with_name(self):
        self.assert_rejected(['cartridge', 'install', 'fixture-cart', '--from='], '--from requires')

    def test_install_empty_equals_without_name(self):
        self.assert_rejected(['cartridge', 'install', '--from='], '--from requires')

    def test_invalid_duplicate_does_not_reuse_previous_value(self):
        self.assert_rejected(['cartridge', 'install', 'fixture-cart', '--from',
                              'fixture://valid', '--from='], '--from requires')

    def test_valid_explicit_from_never_uses_registry(self):
        for values in [['--from', 'fixture://local path/cart'], ['--from=fixture://local path/cart']]:
            with self.subTest(values=values):
                self.trace.write_text('')
                result = self.run_cli('cartridge', 'install', 'fixture-cart', *values)
                self.assertEqual(result.returncode, 1, result.stderr)  # inert clone rejects
                self.assertIn('Failed to clone', result.stderr)
                trace = self.trace.read_text()
                self.assertIn('git<clone><--quiet><--><fixture://local path/cart><', trace)
                self.assertNotIn('registry', trace)
                self.assertNotIn('unexpected-', trace)

    def test_omitted_from_retains_registry_path(self):
        result = self.run_cli('cartridge', 'install', 'fixture-cart')
        self.assertEqual(result.returncode, 1, result.stderr)
        trace = self.trace.read_text()
        self.assertIn('registry-version', trace)
        self.assertIn('registry-info', trace)
        self.assertIn('git<clone><--quiet><--><fixture://registry/cart><', trace)

    def test_missing_values_under_nounset(self):
        for args, diagnostic in [(['console', 'log', '--lines'], '--lines requires'),
                                 (['cartridge', 'search', '--tag'], '--tag requires'),
                                 (['cartridge', 'search', '--author'], '--author requires'),
                                 (['cartridge', 'install', '--from'], '--from requires')]:
            with self.subTest(args=args):
                self.assert_rejected(args, diagnostic, strict=True)

    def test_executable_entrypoint_rejects_missing_and_empty_values(self):
        cases = [(['console', 'log', '--lines'], '--lines requires'),
                 (['console', 'log', '--lines', ''], '--lines requires'),
                 (['cartridge', 'install', 'fixture-cart', '--from='], '--from requires'),
                 (['cartridge', 'install', '--from='], '--from requires'),
                 (['cartridge', 'install', '--from'], '--from requires'),
                 (['cartridge', 'install', '--from', ''], '--from requires')]
        for option in ['--tag', '--author']:
            cases += [(['cartridge', 'search', option], option + ' requires'),
                      (['cartridge', 'search', option, ''], option + ' requires')]
        for args, diagnostic in cases:
            with self.subTest(args=args):
                self.assert_rejected(args, diagnostic, direct=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
