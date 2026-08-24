#!/usr/bin/env python3
"""Adversarial contract tests for the Star Pattern Kit session plugin."""

from __future__ import annotations

import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import struct
import sys
import tempfile
import threading
import unittest


sys.dont_write_bytecode = True

REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_PATH = REPO_ROOT / "files/app/hermes/patternkit_session_plugin/tools.py"
SPEC = importlib.util.spec_from_file_location("patternkit_session_plugin_tools", PLUGIN_PATH)
assert SPEC and SPEC.loader
PLUGIN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PLUGIN)
BROKER_PATH = REPO_ROOT / "files/app/hermes/patternkit_session_broker.py"
BROKER_SPEC = importlib.util.spec_from_file_location("patternkit_session_broker", BROKER_PATH)
assert BROKER_SPEC and BROKER_SPEC.loader
BROKER = importlib.util.module_from_spec(BROKER_SPEC)
BROKER_SPEC.loader.exec_module(BROKER)
BRIDGE_PATH = REPO_ROOT / "files/app/patternkit/workbench_bridge.py"
BRIDGE_SPEC = importlib.util.spec_from_file_location("patternkit_session_integration_bridge", BRIDGE_PATH)
assert BRIDGE_SPEC and BRIDGE_SPEC.loader
BRIDGE = importlib.util.module_from_spec(BRIDGE_SPEC)
BRIDGE_SPEC.loader.exec_module(BRIDGE)


