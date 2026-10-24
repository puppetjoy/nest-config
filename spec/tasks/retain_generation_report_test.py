#!/usr/bin/env python3
"""Supervisor-only generation retention fixtures; no host or native storage."""

import copy
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
TASK = ROOT / 'tasks/retain_generation_report.py'
M = runpy.run_path(str(TASK))


def fixture(verify=False, check=True):
    policy = dict(hostname='fixture-host', release='sha256:' + 'a' * 64, pool_guid='123', destination_guid='456')
    observed = dict(dataset='pool/crypt/generations/fixture', creation_txg='789', state_dataset='pool/crypt/nest-updates',
                    state_guid='800', current='pool/crypt/ROOT/A', boot_id='12345678-1234-1234-1234-123456789abc')
    row: dict = dict(schema=1, kind='nest_generation_verification_report' if verify else 'nest_generation_transfer_report',
               policy=policy, policy_sha256=hashlib.sha256(M['R']['canonical'](policy)).hexdigest(),
               read_only=check, sealed=verify or not check, reset_authorized=False)
    if verify:
        row.update(generation=observed, transfer_receipt_sha256='c' * 64, reset_capacity_admitted=False)
    else:
        row.update(source=dict(observed, source_mount={'source': 'private-sentinel', 'options': 'private-sentinel'}),
                   capacity=dict(apparent_bytes=1000, available_bytes=1000000, physical_free_bytes=1000000))
    return policy, row


