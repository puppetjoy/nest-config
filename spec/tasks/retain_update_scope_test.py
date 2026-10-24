"""Actual supervisor scope publication using disposable native report fixtures."""

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from typing import Any
from unittest import mock

from retain_update_report_test import fixture, retainer, with_reboot

ROOT = Path(__file__).resolve().parents[2]
TASK = ROOT / 'tasks/retain_update_scope.py'
sys.path.insert(0, str(TASK.parent))
spec = importlib.util.spec_from_file_location('scope_retainer', TASK)
assert spec is not None and spec.loader is not None
scope = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scope)


class ScopeRetentionTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name).resolve()
        self.hosts = ['fixture-host', 'fixture-peer']
        self.policy = {'schema': 1, 'kind': 'nest_update_wave_policy', 'release': 'sha256:' + 'a' * 64,
                       'config_source': 'b' * 40, 'max_parallel': 2, 'domains': ['fixture-serial'],
                       'hosts': [{'name': name, 'platform': 'fixture', 'kernel': 'fixture-kernel',
                                  'domains': ['fixture-serial']} for name in self.hosts],
                       'excluded': ['fixture-console'], 'canaries': ['fixture-host']}
        self.observations = {name: {'transaction': 'fixture-report'} for name in self.hosts}
        self.arguments: dict[str, Any] = dict(action='retain', mode='prepare', policy=self.policy, targets=self.hosts,
                              observations=self.observations, output_dir=str(self.directory))
        self.reports = [fixture(), fixture()]
        self.reports[1]['host']['hostname'] = self.hosts[1]
        self.refresh()

    def tearDown(self):
        self.temporary.cleanup()

    def refresh(self):
        self.arguments['waves'] = [[retainer.publish(retainer.project(json.dumps(data), 'fixture-report',
                                   self.policy['release'], name), self.directory)]
                                   for name, data in zip(self.hosts, self.reports)]

    def run_task(self, **changes):
        result = subprocess.run([sys.executable, '-B', str(TASK)], input=json.dumps(dict(self.arguments, **changes)),
                                capture_output=True, text=True, check=False)
        self.assertNotIn('private sentinel', result.stdout + result.stderr)
        return result.returncode, json.loads(result.stdout)

    def test_complete_scope_reopens_every_host_and_durably_retains_exact_policy(self):
        self.arguments['waves'][0][0]['private'] = 'private sentinel'
        self.arguments['waves'][0][0]['backup_verification'] = ['private sentinel']
        code, receipt = self.run_task()
        self.assertEqual(code, 0, receipt)
        raw = Path(receipt['path']).read_bytes()
        report = json.loads(raw)
        self.assertEqual(receipt['sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(receipt['bytes'], len(raw))
        self.assertEqual(report['policy'], self.policy)
        self.assertEqual(report['observations'], self.observations)
        self.assertEqual(report['host_count'], 2)
        self.assertEqual(report['policy_sha256'], scope.context(self.arguments)['policy_sha256'])
        self.assertTrue(receipt['readback_verified'])
        self.assertFalse(receipt['execution_authorized'])
        self.assertFalse(receipt['acceptance_recorded'])
        self.assertEqual(receipt['reboot_eligible'], [])
        self.assertNotIn(b'private sentinel', raw)
        self.assertEqual(self.run_task()[1], receipt)

    def test_observe_requires_actual_retained_observation_but_not_prepared_state(self):
        self.assertEqual(self.run_task(mode='observe')[0], 1)
        for data in self.reports:
            data['state'] = 'stopped'
            data['success'] = False
            data['observation'] = dict(boot_id=data['host']['boot_id'], boot_changed=False,
                                       current=data['host']['current'], next_boot=data['host']['target'],
                                       expected_target_booted=False, accepted=False)
        self.refresh()
        code, receipt = self.run_task(mode='observe')
        self.assertEqual(code, 0, receipt)
        self.assertEqual(json.loads(Path(receipt['path']).read_bytes())['mode'], 'observe')
        self.assertEqual(self.run_task()[0], 1)

    def test_check_validates_scope_and_destination_without_creating_files(self):
        before = set(self.directory.iterdir())
        self.assertEqual(self.run_task(action='check', waves=None), (0, {
            'destination_checked': True, 'scope_checked': True, 'host_action_performed': False}))
        self.assertEqual(set(self.directory.iterdir()), before)
        self.assertEqual(self.run_task(action='check', output_dir=str(self.directory / 'missing'))[0], 1)
        self.assertEqual(self.run_task(action='execute')[0], 1)

    def test_missing_duplicate_reordered_extra_and_incomplete_hosts_refuse(self):
        original = self.arguments['waves']
        for waves in ([], original[:1], original[::-1], [original[0], original[0]],
                      [original[0], []], [original[0] + original[1], original[1]], None):
            self.assertEqual(self.run_task(waves=waves)[0], 1, waves)
        for changes in ({'targets': self.hosts[:1]}, {'observations': {}},
                        {'targets': self.hosts + ['fixture-console']}):
            self.assertEqual(self.run_task(**changes)[0], 1)
        self.assertEqual(list(self.directory.glob('scope-*.json')), [])

    def test_wrong_receipt_context_flags_lengths_or_digest_refuse(self):
        changes = {'id': 'other', 'hostname': 'other', 'release': 'sha256:' + 'f' * 64,
                   'phase_count': True, 'bytes': True, 'sha256': 'f' * 64,
                   'state': 'accepted', 'cli_accepted': 0, 'cli_finalized': True,
                   'observation_retained': True, 'readback_verified': False}
        for key, value in changes.items():
            waves = copy.deepcopy(self.arguments['waves'])
            waves[0][0][key] = value
            self.assertEqual(self.run_task(waves=waves)[0], 1, key)
        self.assertEqual(list(self.directory.glob('scope-*.json')), [])

    def test_missing_corrupt_symlink_hardlink_and_fifo_reports_refuse_without_hanging(self):
        path = Path(self.arguments['waves'][0][0]['path'])
        raw = path.read_bytes()
        path.unlink()
        self.assertEqual(self.run_task()[0], 1)
        path.write_bytes(b'corrupt')
        self.assertEqual(self.run_task()[0], 1)
        path.unlink()
        other = self.directory / 'other'
        other.write_bytes(raw)
        path.symlink_to(other)
        self.assertEqual(self.run_task()[0], 1)
        path.unlink()
        os.link(other, path)
        self.assertEqual(self.run_task()[0], 1)
        path.unlink()
        os.mkfifo(path)
        self.assertEqual(self.run_task()[0], 1)
        self.assertEqual(list(self.directory.glob('scope-*.json')), [])

    def test_wrong_directory_and_noncanonical_path_refuse(self):
        original = self.arguments['waves'][0][0]['path']
        for path in (original.replace('/fixture-host-', '/../fixture-host-'), str(self.directory / 'other.json')):
            waves = copy.deepcopy(self.arguments['waves'])
            waves[0][0]['path'] = path
            self.assertEqual(self.run_task(waves=waves)[0], 1)

    def test_attempted_reboot_and_accepted_native_reports_are_not_preparation(self):
        self.reports[0] = with_reboot(self.reports[0], intent=True)
        self.refresh()
        self.assertEqual(self.run_task()[0], 1)
        self.reports[0] = fixture(state='accepted', schema=2)
        self.refresh()
        self.assertEqual(self.run_task()[0], 1)

    def test_changed_report_during_publication_never_returns_success(self):
        original = scope.publish_document
        path = Path(self.arguments['waves'][1][0]['path'])

        def change_after_publish(*args):
            receipt = original(*args)
            path.unlink()
            return receipt

        with mock.patch.object(scope, 'publish_document', side_effect=change_after_publish):
            with self.assertRaises(OSError):
                scope.retain(self.arguments, scope.context(self.arguments))
        self.assertEqual(len(list(self.directory.glob('scope-*.json'))), 1)

    def test_bad_duplicate_or_oversized_input_is_bounded_and_sanitized(self):
        for raw in ('private sentinel', '[]', 'x' * (scope.LIMIT + 1),
                    json.dumps(self.arguments).replace('"action": "retain"', '"action": "check", "action": "retain"')):
            result = subprocess.run([sys.executable, '-B', str(TASK)], input=raw, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 1)
            self.assertNotIn('private sentinel', result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
