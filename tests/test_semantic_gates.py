#!/usr/bin/env python3
"""Negative controls prove that actual runners and the saved CI gate reject faults."""
import copy
import importlib.util
import json
import os
import pathlib
import shlex
import shutil
import subprocess
import tempfile
import textwrap
import unittest

REPO = pathlib.Path(os.environ.get('SEMANTIC_TEST_REPO', pathlib.Path(__file__).resolve().parent.parent))


class SemanticGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bcm-semantic-controls-')
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.repo = self.root / "source 'copy'"
        for part in ['bin', 'boot', 'lib', 'tests', '.github']:
            shutil.copytree(REPO / part, self.repo / part, symlinks=True,
                            ignore=shutil.ignore_patterns('results', '__pycache__'))
        shutil.copyfile(REPO / 'VERSION', self.repo / 'VERSION')
        self.home = self.root / 'home'
        self.tmp = self.root / 'temp parent'
        self.home.mkdir()
        self.tmp.mkdir()
        self.results = self.repo / 'tests/results'
        self.bash = shutil.which('bash')
        self.env = {'HOME': str(self.home), 'PATH': os.environ.get('PATH', os.defpath),
                    'TMPDIR': str(self.tmp), 'LC_ALL': 'C', 'TERM': 'dumb',
                    'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
                    'GIT_ALLOW_PROTOCOL': 'file', 'GIT_TERMINAL_PROMPT': '0'}
        self.calls = []

    def tearDown(self):
        evidence = os.environ.get('SEMANTIC_TEST_EVIDENCE_DIR')
        if evidence:
            destination = pathlib.Path(evidence) / self.id().split('.')[-1]
            destination.mkdir(parents=True, exist_ok=True)
            (destination / 'calls.json').write_text(json.dumps(self.calls, indent=2) + '\n')
            if self.results.exists():
                shutil.copytree(self.results, destination / 'results')

    def run_command(self, argv):
        p = subprocess.run(argv, cwd=self.repo, env=self.env, text=True, capture_output=True, timeout=20)
        self.calls.append({'argv': argv, 'exit': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr})
        return p

    def suite(self, name='factorial'):
        return self.run_command([self.bash, '--noprofile', '--norc', 'tests/' +
                                 ('factorial_test_runner.bash' if name == 'factorial' else 'test_runner.bash')])

    def ci_contract(self):
        workflow = (self.repo / '.github/workflows/test.yml').read_text()
        step = workflow.split('      - name: Run required development checks\n', 1)[1].split('\n      - name:', 1)[0]
        self.assertEqual(step.strip(), 'run: bash --noprofile --norc tests/ci.bash .test-inputs/first-party')
        entry = (self.repo / 'tests/ci.bash').read_text()
        self.assertIn('exec python3 "$root/tests/ci_driver.py" --bash "$BASH" "$@"', entry)
        spec = importlib.util.spec_from_file_location('owned_ci_contract', self.repo / 'tests/ci_driver.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def ci(self):
        return self.run_command(self.ci_contract().rapid_gate_command(self.bash))

    def ci_unit(self):
        return self.run_command(self.ci_contract().shell_suite_commands(self.bash)['test_runner'])

    def ok(self, p):
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def failed(self, p):
        self.assertNotEqual(p.returncode, 0, p.stdout + p.stderr)

    def matrix(self):
        files = list(self.results.glob('factorial.*/rapid_test_results.json'))
        self.assertEqual(len(files), 1)
        return files[0], json.loads(files[0].read_text())

    def normal_matrix(self):
        self.ok(self.suite())
        return self.matrix()

    def mutate(self, relative, needle, replacement):
        p = self.repo / relative
        text = p.read_text()
        self.assertIn(needle, text)
        p.write_text(text.replace(needle, replacement, 1))

    def test_normal_runner_and_ci_accept_complete_reviewed_cases(self):
        path, data = self.normal_matrix()
        self.assertEqual(len(data['results']), 35)
        self.assertTrue(all(row.get('passed') is True for row in data['results']))
        self.assertEqual(sum(row['expected_exit'] == 1 for row in data['results']), 12)
        self.assertTrue(all((path.parent / row['output_log']).is_file() for row in data['results']))
        self.ok(self.ci())

    def test_normal_unit_suite_keeps_56_meaningful_assertions(self):
        p = self.ci_unit()
        self.ok(p)
        self.assertIn('Total tests: 56', p.stdout)

    def test_valid_version_exit1_fails_runner_and_ci(self):
        self.mutate('bin/bashcmdr', 'version_cmd() {', 'version_cmd() {\n    return 1')
        self.failed(self.suite())
        _, data = self.matrix()
        row = next(x for x in data['results'] if x['command'].endswith(' version'))
        self.assertEqual(row['exit_code'], 1)
        self.assertEqual(row.get('expected_exit'), 0)
        self.assertEqual(row['classification'], 'mismatch')
        self.failed(self.ci())

    def test_invalid_command_exit0_fails_runner_and_ci(self):
        self.mutate('bin/bashcmdr', 'main() {', 'main() {\n    if [[ ${1-} == foobar ]]; then return 0; fi')
        self.failed(self.suite())
        _, data = self.matrix()
        row = next(x for x in data['results'] if x['command'].endswith(' foobar status'))
        self.assertEqual(row['exit_code'], 0)
        self.assertEqual(row.get('expected_exit'), 1)
        self.failed(self.ci())

    def test_unexpected_exit42_is_retained_and_fails_both_gates(self):
        self.mutate('bin/bashcmdr', 'version_cmd() {', 'version_cmd() {\n    return 42')
        self.failed(self.suite())
        _, data = self.matrix()
        row = next(x for x in data['results'] if x['command'].endswith(' version'))
        self.assertEqual(row['exit_code'], 42)
        self.assertEqual(row['classification'], 'error')
        self.failed(self.ci())

    def test_negative_error_text_cannot_hide_exit0(self):
        self.mutate('lib/interface.bashcmdr', 'bashcmdr_plug_cartridge() {',
                    'bashcmdr_plug_cartridge() {\n    if [[ ${1-} == nonexistent ]]; then printf "not found\\n" >&2; return 0; fi')
        p = self.ci_unit()
        self.failed(p)
        self.assertIn('cartridge plug nonexistent warns', p.stdout)

    def test_negative_error_text_cannot_hide_wrong_nonzero_exit(self):
        self.mutate('lib/interface.bashcmdr', 'bashcmdr_plug_cartridge() {',
                    'bashcmdr_plug_cartridge() {\n    if [[ ${1-} == nonexistent ]]; then printf "not found\\n" >&2; return 42; fi')
        self.failed(self.ci_unit())

    def test_positive_matching_output_cannot_hide_failure(self):
        self.mutate('bin/bashcmdr', 'main() {',
                    'main() {\n    if [[ ${1-}:${2-} == cartridge:plug && ${3-} == --help ]]; then printf "Usage: plug\\n"; return 1; fi')
        self.failed(self.ci_unit())

    def test_quiet_stdout_noise_fails_unit_suite(self):
        self.mutate('lib/sourcing.bashcmdr', 'bc_source() {',
                    'bc_source() {\n    if [[ ${1-} == --quiet ]]; then printf "QUIET_NOISE\\n"; fi')
        p = self.ci_unit()
        self.failed(p)
        self.assertIn('bc.source --quiet suppresses messages', p.stdout)

    def test_quiet_newline_only_noise_is_not_trimmed_into_success(self):
        self.mutate('lib/sourcing.bashcmdr', 'bc_source() {',
                    'bc_source() {\n    if [[ ${1-} == --quiet ]]; then printf "\\n"; fi')
        self.failed(self.ci_unit())
        logs = list(self.results.glob('unit.*/quiet-*.output.log'))
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].read_bytes(), b'\n')

    def test_quiet_stderr_noise_fails_unit_suite(self):
        self.mutate('lib/sourcing.bashcmdr', 'bc_source() {',
                    'bc_source() {\n    if [[ ${1-} == --quiet ]]; then printf "QUIET_NOISE\\n" >&2; fi')
        self.failed(self.ci_unit())

    def test_quiet_zero_output_with_failure_is_rejected(self):
        self.mutate('lib/sourcing.bashcmdr', 'bc_source() {',
                    'bc_source() {\n    if [[ ${1-} == --quiet ]]; then return 1; fi')
        self.failed(self.ci_unit())

    def test_empty_contains_expectation_is_not_a_silent_assertion(self):
        script = self.repo / 'tests/test_runner.bash'
        text = script.read_text()
        # Introduce a vacuous check via the generic helper; it must fail even
        # when command status is otherwise correct.
        script.write_text(text.replace('    test_basic_commands\n',
            '    assert_output_contains "empty expected substring" "true" ""\n    test_basic_commands\n', 1))
        self.failed(self.suite('unit'))

    def test_ci_rejects_missing_results(self):
        self.failed(self.ci())

    def test_ci_rejects_empty_malformed_or_multiple_documents(self):
        path, data = self.normal_matrix()
        for text in ['', '{broken', 'null', '[]', json.dumps({'metadata': data['metadata'], 'results': []}),
                     json.dumps(data) + '\n' + json.dumps(data)]:
            with self.subTest(text=text[:40]):
                path.write_text(text)
                self.failed(self.ci())

    def test_ci_ignores_forged_pass_flags_and_expectations(self):
        path, data = self.normal_matrix()
        for forged_expected in [0, 1]:
            with self.subTest(expected=forged_expected):
                changed = copy.deepcopy(data)
                row = next(x for x in changed['results'] if x['command'].endswith(' version'))
                row.update(exit_code=1, expected_exit=forged_expected, passed=True,
                           classification='success' if forged_expected == 0 else 'expected_failure')
                path.write_text(json.dumps(changed))
                self.failed(self.ci())

    def test_ci_rejects_missing_duplicate_extra_or_changed_cases(self):
        path, data = self.normal_matrix()
        self.assertIn('argv', data['results'][0])
        for mode in ['missing', 'duplicate', 'extra', 'argv', 'executable', 'schema']:
            with self.subTest(mode=mode):
                changed = copy.deepcopy(data)
                if mode == 'missing':
                    changed['results'].pop()
                elif mode == 'duplicate':
                    changed['results'][-1] = changed['results'][0]
                elif mode == 'extra':
                    changed['results'].append(changed['results'][0])
                elif mode == 'argv':
                    changed['results'][0]['argv'][-1] = 'different'
                elif mode == 'executable':
                    changed['results'][0]['argv'][0] = 'different-program'
                else:
                    changed['metadata']['schema'] = 'unknown'
                path.write_text(json.dumps(changed))
                self.failed(self.ci())

    def test_ci_rejects_missing_diagnostic_log(self):
        path, data = self.normal_matrix()
        (path.parent / data['results'][0]['output_log']).unlink()
        self.failed(self.ci())

    def test_ci_rejects_linked_record_or_diagnostic(self):
        path, data = self.normal_matrix()
        original = path.read_text()
        target = path.parent / 'saved.json'
        target.write_text(original)
        path.unlink()
        path.symlink_to(target.name)
        self.failed(self.ci())
        path.unlink()
        path.write_text(original)
        log = path.parent / data['results'][0]['output_log']
        saved = path.parent / 'saved-output.log'
        log.rename(saved)
        log.symlink_to(saved.name)
        self.failed(self.ci())

    def test_invalid_case_manifest_fails_before_case_execution(self):
        manifest = self.repo / 'tests/rapid-cases.json'
        self.assertTrue(manifest.is_file())
        data = json.loads(manifest.read_text())
        data['cases'][0]['argv'].append('\0')
        manifest.write_text(json.dumps(data))
        p = self.suite()
        self.failed(p)
        self.assertIn('Invalid rapid case manifest', p.stderr)
        self.assertFalse(list(self.results.glob('factorial.*/case-*.output.log')))

    def test_case_argument_data_is_never_shell_source(self):
        manifest = self.repo / 'tests/rapid-cases.json'
        self.assertTrue(manifest.is_file())
        data = json.loads(manifest.read_text())
        trace = self.root / 'must-not-exist'
        payload = '$(printf EXECUTED > ' + shlex.quote(str(trace)) + ')'
        case = next(x for x in data['cases'] if x['argv'] == ['version'])
        case['argv'].append(payload)
        manifest.write_text(json.dumps(data))
        self.ok(self.suite())
        _, actual = self.matrix()
        row = next(x for x in actual['results'] if x['test_id'] == case['id'])
        self.assertEqual(row['argv'][-1], payload)
        self.assertFalse(trace.exists())
        self.ok(self.ci())


if __name__ == '__main__':
    unittest.main(verbosity=2)
