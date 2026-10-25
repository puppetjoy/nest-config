#!/usr/bin/env python3
"""Offline split recipe/executor identities; never native build or host proof."""

import copy
import hashlib
import runpy
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
M = runpy.run_path(str(ROOT / 'spec/files/nest_release_manifest_test.py'))
B = runpy.run_path(str(ROOT / 'spec/files/nest_release_bind_test.py'))
A = runpy.run_path(str(ROOT / 'spec/files/nest_release_assemble_test.py'))
G = runpy.run_path(str(ROOT / 'spec/files/nest_release_graph_test.py'))
E = runpy.run_path(str(ROOT / 'spec/files/nest_executor_bootstrap_test.py'))
R = B['R']
EXECUTOR_SOURCE = 'e' * 40


def split_executor(api):
    """Explicitly synthetic old executor, leaving recipe/input job identities alone."""
    seen = set()

    def visit(value):
        if not isinstance(value, (dict, list)) or id(value) in seen:
            return
        seen.add(id(value))
        if isinstance(value, list):
            for row in value:
                visit(row)
            return
        if value.get('kind') == 'nest_release_expectations':
            value['schema'] = 2
        if set(value) == {'source', 'image'}:
            value['source'] = EXECUTOR_SOURCE
        if value.get('kind') == 'nest_config_executor_member':
            value['sha'] = EXECUTOR_SOURCE
            value['inputs']['source'] = EXECUTOR_SOURCE
            for module in value['inputs']['modules']:
                if module['name'] == 'nest':
                    module['git_head'] = EXECUTOR_SOURCE
        for row in value.values():
            visit(row)

    for value in vars(api).values():
        visit(value)
    job = api.jobs[('nest/config', 901)]
    job['pipeline']['sha'] = job['commit']['id'] = EXECUTOR_SOURCE
    inputs = next(row for (project, _, path), row in api.artifacts.items()
                  if project == 'nest/config' and path == 'release-inputs/expectations.json')
    for (_, _, path), row in api.artifacts.items():
        if path.startswith('release-results/'):
            row['expectations_digest'] = R['digest'](inputs)


