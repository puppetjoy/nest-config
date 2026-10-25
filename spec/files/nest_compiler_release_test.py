#!/usr/bin/env python3
"""Compiler producer contract with real Git identities and the native Ruby reader."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('compiler_release', REPO / 'scripts/nest-compiler-release.py')
assert spec is not None and spec.loader is not None
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)
BASE = 'registry.example/nest/bolt@sha256:' + 'b' * 64


class CompilerReleaseTest(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.work.cleanup)
        self.parent = Path(self.work.name)
        self.project = self.parent / 'input'
        self.project.mkdir()
        self.write('site.pp', 'include nest\n')
        self.write('hiera.yaml', 'version: 5\n')
        self.write('data/common.yaml', 'value: fixture\n')
        self.write('spec/fixture.txt', 'not served\n')
        self.write('Puppetfile', "moduledir '.modules'\n")
        self.write('.gitignore', '.modules/\n.executor-inputs.json\n')
        (self.project / 'data/private').symlink_to('../.modules/private/data')
        self.git(self.project, 'init', '-q')
        self.git(self.project, 'add', '.')
        self.git(self.project, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                 '-c', 'commit.gpgsign=false', 'commit', '-qm', 'fixture inputs')
        self.source = self.git(self.project, 'rev-parse', 'HEAD')
        modules = self.project / '.modules'
        modules.mkdir()
        self.git(self.parent, 'clone', '-q', str(self.project), str(modules / 'nest'))
        for name in ('stdlib', 'reboot', 'ruby_task_helper', 'private', 'kubecm'):
            self.write('.modules/' + name + '/manifests/init.pp', '# inert fixture\n')
        self.write('.modules/private/data/common.yaml', 'private: encrypted fixture only\n')
        self.write('.modules/nest/files/firmware/target.txt', 'not present under alias\n')
        # This committed missing leaf models the existing firmware alias. Bind
        # it in the input receipt, then prove it cannot be served as content.
        (modules / 'nest/files/firmware/missing').symlink_to('absent')
        # The real inputs checker requires nest to remain at the control SHA;
        # an untracked fixture file is nevertheless bound by its module digest.
        self.record()
        self.output = self.parent / 'release'

    def write(self, name, value):
        path = self.project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)

    @staticmethod
    def git(directory, *args):
        return subprocess.check_output(['git', '-C', str(directory), *args], stderr=subprocess.DEVNULL,
                                       text=True).strip()

    def record(self):
        row = R.inputs.observe(self.project, self.source, BASE)
        (self.project / '.executor-inputs.json').write_bytes(R.inputs.canonical(row))

    def produce(self):
        return R.produce(self.project, self.output, self.source, BASE)

    def test_projection_preserves_site_hiera_all_modules_and_private_binding(self):
        expected = self.produce()
        root = self.output / 'main'
        self.assertEqual((root / 'manifests/site.pp').read_bytes(), (self.project / 'site.pp').read_bytes())
        self.assertEqual((root / 'hiera.yaml').read_bytes(), (self.project / 'hiera.yaml').read_bytes())
        self.assertEqual((root / 'data/private/common.yaml').read_bytes(),
                         (root / '.modules/nest/data/private/common.yaml').read_bytes())
        self.assertFalse((root / '.modules/nest/spec').exists())
        self.assertFalse((root / '.modules/nest/.git').exists())
        self.assertEqual(set(p.name for p in (root / '.modules').iterdir()),
                         set(p.name for p in (self.project / '.modules').iterdir()))
        self.assertNotEqual((root / 'manifests/site.pp').stat().st_ino, (self.project / 'site.pp').stat().st_ino)
        self.assertEqual(json.loads((self.output / 'expected.json').read_bytes()), expected)
        self.assertEqual(expected['source'], self.source)
        self.assertTrue(expected['code_id'].startswith('sha256:'))
        self.assertEqual((self.output / 'executor-inputs.json').read_bytes(),
                         (self.project / '.executor-inputs.json').read_bytes())

    def test_deterministic_projection(self):
        first = self.produce()
        self.output = self.parent / 'second'
        previous = os.umask(0o077)
        try:
            self.assertEqual(self.produce(), first)
        finally:
            os.umask(previous)

    def test_untracked_control_data_is_not_an_accepted_input(self):
        self.write('data/untracked.yaml', 'not accepted\n')
        self.produce()
        self.assertFalse((self.output / 'main/data/untracked.yaml').exists())

    def test_module_drift_refuses_before_output_allocation(self):
        self.write('.modules/private/data/common.yaml', 'changed')
        with self.assertRaises(ValueError):
            self.produce()
        self.assertFalse(self.output.exists())

    def test_tracked_control_drift_refuses_before_output_allocation(self):
        self.write('site.pp', 'changed')
        with self.assertRaises(ValueError):
            self.produce()
        self.assertFalse(self.output.exists())

    def test_wrong_source_or_base_refuses(self):
        for source, base in [('c' * 40, BASE), (self.source, BASE[:-1] + 'c')]:
            with self.assertRaises(ValueError):
                R.produce(self.project, self.output, source, base)
        self.assertFalse(self.output.exists())

    def test_existing_output_never_replaced(self):
        self.produce()
        before = (self.output / 'expected.json').read_bytes()
        with self.assertRaises(FileExistsError):
            self.produce()
        self.assertEqual((self.output / 'expected.json').read_bytes(), before)

    def test_escaping_link_never_yields_receipt(self):
        (self.project / '.modules/private/escape').symlink_to('../../../../outside')
        self.record()
        with self.assertRaises(subprocess.SubprocessError):
            self.produce()
        self.assertTrue(self.output.is_dir())
        self.assertFalse((self.output / 'expected.json').exists())

    def test_writable_or_symlinked_output_parent_refuses(self):
        self.parent.chmod(0o777)
        with self.assertRaises(ValueError):
            self.produce()
        self.parent.chmod(0o700)
        (self.parent / 'alias').symlink_to(self.parent)
        with self.assertRaises(ValueError):
            R.produce(self.project, self.parent / 'alias/release', self.source, BASE)

    def test_cli_sanitizes_failure(self):
        result = subprocess.run(['python3', str(REPO / 'scripts/nest-compiler-release.py'),
                                 '--project', str(self.project), '--destination', str(self.output),
                                 '--source', 'not-a-source', '--base', BASE], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, '')
        self.assertEqual(result.stderr, 'Compiler release production unavailable\n')


if __name__ == '__main__':
    unittest.main()
