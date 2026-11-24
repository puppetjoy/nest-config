#!/usr/bin/env python3
"""Validate an already staged PatternKit pair without publishing or deploying it."""

import argparse
import os
import re
import subprocess
from pathlib import Path

PAIR = re.compile(r'[0-9a-f]{40}-[0-9a-f]{40}')
IMAGE = re.compile(r'registry\.eyrie/nest/stage1/server@sha256:[0-9a-f]{64}')


def check(base, pair, image):
    if not PAIR.fullmatch(pair) or not IMAGE.fullmatch(image):
        raise ValueError('expected two full revisions and a pinned Nest runtime image')
    root = base / pair
    for path in (root, root / 'patternkit', root / 'patternkit-atelier'):
        if not path.is_dir() or path.resolve() != path:
            raise ValueError(f'expected a concrete staged directory: {path}')
    for name, revision in zip(('patternkit', 'patternkit-atelier'), pair.split('-'), strict=True):
        repo = root / name
        if os.path.lexists(repo / '.git-credentials'):
            raise ValueError('credential file present in staged source')
        git = ['git', '--no-optional-locks', '-C', str(repo)]
        if subprocess.check_output(git + ['rev-parse', '--show-toplevel'], text=True).strip() != str(repo):
            raise ValueError(f'unexpected Git root: {name}')
        if subprocess.check_output(git + ['rev-parse', 'HEAD'], text=True).strip() != revision:
            raise ValueError(f'wrong staged revision: {name}')
        if subprocess.check_output(git + ['status', '--porcelain', '--untracked-files=all']):
            raise ValueError(f'dirty staged checkout: {name}')
    subprocess.run([
        'podman', 'run', '--rm', '--pull=never', '--network=none', '--read-only',
        '--tmpfs', '/tmp:rw', '-v', f'{root}:/pair:ro', '-w', '/pair/patternkit',
        '--entrypoint', '/bin/sh', image, '-ceu',
        '.venv/bin/python -B -c "import studio; import yaml, reportlab, watchfiles"; '
        'python3 -B /pair/patternkit-atelier/scripts/verify_patternkit_compatibility.py '
        '--patternkit-root /pair/patternkit --revision "$1"',
        'verify', pair.split('-')[0],
    ], check=True, timeout=60)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pair')
    parser.add_argument('image')
    args = parser.parse_args()
    try:
        check(Path('/var/lib/patternkit/source-pairs'), args.pair, args.image)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        parser.exit(1, f'PatternKit preflight failed: {error}\n')