class RetentionTests(unittest.TestCase):
    def call(self, params):
        return subprocess.run([sys.executable, str(TASK)], input=json.dumps(params), text=True,
                              capture_output=True, cwd=ROOT / 'spec', timeout=10)

    def test_all_modes_bind_identity_and_do_not_retain_mount_details(self):
        for verify, check in ((False, True), (False, False), (True, True)):
            policy, row = fixture(verify, check)
            before = copy.deepcopy(row)
            result = M['project'](json.dumps(row), policy, check, verify)
            self.assertEqual(result['sealed'], verify or not check)
            self.assertEqual(result['policy_sha256'], row['policy_sha256'])
            self.assertNotIn('private-sentinel', json.dumps(result))
            self.assertFalse(result['reset_authorized'])
            self.assertFalse(result['reset_capacity_admitted'])
            self.assertEqual(row, before)

    def test_wrong_mode_identity_hash_schema_unknown_and_boolean_flags_refuse(self):
        policy, good = fixture(True)
        for change in ({'schema': True}, {'read_only': 1}, {'sealed': 1}, {'reset_authorized': 0},
                       {'reset_capacity_admitted': True}, {'policy_sha256': 'f' * 64},
                       {'policy': dict(policy, hostname='other')}, {'transfer_receipt_sha256': 'bad'},
                       {'private': 'private-sentinel'}, {'kind': 'nest_generation_transfer_report'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                M['project'](json.dumps(dict(good, **change)), policy, True, True)

    def test_changed_dataset_state_or_boot_identity_refuses(self):
        policy, good = fixture(True)
        for key, value in [('dataset', 'other/generation'), ('state_dataset', 'pool/crypt/ROOT/A/state'),
                           ('state_dataset', 'pool/crypt/generations/fixture/child'), ('current', 'pool/crypt/ROOT/C'),
                           ('creation_txg', '0'), ('state_guid', True), ('boot_id', 'unknown')]:
            row = copy.deepcopy(good)
            row['generation'][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                M['project'](json.dumps(row), policy, True, True)

    def test_invalid_capacity_duplicate_nonfinite_and_oversized_refuse(self):
        policy, good = fixture()
        for value in (True, -1, 1.5, 2 ** 64):
            row = copy.deepcopy(good)
            row['capacity']['apparent_bytes'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                M['project'](json.dumps(row), policy, True, False)
        for raw in ('{"schema":1,"schema":1}', '{"schema":NaN}', 'x' * 32769):
            with self.subTest(raw=raw[:80]), self.assertRaises(ValueError):
                M['project'](raw, policy, True, False)

    def test_readonly_directory_preflight_and_missing_or_symlink_refusal(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary).resolve()
            result = self.call({'output_dir': str(target)})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(json.loads(result.stdout)['read_only'])
            self.assertEqual(list(target.iterdir()), [])
            link = target / 'link'
            link.symlink_to(target, target_is_directory=True)
            for path in (link, target / 'missing'):
                self.assertNotEqual(self.call({'output_dir': str(path)}).returncode, 0)

    def test_real_publish_reopen_idempotency_and_conflicting_bytes_refuse(self):
        policy, row = fixture(True)
        with tempfile.TemporaryDirectory() as temporary:
            params = dict(output_dir=str(Path(temporary).resolve()), policy=policy, report=json.dumps(row), check=True, verify_only=True)
            first = self.call(params)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            receipt = json.loads(first.stdout)
            path = Path(receipt['path'])
            payload = path.read_bytes()
            self.assertEqual(hashlib.sha256(payload).hexdigest(), receipt['sha256'])
            self.assertEqual(len(payload), receipt['bytes'])
            self.assertEqual(json.loads(payload)['hostname'], policy['hostname'])
            self.assertTrue(receipt['readback_verified'])
            self.assertEqual(self.call(params).stdout, first.stdout)
            path.write_bytes(b'conflict')
            failed = self.call(params)
            self.assertEqual(failed.returncode, 1)
            self.assertEqual(path.read_bytes(), b'conflict')
            self.assertNotIn('Traceback', failed.stdout + failed.stderr)

    def test_preparation_binding_survives_publication_and_separates_stages_and_transactions(self):
        policy, row = fixture(True)
        with tempfile.TemporaryDirectory() as temporary:
            params = dict(output_dir=str(Path(temporary).resolve()), policy=policy, report=json.dumps(row), check=True, verify_only=True)
            paths = set()
            for transaction, stage, digest in [('one', 'preflight', 'd'), ('one', 'initiation', 'd'),
                                               ('two', 'preflight', 'd'), ('one', 'preflight', 'e')]:
                bound = dict(transaction=transaction, stage=stage, policy_sha256=digest * 64)
                preflight = self.call(dict(output_dir=params['output_dir'], binding=bound))
                self.assertEqual(preflight.returncode, 0, preflight.stdout + preflight.stderr)
                self.assertEqual(json.loads(preflight.stdout)['preparation'], bound)
                published = self.call(dict(params, binding=bound))
                self.assertEqual(published.returncode, 0, published.stdout + published.stderr)
                receipt = json.loads(published.stdout)
                raw = Path(receipt['path']).read_bytes()
                self.assertEqual(receipt['preparation'], bound)
                self.assertEqual(json.loads(raw)['preparation'], bound)
                self.assertEqual(hashlib.sha256(raw).hexdigest(), receipt['sha256'])
                self.assertEqual(len(raw), receipt['bytes'])
                self.assertEqual(self.call(dict(params, binding=bound)).stdout, published.stdout)
                paths.add(receipt['path'])
            self.assertEqual(len(paths), 4)
            legacy = self.call(params)
            self.assertEqual(legacy.returncode, 0, legacy.stdout + legacy.stderr)
            receipt = json.loads(legacy.stdout)
            self.assertNotIn('preparation', receipt)
            self.assertEqual(Path(receipt['path']).read_bytes(), M['R']['canonical'](M['project'](params['report'], policy, True, True)))

    def test_invalid_preparation_binding_refuses_preflight_and_publication_without_artifacts(self):
        policy, row = fixture(True)
        good = dict(transaction='one', policy_sha256='d' * 64, stage='preflight')
        bad = [None, [], {}, dict(good, transaction=True), dict(good, transaction='bad id'),
               dict(good, transaction='x' * 65), dict(good, policy_sha256='D' * 64),
               dict(good, stage=True), dict(good, stage='accepted'), dict(good, private='private-sentinel')]
        with tempfile.TemporaryDirectory() as temporary:
            target = str(Path(temporary).resolve())
            for bound in bad:
                for params in ({}, dict(report=json.dumps(row), policy=policy, check=True, verify_only=True)):
                    result = self.call(dict(params, output_dir=target, binding=bound))
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertNotIn('private-sentinel', result.stdout + result.stderr)
                    self.assertEqual(list(Path(target).iterdir()), [])
            for check in (True, False):
                policy, row = fixture(False, check)
                result = self.call(dict(output_dir=target, binding=good, report=json.dumps(row), policy=policy, check=check, verify_only=False))
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertEqual(list(Path(target).iterdir()), [])

    def test_missing_report_fields_and_private_errors_fail_without_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            for params in ({'policy': {}}, {'report': 'private-sentinel'}, {'extra': 'private-sentinel'}):
                result = self.call(dict(params, output_dir=str(Path(temporary).resolve())))
                self.assertEqual(result.returncode, 1)
                self.assertNotIn('private-sentinel', result.stdout + result.stderr)
                self.assertEqual(list(Path(temporary).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
