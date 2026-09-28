import pytest

from app.core.research_trace_adapter import (
    MASK,
    MAX_TRACE_EVIDENCE_PER_ITERATION,
    MAX_TRACE_ITERATIONS,
    mask_secrets,
    normalize_rd_agent_trace,
)


def test_normalize_rd_agent_trace_maps_loop_iterations_feedback_and_source_marker():
    normalized = normalize_rd_agent_trace(
        {
            "trace_id": "RD_RUN_001",
            "loop": {
                "title": "Factor RD loop",
                "objective": "Improve defensive timing with volume-price divergence.",
                "tags": ["factor", "timing"],
            },
            "iterations": [
                {
                    "id": "iter-a",
                    "hypothesis": "Volume divergence reduces false breakouts.",
                    "plan": ["Build divergence feature", "Backtest against baseline"],
                    "action_target": "factor",
                    "target_modules": ["factor_engine", "signalops"],
                    "metrics": {"ic": 0.13, "max_drawdown_delta": -0.04},
                    "evidence": [
                        {
                            "id": "artifact-1",
                            "label": "Backtest summary",
                            "quality": "high",
                        }
                    ],
                    "feedback": {"verdict": "accept", "note": "Stable improvement."},
                },
                {
                    "id": "iter-b",
                    "proposal": "Add liquidity guard for low turnover names.",
                    "experiment_plan": "Run segmented backtest by turnover bucket.",
                    "modules": "signalops, risk_firewall",
                    "scores": [{"name": "precision", "value": 0.71}],
                    "verdict": "needs_patch",
                    "review": "Precision improved but low-liquidity bucket regressed.",
                },
            ],
        },
        imported_at="2026-05-20T00:00:00+00:00",
    )

    loop_request = normalized.loop_create_request
    assert loop_request.title == "Factor RD loop"
    assert loop_request.objective == "Improve defensive timing with volume-price divergence."
    assert loop_request.hypothesis == "Volume divergence reduces false breakouts."
    assert loop_request.plan == "Build divergence feature\nBacktest against baseline"
    assert loop_request.action_target == "factor"
    assert loop_request.owner == "rd-agent"
    assert loop_request.tags == ["rd-agent", "external-import", "factor", "timing"]
    assert loop_request.target_modules == ["factor_engine", "signalops"]

    assert normalized.external_source == {
        "source": "rd-agent",
        "source_type": "RD_AGENT_TRACE",
        "source_id": "RD_RUN_001",
        "imported_at": "2026-05-20T00:00:00+00:00",
        "external": True,
    }
    assert len(normalized.iterations) == 2

    first = normalized.iterations[0]
    assert first.order == 1
    assert first.create_request.metrics["ic"] == 0.13
    assert first.feedback_request.verdict == "ACCEPTED"
    assert first.feedback_request.action == "ACCEPT"
    assert first.feedback_request.note == "Stable improvement."
    assert first.feedback_request.evidence_links[0].source_type == "RD_AGENT_TRACE"
    assert first.feedback_request.evidence_links[0].source_id == "artifact-1"
    assert first.external_source["external_iteration_id"] == "iter-a"

    second = normalized.iterations[1]
    assert second.create_request.hypothesis == "Add liquidity guard for low turnover names."
    assert second.create_request.target_modules == ["signalops", "risk_firewall"]
    assert second.create_request.metrics == {"precision": 0.71}
    assert second.feedback_request.verdict == "PATCH_REQUIRED"
    assert second.feedback_request.action == "PATCH"
    assert second.feedback_request.note == "Precision improved but low-liquidity bucket regressed."


def test_normalize_rd_agent_trace_falls_back_to_top_level_iteration():
    normalized = normalize_rd_agent_trace(
        {
            "id": "RD_RUN_MIN",
            "title": "Minimal external trace",
            "goal": "Import a top-level RD-Agent result.",
            "hypothesis": "Top-level hypothesis is still importable.",
            "metrics": "score=0.8",
            "evidence": "logs/rd-agent/run.log",
            "api_key": "sk-proj-secretsecretsecret",
        },
        imported_at="2026-05-20T00:00:00+00:00",
    )

    assert normalized.loop_create_request.title == "Minimal external trace"
    assert normalized.loop_create_request.objective == "Import a top-level RD-Agent result."
    assert normalized.loop_create_request.hypothesis == "Top-level hypothesis is still importable."
    assert normalized.iterations[0].create_request.metrics == {"value": "score=0.8"}
    assert normalized.iterations[0].feedback_request.evidence_links[0].source_id == "logs/rd-agent/run.log"
    assert normalized.iterations[0].raw["api_key"] == MASK
    assert normalized.warnings == [
        "No explicit iterations found; created one iteration from top-level trace fields."
    ]


def test_mask_secrets_redacts_sensitive_keys_and_secret_text():
    masked = mask_secrets(
        {
            "authorization": "Bearer live-secret-token",
            "nested": {
                "url": "https://example.test/callback?token=abc123456789&ok=1",
                "note": "use sk-proj-abcdefghijklmnopqrstuvwxyz for the run",
                "password": "plain-text",
            },
        }
    )

    assert masked["authorization"] == MASK
    assert masked["nested"]["url"] == f"https://example.test/callback?token={MASK}&ok=1"
    assert masked["nested"]["note"] == f"use {MASK} for the run"
    assert masked["nested"]["password"] == MASK


def test_normalize_rd_agent_trace_rejects_non_mapping_input():
    with pytest.raises(TypeError):
        normalize_rd_agent_trace(["not", "a", "mapping"])


def test_normalize_rd_agent_trace_rejects_iteration_budget_overflow():
    with pytest.raises(ValueError, match="iteration limit"):
        normalize_rd_agent_trace({"iterations": [{"hypothesis": f"h{index}"} for index in range(MAX_TRACE_ITERATIONS + 1)]})


def test_normalize_rd_agent_trace_rejects_evidence_budget_overflow():
    with pytest.raises(ValueError, match="evidence"):
        normalize_rd_agent_trace(
            {
                "iterations": [
                    {
                        "hypothesis": "bounded evidence",
                        "evidence": [f"artifact-{index}" for index in range(MAX_TRACE_EVIDENCE_PER_ITERATION + 1)],
                    }
                ]
            }
        )
