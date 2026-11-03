#!/usr/bin/env python3
"""Explicitly wake/park only Eyrie's infrastructure test mirrors.

No namespace deletion, PVC mutation, schedule re-enablement or autosleep.
The ConfigMap is a small rollback ledger, not a controller.
"""
import argparse
import json
import subprocess
import time

NS = 'test'
LEDGER = 'infrastructure-test-power-state'
SKIP = 'ceph.rook.io/do-not-reconcile'
CLUSTERS = ('gitlab-cnpg', 'puppet-cnpg')
CEPH_RESOURCES = (('cephcluster', 'ceph-test'), ('cephfilesystem', 'ceph-test-filesystem'),
                  ('cephobjectstore', 'ceph-test-objectstore'))
PREFIXES = ('gitlab-', 'puppet-', 'registry', 'bitwarden-',
            'kube-prometheus-stack-test-', 'prometheus-kube-prometheus-stack-test-',
            'ceph-monitoring-test-', 'prometheus-ceph-monitoring-test-', 'rook-ceph-')


def kubectl(*args, data=None, namespace=NS):
    result = subprocess.run(['kubectl', '-n', namespace, *args],
                            input=None if data is None else json.dumps(data),
                            text=True, capture_output=True, timeout=650)
    if result.returncode:
        # Avoid including arbitrary application output/credentials in an exception.
        raise RuntimeError('kubectl failed: ' + ' '.join(args[:3]))
    return result.stdout


def get(kind, name=None):
    return json.loads(kubectl('get', kind, *([name] if name else []), '-o', 'json'))


def patch(kind, name, value):
    kubectl('patch', kind, name, '--type=merge', '-p', json.dumps(value))


def save(state):
    kubectl('apply', '-f', '-', data={
        'apiVersion': 'v1', 'kind': 'ConfigMap',
        'metadata': {'name': LEDGER, 'namespace': NS},
        'data': {'state.json': json.dumps(state, sort_keys=True)},
    })
    assert json.loads(get('configmap', LEDGER)['data']['state.json']) == state


def load():
    items = get('configmap')['items']
    for item in items:
        if item['metadata']['name'] == LEDGER:
            return json.loads(item['data']['state.json'])
    return None


def workloads():
    return [x for x in get('deployment,statefulset')['items']
            if x['metadata']['name'].startswith(PREFIXES)]


def scale(items, count=None):
    for x in items:
        replicas = x['replicas'] if count is None else count
        kubectl('scale', x['kind'] + '/' + x['name'], '--replicas=' + str(replicas))
        actual = get(x['kind'], x['name'])
        assert actual['spec']['replicas'] == replicas


def wait_stopped(items):
    names = {x['name'] for x in items}
    end = time.monotonic() + 600
    while time.monotonic() < end:
        live = []
        for p in get('pod')['items']:
            if p['status'].get('phase') in ('Succeeded', 'Failed'):
                continue
            for owner in p['metadata'].get('ownerReferences', []):
                if owner['name'] in names or any(owner['name'].startswith(n + '-') for n in names):
                    live.append(p['metadata']['name'])
        if not live:
            return
        time.sleep(3)
    raise RuntimeError('Selected pods did not stop cleanly; storage was not advanced')


def ready(items):
    for x in items:
        if x['replicas']:
            kubectl('rollout', 'status', x['kind'] + '/' + x['name'], '--timeout=600s')


def ceph(*args):
    return kubectl('exec', 'deploy/rook-ceph-tools', '--', 'ceph', *args)


def clean():
    status = json.loads(ceph('status', '-f', 'json'))
    assert status['fsid'] == 'a0a508d3-cffb-4d5f-aeaf-a10f02f4d79c'
    osds = status['osdmap']
    assert osds['num_osds'] == osds['num_up_osds'] == osds['num_in_osds'] == 6
    assert status['pgmap']['pgs_by_state'] and all({'active', 'clean'} <= set(x['state_name'].split('+')) <= {'active', 'clean', 'scrubbing', 'deep'} for x in status['pgmap']['pgs_by_state'])
    assert not any(status['pgmap'].get(k, 0) for k in ('degraded_objects', 'unfound_objects', 'misplaced_objects'))


