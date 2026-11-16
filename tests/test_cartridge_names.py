#!/usr/bin/env python3
"""Name-boundary regressions: unsafe removal/link/hook operations are intercepted."""
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

REPO = pathlib.Path(os.environ.get('NAME_TEST_REPO', pathlib.Path(__file__).resolve().parent.parent))
BAD_NAMES = ['', '/', '../victim', '../../outside', 'demo/', './demo', 'demo/sub',
             r'a\b', 'demo name', '.hidden', '-demo', 'demo\nx', 'a*', "a'quoted", 'Aé']
FUNCTIONS = ['cartridge_install_cmd', 'cartridge_uninstall_cmd', 'cartridge_diagnose_cmd',
             'bashcmdr_plug_cartridge', 'bashcmdr_unplug_cartridge',
             'bashcmdr_quarantine_cartridge', 'bashcmdr_release_cartridge',
             '__bashcmdr_cartridge_call']
PREFIX = r'''
source "$BASHCMDR_ROOT_DIR/bin/bashcmdr"
declare -gA BASHCMDR_CARTRIDGES_STATE=()
declare -gA BASHCMDR_DEPENDENCY_GRAPH=()
if [[ -n $TEST_NAME ]]; then BASHCMDR_CARTRIDGES_STATE["$TEST_NAME"]=quarantine; fi
if [[ ${1-} == bashcmdr_release_cartridge ]] &&
   __bashcmdr_validate_cartridge_name "$TEST_NAME" >/dev/null 2>&1 &&
   [[ -L "$BASHCMDR_ROOT_DIR/console/inactive/$TEST_NAME" ]]; then
    command mv "$BASHCMDR_ROOT_DIR/console/inactive/$TEST_NAME" "$BASHCMDR_ROOT_DIR/console/quarantine/$TEST_NAME"
fi
bashcmdr_get_activation_plan() { printf '%s\n' "${TEST_PLAN:-$TEST_NAME}"; }
bashcmdr_get_dependents() { printf 'dependents:%s\n' "$1" >> "$TRACE"; }
__bashcmdr_load_dependencies() { printf 'dependencies:%s\n' "$1" >> "$TRACE"; }
git() { printf 'git\n' >> "$TRACE"; return 99; }
curl() { printf 'unexpected-curl\n' >> "$TRACE"; return 99; }
wget() { printf 'unexpected-wget\n' >> "$TRACE"; return 99; }
sudo() { printf 'unexpected-sudo\n' >> "$TRACE"; return 99; }
demo_diagnose() { printf 'diagnose\n' >> "$TRACE"; }
if [[ $TEST_INTERCEPT == 1 ]]; then
    rm() {
        printf 'rm'; printf '<%s>' "$@"; printf '\n'
        local relative="${1#"$BASHCMDR_ROOT_DIR/console/"}"
        if (($# == 1)) && [[ $relative != "$1" && -L $1 ]] &&
           [[ $relative =~ ^(active|inactive|broken|quarantine)/[A-Za-z0-9][A-Za-z0-9._-]*$ ||
              $relative =~ ^\.state-[A-Za-z0-9][A-Za-z0-9._-]*\.lock/(active|inactive|broken|quarantine)$ ]]; then
            command rm "$@"
        fi
        return 0
    } >> "$TRACE"
    ln() {
        printf 'ln'; printf '<%s>' "$@"; printf '\n'
        local relative="${3-}"
        relative="${relative#"$BASHCMDR_ROOT_DIR/console/"}"
        if (($# == 3)) && [[ $1 == -s || $1 == -sf ]] &&
           [[ $3 == "$BASHCMDR_ROOT_DIR/console/"* ]] &&
           [[ $relative =~ ^(active|inactive|broken|quarantine)/[A-Za-z0-9][A-Za-z0-9._-]*$ ]] &&
           [[ $2 == "../../cartridges/${3##*/}" ]]; then
            command ln "$@"
        fi
        return 0
    } >> "$TRACE"
    source() {
        if [[ $1 == "$BASHCMDR_ROOT_DIR/lib/path.bashcmdr" ]]; then
            builtin source "$@"
            return $?
        fi
        printf 'hook-source:%s\n' "$1" >> "$TRACE"
        cartridge_dispatch() { printf 'hook-dispatch:%s\n' "$*" >> "$TRACE"; }
        return 0
    }
fi
[[ $TEST_STRICT == 0 ]] || set -u
case "$TEST_MODE" in
    call) "$@" ;;
    state-roundtrip)
        __bashcmdr_set_cartridge_state demo active || exit $?
        [[ -L "$BASHCMDR_ROOT/console/active/demo" ]] || exit 80
        __bashcmdr_set_cartridge_state demo inactive || exit $?
        [[ ! -L "$BASHCMDR_ROOT/console/active/demo" && -L "$BASHCMDR_ROOT/console/inactive/demo" ]] ;;
    discovery)
        __bashcmdr_sync_physical_state
        printf '%s\n' "${!BASHCMDR_CARTRIDGES_STATE[@]}" ;;
esac
'''


class CartridgeNameTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bcm-name-boundary-')
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.home = self.root / 'home'
        self.console = self.home / 'console'
        self.console.mkdir(parents=True)
        for name in ['bin', 'lib', 'boot']:
            shutil.copytree(REPO / name, self.console / name)
        shutil.copyfile(REPO / 'VERSION', self.console / 'VERSION')
        for state in ['active', 'inactive', 'quarantine', 'broken']:
            (self.console / 'console' / state).mkdir(parents=True)
        self.metadata = self.home / '.bashcmdr/registry/installed'
        self.metadata.mkdir(parents=True)
        for path, name in [(self.console / 'cartridges/demo', 'demo'),
                           (self.console / 'cartridges/Alpha_2.x-9', 'Alpha_2.x-9'),
                           (self.console / 'victim', 'victim'),
                           (self.home / 'outside', 'outside'),
                           (self.console / 'cartridges', 'base')]:
            path.mkdir(parents=True, exist_ok=True)
            (path / 'manifest.json').write_text(json.dumps({'name': name, 'version': '1.0.0'}))
            (path / 'main.bashcmdr').write_text('printf "UNEXPECTED-HOOK-BODY\\n"\n')
            (path / 'sentinel').write_text('preserve-owned-fixture\n')
        for path in [self.metadata / 'demo.json', self.metadata.parent / 'victim.json',
                     self.home / '.bashcmdr/outside.json']:
            path.write_text('{"preserve":true}\n')
        for name in ['demo', 'Alpha_2.x-9']:
            (self.console / 'console/inactive' / name).symlink_to('../../cartridges/' + name)
        self.trace = self.root / 'operations.log'
        self.trace.write_text('')

    def fingerprint(self):
        result = {}
        for path in self.home.rglob('*'):
            key = str(path.relative_to(self.home))
            result[key] = ('link:' + os.readlink(path) if path.is_symlink() else
                           'dir' if path.is_dir() else hashlib.sha256(path.read_bytes()).hexdigest())
        return result

    def run_probe(self, *args, name='demo', plan=None, mode='call', intercept=True, strict=False):
        self.trace.write_text('')
        env = {'HOME': str(self.home), 'TMPDIR': str(self.root), 'PATH': '/usr/bin:/bin',
               'TERM': 'dumb', 'LC_ALL': 'C', 'BASHCMDR_ROOT_DIR': str(self.console),
               'TRACE': str(self.trace), 'TEST_NAME': name, 'TEST_MODE': mode,
               'TEST_INTERCEPT': '1' if intercept else '0', 'TEST_STRICT': '1' if strict else '0',
               'GIT_TERMINAL_PROMPT': '0', 'GIT_ALLOW_PROTOCOL': 'file'}
        if plan is not None:
            env['TEST_PLAN'] = plan
        return subprocess.run(['/bin/bash', '--noprofile', '--norc', '-c', PREFIX, 'fixture', *args],
                              env=env, cwd=self.root, capture_output=True, text=True, timeout=5)

    def assert_rejected(self, result, before, diagnostic='Invalid cartridge name'):
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(diagnostic, result.stderr)
        self.assertEqual(self.trace.read_text(), '', 'invalid name reached a backend or hook sink')
        self.assertEqual(self.fingerprint(), before, 'invalid name changed the owned fixture tree')
        self.assertNotIn('UNEXPECTED-HOOK-BODY', result.stdout + result.stderr)

    def arguments(self, function, name):
        if function == 'cartridge_install_cmd':
            return [function, name, '--from', 'fixture://not-a-network-source']
        if function == 'cartridge_uninstall_cmd':
            return [function, name, '--purge']
        if function == '__bashcmdr_cartridge_call':
            return [function, name, 'activate']
        return [function, name]

    def test_invalid_names_rejected_by_lifecycle_boundaries(self):
        for function in FUNCTIONS:
            for name in BAD_NAMES:
                with self.subTest(function=function, name=name):
                    before = self.fingerprint()
                    diagnostic = 'Unknown option:' if function == 'cartridge_install_cmd' and name.startswith('-') else 'Invalid cartridge name'
                    self.assert_rejected(self.run_probe(*self.arguments(function, name), name=name), before, diagnostic)

    def test_cli_dispatch_rejects_unsafe_names(self):
        for verb in ['install', 'uninstall', 'plug', 'unplug', 'diagnose', 'quarantine', 'release']:
            for name in ['/', '../victim', '../../outside', 'demo/', r'a\b', 'a*']:
                with self.subTest(verb=verb, name=name):
                    args = ['cartridge_dispatch', verb, name]
                    if verb == 'install':
                        args += ['--from', 'fixture://not-a-network-source']
                    before = self.fingerprint()
                    self.assert_rejected(self.run_probe(*args, name=name), before)

    def test_main_dispatch_rejects_path_names_without_requested_effects(self):
        for verb in ['install', 'uninstall', 'plug', 'unplug', 'diagnose', 'quarantine', 'release']:
            for name in ['../victim', '../../outside', 'demo/']:
                with self.subTest(verb=verb, name=name):
                    args = ['main', 'cartridge', verb, name]
                    if verb == 'install':
                        args += ['--from', 'fixture://not-a-network-source']
                    before = self.fingerprint()
                    self.assert_rejected(self.run_probe(*args, name=name), before)

    def test_state_boundary_rejects_unsafe_names(self):
        for name in BAD_NAMES:
            with self.subTest(name=name):
                before = self.fingerprint()
                self.assert_rejected(self.run_probe('__bashcmdr_set_cartridge_state', name, 'active', name=name), before)

    def test_metadata_boundaries_reject_unsafe_names(self):
        for function in ['bashcmdr_save_cartridge_metadata', 'bashcmdr_remove_cartridge_metadata']:
            for name in BAD_NAMES:
                with self.subTest(function=function, name=name):
                    before = self.fingerprint()
                    self.assert_rejected(self.run_probe(function, name, name=name), before)

    def test_missing_name_under_nounset_is_controlled(self):
        for function in FUNCTIONS + ['__bashcmdr_set_cartridge_state',
                                     'bashcmdr_save_cartridge_metadata', 'bashcmdr_remove_cartridge_metadata']:
            if function == 'cartridge_install_cmd':
                continue  # its omitted-name usage check has its own existing contract
            with self.subTest(function=function):
                before = self.fingerprint()
                self.assert_rejected(self.run_probe(function, name='', strict=True), before)

    def test_plan_is_preflighted_before_any_state_or_hook_effect(self):
        before = self.fingerprint()
        result = self.run_probe('bashcmdr_plug_cartridge', 'demo', plan='demo\n../victim')
        self.assert_rejected(result, before)

    def test_valid_multi_cartridge_plan_reaches_owned_hooks(self):
        result = self.run_probe('bashcmdr_plug_cartridge', 'demo', plan='demo\nAlpha_2.x-9')
        self.assertEqual(result.returncode, 0, result.stderr)
        trace = self.trace.read_text()
        self.assertIn('hook-source:' + str(self.console / 'cartridges/demo/main.bashcmdr'), trace)
        self.assertIn('hook-source:' + str(self.console / 'cartridges/Alpha_2.x-9/main.bashcmdr'), trace)
        self.assertNotIn('UNEXPECTED-HOOK-BODY', result.stdout)

    def test_ordinary_lifecycle_names_reach_expected_sinks(self):
        expected = {'cartridge_uninstall_cmd': 'rm<-rf><--><' + str(self.console / 'cartridges/demo') + '>',
                    'cartridge_diagnose_cmd': 'diagnose', 'bashcmdr_plug_cartridge': 'hook-source:',
                    'bashcmdr_unplug_cartridge': 'hook-source:', 'bashcmdr_quarantine_cartridge': 'ln',
                    'bashcmdr_release_cartridge': 'ln', '__bashcmdr_cartridge_call': 'hook-dispatch:activate'}
        for function, marker in expected.items():
            with self.subTest(function=function):
                metadata = self.metadata / 'demo.json'
                original_metadata = metadata.read_bytes()
                try:
                    if function == 'cartridge_uninstall_cmd':
                        metadata.write_text('{"cartridge":"demo"}\n')
                    result = self.run_probe(*self.arguments(function, 'demo'))
                    # This sink is deliberately inert. A successful rm status
                    # with a still-present package must no longer claim success.
                    self.assertEqual(result.returncode, 1 if function == 'cartridge_uninstall_cmd' else 0,
                                     result.stdout + result.stderr)
                    self.assertIn(marker, self.trace.read_text())
                    if function == 'cartridge_uninstall_cmd':
                        self.assertIn('did not remove the installed path', result.stderr)
                        self.assertTrue((self.console / 'cartridges/demo').is_dir())
                    self.assertNotIn('UNEXPECTED-HOOK-BODY', result.stdout)
                finally:
                    metadata.write_bytes(original_metadata)

    def test_documented_valid_install_names_reach_only_inert_git(self):
        for name in ['a', '9', 'Demo_1.v2-x']:
            with self.subTest(name=name):
                result = self.run_probe(*self.arguments('cartridge_install_cmd', name), name=name)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn('Failed to clone', result.stderr)
                self.assertIn('git', self.trace.read_text())
                self.assertNotIn('Invalid cartridge name', result.stderr)

    def test_real_owned_state_transition_preserves_valid_behavior(self):
        result = self.run_probe(mode='state-roundtrip', intercept=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(os.readlink(self.console / 'console/inactive/demo'), '../../cartridges/demo')

    def test_real_owned_metadata_roundtrip_preserves_valid_behavior(self):
        result = self.run_probe('bashcmdr_save_cartridge_metadata', 'demo', intercept=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads((self.metadata / 'demo.json').read_text())['cartridge'], 'demo')
        result = self.run_probe('bashcmdr_remove_cartridge_metadata', 'demo', intercept=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.metadata / 'demo.json').exists())

    def test_discovery_skips_invalid_directory_names_without_linking_them(self):
        (self.console / 'cartridges/.hidden').mkdir()
        result = self.run_probe(mode='discovery')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('demo', result.stdout.splitlines())
        self.assertNotIn('.hidden', result.stdout.splitlines())
        self.assertNotIn('/.hidden', self.trace.read_text())


if __name__ == '__main__':
    unittest.main(verbosity=2)
