#!/usr/bin/env python3
"""Hook/dispatcher ownership in disposable shells; optional exact first-party inputs."""
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

REPO = pathlib.Path(os.environ.get('HOOK_TEST_REPO', pathlib.Path(__file__).resolve().parent.parent))
FIRST_PARTY = os.environ.get('HOOK_TEST_FIRST_PARTY_ROOT')
PREFIX = r'''
git() { printf 'unexpected-git\n' >> "$TRACE"; return 99; }
curl() { printf 'unexpected-curl\n' >> "$TRACE"; return 99; }
wget() { printf 'unexpected-wget\n' >> "$TRACE"; return 99; }
sudo() { printf 'unexpected-sudo\n' >> "$TRACE"; return 99; }
go() {
    case "${1-}" in
        version) printf 'go version fixture\n' ;;
        env) printf 'fixture\n' ;;
        *) printf 'unexpected-go\n' >> "$TRACE"; return 99 ;;
    esac
}
if [[ $TEST_BIOS == 1 ]]; then
    source "$TEST_CONSOLE/boot/shell-init.bashcmdr"
else
    source "$TEST_CONSOLE/bin/bashcmdr"
fi
'''
DEMO = r'''
cartridge_dispatch() {
    case "$1" in
        activate)
            addpath -f "$HOME/hook-bin" || return $?
            export HOOK_PERSIST=present
            hook_visible() { printf 'visible\n'; } ;;
        deactivate) delpath "$HOME/hook-bin" ;;
        diagnose) printf 'DEMO-DIAG\n'; return "${DEMO_STATUS:-0}" ;;
        help|setup) printf 'HOOK:%s\n' "$1" ;;
    esac
}
'''


class HookFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bcm-hook-context-')
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.home = self.root / 'home'
        self.console = self.home / '.local/bin/bashcmdr'
        self.console.mkdir(parents=True)
        for name in ['bin', 'lib', 'boot']:
            shutil.copytree(REPO / name, self.console / name, symlinks=True)
        shutil.copyfile(REPO / 'VERSION', self.console / 'VERSION')
        (self.console / 'cartridges').mkdir()
        for state in ['active', 'inactive', 'quarantine', 'broken']:
            (self.console / 'console' / state).mkdir(parents=True)
        (self.home / 'hook-bin').mkdir()
        self.bash = shutil.which('bash')
        self.trace = self.root / 'operations.log'
        self.trace.write_text('')

    def cartridge(self, name, body, active=False):
        directory = self.console / 'cartridges' / name
        directory.mkdir(parents=True)
        (directory / 'main.bashcmdr').write_text(body)
        (directory / 'manifest.json').write_text(json.dumps({'name': name, 'version': '1.0.0',
                                                           'requires': {'bashcmdr': '>=1.0.0'}}))
        state = 'active' if active else 'inactive'
        (self.console / 'console' / state / name).symlink_to('../../cartridges/' + name)

    def run_shell(self, body, *args, bios=False, tool_path=False, shell_env=None):
        paths = [str(self.home / 'go/bin'), str(self.home / 'go-root/bin'),
                 str(self.home / '.pyenv/bin')] if tool_path else []
        env = {'HOME': str(self.home), 'TMPDIR': str(self.root), 'PATH': ':'.join(paths + [os.environ.get('PATH', os.defpath)]),
               'TERM': 'dumb', 'LC_ALL': 'C', 'TEST_CONSOLE': str(self.console),
               'BASHCMDR_ROOT_DIR': str(self.console), 'BASHCMDR_QUIET_BOOT': '1',
               'BASHCMDR_VERBOSITY': '1', 'TRACE': str(self.trace),
               'TEST_BIOS': '1' if bios else '0', 'GOROOT': str(self.home / 'go-root'),
               'GIT_CONFIG_NOSYSTEM': '1', 'GIT_TERMINAL_PROMPT': '0', 'GIT_ALLOW_PROTOCOL': 'file'}
        env.update(shell_env or {})
        result = subprocess.run([self.bash, '--noprofile', '--norc', '-c', PREFIX + '\n' + body,
                                 'fixture', *args], cwd=self.root, env=env, text=True,
                                capture_output=True, timeout=8)
        self.assertNotIn('unexpected-', self.trace.read_text())
        return result

    def assert_ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class HookContextTests(HookFixture):
    def test_fresh_cli_hook_gets_path_helpers_and_persists_environment(self):
        self.cartridge('demo', DEMO)
        result = self.run_shell('''
__bashcmdr_cartridge_call demo activate || exit $?
[[ $HOOK_PERSIST == present && :$PATH: == *":$HOME/hook-bin:"* ]] || exit 81
hook_visible
''')
        self.assert_ok(result)
        self.assertIn('visible', result.stdout)

    def test_complete_bios_helpers_are_preserved(self):
        self.cartridge('demo', DEMO)
        result = self.run_shell('''
source "$TEST_CONSOLE/lib/path.bashcmdr"
before=$(declare -f addpath)
__bashcmdr_cartridge_call demo activate || exit $?
[[ $(declare -f addpath) == "$before" && $HOOK_PERSIST == present ]]
''')
        self.assert_ok(result)

    def test_standard_actions_share_context_and_return_their_results(self):
        self.cartridge('demo', DEMO)
        result = self.run_shell('''
__bashcmdr_cartridge_call demo activate || exit $?
__bashcmdr_cartridge_call demo deactivate || exit $?
[[ :$PATH: != *":$HOME/hook-bin:"* ]] || exit 89
__bashcmdr_cartridge_call demo setup || exit $?
__bashcmdr_cartridge_call demo diagnose || exit $?
__bashcmdr_cartridge_call demo help
''')
        self.assert_ok(result)
        for marker in ['HOOK:setup', 'DEMO-DIAG', 'HOOK:help']:
            self.assertIn(marker, result.stdout)

    def test_dispatcher_is_restored_and_console_routing_survives(self):
        self.cartridge('demo', DEMO)
        result = self.run_shell('''
before=$(declare -pf cartridge_dispatch)
__bashcmdr_cartridge_call demo help || exit $?
[[ $(declare -pf cartridge_dispatch) == "$before" ]] || exit 82
cartridge_dispatch help
''')
        self.assert_ok(result)
        self.assertIn('bcm cartridge', result.stdout)

    def test_absent_ambient_dispatcher_stays_absent(self):
        self.cartridge('demo', DEMO)
        result = self.run_shell('''
unset -f cartridge_dispatch
__bashcmdr_cartridge_call demo help || exit $?
if declare -F cartridge_dispatch >/dev/null; then exit 83; fi
''')
        self.assert_ok(result)

    def test_exported_dispatcher_binding_is_restored(self):
        self.cartridge('demo', DEMO)
        result = self.run_shell('''
cartridge_dispatch() { printf 'CALLER-DISPATCH\\n'; }
export -f cartridge_dispatch
__bashcmdr_cartridge_call demo help || exit $?
"$BASH" --noprofile --norc -c 'cartridge_dispatch'
''')
        self.assert_ok(result)
        self.assertIn('CALLER-DISPATCH', result.stdout)

    def test_missing_dispatcher_cannot_reuse_ambient_function(self):
        self.cartridge('missing', 'export MISSING_LOADED=1\n')
        result = self.run_shell('''
cartridge_dispatch() { printf 'ambient-called\\n' >> "$TRACE"; }
before=$(declare -pf cartridge_dispatch)
__bashcmdr_cartridge_call missing activate; status=$?
[[ $status == 1 && $(declare -pf cartridge_dispatch) == "$before" ]] || exit 84
''')
        self.assert_ok(result)
        self.assertEqual(self.trace.read_text(), '')
        self.assertIn('dispatcher', result.stderr.lower())

    def test_sequential_missing_cartridge_cannot_reuse_previous_handler(self):
        self.cartridge('good', 'cartridge_dispatch() { export HOOK_CALLS=$((${HOOK_CALLS:-0}+1)); }\n')
        self.cartridge('missing', ':\n')
        result = self.run_shell('''
__bashcmdr_cartridge_call good activate || exit $?
__bashcmdr_cartridge_call missing activate; status=$?
[[ $status == 1 && $HOOK_CALLS == 1 ]]
''')
        self.assert_ok(result)

    def test_source_failure_restores_caller_and_preserves_status(self):
        self.cartridge('failed', 'cartridge_dispatch() { printf "SHOULD-NOT-RUN\\n"; }; return 23\n')
        result = self.run_shell('''
before=$(declare -pf cartridge_dispatch)
__bashcmdr_cartridge_call failed activate; status=$?
[[ $status == 23 && $(declare -pf cartridge_dispatch) == "$before" ]]
''')
        self.assert_ok(result)
        self.assertNotIn('SHOULD-NOT-RUN', result.stdout)

    def test_callback_failure_restores_caller_and_preserves_status(self):
        self.cartridge('failed', 'cartridge_dispatch() { return 37; }\n')
        result = self.run_shell('''
before=$(declare -pf cartridge_dispatch)
__bashcmdr_cartridge_call failed activate; status=$?
[[ $status == 37 && $(declare -pf cartridge_dispatch) == "$before" ]]
''')
        self.assert_ok(result)

    def test_readonly_ambient_function_fails_before_loading_cartridge(self):
        self.cartridge('demo', 'export SHOULD_NOT_LOAD=1\n' + DEMO)
        result = self.run_shell('''
readonly -f cartridge_dispatch
__bashcmdr_cartridge_call demo help; status=$?
[[ $status == 1 && -z ${SHOULD_NOT_LOAD:-} ]]
''')
        self.assert_ok(result)

    def test_missing_path_library_fails_before_loading_cartridge(self):
        self.cartridge('demo', 'export SHOULD_NOT_LOAD=1\n' + DEMO)
        (self.console / 'lib/path.bashcmdr').unlink()
        result = self.run_shell('''
__bashcmdr_cartridge_call demo activate; status=$?
[[ $status == 1 && -z ${SHOULD_NOT_LOAD:-} ]]
''')
        self.assert_ok(result)

    def test_loaded_helpers_work_without_forced_reimport(self):
        self.cartridge('demo', DEMO)
        shutil.copyfile(self.console / 'lib/path.bashcmdr', self.home / 'path-provider.bash')
        (self.console / 'lib/path.bashcmdr').write_text(': # no helpers here\n')
        self.assert_ok(self.run_shell('''
source "$HOME/path-provider.bash"
__bashcmdr_cartridge_call demo activate
'''))

    def test_empty_path_library_is_rejected_before_cartridge_load(self):
        self.cartridge('demo', 'export SHOULD_NOT_LOAD=1\n' + DEMO)
        (self.console / 'lib/path.bashcmdr').write_text(': # missing helper definitions\n')
        self.assert_ok(self.run_shell('''
__bashcmdr_cartridge_call demo activate; status=$?
[[ $status == 1 && -z ${SHOULD_NOT_LOAD:-} ]]
'''))

    def test_diagnose_uses_standard_dispatch_and_propagates_failure(self):
        self.cartridge('demo', DEMO)
        result = self.run_shell('main cartridge diagnose demo')
        self.assert_ok(result)
        self.assertIn('DEMO-DIAG', result.stdout)
        result = self.run_shell('DEMO_STATUS=29; cartridge_diagnose_cmd demo')
        self.assertEqual(result.returncode, 29, result.stdout + result.stderr)

    def test_bios_never_reuses_a_previous_cartridge_dispatcher(self):
        self.cartridge('alpha-good', 'cartridge_dispatch() { export HOOK_CALLS=$((${HOOK_CALLS:-0}+1)); }\n', active=True)
        self.cartridge('beta-missing', ': # no dispatcher\n', active=True)
        result = self.run_shell('''
[[ $HOOK_CALLS == 1 ]] || exit 85
grep -q 'failed=1' "$TEST_CONSOLE/logs/console-poweron.log" || exit 86
cartridge_dispatch help
''', bios=True)
        self.assert_ok(result)
        self.assertIn('bcm cartridge', result.stdout)

    def test_hook_after_bios_preserves_canonical_root(self):
        self.cartridge('demo', DEMO, active=True)
        result = self.run_shell('''
unset HOOK_PERSIST
[[ $BASHCMDR_ROOT == "$TEST_CONSOLE" ]] || exit 88
__bashcmdr_cartridge_call demo activate || exit $?
[[ $HOOK_PERSIST == present && $BASHCMDR_ROOT == "$TEST_CONSOLE" ]]
''', bios=True)
        self.assert_ok(result)

    def test_nested_hook_calls_restore_each_dispatcher(self):
        self.cartridge('inner', 'cartridge_dispatch() { export INNER_VISIBLE=1; }\n')
        self.cartridge('outer', '''cartridge_dispatch() {
__bashcmdr_cartridge_call inner activate || return $?
export OUTER_VISIBLE=1
}
''')
        result = self.run_shell('''
before=$(declare -pf cartridge_dispatch)
__bashcmdr_cartridge_call outer activate || exit $?
[[ $INNER_VISIBLE == 1 && $OUTER_VISIBLE == 1 && $(declare -pf cartridge_dispatch) == "$before" ]]
''')
        self.assert_ok(result)


