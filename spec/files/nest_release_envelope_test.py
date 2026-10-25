#!/usr/bin/env python3
"""Offline complete-architecture acquisition with real discovery/assembly checks."""

import copy
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
E = runpy.run_path(str(ROOT / 'scripts/nest-release-envelope.py'))
F = runpy.run_path(str(ROOT / 'spec/files/nest_release_assemble_test.py'))
R = E['R']


class ProgramGitLab:
    request: Any
    after_read: Any

    def __init__(self, architectures=('haswell', 'cortex-a53', 'sifive-u74'), full=False):
        self.replies = {}
        self.reads = []
        self.after_read = None
        assemblies = {}
        for number, architecture in enumerate(architectures):
            original = F['MatrixGitLab']()
            if full:
                fixture = F['AssemblyTest']()
                fixture.api = original
                fixture.full_matrix()
            F['A']['assemble'](original.request, original)
            offset = number * 1000

            def transform(value, key='') -> Any:
                if type(value) is dict:
                    if 'path_with_namespace' in value:
                        return copy.deepcopy(value)
                    return {k: transform(v, k) for k, v in value.items()}
                if type(value) is list:
                    return [transform(v, key) for v in value]
                if type(value) is int and key in ('id', 'pipeline', 'job', 'root_pipeline', 'input_pipeline'):
                    return value + offset
                if type(value) is str:
                    if value == 'haswell' or value in ('Candidate haswell', 'Build haswell'):
                        return value.replace('haswell', architecture)
                    if key in ('id', 'member', 'members') and value in ('stage0', 'stage1', 'stage2', 'stage3', 'tool'):
                        return value + '-' + architecture
                    if 'fixture-host' in value:
                        return value.replace('fixture-host', 'fixture-host-' + architecture)
                    if '12345678-1234-4123-8123-123456789abc' in value:
                        return value.replace('12345678-1234-4123-8123-123456789abc',
                                             '12345678-1234-4123-8123-' + format(number + 1, '012x'))
                    if key == 'dataset_guid':
                        return str(int(value) + offset)
                    if value == F['F']['F']['MANIFEST']['image'](1):
                        return F['F']['F']['MANIFEST']['image'](1 + offset)
                return value

            assembly = transform(original.request)
            expected = assembly['expectations']
            # Producer-map keys are member identities, not JSON field names.
            assembly['producers'] = {k + '-' + architecture: v for k, v in assembly['producers'].items()}
            assemblies[architecture] = assembly
            paths = set(original.native_reads) - {p for p in original.native_reads if p.endswith('/artifacts')}
            paths.update('projects/' + project.replace('/', '%2F') + '/jobs/' + str(job) + '/artifacts/' + name
                         for project, job, name in original.artifacts if name.startswith('release-results/'))
            for path in paths:
                raw = json.loads(original.get(path))
                row = transform(raw)
                if type(row) is dict and row.get('kind') == 'nest_release_member_result':
                    row['expectations_digest'] = R['digest'](expected)
                parts = path.split('/')
                if len(parts) >= 4:
                    parts[3] = str(int(parts[3]) + offset)
                target = '/'.join(parts).replace('executor-receipts/haswell.json', 'executor-receipts/' + architecture + '.json')
                for member in ('stage0', 'stage1', 'stage2', 'stage3', 'tool'):
                    target = target.replace('release-results/' + member + '.json',
                                            'release-results/' + member + '-' + architecture + '.json')
                if target in self.replies:
                    assert self.replies[target] == row
                self.replies[target] = row
        first = next(iter(assemblies.values()))['expectations']
        consumers = copy.deepcopy(first['consumers'])
        for consumer in consumers:
            consumer['members'] = [identifier for a in assemblies.values() for c in a['expectations']['consumers']
                                   if c['project'] == consumer['project'] for identifier in c['members']]
        self.request = dict(schema=1, kind='nest_release_envelope_request', release=first['release'],
                            sources=copy.deepcopy(first['sources']), consumers=consumers, assemblies=assemblies)

    def get(self, path):
        self.reads.append(path)
        if path.endswith('/artifacts'):
            raw = F['F']['F']['result_archive']([(key.removeprefix(path + '/'), R['canonical'](row))
                                                for key, row in self.replies.items() if key.startswith(path + '/')])
        else:
            raw = R['canonical'](self.replies[path])
        if self.after_read:
            self.after_read(self, path)
        return raw


