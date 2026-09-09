#!/usr/bin/env python3
"""Behavior tests for non-instrumented Firefox UI workflow continuity."""

from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[3]
BRIDGE = REPO_ROOT / "files/firefox-browser/firefox-ui-bridge.py"


def load_bridge() -> Any:
    spec = importlib.util.spec_from_file_location("firefox_ui_bridge_under_test", BRIDGE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DesktopFixture:
    def __init__(self, module: Any) -> None:
        self.module = module
        self.generation = 100
        self.tabs = [{"name": "Joy tab", "selected": True}]
        self.pending_url = ""
        self.commands: list[tuple[str, ...]] = []

    def snapshot(self) -> dict[str, Any]:
        tabs = []
        for index, tab in enumerate(self.tabs):
            tabs.append({
                **tab,
                "locator": f"ax:{self.generation}:{index}:deadbeef{index:04d}",
            })
        selected = next((tab["name"] for tab in tabs if tab["selected"]), "")
        return {
            "protocol": "firefox-ui-v1",
            "browser_generation": self.generation,
            "title": selected,
            "url": "https://example.test/",
            "tab_count": len(tabs),
            "tabs": tabs,
            "nodes": [],
            "truncated": False,
            "window_id": "1",
        }

    def xdotool(self, *args: str, **_kwargs: Any) -> str:
        self.commands.append(tuple(args))
        if args[:3] == ("key", "--clearmodifiers", "ctrl+t"):
            for tab in self.tabs:
                tab["selected"] = False
            self.tabs.append({"name": "New Tab", "selected": True})
        elif args[:3] == ("key", "--clearmodifiers", "ctrl+w"):
            selected = next(index for index, tab in enumerate(self.tabs) if tab["selected"])
            self.tabs.pop(selected)
            if self.tabs:
                self.tabs[max(0, selected - 1)]["selected"] = True
        elif args and args[0] == "type":
            self.pending_url = args[-1]
        elif args[:3] == ("key", "--clearmodifiers", "Return") and self.pending_url:
            selected = next(tab for tab in self.tabs if tab["selected"])
            selected["name"] = urlsplit(self.pending_url).hostname or self.pending_url
        return ""

    def resolve(self, locator: str) -> tuple[None, dict[str, int]]:
        index = int(locator.split(":")[2])
        return None, {"x": index * 20, "y": 0, "width": 10, "height": 10}

    def readback(self) -> dict[str, Any]:
        snapshot = self.snapshot()
        selected = next((tab["name"] for tab in snapshot["tabs"] if tab["selected"]), "")
        selected_locator = next((tab["locator"] for tab in snapshot["tabs"] if tab["selected"]), "")
        return {
            "browser_generation": self.generation,
            "title": selected,
            "url": snapshot["url"],
            "tab_count": len(self.tabs),
            "selected_tab": selected,
            "selected_locator": selected_locator,
        }


def configured_bridge() -> tuple[Any, DesktopFixture, tempfile.TemporaryDirectory[str]]:
    module = load_bridge()
    fixture = DesktopFixture(module)
    tmp = tempfile.TemporaryDirectory()
    module.STATE_DIR = Path(tmp.name)
    module.STATE_PATH = module.STATE_DIR / "state.json"
    module.LOCK_PATH = module.STATE_DIR / "state.lock"
    module._snapshot = fixture.snapshot
    module._xdotool = fixture.xdotool
    module._resolve_locator = fixture.resolve
    module._focus_browser = lambda: "1"
    module._readback = fixture.readback
    return module, fixture, tmp


def test_same_tab_continuity_and_readback_without_duplicate_tabs() -> None:
    module, fixture, tmp = configured_bridge()
    try:
        fixture.tabs = [{"name": "New Tab", "selected": True}]
        first = module.command_navigate({"workflow_id": "w", "url": "https://example.test/one"})
        second = module.command_navigate({"workflow_id": "w", "url": "https://example.test/two"})
        assert first["status"] == second["status"] == "delivered"
        assert first["created_tab"] is False
        assert len(fixture.tabs) == 1
        assert second["readback"]["selected_tab"] == "example.test"
        assert sum(command[:3] == ("key", "--clearmodifiers", "ctrl+t") for command in fixture.commands) == 0
    finally:
        tmp.cleanup()


def test_page_tab_locator_survives_title_change() -> None:
    module = load_bridge()
    before = module._identity("page tab", "New Tab", (0, 22, 1, 4), 60)
    after = module._identity("page tab", "MSC Industrial Supply", (0, 22, 1, 4), 60)
    control = module._identity("link", "Learn more", (0, 25, 4), 60)
    changed_control = module._identity("link", "Buy now", (0, 25, 4), 60)
    assert before == after
    assert control != changed_control


def test_exactly_once_click_has_readback_and_does_not_repeat_input() -> None:
    module, fixture, tmp = configured_bridge()
    try:
        fixture.tabs = [{"name": "New Tab", "selected": True}]
        module.command_navigate({"workflow_id": "w", "url": "https://example.test/"})
        fixture.commands.clear()
        locator = fixture.snapshot()["tabs"][0]["locator"]
        first = module.command_click({"workflow_id": "w", "locator": locator, "action_key": "fixture-purchase"})
        delivered_commands = list(fixture.commands)
        second = module.command_click({"workflow_id": "w", "locator": locator, "action_key": "fixture-purchase"})
        assert first["status"] == "delivered"
        assert second["status"] == "already_delivered"
        assert first["readback"]["tab_count"] == second["readback"]["tab_count"] == 1
        assert fixture.commands == delivered_commands
    finally:
        tmp.cleanup()


def test_click_action_key_survives_readback_failure() -> None:
    module, fixture, tmp = configured_bridge()
    try:
        fixture.tabs = [{"name": "New Tab", "selected": True}]
        module.command_navigate({"workflow_id": "w", "url": "https://example.test/"})
        locator = fixture.snapshot()["tabs"][0]["locator"]
        module._readback = lambda: (_ for _ in ()).throw(RuntimeError("readback unavailable"))
        try:
            module.command_click({"workflow_id": "w", "locator": locator, "action_key": "fixture-once"})
            raise AssertionError("failed readback should be reported")
        except RuntimeError as exc:
            assert "readback unavailable" in str(exc)
        assert module._load_state()["action_keys"]["fixture-once"]["workflow_id"] == "w"
    finally:
        tmp.cleanup()


def test_action_key_cannot_suppress_a_different_workflow() -> None:
    module, fixture, tmp = configured_bridge()
    try:
        fixture.tabs = [{"name": "New Tab", "selected": True}]
        module.command_navigate({"workflow_id": "first", "url": "https://example.test/"})
        locator = fixture.snapshot()["tabs"][0]["locator"]
        module.command_click({"workflow_id": "first", "locator": locator, "action_key": "fixture-once"})
        fixture.tabs.append({"name": "New Tab", "selected": True})
        fixture.tabs[0]["selected"] = False
        module.command_tabs({"action": "acquire", "workflow_id": "second"})
        second_locator = fixture.snapshot()["tabs"][1]["locator"]
        try:
            module.command_click({"workflow_id": "second", "locator": second_locator, "action_key": "fixture-once"})
            raise AssertionError("cross-workflow action key reuse should fail")
        except ValueError as exc:
            assert "another workflow" in str(exc)
    finally:
        tmp.cleanup()


def test_restart_reconciliation_and_ambiguous_tabs_are_fail_closed() -> None:
    module, fixture, tmp = configured_bridge()
    try:
        fixture.tabs = [{"name": "New Tab", "selected": True}]
        module.command_navigate({"workflow_id": "w", "url": "https://example.test/"})
        fixture.generation = 200
        status = module.command_status({})
        state = module._load_state()
        assert status["status"] == "ok"
        assert state["workflows"]["w"]["browser_generation"] == 200
        fixture.tabs.append({"name": "example.test", "selected": False})
        fixture.generation = 300
        module.command_status({})
        state = module._load_state()
        assert state["workflows"]["w"]["uncertain"] is True
        try:
            module.command_tabs({"action": "acquire", "workflow_id": "w"})
            raise AssertionError("uncertain ownership should not be overwritten")
        except RuntimeError as exc:
            assert "uncertain" in str(exc)
        try:
            module.command_click({"workflow_id": "w", "coordinate": [10, 10]})
            raise AssertionError("ambiguous tab input should fail closed")
        except RuntimeError as exc:
            assert "unambiguous" in str(exc)
    finally:
        tmp.cleanup()


def test_owned_tab_expiry_closes_once_but_owner_tab_is_preserved() -> None:
    module, fixture, tmp = configured_bridge()
    try:
        module.DEFAULT_HARD_TAB_CAP = 3
        acquired = module.command_tabs({"action": "acquire", "workflow_id": "w", "lease_seconds": 60})
        assert acquired["created_tab"] is True
        with module._locked_state() as state:
            state["workflows"]["w"]["lease_expires_at"] = 0
        status = module.command_status({})
        assert status["reconciliation"]["closed_expired"] == ["w"]
        assert [tab["name"] for tab in fixture.tabs] == ["Joy tab"]
        again = module.command_status({})
        assert again["reconciliation"]["closed_expired"] == []
    finally:
        tmp.cleanup()


def test_release_preserves_claimed_owner_blank_and_hard_cap_blocks_creation() -> None:
    module, fixture, tmp = configured_bridge()
    try:
        fixture.tabs = [{"name": "New Tab", "selected": True}]
        module.command_tabs({"action": "acquire", "workflow_id": "claimed"})
        released = module.command_tabs({"action": "release", "workflow_id": "claimed"})
        assert released["status"] == "released_preserved_tab"
        assert len(fixture.tabs) == 1

        fixture.tabs = [
            {"name": "Joy one", "selected": True},
            {"name": "Joy two", "selected": False},
        ]
        module.DEFAULT_HARD_TAB_CAP = 2
        try:
            module.command_tabs({"action": "acquire", "workflow_id": "capped"})
            raise AssertionError("hard cap should block tab creation")
        except RuntimeError as exc:
            assert "hard cap" in str(exc)
        assert len(fixture.tabs) == 2
    finally:
        tmp.cleanup()


if __name__ == "__main__":
    test_same_tab_continuity_and_readback_without_duplicate_tabs()
    test_page_tab_locator_survives_title_change()
    test_exactly_once_click_has_readback_and_does_not_repeat_input()
    test_click_action_key_survives_readback_failure()
    test_action_key_cannot_suppress_a_different_workflow()
    test_restart_reconciliation_and_ambiguous_tabs_are_fail_closed()
    test_owned_tab_expiry_closes_once_but_owner_tab_is_preserved()
    test_release_preserves_claimed_owner_blank_and_hard_cap_blocks_creation()
