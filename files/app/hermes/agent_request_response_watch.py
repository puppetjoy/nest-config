#!/usr/bin/env python3
"""Deliver completed agent-request responses to the requesting Hermes profile."""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TERMINAL_STATUSES = {"completed", "needs_info", "denied", "cancelled"}


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


def update_received_message(profile: str, request: dict[str, Any], update: dict[str, Any]) -> str:
    return "\n".join(
        [
            "📬 Agent update received",
            f"To: {profile}",
            f"ID: {request.get('id')}",
            f"Status: {request.get('status')}",
            f"Title: {request.get('title')}",
            f"From: {update.get('actor', 'unknown')}",
            f"Update: {update.get('action', request.get('status'))}",
            "",
            "Star is processing Talon's response and will follow up shortly.",
        ]
    )


def pending_items(state: dict[str, Any], profile: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for request in state.get("requests", []):
        if request.get("requester") != profile:
            continue
        if request.get("status") not in TERMINAL_STATUSES:
            continue
        update = request.get("latest_update") or {}
        response = str(update.get("response_to_requester") or "").strip()
        if not response:
            continue
        marker = f"{update.get('at')}:{update.get('action')}"
        if request.get("requester_response_delivered") == marker:
            continue
        items.append({"request": request, "update": update, "marker": marker, "response": response})
    return items


def run_profile_agent(profile: str, request: dict[str, Any], response: str) -> str:
    profile_home = hermes_root() / "profiles" / profile
    hermes_bin = os.environ.get("HERMES_BIN", "/opt/hermes-agent/venv/bin/hermes")
    env = os.environ.copy()
    env["HERMES_HOME"] = str(profile_home)
    env.setdefault("PYTHONPATH", "/opt/hermes-agent/src")
    prompt = textwrap.dedent(
        f"""
        You are {profile}. Talon completed an agent-request that you submitted.

        Request ID: {request.get('id')}
        Request title: {request.get('title')}
        Request status: {request.get('status')}

        Talon's response to you:
        {response}

        Continue the user-facing workflow now. Send Joy a concise, friendly
        message in your own voice. If the next step requires Joy to provide a
        file path, redirect URL, code, or other missing input, ask for exactly
        that. Do not claim you performed OAuth or Google Workspace access until
        you have verified it. Do not mention internal implementation details
        unless they help Joy understand what to do next.
        """
    ).strip()
    command = [
        hermes_bin,
        "--profile",
        profile,
        "--skills",
        "google-workspace",
        "--toolsets",
        "agent_requests,skills,web",
        "--oneshot",
        prompt,
    ]
    result = subprocess.run(
        command,
        env=env,
        cwd=f"/home/{os.environ.get('USER', 'joy')}",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=300,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Hermes oneshot failed rc={result.returncode}: {result.stderr[-1000:]}")
    output = result.stdout.strip()
    if not output:
        raise RuntimeError("Hermes oneshot produced no output")
    return output


def main(argv: list[str]) -> int:
    profile = argv[1] if len(argv) > 1 else os.environ.get("REQUESTER_PROFILE", "star")
    directory = store_dir()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = state_path()
    lock = lock_path()

    with lock.open("a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        state = load_state(path)
        items = pending_items(state, profile)
        fcntl.flock(lock_handle, fcntl.LOCK_UN)

    if not items:
        print(f"no undelivered responses for {profile}")
        return 0

    delivered: list[tuple[str, str, dict[str, Any]]] = []
    for item in items[:3]:
        request = item["request"]
        try:
            received = telegram_send(update_received_message(profile, request, item["update"]))
            if received.get("sent"):
                print(f"update_received_notified id={request.get('id')} telegram_sent=True")
            else:
                print(f"update_received_notify_failed id={request.get('id')} notification={received}", file=sys.stderr)

            message = run_profile_agent(profile, request, item["response"])
            notification = telegram_send(message)
            if not notification.get("sent"):
                raise RuntimeError(f"Telegram send failed: {notification}")
            delivered.append((request.get("id"), item["marker"], notification))
            print(f"delivered id={request.get('id')} telegram_sent=True")
        except Exception as exc:  # noqa: BLE001 - keep other responses deliverable
            print(f"delivery_failed id={request.get('id')} error={exc}", file=sys.stderr)

    if delivered:
        delivered_by_id = {request_id: marker for request_id, marker, _ in delivered}
        with lock.open("a+", encoding="utf-8") as lock_handle:
            fcntl.flock(lock_handle, fcntl.LOCK_EX)
            state = load_state(path)
            at = now()
            for request in state.get("requests", []):
                marker = delivered_by_id.get(request.get("id"))
                if not marker:
                    continue
                request["requester_response_delivered"] = marker
                request["requester_response_delivered_at"] = at
            save_state(path, state)
            fcntl.flock(lock_handle, fcntl.LOCK_UN)

    return 0 if len(delivered) == len(items[:3]) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
