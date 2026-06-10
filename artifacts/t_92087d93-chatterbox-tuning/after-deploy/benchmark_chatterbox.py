#!/usr/bin/env python3
import concurrent.futures
import json
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

ENDPOINT = 'http://10.108.157.193/v1/audio/speech'
OUT = Path(__file__).resolve().parent
PROMPTS = {
    'agent_request_received': 'Agent request received: Tune Chatterbox TTS latency and breath artifacts. I will reproduce the breath artifact and benchmark owl before deploying.',
    'ops_tokens': 'KubeCM deploy finished on owl. llama-qwen, OpenVox, ROCm, and kubectl checks are ready for review.',
    'short_ack': 'Done.',
    'long_ops': 'Voice Chatterbox rollout update: Puppet code deploy completed, the managed KubeCM deployment is rolling out in the ai namespace, and Talon will verify health, timing, audio duration, and rollback evidence before closing the request.',
}

def wav_duration(path: Path) -> float:
    with wave.open(str(path), 'rb') as fh:
        return fh.getnframes() / float(fh.getframerate())

def synth(name: str, text: str, voice='talon', postprocess=True):
    payload = {
        'model': 'chatterbox-turbo',
        'voice': voice,
        'response_format': 'wav',
        'input': text,
        'postprocess_audio': postprocess,
    }
    body = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(ENDPOINT, data=body, headers={'Content-Type': 'application/json'}, method='POST')
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=240) as resp:
            content = resp.read()
            status = resp.status
            headers = {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as e:
        content = e.read()
        status = e.code
        headers = {k.lower(): v for k, v in e.headers.items()}
    wall = time.perf_counter() - started
    wav_path = OUT / f'{name}.wav'
    wav_path.write_bytes(content)
    audio_s = wav_duration(wav_path) if status == 200 else None
    return {
        'name': name,
        'status': status,
        'client_wall_seconds': round(wall, 3),
        'audio_seconds': round(audio_s, 3) if audio_s is not None else None,
        'client_rtf': round(wall / audio_s, 3) if audio_s else None,
        'server_wall_seconds': float(headers.get('x-nest-tts-wall-seconds', 'nan')),
        'server_audio_seconds': float(headers.get('x-nest-tts-seconds', 'nan')),
        'server_rtf': float(headers.get('x-nest-tts-rtf', 'nan')),
        'postprocess': headers.get('x-nest-tts-postprocess'),
        'voice': headers.get('x-nest-tts-voice'),
        'wav': str(wav_path.relative_to(OUT.parent)),
    }

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    results = [synth(name, text) for name, text in PROMPTS.items()]
    pair_start = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(synth, f'concurrency_{idx}', PROMPTS['agent_request_received']) for idx in (1, 2)]
        concurrent_results = [future.result() for future in futures]
    pair_wall = time.perf_counter() - pair_start
    manifest = {
        'endpoint': ENDPOINT,
        'voice': 'talon',
        'postprocess_audio': True,
        'sequential': results,
        'concurrency_probe': {
            'pair_wall_seconds': round(pair_wall, 3),
            'requests': concurrent_results,
        },
    }
    (OUT / 'after_deploy_manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    print(json.dumps(manifest, indent=2, sort_keys=True))

if __name__ == '__main__':
    main()
