#!/usr/bin/env python3
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path
from urllib import request

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / 'artifacts' / 't_4faddcbc-tts-pronunciation'
SCRIPT = ROOT / 'files' / 'app' / 'hermes' / 'chatterbox-tts-command.py'
ENDPOINT = 'http://10.108.157.193'
PROMPT = ART / 'sample.txt'

spec = importlib.util.spec_from_file_location('chatterbox_tts_command', SCRIPT)
assert spec is not None
assert spec.loader is not None
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

text = PROMPT.read_text(encoding='utf-8')
normalized = mod.normalize_tts_text(text)
(ART / 'sample-normalized.txt').write_text(normalized, encoding='utf-8')

manifest = {
    'endpoint': ENDPOINT,
    'source_text_file': str(PROMPT),
    'normalized_text_file': str(ART / 'sample-normalized.txt'),
    'source_text': text,
    'normalized_text': normalized,
    'samples': [],
}

# Direct API call with source text reproduces the pre-fix production behavior:
# Hermes passed the visual notification text through unchanged.
def direct_before(voice: str) -> Path:
    out = ART / f'before-{voice}.wav'
    payload = {
        'input': text,
        'model': 'chatterbox-turbo',
        'voice': voice,
        'response_format': 'wav',
        'speed': 1.0,
    }
    req = request.Request(
        f'{ENDPOINT}/v1/audio/speech',
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'Accept': 'audio/*'},
        method='POST',
    )
    start = time.monotonic()
    with request.urlopen(req, timeout=180) as resp:
        body = resp.read()
        status = resp.status
    out.write_bytes(body)
    manifest['samples'].append({
        'kind': 'before',
        'voice': voice,
        'path': str(out),
        'status': status,
        'bytes': len(body),
        'seconds': round(time.monotonic() - start, 3),
        'input_text': text,
    })
    return out

# Patched wrapper call proves the provider command sends normalized speech text.
def wrapper_after(voice: str) -> Path:
    out = ART / f'after-{voice}.wav'
    cmd = [
        sys.executable,
        str(SCRIPT),
        '--endpoint', ENDPOINT,
        '--text-file', str(PROMPT),
        '--output', str(out),
        '--voice', voice,
        '--model', 'chatterbox-turbo',
        '--format', 'wav',
        '--speed', '1.0',
    ]
    start = time.monotonic()
    cp = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=210)
    manifest['samples'].append({
        'kind': 'after',
        'voice': voice,
        'path': str(out),
        'returncode': cp.returncode,
        'stdout': cp.stdout,
        'stderr': cp.stderr,
        'bytes': out.stat().st_size if out.exists() else 0,
        'seconds': round(time.monotonic() - start, 3),
        'input_text': normalized,
    })
    if cp.returncode != 0:
        raise SystemExit(cp.returncode)
    return out

for voice in ('talon', 'star'):
    direct_before(voice)
    wrapper_after(voice)

(ART / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
print(json.dumps(manifest, indent=2))
