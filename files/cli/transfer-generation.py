#!/usr/bin/env python3
"""Transfer a versioned mounted publication into an empty host-local ZFS generation."""

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import sys
import tempfile
from typing import Any

sys.dont_write_bytecode = True
SPEC = importlib.util.spec_from_file_location('stage3_root', Path(__file__).with_name('check-stage3-root.py'))
assert SPEC is not None and SPEC.loader is not None
ROOT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ROOT)
require = ROOT.require
STATE = Path('/var/lib/nest/updates')
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C'}


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result)
        result[key] = value
    return result


def policy(raw):
    require(len(raw.encode('utf-8')) <= 16384)
    value: Any = json.loads(raw, object_pairs_hook=unique)
    names = {'schema', 'kind', 'source', 'build_release', 'release', 'content_digest', 'hostname',
             'host_identity_sha256', 'pool_guid', 'destination', 'destination_guid',
             'write_budget_bytes', 'physical_reserve_bytes'}
    require(type(value) is dict and set(value) == names)
    require(type(value['schema']) is int and value['schema'] == 1 and value['kind'] == 'nest_generation_transfer')
    patterns = {'hostname': r'[a-z0-9][a-z0-9-]{0,62}', 'build_release': ROOT.TOKEN,
                'release': ROOT.DIGEST, 'content_digest': ROOT.DIGEST,
                'host_identity_sha256': r'[0-9a-f]{64}', 'pool_guid': ROOT.GUID, 'destination_guid': ROOT.GUID}
    for key, pattern in patterns.items():
        require(type(value[key]) is str and re.fullmatch(pattern, value[key]) is not None)
    require(value['source'] == '/nest/releases/' + value['build_release'] + '/hosts/' + value['hostname'])
    destination: Any = value['destination']
    require(type(destination) is str and re.fullmatch(r'/[A-Za-z0-9_./-]{1,254}', destination) is not None)
    require(not any(part in ('', '.', '..') for part in destination.split('/')[1:]))
    require(destination == '/var/lib/nest/generations/' + value['release'].split(':')[1])
    for key in ('write_budget_bytes', 'physical_reserve_bytes'):
        require(type(value[key]) is int and 0 <= value[key] <= 2 ** 63 - 1)
    require(value['write_budget_bytes'] > 0)
    return value


def command(args, timeout=60):
    # Captured stderr and all content/file identities stay private on failure.
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=True, env=ENV).stdout.strip()


def property_value(dataset, name):
    return command(['zfs', 'get', '-Hp', '-o', 'value', name, dataset])


def mounts():
    rows = json.loads(command(['findmnt', '--json', '--list', '--all', '-o', 'SOURCE,TARGET,FSTYPE,OPTIONS']))['filesystems']
    require(type(rows) is list and all(type(row) is dict and
            all(type(row.get(key)) is str for key in ('source', 'target', 'fstype', 'options')) for row in rows))
    return rows


def exact(path, inventory, writable):
    rows = [row for row in inventory if row['target'] == str(path)]
    require(len(rows) == 1 and rows[0]['fstype'] == 'zfs')
    row = rows[0]
    require(('rw' if writable else 'ro') in row['options'].split(','))
    require(not any(Path(row['target']) != path and path in Path(row['target']).parents for row in inventory))
    dataset = row['source']
    require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]*(?:/[A-Za-z0-9_.:-]+)*', dataset) is not None)
    require(not any(other['source'] == dataset and other['target'] != str(path) for other in inventory))
    require(property_value(dataset, 'mountpoint') == str(path))
    require(property_value(dataset, 'readonly') == ('off' if writable else 'on'))
    require(command(['zfs', 'list', '-H', '-t', 'filesystem,volume', '-r', '-o', 'name', dataset]).splitlines() == [dataset])
    return dataset


def source_mount(path, inventory):
    # A pre-existing read-only NFS publication export is supported. No network
    # mount, remote shell, mutable host alias or source-side write is performed.
    candidates = [row for row in inventory if Path(row['target']) == path or Path(row['target']) in path.parents]
    require(candidates)
    length = max(len(row['target']) for row in candidates)
    selected = [row for row in candidates if len(row['target']) == length]
    require(len(selected) == 1 and selected[0]['fstype'] in ('nfs', 'nfs4', 'zfs'))
    require('ro' in selected[0]['options'].split(','))
    require(not any(path in Path(row['target']).parents for row in inventory))
    return selected[0]


