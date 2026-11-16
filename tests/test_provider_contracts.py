#!/usr/bin/env python3
"""Mandatory pinned first-party lifecycle contracts with owned inert tool interfaces."""
import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

import provider_inputs
import test_hook_context as hooks

REPO = pathlib.Path(os.environ.get('PROVIDER_TEST_REPO', pathlib.Path(__file__).resolve().parent.parent))
hooks.REPO = REPO
INPUTS = None
FLAGS = {'go-loader': 'BASHCMDR_GO_LOADED', 'nvm-loader': 'BASHCMDR_NVM_LOADED',
         'pyenv-loader': 'BASHCMDR_PYENV_LOADED', 'fabric-loader': 'BASHCMDR_FABRIC_LOADED'}


class ProviderContractTests(hooks.HookFixture):
    def setUp(self):
        if INPUTS is None:
            raise RuntimeError('Run test_provider_contracts.py with --first-party-root; skipping inputs is not a pass')
        super().setUp()
        self.manifests = {}
        self.calls = []
        for source in INPUTS.values():
            directory = pathlib.Path(source['path'])
            manifest = json.loads((directory / 'manifest.json').read_text())
            name = manifest['name']
            self.cartridge(name, (directory / 'main.bashcmdr').read_text())
            shutil.copyfile(directory / 'manifest.json', self.console / 'cartridges' / name / 'manifest.json')
            self.manifests[name] = manifest
        self.fixture_tools()

    def executable(self, relative, text):
        path = self.home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('#!' + self.bash + '\n' + text)
        path.chmod(0o755)

    fixture_tools = hooks.FirstPartyHookTests.fixture_tools

    def run_shell(self, body, *args, **kwargs):
        # The operator's PATH may contain real Go/Fabric/Pyenv installations.
        # Prefer the owned tools for every admitted provider lifecycle case.
        kwargs.setdefault('tool_path', True)
        result = super().run_shell(body, *args, **kwargs)
        self.calls.append({'body': body, 'args': args, 'options': kwargs, 'exit': result.returncode,
                           'stdout': result.stdout, 'stderr': result.stderr})
        return result

    def tearDown(self):
        directory = os.environ.get('PROVIDER_TEST_EVIDENCE_DIR')
        if directory:
            destination = pathlib.Path(directory) / self.id().split('.')[-1]
            destination.mkdir(parents=True, exist_ok=True)
            (destination / 'calls.json').write_text(json.dumps(self.calls, indent=2) + '\n')
            (destination / 'inputs.json').write_text(json.dumps(INPUTS, indent=2) + '\n')
            shutil.copyfile(self.trace, destination / 'operations.log')
            for name in ['logs', 'plan.stdout', 'plan.stderr', 'local-git-calls.jsonl',
                         'pinned-install-source.json', 'installed-metadata.json',
                         'protected-before.json', 'protected-after.json', 'declared-edge-control.json']:
                source = self.console / name
                if source.is_dir():
                    shutil.copytree(source, destination / name)
                elif source.is_file():
                    shutil.copyfile(source, destination / name)

    def provider_install_cycle(self, provider, pyenv_state):
        # Admit exact first-party bytes, then let the real installer clone an
        # owned local Git repository. No remote, upstream installer or sudo runs.
        for state in ['active', 'inactive', 'quarantine', 'broken']:
            for path in (self.console / 'console' / state).iterdir():
                path.unlink()
        for path in (self.console / 'cartridges').iterdir():
            shutil.rmtree(path)
        if pyenv_state != 'absent':
            source = pathlib.Path(INPUTS['pyenv']['path'])
            self.cartridge('pyenv-loader', (source / 'main.bashcmdr').read_text())
            shutil.copyfile(source / 'manifest.json', self.console / 'cartridges/pyenv-loader/manifest.json')
            if pyenv_state == 'quarantine':
                (self.console / 'console/inactive/pyenv-loader').unlink()
                (self.console / 'console/quarantine/pyenv-loader').symlink_to('../../cartridges/pyenv-loader')
        if pyenv_state != 'active':
            self.executable('.pyenv/bin/pyenv', 'printf "unexpected-unrelated-pyenv\\n" >> "$TRACE"; exit 97\n')
        upstream = self.root / ("owned " + provider.upper() + " 'source'")
        upstream.mkdir()
        for name in ['main.bashcmdr', 'manifest.json']:
            shutil.copyfile(pathlib.Path(INPUTS[provider]['path']) / name, upstream / name)
        git = shutil.which('git')
        env = {'PATH': os.environ.get('PATH', os.defpath), 'HOME': str(self.home),
               'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
               'GIT_TEMPLATE_DIR': str(self.root / 'empty templates'), 'GIT_ALLOW_PROTOCOL': 'file'}
        pathlib.Path(env['GIT_TEMPLATE_DIR']).mkdir()
        for args in [('init', '--quiet', str(upstream)),
                     ('-C', str(upstream), 'add', '--', 'main.bashcmdr', 'manifest.json'),
                     ('-C', str(upstream), '-c', 'user.name=fixture', '-c', 'user.email=fixture@example.invalid',
                      'commit', '--quiet', '-m', 'Owned exact provider bytes')]:
            subprocess.run([git, *args], env=env, check=True, capture_output=True, timeout=10)
        revision = subprocess.check_output([git, '-C', str(upstream), 'rev-parse', 'HEAD'], env=env, text=True).strip()
        (self.console / 'pinned-install-source.json').write_text(json.dumps({
            'input': INPUTS[provider], 'owned_fixture_commit': revision,
            'files': {name: hashlib.sha256((upstream / name).read_bytes()).hexdigest()
                      for name in ['main.bashcmdr', 'manifest.json']}}, indent=2) + '\n')
        gitlog = self.console / 'local-git-calls.jsonl'
        gitlog.write_text('')
        wrapper = self.root / 'owned-git.py'
        wrapper.write_text('#!' + sys.executable + '\n' +
            'REAL=' + repr(git) + '\nROOT=' + repr(str(self.root)) +
            '\nSOURCE=' + repr(str(upstream)) + '\nLOG=' + repr(str(gitlog)) + '\n' + r'''
import json, os, pathlib, subprocess, sys
args = sys.argv[1:]
with open(LOG, 'a') as stream: stream.write(json.dumps(args) + '\n')
if args[:1] == ['clone']:
    assert len(args) == 5 and args[:3] == ['clone', '--quiet', '--'] and args[3] == SOURCE
    assert pathlib.Path(args[4]).resolve().is_relative_to(ROOT)
elif len(args) == 5 and args[0] == '-C' and args[2:] == ['rev-parse', '--verify', 'HEAD^{commit}']:
    assert pathlib.Path(args[1]).resolve().is_relative_to(ROOT)
else:
    sys.exit(96)
environment = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                   GIT_TEMPLATE_DIR=str(pathlib.Path(ROOT) / 'empty templates'), GIT_ALLOW_PROTOCOL='file')
sys.exit(subprocess.run([REAL, *args], env=environment).returncode)
''')
        wrapper.chmod(0o755)
        protected = [self.home / name for name in ['.bashrc', '.bash_profile', '.profile']]
        for path in protected:
            path.write_text('owned startup sentinel\n')
        snapshot = lambda: {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in protected}
        before = snapshot()
        (self.console / 'protected-before.json').write_text(json.dumps(before))
        result = self.run_shell(r'''
PROVIDER_LOCAL_GIT=$1
git() { "$PROVIDER_LOCAL_GIT" "$@"; }
target=$4
loaded_flag=$5
[[ $(type -P go) == "$HOME/go-root/bin/go" && $(type -P fabric) == "$HOME/go/bin/fabric" && $(type -P pyenv) == "$HOME/.pyenv/bin/pyenv" ]] || exit 102
if [[ $3 == active ]]; then main cartridge plug pyenv-loader || exit $?; fi
pyenv_before=$(declare -pf pyenv 2>/dev/null || :)
pyenv_root_before=${PYENV_ROOT-unset}
pyenv_loaded_before=${BASHCMDR_PYENV_LOADED-unset}
before=$(declare -pf cartridge_dispatch)
main cartridge install "$target" --from "$2" || exit $?
[[ -d "$TEST_CONSOLE/cartridges/$target/.git" && -z ${!loaded_flag} ]] || exit 91
bashcmdr_get_activation_plan "$target" > "$TEST_CONSOLE/plan.stdout" 2> "$TEST_CONSOLE/plan.stderr" || exit $?
[[ $(cat "$TEST_CONSOLE/plan.stdout") == "$target" ]] || exit 92
main cartridge plug "$target" || exit $?
[[ ${!loaded_flag} == 1 && -L "$TEST_CONSOLE/console/active/$target" ]] || exit 93
if [[ $target == fabric-loader && $3 == active ]]; then
    main cartridge unplug pyenv-loader || exit $?
    [[ -z ${BASHCMDR_PYENV_LOADED-} && ${!loaded_flag} == 1 && $(type -P fabric) == "$HOME/go/bin/fabric" && $(fabric --version) == fixture-fabric ]] || exit 101
    main cartridge plug pyenv-loader || exit $?
fi
main cartridge unplug "$target" || exit $?
[[ -z ${!loaded_flag} && -L "$TEST_CONSOLE/console/inactive/$target" ]] || exit 94
[[ $(declare -pf cartridge_dispatch) == "$before" ]] || exit 95
[[ $(declare -pf pyenv 2>/dev/null || :) == "$pyenv_before" && ${PYENV_ROOT-unset} == "$pyenv_root_before" && ${BASHCMDR_PYENV_LOADED-unset} == "$pyenv_loaded_before" ]] || exit 96
case $3 in
absent) [[ ! -e "$TEST_CONSOLE/cartridges/pyenv-loader" ]] || exit 97;;
inactive) [[ -L "$TEST_CONSOLE/console/inactive/pyenv-loader" && ! -L "$TEST_CONSOLE/console/active/pyenv-loader" ]] || exit 98;;
quarantine) [[ -L "$TEST_CONSOLE/console/quarantine/pyenv-loader" && ! -L "$TEST_CONSOLE/console/active/pyenv-loader" ]] || exit 99;;
active) [[ -L "$TEST_CONSOLE/console/active/pyenv-loader" && ${BASHCMDR_PYENV_LOADED-} == 1 ]] || exit 100;;
esac
''', str(wrapper), str(upstream), pyenv_state, provider + '-loader', FLAGS[provider + '-loader'])
        after = snapshot()
        (self.console / 'protected-after.json').write_text(json.dumps(after))
        metadata_path = self.home / '.bashcmdr/registry/installed' / (provider + '-loader.json')
        if metadata_path.is_file():
            shutil.copyfile(metadata_path, self.console / 'installed-metadata.json')
        self.assert_ok(result)
        self.assertEqual(before, after)
        self.assertEqual(self.trace.read_text(), '')
        calls = [json.loads(line) for line in gitlog.read_text().splitlines()]
        self.assertEqual(len(calls), 2)
        metadata = json.loads(metadata_path.read_text())
        self.assertEqual(metadata['source']['commit'], revision)
        installed = self.console / 'cartridges' / (provider + '-loader')
        for name, digest in INPUTS[provider]['files'].items():
            self.assertEqual(hashlib.sha256((installed / name).read_bytes()).hexdigest(), digest)
        expected = {provider + '-loader'} | ({'pyenv-loader'} if pyenv_state != 'absent' else set())
        self.assertEqual({p.name for p in (self.console / 'cartridges').iterdir()}, expected)

    def test_nvm_fresh_install_cycle_without_pyenv(self):
        self.provider_install_cycle('nvm', 'absent')

    def test_nvm_fresh_install_cycle_preserves_inactive_pyenv(self):
        self.provider_install_cycle('nvm', 'inactive')

    def test_nvm_fresh_install_cycle_ignores_quarantined_pyenv(self):
        self.provider_install_cycle('nvm', 'quarantine')

    def test_nvm_fresh_install_cycle_preserves_active_pyenv(self):
        self.provider_install_cycle('nvm', 'active')

    def test_fabric_fresh_install_cycle_without_pyenv(self):
        self.provider_install_cycle('fabric', 'absent')

    def test_fabric_fresh_install_cycle_preserves_inactive_pyenv(self):
        self.provider_install_cycle('fabric', 'inactive')

    def test_fabric_fresh_install_cycle_ignores_quarantined_pyenv(self):
        self.provider_install_cycle('fabric', 'quarantine')

    def test_fabric_fresh_install_cycle_preserves_active_pyenv_and_allows_unplug(self):
        self.provider_install_cycle('fabric', 'active')

    def test_fabric_declared_edge_still_blocks_pyenv_unplug(self):
        path = self.console / 'cartridges/fabric-loader/manifest.json'
        data = json.loads(path.read_text())
        data['requires']['cartridges'] = {'pyenv-loader': '>=1.0.0'}
        path.write_text(json.dumps(data))
        (self.console / 'declared-edge-control.json').write_text(json.dumps(data))
        self.states()
        result = self.run_shell(r'''
main cartridge plug pyenv-loader || exit $?
main cartridge plug fabric-loader || exit $?
[[ $(type -P fabric) == "$HOME/go/bin/fabric" ]] || exit 94
main cartridge unplug pyenv-loader; status=$?
[[ $status == 1 && ${BASHCMDR_FABRIC_LOADED-} == 1 && ${BASHCMDR_PYENV_LOADED-} == 1 ]] || exit 91
[[ $(fabric --version) == fixture-fabric ]] || exit 92
main cartridge unplug fabric-loader || exit $?
main cartridge unplug pyenv-loader || exit $?
[[ -z ${BASHCMDR_FABRIC_LOADED-} && -z ${BASHCMDR_PYENV_LOADED-} ]] || exit 93
''')
        self.assert_ok(result)
        self.assertIn('required by active cartridge', result.stdout + result.stderr)
        self.assertEqual(self.trace.read_text(), '')

    def states(self, active=(), quarantine=()):
        for state in ['active', 'inactive', 'quarantine', 'broken']:
            for path in (self.console / 'console' / state).iterdir():
                path.unlink()
        for name in self.manifests:
            state = 'quarantine' if name in quarantine else 'active' if name in active else 'inactive'
            (self.console / 'console' / state / name).symlink_to('../../cartridges/' + name)

    def failing_client(self):
        self.cartridge('failure-client', r'''
cartridge_dispatch() {
    case "$1" in
        activate)
            [[ ${BASHCMDR_NVM_LOADED-} == 1 ]] || return 92
            printf 'NVM-WAS-LOADED\n' >> "$TRACE"
            return 37 ;;
        deactivate) return 0 ;;
        *) return 2 ;;
    esac
}
''')
        path = self.console / 'cartridges/failure-client/manifest.json'
        data = json.loads(path.read_text())
        data['requires']['cartridges'] = {'nvm-loader': '>=1.0.0'}
        path.write_text(json.dumps(data))

    def test_fresh_cli_real_activation_deactivation_and_dispatcher_restore(self):
        for name, flag in FLAGS.items():
            with self.subTest(name=name):
                self.states()
                result = self.run_shell(r'''
before=$(declare -pf cartridge_dispatch)
main cartridge plug "$1" || exit $?
[[ ${!2} == 1 && $(declare -pf cartridge_dispatch) == "$before" ]] || exit 91
if [[ $1 == pyenv-loader ]]; then [[ :$PATH: == *":$HOME/.pyenv/bin:"* ]] || exit 92; fi
main cartridge unplug "$1" || exit $?
[[ -z ${!2} && $(declare -pf cartridge_dispatch) == "$before" ]] || exit 93
''', name, flag)
                self.assert_ok(result)

    def test_actual_standard_setup_and_help_callbacks_remain_framework_safe(self):
        titles = {'go-loader': 'Go Loader:', 'nvm-loader': 'NVM Loader Cartridge',
                  'pyenv-loader': 'Pyenv Loader Cartridge', 'fabric-loader': 'Fabric Loader Cartridge'}
        for name, title in titles.items():
            with self.subTest(name=name):
                result = self.run_shell(r'''
before=$(declare -pf cartridge_dispatch)
__bashcmdr_cartridge_call "$1" setup || exit $?
__bashcmdr_cartridge_call "$1" help || exit $?
[[ $(declare -pf cartridge_dispatch) == "$before" ]] || exit 91
''', name, tool_path=True)
                self.assert_ok(result)
                self.assertIn(title, result.stdout)

    def test_actual_diagnose_callbacks_with_owned_configured_tools(self):
        titles = {'go-loader': 'go version fixture', 'nvm-loader': 'NVM Cartridge Diagnostic',
                  'pyenv-loader': 'Pyenv Cartridge Diagnostic', 'fabric-loader': 'Fabric Cartridge Diagnostic'}
        for name, title in titles.items():
            with self.subTest(name=name):
                result = self.run_shell('main cartridge diagnose "$1"', name, tool_path=True)
                self.assert_ok(result)
                self.assertIn(title, result.stdout)
                self.assertNotIn('does not implement diagnose', result.stderr)

    def test_real_diagnose_failure_is_observable(self):
        (self.home / '.nvm/nvm.sh').unlink()
        result = self.run_shell('main cartridge diagnose nvm-loader', tool_path=True)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('NVM script not found', result.stdout)

    def test_nvm_public_helpers_keep_configuration_after_console_callback(self):
        for configured in [False, True]:
            with self.subTest(configured=configured):
                directory = self.home / 'custom nvm space' if configured else self.home / '.nvm'
                if configured:
                    (self.home / '.nvm').rename(directory)
                self.states()
                result = self.run_shell(r'''
if [[ $1 == custom ]]; then export NVM_DIR=$2; else unset NVM_DIR; fi
main cartridge plug nvm-loader || exit $?
[[ $(declare -p NVM_CONFIG 2>/dev/null) == 'declare -A '* ]] || exit 91
[[ ${NVM_CONFIG[dir]} == "$NVM_DIR" ]] || exit 92
nvm_setup || exit $?
nvm_diagnose || exit $?
nvm_deactivate || exit $?
[[ -z ${BASHCMDR_NVM_LOADED-} ]] || exit 93
nvm_activate || exit $?
[[ ${BASHCMDR_NVM_LOADED-} == 1 && ${NVM_CONFIG[dir]} == "$NVM_DIR" ]] || exit 94
[[ $(nvm --version) == fixture-nvm ]] || exit 95
''', 'custom' if configured else 'default', str(directory))
                self.assert_ok(result)
                self.assertIn('NVM function available; version: fixture-nvm', result.stdout)
        self.assertEqual(self.trace.read_text(), '')

    def test_pyenv_public_helpers_keep_configuration_after_plug_and_bios(self):
        protected = [self.home / name for name in ['.bashrc', '.bash_profile', '.profile']]
        for path in protected:
            path.write_text('owned startup sentinel\n')
        snapshot = lambda: {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in protected}
        before = snapshot()
        (self.console / 'protected-before.json').write_text(json.dumps(before))
        for configured in [False, True]:
            root = self.home / 'custom pyenv data space' if configured else self.home / '.pyenv'
            root.mkdir(exist_ok=True)
            for bios in [False, True]:
                with self.subTest(configured=configured, bios=bios):
                    self.states(active=('pyenv-loader',) if bios else ())
                    result = self.run_shell(r'''
if [[ $1 == bios ]]; then
    [[ $BASHCMDR_BOOT_EXIT_CODE == 0 && ${BASHCMDR_PYENV_LOADED-} == 1 ]] || exit 91
else
    main cartridge plug pyenv-loader || exit $?
fi
# Call discovery first: the archived callback-local table aborts this caller.
pyenv_setup || exit $?
printf 'SETUP-RETURNED\n'
[[ $(declare -p PYENV_CONFIG 2>/dev/null) == 'declare -A '* ]] || exit 92
[[ ${PYENV_CONFIG[root]} == "$2" && $PYENV_ROOT == "$2" ]] || exit 93
pyenv_diagnose || exit $?
[[ $(pyenv --version) == fixture-python ]] || exit 94
pyenv_deactivate || exit $?
[[ -z ${BASHCMDR_PYENV_LOADED-} && -z ${BASHCMDR_PYENV_CONTEXT_ACTIVE-} && $PYENV_ROOT == "$2" ]] || exit 95
if declare -F pyenv >/dev/null; then exit 96; fi
pyenv_diagnose || exit $?
pyenv_activate || exit $?
[[ ${BASHCMDR_PYENV_LOADED-} == 1 && ${PYENV_CONFIG[root]} == "$2" && $(pyenv --version) == fixture-python ]] || exit 97
pyenv_deactivate || exit $?
printf 'HELPERS-RETURNED\n'
''', 'bios' if bios else 'plug', str(root), bios=bios,
                        shell_env={'PYENV_ROOT': str(root)} if configured else {})
                    self.assert_ok(result)
                    self.assertIn('SETUP-RETURNED', result.stdout)
                    self.assertIn('HELPERS-RETURNED', result.stdout)
                    self.assertIn('Bootstrap available; cartridge activation unverified', result.stdout)
        after = snapshot()
        (self.console / 'protected-after.json').write_text(json.dumps(after))
        self.assertEqual(before, after)
        self.assertEqual(self.trace.read_text(), '')

    def test_failed_client_rolls_back_new_real_provider_activation(self):
        self.failing_client()
        result = self.run_shell(r'''
main cartridge plug failure-client; status=$?
[[ $status == 1 && -z ${BASHCMDR_NVM_LOADED-} && -z ${BASHCMDR_PYENV_LOADED-} ]] || exit 91
[[ ! -L "$TEST_CONSOLE/console/active/nvm-loader" && -L "$TEST_CONSOLE/console/inactive/nvm-loader" ]] || exit 92
[[ ! -L "$TEST_CONSOLE/console/active/failure-client" ]] || exit 93
''')
        self.assert_ok(result)
        self.assertEqual(self.trace.read_text(), 'NVM-WAS-LOADED\n')

    def test_failed_client_preserves_preexisting_real_provider_context(self):
        self.failing_client()
        result = self.run_shell(r'''
main cartridge plug nvm-loader || exit $?
main cartridge plug failure-client; status=$?
[[ $status == 1 && ${BASHCMDR_NVM_LOADED-} == 1 ]] || exit 91
[[ -L "$TEST_CONSOLE/console/active/nvm-loader" && ! -L "$TEST_CONSOLE/console/active/failure-client" ]] || exit 92
''')
        self.assert_ok(result)
        self.assertEqual(self.trace.read_text(), 'NVM-WAS-LOADED\n')

    def test_verbose_real_plan_is_data_and_plug_uses_actual_declared_dependencies(self):
        result = self.run_shell(r'''
BASHCMDR_VERBOSITY=3
bashcmdr_get_activation_plan nvm-loader > "$TEST_CONSOLE/plan.stdout" 2> "$TEST_CONSOLE/plan.stderr" || exit $?
main cartridge plug nvm-loader || exit $?
[[ ${BASHCMDR_NVM_LOADED-} == 1 ]] || exit 91
''')
        self.assert_ok(result)
        rows = (self.console / 'plan.stdout').read_text().splitlines()
        required = set()
        def visit(name):
            if name in required:
                return
            required.add(name)
            for dependency in self.manifests[name].get('requires', {}).get('cartridges', {}):
                visit(dependency)
        visit('nvm-loader')
        self.assertEqual(set(rows), required)
        self.assertEqual(len(rows), len(required))
        for name in required:
            for dependency in self.manifests[name].get('requires', {}).get('cartridges', {}):
                self.assertLess(rows.index(dependency), rows.index(name))

    def test_full_boot_never_loads_quarantined_real_provider(self):
        self.states(active=tuple(FLAGS), quarantine=('nvm-loader',))
        result = self.run_shell(r'''
[[ $BASHCMDR_BOOT_EXIT_CODE == 0 && -z ${BASHCMDR_NVM_LOADED-} ]] || exit 91
[[ ${BASHCMDR_GO_LOADED-} == 1 && ${BASHCMDR_PYENV_LOADED-} == 1 && ${BASHCMDR_FABRIC_LOADED-} == 1 ]] || exit 92
[[ -L "$TEST_CONSOLE/console/quarantine/nvm-loader" && ! -L "$TEST_CONSOLE/console/active/nvm-loader" ]] || exit 93
''', bios=True)
        self.assert_ok(result)

    def test_quarantined_real_dependency_blocks_boot_before_other_hooks(self):
        self.failing_client()
        self.states(active=tuple(FLAGS), quarantine=('nvm-loader',))
        inactive = self.console / 'console/inactive/failure-client'
        if inactive.is_symlink():
            inactive.unlink()
        (self.console / 'console/active/failure-client').symlink_to('../../cartridges/failure-client')
        result = self.run_shell(r'''
[[ $BASHCMDR_BOOT_EXIT_CODE == 1 ]] || exit 91
[[ -z ${BASHCMDR_NVM_LOADED-} && -z ${BASHCMDR_GO_LOADED-} && -z ${BASHCMDR_PYENV_LOADED-} ]] || exit 92
[[ -L "$TEST_CONSOLE/console/quarantine/nvm-loader" ]] || exit 93
''', bios=True)
        self.assert_ok(result)
        self.assertEqual(self.trace.read_text(), '')

    def test_missing_declared_dependency_prevents_real_provider_activation(self):
        path = self.console / 'cartridges/nvm-loader/manifest.json'
        data = json.loads(path.read_text())
        data['requires']['cartridges'] = {'missing-fixture': '>=1.0.0'}
        path.write_text(json.dumps(data))
        result = self.run_shell('main cartridge plug nvm-loader; status=$?; [[ $status == 1 && -z ${BASHCMDR_NVM_LOADED-} ]]')
        self.assert_ok(result)
        self.assertEqual(self.trace.read_text(), '')

    def graph_cartridge(self, name, dependencies):
        body = 'cartridge_dispatch() { case "$1" in activate) [[ ${BASHCMDR_GO_LOADED-} == 1 ]] || return 91; printf "%s\\n" ' + name + ' >> "$TRACE" ;; deactivate) return 0 ;; *) return 2 ;; esac; }\n'
        self.cartridge(name, body)
        path = self.console / 'cartridges' / name / 'manifest.json'
        data = json.loads(path.read_text())
        data['requires']['cartridges'] = dependencies
        path.write_text(json.dumps(data))

    def test_diamond_resolution_loads_real_shared_provider_before_clients(self):
        self.graph_cartridge('left', {'go-loader': '>=1.0.0'})
        self.graph_cartridge('right', {'go-loader': '>=1.0.0'})
        self.graph_cartridge('client', {'left': '>=1.0.0', 'right': '>=1.0.0'})
        result = self.run_shell('main cartridge plug client || exit $?; [[ ${BASHCMDR_GO_LOADED-} == 1 ]]')
        self.assert_ok(result)
        rows = self.trace.read_text().splitlines()
        self.assertEqual(set(rows), {'left', 'right', 'client'})
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[-1], 'client')

    def test_cycle_rejection_happens_before_real_or_client_hooks(self):
        self.graph_cartridge('cycle-a', {'cycle-b': '>=1.0.0', 'go-loader': '>=1.0.0'})
        self.graph_cartridge('cycle-b', {'cycle-a': '>=1.0.0'})
        result = self.run_shell('main cartridge plug cycle-a; status=$?; [[ $status == 1 && -z ${BASHCMDR_GO_LOADED-} ]]')
        self.assert_ok(result)
        self.assertEqual(self.trace.read_text(), '')

    def test_version_conflict_rejection_happens_before_real_or_client_hooks(self):
        self.graph_cartridge('conflict', {'go-loader': '>=99.0.0'})
        result = self.run_shell('main cartridge plug conflict; status=$?; [[ $status == 1 && -z ${BASHCMDR_GO_LOADED-} ]]')
        self.assert_ok(result)
        self.assertEqual(self.trace.read_text(), '')

    def test_framework_help_never_sources_real_provider_code(self):
        for name in FLAGS:
            with self.subTest(name=name):
                prefix = name.removesuffix('-loader')
                result = self.run_shell(r'''
main cartridge plug "$1" --help || exit $?
main cartridge diagnose "$1" --help || exit $?
if declare -F "$2" >/dev/null; then exit 91; fi
''', name, prefix + '_activate')
                self.assert_ok(result)
                self.assertIn('Usage:', result.stdout)
        self.assertEqual(self.trace.read_text(), '')

    def test_missing_first_party_root_is_an_error_not_skipped_success(self):
        result = subprocess.run([sys.executable, str(pathlib.Path(__file__).resolve())],
                                env={k: v for k, v in os.environ.items() if k != 'PROVIDER_FIRST_PARTY_ROOT'},
                                text=True, capture_output=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('--first-party-root', result.stderr)
        self.assertNotIn('OK (skipped=', result.stderr)

    def test_changed_provider_content_is_rejected_before_hook_execution(self):
        root = self.root / 'changed inputs'
        for source in INPUTS.values():
            directory = root / pathlib.Path(source['path']).name
            directory.mkdir(parents=True)
            for name in source['files']:
                shutil.copyfile(pathlib.Path(source['path']) / name, directory / name)
        script = root / 'bashcmdr-cartridge-nvm/main.bashcmdr'
        script.write_text(script.read_text() + '\nprintf NEVER-RUN\n')
        with self.assertRaisesRegex(ValueError, 'content differs'):
            provider_inputs.verify(root)
        self.assertEqual(self.trace.read_text(), '')

    def test_exact_content_exports_are_labeled_without_inventing_git_head_evidence(self):
        root = self.root / 'exported inputs'
        for source in INPUTS.values():
            directory = root / pathlib.Path(source['path']).name
            directory.mkdir(parents=True)
            for name in source['files']:
                shutil.copyfile(pathlib.Path(source['path']) / name, directory / name)
        result = provider_inputs.verify(root)
        self.assertEqual(len(result), 4)
        self.assertTrue(all(x['observed_revision'] is None and x['verification'] == 'content_only_export' for x in result.values()))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, add_help=False)
    parser.add_argument('--first-party-root', default=os.environ.get('PROVIDER_FIRST_PARTY_ROOT'))
    options, remaining = parser.parse_known_args()
    if not options.first_party_root:
        parser.error('--first-party-root is required; missing first-party fixtures must not become skipped success')
    try:
        INPUTS = provider_inputs.verify(options.first_party_root)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        parser.exit(1, 'First-party fixture admission failed: ' + str(error) + '\n')
    if not os.environ.get('PROVIDER_TEST_EVIDENCE_DIR'):
        parent = REPO / 'tests/results'
        parent.mkdir(parents=True, exist_ok=True)
        os.environ['PROVIDER_TEST_EVIDENCE_DIR'] = tempfile.mkdtemp(prefix='provider-contracts.', dir=parent)
    evidence = pathlib.Path(os.environ['PROVIDER_TEST_EVIDENCE_DIR'])
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / 'admitted-inputs.json').write_text(json.dumps(INPUTS, indent=2) + '\n')
    print('Provider contract artifacts: ' + str(evidence), flush=True)
    unittest.main(argv=[sys.argv[0], *remaining], verbosity=2)
