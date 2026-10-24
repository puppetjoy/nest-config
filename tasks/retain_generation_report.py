#!/usr/bin/env python3
"""Retain a bounded generation result on the supervisor; never operate a host."""

import hashlib
import json
from pathlib import Path
import re
import runpy
import sys

sys.dont_write_bytecode = True
R = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/nest-release-manifest.py'))
require = R['require']
DATASET = r'[A-Za-z0-9][A-Za-z0-9_.:-]*(?:/[A-Za-z0-9_.:-]+)*'
GUID = r'[1-9][0-9]{0,19}'
HEX = r'[0-9a-f]{64}'


def directory(value):
    require(type(value) is str, 'Invalid output directory')
    path = Path(value)
    require(path.is_absolute() and path.resolve() == path and path.is_dir(), 'Output directory must exist and be canonical')
    return path


def project(raw, policy, check, verify_only):
    """Only known public identity/outcome fields cross the retention boundary."""
    require(type(raw) is str and len(raw.encode('utf-8')) <= 32768, 'Invalid report size')
    row = json.loads(raw, object_pairs_hook=R['unique_object'], parse_int=R['json_integer'],
                     parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    require(type(policy) is dict and type(check) is bool and type(verify_only) is bool
            and (check or not verify_only), 'Invalid mode')
    fields = 'schema kind policy policy_sha256 read_only sealed reset_authorized '
    fields += 'generation transfer_receipt_sha256 reset_capacity_admitted' if verify_only else 'source capacity'
    R['fields'](row, fields, 'generation report')
    require(type(row['schema']) is int and row['schema'] == 1, 'Invalid schema')
    require(row['kind'] == ('nest_generation_verification_report' if verify_only else 'nest_generation_transfer_report'), 'Invalid kind')
    require(R['canonical'](row['policy']) == R['canonical'](policy)
            and row['policy_sha256'] == hashlib.sha256(R['canonical'](policy)).hexdigest(), 'Policy mismatch')
    require(row['read_only'] is check and row['sealed'] is (verify_only or not check)
            and row['reset_authorized'] is False, 'Contradictory outcome')
    R['match'](policy['hostname'], r'[a-z0-9][a-z0-9-]{0,62}', 'hostname')
    R['match'](policy['release'], 'sha256:' + HEX, 'release')
    for key in ('pool_guid', 'destination_guid'):
        R['match'](policy[key], GUID, key)
    observed = row['generation' if verify_only else 'source']
    R['fields'](observed, 'dataset creation_txg state_dataset current boot_id state_guid' + ('' if verify_only else ' source_mount'), 'observation')
    for key in ('dataset', 'state_dataset', 'current'):
        R['match'](observed[key], DATASET, key)
    for key in ('creation_txg', 'state_guid'):
        R['match'](observed[key], GUID, key)
    R['match'](observed['boot_id'], r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', 'boot')
    pool = observed['current'].split('/')[0]
    require(re.fullmatch(DATASET + r'/ROOT/[AB]', observed['current']) is not None, 'Invalid current root')
    for key in ('dataset', 'state_dataset'):
        require(observed[key].split('/')[0] == pool and 'ROOT' not in observed[key].split('/'), 'Invalid pool placement')
    first, second = observed['dataset'], observed['state_dataset']
    require(first != second and not first.startswith(second + '/') and not second.startswith(first + '/'), 'Overlapping state')
    # Do not retain arbitrary mount options, server addresses or command output.
    observation = {key: observed[key] for key in ('dataset', 'creation_txg', 'state_dataset', 'current', 'boot_id', 'state_guid')}
    result = dict(schema=1, kind='nest_retained_generation_report', hostname=policy['hostname'], release=policy['release'],
                  pool_guid=policy['pool_guid'], destination_guid=policy['destination_guid'], policy_sha256=row['policy_sha256'],
                  native_kind=row['kind'], read_only=check, sealed=row['sealed'], observation=observation,
                  reset_authorized=False, reset_capacity_admitted=False, resource_verification='not_performed')
    if verify_only:
        require(row['reset_capacity_admitted'] is False, 'Unexpected reset capacity assertion')
        R['match'](row['transfer_receipt_sha256'], HEX, 'transfer receipt digest')
        result['transfer_receipt_sha256'] = row['transfer_receipt_sha256']
    else:
        capacity = row['capacity']
        R['fields'](capacity, 'apparent_bytes available_bytes physical_free_bytes', 'capacity')
        require(all(type(value) is int and 0 <= value <= 2 ** 64 - 1 for value in capacity.values()), 'Invalid byte counts')
        result['transfer_capacity_observation'] = capacity
    return result


def binding(value):
    """Caller context is an association, not native transaction provenance."""
    R['fields'](value, 'transaction policy_sha256 stage', 'preparation binding')
    R['match'](value['transaction'], r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', 'transaction')
    R['match'](value['policy_sha256'], HEX, 'wave policy digest')
    require(value['stage'] in ('preflight', 'initiation'), 'Invalid preparation stage')
    return dict(value)


def main():
    try:
        raw = sys.stdin.buffer.read(65537)
        require(len(raw) <= 65536, 'Oversized task input')
        params = json.loads(raw, object_pairs_hook=R['unique_object'], parse_int=R['json_integer'],
                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        require(type(params) is dict and all(key in {'output_dir', 'report', 'policy', 'check', 'verify_only', 'binding'}
                                            or isinstance(key, str) and key.startswith('_') for key in params), 'Invalid parameters')
        bound = binding(params['binding']) if 'binding' in params else None
        target = directory(params['output_dir'])
        if 'report' not in params:
            require(not {'policy', 'check', 'verify_only'} & params.keys(), 'Incomplete retention input')
            result = dict(schema=1, kind='nest_generation_retention_preflight', output_dir=str(target), read_only=True)
        else:
            report = project(params['report'], params['policy'], params['check'], params['verify_only'])
            if bound is not None:
                require(params['verify_only'] is True, 'Preparation binding requires sealed verification')
                report['preparation'] = bound
            payload = R['canonical'](report)
            path = R['retain'](target, payload)
            result = dict(schema=1, kind='nest_generation_retention_receipt', path=path, sha256=hashlib.sha256(payload).hexdigest(),
                          bytes=len(payload), hostname=report['hostname'], release=report['release'],
                          readback_verified=True, sealed=report['sealed'], reset_authorized=False)
        if bound is not None:
            result['preparation'] = bound
        print(R['canonical'](result).decode('ascii'), end='')
        return 0
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        print(json.dumps({'_error': {'kind': 'nest/generation-retention',
                                    'msg': 'Generation report retention refused; do not replay transfer'}}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
