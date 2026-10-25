#!/usr/bin/env python3
"""Compile and freeze a same-source native release DAG using existing CI routes."""

import argparse
import copy
import hashlib
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
D = runpy.run_path(str(ROOT / 'scripts/nest-release-discover.py'))
B = D['BIND']
R = D['R']
I = runpy.run_path(str(ROOT / 'scripts/nest-release-inputs.py'))
A = runpy.run_path(str(ROOT / 'scripts/nest-release-assemble.py'))
require = R['require']
KEYS = ('RELEASE_GRAPH', 'RELEASE_GRAPH_FILE', 'RELEASE_GRAPH_NODE', 'RELEASE_GRAPH_MEMBER',
        'RELEASE_GRAPH_INPUT_PIPELINE', 'RELEASE_GRAPH_INPUT_JOB', 'RELEASE_GRAPH_INPUT_SHA256',
        'RELEASE_GRAPH_ROOT_PIPELINE')

CONFLICTS = ('EXECUTOR_BOOTSTRAP', 'RELEASE_BOOTSTRAP_FILE', 'RELEASE_BOOTSTRAP_PIPELINE',
             'RELEASE_BOOTSTRAP_JOB', 'RELEASE_BOOTSTRAP_SHA256', 'BUILD', 'EXECUTOR_ONLY',
             'RELEASE_CANDIDATE', 'RELEASE_VALIDATE_ONLY', 'NEST_DAG_FIXTURE', 'RELEASE_DAG',
             'RELEASE_DAG_FIXTURE', 'RELEASE_EXPECTATIONS_FILE', 'RELEASE_DISCOVERY_FILE',
             'RELEASE_ROUTE', 'RELEASE_ROUTE_MEMBER', 'RELEASE_ROUTE_EXECUTOR_PIPELINE',
             'RELEASE_ROUTE_EXECUTOR_JOB', 'RELEASE_ROUTE_PLACEMENT', 'REFRESH',
             'NEST_LEGACY_BUILD', 'FROM_GENTOO', 'STAGE0_RESUME', 'CPU', 'VARIANT',
             'PLATFORM', 'CLUSTER', 'PROFILE', 'RUNNER_SMOKE_TAG')


class GitLab(D['GitLab']):
    def get(self, path):
        if re.fullmatch(r'projects/nest%2Fconfig/jobs/[1-9][0-9]{0,19}/artifacts/release-graph/request.json', path):
            return self._read(path, 'artifact')
        return super().get(path)


def selected(env):
    if not any(env.get(k) for k in KEYS):
        return None
    require(not any(env.get(k) for k in CONFLICTS) and not env.get('CI_COMMIT_TAG'), 'conflicting graph selection')
    if env.get('RELEASE_GRAPH') in ('true', 'verify-inputs'):
        require(env.get('CI_PIPELINE_SOURCE') in ('api', 'web', 'trigger'), 'unsupported graph source')
        require(env.get('RELEASE_GRAPH_FILE') and not env.get('RELEASE_INPUTS')
                and not any(env.get(k) for k in KEYS[2:]), 'invalid graph compilation selection')
        return 'compile'
    require(env.get('RELEASE_GRAPH_NODE') in ('true', 'verify-inputs') and env.get('RELEASE_INPUTS') == 'true'
            and env.get('CI_PIPELINE_SOURCE') == 'parent_pipeline'
            and not env.get('RELEASE_GRAPH') and not env.get('RELEASE_GRAPH_FILE'), 'invalid graph node selection')
    R['match'](env.get('RELEASE_GRAPH_MEMBER'), R['TOKEN'], 'graph member')
    for key in ('RELEASE_GRAPH_INPUT_PIPELINE', 'RELEASE_GRAPH_INPUT_JOB', 'RELEASE_GRAPH_ROOT_PIPELINE'):
        R['match'](env.get(key), r'[1-9][0-9]{0,19}', 'graph resource')
    R['match'](env.get('RELEASE_GRAPH_INPUT_SHA256'), r'[0-9a-f]{64}', 'graph artifact digest')
    return 'node'


