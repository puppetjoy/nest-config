import argparse
import json

from nest_honcho.cli import (
    _native_context_has_recall,
    _native_peer_card_omission_reason,
    _native_safe_peer_label,
    register_cli,
)
from nest_honcho.evaluation import (
    SAFE_PROBE_INPUT_CONTRACT,
    build_content_safe_probe_evidence,
    guidance,
    load_ledger,
    record_run,
    render_report,
    score_evidence,
)


def test_honcho_eval_cli_parser_accepts_record_subcommand():
    parser = argparse.ArgumentParser(prog="hermes honcho")
    register_cli(parser)

    args = parser.parse_args([
        "eval",
        "--ledger",
        "/tmp/ledger.json",
        "record",
        "--input",
        "/tmp/evidence.json",
        "--baseline",
    ])

    assert args.honcho_command == "eval"
    assert args.eval_command == "record"
    assert args.ledger == "/tmp/ledger.json"
    assert args.input == "/tmp/evidence.json"
    assert args.baseline is True


def test_honcho_eval_cli_parser_accepts_probe_subcommand():
    parser = argparse.ArgumentParser(prog="hermes honcho")
    register_cli(parser)

    args = parser.parse_args([
        "eval",
        "probe",
        "--input",
        "/tmp/aggregate.json",
        "--record",
    ])

    assert args.honcho_command == "eval"
    assert args.eval_command == "probe"
    assert args.input == "/tmp/aggregate.json"
    assert args.record is True


def test_honcho_eval_cli_parser_accepts_native_probes_subcommand():
    parser = argparse.ArgumentParser(prog="hermes honcho")
    register_cli(parser)

    args = parser.parse_args([
        "eval",
        "native-probes",
        "--peer",
        "user",
        "--probe",
        "--record",
    ])

    assert args.honcho_command == "eval"
    assert args.eval_command == "native-probes"
    assert args.peer == ["user"]
    assert args.probe is True
    assert args.record is True


def test_native_probe_peer_labels_do_not_expose_custom_peer_names():
    assert _native_safe_peer_label("user", 0) == "user"
    assert _native_safe_peer_label("AI", 1) == "ai"
    assert _native_safe_peer_label("Joyful Lee", 2) == "custom_peer_2"
    assert "Joyful" not in _native_safe_peer_label("Joyful Lee", 2)


def test_native_probe_omits_empty_ai_card_when_context_has_recall():
    assert _native_context_has_recall({"representation": "present"}) is True
    assert _native_peer_card_omission_reason(
        "ai",
        {"representation": "present"},
    ) == "ai_peer_card_missing_context_available"

    evidence = build_content_safe_probe_evidence(
        {
            "aggregates": {
                "native_honcho_probe_attempts": 11,
                "native_honcho_probe_omission_count": 1,
                "native_honcho_probe_omitted_ai_peer_card_missing_context_available_count": 1,
                "native_honcho_probe_results": [
                    {
                        "query_label": "session_context:ai",
                        "category_label": "session_context",
                        "bucket_label": "session_context",
                        "recall_label": "useful",
                        "freshness_label": "fresh",
                        "noise_label": "clean",
                        "regression_label": "pass",
                    }
                ],
            }
        }
    )

    assert evidence["aggregates"]["native_honcho_probe_omission_count"] == 1
    assert evidence["aggregates"]["recall_attempts"] == 1
    assert evidence["aggregates"]["useful_recall_count"] == 1
    assert evidence["aggregates"].get("empty_recall_count") is None
    assert evidence.get("safe_probe_failures", []) == []
    assert "peer_card:ai" not in json.dumps(evidence)


def test_native_probe_keeps_empty_user_card_as_failure():
    assert _native_context_has_recall({"card": ["present"]}) is False
    assert _native_peer_card_omission_reason(
        "user",
        {"representation": "present"},
    ) is None


def test_score_evidence_normalizes_percent_and_penalties():
    result = score_evidence(
        {
            "probes": {
                "recall_usefulness": 90,
                "freshness": 0.8,
                "noise": 0.1,
                "regression": 0.0,
                "dream_success": 1.0,
                "representation_freshness": 0.75,
                "budget_efficiency": 0.5,
            }
        }
    )

    assert result.normalized["recall_usefulness"] == 0.9
    assert result.missing == []
    assert "budget_efficiency below target (0.50 < 0.70)" in result.warnings
    assert 0.8 < result.score < 1.0


