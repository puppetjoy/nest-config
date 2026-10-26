#!/usr/bin/env python3
"""Small policy/journal/acceptance adapter for the existing Bolt lifecycle plans."""

import hashlib
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
from retain_update_report import output_directory, project, publish_document, read_report, require, token, unique
from update_observe_inputs import observe
from update_wave_plan import canonical, preparation_window
from update_prepare_inputs import current_time
from update_lifecycle_policy import lifecycle_policy
import update_network_health

LIMIT = 2097152


def context(p):
    bound = observe(p['policy'], p['targets'], p['inputs'])
    require(p['policy']['schema'] == 5, 'lifecycle requires complete policy')
    output_directory(p['output_dir'])
    return bound


def active(policy):
    start, end = preparation_window(policy['lifecycle']['window'])
    require(start <= current_time() < end, 'disruption window closed')


def reopen(receipt, directory):
    require(type(receipt) is dict and receipt.get('readback_verified') is True, 'missing retained result')
    path = Path(receipt['path'])
    require(path.parent == output_directory(directory), 'report outside supervisor directory')
    raw = read_report(path, LIMIT)
    require(type(receipt['bytes']) is int and len(raw) == receipt['bytes'] and
            hashlib.sha256(raw).hexdigest() == receipt['sha256'], 'report changed')
    return json.loads(raw, object_pairs_hook=unique)


def journal(p, bound):
    token(p['host'], r'[a-z0-9][a-z0-9_.-]{0,127}')
    require(p['host'] in bound['inputs'], 'unknown lifecycle host')
    token(p['step'], r'(?:catalog|health|reboot|submit|accept|finalize|canary-[a-z][a-z0-9_-]{0,63})')
    prefix = 'lifecycle-' + bound['policy_sha256'] + '-' + p['host'] + '-' + p['step']
    return output_directory(p['output_dir']) / (prefix + '.json')


def save_exclusive(path, data):
    # Intent is durable BEFORE a side effect. An ambiguous intent is never
    # converted into permission to replay catalog or canary commands.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(canonical(data))
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def step(p, bound):
    path = journal(p, bound)
    done = path.with_name(path.stem + '-complete.json')
    if p['action'] == 'begin':
        active(p['policy'])
        save_exclusive(path, {'policy_sha256': bound['policy_sha256'], 'host': p['host'], 'step': p['step']})
        return {'intent_retained': True}
    if p['action'] == 'complete':
        # Read-only admission and health collection need a retained result, not
        # a second intent file. Interrupted observations can be collected again;
        # mutations and arbitrary canary commands still require prior intent.
        require(p['step'] in ('reboot', 'health') or path.exists(), 'missing operation intent')
        result = p['result']
        # Only published sanitized results enter the journal, never raw command output.
        reopen(result, p['output_dir'])
        save_exclusive(done, result)
    if done.exists():
        receipt = json.loads(read_report(done, LIMIT), object_pairs_hook=unique)
        reopen(receipt, p['output_dir'])
        return {'complete': True, 'intent': path.exists(), 'receipt': receipt}
    return {'complete': False, 'intent': path.exists()}


def native(p, bound):
    name = p['host']
    return project(p['status'], bound['inputs'][name]['transaction'], bound['release'], name)


def boot_expectations(p, bound):
    report = native(p, bound)
    observed = report.get('observation', {})
    require(report['prepared'] and observed.get('boot_changed') is True and
            observed.get('expected_target_booted') is True and observed['current'] == report['host']['target'] and
            observed['next_boot'] == report['host']['target'] and 'reboot' in report, 'target boot not observed')
    tree = {row['dataset']: row for row in report['target_tree']}
    target = report['host']['target']
    host = next(row for row in p['policy']['hosts'] if row['name'] == p['host'])
    return {'hostname': p['host'], 'kernel': host['kernel'], 'previous_boot_id': report['host']['boot_id'],
            'current': target, 'current_guid': tree[target]['guid'], 'var_guid': tree[target + '/var']['guid'],
            'pool_guid': report['host']['pool_guid']}


