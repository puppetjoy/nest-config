"""Synthetic node-local cache tests; never access live routing data."""
from contextlib import closing
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

installer = load("local_cache_installer", ROOT / "files/app/joyride/install_routing_graph.py")
cache = load("local_graph_cache", ROOT / "files/app/joyride/cache_routing_graph.py")

class LocalGraphCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.source = base / "source.sqlite3"
        with closing(sqlite3.connect(self.source)) as db, db:
            db.execute("CREATE TABLE metadata (key TEXT, value TEXT)")
            db.executemany("INSERT INTO metadata VALUES (?, ?)", [
                ("graph_build", json.dumps(installer.GRAPH_BUILD)),
                ("unresolved_migrations", "[]")])
            db.execute("CREATE TABLE routes (id INTEGER PRIMARY KEY, name TEXT)")
            db.execute("INSERT INTO routes(name) VALUES ('fixture')")
        self.raw = self.source.read_bytes()
        self.destdir = base / "cache"
        self.destdir.mkdir()
        self.destination = self.destdir / "graph.sqlite3"
        env = patch.dict(os.environ, {"RUNTIME_ENV": "test"})
        env.start()
        self.addCleanup(env.stop)
        self.pins = (patch.object(cache._installer, "SIZE", len(self.raw)),
                     patch.object(cache._installer, "SHA256", hashlib.sha256(self.raw).hexdigest()))
        for p in self.pins:
            p.start()
            self.addCleanup(p.stop)

    def test_current_selection_symlink_is_supported_without_mutating_it(self):
        selected = self.source.with_name('current.sqlite3')
        selected.symlink_to(self.source.name)
        before = os.readlink(selected)
        cache.stage(selected, self.destination)
        self.assertEqual(self.destination.read_bytes(), self.raw)
        self.assertEqual(os.readlink(selected), before)

    def test_bad_source_without_cache_is_never_published(self):
        for raw in (self.raw[:-1], self.raw + b'x', b'x' * len(self.raw)):
            self.source.write_bytes(raw)
            with self.subTest(size=len(raw)), self.assertRaises(ValueError):
                cache.stage(self.source, self.destination)
            self.assertFalse(self.destination.exists())
            self.assertEqual(list(self.destdir.iterdir()), [])

    def test_copies_and_verifies_local_atomic_readonly_result_without_touching_source(self):
        before = self.source.stat()
        cache.stage(self.source, self.destination)
        self.assertEqual(self.destination.read_bytes(), self.raw)
        self.assertEqual(self.destination.stat().st_mode & 0o777, 0o400)
        self.assertEqual(self.source.read_bytes(), self.raw)
        self.assertEqual((self.source.stat().st_ino, self.source.stat().st_mtime_ns),
                         (before.st_ino, before.st_mtime_ns))
        self.assertEqual(list(self.destdir.iterdir()), [self.destination])

    def test_bad_source_checksum_or_size_never_replaces_destination(self):
        self.destination.write_bytes(b"old")
        for raw in (self.raw[:-1], self.raw + b"x", b"x" * len(self.raw)):
            self.source.write_bytes(raw)
            with self.subTest(size=len(raw)), self.assertRaises(ValueError):
                cache.stage(self.source, self.destination)
            self.assertEqual(self.destination.read_bytes(), b"old")
            self.assertFalse(any(p.name.startswith(".graph.sqlite3-") for p in self.destdir.iterdir()))

    def test_existing_valid_destination_is_reused_and_invalid_refused(self):
        self.destination.write_bytes(self.raw)
        ino = self.destination.stat().st_ino
        cache.stage(self.source, self.destination)
        self.assertEqual(self.destination.stat().st_ino, ino)
        self.destination.write_bytes(b"invalid")
        with self.assertRaises(ValueError):
            cache.stage(self.source, self.destination)
        self.assertEqual(self.destination.read_bytes(), b"invalid")

    def test_non_test_runtime_and_symlink_destination_refused(self):
        with patch.dict(os.environ, {"RUNTIME_ENV": "production"}), self.assertRaises(ValueError):
            cache.stage(self.source, self.destination)
        self.destination.symlink_to(self.source)
        with patch.dict(os.environ, {"RUNTIME_ENV": "test"}), self.assertRaises(ValueError):
            cache.stage(self.source, self.destination)
        self.assertEqual(self.source.read_bytes(), self.raw)

if __name__ == "__main__":
    unittest.main(verbosity=2)
