#!/usr/bin/env python3
"""Retain native read-only capacity admission; never authorize or execute reset."""

import hashlib
import json
import re
import sys
from typing import Any

sys.dont_write_bytecode = True
from retain_update_report import identity_tree, publish_document, require, token
from update_wave_plan import unique_object

DIGEST = r'[0-9a-f]{64}'
DATASET = r'[A-Za-z0-9_.:/-]{1,255}'


def project(raw, hostname, release, inputs):
    require(type(raw) is str and len(raw.encode('utf-8')) <= 262144, 'Invalid preflight size')
    row: Any = json.loads(raw, object_pairs_hook=unique_object)
    require(type(row) is dict and type(row.get('schema')) is int and row['schema'] == 1
            and row.get('kind') == 'reset_plan' and row.get('read_only') is True
            and row.get('observation_success') is True, 'Invalid native planner outcome')
    require(row.get('steps') == ['backup', 'mount', 'sync', 'kernel', 'unmount', 'activate']
            and row.get('replaces_alternate') is True, 'Unexpected native plan scope')
    preflight = row['transaction_preflight']
    require(type(preflight) is dict and preflight.get('read_only') is True
            and preflight.get('capacity_admission') == 'admitted', 'Missing transaction admission')
    capacity = preflight['capacity']
    require(type(capacity) is dict and row['capacity'] == capacity and capacity.get('admission') == 'admitted'
            and capacity.get('admitted') is True, 'Capacity not admitted')
    observed = capacity['observations']
    require(type(observed) is dict and type(observed.get('accounting_contract')) is int and observed['accounting_contract'] == 2
            and observed.get('stage') == 'backup', 'Unsupported capacity accounting')
    observation_digest = token(capacity['observations_sha256'], DIGEST)
    # Native Ruby JSON.generate preserves hash insertion order, as does this
    # bounded JSON decoder. This checks transport consistency, not fresh storage.
    observed_bytes = json.dumps(observed, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    require(hashlib.sha256(observed_bytes).hexdigest() == observation_digest, 'Changed accounting bytes')
    policy_digest = token(capacity['policy_sha256'], DIGEST)
    host = preflight['host']
    generation = inputs['generation_policy']
    require(host['hostname'] == token(hostname, r'[a-z0-9][a-z0-9-]{0,62}') == generation['hostname'], 'Wrong host')
    require(token(release, 'sha256:' + DIGEST) == generation['release'], 'Wrong release')
    pool_guid = token(host['pool_guid'], r'[1-9][0-9]*')
    require(pool_guid == generation['pool_guid'], 'Wrong pool')
    current = token(host['current'], DATASET)
    match = re.fullmatch(r'([^/]+(?:/[^/]+)*/ROOT)/(A|B)', current)
    if match is None:
        raise ValueError('Invalid current A/B root')
    target = match[1] + ('/B' if match[2] == 'A' else '/A')
    require(host['target'] == target and row['current'] == current and row['target'] == target
            and row['destination'] == '/mnt/' + target.rsplit('/', 1)[1], 'Inconsistent native target')
    boot = token(host['boot_id'], r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}')
    source = preflight['source']
    require(source['path'] == inputs['root_generation'] == generation['destination']
            and source['release'] == release and source['guid'] == generation['destination_guid'], 'Wrong generation')
    source_result = {key: token(source[key], DATASET if key == 'dataset' else r'[1-9][0-9]*')
                     for key in ('dataset', 'guid', 'creation_txg')}
    pool = current.split('/')[0]
    require(source_result['dataset'].split('/')[0] == pool
            and 'ROOT' not in source_result['dataset'].split('/'), 'Nonlocal generation')
    shared: Any = preflight['shared_state']
    shared_result = {'dataset': token(shared['dataset'], DATASET), 'guid': token(shared['guid'], r'[1-9][0-9]*')}
    require(shared['pool_guid'] == pool_guid and shared['dataset'].split('/')[0] == pool
            and 'ROOT' not in shared['dataset'].split('/'), 'Wrong shared state')
    trees = {}
    for name, root in (('current_tree', current), ('alternate_tree', target)):
        rows = host[name]
        trees[name] = identity_tree(rows) if rows else []
        require(name != 'current_tree' or trees[name], 'Missing current tree')
        require(not rows or any(item['dataset'] == root and item['mountpoint'] == '/' for item in rows), 'Missing tree root')
        require(all(item['dataset'] == root or item['dataset'].startswith(root + '/') for item in rows), 'Unrelated tree')
    cli_digest = token(row['source_identity']['source_sha256'], DIGEST)
    require(preflight['policy']['cli_sha256'] == cli_digest, 'Inconsistent CLI identity')
    return {'schema': 1, 'kind': 'nest_update_capacity_preflight', 'hostname': hostname, 'release': release,
            'transaction': token(inputs['transaction'], r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}'),
            'boot_id': boot, 'pool_guid': pool_guid, 'current': current, 'target': target,
            'source': source_result, 'shared_state': shared_result, **trees,
            'cli_sha256': cli_digest, 'filter_sha256': token(preflight['policy']['filter_sha256'], DIGEST),
            'capacity_policy_sha256': policy_digest, 'accounting_contract': 2,
            'observations_sha256': observation_digest, 'capacity_admitted': True,
            'read_only': True, 'reset_authorized': False,
            'transport_sha256': hashlib.sha256(raw.encode('utf-8')).hexdigest()}


def main():
    try:
        raw = sys.stdin.buffer.read(524289)
        require(len(raw) <= 524288, 'Input too large')
        params = json.loads(raw, object_pairs_hook=unique_object)
        report = project(params['report'], params['hostname'], params['release'], params['inputs'])
        if 'binding' in params:
            binding = params['binding']
            require(type(binding) is dict and set(binding) == {'transaction', 'policy_sha256', 'stage'},
                    'Invalid preparation binding')
            require(binding['transaction'] == report['transaction']
                    and binding['stage'] in ('preflight', 'initiation'), 'Wrong preparation context')
            token(binding['policy_sha256'], DIGEST)
            # Caller-supplied association, not a native recorded transaction,
            # observation timestamp, capacity lease or permission to reset.
            report['preparation'] = binding
        receipt = publish_document(report, params['output_dir'], report['hostname'] + '-' + report['transaction'] + '-capacity')
        if 'binding' in params:
            receipt['preparation'] = report['preparation']
        print(json.dumps(dict(receipt, capacity_admitted=True, reset_authorized=False)))
        return 0
    except (KeyError, TypeError, ValueError, OSError, UnicodeError, RecursionError):
        print(json.dumps({'_error': {'kind': 'nest/update-capacity-preflight',
                                   'msg': 'Native capacity preflight validation or retention failed; no reset authorized'}}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
