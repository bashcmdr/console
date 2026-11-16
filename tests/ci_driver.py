#!/usr/bin/env python3
"""Required Console development payload with explicit inputs and fresh evidence."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
SHELL_FILES = (
    'bin/bashcmdr', 'bin/bcm', 'boot/completions.bash', 'boot/shell-init.bashcmdr',
    'lib/core.bashcmdr', 'lib/guards.bashcmdr', 'lib/inspection.bashcmdr',
    'lib/interface.bashcmdr', 'lib/path.bashcmdr', 'lib/registry.bashcmdr',
    'lib/resolver.bashcmdr', 'lib/root.bashcmdr', 'lib/sourcing.bashcmdr', 'lib/state.bashcmdr',
    'scripts/bump-version.sh', 'tests/assertions.bash', 'tests/check-matrix.bash',
    'tests/ci.bash', 'tests/command_matrix_generator.bash', 'tests/factorial_test_runner.bash',
    'tests/harness.bash', 'tests/test_analyzer.bash', 'tests/test_install.bash',
    'tests/test_path.bash', 'tests/test_resolver.bash', 'tests/test_runner.bash',
)
PYTHON_SUITES = tuple('test_' + name + '.py' for name in (
    'activation_plan', 'alias_help', 'analyzer_contracts', 'boot_order', 'boot_status',
    'cartridge_names', 'cli_options', 'completion_data', 'dependency_inspection', 'docs',
    'harness_isolation', 'hook_context', 'install_source_policy', 'jq_inputs', 'local_info',
    'matrix_generator', 'path_edge_contracts', 'plug_rollback', 'provider_contracts',
    'quarantine_logs', 'quarantine_policy', 'reset', 'root_selection', 'runtime_preflight',
    'semantic_gates', 'shell_hygiene', 'sourcing_contracts', 'startup_footprint',
    'state_layout', 'state_results', 'tool_portability', 'uninstall_deps', 'version_comparison',
))
PROVIDER_SUITES = {
    'go': ('test_runtime_context.py', 'test_docs.py'),
    'nvm': ('test_runtime_context.py', 'test_nvm_hook.py', 'test_docs.py'),
    'pyenv': ('test_runtime_context.py', 'test_docs.py'),
    'fabric': ('test_runtime.py', 'test_docs.py'),
}
SHELLCHECK_SHA256 = 'f35ae15a4677945428bdfe61ccc297490d89dd1e544cc06317102637638c6deb'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def shell_suite_commands(bash):
    """The full runner and its negative controls use these same commands."""
    return {name: [str(bash), '--noprofile', '--norc', 'tests/'+name+'.bash']
            for name in ['test_runner', 'test_resolver', 'test_path', 'test_install', 'factorial_test_runner']}


def rapid_gate_command(bash, result=None):
    command = [str(bash), '--noprofile', '--norc', 'tests/check-matrix.bash']
    return command + ([str(result)] if result is not None else [])


class Checks:
    def __init__(self):
        parent = ROOT/'tests/results/ci'
        parent.mkdir(parents=True, exist_ok=True)
        self.directory = Path(tempfile.mkdtemp(prefix='run.', dir=parent))
        self.home = self.directory/'home'
        self.home.mkdir()
        self.summary = {'status': 'running', 'phases': [], 'platform': platform.platform(), 'machine': platform.machine(), 'scope':
            'Development proposal with owned external interfaces; no product-support, hosted-execution or release/publication acceptance.'}
        self.save()

    def save(self):
        temporary = self.directory/'summary.json.tmp'
        temporary.write_text(json.dumps(self.summary, indent=2)+'\n')
        temporary.replace(self.directory/'summary.json')

    def record(self, name, argv, callback):
        row = {'name': name, 'argv': [str(x) for x in argv], 'exit': None,
               'stdout': name+'.stdout.log', 'stderr': name+'.stderr.log'}
        self.summary['phases'].append(row)
        self.save()
        start = time.monotonic()
        try:
            with (self.directory/row['stdout']).open('w') as out, (self.directory/row['stderr']).open('w') as err:
                code = callback(out, err)
            row['exit'] = code
            if code:
                raise RuntimeError(f'{name} failed with exit {code}; see {self.directory/row["stderr"]}')
        except Exception as error:
            if row['exit'] is None:
                row['exit'] = 1
                with (self.directory/row['stderr']).open('a') as err:
                    err.write(str(error)+'\n')
            raise
        finally:
            row['duration_seconds'] = round(time.monotonic()-start, 3)
            (self.directory/(name+'.exit')).write_text(str(row['exit'])+'\n')
            self.save()
            print(f'{name}: exit {row["exit"]}', flush=True)

    def operation(self, name, callback):
        def execute(out, err):
            out.write(json.dumps(callback(), indent=2)+'\n')
            return 0
        self.record(name, [], execute)

    def run(self, name, argv, env, cwd=ROOT, methods=None):
        def execute(out, err):
            try:
                result = subprocess.run([str(x) for x in argv], cwd=cwd, env=env,
                                        stdout=out, stderr=err, timeout=180)
            except subprocess.TimeoutExpired:
                err.write('Phase exceeded the 180-second limit.\n')
                return 124
            if result.returncode == 0 and methods is not None:
                err.flush()
                text = (self.directory/(name+'.stderr.log')).read_text()
                match = re.search(r'(?m)^Ran (\d+) tests? in ', text)
                if not match or int(match.group(1)) != methods or not re.search(r'(?m)^OK$', text):
                    err.write('Required unittest count/success evidence is missing or includes skipped cases.\n')
                    return 1
            return result.returncode
        self.record(name, argv, execute)

    def suite(self, name, program, env, arguments=(), cwd=ROOT):
        tree = ast.parse(program.read_text())
        count = sum(isinstance(node, ast.FunctionDef) and node.name.startswith('test_') for node in ast.walk(tree))
        if count < 1:
            raise ValueError('Required suite contains no test methods: '+str(program))
        extra = dict(env)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            variable = node.value
            if re.fullmatch(r'[A-Z][A-Z0-9_]*_TEST_EVIDENCE_DIR', variable):
                directory = self.directory/'records'/name/variable.lower()
                directory.mkdir(parents=True, exist_ok=True)
                extra[variable] = str(directory)
            elif re.fullmatch(r'[A-Z][A-Z0-9_]*_TEST_BASH', variable):
                extra[variable] = env['CI_SELECTED_BASH']
        self.run(name, [sys.executable, program, *arguments], extra, cwd=cwd, methods=count)


def main():
    checks = Checks()
    print('Development evidence: '+str(checks.directory), flush=True)
    try:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--bash', required=True)
        parser.add_argument('first_party_root')
        args = parser.parse_args()
        selected = Path(args.bash).resolve(strict=True)
        provider_root = Path(args.first_party_root).resolve(strict=True)
        path = os.environ.get('PATH', os.defpath)
        found = shutil.which('bash', path=path)
        if not found or Path(found).resolve() != selected:
            path = str(selected.parent)+os.pathsep+path
        env = {'HOME': str(checks.home), 'PATH': path, 'BASH_ENV': os.devnull, 'ENV': os.devnull,
               'LC_ALL': 'C', 'TERM': 'dumb', 'PYTHONDONTWRITEBYTECODE': '1',
               'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
               'GIT_ALLOW_PROTOCOL': 'file', 'GIT_TERMINAL_PROMPT': '0',
               'CI_SELECTED_BASH': str(selected), 'HOOK_TEST_FIRST_PARTY_ROOT': str(provider_root)}
        for variable in ['LD_LIBRARY_PATH', 'DYLD_LIBRARY_PATH']:
            if variable in os.environ:
                env[variable] = os.environ[variable]
        inputs = {}
        protected = ROOT/'tests/results/rapid_test_results.json'
        protected_hash = sha(protected)
        initial_results = set((ROOT/'tests/results').iterdir())

        def capabilities():
            tools = {}
            for name in ['bash', 'python3', 'git', 'jq', 'shellcheck', 'env']:
                resolved = shutil.which(name, path=env['PATH'])
                if not resolved:
                    raise ValueError('Required development tool is missing: '+name)
                tools[name] = {'path': resolved, 'sha256': sha(Path(resolved))}
                if name != 'env':
                    tools[name]['version'] = subprocess.check_output([resolved, '--version'], env=env, text=True).splitlines()[0]
            if Path(tools['bash']['path']).resolve() != selected:
                raise ValueError('Child bash on PATH differs from the selected interpreter')
            if tools['shellcheck']['sha256'] != SHELLCHECK_SHA256:
                raise ValueError('Use the pinned official ShellCheck0.10.0 Linux x86_64 development tool; its binary hash differs')
            version = subprocess.check_output([str(selected), '--noprofile', '--norc', '-c', 'printf %s "$BASH_VERSION"'], env=env, text=True)
            match = re.match(r'(\d+)\.(\d+)', version)
            if not match or tuple(map(int, match.groups())) < (4, 3):
                raise ValueError('Development checks require Bash4.3 or newer')
            checks.summary['tools'] = tools
            checks.summary['selected_bash_version'] = version
            return tools
        checks.operation('capabilities', capabilities)

        def admission():
            discovered = {file.name for file in (ROOT/'tests').glob('test_*.py')}
            if discovered != set(PYTHON_SUITES):
                raise ValueError('Required Console suite manifest differs from discovered files: '+str(discovered ^ set(PYTHON_SUITES)))
            required = [*SHELL_FILES, *('tests/'+file for file in PYTHON_SUITES),
                        'tests/ci_driver.py', 'tests/ci-first-party.json', 'tests/first-party-inputs.json',
                        'tests/provider_inputs.py', 'tests/rapid-cases.json', 'tests/analyzer.jq',
                        'tests/matrix-catalog.jq', 'VERSION', 'README.md', '.shellcheckrc', '.github/workflows/test.yml']
            for file in required:
                target = ROOT/file
                if not target.is_file() or not target.resolve().is_relative_to(ROOT):
                    raise ValueError('Missing or outside-root required input: '+file)
                inputs[str(target)] = sha(target)
            tracked = subprocess.check_output(['git', '-C', str(ROOT), 'ls-files', '-z'], env=env).decode().split('\0')
            shells = {file for file in tracked if file and (Path(file).suffix in {'.bash', '.bashcmdr', '.sh'} or file in {'bin/bashcmdr','bin/bcm'})}
            if shells and shells != set(SHELL_FILES):
                raise ValueError('Tracked shell inventory differs from required lint/syntax targets: '+str(shells ^ set(SHELL_FILES)))
            import provider_inputs
            providers = provider_inputs.verify(provider_root)
            contract = json.loads((ROOT/'tests/ci-first-party.json').read_text())
            if contract.get('schema') != 'bashcmdr.ci-first-party.v1' or set(contract.get('inputs', {})) != set(PROVIDER_SUITES):
                raise ValueError('Expected four CI input content records')
            for name, suites in PROVIDER_SUITES.items():
                required_provider = {'README.md', *('tests/'+file for file in suites)}
                recorded = contract['inputs'][name]
                if set(recorded) != required_provider:
                    raise ValueError('CI test/guide content manifest differs: '+name)
                source = provider_root/('bashcmdr-cartridge-'+name)
                for file, expected in {**providers[name]['files'], **recorded}.items():
                    target = source/file
                    if not target.is_file() or not target.resolve().is_relative_to(source.resolve()):
                        raise ValueError('Missing or outside-provider CI input: '+name+'/'+file)
                    if not isinstance(expected, str) or not re.fullmatch(r'[a-f0-9]{64}', expected) or sha(target) != expected:
                        raise ValueError('CI provider content differs from pin: '+name+'/'+file)
                    inputs[str(target)] = expected
            checks.summary['providers'] = providers
            checks.summary['input_hashes'] = inputs
            return {'shell_targets': len(SHELL_FILES), 'console_suites': len(PYTHON_SUITES), 'providers': providers, 'input_hashes': inputs}
        checks.operation('input-admission', admission)
        for index, file in enumerate(SHELL_FILES):
            checks.run(f'syntax-{index+1:02d}', [selected, '--noprofile', '--norc', '-n', file], env)
        checks.run('shellcheck', ['shellcheck', '--norc', '-x', '-P', 'SCRIPTDIR', '-s', 'bash', *SHELL_FILES], env)
        shell_results = checks.directory/'shell-results'
        shell_results.mkdir()
        shell_env = {**env, 'BASHCMDR_TEST_RESULTS_DIR': str(shell_results)}
        for name, command in shell_suite_commands(selected).items():
            checks.run(name, command, shell_env)
        rapid = list(shell_results.glob('factorial.*/rapid_test_results.json'))
        if len(rapid) != 1:
            raise ValueError('Expected one current rapid result, never a historical sample')
        checks.run('actual-rapid-gate', rapid_gate_command(selected, rapid[0]), env)
        checks.run('actual-rapid-analysis', [selected, '--noprofile', '--norc', 'tests/test_analyzer.bash', '--output-dir', checks.directory/'analysis', rapid[0]], env)
        catalog = checks.directory/'catalog/full_factorial_matrix.json'
        catalog.parent.mkdir()
        checks.run('catalog-generation', [selected, '--noprofile', '--norc', 'tests/command_matrix_generator.bash', '--output', catalog], env)
        def catalog_gate():
            data = json.loads(catalog.read_text())
            if data['metadata']['execution'] != 'not_executed' or data['metadata']['total_combinations'] != 296 or len(data['test_matrix']) != 296:
                raise ValueError('Command catalog metadata/count differs from the current grammar contract')
            return {'execution': 'not_executed', 'cases': 296}
        checks.operation('catalog-gate', catalog_gate)
        for file in PYTHON_SUITES:
            arguments = ('--first-party-root', str(provider_root)) if file in {'test_docs.py','test_provider_contracts.py'} else ()
            checks.suite('console-'+Path(file).stem, ROOT/'tests'/file, env, arguments)
        for name, suites in PROVIDER_SUITES.items():
            source = provider_root/('bashcmdr-cartridge-'+name)
            for file in suites:
                arguments = ('--console-root', str(ROOT)) if file == 'test_docs.py' else ()
                checks.suite(name+'-'+Path(file).stem, source/'tests'/file, env, arguments, cwd=source)
        def preservation():
            if sha(protected) != protected_hash or any(sha(Path(file)) != expected for file,expected in inputs.items()):
                raise ValueError('A required input or retained historical sample changed during checks')
            for path in set((ROOT/'tests/results').iterdir())-initial_results:
                destination = checks.directory/'additional-results'/path.name
                destination.parent.mkdir(exist_ok=True)
                if path.is_dir():
                    shutil.copytree(path, destination)
                else:
                    shutil.copy2(path, destination)
            return {'all_input_hashes_preserved': True, 'historical_sample_preserved': True, 'current_rapid_result': str(rapid[0])}
        checks.operation('input-preservation', preservation)
        checks.summary['status'] = 'passed'
        checks.save()
        print('All required development checks passed.', flush=True)
        return 0
    except SystemExit as error:
        checks.summary.update(status='failed' if error.code else 'help', error='CLI exit '+str(error.code))
        checks.save()
        return error.code
    except Exception as error:
        checks.summary.update(status='failed', error=str(error))
        (checks.directory/'failure.log').write_text(str(error)+'\n')
        checks.save()
        print(str(error), file=sys.stderr)
        code = checks.summary['phases'][-1]['exit'] if checks.summary['phases'] else 1
        return code if isinstance(code, int) and 1 <= code <= 255 else 1


if __name__ == '__main__':
    sys.exit(main())
