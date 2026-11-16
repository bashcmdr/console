#!/usr/bin/env python3
"""Separate reason-file names from state names without adopting foreign files."""
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

REPO = pathlib.Path(os.environ.get('QUARANTINE_LOG_TEST_REPO', pathlib.Path(__file__).resolve().parent.parent))
HEADER = '# Bash Commander quarantine reason log v1\n'
PREFIX = r'''
source "$TEST_CONSOLE/bin/bashcmdr"
__bashcmdr_init_state || exit $?
declare -gA BASHCMDR_CARTRIDGES_STATE=()
'''


class QuarantineLogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bcm-quarantine-logs-')
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.home = self.root / 'home'
        self.console = self.home / 'console'
        self.console.mkdir(parents=True)
        for name in ['bin', 'lib', 'boot']:
            shutil.copytree(REPO / name, self.console / name)
        shutil.copyfile(REPO / 'VERSION', self.console / 'VERSION')
        for name in ['demo', 'demo.log', 'demo.log.log']:
            cart = self.console / 'cartridges' / name
            cart.mkdir(parents=True)
            (cart / 'manifest.json').write_text(json.dumps({'name': name, 'version': '1.0.0'}))
            (cart / 'main.bashcmdr').write_text('cartridge_dispatch() { return 0; }\n')
        self.env = {'HOME': str(self.home), 'TEST_CONSOLE': str(self.console),
                    'BASHCMDR_ROOT_DIR': str(self.console), 'PATH': '/usr/bin:/bin',
                    'TMPDIR': str(self.root), 'TERM': 'dumb', 'LC_ALL': 'C',
                    'BASHCMDR_VERBOSITY': '2', 'BASHCMDR_QUIET_BOOT': '1'}
        self.assert_ok(self.shell(':'))
        self.log_dir = self.console / 'logs/quarantine'
        self.log_file = self.log_dir / 'demo.log'

    def shell(self, body, direct=None):
        argv = (['/bin/bash', '--noprofile', '--norc', str(self.console / 'bin/bashcmdr'), *direct]
                if direct else ['/bin/bash', '--noprofile', '--norc', '-c', PREFIX + body])
        return subprocess.run(argv, cwd=self.root, env=self.env, text=True,
                              capture_output=True, timeout=7)

    def assert_ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def assert_log_failure(self, result):
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('is quarantined, but its reason could not be logged', result.stderr)
        self.assertNotIn('Cartridge quarantined:', result.stdout)
        self.assertTrue((self.console / 'console/quarantine/demo').is_symlink())

    def test_valid_suffix_names_complete_independent_fresh_cli_lifecycles(self):
        for name in ['demo', 'demo.log', 'demo.log.log']:
            with self.subTest(name=name):
                self.assert_ok(self.shell('', direct=['cartridge', 'quarantine', name, 'reason-' + name]))
                self.assert_ok(self.shell('__bashcmdr_sync_physical_state'))
                self.assertEqual(self.shell('', direct=['cartridge', 'plug', name]).returncode, 1)
                self.assert_ok(self.shell('', direct=['cartridge', 'release', name]))
                self.assert_ok(self.shell('', direct=['cartridge', 'plug', name]))
                self.assert_ok(self.shell('', direct=['cartridge', 'unplug', name]))
                self.assert_ok(self.shell('', direct=['cartridge', 'quarantine', name, 'again-' + name]))
                reason_file = self.log_dir / (name + '.log')
                self.assertTrue(reason_file.is_file(), 'new-format reason file was not created')
                text = reason_file.read_text()
                self.assertTrue(text.startswith(HEADER))
                self.assertIn('reason-' + name, text)
                self.assertIn('again-' + name, text)
        self.assertTrue(all(p.is_symlink() for p in (self.console / 'console/quarantine').iterdir()))

    def test_reason_bytes_are_data_and_header_is_not_duplicated(self):
        result = self.shell(r'''
set -euo pipefail
before=$(set +o)
before_ifs=$IFS
bashcmdr_quarantine_cartridge demo 'first\reason $(literal)' || exit $?
bashcmdr_quarantine_cartridge demo $'second\nreason' || exit $?
[[ $(set +o) == "$before" && $IFS == "$before_ifs" ]]
''')
        self.assert_ok(result)
        self.assertTrue(self.log_file.is_file(), 'new-format reason file was not created')
        text = self.log_file.read_text()
        self.assertEqual(text.count(HEADER), 1)
        self.assertIn(r'first\reason $(literal)', text)
        self.assertIn('second\nreason', text)

    def test_legacy_state_directory_reason_file_is_preserved(self):
        legacy = self.console / 'console/quarantine/demo.log'
        legacy.write_bytes(b'legacy reason\nkeep exact bytes\\\n')
        before = legacy.read_bytes()
        self.assert_ok(self.shell('bashcmdr_quarantine_cartridge demo new-reason'))
        self.assertEqual(legacy.read_bytes(), before)
        self.assertIn('new-reason', self.log_file.read_text())
        result = self.shell('__bashcmdr_sync_physical_state')
        self.assertEqual(result.returncode, 1)
        self.assertIn('Refusing to replace non-symlink state entry:', result.stderr)
        self.assertEqual(legacy.read_bytes(), before)

    def test_explicit_operator_relocation_preserves_legacy_data_and_unblocks_cli(self):
        legacy = self.console / 'console/quarantine/demo.log'
        legacy.write_text('operator-confirmed old reason\n')
        expected = legacy.read_bytes()
        self.assertEqual(self.shell('__bashcmdr_sync_physical_state').returncode, 1)
        backup = self.home / 'chosen-legacy-backup'
        backup.mkdir()
        shutil.move(str(legacy), str(backup / 'demo.old-reason.log'))
        self.assert_ok(self.shell('__bashcmdr_sync_physical_state'))
        self.assert_ok(self.shell('', direct=['cartridge', 'quarantine', 'demo.log', 'new-reason']))
        self.assert_ok(self.shell('', direct=['cartridge', 'release', 'demo.log']))
        self.assert_ok(self.shell('', direct=['cartridge', 'plug', 'demo.log']))
        self.assertEqual((backup / 'demo.old-reason.log').read_bytes(), expected)

    def test_unknown_regular_file_in_new_namespace_is_not_appended_or_overwritten(self):
        self.log_dir.mkdir(parents=True)
        self.log_file.write_bytes(b'foreign file\nunchanged\n')
        before = self.log_file.read_bytes()
        result = self.shell('bashcmdr_quarantine_cartridge demo new-reason')
        self.assert_log_failure(result)
        self.assertIn('Unrecognized quarantine reason file preserved:', result.stderr)
        self.assertEqual(self.log_file.read_bytes(), before)

    def test_reason_file_symlink_is_not_followed(self):
        self.log_dir.mkdir(parents=True)
        sentinel = self.home / 'foreign-sentinel'
        sentinel.write_text('preserve\n')
        self.log_file.symlink_to(sentinel)
        self.assert_log_failure(self.shell('bashcmdr_quarantine_cartridge demo forbidden'))
        self.assertEqual(sentinel.read_text(), 'preserve\n')
        self.assertEqual(os.readlink(self.log_file), str(sentinel))

    def test_reason_path_directory_is_preserved(self):
        self.log_file.mkdir(parents=True)
        (self.log_file / 'sentinel').write_text('preserve\n')
        self.assert_log_failure(self.shell('bashcmdr_quarantine_cartridge demo forbidden'))
        self.assertEqual((self.log_file / 'sentinel').read_text(), 'preserve\n')

    def test_log_directory_symlinks_are_not_followed(self):
        for component in ['logs', 'logs/quarantine']:
            with self.subTest(component=component):
                logs = self.console / 'logs'
                if logs.is_symlink(): logs.unlink()
                elif logs.exists(): shutil.rmtree(logs)
                foreign = self.home / component.replace('/', '-')
                foreign.mkdir(exist_ok=True)
                (foreign / 'sentinel').write_text('preserve\n')
                path = self.console / component
                path.parent.mkdir(parents=True, exist_ok=True)
                path.symlink_to(foreign, target_is_directory=True)
                result = self.shell('bashcmdr_quarantine_cartridge demo forbidden')
                self.assert_log_failure(result)
                self.assertEqual(sorted(x.name for x in foreign.iterdir()), ['sentinel'])

    def test_regular_file_log_parent_is_preserved(self):
        logs = self.console / 'logs'
        logs.write_text('foreign parent\n')
        self.assert_log_failure(self.shell('bashcmdr_quarantine_cartridge demo forbidden'))
        self.assertEqual(logs.read_text(), 'foreign parent\n')

    def test_failed_directory_creation_reports_applied_quarantine(self):
        result = self.shell(r'''
mkdir() { if [[ ${@: -1} == "$BASHCMDR_ROOT/logs/quarantine" ]]; then return 73; else command mkdir "$@"; fi; }
bashcmdr_quarantine_cartridge demo denied
''')
        self.assert_log_failure(result)
        self.assertFalse(self.log_file.exists())

    def test_failed_timestamp_does_not_claim_logged_reason(self):
        result = self.shell('date() { return 73; }; bashcmdr_quarantine_cartridge demo missing-time')
        self.assert_log_failure(result)
        if self.log_file.exists(): self.assertNotIn('missing-time', self.log_file.read_text())

    def test_failed_append_preserves_prior_content_and_reports_failure(self):
        self.assert_ok(self.shell('bashcmdr_quarantine_cartridge demo first-reason'))
        self.assertTrue(self.log_file.is_file(), 'new-format reason file was not created')
        before = self.log_file.read_bytes()
        result = self.shell(r'''
printf() { if [[ $1 == '%s: %s\n' ]]; then return 73; else builtin printf "$@"; fi; }
bashcmdr_quarantine_cartridge demo denied-reason
''')
        self.assert_log_failure(result)
        self.assertEqual(self.log_file.read_bytes(), before)

    def test_invalid_names_cannot_create_log_namespace(self):
        result = self.shell('__bashcmdr_log_quarantine_reason ../outside forbidden')
        self.assertEqual(result.returncode, 1)
        self.assertFalse((self.console / 'logs').exists())
        self.assertFalse((self.home / 'outside.log').exists())

    def test_partial_append_is_reported_without_truncating_retained_data(self):
        self.assert_ok(self.shell('bashcmdr_quarantine_cartridge demo first-reason'))
        self.assertTrue(self.log_file.is_file(), 'new-format reason file was not created')
        before = self.log_file.read_bytes()
        result = self.shell(r'''
printf() {
    if [[ $1 == '%s: %s\n' ]]; then builtin printf 'partial-record'; return 73; fi
    builtin printf "$@"
}
bashcmdr_quarantine_cartridge demo partial-reason
''')
        self.assert_log_failure(result)
        self.assertEqual(self.log_file.read_bytes(), before + b'partial-record')


if __name__ == '__main__':
    unittest.main(verbosity=2)
