#!/usr/bin/env python3
"""Offline native DAG compiler and actual predecessor-freezing fault fixtures."""

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
G = runpy.run_path(str(ROOT / 'scripts/nest-release-graph.py'))
F = runpy.run_path(str(ROOT / 'spec/files/nest_release_bind_test.py'))
P = runpy.run_path(str(ROOT / 'spec/files/nest_release_inputs_test.py'))
R = G['R']


def request(expected) -> Any:
    nodes = []
    for member in expected['members']:
        edges = [dict(base=role, producer='stage0', artifact=role) for role in ('normal', 'debug')] if member['id'] == 'stage1' else []
        nodes.append(dict(member=member['id'], job_name='Candidate haswell' if member['stage'] == 'stage0' else 'Candidate haswell-server',
                          placement=None, bindings=edges))
    return dict(schema=1, kind='nest_release_graph', expectations=copy.deepcopy(expected),
                executor_job=dict(pipeline=900, job=901), nodes=nodes)


class NativeGraph(F['FakeGitLab']):
    after_get: Any

    def __init__(self, expected):
        super().__init__()
        self.expected = expected
        self.executor = F['receipt'](expected)
        self.graph = request(expected)
        self.jobs[('nest/config', 901)] = self.make_job('nest/config', 900, 901, 'Build haswell')
        self.jobs[('nest/config', 601)] = self.make_job('nest/config', 600, 601, 'Compile release graph')
        self.jobs[('nest/config', 801)] = self.make_job('nest/config', 650, 801, 'Freeze release inputs stage0')
        self.jobs[('nest/config', 9011)] = self.make_job('nest/config', 650, 9011, 'Freeze release inputs stage1')
        self.jobs[('nest/stage0', 101)] = self.make_job('nest/stage0', 1, 101, 'Candidate haswell')
        for job in self.jobs.values(): job['allow_failure'] = False
        self.jobs[('nest/config', 9011)]['status'] = 'running'
        self.result['release'] = expected['release']
        self.result['executor_receipt'] = self.executor
        projected = G['I']['project_member'](expected, 'stage0')
        self.result['expectations_digest'] = R['digest'](projected)
        self.result['output']['member'] = copy.deepcopy(expected['members'][0])
        self.result['output']['executor'] = expected['executor']
        self.result['output']['producer']['sha'] = expected['sources']['nest/stage0']
        self.artifacts = {('nest/config', 901, 'executor-receipts/haswell.json'): self.executor,
                          ('nest/config', 601, 'release-graph/request.json'): self.graph,
                          ('nest/config', 801, 'release-inputs/expectations.json'): projected,
                          ('nest/stage0', 101, 'release-results/stage0.json'): self.result}
        self.pipelines = {i: self.pipeline(i, source, status) for i, source, status in (
            (600, 'api', 'running'), (650, 'parent_pipeline', 'running'),
            (850, 'parent_pipeline', 'success'))}
        self.pipelines[1] = self.pipeline(1, 'pipeline', 'success', project='nest/stage0')
        self.bridges = {
            600: [self.bridge(610, 'Run release graph', 600, 650, 'running')],
            650: [self.bridge(660, 'Release node stage0', 650, 850)],
            850: [self.bridge(860, 'Build frozen member', 850, 1)], 1: []}
        self.pipeline_jobs = {650: [self.jobs[('nest/config', 801)], self.jobs[('nest/config', 9011)]],
                              1: [self.jobs[('nest/stage0', 101)]]}
        self.after_get = None

    def pipeline(self, number, source, status, project='nest/config'):
        return dict(id=number, project_id=3 if project == 'nest/config' else 10,
                    sha=self.expected['sources'][project], ref='main', source=source, status=status)

    def bridge(self, number, name, parent, child, status='success'):
        return dict(id=number, name=name, status=status, allow_failure=False,
                    pipeline=copy.deepcopy(self.pipelines[parent]),
                    downstream_pipeline=copy.deepcopy(self.pipelines.get(child)))

    def get(self, path):
        parts = path.split('/')
        if len(parts) >= 4 and parts[2] == 'pipelines':
            number = int(parts[3])
            if len(parts) == 4: row = self.pipelines[number]
            elif parts[4].startswith('bridges'): row = self.bridges[number]
            else: row = self.pipeline_jobs[number]
            self.reads.append(path)
            raw = R['canonical'](row)
        else:
            raw = super().get(path)
        if self.after_get: self.after_get(path)
        return raw


