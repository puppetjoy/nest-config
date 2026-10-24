"""Real stdin, retained admission readback and sanitized continuity publication."""

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tasks'))
from retain_update_reboot import retain
from retain_update_reboot_observation import admission
from retain_update_reboot_test import plan
from retain_update_report_test import with_reboot

TASK = Path(__file__).resolve().parents[2] / 'tasks/retain_update_reboot_observation.py'


class RebootObservationTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name).resolve()
        self.context = dict(transaction='fixture-report', release='sha256:' + 'a' * 64,
                            hostname='fixture-host', output_dir=str(self.directory))
        self.before = plan()
        self.receipt = retain(dict(self.context, report=json.dumps(self.before)))

    def tearDown(self):
        self.temporary.cleanup()

    def run_task(self, data=None, **changes):
        arguments = dict(self.context, action='retain', admission=self.receipt,
                         report=json.dumps(self.after() if data is None else data))
        arguments.update(changes)
        result = subprocess.run([sys.executable, '-B', str(TASK)], input=json.dumps(arguments),
                                capture_output=True, text=True, check=False)
        self.assertNotIn('private sentinel', result.stdout + result.stderr)
        return result.returncode, json.loads(result.stdout)

    def after(self, changed=False, intent=False, native_exit=0):
        data = with_reboot(plan('already_booted' if changed else 'already_requested'),
                           intent=intent, native_exit=native_exit)
        for key in ('read_only', 'reboot_eligible', 'reboot_reason'):
            del data[key]
        return data

    def test_all_native_outcomes_are_distinct_from_actual_target_boot(self):
        for changed in (False, True):
            for intent, native_exit, outcome in ((True, 0, 'unknown'), (False, 0, 'returned_success'),
                                                (False, 23, 'returned_failure')):
                code, receipt = self.run_task(self.after(changed, intent, native_exit))
                self.assertEqual(code, 0, receipt)
                raw = Path(receipt['path']).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), receipt['sha256'])
                self.assertEqual(len(raw), receipt['bytes'])
                self.assertTrue(receipt['readback_verified'])
                self.assertIs(receipt['target_boot_observed'], changed)
                self.assertEqual(receipt['submission_outcome'], outcome)
                self.assertFalse(receipt['resubmission_allowed'])
                self.assertFalse(receipt['acceptance_recorded'])
                self.assertFalse(receipt['execution_requested'])
                document = json.loads(raw)
                self.assertEqual(document['admission']['sha256'], self.receipt['sha256'])
                self.assertIs(document['report']['reboot_requested'], None if intent else native_exit == 0)

    def test_original_boot_without_attempt_is_observed_not_permission(self):
        code, receipt = self.run_task(plan())
        self.assertEqual(code, 0, receipt)
        self.assertEqual(receipt['submission_outcome'], 'not_attempted')
        self.assertFalse(receipt['target_boot_observed'])
        self.assertFalse(receipt['resubmission_allowed'])

    def test_changed_boot_without_native_intent_refuses_attribution(self):
        self.assertEqual(self.run_task(plan('already_booted'))[0], 1)

    def test_check_reopens_admission_without_publishing_or_acting(self):
        code, receipt = self.run_task(action='check', report=None)
        self.assertEqual(code, 0, receipt)
        self.assertTrue(receipt['admission_readback_verified'])
        self.assertFalse(receipt['host_action_performed'])
        self.assertEqual(len(list(self.directory.iterdir())), 1)
        self.assertEqual(self.run_task(action='execute')[0], 1)

    def test_missing_or_modified_admission_refuses_before_status_use(self):
        path = Path(self.receipt['path'])
        original = path.read_bytes()
        path.write_text('private sentinel')
        self.assertEqual(self.run_task(action='check')[0], 1)
        path.unlink()
        self.assertEqual(self.run_task(action='check')[0], 1)
        path.write_bytes(original)
        for key, value in (('bytes', True), ('sha256', 'b' * 64), ('readback_verified', False),
                           ('transaction', 'wrong'), ('reboot_reason', 'already_booted'), ('read_only', False)):
            receipt = dict(self.receipt, **{key: value})
            self.assertEqual(self.run_task(action='check', admission=receipt)[0], 1, key)

    def test_symlink_or_cross_directory_admission_refuses(self):
        path = Path(self.receipt['path'])
        moved = path.with_suffix('.moved')
        path.rename(moved)
        path.symlink_to(moved)
        self.assertEqual(self.run_task(action='check')[0], 1)
        self.assertEqual(self.run_task(output_dir=str(self.directory / 'absent'))[0], 1)
        self.assertEqual(self.run_task(admission=dict(self.receipt, path=str(moved)))[0], 1)

    def test_admission_replacement_between_validation_and_open_refuses(self):
        path = Path(self.receipt['path'])
        moved = path.with_suffix('.moved')
        original = os.open

        def replace_before_open(candidate, *args, **kwargs):
            if candidate == path.name and not path.is_symlink():
                path.rename(moved)
                path.symlink_to(moved)
            return original(candidate, *args, **kwargs)

        with mock.patch.object(os, 'open', replace_before_open):
            with self.assertRaises((ValueError, OSError)):
                admission(dict(self.context, admission=self.receipt))

    def test_all_immutable_transaction_bindings_must_match(self):
        data = self.after()
        changes = [('host', 'pool_guid', '999'), ('host', 'boot_id', '22345678-1234-1234-1234-123456789abc'),
                   ('shared_state', 'guid', '999'), ('source', 'guid', '999'), ('policy', 'cli_sha256', 'b' * 64)]
        for section, key, value in changes:
            changed = copy.deepcopy(data)
            changed[section][key] = value
            self.assertEqual(self.run_task(changed)[0], 1, (section, key))
        for key, value in (('host_identity_sha256', 'f' * 64), ('release', 'sha256:' + 'b' * 64), ('id', 'wrong')):
            changed = copy.deepcopy(data)
            changed[key] = value
            self.assertEqual(self.run_task(changed)[0], 1, key)
        for tree in ('target_tree',):
            changed = copy.deepcopy(data)
            changed[tree][0]['guid'] = '999'
            self.assertEqual(self.run_task(changed)[0], 1)
        changed = copy.deepcopy(data)
        changed['phases'][0]['attempt'] += 1
        self.assertEqual(self.run_task(changed)[0], 1)

    def test_existing_intent_may_only_acquire_valid_completion(self):
        self.before = with_reboot(plan('already_requested'), intent=True)
        self.receipt = retain(dict(self.context, report=json.dumps(self.before)))
        self.assertEqual(self.run_task(self.after(intent=True))[0], 0)
        self.assertEqual(self.run_task(self.after())[0], 0)
        self.assertEqual(self.run_task(plan())[0], 1)
        changed = self.after()
        changed['reboot']['requested_at'] = '2026-10-24T00:00:00Z'
        changed['reboot']['finished_at'] = '2026-10-24T00:00:01Z'
        self.assertEqual(self.run_task(changed)[0], 1)

    def test_returned_receipt_cannot_change_or_regress_to_intent(self):
        self.before = with_reboot(plan('already_requested'))
        self.receipt = retain(dict(self.context, report=json.dumps(self.before)))
        self.assertEqual(self.run_task(self.after())[0], 0)
        self.assertEqual(self.run_task(self.after(True))[0], 0)
        self.assertEqual(self.run_task(self.after(intent=True))[0], 1)
        self.assertEqual(self.run_task(self.after(native_exit=23))[0], 1)

    def test_wrong_observed_boot_current_next_or_missing_observation_refuses(self):
        for changed in (False, True):
            for key, value in (('next_boot', self.before['host']['current']),
                               ('boot_changed', not changed), ('expected_target_booted', not changed),
                               ('current', self.before['host']['current'] if changed else self.before['host']['target'])):
                data = self.after(changed)
                data['observation'][key] = value
                self.assertEqual(self.run_task(data)[0], 1, (changed, key))
        data = self.after()
        del data['observation']
        self.assertEqual(self.run_task(data)[0], 1)

    def test_private_fields_are_omitted_and_repeated_read_is_idempotent(self):
        data = self.after()
        data['private'] = 'private sentinel'
        code, receipt = self.run_task(data)
        self.assertEqual(code, 0, receipt)
        self.assertNotIn(b'private sentinel', Path(receipt['path']).read_bytes())
        self.assertEqual(self.run_task(data)[1], receipt)
        Path(receipt['path']).write_text('existing evidence')
        self.assertEqual(self.run_task(data)[0], 1)
        self.assertEqual(Path(receipt['path']).read_text(), 'existing evidence')

    def test_invalid_duplicate_or_oversized_report_is_not_published(self):
        for raw in ('private sentinel', '{}', '[]', 'x' * 262145,
                    json.dumps(self.after()).replace('"schema": 1', '"schema": 1, "schema": 1', 1)):
            self.assertEqual(self.run_task(report=raw)[0], 1)
        self.assertEqual(len(list(self.directory.iterdir())), 1)


if __name__ == '__main__':
    unittest.main()
