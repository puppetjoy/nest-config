#!/usr/bin/env python3
"""Exercise real GNU tar/rsync metadata transfer; fake only Podman and ZFS."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('transfer', PROJECT / 'files/build/transfer-stage3-root.py')
assert SPEC is not None and SPEC.loader is not None
TRANSFER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TRANSFER)
MAT, PUB, ROOT = TRANSFER.MAT, TRANSFER.PUB, TRANSFER.ROOT


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.source = self.base / 'source'
        (self.source / 'var/db/repos').mkdir(parents=True)
        (self.source / 'etc').mkdir()
        (self.source / 'etc/file').write_bytes(b'synthetic private fixture')
        os.link(self.source / 'etc/file', self.source / 'etc/hardlink')
        (self.source / 'etc/link').symlink_to('../var/db/repos/file')
        os.mkfifo(self.source / 'etc/fifo', 0o600)
        os.utime(self.source / 'etc/file', ns=(1234567890123456789, 1234567890987654321))
        (self.source / 'var/db/repos/hidden').write_text('old image tree, not payload')
        self.repos = self.base / 'repos'
        self.repos.mkdir(mode=0o750)
        (self.repos / 'file').write_bytes(b'frozen repository fixture')
        os.link(self.repos / 'file', self.repos / 'hardlink')
        os.setxattr(self.repos / 'file', 'user.fixture', b'file metadata')
        os.setxattr(self.repos, 'user.fixture', b'directory metadata')
        (self.repos / 'link').symlink_to('file')
        self.spool = self.base / 'spool'
        self.spool.mkdir(mode=0o700)
        self.archive = self.spool / 'fixture.tar'
        self.staging = self.base / 'staging'
        self.staging.mkdir(mode=0o700)
        self.receipts = self.base / 'receipts'
        self.receipts.mkdir(mode=0o700)
        self.parent = self.base / 'releases/release/hosts'
        self.parent.mkdir(parents=True, mode=0o700)
        self.identity = self.base / 'identity'
        self.identity.mkdir(mode=0o700)
        self.values = ['fixture', str(self.staging), '123', str(self.receipts), 'fixture-host',
                       'release', '456', 'sha256:' + 'a' * 64, str(self.identity)]
        self.row = {'Id': 'b' * 64, 'Mounts': [{'Destination': '/var/db/repos', 'Source': str(self.repos)}]}
        self.sealed = False
        self.published = False
        self.calls = []
        # Native owner/mount admission is separately covered by the existing
        # root/finish tests. These fixtures run unprivileged, using only scratch.
        real_file_digest = TRANSFER.file_digest

        def fixture_digest(path):
            class Info:
                def __init__(self, info):
                    self.info = info

                def __getattr__(self, key):
                    return 0 if key == 'st_uid' else getattr(self.info, key)
            fstat, lstat = os.fstat, Path.lstat
            with patch.object(os, 'fstat', side_effect=lambda fd: Info(fstat(fd))), \
                    patch.object(Path, 'lstat', lambda path: Info(lstat(path))):
                return real_file_digest(path)

        for manager in [patch.object(ROOT, 'safe_ancestors'), patch.object(ROOT, 'BASE', self.base / 'releases'),
                        patch.object(TRANSFER.os, 'geteuid', return_value=0),
                        patch.object(TRANSFER, 'file_digest', side_effect=fixture_digest),
                        patch.object(MAT, 'inspect', return_value=self.row),
                        patch.object(MAT, 'volume', return_value=({'Name': 'fixture'}, self.repos)),
                        patch.object(MAT, 'exclusive_volume'), patch.object(MAT, 'no_submounts'),
                        patch.object(MAT, 'command', side_effect=self.command),
                        patch.object(PUB, 'filesystem', side_effect=self.filesystem),
                        patch.object(PUB, 'publish', side_effect=self.publish),
                        patch.object(ROOT, 'check', side_effect=lambda *args: self.artifact)]:
            manager.start()
            self.addCleanup(manager.stop)

    def command(self, args):
        self.calls.append(args)
        if args[:2] == ['podman', 'mount']:
            return str(self.source)
        if args[0] == 'tar':
            return subprocess.run(args, capture_output=True, text=True, check=True).stdout
        if args[:3] == ['zfs', 'set', 'readonly=on']:
            self.sealed = True
        return ''

    def filesystem(self, path, readonly, guid=None, parent=False):
        return ['pool/parent' if parent else 'pool/staging', guid, str(path), 'yes', readonly]

    def publish(self, *args):
        self.published = True
        self.assertTrue(self.sealed)
        self.artifact = {'path': str(self.parent / 'fixture-host'), 'dataset_guid': '789',
                         'content_digest': ROOT.content_digest(self.staging)}
        return self.artifact

    def export(self):
        return TRANSFER.export('fixture', str(self.archive))

    def receive(self, row):
        return TRANSFER.receive(str(self.archive), row['archive_digest'], row['content_digest'], self.values)

    def test_real_archive_roundtrip_preserves_full_root_and_repositories(self):
        expected = ROOT.content_digest(self.source, repositories=self.repos)
        row = self.export()
        self.assertEqual(row['content_digest'], expected)
        self.assertEqual(json.loads(Path(str(self.archive) + '.json').read_bytes()), row)
        result = self.receive(row)
        self.assertEqual(result['root']['content_digest'], expected)
        self.assertEqual(ROOT.content_digest(self.staging), expected)
        self.assertFalse((self.staging / 'var/db/repos/hidden').exists())
        self.assertEqual(os.readlink(self.staging / 'var/db/repos/link'), 'file')
        self.assertEqual(os.getxattr(self.staging / 'var/db/repos', 'user.fixture'), b'directory metadata')
        self.assertTrue((self.receipts / 'finish-123.json').exists())
        self.assertEqual(self.archive.stat().st_mode & 0o777, 0o600)
        self.assertFalse(any(args[0] in ['ssh', 'scp'] or 'destroy' in args for args in self.calls))

    def test_export_check_is_read_only_and_refuses_existing_partial_or_complete_bytes(self):
        before = sorted(self.base.rglob('*'))
        TRANSFER.export_check(str(self.archive))
        self.assertEqual(sorted(self.base.rglob('*')), before)
        self.assertEqual(self.calls, [])
        Path(str(self.archive) + '.started').write_text('keep')
        with self.assertRaises(ValueError):
            self.export()
        self.assertEqual(self.calls, [])

    def test_export_failure_retains_intent_without_success_and_does_not_replay(self):
        def fail(args):
            if args[0] == 'tar':
                raise subprocess.CalledProcessError(23, args)
            return self.command(args)
        with patch.object(MAT, 'command', side_effect=fail), self.assertRaises(subprocess.CalledProcessError):
            self.export()
        self.assertTrue(Path(str(self.archive) + '.started').exists())
        self.assertFalse(Path(str(self.archive) + '.json').exists())
        with self.assertRaises(ValueError):
            self.export()

    def test_changed_archive_refuses_before_extraction_or_intent(self):
        row = self.export()
        with self.archive.open('ab') as stream:
            stream.write(b'changed')
        with self.assertRaises(ValueError):
            self.receive(row)
        self.assertFalse((self.receipts / 'finish-123.started').exists())
        self.assertFalse(self.sealed or self.published)

    def test_wrong_content_or_failed_extract_keeps_partial_without_publish(self):
        row = self.export()
        wrong = dict(row, content_digest='sha256:' + 'c' * 64)
        Path(str(self.archive) + '.json').write_text(json.dumps(wrong))
        with self.assertRaises(ValueError):
            self.receive(wrong)
        self.assertTrue((self.receipts / 'finish-123.started').exists())
        self.assertFalse((self.receipts / 'finish-123.json').exists())
        self.assertFalse(self.sealed or self.published)
        with self.assertRaises(ValueError):
            self.receive(wrong)

    def test_unsafe_spool_or_symlink_refuses(self):
        self.spool.chmod(0o755)
        with self.assertRaises(ValueError):
            TRANSFER.export_check(str(self.archive))
        self.spool.chmod(0o700)
        self.archive.symlink_to(self.base / 'absent')
        with self.assertRaises(ValueError):
            TRANSFER.export_check(str(self.archive))


    def receive_fault(self, phase):
        row = self.export()

        def fail(args):
            if (phase == 'extract' and args[:2] == ['tar', '--extract']) or (phase in ['sync', 'set'] and args[1] == phase):
                raise subprocess.CalledProcessError(1, args)
            return self.command(args)
        with patch.object(MAT, 'command', side_effect=fail), self.assertRaises(subprocess.CalledProcessError):
            self.receive(row)
        self.assertTrue((self.receipts / 'finish-123.started').exists())
        self.assertFalse((self.receipts / 'finish-123.json').exists())
        self.assertFalse(self.published)

    def test_extraction_failure_keeps_intent_without_seal_or_publish(self):
        self.receive_fault('extract')
        self.assertFalse(self.sealed)

    def test_flush_failure_keeps_unaccepted_staging(self):
        self.receive_fault('sync')
        self.assertFalse(self.sealed)

    def test_seal_failure_never_publishes(self):
        self.receive_fault('set')

    def test_native_publication_failure_keeps_archive_and_started_intent(self):
        row = self.export()
        with patch.object(PUB, 'publish', side_effect=ValueError('failed publication')), self.assertRaises(ValueError):
            self.receive(row)
        self.assertTrue(self.archive.exists())
        self.assertTrue((self.receipts / 'finish-123.started').exists())
        self.assertFalse((self.receipts / 'finish-123.json').exists())


if __name__ == '__main__':
    unittest.main()
