#!/usr/bin/env python3
"""Offline discovery and import behavior in owned console trees."""
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

REPO = pathlib.Path(os.environ.get('LOCAL_INFO_TEST_REPO', pathlib.Path(__file__).resolve().parent.parent))


class LocalInfoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bcm-local-info-')
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.home = self.root / 'home with spaces'
        self.console = self.home / 'console'
        self.console.mkdir(parents=True)
        for part in ['bin', 'lib', 'boot']:
            shutil.copytree(REPO / part, self.console / part)
        shutil.copyfile(REPO / 'VERSION', self.console / 'VERSION')
        self.index = self.home / '.bashcmdr/registry/index.json'
        self.trace = self.root / 'external.log'
        self.trace.write_text('')
        self.env = {'HOME': str(self.home), 'CONSOLE': str(self.console),
                    'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'TERM': 'dumb',
                    'TMPDIR': str(self.root), 'TRACE': str(self.trace)}

    def tearDown(self):
        self.assertEqual(self.trace.read_text(), '', 'query executed a hook or external operation')

    def shell(self, body, entry='bin/bashcmdr', pre=''):
        inert = '\n'.join(name + '() { printf "unexpected-' + name + '\\n" >> "$TRACE"; return 99; }'
                          for name in ['git', 'curl', 'wget', 'sudo'])
        return subprocess.run(['/bin/bash', '--noprofile', '--norc', '-c',
                               inert + '\n' + pre + '\nsource "$CONSOLE/' + entry + '" || exit $?\n' + body],
                              env=self.env, cwd=self.root, text=True, capture_output=True, timeout=6)

    def ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def cartridge(self, name='demo', state=None, **overrides):
        path = self.console / 'cartridges' / name
        path.mkdir(parents=True)
        data = {'name': name, 'version': '1.2.3', 'description': 'Local description',
                'author': 'Alice "quoted"', 'tags': ['blue', 'path\\tag']}
        data.update(overrides)
        (path / 'manifest.json').write_text(json.dumps(data))
        (path / 'main.bashcmdr').write_text('printf "unexpected-hook\\n" >> "$TRACE"\n')
        if state:
            parent = self.console / 'console' / state
            parent.mkdir(parents=True, exist_ok=True)
            (parent / name).symlink_to('../../cartridges/' + name)
        return path

    def registry(self, index=None, **overrides):
        path = index or self.index
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {'version': 'selected-index', 'registry_url': 'fixture://owned',
                'timestamp': 'fixture-time', 'cartridges': {
                    'remote': {'version': '9.0.0', 'description': 'Remote description'}}}
        data.update(overrides)
        path.write_text(json.dumps(data))
        return path

    def snapshot(self):
        return sorted(str(p.relative_to(self.home)) for p in self.home.rglob('*'))

    def test_imports_create_no_directories(self):
        before = self.snapshot()
        for entry in ['lib/registry.bashcmdr', 'bin/bashcmdr']:
            with self.subTest(entry=entry):
                self.ok(self.shell(':', entry))
                self.assertEqual(self.snapshot(), before)

    def test_imports_do_not_call_mkdir(self):
        self.ok(self.shell(':', pre='mkdir() { printf "unexpected-mkdir\\n" >> "$TRACE"; return 73; }'))

    def test_import_succeeds_in_strict_shell(self):
        self.ok(self.shell(':', 'lib/registry.bashcmdr', 'set -euo pipefail'))

    def test_installed_show_without_registry(self):
        self.cartridge()
        result = self.shell('main cartridge show demo')
        self.ok(result)
        self.assertIn('Local description', result.stdout)
        self.assertIn('installed', result.stdout)
        self.assertFalse(self.index.parent.exists())

    def test_installed_show_ignores_invalid_or_disagreeing_index(self):
        self.cartridge()
        self.registry(cartridges={'demo': {'version': '9.0.0', 'description': 'WRONG'}})
        for text in ['{broken', self.index.read_text()]:
            with self.subTest(text=text):
                self.index.write_text(text)
                result = self.shell('main cartridge show demo')
                self.ok(result)
                self.assertIn('1.2.3', result.stdout)
                self.assertNotIn('WRONG', result.stdout)

    def test_show_rejects_malformed_local_data_without_remote_fallback(self):
        path = self.cartridge()
        self.registry(cartridges={'demo': {'version': '9.0.0'}})
        for text in ['{broken', '[]', '{}\n{}', '']:
            with self.subTest(text=text):
                (path / 'manifest.json').write_text(text)
                result = self.shell('main cartridge show demo')
                self.assertEqual(result.returncode, 1)
                self.assertIn('Cannot read installed manifest', result.stderr)
                self.assertNotIn('9.0.0', result.stdout)

    def test_uninstalled_show_uses_registry(self):
        self.registry()
        result = self.shell('main cartridge show remote')
        self.ok(result)
        self.assertIn('9.0.0', result.stdout)
        self.assertIn('registry', result.stdout)

    def test_installed_show_missing_manifest_does_not_fall_back(self):
        path = self.cartridge()
        (path / 'manifest.json').unlink()
        self.registry(cartridges={'demo': {'version': '9.0.0'}})
        result = self.shell('main cartridge show demo')
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('9.0.0', result.stdout)

    def test_remote_show_without_index_fails(self):
        self.assertEqual(self.shell('main cartridge show remote').returncode, 1)

    def test_installed_search_uses_physical_manifests_without_metadata(self):
        self.cartridge()
        result = self.shell('main cartridge search --installed')
        self.ok(result)
        self.assertIn('demo', result.stdout)
        self.assertIn('1.2.3', result.stdout)
        self.assertIn('Local description', result.stdout)
        self.assertFalse(self.index.parent.exists())

    def test_local_search_ignores_invalid_index_and_stale_cache(self):
        self.cartridge()
        self.registry()
        self.index.write_text('{broken')
        metadata = self.index.parent / 'installed'
        metadata.mkdir()
        (metadata / 'ghost.json').write_text('{broken')
        result = self.shell('main cartridge search --installed')
        self.ok(result)
        self.assertIn('demo', result.stdout)
        self.assertNotIn('ghost', result.stdout)

    def test_active_search_without_index_excludes_inactive_and_quarantine(self):
        self.cartridge('selected', 'active')
        self.cartridge('inactive', 'inactive')
        self.cartridge('isolated', 'active')
        quarantine = self.console / 'console/quarantine'
        quarantine.mkdir()
        (quarantine / 'isolated').symlink_to('../../cartridges/isolated')
        result = self.shell('main cartridge search --active')
        self.ok(result)
        self.assertIn('selected', result.stdout)
        self.assertNotIn('inactive', result.stdout)
        self.assertNotIn('isolated', result.stdout)

    def test_active_search_ignores_dangling_and_wrong_target_links(self):
        self.cartridge('first', 'active')
        self.cartridge('other')
        link = self.console / 'console/active/first'
        link.unlink()
        link.symlink_to('../../cartridges/other')
        (link.parent / 'ghost').symlink_to('../../cartridges/ghost')
        result = self.shell('main cartridge search --active')
        self.ok(result)
        self.assertNotIn('first', result.stdout)
        self.assertNotIn('ghost', result.stdout)

    def test_local_filters_combine_and_preserve_regex(self):
        self.cartridge('alpha', 'active')
        self.cartridge('beta', 'inactive', tags=['red'], author='Bob')
        result = self.shell("main cartridge search '^ALPHA$' --installed --active --tag '^BLUE$' --author 'quoted'")
        self.ok(result)
        self.assertIn('alpha', result.stdout)
        self.assertNotIn('beta', result.stdout)

    def test_local_regex_quoted_backslash_data_and_no_match(self):
        self.cartridge()
        for expression, expected in [("--author 'Alice \"quoted\"'", True),
                                     ("--tag 'path\\\\tag'", True), ("'^absent$'", False)]:
            with self.subTest(expression=expression):
                result = self.shell('main cartridge search --installed ' + expression)
                self.ok(result)
                self.assertEqual('demo' in result.stdout, expected)

    def test_invalid_regex_fails_even_with_empty_local_installation(self):
        for flag in ['', '--tag ', '--author ']:
            with self.subTest(flag=flag):
                result = self.shell("main cartridge search --installed " + flag + "'['")
                self.assertEqual(result.returncode, 1)
                self.assertIn('Invalid local search pattern', result.stderr)

    def test_bad_selected_manifest_fails_without_partial_results(self):
        self.cartridge('aaa')
        bad = self.cartridge('zzz')
        for text in ['{broken', '{}\n{}', '{"tags":false}', '{"author":{}}', '{"version":false}']:
            with self.subTest(text=text):
                (bad / 'manifest.json').write_text(text)
                result = self.shell('main cartridge search --installed')
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, '')
                self.assertIn('Cannot search installed manifest: zzz', result.stderr)

    def test_empty_direct_local_query_does_not_create_paths(self):
        before = self.snapshot()
        for flag in ['--installed', '--active']:
            self.ok(self.shell('cartridge_search_cmd ' + flag))
            self.assertEqual(self.snapshot(), before)

    def test_registry_status_honors_directory_override(self):
        directory = self.root / 'alternate registry'
        self.registry(directory / 'index.json')
        self.env['BASHCMDR_REGISTRY_DIR'] = str(directory)
        result = self.shell('main registry status')
        self.ok(result)
        self.assertIn('selected-index', result.stdout)
        self.assertNotIn('No registry index', result.stdout)
        self.assertFalse(self.index.parent.exists())

    def test_registry_status_honors_explicit_index_over_directory_and_default(self):
        custom = self.root / 'selected file.json'
        self.registry(custom, version='chosen')
        self.registry(version='WRONG')
        self.env.update({'BASHCMDR_REGISTRY_DIR': str(self.root / 'unused'), 'BASHCMDR_REGISTRY_INDEX': str(custom)})
        result = self.shell('main registry status')
        self.ok(result)
        self.assertIn('chosen', result.stdout)
        self.assertNotIn('WRONG', result.stdout)
        self.assertFalse((self.root / 'unused').exists())

    def test_missing_registry_status_is_read_only(self):
        before = self.snapshot()
        result = self.shell('registry_status_cmd')
        self.ok(result)
        self.assertIn('No registry index found', result.stdout)
        self.assertEqual(self.snapshot(), before)

    def test_invalid_registry_status_is_nonzero(self):
        self.registry()
        for text in ['{broken', '[]', '{"cartridges":[]}', '{"cartridges":{}}\n{"cartridges":{}}', '']:
            with self.subTest(text=text):
                self.index.write_text(text)
                result = self.shell('main registry status')
                self.assertEqual(result.returncode, 1)
                self.assertIn('Invalid registry index', result.stderr)

    def test_version_explicitly_creates_runtime_but_no_registry(self):
        self.ok(self.shell('main version'))
        self.assertTrue((self.console / 'cartridges').is_dir())
        for state in ['active', 'inactive', 'broken', 'quarantine']:
            self.assertTrue((self.console / 'console' / state).is_dir())
        self.assertFalse(self.index.parent.exists())

    def test_failed_runtime_creation_stops_dispatch(self):
        result = self.shell('mkdir() { return 73; }\nversion_cmd() { printf "UNEXPECTED"; }\nmain version')
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('UNEXPECTED', result.stdout)

    def test_metadata_writer_initializes_its_directory_on_demand(self):
        self.cartridge()
        result = self.shell('bashcmdr_save_cartridge_metadata demo')
        self.ok(result)
        metadata = json.loads((self.index.parent / 'installed/demo.json').read_text())
        self.assertEqual(metadata['cartridge'], 'demo')
        self.assertFalse(self.index.exists())

    def test_metadata_writer_propagates_creation_and_json_failure(self):
        path = self.cartridge()
        self.assertEqual(self.shell('mkdir() { return 73; }\nbashcmdr_save_cartridge_metadata demo').returncode, 1)
        (path / 'manifest.json').write_text('{broken')
        result = self.shell('bashcmdr_save_cartridge_metadata demo')
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('Metadata saved', result.stdout + result.stderr)

    def test_install_reports_metadata_failure_after_package_move(self):
        self.cartridge('fixture')
        # A local copy stub replaces clone; it performs no Git/network operation.
        fixture = self.console / 'cartridges/fixture'
        manifest = json.loads((fixture / 'manifest.json').read_text())
        manifest['name'] = 'new-package'
        (fixture / 'manifest.json').write_text(json.dumps(manifest))
        result = self.shell(r'''
git() {
    if [[ $1 == -C && $3 == rev-parse && $4 == --verify && $5 == 'HEAD^{commit}' ]]; then
        printf '%040d\n' 1
        return 0
    fi
    [[ $1 == clone && $2 == --quiet && $3 == -- && $4 == fixture://owned ]] || return 99
    mkdir -p -- "$5" || return 1
    cp -- "$CONSOLE/cartridges/fixture/manifest.json" "$5/manifest.json" || return 1
    cp -- "$CONSOLE/cartridges/fixture/main.bashcmdr" "$5/main.bashcmdr" || return 1
}
bashcmdr_save_cartridge_metadata() { return 73; }
cartridge_install_cmd --from fixture://owned
''')
        self.assertEqual(result.returncode, 1)
        self.assertTrue((self.console / 'cartridges/new-package/manifest.json').is_file())
        self.assertIn('Package installed but metadata recording failed', result.stderr)
        self.assertNotIn('Cartridge installed: new-package', result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
