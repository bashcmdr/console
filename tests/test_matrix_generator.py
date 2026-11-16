#!/usr/bin/env python3
"""Exercise catalog generation as data, including failures and owned discovery."""
import json
import os
import pathlib
import shlex
import shutil
import subprocess
import tempfile
import textwrap
import unittest

REPO = pathlib.Path(os.environ.get('MATRIX_TEST_REPO', pathlib.Path(__file__).resolve().parent.parent))


class MatrixGeneratorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bcm-catalog-')
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.repo = self.root / "source 'copy'"
        self.tests = self.repo / 'tests'
        self.tests.mkdir(parents=True)
        for filename in ['command_matrix_generator.bash', 'matrix-catalog.jq']:
            source = REPO / 'tests' / filename
            if source.exists():
                shutil.copyfile(source, self.tests / filename)
        self.tmp = self.root / 'temporary parent'
        self.home = self.root / 'home'
        self.tmp.mkdir()
        self.home.mkdir()
        self.bash = shutil.which('bash')
        self.env = {'HOME': str(self.home), 'PATH': os.environ.get('PATH', os.defpath),
                    'TMPDIR': str(self.tmp), 'LC_ALL': 'C', 'TERM': 'dumb'}
        self.calls = []

    def tearDown(self):
        evidence = os.environ.get('MATRIX_TEST_EVIDENCE_DIR')
        if evidence:
            destination = pathlib.Path(evidence) / self.id().split('.')[-1]
            destination.mkdir(parents=True, exist_ok=True)
            (destination / 'calls.json').write_text(json.dumps(self.calls, indent=2) + '\n')

    def run_command(self, argv, extra=None):
        p = subprocess.run(argv, cwd=self.repo, env={**self.env, **(extra or {})},
                           text=True, capture_output=True, timeout=15)
        self.calls.append({'argv': argv, 'exit': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr})
        return p

    def generate(self, *args, extra=None):
        return self.run_command([self.bash, '--noprofile', '--norc', '-e', '-o', 'pipefail',
                                 'tests/command_matrix_generator.bash', *args], extra)

    def catalog(self, *args, extra=None):
        p = self.generate('--output', '-', *args, extra=extra)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return json.loads(p.stdout)

    def stub(self, name, body):
        directory = self.root / 'tool stubs'
        directory.mkdir(exist_ok=True)
        p = directory / name
        p.write_text('#!' + self.bash + '\n' + body + '\n')
        p.chmod(0o755)
        return {'PATH': str(directory) + os.pathsep + self.env['PATH']}

    def test_complete_errexit_catalog_has_stable_case_counts_and_unique_argv(self):
        data = self.catalog()
        rows = data['test_matrix']
        self.assertEqual(data['metadata']['schema'], 'bashcmdr.command-catalog.v2')
        self.assertEqual(data['metadata']['execution'], 'not_executed')
        self.assertEqual(data['metadata']['total_combinations'], 296)
        self.assertEqual(len(rows), 296)
        self.assertEqual([x['id'] for x in rows], list(range(1, 297)))
        self.assertEqual(len({tuple(x['argv']) for x in rows}), len(rows))
        self.assertEqual(data['metadata']['fixed_expectations'], 153)
        self.assertEqual(data['metadata']['fixture_required'], 143)
        for row in rows:
            self.assertEqual(shlex.split(row['command']), ['bcm', *row['argv']])

    def test_current_taxonomy_and_phase1_outcomes(self):
        rows = {tuple(x['argv']): x for x in self.catalog()['test_matrix']}
        self.assertEqual(rows[()]['expected_exit_code'], 0)
        for argv in [('console', 'upgrade'), ('console', 'uninstall'),
                     ('cartridge', 'upgrade', 'demo'), ('registry', 'sync')]:
            self.assertEqual(rows[argv]['classification'], 'valid')
            self.assertEqual(rows[argv]['expected_exit_code'], 1)
            self.assertIn('phase1_not_implemented', rows[argv]['requirements'])
        self.assertEqual(rows[('quarantine', 'demo')]['classification'], 'invalid')
        for verb in ['install', 'uninstall', 'plug', 'unplug', 'quarantine', 'release',
                     'show', 'deps', 'plan', 'graph', 'why', 'diagnose']:
            self.assertIn(('cartridge', verb, 'nonexistent-cartridge'), rows)
        for command in ['doctor', 'version', 'help']:
            for flag in ['-h', '--help']:
                self.assertIn((command, flag), rows)
        self.assertIn(('alias', 'remove', 'nonexistent'), rows)
        self.assertIn(('cartridge', 'quarantine', 'demo'), rows)
        self.assertIn(('console', 'shortcut', '--install'), rows)
        self.assertIn(('cartridge', 'list', 'quarantine'), rows)
        for row in rows.values():
            if row['classification'] == 'valid' and row['argv']:
                self.assertIn(row['argv'][0], ['console', 'cartridge', 'registry', 'alias',
                                             'doctor', 'help', 'version', '-h', '--help'])

    def test_context_dependent_cases_require_explicit_fixture_binding(self):
        rows = {tuple(x['argv']): x for x in self.catalog()['test_matrix']}
        for argv in [('cartridge', 'why', 'nonexistent-cartridge'),
                     ('cartridge', 'install', 'demo'), ('console', 'poweron'),
                     ('cartridge', 'search'), ('alias', 'remove', 'sample-shortcut')]:
            self.assertIsNone(rows[argv]['expected_exit_code'])
            self.assertEqual(rows[argv]['expectation_kind'], 'fixture_required')
            self.assertTrue(rows[argv]['requirements'])
        for row in rows.values():
            if row['expected_exit_code'] is None:
                self.assertEqual(row['classification'], 'valid')
                self.assertTrue(row['requirements'])
            elif row['classification'] == 'invalid':
                self.assertEqual(row['expected_exit_code'], 1)

    def test_search_crossproduct_and_quoted_data_roundtrip(self):
        rows = self.catalog()['test_matrix']
        search = [x for x in rows if x['argv'][:2] == ['cartridge', 'search']
                  and x['expectation_kind'] == 'fixture_required']
        self.assertEqual(len(search), 80)
        self.assertTrue(any('quoted"term' in x['argv'] for x in search))
        self.assertTrue(any('Author "quoted"' in x['argv'] for x in search))
        self.assertTrue(any('--installed' in x['argv'] and '--active' in x['argv'] for x in search))
        self.assertTrue(any(x['argv'] and x['argv'][-1] == 'manual reason' for x in rows))

    def test_default_output_is_ignored_and_does_not_rewrite_historical_path(self):
        historical = self.tests / 'full_factorial_matrix.json'
        historical.write_text('retained sentinel\n')
        p = self.generate()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        output = self.tests / 'results/full_factorial_matrix.json'
        self.assertEqual(json.loads(output.read_text())['metadata']['total_combinations'], 296)
        self.assertEqual(historical.read_text(), 'retained sentinel\n')
        self.assertEqual(p.stdout, '')
        git = subprocess.run(['git', 'check-ignore', '--no-index', 'tests/results/full_factorial_matrix.json'],
                             cwd=REPO, text=True, capture_output=True)
        self.assertEqual(git.returncode, 0, git.stdout + git.stderr)

    def test_stdout_mode_writes_no_checkout_file_and_cleans_temporary_files(self):
        before = {p.relative_to(self.repo): p.read_bytes() for p in self.repo.rglob('*') if p.is_file()}
        self.catalog()
        after = {p.relative_to(self.repo): p.read_bytes() for p in self.repo.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_default_ignores_ambient_roots_and_runtime_payload(self):
        installed = self.repo / 'cartridges/injected'
        installed.mkdir(parents=True)
        (installed / 'main.bashcmdr').write_text('touch "' + str(self.root / 'executed') + '"\n')
        a = self.catalog(extra={'BASHCMDR_ROOT': str(self.repo), 'BASHCMDR_ROOT_DIR': str(self.repo),
                                'BASHCMDR_INSTALLED_DIR': str(installed.parent)})
        self.assertEqual(a['metadata']['fixture_names'], ['demo', 'dependency'])
        self.assertFalse((self.root / 'executed').exists())

    def test_explicit_discovery_uses_current_ordinary_cartridge_directories(self):
        root = self.root / 'installation'
        (root / 'cartridges/zeta').mkdir(parents=True)
        (root / 'cartridges/alpha').mkdir()
        (root / 'installed/retired').mkdir(parents=True)
        (root / 'cartridges/file-entry').write_text('data')
        (root / 'cartridges/linked').symlink_to(root / 'cartridges/alpha', target_is_directory=True)
        (root / 'cartridges/dangling').symlink_to(root / 'missing', target_is_directory=True)
        data = self.catalog('--root', str(root))
        self.assertEqual(data['metadata']['fixture_names'], ['alpha', 'demo', 'dependency', 'zeta'])
        self.assertNotIn(str(root), json.dumps(data))

    def test_explicit_template_names_are_sorted_unique_and_replace_defaults(self):
        a = self.catalog('--cartridge', 'zeta-2', '--cartridge', 'Alpha_1.log', '--cartridge', 'zeta-2')
        b = self.catalog('--cartridge', 'Alpha_1.log', '--cartridge', 'zeta-2')
        self.assertEqual(a, b)
        self.assertEqual(a['metadata']['fixture_names'], ['Alpha_1.log', 'zeta-2'])

    def test_invalid_options_and_names_fail_without_changing_destination(self):
        output = self.root / 'destination'
        output.write_text('retain this\n')
        for args in [('--unknown',), ('--output',), ('--output', ''), ('--cartridge',),
                     ('--cartridge', ''), ('--cartridge', '../escape'), ('--cartridge', '.hidden'),
                     ('--cartridge', 'quote"name'), ('--cartridge', 'two words'),
                     ('--root',), ('--root', str(self.root / 'missing')),
                     ('--root', str(self.repo), '--root', str(self.repo))]:
            with self.subTest(args=args):
                p = self.generate('--output', str(output), *args)
                self.assertNotEqual(p.returncode, 0, p.stdout + p.stderr)
                self.assertEqual(output.read_text(), 'retain this\n')
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_discovery_rejects_linked_storage_and_invalid_directory_names(self):
        root = self.root / 'installation'
        root.mkdir()
        (root / 'cartridges').symlink_to(self.repo, target_is_directory=True)
        self.assertNotEqual(self.generate('--root', str(root), '--output', '-').returncode, 0)
        (root / 'cartridges').unlink()
        (root / 'cartridges/bad name').mkdir(parents=True)
        self.assertNotEqual(self.generate('--root', str(root), '--output', '-').returncode, 0)

    def test_output_rejects_symlinks_dangling_symlinks_and_directories(self):
        target = self.root / 'target'
        target.write_text('retained')
        link = self.root / 'linked-output'
        link.symlink_to(target)
        dangling = self.root / 'dangling-output'
        dangling.symlink_to(self.root / 'missing')
        for path in [link, dangling, self.home]:
            with self.subTest(path=path):
                self.assertNotEqual(self.generate('--output', str(path)).returncode, 0)
        self.assertTrue(link.is_symlink())
        self.assertTrue(dangling.is_symlink())
        self.assertEqual(target.read_text(), 'retained')

    def test_completed_output_replaces_existing_file_in_path_with_spaces(self):
        output = self.root / "output dir 'quoted'/catalog.json"
        output.parent.mkdir()
        output.write_text('old')
        p = self.generate('--output', str(output))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(json.loads(output.read_text()), self.catalog())
        self.assertEqual(list(output.parent.iterdir()), [output])

    def test_failed_or_empty_jq_output_preserves_existing_destination(self):
        output = self.root / 'destination'
        output.write_text('retained')
        real_jq = shutil.which('jq')
        for body in ['exit 42', 'exit 0',
                     'if [[ ${1-} == -n ]]; then printf "{partial"; exit 1; fi\nexec ' + shlex.quote(real_jq) + ' "$@"']:
            with self.subTest(body=body):
                p = self.generate('--output', str(output), extra=self.stub('jq', body))
                self.assertNotEqual(p.returncode, 0, p.stdout + p.stderr)
                self.assertEqual(output.read_text(), 'retained')
                self.assertEqual(list(self.tmp.iterdir()), [])

    def test_failed_move_cleans_staging_and_retains_previous_output(self):
        output = self.root / 'destination'
        output.write_text('retained')
        p = self.generate('--output', str(output), extra=self.stub('mv', 'exit 42'))
        self.assertNotEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(output.read_text(), 'retained')
        self.assertEqual(list(self.root.glob('.bashcmdr-matrix.*')), [])
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_readonly_output_parent_reports_failure(self):
        # These tests run as the ordinary developer account; root cannot prove DAC denial.
        if not hasattr(os, 'geteuid') or os.geteuid() == 0:
            self.skipTest('Permission denial requires an ordinary POSIX user')
        output = self.root / 'readonly/catalog.json'
        output.parent.mkdir()
        output.write_text('retained')
        output.parent.chmod(0o555)
        try:
            p = self.generate('--output', str(output))
        finally:
            output.parent.chmod(0o755)
        self.assertNotEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(output.read_text(), 'retained')
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_source_only_is_pure_and_explicit_function_call_handles_conditional_failure(self):
        script = textwrap.dedent('''\
            set -euo pipefail
            before=$(set +o)
            source tests/command_matrix_generator.bash
            [[ $(set +o) == "$before" ]]
            [[ ! -d tests/results ]]
            if generate_matrix_catalog --output destination; then exit 99; fi
            [[ $(cat destination) == retained ]]
        ''')
        (self.repo / 'destination').write_text('retained')
        extra = self.stub('mv', 'exit 42')
        p = self.run_command([self.bash, '--noprofile', '--norc', '-c', script], extra)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_generation_never_executes_command_data_or_providers(self):
        sentinel = self.root / 'executed'
        extra = None
        for name in ['bcm', 'bashcmdr', 'git', 'curl', 'sudo']:
            extra = self.stub(name, 'printf called >> ' + shlex.quote(str(sentinel)) + '\nexit 42')
        provider = self.repo / 'cartridges/payload'
        provider.mkdir(parents=True)
        (provider / 'main.bashcmdr').write_text('printf called >> ' + shlex.quote(str(sentinel)))
        self.catalog('--root', str(self.repo), extra=extra)
        self.assertFalse(sentinel.exists())

    def test_deterministic_across_working_directories_and_no_machine_paths(self):
        a = self.catalog()
        other = self.root / 'relocated source'
        shutil.copytree(self.tests, other / 'tests')
        p = self.run_command([self.bash, '--noprofile', '--norc',
                              str(other / 'tests/command_matrix_generator.bash'), '--output', '-'])
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(a, json.loads(p.stdout))
        for value in [str(self.repo), str(other), str(self.home), str(REPO), '/home/', '/Users/']:
            self.assertNotIn(value, json.dumps(a))

    def test_help_is_successful_without_output_artifact(self):
        p = self.generate('--help')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn('Usage:', p.stdout)
        self.assertFalse((self.tests / 'results').exists())
        self.assertEqual(list(self.tmp.iterdir()), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
