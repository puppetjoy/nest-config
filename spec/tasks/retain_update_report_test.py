"""No host or ZFS mutation: exercise the actual stdin task across filesystems."""


import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True
TASK = Path(__file__).resolve().parents[2] / "tasks" / "retain_update_report.py"
spec = importlib.util.spec_from_file_location("retain_update_report", TASK)
assert spec is not None and spec.loader is not None
retainer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retainer)


def fixture(state="prepared", schema=1):
    tree = [{"dataset": "fixture/crypt/ROOT/A", "guid": "101", "mountpoint": "/"}]
    boot = "12345678-1234-1234-1234-123456789abc"
    return {
        "schema": schema, "kind": "reset_transaction_report", "id": "fixture-report", "state": state,
        "release": "sha256:" + "a" * 64, "success": True,
        "accepted": schema == 2, "finalized": state == "finalized", "reboot_requested": False,
        "host": {"hostname": "fixture-host", "boot_id": boot, "pool_guid": "100",
                 "current": "fixture/crypt/ROOT/A", "target": "fixture/crypt/ROOT/B",
                 "next_boot": "fixture/crypt/ROOT/A", "current_tree": tree},
        "host_identity_sha256": "b" * 64,
        "shared_state": {"dataset": "fixture/crypt/nest-updates", "guid": "102", "pool_guid": "100"},
        "source": {"path": "/fixture/releases/one", "dataset": "fixture/releases/one", "guid": "103",
                   "creation_txg": "104", "release": "sha256:" + "a" * 64},
        "policy": {"filter_sha256": "c" * 64, "cli_sha256": "d" * 64},
        "target_tree": [{"dataset": "fixture/crypt/ROOT/B", "guid": "105", "mountpoint": "/"}],
        "phases": [{"phase": phase, "state": "complete", "attempt": 1, "boot_id": boot,
                    "started_at": "2026-10-21T20:00:00Z", "finished_at": "2026-10-21T20:01:00Z",
                    "native_exit": None, "commands": []} for phase in retainer.PHASES],
    }


def with_reboot(data=None, native_exit=0, intent=False):
    data = copy.deepcopy(data if data is not None else fixture())
    data['capacity'] = {'accounting_contract': 2}
    data['reboot'] = {
        'schema': 1, 'state': 'intent' if intent else 'returned', 'boot_id': data['host']['boot_id'],
        'requested_at': '2026-10-21T20:02:00.123456Z', 'command': ['systemctl', '--no-block', 'reboot'],
    }
    if not intent:
        data['reboot'].update(finished_at='2026-10-21T20:02:01Z', native_exit=native_exit)
    data['reboot_requested'] = None if intent else native_exit == 0
    return data


class RetainUpdateReportTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.worker = self.root / "worker"
        self.supervisor = self.root / "supervisor"
        self.worker.mkdir()
        self.supervisor.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def arguments(self, data=None):
        return {"report": json.dumps(data or fixture()), "transaction": "fixture-report",
                "release": "sha256:" + "a" * 64, "hostname": "fixture-host", "output_dir": str(self.supervisor)}

    def run_task(self, arguments):
        return subprocess.run([sys.executable, str(TASK)], input=json.dumps(arguments), text=True,
                              capture_output=True, cwd=self.worker, check=False)

    def test_real_stdin_transport_reopen_and_worker_removal(self):
        source = self.worker / "remote-stdout.json"
        source.write_text(json.dumps(fixture()))
        arguments = self.arguments()
        arguments["report"] = source.read_text()
        result = self.run_task(arguments)
        self.assertEqual(result.returncode, 0, result.stdout)
        receipt = json.loads(result.stdout)
        path = Path(receipt["path"])
        self.assertEqual(path.parent, self.supervisor)
        self.assertTrue(receipt["readback_verified"])
        self.assertEqual(receipt["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(receipt["phase_count"], 6)
        self.assertEqual(path.stat().st_mode & 0o777, 0o644)
        shutil.rmtree(self.worker)
        self.assertEqual(json.loads(path.read_text())["state"], "prepared")

    def test_reboot_attempts_retain_three_valued_outcomes_without_acceptance(self):
        for state, schema in (('prepared', 1), ('accepted', 2), ('finalizing', 2), ('finalized', 2)):
            for code, intent in ((0, False), (23, False), (0, True)):
                with self.subTest(state=state, code=code, intent=intent):
                    data = with_reboot(fixture(state, schema), native_exit=code, intent=intent)
                    result = self.run_task(self.arguments(data))
                    self.assertEqual(result.returncode, 0, result.stdout)
                    retained = json.loads(Path(json.loads(result.stdout)['path']).read_bytes())
                    self.assertEqual(retained['reboot'], data['reboot'])
                    self.assertIs(retained['reboot_requested'], data['reboot_requested'])
                    self.assertFalse(retained['acceptance_independently_verified'])
                    self.assertNotIn('observation', retained)

    def test_readable_capacity_contracts_retain_reboot_outcomes_without_boot_acceptance(self):
        for contract in (2, 3):
            for code, intent in ((0, False), (23, False), (0, True)):
                data = with_reboot(native_exit=code, intent=intent)
                data['capacity']['accounting_contract'] = contract
                with self.subTest(contract=contract, code=code, intent=intent):
                    result = self.run_task(self.arguments(data))
                    self.assertEqual(result.returncode, 0, result.stdout)
                    receipt = json.loads(result.stdout)
                    content = Path(receipt['path']).read_bytes()
                    retained = json.loads(content)
                    self.assertEqual(hashlib.sha256(content).hexdigest(), receipt['sha256'])
                    self.assertTrue(receipt['readback_verified'])
                    self.assertIs(retained['reboot_requested'], data['reboot_requested'])
                    self.assertFalse(retained['acceptance_independently_verified'])

    def test_unknown_capacity_contract_cannot_publish_reboot_receipts(self):
        for contract in (None, True, 2.0, 3.0, '2', '3', 1, 4):
            data = with_reboot()
            data['capacity']['accounting_contract'] = contract
            with self.subTest(contract=contract):
                self.assertEqual(self.run_task(self.arguments(data)).returncode, 1)
        self.assertEqual(list(self.supervisor.iterdir()), [])

    def test_reboot_receipt_strict_shape_binding_and_calendar_validation(self):
        changes = [
            {'schema': True}, {'schema': 2}, {'state': 'submitted'}, {'boot_id': 'other'},
            {'command': ['systemctl', '--force', 'reboot']}, {'stdout': 'private sentinel'},
            {'requested_at': '2026-02-30T20:02:00Z'}, {'requested_at': '2026-10-21T20:02:00+00:00'},
            {'requested_at': '2026-10-21T20:00:00Z'}, {'finished_at': '2026-10-21T20:01:00Z'},
            {'finished_at': '2026-10-21T20:02:60Z'}, {'native_exit': True}, {'native_exit': -1},
            {'native_exit': 256}, {'native_exit': 0.0}, {'native_exit': None},
        ]
        for change in changes:
            data = with_reboot()
            data['reboot'].update(change)
            with self.subTest(change=change):
                result = self.run_task(self.arguments(data))
                self.assertEqual(result.returncode, 1)
                self.assertNotIn('private sentinel', result.stdout + result.stderr)
        for key in with_reboot()['reboot']:
            data = with_reboot()
            del data['reboot'][key]
            self.assertEqual(self.run_task(self.arguments(data)).returncode, 1)
        for invalid in (None, [], False, 'private sentinel'):
            data = with_reboot()
            data['reboot'] = invalid
            self.assertEqual(self.run_task(self.arguments(data)).returncode, 1)
        self.assertEqual(list(self.supervisor.iterdir()), [])

    def test_reboot_outcome_requires_matching_receipt_and_successful_preparation(self):
        for outcome in (True, None, 0, 1, 'false'):
            data = fixture()
            data['reboot_requested'] = outcome
            self.assertEqual(self.run_task(self.arguments(data)).returncode, 1)
        for change in ('outcome', 'intent_completion', 'capacity', 'old_contract', 'bool_contract', 'state', 'phase_exit', 'command_exit'):
            data = with_reboot()
            if change == 'outcome':
                data['reboot_requested'] = False
            elif change == 'intent_completion':
                data['reboot']['state'] = 'intent'
                data['reboot_requested'] = None
            elif change == 'capacity':
                del data['capacity']
            elif change in ('old_contract', 'bool_contract'):
                data['capacity']['accounting_contract'] = 1 if change == 'old_contract' else True
            elif change == 'state':
                data.update(state='stopped', success=False)
            elif change == 'phase_exit':
                data['phases'][0]['native_exit'] = 17
            else:
                data['phases'][0]['commands'] = [{'operation': 'root', 'success': True, 'native_exit': 17}]
            with self.subTest(change=change):
                self.assertEqual(self.run_task(self.arguments(data)).returncode, 1)
        self.assertEqual(list(self.supervisor.iterdir()), [])

    def test_duplicate_fields_cannot_hide_reboot_outcome_or_secret_material(self):
        arguments = self.arguments(with_reboot())
        for field, replacement in (('"reboot_requested": true', '"reboot_requested": null, "reboot_requested": true'),
                                   ('"native_exit": 0', '"native_exit": 23, "native_exit": 0')):
            raw = arguments['report'].replace(field, replacement)
            self.assertNotEqual(raw, arguments['report'])
            self.assertEqual(self.run_task(dict(arguments, report=raw)).returncode, 1)
        self.assertEqual(list(self.supervisor.iterdir()), [])

    def test_unknown_payload_fields_cannot_leak(self):
        data = fixture()
        data["environment"] = {"SECRET": "private sentinel"}
        data["host"]["machine_id"] = "private sentinel"
        data["phases"][0]["stdout"] = "private sentinel"
        data["acceptance"] = {"raw_journal": "private sentinel"}
        result = self.run_task(self.arguments(data))
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn("private sentinel", Path(json.loads(result.stdout)["path"]).read_text())

    def test_mismatched_binding_or_schema_cannot_publish(self):
        for key, value in (("transaction", "wrong"), ("release", "sha256:" + "b" * 64), ("hostname", "wrong")):
            arguments = self.arguments()
            arguments[key] = value
            self.assertEqual(self.run_task(arguments).returncode, 1)
        data = fixture()
        data["schema"] = True
        self.assertEqual(self.run_task(self.arguments(data)).returncode, 1)
        self.assertEqual(list(self.supervisor.iterdir()), [])

    def test_incomplete_or_invalid_phase_cannot_claim_prepared(self):
        for change in ("order", "missing", "failed", "boot", "native", "success"):
            data = fixture()
            if change == "order":
                data["phases"].reverse()
            elif change == "missing":
                data["phases"].pop()
            elif change == "failed":
                data["phases"][-1]["state"] = "failed"
            elif change == "boot":
                data["phases"][0]["boot_id"] = "wrong"
            elif change == "native":
                data["phases"][0]["native_exit"] = True
            else:
                data["phases"][0]["commands"] = [{"operation": "root", "native_exit": 1, "success": False}]
            with self.subTest(change=change):
                self.assertEqual(self.run_task(self.arguments(data)).returncode, 1)

    def test_completed_phase_native_outcomes_are_operation_specific(self):
        for reboot in (False, True):
            for operation in ('mountpoint', 'root', 'source', 'modules', 'puppet', 'kexec'):
                for phase in retainer.PHASES:
                    for code in (None, 0, 1, 2, 4, 6, 17, True):
                        with self.subTest(reboot=reboot, operation=operation, phase=phase, code=code):
                            data = with_reboot() if reboot else fixture()
                            row = next(row for row in data['phases'] if row['phase'] == phase)
                            row['commands'] = [dict(operation=operation, native_exit=code, success=True)]
                            allowed = code is None or type(code) is int and (
                                code == 0 or code == 2 and operation == 'puppet' and phase == 'kernel')
                            try:
                                retained = retainer.project(json.dumps(data), 'fixture-report',
                                                            data['release'], 'fixture-host')
                            except ValueError:
                                self.assertFalse(allowed)
                            else:
                                self.assertTrue(allowed)
                                self.assertIs(next(row for row in retained['phases'] if row['phase'] == phase)
                                              ['commands'][0]['native_exit'], code)

    def test_nonzero_aggregate_phase_exit_cannot_claim_completion(self):
        for phase in retainer.PHASES:
            for code in (1, 2, 4, 6, 17):
                data = fixture()
                next(row for row in data['phases'] if row['phase'] == phase)['native_exit'] = code
                self.assertEqual(self.run_task(self.arguments(data)).returncode, 1, (phase, code))
        self.assertEqual(list(self.supervisor.iterdir()), [])

    def test_partial_stopped_and_lifecycle_are_distinct(self):
        for state, schema in (("stopped", 1), ("accepted", 2), ("finalizing", 2), ("finalized", 2)):
            data = fixture(state, schema)
            if state == "stopped":
                data["phases"] = data["phases"][:2]
                data["phases"][-1]["state"] = "failed"
                data["phases"][-1]["native_exit"] = 17
                data["success"] = False
                data["target_tree"] = None
            result = self.run_task(self.arguments(data))
            self.assertEqual(result.returncode, 0, result.stdout)
            receipt = json.loads(result.stdout)
            self.assertEqual(receipt["state"], state)
            self.assertEqual(receipt["cli_accepted"], schema == 2)
            retained = json.loads(Path(receipt["path"]).read_text())
            self.assertFalse(retained["acceptance_independently_verified"])

    def test_live_status_is_retained_without_independent_acceptance(self):
        data = fixture()
        for changed in (False, True):
            current = data['host']['target'] if changed else data['host']['current']
            boot = '22345678-1234-1234-1234-123456789abc' if changed else data['host']['boot_id']
            data['observation'] = {'boot_id': boot, 'boot_changed': changed, 'current': current,
                                   'next_boot': data['host']['target'], 'expected_target_booted': changed,
                                   'accepted': False, 'private': 'private sentinel'}
            result = self.run_task(self.arguments(data))
            self.assertEqual(result.returncode, 0, result.stdout)
            receipt = json.loads(result.stdout)
            self.assertTrue(receipt['observation_retained'])
            retained = json.loads(Path(receipt['path']).read_bytes())
            self.assertEqual(retained['observation']['boot_changed'], changed)
            self.assertEqual(retained['observation']['expected_target_booted'], changed)
            self.assertFalse(retained['acceptance_independently_verified'])
            self.assertNotIn('private sentinel', Path(receipt['path']).read_text())
        self.assertEqual(len(list(self.supervisor.glob('*.json'))), 2)

    def test_bad_live_observations_cannot_publish(self):
        baseline = {'boot_id': fixture()['host']['boot_id'], 'boot_changed': False,
                    'current': fixture()['host']['current'], 'next_boot': fixture()['host']['target'],
                    'expected_target_booted': False, 'accepted': False}
        for change in ({'boot_changed': True}, {'boot_changed': 0}, {'boot_id': 'private sentinel'},
                       {'current': 'fixture/crypt/ROOT/unknown'}, {'expected_target_booted': True},
                       {'expected_target_booted': None}, {'accepted': True}, {'accepted': 0}):
            data = fixture()
            data['observation'] = dict(baseline, **change)
            with self.subTest(change=change):
                result = self.run_task(self.arguments(data))
                self.assertEqual(result.returncode, 1)
                self.assertNotIn('private sentinel', result.stdout + result.stderr)
        self.assertEqual(list(self.supervisor.iterdir()), [])

    def test_pending_observation_without_target_is_not_a_boot_success(self):
        data = fixture()
        data.update(state='pending', success=False, target_tree=None, phases=[])
        data['observation'] = {'boot_id': data['host']['boot_id'], 'boot_changed': False,
                               'current': data['host']['current'], 'next_boot': data['host']['next_boot'],
                               'expected_target_booted': None, 'accepted': False}
        result = self.run_task(self.arguments(data))
        self.assertEqual(result.returncode, 0, result.stdout)
        receipt = json.loads(result.stdout)
        retained = json.loads(Path(receipt['path']).read_bytes())
        self.assertIsNone(retained['observation']['expected_target_booted'])
        self.assertFalse(retained['prepared'])

    def test_bad_input_error_does_not_repeat_private_payload(self):
        args = self.arguments()
        for raw in ("private sentinel", "{}", "[]", "x" * 262145):
            args["report"] = raw
            result = self.run_task(args)
            self.assertEqual(result.returncode, 1)
            self.assertNotIn("private sentinel", result.stdout + result.stderr)
            self.assertIn("_error", json.loads(result.stdout))

    def test_read_only_destination_preflight_and_unchanged_default(self):
        arguments = self.arguments()
        arguments.pop('report')
        arguments['action'] = 'check'
        result = self.run_task(arguments)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertTrue(json.loads(result.stdout)['destination_checked'])
        self.assertEqual(list(self.supervisor.iterdir()), [])
        arguments['output_dir'] += '/missing'
        self.assertEqual(self.run_task(arguments).returncode, 1)
        arguments = self.arguments()
        arguments['action'] = 'unknown'
        self.assertEqual(self.run_task(arguments).returncode, 1)

    def test_missing_or_symlink_destination_is_refused(self):
        args = self.arguments()
        args["output_dir"] = str(self.root / "missing")
        self.assertEqual(self.run_task(args).returncode, 1)
        link = self.root / "link"
        link.symlink_to(self.supervisor)
        args["output_dir"] = str(link)
        self.assertEqual(self.run_task(args).returncode, 1)
        self.assertEqual(list(self.supervisor.iterdir()), [])

    def test_identical_repeat_and_concurrent_publication_are_idempotent(self):
        args = self.arguments()
        processes = [subprocess.Popen([sys.executable, str(TASK)], stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
        receipts = []
        for process in processes:
            stdout, stderr = process.communicate(json.dumps(args))
            self.assertEqual(process.returncode, 0, stderr + stdout)
            receipts.append(json.loads(stdout))
        self.assertEqual(receipts[0], receipts[1])
        self.assertEqual(len(list(self.supervisor.glob("*.json"))), 1)
        args["report"] = json.dumps(fixture("accepted", 2))
        self.assertEqual(self.run_task(args).returncode, 0)
        self.assertEqual(len(list(self.supervisor.glob("*.json"))), 2)

    def test_publish_failure_preserves_prior_report(self):
        args = self.arguments()
        first = json.loads(self.run_task(args).stdout)
        prior = Path(first["path"]).read_bytes()
        report = retainer.project(json.dumps(fixture("accepted", 2)), args["transaction"], args["release"], args["hostname"])
        with mock.patch.object(retainer.os, "link", side_effect=OSError("injected")):
            with self.assertRaises(OSError):
                retainer.publish(report, self.supervisor)
        self.assertEqual(Path(first["path"]).read_bytes(), prior)
        self.assertEqual(len(list(self.supervisor.iterdir())), 1)

    def test_retained_corruption_is_not_overwritten(self):
        args = self.arguments()
        first = json.loads(self.run_task(args).stdout)
        path = Path(first["path"])
        path.write_text("corrupt fixture")
        self.assertEqual(self.run_task(args).returncode, 1)
        self.assertEqual(path.read_text(), "corrupt fixture")

    def test_opened_readback_rejects_symlink_hardlink_fifo_and_oversize(self):
        path = self.supervisor / 'report.json'
        other = self.worker / 'original.json'
        other.write_bytes(b'{}\n')
        for kind in ('symlink', 'hardlink', 'fifo', 'directory', 'oversize'):
            with self.subTest(kind=kind):
                if kind == 'symlink':
                    path.symlink_to(other)
                elif kind == 'hardlink':
                    os.link(other, path)
                elif kind == 'fifo':
                    os.mkfifo(path)
                elif kind == 'directory':
                    path.mkdir()
                else:
                    path.write_bytes(b'x' * 5)
                try:
                    with self.assertRaises((ValueError, OSError)):
                        retainer.read_report(path, 4)
                finally:
                    path.rmdir() if path.is_dir() else path.unlink()

    def test_opened_report_cannot_be_replaced_with_identical_bytes(self):
        path = self.supervisor / 'report.json'
        path.write_bytes(b'{}\n')
        original = retainer.os.read
        replaced = False

        def replace_during_read(descriptor, count):
            nonlocal replaced
            raw = original(descriptor, count)
            if not replaced:
                replaced = True
                path.rename(self.supervisor / 'old.json')
                path.write_bytes(b'{}\n')
            return raw

        with mock.patch.object(retainer.os, 'read', replace_during_read):
            with self.assertRaises(ValueError):
                retainer.read_report(path, 4)
        self.assertTrue(replaced)

    def test_same_inode_in_place_change_during_read_refuses(self):
        path = self.supervisor / 'report.json'
        path.write_bytes(b'{}\n')
        original = retainer.os.read
        replaced = False

        def mutate_during_read(descriptor, count):
            nonlocal replaced
            raw = original(descriptor, count)
            if not replaced:
                replaced = True
                path.write_bytes(b'[]\n')
            return raw

        with mock.patch.object(retainer.os, 'read', mutate_during_read):
            with self.assertRaises(ValueError):
                retainer.read_report(path, 4)

    def test_directory_replacement_during_publication_cannot_claim_readback(self):
        original = retainer.os.link
        moved = self.root / 'moved-supervisor'

        def replace_directory(*args, **kwargs):
            self.supervisor.rename(moved)
            self.supervisor.mkdir()
            return original(*args, **kwargs)

        with mock.patch.object(retainer.os, 'link', replace_directory):
            with self.assertRaises(ValueError):
                retainer.publish_document({'kind': 'fixture'}, self.supervisor, 'fixture')
        self.assertEqual(list(self.supervisor.iterdir()), [])
        self.assertEqual(len(list(moved.glob('*.json'))), 1)
        self.assertEqual(list(moved.glob('.nest-update-report-*')), [])

    def test_swapped_ancestor_symlink_refuses_before_report_open(self):
        path = self.supervisor / 'report.json'
        path.write_bytes(b'{}\n')
        original = retainer.os.open
        moved = self.root / 'moved-supervisor'

        def swap_before_traversal(name, *args, **kwargs):
            if name == self.supervisor.name and not self.supervisor.is_symlink():
                self.supervisor.rename(moved)
                self.supervisor.symlink_to(moved)
            return original(name, *args, **kwargs)

        with mock.patch.object(retainer.os, 'open', swap_before_traversal):
            with self.assertRaises(OSError):
                retainer.read_report(path, 4)

    def test_existing_target_symlink_is_not_followed_or_overwritten(self):
        receipt = retainer.publish_document({'kind': 'fixture'}, self.supervisor, 'fixture')
        path = Path(receipt['path'])
        other = self.worker / 'original.json'
        path.rename(other)
        path.symlink_to(other)
        with self.assertRaises(ValueError):
            retainer.publish_document({'kind': 'fixture'}, self.supervisor, 'fixture')
        self.assertTrue(path.is_symlink())
        self.assertEqual(hashlib.sha256(other.read_bytes()).hexdigest(), receipt['sha256'])
        self.assertEqual(list(self.supervisor.glob('.nest-update-report-*')), [])

    def test_file_and_directory_fsync_failure_cannot_return_receipt(self):
        for failure in (1, 2):
            with self.subTest(failure=failure):
                original = retainer.os.fsync
                calls = 0

                def failed_fsync(descriptor):
                    nonlocal calls
                    calls += 1
                    if calls == failure:
                        raise OSError('injected')
                    return original(descriptor)

                with mock.patch.object(retainer.os, 'fsync', failed_fsync):
                    with self.assertRaises(OSError):
                        retainer.publish_document({'kind': 'fixture'}, self.supervisor, 'fsync-' + str(failure))
                self.assertEqual(list(self.supervisor.glob('.nest-update-report-*')), [])


if __name__ == "__main__":
    unittest.main()
