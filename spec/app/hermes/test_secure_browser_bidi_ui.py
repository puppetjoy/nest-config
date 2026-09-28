#!/usr/bin/env python3
"""Source-level regression fixtures for the opt-in Firefox BiDi/UI adapter."""
from __future__ import annotations

import importlib.util
import contextlib
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


def test_origin_address_bar_without_slash_matches_bidi_canonical_url():
    module, legacy = load()
    browser = Browser([{"context": "visible", "url": "https://example.com/"}])
    legacy._with_browser = lambda fn: fn(browser)
    result = module.query(snapshot("https://example.com"), "document.title")
    assert result["status"] == "ok"
    assert browser.calls[0][1]["target"] == {"context": "visible"}
    assert module._url_identity("https://example.com?cart=one") == "https://example.com/?cart=one"
    assert module._url_identity("https://example.com/?cart=two") != module._url_identity("https://example.com?cart=one")


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
    assert "e.isContentEditable" in script and "row.control.value" in script
    assert "input[type=file]" in script
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
    value:opts.value||'',childNodes:[{nodeType:3,textContent:opts.text||''}],
    getAttribute:k=>opts[k]||null,closest:()=>null,
    matches:s=>s==='input,textarea,select'?tag==='input':s==='input[type=password],input[type=hidden]'?opts.type==='password':false,
    getBoundingClientRect:()=>({width:100,height:30,bottom:40,right:110,top:10,left:10})};
}
const nodes=[element('button',{text:'Choose size'}),
  element('input',{name:'password',type:'password',value:'NEVER_EXPORT_ME'}),
  element('input',{name:'quantity',type:'number',value:'2','aria-label':'Quantity'})];
const document={body:{querySelectorAll:()=>nodes}};
const getComputedStyle=()=>({display:'block',visibility:'visible'});
const innerHeight=800,innerWidth=1200;
"""
    result = subprocess.run(["node", "-e", source + "\nconsole.log(JSON.stringify(" + module._read_script("document.domSnapshot") + "));"],
                            capture_output=True, text=True, check=True)
    assert "NEVER_EXPORT" not in result.stdout
    parsed = json.loads(result.stdout)
    assert parsed["total"] == 3 and len(parsed["nodes"]) == 2
    assert parsed["nodes"][0]["text"] == "Choose size"
    assert parsed["nodes"][1]["control"] == {"type": "number", "disabled": False, "checked": False, "value": "2"}
    assert parsed["nodes"][1]["label"] == "Quantity"

def test_dom_snapshot_paginates_large_unrelated_page_without_skipping_nodes():
    module, _ = load()
    source = """
const Node={TEXT_NODE:3};
const all=Array.from({length:260},(_,i)=>({localName:'p',name:'',id:'',
  isContentEditable:false,parentElement:null,childNodes:[{nodeType:3,textContent:'item '+i}],
  getAttribute:()=>null,closest:()=>null,matches:()=>false,
  getBoundingClientRect:()=>({width:10,height:10,bottom:20,right:20,top:10,left:10})}));
