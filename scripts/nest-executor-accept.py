#!/usr/bin/env python3
"""Accept an exact completed bootstrap successor through read-only native evidence.

Does not build, trigger, pull images, promote aliases or operate hosts.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess
import sys

M = runpy.run_path(str(Path(__file__).with_name('nest-executor-bootstrap.py')))
B, D, R = M['B'], M['D'], M['R']
require = R['require']


class GitLab(M['GitLab']):
    """Only the config build's two bootstrap artifacts extend ordinary reads."""

    def get(self, path):
        if re.fullmatch(r'projects/nest%2Fconfig/jobs/[1-9][0-9]{0,19}/artifacts/'
                        r'executor-bootstrap/(?:receipt\.json|bolt\.ref)', path):
            return self._read(path, 'artifact')
        return super().get(path)


def selection(request):
    R['fields'](request, 'schema kind bootstrap successor', 'successor acceptance')
    require(type(request['schema']) is int and request['schema'] == 1
            and request['kind'] == 'nest_executor_successor_request', 'wrong successor request')
    bootstrap, successor = request['bootstrap'], request['successor']
    names = 'schema kind successor_source successor_cpu producer'
    R['fields'](bootstrap, names + (' native' if type(bootstrap) is dict and 'native' in bootstrap else ''), 'bootstrap request')
    source, cpu = bootstrap['successor_source'], bootstrap['successor_cpu']
    M['selection'](bootstrap, source, cpu)
    R['fields'](successor, 'pipeline job image executor_sha256 bootstrap_sha256', 'successor selector')
    for key in ('pipeline', 'job'):
        B['positive'](successor[key])
    for key in ('executor_sha256', 'bootstrap_sha256'):
        R['match'](successor[key], r'[0-9a-f]{64}', 'successor artifact digest')
    R['match'](successor['image'], r'registry[.]gitlab[.]joyfullee[.]me/nest/config/'
               r'[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}', 'successor image')
    return bootstrap, successor, source, cpu


def observe(request, api):
    bootstrap, successor, source, cpu = selection(request)
    pipeline = D['pipeline'](api, 'nest/config', successor['pipeline'], source, root=True)
    require(pipeline['status'] == 'success' and pipeline['source'] in ('api', 'web', 'pipeline', 'trigger', 'parent_pipeline'),
            'successor pipeline has not completed or has unsupported source')
    require(not D['listing'](api, 'nest/config', pipeline['id'], 'bridges'), 'unexpected successor fan-out')
    jobs = D['listing'](api, 'nest/config', pipeline['id'], 'jobs')
    require(jobs and all(row['status'] == 'success' and row.get('allow_failure') is False
                        and row.get('erased_at') is None for row in jobs), 'incomplete successor pipeline')
    name = 'Build ' + cpu
    selected = D['selected'](jobs, name)
    require(selected['id'] == successor['job']
            and [row['name'] for row in jobs if row['name'].startswith('Build ')] == [name]
            and not any(row['name'].startswith('Deploy ') for row in jobs), 'not one isolated bootstrap successor')
    job = B['job'](api, 'nest/config', pipeline['id'], successor['job'], source)
    require(job['name'] == name, 'successor build job changed')
    prefix = B['prefix']('nest/config') + '/jobs/' + str(successor['job']) + '/artifacts/'
    executor_raw = api.get(prefix + 'executor-receipts/' + cpu + '.json')
    bootstrap_raw = api.get(prefix + 'executor-bootstrap/receipt.json')
    reference_raw = api.get(prefix + 'executor-bootstrap/bolt.ref')
    require(hashlib.sha256(executor_raw).hexdigest() == successor['executor_sha256']
            and hashlib.sha256(bootstrap_raw).hexdigest() == successor['bootstrap_sha256'], 'successor bytes changed')
    executor, retained = B['decode'](executor_raw), B['decode'](bootstrap_raw)
    B['check_executor'](executor, dict(executor=dict(source=source, image=successor['image'])), cpu)
    require(executor['pipeline'] == pipeline['id'] and executor['job'] == successor['job'],
            'successor receipt identifies another job')
    # Acquire the OLD boundary independently rather than trusting nested copies
    # retained by the new build. Never require the successor to produce itself.
    acquired = M['acquire'](bootstrap, source, cpu, api)
    acquired['successor'].update(pipeline=pipeline['id'], job=successor['job'])
    if pipeline['source'] == 'parent_pipeline':
        require('route' in retained, 'missing bootstrap route evidence')
        require(M['route_input'](retained['route'], source, pipeline['id'], api, 'success') == bootstrap,
                'successor bootstrap route mismatch')
        acquired['route'] = retained['route']
    require(retained == acquired, 'successor retained another bootstrap boundary')
    require(executor['inputs']['base_image'] == acquired['successor']['base_image']
            and reference_raw == (acquired['successor']['base_image'] + '\n').encode('ascii'),
            'successor installed base differs from acquired OpenBolt')
    return dict(pipeline=pipeline, job=job,
                jobs=[dict(id=row['id'], name=row['name']) for row in jobs],
                executor=executor, bootstrap=retained)


def accept(request, api):
    selection(request)
    first = observe(request, api)
    # Full reacquisition includes both old and new jobs, receipts and pipeline
    # inventories. Changed retries/erasures/bytes refuse, never poll or rebuild.
    require(observe(request, api) == first, 'bootstrap successor changed during acceptance')
    result = dict(schema=1, kind='nest_executor_successor_acceptance', request=request,
                  request_digest=R['digest'](request), accepted=first,
                  resource_verification='successful_native_jobs_and_exact_artifact_bytes_only',
                  image_compatibility_verification='not_performed',
                  local_image_execution='not_performed', promotion_authorized=False)
    require(len(R['canonical'](result)) <= R['LIMIT'], 'successor evidence exceeds size limit')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--successor', required=True, help='exact successor acceptance request')
    parser.add_argument('--output-dir', help='existing canonical artifact directory')
    args = parser.parse_args()
    try:
        result = accept(R['load'](args.successor), GitLab())
        raw = R['canonical'](result)
        path = R['retain'](args.output_dir, raw) if args.output_dir else None
        print(json.dumps(dict(schema=1, kind=result['kind'], digest=R['digest'](result), path=path,
                              readback_verified=path is not None, promotion_authorized=False), sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, RecursionError, StopIteration, subprocess.SubprocessError):
        print('Bootstrap successor acceptance refused or failed', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
