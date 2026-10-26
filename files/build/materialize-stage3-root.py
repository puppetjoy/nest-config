#!/usr/bin/env python3
"""Assemble a stopped frozen build's root and repository volume on private ZFS."""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

SPEC = importlib.util.spec_from_file_location('stage3_publish', Path(__file__).with_name('publish-stage3-root.py'))
assert SPEC is not None and SPEC.loader is not None
PUB = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PUB)
ROOT = PUB.ROOT
require = ROOT.require


def command(arguments):
    return subprocess.run(arguments, capture_output=True, text=True, timeout=3600, check=True).stdout


def inspect(container):
    rows: list[dict] = json.loads(command(['podman', 'container', 'inspect', container]))
    require(type(rows) is list and len(rows) == 1)
    row = rows[0]
    require(re.fullmatch(r'[0-9a-f]{64}', row['Id']) is not None and row['Name'] == container)
    require(row['State']['Status'] == 'exited' and row['State']['Running'] is False
            and row['State']['Paused'] is False and row['State']['Pid'] == 0)
    require(not row.get('ExecIDs'))
    mounts = row['Mounts']
    require(type(mounts) is list)
    destinations = [mount['Destination'] for mount in mounts]
    require(len(destinations) == len(set(destinations)))
    require(set(['/nest', '/falcon', '/var/db/repos']).issubset(destinations))
    for mount in mounts:
        destination = mount['Destination']
        if destination == '/var/db/repos':
            require(mount['Type'] == 'volume' and mount['Name'] == container + '-frozen-repos')
        elif destination in ['/nest', '/falcon']:
            require(mount['Type'] == 'bind' and mount['Source'] == destination)
        else:
            # Emulation helpers are build-only binds, never copied into the root.
            require(re.fullmatch(r'/usr/bin/qemu-[a-z0-9_]+', destination) is not None)
            require(mount['Type'] == 'bind' and mount['Source'] == destination and mount['RW'] is False)
    # Podman adds this transient path while our own mount is open. It is not
    # container identity; keep comparing every other field, including layers.
    row.get('GraphDriver', {}).get('Data', {}).pop('MergedDir', None)
    return row


def volume(container):
    name = container + '-frozen-repos'
    rows: list[dict] = json.loads(command(['podman', 'volume', 'inspect', name]))
    require(type(rows) is list and len(rows) == 1)
    row = rows[0]
    require(row['Name'] == name and row['Driver'] == 'local' and row['Options'] in [None, {}])
    path = Path(row['Mountpoint'])
    require(path.is_absolute() and path != Path('/'))
    ROOT.safe_ancestors(path)
    return row, path


def copy(source, destination, layer=False):
    command(['rsync', '--archive', '--acls', '--hard-links', '--xattrs', '--numeric-ids',
             '--modify-window=-1', '--one-file-system',
             *(['--exclude=/var/db/repos/*'] if layer else []),
             '--', str(source) + '/', str(destination) + '/'])


def no_submounts(path):
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        fields = line.split(' - ', 1)[0].split()
        mount = Path(re.sub(r'\\([0-7]{3})', lambda match: chr(int(match[1], 8)), fields[4]))
        require(path not in mount.parents)


def exclusive_volume(container, identity):
    users = command(['podman', 'ps', '--all', '--no-trunc', '--filter',
                     'volume=' + container + '-frozen-repos', '--format', '{{.ID}}']).splitlines()
    require(users == [identity])


