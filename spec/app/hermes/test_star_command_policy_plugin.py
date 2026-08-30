#!/usr/bin/env python3
"""Contract tests for Star's sudo-only approval plugin."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import unittest


sys.dont_write_bytecode = True
REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_PATH = REPO_ROOT / "files/app/hermes/star_command_policy_plugin/__init__.py"
SPEC = importlib.util.spec_from_file_location("star_command_policy_plugin", PLUGIN_PATH)
assert SPEC and SPEC.loader
PLUGIN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PLUGIN)


class StarCommandPolicyPluginTest(unittest.TestCase):
    def test_non_sudo_commands_never_request_approval(self) -> None:
        commands = (
            "python -c 'print(1)'",
            "python - <<'PY'\nprint('sudo is a word')\nPY",
            "bash -lc \"python -c 'print(1)'\"",
            "printf '%s\\n' sudo",
            "grep sudo README.md",
            "FOO=bar env python -c 'print(1)' && git status",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertFalse(PLUGIN.command_invokes_sudo(command))

    def test_direct_compound_and_wrapped_sudo_are_detected(self) -> None:
        commands = (
            "sudo id",
            "FOO=bar sudo id",
            "env FOO=bar sudo -n id",
            "command sudo id",
            "printf ready && sudo id",
            "(sudo id)",
            "bash -lc 'sudo id'",
            "sh -c \"env FOO=bar sudo id\"",
            "bash <<'SH'\nsudo id\nSH",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertTrue(PLUGIN.command_invokes_sudo(command))

    def test_hook_is_exactly_star_terminal_and_per_invocation(self) -> None:
        previous = os.environ.get("HERMES_PROFILE")
        try:
            os.environ["HERMES_PROFILE"] = "star"
            first = PLUGIN._on_pre_tool_call(
                tool_name="terminal",
                args={"command": "sudo id"},
                tool_call_id="call-one",
            )
            second = PLUGIN._on_pre_tool_call(
                tool_name="terminal",
                args={"command": "sudo id"},
                tool_call_id="call-two",
            )
            self.assertEqual(first["action"], "approve")
            self.assertEqual(first["rule_key"], "star-sudo:call-one")
            self.assertNotEqual(first["rule_key"], second["rule_key"])
            self.assertIsNone(PLUGIN._on_pre_tool_call(
                tool_name="terminal",
                args={"command": "python -c 'print(1)'"},
            ))
            self.assertIsNone(PLUGIN._on_pre_tool_call(
                tool_name="execute_code",
                args={"code": "print(1)"},
            ))
            os.environ["HERMES_PROFILE"] = "talon"
            self.assertIsNone(PLUGIN._on_pre_tool_call(
                tool_name="terminal",
                args={"command": "sudo id"},
            ))
        finally:
            if previous is None:
                os.environ.pop("HERMES_PROFILE", None)
            else:
                os.environ["HERMES_PROFILE"] = previous

    def test_register_installs_only_the_pre_tool_hook(self) -> None:
        class Context:
            def __init__(self) -> None:
                self.hooks = []

            def register_hook(self, name, callback) -> None:
                self.hooks.append((name, callback))

        context = Context()
        PLUGIN.register(context)
        self.assertEqual(context.hooks, [("pre_tool_call", PLUGIN._on_pre_tool_call)])


if __name__ == "__main__":
    unittest.main()
