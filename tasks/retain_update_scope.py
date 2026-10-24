#!/usr/bin/env python3
"""Retain an exact wave-policy index of already published native host reports."""

import hashlib
import json
from pathlib import Path
import sys
from typing import Any

sys.dont_write_bytecode = True
from retain_update_report import output_directory, publish_document, read_report, report_directory, require, token, unique
from update_observe_inputs import observe

LIMIT = 524288
REPORT_LIMIT = 262144
RECEIPT_KEYS = ('path', 'sha256', 'bytes', 'id', 'release', 'hostname', 'phase_count', 'state',
                'cli_accepted', 'cli_finalized', 'observation_retained', 'readback_verified')


def context(arguments):
    require(arguments['mode'] in ('prepare', 'observe'), 'invalid scope mode')
    output_directory(arguments['output_dir'])
    # Reuse complete scope, exclusion, domain and transaction validation without
    # initiating preparation or interpreting a preparation window as authority.
    return observe(arguments['policy'], arguments['targets'], arguments['observations'])


def host_report(receipt: Any, name, transaction, release, directory, mode):
    require(type(receipt) is dict and receipt.get('readback_verified') is True, 'missing host receipt')
    path_value: Any = receipt['path']
    require(type(path_value) is str, 'invalid report path')
    path = Path(path_value)
    digest = token(receipt['sha256'], r'[0-9a-f]{64}')
    require(path.parent == directory and path.name == name + '-' + transaction + '-' + digest + '.json',
            'wrong report path')
    raw = read_report(path, REPORT_LIMIT)
    require(type(receipt['bytes']) is int and len(raw) == receipt['bytes'] and
            hashlib.sha256(raw).hexdigest() == digest, 'changed host report')
    report = json.loads(raw, object_pairs_hook=unique)
    require(type(report['schema']) is int and report['schema'] == 1 and
            report['kind'] == 'nest_update_retained_report' and report['id'] == transaction and
            report['release'] == release and report['host']['hostname'] == name and
            report['acceptance_independently_verified'] is False, 'wrong host report context')
    require(report['state'] in ('pending', 'stopped', 'prepared', 'accepted', 'finalizing', 'finalized'), 'invalid host state')
    expected = {'id': transaction, 'release': release, 'hostname': name, 'state': report['state'],
                'phase_count': len(report['phases']), 'cli_accepted': report['cli_accepted'],
                'cli_finalized': report['cli_finalized'], 'observation_retained': 'observation' in report}
    require(type(report['cli_accepted']) is bool and type(report['cli_finalized']) is bool, 'invalid lifecycle flags')
    for key, value in expected.items():
        require(type(receipt[key]) is type(value) and receipt[key] == value, 'changed host receipt')
    if mode == 'prepare':
        require(report['state'] == 'prepared' and report['prepared'] is True and
                report['cli_accepted'] is False and report['cli_finalized'] is False and
                report['reboot_requested'] is False and 'reboot' not in report, 'not an unsubmitted preparation')
    else:
        require('observation' in report and type(report['observation']) is dict, 'missing live observation')
    # Unknown receipt fields (including private caller data and prerequisite
    # payloads) never enter this index. Those prerequisite retainers remain separate.
    return {key: receipt[key] for key in RECEIPT_KEYS}


def scope_document(arguments, bound, waves):
    require(type(waves) is list and len(waves) == len(bound['waves']), 'incomplete wave coverage')
    directory = output_directory(arguments['output_dir'])
    retained = []
    for expected_wave, actual_wave in zip(bound['waves'], waves):
        require(type(actual_wave) is list and len(actual_wave) == len(expected_wave), 'incomplete host coverage')
        retained.append([host_report(receipt, name, bound['inputs'][name]['transaction'],
                                     bound['release'], directory, arguments['mode'])
                         for name, receipt in zip(expected_wave, actual_wave)])
    return {'schema': 1, 'kind': 'nest_update_scope_index', 'mode': arguments['mode'],
            'policy': arguments['policy'], 'policy_sha256': bound['policy_sha256'],
            'observations': bound['inputs'], 'waves': retained,
            'host_count': sum(len(wave) for wave in retained),
            'reboot_eligible': [], 'execution_authorized': False, 'acceptance_recorded': False}


