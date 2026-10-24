"""Contract and interruption fixtures for the trusted TEST delivery adapter."""

import copy
import importlib.util
import io
import json
from email.message import Message
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("controller", ROOT / "files/app/joyride/test_delivery_controller.py")
assert spec is not None and spec.loader is not None
controller = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controller)
OLD = controller.REPOSITORY + "@sha256:" + "a" * 64
NEW = controller.REPOSITORY + "@sha256:" + "b" * 64
ID = "12345678-1234-4234-8234-123456789abc"


def deployment():
    return {
        "metadata": {"uid": "fixture-uid", "resourceVersion": "1", "generation": 1},
        "spec": {
            "replicas": 1, "minReadySeconds": 10,
            "strategy": {"type": "RollingUpdate", "rollingUpdate": {"maxUnavailable": 0, "maxSurge": 1}},
            "template": {
                "metadata": {"labels": {"app": "joyride-test"}},
                "spec": {
                    "containers": [{"name": name, "image": OLD} for name in sorted(controller.CONTAINERS)],
                    "initContainers": [{"name": name, "image": OLD} for name in sorted(controller.INITIALIZERS)],
                },
            },
        },
        "status": {"observedGeneration": 1, "replicas": 1, "updatedReplicas": 1, "readyReplicas": 1, "availableReplicas": 1},
    }


class FixtureClient:
    def __init__(self):
        self.deployment = deployment()
        self.queue = [{"id": ID, "image": NEW, "environment": "test", "action": "promote"}]
        self.journal = None
        self.state = "queued"
        self.patches = 0
        self.available = True
        self.crash_after_patch = False
        self.crash_after_result = False
        self.readiness = True

    def request(self, path):
        assert path == "/delivery/queue"
        return {"deployments": copy.deepcopy(self.queue)}

    def read_journal(self):
        return {"metadata": {"resourceVersion": "1"}}, copy.deepcopy(self.journal)

    def save_journal(self, row, active):
        if active is None and self.crash_after_result:
            self.crash_after_result = False
            raise RuntimeError("fixture crash after terminal callback")
        self.journal = copy.deepcopy(active)
        return row

    def get_deployment(self):
        if not self.available:
            raise controller.DeliveryError("request_failed")
        return copy.deepcopy(self.deployment)

    def patch_deployment(self, deployment, operation):
        self.patches += 1
        for group in ("containers", "initContainers"):
            for row in self.deployment["spec"]["template"]["spec"][group]:
                row["image"] = operation["image"]
        self.deployment["spec"]["template"]["metadata"].setdefault("annotations", {})[controller.ANNOTATION] = operation["id"]
        self.deployment["metadata"]["generation"] = 2
        self.deployment["status"]["observedGeneration"] = 2
        if self.crash_after_patch:
            self.crash_after_patch = False
            raise RuntimeError("fixture crash after committed patch")
        return copy.deepcopy(self.deployment)

    def result(self, operation, state):
        if self.state not in ("succeeded", "failed"):
            self.state = state
        return {"id": ID, "state": self.state}

    def ready(self):
        return self.readiness


