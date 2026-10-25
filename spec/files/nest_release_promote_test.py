#!/usr/bin/env python3
"""Real pointer files and mocked registry reads/copies; no production writes."""

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('promotion', ROOT / 'scripts/nest-release-promote.py')
assert SPEC is not None and SPEC.loader is not None
P = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(P)
FIX = importlib.util.spec_from_file_location('release_fixture', ROOT / 'spec/files/nest_release_manifest_test.py')
assert FIX is not None and FIX.loader is not None
F = importlib.util.module_from_spec(FIX)
FIX.loader.exec_module(F)


class PromotionTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        expected, candidate = F.fixture()
        self.previous = P.R['validate'](expected, candidate)
        self.manifest = copy.deepcopy(self.previous)
        for output in self.manifest['candidate']['outputs']:
            if output['member']['stage'] != 'stage3':
                output['artifacts'] = {role: ref.split('@')[0] + '@sha256:' + format(100 + index, '064x')
                                       for index, (role, ref) in enumerate(output['artifacts'].items())}
        old = P.images(self.previous)
        self.new = P.images(self.manifest)
        aliases = [dict(member=key[0], artifact=key[1], alias=ref.split('@')[0] + ':' + key[0] + '-' + key[1], old=old[key])
                   for key, ref in self.new.items()]
        self.plan = dict(schema=1, kind='nest_release_promotion', manifest_digest=P.R['digest'](self.manifest),
                         previous_digest=P.R['digest'](self.previous), aliases=aliases)
        self.pointer = self.directory / 'current.json'
        self.pointer.write_bytes(P.R['canonical'](self.previous))
        self.registry = {ref: ref.split('@')[1] for ref in list(old.values()) + list(self.new.values())}
        self.registry.update({row['alias']: row['old'].split('@')[1] for row in aliases})
        self.copies = []
        for manager in (patch.object(P, 'inspect', side_effect=self.registry.__getitem__),
                        patch.object(P, 'roots'), patch.object(P, 'command', side_effect=self.command)):
            manager.start()
            self.addCleanup(manager.stop)

    def command(self, arguments):
        self.copies.append(arguments)
        self.assertEqual(arguments[:4], ['skopeo', 'copy', '--all', '--preserve-digests'])
        source, target = [ref.removeprefix('docker://') for ref in arguments[4:]]
        # Rollback manifest and exact request are retained before even first copy.
        self.assertTrue((self.directory / ('release-' + P.R['digest'](self.previous).split(':')[1] + '.json')).exists())
        self.registry[target] = self.registry[source]
        return b''

    def run_promotion(self, apply=False):
        return P.promote(self.manifest, self.previous, self.plan, str(self.pointer), apply)

    def test_default_reads_complete_matrix_without_any_local_or_registry_writes(self):
        before = list(self.directory.iterdir())
        self.assertFalse(self.run_promotion()['applied'])
        self.assertEqual(list(self.directory.iterdir()), before)
        self.assertEqual(self.copies, [])
        self.assertEqual(P.roots.call_count, 2)

    def test_apply_reopens_every_alias_and_atomic_pointer(self):
        result = self.run_promotion(True)
        self.assertTrue(result['applied'])
        self.assertEqual(json.loads(self.pointer.read_bytes()), self.manifest)
        self.assertEqual(len(self.copies), len(self.plan['aliases']))
        self.assertEqual(result['manifest_digest'], P.R['digest'](self.manifest))

    def test_stale_alias_or_missing_rollback_refuses_before_first_copy(self):
        for row in self.plan['aliases']:
            prior = self.registry[row['alias']]
            self.registry[row['alias']] = 'sha256:' + 'f' * 64
            with self.assertRaises(ValueError):
                self.run_promotion(True)
            self.registry[row['alias']] = prior
        self.assertEqual(self.copies, [])

    def test_missing_candidate_or_root_refuses_before_first_copy(self):
        P.roots.side_effect = ValueError('fixture unreadable rollback root')
        with self.assertRaises(ValueError):
            self.run_promotion(True)
        self.assertEqual(self.copies, [])
        P.roots.side_effect = None
        self.registry[next(iter(self.new.values()))] = 'sha256:' + 'f' * 64
        with self.assertRaises(ValueError):
            self.run_promotion(True)
        self.assertEqual(self.copies, [])

    def test_failed_partial_copy_never_advances_pointer_and_retains_prior_manifest(self):
        real = P.command.side_effect
        def fail(arguments):
            if self.copies:
                raise subprocess.CalledProcessError(37, 'skopeo')
            return real(arguments)
        P.command.side_effect = fail
        with self.assertRaises(subprocess.CalledProcessError):
            self.run_promotion(True)
        self.assertEqual(json.loads(self.pointer.read_bytes()), self.previous)
        self.assertEqual(len(self.copies), 1)
        with self.assertRaises(ValueError):
            self.run_promotion(True)  # Observe partial aliases; never replay blindly.

    def test_readback_mismatch_or_late_alias_move_never_advances_pointer(self):
        P.command.side_effect = lambda arguments: b''
        with self.assertRaises(ValueError):
            self.run_promotion(True)
        self.assertEqual(json.loads(self.pointer.read_bytes()), self.previous)

    def test_missing_pair_wrong_manifest_or_injected_alias_refuses_without_io(self):
        for mutation in ('partial', 'digest', 'alias', 'old'):
            plan = copy.deepcopy(self.plan)
            if mutation == 'partial':
                plan['aliases'].pop()
            elif mutation == 'digest':
                plan['manifest_digest'] = 'sha256:' + 'f' * 64
            elif mutation == 'alias':
                plan['aliases'][0]['alias'] += ';touch /unsafe'
            else:
                plan['aliases'][0]['old'] = next(iter(self.new.values()))
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                P.promote(self.manifest, self.previous, plan, str(self.pointer), True)
        self.assertEqual(self.copies, [])

    def test_rollback_uses_same_explicit_compare_old_interface_without_rebuild(self):
        self.run_promotion(True)
        current = self.manifest
        target = self.previous
        self.previous = current
        self.manifest = target
        old, new = P.images(current), P.images(target)
        for row in self.plan['aliases']:
            row['old'] = old[(row['member'], row['artifact'])]
        self.plan.update(manifest_digest=P.R['digest'](target), previous_digest=P.R['digest'](current))
        self.assertTrue(self.run_promotion(True)['applied'])
        self.assertEqual(json.loads(self.pointer.read_bytes()), target)

    def test_changed_pointer_and_symlink_refuse(self):
        self.pointer.write_text('{}')
        with self.assertRaises(ValueError):
            self.run_promotion(True)
        self.pointer.unlink()
        self.pointer.symlink_to(self.directory / 'absent')
        with self.assertRaises(OSError):
            self.run_promotion(True)
        self.assertEqual(self.copies, [])


if __name__ == '__main__':
    unittest.main()
