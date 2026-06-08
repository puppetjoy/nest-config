#!/usr/bin/env python3
"""Manage OpenAI Codex auth slots for Joy's Hermes profiles.

The steady-state Nest model is:

* Joy captures two owner-operated OAuth results as labelled slots (primary and
  secondary) and stores the encrypted JSON in nest/private Hiera.
* Puppet renders that encrypted private value to a root-fallback slot store that
  is readable only by Joy.
* This helper activates one slot by copying only the openai-codex provider and
  credential-pool payload into ~/.hermes/auth.json, then removes profile-local
  openai-codex shadow entries from managed profiles.

The helper prints labels, counts, fingerprints, and status metadata only. It
never prints token values. The capture --eyaml mode sends plaintext only to the
local eyaml process over stdin, then prints the encrypted EYAML block.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import stat
import subprocess
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
DEFAULT_LABELS = ("primary", "secondary")
SECRETISH_KEYS = {
    "access_token",
    "refresh_token",
    "id_token",
    "token",
    "api_key",
    "authorization",
    "cookie",
    "cookies",
    "client_secret",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage labelled openai-codex auth slots")
    parser.add_argument("mode", choices=("check", "apply", "switch", "status", "capture", "fingerprint"))
    parser.add_argument("args", nargs="*", help="switch/capture: LABEL [PROFILES...]; other modes: [PROFILES...]")
    parser.add_argument("--home", default=str(Path.home()), help="user home directory, default: current user's home")
    parser.add_argument("--slots-file", help="managed JSON file containing labelled Codex slots")
    parser.add_argument("--active-file", help="runtime file containing the selected slot label")
    parser.add_argument("--default-label", default="primary", help="slot label to use when no active-file exists")
    parser.add_argument("--from-profile", default=None, help="capture from a profile auth store instead of root")
    parser.add_argument("--eyaml-label", help="capture mode: encrypt captured slot JSON with eyaml and this Hiera label")
    parser.add_argument("--out", help="capture mode: write captured slot JSON to a 0600 local file instead of stdout")
    parser.add_argument("--restart", action="store_true", help="switch mode: restart Hermes gateway/dashboard units for named profiles")
    args = parser.parse_intermixed_args()
    if args.mode in {"switch", "capture"}:
        if not args.args:
            parser.error(f"{args.mode} requires a slot label")
        args.label = args.args[0]
        args.profiles = args.args[1:]
    else:
        args.label = None
        args.profiles = args.args
    return args


@contextmanager
def locked(path: Path, timeout: float = 10.0) -> Iterator[None]:
    lock_path = path.with_suffix(f"{path.suffix}.lock") if path.suffix else path.with_name(f"{path.name}.lock")
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
    write_secret_text(path, payload)


def write_secret_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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
    exhausted = bool(entries) and all(entry_is_exhausted(entry) for entry in entries)
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


def slot_to_store(slot: Any) -> dict[str, Any]:
    if isinstance(slot, str):
        try:
            slot = json.loads(slot)
        except json.JSONDecodeError as exc:
            raise ValueError("slot string must contain a JSON object") from exc
    if not isinstance(slot, dict):
        raise ValueError("slot payload must be a JSON object")
    if PROVIDER in slot and isinstance(slot[PROVIDER], dict):
        # Backward-compatible shorthand: {"openai-codex": {provider state}}
        return {"version": AUTH_VERSION, "providers": {PROVIDER: slot[PROVIDER]}}
    if provider_state(slot) is not None or pool_entries(slot):
        return copy.deepcopy(slot)
    if "provider" in slot or "pool" in slot:
        store: dict[str, Any] = {"version": AUTH_VERSION, "providers": {}}
        if isinstance(slot.get("provider"), dict):
            store["providers"][PROVIDER] = copy.deepcopy(slot["provider"])
        if isinstance(slot.get("pool"), list):
            store["credential_pool"] = {PROVIDER: copy.deepcopy(slot["pool"])}
        return store
    raise ValueError("slot payload must contain providers/credential_pool or provider/pool")


def store_to_slot(store: dict[str, Any], label: str) -> dict[str, Any]:
    state, entries = openai_codex_payload(store)
    if state is None and not entries:
        raise ValueError(f"no {PROVIDER} auth found in capture source")
    slot: dict[str, Any] = {
        "label": label,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "providers": {},
    }
    if state is not None:
        slot["providers"][PROVIDER] = state
    if entries:
        slot["credential_pool"] = {PROVIDER: entries}
    return slot


def load_slots(path: Path) -> dict[str, dict[str, Any]]:
    data = load_store(path) if path.exists() else {}
    raw_slots = data.get("slots", data)
    if not isinstance(raw_slots, dict):
        raise ValueError(f"{path} must contain a JSON object of slots")
    slots: dict[str, dict[str, Any]] = {}
    for label, slot in raw_slots.items():
        if label in {"version", "updated_at", "active_label"}:
            continue
        if not isinstance(label, str) or not label:
            raise ValueError("slot labels must be non-empty strings")
        slots[label] = slot_to_store(slot)
    return slots


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


def active_label(active_path: Path, default_label: str) -> str:
    if active_path.exists():
        label = active_path.read_text(encoding="utf-8").strip()
        if label:
            return label
    return default_label


def set_active_label(active_path: Path, label: str) -> None:
    write_secret_text(active_path, f"{label}\n")


def auth_paths(home: Path, profiles: list[str]) -> tuple[Path, list[tuple[str, Path]]]:
    hermes_home = home / ".hermes"
    root_path = hermes_home / "auth.json"
    profile_paths = [(profile, hermes_home / "profiles" / profile / "auth.json") for profile in profiles]
    return root_path, profile_paths


def activate_slot(label: str, slot_store: dict[str, Any], root_store: dict[str, Any], stores: dict[str, tuple[Path, dict[str, Any]]]) -> tuple[bool, list[str]]:
    changed = False
    if not stores_equal_for_codex(root_store, slot_store):
        state, entries = openai_codex_payload(slot_store)
        if state is not None:
            root_store.setdefault("providers", {})[PROVIDER] = state
            root_store["active_provider"] = PROVIDER
        if entries:
            root_store.setdefault("credential_pool", {})[PROVIDER] = entries
        else:
            pool = root_store.get("credential_pool")
            if isinstance(pool, dict):
                pool.pop(PROVIDER, None)
        changed = True

    cleaned: list[str] = []
    for store_label, (path, store) in stores.items():
        if store_label == "root":
            continue
        if remove_local_codex(store):
            write_store(path, store)
            cleaned.append(store_label)
            changed = True
    return changed, cleaned


def redacted_fingerprint(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def summarize_slot(label: str, store: dict[str, Any], active: bool = False) -> dict[str, Any]:
    state = provider_state(store)
    entries = pool_entries(store)
    exhausted_entries = sum(1 for entry in entries if entry_is_exhausted(entry))
    timestamps: list[float] = [parse_time(store.get("updated_at"))]
    if isinstance(state, dict):
        timestamps.append(parse_time(state.get("last_refresh")))
    for entry in entries:
        if isinstance(entry, dict):
            timestamps.extend(parse_time(entry.get(key)) for key in ("updated_at", "last_refresh", "created_at"))
    newest = max(timestamps) if timestamps else 0.0
    return {
        "label": label,
        "active": active,
        "provider_entry": state is not None,
        "pool_entries": len(entries),
        "exhausted_pool_entries": exhausted_entries,
        "fingerprint": redacted_fingerprint(openai_codex_payload(store)),
        "newest_timestamp": datetime.fromtimestamp(newest, timezone.utc).isoformat() if newest else None,
    }


def print_status(slots: dict[str, dict[str, Any]], active: str, root_store: dict[str, Any], stores: dict[str, tuple[Path, dict[str, Any]]]) -> None:
    print(json.dumps({
        "provider": PROVIDER,
        "active_label": active if active in slots else None,
        "slots": [summarize_slot(label, store, active=(label == active)) for label, store in sorted(slots.items())],
        "root": summarize_slot("root", root_store, active=False),
        "profile_shadows": sorted(label for label, (_, store) in stores.items() if label != "root" and (provider_state(store) is not None or pool_entries(store))),
    }, indent=2))


def run_restart(profiles: list[str]) -> None:
    if not profiles:
        return
    units: list[str] = []
    for profile in profiles:
        units.extend([f"hermes-gateway@{profile}.service", f"hermes-dashboard@{profile}.service"])
    cmd = ["systemctl", "--user", "try-reload-or-restart", *units]
    completed = subprocess.run(cmd, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if completed.returncode != 0:
        print("restart command failed (token values were not involved)", file=sys.stderr)
        if completed.stderr.strip():
            print(completed.stderr.strip(), file=sys.stderr)
        raise SystemExit(completed.returncode)
    print("restarted " + ", ".join(units))


def capture(args: argparse.Namespace, home: Path) -> int:
    profile = args.from_profile
    path = home / ".hermes" / "auth.json" if profile is None else home / ".hermes" / "profiles" / profile / "auth.json"
    label = args.label or args.default_label
    with locked(path):
        slot = store_to_slot(load_store(path), label)
    payload = json.dumps(slot, indent=2, sort_keys=False) + "\n"
    if args.out:
        write_secret_text(Path(args.out).expanduser(), payload)
        print(f"captured {PROVIDER} slot {label} to {args.out} (0600; contains token material)")
        return 0
    if args.eyaml_label:
        completed = subprocess.run(
            ["eyaml", "encrypt", "--stdin", "--output", "block", "--label", args.eyaml_label],
            input=payload,
            text=True,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if completed.returncode != 0:
            if completed.stderr.strip():
                print(completed.stderr.strip(), file=sys.stderr)
            return completed.returncode
        print(completed.stdout.rstrip())
        return 0
    raise SystemExit("capture requires --eyaml-label or --out so plaintext is not printed")


def fingerprint_capture_source(args: argparse.Namespace, home: Path) -> int:
    profile = args.from_profile
    path = home / ".hermes" / "auth.json" if profile is None else home / ".hermes" / "profiles" / profile / "auth.json"
    label = profile or "root"
    with locked(path):
        source_store = load_store(path)
    state, entries = openai_codex_payload(source_store)
    if state is None and not entries:
        raise SystemExit(f"no {PROVIDER} auth found in {label} capture source")

    hermes_home = home / ".hermes"
    slots_path = Path(args.slots_file).expanduser() if args.slots_file else hermes_home / "codex-auth" / "slots.json"
    source_fingerprint = redacted_fingerprint(openai_codex_payload(source_store))
    matches: list[str] = []
    if slots_path.exists():
        with locked(slots_path):
            slots = load_slots(slots_path)
        matches = sorted(
            slot_label
            for slot_label, slot_store in slots.items()
            if redacted_fingerprint(openai_codex_payload(slot_store)) == source_fingerprint
        )

    print(json.dumps({
        "provider": PROVIDER,
        "capture_source": label,
        "slots_file_exists": slots_path.exists(),
        "fingerprint": source_fingerprint,
        "provider_entry": state is not None,
        "pool_entries": len(entries),
        "exhausted_pool_entries": sum(1 for entry in entries if entry_is_exhausted(entry)),
        "matches_existing_slots": matches,
        "safe_to_capture_as_distinct_slot": not matches,
    }, indent=2))
    return 0


def legacy_share(args: argparse.Namespace, home: Path) -> int:
    root_path, profile_paths = auth_paths(home, args.profiles)
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
            if args.mode != "check":
                print(f"no {PROVIDER} auth found; nothing to share")
            return 0
        _, source_label, source_store = max(candidates, key=lambda item: item[0])
        root_store = stores["root"][1]
        changed, cleaned = activate_slot(source_label, source_store, root_store, stores)
        if args.mode == "check":
            return 1 if changed else 0
        if changed:
            write_store(root_path, root_store)
            parts = [f"shared {PROVIDER} auth from {source_label}"]
            if cleaned:
                parts.append("removed local shadow entries from " + ", ".join(sorted(cleaned)))
            print("; ".join(parts))
        else:
            print(f"{PROVIDER} auth is already shared")
        return 0


def main() -> int:
    args = parse_args()
    home = Path(args.home).expanduser()
    if args.mode == "fingerprint":
        return fingerprint_capture_source(args, home)
    if args.mode == "capture":
        return capture(args, home)

    hermes_home = home / ".hermes"
    slots_path = Path(args.slots_file).expanduser() if args.slots_file else hermes_home / "codex-auth" / "slots.json"
    active_path = Path(args.active_file).expanduser() if args.active_file else hermes_home / "codex-auth" / "active-label"

    if not slots_path.exists():
        if args.mode in {"switch", "status"}:
            raise SystemExit(f"slot store {slots_path} does not exist; complete capture/private Hiera workflow first")
        return legacy_share(args, home)

    root_path, profile_paths = auth_paths(home, args.profiles)
    all_paths = [root_path, slots_path, active_path] + [path for _, path in profile_paths]
    with ExitStack() as stack:
        for path in sorted(set(all_paths), key=lambda p: str(p)):
            stack.enter_context(locked(path))
        slots = load_slots(slots_path)
        if not slots:
            raise SystemExit(f"slot store {slots_path} has no slots")
        desired = args.label or active_label(active_path, args.default_label)
        if desired not in slots:
            raise SystemExit(f"unknown Codex slot {desired!r}; available labels: {', '.join(sorted(slots))}")
        stores: dict[str, tuple[Path, dict[str, Any]]] = {"root": (root_path, load_store(root_path))}
        for profile, path in profile_paths:
            stores[profile] = (path, load_store(path))
        root_store = stores["root"][1]

        if args.mode == "status":
            print_status(slots, desired, root_store, stores)
            return 0

        changed, cleaned = activate_slot(desired, slots[desired], root_store, stores)
        active_changed = active_label(active_path, args.default_label) != desired or not active_path.exists()
        if args.mode == "check":
            return 1 if changed or active_changed else 0

        if changed:
            write_store(root_path, root_store)
        if args.mode == "switch" or active_changed:
            set_active_label(active_path, desired)

    if changed or active_changed:
        parts = [f"activated {PROVIDER} slot {desired}"]
        if cleaned:
            parts.append("removed local shadow entries from " + ", ".join(sorted(cleaned)))
        print("; ".join(parts))
    else:
        print(f"{PROVIDER} slot {desired} is already active")
    if args.mode == "switch" and args.restart:
        run_restart(args.profiles)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
