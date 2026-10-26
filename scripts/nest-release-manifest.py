#!/usr/bin/env python3
"""Validate and retain a plain Nest candidate release record; never build/promote."""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import tempfile
from typing import Any

LIMIT = 4 * 1024 * 1024
TOKEN = r"[a-z0-9][a-z0-9._-]{0,127}"
SHA = r"[0-9a-f]{40}"
DIGEST = r"sha256:[0-9a-f]{64}"
IMAGE = r"[a-z0-9][a-z0-9._:-]*(?:/[a-z0-9][a-z0-9._-]*)+@" + DIGEST
PROJECT = r"nest/(?:[a-z0-9][a-z0-9._-]*/)*[a-z0-9][a-z0-9._-]*"
STAGES = {"stage0", "stage1", "stage2", "stage3", "tool"}
TOOL_CONSUMERS = {"nest/tools/" + name for name in (
    "bolt", "pdk", "agent", "firefox", "camofox", "llama.cpp",
    "whisper.cpp", "hadrian", "chromium", "ghc", "r10k", "buildah",
)}


class Invalid(ValueError):
    """An unusable release record. Error messages never echo input values."""


def require(condition, message):
    if not condition:
        raise Invalid(message)


def fields(value, names, where):
    require(type(value) is dict and set(value) == set(names.split()),
            where + ": unexpected or missing fields")


def match(value, pattern, where):
    require(type(value) is str and re.fullmatch(pattern, value) is not None,
            where + ": invalid value")


def text(value, where):
    require(type(value) is str and 0 < len(value) <= 512
            and all(32 <= ord(c) < 127 for c in value), where + ": invalid text")


