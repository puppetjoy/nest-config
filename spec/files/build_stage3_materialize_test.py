#!/usr/bin/env python3
"""Real two-tree assembly and rsync faults with fake Podman/ZFS; no live roots."""

import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('materialize', PROJECT / 'files/build/materialize-stage3-root.py')
assert SPEC is not None and SPEC.loader is not None
MAT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MAT)


class MaterializeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.source = self.base / 'container'
        (self.source / 'var/db/repos').mkdir(parents=True)
        (self.source / 'etc').mkdir()
        (self.source / 'etc/fixture').write_bytes(b'synthetic root fixture\n')
        (self.source / 'etc/fixture').chmod(0o600)
        os.link(self.source / 'etc/fixture', self.source / 'etc/linked')
        (self.source / 'link').symlink_to('etc/fixture')
        self.repos = self.base / 'volume'
        self.repos.mkdir()
        (self.repos / 'fixture').write_bytes(b'synthetic volume fixture\n')
        os.setxattr(self.repos / 'fixture', 'user.fixture', b'value')
        self.target = self.base / 'staging'
        self.target.mkdir()
        self.receipts = self.base / 'receipts'
        self.receipts.mkdir(mode=0o700)
        self.identity = 'a' * 64
        self.row = {'Id': self.identity, 'Name': 'fixture', 'State': {
            'Status': 'exited', 'Running': False, 'Paused': False, 'Pid': 0}, 'ExecIDs': [], 'Mounts': [
                {'Type': 'bind', 'Source': '/nest', 'Destination': '/nest'},
                {'Type': 'bind', 'Source': '/falcon', 'Destination': '/falcon'},
                {'Type': 'volume', 'Source': str(self.repos), 'Destination': '/var/db/repos', 'Name': 'fixture-frozen-repos'}]}
        self.row['GraphDriver'] = {'Name': 'overlay', 'Data': {'UpperDir': '/fixture/diff', 'LowerDir': '/fixture/base'}}
        self.vol = {'Name': 'fixture-frozen-repos', 'Driver': 'local', 'Options': {}, 'Mountpoint': str(self.repos)}
        self.commands = []
        self.sealed = False
        self.args = ['fixture', str(self.target), '123', str(self.receipts)]

    def command(self, args):
        self.commands.append(args)
        if args[:3] == ['podman', 'container', 'inspect']:
            return json.dumps([self.row])
        if args[:3] == ['podman', 'volume', 'inspect']:
            return json.dumps([self.vol])
        if args[:2] == ['podman', 'ps']:
            return self.identity + '\n'
        if args[:2] == ['podman', 'mount']:
            self.row['GraphDriver']['Data']['MergedDir'] = str(self.source)
            return str(self.source) + '\n'
        if args[0] == 'rsync':
            return subprocess.run(args, capture_output=True, text=True, check=True).stdout
        if args[:3] == ['zfs', 'set', 'readonly=on']:
            self.sealed = True
        return ''

    def filesystem(self, path, readonly, guid=None):
        self.assertEqual(path, self.target)
        self.assertEqual(guid, '123')
        self.assertEqual(readonly, 'on' if self.sealed else 'off')
        return ['pool/staging', '123', str(path), 'yes', readonly]

    def run_materialize(self, command=None):
        with patch.object(MAT.ROOT, 'safe_ancestors'), patch.object(MAT.os, 'geteuid', return_value=0), \
                patch.object(MAT.PUB, 'filesystem', side_effect=self.filesystem), \
                patch.object(MAT, 'command', side_effect=command or self.command):
            return MAT.materialize(*self.args)

    def test_exact_two_tree_copy_seal_and_private_retained_readback(self):
        source_digest = MAT.ROOT.content_digest(self.source)
        repos_digest = MAT.ROOT.content_digest(self.repos)
        result = self.run_materialize()
        self.assertEqual(MAT.ROOT.content_digest(self.source), source_digest)
        self.assertEqual(MAT.ROOT.content_digest(self.repos), repos_digest)
        self.assertEqual(MAT.ROOT.content_digest(self.target / 'var/db/repos'), repos_digest)
        self.assertEqual(result['content_digest'], MAT.ROOT.content_digest(self.target))
        output = self.receipts / 'materialize-123.json'
        self.assertEqual(json.loads(output.read_bytes()), result)
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.target / 'etc/fixture').stat().st_ino, (self.target / 'etc/linked').stat().st_ino)
        self.assertTrue(self.sealed)
        self.assertFalse(any(args[1] in ['start', 'stop', 'destroy', 'rm'] for args in self.commands if len(args) > 1))
        self.assertLess(next(i for i, args in enumerate(self.commands) if args[:2] == ['podman', 'unmount']),
                        next(i for i, args in enumerate(self.commands) if args[:2] == ['zpool', 'sync']))

    def test_inspection_ignores_only_transient_merged_mount_path(self):
        with patch.object(MAT, 'command', side_effect=self.command):
            before = MAT.inspect('fixture')
            self.command(['podman', 'mount', self.identity])
            self.assertEqual(MAT.inspect('fixture'), before)
            self.row['GraphDriver']['Data']['LowerDir'] = '/different/base'
            self.assertNotEqual(MAT.inspect('fixture'), before)

    def test_nonempty_target_refuses_without_podman_or_reservation(self):
        (self.target / 'existing').write_bytes(b'keep')
        with self.assertRaises(ValueError):
            self.run_materialize()
        self.assertEqual(self.commands, [])
        self.assertEqual(list(self.receipts.iterdir()), [])

    def test_existing_reservation_refuses_even_when_target_empty(self):
        reservation = self.receipts / 'materialize-123.started'
        reservation.write_bytes(b'prior attempt')
        with self.assertRaises(FileExistsError):
            self.run_materialize()
        self.assertFalse(any(args[:2] == ['podman', 'mount'] for args in self.commands))
        self.assertEqual(reservation.read_bytes(), b'prior attempt')

    def test_active_or_unknown_state_refuses_before_reservation(self):
        for field, value in [('Status', 'running'), ('Running', True), ('Paused', True), ('Pid', 123)]:
            old = copy.deepcopy(self.row)
            self.row['State'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.run_materialize()
            self.row = old
        self.assertEqual(list(self.receipts.iterdir()), [])

    def test_unknown_mount_or_secret_socket_or_missing_repos_refuses(self):
        for change in ['unknown', 'socket', 'missing', 'duplicate', 'wrong_source']:
            old = copy.deepcopy(self.row)
            if change in ['unknown', 'socket']:
                self.row['Mounts'].append({'Type': 'bind', 'Source': '/private',
                                           'Destination': '/secret' if change == 'unknown' else '/run/ssh-agent'})
            elif change == 'missing':
                self.row['Mounts'].pop()
            elif change == 'duplicate':
                self.row['Mounts'].append(copy.deepcopy(self.row['Mounts'][0]))
            else:
                self.row['Mounts'][-1]['Source'] = '/wrong-volume'
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.run_materialize()
            self.row = old
        self.assertEqual(list(self.receipts.iterdir()), [])

    def test_volume_plugin_and_shared_users_refuse_before_copy(self):
        self.vol['Options'] = {'type': 'nfs'}
        with self.assertRaises(ValueError):
            self.run_materialize()
        self.vol['Options'] = {}

        def shared(args):
            if args[:2] == ['podman', 'ps']:
                return self.identity + '\n' + 'b' * 64 + '\n'
            return self.command(args)
        with self.assertRaises(ValueError):
            self.run_materialize(command=shared)
        self.assertEqual(list(self.receipts.iterdir()), [])

    def test_copy_failure_keeps_reservation_and_unmounts_without_seal(self):
        def fail(args):
            if args[0] == 'rsync':
                raise subprocess.CalledProcessError(23, args, stderr='PRIVATE')
            return self.command(args)
        with self.assertRaises(subprocess.CalledProcessError):
            self.run_materialize(command=fail)
        self.assertTrue((self.receipts / 'materialize-123.started').exists())
        self.assertFalse((self.receipts / 'materialize-123.json').exists())
        self.assertIn(['podman', 'unmount', self.identity], self.commands)
        self.assertFalse(self.sealed)

    def test_hidden_repositories_replaced_without_source_mutation_or_stale_payload(self):
        (self.source / 'var/db/repos/old').write_bytes(b'old hidden repository')
        (self.source / 'var/db/repos/.hidden').write_bytes(b'hidden old metadata')
        (self.source / 'var/db/repos/stale').mkdir()
        (self.source / 'var/db/repos/stale/link').symlink_to('/not/release/payload')
        original = MAT.ROOT.content_digest(self.source)
        expected = MAT.ROOT.content_digest(self.source, repositories=self.repos)
        result = self.run_materialize()
        self.assertEqual(result['content_digest'], expected)
        self.assertEqual(MAT.ROOT.content_digest(self.source), original)
        self.assertEqual(set(os.listdir(self.target / 'var/db/repos')), {'fixture'})
        self.assertTrue(self.sealed)

    def test_assembled_digest_detects_corruption_outside_repository_subtree(self):
        calls = 0

        def corrupt(args):
            nonlocal calls
            result = self.command(args)
            if args[0] == 'rsync':
                calls += 1
                if calls == 2:
                    (self.target / 'etc/fixture').write_bytes(b'bad copy')
            return result
        with self.assertRaises(ValueError):
            self.run_materialize(command=corrupt)
        self.assertFalse(self.sealed)
        self.assertFalse((self.receipts / 'materialize-123.json').exists())

    def test_repository_directory_metadata_and_hardlinks_are_preserved(self):
        self.repos.chmod(0o750)
        os.setxattr(self.repos, 'user.fixture', b'directory metadata')
        os.link(self.repos / 'fixture', self.repos / 'linked')
        (self.repos / '.hidden').write_bytes(b'new hidden volume metadata')
        result = self.run_materialize()
        self.assertEqual(result['content_digest'], MAT.ROOT.content_digest(self.source, repositories=self.repos))
        destination = self.target / 'var/db/repos'
        self.assertEqual(destination.stat().st_mode & 0o777, 0o750)
        self.assertEqual(os.getxattr(destination, 'user.fixture'), b'directory metadata')
        self.assertEqual((destination / 'fixture').stat().st_ino, (destination / 'linked').stat().st_ino)
        self.assertEqual((destination / '.hidden').read_bytes(), b'new hidden volume metadata')

    def test_cross_tree_hardlink_loss_refuses_before_sealing(self):
        os.link(self.source / 'etc/fixture', self.repos / 'cross-tree-link')
        with self.assertRaises(ValueError):
            self.run_materialize()
        self.assertFalse(self.sealed)
        self.assertFalse((self.receipts / 'materialize-123.json').exists())

    def test_changed_target_after_sealing_never_emits_receipt(self):
        def mutate(args):
            result = self.command(args)
            if args[:3] == ['zfs', 'set', 'readonly=on']:
                (self.target / 'etc/fixture').write_bytes(b'changed at seal boundary')
            return result
        with self.assertRaises(ValueError):
            self.run_materialize(command=mutate)
        self.assertTrue(self.sealed)
        self.assertFalse((self.receipts / 'materialize-123.json').exists())

    def test_source_and_volume_mutations_during_copy_refuse(self):
        for relative in ['etc/fixture', 'var/db/repos/fixture']:
            calls = 0

            def mutate(args):
                nonlocal calls
                result = self.command(args)
                if args[0] == 'rsync':
                    calls += 1
                    if calls == 1 and relative.startswith('etc'):
                        (self.source / relative).write_bytes(b'changed')
                    elif calls == 2 and relative.startswith('var'):
                        (self.repos / 'fixture').write_bytes(b'changed')
                return result
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                self.run_materialize(command=mutate)
            self.assertFalse(self.sealed)
            # Separate fixture attempts only; production never removes reservations.
            import shutil
            shutil.rmtree(self.target)
            self.target.mkdir()
            (self.receipts / 'materialize-123.started').unlink()

    def test_unmount_flush_seal_failures_never_emit_receipt(self):
        for phase in ['unmount', 'sync', 'set']:
            def fail(args):
                if args[1] == phase:
                    raise subprocess.CalledProcessError(1, args)
                return self.command(args)
            with self.subTest(phase=phase), self.assertRaises(subprocess.CalledProcessError):
                self.run_materialize(command=fail)
            self.assertFalse((self.receipts / 'materialize-123.json').exists())
            import shutil
            shutil.rmtree(self.target)
            self.target.mkdir()
            (self.receipts / 'materialize-123.started').unlink()

    def test_submount_refuses_including_same_device_bind(self):
        mountinfo = '10 1 0:1 / ' + str(self.source / 'etc') + ' rw - overlay overlay rw\n'
        with patch.object(Path, 'read_text', return_value=mountinfo), self.assertRaises(ValueError):
            MAT.no_submounts(self.source)

    def test_cli_failure_has_no_private_diagnostic_or_stdout(self):
        result = subprocess.run(['python3', str(PROJECT / 'files/build/materialize-stage3-root.py'), *self.args],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, '')
        self.assertEqual(result.stderr, 'Stage 3 root materialization failed; retain reservation and staging root; no accepted artifact emitted\n')


if __name__ == '__main__':
    unittest.main()
