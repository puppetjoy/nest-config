#!/usr/bin/env python3
"""Regression checks for profile-scoped Gmail attachment sending."""

from __future__ import annotations

import base64
import builtins
import importlib.util
import json
import os
import sys
import tempfile
import types
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Any
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
GOOGLE_WORKSPACE_TOOL = REPO_ROOT / "files/app/hermes/google_workspace_tool.py"


class DummyRegistry:
  def register(self, **_kwargs: Any) -> None:
    return None


class SendExecutable:
  def __init__(self, result: dict[str, Any]) -> None:
    self.result = result
    self.num_retries: int | None = None

  def execute(self, *, num_retries: int = 0) -> dict[str, Any]:
    self.num_retries = num_retries
    return self.result


class FakeHttpError(RuntimeError):
  def __init__(self, status: int) -> None:
    super().__init__(f"HTTP {status}: secret response body must not escape")
    self.resp = types.SimpleNamespace(status=status)


class ErrorExecutable:
  def __init__(self, status: int) -> None:
    self.status = status

  def execute(self, *, num_retries: int = 0) -> dict[str, str]:
    del num_retries
    raise FakeHttpError(self.status)


class FakeMessages:
  def __init__(self, error_status: int | None = None) -> None:
    self.calls: list[dict[str, Any]] = []
    self.executables: list[SendExecutable] = []
    self.error_status = error_status

  def send(self, **kwargs: Any) -> SendExecutable | ErrorExecutable:
    self.calls.append(kwargs)
    if self.error_status is not None:
      return ErrorExecutable(self.error_status)
    executable = SendExecutable({"id": "message-123", "threadId": "thread-456"})
    self.executables.append(executable)
    return executable


class FakeThreads:
  def __init__(self, subject: str = "Attachment test") -> None:
    self.calls: list[dict[str, Any]] = []
    self.subject = subject

  def get(self, **kwargs: Any) -> SendExecutable:
    self.calls.append(kwargs)
    return SendExecutable(
      {
        "messages": [
          {
            "payload": {
              "headers": [
                {"name": "Message-ID", "value": "<previous@example.test>"},
                {"name": "References", "value": "<root@example.test>"},
                {"name": "Subject", "value": self.subject},
              ]
            }
          }
        ]
      }
    )


class FakeUsers:
  def __init__(self, messages: FakeMessages, threads: FakeThreads) -> None:
    self.messages_api = messages
    self.threads_api = threads

  def messages(self) -> FakeMessages:
    return self.messages_api

  def threads(self) -> FakeThreads:
    return self.threads_api


class FakeService:
  def __init__(self, error_status: int | None = None, thread_subject: str = "Attachment test") -> None:
    self.messages_api = FakeMessages(error_status)
    self.threads_api = FakeThreads(thread_subject)

  def users(self) -> FakeUsers:
    return FakeUsers(self.messages_api, self.threads_api)


def load_tool_module(tmp_path: Path, service: FakeService | None = None):
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
  services = getattr(builtins, "_gmail_test_services", {})
  services[str(tmp_path)] = service
  setattr(builtins, "_gmail_test_services", services)
  (scripts / "google_api.py").write_text(
    "import builtins\n"
    f"PROFILE_HOME = {str(tmp_path)!r}\n"
    "def build_service(*_args, **_kwargs):\n"
    "  return builtins._gmail_test_services[PROFILE_HOME]\n",
    encoding="utf-8",
  )

  spec = importlib.util.spec_from_file_location("google_workspace_send_tool_under_test", GOOGLE_WORKSPACE_TOOL)
  assert spec is not None and spec.loader is not None
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


def test_send_schema_exposes_attachment_and_existing_message_fields() -> None:
  with tempfile.TemporaryDirectory() as tmpdir:
    module = load_tool_module(Path(tmpdir))

    parameters = module.GMAIL_SEND_SCHEMA["parameters"]

    assert set(parameters["properties"]) >= {
      "to",
      "cc",
      "bcc",
      "from_header",
      "subject",
      "body",
      "html",
      "thread_id",
      "attachments",
      "idempotency_key",
    }
    attachment = parameters["properties"]["attachments"]["items"]
    assert attachment["required"] == ["path"]
    assert set(attachment["properties"]) == {"path", "filename", "mime_type"}
    assert parameters["properties"]["attachments"]["maxItems"] == 20
    assert parameters["properties"]["idempotency_key"]["minLength"] == 8
    assert parameters["properties"]["idempotency_key"]["maxLength"] == 128


