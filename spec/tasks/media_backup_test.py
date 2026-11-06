"""Exercise the recurring backup helper with real archives and fake ZFS."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import unittest
from unittest import mock
import uuid

SPEC = importlib.util.spec_from_file_location("media_backup", Path(__file__).parents[2] / "tasks/media_backup.py")
assert SPEC is not None and SPEC.loader is not None
BACKUP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BACKUP)


class MediaBackupTests(unittest.TestCase):
    def test_rejects_incomplete_and_unsafe_volume_identity_before_commands(self):
        with mock.patch.object(BACKUP, "run") as run:
            with self.assertRaises(ValueError):
                BACKUP.backup({})
            with self.assertRaises(ValueError):
                BACKUP.backup({app: "../../srv/plex" for app in BACKUP.APPS})
            run.assert_not_called()

    def test_snapshot_archive_and_restore_preserve_databases_and_symlinks(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as temp:
            root = Path(temp)
            volumes = {app: "pvc-" + str(uuid.uuid4()) for app in BACKUP.APPS}
            mounts = {BACKUP.POOL + "/" + uid: root / app for app, uid in volumes.items()}
            snapshots = []
            destroyed = []
            original_temporary_directory = tempfile.TemporaryDirectory
            real_run = BACKUP.run

            def command(argv):
                if argv[0] == "zfs":
                    if argv[1] == "list":
                        return ""
                    if argv[1] == "get":
                        prop = argv[-2]
                        return {"type": "filesystem", "logicalreferenced": "4096", "mountpoint": str(mounts[argv[-1]])}[prop]
                    if argv[1] == "snapshot":
                        snapshots.extend(argv[2:])
                        for snapshot in argv[2:]:
                            ds, name = snapshot.split("@")
                            path = mounts[ds] / ".zfs" / "snapshot" / name
                            path.mkdir(parents=True)
                            db = sqlite3.connect(path / "app.db")
                            db.execute("create table preserved (value text)")
                            db.execute("insert into preserved values ('identity preserved')")
                            db.commit()
                            db.close()
                            (path / "link").symlink_to("app.db")
                        return ""
                    if argv[1] == "destroy":
                        destroyed.append(argv[2])
                        return ""
                    self.fail("Unexpected ZFS operation")
                if argv[0] == "findmnt":
                    return "nest/crypt/backup"
                return real_run(argv)

            with mock.patch.object(BACKUP, "DEST", root / "backup"), mock.patch.object(BACKUP, "run", command), mock.patch.object(BACKUP.shutil, "disk_usage", return_value=shutil._ntuple_diskusage(10 ** 12, 0, 10 ** 12)), mock.patch.object(BACKUP.tempfile, "TemporaryDirectory", side_effect=lambda **kw: original_temporary_directory(prefix=kw.get("prefix"), dir=root)):
                result = BACKUP.backup(volumes)
            self.assertEqual(len(snapshots), 5)
            self.assertEqual(destroyed, snapshots)
            self.assertEqual(len({s.split("@")[1] for s in snapshots}), 1)
            archive = Path(result["archive"])
            self.assertEqual(archive.stat().st_mode & 0o777, 0o600)
            outer = root / "restore.tar"
            subprocess.run(["zstd", "-d", str(archive), "-o", str(outer)], check=True, capture_output=True)
            restored = root / "restored"
            restored.mkdir()
            with tarfile.open(outer) as tar:
                self.assertEqual(set(tar.getnames()), {app + ".tar" for app in BACKUP.APPS})
                tar.extractall(restored, filter="data")
            for app in BACKUP.APPS:
                target = restored / app
                target.mkdir()
                with tarfile.open(restored / (app + ".tar")) as tar:
                    tar.extractall(target, filter="data")
                self.assertTrue((target / "link").is_symlink())
                db = sqlite3.connect(target / "app.db")
                self.assertEqual(db.execute("pragma integrity_check").fetchone()[0], "ok")
                self.assertEqual(db.execute("select value from preserved").fetchone()[0], "identity preserved")
                db.close()


if __name__ == "__main__":
    unittest.main()