class ControllerTests(unittest.TestCase):
    def test_unsafe_rollout_strategy_refused_before_claim(self):
        for strategy in (
            {"type": "Recreate"},
            {"type": "RollingUpdate", "rollingUpdate": {"maxUnavailable": 1, "maxSurge": 1}},
            {"type": "RollingUpdate", "rollingUpdate": {"maxUnavailable": "0%", "maxSurge": "100%"}},
            {"type": "RollingUpdate", "rollingUpdate": {"maxUnavailable": 0, "maxSurge": 2}},
        ):
            with self.subTest(strategy=strategy):
                client = FixtureClient()
                client.deployment["spec"]["strategy"] = strategy
                with self.assertRaisesRegex(controller.DeliveryError, "unexpected_workload_strategy"):
                    controller.run(client)
                self.assertEqual(client.state, "queued")
                self.assertEqual(client.patches, 0)
                self.assertIsNone(client.journal)

    def test_old_ready_replica_cannot_mask_unready_surge(self):
        client = FixtureClient()
        client.crash_after_patch = True
        with self.assertRaises(RuntimeError):
            controller.run(client, clock=lambda: 0)
        client.deployment["status"].update(replicas=2, unavailableReplicas=1)
        self.assertFalse(controller.complete(client.deployment, client.journal))
        times = iter([10, 10, 1801])
        with self.assertRaisesRegex(controller.DeliveryError, "rollout_deadline"):
            controller.run(client, clock=lambda: next(times), pause=lambda _: None)
        self.assertEqual(client.state, "failed")
        self.assertEqual(client.patches, 1)
        self.assertEqual(client.deployment["status"]["availableReplicas"], 1)

    def test_full_claim_patch_observe_probe_callback(self):
        client = FixtureClient()
        self.assertEqual(controller.run(client, clock=lambda: 0), "succeeded")
        self.assertEqual(client.patches, 1)
        self.assertEqual(client.state, "succeeded")
        self.assertIsNone(client.journal)
        self.assertEqual(set(controller.images(client.deployment).values()), {NEW})

    def test_current_curated_workload_updates_all_application_initializers(self):
        client = FixtureClient()
        # Independent workload shape: deriving this from INITIALIZERS hid the
        # regression when managed private intake added its two init containers.
        names = ("migrate", "provision-owner", "basemap", "curated-fetch", "curated-import")
        containers = ("web", "internal-web", "ops", "trusted-test", "worker")
        client.deployment["spec"]["template"]["spec"]["containers"] = [
            {"name": name, "image": OLD} for name in containers
        ]
        client.deployment["spec"]["template"]["spec"]["initContainers"] = [
            {"name": name, "image": OLD} for name in names
        ]
        self.assertEqual(controller.run(client, clock=lambda: 0), "succeeded")
        actual = client.deployment["spec"]["template"]["spec"]["initContainers"]
        self.assertEqual({row["name"]: row["image"] for row in actual}, dict.fromkeys(names, NEW))
        self.assertEqual(client.state, "succeeded")

    def test_unknown_or_duplicate_initializer_refused_before_claim(self):
        for name in ("unmanaged-init", "curated-import"):
            with self.subTest(name=name):
                client = FixtureClient()
                client.deployment["spec"]["template"]["spec"]["initContainers"].append(
                    {"name": name, "image": OLD}
                )
                with self.assertRaisesRegex(controller.DeliveryError, "unexpected_workload_shape"):
                    controller.run(client)
                self.assertEqual(client.state, "queued")
                self.assertEqual(client.patches, 0)
                self.assertIsNone(client.journal)

    def test_idle_and_production_are_never_claimed(self):
        client = FixtureClient()
        client.queue[0]["environment"] = "production"
        self.assertEqual(controller.run(client), "idle")
        self.assertEqual(client.state, "queued")
        self.assertEqual(client.patches, 0)

    def test_reject_arbitrary_repository_tag_and_action(self):
        for key, value in (("image", "example.invalid/evil@sha256:" + "a" * 64), ("image", controller.REPOSITORY + ":latest"), ("action", "shell")):
            with self.subTest(key=key, value=value):
                client = FixtureClient()
                client.queue[0][key] = value
                with self.assertRaises(controller.DeliveryError):
                    controller.run(client)
                self.assertEqual(client.state, "queued")
                self.assertIsNone(client.journal)

    def test_unknown_or_duplicate_container_refused(self):
        for change in ("extra", "duplicate"):
            client = FixtureClient()
            rows = client.deployment["spec"]["template"]["spec"]["containers"]
            rows.append({"name": "extra" if change == "extra" else "web", "image": OLD})
            with self.assertRaises(controller.DeliveryError):
                controller.run(client)
            self.assertEqual(client.patches, 0)

    def test_crash_after_patch_resumes_without_second_patch(self):
        client = FixtureClient()
        client.crash_after_patch = True
        with self.assertRaises(RuntimeError):
            controller.run(client, clock=lambda: 0)
        self.assertEqual(client.state, "running")
        self.assertEqual(controller.run(client, clock=lambda: 10), "succeeded")
        self.assertEqual(client.patches, 1)

    def test_crash_after_terminal_callback_preserves_outcome(self):
        client = FixtureClient()
        client.crash_after_result = True
        with self.assertRaises(RuntimeError):
            controller.run(client, clock=lambda: 0)
        self.assertEqual(client.state, "succeeded")
        self.assertEqual(controller.run(client, clock=lambda: 10), "recovered_succeeded")
        self.assertIsNone(client.journal)
        self.assertEqual(client.patches, 1)

    def test_platform_template_change_refused_on_resume(self):
        client = FixtureClient()
        client.crash_after_patch = True
        with self.assertRaises(RuntimeError):
            controller.run(client, clock=lambda: 0)
        client.deployment["spec"]["template"]["spec"]["containers"][0]["env"] = [{"name": "MAIL_ENABLED", "value": "1"}]
        with self.assertRaisesRegex(controller.DeliveryError, "concurrent_workload_change"):
            controller.run(client, clock=lambda: 10)
        self.assertEqual(client.state, "failed")
        self.assertEqual(client.patches, 1)

    def test_replaced_workload_refused(self):
        client = FixtureClient()
        client.crash_after_patch = True
        with self.assertRaises(RuntimeError):
            controller.run(client, clock=lambda: 0)
        client.deployment["metadata"]["uid"] = "replacement"
        with self.assertRaisesRegex(controller.DeliveryError, "workload_replaced"):
            controller.run(client, clock=lambda: 10)
        self.assertEqual(client.state, "failed")

    def test_transient_failure_preserves_running_journal(self):
        client = FixtureClient()
        client.crash_after_patch = True
        with self.assertRaises(RuntimeError):
            controller.run(client, clock=lambda: 0)
        client.available = False
        with self.assertRaises(controller.DeliveryError):
            controller.run(client, clock=lambda: 10)
        self.assertEqual(client.state, "running")
        self.assertIsNotNone(client.journal)
        client.available = True
        self.assertEqual(controller.run(client, clock=lambda: 20), "succeeded")

    def test_deadline_fails_without_automatic_rollback(self):
        client = FixtureClient()
        client.crash_after_patch = True
        with self.assertRaises(RuntimeError):
            controller.run(client, clock=lambda: 0)
        with self.assertRaisesRegex(controller.DeliveryError, "rollout_deadline"):
            controller.run(client, clock=lambda: 1801)
        self.assertEqual(client.state, "failed")
        self.assertEqual(set(controller.images(client.deployment).values()), {NEW})

    def test_full_admission_can_finish_after_ten_minutes_with_original_deadline(self):
        client = FixtureClient()
        client.crash_after_patch = True
        with self.assertRaises(RuntimeError):
            controller.run(client, clock=lambda: 0)
        assert client.journal is not None
        self.assertEqual(client.journal["deadline"], 1800)
        self.assertEqual(controller.run(client, clock=lambda: 700), "succeeded")
        self.assertEqual(client.patches, 1)

    def test_resuming_does_not_extend_original_deadline(self):
        client = FixtureClient()
        client.crash_after_patch = True
        with self.assertRaises(RuntimeError):
            controller.run(client, clock=lambda: 0)
        # An already journaled operation retains its exact deadline.
        assert client.journal is not None
        client.journal["deadline"] = 600
        with self.assertRaisesRegex(controller.DeliveryError, "rollout_deadline"):
            controller.run(client, clock=lambda: 601)
        self.assertEqual(client.state, "failed")
        self.assertEqual(client.patches, 1)

    def test_readiness_is_not_controller_success(self):
        client = FixtureClient()
        client.readiness = False
        times = iter([0, 0, 0, 1801])
        with self.assertRaisesRegex(controller.DeliveryError, "rollout_deadline"):
            controller.run(client, clock=lambda: next(times), pause=lambda _: None)
        self.assertEqual(client.state, "failed")

    def test_old_observed_generation_never_completes(self):
        client = FixtureClient()
        client.crash_after_patch = True
        with self.assertRaises(RuntimeError):
            controller.run(client, clock=lambda: 0)
        client.deployment["status"]["observedGeneration"] = 1
        self.assertFalse(controller.complete(client.deployment, client.journal))

    def test_json_patch_is_cas_and_only_images_and_delivery_annotation(self):
        client = controller.Client.__new__(controller.Client)
        client.kube_token = "fixture-not-a-secret"
        client.kube_context = None
        client.base = "/apis/apps/v1/namespaces/test/deployments/joyride-test"
        row = deployment()
        operation = {"id": ID, "uid": "fixture-uid", "image": NEW}
        response = io.BytesIO(b"{}")
        with patch.object(controller, "open_request", return_value=response) as opened:
            client.patch_deployment(row, operation)
        request = opened.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(payload[:2], [
            {"op": "test", "path": "/metadata/uid", "value": "fixture-uid"},
            {"op": "test", "path": "/metadata/resourceVersion", "value": "1"},
        ])
        for item in payload[2:-1]:
            self.assertEqual(item["op"], "replace")
            self.assertTrue(item["path"].endswith("/image"))
            self.assertEqual(item["value"], NEW)
        self.assertEqual(len(payload), 3 + len(controller.CONTAINERS) + len(controller.INITIALIZERS))
        self.assertEqual(payload[-1]["value"], {controller.ANNOTATION: ID})

    def test_terminal_conflict_reads_only_exact_result_shape(self):
        client = controller.Client.__new__(controller.Client)
        client.delivery_token = "fixture-not-a-secret"
        for value, accepted in (({"id": ID, "state": "succeeded"}, True), ({"error": "digest_mismatch"}, False)):
            error = HTTPError("http://fixture", 409, "conflict", Message(), io.BytesIO(json.dumps(value).encode()))
            with patch.object(controller, "open_request", side_effect=error):
                if accepted:
                    self.assertEqual(client.result({"id": ID, "image": NEW}, "running"), value)
                else:
                    with self.assertRaises(controller.DeliveryError):
                        client.result({"id": ID, "image": NEW}, "running")

    def test_redirect_never_forwards_credentials(self):
        with self.assertRaisesRegex(controller.DeliveryError, "redirect_denied"):
            controller.NoRedirect().redirect_request(None, None, 302, "found", {}, "https://example.invalid")

    def test_database_readiness_alone_is_not_application_acceptance(self):
        client = controller.Client.__new__(controller.Client)
        good = [{"status": "ready"}, {"csrf_token": "c" * 64}, {"sha256": "a" * 64, "url": "/maps/fixture.pmtiles"}, b"<!doctype html><html></html>"]
        with patch.object(client, "request", side_effect=good):
            self.assertTrue(client.ready())
        for index, value in ((1, {}), (2, {"error": "basemap_not_installed"}), (3, b"not an HTML release")):
            values = copy.deepcopy(good)
            values[index] = value
            with patch.object(client, "request", side_effect=values):
                self.assertFalse(client.ready())


if __name__ == "__main__":
    unittest.main()