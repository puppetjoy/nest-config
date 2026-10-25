#!/usr/bin/env python3
"""Compile one frozen input publication into a native, failure-propagating bridge."""

from pathlib import Path
import re
import runpy
import os
import sys

B = runpy.run_path(str(Path(__file__).with_name('nest-release-bind.py')))
R = B['RELEASE']
require = R['require']

# These are compiler inputs, not variables forwarded to a candidate pipeline.
ROUTE_KEYS = ('RELEASE_ROUTE', 'RELEASE_ROUTE_MEMBER', 'RELEASE_ROUTE_EXECUTOR_PIPELINE',
              'RELEASE_ROUTE_EXECUTOR_JOB', 'RELEASE_ROUTE_PLACEMENT')
CONFLICTS = ('BUILD', 'EXECUTOR_ONLY', 'EXECUTOR_BOOTSTRAP', 'RELEASE_BOOTSTRAP_FILE',
             'RELEASE_BOOTSTRAP_PIPELINE', 'RELEASE_BOOTSTRAP_JOB', 'RELEASE_BOOTSTRAP_SHA256',
             'RELEASE_CANDIDATE', 'RELEASE_VALIDATE_ONLY',
             'NEST_DAG_FIXTURE', 'RELEASE_DAG', 'RELEASE_DAG_FIXTURE', 'RELEASE_MEMBER',
             'RELEASE_CPU', 'RELEASE_PLATFORM', 'RELEASE_VARIANT', 'RELEASE_HOST',
             'RELEASE_INPUT_JOB_ID', 'RELEASE_INPUT_SHA256', 'RELEASE_EXECUTOR_IMAGE',
             'RELEASE_EXECUTOR_JOB_ID', 'RELEASE_STAGE3_PLACEMENT_FILE', 'REFRESH',
             'NEST_LEGACY_BUILD', 'FROM_GENTOO', 'STAGE0_RESUME', 'CPU', 'VARIANT',
             'PLATFORM', 'CLUSTER', 'PROFILE', 'RUNNER_SMOKE_TAG')


def selected(env):
    requested = any(env.get(key) for key in ROUTE_KEYS)
    if requested:
        require(env.get('RELEASE_ROUTE') in ('true', 'verify-inputs'), 'explicit release routing required')
        require(env.get('RELEASE_INPUTS') == 'true', 'routing requires frozen inputs')
        native_freezer = (env.get('CI_PIPELINE_SOURCE') == 'parent_pipeline'
                          and env.get('CI_JOB_NAME') == 'Freeze release inputs ' + str(env.get('RELEASE_ROUTE_MEMBER')))
        require((env.get('CI_PIPELINE_SOURCE') in ('api', 'web', 'pipeline', 'trigger') or native_freezer)
                and not env.get('CI_COMMIT_TAG'), 'unsupported routing source')
        require(not any(env.get(key) for key in CONFLICTS), 'conflicting routing selection')
        R['match'](env.get('RELEASE_ROUTE_MEMBER'), R['TOKEN'], 'routing member')
        for key in ('RELEASE_ROUTE_EXECUTOR_PIPELINE', 'RELEASE_ROUTE_EXECUTOR_JOB'):
            R['match'](env.get(key), r'[1-9][0-9]{0,19}', 'routing executor identity')
    return requested


