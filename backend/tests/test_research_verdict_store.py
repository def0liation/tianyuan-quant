from copy import deepcopy

import pytest
from fastapi import HTTPException

from app.api import routes_analysis, routes_research
from app.core import analysis_lifecycle_service, knowledge_store, research_verdict_store as verdict_module
from app.core.research_store import ResearchLoopStore
from app.models.knowledge import CreateKnowledgeItemRequest
from app.models.research import (
    CreateResearchIterationRequest,
    CreateResearchLoopRequest,
    ResearchEvidenceLink,
    ResearchIterationFeedbackRequest,
    ResearchVerdictEvidence,
)


@pytest.fixture(autouse=True)
def restore_runs_store():
    snapshot = deepcopy(routes_analysis.runs_store)
    yield
    routes_analysis.runs_store.clear()
    routes_analysis.runs_store.update(snapshot)


@pytest.fixture
def research_store():
    return ResearchLoopStore()


@pytest.fixture(autouse=True)
def temp_knowledge_store(monkeypatch, tmp_path):
    monkeypatch.setattr(knowledge_store, "STORAGE_FILE", tmp_path / "knowledge_iterations.json")


def _run(run_id: str, *, quality_level: str = "HIGH", quality_score: int = 88):
    return {
        "runId": run_id,
        "stockCode": "603663",
        "stockName": "Test Stock",
        "runMode": "STANDARD_MODE",
        "status": "COMPLETED",
        "dataMode": "LIVE",
        "createdAt": "2026-05-19T09:00:00",
        "updatedAt": "2026-05-19T09:05:00",
        "compressedSummary": {
            "quality": {
                "score": quality_score,
                "level": quality_level,
                "issues": [] if quality_level == "HIGH" else ["data_sources_not_reported"],
                "missing_critical_fields": [],
            }
        },
        "dvg": {"status": "PASS", "dataReliability": "HIGH"},
        "qiam": {"finalBuySuitability": "BUY_CANDIDATE", "modelConfidenceFinal": 0.82},
        "killSwitch": {"active": False, "level": "NONE"},
        "signalOps": {"signalStatus": "QUALIFIED", "blockedReason": ""},
        "paperTrading": {
            "status": "ACTIVE",
            "simulatedProfit": 0.04,
            "maxDrawdown": 0.03,
            "triggeredInvalidation": False,
        },
        "finalWriter": {"finalAction": "BUY_CANDIDATE", "sections": [{"title": "Decision", "content": "ok"}]},
        "dataSources": {"summary": {"availableCount": 4, "totalCount": 4}},
        "nodes": [{"id": "final_writer", "status": "PASS", "outputSummary": "Decision completed"}],
        "agentResults": [{"node": "final_writer", "status": "PASS"}],
        "auditLog": [{"node": "final_writer", "message": "completed"}],
    }


def _assert_review_gate_evidence_quality(evidence):
    forbidden = {
        "HIGH",
        "PASS",
        "READY",
        "STRONG",
        "PRIMARY",
        "PRIMARY_EVIDENCE",
        "PRIMARY_EVIDENCE_READY",
        "RESEARCH_GRADE",
    }
    assert evidence
    assert {str(item.quality).upper() for item in evidence}.isdisjoint(forbidden)


def test_review_gate_verdict_evidence_caps_legacy_research_grade_labels():
    legacy_evidence = [
        ResearchVerdictEvidence.model_construct(
            source_type="BACKTEST",
            source_id="BT_LEGACY_RESEARCH_GRADE_001",
            label="Legacy backtest evidence",
            quality="RESEARCH_GRADE",
            reported_quality=None,
            summary="Legacy persisted verdict evidence bypassed model validators.",
            metrics={},
            created_at="2026-06-15T00:00:00+00:00",
        ),
        ResearchVerdictEvidence.model_construct(
            source_type="BACKTEST",
            source_id="BT_LEGACY_PRIMARY_READY_001",
            label="Legacy primary-ready evidence",
            quality="PRIMARY_EVIDENCE_READY",
            reported_quality=None,
            summary="Legacy persisted verdict evidence bypassed model validators.",
            metrics={},
            created_at="2026-06-15T00:00:00+00:00",
        ),
        ResearchVerdictEvidence.model_construct(
            source_type="BACKTEST",
            source_id="BT_LEGACY_SUPPORTING_ONLY_001",
            label="Legacy supporting-only evidence",
            quality="SUPPORTING_ONLY",
            reported_quality=None,
            summary="Legacy persisted verdict evidence bypassed model validators.",
            metrics={},
            created_at="2026-06-15T00:00:00+00:00",
        ),
    ]

    capped = verdict_module._review_gate_verdict_evidence(legacy_evidence)

    assert {item.source_id: item.quality for item in capped} == {
        "BT_LEGACY_RESEARCH_GRADE_001": "MEDIUM",
        "BT_LEGACY_PRIMARY_READY_001": "MEDIUM",
        "BT_LEGACY_SUPPORTING_ONLY_001": "LOW",
    }
    assert {item.source_id: item.reported_quality for item in capped} == {
        "BT_LEGACY_RESEARCH_GRADE_001": "RESEARCH_GRADE",
        "BT_LEGACY_PRIMARY_READY_001": "PRIMARY_EVIDENCE_READY",
        "BT_LEGACY_SUPPORTING_ONLY_001": "SUPPORTING_ONLY",
    }
    _assert_review_gate_evidence_quality(capped)