def scope_receipt(receipt, document):
    return dict(receipt, kind=document['kind'], mode=document['mode'], policy_sha256=document['policy_sha256'],
                host_count=document['host_count'], reboot_eligible=[], execution_authorized=False, acceptance_recorded=False)


def retain(arguments, bound):
    document = scope_document(arguments, bound, arguments['waves'])
    directory = output_directory(arguments['output_dir'])
    require(document == scope_document(arguments, bound, arguments['waves']), 'host reports changed during acquisition')
    receipt = publish_document(document, directory, 'scope-' + arguments['mode'] + '-' + bound['policy_sha256'])
    # A failed final reopen never returns a success receipt, even if the index
    # snapshot was already published. Preserve that file for diagnosis, not retry.
    require(document == scope_document(arguments, bound, arguments['waves']), 'host reports changed during publication')
    return scope_receipt(receipt, document)


def reopen_scope(arguments, bound):
    # Only the original content-addressed index selects reports. Caller-supplied
    # waves must not replace a missing or changed historical execution result.
    require('waves' not in arguments, 'read refuses replacement waves')
    receipt: Any = arguments['receipt']
    require(type(receipt) is dict and type(receipt.get('path')) is str, 'missing scope receipt')
    path_value: Any = receipt['path']
    path = Path(path_value)
    digest = token(receipt['sha256'], r'[0-9a-f]{64}')
    prefix = 'scope-' + arguments['mode'] + '-' + bound['policy_sha256']
    with report_directory(arguments['output_dir']) as (directory, _):
        require(path.parent == directory and path.name == prefix + '-' + digest + '.json', 'wrong scope path')
        raw = read_report(path, LIMIT)
        require(type(receipt['bytes']) is int and len(raw) == receipt['bytes'] and
                hashlib.sha256(raw).hexdigest() == digest, 'changed scope index')
        document = json.loads(raw, object_pairs_hook=unique)
        require(type(document) is dict, 'invalid scope index')
        expected = scope_document(arguments, bound, document['waves'])
        # Canonical bytes also distinguish booleans from integer lookalikes and
        # refuse extra/private fields instead of echoing them during recovery.
        canonical = (json.dumps(expected, sort_keys=True, indent=2) + '\n').encode('utf-8')
        require(raw == canonical, 'wrong scope context or report coverage')
        expected_receipt = scope_receipt(dict(path=str(path), sha256=digest, bytes=len(raw), readback_verified=True), expected)
        require(json.dumps(receipt, sort_keys=True) == json.dumps(expected_receipt, sort_keys=True), 'changed scope receipt')
        require(raw == read_report(path, LIMIT) and expected == scope_document(arguments, bound, document['waves']),
                'scope or host reports changed during recovery')
    # A retained prepared report can be old even when its bytes are intact. No
    # host is contacted, freshness asserted, phase resumed or command authorized.
    return dict(expected_receipt, waves=expected['waves'], observations=expected['observations'],
                scope_reopened=True, read_only=True, historical_only=True, host_action_performed=False)


def main():
    try:
        raw = sys.stdin.buffer.read(LIMIT + 1)
        require(len(raw) <= LIMIT, 'oversized scope input')
        arguments = json.loads(raw, object_pairs_hook=unique)
        require(type(arguments) is dict and arguments['action'] in ('check', 'retain', 'read'), 'invalid action')
        bound = context(arguments)
        result = {'destination_checked': True, 'scope_checked': True, 'host_action_performed': False}
        if arguments['action'] == 'retain':
            result = retain(arguments, bound)
        elif arguments['action'] == 'read':
            result = reopen_scope(arguments, bound)
        print(json.dumps(result))
        return 0
    except (KeyError, TypeError, ValueError, OSError, UnicodeError, RecursionError):
        print(json.dumps({'_error': {'kind': 'nest/update-scope-retention',
                                   'msg': 'Update scope or host report readback failed; inspect retained reports, never replay'}}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
