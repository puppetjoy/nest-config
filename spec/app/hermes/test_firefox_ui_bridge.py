#!/usr/bin/env python3
"""Behavior tests for non-instrumented Firefox UI workflow continuity."""

from __future__ import annotations

import importlib.util
import json
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

    def readback(self, _max_wait_seconds: float = 6) -> dict[str, Any]:
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
        assert first["delivery"] == {"state": "delivered", "input_sent": True}
        assert second["delivery"] == {"state": "replayed", "input_sent": False}
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
        module._readback = lambda _max_wait_seconds=6: (_ for _ in ()).throw(RuntimeError("readback unavailable"))
        try:
            module.command_click({"workflow_id": "w", "locator": locator, "action_key": "fixture-once"})
            raise AssertionError("failed readback should be reported")
        except RuntimeError as exc:
            assert "readback unavailable" in str(exc)
        assert module._load_state()["action_keys"]["fixture-once"]["workflow_id"] == "w"
    finally:
        tmp.cleanup()


def test_click_action_key_is_fail_closed_when_input_delivery_is_uncertain() -> None:
    module, fixture, tmp = configured_bridge()
    try:
        fixture.tabs = [{"name": "New Tab", "selected": True}]
        module.command_navigate({"workflow_id": "w", "url": "https://example.test/"})
        locator = fixture.snapshot()["tabs"][0]["locator"]
        attempted = 0

        def fail_input(*_args: str, **_kwargs: Any) -> str:
            nonlocal attempted
            attempted += 1
            raise RuntimeError("input delivery interrupted")

        module._xdotool = fail_input
        try:
            module.command_click({"workflow_id": "w", "locator": locator, "action_key": "fixture-uncertain"})
            raise AssertionError("uncertain delivery should be reported")
        except RuntimeError as exc:
            assert "interrupted" in str(exc)
        assert module._load_state()["action_keys"]["fixture-uncertain"]["delivery_state"] == "delivery_started"

        replay = module.command_click({"workflow_id": "w", "locator": locator, "action_key": "fixture-uncertain"})
        assert replay["status"] == "delivery_uncertain"
        assert replay["delivery"] == {"state": "uncertain_replay_blocked", "input_sent": False}
        assert attempted == 1
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


def test_atspi_text_api_and_safe_commerce_canonicalization() -> None:
    module = load_bridge()

    class TextAPI:
        @staticmethod
        def get_character_count(_node: Any) -> int:
            return len("Subtotal $50.00")

        @staticmethod
        def get_text(_node: Any, start: int, end: int) -> str:
            assert start == 0
            assert end == len("Subtotal $50.00")
            return "Subtotal $50.00"

    original_import = module.importlib.import_module
    module.importlib.import_module = lambda name: type("AtspiModule", (), {"Text": TextAPI}) if name == "gi.repository.Atspi" else original_import(name)
    try:
        assert module._text_content(object()) == "Subtotal $50.00"
    finally:
        module.importlib.import_module = original_import

    assert module._safe_visible_commerce_text("Subtotal $50.00") == "Subtotal $50.00"
    assert module._safe_visible_commerce_text("Shipping Free") == "Shipping free"
    assert module._safe_visible_commerce_text("Quantity 1") == "Quantity 1"
    assert module._safe_visible_commerce_text("Thank you. Your order is confirmed #raw-order-id") == "Order confirmed"
    assert module._safe_visible_commerce_text("Payment failed for Joyful Lee") == "Payment failed"
    assert module._safe_visible_commerce_text("123 Private Lane") == ""
    assert module._safe_observed_name("paragraph", "Roll-Line Small Step Lower Gray/Soft", "") == "Roll-Line Small Step Lower Gray/Soft"
    assert module._safe_observed_name("static text", "joy@example.test", "") == "<sensitive control; value redacted>"
    assert module._safe_observed_name("heading", "Order confirmed #raw-order-id", "") == "Order confirmed #raw-order-id"
    assert module._safe_observed_name("paragraph", "Read our return policy", "") == "Read our return policy"
    assert module._safe_observed_name("spin button", "Quantity", "2") == "2"
    static_terminal = {
        "title": "Checkout", "url": "https://shop.example/checkout",
        "nodes": [{"role": "paragraph", "name": "Order confirmed", "states": ["visible"]}],
    }
    assert module._transition_state(static_terminal) == "terminal_success"


