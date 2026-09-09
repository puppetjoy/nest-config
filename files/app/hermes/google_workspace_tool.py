"""Profile-scoped Google Workspace tools for Joy's Hermes profiles.

This exposes selected profile-scoped Google Workspace operations without
requiring a personal-assistant profile to have the general terminal tool.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
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
MAX_GMAIL_ATTACHMENT_BYTES = 20 * 1024 * 1024
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
SAFE_GMAIL_ATTACHMENT_MIME_TYPES = frozenset(
    {
        "application/json",
        "application/msword",
        "application/pdf",
        "application/rtf",
        "application/vnd.ms-excel",
        "application/vnd.ms-powerpoint",
        "application/xml",
    }
)
SAFE_GMAIL_ATTACHMENT_MIME_PREFIXES = (
    "image/",
    "text/",
    "application/vnd.oasis.opendocument.",
    "application/vnd.openxmlformats-officedocument.",
)


def _hermes_home() -> Path:
    return get_hermes_home()


def _script_path(script: str) -> Path:
    return _hermes_home() / "skills" / "productivity" / "google-workspace" / "scripts" / script


def _token_path() -> Path:
    return _hermes_home() / "google_token.json"


def _client_secret_path() -> Path:
    return _hermes_home() / "google_client_secret.json"


def _stored_token_scopes() -> list[str]:
    try:
        payload = json.loads(_token_path().read_text())
    except Exception:
        return []
    raw = payload.get("scopes") or payload.get("scope") or []
    if isinstance(raw, str):
        return [scope for scope in raw.split() if scope]
    if isinstance(raw, list):
        return [str(scope) for scope in raw if str(scope)]
    return []


def _has_scope(scope: str) -> bool:
    return scope in set(_stored_token_scopes())


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
    # The upstream google_api.py prefers the `gws` CLI when it is on PATH, but
    # the packaged CLI uses its own keyring-backed credential store rather than
    # Star's profile-scoped google_token.json.  Keep this Hermes tool on the
    # profile-scoped Python client path so reads and sends use the OAuth token
    # Joy granted to Star, not an unrelated/stale gws keyring entry.
    env["PATH"] = "/opt/hermes-agent/venv/bin:/usr/bin:/bin"
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


def _decode_base64url_bytes(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _decode_body_data(data: str) -> str:
    return _decode_base64url_bytes(data).decode("utf-8", errors="replace")


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


def _gmail_service():
    script_dir = _script_path("google_api.py").parent
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    import google_api  # type: ignore[import-not-found]

    return google_api.build_service("gmail", "v1")


def _gmail_message(service, message_id: str) -> dict[str, Any]:
    return service.users().messages().get(userId="me", id=message_id, format="full").execute()


def _attachment_metadata(payload: dict[str, Any]) -> list[dict[str, Any]]:
    attachments: list[dict[str, Any]] = []

    def walk(part: dict[str, Any]) -> None:
        body = part.get("body") or {}
        attachment_id = str(body.get("attachmentId") or "")
        if attachment_id:
            attachments.append(
                {
                    "attachment_id": attachment_id,
                    "part_id": str(part.get("partId") or ""),
                    "filename": str(part.get("filename") or ""),
                    "mime_type": str(part.get("mimeType") or "application/octet-stream").lower(),
                    "size": int(body.get("size") or 0),
                }
            )
        for child in part.get("parts") or []:
            walk(child)

    walk(payload)
    return attachments


def _gmail_attachments(message_id: str):
    service = _gmail_service()
    msg = _gmail_message(service, message_id)
    return service, _attachment_metadata(msg.get("payload") or {})


def _safe_attachment_mime_type(mime_type: str, filename: str) -> bool:
    normalized = mime_type.lower().split(";", 1)[0].strip()
    if normalized == "application/octet-stream":
        return Path(filename).suffix.lower() == ".pdf"
    return normalized in SAFE_GMAIL_ATTACHMENT_MIME_TYPES or normalized.startswith(SAFE_GMAIL_ATTACHMENT_MIME_PREFIXES)


def _attachment_content_matches_metadata(content: bytes, mime_type: str, filename: str) -> bool:
    normalized = mime_type.lower().split(";", 1)[0].strip()
    if normalized == "application/pdf" or (normalized == "application/octet-stream" and Path(filename).suffix.lower() == ".pdf"):
        return b"%PDF-" in content[:1024]
    return True


def _download_filename(filename: str, mime_type: str, attachment_id: str) -> str:
    basename = Path(filename.replace("\\", "/")).name
    basename = re.sub(r"[\x00-\x1f\x7f/\\]", "_", basename).strip(" .")
    if not basename:
        basename = "attachment.pdf" if mime_type == "application/pdf" else "attachment.bin"
    suffix = Path(basename).suffix[:20]
    stem = Path(basename).stem[:140] or "attachment"
    digest = hashlib.sha256(attachment_id.encode("utf-8")).hexdigest()[:12]
    return f"{stem}--{digest}{suffix}"


def _attachment_download_path(message_id: str, filename: str, mime_type: str, attachment_id: str) -> Path:
    root = _hermes_home() / "downloads" / "google-workspace" / "gmail"
    message_dir = root / message_id
    message_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    os.chmod(message_dir, 0o700)
    return message_dir / _download_filename(filename, mime_type, attachment_id)


def _write_private_file(path: Path, content: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(content)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    os.chmod(path, 0o600)


def _gmail_get_recursive(message_id: str) -> dict[str, Any]:
    service = _gmail_service()
    msg = _gmail_message(service, message_id)
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


def google_workspace_gmail_attachments_tool(args: dict[str, Any], **_kw) -> str:
    """List attachment metadata for one Gmail message using read-only API calls."""
    message_id = str(args.get("message_id") or "").strip()
    if not message_id:
        return json.dumps({"error": "message_id is required"})
    try:
        _service, attachments = _gmail_attachments(message_id)
        result = {
            "message_id": message_id,
            "attachments": attachments,
            "attachment_count": len(attachments),
            "read_only": True,
        }
    except Exception:
        result = {"error": "GMAIL_ATTACHMENTS_FAILED", "message": "Gmail attachment metadata retrieval failed."}
    return json.dumps(result, ensure_ascii=False)


def google_workspace_gmail_attachment_download_tool(args: dict[str, Any], **_kw) -> str:
    """Download one explicitly selected safe Gmail attachment into the profile."""
    message_id = str(args.get("message_id") or "").strip()
    part_id = str(args.get("part_id") or "").strip()
    missing = [name for name, value in (("message_id", message_id), ("part_id", part_id)) if not value]
    if missing:
        return json.dumps({"error": "missing_required_fields", "fields": missing})
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", message_id):
        return json.dumps({"error": "INVALID_MESSAGE_ID"})
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", part_id):
        return json.dumps({"error": "INVALID_PART_ID"})

    try:
        service, attachments = _gmail_attachments(message_id)
        metadata = next((item for item in attachments if item["part_id"] == part_id), None)
        if metadata is None:
            return json.dumps({"error": "ATTACHMENT_NOT_FOUND", "message_id": message_id})
        attachment_id = metadata["attachment_id"]
        if metadata["size"] > MAX_GMAIL_ATTACHMENT_BYTES:
            return json.dumps(
                {
                    "error": "ATTACHMENT_TOO_LARGE",
                    "message_id": message_id,
                    "attachment_id": attachment_id,
                    "size": metadata["size"],
                    "max_size": MAX_GMAIL_ATTACHMENT_BYTES,
                }
            )
        if not _safe_attachment_mime_type(metadata["mime_type"], metadata["filename"]):
            return json.dumps(
                {
                    "error": "UNSUPPORTED_ATTACHMENT_MIME_TYPE",
                    "message_id": message_id,
                    "attachment_id": attachment_id,
                    "mime_type": metadata["mime_type"],
                }
            )

        attachment = (
            service.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=message_id, id=attachment_id)
            .execute()
        )
        data = str(attachment.get("data") or "")
        if not data:
            return json.dumps({"error": "ATTACHMENT_DATA_MISSING", "message_id": message_id})
        content = _decode_base64url_bytes(data)
        if len(content) > MAX_GMAIL_ATTACHMENT_BYTES:
            return json.dumps(
                {
                    "error": "ATTACHMENT_TOO_LARGE",
                    "message_id": message_id,
                    "attachment_id": attachment_id,
                    "size": len(content),
                    "max_size": MAX_GMAIL_ATTACHMENT_BYTES,
                }
            )
        if not _attachment_content_matches_metadata(content, metadata["mime_type"], metadata["filename"]):
            return json.dumps(
                {
                    "error": "ATTACHMENT_CONTENT_MISMATCH",
                    "message_id": message_id,
                    "attachment_id": attachment_id,
                    "mime_type": metadata["mime_type"],
                    "filename": metadata["filename"],
                }
            )

        path = _attachment_download_path(
            message_id,
            metadata["filename"],
            metadata["mime_type"],
            f"{message_id}:{part_id}",
        )
        _write_private_file(path, content)
        result = {
            "message_id": message_id,
            "attachment_id": attachment_id,
            "part_id": part_id,
            "filename": metadata["filename"],
            "mime_type": metadata["mime_type"],
            "size": len(content),
            "path": str(path),
            "read_only": True,
        }
    except Exception:
        result = {"error": "GMAIL_ATTACHMENT_DOWNLOAD_FAILED", "message": "Gmail attachment download failed."}
    return json.dumps(result, ensure_ascii=False)


def google_workspace_gmail_labels_tool(args: dict[str, Any], **_kw) -> str:
    result = _run_google_api(["gmail", "labels"])
    return json.dumps(result, ensure_ascii=False)


def google_workspace_gmail_send_tool(args: dict[str, Any], **_kw) -> str:
    """Send a Gmail message through the profile-scoped OAuth token."""
    to = str(args.get("to") or "").strip()
    subject = str(args.get("subject") or "").strip()
    body = str(args.get("body") or "")
    cc = str(args.get("cc") or "").strip()
    from_header = str(args.get("from_header") or "").strip()
    html = bool(args.get("html") or False)
    thread_id = str(args.get("thread_id") or "").strip()

    missing = [name for name, value in [("to", to), ("subject", subject), ("body", body)] if not value]
    if missing:
        return json.dumps({"error": "missing_required_fields", "fields": missing}, ensure_ascii=False)

    if not _token_path().exists():
        return json.dumps(
            {
                "error": "NOT_AUTHENTICATED",
                "message": "Star's profile-scoped Google token is missing; ask Talon to complete OAuth setup.",
                "token_path": str(_token_path()),
            },
            ensure_ascii=False,
        )

    if not _has_scope(GMAIL_SEND_SCOPE):
        return json.dumps(
            {
                "error": "MISSING_SCOPE",
                "required_scope": GMAIL_SEND_SCOPE,
                "message": "Star must be reauthorized by Joy with gmail.send before Gmail send can run.",
            },
            ensure_ascii=False,
        )

    parts = ["gmail", "send", "--to", to, "--subject", subject, "--body", body]
    if cc:
        parts.extend(["--cc", cc])
    if from_header:
        parts.extend(["--from", from_header])
    if html:
        parts.append("--html")
    if thread_id:
        parts.extend(["--thread-id", thread_id])
    result = _run_google_api(parts)
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

GMAIL_ATTACHMENTS_SCHEMA = {
    "name": "google_workspace_gmail_attachments",
    "description": "List attachment metadata for a Gmail message. Read-only; returns attachment id, stable part id, filename, MIME type, and size without downloading content. Select an item and pass its part_id to google_workspace_gmail_attachment_download.",
    "parameters": {
        "type": "object",
        "properties": {
            "message_id": {"type": "string", "description": "Gmail message id returned by google_workspace_gmail_search"},
        },
        "required": ["message_id"],
    },
}

GMAIL_ATTACHMENT_DOWNLOAD_SCHEMA = {
    "name": "google_workspace_gmail_attachment_download",
    "description": "Download one explicitly selected Gmail attachment into the profile's private downloads directory for file/PDF analysis. Read-only Gmail access; allows common document, text, and image MIME types up to 20 MiB. First call google_workspace_gmail_attachments and pass its stable part_id (Gmail attachment_id values may rotate between reads).",
    "parameters": {
        "type": "object",
        "properties": {
            "message_id": {"type": "string", "description": "Gmail message id returned by google_workspace_gmail_search"},
            "part_id": {"type": "string", "description": "Stable MIME part id returned by google_workspace_gmail_attachments"},
        },
        "required": ["message_id", "part_id"],
    },
}

GMAIL_LABELS_SCHEMA = {
    "name": "google_workspace_gmail_labels",
    "description": "List Gmail labels. Read-only.",
    "parameters": {"type": "object", "properties": {}, "required": []},
}

GMAIL_SEND_SCHEMA = {
    "name": "google_workspace_gmail_send",
    "description": "Send a Gmail message from Joy's profile-scoped Google account using Star's Google Workspace OAuth token.",
    "parameters": {
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "Recipient email address"},
            "subject": {"type": "string", "description": "Email subject"},
            "body": {"type": "string", "description": "Email body"},
            "cc": {"type": "string", "description": "Optional comma-separated Cc recipients"},
            "from_header": {"type": "string", "description": "Optional From header/display name"},
            "html": {"type": "boolean", "description": "Treat body as HTML"},
            "thread_id": {"type": "string", "description": "Optional Gmail threadId for threading the sent message"},
        },
        "required": ["to", "subject", "body"],
    },
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
    name=GMAIL_ATTACHMENTS_SCHEMA["name"],
    toolset=TOOLSET,
    schema=GMAIL_ATTACHMENTS_SCHEMA,
    handler=google_workspace_gmail_attachments_tool,
    check_fn=_check_google_workspace,
    description=GMAIL_ATTACHMENTS_SCHEMA["description"],
    emoji="📎",
    max_result_size_chars=MAX_RESULT_CHARS,
)
registry.register(
    name=GMAIL_ATTACHMENT_DOWNLOAD_SCHEMA["name"],
    toolset=TOOLSET,
    schema=GMAIL_ATTACHMENT_DOWNLOAD_SCHEMA,
    handler=google_workspace_gmail_attachment_download_tool,
    check_fn=_check_google_workspace,
    description=GMAIL_ATTACHMENT_DOWNLOAD_SCHEMA["description"],
    emoji="📥",
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
    name=GMAIL_SEND_SCHEMA["name"],
    toolset=TOOLSET,
    schema=GMAIL_SEND_SCHEMA,
    handler=google_workspace_gmail_send_tool,
    check_fn=_check_google_workspace,
    description=GMAIL_SEND_SCHEMA["description"],
    emoji="📨",
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
