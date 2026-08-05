"""Profile-scoped Google Photos Picker tools for Star.

Google removed full-library Library API scopes in 2025. This module therefore
uses the supported Picker API: Joy selects up to 2,000 items in Google Photos,
then Star can inspect safe metadata and download the selected media into a
profile-local managed workspace. It deliberately exposes no cloud mutation.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable

from hermes_constants import get_hermes_home
from tools.registry import registry

TOOLSET = "google_photos"
PICKER_SCOPE = "https://www.googleapis.com/auth/photospicker.mediaitems.readonly"
PICKER_API = "https://photospicker.googleapis.com/v1"
MAX_RESULT_CHARS = 24000
MAX_PICKED_ITEMS = 2000
MAX_LIST_ITEMS = 200
MAX_BATCH_ITEMS = 2000
_BATCH_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def _hermes_home() -> Path:
    return get_hermes_home()


def _token_path() -> Path:
    return _hermes_home() / "google_photos_token.json"


def _import_root() -> Path:
    return _hermes_home() / "google-photos" / "imports"


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


def _check_google_photos() -> bool:
    # Keep status visible before OAuth. The toolset itself is enabled only for
    # profiles explicitly opted in by Puppet.
    return True


def _credentials():
    if not _token_path().exists():
        raise RuntimeError("NOT_AUTHENTICATED: Joy must complete profile-scoped Google Photos OAuth")
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = Credentials.from_authorized_user_file(str(_token_path()), scopes=[PICKER_SCOPE])
    if PICKER_SCOPE not in set(creds.scopes or []):
        raise RuntimeError("NOT_AUTHENTICATED: Google Photos Picker scope is not present")
    if not creds.valid:
        if not creds.refresh_token:
            raise RuntimeError("NOT_AUTHENTICATED: Google Photos refresh token is unavailable")
        creds.refresh(Request())
        _atomic_private_json(_token_path(), json.loads(creds.to_json()))
    return creds


def _atomic_private_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    os.chmod(path, 0o600)


def _api_json(method: str, endpoint: str, *, body: Any | None = None, query: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{PICKER_API}/{endpoint.lstrip('/')}"
    if query:
        url += "?" + urllib.parse.urlencode(query)
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {_credentials().token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:4000]
        raise RuntimeError(f"Google Photos Picker API HTTP {exc.code}: {detail}") from exc
    return json.loads(raw or b"{}")


def _session_id(value: Any) -> str:
    session_id = str(value or "").strip()
    if not session_id or len(session_id) > 512 or any(ch.isspace() for ch in session_id):
        raise ValueError("a valid session_id is required")
    return session_id


def _picked_items(session_id: str, *, limit: int = MAX_BATCH_ITEMS) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page_token = ""
    while len(items) < limit:
        query: dict[str, Any] = {
            "sessionId": session_id,
            "pageSize": min(100, limit - len(items)),
        }
        if page_token:
            query["pageToken"] = page_token
        response = _api_json("GET", "mediaItems", query=query)
        items.extend(response.get("mediaItems") or [])
        page_token = str(response.get("nextPageToken") or "")
        if not page_token:
            break
    return items[:limit]


def _safe_item(item: dict[str, Any], index: int) -> dict[str, Any]:
    media_file = item.get("mediaFile") or {}
    metadata = media_file.get("mediaFileMetadata") or {}
    return {
        "item_handle": f"item-{index:04d}",
        "filename": _safe_filename(media_file.get("filename"), index, media_file.get("mimeType")),
        "mime_type": str(media_file.get("mimeType") or "application/octet-stream"),
        "media_type": str(item.get("type") or "TYPE_UNSPECIFIED"),
        "create_time": str(item.get("createTime") or ""),
        "width": metadata.get("width"),
        "height": metadata.get("height"),
        "video_processing_status": (metadata.get("videoMetadata") or {}).get("processingStatus"),
    }


def _safe_filename(value: Any, index: int, mime_type: Any) -> str:
    name = Path(str(value or "")).name
    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" .")
    if not name:
        extension = mimetypes.guess_extension(str(mime_type or "")) or ".bin"
        name = f"item-{index:04d}{extension}"
    return name[:180]


def _unique_path(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    counter = 2
    while True:
        candidate = directory / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _download_url(item: dict[str, Any]) -> tuple[str, str]:
    media_file = item.get("mediaFile") or {}
    base_url = str(media_file.get("baseUrl") or "")
    media_type = str(item.get("type") or "")
    if not base_url.startswith("https://"):
        raise RuntimeError("selected item did not include a valid HTTPS media URL")
    if media_type == "VIDEO":
        status = ((media_file.get("mediaFileMetadata") or {}).get("videoMetadata") or {}).get("processingStatus")
        if status and status != "READY":
            raise RuntimeError(f"video is not ready for download (status={status})")
        return base_url + "=dv", "high-quality-transcoded-video"
    return base_url + "=d", "download-photo-location-metadata-removed"


def _download_item(item: dict[str, Any], destination: Path) -> dict[str, Any]:
    url, rendition = _download_url(item)
    request = urllib.request.Request(
        url,
        method="GET",
        headers={"Authorization": f"Bearer {_credentials().token}"},
    )
    hasher = hashlib.sha256()
    size = 0
    tmp = destination.with_suffix(destination.suffix + ".part")
    try:
        with urllib.request.urlopen(request, timeout=300) as response, tmp.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                hasher.update(chunk)
                size += len(chunk)
        if size == 0:
            raise RuntimeError("Google returned an empty media file")
        os.replace(tmp, destination)
        os.chmod(destination, 0o600)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return {
        "path": str(destination),
        "bytes": size,
        "sha256": hasher.hexdigest(),
        "rendition": rendition,
    }


def google_photos_status_tool(args: dict[str, Any], **_kw) -> str:
    scopes = _stored_token_scopes()
    return json.dumps(
        {
            "authenticated": _token_path().exists() and PICKER_SCOPE in scopes,
            "scope_present": PICKER_SCOPE in scopes,
            "token_path": str(_token_path()),
            "import_root": str(_import_root()),
            "access_model": "Joy-selected Picker sessions; no full-library API exists",
            "cloud_mutations_exposed": False,
        },
        ensure_ascii=False,
    )


def google_photos_create_selection_tool(args: dict[str, Any], **_kw) -> str:
    max_items = max(1, min(int(args.get("max_items") or 200), MAX_PICKED_ITEMS))
    try:
        response = _api_json("POST", "sessions", body={"pickingConfig": {"maxItemCount": str(max_items)}})
        result = {
            "session_id": response.get("id"),
            "picker_uri": response.get("pickerUri"),
            "expire_time": response.get("expireTime"),
            "max_items": max_items,
            "instructions": "Joy opens picker_uri, searches by keyword/date/location/album title, selects one or more items, then taps Done.",
        }
    except Exception as exc:
        result = {"error": str(exc)}
    return json.dumps(result, ensure_ascii=False)


def google_photos_selection_status_tool(args: dict[str, Any], **_kw) -> str:
    try:
        response = _api_json("GET", f"sessions/{urllib.parse.quote(_session_id(args.get('session_id')), safe='')}")
        result = {
            "session_id": response.get("id"),
            "ready": bool(response.get("mediaItemsSet")),
            "expire_time": response.get("expireTime"),
            "polling_config": response.get("pollingConfig") or {},
        }
    except Exception as exc:
        result = {"error": str(exc)}
    return json.dumps(result, ensure_ascii=False)


def google_photos_list_selection_tool(args: dict[str, Any], **_kw) -> str:
    try:
        session_id = _session_id(args.get("session_id"))
        limit = max(1, min(int(args.get("max_items") or 50), MAX_LIST_ITEMS))
        start_index = max(1, min(int(args.get("start_index") or 1), MAX_PICKED_ITEMS))
        fetched = _picked_items(session_id, limit=min(MAX_PICKED_ITEMS, start_index - 1 + limit))
        items = fetched[start_index - 1 : start_index - 1 + limit]
        result = {
            "session_id": session_id,
            "count_returned": len(items),
            "start_index": start_index,
            "items": [_safe_item(item, index) for index, item in enumerate(items, start_index)],
            "note": "Handles are session-order labels, not Google media IDs.",
        }
    except Exception as exc:
        result = {"error": str(exc)}
    return json.dumps(result, ensure_ascii=False)


def _selected_indexes(handles: Iterable[Any], count: int) -> set[int]:
    raw = [str(handle).strip() for handle in handles if str(handle).strip()]
    if not raw:
        return set(range(1, count + 1))
    indexes: set[int] = set()
    for handle in raw:
        match = re.fullmatch(r"item-(\d{4})", handle)
        if not match:
            raise ValueError(f"invalid item handle: {handle}")
        index = int(match.group(1))
        if index < 1 or index > count:
            raise ValueError(f"item handle outside this selection: {handle}")
        indexes.add(index)
    return indexes


def google_photos_download_selection_tool(args: dict[str, Any], **_kw) -> str:
    try:
        session_id = _session_id(args.get("session_id"))
        batch = str(args.get("batch") or "").strip().lower()
        if not _BATCH_RE.fullmatch(batch):
            raise ValueError("batch must be 1-64 lowercase letters, digits, dots, underscores, or hyphens")
        items = _picked_items(session_id, limit=MAX_BATCH_ITEMS)
        indexes = _selected_indexes(args.get("item_handles") or [], len(items))
        batch_dir = _import_root() / batch
        batch_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(batch_dir, 0o700)
        downloaded: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []
        for index, item in enumerate(items, 1):
            if index not in indexes:
                continue
            safe = _safe_item(item, index)
            destination = _unique_path(batch_dir, safe["filename"])
            try:
                download = _download_item(item, destination)
                downloaded.append({**safe, **download})
            except Exception as exc:
                failures.append({"item_handle": safe["item_handle"], "filename": safe["filename"], "error": str(exc)})
        manifest = {
            "schema": 1,
            "batch": batch,
            "source": "google-photos-picker",
            "downloaded": downloaded,
            "failures": failures,
            "quality_note": "Photos use =d (location metadata removed); videos use =dv (high-quality transcoded), per Google's supported Picker base-URL contract.",
        }
        manifest_path = batch_dir / "manifest.json"
        _atomic_private_json(manifest_path, manifest)
        result = {
            "batch": batch,
            "batch_directory": str(batch_dir),
            "manifest_path": str(manifest_path),
            "downloaded_count": len(downloaded),
            "failure_count": len(failures),
            "items": downloaded,
            "failures": failures,
        }
    except Exception as exc:
        result = {"error": str(exc)}
    return json.dumps(result, ensure_ascii=False)


STATUS_SCHEMA = {
    "name": "google_photos_status",
    "description": "Check Star's profile-scoped Google Photos Picker authorization and supported access model.",
    "parameters": {"type": "object", "properties": {}, "required": []},
}
CREATE_SCHEMA = {
    "name": "google_photos_create_selection",
    "description": "Create a Google Photos Picker session so Joy can select a batch from their library. Read-only library access; no cloud mutation.",
    "parameters": {
        "type": "object",
        "properties": {"max_items": {"type": "integer", "description": "Maximum selectable items, 1-2000 (default 200)"}},
        "required": [],
    },
}
SELECTION_STATUS_SCHEMA = {
    "name": "google_photos_selection_status",
    "description": "Check whether Joy finished a Google Photos Picker session.",
    "parameters": {
        "type": "object",
        "properties": {"session_id": {"type": "string", "description": "Session id from google_photos_create_selection"}},
        "required": ["session_id"],
    },
}
LIST_SCHEMA = {
    "name": "google_photos_list_selection",
    "description": "List safe metadata for items Joy selected in a Picker session. Does not expose Google media IDs or transient base URLs.",
    "parameters": {
        "type": "object",
        "properties": {
            "session_id": {"type": "string", "description": "Completed Picker session id"},
            "max_items": {"type": "integer", "description": "Maximum metadata rows to return, 1-200"},
            "start_index": {"type": "integer", "description": "1-based first item index for paging through up to 2000 selected items"},
        },
        "required": ["session_id"],
    },
}
DOWNLOAD_SCHEMA = {
    "name": "google_photos_download_selection",
    "description": "Download all or selected Picker items into Star's profile-local managed import workspace and write a batch manifest. Local download only; no cloud mutation.",
    "parameters": {
        "type": "object",
        "properties": {
            "session_id": {"type": "string", "description": "Completed Picker session id"},
            "batch": {"type": "string", "description": "Safe batch label used below Star's managed Google Photos import root"},
            "item_handles": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional item-0001 handles from list_selection; omit to download the full selection",
            },
        },
        "required": ["session_id", "batch"],
    },
}

for schema, handler, emoji in [
    (STATUS_SCHEMA, google_photos_status_tool, "🔐"),
    (CREATE_SCHEMA, google_photos_create_selection_tool, "🖼️"),
    (SELECTION_STATUS_SCHEMA, google_photos_selection_status_tool, "⏳"),
    (LIST_SCHEMA, google_photos_list_selection_tool, "🗂️"),
    (DOWNLOAD_SCHEMA, google_photos_download_selection_tool, "📥"),
]:
    registry.register(
        name=schema["name"],
        toolset=TOOLSET,
        schema=schema,
        handler=handler,
        check_fn=_check_google_photos,
        description=schema["description"],
        emoji=emoji,
        max_result_size_chars=MAX_RESULT_CHARS,
    )
