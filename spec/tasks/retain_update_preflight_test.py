#!/usr/bin/env python3
"""Offline planner transport fixtures, not real capacity or ZFS observations."""

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tasks'))
from retain_update_preflight import project

RELEASE = 'sha256:' + 'a' * 64


def fixture():
    generation = {'hostname': 'fixture-host', 'release': RELEASE, 'pool_guid': '123',
                  'destination_guid': '456', 'destination': '/var/lib/nest/generations/' + 'a' * 64}
    inputs = {'transaction': 'fixture', 'generation_policy': generation,
              'root_generation': generation['destination'], 'capacity_policy': '/fixture/capacity.json'}
    observed = {'accounting_contract': 2, 'stage': 'backup', 'private': 'private-sentinel'}
    capacity = {'admission': 'admitted', 'admitted': True, 'observations': observed,
                'policy_sha256': 'b' * 64,
                'observations_sha256': hashlib.sha256(json.dumps(observed, separators=(',', ':')).encode()).hexdigest()}
    host = {'hostname': 'fixture-host', 'pool_guid': '123', 'current': 'tank/ROOT/A', 'target': 'tank/ROOT/B',
            'boot_id': '11111111-2222-3333-4444-555555555555', 'private': 'private-sentinel',
            'current_tree': [{'dataset': 'tank/ROOT/A', 'guid': '111', 'mountpoint': '/'}], 'alternate_tree': []}
    source = {'path': inputs['root_generation'], 'release': RELEASE, 'guid': '456',
              'dataset': 'tank/generation', 'creation_txg': '789'}
    preflight = {'read_only': True, 'capacity_admission': 'admitted', 'capacity': capacity, 'host': host,
                 'source': source, 'shared_state': {'dataset': 'tank/nest-updates', 'guid': '987', 'pool_guid': '123'},
                 'policy': {'cli_sha256': 'c' * 64, 'filter_sha256': 'd' * 64}}
    row = {'schema': 1, 'kind': 'reset_plan', 'read_only': True, 'observation_success': True,
           'steps': ['backup', 'mount', 'sync', 'kernel', 'unmount', 'activate'], 'replaces_alternate': True,
           'current': 'tank/ROOT/A', 'target': 'tank/ROOT/B', 'destination': '/mnt/B',
           'transaction_preflight': preflight, 'capacity': capacity, 'source_identity': {'source_sha256': 'c' * 64}}
    return inputs, row