def test_record_run_persists_baseline_and_deltas(tmp_path):
    ledger_path = tmp_path / "ledger.json"

    _, first = record_run(
        {
            "probes": {
                "recall_usefulness": 0.8,
                "freshness": 0.8,
                "noise": 0.2,
                "regression": 0.0,
                "dream_success": 0.8,
                "representation_freshness": 0.7,
                "budget_efficiency": 0.7,
            },
            "aggregates": {"pending_dream_rows": 0, "raw": {"skip": "nested"}},
        },
        path=ledger_path,
        note="initial safe aggregate",
    )
    _, second = record_run(
        {
            "probes": {
                "recall_usefulness": 0.6,
                "freshness": 0.7,
                "noise": 0.4,
                "regression": 0.2,
                "dream_success": 0.7,
                "representation_freshness": 0.6,
                "budget_efficiency": 0.6,
            }
        },
        path=ledger_path,
        note="Authorization: bearer *** should redact",
        intervention_id="ar-test",
    )

    ledger = load_ledger(ledger_path)
    assert ledger["baselines"][0]["source_run_id"] == first["id"]
    assert len(ledger["runs"]) == 2
    assert second["delta_from_previous"] < 0
    assert second["delta_from_baseline"] < 0
    assert ledger["runs"][0]["aggregates"] == {
        "pending_dream_rows": 0,
        "probe_runner": "honcho-eval-safe-probes-v1",
    }
    assert ledger["runs"][1]["note"] == "[redacted: unsafe note marker]"

    on_disk = json.loads(ledger_path.read_text())
    assert on_disk["safety"]["content_safe"] is True


def test_content_safe_input_contract_is_exposed_in_guidance():
    data = guidance()

    assert data["input_contract"] == SAFE_PROBE_INPUT_CONTRACT
    assert "native_honcho_probe_results" in data["input_contract"]["labeled_result_lists"]
    assert "raw messages" in data["input_contract"]["forbidden"]
    budget_contract = "\n".join(data["input_contract"]["budget_efficiency_safe_scalars"])
    assert "limiter_<window>_503_count" in budget_contract
    assert "limiter_<window>_total_tokens_count/p50/p95" in budget_contract
    assert "deriver_<window>_tool_loop_max_count" in budget_contract
    assert "observation_yield_marker_count" in budget_contract
    assert "budget_evidence_missing" in budget_contract

    recommendations = "\n".join(data["recommendations"])
    assert "do not induce/schedule dreams" in recommendations
    assert "dream_observation_mode_label=passive" in recommendations


def test_content_safe_probe_runner_scores_fixed_quality_probes_without_raw_content(tmp_path):
    ledger_path = tmp_path / "ledger.json"
    raw_secret = "Joy's exact private card text should never persist"
    evidence = build_content_safe_probe_evidence(
        {
            "note": raw_secret,
            "probes": {"dream_success": 0.9, "representation_freshness": 0.65, "budget_efficiency": 0.85},
            "aggregates": {
                "recall_attempts": 10,
                "useful_recall_count": 8,
                "recall_error_count": 1,
                "fact_count": 20,
                "recent_fact_count": 16,
                "stale_fact_count": 2,
                "max_age_hours": 24,
                "retrieved_item_count": 30,
                "irrelevant_item_count": 3,
                "duplicate_item_count": 2,
                "stale_retrieved_item_count": 1,
                "regression_checks_total": 5,
                "regression_checks_failed": 1,
                "probe_window_label": "hourly-light",
                "raw": raw_secret,
                "raw_message_count": 12,
                "peer_card_label": "JoyPrivateName",
                "unsafe_label": "Joy Private Name",
            },
        }
    )

    assert set(evidence["probe_labels"]) >= {"recall_usefulness", "freshness", "noise", "regression"}
    assert set(evidence["probes"]) >= {
        "recall_usefulness",
        "freshness",
        "noise",
        "regression",
        "dream_success",
        "representation_freshness",
        "budget_efficiency",
    }
    assert evidence["omissions"] == []
    assert evidence["aggregates"]["probe_window_label"] == "hourly-light"
    assert "raw" not in evidence["aggregates"]
    assert "raw_message_count" not in evidence["aggregates"]
    assert "peer_card_label" not in evidence["aggregates"]
    assert "unsafe_label" not in evidence["aggregates"]
    assert raw_secret not in json.dumps(evidence)
    assert "JoyPrivateName" not in json.dumps(evidence)

    _ledger, entry = record_run(evidence, path=ledger_path)
    persisted = json.dumps(load_ledger(ledger_path))
    assert raw_secret not in persisted
    assert "Joy Private Name" not in persisted
    assert "JoyPrivateName" not in persisted
    assert entry["missing_probes"] == []


