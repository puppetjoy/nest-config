#!/usr/bin/env python3
"""Hermes command-provider wrapper for Nest's local Chatterbox TTS API."""

import argparse
import json
import re
import sys
from pathlib import Path
from urllib import error, request


_DIGIT_WORDS = {
    '0': 'zero',
    '1': 'one',
    '2': 'two',
    '3': 'three',
    '4': 'four',
    '5': 'five',
    '6': 'six',
    '7': 'seven',
    '8': 'eight',
    '9': 'nine',
}

# Operational words that Chatterbox tends to blend, acronymize, or pronounce as
# ordinary English. Keep this table small and Nest-specific so notification
# speech improves without making arbitrary prose sound robotic.
_PRONUNCIATION_REPLACEMENTS = (
    (re.compile(r'\bKubeCM\b'), 'Kube C M'),
    (re.compile(r'\bROCm\b'), 'R O C M'),
    (re.compile(r'\bOpenVox\b'), 'Open Vox'),
    (re.compile(r'\bllama-qwen\b', re.IGNORECASE), 'llama Qwen'),
)


def _spell_chars(text: str) -> str:
    words = []
    for char in text:
        if char.isdigit():
            words.append(_DIGIT_WORDS[char])
        elif char.isalpha():
            words.append(char.upper())
        elif char in {'-', '_'}:
            words.append('dash' if char == '-' else 'underscore')
    return ' '.join(words)


def _normalize_url(match: re.Match[str]) -> str:
    url = match.group(0)
    suffix = ''
    while url.endswith(('.', ',', ';', ':')):
        suffix = url[-1] + suffix
        url = url[:-1]
    spoken = url
    spoken = re.sub(r'^https://', 'H T T P S, ', spoken, flags=re.IGNORECASE)
    spoken = re.sub(r'^http://', 'H T T P, ', spoken, flags=re.IGNORECASE)
    spoken = spoken.replace('/', ' slash ')
    spoken = spoken.replace('.', ' dot ')
    spoken = spoken.replace('-', ' dash ')
    spoken = spoken.replace('_', ' underscore ')
    spoken = re.sub(r'\s+', ' ', spoken).strip()
    return f'{spoken}{suffix}'


def normalize_tts_text(text: str) -> str:
    """Return a speech-only rendering for operational Hermes notifications."""
    normalized = text
    normalized = re.sub(
        r'\b((?:agent request|request)\s+)?ar-([0-9]{8})-([0-9]{6})-([0-9a-fA-F]{6})\b',
        lambda m: f"{m.group(1) or 'agent request '}A R {_spell_chars(m.group(2))}, {_spell_chars(m.group(3))}, {_spell_chars(m.group(4))}",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r'\b(task\s+)?t_([0-9a-fA-F]{8})\b',
        lambda m: f"{m.group(1) or 'task '}T {_spell_chars(m.group(2))}",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r'\b(?:commit|sha|hash)\s+([0-9a-fA-F]{7,40})\b',
        lambda m: f"{m.group(0).split()[0]} {_spell_chars(m.group(1))}",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(r'https?://[^\s)>,]+', _normalize_url, normalized)
    for pattern, replacement in _PRONUNCIATION_REPLACEMENTS:
        normalized = pattern.sub(replacement, normalized)
    return normalized


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--endpoint', required=True, help='Base URL for the Chatterbox API')
    parser.add_argument('--text-file', required=True, help='UTF-8 text input path')
    parser.add_argument('--output', required=True, help='Audio output path')
    parser.add_argument('--voice', required=True, help='Chatterbox voice or alias')
    parser.add_argument('--model', default='chatterbox-turbo', help='Chatterbox model id')
    parser.add_argument('--format', default='wav', help='Audio response format')
    parser.add_argument('--speed', default='1.0', help='Requested speech speed')
    parser.add_argument('--timeout', type=float, default=180.0, help='HTTP timeout seconds')
    args = parser.parse_args()

    endpoint = args.endpoint.rstrip('/')
    text = normalize_tts_text(Path(args.text_file).read_text(encoding='utf-8'))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    try:
        speed = float(args.speed)
    except ValueError:
        speed = 1.0

    payload = {
        'input': text,
        'model': args.model,
        'voice': args.voice,
        'response_format': args.format.lstrip('.'),
        'speed': speed,
    }
    data = json.dumps(payload).encode('utf-8')
    req = request.Request(
        f'{endpoint}/v1/audio/speech',
        data=data,
        headers={
            'Content-Type': 'application/json',
            'Accept': 'audio/*',
        },
        method='POST',
    )

    try:
        with request.urlopen(req, timeout=args.timeout) as resp:
            body = resp.read()
    except error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='replace')
        print(f'Chatterbox TTS HTTP {exc.code}: {detail}', file=sys.stderr)
        return 1
    except Exception as exc:
        print(f'Chatterbox TTS request failed: {exc}', file=sys.stderr)
        return 1

    if not body:
        print('Chatterbox TTS returned an empty response', file=sys.stderr)
        return 1
    output.write_bytes(body)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
