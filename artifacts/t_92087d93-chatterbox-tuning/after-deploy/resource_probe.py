#!/usr/bin/env python3
import json
import subprocess
import threading
import time
import urllib.request
import wave
from pathlib import Path

OUT = Path(__file__).resolve().parent
ENDPOINT = 'http://10.108.157.193/v1/audio/speech'
TEXT = 'Voice Chatterbox resource observation: this deliberately longer notification gives rocm-smi time to observe GPU compute, memory, and power while the local Talon voice is generating after the latency tuning deployment.'

done = threading.Event()

def get_pod():
    cp = subprocess.run(['kubectl','-n','ai','get','pod'], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True)
    for line in cp.stdout.splitlines():
        if line.startswith('voice-chatterbox') and 'Running' in line:
            return line.split()[0]
    raise RuntimeError('voice-chatterbox running pod not found')

def sampler(pod):
    with (OUT / 'rocm-smi-during-after-deploy.txt').open('w') as fh:
        while not done.is_set():
            fh.write(time.strftime('%Y-%m-%dT%H:%M:%S%z') + '\n')
            cmd = ['kubectl','-n','ai','exec',pod,'--','/opt/rocm/bin/rocm-smi','--showuse','--showmemuse','--showpower','--showtemp','--json']
            try:
                cp = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=10)
                fh.write(cp.stdout)
                if not cp.stdout.endswith('\n'):
                    fh.write('\n')
            except Exception as exc:
                fh.write(f'kubectl rocm-smi error: {exc}\n')
            fh.flush()
            done.wait(1)

def main():
    pod = get_pod()
    payload = {'model':'chatterbox-turbo','voice':'talon','response_format':'wav','input':TEXT,'postprocess_audio':True}
    th = threading.Thread(target=sampler, args=(pod,))
    th.start()
    started = time.perf_counter()
    status = None
    headers = {}
    body = b''
    try:
        req = urllib.request.Request(ENDPOINT, data=json.dumps(payload).encode(), headers={'Content-Type':'application/json'}, method='POST')
        with urllib.request.urlopen(req, timeout=240) as resp:
            body = resp.read()
            status = resp.status
            headers = {k.lower(): v for k, v in resp.headers.items()}
    finally:
        done.set(); th.join()
    wall = time.perf_counter() - started
    wav = OUT / 'resource-probe.wav'
    wav.write_bytes(body)
    with wave.open(str(wav), 'rb') as w:
        seconds = w.getnframes() / w.getframerate()
    result = {
        'pod': pod,
        'status': status,
        'wall_seconds': round(wall, 3),
        'audio_seconds': round(seconds, 3),
        'client_rtf': round(wall / seconds, 3),
        'server_wall_seconds': float(headers.get('x-nest-tts-wall-seconds', 'nan')),
        'server_audio_seconds': float(headers.get('x-nest-tts-seconds', 'nan')),
        'server_rtf': float(headers.get('x-nest-tts-rtf', 'nan')),
        'postprocess': headers.get('x-nest-tts-postprocess'),
        'voice': headers.get('x-nest-tts-voice'),
        'wav': str(wav),
        'rocm_samples_path': str(OUT / 'rocm-smi-during-after-deploy.txt'),
    }
    (OUT / 'resource_probe.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps(result, indent=2, sort_keys=True))

if __name__ == '__main__':
    main()
