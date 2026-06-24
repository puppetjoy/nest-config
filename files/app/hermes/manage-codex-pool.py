#!/usr/bin/env python3
"""Audit and clean Hermes' shared openai-codex credential-pool policy.

OAuth token material is runtime-owned state. This helper intentionally never
reads a Puppet-managed token payload and never rewrites root pool entries. It
reports only labels, priorities, sources, counts, and redacted fingerprints,
and its apply mode only removes profile-local Codex shadows so profiles keep
borrowing the shared root pool.
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


def public_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": entry.get("label"),
        "priority": entry.get("priority"),
        "source": entry.get("source"),
        "auth_type": entry.get("auth_type"),
        "fingerprint": fingerprint(entry),
    }


def pool_entries(data: dict[str, Any]) -> list[dict[str, Any]]:
    pools = data.get("credential_pool", {}) if isinstance(data.get("credential_pool"), dict) else {}
    entries = pools.get(PROVIDER, [])
    return entries if isinstance(entries, list) else []


def has_provider_entry(data: dict[str, Any]) -> bool:
    providers = data.get("providers", {}) if isinstance(data.get("providers"), dict) else {}
    return PROVIDER in providers


def profile_state(profile_path: Path) -> dict[str, Any]:
    data = load_json(profile_path, {})
    entries = pool_entries(data) if isinstance(data, dict) else []
    return {
        "provider_entry": has_provider_entry(data) if isinstance(data, dict) else False,
        "pool_entries": len(entries),
    }


def public_state(auth_path: Path, profile_paths: list[Path]) -> dict[str, Any]:
    root = load_json(auth_path, {})
    root_entries = pool_entries(root) if isinstance(root, dict) else []
    profiles = {profile_path.parent.name: profile_state(profile_path) for profile_path in profile_paths}
    return {
        "root_provider_entry": has_provider_entry(root) if isinstance(root, dict) else False,
        "root_pool": [public_entry(entry) for entry in root_entries],
        "root_pool_entries": len(root_entries),
        "profiles": profiles,
    }


def profiles_have_shadows(profile_paths: list[Path]) -> bool:
    return any(
        state["provider_entry"] or state["pool_entries"] > 0
        for state in (profile_state(profile_path) for profile_path in profile_paths)
    )


def apply_profile_cleanup(profile_paths: list[Path]) -> None:
    for profile_path in profile_paths:
        if not profile_path.exists():
            continue
        data = load_json(profile_path, {})
        if not isinstance(data, dict):
            continue
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
    parser.add_argument(
        "--pool-file",
        type=Path,
        help="Deprecated compatibility option; ignored because token material is runtime-owned.",
    )
    parser.add_argument("profiles", nargs="*")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    auth_path = args.home / ".hermes" / "auth.json"
    profile_paths = [args.home / ".hermes" / "profiles" / profile / "auth.json" for profile in args.profiles]

    if args.mode == "status":
        print(json.dumps(public_state(auth_path, profile_paths), sort_keys=True))
        return 0
    if args.mode == "check":
        if profiles_have_shadows(profile_paths):
            print(json.dumps(public_state(auth_path, profile_paths), sort_keys=True))
            return 1
        return 0
    apply_profile_cleanup(profile_paths)
    print(json.dumps(public_state(auth_path, profile_paths), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
