#!/usr/bin/env python3
"""Acquire a prior OpenBolt result for a distinct config executor build.

Only reads exact GitLab resources and retains inputs. Never builds or triggers.
"""

import argparse
import hashlib
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
from typing import Any

B = runpy.run_path(str(Path(__file__).with_name('nest-release-bind.py')))
D = runpy.run_path(str(Path(__file__).with_name('nest-release-discover.py')))
R = B['RELEASE']
require = R['require']
KEYS = ('EXECUTOR_BOOTSTRAP', 'RELEASE_BOOTSTRAP_FILE')
CONFLICTS = ('RELEASE_INPUTS', 'RELEASE_ROUTE', 'RELEASE_ROUTE_MEMBER',
             'RELEASE_ROUTE_EXECUTOR_PIPELINE', 'RELEASE_ROUTE_EXECUTOR_JOB',
             'RELEASE_ROUTE_PLACEMENT', 'RELEASE_EXPECTATIONS_FILE', 'RELEASE_DISCOVERY_FILE',
             'RELEASE_CANDIDATE', 'RELEASE_VALIDATE_ONLY', 'RELEASE_DAG', 'RELEASE_DAG_FIXTURE',
             'NEST_DAG_FIXTURE', 'RELEASE_MEMBER', 'RELEASE_CPU', 'RELEASE_PLATFORM',
             'RELEASE_VARIANT', 'RELEASE_HOST', 'RELEASE_INPUT_JOB_ID', 'RELEASE_INPUT_SHA256',
             'RELEASE_EXECUTOR_IMAGE', 'RELEASE_EXECUTOR_JOB_ID', 'BOLT_IMAGE',
             'REFRESH', 'NEST_LEGACY_BUILD', 'FROM_GENTOO', 'STAGE0_RESUME', 'RUNNER_SMOKE_TAG')
CPUS = ('haswell', 'cortex-a53', 'sifive-u74')


def leaf(api, selector, source):
    pipeline = D['pipeline'](api, 'nest/tools/bolt', selector['pipeline'], source)
    require(not D['listing'](api, 'nest/tools/bolt', selector['pipeline'], 'bridges'),
            'OpenBolt must not trigger another config executor')
    jobs = D['listing'](api, 'nest/tools/bolt', selector['pipeline'], 'jobs')
    require(jobs and all(row['status'] == 'success' and row.get('allow_failure') is False
                        and row.get('erased_at') is None for row in jobs), 'incomplete OpenBolt pipeline')
    require(sum(row['id'] == selector['job'] for row in jobs) == 1, 'OpenBolt result job missing')
    return dict(pipeline=pipeline, jobs=[dict(id=row['id'], name=row['name']) for row in jobs])


def selected(env):
    requested = any(env.get(key) for key in KEYS)
    if requested:
        require(env.get('EXECUTOR_BOOTSTRAP') == 'true' and env.get('RELEASE_BOOTSTRAP_FILE'),
                'explicit bootstrap and input file required')
        require(env.get('EXECUTOR_ONLY') == 'true' and env.get('BUILD') in CPUS,
                'bootstrap requires one explicit executor architecture')
        require(env.get('CI_PIPELINE_SOURCE') in ('api', 'web', 'pipeline', 'trigger')
                and not env.get('CI_COMMIT_TAG'), 'unsupported bootstrap source')
        require(not any(env.get(key) for key in CONFLICTS), 'conflicting bootstrap selection')
    return requested


def identity(env):
    require(selected(env), 'bootstrap not selected')
    require(env.get('CI_PROJECT_PATH') == 'nest/config' and env.get('CI_PROJECT_ID') == '3',
            'wrong bootstrap project')
    source = env.get('CI_COMMIT_SHA')
    R['match'](source, R['SHA'], 'successor source')
    for key in ('CI_PIPELINE_ID', 'CI_JOB_ID'):
        R['match'](env.get(key), r'[1-9][0-9]{0,19}', 'successor job identity')
    require(env.get('CPU') == env['BUILD'], 'wrong successor architecture')
    checkout = Path(env.get('CI_PROJECT_DIR', ''))
    require(checkout.is_absolute() and checkout.resolve() == checkout and checkout.is_dir(),
            'invalid successor checkout')

    def git(*args):
        return subprocess.check_output(['git', '-C', str(checkout), *args],
                                       stderr=subprocess.DEVNULL, timeout=30).decode('ascii').strip()

    require(git('rev-parse', 'HEAD') == source
            and not git('status', '--porcelain', '--untracked-files=no'), 'successor checkout mismatch')
    return checkout, source


