#!/usr/bin/env python3
"""Reset hook context while retaining owned persistent activation choices."""
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

REPO=pathlib.Path(os.environ.get('RESET_TEST_REPO',pathlib.Path(__file__).resolve().parent.parent))
PREFIX=r'''
git() { printf 'unexpected-git\n' >> "$TRACE"; return 99; }
curl() { printf 'unexpected-curl\n' >> "$TRACE"; return 99; }
wget() { printf 'unexpected-wget\n' >> "$TRACE"; return 99; }
sudo() { printf 'unexpected-sudo\n' >> "$TRACE"; return 99; }
service() { printf 'unexpected-service\n' >> "$TRACE"; return 99; }
sleep() { printf 'sleep:%s\n' "$1" >> "$TRACE"; }
source "$CONSOLE/bin/bashcmdr"
'''


class ResetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='bcm-reset-')
        self.addCleanup(self.temp.cleanup)
        self.root=pathlib.Path(self.temp.name)
        self.home=self.root/'home'
        self.console=self.home/'console'
        for part in ['bin','lib','boot']:shutil.copytree(REPO/part,self.console/part)
        shutil.copyfile(REPO/'VERSION',self.console/'VERSION')
        (self.console/'cartridges').mkdir()
        for state in ['active','inactive','broken','quarantine']:(self.console/'console'/state).mkdir(parents=True)
        self.trace=self.root/'hooks.log';self.trace.write_text('')

    def cartridge(self,name='demo',deps=None,state='active',activate=':',deactivate=':',guard=None):
        cart=self.console/'cartridges'/name;cart.mkdir()
        data={'name':name,'version':'1.0.0','requires':{'cartridges':dict.fromkeys(deps or [],'>=1.0.0')}}
        if guard is not None:data['execution']={'guard_variable':guard}
        (cart/'manifest.json').write_text(json.dumps(data))
        (cart/'main.bashcmdr').write_text('cartridge_dispatch() {\ncase "$1" in\n'
            'activate) printf "'+name+':activate\\n" >> "$TRACE"\n'+activate+';;\n'
            'deactivate) printf "'+name+':deactivate\\n" >> "$TRACE"\n'+deactivate+';;\nesac\n}\n')
        if state:(self.console/'console'/state/name).symlink_to('../../cartridges/'+name)
        return cart

    def states(self):
        return {state:{p.name:('symlink',os.readlink(p)) if p.is_symlink() else ('file',p.read_bytes())
                       for p in (self.console/'console'/state).iterdir()}
                for state in ['active','inactive','broken','quarantine']}

    def probe(self,body='main console reset',*,bios=False):
        prefix=PREFIX.replace('source "$CONSOLE/bin/bashcmdr"','source "$CONSOLE/boot/shell-init.bashcmdr"') if bios else PREFIX
        p=subprocess.run(['/bin/bash','--noprofile','--norc','-c',prefix+body],cwd=self.root,
            env={'HOME':str(self.home),'CONSOLE':str(self.console),'TRACE':str(self.trace),
                 'PATH':'/usr/bin:/bin','LC_ALL':'C','TERM':'dumb','TMPDIR':str(self.root),'BASHCMDR_QUIET_BOOT':'1'},
            text=True,capture_output=True,timeout=8)
        self.assertNotIn('unexpected-',self.trace.read_text(),p.stdout+p.stderr)
        return p

    def assert_ok(self,result):self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def assert_rejected(self,body='console_reset'):
        before=self.states()
        self.trace.write_text('')
        try:
            p=self.probe(body)
            self.assertEqual(p.returncode,1,p.stdout+p.stderr)
            self.assertEqual(self.trace.read_text(),'')
            self.assertEqual(self.states(),before)
            return p
        finally:
            # Failed archived-baseline assertions must not contaminate the next
            # subtest. Restore only the owned fixture's recorded marker entries.
            for state,entries in before.items():
                directory=self.console/'console'/state
                for p in directory.iterdir():p.unlink()
                for name,(kind,value) in entries.items():
                    p=directory/name
                    if kind=='symlink':p.symlink_to(value)
                    else:p.write_bytes(value)

    def test_generic_and_essential_active_choices_survive_actual_main_reset(self):
        for name in ['demo','pyenv-loader','nvm-loader','fabric-loader']:self.cartridge(name)
        before=self.states()
        self.assert_ok(self.probe())
        self.assertEqual(self.states(),before)
        events=self.trace.read_text().splitlines()
        for name in ['demo','pyenv-loader','nvm-loader','fabric-loader']:
            self.assertEqual(events.count(name+':deactivate'),1)
            self.assertEqual(events.count(name+':activate'),1)

    def test_dependency_order_reverses_for_deactivation_and_restores_forward(self):
        self.cartridge('a-app',['b-middle'],activate='[[ ${BASE_READY-} == 1 && ${MIDDLE_READY-} == 1 ]]')
        self.cartridge('b-middle',['z-base'],activate='[[ ${BASE_READY-} == 1 ]] || return 37\nexport MIDDLE_READY=1',deactivate='unset MIDDLE_READY')
        self.cartridge('z-base',activate='export BASE_READY=1',deactivate='unset BASE_READY')
        before=self.states()
        self.assert_ok(self.probe())
        self.assertEqual(self.states(),before)
        self.assertEqual(self.trace.read_text().splitlines(),['a-app:deactivate','b-middle:deactivate','z-base:deactivate','z-base:activate','b-middle:activate','a-app:activate'])

    def test_shared_dependency_runs_once_per_phase(self):
        self.cartridge('a-app',['z-base'])
        self.cartridge('b-app',['z-base'])
        self.cartridge('z-base')
        before=self.states()
        self.assert_ok(self.probe())
        self.assertEqual(self.states(),before)
        events=self.trace.read_text().splitlines()
        for name in ['a-app','b-app','z-base']:
            for action in ['activate','deactivate']:self.assertEqual(events.count(name+':'+action),1)
        self.assertGreater(events.index('z-base:deactivate'),events.index('a-app:deactivate'))
        self.assertLess(events.index('z-base:activate'),events.index('a-app:activate'))

    def test_quarantine_and_inactive_broken_untracked_choices_remain_untouched(self):
        for name,state in [('active','active'),('q','quarantine'),('off','inactive'),('broken','broken'),('untracked',None)]:
            self.cartridge(name,state=state)
        before=self.states()
        self.assert_ok(self.probe('console_reset'))
        self.assertEqual(self.states(),before)
        self.assertEqual(self.trace.read_text().splitlines(),['active:deactivate','active:activate'])

    def test_quarantine_overlap_wins_without_rewriting_raw_links(self):
        self.cartridge('q',state='quarantine')
        (self.console/'console/active/q').symlink_to('../../cartridges/q')
        self.cartridge('demo')
        before=self.states()
        self.assert_ok(self.probe('console_reset'))
        self.assertEqual(self.states(),before)
        self.assertEqual(self.trace.read_text().splitlines(),['demo:deactivate','demo:activate'])

    def test_existing_absolute_active_target_is_preserved_byte_for_byte(self):
        self.cartridge()
        link=self.console/'console/active/demo';link.unlink();link.symlink_to(self.console/'cartridges/demo')
        before=self.states()
        self.assert_ok(self.probe())
        self.assertEqual(self.states(),before)

    def test_direct_reset_ignores_stale_or_missing_runtime_state_cache(self):
        self.cartridge()
        self.cartridge('inactive',state='inactive')
        before=self.states()
        self.assert_ok(self.probe('declare -gA BASHCMDR_CARTRIDGES_STATE=([inactive]=active [demo]=inactive)\nconsole_reset || exit $?\nunset BASHCMDR_CARTRIDGES_STATE\nconsole_reset'))
        self.assertEqual(self.states(),before)
        self.assertEqual(self.trace.read_text().splitlines(),['demo:deactivate','demo:activate']*2)

    def test_direct_reset_after_bios_preserves_canonical_runtime_binding(self):
        self.cartridge()
        self.assert_ok(self.probe('[[ $BASHCMDR_ROOT == "$CONSOLE" ]] || exit 1\nconsole_reset || exit $?\n[[ $BASHCMDR_ROOT == "$CONSOLE" ]]',bios=True))
        self.assertEqual(self.trace.read_text().splitlines(),['demo:activate','demo:deactivate','demo:activate'])

    def test_missing_dependency_rejects_before_deactivation(self):
        self.cartridge(deps=['absent'])
        self.assert_rejected()

    def test_inactive_or_quarantined_dependency_rejects_before_deactivation(self):
        for state in ['inactive','quarantine']:
            with self.subTest(state=state):
                self.cartridge('app-'+state,deps=['dep-'+state])
                self.cartridge('dep-'+state,state=state)
                try:self.assert_rejected()
                finally:
                    for name in ['app-'+state,'dep-'+state]:
                        for directory in ['active','inactive','broken','quarantine']:(self.console/'console'/directory/name).unlink(missing_ok=True)
                        shutil.rmtree(self.console/'cartridges'/name)
                    self.trace.write_text('')

    def test_cycle_rejects_before_even_an_independent_hook(self):
        self.cartridge('a',['b']);self.cartridge('b',['a']);self.cartridge('independent')
        self.assert_rejected()

    def test_invalid_guard_metadata_rejects_before_deactivation(self):
        cart=self.cartridge(guard='BASHCMDR_DEMO_LOADED')
        for guard in ['bad-name','x[$(printf unexpected-guard >> "$TRACE")]',False]:
            with self.subTest(guard=guard):
                data=json.loads((cart/'manifest.json').read_text());data['execution']['guard_variable']=guard
                (cart/'manifest.json').write_text(json.dumps(data))
                self.assert_rejected()

    def test_malformed_manifest_or_missing_main_rejects_before_deactivation(self):
        cart=self.cartridge()
        (cart/'manifest.json').write_text('{broken')
        self.assert_rejected()
        (cart/'manifest.json').write_text('{"version":"1.0.0"}')
        (cart/'main.bashcmdr').unlink()
        self.assert_rejected()

    def test_failed_plan_producer_output_never_reaches_hooks(self):
        self.cartridge()
        self.assert_rejected('__bashcmdr_get_boot_plan() { printf "demo:\\n"; return 37; }\nconsole_reset')

    def test_invalid_empty_duplicate_partial_or_unordered_plan_is_rejected(self):
        self.cartridge('a');self.cartridge('b')
        for plan in ['', 'a:\n','a:\na:\n','a:\nforeign:\n','a:b\nb:\n','a:../bad\nb:\n','badrow\nb:\n']:
            with self.subTest(plan=plan):
                quoted="'"+plan.replace("'","'\\''")+"'"
                self.assert_rejected('__bashcmdr_get_boot_plan() { printf %s '+quoted+'; }\nconsole_reset')

    def test_foreign_and_ambiguous_active_links_are_not_deactivated(self):
        self.cartridge()
        (self.console/'console/inactive/demo').symlink_to('../../cartridges/demo')
        self.assert_rejected()
        (self.console/'console/inactive/demo').unlink()
        (self.console/'console/active/demo').unlink()
        (self.console/'console/active/demo').symlink_to(self.home)
        self.assert_rejected()

    def test_failed_deactivation_stops_before_dependencies_and_keeps_choices(self):
        self.cartridge('a-app',['z-base'],deactivate='return 37')
        self.cartridge('z-base')
        before=self.states();p=self.probe()
        self.assertEqual(p.returncode,1,p.stdout+p.stderr)
        self.assertEqual(self.states(),before)
        self.assertEqual(self.trace.read_text().splitlines(),['a-app:deactivate'])
        self.assertIn('Reset deactivation failed',p.stderr)

    def test_later_failure_retains_choices_and_reports_partial_hook_context(self):
        self.cartridge('a-app',['z-base'])
        self.cartridge('z-base',deactivate='return 37')
        before=self.states();p=self.probe()
        self.assertEqual(p.returncode,1,p.stdout+p.stderr)
        self.assertEqual(self.states(),before)
        self.assertEqual(self.trace.read_text().splitlines(),['a-app:deactivate','z-base:deactivate'])
        self.assertIn('hook context may be partial',p.stderr)

    def test_failed_source_is_not_hidden_or_followed_by_reactivation(self):
        cart=self.cartridge()
        (cart/'main.bashcmdr').write_text('printf "demo:source-failed\\n" >> "$TRACE"\nreturn 37\n')
        before=self.states();p=self.probe()
        self.assertEqual(p.returncode,1,p.stdout+p.stderr)
        self.assertEqual(self.states(),before)
        self.assertEqual(self.trace.read_text(),'demo:source-failed\n')

    def test_failed_reactivation_is_propagated_without_changing_active_choices(self):
        self.cartridge(activate='return 37')
        before=self.states();p=self.probe()
        self.assertEqual(p.returncode,1,p.stdout+p.stderr)
        self.assertEqual(self.states(),before)
        self.assertEqual(self.trace.read_text().splitlines(),['demo:deactivate','demo:activate'])

    def test_new_quarantine_from_hook_is_preserved_and_prevents_restart(self):
        self.cartridge('a-app',['z-base'],deactivate='__bashcmdr_set_cartridge_state z-base quarantine')
        self.cartridge('z-base')
        p=self.probe();self.assertEqual(p.returncode,1,p.stdout+p.stderr)
        self.assertTrue((self.console/'console/quarantine/z-base').is_symlink())
        self.assertEqual(self.trace.read_text().splitlines(),['a-app:deactivate'])
        self.assertIn('Active choices changed',p.stderr)

    def test_new_active_choice_from_hook_is_preserved_but_not_restarted(self):
        self.cartridge('demo',deactivate='__bashcmdr_set_cartridge_state extra active')
        self.cartridge('extra',state='inactive')
        p=self.probe();self.assertEqual(p.returncode,1,p.stdout+p.stderr)
        self.assertTrue((self.console/'console/active/extra').is_symlink())
        self.assertEqual(self.trace.read_text().splitlines(),['demo:deactivate'])

    def test_invalid_verbosity_rejects_before_deactivation(self):
        self.cartridge();before=self.states()
        p=self.probe('BASHCMDR_VERBOSITY=abc\nconsole_reset')
        self.assertEqual(p.returncode,12,p.stdout+p.stderr)
        self.assertEqual(self.trace.read_text(),'')
        self.assertEqual(self.states(),before)

    def test_empty_reset_does_not_require_jq_or_sleep(self):
        self.assert_ok(self.probe('jq() { printf "unexpected-jq\\n" >> "$TRACE"; return 37; }\nconsole_reset'))
        self.assertEqual(self.trace.read_text(),'')

    def test_strict_shell_and_dispatcher_binding_survive_reset(self):
        self.cartridge()
        self.assert_ok(self.probe('set -euo pipefail\nbefore=$(declare -pf cartridge_dispatch)\nconsole_reset || exit $?\n[[ $(declare -pf cartridge_dispatch) == "$before" ]]'))

    def test_reset_does_not_use_persistent_unplug_or_state_writes(self):
        self.cartridge()
        self.assert_ok(self.probe('bashcmdr_unplug_cartridge() { printf "unexpected-unplug\\n" >> "$TRACE"; return 37; }\n__bashcmdr_set_cartridge_state() { printf "unexpected-state-write\\n" >> "$TRACE"; return 37; }\nconsole_reset'))

    def test_initialization_failure_prevents_all_hook_effects(self):
        self.cartridge();before=self.states()
        p=self.probe('__bashcmdr_init_state() { return 37; }\nconsole_reset')
        self.assertEqual(p.returncode,1,p.stdout+p.stderr)
        self.assertEqual(self.states(),before)
        self.assertEqual(self.trace.read_text(),'')


if __name__=='__main__':unittest.main(verbosity=2)
