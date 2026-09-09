#!/usr/bin/env python3
"""Regression checks for profile-scoped Gmail attachment retrieval."""

from __future__ import annotations

import base64
import importlib.util
import json
import stat
import sys
import tempfile
import types
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
GOOGLE_WORKSPACE_TOOL = REPO_ROOT / "files/app/hermes/google_workspace_tool.py"


class DummyRegistry:
  def register(self, **_kwargs: Any) -> None:
    return None


class Executable:
  def __init__(self, result: dict[str, Any]) -> None:
    self.result = result

  def execute(self) -> dict[str, Any]:
    return self.result


class FakeAttachments:
  def __init__(self, result: dict[str, Any]) -> None:
    self.result = result
    self.calls: list[dict[str, str]] = []

  def get(self, **kwargs: str) -> Executable:
    self.calls.append(kwargs)
    return Executable(self.result)


class FakeMessages:
  def __init__(self, message: dict[str, Any], attachment: dict[str, Any]) -> None:
    self.message = message
    self.message_calls: list[dict[str, str]] = []
    self.attachment_api = FakeAttachments(attachment)

  def get(self, **kwargs: str) -> Executable:
    self.message_calls.append(kwargs)
    return Executable(self.message)

  def attachments(self) -> FakeAttachments:
    return self.attachment_api


class FakeUsers:
  def __init__(self, messages: FakeMessages) -> None:
    self.message_api = messages

  def messages(self) -> FakeMessages:
    return self.message_api


class FakeService:
  def __init__(self, message: dict[str, Any], attachment: dict[str, Any]) -> None:
    self.messages_api = FakeMessages(message, attachment)

  def users(self) -> FakeUsers:
    return FakeUsers(self.messages_api)


def load_tool_module(tmp_path: Path, service: FakeService):
  tools_module = types.ModuleType("tools")
  registry_module = types.ModuleType("tools.registry")
  setattr(registry_module, "registry", DummyRegistry())
  sys.modules.setdefault("tools", tools_module)
  sys.modules["tools.registry"] = registry_module

  constants_module = types.ModuleType("hermes_constants")
  setattr(constants_module, "get_hermes_home", lambda: tmp_path)
  sys.modules["hermes_constants"] = constants_module

  scripts = tmp_path / "skills/productivity/google-workspace/scripts"
  scripts.mkdir(parents=True)
  (scripts / "google_api.py").write_text("# fake\n", encoding="utf-8")
  google_api_module = types.ModuleType("google_api")
  setattr(google_api_module, "build_service", lambda *_args, **_kwargs: service)
  sys.modules["google_api"] = google_api_module

  spec = importlib.util.spec_from_file_location("google_workspace_tool_under_test", GOOGLE_WORKSPACE_TOOL)
  assert spec is not None and spec.loader is not None
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


def gmail_message(*, size: int = 14, mime_type: str = "application/pdf") -> dict[str, Any]:
  return {
    "id": "message-123",
    "threadId": "thread-456",
    "payload": {
      "mimeType": "multipart/mixed",
      "parts": [
        {
          "partId": "0",
          "mimeType": "multipart/alternative",
          "parts": [
            {"partId": "0.0", "mimeType": "text/plain", "body": {"data": "SGVsbG8="}},
          ],
        },
        {
          "partId": "1",
          "filename": "Quote 20737-1.pdf",
          "mimeType": mime_type,
          "body": {"attachmentId": "attachment-abc", "size": size},
        },
      ],
    },
  }


def test_lists_nested_attachment_metadata_without_downloading() -> None:
  with tempfile.TemporaryDirectory() as tmpdir:
    tmp_path = Path(tmpdir)
    service = FakeService(gmail_message(), {"data": "unused"})
    module = load_tool_module(tmp_path, service)

    result = json.loads(module.google_workspace_gmail_attachments_tool({"message_id": "message-123"}))

    assert result == {
      "message_id": "message-123",
      "attachments": [
        {
          "attachment_id": "attachment-abc",
          "part_id": "1",
          "filename": "Quote 20737-1.pdf",
          "mime_type": "application/pdf",
          "size": 14,
        }
      ],
      "attachment_count": 1,
      "read_only": True,
    }
    assert service.messages_api.message_calls == [
      {"userId": "me", "id": "message-123", "format": "full"}
    ]
    assert service.messages_api.attachment_api.calls == []


