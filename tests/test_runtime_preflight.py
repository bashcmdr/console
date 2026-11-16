#!/usr/bin/env python3
"""Prerequisite admission and completion in owned code/HOME/tool environments."""
import json
import os
import pathlib
import shlex
import shutil
import subprocess
import tempfile
import unittest

REPO = pathlib.Path(os.environ.get('RUNTIME_TEST_REPO', pathlib.Path(__file__).resolve().parent.parent))
BASH = os.environ.get('RUNTIME_TEST_BASH') or shutil.which('bash')


class RuntimeFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='bcm-prerequisites-')
        self.addCleanup(self.temporary.cleanup)
        self.top = pathlib.Path(self.temporary.name)
        self.repo = self.top / "console 'copy'"
        self.repo.mkdir()
        for part in ['bin', 'boot', 'lib']:
            shutil.copytree(REPO / part, self.repo / part, symlinks=True)
        shutil.copyfile(REPO / 'VERSION', self.repo / 'VERSION')
        self.home = self.top / 'home'
        self.home.mkdir()
        self.tmp = self.top / 'tmp'
        self.tmp.mkdir()
        self.tools = self.top / 'tools'
        self.tools.mkdir()
        self.trace = self.top / 'operations'
        self.trace.write_text('')
        for name in ['cat', 'dirname', 'basename', 'readlink', 'mkdir', 'rm', 'mv', 'rmdir',
                     'ln', 'date', 'tail', 'wc', 'find', 'stat', 'env', 'sort', 'mktemp',
                     'head', 'cut', 'grep', 'sed', 'jq']:
            binary = shutil.which(name)
            if binary:
                (self.tools / name).symlink_to(binary)
        (self.tools / 'bash').symlink_to(BASH)
        # A clone can never reach the network, even against a faulty baseline.
        git = self.tools / 'git'
        git.write_text('#!' + BASH + '\nprintf "UNEXPECTED-GIT\\n" >> ' + shlex.quote(str(self.trace)) + '\nexit 37\n')
        git.chmod(0o755)
        self.env = {'HOME': str(self.home), 'PATH': str(self.tools), 'TMPDIR': str(self.tmp),
                    'BASHCMDR_ROOT_DIR': str(self.repo), 'TRACE': str(self.trace),
                    'LC_ALL': 'C', 'TERM': 'dumb', 'BASHCMDR_VERBOSITY': '1'}
        self.calls = []
        for name, dependencies in [('demo', {'dep': '>=1.0.0', 'leaf': '>=1.0.0'}), ('dep', {}), ('leaf', {})]:
            directory = self.repo / 'cartridges' / name
            directory.mkdir(parents=True)
            (directory / 'manifest.json').write_text(json.dumps({'name': name, 'version': '1.0.0',
                'requires': {'cartridges': dependencies}}))
            (directory / 'main.bashcmdr').write_text('cartridge_dispatch() { printf "%s:%s\\n" ' + name + ' "$1" >> "$TRACE"; }\n')

    def tearDown(self):
        destination = os.environ.get('RUNTIME_TEST_EVIDENCE_DIR')
        if destination:
            path = pathlib.Path(destination) / self.id().split('.')[-1]
            path.mkdir(parents=True, exist_ok=True)
            (path / 'calls.json').write_text(json.dumps(self.calls, indent=2) + '\n')
            shutil.copyfile(self.trace, path / 'operations.log')
            if (self.home / 'legacy.log').is_file():
                shutil.copyfile(self.home / 'legacy.log', path / 'legacy.log')

    def missing(self, *names):
        for name in names:
            (self.tools / name).unlink(missing_ok=True)

    def shell(self, body):
        argv = [BASH, '--noprofile', '--norc', '-c', body]
        p = subprocess.run(argv, cwd=self.repo, env=self.env, text=True, capture_output=True, timeout=15)
        self.calls.append({'argv': argv, 'exit': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr})
        return p

    def cli(self, *args):
        return self.shell('"$BASH" bin/bashcmdr ' + ' '.join(shlex.quote(x) for x in args))

    def ok(self, p):
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def failed(self, p, status=1):
        self.assertEqual(p.returncode, status, p.stdout + p.stderr)

    def snapshot(self):
        result = {}
        for directory in [self.repo, self.home, self.tmp]:
            for p in directory.rglob('*'):
                key = str(p.relative_to(self.top))
                result[key] = ('link', str(p.readlink())) if p.is_symlink() else ('file', p.read_bytes()) if p.is_file() else ('directory',)
        return result

    def active(self, *names, complete=False):
        if complete:
            for state in ['active', 'inactive', 'quarantine', 'broken']:
                (self.repo / 'console' / state).mkdir(parents=True, exist_ok=True)
        for name in names:
            directory = self.repo / 'console/active'
            directory.mkdir(parents=True, exist_ok=True)
            (directory / name).symlink_to('../../cartridges/' + name)


