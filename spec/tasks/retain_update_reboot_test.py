"""Actual stdin/supervisor publication with synthetic native reboot-plan reports."""

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from retain_update_report_test import fixture, with_reboot

TASK = Path(__file__).resolve().parents[2] / 'tasks/retain_update_reboot.py'


def plan(reason='eligible'):
    data = fixture()
    if reason == 'already_requested':
        data = with_reboot(data, intent=True)
    changed = reason == 'already_booted'
    data.update(read_only=True, reboot_eligible=reason == 'eligible', reboot_reason=reason)
    data['observation'] = dict(boot_id='22345678-1234-1234-1234-123456789abc' if changed else data['host']['boot_id'],
                               boot_changed=changed, current=data['host']['target'] if changed else data['host']['current'],
                               next_boot=data['host']['target'], expected_target_booted=changed, accepted=False)
    return data


class RebootPlanTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name).resolve()
        self.arguments = dict(action='retain', transaction='fixture-report', release='sha256:' + 'a' * 64,
                              hostname='fixture-host', output_dir=str(self.directory), report=json.dumps(plan()))

    def tearDown(self):
        self.temporary.cleanup()

    def run_task(self, **changes):
        result = subprocess.run([sys.executable, '-B', str(TASK)], input=json.dumps(dict(self.arguments, **changes)),
                                capture_output=True, text=True, check=False)
        return result.returncode, json.loads(result.stdout)

    def test_retains_each_native_reason_with_exact_readback_and_no_execution(self):
        for reason in ('eligible', 'already_requested', 'already_booted'):
            code, receipt = self.run_task(report=json.dumps(plan(reason)))
            self.assertEqual(code, 0, receipt)
            raw = Path(receipt['path']).read_bytes()
            self.assertEqual(receipt['sha256'], hashlib.sha256(raw).hexdigest())
            self.assertEqual(receipt['bytes'], len(raw))
            self.assertTrue(receipt['readback_verified'])
            self.assertIs(receipt['reboot_eligible'], reason == 'eligible')
            self.assertFalse(receipt['execution_requested'])
            self.assertFalse(receipt['acceptance_recorded'])
            self.assertTrue(json.loads(raw)['read_only'])
        self.assertEqual(len(list(self.directory.glob('*.json'))), 3)

    def test_kernel_puppet_applied_exit_is_retained_without_rewriting(self):
        for reason in ('eligible', 'already_requested', 'already_booted'):
            data = plan(reason)
            data['phases'][3]['commands'] = [dict(operation='puppet', native_exit=2, success=True)]
            code, receipt = self.run_task(report=json.dumps(data))
            self.assertEqual(code, 0, receipt)
            saved = json.loads(Path(receipt['path']).read_bytes())
            self.assertEqual(saved['report']['phases'][3]['commands'][0]['native_exit'], 2)
            self.assertIs(receipt['reboot_eligible'], reason == 'eligible')

    def test_false_success_exit_cannot_be_retained_as_eligible(self):
        for operation, phase, code in (('root', 2, 2), ('modules', 3, 2), ('puppet', 2, 2),
                                       ('puppet', 3, 1), ('puppet', 3, 4), ('puppet', 3, 6)):
            data = plan()
            data['phases'][phase]['commands'] = [dict(operation=operation, native_exit=code, success=True)]
            self.assertEqual(self.run_task(report=json.dumps(data))[0], 1)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_all_attempted_outcomes_remain_ineligible(self):
        for code, intent in ((0, False), (23, False), (0, True)):
            for changed in (False, True):
                data = with_reboot(plan('already_booted' if changed else 'already_requested'), native_exit=code, intent=intent)
                result, receipt = self.run_task(report=json.dumps(data))
                self.assertEqual(result, 0, receipt)
                report = json.loads(Path(receipt['path']).read_bytes())['report']
                self.assertIs(report['reboot_requested'], data['reboot_requested'])
                self.assertFalse(receipt['reboot_eligible'])

    def test_check_is_read_only_and_execute_action_is_not_supported(self):
        code, receipt = self.run_task(action='check')
        self.assertEqual(code, 0)
        self.assertTrue(receipt['destination_checked'])
        self.assertFalse(receipt['host_action_performed'])
        self.assertEqual(self.run_task(action='execute')[0], 1)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_wrong_context_or_destination_refuses(self):
        for change in ({'transaction': 'wrong'}, {'hostname': 'wrong'}, {'release': 'sha256:' + 'b' * 64},
                       {'output_dir': str(self.directory / 'absent')}):
            self.assertEqual(self.run_task(**change)[0], 1)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_contradictory_eligibility_and_missing_observation_cannot_publish(self):
        for reason in ('eligible', 'already_requested', 'already_booted'):
            original = plan(reason)
            for key, value in (('read_only', False), ('reboot_eligible', not original['reboot_eligible']),
                               ('reboot_eligible', 1), ('reboot_reason', 'unknown'), ('observation', None)):
                data = copy.deepcopy(original)
                data[key] = value
                self.assertEqual(self.run_task(report=json.dumps(data))[0], 1, (reason, key))
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_no_intent_cannot_claim_already_requested_or_hide_as_eligible(self):
        data = plan('eligible')
        data.update(reboot_eligible=False, reboot_reason='already_requested')
        self.assertEqual(self.run_task(report=json.dumps(data))[0], 1)
        data = with_reboot(plan('eligible'))
        self.assertEqual(self.run_task(report=json.dumps(data))[0], 1)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_wrong_boot_current_next_or_missing_status_refuses(self):
        for reason in ('eligible', 'already_requested', 'already_booted'):
            for key, value in (('next_boot', fixture()['host']['current']), ('current', 'fixture/crypt/ROOT/unknown'),
                               ('boot_changed', reason != 'already_booted'), ('expected_target_booted', None)):
                data = plan(reason)
                data['observation'][key] = value
                self.assertEqual(self.run_task(report=json.dumps(data))[0], 1, (reason, key))
        data = plan()
        del data['observation']
        self.assertEqual(self.run_task(report=json.dumps(data))[0], 1)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_pending_or_stopped_cannot_be_eligible(self):
        for state in ('pending', 'stopped'):
            data = plan()
            data.update(state=state, success=False)
            self.assertEqual(self.run_task(report=json.dumps(data))[0], 1)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_repeat_is_idempotent_and_corruption_not_overwritten(self):
        code, receipt = self.run_task()
        self.assertEqual(code, 0)
        self.assertEqual(self.run_task()[1], receipt)
        path = Path(receipt['path'])
        path.write_text('conflicting fixture')
        self.assertEqual(self.run_task()[0], 1)
        self.assertEqual(path.read_text(), 'conflicting fixture')

    def test_bad_or_duplicate_input_does_not_echo_private_material(self):
        for raw in ('private sentinel', '{}', '[]', 'x' * 262145,
                    json.dumps(plan()).replace('"read_only": true', '"read_only": false, "read_only": true')):
            result = subprocess.run([sys.executable, '-B', str(TASK)], input=json.dumps(dict(self.arguments, report=raw)),
                                    capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 1)
            self.assertNotIn('private sentinel', result.stdout + result.stderr)
        self.assertEqual(list(self.directory.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