def test_dedupe_evidence_preserves_previous_reported_quality():
    stored = ResearchVerdictEvidence(
        source_type="BACKTEST",
        source_id="BT_REPORTED_QUALITY_DEDUPE_001",
        label="Stored backtest audit",
        quality="MEDIUM",
        reported_quality="HIGH",
        summary="Stored review-gated evidence preserved the original audit grade.",
        metrics={},
        created_at="2026-06-15T00:00:00+00:00",
    )
    hydrated = ResearchVerdictEvidence(
        source_type="BACKTEST",
        source_id="BT_REPORTED_QUALITY_DEDUPE_001",
        label="Hydrated backtest audit",
        quality="MEDIUM",
        reported_quality=None,
        summary="Hydrated evidence already passed through the review gate.",
        metrics={},
        created_at="2026-06-15T00:01:00+00:00",
    )

    deduped = verdict_module._dedupe_evidence([stored, hydrated])

    assert len(deduped) == 1
    assert deduped[0].label == "Hydrated backtest audit"
    assert deduped[0].quality == "MEDIUM"
    assert deduped[0].reported_quality == "HIGH"


def test_research_verdict_compare_uses_analysis_lifecycle_service(monkeypatch):
    calls: list[tuple[str, str]] = []

    def fake_compare_runs(left_id: str, right_id: str) -> dict:
        calls.append((left_id, right_id))
        return {
            "leftRun": {"runId": left_id},
            "rightRun": {"runId": right_id},
            "changedItems": [],
            "changedCount": 0,
            "summary": ["Run compare generated."],
            "generatedAt": "2026-05-31T00:00:00+00:00",
        }

    monkeypatch.setattr(analysis_lifecycle_service, "compare_runs", fake_compare_runs)

    result = verdict_module.ResearchVerdictStore()._safe_compare_runs("RUN_BASE", "RUN_CURRENT")

    assert calls == [("RUN_BASE", "RUN_CURRENT")]
    assert result and result["rightRun"]["runId"] == "RUN_CURRENT"


@pytest.mark.asyncio
async def test_verdict_inputs_accept_high_quality_linked_run(research_store):
    routes_analysis.runs_store.clear()
    routes_analysis.runs_store["RUN_HIGH_001"] = _run("RUN_HIGH_001")
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(title="Quality verdict", objective="Validate high quality run")
    )
    iteration = await research_store.create_iteration(
        detail.loop.loop_id,
        CreateResearchIterationRequest(
            hypothesis="High quality evidence supports accepting the iteration.",
            linked_run_id="RUN_HIGH_001",
        ),
    )

    inputs = await verdict_module.research_verdict_store.get_inputs(iteration.iteration_id)

    assert inputs is not None
    assert inputs.engine_verdict == "ACCEPT"
    assert inputs.suggested_feedback_verdict == "ACCEPTED"
    assert inputs.can_accept_feedback is True
    assert inputs.metrics["quality_score"] == 88
    assert inputs.metrics["action_target"] == "factor"
    assert inputs.metrics["thresholds"]["min_quality_score"] == 65
    assert inputs.metrics["signalops_status"] == "QUALIFIED"
    assert inputs.metrics["paper_trading_simulated_profit"] == 0.04
    assert any(item.source_type == "RUN" for item in inputs.evidence)
    _assert_review_gate_evidence_quality(inputs.evidence)
    run_evidence = next(item for item in inputs.evidence if item.source_type == "RUN")
    assert run_evidence.quality == "MEDIUM"
    assert run_evidence.reported_quality == "HIGH"

    accepted = await routes_research.record_research_iteration_feedback_route(
        iteration.iteration_id,
        ResearchIterationFeedbackRequest(action="ACCEPT", verdict="ACCEPTED"),
    )

    assert accepted.verdict == "ACCEPTED"
    assert accepted.metrics["quality_score"] == 88
    assert accepted.metrics["verdict_inputs_generated_at"]
    assert any(item.source_type == "RUN" and item.source_id == "RUN_HIGH_001" for item in accepted.evidence_links)
    accepted_run_evidence = next(
        item for item in accepted.evidence_links
        if item.source_type == "RUN" and item.source_id == "RUN_HIGH_001"
    )
    assert accepted_run_evidence.quality == "MEDIUM"
    assert accepted_run_evidence.reported_quality == "HIGH"
    _assert_review_gate_evidence_quality(accepted.evidence_links)


