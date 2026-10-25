#!/usr/bin/env python3
"""Offline native graph acquisition, exact-artifact and real CLI fixtures."""

import copy
from contextlib import redirect_stderr
import io
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from typing import Any
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
D = runpy.run_path(str(ROOT / 'scripts/nest-release-discover.py'))
F = runpy.run_path(str(ROOT / 'spec/files/nest_release_bind_test.py'))
R = D['R']


class NativeGitLab(F['FakeGitLab']):
    bridge: Any
    after_result: Any

    def __init__(self):
        super().__init__()
        self.request['kind'] = 'nest_release_base_discovery'
        self.request['producers'] = dict(upstream=dict(project='nest/stage0', member='stage0', root_pipeline=800,
                                                     bridge='Stage 0 candidate', job_name='Candidate haswell', input_pipeline=800))
        self.root = dict(id=800, project_id=3, sha=self.expected['sources']['nest/config'], ref='main',
                         source='api', status='running')
        self.child = dict(id=1, project_id=10, sha=self.expected['sources']['nest/stage0'], ref='main',
                          source='pipeline', status='success')
        self.bridge = dict(id=700, name='Stage 0 candidate', status='success', allow_failure=False,
                           pipeline=copy.deepcopy(self.root), downstream_pipeline=copy.deepcopy(self.child))
        for row in self.jobs.values():
            row['allow_failure'] = False
        self.native_reads = []
        self.extra_jobs = []
        self.extra_bridges = []
        self.outgoing = []
        self.after_result = None

    def get(self, path):
        self.native_reads.append(path)
        parts = path.split('/')
        if len(parts) >= 4 and parts[2] == 'pipelines':
            project = parts[1].replace('%2F', '/')
            row = self.root if project == 'nest/config' else self.child
            if len(parts) == 5:
                if parts[4].startswith('bridges'):
                    row = [self.bridge] + self.extra_bridges if project == 'nest/config' else self.outgoing
                else:
                    row = [self.jobs[('nest/config', 801)]] if project == 'nest/config' else [self.jobs[('nest/stage0', 101)]] + self.extra_jobs
            return R['canonical'](row)
        result = super().get(path)
        if path.endswith('/jobs/101/artifacts') and self.after_result:
            self.after_result(self)
        return result


