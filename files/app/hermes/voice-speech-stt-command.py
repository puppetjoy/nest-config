#!/usr/bin/env python3
"""Hermes command-provider wrapper for the Nest voice-speech STT endpoint."""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Iterable


DEFAULT_TRANSCRIPT_PATH = "/v1/audio/transcriptions"


def _endpoint_url(endpoint: str) -> str:
    parsed = urllib.parse.urlparse(endpoint)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"endpoint must be an absolute URL: {endpoint!r}")
    if parsed.path.rstrip("/").endswith("/v1/audio/transcriptions"):
        return endpoint
    return urllib.parse.urljoin(endpoint.rstrip("/") + "/", DEFAULT_TRANSCRIPT_PATH.lstrip("/"))


def _field_part(boundary: str, name: str, value: object) -> bytes:
    return (
        f"--{boundary}\r\n"
        f"Content-Disposition: form-data; name=\"{name}\"\r\n\r\n"
        f"{value}\r\n"
    ).encode("utf-8")


def _file_part(boundary: str, name: str, path: Path) -> bytes:
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    header = (
        f"--{boundary}\r\n"
        f"Content-Disposition: form-data; name=\"{name}\"; filename=\"{path.name}\"\r\n"
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8")
    return header + path.read_bytes() + b"\r\n"


def _multipart_body(fields: Iterable[tuple[str, object]], file_path: Path) -> tuple[bytes, str]:
    boundary = f"hermes-voice-speech-{uuid.uuid4().hex}"
    body = b"".join(_field_part(boundary, name, value) for name, value in fields)
    body += _file_part(boundary, "file", file_path)
    body += f"--{boundary}--\r\n".encode("ascii")
    return body, boundary


def _request(args: argparse.Namespace) -> dict:
    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        raise FileNotFoundError(input_path)

    fields: list[tuple[str, object]] = [
        ("model", args.model),
        ("language", args.language),
        ("temperature", args.temperature),
        ("condition_on_previous_text", str(args.condition_on_previous_text).lower()),
    ]
    if args.initial_prompt:
        fields.append(("initial_prompt", args.initial_prompt))

    body, boundary = _multipart_body(fields, input_path)
    request = urllib.request.Request(
        _endpoint_url(args.endpoint),
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json",
            "User-Agent": "hermes-voice-speech-stt/1.0",
        },
        method="POST",
    )
    start = time.monotonic()
    with urllib.request.urlopen(request, timeout=args.timeout) as response:
        payload = response.read()
        status = response.status
    elapsed = time.monotonic() - start
    try:
        data = json.loads(payload.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"voice-speech returned non-JSON response after {elapsed:.3f}s: {exc}") from exc
    data.setdefault("_hermes_voice_speech_status", status)
    data.setdefault("_hermes_voice_speech_elapsed_seconds", elapsed)
    return data


def _write_output(args: argparse.Namespace, data: dict) -> None:
    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_format = args.format.lower().lstrip(".")
    if output_format == "json":
        output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return
    text = data.get("text") or data.get("transcript")
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError(f"voice-speech response did not include transcript text: {data!r}")
    output_path.write_text(text.strip() + "\n", encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True, help="voice-speech base URL or /v1/audio/transcriptions URL")
    parser.add_argument("--input", required=True, help="audio file to transcribe")
    parser.add_argument("--output", required=True, help="transcript output path")
    parser.add_argument("--model", default="whisper-large-v3-turbo")
    parser.add_argument("--language", default="en")
    parser.add_argument("--format", default="txt", choices=("txt", "json"))
    parser.add_argument("--initial-prompt", default="")
    parser.add_argument("--temperature", default="0.0")
    parser.add_argument("--condition-on-previous-text", action="store_true")
    parser.add_argument("--timeout", type=float, default=300.0)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        data = _request(args)
        _write_output(args, data)
    except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
        print(f"hermes-voice-speech-stt: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