@pytest.mark.asyncio
async def test_verdict_decision_receives_review_gate_evidence_only(monkeypatch, research_store):
    captured_qualities: list[str] = []

    def capture_decide(metrics, evidence, blocking_reasons, quality_warnings, thresholds):
        captured_qualities.extend(str(item.quality).upper() for item in evidence)
        return "NEEDS_MORE_DATA", "PENDING"

    monkeypatch.setattr(verdict_module.research_verdict_store, "_decide", capture_decide)
    routes_analysis.runs_store.clear()
    routes_analysis.runs_store["RUN_HIGH_WITH_STORED_STRONG"] = _run("RUN_HIGH_WITH_STORED_STRONG")
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="Decision evidence gate",
            objective="Strong stored evidence must be capped before verdict decision.",
        )
    )
    iteration = await research_store.create_iteration(
        detail.loop.loop_id,
        CreateResearchIterationRequest(
            hypothesis="Decision inputs should never see strong evidence labels.",
            linked_run_id="RUN_HIGH_WITH_STORED_STRONG",
        ),
    )
    await research_store.record_feedback(
        iteration.iteration_id,
        ResearchIterationFeedbackRequest(
            action="ATTACH_STORED_EVIDENCE",
            verdict="PENDING",
            evidence_links=[
                ResearchEvidenceLink(
                    source_type="CASE",
                    source_id="CASE_STORED_STRONG_001",
                    label="Legacy reviewed case evidence",
                    quality="HIGH",
                    created_at="2026-05-19T10:00:00",
                ),
                ResearchEvidenceLink(
                    source_type="PATCH",
                    source_id="PATCH_STORED_PASS_001",
                    label="Legacy patch evidence",
                    quality="PASS",
                    created_at="2026-05-19T10:00:00",
                ),
            ],
        ),
    )

    inputs = await verdict_module.research_verdict_store.get_inputs(iteration.iteration_id)

    assert inputs is not None
    assert captured_qualities
    assert set(captured_qualities).isdisjoint({"HIGH", "PASS", "READY", "STRONG", "PRIMARY", "PRIMARY_EVIDENCE"})
    assert {"MEDIUM"} <= set(captured_qualities)
    _assert_review_gate_evidence_quality(inputs.evidence)
    input_qualities = {item.source_id: item for item in inputs.evidence}
    assert input_qualities["CASE_STORED_STRONG_001"].reported_quality == "HIGH"
    assert input_qualities["PATCH_STORED_PASS_001"].reported_quality == "PASS"
    payload_evidence = {item["source_id"]: item for item in inputs.model_dump(by_alias=True)["evidence"]}
    assert payload_evidence["CASE_STORED_STRONG_001"]["reportedQuality"] == "HIGH"
    assert payload_evidence["PATCH_STORED_PASS_001"]["reportedQuality"] == "PASS"
    stored_detail = await research_store.get_loop_detail(detail.loop.loop_id)
    assert stored_detail is not None
    stored_iteration = next(item for item in stored_detail.iterations if item.iteration_id == iteration.iteration_id)
    stored_qualities = {item.source_id: item.quality for item in stored_iteration.evidence_links}
    assert stored_qualities["CASE_STORED_STRONG_001"] == "MEDIUM"
    assert stored_qualities["PATCH_STORED_PASS_001"] == "MEDIUM"


@pytest.mark.asyncio
async def test_verdict_inputs_blocks_acceptance_for_low_quality_run(research_store):
    routes_analysis.runs_store.clear()
    routes_analysis.runs_store["RUN_LOW_001"] = _run("RUN_LOW_001", quality_level="LOW", quality_score=38)
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(title="Low quality verdict", objective="Block low quality evidence")
    )
    iteration = await research_store.create_iteration(
        detail.loop.loop_id,
        CreateResearchIterationRequest(
            hypothesis="Low quality evidence should not be accepted.",
            linked_run_id="RUN_LOW_001",
        ),
    )

    inputs = await verdict_module.research_verdict_store.get_inputs(iteration.iteration_id)

    assert inputs is not None
    assert inputs.engine_verdict == "NEEDS_MORE_DATA"
    assert inputs.suggested_feedback_verdict == "PENDING"
    assert inputs.can_accept_feedback is False
    assert "data_sources_not_reported" in inputs.quality_warnings


@pytest.mark.asyncio
async def test_verdict_inputs_exposes_mfe_mae_research_but_keeps_it_supporting_only(monkeypatch, research_store):
    async def fake_get_run(run_id: str):
        assert run_id == "BT_BOTTOM_ONLY_001"
        return {
            "run_id": run_id,
            "status": "COMPLETED",
            "parameters": {"signal_source": "BOTTOM_RESEARCH"},
            "report": {
                "signal_source": "BOTTOM_RESEARCH",
                "total_return_pct": 3.4,
                "hit_rate": 0.6,
                "max_drawdown_pct": 0.05,
                "evidenceStrength": {
                    "grade": "HIGH",
                    "canSupportResearchVerdict": True,
                    "researchUsage": "primary_evidence",
                },
                "provenance": {"bottomResearchVersion": "bottom-research-v1"},
            },
            "updated_at": "2026-05-19T10:00:00",
        }

    monkeypatch.setattr(verdict_module.backtest_store, "get_run", fake_get_run)
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(title="MFE/MAE-only verdict", objective="MFE/MAE evidence remains supporting only")
    )
    iteration = await research_store.create_iteration(
        detail.loop.loop_id,
        CreateResearchIterationRequest(hypothesis="MFE/MAE-only evidence should stay supporting-only."),
    )
    await research_store.record_feedback(
        iteration.iteration_id,
        ResearchIterationFeedbackRequest(
            action="BOTTOM_RESEARCH_BACKTEST_LINKED",
            verdict="PENDING",
            linked_backtest_id="BT_BOTTOM_ONLY_001",
            metrics={
                "quality_score": 95,
                "quality_level": "HIGH",
                "bottom_research_status": "PASS",
                "bottom_repair_probability": 0.81,
                "breakdown_risk_probability": 0.12,
                "bottom_research_supporting_only": True,
            },
            evidence_links=[
                ResearchEvidenceLink(
                    source_type="BOTTOM_RESEARCH_RUN",
                    source_id="RUN_BOTTOM_ONLY_001",
                    label="MFE/MAE Path Research analysis output",
                    quality="HIGH",
                    created_at="2026-05-19T10:00:00",
                ),
                ResearchEvidenceLink(
                    source_type="BACKTEST",
                    source_id="BT_BOTTOM_ONLY_001",
                    label="MFE/MAE Path Research automatic backtest",
                    quality="HIGH",
                    created_at="2026-05-19T10:00:00",
                ),
            ],
        ),
    )

    inputs = await verdict_module.research_verdict_store.get_inputs(iteration.iteration_id)

    assert inputs is not None
    assert inputs.metrics["bottom_repair_probability"] == 0.81
    assert inputs.metrics["breakdown_risk_probability"] == 0.12
    assert inputs.metrics["bottom_research_supporting_only"] is True
    assert inputs.can_accept_feedback is False
    assert "mfe_mae_research_supporting_only" in inputs.quality_warnings
    assert any("MFE/MAE Path Research evidence is supporting_only" in reason for reason in inputs.blocking_reasons)
    _assert_review_gate_evidence_quality(inputs.evidence)


