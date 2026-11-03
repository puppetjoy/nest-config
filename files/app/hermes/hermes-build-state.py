#!/usr/bin/env python3
"""Content-based Puppet guards for the supported Hermes workspace builds."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_files(root, *paths):
    result = subprocess.check_output(
        ['git', '-C', str(root), 'ls-files', '-z', '--cached', '--others',
         '--exclude-standard', '--', *paths],
    )
    return {os.fsdecode(name) for name in result.split(b'\0') if name}


def npm_version(npm_cli):
    command = ['node', str(npm_cli), '--version'] if npm_cli.suffix == '.js' else [str(npm_cli), '--version']
    return subprocess.check_output(command, text=True).strip()


def snapshot(root, kind, npm_cli):
    workspace = 'ui-tui' if kind == 'tui' else 'web'
    inputs = git_files(root, workspace, 'apps/shared', 'package.json', 'package-lock.json')
    # npm ci resolves the root workspace graph, including sibling manifests.
    inputs.update(name for name in git_files(root, 'apps', 'ui-tui', 'web', 'tests-js')
                  if Path(name).name == 'package.json')
    inputs = {name for name in inputs
              if not {'node_modules', 'dist', 'web_dist'} & set(Path(name).parts)
              and not name.endswith('.tsbuildinfo')}
    if not (root / workspace / 'node_modules').is_dir():
        raise ValueError('workspace dependencies are missing')
    if not (root / 'node_modules').is_dir():
        raise ValueError('root workspace dependencies are missing')
    if kind == 'tui':
        output_dir = root / 'ui-tui/dist'
        outputs = [output_dir / 'entry.js']
    else:
        output_dir = root / 'hermes_cli/web_dist'
        outputs = sorted(path for path in output_dir.rglob('*') if path.is_file())
        if not (output_dir / 'index.html').is_file() or not list((output_dir / 'assets').glob('*.js')):
            raise ValueError('dashboard entry point or JavaScript assets are missing')
    if not outputs or any(not path.is_file() or path.stat().st_size == 0 for path in outputs):
        raise ValueError('build output is missing or empty')
    return {
        'schema': 1,
        'guard': digest(Path(__file__)),
        'node': subprocess.check_output(['node', '--version'], text=True).strip(),
        'npm': npm_version(npm_cli),
        'inputs': {name: digest(root / name) for name in sorted(inputs)},
        'outputs': {str(path.relative_to(root)): digest(path) for path in outputs},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('check', 'record'))
    parser.add_argument('root', type=Path)
    parser.add_argument('kind', choices=('tui', 'web'))
    parser.add_argument('state', type=Path)
    parser.add_argument('npm_cli', type=Path)
    args = parser.parse_args()
    try:
        current = snapshot(args.root, args.kind, args.npm_cli)
        if args.action == 'check':
            return 0 if json.loads(args.state.read_text()) == current else 1
        temporary = args.state.with_name(args.state.name + '.new')
        temporary.write_text(json.dumps(current, sort_keys=True) + '\n')
        temporary.replace(args.state)
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print('Hermes build state unavailable: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