def test_visible_unlabelled_interactive_control_is_preserved_with_stable_identity() -> None:
    module = load_bridge()

    class Node:
        def get_role_name(self) -> str:
            return "radio button"

        def get_name(self) -> str:
            return ""

        def get_description(self) -> str:
            return ""

    module._state_names = lambda _node: ["selected", "showing", "enabled"]
    module._extent = lambda _node: {"x": 240, "y": 510, "width": 24, "height": 24}
    first = module._node_record(Node(), (3, 7, 2), 100)
    second = module._node_record(Node(), (3, 7, 2), 100)

    assert first == second
    assert first["name"] == "<unlabelled>"
    assert first["accessible_name_present"] is False
    assert first["unlabelled"] is True
    assert first["role"] == "radio button"
    assert first["states"] == ["selected", "showing", "enabled"]
    assert first["rect"] == {"x": 240, "y": 510, "width": 24, "height": 24}
    assert first["control_id"].startswith("ui:100:3.7.2:")
    assert first["locator"].startswith("ax:100:3.7.2:")


def test_generic_accessible_page_text_and_values_across_unrelated_sites() -> None:
    module = load_bridge()
    for hostname, text, value in (
        ("fivestride.example", "Gray/Soft Large Upper — Set of 4 $29.00", "2"),
        ("library.example", "The public library opens Tuesday at nine", "Tuesday"),
        ("weather.example", "Partly cloudy with scattered showers", "18"),
    ):
        assert hostname
        assert module._safe_observed_name("paragraph", text, "") == text
        assert module._safe_observed_name("entry", "Search", value) == value
    assert module._safe_observed_name("password text", "Password", "hunter2").startswith("<sensitive")
    assert module._safe_observed_name("text", "Card number", "4111111111111111").startswith("<sensitive")


def test_snapshot_keeps_long_rendered_text_in_unusual_accessibility_roles() -> None:
    module = load_bridge()

    class Node:
        def __init__(self, role: str, name: str, text: str = "", children: int = 0) -> None:
            self.role, self.name, self.text, self.children = role, name, text, children

        def get_role_name(self) -> str:
            return self.role

        def get_name(self) -> str:
            return self.name

        def get_description(self) -> str:
            return ""

        def get_child_count(self) -> int:
            return self.children

    for site_text in (
        "Gray/Soft Upper Set of 4 $30.00",
        "Library event starts at noon",
        "Weather advisory: heavy rain tomorrow",
    ):
        long_text = "Read the full page. " * 20 + site_text
        nodes = [Node("section", "", long_text, children=1),
                 Node("section", "", long_text), Node("paragraph", "", long_text),
                 Node("entry", "Card number", "4111111111111111")]
        module._firefox_root = lambda: object()
        module._walk = lambda _root: ((node, (index,)) for index, node in enumerate(nodes))
        module._browser_pid = lambda: 100
        module._state_names = lambda _node: ["showing", "visible"]
        module._extent = lambda _node: None
        module._text_content = lambda node: node.text
        module._firefox_window_id = lambda: "1"
        module._run = lambda _argv: type("Result", (), {"stdout": b"Fixture - Firefox"})()
        snapshot = module._snapshot()
        assert [item["name"] for item in snapshot["nodes"][:2]] == [long_text, long_text]
        assert site_text in snapshot["nodes"][0]["name"]
        assert snapshot["nodes"][2]["name"].startswith("<sensitive")
        assert len(snapshot["nodes"]) == 3
        assert "4111" not in str(snapshot)
    assert module._safe_observed_name("button", "Buy now", "Unrelated subtree") == "Buy now"


