"""Real public handlers -> authenticated TLS -> resident controller -> Firefox.

Run only in a network-disabled disposable image without owner mounts. All page
content, credentials, cookies and windows here are synthetic engineering data.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import threading
import time
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

assert os.environ.get('FIREFOX_DISPOSABLE_CANARY') == '1'
assert not Path('/home/kasm-user/.local/state/nest-firefox-ui/windows.json').exists()
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, '/opt/nest/firefox/bin')

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def emit(stage, **data):
    print(json.dumps({'stage': stage, **data}), flush=True)


class Registry:
    def __init__(self):
        self.tools = {}
    def register(self, **entry):
        self.tools[entry['name']] = entry


requests = []
class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        requests.append({'path': self.path, 'authenticated': 'fixture-session=shared' in self.headers.get('Cookie', '')})
        body = b'''<title>Public workflow fixture</title><style>body{margin:0}button,input,textarea{display:block;margin:20px}#overlay{position:fixed;inset:0;background:white;z-index:10}#dismiss{position:absolute;left:80px;top:80px;width:160px;height:60px;margin:0}#bottom{margin-top:1600px}</style>
        <body><div id="overlay"><button id="dismiss" onclick="document.querySelector('#point').textContent=event.clientX+','+event.clientY;document.querySelector('#overlay').remove()">Dismiss fixture overlay</button></div>
        <button id="selector" onclick="document.querySelector('#result').textContent='selector delivered'">Selector fixture</button>
        <button id="fault" onclick="fetch('/effect',{method:'POST'});document.querySelector('#faultresult').textContent='fault delivered'">Fault fixture</button><pre id="faultresult"></pre>
        <textarea id="draft"></textarea><pre id="result">not clicked</pre><pre id="echo"></pre><pre id="point"></pre><div id="bottom">Bottom fixture</div>
        <script>document.querySelector('#draft').addEventListener('input',e=>document.querySelector('#echo').textContent=e.target.value)</script></body>'''
        self.send_response(200)
        self.send_header('Set-Cookie', 'fixture-session=shared; Path=/; HttpOnly; SameSite=Strict')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_POST(self):
        assert self.path == '/effect'
        requests.append({'path': '/effect', 'effect': True})
        self.send_response(204)
        self.send_header('Content-Length', '0')
        self.end_headers()
    def log_message(self, *args):
        pass


registry = Registry()
tools = types.ModuleType('tools')
registration = types.ModuleType('tools.registry')
registration.registry = registry
sys.modules['tools'] = tools
sys.modules['tools.registry'] = registration
os.environ['HERMES_KANBAN_TASK'] = 't_publicfixture'
os.environ['HERMES_KANBAN_BOARD'] = 'canary'
os.environ['SECURE_BROWSER_CONTROL_MODE'] = 'firefox-windows-v3'
# No dispatcher/session imports in this standalone image; the authoritative
# synthetic worker environment above is consumed by the actual public adapter.
tool = load('public_adapter', ROOT / 'files/app/hermes/secure_browser_tool.py')
controller_root = Path('/opt/nest/firefox/bin') if os.environ.get('FIREFOX_CANARY_BAKED_SOURCE') == '1' else ROOT / 'files/firefox-browser'
engine_module = load('canary_windows', controller_root / 'firefox_windows.py')
source_hash = hashlib.sha256((controller_root / 'firefox_windows.py').read_bytes()).hexdigest()
assert source_hash == hashlib.sha256((ROOT / 'files/firefox-browser/firefox_windows.py').read_bytes()).hexdigest()
emit('source', controller_sha256=source_hash, baked=os.environ.get('FIREFOX_CANARY_BAKED_SOURCE') == '1')
endpoint = load('canary_endpoint', controller_root / 'firefox-bridge-server.py')
launcher = subprocess.Popen(['/opt/nest/firefox/bin/nest-firefox-browser.sh'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
http = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
threading.Thread(target=http.serve_forever, daemon=True).start()
engine = None
server = None
try:
    deadline = time.monotonic() + 45
    while True:
        try:
            with socket.create_connection(('127.0.0.1', 9222), timeout=.2):
                break
        except OSError:
            assert time.monotonic() < deadline
            time.sleep(.2)
    time.sleep(10)  # Disposable extension first-run startup, not a soak.
    engine = engine_module.Windows('/tmp/nest-firefox/public-canary.json')
    initial = engine._tree()
    for extra in initial[1:]:
        engine._call('browsingContext.close', {'context': extra['context'], 'promptUnload': False})
    emit('disposable-first-run-setup', closed_fixture_tabs=len(initial) - 1)
    native_call = engine._call
    def traced_call(method, *args, **kwargs):
        try:
            return native_call(method, *args, **kwargs)
        except Exception as error:
            causes = []
            current = error
            while current is not None:
                causes.append({'type': type(current).__name__, 'native_code': getattr(current, 'native_code', None), 'message': str(current)[:300]})
                current = current.__cause__
            emit('native-failure', method=method, causes=causes)
            raise
    engine._call = traced_call
    endpoint.LOCK_PATH = Path('/tmp/nest-firefox/public-endpoint.lock')
    server = endpoint.Server(('127.0.0.1', 0), endpoint.Handler)
    server.windows = engine
    server.bridge_token = 'synthetic-public-workflow-token-only'
    cert = Path('/tmp/nest-firefox/public-cert.pem')
    key = Path('/tmp/nest-firefox/public-key.pem')
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1', '-subj', '/CN=localhost', '-addext', 'subjectAltName=DNS:localhost', '-keyout', str(key), '-out', str(cert)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(cert, key)
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    token = Path('/tmp/nest-firefox/public-token')
    token.write_text(server.bridge_token)
    os.environ['SSL_CERT_FILE'] = str(cert)
    tool.PUBLIC_URL = f'https://localhost:{server.server_port}/'
    tool.BRIDGE_TOKEN_FILE = token
    count = 0
    def call(name, args, statuses=('ok',)):
        global count
        entry = registry.tools['secure_browser_' + name]
        # Assert the actual published coordinate schema, not an internal object.
        if 'coordinate' in args:
            assert entry['schema']['parameters']['properties']['coordinate']['type'] == 'array'
            assert isinstance(args['coordinate'], list) and len(args['coordinate']) == 2
        result = json.loads(entry['handler'](args))
        count += 1
        emit(name, status=result.get('status'), error=result.get('error'), outcome=result.get('outcome'))
        assert result.get('status') in statuses, result
        return result
    call('tab_lifecycle', {'action': 'status'})
    call('tab_lifecycle', {'action': 'acquire'})
    scope = 'kanban:canary:t_publicfixture'
    binding = dict(engine.state['windows'][scope])
    call('navigate', {'url': f'http://127.0.0.1:{http.server_port}/fixture'})
    call('page_snapshot', {})
    refused = json.loads(registry.tools['secure_browser_click']['handler']({'selector': '#selector', 'action_key': 'blocked-selector'}))
    assert refused['outcome'] == 'not_started'
    assert 'blocked-selector' not in engine.state['actions']
    emit('overlay-preflight', outcome=refused['outcome'])
    call('click', {'coordinate': [110, 95], 'action_key': 'dismiss-overlay'}, ('delivered',))
    point = call('query', {'expression': 'document.readText("#point",0)'})
    assert point['value']['text'] == '110,95', point
    call('click', {'selector': '#selector', 'action_key': 'selector-click'}, ('delivered',))
    result = call('query', {'expression': 'document.readText("#result",0)'})
    assert result['value']['text'] == 'selector delivered', result
    call('type', {'selector': '#draft', 'text': 'harmless fixture', 'action_key': 'type-fixture'}, ('input_readback_confirmed',))
    result = call('query', {'expression': 'document.readText("#echo",0)'})
    assert result['value']['text'] == 'harmless fixture', result
    call('scroll', {'direction': 'down', 'amount': 4})
    snapshot = call('page_snapshot', {})
    assert any('Bottom fixture' in str(n.get('name', '')) for n in snapshot['nodes']), snapshot
    call('current_page_summary', {})
    call('tab_lifecycle', {'action': 'recover'})
    assert engine.state['windows'][scope]['context'] == binding['context']
    assert engine.state['windows'][scope]['window'] == binding['window']
    call('navigate', {'url': f'http://127.0.0.1:{http.server_port}/continuity'})
    assert any(r['path'] == '/continuity' and r.get('authenticated') for r in requests)
    call('click', {'coordinate': [110, 95], 'action_key': 'continuity-dismiss'}, ('delivered',))
    # Consume the real native acknowledgement, but lose it before the journal
    # owner receives it. This fault seam cannot fabricate a successful action.
    native_exchange = engine.browser._bidi
    def lose_ack(method, params, **kwargs):
        result = native_exchange(method, params, **kwargs)
        if method == 'input.performActions':
            raise TimeoutError('synthetic lost native acknowledgement')
        return result
    engine.browser._bidi = lose_ack
    fault = {'selector': '#fault', 'action_key': 'lost-native-ack'}
    unknown = json.loads(registry.tools['secure_browser_click']['handler'](fault))
    assert unknown['outcome'] == 'uncertain', unknown
    assert engine.state['actions']['lost-native-ack']['state'] == 'started'
    call('page_snapshot', {})
    call('tab_lifecycle', {'action': 'recover'})
    repeated = call('click', fault, ('delivery_uncertain',))
    assert repeated['delivery']['input_sent'] is False
    readback = call('query', {'expression': 'document.readText("#faultresult",0)'})
    assert readback['value']['text'] == 'fault delivered'
    assert sum(r['path'] == '/effect' for r in requests) == 1
    assert engine.state['actions']['lost-native-ack']['state'] == 'started'
    call('click', {'selector': '#selector', 'action_key': 'safe-after-native-loss'}, ('delivered',))
    emit('lost-native-ack', unknown_preserved=True, effect_count=1, replay_blocked=True, safe_input_after_recovery=True)
    # Interrupt the actual HTTP transport after dispatch completed. The public
    # adapter must not retry; the resident journal remains authoritative.
    reply = endpoint.Handler.reply
    def drop_reply(handler, code, value):
        if value.get('action_key') == 'lost-http-ack':
            handler.connection.shutdown(socket.SHUT_RDWR)
            handler.connection.close()
            return
        return reply(handler, code, value)
    endpoint.Handler.reply = drop_reply
    http_fault = {'selector': '#fault', 'action_key': 'lost-http-ack'}
    interrupted = json.loads(registry.tools['secure_browser_click']['handler'](http_fault))
    assert interrupted['status'] == 'error', interrupted
    endpoint.Handler.reply = reply
    call('current_page_summary', {})
    call('tab_lifecycle', {'action': 'recover'})
    repeated = call('click', http_fault, ('already_delivered',))
    assert repeated['delivery']['input_sent'] is False
    assert sum(r['path'] == '/effect' for r in requests) == 2
    call('type', {'selector': '#draft', 'text': 'safe recovery', 'action_key': 'safe-after-http-loss'}, ('input_readback_confirmed',))
    emit('interrupted-http', effect_count=2, replay_blocked=True, observation_available=True, safe_input_after_recovery=True)
    emit('workflow-pass', public_calls=count, cookie_continuity=True, binding_preserved=True)
finally:
    if engine is not None:
        scope = 'kanban:canary:t_publicfixture'
        if engine.state['windows'].get(scope, {}).get('state') == 'open':
            result = engine.dispatch('tabs', {'scope': scope, 'action': 'release'})
            emit('cleanup', closed=result.get('closed'), scope_state=engine.state['windows'][scope]['state'])
        if engine.browser is not None:
            engine.browser.close()
    if server:
        server.shutdown()
        server.server_close()
    http.shutdown()
    http.server_close()
    launcher.terminate()
    launcher.wait(timeout=20)