@pytest.mark.asyncio
async def test_verdict_inputs_keeps_direct_mfe_mae_run_supporting_only(research_store):
    routes_analysis.runs_store.clear()
    run = _run("RUN_MFE_ONLY_001", quality_level="HIGH", quality_score=94)
    run["taskType"] = "mfe_mae_path_research"
    run["finalWriter"] = {"finalAction": "WAIT"}
    run["qiam"] = {}
    run["mfeMaeResearch"] = {
        "status": "PASS",
        "researchType": "MFE_MAE_PATH_RESEARCH",
        "mfeFavorableProbability": 0.82,
        "maeBreachProbability": 0.16,
        "regimeState": "BOTTOM_REPAIR_ZONE",
        "modelDiagnostics": {
            "modelVersion": "mfe-mae-path-risk-v1",
            "sampleCount": 260,
            "evidenceGrade": "HIGH",
            "mfeMaePathRiskEvaluation": {
                "rankIc": 0.18,
                "folds": [{"fold": 1}, {"fold": 2}],
            },
        },
        "provenance": {
            "modelVersion": "mfe-mae-path-risk-v1",
            "firstTradeDate": "2024-01-02",
            "lastTradeDate": "2025-03-31",
            "simulation_only": True,
            "is_real_trade": False,
        },
    }
    routes_analysis.runs_store["RUN_MFE_ONLY_001"] = run
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(title="Direct MFE/MAE run", objective="Direct MFE/MAE run stays supporting only")
    )
    iteration = await research_store.create_iteration(
        detail.loop.loop_id,
        CreateResearchIterationRequest(
            hypothesis="A direct MFE/MAE research run should not auto-accept by itself.",
            linked_run_id="RUN_MFE_ONLY_001",
        ),
    )

    inputs = await verdict_module.research_verdict_store.get_inputs(iteration.iteration_id)

    assert inputs is not None
    assert inputs.can_accept_feedback is False
    assert inputs.engine_verdict == "NEEDS_MORE_DATA"
    assert inputs.metrics["mfe_mae_research_supporting_only"] is True
    assert inputs.metrics["bottom_research_supporting_only"] is True
    assert inputs.evidence[0].source_type == "MFE_MAE_RESEARCH_RUN"
    assert "mfe_mae_research_supporting_only" in inputs.quality_warnings
    assert any("MFE/MAE Path Research evidence is supporting_only" in reason for reason in inputs.blocking_reasons)
    _assert_review_gate_evidence_quality(inputs.evidence)


@pytest.mark.asyncio
async def test_verdict_inputs_allows_accept_with_bottom_and_qualified_non_bottom_evidence(research_store):
    routes_analysis.runs_store.clear()
    routes_analysis.runs_store["RUN_HIGH_WITH_BOTTOM_001"] = _run("RUN_HIGH_WITH_BOTTOM_001")
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="MFE/MAE plus independent verdict",
            objective="MFE/MAE evidence should not block qualified independent evidence",
        )
    )
    iteration = await research_store.create_iteration(
        detail.loop.loop_id,
        CreateResearchIterationRequest(
            hypothesis="Independent high quality evidence can accept while MFE/MAE remains supporting-only.",
            linked_run_id="RUN_HIGH_WITH_BOTTOM_001",
        ),
    )
    await research_store.record_feedback(
        iteration.iteration_id,
        ResearchIterationFeedbackRequest(
            action="BOTTOM_RESEARCH_BACKTEST_LINKED",
            verdict="PENDING",
            metrics={
                "bottom_research_status": "PASS",
                "bottom_repair_probability": 0.79,
                "breakdown_risk_probability": 0.13,
                "bottom_research_supporting_only": True,
                "simulation_only": True,
                "is_real_trade": False,
            },
            evidence_links=[
                ResearchEvidenceLink(
                    source_type="BOTTOM_RESEARCH_RUN",
                    source_id="RUN_BOTTOM_SUPPORT_001",
                    label="MFE/MAE Path Research analysis output",
                    quality="HIGH",
                    created_at="2026-05-19T10:00:00",
                ),
                ResearchEvidenceLink(
                    source_type="BACKTEST",
                    source_id="BT_BOTTOM_SUPPORT_001",
                    label="MFE/MAE Path Research automatic backtest",
                    quality="HIGH",
                    created_at="2026-05-19T10:00:00",
                ),
            ],
        ),
    )

    inputs = await verdict_module.research_verdict_store.get_inputs(iteration.iteration_id)

    assert inputs is not None
    assert inputs.can_accept_feedback is True
    assert inputs.engine_verdict == "ACCEPT"
    assert inputs.suggested_feedback_verdict == "ACCEPTED"
    assert inputs.metrics["bottom_research_supporting_only"] is True
    assert "mfe_mae_research_supporting_only" not in inputs.quality_warnings
    assert not any("MFE/MAE Path Research evidence is supporting_only" in reason for reason in inputs.blocking_reasons)
    _assert_review_gate_evidence_quality(inputs.evidence)