def test_overlapping_radio_locator_fails_closed_without_action() -> None:
    module, fixture, tmp = configured_bridge()
    try:
        fixture.tabs = [{"name": "New Tab", "selected": True}]
        module.command_navigate({"workflow_id": "w", "url": "https://example.test/"})
        rect = {"x": 0, "y": 0, "width": 10, "height": 10}
        class Radio:
            def get_role_name(self) -> str:
                return "radio button"
            def get_action_iface(self) -> None:
                return None
        module._resolve_locator = lambda locator: (Radio(), rect)
        original_snapshot = fixture.snapshot
        module._snapshot = lambda: {**original_snapshot(), "nodes": [
            {"role": "radio button", "rect": rect, "name": name} for name in ("Green", "Gray")
        ]}
        fixture.commands.clear()
        try:
            module.command_click({"workflow_id": "w", "locator": original_snapshot()["tabs"][0]["locator"]})
            raise AssertionError("overlapping radio bounds must not deliver input")
        except ValueError as exc:
            assert "overlapping" in str(exc)
        assert not any("click" in command for command in fixture.commands)
    finally:
        tmp.cleanup()


def test_wait_for_stable_distinguishes_in_flight_success_and_failure() -> None:
    module = load_bridge()
    base = {
        "browser_generation": 100,
        "title": "Checkout",
        "url": "https://shop.example/checkout",
        "tab_count": 1,
        "tabs": [{"name": "Checkout", "selected": True, "locator": "ax:100:1:deadbeef0001"}],
        "truncated": False,
    }

    def run_sequence(node_names: list[list[str]], role: str = "paragraph") -> dict[str, Any]:
        snapshots = [
            {
                **base,
                "nodes": [
                    {
                        "role": role, "name": name, "states": ["showing"],
                        "locator": f"ax:100:{index}:deadbeef0001",
                        "control_id": f"ui:100:{index}:deadbeef0001",
                    }
                    for index, name in enumerate(names)
                ],
            }
            for names in node_names
        ]
        module._snapshot = lambda: snapshots.pop(0) if len(snapshots) > 1 else snapshots[0]
        module.time.sleep = lambda _seconds: None
        return module._wait_for_stable(max_wait_seconds=0.01, stable_polls=2)

    in_flight = run_sequence([["Processing payment"], ["Processing payment"], ["Processing payment"]])
    assert in_flight["state"] == "in_flight"
    assert in_flight["settled"] is False

    sparse_document = run_sequence([["Document"], ["Document"], ["Document"]])
    assert sparse_document["state"] == "in_flight"
    assert sparse_document["settled"] is False

    generic_copy = run_sequence([["Payment successful stories"], ["Payment successful stories"]], role="text")
    assert generic_copy["state"] == "stable"
    unrelated_heading = {
        **base,
        "title": "Customer stories",
        "url": "https://shop.example/stories",
        "nodes": [{"role": "heading", "name": "Payment was successful", "states": ["showing"]}],
    }
    assert module._transition_state(unrelated_heading) == "stable"
    background_loading_tab = {
        **base,
        "nodes": [
            {"role": "page tab", "name": "Problem loading page", "states": ["showing"]},
            {"role": "page tab", "name": "Checkout", "states": ["selected", "showing"]},
            {"role": "paragraph", "name": "Total $57.24", "states": ["showing"]},
        ],
    }
    assert module._transition_state(background_loading_tab) == "stable"

    success = run_sequence([["Processing payment"], ["Thank you. Your order is confirmed"], ["Thank you. Your order is confirmed"]], role="heading")
    assert success["state"] == "terminal_success"
    assert success["settled"] is True

    failure = run_sequence([["Processing payment"], ["Payment failed. Please try again"], ["Payment failed. Please try again"]], role="alert")
    assert failure["state"] == "terminal_error"
    assert failure["settled"] is True


