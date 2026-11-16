#!/usr/bin/env python3
"""Installed dependency protection and explicit uninstall state policy."""
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

REPO=pathlib.Path(os.environ.get('UNINSTALL_TEST_REPO',pathlib.Path(__file__).resolve().parent.parent))
PREFIX=r'''
git() { printf 'unexpected-git\n' >> "$TRACE"; return 99; }
curl() { printf 'unexpected-curl\n' >> "$TRACE"; return 99; }
wget() { printf 'unexpected-wget\n' >> "$TRACE"; return 99; }
sudo() { printf 'unexpected-sudo\n' >> "$TRACE"; return 99; }
service() { printf 'unexpected-service\n' >> "$TRACE"; return 99; }
rm() {
    local argument canonical
    for argument in "$@"; do
        [[ "$argument" == -* ]] && continue
        canonical="$argument"
        [[ "$canonical" == /* ]] || canonical="$PWD/$canonical"
        case "$canonical" in "$OWNED"/*) ;; *) printf 'unexpected-rm-outside-fixture\n' >> "$TRACE"; return 97;; esac
        if [[ $canonical == "$CONSOLE/cartridges/base" && ${FAIL_RM-} == package ]]; then return 37; fi
        if [[ $canonical == "$CONSOLE/cartridges/base" && ${FAIL_RM-} == noop-package ]]; then return 0; fi
        if [[ $canonical == "$CONSOLE/console/inactive/base" && ${FAIL_RM-} == state ]]; then return 37; fi
        if [[ $canonical == "$CONSOLE/console/inactive/base" && ${FAIL_RM-} == noop-state ]]; then return 0; fi
        if [[ $canonical == "$HOME/.bashcmdr/registry/installed/base.json" && ${FAIL_RM-} == metadata ]]; then return 37; fi
        if [[ $canonical == "$HOME/.bashcmdr/registry/installed/base.json" && ${FAIL_RM-} == noop-metadata ]]; then return 0; fi
    done
    printf 'RM:%s\n' "$*" >> "$TRACE"
    command rm "$@"
}
'''


class UninstallTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='bcm-uninstall-')
        self.addCleanup(self.temp.cleanup)
        self.root=pathlib.Path(self.temp.name)
        self.home=self.root/'home'
        self.console=self.home/'console with spaces'
        for part in ['bin','lib','boot']:shutil.copytree(REPO/part,self.console/part)
        shutil.copyfile(REPO/'VERSION',self.console/'VERSION')
        (self.console/'cartridges').mkdir()
        for state in ['active','inactive','broken','quarantine']:(self.console/'console'/state).mkdir(parents=True)
        self.registry=self.home/'.bashcmdr/registry'
        self.metadata=self.registry/'installed';self.metadata.mkdir(parents=True)
        self.trace=self.root/'operations.log';self.trace.write_text('')

    def cartridge(self,name='base',deps=None,state='inactive',deactivate=':'):
        cart=self.console/'cartridges'/name;cart.mkdir()
        data={'name':name,'version':'1.0.0','requires':{'cartridges':deps if isinstance(deps,dict) else dict.fromkeys(deps or [],'>=1.0.0')}}
        (cart/'manifest.json').write_text(json.dumps(data))
        (cart/'main.bashcmdr').write_text('cartridge_dispatch() {\n[[ $1 == deactivate ]] || return 0\nprintf "HOOK:'+name+':deactivate\\n" >> "$TRACE"\n'+deactivate+'\n}\n')
        (self.metadata/(name+'.json')).write_text(json.dumps({'cartridge':name,'manifest':data}))
        if state:
            link=self.console/'console'/state/name
            if link.is_symlink():link.unlink()
            link.symlink_to('../../cartridges/'+name)
        return cart

    def index(self,mode):
        path=self.registry/'index.json'
        if mode=='missing':path.unlink(missing_ok=True);return
        if mode=='invalid':path.write_text('{broken');return
        data={}
        for cart in (self.console/'cartridges').iterdir():
            if cart.is_dir() and (cart/'manifest.json').is_file():data[cart.name]=json.loads((cart/'manifest.json').read_text())
        if mode=='stale':
            for value in data.values():value['requires']={'cartridges':{}}
        path.write_text(json.dumps({'cartridges':data}))

    def probe(self,body='main cartridge uninstall base',*,prelude='',extra=None):
        env={'HOME':str(self.home),'CONSOLE':str(self.console),'OWNED':str(self.root),'TRACE':str(self.trace),
             'PATH':'/usr/bin:/bin','LC_ALL':'C','TERM':'dumb','TMPDIR':str(self.root)}
        env.update(extra or {})
        p=subprocess.run(['/bin/bash','--noprofile','--norc','-c',PREFIX+prelude+'\nsource "$CONSOLE/bin/bashcmdr"\n'+body],
            cwd=self.root,env=env,text=True,capture_output=True,timeout=8)
        self.assertNotIn('unexpected-',self.trace.read_text(),p.stdout+p.stderr)
        return p

    def fingerprint(self):
        result={}
        for p in self.root.rglob('*'):
            if p==self.trace:continue
            key=str(p.relative_to(self.root))
            if p.is_symlink():result[key]=('link',os.readlink(p))
            elif p.is_file():result[key]=('file',hashlib.sha256(p.read_bytes()).hexdigest())
        return result

    def assert_blocked(self,body='cartridge_uninstall_cmd base',**kwargs):
        before=self.fingerprint();self.trace.write_text('')
        result=self.probe(body,**kwargs)
        self.assertEqual(result.returncode,1,result.stdout+result.stderr)
        self.assertEqual(self.fingerprint(),before)
        self.assertEqual(self.trace.read_text(),'')
        return result

    def assert_ok(self,p):self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_installed_dependents_block_missing_stale_invalid_and_accurate_registry(self):
        self.cartridge();self.cartridge('app',['base'])
        for mode in ['missing','stale','invalid','accurate']:
            with self.subTest(mode=mode):
                self.index(mode)
                self.assert_blocked('main cartridge uninstall base')

    def test_every_installed_dependent_state_is_protected(self):
        self.cartridge()
        for state in ['inactive','active','broken','quarantine',None]:
            with self.subTest(state=state):
                cart=self.cartridge('app',{'base':None},state=state)
                try:self.assert_blocked()
                finally:
                    for directory in ['active','inactive','broken','quarantine']:(self.console/'console'/directory/'app').unlink(missing_ok=True)
                    shutil.rmtree(cart);(self.metadata/'app.json').unlink();self.trace.write_text('')

    def test_inspection_uses_literal_dependency_keys_and_ignores_constraint_values(self):
        self.cartridge();self.cartridge('app',{'base':False})
        self.assert_blocked()

    def test_regex_metacharacter_in_target_is_literal(self):
        self.cartridge('demo.name');self.cartridge('app',['demoXname']);self.index('accurate')
        self.assert_ok(self.probe('main cartridge uninstall demo.name'))
        self.assertFalse((self.console/'cartridges/demo.name').exists())
        self.assertTrue((self.console/'cartridges/app').exists())

    def test_failed_or_partial_producer_status_blocks_every_removal(self):
        self.cartridge()
        for output in ['', 'app\n']:
            with self.subTest(output=output):
                quoted="'"+output+"'"
                self.assert_blocked('bashcmdr_get_dependents() { printf %s '+quoted+'; return 37; }\ncartridge_uninstall_cmd base')

    def test_invalid_successful_producer_output_blocks_removal(self):
        self.cartridge()
        self.assert_blocked('bashcmdr_get_dependents() { printf "../bad\\n"; }\ncartridge_uninstall_cmd base')

    def test_malformed_or_missing_other_manifest_fails_closed(self):
        self.cartridge();app=self.cartridge('app')
        for data in ['{broken','[]','{"requires":false}','{"requires":{"cartridges":[]}}','{"requires":{"cartridges":{"../bad":"*"}}}']:
            with self.subTest(data=data):
                (app/'manifest.json').write_text(data)
                self.assert_blocked()
        (app/'manifest.json').unlink();self.assert_blocked()

    def test_no_partial_dependent_list_escapes_a_later_inspection_failure(self):
        self.cartridge();self.cartridge('a-app',['base']);bad=self.cartridge('z-bad')
        (bad/'manifest.json').write_text('{broken')
        p=self.probe('bashcmdr_get_dependents base')
        self.assertEqual(p.returncode,1,p.stdout+p.stderr)
        self.assertEqual(p.stdout,'')

    def test_unrelated_valid_package_allows_removal_without_registry_queries(self):
        self.cartridge();self.cartridge('other')
        self.assert_ok(self.probe('bashcmdr_list_registry_cartridges() { printf "unexpected-registry\\n" >> "$TRACE"; return 37; }\nmain cartridge uninstall base'))
        self.assertFalse((self.console/'cartridges/base').exists())
        self.assertTrue((self.console/'cartridges/other').exists())

    def test_plain_inactive_and_broken_uninstall_cleans_framework_state(self):
        for state in ['inactive','broken']:
            with self.subTest(state=state):
                self.cartridge(state=state)
                self.assert_ok(self.probe())
                self.assertFalse((self.console/'cartridges/base').exists())
                self.assertFalse((self.console/'console'/state/'base').is_symlink())
                self.assertFalse((self.metadata/'base.json').exists())

    def test_active_uninstall_deactivates_once_and_cleans_all_ordinary_state(self):
        self.cartridge(state='active')
        p=self.probe();self.assert_ok(p)
        self.assertEqual(self.trace.read_text().count('HOOK:base:deactivate'),1)
        self.assertFalse((self.console/'cartridges/base').exists())
        self.assertFalse((self.console/'console/active/base').is_symlink())
        self.assertFalse((self.console/'console/inactive/base').is_symlink())

    def test_quarantine_is_retained_as_a_documented_tombstone(self):
        self.cartridge(state='quarantine')
        before=os.readlink(self.console/'console/quarantine/base')
        self.assert_ok(self.probe('main cartridge uninstall base\nstatus=$?\n[[ $status == 0 && ${BASHCMDR_CARTRIDGES_STATE[base]-} == quarantine && ! ${BASHCMDR_CARTRIDGES_PATHS[base]+set} ]]'))
        link=self.console/'console/quarantine/base'
        self.assertEqual(os.readlink(link),before)
        self.assertFalse(link.exists())
        self.assertNotIn('HOOK:',self.trace.read_text())

    def test_explicit_purge_removes_quarantine_and_other_target_state(self):
        self.cartridge(state='quarantine')
        (self.console/'console/active/base').symlink_to('../../cartridges/base')
        self.assert_ok(self.probe('main cartridge uninstall base --purge'))
        for directory in ['active','inactive','broken','quarantine']:
            self.assertFalse((self.console/'console'/directory/'base').is_symlink())
        self.assertNotIn('HOOK:',self.trace.read_text())

    def test_purge_does_not_bypass_dependency_protection(self):
        self.cartridge(state='quarantine');self.cartridge('app',['base'])
        self.assert_blocked('main cartridge uninstall base --purge')

    def test_failed_deactivation_leaves_package_metadata_and_state(self):
        self.cartridge(state='active',deactivate='return 37');before=self.fingerprint()
        p=self.probe();self.assertEqual(p.returncode,1,p.stdout+p.stderr)
        self.assertEqual(self.fingerprint(),before)
        self.assertNotIn('RM:',self.trace.read_text())

    def test_new_quarantine_from_deactivation_stops_package_removal(self):
        self.cartridge(state='active',deactivate='__bashcmdr_set_cartridge_state base quarantine')
        p=self.probe();self.assertEqual(p.returncode,1,p.stdout+p.stderr)
        self.assertTrue((self.console/'cartridges/base').exists())
        self.assertTrue((self.console/'console/quarantine/base').is_symlink())
        self.assertIn('State changed',p.stderr)

    def test_new_installed_dependent_from_deactivation_is_rechecked(self):
        body='mkdir -p "$CONSOLE/cartridges/new-app"\nprintf \'%s\\n\' \'{"requires":{"cartridges":{"base":">=1.0.0"}}}\' > "$CONSOLE/cartridges/new-app/manifest.json"'
        self.cartridge(state='active',deactivate=body)
        p=self.probe();self.assertEqual(p.returncode,1,p.stdout+p.stderr)
        self.assertTrue((self.console/'cartridges/base').exists())
        self.assertNotIn('RM:',self.trace.read_text())

    def test_deactivation_storage_changes_do_not_redirect_removal(self):
        self.cartridge(state='active',deactivate='BASHCMDR_INSTALLED_DIR="$HOME"')
        before=self.fingerprint();p=self.probe()
        self.assertEqual(p.returncode,1,p.stdout+p.stderr)
        self.assertEqual(self.fingerprint(),before)
        self.assertNotIn('RM:',self.trace.read_text())

    def test_deactivation_cwd_change_keeps_relative_metadata_anchored(self):
        self.cartridge(state='active',deactivate='cd "$HOME"')
        p=self.probe('main cartridge uninstall base',prelude='BASHCMDR_REGISTRY_DIR=home/.bashcmdr/registry')
        self.assert_ok(p)
        self.assertFalse((self.metadata/'base.json').exists())
        self.assertFalse((self.console/'cartridges/base').exists())

    def test_foreign_state_files_and_wrong_link_targets_are_preserved(self):
        self.cartridge()
        foreign=self.console/'console/quarantine/base';foreign.write_text('foreign bytes')
        self.assert_blocked();foreign.unlink()
        link=self.console/'console/inactive/base';link.unlink();link.symlink_to(self.home)
        self.assert_blocked()

    def test_linked_installed_entries_are_not_followed_or_removed(self):
        self.cartridge();foreign=self.root/'foreign';foreign.mkdir()
        (foreign/'manifest.json').write_text('{"requires":{}}')
        (self.console/'cartridges/linked').symlink_to(foreign,target_is_directory=True)
        self.assert_blocked()

    def test_linked_target_directory_is_not_treated_as_an_owned_package(self):
        self.cartridge();target=self.console/'cartridges/base';moved=self.root/'moved'
        target.rename(moved);target.symlink_to(moved,target_is_directory=True)
        self.assert_blocked()

    def test_wrong_installed_root_does_not_remove_another_directory(self):
        self.cartridge();foreign=self.root/'foreign';(foreign/'base').mkdir(parents=True)
        self.assert_blocked('BASHCMDR_INSTALLED_DIR="$OWNED/foreign"\ncartridge_uninstall_cmd base')

    def test_metadata_type_or_identity_conflict_preserves_package(self):
        self.cartridge();metadata=self.metadata/'base.json'
        metadata.write_text('{"cartridge":"other"}');self.assert_blocked()
        metadata.unlink();metadata.symlink_to(self.console/'cartridges/base/manifest.json');self.assert_blocked()
        metadata.unlink();metadata.mkdir();self.assert_blocked()

    def test_malformed_target_itself_can_be_removed_when_no_other_depends(self):
        cart=self.cartridge(state='broken');(cart/'manifest.json').write_text('{broken')
        self.assert_ok(self.probe('cartridge_uninstall_cmd base'))
        self.assertFalse(cart.exists())

    def test_self_dependency_does_not_prevent_removing_the_only_package(self):
        self.cartridge(deps=['base'])
        self.assert_ok(self.probe())

    def test_unknown_or_extra_options_are_rejected_before_effects(self):
        self.cartridge()
        for args in ['base --force','base --purge extra','base unexpected']:
            with self.subTest(args=args):self.assert_blocked('cartridge_uninstall_cmd '+args)

    def test_missing_jq_with_other_installed_packages_fails_closed(self):
        self.cartridge();self.cartridge('other')
        self.assert_blocked('jq() { return 127; }\ncartridge_uninstall_cmd base')

    def test_locked_or_incompatible_caches_reject_before_removal(self):
        self.cartridge()
        for declaration in ['declare -grA BASHCMDR_CARTRIDGES_STATE=([base]=inactive)','declare -ga BASHCMDR_CARTRIDGES_PATHS=(base)']:
            with self.subTest(declaration=declaration):self.assert_blocked(declaration+'\ncartridge_uninstall_cmd base')

    def test_package_removal_failure_or_noop_does_not_claim_success(self):
        self.cartridge()
        for mode in ['package','noop-package']:
            with self.subTest(mode=mode):self.assert_blocked(extra={'FAIL_RM':mode})

    def test_state_cleanup_failure_is_nonzero_and_cache_matches_retained_marker(self):
        self.cartridge()
        p=self.probe('main cartridge uninstall base\nstatus=$?\n[[ $status == 1 && ! ${BASHCMDR_CARTRIDGES_PATHS[base]+set} && ${BASHCMDR_CARTRIDGES_STATE[base]-} == inactive ]]',extra={'FAIL_RM':'state'})
        self.assert_ok(p)
        self.assertFalse((self.console/'cartridges/base').exists())
        self.assertTrue((self.console/'console/inactive/base').is_symlink())
        self.assertTrue((self.metadata/'base.json').exists())

    def test_noop_state_cleanup_is_detected(self):
        self.cartridge();p=self.probe(extra={'FAIL_RM':'noop-state'})
        self.assertEqual(p.returncode,1,p.stdout+p.stderr)
        self.assertTrue((self.console/'console/inactive/base').is_symlink())

    def test_metadata_cleanup_failure_and_noop_are_not_hidden(self):
        for mode in ['metadata','noop-metadata']:
            with self.subTest(mode=mode):
                self.cartridge()
                p=self.probe(extra={'FAIL_RM':mode})
                self.assertEqual(p.returncode,1,p.stdout+p.stderr)
                self.assertTrue((self.metadata/'base.json').exists())
                self.assertFalse((self.console/'console/inactive/base').is_symlink())
                (self.metadata/'base.json').unlink()

    def test_strict_shell_and_literal_target_remove_only_the_selected_package(self):
        self.cartridge('demo.name');self.cartridge('demoXname')
        self.assert_ok(self.probe('set -euo pipefail\ncartridge_uninstall_cmd demo.name'))
        self.assertTrue((self.console/'cartridges/demoXname').exists())


if __name__=='__main__':unittest.main(verbosity=2)
