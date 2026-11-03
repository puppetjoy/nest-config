#!/usr/bin/env python3
"""Bounded safe speech roundtrip + Owl shared-memory/device telemetry.

Run on Owl from the Nest project. --baseline records CPU behavior without
accepting it as GPU success. No audio is sent to a messaging service.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
from typing import Any

import yaml


def command(*args):
    return subprocess.check_output(args, text=True, timeout=30)


def host_sample():
    memory = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
    result = {'time': time.time(), 'mem_available_bytes': int(memory['MemAvailable'].split()[0]) * 1024}
    for name in ('mem_info_gtt_used', 'mem_info_vram_used', 'gpu_busy_percent'):
        for path in Path('/sys/class/drm').glob(f'card*/device/{name}'):
            result[str(path)] = int(path.read_text())
    return result


def container_sample(pod):
    source = '''import glob,json,pathlib,os
status = dict(line.split(':',1) for line in pathlib.Path('/proc/1/status').read_text().splitlines() if ':' in line)
fds = []
for p in glob.glob('/proc/1/fd/*'):
    try:
        target = os.readlink(p)
        if target.startswith(('/dev/kfd','/dev/dri/')): fds.append(target)
    except OSError: pass
print(json.dumps({'rss_kib':status.get('VmRSS'), 'swap_kib':status.get('VmSwap'),
 'container_bytes':int(pathlib.Path('/sys/fs/cgroup/memory.current').read_text()),
 'devices':glob.glob('/dev/kfd')+glob.glob('/dev/dri/*'), 'open_gpu_fds':sorted(set(fds))}))'''
    return json.loads(command('kubectl', '-n', 'ai', 'exec', pod, '--', 'python3', '-c', source))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', action='store_true')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    if socket.gethostname() != 'owl':
        raise SystemExit('Run on Owl: host memory/GTT samples must describe the serving node')
    os.environ.setdefault('VOICE_SPEECH_ENDPOINT', 'https://voice-speech.eyrie')
    data = yaml.safe_load((Path(__file__).resolve().parents[1] / 'data/kubernetes/app/voice-speech.yaml').read_text())
    monitor: dict[str, Any] = {'__name__': 'speech_check_helpers'}
    exec(compile(data['resources']['roundtrip-monitor-script']['data']['monitor.py'], 'monitor.py', 'exec'), monitor)
    pods = json.loads(command('kubectl', '-n', 'ai', 'get', 'pods', '-l', 'app=voice-speech', '-o', 'json'))['items']
    running = [p for p in pods if p['status']['phase'] == 'Running']
    if len(running) != 1:
        raise SystemExit('Expected exactly one running speech pod (no overlapping resident copies)')
    pod = running[0]['metadata']['name']
    result = {'baseline': args.baseline, 'pod': pod, 'before': container_sample(pod), 'health_before': monitor['get_json']('/health')}
    samples = []
    stop = threading.Event()

    def sample():
        while not stop.is_set():
            samples.append(host_sample())
            stop.wait(0.2)

    thread = threading.Thread(target=sample)
    thread.start()
    try:
        audio, headers, wall = monitor['post_json_audio']('/v1/audio/speech', {
            'input': monitor['PROMPT'], 'model': 'kokoro', 'voice': 'af_alloy',
            'response_format': 'wav', 'speed': 1.0, 'normalize': True,
        })
        stats = monitor['wav_stats'](audio)
        if stats['duration'] < 1 or stats['rms'] < 2:
            raise RuntimeError('Empty, silent or invalid WAV')
        start = time.monotonic()
        transcript = monitor['post_multipart_transcription'](audio)['text']
        stt_wall = time.monotonic() - start
        for word in ('joy', 'talon', 'star', 'voice', 'speech', 'request', 'recorded'):
            if word not in transcript.lower():
                raise RuntimeError(f'Missing expected word: {word}; transcript: {transcript}')
        result.update(audio=stats, transcript=transcript, tts_wall_seconds=wall,
                      stt_wall_seconds=stt_wall, tts_headers=headers)
        result['health_after'] = monitor['get_json']('/health')
        if not args.baseline:
            health = result['health_after']
            if not health['ok'] or not health['cuda_available']:
                raise RuntimeError('Required GPU is not healthy')
            for path in ('tts', 'stt'):
                evidence = health['inference'][path]
                if evidence['model_devices'] != ['cuda:0'] or not evidence['stages']:
                    raise RuntimeError(f'No GPU parameter/stage evidence for {path}')
                for stage in evidence['stages'].values():
                    if stage['calls'] < 1 or stage['inputs'] != ['cuda:0'] or stage['outputs'] != ['cuda:0']:
                        raise RuntimeError(f'Non-GPU stage for {path}: {stage}')
        result['ok'] = True
    except Exception as exc:
        result['ok'] = False
        result['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        stop.set()
        thread.join()
        result['host_samples'] = samples
        result['after'] = container_sample(pod)
        Path(args.output).write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps({k: v for k, v in result.items() if k != 'host_samples'}, indent=2))


if __name__ == '__main__':
    main()