def test_labeled_native_honcho_probe_results_score_quality_without_persisting_raw_rows(tmp_path):
    ledger_path = tmp_path / "ledger.json"
    private_excerpt = "Joy private recalled excerpt"
    evidence = build_content_safe_probe_evidence(
        {
            "aggregates": {
                "probe_window_label": "hourly-light",
                "native_honcho_probe_results": [
                    {
                        "query_label": "talon_identity",
                        "recall_label": "useful",
                        "freshness_label": "fresh",
                        "noise_label": "clean",
                        "regression_label": "pass",
                    },
                    {
                        "query_label": "stale_request_policy",
                        "recall_label": "irrelevant",
                        "freshness_label": "stale",
                        "noise_label": "stale",
                        "regression_label": "fail",
                    },
                    {
                        "query_label": "unsafe row has spaces",
                        "recall_label": "useful",
                    },
                    {
                        "query_label": "raw_content_row",
                        "recall_label": "useful",
                        "raw_content": private_excerpt,
                    },
                ],
            }
        }
    )

    assert set(evidence["probes"]) >= {"recall_usefulness", "freshness", "noise", "regression"}
    assert evidence["aggregates"]["fixed_probe_label_count"] == 2
    assert evidence["aggregates"]["recall_attempts"] == 2
    assert evidence["aggregates"]["useful_recall_count"] == 1
    assert evidence["aggregates"]["regression_checks_total"] == 2
    assert evidence["aggregates"]["regression_checks_failed"] == 1
    assert "native_honcho_probe_results" not in evidence["aggregates"]
    assert private_excerpt not in json.dumps(evidence)

    _ledger, entry = record_run(evidence, path=ledger_path, note="hourly_cron")
    persisted = json.dumps(load_ledger(ledger_path))
    assert private_excerpt not in persisted
    assert "native_honcho_probe_results" not in persisted
    assert not {"recall_usefulness", "freshness", "noise", "regression"} & set(entry["missing_probes"])


def test_safe_failure_details_distinguish_actionable_native_probe_buckets(tmp_path):
    ledger_path = tmp_path / "ledger.json"
    private_excerpt = "Joy private retrieved content must not persist"
    evidence = build_content_safe_probe_evidence(
        {
            "aggregates": {
                "native_honcho_probe_results": [
                    {
                        "query_label": "search:user:empty-memory-quality",
                        "category_label": "retrieval",
                        "recall_label": "empty",
                        "freshness_label": "fresh",
                        "noise_label": "empty",
                        "regression_label": "pass",
                    },
                    {
                        "query_label": "fact:agent-request-policy",
                        "category_label": "memory_fact",
                        "freshness_label": "stale",
                        "age_bucket_label": "older-than-7d",
                    },
                    {
                        "query_label": "peer_card:user",
                        "category_label": "peer_card",
                        "freshness_label": "stale",
                        "age_bucket_label": "older-than-7d",
                    },
                    {
                        "query_label": "session_context:ai",
                        "category_label": "session_context",
                        "freshness_label": "stale",
                        "age_bucket_label": "older-than-24h",
                    },
                    {
                        "query_label": "search:user:old-routing",
                        "category_label": "retrieval",
                        "recall_label": "stale",
                        "noise_label": "stale",
                    },
                    {
                        "query_label": "search:user:noisy-routing",
                        "category_label": "retrieval",
                        "recall_label": "irrelevant",
                        "noise_label": "noisy",
                    },
                    {
                        "query_label": "search:user:duplicate-routing",
                        "category_label": "retrieval",
                        "recall_label": "useful",
                        "noise_label": "duplicate",
                    },
                    {
                        "query_label": "regression:north-star:agent-requests",
                        "category_label": "regression",
                        "regression_label": "fail",
                    },
                    {
                        "query_label": "unsafe-row",
                        "recall_label": "empty",
                        "raw_content": private_excerpt,
                    },
                ],
            },
        }
    )

    reasons = {item["failure_reason_label"] for item in evidence["safe_probe_failures"]}
    assert reasons >= {
        "empty_recall",
        "stale_fact",
        "stale_card",
        "stale_context",
        "stale_retrieved_item",
        "irrelevant_retrieval",
        "noisy_retrieval",
        "duplicate_retrieval",
        "regression_check_failure",
    }
    assert evidence["aggregates"]["empty_recall_label_count"] >= 1
    assert evidence["aggregates"]["stale_fact_label_count"] == 1
    assert evidence["aggregates"]["stale_card_label_count"] == 1
    assert evidence["aggregates"]["stale_context_label_count"] == 1
    assert evidence["aggregates"]["stale_retrieved_item_label_count"] >= 1
    assert evidence["aggregates"]["irrelevant_retrieval_label_count"] >= 1
    assert evidence["aggregates"]["noisy_retrieval_label_count"] >= 1
    assert evidence["aggregates"]["duplicate_retrieval_label_count"] == 1
    assert evidence["aggregates"]["regression_check_failure_label_count"] == 1
    assert private_excerpt not in json.dumps(evidence)

    _ledger, entry = record_run(evidence, path=ledger_path, note="hourly_cron")
    assert entry["safe_probe_failures"] == evidence["safe_probe_failures"]
    persisted = json.dumps(load_ledger(ledger_path))
    assert private_excerpt not in persisted
    assert "raw_content" not in persisted


