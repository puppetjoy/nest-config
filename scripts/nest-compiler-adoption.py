#!/usr/bin/env python3
"""Reconcile a legacy compiler's scoped client caches; propose only, never deploy."""
import argparse
from pathlib import Path
import re
import runpy
import subprocess
import sys
import time

CANDIDATE = runpy.run_path(str(Path(__file__).with_name('nest-compiler-candidate.py')))
require, load = CANDIDATE['require'], CANDIDATE['load']
NAME = r'[A-Za-z0-9][A-Za-z0-9_.-]{0,252}'
UUID = r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}'


def matches(value, pattern):
    return type(value) is str and re.fullmatch(pattern, value) is not None


def propose(candidate_path, scope_path, observations_path, releases_path, output, now=None):
    # Observations are evidence, not trusted attestations. Invocation and scope
    # provenance must be retained by the existing inventory-backed caller.
    value = CANDIDATE['checked_candidate'](load(candidate_path))
    scope, observations, known = load(scope_path), load(observations_path), load(releases_path)
    require(type(scope) is dict and set(scope) == {'schema', 'clients'})
    require(type(scope['schema']) is int and scope['schema'] == 1)
    require(type(scope['clients']) is list and 0 < len(scope['clients']) <= 128)
    for client in scope['clients']:
        require(type(client) is dict and set(client) == {'hostname', 'certname', 'server'})
        require(all(matches(item, NAME) for item in client.values()))
    clients = {client['certname']: client for client in scope['clients']}
    require(len(clients) == len(scope['clients']))
    require(len({client['hostname'] for client in scope['clients']}) == len(clients))
    require(type(known) is list and len(known) <= 128)
    releases = [CANDIDATE['release'](item) for item in known]
    identities = {item['expected']['code_id']: item for item in releases}
    require(len(identities) == len(releases))
    current = value['current']
    if current['expected']['code_id'] in identities:
        require(identities[current['expected']['code_id']]['expected'] == current['expected'])
    identities[current['expected']['code_id']] = current
    require(type(observations) is list and len(observations) == len(clients))
    now = int(time.time()) if now is None else now
    seen, legacy = set(), []
    for row in observations:
        require(type(row) is dict and set(row) == {'schema', 'kind', 'hostname', 'certname', 'server', 'boot_id',
                                                   'observed_at', 'environment', 'cache', 'read_only',
                                                   'catalog_applied', 'acceptance_recorded'})
        require(type(row['schema']) is int and row['schema'] == 1 and row['kind'] == 'nest_compiler_catalog_cache')
        require(type(row['certname']) is str and row['certname'] in clients and row['certname'] not in seen)
        require({key: row[key] for key in ('hostname', 'certname', 'server')} == clients[row['certname']])
        seen.add(row['certname'])
        require(matches(row['boot_id'], UUID))
        require(type(row['observed_at']) is int and 0 <= now - row['observed_at'] <= 900)
        require(row['environment'] == 'main' and row['read_only'] is True
                and row['catalog_applied'] is False and row['acceptance_recorded'] is False)
        cache = row['cache']
        require(type(cache) is dict and set(cache) == {'configuration_version', 'code_id', 'catalog_uuid', 'cache_sha256'})
        require(matches(cache['configuration_version'], r'[0-9a-f]{40}'))
        require(matches(cache['catalog_uuid'], UUID) and matches(cache['cache_sha256'], r'[0-9a-f]{64}'))
        if cache['code_id'] is None:
            legacy.append(row['certname'])
        else:
            require(type(cache['code_id']) is str and cache['code_id'] in identities)
            require(identities[cache['code_id']]['expected']['source'] == cache['configuration_version'])
    # Keep every supplied release, including identities absent in today's
    # bounded scope. Nothing here grants global retirement/garbage collection.
    retained = [item for item in releases if item['expected']['code_id'] != current['expected']['code_id']]
    CANDIDATE['verify_index'](current['image'], value['members'])
    result = {'schema': 1, 'kind': 'nest_openvox_compiler_adoption_proposal',
              'selection': {'schema': 1, 'current': current, 'retained': retained},
              'clients': sorted(seen), 'legacy_null_code_id_clients': sorted(legacy),
              'scope_cache_reconciled': True, 'global_cache_coverage': False,
              'legacy_historical_content_bound': False, 'deployment_authorized': False,
              'retention_complete': False, 'compiler_attestation': False}
    CANDIDATE['write'](output, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('candidate', 'scope', 'observations', 'known_releases', 'output'):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    try:
        propose(args.candidate, args.scope, args.observations, args.known_releases, args.output)
        return 0
    except (OSError, ValueError, KeyError, TypeError, RecursionError, subprocess.SubprocessError):
        print('Compiler adoption unavailable; no deployment authorized', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
