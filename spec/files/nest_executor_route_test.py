#!/usr/bin/env python3
"""Offline artifact-backed executor routing; no native builds or host actions."""

import copy
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import unittest
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
M = runpy.run_path(str(ROOT / 'scripts/nest-executor-bootstrap.py'))
T = runpy.run_path(str(ROOT / 'spec/files/nest_executor_bootstrap_test.py'))
A = runpy.run_path(str(ROOT / 'spec/files/nest_executor_accept_test.py'))
R = M['R']


class ExecutorRouteTest(unittest.TestCase):
    native_request: dict[str, Any]
    native_bridge: dict[str, Any]

    def setUp(self):
        self.f = T['ExecutorBootstrapTest']()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.api = self.f.api
        self.env = dict(self.f.env, EXECUTOR_BOOTSTRAP='route', CI_COMMIT_BRANCH='main',
                        CI_JOB_NAME='Compile executor bootstrap')

    def compile(self):
        return M['compile_route'](self.env, self.api)

    def routed(self, child_id=1000, status='running'):
        raw = R['canonical'](self.f.request)
        self.selector = dict(pipeline=1100, job=1101, sha256=hashlib.sha256(raw).hexdigest())
        self.parent = dict(id=1100, project_id=3, sha=self.f.f.sha, ref='main', source='api', status='running')
        self.child = dict(id=child_id, project_id=3, sha=self.f.f.sha, ref='main', source='parent_pipeline', status=status)
        self.job = self.api.make_job('nest/config', 1100, 1101, 'Compile executor bootstrap')
        self.job['pipeline']['sha'] = self.job['commit']['id'] = self.f.f.sha
        self.job['allow_failure'] = False
        self.bridge = dict(id=1102, name='Run executor bootstrap', status=status, allow_failure=False,
                           pipeline=dict(id=1100, project_id=3, sha=self.f.f.sha), downstream_pipeline=self.child)
        self.bridges = [self.bridge]
        self.outgoing = []
        self.raw = raw
        original = self.api.get

        def get(path):
            self.api.reads.append(path)
            if path.endswith('/jobs/1101'):
                return R['canonical'](self.job)
            if path.endswith('/artifacts/executor-bootstrap-route/request.json'):
                return self.raw
            if '/pipelines/1100' in path:
                return R['canonical'](self.bridges if '/bridges?' in path else self.parent)
            if '/pipelines/' + str(child_id) in path:
                return R['canonical'](self.outgoing if '/bridges?' in path else self.child)
            return original(path)

        self.api.get = get
        env = {k: v for k, v in self.f.env.items() if k != 'RELEASE_BOOTSTRAP_FILE'}
        env.update(CI_PIPELINE_SOURCE='parent_pipeline', CI_PIPELINE_ID=str(child_id),
                   RELEASE_BOOTSTRAP_PIPELINE='1100', RELEASE_BOOTSTRAP_JOB='1101',
                   RELEASE_BOOTSTRAP_SHA256=self.selector['sha256'])
        return env

    def read(self, status='running'):
        return M['route_input'](self.selector, self.f.f.sha, 1000, self.api, status)

    def test_compile_reacquires_old_boundary_and_retains_exact_child(self):
        receipt = self.compile()
        directory = self.f.f.checkout / 'executor-bootstrap-route'
        child = json.loads((directory / 'child.yml').read_bytes())
        self.assertEqual(child['include'], [dict(local='.gitlab-ci.yml')])
        self.assertEqual(child['variables']['EXECUTOR_BOOTSTRAP'], 'true')
        self.assertEqual(set(child['variables']), {'EXECUTOR_BOOTSTRAP', 'EXECUTOR_ONLY', 'BUILD', *M['ROUTE_KEYS']})
        self.assertNotIn('RELEASE_BOOTSTRAP_FILE', child['variables'])
        self.assertEqual(hashlib.sha256((directory / 'request.json').read_bytes()).hexdigest(),
                         child['variables']['RELEASE_BOOTSTRAP_SHA256'])
        self.assertEqual(receipt['execution'], 'not_started')
        self.assertFalse(receipt['promotion_authorized'])
        self.assertGreaterEqual(self.api.reads.count('projects/nest%2Ftools%2Fbolt/pipelines/5'), 4)
        self.f.f.input.unlink()
        self.assertEqual(json.loads((directory / 'request.json').read_bytes()), self.f.request)

    def test_compile_no_clobber_and_failed_readback(self):
        self.compile()
        with self.assertRaises(FileExistsError): self.compile()
        original = Path.read_bytes
        def read(path):
            return b'changed' if path.name == 'child.yml' else original(path)
        # Fresh compiler directory is required; preserve earlier evidence.
        self.env['CI_PROJECT_DIR'] = str(self.f.f.checkout)
        with patch.object(Path, 'read_bytes', read):
            with self.assertRaises(ValueError):
                # Use another real, clean fixture checkout.
                other = T['ExecutorBootstrapTest'](); other.setUp()
                try:
                    env = dict(other.env, EXECUTOR_BOOTSTRAP='route', CI_COMMIT_BRANCH='main',
                               CI_JOB_NAME='Compile executor bootstrap')
                    M['compile_route'](env, other.api)
                finally: other.doCleanups()

    def test_each_native_cpu_compiles_its_own_prior_executor_and_successor(self):
        for cpu in M['CPUS']:
            with self.subTest(cpu=cpu):
                fixture = T['ExecutorBootstrapTest'](); fixture.setUp()
                try:
                    api = fixture.api
                    api.expected['members'][0]['cpu'] = cpu
                    api.result['output']['member']['cpu'] = cpu
                    api.executor['cpu'] = cpu
                    api.jobs[('nest/config', 901)]['name'] = 'Build ' + cpu
                    api.artifacts = {('nest/config', 901, 'executor-receipts/' + cpu + '.json'): api.executor,
                                     ('nest/config', 801, 'release-inputs/expectations.json'): api.expected,
                                     ('nest/tools/bolt', 105, 'release-results/tool.json'): api.result}
                    fixture.request['successor_cpu'] = cpu
                    fixture.reseal()
                    env = dict(fixture.env, EXECUTOR_BOOTSTRAP='route', BUILD=cpu, CPU=cpu,
                               CI_COMMIT_BRANCH='main', CI_JOB_NAME='Compile executor bootstrap')
                    receipt = M['compile_route'](env, api)
                    self.assertEqual(receipt['acquired']['successor']['cpu'], cpu)
                    child = json.loads((fixture.f.checkout / 'executor-bootstrap-route/child.yml').read_bytes())
                    self.assertEqual(child['variables']['BUILD'], cpu)
                finally: fixture.doCleanups()

    def test_compile_identity_schema_source_and_conflicts_refuse_without_reads(self):
        for key, value in [('CI_JOB_NAME', 'Other'), ('CI_COMMIT_BRANCH', 'other'),
                           ('CI_COMMIT_SHA', 'f' * 40), ('CI_PROJECT_ID', '4'),
                           ('EXECUTOR_BOOTSTRAP', 'true'), ('CI_PIPELINE_SOURCE', 'parent_pipeline')]:
            old = self.env.get(key); self.env[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): self.compile()
            self.env[key] = old
        for key in M['CONFLICTS']:
            self.env[key] = 'false'
            with self.subTest(key=key), self.assertRaises(ValueError): self.compile()
            del self.env[key]
        self.assertEqual(self.api.reads, [])

    def test_route_compiler_refuses_failed_prior_and_publication_race(self):
        self.api.pipeline['status'] = 'failed'
        with self.assertRaises(ValueError): self.compile()
        self.api.pipeline['status'] = 'success'
        original = self.api.get
        calls = 0
        def get(path):
            nonlocal calls
            if path.endswith('/pipelines/5'):
                calls += 1
                if calls == 3: self.api.pipeline['status'] = 'failed'
            return original(path)
        with patch.object(self.api, 'get', get), self.assertRaises(ValueError): self.compile()
        self.assertFalse((self.f.f.checkout / 'executor-bootstrap-route').exists())

    def test_route_transport_selected_only_as_complete_native_child(self):
        env = self.routed()
        self.assertTrue(M['selected'](env))
        for key in M['ROUTE_KEYS']:
            old = env.pop(key)
            with self.subTest(key=key), self.assertRaises(ValueError): M['selected'](env)
            env[key] = old
        for key, value in [('RELEASE_BOOTSTRAP_FILE', '/fixture/request.json'), ('EXECUTOR_BOOTSTRAP', 'route'),
                           ('CI_PIPELINE_SOURCE', 'api'), ('RELEASE_BOOTSTRAP_JOB', '01'),
                           ('RELEASE_BOOTSTRAP_SHA256', 'f' * 64 + '\n')]:
            with self.subTest(key=key), self.assertRaises(ValueError): M['selected'](dict(env, **{key: value}))

    def test_native_child_reads_compiler_and_reacquires_prior_before_retaining_base(self):
        env = self.routed()
        image = M['publish'](None, env, self.api)
        retained = json.loads((self.f.f.checkout / 'executor-bootstrap/receipt.json').read_bytes())
        self.assertEqual(retained['route'], self.selector)
        self.assertEqual(image, self.api.result['output']['artifacts']['image'])
        self.assertEqual(retained['successor']['pipeline'], 1000)
        M['check_successor'](dict(sha=self.f.f.sha, cpu='haswell', inputs=dict(base_image=image),
                                  pipeline=1000, job=int(env['CI_JOB_ID'])), self.f.f.checkout / 'executor-bootstrap')

    def test_route_changed_failed_recursive_wrong_child_or_compiler_refuses(self):
        self.routed()
        cases = [(self.parent, 'source', 'parent_pipeline'), (self.parent, 'sha', 'f' * 40),
                 (self.parent, 'ref', 'other'), (self.job, 'name', 'Other'),
                 (self.job, 'status', 'failed'), (self.job, 'erased_at', 'fixture'),
                 (self.bridge, 'allow_failure', True), (self.bridge, 'status', 'failed'),
                 (self.child, 'id', 999), (self.child, 'source', 'pipeline'),
                 (self.child, 'sha', 'f' * 40), (self.child, 'ref', 'other'),
                 (self.selector, 'sha256', 'f' * 64)]
        for target, key, value in cases:
            old = target[key]; target[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError): self.read()
            target[key] = old
        self.bridges.append(copy.deepcopy(self.bridge))
        with self.assertRaises(ValueError): self.read()
        self.bridges.pop()
        self.outgoing.append(dict(id=1200))
        with self.assertRaises(ValueError): self.read()

    def test_child_reacquisition_refuses_changed_route_after_prior_acquisition(self):
        env = self.routed()
        original = self.api.get
        count = 0
        def get(path):
            nonlocal count
            raw = original(path)
            if path.endswith('/artifacts/executor-bootstrap-route/request.json'):
                count += 1
                if count == 3: raw += b' '
            return raw
        with patch.object(self.api, 'get', get), self.assertRaises(ValueError): M['publish'](None, env, self.api)
        self.assertFalse((self.f.f.checkout / 'executor-bootstrap').exists())

    def test_only_exact_route_artifact_is_allowlisted(self):
        api = M['GitLab']()
        path = 'projects/nest%2Fconfig/jobs/1101/artifacts/executor-bootstrap-route/request.json'
        with patch.object(api, '_read', return_value=b'fixture') as read:
            self.assertEqual(api.get(path), b'fixture'); read.assert_called_once_with(path, 'artifact')
        for wrong in (path.replace('request.json', 'private.json'), path.replace('nest%2Fconfig', 'nest%2Ftools%2Fbolt'),
                      path.replace('request.json', '../request.json')):
            with patch.object(api, '_read') as read, self.assertRaises(ValueError): api.get(wrong)
            read.assert_not_called()

    def test_real_compiler_cli_with_fake_glab_retains_after_exit(self):
        replies = {}
        original = self.api.get
        def get(path):
            raw = original(path); replies[path] = raw; return raw
        with patch.object(self.api, 'get', get): self.compile()
        other = T['ExecutorBootstrapTest'](); other.setUp()
        self.addCleanup(other.doCleanups)
        binary = other.f.root / 'bin'; binary.mkdir()
        T['T']['fake_glab'](binary / 'glab', replies)
        # The clean checkout source must equal the request selected for this run.
        request = copy.deepcopy(self.f.request)
        request['successor_source'] = other.f.sha
        other.f.input.write_bytes(R['canonical'](request))
        env = dict(other.env, EXECUTOR_BOOTSTRAP='route', CI_COMMIT_BRANCH='main',
                   CI_JOB_NAME='Compile executor bootstrap', PATH=str(binary) + os.pathsep + os.environ['PATH'])
        child = subprocess.run([sys.executable, str(ROOT / 'scripts/nest-executor-bootstrap.py'), '--compile-route'],
                               env=env, capture_output=True, text=True)
        self.assertEqual(child.returncode, 0, child.stderr)
        other.f.input.unlink()
        self.assertEqual(json.loads((other.f.checkout / 'executor-bootstrap-route/request.json').read_bytes()), request)
        self.assertNotIn('Traceback', child.stderr)

    def native_discovery(self):
        expected = self.api.expected
        self.native_root = dict(id=850, project_id=3, sha=expected['sources']['nest/config'],
                                ref='main', source='parent_pipeline', status='success')
        self.native_bridge = dict(id=851, name='Build frozen member', status='success', allow_failure=False,
                                  pipeline=copy.deepcopy(self.native_root), downstream_pipeline=copy.deepcopy(self.api.pipeline))
        self.native_request = dict(schema=1, kind='nest_executor_bootstrap_discovery',
                                   successor_source=self.f.f.sha, successor_cpu=self.f.request['successor_cpu'],
                                   config_source=expected['sources']['nest/config'],
                                   bolt_source=expected['sources']['nest/tools/bolt'],
                                   producer=dict(project='nest/tools/bolt', member='tool', root_pipeline=850,
                                                 input_pipeline=800, bridge='Build frozen member', job_name='Candidate haswell'))
        original = self.api.get
        def get(path):
            if '/pipelines/850' in path or '/pipelines/800/jobs?' in path:
                self.api.reads.append(path)
                if '/pipelines/800/jobs?' in path:
                    return R['canonical']([self.api.jobs[('nest/config', 801)]])
                return R['canonical']([self.native_bridge] if '/bridges?' in path else self.native_root)
            return original(path)
        self.api.get = get
        self.f.f.input.write_bytes(R['canonical'](self.native_request))

    def discover(self):
        return M['discover_route'](self.native_request, self.f.f.sha, self.native_request['successor_cpu'], self.api)

    def test_discovery_resolves_native_bridge_and_retains_reopenable_canonical_request(self):
        self.native_discovery()
        original = copy.deepcopy(self.native_request)
        canonical, evidence, acquired = self.discover()
        self.assertEqual(canonical['producer'], self.f.request['producer'])
        self.assertEqual(canonical['native']['producer'], original['producer'])
        self.assertEqual(evidence['edge']['bridge']['id'], 851)
        self.assertEqual(acquired['successor']['base_image'], self.api.result['output']['artifacts']['image'])
        receipt = self.compile()
        directory = self.f.f.checkout / 'executor-bootstrap-route'
        self.assertEqual(json.loads((directory / 'request.json').read_bytes()), canonical)
        self.assertEqual(json.loads((directory / 'discovery.json').read_bytes())['request'], original)
        self.assertEqual(receipt['request_sha256'], hashlib.sha256((directory / 'request.json').read_bytes()).hexdigest())
        self.f.f.input.unlink()
        self.assertEqual(M['acquire'](canonical, self.f.f.sha, 'haswell', self.api), acquired)
        self.assertEqual(self.native_request, original)

    def test_discovery_all_native_cpus_and_digest_named_results(self):
        self.native_discovery()
        for cpu in M['CPUS']:
            with self.subTest(cpu=cpu):
                self.api.expected['members'][0]['cpu'] = cpu
                self.api.result['output']['member']['cpu'] = cpu
                self.api.executor['cpu'] = cpu
                self.api.jobs[('nest/config', 901)]['name'] = 'Build ' + cpu
                self.api.artifacts = {('nest/config', 901, 'executor-receipts/' + cpu + '.json'): self.api.executor,
                                      ('nest/config', 801, 'release-inputs/expectations.json'): self.api.expected,
                                      ('nest/tools/bolt', 105, 'release-results/tool.json'): self.api.result}
                self.native_request['successor_cpu'] = cpu
                self.f.reseal()
                T['T']['digest_results'](self.api.artifacts)
                canonical, _, acquired = self.discover()
                self.assertEqual(acquired['successor']['cpu'], cpu)
                self.assertEqual(canonical['producer']['job'], 105)

    def test_discovery_running_root_requires_successful_required_completed_leaf(self):
        self.native_discovery()
        self.native_root['status'] = 'running'
        canonical, _, acquired = self.discover()
        self.assertEqual(acquired['native_edge']['root']['status'], 'running')
        self.assertEqual(canonical['producer']['pipeline'], 5)
        self.native_bridge['status'] = 'running'
        with self.assertRaises(ValueError): self.discover()

    def test_discovery_complete_static_admission_precedes_external_reads(self):
        self.native_discovery()
        mutations = [('schema', True), ('kind', 'other'), ('successor_source', 'f' * 40),
                     ('successor_cpu', 'zen5'), ('config_source', self.f.f.sha),
                     ('config_source', 'a' * 40 + '\n'), ('bolt_source', None), ('extra', 'field')]
        for key, value in mutations:
            request = copy.deepcopy(self.native_request); request[key] = value
            with self.subTest(key=key), self.assertRaises((ValueError, TypeError)):
                M['discover_route'](request, self.f.f.sha, 'haswell', self.api)
        for key, value in [('project', 'nest/stage0'), ('root_pipeline', True), ('input_pipeline', 0),
                           ('member', '../tool'), ('bridge', '$SECRET'), ('job_name', ''), ('extra', 'field')]:
            request = copy.deepcopy(self.native_request); request['producer'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                M['discover_route'](request, self.f.f.sha, 'haswell', self.api)
        self.assertEqual(self.api.reads, [])

    def test_discovery_failed_erased_ambiguous_wrong_source_or_native_lineage_refuses(self):
        self.native_discovery()
        cases = [(self.native_root, 'sha', 'f' * 40), (self.native_root, 'status', 'failed'),
                 (self.native_bridge, 'status', 'failed'), (self.native_bridge, 'allow_failure', True),
                 (self.native_bridge['downstream_pipeline'], 'id', 6),
                 (self.api.pipeline, 'source', 'api'), (self.api.pipeline, 'sha', 'f' * 40),
                 (self.api.jobs[('nest/config', 801)], 'erased_at', 'fixture')]
        for target, key, value in cases:
            old = target[key]; target[key] = value
            with self.subTest(key=key), self.assertRaises((ValueError, TypeError)): self.discover()
            target[key] = old
        self.api.extra_jobs.append(copy.deepcopy(self.api.jobs[('nest/tools/bolt', 105)]))
        with self.assertRaises(ValueError): self.discover()

    def test_discovery_detects_bridge_retry_during_old_executor_acquisition(self):
        self.native_discovery()
        original = self.api.get
        def get(path):
            raw = original(path)
            if path.endswith('/jobs/901/artifacts/executor-receipts/haswell.json'):
                self.native_bridge['id'] += 1
            return raw
        with patch.object(self.api, 'get', get), self.assertRaises(ValueError): self.compile()
        self.assertFalse((self.f.f.checkout / 'executor-bootstrap-route').exists())

    def test_retained_native_request_rechecks_lineage_and_admits_all_fields_before_reads(self):
        self.native_discovery()
        canonical, _, _ = self.discover()
        self.api.reads.clear()
        for key, value in [('config_source', self.f.f.sha), ('bolt_source', 'malformed'), ('extra', 'field')]:
            bad = copy.deepcopy(canonical); bad['native'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                M['acquire'](bad, self.f.f.sha, 'haswell', self.api)
        self.assertEqual(self.api.reads, [])
        self.native_bridge['status'] = 'failed'
        with self.assertRaises(ValueError): M['acquire'](canonical, self.f.f.sha, 'haswell', self.api)

    def test_discovered_route_real_cli_retains_exact_native_context_after_exit(self):
        self.native_discovery()
        replies = {}
        original = self.api.get
        def get(path):
            raw = original(path); replies[path] = raw; return raw
        with patch.object(self.api, 'get', get): self.compile()
        other = T['ExecutorBootstrapTest'](); other.setUp()
        self.addCleanup(other.doCleanups)
        binary = other.f.root / 'bin'; binary.mkdir()
        T['T']['fake_glab'](binary / 'glab', replies)
        submitted = dict(self.native_request, successor_source=other.f.sha)
        other.f.input.write_bytes(R['canonical'](submitted))
        env = dict(other.env, EXECUTOR_BOOTSTRAP='route', CI_COMMIT_BRANCH='main',
                   CI_JOB_NAME='Compile executor bootstrap', PATH=str(binary) + os.pathsep + os.environ['PATH'])
        child = subprocess.run([sys.executable, str(ROOT / 'scripts/nest-executor-bootstrap.py'), '--compile-route'],
                               env=env, capture_output=True, text=True)
        self.assertEqual(child.returncode, 0, child.stderr)
        other.f.input.unlink()
        directory = other.f.checkout / 'executor-bootstrap-route'
        canonical = json.loads((directory / 'request.json').read_bytes())
        self.assertEqual(canonical['native']['producer'], submitted['producer'])
        self.assertEqual(json.loads((directory / 'discovery.json').read_bytes())['request'], submitted)
        self.assertNotIn('Traceback', child.stderr)

    def test_successor_acceptance_reopens_original_discovered_native_edge(self):
        fixture = A['ExecutorAcceptanceTest'](); fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.f, self.api = fixture.f, fixture.api
        self.native_discovery()
        canonical, _, acquired = self.discover()
        fixture.request['bootstrap'] = canonical
        fixture.bootstrap = acquired
        fixture.bootstrap['successor'].update(pipeline=1000, job=1001)
        fixture.reseal()
        accepted = fixture.accept()
        self.assertEqual(accepted['request']['bootstrap']['native'], canonical['native'])
        original = self.api.get
        calls = 0
        def get(path):
            nonlocal calls
            if path.endswith('/pipelines/1000'):
                calls += 1
                if calls == 2: self.native_bridge['id'] += 1
            return original(path)
        with patch.object(self.api, 'get', get), self.assertRaises(ValueError): fixture.accept()
        self.native_bridge['status'] = 'failed'
        with self.assertRaises(ValueError): fixture.accept()

    def test_completed_routed_successor_accepts_only_its_actual_native_lineage(self):
        fixture = A['ExecutorAcceptanceTest'](); fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        # Reuse the completed successor's independently acquired old/new evidence.
        self.f = fixture.f
        self.api = fixture.api
        self.routed(status='success')
        # Preserve acceptance's completed child inventories while adding compiler reads.
        route_get = self.api.get
        def get(path):
            if path.endswith('/pipelines/1000'):
                return R['canonical'](dict(fixture.pipeline, source='parent_pipeline'))
            if '/pipelines/1000/jobs?' in path:
                return R['canonical'](fixture.jobs)
            return route_get(path)
        self.api.get = get
        fixture.bootstrap['route'] = self.selector
        fixture.reseal()
        accepted = fixture.accept()
        self.assertEqual(accepted['accepted']['bootstrap']['route'], self.selector)
        self.bridge['allow_failure'] = True
        with self.assertRaises(ValueError): fixture.accept()


if __name__ == '__main__':
    unittest.main()