def test_report_surfaces_regression_warning_safe_failure_buckets_without_raw_content(tmp_path):
    ledger_path = tmp_path / "ledger.json"
    raw_private_text = "Joy private raw memory text must not appear"
    baseline_evidence = build_content_safe_probe_evidence(
        {
            "aggregates": {
                "recall_attempts": 12,
                "useful_recall_count": 12,
                "fact_count": 12,
                "recent_fact_count": 12,
                "retrieved_item_count": 12,
                "regression_checks_total": 12,
                "regression_checks_failed": 0,
            }
        }
    )
    record_run(baseline_evidence, path=ledger_path)
    current_evidence = build_content_safe_probe_evidence(
        {
            "aggregates": {
                "native_honcho_probe_results": [
                    {
                        "query_label": "regression:north-star:agent-requests",
                        "probe_label": "north-star",
                        "category_label": "regression",
                        "bucket_label": "agent-requests",
                        "age_bucket_label": "older-than-7d",
                        "regression_label": "fail",
                    },
                    {
                        "query_label": "unsafe-regression-row",
                        "regression_label": "fail",
                        "raw_content": raw_private_text,
                    },
                ],
                "recall_attempts": 12,
                "useful_recall_count": 11,
                "fact_count": 12,
                "recent_fact_count": 11,
                "retrieved_item_count": 24,
                "stale_retrieved_item_count": 1,
                "regression_checks_total": 12,
                "regression_checks_failed": 1,
            },
        }
    )
    ledger, entry = record_run(current_evidence, path=ledger_path, note="hourly_cron")
    report = render_report(guidance(ledger))

    warning_text = "\n".join(entry["warnings"])
    assert "regression above target" in warning_text
    assert "safe_failure_buckets:" in warning_text
    assert "query_label=regression:north-star:agent-requests" in warning_text
    assert "failure_reason_label=regression_check_failure" in warning_text
    assert raw_private_text not in warning_text
    assert "raw_content" not in warning_text
    assert "Safe failure buckets:" in report
    assert "query_label=regression:north-star:agent-requests" in report
    assert "probe_label=north-star" in report
    assert "category_label=regression" in report
    assert "bucket_label=agent-requests" in report
    assert "failure_reason_label=regression_check_failure" in report
    assert "age_bucket_label=older-than-7d" in report
    assert "regression_check_failure_label_count=1" in report
    assert raw_private_text not in report
    assert "raw_content" not in report


