#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


sys.dont_write_bytecode = True

REPO_ROOT = Path(__file__).resolve().parents[2]
BRIDGE_PATH = REPO_ROOT / "files/app/patternkit/workbench_bridge.py"
SPEC = importlib.util.spec_from_file_location("patternkit_workbench_bridge", BRIDGE_PATH)
assert SPEC and SPEC.loader
BRIDGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BRIDGE)


class BindingIdentityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = {
            "binding_id": "expected-binding",
            "browser_start_identity": "123:456",
            "target_id": "tab-A",
        }

    def context(self, url: str, target_id: str = "tab-A") -> dict[str, str]:
        return {"id": target_id, "url": url}

    def assert_binding(self, url: str, expected: bool) -> None:
        valid, origin_matches = BRIDGE._binding_matches(self.state, "123:456", self.context(url))
        self.assertEqual(valid, expected)
        self.assertEqual(origin_matches, url.startswith("https://patternkit.eyrie/"))

    def test_accepts_exact_binding_on_exact_origin(self) -> None:
        self.assert_binding("https://patternkit.eyrie/?session=atelier&pk-share=expected-binding", True)

    def test_rejects_stale_browser_generation(self) -> None:
        valid, _ = BRIDGE._binding_matches(
            self.state,
            "789:999",
            self.context("https://patternkit.eyrie/?pk-share=expected-binding"),
        )
        self.assertFalse(valid)

    def test_rejects_wrong_origin_and_inexact_parameter_name(self) -> None:
        self.assert_binding("https://patternkit.eyrie.invalid/?pk-share=expected-binding", False)
        self.assert_binding("https://patternkit.eyrie/?not-pk-share=expected-binding", False)

    def test_rejects_wrong_or_duplicate_binding(self) -> None:
        self.assert_binding("https://patternkit.eyrie/?pk-share=wrong", False)
        self.assert_binding(
            "https://patternkit.eyrie/?pk-share=expected-binding&pk-share=wrong",
            False,
        )

    def test_persisted_target_rejects_another_tab_with_the_same_url(self) -> None:
        url = "https://patternkit.eyrie/?pk-share=expected-binding"
        valid, _ = BRIDGE._binding_matches(self.state, "123:456", self.context(url, "tab-B"))
        self.assertFalse(valid)
        valid, _ = BRIDGE._binding_matches(self.state, "123:456", self.context(url, "tab-A"))
        self.assertTrue(valid)

    def test_missing_target_identity_fails_closed(self) -> None:
        self.state.pop("target_id")
        valid, _ = BRIDGE._binding_matches(
            self.state,
            "123:456",
            self.context("https://patternkit.eyrie/?pk-share=expected-binding"),
        )
        self.assertFalse(valid)

    def test_only_literal_loopback_addresses_are_local(self) -> None:
        self.assertTrue(BRIDGE._is_loopback("127.0.0.1"))
        self.assertTrue(BRIDGE._is_loopback("::1"))
        self.assertFalse(BRIDGE._is_loopback("127.0.0.2"))
        self.assertFalse(BRIDGE._is_loopback("10.0.0.1"))

    def test_remote_status_token_is_compared_exactly(self) -> None:
        handler = object.__new__(BRIDGE.Handler)
        handler.headers = {"X-PatternKit-Bridge-Token": "bridge-secret"}
        previous = BRIDGE.BRIDGE_TOKEN
        try:
            BRIDGE.__dict__["BRIDGE_TOKEN"] = "bridge-secret"
            self.assertTrue(handler._bridge_authorized())
            handler.headers = {"X-PatternKit-Bridge-Token": "bridge-secret-suffix"}
            self.assertFalse(handler._bridge_authorized())
        finally:
            BRIDGE.__dict__["BRIDGE_TOKEN"] = previous

    def test_synthetic_contract_exercises_fail_closed_lifecycle(self) -> None:
        contract = BRIDGE._synthetic_contract()
        self.assertTrue(contract["ok"])
        self.assertTrue(all(contract["cases"].values()))
        self.assertEqual(
            set(contract["cases"]),
            {
                "exact_active_tab",
                "browser_restart_fails_closed",
                "tab_switch_fails_closed",
                "copied_url_fails_closed",
                "stale_nonce_fails_closed",
                "duplicate_nonce_fails_closed",
                "wrong_origin_fails_closed",
            },
        )


if __name__ == "__main__":
    unittest.main()