@pytest.mark.asyncio
async def test_verdict_inputs_warns_for_unhydrated_low_quality_backtest_evidence(research_store):
    routes_analysis.runs_store.clear()
    routes_analysis.runs_store["RUN_HIGH_WITH_STORED_BT"] = _run("RUN_HIGH_WITH_STORED_BT")
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(title="Stored backtest evidence", objective="Warn on low quality stored evidence")
    )
    iteration = await research_store.create_iteration(
        detail.loop.loop_id,
        CreateResearchIterationRequest(
            hypothesis="Low quality stored backtest evidence should not be silently ignored.",
            linked_run_id="RUN_HIGH_WITH_STORED_BT",
        ),
    )
    await research_store.record_feedback(
        iteration.iteration_id,
        ResearchIterationFeedbackRequest(
            action="ATTACH_STORED_BACKTEST_EVIDENCE",
            verdict="PENDING",
            evidence_links=[
                ResearchEvidenceLink(
                    source_type="BACKTEST",
                    source_id="BT_STORED_LOW_001",
                    label="Stored low-quality backtest evidence",
                    quality="LOW",
                    created_at="2026-05-19T10:00:00",
                )
            ],
        ),
    )

    inputs = await verdict_module.research_verdict_store.get_inputs(iteration.iteration_id)

    assert inputs is not None
    assert inputs.can_accept_feedback is False
    assert any("BACKTEST:BT_STORED_LOW_001 quality=LOW" in warning for warning in inputs.quality_warnings)


@pytest.mark.asyncio
async def test_verdict_inputs_marks_regressed_backtest_as_patch_required(monkeypatch, research_store):
    async def fake_get_run(run_id: str):
        assert run_id == "BT_REGRESSED_001"
        return {
            "run_id": run_id,
            "status": "COMPLETED",
            "report": {"total_return_pct": -0.08, "hit_rate": 0.35, "max_drawdown_pct": 0.16},
            "comparison": {"verdict": "REGRESSED", "return_delta": -0.12, "drawdown_delta": 0.08},
            "updated_at": "2026-05-19T10:00:00",
        }

    monkeypatch.setattr(verdict_module.backtest_store, "get_run", fake_get_run)
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(title="Backtest verdict", objective="Detect regression")
    )
    iteration = await research_store.create_iteration(
        detail.loop.loop_id,
        CreateResearchIterationRequest(hypothesis="Backtest regression should require a patch."),
    )
    await research_store.record_feedback(
        iteration.iteration_id,
        ResearchIterationFeedbackRequest(
            action="LINK_BACKTEST",
            verdict="PENDING",
            linked_backtest_id="BT_REGRESSED_001",
        ),
    )

    inputs = await verdict_module.research_verdict_store.get_inputs(iteration.iteration_id)

    assert inputs is not None
    assert inputs.engine_verdict == "REGRESSED"
    assert inputs.suggested_feedback_verdict == "PATCH_REQUIRED"
    assert any(item.source_type == "BACKTEST" for item in inputs.evidence)


@pytest.mark.asyncio
async def test_verdict_inputs_downgrades_weak_direct_linked_backtest(monkeypatch, research_store):
    async def fake_get_run(run_id: str):
        assert run_id == "BT_WEAK_001"
        return {
            "run_id": run_id,
            "status": "COMPLETED",
            "report": {
                "total_return_pct": 0.04,
                "hit_rate": 0.5,
                "max_drawdown_pct": 0.08,
                "data_source": "MOCK",
                "evidenceStrength": {
                    "grade": "LOW",
                    "canSupportResearchVerdict": False,
                    "researchUsage": "supporting_only",
                },
                "limitations": ["Market data source is MOCK."],
            },
            "comparison": {"verdict": "IMPROVED", "return_delta": 0.02, "drawdown_delta": -0.01},
            "updated_at": "2026-05-19T10:00:00",
        }

    monkeypatch.setattr(verdict_module.backtest_store, "get_run", fake_get_run)
    routes_analysis.runs_store.clear()
    routes_analysis.runs_store["RUN_HIGH_WITH_WEAK_BT"] = _run("RUN_HIGH_WITH_WEAK_BT")
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(title="Weak backtest verdict", objective="Keep weak backtest supporting only")
    )
    iteration = await research_store.create_iteration(
        detail.loop.loop_id,
        CreateResearchIterationRequest(
            hypothesis="Weak backtest should not upgrade verdict evidence.",
            linked_run_id="RUN_HIGH_WITH_WEAK_BT",
        ),
    )
    await research_store.record_feedback(
        iteration.iteration_id,
        ResearchIterationFeedbackRequest(
            action="LINK_BACKTEST",
            verdict="PENDING",
            linked_backtest_id="BT_WEAK_001",
        ),
    )

    inputs = await verdict_module.research_verdict_store.get_inputs(iteration.iteration_id)

    assert inputs is not None
    backtest_evidence = next(item for item in inputs.evidence if item.source_type == "BACKTEST")
    assert backtest_evidence.quality == "LOW"
    assert inputs.can_accept_feedback is False
    assert inputs.metrics["backtest_can_support_research_verdict"] is False
    assert any("BACKTEST:BT_WEAK_001 quality=LOW" in warning for warning in inputs.quality_warnings)


