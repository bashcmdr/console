#!/usr/bin/env python3
"""Dependency inspection against owned manifests, without hooks or network."""
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

REPO = pathlib.Path(os.environ.get('INSPECTION_TEST_REPO', pathlib.Path(__file__).resolve().parent.parent))


class DependencyInspectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bcm-inspection-')
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.home = self.root / 'home with spaces'
        self.console = self.home / 'console'
        self.console.mkdir(parents=True)
        for part in ['bin', 'lib', 'boot']:
            shutil.copytree(REPO / part, self.console / part)
        shutil.copyfile(REPO / 'VERSION', self.console / 'VERSION')
        self.trace = self.root / 'external.log'
        self.trace.write_text('')
        self.env = {'HOME': str(self.home), 'CONSOLE': str(self.console),
                    'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'TERM': 'dumb',
                    'TMPDIR': str(self.root), 'TRACE': str(self.trace)}

    def tearDown(self):
        self.assertEqual(self.trace.read_text(), '', 'inspection reached a provider or external operation')

    def cartridge(self, name, deps=None):
        path = self.console / 'cartridges' / name
        path.mkdir(parents=True)
        data = {'name': name, 'version': '1.0.0', 'requires': {'cartridges':
                deps if isinstance(deps, dict) else dict.fromkeys(deps or [], '>=1.0.0')}}
        (path / 'manifest.json').write_text(json.dumps(data))
        (path / 'main.bashcmdr').write_text('printf "unexpected-hook\\n" >> "$TRACE"\n')
        return path

    def shell(self, body):
        inert = '\n'.join(name + '() { printf "unexpected-' + name + '\\n" >> "$TRACE"; return 99; }'
                          for name in ['git', 'curl', 'wget', 'sudo'])
        return subprocess.run(['/bin/bash', '--noprofile', '--norc', '-c', inert +
                               '\nsource "$CONSOLE/bin/bashcmdr" || exit $?\n' + body],
                              env=self.env, cwd=self.root, capture_output=True, text=True, timeout=8)

    def ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def chain(self):
        self.cartridge('root', ['middle'])
        self.cartridge('middle', ['leaf'])
        self.cartridge('leaf')

    def test_fresh_graph_contains_three_levels_with_indentation(self):
        self.chain()
        result = self.shell('main cartridge graph root')
        self.ok(result)
        self.assertIn('\nroot\n└── middle\n    └── leaf\n', result.stdout)

    def test_fresh_and_warmed_graphs_are_identical(self):
        self.chain()
        cold = self.shell('cartridge_graph_cmd root')
        warm = self.shell('__bashcmdr_load_dependencies middle || exit $?\ncartridge_graph_cmd root')
        self.ok(cold)
        self.ok(warm)
        self.assertEqual(cold.stdout, warm.stdout)

    def test_diamond_marks_shared_node_without_cycle_failure(self):
        self.cartridge('root', ['left', 'right'])
        self.cartridge('left', ['shared'])
        self.cartridge('right', ['shared'])
        self.cartridge('shared', ['leaf'])
        self.cartridge('leaf')
        result = self.shell('main cartridge graph root')
        self.ok(result)
        self.assertIn('├── left\n│   └── shared\n│       └── leaf', result.stdout)
        self.assertIn('└── right\n    └── shared (shared)', result.stdout)
        self.assertNotIn('(cycle)', result.stdout)

    def test_cycle_is_marked_and_other_branches_are_still_rendered(self):
        self.cartridge('root', ['aaa', 'zzz'])
        self.cartridge('aaa', ['root'])
        self.cartridge('zzz')
        result = self.shell('main cartridge graph root')
        self.assertEqual(result.returncode, 1)
        self.assertIn('root (cycle)', result.stdout)
        self.assertIn('└── zzz', result.stdout)
        self.assertIn('Dependency cycle', result.stderr)

    def test_self_cycle_returns_failure(self):
        self.cartridge('root', ['root'])
        result = self.shell('main cartridge graph root')
        self.assertEqual(result.returncode, 1)
        self.assertIn('root (cycle)', result.stdout)

    def test_missing_transitive_manifest_is_visible_and_nonzero(self):
        self.cartridge('root', ['middle'])
        self.cartridge('middle', ['absent'])
        result = self.shell('main cartridge graph root')
        self.assertEqual(result.returncode, 1)
        self.assertIn('    └── absent [unavailable manifest]', result.stdout)

    def test_unknown_graph_root_does_not_claim_no_dependencies(self):
        result = self.shell('main cartridge graph unknown')
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('No dependencies', result.stdout)

    def test_empty_valid_graph_prints_root_and_no_dependencies(self):
        self.cartridge('root')
        result = self.shell('main cartridge graph root')
        self.ok(result)
        self.assertIn('\nroot\n', result.stdout)
        self.assertIn('No dependencies', result.stdout)

    def test_deps_unknown_root_fails_without_false_empty_success(self):
        result = self.shell('main cartridge deps unknown')
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('No dependencies', result.stdout)

    def test_deps_empty_manifest_succeeds(self):
        self.cartridge('root')
        result = self.shell('main cartridge deps root')
        self.ok(result)
        self.assertIn('No dependencies', result.stdout)

    def test_deps_preserves_constraints_as_text_including_empty(self):
        self.cartridge('root', {'one': '>= 1.0.0', 'two': '', 'three': 'quoted"value\\path\nline'})
        for name in ['one', 'two', 'three']:
            self.cartridge(name)
        result = self.shell('main cartridge deps root')
        self.ok(result)
        self.assertIn('one >= 1.0.0', result.stdout)
        self.assertIn('two ', result.stdout)
        self.assertIn(r'three quoted"value\\path\nline', result.stdout)

    def test_deps_missing_declared_package_is_nonzero(self):
        self.cartridge('root', ['absent'])
        result = self.shell('main cartridge deps root')
        self.assertEqual(result.returncode, 1)
        self.assertIn('absent', result.stdout)
        self.assertNotIn('No dependencies', result.stdout)

    def test_malformed_schema_and_multiple_documents_fail(self):
        path = self.cartridge('root')
        for text in ['{broken', '', '{}\n{}', '[]', '{"requires":false}',
                     '{"requires":{"cartridges":[]}}', '{"requires":{"cartridges":{"x":false}}}',
                     '{"requires":{"cartridges":{"../x":"1"}}}']:
            with self.subTest(text=text):
                (path / 'manifest.json').write_text(text)
                for command in ['deps', 'graph', 'why']:
                    result = self.shell('main cartridge ' + command + ' root')
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertNotIn('No dependencies', result.stdout)
                    self.assertNotIn('No installed cartridges depend', result.stdout)

    def test_why_empty_tree_reports_absence_without_literal_glob(self):
        result = self.shell('main cartridge why unknown')
        self.ok(result)
        self.assertEqual(result.stderr, '')
        self.assertIn('Target is not installed: unknown', result.stdout)
        self.assertIn("No installed cartridges depend on 'unknown'", result.stdout)
        self.assertNotIn('can be removed independently', result.stdout)

    def test_why_reports_direct_and_transitive_dependents_once(self):
        self.chain()
        result = self.shell('main cartridge why leaf')
        self.ok(result)
        self.assertIn('middle requires it (>=1.0.0)', result.stdout)
        self.assertIn('root requires it transitively (via root -> middle -> leaf)', result.stdout)
        self.assertIn('required by 2 cartridge(s)', result.stdout)
        self.assertNotIn('Activated at position', result.stdout)

    def test_why_handles_shared_graph_and_literal_dot_names(self):
        self.cartridge('root', ['left', 'right'])
        self.cartridge('left', ['dep.one'])
        self.cartridge('right', ['dep.one'])
        self.cartridge('dep.one')
        self.cartridge('unrelated', ['depXone'])
        self.cartridge('depXone')
        result = self.shell('main cartridge why dep.one')
        self.ok(result)
        self.assertEqual(result.stdout.count('root requires it'), 1)
        self.assertNotIn('unrelated requires it', result.stdout)
        self.assertIn('required by 3 cartridge(s)', result.stdout)

    def test_why_cycle_traversal_terminates_and_reports_declared_paths(self):
        self.cartridge('root', ['middle'])
        self.cartridge('middle', ['root', 'target'])
        self.cartridge('target')
        result = self.shell('main cartridge why target')
        self.ok(result)
        self.assertIn('root requires it transitively', result.stdout)
        self.assertIn('middle requires it (>=1.0.0)', result.stdout)

    def test_why_missing_queried_target_can_explain_dangling_declarations(self):
        self.cartridge('root', ['missing'])
        result = self.shell('main cartridge why missing')
        self.ok(result)
        self.assertIn('Target is not installed: missing', result.stdout)
        self.assertIn('root requires it (>=1.0.0)', result.stdout)

    def test_why_missing_other_node_refuses_incomplete_negative_result(self):
        self.cartridge('root', ['absent'])
        result = self.shell('main cartridge why target')
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('No installed cartridges depend', result.stdout)

    def test_why_damaged_other_manifest_fails_before_any_results(self):
        self.cartridge('target')
        path = self.cartridge('other')
        (path / 'manifest.json').unlink()
        result = self.shell('main cartridge why target')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, '')

    def test_linked_package_is_not_silently_adopted(self):
        self.cartridge('target')
        (self.console / 'cartridges/linked').symlink_to('target')
        for command in ['graph linked', 'deps linked', 'why target']:
            result = self.shell('main cartridge ' + command)
            self.assertEqual(result.returncode, 1)
            self.assertNotIn('No installed cartridges depend', result.stdout)

    def test_invalid_names_fail_without_external_effects(self):
        for name in ['', '../outside', 'bad name', 'bad:entry', 'bad\nname']:
            for command in ['deps', 'graph', 'why']:
                with self.subTest(command=command, name=name):
                    self.env['QUERY_NAME'] = name
                    result = self.shell('cartridge_' + command + '_cmd "$QUERY_NAME"')
                    self.assertEqual(result.returncode, 1)
                    self.assertIn('Invalid cartridge name', result.stderr)

    def test_queries_preserve_resolver_caches_functions_and_ifs(self):
        self.chain()
        result = self.shell(r'''
declare -A BASHCMDR_DEPENDENCY_GRAPH=([sentinel]='preserve')
declare -A BASHCMDR_DEPENDENCY_CONSTRAINTS=([sentinel]='preserve')
declare -a BASHCMDR_ACTIVATION_ORDER=(preserve)
_print_dep_tree() { printf 'preserve\n'; }
before=$(declare -p BASHCMDR_DEPENDENCY_GRAPH BASHCMDR_DEPENDENCY_CONSTRAINTS BASHCMDR_ACTIVATION_ORDER)
IFS=':'
for operation in deps graph why; do
    "cartridge_${operation}_cmd" root >/dev/null || exit $?
done
[[ $IFS == ':' && $(_print_dep_tree) == preserve ]] || exit 88
[[ $(declare -p BASHCMDR_DEPENDENCY_GRAPH BASHCMDR_DEPENDENCY_CONSTRAINTS BASHCMDR_ACTIVATION_ORDER) == "$before" ]]
''')
        self.ok(result)

    def test_strict_shell_queries_and_failure_status(self):
        self.chain()
        result = self.shell('set -euo pipefail\ncartridge_graph_cmd root\n'
                            'cartridge_deps_cmd root\ncartridge_why_cmd leaf\n'
                            'if cartridge_deps_cmd absent; then exit 88; fi')
        self.ok(result)

    def test_direct_queries_do_not_write_runtime_or_registry_paths(self):
        self.chain()
        before = sorted(str(p.relative_to(self.home)) for p in self.home.rglob('*'))
        for command in ['cartridge_graph_cmd root', 'cartridge_deps_cmd root', 'cartridge_why_cmd leaf']:
            self.ok(self.shell(command))
            self.assertEqual(sorted(str(p.relative_to(self.home)) for p in self.home.rglob('*')), before)

    def test_why_is_complete_with_caller_globbing_disabled_or_filtered(self):
        self.chain()
        for setup in ['set -f', 'GLOBIGNORE="*"', 'shopt -s failglob']:
            with self.subTest(setup=setup):
                result = self.shell(setup + '\ncartridge_why_cmd leaf')
                self.ok(result)
                self.assertIn('required by 2 cartridge(s)', result.stdout)

    def test_why_empty_tree_with_failglob_is_still_a_valid_query(self):
        result = self.shell('shopt -s failglob\ncartridge_why_cmd unknown')
        self.ok(result)
        self.assertIn('No installed cartridges depend', result.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
