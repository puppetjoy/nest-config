#!/usr/bin/env python3
"""Static checks for Honcho local-Qwen thinking experiment wiring.

Kubernetes env values are strings, but the maintained Honcho fork normalizes
chat_template_kwargs.enable_thinking at the OpenAI-compatible request boundary.
These checks keep the Nest config staged to only the intended paths and verify
that the values are boolean-shaped before they are serialized into JSON.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
HONCHO_YAML = REPO_ROOT / "data/kubernetes/app/honcho.yaml"

ENABLE_THINKING_EXPECTATIONS = {
    "DERIVER_MODEL_CONFIG__OVERRIDES__PROVIDER_PARAMS__CHAT_TEMPLATE_KWARGS__ENABLE_THINKING": False,
    "SUMMARY_MODEL_CONFIG__OVERRIDES__PROVIDER_PARAMS__CHAT_TEMPLATE_KWARGS__ENABLE_THINKING": False,
    "DIALECTIC_LEVELS__minimal__MODEL_CONFIG__OVERRIDES__PROVIDER_PARAMS__CHAT_TEMPLATE_KWARGS__ENABLE_THINKING": False,
    "DIALECTIC_LEVELS__low__MODEL_CONFIG__OVERRIDES__PROVIDER_PARAMS__CHAT_TEMPLATE_KWARGS__ENABLE_THINKING": False,
    "DIALECTIC_LEVELS__medium__MODEL_CONFIG__OVERRIDES__PROVIDER_PARAMS__CHAT_TEMPLATE_KWARGS__ENABLE_THINKING": False,
    "DIALECTIC_LEVELS__high__MODEL_CONFIG__OVERRIDES__PROVIDER_PARAMS__CHAT_TEMPLATE_KWARGS__ENABLE_THINKING": False,
    "DIALECTIC_LEVELS__max__MODEL_CONFIG__OVERRIDES__PROVIDER_PARAMS__CHAT_TEMPLATE_KWARGS__ENABLE_THINKING": False,
    "DREAM_DEDUCTION_MODEL_CONFIG__OVERRIDES__PROVIDER_PARAMS__CHAT_TEMPLATE_KWARGS__ENABLE_THINKING": True,
    "DREAM_INDUCTION_MODEL_CONFIG__OVERRIDES__PROVIDER_PARAMS__CHAT_TEMPLATE_KWARGS__ENABLE_THINKING": True,
}


def env_entries() -> dict[str, str]:
    entries: dict[str, str] = {}
    current_name: str | None = None
    for raw_line in HONCHO_YAML.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("- name: "):
            current_name = line.removeprefix("- name: ").strip('"\'')
        elif current_name and line.startswith("value: "):
            entries[current_name] = line.removeprefix("value: ").strip('"\'')
            current_name = None
    return entries


def coerce_enable_thinking(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    raise AssertionError(f"enable_thinking value must be true/false, got {value!r}")


def test_qwen_thinking_only_enabled_for_dream_synthesis_paths() -> None:
    entries = env_entries()
    enable_thinking_entries = {
        name: coerce_enable_thinking(value)
        for name, value in entries.items()
        if name.endswith("PROVIDER_PARAMS__CHAT_TEMPLATE_KWARGS__ENABLE_THINKING")
    }

    assert enable_thinking_entries == ENABLE_THINKING_EXPECTATIONS


def test_intervention_metadata_is_available_to_eval_tooling() -> None:
    entries = env_entries()

    assert entries["HONCHO_THINKING_INTERVENTION_ID"] == "qwen-thinking-dream-synthesis-v1"
    assert entries["HONCHO_THINKING_INTERVENTION_PATHS"] == "dream_deduction,dream_induction"
    assert "recall/relevance" in entries["HONCHO_THINKING_INTERVENTION_EVAL_NOTE"]
    assert "limiter" in entries["HONCHO_THINKING_INTERVENTION_EVAL_NOTE"]


def test_enable_thinking_values_serialize_as_json_booleans() -> None:
    entries = env_entries()

    for name, expected in ENABLE_THINKING_EXPECTATIONS.items():
        extra_body = {
            "chat_template_kwargs": {
                "enable_thinking": coerce_enable_thinking(entries[name]),
            },
        }
        round_tripped = json.loads(json.dumps(extra_body))

        value = round_tripped["chat_template_kwargs"]["enable_thinking"]
        assert value is expected
        assert not isinstance(value, str)


if __name__ == "__main__":
    test_qwen_thinking_only_enabled_for_dream_synthesis_paths()
    test_intervention_metadata_is_available_to_eval_tooling()
    test_enable_thinking_values_serialize_as_json_booleans()
