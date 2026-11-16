#!/usr/bin/env python3
"""Owned path variables and inert editor argv/status controls; no real editor."""
import datetime
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO=Path(os.environ.get('PATH_EDGE_TEST_REPO',Path(__file__).resolve().parents[1])).resolve()
BASH=Path(os.environ.get('PATH_EDGE_TEST_BASH',shutil.which('bash'))).resolve()
EVIDENCE=Path(os.environ['PATH_EDGE_TEST_EVIDENCE_DIR'] if 'PATH_EDGE_TEST_EVIDENCE_DIR' in os.environ
              else tempfile.mkdtemp(prefix='bcm-path-edge-records-')).resolve()
EVIDENCE.mkdir(parents=True,exist_ok=True)


class PathEdgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='bcm-path-edge-owned-')
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.home=self.root/'home with spaces';self.home.mkdir()
        self.temps=self.root/'temporary space';self.temps.mkdir()
        self.tools=self.root/'tools';self.tools.mkdir()
        self.record=EVIDENCE/self._testMethodName;self.record.mkdir(exist_ok=True)
        self.calls=[];self.spy=self.record/'editor-argv.jsonl';self.spy.write_text('')
        self.addCleanup(lambda:(self.record/'calls.json').write_text(json.dumps(self.calls,indent=2)+'\n'))
        self.editor=self.tools/'owned editor'
        self.editor.write_text('#!'+sys.executable+'\n'+
            'import json,os,pathlib,sys\n'
            'with open(os.environ["EDITOR_SPY"],"a") as f:f.write(json.dumps(sys.argv[1:])+"\\n")\n'
            'if os.environ.get("EDITOR_FAIL")=="1":sys.exit(41)\n'
            'pathlib.Path(sys.argv[-1]).write_text(os.environ.get("EDITOR_CONTENT","/EDITED\\n/SECOND\\n"))\n')
        self.editor.chmod(0o755)
        self.env={'HOME':str(self.home),'PATH':str(self.tools)+':/usr/bin:/bin','LC_ALL':'C',
                  'TMPDIR':str(self.temps),'BASH_ENV':os.devnull,'ENV':os.devnull,
                  'PATH_LIBRARY':str(REPO/'lib/path.bashcmdr'),'EDITOR':str(self.editor),'EDITOR_SPY':str(self.spy)}

    def shell(self,body,*,extra=None,strict=True):
        script=('set -euo pipefail\n' if strict else '')+'source "$PATH_LIBRARY"\n'+body
        p=subprocess.run([str(BASH),'--noprofile','--norc','-c',script],cwd=self.home,
                         env={**self.env,**(extra or {})},text=True,capture_output=True,timeout=10)
        self.calls.append({'script':script,'editor':(extra or {}).get('EDITOR',self.env['EDITOR']),
                           'editor_fail':(extra or {}).get('EDITOR_FAIL'),
                           'editor_content_override':(extra or {}).get('EDITOR_CONTENT'),
                           'exit':p.returncode,'stdout':p.stdout,'stderr':p.stderr})
        return p

    def good(self,p):self.assertEqual(p.returncode,0,p.stdout+p.stderr)
    def argv(self):return [json.loads(line) for line in self.spy.read_text().splitlines()]
    def clean(self):self.assertEqual(list(self.temps.iterdir()),[])

    def test_options_preserve_explicit_empty_values_without_flag_sentinel(self):
        self.good(self.shell('probe() { local opt_c=unset options_shift_val options_missing_arg options_unknown_option options_num_args_left; '
                             'options "c:" -c ""; [[ ${opt_c+x} && -z $opt_c && -z $options_missing_arg ]]; }; probe'))

    def test_empty_p_is_rejected_by_all_helpers_without_default_path_mutation(self):
        for command in ['addpath -p "" /new','delpath -p "" /a','uniqpath -p ""','listpath -p ""','edpath -p ""']:
            with self.subTest(command=command):
                p=self.shell('before=$(declare -p PATH); '+command+'; rc=$?; '
                             '[[ $rc == 1 && $(declare -p PATH) == "$before" ]]',strict=False)
                self.good(p);self.assertIn('invalid path variable name:',p.stderr);self.assertNotIn('name: 1',p.stderr)
        self.clean();self.assertEqual(self.argv(),[])

    def test_invalid_ere_preserves_nonempty_empty_and_unset_variable_state(self):
        for setup in ['X=/a:/b','X=','unset X','export X=/a:/b']:
            with self.subTest(setup=setup):
                p=self.shell(setup+'; before=$(declare -p X 2>/dev/null) || before=unset; '
                             'before_path=$PATH; delpath -e -p X "["; rc=$?; '
                             'after=$(declare -p X 2>/dev/null) || after=unset; '
                             '[[ $rc == 2 && $before == "$after" && $PATH == "$before_path" ]]',strict=False)
                self.good(p);self.assertIn('invalid extended regular expression',p.stderr)

    def test_valid_regex_match_and_no_match_retain_expected_path_behavior(self):
        self.good(self.shell('X=/a:/b:/abc; delpath -e -p X "^/a$"; [[ $X == /b:/abc ]]; '
                             'delpath -e -p X "^/missing$"; [[ $X == /b:/abc ]]'))

    def test_unset_delpath_and_uniqpath_have_explicit_exported_empty_results(self):
        for command in ['delpath -p X /missing','uniqpath -p X']:
            with self.subTest(command=command):
                self.good(self.shell('unset X; original=$PATH; '+command+'; '
                                     '[[ ${X+x} && -z $X && $PATH == "$original" && $(declare -p X) == "declare -x "* ]]'))

    def test_inherited_empty_add_and_front_alias_contracts_still_hold(self):
        self.good(self.shell('X=/base; before=$(declare -p X); '
                             'if addpath -p X ""; then exit 81; fi; [[ $(declare -p X) == "$before" ]]; '
                             'addpath --front -p X /first; addpath -b -p X /last; [[ $X == /first:/base:/last ]]'))

    def test_colon_operands_retain_colon_delimited_representation(self):
        self.good(self.shell('X=/head; addpath -p X /left:/right; [[ $X == /head:/left:/right ]]; '
                             '[[ $(listpath -p X) == $\'/head\\n/left\\n/right\' ]]'))

    def test_single_editor_executable_path_with_spaces_is_preserved(self):
        self.good(self.shell('X=/before; edpath -p X; [[ $X == /EDITED:/SECOND && $OLDX == /before ]]'))
        self.assertEqual(len(self.argv()),1);self.assertEqual(len(self.argv()[0]),1);self.clean()

    def test_multiword_editor_command_receives_distinct_arguments(self):
        (self.tools/'editor').symlink_to(self.editor.name)
        self.good(self.shell('X=/before; edpath -p X; [[ $X == /EDITED:/SECOND ]]',extra={'EDITOR':'editor --wait --mode=text'}))
        self.assertEqual(self.argv()[0][:-1],['--wait','--mode=text']);self.clean()

    def test_editor_word_quotes_escapes_and_empty_arguments_are_literal(self):
        editor=shlex.quote(str(self.editor))+' --wait "two words" \'\' escaped\\ space "back\\slash"'
        editor+=' '+shlex.quote("a'b")+' '+shlex.quote('a"b')
        self.good(self.shell('X=/before; edpath -p X',extra={'EDITOR':editor}))
        self.assertEqual(self.argv()[0][:-1],['--wait','two words','','escaped space','back\\slash',"a'b",'a"b']);self.clean()

    def test_editor_words_do_not_evaluate_substitutions_operators_or_globs(self):
        words=['$(touch injected)','`touch injected2`',';','*','$HOME','>','injected3']
        editor=shlex.quote(str(self.editor))+' '+' '.join(shlex.quote(x) for x in words)
        self.good(self.shell('X=/before; edpath -p X',extra={'EDITOR':editor}))
        self.assertEqual(self.argv()[0][:-1],words)
        for name in ['injected','injected2','injected3']:self.assertFalse((self.home/name).exists())
        self.clean()

    def test_malformed_editor_words_fail_before_files_or_variable_changes(self):
        for editor in ["'unterminated",'"unterminated','missing\\','  ',"'' --wait"]:
            with self.subTest(editor=editor):
                p=self.shell('X=/before; OLDX=keep; before=$(declare -p X); old=$(declare -p OLDX); '
                             'if edpath -p X; then exit 82; fi; '
                             '[[ $(declare -p X) == "$before" && $(declare -p OLDX) == "$old" ]]',extra={'EDITOR':editor})
                self.good(p);self.assertIn('edpath:',p.stderr);self.clean()
        self.assertEqual(self.argv(),[])

    def test_failed_editor_preserves_target_and_old_value_and_cleans_temp(self):
        self.good(self.shell('X=/before; OLDX=keep; before=$(declare -p X); old=$(declare -p OLDX); '
                             'if edpath -p X; then exit 83; fi; '
                             '[[ $(declare -p X) == "$before" && $(declare -p OLDX) == "$old" ]]',extra={'EDITOR_FAIL':'1'}))
        self.assertEqual(len(self.argv()),1);self.clean()

    def test_missing_editor_fails_without_creating_old_value_or_tempfile(self):
        self.good(self.shell('X=/before; unset OLDX; if edpath -p X; then exit 84; fi; '
                             '[[ $X == /before && ! ${OLDX+x} ]]',extra={'EDITOR':str(self.root/'absent editor')}))
        self.assertEqual(self.argv(),[]);self.clean()

    def test_empty_editor_output_is_a_successful_empty_path_with_previous_value(self):
        self.good(self.shell('X=/before; edpath -p X; [[ -z $X && $OLDX == /before ]]',extra={'EDITOR_CONTENT':''}))
        self.clean()

    def test_failed_partial_temp_list_and_reconstruction_producers_never_publish(self):
        for function in ['mktemp() { printf /partial-not-a-tempfile; return 31; }',
                         'listpath() { printf partial; return 42; }',
                         'makepath() { printf /wrong; return 43; }']:
            with self.subTest(function=function):
                self.good(self.shell(function+'\nX=/before; OLDX=keep; before=$(declare -p X); old=$(declare -p OLDX); '
                                     'if edpath -p X; then exit 85; fi; '
                                     '[[ $(declare -p X) == "$before" && $(declare -p OLDX) == "$old" ]]'))
                self.clean()

    def test_readonly_or_nonscalar_target_and_old_binding_fail_before_editor(self):
        for setup in ['X=/before; readonly X','X=/before; OLDX=keep; readonly OLDX',
                      'declare -a X=(/before)','declare -i X=7','Y=/before; declare -n X=Y']:
            with self.subTest(setup=setup):
                p=self.shell(setup+'; before=$(declare -p X); '
                             'if edpath -p X; then exit 86; fi; [[ $(declare -p X) == "$before" ]]')
                self.good(p);self.assertIn('writable scalar string',p.stderr);self.clean()
        self.assertEqual(self.argv(),[])

    def test_failed_temp_removal_is_nonzero_without_publishing_edited_values(self):
        p=self.shell('rm() { return 17; }; X=/before; OLDX=keep; '
                     'if edpath -p X; then exit 87; fi; [[ $X == /before && $OLDX == keep ]]')
        self.good(p);self.assertIn('cannot remove temporary file',p.stderr)
        self.assertEqual(len(list(self.temps.iterdir())),1)

    def test_help_and_argument_errors_do_not_open_editor_or_create_files(self):
        for command in ['addpath -h','delpath -h','uniqpath -h','listpath -h','edpath -h']:
            with self.subTest(command=command):self.good(self.shell(command))
        self.good(self.shell('X=/before; if edpath -z -p X; then exit 88; fi; '
                             'if edpath -p; then exit 89; fi; if edpath -p X extra; then exit 90; fi; [[ $X == /before ]]'))
        self.assertEqual(self.argv(),[]);self.clean()

    def test_default_editor_and_path_selection_preserve_caller_flags_and_directory(self):
        (self.tools/'vi').symlink_to(self.editor.name)
        self.good(self.shell('unset EDITOR; before_flags=$-; before_dir=$PWD; prior_path=$PATH; '
                             'edpath; [[ $PATH == /EDITED:/SECOND && $OLDPATH == "$prior_path" '
                             '&& $- == "$before_flags" && $PWD == "$before_dir" ]]'))
        self.assertEqual(len(self.argv()),1);self.clean()


if __name__=='__main__':
    (EVIDENCE/'runner.json').write_text(json.dumps({'at':datetime.datetime.now().astimezone().isoformat(),
        'bash':str(BASH),'repo':str(REPO),'scope':'Owned variables, temporary files and inert editor spy; no interactive editor, production path mutation, sudo or native-platform claim.'},indent=2)+'\n')
    unittest.main(verbosity=2)
