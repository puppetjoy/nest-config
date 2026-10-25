#!/usr/bin/env python3
"""Advance an already immutable compiler through the existing KubeCM plan."""
import argparse
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = runpy.run_path(str(ROOT / 'scripts/nest-compiler-candidate.py'))
require, load = CANDIDATE['require'], CANDIDATE['load']
ANNOTATION = 'nest.eyrie/compiler-selection'


def command(argv, timeout=180, log=None):
    # Rendering can contain private chart data. Never copy native stdout/stderr
    # into the public result or exception; keep only the safe phase failure.
    result = subprocess.run(argv, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False)
    if log is not None:
        for suffix, payload in (('.stdout', result.stdout), ('.stderr', result.stderr)):
            descriptor = os.open(str(log) + suffix, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(payload)
    require(result.returncode == 0)
    return result.stdout


def selection(value):
    require(type(value) is dict and set(value) == {'schema', 'current', 'retained'})
    require(type(value['schema']) is int and value['schema'] == 1)
    require(type(value['retained']) is list and len(value['retained']) < 128)
    releases = [CANDIDATE['release'](value['current'])] + [CANDIDATE['release'](row) for row in value['retained']]
    require(len({row['expected']['code_id'] for row in releases}) == len(releases))
    return value


def predecessor(deployment, namespace, live=True):
    """Read declared selection AND native layout; an annotation alone is not evidence."""
    require(type(deployment) is dict and deployment.get('kind') == 'Deployment' and deployment.get('apiVersion') == 'apps/v1')
    meta = deployment['metadata']
    require(meta['name'] == 'puppet-puppetserver' and meta.get('namespace', namespace if not live else None) == namespace)
    if live:
        require(type(meta['uid']) is str and len(meta['uid']) > 0)
        require(type(meta['resourceVersion']) is str and len(meta['resourceVersion']) > 0)
    template = deployment['spec']['template']
    spec = template['spec']
    strategy = deployment['spec']['strategy']
    require(strategy == {'type': 'Recreate'} or not live and strategy == {'type': 'Recreate', 'rollingUpdate': None})
    # Refuse legacy first adoption, partial/manual hook changes and unannotated
    # snapshots. Their consumer scope must be reconciled outside routine CI.
    value = selection(json.loads(template['metadata']['annotations'][ANNOTATION], object_pairs_hook=CANDIDATE['EXECUTOR']['unique']))
    releases = value['retained'] + [value['current']]
    inits = [item for item in spec['initContainers'] if item['name'].startswith('compiler-snapshot-')]
    require(len(inits) == len(releases))
    for index, (init, release) in enumerate(zip(inits, releases)):
        require(init['name'] == 'compiler-snapshot-' + str(index) and init['image'] == release['image'])
        argv = init['command']
        require(argv[:2] == ['ruby', '-e'] and json.loads(argv[3]) == release['expected'])
        require(argv[4] == ('first' if index == 0 else 'next'))
        require(init['volumeMounts'] == [{'name': 'compiler-snapshots', 'mountPath': '/compiler'}])
        require(init['securityContext']['readOnlyRootFilesystem'] is True)
    require(json.loads(inits[-1]['command'][5]) == [item['expected'] for item in releases])
    require(inits[-1]['command'][6] == value['current']['expected']['code_id'])
    containers = spec['containers']
    require(containers[0]['name'] == 'puppet-puppetserver')
    required = {'/compiler': None, '/docker-custom-entrypoint.d/20-compiler.sh': 'runtime/entrypoint'}
    mounts = [item for item in containers[0]['volumeMounts'] if item['name'] == 'compiler-snapshots']
    require(len(mounts) == len(required))
    for mount in mounts:
        require(mount['mountPath'] in required and mount['readOnly'] is True)
        require(mount.get('subPath') == required[mount['mountPath']])
    require(not any(item['name'] == 'puppet-code-storage' for item in containers[0]['volumeMounts']))
    require(not any(item['name'] == 'compiler-snapshots' for container in containers[1:] for item in container.get('volumeMounts', [])))
    volumes = [item for item in spec['volumes'] if item['name'] == 'compiler-snapshots']
    require(volumes == [{'name': 'compiler-snapshots', 'emptyDir': {}}])
    return value


def ready(deployment):
    status = deployment['status']
    count = deployment['spec'].get('replicas', 1)
    require(type(count) is int and count > 0)
    require(status['observedGeneration'] == deployment['metadata']['generation'])
    require(all(status.get(key, 0) == count for key in ('replicas', 'updatedReplicas', 'readyReplicas', 'availableReplicas')))
    require(status.get('unavailableReplicas', 0) == 0)


def successor(candidate, previous):
    current = candidate['current']
    retained = []
    for item in [previous['current']] + previous['retained']:
        if item['expected']['code_id'] == current['expected']['code_id']:
            require(item['expected'] == current['expected'])
        else:
            retained.append(item)
    return selection({'schema': 1, 'current': current, 'retained': retained})


def get_deployment(namespace):
    raw = command(['kubectl', 'get', 'deployment', '-n', namespace, 'puppet-puppetserver', '-o', 'json'])
    require(len(raw) <= 2097152)
    return json.loads(raw, object_pairs_hook=CANDIDATE['EXECUTOR']['unique'])


def assert_same(before, after):
    # Recheck immediately before Helm. The CI resource group serializes ordinary
    # writers; this detects intervening manual writes, not an atomic cluster lock.
    require(all(before['metadata'][key] == after['metadata'][key] for key in ('uid', 'resourceVersion')))


def rendered_deployment(manifest):
    raw = command(['ruby', '-ryaml', '-rjson', '-e',
                   'docs=YAML.load_stream(File.read(ARGV.fetch(0))); puts JSON.generate(docs.select { |d| d.is_a?(Hash) && d["kind"] == "Deployment" && d.dig("metadata", "name") == "puppet-puppetserver" })',
                   str(manifest)])
    deployments = json.loads(raw)
    require(type(deployments) is list and len(deployments) == 1)
    return deployments[0]


def guard_chart(namespace, manifest):
    """Prevent ordinary stack redeployment from forgetting CI-retained identities."""
    require(namespace in ('test', 'default'))
    before = get_deployment(namespace)
    prior = predecessor(before, namespace)
    selected = predecessor(rendered_deployment(manifest), namespace, live=False)
    retained = {row['expected']['code_id']: row for row in [selected['current']] + selected['retained']}
    for release in [prior['current']] + prior['retained']:
        require(retained.get(release['expected']['code_id']) == release)
    assert_same(before, get_deployment(namespace))
    return {'schema': 1, 'kind': 'nest_openvox_compiler_chart_guard', 'namespace': namespace,
            'prior_identities_preserved': True, 'deployed': False, 'compiler_attestation': False}


def hiera_overlay(directory, value):
    # Keep the original hierarchy and encrypted data handling intact. Only this
    # invocation's compiler selection overrides Hiera, never the source checkout.
    raw = command(['ruby', '-ryaml', '-rjson', '-e', 'puts JSON.generate(YAML.load_file(ARGV.fetch(0)))', str(ROOT / 'hiera.yaml')])
    config = json.loads(raw)
    datadir = ROOT / config['defaults'].get('datadir', 'data')
    config['defaults']['datadir'] = os.path.relpath(datadir, directory)
    entry = {'name': 'Invocation compiler selection', 'datadir': '.', 'path': 'selection.json'}
    config['hierarchy'].insert(0, entry)
    CANDIDATE['write'](directory / 'selection.json', {'nest::service::puppet::compiler_release': value})
    CANDIDATE['write'](directory / 'hiera.json', config)


def rollout(candidate_path, namespace, output, deploy=False, check_only=False):
    require(namespace in ('test', 'default'))
    # The ordinary CI job must carry the same producing candidate, not a stale
    # artifact from another pipeline. Manual callers supply an accepted candidate.
    value = CANDIDATE['checked_candidate'](load(candidate_path))
    if os.environ.get('CI'):
        require(os.environ.get('CI_COMMIT_BRANCH') == 'main' and os.environ.get('CI_DEFAULT_BRANCH') == 'main')
        require(value['source'] == os.environ.get('CI_COMMIT_SHA') and str(value['pipeline']) == os.environ.get('CI_PIPELINE_ID'))
    head = command(['git', 'ls-remote', '--exit-code', 'origin', 'refs/heads/main']).decode().split()
    require(len(head) == 2 and head == [value['source'], 'refs/heads/main'])
    require(not output.exists())
    before = get_deployment(namespace)
    prior = predecessor(before, namespace)
    ready(before)
    selected = successor(value, prior)
    CANDIDATE['verify_index'](selected['current']['image'], value['members'])
    # Resolve all retained digests too; selection never silently drops an old
    # identity because its image has disappeared. This is not a registry lease.
    for release in selected['retained']:
        command(['podman', 'manifest', 'inspect', release['image']])
    if check_only:
        return {'schema': 1, 'kind': 'nest_openvox_compiler_preflight', 'namespace': namespace,
                'selection': selected, 'deployed': False, 'compiler_attestation': False}
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    output.mkdir(mode=0o700)
    hiera_overlay(output, selected)
    args = ['bolt', 'plan', 'run', 'nest::eyrie::openvox::deploy', 'service=puppet', 'namespace=' + namespace,
            '--hiera-config', str((output / 'hiera.json').relative_to(ROOT))]
    # Render via the unchanged KubeCM path first. The manifest can contain private
    # resources, so it stays in the private local directory, not CI artifacts.
    manifest = output / 'rendered.yaml'
    command(args + ['render_to=' + str(manifest.relative_to(ROOT))], timeout=600, log=output / 'render')
    require(predecessor(rendered_deployment(manifest), namespace, live=False) == selected)
    result = {'schema': 1, 'kind': 'nest_openvox_compiler_rollout', 'namespace': namespace,
              'selection': selected, 'previous_selection': prior, 'rendered': True,
              'deployed': False, 'rollout_ready': False, 'compiler_attestation': False,
              'normal_catalog_accepted': False, 'retention_complete': False}
    if deploy:
        assert_same(before, get_deployment(namespace))
        command(args, timeout=3600, log=output / 'deploy')
        command(['kubectl', 'rollout', 'status', '-n', namespace, 'deployment/puppet-puppetserver', '--timeout=600s'], timeout=620, log=output / 'rollout')
        after = get_deployment(namespace)
        require(after['metadata']['uid'] == before['metadata']['uid'])
        require(predecessor(after, namespace) == selected)
        ready(after)
        result.update(deployed=True, rollout_ready=True)
    CANDIDATE['write'](output / 'receipt.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    if sys.argv[1:2] == ['--guard-chart']:
        parser.add_argument('--guard-chart', action='store_true', required=True)
        parser.add_argument('namespace', choices=('test', 'default'))
        parser.add_argument('manifest', type=Path)
        args = parser.parse_args()
        try:
            print(json.dumps(guard_chart(args.namespace, args.manifest), sort_keys=True))
            return 0
        except (OSError, ValueError, KeyError, TypeError, IndexError, RecursionError, subprocess.SubprocessError):
            print('Compiler chart would lose or change retained identities; deployment refused', file=sys.stderr)
            return 1
    parser.add_argument('candidate', type=Path)
    parser.add_argument('namespace', choices=('test', 'default'))
    parser.add_argument('output', type=Path)
    parser.add_argument('--deploy', action='store_true', help='Replace the existing immutable compiler after rendering and fresh preflight')
    parser.add_argument('--check', action='store_true', help='Read-only preflight without rendering or local output')
    args = parser.parse_args()
    try:
        output = args.output.resolve()
        require(output != ROOT and ROOT in output.parents)
        require(not (args.check and args.deploy))
        result = rollout(args.candidate, args.namespace, output, args.deploy, args.check)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, IndexError, RecursionError, subprocess.SubprocessError):
        print('Compiler rollout unavailable; preserve prior selections and inspect native service status', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