@pytest.mark.asyncio
async def test_verdict_inputs_reads_legacy_snake_case_backtest_evidence(monkeypatch, research_store):
    async def fake_get_run(run_id: str):
        assert run_id == "BT_LEGACY_WEAK_001"
        return {
            "run_id": run_id,
            "status": "COMPLETED",
            "report": {
                "total_return_pct": 0.12,
                "hit_rate": 0.68,
                "max_drawdown_pct": 0.07,
                "evidence_strength": {
                    "grade": "LOW",
                    "can_support_research_verdict": "false",
                    "research_usage": "supporting_only",
                },
            },
            "comparison": {"verdict": "IMPROVED", "return_delta": 0.1, "drawdown_delta": -0.02},
            "updated_at": "2026-05-19T10:00:00",
        }

    monkeypatch.setattr(verdict_module.backtest_store, "get_run", fake_get_run)
    routes_analysis.runs_store.clear()
    routes_analysis.runs_store["RUN_HIGH_WITH_LEGACY_BT"] = _run("RUN_HIGH_WITH_LEGACY_BT")
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(title="Legacy backtest verdict", objective="Read legacy evidence strength")
    )
    iteration = await research_store.create_iteration(
        detail.loop.loop_id,
        CreateResearchIterationRequest(
            hypothesis="Legacy weak backtest evidence should remain supporting only.",
            linked_run_id="RUN_HIGH_WITH_LEGACY_BT",
        ),
    )
    await research_store.record_feedback(
        iteration.iteration_id,
        ResearchIterationFeedbackRequest(
            action="LINK_BACKTEST",
            verdict="PENDING",
            linked_backtest_id="BT_LEGACY_WEAK_001",
        ),
    )

    inputs = await verdict_module.research_verdict_store.get_inputs(iteration.iteration_id)

    assert inputs is not None
    assert inputs.metrics["backtest_evidence_grade"] == "LOW"
    assert inputs.metrics["backtest_can_support_research_verdict"] is False
    assert inputs.can_accept_feedback is False
    assert any("BACKTEST:BT_LEGACY_WEAK_001 quality=LOW" in warning for warning in inputs.quality_warnings)


@pytest.mark.asyncio
async def test_verdict_inputs_conservatively_merges_conflicting_backtest_evidence_aliases(monkeypatch, research_store):
    async def fake_get_run(run_id: str):
        assert run_id == "BT_CONFLICTING_ALIAS_001"
        return {
            "run_id": run_id,
            "status": "COMPLETED",
            "report": {
                "total_return_pct": 0.2,
                "hit_rate": 0.74,
                "max_drawdown_pct": 0.03,
                "evidenceStrength": {
                    "grade": "HIGH",
                    "canSupportResearchVerdict": True,
                    "weakSample": False,
                    "researchUsage": "primary_evidence",
                },
                "evidence_strength": {
                    "grade": "LOW",
                    "can_support_research_verdict": False,
                    "weak_sample": True,
                    "research_usage": "supporting_only",
                },
            },
            "comparison": {"verdict": "IMPROVED", "return_delta": 0.12, "drawdown_delta": -0.02},
            "updated_at": "2026-05-19T10:00:00",
        }

    monkeypatch.setattr(verdict_module.backtest_store, "get_run", fake_get_run)
    routes_analysis.runs_store.clear()
    routes_analysis.runs_store["RUN_HIGH_WITH_CONFLICTING_BT"] = _run("RUN_HIGH_WITH_CONFLICTING_BT")
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(title="Conflicting backtest verdict", objective="Do not upgrade conflicting evidence")
    )
    iteration = await research_store.create_iteration(
        detail.loop.loop_id,
        CreateResearchIterationRequest(
            hypothesis="Conflicting backtest evidence aliases should remain supporting-only.",
            linked_run_id="RUN_HIGH_WITH_CONFLICTING_BT",
        ),
    )
    await research_store.record_feedback(
        iteration.iteration_id,
        ResearchIterationFeedbackRequest(
            action="LINK_BACKTEST",
            verdict="PENDING",
            linked_backtest_id="BT_CONFLICTING_ALIAS_001",
        ),
    )

    inputs = await verdict_module.research_verdict_store.get_inputs(iteration.iteration_id)

    assert inputs is not None
    backtest_evidence = next(item for item in inputs.evidence if item.source_type == "BACKTEST")
    assert backtest_evidence.quality == "LOW"
    assert inputs.metrics["backtest_evidence_grade"] == "LOW"
    assert inputs.metrics["backtest_can_support_research_verdict"] is False
    assert inputs.metrics["backtest_research_usage"] == "supporting_only"
    assert inputs.metrics["backtest_review_conclusion"] == "SUPPORTING_ONLY"
    assert inputs.can_accept_feedback is False
    assert any("BT_CONFLICTING_ALIAS_001 quality=LOW" in warning for warning in inputs.quality_warnings)


