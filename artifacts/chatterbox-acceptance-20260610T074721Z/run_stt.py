#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import time

ROOT = Path('/home/joy/projects/.worktrees/nest-config/t_e9f23762/artifacts/chatterbox-acceptance-20260610T074721Z/generated')
MANIFEST = ROOT / 'manifest.json'
ENDPOINT = 'http://10.108.246.221/v1/audio/transcriptions'
MODEL = 'small'
PROMPT = 'Talon Star Honcho Eyrie KubeCM llama-qwen GitLab Puppet Kubernetes OpenVox ROCm kubectl owl voice-speech Chatterbox Kokoro'

def transcribe(path: Path) -> dict:
    started = time.perf_counter()
    proc = subprocess.run([
        'curl', '-fsS', ENDPOINT,
        '-F', f'file=@{path}',
        '-F', f'model={MODEL}',
        '-F', 'language=en',
        '-F', 'temperature=0.0',
        '-F', 'condition_on_previous_text=false',
        '-F', f'initial_prompt={PROMPT}',
    ], text=True, capture_output=True, check=False, timeout=180)
    elapsed = time.perf_counter() - started
    if proc.returncode != 0:
        return {'model': MODEL, 'initial_prompt': PROMPT, 'wall_seconds': round(elapsed, 3), 'error': proc.stderr.strip() or proc.stdout.strip()}
    data = json.loads(proc.stdout)
    return {'model': MODEL, 'initial_prompt': PROMPT, 'wall_seconds': round(elapsed, 3), 'text': data.get('text', '').strip()}

def main():
    manifest = json.loads(MANIFEST.read_text())
    for preset in manifest['presets']:
        for sample in preset['samples']:
            wav = ROOT / preset['preset'] / Path(sample['wav']).name
            sample['stt_roundtrip'] = transcribe(wav)
    manifest['stt_endpoint'] = ENDPOINT
    manifest['stt_model'] = MODEL
    manifest['stt_context_prompt'] = PROMPT
    MANIFEST.write_text(json.dumps(manifest, indent=2) + '\n')
    print(MANIFEST)

if __name__ == '__main__':
    main()