class NativeTransportTest(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, CI_JOB_TOKEN='nonsecret-fixture-token', GITLAB_TOKEN='unused-sentinel')
        environment.start()
        self.addCleanup(environment.stop)
        self.graph = runpy.run_path(str(ROOT / 'scripts/nest-release-graph.py'))
        self.clients = (D['GitLab'](), self.graph['GitLab']())
        self.builder = Mock()
        for client in self.clients:
            substitution = patch.dict(client._read.__globals__, build_opener=self.builder)
            substitution.start()
            self.addCleanup(substitution.stop)
        self.paths = (('/pipelines/800', 'pipeline'),
                      ('/pipelines/800/jobs?per_page=100&page=1', 'job'),
                      ('/pipelines/800/bridges?per_page=100&page=2', 'bridge'))

    def test_pipeline_inventories_and_graph_request_use_only_ephemeral_auth(self):
        for client in self.clients:
            paths = self.paths + ((('/jobs/801/artifacts/release-graph/request.json', 'artifact'),)
                                  if client is self.clients[1] else ())
            for suffix, _ in paths:
                with self.subTest(client=type(client).__module__, suffix=suffix), patch('subprocess.run') as command:
                    payload = b'\x00exact bytes\xff'
                    self.builder.return_value.open.return_value = io.BytesIO(payload)
                    self.assertEqual(client.get('projects/nest%2Fconfig' + suffix), payload)
                    request = self.builder.return_value.open.call_args.args[0]
                    self.assertEqual(request.full_url, 'https://gitlab.joyfullee.me/api/v4/projects/nest%2Fconfig' + suffix)
                    self.assertEqual(request.get_method(), 'GET')
                    self.assertEqual(request.headers, {'Job-token': 'nonsecret-fixture-token'})
                    redirect = self.builder.call_args.args[0]()
                    self.assertIsNone(redirect.redirect_request(None, None, 302, '', {}, 'https://other.example/'))
                    command.assert_not_called()

    def test_permission_redirect_timeout_and_size_refuse_without_fallback(self):
        for client in self.clients:
            paths = self.paths + ((('/jobs/801/artifacts/release-graph/request.json', 'artifact'),)
                                  if client is self.clients[1] else ())
            for suffix, operation in paths:
                for error, failure in ((D['BIND']['HTTPError']('unused-sentinel', 403, 'unused-sentinel', {}, None), 'http_403'),
                                       (D['BIND']['HTTPError']('unused-sentinel', 302, 'unused-sentinel', {}, None), 'http_refused'),
                                       (TimeoutError('unused-sentinel'), 'timeout')):
                    with self.subTest(suffix=suffix, failure=failure), patch('subprocess.run') as command:
                        self.builder.reset_mock()
                        self.builder.return_value.open.side_effect = error
                        stream = io.StringIO()
                        with redirect_stderr(stream), self.assertRaisesRegex(ValueError, '^GitLab read failed$'):
                            client.get('projects/nest%2Fconfig' + suffix)
                        row = json.loads(stream.getvalue())
                        self.assertEqual((row['operation'], row['failure']), (operation, failure))
                        self.assertNotIn('unused-sentinel', stream.getvalue())
                        self.assertNotIn('nonsecret-fixture-token', stream.getvalue())
                        self.assertEqual(self.builder.return_value.open.call_count, 1)
                        command.assert_not_called()
        self.builder.return_value.open.side_effect = None
        self.builder.return_value.open.return_value = io.BytesIO(b'x' * (R['LIMIT'] + 1))
        with redirect_stderr(io.StringIO()), self.assertRaises(ValueError):
            self.clients[1].get('projects/nest%2Fconfig/jobs/801/artifacts/release-graph/request.json')

    def test_local_reads_keep_glab_and_exact_bytes(self):
        with patch.dict(os.environ, CI_JOB_TOKEN=''), patch('subprocess.run') as command:
            command.return_value = subprocess.CompletedProcess([], 0, b'exact bytes', b'')
            for client in self.clients:
                for suffix, _ in self.paths:
                    path = 'projects/nest%2Fconfig' + suffix
                    self.assertEqual(client.get(path), b'exact bytes')
                    self.assertEqual(command.call_args.args[0], ['glab', 'api', '--hostname', D['BIND']['HOST'], path])
        self.builder.assert_not_called()

    def test_unsupported_paths_refuse_before_either_transport(self):
        with patch('subprocess.run') as command:
            for client in self.clients:
                for path in ('https://other.example/', 'projects/nest%2Fconfig/pipelines/800/retry',
                             'projects/nest%2Fconfig/pipelines/800/jobs?per_page=100&page=0',
                             'projects/nest%2Fconfig/pipelines/800/bridges?per_page=100&page=1&token=unused-sentinel',
                             'projects/nest%2Fconfig/jobs/801/artifacts/release-graph/other.json'):
                    with self.subTest(path=path), self.assertRaises(ValueError): client.get(path)
            command.assert_not_called()
        self.builder.assert_not_called()

    def test_discovery_runs_through_real_native_transport_without_changing_resource_checks(self):
        fixture = NativeGitLab()
        def reply(request, **kwargs):
            path = request.full_url.removeprefix('https://gitlab.joyfullee.me/api/v4/')
            if path.endswith('/jobs?per_page=100&include_retried=true'):
                project = path.split('/')[1].replace('%2F', '/')
                pipeline = int(path.split('/')[3])
                raw = R['canonical']([row for (p, _), row in fixture.jobs.items()
                                      if p == project and row['pipeline']['id'] == pipeline])
            else:
                raw = fixture.get(path)
            return io.BytesIO(raw)
        self.builder.return_value.open.side_effect = reply
        with patch('subprocess.run') as command:
            result = D['discover'](fixture.request, self.clients[0])
            self.assertEqual(result, D['discover'](fixture.request, fixture))
            fixture.bridge['downstream_pipeline']['sha'] = 'f' * 40
            with self.assertRaises(ValueError): D['discover'](fixture.request, self.clients[0])
            command.assert_not_called()


