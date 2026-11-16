#!/usr/bin/env python3
"""Completion metadata stays literal, including Readline insertion and Enter.

All attack-shaped values are fixed test strings invoking only an owned printf
probe. The interactive checks require a POSIX PTY on the development test host.
"""
import hashlib
import json
import os
import pathlib
import shlex
import shutil
import subprocess
import tempfile
import unittest

REPO = pathlib.Path(os.environ.get('COMPLETION_DATA_TEST_REPO', pathlib.Path(__file__).resolve().parent.parent))
TOP = ['console', 'cartridge', 'registry', 'version', 'help', 'doctor', 'alias']
NAMES = ['*', '?[ab]', '$(__bcm_completion_probe)', '`__bcm_completion_probe`',
         '$((1+1))', 'two words', 'two\tcolumns', 'two\nlines', 'one\\backslash',
         'a\'single"double', 'name; __bcm_completion_probe', 'ordinary-demo']


class CompletionDataTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='bcm-completion-data-')
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        self.home = self.root/'home'; self.home.mkdir()
        self.store = self.home/'.bashcmdr'; self.store.mkdir()
        self.aliases = self.store/'aliases.json'
        self.registry = self.store/'registry/index.json'; self.registry.parent.mkdir()
        self.storage = self.root/'storage'; self.storage.mkdir()
        for subdir in ['cartridges', 'console/active', 'console/quarantine']:
            (self.storage/subdir).mkdir(parents=True)
        self.trace = self.root/'probe-trace'
        self.bash = shutil.which('bash')
        self.source = REPO/'boot/completions.bash'
        self.tools = self.root/'inert-tools'; self.tools.mkdir()
        self.tool_trace = self.root/'unexpected-tools'
        for name in ['sudo', 'curl', 'wget', 'git']:
            tool = self.tools/name
            tool.write_text('#!'+self.bash+'\nprintf "%s\\n" '+shlex.quote(name)+
                            ' >> '+shlex.quote(str(self.tool_trace))+'\nexit 99\n')
            tool.chmod(0o755)
        self.env = {'HOME': str(self.home), 'PATH': str(self.tools)+os.pathsep+os.environ.get('PATH', os.defpath),
                    'LC_ALL': 'C', 'TERM': 'dumb', 'BASH_ENV': os.devnull, 'ENV': os.devnull,
                    'INPUTRC': os.devnull, 'HISTFILE': os.devnull,
                    'SOURCE': str(self.source), 'TRACE': str(self.trace),
                    'BASHCMDR_ROOT_DIR': str(self.storage)}
        (self.root/'ordinary-file').write_text('owned cwd glob sentinel\n')
        self.calls = []
        self.write_stores([], [])

    def tearDown(self):
        evidence = os.environ.get('COMPLETION_DATA_TEST_EVIDENCE_DIR')
        if evidence:
            out = pathlib.Path(evidence)/self.id().split('.')[-1]
            out.mkdir(parents=True, exist_ok=True)
            (out/'calls.json').write_text(json.dumps({'bash': self.bash,
                'bash_sha256': hashlib.sha256(pathlib.Path(self.bash).read_bytes()).hexdigest(),
                'source_sha256': hashlib.sha256(self.source.read_bytes()).hexdigest(),
                'calls': self.calls, 'probe_called': self.trace.exists(),
                'unexpected_tools': self.tool_trace.exists()}, indent=2)+'\n')
        self.assertFalse(self.trace.exists(), 'Completion must never execute the owned metadata probe')
        self.assertFalse(self.tool_trace.exists(), 'Completion must not invoke network/install/privileged tools')

    def write_stores(self, aliases, registry):
        self.aliases.write_text(json.dumps({n: 'version' for n in aliases}))
        self.registry.write_text(json.dumps({'cartridges': {n: {} for n in registry}}))

    def directories(self, subdir, names):
        for name in names:
            (self.storage/subdir/name).mkdir(exist_ok=True)

    def quoted(self, names):
        p = subprocess.run([self.bash, '--noprofile', '--norc', '-c',
            'for name in "$@"; do printf -v quoted "%q" "$name"; printf "%s\\0" "$quoted"; done',
            'owned', *names], env=self.env, capture_output=True, timeout=10)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout.decode().split('\0')[:-1]

    def completion(self, words, prelude='', helper=False):
        assignments = 'words=('+ ' '.join(shlex.quote(w) for w in words)+'); cword='+str(len(words)-1)+'; cur=${words[cword]}; prev=${words[cword-1]};'
        state = ('_init_completion() { '+assignments+' }' if helper else
                 'COMP_WORDS=('+ ' '.join(shlex.quote(w) for w in words)+'); COMP_CWORD='+str(len(words)-1))
        state_file = self.root/'shell-state'
        script = '''__bcm_completion_probe() { printf '%s\\n' called >> "$TRACE"; }
source "$SOURCE"
'''+prelude+'\n'+state+'''
before=$(set +o; shopt -p || :; declare -p IFS; declare -p GLOBIGNORE 2>/dev/null || :)
__bcm_completions
status=$?
after=$(set +o; shopt -p || :; declare -p IFS; declare -p GLOBIGNORE 2>/dev/null || :)
[[ "$before" == "$after" ]] && printf unchanged > '''+shlex.quote(str(state_file))+'''
if ((${#COMPREPLY[@]})); then printf '%s\\0' "${COMPREPLY[@]}"; fi
exit "$status"
'''
        p = subprocess.run([self.bash, '--noprofile', '--norc', '-c', script],
                           cwd=self.root, env=self.env, capture_output=True, timeout=15)
        values = p.stdout.decode().split('\0')[:-1]
        self.calls.append({'words': words, 'script': script, 'exit': p.returncode,
                           'candidates': values, 'stderr': p.stderr.decode()})
        self.assertEqual(p.returncode, 0, p.stderr.decode())
        self.assertEqual(p.stderr, b'')
        self.assertEqual(state_file.read_text(), 'unchanged')
        self.assertFalse(self.trace.exists(), 'Metadata was evaluated during completion')
        return values

    def test_eight_baseline_routes_now_keep_names_literal(self):
        # The same four routes on host/private Bash4.3 reproduce all eight
        # archived cases. Additional active/quarantine routes share no shortcut.
        self.write_stores(NAMES, NAMES)
        for directory in ['cartridges', 'console/active', 'console/quarantine']:
            self.directories(directory, NAMES)
        for words, expected in [(['bcm', ''], TOP+NAMES),
                                (['bcm', 'alias', 'remove', ''], NAMES),
                                (['bcm', 'cartridge', 'install', ''], NAMES),
                                (['bcm', 'cartridge', 'show', ''], NAMES),
                                (['bcm', 'cartridge', 'uninstall', ''], NAMES),
                                (['bcm', 'cartridge', 'unplug', ''], NAMES),
                                (['bcm', 'cartridge', 'release', ''], NAMES)]:
            with self.subTest(words=words):
                actual = self.completion(words)
                self.assertCountEqual(actual, self.quoted(expected))
                self.assertEqual(len(actual), len(set(actual)))
                self.assertNotIn('ordinary-file', actual)

    def test_literal_prefixes_are_not_globs_or_expansions(self):
        self.write_stores(NAMES, NAMES)
        for prefix in ['*', '?[', '$(', '`', 'two ', 'two\n', 'one\\', 'absent']:
            with self.subTest(prefix=prefix):
                expected = [n for n in NAMES if n.startswith(prefix)]
                for words in [['bcm', prefix], ['bcm', 'cartridge', 'install', prefix]]:
                    self.assertCountEqual(self.completion(words), self.quoted(expected))

    def test_optional_helper_keeps_literal_matching_and_word_boundaries(self):
        self.write_stores(NAMES, [])
        self.assertCountEqual(self.completion(['bcm', 'alias', 'remove', ''], helper=True), self.quoted(NAMES))

    def test_duplicate_union_keeps_ordinary_sorted_order(self):
        self.write_stores(['console', 'shared-demo'], ['z-registry', 'shared-demo'])
        self.directories('cartridges', ['a-installed', 'shared-demo'])
        self.assertEqual(self.completion(['bcm', 'cartridge', 'install', '']),
                         ['a-installed', 'shared-demo', 'z-registry'])
        self.assertEqual(self.completion(['bcm', '']).count('console'), 1)

    def test_invalid_or_multiple_json_documents_offer_no_partial_keys(self):
        self.directories('cartridges', ['installed-demo'])
        for text in ['{partial', '[]', 'null', '{}\n{}', '{"partial":"version"}\n{broken',
                     '{"cartridges": ["bad"]}']:
            with self.subTest(text=text):
                self.aliases.write_text(text); self.registry.write_text(text)
                # The last document is an object, so its alias key is valid;
                # registry fields of non-object type still provide no names.
                expected = ['cartridges'] if text.startswith('{"cartridges"') else []
                self.assertEqual(self.completion(['bcm', 'alias', 'remove', '']), expected)
                self.assertEqual(self.completion(['bcm', 'cartridge', 'show', '']), ['installed-demo'])

    def test_nul_keys_are_rejected_without_concatenating_other_names(self):
        self.write_stores(['before\0after', '', 'ordinary-demo'], ['before\0after', '', 'ordinary-demo'])
        self.assertEqual(self.completion(['bcm', 'alias', 'remove', '']), ['ordinary-demo'])
        self.assertEqual(self.completion(['bcm', 'cartridge', 'show', '']), ['ordinary-demo'])

    def test_caller_glob_and_ifs_settings_are_preserved(self):
        self.directories('cartridges', ['ordinary-demo', 'two words', '.hidden'])
        for prelude in ['set -f; shopt -s failglob dotglob nullglob; GLOBIGNORE="*"; IFS=:',
                        'set -u', 'shopt -s nocaseglob; IFS=']:
            with self.subTest(prelude=prelude):
                self.assertCountEqual(self.completion(['bcm', 'cartridge', 'show', ''], prelude),
                                      self.quoted(['ordinary-demo', 'two words']))

    def test_empty_directories_with_failglob_remain_quiet(self):
        self.assertEqual(self.completion(['bcm', 'cartridge', 'unplug', ''], 'shopt -s failglob'), [])
        self.assertEqual(self.completion(['bcm', 'cartridge', 'release', ''], 'shopt -s failglob'), [])

    def test_ordinary_static_flags_alias_positions_and_from_boundary(self):
        self.aliases.write_text(json.dumps({'cs': 'cartridge show', 'cart': 'cartridge'}))
        self.directories('cartridges', ['demo'])
        self.assertEqual(self.completion(['bcm', 'c']), ['console', 'cartridge', 'cart', 'cs'])
        self.assertEqual(self.completion(['bcm', 'cs', '']), ['demo'])
        self.assertEqual(self.completion(['bcm', 'cartridge', 'install', '--']), ['--from', '--help'])
        self.assertEqual(self.completion(['bcm', 'cartridge', 'install', '--from', '']), [])

    def test_readline_insertion_then_enter_is_literal_in_all_quote_contexts(self):
        self.readline_cases(helper=False)

    def test_readline_with_optional_state_helper_keeps_quoted_names_literal(self):
        self.readline_cases(helper=True)

    def readline_cases(self, helper):
        # Real programmable completion and Readline on the selected interpreter,
        # rather than just testing COMPREPLY in a noninteractive shell.
        import errno
        import pty
        import select
        import signal
        import time
        names = ['zz$(__bcm_completion_probe)', 'zz two words', 'zz\'single"double\\tail',
                 'zz\nnewline', "zzends'", 'zz`__bcm_completion_probe`']
        for name in names:
            self.write_stores([name], [])
            prefixes = ['zz', '"zz', "'zz", 'z"z', "z'z", 'z"z"']
            if name == 'zz two words':
                prefixes.append('zz\\ t')
            for prefix in prefixes:
                with self.subTest(name=name, prefix=prefix):
                    result = self.root/'arguments'
                    result.unlink(missing_ok=True)
                    transcript = bytearray()
                    pid, fd = pty.fork()
                    if pid == 0:
                        os.chdir(self.root)
                        os.execve(self.bash, [self.bash, '--noprofile', '--norc', '-i'], self.env)
                    def until(marker):
                        chunk = bytearray(); deadline = time.monotonic()+6
                        while time.monotonic() < deadline:
                            if select.select([fd], [], [], .05)[0]:
                                try: part = os.read(fd, 65536)
                                except OSError as error:
                                    if error.errno == errno.EIO: break
                                    raise
                                if not part: break
                                chunk.extend(part); transcript.extend(part)
                                if marker in chunk: return
                        self.fail('Readline command did not finish: '+transcript.decode(errors='replace'))
                    try:
                        state_helper = ('_init_completion() { words=("${COMP_WORDS[@]}"); '
                                        'cword=$COMP_CWORD; cur=${words[cword]}; prev=${words[cword-1]}; }; '
                                        if helper else '')
                        init = ('PS1=""; PS2=""; set +o history; '+state_helper+
                                '__bcm_completion_probe() { printf called >> "$TRACE"; }; '
                                'bcm() { printf "%s\\0" "$@" > '+shlex.quote(str(result))+'; }; '
                                'source "$SOURCE"; printf "__%s__\\n" READY\n')
                        os.write(fd, init.encode()); until(b'__READY__\r\n')
                        os.write(fd, ('bcm '+prefix+'\t\n').encode())
                        os.write(fd, b'printf "__%s__\\n" DONE\n'); until(b'__DONE__\r\n')
                        self.assertEqual(result.read_bytes(), name.encode()+b'\0')
                        self.assertFalse(self.trace.exists(), 'Metadata executed after pressing Enter')
                    finally:
                        self.calls.append({'name': name, 'prefix': prefix, 'transcript': transcript.decode(errors='replace')})
                        os.kill(pid, signal.SIGKILL); os.waitpid(pid, 0); os.close(fd)


if __name__ == '__main__':
    unittest.main(verbosity=2)