@pytest.mark.asyncio
async def test_verdict_inputs_keeps_completed_legacy_backtest_without_evidence_strength_supporting_only(monkeypatch, research_store):
    async def fake_get_run(run_id: str):
        assert run_id == "BT_LEGACY_NO_GATE_001"
        return {
            "run_id": run_id,
            "status": "COMPLETED",
            "report": {
                "total_return_pct": 0.18,
                "hit_rate": 0.72,
                "max_drawdown_pct": 0.04,
                "data_source": "LIVE",
            },
            "comparison": {"verdict": "IMPROVED", "return_delta": 0.12, "drawdown_delta": -0.02},
            "updated_at": "2026-05-19T10:00:00",
        }

    monkeypatch.setattr(verdict_module.backtest_store, "get_run", fake_get_run)
    routes_analysis.runs_store.clear()
    routes_analysis.runs_store["RUN_HIGH_WITH_NO_GATE_BT"] = _run("RUN_HIGH_WITH_NO_GATE_BT")
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="Legacy backtest without review gate",
            objective="Legacy completed backtest must not become primary verdict evidence by default.",
        )
    )
    iteration = await research_store.create_iteration(
        detail.loop.loop_id,
        CreateResearchIterationRequest(
            hypothesis="A legacy completed backtest without evidenceStrength stays supporting-only.",
            linked_run_id="RUN_HIGH_WITH_NO_GATE_BT",
        ),
    )
    await research_store.record_feedback(
        iteration.iteration_id,
        ResearchIterationFeedbackRequest(
            action="LINK_BACKTEST",
            verdict="PENDING",
            linked_backtest_id="BT_LEGACY_NO_GATE_001",
        ),
    )

    inputs = await verdict_module.research_verdict_store.get_inputs(iteration.iteration_id)

    assert inputs is not None
    backtest_evidence = next(item for item in inputs.evidence if item.source_type == "BACKTEST")
    assert backtest_evidence.quality == "LOW"
    assert inputs.metrics["backtest_evidence_grade"] == "LOW"
    assert inputs.metrics["backtest_can_support_research_verdict"] is False
    assert inputs.metrics["backtest_research_usage"] == "supporting_only"
    assert inputs.metrics["backtest_review_conclusion"] == "SUPPORTING_ONLY"
    assert inputs.can_accept_feedback is False
    assert any(
        "BACKTEST:BT_LEGACY_NO_GATE_001 quality=LOW; missing evidenceStrength review gate" in warning
        for warning in inputs.quality_warnings
    )


@pytest.mark.asyncio
async def test_verdict_inputs_reports_review_gate_ready_without_primary_backtest_label(monkeypatch, research_store):
    async def fake_get_run(run_id: str):
        assert run_id == "BT_REVIEW_GATE_READY_001"
        return {
            "run_id": run_id,
            "status": "COMPLETED",
            "report": {
                "total_return_pct": 0.22,
                "hit_rate": 0.69,
                "max_drawdown_pct": 0.05,
                "evidenceStrength": {
                    "grade": "HIGH",
                    "canSupportResearchVerdict": True,
                    "weakSample": False,
                    "researchUsage": "primary_evidence",
                },
                "limitations": [],
            },
            "comparison": {"verdict": "IMPROVED", "return_delta": 0.11, "drawdown_delta": -0.01},
            "updated_at": "2026-05-19T10:00:00",
        }

    monkeypatch.setattr(verdict_module.backtest_store, "get_run", fake_get_run)
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="Review gate backtest verdict",
            objective="Primary-looking backtest evidence stays review-gated in verdict inputs.",
        )
    )
    iteration = await research_store.create_iteration(
        detail.loop.loop_id,
        CreateResearchIterationRequest(hypothesis="Review-gated backtest evidence should not expose primary labels."),
    )
    await research_store.record_feedback(
        iteration.iteration_id,
        ResearchIterationFeedbackRequest(
            action="LINK_BACKTEST",
            verdict="PENDING",
            linked_backtest_id="BT_REVIEW_GATE_READY_001",
        ),
    )

    inputs = await verdict_module.research_verdict_store.get_inputs(iteration.iteration_id)

    assert inputs is not None
    assert inputs.metrics["backtest_review_conclusion"] == "REVIEW_GATE_READY"
    assert "PRIMARY" not in inputs.metrics["backtest_review_conclusion"]
    backtest_evidence = next(item for item in inputs.evidence if item.source_type == "BACKTEST")
    assert backtest_evidence.quality == "MEDIUM"
    assert backtest_evidence.reported_quality == "HIGH"
    _assert_review_gate_evidence_quality(inputs.evidence)

    refreshed = await verdict_module.research_verdict_store.refresh_inputs(iteration.iteration_id)
    stored = (await research_store.get_loop_detail(detail.loop.loop_id)).iterations[0]
    assert refreshed is not None
    stored_backtest_evidence = next(item for item in stored.evidence_links if item.source_type == "BACKTEST")
    assert stored_backtest_evidence.quality == "MEDIUM"
    assert stored_backtest_evidence.reported_quality == "HIGH"