def identity(value, writable, local=False):
    require(os.geteuid() == 0 and socket.gethostname() == value['hostname'])
    machine = Path('/etc/machine-id').read_text().strip()
    require(re.fullmatch(r'[0-9a-f]{32}', machine) is not None)
    require(hashlib.sha256(machine.encode('ascii')).hexdigest() == value['host_identity_sha256'])
    source, destination = Path(value['source']), Path(value['destination'])
    for path in ((destination, STATE) if local else (source, destination, STATE)):
        ROOT.safe_ancestors(path)
    for first, second in ((source, destination), (source, STATE), (destination, STATE)):
        require(first != second and first not in second.parents and second not in first.parents)
    require(stat.S_IMODE(STATE.stat().st_mode) == 0o700)
    inventory: Any = mounts()
    root: Any = [row for row in inventory if row['target'] == '/']
    require(len(root) == 1 and root[0]['fstype'] == 'zfs')
    require(re.fullmatch(r'[^/]+(?:/[^/]+)*/ROOT/[AB]', root[0]['source']) is not None)
    pool = root[0]['source'].split('/')[0]
    require(command(['zpool', 'get', '-Hp', '-o', 'value', 'guid', pool]) == value['pool_guid'])
    require(command(['zpool', 'get', '-Hp', '-o', 'value', 'org.nest:host-id', pool]) == machine)
    state = exact(STATE, inventory, True)
    # Match the explicitly provisioned state contract, not just a filesystem
    # mounted at the right path on a host-bound pool. Never repair or rebind it.
    require(property_value(state, 'org.nest:host-id') == machine)
    require(property_value(state, 'canmount') == 'noauto')
    target = exact(destination, inventory, writable)
    require(state.split('/')[0] == target.split('/')[0] == pool)
    require('ROOT' not in state.split('/') and 'ROOT' not in target.split('/'))
    require(state != target and not state.startswith(target + '/') and not target.startswith(state + '/'))
    require(property_value(target, 'guid') == value['destination_guid'])
    require(property_value(target, 'origin') == '-')
    require(command(['zfs', 'list', '-H', '-t', 'snapshot', '-r', '-o', 'name', target]) == '')
    for name, expected in {'exec': 'off', 'setuid': 'off', 'devices': 'off', 'canmount': 'on'}.items():
        require(property_value(target, name) == expected)
    txg = property_value(target, 'createtxg')
    require(re.fullmatch(ROOT.GUID, txg) is not None)
    expected = {'org.nest:host': value['hostname'], 'org.nest:release': value['release'],
                'org.nest:build-release': value['build_release'], 'org.nest:content-digest': value['content_digest']}
    for name, content in expected.items():
        require(property_value(target, name) == ('-' if writable else content))
    state_guid = property_value(state, 'guid')
    require(re.fullmatch(ROOT.GUID, state_guid) is not None)
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    require(re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', boot) is not None)
    observed = {'dataset': target, 'creation_txg': txg, 'state_dataset': state, 'current': root[0]['source'],
                'boot_id': boot, 'state_guid': state_guid}
    if not local:
        observed['source_mount'] = source_mount(source, inventory)
    return observed


def admission(value, observed):
    target = observed['dataset']
    available = property_value(target, 'available')
    free = command(['zpool', 'get', '-Hp', '-o', 'value', 'free', target.split('/')[0]])
    require(available.isdecimal() and free.isdecimal())
    output = command(['du', '--apparent-size', '--block-size=1', '--summarize', '--one-file-system', '--', value['source']], 3600)
    apparent, path = output.split('\t')
    require(apparent.isdecimal() and path == value['source'])
    require(value['write_budget_bytes'] >= int(apparent))
    require(int(available) >= value['write_budget_bytes'])
    require(int(free) >= value['write_budget_bytes'] + value['physical_reserve_bytes'])
    return {'apparent_bytes': int(apparent), 'available_bytes': int(available), 'physical_free_bytes': int(free)}


def fsync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def retain(path, row):
    raw = ROOT.canonical(row)
    descriptor, temporary = tempfile.mkstemp(prefix='.generation-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        # Atomic no-clobber publication. Never replace a previous generation's
        # reservation/receipt, including one from an interrupted invocation.
        os.link(temporary, path, follow_symlinks=False)
        os.unlink(temporary)
        fsync_directory(path.parent)
        info = path.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1
                and stat.S_IMODE(info.st_mode) == 0o600 and path.read_bytes() == raw)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def contained_paths(root):
    for relative in ('var/db/pkg', 'usr/src/linux', 'lib/modules'):
        resolved = (root / relative).resolve(strict=True)
        require(root in resolved.parents and resolved.is_dir())


def archive_digest(path, expected):
    require(re.fullmatch(ROOT.DIGEST, expected) is not None)
    require(path.is_absolute() and path.suffix == '.tar')
    ROOT.safe_ancestors(path.parent)
    require(stat.S_IMODE(path.parent.stat().st_mode) == 0o700)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_uid == 0 and before.st_nlink == 1
                and stat.S_IMODE(before.st_mode) == 0o600)
        digest = 'sha256:' + hashlib.file_digest(stream, 'sha256').hexdigest()
        require(ROOT.metadata(os.fstat(stream.fileno())) == ROOT.metadata(before)
                and ROOT.metadata(path.lstat()) == ROOT.metadata(before))
    require(digest == expected)


