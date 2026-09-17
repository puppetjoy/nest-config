#!/usr/bin/env python3
"""Contract checks for Star's Google Photos Picker tool surface."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import sys
import tempfile
import types
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOL = REPO_ROOT / "files/app/hermes/google_photos_tool.py"
EXPECTED_TOOLS = {
    "google_photos_status",
    "google_photos_create_selection",
    "google_photos_selection_status",
    "google_photos_list_selection",
    "google_photos_download_selection",
}


class DummyRegistry:
    def __init__(self) -> None:
        self.names: list[str] = []

    def register(self, **kwargs: Any) -> None:
        self.names.append(kwargs["name"])


def load_tool() -> tuple[Any, DummyRegistry]:
    registry = DummyRegistry()
    tools = types.ModuleType("tools")
    registry_module = types.ModuleType("tools.registry")
    setattr(registry_module, "registry", registry)
    constants_module = types.ModuleType("hermes_constants")
    setattr(constants_module, "get_hermes_home", lambda: Path("/nonexistent"))
    sys.modules["tools"] = tools
    sys.modules["tools.registry"] = registry_module
    sys.modules["hermes_constants"] = constants_module
    spec = importlib.util.spec_from_file_location("google_photos_tool_under_test", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, registry


def parsed(value: str) -> dict[str, Any]:
    result = json.loads(value)
    assert isinstance(result, dict)
    return result


def test_all_tools_have_top_level_registry_registration_for_discovery() -> None:
    tree = ast.parse(TOOL.read_text(encoding="utf-8"))
    registered_names = {
        keyword.value.value
        for statement in tree.body
        if isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Call)
        and isinstance(statement.value.func, ast.Attribute)
        and statement.value.func.attr == "register"
        and isinstance(statement.value.func.value, ast.Name)
        and statement.value.func.value.id == "registry"
        for keyword in statement.value.keywords
        if keyword.arg == "name" and isinstance(keyword.value, ast.Constant)
    }
    assert registered_names == EXPECTED_TOOLS


def test_picker_workflow_is_bounded_safe_and_downloads_exact_supported_renditions() -> None:
    module, registry = load_tool()
    assert set(registry.names) == EXPECTED_TOOLS

    with tempfile.TemporaryDirectory() as auth_tmpdir:
        token_path = Path(auth_tmpdir) / "google_photos_token.json"
        token_path.write_text(
            json.dumps({"token": "must-not-leak", "scopes": [module.PICKER_SCOPE]}),
            encoding="utf-8",
        )
        module._token_path = lambda: token_path
        auth_text = module.google_photos_status_tool({})
        auth = parsed(auth_text)
        assert auth["authenticated"] is True
        assert auth["cloud_mutations_exposed"] is False
        assert "must-not-leak" not in auth_text

    api_calls: list[tuple[str, str, Any, Any]] = []

    def fake_api(method: str, endpoint: str, *, body: Any = None, query: Any = None) -> dict[str, Any]:
        api_calls.append((method, endpoint, body, query))
        if method == "POST":
            return {"id": "session-secret", "pickerUri": "https://picker.example/secret", "expireTime": "later"}
        return {"id": "session-secret", "mediaItemsSet": True, "pollingConfig": {"pollInterval": "3s"}}

    module._api_json = fake_api
    created = parsed(module.google_photos_create_selection_tool({"max_items": 9999}))
    assert created["max_items"] == 2000
    assert api_calls[-1][2] == {"pickingConfig": {"maxItemCount": "2000"}}
    status = parsed(module.google_photos_selection_status_tool({"session_id": "session-secret"}))
    assert status["ready"] is True
    assert status["polling_config"] == {"pollInterval": "3s"}

    picked_items = [
        {
            "id": "google-media-id-1",
            "type": "PHOTO",
            "mediaFile": {
                "baseUrl": "https://media.example/transient-1",
                "filename": "first.jpg",
                "mimeType": "image/jpeg",
                "mediaFileMetadata": {"width": "10", "height": "20"},
            },
        },
        {
            "id": "google-media-id-2",
            "type": "PHOTO",
            "mediaFile": {
                "baseUrl": "https://media.example/transient-2",
                "filename": "second.jpg",
                "mimeType": "image/jpeg",
                "mediaFileMetadata": {"width": "30", "height": "40"},
            },
        },
    ]
    module._picked_items = lambda _session_id, *, limit: picked_items[:limit]
    listed_text = module.google_photos_list_selection_tool({"session_id": "session-secret", "max_items": 1})
    listed = parsed(listed_text)
    assert listed["count_returned"] == 1
    assert listed["items"][0]["item_handle"] == "item-0001"
    assert "google-media-id" not in listed_text
    assert "media.example" not in listed_text

    with tempfile.TemporaryDirectory() as tmpdir:
        module._import_root = lambda: Path(tmpdir)

        def fake_download(item: dict[str, Any], destination: Path) -> dict[str, Any]:
            payload = item["mediaFile"]["filename"].encode("utf-8")
            destination.write_bytes(payload)
            return {
                "path": str(destination),
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "rendition": "download-photo-location-metadata-removed",
            }

        module._download_item = fake_download
        downloaded = parsed(
            module.google_photos_download_selection_tool(
                {"session_id": "session-secret", "batch": "bounded-test", "item_handles": ["item-0002"]}
            )
        )
        manifest = json.loads(Path(downloaded["manifest_path"]).read_text(encoding="utf-8"))
        assert downloaded["downloaded_count"] == 1
        assert downloaded["items"][0]["item_handle"] == "item-0002"
        assert manifest["artifact_kind"] == "supported-rendition"
        assert manifest["archival_original"] is False
        row = manifest["downloaded"][0]
        assert hashlib.sha256(Path(row["path"]).read_bytes()).hexdigest() == row["sha256"]
        manifest_text = json.dumps(manifest)
        assert "google-media-id" not in manifest_text
        assert "media.example" not in manifest_text


if __name__ == "__main__":
    test_all_tools_have_top_level_registry_registration_for_discovery()
    test_picker_workflow_is_bounded_safe_and_downloads_exact_supported_renditions()
