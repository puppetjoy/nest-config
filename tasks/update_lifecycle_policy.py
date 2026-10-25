#!/usr/bin/env python3
"""Schema-5 policy validation shared by the existing wave and lifecycle tasks."""

from retain_update_report import require, token
from update_wave_plan import fields, preparation_window
import update_network_health


def lifecycle_policy(value, hosts):
    fields(value, 'controller window impact rollback retention acceptance')
    token(value['controller'], r'[a-z0-9][a-z0-9_.-]{0,127}')
    require(value['controller'] not in hosts, 'controller must survive every target outage')
    preparation_window(value['window'])
    require(value['rollback'] == 'keep_previous_be_manual_recovery' and
            value['retention'] == 'keep_backups_and_origins_until_release_retired', 'unsupported retention')
    for key in ('impact', 'acceptance'):
        require(type(value[key]) is dict and set(value[key]) == set(hosts), 'incomplete lifecycle scope')
    for name in hosts:
        impact = value['impact'][name]
        require(type(impact) is list and 0 < len(impact) <= 16 and len(set(impact)) == len(impact), 'invalid impact')
        for item in impact:
            token(item, r'[a-z0-9][a-z0-9_.-]{0,127}')
        entry = value['acceptance'][name]
        fields(entry, 'certname endpoints canaries historical_failures')
        token(entry['certname'], r'[A-Za-z0-9][A-Za-z0-9_.-]{0,252}')
        require(type(entry['endpoints']) is list and entry['endpoints'], 'network acceptance is required')
        update_network_health.policy(entry['endpoints'])
        require(type(entry['canaries']) is list and 0 < len(entry['canaries']) <= 16, 'targeted canary required')
        seen = set()
        for canary in entry['canaries']:
            fields(canary, 'name command')
            token(canary['name'], r'[a-z][a-z0-9_-]{0,63}')
            require(canary['name'] not in seen, 'duplicate canary')
            seen.add(canary['name'])
            command = canary['command']
            require(type(command) is list and 0 < len(command) <= 64 and
                    all(type(arg) is str and 0 < len(arg) <= 1024 and '\x00' not in arg for arg in command), 'invalid canary command')
        failures = entry['historical_failures']
        require(type(failures) is list and len(failures) <= 128, 'invalid failure dispositions')
        seen = set()
        for failure in failures:
            fields(failure, 'manager identity rationale evidence_ref evidence_sha256')
            for key in ('manager', 'identity'):
                token(failure[key], r'[\w@.:-]{1,128}')
            token(failure['rationale'], r'[A-Za-z0-9][A-Za-z0-9 ,.():/_-]{0,511}')
            token(failure['evidence_ref'], r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,255}')
            token(failure['evidence_sha256'], r'[0-9a-f]{64}')
            require((failure['manager'], failure['identity']) not in seen, 'duplicate historical failure')
            seen.add((failure['manager'], failure['identity']))
    return value

