#!/usr/bin/env python3
"""Profile isolation and immutable registration contract for Talon's prompt plugin."""

import importlib.util
from pathlib import Path
import sys

import unittest
from unittest.mock import Mock, call, patch


PLUGIN_DIR = Path(__file__).resolve().parents[3] / "files/app/hermes/talon_operational_prompt_plugin"


class TalonOperationalPromptTest(unittest.TestCase):
    def setUp(self):
        # Hermes is a deployment dependency, not a dependency of Nest's tests.
        constants = Mock()
        constants.get_hermes_home = Mock(return_value=Path("/profiles/talon"))
        profiles = Mock()
        profiles.get_active_profile_name = Mock(return_value="talon")
        with patch.dict(sys.modules, {"hermes_constants": constants, "hermes_cli.profiles": profiles}):
            spec = importlib.util.spec_from_file_location("talon_prompt_test", PLUGIN_DIR / "__init__.py")
            assert spec and spec.loader
            self.plugin = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.plugin)
        self.plugin.__file__ = "/profiles/talon/plugins/talon-operational-prompt/__init__.py"
        self.ctx = Mock()

    def test_registers_two_bounded_static_sections(self):
        self.assertEqual(self.plugin.SECTIONS, (
            ("talon.readable-prose", "readable-prose.md", 2048),
            ("talon.delivery-completion", "delivery-completion.md", 1024),
        ))
        expected = [(PLUGIN_DIR / filename).read_text().strip()
                    for _, filename, _ in self.plugin.SECTIONS]
        with patch.object(Path, "read_text", side_effect=expected) as read:
            self.plugin.register(self.ctx)
        self.assertEqual(read.call_count, 2)
        self.ctx.register_system_prompt_section.assert_has_calls([
            call(section_id, content, position="after_memory", max_chars=budget)
            for (section_id, _, budget), content in zip(self.plugin.SECTIONS, expected)
        ])
        self.assertEqual(self.ctx.register_system_prompt_section.call_count, 2)
        self.assertIn("tool arguments, request/context/subject fields", expected[0])
        self.assertIn("Preserve opaque identifiers, hashes, URLs, paths and commands exactly", expected[0])
        self.assertIn("Do not make user validation a completion gate.", expected[1])
        self.assertIn("required approvals, genuinely necessary user input, or known failures", expected[1])
        self.assertIn("briefly identify any checks you could not perform", expected[1])
        for name in ("Agent Request", "Kanban", "Telegram"):
            self.assertNotIn(name, expected[1])
        # Static strings, not callbacks or subsequent asset reads, own the prompt.
        self.assertTrue(all(isinstance(c.args[1], str)
                            for c in self.ctx.register_system_prompt_section.call_args_list))

    def test_other_profiles_never_read_or_register_even_with_inherited_environment(self):
        for name in ("star", "beryl", "quill", "default", "custom"):
            with self.subTest(profile=name), patch.dict("os.environ", {"HERMES_PROFILE": "talon"}):
                self.plugin.get_active_profile_name.return_value = name
                with patch.object(Path, "read_text") as read:
                    self.plugin.register(self.ctx)
                read.assert_not_called()
        self.ctx.register_system_prompt_section.assert_not_called()

    def test_project_or_other_home_copy_is_not_accepted(self):
        self.plugin.__file__ = "/project/.hermes/plugins/talon-operational-prompt/__init__.py"
        with patch.object(Path, "read_text") as read:
            self.plugin.register(self.ctx)
        read.assert_not_called()
        self.ctx.register_system_prompt_section.assert_not_called()

    def test_invalid_assets_fail_before_any_registration(self):
        for index, (_, _, budget) in enumerate(self.plugin.SECTIONS):
            for invalid in (FileNotFoundError(), UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid"),
                            " \n", "x" * (budget + 1)):
                with self.subTest(asset=index, invalid=type(invalid).__name__):
                    values = [invalid if i == index else "valid" for i in range(2)]
                    with patch.object(Path, "read_text", side_effect=values):
                        with self.assertRaises((FileNotFoundError, UnicodeDecodeError, ValueError)):
                            self.plugin.register(self.ctx)
                    self.ctx.register_system_prompt_section.assert_not_called()


if __name__ == "__main__":
    unittest.main()
