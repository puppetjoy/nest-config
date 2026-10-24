#!/usr/bin/env python3
"""Materialize a bounded CLI report on the Bolt supervisor, never on the host."""

from datetime import datetime
from contextlib import contextmanager
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys


ID = r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}"
DIGEST = r"[0-9a-f]{64}"
PHASES = ["backup", "mount", "sync", "kernel", "unmount", "activate"]


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate field")
        result[key] = value
    return result


def require(condition, message):
    if not condition:
        raise ValueError(message)


def token(value, pattern):
    require(isinstance(value, str) and re.fullmatch(pattern, value) is not None, "invalid report identity")
    return value


def identity_tree(rows):
    require(isinstance(rows, list) and 0 < len(rows) <= 128, "invalid dataset tree")
    result = []
    for row in rows:
        result.append({
            "dataset": token(row["dataset"], r"[A-Za-z0-9_.:/-]{1,255}"),
            "guid": token(row["guid"], r"[1-9][0-9]*"),
            "mountpoint": token(row["mountpoint"], r"/[A-Za-z0-9_./-]*"),
        })
    require(len({row["dataset"] for row in result}) == len(result), "duplicate dataset identity")
    return result


def reboot_time(value):
    token(value, r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def reboot_receipt(data, phases, prepared):
    """Validate native submission semantics, never infer an observed boot."""
    if "reboot" not in data:
        require(data.get("reboot_requested") is False, "request outcome without receipt")
        return None
    receipt = data["reboot"]
    require(isinstance(receipt, dict), "invalid reboot receipt")
    keys = {"schema", "state", "boot_id", "requested_at", "command"}
    if receipt.get("state") == "returned":
        keys |= {"finished_at", "native_exit"}
    require(set(receipt) == keys and type(receipt["schema"]) is int and receipt["schema"] == 1 and
            receipt["state"] in ("intent", "returned") and
            receipt["command"] == ["systemctl", "--no-block", "reboot"] and
            receipt["boot_id"] == data["host"]["boot_id"], "invalid reboot binding")
    capacity = data.get("capacity")
    require(prepared and isinstance(capacity, dict) and type(capacity.get("accounting_contract")) is int and
            capacity["accounting_contract"] == 2, "missing reboot preparation provenance")
    requested = reboot_time(receipt["requested_at"])
    for phase in phases:
        require(phase["state"] == "complete" and phase["native_exit"] in (None, 0) and
                all(command["success"] and command["native_exit"] in (None, 0) for command in phase["commands"]),
                "unsuccessful reboot preparation")
        finished = datetime.fromisoformat(phase["finished_at"].replace("Z", "+00:00"))
        require(finished.tzinfo is not None and finished <= requested, "reboot predates preparation")
    outcome = None
    if receipt["state"] == "returned":
        require(type(receipt["native_exit"]) is int and 0 <= receipt["native_exit"] <= 255 and
                reboot_time(receipt["finished_at"]) >= requested, "invalid reboot completion")
        outcome = receipt["native_exit"] == 0
    require(data.get("reboot_requested") is outcome, "inconsistent reboot outcome")
    return dict(receipt)


def project(raw, transaction, release, hostname):
    """Project known fields; no arbitrary command output, exception or environment."""
    require(isinstance(raw, str) and len(raw.encode("utf-8")) <= 262144, "report exceeds size bound")
    data = json.loads(raw, object_pairs_hook=unique)
    require(isinstance(data, dict), "report must be an object")
    require(type(data.get("schema")) is int and data["schema"] in (1, 2), "unsupported CLI report schema")
    require(data.get("kind") == "reset_transaction_report", "not a CLI transaction report")
    require(data.get("id") == token(transaction, ID), "transaction mismatch")
    require(data.get("release") == token(release, "sha256:" + DIGEST), "release mismatch")
    host = data["host"]
    require(isinstance(host, dict), "invalid host object")
    require(host.get("hostname") == token(hostname, r"[A-Za-z0-9][A-Za-z0-9_.-]{0,252}"), "host mismatch")
    state = data["state"]
    require(state in ("pending", "stopped", "prepared", "accepted", "finalizing", "finalized"), "invalid state")
    lifecycle = state in ("accepted", "finalizing", "finalized")
    require((data["schema"] == 2) == lifecycle, "schema and lifecycle disagree")
    prepared = state in ("prepared", "accepted", "finalizing", "finalized")
    require(data.get("success") is prepared and data.get("accepted") is lifecycle and
            data.get("finalized") is (state == "finalized"),
            "inconsistent outcome flags")
    rows = data["phases"]
    require(isinstance(rows, list) and len(rows) <= len(PHASES), "invalid phase count")
    phases = []
    for index, row in enumerate(rows):
        require(row["phase"] == PHASES[index], "invalid phase order")
        require(row["state"] in ("started", "failed", "complete"), "invalid phase state")
        require(index == len(rows) - 1 or row["state"] == "complete", "incomplete earlier phase")
        require(type(row["attempt"]) is int and row["attempt"] > 0, "invalid attempt")
        require(row["boot_id"] == host["boot_id"], "phase boot mismatch")
        phase = {key: row[key] for key in ("phase", "state", "attempt", "boot_id")}
        phase["started_at"] = token(row["started_at"], r"[0-9T:.+Z-]{20,40}")
        if row["state"] != "started":
            phase["finished_at"] = token(row["finished_at"], r"[0-9T:.+Z-]{20,40}")
            native_exit = row["native_exit"]
            require(native_exit is None or type(native_exit) is int and 0 <= native_exit <= 255, "invalid native exit")
            phase["native_exit"] = native_exit
            commands = row["commands"]
            require(isinstance(commands, list) and len(commands) <= 128, "invalid command outcomes")
            phase["commands"] = []
            for command in commands:
                exit_code = command["native_exit"]
                require(exit_code is None or type(exit_code) is int and 0 <= exit_code <= 255, "invalid command exit")
                require(type(command["success"]) is bool, "invalid command result")
                require(command["operation"] in ("mountpoint", "root", "source", "modules", "puppet", "kexec"),
                        "unsupported native operation")
                require(row["state"] != "complete" or command["success"], "failed command in completed phase")
                phase["commands"].append({
                    "operation": token(command["operation"], r"[A-Za-z0-9_. -]{1,128}"),
                    "native_exit": exit_code, "success": command["success"],
                })
        phases.append(phase)
    require(not prepared or len(phases) == len(PHASES) and all(row["state"] == "complete" for row in phases),
            "incomplete prepared report")
    reboot = reboot_receipt(data, phases, prepared)
    host_result = {"hostname": hostname, "boot_id": token(host["boot_id"], r"[0-9a-f-]{36}"),
                   "pool_guid": token(host["pool_guid"], r"[1-9][0-9]*")}
    for key in ("current", "target", "next_boot"):
        host_result[key] = token(host[key], r"[A-Za-z0-9_.:/-]{1,255}")
    host_result["current_tree"] = identity_tree(host["current_tree"])
    require(any(row["dataset"] == host_result["current"] and row["mountpoint"] == "/"
                for row in host_result["current_tree"]), "missing current root identity")
    require(all(row["dataset"] == host_result["current"] or row["dataset"].startswith(host_result["current"] + "/")
                for row in host_result["current_tree"]), "unrelated current tree member")
    shared = data["shared_state"]
    require("ROOT" not in shared["dataset"].split("/"), "shared state must be outside ROOT")
    source = data["source"]
    require(source["release"] == release, "source release mismatch")
    target_tree = None if data["target_tree"] is None else identity_tree(data["target_tree"])
    require(not prepared or target_tree is not None, "missing prepared target identity")
    if target_tree is not None:
        require(any(row["dataset"] == host_result["target"] and row["mountpoint"] == "/" for row in target_tree),
                "missing target root identity")
        require(all(row["dataset"] == host_result["target"] or row["dataset"].startswith(host_result["target"] + "/")
                    for row in target_tree), "unrelated target tree member")
    result = {
        "schema": 1, "kind": "nest_update_retained_report", "cli_schema": data["schema"],
        "id": transaction, "release": release, "state": state, "host": host_result,
        "host_identity_sha256": token(data["host_identity_sha256"], DIGEST),
        "shared_state": {"dataset": token(shared["dataset"], r"[A-Za-z0-9_.:/-]{1,255}"),
                         "guid": token(shared["guid"], r"[1-9][0-9]*"),
                         "pool_guid": token(shared["pool_guid"], r"[1-9][0-9]*")},
        "source": {"path": token(source["path"], r"/[A-Za-z0-9_./-]+"),
                   "dataset": token(source["dataset"], r"[A-Za-z0-9_.:/-]{1,255}"),
                   "guid": token(source["guid"], r"[1-9][0-9]*"),
                   "creation_txg": token(source["creation_txg"], r"[1-9][0-9]*"), "release": release},
        "policy": {key: token(data["policy"][key], DIGEST) for key in ("filter_sha256", "cli_sha256")},
        "target_tree": target_tree, "phases": phases,
        "prepared": prepared, "cli_accepted": lifecycle, "cli_finalized": state == "finalized",
        "reboot_requested": data["reboot_requested"],
        "acceptance_independently_verified": False,
        "transport_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    }
    if reboot is not None:
        result["reboot"] = reboot
    if "observation" in data:
        observed = data["observation"]
        require(isinstance(observed, dict), "invalid observation")
        boot_id = token(observed["boot_id"], r"[0-9a-f-]{36}")
        current = token(observed["current"], r"[A-Za-z0-9_.:/-]{1,255}")
        next_boot = token(observed["next_boot"], r"[A-Za-z0-9_.:/-]{1,255}")
        require(type(observed["boot_changed"]) is bool and
                observed["boot_changed"] == (boot_id != host_result["boot_id"]), "inconsistent boot observation")
        expected = observed["expected_target_booted"]
        require(type(expected) is bool or expected is None, "invalid target observation")
        require(current in (host_result["current"], host_result["target"]), "unknown observed current")
        require(expected == (current == host_result["target"]) if target_tree is not None else expected is None,
                "inconsistent target observation")
        require(type(observed["accepted"]) is bool and (not observed["accepted"] or lifecycle),
                "invalid observed acceptance")
        result["observation"] = {
            "boot_id": boot_id, "boot_changed": observed["boot_changed"],
            "current": current, "next_boot": next_boot,
            "expected_target_booted": expected, "cli_accepted_current_boot": observed["accepted"],
        }
    return result


def output_directory(directory):
    # An existing canonical directory is deliberate: never silently create an
    # unmounted/remote destination or hide a misspelled supervisor path.
    directory = Path(directory)
    require(directory.is_absolute() and str(directory.resolve(strict=True)) == str(directory),
            "output directory must already exist and be canonical")
    require(directory.is_dir() and not directory.is_symlink(), "invalid output directory")
    return directory


def file_identity(value):
    return (value.st_dev, value.st_ino, value.st_mode, value.st_nlink, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns)


def directory_identity(directory, descriptor):
    # Directory size/timestamps change during our own publication. Bind its
    # location and inode, not those expected directory-entry mutations.
    current = output_directory(directory).stat()
    opened = os.fstat(descriptor)
    require((current.st_dev, current.st_ino) == (opened.st_dev, opened.st_ino),
            "report directory changed")


@contextmanager
def report_directory(directory):
    directory = output_directory(directory)
    descriptor = os.open(directory.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        # Resolve each component relative to its already opened parent. A
        # canonical-path precheck alone cannot exclude a swapped ancestor.
        for part in directory.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        directory_identity(directory, descriptor)
        yield directory, descriptor
        directory_identity(directory, descriptor)
    finally:
        os.close(descriptor)


def read_report_at(directory_fd, name, limit):
    token(name, r"[A-Za-z0-9][A-Za-z0-9_.-]{0,480}")
    require(type(limit) is int and limit > 0, "invalid report read bound")
    # NONBLOCK prevents a substituted FIFO from hanging before fstat refuses it.
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise ValueError("report must not be a symlink") from None
        raise
    try:
        before = os.fstat(descriptor)
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= limit,
                "report must be a bounded single-link regular file")
        observations = []
        # Some filesystems expose coarse timestamps. Re-read the same inode so
        # a same-size in-place mutation cannot rely on timestamp equality alone.
        for _ in range(2):
            os.lseek(descriptor, 0, os.SEEK_SET)
            chunks = []
            remaining = limit + 1
            while remaining:
                chunk = os.read(descriptor, min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            observations.append(b"".join(chunks))
        raw = observations[0]
        after = os.fstat(descriptor)
        named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        require(raw == observations[1] and len(raw) == before.st_size and len(raw) <= limit and
                file_identity(before) == file_identity(after) == file_identity(named),
                "report changed during readback")
        return raw
    finally:
        os.close(descriptor)


def read_report(path, limit):
    path = Path(path)
    with report_directory(path.parent) as (_, directory_fd):
        return read_report_at(directory_fd, path.name, limit)


def publish_document(report, directory, prefix):
    directory = output_directory(directory)
    token(prefix, r"[A-Za-z0-9][A-Za-z0-9_.-]{0,400}")
    payload = (json.dumps(report, sort_keys=True, indent=2) + "\n").encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    # Content-addressed versions retain pending, failed and completed reports;
    # later observations never overwrite an earlier phase's only receipt.
    name = prefix + "-" + digest + ".json"
    target = directory / name
    with report_directory(directory) as (_, directory_fd):
        temporary = ".nest-update-report-" + secrets.token_hex(16)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(payload)
                output.flush()
                os.fchmod(output.fileno(), 0o644)  # Only sanitized projections are public.
                os.fsync(output.fileno())
            try:
                os.link(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd, follow_symlinks=False)
            except FileExistsError:
                pass  # Read the existing inode below; never replace it.
            os.unlink(temporary, dir_fd=directory_fd)
            os.fsync(directory_fd)
            raw = read_report_at(directory_fd, name, len(payload))
            require(raw == payload, "retained report readback mismatch")
            require(json.loads(raw, object_pairs_hook=unique) == report, "retained report parse mismatch")
            directory_identity(directory, directory_fd)
            return {"path": str(target), "sha256": digest, "bytes": len(payload), "readback_verified": True}
        finally:
            try:
                os.unlink(temporary, dir_fd=directory_fd)
            except FileNotFoundError:
                pass


def publish(report, directory):
    receipt = publish_document(report, directory, report["host"]["hostname"] + "-" + report["id"])
    return dict(receipt, id=report["id"], release=report["release"], hostname=report["host"]["hostname"],
                phase_count=len(report["phases"]), state=report["state"],
                cli_accepted=report["cli_accepted"], cli_finalized=report["cli_finalized"],
                observation_retained="observation" in report)


def main():
    try:
        arguments = json.load(sys.stdin)
        if arguments.get('action', 'retain') == 'check':
            token(arguments['transaction'], ID)
            token(arguments['release'], 'sha256:' + DIGEST)
            token(arguments['hostname'], r'[A-Za-z0-9][A-Za-z0-9_.-]{0,252}')
            output_directory(arguments['output_dir'])
            print(json.dumps({'destination_checked': True, 'host_action_performed': False}))
            return 0
        require(arguments.get('action', 'retain') == 'retain', 'invalid action')
        report = project(arguments["report"], arguments["transaction"], arguments["release"], arguments["hostname"])
        print(json.dumps(publish(report, arguments["output_dir"])))
    except (KeyError, TypeError, ValueError, OSError):
        # Do not print raw payloads, paths embedded in exceptions, or private host errors.
        print(json.dumps({"_error": {"kind": "nest/update-report", "msg": "Update report validation or durable publication failed"}}))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