def test_sends_multipart_attachment_with_all_headers_and_returns_ids() -> None:
  with tempfile.TemporaryDirectory() as tmpdir:
    tmp_path = Path(tmpdir)
    service = FakeService()
    module = load_tool_module(tmp_path, service)
    (tmp_path / "google_token.json").write_text(
      json.dumps({"scopes": [module.GMAIL_SEND_SCOPE]}),
      encoding="utf-8",
    )
    attachment = tmp_path / "downloads/google-workspace/report.txt"
    attachment.parent.mkdir(parents=True)
    attachment.write_text("attachment body", encoding="utf-8")

    result = json.loads(
      module.google_workspace_gmail_send_tool(
        {
          "to": "to@example.test",
          "cc": "cc@example.test",
          "bcc": "bcc@example.test",
          "from_header": "Joy <joy@example.test>",
          "subject": "Attachment test",
          "body": "Plain body",
          "thread_id": "existing-thread",
          "attachments": [
            {
              "path": str(attachment),
              "filename": "renamed.txt",
              "mime_type": "text/plain",
            }
          ],
          "idempotency_key": "attachment-test-1",
        }
      )
    )

    assert result["message_id"] == "message-123"
    assert result["thread_id"] == "thread-456"
    assert result["idempotency_key"] == "attachment-test-1"
    assert service.messages_api.executables[0].num_retries == 0
    request = service.messages_api.calls[0]
    assert request["userId"] == "me"
    assert request["body"]["threadId"] == "existing-thread"
    raw = base64.urlsafe_b64decode(request["body"]["raw"] + "==")
    message = BytesParser(policy=policy.default).parsebytes(raw)
    assert message["To"] == "to@example.test"
    assert message["Cc"] == "cc@example.test"
    assert message["Bcc"] == "bcc@example.test"
    assert message["From"] == "Joy <joy@example.test>"
    assert message["Subject"] == "Attachment test"
    assert message["In-Reply-To"] == "<previous@example.test>"
    assert message["References"] == "<root@example.test> <previous@example.test>"
    assert service.threads_api.calls == [
      {"userId": "me", "id": "existing-thread", "format": "metadata"}
    ]
    plain_body = message.get_body(preferencelist=("plain",))
    assert plain_body is not None
    assert plain_body.get_content() == "Plain body\n"
    sent_attachment = next(message.iter_attachments())
    assert sent_attachment.get_filename() == "renamed.txt"
    assert sent_attachment.get_content_type() == "text/plain"
    assert sent_attachment.get_payload(decode=True) == b"attachment body"


def test_auto_detects_attachment_mime_type_and_preserves_html_body() -> None:
  with tempfile.TemporaryDirectory() as tmpdir:
    tmp_path = Path(tmpdir)
    service = FakeService()
    module = load_tool_module(tmp_path, service)
    (tmp_path / "google_token.json").write_text(
      json.dumps({"scopes": [module.GMAIL_SEND_SCOPE]}),
      encoding="utf-8",
    )
    attachment = tmp_path / "downloads/google-workspace/data.json"
    attachment.parent.mkdir(parents=True)
    attachment.write_text('{"ok": true}', encoding="utf-8")

    result = json.loads(
      module.google_workspace_gmail_send_tool(
        {
          "to": "to@example.test",
          "subject": "Auto MIME",
          "body": "<strong>Hello</strong>",
          "html": True,
          "attachments": [{"path": str(attachment)}],
        }
      )
    )

    assert result["message_id"] == "message-123"
    request = service.messages_api.calls[0]
    raw = base64.urlsafe_b64decode(request["body"]["raw"] + "==")
    message = BytesParser(policy=policy.default).parsebytes(raw)
    html_body = message.get_body(preferencelist=("html",))
    assert html_body is not None
    assert html_body.get_content() == "<strong>Hello</strong>\n"
    sent_attachment = next(message.iter_attachments())
    assert sent_attachment.get_filename() == "data.json"
    assert sent_attachment.get_content_type() == "application/json"


