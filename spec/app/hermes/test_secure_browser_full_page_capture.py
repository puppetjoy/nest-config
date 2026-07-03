#!/usr/bin/env python3
"""Regression checks for secure_browser full-page and owner-review captures."""

from __future__ import annotations

import base64
import importlib.util
import sys
import tempfile
import types
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
SECURE_BROWSER_TOOL = REPO_ROOT / "files/app/hermes/secure_browser_tool.py"
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


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

    spec = importlib.util.spec_from_file_location("secure_browser_full_page_under_test", SECURE_BROWSER_TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    setattr(module, "OWNERSHIP_STATE_PATH", str(state_path))
    setattr(module, "BROWSER_OWNER", "shopping-test")
    return module


def test_bidi_capture_screenshot_uses_document_origin_for_full_page() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        module = load_tool_module(Path(tmpdir) / "secure-browser-tabs.json")

        class FakeBiDiSession(module.CdpSession):
            def __init__(self) -> None:
                self.next_id = 1
                self.cdp_url = None
                self.protocol = "bidi"
                self._bidi_session_created = True
                self.calls: list[tuple[str, dict[str, Any]]] = []

            def _bidi(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
                self.calls.append((method, params or {}))
                return {"data": base64.b64encode(TINY_PNG).decode("ascii")}

        browser = FakeBiDiSession()
        browser.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True}, session_id="tab-1")
        browser.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}, session_id="tab-1")

        capture_calls = [params for method, params in browser.calls if method == "browsingContext.captureScreenshot"]
        assert capture_calls[0] == {"context": "tab-1", "origin": "document"}
        assert capture_calls[1] == {"context": "tab-1", "origin": "viewport"}


def test_owner_review_falls_back_to_viewport_sequence_covering_below_fold() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        module = load_tool_module(Path(tmpdir) / "secure-browser-tabs.json")
        setattr(module, "OWNER_CHECKOUT_REVIEW_DIR", tmpdir)
        setattr(module, "MAX_OWNER_REVIEW_VIEWPORTS", 12)
        setattr(module, "_telegram_send_document", lambda path, caption: {"message_id": Path(path).name, "caption": caption})

        class FakeBrowser:
            def __init__(self) -> None:
                self.scroll_positions: list[int] = []
                self.viewport_captures = 0

            def call(self, method: str, params: dict[str, Any] | None = None, session_id: str | None = None) -> dict[str, Any]:
                assert method == "Page.captureScreenshot"
                assert session_id == "checkout-tab"
                if (params or {}).get("captureBeyondViewport"):
                    raise RuntimeError("full-document screenshot unavailable")
                self.viewport_captures += 1
                return {"data": base64.b64encode(TINY_PNG).decode("ascii")}

        fake = FakeBrowser()

        def fake_evaluate(_browser: Any, _session_id: str, expression: str) -> Any:
            if "document.documentElement.scrollHeight" in expression:
                return {"width": 1200, "height": 2500, "viewport_width": 1200, "viewport_height": 1000, "original_x": 0, "original_y": 321}
            if expression.startswith("window.scrollTo(0,"):
                fake.scroll_positions.append(int(expression.rsplit(",", 1)[1].rstrip(")")))
                return None
            if expression.startswith("window.scrollTo("):
                return None
            return None

        setattr(module, "_evaluate", fake_evaluate)

        capture_mode, deliveries, artifact_hashes, artifact_count = module._capture_owner_visual_artifacts(
            fake,
            "checkout-tab",
            "review123",
            False,
            lambda index, count, mode: f"caption {index}/{count} {mode}",
        )

        assert capture_mode == "viewport-sequence"
        assert fake.scroll_positions[:3] == [0, 1000, 1500]
        assert fake.scroll_positions[-1] == 321
        assert fake.viewport_captures == 3
        assert artifact_count == 3
        assert len(deliveries) == 3
        assert len(artifact_hashes) == 3


def test_owner_review_scroll_positions_include_bottom_when_capped() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        module = load_tool_module(Path(tmpdir) / "secure-browser-tabs.json")
        setattr(module, "MAX_OWNER_REVIEW_VIEWPORTS", 4)

        positions = module._owner_review_scroll_positions({"height": 10000, "viewport_height": 1000})

        assert len(positions) == 4
        assert positions[0] == 0
        assert positions[-1] == 9000


def test_full_page_dimensions_detect_viewport_only_downgrade() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        module = load_tool_module(Path(tmpdir) / "secure-browser-tabs.json")

        layout = {"height": 3000, "viewport_height": 1000, "viewport_width": 1200, "device_scale_factor": 1}

        assert module._image_covers_document(1200, 3000, layout)
        assert not module._image_covers_document(1200, 1000, layout)


if __name__ == "__main__":
    test_bidi_capture_screenshot_uses_document_origin_for_full_page()
    test_owner_review_falls_back_to_viewport_sequence_covering_below_fold()
    test_owner_review_scroll_positions_include_bottom_when_capped()
    test_full_page_dimensions_detect_viewport_only_downgrade()
