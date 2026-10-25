#!/usr/bin/env python3
"""Offline exact old-executor/OpenBolt/successor fixtures; no real builds."""

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
T = runpy.run_path(str(ROOT / 'spec/files/nest_release_bind_test.py'))
I = runpy.run_path(str(ROOT / 'spec/files/nest_release_inputs_test.py'))
R = M['R']


class BootstrapGitLab(T['FakeGitLab']):
    def get(self, path):
        if '/pipelines/' not in path:
            return super().get(path)
        self.reads.append(path)
        if path.endswith('/pipelines/5'):
            return R['canonical'](self.pipeline)
        if '/bridges?' in path:
            return R['canonical'](self.outgoing)
        return R['canonical']([self.jobs[('nest/tools/bolt', 105)]] + self.extra_jobs)


class ExecutorBootstrapTest(unittest.TestCase):
    request: dict[str, Any]

    def setUp(self):
        self.fixture = I['ReleaseInputsTest']()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.f = self.fixture
        self.api = BootstrapGitLab()
        expected, candidate = T['MANIFEST']['fixture']()
        member = expected['members'][-1]
        expected['members'] = [member]
        for row in expected['consumers']:
            if row['project'] != 'nest/tools/bolt':
                row.update(decision='defer', members=[])
        self.api.expected = expected
        self.api.executor = T['receipt'](expected)
        output = candidate['outputs'][-1]
        output['artifacts']['image'] = 'registry.gitlab.joyfullee.me/nest/tools/bolt/main@sha256:' + 'b' * 64
        self.api.result = dict(schema=1, kind='nest_release_member_result', release=expected['release'],
                               expectations_digest=R['digest'](expected),
                               executor_receipt=self.api.executor, output=output)
        self.api.jobs = {('nest/config', 901): self.api.make_job('nest/config', 900, 901, 'Build haswell'),
                         ('nest/config', 801): self.api.make_job('nest/config', 800, 801, 'Freeze release inputs'),
                         ('nest/tools/bolt', 105): self.api.make_job('nest/tools/bolt', 5, 105, 'Candidate haswell')}
        self.api.artifacts = {('nest/config', 901, 'executor-receipts/haswell.json'): self.api.executor,
                              ('nest/config', 801, 'release-inputs/expectations.json'): expected,
                              ('nest/tools/bolt', 105, 'release-results/tool.json'): self.api.result}
        for job in self.api.jobs.values():
            job['allow_failure'] = False
        self.api.pipeline = dict(id=5, project_id=10, sha=expected['sources']['nest/tools/bolt'],
                                 ref='main', source='pipeline', status='success')
        self.api.outgoing = []
        self.api.extra_jobs = []
        self.request = dict(schema=1, kind='nest_executor_bootstrap', successor_source=self.f.sha,
                            successor_cpu='haswell', producer=dict(project='nest/tools/bolt', pipeline=5, job=105,
                                                                  member='tool', input_pipeline=800, input_job=801,
                                                                  input_sha256='', result_sha256=''))
        self.env = {k: v for k, v in self.f.env.items() if k != 'RELEASE_INPUTS'}
        self.env.update(EXECUTOR_BOOTSTRAP='true', RELEASE_BOOTSTRAP_FILE=str(self.f.input),
                        EXECUTOR_ONLY='true', BUILD='haswell', CPU='haswell', CI_PIPELINE_SOURCE='api')
        self.reseal()

    def reseal(self):
        self.api.result['expectations_digest'] = R['digest'](self.api.expected)
        self.request['producer']['input_sha256'] = hashlib.sha256(R['canonical'](self.api.expected)).hexdigest()
        self.request['producer']['result_sha256'] = hashlib.sha256(R['canonical'](self.api.result)).hexdigest()
        self.f.input.write_bytes(R['canonical'](self.request))

    def acquire(self):
        return M['acquire'](self.request, self.f.sha, 'haswell', self.api)

    def publish(self, **changes):
        return M['publish'](self.f.input, dict(self.env, **changes), self.api)

    def test_distinct_boundary_keeps_original_bytes_and_source_closure(self):
        before = copy.deepcopy(self.api.artifacts)
        result = self.acquire()
        self.assertEqual(self.api.artifacts, before)
        self.assertEqual(result['predecessor']['expectations'], self.api.expected)
        self.assertNotEqual(result['predecessor']['expectations']['sources']['nest/config'], result['successor']['source'])
        self.assertEqual(result['successor']['base_image'], self.api.result['output']['artifacts']['image'])
        self.assertEqual(result['successor']['build'], 'not_started')
        self.assertFalse(result['promotion_authorized'])
        self.assertEqual(result['image_compatibility_verification'], 'not_performed')
        self.assertTrue(all('/pipelines/' not in path or '/pipelines/5' in path for path in self.api.reads))
        self.assertFalse(any('latest' in path for path in self.api.reads))

    def test_digest_named_result_and_every_executor_architecture(self):
        for cpu in M['CPUS']:
            with self.subTest(cpu=cpu):
                self.api.expected['members'][0]['cpu'] = cpu
                self.api.result['output']['member']['cpu'] = cpu
                self.api.executor['cpu'] = cpu
                self.api.jobs[('nest/config', 901)]['name'] = 'Build ' + cpu
                self.api.artifacts = {('nest/config', 901, 'executor-receipts/' + cpu + '.json'): self.api.executor,
                                      ('nest/config', 801, 'release-inputs/expectations.json'): self.api.expected,
                                      ('nest/tools/bolt', 105, 'release-results/tool.json'): self.api.result}
                self.request['successor_cpu'] = cpu
                self.reseal()
                T['digest_results'](self.api.artifacts)
                result = M['acquire'](self.request, self.f.sha, cpu, self.api)
                self.assertEqual(result['successor']['cpu'], cpu)

    def test_selection_requires_explicit_single_architecture_and_source(self):
        plain = {key: value for key, value in self.env.items() if key not in M['KEYS']}
        self.assertFalse(M['selected'](plain))
        for key in M['KEYS']:
            with self.subTest(key=key), self.assertRaises(ValueError):
                M['selected'](dict(plain, **{key: 'true'}))
        for key, value in [('EXECUTOR_BOOTSTRAP', 'false'), ('EXECUTOR_ONLY', ''), ('BUILD', ''),
                           ('BUILD', 'zen5'), ('BUILD', 'haswell\n'), ('CI_COMMIT_TAG', 'v1'),
                           ('CI_PIPELINE_SOURCE', 'parent_pipeline'), ('CI_PIPELINE_SOURCE', 'push'),
                           ('CI_PIPELINE_SOURCE', 'merge_request_event'), ('CI_PIPELINE_SOURCE', 'schedule')]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                M['selected'](dict(self.env, **{key: value}))
        for key in M['CONFLICTS']:
            for value in ('false', ' ', '\n'):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    M['selected'](dict(self.env, **{key: value}))
        self.assertEqual(self.api.reads, [])

    def test_wrong_schema_selector_or_successor_refuses_before_external_reads(self):
        for key, value in [('schema', True), ('kind', 'other'), ('successor_source', 'f' * 40),
                           ('successor_cpu', 'cortex-a53'), ('extra', 'no')]:
            before = copy.deepcopy(self.request)
            self.request[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): self.acquire()
            self.request = before
        for key, value in [('project', 'nest/stage0'), ('job', True), ('pipeline', 0),
                           ('member', '../unsafe'), ('input_job', '801'), ('input_sha256', 'a' * 64 + '\n'),
                           ('result_sha256', 'invalid')]:
            before = copy.deepcopy(self.request)
            self.request['producer'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): self.acquire()
            self.request = before
        self.assertEqual(self.api.reads, [])

    def test_same_config_revision_is_valid_for_a_distinct_successor_build(self):
        self.request['successor_source'] = self.api.expected['sources']['nest/config']
        result = M['acquire'](self.request, self.request['successor_source'], 'haswell', self.api)
        M['successor_boundary'](result, 1000, 1001)
        self.assertEqual(result['successor']['source'], self.api.expected['sources']['nest/config'])
        self.assertEqual(result['successor']['base_image'], self.api.result['output']['artifacts']['image'])

    def test_same_revision_does_not_allow_self_dependent_build_resources(self):
        result = self.acquire()
        for pipeline, job in ((900, 1001), (800, 1001), (1000, 901), (1000, 801)):
            with self.subTest(pipeline=pipeline, job=job), self.assertRaises(ValueError):
                M['successor_boundary'](result, pipeline, job)
            with self.subTest(publication=(pipeline, job)), self.assertRaises(ValueError):
                self.publish(CI_PIPELINE_ID=str(pipeline), CI_JOB_ID=str(job))
            self.assertFalse((self.f.checkout / 'executor-bootstrap').exists())

    def test_wrong_cpu_variant_reuse_and_non_bolt_output_refuse(self):
        for target, key, value in [(self.api.expected['members'][0], 'cpu', 'zen5'),
                                   (self.api.expected['members'][0], 'variant', 'workstation')]:
            # All selected member/consumer relationships are validated, even before
            # the corresponding result/schema check.
            before = copy.deepcopy(target)
            target[key] = value
            self.reseal()
            with self.subTest(key=key), self.assertRaises(ValueError): self.acquire()
            target.clear(); target.update(before)
        bolt = next(c for c in self.api.expected['consumers'] if c['project'] == 'nest/tools/bolt')
        bolt['decision'] = 'reuse'; self.reseal()
        with self.assertRaises(ValueError): self.acquire()

    def test_mutable_wrong_registry_or_wrong_executor_receipt_refuses(self):
        image = self.api.result['output']['artifacts']['image']
        for value in ('nest/tools/bolt:latest', 'registry.example/nest/tools/bolt/main@sha256:' + 'b' * 64,
                      'registry.gitlab.joyfullee.me/nest/tools/pdk/main@sha256:' + 'b' * 64):
            self.api.result['output']['artifacts']['image'] = value
            self.reseal()
            with self.subTest(image=value), self.assertRaises(ValueError): self.acquire()
        self.api.result['output']['artifacts']['image'] = image
        self.reseal()
        observed = copy.deepcopy(self.api.executor)
        observed['inputs']['base_image'] = T['MANIFEST']['image'](100)
        self.api.artifacts[('nest/config', 901, 'executor-receipts/haswell.json')] = observed
        with self.assertRaises(ValueError): self.acquire()

    def test_each_failed_erased_moved_or_wrong_named_resource_refuses(self):
        for key in self.api.jobs:
            for field, value in [('status', 'failed'), ('erased_at', 'fixture'), ('name', 'Wrong job')]:
                row = self.api.jobs[key]; before = copy.deepcopy(row)
                row[field] = value
                with self.subTest(job=key, field=field):
                    if key == ('nest/tools/bolt', 105) and field == 'name':
                        # Source-owned candidate names differ across OpenBolt CPU
                        # recipes. Exact member/result identity is authoritative.
                        self.acquire()
                    else:
                        with self.assertRaises(ValueError): self.acquire()
                row.clear(); row.update(before)
        self.api.jobs[('nest/tools/bolt', 105)]['commit']['id'] = 'f' * 40
        with self.assertRaises(ValueError): self.acquire()

    def test_failed_non_native_looping_or_hidden_failed_openbolt_pipeline_refuses(self):
        for key, value in [('status', 'running'), ('status', 'failed'), ('source', 'api'), ('sha', 'f' * 40)]:
            before = copy.deepcopy(self.api.pipeline)
            self.api.pipeline[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): self.acquire()
            self.api.pipeline = before
        self.api.outgoing = [dict(id=600)]
        with self.assertRaises(ValueError): self.acquire()
        self.api.outgoing = []
        self.api.extra_jobs = [dict(id=106, status='failed', allow_failure=True, name='Hidden failure')]
        with self.assertRaises(ValueError): self.acquire()

    def test_raw_hashes_and_resource_races_refuse(self):
        for key in ('input_sha256', 'result_sha256'):
            old = self.request['producer'][key]
            self.request['producer'][key] = 'f' * 64
            with self.subTest(key=key), self.assertRaises(ValueError): self.acquire()
            self.request['producer'][key] = old
        self.api.mutate_after_result = lambda api: api.jobs[('nest/config', 801)].update(erased_at='fixture')
        with self.assertRaises(ValueError): self.acquire()

    def test_artifact_changed_after_first_read_refuses(self):
        original = self.api.get
        calls = 0

        def get(path):
            nonlocal calls
            raw = original(path)
            if path.endswith('expectations.json'):
                calls += 1
                if calls == 2: raw += b' '
            return raw

        with patch.object(self.api, 'get', get), self.assertRaises(ValueError): self.acquire()

    def test_publisher_reopens_and_does_not_replace_or_need_original_request(self):
        image = self.publish()
        self.f.input.unlink()
        directory = self.f.checkout / 'executor-bootstrap'
        receipt = json.loads((directory / 'receipt.json').read_bytes())
        self.assertEqual((directory / 'bolt.ref').read_text(), image + '\n')
        self.assertEqual(receipt['successor']['source'], self.f.sha)
        self.assertEqual(receipt['successor']['job'], 902)
        self.f.input.write_bytes(R['canonical'](self.request))
        with self.assertRaises(FileExistsError): self.publish()
        self.assertEqual(json.loads((directory / 'receipt.json').read_bytes()), receipt)

    def test_dirty_wrong_cpu_or_wrong_source_refuses_before_gets(self):
        for key, value in [('CI_PROJECT_PATH', 'nest/tools/bolt'), ('CI_PROJECT_ID', '4'),
                           ('CPU', 'cortex-a53'), ('CI_COMMIT_SHA', 'f' * 40), ('CI_JOB_ID', '01')]:
            with self.subTest(key=key), self.assertRaises(ValueError): self.publish(**{key: value})
        (self.f.checkout / 'tracked').write_text('modified')
        with self.assertRaises(ValueError): self.publish()
        self.assertEqual(self.api.reads, [])
        self.assertFalse((self.f.checkout / 'executor-bootstrap').exists())

    def test_failed_readback_and_symlink_input_refuse(self):
        original = Path.read_bytes

        def read(path):
            return b'changed' if path.name == 'bolt.ref' else original(path)

        with patch.object(Path, 'read_bytes', read), self.assertRaises(ValueError): self.publish()
        linked = self.f.root / 'linked.json'; linked.symlink_to(self.f.input)
        with self.assertRaises(ValueError): M['publish'](linked, self.env, self.api)

    def test_real_cli_exact_GET_acquisition_retains_after_exit(self):
        replies = {}
        original = self.api.get

        def get(path):
            raw = original(path); replies[path] = raw; return raw

        with patch.object(self.api, 'get', get): self.acquire()
        binary = self.f.root / 'bin'; binary.mkdir()
        T['fake_glab'](binary / 'glab', replies)
        env = dict(self.env, PATH=str(binary) + os.pathsep + self.env['PATH'])
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/nest-executor-bootstrap.py'), '--ci-base'],
                                env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.f.input.unlink()
        image = self.api.result['output']['artifacts']['image']
        self.assertEqual(result.stdout, image + '\n')
        self.assertEqual((self.f.checkout / 'executor-bootstrap/bolt.ref').read_text(), image + '\n')
        self.assertNotIn('Traceback', result.stderr)

    def test_ordinary_ci_base_preserves_existing_default_and_override(self):
        env = {key: value for key, value in self.env.items() if key not in M['KEYS']}
        script = str(ROOT / 'scripts/nest-executor-bootstrap.py')
        for override in (None, 'fixture.invalid/pinned@sha256:' + 'b' * 64):
            child = dict(env)
            if override: child['BOLT_IMAGE'] = override
            else: child.pop('BOLT_IMAGE', None)
            result = subprocess.run([sys.executable, script, '--ci-base'], env=child, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, (override or 'nest/tools/bolt') + '\n')
        self.assertFalse((self.f.checkout / 'executor-bootstrap').exists())


if __name__ == '__main__':
    unittest.main()
