#!/usr/bin/env python3
"""Share OpenAI Codex auth across Joy's Hermes profiles.

Hermes profiles can read provider and credential-pool entries from the root
~/.hermes/auth.json when the profile has no local entry for that provider.  This
script makes that fallback intentional for openai-codex: it moves the freshest
available local profile Codex state into the root auth store and removes only the
profile-local openai-codex entries that would shadow it.

The script never prints token values.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import stat
import sys
import time
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - Joy's managed hosts are POSIX
    fcntl = None

PROVIDER = "openai-codex"
AUTH_VERSION = 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Share openai-codex auth via the root Hermes auth store")
    parser.add_argument("mode", choices=("check", "apply"))
    parser.add_argument("--home", default=str(Path.home()), help="user home directory, default: current user's home")
    parser.add_argument("profiles", nargs="*", help="Hermes profile names to de-shadow")
    return parser.parse_args()


@contextmanager
def locked(path: Path, timeout: float = 10.0) -> Iterator[None]:
    lock_path = path.with_suffix(".json.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        if fcntl is None:
            yield
            return
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"timed out waiting for {lock_path}")
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def load_store(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": AUTH_VERSION, "providers": {}}
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        return {"version": AUTH_VERSION, "providers": {}}
    providers = data.get("providers")
    if not isinstance(providers, dict):
        data["providers"] = {}
    pool = data.get("credential_pool")
    if pool is not None and not isinstance(pool, dict):
        data["credential_pool"] = {}
    return data


def write_store(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data["version"] = AUTH_VERSION
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    payload = json.dumps(data, indent=2, sort_keys=False) + "\n"
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, stat.S_IRUSR | stat.S_IWUSR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def provider_state(store: dict[str, Any]) -> dict[str, Any] | None:
    providers = store.get("providers")
    if isinstance(providers, dict) and isinstance(providers.get(PROVIDER), dict):
        return providers[PROVIDER]
    return None


def pool_entries(store: dict[str, Any]) -> list[Any]:
    pool = store.get("credential_pool")
    if isinstance(pool, dict) and isinstance(pool.get(PROVIDER), list):
        return pool[PROVIDER]
    return []


def parse_time(value: Any) -> float:
    if not isinstance(value, str) or not value:
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def entry_is_exhausted(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    fields = [
        str(entry.get("last_status", "")),
        str(entry.get("last_error_code", "")),
        str(entry.get("last_error_reason", "")),
        str(entry.get("status", "")),
    ]
    text = " ".join(fields).lower()
    return any(marker in text for marker in ("exhaust", "usage_limit", "rate_limited", "429"))


def source_score(label: str, store: dict[str, Any]) -> tuple[int, float, str]:
    state = provider_state(store)
    entries = pool_entries(store)
    if state is None and not entries:
        return (0, 0.0, label)
    exhausted = entries and all(entry_is_exhausted(entry) for entry in entries)
    healthy_rank = 1 if exhausted else 2
    timestamps = [parse_time(store.get("updated_at"))]
    if isinstance(state, dict):
        timestamps.append(parse_time(state.get("last_refresh")))
    for entry in entries:
        if isinstance(entry, dict):
            timestamps.extend(parse_time(entry.get(key)) for key in ("updated_at", "last_refresh", "created_at"))
    return (healthy_rank, max(timestamps), label)


def openai_codex_payload(store: dict[str, Any]) -> tuple[dict[str, Any] | None, list[Any]]:
    state = provider_state(store)
    entries = pool_entries(store)
    return (copy.deepcopy(state) if state is not None else None, copy.deepcopy(entries))


def remove_local_codex(store: dict[str, Any]) -> bool:
    changed = False
    providers = store.get("providers")
    if isinstance(providers, dict) and PROVIDER in providers:
        providers.pop(PROVIDER, None)
        changed = True
    pool = store.get("credential_pool")
    if isinstance(pool, dict) and PROVIDER in pool:
        pool.pop(PROVIDER, None)
        changed = True
    return changed


def stores_equal_for_codex(root: dict[str, Any], source: dict[str, Any]) -> bool:
    return openai_codex_payload(root) == openai_codex_payload(source)


def main() -> int:
    args = parse_args()
    home = Path(args.home).expanduser()
    hermes_home = home / ".hermes"
    root_path = hermes_home / "auth.json"
    profile_paths = [(profile, hermes_home / "profiles" / profile / "auth.json") for profile in args.profiles]
    all_paths = [root_path] + [path for _, path in profile_paths]

    with ExitStack() as stack:
        for path in sorted(set(all_paths), key=lambda p: str(p)):
            stack.enter_context(locked(path))

        stores: dict[str, tuple[Path, dict[str, Any]]] = {"root": (root_path, load_store(root_path))}
        for profile, path in profile_paths:
            stores[profile] = (path, load_store(path))

        candidates = [(source_score(label, store), label, store) for label, (_, store) in stores.items()]
        candidates = [candidate for candidate in candidates if candidate[0][0] > 0]
        if not candidates:
            print(f"no {PROVIDER} auth found; nothing to share")
            return 0

        _, source_label, source_store = max(candidates, key=lambda item: item[0])
        root_store = stores["root"][1]
        root_matches = stores_equal_for_codex(root_store, source_store)
        local_shadow_profiles = [label for label, (_, store) in stores.items() if label != "root" and (provider_state(store) is not None or pool_entries(store))]
        changed = (not root_matches) or bool(local_shadow_profiles)

        if args.mode == "check":
            return 1 if changed else 0

        if not root_matches:
            state, entries = openai_codex_payload(source_store)
            if state is not None:
                root_store.setdefault("providers", {})[PROVIDER] = state
                root_store["active_provider"] = PROVIDER
            if entries:
                root_store.setdefault("credential_pool", {})[PROVIDER] = entries
            write_store(root_path, root_store)

        cleaned: list[str] = []
        for label, (path, store) in stores.items():
            if label == "root":
                continue
            if remove_local_codex(store):
                write_store(path, store)
                cleaned.append(label)

    if changed:
        parts = [f"shared {PROVIDER} auth from {source_label}"]
        if cleaned:
            parts.append("removed local shadow entries from " + ", ".join(sorted(cleaned)))
        print("; ".join(parts))
    else:
        print(f"{PROVIDER} auth is already shared")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
