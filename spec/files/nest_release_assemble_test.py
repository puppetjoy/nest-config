#!/usr/bin/env python3
"""Offline complete-matrix assembly through real discovery and result validation."""

import copy
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
A = runpy.run_path(str(ROOT / 'scripts/nest-release-assemble.py'))
F = runpy.run_path(str(ROOT / 'spec/files/nest_release_discover_test.py'))
R = A['R']


class MatrixGitLab(F['NativeGitLab']):
    request: Any
    after_read: Any

    def __init__(self):
        super().__init__()
        self.children = {'nest/stage0': self.child,
                         'nest/stage1': dict(self.child, id=2, sha=self.expected['sources']['nest/stage1'])}
        self.bridges = [self.bridge, dict(self.bridge, id=701, name='Stage 1 candidate',
                                         downstream_pipeline=copy.deepcopy(self.children['nest/stage1']))]
        self.jobs[('nest/stage1', 102)] = dict(self.make_job('nest/stage1', 2, 102, 'Candidate haswell'), allow_failure=False)
        output = copy.deepcopy(F['F']['MANIFEST']['fixture']()[1]['outputs'][1])
        self.stage1 = dict(self.result, output=output)
        self.stage1['output']['producer']['job'] = 102
        self.stage1['output']['producer']['pipeline'] = 2
        self.artifacts[('nest/stage1', 102, 'release-results/stage1.json')] = self.stage1
        producers = {}
        for identifier in ('stage0', 'stage1'):
            producers[identifier] = dict(project='nest/' + identifier, member=identifier, root_pipeline=800,
                                         bridge='Stage ' + identifier[-1] + ' candidate',
                                         job_name='Candidate haswell', input_pipeline=800)
        self.request = dict(schema=1, kind='nest_release_assembly', expectations=copy.deepcopy(self.expected),
                            executor_job=dict(pipeline=900, job=901), producers=producers)
        self.after_read = None
        self.read_count = 0

    def get(self, path):
        self.native_reads.append(path)
        parts = path.split('/')
        project = parts[1].replace('%2F', '/')
        if len(parts) >= 4 and parts[2] == 'pipelines':
            row = self.root if project == 'nest/config' else self.children[project]
            if len(parts) == 5:
                if parts[4].startswith('bridges'):
                    row = self.bridges + self.extra_bridges if project == 'nest/config' else self.outgoing
                else:
                    row = [job for (p, _), job in self.jobs.items()
                           if p == project and job['pipeline']['id'] == int(parts[3])] + self.extra_jobs
            raw = R['canonical'](row)
        else:
            raw = F['F']['FakeGitLab'].get(self, path)
        self.read_count += 1
        if self.after_read:
            self.after_read(self, path)
        return raw


