#!/usr/bin/env python3
"""Admit only the isolated, nonpublishing native GitLab status fixture."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

CONFLICTS = (
    'RELEASE_INPUTS', 'EXECUTOR_ONLY', 'BUILD', 'CPU', 'RUNNER_SMOKE_TAG',
    'RELEASE_CANDIDATE', 'RELEASE_DAG', 'RELEASE_DAG_FIXTURE',
    'RELEASE_VALIDATE_ONLY', 'RELEASE_CPU', 'RELEASE_MEMBER',
    'RELEASE_INPUT_JOB_ID', 'RELEASE_INPUT_SHA256', 'RELEASE_EXECUTOR_JOB_ID',
    'RELEASE_EXECUTOR_IMAGE', 'FROM_GENTOO', 'STAGE0_RESUME', 'REFRESH',
    'NEST_LEGACY_BUILD', 'RELEASE_PLATFORM', 'PLATFORM', 'RELEASE_VARIANT',
    'VARIANT', 'RELEASE_MODE', 'RELEASE_HOST', 'RELEASE_STAGE3_PLACEMENT_FILE',
    'HOSTNAME', 'CLUSTER', 'PROFILE',
    'RELEASE_GRAPH', 'RELEASE_GRAPH_FILE', 'RELEASE_GRAPH_NODE', 'RELEASE_GRAPH_MEMBER',
    'RELEASE_GRAPH_INPUT_PIPELINE', 'RELEASE_GRAPH_INPUT_JOB', 'RELEASE_GRAPH_INPUT_SHA256',
    'RELEASE_GRAPH_ROOT_PIPELINE',
    'EXECUTOR_BOOTSTRAP', 'RELEASE_BOOTSTRAP_FILE', 'RELEASE_ROUTE',
    'RELEASE_BOOTSTRAP_PIPELINE', 'RELEASE_BOOTSTRAP_JOB', 'RELEASE_BOOTSTRAP_SHA256',
    'RELEASE_ROUTE_MEMBER', 'RELEASE_ROUTE_EXECUTOR_PIPELINE',
    'RELEASE_ROUTE_EXECUTOR_JOB', 'RELEASE_ROUTE_PLACEMENT',
)


def nested_mode(env):
    mode = env.get('NEST_DAG_FIXTURE', '')
    for prefix, sources in (('nested-stage1-', ('api', 'web')), ('node-stage1-', ('parent_pipeline',))):
        if mode in (prefix + 'pass', prefix + 'fail') and env.get('CI_PIPELINE_SOURCE') in sources:
            return ('root' if prefix.startswith('nested') else 'node', mode.rsplit('-', 1)[1])
    return None


def admitted(env):
    direct = (env.get('NEST_DAG_FIXTURE') in ('pass', 'fail', 'stage1-pass', 'stage1-fail', 'stage2-pass', 'stage2-fail', 'stage3-pass', 'stage3-fail', 'bolt-pass', 'bolt-fail', 'pdk-pass', 'pdk-fail', 'agent-pass', 'agent-fail', 'firefox-pass', 'firefox-fail', 'camofox-pass', 'camofox-fail', 'llama-pass', 'llama-fail') and
              env.get('CI_PIPELINE_SOURCE') in ('api', 'web'))
    return ((direct or nested_mode(env) is not None) and
            not env.get('CI_COMMIT_TAG') and
            not any(env.get(key) for key in CONFLICTS))


def compile_nested(env):
    mode = nested_mode(env)
    if not admitted(env) or mode is None:
        raise ValueError('nested fixture selection refused')
    layer, outcome = mode
    if (env.get('CI_PROJECT_PATH') != 'nest/config' or env.get('CI_COMMIT_BRANCH') != 'main'
            or env.get('CI_JOB_NAME') != 'Compile nested DAG fixture'):
        raise ValueError('wrong nested fixture project, branch or job')
    root = Path(env['CI_PROJECT_DIR'])
    source = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    if source != env.get('CI_COMMIT_SHA') or subprocess.check_output(
            ['git', '-C', str(root), 'status', '--porcelain', '--untracked-files=no']):
        raise ValueError('nested fixture checkout changed')
    for key in ('CI_PIPELINE_ID', 'CI_JOB_ID'):
        value = env.get(key, '')
        if not value.isascii() or not value.isdecimal() or int(value) <= 0:
            raise ValueError('invalid nested fixture resource identity')
    graph: dict = {'workflow': {'rules': [{'if': '$CI_PIPELINE_SOURCE == "parent_pipeline"'}, {'when': 'never'}]}}
    if layer == 'root':
        # A same-project trigger:project is invalid in GitLab. Use a native
        # child and keep the freezer in that child, leaving depth two for its
        # artifact-backed route. Never add a third same-project child layer.
        graph.update({'include': [{'local': '.gitlab-ci.yml'}],
                      'variables': {'NEST_DAG_FIXTURE': 'node-stage1-' + outcome},
                      # This bridge disables YAML inheritance. Keep its fixed
                      # selection explicit at job scope; forwarding stays off.
                      'Run nested DAG fixture': {'variables': {'NEST_DAG_FIXTURE': 'node-stage1-' + outcome}}})
    else:
        graph.update({'stages': ['Fixture'], 'Fixture Stage 1 leaf': {
            'stage': 'Fixture', 'allow_failure': False, 'inherit': {'variables': False},
            'variables': {'RELEASE_DAG': 'true', 'RELEASE_VALIDATE_ONLY': 'true', 'RELEASE_DAG_FIXTURE': outcome},
            'trigger': {'project': 'nest/stage1', 'branch': 'main', 'strategy': 'mirror',
                        'forward': {'yaml_variables': True, 'pipeline_variables': False}},
        }})
    raw = (json.dumps(graph, sort_keys=True, indent=2) + '\n').encode()
    receipt = dict(schema=1, kind='nest_nested_dag_status_fixture', source=source,
                   pipeline=int(env['CI_PIPELINE_ID']), job=int(env['CI_JOB_ID']),
                   layer=layer, expected_outcome=outcome, child_sha256=hashlib.sha256(raw).hexdigest(),
                   candidate_builds=False, publication=False, host_actions=False)
    records = {'child.yml': raw, 'receipt.json': (json.dumps(receipt, sort_keys=True, indent=2) + '\n').encode()}
    directory = root / 'nested-dag-fixture'
    directory.mkdir(mode=0o700)
    for name, content in records.items():
        with (directory / name).open('xb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    if any((directory / name).read_bytes() != content for name, content in records.items()):
        raise ValueError('nested fixture artifact readback failed')
    return receipt


def main():
    if sys.argv[1:] == ['--compile-nested']:
        try:
            compile_nested(os.environ)
        except (KeyError, ValueError, OSError, subprocess.SubprocessError):
            print('Nested status fixture refused; no build or deployment', file=sys.stderr)
            return 1
        print('Published nonpublishing nested status fixture; no release execution')
        return 0
    if sys.argv[1:] or not admitted(os.environ):
        print('Release DAG fixture selection refused; no build or deployment', file=sys.stderr)
        return 1
    print('Nonpublishing native status fixture selected; no release execution')
    return 0


if __name__ == '__main__':
    sys.exit(main())
