"""Generic secure-browser safety regressions; no retailer or composer fixtures."""
import contextlib
import json
import subprocess

from test_firefox_ui_bridge import configured_bridge
from test_secure_browser_firefox_ui import load_tool
from test_secure_browser_bidi_ui import load


def test_ordinary_type_forwards_retry_key_and_coordinate():
    tool, _ = load_tool()
    calls = []
    tool._bridge = lambda command, payload: calls.append((command, payload)) or {"status": "delivered"}
    args = {"workflow_id": "w", "coordinate": [120, 300], "text": "public text", "action_key": "once"}
    assert json.loads(tool.secure_browser_type_tool(args))["status"] == "delivered"
    assert calls == [("type", {"workflow_id": "w", "locator": None, "coordinate": [120, 300],
                               "text": "public text", "action_key": "once"})]
    calls.clear()
    assert json.loads(tool.secure_browser_type_tool({"text": "public text"}))["status"] == "error"
    assert calls == []


def test_duplicate_titles_and_multiple_selected_tabs_are_not_identity():
    bridge, desktop, tmp = configured_bridge()
    try:
        bridge.command_tabs({"action": "acquire", "workflow_id": "w"})
        desktop.tabs[0]["name"] = "New Tab"
        state = bridge._load_state()
        assert bridge._matching_tabs(desktop.snapshot(), state["workflows"]["w"]) == []
        desktop.tabs[0]["selected"] = True
        assert bridge._selected_tab(desktop.snapshot()) is None
    finally:
        tmp.cleanup()


def test_ambiguous_selected_state_never_sends_input():
    bridge, desktop, tmp = configured_bridge()
    try:
        bridge.command_tabs({"action": "acquire", "workflow_id": "w"})
        desktop.tabs[0]["selected"] = True
        before = list(desktop.commands)
        try:
            bridge.command_type({"workflow_id": "w", "text": "public text", "action_key": "once"})
        except RuntimeError as exc:
            assert "selected" in str(exc)
        else:
            raise AssertionError("ambiguous selected state received input")
        assert desktop.commands == before
    finally:
        tmp.cleanup()


def test_bridge_rejects_unjournaled_typing_before_input():
    bridge, desktop, tmp = configured_bridge()
    try:
        bridge.command_tabs({"action": "acquire", "workflow_id": "w"})
        before = list(desktop.commands)
        try:
            bridge.command_type({"workflow_id": "w", "text": "public text"})
        except ValueError as exc:
            assert "action_key" in str(exc)
        else:
            raise AssertionError("unjournaled typing accepted")
        assert desktop.commands == before
    finally:
        tmp.cleanup()


def test_explicit_recovery_preserves_uncertain_tabs_and_action_journal():
    bridge, desktop, tmp = configured_bridge()
    try:
        bridge.command_tabs({"action": "acquire", "workflow_id": "w"})
        with bridge._locked_state() as state:
            state["workflows"]["w"]["uncertain"] = True
            state["action_keys"]["once"] = {"created_at": bridge.time.time(), "workflow_id": "w",
                                             "operation": "type", "delivery_state": "delivery_started"}
        preserved = list(desktop.tabs)
        result = bridge.command_tabs({"action": "recover", "workflow_id": "w"})
        assert result["status"] == "recovered_preserved_tab"
        assert desktop.tabs == preserved
        assert "w" not in bridge._load_state()["workflows"]
        assert "once" in bridge._load_state()["action_keys"]
        assert not any(c[:3] == ("key", "--clearmodifiers", "ctrl+w") for c in desktop.commands)
    finally:
        tmp.cleanup()


def test_native_selector_uses_post_selection_snapshot():
    bridge, desktop, tmp = configured_bridge()
    try:
        bridge.command_tabs({"action": "acquire", "workflow_id": "w"})
        desktop.tabs[0]["selected"], desktop.tabs[1]["selected"] = True, False
        def select(record):
            desktop.tabs[0]["selected"], desktop.tabs[1]["selected"] = False, True
        bridge._select_workflow_tab = select
        @contextlib.contextmanager
        def driver():
            yield lambda *args: None
        bridge._webdriver = driver
        def selector(command, snapshot, css, field):
            assert snapshot["tabs"][1]["selected"]
            return "public-element"
        bridge._native_selector = selector
        assert bridge.command_selector_action({"workflow_id": "w", "operation": "click",
                                               "selector": "#public", "action_key": "once"})["status"] == "delivered"
    finally:
        tmp.cleanup()


