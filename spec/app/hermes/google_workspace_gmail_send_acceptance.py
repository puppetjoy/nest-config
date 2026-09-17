#!/usr/bin/env python3
"""Controlled live acceptance test for profile-scoped Gmail attachment sending.

This script intentionally requires both --confirm-send and an explicit recipient.
It sends exactly one small, uniquely named text attachment, then reads the sent
message back and verifies the SENT label plus attachment filename, MIME type,
and size. It never prints OAuth material.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any


def load_tool(path: Path):
  spec = importlib.util.spec_from_file_location("google_workspace_tool_acceptance", path)
  if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot load Google Workspace tool from {path}")
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--confirm-send", action="store_true", help="Required acknowledgement that this test sends one real email")
  parser.add_argument("--recipient", required=True, help="Controlled recipient address, normally the authenticated account")
  parser.add_argument("--profile-home", type=Path, required=True, help="Hermes profile home containing google_token.json")
  parser.add_argument(
    "--tool-path",
    type=Path,
    default=Path("/opt/hermes-agent/src/tools/google_workspace_tool.py"),
    help="Deployed google_workspace_tool.py to exercise",
  )
  parser.add_argument("--poll-seconds", type=int, default=30, help="Maximum read-back wait; defaults to 30 seconds")
  args = parser.parse_args()
  if not args.confirm_send:
    parser.error("--confirm-send is required because this test sends one real email")
  if not args.profile_home.is_absolute():
    parser.error("--profile-home must be absolute")

  os.environ["HERMES_HOME"] = str(args.profile_home)
  module = load_tool(args.tool_path)
  nonce = secrets.token_hex(8)
  content = f"Hermes Gmail attachment acceptance {nonce}\n".encode("utf-8")
  attachment_dir = args.profile_home / "downloads/google-workspace/acceptance"
  attachment_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
  attachment_path = attachment_dir / f"gmail-attachment-acceptance-{nonce}.txt"
  attachment_path.write_bytes(content)
  os.chmod(attachment_path, 0o600)
  idempotency_key = f"gmail-attachment-acceptance-{nonce}"

  try:
    result = json.loads(
      module.google_workspace_gmail_send_tool(
        {
          "to": args.recipient,
          "subject": f"[controlled acceptance] Gmail attachment {nonce}",
          "body": "Controlled non-production verification of first-class Gmail attachment sending.",
          "attachments": [{"path": str(attachment_path)}],
          "idempotency_key": idempotency_key,
        }
      )
    )
    if result.get("error"):
      raise RuntimeError(json.dumps(result, ensure_ascii=False))
    message_id = str(result.get("message_id") or "")
    thread_id = str(result.get("thread_id") or "")
    if not message_id or not thread_id:
      raise RuntimeError("send result did not include message_id and thread_id")

    deadline = time.monotonic() + max(1, args.poll_seconds)
    message: dict[str, Any] | None = None
    while time.monotonic() < deadline:
      candidate = module._gmail_message(module._gmail_service(), message_id)
      if "SENT" in candidate.get("labelIds", []):
        message = candidate
        break
      time.sleep(1)
    if message is None:
      raise RuntimeError("sent message was not readable with the SENT label before the acceptance timeout")

    attachments = module._attachment_metadata(message.get("payload") or {})
    expected_name = attachment_path.name
    metadata = next((item for item in attachments if item.get("filename") == expected_name), None)
    if metadata is None:
      raise RuntimeError("sent message did not expose the expected attachment metadata")
    if metadata.get("mime_type") != "text/plain":
      raise RuntimeError(f"unexpected attachment MIME type: {metadata.get('mime_type')}")
    if metadata.get("size") != len(content):
      raise RuntimeError(f"unexpected attachment size: {metadata.get('size')} != {len(content)}")

    print(
      json.dumps(
        {
          "ok": True,
          "message_id": message_id,
          "thread_id": thread_id,
          "labels": message.get("labelIds", []),
          "attachment": {
            "filename": metadata["filename"],
            "mime_type": metadata["mime_type"],
            "size": metadata["size"],
          },
        },
        ensure_ascii=False,
      )
    )
    return 0
  finally:
    attachment_path.unlink(missing_ok=True)


if __name__ == "__main__":
  raise SystemExit(main())
