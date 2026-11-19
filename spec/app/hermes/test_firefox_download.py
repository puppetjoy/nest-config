"""Exact download custody at the public adapter; native fetch is in the canary."""
import base64
import hashlib
import json
from pathlib import Path

import pytest
from test_secure_browser_firefox_ui import load_tool


@pytest.mark.parametrize('mutation', [None, 'checksum', 'size', 'oversize', 'invalid_base64'])
def test_download_custody_and_refusals(tmp_path, monkeypatch, mutation):
    module, registry = load_tool()
    module.CONTROL_MODE = 'firefox-windows-v3'
    assert 'secure_browser_download' in registry.names
    monkeypatch.setattr(module, 'get_hermes_home', lambda: tmp_path)
    raw = bytes(range(256)) if mutation != 'oversize' else b'x' * 1048577
    receipt = {'status': 'ok', 'filename': '../../fixture.gpx', 'content_type': 'application/gpx+xml',
               'data': base64.b64encode(raw).decode(), 'sha256': hashlib.sha256(raw).hexdigest(), 'size_bytes': len(raw)}
    if mutation == 'checksum':
        receipt['sha256'] = '0' * 64
    if mutation == 'size':
        receipt['size_bytes'] += 1
    if mutation == 'invalid_base64':
        receipt['data'] = '!not-base64!'
    seen = []
    def bridge(command, payload):
        seen.append((command, payload))
        return dict(receipt)
    monkeypatch.setattr(module, '_bridge', bridge)
    result = json.loads(module.secure_browser_download_tool({'selector': 'a#original'}))
    assert seen == [('download', {'selector': 'a#original'})]
    if mutation is None:
        path = Path(result['file_path'])
        assert path.is_relative_to(tmp_path)
        assert path.read_bytes() == raw
        assert path.stat().st_mode & 0o777 == 0o600
        assert result['sha256'] == hashlib.sha256(raw).hexdigest()
        assert 'data' not in result
    else:
        assert result['status'] == 'error'
        assert not list(tmp_path.rglob('*.gpx'))