def test_rejects_thread_subject_mismatch_before_send() -> None:
  with tempfile.TemporaryDirectory() as tmpdir:
    tmp_path = Path(tmpdir)
    service = FakeService(thread_subject="Original subject")
    module = load_tool_module(tmp_path, service)
    (tmp_path / "google_token.json").write_text(
      json.dumps({"scopes": [module.GMAIL_SEND_SCOPE]}),
      encoding="utf-8",
    )

    result = json.loads(
      module.google_workspace_gmail_send_tool(
        {
          "to": "to@example.test",
          "subject": "Different subject",
          "body": "No send",
          "thread_id": "existing-thread",
          "idempotency_key": "thread-subject-mismatch",
        }
      )
    )

    assert result["error"] == "THREAD_SUBJECT_MISMATCH"
    assert service.messages_api.calls == []


def test_same_idempotency_key_returns_recorded_result_without_resending() -> None:
  with tempfile.TemporaryDirectory() as tmpdir:
    tmp_path = Path(tmpdir)
    service = FakeService()
    module = load_tool_module(tmp_path, service)
    (tmp_path / "google_token.json").write_text(
      json.dumps({"scopes": [module.GMAIL_SEND_SCOPE]}),
      encoding="utf-8",
    )
    args = {
      "to": "to@example.test",
      "subject": "Exactly once",
      "body": "Only one copy",
      "idempotency_key": "same-request",
    }

    first = json.loads(module.google_workspace_gmail_send_tool(args))
    second = json.loads(module.google_workspace_gmail_send_tool(args))

    assert first["message_id"] == "message-123"
    assert second == {
      "message_id": "message-123",
      "thread_id": "thread-456",
      "idempotency_key": "same-request",
      "duplicate_suppressed": True,
    }
    assert len(service.messages_api.calls) == 1


def test_reports_known_gmail_rejection_as_safe_retryable_error() -> None:
  with tempfile.TemporaryDirectory() as tmpdir:
    tmp_path = Path(tmpdir)
    service = FakeService(error_status=400)
    module = load_tool_module(tmp_path, service)
    (tmp_path / "google_token.json").write_text(
      json.dumps({"scopes": [module.GMAIL_SEND_SCOPE]}),
      encoding="utf-8",
    )

    result = json.loads(
      module.google_workspace_gmail_send_tool(
        {
          "to": "to@example.test",
          "subject": "Rejected",
          "body": "Known failure",
          "idempotency_key": "known-rejection",
        }
      )
    )

    assert result == {
      "error": "GMAIL_REJECTED",
      "message": "Gmail rejected the message before accepting it. Correct the message and use a new idempotency_key.",
      "http_status": 400,
      "idempotency_key": "known-rejection",
    }
    assert "secret response body" not in json.dumps(result)


def test_rejects_malformed_attachment_input_before_any_send() -> None:
  with tempfile.TemporaryDirectory() as tmpdir:
    tmp_path = Path(tmpdir)
    service = FakeService()
    module = load_tool_module(tmp_path, service)
    (tmp_path / "google_token.json").write_text(
      json.dumps({"scopes": [module.GMAIL_SEND_SCOPE]}),
      encoding="utf-8",
    )

    result = json.loads(
      module.google_workspace_gmail_send_tool(
        {
          "to": "to@example.test",
          "subject": "Malformed",
          "body": "No send",
          "attachments": ["not-an-object"],
        }
      )
    )

    assert result == {
      "error": "INVALID_ATTACHMENTS",
      "message": "attachments must be an array of objects with a path field.",
    }
    assert service.messages_api.calls == []


def test_missing_attachment_returns_actionable_error_before_send() -> None:
  with tempfile.TemporaryDirectory() as tmpdir:
    tmp_path = Path(tmpdir)
    service = FakeService()
    module = load_tool_module(tmp_path, service)
    (tmp_path / "google_token.json").write_text(
      json.dumps({"scopes": [module.GMAIL_SEND_SCOPE]}),
      encoding="utf-8",
    )
    missing = tmp_path / "downloads/google-workspace/missing.pdf"

    result = json.loads(
      module.google_workspace_gmail_send_tool(
        {
          "to": "to@example.test",
          "subject": "Missing",
          "body": "No send",
          "attachments": [{"path": str(missing)}],
        }
      )
    )

    assert result == {
      "error": "ATTACHMENT_NOT_FOUND",
      "message": "Attachment path does not exist or cannot be read.",
    }
    assert service.messages_api.calls == []