class EnvelopeTest(unittest.TestCase):
    def setUp(self):
        self.api = ProgramGitLab()

    def acquire(self):
        return E['envelope'](self.api.request, self.api)

    def test_digest_named_tool_results_across_all_architectures_preserve_envelope(self):
        self.api = ProgramGitLab(full=True)
        expected = self.acquire()
        for path in list(self.api.replies):
            if '/artifacts/release-results/' in path:
                row = self.api.replies.pop(path)
                sha = hashlib.sha256(R['canonical'](row)).hexdigest()
                self.api.replies[path[:-5] + '.sha256-' + sha + '.json'] = row
        self.assertEqual(self.acquire(), expected)

    def test_three_distinct_executors_and_all_member_pairs_are_preserved(self):
        before = copy.deepcopy(self.api.request)
        result = self.acquire()
        self.assertEqual(self.api.request, before)
        self.assertEqual(result['members'], 6)
        self.assertEqual(set(result['architectures']), E['ARCHITECTURES'])
        for architecture, group in result['architectures'].items():
            manifest = group['manifest']
            self.assertEqual(manifest['expectations'], before['assemblies'][architecture]['expectations'])
            self.assertEqual(set(group['members']), {'stage0-' + architecture, 'stage1-' + architecture})
            for row in manifest['candidate']['outputs']:
                self.assertEqual(row['member']['cpu'], architecture)
                self.assertEqual(set(row['artifacts']), {'normal', 'debug'})
        self.assertFalse(result['promotion_authorized'])
        self.assertEqual(result['image_compatibility_verification'], 'not_performed')

    def test_single_selected_architecture_is_not_forced_to_invent_other_outputs(self):
        self.api = ProgramGitLab(('haswell',))
        self.assertEqual(self.acquire()['members'], 2)

    def test_stage_roots_and_tools_keep_private_identity_and_unique_generation_boundaries(self):
        self.api = ProgramGitLab(full=True)
        result = self.acquire()
        self.assertEqual(result['members'], 15)
        roots = [output for group in result['architectures'].values()
                 for output in group['manifest']['candidate']['outputs'] if output['member']['stage'] == 'stage3']
        self.assertEqual(len({row['artifacts']['root']['dataset_guid'] for row in roots}), 3)
        self.assertEqual(len({row['member']['identity_reference'] for row in roots}), 3)

    def test_cross_architecture_shared_root_guid_refuses(self):
        self.api = ProgramGitLab(full=True)
        self.api.replies['projects/nest%2Fstage3/jobs/1104/artifacts/release-results/stage3-cortex-a53.json'][
            'output']['artifacts']['root']['dataset_guid'] = '123456789'
        with self.assertRaisesRegex(ValueError, 'host root GUID reused'): self.acquire()

    def test_cross_architecture_host_or_identity_reuse_refuses_before_io(self):
        for key in ('host', 'identity_reference'):
            with self.subTest(key=key):
                self.api = ProgramGitLab(full=True)
                groups = self.api.request['assemblies']
                arm = next(m for m in groups['cortex-a53']['expectations']['members'] if m['stage'] == 'stage3')
                other = next(m for m in groups['haswell']['expectations']['members'] if m['stage'] == 'stage3')
                arm[key] = other[key]
                if key == 'identity_reference': arm['identity_root'] = other['identity_root']
                with self.assertRaises(ValueError): self.acquire()
                self.assertFalse(self.api.reads)

    def test_global_scope_cannot_hide_missing_members_or_consumers(self):
        for change in ('missing_group', 'member', 'consumer', 'duplicate', 'extra'):
            with self.subTest(change=change):
                self.api = ProgramGitLab()
                request = self.api.request
                if change == 'missing_group': del request['assemblies']['cortex-a53']
                if change == 'member': request['consumers'][0]['members'].pop()
                if change == 'consumer': request['consumers'] = request['consumers'][:-1]
                if change == 'duplicate': request['consumers'].append(copy.deepcopy(request['consumers'][0]))
                if change == 'extra': request['unreviewed'] = True
                with self.assertRaises(ValueError): self.acquire()
                self.assertFalse(self.api.reads)

    def test_different_release_config_or_repository_source_closure_refuses(self):
        for key in ('release', 'config', 'overlay'):
            with self.subTest(key=key):
                self.api = ProgramGitLab()
                expected = self.api.request['assemblies']['cortex-a53']['expectations']
                if key == 'release': expected['release'] = 'other-release'
                else: expected['sources']['nest/' + key] = 'e' * 40
                with self.assertRaises(ValueError): self.acquire()
                self.assertFalse(self.api.reads)

    def test_later_architecture_malformed_selector_refuses_before_any_external_read(self):
        for key, value in [('member', 'stage0-haswell'), ('project', 'nest/stage0'),
                           ('root_pipeline', True), ('input_pipeline', 0),
                           ('bridge', ''), ('job_name', []), ('unexpected', 'fixture')]:
            with self.subTest(key=key):
                self.api = ProgramGitLab()
                self.api.request['assemblies']['sifive-u74']['producers']['stage1-sifive-u74'][key] = value
                with self.assertRaises(ValueError): self.acquire()
                self.assertEqual(self.api.reads, [])

    def test_wrong_architecture_or_shared_executor_never_substitutes_for_receipt(self):
        for change in ('cpu', 'image', 'job', 'key', 'boolean'):
            with self.subTest(change=change):
                self.api = ProgramGitLab()
                groups = self.api.request['assemblies']
                arm = groups['cortex-a53']
                if change == 'cpu': arm['expectations']['members'][0]['cpu'] = 'haswell'
                if change == 'image': arm['expectations']['executor'] = copy.deepcopy(groups['haswell']['expectations']['executor'])
                if change == 'job': arm['executor_job'] = copy.deepcopy(groups['haswell']['executor_job'])
                if change == 'key': groups['arbitrary'] = groups.pop('cortex-a53')
                if change == 'boolean': arm['executor_job']['job'] = True
                with self.assertRaises(ValueError): self.acquire()

    def test_local_and_global_decisions_and_full_extra_consumer_inventory_match(self):
        for change in ('local_reuse', 'local_inventory', 'global_defer', 'legacy'):
            with self.subTest(change=change):
                self.api = ProgramGitLab()
                groups = self.api.request['assemblies']
                local = groups['haswell']['expectations']['consumers']
                if change == 'local_reuse': local[0]['decision'] = 'reuse'
                if change == 'local_inventory': local.append(dict(project='nest/legacy', decision='defer', reason='Fixture', members=[]))
                if change == 'global_defer': self.api.request['consumers'][0]['decision'] = 'defer'
                if change == 'legacy':
                    self.api.request['consumers'].append(dict(project='nest/legacy', decision='defer', reason='Fixture', members=[]))
                with self.assertRaises(ValueError): self.acquire()
                self.assertFalse(self.api.reads)

    def test_failed_native_job_in_one_architecture_prevents_whole_envelope(self):
        path = 'projects/nest%2Fstage1/jobs/1102'
        self.api.replies[path]['status'] = 'failed'
        with self.assertRaises(ValueError): self.acquire()

    def test_prior_architecture_is_reacquired_after_later_architecture(self):
        def change(api, path):
            if '/pipelines/2800' in path:
                api.replies['projects/nest%2Fconfig/pipelines/1800']['status'] = 'success'
        self.api.after_read = change
        with self.assertRaisesRegex(ValueError, 'architecture resources changed'): self.acquire()

    def test_cross_architecture_member_duplicate_is_not_a_complete_matrix(self):
        arm = self.api.request['assemblies']['cortex-a53']['expectations']['members'][0]
        arm['id'] = 'stage0-haswell'
        with self.assertRaises(ValueError): self.acquire()

    def test_cli_retains_content_addressed_envelope_and_reopens_without_source_input(self):
        expected = self.acquire()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = root / 'glab'
            F['F']['F']['fake_glab'](fake, {path: self.api.get(path) for path in set(self.api.reads)})
            request = root / 'request.json'
            request.write_bytes(R['canonical'](self.api.request))
            env = dict(os.environ, CI_JOB_TOKEN='', PATH=str(root) + os.pathsep + os.environ['PATH'], PYTHONDONTWRITEBYTECODE='1')
            command = [sys.executable, str(ROOT / 'scripts/nest-release-envelope.py'), '--envelope', str(request)]
            completed = subprocess.run(command, env=env, capture_output=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertFalse(json.loads(completed.stdout)['readback_verified'])
            completed = subprocess.run(command + ['--output-dir', str(root)], env=env, capture_output=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            summary = json.loads(completed.stdout)
            self.assertTrue(summary['readback_verified'])
            self.assertEqual(R['load'](summary['path']), expected)
            request.unlink()
            self.assertEqual(R['load'](summary['path']), expected)

    def test_invalid_cli_emits_static_failure_and_no_partial_envelope(self):
        with tempfile.TemporaryDirectory() as directory:
            request = Path(directory) / 'request.json'
            request.write_text('{"private-fixture-text": 1}')
            completed = subprocess.run([sys.executable, str(ROOT / 'scripts/nest-release-envelope.py'),
                                        '--envelope', str(request), '--output-dir', directory], capture_output=True)
            self.assertEqual(completed.returncode, 1)
            self.assertNotIn(b'private-fixture-text', completed.stdout + completed.stderr)
            self.assertEqual(list(Path(directory).iterdir()), [request])


if __name__ == '__main__':
    unittest.main()