def test_content_safe_probe_preserves_input_safe_failure_details(tmp_path):
    ledger_path = tmp_path / "ledger.json"
    evidence = build_content_safe_probe_evidence(
        {
            "safe_probe_failures": [
                {
                    "query_label": "peer_card:ai",
                    "category_label": "peer_card",
                    "bucket_label": "peer_card",
                    "failure_reason_label": "empty_recall",
                },
                {
                    "query_label": "unsafe-extra-key",
                    "failure_reason_label": "empty_recall",
                    "raw_content": "private memory text",
                },
            ],
            "aggregates": {
                "recall_attempts": 12,
                "useful_recall_count": 11,
                "retrieved_item_count": 24,
                "regression_checks_total": 12,
                "regression_checks_failed": 1,
            },
        }
    )

    assert evidence["safe_probe_failures"] == [
        {
            "query_label": "peer_card:ai",
            "category_label": "peer_card",
            "bucket_label": "peer_card",
            "failure_reason_label": "empty_recall",
        }
    ]
    assert evidence["aggregates"]["empty_recall_label_count"] == 1
    assert "private memory text" not in json.dumps(evidence)

    _ledger, entry = record_run(evidence, path=ledger_path, note="hourly_cron")
    assert entry["safe_probe_failures"] == evidence["safe_probe_failures"]
    assert entry["aggregates"]["empty_recall_label_count"] == 1
    assert "private memory text" not in json.dumps(load_ledger(ledger_path))


def test_content_safe_probe_runner_omits_when_evidence_is_insufficient(tmp_path):
    ledger_path = tmp_path / "ledger.json"
    evidence = build_content_safe_probe_evidence({"aggregates": {"probe_window_label": "hourly-light"}})

    assert evidence["probes"] == {}
    assert {item["id"] for item in evidence["omissions"]} >= {
        "recall_usefulness",
        "freshness",
        "noise",
        "regression",
    }

    _ledger, entry = record_run(evidence, path=ledger_path)
    assert set(entry["missing_probes"]) >= {
        "recall_usefulness",
        "freshness",
        "noise",
        "regression",
    }
    assert entry["omitted_probe_details"] == evidence["omissions"]


def test_hourly_aggregate_operational_probes_score_without_quality_counts(tmp_path):
    ledger_path = tmp_path / "ledger.json"
    evidence = build_content_safe_probe_evidence(
        {
            "aggregates": {
                "honcho_health_ok": True,
                "cnpg_query_ok": True,
                "k8s_rollouts_ok": True,
                "hermes_honcho_status_rc": 0,
                "card_context_readable": True,
                "dream_schedule_http_status": 204,
                "dream_processed": True,
                "queue_error_2h": 0,
                "pending_dream_rows": 0,
                "pending_representation_rows": 3008,
                "deriver_15m_dream_start_markers": 4,
                "dream_completion_markers": 2,
                "observation_yield_markers": 1,
                "finish_length": 2,
                "incomplete": 1,
                "tracebacks": 0,
                "limiter_15m_503": 0,
                "limiter_90m_503": 0,
                "limiter_15m_400": 0,
                "limiter_90m_400": 0,
                "limiter_15m_timeout": 0,
                "limiter_90m_timeout": 0,
                "limiter_15m_prompt_tokens_p95": 3977,
                "limiter_15m_completion_tokens_p95": 1024,
                "limiter_90m_finish_length": 3,
            }
        }
    )

    assert set(evidence["probes"]) >= {"dream_success", "representation_freshness", "budget_efficiency"}
    assert {item["id"] for item in evidence["omissions"]} >= {
        "recall_usefulness",
        "freshness",
        "noise",
        "regression",
    }
    assert not any(
        item["id"] in {"dream_success", "representation_freshness", "budget_efficiency"}
        for item in evidence["omissions"]
    )
    scored = score_evidence(evidence)
    assert scored.score > 0
    assert set(scored.missing) >= {"recall_usefulness", "freshness", "noise", "regression"}
    assert not {"dream_success", "representation_freshness", "budget_efficiency"} & set(scored.missing)

    _ledger, entry = record_run(evidence, path=ledger_path, note="hourly_cron")
    assert entry["score"] > 0
    assert entry["probes"]["dream_success"] > 0
    assert entry["probes"]["budget_efficiency"] > 0
    assert "pending_representation_rows" in entry["aggregates"]


