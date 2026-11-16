#!/usr/bin/env python3
"""Git operand, protocol and installed-commit contracts using owned repositories."""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

import test_runtime_preflight as runtime

REPO = pathlib.Path(os.environ.get('SOURCE_TEST_REPO', pathlib.Path(__file__).resolve().parent.parent))
BASH = os.environ.get('SOURCE_TEST_BASH') or shutil.which('bash')
GIT = shutil.which('git')
runtime.REPO = REPO
runtime.BASH = BASH
POLICY = 'https:http:ssh:git:file'


class InstallSourceTests(runtime.RuntimeFixture):
    def setUp(self):
        super().setUp()
        self.upstream = self.top / "upstream 'quoted' repository"
        self.upstream.mkdir()
        self.gitlog = self.top / 'git-calls.jsonl'; self.gitlog.write_text('')
        self.templates = self.top / 'templates'; self.templates.mkdir()
        self.env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                        GIT_TEMPLATE_DIR=str(self.templates), GIT_TERMINAL_PROMPT='0')
        (self.upstream/'manifest.json').write_text(json.dumps({'name':'source-package', 'version':'1.0.0', 'requires':{'cartridges':{}}}))
        (self.upstream/'main.bashcmdr').write_text('printf "UNEXPECTED-SOURCE\\n" >> "$TRACE"\ncartridge_dispatch() { return 0; }\n')
        self.real_git('init', '--quiet', str(self.upstream))
        self.real_git('-C', str(self.upstream), 'add', '--', 'manifest.json', 'main.bashcmdr')
        self.real_git('-C', str(self.upstream), '-c', 'user.name=fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '--quiet', '-m', 'owned fixture')
        self.head = self.real_git('-C', str(self.upstream), 'rev-parse', 'HEAD').strip()
        self.url = self.upstream.as_uri()
        # Only local fixture clone/revision work can reach actual Git. All network
        # scheme controls are capture-only; the custom helper is an inert marker.
        wrapper = '''import json, os, pathlib, subprocess, sys
args=sys.argv[1:]
with open(LOG,'a') as f:f.write(json.dumps({'argv':args,'allow_protocol':os.environ.get('GIT_ALLOW_PROTOCOL')})+'\\n')
mode=os.environ.get('GIT_FIXTURE_MODE','actual')
if mode=='capture':sys.exit(73)
if args and args[0]=='clone':
    if args[-2] not in ALLOWED:sys.exit(94)
elif len(args)>=4 and args[0]=='-C' and args[2:4]==['rev-parse','--verify']:
    if not pathlib.Path(args[1]).resolve().is_relative_to(TOP):sys.exit(95)
    if mode=='head-failure':sys.exit(37)
    if mode=='bad-head':print('not-a-commit');sys.exit(0)
else:sys.exit(96)
sys.exit(subprocess.run([REAL,*args]).returncode)
'''
        wrapper = 'LOG='+repr(str(self.gitlog))+'\nREAL='+repr(GIT)+'\nTOP='+repr(str(self.top))+'\nALLOWED='+repr([self.url,str(self.upstream),'probe::owned'])+'\n'+wrapper
        path = self.tools/'git'; path.write_text('#!'+sys.executable+'\n'+wrapper); path.chmod(0o755)
        path = self.tools/'git-remote-probe'
        path.write_text('#!'+BASH+'\nprintf "CUSTOM-HELPER\\n" >> "$TRACE"\nexit 73\n'); path.chmod(0o755)

    def real_git(self, *args):
        return subprocess.run([GIT,*args],env=self.env,text=True,capture_output=True,check=True,timeout=10).stdout

    def tearDown(self):
        destination=pathlib.Path(os.environ['SOURCE_TEST_EVIDENCE_DIR'])/self.id().split('.')[-1]
        destination.mkdir(parents=True,exist_ok=True)
        (destination/'calls.json').write_text(json.dumps(self.calls,indent=2)+'\n')
        shutil.copyfile(self.gitlog,destination/'git-calls.jsonl'); shutil.copyfile(self.trace,destination/'operations.log')
        metadata=self.home/'.bashcmdr/registry/installed/source-package.json'
        if metadata.is_file():shutil.copyfile(metadata,destination/'metadata.json')

    def install(self, source=None, prefix=''):
        self.env['INSTALL_SOURCE']=source if source is not None else self.url
        return self.shell('source bin/bashcmdr\n'+prefix+'\ncartridge_install_cmd --from "$INSTALL_SOURCE"')

    def git_calls(self):
        return [json.loads(line) for line in self.gitlog.read_text().splitlines()]

    def metadata(self):
        data=json.loads((self.home/'.bashcmdr/registry/installed/source-package.json').read_text())
        self.assertIn('source',data)
        return data

    def no_package(self):
        self.assertFalse((self.repo/'cartridges/source-package').exists())
        self.assertFalse((self.home/'.bashcmdr/registry/installed/source-package.json').exists())

    def test_leading_dash_source_is_rejected_before_git(self):
        self.env['GIT_FIXTURE_MODE']='capture'; before=self.snapshot()
        p=self.install('--upload-pack=owned-inert-marker'); self.failed(p)
        self.assertIn('Invalid Git source operand',p.stderr); self.assertEqual(self.git_calls(),[])
        self.assertEqual(before,self.snapshot())

    def test_control_characters_in_source_are_rejected_before_git(self):
        self.env['GIT_FIXTURE_MODE']='capture'
        for source in ['file:///owned\nother','file:///owned\r','file:///owned\t']:
            with self.subTest(source=source):
                self.failed(self.install(source)); self.assertEqual(self.git_calls(),[]); self.no_package()

    def test_clone_has_explicit_option_boundary_and_exact_source_operand(self):
        self.env['GIT_FIXTURE_MODE']='capture'; self.failed(self.install())
        call=self.git_calls()[0]
        self.assertEqual(call['argv'][:4],['clone','--quiet','--',self.url])
        self.assertEqual(len(call['argv']),5); self.no_package()

    def test_protocol_policy_intersects_inheritance_without_changing_caller(self):
        self.env.update(GIT_FIXTURE_MODE='capture',GIT_ALLOW_PROTOCOL='probe:file')
        self.env['INSTALL_SOURCE']=self.url
        p=self.shell('source bin/bashcmdr\nif cartridge_install_cmd --from "$INSTALL_SOURCE"; then exit 91; fi\n[[ $GIT_ALLOW_PROTOCOL == probe:file ]]')
        self.ok(p); self.assertEqual(self.git_calls()[0]['allow_protocol'],'file')

    def test_inherited_file_only_limit_is_not_broadened_for_remote_source(self):
        self.env.update(GIT_FIXTURE_MODE='capture',GIT_ALLOW_PROTOCOL='file')
        self.failed(self.install('https://example.invalid/owned'))
        self.assertEqual(self.git_calls()[0]['allow_protocol'],'file')

    def test_metadata_records_the_effective_inherited_transport_limit(self):
        self.env['GIT_ALLOW_PROTOCOL']='file'; self.ok(self.install())
        self.assertEqual(self.metadata()['source']['allowed_protocols'],'file')

    def test_empty_inherited_policy_prevents_clone_before_any_temp_state(self):
        self.env.update(GIT_FIXTURE_MODE='capture',GIT_ALLOW_PROTOCOL='')
        before=self.snapshot(); self.failed(self.install()); self.assertEqual(self.git_calls(),[])
        self.assertEqual(before,self.snapshot())

    def test_remote_scheme_arguments_are_capture_only_and_use_same_policy(self):
        self.env['GIT_FIXTURE_MODE']='capture'
        for source in ['https://example.invalid/owned','http://example.invalid/owned',
                       'ssh://example.invalid/owned','git://example.invalid/owned','user@example.invalid:owned']:
            with self.subTest(source=source):
                self.failed(self.install(source)); call=self.git_calls()[-1]
                self.assertEqual(call['allow_protocol'],POLICY)
                self.assertEqual(call['argv'][2:4],['--',source])
        self.assertEqual(self.trace.read_text(),'')

    def test_custom_transport_is_denied_even_with_permissive_fixture_configuration(self):
        config=self.home/'git-config'; config.write_text('[protocol "probe"]\nallow = always\n')
        self.env.update(GIT_CONFIG_GLOBAL=str(config),GIT_ALLOW_PROTOCOL='probe:file')
        p=self.install('probe::owned'); self.failed(p); self.no_package()
        self.assertEqual(self.trace.read_text(),'')

    def test_url_rewrite_cannot_enable_a_custom_helper_transport(self):
        config=self.home/'git-config'
        config.write_text('[url "probe::owned"]\n insteadOf = '+self.url+'\n[protocol "probe"]\n allow = always\n')
        self.env.update(GIT_CONFIG_GLOBAL=str(config),GIT_ALLOW_PROTOCOL='probe:file')
        p=self.install(); self.failed(p); self.no_package()
        self.assertIn("transport 'probe' not allowed",p.stderr)
        self.assertEqual(self.trace.read_text(),'')

    def test_real_file_clone_records_exact_source_and_commit(self):
        p=self.install(); self.ok(p); metadata=self.metadata()
        self.assertEqual(metadata['source']['repository'],self.url)
        self.assertEqual(metadata['source']['commit'],self.head)
        self.assertEqual(metadata['source']['allowed_protocols'],POLICY)
        self.assertEqual(self.real_git('-C',str(self.repo/'cartridges/source-package'),'rev-parse','HEAD').strip(),self.head)
        self.assertEqual(self.trace.read_text(),'')

    def test_real_local_path_with_spaces_and_quotes_remains_usable(self):
        self.ok(self.install(str(self.upstream)))
        self.assertEqual(self.metadata()['source']['repository'],str(self.upstream))
        self.assertEqual(self.metadata()['source']['commit'],self.head)

    def test_registry_selected_source_gets_same_policy_and_provenance(self):
        index=self.home/'.bashcmdr/registry/index.json'; index.parent.mkdir(parents=True)
        index.write_text(json.dumps({'cartridges':{'source-package':{'version':'1.0.0','repository':self.url}}}))
        p=self.shell('source bin/bashcmdr\ncartridge_install_cmd source-package'); self.ok(p)
        self.assertEqual(self.git_calls()[0]['allow_protocol'],POLICY)
        self.assertEqual(self.metadata()['source']['commit'],self.head)

    def test_failed_clone_never_publishes_package_or_metadata(self):
        self.env['GIT_FIXTURE_MODE']='capture'; self.failed(self.install()); self.no_package()
        self.assertEqual(self.trace.read_text(),'')

    def test_failed_commit_read_never_publishes_package(self):
        self.env['GIT_FIXTURE_MODE']='head-failure'; p=self.install(); self.failed(p); self.no_package()
        self.assertIn('Cannot record cloned commit',p.stderr)

    def test_malformed_commit_read_never_publishes_package(self):
        self.env['GIT_FIXTURE_MODE']='bad-head'; p=self.install(); self.failed(p); self.no_package()
        self.assertIn('Cannot record cloned commit',p.stderr)

    def test_metadata_writer_treats_source_as_json_data(self):
        self.env.update(SOURCE_TEXT='quoted "source"; $(literal)',COMMIT_TEXT=self.head)
        p=self.shell('source bin/bashcmdr\nbashcmdr_save_cartridge_metadata demo "$SOURCE_TEXT" "$COMMIT_TEXT"'); self.ok(p)
        metadata=json.loads((self.home/'.bashcmdr/registry/installed/demo.json').read_text())
        self.assertIn('source',metadata)
        self.assertEqual(metadata['source']['repository'],self.env['SOURCE_TEXT'])
        self.assertEqual(metadata['source']['commit'],self.head)
        self.assertNotIn('allowed_protocols',metadata['source'])

    def test_metadata_writer_rejects_invalid_provenance_before_creation(self):
        self.env['COMMIT_TEXT']='not-a-commit'; before=self.snapshot()
        p=self.shell('source bin/bashcmdr\nbashcmdr_save_cartridge_metadata demo owned "$COMMIT_TEXT"'); self.failed(p)
        self.assertEqual(before,self.snapshot())
        self.env['COMMIT_TEXT']=self.head
        p=self.shell('source bin/bashcmdr\nbashcmdr_save_cartridge_metadata demo owned "$COMMIT_TEXT" probe'); self.failed(p)
        self.assertEqual(before,self.snapshot())

    def test_existing_package_is_preserved_after_manifest_name_discovery(self):
        self.ok(self.install()); before=self.snapshot(); count=len(self.git_calls())
        p=self.install(); self.failed(p); self.assertEqual(len(self.git_calls()),count+1)
        # URL-only installation reads the manifest to learn the package name.
        self.assertEqual(before,self.snapshot()); self.assertEqual(self.trace.read_text(),'')

    def test_metadata_failure_after_move_remains_explicit(self):
        p=self.install(prefix='bashcmdr_save_cartridge_metadata() { return 73; }'); self.failed(p)
        self.assertTrue((self.repo/'cartridges/source-package/manifest.json').is_file())
        self.assertIn('Package installed but metadata recording failed',p.stderr)
        self.assertNotIn('Cartridge installed:',p.stdout)

    def test_changed_default_head_is_recorded_without_a_signature_claim(self):
        (self.upstream/'README').write_text('second owned revision\n')
        self.real_git('-C',str(self.upstream),'add','README')
        self.real_git('-C',str(self.upstream),'-c','user.name=fixture','-c','user.email=fixture@example.invalid','commit','--quiet','-m','second')
        newhead=self.real_git('-C',str(self.upstream),'rev-parse','HEAD').strip(); self.assertNotEqual(newhead,self.head)
        self.ok(self.install()); self.assertEqual(self.metadata()['source']['commit'],newhead)
        self.assertNotIn('signature_verified',self.metadata()['source'])

    def test_legacy_metadata_only_call_needs_no_git_and_claims_no_source(self):
        self.missing('git'); p=self.shell('source bin/bashcmdr\nbashcmdr_save_cartridge_metadata demo'); self.ok(p)
        metadata=json.loads((self.home/'.bashcmdr/registry/installed/demo.json').read_text())
        self.assertNotIn('source',metadata)


if __name__=='__main__':
    if not os.environ.get('SOURCE_TEST_EVIDENCE_DIR'):
        parent=REPO/'tests/results'; parent.mkdir(parents=True,exist_ok=True)
        os.environ['SOURCE_TEST_EVIDENCE_DIR']=tempfile.mkdtemp(prefix='install-source.',dir=parent)
    evidence=pathlib.Path(os.environ['SOURCE_TEST_EVIDENCE_DIR']); evidence.mkdir(parents=True,exist_ok=True)
    (evidence/'runner.json').write_text(json.dumps({'binary':BASH,'git':GIT,'repo':str(REPO)},indent=2)+'\n')
    print('Install source artifacts: '+str(evidence),flush=True)
    unittest.main(verbosity=2)
