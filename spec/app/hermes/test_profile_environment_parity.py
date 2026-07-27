#!/usr/bin/env python3
"""Static checks for Hermes profile environment parity."""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
HERMES_LIB = REPO_ROOT / "manifests/lib/hermes.pp"
OWL_DATA = REPO_ROOT / "data/host/owl.yaml"

STAR_SECURE_BROWSER_ENV = {
    "SECURE_BROWSER_TARGET": "browser.eyrie-firefox",
    "SECURE_BROWSER_WORKLOAD": "deployment/firefox",
    "SECURE_BROWSER_EXPECTED_WORKLOAD": "deployment/firefox",
    "SECURE_BROWSER_EXPECTED_IMAGE_RE": "nest/tools/firefox",
    "SECURE_BROWSER_EXPECTED_APP_LABEL": "firefox",
    "SECURE_BROWSER_PUBLIC_URL": "https://browser.eyrie/",
    "SECURE_BROWSER_OPERATOR_URL": "https://browser.eyrie",
    "SECURE_BROWSER_CDP_URL": "https://browser-cdp.eyrie",
}


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_profile_dotenv_includes_instance_environment_lines() -> None:
    lib_text = HERMES_LIB.read_text(encoding="utf-8")

    env_content_line = next(line for line in lib_text.splitlines() if "$env_content =" in line)
    assert "$extra_env_lines" in env_content_line
    assert env_content_line.index("$extra_env_lines") > env_content_line.index("$kubeconfig_env_lines")
    assert env_content_line.index("$extra_env_lines") < env_content_line.index("$tls_trust_env_lines")


def test_star_profile_declares_secure_browser_service_endpoint_environment() -> None:
    host_config = load_yaml(OWL_DATA)
    star = host_config["nest::app::hermes::instances"]["star"]
    environment = star["environment"]

    for key, value in STAR_SECURE_BROWSER_ENV.items():
        assert environment[key] == value


if __name__ == "__main__":
    test_profile_dotenv_includes_instance_environment_lines()
    test_star_profile_declares_secure_browser_service_endpoint_environment()