def selection(request, source, cpu):
    """Admit the complete bootstrap selector before any external acquisition."""
    R['fields'](request, 'schema kind successor_source successor_cpu producer', 'bootstrap request')
    require(type(request['schema']) is int and request['schema'] == 1
            and request['kind'] == 'nest_executor_bootstrap', 'unsupported bootstrap request')
    R['match'](source, R['SHA'], 'successor source')
    require(request['successor_source'] == source and request['successor_cpu'] == cpu
            and cpu in CPUS, 'wrong bootstrap successor')
    selector = request['producer']
    R['fields'](selector, 'project pipeline job member input_pipeline input_job input_sha256 result_sha256',
                'OpenBolt producer')
    require(selector['project'] == 'nest/tools/bolt', 'bootstrap requires OpenBolt')
    R['match'](selector['member'], R['TOKEN'], 'OpenBolt member')
    # Validate every selector before the first external read.
    for key in ('pipeline', 'job', 'input_pipeline', 'input_job'):
        B['positive'](selector[key])
    for key in ('input_sha256', 'result_sha256'):
        R['match'](selector[key], r'[0-9a-f]{64}', 'OpenBolt artifact digest')
    return selector


def acquire(request, source, cpu, api) -> dict[str, Any]:
    """Keep old expectations/result untouched; cross-source only at this boundary."""
    selector = selection(request, source, cpu)
    input_path = 'release-inputs/expectations.json'
    raw_input = api.get(B['prefix']('nest/config') + '/jobs/' + str(selector['input_job']) + '/artifacts/' + input_path)
    require(hashlib.sha256(raw_input).hexdigest() == selector['input_sha256'], 'OpenBolt input bytes changed')
    expected = B['decode'](raw_input)
    members = R['expectations'](expected)
    old_source = expected['sources']['nest/config']
    old_executor_source = expected['executor']['source']
    require(old_source != source and old_executor_source != source, 'bootstrap requires distinct config sources')
    require(selector['member'] in members, 'missing OpenBolt member')
    member = members[selector['member']]
    require(member['stage'] == 'tool' and member['project'] == 'nest/tools/bolt'
            and member['cpu'] == cpu and member['variant'] == 'server', 'incompatible OpenBolt member')
    require(next(row['decision'] for row in expected['consumers'] if row['project'] == 'nest/tools/bolt') == 'rebuild',
            'bootstrap requires a newly produced OpenBolt result')
    input_job = B['job'](api, 'nest/config', selector['input_pipeline'], selector['input_job'], old_source)
    require(input_job['name'] in B['input_job_names'](selector['member']), 'wrong OpenBolt input job')
    producer = B['job'](api, 'nest/tools/bolt', selector['pipeline'], selector['job'],
                        expected['sources']['nest/tools/bolt'])
    observed_leaf = leaf(api, selector, expected['sources']['nest/tools/bolt'])
    raw_result = B['result_bytes'](api, 'nest/tools/bolt', selector['job'], selector['member'], selector['result_sha256'])
    result = B['decode'](raw_result)
    output = B['check_result'](expected, result, selector)
    image = output['artifacts']['image']
    require(re.fullmatch(r'registry[.]gitlab[.]joyfullee[.]me/nest/tools/bolt/[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}',
                         image) is not None, 'unsupported OpenBolt publication')
    # Independently read the OLD executor job and actual receipt, not merely the
    # embedded declaration. No successor executor is a prerequisite for itself.
    embedded = result['executor_receipt']
    executor_job = B['job'](api, 'nest/config', embedded['pipeline'], embedded['job'], old_executor_source)
    require(executor_job['name'] == 'Build ' + cpu, 'wrong old executor job')
    executor_path = 'executor-receipts/' + cpu + '.json'
    executor = B['artifact'](api, 'nest/config', embedded['job'], executor_path)
    require(executor == embedded, 'old executor receipt mismatch')
    B['check_executor'](executor, expected, cpu)
    for row in (input_job, producer, executor_job):
        require(B['job'](api, row['project'], row['pipeline'], row['job'], row['source']) == row,
                'bootstrap resource changed during acquisition')
    require(api.get(B['prefix']('nest/config') + '/jobs/' + str(selector['input_job']) + '/artifacts/' + input_path) == raw_input
            and B['result_bytes'](api, 'nest/tools/bolt', selector['job'], selector['member'], selector['result_sha256']) == raw_result
            and B['artifact'](api, 'nest/config', embedded['job'], executor_path) == executor,
            'bootstrap artifact changed during acquisition')
    require(leaf(api, selector, expected['sources']['nest/tools/bolt']) == observed_leaf,
            'OpenBolt pipeline changed during acquisition')
    return dict(schema=1, kind='nest_executor_bootstrap_input', request_digest=R['digest'](request),
                successor=dict(source=source, cpu=cpu, base_image=image, build='not_started'),
                predecessor=dict(expectations=expected, input_sha256=selector['input_sha256'],
                                 result_sha256=selector['result_sha256'], result=result,
                                 input_job=input_job, producer=producer, executor_job=executor_job,
                                 native_pipeline=observed_leaf),
                resource_verification='successful_gitlab_jobs_and_exact_artifact_bytes_only',
                image_compatibility_verification='not_performed', promotion_authorized=False)


