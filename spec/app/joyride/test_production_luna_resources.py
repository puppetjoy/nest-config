"""Source-qualified Luna production resources; not live admission or deployment."""
import json
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET

import yaml

ROOT = Path(__file__).resolve().parents[3]


class LunaProductionResources(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base = yaml.safe_load((ROOT / 'data/kubernetes/app/joyride/joyride.yaml').read_text())
        overlay = yaml.safe_load((ROOT / 'data/kubernetes/service/joyride.yaml').read_text())
        cls.resources = dict(base['resources'])
        cls.resources.update(overlay['resources'])

    def test_stateless_tls_proxy_and_trusted_listener_are_role_isolated(self):
        proxy = self.resources['production_access']['spec']['template']['spec']
        self.assertIs(proxy['automountServiceAccountToken'], False)
        self.assertNotIn('serviceAccountName', proxy)
        self.assertNotIn('imagePullSecrets', proxy)
        container, = proxy['containers']
        self.assertNotIn('env', container)
        self.assertNotIn('envFrom', container)
        self.assertEqual({m['name'] for m in container['volumeMounts']}, {'config', 'tls', 'tmp'})
        self.assertTrue(all(m.get('readOnly', False) for m in container['volumeMounts'] if m['name'] in {'config', 'tls'}))
        self.assertNotIn('persistentVolumeClaim', yaml.safe_dump(proxy))
        self.assertEqual({v['name'] for v in proxy['volumes']}, {'config', 'tls', 'tmp'})
        self.assertEqual(proxy['volumes'][1]['secret']['secretName'], 'joyride-tls')
        trusted = self.resources['trusted_production']['spec']
        self.assertEqual(trusted['selector'], {'app': 'joyride-trusted-production'})
        self.assertEqual(trusted['ports'], [{'name': 'trusted', 'port': 8004, 'targetPort': 8004}])
        policy = self.resources['trusted_production_policy']['spec']
        self.assertEqual(policy['ingress'], [{'from': [{'podSelector': {'matchLabels': {'app': 'joyride-production-access'}}}], 'ports': [{'protocol': 'TCP', 'port': 8004}]}])
        ingress = self.resources['internal_web_policy']['spec']['ingress']
        self.assertEqual(len(ingress), 2)
        self.assertEqual(ingress[1]['from'], [{'podSelector': {'matchLabels': {'app': 'joyride-production-access'}}}])

    def test_exact_vip_service_source_and_source_preservation(self):
        spec = self.resources['production_access_service']['spec']
        self.assertEqual(spec['type'], 'LoadBalancer')
        self.assertEqual(spec['loadBalancerIP'], '172.21.0.3')
        self.assertIs(spec['allocateLoadBalancerNodePorts'], False)
        self.assertEqual(spec['externalTrafficPolicy'], 'Local')
        self.assertEqual(spec['loadBalancerSourceRanges'], ['172.22.4.3/32'])
        self.assertEqual(spec['selector'], {'app': 'joyride-production-access'})
        self.assertEqual(spec['ports'], [{'name': 'https', 'port': 443, 'targetPort': 8443}])
        source = (ROOT / 'files/app/joyride/production-access-nginx.conf').read_text()
        self.assertIn('allow 172.22.4.3/32;', source)
        self.assertIn('deny all;', source)
        self.assertNotIn('proxy_set_header Authorization "";', source)
        self.assertIn('location / { proxy_pass http://joyride_web; }', source)
        self.assertIn('proxy_pass_request_headers off;', source)
        self.assertIn('proxy_set_header X-Forwarded-For $remote_addr;', source)
        self.assertIn('proxy_set_header X-Real-IP $remote_addr;', source)
        self.assertNotIn('real_ip_header', source)
        self.assertIn('127.0.0.1:8001', (ROOT / 'files/app/joyride/production-ops-nginx.conf').read_text())

    def test_production_graph_bootstrap_is_init_only_and_read_only_to_pull(self):
        pod = self.resources['trusted_production_app']['spec']['template']['spec']
        self.assertEqual(pod['nodeSelector'], {'node-role.kubernetes.io/compute': ''})
        self.assertEqual(pod.get('tolerations'), [{
            'key': 'node-role.kubernetes.io/compute', 'operator': 'Exists', 'effect': 'NoSchedule'
        }])
        init, = pod['initContainers']
        runtime, = pod['containers']
        self.assertEqual(init['name'], 'routing-graph')
        self.assertEqual(init['command'], ['python', '-B', '/platform/install_routing_graph.py'])
        self.assertEqual(init['env'], [{'name': 'RUNTIME_ENV', 'value': 'production'}, {'name': 'JOYRIDE_PRODUCTION_ROUTING_BOOTSTRAP', 'value': '1'}])
        self.assertNotIn('envFrom', init)
        self.assertEqual(init['volumeMounts'][-1], {'name': 'pull', 'mountPath': '/pull', 'readOnly': True})
        self.assertNotIn('pull', {m['name'] for m in runtime['volumeMounts']})
        self.assertNotIn('JOYRIDE_PRODUCTION_ROUTING_BOOTSTRAP', [e['name'] for e in runtime['env']])
        self.assertEqual(pod['volumes'][-1], {'name': 'pull', 'secret': {'secretName': 'joyride-pull'}})
        self.assertEqual(runtime['image'], "%{lookup('joyride_image')}")
        self.assertEqual(init['image'], runtime['image'])
        for name in ('OPS_TOKEN', 'DELIVERY_TOKEN', 'TEST_TOKEN', 'GITLAB_READ_API_TOKEN'):
            self.assertNotIn(name, yaml.safe_dump(init))
            self.assertNotIn(name, yaml.safe_dump(runtime))
        base = yaml.safe_load((ROOT / 'data/kubernetes/app/joyride/joyride.yaml').read_text())['resources']['app']['spec']['template']['spec']
        base_caps = base['containers'][0]['resources']['limits']
        prod_caps = runtime['resources']['limits']
        for resource in ('memory', 'ephemeral-storage'):
            if resource in base_caps and resource in prod_caps:
                self.assertGreaterEqual(self._quantity(prod_caps[resource]), self._quantity(base_caps[resource]))
        mounts = {m['mountPath']: m for m in runtime['volumeMounts']}
        self.assertIs(mounts['/data']['readOnly'], True)
        self.assertFalse(mounts['/data/private'].get('readOnly', False))
        installer = (ROOT / 'files/app/joyride/install_routing_graph.py').read_text()
        self.assertIn('RUNTIME_ENV', installer)
        self.assertIn('production_bootstrap_not_authorized', installer)
        digest = __import__('hashlib').sha256((ROOT / 'files/app/joyride/install_routing_graph.py').read_bytes()).hexdigest()
        self.assertEqual(self.resources['production_operations_scripts']['binaryData']['install_routing_graph.py'], '%{nest::service::joyride::production_routing_installer_base64}')
        self.assertEqual(self.resources['trusted_production_app']['spec']['template']['metadata']['annotations']['checksum/routing-installer'], '%{nest::service::joyride::production_routing_installer_sha256}')
        self.assertRegex(digest, r'^[0-9a-f]{64}$')

    def test_actual_luna_policy_and_firewall_rules_preserve_existing_paths(self):
        tailnet = json.loads((ROOT / 'files/tailscale/luna-gitlab.json').read_text())
        self.assertIn({'src': ['tag:luna-gitlab'], 'dst': ['172.21.0.3/32'], 'ip': ['tcp:443']}, tailnet['grants'])
        luna_tests = next(t for t in tailnet['tests'] if t['src'] == 'tag:luna-gitlab')
        self.assertIn('172.21.0.3:443', luna_tests['accept'])
        self.assertIn('172.21.0.3:8004', luna_tests['deny'])
        self.assertIn('172.21.1.3:443', luna_tests['accept'])
        self.assertIn('172.21.2.1:22', luna_tests['accept'])
        nft = (ROOT / 'files/tailscale/luna-gitlab.nft').read_text()
        self.assertRegex(nft, r'iifname "tailscale0" ip saddr 100\.127\.2\.74 ip daddr 172\.21\.0\.3 tcp dport 443 counter return')
        self.assertRegex(nft, r'ip daddr 172\.21\.0\.3 counter drop')
        self.assertRegex(nft, r'oifname "tailscale0" ip saddr 172\.21\.0\.3 ip daddr 100\.127\.2\.74 tcp sport 443 ct state established counter return')
        xml = ET.parse(ROOT / 'files/tailscale/luna-gitlab.xml').getroot()
        rules = list(xml.findall('rule'))
        def fields(rule):
            return ({x.attrib.get('address') for x in rule.findall('source')}, {x.attrib.get('address') for x in rule.findall('destination')}, {(x.attrib.get('protocol'), x.attrib.get('port')) for x in rule.findall('port')}, [x.tag for x in rule])
        expected = ({'100.127.2.74/32'}, {'172.21.0.3/32'}, {('tcp', '443')}, ['source', 'destination', 'port', 'accept'])
        self.assertIn(expected, [fields(r) for r in rules])
        self.assertIn(({'100.127.2.74/32'}, {'172.21.0.3/32'}, set(), ['source', 'destination', 'masquerade']), [fields(r) for r in rules])
        self.assertIn(({'100.127.2.74/32'}, {'172.21.1.3/32'}, {('tcp', '443')}, ['source', 'destination', 'port', 'accept']), [fields(r) for r in rules])
        self.assertIn(({'100.127.2.74/32'}, {'172.21.2.1/32'}, {('tcp', '22')}, ['source', 'destination', 'port', 'accept']), [fields(r) for r in rules])

    @staticmethod
    def _quantity(value):
        match = re.fullmatch(r'(\d+)(Ki|Mi|Gi)?', value)
        if not match:
            raise AssertionError('unrecognized resource quantity: ' + value)
        factor = {None: 1, 'Ki': 1024, 'Mi': 1024**2, 'Gi': 1024**3}[match.group(2)]
        return int(match.group(1)) * factor


if __name__ == '__main__':
    unittest.main()
