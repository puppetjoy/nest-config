#!/usr/bin/env python3
import importlib.util
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'files' / 'app' / 'hermes' / 'chatterbox-tts-command.py'
ART = ROOT / 'artifacts' / 't_4faddcbc-tts-pronunciation'
PROMPT = ART / 'sample.txt'
CAPTURE = ART / 'stub-captured-payload.json'

spec = importlib.util.spec_from_file_location('chatterbox_tts_command', SCRIPT)
assert spec is not None
assert spec.loader is not None
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
expected = mod.normalize_tts_text(PROMPT.read_text(encoding='utf-8'))

captured = {}

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get('Content-Length', '0'))
        body = self.rfile.read(length)
        captured.update(json.loads(body.decode('utf-8')))
        self.send_response(200)
        self.send_header('Content-Type', 'audio/wav')
        self.end_headers()
        self.wfile.write(b'RIFFstubWAVE')

    def log_message(self, format, *args):
        return

server = HTTPServer(('127.0.0.1', 0), Handler)
thread = threading.Thread(target=server.handle_request, daemon=True)
thread.start()
endpoint = f'http://127.0.0.1:{server.server_port}'
out = ART / 'stub-output.wav'
cmd = [
    sys.executable,
    str(SCRIPT),
    '--endpoint', endpoint,
    '--text-file', str(PROMPT),
    '--output', str(out),
    '--voice', 'talon',
]
cp = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
thread.join(timeout=5)
server.server_close()
CAPTURE.write_text(json.dumps(captured, indent=2) + '\n', encoding='utf-8')
if cp.returncode != 0:
    print(cp.stdout)
    print(cp.stderr, file=sys.stderr)
    raise SystemExit(cp.returncode)
if captured.get('input') != expected:
    print('expected:', expected)
    print('captured:', captured.get('input'))
    raise SystemExit(1)
if PROMPT.read_text(encoding='utf-8') == expected:
    print('normalization did not change speech text')
    raise SystemExit(1)
print('captured wrapper input matches normalized speech text')
print(CAPTURE)
