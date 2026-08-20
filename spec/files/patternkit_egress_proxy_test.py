#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


sys.dont_write_bytecode = True

REPO_ROOT = Path(__file__).resolve().parents[2]
PROXY_PATH = REPO_ROOT / "files/app/patternkit/egress_proxy.py"
SPEC = importlib.util.spec_from_file_location("patternkit_egress_proxy", PROXY_PATH)
assert SPEC and SPEC.loader
PROXY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROXY)


class DestinationAllowlistTest(unittest.TestCase):
    def test_allows_only_exact_expected_hosts_on_web_ports(self) -> None:
        self.assertEqual(PROXY._parse_authority("patternkit.eyrie:443", 443), ("patternkit.eyrie", 443))
        self.assertEqual(PROXY._parse_authority("gitlab.joyfullee.me", 443), ("gitlab.joyfullee.me", 443))
        self.assertEqual(PROXY._parse_authority("patternkit.eyrie:80", 80), ("patternkit.eyrie", 80))

    def test_rejects_shared_browser_suffixes_and_non_web_ports(self) -> None:
        self.assertIsNone(PROXY._parse_authority("browser.eyrie:443", 443))
        self.assertIsNone(PROXY._parse_authority("patternkit.eyrie.attacker.invalid:443", 443))
        self.assertIsNone(PROXY._parse_authority("patternkit.eyrie:6901", 443))
        self.assertIsNone(PROXY._parse_authority("patternkit.eyrie:invalid", 443))


if __name__ == "__main__":
    unittest.main()