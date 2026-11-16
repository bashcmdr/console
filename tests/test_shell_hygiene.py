#!/usr/bin/env python3
"""Owned shell-state/config lifetime controls, without production hooks or services."""
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(os.environ.get('HYGIENE_TEST_REPO', Path(__file__).resolve().parents[1])).resolve()
BASH = Path(os.environ.get('HYGIENE_TEST_BASH', shutil.which('bash'))).resolve()
EVIDENCE = Path(os.environ['HYGIENE_TEST_EVIDENCE_DIR'] if 'HYGIENE_TEST_EVIDENCE_DIR' in os.environ
                else tempfile.mkdtemp(prefix='bcm-hygiene-records-')).resolve()
EVIDENCE.mkdir(parents=True, exist_ok=True)


class HygieneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='bcm-hygiene-owned-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root/'home space'
        self.home.mkdir()
        self.console = self.home/'console'
        self.console.mkdir()
        for directory in ['bin','boot','lib']:
            shutil.copytree(REPO/directory,self.console/directory,symlinks=True)
        shutil.copyfile(REPO/'VERSION',self.console/'VERSION')
        (self.console/'config').mkdir()
        self.trace = self.root/'operations.log'
        self.trace.write_text('')
        self.calls = []
        self.record = EVIDENCE/self._testMethodName
        self.record.mkdir(exist_ok=True)
        self.addCleanup(self.save)
        self.env = {'HOME':str(self.home),'CONSOLE':str(self.console),'TRACE':str(self.trace),
                    'PATH':'/usr/bin:/bin','BASH_ENV':os.devnull,'ENV':os.devnull,
                    'LC_ALL':'C','TERM':'dumb','TMPDIR':str(self.root),'BASHCMDR_QUIET_BOOT':'1'}

    def save(self):
        (self.record/'calls.json').write_text(json.dumps(self.calls,indent=2)+'\n')
        (self.record/'operations.log').write_text(self.trace.read_text())
        config=self.console/'config/bashcmdr.conf'
        if config.is_file(): (self.record/'config-fixture.txt').write_text(config.read_text())

    def config(self,text='config_count=$(( ${config_count:-0} + 1 ))\n'):
        (self.console/'config/bashcmdr.conf').write_text(text)

    def shell(self,body,*,entry='bin/bashcmdr',strict=False):
        inert='\n'.join(name+'() { printf "external:'+name+'\\n" >> "$TRACE"; return 99; }'
                        for name in ['sudo','git','curl','wget'])
        prefix='set -euo pipefail\n' if strict else ''
        script=prefix+inert+'\n'
        if entry:script+='source "$CONSOLE/'+entry+'" || exit $?\n'
        script+=body
        p=subprocess.run([str(BASH),'--noprofile','--norc','-c',script],env=self.env,cwd=self.root,
                         text=True,capture_output=True,timeout=10)
        self.calls.append({'entry':entry,'script':script,'exit':p.returncode,'stdout':p.stdout,'stderr':p.stderr})
        self.assertNotIn('external:',self.trace.read_text())
        return p

    def good(self,p):self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def cartridge(self):
        directory=self.console/'cartridges/fixture'
        directory.mkdir(parents=True)
        (directory/'manifest.json').write_text(json.dumps({'name':'fixture','version':'1.0.0','type':'fixture',
            'dependencies':[],'bashcmdr':{'loaded_var':'HYGIENE_LOADED'}})+'\n')
        (directory/'main.bashcmdr').write_text('cartridge_dispatch() {\n'
            '  printf "fixture:%s\\n" "$1" >> "$TRACE"\n'
            '  [[ $1 != activate ]] || HYGIENE_LOADED=1\n'
            '  return 0\n}\n')
        active=self.console/'console/active'
        active.mkdir(parents=True)
        (active/'fixture').symlink_to('../../cartridges/fixture')

    def test_repeated_core_source_evaluates_config_once(self):
        self.config()
        self.good(self.shell('source "$CONSOLE/lib/core.bashcmdr"; source "$CONSOLE/lib/core.bashcmdr"; [[ $config_count == 1 ]]',entry='lib/core.bashcmdr',strict=True))

    def test_firmware_library_chain_evaluates_config_once(self):
        self.config()
        self.good(self.shell('printf "config_count=%s\\n" "$config_count"; [[ $config_count == 1 ]]',strict=True))

    def test_bios_and_repeated_bios_evaluate_config_once(self):
        self.config()
        self.good(self.shell('source "$CONSOLE/boot/shell-init.bashcmdr"; printf "config_count=%s\\n" "$config_count"; [[ $config_count == 1 && $BASHCMDR_BOOT_EXIT_CODE == 0 ]]',entry='boot/shell-init.bashcmdr',strict=True))

    def test_config_can_source_core_without_recursion(self):
        self.config('config_count=$(( ${config_count:-0} + 1 ))\n'
                    'if (( config_count < 3 )); then source "$CONSOLE/lib/core.bashcmdr"; fi\n')
        self.good(self.shell('[[ $config_count == 1 ]]',entry='lib/core.bashcmdr',strict=True))

    def test_failed_config_status_is_retained_without_reexecution(self):
        self.config('config_count=$(( ${config_count:-0} + 1 ))\nreturn 37\n')
        self.good(self.shell('source "$CONSOLE/lib/core.bashcmdr"; first=$?; '
                             'source "$CONSOLE/lib/core.bashcmdr"; second=$?; '
                             '[[ $first == 37 && $second == 37 && $config_count == 1 ]]',entry=None))

    def test_config_created_after_initialization_requires_fresh_shell(self):
        self.good(self.shell('printf "late_config=1\\n" > "$CONSOLE/config/bashcmdr.conf"; '
                             'source "$CONSOLE/lib/core.bashcmdr"; [[ ! ${late_config+x} ]]',entry='lib/core.bashcmdr',strict=True))
        self.good(self.shell('[[ $late_config == 1 ]]',entry='lib/core.bashcmdr',strict=True))

    def test_core_tracks_a_changed_explicit_root_selection(self):
        self.config()
        other=self.home/'second';(other/'config').mkdir(parents=True)
        (other/'config/bashcmdr.conf').write_text('second_config=$(( ${second_config:-0} + 1 ))\n')
        self.good(self.shell('BASHCMDR_ROOT="$HOME/second"; source "$CONSOLE/lib/core.bashcmdr"; '
                             'source "$CONSOLE/lib/core.bashcmdr"; [[ $config_count == 1 && $second_config == 1 ]]',entry='lib/core.bashcmdr',strict=True))

    def test_source_once_guard_survives_library_reimport(self):
        f=self.home/'once.sh';f.write_text('once_count=$(( ${once_count:-0} + 1 ))\n')
        self.good(self.shell('bc.source-once "$HOME/once.sh"; source "$CONSOLE/lib/sourcing.bashcmdr"; '
                             'bc.source-once "$HOME/once.sh"; [[ $once_count == 1 ]]',entry='lib/sourcing.bashcmdr',strict=True))

    def test_source_once_canonical_guard_survives_alias_reimport(self):
        f=self.home/'once.sh';f.write_text('once_count=$(( ${once_count:-0} + 1 ))\n')
        (self.home/'alias.sh').symlink_to(f.name)
        self.good(self.shell('bc.source-once "$HOME/once.sh"; source "$CONSOLE/lib/sourcing.bashcmdr"; '
                             'bc.source-once "$HOME/alias.sh"; [[ $once_count == 1 ]]',entry='lib/sourcing.bashcmdr',strict=True))

    def test_incompatible_reserved_once_array_fails_without_erasing_it(self):
        self.good(self.shell('declare -a __SF_SOURCED=([0]=keep); '
                             'source "$CONSOLE/lib/sourcing.bashcmdr"; status=$?; '
                             '[[ $status == 1 && ${__SF_SOURCED[0]} == keep ]]',entry=None))

    def test_bios_retains_root_and_runtime_state_for_loaded_functions(self):
        self.cartridge()
        self.good(self.shell('[[ $BASHCMDR_ROOT == "$CONSOLE" && ${BASHCMDR_BOOT_RESULTS[fixture]} == succeeded ]]',entry='boot/shell-init.bashcmdr',strict=True))

    def test_require_active_cartridge_works_after_bios(self):
        self.cartridge()
        self.good(self.shell('bashcmdr_require_cartridge fixture',entry='boot/shell-init.bashcmdr',strict=True))
        self.good(self.shell('readonly BASHCMDR_ROOT; bashcmdr_require_cartridge fixture',entry='boot/shell-init.bashcmdr',strict=True))
        quarantine=self.console/'console/quarantine/fixture'
        quarantine.symlink_to('../../cartridges/fixture')
        self.good(self.shell('bashcmdr_require_cartridge fixture; status=$?; [[ $status == 1 ]]',entry='boot/shell-init.bashcmdr'))

    def test_require_missing_cartridge_still_fails(self):
        self.good(self.shell('bashcmdr_require_cartridge absent; status=$?; [[ $status == 1 ]]',entry='boot/shell-init.bashcmdr'))
        self.good(self.shell('declare -gA BASHCMDR_CARTRIDGES_STATE=([legacy]=active); '
                             'bashcmdr_require_cartridge legacy',entry='lib/core.bashcmdr',strict=True))
        self.good(self.shell('declare -a BASHCMDR_CARTRIDGES_STATE=([0]=active); '
                             'bashcmdr_require_cartridge absent; status=$?; [[ $status == 1 ]]',entry='lib/core.bashcmdr'))

    def test_boot_only_helpers_are_removed(self):
        self.good(self.shell('for helper in __bashcmdr_boot_error __bashcmdr_boot_poweron '
                             '__bashcmdr_boot_output_success __bashcmdr_boot_run_console; do '
                             '! declare -F "$helper" >/dev/null || exit 1; done',entry='boot/shell-init.bashcmdr',strict=True))

    def test_postboot_public_path_and_sourcing_helpers_work(self):
        (self.home/'code.sh').write_text('public_source_ok=1\n')
        self.good(self.shell('addpath "$HOME/extra"; [[ :$PATH: == *":$HOME/extra:"* ]]; '
                             'bc.source "$HOME/code.sh"; [[ $public_source_ok == 1 ]]',entry='boot/shell-init.bashcmdr',strict=True))

    def test_postboot_reset_preserves_binding_and_selected_choices(self):
        self.cartridge()
        self.good(self.shell('root_before=$BASHCMDR_ROOT; console_reset || exit $?; '
                             '[[ $BASHCMDR_ROOT == "$root_before" && -L "$CONSOLE/console/active/fixture" ]]',entry='boot/shell-init.bashcmdr',strict=True))
        self.assertEqual(self.trace.read_text().splitlines(),['fixture:activate','fixture:deactivate','fixture:activate'])

    def test_retained_compatibility_functions_remain_available(self):
        self.good(self.shell('for helper in main help_cmd console_poweron console_reset Usage options '
                             '__bashcmdr_add_to_path __bashcmdr_discover_cartridge_root; do '
                             'declare -F "$helper" >/dev/null || exit 1; done',entry='boot/shell-init.bashcmdr',strict=True))

    def test_source_preserves_caller_flags_and_directory(self):
        self.good(self.shell('before=$-; here=$PWD; source "$CONSOLE/lib/core.bashcmdr"; '
                             'source "$CONSOLE/lib/sourcing.bashcmdr"; [[ $- == "$before" && $PWD == "$here" ]]',strict=True))

    def test_second_bios_entry_keeps_original_installation_and_outcome(self):
        other=self.home/'second';shutil.copytree(self.console,other,symlinks=True)
        self.config()
        self.good(self.shell('source "$HOME/second/boot/shell-init.bashcmdr"; '
                             '[[ $BASHCMDR_ROOT_DIR == "$CONSOLE" && $BASHCMDR_ROOT == "$CONSOLE" '
                             '&& $BASHCMDR_BOOT_EXIT_CODE == 0 && $config_count == 1 ]]',entry='boot/shell-init.bashcmdr',strict=True))

    def test_empty_boot_remains_quiet_and_does_not_call_external_sinks(self):
        p=self.shell('[[ $BASHCMDR_BOOT_EXIT_CODE == 0 ]]',entry='boot/shell-init.bashcmdr',strict=True)
        self.good(p);self.assertEqual(p.stdout,'');self.assertEqual(p.stderr,'');self.assertEqual(self.trace.read_text(),'')


if __name__ == '__main__':
    (EVIDENCE/'runner.json').write_text(json.dumps({'at':datetime.datetime.now().astimezone().isoformat(),
        'bash':str(BASH),'repo':str(REPO),'scope':'Owned copied code, inert config/hooks/tool sinks. No live installations, sudo, network or native certification.'},indent=2)+'\n')
    unittest.main(verbosity=2)