def inventory():
    # Refuse unknown users of test Ceph, even outside this namespace.
    pvcs = json.loads(kubectl('get', 'pvc', '-A', '-o', 'json'))['items']
    selected = {(x['metadata']['namespace'], x['metadata']['name']) for x in pvcs if x['spec'].get('storageClassName', '').startswith('ceph-test-')}
    assert all(ns == NS for ns, _ in selected), 'Test Ceph has a PVC outside the approved namespace'
    pods = json.loads(kubectl('get', 'pods', '-A', '-o', 'json'))['items']
    for p in pods:
        if p['status'].get('phase') in ('Succeeded', 'Failed'):
            continue
        claims = [(p['metadata']['namespace'], v['persistentVolumeClaim']['claimName']) for v in p['spec'].get('volumes', []) if 'persistentVolumeClaim' in v]
        if selected.intersection(claims):
            assert p['metadata']['namespace'] == NS and p['metadata']['name'].startswith('bitwarden-'), 'Unknown test Ceph PVC consumer'
    for j in get('job')['items']:
        if not j['metadata']['name'].startswith('joyride-'):
            assert not j.get('status', {}).get('active', 0), 'An infrastructure test Job is active'
    assert not get('hpa')['items'], 'Review new HPA ownership before parking'
    assert all(x['spec'].get('suspend', False) for x in get('cronjob')['items'] if not x['metadata']['name'].startswith('joyride-')), 'Suspend infrastructure schedules deliberately before parking'


CSI_NS = 'rook-ceph'
CSI_DRIVERS = ('rook-ceph.cephfs.csi.ceph.com', 'rook-ceph.rbd.csi.ceph.com')


def csi_quiet_inventory():
    """Refuse visible attach, mount, provision, delete and resize transitions."""
    attachments = json.loads(kubectl('get', 'volumeattachment', '-o', 'json', namespace=CSI_NS))['items']
    attachments = [x for x in attachments if x['spec']['attacher'] in CSI_DRIVERS]
    assert all(x.get('status', {}).get('attached') and not x['metadata'].get('deletionTimestamp')
               and not x.get('status', {}).get('attachError') and not x.get('status', {}).get('detachError')
               for x in attachments), 'A CSI operation is pending or terminating'
    classes = json.loads(kubectl('get', 'storageclass', '-o', 'json', namespace=CSI_NS))['items']
    classes = {x['metadata']['name'] for x in classes if x['provisioner'] in CSI_DRIVERS}
    claims = json.loads(kubectl('get', 'pvc', '-A', '-o', 'json', namespace=CSI_NS))['items']
    claims = [x for x in claims if x['spec'].get('storageClassName') in classes]
    assert all(x['status']['phase'] == 'Bound' and not x['metadata'].get('deletionTimestamp')
               and not x['status'].get('conditions') and x['spec']['resources']['requests']['storage'] == x['status']['capacity']['storage']
               for x in claims), 'A CSI operation is provisioning, deleting or resizing a claim'
    identities = {(x['metadata']['namespace'], x['metadata']['name']) for x in claims}
    pods = json.loads(kubectl('get', 'pod', '-A', '-o', 'json', namespace=CSI_NS))['items']
    consumers = []
    for p in pods:
        if p['status']['phase'] in ('Succeeded', 'Failed'):
            continue
        volumes = [(p['metadata']['namespace'], v['persistentVolumeClaim']['claimName'])
                   for v in p['spec'].get('volumes', []) if 'persistentVolumeClaim' in v]
        if identities.intersection(volumes):
            assert p['status']['phase'] == 'Running' and not p['metadata'].get('deletionTimestamp'), 'A CSI operation is mounting or unmounting a consumer'
            consumers.append([p['metadata']['uid'], p['spec']['nodeName'], sorted(volumes)])
    return {'attachments': sorted(x['metadata']['uid'] for x in attachments),
            'claims': sorted([x['metadata']['uid'], x['spec']['volumeName']] for x in claims),
            'consumers': sorted(consumers)}


def production_clean():
    status = json.loads(kubectl('exec', 'deploy/rook-ceph-tools', '--', 'ceph', 'status', '-f', 'json', namespace=CSI_NS))
    assert status['fsid'] == '5db61f8c-b0db-450a-b387-fa8718630ae8', 'Unexpected production cluster'
    osds = status['osdmap']
    assert osds['num_osds'] > 0 and osds['num_osds'] == osds['num_up_osds'] == osds['num_in_osds'], 'Production OSD unavailable'
    assert status['pgmap']['pgs_by_state'] and all({'active', 'clean'} <= set(x['state_name'].split('+')) <= {'active', 'clean', 'scrubbing', 'deep'} for x in status['pgmap']['pgs_by_state']), 'Production PG unavailable or recovering'
    assert not any(status['pgmap'].get(k, 0) for k in ('degraded_objects', 'unfound_objects', 'misplaced_objects')), 'Production replicas not settled'


