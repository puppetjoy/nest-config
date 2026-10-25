#!/usr/bin/env python3
"""Bind checked compiler projections to published executor members; never deploy."""

import argparse
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
EXECUTOR = runpy.run_path(str(ROOT / 'bin/ci-executor-receipt'))
CPUS = {'haswell': 'amd64', 'cortex-a53': 'arm64', 'sifive-u74': 'riscv64'}
INDEX_TYPES = {'application/vnd.oci.image.index.v1+json', 'application/vnd.docker.distribution.manifest.list.v2+json'}


def require(value):
    if not value:
        raise ValueError('Compiler candidate unavailable')


def load(path):
    with Path(path).open('rb') as stream:
        raw = stream.read(131073)
    require(len(raw) <= 131072)
    return json.loads(raw, object_pairs_hook=EXECUTOR['unique'])


def write(path, value):
    payload = (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode('ascii')
    with Path(path).open('xb') as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    require(Path(path).read_bytes() == payload)


def expected(value, source):
    require(type(value) is dict and set(value) == {'schema', 'environment', 'source', 'code_id'})
    require(type(value['schema']) is int and value['schema'] == 1)
    require(value['environment'] == 'main' and value['source'] == source)
    require(type(value['code_id']) is str and re.fullmatch(r'sha256:[0-9a-f]{64}', value['code_id']))
    return value


def checked(row, context=None):
    require(type(row) is dict and set(row) == {'schema', 'executor', 'expected'})
    require(type(row['schema']) is int and row['schema'] == 1)
    member = row['executor']
    require(type(member) is dict)
    EXECUTOR['validate'](member, member.get('cpu'), context)
    expected(row['expected'], member['sha'])
    return row


def command(argv, phase, timeout=180):
    return EXECUTOR['command'](argv, phase, timeout=timeout)


def record(receipt, output):
    member = load(receipt)
    require(type(member) is dict)
    EXECUTOR['validate'](member, os.environ.get('CPU'))
    require(str(member['job']) == os.environ.get('CI_JOB_ID'))
    # The existing executor verifier checks the published member first. Read
    # the projection from that same digest, never a mounted source checkout.
    command(['podman', 'pull', member['image']], 'pull compiler member', timeout=600)
    probe = '''import json,runpy,subprocess,sys
from pathlib import Path
project=Path('/opt/nest')
inputs=json.loads((project/'.executor-inputs.json').read_bytes())
observed=runpy.run_path(str(project/'scripts/nest-executor-inputs.py'))['observe'](project,sys.argv[1],inputs['base_image'])
if observed != inputs or json.loads(Path('/opt/nest-compiler-release/executor-inputs.json').read_bytes()) != inputs:
    raise ValueError('Installed compiler inputs differ')
ruby="require '/opt/nest/files/puppet-versioned-code'; receipt=JSON.parse(File.read('/opt/nest-compiler-release/expected.json')); NestPuppetVersionedCode::Snapshot.new('/opt/nest-compiler-release/main',receipt); puts JSON.generate(receipt)"
receipt=json.loads(subprocess.check_output(['ruby','-e',ruby],text=True))
print(json.dumps(dict(expected=receipt,inputs=observed)))
'''
    raw = command(['podman', 'run', '--rm', '--pull=never', '--network=none', '--read-only', '--read-only-tmpfs=false',
                   '--cap-drop=ALL', '--security-opt=no-new-privileges', '--entrypoint=python3', member['image'],
                   '-c', probe, member['sha']], 'check installed compiler projection')
    require(len(raw) <= 131072)
    observed = json.loads(raw, object_pairs_hook=EXECUTOR['unique'])
    require(type(observed) is dict and set(observed) == {'expected', 'inputs'} and observed['inputs'] == member['inputs'])
    row = checked({'schema': 1, 'executor': member, 'expected': observed['expected']})
    write(output, row)
    return row


def candidate(directory, reference, output):
    source, pipeline, repository = EXECUTOR['context']()
    # An ordinary main publication only, never branch/bootstrap promotion.
    require(repository == 'registry.gitlab.joyfullee.me/nest/config/main')
    require(os.environ.get('CI_COMMIT_BRANCH') == 'main')
    require(type(reference) is str and re.fullmatch(r'registry\.eyrie/nest/config/main@sha256:[0-9a-f]{64}', reference))
    rows = [checked(load(Path(directory) / (cpu + '.compiler.json'))) for cpu in CPUS]
    require([row['executor']['cpu'] for row in rows] == list(CPUS))
    require(len({row['executor']['job'] for row in rows}) == len(CPUS))
    require(len({row['executor']['image'] for row in rows}) == len(CPUS))
    receipt = rows[0]['expected']
    for row in rows:
        require(row['expected'] == receipt)
        # Base images may be architecture-specific, but the full module set
        # and Puppetfile must agree before selecting a common compiler ID.
        require(row['executor']['inputs']['modules'] == rows[0]['executor']['inputs']['modules'])
        require(row['executor']['inputs']['puppetfile_digest'] == rows[0]['executor']['inputs']['puppetfile_digest'])
    verify_index(reference, rows)
    result = {'schema': 1, 'kind': 'nest_openvox_compiler_candidate', 'source': source, 'pipeline': pipeline,
              'current': {'image': reference, 'expected': receipt}, 'members': rows,
              'deployment_authorized': False, 'retention_complete': False, 'compiler_attestation': False}
    # Deliberately not a complete chart selection: retained catalog identities
    # must be reconciled before any replacement, not silently reset to [].
    write(output, result)
    return result


def release(value):
    require(type(value) is dict and set(value) == {'image', 'expected'})
    require(type(value['image']) is str and re.fullmatch(r'registry\.eyrie/nest/config/main@sha256:[0-9a-f]{64}', value['image']))
    receipt = value['expected']
    require(type(receipt) is dict and type(receipt.get('source')) is str and re.fullmatch(r'[0-9a-f]{40}', receipt['source']))
    expected(receipt, receipt['source'])
    return value


def selection(candidate_path, previous_path, output):
    """Propose an additive successor; an explicit previous selection is required.

    This does not accept a legacy mutable deployment, retire any code identity,
    mutate Hiera or deploy. The caller must separately establish the previous
    selection's provenance and the deployment's normal acceptance obligations.
    """
    value = load(candidate_path)
    require(type(value) is dict and set(value) == {'schema', 'kind', 'source', 'pipeline', 'current', 'members',
                                                   'deployment_authorized', 'retention_complete', 'compiler_attestation'})
    require(type(value['schema']) is int and value['schema'] == 1 and value['kind'] == 'nest_openvox_compiler_candidate')
    require(type(value['source']) is str and re.fullmatch(r'[0-9a-f]{40}', value['source']))
    require(type(value['pipeline']) is int and value['pipeline'] > 0)
    require(all(value[field] is False for field in ('deployment_authorized', 'retention_complete', 'compiler_attestation')))
    current = release(value['current'])
    require(current['expected']['source'] == value['source'])
    require(type(value['members']) is list and len(value['members']) == len(CPUS))
    context = (value['source'], value['pipeline'], 'registry.gitlab.joyfullee.me/nest/config/main')
    rows = [checked(row, context) for row in value['members']]
    require([row['executor']['cpu'] for row in rows] == list(CPUS))
    require(len({row['executor']['job'] for row in rows}) == len(CPUS))
    require(len({row['executor']['image'] for row in rows}) == len(CPUS))
    for row in rows:
        require(row['expected'] == current['expected'])
        require(row['executor']['inputs']['modules'] == rows[0]['executor']['inputs']['modules'])
        require(row['executor']['inputs']['puppetfile_digest'] == rows[0]['executor']['inputs']['puppetfile_digest'])
    previous = load(previous_path)
    require(type(previous) is dict and set(previous) == {'schema', 'current', 'retained'})
    require(type(previous['schema']) is int and previous['schema'] == 1 and type(previous['retained']) is list)
    prior = [release(previous['current'])] + [release(item) for item in previous['retained']]
    identities = [item['expected']['code_id'] for item in prior]
    require(len(identities) == len(set(identities)))
    retained = []
    for item in prior:
        if item['expected']['code_id'] == current['expected']['code_id']:
            require(item['expected'] == current['expected'])
        else:
            retained.append(item)
    # Validate all local inputs before any registry access. Reopen the exact
    # candidate index; never resolve latest or regenerate expected tree bytes.
    verify_index(current['image'], rows)
    result = {'schema': 1, 'current': current, 'retained': retained}
    write(output, result)
    return result


def verify_index(reference, rows):
    raw = command(['podman', 'manifest', 'inspect', reference], 'check published compiler index')
    require(len(raw) <= 131072)
    index = json.loads(raw, object_pairs_hook=EXECUTOR['unique'])
    require(type(index) is dict and type(index.get('schemaVersion')) is int and index['schemaVersion'] == 2)
    require(index.get('mediaType') in INDEX_TYPES and type(index.get('manifests')) is list)
    wanted = {CPUS[row['executor']['cpu']]: row['executor']['image'].split('@')[1] for row in rows}
    require(len(index['manifests']) == len(wanted))
    actual = {}
    for item in index['manifests']:
        require(type(item) is dict and type(item.get('platform')) is dict)
        platform = item['platform']
        require(set(platform) <= {'os', 'architecture', 'variant'} and platform.get('os') == 'linux')
        arch = platform.get('architecture')
        require(type(arch) is str and arch in wanted and arch not in actual)
        require(platform.get('variant', '') in ('', 'v8') and (platform.get('variant', '') == '' or arch == 'arm64'))
        require(type(item.get('size')) is int and item['size'] > 0)
        require(item.get('mediaType') in {'application/vnd.oci.image.manifest.v1+json', 'application/vnd.docker.distribution.manifest.v2+json'})
        actual[arch] = item.get('digest')
    require(actual == wanted)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    one = commands.add_parser('record')
    one.add_argument('executor_receipt', type=Path)
    one.add_argument('output', type=Path)
    many = commands.add_parser('candidate')
    many.add_argument('directory', type=Path)
    many.add_argument('index_reference')
    many.add_argument('output', type=Path)
    successor = commands.add_parser('selection', help='Propose an additive successor to an explicitly accepted previous selection; never deploy')
    successor.add_argument('candidate', type=Path)
    successor.add_argument('previous_selection', type=Path)
    successor.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        if args.action == 'record':
            record(args.executor_receipt, args.output)
        elif args.action == 'candidate':
            candidate(args.directory, args.index_reference, args.output)
        else:
            selection(args.candidate, args.previous_selection, args.output)
        return 0
    except (OSError, ValueError, KeyError, TypeError, RecursionError, subprocess.SubprocessError):
        print('Compiler candidate unavailable; no deployment authorized', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
