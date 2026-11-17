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
    owner_panel = desktop.OwnerPanel(engine)
    owner_panel.start()
    panel = owner_panel.process
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
    def current_choice():
        for app in Atspi.get_desktop(0):
            for candidate in app:
                if candidate.get_name() != 'Firefox windows':
                    continue
                stack = [candidate]
                while stack:
                    item = stack.pop()
                    if item.get_role_name() == 'combo box':
                        selected = item.get_selection_iface().get_selected_child(0)
                        return selected.get_name() if selected else None
                    stack.extend(list(item))
        raise AssertionError('selector unavailable')
    try:
        time.sleep(2)
        assert panel.poll() is None, 'GTK owner panel failed'
        # Ordinary owner entry: no capability link, credential or activation.
        import gi
        gi.require_version('Atspi', '2.0')
        from gi.repository import Atspi
        panels = [window for app in Atspi.get_desktop(0) for window in app
                  if window.get_name() == 'Firefox windows']
        assert panels, 'owner selector is not visible'
        native_panel = panels[-1]
        rect = native_panel.get_component_iface().get_extents(Atspi.CoordType.SCREEN)
        stack, labels, roles = [native_panel], [], []
        while stack:
            item = stack.pop()
            labels.append(item.get_name())
            roles.append(item.get_role_name())
            stack.extend(list(item))
        geometry = subprocess.check_output(['xdotool', 'getdisplaygeometry'], text=True).split()
        defects = []
        if 'Unlock' in labels or any('owner window link' in label for label in labels):
            defects.append('ordinary owner entry is gated by Unlock / agent link')
        if 'combo box' not in roles:
            defects.append('no immediately usable window selector')
        if rect.x != 0 or rect.width != int(geometry[0]):
            defects.append(f'unpainted reserved strip: panel={rect.width}, desktop={geometry[0]}')
        if Path('/evidence').is_dir():
            subprocess.run(['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-f', 'x11grab', '-video_size', 'x'.join(geometry), '-i', ':1', '-frames:v', '1', '/evidence/owner-entry.png'], check=True)
        emit('owner-entry', defects=defects, panel_width=rect.width, desktop_width=int(geometry[0]))
        assert not defects, '; '.join(defects)
        time.sleep(.3)
        listing = local('list')
        assert listing['status'] == 'ok' and len(listing['windows']) == 2, listing
        assert local('list', owner_capability='wrong-owner-capability-only')['status'] == 'error'
        assert local('list', owner_capability=engine.state['windows'][scope]['viewer'])['status'] == 'error'
        assert 'viewer' not in json.dumps(listing)
        one = dict(engine.state['windows'][scope])
        # A window opened by the owner's ordinary Firefox chrome is not an
        # agent lease. It must still appear, and manual close must remove it.
        unbound = engine._call('browsingContext.create', {'type': 'window'})
        engine._call('browsingContext.navigate', {'context': unbound['context'], 'url': base + '/fixture', 'wait': 'complete'})
        time.sleep(2.5)
        directory = owner_panel.dispatch({'command': 'list'})
        assert any(item['label'] == 'Owner window 2' for item in directory['windows']), directory
        click_button(None, 'combo box')
        subprocess.run(['xdotool', 'key', 'End', 'Return'], check=True)
        time.sleep(.2)
        assert current_choice() == 'Owner window 2'
        engine._call('browsingContext.close', {'context': unbound['context'], 'promptUnload': False})
        time.sleep(2.5)
        assert all(item['label'] != 'Owner window 2' for item in owner_panel.dispatch({'command': 'list'})['windows'])
        click_button('Return to owner')
        other = engine.acquire(second).copy()
        engine._call('browsingContext.navigate', {'context': other['context'], 'url': base + '/scroll-read-nested', 'wait': 'complete'})
        time.sleep(.2)
        assert len(local('list')['windows']) == 3
        before = json.dumps(engine.state, sort_keys=True)
        time.sleep(2.5)  # Automatic directory refresh; no activation or Refresh step.
        click_button(None, 'combo box')
        subprocess.run(['xdotool', 'key', 'Home', 'Down', 'Return'], check=True)
        time.sleep(.2)
        second_focus = focus()
        assert second_focus == desktop.native_window_id(engine, other['window'])
        assert current_choice() == 'Task canary:t_otherfixture'
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
        time.sleep(.2)
        assert focus() == desktop.native_window_id(engine, one['window'])
        assert current_choice() == 'Task canary:t_publicfixture'
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
        # Inspect the actual combo selection, not just IPC acknowledgements.
        time.sleep(2.5)
        assert current_choice() == 'Owner window', current_choice()
        # Test real framebuffer resizing, including shrink and subsequent grow.
        for width, height in [(900, 650), (1365, 768)]:
            resized = subprocess.run(['xrandr', '--fb', f'{width}x{height}'], capture_output=True, text=True)
            actual = subprocess.check_output(['xdotool', 'getdisplaygeometry'], text=True).strip()
            assert actual == f'{width} {height}', (resized.returncode, resized.stderr, actual)
            time.sleep(.5)
            rect = native_panel.get_component_iface().get_extents(Atspi.CoordType.SCREEN)
            assert rect.x == rect.y == 0 and rect.width == width and 0 < rect.height <= 48, (rect.x, rect.y, rect.width, rect.height)
            assert current_choice() == 'Owner window'
            if output.is_dir():
                subprocess.run(['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-f', 'x11grab', '-video_size', f'{width}x{height}', '-i', ':1', '-frames:v', '1', str(output / f'owner-resize-{width}.png')], check=True)
        click_button(None, 'combo box')
        time.sleep(.2)
        if output.is_dir():
            subprocess.run(['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-f', 'x11grab', '-video_size', '1365x768', '-i', ':1', '-frames:v', '1', str(output / 'owner-populated-choices.png')], check=True)
        subprocess.run(['xdotool', 'key', 'Escape'], check=True)
        emit('owner-panel-pass', simultaneous_windows=3, private_ipc=True, native_activation=True,
             owner_return_button=True, background_public_scroll=True, new_closed_stale=True, bindings_preserved=True,
             current_selection=True, framebuffer_resize=True, no_unlock=True)
        owner_panel.server.shutdown(socket.SHUT_RDWR)
        assert panel.wait(timeout=5) == 0, 'owner panel survived its controller channel'
        emit('owner-channel-close', child_exited=True)
    finally:
        owner_panel.close()
        ipc.close()
        if engine.state['windows'].get(second, {}).get('state') == 'open':
            engine.dispatch('tabs', {'scope': second, 'action': 'release'})