def test_link_observation_executes_with_credential_components_removed():
    module, _ = load()
    script = module._read_script('document.querySelectorAll("a").href')
    source = '''
const links=['https://example.test/avatar.png?signature=PRIVATE#PRIVATE',
 'https://user:PRIVATE@example.test/path', 'javascript:alert(1)',
 'https://example.test/reset/PRIVATE', '/relative?code=PRIVATE'];
const document={baseURI:'https://example.test/',querySelectorAll:()=>links.map(href=>({
 name:'',id:'',labels:[],getAttribute:()=>null,matches:s=>s==='a[href],area[href]',
 querySelector:()=>null,href}))};
'''
    result = subprocess.run(["node", "-e", source + "console.log(JSON.stringify(" + script + "));"],
                            capture_output=True, text=True, check=True)
    values = json.loads(result.stdout)["values"]
    assert values == ["https://example.test", "<redacted>", "<redacted>", "https://example.test", "https://example.test"]
    assert "PRIVATE" not in result.stdout


def test_native_mapping_restores_initial_handle_on_ambiguity():
    bridge, desktop, tmp = configured_bridge()
    try:
        current = "owner"
        sent = []
        def command(method, path, data=None):
            nonlocal current
            if path == "/window/handles":
                return ["owner", "duplicate"]
            if path == "/window" and method == "GET":
                return current
            if path == "/window":
                assert data is not None
                current = data["handle"]
                sent.append(current)
                return None
            if path == "/url":
                return "https://example.test/"
            raise AssertionError("element lookup must not happen")
        try:
            bridge._native_selector(command, desktop.snapshot(), "#public", False)
        except RuntimeError as exc:
            assert "ambiguous" in str(exc)
        else:
            raise AssertionError("ambiguous native mapping accepted")
        assert current == "owner"
        assert sent[-1] == "owner"
    finally:
        tmp.cleanup()


def test_native_typing_supports_inherited_contenteditable():
    bridge, desktop, tmp = configured_bridge()
    try:
        scripts = []
        def command(method, path, data=None):
            if path == "/window/handles":
                return ["visible"]
            if path == "/window":
                return "visible" if method == "GET" else None
            if path == "/url":
                return "https://example.test/"
            if path == "/elements":
                return [{"element-6066-11e4-a52e-4f735466cecf": "editable"}]
            if path == "/execute/sync":
                assert data is not None
                scripts.append(data["script"])
                return True
            raise AssertionError(path)
        bridge._native_selector(command, desktop.snapshot(), "#public", True)
        source = '''
const e={name:'',id:'',labels:[],isContentEditable:true,disabled:false,readOnly:false,
 getAttribute:()=>null,matches:()=>false};
'''
        result = subprocess.run(["node", "-e", source + "console.log((function(){" + scripts[0] + "})(e,true));"],
                                capture_output=True, text=True, check=True)
        assert result.stdout.strip() == "true"
    finally:
        tmp.cleanup()


def test_accessibility_object_identity_survives_rename_and_reorder_not_replacement():
    bridge, desktop, tmp = configured_bridge()
    try:
        record = {"browser_generation": 100, "tab_identity": "opaque-original",
                  "tab_name": "Fixture", "locator": "old"}
        snapshot = {"browser_generation": 100, "tabs": [
            {"name": "Fixture", "locator": "old", "tab_identity": "opaque-replacement"},
            {"name": "Renamed", "locator": "new", "tab_identity": "opaque-original"}]}
        assert bridge._matching_tabs(snapshot, record) == [snapshot["tabs"][1]]
        snapshot["tabs"].pop()
        assert bridge._matching_tabs(snapshot, record) == []
        snapshot["tabs"][0]["tab_identity"] = "opaque-original"
        snapshot["browser_generation"] = 101
        assert bridge._matching_tabs(snapshot, record) == []
    finally:
        tmp.cleanup()


if __name__ == "__main__":
    tests = [(name, fn) for name, fn in list(globals().items()) if name.startswith("test_")]
    for name, fn in tests:
        fn()
        print("PASS", name)
    print(f"{len(tests)} generic secure-browser regressions passed")
