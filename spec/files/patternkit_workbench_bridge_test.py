#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import time
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
            "session": "atelier",
        }

    def context(self, url: str, target_id: str = "tab-A") -> dict[str, str]:
        return {"id": target_id, "url": url}

    def assert_binding(self, url: str, expected: bool) -> None:
        valid, origin_matches = BRIDGE._binding_matches(self.state, "123:456", self.context(url))
        self.assertEqual(valid, expected)
        self.assertEqual(origin_matches, url.startswith("https://patternkit.eyrie/"))

    def test_accepts_exact_binding_on_exact_origin(self) -> None:
        self.assert_binding("https://patternkit.eyrie/?session=atelier&pk-share=expected-binding", True)

    def test_rejects_cross_session_and_ambiguous_session_bindings(self) -> None:
        self.assert_binding("https://patternkit.eyrie/?session=other&pk-share=expected-binding", False)
        self.assert_binding("https://patternkit.eyrie/?session=atelier&session=other&pk-share=expected-binding", False)

        binding = BRIDGE._require_exact_binding({
            "bound": True,
            "selected_context": "tab-A",
            "browser_generation": "123:456",
            "active_origin_matches": True,
            "session": "atelier",
        }, "atelier")
        self.assertEqual(binding["session"], "atelier")
        with self.assertRaises(BRIDGE.AgentRequestError):
            BRIDGE._require_exact_binding(binding, "other")

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
        url = "https://patternkit.eyrie/?session=atelier&pk-share=expected-binding"
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

    def test_agent_routes_require_a_fresh_exact_binding(self) -> None:
        valid = {
            "bound": True,
            "selected_context": "tab-A",
            "browser_generation": "123:456",
            "active_origin_matches": True,
        }
        valid["session"] = "atelier"
        self.assertEqual(BRIDGE._require_exact_binding(valid, "atelier")["selected_context"], "tab-A")
        for changed in (
            {**valid, "bound": False},
            {**valid, "selected_context": None},
            {**valid, "browser_generation": None},
            {**valid, "active_origin_matches": False},
        ):
            with self.subTest(changed=changed):
                with self.assertRaises(BRIDGE.AgentRequestError):
                    BRIDGE._require_exact_binding(changed, "atelier")

    def test_agent_authorization_does_not_accept_the_smoke_token(self) -> None:
        handler = object.__new__(BRIDGE.Handler)
        previous_bridge = BRIDGE.BRIDGE_TOKEN
        previous_agent = BRIDGE.AGENT_TOKEN
        try:
            BRIDGE.__dict__["BRIDGE_TOKEN"] = "smoke-secret"
            BRIDGE.__dict__["AGENT_TOKEN"] = "star-secret"
            handler.headers = {"X-PatternKit-Agent-Token": "smoke-secret"}
            self.assertFalse(handler._agent_authorized(send_error=False))
            handler.headers = {"X-PatternKit-Agent-Token": "star-secret"}
            self.assertTrue(handler._agent_authorized(send_error=False))
        finally:
            BRIDGE.__dict__["BRIDGE_TOKEN"] = previous_bridge
            BRIDGE.__dict__["AGENT_TOKEN"] = previous_agent

    def test_supported_studio_paths_reject_login_redirects_and_secret_queries(self) -> None:
        self.assertEqual(BRIDGE._studio_api_path("session", "atelier"), "/api/session?name=atelier")
        self.assertEqual(
            BRIDGE._studio_api_path("diagnostics", "atelier"),
            "/api/diagnostics/capture?name=atelier",
        )
        for invalid in ("", "../atelier", "atelier?token=x", "atelier&cookie=x"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(BRIDGE.AgentRequestError):
                    BRIDGE._session_name(invalid)
        with self.assertRaises(BRIDGE.AgentRequestError):
            BRIDGE._decode_studio_response(302, {"Location": "https://gitlab.joyfullee.me/oauth/authorize"}, b"")
        with self.assertRaises(BRIDGE.AgentRequestError):
            BRIDGE._decode_studio_response(200, {"Content-Type": "text/html"}, b"<form>login</form>")

    def test_status_and_snapshot_publish_only_redacted_supported_api_state(self) -> None:
        raw = {
            "name": "atelier",
            "revision": 9,
            "state": {"session": {"profile": "private-profile", "measurements": {"waist": 812}}},
            "presence": {"joy": {"mode": "inspect"}, "star": {"mode": "inspect"}},
            "control": {"holder": "star", "expires_at": 1000},
        }
        compact = BRIDGE._compact_session(raw)
        encoded = str(compact)
        self.assertEqual(compact["revision"], 9)
        self.assertEqual(compact["control_owner"], "star")
        self.assertEqual(set(compact["presence"]), {"joy", "star"})
        self.assertNotIn("measurements", encoded)
        self.assertNotIn("private-profile", encoded)

    def test_mutation_requires_star_lease_and_exact_revision(self) -> None:
        snapshot = {"revision": 12, "control": {"holder": "star", "expires_at": time.time() + 60}}
        BRIDGE._require_star_lease(snapshot, 12)
        for changed, revision in (
            ({"revision": 12, "control": {"holder": "joy", "expires_at": time.time() + 60}}, 12),
            ({"revision": 12, "control": {"holder": None, "expires_at": None}}, 12),
            ({"revision": 12, "control": {"holder": "star", "expires_at": time.time() - 1}}, 12),
            (snapshot, 11),
        ):
            with self.subTest(changed=changed, revision=revision):
                with self.assertRaises(BRIDGE.AgentRequestError):
                    BRIDGE._require_star_lease(changed, revision)

    def test_browser_diagnostics_strip_queries_headers_and_private_values(self) -> None:
        event = BRIDGE._sanitize_browser_event(
            {
                "type": "network.responseCompleted",
                "url": "https://patternkit.eyrie/api/render?token=secret",
                "status": 503,
                "duration_ms": 1500,
                "headers": {"Authorization": "Bearer secret"},
                "body": "private measurements",
            },
            slow_ms=1000,
        )
        self.assertEqual(event["origin_scope"], "patternkit")
        self.assertNotIn("url", event)
        self.assertEqual(event["status"], 503)
        self.assertTrue(event["failed"])
        self.assertTrue(event["slow"])
        self.assertNotIn("headers", event)
        self.assertNotIn("body", event)
        console = BRIDGE._sanitize_browser_event(
            {"type": "log.entryAdded", "level": "error", "message": "measurement waist=812 token=secret"},
            slow_ms=1000,
        )
        self.assertEqual(console["message"], "[REDACTED]")
        arbitrary_private_console = BRIDGE._sanitize_browser_event(
            {
                "type": "log.entryAdded",
                "level": "error",
                "message": "render failed for Joyful at Riverdale with value 812",
            },
            slow_ms=1000,
        )
        self.assertEqual(arbitrary_private_console["message"], "render failed for [REDACTED] at [REDACTED] with value [REDACTED]")
        for private in ("Joyful", "Riverdale", "812"):
            self.assertNotIn(private, str(arbitrary_private_console))
        sensitive_url = BRIDGE._sanitize_browser_event(
            {"type": "network", "url": "https://private-user:private-pass@example.test/profiles/joy?token=value"},
            slow_ms=1000,
        )
        self.assertEqual(sensitive_url["origin_scope"], "external")
        self.assertNotIn("private", str(sensitive_url))

    def test_public_binding_never_exposes_context_process_node_session_or_url(self) -> None:
        public = BRIDGE._public_binding({
            "schema": "patternkit.workbench.binding/v1",
            "bound": True,
            "binding_id": "private-binding",
            "selected_context": "private-context",
            "origin": "https://patternkit.eyrie",
            "node": "owl",
            "browser_generation": "123:456",
            "active_origin_matches": True,
            "session": "atelier",
            "reason": "verified-active-tab",
        })
        self.assertTrue(public["active_context_verified"])
        self.assertTrue(public["patternkit_origin_verified"])
        encoded = str(public)
        for private in ("private-binding", "private-context", "https://", "owl", "123:456", "atelier"):
            self.assertNotIn(private, encoded)

    def test_context_isolation_rejects_any_other_http_origin(self) -> None:
        self.assertTrue(BRIDGE._contexts_are_isolated([
            {"url": "https://patternkit.eyrie/?session=atelier"},
            {"url": "about:blank"},
        ]))
        self.assertFalse(BRIDGE._contexts_are_isolated([
            {"url": "https://patternkit.eyrie/"},
            {"url": "https://browser.eyrie/"},
        ]))

    def test_app_diagnostics_are_whitelisted_even_if_the_upstream_regresses(self) -> None:
        sanitized = BRIDGE._sanitize_app_diagnostic({
            "schema": "patternkit.studio.diagnostic-capture/v1",
            "captured_at": 123.0,
            "session": {
                "name": "atelier",
                "revision": 9,
                "state": {
                    "session": {"target": "garment:coat", "profile": "private-profile"},
                    "measurements": {"waist": 812},
                    "options": {"ease": 12},
                },
                "presence": {"joy": {"mode": "inspect"}, "star": {"mode": "control"}},
                "control": {"holder": "star", "expires_at": 456.0},
                "cookie": "private-cookie",
            },
            "authorization": "Bearer private",
        })

        encoded = str(sanitized)
        self.assertEqual(sanitized["session"]["target"], "garment:coat")
        self.assertEqual(sanitized["session"]["presence"], ["joy", "star"])
        self.assertNotIn("812", encoded)
        self.assertNotIn("private-profile", encoded)
        self.assertNotIn("private-cookie", encoded)
        self.assertNotIn("Bearer", encoded)

        poisoned = BRIDGE._sanitize_app_diagnostic({
            "session": {
                "name": "atelier-token-private",
                "revision": 10,
                "state": {"session": {"target": "mailto:joy@example.com?token=private"}},
                "presence": {
                    "star": {"mode": "control"},
                    "joy@example.com": {"mode": "inspect"},
                },
                "control": {"holder": "joy@example.com"},
            },
        })
        poisoned_encoded = str(poisoned)
        self.assertEqual(poisoned["session"]["name"], "[REDACTED]")
        self.assertEqual(poisoned["session"]["target"], "[REDACTED]")
        self.assertEqual(poisoned["session"]["presence"], ["human", "star"])
        self.assertEqual(poisoned["session"]["control_owner"], "human")
        self.assertNotIn("joy@example.com", poisoned_encoded)
        self.assertNotIn("private", poisoned_encoded)

    def test_verified_browser_receipt_requires_star_identity_and_expected_revision(self) -> None:
        before = {"revision": 12, "control": {"holder": "star", "expires_at": time.time() + 60}}
        after = {"revision": 13, "control": {"holder": "star", "expires_at": time.time() + 60}}
        receipt = {"status": 200, "actor": "star", "session": "atelier", "revision": 12}
        BRIDGE._verify_browser_receipt("atelier", 12, before, after, receipt, mutates_session=True)
        for changed in (
            {**receipt, "actor": "joy"},
            {**receipt, "session": "other"},
            {**receipt, "revision": 11},
            {**receipt, "status": 409},
        ):
            with self.subTest(changed=changed):
                with self.assertRaises(BRIDGE.AgentRequestError):
                    BRIDGE._verify_browser_receipt("atelier", 12, before, after, changed, mutates_session=True)
        with self.assertRaises(BRIDGE.AgentRequestError):
            BRIDGE._verify_browser_receipt("atelier", 12, before, before, receipt, mutates_session=True)
        too_far = {**before, "revision": 14}
        with self.assertRaises(BRIDGE.AgentRequestError):
            BRIDGE._verify_browser_receipt("atelier", 12, before, too_far, receipt, mutates_session=True)
        with self.assertRaises(BRIDGE.AgentRequestError):
            BRIDGE._verify_browser_receipt("atelier", 12, before, changed, receipt, mutates_session=False)

    def test_browser_intercept_injects_star_only_for_supported_patternkit_posts(self) -> None:
        class FakeBidi:
            def __init__(self) -> None:
                self.calls = []

            def call(self, method, params=None):
                self.calls.append((method, params))
                return {}

        previous = BRIDGE.STUDIO_BRIDGE_TOKEN
        BRIDGE.__dict__["STUDIO_BRIDGE_TOKEN"] = "dedicated-star-token"
        try:
            bidi = FakeBidi()
            accepted = BRIDGE._continue_as_star(bidi, {
                "method": "network.beforeRequestSent",
                "params": {
                    "isBlocked": True,
                    "intercepts": ["intercept-1"],
                    "request": {
                        "request": "request-1",
                        "method": "POST",
                        "url": "https://patternkit.eyrie/api/session/state?ignored=1",
                        "headers": [{"name": "Content-Type", "value": {"type": "string", "value": "application/json"}}],
                    },
                },
            }, intercept="intercept-1", operation="operation-1", session="atelier", revision=12)
            self.assertEqual(accepted, ("request-1", "/api/session/state", "operation-1"))
            continued = bidi.calls[-1][1]
            self.assertEqual(continued["request"], "request-1")
            self.assertIn("dedicated-star-token", str(continued["headers"]))
            self.assertIn("pk-session=atelier", continued["url"])
            self.assertIn("pk-revision=12", continued["url"])

            for url in (
                "https://browser.eyrie/api/session/state",
                "https://patternkit.eyrie/api/save-profile",
                "https://patternkit.eyrie/api/session/control",
                "https://patternkit.eyrie/api/render",
            ):
                bidi = FakeBidi()
                with self.assertRaises(BRIDGE.AgentRequestError):
                    BRIDGE._continue_as_star(bidi, {
                        "params": {
                            "isBlocked": True,
                            "intercepts": ["intercept-1"],
                            "request": {"request": "request-2", "method": "POST", "url": url, "headers": []},
                        },
                    }, intercept="intercept-1", operation="operation-1", session="atelier", revision=12)
                self.assertNotIn("dedicated-star-token", str(bidi.calls))
                self.assertEqual(bidi.calls[-1][0], "network.failRequest")
        finally:
            BRIDGE.__dict__["STUDIO_BRIDGE_TOKEN"] = previous

    def test_browser_response_receipt_is_bound_to_the_guarded_star_operation(self) -> None:
        guarded = ("request-1", "/api/session/state", "operation-1")
        event = {
            "params": {
                "request": {
                    "request": "request-1",
                    "method": "POST",
                    "url": (
                        "https://patternkit.eyrie/api/session/state?"
                        "pk-agent-operation=operation-1&pk-session=atelier&pk-revision=12"
                    ),
                },
                "response": {"status": 200},
            },
        }
        self.assertEqual(
            BRIDGE._browser_response_receipt(event, guarded, session="atelier", revision=12),
            {
                "status": 200,
                "path": "/api/session/state",
                "operation": "operation-1",
                "actor": "star",
                "session": "atelier",
                "revision": 12,
            },
        )
        for changed in (
            {**event, "params": {**event["params"], "request": {**event["params"]["request"], "request": "other"}}},
            {**event, "params": {**event["params"], "request": {**event["params"]["request"], "url": "https://patternkit.eyrie/api/session/state?pk-agent-operation=wrong&pk-session=atelier&pk-revision=12"}}},
            {**event, "params": {**event["params"], "request": {**event["params"]["request"], "url": "https://browser.eyrie/api/session/state?pk-agent-operation=operation-1&pk-session=atelier&pk-revision=12"}}},
            {**event, "params": {**event["params"], "request": {**event["params"]["request"], "url": "https://patternkit.eyrie/api/render?pk-agent-operation=operation-1&pk-session=atelier&pk-revision=12"}}},
        ):
            with self.subTest(changed=changed):
                self.assertIsNone(BRIDGE._browser_response_receipt(changed, guarded, session="atelier", revision=12))

    def test_agent_input_transaction_requires_atomic_state_receipt(self) -> None:
        snapshots = [
            {"name": "atelier", "revision": 12, "presence": {"star": {}}, "control": {"holder": "star", "expires_at": time.time() + 60}},
            {"name": "atelier", "revision": 13, "presence": {"star": {}}, "control": {"holder": "star", "expires_at": time.time() + 60}},
        ]
        previous_studio = BRIDGE._studio_request
        previous_browser = BRIDGE._browser_input
        BRIDGE._studio_request = lambda *_args, **_kwargs: snapshots.pop(0)
        BRIDGE._browser_input = lambda *_args, **_kwargs: {
            "status": 200,
            "path": "/api/session/state",
            "operation": "operation-1",
            "actor": "star",
            "session": "atelier",
            "revision": 12,
        }
        try:
            result = BRIDGE._execute_agent_input(
                {"selected_context": "tab-A"},
                {"session": "atelier", "revision": 12, "action": "type", "selector": "#gaugeInput", "text": "24"},
            )
        finally:
            BRIDGE._studio_request = previous_studio
            BRIDGE._browser_input = previous_browser

        self.assertTrue(result["ok"])
        self.assertEqual(result["session"]["revision"], 13)
        self.assertEqual(snapshots, [])

    def test_runtime_canary_exercises_bidi_without_exposing_context_ids_or_urls(self) -> None:
        class FakeBidi:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

        previous_bidi = BRIDGE._Bidi
        previous_contexts = BRIDGE._browser_contexts
        previous_generation = BRIDGE._browser_start_identity
        BRIDGE._Bidi = FakeBidi
        BRIDGE._browser_contexts = lambda _bidi=None: [
            {"id": "private-tab-id", "url": "https://patternkit.eyrie/?session=atelier", "title": "Pattern Kit"},
            {"id": "other-private-tab-id", "url": "about:blank", "title": ""},
        ]
        BRIDGE._browser_start_identity = lambda: "100:200"
        try:
            result = BRIDGE._agent_runtime_canary()
        finally:
            BRIDGE._Bidi = previous_bidi
            BRIDGE._browser_contexts = previous_contexts
            BRIDGE._browser_start_identity = previous_generation

        self.assertTrue(result["ok"])
        self.assertEqual(result["context_count"], 2)
        self.assertEqual(result["patternkit_context_count"], 1)
        self.assertEqual(result["external_context_count"], 0)
        self.assertNotIn("private-tab-id", str(result))
        self.assertNotIn("https://", str(result))

    def test_studio_operations_resolve_one_exact_child_frame(self) -> None:
        class FakeBidi:
            @staticmethod
            def call(method, params=None):
                self.assertEqual(method, "browsingContext.getTree")
                self.assertEqual(params, {"root": "tab-A"})
                return {"contexts": [{
                    "context": "tab-A",
                    "url": "https://patternkit.eyrie/?session=atelier",
                    "children": [{"context": "studio-frame", "url": "https://patternkit.eyrie/studio/", "children": []}],
                }]}

        previous = BRIDGE._exact_bidi_context
        BRIDGE._exact_bidi_context = lambda *_args: {"id": "tab-A", "url": "https://patternkit.eyrie/?session=atelier"}
        try:
            self.assertEqual(BRIDGE._studio_bidi_context(FakeBidi(), {}), {"id": "studio-frame", "url": "https://patternkit.eyrie/studio/"})
        finally:
            BRIDGE._exact_bidi_context = previous

    def test_control_lease_changes_share_the_agent_operation_lock(self) -> None:
        previous = BRIDGE._studio_request

        def studio_request(*_args, **_kwargs):
            self.assertTrue(BRIDGE._AGENT_OPERATION_LOCK.locked())
            return {"name": "atelier", "revision": 3, "presence": {}, "control": {"holder": "star"}}

        BRIDGE._studio_request = studio_request
        try:
            result = BRIDGE._execute_agent_control({"session": "atelier", "action": "acquire"})
        finally:
            BRIDGE._studio_request = previous
        self.assertTrue(result["ok"])

    def test_visual_evidence_intersects_canvas_with_the_frame_viewport(self) -> None:
        source = Path(BRIDGE_PATH).read_text()
        self.assertIn("right=Math.min(innerWidth,r.right)", source)
        self.assertIn("bottom=Math.min(innerHeight,r.bottom)", source)
        self.assertIn("width:right-left,height:bottom-top", source)

    def test_browser_input_subscribes_before_waiting_for_response_receipts(self) -> None:
        source = Path(BRIDGE_PATH).read_text()
        subscribe = source.index('"session.subscribe"')
        intercept = source.index('"network.addIntercept"')
        self.assertLess(subscribe, intercept)
        self.assertIn('"network.responseCompleted"', source[subscribe:intercept])

    def test_navigation_key_fails_without_a_guarded_studio_receipt(self) -> None:
        class FakeBidi:
            def __init__(self) -> None:
                self.calls = []

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def call(self, method, params=None):
                self.calls.append((method, params))
                return {"intercept": "intercept-1"} if method == "network.addIntercept" else {}

            @staticmethod
            def event(_timeout):
                return None

        previous_bidi = BRIDGE._Bidi
        previous_context = BRIDGE._studio_bidi_context
        previous_evaluate = BRIDGE._evaluate
        BRIDGE._Bidi = FakeBidi
        BRIDGE._studio_bidi_context = lambda *_args: {"id": "studio-frame"}
        BRIDGE._evaluate = lambda _bidi, _context, expression: "safeControl" if "activeElement" in expression else {"ok": True}
        try:
            with self.assertRaises(BRIDGE.AgentRequestError):
                BRIDGE._browser_input(
                    {"selected_context": "tab-A"},
                    "key",
                    None,
                    None,
                    "ArrowDown",
                    session="atelier",
                    revision=12,
                )
        finally:
            BRIDGE._Bidi = previous_bidi
            BRIDGE._studio_bidi_context = previous_context
            BRIDGE._evaluate = previous_evaluate


    def test_direct_studio_requests_use_agent_not_synthetic_smoke_identity(self) -> None:
        captured = {}

        class Response:
            status = 200
            headers = {"Content-Type": "application/json"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            @staticmethod
            def read(_limit):
                return b'{}'

        class Opener:
            @staticmethod
            def open(request, timeout):
                captured["request"] = request
                captured["timeout"] = timeout
                return Response()

        previous = (BRIDGE.STUDIO_BRIDGE_TOKEN, BRIDGE.BRIDGE_TOKEN, BRIDGE.build_opener)
        BRIDGE.__dict__.update({
            "STUDIO_BRIDGE_TOKEN": "dedicated-agent-token",
            "BRIDGE_TOKEN": "synthetic-smoke-token",
            "build_opener": lambda *_args: Opener(),
        })
        try:
            BRIDGE._studio_request("GET", "/api/session?name=atelier")
            self.assertEqual(captured["request"].get_header("X-patternkit-bridge-token"), "dedicated-agent-token")
            self.assertNotIn("synthetic-smoke-token", str(captured))
        finally:
            BRIDGE.STUDIO_BRIDGE_TOKEN, BRIDGE.BRIDGE_TOKEN, BRIDGE.build_opener = previous

    def test_safe_browser_controls_cannot_trigger_source_or_sensitive_actions(self) -> None:
        self.assertEqual(BRIDGE._safe_selector("#gaugeInput"), "#gaugeInput")
        for invalid in ("#renderButton", "#saveButton", "#exportButton", "input[name=password]", "script:localStorage"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(BRIDGE.AgentRequestError):
                    BRIDGE._safe_selector(invalid)
        for invalid in ("Control+L", "Meta+S", "F12", "x"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(BRIDGE.AgentRequestError):
                    BRIDGE._safe_key(invalid)

    def test_every_bidi_attach_rechecks_the_browser_proven_active_tab(self) -> None:
        previous_contexts = BRIDGE._browser_contexts
        previous_active = BRIDGE._active_context
        previous_state = BRIDGE._read_state
        previous_process = BRIDGE._browser_start_identity
        BRIDGE._browser_contexts = lambda _bidi=None: [
            {"id": "tab-A", "url": "https://patternkit.eyrie/?pk-share=binding", "title": "Pattern Kit"},
        ]
        BRIDGE._active_context = lambda _bidi=None: {
            "id": "tab-B",
            "url": "https://patternkit.eyrie/?pk-share=other",
        }
        BRIDGE._read_state = lambda: {
            "binding_id": "binding",
            "browser_start_identity": "100:200",
            "target_id": "tab-A",
        }
        BRIDGE._browser_start_identity = lambda: "100:200"
        try:
            with self.assertRaises(BRIDGE.AgentRequestError):
                BRIDGE._exact_bidi_context(object(), {"selected_context": "tab-A"})
        finally:
            BRIDGE._browser_contexts = previous_contexts
            BRIDGE._active_context = previous_active
            BRIDGE._read_state = previous_state
            BRIDGE._browser_start_identity = previous_process


if __name__ == "__main__":
    unittest.main()
