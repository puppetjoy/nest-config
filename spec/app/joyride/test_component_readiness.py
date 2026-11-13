"""TEST component selector regression; no live cluster or private graph access."""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[3]


KEYS = ('worker', 'app', 'internal_web_app', 'ops_app', 'trusted_test_app')


def load_resources():
    rendered = os.environ.get('JOYRIDE_RENDER')
    if rendered:
        rows = list(yaml.safe_load_all(Path(rendered).read_text()))
        names = {(r['kind'], r['metadata']['name']): r for r in rows if r}
        return {**{key: names['Deployment', name] for key, name in zip(KEYS, (
            'joyride-test-worker', 'joyride-test', 'joyride-test-internal-web', 'joyride-test-ops', 'joyride-test-trusted-test'))},
            **{key: names['Service', name] for key, name in [('web', 'joyride-test-web'), ('internal_web', 'joyride-test-internal-web'),
                                                          ('ops', 'joyride-test-ops'), ('trusted_test', 'joyride-test-trusted-test')]}}
    return yaml.safe_load((ROOT / 'data/kubernetes/app/joyride/test.yaml').read_text())['resources']


class ComponentReadiness(unittest.TestCase):
    def test_each_service_has_exactly_one_listener_workload(self):
        resources = load_resources()
        deployments = [r for r in resources.values() if r.get('kind') == 'Deployment']
        selected = {}
        for key, component in [('web', 'web'), ('internal_web', 'internal-web'),
                               ('ops', 'ops'), ('trusted_test', 'trusted-test')]:
            service = resources[key]
            selector = service['spec']['selector']
            matches = [d for d in deployments if all(
                d['spec']['template']['metadata']['labels'].get(k) == v for k, v in selector.items())]
            self.assertEqual(len(matches), 1, component)
            containers = matches[0]['spec']['template']['spec']['containers']
            self.assertEqual([c['name'] for c in containers], [component])
            self.assertNotIn('publishNotReadyAddresses', service['spec'])
            selected[component] = matches[0]['metadata']['name']
        self.assertEqual(len(set(selected.values())), 4)


    def test_routing_listeners_reserve_measured_health_capacity(self):
        # Paired with application one-expensive-dispatch-per-process admission.
        # Thread count alone does not certify HTTP latency or live availability.
        data = load_resources()
        for key in KEYS[1:]:
            container, = data[key]['spec']['template']['spec']['containers']
            command = container['command']
            self.assertEqual(command[command.index('--workers') + 1], '2')
            if container['name'] in ('internal-web', 'trusted-test'):
                self.assertEqual(command[command.index('--threads') + 1] if '--threads' in command else None, '3')
            else:
                self.assertNotIn('--threads', command)

    def test_owner_route_loading_has_regional_graph_memory_headroom(self):
        # The fixed graph is 1.23 GB before two worker runtimes and file cache.
        # A 768 MiB cap stalled both readers in CephFS faults while admission
        # stayed occupied; reserve capacity as well as lifting the hard limit.
        data = load_resources()
        container, = data['internal_web_app']['spec']['template']['spec']['containers']
        self.assertEqual(container['resources']['limits']['memory'], '2Gi')
        self.assertEqual(container['resources']['requests']['memory'], '1Gi')

    def test_owner_routing_stages_verified_graph_before_serving_locally(self):
        data = load_resources()
        pod = data['internal_web_app']['spec']['template']['spec']
        self.assertEqual([c['name'] for c in pod['initContainers']], ['wait-bootstrap', 'cache-routing-graph'])
        cache = pod['initContainers'][1]
        self.assertEqual(cache['command'], ['python', '-B', '/graph-cache-tools/cache_routing_graph.py'])
        self.assertTrue(next(m for m in cache['volumeMounts'] if m['name'] == 'data')['readOnly'])
        container, = pod['containers']
        command = container['command']
        self.assertEqual(command[command.index('--env') + 1], 'ROUTING_GRAPH_PATH=/routing-cache/graph.sqlite3')
        self.assertTrue(next(m for m in container['volumeMounts'] if m['name'] == 'routing-cache')['readOnly'])
        volume = next(v for v in pod['volumes'] if v['name'] == 'routing-cache')
        self.assertEqual(volume['emptyDir'], {'sizeLimit': '2Gi'})
        self.assertNotIn('envFrom', cache)

    def test_private_content_staging_follows_each_split_writer(self):
        data = load_resources()
        for key in KEYS:
            tmp, = [v for v in data[key]['spec']['template']['spec']['volumes'] if v['name'] == 'tmp']
            expected = '2Gi' if key in ('worker', 'ops_app', 'trusted_test_app') else '1Gi'
            self.assertEqual(tmp['emptyDir']['sizeLimit'], expected, key)

    def test_readiness_failure_only_withdraws_its_own_service_endpoints(self):
        # Render-level EndpointSlice predicate: exact selector AND Pod Ready.
        # No cluster controller is emulated or claimed to have been exercised.
        data = load_resources()
        pods = {k: data[k]['spec']['template'] for k in KEYS}
        services = ('web', 'internal_web', 'ops', 'trusted_test')
        for failed in KEYS:
            actual = {}
            for service in services:
                selector = data[service]['spec']['selector']
                actual[service] = [k for k, p in pods.items() if k != failed and all(
                    p['metadata']['labels'].get(label) == value for label, value in selector.items())]
            expected_lost = {'app': 'web', 'internal_web_app': 'internal_web',
                             'ops_app': 'ops', 'trusted_test_app': 'trusted_test'}.get(failed)
            self.assertEqual([s for s in services if not actual[s]], [expected_lost] if expected_lost else [])

    def test_bootstrap_is_single_owned_and_readers_wait_read_only(self):
        data = load_resources()
        worker = data['worker']['spec']['template']['spec']
        expected = ['migrate', 'provision-owner', 'basemap', 'curated-fetch', 'curated-import', 'routing-graph', 'bootstrap-complete']
        self.assertEqual([c['name'] for c in worker['initContainers']], expected)
        self.assertEqual([c['name'] for c in worker['containers']], ['worker'])
        completion = worker['initContainers'][-1]
        self.assertEqual(completion['command'][-1], 'publish')
        for key in KEYS[1:]:
            pod = data[key]['spec']['template']['spec']
            gate = pod['initContainers'][0]
            self.assertEqual([c['name'] for c in pod['initContainers']],
                             ['wait-bootstrap', 'cache-routing-graph'] if key == 'internal_web_app' else ['wait-bootstrap'])
            self.assertEqual(gate['name'], 'wait-bootstrap')
            self.assertEqual(gate['command'][-1], 'wait')
            self.assertEqual(gate['env'], completion['env'])
            self.assertNotIn('livenessProbe', gate)
            self.assertNotIn('envFrom', gate)
            self.assertTrue(next(m for m in gate['volumeMounts'] if m['name'] == 'data')['readOnly'])
            self.assertFalse(any(v['name'] in ('curated-input', 'package-reader', 'pull') for v in pod['volumes']))
        # Recipe hash maintenance is checked against raw source, not expanded Hiera.
        source = yaml.safe_load((ROOT / 'data/kubernetes/app/joyride/test.yaml').read_text())['resources']
        inits = source['worker']['spec']['template']['spec']['initContainers']
        digest = hashlib.sha256(json.dumps(inits[:-1], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.assertEqual(inits[-1]['env'][0]['value'], digest)

    def test_readers_cannot_write_bootstrap_receipt_location(self):
        from pathlib import PurePosixPath
        receipt = PurePosixPath('/data/.bootstrap/receipt')
        for key in KEYS[1:]:
            pod = load_resources()[key]['spec']['template']['spec']
            for container in pod['initContainers'] + pod['containers']:
                # Most-specific mount governs the receipt, including nested ops
                # private writes. Same UID does not bypass a read-only mount.
                covering = [m for m in container['volumeMounts'] if PurePosixPath(m['mountPath']) in receipt.parents]
                effective = max(covering, key=lambda m: len(PurePosixPath(m['mountPath']).parts))
                self.assertTrue(effective.get('readOnly'), (key, container['name']))
        # Pin the actual implementation location, not a hypothetical protected path.
        program = (ROOT / 'files/app/joyride/bootstrap_gate.py').read_text()
        self.assertIn("Path('/data/.bootstrap')", program)

    def test_bootstrap_receipt_requires_exact_revision_recipe_and_installer(self):
        spec = importlib.util.spec_from_file_location('bootstrap_gate', ROOT / 'files/app/joyride/bootstrap_gate.py')
        assert spec is not None and spec.loader is not None
        gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gate)
        with TemporaryDirectory() as temporary, patch.dict(os.environ, {'ROUTING_INSTALLER_SHA256': 'c' * 64}):
            root = Path(temporary)
            path = gate.receipt_path(root, 'a' * 40, 'b' * 64)
            self.assertFalse(gate.ready(path))
            gate.publish(path)
            self.assertTrue(gate.ready(path))
            self.assertFalse(gate.ready(gate.receipt_path(root, 'd' * 40, 'b' * 64)))
            self.assertFalse(gate.ready(gate.receipt_path(root, 'a' * 40, 'e' * 64)))
            with patch.dict(os.environ, {'ROUTING_INSTALLER_SHA256': 'f' * 64}):
                self.assertFalse(gate.ready(gate.receipt_path(root, 'a' * 40, 'b' * 64)))
            with self.assertRaises(ValueError):
                gate.receipt_path(root, 'not recorded', 'b' * 64)
            with self.assertRaises(OSError), patch.object(gate.os, 'replace', side_effect=OSError('fixture interruption')):
                gate.publish(path)
            gate.publish(path)  # Retry after interrupted rename must succeed.
            self.assertTrue(gate.ready(path))
            self.assertEqual(list(root.iterdir()), [path])
            gate.publish(path)  # Compatible rolling surge is idempotent.
            self.assertTrue(gate.ready(path))


if __name__ == '__main__':
    unittest.main()
