#!/usr/bin/env python3
"""Execute README examples against a required console in owned local fixtures."""
import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

import provider_inputs

REPO = pathlib.Path(os.environ.get('CONSOLE_DOCS_TEST_REPO', pathlib.Path(__file__).resolve().parent.parent))
FIRST_PARTY = None
INPUTS = None
BASH = os.environ.get('CONSOLE_DOCS_TEST_BASH') or shutil.which('bash')
URLS = {'console': 'https://github.com/bashcmdr/console.git',
        'go': 'https://github.com/bashcmdr/cartridge-go.git',
        'demo': 'https://example.invalid/docs-demo.git'}


class ReadmeExamples(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bcm-console-readme-owned-')
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.home = self.root / 'home space'
        self.tools = self.root / 'tools'
        self.home.mkdir(); self.tools.mkdir()
        self.calls = []
        self.gitlog = self.root / 'git-calls.jsonl'; self.gitlog.write_text('')
        self.trace = self.root / 'forbidden.log'; self.trace.write_text('')
        self.gotrace = self.root / 'go-calls.jsonl'; self.gotrace.write_text('')
        self.env = {'HOME': str(self.home), 'PATH': str(self.tools) + os.pathsep + os.defpath,
                    'TMPDIR': str(self.root), 'LC_ALL': 'C', 'TERM': 'dumb',
                    'BASH_ENV': os.devnull, 'ENV': os.devnull, 'BASHCMDR_QUIET_BOOT': '1',
                    'BASHCMDR_VERBOSITY': '1', 'FORBIDDEN': str(self.trace), 'GO_CALLS': str(self.gotrace), 'DOCS_DEMO_SOURCE': URLS['demo'],
                    'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
                    'GIT_ALLOW_PROTOCOL': 'file', 'GIT_TERMINAL_PROMPT': '0'}
        (self.tools / 'bash').symlink_to(BASH)
        for name in ['curl', 'wget', 'sudo', 'service', 'systemctl']:
            path = self.tools / name
            path.write_text('#!' + BASH + '\nprintf "%s\\n" ' + name + ' >> "$FORBIDDEN"\nexit 99\n')
            path.chmod(0o755)
        self.project = self.root / 'project space'; self.project.mkdir()
        self.bootstrap = self.home / 'go bootstrap'
        self.userbin = self.home / 'go workspace/bin'
        (self.bootstrap / 'bin').mkdir(parents=True); self.userbin.mkdir(parents=True)
        self.saved_setting = self.home / '.config/go/env'
        go = self.bootstrap / 'bin/go'
        go.write_text('#!' + sys.executable + '\n' + r'''
import json,os,pathlib,sys
args=sys.argv[1:];home=pathlib.Path(os.environ['HOME']);setting=home/'.config/go/env'
with open(os.environ['GO_CALLS'],'a') as f:f.write(json.dumps({'args':args,'GOTOOLCHAIN':os.environ.get('GOTOOLCHAIN')})+'\n')
def reject():
    with open(os.environ['FORBIDDEN'],'a') as f:f.write('unexpected-go:'+repr(args)+'\n')
    sys.exit(99)
if args==['version']:print('go version fixture')
elif args[:1]==['env']:
    if args[1:2]==['-w']:
        if len(args)!=3 or not args[2].startswith('GOTOOLCHAIN='):reject()
        setting.parent.mkdir(parents=True,exist_ok=True);setting.write_text(args[2]+'\n')
    elif args[1:]==['-u','GOTOOLCHAIN']:setting.unlink(missing_ok=True)
    else:
        values={'GOROOT':os.environ.get('GOROOT',str(home/'go bootstrap')),'GOPATH':os.environ.get('GOPATH',str(home/'go workspace')),'GOBIN':os.environ.get('GOBIN','')}
        if not args[1:] or any(x not in values for x in args[1:]):reject()
        for name in args[1:]:print(values[name])
else:reject()
''')
        go.chmod(0o755)
        (self.tools / 'go').symlink_to(go)
        configured = self.home / 'custom go bootstrap/bin/go'
        configured.parent.mkdir(parents=True); shutil.copyfile(go, configured); configured.chmod(0o755)
        self.protected = [self.home / x for x in ['.bashrc', '.bash_profile', '.profile']] + [self.project / 'go.mod', self.project / 'go.work']
        for path in self.protected: path.write_text('owned profile sentinel\n')
        self.before = self.snapshot()
        self.sources = {name: self.root / 'sources' / ('source ' + name) for name in URLS}
        for path in self.sources.values(): path.mkdir(parents=True)
        for name in ['bin','lib','boot','docs']: shutil.copytree(REPO/name,self.sources['console']/name,symlinks=True)
        for name in ['VERSION','README.md','CLAUDE.md','INSTALL_REPORT.md','RESOLUTION_PLAN.md','TODO.md']: shutil.copyfile(REPO/name,self.sources['console']/name)
        go_source=pathlib.Path(INPUTS['go']['path'])
        for name in ['main.bashcmdr','manifest.json','README.md']: shutil.copyfile(go_source/name,self.sources['go']/name)
        contract=(REPO/'docs/CARTRIDGE_CONTRACT.md').read_text()
        manifest=re.search(r'^```json\n(.*?)^```',contract,re.M|re.S).group(1)
        script=re.search(r'^```bash\n(.*?)^```',contract,re.M|re.S).group(1)
        (self.sources['demo']/'manifest.json').write_text(manifest)
        (self.sources['demo']/'main.bashcmdr').write_text(script)

        templates = self.root / 'empty templates'; templates.mkdir()
        self.env['GIT_TEMPLATE_DIR'] = str(templates)
        real_git = shutil.which('git')
        self.revisions = {}
        for name, path in self.sources.items():
            for args in [('init', '--quiet', str(path)), ('-C', str(path), 'add', '--all'),
                         ('-C', str(path), '-c', 'user.name=fixture', '-c', 'user.email=fixture@example.invalid',
                          'commit', '--quiet', '-m', 'Owned exact source subset')]:
                subprocess.run([real_git, *args], env=self.env, check=True, capture_output=True, timeout=10)
            self.revisions[name] = subprocess.check_output([real_git, '-C', str(path), 'rev-parse', 'HEAD'], env=self.env, text=True).strip()
        wrapper = self.tools / 'git'
        wrapper.write_text('#!' + sys.executable + '\n' +
            'REAL=' + repr(real_git) + '\nROOT=' + repr(str(self.root)) + '\nLOG=' + repr(str(self.gitlog)) +
            '\nSOURCES=' + repr({URLS[n]: str(p) for n, p in self.sources.items()}) + '\n' + r'''
import json, pathlib, subprocess, sys
args = sys.argv[1:]
with open(LOG, 'a') as stream: stream.write(json.dumps(args) + '\n')
if args[:1] == ['clone']:
    assert args[-2] in SOURCES and pathlib.Path(args[-1]).resolve().is_relative_to(ROOT)
    assert args[:-2] in [['clone'], ['clone', '--quiet', '--']]
    args[-2] = SOURCES[args[-2]]
elif len(args) == 5 and args[0] == '-C' and args[2:] == ['rev-parse', '--verify', 'HEAD^{commit}']:
    assert pathlib.Path(args[1]).resolve().is_relative_to(ROOT)
else:
    sys.exit(96)
sys.exit(subprocess.run([REAL, *args]).returncode)
''')
        wrapper.chmod(0o755)

    def snapshot(self):
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.protected}

    def blocks(self, title):
        text = (REPO / 'README.md').read_text()
        match = re.search(r'^## ' + re.escape(title) + r'\n(.*?)(?=^## |\Z)', text, re.M | re.S)
        self.assertIsNotNone(match, 'README section missing: ' + title)
        return re.findall(r'^```bash\n(.*?)^```', match.group(1), re.M | re.S)

    def run_example(self, text, cwd=None):
        p = subprocess.run([BASH, '--noprofile', '--norc', '-e', '-o', 'pipefail', '-c', text],
                           cwd=cwd or self.project, env=self.env, text=True, capture_output=True, timeout=15)
        self.calls.append({'script': text, 'cwd': str(cwd or self.project), 'exit': p.returncode,
                           'stdout': p.stdout, 'stderr': p.stderr})
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.trace.read_text(), '')
        self.assertEqual(self.snapshot(), self.before)
        return p

    def console_install(self):
        blocks=self.blocks('Install the console')
        self.assertEqual(len(blocks),2)
        return blocks[0]

    def install_go(self):
        blocks=self.blocks('Install a first-party cartridge')
        self.assertEqual(len(blocks),2)
        return self.console_install()+'\n'+blocks[0]

    def install_go_and_boot(self):
        return self.install_go()+'\n'+self.blocks('Install a first-party cartridge')[1]

    def test_console_acquisition_and_empty_current_shell_boot(self):
        initial=self.run_example(self.console_install())
        self.assertIn('cartridge install go-loader --from https://github.com/bashcmdr/cartridge-go.git',initial.stdout)
        p=self.run_example(self.blocks('Install the console')[1]+'\n[[ $BASHCMDR_BOOT_EXIT_CODE == 0 ]]\nif declare -F go_diagnose >/dev/null; then exit 91; fi\n')
        self.assertIn('Bash Commander boot status: 0',p.stdout)
        self.assertFalse(self.saved_setting.exists())

    def test_first_party_install_state_differs_from_parent_functions(self):
        sequential=self.console_install()+'\n'+self.blocks('Install the console')[1]+'\n'+self.blocks('Install a first-party cartridge')[0]
        self.run_example(sequential+'\nif declare -F go_activate >/dev/null; then exit 91; fi\n')
        p=self.run_example(self.blocks('Install a first-party cartridge')[1]+'\n[[ $BASHCMDR_BOOT_EXIT_CODE == 0 && $BASHCMDR_GO_LOADED == 1 ]]\n')
        self.assertIn('Bootstrap executable:',p.stdout)
        metadata=json.loads((self.home/'.bashcmdr/registry/installed/go-loader.json').read_text())
        self.assertEqual(metadata['source']['commit'],self.revisions['go'])
        self.assertEqual(hashlib.sha256((self.home/'.local/bin/bashcmdr/cartridges/go-loader/main.bashcmdr').read_bytes()).hexdigest(),INPUTS['go']['files']['main.bashcmdr'])

    def test_inspection_help_and_recognized_stub_results(self):
        text=self.install_go_and_boot()+'\n'+self.blocks('Inspect and get help')[0]
        text+=r'''
for args in 'registry sync' 'console upgrade' 'console uninstall' 'cartridge upgrade go-loader'; do
    status=0
    bashcmdr $args > "$HOME/stub.out" 2>&1 || status=$?
    [[ $status == 1 ]] || exit 91
    grep -q 'not yet implemented' "$HOME/stub.out" || exit 92
done
env BASHCMDR_VERBOSITY=3 bashcmdr cartridge list outdated > "$HOME/outdated.out" 2>&1 || exit $?
grep -q 'not yet implemented' "$HOME/outdated.out" || exit 93
'''
        p=self.run_example(text)
        self.assertIn('Console Log',p.stdout)
        self.assertFalse(self.saved_setting.exists())

    def test_doctor_repairs_owned_orphan_reset_retains_active_state(self):
        text=self.install_go()+r'''
ln -s ../../cartridges/no-such-cartridge "$BASHCMDR_ROOT_DIR/console/active/no-such-cartridge"
status=0
bashcmdr doctor > "$HOME/doctor-first.out" 2>&1 || status=$?
[[ $status != 0 && ! -L "$BASHCMDR_ROOT_DIR/console/active/no-such-cartridge" ]] || exit 91
bashcmdr doctor || exit $?
bashcmdr console reset || exit $?
[[ -L "$BASHCMDR_ROOT_DIR/console/active/go-loader" ]] || exit 92
if declare -F go_activate >/dev/null; then exit 93; fi
'''
        self.run_example(text)
        self.assertFalse(self.saved_setting.exists())

    def test_exact_contract_dispatch_status_repeated_source_and_cleanup(self):
        text=self.console_install()+r'''
bashcmdr cartridge install docs-demo --from "$DOCS_DEMO_SOURCE" || exit $?
source "$BASHCMDR_ROOT_DIR/bin/bashcmdr"
before=$(declare -pf cartridge_dispatch)
__bashcmdr_cartridge_call docs-demo activate || exit $?
__bashcmdr_cartridge_call docs-demo activate || exit $?
[[ $BASHCMDR_DOCS_DEMO_LOADED == 1 && $(docs_demo_hello) == 'hello from docs-demo' ]] || exit 91
[[ $(declare -pf cartridge_dispatch) == "$before" ]] || exit 92
status=0
__bashcmdr_cartridge_call docs-demo diagnose 37 || status=$?
[[ $status == 37 && $(declare -pf cartridge_dispatch) == "$before" ]] || exit 93
__bashcmdr_cartridge_call docs-demo deactivate || exit $?
[[ -z ${BASHCMDR_DOCS_DEMO_LOADED-} && $(declare -pf cartridge_dispatch) == "$before" ]] || exit 94
if declare -F docs_demo_hello >/dev/null; then exit 95; fi
source "$BASHCMDR_ROOT_DIR/cartridges/docs-demo/main.bashcmdr" activate
[[ -z ${BASHCMDR_DOCS_DEMO_LOADED-} ]] || exit 96
'''
        self.run_example(text)

    def test_historical_presentations_inventory_links_and_sample_are_explicit(self):
        for name in ['INSTALL_REPORT.md','RESOLUTION_PLAN.md','tests/final_report.md','tests/mission_completion_report.md']:
            text=(REPO/name).read_text()
            self.assertIn('Historical development record',text)
            self.assertIn('exact original blob',text)
            self.assertNotRegex(text,r'/home/[A-Za-z0-9_.-]+/')
        paths=re.search(r'^## Exact tracked path list\n.*?^```text\n(.*?)^```',(REPO/'docs/DIRECTORY_STRUCTURE.md').read_text(),re.M|re.S).group(1).splitlines()
        self.assertEqual(len(paths),len(set(paths)))
        for name in paths:self.assertTrue((REPO/name).is_file() or (REPO/name).is_symlink(),name)
        for name in ['lib/interface.bashcmdr','docs/CARTRIDGE_CONTRACT.md','tests/test_resolver.bash','tests/test_path.bash','tests/test_install.bash','tests/test_docs.py']:self.assertIn(name,paths)
        data=json.loads((REPO/'tests/results/rapid_test_results.json').read_text())
        self.assertTrue(data['metadata']['historical_display_fixture'])
        self.assertTrue(data['metadata']['not_current_acceptance_or_expectations'])
        self.assertEqual(len(data['results']),35)
        self.assertTrue(all(x['command'].startswith('bashcmdr ') for x in data['results']))
        for name in ['README.md','CLAUDE.md','docs/CLI_GRAMMAR.md','docs/DIRECTORY_STRUCTURE.md','docs/CARTRIDGE_CONTRACT.md']:
            text=(REPO/name).read_text()
            for target in re.findall(r'\[[^\]\n]+\]\(([^)]+)\)',text):
                if target.startswith(('http:','https:','mailto:')):continue
                self.assertTrue((REPO/pathlib.Path(name).parent/target.split('#',1)[0]).exists(),name+': '+target)

    def test_current_readiness_claims_states_and_development_entrypoints(self):
        text=(REPO/'README.md').read_text()
        self.assertNotRegex(text,r'(?i)status[^\n]*production.ready')
        self.assertNotIn('loaded into current shell session',text)
        self.assertIn('persistent state alone says nothing',text)
        self.assertIn('registry synchronization is not implemented',text)
        self.assertIn('[Apache-2.0](LICENSE)',text)
        self.assertIn('Copyright 2026 Eric Milgram',text)
        self.assertIn('[third-party notices](THIRD_PARTY_NOTICES.md)',text)
        for name in ['tests/test_runner.bash','tests/test_resolver.bash','tests/test_path.bash','tests/test_install.bash','tests/factorial_test_runner.bash','tests/test_docs.py']:self.assertIn(name,text)

    def test_missing_first_party_input_is_error(self):
        p=subprocess.run([sys.executable,str(pathlib.Path(__file__).resolve())],env={'PATH':os.defpath},text=True,capture_output=True,timeout=10)
        self.assertNotEqual(p.returncode,0)
        self.assertIn('--first-party-root',p.stderr)
        self.assertNotIn('skipped=',p.stderr)

    def tearDown(self):
        directory=os.environ.get('CONSOLE_DOCS_TEST_EVIDENCE_DIR')
        if directory:
            target=pathlib.Path(directory)/self.id().split('.')[-1];target.mkdir(parents=True,exist_ok=True)
            names=['bin/bashcmdr','README.md','CLAUDE.md','INSTALL_REPORT.md','RESOLUTION_PLAN.md','TODO.md','docs/CLI_GRAMMAR.md','docs/DIRECTORY_STRUCTURE.md','docs/CARTRIDGE_CONTRACT.md','tests/final_report.md','tests/mission_completion_report.md','tests/results/rapid_test_results.json']
            data={'calls':self.calls,'source_files':{name:hashlib.sha256((REPO/name).read_bytes()).hexdigest() for name in names},
                  'provider_inputs':INPUTS,'owned_fixture_commits':self.revisions,'intercepted_git':self.gitlog.read_text(),'forbidden':self.trace.read_text(),'go_calls':self.gotrace.read_text(),
                  'saved_setting_exists':self.saved_setting.exists(),'protected_before':self.before,'protected_after':self.snapshot(),'bash':BASH}
            (target/'records.json').write_text(json.dumps(data,indent=2)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__,add_help=False);parser.add_argument('--first-party-root')
    options,remaining=parser.parse_known_args()
    if not options.first_party_root:parser.error('--first-party-root is required; missing inputs must not become skipped success')
    FIRST_PARTY=pathlib.Path(options.first_party_root).resolve()
    try:INPUTS=provider_inputs.verify(FIRST_PARTY)
    except (OSError,ValueError,KeyError,subprocess.CalledProcessError) as error:parser.exit(1,'First-party fixture admission failed: '+str(error)+'\n')
    unittest.main(argv=[sys.argv[0],*remaining],verbosity=2)
