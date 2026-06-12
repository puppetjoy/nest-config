#!/usr/bin/env python3
"""Manage Hermes' shared openai-codex credential pool from Puppet.

The pool payload is secret material. This script intentionally reports only
labels, priorities, sources, counts, and redacted fingerprints.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

PROVIDER = "openai-codex"
MANAGED_SOURCE = "manual:device_code"
RESET_FIELDS = (
    "last_status",
    "last_status_at",
    "last_error_code",
    "last_error_reason",
    "last_error_message",
    "last_error_reset_at",
)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text())


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def fingerprint(entry: dict[str, Any]) -> str | None:
    material = "\0".join(str(entry.get(key) or "") for key in ("access_token", "refresh_token"))
    return hashlib.sha256(material.encode()).hexdigest()[:12] if material.strip("\0") else None


def normalized_pool(pool_payload: Any) -> list[dict[str, Any]]:
    if isinstance(pool_payload, dict) and isinstance(pool_payload.get(PROVIDER), list):
        raw_entries = pool_payload[PROVIDER]
    elif isinstance(pool_payload, dict) and isinstance(pool_payload.get("credential_pool"), dict):
        raw_entries = pool_payload["credential_pool"].get(PROVIDER, [])
    elif isinstance(pool_payload, list):
        raw_entries = pool_payload
    else:
        raise SystemExit("pool payload must be a list, a provider map, or an auth-store object")

    entries: list[dict[str, Any]] = []
    for idx, raw_entry in enumerate(raw_entries):
        if not isinstance(raw_entry, dict):
            raise SystemExit(f"pool entry #{idx + 1} is not an object")
        entry = dict(raw_entry)
        label = str(entry.get("label") or "").strip()
        if not label:
            raise SystemExit(f"pool entry #{idx + 1} is missing label")
        entry["label"] = label
        entry["priority"] = int(entry.get("priority", idx))
        entry["source"] = str(entry.get("source") or MANAGED_SOURCE)
        if entry.get("auth_type") is None:
            entry["auth_type"] = "oauth"
        for field in RESET_FIELDS:
            entry[field] = None
        entries.append(entry)

    labels = [str(entry.get("label")) for entry in entries]
    if len(labels) != len(set(labels)):
        raise SystemExit(f"duplicate labels in managed pool: {labels}")
    fps = [fingerprint(entry) for entry in entries]
    real_fps = [fp for fp in fps if fp]
    if len(real_fps) != len(set(real_fps)):
        raise SystemExit("duplicate token fingerprints in managed pool")
    return sorted(entries, key=lambda entry: (int(entry.get("priority", 0)), str(entry.get("label") or "")))


def public_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": entry.get("label"),
        "priority": entry.get("priority"),
        "source": entry.get("source"),
        "auth_type": entry.get("auth_type"),
        "fingerprint": fingerprint(entry),
    }


def public_state(auth_path: Path, profile_paths: list[Path]) -> dict[str, Any]:
    root = load_json(auth_path, {})
    root_entries = root.get("credential_pool", {}).get(PROVIDER, []) if isinstance(root.get("credential_pool"), dict) else []
    profiles: dict[str, Any] = {}
    for profile_path in profile_paths:
        data = load_json(profile_path, {})
        entries = data.get("credential_pool", {}).get(PROVIDER, []) if isinstance(data.get("credential_pool"), dict) else []
        profiles[profile_path.parent.name] = {
            "provider_entry": PROVIDER in (data.get("providers", {}) if isinstance(data.get("providers"), dict) else {}),
            "pool_entries": len(entries),
        }
    return {
        "root_provider_entry": PROVIDER in (root.get("providers", {}) if isinstance(root.get("providers"), dict) else {}),
        "root_pool": [public_entry(entry) for entry in root_entries],
        "profiles": profiles,
    }


def desired_matches(auth_path: Path, pool: list[dict[str, Any]], profile_paths: list[Path]) -> bool:
    current = load_json(auth_path, {})
    current_entries = current.get("credential_pool", {}).get(PROVIDER, []) if isinstance(current.get("credential_pool"), dict) else []
    if [public_entry(entry) for entry in current_entries] != [public_entry(entry) for entry in pool]:
        return False
    providers = current.get("providers", {}) if isinstance(current.get("providers"), dict) else {}
    if PROVIDER in providers:
        return False
    for profile_path in profile_paths:
        data = load_json(profile_path, {})
        providers = data.get("providers", {}) if isinstance(data.get("providers"), dict) else {}
        pools = data.get("credential_pool", {}) if isinstance(data.get("credential_pool"), dict) else {}
        if PROVIDER in providers or PROVIDER in pools:
            return False
    return True


def apply(auth_path: Path, pool: list[dict[str, Any]], profile_paths: list[Path]) -> None:
    root = load_json(auth_path, {"version": 1})
    providers = root.setdefault("providers", {})
    if not isinstance(providers, dict):
        providers = {}
        root["providers"] = providers
    providers.pop(PROVIDER, None)
    credential_pool = root.setdefault("credential_pool", {})
    if not isinstance(credential_pool, dict):
        credential_pool = {}
        root["credential_pool"] = credential_pool
    credential_pool[PROVIDER] = pool
    root["active_provider"] = PROVIDER
    suppressed = root.setdefault("suppressed_sources", {})
    if isinstance(suppressed, dict):
        provider_suppressed = suppressed.setdefault(PROVIDER, [])
        if isinstance(provider_suppressed, list) and "device_code" not in provider_suppressed:
            provider_suppressed.append("device_code")
    root["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    save_json(auth_path, root)

    for profile_path in profile_paths:
        if not profile_path.exists():
            continue
        data = load_json(profile_path, {})
        changed = False
        providers = data.get("providers")
        if isinstance(providers, dict) and PROVIDER in providers:
            providers.pop(PROVIDER)
            changed = True
        pools = data.get("credential_pool")
        if isinstance(pools, dict) and PROVIDER in pools:
            pools.pop(PROVIDER)
            changed = True
        if changed:
            data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            save_json(profile_path, data)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("check", "apply", "status"))
    parser.add_argument("--home", required=True, type=Path)
    parser.add_argument("--pool-file", required=True, type=Path)
    parser.add_argument("profiles", nargs="*")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    auth_path = args.home / ".hermes" / "auth.json"
    profile_paths = [args.home / ".hermes" / "profiles" / profile / "auth.json" for profile in args.profiles]
    pool = normalized_pool(load_json(args.pool_file, {}))

    if args.mode == "status":
        print(json.dumps(public_state(auth_path, profile_paths), sort_keys=True))
        return 0
    if desired_matches(auth_path, pool, profile_paths):
        return 0
    if args.mode == "check":
        print(json.dumps({"desired": [public_entry(entry) for entry in pool], "current": public_state(auth_path, profile_paths)}, sort_keys=True))
        return 1
    apply(auth_path, pool, profile_paths)
    print(json.dumps(public_state(auth_path, profile_paths), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