def selection(request: Any) -> tuple[dict[str, Any], dict[str, Any], dict[str, set[str]], list[str]]:
    R['fields'](request, 'schema kind expectations executor_job nodes', 'release graph')
    require(type(request['schema']) is int and request['schema'] == 1
            and request['kind'] == 'nest_release_graph', 'unsupported graph')
    indexed = R['expectations'](request['expectations'])
    R['fields'](request['executor_job'], 'pipeline job', 'graph executor')
    for value in request['executor_job'].values():
        B['positive'](value)
    require(all(m['cpu'] in B['CPUS'] for m in indexed.values())
            and len({B['CPUS'][m['cpu']] for m in indexed.values()}) == 1, 'graph requires one executor architecture')
    nodes = request['nodes']
    require(type(nodes) is list and 0 < len(nodes) <= 32, 'invalid graph node inventory')
    rebuilt = {m['id'] for m in indexed.values() if next(c['decision'] for c in request['expectations']['consumers']
                                                       if c['project'] == m['project']) == 'rebuild'}
    names = [n['member'] for n in nodes]
    require(len(set(names)) == len(names) and set(names) == rebuilt, 'graph must cover every rebuilt member exactly once')
    dependencies = {}
    for node in nodes:
        R['fields'](node, 'member job_name placement bindings', 'graph node')
        member = indexed[node['member']]
        require(member['project'] in B['PROJECTS'] - {'nest/config'}, 'unsupported graph producer')
        R['text'](node['job_name'], 'candidate job name')
        require(node['job_name'].startswith('Candidate ') and '$' not in node['job_name'], 'invalid candidate job name')
        if member['stage'] == 'stage3':
            R['absolute_path'](node['placement'], 'graph placement')
            require('$' not in node['placement'], 'variable expansion in placement')
        else:
            require(node['placement'] is None, 'placement outside Stage 3')
        edges = node['bindings']
        require(type(edges) is list and len(edges) <= 2, 'invalid graph bindings')
        slots = set()
        parents = set()
        for edge in edges:
            R['fields'](edge, 'base producer artifact', 'graph edge')
            require(edge['base'] in member['bases'] and edge['base'] not in slots, 'duplicate or unknown base slot')
            require(type(edge['producer']) is str and edge['producer'] in rebuilt
                    and edge['producer'] != member['id'], 'unknown or self dependency')
            B['compatible'](member, edge['base'], indexed[edge['producer']], edge['artifact'])
            slots.add(edge['base'])
            parents.add(edge['producer'])
        require(not edges or slots == set(member['bases']), 'partial member binding')
        require(member['stage'] != 'stage1' or len(parents) <= 1, 'split Stage 1 base pair')
        dependencies[node['member']] = parents
    # Deterministic topological ordering; no arbitrary global serialization.
    order = []
    remaining = set(names)
    while remaining:
        ready = sorted(n for n in remaining if dependencies[n] <= set(order))
        require(ready, 'cyclic graph')
        order.extend(ready)
        remaining.difference_update(ready)
    require(b'$' not in R['canonical'](request), 'variable expansion in graph input')
    return indexed, {n['member']: n for n in nodes}, dependencies, order


def verification_selection(request):
    """A real scoped freezer, but no candidate or invented predecessor output."""
    indexed, nodes, dependencies, order = selection(request)
    require(len(nodes) == 1, 'input verification requires exactly one independent node')
    member = indexed[order[0]]
    require(not dependencies[order[0]] and member['stage'] == 'stage0'
            and member['project'] == 'nest/stage0' and member['variant'] == 'server'
            and member['mode'] == 'refresh', 'input verification only supports independent Stage 0 refresh')


