#!/usr/bin/env python3
"""Source-level regression fixtures for the opt-in Firefox BiDi/UI adapter."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
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
            if value["type"] == "array":
                return [Session._bidi_value(item) for item in value["value"]]
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
    return {"url": url, "tabs": [{"selected": True, "name": "Unrelated shop"}], "title": "Unrelated shop", "browser_generation": 100}


def test_unambiguous_visible_page_query_and_secret_guard():
    module, legacy = load()
    browser = Browser([{"context": "visible", "url": "https://fixture.example/shop?order=private"}])
    legacy._with_browser = lambda fn: fn(browser)
    result = module.query(snapshot("https://fixture.example/shop?order=private"), "document.title")
    assert result["value"] == "Unrelated shop"
    assert browser.calls[0][1]["target"] == {"context": "visible"}
    for expression in ("document.cookie", "localStorage.getItem('x')", "document.querySelector('input[type=password]').value", "document.querySelector(\"#add\").click()"):
        try:
            module.query(snapshot(), expression)
        except ValueError:
            pass
        else:
            raise AssertionError("secret query was accepted")


def test_general_collection_read_is_bounded_and_redacts_each_field():
    module, legacy = load()
    expression = 'document.querySelectorAll(".cart-row input, .cart-row .variant").value'
    script = module._read_script(expression)
    assert "nodes.length" in script and ".slice(0,120)" in script
    assert "input[type=password],input[type=hidden]" in script
    assert "e.value" in script
    browser = Browser([{"context": "visible", "url": "https://fixture.example/shop"}])
    def evaluate(method, payload):
        assert method == "script.evaluate" and payload["expression"] == script
        return {"result": {"type": "object", "value": [
            ["total", {"type": "number", "value": 3}],
            ["values", {"type": "array", "value": [
                {"type": "string", "value": "Gray/Soft"},
                {"type": "string", "value": "1"},
                {"type": "string", "value": "<redacted>"},
            ]}],
        ]}}
    browser._bidi = evaluate
    legacy._with_browser = lambda fn: fn(browser)
    result = module.query(snapshot(), expression)
    assert result["value"] == {"total": 3, "values": ["Gray/Soft", "1", "<redacted>"]}
    for forbidden in ('document.querySelectorAll("input[type=password]").value',
                      'document.querySelectorAll(".cart-row").click()'):
        try:
            module.query(snapshot(), forbidden)
        except ValueError:
            pass
        else:
            raise AssertionError("unsafe collection expression was accepted")

def test_site_independent_dom_snapshot_is_generated_and_bounded():
    module, legacy = load()
    script = module._read_script("document.domSnapshot")
    assert "querySelectorAll('*')" in script and "max=120" in script
    assert "input[type=password],input[type=hidden]" in script
    assert "e.isContentEditable" in script and "e.value" not in script
    browser = Browser([{"context": "visible", "url": "https://fixture.example/shop"}])
    def evaluate(method, payload):
        assert method == "script.evaluate" and payload["expression"] == script
        return {"result": {"type": "object", "value": [
            ["total", {"type": "number", "value": 150}],
            ["nodes", {"type": "array", "value": [
                {"type": "object", "value": [["tag", {"type": "string", "value": "button"}],
                                              ["text", {"type": "string", "value": "Select size"}]]},
            ]}],
        ]}}
    browser._bidi = evaluate
    legacy._with_browser = lambda fn: fn(browser)
    result = module.query(snapshot(), "document.domSnapshot")
    assert result["truncated"] is True
    assert result["value"]["nodes"][0] == {"tag": "button", "text": "Select size"}
    try:
        module.query(snapshot(), "document.domSnapshot;fetch('https://other.example/')")
    except ValueError:
        pass
    else:
        raise AssertionError("caller-supplied script accepted")

def test_dom_snapshot_executes_without_exporting_credential_values():
    module, _ = load()
    source = """
const Node={TEXT_NODE:3};
function element(tag, opts={}) {
  return {localName:tag,name:opts.name||'',id:opts.id||'',type:opts.type||'',
    disabled:false,checked:false,isContentEditable:false,labels:[],parentElement:null,
    childNodes:[{nodeType:3,textContent:opts.text||''}],
    getAttribute:k=>opts[k]||null,closest:()=>null,
    matches:s=>s==='input,textarea,select'?tag==='input':s==='input[type=password],input[type=hidden]'?opts.type==='password':false,
    getBoundingClientRect:()=>({width:100,height:30,bottom:40,right:110,top:10,left:10})};
}
const nodes=[element('button',{text:'Choose size'}),
  element('input',{name:'password',type:'password',value:'NEVER_EXPORT_ME'}),
  element('input',{name:'publicField',type:'text',value:'NEVER_EXPORT_VALUE'})];
