"""Regression fixtures for build receipts and glab runtime/managed ownership."""

import importlib.util

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'files/app/hermes' / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILD = load('build_state', 'hermes-build-state.py')
GLAB = load('glab_config', 'manage-glab-config.py')


class BuildStateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        for name in ('ui-tui', 'web'):
            (self.root / name / 'node_modules').mkdir(parents=True)
        (self.root / 'node_modules').mkdir()
        for name, text in {
            '.gitignore': 'node_modules/\ndist/\nweb_dist/\n*.tsbuildinfo\n',
            'package.json': '{}', 'package-lock.json': '{}',
            'ui-tui/src/entry.tsx': 'export default 1',
            'ui-tui/package.json': '{}', 'ui-tui/scripts/build.mjs': 'build()',
            'web/src/main.tsx': 'render()', 'web/package.json': '{}',
            'apps/shared/src/index.ts': 'export default 2',
            'ui-tui/dist/entry.js': 'bundle without obsolete UI strings',
            'hermes_cli/web_dist/index.html': '<script src="/assets/main.js"></script>',
            'hermes_cli/web_dist/assets/main.js': 'minified()',
            'hermes_cli/web_dist/assets/lazy.js': 'lazy()',
        }.items():
            self.write(name, text)
        subprocess.run(['git', '-C', str(self.root), 'add', '.'], check=True)
        original = subprocess.check_output

        def output(command, **kwargs):
            if command[0] == 'node':
                return 'v26.0.0\n' if command[1] == '--version' else '11.17.0\n'
            return original(command, **kwargs)

        mock = patch.object(BUILD.subprocess, 'check_output', side_effect=output)
        mock.start()
        self.addCleanup(mock.stop)

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def snapshot(self, kind='tui'):
        return BUILD.snapshot(self.root, kind, Path('npm-cli.js'))

    def test_system_npm_guard_invokes_system_npm_not_node(self):
        with patch.object(BUILD.subprocess, 'check_output', return_value='11.17.0\n') as check_output:
            self.assertEqual(BUILD.npm_version(Path('/usr/bin/npm')), '11.17.0')
        check_output.assert_called_once_with(['/usr/bin/npm', '--version'], text=True)

    def test_pm_npm_guard_invokes_node_with_private_cli(self):
        with patch.object(BUILD.subprocess, 'check_output', return_value='11.17.0\n') as check_output:
            self.assertEqual(BUILD.npm_version(Path('/opt/hermes-agent/npm-cli.js')), '11.17.0')
        check_output.assert_called_once_with(['node', '/opt/hermes-agent/npm-cli.js', '--version'], text=True)

    def test_unchanged_second_run_and_timestamps(self):
        for kind in ('tui', 'web'):
            before = self.snapshot(kind)
            for path in self.root.rglob('*'):
                os.utime(path, None)
            self.assertEqual(before, self.snapshot(kind))

    def test_relevant_source_shared_dependency_and_lock_changes(self):
        for name in ('ui-tui/src/entry.tsx', 'apps/shared/src/index.ts',
                     'package-lock.json', 'ui-tui/scripts/build.mjs', 'web/package.json'):
            before = self.snapshot()
            self.write(name, 'changed ' + name)
            self.assertNotEqual(before, self.snapshot(), name)

    def test_added_untracked_source_and_deleted_tracked_source(self):
        before = self.snapshot()
        self.write('ui-tui/src/new.ts', 'new input')
        self.assertNotEqual(before, self.snapshot())
        (self.root / 'ui-tui/src/entry.tsx').unlink()
        with self.assertRaises(FileNotFoundError):
            self.snapshot()

    def test_unrelated_python_change_does_not_rebuild(self):
        before = self.snapshot()
        self.write('tools/runtime.py', 'unrelated')
        self.assertEqual(before, self.snapshot())

    def test_generated_build_info_does_not_invalidate_inputs(self):
        before = self.snapshot('web')
        self.write('web/tsconfig.app.tsbuildinfo', 'generated')
        self.assertEqual(before, self.snapshot('web'))

    def test_output_corruption_and_missing_lazy_chunk(self):
        before = self.snapshot('web')
        (self.root / 'hermes_cli/web_dist/assets/lazy.js').unlink()
        self.assertNotEqual(before, self.snapshot('web'))
        before = self.snapshot()
        self.write('ui-tui/dist/entry.js', 'corrupt')
        self.assertNotEqual(before, self.snapshot())

    def test_missing_or_empty_required_outputs_fail(self):
        for name, kind in (('ui-tui/dist/entry.js', 'tui'),
                           ('hermes_cli/web_dist/index.html', 'web')):
            self.write(name, '')
            with self.assertRaises(ValueError):
                self.snapshot(kind)

    def test_missing_dependencies_fail(self):
        shutil.rmtree(self.root / 'ui-tui/node_modules')
        with self.assertRaises(ValueError):
            self.snapshot()

    def test_toolchain_change_invalidates_receipt(self):
        before = self.snapshot()
        original = BUILD.subprocess.check_output
        with patch.object(BUILD.subprocess, 'check_output', side_effect=lambda command, **kwargs:
                          '11.18.0' if command[0] == 'node' and command[1] != '--version'
                          else original(command, **kwargs)):
            self.assertNotEqual(before, self.snapshot())

    def test_receipt_cli_record_then_check_and_corrupt_state(self):
        state = self.root / 'receipt.json'
        args = ['guard', 'record', str(self.root), 'web', str(state), 'npm-cli.js']
        with patch('sys.argv', args):
            self.assertEqual(0, BUILD.main())
        args[1] = 'check'
        with patch('sys.argv', args):
            self.assertEqual(0, BUILD.main())
            state.write_text('invalid')
            self.assertEqual(1, BUILD.main())


class GlabStateTest(unittest.TestCase):
    def test_runtime_receipt_is_preserved_without_policy_change(self):
        managed = {'hosts': {'example.test': {'token': 'fixture'}}, 'editor': None}
        current = dict(managed, last_seen_version='fixture-version')
        self.assertEqual(current, GLAB.reconcile(current, managed))
        current['last_seen_version'] = 'new-fixture-version'
        self.assertEqual(current, GLAB.reconcile(current, managed))

    def test_real_policy_and_auth_changes_are_not_hidden(self):
        current = {'hosts': {'old.test': {'token': 'old-fixture'}}, 'last_seen_version': 'fixture'}
        managed = {'hosts': {'new.test': {'token': 'new-fixture'}}, 'no_prompt': True}
        desired = GLAB.reconcile(current, managed)
        self.assertNotEqual(current, desired)
        self.assertEqual(desired['hosts'], managed['hosts'])
        self.assertEqual(desired['last_seen_version'], 'fixture')
        self.assertEqual(desired, GLAB.reconcile(desired, managed))


if __name__ == '__main__':
    unittest.main()
