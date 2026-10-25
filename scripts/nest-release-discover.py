#!/usr/bin/env python3
"""Discover exact native bridge/member jobs, then bind their actual outputs.

Read-only GitLab acquisition; never starts, retries, promotes or operates hosts.
"""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BIND = runpy.run_path(str(ROOT / 'scripts/nest-release-bind.py'))
R = BIND['RELEASE']
require = R['require']
fields = R['fields']


class GitLab(BIND['GitLab']):
    """Add only bounded exact-pipeline GETs to the existing artifact reader."""

    def get(self, path):
        pattern = (r'projects/nest(?:%2F[a-z0-9._-]+)+/pipelines/[1-9][0-9]{0,19}'
                   r'(?:/(?:jobs|bridges)\?per_page=100&page=[1-9][0-9]?)?')
        if re.fullmatch(pattern, path) is None:
            return super().get(path)
        operation = 'job' if '/jobs?' in path else 'bridge' if '/bridges?' in path else 'pipeline'
        return self._read(path, operation)


def listing(api, project, identifier, kind):
    require(kind in ('jobs', 'bridges'), 'unsupported pipeline inventory')
    BIND['positive'](identifier)
    prefix = BIND['prefix'](project) + '/pipelines/' + str(identifier) + '/' + kind
    rows = []
    seen = set()
    # The default GitLab jobs/bridges listing excludes superseded retries.
    # Exhaust pagination instead of silently treating the first page as closure.
    for page in range(1, 21):
        batch: Any = BIND['decode'](api.get(prefix + '?per_page=100&page=' + str(page)))
        require(type(batch) is list and len(batch) <= 100, 'invalid pipeline inventory')
        for row in batch:
            BIND['positive'](row['id'])
            require(row['id'] not in seen and row.get('retried') is not True, 'duplicate or retried resource')
            seen.add(row['id'])
        rows.extend(batch)
        if len(batch) < 100:
            return rows
    raise ValueError('pipeline inventory exceeds bound')


def pipeline(api, project, identifier, sha, root=False):
    BIND['positive'](identifier)
    R['match'](sha, R['SHA'], 'pipeline source')
    base = BIND['prefix'](project)
    repository = BIND['decode'](api.get(base))
    require(repository['path_with_namespace'] == project, 'wrong pipeline project')
    BIND['positive'](repository['id'])
    row = BIND['decode'](api.get(base + '/pipelines/' + str(identifier)))
    require(type(row['id']) is int and row['id'] == identifier
            and type(row['project_id']) is int and row['project_id'] == repository['id']
            and row['sha'] == sha, 'wrong pipeline identity')
    allowed = ('running', 'success') if root else ('success',)
    require(row['status'] in allowed, 'pipeline has not succeeded')
    require(root or row['source'] == 'pipeline', 'member pipeline is not a native downstream')
    return {key: row[key] for key in ('id', 'project_id', 'sha', 'ref', 'source', 'status')}


def selected(rows, name):
    R['text'](name, 'resource name')
    matches = [row for row in rows if row['name'] == name]
    require(len(matches) == 1, 'missing or ambiguous pipeline resource')
    row = matches[0]
    require(row['status'] == 'success' and row.get('allow_failure') is False
            and row.get('erased_at') is None, 'resource is unavailable or not required/successful')
    return row