@unittest.skipUnless(FIRST_PARTY, 'set HOOK_TEST_FIRST_PARTY_ROOT for exact cross-repository fixtures')
class FirstPartyHookTests(HookFixture):
    def providers(self, target):
        for child in (self.console / 'cartridges').iterdir():
            shutil.rmtree(child)
        for state in ['active', 'inactive', 'quarantine', 'broken']:
            for child in (self.console / 'console' / state).iterdir():
                child.unlink()
        names = [target] + (['pyenv'] if target in ['nvm', 'fabric'] else [])
        for name in names:
            source = pathlib.Path(FIRST_PARTY) / ('bashcmdr-cartridge-' + name)
            manifest = json.loads((source / 'manifest.json').read_text())
            self.cartridge(manifest['name'], (source / 'main.bashcmdr').read_text(), active=True)
            shutil.copyfile(source / 'manifest.json', self.console / 'cartridges' / manifest['name'] / 'manifest.json')
        self.fixture_tools()

    def executable(self, relative, text):
        path = self.home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('#!' + self.bash + '\n' + text)
        path.chmod(0o755)

    def fixture_tools(self):
        self.executable('go-root/bin/go', '''case "$1" in
version) printf 'go version fixture\\n';;
env) case "$2" in GOBIN) printf '%s/go/bin\\n' "$HOME";; GOPATH) printf '%s/go\\n' "$HOME";; GOTOOLCHAIN) printf 'fixture\\n';; *) exit 99;; esac;;
*) printf 'unexpected-go-binary\\n' >> "$TRACE"; exit 99;; esac
''')
        self.executable('go/bin/fabric', 'printf "fixture-fabric\\n"\n')
        self.executable('.pyenv/bin/pyenv', '''case "$1" in
root) printf '%s\\n' "${PYENV_ROOT:-$HOME/.pyenv}";;
init) printf '%s\\n' 'export PYENV_SHELL=bash' 'case :$PATH: in *:"$PYENV_ROOT/shims":*) ;; *) export PATH="$PYENV_ROOT/shims:$PATH";; esac' 'pyenv() { command pyenv "$@"; }';;
rehash) exit 0;;
virtualenv-init) printf ': # fixture plugin init\\n';;
commands) printf 'versions\\n';;
version|--version) printf 'fixture-python\\n';;
versions) printf 'fixture versions\\n';;
*) printf 'unexpected-pyenv\\n' >> "$TRACE"; exit 99;; esac
''')
        (self.home / '.pyenv/shims').mkdir(exist_ok=True)
        nvm = self.home / '.nvm'
        nvm.mkdir(exist_ok=True)
        (nvm / 'nvm.sh').write_text('''nvm() { case "${1-}" in --version) printf 'fixture-nvm\\n';; list) printf 'fixture-list\\n';; *) return 0;; esac; }
node() { printf 'fixture-node\\n'; }
npm() { printf 'fixture-npm\\n'; }
''')
        (nvm / 'bash_completion').write_text(': # fixture completion\n')

    def test_exact_first_party_activation_in_fresh_cli(self):
        flags = {'go': 'BASHCMDR_GO_LOADED', 'pyenv': 'BASHCMDR_PYENV_LOADED',
                 'nvm': 'BASHCMDR_NVM_LOADED', 'fabric': 'BASHCMDR_FABRIC_LOADED'}
        for name, flag in flags.items():
            with self.subTest(name=name):
                self.providers(name)
                result = self.run_shell('''
before=$(declare -pf cartridge_dispatch)
main cartridge plug "$1" || exit $?
[[ ${!2} == 1 && $(declare -pf cartridge_dispatch) == "$before" ]] || exit 90
main cartridge unplug "$1" || exit $?
[[ -z ${!2} && $(declare -pf cartridge_dispatch) == "$before" ]]
''', name + '-loader', flag)
                self.assert_ok(result)

    def test_exact_first_party_diagnose_routes_to_actual_callback(self):
        titles = {'go': 'go version fixture', 'pyenv': 'Pyenv Cartridge Diagnostic',
                  'nvm': 'NVM Cartridge Diagnostic', 'fabric': 'Fabric Cartridge Diagnostic'}
        for name, title in titles.items():
            with self.subTest(name=name):
                self.providers(name)
                result = self.run_shell('main cartridge diagnose "$1"', name + '-loader', tool_path=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(title, result.stdout)
                self.assertNotIn('does not implement diagnose', result.stderr)

    def test_exact_first_party_activation_persists_through_full_bios(self):
        flags = {'go': 'BASHCMDR_GO_LOADED', 'pyenv': 'BASHCMDR_PYENV_LOADED',
                 'nvm': 'BASHCMDR_NVM_LOADED', 'fabric': 'BASHCMDR_FABRIC_LOADED'}
        for name, flag in flags.items():
            with self.subTest(name=name):
                self.providers(name)
                result = self.run_shell('[[ ${!1} == 1 ]] || exit 87; cartridge_dispatch help', flag, bios=True)
                self.assert_ok(result)
                self.assertIn('bcm cartridge', result.stdout)

    def test_exact_first_party_reset_retains_choices_and_loaded_context(self):
        flags = {'go': 'BASHCMDR_GO_LOADED', 'pyenv': 'BASHCMDR_PYENV_LOADED',
                 'nvm': 'BASHCMDR_NVM_LOADED', 'fabric': 'BASHCMDR_FABRIC_LOADED'}
        for name, flag in flags.items():
            with self.subTest(name=name):
                self.providers(name)
                result = self.run_shell(r'''
before=$(declare -pf cartridge_dispatch)
console_reset || exit $?
[[ ${!1} == 1 && $(declare -pf cartridge_dispatch) == "$before" ]] || exit 90
[[ -L "$TEST_CONSOLE/console/active/$2" && ! -L "$TEST_CONSOLE/console/inactive/$2" ]] || exit 91
if [[ $2 == nvm-loader || $2 == fabric-loader ]]; then
    [[ ${BASHCMDR_PYENV_LOADED-} == 1 && -L "$TEST_CONSOLE/console/active/pyenv-loader" ]] || exit 92
fi
''', flag, name + '-loader', bios=True)
                self.assert_ok(result)


if __name__ == '__main__':
    unittest.main(verbosity=2)
