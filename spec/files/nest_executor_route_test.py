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
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
M = runpy.run_path(str(ROOT / 'scripts/nest-executor-bootstrap.py'))
T = runpy.run_path(str(ROOT / 'spec/files/nest_executor_bootstrap_test.py'))
A = runpy.run_path(str(ROOT / 'spec/files/nest_executor_accept_test.py'))
R = M['R']


class ExecutorRouteTest(unittest.TestCase):
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
