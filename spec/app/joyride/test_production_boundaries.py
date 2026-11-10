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
        base_source = (ROOT / 'data/kubernetes/app/joyride/joyride.yaml').read_text()
        overlay_source = (ROOT / 'data/kubernetes/service/joyride.yaml').read_text()
        cls.source = base_source + '\n' + overlay_source
        cls.candidate = yaml.safe_load(base_source)
        overlay = yaml.safe_load(overlay_source)
        cls.candidate.update({key: value for key, value in overlay.items() if key != 'resources'})
        # Hiera merges resources as a hash with whole-resource precedence.
        cls.resources = dict(cls.candidate['resources'])
        cls.resources.update(overlay['resources'])
        cls.candidate['resources'] = cls.resources
        cls.deployments = [r for r in cls.resources.values() if r.get('kind') == 'Deployment']

    def test_namespace_and_no_test_operational_authority(self):
        self.assertEqual(self.candidate['runtime_environment'], 'production')
        self.assertEqual(self.candidate['service_name'], 'joyride')
        for resource in self.resources.values():
            if resource:
                self.assertEqual(resource['metadata']['namespace'], 'joyride')
                self.assertNotIn(resource['kind'], ('Role', 'RoleBinding', 'ServiceAccount', 'Job'))
                if resource['kind'] == 'Secret':
                    self.assertIn(resource['metadata']['name'], (
                        'joyride-runtime', 'joyride-smtp', 'joyride-upstream',
                        'joyride-stripe', 'joyride-ops-auth', 'joyride-pull',
                        'joyride-backup-pull'))
                if resource['kind'] == 'CronJob':
                    self.assertIn(resource['metadata']['name'], ('joyride-monitor', 'joyride-backup'))
                    self.assertIs(resource['spec']['suspend'], False)
        self.assertNotIn('joyride-test', self.source)
        self.assertNotIn('8002', self.source)
        self.assertNotIn('172.21.1.3', self.source)

        self.assertEqual(self.resources['restore'], {})

    def test_production_mail_and_billing_have_explicit_secret_consumers(self):
        config = self.resources['config']['data']
        self.assertEqual(config['MAIL_ENABLED'], '1')
        self.assertEqual(config['STRIPE_MODE'], 'live')
        self.assertEqual(config['STRIPE_PRICE_ID'], 'price_1USr46RreaX3Pn1aj9WYMMj4')
        self.assertEqual(config['STRIPE_TAX_RATE_ID'], 'txr_1Ua0ZgRreaX3Pn1aVV1r9tS2')
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
        self.assertIn('$is_production', contract)
        self.assertIn('$production_smtp_password', contract)
        self.assertIn("$production_runtime_secrets", contract)

    def test_immutable_artifacts_and_inert_deployments(self):
        test = yaml.safe_load((ROOT / 'data/kubernetes/app/joyride/test.yaml').read_text())
        # TEST advances independently; a backend update must not promote production.
        self.assertRegex(test['joyride_image'], r'@sha256:[0-9a-f]{64}$')
        self.assertRegex(self.candidate['joyride_image'], r'@sha256:[0-9a-f]{64}$')
        self.assertEqual({d['metadata']['name'] for d in self.deployments}, {'joyride', 'joyride-ops', 'joyride-internal-web', 'joyride-production-access', 'joyride-trusted-production', 'joyride-worker'})
        for deployment in self.deployments:
            self.assertEqual(deployment['spec']['replicas'], 1)
            pod = deployment['spec']['template']['spec']
            self.assertIs(pod['automountServiceAccountToken'], False)
            if deployment['metadata']['name'] in ('joyride-ops', 'joyride-internal-web', 'joyride-worker'):
                self.assertNotIn('initContainers', pod)
            if deployment['metadata']['name'] in ('joyride', 'joyride-worker', 'joyride-trusted-production', 'joyride-internal-web', 'joyride-ops'):
                self.assertEqual(pod['imagePullSecrets'], [{'name': 'joyride-pull'}])
            else:
                self.assertNotIn('imagePullSecrets', pod)
            for container in pod['containers']:
                if container['name'] in ('tls-ops', 'nginx'):
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
        private = self.resources['internal_web_ingress']['spec']['rules'][0]['http']['paths']
        self.assertEqual([(p['path'], p['pathType'], p['backend']['service']['name'], p['backend']['service']['port']['number']) for p in private], [('/admin', 'Prefix', 'joyride-internal-web', 8003), ('/routing', 'Prefix', 'joyride-internal-web', 8003)])
        self.assertEqual(self.resources['internal_web']['spec'], {'selector': {'app': 'joyride-internal-web'}, 'ports': [{'name': 'http', 'port': 8003, 'targetPort': 8003}]})
        self.assertEqual(self.resources['internal_web_app']['spec']['template']['spec']['containers'][0]['command'][1], 'joyride.internal_wsgi:application')
        web = self.resources['app']['spec']['template']['spec']['containers']
        self.assertEqual([c['name'] for c in web], ['web'])
        self.assertIn('joyride.wsgi:application', web[0]['command'])
        for resource in self.resources.values():
            if resource.get('kind') == 'Service':
                if resource['metadata']['name'] not in ('joyride-ops', 'joyride-production-access'):
                    self.assertNotIn(resource['spec'].get('type'), ('NodePort', 'LoadBalancer'))

    def test_serial_initialization_is_scoped_to_production_storage(self):
        pod = self.resources['app']['spec']['template']['spec']
        web = pod['containers'][0]
        migrate, provision_owner, basemap = pod['initContainers']
        self.assertEqual([c['name'] for c in pod['initContainers']], ['migrate', 'provision-owner', 'basemap'])
        self.assertEqual(provision_owner['command'], ['python', 'manage.py', 'provision_owner'])
        self.assertEqual(provision_owner['image'], web['image'])
        self.assertEqual(provision_owner['env'], web['env'])
        self.assertEqual(provision_owner['envFrom'], web['envFrom'])
        self.assertEqual(provision_owner['resources'], web['resources'])
        self.assertEqual(migrate['command'], ['python', 'manage.py', 'migrate', '--noinput'])
        self.assertEqual(basemap['command'], ['python', '/app/platform_runtime/bootstrap.py'])
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
                if deployment['metadata']['name'] == 'joyride-trusted-production':
                    self.assertIn('pull', {v['name'] for v in runtime_pod['volumes']})
                else:
                    self.assertTrue({'pull', 'scripts'}.isdisjoint(v['name'] for v in runtime_pod['volumes']))

    def test_network_boundary_separates_ops_from_shared_ingress(self):
        self.assertEqual(self.resources['ops_policy']['spec'], {
            'podSelector': {'matchLabels': {'app': 'joyride-ops'}},
            'policyTypes': ['Ingress'], 'ingress': [{
                'from': [{'ipBlock': {'cidr': '172.22.0.0/24'}}],
                'ports': [{'protocol': 'TCP', 'port': 8443}]}]})
        self.assertEqual(self.resources['worker_policy']['spec']['ingress'], [])
        self.assertEqual(self.resources['internal_web_policy']['spec']['ingress'], [{
            'from': [{'namespaceSelector': {'matchLabels': {'kubernetes.io/metadata.name': 'projectcontour'}},
                     'podSelector': {'matchLabels': {'app.kubernetes.io/component': 'envoy'}}}],
            'ports': [{'protocol': 'TCP', 'port': 8003}]}, {
            'from': [{'podSelector': {'matchLabels': {'app': 'joyride-production-access'}}}],
            'ports': [{'protocol': 'TCP', 'port': 8003}]}])
        self.assertEqual(self.resources['web_policy']['spec']['ingress'], [{
            'from': [{'namespaceSelector': {'matchLabels': {
                'kubernetes.io/metadata.name': 'projectcontour'}},
                'podSelector': {'matchLabels': {'app.kubernetes.io/component': 'envoy'}}}],
            'ports': [{'protocol': 'TCP', 'port': 8000}]}])

    def test_credential_consumers_are_explicit_and_environment_local(self):
        actual = {}
        for deployment in self.deployments:
            for container in deployment['spec']['template']['spec']['containers']:
                if container['name'] in ('tls-ops', 'nginx'):
                    self.assertNotIn('env', container)
                    self.assertNotIn('envFrom', container)
                    expected = {'ops-config', 'ops-tls', 'nginx-tmp'} if container['name'] == 'tls-ops' else {'config', 'tls', 'tmp'}
                    self.assertEqual({m['name'] for m in container['volumeMounts']}, expected)
                    continue
                if deployment['metadata']['name'] == 'joyride-trusted-production':
                    self.assertIn({'configMapRef': {'name': 'joyride-config'}}, container['envFrom'])
                    actual[container['name']] = {item['name']: item['valueFrom']['secretKeyRef'] for item in container['env']}
                    continue
                self.assertEqual(container['envFrom'], [{'configMapRef': {'name': 'joyride-config'}}])
                actual[container['name']] = {item['name']: item['valueFrom']['secretKeyRef'] for item in container['env']}
        common = {'DJANGO_SECRET_KEY': {'name': 'joyride-runtime', 'key': 'DJANGO_SECRET_KEY'},
                  'DATABASE_URL': {'name': 'joyride-cnpg-app', 'key': 'uri'}}
        stripe = {'STRIPE_SECRET_KEY': {'name': 'joyride-stripe', 'key': 'STRIPE_SECRET_KEY'},
                  'STRIPE_WEBHOOK_SECRET': {'name': 'joyride-stripe', 'key': 'STRIPE_WEBHOOK_SECRET'}}
        mail = dict(common, EMAIL_HOST_PASSWORD={'name': 'joyride-smtp', 'key': 'EMAIL_HOST_PASSWORD'}, **stripe)
        self.assertEqual(actual, {
            'web': mail,
            'worker': dict(mail, WMATA_API_KEY={'name': 'joyride-upstream', 'key': 'WMATA_API_KEY'}),
            'ops': dict(common, OPS_TOKEN={'name': 'joyride-ops-auth', 'key': 'OPS_TOKEN'}, **stripe),
            'internal-web': dict(common, **stripe),
            'trusted-production': dict(common, **stripe)})
        config = self.resources['config']['data']
        self.assertEqual(config['MAIL_ENABLED'], '1')
        self.assertEqual(config['STRIPE_MODE'], 'live')
        self.assertEqual(config['STRIPE_PRICE_ID'], 'price_1USr46RreaX3Pn1aj9WYMMj4')
        self.assertEqual(config['STRIPE_TAX_RATE_ID'], 'txr_1Ua0ZgRreaX3Pn1aVV1r9tS2')
        self.assertEqual(config['OPS_SCOPES'], 'status,diagnostics,member:read')
        self.assertEqual(config['ALLOWED_HOSTS'], 'joyride.eyrie')

    def test_internal_web_preserves_owner_authentication_and_read_only_production_data(self):
        deployment = self.resources['internal_web_app']['spec']
        pod = deployment['template']['spec']
        container, = pod['containers']
        self.assertEqual(deployment['replicas'], 1)
        self.assertEqual(pod['securityContext']['fsGroupChangePolicy'], 'OnRootMismatch')
        self.assertEqual(container['resources']['limits']['memory'], '2048Mi')
        self.assertEqual(self.resources['app']['spec']['strategy'], {
            'type': 'RollingUpdate', 'rollingUpdate': {'maxUnavailable': 0, 'maxSurge': 1},
        })
        self.assertEqual(self.resources['app']['spec']['minReadySeconds'], 10)
        self.assertEqual(container['command'][1], 'joyride.internal_wsgi:application')
        self.assertIn('0.0.0.0:8003', container['command'])
        self.assertEqual(container['envFrom'], [{'configMapRef': {'name': 'joyride-config'}}])
        refs = {row['name']: row['valueFrom']['secretKeyRef'] for row in container['env']}
        self.assertEqual(refs, {
            'DJANGO_SECRET_KEY': {'name': 'joyride-runtime', 'key': 'DJANGO_SECRET_KEY'},
            'DATABASE_URL': {'name': 'joyride-cnpg-app', 'key': 'uri'},
            'STRIPE_SECRET_KEY': {'name': 'joyride-stripe', 'key': 'STRIPE_SECRET_KEY'},
            'STRIPE_WEBHOOK_SECRET': {'name': 'joyride-stripe', 'key': 'STRIPE_WEBHOOK_SECRET'},
        })
        self.assertNotIn('EMAIL_HOST_PASSWORD', refs)
        self.assertNotIn('OPS_TOKEN', refs)
        mounts = {m['mountPath']: m for m in container['volumeMounts']}
        self.assertIs(mounts['/data']['readOnly'], True)
        self.assertNotIn('/data/private', mounts)
        self.assertEqual(mounts['/data/tmp']['name'], 'tmp')
        self.assertEqual(self.resources['ingress']['spec']['rules'][0]['http']['paths'][0]['backend']['service']['name'], 'joyride-web')

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
        self.assertIs(job['suspend'], False)
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
        self.assertIs(job['suspend'], False)
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
        self.assertIn('352f5de3ca10ccb1f61c1ffaaec887d491c6a6347a234a0ebdc5195ae30d95b3', initializer['command'][-1])
        rule = self.resources['alert_rules']['spec']['groups'][0]['rules'][1]
        self.assertIn('kube_cronjob_spec_suspend{namespace="joyride",cronjob="joyride-backup"} == 0', rule['expr'])
        self.assertIn('unless on(namespace,cronjob)', rule['expr'])
        self.assertEqual(self.resources['restore'], {})

    def test_storage_does_not_reference_test_claims_or_database(self):
        self.assertEqual(self.resources['database']['metadata']['name'], 'joyride-cnpg')
        self.assertEqual(self.resources['storage']['metadata']['name'], 'joyride-data')
        for deployment in self.deployments:
            volumes = deployment['spec']['template']['spec']['volumes']
            if deployment['metadata']['name'] == 'joyride-production-access':
                self.assertNotIn('persistentVolumeClaim', yaml.safe_dump(volumes))
            else:
                self.assertIn({'name': 'data', 'persistentVolumeClaim': {'claimName': 'joyride-data'}}, volumes)

    def test_production_is_explicitly_scoped_without_test_authority(self):
        guard = (ROOT / 'manifests/service/joyride.pp').read_text()
        self.assertIn("$nest::kubernetes::namespace == 'test'", guard)
        self.assertIn("$nest::kubernetes::service == 'joyride-test'", guard)
        self.assertIn("$nest::kubernetes::namespace == 'joyride'", guard)
        self.assertIn("$nest::kubernetes::service == 'joyride'", guard)
        self.assertIn("$runtime_environment == 'production'", guard)
        self.assertIn("if !$is_test and !$is_production", guard)
        self.assertNotIn('joyride-test', yaml.safe_dump(self.resources, sort_keys=True))
        self.assertNotIn('8002', self.source)
        self.assertNotIn('172.21.1.3', self.source)
        self.assertTrue((ROOT / 'plans/eyrie/deploy_joyride.yaml').exists())
        gateway = yaml.safe_load((ROOT / 'data/host/gateway.yaml').read_text())
        self.assertIn('nest::service::joyride_gateway', gateway['nest::classes'])
        self.assertIs(gateway['nest::service::joyride_gateway::https_enabled'], True)
        gateway_class = (ROOT / 'manifests/service/joyride_gateway.pp').read_text()
        self.assertIn('if $https_enabled {', gateway_class)
        activation = (ROOT / 'manifests/service/gateway.pp').read_text()
        self.assertNotIn('joyride_gateway', activation)


if __name__ == '__main__':
    unittest.main()
