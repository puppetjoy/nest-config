import contextlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import struct
import threading

ROOT = Path(__file__).resolve().parents[3] / "files/firefox-browser"
spec = importlib.util.spec_from_file_location("owner_desktop", ROOT / "owner-desktop.py")
owner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(owner)


class FakeWindows:
    def __init__(self):
        self.epoch = "epoch-a"
        self.state = {"windows": {
            "owner": {"state": "open", "epoch": "epoch-a", "context": "c0", "window": "w0", "owner": True, "viewer": "synthetic-owner-capability-only"},
            "kanban:board:t_123": {"state": "open", "epoch": "epoch-a", "context": "c1", "window": "w1"},
            "kanban:board:t_old": {"state": "closed", "epoch": "epoch-a", "context": "cx", "window": "wx"},
        }}
        self.calls = []
        self.lock = threading.RLock()
    def operation(self):
        return self.lock
    def _tree(self):
        return [{'context': record['context'], 'clientWindow': record['window']}
                for record in self.state['windows'].values()
                if record['state'] == 'open' and record['epoch'] == self.epoch]
    def _resolve(self, record):
        self.calls.append(("resolve", record["context"]))
        if record.get("epoch") != self.epoch or record.get("state") != "open":
            raise RuntimeError("stale")
        return {"context": record["context"], "clientWindow": record["window"]}
    def _call(self, method, params):
        self.calls.append((method, params))
        return {}


def test_list_shows_only_open_exact_epoch_scope_and_no_page_data():
    windows = FakeWindows()
    entries = owner.visible_windows(windows)
    assert entries == [{"scope": "owner", "label": "Owner window"},
                       {"scope": "kanban:board:t_123", "label": "Task board:t_123"}]
    assert windows.calls == []


def test_select_validates_exact_binding_then_activates_without_mutating_registry(monkeypatch):
    windows = FakeWindows()
    windows.state['controller'] = {'session': 'fixture', 'pid': 123}
    before = json.dumps(windows.state, sort_keys=True)
    mapped = []
    monkeypatch.setattr(owner, 'native_window_id', lambda engine, native: mapped.append(native) or '999')
    monkeypatch.setattr(owner, 'focus_native_window', lambda xid, pid: windows.calls.append(('focus', xid, pid)))
    owner.select_window(windows, "kanban:board:t_123", "epoch-a")
    assert mapped == ['w1']
    assert windows.calls == [("resolve", "c1"), ("resolve", "c1"), ('focus', '999', 123)]
    assert json.dumps(windows.state, sort_keys=True) == before


def test_stale_selection_refuses_without_fallback_or_activation():
    windows = FakeWindows()
    windows.epoch = "epoch-b"
    try:
        owner.select_window(windows, "kanban:board:t_123", "epoch-a")
    except ValueError:
        pass
    else:
        assert False, "stale epoch must refuse"
    assert not any(call[0] == "browsingContext.activate" for call in windows.calls)


