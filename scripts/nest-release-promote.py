#!/usr/bin/env python3
"""Explicit release alias promotion or rollback; default is a read-only check.

Requires skopeo and existing registry authentication. Run under exclusive release
operator ownership. Registry tags do not offer a server-side compare-and-swap.
"""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile

R = runpy.run_path(str(Path(__file__).with_name('nest-release-manifest.py')))
require = R['require']
TAG = r'[a-z0-9][a-z0-9.:-]*(?:/[a-z0-9][a-z0-9._-]*)+:[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}'


def checked(value):
    R['fields'](value, 'schema kind expectations candidate', 'manifest')
    require(type(value['schema']) is int and value['schema'] == 1 and value['kind'] == 'nest_release_manifest',
            'unsupported manifest')
    require(value == R['validate'](value['expectations'], value['candidate']), 'invalid manifest')
    return value


def images(manifest):
    return {(row['member']['id'], role): ref for row in manifest['candidate']['outputs']
            for role, ref in row['artifacts'].items() if role != 'root'}


def command(args):
    # Native diagnostics may contain authentication details; never forward them.
    return subprocess.run(args, capture_output=True, check=True, timeout=3600).stdout


def inspect(reference):
    raw = command(['skopeo', 'inspect', '--raw', 'docker://' + reference])
    require(0 < len(raw) <= R['LIMIT'], 'invalid registry manifest size')
    value = json.loads(raw)
    require(type(value) is dict and value.get('schemaVersion') == 2, 'unsupported registry manifest')
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


def roots(manifest):
    helper = Path(__file__).resolve().parents[1] / 'files/build/check-stage3-root.py'
    for row in manifest['candidate']['outputs']:
        if row['member']['stage'] == 'stage3':
            root = row['artifacts']['root']
            result = command([sys.executable, str(helper), root['path'], row['member']['host'],
                              manifest['expectations']['release'], root['dataset_guid'],
                              R['digest'](manifest['expectations']), '--content-digest', root['content_digest']])
            require(json.loads(result) == root, 'root readback differs')


def selection(candidate, previous, plan):
    checked(candidate)
    checked(previous)
    R['fields'](plan, 'schema kind manifest_digest previous_digest aliases', 'promotion plan')
    require(type(plan['schema']) is int and plan['schema'] == 1 and plan['kind'] == 'nest_release_promotion',
            'unsupported promotion plan')
    require(plan['manifest_digest'] == R['digest'](candidate)
            and plan['previous_digest'] == R['digest'](previous), 'changed promotion manifests')
    new, old = images(candidate), images(previous)
    require(type(plan['aliases']) is list and len(plan['aliases']) <= 4096, 'invalid aliases')
    covered, aliases = set(), set()
    for row in plan['aliases']:
        R['fields'](row, 'member artifact alias old', 'alias')
        R['match'](row['member'], R['TOKEN'], 'alias member')
        R['match'](row['artifact'], r'normal|debug|image', 'artifact role')
        key = (row['member'], row['artifact'])
        R['match'](row['alias'], TAG, 'alias')
        R['match'](row['old'], R['IMAGE'], 'old image')
        require(key in new and key in old and row['old'] == old[key], 'missing prior rollback image')
        require(row['alias'].rsplit(':', 1)[0] == new[key].split('@')[0] == old[key].split('@')[0],
                'alias repository differs from selected artifact')
        require(row['alias'] not in aliases, 'duplicate alias')
        aliases.add(row['alias'])
        covered.add(key)
    require(covered == set(new), 'aliases must cover the complete image matrix')
    return new


def promote(candidate, previous, plan, pointer, apply=False):
    new = selection(candidate, previous, plan)
    pointer = Path(pointer)
    require(pointer.is_absolute() and pointer.resolve(strict=True) == pointer and pointer.is_file(),
            'current pointer must be an existing canonical manifest file')
    require(R['load'](pointer) == previous, 'current release pointer changed')
    # Read ALL candidate and rollback resources before the first alias write.
    roots(candidate)
    roots(previous)
    for row in plan['aliases']:
        wanted = new[(row['member'], row['artifact'])]
        for reference in (wanted, row['old']):
            require(inspect(reference) == reference.split('@')[1], 'unreadable selected image')
        require(inspect(row['alias']) == row['old'].split('@')[1], 'old alias changed')
    receipt = dict(schema=1, kind='nest_release_promotion_result', manifest_digest=R['digest'](candidate),
                   previous_digest=R['digest'](previous), aliases=len(plan['aliases']), applied=False)
    if not apply:
        return receipt
    # A complete readable rollback description must survive even a partial copy.
    R['retain'](str(pointer.parent), R['canonical'](previous))
    R['retain'](str(pointer.parent), R['canonical'](plan))
    # The caller holds the directory-local lock. Recheck before each mutation;
    # a failed/ambiguous copy stops here and NEVER advances the release pointer.
    for row in plan['aliases']:
        require(R['load'](pointer) == previous, 'current release pointer changed')
        require(inspect(row['alias']) == row['old'].split('@')[1], 'old alias changed before copy')
        wanted = new[(row['member'], row['artifact'])]
        command(['skopeo', 'copy', '--all', '--preserve-digests', 'docker://' + wanted, 'docker://' + row['alias']])
        require(inspect(row['alias']) == wanted.split('@')[1], 'alias readback differs')
    roots(candidate)
    for row in plan['aliases']:
        require(inspect(row['alias']) == new[(row['member'], row['artifact'])].split('@')[1],
                'alias changed before pointer publication')
    require(R['load'](pointer) == previous, 'current release pointer changed')

    raw = R['canonical'](candidate)
    fd, temporary = tempfile.mkstemp(prefix='.promotion-', dir=pointer.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o644)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, pointer)
        directory = os.open(pointer.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        require(pointer.read_bytes() == raw, 'release pointer readback differs')
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    receipt['applied'] = True
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('manifest', 'previous', 'plan', 'pointer'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--apply', action='store_true', help='Explicit authorized alias writes and final pointer replacement')
    args = parser.parse_args()
    try:
        # Plan-only opens no lock or output file. Apply coordinates this operator
        # path, not unrelated registry writers; those require manual coordination.
        if args.apply:
            pointer = Path(args.pointer)
            require(pointer.resolve(strict=True) == pointer, 'noncanonical pointer')
            fd = os.open(str(pointer) + '.lock', os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'wb') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                result = promote(R['load'](args.manifest), R['load'](args.previous), R['load'](args.plan), args.pointer, True)
        else:
            result = promote(R['load'](args.manifest), R['load'](args.previous), R['load'](args.plan), args.pointer)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, RecursionError, subprocess.SubprocessError):
        print('Release promotion refused or incomplete; inspect actual aliases and retained manifests before recovery', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
