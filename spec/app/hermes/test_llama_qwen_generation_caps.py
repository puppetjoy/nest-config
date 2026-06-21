#!/usr/bin/env python3
"""Static checks for local Qwen runaway-generation caps."""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
LLAMA_APP = REPO_ROOT / "data/kubernetes/app/llama-server.yaml"
LLAMA_SERVICE = REPO_ROOT / "data/kubernetes/service/llama-qwen.yaml"
OWL_DATA = REPO_ROOT / "data/host/owl.yaml"
HERMES_LIB = REPO_ROOT / "manifests/lib/hermes.pp"
HERMES_CONFIG = REPO_ROOT / "manifests/app/hermes/config.pp"

EXPECTED_BERYL_MODEL_MAX_TOKENS = 4096
EXPECTED_REASONING_BUDGET = "2048"
EXPECTED_LLAMA_QWEN_MODEL_REPO = "unsloth/Qwen3.6-35B-A3B-MTP-GGUF"
EXPECTED_LLAMA_QWEN_MODEL_FILE = "Qwen3.6-35B-A3B-MTP-UD-Q8_K_XL.gguf"
EXPECTED_LLAMA_QWEN_MODEL_PATH = "/cache/models/Qwen3.6-35B-A3B-MTP-UD-Q8_K_XL.gguf"
EXPECTED_LLAMA_QWEN_SPEC_TYPE = "draft-mtp"
EXPECTED_LLAMA_QWEN_SPEC_DRAFT_N_MAX = "2"
EXPECTED_LLAMA_QWEN_BACKEND = "vulkan"


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_llama_qwen_server_args_include_bounded_reasoning_budget() -> None:
    app_text = LLAMA_APP.read_text(encoding="utf-8")
    service_config = load_yaml(LLAMA_SERVICE)

    assert service_config["reasoning_budget"] == EXPECTED_REASONING_BUDGET
    assert int(service_config["reasoning_budget"]) < 10537
    assert "--reasoning-budget" in app_text
    assert '"%{lookup(\'reasoning_budget\')}"' in app_text


def test_llama_qwen_uses_mtp_ud_q8_k_xl_with_mmproj_and_four_slots() -> None:
    app_text = LLAMA_APP.read_text(encoding="utf-8")
    service_config = load_yaml(LLAMA_SERVICE)

    assert service_config["model_repo"] == EXPECTED_LLAMA_QWEN_MODEL_REPO
    assert service_config["model_file"] == EXPECTED_LLAMA_QWEN_MODEL_FILE
    assert service_config["model_path"] == EXPECTED_LLAMA_QWEN_MODEL_PATH
    assert service_config["mmproj_path"] == "/cache/models/Qwen3.6-35B-A3B-mmproj-F16.gguf"
    assert service_config["parallel_requests"] == "4"
    assert int(service_config["ctx_size"]) // int(service_config["parallel_requests"]) == 262144
    assert service_config["spec_type"] == EXPECTED_LLAMA_QWEN_SPEC_TYPE
    assert service_config["spec_draft_n_max"] == EXPECTED_LLAMA_QWEN_SPEC_DRAFT_N_MAX
    assert "--mmproj" in app_text
    assert "--spec-type" in app_text
    assert '"%{lookup(\'spec_type\')}"' in app_text
    assert "--spec-draft-n-max" in app_text
    assert '"%{lookup(\'spec_draft_n_max\')}"' in app_text


def test_llama_qwen_backend_selection_defaults_to_vulkan_with_observability() -> None:
    app = load_yaml(LLAMA_APP)
    service_config = load_yaml(LLAMA_SERVICE)
    app_text = LLAMA_APP.read_text(encoding="utf-8")
    pod_template = app["resources"]["deployment"]["spec"]["template"]
    container = pod_template["spec"]["containers"][0]

    assert app["llama_cpp_backend"] == EXPECTED_LLAMA_QWEN_BACKEND
    assert service_config["llama_cpp_backend"] == EXPECTED_LLAMA_QWEN_BACKEND
    assert pod_template["metadata"]["labels"]["llama.cpp/backend"] == "%{lookup('llama_cpp_backend')}"
    assert pod_template["metadata"]["annotations"]["llama.cpp/backend"] == "%{lookup('llama_cpp_backend')}"
    assert container["imagePullPolicy"] == "Always"
    assert "llama-server-${backend}" in app_text
    assert "unsupported llama.cpp backend" in app_text
    env = {entry["name"]: entry["value"] for entry in container["env"]}
    assert env["LLAMA_CPP_BACKEND"] == "%{lookup('llama_cpp_backend')}"
    assert env["LLAMA_CPP_IMAGE"] == "%{lookup('image')}"


def test_beryl_local_qwen_model_has_output_cap() -> None:
    host_config = load_yaml(OWL_DATA)
    beryl = host_config["nest::app::hermes::instances"]["beryl"]

    assert beryl["model_provider"] == "custom:llama-qwen"
    assert beryl["model_name"] == "qwen-3.6"
    assert beryl["model_max_tokens"] == EXPECTED_BERYL_MODEL_MAX_TOKENS


def test_puppet_renders_model_max_tokens_into_managed_config() -> None:
    lib_text = HERMES_LIB.read_text(encoding="utf-8")
    config_text = HERMES_CONFIG.read_text(encoding="utf-8")

    assert "Optional[Integer[1]] $model_max_tokens" in lib_text
    assert "'max_tokens' => $model_max_tokens" in lib_text
    assert "} + $model_max_tokens_config" in lib_text
    assert "$instance_model_max_tokens  = $config['model_max_tokens']" in config_text
    assert "model_max_tokens           => $instance_model_max_tokens" in config_text


if __name__ == "__main__":
    test_llama_qwen_server_args_include_bounded_reasoning_budget()
    test_llama_qwen_uses_mtp_ud_q8_k_xl_with_mmproj_and_four_slots()
    test_llama_qwen_backend_selection_defaults_to_vulkan_with_observability()
    test_beryl_local_qwen_model_has_output_cap()
    test_puppet_renders_model_max_tokens_into_managed_config()
