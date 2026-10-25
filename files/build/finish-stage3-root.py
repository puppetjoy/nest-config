#!/usr/bin/env python3
"""Complete one stopped frozen Stage 3 build through local sealed publication."""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import runpy
import stat
import subprocess
import sys

SPEC = importlib.util.spec_from_file_location('stage3_materialize', Path(__file__).with_name('materialize-stage3-root.py'))
assert SPEC is not None and SPEC.loader is not None
MAT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MAT)
PUB = MAT.PUB
ROOT = MAT.ROOT
require = ROOT.require


def preflight(container, staging, staging_guid, receipts, hostname, release, parent_guid, expectations, identity):
    require(os.geteuid() == 0)
    for value, pattern in [(container, r'[a-z0-9][a-z0-9_.-]{0,127}'),
                           (hostname, r'[a-z0-9][a-z0-9-]{0,62}'), (release, ROOT.TOKEN),
                           (staging_guid, ROOT.GUID), (parent_guid, ROOT.GUID), (expectations, ROOT.DIGEST)]:
        require(type(value) is str and re.fullmatch(pattern, value) is not None)
    require(staging_guid != parent_guid)
    staging, receipts, identity = Path(staging), Path(receipts), Path(identity)
    parent = ROOT.BASE / release / 'hosts'
    paths = [staging, receipts, identity, parent]
    for path in paths:
        require(path.is_absolute() and path != Path('/'))
        ROOT.safe_ancestors(path)
    for index, path in enumerate(paths):
        for other in paths[index + 1:]:
            require(path != other and path not in other.parents and other not in path.parents)
    require(staging != ROOT.BASE and ROOT.BASE not in staging.parents and staging not in ROOT.BASE.parents)
    require(stat.S_IMODE(receipts.stat().st_mode) == 0o700)
    require(stat.S_IMODE(parent.stat().st_mode) == 0o700)
    source = PUB.filesystem(staging, 'off', staging_guid)
    destination = PUB.filesystem(parent, 'off', parent_guid, parent=True)
    require(source[0] != destination[0] and not destination[0].startswith(source[0] + '/'))
    require(not os.listdir(staging))
    output = parent / hostname
    require(not output.exists() and not output.is_symlink())
    for name in ['materialize-' + staging_guid + '.started', 'materialize-' + staging_guid + '.json',
                 'finish-' + staging_guid + '.started', 'finish-' + staging_guid + '.json']:
        path = receipts / name
        require(not path.exists() and not path.is_symlink())
    return staging, receipts


def retain(path, row):
    raw = ROOT.canonical(row)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    PUB.fsync_directory(path.parent)
    require(not path.is_symlink() and path.read_bytes() == raw)


def finish(container, staging, staging_guid, receipts, hostname, release, parent_guid, expectations, identity):
    staging, receipts = preflight(container, staging, staging_guid, receipts, hostname,
                                  release, parent_guid, expectations, identity)
    binding = {'container': container, 'staging': str(staging), 'staging_guid': staging_guid,
               'host': hostname, 'release': release, 'parent_guid': parent_guid, 'expectations': expectations}
    retain(receipts / ('finish-' + staging_guid + '.started'), binding)
    materialized = MAT.materialize(container, str(staging), staging_guid, str(receipts))
    # Reopen the materializer's retained result, then recheck the exact sealed
    # source before handing it to publication. A stdout-only claim is not enough.
    raw = (receipts / ('materialize-' + staging_guid + '.json')).read_bytes()
    require(raw == ROOT.canonical(materialized))
    require(materialized['path'] == str(staging) and materialized['dataset_guid'] == staging_guid)
    PUB.filesystem(staging, 'on', staging_guid)
    require(ROOT.content_digest(staging) == materialized['content_digest'])
    artifact = PUB.publish(str(staging), hostname, release, parent_guid, expectations)
    require(artifact['content_digest'] == materialized['content_digest'])
    # Reopen the final native resource as well as the small durable local record.
    require(ROOT.check(artifact['path'], hostname, release, artifact['dataset_guid'],
                       expectations, materialized['content_digest']) == artifact)
    PUB.filesystem(staging, 'on', staging_guid)
    record = {'schema': 1, 'kind': 'nest_stage3_completed_root', 'binding': binding,
              'materialized': materialized, 'root': artifact}
    retain(receipts / ('finish-' + staging_guid + '.json'), record)
    return {'root': artifact}