def canonical(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")


def digest(value):
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def json_integer(value):
    require(len(value.lstrip("-")) <= 20, "oversized JSON integer")
    return int(value)


def load(path):
    with open(path, "rb") as stream:
        raw = stream.read(LIMIT + 1)
    require(len(raw) <= LIMIT, "JSON exceeds size limit")
    try:
        return json.loads(raw, object_pairs_hook=unique_object, parse_int=json_integer,
                          parse_constant=lambda _: (_ for _ in ()).throw(Invalid("nonfinite JSON number")))
    except Invalid:
        raise
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise Invalid("malformed JSON") from exc


def absolute_path(value, where):
    text(value, where)
    path = PurePosixPath(value)
    require(path.is_absolute() and str(path) == value and ".." not in path.parts,
            where + ": requires canonical absolute path")
    return path


def producer(value, source_project, sources):
    fields(value, "project sha pipeline job", "producer")
    require(value["project"] == source_project, "producer: wrong project")
    require(value["sha"] == sources[source_project], "producer: wrong source")
    for key in ("pipeline", "job"):
        require(type(value[key]) is int and value[key] > 0, "producer: invalid numeric identity")


def expectations(value: Any):
    fields(value, "schema kind release sources executor members consumers", "expectations")
    require(type(value["schema"]) is int and value["schema"] in (1, 2)
            and value["kind"] == "nest_release_expectations", "expectations: unsupported schema/kind")
    match(value["release"], TOKEN, "release")
    sources = value["sources"]
    require(type(sources) is dict and 4 <= len(sources) <= 128, "sources: invalid inventory")
    for project, sha in sources.items():
        match(project, PROJECT, "source project")
        match(sha, SHA, "source SHA")
    require({"nest/config", "nest/overlay", "nest/gentoo/portage", "nest/gentoo/haskell"} <= set(sources),
            "sources: missing config, overlay, Portage or Haskell")
    fields(value["executor"], "source image", "executor")
    match(value["executor"]["source"], SHA, "executor source SHA")
    # Schema 1 deliberately retains its historical same-source meaning. Schema
    # 2 separately pins the recipe/config checkout and the executor build; its
    # exact native job, receipt, module inventory and image are still acquired.
    require(value["schema"] == 2 or value["executor"]["source"] == sources["nest/config"],
            "executor: stale config source")
    match(value["executor"]["image"], IMAGE, "executor image")
    members = value["members"]
    require(type(members) is list and 0 < len(members) <= 1024, "members: invalid inventory")
    indexed = {}
    selections = set()
    hosts = set()
    identity_references = set()
    for member in members:
        if not isinstance(member, dict):
            raise Invalid("member: invalid fields")
        private_fields = " identity_reference identity_ca_sha256" if member.get("stage") == "stage3" else ""
        fields(member, "id stage project cpu platform variant host mode bases compatibility identity_root" + private_fields, "member")
        match(member["id"], TOKEN, "member ID")
        require(member["id"] not in indexed, "members: duplicate ID")
        stage = member["stage"]
        require(type(stage) is str and stage in STAGES, "member: unknown stage")
        project = member["project"]
        require(type(project) is str and project in sources, "member: missing source project")
        require(project == "nest/" + stage if stage != "tool" else project.startswith("nest/tools/"),
                "member: wrong source project")
        for key in ("cpu", "variant"):
            match(member[key], TOKEN, "member " + key)
        for key in ("platform", "host"):
            if member[key] is not None:
                match(member[key], TOKEN, "member " + key)
        require((member["platform"] is not None) == (stage in {"stage2", "stage3"}),
                "member: platform required only for Stage 2/3")
        require((member["host"] is not None) == (stage == "stage3"), "member: host required only for Stage 3")
        require(member["mode"] in ("fresh", "refresh"), "member: explicit fresh/refresh required")
        selection = tuple(member[k] for k in ("stage", "project", "cpu", "platform", "variant", "host"))
        require(selection not in selections, "members: duplicate selection")
        selections.add(selection)
        # Stage 0 derives both outputs from one build/base; only Stage 1 consumes
        # a normal/debug input pair. Output pairing remains mandatory for both.
        base_keys = "normal debug" if stage == "stage1" else "image"
        fields(member["bases"], base_keys, "member bases")
        for image in member["bases"].values():
            match(image, IMAGE, "base image")
        compatibility = member["compatibility"]
        if stage in {"stage2", "stage3"}:
            fields(compatibility, "kernel modules_abi firmware bootloader", "compatibility")
            for item in compatibility.values():
                text(item, "compatibility")
        else:
            fields(compatibility, "", "compatibility")
        if stage == "stage3":
            identity = absolute_path(member["identity_root"], "identity root")
            require(member["host"] not in hosts, "members: duplicate host publication")
            hosts.add(member["host"])
            root = PurePosixPath("/nest/releases") / value["release"] / "hosts" / member["host"]
            require(identity != root and identity not in root.parents and root not in identity.parents,
                    "member: identity and generation trees overlap")
            reference = member["identity_reference"]
            match(reference, r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", "identity reference")
            match(member["identity_ca_sha256"], r"[0-9a-f]{64}", "identity CA pin")
            require(identity.name == reference, "member: identity path does not name the exact generation")
            require(reference not in identity_references, "members: duplicate identity reference")
            identity_references.add(reference)
        else:
            require(member["identity_root"] is None, "member: identity only belongs to Stage 3")
        indexed[member["id"]] = member
    consumers = value["consumers"]
    require(type(consumers) is list and len(consumers) <= 128, "consumers: invalid inventory")
    seen = set()
    for consumer in consumers:
        fields(consumer, "project decision reason members", "consumer")
        match(consumer["project"], PROJECT, "consumer project")
        require(consumer["project"] not in seen, "consumers: duplicate project")
        seen.add(consumer["project"])
        require(consumer["decision"] in ("rebuild", "reuse", "defer", "retire"), "consumer: missing decision")
        text(consumer["reason"], "consumer reason")
        ids = consumer["members"]
        require(type(ids) is list and all(type(i) is str for i in ids)
                and len(ids) == len(set(ids)), "consumer: invalid member list")
        require(all(i in indexed and indexed[i]["project"] == consumer["project"] for i in ids),
                "consumer: wrong output member")
        actual = {i for i, row in indexed.items() if row["project"] == consumer["project"]}
        require(set(ids) == actual, "consumer: incomplete member selection")
        require(bool(ids) == (consumer["decision"] in ("rebuild", "reuse")),
                "consumer: reuse/rebuild requires exact members; deferred/retired cannot publish")
    # The caller supplies the full independently selected closure, including legacy consumers.
    require({row["project"] for row in members} <= seen, "consumers: unclassified producer")
    require(TOOL_CONSUMERS <= seen, "consumers: unclassified known tool consumer")
    return indexed


def validate(expected: Any, record: Any):
    indexed = expectations(expected)
    fields(record, "schema kind release expectations_digest outputs", "release record")
    require(type(record["schema"]) is int and record["schema"] == 1
            and record["kind"] == "nest_release_candidate", "release record: unsupported schema/kind")
    require(record["release"] == expected["release"], "release record: wrong release")
    require(record["expectations_digest"] == digest(expected), "release record: changed inputs/matrix")
    outputs = record["outputs"]
    require(type(outputs) is list and len(outputs) == len(indexed), "outputs: incomplete matrix")
    seen = set()
    roots = set()
    for output in outputs:
        fields(output, "member producer executor artifacts", "output")
        member = output["member"]
        require(type(member) is dict and type(member.get("id")) is str
                and member["id"] in indexed, "output: unknown member")
        require(member == indexed[member["id"]], "output: input/compatibility mismatch")
        require(member["id"] not in seen, "outputs: duplicate member")
        seen.add(member["id"])
        producer(output["producer"], member["project"], expected["sources"])
        require(output["executor"] == expected["executor"], "output: stale executor")
        stage = member["stage"]
        keys = "normal debug" if stage in {"stage0", "stage1"} else ("root" if stage == "stage3" else "image")
        fields(output["artifacts"], keys, "output artifacts")
        if stage == "stage3":
            root = output["artifacts"]["root"]
            fields(root, "path dataset_guid content_digest", "root artifact")
            require(root["path"] == "/nest/releases/" + expected["release"] + "/hosts/" + member["host"],
                    "root artifact: not the versioned host generation")
            match(root["dataset_guid"], r"[1-9][0-9]{0,19}", "root dataset GUID")
            match(root["content_digest"], DIGEST, "root content digest")
            require(root["dataset_guid"] not in roots, "root artifact: duplicate dataset identity")
            roots.add(root["dataset_guid"])
        else:
            for image in output["artifacts"].values():
                match(image, IMAGE, "output image")
            if stage in {"stage0", "stage1"}:
                require(output["artifacts"]["normal"].split("@")[-1] != output["artifacts"]["debug"].split("@")[-1],
                        "output: normal/debug must be distinct")
    # Embed the independently checked selection, so retained records are self-describing.
    return {"schema": 1, "kind": "nest_release_manifest", "expectations": expected, "candidate": record}


def generation_binding(manifest: Any, policies: Any, scope: Any = None):
    """Reconcile local generation assertions with a complete runtime manifest.

    This is metadata admission, not independent resource or approval evidence.
    The native producer still checks actual content, host and dataset identities.
    """
    fields(manifest, "schema kind expectations candidate", "manifest")
    require(type(manifest["schema"]) is int and manifest["schema"] == 1
            and manifest["kind"] == "nest_release_manifest", "manifest: unsupported schema/kind")
    checked = validate(manifest["expectations"], manifest["candidate"])
    require(canonical(checked) == canonical(manifest), "manifest: inconsistent content")
    runtime = digest(checked)
    require(type(policies) is dict and 0 < len(policies) <= 128, "generation: invalid host scope")
    outputs = {row["member"]["host"]: row for row in checked["candidate"]["outputs"]
               if row["member"]["stage"] == "stage3"}
    bindings = {}
    for hostname, policy in policies.items():
        match(hostname, r"[a-z0-9][a-z0-9-]{0,62}", "generation host")
        require(hostname in outputs and type(policy) is dict, "generation: missing host output")
        output = outputs[hostname]
        root = output["artifacts"]["root"]
        require(policy.get("hostname") == hostname and policy.get("release") == runtime
                and policy.get("build_release") == checked["expectations"]["release"]
                and policy.get("source") == root["path"]
                and policy.get("content_digest") == root["content_digest"]
                and policy.get("destination") == "/var/lib/nest/generations/" + runtime.split(":")[1],
                "generation: publication/runtime/content mismatch")
        bindings[hostname] = {"member": output["member"]["id"], "root": root,
                              "platform": output["member"]["platform"],
                              "kernel": output["member"]["compatibility"]["kernel"]}
    if scope is not None:
        require(type(scope) is dict and scope.get("release") == runtime, "generation: wave release mismatch")
        # The immutable root records its build source. The wave independently
        # selects the main catalog to apply after boot; a tooling/catalog fix
        # must not force an otherwise unchanged OS generation to be rebuilt.
        match(scope.get("config_source"), SHA, "wave catalog source")
        hosts = scope.get("hosts")
        require(type(hosts) is list and all(type(host) is dict for host in hosts)
                and len(hosts) == len(bindings) and {host.get("name") for host in hosts} == set(bindings),
                "generation: incomplete wave scope")
        for host in hosts:
            bound = bindings[host["name"]]
            require(host.get("kernel") == bound["kernel"] and host.get("platform") == bound["platform"],
                    "generation: wave compatibility mismatch")
    return {"schema": 1, "kind": "nest_generation_release_binding", "manifest_digest": runtime,
            "hosts": bindings, "resource_verification": "not_performed", "reset_authorized": False}


def retain(directory, payload):
    """No-clobber local artifact publication, not a release alias or ZFS publisher."""
    directory = Path(directory)
    require(directory.is_absolute() and directory.resolve() == directory and directory.is_dir(),
            "output directory must already exist and be canonical")
    target = directory / ("release-" + hashlib.sha256(payload).hexdigest() + ".json")
    fd, temporary = tempfile.mkstemp(prefix=".release-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o644)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            pass
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        require(not target.is_symlink() and target.is_file(), "retained artifact is not a regular file")
        with open(target, "rb") as stream:
            require(stream.read(len(payload) + 1) == payload, "retained artifact conflicts with expected bytes")
        return str(target)
    finally:
        os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expectations", required=True, help="independently frozen input and member selection JSON")
    parser.add_argument("--candidate", required=True, help="actual producer output JSON")
    parser.add_argument("--output-dir", help="optional existing canonical durable directory; default is read-only")
    args = parser.parse_args()
    try:
        expected = load(args.expectations)
        record = load(args.candidate)
        manifest = validate(expected, record)
        payload = canonical(manifest)
        path = retain(args.output_dir, payload) if args.output_dir else None
        print(json.dumps({"schema": 1, "kind": "nest_release_manifest_validation",
                          "release": expected["release"], "manifest_digest": digest(manifest),
                          "expectations_digest": digest(expected), "members": len(record["outputs"]),
                          "path": path, "readback_verified": path is not None,
                          "resource_verification": "not_performed", "promotion_authorized": False}, sort_keys=True))
        return 0
    except (Invalid, OSError, RecursionError, TypeError) as exc:
        # Never leak filesystem names, submitted fields or producer secret material.
        message = str(exc) if isinstance(exc, Invalid) else "unreadable or invalid input/output"
        print(json.dumps({"schema": 1, "error": message}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