def publish(request_path, env, api):
    checkout, source = identity(env)
    request_path = Path(request_path)
    require(request_path.is_file() and not request_path.is_symlink(), 'invalid bootstrap file')
    result = acquire(R['load'](request_path), source, env['CPU'], api)
    result['successor'].update(pipeline=int(env['CI_PIPELINE_ID']), job=int(env['CI_JOB_ID']))
    raw = R['canonical'](result)
    require(len(raw) <= R['LIMIT'], 'bootstrap evidence exceeds size limit')
    reference = (result['successor']['base_image'] + '\n').encode('ascii')
    directory = checkout / 'executor-bootstrap'
    directory.mkdir(mode=0o700)
    for name, payload in [('receipt.json', raw), ('bolt.ref', reference)]:
        with (directory / name).open('xb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    require((directory / 'receipt.json').read_bytes() == raw
            and (directory / 'bolt.ref').read_bytes() == reference, 'bootstrap readback failed')
    require(identity(env) == (checkout, source), 'successor identity changed')
    return result['successor']['base_image']


def check_successor(row, directory):
    """Bind offline installed-image evidence to the separately retained input."""
    directory = Path(directory)
    receipt = R['load'](directory / 'receipt.json')
    require(type(receipt['schema']) is int and receipt['schema'] == 1
            and receipt['kind'] == 'nest_executor_bootstrap_input', 'wrong bootstrap receipt')
    actual = dict(source=row['sha'], cpu=row['cpu'], base_image=row['inputs']['base_image'],
                  pipeline=row['pipeline'], job=row['job'], build='not_started')
    require(receipt['successor'] == actual, 'actual successor differs from acquired bootstrap')
    require((directory / 'bolt.ref').read_bytes() == (actual['base_image'] + '\n').encode('ascii'),
            'bootstrap reference differs from actual base')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check-selection', action='store_true')
    mode.add_argument('--ci-base', action='store_true')
    args = parser.parse_args()
    try:
        enabled = selected(os.environ)
        if args.check_selection:
            require(enabled, 'bootstrap not selected')
            print('Exact executor bootstrap selected; no build or trigger performed')
        elif enabled:
            print(publish(os.environ['RELEASE_BOOTSTRAP_FILE'], os.environ, D['GitLab']()))
        else:
            # Ordinary build compatibility: the existing pipeline still resolves
            # and records a mutable default once. Bootstrap never takes this path.
            print(os.environ.get('BOLT_IMAGE') or 'nest/tools/bolt')
        return 0
    except (OSError, ValueError, KeyError, TypeError, RecursionError, subprocess.SubprocessError):
        print('Executor bootstrap acquisition refused or failed', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