def transfer(value, check=False, archive=None, expected_archive_digest=None):
    require((archive is None) == (expected_archive_digest is None))
    observed = identity(value, True)
    destination = Path(value['destination'])
    require(not os.listdir(destination))
    started = STATE / ('generation-' + value['destination_guid'] + '.started')
    completed = STATE / ('generation-' + value['destination_guid'] + '.complete')
    require(not started.exists() and not started.is_symlink() and not completed.exists() and not completed.is_symlink())
    capacity = admission(value, observed)
    contained_paths(Path(value['source']))
    if archive is None:
        # NFS can synthesize ACLs and hide security.capability. Never normalize
        # away missing metadata or spend a full hash proving that mismatch.
        require(observed['source_mount'].get('fstype', 'zfs') == 'zfs')
        require(ROOT.content_digest(Path(value['source'])) == value['content_digest'])
    else:
        archive = Path(archive)
        for path in (Path(value['source']), destination, STATE):
            require(path != archive and path not in archive.parents and archive not in path.parents)
        archive_digest(archive, expected_archive_digest)
    require(identity(value, True) == observed)
    binding = {'schema': 1, 'kind': 'nest_generation_transfer_report', 'policy': value,
               'policy_sha256': hashlib.sha256(ROOT.canonical(value)).hexdigest(), 'source': observed, 'capacity': capacity,
               'read_only': check, 'sealed': False, 'reset_authorized': False}
    if archive is not None:
        binding['archive'] = {'path': str(archive), 'digest': expected_archive_digest}
    if check:
        return binding
    # Share the native transaction lock. Never unlink it, wait, or break a lock.
    fd = os.open(STATE / '.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require(identity(value, True) == observed and not os.listdir(destination))
        capacity = admission(value, observed)
        binding['capacity'] = capacity
        retain(started, binding)  # Survives every failed/ambiguous copy; never replay.
        if archive is None:
            command(['rsync', '--archive', '--acls', '--hard-links', '--xattrs', '--numeric-ids', '--modify-window=-1',
                     '--one-file-system', '--', value['source'] + '/', str(destination) + '/'], 86400)
        else:
            # Same private producer archive and GNU tar metadata preservation as
            # transfer-stage3-root.py; no transport shell or NFS xattr fiction.
            command(['tar', '--extract', '--file', str(archive), '--directory', str(destination),
                     '--same-owner', '--same-permissions', '--acls', '--xattrs', '--xattrs-include=*',
                     '--numeric-owner', '--sparse'], 86400)
        require(identity(value, True) == observed)
        if archive is None:
            require(ROOT.content_digest(Path(value['source'])) == value['content_digest'])
        else:
            archive_digest(archive, expected_archive_digest)
        require(ROOT.content_digest(destination) == value['content_digest'])
        contained_paths(destination)
        command(['zpool', 'sync', observed['dataset'].split('/')[0]], 3600)
        # Property publication is not atomic; a failed set/seal is retained as an
        # ambiguous started generation, never made writable or automatically retried.
        command(['zfs', 'set', 'org.nest:host=' + value['hostname'], 'org.nest:release=' + value['release'],
                 'org.nest:build-release=' + value['build_release'],
                 'org.nest:content-digest=' + value['content_digest'], 'readonly=on', observed['dataset']])
        require(identity(value, False) == observed)
        require(ROOT.content_digest(destination) == value['content_digest'])
        contained_paths(destination)
        result = dict(binding, read_only=False, sealed=True)
        retain(completed, result)
        return result
    finally:
        os.close(fd)


def receipt(path):
    # A read-only observation never creates a lock, repairs a receipt or follows
    # a symlink. Bound reads also refuse special files and oversized records.
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == 0 and before.st_nlink == 1
                and stat.S_IMODE(before.st_mode) == 0o600 and 0 < before.st_size <= 32768)
        with os.fdopen(descriptor, 'rb', closefd=False) as stream:
            raw = stream.read(32769)
        require(len(raw) == before.st_size and ROOT.metadata(os.fstat(descriptor)) == ROOT.metadata(before)
                and ROOT.metadata(path.lstat()) == ROOT.metadata(before))
        row = json.loads(raw, object_pairs_hook=unique)
        require(type(row) is dict and ROOT.canonical(row) == raw)
        return row, raw
    finally:
        os.close(descriptor)


