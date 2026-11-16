#!/usr/bin/env python3
"""Numeric version contracts in owned installations and actual selected Bash."""
import json
import os
import pathlib
import shutil
import tempfile
import unittest

import test_runtime_preflight as runtime

REPO = pathlib.Path(os.environ.get('VERSION_TEST_REPO', pathlib.Path(__file__).resolve().parent.parent))
BASH = os.environ.get('VERSION_TEST_BASH') or shutil.which('bash')
runtime.REPO = REPO
runtime.BASH = BASH
INVALID = ['', '00', '01', '1.00', '1.08.0', '1.0.00', '1.0.0.0',
           '1000000000', '999999999999999999999999999', '-1', '+1', '1.', '.1',
           '1..0', '1.0.0-rc1', '1.0.0+build', 'v1.0.0', '*', 'latest',
           ' 1', '1 ', '1\n', '1\t', '1.0.rc1', '1.0.x[0]']


class VersionComparisonTests(runtime.RuntimeFixture):
    def tearDown(self):
        destination = pathlib.Path(os.environ['VERSION_TEST_EVIDENCE_DIR']) / self.id().split('.')[-1]
        destination.mkdir(parents=True, exist_ok=True)
        (destination / 'calls.json').write_text(json.dumps(self.calls, indent=2) + '\n')
        shutil.copyfile(self.trace, destination / 'operations.log')

    def compare(self, left, operator, right):
        self.env.update(LEFT=left, OPERATOR=operator, RIGHT=right)
        p = self.shell('''source bin/bashcmdr
set -euo pipefail
if __bashcmdr_version_compare "$LEFT" "$OPERATOR" "$RIGHT"; then status=0; else status=$?; fi
printf '%s\n' "$status"
''')
        self.ok(p)
        self.assertEqual(p.stderr, '', p.stderr)
        return int(p.stdout)

    def parse(self, constraint):
        self.env['CONSTRAINT'] = constraint
        p = self.shell('''source bin/bashcmdr
set -euo pipefail
declare -A parsed=([operator]=stale [version]=stale [unrelated]=kept)
if __bashcmdr_parse_version_constraint "$CONSTRAINT" parsed; then status=0; else status=$?; fi
printf '%s\n%s\n%s\n%s\n' "$status" "${parsed[operator]}" "${parsed[version]}" "${parsed[unrelated]}"
''')
        self.ok(p)
        self.assertEqual(p.stderr, '')
        return p.stdout.splitlines()

    def set_dependency(self, version='1.0.0', constraint='>=1.0.0'):
        path = self.repo / 'cartridges/dep/manifest.json'
        manifest = json.loads(path.read_text()); manifest['version'] = version
        path.write_text(json.dumps(manifest))
        path = self.repo / 'cartridges/demo/manifest.json'
        manifest = json.loads(path.read_text()); manifest['requires']['cartridges'] = {'dep': constraint}
        path.write_text(json.dumps(manifest))

    def plan(self):
        return self.shell('source bin/bashcmdr\nset -euo pipefail\nbashcmdr_get_activation_plan demo')

    def assert_no_arithmetic_diagnostics(self, result):
        for message in ['value too great for base', 'syntax error', 'unbound variable', 'operand expected', 'invalid arithmetic']:
            self.assertNotIn(message, result.stdout + result.stderr)

    def test_order_relations_and_equality(self):
        for left, op, right, expected in [
            ('1.2.3', '=', '1.2.3', 0), ('1.2.3', '==', '1.2.3', 0),
            ('1.2.3', '!=', '1.2.4', 0), ('1.2.3', '!=', '1.2.3', 1),
            ('2', '>', '1.999.999', 0), ('1.2.3', '>', '1.2.3', 1),
            ('1.2.3', '>=', '1.2.3', 0), ('1.2.2', '>=', '1.2.3', 1),
            ('1.2.3', '<', '1.2.4', 0), ('1.2.3', '<', '1.2.3', 1),
            ('1.2.3', '<=', '1.2.3', 0), ('1.2.4', '<=', '1.2.3', 1)]:
            with self.subTest(left=left, op=op, right=right):
                self.assertEqual(self.compare(left, op, right), expected)

    def test_missing_minor_patch_components_are_zero(self):
        for left in ['1', '1.0', '1.0.0']:
            for right in ['1', '1.0', '1.0.0']:
                with self.subTest(left=left, right=right):
                    self.assertEqual(self.compare(left, '=', right), 0)
        self.assertEqual(self.compare('1.2', '=', '1.2.0'), 0)

    def test_zero_and_largest_supported_components(self):
        for left, op, right in [('0', '=', '0.0.0'), ('999999999.999999999.999999999', '>', '999999999.999999999.999999998'),
                                ('999999999', '=', '999999999.0.0'), ('0.0.1', '>', '0')]:
            with self.subTest(left=left, right=right):
                self.assertEqual(self.compare(left, op, right), 0)

    def test_tilde_and_caret_preserve_existing_numeric_rules(self):
        for left, op, right, expected in [('1.2.9', '~', '1.2', 0), ('1.3', '~', '1.2', 1),
            ('1.2.2', '~', '1.2.3', 1), ('1.9', '^', '1.2', 0), ('2', '^', '1.2', 1),
            ('0.9', '^', '0.2', 0), ('0.1', '^', '0.2', 1)]:
            with self.subTest(left=left, op=op, right=right):
                self.assertEqual(self.compare(left, op, right), expected)

    def test_invalid_actual_versions_never_compare_successfully(self):
        for value in INVALID:
            with self.subTest(value=value):
                self.assertEqual(self.compare(value, '>=', '0'), 1)

    def test_invalid_required_versions_never_compare_successfully(self):
        for value in INVALID:
            with self.subTest(value=value):
                self.assertEqual(self.compare('999999999', '>=', value), 1)

    def test_unknown_operators_are_rejected(self):
        for op in ['', '=>', '=<', '>>', '><', '===', '~~', '^^', '>=<', '== ', 'or']:
            with self.subTest(operator=op):
                self.assertEqual(self.compare('1', op, '1'), 1)

    def test_parser_supports_only_documented_constraint_operators(self):
        for op in ['', '=', '==', '>', '>=', '<', '<=', '~', '^']:
            with self.subTest(operator=op):
                self.assertEqual(self.parse(op + '1.2'), ['0', op or '=', '1.2', 'kept'])

    def test_parser_rejects_combined_and_unsupported_operators(self):
        for op in ['=>', '=<', '>>', '><', '===', '~~', '^^', '>=<', '!=', ' ']:
            with self.subTest(operator=op):
                parsed = self.parse(op + '1.2')
                self.assertEqual(parsed[0:2], ['1', 'invalid'])
                self.assertEqual(parsed[-1], 'kept')

    def test_parser_rejects_invalid_numeric_versions_and_clears_stale_success(self):
        for value in INVALID:
            with self.subTest(value=value):
                parsed = self.parse('>=' + value)
                self.assertEqual(parsed[0:2], ['1', 'invalid'])
                self.assertEqual(parsed[-1], 'kept')

    def test_comparator_preserves_callers_index_ifs_and_strict_options(self):
        p = self.shell('''source bin/bashcmdr
set -euo pipefail
i=sentinel; IFS=,; before=$-
__bashcmdr_version_compare 1.2.3 '>=' 1.0
[[ $i == sentinel && $IFS == , && $- == "$before" ]]
''')
        self.ok(p); self.assertEqual(p.stderr, '')

    def test_public_plan_rejects_malformed_actual_versions_without_data_or_effects(self):
        for value in ['1.08.0', '1.0.0-rc1', '1.0.0.1', '1000000000', 'latest']:
            with self.subTest(version=value):
                self.set_dependency(value); before = self.snapshot()
                p = self.plan(); self.failed(p); self.assertEqual(p.stdout, '')
                self.assert_no_arithmetic_diagnostics(p); self.assertEqual(before, self.snapshot())

    def test_public_plan_rejects_malformed_constraints_without_data_or_effects(self):
        for constraint in ['>=1.00.0', '>=1000000000', '=>1', '><1', '>=1.0.0-rc1']:
            with self.subTest(constraint=constraint):
                self.set_dependency(constraint=constraint); before = self.snapshot()
                p = self.plan(); self.failed(p); self.assertEqual(p.stdout, '')
                self.assert_no_arithmetic_diagnostics(p); self.assertEqual(before, self.snapshot())

    def test_cli_plan_reports_failure_without_successful_order(self):
        self.set_dependency('1.08.0')
        p = self.cli('cartridge', 'plan', 'demo')
        self.failed(p); self.assertIn('Failed to resolve dependencies', p.stdout)
        self.assertNotIn('  Activation order:', p.stdout); self.assertEqual(self.trace.read_text(), '')
        self.assert_no_arithmetic_diagnostics(p)

    def test_plug_never_activates_on_invalid_numeric_version(self):
        self.set_dependency('1.0.0-rc1'); before = self.snapshot()
        p = self.shell('source bin/bashcmdr\nset -euo pipefail\nbashcmdr_plug_cartridge demo')
        self.failed(p); self.assertEqual(self.trace.read_text(), '')
        self.assertEqual(before, self.snapshot()); self.assert_no_arithmetic_diagnostics(p)

    def test_strict_boot_rejects_malformed_version_before_any_hook(self):
        self.set_dependency('1.08.0'); self.active('demo', 'dep', complete=True)
        before = {str(p.relative_to(self.repo)): str(p.readlink()) for p in (self.repo/'console/active').iterdir()}
        p = self.shell('source bin/bashcmdr\nset -euo pipefail\nconsole_poweron')
        self.failed(p); self.assertEqual(self.trace.read_text(), '')
        self.assertEqual(before, {str(p.relative_to(self.repo)): str(p.readlink()) for p in (self.repo/'console/active').iterdir()})
        self.assert_no_arithmetic_diagnostics(p)

    def test_valid_public_plan_is_complete_and_has_no_effects(self):
        self.set_dependency('1.2.3', '^1.2'); before = self.snapshot()
        p = self.plan(); self.ok(p); self.assertEqual(p.stdout, 'dep\ndemo\n')
        self.assertEqual(before, self.snapshot())

    def test_valid_strict_boot_preserves_dependency_order(self):
        self.set_dependency('1.2.3', '~1.2'); self.active('demo', 'dep', complete=True)
        p = self.shell('source bin/bashcmdr\nset -euo pipefail\nconsole_poweron')
        self.ok(p); self.assertEqual(self.trace.read_text(), 'dep:activate\ndemo:activate\n')


if __name__ == '__main__':
    if not os.environ.get('VERSION_TEST_EVIDENCE_DIR'):
        parent = REPO / 'tests/results'; parent.mkdir(parents=True, exist_ok=True)
        os.environ['VERSION_TEST_EVIDENCE_DIR'] = tempfile.mkdtemp(prefix='version-comparison.', dir=parent)
    evidence = pathlib.Path(os.environ['VERSION_TEST_EVIDENCE_DIR']); evidence.mkdir(parents=True, exist_ok=True)
    (evidence/'runner.json').write_text(json.dumps({'binary': BASH, 'repo': str(REPO)}, indent=2) + '\n')
    print('Version comparison artifacts: ' + str(evidence), flush=True)
    unittest.main(verbosity=2)