class AssemblyTest(unittest.TestCase):
    def setUp(self):
        self.api = MatrixGitLab()

    def assemble(self):
        return A['assemble'](self.api.request, self.api)

    def test_digest_named_results_assemble_the_identical_candidate(self):
        self.full_matrix()
        expected = self.assemble()
        F['F']['digest_results'](self.api.artifacts)
        self.assertEqual(self.assemble(), expected)

    def test_complete_native_matrix_is_assembled_without_mutating_request(self):
        before = copy.deepcopy(self.api.request)
        result = self.assemble()
        self.assertEqual(self.api.request, before)
        self.assertEqual(list(result['members']), ['stage0', 'stage1'])
        self.assertEqual(result['manifest']['expectations'], before['expectations'])
        self.assertEqual([r['producer']['job'] for r in result['manifest']['candidate']['outputs']], [101, 102])
        self.assertFalse(result['promotion_authorized'])
        self.assertEqual(result['image_compatibility_verification'], 'not_performed')

    def test_missing_extra_or_wrong_member_selectors_refuse(self):
        for change in ('missing', 'extra', 'member', 'project', 'unknown_field'):
            with self.subTest(change=change):
                self.api = MatrixGitLab()
                producers = self.api.request['producers']
                if change == 'missing': del producers['stage1']
                if change == 'extra': producers['extra'] = copy.deepcopy(producers['stage0'])
                if change == 'member': producers['stage1']['member'] = 'stage0'
                if change == 'project': producers['stage1']['project'] = 'nest/stage0'
                if change == 'unknown_field': self.api.request['shell'] = 'fixture-private-value'
                with self.assertRaises(ValueError): self.assemble()

    def test_complete_selector_inventory_refuses_before_any_external_read(self):
        for key, value in [('member', 'stage0'), ('project', 'nest/stage0'),
                           ('root_pipeline', True), ('input_pipeline', 0),
                           ('bridge', ''), ('job_name', []), ('unexpected', 'fixture')]:
            with self.subTest(key=key):
                self.api = MatrixGitLab()
                self.api.request['producers']['stage1'][key] = value
                with self.assertRaises(ValueError): self.assemble()
                self.assertEqual(self.api.native_reads, [])

    def full_matrix(self):
        expected, candidate = F['F']['MANIFEST']['fixture']()
        self.api.expected.clear()
        self.api.expected.update(expected)
        self.api.request['expectations'] = copy.deepcopy(expected)
        for result in (self.api.result, self.api.stage1):
            result['expectations_digest'] = R['digest'](expected)
        for index, output in enumerate(candidate['outputs'][2:], start=3):
            project, identifier = output['producer']['project'], output['member']['id']
            child = dict(self.api.child, id=index, sha=expected['sources'][project])
            self.api.children[project] = child
            name = 'Member ' + identifier
            self.api.bridges.append(dict(self.api.bridge, id=700 + index, name=name, downstream_pipeline=copy.deepcopy(child)))
            self.api.jobs[(project, 100 + index)] = dict(self.api.make_job(project, index, 100 + index, name), allow_failure=False)
            self.api.artifacts[(project, 100 + index, 'release-results/' + identifier + '.json')] = dict(
                self.api.result, output=copy.deepcopy(output))
            self.api.request['producers'][identifier] = dict(project=project, member=identifier, root_pipeline=800,
                                                            bridge=name, job_name=name, input_pipeline=800)

    def test_all_stage_roots_and_tool_results_form_one_complete_manifest(self):
        self.full_matrix()
        result = self.assemble()
        outputs = result['manifest']['candidate']['outputs']
        self.assertEqual({row['member']['stage'] for row in outputs}, {'stage0', 'stage1', 'stage2', 'stage3', 'tool'})
        root = next(row for row in outputs if row['member']['stage'] == 'stage3')
        self.assertEqual(root['artifacts']['root']['dataset_guid'], '123456789')
        self.assertEqual(root['member']['identity_ca_sha256'], 'a' * 64)

    def test_stage3_identity_generation_and_platform_are_not_relabelled(self):
        for change in ('identity_reference', 'identity_ca_sha256', 'platform', 'root'):
            with self.subTest(change=change):
                self.api = MatrixGitLab()
                self.full_matrix()
                row = self.api.artifacts[('nest/stage3', 104, 'release-results/stage3.json')]['output']
                if change == 'root': row['artifacts']['root']['path'] = '/nest/identity/fixture-host'
                elif change == 'platform': row['member']['platform'] = 'other-platform'
                else: row['member'][change] = 'e' * 64
                with self.assertRaises(ValueError): self.assemble()

    def test_member_receipt_must_match_independently_queried_executor_bytes(self):
        self.api.stage1['executor_receipt'] = copy.deepcopy(self.api.executor)
        self.api.stage1['executor_receipt']['inputs']['modules'][0]['content_digest'] = 'sha256:' + 'c' * 64
        with self.assertRaisesRegex(ValueError, 'selected executor receipt'): self.assemble()

    def test_output_must_match_independent_final_member_and_source_closure(self):
        for change in ('base', 'release', 'source', 'executor', 'decision', 'original_decision', 'digest', 'pair', 'kind'):
            with self.subTest(change=change):
                self.api = MatrixGitLab()
                expected = self.api.request['expectations']
                if change == 'base': expected['members'][1]['bases']['normal'] = F['F']['MANIFEST']['image'](500)
                if change == 'release': expected['release'] = 'different-release'
                if change == 'source': expected['sources']['nest/overlay'] = 'e' * 40
                if change == 'executor': expected['executor']['image'] = F['F']['MANIFEST']['image'](501)
                if change == 'decision': next(c for c in expected['consumers'] if c['project'] == 'nest/stage1')['decision'] = 'defer'
                if change == 'original_decision':
                    next(c for c in self.api.expected['consumers'] if c['project'] == 'nest/stage0')['decision'] = 'reuse'
                    for result in (self.api.result, self.api.stage1): result['expectations_digest'] = R['digest'](self.api.expected)
                if change == 'digest': self.api.stage1['expectations_digest'] = 'sha256:' + '0' * 64
                if change == 'pair': self.api.stage1['output']['artifacts']['debug'] = self.api.stage1['output']['artifacts']['normal']
                if change == 'kind': self.api.stage1['kind'] = 'status_fixture'
                with self.assertRaises(ValueError): self.assemble()

    def test_reuse_still_requires_exact_successful_original_production(self):
        next(c for c in self.api.request['expectations']['consumers'] if c['project'] == 'nest/stage1')['decision'] = 'reuse'
        self.assemble()
        self.api.jobs[('nest/stage1', 102)]['status'] = 'failed'
        with self.assertRaises(ValueError): self.assemble()

    def test_wrong_missing_erased_or_tolerated_native_resources_refuse(self):
        for change in ('failed', 'erased', 'tolerated', 'bridge', 'loop', 'child_source', 'wrong_executor'):
            with self.subTest(change=change):
                self.api = MatrixGitLab()
                job = self.api.jobs[('nest/stage1', 102)]
                if change == 'failed': job['status'] = 'failed'
                if change == 'erased': job['erased_at'] = 'fixture-erased'
                if change == 'tolerated': job['allow_failure'] = True
                if change == 'bridge': self.api.bridges[1]['status'] = 'failed'
                if change == 'loop': self.api.outgoing = [dict(id=999)]
                if change == 'child_source': self.api.children['nest/stage1']['source'] = 'api'
                if change == 'wrong_executor': self.api.jobs[('nest/config', 901)]['name'] = 'Build cortex-a53'
                with self.assertRaises(ValueError): self.assemble()

    def test_changed_previously_read_member_is_reacquired_before_acceptance(self):
        def mutate(api, path):
            if path.endswith('/jobs/102/artifacts'):
                api.result['output']['artifacts']['normal'] = F['F']['MANIFEST']['image'](502)
        self.api.after_read = mutate
        with self.assertRaises(ValueError): self.assemble()

    def test_executor_bytes_are_rechecked_even_if_job_identity_is_unchanged(self):
        def mutate(api, path):
            if path.endswith('/jobs/102/artifacts'):
                changed = copy.deepcopy(api.executor)
                changed['inputs']['modules'][0]['content_digest'] = 'sha256:' + 'c' * 64
                api.artifacts[('nest/config', 901, 'executor-receipts/haswell.json')] = changed
        self.api.after_read = mutate
        with self.assertRaisesRegex(ValueError, 'assembly executor changed'): self.assemble()

    def test_mixed_architecture_and_boolean_numeric_identity_refuse(self):
        self.api.request['expectations']['members'][1]['cpu'] = 'cortex-a53'
        with self.assertRaises(ValueError): self.assemble()
        self.api = MatrixGitLab()
        self.api.request['executor_job']['job'] = True
        with self.assertRaises(ValueError): self.assemble()

    def test_real_cli_retains_manifest_and_provenance_with_reopened_bytes(self):
        F['F']['digest_results'](self.api.artifacts)
        result = self.assemble()
        replies = {path: self.api.get(path) for path in set(self.api.native_reads)}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = root / 'glab'
            F['F']['fake_glab'](fake, replies)
            request = root / 'request.json'
            request.write_bytes(R['canonical'](self.api.request))
            env = dict(os.environ, CI_JOB_TOKEN='', PATH=str(root) + os.pathsep + os.environ['PATH'], PYTHONDONTWRITEBYTECODE='1')
            command = [sys.executable, str(ROOT / 'scripts/nest-release-assemble.py'), '--assembly', str(request)]
            completed = subprocess.run(command, env=env, capture_output=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertFalse(json.loads(completed.stdout)['readback_verified'])
            completed = subprocess.run(command + ['--output-dir', str(root)], env=env, capture_output=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            summary = json.loads(completed.stdout)
            self.assertTrue(summary['readback_verified'])
            self.assertEqual(R['load'](summary['path']), result)
            self.assertEqual(R['load'](summary['manifest_path']), result['manifest'])
            request.unlink()
            self.assertEqual(R['load'](summary['path']), result)

    def test_malformed_real_cli_refuses_without_network_or_partial_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'request.json'
            path.write_text('{"fixture-private-value":1}')
            completed = subprocess.run([sys.executable, str(ROOT / 'scripts/nest-release-assemble.py'),
                                        '--assembly', str(path), '--output-dir', directory], capture_output=True)
            self.assertEqual(completed.returncode, 1)
            self.assertNotIn(b'fixture-private-value', completed.stderr + completed.stdout)
            self.assertEqual(list(Path(directory).iterdir()), [path])


if __name__ == '__main__':
    unittest.main()