const document={body:{querySelectorAll:()=>nodes}};
const getComputedStyle=()=>({display:'block',visibility:'visible'});
const innerHeight=800,innerWidth=1200;
"""
    result = subprocess.run(["node", "-e", source + "\nconsole.log(JSON.stringify(" + module.DOM_SNAPSHOT + "));"],
                            capture_output=True, text=True, check=True)
    assert "NEVER_EXPORT" not in result.stdout
    parsed = json.loads(result.stdout)
    assert parsed["total"] == 3 and len(parsed["nodes"]) == 2
    assert parsed["nodes"][0]["text"] == "Choose size"
    assert parsed["nodes"][1]["control"]["type"] == "text"


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


def test_same_path_different_query_fails_closed():
    module, legacy = load()
    browser = Browser([{"context": "wrong", "url": "https://fixture.example/shop?order=other"}])
    legacy._with_browser = lambda fn: fn(browser)
    try:
        module.query(snapshot("https://fixture.example/shop?order=private"), "document.title")
    except RuntimeError as exc:
        assert "absent or ambiguous" in str(exc)
    else:
        raise AssertionError("same-path wrong-context query was accepted")
    assert browser.calls == []


def test_visible_selector_point_uses_fixed_script():
    module, legacy = load()
    browser = Browser([{"context": "visible", "url": "https://fixture.example/shop"}])
    legacy._with_browser = lambda fn: fn(browser)
    assert module.selector_point(snapshot(), "label[for=color]") == [127, 438]
    assert browser.calls[0][1]["target"] == {"context": "visible"}
    assert 'label[for=color]' in browser.calls[0][1]["expression"]
    assert "control is disabled or read-only" in browser.calls[0][1]["expression"]


def test_status_requires_live_bidi_not_just_launch_configuration():
    import json
    from test_secure_browser_firefox_ui import load_tool
    module, legacy = load()
    tool, _ = load_tool()
    tool.CONTROL_MODE = "firefox-bidi-ui-v2"
    tool._bridge = lambda _cmd, _payload: {"launch_protocol": "firefox-bidi-ui-v2", "status": "ok"}
    legacy._with_browser = lambda _fn: (_ for _ in ()).throw(RuntimeError("endpoint unavailable"))
    status = json.loads(tool.secure_browser_status_tool({}))
    assert status["control_mode_matches_browser"] is False
    assert status["compatibility"]["dom_selectors"] is False
    assert status["instrumentation"]["bidi"] is False
    legacy._with_browser = lambda fn: fn(Browser([]))
    status = json.loads(tool.secure_browser_status_tool({}))
    assert status["control_mode_matches_browser"] is True
    assert status["compatibility"]["dom_selectors"] is True


def test_selector_click_keeps_ui_action_key_and_type_keeps_ui_value_redacted():
    import json
    from test_secure_browser_firefox_ui import load_tool
    tool, _ = load_tool()
    tool.CONTROL_MODE = "firefox-bidi-ui-v2"
    assert json.loads(tool.secure_browser_guardrail_check_tool({"operation": "browse"}))["protocol"] == "firefox-bidi-ui-v2"
    assert json.loads(tool.secure_browser_guardrail_check_tool({"operation": "javascript_query"}))["status"] == "blocked"
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
    missing_key = json.loads(tool.secure_browser_click_tool({"selector": "label[for=color]", "workflow_id": "test"}))
    assert missing_key["status"] == "error" and "action_key" in missing_key["message"]
    assert calls == []
    click = json.loads(tool.secure_browser_click_tool({"selector": "label[for=color]", "workflow_id": "test", "action_key": "once"}))
    assert click["status"] == "delivered"
    assert calls[-1] == ("click", {"workflow_id": "test", "coordinate": [127, 438], "expected_url": "https://fixture.example/shop", "expected_generation": 100, "expected_tab": "Unrelated shop", "action_key": "once", "max_wait_seconds": None})
    typed = json.loads(tool.secure_browser_type_tool({"selector": "#message", "workflow_id": "test", "text": "hello"}))
    assert typed["typed_chars"] == 5
    assert calls[-1] == ("type", {"workflow_id": "test", "coordinate": [127, 438], "expected_url": "https://fixture.example/shop", "expected_generation": 100, "expected_tab": "Unrelated shop", "text": "hello"})


def test_ui_bridge_rejects_displaced_tab_and_offscreen_coordinate():
    from test_firefox_ui_bridge import load_bridge
    bridge = load_bridge()
    bridge._snapshot = lambda: snapshot()
    bridge._xdotool = lambda *args: "1365 768" if args == ("getdisplaygeometry",) else ""
    expected = {"expected_url": "https://fixture.example/shop", "expected_generation": 100, "expected_tab": "Unrelated shop"}
    bridge._assert_selector_precondition(expected)
    for changed in ({"expected_url": "https://other.example/"}, {"expected_generation": 99}, {"expected_tab": "Different"}):
        try:
            bridge._assert_selector_precondition({**expected, **changed})
        except RuntimeError:
            pass
        else:
            raise AssertionError("stale selector precondition passed")
    assert bridge._assert_screen_coordinate([127, 438]) == (127, 438)
    for coordinate in ([-1, 1], [1365, 438], [10, 768]):
        try:
            bridge._assert_screen_coordinate(coordinate)
        except ValueError:
            pass
        else:
            raise AssertionError("offscreen coordinate accepted")


if __name__ == "__main__":
    test_unambiguous_visible_page_query_and_secret_guard()
    test_general_collection_read_is_bounded_and_redacts_each_field()
    test_site_independent_dom_snapshot_is_generated_and_bounded()
    test_dom_snapshot_executes_without_exporting_credential_values()
    test_duplicate_url_fails_without_script_execution()
    test_same_path_different_query_fails_closed()
    test_visible_selector_point_uses_fixed_script()
    test_status_requires_live_bidi_not_just_launch_configuration()
    test_selector_click_keeps_ui_action_key_and_type_keeps_ui_value_redacted()
    test_ui_bridge_rejects_displaced_tab_and_offscreen_coordinate()
    print("ten Firefox BiDi/UI source fixtures passed")