def test_commerce_readback_is_structured_and_never_returns_owner_sensitive_text() -> None:
    module = load_bridge()
    snapshot = {
        "url": "https://checkout.example.test/orders/raw-secret-order-123?email=joy@example.test",
        "title": "Order confirmation raw-secret-order-123",
        "nodes": [
            {"role": "heading", "name": "Thank you! Order confirmed #raw-secret-order-123", "states": ["showing"]},
            {"role": "text", "name": "Joyful Lee", "states": ["showing"]},
            {"role": "text", "name": "123 Private Lane", "states": ["showing"]},
            {"role": "radio button", "name": "Color: Navy", "states": ["showing", "selected"]},
            {"role": "radio button", "name": "Size: Medium", "states": ["showing", "checked"]},
            {"role": "radio button", "name": "Variant: joy@example.test", "states": ["showing", "selected"]},
            {"role": "radio button", "name": "Variant: Joyful Lee", "states": ["showing", "selected"]},
            {"role": "spin button", "name": "Quantity 1", "states": ["showing"]},
            {"role": "text", "name": "Subtotal $50.00", "states": ["showing"]},
            {"role": "text", "name": "Shipping $5.00", "states": ["showing"]},
            {"role": "text", "name": "Tax $2.24", "states": ["showing"]},
            {"role": "text", "name": "Total $57.24", "states": ["showing"]},
            {"role": "text", "name": "Visa ending in 4242", "states": ["showing"]},
        ],
        "truncated": False,
    }
    result = module._commerce_readback(snapshot, {"safe_item_nickname": "ONNO hemp tee"})
    encoded = json.dumps(result, sort_keys=True)

    assert result["retailer"] == "checkout.example.test"
    assert result["safe_item_nickname"] == "ONNO hemp tee"
    assert result["variant"] == ["Navy", "Medium"]
    assert result["quantity"] == 1
    assert result["subtotal"] == "$50.00"
    assert result["shipping"] == "$5.00"
    assert result["tax"] == "$2.24"
    assert result["total"] == "$57.24"
    assert result["confirmation_status"] == "confirmed"
    assert result["source"] == "visible AT-SPI accessibility readback"
    for secret in ("Joyful Lee", "123 Private Lane", "joy@example.test", "4242", "raw-secret-order-123"):
        assert secret not in encoded


def test_commerce_readback_pairs_split_labels_only_with_standalone_amounts() -> None:
    module = load_bridge()
    snapshot = {
        "url": "https://checkout.example.test/review",
        "title": "Review order",
        "nodes": [
            {"role": "text", "name": "Subtotal", "states": ["showing"]},
            {"role": "text", "name": "$50.00", "states": ["showing"]},
            {"role": "text", "name": "Shipping", "states": ["showing"]},
            {"role": "text", "name": "Free", "states": ["showing"]},
            {"role": "text", "name": "Tax", "states": ["showing"]},
            {"role": "text", "name": "Total $57.24", "states": ["showing"]},
            {"role": "text", "name": "Estimated total $55.00", "states": ["showing"]},
        ],
        "truncated": False,
    }
    result = module._commerce_readback(snapshot, {"safe_item_nickname": "fixture item"})

    assert result["subtotal"] == "$50.00"
    assert result["shipping"] == "free"
    assert result["tax"] is None
    assert result["total"] == "$57.24"


def test_commerce_readback_ignores_promotional_amount_and_sums_labelled_controls() -> None:
    module = load_bridge()
    snapshot = {
        "url": "https://unrelated-shop.example/cart", "title": "Cart",
        "nodes": [
            {"role": "static", "name": "FREE STANDARD SHIPPING ON ORDERS OVER $100"},
            {"role": "spin button", "name": "Quantity", "value": "1"},
            {"role": "spin button", "name": "Quantity", "value": "2"},
            {"role": "heading", "name": "Subtotal: $60.00 USD"},
        ], "truncated": False,
    }
    result = module._commerce_readback(snapshot, {"safe_item_nickname": "fixture"})
    assert result["quantity"] == 3
    assert result["subtotal"] == "$60.00"
    assert result["shipping"] is None
    assert result["total"] is None


def test_commerce_readback_keeps_real_shipping_amount_when_banner_precedes_it() -> None:
    module = load_bridge()
    snapshot = {
        "url": "https://another-shop.example/checkout",
        "nodes": [
            {"role": "static", "name": "Free shipping on orders over $100"},
            {"role": "text", "name": "Shipping cost"},
            {"role": "text", "name": "$5.00"},
        ],
    }
    assert module._commerce_readback(snapshot, {"safe_item_nickname": "fixture"})["shipping"] == "$5.00"


if __name__ == "__main__":
    for test_name in sorted(name for name in globals() if name.startswith("test_")):
        globals()[test_name]()