def test_monitor_ips():
    services = json.loads(kubectl('get', 'service', '-l', 'app=rook-ceph-mon', '-o', 'json'))['items']
    ips = sorted(x['spec']['clusterIP'] for x in services)
    assert ips and all('.' in ip for ip in ips), 'Review non-IPv4 or absent TEST monitors'
    return ips


def csi_pods():
    pods = json.loads(kubectl('get', 'pod', '-o', 'json', namespace=CSI_NS))['items']
    selected = [p for p in pods if p['metadata'].get('labels', {}).get('app') in
                [d + suffix for d in CSI_DRIVERS for suffix in ('-nodeplugin', '-ctrlplugin')]]
    assert selected, 'Shared CSI drivers not found'
    for p in selected:
        assert not p['metadata'].get('deletionTimestamp') and all(x.get('ready') for x in p['status'].get('containerStatuses', [])) and p['status'].get('containerStatuses'), 'CSI rollout or unavailable plugin'
        assert any(x.get('controller') and x['kind'] in ('DaemonSet', 'ReplicaSet') for x in p['metadata'].get('ownerReferences', [])), 'CSI pod has no managed replacement'
    return selected


# Read only process-owned sockets and mount identities, never Ceph credentials
# or mount options. Kernel CephFS/krbd mounts survive CSI process replacement;
# userspace fuse/nbd clients explicitly do not qualify for that safety contract.
CSI_PROBE = r'''
import json, os, socket, sys
from pathlib import Path
cgroup = Path('/proc/self/cgroup').read_text()
processes = []
for entry in Path('/proc').iterdir():
    if entry.name.isdigit():
        try:
            if (entry / 'comm').read_text().strip() == 'cephcsi' and (entry / 'cgroup').read_text() == cgroup:
                processes.append(entry)
        except (FileNotFoundError, PermissionError):
            pass
assert len(processes) == 1, 'Resolve exactly one cephcsi process in this container cgroup'
proc = processes[0]
ips = set(json.loads(sys.argv[1]))
inodes = set()
for fd in (proc / 'fd').iterdir():
    try:
        target = os.readlink(fd)
    except FileNotFoundError:
        continue
    if target.startswith('socket:['):
        inodes.add(target[8:-1])
connections = []
for line in (proc / 'net/tcp').read_text().splitlines()[1:]:
    fields = line.split()
    if fields[9] in inodes:
        addr, port = fields[2].split(':')
        ip = socket.inet_ntoa(bytes.fromhex(addr)[::-1])
        if ip in ips:
            connections.append([ip, int(port, 16), fields[3]])
mounts = []
for line in (proc / 'mountinfo').read_text().splitlines():
    first, last = line.split(' - ')
    fstype, source = last.split()[:2]
    assert fstype not in ('fuse.ceph-fuse', 'fuse.rbd-nbd'), 'Userspace Ceph mount requires separate review'
    if fstype == 'ceph' or source.startswith('/dev/rbd'):
        mounts.append([first.split()[4], fstype, source])
for entry in Path('/proc').iterdir():
    if entry.name.isdigit():
        try:
            assert (entry / 'comm').read_text().strip() not in ('ceph-fuse', 'rbd-nbd'), 'Userspace Ceph client requires separate review'
        except FileNotFoundError:
            pass
print(json.dumps({'test_sockets': sorted(connections), 'mounts': sorted(mounts)}))
'''


def csi_probe(pod, ips):
    containers = [c for c in pod['spec']['containers'] if c['name'] in ('csi-cephfsplugin', 'csi-rbdplugin')]
    assert len(containers) == 1, 'Unexpected CSI container identity'
    container = containers[0]
    assert any(a in ('--type=cephfs', '--type=rbd') for a in container.get('args', [])), 'Unexpected driver type'
    return json.loads(kubectl('exec', pod['metadata']['name'], '-c', container['name'], '--', 'python3', '-c', CSI_PROBE, json.dumps(ips), namespace=CSI_NS))