class PatternKitSessionPluginTest(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object] | None]] = []

        def request(path: str, *, method: str = "GET", payload: dict[str, object] | None = None) -> dict[str, object]:
            self.calls.append((path, method, payload))
            if path.startswith("/agent/visual"):
                return {
                    "schema": "patternkit.agent.visual/v1",
                    "revision": 7,
                    "mime_type": "image/png",
                    "image_base64": "iVBORw0KGgo=",
                }
            return {"schema": "patternkit.agent.synthetic/v1", "revision": 7, "ok": True}

        self.previous_request = PLUGIN._bridge_request
        PLUGIN._bridge_request = request

    def tearDown(self) -> None:
        PLUGIN._bridge_request = self.previous_request

    def test_status_and_snapshot_use_bounded_supported_bridge_routes(self) -> None:
        status = json.loads(PLUGIN.patternkit_session_status({}))
        snapshot = json.loads(PLUGIN.patternkit_session_snapshot({"session": "atelier"}))

        self.assertTrue(status["ok"])
        self.assertTrue(snapshot["ok"])
        self.assertEqual(self.calls[0], ("/agent/status?session=atelier", "GET", None))
        self.assertEqual(self.calls[1], ("/agent/snapshot?session=atelier", "GET", None))

    def test_session_and_selector_inputs_reject_secret_queries_and_source_actions(self) -> None:
        for invalid in ("", "../atelier", "atelier?token=secret", "atelier&cookie=x"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    PLUGIN._session_name(invalid)
        for invalid in (
            "script:localStorage",
            "#renderButton",
            "#saveButton",
            "a[href*=git]",
            "#control; fetch('/api/save-profile')",
            "input[name=password]",
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    PLUGIN._selector(invalid)

    def test_mutation_always_carries_visible_lease_revision(self) -> None:
        PLUGIN.patternkit_session_click({"session": "atelier", "revision": 11, "selector": "#layoutToggle"})
        PLUGIN.patternkit_session_type({"session": "atelier", "revision": 12, "selector": "#gaugeInput", "text": "24"})
        PLUGIN.patternkit_session_key({"session": "atelier", "revision": 13, "key": "ArrowDown"})

        for _path, method, payload in self.calls:
            self.assertEqual(method, "POST")
            self.assertIsNotNone(payload)
            self.assertEqual(payload["session"], "atelier")
            self.assertIsInstance(payload["revision"], int)
        self.assertEqual([payload["action"] for _, _, payload in self.calls], ["click", "type", "key"])

    def test_key_and_typed_text_are_bounded_and_non_sensitive(self) -> None:
        for invalid in ("F12", "Control+L", "Meta+S", "Alt+Left", "x"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    PLUGIN._key(invalid)
        for invalid in ("joy@example.com", "4111 1111 1111 1111", "password=secret", "x" * 501):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    PLUGIN._typed_text(invalid)

    def test_visual_evidence_is_written_privately_without_returning_base64(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            previous = PLUGIN.SCREENSHOT_DIR
            PLUGIN.SCREENSHOT_DIR = Path(tmpdir)
            try:
                result = json.loads(PLUGIN.patternkit_session_visual_evidence({"session": "atelier"}))
            finally:
                PLUGIN.SCREENSHOT_DIR = previous

            self.assertNotIn("image_base64", result)
            image = Path(result["path"])
            self.assertTrue(image.is_file())
            self.assertEqual(image.stat().st_mode & 0o777, 0o600)
            self.assertEqual(Path(tmpdir).stat().st_mode & 0o777, 0o700)

    def test_bridge_request_never_accepts_absolute_or_browser_origins(self) -> None:
        for invalid in (
            "https://patternkit.eyrie/api/session",
            "https://browser.eyrie/",
            "//patternkit.eyrie/api/session",
            "/agent/status?token=secret",
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    PLUGIN._validate_bridge_path(invalid)

    def test_tool_availability_is_fail_closed_to_exact_star_profile(self) -> None:
        previous = os.environ.get("HERMES_PROFILE")
        previous_socket = PLUGIN.BROKER_SOCKET
        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = Path(tmpdir) / "broker.sock"
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.bind(str(socket_path))
            PLUGIN.BROKER_SOCKET = socket_path
            try:
                for profile, expected in (("star", True), ("talon", False), ("beryl", False), ("", False)):
                    os.environ["HERMES_PROFILE"] = profile
                    with self.subTest(profile=profile):
                        self.assertEqual(PLUGIN.check_requirements(), expected)
            finally:
                listener.close()
                PLUGIN.BROKER_SOCKET = previous_socket
                if previous is None:
                    os.environ.pop("HERMES_PROFILE", None)
                else:
                    os.environ["HERMES_PROFILE"] = previous

    def test_plugin_is_credential_free_and_cannot_invoke_kubectl(self) -> None:
        source = PLUGIN_PATH.read_text()

        self.assertNotIn("PATTERNKIT_SESSION_TOKEN", source)
        self.assertNotIn("PATTERNKIT_AGENT_TOKEN", source)
        self.assertNotIn("kubectl", source)
        self.assertNotIn("subprocess", source)

    def test_broker_accepts_only_the_star_gateway_systemd_cgroup(self) -> None:
        class PeerSocket:
            @staticmethod
            def getsockopt(_level, _option, _size):
                return struct.pack("3i", 2468, 1000, 1000)

        previous = BROKER.PROC_ROOT
        with tempfile.TemporaryDirectory() as tmpdir:
            BROKER.PROC_ROOT = Path(tmpdir)
            cgroup = BROKER.PROC_ROOT / "2468/cgroup"
            cgroup.parent.mkdir(parents=True)
            try:
                cgroup.write_text("0::/user.slice/hermes-gateway@star.service\n")
                self.assertTrue(BROKER._peer_is_star_gateway(PeerSocket()))
                cgroup.write_text("0::/user.slice/hermes-gateway@talon.service\n")
                self.assertFalse(BROKER._peer_is_star_gateway(PeerSocket()))
                cgroup.write_text("0::/user.slice/x-hermes-gateway@star.service\n")
                self.assertFalse(BROKER._peer_is_star_gateway(PeerSocket()))
            finally:
                BROKER.PROC_ROOT = previous

    def test_broker_uses_the_port_reported_by_its_own_kubectl_process(self) -> None:
        class Process:
            stdout = io.StringIO("warning from kubectl\nForwarding from 127.0.0.1:23456 -> 8766\n")

            @staticmethod
            def poll():
                return None

        previous = (BROKER.LOCAL_PORT, BROKER.REMOTE_PORT)
        BROKER.LOCAL_PORT, BROKER.REMOTE_PORT = 0, 8766
        try:
            self.assertEqual(BROKER._wait_for_port(Process()), 23456)
        finally:
            BROKER.LOCAL_PORT, BROKER.REMOTE_PORT = previous

    def test_broker_service_waits_boundedly_for_its_runtime_socket(self) -> None:
        service = (REPO_ROOT / "manifests/app/hermes/service.pp").read_text()
        self.assertIn("ExecStartPost=/usr/bin/timeout 30", service)
        self.assertIn("until /usr/bin/test -S /run/patternkit-session-broker/patternkit-session.sock", service)

    def test_public_tool_boundary_returns_sanitized_json_errors(self) -> None:
        def fail(_params: dict[str, object]) -> str:
            raise RuntimeError("bridge failed with token=private")

        result = json.loads(PLUGIN._safe_tool_call(fail, {}))

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "Pattern Kit session operation failed")
        self.assertNotIn("private", json.dumps(result))

    def test_star_managed_toolsets_include_the_plugin_toolset(self) -> None:
        config = (REPO_ROOT / "manifests/app/hermes/config.pp").read_text()

        self.assertIn("$instance_effective_toolsets", config)
        self.assertIn("unique($instance_toolsets + ['patternkit_session'])", config)
        self.assertIn("toolsets                   => $instance_effective_toolsets", config)

    def test_real_plugin_entrypoint_registers_the_complete_tool_surface(self) -> None:
        plugin_dir = PLUGIN_PATH.parent
        package_spec = importlib.util.spec_from_file_location(
            "patternkit_session_plugin_test_package",
            plugin_dir / "__init__.py",
            submodule_search_locations=[str(plugin_dir)],
        )
        assert package_spec and package_spec.loader
        package = importlib.util.module_from_spec(package_spec)
        sys.modules[package_spec.name] = package

        class Context:
            def __init__(self) -> None:
                self.tools = {}

            def register_tool(self, **kwargs) -> None:
                self.tools[kwargs["name"]] = kwargs

        try:
            package_spec.loader.exec_module(package)
            context = Context()
            package.register(context)
        finally:
            for name in list(sys.modules):
                if name == package_spec.name or name.startswith(package_spec.name + "."):
                    sys.modules.pop(name, None)

        self.assertEqual(set(context.tools), {
            "patternkit_session_status",
            "patternkit_session_snapshot",
            "patternkit_session_visual_evidence",
            "patternkit_session_diagnostics",
            "patternkit_session_control",
            "patternkit_session_click",
            "patternkit_session_type",
            "patternkit_session_key",
        })
        self.assertTrue(all(tool["toolset"] == "patternkit_session" for tool in context.tools.values()))
        self.assertTrue(all(callable(tool["check_fn"]) for tool in context.tools.values()))

    def test_plugin_transport_reaches_authenticated_live_shaped_bidi_canary(self) -> None:
        class FakeBidi:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

        previous_request = PLUGIN._bridge_request
        real_request = self.previous_request
        previous_profile = os.environ.get("HERMES_PROFILE")
        previous_socket = PLUGIN.BROKER_SOCKET
        previous_agent_token = BRIDGE.AGENT_TOKEN
        previous_bidi = BRIDGE._Bidi
        previous_contexts = BRIDGE._browser_contexts
        previous_broker = (BROKER.TOKEN, BROKER.LOCAL_PORT, BROKER._peer_is_star_gateway)
        bridge_server = BRIDGE.ThreadingHTTPServer(("127.0.0.1", 0), BRIDGE.Handler)
        bridge_thread = threading.Thread(target=bridge_server.serve_forever, daemon=True)
        bridge_thread.start()
        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = Path(tmpdir) / "broker.sock"
            broker_server = BROKER.UnixServer(str(socket_path), BROKER.Handler)
            broker_thread = threading.Thread(target=broker_server.serve_forever, daemon=True)
            broker_thread.start()
            PLUGIN.BROKER_SOCKET = socket_path
            PLUGIN._bridge_request = real_request
            os.environ["HERMES_PROFILE"] = "star"
            BRIDGE.__dict__["AGENT_TOKEN"] = "dedicated-agent-token"
            BRIDGE._Bidi = FakeBidi
            BRIDGE._browser_contexts = lambda _bidi=None: [
                {"id": "private-context", "url": "https://patternkit.eyrie/?session=atelier", "title": "Pattern Kit"},
            ]
            BROKER.__dict__["TOKEN"] = "dedicated-agent-token"
            BROKER.__dict__["LOCAL_PORT"] = bridge_server.server_address[1]
            BROKER._peer_is_star_gateway = lambda _connection: True
            try:
                result = PLUGIN._bridge_request("/agent/runtime-canary")
            finally:
                broker_server.shutdown()
                broker_server.server_close()
                broker_thread.join(timeout=2)
                bridge_server.shutdown()
                bridge_server.server_close()
                bridge_thread.join(timeout=2)
                PLUGIN.BROKER_SOCKET = previous_socket
                PLUGIN._bridge_request = previous_request
                BRIDGE.__dict__["AGENT_TOKEN"] = previous_agent_token
                BRIDGE._Bidi = previous_bidi
                BRIDGE._browser_contexts = previous_contexts
                BROKER.TOKEN, BROKER.LOCAL_PORT, BROKER._peer_is_star_gateway = previous_broker
                if previous_profile is None:
                    os.environ.pop("HERMES_PROFILE", None)
                else:
                    os.environ["HERMES_PROFILE"] = previous_profile

        self.assertTrue(result["ok"])
        self.assertEqual(result["bidi"], "ready")
        self.assertEqual(result["patternkit_context_count"], 1)
        self.assertNotIn("private-context", json.dumps(result))

    def test_puppet_keeps_the_agent_token_out_of_star_and_runs_a_root_broker(self) -> None:
        config = (REPO_ROOT / "manifests/app/hermes/config.pp").read_text()
        service = (REPO_ROOT / "manifests/app/hermes/service.pp").read_text()

        self.assertNotIn("'PATTERNKIT_SESSION_TOKEN' =>", config)
        self.assertIn("patternkit-session-broker.service", service)
        self.assertIn("User=root", service)
        self.assertIn("RuntimeDirectory=patternkit-session-broker", service)
        self.assertIn("PATTERNKIT_SESSION_BRIDGE_TOKEN", service)
        self.assertIn("patternkit_session_broker.py", service)


if __name__ == "__main__":
    unittest.main()
