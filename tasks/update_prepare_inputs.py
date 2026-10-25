#!/usr/bin/env python3
"""Bind native preparation commands to the complete wave scope; never execute."""

import hashlib
import json
from datetime import datetime, timezone
import sys
from typing import Any

sys.dont_write_bytecode = True
from update_wave_plan import LIMIT, canonical, fields, plan, preparation_window, require, token, unique_object


def current_time():
    return datetime.now(timezone.utc)


def prepare(policy: Any, targets: Any, inputs: Any):
    result = plan(policy, targets)
    # Old policies remain inspectable but cannot initiate another reset without
    # explicitly binding release-long retention for every backup prerequisite.
    require(policy['schema'] in (4, 5))
    start, end = preparation_window(policy['preparation_window'])
    require(start <= current_time() < end)
    require(type(inputs) is dict and set(inputs) == {host['name'] for host in policy['hosts']})
    commands = {}
    for name in inputs:
        entry: Any = inputs[name]
        fields(entry, 'transaction root_generation capacity_policy generation_policy')
        transaction = token(entry['transaction'], r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}')
        for key in ('root_generation', 'capacity_policy'):
            path = token(entry[key], r'/[A-Za-z0-9_./-]{1,254}')
            require(not any(part in ('', '.', '..') for part in path.split('/')[1:]))
            require(path != '/' and not path.startswith('/nest/hosts/'))
        # The installed verifier owns the full producer schema and native
        # checks. Bind its exact input before ANY host reset can start.
        generation: Any = entry['generation_policy']
        require(type(generation) is dict and generation.get('hostname') == name
                and generation.get('release') == result['release']
                and generation.get('destination') == entry['root_generation'])
        commands[name] = ['nest', 'reset', '--transaction', transaction, '--release', result['release'],
                          '--root-generation', entry['root_generation'], '--capacity-policy', entry['capacity_policy'],
                          '--format=json']
    # No host observation occurs here. Native CLI still owns reset admission.
    return dict(result, kind='nest_update_prepare_inputs', inputs=inputs, commands=commands,
                inputs_sha256=hashlib.sha256(canonical(inputs)).hexdigest())


def main():
    try:
        raw = sys.stdin.buffer.read(LIMIT + 1)
        require(len(raw) <= LIMIT)
        params: Any = json.loads(raw, object_pairs_hook=unique_object)
        require(type(params) is dict and {'policy', 'targets', 'inputs'} <= set(params)
                and all(key in {'policy', 'targets', 'inputs'} or key.startswith('_') for key in params))
        print(canonical(prepare(params['policy'], params['targets'], params['inputs'])).decode('ascii'), end='')
        return 0
    except (KeyError, TypeError, ValueError, UnicodeError, RecursionError):
        print(json.dumps({'_error': {'kind': 'nest/update-prepare-inputs',
                                    'msg': 'Invalid complete preparation inputs; no host action performed'}}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