class GraphTest(unittest.TestCase):
    leaf: Any

    def setUp(self):
        self.f = P['ReleaseInputsTest']()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        base = F['FakeGitLab']().expected
        base['sources']['nest/config'] = self.f.sha
        base['executor'].update(source=self.f.sha, image='registry.gitlab.joyfullee.me/nest/config/main@sha256:' + 'e' * 64)
        self.api = NativeGraph(base)
        self.request = self.api.graph
        self.env = dict(self.f.env, CI_PIPELINE_SOURCE='api', CI_PIPELINE_ID='600', CI_JOB_ID='601',
                        CI_COMMIT_BRANCH='main',
                        CI_JOB_NAME='Compile release graph', RELEASE_GRAPH='true', RELEASE_GRAPH_FILE='/fixture/graph.json')
        self.env.pop('RELEASE_INPUTS')
        self.node_env = dict(self.f.env, CI_PIPELINE_SOURCE='parent_pipeline', CI_PIPELINE_ID='650', CI_JOB_ID='9011',
                             CI_JOB_NAME='Freeze release inputs stage1', RELEASE_GRAPH_NODE='true', RELEASE_GRAPH_MEMBER='stage1',
                             RELEASE_GRAPH_INPUT_PIPELINE='600', RELEASE_GRAPH_INPUT_JOB='601',
                             RELEASE_GRAPH_INPUT_SHA256=hashlib.sha256(R['canonical'](self.request)).hexdigest(),
                             RELEASE_GRAPH_ROOT_PIPELINE='650')

    def test_public_compile_refuses_unsupported_topology_without_publication(self):
        completed = subprocess.run([sys.executable, str(ROOT / 'scripts/nest-release-graph.py'), '--compile'],
                                   cwd=self.f.checkout, env=self.env, capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 1)
        self.assertIn('flattened graph acceptance pending', completed.stderr)
        self.assertFalse((self.f.checkout / 'release-graph').exists())

    def verification_request(self):
        expected = G['I']['project_member'](self.request['expectations'], 'stage0')
        expected['members'][0]['mode'] = 'refresh'
        self.request.clear()
        self.request.update(request(expected))
        self.env['RELEASE_GRAPH'] = 'verify-inputs'
        self.node_env.update(RELEASE_GRAPH_NODE='verify-inputs', RELEASE_GRAPH_MEMBER='stage0',
                             CI_JOB_ID='801', CI_JOB_NAME='Freeze release inputs stage0',
                             RELEASE_GRAPH_INPUT_SHA256=hashlib.sha256(R['canonical'](self.request)).hexdigest())
        self.api.jobs[('nest/config', 801)]['status'] = 'running'
        return self.request

    def test_nonexecuting_compile_cli_retains_actual_flattened_freezer_only(self):
        self.verification_request()
        submitted = self.f.root / 'graph.json'
        submitted.write_bytes(R['canonical'](self.request))
        env = dict(self.env, RELEASE_GRAPH_FILE=str(submitted))
        completed = subprocess.run([sys.executable, str(ROOT / 'scripts/nest-release-graph.py'), '--compile'],
                                   env=env, capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        directory = self.f.checkout / 'release-graph'
        graph = R['load'](directory / 'graph.yml')
        self.assertEqual(set(graph), {'workflow', 'stages', 'Freeze release inputs stage0', 'Release node stage0'})
        freezer = graph['Freeze release inputs stage0']
        self.assertEqual(freezer['variables']['RELEASE_GRAPH_NODE'], 'verify-inputs')
        self.assertEqual(freezer['needs'], [])
        self.assertEqual(freezer['script'], ['python3 scripts/nest-release-graph.py --freeze-node'])
        self.assertEqual(graph['Release node stage0']['trigger']['strategy'], 'mirror')
        receipt = R['load'](directory / 'receipt.json')
        self.assertEqual(receipt['kind'], 'nest_release_graph_input_verification_publication')
        self.assertEqual(receipt['request_sha256'], hashlib.sha256((directory / 'request.json').read_bytes()).hexdigest())
        self.assertEqual(receipt['graph_sha256'], hashlib.sha256((directory / 'graph.yml').read_bytes()).hexdigest())
        self.assertEqual(receipt['execution'], 'not_started')
        self.assertFalse(receipt['promotion_authorized'])

    def test_nonexecuting_freezer_uses_real_lineage_and_projection_without_candidate(self):
        self.verification_request()
        G['freeze_node'](self.node_env, self.api)
        directory = self.f.checkout / 'release-inputs'
        route = R['load'](directory / 'candidate.yml')
        self.assertEqual(set(route), {'workflow', 'stages', 'Verify frozen inputs'})
        variables = route['Verify frozen inputs']['variables']
        self.assertEqual(variables['RELEASE_VERIFY_INPUTS'], 'true')
        self.assertEqual(variables['RELEASE_VALIDATE_ONLY'], 'true')
        self.assertNotIn('RELEASE_CANDIDATE', variables)
        self.assertEqual(R['load'](directory / 'closure.json'), self.request['expectations'])
        self.assertIn('input_verification_route', R['load'](directory / 'provenance.json'))
        for path in ('/pipelines/650', '/pipelines/650/jobs?', '/pipelines/600/bridges?',
                     '/jobs/601/artifacts/release-graph/request.json'):
            self.assertTrue(any(path in p for p in self.api.reads), path)

    def test_nonexecuting_selection_refuses_dependent_graph_before_publication(self):
        self.env['RELEASE_GRAPH'] = 'verify-inputs'
        with self.assertRaises(ValueError): G['compile_graph'](self.request, self.env)
        self.assertFalse((self.f.checkout / 'release-graph').exists())
        self.node_env['RELEASE_GRAPH_NODE'] = 'verify-inputs'
        with self.assertRaises(ValueError): G['freeze_node'](self.node_env, self.api)
        self.assertFalse((self.f.checkout / 'release-inputs').exists())

    def test_nonexecuting_mode_refuses_conflicts_unsupported_sources_and_nonrefresh_input(self):
        self.verification_request()
        for value in ('false', 'verify-inputs ', 'VERIFY-INPUTS', ' '):
            with self.subTest(value=value), self.assertRaises(ValueError):
                G['selected'](dict(self.env, RELEASE_GRAPH=value))
        for source in ('pipeline', 'parent_pipeline', 'push', 'merge_request_event', 'schedule'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                G['selected'](dict(self.env, CI_PIPELINE_SOURCE=source))
        for key in G['CONFLICTS']:
            with self.subTest(key=key), self.assertRaises(ValueError):
                G['selected'](dict(self.env, **{key: 'false'}))
        self.request['expectations']['members'][0]['mode'] = 'fresh'
        with self.assertRaises(ValueError): G['compile_graph'](self.request, self.env)
        self.assertFalse((self.f.checkout / 'release-graph').exists())

    def test_nonexecuting_freezer_refuses_changed_compiler_bridge_before_publication(self):
        self.verification_request()
        reads = 0
        def after(path):
            nonlocal reads
            if '/artifacts/executor-receipts/' in path:
                reads += 1
                self.api.bridges[600][0]['id'] += 1
        self.api.after_get = after
        with self.assertRaises(ValueError): G['freeze_node'](self.node_env, self.api)
        self.assertGreater(reads, 0)
        self.assertFalse((self.f.checkout / 'release-inputs').exists())

    def test_compiles_exact_native_dependencies_and_reopens_no_clobber_artifacts(self):
        before = copy.deepcopy(self.request)
        self.env['CI_JOB_TOKEN'] = 'fixture-private-value'
        receipt = G['compile_graph'](self.request, self.env)
        directory = self.f.checkout / 'release-graph'
        graph = json.loads((directory / 'graph.yml').read_bytes())
        self.assertEqual(graph['Freeze release inputs stage0']['needs'], [])
        self.assertEqual(graph['Freeze release inputs stage1']['needs'], ['Release node stage0'])
        for name in ('stage0', 'stage1'):
            job = graph['Release node ' + name]
            freezer = 'Freeze release inputs ' + name
            self.assertEqual(job['needs'], [freezer])
            self.assertFalse(job['allow_failure'])
            self.assertEqual(job['trigger'], dict(include=[dict(artifact='release-inputs/candidate.yml', job=freezer)], strategy='mirror',
                                                 forward=dict(yaml_variables=True, pipeline_variables=False)))
            self.assertEqual(job['inherit'], dict(variables=False))
            self.assertNotIn('variables', job)
            frozen = graph[freezer]
            self.assertEqual(frozen['variables']['RELEASE_GRAPH_ROOT_PIPELINE'], '$CI_PIPELINE_ID')
            self.assertNotIn('RELEASE_GRAPH', frozen['variables'])
            self.assertEqual(frozen['script'], ['python3 scripts/nest-release-graph.py --freeze-node'])
            self.assertEqual(frozen['artifacts'], dict(when='on_success', paths=['release-inputs/']))
        self.assertNotIn(b'fixture-private-value', (directory / 'graph.yml').read_bytes())
        self.assertEqual(hashlib.sha256((directory / 'request.json').read_bytes()).hexdigest(), receipt['request_sha256'])
        self.assertEqual(self.request, before)
        self.assertFalse(receipt['promotion_authorized'])
        with self.assertRaises(FileExistsError): G['compile_graph'](self.request, self.env)

    def test_descendant_freezes_actual_successful_predecessor_pair_before_routing(self):
        before = copy.deepcopy(self.request)
        F['digest_results'](self.api.artifacts)
        receipt = G['freeze_node'](self.node_env, self.api)
        directory = self.f.checkout / 'release-inputs'
        frozen = R['load'](directory / 'expectations.json')
        self.assertEqual([m['id'] for m in frozen['members']], ['stage1'])
        self.assertEqual(frozen['members'][0]['bases'], self.api.result['output']['artifacts'])
        self.assertEqual(self.request, before)
        route = R['load'](directory / 'candidate.yml')['Build frozen member']
        self.assertEqual(route['trigger']['project'], 'nest/stage1')
        self.assertEqual(route['variables']['RELEASE_INPUT_JOB_ID'], '9011')
        self.assertEqual(route['variables']['RELEASE_INPUT_SHA256'], receipt['artifact_sha256'])
        self.assertEqual(route['variables']['RELEASE_EXECUTOR_JOB_ID'], '901')
        self.assertNotIn('RELEASE_GRAPH_NODE', route['variables'])
        self.assertIn('base_discovery', R['load'](directory / 'provenance.json'))
        self.assertNotIn('base_discovery', receipt)
        with self.assertRaises(FileExistsError): G['freeze_node'](self.node_env, self.api)

    def test_root_node_uses_reviewed_pinned_bases_without_predecessor_acquisition(self):
        env = dict(self.node_env, RELEASE_GRAPH_MEMBER='stage0', CI_JOB_ID='801', CI_JOB_NAME='Freeze release inputs stage0')
        self.api.jobs[('nest/config', 801)]['status'] = 'running'
        G['freeze_node'](env, self.api)
        frozen = R['load'](self.f.checkout / 'release-inputs/expectations.json')
        self.assertEqual(frozen, G['I']['project_member'](self.request['expectations'], 'stage0'))
        self.assertEqual(R['load'](self.f.checkout / 'release-inputs/closure.json'), self.request['expectations'])
        self.assertFalse(any('/projects/nest%2Fstage0' in p for p in self.api.reads))

    def test_flattened_freezer_exact_identity_and_no_legacy_or_sibling_substitution(self):
        for change in ('legacy', 'sibling', 'duplicate', 'erased', 'tolerated', 'failed', 'pipeline', 'commit', 'job', 'name'):
            api = NativeGraph(copy.deepcopy(self.api.expected))
            env = dict(self.node_env)
            row = api.jobs[('nest/config', 9011)]
            if change == 'legacy': row['name'] = 'Freeze release inputs'
            if change == 'sibling': row['name'] = 'Freeze release inputs stage0'
            if change == 'duplicate': api.pipeline_jobs[650].append(copy.deepcopy(row))
            if change == 'erased': row['erased_at'] = 'fixture'
            if change == 'tolerated': row['allow_failure'] = True
            if change == 'failed': row['status'] = 'failed'
            if change == 'pipeline': row['pipeline']['id'] = 651
            if change == 'commit': row['commit']['id'] = 'f' * 40
            if change == 'job': env['CI_JOB_ID'] = '9012'
            if change == 'name': env['CI_JOB_NAME'] = 'Freeze release inputs stage1 '
            with self.subTest(change=change), self.assertRaises(ValueError): G['freeze_node'](env, api)
            self.assertFalse((self.f.checkout / 'release-inputs').exists())

    def test_running_siblings_and_volatile_job_fields_do_not_block_exact_predecessor(self):
        self.api.pipeline_jobs[650].append(dict(id=990, name='Freeze release inputs sibling', status='running'))
        def after(path):
            if '/pipelines/650/jobs?' in path:
                row = self.api.jobs[('nest/config', 9011)]
                row['duration'] = row.get('duration', 0) + 1
                row['runner'] = dict(contacted_at=str(row['duration']))
        self.api.after_get = after
        G['freeze_node'](self.node_env, self.api)
        self.assertTrue((self.f.checkout / 'release-inputs/candidate.yml').exists())

    def test_running_freezer_replacement_during_acquisition_refuses_before_publication(self):
        def after(path):
            if path.endswith('/jobs/901/artifacts/executor-receipts/haswell.json'):
                self.api.jobs[('nest/config', 9011)]['id'] = 9012
        self.api.after_get = after
        with self.assertRaises(ValueError): G['freeze_node'](self.node_env, self.api)
        self.assertFalse((self.f.checkout / 'release-inputs').exists())

    def test_predecessor_bridge_volatile_metadata_does_not_change_native_identity(self):
        def after(path):
            if '/pipelines/650/bridges?' in path:
                bridge = self.api.bridges[650][0]
                bridge['duration'] = bridge.get('duration', 0) + 1
                bridge['user'] = dict(name='Changing display metadata')
        self.api.after_get = after
        G['freeze_node'](self.node_env, self.api)
        self.assertTrue((self.f.checkout / 'release-inputs/candidate.yml').exists())

    def test_stable_predecessor_observation_keeps_every_safety_identity(self):
        _, original = G['native_node'](self.api, self.request, 650, 'stage0')
        for field in ('id', 'name', 'status', 'allow_failure', 'parent-id', 'parent-project',
                      'parent-source', 'child-id', 'child-project', 'child-source', 'child-ref', 'child-status'):
            api = NativeGraph(copy.deepcopy(self.api.expected))
            bridge = api.bridges[650][0]
            changes = {
                'id': (bridge, 'id', 999), 'name': (bridge, 'name', 'Other'),
                'status': (bridge, 'status', 'failed'), 'allow_failure': (bridge, 'allow_failure', True),
                'parent-id': (bridge['pipeline'], 'id', 999),
                'parent-project': (bridge['pipeline'], 'project_id', 999),
                'parent-source': (bridge['pipeline'], 'sha', 'f' * 40),
                'child-id': (bridge['downstream_pipeline'], 'id', 999),
                'child-project': (bridge['downstream_pipeline'], 'project_id', 999),
                'child-source': (bridge['downstream_pipeline'], 'sha', 'f' * 40),
                'child-ref': (bridge['downstream_pipeline'], 'ref', 'other'),
                'child-status': (bridge['downstream_pipeline'], 'status', 'failed'),
            }
            row, key, value = changes[field]
            row[key] = value
            with self.subTest(field=field):
                try:
                    _, changed = G['native_node'](api, self.request, 650, 'stage0')
                except (ValueError, KeyError):
                    continue
                self.assertNotEqual(original, changed)

    def test_flattened_predecessor_refuses_ambiguous_or_wrong_freezer_and_old_node_layer(self):
        for change in ('legacy', 'duplicate', 'failed', 'old-node', 'extra-route'):
            api = NativeGraph(copy.deepcopy(self.api.expected))
            if change == 'legacy': api.jobs[('nest/config', 801)]['name'] = 'Freeze release inputs'
            if change == 'duplicate':
                extra = copy.deepcopy(api.jobs[('nest/config', 801)])
                extra.update(id=802, name='Freeze release inputs')
                api.pipeline_jobs[650].append(extra)
            if change == 'failed': api.jobs[('nest/config', 801)]['status'] = 'failed'
            if change == 'old-node': api.pipelines[850]['source'] = 'pipeline'
            if change == 'extra-route': api.bridges[850].append(dict(id=870, name='Unexpected'))
            with self.subTest(change=change), self.assertRaises(ValueError):
                G['native_node'](api, self.request, 650, 'stage0')

    def test_partial_modes_conflicts_and_nonoperator_graph_sources_refuse(self):
        plain = {k: v for k, v in self.env.items() if k not in G['KEYS']}
        self.assertIsNone(G['selected'](plain))
        for key in G['KEYS']:
            with self.subTest(key=key), self.assertRaises(ValueError): G['selected'](dict(plain, **{key: 'false'}))
        for source in ('pipeline', 'parent_pipeline', 'push', 'merge_request_event', 'schedule', ''):
            with self.subTest(source=source), self.assertRaises(ValueError): G['selected'](dict(self.env, CI_PIPELINE_SOURCE=source))
        for key in G['CONFLICTS']:
            with self.subTest(key=key), self.assertRaises(ValueError): G['selected'](dict(self.env, **{key: 'false'}))
        for source in ('api', 'pipeline', 'push', 'trigger'):
            with self.assertRaises(ValueError): G['selected'](dict(self.node_env, CI_PIPELINE_SOURCE=source))

    def test_schema_coverage_pair_compatibility_expansion_and_cycles_refuse(self):
        for change in ('missing', 'duplicate', 'partial', 'wrong-role', 'self', 'unknown', 'mode', 'expansion', 'schema', 'architecture'):
            candidate = copy.deepcopy(self.request)
            if change == 'missing': candidate['nodes'].pop()
            if change == 'duplicate': candidate['nodes'].append(copy.deepcopy(candidate['nodes'][0]))
            if change == 'partial': candidate['nodes'][1]['bindings'].pop()
            if change == 'wrong-role': candidate['nodes'][1]['bindings'][0]['artifact'] = 'image'
            if change == 'self': candidate['nodes'][1]['bindings'][0]['producer'] = 'stage1'
            if change == 'unknown': candidate['nodes'][1]['bindings'][0]['producer'] = 'missing'
            if change == 'mode': candidate['expectations']['members'][1]['mode'] = 'refresh'
            if change == 'expansion': candidate['expectations']['consumers'][0]['reason'] = 'Fixture $TOKEN'
            if change == 'schema': candidate['schema'] = True
            if change == 'architecture': candidate['expectations']['members'][1]['cpu'] = 'cortex-a53'
            with self.subTest(change=change), self.assertRaises(ValueError): G['selection'](candidate)
        # A cycle that is recipe-compatible (refresh Stage 1 pairs).
        candidate = copy.deepcopy(self.request)
        a = copy.deepcopy(candidate['expectations']['members'][1])
        a.update(id='stage1-other', variant='workstation', mode='refresh')
        candidate['expectations']['members'][1]['mode'] = 'refresh'
        candidate['expectations']['members'].append(a)
        next(c for c in candidate['expectations']['consumers'] if c['project'] == 'nest/stage1')['members'].append(a['id'])
        # CPU/variant matching would otherwise fail before the graph check.
        candidate['expectations']['members'][1]['variant'] = 'workstation'
        candidate['expectations']['members'][1]['platform'] = None
        # Distinct selection via a separate tool refresh cycle is impossible under
        # recipe identity; nevertheless the topological guard rejects cycles even
        # if future compatible() recipes permit them.
        candidate['nodes'][1]['bindings'] = [dict(base=r, producer=a['id'], artifact=r) for r in ('normal', 'debug')]
        candidate['nodes'].append(dict(member=a['id'], job_name='Candidate other', placement=None,
                                       bindings=[dict(base=r, producer='stage1', artifact=r) for r in ('normal', 'debug')]))
        # Keep selections unique while isolating the topological cycle guard.
        candidate['expectations']['members'][1]['variant'] = 'server'
        with patch.dict(G['B'], {'compatible': lambda *args: None}):
            with self.assertRaisesRegex(ValueError, 'cyclic graph'): G['selection'](candidate)

    def test_exact_native_lineage_failure_hidden_jobs_and_changed_result_refuse(self):
        for change in ('compiler', 'sha', 'root', 'active', 'lineage', 'failed-node', 'moved-node',
                       'missing-route', 'failed-route', 'loop', 'hidden', 'result', 'erased'):
            api = NativeGraph(copy.deepcopy(self.api.expected))
            if change == 'compiler': api.jobs[('nest/config', 601)]['name'] = 'Other'
            if change == 'sha': api.graph['expectations']['release'] = 'moved'
            if change == 'root': api.pipelines[650]['source'] = 'api'
            if change == 'active': api.jobs[('nest/config', 9011)]['id'] = 999
            if change == 'lineage': api.bridges[600][0]['downstream_pipeline']['id'] = 999
            if change == 'failed-node': api.jobs[('nest/config', 801)]['status'] = 'failed'
            if change == 'moved-node': api.bridges[650][0]['downstream_pipeline']['sha'] = 'f' * 40
            if change == 'missing-route': api.bridges[650] = []
            if change == 'failed-route': api.pipelines[850]['status'] = 'failed'
            if change == 'loop': api.bridges[1] = [dict(id=102)]
            if change == 'hidden': api.pipeline_jobs[1].append(dict(id=102, name='Other', status='failed', allow_failure=True))
            if change == 'result': api.result['expectations_digest'] = 'sha256:' + '0' * 64
            if change == 'erased': api.jobs[('nest/stage0', 101)]['erased_at'] = 'fixture'
            with self.subTest(change=change), self.assertRaises(ValueError): G['freeze_node'](self.node_env, api)
            self.assertFalse((self.f.checkout / 'release-inputs').exists())
            submitted = self.f.checkout / 'graph-node-input.json'
            if submitted.exists(): submitted.unlink()

    def test_failed_artifact_readback_and_changed_predecessor_cannot_route(self):
        original = Path.read_bytes
        def read(path): return b'changed' if path.name == 'graph.yml' else original(path)
        with patch.object(Path, 'read_bytes', read), self.assertRaises(ValueError): G['compile_graph'](self.request, self.env)
        count = 0
        def after(path):
            nonlocal count
            if path.endswith('/jobs/101/artifacts'):
                count += 1
                if count == 1: self.api.bridges[650][0]['id'] = 999
        self.api.after_get = after
        with self.assertRaises(ValueError): G['freeze_node'](self.node_env, self.api)
        self.assertFalse((self.f.checkout / 'release-inputs').exists())

    def test_real_cli_acquires_only_captured_gets_and_retains_bound_inputs(self):
        replies = {}
        original = self.api.get
        def get(path):
            result = original(path)
            replies[path] = result
            return result
        with patch.object(self.api, 'get', get): G['freeze_node'](self.node_env, self.api)
        # New job-local checkout prevents replay of already published output.
        import shutil
        shutil.rmtree(self.f.checkout / 'release-inputs')
        (self.f.checkout / 'graph-node-input.json').unlink()
        binary = self.f.root / 'bin'
        binary.mkdir()
        F['fake_glab'](binary / 'glab', replies)
        completed = subprocess.run([sys.executable, str(ROOT / 'scripts/nest-release-graph.py'), '--freeze-node'],
                                   env=dict(self.node_env, PATH=str(binary) + os.pathsep + self.node_env['PATH']), capture_output=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(R['load'](self.f.checkout / 'release-inputs/expectations.json')['members'][0]['bases'],
                         self.api.result['output']['artifacts'])
        self.assertNotIn(b'Traceback', completed.stderr)

    def test_transport_rejects_mutation_latest_and_foreign_paths(self):
        with patch('subprocess.run') as run:
            for path in ('projects/nest%2Fconfig/pipelines/latest', 'projects/nest%2Fconfig/jobs/1/retry',
                         'projects/nest%2Fconfig/jobs/1/artifacts/release-graph/other.json', 'https://fixture.invalid'):
                with self.assertRaises(ValueError): G['GitLab']().get(path)
            run.assert_not_called()

    def test_architectures_fanout_reuse_and_stage3_placement_are_explicit(self):
        for cpu in ('haswell', 'cortex-a53', 'sifive-u74'):
            candidate = copy.deepcopy(self.request)
            for member in candidate['expectations']['members']: member['cpu'] = cpu
            self.assertEqual(G['selection'](candidate)[3], ['stage0', 'stage1'])
        candidate = copy.deepcopy(self.request)
        sibling = copy.deepcopy(candidate['expectations']['members'][1])
        sibling.update(id='stage1-workstation', variant='workstation')
        candidate['expectations']['members'].append(sibling)
        next(c for c in candidate['expectations']['consumers'] if c['project'] == 'nest/stage1')['members'].append(sibling['id'])
        candidate['nodes'].append(dict(member=sibling['id'], job_name='Candidate haswell-workstation', placement=None,
                                       bindings=copy.deepcopy(candidate['nodes'][1]['bindings'])))
        G['compile_graph'](candidate, self.env)
        graph = R['load'](self.f.checkout / 'release-graph/graph.yml')
        self.assertEqual(graph['Freeze release inputs stage1']['needs'], ['Release node stage0'])
        self.assertEqual(graph['Freeze release inputs stage1-workstation']['needs'], ['Release node stage0'])
        candidate['nodes'] = candidate['nodes'][1:]
        candidate['nodes'][0]['bindings'] = []
        candidate['nodes'][1]['bindings'] = []
        next(c for c in candidate['expectations']['consumers'] if c['project'] == 'nest/stage0')['decision'] = 'reuse'
        self.assertNotIn('stage0', G['selection'](candidate)[1])
        full = request(F['MANIFEST']['fixture']()[0])
        node = next(n for n in full['nodes'] if n['member'] == 'stage3')
        with self.assertRaises(ValueError): G['selection'](full)
        node['placement'] = '/fixture/local/placement.json'
        self.assertIn('stage3', G['selection'](full)[1])
        for placement in ('relative', '/fixture/../escape', '/fixture/$EXPANSION'):
            node['placement'] = placement
            with self.assertRaises(ValueError): G['selection'](full)

    def completed(self):
        # Produce a Stage 1 result using the descendant's actually frozen input.
        G['freeze_node'](self.node_env, self.api)
        frozen = R['load'](self.f.checkout / 'release-inputs/expectations.json')
        self.api.pipelines[9050] = self.api.pipeline(9050, 'parent_pipeline', 'success')
        self.api.pipelines[2] = self.api.pipeline(2, 'pipeline', 'success', project='nest/stage1')
        self.api.bridges[650].append(self.api.bridge(661, 'Release node stage1', 650, 9050))
        self.api.bridges[9050] = [self.api.bridge(9060, 'Build frozen member', 9050, 2)]
        self.api.bridges[2] = []
        self.api.jobs[('nest/config', 9011)]['status'] = 'success'
        for project, pipeline, job, name in [('nest/stage1', 2, 102, 'Candidate haswell-server')]:
            self.api.jobs[(project, job)] = self.api.make_job(project, pipeline, job, name)
            self.api.jobs[(project, job)]['allow_failure'] = False
            self.api.pipeline_jobs[pipeline] = [self.api.jobs[(project, job)]]
        self.api.artifacts[('nest/config', 9011, 'release-inputs/expectations.json')] = frozen
        self.leaf = dict(schema=1, kind='nest_release_member_result', release=frozen['release'],
                         expectations_digest=R['digest'](frozen), executor_receipt=self.api.executor,
                         output=dict(member=copy.deepcopy(frozen['members'][0]), executor=frozen['executor'],
                                     producer=dict(project='nest/stage1', sha=frozen['sources']['nest/stage1'], pipeline=2, job=102),
                                     artifacts=dict(normal=F['MANIFEST']['image'](501), debug=F['MANIFEST']['image'](502))))
        self.api.artifacts[('nest/stage1', 102, 'release-results/stage1.json')] = self.leaf
        acceptance = self.api.make_job('nest/config', 650, 699, 'Accept release graph')
        acceptance.update(status='running', allow_failure=False)
        self.api.pipeline_jobs[650].append(acceptance)
        env = {k: v for k, v in self.node_env.items() if k not in ('RELEASE_GRAPH_NODE', 'RELEASE_GRAPH_MEMBER')}
        return dict(env, CI_PIPELINE_SOURCE='parent_pipeline', CI_PIPELINE_ID='650', CI_JOB_ID='699', CI_JOB_NAME='Accept release graph')

    def test_acceptance_requires_its_exact_running_required_native_job(self):
        env = self.completed()
        jobs = self.api.pipeline_jobs[650]
        original = copy.deepcopy(jobs)
        for change in ('missing', 'duplicate', 'job', 'name', 'status', 'tolerated', 'erased',
                       'pipeline', 'project', 'source', 'commit', 'caller'):
            jobs[:] = copy.deepcopy(original)
            row = jobs[-1]
            caller = dict(env)
            if change == 'missing': jobs.pop()
            if change == 'duplicate': jobs.append(copy.deepcopy(row))
            if change == 'job': row['id'] = 700
            if change == 'name': row['name'] += ' sibling'
            if change == 'status': row['status'] = 'success'
            if change == 'tolerated': row['allow_failure'] = True
            if change == 'erased': row['erased_at'] = 'fixture'
            if change == 'pipeline': row['pipeline']['id'] = 651
            if change == 'project': row['pipeline']['project_id'] = 10
            if change == 'source': row['pipeline']['sha'] = 'f' * 40
            if change == 'commit': row['commit']['id'] = 'f' * 40
            if change == 'caller': caller['CI_JOB_ID'] = '700'
            with self.subTest(change=change), self.assertRaises(ValueError):
                G['accept_graph'](caller, self.api)
            self.assertFalse((self.f.checkout / 'release-graph-acceptance').exists())

    def test_acceptance_job_race_refuses_before_publication(self):
        env = self.completed()
        jobs = self.api.pipeline_jobs[650]
        original = copy.deepcopy(jobs)
        for change in ('missing', 'duplicate', 'job', 'status', 'tolerated', 'erased', 'source'):
            jobs[:] = copy.deepcopy(original)
            def after(path):
                if '/jobs/102/artifacts' not in path: return
                self.api.after_get = None
                row = jobs[-1]
                if change == 'missing': jobs.pop()
                if change == 'duplicate': jobs.append(copy.deepcopy(row))
                if change == 'job': row['id'] = 700
                if change == 'status': row['status'] = 'canceled'
                if change == 'tolerated': row['allow_failure'] = True
                if change == 'erased': row['erased_at'] = 'fixture'
                if change == 'source': row['commit']['id'] = 'f' * 40
            self.api.after_get = after
            with self.subTest(change=change), self.assertRaises(ValueError): G['accept_graph'](env, self.api)
            self.assertFalse((self.f.checkout / 'release-graph-acceptance').exists())

    def test_acceptance_job_ignores_volatile_metadata_and_unrelated_siblings(self):
        env = self.completed()
        self.api.pipeline_jobs[650].append(dict(id=999, name='Unrelated sibling', status='running'))
        def after(path):
            if '/pipelines/650/jobs?' in path:
                row = self.api.pipeline_jobs[650][-2]
                row['duration'] = row.get('duration', 0) + 1
                row['runner'] = dict(contacted_at=str(row['duration']))
                row['user'] = dict(last_activity_on=str(row['duration']))
        self.api.after_get = after
        receipt = G['accept_graph'](env, self.api)
        self.assertEqual(receipt['acceptance_job'], 699)
        self.assertEqual(receipt['graph_pipeline'], 650)

    def test_final_acceptance_checks_all_leaf_bytes_and_reopens_complete_rebuilt_manifest(self):
        env = self.completed()
        receipt = G['accept_graph'](env, self.api)
        self.assertEqual(receipt['rebuilt']['manifest']['candidate']['outputs'][1], self.leaf['output'])
        self.assertEqual(receipt['rebuilt']['manifest']['expectations']['members'][1]['bases'], self.api.result['output']['artifacts'])
        self.assertFalse(receipt['promotion_authorized'])
        self.assertEqual(receipt['acceptance_job'], 699)
        self.assertEqual(R['load'](self.f.checkout / 'release-graph-acceptance/receipt.json'), receipt)
        with self.assertRaises(FileExistsError): G['accept_graph'](env, self.api)

    def test_acceptance_ignores_volatile_bridge_metadata_but_retains_exact_lineage(self):
        env = self.completed()
        def after(path):
            if '/pipelines/650/bridges?' in path:
                for bridge in self.api.bridges[650]:
                    bridge['duration'] = bridge.get('duration', 0) + 1
                    bridge['runner'] = dict(contacted_at=str(bridge['duration']))
        self.api.after_get = after
        receipt = G['accept_graph'](env, self.api)
        self.assertEqual(len(receipt['rebuilt']['manifest']['candidate']['outputs']), 2)

    def test_real_acceptance_cli_requires_the_bound_native_writer(self):
        env = self.completed()
        replies = {}
        original = self.api.get
        def get(path):
            result = original(path)
            replies[path] = result
            return result
        with patch.object(self.api, 'get', get): G['accept_graph'](env, self.api)
        import shutil
        directory = self.f.checkout / 'release-graph-acceptance'
        shutil.rmtree(directory)
        binary = self.f.root / 'bin'
        binary.mkdir()
        F['fake_glab'](binary / 'glab', replies)
        cli_env = dict(env, PATH=str(binary) + os.pathsep + env['PATH'])
        for identifier, expected_exit in (('700', 1), ('699', 0)):
            completed = subprocess.run([sys.executable, str(ROOT / 'scripts/nest-release-graph.py'), '--accept'],
                                       env=dict(cli_env, CI_JOB_ID=identifier), capture_output=True, check=False)
            self.assertEqual(completed.returncode, expected_exit, completed.stderr)
            self.assertNotIn(b'Traceback', completed.stderr)
            if expected_exit:
                self.assertFalse(directory.exists())
            else:
                self.assertEqual(R['load'](directory / 'receipt.json')['acceptance_job'], 699)

    def test_self_consistent_leaf_cannot_change_projection_policy_sources_or_dependency_bases(self):
        env = self.completed()
        frozen = self.api.artifacts[('nest/config', 9011, 'release-inputs/expectations.json')]
        original, result = copy.deepcopy(frozen), copy.deepcopy(self.leaf)
        for change in ('policy', 'base', 'full-matrix'):
            if change == 'policy': frozen['consumers'][0]['reason'] = 'Changed unrelated policy'
            if change == 'base':
                frozen['members'][0]['bases']['normal'] = F['MANIFEST']['image'](800)
                self.leaf['output']['member'] = copy.deepcopy(frozen['members'][0])
            if change == 'full-matrix':
                full = copy.deepcopy(self.request['expectations'])
                full['members'][1] = copy.deepcopy(frozen['members'][0])
                frozen.clear(); frozen.update(full)
            # Pass the ordinary result/input digest contract. Final graph
            # acceptance must independently reconstruct the exact projection.
            self.leaf['expectations_digest'] = R['digest'](frozen)
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'graph leaf escaped'):
                G['accept_graph'](env, self.api)
            self.assertFalse((self.f.checkout / 'release-graph-acceptance').exists())
            frozen.clear(); frozen.update(copy.deepcopy(original))
            self.leaf.clear(); self.leaf.update(copy.deepcopy(result))

    def test_reassembly_cannot_replace_the_predecessor_bytes_or_native_edge_used_for_projection(self):
        for change in ('output', 'input', 'inner-bridge'):
            fixture = GraphTest()
            fixture.setUp()
            try:
                env = fixture.completed()
                assemble = G['A']['assemble']

                def changed(request, api):
                    # Each replacement remains independently acceptable to the
                    # ordinary assembler. Graph acceptance must bind it to the
                    # earlier observations used to reconstruct descendant bases.
                    if change == 'output':
                        api.result['output']['artifacts']['normal'] = F['MANIFEST']['image'](850)
                    elif change == 'input':
                        frozen = api.artifacts[('nest/config', 801, 'release-inputs/expectations.json')]
                        frozen['consumers'][0]['reason'] = 'Changed policy between graph and assembly reads'
                        api.result['expectations_digest'] = R['digest'](frozen)
                    else:
                        api.bridges[850][0]['id'] += 1
                    return assemble(request, api)

                with self.subTest(change=change), patch.dict(G['A'], {'assemble': changed}):
                    with self.assertRaisesRegex(ValueError, 'graph member changed before assembly'):
                        G['accept_graph'](env, fixture.api)
                    self.assertFalse((fixture.f.checkout / 'release-graph-acceptance').exists())
            finally:
                fixture.doCleanups()

    def test_green_leaf_with_wrong_dependency_base_or_executor_is_not_accepted(self):
        env = self.completed()
        for change in ('base', 'executor', 'digest', 'failed', 'input', 'lineage'):
            result = copy.deepcopy(self.leaf)
            frozen = self.api.artifacts[('nest/config', 9011, 'release-inputs/expectations.json')]
            original = copy.deepcopy(frozen)
            if change == 'base': self.leaf['output']['member']['bases']['normal'] = F['MANIFEST']['image'](800)
            if change == 'executor': self.leaf['executor_receipt'] = dict(self.api.executor, job=999)
            if change == 'digest': self.leaf['expectations_digest'] = 'sha256:' + '0' * 64
            if change == 'failed': self.api.pipelines[2]['status'] = 'failed'
            if change == 'input': frozen['consumers'][0]['reason'] = 'Changed unrelated closure'
            if change == 'lineage': self.api.bridges[600][0]['downstream_pipeline']['id'] = 999
            with self.subTest(change=change), self.assertRaises(ValueError): G['accept_graph'](env, self.api)
            self.assertFalse((self.f.checkout / 'release-graph-acceptance').exists())
            self.leaf.clear(); self.leaf.update(result)
            frozen.clear(); frozen.update(original)
            self.api.pipelines[2]['status'] = 'success'
            self.api.bridges[600][0]['downstream_pipeline']['id'] = 650


class GraphArtifactFlowTest(unittest.TestCase):
    """Carry emitted artifacts across isolated jobs; all GitLab resources are fake.

    Unlike the independent reader fixtures, no freezer input or leaf projection
    is precomputed. Production compilation stays disabled at its CLI boundary.
    This exercises its compiler function, then the real freezer/acceptance CLIs;
    it is not live scheduling, job-token or image-publication acceptance.
    """

    def setUp(self):
        self.fixture = GraphTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.api = self.fixture.api
        self.root = self.fixture.f.root
        self.compiler = self.fixture.f.checkout
        self.publication = G['compile_graph'](self.api.graph, self.fixture.env)
        self.graph = R['load'](self.compiler / 'release-graph/graph.yml')
        self.request_raw = (self.compiler / 'release-graph/request.json').read_bytes()
        self.assertEqual(hashlib.sha256(self.request_raw).hexdigest(), self.publication['request_sha256'])
        # Populate the fake API only from the compiler's retained publication.
        self.api.graph = R['load'](self.compiler / 'release-graph/request.json')
        self.api.artifacts = {key: row for key, row in self.api.artifacts.items()
                              if key[0] == 'nest/config' and key[1] in (601, 901)}
        self.api.artifacts[('nest/config', 601, 'release-graph/request.json')] = self.api.graph
        self.api.bridges = {600: self.api.bridges[600], 650: []}
        self.api.pipelines = {key: row for key, row in self.api.pipelines.items() if key in (600, 650)}
        self.api.jobs = {key: row for key, row in self.api.jobs.items() if key[0] == 'nest/config'}
        self.api.jobs[('nest/config', 801)]['status'] = 'running'
        self.api.pipeline_jobs = {650: [self.api.jobs[('nest/config', 801)], self.api.jobs[('nest/config', 9011)]]}
        self.binary = self.root / 'flow-bin'
        self.binary.mkdir()
        self.attempts = []

    def replies(self):
        """Expose a closed GET-only inventory, never the real glab or network."""
        paths = set()
        for project, job in self.api.jobs:
            prefix = G['B']['prefix'](project)
            paths.update((prefix, prefix + '/jobs/' + str(job), prefix + '/jobs/' + str(job) + '/artifacts'))
        for project, job, name in self.api.artifacts:
            paths.add(G['B']['prefix'](project) + '/jobs/' + str(job) + '/artifacts/' + name)
        for identifier, pipeline in self.api.pipelines.items():
            project = 'nest/config' if pipeline['project_id'] == 3 else (
                'nest/stage0' if identifier == 1 else 'nest/stage1')
            prefix = G['B']['prefix'](project) + '/pipelines/' + str(identifier)
            paths.add(prefix)
            if identifier in self.api.bridges:
                paths.add(prefix + '/bridges?per_page=100&page=1')
            if identifier in self.api.pipeline_jobs:
                paths.add(prefix + '/jobs?per_page=100&page=1')
        return {path: self.api.get(path) for path in sorted(paths)}

    def invoke(self, name, action, variables, job):
        checkout = self.root / (str(len(self.attempts)) + '-' + name)
        subprocess.run(['git', 'clone', '--no-hardlinks', '--local', str(self.compiler), str(checkout)],
                       env=self.fixture.f.env, capture_output=True, check=True)
        # Use the variables emitted by the actual compiler, not a parallel
        # hand-authored environment that might conceal broken variable wiring.
        variables = {key: '650' if value == '$CI_PIPELINE_ID' else value for key, value in variables.items()}
        env = dict(self.fixture.f.env, **variables, CI_PROJECT_DIR=str(checkout),
                   CI_PIPELINE_SOURCE='parent_pipeline', CI_PIPELINE_ID='650',
                   CI_JOB_NAME=name, CI_JOB_ID=str(job),
                   PATH=str(self.binary) + os.pathsep + self.fixture.f.env['PATH'])
        F['fake_glab'](self.binary / 'glab', self.replies())
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/nest-release-graph.py'), action],
                                cwd=checkout, env=env, capture_output=True, check=False)
        self.attempts.append((checkout, result))
        self.assertNotIn(b'Traceback', result.stderr)
        return checkout, result

    def freeze(self, name, job):
        title = 'Freeze release inputs ' + name
        return self.invoke(title, '--freeze-node', self.graph[title]['variables'], job)

    def leaf(self, name, checkout, freezer, pipeline, job, route, bridge) -> Any:
        """Simulate a leaf, explicitly not a build or a published OCI output."""
        frozen = R['load'](checkout / 'release-inputs/expectations.json')
        member = frozen['members'][0]
        project = member['project']
        candidate = R['load'](checkout / 'release-inputs/candidate.yml')['Build frozen member']
        self.assertEqual(candidate['trigger']['project'], project)
        self.assertEqual(candidate['variables']['RELEASE_INPUT_JOB_ID'], str(freezer))
        self.assertEqual(candidate['variables']['RELEASE_INPUT_SHA256'],
                         hashlib.sha256((checkout / 'release-inputs/expectations.json').read_bytes()).hexdigest())
        self.assertNotIn('RELEASE_GRAPH_NODE', candidate['variables'])
        self.api.artifacts[('nest/config', freezer, 'release-inputs/expectations.json')] = frozen
        self.api.jobs[('nest/config', freezer)]['status'] = 'success'
        self.api.pipelines[route] = self.api.pipeline(route, 'parent_pipeline', 'success')
        self.api.pipelines[pipeline] = self.api.pipeline(pipeline, 'pipeline', 'success', project=project)
        self.api.bridges[650].append(self.api.bridge(bridge, 'Release node ' + name, 650, route))
        self.api.bridges[route] = [self.api.bridge(bridge + 100, 'Build frozen member', route, pipeline)]
        self.api.bridges[pipeline] = []
        node = next(row for row in self.api.graph['nodes'] if row['member'] == name)
        native = self.api.make_job(project, pipeline, job, node['job_name'])
        native['allow_failure'] = False
        self.api.jobs[(project, job)] = native
        self.api.pipeline_jobs[pipeline] = [native]
        # These digests are inert fixture data; only the contract readers run.
        artifacts = dict(normal=F['MANIFEST']['image'](500 + job), debug=F['MANIFEST']['image'](600 + job))
        result = dict(schema=1, kind='nest_release_member_result', release=frozen['release'],
                      expectations_digest=R['digest'](frozen), executor_receipt=self.api.executor,
                      output=dict(member=copy.deepcopy(member), executor=frozen['executor'],
                                  producer=dict(project=project, sha=frozen['sources'][project], pipeline=pipeline, job=job),
                                  artifacts=artifacts))
        emitted = {(project, job, 'release-results/' + name + '.json'): result}
        F['digest_results'](emitted)
        self.api.artifacts.update(emitted)
        return result

    def root_leaf(self) -> Any:
        checkout, result = self.freeze('stage0', 801)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(R['load'](checkout / 'release-inputs/expectations.json'),
                         G['I']['project_member'](self.api.graph['expectations'], 'stage0'))
        return self.leaf('stage0', checkout, 801, 1, 101, 850, 660)

    def acceptance(self):
        row = self.api.make_job('nest/config', 650, 699, 'Accept release graph')
        row.update(status='running', allow_failure=False)
        self.api.pipeline_jobs[650].append(row)
        return self.invoke('Accept release graph', '--accept', self.graph['Accept release graph']['variables'], 699)

    def test_emitted_compiler_root_descendant_and_acceptance_bytes_cross_job_boundaries(self):
        upstream = self.root_leaf()
        checkout, result = self.freeze('stage1', 9011)
        self.assertEqual(result.returncode, 0, result.stderr)
        frozen = R['load'](checkout / 'release-inputs/expectations.json')
        self.assertEqual(frozen['members'][0]['bases'], upstream['output']['artifacts'])
        downstream = self.leaf('stage1', checkout, 9011, 2, 102, 9050, 661)
        checkout, result = self.acceptance()
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = R['load'](checkout / 'release-graph-acceptance/receipt.json')
        self.assertEqual(receipt['inputs'], R['load'](self.compiler / 'release-graph/request.json'))
        self.assertEqual(receipt['graph_sha256'], self.publication['request_sha256'])
        self.assertEqual(receipt['rebuilt']['manifest']['candidate']['outputs'], [upstream['output'], downstream['output']])
        self.assertFalse(receipt['promotion_authorized'])
        self.assertEqual(len({path for path, _ in self.attempts}), 3)

    def test_failed_predecessor_refuses_descendant_publication(self):
        self.root_leaf()
        self.api.pipelines[1]['status'] = 'failed'
        self.api.jobs[('nest/stage0', 101)]['status'] = 'failed'
        checkout, result = self.freeze('stage1', 9011)
        self.assertEqual(result.returncode, 1)
        self.assertFalse((checkout / 'release-inputs').exists())

    def test_failed_predecessor_refuses_acceptance_even_with_both_leaf_artifacts(self):
        self.root_leaf()
        checkout, result = self.freeze('stage1', 9011)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.leaf('stage1', checkout, 9011, 2, 102, 9050, 661)
        self.api.pipelines[1]['status'] = 'failed'
        self.api.jobs[('nest/stage0', 101)]['status'] = 'failed'
        checkout, result = self.acceptance()
        self.assertEqual(result.returncode, 1)
        self.assertFalse((checkout / 'release-graph-acceptance').exists())

    def test_self_consistent_changed_descendant_projection_refuses_final_publication(self):
        self.root_leaf()
        checkout, result = self.freeze('stage1', 9011)
        self.assertEqual(result.returncode, 0, result.stderr)
        leaf = self.leaf('stage1', checkout, 9011, 2, 102, 9050, 661)
        frozen = self.api.artifacts[('nest/config', 9011, 'release-inputs/expectations.json')]
        frozen['consumers'][0]['reason'] = 'Changed fixture policy outside the selected member'
        leaf['expectations_digest'] = R['digest'](frozen)
        # Reseal the simulated leaf filename too, so the refusal cannot be
        # explained by the simpler raw archive byte-hash guard alone.
        key = next(key for key in self.api.artifacts if key[0] == 'nest/stage1')
        del self.api.artifacts[key]
        emitted = {('nest/stage1', 102, 'release-results/stage1.json'): leaf}
        F['digest_results'](emitted)
        self.api.artifacts.update(emitted)
        checkout, result = self.acceptance()
        self.assertEqual(result.returncode, 1)
        self.assertFalse((checkout / 'release-graph-acceptance').exists())

    def test_changed_retained_compiler_bytes_refuse_root_without_leaf_artifacts(self):
        self.api.graph['expectations']['release'] = 'changed-fixture'
        checkout, result = self.freeze('stage0', 801)
        self.assertEqual(result.returncode, 1)
        self.assertFalse((checkout / 'release-inputs').exists())
        self.assertFalse(any(project != 'nest/config' for project, _, _ in self.api.artifacts))


if __name__ == '__main__':
    unittest.main()