def test_rejects_attachment_outside_profile_home() -> None:
  with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as outside_dir:
    tmp_path = Path(tmpdir)
    service = FakeService()
    module = load_tool_module(tmp_path, service)
    (tmp_path / "google_token.json").write_text(
      json.dumps({"scopes": [module.GMAIL_SEND_SCOPE]}),
      encoding="utf-8",
    )
    outside = Path(outside_dir) / "outside.txt"
    outside.write_text("outside", encoding="utf-8")

    result = json.loads(
      module.google_workspace_gmail_send_tool(
        {
          "to": "to@example.test",
          "subject": "Outside",
          "body": "No send",
          "attachments": [{"path": str(outside)}],
        }
      )
    )

    assert result["error"] == "UNSUPPORTED_ATTACHMENT_PATH"
    assert "downloads/google-workspace" in result["message"]
    assert service.messages_api.calls == []


def test_rejects_profile_credentials_as_attachments() -> None:
  for credential_name in ("google_token.json", "google_client_secret.json"):
    with tempfile.TemporaryDirectory() as tmpdir:
      tmp_path = Path(tmpdir)
      service = FakeService()
      module = load_tool_module(tmp_path, service)
      (tmp_path / "google_token.json").write_text(
        json.dumps({"scopes": [module.GMAIL_SEND_SCOPE]}),
        encoding="utf-8",
      )
      credential = tmp_path / credential_name
      if credential_name != "google_token.json":
        credential.write_text('{"client_secret": "must-not-send"}', encoding="utf-8")

      result = json.loads(
        module.google_workspace_gmail_send_tool(
          {
            "to": "to@example.test",
            "subject": "Credential exfiltration",
            "body": "No send",
            "attachments": [{"path": str(credential)}],
          }
        )
      )

      assert result["error"] == "UNSUPPORTED_ATTACHMENT_PATH"
      assert service.messages_api.calls == []


def test_rejects_hard_linked_profile_credentials_as_attachments() -> None:
  with tempfile.TemporaryDirectory() as tmpdir:
    tmp_path = Path(tmpdir)
    service = FakeService()
    module = load_tool_module(tmp_path, service)
    credential = tmp_path / "google_token.json"
    credential.write_text(
      json.dumps({"scopes": [module.GMAIL_SEND_SCOPE], "token": "must-not-send"}),
      encoding="utf-8",
    )
    attachment = tmp_path / "downloads/google-workspace/token.txt"
    attachment.parent.mkdir(parents=True)
    os.link(credential, attachment)

    result = json.loads(
      module.google_workspace_gmail_send_tool(
        {
          "to": "to@example.test",
          "subject": "Hard-link credential exfiltration",
          "body": "No send",
          "attachments": [{"path": str(attachment)}],
        }
      )
    )

    assert result["error"] == "UNSUPPORTED_ATTACHMENT_PATH"
    assert service.messages_api.calls == []


def test_rejects_attachment_replaced_after_validation() -> None:
  with tempfile.TemporaryDirectory() as tmpdir:
    tmp_path = Path(tmpdir)
    service = FakeService()
    module = load_tool_module(tmp_path, service)
    (tmp_path / "google_token.json").write_text(
      json.dumps({"scopes": [module.GMAIL_SEND_SCOPE]}),
      encoding="utf-8",
    )
    attachment = tmp_path / "downloads/google-workspace/race.txt"
    attachment.parent.mkdir(parents=True)
    attachment.write_text("safe content", encoding="utf-8")
    secret = tmp_path / "google_client_secret.json"
    secret.write_text('{"client_secret": "must-not-send"}', encoding="utf-8")
    validate = module._gmail_send_attachment

    def validate_then_swap(item: dict[str, Any]):
      metadata = validate(item)
      attachment.unlink()
      attachment.symlink_to(secret)
      return metadata

    with patch.object(module, "_gmail_send_attachment", side_effect=validate_then_swap):
      result = json.loads(
        module.google_workspace_gmail_send_tool(
          {
            "to": "to@example.test",
            "subject": "Race",
            "body": "No send",
            "attachments": [{"path": str(attachment)}],
          }
        )
      )

    assert result["error"] == "ATTACHMENT_CHANGED"
    assert service.messages_api.calls == []


