#!/usr/bin/env python3
"""Dispatch the existing Bolt plan in an existing external user systemd manager."""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

sys.dont_write_bytecode = True
from retain_update_report import output_directory, publish_document, read_report, require, unique
from update_lifecycle import context, active
from update_wave_plan import canonical

LIMIT = 2097152


def command(argv, **kwargs):
    return subprocess.check_output(argv, timeout=30, **kwargs).decode().strip()


def prepare(p):
    project = output_directory(p['project'])
    require(command(['git', '-C', str(project), 'rev-parse', 'HEAD']) == p['source'], 'controller source changed')
    require(command(['git', '-C', str(project), 'status', '--porcelain', '--untracked-files=no']) == '', 'controller source dirty')
    require((project / 'bolt-project.yaml').is_file(), 'missing existing Bolt project')
    params = p['params']
    require(type(params) is dict and set(params) == {'targets', 'mode', 'policy', 'observations', 'reboot', 'output_dir', 'maintenance'} and
            params['mode'] == 'lifecycle' and params['reboot'] is True and
            params['policy']['lifecycle']['controller'] == socket.gethostname(), 'wrong external controller')
    names = [row['name'] for row in params['policy']['hosts']]
    # The existing Nest wrapper mounts this project at /modules/nest. Keep all
    # artifacts in that mount; no /nest/backup scratch or new credentials.
    digest = hashlib.sha256(canonical(params['policy'])).hexdigest()
    relative = '.nest-update/' + digest
    require(params['output_dir'] == '/modules/nest/' + relative and params['targets'] == names,
            'invalid mounted result directory or target scope')
    directory = project / relative
    if p['action'] == 'start':
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    output_directory(directory)
    bound = context(dict(policy=params['policy'], targets=names, inputs=params['observations'], output_dir=str(directory)))
    require(bound['policy_sha256'] == digest, 'policy changed')
    return project, directory, relative, 'nest-update-' + digest, bound


def collect(directory, bound):
    # Export actual referenced sanitized bytes, not paths on another host.
    # The receiver republishes and reopens each copied document independently.
    files = {}

    def visit(receipt):
        require(type(receipt) is dict and {'path', 'sha256', 'bytes'} <= set(receipt), 'invalid export receipt')
        path = Path(receipt['path'])
        require(str(path.parent) == '/modules/nest/.nest-update/' + bound['policy_sha256'], 'report outside release directory')
        local = directory / path.name
        raw = read_report(local, LIMIT)
        require(type(receipt['bytes']) is int and len(raw) == receipt['bytes'] and
                hashlib.sha256(raw).hexdigest() == receipt['sha256'], 'export readback mismatch')
        if path.name in files:
            return
        document = json.loads(raw, object_pairs_hook=unique)
        require(type(document) is dict and type(document.get('kind')) is str and
                document['kind'].startswith(('nest_update_', 'nest_generation_', 'reset_acceptance_')), 'not a sanitized report')
        files[path.name] = dict(source_path=str(path), sha256=receipt['sha256'], bytes=len(raw), document=document)
        walk(document)

    def walk(value):
        if type(value) is dict:
            if {'path', 'sha256', 'bytes'} <= set(value):
                visit(value)
            else:
                for child in value.values():
                    walk(child)
        elif type(value) is list:
            for child in value:
                walk(child)

    for path in directory.glob('lifecycle-result-' + bound['policy_sha256'] + '-*.json'):
        raw = read_report(path, LIMIT)
        visit(dict(path='/modules/nest/.nest-update/' + bound['policy_sha256'] + '/' + path.name,
                   bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
    require(files, 'no completed lifecycle report')
    result = dict(schema=1, kind='nest_update_lifecycle_export', policy_sha256=bound['policy_sha256'], files=list(files.values()))
    require(len(canonical(result)) <= 8 * LIMIT, 'export exceeds bound')
    return result


def receive(p):
    export = p['export']
    require(export['schema'] == 1 and export['kind'] == 'nest_update_lifecycle_export' and
            type(export['files']) is list and 0 < len(export['files']) <= 1024, 'invalid lifecycle export')
    receipts = []
    for row in export['files']:
        raw = (json.dumps(row['document'], sort_keys=True, indent=2) + '\n').encode()
        require(type(row['bytes']) is int and len(raw) == row['bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256'], 'copied report changed')
        prefix = Path(row['source_path']).name.removesuffix('-' + row['sha256'] + '.json')
        receipt = publish_document(row['document'], p['output_dir'], prefix)
        require(receipt['sha256'] == row['sha256'] and receipt['bytes'] == row['bytes'], 'destination readback mismatch')
        receipts.append(dict(source_path=row['source_path'], retained=receipt))
    return publish_document(dict(schema=1, kind='nest_update_lifecycle_delivery', policy_sha256=export['policy_sha256'],
                                 copied_reports=receipts), p['output_dir'], 'lifecycle-delivery-' + export['policy_sha256'])


def run(p):
    if p['action'] == 'receive':
        return receive(p)
    project, directory, relative, unit, bound = prepare(p)
    if p['action'] == 'export':
        return collect(directory, bound)
    if p['action'] == 'inspect':
        state = command(['systemctl', '--user', 'show', unit, '--property=LoadState,ActiveState,SubState,ExecMainStatus'])
        return dict(unit=unit, state=state, completed=False)
    require(p['action'] in ('start', 'resume') and p.get('_noop') is not True, 'invalid dispatch action')
    active(p['params']['policy'])
    payload = canonical(p['params'])
    params_path = directory / 'params.json'
    if p['action'] == 'resume':
        require(read_report(params_path, LIMIT) == payload, 'resume parameters changed')
        require(command(['systemctl', '--user', 'show', unit, '--property=ActiveState', '--value']) in ('inactive', 'failed'),
                'existing controller job is still active')
        require(not list(directory.glob('lifecycle-result-' + bound['policy_sha256'] + '-*.json')), 'lifecycle already completed')
        command(['systemctl', '--user', 'restart', unit])
    else:
        # No overwrite and no retry of an ambiguous dispatch. Inspect the named
        # native unit and retained transaction state; resume is explicit.
        fd = os.open(params_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        command(['systemd-run', '--user', '--unit=' + unit, '--property=WorkingDirectory=' + str(project),
                 '--property=StandardOutput=append:' + str(directory / 'bolt.private.log'),
                 '--property=StandardError=append:' + str(directory / 'bolt.private.log'),
                 'bolt', 'plan', 'run', 'nest::host::update', '--params', '@' + relative + '/params.json', '--format', 'json'])
    return dict(unit=unit, dispatch_requested=True, completed=False, policy_sha256=bound['policy_sha256'])


def main():
    try:
        raw = sys.stdin.buffer.read(8 * LIMIT + 1)
        require(len(raw) <= 8 * LIMIT, 'parameter limit')
        print(json.dumps(run(json.loads(raw, object_pairs_hook=unique)), sort_keys=True))
        return 0
    except (KeyError, TypeError, ValueError, OSError, UnicodeError, RecursionError, subprocess.SubprocessError):
        print(json.dumps({'_error': {'kind': 'nest/update-dispatch', 'msg': 'Dispatch or report transfer failed; inspect the exact existing unit and retained transaction, never create another run'}}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
