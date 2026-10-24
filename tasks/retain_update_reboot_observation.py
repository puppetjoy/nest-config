#!/usr/bin/env python3
"""Bind a read-only status to a reopened pre-reboot supervisor observation."""

import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from retain_update_reboot import context  # noqa: E402
from retain_update_report import output_directory, project, publish_document, read_report, require, unique  # noqa: E402

LIMIT = 262144
BINDING = ("id", "release", "host", "host_identity_sha256", "shared_state", "source", "policy", "target_tree", "phases")


def admission(arguments):
    """Reopen the exact existing publication, never accept a path alone."""
    receipt = arguments["admission"]
    require(isinstance(receipt, dict) and receipt.get("readback_verified") is True, "missing admission receipt")
    for key in ("transaction", "release", "hostname"):
        require(receipt.get(key) == arguments[key], "admission context mismatch")
    directory = output_directory(arguments["output_dir"])
    path = Path(receipt["path"])
    require(path.parent == directory, "invalid admission path")
    raw = read_report(path, LIMIT)
    digest = hashlib.sha256(raw).hexdigest()
    require(len(raw) <= LIMIT and type(receipt["bytes"]) is int and len(raw) == receipt["bytes"] and
            digest == receipt["sha256"] and
            path.name == "reboot-plan-" + arguments["transaction"] + "-" + digest + ".json", "admission readback mismatch")
    data = json.loads(raw, object_pairs_hook=unique)
    require(type(data.get("schema")) is int and data["schema"] == 1 and data.get("kind") == "nest_update_reboot_plan" and
            data.get("read_only") is True and data.get("execution_requested") is False and
            data.get("acceptance_recorded") is False, "not a retained reboot plan")
    for key in ("transaction", "release", "hostname", "read_only", "execution_requested", "acceptance_recorded",
                "reboot_eligible", "reboot_reason"):
        require(data.get(key) == receipt.get(key) and type(data.get(key)) is type(receipt.get(key)), "admission receipt mismatch")
    before = data["report"]
    require(before["id"] == arguments["transaction"] and before["release"] == arguments["release"] and
            before["host"]["hostname"] == arguments["hostname"] and before["state"] == "prepared" and
            before["prepared"] is True and before["cli_accepted"] is False, "not a pre-reboot admission")
    reason = data["reboot_reason"]
    require(reason in ("eligible", "already_requested") and data["reboot_eligible"] is (reason == "eligible") and
            ("reboot" in before) == (reason == "already_requested"), "invalid pre-reboot outcome")
    observed = before["observation"]
    require(observed["boot_id"] == before["host"]["boot_id"] and observed["boot_changed"] is False and
            observed["expected_target_booted"] is False and observed["current"] == before["host"]["current"] and
            observed["next_boot"] == before["host"]["target"], "admission is not the original prepared boot")
    return before, {key: receipt[key] for key in ("path", "sha256", "bytes")}


def retain(arguments):
    before, retained = admission(arguments)
    after = project(arguments["report"], arguments["transaction"], arguments["release"], arguments["hostname"])
    require(all(after[key] == before[key] for key in BINDING), "transaction identity changed")
    require(after["prepared"], "transaction no longer prepared")
    if "reboot" in before:
        previous = before["reboot"]
        current = after.get("reboot", {})
        require(all(current.get(key) == previous[key] for key in ("schema", "boot_id", "requested_at", "command")),
                "reboot intent changed or disappeared")
        require(previous["state"] != "returned" or current == previous, "completed submission changed")
    observed = after["observation"]
    require(observed["next_boot"] == after["host"]["target"], "next boot changed")
    changed = observed["boot_changed"]
    if changed:
        require("reboot" in after and observed["expected_target_booted"] is True and
                observed["current"] == after["host"]["target"], "changed boot without native continuity")
    else:
        require(after["state"] == "prepared" and observed["expected_target_booted"] is False and
                observed["current"] == after["host"]["current"], "unsafe original boot")
    reboot = after.get("reboot")
    outcome = "not_attempted" if reboot is None else "unknown" if reboot["state"] == "intent" else (
        "returned_success" if reboot["native_exit"] == 0 else "returned_failure")
    document = {
        "schema": 1, "kind": "nest_update_reboot_observation", "transaction": arguments["transaction"],
        "release": arguments["release"], "hostname": arguments["hostname"], "admission": retained, "report": after,
        "read_only": True, "execution_requested": False, "submission_outcome": outcome,
        "target_boot_observed": changed, "resubmission_allowed": False, "acceptance_recorded": False,
    }
    receipt = publish_document(document, arguments["output_dir"], "reboot-observation-" + arguments["transaction"])
    return dict(receipt, **{key: document[key] for key in (
        "transaction", "release", "hostname", "read_only", "execution_requested", "submission_outcome",
        "target_boot_observed", "resubmission_allowed", "acceptance_recorded")})


def main():
    try:
        raw = sys.stdin.buffer.read(LIMIT + 1)
        require(len(raw) <= LIMIT, "input exceeds size bound")
        arguments = json.loads(raw, object_pairs_hook=unique)
        context(arguments)
        require(arguments["action"] in ("check", "retain"), "invalid action")
        admission(arguments)
        result = {"destination_checked": True, "admission_readback_verified": True, "host_action_performed": False}
        if arguments["action"] == "retain":
            result = retain(arguments)
        print(json.dumps(result))
        return 0
    except (KeyError, TypeError, ValueError, OSError, UnicodeError, RecursionError):
        print(json.dumps({"_error": {"kind": "nest/update-reboot-observation",
                                    "msg": "Reboot continuity or retention failed; observe and inspect, never resubmit"}}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