def compile_graph(request: Any, env):
    require(selected(env) == 'compile', 'graph compilation not selected')
    indexed, nodes, dependencies, order = selection(request)
    verifying = env.get('RELEASE_GRAPH') == 'verify-inputs'
    if verifying:
        verification_selection(request)
    source = I['identity'](dict(env, RELEASE_INPUTS='true'), Path(env.get('CI_PROJECT_DIR', '')))
    require(source == request['expectations']['sources']['nest/config']
            and env.get('CI_JOB_NAME') == 'Compile release graph'
            and env.get('CI_COMMIT_BRANCH') == 'main', 'wrong graph source, branch or job')
    raw = R['canonical'](request)
    graph = {'workflow': {'rules': [{'if': '$CI_PIPELINE_SOURCE == "parent_pipeline"'}, {'when': 'never'}]},
             'stages': ['Candidates']}
    image = 'registry.gitlab.joyfullee.me/nest/tools/agent@sha256:820cc8a130309a07db90685958bb9cac87d8376ab63f2d45457e87431ad93e34'
    for name in order:
        freezer = 'Freeze release inputs ' + name
        graph[freezer] = {
            'stage': 'Candidates', 'needs': ['Release node ' + p for p in sorted(dependencies[name])],
            'allow_failure': False, 'inherit': {'variables': False},
            'image': image, 'tags': ['owl'],
            'script': ['python3 scripts/nest-release-graph.py --freeze-node'],
            'variables': {'RELEASE_INPUTS': 'true', 'RELEASE_GRAPH_NODE': 'verify-inputs' if verifying else 'true', 'RELEASE_GRAPH_MEMBER': name,
                          'RELEASE_GRAPH_INPUT_PIPELINE': env['CI_PIPELINE_ID'],
                          'RELEASE_GRAPH_INPUT_JOB': env['CI_JOB_ID'],
                          'RELEASE_GRAPH_INPUT_SHA256': hashlib.sha256(raw).hexdigest(),
                          'RELEASE_GRAPH_ROOT_PIPELINE': '$CI_PIPELINE_ID'},
            'artifacts': {'when': 'on_success', 'paths': ['release-inputs/']}}
        graph['Release node ' + name] = {
            'stage': 'Candidates', 'needs': [freezer],
            'allow_failure': False, 'inherit': {'variables': False},
            'trigger': {'include': [{'artifact': 'release-inputs/candidate.yml', 'job': freezer}], 'strategy': 'mirror',
                        'forward': {'yaml_variables': True, 'pipeline_variables': False}}}
    graph['Accept release graph'] = {
        'stage': 'Candidates', 'needs': ['Release node ' + name for name in order],
        'allow_failure': False, 'inherit': {'variables': False},
        'image': 'registry.gitlab.joyfullee.me/nest/tools/agent@sha256:820cc8a130309a07db90685958bb9cac87d8376ab63f2d45457e87431ad93e34',
        'tags': ['owl'], 'script': ['python3 scripts/nest-release-graph.py --accept'],
        'variables': {'RELEASE_INPUTS': 'true', 'RELEASE_GRAPH_INPUT_PIPELINE': env['CI_PIPELINE_ID'],
                      'RELEASE_GRAPH_INPUT_JOB': env['CI_JOB_ID'],
                      'RELEASE_GRAPH_INPUT_SHA256': hashlib.sha256(raw).hexdigest(),
                      'RELEASE_GRAPH_ROOT_PIPELINE': '$CI_PIPELINE_ID'},
        'artifacts': {'when': 'on_success', 'paths': ['release-graph-acceptance/']}}
    if verifying:
        # Input observations are not member results. Never send them to the
        # production assembler or emit a misleading graph acceptance receipt.
        del graph['Accept release graph']
    # Public source policy is checked before any graph can schedule Stage 3.
    I['identity_trust'](request['expectations'], Path(env['CI_PROJECT_DIR']), source)
    receipt = dict(schema=1, kind='nest_release_graph_publication', source=source,
                   pipeline=int(env['CI_PIPELINE_ID']), job=int(env['CI_JOB_ID']), nodes=len(nodes),
                   request_sha256=hashlib.sha256(raw).hexdigest(), graph_sha256=hashlib.sha256(R['canonical'](graph)).hexdigest(),
                   execution='not_started', promotion_authorized=False)
    if verifying:
        receipt['kind'] = 'nest_release_graph_input_verification_publication'
    publish(Path(env['CI_PROJECT_DIR']) / 'release-graph',
            {'request.json': raw, 'graph.yml': R['canonical'](graph), 'receipt.json': R['canonical'](receipt)})
    return receipt


def publish(directory, records):
    directory.mkdir(mode=0o700)
    for name, raw in records.items():
        require(len(raw) <= R['LIMIT'], 'oversized graph artifact')
        with (directory / name).open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    for name, raw in records.items():
        require((directory / name).read_bytes() == raw, 'graph artifact readback failed')


