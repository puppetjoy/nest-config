"""Baked service entrypoint/owner-UI acceptance, synthetic isolated image only."""
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

assert os.environ.get('FIREFOX_DISPOSABLE_CANARY') == '1'
assert not Path('/home/kasm-user/.local/state/nest-firefox-ui/windows.json').exists()
root = Path(__file__).resolve().parents[3]
for leaf in ['owner-desktop.py', 'firefox-bridge-server.py', 'nest-firefox-browser.sh', 'firefox_windows.py']:
    assert Path('/opt/nest/firefox/bin', leaf).read_bytes() == (root / 'files/firefox-browser' / leaf).read_bytes(), leaf
assert Path('/opt/nest/firefox/xmonad.hs').read_bytes() == (root / 'files/firefox-browser/xmonad.hs').read_bytes()
token = 'synthetic-baked-service-token-only'
token_file = Path('/tmp/fixture-token')
token_file.write_text(token)
os.environ['FIREFOX_BRIDGE_TOKEN_FILE'] = str(token_file)
os.environ['FIREFOX_CONTROL_PROTOCOL'] = 'firefox-windows-v3'
os.environ['DISPLAY'] = ':1'

class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'<title>Disposable service fixture</title><h1>Disposable owner switching</h1><textarea id="draft"></textarea><pre id="echo"></pre><script>document.querySelector("#draft").oninput=e=>document.querySelector("#echo").textContent=e.target.value</script>'
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *args):
        pass

http = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
threading.Thread(target=http.serve_forever, daemon=True).start()
launcher = subprocess.Popen(['sh', '/opt/nest/firefox/bin/nest-firefox-browser.sh'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
def call(command, scope='owner', **payload):
    request = urllib.request.Request('http://127.0.0.1:8766/_nest/bridge/v1',
        data=json.dumps({'command': command, 'payload': {'scope': scope, **payload}}).encode(),
        headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token})
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.load(response)
    assert result.get('status') in {'ok', 'input_readback_confirmed', 'delivered'}, result
    return result

try:
    deadline = time.monotonic() + 60
    while True:
        try:
            result = call('status')
            if result.get('bidi_available'):
                break
        except (OSError, AssertionError):
            pass
        assert time.monotonic() < deadline, 'real service entrypoint did not become ready'
        time.sleep(.5)
    time.sleep(5)  # Bounded disposable extension first-run preparation.
    scopes = ['kanban:canary:t_servicea', 'kanban:canary:t_serviceb']
    for line in Path('/tmp/nest-firefox/session.env').read_text().splitlines():
        key, value = line.split('=', 1)
        os.environ[key] = value
    os.environ.update(NO_AT_BRIDGE='0', GTK_MODULES='atk-bridge', ATSPI_DISABLE_P2P='1')
    import gi
    gi.require_version('Atspi', '2.0')
    from gi.repository import Atspi
    def widgets():
        result = []
        for app in Atspi.get_desktop(0):
            for window in app:
                if window.get_name() != 'Firefox windows':
                    continue
                stack = [window]
                while stack:
                    item = stack.pop()
                    result.append(item)
                    stack.extend(list(item))
        return result
    def click(role=None, name=None):
        matches = [item for item in widgets() if (role is None or item.get_role_name() == role) and (name is None or item.get_name() == name)]
        assert matches, (role, name)
        rect = matches[0].get_component_iface().get_extents(Atspi.CoordType.SCREEN)
        subprocess.run(['xdotool', 'mousemove', '--sync', str(rect.x + rect.width // 2), str(rect.y + rect.height // 2), 'click', '1'], check=True)
    def current():
        combo = next(item for item in widgets() if item.get_role_name() == 'combo box')
        selected = combo.get_selection_iface().get_selected_child(0)
        return selected.get_name() if selected else None
    time.sleep(2.5)
    assert current() == 'Owner window', ('fresh owner entry requires an agent acquisition', current())
    print(json.dumps({'stage': 'fresh-owner-before-agent', 'current': current()}), flush=True)
    for scope in scopes:
        call('tabs', scope, action='acquire')
        call('navigate', scope, url=f'http://127.0.0.1:{http.server_port}/fixture')
    time.sleep(2.5)
    names = [item.get_name() for item in widgets()]
    assert 'Unlock' not in names and not any('window link' in name for name in names)
    assert 'Return to owner' in names and 'Task canary:t_servicea' in names and 'Task canary:t_serviceb' in names, names
    initial = current()
    focus = lambda: subprocess.check_output(['xdotool', 'getwindowfocus'], text=True).strip()
    for label in ['Task canary:t_servicea', 'Task canary:t_serviceb']:
        click(role='combo box')
        click(role='menu item', name=label)
        time.sleep(.3)
        assert current() == label, current()
    selected_focus = focus()
    call('selector_action', scopes[0], operation='type', selector='#draft', text='still bound to service A', action_key='baked-background-type')
    result = call('query', scopes[0], expression='document.readText("#echo",0)')
    assert result['value']['text'] == 'still bound to service A', result
    assert focus() == selected_focus
    subprocess.run(['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-f', 'x11grab', '-video_size', '1365x768', '-i', ':1', '-frames:v', '1', '/evidence/baked-real-service.png'], check=True)
    click(role='combo box')
    time.sleep(.2)
    subprocess.run(['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-f', 'x11grab', '-video_size', '1365x768', '-i', ':1', '-frames:v', '1', '/evidence/baked-real-service-choices.png'], check=True)
    geometry = {}
    for item in widgets():
        if item.get_name() in {'Owner window', 'Task canary:t_servicea', 'Task canary:t_serviceb'} and item.get_role_name() == 'menu item':
            rect = item.get_component_iface().get_extents(Atspi.CoordType.SCREEN)
            geometry[item.get_name()] = [rect.x, rect.y, rect.width, rect.height]
    print(json.dumps({'stage': 'popup-geometry', 'items': geometry}), flush=True)
    assert len(geometry) == 3 and all(y >= 0 and h > 0 and y + h <= 768 for x, y, w, h in geometry.values()), geometry
    click(role='menu item', name='Task canary:t_servicea')
    time.sleep(.3)
    assert current() == 'Task canary:t_servicea' and focus() != selected_focus
    click(name='Return to owner')
    time.sleep(.3)
    assert current() == 'Owner window' and focus() != selected_focus
    for scope in scopes:
        call('tabs', scope, action='release')
    print(json.dumps({'stage': 'real-service-pass', 'baked': os.environ.get('FIREFOX_CANARY_BAKED_SOURCE') == '1', 'entrypoint': True, 'no_capability_entry': True,
                      'populated': True, 'current': True, 'direct_switching': True, 'background_bound_input': True,
                      'owner_return': True, 'cleanup': True}), flush=True)
finally:
    http.shutdown()
    launcher.terminate()
    launcher.wait(timeout=15)
