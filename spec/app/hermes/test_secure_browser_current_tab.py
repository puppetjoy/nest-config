#!/usr/bin/env python3
"""Regression checks for secure_browser current-tab resolution."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import types
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
SECURE_BROWSER_TOOL = REPO_ROOT / "files/app/hermes/secure_browser_tool.py"


class DummyRegistry:
    def register(self, **_kwargs: Any) -> None:
        return None


def load_tool_module(state_path: Path):
    websockets_module = types.ModuleType("websockets")
    websockets_sync_module = types.ModuleType("websockets.sync")
    websockets_client_module = types.ModuleType("websockets.sync.client")
    setattr(websockets_client_module, "connect", lambda *_args, **_kwargs: None)
    setattr(websockets_sync_module, "client", websockets_client_module)
    setattr(websockets_module, "sync", websockets_sync_module)
    sys.modules.setdefault("websockets", websockets_module)
    sys.modules.setdefault("websockets.sync", websockets_sync_module)
    sys.modules.setdefault("websockets.sync.client", websockets_client_module)

    tools_module = types.ModuleType("tools")
    registry_module = types.ModuleType("tools.registry")
    setattr(registry_module, "registry", DummyRegistry())
    sys.modules.setdefault("tools", tools_module)
    sys.modules["tools.registry"] = registry_module

    spec = importlib.util.spec_from_file_location("secure_browser_tool_under_test", SECURE_BROWSER_TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    setattr(module, "OWNERSHIP_STATE_PATH", str(state_path))
    setattr(module, "BROWSER_OWNER", "shopping-test")
    return module


class FakeBiDiBrowser:
    protocol = "bidi"
    cdp_url = None

    def __init__(self, contexts: list[dict[str, Any]]) -> None:
        self.contexts = contexts
        self.created_targets: list[str] = []

    def _bidi_contexts(self) -> list[dict[str, str]]:
        return self.contexts

    def call(self, method: str, params: dict[str, Any] | None = None, session_id: str | None = None) -> dict[str, Any]:
        del params, session_id
        if method == "Target.getTargets":
            return {
                "targetInfos": [
                    {
                        "targetId": context["context"],
                        "type": "page",
                        "url": context.get("url", ""),
                        "title": context.get("title", ""),
                    }
                    for context in self.contexts
                ]
            }
        if method == "Target.createTarget":
            target_id = f"created-{len(self.created_targets) + 1}"
            self.created_targets.append(target_id)
            self.contexts.append({"context": target_id, "url": "about:blank", "title": ""})
            return {"targetId": target_id}
        raise AssertionError(f"unexpected browser call: {method}")


class FakeReadbackBrowser(FakeBiDiBrowser):
    def call(self, method: str, params: dict[str, Any] | None = None, session_id: str | None = None) -> dict[str, Any]:
        if method == "Target.attachToTarget":
            return {"sessionId": str((params or {}).get("targetId") or "")}
        if method in {"Runtime.enable", "Page.enable"}:
            return {}
        if method == "Runtime.evaluate":
            context = next(item for item in self.contexts if item["context"] == session_id)
            expression = str((params or {}).get("expression") or "")
            if expression == "location.href":
                value = context.get("url", "")
            elif expression == "document.title":
                value = context.get("title", "")
            else:
                value = {}
            return {"result": {"value": value}}
        return super().call(method, params, session_id)


def write_owner_state(path: Path, module: Any, target_id: str, url: str) -> None:
    path.write_text(
        json.dumps(
            {
                "owners": {
                    module.BROWSER_OWNER: {
                        "target_id": target_id,
                        "url": module._sanitize_url(url),
                        "toolset": module.TOOLSET,
                        "workload": module.WORKLOAD,
                    }
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_stale_bidi_context_id_resolves_by_stored_full_access_url() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        state_path = Path(tmpdir) / "secure-browser-tabs.json"
        module = load_tool_module(state_path)
        order_url = "https://www.amazon.com/gp/your-account/order-history?ref_=nav_orders_first"
        write_owner_state(state_path, module, "old-session-context", order_url)
        browser = FakeBiDiBrowser(
            [
                {"context": "blank-session-context", "url": "about:blank", "title": ""},
                {"context": "fresh-session-context", "url": order_url, "title": "Your Orders"},
            ]
        )

        target_id = module._claim_owner_target(browser, create=False)

        assert target_id == "fresh-session-context"
        assert browser.created_targets == []
        stored = json.loads(state_path.read_text(encoding="utf-8"))["owners"][module.BROWSER_OWNER]
        assert stored["target_id"] == "fresh-session-context"
        assert stored["url"] == module._sanitize_url(order_url)


def test_read_without_owner_surfaces_absent_state_without_opening_blank_tab() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        state_path = Path(tmpdir) / "secure-browser-tabs.json"
        module = load_tool_module(state_path)
        browser = FakeBiDiBrowser(
            [
                {"context": "blank-session-context", "url": "about:blank", "title": ""},
                {"context": "visible-session-context", "url": "https://example.com/", "title": "Example Domain"},
            ]
        )

        try:
            module._claim_owner_target(browser, create=False)
        except RuntimeError as exc:
            assert "OWNER_TAB_ABSENT" in str(exc)
        else:
            raise AssertionError("read-only owner resolution should fail explicitly")

        assert browser.created_targets == []


def test_stale_checkout_owner_recovers_same_retailer_confirmation_after_owner_handoff() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        state_path = Path(tmpdir) / "secure-browser-tabs.json"
        module = load_tool_module(state_path)
        checkout_url = "https://medusaskates.com/checkout.php"
        confirmation_url = "https://medusaskates.com/order-confirmation.php"
        write_owner_state(state_path, module, "checkout-before-owner-handoff", checkout_url)
        browser = FakeReadbackBrowser(
            [
                {"context": "browser-new-tab", "url": "about:blank", "title": ""},
                {"context": "confirmation-after-owner-submit", "url": confirmation_url, "title": "Thank you - Order Confirmed"},
            ]
        )

        target_id = module._claim_owner_target(browser, create=False)

        assert target_id == "confirmation-after-owner-submit"
        assert browser.created_targets == []
        stored = json.loads(state_path.read_text(encoding="utf-8"))["owners"][module.BROWSER_OWNER]
        assert stored["target_id"] == "confirmation-after-owner-submit"
        assert stored["url"] == confirmation_url

        original_with_browser = module._with_browser
        try:
            module._with_browser = lambda fn: fn(browser)
            summary = module._current_page_summary()
            snapshot = module._page_snapshot()
        finally:
            module._with_browser = original_with_browser

        assert summary["status"] == "purchase_confirmation_visible"
        assert summary["purchase_state"] == "completed_confirmation"
        assert summary["url"] == confirmation_url
        assert "order" not in summary or "order_reference" not in summary
        assert snapshot["status"] == "purchase_confirmation_visible"
        assert snapshot["purchase_state"] == "completed_confirmation"
        assert "interactive" not in snapshot

        original_with_browser = module._with_browser
        try:
            module._with_browser = lambda fn: fn(browser)
            lifecycle = module._tab_lifecycle("list_owned")
        finally:
            module._with_browser = original_with_browser

        assert lifecycle["owned_tab_count"] == 1
        assert lifecycle["owned_tabs"][0]["target_id"] == "confirmation-after-owner-submit"
        assert lifecycle["owned_tabs"][0]["url"] == confirmation_url


def test_stale_checkout_owner_ambiguity_does_not_guess_or_open_blank_tab() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        state_path = Path(tmpdir) / "secure-browser-tabs.json"
        module = load_tool_module(state_path)
        write_owner_state(state_path, module, "old-checkout", "https://shop.example/checkout")
        browser = FakeBiDiBrowser(
            [
                {"context": "confirmation-a", "url": "https://shop.example/order-confirmation/a", "title": "Order confirmed"},
                {"context": "confirmation-b", "url": "https://shop.example/order-confirmation/b", "title": "Order confirmed"},
            ]
        )

        try:
            module._claim_owner_target(browser, create=False)
        except RuntimeError as exc:
            assert "OWNER_TAB_AMBIGUOUS" in str(exc)
        else:
            raise AssertionError("ambiguous owner recovery should fail explicitly")

        assert browser.created_targets == []


def test_keep_open_without_owned_tab_fails_without_opening_blank_tab() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        state_path = Path(tmpdir) / "secure-browser-tabs.json"
        module = load_tool_module(state_path)
        browser = FakeBiDiBrowser(
            [{"context": "browser-new-tab", "url": "about:blank", "title": ""}]
        )

        original_with_browser = module._with_browser
        try:
            module._with_browser = lambda fn: fn(browser)
            try:
                module._tab_lifecycle("mark_keep_open", keep_reason="owner handoff")
            except RuntimeError as exc:
                assert "OWNER_TAB_ABSENT" in str(exc)
            else:
                raise AssertionError("keep-open must not create a blank tab")
        finally:
            module._with_browser = original_with_browser

        assert browser.created_targets == []


def test_create_still_opens_a_new_owned_tab_for_explicit_new_page_navigation() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        state_path = Path(tmpdir) / "secure-browser-tabs.json"
        module = load_tool_module(state_path)
        browser = FakeBiDiBrowser(
            [{"context": "visible-session-context", "url": "https://example.com/", "title": "Example Domain"}]
        )

        target_id = module._claim_owner_target(browser, create=True)

        assert target_id == "created-1"
        assert browser.created_targets == ["created-1"]


def test_browser_ws_url_uses_wss_for_private_https_firefox_route() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        state_path = Path(tmpdir) / "secure-browser-tabs.json"
        module = load_tool_module(state_path)
        setattr(module, "SECURE_BROWSER_TARGET", "browser.eyrie-firefox")

        assert module._browser_ws_url("https://browser-cdp.eyrie") == "bidi+wss://browser-cdp.eyrie:443/session"
        assert module._browser_ws_url("http://127.0.0.1:54321") == "bidi+ws://127.0.0.1:54321/session"


def test_bidi_page_candidates_ignore_child_iframe_contexts() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        state_path = Path(tmpdir) / "secure-browser-tabs.json"
        module = load_tool_module(state_path)
        browser = FakeBiDiBrowser(
            [
                {
                    "context": "top-level-tab",
                    "url": "https://photos.google.com/",
                    "title": "Photos",
                    "children": [
                        {
                            "context": "child-frame",
                            "url": "https://ogs.google.com/u/0/widget/app",
                            "title": "",
                        }
                    ],
                },
                {"context": "current-visible-tab", "url": "https://example.com/", "title": "Example Domain"},
            ]
        )

        pages = module._page_candidates(browser)
        page_ids = {page["id"] for page in pages}
        assert "top-level-tab" in page_ids
        assert "current-visible-tab" in page_ids
        assert "child-frame" not in page_ids
        try:
            module._claim_owner_target(browser, create=False)
        except RuntimeError as exc:
            assert "OWNER_TAB_ABSENT" in str(exc)
        else:
            raise AssertionError("read-only owner resolution should not claim an unowned top-level tab")
        assert browser.created_targets == []


if __name__ == "__main__":
    test_stale_bidi_context_id_resolves_by_stored_full_access_url()
    test_read_without_owner_surfaces_absent_state_without_opening_blank_tab()
    test_stale_checkout_owner_recovers_same_retailer_confirmation_after_owner_handoff()
    test_stale_checkout_owner_ambiguity_does_not_guess_or_open_blank_tab()
    test_keep_open_without_owned_tab_fails_without_opening_blank_tab()
    test_create_still_opens_a_new_owned_tab_for_explicit_new_page_navigation()
    test_browser_ws_url_uses_wss_for_private_https_firefox_route()
    test_bidi_page_candidates_ignore_child_iframe_contexts()
