#!/usr/bin/env python3
"""Boot dependency plans and hooks in disposable console installations."""
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

REPO = pathlib.Path(os.environ.get('BOOT_ORDER_TEST_REPO', pathlib.Path(__file__).resolve().parent.parent))
PREFIX = r'''
git() { printf 'unexpected-git\n' >> "$TRACE"; return 99; }
curl() { printf 'unexpected-curl\n' >> "$TRACE"; return 99; }
wget() { printf 'unexpected-wget\n' >> "$TRACE"; return 99; }
sudo() { printf 'unexpected-sudo\n' >> "$TRACE"; return 99; }
service() { printf 'unexpected-service\n' >> "$TRACE"; return 99; }
source "$CONSOLE/bin/bashcmdr"
'''


class BootOrderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bcm-boot-order-')
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.home = self.root / 'home'
        self.console = self.home / 'console'
        for name in ['bin', 'lib', 'boot']:
            shutil.copytree(REPO / name, self.console / name)
        shutil.copyfile(REPO / 'VERSION', self.console / 'VERSION')
        (self.console / 'cartridges').mkdir()
        for state in ['active', 'inactive', 'broken', 'quarantine']:
            (self.console / 'console' / state).mkdir(parents=True)
        self.trace = self.root / 'hooks.log'
        self.trace.write_text('')

    def cartridge(self, name, deps=None, state='active', body=':', version='1.0.0'):
        cart = self.console / 'cartridges' / name
        cart.mkdir()
        (cart / 'manifest.json').write_text(json.dumps({'name': name, 'version': version,
            'requires': {'cartridges': deps if isinstance(deps, dict) else dict.fromkeys(deps or [], '>=1.0.0')}}))
        (cart / 'main.bashcmdr').write_text('printf "SOURCE:' + name + '\\n" >> "$TRACE"\n'
            'cartridge_dispatch() {\n[[ $1 == activate ]] || return 0\n'
            'printf "ACT:' + name + '\\n" >> "$TRACE"\n' + body + '\n}\n')
        if state:
            (self.console / 'console' / state / name).symlink_to('../../cartridges/' + name)
        return cart

    def probe(self, body, *, bios=False):
        env = {'HOME': str(self.home), 'CONSOLE': str(self.console), 'TRACE': str(self.trace),
               'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'TERM': 'dumb', 'TMPDIR': str(self.root),
               'BASHCMDR_ROOT_DIR': str(self.console), 'BASHCMDR_QUIET_BOOT': '1'}
        prefix = PREFIX.replace('source "$CONSOLE/bin/bashcmdr"', 'source "$CONSOLE/boot/shell-init.bashcmdr"') if bios else PREFIX
        result = subprocess.run(['/bin/bash', '--noprofile', '--norc', '-c', prefix + body],
                                cwd=self.root, env=env, text=True, capture_output=True, timeout=8)
        self.assertNotIn('unexpected-', self.trace.read_text(), result.stdout + result.stderr)
        return result

    def assert_ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def hooks(self):
        return [line[4:] for line in self.trace.read_text().splitlines() if line.startswith('ACT:')]

    def states(self):
        return {str(p.relative_to(self.console)): os.readlink(p) for s in ['active','inactive','broken','quarantine']
                for p in (self.console / 'console' / s).iterdir() if p.is_symlink()}

    def log(self):
        p = self.console / 'logs/console-poweron.log'
        return p.read_text() if p.exists() else ''

    def assert_preflight_failure(self, body='console_poweron'):
        self.trace.write_text('')
        before = self.states()
        result = self.probe(body)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(self.trace.read_text(), '', result.stdout + result.stderr)
        self.assertEqual(self.states(), before)
        return result

    def test_reverse_named_dependency_supplies_environment_first(self):
        self.cartridge('a-app', ['z-dep'], body='[[ ${DEP_READY-} == 1 ]] || return 37\nexport APP_READY=1')
        self.cartridge('z-dep', body='export DEP_READY=1')
        before = self.states()
        self.assert_ok(self.probe('console_poweron || exit $?\n[[ $APP_READY == 1 && $DEP_READY == 1 ]]'))
        self.assertEqual(self.hooks(), ['z-dep','a-app'])
        self.assertEqual(self.states(), before)

    def test_transitive_diamond_activates_shared_dependency_once(self):
        for name,deps in [('a-app',['b-left','c-right']),('b-left',['z-base']),('c-right',['z-base']),('z-base',[])]:
            self.cartridge(name,deps)
        self.assert_ok(self.probe('console_poweron'))
        hooks = self.hooks()
        self.assertEqual(set(hooks), {'a-app','b-left','c-right','z-base'})
        self.assertEqual(len(hooks),4)
        for dep,child in [('z-base','b-left'),('z-base','c-right'),('b-left','a-app'),('c-right','a-app')]:
            self.assertLess(hooks.index(dep),hooks.index(child))

    def test_essential_cannot_bypass_a_generic_dependency(self):
        self.cartridge('fabric-loader',['z-base'])
        self.cartridge('z-base')
        self.assert_ok(self.probe('console_poweron'))
        self.assertEqual(self.hooks(),['z-base','fabric-loader'])

    def test_independent_essential_preference_and_generic_order(self):
        for name in ['z-other','fabric-loader','nvm-loader','pyenv-loader','a-other']:
            self.cartridge(name)
        self.assert_ok(self.probe('console_poweron'))
        self.assertEqual(self.hooks(),['pyenv-loader','nvm-loader','fabric-loader','a-other','z-other'])

    def test_full_bios_uses_dependency_order_and_retains_context(self):
        self.cartridge('a-app',['z-dep'],body='[[ ${DEP_READY-} == 1 ]] || return 37\nexport APP_READY=1')
        self.cartridge('z-dep',body='export DEP_READY=1')
        self.assert_ok(self.probe('[[ $BASHCMDR_BOOT_EXIT_CODE == 0 && $APP_READY == 1 ]]',bios=True))
        self.assertEqual(self.hooks(),['z-dep','a-app'])

    def test_missing_dependency_prevents_any_hook(self):
        self.cartridge('a-app',['absent'])
        self.cartridge('b-independent')
        self.assert_preflight_failure()
        self.assertIn('boot dependency planning',self.log())

    def test_inactive_broken_and_untracked_dependencies_are_not_activated(self):
        for state in ['inactive','broken',None]:
            with self.subTest(state=state):
                app = self.cartridge('app-'+str(state),['dep-'+str(state)])
                dep = self.cartridge('dep-'+str(state),state=state)
                try:
                    self.assert_preflight_failure()
                finally:
                    for name in [app.name,dep.name]:
                        for directory in ['active','inactive','broken','quarantine']:
                            (self.console/'console'/directory/name).unlink(missing_ok=True)
                        shutil.rmtree(self.console/'cartridges'/name)

    def test_quarantined_dependency_prevents_any_hook(self):
        self.cartridge('a-app',['z-dep'])
        self.cartridge('z-dep',state='quarantine')
        self.assert_preflight_failure()
        self.assertIn('is quarantined',self.log())

    def test_quarantined_target_is_skipped_even_with_active_overlap(self):
        self.cartridge('blocked',state='quarantine')
        (self.console/'console/active/blocked').symlink_to('../../cartridges/blocked')
        self.cartridge('allowed')
        self.assert_ok(self.probe('console_poweron'))
        self.assertEqual(self.hooks(),['allowed'])

    def test_cycle_and_self_cycle_have_no_partial_activation(self):
        for self_cycle in [False,True]:
            with self.subTest(self_cycle=self_cycle):
                self.cartridge('a',['a'] if self_cycle else ['b'])
                if not self_cycle:self.cartridge('b',['a'])
                self.cartridge('z-independent')
                try:
                    self.assert_preflight_failure()
                finally:
                    for p in (self.console/'console/active').iterdir():p.unlink()
                    for p in (self.console/'cartridges').iterdir():shutil.rmtree(p)

    def test_incompatible_version_prevents_all_hooks(self):
        self.cartridge('a-app',{'z-dep':'>=2.0.0'})
        self.cartridge('z-dep',version='1.0.0')
        self.assert_preflight_failure()
        self.assertIn('Version constraint failed',self.log())

    def test_malformed_manifests_and_dependency_maps_fail_closed(self):
        cart = self.cartridge('app')
        for contents in ['{broken', '[]', '{"requires":{"cartridges":[]}}',
                         '{"requires":false}', '{"requires":{"cartridges":false}}', '{"version":false}',
                         '{"requires":{"cartridges":{"dep":""}}}',
                         '{"requires":{"cartridges":{"../escape":">=1.0.0"}}}']:
            with self.subTest(contents=contents):
                (cart/'manifest.json').write_text(contents)
                self.assert_preflight_failure()

    def test_unsafe_or_unsupported_versions_are_rejected_as_data(self):
        self.cartridge('a-app',{'z-dep':'>=1.0.0'})
        cart = self.cartridge('z-dep')
        for version in ['x[$(printf unexpected-version >> "$TRACE")]', '1.0.08', '9999999999.0.0', '1.0.0\n']:
            with self.subTest(version=version):
                value=json.loads((cart/'manifest.json').read_text());value['version']=version
                (cart/'manifest.json').write_text(json.dumps(value))
                self.assert_preflight_failure()

    def test_missing_main_is_rejected_before_other_hooks(self):
        self.cartridge('a-independent')
        cart = self.cartridge('z-missing')
        (cart/'main.bashcmdr').unlink()
        self.assert_preflight_failure()

    def test_ambiguous_or_foreign_active_links_fail_closed(self):
        self.cartridge('app')
        (self.console/'console/inactive/app').symlink_to('../../cartridges/app')
        self.assert_preflight_failure()
        (self.console/'console/inactive/app').unlink()
        (self.console/'console/active/app').unlink()
        (self.console/'console/active/app').symlink_to(self.home)
        self.assert_preflight_failure()

    def test_failed_plan_producer_output_is_not_executed(self):
        self.cartridge('app')
        self.assert_preflight_failure('__bashcmdr_get_boot_plan() { printf "app:\\n"; return 37; }\nconsole_poweron')

    def test_empty_partial_duplicate_and_unknown_plans_are_rejected(self):
        self.cartridge('a')
        self.cartridge('b')
        for plan in ['', 'a:\n', 'a:\na:\n', 'a:\nforeign:\n', 'a\nb:\n', 'a:../outside\nb:\n', 'a:b\nb:\n']:
            with self.subTest(plan=plan):
                quoted="'"+plan.replace("'","'\\''")+"'"
                self.assert_preflight_failure('__bashcmdr_get_boot_plan() { printf %s '+quoted+'; }\nconsole_poweron')

    def test_failed_dependency_blocks_descendants_but_independent_runs(self):
        self.cartridge('a-app',['z-dep'])
        self.cartridge('b-child',['a-app'])
        self.cartridge('c-independent')
        self.cartridge('z-dep',body='return 37')
        self.assert_ok(self.probe('console_poweron; :'))
        self.assertEqual(set(self.hooks()),{'c-independent','z-dep'})
        self.assertNotIn('SOURCE:a-app',self.trace.read_text())
        self.assertIn('blocked by unsuccessful dependency',self.log())

    def test_failed_source_blocks_dependents_and_restores_router(self):
        self.cartridge('a-app',['z-dep'])
        cart = self.cartridge('z-dep')
        (cart/'main.bashcmdr').write_text('printf "SOURCE:z-dep\\n" >> "$TRACE"\nreturn 37\n')
        self.assert_ok(self.probe('before=$(declare -pf cartridge_dispatch)\nconsole_poweron\n[[ $(declare -pf cartridge_dispatch) == "$before" ]]'))
        self.assertEqual(self.trace.read_text(),'SOURCE:z-dep\n')

    def test_state_change_by_prior_hook_blocks_later_source(self):
        self.cartridge('a-first',body='__bashcmdr_set_cartridge_state b-next quarantine')
        self.cartridge('b-next')
        self.cartridge('c-child',['b-next'])
        self.cartridge('d-independent')
        self.assert_ok(self.probe('console_poweron; :'))
        self.assertEqual(self.hooks(),['a-first','d-independent'])
        self.assertTrue((self.console/'console/quarantine/b-next').is_symlink())
        self.assertNotIn('SOURCE:b-next',self.trace.read_text())

    def test_plan_preserves_parent_resolver_cache_and_shell_options(self):
        self.cartridge('a-app',['z-dep'])
        self.cartridge('z-dep')
        result = self.probe(r'''
declare -gA BASHCMDR_DEPENDENCY_GRAPH=([stale]=wrong) BASHCMDR_DEPENDENCY_CONSTRAINTS=([stale]=bad)
declare -ga BASHCMDR_ACTIVATION_ORDER=(stale)
before=$(declare -p BASHCMDR_DEPENDENCY_GRAPH BASHCMDR_DEPENDENCY_CONSTRAINTS BASHCMDR_ACTIVATION_ORDER)
before_options=$(set +o); IFS=','
__bashcmdr_get_boot_plan a-app z-dep || exit $?
[[ $(declare -p BASHCMDR_DEPENDENCY_GRAPH BASHCMDR_DEPENDENCY_CONSTRAINTS BASHCMDR_ACTIVATION_ORDER) == "$before" && $IFS == ',' && $(set +o) == "$before_options" ]]
''')
        self.assert_ok(result)
        self.assertEqual(result.stdout,'z-dep:\na-app:z-dep\n')
        self.assertEqual(self.trace.read_text(),'')

    def test_empty_boot_does_not_require_jq_or_activate_installed_essentials(self):
        for name in ['pyenv-loader','nvm-loader','fabric-loader']:
            self.cartridge(name,state='inactive')
        self.assert_ok(self.probe('jq() { printf "unexpected-jq\\n" >> "$TRACE"; return 37; }\nconsole_poweron'))
        self.assertEqual(self.trace.read_text(),'')

    def test_caller_function_local_caches_do_not_contaminate_planning(self):
        self.cartridge('a-app',['z-dep'])
        self.cartridge('z-dep')
        result = self.probe(r'''
invoke() {
    local -A BASHCMDR_DEPENDENCY_GRAPH=([a-app]=stale) BASHCMDR_DEPENDENCY_CONSTRAINTS=([a-app:stale]=bad)
    local -a BASHCMDR_ACTIVATION_ORDER=(stale)
    local before
    before=$(declare -p BASHCMDR_DEPENDENCY_GRAPH BASHCMDR_DEPENDENCY_CONSTRAINTS BASHCMDR_ACTIVATION_ORDER)
    __bashcmdr_get_boot_plan a-app z-dep || return $?
    [[ $(declare -p BASHCMDR_DEPENDENCY_GRAPH BASHCMDR_DEPENDENCY_CONSTRAINTS BASHCMDR_ACTIVATION_ORDER) == "$before" ]]
}
invoke
''')
        self.assert_ok(result)
        self.assertEqual(result.stdout,'z-dep:\na-app:z-dep\n')
        self.assertEqual(self.trace.read_text(),'')

    def test_failed_jq_does_not_produce_partial_activation(self):
        self.cartridge('app')
        self.assert_preflight_failure('jq() { printf "partial-output\\n"; return 37; }\nconsole_poweron')

    def test_incompatible_readonly_resolver_cache_is_an_explicit_failure(self):
        self.cartridge('app')
        self.assert_preflight_failure('declare -gra BASHCMDR_DEPENDENCY_GRAPH=(wrong)\nconsole_poweron')
        self.assertIn('Cannot initialize isolated boot resolver state',self.log())

    def test_explicit_plug_still_may_activate_an_inactive_dependency(self):
        self.cartridge('a-app',['z-dep'],state='inactive')
        self.cartridge('z-dep',state='inactive')
        self.assert_ok(self.probe('main cartridge plug a-app'))
        self.assertEqual(self.hooks(),['z-dep','a-app'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