def test_downloads_explicit_supported_attachment_to_profile_bounded_path() -> None:
  with tempfile.TemporaryDirectory() as tmpdir:
    tmp_path = Path(tmpdir)
    payload = b"%PDF-1.7 quote"
    service = FakeService(
      gmail_message(size=len(payload)),
      {"data": base64.urlsafe_b64encode(payload).decode("ascii"), "size": len(payload)},
    )
    module = load_tool_module(tmp_path, service)

    result = json.loads(
      module.google_workspace_gmail_attachment_download_tool(
        {"message_id": "message-123", "part_id": "1"}
      )
    )

    downloaded = Path(result["path"])
    assert downloaded.is_relative_to(tmp_path / "downloads/google-workspace/gmail")
    assert downloaded.read_bytes() == payload
    assert stat.S_IMODE(downloaded.stat().st_mode) == 0o600
    assert result["message_id"] == "message-123"
    assert result["attachment_id"] == "attachment-abc"
    assert result["filename"] == "Quote 20737-1.pdf"
    assert result["mime_type"] == "application/pdf"
    assert result["size"] == len(payload)
    assert result["read_only"] is True
    assert service.messages_api.attachment_api.calls == [
      {"userId": "me", "messageId": "message-123", "id": "attachment-abc"}
    ]


def test_accepts_pdf_filename_with_generic_octet_stream_metadata() -> None:
  with tempfile.TemporaryDirectory() as tmpdir:
    payload = b"%PDF-1.7 quote"
    service = FakeService(
      gmail_message(size=len(payload), mime_type="application/octet-stream"),
      {"data": base64.urlsafe_b64encode(payload).decode("ascii"), "size": len(payload)},
    )
    module = load_tool_module(Path(tmpdir), service)

    result = json.loads(
      module.google_workspace_gmail_attachment_download_tool(
        {"message_id": "message-123", "part_id": "1"}
      )
    )

    assert result["mime_type"] == "application/octet-stream"
    assert Path(result["path"]).read_bytes() == payload


def test_rejects_oversize_attachment_before_downloading() -> None:
  with tempfile.TemporaryDirectory() as tmpdir:
    service = FakeService(gmail_message(size=20 * 1024 * 1024 + 1), {"data": "unused"})
    module = load_tool_module(Path(tmpdir), service)

    result = json.loads(
      module.google_workspace_gmail_attachment_download_tool(
        {"message_id": "message-123", "part_id": "1"}
      )
    )

    assert result["error"] == "ATTACHMENT_TOO_LARGE"
    assert result["size"] == 20 * 1024 * 1024 + 1
    assert service.messages_api.attachment_api.calls == []


def test_rejects_unsafe_mime_type_before_downloading() -> None:
  with tempfile.TemporaryDirectory() as tmpdir:
    service = FakeService(gmail_message(mime_type="application/x-msdownload"), {"data": "unused"})
    module = load_tool_module(Path(tmpdir), service)

    result = json.loads(
      module.google_workspace_gmail_attachment_download_tool(
        {"message_id": "message-123", "part_id": "1"}
      )
    )

    assert result["error"] == "UNSUPPORTED_ATTACHMENT_MIME_TYPE"
    assert result["mime_type"] == "application/x-msdownload"
    assert service.messages_api.attachment_api.calls == []


def test_rejects_part_id_not_present_on_message() -> None:
  with tempfile.TemporaryDirectory() as tmpdir:
    service = FakeService(gmail_message(), {"data": "unused"})
    module = load_tool_module(Path(tmpdir), service)

    result = json.loads(
      module.google_workspace_gmail_attachment_download_tool(
        {"message_id": "message-123", "part_id": "not-on-message"}
      )
    )

    assert result["error"] == "ATTACHMENT_NOT_FOUND"
    assert service.messages_api.attachment_api.calls == []


def test_api_errors_do_not_expose_oauth_material() -> None:
  with tempfile.TemporaryDirectory() as tmpdir:
    service = FakeService(gmail_message(), {"data": "unused"})
    module = load_tool_module(Path(tmpdir), service)

    def fail(_message_id: str):
      raise RuntimeError("request failed: access_token=never-return-this")

    setattr(module, "_gmail_attachments", fail)
    list_result = module.google_workspace_gmail_attachments_tool({"message_id": "message-123"})
    download_result = module.google_workspace_gmail_attachment_download_tool(
      {"message_id": "message-123", "part_id": "1"}
    )

    assert "never-return-this" not in list_result
    assert "never-return-this" not in download_result


if __name__ == "__main__":
  test_lists_nested_attachment_metadata_without_downloading()
  test_downloads_explicit_supported_attachment_to_profile_bounded_path()
  test_accepts_pdf_filename_with_generic_octet_stream_metadata()
  test_rejects_oversize_attachment_before_downloading()
  test_rejects_unsafe_mime_type_before_downloading()
  test_rejects_part_id_not_present_on_message()
  test_api_errors_do_not_expose_oauth_material()
