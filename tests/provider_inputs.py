#!/usr/bin/env python3
"""Validate pinned first-party code inputs as data; never fetch or execute them."""
import argparse
import hashlib
import json
import pathlib
import re
import subprocess

PIN_FILE = pathlib.Path(__file__).with_name('first-party-inputs.json')
NAMES = ('go', 'nvm', 'pyenv', 'fabric')


def pins():
    data = json.loads(PIN_FILE.read_text())
    if data.get('schema') != 'bashcmdr.first-party-inputs.v1' or set(data['inputs']) != set(NAMES):
        raise ValueError('Expected four first-party inputs in the current schema')
    for name, entry in data['inputs'].items():
        if entry['repository'] != 'bashcmdr/cartridge-' + name or not re.fullmatch('[0-9a-f]{40}', entry['revision']):
            raise ValueError('Invalid repository/revision for ' + name)
        if set(entry['files']) != {'main.bashcmdr', 'manifest.json'} or not all(re.fullmatch('[0-9a-f]{64}', h) for h in entry['files'].values()):
            raise ValueError('Invalid content pins for ' + name)
    return data['inputs']


def verify(root):
    result = {}
    for name, entry in pins().items():
        directory = pathlib.Path(root) / ('bashcmdr-cartridge-' + name)
        for file, expected in entry['files'].items():
            if hashlib.sha256((directory / file).read_bytes()).hexdigest() != expected:
                raise ValueError('First-party content differs from pin: ' + name + '/' + file)
        revision = None
        if (directory / '.git').exists():
            revision = subprocess.check_output(['git', '-C', str(directory), 'rev-parse', 'HEAD'], text=True).strip()
            if revision != entry['revision']:
                raise ValueError('First-party checkout revision differs from pin: ' + name)
        result[name] = {**entry, 'path': str(directory.resolve()), 'observed_revision': revision,
                        'verification': 'commit_and_content' if revision else 'content_only_export'}
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--verify', metavar='ROOT')
    mode.add_argument('--github-output', metavar='FILE')
    args = parser.parse_args()
    try:
        if args.verify:
            print(json.dumps(verify(args.verify), indent=2))
        else:
            data = pins()
            with pathlib.Path(args.github_output).open('a') as stream:
                for name in NAMES:
                    stream.write(name + '=' + data[name]['revision'] + '\n')
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        parser.exit(1, 'First-party input verification failed: ' + str(error) + '\n')
