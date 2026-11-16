#!/usr/bin/env python3
"""Analyzer data/query/output contracts using owned current-format result records."""
import copy
import json
import os
import pathlib
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

import test_runtime_preflight as runtime

REPO=pathlib.Path(os.environ.get('ANALYZER_TEST_REPO',pathlib.Path(__file__).resolve().parent.parent))
BASH=os.environ.get('ANALYZER_TEST_BASH') or shutil.which('bash')
REAL_GIT=shutil.which('git');REAL_JQ=shutil.which('jq')
runtime.REPO=REPO;runtime.BASH=BASH


class AnalyzerTests(runtime.RuntimeFixture):
    def setUp(self):
        super().setUp()
        shutil.copytree(REPO/'tests',self.repo/'tests',ignore=shutil.ignore_patterns('results','reports','__pycache__'))
        shutil.copyfile(REPO/'.gitignore',self.repo/'.gitignore')
        (self.tools/'bash').unlink();shutil.copyfile(BASH,self.tools/'bash');(self.tools/'bash').chmod(0o755)
        self.bash=str(self.tools/'bash')
        for name in ['cp','ls','uniq','sleep','touch','chmod','tr','id']:
            path=shutil.which(name)
            if path and not (self.tools/name).exists():(self.tools/name).symlink_to(path)
        self.input=self.home/"input 'quoted'.json"
        self.env['ANALYSIS_INPUT']=str(self.input)
        self.executable='/owned/bashcmdr-console/bin/bashcmdr'
        self.jqlog=self.top/'jq-calls.jsonl';self.jqlog.write_text('')
        self.write([self.row(1,['help']),self.row(2,['cartridge','list']),
                    self.row(3,['cartridge','show','console-help'],1,1)])

    def row(self,id,args,status=0,expected=0,output=''):
        passed=status==expected
        classification=('success' if expected==0 else 'expected_failure') if passed else ('mismatch' if status in [0,1] else 'error')
        return {'test_id':id,'argv':[self.executable,*args],
                'command':self.executable+' '+' '.join(args),'exit_code':status,
                'expected_exit':expected,'passed':passed,'classification':classification,
                'duration':1,'output':output,'output_log':f'case-{id}.output.log'}

    def dataset(self,rows):
        return {'metadata':{'schema':'bashcmdr.rapid-results.v1','executable':self.executable,
                            'generated_at':'2026-10-28T12:00:00Z','case_count':len(rows),
                            'duration_clock':'bash_SECONDS','duration_resolution_seconds':1},'results':rows}

    def write(self,rows):
        self.input.write_text(json.dumps(self.dataset(rows)))

    def shell(self,body):
        p=subprocess.run([self.bash,'--noprofile','--norc','-c',body],cwd=self.repo,env=self.env,
                         text=True,capture_output=True,timeout=30)
        self.calls.append({'body':body,'exit':p.returncode,'stdout':p.stdout,'stderr':p.stderr})
        return p

    def cli(self,*args):
        return self.shell('"$BASH" tests/test_analyzer.bash '+' '.join(shlex.quote(str(x)) for x in args))

    def reports(self,root=None):
        return sorted(p for p in (root or self.repo/'tests/results').glob('analysis.*') if p.is_dir())

    def model(self,root=None):
        directories=self.reports(root);self.assertEqual(len(directories),1)
        path=directories[0]/'analysis.json';self.assertTrue(path.is_file())
        return json.loads(path.read_text()),directories[0]

    def jq_fault(self,mode):
        state=self.top/'jq-state'
        code='''import json, pathlib, subprocess, sys
args=sys.argv[1:]
with open(LOG,'a') as f:f.write(json.dumps(args)+'\\n')
state=pathlib.Path(STATE);count=int(state.read_text())+1 if state.exists() else 1
state.write_text(str(count))
if count==(2 if MODE=='second' else 1):
    if MODE!='empty':print('0' if MODE=='first' else 'PARTIAL')
    sys.exit(0 if MODE=='empty' else 37)
sys.exit(subprocess.run([REAL,*args]).returncode)
'''
        path=self.tools/'jq';path.unlink()
        prefix='REAL='+repr(REAL_JQ)+'\nLOG='+repr(str(self.jqlog))+'\nSTATE='+repr(str(state))+'\nMODE='+repr(mode)+'\n'
        path.write_text('#!'+sys.executable+'\n'+prefix+code);path.chmod(0o755)

    def tearDown(self):
        destination=pathlib.Path(os.environ['ANALYZER_TEST_EVIDENCE_DIR'])/self.id().split('.')[-1]
        destination.mkdir(parents=True,exist_ok=True)
        (destination/'calls.json').write_text(json.dumps(self.calls,indent=2)+'\n')
        shutil.copyfile(self.jqlog,destination/'jq-calls.jsonl');shutil.copyfile(self.trace,destination/'operations.log')
        if self.input.exists():shutil.copyfile(self.input,destination/'input.json')
        for directory in self.reports():shutil.copytree(directory,destination/directory.name)
        if (self.repo/'tests/reports').exists():shutil.copytree(self.repo/'tests/reports',destination/'legacy-reports')
        if (self.home/'coverage.txt').exists():shutil.copyfile(self.home/'coverage.txt',destination/'coverage.txt')

    def test_categories_use_argv_not_checkout_or_operand_words(self):
        p=self.cli(self.input);self.ok(p);self.assertIn('Console commands: 0/0',p.stdout);model,_=self.model()
        self.assertEqual(model['summary']['total'],3)
        self.assertEqual(model['categories']['Console commands']['total'],0)
        self.assertEqual(model['categories']['Core commands']['total'],1)
        self.assertEqual(model['categories']['List commands']['total'],1)
        self.assertIn('Expected failures: 1',p.stdout)

    def test_current_absolute_argv_coverage_has_real_counts(self):
        p=self.shell('source tests/test_analyzer.bash\ngenerate_coverage_report "$ANALYSIS_INPUT" "$HOME/coverage.txt"');self.ok(p)
        text=(self.home/'coverage.txt').read_text()
        self.assertIn('["cartridge","list"]',text);self.assertIn('["help"]',text)
        self.assertIn('Observed argv requests: 3',text);self.assertNotIn('Estimated total commands',text)

    def test_expected_negatives_are_not_failed_tests(self):
        self.write([self.row(1,['unknown'],1,1,'expected-negative'),self.row(2,['help'],1,0,'unexpected-mismatch'),
                    self.row(3,['version'],42,0,'unexpected-error')])
        p=self.cli(self.input);self.ok(p);model,directory=self.model()
        self.assertEqual(model['summary']['expected_failures'],1);self.assertEqual(model['summary']['mismatches'],1)
        self.assertEqual(model['summary']['errors'],1)
        text=(directory/'failure_analysis.txt').read_text();self.assertNotIn('expected-negative',text)
        self.assertIn('unexpected-mismatch',text);self.assertIn('unexpected-error',text)

    def test_empty_results_have_honest_zero_and_unavailable_timing(self):
        self.write([]);p=self.cli(self.input);self.ok(p);model,_=self.model()
        self.assertEqual(model['summary']['total'],0);self.assertEqual(model['summary']['success_percentage'],0)
        self.assertIsNone(model['timing']['average']);self.assertIn('Successful: 0 (0%)',p.stdout)

    def test_invalid_json_shapes_fail_before_statistics_or_output(self):
        for text in ['{broken','[]','{}','{"results":{}}',json.dumps(self.dataset([]))+'\n'+json.dumps(self.dataset([]))]:
            with self.subTest(text=text):
                self.input.write_text(text);p=self.cli(self.input)
                self.assertNotEqual(p.returncode,0);self.assertEqual(p.stdout,'')
                self.assertEqual(self.reports(),[]);self.assertFalse((self.repo/'tests/reports').exists())

    def test_inconsistent_records_and_metadata_are_rejected(self):
        normal=self.dataset([self.row(1,['help'])]);variants=[]
        for field,value in [('argv','not-an-array'),('duration',-1),('classification','error'),('passed',False)]:
            data=copy.deepcopy(normal);data['results'][0][field]=value;variants.append(data)
        data=copy.deepcopy(normal);data['metadata']['case_count']=2;variants.append(data)
        data=copy.deepcopy(normal);data['metadata']['duration_clock']=[];variants.append(data)
        data=copy.deepcopy(normal);data['metadata']['duration_resolution_seconds']=-1;variants.append(data)
        data=copy.deepcopy(normal);data['results'].append(copy.deepcopy(data['results'][0]));data['metadata']['case_count']=2;variants.append(data)
        data=copy.deepcopy(normal);data['results'][0]['argv'][0]='/different/binary';variants.append(data)
        data=copy.deepcopy(normal);data['results'][0]['argv'][1]='invalid\x00argument';variants.append(data)
        for data in variants:
            with self.subTest(data=data):
                self.input.write_text(json.dumps(data));p=self.cli(self.input)
                self.assertNotEqual(p.returncode,0);self.assertEqual(p.stdout,'');self.assertEqual(self.reports(),[])

    def test_missing_jq_is_explicit_and_creates_no_reports(self):
        self.missing('jq');p=self.cli(self.input);self.assertNotEqual(p.returncode,0)
        self.assertIn('requires jq',p.stderr);self.assertEqual(p.stdout,'');self.assertEqual(self.reports(),[])

    def test_failed_partial_first_query_never_becomes_statistics(self):
        self.jq_fault('first');p=self.shell('source tests/test_analyzer.bash\nanalyze_results "$ANALYSIS_INPUT"')
        self.assertNotEqual(p.returncode,0);self.assertEqual(p.stdout,'');self.assertEqual(self.reports(),[])

    def test_empty_successful_query_is_not_accepted_as_analysis(self):
        self.jq_fault('empty');p=self.cli(self.input)
        self.assertNotEqual(p.returncode,0);self.assertEqual(p.stdout,'');self.assertEqual(self.reports(),[])

    def test_failed_report_query_preserves_preexisting_output(self):
        target=self.home/'coverage.txt';target.write_text('prior-report\n');self.jq_fault('second')
        p=self.shell('source tests/test_analyzer.bash\ngenerate_coverage_report "$ANALYSIS_INPUT" "$HOME/coverage.txt"')
        self.assertNotEqual(p.returncode,0);self.assertEqual(target.read_text(),'prior-report\n')

    def test_default_reports_leave_an_owned_git_checkout_clean(self):
        env={**self.env,'GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':os.devnull,
             'GIT_CONFIG_COUNT':'2','GIT_CONFIG_KEY_0':'core.hooksPath','GIT_CONFIG_VALUE_0':str(self.top/'empty-hooks'),
             'GIT_CONFIG_KEY_1':'commit.gpgsign','GIT_CONFIG_VALUE_1':'false'}
        (self.top/'empty-hooks').mkdir()
        for args in [['init','--quiet'],['add','-A'],['-c','user.name=fixture','-c','user.email=fixture@example.invalid','commit','--quiet','-m','owned fixture']]:
            subprocess.run([REAL_GIT,*args],cwd=self.repo,env=env,capture_output=True,text=True,check=True)
        p=self.cli(self.input);self.ok(p)
        status=subprocess.check_output([REAL_GIT,'status','--porcelain=v1'],cwd=self.repo,env=env,text=True)
        self.assertEqual(status,'');self.assertFalse((self.repo/'tests/reports').exists())
        _,directory=self.model()
        self.assertTrue((directory/'coverage_report.txt').is_file());self.assertTrue((directory/'failure_analysis.txt').is_file())

    def test_explicit_output_root_with_spaces_is_honored(self):
        root=self.home/'selected reports';p=self.cli(self.input,'--output-dir',root);self.ok(p)
        model,_=self.model(root);self.assertEqual(model['summary']['total'],3);self.assertEqual(self.reports(),[])

    def test_unknown_or_incomplete_options_do_not_create_output(self):
        for args in [[],[str(self.input),'--output-dir'],['--bogus'],[str(self.input),str(self.input)]]:
            with self.subTest(args=args):
                p=self.cli(*args);self.assertNotEqual(p.returncode,0);self.assertEqual(p.stdout,'')
                self.assertEqual(self.reports(),[])

    def test_help_works_without_jq_or_result_input(self):
        self.missing('jq');p=self.cli('--help');self.ok(p)
        self.assertIn('RESULTS.json',p.stdout);self.assertEqual(self.reports(),[])

    def test_literal_filenames_and_result_text_are_never_executed(self):
        marker=self.home/'unexpected';payload='$(touch '+str(marker)+')'
        self.write([self.row(1,['cartridge','show',payload],1,1,payload)])
        literal=self.repo/'-input file.json';shutil.copyfile(self.input,literal)
        p=self.cli('--',literal.name);self.ok(p);self.assertFalse(marker.exists())
        model,_=self.model();self.assertEqual(model['summary']['expected_failures'],1)

    def test_invalid_output_root_fails_without_a_success_claim(self):
        root=self.home/'not-a-directory';root.write_text('preserve')
        p=self.cli(self.input,'--output-dir',root);self.assertNotEqual(p.returncode,0)
        self.assertNotIn('Reports written:',p.stderr);self.assertEqual(root.read_text(),'preserve')
        move=self.tools/'mv';move.unlink();move.write_text('#!'+self.bash+'\nexit 73\n');move.chmod(0o755)
        p=self.cli(self.input);self.assertNotEqual(p.returncode,0)
        self.assertEqual(p.stdout,'');self.assertIn('Analyzer output failed',p.stderr)
        self.assertNotIn('Reports written:',p.stderr)

    def test_invalid_input_does_not_clobber_an_existing_direct_report(self):
        target=self.home/'coverage.txt';target.write_text('prior-report\n');self.input.write_text('{broken')
        p=self.shell('source tests/test_analyzer.bash\ngenerate_coverage_report "$ANALYSIS_INPUT" "$HOME/coverage.txt"')
        self.assertNotEqual(p.returncode,0);self.assertEqual(target.read_text(),'prior-report\n')

    def test_linked_direct_report_is_not_followed_or_replaced(self):
        original=self.home/'original';original.write_text('preserve\n');(self.home/'coverage.txt').symlink_to(original)
        p=self.shell('source tests/test_analyzer.bash\ngenerate_coverage_report "$ANALYSIS_INPUT" "$HOME/coverage.txt"')
        self.assertNotEqual(p.returncode,0);self.assertEqual(original.read_text(),'preserve\n')
        self.assertTrue((self.home/'coverage.txt').is_symlink())

    def test_import_preserves_shell_options_and_creates_no_files(self):
        before=self.snapshot();p=self.shell('before=$-\nsource tests/test_analyzer.bash\n[[ $- == "$before" ]] || exit 91\ncd "$HOME"\nanalyze_results "$ANALYSIS_INPUT"')
        self.ok(p);self.assertIn('Total tests: 3',p.stdout);self.assertEqual(before,self.snapshot())

    def test_real_rapid_results_are_consumed_with_correct_console_counts(self):
        self.env['BASHCMDR_TEST_RESULTS_DIR']=str(self.top/'rapid-results')
        p=self.shell('"$BASH" tests/factorial_test_runner.bash');self.ok(p)
        result=next((self.top/'rapid-results').glob('factorial.*/rapid_test_results.json'))
        p=self.cli(result);self.ok(p);model,_=self.model()
        oracle=json.loads((self.repo/'tests/rapid-cases.json').read_text())
        expected=sum(c['argv'][0]=='console' for c in oracle['cases'])
        self.assertEqual(model['summary']['total'],35);self.assertEqual(model['summary']['matched'],35)
        self.assertEqual(model['categories']['Console commands']['total'],expected)


if __name__=='__main__':
    if not os.environ.get('ANALYZER_TEST_EVIDENCE_DIR'):
        parent=REPO/'tests/results';parent.mkdir(parents=True,exist_ok=True)
        os.environ['ANALYZER_TEST_EVIDENCE_DIR']=tempfile.mkdtemp(prefix='analyzer.',dir=parent)
    evidence=pathlib.Path(os.environ['ANALYZER_TEST_EVIDENCE_DIR']);evidence.mkdir(parents=True,exist_ok=True)
    (evidence/'runner.json').write_text(json.dumps({'bash':BASH,'repo':str(REPO)},indent=2)+'\n')
    print('Analyzer artifacts: '+str(evidence),flush=True)
    unittest.main(verbosity=2)