def test_passive_hourly_observation_scores_no_active_dream_as_healthy(tmp_path):
    ledger_path = tmp_path / "ledger.json"
    evidence = build_content_safe_probe_evidence(
        {
            "aggregates": {
                "honcho_health_ok": True,
                "cnpg_query_ok": True,
                "k8s_rollouts_ok": True,
                "hermes_honcho_status_rc": 0,
                "dream_observation_mode_label": "passive",
                "dream_schedule_attempted": 0,
                "queue_error_2h": 0,
                "pending_dream_rows": 0,
                "active_dream_count": 0,
                "pending_representation_rows": 100,
                "deriver_2h_traceback_count": 0,
                "deriver_2h_incomplete_count": 0,
                "limiter_2h_503_count": 0,
                "limiter_2h_400_count": 0,
                "limiter_2h_timeout_count": 0,
                "limiter_2h_finish_length_count": 0,
                "deriver_2h_finish_length_count": 0,
                "limiter_2h_prompt_tokens_p95": 1000,
                "limiter_2h_completion_tokens_p95": 500,
            }
        }
    )

    assert evidence["aggregates"]["dream_state_label"] == "passive_no_active_dream"
    assert evidence["aggregates"]["dream_schedule_attempted"] == 0
    assert evidence["probes"]["dream_success"] == 1.0
    assert {"id": "dream_success", "reason": "insufficient_dream_operational_counts"} not in evidence["omissions"]

    _ledger, entry = record_run(evidence, path=ledger_path, note="passive_hourly_cron")
    assert entry["probes"]["dream_success"] == 1.0
    assert entry["aggregates"]["dream_observation_mode_label"] == "passive"
    assert entry["aggregates"]["dream_state_label"] == "passive_no_active_dream"


def test_content_safe_input_contract_documents_passive_dream_observation():
    budget_contract = "\n".join(SAFE_PROBE_INPUT_CONTRACT["budget_efficiency_safe_scalars"])

    assert "dream_observation_mode_label=passive" in budget_contract
    assert "dream_schedule_attempted=0" in budget_contract
    assert "no active/pending dream is healthy evidence" in budget_contract


def test_hourly_aggregate_missing_queue_evidence_does_not_score_default_zeros(tmp_path):
    ledger_path = tmp_path / "ledger.json"
    evidence = build_content_safe_probe_evidence(
        {
            "aggregates": {
                "honcho_health_ok": True,
                "k8s_rollouts_ok": True,
                "hermes_honcho_status_rc": 0,
                "card_context_readable": True,
                "dream_schedule_http_status": 204,
                "dream_processed": True,
                # These are the dangerous fallback-zero queue values that can
                # appear after a failed CNPG collection.  Without an explicit
                # queue/CNPG success marker they must not become perfect health.
                "queue_error_2h": 0,
                "pending_dream_rows": 0,
                "pending_representation_rows": 0,
                "tracebacks": 0,
                "incomplete": 0,
                "limiter_15m_503": 0,
                "limiter_90m_503": 0,
                "finish_length": 0,
            }
        }
    )

    assert evidence["aggregates"]["queue_evidence_missing"] is True
    assert evidence["aggregates"]["queue_evidence_state_label"] == "missing_or_failed"
    assert not {"dream_success", "representation_freshness", "budget_efficiency"} & set(evidence["probes"])
    assert {
        (item["id"], item["reason"])
        for item in evidence["omissions"]
    } >= {
        ("dream_success", "queue_evidence_missing"),
        ("representation_freshness", "queue_evidence_missing"),
        ("budget_efficiency", "queue_evidence_missing"),
    }

    _ledger, entry = record_run(evidence, path=ledger_path, note="hourly_cron")
    assert entry["score"] < 0.95
    assert {"dream_success", "representation_freshness", "budget_efficiency"} <= set(entry["missing_probes"])


def test_hourly_aggregate_failed_cnpg_marker_omits_queue_dependent_probes():
    evidence = build_content_safe_probe_evidence(
        {
            "aggregates": {
                "honcho_health_ok": True,
                "cnpg_query_ok": False,
                "k8s_rollouts_ok": True,
                "hermes_honcho_status_rc": 0,
                "card_context_readable": True,
                "dream_schedule_http_status": 204,
                "dream_processed": True,
                "queue_error_2h": 0,
                "pending_dream_rows": 0,
                "pending_representation_rows": 0,
                "tracebacks": 0,
                "incomplete": 0,
                "limiter_15m_503": 0,
                "finish_length": 0,
            },
            "probes": {
                "dream_success": 1.0,
                "representation_freshness": 1.0,
                "budget_efficiency": 1.0,
            },
        }
    )

    assert evidence["aggregates"]["cnpg_query_ok"] is False
    assert evidence["aggregates"]["queue_evidence_missing"] is True
    assert "dream_success" not in evidence["probes"]
    assert "representation_freshness" not in evidence["probes"]
    assert "budget_efficiency" not in evidence["probes"]


