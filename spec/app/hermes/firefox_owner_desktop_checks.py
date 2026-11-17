"""Actual native desktop panel acceptance, synthetic Firefox only."""
import base64
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import time


def run(engine, call, base, emit, requests):
    assert os.environ.get('FIREFOX_DISPOSABLE_CANARY') == '1'
    root = Path(__file__).resolve().parents[3]
    baked = os.environ.get('FIREFOX_CANARY_BAKED_SOURCE') == '1'
    desktop_path = Path('/opt/nest/firefox/bin/owner-desktop.py') if baked else root / 'files/firefox-browser/owner-desktop.py'
    import hashlib
    assert desktop_path.read_bytes() == (root / 'files/firefox-browser/owner-desktop.py').read_bytes()
    for installed, leaf in [('/opt/nest/firefox/xmonad.hs', 'xmonad.hs'), ('/opt/nest/firefox/bin/nest-firefox-browser.sh', 'nest-firefox-browser.sh')]:
        assert Path(installed).read_bytes() == (root / 'files/firefox-browser' / leaf).read_bytes()
    emit('owner-source', sha256=hashlib.sha256(desktop_path.read_bytes()).hexdigest(), baked=baked)
    spec = importlib.util.spec_from_file_location('owner_desktop', desktop_path)
    desktop = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(desktop)
    path = '/tmp/nest-firefox/fixture-owner.sock'
    ipc = desktop.OwnerSocket(path, engine)
    ipc.start()
    os.environ['DISPLAY'] = ':1'
    for line in Path('/tmp/nest-firefox/session.env').read_text().splitlines():
        key, value = line.split('=', 1)
        os.environ[key] = value
    os.environ.update(NO_AT_BRIDGE='0', GTK_MODULES='atk-bridge', ATSPI_DISABLE_P2P='1')
    panel = subprocess.Popen(['python3', str(desktop_path), '--gtk', '--socket', path])
    scope = 'kanban:canary:t_publicfixture'
    second = 'kanban:canary:t_otherfixture'
    def local(command, **kwargs):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(10)
            client.connect(path)
            client.sendall(json.dumps({'command': command, 'owner_capability': engine.state['windows']['owner']['viewer'], **kwargs}).encode() + b'\n')
            with client.makefile('rb') as stream:
                return json.loads(stream.readline(4097))
    def focus():
        return subprocess.check_output(['xdotool', 'getwindowfocus'], text=True).strip()
    def click_button(label, role='push button'):
        # Read only this synthetic GTK panel's accessibility subtree, never
        # another application's private page or owner chrome.
        import gi
        gi.require_version('Atspi', '2.0')
        from gi.repository import Atspi
        for line in Path('/tmp/nest-firefox/session.env').read_text().splitlines():
            key, value = line.split('=', 1)
            os.environ[key] = value
        for app in Atspi.get_desktop(0):
            for window in reversed(list(app)):
                if window.get_name() not in {'Firefox windows', 'Unlock Firefox windows'}:
                    continue
                stack = [window]
                while stack:
                    item = stack.pop()
                    if (label is None or item.get_name() == label) and (item.get_role_name() == role or role == 'push button' and item.get_role_name() == 'button'):
                        rect = item.get_component_iface().get_extents(Atspi.CoordType.SCREEN)
                        subprocess.run(['xdotool', 'mousemove', '--sync', str(rect.x + rect.width // 2), str(rect.y + rect.height // 2), 'click', '1'], check=True)
                        return
                    stack.extend(list(item))
        raise AssertionError('panel button unavailable: ' + str(label))
    try:
        time.sleep(2)
        assert panel.poll() is None, 'GTK owner panel failed'
        click_button('Unlock')
        click_button(None, 'password text')
        subprocess.run(['xdotool', 'type', '--clearmodifiers', engine.state['windows']['owner']['viewer']], check=True)
        click_button('Unlock')
        time.sleep(.3)
        listing = local('list')
        assert listing['status'] == 'ok' and len(listing['windows']) == 2, listing
        assert local('list', owner_capability='wrong-owner-capability-only')['status'] == 'error'
        assert local('list', owner_capability=engine.state['windows'][scope]['viewer'])['status'] == 'error'
        assert 'viewer' not in json.dumps(listing)
        one = dict(engine.state['windows'][scope])
        other = engine.acquire(second).copy()
        engine._call('browsingContext.navigate', {'context': other['context'], 'url': base + '/scroll-read-nested', 'wait': 'complete'})
        time.sleep(.2)
        assert len(local('list')['windows']) == 3
        before = json.dumps(engine.state, sort_keys=True)
        click_button('Refresh')
        click_button(None, 'combo box')
        subprocess.run(['xdotool', 'key', 'Home', 'Down', 'Return'], check=True)
        click_button('View')
        time.sleep(.2)
        second_focus = focus()
        assert json.dumps(engine.state, sort_keys=True) == before
        # Operate through the actual public handler while the owner views a
        # different native window. Neither routing nor its scroll may follow focus.
        call('navigate', {'url': base + '/scroll-read-root'})
        result = call('scroll', {'direction': 'down', 'amount': 1})
        assert result['scroll']['outcome'] == 'moved', result
        assert engine._evaluate(other['context'], 'document.querySelector("#pane").scrollTop', read_only=True) == 0
        assert focus() == second_focus
        call('navigate', {'url': base + '/fixture'})
        call('click', {'coordinate': [110, 95], 'action_key': 'background-dismiss'}, ('delivered',))
        call('type', {'selector': '#draft', 'text': 'bound background input', 'action_key': 'background-type'}, ('input_readback_confirmed',))
        assert call('query', {'expression': 'document.readText("#echo",0)'})['value']['text'] == 'bound background input'
        assert focus() == second_focus
        assert engine.state['windows'][scope]['context'] == one['context']
        click_button(None, 'combo box')
        subprocess.run(['xdotool', 'key', 'Home', 'Down', 'Down', 'Return'], check=True)
        click_button('View')
        time.sleep(.2)
        assert focus() != second_focus
        if Path('/evidence').is_dir():
            subprocess.run(['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-f', 'x11grab', '-video_size', '1365x768', '-i', ':1', '-frames:v', '1', '/evidence/owner-task-fixture.png'], check=True)
        click_button('Return to owner')
        time.sleep(.4)
        owner_focus = focus()
        assert owner_focus != second_focus
        engine.dispatch('tabs', {'scope': second, 'action': 'release'})
        assert len(local('list')['windows']) == 2
        assert local('select', scope=second, epoch=engine.epoch)['status'] == 'error'
        assert local('select', scope=scope, epoch='stale')['status'] == 'error'
        assert focus() == owner_focus
        # The owner switch path must not accept/dismiss a native prompt. The
        # only dismissal below is explicit synthetic-fixture cleanup, whose
        # success independently proves the prompt remained open after selection.
        engine._evaluate(one['context'], "setTimeout(()=>alert('Synthetic protected dialog'),0);true")
        time.sleep(.3)
        local('select', scope=scope, epoch=engine.epoch)
        engine._call('browsingContext.handleUserPrompt', {'context': one['context'], 'accept': False})
        click_button('Return to owner')
        time.sleep(.3)
        # Synthetic desktop pixels include the real panel in Kasm's root display.
        env = dict(os.environ)
        output = Path('/evidence')
        if output.is_dir():
            subprocess.run(['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-f', 'x11grab', '-video_size', '1365x768', '-i', ':1', '-frames:v', '1', str(output / 'owner-switcher-fixture.png')], env=env, check=True)
        emit('owner-panel-pass', simultaneous_windows=3, private_ipc=True, native_activation=True,
             owner_return_button=True, background_public_scroll=True, new_closed_stale=True, bindings_preserved=True)
    finally:
        panel.terminate()
        panel.wait(timeout=10)
        ipc.close()
        if engine.state['windows'].get(second, {}).get('state') == 'open':
            engine.dispatch('tabs', {'scope': second, 'action': 'release'})