def native_node(api, request: Any, root_id, name):
    """Resolve graph/freezer -> route child directly, without a config node layer."""
    sha = request['expectations']['sources']['nest/config']
    root = D['pipeline'](api, 'nest/config', root_id, sha, root=True)
    require(root['source'] == 'parent_pipeline', 'not a compiled graph child')
    bridge = D['selected'](D['listing'](api, 'nest/config', root_id, 'bridges'), 'Release node ' + name)
    require(bridge['pipeline']['id'] == root_id and bridge['pipeline']['sha'] == sha
            and bridge['pipeline']['project_id'] == root['project_id'], 'graph bridge parent mismatch')
    child = D['pipeline'](api, 'nest/config', bridge['downstream_pipeline']['id'], sha, root=True)
    require(child['status'] == 'success' and child['source'] == 'parent_pipeline'
            and all(bridge['downstream_pipeline'][k] == child[k] for k in ('id', 'project_id', 'sha', 'ref', 'status')),
            'route child has not succeeded or moved')
    routes = D['listing'](api, 'nest/config', child['id'], 'bridges')
    require(len(routes) == 1 and routes[0]['name'] == 'Build frozen member', 'unexpected route child bridge')
    jobs = D['listing'](api, 'nest/config', root_id, 'jobs')
    names = B['input_job_names'](name)
    inputs = [j for j in jobs if j['name'] in names]
    require(len(inputs) == 1 and inputs[0]['name'] == 'Freeze release inputs ' + name,
            'missing or ambiguous scoped graph freezer')
    freezer = D['selected'](inputs, inputs[0]['name'])
    observed = B['job'](api, 'nest/config', root_id, freezer['id'], sha)
    require(observed['name'] == freezer['name'], 'graph freezer identity changed')
    # GitLab adds volatile duration, runner and user metadata to bridge rows.
    # Compare resource identity, required success and exact parent/child pins,
    # not unrelated mutable display metadata, across independent acquisitions.
    stable_bridge = {key: bridge[key] for key in ('id', 'name', 'status', 'allow_failure')}
    stable_bridge['pipeline'] = {key: bridge['pipeline'][key] for key in ('id', 'project_id', 'sha')}
    stable_bridge['downstream_pipeline'] = {
        key: bridge['downstream_pipeline'][key] for key in ('id', 'project_id', 'sha', 'ref', 'status')}
    return dict(root_pipeline=child['id'], input_pipeline=root_id, bridge='Build frozen member'), dict(
        root=root, bridge=stable_bridge, child=child, freezer=observed)


def active_job(api, root_id, names, env, source):
    """Stable job identity only; duration, runner and user metadata are volatile."""
    jobs = D['listing'](api, 'nest/config', root_id, 'jobs')
    current = [j for j in jobs if j['name'] in names]
    require(len(current) == 1, 'missing or ambiguous active graph job')
    row = current[0]
    require(row['name'] == env['CI_JOB_NAME'] and row['id'] == int(env['CI_JOB_ID'])
            and row['status'] == 'running' and row.get('allow_failure') is False
            and row.get('erased_at') is None, 'graph job is not the active required job')
    parent = row['pipeline']
    B['positive'](row['id'])
    B['positive'](parent['id'])
    B['positive'](parent['project_id'])
    require(parent['id'] == root_id and parent['sha'] == source
            and parent['project_id'] == 3 and row['commit']['id'] == source,
            'active graph job identity mismatch')
    return dict(id=row['id'], name=row['name'], status=row['status'],
                pipeline=root_id, project_id=3, source=source)


def active_freezer(api, root_id, name, env, source):
    return active_job(api, root_id, B['input_job_names'](name), env, source)


