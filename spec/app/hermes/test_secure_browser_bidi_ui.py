#!/usr/bin/env python3
"""Source-level regression fixtures for the opt-in Firefox BiDi/UI adapter."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[3]
MODULE = ROOT / "files/app/hermes/secure_browser_bidi.py"


def load():
    tools = types.ModuleType("tools")
    tools.__path__ = []
    legacy = types.ModuleType("tools.secure_browser_legacy_support")
    class Session:
        @staticmethod
        def _bidi_value(value):
            if value["type"] == "object":
                return {k: Session._bidi_value(v) for k, v in value["value"]}
            return value.get("value")
    legacy.CdpSession = Session
    tools.secure_browser_legacy_support = legacy
    sys.modules["tools"] = tools
    sys.modules["tools.secure_browser_legacy_support"] = legacy
    spec = importlib.util.spec_from_file_location("tools.secure_browser_bidi", MODULE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module, legacy


class Browser:
    protocol = "bidi"
    def __init__(self, contexts):
        self.contexts = contexts
        self.calls = []
    def _bidi_contexts(self):
        return self.contexts
    def _bidi(self, method, payload):
        self.calls.append((method, payload))
        if "querySelectorAll" in payload["expression"]:
            return {"result": {"type": "object", "value": [["x", {"type": "number", "value": 127}], ["y", {"type": "number", "value": 438}]]}}
        return {"result": {"type": "string", "value": "Unrelated shop"}}


def snapshot(url="https://fixture.example/shop"):
    return {"url": url, "tabs": [{"selected": True}], "title": "Unrelated shop"}


def test_unambiguous_visible_page_query_and_secret_guard():
    module, legacy = load()
    browser = Browser([{"context": "visible", "url": "https://fixture.example/shop?order=private"}])
    legacy._with_browser = lambda fn: fn(browser)
    result = module.query(snapshot(), "document.title")
    assert result["value"] == "Unrelated shop"
    assert browser.calls[0][1]["target"] == {"context": "visible"}
    for expression in ("document.cookie", "localStorage.getItem('x')", "document.querySelector('input[type=password]').value", "document.querySelector(\"#add\").click()"):
        try:
            module.query(snapshot(), expression)
        except ValueError:
            pass
        else:
            raise AssertionError("secret query was accepted")


def test_duplicate_url_fails_without_script_execution():
    module, legacy = load()
    browser = Browser([{"context": "a", "url": "https://fixture.example/shop"}, {"context": "b", "url": "https://fixture.example/shop"}])
    legacy._with_browser = lambda fn: fn(browser)
    try:
        module.query(snapshot(), "document.title")
    except RuntimeError as exc:
        assert "ambiguous" in str(exc)
    else:
        raise AssertionError("ambiguous tab was accepted")
    assert browser.calls == []


def test_visible_selector_point_uses_fixed_script():
    module, legacy = load()
    browser = Browser([{"context": "visible", "url": "https://fixture.example/shop"}])
    legacy._with_browser = lambda fn: fn(browser)
    assert module.selector_point(snapshot(), "label[for=color]") == [127, 438]
    assert browser.calls[0][1]["target"] == {"context": "visible"}
    assert 'label[for=color]' in browser.calls[0][1]["expression"]


def test_selector_click_keeps_ui_action_key_and_type_keeps_ui_value_redacted():
    import json
    from test_secure_browser_firefox_ui import load_tool
    tool, _ = load_tool()
    tool.CONTROL_MODE = "firefox-bidi-ui-v2"
    calls = []
    def bridge(command, payload, **_kw):
        calls.append((command, payload))
        if command == "snapshot":
            return snapshot()
        return {"status": "delivered", "typed_chars": len(payload.get("text", ""))}
    tool._bridge = bridge
    bidi = types.ModuleType("tools.secure_browser_bidi")
    bidi.selector_point = lambda _snap, _selector, **_kw: [127, 438]
    sys.modules["tools.secure_browser_bidi"] = bidi
    click = json.loads(tool.secure_browser_click_tool({"selector": "label[for=color]", "workflow_id": "test", "action_key": "once"}))
    assert click["status"] == "delivered"
    assert calls[-1] == ("click", {"workflow_id": "test", "coordinate": [127, 438], "action_key": "once", "max_wait_seconds": None})
    typed = json.loads(tool.secure_browser_type_tool({"selector": "#message", "workflow_id": "test", "text": "hello"}))
    assert typed["typed_chars"] == 5
    assert calls[-1] == ("type", {"workflow_id": "test", "coordinate": [127, 438], "text": "hello"})


if __name__ == "__main__":
    test_unambiguous_visible_page_query_and_secret_guard()
    test_duplicate_url_fails_without_script_execution()
    test_visible_selector_point_uses_fixed_script()
    test_selector_click_keeps_ui_action_key_and_type_keeps_ui_value_redacted()
    print("four Firefox BiDi/UI source fixtures passed")
