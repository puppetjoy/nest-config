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
