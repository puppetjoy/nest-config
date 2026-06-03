"""Narrow Google Workspace tools for Joy's Hermes profiles.

This exposes profile-scoped Google read/search operations without granting a
personal-assistant profile the general terminal tool.  It intentionally wraps
only the read-only subset Joy approved for Star's initial Google Workspace
integration.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from hermes_constants import get_hermes_home
from tools.registry import registry

TOOLSET = "google_workspace"
MAX_RESULT_CHARS = 24000
MAX_GMAIL_RESULTS = 20
MAX_CALENDAR_RESULTS = 50


def _hermes_home() -> Path:
    return get_hermes_home()


def _script_path(script: str) -> Path:
    return _hermes_home() / "skills" / "productivity" / "google-workspace" / "scripts" / script


def _token_path() -> Path:
    return _hermes_home() / "google_token.json"


def _client_secret_path() -> Path:
    return _hermes_home() / "google_client_secret.json"


def _check_google_workspace() -> bool:
    return _script_path("google_api.py").exists() and _token_path().exists()


def _run_google_api(parts: list[str]) -> dict[str, Any] | list[Any] | str:
    script = _script_path("google_api.py")
    if not script.exists():
        return {
            "error": "google-workspace skill script is not installed for this profile",
            "script": str(script),
        }
    if not _token_path().exists():
        return {
            "error": "NOT_AUTHENTICATED",
            "message": "Ask Talon through agent_requests to complete profile-scoped Google OAuth setup.",
            "token_path": str(_token_path()),
        }

    env = os.environ.copy()
    env["HERMES_HOME"] = str(_hermes_home())
    result = subprocess.run(
        ["/opt/hermes-agent/venv/bin/python", str(script), *parts],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        check=False,
    )
    if result.returncode != 0:
        return {
            "error": "GOOGLE_API_FAILED",
            "exit_code": result.returncode,
            "stderr": result.stderr.strip()[:4000],
            "stdout": result.stdout.strip()[:4000],
        }

    stdout = result.stdout.strip()
    if len(stdout) > MAX_RESULT_CHARS:
        stdout = stdout[:MAX_RESULT_CHARS] + "… [truncated]"
    if not stdout:
        return {}
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return stdout


def _decode_body_data(data: str) -> str:
    return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")


def _extract_recursive_body(payload: dict[str, Any]) -> tuple[str, str]:
    """Return body text from nested Gmail MIME payloads.

    Gmail messages often nest the useful text/plain or text/html part inside
    multipart/alternative under multipart/related. The bundled skill extractor
    currently checks only one level, so keep the Star tool robust here without
    broadening Star's tool access.
    """
    text_plain: list[str] = []
    text_html: list[str] = []

    def walk(part: dict[str, Any]) -> None:
        mime_type = str(part.get("mimeType") or "").lower()
        body = part.get("body") or {}
        data = body.get("data")
        if data and mime_type == "text/plain":
            text_plain.append(_decode_body_data(data))
        elif data and mime_type == "text/html":
            text_html.append(_decode_body_data(data))
        for child in part.get("parts") or []:
            walk(child)

    walk(payload)
    if text_plain:
        return "\n".join(text_plain), "text/plain"
    if text_html:
        return "\n".join(text_html), "text/html"
    return "", ""


def _headers_dict(msg: dict[str, Any]) -> dict[str, str]:
    return {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}


def _gmail_get_recursive(message_id: str) -> dict[str, Any]:
    script_dir = _script_path("google_api.py").parent
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    import google_api  # type: ignore[import-not-found]

    service = google_api.build_service("gmail", "v1")
    msg = service.users().messages().get(userId="me", id=message_id, format="full").execute()
    headers = _headers_dict(msg)
    body, body_mime_type = _extract_recursive_body(msg.get("payload") or {})
    return {
        "id": msg["id"],
        "threadId": msg["threadId"],
        "from": headers.get("From", ""),
        "to": headers.get("To", ""),
        "subject": headers.get("Subject", ""),
        "date": headers.get("Date", ""),
        "labels": msg.get("labelIds", []),
        "body": body,
        "body_mime_type": body_mime_type,
    }


def google_workspace_status_tool(args: dict[str, Any], **_kw) -> str:
    setup = _script_path("setup.py")
    status: dict[str, Any] = {
        "hermes_home": str(_hermes_home()),
        "token_path": str(_token_path()),
        "token_exists": _token_path().exists(),
        "client_secret_path": str(_client_secret_path()),
        "client_secret_exists": _client_secret_path().exists(),
        "skill_installed": setup.exists(),
    }
    if setup.exists():
        env = os.environ.copy()
        env["HERMES_HOME"] = str(_hermes_home())
        result = subprocess.run(
            ["/opt/hermes-agent/venv/bin/python", str(setup), "--check"],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
            check=False,
        )
        status.update(
            {
                "check_exit_code": result.returncode,
                "check_stdout": result.stdout.strip()[:4000],
                "check_stderr": result.stderr.strip()[:4000],
            }
        )
    return json.dumps(status, ensure_ascii=False)


def google_workspace_gmail_search_tool(args: dict[str, Any], **_kw) -> str:
    query = str(args.get("query") or "").strip()
    if not query:
        return json.dumps({"error": "query is required"})
    max_results = int(args.get("max_results") or 10)
    max_results = max(1, min(max_results, MAX_GMAIL_RESULTS))
    result = _run_google_api(["gmail", "search", query, "--max", str(max_results)])
    return json.dumps(result, ensure_ascii=False)


def google_workspace_gmail_get_tool(args: dict[str, Any], **_kw) -> str:
    message_id = str(args.get("message_id") or "").strip()
    if not message_id:
        return json.dumps({"error": "message_id is required"})
    try:
        result = _gmail_get_recursive(message_id)
    except Exception as exc:
        result = {"error": "GMAIL_GET_FAILED", "message": str(exc)}
    return json.dumps(result, ensure_ascii=False)


def google_workspace_gmail_labels_tool(args: dict[str, Any], **_kw) -> str:
    result = _run_google_api(["gmail", "labels"])
    return json.dumps(result, ensure_ascii=False)


def google_workspace_calendar_list_tool(args: dict[str, Any], **_kw) -> str:
    parts = ["calendar", "list"]
    start = str(args.get("start") or "").strip()
    end = str(args.get("end") or "").strip()
    calendar = str(args.get("calendar") or "primary").strip() or "primary"
    max_results = int(args.get("max_results") or 10)
    max_results = max(1, min(max_results, MAX_CALENDAR_RESULTS))
    if start:
        parts.extend(["--start", start])
    if end:
        parts.extend(["--end", end])
    parts.extend(["--calendar", calendar, "--max", str(max_results)])
    result = _run_google_api(parts)
    return json.dumps(result, ensure_ascii=False)


STATUS_SCHEMA = {
    "name": "google_workspace_status",
    "description": "Check profile-scoped Google Workspace OAuth status without shell access.",
    "parameters": {"type": "object", "properties": {}, "required": []},
}

GMAIL_SEARCH_SCHEMA = {
    "name": "google_workspace_gmail_search",
    "description": "Search Joy's Gmail using Gmail search syntax. Read-only; returns message metadata/snippets.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Gmail search query, e.g. newer_than:7d is:unread"},
            "max_results": {"type": "integer", "description": f"Maximum messages to return, 1-{MAX_GMAIL_RESULTS}"},
        },
        "required": ["query"],
    },
}

GMAIL_GET_SCHEMA = {
    "name": "google_workspace_gmail_get",
    "description": "Read a Gmail message by id. Read-only; returns headers, labels, and body text.",
    "parameters": {
        "type": "object",
        "properties": {
            "message_id": {"type": "string", "description": "Gmail message id returned by google_workspace_gmail_search"},
        },
        "required": ["message_id"],
    },
}

GMAIL_LABELS_SCHEMA = {
    "name": "google_workspace_gmail_labels",
    "description": "List Gmail labels. Read-only.",
    "parameters": {"type": "object", "properties": {}, "required": []},
}

CALENDAR_LIST_SCHEMA = {
    "name": "google_workspace_calendar_list",
    "description": "List Google Calendar events. Read-only; defaults to the next seven days.",
    "parameters": {
        "type": "object",
        "properties": {
            "start": {"type": "string", "description": "Optional ISO 8601 start time/date"},
            "end": {"type": "string", "description": "Optional ISO 8601 end time/date"},
            "calendar": {"type": "string", "description": "Calendar id; defaults to primary"},
            "max_results": {"type": "integer", "description": f"Maximum events to return, 1-{MAX_CALENDAR_RESULTS}"},
        },
        "required": [],
    },
}

registry.register(
    name=STATUS_SCHEMA["name"],
    toolset=TOOLSET,
    schema=STATUS_SCHEMA,
    handler=google_workspace_status_tool,
    check_fn=_check_google_workspace,
    description=STATUS_SCHEMA["description"],
    emoji="🔐",
    max_result_size_chars=MAX_RESULT_CHARS,
)
registry.register(
    name=GMAIL_SEARCH_SCHEMA["name"],
    toolset=TOOLSET,
    schema=GMAIL_SEARCH_SCHEMA,
    handler=google_workspace_gmail_search_tool,
    check_fn=_check_google_workspace,
    description=GMAIL_SEARCH_SCHEMA["description"],
    emoji="📧",
    max_result_size_chars=MAX_RESULT_CHARS,
)
registry.register(
    name=GMAIL_GET_SCHEMA["name"],
    toolset=TOOLSET,
    schema=GMAIL_GET_SCHEMA,
    handler=google_workspace_gmail_get_tool,
    check_fn=_check_google_workspace,
    description=GMAIL_GET_SCHEMA["description"],
    emoji="✉️",
    max_result_size_chars=MAX_RESULT_CHARS,
)
registry.register(
    name=GMAIL_LABELS_SCHEMA["name"],
    toolset=TOOLSET,
    schema=GMAIL_LABELS_SCHEMA,
    handler=google_workspace_gmail_labels_tool,
    check_fn=_check_google_workspace,
    description=GMAIL_LABELS_SCHEMA["description"],
    emoji="🏷️",
    max_result_size_chars=MAX_RESULT_CHARS,
)
registry.register(
    name=CALENDAR_LIST_SCHEMA["name"],
    toolset=TOOLSET,
    schema=CALENDAR_LIST_SCHEMA,
    handler=google_workspace_calendar_list_tool,
    check_fn=_check_google_workspace,
    description=CALENDAR_LIST_SCHEMA["description"],
    emoji="📅",
    max_result_size_chars=MAX_RESULT_CHARS,
)
