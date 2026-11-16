#!/usr/bin/env python3
"""Help is read-only; aliases and expanded completion retain defined semantics."""
import json
import os
import pathlib
import shlex
import shutil
import subprocess
import tempfile
import unittest

REPO = pathlib.Path(os.environ.get('ALIAS_HELP_TEST_REPO', pathlib.Path(__file__).resolve().parent.parent))
VERBS = {
    'console': ['poweron', 'poweroff', 'status', 'shortcut', 'reset', 'upgrade', 'uninstall', 'log'],
    'cartridge': ['install', 'uninstall', 'upgrade', 'plug', 'unplug', 'quarantine', 'release',
                  'show', 'list', 'search', 'deps', 'plan', 'graph', 'why', 'diagnose'],
    'registry': ['sync', 'list', 'status'],
    'alias': ['list', 'remove'],
}


class AliasHelpTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='bcm-alias-help-')
        self.addCleanup(self.temporary.cleanup)
        self.top = pathlib.Path(self.temporary.name)
        self.repo = self.top / "source 'copy'"
        self.repo.mkdir()
        for part in ['bin', 'boot', 'lib']:
            shutil.copytree(REPO / part, self.repo / part, symlinks=True)
        shutil.copyfile(REPO / 'VERSION', self.repo / 'VERSION')
        self.home = self.top / 'home'
        self.home.mkdir()
        self.aliases = self.home / '.bashcmdr/aliases.json'
        self.bash = shutil.which('bash')
        self.tools = self.top / 'inert tools'
        self.tools.mkdir()
        self.tool_canary = self.top / 'unexpected-tool-calls'
        for name in ['git', 'curl', 'wget', 'sudo']:
            tool = self.tools / name
            tool.write_text('#!' + self.bash + '\nprintf "%s\\n" ' + shlex.quote(name) +
                            ' >> ' + shlex.quote(str(self.tool_canary)) + '\nexit 99\n')
            tool.chmod(0o755)
        self.env = {'HOME': str(self.home), 'PATH': str(self.tools) + os.pathsep + str(self.repo / 'bin') + os.pathsep + os.environ.get('PATH', os.defpath),
                    'LC_ALL': 'C', 'TERM': 'dumb', 'BASHCMDR_VERBOSITY': '3'}
        self.calls = []

    def tearDown(self):
        evidence = os.environ.get('ALIAS_HELP_TEST_EVIDENCE_DIR')
        if evidence:
            destination = pathlib.Path(evidence) / self.id().split('.')[-1]
            destination.mkdir(parents=True, exist_ok=True)
            (destination / 'calls.json').write_text(json.dumps(self.calls, indent=2) + '\n')
            if self.tool_canary.exists():
                shutil.copyfile(self.tool_canary, destination / 'unexpected-tool-calls')
        self.assertFalse(self.tool_canary.exists(), 'Help must not invoke installer, network or privileged tools')

    def run_command(self, argv, extra=None):
        p = subprocess.run(argv, cwd=self.repo, env={**self.env, **(extra or {})}, text=True,
                           capture_output=True, timeout=15)
        self.calls.append({'argv': argv, 'exit': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr})
        return p

    def cli(self, *args):
        return self.run_command([self.bash, '--noprofile', '--norc', 'bin/bashcmdr', *args])

    def shell(self, script, extra=None):
        return self.run_command([self.bash, '--noprofile', '--norc', '-c', script], extra)

    def ok(self, p):
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def failed(self, p, code=1):
        self.assertEqual(p.returncode, code, p.stdout + p.stderr)

    def store(self, data):
        self.aliases.parent.mkdir(parents=True, exist_ok=True)
        self.aliases.write_text(json.dumps(data) + '\n')

    def snapshot(self):
        result = {}
        for root in [self.repo, self.home]:
            for p in root.rglob('*'):
                key = str(p.relative_to(self.top))
                if p.is_symlink():
                    result[key] = ('link', str(p.readlink()))
                elif p.is_file():
                    result[key] = ('file', p.read_bytes())
                elif p.is_dir():
                    result[key] = ('directory',)
        return result

    def completion(self, words):
        script = ('source boot/completions.bash\n'
                  '_init_completion() { words=(' + ' '.join(shlex.quote(x) for x in words) + '); '
                  'cword=' + str(len(words) - 1) + '; cur=${words[cword]}; prev=${words[cword-1]}; }\n'
                  'COMPREPLY=(); __bcm_completions; printf "%s\\n" "${COMPREPLY[@]}"')
        p = self.shell(script)
        self.ok(p)
        return p.stdout.splitlines() if p.stdout.strip() else []

    def completion_fixture(self):
        self.store({'cs': 'cartridge show', 'ci': 'cartridge install', 'cart': 'cartridge',
                    'cl': 'cartridge list', 'cp': 'cartridge plug', 'cu': 'cartridge unplug',
                    'cq': 'cartridge quarantine', 'cr': 'cartridge release',
                    'css': 'console shortcut', 'ch': 'help cartridge', 'ar': 'alias remove',
                    'url': 'cartridge install --from', 'sr': 'cartridge search'})
        registry = self.aliases.parent / 'registry/index.json'
        registry.parent.mkdir()
        registry.write_text('{"cartridges":{"registry-only":{"name":"registry-only"}}}\n')
        (self.repo / 'cartridges/installed-demo').mkdir(parents=True)
        for state in ['active', 'quarantine']:
            directory = self.repo / 'console' / state
            directory.mkdir(parents=True)
            (directory / (state + '-demo')).symlink_to('../../cartridges/installed-demo', target_is_directory=True)

    def test_top_and_firmware_help_routes_are_read_only(self):
        before = self.snapshot()
        for argv in [(), ('help',), ('-h',), ('--help',), ('help', '--help')]:
            with self.subTest(argv=argv):
                p = self.cli(*argv); self.ok(p); self.assertIn('USAGE', p.stdout)
        for noun in ['version', 'doctor', 'help', 'alias']:
            for argv in [('help', noun), (noun, '-h'), (noun, '--help')]:
                with self.subTest(argv=argv):
                    p = self.cli(*argv); self.ok(p)
                    expected = 'USAGE' if noun == 'alias' or argv in [('help', '-h'), ('help', '--help')] else 'Usage:'
                    self.assertIn(expected, p.stdout)
                    self.assertNotIn('Health Check', p.stdout)
        self.assertEqual(before, self.snapshot())

    def test_all_noun_help_forms_are_read_only(self):
        before = self.snapshot()
        for noun in ['console', 'cartridge', 'registry']:
            for argv in [(noun,), (noun, 'help'), (noun, '-h'), (noun, '--help'),
                         ('help', noun), (noun, 'help', '--help')]:
                with self.subTest(argv=argv):
                    p = self.cli(*argv); self.ok(p); self.assertIn('USAGE', p.stdout)
        self.assertEqual(before, self.snapshot())

    def test_every_known_detailed_help_route_has_usage_and_success(self):
        before = self.snapshot()
        for noun, verbs in VERBS.items():
            for verb in verbs:
                for argv in [('help', noun, verb), (noun, verb, '-h'), (noun, verb, '--help')]:
                    with self.subTest(argv=argv):
                        p = self.cli(*argv); self.ok(p)
                        self.assertIn('Usage:', p.stdout)
                        self.assertIn(noun + ' ' + verb, p.stdout)
                        self.assertEqual(p.stderr, '')
        self.assertEqual(before, self.snapshot())

    def test_trailing_help_tokens_do_not_install_remove_or_write_aliases(self):
        self.store({'victim': 'cartridge show'})
        before = self.snapshot()
        for argv in [('cartridge', 'install', 'demo', '--from', 'https://example.invalid/repo', '--help'),
                     ('cartridge', 'uninstall', 'demo', '--purge', '-h'),
                     ('alias', 'remove', 'victim', '--help'),
                     ('alias', 'new-shortcut', 'console status', '--help')]:
            with self.subTest(argv=argv):
                p = self.cli(*argv); self.ok(p)
                self.assertIn('Usage:', p.stdout) if argv[:2] != ('alias', 'new-shortcut') else self.assertIn('USAGE', p.stdout)
        self.assertEqual(before, self.snapshot())

    def test_doctor_help_leaves_corrupt_state_intact(self):
        directory = self.repo / 'console/active'
        directory.mkdir(parents=True)
        (directory / 'missing').symlink_to('../../cartridges/missing')
        before = self.snapshot()
        for flag in ['-h', '--help']:
            p = self.cli('doctor', flag); self.ok(p)
            self.assertNotIn('Health Check', p.stdout)
        self.assertEqual(before, self.snapshot())

    def test_help_works_without_writable_runtime_tree(self):
        if not hasattr(os, 'geteuid') or os.geteuid() == 0:
            self.skipTest('Permission denial requires an ordinary POSIX user')
        self.repo.chmod(0o555)
        try:
            p = self.cli('help', 'cartridge', 'deps')
            self.ok(p)
            self.assertFalse((self.repo / 'console').exists())
        finally:
            self.repo.chmod(0o755)

    def test_unknown_help_routes_fail_without_runtime_changes(self):
        before = self.snapshot()
        for argv in [('help', 'unknown'), ('help', 'console', 'unknown'),
                     ('console', 'unknown', '--help'), ('cartridge', 'unknown', '-h'),
                     ('registry', 'unknown', '--help'), ('unknown', '--help'),
                     ('help', 'cartridge', 'show', 'unexpected')]:
            with self.subTest(argv=argv):
                self.failed(self.cli(*argv))
        self.assertEqual(before, self.snapshot())

    def test_help_failures_propagate_through_main_and_direct_dispatch(self):
        for noun in ['console', 'cartridge', 'registry']:
            for call in ['main ' + noun + ' status --help', noun + '_dispatch status --help']:
                with self.subTest(call=call):
                    self.failed(self.shell('source bin/bashcmdr\nhelp_verb() { return 42; }\n' + call), 42)
        self.failed(self.shell('source bin/bashcmdr\nhelp_top() { return 42; }\nmain --help'), 42)

    def test_help_after_saved_alias_expansion_is_read_only(self):
        self.store({'cs': 'cartridge show', 'health': 'doctor', 'rm': 'alias remove'})
        before = self.snapshot()
        for argv in [('cs', 'demo', '--help'), ('health', '--help'), ('rm', 'cs', '-h')]:
            with self.subTest(argv=argv):
                p = self.cli(*argv); self.ok(p); self.assertIn('Usage:', p.stdout)
        self.assertEqual(before, self.snapshot())

    def test_phase1_stub_help_is_honest_and_operations_still_fail(self):
        for argv in [('console', 'upgrade', '--force'), ('console', 'uninstall', '--keep-config'),
                     ('cartridge', 'upgrade', 'demo'), ('cartridge', 'upgrade', '--all'),
                     ('registry', 'sync')]:
            with self.subTest(argv=argv):
                p = self.cli(*argv, '--help'); self.ok(p)
                self.assertIn('Not implemented in Phase 1', p.stdout)
                p = self.cli(*argv); self.failed(p)
                self.assertIn('not yet implemented', p.stderr)

    def test_missing_alias_removal_fails_and_preserves_exact_store_bytes(self):
        self.store({'keep': 'console status'})
        before = self.aliases.read_bytes()
        p = self.cli('alias', 'remove', 'absent'); self.failed(p)
        self.assertIn('Alias not found', p.stderr)
        self.assertEqual(self.aliases.read_bytes(), before)

    def test_existing_alias_removal_only_removes_selected_key(self):
        self.store({'victim': 'cartridge show', 'keep': 'console status'})
        self.ok(self.cli('alias', 'remove', 'victim'))
        self.assertEqual(json.loads(self.aliases.read_text()), {'keep': 'console status'})

    def test_missing_store_and_missing_operand_fail_without_creating_store(self):
        for argv in [('alias', 'remove', 'absent'), ('alias', 'remove'), ('alias', 'new-name')]:
            with self.subTest(argv=argv):
                self.failed(self.cli(*argv))
                self.assertFalse(self.aliases.parent.exists())

    def test_invalid_or_multiple_alias_documents_fail_without_overwrite(self):
        self.aliases.parent.mkdir()
        for text in ['{partial', '[]', 'null', '{}\n{}\n', '{"keep":"console status"}\n{}']:
            with self.subTest(text=text):
                self.aliases.write_text(text)
                self.failed(self.cli('alias', 'remove', 'keep'))
                self.assertEqual(self.aliases.read_text(), text)

    def test_quoted_alias_keys_remain_json_data(self):
        key = 'quoted"key[$(touch NOT-RUN)]'
        self.store({key: 'console status', 'keep': 'console log'})
        self.ok(self.cli('alias', 'remove', key))
        self.assertEqual(json.loads(self.aliases.read_text()), {'keep': 'console log'})
        self.assertFalse((self.repo / 'NOT-RUN').exists())

    def test_alias_write_permission_failure_is_reported(self):
        if not hasattr(os, 'geteuid') or os.geteuid() == 0:
            self.skipTest('Permission denial requires an ordinary POSIX user')
        self.store({'victim': 'console status'})
        before = self.aliases.read_bytes()
        self.aliases.chmod(0o444)
        try:
            self.failed(self.cli('alias', 'remove', 'victim'))
        finally:
            self.aliases.chmod(0o644)
        self.assertEqual(self.aliases.read_bytes(), before)

    def test_selected_executable_does_not_trigger_alias_conflict_advice(self):
        self.assertTrue((self.repo / 'bin/bcm').samefile(self.repo / 'bin/bashcmdr'))
        p = self.shell('source bin/bashcmdr\nsetup_bcm_alias')
        self.ok(p); self.assertEqual(p.stdout + p.stderr, '')
        self.assertTrue((self.repo / 'bin/bcm').is_symlink())

    def test_existing_shell_alias_is_preserved_with_expansion_on_or_off(self):
        for mode in ['-s', '-u']:
            with self.subTest(mode=mode):
                p = self.shell('shopt ' + mode + ' expand_aliases\nalias bcm="printf retained"\nsource bin/bashcmdr\nsetup_bcm_alias\nstatus=$?\nalias bcm\nexit "$status"')
                self.ok(p); self.assertIn("alias bcm='printf retained'", p.stdout)

    def test_existing_function_is_preserved_and_force_can_shadow_it(self):
        script = 'bcm() { printf retained; }\nsource bin/bashcmdr\nsetup_bcm_alias\nstatus=$?\ndeclare -f bcm\nalias bcm 2>/dev/null || :\nexit "$status"'
        p = self.shell(script); self.failed(p); self.assertIn('printf retained', p.stdout)
        self.assertNotIn("alias bcm='bashcmdr'", p.stdout)
        p = self.shell(script, {'BASHCMDR_FORCE_BCM_ALIAS': '1'}); self.ok(p)
        self.assertIn("alias bcm='bashcmdr'", p.stdout); self.assertIn('printf retained', p.stdout)

    def test_force_alias_shadows_external_command_without_modifying_it(self):
        external = self.top / 'external'
        external.mkdir()
        command = external / 'bcm'
        command.write_text('#!' + self.bash + '\nprintf NEVER-RUN\n')
        command.chmod(0o755)
        before = command.read_bytes()
        path = str(external) + os.pathsep + self.env['PATH']
        script = 'source bin/bashcmdr\nsetup_bcm_alias\nstatus=$?\nalias bcm 2>/dev/null || :\nexit "$status"'
        for force in ['0', 'yes', '1']:
            with self.subTest(force=force):
                p = self.shell(script, {'PATH': path, 'BASHCMDR_FORCE_BCM_ALIAS': force})
                if force == '1':
                    self.ok(p); self.assertIn("alias bcm='bashcmdr'", p.stdout)
                else:
                    self.failed(p); self.assertIn('Preserving existing', p.stdout)
                self.assertNotIn('NEVER-RUN', p.stdout + p.stderr)
                self.assertEqual(command.read_bytes(), before)

    def test_normal_boot_with_own_shortcut_has_no_conflict_advice(self):
        self.assertTrue((self.repo / 'bin/bcm').samefile(self.repo / 'bin/bashcmdr'))
        p = self.shell('source boot/shell-init.bashcmdr\nprintf "BOOT=%s\\n" "$BASHCMDR_BOOT_EXIT_CODE"')
        self.ok(p); self.assertIn('BOOT=0', p.stdout)
        log = (self.repo / 'logs/console-poweron.log').read_text()
        self.assertNotIn('Cannot create', log); self.assertNotIn('Preserving existing', log)

    def test_two_word_alias_completion_matches_canonical_argument_position(self):
        self.completion_fixture()
        for alias, prefix in [('cs', ['cartridge', 'show']), ('ci', ['cartridge', 'install']),
                              ('cp', ['cartridge', 'plug']), ('cu', ['cartridge', 'unplug']),
                              ('cq', ['cartridge', 'quarantine']), ('cr', ['cartridge', 'release'])]:
            with self.subTest(alias=alias):
                actual = self.completion(['bcm', alias, ''])
                self.assertEqual(actual, self.completion(['bcm', *prefix, '']))
                self.assertNotIn('install', actual)
        self.assertIn('registry-only', self.completion(['bcm', 'cs', '']))

    def test_one_word_alias_completion_matches_canonical_verb_position(self):
        self.completion_fixture()
        self.assertEqual(self.completion(['bcm', 'cart', '']), self.completion(['bcm', 'cartridge', '']))
        self.assertIn('install', self.completion(['bcm', 'cart', '']))

    def test_alias_completion_normalizes_flags_filters_and_firmware_commands(self):
        self.completion_fixture()
        for alias, prefix, current in [('css', ['console', 'shortcut'], '--'),
                                       ('cl', ['cartridge', 'list'], ''),
                                       ('sr', ['cartridge', 'search'], '--'),
                                       ('ch', ['help', 'cartridge'], ''),
                                       ('ar', ['alias', 'remove'], '')]:
            with self.subTest(alias=alias):
                self.assertEqual(self.completion(['bcm', alias, current]),
                                 self.completion(['bcm', *prefix, current]))
        self.assertEqual(self.completion(['bcm', 'url', '']), [])
        self.assertIn('--install', self.completion(['bcm', 'css', '--']))
        self.assertIn('cs', self.completion(['bcm', 'ar', '']))

    def test_completion_alias_text_is_not_evaluated(self):
        self.store({'unsafe': 'cartridge show; touch NOT-RUN'})
        self.completion(['bcm', 'unsafe', ''])
        self.assertFalse((self.repo / 'NOT-RUN').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
