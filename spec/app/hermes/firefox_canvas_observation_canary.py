"""Disposable native canvas fault reproduction. Never run in browser.eyrie.

Requires a network-disabled container without owner mounts, launched separately.
The only stopped process is that container's synthetic GPU process.
"""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

sys.path.insert(0, '/opt/nest/firefox/bin')
from firefox_windows import Windows


def emit(**values):
    print(json.dumps(values), flush=True)


def gpu_pid():
    matches = []
    for process in Path('/proc').iterdir():
        if process.name.isdigit():
            try:
                if (process / 'comm').read_text().strip() == 'GPU Process':
                    stat = (process / 'stat').read_text().rsplit(') ', 1)[1].split()
                    if stat[0] != 'Z':
                        matches.append(int(process.name))
            except OSError:
                pass
    assert len(matches) == 1, matches
    return matches[0]


assert os.environ.get('FIREFOX_DISPOSABLE_CANARY') == '1'
assert not Path('/home/kasm-user/.local/state/nest-firefox-ui/windows.json').exists()
policy = sys.argv[1]
assert policy in {'baseline', 'local-canvas'}
profile = Path('/home/kasm-user/.mozilla/firefox/nest-secure-browser')
profile.mkdir(parents=True, exist_ok=True)
if policy == 'local-canvas':
    import re
    import textwrap
    source = Path('/candidate/data/kubernetes/app/firefox.yaml').read_text()
    raw = re.search(r'\.firefox_policy: &firefox_policy \|-\n(.*?)\n\n', source, re.S)
    assert raw is not None
    preference = json.loads(textwrap.dedent(raw.group(1)))['policies']['Preferences']['gfx.canvas.accelerated']
    assert preference == {'Value': False, 'Status': 'locked'}
    (profile / 'user.js').write_text('user_pref("gfx.canvas.accelerated", false);\n')
launcher = subprocess.Popen(['/opt/nest/firefox/bin/nest-firefox-browser.sh'],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    deadline = time.monotonic() + 40
    while True:
        try:
            with socket.create_connection(('127.0.0.1', 9222), timeout=.2):
                break
        except OSError:
            assert time.monotonic() < deadline, 'disposable Firefox startup failed'
            time.sleep(.2)
    engine = Windows('/tmp/nest-firefox/canvas-canary.json')
    # Match the existing native canary's finite first-run extension setup.
    time.sleep(10)
    tree = engine._tree()
    cid = tree[0]['context']
    engine._call('browsingContext.navigate', {'context': cid, 'url': 'about:blank', 'wait': 'complete'})
    # Native input is not used. This fixture creates only synthetic canvas data.
    setup = """(()=>{const c=document.createElement('canvas');c.width=128;c.height=128;
    document.body.appendChild(c);window.fixtureCanvas=c;const x=c.getContext('2d');
    x.fillStyle='red';x.fillRect(0,0,128,128);return x.getImageData(0,0,1,1).data[0]})()"""
    assert engine._evaluate(cid, setup) == 255
    gpu = gpu_pid()
    emit(stage='prepared', policy=policy, gpu=gpu)
    os.kill(gpu, signal.SIGSTOP)
    start = time.monotonic()
    try:
        result = engine._evaluate(cid, "(()=>{const x=fixtureCanvas.getContext('2d');x.fillStyle='blue';x.fillRect(0,0,128,128);return x.getImageData(0,0,1,1).data[2]})()")
        emit(stage='fault-observation', policy=policy, completed=True, value=result,
             elapsed=round(time.monotonic() - start, 3))
        assert result == 255
        if policy == 'baseline':
            raise AssertionError('baseline unexpectedly escaped the stopped canvas peer')
        # A real navigation whose response is lost must not be replayed. Both
        # public readback shapes must observe the effect in the same binding.
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading
        requests = []
        class Fixture(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/receipt':
                    requests.append(self.path)
                body = b'<title>Canvas receipt fixture</title><body><h1>Native receipt</h1></body>'
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        record = engine.acquire('owner').copy()
        native = engine.browser._bidi
        def lost_response(method, params, **kwargs):
            response = native(method, params, **kwargs)
            if method == 'browsingContext.navigate':
                raise TimeoutError('synthetic caller loses the actual native navigation response')
            return response
        engine.browser._bidi = lost_response
        try:
            engine.dispatch('navigate', {'scope': 'owner', 'url': f'http://127.0.0.1:{server.server_port}/receipt'})
            raise AssertionError('lost navigation response was mislabeled successful')
        except Exception as error:
            assert getattr(error, 'outcome', None) == 'uncertain', type(error).__name__
        sys.path.insert(0, '/candidate/spec/app/hermes')
        from test_secure_browser_firefox_ui import load_tool
        tool, _ = load_tool()
        tool.CONTROL_MODE = 'firefox-windows-v3'
        tool._bridge = lambda command, payload, **kw: engine.dispatch(command, {**payload, 'scope': 'owner'})
        snapshot = json.loads(tool.secure_browser_page_snapshot_tool({}))
        summary = json.loads(tool.secure_browser_current_page_summary_tool({}))
        assert snapshot['title'] == 'Canvas receipt fixture'
        assert summary['title'] == 'Canvas receipt fixture'
        assert engine.state['windows']['owner']['window'] == record['window']
        assert engine.state['windows']['owner']['context'] == record['context']
        assert requests == ['/receipt'], requests
        server.shutdown()
        emit(stage='navigation-readbacks', navigation_requests=len(requests),
             original_outcome='uncertain', snapshot=True, summary=True,
             same_native_binding=True, navigation_replayed=False)
    except Exception as exc:
        emit(stage='fault-observation', policy=policy, completed=False,
             error=type(exc).__name__, cause=type(exc.__cause__).__name__,
             elapsed=round(time.monotonic() - start, 3))
        if policy != 'baseline' or not isinstance(exc.__cause__, TimeoutError):
            raise
    finally:
        try:
            os.kill(gpu, signal.SIGCONT)
        except ProcessLookupError:
            pass
finally:
    if 'engine' in globals() and engine.browser is not None:
        engine.browser.close()
    launcher.terminate()
    try:
        launcher.wait(timeout=10)
    except subprocess.TimeoutExpired:
        # Only disposable data exists here; container removal owns cleanup.
        emit(stage='disposable-cleanup', graceful_exit=False)