def drain_csi_clients():
    """A cache-release barrier before deliberately removing TEST monitors."""
    before = csi_quiet_inventory()
    # Allow the configured 150-second CSI request deadline to drain. This is a
    # storage transition barrier, not a guarantee against future concurrent work;
    # operators must retain the documented single lifecycle/deployment lane.
    print('Waiting for the CSI request deadline before releasing TEST clients', flush=True)
    time.sleep(150)
    assert csi_quiet_inventory() == before, 'CSI consumer inventory changed during drain'
    production_clean()
    ips = test_monitor_ips()
    pods = csi_pods()
    observations = {p['metadata']['uid']: csi_probe(p, ips) for p in pods}
    for pod in pods:
        if not observations[pod['metadata']['uid']]['test_sockets']:
            continue
        assert csi_quiet_inventory() == before, 'CSI consumer inventory changed before eviction'
        production_clean()
        name = pod['metadata']['name']
        uid = pod['metadata']['uid']
        owner = next(x['uid'] for x in pod['metadata']['ownerReferences'] if x.get('controller'))
        print('Releasing retained TEST client in ' + name, flush=True)
        # Eviction honors PDBs, normal termination and exact UID preconditions.
        # Do not edit driver templates, scale the shared drivers or unmount data.
        kubectl('create', '--raw=/api/v1/namespaces/' + CSI_NS + '/pods/' + name + '/eviction', '-f', '-',
                data={'apiVersion': 'policy/v1', 'kind': 'Eviction',
                      'metadata': {'name': name, 'namespace': CSI_NS},
                      'deleteOptions': {'preconditions': {'uid': uid}}}, namespace=CSI_NS)
        end = time.monotonic() + 600
        while True:
            current = json.loads(kubectl('get', 'pod', '-o', 'json', namespace=CSI_NS))['items']
            replacement = [p for p in current if p['metadata']['uid'] not in observations
                           and any(x.get('controller') and x['uid'] == owner for x in p['metadata'].get('ownerReferences', []))
                           and (not pod['metadata']['labels']['app'].endswith('-nodeplugin') or p['spec'].get('nodeName') == pod['spec']['nodeName'])
                           and not p['metadata'].get('deletionTimestamp')
                           and p['status'].get('containerStatuses') and all(x.get('ready') for x in p['status']['containerStatuses'])]
            if not any(p['metadata']['uid'] == uid for p in current) and len(replacement) == 1:
                new = replacement[0]
                observed = csi_probe(new, ips)
                assert not observed['test_sockets'], 'Replacement recreated TEST clients; do not park'
                assert observed['mounts'] == observations[uid]['mounts'], 'Mounted data paths changed'
                observations[new['metadata']['uid']] = observed
                break
            assert time.monotonic() < end, 'CSI replacement did not become ready; do not park'
            time.sleep(3)
    assert csi_quiet_inventory() == before, 'CSI consumer inventory changed after drain'
    for pod in csi_pods():
        observed = csi_probe(pod, ips)
        assert not observed['test_sockets'], 'TEST native clients remain; do not park monitors'
        assert observed['mounts'] == observations[pod['metadata']['uid']]['mounts'], 'Mounted data paths changed'
    production_clean()
    print('TEST native CSI clients released; shared drivers and kernel mounts preserved', flush=True)


def capture():
    inventory()
    clean()
    # Fail closed if a test GitLab build or worker is in progress.
    result = kubectl('exec', 'deploy/gitlab-toolbox', '-c', 'toolbox', '--',
                     'gitlab-rails', 'runner',
                     'abort("active work") if Ci::Build.where(status: ["running", "pending", "preparing", "waiting_for_resource"]).exists? || Sidekiq::Workers.new.size > 0 || Sidekiq::Queue.all.sum(&:size) > 0; puts "idle"')
    assert result.strip() == 'idle'
    items = workloads()
    assert items and any(x['metadata']['name'] == 'rook-ceph-mon-a' for x in items)
    return {'phase': 'parking', 'workloads': [
        {'kind': x['kind'].lower(), 'name': x['metadata']['name'],
         'replicas': x['spec'].get('replicas', 1),
         'skip': x['metadata'].get('labels', {}).get(SKIP)} for x in items],
        'prometheus': {x['metadata']['name']: x['spec'].get('paused', False) for x in get('prometheus')['items']},
        'scheduledbackups': {x['metadata']['name']: x['spec'].get('suspend', False) for x in get('scheduledbackup')['items'] if x['spec'].get('cluster', {}).get('name') in CLUSTERS},
        'cronjobs': {x['metadata']['name']: x['spec'].get('suspend', False) for x in get('cronjob')['items']},
        'noout': 'noout' in json.loads(ceph('osd', 'dump', '-f', 'json'))['flags'].split(','),
        'pvcs': {x['metadata']['name']: [x['metadata']['uid'], x['spec'].get('volumeName')] for x in get('pvc')['items']}}