class RetainPreflightTest(unittest.TestCase):
    def test_exact_native_admission_is_projected_without_private_accounting(self):
        inputs, row = fixture()
        result = project(json.dumps(row), 'fixture-host', RELEASE, inputs)
        self.assertTrue(result['read_only'] and result['capacity_admitted'])
        self.assertFalse(result['reset_authorized'])
        self.assertEqual(result['accounting_contract'], 2)
        self.assertNotIn('private-sentinel', json.dumps(result))
        self.assertEqual(result['source']['guid'], '456')

    def test_missing_old_unknown_or_contradictory_admission_refuses(self):
        changes = [({'schema': True}, None), ({'read_only': False}, None), ({'observation_success': False}, None),
                   ({'steps': ['kernel']}, None), ({'target': 'tank/ROOT/A'}, None),
                   ({'capacity': {}}, None), ({'transaction_preflight': {}}, None)]
        for change, _ in changes:
            inputs, row = fixture()
            row.update(change)
            with self.subTest(change=change), self.assertRaises((ValueError, KeyError, TypeError)):
                project(json.dumps(row), 'fixture-host', RELEASE, inputs)
        for value in [None, False, 'unknown', 'denied']:
            inputs, row = fixture()
            row['capacity']['admission'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                project(json.dumps(row), 'fixture-host', RELEASE, inputs)
        for value in [1, 4, True, 2.0, 3.0, None, '2', '3']:
            inputs, row = fixture()
            row['capacity']['observations']['accounting_contract'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                project(json.dumps(row), 'fixture-host', RELEASE, inputs)

    def test_readable_contracts_are_retained_without_relabeling_or_authorization(self):
        for contract in (2, 3):
            inputs, row = fixture()
            observed = row['capacity']['observations']
            observed['accounting_contract'] = contract
            if contract == 3:
                observed['shared_ancestors'] = {'tank': {'private': 'private-sentinel'}}
            row['capacity']['observations_sha256'] = hashlib.sha256(
                json.dumps(observed, separators=(',', ':')).encode()).hexdigest()
            with self.subTest(contract=contract), tempfile.TemporaryDirectory() as directory:
                params = {'report': json.dumps(row), 'hostname': 'fixture-host', 'release': RELEASE,
                          'inputs': inputs, 'output_dir': directory}
                run = subprocess.run([sys.executable, str(ROOT / 'tasks/retain_update_preflight.py')],
                                     input=json.dumps(params), text=True, capture_output=True)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                receipt = json.loads(run.stdout)
                content = Path(receipt['path']).read_bytes()
                retained = json.loads(content)
                self.assertEqual(retained['accounting_contract'], contract)
                self.assertEqual(hashlib.sha256(content).hexdigest(), receipt['sha256'])
                self.assertTrue(receipt['readback_verified'])
                self.assertFalse(retained['reset_authorized'])
                self.assertNotIn(b'private-sentinel', content)

    def test_corrupt_or_wrong_identity_refuses(self):
        for section, key, value in [('host', 'hostname', 'other-host'), ('host', 'pool_guid', '999'),
                                    ('host', 'current', 'tank/ROOT/old'), ('host', 'boot_id', 'unknown'),
                                    ('source', 'guid', '999'), ('source', 'release', 'sha256:' + 'e' * 64),
                                    ('source', 'path', '/nest/hosts/fixture-host'), ('source', 'dataset', 'other/generation'),
                                    ('shared_state', 'dataset', 'tank/ROOT/A/state'), ('shared_state', 'pool_guid', '999'),
                                    ('policy', 'cli_sha256', 'e' * 64), ('capacity', 'observations_sha256', 'f' * 64)]:
            inputs, row = fixture()
            row['transaction_preflight'][section][key] = value
            with self.subTest(section=section, key=key), self.assertRaises((ValueError, KeyError, TypeError)):
                project(json.dumps(row), 'fixture-host', RELEASE, inputs)
        inputs, row = fixture()
        row['capacity']['observations']['stage'] = 'activation'
        with self.assertRaises(ValueError):
            project(json.dumps(row), 'fixture-host', RELEASE, inputs)

    def test_actual_stdin_publication_readback_and_idempotence(self):
        inputs, row = fixture()
        with tempfile.TemporaryDirectory() as directory:
            params = {'report': json.dumps(row), 'hostname': 'fixture-host', 'release': RELEASE,
                      'inputs': inputs, 'output_dir': directory}
            receipts = []
            for _ in range(2):
                run = subprocess.run([sys.executable, str(ROOT / 'tasks/retain_update_preflight.py')],
                                     input=json.dumps(params), text=True, capture_output=True)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                receipt = json.loads(run.stdout)
                content = Path(receipt['path']).read_bytes()
                self.assertEqual(hashlib.sha256(content).hexdigest(), receipt['sha256'])
                self.assertEqual(len(content), receipt['bytes'])
                self.assertTrue(receipt['readback_verified'])
                self.assertNotIn(b'private-sentinel', content)
                receipts.append(receipt)
            self.assertEqual(receipts[0], receipts[1])
            self.assertEqual(len(list(Path(directory).iterdir())), 1)

    def test_preparation_context_is_retained_and_changes_content_identity(self):
        inputs, row = fixture()
        with tempfile.TemporaryDirectory() as directory:
            params = {'report': json.dumps(row), 'hostname': 'fixture-host', 'release': RELEASE,
                      'inputs': inputs, 'output_dir': directory}
            receipts = []
            for binding in [None, {'transaction': 'fixture', 'policy_sha256': 'e' * 64, 'stage': 'preflight'},
                            {'transaction': 'fixture', 'policy_sha256': 'f' * 64, 'stage': 'preflight'},
                            {'transaction': 'fixture', 'policy_sha256': 'e' * 64, 'stage': 'initiation'}]:
                selected = dict(params, **({'binding': binding} if binding is not None else {}))
                run = subprocess.run([sys.executable, str(ROOT / 'tasks/retain_update_preflight.py')],
                                     input=json.dumps(selected), text=True, capture_output=True)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                receipt = json.loads(run.stdout)
                content = Path(receipt['path']).read_bytes()
                report = json.loads(content)
                self.assertEqual(receipt.get('preparation'), binding)
                self.assertEqual(report.get('preparation'), binding)
                self.assertEqual(hashlib.sha256(content).hexdigest(), receipt['sha256'])
                self.assertTrue(receipt['readback_verified'])
                self.assertFalse(receipt['reset_authorized'])
                self.assertNotIn(b'private-sentinel', content)
                receipts.append(receipt)
            self.assertEqual(len({receipt['path'] for receipt in receipts}), 4)

    def test_invalid_or_other_transaction_binding_never_publishes(self):
        inputs, row = fixture()
        binding = {'transaction': 'fixture', 'policy_sha256': 'e' * 64, 'stage': 'preflight'}
        invalid = [None, [], {}, dict(binding, transaction='other'), dict(binding, transaction='bad id'),
                   dict(binding, policy_sha256=True), dict(binding, policy_sha256='e' * 63),
                   dict(binding, stage='accepted'), dict(binding, private='private-sentinel')]
        with tempfile.TemporaryDirectory() as directory:
            for value in invalid:
                params = {'report': json.dumps(row), 'hostname': 'fixture-host', 'release': RELEASE,
                          'inputs': inputs, 'output_dir': directory, 'binding': value}
                run = subprocess.run([sys.executable, str(ROOT / 'tasks/retain_update_preflight.py')],
                                     input=json.dumps(params), text=True, capture_output=True)
                with self.subTest(binding=value):
                    self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
                    self.assertNotIn('private-sentinel', run.stdout + run.stderr)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_invalid_stdin_or_directory_never_publishes(self):
        inputs, row = fixture()
        with tempfile.TemporaryDirectory() as directory:
            params = {'report': json.dumps(row), 'hostname': 'fixture-host', 'release': RELEASE,
                      'inputs': inputs, 'output_dir': directory + '/missing'}
            for raw in [json.dumps(params), '[]', '{"private":"private-sentinel","private":2}', 'x' * 524289]:
                run = subprocess.run([sys.executable, str(ROOT / 'tasks/retain_update_preflight.py')],
                                     input=raw, text=True, capture_output=True)
                self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
                self.assertNotIn('private-sentinel', run.stdout + run.stderr)
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