def test_probe_input_contract_documents_current_queue_schema():
    guidance = "\n".join(SAFE_PROBE_INPUT_CONTRACT["operational_evidence_required"])

    assert "active_queue_sessions.last_updated" in guidance
    assert "queue.processed" in guidance
    assert "started_at/processed_at" in guidance


def test_hourly_aggregate_flattened_two_hour_aliases_score_budget_efficiency(tmp_path):
    ledger_path = tmp_path / "ledger.json"
    evidence = build_content_safe_probe_evidence(
        {
            "aggregates": {
                "health_ok": 1,
                "cnpg_query_ok": 1,
                "k8s_rollouts_ok": 1,
                "honcho_status_rc": 0,
                "native_card_context_readable": 1,
                "scheduled_joy_talon_dream_http": 204,
                "queue_error_2h": 0,
                "pending_dream_rows": 0,
                "pending_representation_rows": 3014,
                "deriver_2h_dream_start_markers": 3,
                "deriver_2h_completion_with_errors_count": 0,
                "deriver_2h_finish_length_count": 7,
                "deriver_2h_incomplete_count": 4,
                "deriver_2h_traceback_count": 4,
                "limiter_2h_503_count": 0,
                "limiter_2h_400_count": 0,
                "limiter_2h_timeout_count": 0,
                "limiter_2h_prompt_tokens_p95": 4250,
                "limiter_2h_completion_tokens_p95": 768,
                "limiter_2h_finish_length_count": 3,
            }
        }
    )

    assert set(evidence["probes"]) >= {"dream_success", "representation_freshness", "budget_efficiency"}
    assert not any(item["id"] == "budget_efficiency" for item in evidence["omissions"])
    scored = score_evidence(evidence)
    assert "budget_efficiency" not in scored.missing

    _ledger, entry = record_run(evidence, path=ledger_path, note="hourly_cron_flattened")
    assert entry["probes"]["budget_efficiency"] > 0
    assert "limiter_2h_prompt_tokens_p95" in entry["aggregates"]


def test_hourly_aggregate_flattened_45m_budget_inputs_score_budget_efficiency(tmp_path):
    ledger_path = tmp_path / "ledger.json"
    evidence = build_content_safe_probe_evidence(
        {
            "aggregates": {
                "native_honcho_probe_attempts": 12,
                "useful_recall_count": 11,
                "recall_attempts": 12,
                "fact_count": 12,
                "recent_fact_count": 11,
                "retrieved_item_count": 24,
                "regression_checks_total": 4,
                "regression_checks_failed": 0,
                "limiter_45m_503_count": 0,
                "limiter_45m_400_count": 0,
                "limiter_45m_timeout_count": 0,
                "limiter_45m_finish_length_count": 0,
                "limiter_45m_prompt_tokens_count": 8,
                "limiter_45m_prompt_tokens_p50": 3713,
                "limiter_45m_prompt_tokens_p95": 4789,
                "limiter_45m_completion_tokens_count": 8,
                "limiter_45m_completion_tokens_p50": 37,
                "limiter_45m_completion_tokens_p95": 896,
                "limiter_45m_total_tokens_count": 8,
                "limiter_45m_total_tokens_p50": 4163,
                "limiter_45m_total_tokens_p95": 5128,
                "dream_success": 1.0,
                "observation_yield_marker_count": 9,
                "no_observation_marker_count": 0,
                "deriver_45m_finish_length_count": 0,
                "deriver_45m_incomplete_llm_output_count": 0,
                "deriver_45m_tool_loop_max_count": 4,
            }
        }
    )

    assert "budget_efficiency" in evidence["probes"]
    assert not any(item["id"] == "budget_efficiency" for item in evidence["omissions"])
    assert 0 < evidence["probes"]["budget_efficiency"] < 1

    _ledger, entry = record_run(evidence, path=ledger_path, note="hourly_cron_45m")
    assert "budget_efficiency" not in entry["missing_probes"]
    assert "limiter_45m_total_tokens_p95" in entry["aggregates"]
    assert "prompt" not in entry["aggregates"]


