"""Bounded TEST-only delivery adapter, owned by Nest rather than app artifacts.

One CronJob (Forbid) owns the journal. Only the exact Deployment and journal
ConfigMap are writable. No DB, registry API, member data or production access.
The journal is written before claiming; interruptions resume the same operation.
"""

import copy
import hashlib
import json
import os
import re
import ssl
import sys
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

REPOSITORY = "registry.gitlab.joyfullee.me/joy/joyride/app"
IMAGE = re.compile(re.escape(REPOSITORY) + r"@sha256:[0-9a-f]{64}\Z")
CONTAINERS = {"web", "internal-web", "ops", "worker", "trusted-test"}
INITIALIZERS = {"migrate", "provision-owner", "basemap", "curated-fetch", "curated-import", "routing-graph"}
ANNOTATION = "joyride.nest/delivery-id"


class DeliveryError(Exception):
    """Safe local failure; never include an HTTP response or secret in logs."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise DeliveryError("redirect_denied")


def open_request(request, context=None):
    return build_opener(NoRedirect(), HTTPSHandler(context=context)).open(request, timeout=15)


class Client:
    def __init__(self):
        self.namespace = "test"
        self.name = "joyride-test"
        self.base = "/apis/apps/v1/namespaces/test/deployments/joyride-test"
        self.journal = "/api/v1/namespaces/test/configmaps/joyride-test-delivery-journal"
        directory = "/var/run/secrets/kubernetes.io/serviceaccount"
        with open(directory + "/token", encoding="utf-8") as stream:
            self.kube_token = stream.read().strip()
        self.kube_context = ssl.create_default_context(cafile=directory + "/ca.crt")
        with open("/delivery-secret/DELIVERY_TOKEN", encoding="utf-8") as stream:
            self.delivery_token = stream.read().strip()
        if not self.kube_token or not self.delivery_token:
            raise DeliveryError("credentials_required")

    def request(self, path, data=None, method=None, kube=False, public=False, terminal_conflict=False, raw=False):
        headers = {"Accept": "application/json"}
        if kube:
            base = "https://kubernetes.default.svc"
            headers["Authorization"] = "Bearer " + self.kube_token
            context = self.kube_context
        else:
            # Service DNS is a fixed in-cluster transport; Host remains exact.
            base = "http://joyride-test-web:8000" if public else "http://joyride-test-ops:8001"
            headers["Host"] = "joyride-test.eyrie"
            if not public:
                headers["Authorization"] = "Bearer " + self.delivery_token
            context = None
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = Request(
            base + path,
            data=json.dumps(data).encode() if data is not None else None,
            headers=headers,
            method=method,
        )
        try:
            with open_request(request, context=context) as response:
                content = response.read(1048577)
                if len(content) > 1048576:
                    raise DeliveryError("oversize_response")
                if raw:
                    return content
                return json.loads(content) if content else {}
        except HTTPError as error:
            if terminal_conflict and error.code == 409:
                try:
                    value = json.loads(error.read(1024))
                    if set(value) == {"id", "state"} and value["state"] in ("succeeded", "failed"):
                        return value
                except (ValueError, TypeError):
                    pass
            raise DeliveryError("request_failed") from None
        except (URLError, TimeoutError, ValueError):
            raise DeliveryError("request_failed") from None

    def get_deployment(self):
        return self.request(self.base, kube=True)

    def read_journal(self):
        row = self.request(self.journal, kube=True)
        value = json.loads(row.get("data", {}).get("active", "null"))
        return row, value

    def save_journal(self, row, active):
        # PUT with resourceVersion is a compare-and-swap, not an unguarded merge.
        row = dict(row)
        row["data"] = {"active": json.dumps(active, sort_keys=True)}
        return self.request(self.journal, row, method="PUT", kube=True)

    def patch_deployment(self, deployment, operation):
        # JSON Patch tests prevent clobbering another platform rollout.
        operations = [
            {"op": "test", "path": "/metadata/uid", "value": operation["uid"]},
            {"op": "test", "path": "/metadata/resourceVersion", "value": deployment["metadata"]["resourceVersion"]},
        ]
        template = deployment["spec"]["template"]
        for group in ("containers", "initContainers"):
            for index, container in enumerate(template["spec"][group]):
                operations.append({"op": "replace", "path": f"/spec/template/spec/{group}/{index}/image", "value": operation["image"]})
        annotations = dict(template.get("metadata", {}).get("annotations", {}))
        annotations[ANNOTATION] = operation["id"]
        operations.append({"op": "add", "path": "/spec/template/metadata/annotations", "value": annotations})
        headers = {
            "Authorization": "Bearer " + self.kube_token,
            "Content-Type": "application/json-patch+json",
        }
        request = Request("https://kubernetes.default.svc" + self.base, data=json.dumps(operations).encode(), headers=headers, method="PATCH")
        try:
            with open_request(request, context=self.kube_context) as response:
                return json.load(response)
        except (HTTPError, URLError, TimeoutError, ValueError):
            raise DeliveryError("patch_failed") from None

    def result(self, operation, state):
        return self.request(
            "/delivery/" + operation["id"] + "/result",
            {"state": state, "digest": operation["image"].split("@", 1)[1]},
            terminal_conflict=True,
        )

    def ready(self):
        if self.request("/health/ready", public=True).get("status") != "ready":
            return False
        csrf = self.request("/api/csrf", public=True).get("csrf_token", "")
        basemap = self.request("/maps/current", public=True)
        homepage = self.request("/", public=True, raw=True)
        return (
            isinstance(csrf, str) and bool(re.fullmatch(r"[a-zA-Z0-9]{64}", csrf))
            and isinstance(basemap.get("sha256"), str)
            and bool(re.fullmatch(r"[0-9a-f]{64}", basemap["sha256"]))
            and basemap.get("url", "").startswith("/maps/")
            and isinstance(homepage, bytes) and b"<html" in homepage.lower()
        )


def validate_item(item):
    if (
        not isinstance(item, dict)
        or item.get("environment") != "test"
        or item.get("action") not in ("promote", "rollback")
        or not isinstance(item.get("image"), str)
        or not IMAGE.fullmatch(item["image"])
        or str(uuid.UUID(item["id"])) != item["id"]
    ):
        raise DeliveryError("invalid_operation")
    return item


def images(deployment):
    template = deployment["spec"]["template"]["spec"]
    found = {}
    for group, expected in (("containers", CONTAINERS), ("initContainers", INITIALIZERS)):
        rows = template[group]
        if {row["name"] for row in rows} != expected or len(rows) != len(expected):
            raise DeliveryError("unexpected_workload_shape")
        for row in rows:
            if not IMAGE.fullmatch(row["image"]):
                raise DeliveryError("unexpected_existing_image")
            found[group + "/" + row["name"]] = row["image"]
    return found


def assert_unchanged(deployment, operation):
    if deployment["metadata"]["uid"] != operation["uid"]:
        raise DeliveryError("workload_replaced")
    if footprint(deployment) != operation["footprint"]:
        raise DeliveryError("concurrent_workload_change")
    actual = images(deployment)
    target = dict.fromkeys(operation["original"], operation["image"])
    annotations = deployment["spec"]["template"].get("metadata", {}).get("annotations", {})
    owned = annotations.get(ANNOTATION) == operation["id"]
    if owned and actual == target:
        return True
    if actual == operation["original"] and annotations.get(ANNOTATION) == operation["prior_annotation"]:
        return False
    raise DeliveryError("concurrent_workload_change")


def footprint(deployment):
    spec = copy.deepcopy(deployment["spec"])
    template = spec["template"]
    template.setdefault("metadata", {}).setdefault("annotations", {}).pop(ANNOTATION, None)
    for group in ("containers", "initContainers"):
        for row in template["spec"][group]:
            row.pop("image", None)
    return hashlib.sha256(json.dumps(spec, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def complete(deployment, operation):
    if not assert_unchanged(deployment, operation):
        return False
    status = deployment.get("status", {})
    return (
        status.get("observedGeneration", 0) >= deployment["metadata"]["generation"]
        and deployment["spec"].get("replicas") == 1
        and status.get("replicas") == 1
        and status.get("updatedReplicas") == 1
        and status.get("readyReplicas") == 1
        and status.get("availableReplicas") == 1
        and status.get("unavailableReplicas", 0) == 0
    )


def run(client, clock=time.time, pause=time.sleep):
    journal, operation = client.read_journal()
    if operation is None:
        queue = client.request("/delivery/queue")["deployments"]
        # Never claim or consume a production request in this TEST adapter.
        item = next((row for row in queue if row.get("environment") == "test"), None)
        if item is None:
            return "idle"
        validate_item(item)
        deployment = client.get_deployment()
        strategy = deployment["spec"].get("strategy", {})
        if (
            deployment["spec"].get("replicas") != 1
            or strategy.get("type") != "RollingUpdate"
            or strategy.get("rollingUpdate") != {"maxUnavailable": 0, "maxSurge": 1}
            or deployment["spec"].get("minReadySeconds") != 10
        ):
            raise DeliveryError("unexpected_workload_strategy")
        operation = {
            "id": item["id"], "image": item["image"], "environment": "test",
            "action": item["action"], "uid": deployment["metadata"]["uid"],
            "original": images(deployment), "deadline": clock() + 1800,
            "footprint": footprint(deployment),
            "prior_annotation": deployment["spec"]["template"].get("metadata", {}).get("annotations", {}).get(ANNOTATION),
        }
        journal = client.save_journal(journal, operation)
    validate_item(operation)
    # Claim before touching the workload; repeated running callbacks are safe.
    claim = client.result(operation, "running")
    if str(claim.get("id")) == operation["id"] and claim.get("state") in ("succeeded", "failed"):
        client.save_journal(journal, None)
        return "recovered_" + claim["state"]
    if claim.get("state") != "running" or str(claim.get("id")) != operation["id"]:
        raise DeliveryError("claim_not_confirmed")
    deployment = client.get_deployment()
    try:
        applied = assert_unchanged(deployment, operation)
        if clock() >= operation["deadline"]:
            raise DeliveryError("rollout_deadline")
        if not applied:
            client.patch_deployment(deployment, operation)
        while clock() < operation["deadline"]:
            deployment = client.get_deployment()
            if complete(deployment, operation) and client.ready():
                # Read exact workload again AFTER the application probe.
                if complete(client.get_deployment(), operation):
                    break
            pause(5)
        else:
            raise DeliveryError("rollout_deadline")
    except DeliveryError as error:
        if str(error) in ("request_failed", "patch_failed"):
            # Uncertain network delivery is resumed, not a terminal rollout.
            raise
        # No implicit image or schema rollback. Preserve journal if callback is
        # unavailable; a later invocation resumes and closes the same operation.
        result = client.result(operation, "failed")
        if result.get("state") == "failed":
            client.save_journal(journal, None)
        raise
    result = client.result(operation, "succeeded")
    if result.get("state") != "succeeded" or str(result.get("id")) != operation["id"]:
        raise DeliveryError("result_not_confirmed")
    client.save_journal(journal, None)
    return "succeeded"


if __name__ == "__main__":
    try:
        if os.environ.get("RUNTIME_ENV") != "test":
            raise DeliveryError("TEST_only")
        print("TEST delivery: " + run(Client()))
    except Exception:
        print("TEST delivery failed; inspect sanitized job status", file=sys.stderr)
        sys.exit(1)