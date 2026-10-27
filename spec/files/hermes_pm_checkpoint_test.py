#!/usr/bin/env python3
"""Local Git checkpoint and exact-transaction regressions; no live installs."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

HELPER = Path(__file__).resolve().parents[2] / 'files/app/hermes/hermes-pm.py'
spec = importlib.util.spec_from_file_location('nest_pm', HELPER)
assert spec is not None and spec.loader is not None
manager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manager)


class CheckpointTests(unittest.TestCase):
    def git(self, repo, *args):
        return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.STDOUT).decode().strip()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.install = Path(self.temporary.name)
        (self.install / 'tools').mkdir()
        self.floors = {}
        for name, branch in [('src', 'nest'), ('agent-request-broker', 'main')]:
            repo = self.install / name
            repo.mkdir()
            self.git(repo, 'init', '-b', branch)
            self.git(repo, 'config', 'user.name', 'Test')
            self.git(repo, 'config', 'user.email', 'test@example.invalid')
            self.git(repo, 'config', 'commit.gpgsign', 'false')
            (repo / 'input').write_text('safe checkpoint\n')
            self.git(repo, 'add', '.')
            self.git(repo, 'commit', '-m', 'checkpoint')
            self.floors[name] = (self.git(repo, 'rev-parse', 'HEAD'),)
        self.checkpoints = patch.object(manager, 'CHECKPOINTS', self.floors)
        self.checkpoints.start()
        self.addCleanup(self.checkpoints.stop)
        self.addCleanup(patch.stopall)
        self.pm = types.SimpleNamespace(sync_venv=lambda *a, **k: None,
                                        venv_is_current=lambda **k: True)
        patch.dict(sys.modules, {'pm': self.pm}).start()
        patch.object(manager, 'dependency_inputs', return_value=object()).start()
        patch.object(manager, 'configure', return_value=self.install / 'src').start()

    def advance(self, name):
        repo = self.install / name
        (repo / 'input').write_text('rolling next version\n')
        self.git(repo, 'commit', '-am', 'rolling update')

    def test_real_rolling_refs_converge_without_head_pins(self):
        self.assertEqual(manager.sync(self.install), 0)
        first = json.loads(manager.receipt_path(self.install).read_text())
        for name in self.floors:
            self.advance(name)
        self.assertEqual(manager.sync(self.install, check=True), 1)
        self.assertEqual(manager.sync(self.install), 0)
        self.assertEqual(manager.sync(self.install, check=True), 0)
        self.assertNotEqual(first, manager.source_state(self.install))
        self.assertEqual(self.git(self.install / 'src', 'branch', '--show-current'), 'nest')
        self.assertEqual(self.git(self.install / 'agent-request-broker', 'branch', '--show-current'), 'main')

    def test_refuses_missing_checkpoint_before_core_import_or_sync(self):
        self.floors['src'] = ('f' * 40,)
        with self.assertRaisesRegex(RuntimeError, 'safe checkpoint missing'):
            manager.sync(self.install)
        manager.configure.assert_not_called()
        self.assertFalse(manager.receipt_path(self.install).exists())

    def test_refuses_broker_without_both_required_ancestors(self):
        self.floors['agent-request-broker'] += ('f' * 40,)
        with self.assertRaisesRegex(RuntimeError, 'safe checkpoint missing'):
            manager.sync(self.install)

    def test_rejects_head_movement_during_sync_without_receipt(self):
        self.pm.sync_venv = lambda *a, **k: self.advance('src')
        with self.assertRaisesRegex(RuntimeError, 'changed during PM sync'):
            manager.sync(self.install)
        self.assertFalse(manager.receipt_path(self.install).exists())

    def test_rejects_same_head_content_movement_and_stale_launch(self):
        manager.sync(self.install)
        (self.install / 'src/input').write_text('changed managed overlay\n')
        self.assertEqual(manager.sync(self.install, check=True), 1)
        with self.assertRaisesRegex(RuntimeError, 'no exact successful PM sync receipt'):
            manager.launch(self.install, ['-c', 'pass'])


if __name__ == '__main__':
    unittest.main()
