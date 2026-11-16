#!/usr/bin/env python3
"""Observable boot outcomes, counters and channels in owned Bash shells."""
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

REPO = pathlib.Path(os.environ.get('BOOT_STATUS_TEST_REPO', pathlib.Path(__file__).resolve().parent.parent))
PREFIX = r'''
git() { printf 'unexpected-git\n' >> "$TRACE"; return 99; }
curl() { printf 'unexpected-curl\n' >> "$TRACE"; return 99; }
wget() { printf 'unexpected-wget\n' >> "$TRACE"; return 99; }
sudo() { printf 'unexpected-sudo\n' >> "$TRACE"; return 99; }
service() { printf 'unexpected-service\n' >> "$TRACE"; return 99; }
'''
COUNTERS = ['loaded','dormant','succeeded','failed','blocked','quarantined','not_attempted']


class BootStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bcm-boot-status-')
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.home = self.root/'home'
        self.console = self.home/'console'
        for part in ['bin','lib','boot']:
            shutil.copytree(REPO/part,self.console/part)
        shutil.copyfile(REPO/'VERSION',self.console/'VERSION')
        (self.console/'cartridges').mkdir()
        for state in ['active','inactive','broken','quarantine']:
            (self.console/'console'/state).mkdir(parents=True)
        self.trace = self.root/'hooks.log'
        self.trace.write_text('')

    def reset(self):
        for state in ['active','inactive','broken','quarantine']:
            for p in (self.console/'console'/state).iterdir(): p.unlink()
        for p in (self.console/'cartridges').iterdir(): shutil.rmtree(p)
        self.trace.write_text('')

    def cartridge(self,name='demo',*,body='export BASHCMDR_DEMO_LOADED=1',guard='BASHCMDR_DEMO_LOADED',state='active',deps=None,noisy=False):
        cart = self.console/'cartridges'/name
        cart.mkdir()
        manifest = {'name':name,'version':'1.0.0','requires':{'cartridges':dict.fromkeys(deps or [],'>=1.0.0')}}
        if guard is not None: manifest['execution']={'guard_variable':guard}
        (cart/'manifest.json').write_text(json.dumps(manifest))
        (cart/'main.bashcmdr').write_text(('printf "source-stdout\\n"; printf "source-stderr\\n" >&2\n' if noisy else '')+
            'cartridge_dispatch() { [[ $1 == activate ]] || return 0\n'
            'printf "ACT:'+name+'\\n" >> "$TRACE"\n'+body+'\n}\n')
        if state: (self.console/'console'/state/name).symlink_to('../../cartridges/'+name)
        return cart

    def probe(self,body='',*,level='1',quiet=False,bios=True,prelude='',interactive=False):
        env = {'HOME':str(self.home),'CONSOLE':str(self.console),'TRACE':str(self.trace),
               'PATH':'/usr/bin:/bin','TERM':'dumb','LC_ALL':'C','TMPDIR':str(self.root),'PS1':''}
        if level is not None: env['BASHCMDR_VERBOSITY']=level
        if quiet: env['BASHCMDR_QUIET_BOOT']='1'
        entry = 'boot/shell-init.bashcmdr' if bios else 'bin/bashcmdr'
        script = PREFIX+prelude+'\nsource "$CONSOLE/'+entry+'"\nsource_status=$?\n'+body
        argv=['/bin/bash','--noprofile','--norc']+(['-i'] if interactive else [])+['-c',script]
        p = subprocess.run(argv,env=env,cwd=self.root,text=True,capture_output=True,timeout=9)
        self.assertNotIn('unexpected-',self.trace.read_text(),p.stdout+p.stderr)
        return p

    def assert_ok(self,result):
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def counts(self,**expected):
        return '\n'.join('[[ ${BASHCMDR_BOOT_SUMMARY['+field+']-missing} == '+str(expected.get(field,0))+' ]] || exit 81' for field in COUNTERS)+'\n'

    def log(self):
        p=self.console/'logs/console-poweron.log'
        return p.read_text() if p.is_file() else ''

    def test_truthful_outcomes_and_channels_at_every_verbosity(self):
        for scenario in ['empty','loaded','dormant','succeeded','failed','quarantined']:
            for level in range(4):
                with self.subTest(scenario=scenario,level=level):
                    self.reset()
                    if scenario!='empty':
                        self.cartridge(body=':' if scenario=='dormant' else 'return 37' if scenario=='failed' else 'export BASHCMDR_DEMO_LOADED=1',
                            guard=None if scenario=='succeeded' else 'BASHCMDR_DEMO_LOADED',
                            state='quarantine' if scenario=='quarantined' else 'active')
                    expected={} if scenario=='empty' else {scenario:1}
                    body=self.counts(**expected)+'[[ $source_status == 0 && $BASHCMDR_BOOT_BASIC_EXIT_CODE == 0 && $BASHCMDR_BOOT_EXIT_CODE == '+('1' if scenario=='failed' else '0')+' ]]'
                    result=self.probe(body,level=str(level))
                    self.assert_ok(result)
                    self.assertEqual(result.stdout,'')
                    if scenario=='failed' and level:
                        self.assertIn('boot failed:',result.stderr)
                        self.assertIn('failed=1',result.stderr)
                        self.assertIn('Boot details:',result.stderr)
                    else: self.assertEqual(result.stderr,'')

    def test_default_noninteractive_success_has_no_banner(self):
        self.cartridge()
        result=self.probe(self.counts(loaded=1),level=None)
        self.assert_ok(result)
        self.assertEqual(result.stdout,'')
        self.assertEqual(result.stderr,'')

    def test_interactive_success_reports_counts_on_stderr(self):
        self.cartridge()
        result=self.probe(self.counts(loaded=1),interactive=True)
        self.assert_ok(result)
        self.assertEqual(result.stdout,'')
        self.assertIn('boot ok: loaded=1 dormant=0 succeeded=0',result.stderr)

    def test_direct_console_call_reports_a_single_summary(self):
        self.cartridge()
        result=self.probe('console_poweron || exit $?\n'+self.counts(loaded=1),bios=False)
        self.assert_ok(result)
        self.assertEqual(result.stdout,'')
        self.assertEqual(result.stderr.count('boot ok:'),1)

    def test_path_setup_is_not_a_cartridge(self):
        result=self.probe(self.counts()+'[[ ${#BASHCMDR_BOOT_RESULTS[@]} == 0 ]]')
        self.assert_ok(result)
        self.assertIn('loaded=0 dormant=0 succeeded=0 failed=0',self.log())

    def test_guardless_completed_hook_is_not_claimed_loaded(self):
        self.cartridge(guard=None,body=':')
        self.assert_ok(self.probe(self.counts(succeeded=1)+'[[ ${BASHCMDR_BOOT_RESULTS[demo]} == succeeded ]]'))

    def test_generic_guard_names_do_not_collide_with_boot_locals(self):
        for guard in ['guard','cart','hook_status','declaration','attributes','result']:
            with self.subTest(guard=guard):
                self.reset()
                self.cartridge(guard=guard,body='declare -g '+guard+'=1')
                self.assert_ok(self.probe(self.counts(loaded=1)))

    def test_nonexported_and_readonly_loaded_flags_are_observed(self):
        self.cartridge(body=':')
        self.assert_ok(self.probe(self.counts(loaded=1),prelude='readonly BASHCMDR_DEMO_LOADED=1'))

    def test_hook_locale_and_caller_locale_are_preserved(self):
        self.cartridge(body='[[ $LC_ALL == POSIX ]] || return 37\nexport BASHCMDR_DEMO_LOADED=1')
        self.assert_ok(self.probe(self.counts(loaded=1)+'[[ $LC_ALL == POSIX ]]',prelude='export LC_ALL=POSIX'))

    def test_failure_wins_over_a_set_loaded_flag(self):
        self.cartridge(body='export BASHCMDR_DEMO_LOADED=1\nreturn 37')
        self.assert_ok(self.probe(self.counts(failed=1)+'[[ $BASHCMDR_BOOT_EXIT_CODE == 1 ]]'))

    def test_quiet_suppresses_routine_boot_output_without_hiding_status(self):
        for failed in [False,True]:
            with self.subTest(failed=failed):
                self.reset()
                self.cartridge(body='return 37' if failed else 'export BASHCMDR_DEMO_LOADED=1',noisy=True)
                result=self.probe(self.counts(**({'failed':1} if failed else {'loaded':1}))+'[[ $BASHCMDR_BOOT_EXIT_CODE == '+('1' if failed else '0')+' ]]',level='2',quiet=True)
                self.assert_ok(result)
                self.assertEqual(result.stdout,'')
                self.assertEqual(result.stderr,'')
                self.assertIn('source-stdout',self.log())
                self.assertIn('source-stderr',self.log())

    def test_hook_stdout_stderr_and_core_advice_are_logged(self):
        self.cartridge(body='__bashcmdr_info advice\nprintf "hook-data\\n"\nprintf "hook-error\\n" >&2\nexport BASHCMDR_DEMO_LOADED=1',noisy=True)
        result=self.probe(self.counts(loaded=1),level='3')
        self.assert_ok(result)
        self.assertEqual(result.stdout,'')
        self.assertEqual(result.stderr,'')
        for text in ['source-stdout','source-stderr','advice','hook-data','hook-error']:
            self.assertIn(text,self.log())

    def test_invalid_verbosity_is_rejected_once_before_hooks(self):
        self.cartridge()
        for level in ['','abc','4','-1','01','0x2','2 ','$(printf unexpected-verbosity >> "$TRACE")']:
            with self.subTest(level=level):
                result=self.probe('[[ $source_status == 0 && $BASHCMDR_BOOT_EXIT_CODE == 12 && ${BASHCMDR_BOOT_SUMMARY[configuration_failed]} == 1 ]]',level=level)
                self.assert_ok(result)
                self.assertEqual(self.trace.read_text(),'')
                self.assertEqual(result.stdout,'')
                self.assertEqual(result.stderr.count('BASHCMDR_VERBOSITY must be'),1)
                self.assertNotIn('invalid number',result.stderr)

    def test_readonly_invalid_verbosity_is_not_rewritten(self):
        self.cartridge()
        result=self.probe('[[ $BASHCMDR_VERBOSITY == abc && $BASHCMDR_BOOT_EXIT_CODE == 12 ]]',level='abc',prelude='readonly BASHCMDR_VERBOSITY')
        self.assert_ok(result)
        self.assertEqual(self.trace.read_text(),'')

    def test_general_command_loggers_keep_existing_channels(self):
        result=self.probe('__bashcmdr_info info\n__bashcmdr_success success\n__bashcmdr_error error',bios=False,level='2',quiet=True)
        self.assert_ok(result)
        self.assertEqual(result.stdout,'ℹ️  bashcmdr: info\n✓ bashcmdr: success\n')
        self.assertEqual(result.stderr,'⚠️  bashcmdr: error\n')

    def test_planning_failure_has_not_attempted_counts_and_failure_code(self):
        self.cartridge(deps=['absent'])
        self.assert_ok(self.probe(self.counts(not_attempted=1)+'[[ ${BASHCMDR_BOOT_SUMMARY[planning_failed]} == 1 && $BASHCMDR_BOOT_EXIT_CODE == 1 ]]'))
        self.assertEqual(self.trace.read_text(),'')

    def test_failed_dependency_counts_blocked_descendant_and_independent_success(self):
        self.cartridge('a-app',deps=['z-dep'],guard=None,body=':')
        self.cartridge('b-independent',guard=None,body=':')
        self.cartridge('z-dep',body='return 37')
        self.assert_ok(self.probe(self.counts(failed=1,blocked=1,succeeded=1)+'[[ $BASHCMDR_BOOT_EXIT_CODE == 1 && ${BASHCMDR_BOOT_RESULTS[a-app]} == blocked ]]'))
        self.assertNotIn('ACT:a-app',self.trace.read_text())

    def test_dormant_dependency_blocks_a_dependent_without_claiming_hook_failure(self):
        self.cartridge('a-app',deps=['z-dep'],guard=None,body=':')
        self.cartridge('z-dep',body=':')
        self.assert_ok(self.probe(self.counts(dormant=1,blocked=1)+'[[ $BASHCMDR_BOOT_EXIT_CODE == 1 ]]'))
        self.assertNotIn('ACT:a-app',self.trace.read_text())

    def test_guardless_dependency_still_allows_a_dependent(self):
        self.cartridge('a-app',deps=['z-dep'],guard=None,body=':')
        self.cartridge('z-dep',guard=None,body=':')
        self.assert_ok(self.probe(self.counts(succeeded=2)+'[[ $BASHCMDR_BOOT_EXIT_CODE == 0 ]]'))

    def test_quarantine_overlap_is_counted_once(self):
        self.cartridge(state='quarantine')
        (self.console/'console/active/demo').symlink_to('../../cartridges/demo')
        self.assert_ok(self.probe(self.counts(quarantined=1)+'[[ ${#BASHCMDR_BOOT_RESULTS[@]} == 1 ]]'))
        self.assertEqual(self.trace.read_text(),'')

    def test_invalid_guard_names_are_data_not_variable_expressions(self):
        cart=self.cartridge()
        for guard in ['x[$(printf unexpected-guard >> "$TRACE")]','bad-name','a\nb','__BASHCMDR_BOOT_CONTEXT',False,[]]:
            with self.subTest(guard=guard):
                data=json.loads((cart/'manifest.json').read_text());data['execution']['guard_variable']=guard
                (cart/'manifest.json').write_text(json.dumps(data))
                self.assert_ok(self.probe(self.counts(not_attempted=1)+'[[ $BASHCMDR_BOOT_EXIT_CODE == 1 ]]'))
                self.assertEqual(self.trace.read_text(),'')

    def test_array_or_nameref_guard_is_rejected_before_hooks(self):
        self.cartridge()
        for prelude in ['declare -a BASHCMDR_DEMO_LOADED=(1)','declare -A BASHCMDR_DEMO_LOADED=([x]=1)','declare -n BASHCMDR_DEMO_LOADED=HOME']:
            with self.subTest(prelude=prelude):
                self.assert_ok(self.probe(self.counts(not_attempted=1)+'[[ $BASHCMDR_BOOT_EXIT_CODE == 1 ]]',prelude=prelude))
                self.assertEqual(self.trace.read_text(),'')

    def test_guard_type_changed_by_hook_is_an_observable_failure(self):
        self.cartridge(body='declare -gA BASHCMDR_DEMO_LOADED=([x]=1)')
        self.assert_ok(self.probe(self.counts(failed=1)+'[[ $BASHCMDR_BOOT_EXIT_CODE == 1 ]]'))
        self.assertIn('Loaded guard must be a scalar',self.log())

    def test_repeated_console_calls_reset_results_and_keep_current_guards(self):
        self.cartridge()
        body='console_poweron || exit $?\n'+self.counts(loaded=1)+'console_poweron || exit $?\n'+self.counts(loaded=1)
        self.assert_ok(self.probe(body,bios=False,quiet=True))
        self.assertEqual(self.trace.read_text().splitlines(),['ACT:demo','ACT:demo'])

    def test_bios_failure_remains_nonfatal_under_errexit_and_nounset(self):
        self.cartridge(body='return 37')
        self.assert_ok(self.probe('[[ $source_status == 0 && $BASHCMDR_BOOT_EXIT_CODE == 1 ]]',prelude='set -euo pipefail'))

    def test_readonly_path_is_rejected_without_hook_effects(self):
        self.cartridge()
        self.assert_ok(self.probe(self.counts(not_attempted=1)+'[[ $BASHCMDR_BOOT_EXIT_CODE == 1 && ${BASHCMDR_BOOT_SUMMARY[setup_failed]} == 1 ]]',prelude='readonly PATH'))
        self.assertEqual(self.trace.read_text(),'')

    def test_failed_path_helper_is_not_reported_as_cartridge_success(self):
        self.cartridge()
        body='addpath() { return 37; }\nuniqpath() { :; }\nconsole_poweron\nstatus=$?\n'+self.counts(not_attempted=1)+'[[ $status == 1 && ${BASHCMDR_BOOT_SUMMARY[setup_failed]} == 1 ]]'
        self.assert_ok(self.probe(body,bios=False))
        self.assertEqual(self.trace.read_text(),'')

    def test_log_directory_and_log_file_failures_are_observable(self):
        self.cartridge()
        (self.console/'logs').write_text('foreign file')
        self.assert_ok(self.probe('[[ $BASHCMDR_BOOT_EXIT_CODE == 1 && ${BASHCMDR_BOOT_SUMMARY[log_failed]} == 1 ]]'))
        self.assertEqual((self.console/'logs').read_text(),'foreign file')
        (self.console/'logs').unlink()
        (self.console/'logs/console-poweron.log').mkdir(parents=True)
        self.assert_ok(self.probe('[[ $BASHCMDR_BOOT_EXIT_CODE == 1 && ${BASHCMDR_BOOT_SUMMARY[log_failed]} == 1 ]]'))
        self.assertEqual(self.trace.read_text(),'')

    def test_log_failure_after_success_does_not_leave_a_success_status(self):
        self.cartridge(body='export BASHCMDR_DEMO_LOADED=1\nrm "$CONSOLE/logs/console-poweron.log"\nmkdir "$CONSOLE/logs/console-poweron.log"')
        self.assert_ok(self.probe(self.counts(loaded=1)+'[[ $BASHCMDR_BOOT_EXIT_CODE == 1 && ${BASHCMDR_BOOT_SUMMARY[log_failed]} == 1 && ${BASHCMDR_BOOT_SUMMARY[status]} == failed ]]'))

    def test_locked_private_result_maps_cannot_claim_success(self):
        self.cartridge()
        self.assert_ok(self.probe('[[ $BASHCMDR_BOOT_EXIT_CODE == 1 ]]',prelude='declare -grA BASHCMDR_BOOT_RESULTS=([old]=old)'))
        self.assertEqual(self.trace.read_text(),'')


if __name__=='__main__':
    unittest.main(verbosity=2)
