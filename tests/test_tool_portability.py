#!/usr/bin/env python3
"""Tool capabilities and honest report metrics in owned code/tool installations."""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

import test_runtime_preflight as runtime

REPO=pathlib.Path(os.environ.get('TOOL_TEST_REPO',pathlib.Path(__file__).resolve().parent.parent))
BASH=os.environ.get('TOOL_TEST_BASH') or shutil.which('bash')
runtime.REPO=REPO;runtime.BASH=BASH


class ToolPortabilityTests(runtime.RuntimeFixture):
    def setUp(self):
        super().setUp()
        shutil.copytree(REPO/'tests',self.repo/'tests',ignore=shutil.ignore_patterns('results','reports','__pycache__'))
        # A real copy keeps the harness's known-Bash prefix inside the owned tool
        # directory, so /usr/bin cannot bypass the tool-contract fixtures.
        (self.tools/'bash').unlink();shutil.copyfile(BASH,self.tools/'bash');(self.tools/'bash').chmod(0o755)
        self.bash=str(self.tools/'bash')
        for name in ['cp','ls','uniq','sleep','touch','chmod','awk','tr','id']:
            path=shutil.which(name)
            if path and not (self.tools/name).exists():(self.tools/name).symlink_to(path)
        self.tooltrace=self.top/'tool-calls.jsonl';self.tooltrace.write_text('')
        self.results=self.top/'suite-results';self.env['BASHCMDR_TEST_RESULTS_DIR']=str(self.results)
        self.index=self.home/'index.json';self.index.write_text('{"version":"fixture","cartridges":{}}\n')
        self.env['BASHCMDR_REGISTRY_INDEX']=str(self.index)
        self.old_epoch=int(time.time())-12*86400
        os.utime(self.index,(self.old_epoch,self.old_epoch))
        self.wrap('date');self.wrap('stat');self.wrap('bc','missing')

    def wrap(self,name,mode='real',value=None):
        real=shutil.which(name)
        code='''import json, subprocess, sys
args=sys.argv[1:]
with open(TRACE,'a') as f:f.write(json.dumps({'tool':NAME,'mode':MODE,'argv':args})+'\\n')
if MODE=='missing':sys.exit(127)
if NAME=='date':
    if MODE=='posix' and any(x.startswith('-I') or '%N' in x for x in args):sys.exit(64)
    if MODE=='bad-utc' and any('%Y-%m-%dT%H:%M:%SZ' in x for x in args):print('not-a-date');sys.exit(0)
    if args==['+%s'] and MODE in ['literal','partial']:
        print(VALUE);sys.exit(37 if MODE=='partial' else 0)
if NAME=='stat':
    if MODE=='bsd':
        if args[:2]==['-f','%m']:print(VALUE);sys.exit(0)
        sys.exit(64)
    if MODE=='partial-gnu':
        if args[:2]==['-c','%Y']:print(0);sys.exit(37)
        if args[:2]==['-f','%m']:print(VALUE);sys.exit(0)
    if MODE in ['literal','partial']:
        print(VALUE);sys.exit(37 if MODE=='partial' else 0)
sys.exit(subprocess.run([REAL,*args]).returncode)
'''
        constants='NAME='+repr(name)+'\nMODE='+repr(mode)+'\nVALUE='+repr(value)+'\nREAL='+repr(real)+'\nTRACE='+repr(str(self.tooltrace))+'\n'
        path=self.tools/name
        if path.is_symlink():path.unlink()
        path.write_text('#!'+sys.executable+'\n'+constants+code);path.chmod(0o755)

    def shell(self,body):
        p=subprocess.run([self.bash,'--noprofile','--norc','-c',body],cwd=self.repo,env=self.env,
                         text=True,capture_output=True,timeout=30)
        self.calls.append({'body':body,'exit':p.returncode,'stdout':p.stdout,'stderr':p.stderr})
        return p

    def tearDown(self):
        destination=pathlib.Path(os.environ['TOOL_TEST_EVIDENCE_DIR'])/self.id().split('.')[-1]
        destination.mkdir(parents=True,exist_ok=True)
        (destination/'calls.json').write_text(json.dumps(self.calls,indent=2)+'\n')
        shutil.copyfile(self.tooltrace,destination/'tool-calls.jsonl');shutil.copyfile(self.trace,destination/'operations.log')
        if self.results.exists():shutil.copytree(self.results,destination/'suite-results',dirs_exist_ok=True)
        for filename in ['coverage.txt','analysis.json']:
            if (self.home/filename).exists():shutil.copyfile(self.home/filename,destination/filename)

    def tools_called(self):
        return [json.loads(line) for line in self.tooltrace.read_text().splitlines()]

    def no_bc_or_effects(self):
        self.assertFalse(any(c['tool']=='bc' for c in self.tools_called()))
        self.assertEqual(self.trace.read_text(),'')

    def status(self):
        return self.shell('source bin/bashcmdr\nset -euo pipefail\nregistry_status_cmd')

    def unavailable(self,result):
        self.ok(result);self.assertIn('Index version:',result.stdout);self.assertIn('Index age: unavailable',result.stdout)
        self.assertNotIn('Index is ',result.stdout)
        for message in ['unbound variable','syntax error','value too great for base','operand expected']:
            self.assertNotIn(message,result.stdout+result.stderr)

    def runner(self):
        p=self.shell('"$BASH" --noprofile --norc tests/factorial_test_runner.bash')
        files=list(self.results.glob('factorial.*/rapid_test_results.json')) if self.results.exists() else []
        return p,json.loads(files[-1].read_text()) if files else None

    def valid_report(self,p,data):
        self.ok(p);self.assertIsNotNone(data)
        self.assertEqual(len(data['results']),35)
        self.assertRegex(data['metadata']['generated_at'],r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')
        self.assertEqual(data['metadata'].get('duration_clock'),'bash_SECONDS')
        self.assertEqual(data['metadata'].get('duration_resolution_seconds'),1)
        for row in data['results']:
            self.assertIs(type(row['duration']),int);self.assertGreaterEqual(row['duration'],0)
            self.assertTrue(row['passed']);self.assertEqual(row['exit_code'],row['expected_exit'])

    def analysis_input(self,rows):
        executable=str(self.repo/'bin/bashcmdr');records=[]
        for index,row in enumerate(rows,1):
            classification=row.get('classification','success')
            expected=1 if classification=='expected_failure' else 0
            status=42 if classification=='error' else expected
            records.append({'test_id':index,'argv':[executable,*row['command'].split()[1:]],
                'command':row['command'],'classification':classification,'exit_code':status,
                'expected_exit':expected,'passed':status==expected,'duration':1,'output':''})
        data={'metadata':{'schema':'bashcmdr.rapid-results.v1','executable':executable,
            'generated_at':'2026-10-28T12:00:00Z','case_count':len(records)},'results':records}
        path=self.home/'analysis.json';path.write_text(json.dumps(data));self.env['ANALYSIS_INPUT']=str(path)

    def test_missing_registry_guidance_uses_available_install_path(self):
        self.index.unlink()
        before = self.snapshot()
        result = self.status()
        self.ok(result)
        self.assertIn('No registry index found', result.stdout)
        self.assertIn('Registry synchronization is not implemented', result.stdout)
        self.assertIn('cartridge install <name> --from <trusted-git-source>', result.stdout)
        self.assertNotIn("Run 'bcm registry sync'", result.stdout)
        self.assertFalse(self.index.exists())
        self.assertEqual(before, self.snapshot())
        self.no_bc_or_effects()

    def test_stale_registry_guidance_uses_available_install_path(self):
        original = self.index.read_bytes()
        for mode in ['real', 'bsd']:
            with self.subTest(stat_mode=mode):
                self.wrap('stat', mode, self.old_epoch)
                before = self.snapshot()
                result = self.status()
                self.ok(result)
                self.assertIn('Index is 12 days old', result.stdout)
                self.assertIn('Registry synchronization is not implemented', result.stdout)
                self.assertIn('cartridge install <name> --from <trusted-git-source>', result.stdout)
                self.assertNotIn('Consider running: bcm registry sync', result.stdout)
                self.assertEqual(self.index.read_bytes(), original)
                self.assertEqual(before, self.snapshot())
                self.no_bc_or_effects()

    def test_gnu_stat_reports_stale_age_without_writes(self):
        before=self.snapshot();p=self.status();self.ok(p)
        self.assertIn('Index is 12 days old',p.stdout);self.assertEqual(before,self.snapshot())

    def test_bsd_stat_fallback_reports_same_stale_age(self):
        self.wrap('stat','bsd',self.old_epoch);p=self.status();self.ok(p)
        self.assertIn('Index is 12 days old',p.stdout)
        self.assertEqual([c['argv'][:2] for c in self.tools_called() if c['tool']=='stat'],[['-c','%Y'],['-f','%m']])

    def test_failed_gnu_producer_cannot_supply_the_epoch(self):
        self.wrap('stat','partial-gnu',int(time.time())-86400);p=self.status();self.ok(p)
        self.assertNotIn('Index is ',p.stdout);self.assertNotIn('unavailable',p.stdout)

    def test_invalid_mtime_text_never_reaches_arithmetic(self):
        for value in ['not-an-epoch','1+2','01','-1','999999999999999999999','1\n2']:
            with self.subTest(value=value):
                self.wrap('stat','literal',value);self.unavailable(self.status())

    def test_failed_or_missing_stat_keeps_other_status_useful(self):
        self.wrap('stat','partial',self.old_epoch);self.unavailable(self.status())
        self.missing('stat');self.unavailable(self.status())

    def test_invalid_or_failed_current_epoch_is_explicitly_unavailable(self):
        for mode,value in [('literal','bad-epoch'),('literal','01'),('partial',int(time.time()))]:
            with self.subTest(mode=mode,value=value):
                self.wrap('date',mode,value);self.unavailable(self.status())

    def test_future_mtime_is_not_reported_as_negative_or_fresh_age(self):
        self.wrap('stat','literal',int(time.time())+86400);p=self.status();self.unavailable(p)
        self.assertIn('mtime is in the future',p.stdout)

    def test_missing_date_keeps_basic_registry_status_useful(self):
        self.missing('date');self.unavailable(self.status())

    def test_recent_index_does_not_emit_a_stale_warning(self):
        epoch=int(time.time())-86400;os.utime(self.index,(epoch,epoch));p=self.status();self.ok(p)
        self.assertNotIn('Index is ',p.stdout);self.assertNotIn('unavailable',p.stdout)

    def test_inherited_bios_error_needs_no_date_and_retains_outcome(self):
        (self.repo/'bin/bashcmdr').chmod(0o644);self.missing('date');before=self.snapshot()
        p=self.shell('source boot/shell-init.bashcmdr; printf "BASIC=%s BOOT=%s\\n" "$BASHCMDR_BOOT_BASIC_EXIT_CODE" "$BASHCMDR_BOOT_EXIT_CODE"')
        self.ok(p);self.assertIn('BASIC=10 BOOT=10',p.stdout);self.assertIn('Console executable not found',p.stderr)
        self.assertEqual(before,self.snapshot());self.no_bc_or_effects()

    def test_runner_uses_posix_timestamp_and_bash_seconds_without_bc(self):
        self.wrap('date','posix');p,data=self.runner();self.valid_report(p,data)
        self.assertFalse(any(any('%N' in arg or arg.startswith('-I') for arg in c['argv']) for c in self.tools_called() if c['tool']=='date'))
        self.no_bc_or_effects()

    def test_runner_missing_date_fails_explicitly_before_case_execution(self):
        self.missing('date');p,data=self.runner();self.assertNotEqual(p.returncode,0)
        self.assertIn('Cannot produce UTC report timestamp',p.stdout+p.stderr);self.assertIsNone(data);self.no_bc_or_effects()

    def test_runner_bad_timestamp_is_not_published_as_valid_metadata(self):
        self.wrap('date','bad-utc');p,data=self.runner();self.assertNotEqual(p.returncode,0)
        self.assertIn('Cannot produce UTC report timestamp',p.stdout+p.stderr);self.assertIsNone(data)

    def test_slow_command_has_nonzero_duration_without_bc(self):
        path=self.repo/'bin/bashcmdr';text=path.read_text();self.assertEqual(text.count('version_cmd() {'),1)
        path.write_text(text.replace('version_cmd() {','version_cmd() {\n    sleep 2',1))
        p,data=self.runner();self.valid_report(p,data)
        durations=[row['duration'] for row in data['results'] if row['argv'][1:]==['version']]
        self.assertEqual(len(durations),1);self.assertGreaterEqual(durations[0],1);self.no_bc_or_effects()

    def test_analyzer_percentages_use_jq_without_bc(self):
        self.analysis_input([{'command':'bcm help','classification':'success'},
                             {'command':'bcm unknown','classification':'expected_failure'},
                             {'command':'bcm error','classification':'error'}])
        p=self.shell('source tests/test_analyzer.bash\nanalyze_results "$ANALYSIS_INPUT"');self.ok(p)
        self.assertIn('Successful: 1 (33.3%)',p.stdout);self.assertIn('Expected failures: 1 (33.3%)',p.stdout)
        self.assertIn('Errors: 1 (33.3%)',p.stdout);self.no_bc_or_effects()

    def test_empty_analyzer_results_have_zero_percentages(self):
        self.analysis_input([]);p=self.shell('source tests/test_analyzer.bash\nanalyze_results "$ANALYSIS_INPUT"');self.ok(p)
        self.assertIn('Successful: 0 (0%)',p.stdout);self.assertIn('Errors: 0 (0%)',p.stdout);self.no_bc_or_effects()

    def test_coverage_percentage_needs_no_bc(self):
        self.analysis_input([{'command':'bcm help'},{'command':'bcm version'},{'command':'bcm doctor'}])
        p=self.shell('source tests/test_analyzer.bash\ngenerate_coverage_report "$ANALYSIS_INPUT" "$HOME/coverage.txt" || exit $?\n__bcm_analyzer_percentage 3 80');self.ok(p)
        self.assertEqual(p.stdout,'3.7\n')
        self.assertIn('Observed argv requests: 3',(self.home/'coverage.txt').read_text());self.no_bc_or_effects()

    def test_percentage_helper_has_explicit_missing_jq_failure(self):
        self.missing('jq');p=self.shell('source tests/test_analyzer.bash\n__bcm_analyzer_percentage 1 2')
        self.assertNotEqual(p.returncode,0);self.assertIn('Analyzer percentages require jq',p.stderr)

    def test_percentage_helper_rejects_invalid_counts_as_data(self):
        for numerator,denominator in [('bad','2'),('-1','2'),('1','-1')]:
            with self.subTest(numerator=numerator,denominator=denominator):
                self.env.update(NUMERATOR=numerator,DENOMINATOR=denominator)
                p=self.shell('source tests/test_analyzer.bash\n__bcm_analyzer_percentage "$NUMERATOR" "$DENOMINATOR"')
                self.assertNotEqual(p.returncode,0);self.assertEqual(p.stdout,'');self.no_bc_or_effects()

    def test_inherited_generator_needs_neither_date_nor_bc(self):
        self.missing('date');p=self.shell('"$BASH" tests/command_matrix_generator.bash --output -');self.ok(p)
        data=json.loads(p.stdout);self.assertEqual(len(data['test_matrix']),296)
        self.assertEqual(data['metadata']['execution'],'not_executed');self.no_bc_or_effects()


if __name__=='__main__':
    if not os.environ.get('TOOL_TEST_EVIDENCE_DIR'):
        parent=REPO/'tests/results';parent.mkdir(parents=True,exist_ok=True)
        os.environ['TOOL_TEST_EVIDENCE_DIR']=tempfile.mkdtemp(prefix='tool-portability.',dir=parent)
    evidence=pathlib.Path(os.environ['TOOL_TEST_EVIDENCE_DIR']);evidence.mkdir(parents=True,exist_ok=True)
    (evidence/'runner.json').write_text(json.dumps({'bash':BASH,'repo':str(REPO),'native_platform_certified':False},indent=2)+'\n')
    print('Tool portability artifacts: '+str(evidence),flush=True)
    unittest.main(verbosity=2)
