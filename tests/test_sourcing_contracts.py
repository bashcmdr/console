#!/usr/bin/env python3
"""Owned sourcing operands/paths/permission contracts; no BIOS or live installs."""
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(os.environ.get('SOURCING_TEST_REPO', Path(__file__).resolve().parents[1])).resolve()
BASH = Path(os.environ.get('SOURCING_TEST_BASH', shutil.which('bash'))).resolve()
EVIDENCE = Path(os.environ['SOURCING_TEST_EVIDENCE_DIR'] if 'SOURCING_TEST_EVIDENCE_DIR' in os.environ
                else tempfile.mkdtemp(prefix='bcm-sourcing-records-')).resolve()
EVIDENCE.mkdir(parents=True, exist_ok=True)


class SourcingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='bcm-sourcing-owned-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / 'home & literal [x] space'
        self.home.mkdir()
        self.record = EVIDENCE / self._testMethodName
        self.record.mkdir(exist_ok=True)
        self.calls = []
        self.addCleanup(lambda: (self.record/'calls.json').write_text(json.dumps(self.calls, indent=2)+'\n'))
        self.env = {**os.environ, 'HOME':str(self.home), 'BASH_ENV':os.devnull, 'ENV':os.devnull,
                    'TERMUX__HOME':str(self.home), 'LC_ALL':'C', 'SOURCE_LIBRARY':str(REPO/'lib/sourcing.bashcmdr')}

    def file(self, name, data='count=$(( ${count:-0} + 1 ))\n'):
        p = self.home / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data)
        return p

    def shell(self, script, *args, strict=True, extra=None):
        prefix = 'set -euo pipefail\n' if strict else ''
        full = prefix + 'source "$SOURCE_LIBRARY"\n' + script
        p = subprocess.run([str(BASH),'--noprofile','--norc','-c',full,'sourcing-test',*map(str,args)],
                           cwd=self.home,env={**self.env,**(extra or {})},text=True,capture_output=True,timeout=15)
        self.calls.append({'script':full,'args':list(map(str,args)),'exit':p.returncode,'stdout':p.stdout,'stderr':p.stderr})
        return p

    def good(self, p):
        self.assertEqual(p.returncode,0,p.stderr+p.stdout)

    def test_literal_tilde_file_expands_with_literal_home_metacharacters(self):
        self.file('file space.sh')
        p=self.shell('bc.source "~/file space.sh"; [[ $count == 1 ]]')
        self.good(p)

    def test_literal_tilde_directory_expands(self):
        self.file('loaders/one.sh')
        self.good(self.shell('bc.source-dir --sh "~/loaders"; [[ $count == 1 ]]'))

    def test_literal_tilde_source_once_uses_same_canonical_guard(self):
        f=self.file('once.sh')
        self.good(self.shell('bc.source-once "~/once.sh"; bc.source-once "$1"; [[ $count == 1 ]]',f))

    def test_read_path_expands_without_evaluation(self):
        self.file('$(touch injected);.sh')
        self.good(self.shell('IFS= read -r path <<< "$1"; bc.source "$path"; [[ $count == 1 && ! -e injected ]]',
                             '~/$(touch injected);.sh'))

    def test_tilde_inside_a_filename_is_literal(self):
        self.file('prefix~/literal.sh')
        self.good(self.shell('bc.source "prefix~/literal.sh"; [[ $count == 1 ]]'))

    def test_unknown_tilde_user_is_not_current_home(self):
        self.file('~not-a-user/script.sh')
        self.good(self.shell('bc.source "~not-a-user/script.sh"; [[ $count == 1 ]]'))

    def test_zero_operands_and_flags_return_usage_status(self):
        for command in ['bc.source','bc.source-once','bc.source --quiet','bc.source-once --debug',
                        'bc.source --','bc.source-dir --sh','bc.source-dir --sh --','bc.source-dir --all --quiet']:
            with self.subTest(command=command):
                p=self.shell(command,strict=False)
                self.assertEqual(p.returncode,2,p.stderr+p.stdout)
                if '--quiet' not in command:self.assertIn('operand is required',p.stderr)

    def test_zero_operands_under_strict_shell_propagate_status(self):
        for command in ['bc.source','bc.source-once','bc.source-dir --sh','bc.source-dir --all']:
            with self.subTest(command=command):
                p=self.shell(command+'\nprintf SHOULD_NOT_RUN')
                self.assertEqual(p.returncode,2,p.stderr+p.stdout)
                self.assertNotIn('SHOULD_NOT_RUN',p.stdout)
                self.assertNotIn('unbound variable',p.stderr)

    def test_help_does_not_require_operands(self):
        for command in ['bc.source','bc.source-once','bc.source-dir']:
            with self.subTest(command=command):
                p=self.shell(command+' --help');self.good(p);self.assertIn('Usage: '+command,p.stdout)

    def test_actual_unreadable_file_is_distinct_and_never_sourced(self):
        f=self.file('unreadable.sh','printf EXECUTED > "$HOME/executed"\n')
        f.chmod(0)
        self.addCleanup(lambda: f.chmod(0o600) if f.exists() else None)
        probe=self.shell('[[ ! -r $1 ]]',f)
        fact={'euid':os.geteuid() if hasattr(os,'geteuid') else None,'egid':os.getegid() if hasattr(os,'getegid') else None,
              'mode':oct(f.stat().st_mode & 0o777),'bash_not_readable_exit':probe.returncode,
              'python_readable':os.access(f,os.R_OK),'skipped':probe.returncode!=0 or os.access(f,os.R_OK)}
        (self.record/'permission-observation.json').write_text(json.dumps(fact,indent=2)+'\n')
        if fact['skipped']:self.skipTest('Current identity can read mode-000 fixture; no unreadability claim')
        for command in ['bc.source','bc.source-once','bc.source-dir --sh']:
            with self.subTest(command=command):
                p=self.shell(command+' "$1"', self.home if 'dir' in command else f,strict=False)
                self.assertEqual(p.returncode,1,p.stderr+p.stdout)
                self.assertIn('not readable',p.stdout)
                self.assertNotIn('not found',p.stdout)
                self.assertFalse((self.home/'executed').exists())

    def test_missing_file_has_a_distinct_failure(self):
        p=self.shell('bc.source "$1"',self.home/'missing.sh',strict=False)
        self.assertEqual(p.returncode,1);self.assertIn('not found',p.stdout)

    def test_invalid_syntax_fails_without_once_success(self):
        f=self.file('invalid.sh','if then\n')
        p=self.shell('bc.source-once "$1"; first=$?; bc.source-once "$1"; second=$?; [[ $first == 1 && $second == 1 ]]',f,strict=False)
        self.good(p);self.assertNotIn('already sourced',p.stdout)

    def test_multiple_files_continue_but_retain_failure(self):
        f=self.file('valid.sh')
        self.good(self.shell('bc.source "$1/missing" "$2"; rc=$?; [[ $rc == 1 && $count == 1 ]]',self.home,f,strict=False))

    def test_ordinary_source_and_once_keep_caller_state(self):
        f=self.file('valid.sh')
        self.good(self.shell('bc.source "$1"; bc.source "$1"; bc.source-once "$1"; bc.source-once "$1"; [[ $count == 3 ]]',f))

    def test_directory_modes_keep_sort_order_and_filtering(self):
        self.file('loaders/b.sh','order=${order:-}b\n')
        self.file('loaders/a.sh','order=${order:-}a\n')
        self.file('loaders/c.txt','order=${order:-}c\n')
        self.file('loaders/nested/hidden.sh','order=${order:-}BAD\n')
        self.good(self.shell('bc.source-dir --sh "$1"; [[ $order == ab ]]; order=; bc.source-dir --all "$1"; [[ $order == abc ]]',self.home/'loaders'))

    def test_file_directory_rejection_and_empty_directory(self):
        d=self.home/'empty';d.mkdir()
        p=self.shell('bc.source "$1"',d,strict=False)
        self.assertEqual(p.returncode,1);self.assertIn('is a directory',p.stdout)
        self.good(self.shell('bc.source-dir --sh "$1"',d))

    def test_quiet_and_debug_keep_their_output_contract(self):
        f=self.file('valid.sh')
        p=self.shell('bc.source --quiet "$1"; [[ $count == 1 ]]',f);self.good(p);self.assertEqual(p.stdout,'')
        p=self.shell('bc.source --debug "$1"',f);self.good(p);self.assertIn('Sourcing ',p.stdout)

    def test_checked_readlink_failure_uses_existing_fallback(self):
        f=self.file('fallback.sh');tools=self.root/'tools';tools.mkdir()
        link=tools/'readlink';link.write_text('#!/bin/sh\nprintf invalid-partial\nexit 1\n');link.chmod(0o755)
        for command in ['dirname','basename']:(tools/command).symlink_to(shutil.which(command))
        self.good(self.shell('bc.source "~/fallback.sh"; [[ $count == 1 ]]',extra={'PATH':str(tools)}))

    def test_import_preserves_caller_options_and_directory(self):
        self.good(self.shell('before=$-; before_pwd=$PWD; source "$SOURCE_LIBRARY"; [[ $before == "$-" && $PWD == "$before_pwd" && $BASHCMDR_SOURCING_FUNCTIONS_LOADED == 1 ]]'))

    def test_leading_dash_literal_filename_uses_operand_separator(self):
        self.file('-file.sh')
        self.good(self.shell('bc.source -- -file.sh; [[ $count == 1 ]]'))


if __name__ == '__main__':
    (EVIDENCE/'runner.json').write_text(json.dumps({'at':datetime.datetime.now().astimezone().isoformat(),
        'bash':str(BASH),'repo':str(REPO),'scope':'Owned paths and source-only helper library, no BIOS/live installations/sudo/native-platform claim.'},indent=2)+'\n')
    unittest.main(verbosity=2)
