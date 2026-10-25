#!/usr/bin/env python3
"""Completion orchestration faults; disposable private paths, fake native resources."""

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import runpy
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('finish', PROJECT / 'files/build/finish-stage3-root.py')
assert SPEC is not None and SPEC.loader is not None
FIN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIN)


class FinishTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.staging = self.base / 'staging'
        self.receipts = self.base / 'receipts'
        self.identity = self.base / 'identity'
        self.parent = self.base / 'releases/release/hosts'
        for path in [self.staging, self.receipts, self.identity, self.parent]:
            path.mkdir(parents=True, mode=0o700)
        self.args = ['fixture', str(self.staging), '123', str(self.receipts), 'fixture-host',
                     'release', '456', 'sha256:' + 'a' * 64, str(self.identity)]
        self.digest = FIN.ROOT.content_digest(self.staging)
        self.materialized = {'schema': 1, 'kind': 'nest_stage3_materialized_root', 'container': 'b' * 64,
                             'path': str(self.staging), 'dataset_guid': '123', 'content_digest': self.digest}
        self.artifact = {'path': str(self.parent / 'fixture-host'), 'dataset_guid': '789', 'content_digest': self.digest}
        self.calls = []
        for manager in [patch.object(FIN.ROOT, 'BASE', self.base / 'releases'),
                        patch.object(FIN.ROOT, 'safe_ancestors'), patch.object(FIN.os, 'geteuid', return_value=0),
                        patch.object(FIN.PUB, 'filesystem', side_effect=self.filesystem),
                        patch.object(FIN.MAT, 'materialize', side_effect=self.materialize),
                        patch.object(FIN.PUB, 'publish', side_effect=self.publish),
                        patch.object(FIN.ROOT, 'check', side_effect=self.check)]:
            manager.start()
            self.addCleanup(manager.stop)

    def filesystem(self, path, readonly, guid=None, parent=False):
        self.calls.append(('filesystem', str(path), readonly, guid))
        return ['pool/parent' if parent else 'pool/staging', guid, str(path), 'yes', readonly]

    def materialize(self, *args):
        self.calls.append(('materialize',))
        FIN.retain(self.receipts / 'materialize-123.json', self.materialized)
        return self.materialized

    def publish(self, *args):
        self.calls.append(('publish',))
        return self.artifact

    def check(self, *args):
        self.calls.append(('check',))
        return self.artifact

    def test_preflight_is_read_only_and_never_inspects_or_builds_container(self):
        before = sorted(self.base.rglob('*'))
        FIN.preflight(*self.args)
        self.assertEqual(sorted(self.base.rglob('*')), before)
        self.assertFalse(any(row[0] in ['materialize', 'publish', 'check'] for row in self.calls))

    def test_finish_retains_reopens_and_binds_exact_root(self):
        self.assertEqual(FIN.finish(*self.args), {'root': self.artifact})
        path = self.receipts / 'finish-123.json'
        record = json.loads(path.read_bytes())
        self.assertEqual(record['root'], self.artifact)
        self.assertEqual(record['materialized'], self.materialized)
        self.assertEqual(record['binding']['expectations'], self.args[7])
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertLess(self.calls.index(('materialize',)), self.calls.index(('publish',)))
        self.assertLess(self.calls.index(('publish',)), self.calls.index(('check',)))

    def test_existing_partial_or_complete_attempt_refuses_before_materialize(self):
        for name in ['finish-123.started', 'finish-123.json', 'materialize-123.started', 'materialize-123.json']:
            path = self.receipts / name
            path.write_bytes(b'prior')
            with self.subTest(name=name), self.assertRaises(ValueError):
                FIN.finish(*self.args)
            self.assertEqual(path.read_bytes(), b'prior')
            path.unlink()
        self.assertNotIn(('materialize',), self.calls)

    def test_overlapping_staging_identity_or_receipts_refuse(self):
        for index, value in [(1, str(self.identity)), (3, str(self.staging)), (8, str(self.parent))]:
            args = list(self.args)
            args[index] = value
            with self.subTest(index=index), self.assertRaises(ValueError):
                FIN.preflight(*args)

    def test_wrong_parent_mode_nonempty_staging_existing_output_refuse(self):
        self.parent.chmod(0o755)
        with self.assertRaises(ValueError):
            FIN.preflight(*self.args)
        self.parent.chmod(0o700)
        (self.staging / 'keep').touch()
        with self.assertRaises(ValueError):
            FIN.preflight(*self.args)
        (self.staging / 'keep').unlink()
        (self.parent / 'fixture-host').symlink_to(self.parent / 'absent')
        with self.assertRaises(ValueError):
            FIN.preflight(*self.args)

    def test_native_placement_failure_has_no_reservation_or_copy(self):
        FIN.PUB.filesystem.side_effect = ValueError('fixture placement failure')
        with self.assertRaises(ValueError):
            FIN.finish(*self.args)
        self.assertEqual(list(self.receipts.iterdir()), [])

    def test_failed_materialization_retains_started_record_and_never_publishes(self):
        FIN.MAT.materialize.side_effect = ValueError('fixture copy failure')
        with self.assertRaises(ValueError):
            FIN.finish(*self.args)
        self.assertTrue((self.receipts / 'finish-123.started').exists())
        self.assertNotIn(('publish',), self.calls)
        self.assertFalse((self.receipts / 'finish-123.json').exists())

    def test_missing_or_changed_materialized_receipt_refuses_before_publication(self):
        FIN.MAT.materialize.side_effect = None
        FIN.MAT.materialize.return_value = self.materialized
        with self.assertRaises(OSError):
            FIN.finish(*self.args)
        self.assertNotIn(('publish',), self.calls)

    def test_changed_staging_digest_refuses_before_publication(self):
        self.materialized['content_digest'] = 'sha256:' + 'c' * 64
        with self.assertRaises(ValueError):
            FIN.finish(*self.args)
        self.assertNotIn(('publish',), self.calls)

    def test_publication_failure_retains_materialized_evidence_without_completion(self):
        FIN.PUB.publish.side_effect = ValueError('fixture publication failure')
        with self.assertRaises(ValueError):
            FIN.finish(*self.args)
        self.assertTrue((self.receipts / 'materialize-123.json').exists())
        self.assertFalse((self.receipts / 'finish-123.json').exists())

    def test_changed_publication_digest_or_native_readback_refuses(self):
        self.artifact['content_digest'] = 'sha256:' + 'd' * 64
        with self.assertRaises(ValueError):
            FIN.finish(*self.args)
        self.assertFalse((self.receipts / 'finish-123.json').exists())

    def test_failed_final_retention_never_returns_accepted_root(self):
        original = FIN.retain

        def fail(path, row):
            if path.name == 'finish-123.json':
                raise OSError('fixture fsync failure')
            return original(path, row)
        with patch.object(FIN, 'retain', side_effect=fail), self.assertRaises(OSError):
            FIN.finish(*self.args)
        self.assertIn(('check',), self.calls)
        self.assertFalse((self.receipts / 'finish-123.json').exists())

    def test_cli_static_failure_without_native_diagnostics(self):
        result = subprocess.run(['python3', str(PROJECT / 'files/build/finish-stage3-root.py'), *self.args],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, '')
        self.assertEqual(result.stderr, 'Stage 3 completion failed; retain staging, publication and receipts; no accepted root emitted\n')


class PlacementTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.storage = self.base / 'releases'
        self.staging_parent = self.base / 'staging'
        self.receipts = self.base / 'receipts'
        fixture = runpy.run_path(str(PROJECT / 'spec/files/nest_release_manifest_test.py'))
        self.expected, _ = fixture['fixture']()
        self.member = next(row for row in self.expected['members'] if row['id'] == 'stage3')
        self.identity = self.base / 'identities' / self.member['identity_reference']
        self.member['identity_root'] = str(self.identity)
        for path in [self.storage, self.staging_parent, self.receipts, self.identity]:
            path.mkdir(parents=True, mode=0o700)
        self.rows = {self.storage: ['pool/releases', '100', str(self.storage), 'yes', 'off'],
                     self.staging_parent: ['pool/staging', '200', str(self.staging_parent), 'yes', 'off']}
        self.calls = []
        self.args = [self.expected, 'stage3', '100', str(self.staging_parent), '200', str(self.receipts)]
        for manager in [patch.object(FIN.ROOT, 'BASE', self.storage),
                        patch.object(FIN.ROOT, 'safe_ancestors'), patch.object(FIN.os, 'geteuid', return_value=0),
                        patch.object(FIN.PUB, 'filesystem', side_effect=self.filesystem),
                        patch.object(FIN.PUB, 'command', side_effect=self.command)]:
            manager.start()
            self.addCleanup(manager.stop)

    def filesystem(self, path, readonly, guid=None, parent=False):
        row = self.rows[path]
        if row[4] != readonly or (guid is not None and row[1] != guid):
            raise ValueError('fixture native mismatch')
        return row

    def command(self, arguments):
        self.calls.append(arguments)
        if arguments[:2] == ['zfs', 'create']:
            mount = Path(next(arg.split('=', 1)[1] for arg in arguments if arg.startswith('mountpoint=')))
            self.rows[mount] = [arguments[-1], str(300 + len(self.rows)), str(mount), 'yes', 'off']
        if arguments[:2] == ['zfs', 'get']:
            return self.expected['release'] + '\n'
        return ''

    def test_preview_never_provisions_or_retains(self):
        before = list(self.base.rglob('*'))
        self.assertFalse(FIN.provision(*self.args)['applied'])
        self.assertEqual(self.calls, [])
        self.assertEqual(list(self.base.rglob('*')), before)

    def test_selected_children_return_existing_adapter_placement_after_native_readback(self):
        result = FIN.provision(*self.args, apply=True)
        placement = json.loads(Path(result['placement']).read_bytes())
        self.assertEqual(placement['kind'], 'nest_stage3_local_placement')
        self.assertEqual(placement['member'], 'stage3')
        self.assertEqual(placement['staging_guid'], self.rows[Path(placement['staging'])][1])
        self.assertEqual(Path(result['placement']).stat().st_mode & 0o777, 0o600)
        self.assertEqual(len([call for call in self.calls if call[:2] == ['zfs', 'create']]), 3)
        self.assertFalse(any('destroy' in call or '-p' in call for call in self.calls))
        with self.assertRaises(ValueError):
            FIN.provision(*self.args, apply=True)

    def test_wrong_selected_guid_or_overlapping_storage_refuses_before_writes(self):
        self.args[2] = '999'
        with self.assertRaises(ValueError):
            FIN.provision(*self.args, apply=True)
        self.args[2] = '100'
        self.args[3] = str(self.storage)
        with self.assertRaises(ValueError):
            FIN.provision(*self.args, apply=True)
        self.assertEqual(self.calls, [])

    def test_zfs_failure_retains_reserved_path_without_accepted_placement_or_deletion(self):
        FIN.PUB.command.side_effect = subprocess.CalledProcessError(37, 'zfs')
        with self.assertRaises(subprocess.CalledProcessError):
            FIN.provision(*self.args, apply=True)
        self.assertTrue((self.storage / self.expected['release']).is_dir())
        self.assertEqual(list(self.receipts.iterdir()), [])

    def test_existing_unowned_or_partial_parent_is_not_adopted(self):
        path = self.storage / self.expected['release']
        path.mkdir(mode=0o700)
        self.rows[path] = ['pool/wrong', '999', str(path), 'yes', 'off']
        with self.assertRaises(ValueError):
            FIN.provision(*self.args, apply=True)
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
