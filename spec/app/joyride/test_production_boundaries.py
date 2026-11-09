"""Dormant production integration boundaries, not deployed acceptance.

Run with python3 spec/app/joyride/test_production_boundaries.py. Requires PyYAML.
The TEST-only Puppet compile guard must remain closed during this preparation.
"""
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[3]


class ProductionBoundaries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / 'data/kubernetes/app/joyride/joyride.yaml').read_text()
        cls.candidate = yaml.safe_load(cls.source)
        cls.resources = cls.candidate['resources']
        cls.deployments = [r for r in cls.resources.values() if r.get('kind') == 'Deployment']

    def test_namespace_and_no_test_operational_authority(self):
        self.assertEqual(self.candidate['runtime_environment'], 'production')
        self.assertEqual(self.candidate['service_name'], 'joyride')
        for resource in self.resources.values():
            if resource:
                self.assertEqual(resource['metadata']['namespace'], 'joyride')
                self.assertNotIn(resource['kind'], ('Secret', 'Role', 'RoleBinding', 'ServiceAccount', 'Job'))
                if resource['kind'] == 'CronJob':
                    self.assertIn(resource['metadata']['name'], ('joyride-monitor', 'joyride-backup'))
                    self.assertIs(resource['spec']['suspend'], True)
        self.assertNotIn('joyride-test', self.source)
        self.assertNotIn('8002', self.source)
        self.assertNotIn('172.21.1.3', self.source)

        self.assertEqual(self.resources['restore'], {})

    def test_dormant_mail_identity_has_production_only_secret_reference(self):
        config = self.resources['config']['data']
        self.assertEqual(config['MAIL_ENABLED'], '0')
        self.assertEqual(config['EMAIL_HOST'], 'smtp.gmail.com')
        self.assertEqual(config['EMAIL_HOST_USER'], 'joy@joyridedc.com')
        self.assertEqual(config['DEFAULT_FROM_EMAIL'], 'Friday Night Joyride <hello@joyridedc.com>')
        self.assertNotIn('EMAIL_HOST_PASSWORD', config)
        for resource_name in ('app', 'worker'):
            pod = self.resources[resource_name]['spec']['template']['spec']
            for container in pod['containers'] + pod.get('initContainers', []):
                env = {row['name']: row for row in container['env']}
                self.assertEqual(env['EMAIL_HOST_PASSWORD'], {
                    'name': 'EMAIL_HOST_PASSWORD', 'valueFrom': {'secretKeyRef': {
                        'name': 'joyride-smtp', 'key': 'EMAIL_HOST_PASSWORD'}}})
                self.assertIn({'configMapRef': {'name': 'joyride-config'}}, container['envFrom'])
        contract = (ROOT / 'manifests/service/joyride.pp').read_text()
        self.assertIn('production is not configured', contract)
        self.assertNotIn('production_smtp_password', contract)

    def test_immutable_artifacts_and_inert_deployments(self):
        test = yaml.safe_load((ROOT / 'data/kubernetes/app/joyride/test.yaml').read_text())
        # TEST advances independently; a backend update must not promote production.
        self.assertRegex(test['joyride_image'], r'@sha256:[0-9a-f]{64}$')
        self.assertRegex(self.candidate['joyride_image'], r'@sha256:[0-9a-f]{64}$')
        self.assertEqual(len(self.deployments), 3)
        for deployment in self.deployments:
            self.assertEqual(deployment['spec']['replicas'], 0)
            pod = deployment['spec']['template']['spec']
            self.assertIs(pod['automountServiceAccountToken'], False)
            if deployment['metadata']['name'] != 'joyride':
                self.assertNotIn('initContainers', pod)
            self.assertEqual(pod['imagePullSecrets'], [{'name': 'joyride-pull'}])
            for container in pod['containers']:
                if container['name'] == 'tls-ops':
                    self.assertRegex(container['image'], r'^docker.io/nginxinc/nginx-unprivileged@sha256:[0-9a-f]{64}$')
                else:
                    self.assertEqual(container['image'], "%{lookup('joyride_image')}")
                self.assertIs(container['securityContext']['readOnlyRootFilesystem'], True)
                self.assertIs(container['securityContext']['allowPrivilegeEscalation'], False)

    def test_public_origin_only_reaches_web(self):
        ingress = self.resources['ingress']['spec']
        self.assertEqual(ingress['ingressClassName'], 'contour')
        self.assertEqual(ingress['rules'], [{
            'host': 'joyride.eyrie', 'http': {'paths': [{
                'path': '/', 'pathType': 'Prefix', 'backend': {'service': {
                    'name': 'joyride-web', 'port': {'number': 8000}}}}]}}])
        self.assertEqual(self.resources['web']['spec']['selector'], {'app': 'joyride'})
        self.assertEqual(self.resources['ops']['spec']['selector'], {'app': 'joyride-ops'})
        web = self.resources['app']['spec']['template']['spec']['containers']
        self.assertEqual([c['name'] for c in web], ['web'])
        self.assertIn('joyride.wsgi:application', web[0]['command'])
        for resource in self.resources.values():
            if resource.get('kind') == 'Service':
                if resource['metadata']['name'] != 'joyride-ops':
                    self.assertNotIn(resource['spec'].get('type'), ('NodePort', 'LoadBalancer'))

    def test_serial_initialization_is_scoped_to_production_storage(self):
        pod = self.resources['app']['spec']['template']['spec']
        migrate, basemap = pod['initContainers']
        self.assertEqual([c['name'] for c in pod['initContainers']], ['migrate', 'basemap'])
        self.assertEqual(migrate['command'], ['python', 'manage.py', 'migrate', '--noinput'])
        self.assertEqual(basemap['command'], ['python', '/app/platform_runtime/bootstrap.py'])
        web = pod['containers'][0]
        for initializer in (migrate, basemap):
            self.assertEqual(initializer['image'], web['image'])
            self.assertEqual(initializer['securityContext'], web['securityContext'])
            self.assertEqual(initializer['env'], web['env'])
            self.assertEqual(initializer['envFrom'], web['envFrom'])
            self.assertEqual(initializer['resources'], web['resources'])
        self.assertEqual(migrate['volumeMounts'], [{'name': 'tmp', 'mountPath': '/data/tmp'}])
        volumes = {v['name']: v for v in pod['volumes']}
        self.assertEqual(volumes['data']['persistentVolumeClaim'], {'claimName': 'joyride-data'})
        self.assertNotIn('scripts', volumes)
        self.assertEqual(volumes['pull']['secret'], {'secretName': 'joyride-pull'})
        self.assertNotIn('scripts', self.resources)
        mounts = {m['name']: m for m in basemap['volumeMounts']}
        self.assertNotIn('scripts', mounts)
        self.assertIs(mounts['pull']['readOnly'], True)
        self.assertFalse(mounts['data'].get('readOnly', False))
        for deployment in self.deployments:
            runtime_pod = deployment['spec']['template']['spec']
            for container in runtime_pod['containers']:
                self.assertTrue({'pull', 'scripts'}.isdisjoint(m['name'] for m in container['volumeMounts']))
            if deployment['metadata']['name'] != 'joyride':
                self.assertTrue({'pull', 'scripts'}.isdisjoint(v['name'] for v in runtime_pod['volumes']))

    def test_network_boundary_separates_ops_from_shared_ingress(self):
        self.assertEqual(self.resources['ops_policy']['spec'], {
            'podSelector': {'matchLabels': {'app': 'joyride-ops'}},
            'policyTypes': ['Ingress'], 'ingress': [{
                'from': [{'ipBlock': {'cidr': '172.22.0.0/24'}}],
                'ports': [{'protocol': 'TCP', 'port': 8443}]}]})
        self.assertEqual(self.resources['worker_policy']['spec']['ingress'], [])
        self.assertEqual(self.resources['web_policy']['spec']['ingress'], [{
            'from': [{'namespaceSelector': {'matchLabels': {
                'kubernetes.io/metadata.name': 'projectcontour'}},
                'podSelector': {'matchLabels': {'app.kubernetes.io/component': 'envoy'}}}],
            'ports': [{'protocol': 'TCP', 'port': 8000}]}])

    def test_credential_consumers_are_explicit_and_environment_local(self):
        actual = {}
        for deployment in self.deployments:
            for container in deployment['spec']['template']['spec']['containers']:
                if container['name'] == 'tls-ops':
                    self.assertNotIn('env', container)
                    self.assertNotIn('envFrom', container)
                    self.assertEqual({m['name'] for m in container['volumeMounts']}, {'ops-config', 'ops-tls', 'nginx-tmp'})
                    continue
                self.assertEqual(container['envFrom'], [{'configMapRef': {'name': 'joyride-config'}}])
                actual[container['name']] = {item['name']: item['valueFrom']['secretKeyRef'] for item in container['env']}
        common = {'DJANGO_SECRET_KEY': {'name': 'joyride-runtime', 'key': 'DJANGO_SECRET_KEY'},
                  'DATABASE_URL': {'name': 'joyride-cnpg-app', 'key': 'uri'}}
        mail = dict(common, EMAIL_HOST_PASSWORD={'name': 'joyride-smtp', 'key': 'EMAIL_HOST_PASSWORD'})
        self.assertEqual(actual, {
            'web': mail,
            'worker': dict(mail, WMATA_API_KEY={'name': 'joyride-upstream', 'key': 'WMATA_API_KEY'}),
            'ops': dict(common, OPS_TOKEN={'name': 'joyride-ops-auth', 'key': 'OPS_TOKEN'})})
        config = self.resources['config']['data']
        self.assertEqual(config['MAIL_ENABLED'], '0')
        self.assertEqual(config['STRIPE_MODE'], 'disabled')
        self.assertEqual(config['OPS_SCOPES'], 'status,diagnostics,member:read')
        self.assertEqual(config['ALLOWED_HOSTS'], 'joyride.eyrie')

    def test_private_ops_has_dedicated_tls_vpn_service_and_loopback_auth(self):
        service = self.resources['ops']['spec']
        self.assertEqual(service['type'], 'LoadBalancer')
        self.assertEqual(service['loadBalancerIP'], '172.21.0.2')
        self.assertIs(service['allocateLoadBalancerNodePorts'], False)
        self.assertEqual(service['externalTrafficPolicy'], 'Local')
        self.assertEqual(service['loadBalancerSourceRanges'], ['172.22.0.0/24'])
        self.assertEqual(service['ports'], [{'name': 'https', 'port': 443, 'targetPort': 8443}])
        pod = self.resources['ops_app']['spec']['template']['spec']
        self.assertEqual(pod['nodeSelector'], {'node-role.kubernetes.io/worker': ''})
        ops, tls = pod['containers']
        self.assertIn('127.0.0.1:8001', ops['command'])
        self.assertNotIn('ports', ops)
        self.assertEqual(tls['ports'], [{'name': 'tls-ops', 'containerPort': 8443}])
        self.assertEqual(self.resources['ops_certificate']['spec']['dnsNames'], ['joyride-ops.eyrie'])
        self.assertEqual(self.resources['ops_config']['binaryData'], {
            'nginx.conf': '%{nest::service::joyride::production_ops_config_base64}'})
        config = (ROOT / 'files/app/joyride/production-ops-nginx.conf').read_text()
        self.assertIn('allow 172.22.0.0/24;', config)
        self.assertIn('deny all;', config)
        self.assertIn('proxy_set_header Authorization $http_authorization;', config)
        self.assertIn('proxy_pass_request_headers off;', config)
        self.assertIn('server 127.0.0.1:8001;', config)
        self.assertNotIn('real_ip_header', config)
        self.assertNotIn('8002', config)

    def test_monitor_has_no_runtime_credentials_or_privileged_network_path(self):
        job = self.resources['monitor']['spec']
        self.assertIs(job['suspend'], True)
        self.assertEqual(job['concurrencyPolicy'], 'Forbid')
        pod = job['jobTemplate']['spec']['template']['spec']
        self.assertIs(pod['automountServiceAccountToken'], False)
        self.assertNotIn('volumes', pod)
        container, = pod['containers']
        self.assertEqual(container['image'], "%{lookup('joyride_operations_image')}")
        self.assertEqual(container['command'], ['python', '-B', '/app/platform_runtime/monitor.py', '--environment', 'production'])
        self.assertNotIn('env', container)
        self.assertNotIn('envFrom', container)
        self.assertIs(container['securityContext']['readOnlyRootFilesystem'], True)
        self.assertNotIn('monitor_scripts', self.resources)
        self.assertEqual(self.resources['monitor_policy']['spec'], {
            'podSelector': {'matchLabels': {'app': 'joyride'}}, 'policyTypes': ['Ingress'],
            'ingress': [{'from': [{'podSelector': {'matchLabels': {'app': 'joyride-monitor'}}}],
                         'ports': [{'protocol': 'TCP', 'port': 8000}]}]})
        rule = self.resources['alert_rules']['spec']['groups'][0]['rules'][0]
        self.assertIn('kube_cronjob_spec_suspend{namespace="joyride",cronjob="joyride-monitor"} == 0', rule['expr'])
        self.assertIn('unless on(namespace,cronjob)', rule['expr'])

    def test_backup_is_suspended_administrative_capture_not_restore(self):
        job = self.resources['backup']['spec']
        self.assertIs(job['suspend'], True)
        self.assertEqual(job['concurrencyPolicy'], 'Forbid')
        pod = job['jobTemplate']['spec']['template']['spec']
        self.assertIs(pod['automountServiceAccountToken'], False)
        self.assertEqual(pod['imagePullSecrets'], [{'name': 'joyride-backup-pull'}, {'name': 'joyride-pull'}])
        container, = pod['containers']
        self.assertEqual(container['image'], "%{lookup('config_image')}")
        self.assertEqual(container['command'], [
            'python3', '-B', '/trusted/backup.py', '--stage-root', '/scratch', '--environment', 'production'])
        self.assertEqual(container['env'], [{'name': 'KUBECONFIG', 'value': '/kubeconfig/eyrie.conf'}])
        self.assertNotIn('envFrom', container)
        self.assertIs(container['securityContext']['readOnlyRootFilesystem'], True)
        mounts = {m['name']: m for m in container['volumeMounts']}
        self.assertIs(mounts['scripts']['readOnly'], True)
        self.assertIs(mounts['kubeconfig']['readOnly'], True)
        self.assertEqual(mounts['backup']['mountPath'], '/nest/backup/joyride')
        volumes = {v['name']: v for v in pod['volumes']}
        self.assertEqual(set(volumes), {'scripts', 'scratch', 'backup', 'kubeconfig'})
        self.assertEqual(volumes['backup']['hostPath']['path'], '/nest/backup/joyride')
        self.assertEqual(volumes['scratch']['emptyDir'], {'sizeLimit': '24Gi'})
        self.assertNotIn('backup_scripts', self.resources)
        self.assertEqual(volumes['scripts']['emptyDir'], {'sizeLimit': '1Mi'})
        initializer, = pod['initContainers']
        self.assertEqual(initializer['image'], "%{lookup('joyride_operations_image')}")
        self.assertNotIn('env', initializer)
        self.assertNotIn('envFrom', initializer)
        self.assertEqual(initializer['volumeMounts'], [{'name': 'scripts', 'mountPath': '/trusted'}])
        self.assertIn('0bd5c397f068b7e9eed784ce48afcd0abf4eeb4ae3b5a11c53aaa04939415f5c', initializer['command'][-1])
        rule = self.resources['alert_rules']['spec']['groups'][0]['rules'][1]
        self.assertIn('kube_cronjob_spec_suspend{namespace="joyride",cronjob="joyride-backup"} == 0', rule['expr'])
        self.assertIn('unless on(namespace,cronjob)', rule['expr'])
        self.assertEqual(self.resources['restore'], {})

    def test_storage_does_not_reference_test_claims_or_database(self):
        self.assertEqual(self.resources['database']['metadata']['name'], 'joyride-cnpg')
        self.assertEqual(self.resources['storage']['metadata']['name'], 'joyride-data')
        for deployment in self.deployments:
            volumes = deployment['spec']['template']['spec']['volumes']
            self.assertEqual(volumes[0]['persistentVolumeClaim'], {'claimName': 'joyride-data'})

    def test_activation_still_refused_by_common_class(self):
        guard = (ROOT / 'manifests/service/joyride.pp').read_text()
        self.assertIn("$nest::kubernetes::namespace != 'test'", guard)
        self.assertIn("$nest::kubernetes::service != 'joyride-test'", guard)
        self.assertIn("fail('Joyride currently supports only service joyride-test", guard)
        self.assertFalse((ROOT / 'plans/eyrie/deploy_joyride.yaml').exists())
        gateway = (ROOT / 'data/host/gateway.yaml').read_text()
        self.assertNotIn('joyridedc.com', gateway)
        # ACME-only bootstrap is not the retired informational publication path
        gateway_data = yaml.safe_load(gateway)
        self.assertIn('nest::service::joyride_gateway', gateway_data['nest::classes'])
        self.assertIs(gateway_data['nest::service::joyride_gateway::https_enabled'], False)
        gateway_class = (ROOT / 'manifests/service/joyride_gateway.pp').read_text()
        self.assertIn('if $https_enabled {', gateway_class)
        activation = (ROOT / 'manifests/service/gateway.pp').read_text()
        self.assertNotIn('joyride_gateway', activation)


if __name__ == '__main__':
    unittest.main()