def ref(receipt, section=''):
    return {'result': 'pass', 'evidence_ref': 'sha256:' + receipt['sha256'] + ('/' + section if section else ''),
            'evidence_sha256': receipt['sha256']}


def evidence(p, bound):
    report = native(p, bound)
    expected = boot_expectations(p, bound)
    boot = report['observation']['boot_id']
    name = p['host']
    settings = p['policy']['lifecycle']['acceptance'][name]
    receipts = {}
    documents = {}
    for key in ('health', 'catalog'):
        entry = step(dict(p, action='read', step=key), bound)
        require(entry['complete'], 'acceptance observation missing')
        receipts[key] = entry['receipt']
        documents[key] = reopen(entry['receipt'], p['output_dir'])
    health, catalog = documents['health'], documents['catalog']
    require(health['kind'] == 'nest_update_retained_health' and health['transaction'] == report['id'] and
            health['release'] == report['release'] and health['expectations'] == expected and
            health['endpoints'] == settings['endpoints'] and health['observations_bound'] is True and
            health['boot_before'] == health['boot_after'] and health['boot_before']['boot_id'] == boot and
            health['boot_before']['result'] == 'pass' and health['network']['result'] == 'pass' and
            health['network']['boot_id'] == boot, 'health acceptance failed')
    require(catalog['kind'] == 'nest_update_retained_catalog' and catalog['transaction'] == report['id'] and
            catalog['release'] == report['release'] and catalog['expectations'] == {
                'hostname': name, 'certname': settings['certname'], 'boot_id': boot,
                'configuration_version': p['policy']['config_source']}, 'catalog context mismatch')
    cat = catalog['catalog']
    require(cat['result'] == 'pass' and cat['converged'] is True and cat['hostname'] == name and cat['boot_id'] == boot and
            cat['main']['report_bound'] is True and cat['repeat']['report_bound'] is True and
            type(cat['main']['native_exit']) is int and cat['main']['native_exit'] in (0, 2) and
            cat['repeat']['native_exit'] == 0 and
            cat['main']['report']['transaction_uuid'] != cat['repeat']['report']['transaction_uuid'], 'catalog acceptance failed')
    managers = health['managers']
    require(managers['hostname'] == name and managers['boot_id'] == boot, 'manager boot mismatch')
    # Projections are already validated by retain_update_health. Missing buses
    # cannot pass; only exact, reviewed historical units may remain failed.
    historical = {(row['manager'], row['identity']): row for row in settings['historical_failures']}
    used = set()

    def failures(manager, inventory):
        require(inventory['availability'] == 'available' and inventory['inventory_complete'] is True, 'manager unavailable')
        result = []
        require(inventory.get('failures_after', inventory['failures']) == inventory['failures'], 'failure inventory changed')
        for row in inventory['failures']:
            key = manager, row['identity']
            require(key in historical, 'unexplained failed unit')
            disposition = historical[key]
            used.add(key)
            result.append({'identity': row['identity'], 'disposition': 'explained_historical',
                           'evidence_ref': disposition['evidence_ref'], 'evidence_sha256': disposition['evidence_sha256']})
        return result

    system_failures = failures('system', managers['system_failures'])
    users = managers['user_managers']
    require(users['availability'] == 'available' and users['inventory_complete'] is True, 'user inventory unavailable')
    user_failures = []
    user_rows = []
    for row in users['managers']:
        user_failures.extend(failures(row['identity'], row))
        user_rows.append(dict(ref(receipts['health'], row['identity']), identity=row['identity'], availability='available'))
    require(used == set(historical), 'historical disposition no longer matches observations')
    canaries = []
    for canary in settings['canaries']:
        entry = step(dict(p, action='read', step='canary-' + canary['name']), bound)
        require(entry['complete'], 'canary incomplete')
        document = reopen(entry['receipt'], p['output_dir'])
        require(document == dict(schema=1, kind='nest_update_canary', hostname=name, transaction=report['id'],
                                 release=report['release'], boot_id=boot, name=canary['name'],
                                 command_sha256=hashlib.sha256(canonical(canary['command'])).hexdigest(),
                                 native_exit=0), 'canary failed or wrong boot')
        canaries.append(entry['receipt'])
    gates = {key: ref(receipts['health'], key) for key in ('kernel', 'root_var', 'pools', 'network_dns_trust')}
    for key, section in (('normal_main_apply', 'main'), ('converged_repeat', 'repeat')):
        gates[key] = dict(ref(receipts['catalog'], section), native_exit=cat[section]['native_exit'])
    gates['system_failures'] = dict(ref(receipts['health'], 'system'), availability='available', inventory_complete=True, failures=system_failures)
    gates['user_managers'] = dict(ref(receipts['health'], 'users'), availability='available', inventory_complete=True,
                                  failures=user_failures, managers=user_rows)
    summary = publish_document({'schema': 1, 'kind': 'nest_update_acceptance_collection', 'hostname': name,
                                'transaction': report['id'], 'release': report['release'], 'boot_id': boot,
                                'health': receipts['health'], 'catalog': receipts['catalog'], 'canaries': canaries,
                                'historical_failures': settings['historical_failures'], 'physical_ux': 'not_observed'},
                               p['output_dir'], 'acceptance-collection-' + report['id'])
    gates['service_canaries'] = ref(summary, 'canaries')
    document = dict(schema=1, kind='reset_acceptance_evidence', transaction_id=report['id'], release=report['release'],
                    observed_boot_id=boot, host_identity_sha256=report['host_identity_sha256'], pool_guid=report['host']['pool_guid'],
                    shared_state=report['shared_state'], target_tree=report['target_tree'], gates=gates)
    document.update({key: value for key, value in ref(summary).items() if key != 'result'})
    receipt = publish_document(document, p['output_dir'], 'acceptance-' + report['id'])
    return dict(receipt, evidence=document, collection=summary)