def assert_data(state):
    current = {x['metadata']['name']: [x['metadata']['uid'], x['spec'].get('volumeName')] for x in get('pvc')['items']}
    assert all(current.get(k) == v for k, v in state['pvcs'].items()), 'Persistent volume identity changed'
    for x in get('cronjob')['items']:
        name = x['metadata']['name']
        if name in state['cronjobs']:
            assert x['spec'].get('suspend', False) == state['cronjobs'][name], 'CronJob intent changed'


def stop(state):
    if state is None:
        state = capture()
        save(state)
    elif state['phase'] == 'awake':
        # Take a new inventory after an upgrade: names and replica intent may change.
        state = capture()
        save(state)
    if state['phase'] == 'asleep':
        assert_data(state)
        print('Infrastructure mirrors are already parked')
        return
    assert state['phase'] == 'parking', 'Finish the current wake before parking'
    for name in state['scheduledbackups']:
        patch('scheduledbackup', name, {'spec': {'suspend': True}})
    apps = [x for x in state['workloads'] if not x['name'].startswith(('rook-ceph-', 'prometheus-', 'ceph-monitoring-test-', 'kube-prometheus-stack-test-')) and x['name'] not in ('gitlab-valkey', 'bitwarden-mariadb')]
    scale(apps, 0)
    wait_stopped(apps)
    for name in CLUSTERS:
        kubectl('annotate', 'cluster', name, 'cnpg.io/hibernation=on', '--overwrite')
        kubectl('wait', 'cluster/' + name, '--for=condition=cnpg.io/hibernation', '--timeout=600s')
    databases = [x for x in state['workloads'] if x['name'] in ('gitlab-valkey', 'bitwarden-mariadb')]
    scale(databases, 0)
    wait_stopped(databases)
    inventory()
    clean()
    sessions = json.loads(ceph('tell', 'mds.ceph-test-filesystem-a', 'client', 'ls', '-f', 'json'))
    managers = {p['metadata']['name'] for p in get('pod')['items'] if p['metadata'].get('labels', {}).get('app') == 'rook-ceph-mgr'}
    assert all(s.get('auth_name', {}).get('type') == 16 and s.get('client_metadata', {}).get('hostname') in managers and not s.get('requests_in_flight') for s in sessions), 'External CephFS clients remain mounted'
    images = json.loads(kubectl('exec', 'deploy/rook-ceph-tools', '--', 'rbd', 'ls', 'ceph-test-blockpool', '--format', 'json'))
    for image in images:
        status = json.loads(kubectl('exec', 'deploy/rook-ceph-tools', '--', 'rbd', 'status', 'ceph-test-blockpool/' + image, '--format', 'json'))
        assert not status.get('watchers'), 'A test RBD client remains connected'
    # Kernel mounts are gone, but CSI's native control clients can outlive them.
    # Release those clients while monitors are still reachable, not after the
    # reconnect loop has already started. Keep production drivers/mappings intact.
    drain_csi_clients()
    if not state['noout']:
        ceph('osd', 'set', 'noout')
    # Rook checks daemon deployment labels in its independent health loops.
    # Label both CRs and every daemon; never scale the shared production operator.
    for kind, name in CEPH_RESOURCES:
        kubectl('label', kind, name, SKIP + '=true', '--overwrite')
    storage = [x for x in state['workloads'] if x['name'].startswith('rook-ceph-')]
    for x in storage:
        kubectl('label', x['kind'], x['name'], SKIP + '=true', '--overwrite')
    for name in state['prometheus']:
        patch('prometheus', name, {'spec': {'paused': True}})
    monitoring = [x for x in state['workloads'] if x['name'].startswith(('prometheus-', 'ceph-monitoring-test-', 'kube-prometheus-stack-test-'))]
    scale(monitoring, 0)
    wait_stopped(monitoring)
    for prefixes in (('rook-ceph-rgw-',), ('rook-ceph-mgr-',), ('rook-ceph-mds-',), ('rook-ceph-osd-',), ('rook-ceph-mon-',), ('rook-ceph-tools', 'rook-ceph-exporter-', 'rook-ceph-crashcollector-')):
        group = [x for x in storage if x['name'].startswith(prefixes)]
        scale(group, 0)
        wait_stopped(group)
    state['phase'] = 'asleep'
    assert_data(state)
    save(state)
    print('Parked infrastructure mirrors; Joyride, ingress, certificate services and jump retained')