def freeze_node(env, api):
    require(selected(env) == 'node'
            and env.get('CI_JOB_NAME') == 'Freeze release inputs ' + env['RELEASE_GRAPH_MEMBER'], 'node not selected')
    source = I['identity'](env, Path(env.get('CI_PROJECT_DIR', '')))
    graph_pipeline, graph_job = int(env['RELEASE_GRAPH_INPUT_PIPELINE']), int(env['RELEASE_GRAPH_INPUT_JOB'])
    root_id = int(env['RELEASE_GRAPH_ROOT_PIPELINE'])
    require(int(env['CI_PIPELINE_ID']) == root_id and root_id != graph_pipeline, 'wrong flattened graph pipeline')
    producer = B['job'](api, 'nest/config', graph_pipeline, graph_job, source)
    require(producer['name'] == 'Compile release graph', 'wrong graph publication job')
    path = B['prefix']('nest/config') + '/jobs/' + str(graph_job) + '/artifacts/release-graph/request.json'
    raw = api.get(path)
    require(hashlib.sha256(raw).hexdigest() == env['RELEASE_GRAPH_INPUT_SHA256'], 'graph input bytes changed')
    request = B['decode'](raw)
    indexed, nodes, dependencies, _ = selection(request)
    verifying = env.get('RELEASE_GRAPH_NODE') == 'verify-inputs'
    if verifying:
        verification_selection(request)
    require(request['expectations']['sources']['nest/config'] == source, 'graph uses another source')
    name = env['RELEASE_GRAPH_MEMBER']
    require(name in nodes, 'unknown graph node')
    # Bind the running freezer job to this graph, not a caller-supplied node pipeline.
    root = D['pipeline'](api, 'nest/config', root_id, source, root=True)
    require(root['source'] == 'parent_pipeline', 'wrong graph root source')
    active = active_freezer(api, root_id, name, env, source)
    # Prove the root is the compiler's artifact-backed child, not another graph.
    compiler_routes = D['listing'](api, 'nest/config', graph_pipeline, 'bridges')
    matches = [b for b in compiler_routes if b['name'] == 'Run release graph']
    require(len(matches) == 1 and matches[0]['status'] == 'running' and matches[0].get('allow_failure') is False
            and matches[0]['pipeline']['id'] == graph_pipeline and matches[0]['pipeline']['sha'] == source
            and matches[0]['downstream_pipeline']['id'] == root_id
            and matches[0]['downstream_pipeline']['sha'] == source
            and matches[0]['downstream_pipeline']['project_id'] == 3, 'graph root is not the published child')
    node = nodes[name]
    producers, observations = {}, {}
    for parent in sorted(dependencies[name]):
        resolved, observations[parent] = native_node(api, request, root_id, parent)
        producers[parent] = dict(project=indexed[parent]['project'], member=parent,
                                 job_name=nodes[parent]['job_name'], **resolved)
    expected = copy.deepcopy(request['expectations'])
    discovery = None
    if producers:
        discovery = dict(schema=1, kind='nest_release_base_discovery', expectations=expected,
                         executor_job=request['executor_job'], producers=producers,
                         bindings=[dict(target=name, **edge) for edge in node['bindings']])
    selected_input = discovery or expected
    # Reserve the local node before input publication. A retry is a fresh CI job,
    # never a trigger API retry or reuse of an ambiguous old result directory.
    submitted = Path(env['CI_PROJECT_DIR']) / 'graph-node-input.json'
    with submitted.open('xb') as stream:
        stream.write(R['canonical'](selected_input))
        stream.flush()
        os.fsync(stream.fileno())
    route_env = dict(env, RELEASE_ROUTE='verify-inputs' if verifying else 'true', RELEASE_ROUTE_MEMBER=name,
                     RELEASE_ROUTE_EXECUTOR_PIPELINE=str(request['executor_job']['pipeline']),
                     RELEASE_ROUTE_EXECUTOR_JOB=str(request['executor_job']['job']))
    # The ordinary route sees no graph selection and never recursively schedules it.
    for key in KEYS:
        route_env.pop(key, None)
    if node['placement'] is not None:
        route_env['RELEASE_ROUTE_PLACEMENT'] = node['placement']
    def guard():
        # Called after ordinary discovery AND route acquisition, immediately
        # before publication. A graph-parent retry during result reads must not
        # escape the ordinary leaf edge's independent race checks.
        for parent in sorted(producers):
            again, observation = native_node(api, request, root_id, parent)
            require(observation == observations[parent] and all(again[k] == producers[parent][k] for k in again),
                    'predecessor changed before freeze')
        require(B['job'](api, 'nest/config', graph_pipeline, graph_job, source) == producer and api.get(path) == raw,
                'graph publication changed during acquisition')
        require(active_freezer(api, root_id, name, env, source) == active, 'active graph freezer changed')
        for pipeline_id, bridge_name, original in ((graph_pipeline, 'Run release graph', matches[0]),):
            rows = D['listing'](api, 'nest/config', pipeline_id, 'bridges')
            found = [b for b in rows if b['name'] == bridge_name]
            require(len(found) == 1, 'active graph bridge disappeared')
            for key in ('id', 'status', 'allow_failure'):
                require(found[0][key] == original[key], 'active graph bridge changed')
            for key in ('id', 'sha', 'project_id'):
                require(found[0]['pipeline'][key] == original['pipeline'][key]
                        and found[0]['downstream_pipeline'][key] == original['downstream_pipeline'][key],
                        'active graph lineage changed')
    return I['publish'](submitted, route_env, discovery=discovery is not None, api=api, before_publication=guard)


