#!/usr/bin/env python3
"""Hermes command-provider wrapper for the Nest voice-speech TTS endpoint."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


DEFAULT_SPEECH_PATH = "/v1/audio/speech"

_DIGIT_WORDS = {
    "0": "zero",
    "1": "one",
    "2": "two",
    "3": "three",
    "4": "four",
    "5": "five",
    "6": "six",
    "7": "seven",
    "8": "eight",
    "9": "nine",
}

# Kokoro benefits from human-readable Nest spellings more than raw acronyms.
# Keep this table small and operational so ordinary prose remains natural.
_PRONUNCIATION_REPLACEMENTS = (
    (re.compile(r"\bKubeCM\b"), "cube see em"),
    (re.compile(r"\bkubectl\b"), "cube control"),
    (re.compile(r"\bllama-qwen\b", re.IGNORECASE), "llama qwen"),
    (re.compile(r"\bEyrie\b"), "airy"),
    (re.compile(r"\bOpenVox\b"), "open vox"),
    (re.compile(r"\bROCm\b"), "rock em"),
)


def _endpoint_url(endpoint: str) -> str:
    parsed = urllib.parse.urlparse(endpoint)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"endpoint must be an absolute URL: {endpoint!r}")
    if parsed.path.rstrip("/").endswith(DEFAULT_SPEECH_PATH):
        return endpoint
    return urllib.parse.urljoin(endpoint.rstrip("/") + "/", DEFAULT_SPEECH_PATH.lstrip("/"))


def _spell_chars(value: str) -> str:
    words: list[str] = []
    for char in value:
        if char.isdigit():
            words.append(_DIGIT_WORDS[char])
        elif char.isalpha():
            words.append(char.upper())
        elif char == "-":
            words.append("dash")
        elif char == "_":
            words.append("underscore")
        elif char == ".":
            words.append("dot")
        elif char == "/":
            words.append("slash")
    return " ".join(words)


def _normalize_url(match: re.Match[str]) -> str:
    url = match.group(0)
    suffix = ""
    while url.endswith((".", ",", ";", ":", "!", "?")):
        suffix = url[-1] + suffix
        url = url[:-1]
    spoken = re.sub(r"^https://", "H T T P S link ", url, flags=re.IGNORECASE)
    spoken = re.sub(r"^http://", "H T T P link ", spoken, flags=re.IGNORECASE)
    spoken = spoken.replace("/", " slash ")
    spoken = spoken.replace(".", " dot ")
    spoken = spoken.replace("-", " dash ")
    spoken = spoken.replace("_", " underscore ")
    spoken = re.sub(r"\s+", " ", spoken).strip()
    return f"{spoken}{suffix}"


def _normalize_path(match: re.Match[str]) -> str:
    path = match.group(0)
    suffix = ""
    while path.endswith((".", ",", ";", ":")):
        suffix = path[-1] + suffix
        path = path[:-1]
    spoken = path.replace("/", " slash ").replace("-", " dash ").replace("_", " underscore ")
    spoken = re.sub(r"\s+", " ", spoken).strip()
    return f"path {spoken}{suffix}"


def _normalize_pause_punctuation(text: str) -> str:
    """Add Kokoro-friendly pauses for list labels without changing visible text."""
    # Kokoro tends to run label-style colons into the following word. A speech-
    # only period gives a reliable phrase boundary while keeping identifiers,
    # URLs, times, and ratios intact.
    text = re.sub(r"(?<!\d):\s+(?=[A-Za-z])", ". ", text)
    text = re.sub(r";\s+(?=[A-Za-z])", ". ", text)
    return text


def normalize_tts_text(text: str) -> str:
    """Return a speech-only rendering for operational Hermes notifications."""
    normalized = text
    normalized = re.sub(r"https?://[^\s)>,]+", _normalize_url, normalized)
    normalized = re.sub(
        r"\b((?:agent request|request)\s+)?ar-([0-9]{8})-([0-9]{6})-([0-9a-fA-F]{6})\b",
        lambda m: f"{m.group(1) or 'agent request '}A R, {_spell_chars(m.group(2))}, {_spell_chars(m.group(3))}, {_spell_chars(m.group(4))}",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"\b(task\s+)?t_([0-9a-fA-F]{8})\b",
        lambda m: f"{m.group(1) or 'task '}T, {_spell_chars(m.group(2))}",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"\b(commit|sha|hash)\s+([0-9a-fA-F]{7,40})\b",
        lambda m: f"{m.group(1)} {_spell_chars(m.group(2))}",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(r"(?<!\w)/(?:[A-Za-z0-9._-]+/?)+", _normalize_path, normalized)
    for pattern, replacement in _PRONUNCIATION_REPLACEMENTS:
        normalized = pattern.sub(replacement, normalized)
    normalized = _normalize_pause_punctuation(normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _request(args: argparse.Namespace) -> tuple[bytes, dict[str, str], float]:
    input_path = Path(args.text_file).expanduser().resolve()
    if not input_path.exists():
        raise FileNotFoundError(input_path)
    text = normalize_tts_text(input_path.read_text(encoding="utf-8"))
    try:
        speed = float(args.speed)
    except ValueError:
        speed = 1.0
    payload = {
        "input": text,
        "model": args.model,
        "voice": args.voice,
        "response_format": args.format.lstrip("."),
        "speed": speed,
        # The wrapper owns Hermes notification normalization so service-side
        # normalization does not re-spell already-expanded identifiers.
        "normalize": False,
    }
    request = urllib.request.Request(
        _endpoint_url(args.endpoint),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "audio/*",
            "User-Agent": "hermes-voice-speech-tts/1.0",
        },
        method="POST",
    )
    start = time.monotonic()
    with urllib.request.urlopen(request, timeout=args.timeout) as response:
        body = response.read()
        headers = {key.lower(): value for key, value in response.headers.items()}
    return body, headers, time.monotonic() - start


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True, help="voice-speech base URL or /v1/audio/speech URL")
    parser.add_argument("--text-file", required=True, help="UTF-8 text input path")
    parser.add_argument("--output", required=True, help="audio output path")
    parser.add_argument("--voice", required=True, help="Kokoro voice id")
    parser.add_argument("--model", default="kokoro")
    parser.add_argument("--format", default="wav")
    parser.add_argument("--speed", default="1.0")
    parser.add_argument("--timeout", type=float, default=60.0)
    return parser


def main() -> int:
    args = _parser().parse_args()
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        body, headers, elapsed = _request(args)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"voice-speech TTS HTTP {exc.code}: {detail}", file=sys.stderr)
        return 1
    except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
        print(f"hermes-voice-speech-tts: {exc}", file=sys.stderr)
        return 1
    if not body:
        print("voice-speech TTS returned an empty response", file=sys.stderr)
        return 1
    output.write_bytes(body)
    if headers:
        stats = ", ".join(
            f"{key}={value}"
            for key, value in sorted(headers.items())
            if key.startswith("x-nest-tts-")
        )
        if stats:
            print(f"voice-speech TTS completed in {elapsed:.3f}s ({stats})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
