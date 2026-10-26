"""Shared isolated lifecycle tests: no host, pool, catalog or reboot mutation."""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

TASKS = Path(__file__).resolve().parents[2] / 'tasks'
sys.dont_write_bytecode = True
sys.path.insert(0, str(TASKS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import update_lifecycle as lifecycle
import update_dispatch as dispatch
from update_wave_plan import plan as wave_plan, canonical
from retain_update_report import publish_document
from retain_update_report_test import with_reboot
from retain_update_reboot_test import plan as reboot_plan
import retain_update_health_test as health_fixture
import retain_update_catalog_test as catalog_fixture
import retain_update_catalog
import retain_update_health


def policy():
    now = datetime.now(timezone.utc)
    window = {'not_before': (now - timedelta(minutes=1)).strftime('%Y-%m-%dT%H:%M:%SZ'),
              'not_after': (now + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')}
    return dict(schema=5, kind='nest_update_wave_policy', release='sha256:' + 'a' * 64,
                config_source='a' * 40, max_parallel=2, domains=['fixture-domain'],
                hosts=[dict(name='fixture-host', platform='fixture', kernel='6.18.57', domains=['fixture-domain'])],
                excluded=['fixture-console'], canaries=['fixture-host'], preparation_window=window,
                backup_requirements={'fixture-host': []}, lifecycle=dict(controller='fixture-controller', window=window,
                    impact={'fixture-host': ['fixture-service-outage']}, rollback='keep_previous_be_manual_recovery',
                    retention='keep_backups_and_origins_until_release_retired', acceptance={'fixture-host': dict(
                        certname='fixture.nest', endpoints=health_fixture.ENDPOINTS,
                        canaries=[dict(name='service', command=['/usr/bin/true'])], historical_failures=[])}))


def status():
    value = with_reboot(reboot_plan('already_booted'))
    for key in ('read_only', 'reboot_reason', 'reboot_eligible'):
        value.pop(key)
    expected = health_fixture.EXPECTED
    value['host'].update(pool_guid=expected['pool_guid'], current='rpool/crypt/ROOT/A', target=expected['current'],
                         current_tree=[dict(dataset='rpool/crypt/ROOT/A', guid='21', mountpoint='/')])
    value['target_tree'] = [dict(dataset=expected['current'], guid=expected['current_guid'], mountpoint='/'),
                            dict(dataset=expected['current'] + '/var', guid=expected['var_guid'], mountpoint='/var')]
    value['observation'].update(current=expected['current'], next_boot=expected['current'])
    return value


class LifecycleTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name).resolve()
        self.p = dict(policy=policy(), targets=['fixture-host'], inputs={'fixture-host': {'transaction': 'fixture-report'}},
                      output_dir=str(self.directory), host='fixture-host', status=json.dumps(status()))
        self.bound = lifecycle.context(self.p)

    def tearDown(self):
        self.temp.cleanup()

    def store(self, step, document):
        p = dict(self.p, step=step)
        lifecycle.step(dict(p, action='begin'), self.bound)
        receipt = publish_document(document, self.directory, step + '-fixture')
        lifecycle.step(dict(p, action='complete', result=receipt), self.bound)
        return receipt

    def observations(self, health=None, catalog=None):
        health = health_fixture.fixture(endpoints=health_fixture.ENDPOINTS) if health is None else health
        projected = retain_update_health.project(json.dumps(health), health_fixture.EXPECTED, health_fixture.ENDPOINTS,
                                                 'fixture-report', self.bound['release'])
        self.store('health', projected)
        expected = dict(catalog_fixture.EXPECTED, hostname='fixture-host', boot_id=health_fixture.BOOT)
        cat = catalog_fixture.fixture() if catalog is None else catalog
        cat.update(hostname='fixture-host', boot_id=health_fixture.BOOT)
        projected = retain_update_catalog.project(json.dumps(cat), expected, 'fixture-report', self.bound['release'])
        self.store('catalog', projected)
        document = dict(schema=1, kind='nest_update_canary', hostname='fixture-host', transaction='fixture-report',
                        release=self.bound['release'], boot_id=health_fixture.BOOT, name='service',
                        command_sha256=hashlib.sha256(canonical(['/usr/bin/true'])).hexdigest(), native_exit=0)
        self.store('canary-service', document)

    def test_real_collectors_bind_same_boot_to_all_native_acceptance_gates(self):
        self.observations()
        receipt = lifecycle.evidence(self.p, self.bound)
        evidence = lifecycle.reopen(receipt, self.directory)
        self.assertEqual(evidence['observed_boot_id'], health_fixture.BOOT)
        self.assertEqual(evidence['target_tree'], status()['target_tree'])
        self.assertEqual(evidence['gates']['normal_main_apply']['native_exit'], 2)
        self.assertEqual(evidence['gates']['converged_repeat']['native_exit'], 0)
        self.assertNotEqual(evidence['gates']['normal_main_apply']['evidence_ref'], evidence['gates']['converged_repeat']['evidence_ref'])
        self.assertEqual(lifecycle.evidence(self.p, self.bound), receipt)
        self.assertEqual(len(evidence['gates']['user_managers']['managers']), 1)
        self.assertEqual(evidence['gates']['system_failures']['failures'], [])

    def test_missing_bus_never_becomes_zero_failures_or_acceptance(self):
        manager = health_fixture.manager_fixture.health
        health = health_fixture.fixture(endpoints=health_fixture.ENDPOINTS, user={1000: manager.Unavailable('user_bus_unavailable')})
        self.observations(health=health)
        with self.assertRaises(ValueError):
            lifecycle.evidence(self.p, self.bound)

    def test_failed_catalog_cannot_be_accepted_or_replayed(self):
        self.observations(catalog=catalog_fixture.fixture(second=2))
        with self.assertRaises(ValueError):
            lifecycle.evidence(self.p, self.bound)
        with self.assertRaises(FileExistsError):
            lifecycle.step(dict(self.p, action='begin', step='catalog'), self.bound)

    def test_historical_failure_requires_exact_reviewed_disposition(self):
        unit = health_fixture.manager_fixture.unit('historic.service', 'failed', 'failed')
        self.observations(health=health_fixture.fixture(endpoints=health_fixture.ENDPOINTS, system=[unit]))
        with self.assertRaises(ValueError):
            lifecycle.evidence(self.p, self.bound)
        row = dict(manager='system', identity='historic.service', rationale='Historical timer incident retained',
                   evidence_ref='incident:fixture', evidence_sha256='e' * 64)
        self.p['policy']['lifecycle']['acceptance']['fixture-host']['historical_failures'] = [row]
        # A changed policy changes the journal namespace: it never adopts prior
        # actions implicitly. Test the collector itself against retained rows.
        receipt = lifecycle.evidence(self.p, self.bound)
        evidence = lifecycle.reopen(receipt, self.directory)
        self.assertEqual(evidence['gates']['system_failures']['failures'][0]['identity'], 'historic.service')
        self.assertEqual(evidence['gates']['system_failures']['failures'][0]['disposition'], 'explained_historical')

    def test_changed_boot_or_missing_preparation_refuses(self):
        self.observations()
        data = status()
        for update in (dict(boot_changed=False), dict(expected_target_booted=False), dict(next_boot='rpool/crypt/ROOT/A')):
            data = status()
            data['observation'].update(update)
            with self.assertRaises(ValueError):
                lifecycle.evidence(dict(self.p, status=json.dumps(data)), self.bound)
        data = status()
        data['phases'][-1]['commands'] = [dict(operation='root', native_exit=2, success=True)]
        with self.assertRaises(ValueError):
            lifecycle.evidence(dict(self.p, status=json.dumps(data)), self.bound)

    def test_restart_preserves_ambiguous_intent_without_permission_to_replay(self):
        p = dict(self.p, step='submit')
        lifecycle.step(dict(p, action='begin'), self.bound)
        result = subprocess.run([sys.executable, '-B', str(TASKS / 'update_lifecycle.py')],
                                input=json.dumps(dict(p, action='read')), text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), dict(complete=False, intent=True))
        with self.assertRaises(FileExistsError):
            lifecycle.step(dict(p, action='begin'), self.bound)

    def test_read_only_steps_retain_results_without_mutation_intents(self):
        for name in ('reboot', 'health'):
            p = dict(self.p, step=name)
            receipt = publish_document({'kind': 'fixture-observation'}, self.directory, name + '-fixture')
            result = lifecycle.step(dict(p, action='complete', result=receipt), self.bound)
            self.assertTrue(result['complete'])
            self.assertFalse(result['intent'])
            self.assertFalse(lifecycle.journal(p, self.bound).exists())
            self.assertEqual(lifecycle.step(dict(p, action='read'), self.bound)['receipt'], receipt)

    def test_mutating_steps_still_require_intent_before_completion(self):
        receipt = publish_document({'kind': 'fixture-result'}, self.directory, 'fixture-result')
        for name in ('catalog', 'submit', 'canary-service'):
            with self.subTest(step=name), self.assertRaisesRegex(ValueError, 'missing operation intent'):
                lifecycle.step(dict(self.p, step=name, action='complete', result=receipt), self.bound)

    def test_modified_or_missing_reports_refuse_on_resume(self):
        self.observations()
        receipt = lifecycle.step(dict(self.p, action='read', step='health'), self.bound)['receipt']
        Path(receipt['path']).write_text('{}')
        with self.assertRaises(ValueError):
            lifecycle.step(dict(self.p, action='read', step='health'), self.bound)

    def test_expired_window_refuses_new_mutations_but_not_observation(self):
        now = datetime.now(timezone.utc) + timedelta(days=2)
        with patch.object(lifecycle, 'current_time', return_value=now):
            self.assertFalse(lifecycle.step(dict(self.p, action='read', step='catalog'), self.bound)['intent'])
            with self.assertRaises(ValueError):
                lifecycle.step(dict(self.p, action='begin', step='catalog'), self.bound)

    def test_same_policy_excludes_consoles_requires_canary_and_surviving_controller(self):
        for change in ('console', 'controller', 'canary', 'network', 'retention'):
            p = copy.deepcopy(self.p['policy'])
            if change == 'console':
                p['hosts'][0]['name'] = 'fixture-console'
            elif change == 'controller':
                p['lifecycle']['controller'] = 'fixture-host'
            elif change == 'canary':
                p['lifecycle']['acceptance']['fixture-host']['canaries'] = []
            elif change == 'network':
                p['lifecycle']['acceptance']['fixture-host']['endpoints'] = []
            else:
                p['lifecycle']['retention'] = 'prune_now'
            with self.subTest(change=change), self.assertRaises(ValueError):
                wave_plan(p, ['fixture-host'])

    def test_cross_host_export_materializes_and_reopens_real_documents(self):
        destination = self.directory / 'destination'
        destination.mkdir()
        doc = dict(schema=1, kind='nest_update_lifecycle', host_count=1)
        raw = (json.dumps(doc, sort_keys=True, indent=2) + '\n').encode()
        digest = hashlib.sha256(raw).hexdigest()
        export = dict(schema=1, kind='nest_update_lifecycle_export', policy_sha256=self.bound['policy_sha256'],
                      files=[dict(source_path='/modules/nest/report-' + digest + '.json', sha256=digest, bytes=len(raw), document=doc)])
        receipt = dispatch.receive(dict(export=export, output_dir=str(destination)))
        delivery = lifecycle.reopen(receipt, destination)
        copied = delivery['copied_reports'][0]['retained']
        self.assertEqual(lifecycle.reopen(copied, destination), doc)
        export['files'][0]['document']['host_count'] = 2
        with self.assertRaises(ValueError):
            dispatch.receive(dict(export=export, output_dir=str(destination)))

    def dispatch_params(self):
        policy_value = self.p['policy']
        digest = hashlib.sha256(canonical(policy_value)).hexdigest()
        (self.directory / 'bolt-project.yaml').write_text('name: nest\n')
        params = dict(targets=['fixture-host'], mode='lifecycle', policy=policy_value,
                      observations=self.p['inputs'], reboot=True, maintenance=None,
                      output_dir='/modules/nest/.nest-update/' + digest)
        return dict(action='start', project=str(self.directory), source='f' * 40, params=params)

    def test_dispatch_uses_one_existing_native_unit_not_a_new_supervisor(self):
        p = self.dispatch_params()
        calls = []

        def commands(argv):
            calls.append(argv)
            if argv[:1] == ['git']:
                return p['source'] if argv[-1] == 'HEAD' else ''
            return ''

        with patch.object(dispatch, 'command', side_effect=commands), patch.object(dispatch.socket, 'gethostname', return_value='fixture-controller'):
            result = dispatch.run(p)
            self.assertTrue(result['dispatch_requested'])
            self.assertFalse(result['completed'])
            self.assertEqual(len([argv for argv in calls if argv[0] == 'systemd-run']), 1)
            native = next(argv for argv in calls if argv[0] == 'systemd-run')
            self.assertIn('nest::host::update', native)
            self.assertNotIn('ssh', native)
            with self.assertRaises(FileExistsError):
                dispatch.run(p)

    def test_active_controller_unit_is_never_restarted(self):
        p = self.dispatch_params()

        def commands(argv):
            if argv[:1] == ['git']:
                return p['source'] if argv[-1] == 'HEAD' else ''
            if argv[:1] == ['systemctl']:
                return 'active'
            return ''

        with patch.object(dispatch, 'command', side_effect=commands), patch.object(dispatch.socket, 'gethostname', return_value='fixture-controller'):
            dispatch.run(p)
            with self.assertRaises(ValueError):
                dispatch.run(dict(p, action='resume'))

    def test_stale_controller_source_refuses_before_dispatch(self):
        p = self.dispatch_params()
        with patch.object(dispatch, 'command', return_value='e' * 40), self.assertRaises(ValueError):
            dispatch.run(p)

    def test_export_reads_actual_reference_graph_not_private_logs(self):
        digest = self.bound['policy_sha256']
        child = publish_document(dict(schema=1, kind='nest_update_canary', native_exit=0), self.directory, 'canary-fixture')
        remote = dict(child, path='/modules/nest/.nest-update/' + digest + '/' + Path(child['path']).name)
        publish_document(dict(schema=1, kind='nest_update_lifecycle', child=remote), self.directory, 'lifecycle-result-' + digest)
        (self.directory / 'bolt.private.log').write_text('private sentinel')
        exported = dispatch.collect(self.directory, self.bound)
        self.assertEqual(len(exported['files']), 2)
        self.assertNotIn('private sentinel', json.dumps(exported))
        Path(child['path']).unlink()
        with self.assertRaises(FileNotFoundError):
            dispatch.collect(self.directory, self.bound)


if __name__ == '__main__':
    unittest.main()