def main():
    if sys.argv[1:2] == ['--provision']:
        return provision_main(sys.argv[2:])
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['container', 'staging', 'staging_guid', 'receipts', 'hostname', 'release',
                 'parent_guid', 'expectations', 'identity']:
        parser.add_argument(name)
    parser.add_argument('--check', action='store_true', help='Read-only placement admission; no build or reservation')
    args = parser.parse_args()
    values = [getattr(args, name) for name in ['container', 'staging', 'staging_guid', 'receipts',
                                             'hostname', 'release', 'parent_guid', 'expectations', 'identity']]
    try:
        if args.check:
            preflight(*values)
            print('{"placement_admitted":true}')
        else:
            print(json.dumps(finish(*values), sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, KeyError, IndexError, RuntimeError, subprocess.SubprocessError):
        print('Stage 3 completion failed; retain staging, publication and receipts; no accepted root emitted', file=sys.stderr)
        return 1


def provision(expected, member_id, storage_guid, staging_parent, staging_parent_guid, receipts, apply=False):
    """Place only selected children on existing, explicitly identified local ZFS.

    No pool choice, ancestor creation, quota changes, deletion or OS build.
    Partial attempts are retained; this is not a destructive retry interface.
    """
    release = runpy.run_path(str(Path(__file__).resolve().parents[2] / 'scripts/nest-release-manifest.py'))
    indexed = release['expectations'](expected)
    member = indexed[member_id]
    require(member['stage'] == 'stage3' and member['mode'] == 'fresh' and os.geteuid() == 0)
    base, staging_parent, receipts = ROOT.BASE, Path(staging_parent), Path(receipts)
    identity = Path(member['identity_root'])
    for path in [base, staging_parent, receipts, identity]:
        ROOT.safe_ancestors(path)
    paths = [base, staging_parent, receipts, identity]
    for index, path in enumerate(paths):
        require(all(path != other and path not in other.parents and other not in path.parents
                    for other in paths[index + 1:]))
    require(stat.S_IMODE(receipts.stat().st_mode) == 0o700)
    storage = PUB.filesystem(base, 'off', storage_guid, parent=True)
    staging_storage = PUB.filesystem(staging_parent, 'off', staging_parent_guid, parent=True)
    require(storage[0] != staging_storage[0]
            and not storage[0].startswith(staging_storage[0] + '/')
            and not staging_storage[0].startswith(storage[0] + '/'))
    token = expected['release'] + '-' + member_id
    require(len(token) <= 200)
    staging = staging_parent / token
    output = receipts / ('placement-' + token + '.json')
    require(not staging.exists() and not staging.is_symlink() and not output.exists() and not output.is_symlink())
    parent = base / expected['release'] / 'hosts'
    target = parent / member['host']
    require(not target.exists() and not target.is_symlink())
    # Existing release/hosts parents may be shared by other members. Admit their
    # exact native placement and release ownership; never repair/adopt old paths.
    parents = [(base / expected['release'], storage[0] + '/' + expected['release']),
               (parent, storage[0] + '/' + expected['release'] + '/hosts')]
    existing = {}
    for path, dataset in parents:
        if path.exists() or path.is_symlink():
            row = PUB.filesystem(path, 'off', parent=True)
            require(row[0] == dataset and stat.S_IMODE(path.stat().st_mode) == 0o700)
            require(PUB.command(['zfs', 'get', '-H', '-o', 'value', 'org.nest:build-release', dataset]).strip() == expected['release'])
            existing[path] = row
    result = {'schema': 1, 'kind': 'nest_stage3_placement_plan', 'member': member_id,
              'expectations_digest': release['digest'](expected), 'applied': False}
    if not apply:
        return result
    for path, dataset in parents + [(staging, staging_storage[0] + '/' + token)]:
        if path in existing:
            require(PUB.filesystem(path, 'off', parent=True) == existing[path])
            continue
        # Private no-clobber mountpoint reservation; a failed ZFS create leaves
        # the path for diagnosis, not an automatic destroy/recreate loop.
        path.mkdir(mode=0o700)
        PUB.command(['zfs', 'create', '-u', '-o', 'mountpoint=' + str(path), '-o', 'canmount=noauto',
                     '-o', 'readonly=off', '-o', 'exec=off', '-o', 'setuid=off', '-o', 'devices=off',
                     '-o', 'org.nest:build-release=' + expected['release'], dataset])
        PUB.command(['zfs', 'mount', dataset])
        path.chmod(0o700)
        require(PUB.filesystem(path, 'off', parent=True)[0] == dataset)
    # The original independently selected parent resources must still match.
    require(PUB.filesystem(base, 'off', storage_guid, parent=True) == storage)
    require(PUB.filesystem(staging_parent, 'off', staging_parent_guid, parent=True) == staging_storage)
    placement = {'schema': 1, 'kind': 'nest_stage3_local_placement', 'member': member_id,
                 'expectations_digest': release['digest'](expected), 'staging': str(staging),
                 'staging_guid': PUB.filesystem(staging, 'off')[1], 'receipts': str(receipts),
                 'parent_guid': PUB.filesystem(parent, 'off', parent=True)[1]}
    preflight('placement-check', str(staging), placement['staging_guid'], str(receipts), member['host'],
              expected['release'], placement['parent_guid'], placement['expectations_digest'], str(identity))
    retain(output, placement)
    result.update(applied=True, placement=str(output))
    return result


def provision_main(arguments):
    parser = argparse.ArgumentParser(description='Select local Stage 3 placement; default checks only, --apply provisions children')
    for name in ['expectations', 'member', 'storage-guid', 'staging-parent', 'staging-parent-guid', 'receipts']:
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(arguments)
    try:
        release = runpy.run_path(str(Path(__file__).resolve().parents[2] / 'scripts/nest-release-manifest.py'))
        print(json.dumps(provision(release['load'](args.expectations), args.member, args.storage_guid,
                                   args.staging_parent, args.staging_parent_guid, args.receipts, args.apply), sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, KeyError, IndexError, RuntimeError, subprocess.SubprocessError):
        print('Stage 3 placement refused or incomplete; retain existing paths and datasets for diagnosis', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