def materialize(container, path, guid, receipts):
    require(os.geteuid() == 0)
    require(re.fullmatch(r'[a-z0-9][a-z0-9_.-]{0,127}', container) is not None)
    require(re.fullmatch(ROOT.GUID, guid) is not None)
    target, receipts = Path(path), Path(receipts)
    require(target.is_absolute() and target != Path('/') and receipts.is_absolute())
    ROOT.safe_ancestors(target)
    ROOT.safe_ancestors(receipts)
    require(stat.S_IMODE(receipts.stat().st_mode) == 0o700)
    require(target != receipts and target not in receipts.parents and receipts not in target.parents)
    require(target != ROOT.BASE and ROOT.BASE not in target.parents and target not in ROOT.BASE.parents)
    destination = PUB.filesystem(target, 'off', guid)
    require(not os.listdir(target))
    before = inspect(container)
    source_volume, repositories = volume(container)
    exclusive_volume(container, before['Id'])
    require(next(mount['Source'] for mount in before['Mounts'] if mount['Destination'] == '/var/db/repos') == str(repositories))
    require(target != repositories and target not in repositories.parents and repositories not in target.parents)
    require(receipts != repositories and receipts not in repositories.parents and repositories not in receipts.parents)
    # A completed or interrupted attempt cannot be replayed, even if the target
    # remained empty. The reservation is deliberately outside the shipped root.
    reservation = receipts / ('materialize-' + guid + '.started')
    fd = os.open(reservation, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        raw = ROOT.canonical({'container': before['Id'], 'dataset_guid': guid})
        require(os.write(fd, raw) == len(raw))
        os.fsync(fd)
    finally:
        os.close(fd)
    PUB.fsync_directory(receipts)
    mounted = False
    try:
        source = Path(command(['podman', 'mount', before['Id']]).strip())
        mounted = True
        require(source.is_absolute() and source != Path('/'))
        ROOT.safe_ancestors(source)
        no_submounts(source)
        no_submounts(repositories)
        require(target != source and target not in source.parents and source not in target.parents)
        require(receipts != source and receipts not in source.parents and source not in receipts.parents)
        require(source != repositories and source not in repositories.parents and repositories not in source.parents)
        # podman mount exposes only the image layer, not external mounts. Admit
        # every mounted subtree explicitly; only the isolated repository volume
        # is release payload. Host shares and emulation helpers remain build-only.
        for relative in ['var', 'var/db', 'var/db/repos']:
            entry = source / relative
            require(entry.is_dir() and not entry.is_symlink())
        source_digest = ROOT.content_digest(source)
        repos_digest = ROOT.content_digest(repositories)
        assembled_digest = ROOT.content_digest(source, repositories=repositories)
        require(inspect(container) == before and volume(container)[0] == source_volume)
        exclusive_volume(container, before['Id'])
        # Preserve the mountpoint but do not copy its hidden image payload.
        # The complete volume replaces that subtree, just as in the build.
        # No source mutation, target deletion or generic exclusion is allowed.
        copy(source, target, layer=True)
        require(not os.listdir(target / 'var/db/repos'))
        copy(repositories, target / 'var/db/repos')
        require(ROOT.content_digest(target / 'var/db/repos') == repos_digest)
        require(ROOT.content_digest(target) == assembled_digest)
        require(ROOT.content_digest(source) == source_digest and ROOT.content_digest(repositories) == repos_digest)
        require(ROOT.content_digest(source, repositories=repositories) == assembled_digest)
        require(inspect(container) == before and volume(container)[0] == source_volume)
        exclusive_volume(container, before['Id'])
        no_submounts(source)
        no_submounts(repositories)
        require(PUB.filesystem(target, 'off', guid) == destination)
        command(['podman', 'unmount', before['Id']])
        mounted = False
        command(['zpool', 'sync', destination[0].split('/')[0]])
        command(['zfs', 'set', 'readonly=on', destination[0]])
        sealed = PUB.filesystem(target, 'on', guid)
        require(sealed == destination[:4] + ['on'])
        digest = ROOT.content_digest(target)
        require(digest == assembled_digest)
        require(PUB.filesystem(target, 'on', guid) == sealed)
        result = {'schema': 1, 'kind': 'nest_stage3_materialized_root', 'container': before['Id'],
                  'path': str(target), 'dataset_guid': guid, 'content_digest': digest}
        raw = ROOT.canonical(result)
        output = receipts / ('materialize-' + guid + '.json')
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        PUB.fsync_directory(receipts)
        require(output.read_bytes() == raw)
        return result
    finally:
        if mounted:
            # Best-effort release after failure, never force unmount, destroy,
            # restart, remove a reservation or claim the incomplete copy passed.
            try:
                command(['podman', 'unmount', before['Id']])
            except (OSError, subprocess.SubprocessError):
                pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('container')
    parser.add_argument('path')
    parser.add_argument('dataset_guid')
    parser.add_argument('receipt_dir')
    args = parser.parse_args()
    try:
        print(json.dumps(materialize(args.container, args.path, args.dataset_guid, args.receipt_dir), sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, KeyError, IndexError, RuntimeError, subprocess.SubprocessError):
        print('Stage 3 root materialization failed; retain reservation and staging root; no accepted artifact emitted', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