def verify(value):
    observed = identity(value, False, local=True)
    started = STATE / ('generation-' + value['destination_guid'] + '.started')
    completed = STATE / ('generation-' + value['destination_guid'] + '.complete')
    initial, initial_raw = receipt(started)
    final, final_raw = receipt(completed)
    names = {'schema', 'kind', 'policy', 'policy_sha256', 'source', 'capacity',
             'read_only', 'sealed', 'reset_authorized'}
    require(set(initial) in (names, names | {'archive'}))
    if 'archive' in initial:
        archive: Any = initial['archive']
        require(type(archive) is dict and set(archive) == {'path', 'digest'})
        require(type(archive['path']) is str and Path(archive['path']).is_absolute())
        require(type(archive['digest']) is str and re.fullmatch(ROOT.DIGEST, archive['digest']) is not None)
    require(type(initial['schema']) is int and initial['schema'] == 1
            and initial['kind'] == 'nest_generation_transfer_report')
    require(ROOT.canonical(initial['policy']) == ROOT.canonical(value)
            and initial['policy_sha256'] == hashlib.sha256(ROOT.canonical(value)).hexdigest())
    require(initial['read_only'] is False and initial['sealed'] is False and initial['reset_authorized'] is False)
    require(final_raw == ROOT.canonical(dict(initial, sealed=True)))
    historical = initial['source']
    require(type(historical) is dict and set(historical) == set(observed) | {'source_mount'})
    for key in ('dataset', 'creation_txg', 'state_dataset', 'state_guid'):
        require(historical[key] == observed[key])
    # Current BE and boot are current observations, not replay requirements.
    # Pool/host/destination and shared-state identity are freshly checked above.
    destination = Path(value['destination'])
    contained_paths(destination)
    require(ROOT.content_digest(destination) == value['content_digest'])
    require(identity(value, False, local=True) == observed)
    require(receipt(started)[1] == initial_raw and receipt(completed)[1] == final_raw)
    return {'schema': 1, 'kind': 'nest_generation_verification_report', 'policy': value,
            'policy_sha256': initial['policy_sha256'], 'generation': observed,
            'transfer_receipt_sha256': hashlib.sha256(final_raw).hexdigest(),
            'read_only': True, 'sealed': True, 'reset_authorized': False, 'reset_capacity_admitted': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('policy', help='Exact JSON policy; never include secrets')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true', help='Read-only placement/content/budget checks; no lock or receipt creation')
    mode.add_argument('--verify', action='store_true', help='Read-only sealed local generation and retained receipt verification')
    parser.add_argument('--archive', help='Existing private producer tar; preserves metadata hidden by NFS')
    parser.add_argument('--archive-digest', help='Exact independently retained producer archive SHA256')
    args = parser.parse_args()
    try:
        value = policy(args.policy)
        require(not args.verify or (args.archive is None and args.archive_digest is None))
        print(json.dumps(verify(value) if args.verify else transfer(value, args.check, args.archive, args.archive_digest), sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, KeyError, IndexError, RuntimeError, RecursionError, subprocess.SubprocessError):
        print('Generation transfer refused or stopped; retain the dataset and native receipts; never replay automatically', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
