#!/usr/bin/env python3
"""Hermes command-provider wrapper for Nest's local Chatterbox TTS API."""

import argparse
import json
import sys
from pathlib import Path
from urllib import error, request


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
    text = Path(args.text_file).read_text(encoding='utf-8')
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
