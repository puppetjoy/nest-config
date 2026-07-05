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


def test_stale_bidi_context_id_resolves_by_stored_sanitized_url() -> None:
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
        assert stored["url"] == "https://www.amazon.com/gp/your-account/order-history"
        assert "ref_=" not in stored["url"]


def test_no_owner_match_opens_agent_owned_tab_without_claiming_unowned_page() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        state_path = Path(tmpdir) / "secure-browser-tabs.json"
        module = load_tool_module(state_path)
        browser = FakeBiDiBrowser(
            [
                {"context": "blank-session-context", "url": "about:blank", "title": ""},
                {"context": "visible-session-context", "url": "https://example.com/", "title": "Example Domain"},
            ]
        )

        target_id = module._claim_owner_target(browser, create=False)

        assert target_id == "created-1"
        assert browser.created_targets == ["created-1"]
        stored = json.loads(state_path.read_text(encoding="utf-8"))
        assert stored["owners"][module.BROWSER_OWNER]["target_id"] == "created-1"
        assert "visible-session-context" not in stored.get("owner_tabs", {}).get(module.BROWSER_OWNER, {})


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
        target_id = module._claim_owner_target(browser, create=False)

        assert "top-level-tab" in page_ids
        assert "current-visible-tab" in page_ids
        assert "child-frame" not in page_ids
        assert target_id == "created-1"
        assert browser.created_targets == ["created-1"]


if __name__ == "__main__":
    test_stale_bidi_context_id_resolves_by_stored_sanitized_url()
    test_no_owner_match_opens_agent_owned_tab_without_claiming_unowned_page()
    test_create_still_opens_a_new_owned_tab_for_explicit_new_page_navigation()
    test_browser_ws_url_uses_wss_for_private_https_firefox_route()
    test_bidi_page_candidates_ignore_child_iframe_contexts()
