"""Profile-scoped Google Workspace tools for Joy's Hermes profiles.

This exposes selected profile-scoped Google Workspace operations without
requiring a personal-assistant profile to have the general terminal tool.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import stat
import subprocess
import sys
import threading
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from hermes_constants import get_hermes_home
from tools.registry import registry

TOOLSET = "google_workspace"
MAX_RESULT_CHARS = 24000
MAX_GMAIL_RESULTS = 20
MAX_CALENDAR_RESULTS = 50
MAX_GMAIL_ATTACHMENT_BYTES = 20 * 1024 * 1024
MAX_GMAIL_SEND_ATTACHMENT_BYTES = 18 * 1024 * 1024
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
_GOOGLE_API_IMPORT_LOCK = threading.Lock()


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
    script = _script_path("google_api.py")
    module_name = f"hermes_google_api_{hashlib.sha256(str(_hermes_home()).encode()).hexdigest()[:16]}"

    def load_module(name: str, path: Path):
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError("profile-scoped Google Workspace API script could not be loaded")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(name, None)
            raise
        return module

    with _GOOGLE_API_IMPORT_LOCK:
        original_path = sys.path[:]
        previous_helper = sys.modules.get("_hermes_home")
        try:
            sys.path.insert(0, str(script.parent))
            helper_path = script.parent / "_hermes_home.py"
            if helper_path.exists():
                helper_name = f"{module_name}_hermes_home"
                sys.modules["_hermes_home"] = load_module(helper_name, helper_path)
            google_api = load_module(module_name, script)
        finally:
            sys.path[:] = original_path
            if previous_helper is None:
                sys.modules.pop("_hermes_home", None)
            else:
                sys.modules["_hermes_home"] = previous_helper
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


def _gmail_send_attachment_root() -> Path:
    return _hermes_home() / "downloads" / "google-workspace"


def _gmail_send_attachment(item: dict[str, Any]) -> tuple[Path, str, str, int]:
    raw_path = str(item.get("path") or "").strip()
    if not raw_path:
        raise ValueError("ATTACHMENT_PATH_REQUIRED")
    source = Path(raw_path).expanduser()
    if not source.is_absolute():
        raise ValueError("UNSUPPORTED_ATTACHMENT_PATH")
    if source.is_symlink():
        raise ValueError("UNSUPPORTED_ATTACHMENT_PATH")
    try:
        resolved = source.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError("ATTACHMENT_NOT_FOUND") from exc
    try:
        resolved.relative_to(_gmail_send_attachment_root().resolve())
    except ValueError as exc:
        raise ValueError("UNSUPPORTED_ATTACHMENT_PATH") from exc
    source_stat = resolved.stat()
    if not stat.S_ISREG(source_stat.st_mode) or source_stat.st_nlink != 1:
        raise ValueError("UNSUPPORTED_ATTACHMENT_PATH")

    filename = str(item.get("filename") or resolved.name).strip()
    if not filename or Path(filename.replace("\\", "/")).name != filename or "\n" in filename or "\r" in filename:
        raise ValueError("INVALID_ATTACHMENT_FILENAME")
    mime_type = str(item.get("mime_type") or mimetypes.guess_type(filename)[0] or "application/octet-stream").lower().strip()
    if not re.fullmatch(r"[-+.a-z0-9]+/[-+.a-z0-9]+", mime_type):
        raise ValueError("INVALID_ATTACHMENT_MIME_TYPE")
    return resolved, filename, mime_type, source_stat.st_size


def _read_gmail_send_attachment(path: Path, max_bytes: int) -> bytes:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        if path.is_symlink():
            raise ValueError("ATTACHMENT_CHANGED") from exc
        raise ValueError("ATTACHMENT_NOT_READABLE") from exc

    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise ValueError("UNSUPPORTED_ATTACHMENT_PATH")

        try:
            current = os.stat(path, follow_symlinks=False)
            resolved = path.resolve(strict=True)
            resolved.relative_to(_gmail_send_attachment_root().resolve())
        except (OSError, RuntimeError, ValueError) as exc:
            raise ValueError("ATTACHMENT_CHANGED") from exc
        if (
            not stat.S_ISREG(current.st_mode)
            or current.st_nlink != 1
            or (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino)
        ):
            raise ValueError("ATTACHMENT_CHANGED")
        if opened.st_size > max_bytes:
            raise ValueError("ATTACHMENTS_TOO_LARGE")

        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            descriptor = -1
            content = handle.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise ValueError("ATTACHMENTS_TOO_LARGE")
        return content
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _gmail_thread_reply_headers(service, thread_id: str) -> tuple[str, str, str]:
    thread = (
        service.users()
        .threads()
        .get(userId="me", id=thread_id, format="metadata")
        .execute(num_retries=0)
    )
    messages = thread.get("messages") or []
    if not messages:
        raise ValueError("THREAD_NOT_FOUND")
    headers = {
        str(item.get("name") or "").lower(): str(item.get("value") or "")
        for item in (messages[-1].get("payload") or {}).get("headers") or []
    }
    message_id = headers.get("message-id", "").strip()
    if not message_id:
        raise ValueError("THREAD_MESSAGE_ID_MISSING")
    subject = headers.get("subject", "").strip()
    if not subject:
        raise ValueError("THREAD_SUBJECT_MISSING")
    references = headers.get("references", "").strip()
    if message_id not in references.split():
        references = f"{references} {message_id}".strip()
    return message_id, references, subject


def _gmail_send_request_hash(
    *,
    to: str,
    cc: str,
    bcc: str,
    from_header: str,
    subject: str,
    body: str,
    html: bool,
    thread_id: str,
    attachments: list[tuple[bytes, str, str]],
) -> str:
    payload = {
        "to": to,
        "cc": cc,
        "bcc": bcc,
        "from_header": from_header,
        "subject": subject,
        "body": body,
        "html": html,
        "thread_id": thread_id,
        "attachments": [
            {
                "sha256": hashlib.sha256(content).hexdigest(),
                "filename": filename,
                "mime_type": mime_type,
            }
            for content, filename, mime_type in attachments
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _gmail_send_ledger() -> sqlite3.Connection:
    state_dir = _hermes_home() / "state"
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(state_dir, 0o700)
    path = state_dir / "google_workspace_gmail_send.sqlite3"
    connection = sqlite3.connect(path, timeout=5)
    connection.execute(
        """CREATE TABLE IF NOT EXISTS sends (
               idempotency_key TEXT PRIMARY KEY,
               request_hash TEXT NOT NULL,
               status TEXT NOT NULL,
               message_id TEXT,
               thread_id TEXT
           )"""
    )
    connection.commit()
    os.chmod(path, 0o600)
    return connection


def _reserve_gmail_send(idempotency_key: str, request_hash: str) -> dict[str, Any] | None:
    with _gmail_send_ledger() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT request_hash, status, message_id, thread_id FROM sends WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if row is None:
            connection.execute(
                "INSERT INTO sends (idempotency_key, request_hash, status) VALUES (?, ?, 'sending')",
                (idempotency_key, request_hash),
            )
            return None
        stored_hash, status, message_id, thread_id = row
        if stored_hash != request_hash:
            return {
                "error": "IDEMPOTENCY_KEY_REUSED",
                "message": "This idempotency_key is already bound to different message content.",
                "idempotency_key": idempotency_key,
            }
        if status == "sent":
            return {
                "message_id": message_id or "",
                "thread_id": thread_id or "",
                "idempotency_key": idempotency_key,
                "duplicate_suppressed": True,
            }
        return {
            "error": "UNKNOWN_SEND_OUTCOME",
            "message": "A prior attempt may have reached Gmail; the tool will not risk sending a duplicate.",
            "idempotency_key": idempotency_key,
        }


def _record_gmail_send(idempotency_key: str, *, status: str, message_id: str = "", thread_id: str = "") -> None:
    with _gmail_send_ledger() as connection:
        connection.execute(
            "UPDATE sends SET status = ?, message_id = ?, thread_id = ? WHERE idempotency_key = ?",
            (status, message_id, thread_id, idempotency_key),
        )


def _forget_gmail_send(idempotency_key: str) -> None:
    with _gmail_send_ledger() as connection:
        connection.execute("DELETE FROM sends WHERE idempotency_key = ?", (idempotency_key,))


def google_workspace_gmail_send_tool(args: dict[str, Any], **_kw) -> str:
    """Send a Gmail message through the profile-scoped OAuth token."""
    to = str(args.get("to") or "").strip()
    subject = str(args.get("subject") or "").strip()
    body = str(args.get("body") or "")
    cc = str(args.get("cc") or "").strip()
    bcc = str(args.get("bcc") or "").strip()
    from_header = str(args.get("from_header") or "").strip()
    html = bool(args.get("html") or False)
    thread_id = str(args.get("thread_id") or "").strip()
    idempotency_key = str(args.get("idempotency_key") or secrets.token_urlsafe(18)).strip()

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

    if not re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", idempotency_key):
        return json.dumps(
            {
                "error": "INVALID_IDEMPOTENCY_KEY",
                "message": "idempotency_key must be 8-128 safe ASCII characters.",
            },
            ensure_ascii=False,
        )

    attachment_items = args.get("attachments") or []
    if not isinstance(attachment_items, list) or not all(isinstance(item, dict) for item in attachment_items):
        return json.dumps(
            {
                "error": "INVALID_ATTACHMENTS",
                "message": "attachments must be an array of objects with a path field.",
            },
            ensure_ascii=False,
        )
    if len(attachment_items) > 20:
        return json.dumps(
            {"error": "TOO_MANY_ATTACHMENTS", "message": "At most 20 attachments may be sent in one message."},
            ensure_ascii=False,
        )
    try:
        attachment_sources = [_gmail_send_attachment(item) for item in attachment_items]
    except ValueError as exc:
        error = str(exc)
        messages = {
            "ATTACHMENT_PATH_REQUIRED": "Every attachment requires a path.",
            "ATTACHMENT_NOT_FOUND": "Attachment path does not exist or cannot be read.",
            "UNSUPPORTED_ATTACHMENT_PATH": "Attachment must be a regular, non-symlink file under this profile's downloads/google-workspace staging directory.",
            "INVALID_ATTACHMENT_FILENAME": "Attachment filename must be a safe basename without control characters.",
            "INVALID_ATTACHMENT_MIME_TYPE": "Attachment MIME type must use a valid type/subtype form.",
        }
        return json.dumps({"error": error, "message": messages.get(error, "Attachment validation failed.")}, ensure_ascii=False)
    except OSError:
        return json.dumps(
            {"error": "ATTACHMENT_NOT_READABLE", "message": "Attachment exists but could not be read."},
            ensure_ascii=False,
        )
    total_attachment_bytes = sum(size for _path, _filename, _mime_type, size in attachment_sources)
    if total_attachment_bytes > MAX_GMAIL_SEND_ATTACHMENT_BYTES:
        return json.dumps(
            {
                "error": "ATTACHMENTS_TOO_LARGE",
                "message": "Aggregate attachment source size exceeds the safe 18 MiB limit for Gmail's encoded message limit.",
                "size": total_attachment_bytes,
                "max_size": MAX_GMAIL_SEND_ATTACHMENT_BYTES,
            },
            ensure_ascii=False,
        )

    try:
        attachments: list[tuple[bytes, str, str]] = []
        remaining_bytes = MAX_GMAIL_SEND_ATTACHMENT_BYTES
        for path, filename, mime_type, _size in attachment_sources:
            content = _read_gmail_send_attachment(path, remaining_bytes)
            attachments.append((content, filename, mime_type))
            remaining_bytes -= len(content)
    except ValueError as exc:
        error = str(exc)
        if error != "ATTACHMENTS_TOO_LARGE":
            messages = {
                "ATTACHMENT_CHANGED": "Attachment changed after validation and was not read; stage it again before retrying.",
                "ATTACHMENT_NOT_READABLE": "Attachment exists but could not be safely opened for reading.",
                "UNSUPPORTED_ATTACHMENT_PATH": "Attachment must remain a regular, non-symlink file under downloads/google-workspace.",
            }
            return json.dumps(
                {"error": error, "message": messages.get(error, "Attachment validation failed while reading.")},
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "error": "ATTACHMENTS_TOO_LARGE",
                "message": "Attachment content changed while reading and exceeds the safe 18 MiB limit.",
                "max_size": MAX_GMAIL_SEND_ATTACHMENT_BYTES,
            },
            ensure_ascii=False,
        )

    request_hash = _gmail_send_request_hash(
        to=to,
        cc=cc,
        bcc=bcc,
        from_header=from_header,
        subject=subject,
        body=body,
        html=html,
        thread_id=thread_id,
        attachments=attachments,
    )

    try:
        message = EmailMessage()
        message["To"] = to
        message["Subject"] = subject
        if cc:
            message["Cc"] = cc
        if bcc:
            message["Bcc"] = bcc
        if from_header:
            message["From"] = from_header
        message["Message-ID"] = f"<hermes-{hashlib.sha256(idempotency_key.encode()).hexdigest()}@gmail-send.invalid>"
        message.set_content(body, subtype="html" if html else "plain")
        for content, filename, mime_type in attachments:
            maintype, subtype = mime_type.split("/", 1)
            message.add_attachment(content, maintype=maintype, subtype=subtype, filename=filename)
    except (TypeError, ValueError):
        return json.dumps(
            {
                "error": "INVALID_MESSAGE_HEADERS",
                "message": "Message address or header values are invalid; no message was sent.",
                "idempotency_key": idempotency_key,
            },
            ensure_ascii=False,
        )

    try:
        service = _gmail_service()
        reply_headers = _gmail_thread_reply_headers(service, thread_id) if thread_id else None
        if reply_headers is not None:
            in_reply_to, references, thread_subject = reply_headers
            if subject != thread_subject:
                return json.dumps(
                    {
                        "error": "THREAD_SUBJECT_MISMATCH",
                        "message": "Gmail requires a threaded reply to use the existing thread subject; no message was sent.",
                        "thread_subject": thread_subject,
                        "idempotency_key": idempotency_key,
                    },
                    ensure_ascii=False,
                )
            message["In-Reply-To"] = in_reply_to
            message["References"] = references

        request_body: dict[str, str] = {
            "raw": base64.urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("="),
        }
        if thread_id:
            request_body["threadId"] = thread_id
    except Exception as exc:
        http_status = int(getattr(getattr(exc, "resp", None), "status", 0) or 0)
        error = "THREAD_LOOKUP_FAILED" if thread_id else "GMAIL_CLIENT_FAILED"
        message_text = (
            "Gmail thread metadata could not be read; no message was sent. Retry with the same idempotency_key."
            if thread_id
            else "The profile-scoped Gmail client could not be loaded; no message was sent. Retry with the same idempotency_key."
        )
        return json.dumps(
            {
                "error": error,
                "message": message_text,
                "http_status": http_status,
                "idempotency_key": idempotency_key,
            },
            ensure_ascii=False,
        )

    prior_result = _reserve_gmail_send(idempotency_key, request_hash)
    if prior_result is not None:
        return json.dumps(prior_result, ensure_ascii=False)

    try:
        result = (
            service
            .users()
            .messages()
            .send(userId="me", body=request_body)
            .execute(num_retries=0)
        )
    except Exception as exc:
        http_status = int(getattr(getattr(exc, "resp", None), "status", 0) or 0)
        if http_status == 401:
            _forget_gmail_send(idempotency_key)
            return json.dumps(
                {
                    "error": "AUTHENTICATION_FAILED",
                    "message": "Gmail authorization failed; ask Talon to refresh this profile's OAuth grant and scopes.",
                    "http_status": http_status,
                    "idempotency_key": idempotency_key,
                },
                ensure_ascii=False,
            )
        if 400 <= http_status < 500 and http_status not in (403, 408, 429):
            _forget_gmail_send(idempotency_key)
            return json.dumps(
                {
                    "error": "GMAIL_REJECTED",
                    "message": "Gmail rejected the message before accepting it. Correct the message and use a new idempotency_key.",
                    "http_status": http_status,
                    "idempotency_key": idempotency_key,
                },
                ensure_ascii=False,
            )
        _record_gmail_send(idempotency_key, status="unknown")
        return json.dumps(
            {
                "error": "UNKNOWN_SEND_OUTCOME",
                "message": "Gmail did not confirm whether the message was accepted; do not retry without this idempotency_key.",
                "http_status": http_status,
                "idempotency_key": idempotency_key,
            },
            ensure_ascii=False,
        )
    message_id = str(result.get("id") or "")
    result_thread_id = str(result.get("threadId") or "")
    if not message_id or not result_thread_id:
        _record_gmail_send(idempotency_key, status="unknown")
        return json.dumps(
            {
                "error": "UNKNOWN_SEND_OUTCOME",
                "message": "Gmail accepted the request but did not return both message ID and thread ID; do not retry without this idempotency_key.",
                "idempotency_key": idempotency_key,
            },
            ensure_ascii=False,
        )
    _record_gmail_send(
        idempotency_key,
        status="sent",
        message_id=message_id,
        thread_id=result_thread_id,
    )
    return json.dumps(
        {
            "message_id": message_id,
            "thread_id": result_thread_id,
            "idempotency_key": idempotency_key,
        },
        ensure_ascii=False,
    )


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
    "description": "Send a Gmail message, optionally with local attachments, from Joy's profile-scoped Google account using Star's Google Workspace OAuth token.",
    "parameters": {
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "Recipient email address"},
            "subject": {"type": "string", "description": "Email subject"},
            "body": {"type": "string", "description": "Email body"},
            "cc": {"type": "string", "description": "Optional comma-separated Cc recipients"},
            "bcc": {"type": "string", "description": "Optional comma-separated Bcc recipients"},
            "from_header": {"type": "string", "description": "Optional From header/display name"},
            "html": {"type": "boolean", "description": "Treat body as HTML"},
            "thread_id": {"type": "string", "description": "Optional Gmail threadId for threading the sent message"},
            "attachments": {
                "type": "array",
                "description": "Optional local files under this profile's downloads/google-workspace staging directory; aggregate source size is limited to 18 MiB.",
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Absolute path under this profile's downloads/google-workspace staging directory"},
                        "filename": {"type": "string", "description": "Optional attachment filename; defaults to the local basename"},
                        "mime_type": {"type": "string", "description": "Optional type/subtype; safely auto-detected when omitted"},
                    },
                    "required": ["path"],
                    "additionalProperties": False,
                },
            },
            "idempotency_key": {
                "type": "string",
                "description": "Optional stable retry key. Reuse the returned key after an unknown outcome; the tool will not send twice.",
                "minLength": 8,
                "maxLength": 128,
                "pattern": "^[A-Za-z0-9._:-]+$",
            },
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
