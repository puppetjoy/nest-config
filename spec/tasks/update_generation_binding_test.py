#!/usr/bin/env python3
"""Complete fixture manifests; no real publication, generation or host access."""

import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'spec/files'))
from nest_release_manifest_test import fixture, release


def binding_fixture():
    expected, candidate = fixture()
    manifest = release.validate(expected, candidate)
    runtime = release.digest(manifest)
    output = candidate['outputs'][3]
    policy = {'hostname': 'fixture-host', 'release': runtime, 'build_release': expected['release'],
              'source': output['artifacts']['root']['path'], 'content_digest': output['artifacts']['root']['content_digest'],
              'destination': '/var/lib/nest/generations/' + runtime.split(':')[1]}
    scope = {'release': runtime, 'config_source': expected['sources']['nest/config'],
             'hosts': [{'name': 'fixture-host', 'platform': output['member']['platform'],
                        'kernel': output['member']['compatibility']['kernel']}]}
    return manifest, {'fixture-host': policy}, scope


class GenerationBindingTests(unittest.TestCase):
    def setUp(self):
        self.manifest, self.policies, self.scope = binding_fixture()

    def bind(self):
        return release.generation_binding(self.manifest, self.policies, self.scope)

    def test_exact_full_manifest_binds_publication_runtime_content_and_scope(self):
        before = copy.deepcopy((self.manifest, self.policies, self.scope))
        result = self.bind()
        self.assertEqual(result['manifest_digest'], release.digest(self.manifest))
        self.assertEqual(result['hosts']['fixture-host']['root'], self.manifest['candidate']['outputs'][3]['artifacts']['root'])
        self.assertEqual(result['resource_verification'], 'not_performed')
        self.assertFalse(result['reset_authorized'])
        self.assertEqual(before, (self.manifest, self.policies, self.scope))
        self.assertEqual(result, release.generation_binding(self.manifest, self.policies))

    def test_foreign_content_release_build_path_or_host_refuses(self):
        for key, value in [('hostname', 'other'), ('release', 'sha256:' + '0' * 64), ('build_release', 'other'),
                           ('content_digest', 'sha256:' + '0' * 64), ('source', '/nest/hosts/fixture-host'),
                           ('destination', '/var/lib/nest/generations/' + '0' * 64)]:
            original = self.policies['fixture-host'][key]
            self.policies['fixture-host'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.bind()
            self.policies['fixture-host'][key] = original

    def test_complete_manifest_validation_cannot_be_replaced_by_host_output_only(self):
        self.manifest['candidate']['outputs'].pop(0)
        with self.assertRaises(ValueError):
            self.bind()

    def test_changed_unrelated_output_changes_runtime_identity(self):
        self.manifest['candidate']['outputs'][0]['artifacts']['normal'] = 'registry.example/nest/image@sha256:' + 'f' * 64
        with self.assertRaises(ValueError):
            self.bind()

    def test_moved_expectations_or_producer_source_refuses(self):
        for key in ('expectations', 'producer'):
            manifest = copy.deepcopy(self.manifest)
            if key == 'expectations':
                manifest[key]['sources']['nest/config'] = 'f' * 40
            else:
                manifest['candidate']['outputs'][3][key]['sha'] = 'f' * 40
            with self.subTest(key=key), self.assertRaises(ValueError):
                release.generation_binding(manifest, self.policies)

    def test_manifest_envelope_is_exact_and_schema_is_not_boolean(self):
        for change in ({'schema': True}, {'kind': 'nest_release_manifest_validation'}, {'unknown': 'private'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                release.generation_binding(dict(self.manifest, **change), self.policies)

    def test_unknown_empty_or_non_stage3_hosts_refuse(self):
        for policies in ({}, {'other': self.policies['fixture-host']}, {'fixture-host': None}, []):
            with self.subTest(policies=policies), self.assertRaises(ValueError):
                release.generation_binding(self.manifest, policies)

    def test_catalog_source_can_advance_without_rebuilding_or_relabeling_the_root(self):
        before = copy.deepcopy(self.manifest)
        scope = dict(self.scope, config_source='f' * 40)
        result = release.generation_binding(self.manifest, self.policies, scope)
        self.assertEqual(result['manifest_digest'], release.digest(before))
        self.assertEqual(self.manifest, before)
        self.assertEqual(result['hosts'], self.bind()['hosts'])

    def test_wave_release_config_kernel_platform_and_complete_scope_refuse(self):
        for key, value in [('release', 'sha256:' + '0' * 64), ('config_source', 'main'),
                           ('hosts', []), ('hosts', self.scope['hosts'] * 2)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                release.generation_binding(self.manifest, self.policies, dict(self.scope, **{key: value}))
        for key, value in [('name', 'other'), ('kernel', 'other'), ('platform', 'other')]:
            scope = copy.deepcopy(self.scope)
            scope['hosts'][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                release.generation_binding(self.manifest, self.policies, scope)

    def run_task(self, raw, directory=None):
        task = ROOT / 'tasks/update_generation_binding.py'
        return subprocess.run([sys.executable, str(task)], input=raw, capture_output=True, text=True, cwd=directory)

    def test_real_stdin_from_unrelated_working_directory(self):
        payload = {'manifest': self.manifest, 'policies': self.policies, 'scope': self.scope, '_noop': True}
        result = self.run_task(json.dumps(payload), ROOT / 'spec')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), self.bind())

    def test_stdin_duplicate_keys_nonfinite_oversized_and_private_errors_are_sanitized(self):
        for raw in ('[]', '{"manifest":{},"manifest":{"private":"sentinel"}}',
                    '{"manifest":NaN,"policies":{}}', 'x' * (release.LIMIT + 1),
                    json.dumps({'manifest': self.manifest, 'policies': self.policies, 'private': 'sentinel'})):
            result = self.run_task(raw)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout)['_error']['kind'], 'nest/update-generation-binding')
            self.assertNotIn('sentinel', result.stdout + result.stderr)
            self.assertNotIn('Traceback', result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
