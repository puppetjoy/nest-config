"""Agent request broker tools for Joy's Hermes profiles.

This is a narrow, local control-plane for assistant-to-ops requests.  It lets
Star submit setup/install/help requests to Talon without giving Star operator
credentials, and lets Talon publish review/progress/outcome updates with a
Telegram audit trail.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hermes_constants import get_default_hermes_root, get_hermes_home
from tools.registry import registry

TOOLSET = "agent_requests"
MAX_TEXT = 12000
STATUS_VALUES = {
    "submitted",
    "reviewing",
    "proposed",
    "approved",
    "denied",
    "needs_info",
    "in_progress",
    "completed",
    "cancelled",
}
UPDATE_STATUS_VALUES = STATUS_VALUES - {"submitted"}
CHANGE_STATUSES = {"in_progress", "completed"}



def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _profile_name() -> str:
    home = get_hermes_home()
    if home.parent.name == "profiles":
        return home.name
    return "default"


def _store_dir() -> Path:
    return get_default_hermes_root() / "agent-requests"


def _state_path() -> Path:
    return _store_dir() / "requests.json"


def _lock_path() -> Path:
    return _store_dir() / ".requests.lock"


def _ensure_store() -> None:
    directory = _store_dir()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        directory.chmod(0o700)
    except OSError:
        pass


def _load_state() -> dict[str, Any]:
    path = _state_path()
    if not path.exists():
        return {"requests": []}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or not isinstance(data.get("requests"), list):
        raise ValueError(f"Invalid request broker state in {path}")
    return data


def _save_state(state: dict[str, Any]) -> None:
    path = _state_path()
    directory = path.parent
    fd, tmp_name = tempfile.mkstemp(prefix="requests.", suffix=".tmp", dir=directory)
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


class _LockedState:
    def __enter__(self) -> dict[str, Any]:
        _ensure_store()
        self._lock_handle = _lock_path().open("a+", encoding="utf-8")
        fcntl.flock(self._lock_handle, fcntl.LOCK_EX)
        self.state = _load_state()
        return self.state

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            _save_state(self.state)
        fcntl.flock(self._lock_handle, fcntl.LOCK_UN)
        self._lock_handle.close()


def _clean_text(value: Any, *, max_len: int = MAX_TEXT) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    if len(text) > max_len:
        return text[: max_len - 20] + "… [truncated]"
    return text


def _find_request(state: dict[str, Any], request_id: str) -> dict[str, Any] | None:
    for request in state.get("requests", []):
        if request.get("id") == request_id:
            return request
    return None


def _public_request(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": request.get("id"),
        "status": request.get("status"),
        "title": request.get("title"),
        "requester": request.get("requester"),
        "created_at": request.get("created_at"),
        "updated_at": request.get("updated_at"),
        "urgency": request.get("urgency"),
        "request": request.get("request"),
        "latest_update": request.get("latest_update", {}),
        "events": request.get("events", [])[-10:],
    }


def _telegram_send(message: str) -> dict[str, Any]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_HOME_CHANNEL", "").strip()
    if not token or not chat_id:
        return {"sent": False, "reason": "TELEGRAM_BOT_TOKEN or TELEGRAM_HOME_CHANNEL is not configured"}

    data = urllib.parse.urlencode({"chat_id": chat_id, "text": message[:3900]}).encode()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    request = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return {"sent": bool(payload.get("ok")), "ok": payload.get("ok")}
    except Exception as exc:  # noqa: BLE001 - tool result should report best-effort notification failures
        return {"sent": False, "reason": str(exc)}


def _notify_submission(request: dict[str, Any]) -> dict[str, Any]:
    requester = request.get("requester", "unknown")
    message = (
        "🦋 Agent request submitted\n"
        f"From: {requester}\n"
        f"ID: {request.get('id')}\n"
        f"Urgency: {request.get('urgency')}\n"
        f"Title: {request.get('title')}\n\n"
        "Talon should review this request, propose a Puppet/source-of-truth "
        "solution to Joy, and update the request with the outcome."
    )
    return _telegram_send(message)


def _request_has_joy_approval(request: dict[str, Any]) -> bool:
    if request.get("joy_approved_at"):
        return True
    for event in request.get("events", []):
        if event.get("joy_approval") or event.get("joy_steering"):
            return True
    return False


def _notify_update(request: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    parts = [
        "🦉 Agent request update",
        f"ID: {request.get('id')}",
        f"Status: {request.get('status')}",
        f"Title: {request.get('title')}",
        f"By: {event.get('actor')}",
        "",
        event.get("summary", ""),
    ]
    if event.get("proposal"):
        parts.extend(["", "Proposal:", event["proposal"]])
    if event.get("joy_approval"):
        parts.extend(["", "Joy approval:", event["joy_approval"]])
    if event.get("joy_steering"):
        parts.extend(["", "Joy steering:", event["joy_steering"]])
    if event.get("response_to_requester"):
        parts.extend(["", "Response to requester:", event["response_to_requester"]])
    message = "\n".join(part for part in parts if part is not None)
    return _telegram_send(message)


def agent_request_submit_tool(args: dict[str, Any], **_kw) -> str:
    title = _clean_text(args.get("title"), max_len=200)
    request_text = _clean_text(args.get("request"))
    urgency = _clean_text(args.get("urgency") or "normal", max_len=40).lower()
    context = _clean_text(args.get("context"), max_len=4000)

    if not title or not request_text:
        return json.dumps({"error": "Both title and request are required"})
    if urgency not in {"low", "normal", "high", "urgent"}:
        return json.dumps({"error": "urgency must be one of: low, normal, high, urgent"})

    request_id = f"ar-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}"
    created_at = _now()
    event = {
        "at": created_at,
        "actor": _profile_name(),
        "action": "submitted",
        "summary": "Request submitted for Talon review",
    }
    request = {
        "id": request_id,
        "status": "submitted",
        "title": title,
        "request": request_text,
        "context": context,
        "urgency": urgency,
        "requester": _profile_name(),
        "created_at": created_at,
        "updated_at": created_at,
        "latest_update": event,
        "events": [event],
    }

    with _LockedState() as state:
        state.setdefault("requests", []).append(request)

    notification = _notify_submission(request)
    return json.dumps({"request": _public_request(request), "telegram": notification}, ensure_ascii=False)


def agent_request_status_tool(args: dict[str, Any], **_kw) -> str:
    request_id = _clean_text(args.get("request_id"), max_len=80)
    limit = int(args.get("limit") or 5)
    limit = min(max(limit, 1), 25)
    status_filter = _clean_text(args.get("status"), max_len=40).lower()

    state = _load_state() if _state_path().exists() else {"requests": []}
    requests = list(state.get("requests", []))
    if request_id:
        request = _find_request(state, request_id)
        if not request:
            return json.dumps({"error": f"No request found with id {request_id}"})
        return json.dumps({"request": _public_request(request)}, ensure_ascii=False)

    if status_filter:
        if status_filter not in STATUS_VALUES:
            return json.dumps({"error": f"Unknown status: {status_filter}"})
        requests = [request for request in requests if request.get("status") == status_filter]

    requests = sorted(requests, key=lambda request: request.get("updated_at", ""), reverse=True)[:limit]
    return json.dumps({"requests": [_public_request(request) for request in requests]}, ensure_ascii=False)


def _require_talon() -> str | None:
    if _profile_name() != "talon":
        return "Only Talon may update agent requests. Other profiles can submit requests and check status."
    return None


def agent_request_update_tool(args: dict[str, Any], **_kw) -> str:
    role_error = _require_talon()
    if role_error:
        return json.dumps({"error": role_error})

    request_id = _clean_text(args.get("request_id"), max_len=80)
    status = _clean_text(args.get("status"), max_len=40).lower()
    summary = _clean_text(args.get("summary"), max_len=4000)
    proposal = _clean_text(args.get("proposal"), max_len=8000)
    response_to_requester = _clean_text(args.get("response_to_requester"), max_len=8000)
    joy_approval = _clean_text(args.get("joy_approval"), max_len=4000)
    joy_steering = _clean_text(args.get("joy_steering"), max_len=8000)

    if not request_id or not status or not summary:
        return json.dumps({"error": "request_id, status, and summary are required"})
    if status not in UPDATE_STATUS_VALUES:
        return json.dumps({"error": f"status must be one of: {', '.join(sorted(UPDATE_STATUS_VALUES))}"})

    at = _now()
    with _LockedState() as state:
        request = _find_request(state, request_id)
        if not request:
            return json.dumps({"error": f"No request found with id {request_id}"})
        if status == "approved":
            if request.get("status") != "proposed":
                return json.dumps({"error": "Requests must be in proposed status before Joy can approve them"})
            if not joy_approval and not joy_steering:
                return json.dumps({"error": "status=approved requires joy_approval and/or joy_steering documenting Joy's decision"})
        if status in CHANGE_STATUSES and not _request_has_joy_approval(request):
            return json.dumps({"error": "Joy approval is required before marking a request in_progress or completed; use status=proposed first, then status=approved with joy_approval/joy_steering"})
        event = {
            "at": at,
            "actor": _profile_name(),
            "action": status,
            "summary": summary,
        }
        if proposal:
            event["proposal"] = proposal
        if joy_approval:
            event["joy_approval"] = joy_approval
        if joy_steering:
            event["joy_steering"] = joy_steering
        if response_to_requester:
            event["response_to_requester"] = response_to_requester
        if status == "approved":
            request["joy_approved_at"] = at
            request["joy_approval"] = joy_approval
            request["joy_steering"] = joy_steering
        request["status"] = status
        request["updated_at"] = at
        request["latest_update"] = event
        request.setdefault("events", []).append(event)
        public = _public_request(request)

    notification = _notify_update(request, event)
    return json.dumps({"request": public, "telegram": notification}, ensure_ascii=False)


SUBMIT_SCHEMA = {
    "name": "agent_request_submit",
    "description": (
        "Submit a request from an assistant profile to Talon for ops/setup/install review. "
        "Use this instead of giving a narrow assistant broad operator credentials."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Short title for the request"},
            "request": {"type": "string", "description": "What the assistant needs and why"},
            "context": {"type": "string", "description": "Optional context, constraints, or attempted steps"},
            "urgency": {"type": "string", "enum": ["low", "normal", "high", "urgent"], "description": "Request urgency"},
        },
        "required": ["title", "request"],
    },
}

STATUS_SCHEMA = {
    "name": "agent_request_status",
    "description": "Check one request by id, or list recent agent requests and their latest updates.",
    "parameters": {
        "type": "object",
        "properties": {
            "request_id": {"type": "string", "description": "Specific request id to inspect"},
            "status": {"type": "string", "enum": sorted(STATUS_VALUES), "description": "Optional status filter for listing"},
            "limit": {"type": "integer", "description": "Maximum recent requests to return, 1-25"},
        },
        "required": [],
    },
}

UPDATE_SCHEMA = {
    "name": "agent_request_update",
    "description": (
        "Talon-only: update an agent request after review, approval, implementation, or denial. "
        "Use status='proposed' with proposal text when asking Joy to approve a plan. "
        "Use status='approved' only after Joy approves or steers the proposal, and include joy_approval/joy_steering."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "request_id": {"type": "string", "description": "Request id to update"},
            "status": {"type": "string", "enum": sorted(UPDATE_STATUS_VALUES), "description": "New request status"},
            "summary": {"type": "string", "description": "Concise human-readable update"},
            "proposal": {"type": "string", "description": "Optional proposed solution for Joy approval"},
            "joy_approval": {"type": "string", "description": "Joy's explicit approval text for status=approved"},
            "joy_steering": {"type": "string", "description": "Joy's steering, constraints, or modifications to an approved proposal"},
            "response_to_requester": {"type": "string", "description": "Optional message/result intended for the requesting assistant"},
        },
        "required": ["request_id", "status", "summary"],
    },
}

registry.register(
    name="agent_request_submit",
    toolset=TOOLSET,
    schema=SUBMIT_SCHEMA,
    handler=agent_request_submit_tool,
    description=SUBMIT_SCHEMA["description"],
    emoji="🦋",
)
registry.register(
    name="agent_request_status",
    toolset=TOOLSET,
    schema=STATUS_SCHEMA,
    handler=agent_request_status_tool,
    description=STATUS_SCHEMA["description"],
    emoji="📬",
)
registry.register(
    name="agent_request_update",
    toolset=TOOLSET,
    schema=UPDATE_SCHEMA,
    handler=agent_request_update_tool,
    description=UPDATE_SCHEMA["description"],
    emoji="🦉",
)
