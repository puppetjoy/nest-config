#!/usr/bin/env python3
"""Acquire a complete multi-architecture release without relabelling executors.

Authenticated GETs only; no build, trigger, alias promotion or host operation.
"""

import argparse
import copy
import json
from pathlib import Path
import runpy
import subprocess
import sys
from typing import Any

A = runpy.run_path(str(Path(__file__).with_name('nest-release-assemble.py')))
R = A['R']
require = R['require']
ARCHITECTURES = {'haswell', 'cortex-a53', 'sifive-u74'}


def selection(request: Any):
    """Validate the entire requested closure before any external acquisition."""
    R['fields'](request, 'schema kind release sources consumers assemblies', 'envelope request')
    require(type(request['schema']) is int and request['schema'] == 1
            and request['kind'] == 'nest_release_envelope_request', 'unsupported envelope request')
    assemblies = request['assemblies']
    require(type(assemblies) is dict and 0 < len(assemblies) <= len(ARCHITECTURES)
            and set(assemblies) <= ARCHITECTURES, 'invalid architecture inventory')
    members, images = [], set()
    for architecture, assembly in assemblies.items():
        expected, _, selected_architecture = A['selection'](assembly)
        require(expected['release'] == request['release'] and expected['sources'] == request['sources'],
                'architecture has different release or source closure')
        require(selected_architecture == architecture, 'member in wrong architecture')
        require(expected['executor']['image'] not in images, 'executor image reused across architectures')
        images.add(expected['executor']['image'])
        members.extend(expected['members'])
    require(len(members) <= 128, 'envelope member inventory exceeds bound')
    # Reuse the existing complete member/consumer schema for global uniqueness,
    # identity and decision coverage only. No output is validated under this
    # temporary executor: each manifest retains its own independently read one.
    whole = copy.deepcopy(next(iter(assemblies.values()))['expectations'])
    whole['members'], whole['consumers'] = members, request['consumers']
    R['expectations'](whole)
    global_consumers = {c['project']: c for c in request['consumers']}
    for assembly in assemblies.values():
        local_consumers = {c['project']: c for c in assembly['expectations']['consumers']}
        require(set(local_consumers) == set(global_consumers), 'different consumer inventory across architectures')
        for project, local in local_consumers.items():
            global_row = global_consumers[project]
            require(set(local['members']) <= set(global_row['members']), 'local consumer outside selected program')
            require(local['decision'] == (global_row['decision'] if local['members'] else
                                         ('defer' if global_row['members'] else global_row['decision'])),
                    'architecture decision contradicts global consumer policy')
    return len(members)


def envelope(request: Any, api):
    count = selection(request)
    assemblies = request['assemblies']
    acquired = {}
    resources = set()
    root_guids = set()
    for architecture in sorted(assemblies):
        result = A['assemble'](assemblies[architecture], api)
        for output in result['manifest']['candidate']['outputs']:
            producer = output['producer']
            identity = (producer['project'], producer['pipeline'], producer['job'])
            require(identity not in resources, 'producer reused across architectures')
            resources.add(identity)
            if output['member']['stage'] == 'stage3':
                guid = output['artifacts']['root']['dataset_guid']
                require(guid not in root_guids, 'host root GUID reused across architectures')
                root_guids.add(guid)
        acquired[architecture] = result
    # A previous architecture can change while a later one is acquired. Re-run
    # the existing bounded acquisition, including exact artifact/executor bytes,
    # across the entire program before accepting the envelope.
    for architecture in sorted(assemblies):
        require(A['assemble'](assemblies[architecture], api) == acquired[architecture],
                'architecture resources changed during envelope acquisition')
    return dict(schema=1, kind='nest_release_envelope', release=request['release'],
                sources=copy.deepcopy(request['sources']), consumers=copy.deepcopy(request['consumers']),
                request_digest=R['digest'](request), architectures=acquired, members=count,
                resource_verification='successful_native_jobs_and_exact_artifact_bytes_only',
                image_compatibility_verification='not_performed', promotion_authorized=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--envelope', required=True)
    parser.add_argument('--output-dir', help='existing canonical durable artifact directory')
    args = parser.parse_args()
    try:
        result = envelope(R['load'](args.envelope), A['D']['GitLab']())
        payload = R['canonical'](result)
        require(len(payload) <= R['LIMIT'], 'envelope exceeds readable artifact bound')
        path = R['retain'](args.output_dir, payload) if args.output_dir else None
        print(json.dumps(dict(schema=1, architectures=len(result['architectures']), members=result['members'],
                              envelope_digest=R['digest'](result), path=path, readback_verified=path is not None,
                              promotion_authorized=False), sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, StopIteration, RecursionError, subprocess.SubprocessError):
        print('Native release envelope refused or failed; no accepted envelope published', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