@pytest.mark.asyncio
async def test_verdict_inputs_treats_paper_trading_invalidation_as_regression(research_store):
    run = _run("RUN_PAPER_INVALID_001")
    run["paperTrading"]["triggeredInvalidation"] = True
    routes_analysis.runs_store.clear()
    routes_analysis.runs_store["RUN_PAPER_INVALID_001"] = run
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="Signal paper result",
            objective="Attach paper trading result to verdict",
            action_target="signal",
        )
    )
    iteration = await research_store.create_iteration(
        detail.loop.loop_id,
        CreateResearchIterationRequest(
            hypothesis="Paper trading invalidation should block acceptance.",
            linked_run_id="RUN_PAPER_INVALID_001",
        ),
    )

    inputs = await verdict_module.research_verdict_store.get_inputs(iteration.iteration_id)

    assert inputs is not None
    assert inputs.engine_verdict == "REGRESSED"
    assert inputs.suggested_feedback_verdict == "PATCH_REQUIRED"
    assert "paper_trading_triggered_invalidation" in inputs.quality_warnings


@pytest.mark.asyncio
async def test_refresh_verdict_inputs_preserves_terminal_status_and_dedupes_evidence(research_store):
    routes_analysis.runs_store.clear()
    routes_analysis.runs_store["RUN_REFRESH_001"] = _run("RUN_REFRESH_001")
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(title="Refresh verdict", objective="Refresh should not downgrade status")
    )
    iteration = await research_store.create_iteration(
        detail.loop.loop_id,
        CreateResearchIterationRequest(
            hypothesis="Accepted status should survive verdict input refresh.",
            linked_run_id="RUN_REFRESH_001",
        ),
    )
    accepted = await research_store.record_feedback(
        iteration.iteration_id,
        ResearchIterationFeedbackRequest(
            action="ACCEPT",
            verdict="ACCEPTED",
            status="ACCEPTED",
            linked_run_id="RUN_REFRESH_001",
        ),
    )
    assert accepted is not None

    refreshed = await verdict_module.research_verdict_store.refresh_inputs(iteration.iteration_id)
    stored = (await research_store.get_loop_detail(detail.loop.loop_id)).iterations[0]

    assert refreshed is not None
    assert stored.status == "ACCEPTED"
    assert stored.verdict == "ACCEPTED"
    assert len([item for item in refreshed.evidence if item.source_type == "RUN" and item.source_id == "RUN_REFRESH_001"]) == 1
    assert len([item for item in stored.evidence_links if item.source_type == "RUN" and item.source_id == "RUN_REFRESH_001"]) == 1
    refreshed_run_evidence = next(
        item for item in refreshed.evidence
        if item.source_type == "RUN" and item.source_id == "RUN_REFRESH_001"
    )
    stored_run_evidence = next(
        item for item in stored.evidence_links
        if item.source_type == "RUN" and item.source_id == "RUN_REFRESH_001"
    )
    assert refreshed_run_evidence.quality == "MEDIUM"
    assert refreshed_run_evidence.reported_quality == "HIGH"
    assert stored_run_evidence.quality == "MEDIUM"
    assert stored_run_evidence.reported_quality == "HIGH"
    _assert_review_gate_evidence_quality(refreshed.evidence)
    _assert_review_gate_evidence_quality(stored.evidence_links)


@pytest.mark.asyncio
async def test_verdict_inputs_reads_knowledge_from_artifact_links(research_store):
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="Knowledge verdict",
            objective="Knowledge artifacts should stay linked",
            hypothesis="Linked knowledge should be visible in verdict inputs.",
        )
    )
    iteration = detail.iterations[0]
    item = knowledge_store.create_knowledge_item(
        CreateKnowledgeItemRequest(
            category="RESEARCH_FEEDBACK",
            title="Research knowledge candidate",
            thesis="A linked knowledge candidate should appear in verdict inputs.",
            evidence=["Research Lab materialized this candidate."],
            decision_impact="Human review is required before reuse.",
            guardrail_notes=["pending review"],
            tags=[f"iteration:{iteration.iteration_id}"],
            confidence="MEDIUM",
        )
    )
    await research_store.record_feedback(
        iteration.iteration_id,
        ResearchIterationFeedbackRequest(
            action="MATERIALIZE_ARTIFACTS",
            verdict="PENDING",
            status="EVALUATED",
            metrics={"artifact_links": {"knowledge_item_id": item.item_id}},
        ),
    )

    inputs = await verdict_module.research_verdict_store.get_inputs(iteration.iteration_id)

    assert inputs is not None
    assert inputs.metrics["knowledge_status"] == "PENDING_REVIEW"
    assert inputs.metrics["knowledge_confidence"] == "MEDIUM"
    assert any(evidence.source_type == "KNOWLEDGE" and evidence.source_id == item.item_id for evidence in inputs.evidence)
    assert "Linked knowledge item is still pending review." in inputs.blocking_reasons


@pytest.mark.asyncio
async def test_verdict_inputs_route_returns_404_for_missing_iteration():
    with pytest.raises(HTTPException) as exc:
        await routes_research.research_iteration_verdict_inputs("RITER_MISSING")

    assert exc.value.status_code == 404
