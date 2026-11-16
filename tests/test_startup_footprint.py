#!/usr/bin/env python3
"""Startup preserves shortcut objects; explicit installation is bounded."""
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

REPO = pathlib.Path(os.environ.get('STARTUP_TEST_REPO', pathlib.Path(__file__).resolve().parent.parent))


class StartupFootprintTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bcm-shortcut-')
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.home = self.root / 'home with spaces'
        self.console = self.home / 'console'
        self.console.mkdir(parents=True)
        for part in ['bin', 'lib', 'boot']:
            shutil.copytree(REPO / part, self.console / part, symlinks=True)
        shutil.copyfile(REPO / 'VERSION', self.console / 'VERSION')
        self.link = self.console / 'bin/bcm'
        if self.link.exists() or self.link.is_symlink():
            self.link.unlink()
        self.trace = self.root / 'operations.log'
        self.trace.write_text('')
        self.env = {'HOME': str(self.home), 'CONSOLE': str(self.console), 'TRACE': str(self.trace),
                    'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'TERM': 'dumb',
                    'TMPDIR': str(self.root), 'BASHCMDR_QUIET_BOOT': '1'}
        self.addCleanup(self.restore_permissions)

    def restore_permissions(self):
        self.console.chmod(0o755)
        for path in self.console.rglob('*'):
            if not path.is_symlink():
                path.chmod(0o755 if path.is_dir() or path.stat().st_mode & 0o111 else 0o644)

    def shell(self, body, bios=False):
        inert = '\n'.join(name + '() { printf "unexpected-' + name + '\\n" >> "$TRACE"; return 99; }'
                          for name in ['git', 'curl', 'wget', 'sudo'])
        # Record actual link attempts while allowing only the exact owned operand.
        inert += r'''
ln() {
    printf 'ln' >> "$TRACE"; printf '<%s>' "$@" >> "$TRACE"; printf '\n' >> "$TRACE"
    [[ ${*: -1} == "$CONSOLE/bin/bcm" ]] || return 98
    command ln "$@"
}
'''
        entry = 'boot/shell-init.bashcmdr' if bios else 'bin/bashcmdr'
        return subprocess.run(['/bin/bash', '--noprofile', '--norc', '-c', inert +
                               '\nsource "$CONSOLE/' + entry + '" || exit $?\n' + body],
                              env=self.env, cwd=self.root, capture_output=True, text=True, timeout=8)

    def ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def snapshot(self):
        result = {}
        for path in self.home.rglob('*'):
            key = str(path.relative_to(self.home))
            if path.is_symlink():
                result[key] = 'link:' + os.readlink(path)
            elif path.is_file():
                result[key] = hashlib.sha256(path.read_bytes()).hexdigest()
            else:
                result[key] = 'directory'
        return result

    def readonly(self, whole_tree=False):
        if os.geteuid() == 0:
            self.skipTest('Genuine permission-denial control requires a non-bypassing UID')
        (self.console / 'bin').chmod(0o555)
        with self.assertRaises(PermissionError):
            (self.console / 'bin/permission-probe').write_text('unexpected')
        if whole_tree:
            for path in self.console.rglob('*'):
                if not path.is_symlink():
                    path.chmod(0o555 if path.is_dir() or path.stat().st_mode & 0o111 else 0o444)
            self.console.chmod(0o555)

    def test_missing_shortcut_boot_does_not_install_it(self):
        result = self.shell('[[ $BASHCMDR_BOOT_EXIT_CODE == 0 && ${BASHCMDR_BOOT_SUMMARY[shortcut]-} == missing ]]', bios=True)
        self.ok(result)
        self.assertFalse(self.link.exists())
        self.assertFalse(self.link.is_symlink())
        self.assertEqual(self.trace.read_text(), '')

    def test_correct_link_boot_is_ready_and_unchanged(self):
        self.link.symlink_to('bashcmdr')
        self.ok(self.shell('[[ $BASHCMDR_BOOT_EXIT_CODE == 0 && ${BASHCMDR_BOOT_SUMMARY[shortcut]-} == ready ]]', bios=True))
        self.assertEqual(os.readlink(self.link), 'bashcmdr')
        self.assertEqual(self.trace.read_text(), '')

    def test_regular_file_boot_preserves_content_and_records_conflict(self):
        self.link.write_text('preserve unrelated contents\n')
        self.ok(self.shell('[[ ${BASHCMDR_BOOT_SUMMARY[shortcut]-} == conflict ]]', bios=True))
        self.assertEqual(self.link.read_text(), 'preserve unrelated contents\n')
        self.assertEqual(self.trace.read_text(), '')

    def test_wrong_and_dangling_links_boot_preserves_targets(self):
        for target in ['../VERSION', 'absent']:
            with self.subTest(target=target):
                self.link.symlink_to(target)
                try:
                    self.ok(self.shell('[[ ${BASHCMDR_BOOT_SUMMARY[shortcut]-} == conflict ]]', bios=True))
                    self.assertEqual(os.readlink(self.link), target)
                finally:
                    self.link.unlink()
        self.assertEqual(self.trace.read_text(), '')

    def test_existing_directory_is_not_modified_at_boot(self):
        self.link.mkdir()
        (self.link / 'keep').write_text('preserve')
        self.ok(self.shell('[[ ${BASHCMDR_BOOT_SUMMARY[shortcut]-} == conflict ]]', bios=True))
        self.assertEqual((self.link / 'keep').read_text(), 'preserve')
        self.assertEqual(self.trace.read_text(), '')

    def test_readonly_bin_boot_never_attempts_shortcut_write(self):
        self.readonly()
        self.ok(self.shell('[[ $BASHCMDR_BOOT_EXIT_CODE == 0 && ${BASHCMDR_BOOT_SUMMARY[shortcut]-} == missing ]]', bios=True))
        self.assertEqual(self.trace.read_text(), '')
        self.assertFalse(self.link.is_symlink())

    def test_readonly_tree_boot_reports_runtime_failure_without_install_write(self):
        self.readonly(whole_tree=True)
        before = self.snapshot()
        result = self.shell('[[ $BASHCMDR_BOOT_EXIT_CODE == 1 && ${BASHCMDR_BOOT_SUMMARY[shortcut]-} == missing ]]', bios=True)
        self.ok(result)
        self.assertIn('Cannot initialize state directory', result.stderr)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.trace.read_text(), '')

    def test_shortcut_status_is_actionable_and_creates_no_runtime_paths(self):
        before = self.snapshot()
        result = self.shell('main console shortcut')
        self.ok(result)
        self.assertIn('bcm shortcut: missing', result.stdout)
        self.assertIn('console shortcut --install', result.stdout)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.trace.read_text(), '')

    def test_status_on_readonly_tree_still_works(self):
        self.readonly(whole_tree=True)
        before = self.snapshot()
        self.ok(self.shell('main console shortcut'))
        self.assertEqual(self.snapshot(), before)

    def test_status_through_alias_has_no_runtime_initialization(self):
        aliases = self.home / '.bashcmdr/aliases.json'
        aliases.parent.mkdir()
        aliases.write_text(json.dumps({'shortcut-query': 'console shortcut'}))
        before = self.snapshot()
        self.readonly(whole_tree=True)
        result = self.shell('main shortcut-query')
        self.ok(result)
        self.assertIn('bcm shortcut: missing', result.stdout)
        self.assertEqual(self.snapshot(), before)

    def test_explicit_install_creates_only_expected_link(self):
        before = self.snapshot()
        result = self.shell('main console shortcut --install')
        self.ok(result)
        self.assertIn('bcm shortcut: ready', result.stdout)
        self.assertEqual(os.readlink(self.link), 'bashcmdr')
        after = self.snapshot()
        self.assertEqual(set(after) - set(before), {'console/bin/bcm'})
        self.assertTrue(all(after[k] == v for k, v in before.items()))
        self.assertEqual(self.trace.read_text().count('ln<'), 1)

    def test_repeated_explicit_install_is_idempotent(self):
        self.link.symlink_to('bashcmdr')
        self.ok(self.shell('main console shortcut --install\nmain console shortcut --install'))
        self.assertEqual(self.trace.read_text(), '')

    def test_conflicting_file_explicit_install_fails_without_overwrite(self):
        self.link.write_text('preserve')
        result = self.shell('main console shortcut --install')
        self.assertEqual(result.returncode, 1)
        self.assertIn('was preserved', result.stdout)
        self.assertEqual(self.link.read_text(), 'preserve')
        self.assertEqual(self.trace.read_text(), '')

    def test_conflicting_links_and_directory_refuse_explicit_install(self):
        for target in ['../VERSION', 'absent']:
            self.link.symlink_to(target)
            self.assertEqual(self.shell('main console shortcut --install').returncode, 1)
            self.assertEqual(os.readlink(self.link), target)
            self.link.unlink()
        self.link.mkdir()
        self.assertEqual(self.shell('main console shortcut --install').returncode, 1)
        self.assertEqual(list(self.link.iterdir()), [])
        self.assertEqual(self.trace.read_text(), '')

    def test_permission_denied_install_is_nonzero_and_leaves_no_runtime(self):
        self.readonly()
        before = self.snapshot()
        result = self.shell('main console shortcut --install')
        self.assertEqual(result.returncode, 1)
        self.assertIn('Cannot install bcm shortcut', result.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_noop_successful_ln_is_detected(self):
        result = self.shell('ln() { return 0; }\nmain console shortcut --install')
        self.assertEqual(result.returncode, 1)
        self.assertIn('did not produce the expected link', result.stderr)
        self.assertFalse(self.link.exists())

    def test_link_failure_and_missing_tool_are_propagated(self):
        for code in [73, 127]:
            with self.subTest(code=code):
                result = self.shell('ln() { return ' + str(code) + '; }\nmain console shortcut --install')
                self.assertEqual(result.returncode, 1)
                self.assertIn('Cannot install bcm shortcut', result.stderr)

    def test_linked_bin_directory_is_not_a_write_destination(self):
        directory = self.console / 'bin'
        alternate = self.console / 'actual-bin'
        directory.rename(alternate)
        directory.symlink_to('actual-bin')
        result = self.shell('console_shortcut --install')
        self.assertEqual(result.returncode, 1)
        self.assertIn('ordinary selected bin directory', result.stderr)
        self.assertEqual(self.trace.read_text(), '')

    def test_bad_arguments_never_create_paths(self):
        before = self.snapshot()
        for args in ['--force', '--install extra', "''", '--']:
            result = self.shell('main console shortcut ' + args)
            self.assertEqual(result.returncode, 1)
            self.assertIn('Usage:', result.stderr)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.trace.read_text(), '')

    def test_help_route_has_no_runtime_writes(self):
        before = self.snapshot()
        result = self.shell('main console shortcut --help')
        self.ok(result)
        self.assertIn('creates only a missing', result.stdout)
        self.assertEqual(self.snapshot(), before)

    def test_postbios_status_uses_surviving_selected_root(self):
        result = self.shell('main console shortcut', bios=True)
        self.ok(result)
        self.assertIn('bcm shortcut: missing', result.stdout)
        self.assertEqual(self.trace.read_text(), '')

    def test_strict_shell_supports_status_install_and_conflict(self):
        result = self.shell('set -euo pipefail\nmain console shortcut\n'
                            'main console shortcut --install\nmain console shortcut')
        self.ok(result)

    def test_reported_install_command_handles_spaces_and_is_runnable(self):
        result = self.shell('main console shortcut')
        self.ok(result)
        command = result.stdout.split('To install a missing shortcut, run: ', 1)[1].strip()
        result = self.shell(command)
        self.ok(result)
        self.assertEqual(os.readlink(self.link), 'bashcmdr')

    def test_completion_includes_shortcut_and_install_option(self):
        result = self.shell(r'''
source "$CONSOLE/boot/completions.bash"
_init_completion() { cur=''; prev=console; words=(bcm console ''); cword=2; }
__bcm_completions
printf '%s\n' "${COMPREPLY[@]}"
_init_completion() { cur='--'; prev=shortcut; words=(bcm console shortcut --); cword=3; }
__bcm_completions
printf '%s\n' "${COMPREPLY[@]}"
''')
        self.ok(result)
        self.assertIn('shortcut', result.stdout.splitlines())
        self.assertIn('--install', result.stdout.splitlines())


if __name__ == '__main__':
    unittest.main(verbosity=2)
