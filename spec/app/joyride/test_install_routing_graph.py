"""Synthetic installer checks; never load or publish private graph contents."""
import hashlib
from contextlib import closing
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("installer", ROOT / "files/app/joyride/install_routing_graph.py")
assert SPEC is not None and SPEC.loader is not None
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class GraphInstall(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name) / "routing"
        source = Path(directory.name) / "source.sqlite3"
        with closing(sqlite3.connect(source)) as db:
            db.execute("CREATE TABLE metadata (key TEXT, value TEXT)")
            db.executemany("INSERT INTO metadata VALUES (?, ?)", [
                ("graph_build", json.dumps(installer.BUILD)), ("unresolved_migrations", "[]")])
            db.commit()
        self.raw = source.read_bytes()
        self.sha = hashlib.sha256(self.raw).hexdigest()
        for name, value in (("SIZE", len(self.raw)), ("SHA256", self.sha)):
            stub = patch.object(installer, name, value)
            stub.start()
            self.addCleanup(stub.stop)
        environment = patch.dict(os.environ, {"RUNTIME_ENV": "test"})
        environment.start()
        self.addCleanup(environment.stop)
        self.root.mkdir()

    def download(self, raw=None):
        response = io.BytesIO(self.raw if raw is None else raw)
        opener = Mock()
        opener.open.return_value = response
        with patch.object(installer.urllib.request, "build_opener", return_value=opener), \
                patch.object(Path, "read_text", return_value="synthetic-private-reader"):
            installer.install(self.root)
        return opener

    def test_verified_atomic_install_reuse_and_retained_selection(self):
        old = self.root / "old.sqlite3"
        old.write_bytes(b"retained rollback fixture")
        (self.root / "current.sqlite3").symlink_to(old.name)
        self.download()
        self.assertEqual((self.root / "current.sqlite3").read_bytes(), self.raw)
        self.assertEqual((self.root / "previous.sqlite3").resolve(), old)
        self.assertEqual(old.read_bytes(), b"retained rollback fixture")
        self.assertEqual((self.root / "current.sqlite3").stat().st_mode & 0o777, 0o400)
        with patch.object(installer.urllib.request, "build_opener", side_effect=AssertionError("must reuse")):
            installer.install(self.root)
        self.assertEqual((self.root / "previous.sqlite3").resolve(), old)

    def test_bad_downloads_never_change_active_selection(self):
        for raw in (self.raw[:-1], self.raw + b"x", b"x" * len(self.raw)):
            with self.subTest(size=len(raw)):
                with self.assertRaises(ValueError):
                    self.download(raw)
                self.assertFalse((self.root / "current.sqlite3").exists())
                self.assertEqual(list(self.root.iterdir()), [])

    def test_capacity_gate_precedes_download_and_retains_data(self):
        with patch.object(installer.shutil, "disk_usage", return_value=Mock(free=0)):
            with self.assertRaisesRegex(ValueError, "insufficient_graph_staging_space"):
                installer.install(self.root)

    def test_streaming_bounds_dirty_page_writeback(self):
        self.raw = b"x" * (17 * 1024 * 1024)
        with patch.object(installer, "SIZE", len(self.raw)), \
                patch.object(installer, "verify"), \
                patch.object(installer.os, "fsync", wraps=os.fsync) as sync, \
                patch.object(installer.os, "posix_fadvise") as evict:
            self.download()
        self.assertEqual(evict.call_count, 1)
        self.assertGreaterEqual(sync.call_count, 3)

    def test_production_refused(self):
        with patch.dict(os.environ, {"RUNTIME_ENV": "production"}):
            with self.assertRaisesRegex(ValueError, "test_only"):
                installer.install(self.root)

    def test_unmanaged_selection_and_corrupt_retained_file_refused(self):
        current = self.root / "current.sqlite3"
        current.write_bytes(b"keep this")
        with self.assertRaisesRegex(ValueError, "retain_unmanaged"):
            installer.install(self.root)
        self.assertEqual(current.read_bytes(), b"keep this")
        current.unlink()
        destination = self.root / (installer.BUILD + "-" + self.sha + ".sqlite3")
        destination.write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "graph_size_mismatch"):
            installer.install(self.root)
        self.assertFalse(current.exists())

    def test_credential_redirect_denied(self):
        with self.assertRaisesRegex(ValueError, "redirect_denied"):
            installer.NoRedirect().redirect_request(None, None, None, None, None, None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