class RuntimePreflightTests(RuntimeFixture):
    def test_legacy_assertions_capture_failure_without_disabling_strict_mode(self):
        shutil.copyfile(REPO / 'tests/assertions.bash', self.repo / 'assertions.bash')
        p = self.shell('''set -euo pipefail
TEST_LOG="$HOME/legacy.log"
source assertions.bash
expected_failure() { printf 'failure-output\\n'; return 37; }
before=$-
if bcm_test_eval expected_failure; then exit 91; else status=$?; fi
[[ $status == 37 && $- == "$before" ]] || exit 92
bcm_test_eval 'EVAL_ASSIGNMENT=kept'
[[ $EVAL_ASSIGNMENT == kept && $- == "$before" ]] || exit 93
''')
        self.ok(p)
        log = (self.home / 'legacy.log').read_text()
        self.assertIn('failure-output', log)
        self.assertIn('Exit: 37', log)
        self.assertIn('Exit: 0', log)

    def test_json_commands_missing_jq_fail_before_runtime_mutation(self):
        self.missing('jq')
        before = self.snapshot()
        for verb in ['plug', 'unplug', 'uninstall', 'quarantine', 'show', 'search', 'deps', 'plan', 'graph', 'why']:
            with self.subTest(verb=verb):
                p = self.cli('cartridge', verb, 'demo'); self.failed(p)
                self.assertIn("Required tool 'jq'", p.stderr)
                self.assertNotIn('command not found', p.stderr)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.trace.read_text(), '')

    def test_install_missing_git_is_explicit_before_clone_or_runtime_creation(self):
        self.missing('git')
        before = self.snapshot()
        p = self.cli('cartridge', 'install', 'fresh', '--from', 'https://example.invalid/repo')
        self.failed(p); self.assertIn("Required tool 'git'", p.stderr)
        self.assertNotIn('Failed to clone', p.stderr)
        self.assertEqual(before, self.snapshot())

    def test_install_missing_jq_never_calls_git(self):
        self.missing('jq')
        before = self.snapshot()
        p = self.cli('cartridge', 'install', 'fresh', '--from', 'https://example.invalid/repo')
        self.failed(p); self.assertIn("Required tool 'jq'", p.stderr)
        self.assertEqual(self.trace.read_text(), '')
        self.assertEqual(before, self.snapshot())

    def test_doctor_reports_both_missing_tools_without_repair(self):
        self.missing('jq', 'git')
        self.active('missing')
        before = self.snapshot()
        p = self.cli('doctor'); self.failed(p)
        self.assertIn("Required tool 'jq'", p.stderr)
        self.assertIn("Required tool 'git'", p.stderr)
        self.assertEqual(before, self.snapshot())

    def test_direct_doctor_has_the_same_missing_tool_guard(self):
        self.missing('jq', 'git')
        before = self.snapshot()
        p = self.shell('source bin/bashcmdr\ndoctor_cmd'); self.failed(p)
        self.assertIn("Required tool 'git'", p.stderr)
        self.assertEqual(before, self.snapshot())

    def test_missing_jq_cannot_replace_cached_dependency_edges(self):
        self.missing('jq')
        p = self.shell('''source bin/bashcmdr
declare -gA BASHCMDR_DEPENDENCY_GRAPH=([demo]=retained)
__bashcmdr_load_dependencies demo; status=$?
[[ $status == 1 && ${BASHCMDR_DEPENDENCY_GRAPH[demo]} == retained ]]
''')
        self.ok(p); self.assertIn("Required tool 'jq'", p.stderr)

    def test_failed_partial_jq_cannot_replace_cache_or_publish_plan(self):
        p = self.shell('''source bin/bashcmdr
declare -gA BASHCMDR_DEPENDENCY_GRAPH=([demo]=retained)
jq() { printf 'dep:>=1.0.0\\n'; return 37; }
__bashcmdr_load_dependencies demo; status=$?
[[ $status == 1 && ${BASHCMDR_DEPENDENCY_GRAPH[demo]} == retained ]] || exit 91
plan=$(bashcmdr_get_activation_plan demo); status=$?
[[ $status == 1 && -z $plan ]]
''')
        self.ok(p); self.assertIn('jq could not read dependency manifest', p.stderr)
        self.assertEqual(self.trace.read_text(), '')

    def test_valid_empty_dependency_object_remains_successful(self):
        p = self.shell('source bin/bashcmdr\n__bashcmdr_load_dependencies dep || exit $?\n[[ -z ${BASHCMDR_DEPENDENCY_GRAPH[dep]} ]]')
        self.ok(p)

    def test_strict_mode_resolver_handles_initially_empty_visited_array(self):
        p = self.shell('''set -euo pipefail
source bin/bashcmdr
before=$-
bashcmdr_resolve_dependencies demo
[[ ${#BASHCMDR_ACTIVATION_ORDER[@]} == 3 && ${BASHCMDR_ACTIVATION_ORDER[2]} == demo ]] || exit 91
[[ $- == "$before" ]] || exit 92
''')
        self.ok(p)

    def test_invalid_manifest_documents_and_declarations_never_publish_edges(self):
        manifest = self.repo / 'cartridges/demo/manifest.json'
        values = ['{partial', '[]', 'null', '{}\n{}', '{"requires":{"cartridges":false}}',
                  '{"requires":{"cartridges":{"../escape":">=1.0.0"}}}',
                  '{"requires":{"cartridges":{"dep":3}}}', '{"requires":{"cartridges":{"dep":""}}}']
        values.extend(json.dumps({'requires': {'cartridges': {'dep': value}}})
                      for value in ['>=1.0.0\nleaf:>=1.0.0', '>=1.0.0\x00', '>=1.0.0\t'])
        for value in values:
            with self.subTest(value=value):
                manifest.write_text(value)
                p = self.shell('''source bin/bashcmdr
declare -gA BASHCMDR_DEPENDENCY_GRAPH=([demo]=retained)
__bashcmdr_load_dependencies demo; status=$?
[[ $status == 1 && ${BASHCMDR_DEPENDENCY_GRAPH[demo]} == retained ]]
''')
                self.ok(p)
                self.assertIn('jq could not read dependency manifest', p.stderr)

    def test_failed_version_query_cannot_be_treated_as_a_version(self):
        p = self.shell('''source bin/bashcmdr
jq() { if [[ $* == *'.version'* ]]; then printf '99.0.0\\n'; return 37; fi; command jq "$@"; }
plan=$(bashcmdr_get_activation_plan demo); status=$?
[[ $status == 1 && -z $plan ]]
''')
        self.ok(p); self.assertIn('jq could not read dependency version', p.stderr)

    def test_dependency_version_type_is_checked_before_comparison(self):
        path = self.repo / 'cartridges/dep/manifest.json'
        data = json.loads(path.read_text())
        for value in [3, False, ['1.0.0'], {'version': '1.0.0'}]:
            with self.subTest(value=value):
                data['version'] = value
                path.write_text(json.dumps(data))
                p = self.shell('source bin/bashcmdr\nplan=$(bashcmdr_get_activation_plan demo); status=$?\n[[ $status == 1 && -z $plan ]]')
                self.ok(p); self.assertIn('jq could not read dependency version', p.stderr)

    def test_unplug_does_not_ignore_failed_dependent_inspection(self):
        self.active('demo', 'dep', 'leaf', complete=True)
        before = self.snapshot()
        p = self.shell('''source bin/bashcmdr
__bashcmdr_sync_physical_state || exit $?
jq() { printf 'partial\\n'; return 37; }
bashcmdr_unplug_cartridge dep; status=$?
[[ $status == 1 ]]
''')
        self.ok(p)
        self.assertEqual(self.trace.read_text(), '')
        self.assertEqual(before, self.snapshot())

    def test_manifest_guard_missing_jq_is_not_an_optional_bypass(self):
        self.missing('jq')
        p = self.shell('source bin/bashcmdr\nbashcmdr_guard_validate demo "$BASHCMDR_ROOT/cartridges/demo/manifest.json"')
        self.failed(p); self.assertIn("Required tool 'jq'", p.stderr)

    def test_registry_missing_jq_is_not_invalid_json(self):
        index = self.home / '.bashcmdr/registry/index.json'
        index.parent.mkdir(parents=True)
        index.write_text('{"cartridges":{}}')
        self.missing('jq')
        p = self.shell('source bin/bashcmdr\nbashcmdr_load_registry_index')
        self.failed(p); self.assertIn("Required tool 'jq'", p.stderr)
        self.assertNotIn('Invalid registry index JSON', p.stderr)

    def test_empty_boot_needs_neither_jq_nor_git(self):
        self.missing('jq', 'git')
        p = self.shell('source boot/shell-init.bashcmdr\n[[ $BASHCMDR_BOOT_EXIT_CODE == 0 ]]')
        self.ok(p); self.assertEqual(p.stderr, '')
        self.assertEqual(self.trace.read_text(), '')

    def test_active_boot_missing_jq_stops_before_runtime_creation_or_hooks(self):
        self.active('demo')
        self.missing('jq')
        before = self.snapshot()
        p = self.shell('source bin/bashcmdr\nconsole_poweron')
        self.failed(p); self.assertIn("Required tool 'jq'", p.stderr)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.trace.read_text(), '')

    def test_wholly_quarantined_boot_without_jq_never_loads_the_provider(self):
        self.active('demo')
        directory = self.repo / 'console/quarantine'
        directory.mkdir()
        (directory / 'demo').symlink_to('../../cartridges/demo')
        self.missing('jq', 'git')
        p = self.shell('source boot/shell-init.bashcmdr\n[[ $BASHCMDR_BOOT_EXIT_CODE == 0 ]]')
        self.ok(p)
        self.assertEqual(self.trace.read_text(), '')
        self.assertTrue((directory / 'demo').is_symlink())

    def test_present_json_tool_keeps_dependency_order_and_hooks(self):
        self.ok(self.cli('cartridge', 'plug', 'demo'))
        rows = self.trace.read_text().splitlines()
        self.assertEqual(set(rows), {'dep:activate', 'leaf:activate', 'demo:activate'})
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[-1], 'demo:activate')

    def test_help_and_version_remain_useful_without_json_or_git(self):
        self.missing('jq', 'git')
        for argv in [('help',), ('doctor', '--help'), ('cartridge', 'install', 'demo', '--help')]:
            with self.subTest(argv=argv):
                before = self.snapshot(); self.ok(self.cli(*argv)); self.assertEqual(before, self.snapshot())
        self.ok(self.cli('version'))
        self.assertEqual(self.trace.read_text(), '')

    def test_saved_alias_resolution_requires_jq_before_runtime_mutation(self):
        file = self.home / '.bashcmdr/aliases.json'
        file.parent.mkdir()
        file.write_text('{"cs":"cartridge show"}')
        self.missing('jq')
        before = self.snapshot()
        p = self.cli('cs', 'demo'); self.failed(p)
        self.assertIn("Required tool 'jq'", p.stderr)
        self.assertEqual(before, self.snapshot())
        self.ok(self.cli('help'))
        self.assertEqual(before, self.snapshot())

    def test_saved_alias_failed_jq_has_an_explicit_error(self):
        file = self.home / '.bashcmdr/aliases.json'
        file.parent.mkdir()
        file.write_text('{partial')
        before = self.snapshot()
        p = self.cli('cs', 'demo'); self.failed(p)
        self.assertIn('jq could not read saved command shortcuts', p.stderr)
        self.assertEqual(before, self.snapshot())

    def test_present_jq_keeps_saved_alias_dispatch_correct(self):
        file = self.home / '.bashcmdr/aliases.json'
        file.parent.mkdir()
        file.write_text('{"activate-demo":"cartridge plug"}')
        self.ok(self.cli('activate-demo', 'demo'))
        rows = self.trace.read_text().splitlines()
        self.assertEqual(set(rows), {'dep:activate', 'leaf:activate', 'demo:activate'})
        self.assertEqual(rows[-1], 'demo:activate')

    def complete(self, state, prelude=''):
        return self.shell('source boot/completions.bash\n' + prelude + '\n' + state + '\nCOMPREPLY=(stale)\n__bcm_completions; status=$?\nprintf "STATUS=%s\\n" "$status"\nprintf "[%s]\\n" "${COMPREPLY[@]}"')

    def test_completion_without_optional_helper_has_static_suggestions(self):
        p = self.complete('COMP_WORDS=(bcm c); COMP_CWORD=1')
        self.ok(p); self.assertIn('[console]', p.stdout); self.assertIn('[cartridge]', p.stdout)
        self.assertIn('STATUS=0', p.stdout); self.assertEqual(p.stderr, '')

    def test_completion_without_jq_keeps_installed_suggestions_quietly(self):
        self.missing('jq')
        p = self.complete('COMP_WORDS=(bcm cartridge show ""); COMP_CWORD=3')
        self.ok(p)
        for name in ['demo', 'dep', 'leaf']:
            self.assertIn('[' + name + ']', p.stdout)
        self.assertEqual(p.stderr, '')

    def test_completion_fallback_resolves_aliases_with_json_available(self):
        file = self.home / '.bashcmdr/aliases.json'
        file.parent.mkdir()
        file.write_text('{"cs":"cartridge show"}')
        p = self.complete('COMP_WORDS=(bcm cs ""); COMP_CWORD=2')
        self.ok(p); self.assertIn('[demo]', p.stdout); self.assertNotIn('[install]', p.stdout)
        self.assertEqual(p.stderr, '')

    def test_optional_completion_helper_is_used_when_present(self):
        p = self.complete('', '_init_completion() { words=(bcm cartridge list ""); cword=3; cur=""; prev=list; }')
        self.ok(p); self.assertIn('[active]', p.stdout); self.assertEqual(p.stderr, '')

    def test_failed_optional_helper_clears_stale_completion_without_noise(self):
        p = self.complete('', '_init_completion() { return 1; }')
        self.ok(p); self.assertNotIn('[stale]', p.stdout); self.assertEqual(p.stderr, '')

    def test_invalid_completion_state_is_not_arithmetic_or_shell_source(self):
        for state in ['unset COMP_WORDS COMP_CWORD', 'COMP_WORDS=(bcm c); COMP_CWORD="08"',
                      'COMP_WORDS=(bcm c); COMP_CWORD=\'1+$(touch NOT-RUN)\'']:
            with self.subTest(state=state):
                p = self.complete(state); self.ok(p)
                self.assertEqual(p.stderr, ''); self.assertNotIn('[stale]', p.stdout)
                self.assertFalse((self.repo / 'NOT-RUN').exists())

    def test_failed_partial_json_completion_is_not_presented_as_names(self):
        directory = self.home / '.bashcmdr/registry'
        directory.mkdir(parents=True)
        (directory / 'index.json').write_text('{"cartridges":{}}')
        p = self.complete('COMP_WORDS=(bcm cartridge show ""); COMP_CWORD=3',
                          'jq() { printf "not-a-complete-result\\n"; return 37; }')
        self.ok(p); self.assertNotIn('not-a-complete-result', p.stdout); self.assertIn('[demo]', p.stdout)
        self.assertEqual(p.stderr, '')

    def test_absent_programmable_completion_builtin_is_nonfatal(self):
        p = self.shell('enable -n complete\nsource boot/completions.bash\nstatus=$?\n[[ $status == 0 ]]')
        self.ok(p); self.assertEqual(p.stderr, '')