def test_rejects_attachments_over_safe_aggregate_limit() -> None:
  with tempfile.TemporaryDirectory() as tmpdir:
    tmp_path = Path(tmpdir)
    service = FakeService()
    module = load_tool_module(tmp_path, service)
    setattr(module, "MAX_GMAIL_SEND_ATTACHMENT_BYTES", 3)
    (tmp_path / "google_token.json").write_text(
      json.dumps({"scopes": [module.GMAIL_SEND_SCOPE]}),
      encoding="utf-8",
    )
    attachment = tmp_path / "downloads/google-workspace/large.bin"
    attachment.parent.mkdir(parents=True)
    attachment.write_bytes(b"1234")

    with patch.object(Path, "read_bytes", side_effect=AssertionError("oversize attachment was read")):
      result = json.loads(
        module.google_workspace_gmail_send_tool(
          {
            "to": "to@example.test",
            "subject": "Large",
            "body": "No send",
            "attachments": [{"path": str(attachment)}],
          }
        )
      )

    assert result["error"] == "ATTACHMENTS_TOO_LARGE"
    assert result["size"] == 4
    assert result["max_size"] == 3
    assert service.messages_api.calls == []


def test_reports_profile_oauth_failure_without_exposing_provider_body() -> None:
  with tempfile.TemporaryDirectory() as tmpdir:
    tmp_path = Path(tmpdir)
    service = FakeService(error_status=401)
    module = load_tool_module(tmp_path, service)
    (tmp_path / "google_token.json").write_text(
      json.dumps({"scopes": [module.GMAIL_SEND_SCOPE]}),
      encoding="utf-8",
    )

    serialized = module.google_workspace_gmail_send_tool(
      {
        "to": "to@example.test",
        "subject": "Auth",
        "body": "Known failure",
        "idempotency_key": "auth-failure",
      }
    )
    result = json.loads(serialized)

    assert result["error"] == "AUTHENTICATION_FAILED"
    assert result["http_status"] == 401
    assert "profile's OAuth grant" in result["message"]
    assert "secret response body" not in serialized


def test_rate_limit_and_forbidden_responses_preserve_unknown_outcome() -> None:
  for status in (403, 429):
    with tempfile.TemporaryDirectory() as tmpdir:
      tmp_path = Path(tmpdir)
      service = FakeService(error_status=status)
      module = load_tool_module(tmp_path, service)
      (tmp_path / "google_token.json").write_text(
        json.dumps({"scopes": [module.GMAIL_SEND_SCOPE]}),
        encoding="utf-8",
      )
      args = {
        "to": "to@example.test",
        "subject": f"Ambiguous HTTP {status}",
        "body": "Do not duplicate",
        "idempotency_key": f"ambiguous-http-{status}",
      }

      first = json.loads(module.google_workspace_gmail_send_tool(args))
      second = json.loads(module.google_workspace_gmail_send_tool(args))

      assert first["error"] == "UNKNOWN_SEND_OUTCOME"
      assert first["http_status"] == status
      assert second["error"] == "UNKNOWN_SEND_OUTCOME"
      assert len(service.messages_api.calls) == 1


def test_unknown_outcome_is_never_automatically_resent() -> None:
  with tempfile.TemporaryDirectory() as tmpdir:
    tmp_path = Path(tmpdir)
    service = FakeService(error_status=500)
    module = load_tool_module(tmp_path, service)
    (tmp_path / "google_token.json").write_text(
      json.dumps({"scopes": [module.GMAIL_SEND_SCOPE]}),
      encoding="utf-8",
    )
    args = {
      "to": "to@example.test",
      "subject": "Ambiguous",
      "body": "Do not duplicate",
      "idempotency_key": "ambiguous-send",
    }

    first = json.loads(module.google_workspace_gmail_send_tool(args))
    second = json.loads(module.google_workspace_gmail_send_tool(args))

    assert first["error"] == "UNKNOWN_SEND_OUTCOME"
    assert second["error"] == "UNKNOWN_SEND_OUTCOME"
    assert second["idempotency_key"] == "ambiguous-send"
    assert len(service.messages_api.calls) == 1