def accept_graph(env, api):
    """Verify leaf outputs too; a green bridge alone is not a release receipt."""
    require(env.get('CI_PIPELINE_SOURCE') == 'parent_pipeline' and env.get('CI_JOB_NAME') == 'Accept release graph'
            and not any(env.get(k) for k in CONFLICTS + KEYS[:4]), 'invalid graph acceptance selection')
    source = I['identity'](env, Path(env.get('CI_PROJECT_DIR', '')))
    for key in ('RELEASE_GRAPH_INPUT_PIPELINE', 'RELEASE_GRAPH_INPUT_JOB', 'RELEASE_GRAPH_ROOT_PIPELINE'):
        R['match'](env.get(key), r'[1-9][0-9]{0,19}', 'acceptance resource')
    R['match'](env.get('RELEASE_GRAPH_INPUT_SHA256'), r'[0-9a-f]{64}', 'graph artifact digest')
    graph_pipeline, graph_job = int(env['RELEASE_GRAPH_INPUT_PIPELINE']), int(env['RELEASE_GRAPH_INPUT_JOB'])
    root_id = int(env['RELEASE_GRAPH_ROOT_PIPELINE'])
    require(root_id == int(env['CI_PIPELINE_ID']) and root_id != graph_pipeline, 'wrong acceptance pipeline')
    active = active_job(api, root_id, ('Accept release graph',), env, source)
    producer = B['job'](api, 'nest/config', graph_pipeline, graph_job, source)
    require(producer['name'] == 'Compile release graph', 'wrong graph publication')
    path = B['prefix']('nest/config') + '/jobs/' + str(graph_job) + '/artifacts/release-graph/request.json'
    raw = api.get(path)
    require(hashlib.sha256(raw).hexdigest() == env['RELEASE_GRAPH_INPUT_SHA256'], 'graph bytes changed')
    request = B['decode'](raw)
    indexed, nodes, _, order = selection(request)
    require(request['expectations']['sources']['nest/config'] == source, 'wrong acceptance source')
    compiler = D['listing'](api, 'nest/config', graph_pipeline, 'bridges')
    routes = [b for b in compiler if b['name'] == 'Run release graph']
    require(len(routes) == 1 and routes[0]['status'] == 'running' and routes[0].get('allow_failure') is False
            and routes[0]['pipeline']['id'] == graph_pipeline and routes[0]['pipeline']['sha'] == source
            and routes[0]['downstream_pipeline']['id'] == root_id
            and routes[0]['downstream_pipeline']['sha'] == source
            and routes[0]['downstream_pipeline']['project_id'] == 3, 'unbound graph acceptance')
    expected = copy.deepcopy(request['expectations'])
    outputs: dict[str, Any] = {}
    acquired = {}
    producers, observations = {}, {}
    for name in order:
        resolved, observations[name] = native_node(api, request, root_id, name)
        selector = dict(project=indexed[name]['project'], member=name, job_name=nodes[name]['job_name'], **resolved)
        producers[name] = selector
        actual, native = D['edge'](api, source, expected['sources'][selector['project']], selector)
        acquired[name] = dict(selector=actual, native=native)
        original = B['artifact'](api, 'nest/config', actual['input_job'], 'release-inputs/expectations.json', actual['input_sha256'])
        result = B['decode'](B['result_bytes'](api, selector['project'], actual['job'], name, actual['result_sha256']))
        output = B['check_result'](original, result, actual)
        selected_member = copy.deepcopy(indexed[name])
        for edge in nodes[name]['bindings']:
            selected_member['bases'][edge['base']] = outputs[edge['producer']]['artifacts'][edge['artifact']]
        original_expected = copy.deepcopy(request['expectations'])
        original_expected['members'] = [selected_member if m['id'] == name else m for m in original_expected['members']]
        require(original == I['project_member'](original_expected, name) and output['member'] == selected_member
                and output['executor'] == expected['executor'], 'graph leaf escaped frozen inputs or dependency bases')
        outputs[name] = output
        expected['members'] = [selected_member if m['id'] == name else m for m in expected['members']]
    # Assemble all rebuilt outputs with the existing independent executor/result
    # rechecks. Reuse/defer/retire decisions remain explicit and unclaimed here.
    expected['members'] = [m for m in expected['members'] if m['id'] in nodes]
    for consumer in expected['consumers']:
        consumer['members'] = [m for m in consumer['members'] if m in nodes]
        if not consumer['members'] and consumer['decision'] == 'reuse':
            consumer['decision'] = 'defer'
    assembled = A['assemble'](dict(schema=1, kind='nest_release_assembly', expectations=expected,
                                 executor_job=request['executor_job'], producers=producers), api)
    # Assembly independently reacquires each leaf, but must not silently replace
    # the bytes or inner native edge used above to reconstruct descendant bases.
    # Two internally consistent observations are not one consistent graph.
    assembled_outputs = {row['member']['id']: row for row in assembled['manifest']['candidate']['outputs']}
    require(assembled['members'] == acquired and assembled_outputs == outputs,
            'graph member changed before assembly')
    for name in order:
        _, observation = native_node(api, request, root_id, name)
        require(observation == observations[name], 'graph lineage changed during acceptance')
    require(B['job'](api, 'nest/config', graph_pipeline, graph_job, source) == producer and api.get(path) == raw,
            'graph publication changed during acceptance')
    fresh = [b for b in D['listing'](api, 'nest/config', graph_pipeline, 'bridges') if b['name'] == 'Run release graph']
    require(len(fresh) == 1, 'graph compiler bridge disappeared')
    for key in ('id', 'status', 'allow_failure'):
        require(fresh[0][key] == routes[0][key], 'graph compiler bridge changed')
    for key in ('id', 'sha', 'project_id'):
        require(fresh[0]['pipeline'][key] == routes[0]['pipeline'][key]
                and fresh[0]['downstream_pipeline'][key] == routes[0]['downstream_pipeline'][key],
                'graph compiler lineage changed')
    require(active_job(api, root_id, ('Accept release graph',), env, source) == active,
            'active graph acceptance job changed')
    receipt = dict(schema=1, kind='nest_release_graph_acceptance', graph_sha256=hashlib.sha256(raw).hexdigest(),
                   graph_pipeline=root_id, acceptance_job=active['id'], inputs=request, rebuilt=assembled,
                   unbuilt_decisions=[c for c in request['expectations']['consumers'] if c['decision'] != 'rebuild'],
                   resource_verification='successful_native_jobs_and_exact_artifact_bytes_only',
                   image_compatibility_verification='not_performed', promotion_authorized=False)
    publish(Path(env['CI_PROJECT_DIR']) / 'release-graph-acceptance', {'receipt.json': R['canonical'](receipt)})
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--check-selection', action='store_true')
    choice.add_argument('--compile', action='store_true')
    choice.add_argument('--freeze-node', action='store_true')
    choice.add_argument('--accept', action='store_true')
    args = parser.parse_args()
    try:
        if args.check_selection:
            require(selected(os.environ) is not None, 'no graph selected')
        elif args.compile:
            if os.environ.get('RELEASE_GRAPH') == 'verify-inputs':
                compile_graph(R['load'](os.environ['RELEASE_GRAPH_FILE']), os.environ)
                print('Graph input verification route retained; no candidate execution authorized')
                return 0
            # The compiler/freezer/acceptance source now uses two child levels.
            # Retain refusal until the exact contracts, not only the prior
            # status-only nesting fixture, pass nonpublishing live acceptance.
            print('Release graph scheduling unavailable: flattened graph acceptance pending; '
                  'use the existing standalone frozen-input route', file=sys.stderr)
            return 1
        elif args.accept:
            accept_graph(os.environ, GitLab())
        else:
            freeze_node(os.environ, GitLab())
        print('Release graph selection or artifact readback passed; no host operation performed')
        return 0
    except (OSError, ValueError, KeyError, TypeError, RecursionError, StopIteration, subprocess.SubprocessError):
        print('Release graph refused or failed', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
