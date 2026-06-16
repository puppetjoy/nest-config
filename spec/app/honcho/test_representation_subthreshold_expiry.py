#!/usr/bin/env python3
"""Static checks for Honcho representation subthreshold expiry policy.

The runtime evidence that prompted this check was aggregate-only: old inactive
representation rows were below Honcho's representation batch threshold and were
not active work. The source-of-truth policy should prune those stale
subthreshold rows without lowering the representation quality gate or accepting
truncated/low-context generations.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
HONCHO_YAML = REPO_ROOT / "data/kubernetes/app/honcho.yaml"


def honcho_yaml_text() -> str:
    return HONCHO_YAML.read_text(encoding="utf-8")


def top_level_value(name: str) -> str:
    pattern = re.compile(rf"^{re.escape(name)}:\s*['\"]?([^'\"\n]+)['\"]?$", re.MULTILINE)
    match = pattern.search(honcho_yaml_text())
    if not match:
        raise AssertionError(f"missing top-level Honcho setting {name}")
    return match.group(1)


def test_representation_quality_gate_is_preserved() -> None:
    assert top_level_value("representation_batch_max_tokens") == "1024"


def test_subthreshold_tail_expires_before_freshness_window_gets_stale() -> None:
    assert top_level_value("representation_subthreshold_ttl") == "3 days"


def test_expiry_marks_rows_terminal_without_processing_or_hard_delete() -> None:
    text = honcho_yaml_text()

    assert "SET\n                          processed = true," in text
    assert "error = 'expired_subthreshold_representation'" in text
    assert "DELETE FROM queue" not in text
    assert "DERIVER_FLUSH_ENABLED" not in text


def test_expiry_job_reports_aggregate_tail_buckets_for_eval_triage() -> None:
    text = honcho_yaml_text()

    assert "aggregate-only age/token buckets for eval freshness triage" in text
    assert "rows_younger_than_1d" in text
    assert "rows_1d_to_3d" in text
    assert "rows_older_than_3d" in text
    assert "subthreshold_rows" in text
    assert "oldest_pending_age" in text


if __name__ == "__main__":
    test_representation_quality_gate_is_preserved()
    test_subthreshold_tail_expires_before_freshness_window_gets_stale()
    test_expiry_marks_rows_terminal_without_processing_or_hard_delete()
    test_expiry_job_reports_aggregate_tail_buckets_for_eval_triage()