def test_missing_send_response_ids_preserves_unknown_outcome() -> None:
  with tempfile.TemporaryDirectory() as tmpdir:
    tmp_path = Path(tmpdir)
    service = FakeService()
    module = load_tool_module(tmp_path, service)
    (tmp_path / "google_token.json").write_text(
      json.dumps({"scopes": [module.GMAIL_SEND_SCOPE]}),
      encoding="utf-8",
    )

    def send_without_ids(**kwargs: Any) -> SendExecutable:
      service.messages_api.calls.append(kwargs)
      executable = SendExecutable({})
      service.messages_api.executables.append(executable)
      return executable

    service.messages_api.send = send_without_ids  # type: ignore[method-assign]
    args = {
      "to": "to@example.test",
      "subject": "Missing response IDs",
      "body": "Do not duplicate",
      "idempotency_key": "missing-response-ids",
    }

    first = json.loads(module.google_workspace_gmail_send_tool(args))
    second = json.loads(module.google_workspace_gmail_send_tool(args))

    assert first["error"] == "UNKNOWN_SEND_OUTCOME"
    assert "message ID and thread ID" in first["message"]
    assert second["error"] == "UNKNOWN_SEND_OUTCOME"
    assert len(service.messages_api.calls) == 1


def test_client_load_failure_has_actionable_non_thread_message() -> None:
  with tempfile.TemporaryDirectory() as tmpdir:
    tmp_path = Path(tmpdir)
    module = load_tool_module(tmp_path, FakeService())
    (tmp_path / "google_token.json").write_text(
      json.dumps({"scopes": [module.GMAIL_SEND_SCOPE]}),
      encoding="utf-8",
    )

    with patch.object(module, "_gmail_service", side_effect=RuntimeError("provider secret")):
      serialized = module.google_workspace_gmail_send_tool(
        {
          "to": "to@example.test",
          "subject": "Client failure",
          "body": "No send",
          "idempotency_key": "client-load-failure",
        }
      )
    result = json.loads(serialized)

    assert result["error"] == "GMAIL_CLIENT_FAILED"
    assert "profile-scoped Gmail client could not be loaded" in result["message"]
    assert "thread metadata" not in result["message"]
    assert "provider secret" not in serialized


def test_idempotency_key_cannot_be_reused_for_different_content() -> None:
  with tempfile.TemporaryDirectory() as tmpdir:
    tmp_path = Path(tmpdir)
    service = FakeService()
    module = load_tool_module(tmp_path, service)
    (tmp_path / "google_token.json").write_text(
      json.dumps({"scopes": [module.GMAIL_SEND_SCOPE]}),
      encoding="utf-8",
    )
    common = {
      "to": "to@example.test",
      "subject": "Stable key",
      "idempotency_key": "one-binding",
    }

    first = json.loads(module.google_workspace_gmail_send_tool({**common, "body": "first"}))
    second = json.loads(module.google_workspace_gmail_send_tool({**common, "body": "changed"}))

    assert first["message_id"] == "message-123"
    assert second["error"] == "IDEMPOTENCY_KEY_REUSED"
    assert len(service.messages_api.calls) == 1


def test_rejects_thread_subject_mismatch_before_reserving_or_sending() -> None:
  with tempfile.TemporaryDirectory() as tmpdir:
    tmp_path = Path(tmpdir)
    service = FakeService(thread_subject="Original subject")
    module = load_tool_module(tmp_path, service)
    (tmp_path / "google_token.json").write_text(
      json.dumps({"scopes": [module.GMAIL_SEND_SCOPE]}),
      encoding="utf-8",
    )
    common = {
      "to": "to@example.test",
      "body": "Thread reply",
      "thread_id": "existing-thread",
      "idempotency_key": "thread-subject-check",
    }

    rejected = json.loads(
      module.google_workspace_gmail_send_tool({**common, "subject": "Different subject"})
    )
    accepted = json.loads(
      module.google_workspace_gmail_send_tool({**common, "subject": "Original subject"})
    )

    assert rejected["error"] == "THREAD_SUBJECT_MISMATCH"
    assert rejected["thread_subject"] == "Original subject"
    assert accepted["message_id"] == "message-123"
    assert len(service.messages_api.calls) == 1