def compile_bridge(expected, receipt, env, api):
    """Accept exact executor evidence, then emit JSON (a YAML subset), never trigger."""
    require(selected(env), 'no candidate routing selected')
    members = R['expectations'](expected)
    identifier = env['RELEASE_ROUTE_MEMBER']
    require(identifier in members, 'unknown routing member')
    member = members[identifier]
    verifying = env['RELEASE_ROUTE'] == 'verify-inputs'
    require(not verifying or (member['stage'] == 'stage0' and member['project'] == 'nest/stage0'
                             and member['mode'] == 'refresh' and member['variant'] == 'server'),
            'input verification only supports Stage 0 refresh')
    require(member['project'] in B['PROJECTS'] - {'nest/config'}, 'unsupported routing project')
    consumer = next(row for row in expected['consumers'] if row['project'] == member['project'])
    require(consumer['decision'] == 'rebuild', 'routing requires rebuild decision')
    # Reuse the existing exact job/receipt and architecture admission contract.
    # This does not prove registry existence, hardware ISA, or module ABI contents.
    pipeline = int(env['RELEASE_ROUTE_EXECUTOR_PIPELINE'])
    job_id = int(env['RELEASE_ROUTE_EXECUTOR_JOB'])
    require(job_id != receipt['producer']['job'], 'executor and input job cannot coincide')
    observed = B['job'](api, 'nest/config', pipeline, job_id, expected['executor']['source'])
    cpu = B['CPUS'].get(member['cpu'])
    if cpu is None:
        raise ValueError('unsupported routing executor CPU')
    require(observed['name'] == 'Build ' + cpu, 'wrong routing executor job')
    executor = B['artifact'](api, 'nest/config', job_id, 'executor-receipts/' + cpu + '.json')
    B['check_executor'](executor, expected, member['cpu'])
    require(executor['pipeline'] == pipeline and executor['job'] == job_id, 'executor receipt identity mismatch')
    variables = {
        'RELEASE_DAG': 'true', 'RELEASE_CANDIDATE': 'true',
        'RELEASE_MEMBER': identifier, 'RELEASE_CPU': member['cpu'],
        'RELEASE_INPUT_JOB_ID': str(receipt['producer']['job']),
        'RELEASE_INPUT_SHA256': receipt['artifact_sha256'],
        'RELEASE_EXECUTOR_JOB_ID': str(job_id),
        'RELEASE_EXECUTOR_IMAGE': expected['executor']['image'],
    }
    if verifying:
        del variables['RELEASE_CANDIDATE']
        variables.update(RELEASE_VERIFY_INPUTS='true', RELEASE_VALIDATE_ONLY='true')
    require(re.fullmatch(r'registry[.]gitlab[.]joyfullee[.]me/nest/config/[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}',
                         variables['RELEASE_EXECUTOR_IMAGE']) is not None, 'unsupported executor registry')
    if member['stage'] != 'stage0':
        variables['RELEASE_VARIANT'] = member['variant']
    if member['stage'] in ('stage2', 'stage3'):
        variables['RELEASE_PLATFORM'] = member['platform']
    if member['stage'] == 'stage3':
        placement = env.get('RELEASE_ROUTE_PLACEMENT')
        R['absolute_path'](placement, 'routing placement')
        require('$' not in placement, 'variable expansion in placement path')
        variables.update(RELEASE_HOST=member['host'], HOSTNAME='', RELEASE_STAGE3_PLACEMENT_FILE=placement)
    else:
        require(not env.get('RELEASE_ROUTE_PLACEMENT'), 'placement only belongs to Stage 3')
    # Nothing caller-controlled is interpolated into script, include, project, ref
    # or image syntax. The downstream validates actual checkout SHA against inputs;
    # a moving main branch refuses rather than silently changing selected source.
    graph = {
        'workflow': {'rules': [{'if': '$CI_PIPELINE_SOURCE == "parent_pipeline"'}, {'when': 'never'}]},
        'stages': ['Candidate'],
        'Build frozen member': {
            'stage': 'Candidate', 'allow_failure': False, 'inherit': {'variables': False},
            'variables': variables,
            'trigger': {'project': member['project'], 'branch': 'main', 'strategy': 'mirror',
                        'forward': {'yaml_variables': True, 'pipeline_variables': False}},
        },
    }
    if verifying:
        graph['Verify frozen inputs'] = graph.pop('Build frozen member')
    # Re-read the independently selected executor resource and artifact before
    # permitting publication. No retries or mutable latest-success lookups.
    require(B['job'](api, 'nest/config', pipeline, job_id, expected['executor']['source']) == observed
            and B['artifact'](api, 'nest/config', job_id, 'executor-receipts/' + cpu + '.json') == executor,
            'routing executor changed during acquisition')
    return graph


def main():
    try:
        require(sys.argv[1:] == ['--check-selection'] and selected(os.environ), 'invalid route selection')
        print('Frozen candidate route selected; no build or trigger performed')
        return 0
    except (ValueError, KeyError, TypeError):
        print('Frozen candidate route selection refused', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
