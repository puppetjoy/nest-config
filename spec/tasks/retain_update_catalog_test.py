"""Exercise real supervisor task publication; no native agent, host or ZFS effects."""


import hashlib
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True
TASKS = Path(__file__).resolve().parents[2] / "tasks"
sys.path.insert(0, str(TASKS))
spec = importlib.util.spec_from_file_location("retain_catalog", TASKS / "retain_update_catalog.py")
assert spec is not None and spec.loader is not None
retainer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retainer)

EXPECTED = {"hostname": "fixture", "certname": "fixture.nest", "boot_id": "11111111-1111-4111-8111-111111111111",
            "configuration_version": "a" * 40}
TRANSACTION = "fixture-cycle"
RELEASE = "sha256:" + "b" * 64


def fixture(first: int | None = 2, second: int | None = 0):
    def invocation(code, uuid):
        result = {"native_exit": code, "report_bound": code in (0, 2)}
        if result["report_bound"]:
            result["report"] = {"host": "fixture.nest", "environment": "main", "configuration_version": "a" * 40,
                                "transaction_uuid": uuid, "catalog_uuid": uuid, "time": "2026-10-24T03:00:00Z",
                                "status": "unchanged" if code == 0 else "changed", "noop": False,
                                "cached_catalog_status": "not_used", "transaction_completed": True, "report_sha256": "c" * 64}
        return result
    repeated = first in (0, 2)
    converged = repeated and second == 0
    value = {"schema": 1, "kind": "nest_update_catalog_bound", "result": "pass" if converged else "fail",
             "hostname": EXPECTED["hostname"], "boot_id": EXPECTED["boot_id"], "configuration_version": "a" * 40,
             "repeat_attempted": repeated, "converged": converged, "served_source_verified": False,
             "acceptance_recorded": False, "main": invocation(first, "22222222-2222-4222-8222-222222222222")}
    if repeated:
        value["repeat"] = invocation(second, "33333333-3333-4333-8333-333333333333")
    return value


class RetainCatalogTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.worker = self.root / "worker"
        self.supervisor = self.root / "supervisor"
        self.worker.mkdir()
        self.supervisor.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def arguments(self, value=None):
        return {"action": "retain", "expectations": EXPECTED, "transaction": TRANSACTION, "release": RELEASE,
                "output_dir": str(self.supervisor), "report": json.dumps(fixture() if value is None else value)}

    def run_task(self, arguments):
        return subprocess.run([sys.executable, str(TASKS / "retain_update_catalog.py")], input=json.dumps(arguments),
                              text=True, capture_output=True, cwd=self.worker, check=False)

    def project(self, value):
        return retainer.project(json.dumps(value), EXPECTED, TRANSACTION, RELEASE)

    def test_real_stdin_cross_filesystem_transport_and_readback_survive_worker_removal(self):
        arguments = self.arguments()
        source = self.worker / "transport.json"
        source.write_text(arguments["report"])
        arguments["report"] = source.read_text()
        result = self.run_task(arguments)
        self.assertEqual(result.returncode, 0, result.stdout)
        receipt = json.loads(result.stdout)
        path = Path(receipt["path"])
        payload = path.read_bytes()
        self.assertTrue(receipt["readback_verified"])
        self.assertEqual(receipt["sha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(receipt["bytes"], len(payload))
        self.assertEqual(path.stat().st_mode & 0o777, 0o644)
        self.assertEqual(path.parent, self.supervisor)
        shutil.rmtree(self.worker)
        value = json.loads(path.read_bytes())
        self.assertEqual(value["catalog"], fixture())
        self.assertEqual(value["expectations"], EXPECTED)
        for field in ("acceptance_recorded", "served_source_verified", "release_binding_verified"):
            self.assertIs(value[field], False)

    def test_preflight_is_read_only_and_refuses_missing_or_symlink_destination(self):
        arguments = self.arguments()
        arguments.pop("report")
        arguments["action"] = "check"
        self.assertEqual(self.run_task(arguments).returncode, 0)
        self.assertEqual(list(self.supervisor.iterdir()), [])
        for path in (self.root / "missing", self.root / "alias"):
            if path.name == "alias":
                path.symlink_to(self.supervisor, target_is_directory=True)
            arguments["output_dir"] = str(path)
            self.assertEqual(self.run_task(arguments).returncode, 1)
        self.assertFalse((self.root / "missing").exists())

    def test_failed_or_unknown_native_exits_are_retained_not_promoted(self):
        for first, second in ((1, 0), (None, 0), (2, 2), (2, 4), (0, None)):
            with self.subTest(first=first, second=second):
                value = self.project(fixture(first, second))
                self.assertEqual(value["catalog"]["result"], "fail")
                self.assertIs(value["acceptance_recorded"], False)
                receipt = retainer.publish_document(value, self.supervisor, "catalog-" + TRANSACTION)
                self.assertEqual(json.loads(Path(receipt["path"]).read_bytes()), value)
        self.assertEqual(len(list(self.supervisor.iterdir())), 5)

    def test_expected_native_code_id_survives_real_task_publication_and_readback(self):
        arguments = self.arguments()
        arguments["expectations"] = dict(EXPECTED, code_id="sha256:" + "d" * 64)
        value = fixture()
        for phase in ("main", "repeat"):
            value[phase]["report"]["code_id"] = arguments["expectations"]["code_id"]
        arguments["report"] = json.dumps(value)
        result = self.run_task(arguments)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        receipt = json.loads(result.stdout)
        raw = Path(receipt["path"]).read_bytes()
        self.assertEqual(receipt["sha256"], hashlib.sha256(raw).hexdigest())
        retained = json.loads(raw)
        self.assertEqual(retained["expectations"], arguments["expectations"])
        self.assertEqual(retained["catalog"], value)
        self.assertFalse(retained["served_source_verified"])

    def test_code_id_missing_changed_unsolicited_or_invalid_refuses_without_publication(self):
        code_id = "sha256:" + "d" * 64
        for phase in ("main", "repeat"):
            for replacement in (None, False, "sha256:" + "e" * 64):
                arguments = self.arguments()
                arguments["expectations"] = dict(EXPECTED, code_id=code_id)
                value = fixture()
                for name in ("main", "repeat"):
                    value[name]["report"]["code_id"] = code_id
                if replacement is None:
                    del value[phase]["report"]["code_id"]
                else:
                    value[phase]["report"]["code_id"] = replacement
                arguments["report"] = json.dumps(value)
                self.assertEqual(self.run_task(arguments).returncode, 1)
        for invalid in (None, False, 7, "main", "d" * 64, "sha256:" + "D" * 64):
            arguments = self.arguments()
            arguments["expectations"] = dict(EXPECTED, code_id=invalid)
            self.assertEqual(self.run_task(arguments).returncode, 1)
            arguments.pop("report")
            arguments["action"] = "check"
            self.assertEqual(self.run_task(arguments).returncode, 1)
        value = fixture()
        value["main"]["report"]["code_id"] = code_id
        self.assertEqual(self.run_task(self.arguments(value)).returncode, 1)
        self.assertEqual(list(self.supervisor.iterdir()), [])

    def test_idempotent_concurrent_publication_and_conflicting_target_refusal(self):
        arguments = self.arguments()
        children = [subprocess.Popen([sys.executable, str(TASKS / "retain_update_catalog.py")], stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
        receipts = []
        for child in children:
            out, err = child.communicate(json.dumps(arguments), timeout=30)
            self.assertEqual(child.returncode, 0, err + out)
            receipts.append(json.loads(out))
        self.assertEqual(receipts[0], receipts[1])
        path = Path(receipts[0]["path"])
        path.write_text("conflict")
        self.assertEqual(self.run_task(arguments).returncode, 1)
        self.assertEqual(path.read_text(), "conflict")

    def test_complete_unknown_fields_and_private_payload_refuse_without_publication(self):
        for location in ("top", "invocation", "report"):
            value = fixture()
            target = value if location == "top" else value["main"] if location == "invocation" else value["main"]["report"]
            target["logs"] = "private sentinel"
            result = self.run_task(self.arguments(value))
            self.assertEqual(result.returncode, 1)
            self.assertNotIn("private sentinel", result.stdout + result.stderr)
        self.assertEqual(list(self.supervisor.iterdir()), [])

    def test_identity_outcome_and_native_report_corruption_refuse(self):
        mutations = [(("schema",), True), (("kind",), "nest_update_catalog"), (("hostname",), "other"),
                     (("boot_id",), "22222222-2222-4222-8222-222222222222"), (("configuration_version",), "b" * 40),
                     (("acceptance_recorded",), True), (("served_source_verified",), True), (("result",), "fail"),
                     (("converged",), False), (("repeat_attempted",), False), (("identity_binding_failed",), False),
                     (("main", "native_exit"), True), (("main", "report", "host"), "other"),
                     (("main", "report", "environment"), "test"), (("main", "report", "configuration_version"), "b" * 40),
                     (("main", "report", "noop"), True), (("main", "report", "transaction_completed"), False),
                     (("main", "report", "status"), "unchanged"), (("main", "report", "cached_catalog_status"), "used"),
                     (("main", "report", "report_sha256"), "bad"), (("main", "report", "time"), "2026-99-99T03:00:00Z"),
                     (("main", "report", "transaction_uuid"), "invented"), (("main", "report", "catalog_uuid"), "invented"),
                     (("repeat", "report", "transaction_uuid"), fixture()["main"]["report"]["transaction_uuid"])]
        for path, replacement in mutations:
            with self.subTest(path=path):
                value = fixture()
                target = value
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = replacement
                with self.assertRaises((ValueError, TypeError)):
                    self.project(value)

    def test_identity_failure_retains_known_exits_and_cannot_pass(self):
        for value in (fixture(), fixture(0, 0)):
            value.update(identity_binding_failed=True, result="fail", converged=False)
            result = self.project(value)
            self.assertEqual(result["catalog"]["main"]["native_exit"], value["main"]["native_exit"])
            self.assertEqual(result["catalog"]["result"], "fail")
        value = fixture()
        value["repeat"]["report"]["transaction_uuid"] = value["main"]["report"]["transaction_uuid"]
        value.update(identity_binding_failed=True, result="fail", converged=False)
        self.assertEqual(self.project(value)["catalog"]["result"], "fail")

    def test_missing_report_repeat_or_false_type_and_unbound_repeat_refuse(self):
        for mutation in ("missing_main", "missing_repeat", "missing_bound", "repeat_after_failed", "missing_exit"):
            value = fixture()
            if mutation == "missing_main":
                del value["main"]
            elif mutation == "missing_repeat":
                del value["repeat"]
            elif mutation == "missing_bound":
                del value["main"]["report_bound"]
            elif mutation == "repeat_after_failed":
                value["main"] = {"native_exit": 4, "report_bound": False}
            else:
                del value["main"]["native_exit"]
            with self.subTest(mutation=mutation), self.assertRaises((ValueError, TypeError)):
                self.project(value)

    def test_duplicate_keys_oversize_parameters_and_noop_do_not_publish(self):
        arguments = self.arguments()
        arguments["report"] = arguments["report"][:-1] + ',"schema":1}'
        self.assertEqual(self.run_task(arguments).returncode, 1)
        arguments = self.arguments()
        arguments["report"] += " " * 65536
        self.assertEqual(self.run_task(arguments).returncode, 1)
        arguments = self.arguments()
        arguments["_noop"] = True
        self.assertEqual(self.run_task(arguments).returncode, 1)
        arguments = self.arguments()
        arguments["_extra"] = "x" * 131072
        self.assertEqual(self.run_task(arguments).returncode, 1)
        self.assertEqual(list(self.supervisor.iterdir()), [])

    def test_failed_flush_has_no_success_and_does_not_erase_published_evidence(self):
        document = self.project(fixture())
        with mock.patch.object(retainer.publish_document.__globals__["os"], "fsync", side_effect=OSError("private sentinel")):
            with self.assertRaises(OSError):
                retainer.publish_document(document, self.supervisor, "catalog-" + TRANSACTION)
        self.assertEqual(list(self.supervisor.iterdir()), [])
        native_fsync = retainer.publish_document.__globals__["os"].fsync
        calls = []

        def fail_directory_flush(fd):
            calls.append(fd)
            if len(calls) == 2:
                raise OSError("private sentinel")
            native_fsync(fd)

        with mock.patch.object(retainer.publish_document.__globals__["os"], "fsync", side_effect=fail_directory_flush):
            with self.assertRaises(OSError):
                retainer.publish_document(document, self.supervisor, "catalog-" + TRANSACTION)
        paths = list(self.supervisor.iterdir())
        self.assertEqual(len(paths), 1)
        self.assertEqual(json.loads(paths[0].read_bytes()), document)
        receipt = retainer.publish_document(document, self.supervisor, "catalog-" + TRANSACTION)
        self.assertTrue(receipt["readback_verified"])

    def manifest_arguments(self):
        sys.path.insert(0, str(TASKS.parent / "spec/files"))
        from nest_release_manifest_test import fixture as release_fixture, release as validator
        expected, candidate = release_fixture()
        manifest = validator.validate(expected, candidate)
        arguments = self.arguments()
        arguments["manifest"] = manifest
        arguments["release"] = validator.digest(manifest)
        arguments["expectations"] = dict(EXPECTED, hostname="fixture-host",
                                        configuration_version=expected["sources"]["nest/config"])
        data = fixture()
        data.update(hostname="fixture-host", configuration_version=arguments["expectations"]["configuration_version"])
        for key in ("main", "repeat"):
            data[key]["report"]["configuration_version"] = arguments["expectations"]["configuration_version"]
        arguments["report"] = json.dumps(data)
        return arguments

    def test_release_manifest_preflight_creates_nothing_and_retains_bound_metadata(self):
        arguments = self.manifest_arguments()
        preflight = dict(arguments, action="check")
        del preflight["report"]
        result = self.run_task(preflight)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)["release_metadata_bound"])
        self.assertEqual(list(self.supervisor.iterdir()), [])
        result = self.run_task(arguments)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        receipt = json.loads(result.stdout)
        document = json.loads(Path(receipt["path"]).read_bytes())
        binding = document["release_metadata"]
        self.assertEqual(binding["manifest_digest"], arguments["release"])
        self.assertEqual(binding["configuration_version"], arguments["expectations"]["configuration_version"])
        self.assertEqual(binding["root"], arguments["manifest"]["candidate"]["outputs"][3]["artifacts"]["root"])
        self.assertEqual(binding["resource_verification"], "not_performed")
        for field in ("release_binding_verified", "served_source_verified", "acceptance_recorded"):
            self.assertIs(document[field], False)

    def test_release_metadata_does_not_turn_failed_catalog_into_acceptance(self):
        arguments = self.manifest_arguments()
        data = json.loads(arguments["report"])
        data.update(result="fail", converged=False)
        data["repeat"]["native_exit"] = 2
        data["repeat"]["report"]["status"] = "changed"
        arguments["report"] = json.dumps(data)
        result = self.run_task(arguments)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["result"], "fail")
        self.assertTrue(receipt["release_metadata_bound"])
        self.assertFalse(receipt["acceptance_recorded"])

    def test_wrong_release_source_host_and_incomplete_matrix_refuse_before_publication(self):
        original = self.manifest_arguments()
        mutations = [(("release",), "sha256:" + "0" * 64),
                     (("expectations", "configuration_version"), "f" * 40),
                     (("expectations", "hostname"), "other-host"),
                     (("manifest", "schema"), True), (("manifest", "kind"), "nest_release_manifest_validation"),
                     (("manifest", "candidate", "outputs"), original["manifest"]["candidate"]["outputs"][1:]),
                     (("manifest", "expectations", "sources", "nest/config"), "f" * 40),
                     (("manifest", "private"), "private sentinel"), (("manifest",), None)]
        for path, value in mutations:
            arguments = copy.deepcopy(original)
            target = arguments
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            for action in ("check", "retain"):
                params = dict(arguments, action=action)
                if action == "check":
                    del params["report"]
                with self.subTest(path=path, action=action):
                    result = self.run_task(params)
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertNotIn("private sentinel", result.stdout + result.stderr)
                    self.assertNotIn("Traceback", result.stdout + result.stderr)
        self.assertEqual(list(self.supervisor.iterdir()), [])

    def test_changed_unrelated_output_invalidates_runtime_release(self):
        arguments = self.manifest_arguments()
        arguments["manifest"]["candidate"]["outputs"][0]["artifacts"]["normal"] = "registry.example/nest/image@sha256:" + "f" * 64
        self.assertEqual(self.run_task(arguments).returncode, 1)
        self.assertEqual(list(self.supervisor.iterdir()), [])

    def test_duplicate_manifest_keys_nonfinite_and_oversized_input_refuse(self):
        arguments = self.manifest_arguments()
        raw = json.dumps(arguments)
        for payload in (raw[:-1] + ',"manifest":{}}', raw.replace('"schema": 1', '"schema": NaN', 1), " " * 2097153):
            result = subprocess.run([sys.executable, str(TASKS / "retain_update_catalog.py")], input=payload,
                                    text=True, capture_output=True, cwd=self.worker, check=False)
            self.assertEqual(result.returncode, 1)
            self.assertNotIn("Traceback", result.stdout + result.stderr)
        self.assertEqual(list(self.supervisor.iterdir()), [])

    def test_symlink_target_refuses_without_changing_its_referent(self):
        document = self.project(fixture())
        receipt = retainer.publish_document(document, self.supervisor, "catalog-" + TRANSACTION)
        path = Path(receipt["path"])
        referent = self.root / "private"
        referent.write_text("unchanged")
        path.unlink()
        path.symlink_to(referent)
        with self.assertRaises(ValueError):
            retainer.publish_document(document, self.supervisor, "catalog-" + TRANSACTION)
        self.assertEqual(referent.read_text(), "unchanged")


if __name__ == "__main__":
    unittest.main()