def test_peer_auth_and_malformed_messages_are_rejected(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    sock_path = 'owner.sock'
    windows = FakeWindows()
    server = owner.OwnerSocket(sock_path, windows, peer_uid=os.getuid())
    server.start()
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(sock_path)
        client.sendall(b'{"command":"list","owner_capability":"synthetic-owner-capability-only"}\n')
        response = json.loads(client.makefile().readline())
        client.close()
        assert response["status"] == "ok"
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(sock_path)
        client.sendall(b'{"command":"delete"}\n')
        response = json.loads(client.makefile().readline())
        client.close()
        assert response == {"status": "error", "message": "Window unavailable or selection uncertain. No automatic retry or fallback."}
    finally:
        server.close()


def test_peer_with_different_uid_is_rejected(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    server = owner.OwnerSocket('foreign.sock', FakeWindows(), peer_uid=os.getuid() + 1)
    server.start()
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(server.path)
        client.sendall(b'{"command":"list"}\\n')
        try:
            received = client.recv(1)
        except ConnectionResetError:
            received = b""
        assert received == b""
        client.close()
    finally:
        server.close()


def test_owner_socket_oversize_refuses(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    server = owner.OwnerSocket('owner.sock', FakeWindows(), peer_uid=os.getuid())
    server.start()
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(server.path)
        client.sendall(b"x" * 4097 + b"\\n")
        assert json.loads(client.makefile().readline()) == {"status": "error", "message": "Window unavailable or selection uncertain. No automatic retry or fallback."}
        client.close()
    finally:
        server.close()


def test_chrome_identity_read_restores_content_even_after_failure(monkeypatch):
    import sys
    from types import SimpleNamespace
    import pytest
    windows = FakeWindows()
    windows.state['controller'] = {'session': 'fixture-session'}
    calls = []
    def driver(method, path, data):
        calls.append((method, path, data))
        if path.endswith('/execute/sync'):
            raise RuntimeError('synthetic observation failure')
    monkeypatch.setitem(sys.modules, 'firefox_windows', SimpleNamespace(driver_request=driver))
    with pytest.raises(RuntimeError):
        owner.native_window_id(windows, 'exact-native-id')
    assert calls[0][2] == {'context': 'chrome'}
    assert calls[1][2]['args'] == ['exact-native-id']
    assert 'getWindowById(arguments[0])' in calls[1][2]['script']
    assert calls[-1][2] == {'context': 'content'}
    assert len(calls) == 3


def test_wrong_x_process_refuses_before_focus_or_native_library(monkeypatch):
    import subprocess
    import ctypes
    import pytest
    monkeypatch.setattr(subprocess, 'check_output', lambda *a, **kw: '_NET_WM_PID(CARDINAL) = 999\n')
    monkeypatch.setattr(ctypes, 'CDLL', lambda *a: (_ for _ in ()).throw(AssertionError('focus started')))
    with pytest.raises(ValueError, match='process changed'):
        owner.focus_native_window('1234', 123)


def test_closed_and_foreign_epoch_selection_never_resolves_or_focuses():
    import pytest
    windows = FakeWindows()
    for scope, epoch in [('kanban:board:t_old', windows.epoch), ('kanban:board:t_123', 'old'), ('missing', windows.epoch)]:
        with pytest.raises(ValueError):
            owner.select_window(windows, scope, epoch)
    assert not windows.calls


def test_owner_directory_is_not_a_public_agent_command():
    spec = importlib.util.spec_from_file_location('owner_endpoint_contract', ROOT / 'firefox-bridge-server.py')
    endpoint = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(endpoint)
    import pytest
    for command in ['list', 'select', 'owner_windows', 'owner_focus']:
        with pytest.raises(ValueError):
            endpoint.validate({'command': command, 'payload': {'scope': 'owner'}})

def test_directory_requires_exact_owner_capability_not_missing_or_task_link(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    windows = FakeWindows()
    windows.state['windows']['kanban:board:t_123']['viewer'] = 'synthetic-task-capability-only'
    server = owner.OwnerSocket('owner.sock', windows, peer_uid=os.getuid())
    server.start()
    try:
        for capability in [None, '', 'synthetic-task-capability-only', 'wrong-owner-capability-only']:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.connect(server.path)
                body = {'command': 'list'}
                if capability is not None:
                    body['owner_capability'] = capability
                client.sendall(json.dumps(body).encode() + b'\n')
                with client.makefile() as stream:
                    result = json.loads(stream.readline())
            assert result['status'] == 'error' and 'windows' not in result
            assert 'viewer' not in json.dumps(result)
        assert not windows.calls
    finally:
        server.close()


def test_native_panel_lists_without_task_or_owner_capability_and_tracks_real_focus(monkeypatch):
    import subprocess
    windows = FakeWindows()
    before = json.dumps(windows.state, sort_keys=True)
    mapped = []
    monkeypatch.setattr(subprocess, 'check_output', lambda *a, **kw: '101\n')
    monkeypatch.setattr(owner, 'native_window_id', lambda engine, window: mapped.append(window) or {'w0': '100', 'w1': '101'}[window])
    panel = owner.OwnerPanel(windows)
    try:
        result = panel.dispatch({'command': 'list'})
        assert result['status'] == 'ok' and result['current'] == 'kanban:board:t_123'
        assert result['windows'] == owner.visible_windows(windows)
        assert 'viewer' not in json.dumps(result) and 'capability' not in json.dumps(result)
        assert mapped == ['w0', 'w1']
        assert panel.dispatch({'command': 'list'}) == result
        assert mapped == ['w0', 'w1']  # No repeated privileged identity reads.
        windows.state['windows']['kanban:board:t_123']['state'] = 'closed'
        result = panel.dispatch({'command': 'list'})
        assert result['current'] is None
        assert result['windows'] == [{'scope': 'owner', 'label': 'Owner window'}]
        windows.state['windows']['kanban:board:t_123']['state'] = 'open'
        assert json.dumps(windows.state, sort_keys=True) == before
    finally:
        panel.close()


def test_native_panel_select_uses_exact_binding_and_rejects_capability_injection(monkeypatch):
    import pytest
    windows = FakeWindows()
    selections = []
    monkeypatch.setattr(owner, 'select_window', lambda *args: selections.append(args))
    panel = owner.OwnerPanel(windows)
    try:
        request = {'command': 'select', 'scope': 'kanban:board:t_123', 'epoch': windows.epoch}
        assert panel.dispatch(request) == {'status': 'ok'}
        assert selections == [(windows, request['scope'], windows.epoch)]
        for invalid in [None, {}, {'command': 'input'}, {'command': 'list', 'owner_capability': 'anything'},
                        {**request, 'task_token': 'anything'}, {'command': 'select', 'scope': 'owner'}]:
            with pytest.raises(ValueError):
                panel.dispatch(invalid)
        assert len(selections) == 1
    finally:
        panel.close()


def test_native_panel_channel_is_unnamed_and_closes_without_replaying_selection(monkeypatch):
    windows = FakeWindows()
    selections = []
    panel = owner.OwnerPanel(windows)
    monkeypatch.setattr(owner, 'select_window', lambda *args: selections.append(args))
    assert panel.server.getsockname() == panel.client.getsockname() == ''
    thread = threading.Thread(target=panel.serve)
    thread.start()
    try:
        panel.client.sendall(json.dumps({'command': 'select', 'scope': 'owner', 'epoch': windows.epoch}).encode() + b'\n')
        assert json.loads(panel.client.recv(4096)) == {'status': 'ok'}
        panel.client.close()
        thread.join(timeout=2)
        assert not thread.is_alive()
        assert selections == [(windows, 'owner', windows.epoch)]
    finally:
        panel.close()


def test_fresh_owner_desktop_needs_no_agent_acquisition_and_does_not_create_a_lease(monkeypatch):
    import subprocess
    windows = FakeWindows()
    windows.state['windows'].clear()
    before = json.dumps(windows.state, sort_keys=True)
    monkeypatch.setattr(windows, '_tree', lambda: [{'context': 'initial', 'clientWindow': 'native-initial'}])
    monkeypatch.setattr(subprocess, 'check_output', lambda *a, **kw: '100\n')
    monkeypatch.setattr(owner, 'native_window_id', lambda *a: '100')
    panel = owner.OwnerPanel(windows)
    try:
        result = panel.dispatch({'command': 'list'})
        assert result['windows'] == [{'scope': 'desktop:native-initial', 'label': 'Owner window'}]
        assert result['current'] == 'desktop:native-initial'
        assert json.dumps(windows.state, sort_keys=True) == before
        assert windows.calls == []
    finally:
        panel.close()


def test_native_owner_created_window_is_discovered_and_selected_without_claiming_it(monkeypatch):
    import subprocess
    import pytest
    windows = FakeWindows()
    windows.state['controller'] = {'pid': 123}
    before = json.dumps(windows.state, sort_keys=True)
    original = windows._tree
    extra = [{'context': 'c2', 'clientWindow': 'w2'}]
    monkeypatch.setattr(windows, '_tree', lambda: original() + extra)
    monkeypatch.setattr(subprocess, 'check_output', lambda *a, **kw: '102\n')
    monkeypatch.setattr(owner, 'native_window_id', lambda engine, window: {'w0': '100', 'w1': '101', 'w2': '102'}[window])
    focused = []
    monkeypatch.setattr(owner, 'focus_native_window', lambda *args: focused.append(args))
    panel = owner.OwnerPanel(windows)
    try:
        listing = panel.dispatch({'command': 'list'})
        assert listing['windows'][-1] == {'scope': 'desktop:w2', 'label': 'Owner window 2'}
        assert listing['current'] == 'desktop:w2'
        selection = {'command': 'select', 'scope': 'desktop:w2', 'epoch': windows.epoch}
        assert panel.dispatch(selection) == {'status': 'ok'}
        assert focused == [('102', 123)]
        extra.clear()
        assert all(item['scope'] != 'desktop:w2' for item in panel.dispatch({'command': 'list'})['windows'])
        with pytest.raises(ValueError):
            panel.dispatch(selection)
        assert focused == [('102', 123)]
        assert json.dumps(windows.state, sort_keys=True) == before
    finally:
        panel.close()


def test_native_panel_generation_and_closed_window_refusals_preserve_registry():
    import pytest
    windows = FakeWindows()
    panel = owner.OwnerPanel(windows)
    before = json.dumps(windows.state, sort_keys=True)
    try:
        for scope, epoch in [('owner', 'old'), ('kanban:board:t_old', windows.epoch), ('foreign', windows.epoch)]:
            with pytest.raises(ValueError):
                panel.dispatch({'command': 'select', 'scope': scope, 'epoch': epoch})
        assert windows.calls == []
        assert json.dumps(windows.state, sort_keys=True) == before
    finally:
        panel.close()
