#!/usr/bin/env python3
"""Watch Joy's local Hermes agent-request broker for new submissions."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def hermes_root() -> Path:
    configured = Path(os.environ.get("HERMES_HOME", "/home/joy/.hermes")).expanduser()
    if configured.parent.name == "profiles":
        return configured.parent.parent
    return configured


def store_dir() -> Path:
    return hermes_root() / "agent-requests"


def state_path() -> Path:
    return store_dir() / "requests.json"


def lock_path() -> Path:
    return store_dir() / ".requests.lock"


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"requests": []}
    with path.open("r", encoding="utf-8") as handle:
        state = json.load(handle)
    if not isinstance(state, dict) or not isinstance(state.get("requests"), list):
        raise ValueError(f"Invalid agent request state in {path}")
    return state


def save_state(path: Path, state: dict[str, Any]) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix="requests.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def telegram_send(message: str) -> dict[str, Any]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_HOME_CHANNEL", "").strip()
    if not token or not chat_id:
        return {"sent": False, "reason": "missing Telegram token or home channel"}

    data = urllib.parse.urlencode({"chat_id": chat_id, "text": message[:3900]}).encode()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    request = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return {"sent": bool(payload.get("ok")), "ok": payload.get("ok")}
    except Exception as exc:  # noqa: BLE001 - report best-effort notification failure
        return {"sent": False, "reason": str(exc)}


def notify(request: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    message = (
        "🦉 Talon picked up an agent request\n"
        f"ID: {request.get('id')}\n"
        f"From: {request.get('requester', 'unknown')}\n"
        f"Urgency: {request.get('urgency', 'normal')}\n"
        f"Title: {request.get('title')}\n\n"
        f"{event['summary']}"
    )
    return telegram_send(message)


def main() -> int:
    directory = store_dir()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = state_path()
    lock = lock_path()

    picked_up: list[dict[str, Any]] = []
    with lock.open("a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        state = load_state(path)
        for request in state.get("requests", []):
            if request.get("status") != "submitted":
                continue
            at = now()
            event = {
                "at": at,
                "actor": "talon",
                "action": "reviewing",
                "summary": (
                    "Talon's watcher noticed this submitted request and marked it for review. "
                    "Talon will propose a plan to Joy before making setup or ops changes."
                ),
            }
            request["status"] = "reviewing"
            request["updated_at"] = at
            request["latest_update"] = event
            request.setdefault("events", []).append(event)
            picked_up.append({"request": request, "event": event})
        if picked_up:
            save_state(path, state)
        fcntl.flock(lock_handle, fcntl.LOCK_UN)

    for item in picked_up:
        result = notify(item["request"], item["event"])
        print(
            f"picked_up id={item['request'].get('id')} "
            f"telegram_sent={result.get('sent')}"
        )
    if not picked_up:
        print("no submitted agent requests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