class BashAdmissionTests(RuntimeFixture):
    def test_actual_interpreter_cli_admission_before_runtime_mutation(self):
        before = self.snapshot()
        p = self.cli('version')
        if os.environ.get('RUNTIME_EXPECT_REJECTION') == '1':
            self.failed(p, 12); self.assertIn('requires Bash 4.3 or newer', p.stderr)
            self.assertNotIn('invalid option', p.stderr); self.assertEqual(before, self.snapshot())
        else:
            self.ok(p); self.assertIn('bashcmdr version', p.stdout)

    def test_actual_interpreter_sourced_cli_has_explicit_status(self):
        before = self.snapshot()
        p = self.shell('source bin/bashcmdr; status=$?; printf "SOURCE=%s\\n" "$status"')
        self.ok(p)
        expected = '12' if os.environ.get('RUNTIME_EXPECT_REJECTION') == '1' else '0'
        self.assertIn('SOURCE=' + expected, p.stdout)
        self.assertEqual(before, self.snapshot())

    def test_actual_interpreter_bios_keeps_shell_nonfatal_and_records_outcome(self):
        before = self.snapshot()
        p = self.shell('source boot/shell-init.bashcmdr; status=$?; printf "SOURCE=%s BASIC=%s BOOT=%s\\n" "$status" "${BASHCMDR_BOOT_BASIC_EXIT_CODE-unset}" "${BASHCMDR_BOOT_EXIT_CODE-unset}"')
        self.ok(p)
        if os.environ.get('RUNTIME_EXPECT_REJECTION') == '1':
            self.assertIn('SOURCE=0 BASIC=12 BOOT=12', p.stdout)
            self.assertIn('requires Bash 4.3 or newer', p.stderr)
            self.assertNotIn('invalid option', p.stderr); self.assertEqual(before, self.snapshot())
        else:
            self.assertIn('SOURCE=0 BASIC=0 BOOT=0', p.stdout)


if __name__ == '__main__':
    if not os.environ.get('RUNTIME_TEST_EVIDENCE_DIR'):
        parent = REPO / 'tests/results'
        parent.mkdir(parents=True, exist_ok=True)
        os.environ['RUNTIME_TEST_EVIDENCE_DIR'] = tempfile.mkdtemp(prefix='runtime-preflight.', dir=parent)
    evidence = pathlib.Path(os.environ['RUNTIME_TEST_EVIDENCE_DIR'])
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / 'runner.json').write_text(json.dumps({'binary': BASH, 'repo': str(REPO),
        'expected_rejection': os.environ.get('RUNTIME_EXPECT_REJECTION') == '1'}, indent=2) + '\n')
    print('Runtime preflight artifacts: ' + str(evidence), flush=True)
    unittest.main(verbosity=2)