def test_invalid_header_does_not_poison_idempotency_key() -> None:
  with tempfile.TemporaryDirectory() as tmpdir:
    tmp_path = Path(tmpdir)
    service = FakeService()
    module = load_tool_module(tmp_path, service)
    (tmp_path / "google_token.json").write_text(
      json.dumps({"scopes": [module.GMAIL_SEND_SCOPE]}),
      encoding="utf-8",
    )
    common = {
      "subject": "Header validation",
      "body": "No poisoned reservation",
      "idempotency_key": "header-validation",
    }

    rejected = json.loads(
      module.google_workspace_gmail_send_tool(
        {**common, "to": "to@example.test\nBcc: injected@example.test"}
      )
    )
    accepted = json.loads(
      module.google_workspace_gmail_send_tool({**common, "to": "to@example.test"})
    )

    assert rejected["error"] == "INVALID_MESSAGE_HEADERS"
    assert accepted["message_id"] == "message-123"
    assert len(service.messages_api.calls) == 1


def test_gmail_service_does_not_reuse_another_profiles_cached_google_api() -> None:
  with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
    cached_helper = types.ModuleType("_hermes_home")
    setattr(cached_helper, "SERVICE", "wrong-cached-profile-service")
    original_helper = sys.modules.get("_hermes_home")
    sys.modules["_hermes_home"] = cached_helper
    modules = []
    original_path = sys.path.copy()
    try:
      for profile_home, service_name in (
        (Path(first_dir), "first-profile-service"),
        (Path(second_dir), "second-profile-service"),
      ):
        module = load_tool_module(profile_home, FakeService())
        scripts = profile_home / "skills/productivity/google-workspace/scripts"
        (scripts / "_hermes_home.py").write_text(f"SERVICE = {service_name!r}\n", encoding="utf-8")
        (scripts / "google_api.py").write_text(
          "from _hermes_home import SERVICE\n"
          "def build_service(*_args, **_kwargs):\n"
          "  return SERVICE\n",
          encoding="utf-8",
        )
        modules.append(module)

      assert modules[0]._gmail_service() == "first-profile-service"
      assert modules[1]._gmail_service() == "second-profile-service"
      assert sys.path == original_path
      assert sys.modules["_hermes_home"] is cached_helper
    finally:
      if original_helper is None:
        sys.modules.pop("_hermes_home", None)
      else:
        sys.modules["_hermes_home"] = original_helper


if __name__ == "__main__":
  test_send_schema_exposes_attachment_and_existing_message_fields()
  test_sends_multipart_attachment_with_all_headers_and_returns_ids()
  test_auto_detects_attachment_mime_type_and_preserves_html_body()
  test_rejects_thread_subject_mismatch_before_send()
  test_same_idempotency_key_returns_recorded_result_without_resending()
  test_reports_known_gmail_rejection_as_safe_retryable_error()
  test_rejects_malformed_attachment_input_before_any_send()
  test_missing_attachment_returns_actionable_error_before_send()
  test_rejects_attachment_outside_profile_home()
  test_rejects_profile_credentials_as_attachments()
  test_rejects_hard_linked_profile_credentials_as_attachments()
  test_rejects_attachment_replaced_after_validation()
  test_rejects_attachments_over_safe_aggregate_limit()
  test_reports_profile_oauth_failure_without_exposing_provider_body()
  test_rate_limit_and_forbidden_responses_preserve_unknown_outcome()
  test_unknown_outcome_is_never_automatically_resent()
  test_missing_send_response_ids_preserves_unknown_outcome()
  test_client_load_failure_has_actionable_non_thread_message()
  test_idempotency_key_cannot_be_reused_for_different_content()
  test_rejects_thread_subject_mismatch_before_reserving_or_sending()
  test_invalid_header_does_not_poison_idempotency_key()
  test_gmail_service_does_not_reuse_another_profiles_cached_google_api()
