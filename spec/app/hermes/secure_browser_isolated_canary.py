"""Opt-in canary: run ONLY inside a disposable browser pod without owner PVCs."""

import http.server
import importlib.util
import json
import os
from pathlib import Path
from typing import Any
import threading
import tempfile
import time
import uuid

if os.environ.get('NEST_ISOLATED_BROWSER_CANARY') != 't_9590a2b9':
    raise SystemExit('Refusing: isolated fixture acknowledgement missing')
spec = importlib.util.spec_from_file_location('bridge', '/tmp/hardening-bridge.py')
assert spec is not None and spec.loader is not None
b: Any = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)
state_dir = Path(tempfile.mkdtemp(prefix='canary-', dir='/home/kasm-user/.local/state'))
b.STATE_DIR = state_dir
b.STATE_PATH = state_dir / 'state.json'
b.LOCK_PATH = state_dir / 'state.lock'

class Fixture(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(b'<title>Generic fixture</title><input id="public"><div contenteditable="true"><span id="editable"> </span></div><a href="https://example.test/reset/PRIVATE?token=PRIVATE#PRIVATE">Public link</a><button id="delayed" onclick="setTimeout(()=>document.title=\'Delayed fixture\',300)">Delayed change</button>')
    def log_message(self, format, *args):
        pass

server = http.server.ThreadingHTTPServer(('127.0.0.1', 8765), Fixture)
threading.Thread(target=server.serve_forever, daemon=True).start()
workflow = 'isolated-hardening-' + uuid.uuid4().hex
b.command_tabs({'action': 'acquire', 'workflow_id': workflow})
b.command_navigate({'workflow_id': workflow, 'url': 'http://127.0.0.1:8765/' + workflow})
record = b._load_state()['workflows'][workflow]
identity = record['tab_identity']
assert identity
# Rename does not lose ownership.
with b._webdriver() as command:
    command('POST', '/execute/sync', {'script': "document.title='Renamed fixture'; return true", 'args': []})
time.sleep(0.5)
b.command_tabs({'action': 'acquire', 'workflow_id': workflow})
assert b._load_state()['workflows'][workflow]['tab_identity'] == identity
print('PASS live rename preserves object identity')
args = {'workflow_id': workflow, 'operation': 'type', 'selector': '#public', 'text': 'once', 'action_key': 'canary-native'}
assert b.command_selector_action(args)['status'] == 'delivered'
assert b.command_selector_action(args)['status'] == 'already_delivered'
with b._webdriver() as command:
    assert command('POST', '/execute/sync', {'script': "return document.querySelector('#public').value", 'args': []}) == 'once'
print('PASS native typing retry delivers once')
args = {'workflow_id': workflow, 'operation': 'type', 'selector': '[contenteditable]', 'text': 'editable', 'action_key': 'canary-editable'}
assert b.command_selector_action(args)['status'] == 'delivered'
print('PASS contenteditable editing-host input')
with b._webdriver() as command:
    script = json.loads(Path('/tmp/hardening-link-script.json').read_text())
    value = command('POST', '/execute/sync', {'script': 'return ' + script, 'args': []})
    assert 'PRIVATE' not in str(value) and 'https://example.test' in str(value)
print('PASS live bounded link observation redacts credential components')
b.command_selector_action({'workflow_id': workflow, 'operation': 'click', 'selector': '#delayed', 'action_key': 'delayed'})
time.sleep(0.5)
assert b._selected_tab(b._snapshot())['name'] == 'Delayed fixture'
assert b._selected_tab(b._snapshot())['tab_identity'] == identity
print('PASS delayed outcome independently observed; delivery alone not completion')

# Ordinary typing targets a fresh AX locator, then blocks both completed and uncertain retries.
snapshot = b._snapshot()
entry = next(n for n in snapshot['nodes'] if n['role'] == 'entry' and n.get('rect') and n['rect']['y'] > 80)
args = {'workflow_id': workflow, 'locator': entry['locator'], 'text': 'ordinary', 'action_key': 'canary-ordinary'}
assert b.command_type(args)['status'] == 'delivered'
assert b.command_type(args)['status'] == 'already_delivered'
with b._locked_state() as state:
    state['action_keys']['canary-uncertain'] = {'created_at': time.time(), 'workflow_id': workflow, 'operation': 'type', 'delivery_state': 'delivery_started'}
args['action_key'] = 'canary-uncertain'
assert b.command_type(args)['status'] == 'delivery_uncertain'
print('PASS ordinary completed and uncertain retries block replay')
# Owner-selected changes and same-title replacement are tested only on this disposable desktop.
b._xdotool('key', '--clearmodifiers', 'ctrl+t')
time.sleep(0.5)
b.command_navigate({'workflow_id': workflow, 'url': 'http://127.0.0.1:8765/two'})
assert b._selected_tab(b._snapshot())['tab_identity'] == identity
print('PASS other selected tab cannot receive workflow navigation')
b._xdotool('key', '--clearmodifiers', 'ctrl+shift+Prior')
time.sleep(0.5)
try:
    b.command_type({'workflow_id': workflow, 'text': 'MUST NOT ARRIVE', 'action_key': 'reorder'})
except RuntimeError:
    pass
else:
    raise AssertionError('recreated accessibility identity accepted after reorder')
assert 'reorder' not in b._load_state()['action_keys']
b.command_tabs({'action': 'recover', 'workflow_id': workflow})
assert 'canary-uncertain' in b._load_state()['action_keys']
b.command_tabs({'action': 'acquire', 'workflow_id': workflow})
b.command_navigate({'workflow_id': workflow, 'url': 'http://127.0.0.1:8765/two'})
print('PASS reordered AX object fails closed; explicit recovery preserves journal')
b._xdotool('key', '--clearmodifiers', 'ctrl+w')
time.sleep(0.5)
b._xdotool('key', '--clearmodifiers', 'ctrl+l')
b._xdotool('type', '--clearmodifiers', '--', 'http://127.0.0.1:8765/two')
b._xdotool('key', '--clearmodifiers', 'Return')
time.sleep(0.5)
try:
    b.command_type({'workflow_id': workflow, 'text': 'MUST NOT ARRIVE', 'action_key': 'replacement'})
except RuntimeError:
    pass
else:
    raise AssertionError('replacement received workflow input')
assert 'replacement' not in b._load_state()['action_keys']
print('PASS indistinguishable replacement refuses input')
b.command_tabs({'action': 'recover', 'workflow_id': workflow})
assert 'canary-uncertain' in b._load_state()['action_keys']
print('PASS explicit recovery preserves retry journal')
server.shutdown()
