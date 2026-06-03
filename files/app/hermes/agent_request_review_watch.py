#!/usr/bin/env python3
"""Run Talon on pending Hermes agent requests marked for review."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
import tempfile
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_REVIEWER = "talon"
DEFAULT_HERMES_BIN = "/opt/hermes-agent/venv/bin/hermes"
PROCESSABLE_STATUSES = {"reviewing"}


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


def event_marker(request: dict[str, Any]) -> str:
    update = request.get("latest_update") or {}
    return f"{request.get('updated_at')}:{update.get('at')}:{update.get('action')}"


def pending_items(state: dict[str, Any], reviewer: str, request_id: str | None = None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for request in state.get("requests", []):
        if request_id and request.get("id") != request_id:
            continue
        if request.get("status") not in PROCESSABLE_STATUSES:
            continue
        if request.get("reviewer", reviewer) != reviewer:
            continue
        marker = event_marker(request)
        if request.get("reviewer_agent_hold"):
            continue
        if request.get("reviewer_agent_processed") == marker:
            continue
        items.append({"request": request, "marker": marker})
    return items


def request_context(request: dict[str, Any]) -> str:
    public = {
        "id": request.get("id"),
        "requester": request.get("requester"),
        "title": request.get("title"),
        "urgency": request.get("urgency"),
        "status": request.get("status"),
        "submitted_at": request.get("submitted_at"),
        "updated_at": request.get("updated_at"),
        "request": request.get("request"),
        "context": request.get("context"),
        "latest_update": request.get("latest_update"),
    }
    return json.dumps(public, ensure_ascii=False, indent=2, sort_keys=True)


def run_reviewer_agent(reviewer: str, request: dict[str, Any]) -> str:
    profile_home = hermes_root() / "profiles" / reviewer
    hermes_bin = os.environ.get("HERMES_BIN", DEFAULT_HERMES_BIN)
    env = os.environ.copy()
    env["HERMES_HOME"] = str(profile_home)
    env.setdefault("PYTHONPATH", "/opt/hermes-agent/src")
    prompt = textwrap.dedent(
        f"""
        You are {reviewer}, Joy's Nest Ops reviewer for the local Hermes
        agent-request broker. A requesting assistant submitted a request and
        the deterministic watcher marked it for review.

        Request data:
        {request_context(request)}

        Begin work on this request now. Use the agent_request_update tool to
        move the request forward. If the work requires Joy's approval before
        setup or ops changes, update the request with status='proposed' and a
        concrete proposal. If the request is safe and already approved by its
        context, complete it with status='completed' and a response_to_requester.
        If required input is missing, use status='needs_info' and state exactly
        what is missing. If the request is unsafe or out of policy, deny it.

        Do not merely summarize the request. Do not send a separate Telegram
        message as the main result; broker updates are the control plane. Keep
        secrets out of the response. Verify concrete claims with tools where
        practical.
        """
    ).strip()
    command = [
        hermes_bin,
        "--profile",
        reviewer,
        "--toolsets",
        "agent_requests,terminal,file,web,skills",
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
        timeout=600,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Hermes reviewer oneshot failed rc={result.returncode}: {result.stderr[-1000:]}")
    output = result.stdout.strip()
    if not output:
        raise RuntimeError("Hermes reviewer oneshot produced no output")
    return output


def mark_processed(delivered: list[tuple[str, str]]) -> None:
    if not delivered:
        return
    delivered_by_id = {request_id: marker for request_id, marker in delivered}
    path = state_path()
    lock = lock_path()
    with lock.open("a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        state = load_state(path)
        at = now()
        for request in state.get("requests", []):
            marker = delivered_by_id.get(request.get("id"))
            if not marker:
                continue
            request["reviewer_agent_processed"] = marker
            request["reviewer_agent_processed_at"] = at
        save_state(path, state)
        fcntl.flock(lock_handle, fcntl.LOCK_UN)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reviewer", nargs="?", default=os.environ.get("REVIEWER_PROFILE", DEFAULT_REVIEWER))
    parser.add_argument("--request-id", help="Only process one request id")
    parser.add_argument("--dry-run", action="store_true", help="List work without running Talon")
    parser.add_argument("--limit", type=int, default=1, help="Maximum requests to run per invocation")
    return parser.parse_args(argv[1:])


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    directory = store_dir()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = state_path()
    lock = lock_path()

    with lock.open("a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        state = load_state(path)
        items = pending_items(state, args.reviewer, args.request_id)
        fcntl.flock(lock_handle, fcntl.LOCK_UN)

    if not items:
        target = f" id={args.request_id}" if args.request_id else ""
        print(f"no pending review requests for {args.reviewer}{target}")
        return 0

    if args.dry_run:
        for item in items[: args.limit]:
            request = item["request"]
            print(f"would_review id={request.get('id')} requester={request.get('requester')} title={request.get('title')!r}")
        return 0

    processed: list[tuple[str, str]] = []
    failures = 0
    for item in items[: args.limit]:
        request = item["request"]
        request_id = request.get("id")
        try:
            output = run_reviewer_agent(args.reviewer, request)
            processed.append((str(request_id), item["marker"]))
            print(f"reviewed id={request_id} output={output[-500:]}")
        except Exception as exc:  # noqa: BLE001 - leave marker unset so the request can retry
            failures += 1
            print(f"review_failed id={request_id} error={exc}", file=sys.stderr)

    mark_processed(processed)
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