const document={body:{querySelectorAll:()=>all}};
const getComputedStyle=()=>({display:'block',visibility:'visible'});
const innerHeight=800,innerWidth=1200;
"""
    observed, offset = [], 0
    while offset is not None:
        script = module._read_script(f"document.domSnapshot({offset})")
        result = subprocess.run(["node", "-e", source + "\nconsole.log(JSON.stringify(" + script + "));"],
                                capture_output=True, text=True, check=True)
        page = json.loads(result.stdout)
        observed.extend(row["text"] for row in page["nodes"])
        assert page["total"] == 260
        assert page["nextOffset"] is None or page["nextOffset"] > offset
        offset = page["nextOffset"]
    assert observed == [f"item {i}" for i in range(260)]
    for malformed in ("document.domSnapshot(-1)", "document.domSnapshot(01)", "document.domSnapshot(100001)"):
        try:
            module._read_script(malformed)
        except ValueError:
            pass
        else:
            raise AssertionError("malformed or excessive offset accepted")


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

def test_redacted_url_with_query_maps_only_unique_visible_context():
    module, legacy = load()
    browser = Browser([{"context": "visible", "url": "https://fixture.example/shop?order=private"}])
    legacy._with_browser = lambda fn: fn(browser)
    assert module.query(snapshot(), "document.title")["value"] == "Unrelated shop"
    browser.contexts.append({"context": "other", "url": "https://fixture.example/shop?order=other"})
    try:
        module.query(snapshot(), "document.title")
    except RuntimeError as exc:
        assert "ambiguous" in str(exc)
    else:
        raise AssertionError("same-path tab ambiguity accepted")


def test_selector_point_is_not_exposed_and_secrets_are_redacted():
    module, legacy = load()
    assert not hasattr(module, "selector_point")
    assert "847261" not in str(module._safe_result({"text": "Your verification code is 847261", "other": "847261"}))
    try:
        module._read_script("document.body.innerText")
    except ValueError:
        pass
    else:
        raise AssertionError("unfiltered body text accepted")


def test_status_requires_live_bidi_not_just_launch_configuration():
    import json
    from test_secure_browser_firefox_ui import load_tool
    module, legacy = load()
    tool, _ = load_tool()
    tool.CONTROL_MODE = "firefox-bidi-ui-v2"
    tool._bridge = lambda _cmd, _payload: {"launch_protocol": "firefox-bidi-ui-v2", "native_element_available": True, "status": "ok"}
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

    missing_key = json.loads(tool.secure_browser_click_tool({"selector": "label[for=color]", "workflow_id": "test"}))
    assert missing_key["status"] == "error" and "action_key" in missing_key["message"]
    assert calls == []
    missing_type_key = json.loads(tool.secure_browser_type_tool({"selector": "#message", "workflow_id": "test", "text": "hello"}))
    assert missing_type_key["status"] == "error" and "action_key" in missing_type_key["message"]
    assert calls == []
    click = json.loads(tool.secure_browser_click_tool({"selector": "label[for=color]", "workflow_id": "test", "action_key": "once"}))
    assert click["status"] == "delivered"
    assert calls[-1] == ("selector_action", {"workflow_id": "test", "operation": "click", "selector": "label[for=color]", "expected_url": "https://fixture.example/shop", "expected_generation": 100, "expected_tab": "Unrelated shop", "action_key": "once", "max_wait_seconds": None})
    typed = json.loads(tool.secure_browser_type_tool({"selector": "#message", "workflow_id": "test", "text": "hello", "action_key": "type-once"}))
    assert typed["typed_chars"] == 5
    assert calls[-1] == ("selector_action", {"workflow_id": "test", "operation": "type", "selector": "#message", "expected_url": "https://fixture.example/shop", "expected_generation": 100, "expected_tab": "Unrelated shop", "text": "hello", "action_key": "type-once"})

def test_selector_typing_reserves_before_input_and_replay_never_retypes():
    from test_firefox_ui_bridge import configured_bridge
    bridge, desktop, tmp = configured_bridge()
    try:
        bridge._xdotool = lambda *args, **_kw: "1365 768" if args == ("getdisplaygeometry",) else desktop.xdotool(*args)
        bridge.command_tabs({"action": "acquire", "workflow_id": "w"})
        payload = {"workflow_id": "w", "coordinate": [120, 300], "text": "ordinary text", "action_key": "type-1",
                   "expected_url": "https://example.test/", "expected_generation": 100, "expected_tab": "New Tab"}
        first = bridge.command_type(payload)
        assert first["status"] == "delivered" and first["typed_chars"] == len(payload["text"])
        assert sum(command[0] == "type" for command in desktop.commands) == 1
        second = bridge.command_type(payload)
        assert second["status"] == "already_delivered" and second["delivery"]["input_sent"] is False
        assert sum(command[0] == "type" for command in desktop.commands) == 1
        try:
            bridge.command_click({"workflow_id": "w", "action_key": "type-1", "coordinate": [120, 300]})
        except ValueError as exc:
            assert "another operation" in str(exc)
        else:
            raise AssertionError("typed action key was reusable for a click")
        before = len(desktop.commands)
        try:
            bridge.command_type({**payload, "action_key": "type-failed", "expected_url": "https://wrong.test/"})
        except RuntimeError as exc:
            assert "stale" in str(exc)
        else:
            raise AssertionError("stale type was delivered")
        assert len(desktop.commands) == before
        assert "type-failed" not in bridge._load_state()["action_keys"]
        for operation in (bridge.command_type, bridge.command_click):
            try:
                operation({**payload, "action_key": "x" * 201})
            except ValueError as exc:
                assert "200 characters" in str(exc)
            else:
                raise AssertionError("overlong action key was silently truncated")
        def fail_after_reservation(*args, **_kw):
            if args[0] == "type":
                raise RuntimeError("transport uncertain")
            return desktop.xdotool(*args)
        bridge._xdotool = lambda *args, **kw: "1365 768" if args == ("getdisplaygeometry",) else fail_after_reservation(*args, **kw)
        try:
            bridge.command_type({**payload, "action_key": "type-uncertain"})
        except RuntimeError as exc:
            assert "transport uncertain" in str(exc)
        else:
            raise AssertionError("transport failure was hidden")
        replay = bridge.command_type({**payload, "action_key": "type-uncertain"})
        assert replay["status"] == "delivery_uncertain" and replay["delivery"]["input_sent"] is False
        # Legacy focused-field typing has no selector precondition; keep its
        # existing behavior while v2 selector typing uses the journal.
        bridge._xdotool = lambda *args, **kw: "1365 768" if args == ("getdisplaygeometry",) else desktop.xdotool(*args, **kw)
        legacy = bridge.command_type({"workflow_id": "w", "text": "focused field"})
        assert legacy["status"] == "delivered" and legacy["typed_chars"] == 13
    finally:
        tmp.cleanup()


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


def test_native_selector_reorder_overlay_cross_site_and_uncertain_replay():
    from test_firefox_ui_bridge import configured_bridge
    bridge, desktop, tmp = configured_bridge()
    try:
        bridge.command_tabs({"action": "acquire", "workflow_id": "w"})
        native = {"url": "https://example.test/", "element": "original", "overlay": False,
                  "sent": [], "queries": [], "fail": False}
        ref = "element-6066-11e4-a52e-4f735466cecf"
        def command(method, path, data=None):
            native["queries"].append((method, path, data))
            if path == "/window/handles":
                return ["visible", "unrelated"]
            if path == "/url":
                return native["url"] if native.get("handle") == "visible" else "https://other.test/"
            if path == "/window":
                native["handle"] = data["handle"]
                return None
            if path == "/elements":
                assert data["using"] == "css selector"
                return [{ref: native["element"]}]
            if path == "/execute/sync":
                assert "arguments[0]" in data["script"] and "click()" not in data["script"]
                return True
            if path.startswith("/element/"):
                if native["fail"]:
                    raise RuntimeError("transport uncertain")
                # Model a same-URL reorder and a new overlay *after* lookup.
                # Native click references original, not the replacement point.
                if native["overlay"] or native["element"] != path.split("/")[2]:
                    raise RuntimeError("native element click intercepted or stale")
                native["sent"].append((path, data))
                return None
            raise AssertionError(path)
        @contextlib.contextmanager
        def webdriver():
            yield command
        bridge._webdriver = webdriver
        base = {"workflow_id": "w", "operation": "click", "selector": "#target",
                "expected_url": "https://example.test/", "expected_generation": 100, "expected_tab": "New Tab"}
        native["url"] = "https://other.test/"
        try:
            bridge.command_selector_action({**base, "action_key": "wrong-site"})
        except RuntimeError as exc:
            assert "absent or ambiguous" in str(exc)
        else:
            raise AssertionError("cross-site element accepted")
        assert "wrong-site" not in bridge._load_state()["action_keys"]
        native["url"] = "https://example.test/"
        original = bridge.command_selector_action({**base, "action_key": "first"})
        assert original["status"] == "delivered" and original["delivery"]["via"] == "native_element"
        assert native["sent"][-1][0] == "/element/original/click"
        native["fail"] = True
        for key in ("reordered", "occluded"):
            native["overlay"] = key == "occluded"
            if key == "reordered":
                # Change the lookup result only after native handle is obtained.
                old = bridge._native_selector
                def reorder(cmd, snap, selector, field_only):
                    element = old(cmd, snap, selector, field_only)
                    native["element"] = "replacement"
                    return element
                bridge._native_selector = reorder
            try:
                bridge.command_selector_action({**base, "action_key": key})
            except RuntimeError:
                pass
            else:
                raise AssertionError("unsafe native input reported delivered")
            bridge._native_selector = old if key == "reordered" else bridge._native_selector
            replay = bridge.command_selector_action({**base, "action_key": key})
            assert replay["status"] == "delivery_uncertain" and not replay["delivery"]["input_sent"]
            native["element"] = "original"
        assert len(native["sent"]) == 1
        assert bridge._load_state()["action_keys"]["occluded"]["delivery_state"] == "delivery_started"
    finally:
        tmp.cleanup()


if __name__ == "__main__":
    test_unambiguous_visible_page_query_and_secret_guard()
    test_general_collection_read_is_bounded_and_redacts_each_field()
    test_site_independent_dom_snapshot_is_generated_and_bounded()
    test_dom_snapshot_executes_without_exporting_credential_values()
    test_dom_snapshot_paginates_large_unrelated_page_without_skipping_nodes()
    test_duplicate_url_fails_without_script_execution()
    test_same_path_different_query_fails_closed()
    test_redacted_url_with_query_maps_only_unique_visible_context()
    test_selector_point_is_not_exposed_and_secrets_are_redacted()
    test_status_requires_live_bidi_not_just_launch_configuration()
    test_selector_click_keeps_ui_action_key_and_type_keeps_ui_value_redacted()
    test_selector_typing_reserves_before_input_and_replay_never_retypes()
    test_ui_bridge_rejects_displaced_tab_and_offscreen_coordinate()
    test_native_selector_reorder_overlay_cross_site_and_uncertain_replay()
    print("fourteen Firefox BiDi/UI source fixtures passed")
