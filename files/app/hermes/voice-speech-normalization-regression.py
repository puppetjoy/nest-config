#!/usr/bin/env python3
"""Offline regression check for Nest voice-speech speech normalization.

This deliberately tests only the Nest wrapper's direct-call fallback policy. The
canonical behavior classes live in voice-speech-normalization-corpus.json and
should be mirrored by Hermes and agent-request-broker tests in their own repos.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
CORPUS = HERE / "voice-speech-normalization-corpus.json"
WRAPPER = HERE / "voice-speech-tts-command.py"


def load_wrapper():
    spec = importlib.util.spec_from_file_location("voice_speech_tts_command", WRAPPER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {WRAPPER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    wrapper = load_wrapper()
    failures: list[str] = []
    for case in corpus["cases"]:
        actual = wrapper.normalize_tts_text(case["input"])
        expected = case["expected"]
        if actual != expected:
            failures.append(
                f"{case['id']}: expected {expected!r}, got {actual!r}"
            )
    if failures:
        print("voice-speech normalization regressions:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print(f"ok: {len(corpus['cases'])} voice-speech normalization cases passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