class SourceContractTest(unittest.TestCase):
    def fixture(self, cls):
        fixture = cls()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def test_schema_one_keeps_same_source_and_schema_two_keeps_literal_pins(self):
        expected, candidate = M['fixture']()
        expected['executor']['source'] = EXECUTOR_SOURCE
        with self.assertRaisesRegex(ValueError, 'stale config source'):
            R['expectations'](expected)
        expected['schema'] = 2
        for output in candidate['outputs']:
            output['executor'] = copy.deepcopy(expected['executor'])
        candidate['expectations_digest'] = R['digest'](expected)
        result = R['validate'](expected, candidate)
        self.assertEqual(result['expectations'], expected)
        self.assertNotEqual(expected['executor']['source'], expected['sources']['nest/config'])
        for version in (True, 2.0, '2', 0, 3):
            with self.subTest(version=version), self.assertRaises(ValueError):
                R['expectations'](dict(expected, schema=version))
        for source in ('e' * 39, 'E' * 40, EXECUTOR_SOURCE + '\n', None, True):
            broken = copy.deepcopy(expected)
            broken['executor']['source'] = source
            with self.subTest(source=source), self.assertRaises(ValueError):
                R['expectations'](broken)

    def test_schema_version_and_each_source_remain_in_frozen_digest(self):
        for field in ('schema', 'recipe', 'executor'):
            expected, candidate = M['fixture']()
            expected['schema'] = 2
            candidate['expectations_digest'] = R['digest'](expected)
            if field == 'schema': expected['schema'] = 1
            if field == 'recipe': expected['sources']['nest/config'] = 'f' * 40
            if field == 'executor': expected['executor']['source'] = EXECUTOR_SOURCE
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'changed inputs/matrix'):
                R['validate'](expected, candidate)

    def test_binding_acquires_old_executor_but_current_recipe_input_job(self):
        api = B['FakeGitLab']()
        split_executor(api)
        api.reseal()
        before = copy.deepcopy(api.request)
        expected, receipt = B['BIND']['bind'](api.request, api)
        self.assertEqual(api.request, before)
        self.assertEqual(receipt['executor_job']['source'], EXECUTOR_SOURCE)
        self.assertEqual(receipt['predecessors'][1]['job']['source'], expected['sources']['nest/config'])
        self.assertEqual(expected['members'][0]['bases'], api.result['output']['artifacts'])
        self.assertFalse(receipt['promotion_authorized'])

    def test_binding_cannot_mix_predecessor_schema_or_executor_closures(self):
        for field in ('schema', 'executor'):
            api = B['FakeGitLab']()
            split_executor(api)
            if field == 'schema': api.expected['schema'] = 1
            else: api.expected['executor'] = dict(api.expected['executor'], source='f' * 40)
            api.reseal()
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'different release or source closure'):
                B['BIND']['bind'](api.request, api)

    def test_assembly_keeps_native_recipe_lineage_and_separate_executor(self):
        api = A['MatrixGitLab']()
        split_executor(api)
        result = A['A']['assemble'](api.request, api)
        self.assertEqual(result['executor']['job']['source'], EXECUTOR_SOURCE)
        self.assertEqual(result['manifest']['expectations'], api.request['expectations'])
        for observed in result['members'].values():
            self.assertEqual(observed['native']['root']['sha'], api.expected['sources']['nest/config'])

    def test_wrong_executor_job_commit_or_receipt_still_refuses(self):
        for field in ('job', 'receipt', 'image', 'modules'):
            api = A['MatrixGitLab']()
            split_executor(api)
            if field == 'job': api.jobs[('nest/config', 901)]['commit']['id'] = api.expected['sources']['nest/config']
            if field == 'receipt': api.executor['sha'] = api.expected['sources']['nest/config']
            if field == 'image': api.executor['image'] = M['image'](999)
            if field == 'modules': api.executor['inputs']['modules'][0]['git_head'] = api.expected['sources']['nest/config']
            with self.subTest(field=field), self.assertRaises(ValueError):
                A['A']['assemble'](api.request, api)

    def test_graph_compiler_and_descendant_freezer_preserve_both_sources(self):
        fixture = self.fixture(G['GraphTest'])
        split_executor(fixture.api)
        fixture.node_env['RELEASE_GRAPH_INPUT_SHA256'] = hashlib.sha256(R['canonical'](fixture.request)).hexdigest()
        G['G']['compile_graph'](fixture.request, fixture.env)
        G['G']['freeze_node'](fixture.node_env, fixture.api)
        frozen = R['load'](fixture.f.checkout / 'release-inputs/expectations.json')
        closure = R['load'](fixture.f.checkout / 'release-inputs/closure.json')
        self.assertEqual(frozen['schema'], 2)
        self.assertEqual(frozen['sources']['nest/config'], fixture.f.sha)
        self.assertEqual(frozen['executor']['source'], EXECUTOR_SOURCE)
        self.assertEqual(closure['sources'], fixture.request['expectations']['sources'])
        route = R['load'](fixture.f.checkout / 'release-inputs/candidate.yml')['Build frozen member']
        self.assertEqual(route['variables']['RELEASE_EXECUTOR_JOB_ID'], '901')
        self.assertEqual(route['variables']['RELEASE_EXECUTOR_IMAGE'], frozen['executor']['image'])

    def test_graph_recipe_cannot_be_relabelled_as_executor_source(self):
        fixture = self.fixture(G['GraphTest'])
        split_executor(fixture.api)
        fixture.request['expectations']['sources']['nest/config'] = EXECUTOR_SOURCE
        with self.assertRaisesRegex(ValueError, 'wrong graph source'):
            G['G']['compile_graph'](fixture.request, fixture.env)
        self.assertFalse((fixture.f.checkout / 'release-graph').exists())

    def test_graph_final_acceptance_keeps_exact_split_source_closure(self):
        fixture = self.fixture(G['GraphTest'])
        split_executor(fixture.api)
        fixture.node_env['RELEASE_GRAPH_INPUT_SHA256'] = hashlib.sha256(R['canonical'](fixture.request)).hexdigest()
        env = fixture.completed()
        receipt = G['G']['accept_graph'](env, fixture.api)
        expected = receipt['rebuilt']['manifest']['expectations']
        self.assertEqual(expected['schema'], 2)
        self.assertEqual(expected['sources']['nest/config'], fixture.f.sha)
        self.assertEqual(expected['executor']['source'], EXECUTOR_SOURCE)
        self.assertEqual(receipt['rebuilt']['executor']['job']['source'], EXECUTOR_SOURCE)
        self.assertEqual(R['load'](fixture.f.checkout / 'release-graph-acceptance/receipt.json'), receipt)
        self.assertFalse(receipt['promotion_authorized'])

    def test_bootstrap_retains_exact_sources_without_requiring_gratuitous_source_changes(self):
        fixture = self.fixture(E['ExecutorBootstrapTest'])
        split_executor(fixture.api)
        fixture.reseal()
        result = fixture.acquire()
        self.assertEqual(result['predecessor']['executor_job']['source'], EXECUTOR_SOURCE)
        self.assertEqual(result['predecessor']['input_job']['source'], fixture.api.expected['sources']['nest/config'])
        self.assertEqual(result['successor']['source'], fixture.f.sha)
        self.assertEqual(len({result['predecessor']['executor_job']['source'],
                              result['predecessor']['input_job']['source'], result['successor']['source']}), 3)
        same = E['M']['acquire'](dict(fixture.request, successor_source=EXECUTOR_SOURCE), EXECUTOR_SOURCE, 'haswell', fixture.api)
        E['M']['successor_boundary'](same, 1000, 1001)
        self.assertEqual(same['predecessor'], result['predecessor'])
        self.assertEqual(same['successor']['source'], EXECUTOR_SOURCE)
        self.assertEqual(same['successor']['base_image'], result['successor']['base_image'])


if __name__ == '__main__':
    unittest.main()
