#!/usr/bin/env python3
"""Local query-data regressions using disposable consoles and inert external sinks."""
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

REPO = pathlib.Path(os.environ.get('JQ_TEST_REPO', pathlib.Path(__file__).resolve().parent.parent))
PREFIX = r'''
source "$BASHCMDR_ROOT_DIR/bin/bashcmdr"
git() { printf 'unexpected-git\n' >> "$TRACE"; return 99; }
curl() { printf 'unexpected-curl\n' >> "$TRACE"; return 99; }
wget() { printf 'unexpected-wget\n' >> "$TRACE"; return 99; }
sudo() { printf 'unexpected-sudo\n' >> "$TRACE"; return 99; }
[[ $TEST_XPG == 0 ]] || shopt -s xpg_echo
case "$TEST_MODE" in
    function) "$@" ;;
    resolve)
        resolve_alias "$@"; result=$?
        printf '%s\0' "${RESOLVED_ARGS[@]}"
        exit "$result" ;;
    completion)
        source "$BASHCMDR_ROOT_DIR/boot/completions.bash"
        _init_completion() { cur=''; prev=$TEST_ALIAS; words=(bcm "$TEST_ALIAS" ''); cword=2; }
        __bcm_completions
        printf '%s\n' "${COMPREPLY[@]}" ;;
esac
'''


class QueryInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bcm-jq-inputs-')
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.home = self.root / 'home with spaces'
        self.console = self.home / 'console'
        self.console.mkdir(parents=True)
        for name in ['bin', 'lib', 'boot']:
            shutil.copytree(REPO / name, self.console / name)
        shutil.copyfile(REPO / 'VERSION', self.console / 'VERSION')
        self.aliases = self.home / '.bashcmdr/aliases.json'
        self.aliases.parent.mkdir()
        self.aliases.write_text(json.dumps({'keep': 'help'}))
        self.quoted = 'quoted"cart\\name'
        self.program_like = 'missing" | "UNEXPECTED" #'
        self.registry = self.root / 'index.json'
        self.data = {'cartridges': {
            'alpha': {'version': '1.0.0', 'description': 'Plain alpha', 'tags': ['blue'],
                      'author': 'Alice', 'requires': {'cartridges': {'dep-one': '>=1.0.0'}}},
            'beta': {'version': '2.0.0', 'description': 'Beta fixture', 'tags': ['tag"quoted'],
                     'author': 'Bob "quoted"'},
            self.quoted: {'version': '3.0.0', 'description': 'path\\bin "quoted"',
                          'tags': ['path\\tag'], 'author': 'C:\\Author'},
            self.program_like: {'version': '4.0.0', 'description': 'Local constant fixture',
                                'tags': ['other'], 'author': 'Other'}
        }}
        self.registry.write_text(json.dumps(self.data))
        self.trace = self.root / 'external-operations.log'
        self.trace.write_text('')

    def tearDown(self):
        self.assertEqual(self.trace.read_text(), '', 'query reached an external command sink')

    def run_query(self, *args, mode='function', alias='', xpg=False):
        env = {'HOME': str(self.home), 'TMPDIR': str(self.root), 'PATH': '/usr/bin:/bin',
               'TERM': 'dumb', 'LC_ALL': 'C', 'TRACE': str(self.trace),
               'BASHCMDR_ROOT_DIR': str(self.console), 'BASHCMDR_REGISTRY_INDEX': str(self.registry),
               'TEST_MODE': mode, 'TEST_ALIAS': alias, 'TEST_XPG': '1' if xpg else '0',
               'GIT_TERMINAL_PROMPT': '0', 'GIT_ALLOW_PROTOCOL': 'file'}
        return subprocess.run(['/bin/bash', '--noprofile', '--norc', '-c', PREFIX, 'fixture', *args],
                              env=env, cwd=self.root, capture_output=True, text=True, timeout=5)

    def assert_ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_alias_create_roundtrips_quotes_backslashes_and_newlines(self):
        target = 'console log "quoted" \\path\nsecond line'
        result = self.run_query('alias_cmd', self.quoted, target)
        self.assert_ok(result)
        self.assertEqual(json.loads(self.aliases.read_text()), {'keep': 'help', self.quoted: target})

    def test_alias_json_write_with_xpg_echo(self):
        target = 'console \\path "quoted"'
        self.assert_ok(self.run_query('alias_cmd', 'plain', target, xpg=True))
        self.assertEqual(json.loads(self.aliases.read_text())['plain'], target)

    def test_alias_remove_only_exact_quoted_key(self):
        self.aliases.write_text(json.dumps({'keep': 'help', self.quoted: 'console'}))
        self.assert_ok(self.run_query('alias_cmd', 'remove', self.quoted))
        self.assertEqual(json.loads(self.aliases.read_text()), {'keep': 'help'})

    def test_alias_resolution_literal_quoted_key(self):
        self.aliases.write_text(json.dumps({self.quoted: 'console log --lines 2'}))
        result = self.run_query(self.quoted, 'extra', mode='resolve')
        self.assert_ok(result)
        self.assertEqual(result.stdout.split('\0')[:-1], ['console', 'log', '--lines', '2', 'extra'])

    def test_alias_program_text_is_a_literal_key(self):
        self.aliases.write_text(json.dumps({self.program_like: 'console'}))
        result = self.run_query(self.program_like, mode='resolve')
        self.assert_ok(result)
        self.assertEqual(result.stdout.split('\0')[:-1], ['console'])

    def test_registry_lookup_literal_quoted_name(self):
        result = self.run_query('bashcmdr_get_cartridge_info', self.quoted, '.version')
        self.assert_ok(result)
        self.assertEqual(result.stdout.strip(), '3.0.0')

    def test_registry_program_text_is_a_literal_name(self):
        result = self.run_query('bashcmdr_get_cartridge_info', self.program_like, '.version')
        self.assert_ok(result)
        self.assertEqual(result.stdout.strip(), '4.0.0')

    def test_registry_default_field_returns_selected_object(self):
        result = self.run_query('bashcmdr_get_cartridge_info', 'alpha')
        self.assert_ok(result)
        self.assertEqual(json.loads(result.stdout), self.data['cartridges']['alpha'])

    def test_registry_internal_field_filter_contract(self):
        for name, query, expected in [('alpha', '.requires.cartridges // {}', {'dep-one': '>=1.0.0'}),
                                      ('beta', '.requires.cartridges // {}', {}),
                                      ('alpha', '.tags | join(",")', 'blue')]:
            with self.subTest(name=name, query=query):
                result = self.run_query('bashcmdr_get_cartridge_info', name, query)
                self.assert_ok(result)
                self.assertEqual(json.loads(result.stdout) if isinstance(expected, dict) else result.stdout.strip(), expected)

    def test_registry_malformed_internal_filter_is_nonzero(self):
        result = self.run_query('bashcmdr_get_cartridge_info', 'alpha', '.tags[')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')

    def test_show_quoted_name_and_fallback_display(self):
        result = self.run_query('main', 'cartridge', 'show', self.quoted)
        self.assert_ok(result)
        self.assertIn('=== Cartridge: ' + self.quoted + ' ===', result.stdout)
        self.assertIn('3.0.0', result.stdout)

    def test_show_program_text_name(self):
        result = self.run_query('cartridge_show_cmd', self.program_like)
        self.assert_ok(result)
        self.assertIn('=== Cartridge: ' + self.program_like + ' ===', result.stdout)
        self.assertIn('4.0.0', result.stdout)

    def test_keyword_regex_preserves_case_insensitive_anchors(self):
        result = self.run_query('main', 'cartridge', 'search', '^ALPHA$')
        self.assert_ok(result)
        self.assertIn('alpha', result.stdout)
        self.assertNotIn('beta', result.stdout)

    def test_keyword_regex_with_literal_quotes(self):
        result = self.run_query('main', 'cartridge', 'search', '"quoted"')
        self.assert_ok(result)
        self.assertIn('beta', result.stdout)
        self.assertIn(self.quoted, result.stdout)

    def test_keyword_regex_preserves_backslash_level(self):
        result = self.run_query('main', 'cartridge', 'search', r'path\\bin')
        self.assert_ok(result)
        self.assertIn(self.quoted, result.stdout)
        self.assertNotIn('alpha', result.stdout)

    def test_tag_and_author_regex_data(self):
        for option, pattern, expected in [('--tag', 'tag"quoted', 'beta'),
                                           ('--tag', r'path\\tag', self.quoted),
                                           ('--author', '^bob "quoted"$', 'beta')]:
            with self.subTest(option=option, pattern=pattern):
                result = self.run_query('main', 'cartridge', 'search', option, pattern)
                self.assert_ok(result)
                self.assertIn(expected, result.stdout)
                self.assertNotIn('alpha', result.stdout)

    def test_malformed_regex_is_nonzero_with_diagnostic(self):
        for arguments in [['['], ['--tag', '['], ['--author', '[']]:
            with self.subTest(arguments=arguments):
                result = self.run_query('main', 'cartridge', 'search', *arguments)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertNotEqual(result.stderr, '')
                self.assertNotIn('No cartridges found', result.stdout)

    def test_malformed_regex_is_rejected_even_for_empty_registry(self):
        self.registry.write_text('{"cartridges":{}}')
        for arguments in [['['], ['--tag', '['], ['--author', '[']]:
            with self.subTest(arguments=arguments):
                result = self.run_query('main', 'cartridge', 'search', *arguments)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_valid_regex_without_matches_is_success(self):
        result = self.run_query('main', 'cartridge', 'search', '^NOT-A-FIXTURE$')
        self.assert_ok(result)
        self.assertIn('No cartridges found', result.stdout)

    def test_invalid_registry_json_is_controlled(self):
        self.registry.write_text('{broken')
        result = self.run_query('main', 'cartridge', 'search', 'alpha')
        self.assertEqual(result.returncode, 1)
        self.assertNotEqual(result.stderr, '')

    def test_completion_resolves_literal_quoted_alias(self):
        self.aliases.write_text(json.dumps({self.quoted: 'console'}))
        result = self.run_query(mode='completion', alias=self.quoted)
        self.assert_ok(result)
        self.assertIn('poweron', result.stdout.splitlines())

    def test_completion_treats_program_text_as_literal_alias(self):
        self.aliases.write_text(json.dumps({self.program_like: 'console'}))
        result = self.run_query(mode='completion', alias=self.program_like)
        self.assert_ok(result)
        self.assertIn('poweron', result.stdout.splitlines())


if __name__ == '__main__':
    unittest.main(verbosity=2)
