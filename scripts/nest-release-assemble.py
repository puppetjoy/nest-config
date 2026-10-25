#!/usr/bin/env python3
"""Assemble a complete candidate from exact native GitLab member artifacts.

Authenticated GETs only; never builds, retries, promotes, or operates hosts.
"""

import argparse
import copy
import json
from pathlib import Path
import runpy
import subprocess
import sys
from typing import Any

D = runpy.run_path(str(Path(__file__).with_name('nest-release-discover.py')))
B = D['BIND']
R = D['R']
require = R['require']


def acquire(expected, identifier, selector, executor_digest, api):
    """Validate the native edge and its original inputs, not submitted output rows."""
    member = next(row for row in expected['members'] if row['id'] == identifier)
    require(selector['member'] == identifier and selector['project'] == member['project'],
            'wrong assembly member selector')
    resolved, observation = D['edge'](api, expected['sources']['nest/config'],
                                      expected['sources'][member['project']], selector)
    original = B['artifact'](api, 'nest/config', resolved['input_job'], 'release-inputs/expectations.json',
                             resolved['input_sha256'])
    R['expectations'](original)
    require(original['sources'] == expected['sources'] and original['release'] == expected['release']
            and original['schema'] == expected['schema'] and original['executor'] == expected['executor'],
            'different release source or executor closure')
    result = B['decode'](B['result_bytes'](api, member['project'], resolved['job'], identifier, resolved['result_sha256']))
    output = B['check_result'](original, result, resolved)
    require(R['digest'](result['executor_receipt']) == executor_digest,
            'member did not retain the selected executor receipt')
    require(output['member'] == member and output['executor'] == expected['executor'],
            'assembled output differs from selected final inputs')
    original_consumer = next(c for c in original['consumers'] if c['project'] == member['project'])
    require(original_consumer['decision'] == 'rebuild', 'original input did not authorize member production')
    return output, dict(selector=resolved, native=observation)


def selection(request: Any):
    """Validate every selected member and executor before any acquisition."""
    R['fields'](request, 'schema kind expectations executor_job producers', 'assembly request')
    require(type(request['schema']) is int and request['schema'] == 1
            and request['kind'] == 'nest_release_assembly', 'unsupported assembly request')
    expected = copy.deepcopy(request['expectations'])
    indexed = R['expectations'](expected)
    producers: dict[str, Any] = request['producers']
    require(type(producers) is dict and set(producers) == set(indexed) and len(producers) <= 128,
            'assembly must select the complete member matrix')
    # An executor is architecture-specific. Assemble separate complete manifests
    # per architecture; never reinterpret an amd64 receipt as an ARM receipt.
    require(all(row['cpu'] in B['CPUS'] for row in indexed.values()), 'unsupported executor CPU')
    architectures = {B['CPUS'][row['cpu']] for row in indexed.values()}
    require(len(architectures) == 1, 'mixed executor architectures')
    architecture = next(iter(architectures))
    R['fields'](request['executor_job'], 'pipeline job', 'executor job')
    for value in request['executor_job'].values():
        B['positive'](value)
    for identifier, selector in producers.items():
        D['selector_fields'](selector)
        require(selector['member'] == identifier and selector['project'] == indexed[identifier]['project'],
                'wrong assembly member selector')
    return expected, indexed, architecture


def assemble(request: Any, api) -> dict[str, Any]:
    expected, indexed, architecture = selection(request)
    producers = request['producers']
    selected = request['executor_job']

    def executor():
        job = B['job'](api, 'nest/config', selected['pipeline'], selected['job'], expected['executor']['source'])
        require(job['name'] == 'Build ' + architecture, 'wrong assembly executor job')
        receipt = B['artifact'](api, 'nest/config', selected['job'], 'executor-receipts/' + architecture + '.json')
        B['check_executor'](receipt, expected, next(iter(indexed.values()))['cpu'])
        require(receipt['pipeline'] == selected['pipeline'] and receipt['job'] == selected['job'],
                'executor receipt resource mismatch')
        return dict(job=job, receipt_digest=R['digest'](receipt))

    executor_before = executor()
    outputs, observations = [], {}
    resources = set()
    for identifier in sorted(indexed):
        output, observation = acquire(expected, identifier, producers[identifier], executor_before['receipt_digest'], api)
        resource = (output['producer']['project'], output['producer']['pipeline'], output['producer']['job'])
        require(resource not in resources, 'one producer job cannot supply multiple members')
        resources.add(resource)
        outputs.append(output)
        observations[identifier] = observation
    candidate = dict(schema=1, kind='nest_release_candidate', release=expected['release'],
                     expectations_digest=R['digest'](expected), outputs=outputs)
    manifest = R['validate'](expected, candidate)
    # Re-read actual artifacts as well as statuses; a moved job, retry, newly
    # hidden failure or changed archive must not be accepted as the first read.
    for identifier in sorted(indexed):
        again_output, again = acquire(expected, identifier, producers[identifier], executor_before['receipt_digest'], api)
        require(again == observations[identifier]
                and again_output == next(row for row in outputs if row['member']['id'] == identifier),
                'assembly resources changed during acquisition')
    require(executor() == executor_before, 'assembly executor changed during acquisition')
    return dict(schema=1, kind='nest_release_assembled_candidate', manifest=manifest,
                executor=executor_before, members=observations,
                resource_verification='successful_native_jobs_and_exact_artifact_bytes_only',
                image_compatibility_verification='not_performed', promotion_authorized=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assembly', required=True)
    parser.add_argument('--output-dir', help='existing canonical durable artifact directory')
    args = parser.parse_args()
    try:
        result = assemble(R['load'](args.assembly), D['GitLab']())
        manifest = result['manifest']
        manifest_path = R['retain'](args.output_dir, R['canonical'](manifest)) if args.output_dir else None
        path = R['retain'](args.output_dir, R['canonical'](result)) if args.output_dir else None
        print(json.dumps(dict(schema=1, members=len(result['members']), path=path, manifest_path=manifest_path,
                              manifest_digest=R['digest'](manifest), readback_verified=path is not None,
                              promotion_authorized=False), sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, StopIteration, RecursionError, subprocess.SubprocessError):
        print('Native release assembly refused or failed; no accepted manifest published', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
