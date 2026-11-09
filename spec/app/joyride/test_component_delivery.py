"""Exact component fleet delivery and interruption fixtures; no cluster writes."""
import copy
from pathlib import Path
import sys
import io
import json
from unittest.mock import patch
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_delivery_controller import controller, FixtureClient, OLD, NEW

NAMES = {'joyride-test-worker': 'worker', 'joyride-test': 'web',
         'joyride-test-internal-web': 'internal-web', 'joyride-test-ops': 'ops',
         'joyride-test-trusted-test': 'trusted-test'}


class FleetClient(FixtureClient):
    def __init__(self):
        super().__init__()
        self.fleet = {}
        self.order = []
        for name, component in NAMES.items():
            row = copy.deepcopy(self.deployment)
            row['metadata'].update(name=name, uid=name)
            row['spec']['selector'] = {'matchLabels': {'app': name}}
            row['spec']['template']['metadata']['labels']['app'] = name
            row['spec']['template']['metadata']['labels']['app.kubernetes.io/component'] = component
            pod = row['spec']['template']['spec']
            pod['containers'] = [{'name': component, 'image': OLD}]
            initializers = ['migrate', 'provision-owner', 'basemap', 'curated-fetch', 'curated-import',
                            'routing-graph', 'bootstrap-complete'] if component == 'worker' else ['wait-bootstrap']
            pod['initContainers'] = [{'name': n, 'image': OLD} for n in initializers]
            self.fleet[name] = row

    def get_deployments(self):
        return copy.deepcopy(self.fleet)

    def patch_deployment(self, deployment, operation):
        name = deployment['metadata']['name']
        self.deployment = self.fleet[name]
        super().patch_deployment(deployment, operation)
        self.order.append(name)
        return copy.deepcopy(self.deployment)


class ComponentDelivery(unittest.TestCase):
    def test_worker_first_then_every_reader_and_initializer_same_digest(self):
        client = FleetClient()
        self.assertEqual(controller.run_components(client, clock=lambda: 0), 'succeeded')
        self.assertEqual(client.order, list(NAMES))
        for row in client.fleet.values():
            self.assertEqual(set(controller.images(row).values()), {NEW})
        self.assertIsNone(client.journal)

    def test_partial_patch_resumes_same_operation_without_repatch(self):
        client = FleetClient()
        client.crash_after_patch = True
        with self.assertRaises(RuntimeError):
            controller.run_components(client, clock=lambda: 0)
        self.assertEqual(client.state, 'running')
        self.assertEqual(controller.run_components(client, clock=lambda: 1), 'succeeded')
        self.assertEqual(client.patches, 5)

    def test_real_patch_transport_targets_exact_named_workloads_with_cas(self):
        client = controller.Client.__new__(controller.Client)
        client.kube_token = 'fixture-only'
        client.kube_context = None
        fleet = FleetClient()
        for name, row in fleet.fleet.items():
            operation = {'uid': name, 'id': fleet.queue[0]['id'], 'image': NEW}
            with patch.object(controller, 'open_request', return_value=io.BytesIO(b'{}')) as transport:
                client.patch_deployment(row, operation)
            request = transport.call_args.args[0]
            self.assertEqual(request.full_url, 'https://kubernetes.default.svc/apis/apps/v1/namespaces/test/deployments/' + name)
            payload = json.loads(request.data)
            self.assertEqual(payload[:2], [
                {'op': 'test', 'path': '/metadata/uid', 'value': name},
                {'op': 'test', 'path': '/metadata/resourceVersion', 'value': '1'},
            ])
            images = payload[2:-1]
            expected = {'/spec/template/spec/' + group + '/' + str(i) + '/image'
                        for group in ('containers', 'initContainers')
                        for i, _ in enumerate(row['spec']['template']['spec'][group])}
            self.assertEqual({item['path'] for item in images}, expected)
            self.assertTrue(all(item['op'] == 'replace' and item['value'] == NEW for item in images))
            self.assertEqual(payload[-1]['path'], '/spec/template/metadata/annotations')

    def test_rollback_uses_same_exact_fleet_and_single_deadline(self):
        client = FleetClient()
        client.queue[0]['action'] = 'rollback'
        self.assertEqual(controller.run_components(client, clock=lambda: 0), 'succeeded')
        self.assertEqual(client.order, list(NAMES))

    def test_legacy_journal_is_preserved_and_not_claimed(self):
        client = FleetClient()
        client.journal = {**client.queue[0], 'uid': 'old-shared-pod', 'original': {}, 'deadline': 1800}
        before = copy.deepcopy(client.journal)
        with self.assertRaisesRegex(controller.DeliveryError, 'legacy_delivery_requires_idle'):
            controller.run_components(client, clock=lambda: 0)
        self.assertEqual(client.journal, before)
        self.assertEqual(client.state, 'queued')
        self.assertEqual(client.patches, 0)

    def test_reader_drift_refused_before_any_claim(self):
        client = FleetClient()
        client.fleet['joyride-test-ops']['spec']['template']['spec']['containers'].append({'name': 'extra', 'image': OLD})
        with self.assertRaisesRegex(controller.DeliveryError, 'unexpected_workload_shape'):
            controller.run_components(client, clock=lambda: 0)
        self.assertEqual(client.state, 'queued')
        self.assertEqual(client.patches, 0)

    def test_unready_worker_does_not_patch_readers_or_claim_success(self):
        client = FleetClient()
        client.fleet['joyride-test-worker']['status']['availableReplicas'] = 0
        ticks = iter([0, 0, 0, 1801])
        with self.assertRaisesRegex(controller.DeliveryError, 'rollout_deadline'):
            controller.run_components(client, clock=lambda: next(ticks), pause=lambda _: None)
        self.assertEqual(client.order, ['joyride-test-worker'])
        self.assertEqual(client.state, 'failed')


if __name__ == '__main__':
    unittest.main()