class DiscoverTest(unittest.TestCase):
    def setUp(self):
        self.api = NativeGitLab()

    def discover(self):
        return D['discover'](self.api.request, self.api)

    def test_digest_named_producer_is_discovered_and_independently_bound(self):
        expected = self.discover()
        F['digest_results'](self.api.artifacts)
        self.assertEqual(self.discover(), expected)

    def test_native_bridge_discovers_exact_jobs_and_binds_actual_pair(self):
        before = copy.deepcopy(self.api.request)
        result = self.discover()
        self.assertEqual(self.api.request, before)
        selector = result['binding_request']['producers']['upstream']
        self.assertEqual((selector['pipeline'], selector['job'], selector['input_job']), (1, 101, 801))
        self.assertEqual(result['expectations']['members'][0]['bases'], self.api.result['output']['artifacts'])
        self.assertEqual(result['edges']['upstream']['bridge']['id'], 700)
        self.assertFalse(result['promotion_authorized'])
        self.assertEqual(result['publication'], 'not_performed')

    def test_all_predecessor_selectors_validate_before_any_external_read(self):
        for key, value in [('project', 'nest/unknown'), ('member', ''),
                           ('root_pipeline', True), ('input_pipeline', 0),
                           ('bridge', ''), ('job_name', []), ('unexpected', 'fixture')]:
            with self.subTest(key=key):
                self.api = NativeGitLab()
                later = copy.deepcopy(self.api.request['producers']['upstream'])
                later[key] = value
                self.api.request['producers']['later'] = later
                with self.assertRaises(ValueError): self.discover()
                self.assertEqual(self.api.native_reads, [])

    def test_binding_policy_and_executor_admit_before_predecessor_reads(self):
        for change in ('executor', 'empty', 'target', 'producer', 'base', 'artifact', 'duplicate', 'partial'):
            with self.subTest(change=change):
                self.api = NativeGitLab()
                request = self.api.request
                if change == 'executor': request['executor_job']['job'] = True
                if change == 'empty': request['bindings'] = []
                if change == 'target': request['bindings'][0]['target'] = 'missing'
                if change == 'producer': request['bindings'][0]['producer'] = 'missing'
                if change == 'base': request['bindings'][0]['base'] = 'image'
                if change == 'artifact': request['bindings'][0]['artifact'] = 'unknown'
                if change == 'duplicate': request['bindings'].append(copy.deepcopy(request['bindings'][0]))
                if change == 'partial': request['bindings'].pop()
                with self.assertRaises(ValueError): self.discover()
                self.assertEqual(self.api.native_reads, [])

    def test_generated_child_bridge_can_use_original_parent_input_pipeline(self):
        # Artifact-backed routing creates a config child containing the direct
        # member bridge; the unique input publisher remains in its parent.
        self.api.root['id'] = 850
        self.api.request['producers']['upstream'].update(root_pipeline=850, bridge='Build frozen member')
        self.api.bridge.update(name='Build frozen member', pipeline=copy.deepcopy(self.api.root))
        result = self.discover()
        selector = result['binding_request']['producers']['upstream']
        self.assertEqual((selector['input_pipeline'], selector['input_job']), (800, 801))
        self.assertEqual(result['edges']['upstream']['root']['id'], 850)
        self.assertEqual(result['expectations']['members'][0]['bases'], self.api.result['output']['artifacts'])

    def test_parent_can_finish_during_acquisition_but_requires_fresh_run(self):
        self.api.after_result = lambda api: api.root.update(status='success')
        with self.assertRaises(ValueError): self.discover()
        self.api.after_result = None
        self.discover()

    def test_failed_canceled_pending_or_wrong_source_pipeline_refuses(self):
        for target, key, value in [('root', 'status', 'failed'), ('root', 'status', 'canceled'),
                                   ('root', 'status', 'pending'), ('child', 'status', 'running'),
                                   ('child', 'source', 'api'), ('child', 'sha', 'e' * 40),
                                   ('child', 'project_id', 3), ('root', 'id', True)]:
            with self.subTest(target=target, key=key, value=value):
                self.api = NativeGitLab()
                getattr(self.api, target)[key] = value
                with self.assertRaises(ValueError): self.discover()

    def test_missing_ambiguous_tolerated_retried_or_moved_bridge_refuses(self):
        for change in ('missing', 'duplicate', 'tolerated', 'failed', 'retried', 'missing_child', 'moved_child', 'parent'):
            with self.subTest(change=change):
                self.api = NativeGitLab()
                if change == 'missing': self.api.bridge['name'] = 'other'
                if change == 'duplicate': self.api.extra_bridges = [dict(self.api.bridge, id=701)]
                if change == 'tolerated': self.api.bridge['allow_failure'] = True
                if change == 'failed': self.api.bridge['status'] = 'failed'
                if change == 'retried': self.api.bridge['retried'] = True
                if change == 'missing_child': self.api.bridge['downstream_pipeline'] = None
                if change == 'moved_child': self.api.bridge['downstream_pipeline']['sha'] = 'e' * 40
                if change == 'parent': self.api.bridge['pipeline']['project_id'] = 10
                with self.assertRaises((ValueError, TypeError)): self.discover()

    def test_leaf_trigger_loop_hidden_failure_and_ambiguous_member_refuse(self):
        for change in ('loop', 'failed', 'tolerated', 'duplicate', 'missing', 'erased'):
            with self.subTest(change=change):
                self.api = NativeGitLab()
                job = self.api.jobs[('nest/stage0', 101)]
                if change == 'loop': self.api.outgoing = [dict(id=702)]
                if change == 'failed': self.api.extra_jobs = [dict(id=102, name='ignored', status='failed', allow_failure=True)]
                if change == 'tolerated': job['allow_failure'] = True
                if change == 'duplicate': self.api.extra_jobs = [dict(job, id=102)]
                if change == 'missing': job['name'] = 'other'
                if change == 'erased': job['erased_at'] = 'fixture-erased'
                with self.assertRaises(ValueError): self.discover()

    def test_changed_bridge_inventory_or_artifact_after_read_refuses(self):
        def bridge(api): api.bridge['id'] = 701
        def failed_job(api): api.extra_jobs = [dict(id=102, name='late', status='failed', allow_failure=False)]
        def moved(api): api.result['output']['artifacts']['normal'] = F['MANIFEST']['image'](555)
        for mutate in (bridge, failed_job, moved):
            with self.subTest(mutation=mutate.__name__):
                self.api = NativeGitLab()
                self.api.after_result = mutate
                with self.assertRaises(ValueError): self.discover()

    def test_incompatible_or_fabricated_result_is_not_accepted_by_discovery(self):
        for change in ('source', 'debug', 'executor', 'digest', 'kind'):
            with self.subTest(change=change):
                self.api = NativeGitLab()
                if change == 'source': self.api.result['output']['producer']['sha'] = 'e' * 40
                if change == 'debug': del self.api.result['output']['artifacts']['debug']
                if change == 'executor': self.api.result['executor_receipt']['cpu'] = 'cortex-a53'
                if change == 'digest': self.api.result['expectations_digest'] = 'sha256:' + '0' * 64
                if change == 'kind': self.api.result['kind'] = 'status_fixture'
                with self.assertRaises(ValueError): self.discover()

    def test_freeze_job_must_be_exact_and_successful(self):
        for change in ('name', 'status', 'pipeline'):
            self.api = NativeGitLab()
            job = self.api.jobs[('nest/config', 801)]
            if change == 'name': job['name'] = 'Other input'
            if change == 'status': job['status'] = 'failed'
            if change == 'pipeline': job['pipeline']['id'] = 999
            with self.assertRaises(ValueError): self.discover()

    def test_pagination_exhaustion_duplicates_and_bounds(self):
        class Pages:
            def get(self, path):
                page = int(path.rsplit('=', 1)[1])
                return R['canonical']([dict(id=i) for i in range((page - 1) * 100 + 1, page * 100 + 1)] if page == 1 else [dict(id=101)])
        self.assertEqual(len(D['listing'](Pages(), 'nest/stage0', 1, 'jobs')), 101)
        class Duplicate:
            def get(self, path): return R['canonical']([dict(id=1), dict(id=1)])
        with self.assertRaises(ValueError): D['listing'](Duplicate(), 'nest/stage0', 1, 'jobs')
        class Unbounded:
            def get(self, path):
                page = int(path.rsplit('=', 1)[1])
                return R['canonical']([dict(id=i) for i in range(page * 100, (page + 1) * 100)])
        with self.assertRaises(ValueError): D['listing'](Unbounded(), 'nest/stage0', 1, 'jobs')

    def test_transport_only_allows_exact_pipeline_gets_and_sanitizes_failure(self):
        with patch.dict(os.environ, CI_JOB_TOKEN=''), patch('subprocess.run') as run:
            api = D['GitLab']()
            for path in ('projects/nest%2Fconfig/pipelines/latest', 'projects/nest%2Fconfig/pipelines/1/retry',
                         'projects/nest%2Fconfig/pipelines/1/jobs?per_page=100&page=0', 'https://fixture.invalid'):
                with self.assertRaises(ValueError): api.get(path)
            run.assert_not_called()
            run.return_value = subprocess.CompletedProcess([], 1, b'', b'HTTP 403')
            with self.assertRaisesRegex(ValueError, '^GitLab read failed$'):
                api.get('projects/nest%2Fconfig/pipelines/1/bridges?per_page=100&page=1')

    def test_real_cli_publishes_reopened_content_addressed_expectations(self):
        F['digest_results'](self.api.artifacts)
        result = self.discover()
        replies = {path: self.api.get(path) for path in set(self.api.native_reads)}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = root / 'glab'
            F['fake_glab'](fake, replies)
            request = root / 'request.json'
            request.write_bytes(R['canonical'](self.api.request))
            env = dict(os.environ, CI_JOB_TOKEN='', PATH=str(root) + os.pathsep + os.environ['PATH'], PYTHONDONTWRITEBYTECODE='1')
            cmd = [sys.executable, str(ROOT / 'scripts/nest-release-discover.py'), '--discovery', str(request)]
            completed = subprocess.run(cmd + ['--output-dir', str(root)], env=env, capture_output=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            summary = json.loads(completed.stdout)
            self.assertEqual(R['load'](summary['path']), result)
            self.assertEqual(R['load'](summary['expectations_path']), result['expectations'])
            request.unlink()
            self.assertTrue(summary['readback_verified'])

    def test_real_cli_malformed_input_has_static_error_and_no_side_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'input.json'
            path.write_text('{"fixture-private-value":1}')
            completed = subprocess.run([sys.executable, str(ROOT / 'scripts/nest-release-discover.py'),
                                        '--discovery', str(path)], capture_output=True)
            self.assertEqual(completed.returncode, 1)
            self.assertNotIn(b'fixture-private-value', completed.stderr + completed.stdout)
            self.assertEqual(list(Path(directory).iterdir()), [path])


if __name__ == '__main__':
    unittest.main()
