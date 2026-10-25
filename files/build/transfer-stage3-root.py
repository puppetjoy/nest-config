#!/usr/bin/env python3
"""Bridge a stopped native build to local ZFS publication over an existing private share."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

SPEC = importlib.util.spec_from_file_location('stage3_finish', Path(__file__).with_name('finish-stage3-root.py'))
assert SPEC is not None and SPEC.loader is not None
FIN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIN)
MAT, PUB, ROOT = FIN.MAT, FIN.PUB, FIN.ROOT
require = ROOT.require


def archive_path(value):
    path = Path(value)
    require(path.is_absolute() and path.suffix == '.tar')
    ROOT.safe_ancestors(path.parent)
    require(stat.S_IMODE(path.parent.stat().st_mode) == 0o700)
    require(path != ROOT.BASE and ROOT.BASE not in path.parents)
    require(Path('/nest/backup') not in path.parents)
    return path


def export_check(archive):
    require(os.geteuid() == 0)
    archive = archive_path(archive)
    for path in [archive, Path(str(archive) + '.started'), Path(str(archive) + '.json')]:
        require(not path.exists() and not path.is_symlink())
    return archive


def file_digest(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_uid == 0 and not before.st_mode & 0o077)
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        require(ROOT.metadata(os.fstat(stream.fileno())) == ROOT.metadata(before))
        require(ROOT.metadata(path.lstat()) == ROOT.metadata(before))
    return 'sha256:' + digest


def export(container, archive):
    archive = export_check(archive)
    require(re.fullmatch(r'[a-z0-9][a-z0-9_.-]{0,127}', container) is not None)
    before = MAT.inspect(container)
    vol, repositories = MAT.volume(container)
    MAT.exclusive_volume(container, before['Id'])
    require(next(m['Source'] for m in before['Mounts'] if m['Destination'] == '/var/db/repos') == str(repositories))
    FIN.retain(Path(str(archive) + '.started'), {'container': before['Id']})
    # Reserve private bytes before GNU tar opens its output. Never clobber a
    # partial archive or remove an intent in order to retry a failed build.
    fd = os.open(archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    os.close(fd)
    mounted = False
    try:
        source = Path(MAT.command(['podman', 'mount', before['Id']]).strip())
        mounted = True
        require(source.is_absolute() and source != Path('/'))
        ROOT.safe_ancestors(source)
        for path in [source, repositories]:
            MAT.no_submounts(path)
            require(path != archive.parent and path not in archive.parents and archive.parent not in path.parents)
        digest = ROOT.content_digest(source, repositories=repositories)
        source_digest, repos_digest = ROOT.content_digest(source), ROOT.content_digest(repositories)
        options = ['--format=pax', '--acls', '--xattrs', '--xattrs-include=*', '--numeric-owner', '--sparse', '--one-file-system']
        MAT.command(['tar', '--create', '--file', str(archive), *options,
                     '--exclude=./var/db/repos/*', '--directory', str(source), '.'])
        # Transform names and hardlink references, never symbolic-link targets.
        MAT.command(['tar', '--append', '--file', str(archive), *options,
                     '--transform=flags=rh;s,^\\.,./var/db/repos,', '--directory', str(repositories), '.'])
        require(ROOT.content_digest(source) == source_digest and ROOT.content_digest(repositories) == repos_digest)
        require(ROOT.content_digest(source, repositories=repositories) == digest)
        require(MAT.inspect(container) == before and MAT.volume(container)[0] == vol)
        MAT.exclusive_volume(container, before['Id'])
        MAT.no_submounts(source)
        MAT.no_submounts(repositories)
        MAT.command(['podman', 'unmount', before['Id']])
        mounted = False
        with archive.open('rb') as stream:
            os.fsync(stream.fileno())
        row = {'archive_digest': file_digest(archive), 'content_digest': digest}
        FIN.retain(Path(str(archive) + '.json'), row)
        return row
    finally:
        if mounted:
            try:
                MAT.command(['podman', 'unmount', before['Id']])
            except (OSError, subprocess.SubprocessError):
                pass


def receive(archive, archive_digest, content_digest, values):
    for digest in [archive_digest, content_digest]:
        require(type(digest) is str and re.fullmatch(ROOT.DIGEST, digest) is not None)
    archive = archive_path(archive)
    # The same existing local placement checks still admit Falcon's actual ZFS,
    # disjoint identity, empty staging, parent GUID and absent final publication.
    staging, receipts = FIN.preflight(*values)
    require(all(path != archive.parent and path not in archive.parents and archive.parent not in path.parents
                for path in [staging, receipts, Path(values[8]), ROOT.BASE]))
    require(file_digest(archive) == archive_digest)
    require(json.loads(Path(str(archive) + '.json').read_bytes()) ==
            {'archive_digest': archive_digest, 'content_digest': content_digest})
    guid = values[2]
    FIN.retain(receipts / ('finish-' + guid + '.started'),
               {'archive_digest': archive_digest, 'content_digest': content_digest, 'binding': values})
    destination = PUB.filesystem(staging, 'off', guid)
    # Only this root-owned producer archive is admitted. Private shared storage
    # carries opaque tar bytes, so NFS need not support release xattrs/devices.
    MAT.command(['tar', '--extract', '--file', str(archive), '--directory', str(staging),
                 '--same-owner', '--same-permissions', '--acls', '--xattrs', '--xattrs-include=*', '--numeric-owner', '--sparse'])
    require(file_digest(archive) == archive_digest)
    require(ROOT.content_digest(staging) == content_digest)
    require(PUB.filesystem(staging, 'off', guid) == destination)
    MAT.command(['zpool', 'sync', destination[0].split('/')[0]])
    MAT.command(['zfs', 'set', 'readonly=on', destination[0]])
    PUB.filesystem(staging, 'on', guid)
    require(ROOT.content_digest(staging) == content_digest)
    artifact = PUB.publish(str(staging), values[4], values[5], values[6], values[7])
    require(artifact['content_digest'] == content_digest)
    require(ROOT.check(artifact['path'], values[4], values[5], artifact['dataset_guid'], values[7], content_digest) == artifact)
    FIN.retain(receipts / ('finish-' + guid + '.json'), {'root': artifact, 'archive_digest': archive_digest})
    return {'root': artifact}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['export-check', 'export', 'receive'])
    parser.add_argument('container')
    parser.add_argument('archive')
    parser.add_argument('values', nargs='*')
    args = parser.parse_args()
    try:
        if args.action == 'export-check':
            require(not args.values)
            export_check(args.archive)
            result = {'transfer_admitted': True}
        elif args.action == 'export':
            require(not args.values)
            result = export(args.container, args.archive)
        else:
            require(len(args.values) == 10)
            result = receive(args.archive, args.values[0], args.values[1], [args.container, *args.values[2:]])
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, KeyError, IndexError, RuntimeError, subprocess.SubprocessError):
        print('Stage 3 transfer refused or incomplete; retain archive, staging and receipts; no accepted root emitted', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