def verify():
    clean()
    for name in CLUSTERS:
        kubectl('wait', 'cluster/' + name, '--for=condition=Ready', '--timeout=600s')
    ready([{'kind': x['kind'].lower(), 'name': x['metadata']['name'], 'replicas': x['spec'].get('replicas', 1)} for x in workloads()])
    for url in ('https://gitlab-test.eyrie/-/readiness?all=1',
                'https://puppetdb-test.eyrie/status/v1/services',
                'https://grafana-test.eyrie/api/health'):
        subprocess.run(['curl', '--fail', '--silent', '--show-error', '--max-time', '30', '--output', '/dev/null', url], check=True)


def start(state):
    if state is None and not get('cephcluster')['items']:
        print('Infrastructure test mirrors are not initialized; continue normal deployment')
        return
    if state is None or state['phase'] == 'awake':
        verify()
        print('Infrastructure mirrors are awake and dependencies verified')
        return
    assert state['phase'] in ('asleep', 'waking'), 'Incomplete park requires diagnosis, not generic wake'
    state['phase'] = 'waking'
    save(state)
    storage = [x for x in state['workloads'] if x['name'].startswith('rook-ceph-')]
    for prefixes in (('rook-ceph-mon-', 'rook-ceph-tools'), ('rook-ceph-osd-',), ('rook-ceph-mgr-',), ('rook-ceph-mds-', 'rook-ceph-rgw-', 'rook-ceph-exporter-', 'rook-ceph-crashcollector-')):
        group = [x for x in storage if x['name'].startswith(prefixes)]
        scale(group)
        ready(group)
    end = time.monotonic() + 600
    while True:
        try:
            clean()
            break
        except (AssertionError, RuntimeError):
            if time.monotonic() > end:
                raise
            time.sleep(5)
    if not state['noout']:
        ceph('osd', 'unset', 'noout')
    for x in storage:
        kubectl('label', x['kind'], x['name'], SKIP + '-' if x['skip'] is None else SKIP + '=' + x['skip'], '--overwrite')
    for kind, name in CEPH_RESOURCES:
        kubectl('label', kind, name, SKIP + '-')
    monitoring = [x for x in state['workloads'] if x['name'].startswith(('prometheus-', 'ceph-monitoring-test-', 'kube-prometheus-stack-test-'))]
    scale(monitoring)
    for name, paused in state['prometheus'].items():
        patch('prometheus', name, {'spec': {'paused': paused}})
    ready(monitoring)
    for name in CLUSTERS:
        kubectl('annotate', 'cluster', name, 'cnpg.io/hibernation=off', '--overwrite')
        kubectl('wait', 'cluster/' + name, '--for=condition=Ready', '--timeout=600s')
    databases = [x for x in state['workloads'] if x['name'] in ('gitlab-valkey', 'bitwarden-mariadb')]
    scale(databases)
    ready(databases)
    apps = [x for x in state['workloads'] if x not in storage + monitoring + databases]
    scale(apps)
    ready(apps)
    # Restore only the backup schedules we suspended. CronJobs are never resumed.
    for name, suspend in state['scheduledbackups'].items():
        patch('scheduledbackup', name, {'spec': {'suspend': suspend}})
    assert_data(state)
    verify()
    state['phase'] = 'awake'
    save(state)
    print('Infrastructure mirrors awake; original CronJob suspension policy preserved')


def main():
    if not __debug__:
        raise RuntimeError('Safety checks require Python without optimization')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('start', 'stop', 'status'))
    args = parser.parse_args()
    state = load()
    if args.action == 'start':
        start(state)
    elif args.action == 'stop':
        stop(state)
    else:
        print('unmanaged/awake' if state is None else state['phase'])


if __name__ == '__main__':
    main()