def edge(api, config_source, producer_source, selector):
    """Resolve one direct native edge; refuse child trigger loops and failure hiding."""
    fields(selector, 'project member root_pipeline bridge job_name input_pipeline', 'discovery selector')
    require(selector['project'] in BIND['PROJECTS'] - {'nest/config'}, 'unsupported member project')
    R['match'](selector['member'], R['TOKEN'], 'member ID')
    root = pipeline(api, 'nest/config', selector['root_pipeline'], config_source, root=True)
    bridge = selected(listing(api, 'nest/config', root['id'], 'bridges'), selector['bridge'])
    require(bridge['pipeline']['id'] == root['id'] and bridge['pipeline']['sha'] == config_source
            and bridge['pipeline']['project_id'] == root['project_id'], 'bridge parent mismatch')
    downstream = bridge['downstream_pipeline']
    require(type(downstream) is dict, 'bridge has no downstream pipeline')
    child = pipeline(api, selector['project'], downstream['id'], producer_source)
    require(all(downstream[key] == child[key] for key in ('id', 'project_id', 'sha', 'ref', 'status')),
            'bridge downstream identity mismatch')
    require(not listing(api, selector['project'], child['id'], 'bridges'), 'unexpected outgoing member bridge')
    jobs = listing(api, selector['project'], child['id'], 'jobs')
    require(jobs and all(row['status'] == 'success' and row.get('allow_failure') is False for row in jobs),
            'member pipeline contains incomplete or tolerated jobs')
    member = selected(jobs, selector['job_name'])
    # The binder independently verifies these jobs, archives, sources and bytes.
    names = BIND['input_job_names'](selector['member'])
    candidates = [row for row in listing(api, 'nest/config', selector['input_pipeline'], 'jobs')
                  if row['name'] in names]
    require(len(candidates) == 1, 'missing or ambiguous member input job')
    inputs = selected(candidates, candidates[0]['name'])
    input_job = BIND['job'](api, 'nest/config', selector['input_pipeline'], inputs['id'], config_source)
    require(input_job['name'] == inputs['name'], 'input job name changed during acquisition')
    member_job = BIND['job'](api, selector['project'], child['id'], member['id'], producer_source)
    raw_input = api.get(BIND['prefix']('nest/config') + '/jobs/' + str(inputs['id']) +
                        '/artifacts/release-inputs/expectations.json')
    raw_result = BIND['result_bytes'](api, selector['project'], member['id'], selector['member'])
    resolved = dict(project=selector['project'], member=selector['member'], pipeline=child['id'], job=member['id'],
                    input_pipeline=selector['input_pipeline'], input_job=inputs['id'],
                    input_sha256=hashlib.sha256(raw_input).hexdigest(),
                    result_sha256=hashlib.sha256(raw_result).hexdigest())
    observation = dict(root=root, bridge=dict(id=bridge['id'], name=bridge['name'], downstream=child),
                       member_job=member_job, input_job=input_job,
                       jobs=[dict(id=row['id'], name=row['name']) for row in jobs])
    return resolved, observation


def discover(request: Any, api):
    fields(request, 'schema kind expectations executor_job producers bindings', 'discovery request')
    require(type(request['schema']) is int and request['schema'] == 1
            and request['kind'] == 'nest_release_base_discovery', 'unsupported discovery request')
    R['expectations'](request['expectations'])
    producers = request['producers']
    require(type(producers) is dict and 0 < len(producers) <= 32, 'invalid discovery inventory')
    binding = copy.deepcopy(request)
    binding['kind'] = 'nest_release_base_binding'
    observations = {}
    sources = request['expectations']['sources']
    for name, selector in producers.items():
        R['match'](name, R['TOKEN'], 'predecessor name')
        binding['producers'][name], observations[name] = edge(
            api, sources['nest/config'], sources[selector['project']], selector)
    expected, provenance = BIND['bind'](binding, api)
    # Reacquire after binding: detect a retried bridge, moved child, erased job,
    # changed result/input bytes or newly hidden failed job before acceptance.
    for name, selector in producers.items():
        again, observed = edge(api, sources['nest/config'], sources[selector['project']], selector)
        require(again == binding['producers'][name] and observed == observations[name],
                'native pipeline resources changed during acquisition')
    return dict(schema=1, kind='nest_release_discovered_inputs', expectations=expected,
                binding_request=binding, binding=provenance, edges=observations,
                publication='not_performed', promotion_authorized=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--discovery', required=True)
    parser.add_argument('--output-dir', help='existing canonical artifact directory')
    args = parser.parse_args()
    try:
        result = discover(R['load'](args.discovery), GitLab())
        path = R['retain'](args.output_dir, R['canonical'](result)) if args.output_dir else None
        expected_path = R['retain'](args.output_dir, R['canonical'](result['expectations'])) if args.output_dir else None
        print(json.dumps(dict(schema=1, edges=len(result['edges']), path=path, expectations_path=expected_path,
                              expectations_digest=R['digest'](result['expectations']), readback_verified=path is not None,
                              publication='not_performed', promotion_authorized=False), sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, KeyError, RecursionError, subprocess.SubprocessError):
        print('Native release discovery refused or failed; no accepted inputs published', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
