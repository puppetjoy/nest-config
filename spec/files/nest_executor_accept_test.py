#!/usr/bin/env python3
"""Offline completed bootstrap acquisition; no actual images or native builds."""

import copy
from contextlib import redirect_stderr
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import unittest
from typing import Any
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
M = runpy.run_path(str(ROOT / 'scripts/nest-executor-accept.py'))
T = runpy.run_path(str(ROOT / 'spec/files/nest_executor_bootstrap_test.py'))
R = M['R']


class ExecutorAcceptanceTest(unittest.TestCase):
    request: dict[str, Any]

    def setUp(self):
        fixture = T['ExecutorBootstrapTest']()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.f = fixture
        self.api = fixture.api
        self.bootstrap = fixture.acquire()
        self.bootstrap['successor'].update(pipeline=1000, job=1001)
        self.executor = copy.deepcopy(self.api.executor)
        self.executor.update(sha=fixture.f.sha, pipeline=1000, job=1001,
                             image='registry.gitlab.joyfullee.me/nest/config/main@sha256:' + 'e' * 64)
        self.executor['inputs'].update(source=fixture.f.sha, base_image=self.bootstrap['successor']['base_image'])
        self.executor['inputs']['modules'][0]['git_head'] = fixture.f.sha
        self.job = self.api.make_job('nest/config', 1000, 1001, 'Build haswell')
        self.job['pipeline']['sha'] = fixture.f.sha
        self.job['commit']['id'] = fixture.f.sha
        self.job['allow_failure'] = False
        self.pipeline = dict(id=1000, project_id=3, sha=fixture.f.sha, ref='main', source='api', status='success')
        self.jobs = [self.job]
        self.bridges = []
        self.request = dict(schema=1, kind='nest_executor_successor_request', bootstrap=fixture.request,
                            successor=dict(pipeline=1000, job=1001, image=self.executor['image'],
                                           executor_sha256='', bootstrap_sha256=''))
        self.raw = {}
        self.reseal()
        original = self.api.get

        def get(path):
            if path in self.raw:
                self.api.reads.append(path)
                return self.raw[path]
            if '/pipelines/1000' in path:
                self.api.reads.append(path)
                row = self.jobs if '/jobs?' in path else self.bridges if '/bridges?' in path else self.pipeline
                return R['canonical'](row)
            if path.endswith('/jobs/1001'):
                self.api.reads.append(path)
                return R['canonical'](self.job)
            return original(path)

        self.api.get = get
        self.api.reads.clear()

    def reseal(self):
        prefix = 'projects/nest%2Fconfig/jobs/1001/artifacts/'
        executor = R['canonical'](self.executor)
        bootstrap = R['canonical'](self.bootstrap)
        self.raw.update({prefix + 'executor-receipts/' + self.executor['cpu'] + '.json': executor,
                         prefix + 'executor-bootstrap/receipt.json': bootstrap,
                         prefix + 'executor-bootstrap/bolt.ref': (self.bootstrap['successor']['base_image'] + '\n').encode()})
        self.request['successor'].update(executor_sha256=hashlib.sha256(executor).hexdigest(),
                                         bootstrap_sha256=hashlib.sha256(bootstrap).hexdigest())

    def accept(self):
        return M['accept'](self.request, self.api)

    def test_complete_old_and_new_boundary_remains_distinct_and_unpromoted(self):
        before = copy.deepcopy(self.api.artifacts)
        result = self.accept()
        self.assertEqual(self.api.artifacts, before)
        self.assertEqual(result['accepted']['executor'], self.executor)
        self.assertEqual(result['accepted']['bootstrap'], self.bootstrap)
        self.assertNotEqual(self.executor['sha'], self.api.executor['sha'])
        self.assertEqual(result['local_image_execution'], 'not_performed')
        self.assertFalse(result['promotion_authorized'])
        self.assertGreaterEqual(self.api.reads.count('projects/nest%2Fconfig/jobs/1001/artifacts/executor-bootstrap/receipt.json'), 2)

    def test_same_revision_successor_preserves_distinct_builds_and_original_receipts(self):
        source = self.api.expected['sources']['nest/config']
        self.f.request['successor_source'] = source
        self.bootstrap['request_digest'] = R['digest'](self.f.request)
        self.bootstrap['successor']['source'] = source
        self.executor['sha'] = source
        self.executor['inputs']['source'] = source
        self.executor['inputs']['modules'][0]['git_head'] = source
        self.job['pipeline']['sha'] = source
        self.job['commit']['id'] = source
        self.pipeline['sha'] = source
        self.reseal()
        result = self.accept()
        self.assertEqual(result['accepted']['executor']['sha'], self.api.executor['sha'])
        self.assertNotEqual(result['accepted']['executor']['pipeline'], self.api.executor['pipeline'])
        self.assertEqual(result['accepted']['executor']['inputs']['base_image'],
                         self.api.result['output']['artifacts']['image'])

    def test_complete_static_admission_precedes_any_reads(self):
        for target, key, value in [(self.request, 'schema', True), (self.request, 'kind', 'other'),
                                   (self.request['successor'], 'job', True),
                                   (self.request['successor'], 'pipeline', 0),
                                   (self.request['successor'], 'executor_sha256', 'f' * 64 + '\n'),
                                   (self.request['successor'], 'bootstrap_sha256', ''),
                                   (self.request['successor'], 'image', 'nest/config:latest'),
                                   (self.request['bootstrap']['producer'], 'input_job', 0),
                                   (self.request['bootstrap'], 'successor_cpu', 'zen5')]:
            old = target[key]
            target[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): self.accept()
            target[key] = old
        self.assertEqual(self.api.reads, [])

    def test_every_distinct_architecture_and_digest_named_prior_result(self):
        for cpu in M['M']['CPUS']:
            with self.subTest(cpu=cpu):
                self.api.expected['members'][0]['cpu'] = cpu
                self.api.result['output']['member']['cpu'] = cpu
                self.api.executor['cpu'] = cpu
                self.api.jobs[('nest/config', 901)]['name'] = 'Build ' + cpu
                self.api.artifacts = {('nest/config', 901, 'executor-receipts/' + cpu + '.json'): self.api.executor,
                                      ('nest/config', 801, 'release-inputs/expectations.json'): self.api.expected,
                                      ('nest/tools/bolt', 105, 'release-results/tool.json'): self.api.result}
                self.f.request['successor_cpu'] = cpu
                self.f.reseal()
                T['T']['digest_results'](self.api.artifacts)
                self.bootstrap = M['M']['acquire'](self.f.request, self.f.f.sha, cpu, self.api)
                self.bootstrap['successor'].update(pipeline=1000, job=1001)
                self.executor['cpu'] = cpu
                self.job['name'] = 'Build ' + cpu
                self.reseal()
                self.assertEqual(self.accept()['accepted']['executor']['cpu'], cpu)

    def test_failed_or_unexpected_successor_pipeline_refuses(self):
        for key, value in [('status', 'running'), ('status', 'failed'), ('source', 'push'),
                           ('source', 'parent_pipeline'), ('sha', 'f' * 40)]:
            old = self.pipeline[key]; self.pipeline[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): self.accept()
            self.pipeline[key] = old
        self.bridges = [dict(id=9000)]
        with self.assertRaises(ValueError): self.accept()

    def test_erased_failed_tolerated_duplicate_or_wrong_build_job_refuses(self):
        for key, value in [('status', 'failed'), ('erased_at', 'fixture'), ('allow_failure', True),
                           ('id', 1002), ('name', 'Build cortex-a53')]:
            old = copy.deepcopy(self.job)
            self.job[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): self.accept()
            self.job.clear(); self.job.update(old)
        for name in ('Build haswell', 'Build cortex-a53', 'Deploy image'):
            extra = copy.deepcopy(self.job); extra.update(id=1002, name=name)
            self.jobs.append(extra)
            with self.subTest(name=name), self.assertRaises(ValueError): self.accept()
            self.jobs.pop()

    def test_each_artifact_digest_and_reference_refuses_changed_bytes(self):
        for path in self.raw:
            original = self.raw[path]
            self.raw[path] += b' '
            with self.subTest(path=path), self.assertRaises(ValueError): self.accept()
            self.raw[path] = original

    def test_pinned_but_relabelled_executor_and_bootstrap_refuse(self):
        for target, key, value in [(self.executor, 'job', 1002), (self.executor, 'sha', 'f' * 40),
                                   (self.executor['inputs'], 'base_image', T['T']['MANIFEST']['image'](98)),
                                   (self.bootstrap['successor'], 'pipeline', 999),
                                   (self.bootstrap, 'request_digest', 'sha256:' + 'f' * 64),
                                   (self.bootstrap, 'promotion_authorized', True)]:
            old = target[key]; target[key] = value; self.reseal()
            with self.subTest(key=key), self.assertRaises(ValueError): self.accept()
            target[key] = old; self.reseal()

    def test_old_failed_resources_and_copied_prior_receipt_cannot_substitute(self):
        self.api.jobs[('nest/config', 901)]['status'] = 'failed'
        with self.assertRaises(ValueError): self.accept()
        self.api.jobs[('nest/config', 901)]['status'] = 'success'
        self.bootstrap['predecessor']['executor_job']['job'] = 999
        self.reseal()
        with self.assertRaises(ValueError): self.accept()

    def test_reacquisition_refuses_later_resource_inventory_or_byte_changes(self):
        original = self.api.get
        count = 0

        def get(path):
            nonlocal count
            if path.endswith('/pipelines/1000'):
                count += 1
                if count == 2:
                    self.job['erased_at'] = 'changed'
            return original(path)

        with patch.object(self.api, 'get', get), self.assertRaises(ValueError): self.accept()

    def test_only_exact_config_bootstrap_artifacts_extend_allowlist(self):
        api = M['GitLab']()
        for name in ('receipt.json', 'bolt.ref'):
            with patch.object(api, '_read', return_value=b'fixture') as read:
                self.assertEqual(api.get('projects/nest%2Fconfig/jobs/1001/artifacts/executor-bootstrap/' + name), b'fixture')
                read.assert_called_once()
        for path in ('projects/nest%2Ftools%2Fbolt/jobs/1001/artifacts/executor-bootstrap/receipt.json',
                     'projects/nest%2Fconfig/jobs/1001/artifacts/executor-bootstrap/private.json',
                     'projects/nest%2Fconfig/jobs/1001/artifacts/executor-bootstrap/../receipt.json'):
            with patch.object(api, '_read') as read, self.assertRaises(ValueError):
                api.get(path)
            read.assert_not_called()

    def test_native_denial_closes_response_without_credential_fallback(self):
        api = M['GitLab']()
        payload = io.BytesIO(b'private-sentinel')
        error = M['B']['HTTPError']('private-sentinel', 403, 'private-sentinel', {}, payload)
        builder = Mock()
        builder.return_value.open.side_effect = error
        stream = io.StringIO()
        with patch.dict(os.environ, CI_JOB_TOKEN='nonsecret-fixture-token'), \
                patch.dict(api._read.__globals__, build_opener=builder), \
                patch('subprocess.run') as fallback, redirect_stderr(stream), self.assertRaises(ValueError):
            api.get('projects/nest%2Fconfig/jobs/1001/artifacts/executor-bootstrap/receipt.json')
        self.assertTrue(payload.closed)
        fallback.assert_not_called()
        self.assertEqual(json.loads(stream.getvalue()), dict(schema=1, kind='nest_release_gitlab_read_failure',
                                                             operation='artifact', failure='http_403'))

    def test_real_cli_retains_reopens_after_request_removed_and_static_failure(self):
        replies = {}
        original = self.api.get

        def get(path):
            raw = original(path); replies[path] = raw; return raw

        with patch.object(self.api, 'get', get): self.accept()
        binary = self.f.f.root / 'bin'; binary.mkdir()
        T['T']['fake_glab'](binary / 'glab', replies)
        request = self.f.f.root / 'successor.json'; request.write_bytes(R['canonical'](self.request))
        directory = self.f.f.root / 'accepted'; directory.mkdir()
        env = dict(os.environ, PATH=str(binary) + os.pathsep + os.environ['PATH'], CI_JOB_TOKEN='')
        args = [sys.executable, str(ROOT / 'scripts/nest-executor-accept.py'), '--successor', str(request),
                '--output-dir', str(directory)]
        child = subprocess.run(args, env=env, capture_output=True, text=True)
        self.assertEqual(child.returncode, 0, child.stderr)
        summary = json.loads(child.stdout)
        request.unlink()
        retained = Path(summary['path']).read_bytes()
        self.assertEqual(json.loads(retained)['accepted']['executor'], self.executor)
        self.assertTrue(summary['readback_verified'])
        again = subprocess.run(args, env=env, capture_output=True, text=True)
        self.assertEqual(again.returncode, 1)
        self.assertEqual(again.stdout, '')
        self.assertEqual(again.stderr, 'Bootstrap successor acceptance refused or failed\n')
        self.assertEqual(Path(summary['path']).read_bytes(), retained)


if __name__ == '__main__':
    unittest.main()
