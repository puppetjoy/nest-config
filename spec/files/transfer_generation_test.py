#!/usr/bin/env python3
"""Real rsync/atomic receipts with fake native ZFS inventories; no real datasets."""

import copy
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[2]
STAGED = tempfile.TemporaryDirectory()
for source in ('files/cli/transfer-generation.py', 'files/build/check-stage3-root.py'):
    shutil.copyfile(PROJECT / source, Path(STAGED.name) / Path(source).name)
SPEC = importlib.util.spec_from_file_location('transfer_generation', Path(STAGED.name) / 'transfer-generation.py')
assert SPEC is not None and SPEC.loader is not None
GEN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GEN)


def example():
    return {'schema': 1, 'kind': 'nest_generation_transfer', 'source': '/nest/releases/fixture/hosts/fixture-host',
            'build_release': 'fixture', 'release': 'sha256:' + 'a' * 64, 'content_digest': 'sha256:' + 'b' * 64,
            'hostname': 'fixture-host', 'host_identity_sha256': hashlib.sha256(b'c' * 32).hexdigest(),
            'pool_guid': '123', 'destination': '/var/lib/nest/generations/' + 'a' * 64,
            'destination_guid': '456', 'write_budget_bytes': 1048576, 'physical_reserve_bytes': 4096}


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.source, self.destination, self.state = [self.base / name for name in ('source', 'destination', 'state')]
        for path in (self.source, self.destination, self.state):
            path.mkdir(mode=0o700)
        for relative in ('var/db/pkg', 'usr/src/linux', 'lib/modules'):
            (self.source / relative).mkdir(parents=True)
        (self.source / 'private').write_bytes(b'fixture only, never a real key\n')
        (self.source / 'private').chmod(0o600)
        os.link(self.source / 'private', self.source / 'hardlink')
        (self.source / 'symlink').symlink_to('private')
        os.setxattr(self.source / 'private', 'user.fixture', b'fixture attribute')
        self.value = dict(example(), source=str(self.source), destination=str(self.destination),
                          content_digest=GEN.ROOT.content_digest(self.source))
        self.observed = {'dataset': 'pool/crypt/generations/fixture', 'creation_txg': '789',
                         'state_dataset': 'pool/crypt/nest-updates', 'state_guid': '800',
                         'current': 'pool/crypt/ROOT/A', 'boot_id': '1' * 36, 'source_mount': {'fixture': 'readonly'}}
        self.capacity = {'apparent_bytes': 1000, 'available_bytes': 10000000, 'physical_free_bytes': 10000000}
        self.commands = []
        self.sealed = False
        self.patches = [patch.object(GEN, 'STATE', self.state),
                        patch.object(GEN, 'identity', side_effect=self.identity),
                        patch.object(GEN, 'admission', return_value=self.capacity),
                        patch.object(GEN, 'command', side_effect=self.command)]
        for manager in self.patches:
            manager.start()
            self.addCleanup(manager.stop)

    def identity(self, value, writable, local=False):
        self.assertEqual(writable, not self.sealed)
        return {key: copy.deepcopy(content) for key, content in self.observed.items() if not local or key != 'source_mount'}

    def command(self, args, timeout=60):
        self.commands.append(args)
        if args[0] == 'rsync':
            return subprocess.run(args, capture_output=True, text=True, check=True).stdout
        if args[:2] == ['zfs', 'set']:
            self.sealed = True
        return ''

    def started(self):
        return self.state / 'generation-456.started'

    def completed(self):
        return self.state / 'generation-456.complete'

    def test_real_transfer_metadata_content_and_atomic_receipt(self):
        result = GEN.transfer(self.value)
        self.assertTrue(result['sealed'])
        self.assertFalse(result['reset_authorized'])
        self.assertEqual(GEN.ROOT.content_digest(self.destination), self.value['content_digest'])
        self.assertEqual((self.destination / 'private').stat().st_ino, (self.destination / 'hardlink').stat().st_ino)
        self.assertEqual(os.getxattr(self.destination / 'private', 'user.fixture'), b'fixture attribute')
        self.assertEqual(json.loads(self.completed().read_bytes()), result)
        self.assertFalse(json.loads(self.started().read_bytes())['sealed'])
        self.assertEqual(self.completed().stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.completed().stat().st_nlink, 1)
        self.assertFalse(list(self.state.glob('.generation-*')))
        self.assertEqual([args[0] for args in self.commands], ['rsync', 'zpool', 'zfs'])
        self.assertIn('org.nest:release=' + self.value['release'], self.commands[-1])
        self.assertIn('readonly=on', self.commands[-1])
        self.assertNotIn('--delete', self.commands[0])

    def test_verify_local_seal_after_boot_change_without_publication_or_writes(self):
        transferred = GEN.transfer(self.value)
        self.commands.clear()
        shutil.rmtree(self.source)
        (self.state / '.lock').unlink()
        self.observed.update(current='pool/crypt/ROOT/B', boot_id='2' * 36)
        before = {path.name: path.read_bytes() for path in self.state.iterdir()}
        with patch.object(GEN, 'admission', side_effect=AssertionError('No transfer capacity probe')):
            result = GEN.verify(self.value)
        self.assertTrue(result['read_only'] and result['sealed'])
        self.assertFalse(result['reset_authorized'] or result['reset_capacity_admitted'])
        self.assertEqual(result['generation']['current'], 'pool/crypt/ROOT/B')
        self.assertEqual(result['generation']['boot_id'], '2' * 36)
        self.assertNotIn('source_mount', result['generation'])
        self.assertEqual(result['transfer_receipt_sha256'], hashlib.sha256(GEN.ROOT.canonical(transferred)).hexdigest())
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.state.iterdir()})
        self.assertEqual(self.commands, [])

    def test_verify_refuses_incomplete_or_changed_receipts(self):
        GEN.transfer(self.value)
        for path in (self.started(), self.completed()):
            original = path.read_bytes()
            for content in (b'', b'{}\n', b'x' * 32769,
                            GEN.ROOT.canonical(dict(json.loads(original), policy_sha256='0' * 64)),
                            original.replace(b'"schema":1', b'"schema":true')):
                with self.subTest(path=path.name, content=content[:30]):
                    path.write_bytes(content)
                    with self.assertRaises((ValueError, json.JSONDecodeError)):
                        GEN.verify(self.value)
            path.write_bytes(original)
            path.unlink()
            with self.assertRaises(FileNotFoundError):
                GEN.verify(self.value)
            path.write_bytes(original)
            path.chmod(0o600)

    def test_verify_observation_does_not_take_or_break_busy_transaction_lock(self):
        GEN.transfer(self.value)
        descriptor = os.open(self.state / '.lock', os.O_RDWR)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            before = os.fstat(descriptor).st_ino
            self.assertTrue(GEN.verify(self.value)['read_only'])
            self.assertEqual((self.state / '.lock').stat().st_ino, before)
        finally:
            os.close(descriptor)

    def test_verify_refuses_symlink_hardlink_fifo_and_unsafe_receipt_mode(self):
        GEN.transfer(self.value)
        original = self.completed().read_bytes()
        self.completed().chmod(0o644)
        with self.assertRaises(ValueError):
            GEN.verify(self.value)
        self.completed().unlink()
        self.completed().symlink_to(self.started())
        with self.assertRaises(OSError):
            GEN.verify(self.value)
        self.completed().unlink()
        os.link(self.started(), self.completed())
        with self.assertRaises(ValueError):
            GEN.verify(self.value)
        self.completed().unlink()
        os.mkfifo(self.completed(), 0o600)
        with self.assertRaises(ValueError):
            GEN.verify(self.value)
        self.completed().unlink()
        self.completed().write_bytes(original)

    def test_verify_refuses_corrupted_sealed_bytes(self):
        GEN.transfer(self.value)
        (self.destination / 'private').write_bytes(b'corrupt')
        with self.assertRaises(ValueError):
            GEN.verify(self.value)

    def test_verify_refuses_changed_native_identity_and_during_read(self):
        GEN.transfer(self.value)
        original = copy.deepcopy(self.observed)
        for key in ('dataset', 'creation_txg', 'state_dataset', 'state_guid'):
            self.observed[key] = 'changed'
            with self.subTest(key=key), self.assertRaises(ValueError):
                GEN.verify(self.value)
            self.observed = copy.deepcopy(original)
        observed = self.identity(self.value, False, local=True)
        with patch.object(GEN, 'identity', side_effect=[observed, dict(observed, boot_id='changed')]), self.assertRaises(ValueError):
            GEN.verify(self.value)

    def test_verify_refuses_receipt_change_during_content_check(self):
        GEN.transfer(self.value)
        digest = GEN.ROOT.content_digest
        def mutate(path):
            self.completed().write_bytes(b'{}\n')
            return digest(path)
        with patch.object(GEN.ROOT, 'content_digest', side_effect=mutate), self.assertRaises(ValueError):
            GEN.verify(self.value)

    def test_check_creates_no_lock_receipt_or_copy(self):
        result = GEN.transfer(self.value, check=True)
        self.assertTrue(result['read_only'])
        self.assertFalse(result['sealed'])
        self.assertEqual(list(self.state.iterdir()), [])
        self.assertEqual(list(self.destination.iterdir()), [])
        self.assertEqual(self.commands, [])

    def test_bad_digest_stops_before_lock_or_copy(self):
        self.value['content_digest'] = 'sha256:' + '0' * 64
        with self.assertRaises(ValueError):
            GEN.transfer(self.value)
        self.assertEqual(list(self.state.iterdir()), [])
        self.assertEqual(self.commands, [])

    def test_nonempty_destination_never_deleted(self):
        (self.destination / 'keep').write_bytes(b'keep')
        with self.assertRaises(ValueError):
            GEN.transfer(self.value)
        self.assertEqual((self.destination / 'keep').read_bytes(), b'keep')
        self.assertEqual(self.commands, [])

    def test_existing_reservation_including_dangling_symlink_refuses(self):
        for dangling in (False, True):
            with self.subTest(dangling=dangling):
                self.started().symlink_to('absent') if dangling else self.started().write_bytes(b'interrupted')
                with self.assertRaises(ValueError):
                    GEN.transfer(self.value)
                self.started().unlink()
        self.assertEqual(self.commands, [])

    def test_native_copy_flush_or_seal_failure_keeps_started_and_no_completion(self):
        for operation in ('rsync', 'zpool', 'zfs'):
            with self.subTest(operation=operation):
                def fail(args, timeout=60):
                    if args[0] == operation:
                        raise subprocess.CalledProcessError(17, args, stderr='PRIVATE NATIVE DIAGNOSTIC')
                    return self.command(args, timeout)
                with patch.object(GEN, 'command', side_effect=fail), self.assertRaises(subprocess.CalledProcessError):
                    GEN.transfer(self.value)
                self.assertTrue(self.started().exists())
                self.assertFalse(self.completed().exists())
                # A retry cannot auto-recopy a partially materialized generation.
                with self.assertRaises(ValueError):
                    GEN.transfer(self.value)
                self.started().unlink()
                for path in self.destination.iterdir():
                    shutil.rmtree(path) if path.is_dir() and not path.is_symlink() else path.unlink()

    def test_changed_identity_under_lock_stops_before_reservation(self):
        observed = copy.deepcopy(self.observed)
        with patch.object(GEN, 'identity', side_effect=[observed, observed, dict(observed, state_guid='999')]), self.assertRaises(ValueError):
            GEN.transfer(self.value)
        self.assertFalse(self.started().exists())
        self.assertEqual(self.commands, [])

    def test_changed_source_after_copy_never_seals(self):
        def mutate(args, timeout=60):
            output = self.command(args, timeout)
            if args[0] == 'rsync':
                (self.source / 'private').write_bytes(b'changed')
            return output
        with patch.object(GEN, 'command', side_effect=mutate), self.assertRaises(ValueError):
            GEN.transfer(self.value)
        self.assertFalse(self.sealed)
        self.assertTrue(self.started().exists())
        self.assertFalse(self.completed().exists())

    def test_corrupt_copy_never_seals(self):
        def corrupt(args, timeout=60):
            output = self.command(args, timeout)
            if args[0] == 'rsync':
                (self.destination / 'private').write_bytes(b'corrupt')
            return output
        with patch.object(GEN, 'command', side_effect=corrupt), self.assertRaises(ValueError):
            GEN.transfer(self.value)
        self.assertFalse(self.sealed)
        self.assertFalse(self.completed().exists())

    def test_escaping_required_kernel_path_has_no_accepted_receipt(self):
        shutil.rmtree(self.source / 'usr/src/linux')
        (self.source / 'usr/src/linux').symlink_to('/usr')
        self.value['content_digest'] = GEN.ROOT.content_digest(self.source)
        with self.assertRaises(ValueError):
            GEN.transfer(self.value)
        self.assertFalse(self.sealed)
        self.assertFalse(self.completed().exists())
        self.assertFalse(self.started().exists())
        self.assertEqual(self.commands, [])

    def test_real_flock_contention_does_not_replace_native_lock(self):
        descriptor = os.open(self.state / '.lock', os.O_RDWR | os.O_CREAT, 0o600)
        try:
            before = os.fstat(descriptor).st_ino
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                GEN.transfer(self.value)
            self.assertEqual((self.state / '.lock').stat().st_ino, before)
            self.assertFalse(self.started().exists())
            self.assertEqual(self.commands, [])
        finally:
            os.close(descriptor)

    def test_atomic_receipt_refuses_clobber(self):
        GEN.retain(self.started(), {'first': True})
        with self.assertRaises(FileExistsError):
            GEN.retain(self.started(), {'second': True})
        self.assertEqual(json.loads(self.started().read_bytes()), {'first': True})
        self.assertFalse(list(self.state.glob('.generation-*')))

    def test_receipt_failure_before_copy_stops_native_effects(self):
        with patch.object(GEN.os, 'link', side_effect=OSError('fixture link failure')), self.assertRaises(OSError):
            GEN.transfer(self.value)
        self.assertEqual(self.commands, [])
        self.assertFalse(self.started().exists())


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.value = example()
        self.state = 'pool/crypt/nest-updates'
        self.dataset = 'pool/crypt/generations/fixture'
        self.rows = [{'target': '/', 'source': 'pool/crypt/ROOT/A', 'fstype': 'zfs', 'options': 'rw'},
                     {'target': str(GEN.STATE), 'source': self.state, 'fstype': 'zfs', 'options': 'rw'},
                     {'target': self.value['destination'], 'source': self.dataset, 'fstype': 'zfs', 'options': 'rw'},
                     {'target': '/nest/releases', 'source': 'server:/releases', 'fstype': 'nfs4', 'options': 'ro'}]
        self.properties = {'guid': '456', 'createtxg': '789', 'origin': '-', 'exec': 'off',
                           'setuid': 'off', 'devices': 'off', 'canmount': 'on'}
        self.state_properties = {'guid': '800', 'canmount': 'noauto', 'org.nest:host-id': 'c' * 32}
        self.pool_identity = 'c' * 32
        self.calls = []

    def property_value(self, dataset, name):
        if dataset == 'pool':
            return '-'  # A pool user property is not a root-dataset property.
        if name == 'mountpoint':
            return str(GEN.STATE) if dataset == self.state else self.value['destination']
        if name == 'readonly':
            return 'off'
        if dataset == self.state:
            return self.state_properties.get(name, '-')
        return self.properties.get(name, '-')

    def command(self, args, timeout=60):
        self.calls.append(args)
        if args[0] == 'zpool':
            return self.pool_identity if args[-2:] == ['org.nest:host-id', 'pool'] else '123'
        if args[:3] == ['zfs', 'list', '-H']:
            return '' if 'snapshot' in args else args[-1]
        raise AssertionError(args)

    def read(self, path, *args, **kwargs):
        return 'c' * 32 if str(path) == '/etc/machine-id' else '11111111-2222-3333-4444-555555555555'

    def run_identity(self, writable=True, local=False):
        with patch.object(GEN.os, 'geteuid', return_value=0), patch.object(GEN.socket, 'gethostname', return_value='fixture-host'), \
                patch.object(GEN.Path, 'read_text', new=lambda path: self.read(path)), patch.object(GEN.ROOT, 'safe_ancestors'), \
                patch.object(GEN.Path, 'stat', return_value=type('Info', (), {'st_mode': 0o40700})()), \
                patch.object(GEN, 'mounts', return_value=self.rows), \
                patch.object(GEN, 'property_value', side_effect=self.property_value), patch.object(GEN, 'command', side_effect=self.command):
            return GEN.identity(self.value, writable, local=local)

    def test_sealed_local_identity_has_no_publication_dependency(self):
        self.rows = self.rows[:3]
        self.rows[2]['options'] = 'ro'
        original = self.property_value
        sealed = {'org.nest:host': self.value['hostname'], 'org.nest:release': self.value['release'],
                  'org.nest:build-release': self.value['build_release'], 'org.nest:content-digest': self.value['content_digest'],
                  'readonly': 'on'}
        def properties(dataset, name):
            return sealed[name] if dataset == self.dataset and name in sealed else original(dataset, name)
        self.property_value = properties
        result = self.run_identity(writable=False, local=True)
        self.assertNotIn('source_mount', result)
        self.assertEqual(result['dataset'], self.dataset)
        with self.assertRaises(ValueError):
            self.run_identity(writable=False, local=False)
        self.rows[2]['options'] = 'rw'
        with self.assertRaises(ValueError):
            self.run_identity(writable=False, local=True)

    def test_native_host_pool_state_source_and_destination_binding(self):
        result = self.run_identity()
        self.assertEqual(result['dataset'], self.dataset)
        self.assertEqual(result['state_guid'], '800')
        self.assertEqual(result['creation_txg'], '789')
        self.assertEqual(result['current'], 'pool/crypt/ROOT/A')
        self.assertFalse(any(args[1] in ('create', 'set', 'destroy', 'mount') for args in self.calls))

    def test_changed_host_pool_or_generation_guid_refuses(self):
        for key, changed in [('hostname', 'other'), ('host_identity_sha256', '0' * 64),
                             ('pool_guid', '999'), ('destination_guid', '999')]:
            previous = self.value[key]
            self.value[key] = changed
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.run_identity()
            self.value[key] = previous

    def test_pool_identity_uses_pool_property_and_refuses_missing_or_changed_binding(self):
        self.run_identity()
        self.assertIn(['zpool', 'get', '-Hp', '-o', 'value', 'org.nest:host-id', 'pool'], self.calls)
        for identity in ('-', 'd' * 32):
            self.pool_identity = identity
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                self.run_identity()

    def test_state_requires_explicit_host_binding_and_managed_mount_policy(self):
        for key, changed in [('org.nest:host-id', '-'), ('org.nest:host-id', 'd' * 32),
                             ('canmount', 'on'), ('canmount', 'off')]:
            original = self.state_properties[key]
            self.state_properties[key] = changed
            with self.subTest(key=key, changed=changed), self.assertRaises(ValueError):
                self.run_identity()
            self.state_properties[key] = original

    def test_state_and_generation_reject_alias_mounts(self):
        for index in (1, 2):
            self.rows.append(dict(self.rows[index], target='/unexpected-alias'))
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.run_identity()
            self.rows.pop()

    def test_existing_origin_release_or_unsafe_execution_properties_refuse(self):
        for key, changed in [('origin', 'pool/old@snap'), ('org.nest:release', self.value['release']),
                             ('canmount', 'noauto'), ('exec', 'on'), ('devices', 'on'), ('createtxg', '0')]:
            previous = self.properties.get(key, '-')
            self.properties[key] = changed
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.run_identity()
            self.properties[key] = previous

    def test_cross_pool_root_tree_stacked_or_writable_source_refuses(self):
        for index, change in [(1, {'source': 'other/state'}), (2, {'source': 'pool/crypt/ROOT/generation'}),
                              (3, {'options': 'rw'})]:
            original = self.rows[index]
            self.rows[index] = dict(original, **change)
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.run_identity()
            self.rows[index] = original
        self.rows.append(self.rows[2])
        with self.assertRaises(ValueError):
            self.run_identity()


