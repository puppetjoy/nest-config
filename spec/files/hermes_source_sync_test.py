#!/usr/bin/env python3
"""Real Git overlay transitions; all writes stay in isolated fixture roots."""
import importlib.util
import multiprocessing
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('source_sync', ROOT / 'files/app/hermes/hermes-source-sync.py')
assert SPEC is not None and SPEC.loader is not None
manager = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manager)
LEGACY = '04fe62345b00986e6a1f4d4776296f7c1e82e1ce'
CERTIFIED = '8199b2592b3ad4efd5c7ad8fcf861cffc5514b17'


def git(repo, *args):
    return manager.git(repo, *args)


class SourceSyncTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.origin = self.root / 'origin'
        self.origin.mkdir()
        git(self.origin, 'init', '-b', 'nest')
        git(self.origin, 'config', 'user.name', 'Fixture')
        git(self.origin, 'config', 'user.email', 'fixture@example.invalid')
        git(self.origin, 'config', 'commit.gpgsign', 'false')
        (self.origin / 'tools').mkdir()
        (self.origin / 'tools/secure_browser_tool.py').write_text('legacy upstream\n')
        (self.origin / 'core.py').write_text('legacy\n')
        git(self.origin, 'add', '.')
        git(self.origin, 'commit', '-m', 'legacy')
        self.legacy = git(self.origin, 'rev-parse', 'HEAD')
        (self.origin / 'tools/secure_browser_tool.py').write_text('rolling upstream\n')
        (self.origin / 'core.py').write_text('rolling\n')
        git(self.origin, 'commit', '-am', 'rolling')
        self.target = git(self.origin, 'rev-parse', 'HEAD')
        self.repo = self.root / 'src'
        subprocess.run(['git', 'clone', '-q', str(self.origin), str(self.repo)], check=True)
        git(self.repo, 'checkout', '--detach', self.legacy)
        self.overlay()

    def overlay(self):
        (self.repo / 'tools/secure_browser_tool.py').write_bytes(b'Firefox overlay\x00\xff\n')
        (self.repo / 'tools/secure_browser_tool.py').chmod(0o640)
        (self.repo / 'tools/google_workspace_tool.py').write_text('independent managed tool\n')
        (self.repo / 'tools/agent_request_tool.py').symlink_to('../../agent-request-broker/src/tools/agent_request_tool.py')
        (self.repo / 'tools/private-local-tool.py').write_text('unknown untracked: preserve\n')
        self.files = manager.snapshot(self.repo)

    def assert_preserved(self, head):
        self.assertEqual(git(self.repo, 'rev-parse', 'HEAD'), head)
        self.assertEqual(manager.snapshot(self.repo), self.files)
        self.assertEqual((self.repo / 'tools/private-local-tool.py').read_text(), 'unknown untracked: preserve\n')
        self.assertFalse((self.repo / '.git/nest-source-transition.json').exists())
        self.assertEqual(git(self.repo, 'diff', '--cached', '--name-only'), '')

    def test_upgrade_repeat_rolling_update_and_explicit_rollback(self):
        manager.sync(self.repo, 'nest')
        self.assert_preserved(self.target)
        self.assertEqual(git(self.repo, 'symbolic-ref', 'HEAD'), 'refs/heads/nest')
        with patch.object(manager, 'uncover', side_effect=AssertionError('not idempotent')):
            manager.sync(self.repo, 'nest')
        (self.origin / 'core.py').write_text('next rolling update\n')
        git(self.origin, 'commit', '-am', 'next')
        next_head = git(self.origin, 'rev-parse', 'HEAD')
        manager.sync(self.repo, 'nest')
        self.assert_preserved(next_head)
        manager.sync(self.repo, 'nest', self.legacy)
        self.assert_preserved(self.legacy)
        self.assertEqual(git(self.repo, 'branch', '--show-current'), '')
        manager.sync(self.repo, 'nest')
        self.assert_preserved(next_head)

    def test_unknown_tracked_change_fails_without_loss(self):
        (self.repo / 'core.py').write_text('operator change\n')
        with self.assertRaisesRegex(RuntimeError, 'unmanaged tracked'):
            manager.sync(self.repo, 'nest')
        self.assert_preserved(self.legacy)
        self.assertEqual((self.repo / 'core.py').read_text(), 'operator change\n')

    def test_staged_overlay_fails_without_loss(self):
        git(self.repo, 'add', 'tools/secure_browser_tool.py')
        with self.assertRaisesRegex(RuntimeError, 'staged source changes'):
            manager.sync(self.repo, 'nest')
        self.assertEqual(manager.snapshot(self.repo), self.files)
        self.assertEqual(git(self.repo, 'rev-parse', 'HEAD'), self.legacy)
        self.assertEqual(git(self.repo, 'diff', '--cached', '--name-only'), 'tools/secure_browser_tool.py')

    def test_untracked_collision_rolls_back_without_cleaning(self):
        (self.origin / 'tools/private-local-tool.py').write_text('new upstream path\n')
        git(self.origin, 'add', '.')
        git(self.origin, 'commit', '-m', 'collision')
        with self.assertRaises(subprocess.CalledProcessError):
            manager.sync(self.repo, 'nest')
        self.assert_preserved(self.legacy)

    def test_fetch_failure_is_nonmutating(self):
        git(self.repo, 'remote', 'set-url', 'origin', str(self.root / 'missing'))
        with self.assertRaises(subprocess.CalledProcessError):
            manager.sync(self.repo, 'nest')
        self.assert_preserved(self.legacy)

    def test_existing_git_operation_fails_closed(self):
        (self.repo / '.git/MERGE_HEAD').write_text(self.target)
        with self.assertRaisesRegex(RuntimeError, 'Git operation in progress'):
            manager.sync(self.repo, 'nest')
        self.assert_preserved(self.legacy)

    def test_legacy_tag_ref_and_missing_ref(self):
        git(self.origin, 'tag', 'legacy/core', self.legacy)
        manager.sync(self.repo, 'legacy/core')
        self.assert_preserved(self.legacy)
        self.assertEqual(git(self.repo, 'branch', '--show-current'), '')
        with self.assertRaises(subprocess.CalledProcessError):
            manager.sync(self.repo, 'missing')
        self.assert_preserved(self.legacy)

    def test_restore_failure_rolls_back_original_branch_and_bytes(self):
        manager.sync(self.repo, 'nest', self.legacy)
        git(self.repo, 'checkout', '-B', 'nest', self.legacy)
        original = manager.restore
        calls = []

        def fail_once(*args):
            calls.append(1)
            if len(calls) == 1:
                raise OSError('injected restore failure')
            return original(*args)

        with patch.object(manager, 'restore', side_effect=fail_once):
            with self.assertRaisesRegex(OSError, 'injected restore failure'):
                manager.sync(self.repo, 'nest')
        self.assert_preserved(self.legacy)
        self.assertEqual(git(self.repo, 'symbolic-ref', 'HEAD'), 'refs/heads/nest')
        self.assertEqual(git(self.repo, 'rev-parse', 'nest'), self.legacy)

    def test_process_death_recovery_before_and_after_checkout_and_reattach(self):
        for phase in ('uncover', 'checkout', 'restore', 'attach'):
            with self.subTest(phase=phase):
                manager.sync(self.repo, 'nest', self.legacy)
                git(self.repo, 'checkout', '-B', 'nest', self.legacy)
                original_git = manager.git
                original_uncover = manager.uncover
                original_restore = manager.restore

                def kill_git(repo, *args):
                    result = original_git(repo, *args)
                    if (phase == 'checkout' and args == ('checkout', '--detach', self.target)
                            or phase == 'attach' and args == ('symbolic-ref', 'HEAD', 'refs/heads/nest')):
                        os._exit(86)
                    return result

                def kill_uncover(repo):
                    original_uncover(repo)
                    if phase == 'uncover':
                        os._exit(86)

                def kill_restore(repo, files):
                    original_restore(repo, files)
                    if phase == 'restore':
                        os._exit(86)

                def child():
                    manager.git = kill_git
                    manager.uncover = kill_uncover
                    manager.restore = kill_restore
                    manager.sync(self.repo, 'nest')

                process = multiprocessing.get_context('fork').Process(target=child)
                process.start()
                process.join(30)
                self.assertEqual(process.exitcode, 86)
                self.assertTrue((self.repo / '.git/nest-source-transition.json').exists())
                # A failed fetch after recovery proves recovery happened first.
                git(self.repo, 'remote', 'set-url', 'origin', str(self.root / 'missing'))
                with self.assertRaises(subprocess.CalledProcessError):
                    manager.sync(self.repo, 'nest')
                self.assert_preserved(self.legacy)
                self.assertEqual(git(self.repo, 'symbolic-ref', 'HEAD'), 'refs/heads/nest')
                git(self.repo, 'remote', 'set-url', 'origin', str(self.origin))
                manager.sync(self.repo, 'nest')
                self.assert_preserved(self.target)

    def test_diverged_rolling_update_fails_closed(self):
        manager.sync(self.repo, 'nest')
        git(self.repo, 'config', 'user.name', 'Fixture')
        git(self.repo, 'config', 'user.email', 'fixture@example.invalid')
        git(self.repo, 'config', 'commit.gpgsign', 'false')
        git(self.repo, 'commit', '--allow-empty', '-m', 'local divergence')
        local = git(self.repo, 'rev-parse', 'HEAD')
        with self.assertRaises(subprocess.CalledProcessError):
            manager.sync(self.repo, 'nest')
        self.assert_preserved(local)

    def test_overlay_allowlist_and_manifest_ordering_contract(self):
        text = (ROOT / 'manifests/app/hermes/install.pp').read_text()
        listed = re.search(r'\$source_overlays = \[(.*?)\n  \]', text, re.S).group(1)
        self.assertEqual({'tools/' + name for name in re.findall(r"'([^']+)'", listed)}, set(manager.OVERLAYS))
        resources = set(re.findall(r'file \{ "\$\{source_dir\}/(tools/[^\"]+)":', text))
        self.assertEqual(resources, set(manager.OVERLAYS))
        self.assertIn("Exec['sync_hermes_source'] -> File[$source_overlay_paths]", text)
        self.assertNotIn('reattach_hermes_source_ref', text)
        vcsrepo = re.search(r'vcsrepo \{ \$source_dir:(.*?)\n  \}', text, re.S).group(1)
        self.assertIn('ensure   => present', vcsrepo)
        self.assertNotIn('revision', vcsrepo)

    @unittest.skipUnless(os.environ.get('HERMES_SOURCE_FIXTURE'), 'optional read-only real core object source')
    def test_exact_production_core_and_current_puppet_overlay(self):
        real = self.root / 'real-src'
        subprocess.run(['git', 'clone', '-q', '--shared', '--no-checkout',
                        os.environ['HERMES_SOURCE_FIXTURE'], str(real)], check=True)
        git(real, 'checkout', '--detach', LEGACY)
        # Local fixture origin only; never fetch the installed runtime's remote.
        git(real, 'update-ref', 'refs/remotes/origin/nest', CERTIFIED)
        git(real, 'config', 'remote.origin.fetch', '+refs/heads/fixture-nest:refs/remotes/origin/nest')
        origin = self.root / 'real-origin.git'
        subprocess.run(['git', 'clone', '-q', '--bare', '--shared', str(real), str(origin)], check=True)
        git(origin, 'update-ref', 'refs/heads/fixture-nest', CERTIFIED)
        git(real, 'remote', 'set-url', 'origin', str(origin))
        for name in manager.OVERLAYS:
            path = real / name
            source = ROOT / 'files/app/hermes' / path.name
            if source.is_file():
                path.write_bytes(source.read_bytes())
        bridge = real / 'tools/firefox_ui_bridge.py'
        bridge.write_bytes((ROOT / 'files/firefox-browser/firefox-ui-bridge.py').read_bytes())
        broker = real / 'tools/agent_request_tool.py'
        if broker.exists():
            broker.unlink()
        broker.symlink_to('../../agent-request-broker/src/tools/agent_request_tool.py')
        files = manager.snapshot(real)
        manager.sync(real, 'nest')
        self.assertEqual(git(real, 'rev-parse', 'HEAD'), CERTIFIED)
        self.assertEqual(manager.snapshot(real), files)
        manager.sync(real, 'nest')
        manager.sync(real, 'nest', LEGACY)
        self.assertEqual(git(real, 'rev-parse', 'HEAD'), LEGACY)
        self.assertEqual(manager.snapshot(real), files)
        manager.sync(real, 'nest')
        self.assertEqual(git(real, 'rev-parse', 'HEAD'), CERTIFIED)
        self.assertEqual(manager.snapshot(real), files)


if __name__ == '__main__':
    unittest.main(verbosity=2)