def test_budget_efficiency_explicit_missing_evidence_is_omitted(tmp_path):
    ledger_path = tmp_path / "ledger.json"
    evidence = build_content_safe_probe_evidence(
        {
            "aggregates": {
                "budget_evidence_missing": True,
                "limiter_45m_503_count": 0,
                "limiter_45m_400_count": 0,
                "limiter_45m_timeout_count": 0,
                "limiter_45m_total_tokens_p95": 5128,
                "prompt": "raw prompt content must be dropped",
            }
        }
    )

    assert "budget_efficiency" not in evidence["probes"]
    assert {"id": "budget_efficiency", "reason": "budget_evidence_missing"} in evidence["omissions"]
    assert "prompt" not in evidence["aggregates"]

    _ledger, entry = record_run(evidence, path=ledger_path, note="missing_budget")
    assert "budget_efficiency" in entry["missing_probes"]
    assert "prompt" not in entry["aggregates"]


def test_active_dream_probe_records_in_progress_note_instead_of_degraded_score(tmp_path):
    ledger_path = tmp_path / "ledger.json"
    evidence = build_content_safe_probe_evidence(
        {
            "aggregates": {
                "honcho_health_ok": True,
                "cnpg_query_ok": True,
                "k8s_rollouts_ok": True,
                "honcho_status_rc": 0,
                "dream_schedule_http_status": 204,
                "pending_dream_rows": 1,
                "active_dream_count": 1,
                "deriver_2h_dream_start_markers": 1,
                "dream_completion_markers": 0,
                "tracebacks": 0,
                "incomplete": 0,
                "recall_attempts": 2,
                "useful_recall_count": 2,
                "fact_count": 2,
                "recent_fact_count": 2,
                "retrieved_item_count": 2,
                "irrelevant_item_count": 0,
                "duplicate_item_count": 0,
                "stale_retrieved_item_count": 0,
                "regression_checks_total": 2,
                "regression_checks_failed": 0,
            }
        }
    )

    assert "dream_success" not in evidence["probes"]
    assert {"id": "dream_success", "reason": "dream_active_in_progress"} in evidence["omissions"]
    assert evidence["aggregates"]["dream_in_progress"] is True
    assert evidence["aggregates"]["dream_state_label"] == "active_in_progress"
    assert "dream_active_in_progress" in evidence["note"]
    assert {"recall_usefulness", "freshness", "noise", "regression"} <= set(evidence["probes"])

    _ledger, entry = record_run(evidence, path=ledger_path)
    assert "dream_success" in entry["missing_probes"]
    assert entry["omitted_probe_details"] == evidence["omissions"]
    assert entry["note"] == "content-safe hourly quality probe run; dream_active_in_progress"


def test_guidance_and_report_call_out_regression(tmp_path):
    ledger_path = tmp_path / "ledger.json"
    record_run(
        {"probes": {"recall_usefulness": 0.9, "freshness": 0.9, "noise": 0, "regression": 0}},
        path=ledger_path,
    )
    ledger, _ = record_run(
        {"probes": {"recall_usefulness": 0.4, "freshness": 0.4, "noise": 0.7, "regression": 0.5}},
        path=ledger_path,
    )

    data = guidance(ledger)
    report = render_report(data)

    assert "regressed more than 0.05 below baseline" in "\n".join(data["recommendations"])
    assert "Δ previous:" in report
    assert "Warnings:" in report


def test_report_distinguishes_scored_operational_probes_from_missing_quality_probes(tmp_path):
    ledger_path = tmp_path / "ledger.json"
    ledger, _ = record_run(
        {
            "probes": {
                "dream_success": 0.9,
                "representation_freshness": 0.7,
                "budget_efficiency": 0.8,
            },
            "omissions": [
                {"id": "recall_usefulness", "reason": "insufficient_recall_counts"},
                {"id": "freshness", "reason": "insufficient_age_or_freshness_counts"},
            ],
        },
        path=ledger_path,
    )
    report = render_report(guidance(ledger))

    assert "scored probes remain valid operational evidence" in report
    assert "evaluate scored probes separately" in report
