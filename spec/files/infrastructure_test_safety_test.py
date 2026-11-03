#!/usr/bin/env python3
"""Isolated safety checks: no Kubernetes or network calls escape these fixtures."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('infrastructure_test', Path(__file__).resolve().parents[2] / 'scripts/infrastructure_test.py')
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


class InfrastructureTestSafety(unittest.TestCase):
    def test_only_explicit_mirrors_selected(self):
        names = ['joyride-test', 'joyride-test-access', 'jump', 'ingress-test-contour',
                 'cert-manager-test', 'gitlab-webservice-default', 'puppet-puppetserver',
                 'rook-ceph-mon-a', 'registry', 'bitwarden-mariadb']
        data = {'items': [{'metadata': {'name': n}} for n in names]}
        with patch.object(m, 'get', return_value=data):
            self.assertEqual([x['metadata']['name'] for x in m.workloads()], names[5:])

    def test_rejects_foreign_test_storage_consumer(self):
        pvc = {'metadata': {'namespace': 'another', 'name': 'data'}, 'spec': {'storageClassName': 'ceph-test-block'}}
        with patch.object(m, 'kubectl', return_value=m.json.dumps({'items': [pvc]})):
            with self.assertRaisesRegex(AssertionError, 'outside'):
                m.inventory()

    def test_production_same_named_claim_is_not_test_storage_consumer(self):
        pvc = {'metadata': {'namespace': 'test', 'name': 'data'}, 'spec': {'storageClassName': 'ceph-test-block'}}
        pod = {'metadata': {'namespace': 'default', 'name': 'important-production'},
               'status': {'phase': 'Running'}, 'spec': {'volumes': [{'persistentVolumeClaim': {'claimName': 'data'}}]}}
        with patch.object(m, 'kubectl', side_effect=[m.json.dumps({'items': [pvc]}), m.json.dumps({'items': [pod]})]), patch.object(m, 'get', return_value={'items': []}):
            m.inventory()

    def test_rejects_live_unknown_test_pvc_user(self):
        pvc = {'metadata': {'namespace': 'test', 'name': 'data'}, 'spec': {'storageClassName': 'ceph-test-block'}}
        pod = {'metadata': {'namespace': 'test', 'name': 'important-new-test'},
               'status': {'phase': 'Running'}, 'spec': {'volumes': [{'persistentVolumeClaim': {'claimName': 'data'}}]}}
        with patch.object(m, 'kubectl', side_effect=[m.json.dumps({'items': [pvc]}), m.json.dumps({'items': [pod]})]):
            with self.assertRaisesRegex(AssertionError, 'Unknown'):
                m.inventory()

    def test_resume_does_not_change_cronjob_intent(self):
        source = Path(m.__file__).read_text()
        self.assertNotIn("patch('cronjob'", source)
        self.assertNotIn("'suspend': False", source)
        self.assertNotIn("'delete'", source)

    def test_test_cluster_allows_clean_scrubs_but_refuses_recovery(self):
        status = {'fsid': 'a0a508d3-cffb-4d5f-aeaf-a10f02f4d79c',
                  'osdmap': {'num_osds': 6, 'num_up_osds': 6, 'num_in_osds': 6},
                  'pgmap': {'pgs_by_state': [{'state_name': 'active+clean+scrubbing+deep'}]}}
        with patch.object(m, 'ceph', side_effect=lambda *args: m.json.dumps(status)):
            m.clean()
            for state in ('active+degraded', 'active+clean+remapped', 'peering'):
                status['pgmap']['pgs_by_state'][0]['state_name'] = state
                with self.assertRaises(AssertionError):
                    m.clean()

    def test_native_client_barrier_precedes_monitor_shutdown(self):
        state = {'phase': 'parking', 'noout': True, 'prometheus': {}, 'scheduledbackups': {},
                 'workloads': [{'name': 'rook-ceph-mon-a', 'kind': 'deployment', 'replicas': 1, 'skip': None}]}
        events = []
        def command(*args, **kwargs):
            if 'rbd' in args:
                return '[]'
            return ''
        with patch.object(m, 'kubectl', side_effect=command), patch.object(m, 'save'), patch.object(m, 'scale', side_effect=lambda items, count=None: events.extend(('stop', x['name']) for x in items)), patch.object(m, 'wait_stopped'), patch.object(m, 'inventory'), patch.object(m, 'clean'), patch.object(m, 'ceph', return_value='[]'), patch.object(m, 'get', return_value={'items': []}), patch.object(m, 'patch'), patch.object(m, 'assert_data'), patch.object(m, 'drain_csi_clients', create=True, side_effect=lambda: events.append(('barrier',))):
            m.stop(state)
        self.assertIn(('barrier',), events, 'Native TEST clients must be released before monitors disappear')
        self.assertLess(events.index(('barrier',)), events.index(('stop', 'rook-ceph-mon-a')))

    def test_csi_inventory_tracks_driver_identity_not_class_name(self):
        claim = {'metadata': {'namespace': 'default', 'name': 'data', 'uid': 'claim'},
                 'spec': {'storageClassName': 'custom-alias', 'volumeName': 'pv',
                          'resources': {'requests': {'storage': '1Gi'}}},
                 'status': {'phase': 'Bound', 'capacity': {'storage': '1Gi'}}}
        def command(*args, **kwargs):
            items = {'storageclass': [{'metadata': {'name': 'custom-alias'}, 'provisioner': m.CSI_DRIVERS[0]}],
                     'pvc': [claim]}.get(args[1], [])
            return m.json.dumps({'items': items})
        with patch.object(m, 'kubectl', side_effect=command):
            self.assertEqual(m.csi_quiet_inventory()['claims'], [['claim', 'pv']])

    def test_csi_recycle_refuses_unattached_or_terminating_volume(self):
        for status, deleting in (({'attached': False}, False), ({'attached': True}, True)):
            attachment = {'spec': {'attacher': 'rook-ceph.rbd.csi.ceph.com'}, 'status': status,
                          'metadata': {'deletionTimestamp': 'now'} if deleting else {}}
            def command(*args, **kwargs):
                return m.json.dumps({'items': [attachment] if 'volumeattachment' in args else []})
            with patch.object(m, 'kubectl', side_effect=command):
                with self.assertRaisesRegex(AssertionError, 'CSI operation'):
                    m.csi_quiet_inventory()

    def test_csi_barrier_refuses_changed_consumer_inventory(self):
        with patch.object(m, 'csi_quiet_inventory', side_effect=[{'claims': ['before']}, {'claims': ['after']}]), patch.object(m.time, 'sleep'), patch.object(m, 'kubectl') as command:
            with self.assertRaisesRegex(AssertionError, 'changed'):
                m.drain_csi_clients()
            command.assert_not_called()

    def test_csi_barrier_does_not_restart_clients_without_test_sockets(self):
        pod = {'metadata': {'name': 'plugin', 'uid': 'uid'}, 'spec': {'nodeName': 'falcon'}}
        with patch.object(m, 'csi_quiet_inventory', return_value={}), patch.object(m.time, 'sleep'), patch.object(m, 'csi_pods', create=True, return_value=[pod]), patch.object(m, 'csi_probe', create=True, return_value={'test_sockets': [], 'mounts': []}), patch.object(m, 'production_clean', create=True), patch.object(m, 'test_monitor_ips', create=True, return_value=['10.98.208.118']), patch.object(m, 'kubectl') as command:
            m.drain_csi_clients()
            command.assert_not_called()

    def test_csi_barrier_replaces_only_retained_client_and_checks_mounts(self):
        import copy
        old = {'metadata': {'name': 'old', 'uid': 'old-uid', 'labels': {'app': 'driver-nodeplugin'},
                            'ownerReferences': [{'uid': 'daemonset', 'controller': True}]},
               'spec': {'nodeName': 'falcon'}, 'status': {'containerStatuses': [{'ready': True}]}}
        new = copy.deepcopy(old)
        new['metadata'].update(name='new', uid='new-uid')
        idle = copy.deepcopy(old)
        idle['metadata'].update(name='idle', uid='idle-uid')
        connected = {'test_sockets': [['10.98.208.118', 3300, '01']], 'mounts': [['/mount', 'ceph', 'production']]}
        drained = {'test_sockets': [], 'mounts': connected['mounts']}
        with patch.object(m, 'csi_quiet_inventory', return_value={}), patch.object(m.time, 'sleep'), patch.object(m, 'csi_pods', side_effect=[[old, idle], [new, idle]]), patch.object(m, 'csi_probe', side_effect=[connected, drained, drained, drained, drained]), patch.object(m, 'production_clean'), patch.object(m, 'test_monitor_ips', return_value=['10.98.208.118']), patch.object(m, 'kubectl', side_effect=['{}', m.json.dumps({'items': [new, idle]})]) as command:
            m.drain_csi_clients()
        evictions = [c for c in command.call_args_list if c.args[0] == 'create']
        self.assertEqual(len(evictions), 1)
        self.assertIn('/pods/old/eviction', evictions[0].args[1])
        self.assertEqual(evictions[0].kwargs['data']['deleteOptions']['preconditions'], {'uid': 'old-uid'})

    def test_probe_resolves_container_cgroup_not_host_pid_one(self):
        import contextlib
        import io
        import os
        import socket
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, comm, cgroup in (('self', 'python3', '0::/driver'), ('1', 'systemd', '0::/host'),
                                       ('78', 'cephcsi', '0::/driver'), ('79', 'cephcsi', '0::/other')):
                p = root / name
                p.mkdir()
                (p / 'comm').write_text(comm)
                (p / 'cgroup').write_text(cgroup)
            driver = root / '78'
            (driver / 'fd').mkdir()
            (driver / 'fd' / '3').symlink_to('socket:[123]')
            (driver / 'net').mkdir()
            address = socket.inet_aton('10.98.208.118')[::-1].hex()
            (driver / 'net' / 'tcp').write_text('header\n0: 00000000:0000 ' + address + ':0CE4 02 0 0 0 0 0 123\n')
            (driver / 'mountinfo').write_text('1 0 0:1 / /production rw - ceph client@production=/data rw\n')
            program = m.CSI_PROBE.replace("'/proc", "'" + os.fspath(root))
            output = io.StringIO()
            with patch('sys.argv', ['probe', '["10.98.208.118"]']), contextlib.redirect_stdout(output):
                exec(compile(program, '<csi-probe>', 'exec'), {})
            actual = m.json.loads(output.getvalue())
            self.assertEqual(actual['test_sockets'], [['10.98.208.118', 3300, '02']])
            self.assertEqual(actual['mounts'], [['/production', 'ceph', 'client@production=/data']])

    def test_refuses_partial_park_wake(self):
        with patch.object(m, 'kubectl') as command:
            with self.assertRaisesRegex(AssertionError, 'Incomplete park'):
                m.start({'phase': 'parking'})
            command.assert_not_called()

    def test_wake_orders_storage_database_apps(self):
        state = {'phase': 'asleep', 'noout': False, 'prometheus': {}, 'scheduledbackups': {},
                 'workloads': [{'name': n, 'kind': 'deployment', 'replicas': 1, 'skip': None}
                               for n in ('rook-ceph-mon-a', 'rook-ceph-osd-2', 'rook-ceph-mgr-a',
                                         'rook-ceph-mds-a', 'gitlab-valkey', 'gitlab-webservice-default')]}
        events = []
        with patch.object(m, 'save'), patch.object(m, 'kubectl', side_effect=lambda *a, **k: events.append(a)), patch.object(m, 'scale', side_effect=lambda items: events.extend(('scale', x['name']) for x in items)), patch.object(m, 'ready'), patch.object(m, 'clean'), patch.object(m, 'ceph'), patch.object(m, 'patch'), patch.object(m, 'assert_data'), patch.object(m, 'verify'):
            m.start(state)
        scaled = [x[1] for x in events if x[0] == 'scale']
        self.assertEqual(scaled, [x['name'] for x in state['workloads']])
        self.assertEqual(state['phase'], 'awake')


if __name__ == '__main__':
    unittest.main()
