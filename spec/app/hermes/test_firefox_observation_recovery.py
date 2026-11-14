"""Native timeout custody: late receipts never justify operation replay."""
import json

import pytest

from test_firefox_creation_recovery import resumable, wire_controller
from test_firefox_windows import A, ROOT, windows


def test_managed_canvas_policy_avoids_stalled_remote_checkpoint():
    import re
    import textwrap
    source = (ROOT / 'data/kubernetes/app/firefox.yaml').read_text()
    policy = json.loads(textwrap.dedent(re.search(
        r'\.firefox_policy: &firefox_policy \|-\n(.*?)\n\n', source, re.S).group(1)))
    assert policy['policies']['Preferences']['gfx.canvas.accelerated'] == {
        'Value': False, 'Status': 'locked'}


def test_exhausted_wait_preserves_late_correlated_receipt_without_replay(tmp_path, monkeypatch):
    controller, native, socket, client = wire_controller(tmp_path)
    resumable(controller, monkeypatch)
    recv = socket.recv
    waits = []
    failures = 2

    def delayed(**kw):
        nonlocal failures
        if native.created:
            waits.append(kw['timeout'])
            if failures:
                failures -= 1
                raise TimeoutError('synthetic translator stall delays the native receipt')
        return recv(**kw)

    socket.recv = delayed
    with pytest.raises(windows.ControlError) as failed:
        controller.acquire(A)
    assert failed.value.outcome == 'uncertain'
    result = controller.dispatch('tabs', {'scope': A, 'action': 'recover'})
    assert result['recovery']['reason'] == 'correlated_reply_wait_exhausted'
    assert not socket.closed, 'exhaustion must preserve the only correlated observer'
    assert client.pending is not None
    assert client.pending['wait_exhausted'] is True
    # Unrelated commands cannot restart the wait or pass the pending creation.
    failures = 1
    sent = list(socket.sent)
    with pytest.raises(TimeoutError):
        client._bidi('browsingContext.getTree')
    assert socket.sent == sent
    assert waits[-1] == 0
    # A later explicit read can consume an already-queued reply, without
    # restarting a full wait or sending another create/input command.
    result = controller.dispatch('tabs', {'scope': A, 'action': 'recover'})
    assert result['recovery']['recovery_state'] == 'verified'
    assert waits[2] == 0
    assert json.loads(controller.path.read_text())['windows'][A]['context'] == 'context-1'
    assert sum(c['method'] == 'browsingContext.create' for c in socket.sent) == 1
    assert native.created == 1
    assert not any(c['method'].startswith('input.') for c in socket.sent)


def test_exhausted_receipt_poll_bounds_unrelated_frames_without_sending(tmp_path, monkeypatch):
    controller, native, socket, client = wire_controller(tmp_path)
    resumable(controller, monkeypatch)
    recv = socket.recv
    def delayed(**kw):
        if native.created:
            raise TimeoutError('synthetic reply remains pending')
        return recv(**kw)
    socket.recv = delayed
    with pytest.raises(windows.ControlError):
        controller.acquire(A)
    controller.dispatch('tabs', {'scope': A, 'action': 'recover'})
    before = list(socket.sent)
    frames = []
    def unrelated(**kw):
        frames.append(kw['timeout'])
        return json.dumps({'type': 'success', 'id': -1, 'result': {'context': 'foreign'}})
    socket.recv = unrelated
    result = controller.dispatch('tabs', {'scope': A, 'action': 'recover'})
    assert result['recovery']['reason'] == 'correlated_reply_wait_exhausted'
    assert frames == [0] * 64
    assert socket.sent == before
    assert 'context' not in controller.state['windows'][A]
    assert not socket.closed
    assert native.created == 1