def main():
    try:
        raw = sys.stdin.buffer.read(LIMIT + 1)
        require(len(raw) <= LIMIT, 'parameter limit')
        p = json.loads(raw, object_pairs_hook=unique)
        require(p.get('_noop') is not True, 'lifecycle is not noop')
        bound = context(p)
        action = p['action']
        if action == 'inputs':
            result = bound
        elif action == 'admit':
            active(p['policy'])
            result = {'window_open': True}
        elif action in ('read', 'begin', 'complete'):
            result = step(p, bound)
        elif action == 'boot':
            result = boot_expectations(p, bound)
        elif action == 'evidence':
            result = evidence(p, bound)
        elif action == 'canary':
            report = native(p, bound)
            boot_expectations(p, bound)
            canary = next(row for row in p['policy']['lifecycle']['acceptance'][p['host']]['canaries'] if row['name'] == p['canary'])
            require(type(p['native_exit']) is int and 0 <= p['native_exit'] <= 255, 'invalid canary exit')
            result = publish_document(dict(schema=1, kind='nest_update_canary', hostname=p['host'], transaction=report['id'],
                                           release=report['release'], boot_id=report['observation']['boot_id'], name=canary['name'],
                                           command_sha256=hashlib.sha256(canonical(canary['command'])).hexdigest(), native_exit=p['native_exit']),
                                      p['output_dir'], 'canary-' + report['id'] + '-' + canary['name'])
        elif action == 'retain':
            result = publish_document(p['report'], p['output_dir'], 'lifecycle-result-' + bound['policy_sha256'])
        else:
            raise ValueError('invalid lifecycle action')
        print(json.dumps(result, sort_keys=True))
        return 0
    except (KeyError, TypeError, ValueError, OSError, UnicodeError, RecursionError, StopIteration, update_network_health.Unavailable):
        print(json.dumps({'_error': {'kind': 'nest/update-lifecycle', 'msg': 'Lifecycle binding or retention failed; inspect exact phase, never replay ambiguous mutations'}}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
