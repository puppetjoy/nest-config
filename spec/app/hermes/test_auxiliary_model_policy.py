#!/usr/bin/env python3
"""Static public-contract checks for managed Hermes auxiliary models."""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
APP_MANIFEST = REPO_ROOT / "manifests/app/hermes.pp"
CONFIG_MANIFEST = REPO_ROOT / "manifests/app/hermes/config.pp"
LIB_MANIFEST = REPO_ROOT / "manifests/lib/hermes.pp"
OWL_DATA = REPO_ROOT / "data/host/owl.yaml"

EXPECTED_PROVIDER = "openai-codex"
EXPECTED_COMPRESSION_MODEL = "gpt-5.6-terra"
EXPECTED_WEB_EXTRACT_MODEL = "gpt-5.6-terra"
EXPECTED_TITLE_MODEL = "gpt-5.6-luna"
EXPECTED_DELEGATION_MODEL = "gpt-5.6-terra"
EXPECTED_LOCAL_PROVIDER = "custom:llama-qwen"
EXPECTED_LOCAL_MODEL = "qwen-3.6"


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_owl_tracks_merged_hermes_and_shared_auxiliary_policy() -> None:
    host_config = load_yaml(OWL_DATA)

    assert host_config["nest::app::hermes::git_ref"] == "nest"
    assert "nest::app::hermes::git_commit" not in host_config
    assert host_config["nest::app::hermes::auxiliary_provider"] == EXPECTED_PROVIDER
    assert host_config["nest::app::hermes::auxiliary_compress_model"] == EXPECTED_COMPRESSION_MODEL
    assert host_config["nest::app::hermes::auxiliary_extract_model"] == EXPECTED_WEB_EXTRACT_MODEL
    assert host_config["nest::app::hermes::auxiliary_title_model"] == EXPECTED_TITLE_MODEL
    assert host_config["nest::app::hermes::delegation_provider"] == EXPECTED_PROVIDER
    assert host_config["nest::app::hermes::delegation_model"] == EXPECTED_DELEGATION_MODEL


def test_codex_instances_inherit_shared_auxiliary_policy_without_legacy_override() -> None:
    instances = load_yaml(OWL_DATA)["nest::app::hermes::instances"]

    for profile in ("talon", "star"):
        instance = instances[profile]
        assert "auxiliary_mini_model" not in instance
        assert "auxiliary_provider" not in instance


def test_beryl_keeps_every_model_route_local() -> None:
    beryl = load_yaml(OWL_DATA)["nest::app::hermes::instances"]["beryl"]
    expected_routes = {
        "model_provider": EXPECTED_LOCAL_PROVIDER,
        "model_name": EXPECTED_LOCAL_MODEL,
        "auxiliary_provider": EXPECTED_LOCAL_PROVIDER,
        "auxiliary_compress_model": EXPECTED_LOCAL_MODEL,
        "auxiliary_extract_model": EXPECTED_LOCAL_MODEL,
        "auxiliary_title_model": EXPECTED_LOCAL_MODEL,
        "delegation_provider": EXPECTED_LOCAL_PROVIDER,
        "delegation_model": EXPECTED_LOCAL_MODEL,
    }

    assert {key: beryl[key] for key in expected_routes} == expected_routes
    assert all("gpt" not in value.lower() and "openai" not in value.lower() for value in expected_routes.values())


def test_split_auxiliary_interface_is_wired_to_each_managed_task() -> None:
    app_text = APP_MANIFEST.read_text(encoding="utf-8")
    config_text = CONFIG_MANIFEST.read_text(encoding="utf-8")
    lib_text = LIB_MANIFEST.read_text(encoding="utf-8")

    for parameter in (
        "auxiliary_compress_model",
        "auxiliary_extract_model",
        "auxiliary_title_model",
        "delegation_provider",
        "delegation_model",
    ):
        assert f"${parameter}" in app_text
        assert f"$nest::app::hermes::{parameter}" in config_text
        assert f"${parameter}" in lib_text

    assert "'model'    => $auxiliary_compress_model" in lib_text
    assert "'model'    => $auxiliary_extract_model" in lib_text
    assert "'model'    => $auxiliary_title_model" in lib_text
    assert "'provider' => $delegation_provider" in lib_text
    assert "'model'    => $delegation_model" in lib_text
    assert "auxiliary_mini_model" not in app_text
    assert "auxiliary_mini_model" not in config_text
    assert "auxiliary_mini_model" not in lib_text


if __name__ == "__main__":
    test_owl_tracks_merged_hermes_and_shared_auxiliary_policy()
    test_codex_instances_inherit_shared_auxiliary_policy_without_legacy_override()
    test_beryl_keeps_every_model_route_local()
    test_split_auxiliary_interface_is_wired_to_each_managed_task()