class ContractTests(unittest.TestCase):
    def test_strict_policy_and_duplicate_keys(self):
        original = example()
        self.assertEqual(GEN.policy(json.dumps(original)), original)
        for key, value in [('schema', True), ('kind', 'other'), ('source', '/nest/hosts/fixture-host'),
                           ('release', 'sha256:' + 'A' * 64), ('destination', '/var/log'),
                           ('write_budget_bytes', True), ('write_budget_bytes', 0), ('physical_reserve_bytes', -1),
                           ('hostname', '../host'), ('destination_guid', '0'), ('unknown', 'field')]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                GEN.policy(json.dumps(dict(original, **{key: value})))
        raw = json.dumps(original)
        with self.assertRaises(ValueError):
            GEN.policy('{"schema":1,' + raw[1:])

    def test_source_mount_rejects_writable_stacked_or_submounts(self):
        root = Path('/nest/releases/fixture/hosts/fixture-host')
        good = {'source': 'server:/releases', 'target': '/nest/releases', 'fstype': 'nfs4', 'options': 'ro,relatime'}
        self.assertEqual(GEN.source_mount(root, [good]), good)
        for rows in ([dict(good, options='rw')], [good, good], [dict(good, fstype='tmpfs')],
                     [good, dict(good, target=str(root / 'hidden'))]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                GEN.source_mount(root, rows)

    def test_exact_mount_and_native_filesystem_closure(self):
        root = Path('/var/lib/nest/generations/fixture')
        row = {'source': 'pool/generation', 'target': str(root), 'fstype': 'zfs', 'options': 'rw'}
        properties = {'mountpoint': str(root), 'readonly': 'off'}
        with patch.object(GEN, 'property_value', side_effect=lambda ds, name: properties[name]), \
                patch.object(GEN, 'command', return_value='pool/generation'):
            self.assertEqual(GEN.exact(root, [row], True), 'pool/generation')
            for rows in ([row, row], [dict(row, fstype='nfs')], [dict(row, options='ro')],
                         [row, dict(row, target=str(root / 'child'))]):
                with self.subTest(rows=rows), self.assertRaises(ValueError):
                    GEN.exact(root, rows, True)
            with patch.object(GEN, 'command', return_value='pool/generation\npool/generation/child'), self.assertRaises(ValueError):
                GEN.exact(root, [row], True)

    def test_transfer_budget_has_independent_apparent_logical_and_physical_gates(self):
        value = example()
        observed = {'dataset': 'pool/generation'}
        def run(args, timeout=60):
            return '2000000' if args[0] == 'zpool' else '1000\t' + value['source']
        with patch.object(GEN, 'property_value', return_value='2000000'), patch.object(GEN, 'command', side_effect=run):
            self.assertEqual(GEN.admission(value, observed)['apparent_bytes'], 1000)
            for changed in (dict(value, write_budget_bytes=999), dict(value, write_budget_bytes=3000000),
                            dict(value, physical_reserve_bytes=2000000)):
                with self.assertRaises(ValueError):
                    GEN.admission(changed, observed)
            with patch.object(GEN, 'property_value', return_value='999'), self.assertRaises(ValueError):
                GEN.admission(value, observed)
            with patch.object(GEN, 'command', return_value='unknown'), self.assertRaises(ValueError):
                GEN.admission(value, observed)

    def test_cli_sanitized_failure_has_no_stdout_or_native_errors(self):
        result = subprocess.run(['python3', str(Path(STAGED.name) / 'transfer-generation.py'), '{bad'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, '')
        self.assertEqual(result.stderr, 'Generation transfer refused or stopped; retain the dataset and native receipts; never replay automatically\n')

    def test_cli_verify_has_sanitized_failure_and_refuses_conflicting_modes(self):
        helper = str(Path(STAGED.name) / 'transfer-generation.py')
        result = subprocess.run(['python3', helper, '{bad', '--verify'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, '')
        self.assertNotIn('Traceback', result.stderr)
        result = subprocess.run(['python3', helper, json.dumps(example()), '--verify', '--check'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, '')


if __name__ == '__main__':
    unittest.main()
