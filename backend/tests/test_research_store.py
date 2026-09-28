import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.api import routes_analysis, routes_research
from app.api.routes_analysis import _update_research_iteration_from_run
from app.core import research_store as research_store_module
from app.core.auto_paper_trading import auto_paper_trading_store
from app.core.backtest_store import BacktestStore
from app.core.research_trace_adapter import MAX_TRACE_ITERATIONS
from app.core.research_store import ResearchLoopStore
from app.core.research_verdict_store import research_verdict_store
from app.core.signalops_store import signalops_store
from app.db.models_research import ResearchEvidenceLinkDB, ResearchFeedbackEventDB, ResearchIterationDB
from app.db.session import AsyncSessionLocal
from app.main import app
from app.models.research import (
    ArchiveResearchLoopRequest,
    AttachResearchBacktestRequest,
    AttachResearchRunRequest,
    CreateNextResearchIterationRequest,
    CreateResearchBacktestVerdictInputsRequest,
    CreateResearchIterationRequest,
    CreateResearchLoopRequest,
    CreateResearchSignalOpsEvidenceRequest,
    LinkedProjectRef,
    ResearchEvidenceLink,
    ResearchVerdictEvidence,
    ResearchIterationFeedbackRequest,
    CreateSampleResearchLoopRequest,
    ResearchTraceImportRequest,
    StartResearchRunRequest,
    UpdateResearchIterationRequest,
    UpdateResearchLoopRequest,
)


@pytest.fixture
def research_store():
    return ResearchLoopStore()


def _workflow_steps(detail):
    assert detail.workflow_state.evidence_usage == "review_gate_only"
    assert detail.workflow_state.evidence_strength in {"MEDIUM", "LOW", "MISSING", "PENDING", "UNKNOWN"}
    assert detail.workflow_state.evidence_strength != "SUPPORTING_ONLY"
    assert detail.workflow_state.simulation_only is True
    assert detail.workflow_state.is_real_trade is False
    assert detail.workflow_state.strong_conclusion_allowed is False
    steps = {step.key: step for step in detail.workflow_state.steps}
    for step in steps.values():
        assert step.evidence_usage == "review_gate_only"
        assert step.evidence_strength not in {"HIGH", "STRONG", "PRIMARY_EVIDENCE"}
        assert step.simulation_only is True
        assert step.is_real_trade is False
        assert step.strong_conclusion_allowed is False
    return steps


def _register_analysis_run(run_id: str, **overrides) -> dict:
    run = {
        "runId": run_id,
        "auditId": f"AUD_{run_id}",
        "status": "COMPLETED",
        "stockCode": "TEST001.SZ",
        "stockName": "Registered Test Run",
        "taskType": "research",
        "runMode": "STANDARD_MODE",
        "finalAction": "WAIT",
        "finalWriter": {"finalAction": "WAIT"},
        "compressedSummary": {"quality": {"score": 86}},
        "qiam": {"modelConfidenceFinal": 0.72},
        "dvg": {"status": "PASS"},
    }
    run.update(overrides)
    routes_analysis.runs_store[run_id] = run
    return run


async def _register_backtest_run(symbol: str = "TEST001.SZ") -> dict:
    return await BacktestStore().create_run(
        symbol=symbol,
        stock_name="Registered Backtest Run",
        start_date="2026-01-01",
        end_date="2026-01-05",
        scenario_label="registered-test-backtest",
        parameters={"data_source": "MOCK"},
        market_data=[
            {"date": "2026-01-01", "open": 10, "close": 10, "prev_close": 10},
            {"date": "2026-01-02", "open": 10.2, "close": 10.4, "prev_close": 10},
            {"date": "2026-01-05", "open": 10.4, "close": 10.6, "prev_close": 10.4},
        ],
        signals=[
            {"timestamp": "2026-01-01", "direction": "BUY", "signal_type": "BUY", "strength": 1},
        ],
        reuse_existing=False,
        force_new=True,
    )


def test_research_evidence_models_cap_strong_quality_to_review_gate():
    link = ResearchEvidenceLink(
        source_type="RUN",
        source_id="RUN_MODEL_HIGH_001",
        label="Legacy high evidence",
        quality="HIGH",
        created_at="2026-05-20T00:00:00Z",
    )
    verdict_evidence = ResearchVerdictEvidence(
        source_type="PATCH",
        source_id="PATCH_MODEL_PASS_001",
        label="Legacy pass evidence",
        quality="PASS",
        summary="legacy evidence",
        metrics={},
        created_at="2026-05-20T00:00:00Z",
    )
    warned = ResearchEvidenceLink(
        source_type="CASE",
        source_id="CASE_MODEL_WARN_001",
        label="Warning evidence",
        quality="WARN",
        created_at="2026-05-20T00:00:00Z",
    )
    research_grade = ResearchEvidenceLink(
        source_type="BACKTEST",
        source_id="BT_MODEL_RESEARCH_GRADE_001",
        label="Calculated research-grade evidence",
        quality="RESEARCH_GRADE",
        created_at="2026-05-20T00:00:00Z",
    )
    supporting_only = ResearchEvidenceLink(
        source_type="BACKTEST",
        source_id="BT_MODEL_SUPPORTING_ONLY_001",
        label="Legacy supporting-only evidence",
        quality="SUPPORTING_ONLY",
        created_at="2026-05-20T00:00:00Z",
    )

    assert link.quality == "MEDIUM"
    assert link.reported_quality == "HIGH"
    assert verdict_evidence.quality == "MEDIUM"
    assert verdict_evidence.reported_quality == "PASS"
    assert warned.quality == "LOW"
    assert warned.reported_quality == "WARN"
    assert research_grade.quality == "MEDIUM"
    assert research_grade.reported_quality == "RESEARCH_GRADE"
    assert supporting_only.quality == "LOW"
    assert supporting_only.reported_quality == "SUPPORTING_ONLY"


def test_research_store_evidence_payload_caps_research_grade_aliases():
    research_grade = research_store_module._review_gate_evidence_payload(
        {
            "source_type": "BACKTEST",
            "source_id": "BT_STORE_RESEARCH_GRADE_001",
            "label": "Legacy research-grade evidence",
            "quality": "RESEARCH_GRADE",
            "created_at": "2026-06-15T00:00:00+00:00",
        }
    )
    primary_ready = research_store_module._review_gate_evidence_payload(
        {
            "source_type": "EVALUATION",
            "source_id": "EVAL_STORE_PRIMARY_READY_001",
            "label": "Legacy primary-ready evidence",
            "quality": "PRIMARY_EVIDENCE_READY",
            "created_at": "2026-06-15T00:00:00+00:00",
        }
    )
    supporting_only = research_store_module._review_gate_evidence_payload(
        {
            "source_type": "BACKTEST",
            "source_id": "BT_STORE_SUPPORTING_ONLY_001",
            "label": "Legacy supporting-only evidence",
            "quality": "SUPPORTING_ONLY",
            "created_at": "2026-06-15T00:00:00+00:00",
        }
    )

    assert research_grade["quality"] == "MEDIUM"
    assert research_grade["reportedQuality"] == "RESEARCH_GRADE"
    assert research_grade["reported_quality"] == "RESEARCH_GRADE"
    assert primary_ready["quality"] == "MEDIUM"
    assert primary_ready["reportedQuality"] == "PRIMARY_EVIDENCE_READY"
    assert primary_ready["reported_quality"] == "PRIMARY_EVIDENCE_READY"
    assert supporting_only["quality"] == "LOW"
    assert supporting_only["reportedQuality"] == "SUPPORTING_ONLY"
    assert supporting_only["reported_quality"] == "SUPPORTING_ONLY"


def _bottom_research_run(
    run_id: str,
    loop_id: str,
    iteration_id: str,
    *,
    status: str = "PASS",
    symbol: str = "BOTTOM001.SZ",
) -> dict:
    return {
        "runId": run_id,
        "status": "COMPLETED",
        "stockCode": symbol,
        "stockName": "Bottom Research Stock",
        "rdResearch": {"loopId": loop_id, "iterationId": iteration_id},
        "bottomResearchConfig": {"repair_probability_threshold": 0.25},
        "bottomResearch": {
            "status": status,
            "bottomRepairProbability": 0.72,
            "breakdownRiskProbability": 0.18,
            "regimeState": "BOTTOM_REPAIR_ZONE",
            "modelDiagnostics": {
                "modelVersion": "bottom-research-v1",
                "sampleCount": 260,
                "evidenceGrade": "MEDIUM",
                "walkForward": {
                    "bottomRepair": {
                        "foldCount": 4,
                        "brier": 0.21,
                        "prAuc": 0.64,
                    }
                },
            },
            "provenance": {
                "modelVersion": "bottom-research-v1",
                "firstTradeDate": "2024-01-02",
                "lastTradeDate": "2025-03-31",
                "simulation_only": True,
                "is_real_trade": False,
            },
        },
        "compressedSummary": {"quality": {"score": 0, "level": ""}},
        "finalWriter": {"finalAction": "WAIT"},
        "qiam": {"modelConfidenceFinal": None},
        "dvg": {"status": "PASS"},
    }


@pytest.mark.asyncio
async def test_create_loop_with_initial_iteration_and_linked_project(research_store):
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="Factor drift research",
            objective="Validate if factor drift explains recent drawdown",
            hypothesis="Volume-price divergence improves defensive timing.",
            plan="Run guarded analysis, compress evidence, evaluate against paper results.",
            action_target="factor",
            target_modules=["factor_engine", "signalops"],
            linked_projects=[
                LinkedProjectRef(
                    project="external-strategy-lab",
                    module="factor_drift",
                    path="modules/factor_drift.py",
                    expected_version="2026.05",
                )
            ],
        )
    )
    summary = await research_store.get_summary()

    assert detail.loop.loop_id.startswith("RLOOP_")
    assert detail.loop.title == "Factor drift research"
    assert detail.loop.current_iteration_id == detail.iterations[0].iteration_id
    assert detail.iterations[0].iteration_id.startswith("RITER_")
    assert detail.iterations[0].order == 1
    assert detail.iterations[0].target_modules == ["factor_engine", "signalops"]
    assert summary.total_loops == 1
    assert summary.total_iterations == 1
    assert summary.linked_project_count == 1


@pytest.mark.asyncio
async def test_loop_detail_workflow_state_requires_first_iteration(research_store):
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="Empty workflow",
            objective="Expose the first required research workflow action",
        )
    )

    assert detail.iterations == []
    assert detail.workflow_state.stage == "no_iteration"
    assert detail.workflow_state.next_action == "create_iteration"
    assert detail.workflow_state.maturity_score == 0
    assert detail.workflow_state.maturity_level == "missing_data"
    assert detail.workflow_state.maturity_label == "Missing data"
    assert "No research iteration exists for this loop." in detail.workflow_state.maturity_reasons
    assert "No research iteration exists for this loop." in detail.workflow_state.blocking_reasons
    steps = _workflow_steps(detail)
    assert steps["iteration"].status == "WAIT"
    assert steps["iteration"].source == "research_loop"
    assert steps["iteration"].evidence_strength == "MISSING"
    assert steps["iteration"].missing_items == ["No research iteration exists for this loop."]
    assert steps["iteration"].next_action == "create_iteration"
    assert steps["portfolio"].status == "WAIT"
    assert steps["portfolio"].missing_items == ["No current research iteration."]
    assert steps["portfolio"].next_action == "create_iteration"


@pytest.mark.asyncio
async def test_loop_detail_workflow_state_points_to_missing_run_and_backtest(research_store):
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="Missing links workflow",
            objective="Guide run and backtest linking",
            hypothesis="Workflow should ask for a run before backtest.",
        )
    )

    missing_run = await research_store.get_loop_detail(detail.loop.loop_id)
    assert missing_run is not None
    assert missing_run.workflow_state.stage == "missing_run"
    assert missing_run.workflow_state.next_action == "attach_or_create_run"
    assert missing_run.workflow_state.maturity_level == "missing_data"
    assert _workflow_steps(missing_run)["run"].status == "WAIT"

    _register_analysis_run("RUN_WORKFLOW_001")
    await research_store.attach_run(
        detail.iterations[0].iteration_id,
        AttachResearchRunRequest(
            run_id="RUN_WORKFLOW_001",
            metrics={"portfolio_snapshot_id": "PF_WORKFLOW_001"},
        ),
    )
    missing_backtest = await research_store.get_loop_detail(detail.loop.loop_id)
    assert missing_backtest is not None
    assert missing_backtest.workflow_state.stage == "missing_backtest"
    assert missing_backtest.workflow_state.next_action == "attach_or_create_backtest"
    assert missing_backtest.workflow_state.maturity_level == "missing_sample"
    assert missing_backtest.workflow_state.maturity_label == "Missing sample"
    steps = _workflow_steps(missing_backtest)
    assert steps["portfolio"].status == "PASS"
    assert steps["portfolio"].source == "metrics.portfolio_snapshot_id"
    assert steps["portfolio"].evidence_strength == "MEDIUM"
    assert steps["run"].status == "PASS"
    assert steps["run"].source == "evidence_links.RUN"
    assert steps["run"].source_timestamp
    assert steps["backtest"].status == "WAIT"
    assert steps["backtest"].missing_items == ["No linked backtest for the current iteration."]
    assert steps["backtest"].next_action == "attach_or_create_backtest"
    assert "No linked backtest for the current iteration." in missing_backtest.workflow_state.blocking_reasons


@pytest.mark.asyncio
async def test_loop_detail_keeps_portfolio_evidence_link_review_only(research_store):
    run_id = "RUN_PORTFOLIO_EVIDENCE_REVIEW_ONLY_001"
    _register_analysis_run(run_id)
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="Portfolio evidence link review-only",
            objective="Portfolio evidence links must not replace imported snapshot ids.",
            hypothesis="A stored portfolio evidence link can be reviewed without satisfying portfolio readiness.",
        )
    )
    iteration = detail.iterations[0]
    await research_store.update_iteration(
        iteration.iteration_id,
        UpdateResearchIterationRequest(linked_run_id=run_id),
    )
    await research_store.record_feedback(
        iteration.iteration_id,
        ResearchIterationFeedbackRequest(
            action="ATTACH_PORTFOLIO_EVIDENCE",
            verdict="PENDING",
            evidence_links=[
                ResearchEvidenceLink(
                    source_type="PORTFOLIO_SNAPSHOT",
                    source_id="PF_FORGED_REVIEW_ONLY_001",
                    label="Forged portfolio snapshot evidence",
                    quality="HIGH",
                    created_at="2026-06-15T00:00:00+00:00",
                )
            ],
        ),
    )

    loaded = await research_store.get_loop_detail(detail.loop.loop_id)

    assert loaded is not None
    assert loaded.workflow_state.stage == "missing_portfolio_snapshot"
    assert loaded.workflow_state.next_action == "attach_portfolio_snapshot"
    steps = _workflow_steps(loaded)
    assert steps["evidence"].status == "WARN"
    assert steps["evidence"].evidence_strength == "LOW"
    assert "No imported holdings snapshot is linked; portfolio evidence remains user-input or template context." in steps["evidence"].missing_items
    assert steps["portfolio"].status == "BLOCKED"
    assert steps["portfolio"].ref_id is None
    assert steps["portfolio"].evidence_strength == "MISSING"
    assert steps["portfolio"].missing_items == [
        "No imported holdings snapshot is linked."
    ]


@pytest.mark.asyncio
async def test_workflow_source_meta_caps_high_quality_links_to_review_gate(research_store):
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="Workflow evidence cap",
            objective="Keep source meta review-only before workflow rendering",
            hypothesis="High-quality links should not become strong conclusions.",
        )
    )
    iteration = detail.iterations[0]
    iteration.evidence_links.append(
        ResearchEvidenceLink(
            source_type="RUN",
            source_id="RUN_META_HIGH_001",
            label="Raw high run evidence",
            quality="HIGH",
            created_at="2026-05-20T00:00:00Z",
        )
    )
    iteration.evidence_links.append(
        ResearchEvidenceLink(
            source_type="EVALUATION",
            source_id="EVAL_META_LOW_001",
            label="Reviewed evaluation evidence",
            quality="HIGH",
            created_at="2026-05-20T00:00:00Z",
        )
    )

    linked_meta = research_store._source_meta_for_ref(
        iteration,
        "RUN_META_HIGH_001",
        ["RUN"],
        "metrics.artifact_links",
        fallback_strength="HIGH",
    )
    fallback_meta = research_store._source_meta_for_ref(
        iteration,
        "RUN_META_FALLBACK_001",
        ["RUN"],
        "metrics.artifact_links",
        fallback_strength="HIGH",
    )
    low_canonical_meta = research_store._source_meta_for_ref(
        iteration,
        "EVAL_META_LOW_001",
        ["EVALUATION"],
        "metrics.artifact_links",
        fallback_strength="LOW",
    )

    assert linked_meta["source"] == "evidence_links.RUN"
    assert linked_meta["evidence_strength"] == "MEDIUM"
    assert fallback_meta["source"] == "metrics.artifact_links"
    assert fallback_meta["evidence_strength"] == "MEDIUM"
    assert low_canonical_meta["source"] == "evidence_links.EVALUATION"
    assert low_canonical_meta["evidence_strength"] == "LOW"


@pytest.mark.asyncio
async def test_loop_detail_sanitizes_legacy_high_evidence_links_on_read(research_store):
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="Legacy evidence read cap",
            objective="Old high-quality evidence links must be review-gated when loaded.",
            hypothesis="Legacy evidence can be audited without becoming primary evidence.",
        )
    )
    iteration = detail.iterations[0]
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ResearchIterationDB).where(ResearchIterationDB.iteration_id == iteration.iteration_id)
        )
        record = result.scalar_one()
        record.linked_run_id = "RUN_LEGACY_HIGH_001"
        record.metrics = {"artifact_links": {"run_id": "RUN_LEGACY_HIGH_001"}}
        record.evidence_links = [
            {
                "source_type": "RUN",
                "source_id": "RUN_LEGACY_HIGH_001",
                "label": "Legacy primary-looking run evidence",
                "quality": "HIGH",
                "created_at": "2026-05-20T00:00:00Z",
            }
        ]
        await db.commit()

    loaded = await research_store.get_loop_detail(detail.loop.loop_id)
    assert loaded is not None
    loaded_iteration = loaded.iterations[0]
    assert loaded_iteration.linked_run_id is None
    assert loaded_iteration.evidence_links[0].quality == "MEDIUM"
    assert loaded_iteration.evidence_links[0].reported_quality == "HIGH"
    steps = _workflow_steps(loaded)
    assert loaded.workflow_state.stage == "missing_run"
    assert steps["run"].status == "WAIT"
    assert steps["run"].ref_id is None
    assert steps["run"].evidence_strength == "MISSING"
    assert steps["run"].source == "metrics.artifact_links"
    assert steps["run"].missing_items == [
        "Linked analysis run is missing or legacy; attach a canonical analysis run."
    ]


@pytest.mark.asyncio
async def test_loop_detail_keeps_legacy_metrics_evidence_refs_review_only(research_store):
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="Legacy metrics evidence refs",
            objective="Old metrics evidence refs must not pass evidence review.",
            hypothesis="Compatibility evidence refs require first-class evidence_links before verdict review.",
        )
    )
    iteration = detail.iterations[0]
    await research_store.update_iteration(
        iteration.iteration_id,
        UpdateResearchIterationRequest(
            metrics={
                "portfolio_snapshot_id": "PF_LEGACY_METRICS_REF",
                "evidence_refs": [
                    {
                        "source_type": "BACKTEST",
                        "source_id": "BT_LEGACY_METRICS_REF_001",
                        "quality": "HIGH",
                    }
                ],
            },
        ),
    )

    loaded = await research_store.get_loop_detail(detail.loop.loop_id)

    assert loaded is not None
    steps = _workflow_steps(loaded)
    evidence_step = steps["evidence"]
    assert evidence_step.status == "WARN"
    assert evidence_step.source == "metrics.evidence_refs"
    assert evidence_step.evidence_strength == "LOW"
    assert evidence_step.next_action == "review_evidence"
    assert evidence_step.missing_items == [
        "metrics.evidence_refs are compatibility-only; attach first-class evidence_links before verdict review."
    ]
    assert "metrics.evidence_refs are compatibility-only" not in loaded.workflow_state.blocking_reasons


@pytest.mark.asyncio
async def test_loop_detail_accepts_canonical_artifact_run_ref_on_read(research_store):
    run_id = "RUN_ARTIFACT_LINK_CANONICAL_001"
    _register_analysis_run(run_id)
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="Canonical artifact run ref",
            objective="Metrics artifact links can still point to canonical runs.",
            hypothesis="A canonical artifact run ref should drive the run workflow step.",
        )
    )
    iteration = detail.iterations[0]

    await research_store.update_iteration(
        iteration.iteration_id,
        UpdateResearchIterationRequest(
            metrics={
                "artifact_links": {
                    "run_id": run_id,
                }
            },
        ),
    )

    loaded = await research_store.get_loop_detail(detail.loop.loop_id)
    assert loaded is not None
    steps = _workflow_steps(loaded)
    assert steps["run"].status == "PASS"
    assert steps["run"].ref_id == run_id
    assert steps["run"].source == "metrics.artifact_links"
    assert steps["run"].evidence_strength == "MEDIUM"


@pytest.mark.asyncio
async def test_loop_detail_rejects_missing_backtest_refs_on_read(research_store):
    run_id = "RUN_BACKTEST_READ_GUARD_001"
    backtest_id = "BT_LEGACY_MISSING_001"
    _register_analysis_run(run_id)
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="Missing backtest read guard",
            objective="Legacy backtest refs must not drive workflow readiness.",
            hypothesis="A missing backtest ref should remain a blocker.",
        )
    )
    iteration = detail.iterations[0]
    await research_store.update_iteration(
        iteration.iteration_id,
        UpdateResearchIterationRequest(
            linked_run_id=run_id,
            metrics={
                "portfolio_snapshot_id": "PF_BACKTEST_READ_GUARD",
            },
        ),
    )
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ResearchIterationDB).where(ResearchIterationDB.iteration_id == iteration.iteration_id)
        )
        record = result.scalar_one()
        record.linked_backtest_id = backtest_id
        record.metrics = {
            **(record.metrics or {}),
            "artifact_links": {"backtest_id": backtest_id},
        }
        record.evidence_links = [
            {
                "source_type": "BACKTEST",
                "source_id": backtest_id,
                "label": "Legacy backtest evidence",
                "quality": "HIGH",
                "created_at": "2026-05-20T00:00:00Z",
            }
        ]
        await db.commit()

    loaded = await research_store.get_loop_detail(detail.loop.loop_id)

    assert loaded is not None
    loaded_iteration = loaded.iterations[0]
    assert loaded_iteration.evidence_links[0].quality == "MEDIUM"
    assert loaded_iteration.evidence_links[0].reported_quality == "HIGH"
    steps = _workflow_steps(loaded)
    assert steps["run"].status == "PASS"
    assert loaded.workflow_state.stage == "missing_backtest"
    assert steps["backtest"].status == "WAIT"
    assert steps["backtest"].ref_id is None
    assert steps["backtest"].source == "research_iteration.linked_backtest_id"
    assert steps["backtest"].evidence_strength == "MISSING"
    assert steps["backtest"].missing_items == [
        "Linked backtest is missing; attach a persisted backtest run."
    ]
    evidence_step = steps["evidence"]
    assert evidence_step.status == "WARN"
    assert evidence_step.evidence_strength == "LOW"
    assert evidence_step.missing_items == [
        "Linked backtest is missing; attach a persisted backtest run."
    ]


@pytest.mark.asyncio
async def test_loop_detail_accepts_canonical_artifact_backtest_ref_on_read(research_store):
    run_id = "RUN_BACKTEST_ARTIFACT_CANONICAL_001"
    _register_analysis_run(run_id)
    backtest = await _register_backtest_run()
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="Canonical artifact backtest ref",
            objective="Metrics artifact links can still point to persisted backtests.",
            hypothesis="A persisted artifact backtest ref should drive the workflow step.",
        )
    )
    iteration = detail.iterations[0]
    await research_store.update_iteration(
        iteration.iteration_id,
        UpdateResearchIterationRequest(
            linked_run_id=run_id,
            metrics={
                "portfolio_snapshot_id": "PF_BACKTEST_ARTIFACT_CANONICAL",
                "artifact_links": {"backtest_id": backtest["run_id"]},
            },
        ),
    )

    loaded = await research_store.get_loop_detail(detail.loop.loop_id)

    assert loaded is not None
    steps = _workflow_steps(loaded)
    assert steps["run"].status == "PASS"
    assert steps["backtest"].status == "PASS"
    assert steps["backtest"].ref_id == backtest["run_id"]
    assert steps["backtest"].source == "metrics.artifact_links"
    assert steps["backtest"].evidence_strength == "MEDIUM"


@pytest.mark.asyncio
async def test_loop_detail_workflow_state_guides_evaluation_and_feedback(research_store, monkeypatch):
    async def fake_get_evaluation(eval_id: str):
        if eval_id == "EVAL_WORKFLOW_READY_001":
            return {
                "eval_id": eval_id,
                "patch_id": "PATCH_WORKFLOW_READY_001",
                "status": "COMPLETED",
                "evidence_strength": "MEDIUM",
            }
        if eval_id == "EVAL_WORKFLOW_LOW_001":
            return {
                "eval_id": eval_id,
                "patch_id": "PATCH_WORKFLOW_READY_001",
                "status": "COMPLETED",
                "evidence_strength": "LOW",
            }
        if eval_id == "EVAL_WORKFLOW_RESEARCH_GRADE_001":
            return {
                "eval_id": eval_id,
                "patch_id": "PATCH_WORKFLOW_READY_001",
                "status": "COMPLETED",
                "evidence_strength": "RESEARCH_GRADE",
            }
        return None

    monkeypatch.setattr("app.core.evaluation_store.evaluation_sandbox_store.get_evaluation", fake_get_evaluation)

    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="Artifact workflow",
            objective="Guide complete artifact links into evaluation and feedback",
            hypothesis="Complete assets should expose the next actionable step.",
        )
    )
    iteration = detail.iterations[0]
    _register_analysis_run("RUN_WORKFLOW_READY_001")
    backtest = await _register_backtest_run()
    await research_store.update_iteration(
        iteration.iteration_id,
        UpdateResearchIterationRequest(
            linked_run_id="RUN_WORKFLOW_READY_001",
            linked_backtest_id=backtest["run_id"],
            linked_case_id="CASE_WORKFLOW_READY_001",
            linked_knowledge_item_id="KNOW_WORKFLOW_READY_001",
            linked_patch_id="PATCH_WORKFLOW_READY_001",
            metrics={
                "portfolio_snapshot_id": "PF_WORKFLOW_READY_001",
                "backtest_sample_window": {"start_date": "2026-01-01", "end_date": "2026-01-05"},
                "backtest_evidence_strength": {
                    "grade": "HIGH",
                    "canSupportResearchVerdict": True,
                    "weakSample": False,
                    "researchUsage": "primary_evidence",
                },
            },
        ),
    )

    evaluable = await research_store.get_loop_detail(detail.loop.loop_id)
    assert evaluable is not None
    assert evaluable.workflow_state.stage == "missing_evaluation"
    assert evaluable.workflow_state.next_action == "evaluate_patch"
    assert evaluable.workflow_state.maturity_level == "evaluation_ready"
    assert evaluable.workflow_state.maturity_label == "Ready for evaluation"
    steps = _workflow_steps(evaluable)
    assert steps["artifacts"].status == "PASS"
    assert steps["backtest_quality"].evidence_strength == "MEDIUM"
    assert steps["evaluation"].status == "WAIT"
    assert steps["evaluation"].missing_items == ["No linked patch evaluation for the current iteration."]
    assert steps["evaluation"].next_action == "evaluate_patch"

    await research_store.update_iteration(
        iteration.iteration_id,
        UpdateResearchIterationRequest(
            metrics={
                "artifact_links": {
                    "evaluation_id": "EVAL_WORKFLOW_FORGED_001",
                },
            },
        ),
    )
    forged_evaluation = await research_store.get_loop_detail(detail.loop.loop_id)
    assert forged_evaluation is not None
    assert forged_evaluation.workflow_state.stage == "missing_evaluation"
    assert forged_evaluation.workflow_state.next_action == "evaluate_patch"
    assert any(
        "Linked patch evaluation is missing or incomplete" in reason
        for reason in forged_evaluation.workflow_state.blocking_reasons
    )
    steps = _workflow_steps(forged_evaluation)
    assert steps["evaluation"].status == "WAIT"
    assert steps["evaluation"].ref_id is None
    assert steps["evaluation"].evidence_strength == "MISSING"
    assert steps["evaluation"].missing_items == [
        "Linked patch evaluation is missing or incomplete."
    ]

    await research_store.update_iteration(
        iteration.iteration_id,
        UpdateResearchIterationRequest(
            metrics={
                "artifact_links": {
                    "evaluation_id": "EVAL_WORKFLOW_READY_001",
                },
            },
        ),
    )
    knowledge_ready = await research_store.get_loop_detail(detail.loop.loop_id)
    assert knowledge_ready is not None
    assert knowledge_ready.workflow_state.stage == "missing_knowledge_version"
    assert knowledge_ready.workflow_state.next_action == "promote_knowledge_version"
    assert knowledge_ready.workflow_state.maturity_level == "knowledge_ready"
    assert knowledge_ready.workflow_state.maturity_label == "Ready to publish knowledge version"

    await research_store.update_iteration(
        iteration.iteration_id,
        UpdateResearchIterationRequest(
            metrics={
                "artifact_links": {
                    "evaluation_id": "EVAL_WORKFLOW_LOW_001",
                },
            },
        ),
    )
    low_evaluation = await research_store.get_loop_detail(detail.loop.loop_id)
    assert low_evaluation is not None
    assert low_evaluation.workflow_state.stage == "missing_knowledge_version"
    steps = _workflow_steps(low_evaluation)
    assert steps["evaluation"].status == "PASS"
    assert steps["evaluation"].ref_id == "EVAL_WORKFLOW_LOW_001"
    assert steps["evaluation"].evidence_strength == "LOW"

    await research_store.update_iteration(
        iteration.iteration_id,
        UpdateResearchIterationRequest(
            metrics={
                "artifact_links": {
                    "evaluation_id": "EVAL_WORKFLOW_RESEARCH_GRADE_001",
                },
            },
        ),
    )
    research_grade_evaluation = await research_store.get_loop_detail(detail.loop.loop_id)
    assert research_grade_evaluation is not None
    steps = _workflow_steps(research_grade_evaluation)
    assert steps["evaluation"].status == "PASS"
    assert steps["evaluation"].ref_id == "EVAL_WORKFLOW_RESEARCH_GRADE_001"
    assert steps["evaluation"].evidence_strength == "MEDIUM"

    await research_store.update_iteration(
        iteration.iteration_id,
        UpdateResearchIterationRequest(
            metrics={
                "artifact_links": {
                    "evaluation_id": "EVAL_WORKFLOW_READY_001",
                    "knowledge_version_id": "KVER_WORKFLOW_READY_001",
                },
                "can_accept_feedback": True,
            },
        ),
    )
    missing_version_status = await research_store.get_loop_detail(detail.loop.loop_id)
    assert missing_version_status is not None
    assert missing_version_status.workflow_state.stage == "review_knowledge_version"
    assert missing_version_status.workflow_state.next_action == "review_knowledge_version"
    assert any(
        "Knowledge version status is missing" in reason
        for reason in missing_version_status.workflow_state.blocking_reasons
    )
    steps = _workflow_steps(missing_version_status)
    assert steps["knowledge_version"].status == "WARN"
    assert steps["knowledge_version"].evidence_strength == "MEDIUM"
    assert steps["knowledge_version"].missing_items == [
        "Knowledge version status is missing and cannot activate feedback acceptance."
    ]
    assert steps["feedback"].status == "WAIT"
    assert steps["feedback"].evidence_strength == "MISSING"
    assert steps["feedback"].next_action == "review_knowledge_version"

    await research_store.update_iteration(
        iteration.iteration_id,
        UpdateResearchIterationRequest(
            metrics={
                "artifact_links": {
                    "evaluation_id": "EVAL_WORKFLOW_READY_001",
                    "knowledge_version_id": "KVER_WORKFLOW_READY_001",
                    "knowledge_version_status": "review",
                },
                "can_accept_feedback": True,
            },
        ),
    )
    review_version = await research_store.get_loop_detail(detail.loop.loop_id)
    assert review_version is not None
    assert review_version.workflow_state.stage == "review_knowledge_version"
    assert review_version.workflow_state.next_action == "review_knowledge_version"
    assert review_version.workflow_state.maturity_level == "knowledge_ready"
    assert any("cannot activate feedback acceptance" in reason for reason in review_version.workflow_state.blocking_reasons)
    steps = _workflow_steps(review_version)
    assert steps["knowledge_version"].status == "WARN"
    assert steps["knowledge_version"].next_action == "review_knowledge_version"
    assert steps["feedback"].status == "WAIT"
    assert steps["feedback"].evidence_strength == "MISSING"
    assert steps["feedback"].next_action == "review_knowledge_version"

    await research_store.update_iteration(
        iteration.iteration_id,
        UpdateResearchIterationRequest(
            metrics={
                "artifact_links": {
                    "evaluation_id": "EVAL_WORKFLOW_READY_001",
                    "knowledge_version_id": "KVER_WORKFLOW_READY_001",
                    "knowledge_version_status": "active",
                },
                "knowledge_version_status": "active",
                "suggested_feedback_verdict": "ACCEPTED",
                "can_accept_feedback": False,
            },
        ),
    )
    suggested_only = await research_store.get_loop_detail(detail.loop.loop_id)
    assert suggested_only is not None
    assert suggested_only.workflow_state.stage == "needs_feedback_decision"
    assert suggested_only.workflow_state.next_action == "send_to_feedback"
    steps = _workflow_steps(suggested_only)
    assert steps["feedback"].status == "WAIT"
    assert steps["feedback"].evidence_strength == "MISSING"
    assert steps["feedback"].missing_items == ["Feedback acceptance is not ready."]
    assert steps["feedback"].next_action == "send_to_feedback"

    await research_store.update_iteration(
        iteration.iteration_id,
        UpdateResearchIterationRequest(
            metrics={
                "artifact_links": {
                    "evaluation_id": "EVAL_WORKFLOW_READY_001",
                    "knowledge_version_id": "KVER_WORKFLOW_READY_001",
                    "knowledge_version_status": "active",
                },
                "knowledge_version_status": "active",
                "can_accept_feedback": True,
            },
        ),
    )
    feedback_ready = await research_store.get_loop_detail(detail.loop.loop_id)
    assert feedback_ready is not None
    assert feedback_ready.workflow_state.stage == "feedback_ready"
    assert feedback_ready.workflow_state.next_action == "accept_feedback"
    assert feedback_ready.workflow_state.maturity_level == "feedback_ready"
    assert feedback_ready.workflow_state.blocking_reasons == []
    steps = _workflow_steps(feedback_ready)
    assert steps["evaluation"].status == "PASS"
    assert steps["evaluation"].source == "metrics.artifact_links"
    assert steps["knowledge_version"].status == "PASS"
    assert steps["knowledge_version"].source == "metrics.artifact_links"
    assert steps["feedback"].status == "READY"
    assert steps["feedback"].evidence_strength == "MEDIUM"
    assert steps["feedback"].next_action == "accept_feedback"


@pytest.mark.asyncio
async def test_loop_detail_keeps_artifact_evidence_links_review_only(research_store):
    run_id = "RUN_ARTIFACT_EVIDENCE_REVIEW_ONLY_001"
    _register_analysis_run(run_id)
    backtest = await _register_backtest_run()
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="Artifact evidence links review-only",
            objective="Evidence links must not replace materialized artifact ids.",
            hypothesis="Stored artifact evidence can be reviewed without making artifacts ready.",
        )
    )
    iteration = detail.iterations[0]
    await research_store.update_iteration(
        iteration.iteration_id,
        UpdateResearchIterationRequest(
            linked_run_id=run_id,
            linked_backtest_id=backtest["run_id"],
            metrics={
                "portfolio_snapshot_id": "PF_ARTIFACT_EVIDENCE_REVIEW_ONLY",
                "backtest_sample_window": {"start_date": "2026-01-01", "end_date": "2026-01-05"},
                "backtest_evidence_strength": {
                    "grade": "HIGH",
                    "canSupportResearchVerdict": True,
                    "weakSample": False,
                    "researchUsage": "primary_evidence",
                },
            },
        ),
    )
    await research_store.record_feedback(
        iteration.iteration_id,
        ResearchIterationFeedbackRequest(
            action="ATTACH_ARTIFACT_EVIDENCE",
            verdict="PENDING",
            evidence_links=[
                ResearchEvidenceLink(
                    source_type="CASE",
                    source_id="CASE_FORGED_REVIEW_ONLY_001",
                    label="Forged case evidence",
                    quality="LOW",
                    created_at="2026-06-15T00:00:00+00:00",
                ),
                ResearchEvidenceLink(
                    source_type="KNOWLEDGE",
                    source_id="KNOW_FORGED_REVIEW_ONLY_001",
                    label="Forged knowledge evidence",
                    quality="HIGH",
                    created_at="2026-06-15T00:00:00+00:00",
                ),
                ResearchEvidenceLink(
                    source_type="PATCH",
                    source_id="PATCH_FORGED_REVIEW_ONLY_001",
                    label="Forged patch evidence",
                    quality="HIGH",
                    created_at="2026-06-15T00:00:00+00:00",
                ),
            ],
        ),
    )

    loaded = await research_store.get_loop_detail(detail.loop.loop_id)

    assert loaded is not None
    assert loaded.workflow_state.stage == "missing_artifacts"
    steps = _workflow_steps(loaded)
    assert steps["evidence"].status == "PASS"
    assert steps["evidence"].evidence_strength == "LOW"
    assert steps["artifacts"].status == "WAIT"
    assert steps["artifacts"].ref_id is None
    assert steps["artifacts"].missing_items == [
        "No linked research case.",
        "No linked knowledge item.",
        "No linked patch candidate.",
    ]


@pytest.mark.asyncio
async def test_loop_detail_conflicting_backtest_support_flags_block_feedback(research_store):
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="Conflicting backtest evidence flags",
            objective="Do not promote weak backtest evidence when aliases disagree.",
            hypothesis="Conflicting canSupport aliases must remain review gated.",
        )
    )
    iteration = detail.iterations[0]

    _register_analysis_run("RUN_CONFLICTING_BT_FLAGS_001")
    backtest = await _register_backtest_run()
    await research_store.update_iteration(
        iteration.iteration_id,
        UpdateResearchIterationRequest(
            linked_run_id="RUN_CONFLICTING_BT_FLAGS_001",
            linked_backtest_id=backtest["run_id"],
            linked_case_id="CASE_CONFLICTING_FLAGS_001",
            linked_knowledge_item_id="KNOW_CONFLICTING_FLAGS_001",
            linked_patch_id="PATCH_CONFLICTING_FLAGS_001",
            metrics={
                "portfolio_snapshot_id": "PF_CONFLICTING_FLAGS_001",
                "backtest_sample_window": {"start_date": "2026-01-01", "end_date": "2026-01-05"},
                "backtest_evidence_strength": {
                    "grade": "HIGH",
                    "canSupportResearchVerdict": False,
                    "can_support_research_verdict": True,
                    "weakSample": False,
                    "weak_sample": False,
                    "researchUsage": "primary_evidence",
                    "research_usage": "primary_evidence",
                },
                "artifact_links": {
                    "evaluation_id": "EVAL_CONFLICTING_FLAGS_001",
                    "knowledge_version_id": "KVER_CONFLICTING_FLAGS_001",
                    "knowledge_version_status": "active",
                },
                "knowledge_version_status": "active",
                "can_accept_feedback": True,
            },
        ),
    )

    blocked = await research_store.get_loop_detail(detail.loop.loop_id)

    assert blocked is not None
    assert blocked.workflow_state.stage == "needs_evidence_review"
    assert blocked.workflow_state.next_action == "review_evidence"
    assert any("canSupportResearchVerdict" in reason for reason in blocked.workflow_state.blocking_reasons)
    steps = _workflow_steps(blocked)
    assert steps["backtest_quality"].status == "WARN"
    assert steps["feedback"].status == "WAIT"
    assert steps["feedback"].next_action == "send_to_feedback"


@pytest.mark.asyncio
async def test_create_iteration_and_record_feedback_updates_loop(research_store):
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="Execution review",
            objective="Reduce simulated execution regressions",
        )
    )
    _register_analysis_run("RUN_TEST_001")
    iteration = await research_store.create_iteration(
        detail.loop.loop_id,
        CreateResearchIterationRequest(
            hypothesis="Slippage cap should be stricter for low-liquidity cases.",
            plan="Compare execution node results with SignalOps paper fills.",
            linked_run_id="RUN_TEST_001",
            metrics={"baseline_slippage": 0.012},
        ),
    )
    assert iteration is not None

    reviewed = await research_store.record_feedback(
        iteration.iteration_id,
        ResearchIterationFeedbackRequest(
            action="ACCEPT",
            verdict="ACCEPTED",
            note="Evidence supports the stricter cap.",
            linked_case_id="CASE_001",
            metrics={"improvement_rate": 0.25},
            evidence_links=[
                ResearchEvidenceLink(
                    source_type="RUN",
                    source_id="RUN_TEST_001",
                    label="Initial run evidence",
                    quality="HIGH",
                    created_at="2026-05-19T00:00:00Z",
                )
            ],
        ),
    )
    reviewed_again = await research_store.record_feedback(
        iteration.iteration_id,
        ResearchIterationFeedbackRequest(
            action="REFRESH",
            verdict="ACCEPTED",
            evidence_links=[
                ResearchEvidenceLink(
                    source_type="RUN",
                    source_id="RUN_TEST_001",
                    label="Refreshed run evidence",
                    quality="HIGH",
                    created_at="2026-05-19T00:01:00Z",
                )
            ],
        ),
    )
    assert reviewed is not None
    assert reviewed_again is not None
    updated_loop = (await research_store.get_loop_detail(detail.loop.loop_id)).loop
    summary = await research_store.get_summary()

    assert reviewed.status == "ACCEPTED"
    assert reviewed.verdict == "ACCEPTED"
    assert reviewed.linked_run_id == "RUN_TEST_001"
    assert reviewed.linked_case_id == "CASE_001"
    assert reviewed.metrics["baseline_slippage"] == 0.012
    assert reviewed.metrics["improvement_rate"] == 0.25
    assert len(reviewed_again.evidence_links) == 1
    assert reviewed_again.evidence_links[0].label == "Refreshed run evidence"
    assert updated_loop.current_iteration_id == iteration.iteration_id
    assert summary.accepted_iterations == 1


@pytest.mark.asyncio
async def test_research_routes_validate_missing_loop():
    created = await routes_research.create_research_loop_route(
        CreateResearchLoopRequest(
            title="Knowledge feedback loop",
            objective="Connect accepted cases back to knowledge versions",
            hypothesis="Reviewed cases improve patch acceptance quality.",
        )
    )
    loops = await routes_research.research_loops()
    iterations = await routes_research.research_iterations(loop_id=created.loop.loop_id)

    assert loops[0].loop_id == created.loop.loop_id
    assert iterations[0].loop_id == created.loop.loop_id

    with pytest.raises(HTTPException) as exc_info:
        await routes_research.create_research_iteration_route(
            "MISSING_LOOP",
            CreateResearchIterationRequest(hypothesis="Missing loop should fail"),
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_analysis_run_update_links_research_iteration(research_store):
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="Run linkage",
            objective="Attach a guarded run to a research iteration",
            hypothesis="A guarded run should update iteration provenance.",
        )
    )
    iteration = detail.iterations[0]
    _register_analysis_run("RUN_RESEARCH_001")
    await _update_research_iteration_from_run(
        {
            "runId": "RUN_RESEARCH_001",
            "status": "COMPLETED",
            "rdResearch": {
                "loopId": detail.loop.loop_id,
                "iterationId": iteration.iteration_id,
            },
            "finalWriter": {"finalAction": "WAIT"},
            "compressedSummary": {"quality": {"score": 86}},
            "qiam": {"modelConfidenceFinal": 0.72},
            "dvg": {"status": "PASS"},
        },
        action="RUN_COMPLETED",
        status="RUN_COMPLETED",
        note="completed",
    )
    updated = (await research_store.get_loop_detail(detail.loop.loop_id)).iterations[0]

    assert updated.linked_run_id == "RUN_RESEARCH_001"
    assert updated.status == "RUN_COMPLETED"
    assert updated.metrics["quality_score"] == 86
    assert updated.metrics["final_action"] == "WAIT"


@pytest.mark.asyncio
async def test_bottom_research_run_completion_auto_links_backtest_idempotently(monkeypatch, research_store):
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="Bottom Research closure",
            objective="Create supporting Bottom Research backtest evidence",
            hypothesis="Bottom Research output should close into Research Lab evidence.",
        )
    )
    iteration = detail.iterations[0]
    calls: list[dict] = []
    backtest_run = {
        "run_id": "BT_BOTTOM_AUTO_001",
        "status": "COMPLETED",
        "parameters": {
            "backtest_fingerprint": "fp-bottom",
            "dedupe_reused": False,
            "bottom_research_signal_hash": "SIG_BOTTOM_HASH",
            "bottom_research_signal_count": 5,
            "signal_source": "BOTTOM_RESEARCH",
        },
        "report": {
            "signal_source": "BOTTOM_RESEARCH",
            "total_return_pct": 1.2,
            "hit_rate": 0.5,
            "max_drawdown_pct": 0.04,
            "evidenceStrength": {
                "grade": "HIGH",
                "canSupportResearchVerdict": True,
                "researchUsage": "primary_evidence",
                "weakSample": False,
            },
            "provenance": {"bottomResearchVersion": "bottom-research-v1"},
        },
        "updated_at": "2026-05-20T00:00:00+00:00",
    }

    async def fake_create_run(**kwargs):
        calls.append(kwargs)
        return {
            **backtest_run,
            "parameters": {
                **backtest_run["parameters"],
                "dedupe_reused": len(calls) > 1,
            },
        }

    async def fake_get_run(run_id: str):
        return backtest_run if run_id == backtest_run["run_id"] else None

    monkeypatch.setattr("app.core.research_store.backtest_store.create_run", fake_create_run)
    monkeypatch.setattr("app.core.research_store.backtest_store.get_run", fake_get_run)

    run = _bottom_research_run("RUN_BOTTOM_AUTO_001", detail.loop.loop_id, iteration.iteration_id)
    routes_analysis.runs_store[run["runId"]] = run
    await _update_research_iteration_from_run(
        run,
        action="RUN_COMPLETED",
        status="RUN_COMPLETED",
        note="completed",
    )
    await research_store.close_bottom_research_backtest(
        iteration.iteration_id,
        run_id=run["runId"],
        run_data=run,
    )
    updated = (await research_store.get_loop_detail(detail.loop.loop_id)).iterations[0]

    assert calls
    assert calls[0]["reuse_existing"] is True
    assert calls[0]["force_new"] is False
    assert calls[0]["start_date"] == "2024-01-02"
    assert calls[0]["end_date"] == "2025-03-31"
    assert calls[0]["parameters"]["signal_source"] == "MFE_MAE_PATH_RESEARCH"
    assert calls[0]["parameters"]["data_source"] == "AUTO"
    assert calls[0]["parameters"]["bottom_research_config"]["marketProfile"]["market"] == "CN_A"
    assert calls[0]["parameters"]["bottom_research_config"]["mae_avoid_pct"] == pytest.approx(0.105)
    assert updated.linked_run_id == "RUN_BOTTOM_AUTO_001"
    assert updated.linked_backtest_id == "BT_BOTTOM_AUTO_001"
    assert updated.metrics["bottom_repair_probability"] == 0.72
    assert updated.metrics["breakdown_risk_probability"] == 0.18
    assert updated.metrics["bottom_research_brier"] == 0.21
    assert updated.metrics["bottom_research_pr_auc"] == 0.64
    assert updated.metrics["bottom_research_fold_count"] == 4
    assert updated.metrics["bottom_research_signal_hash"] == "SIG_BOTTOM_HASH"
    assert updated.metrics["bottom_research_signal_count"] == 5
    assert updated.metrics["bottom_research_supporting_only"] is True
    assert updated.metrics["simulation_only"] is True
    assert updated.metrics["is_real_trade"] is False
    assert len([item for item in updated.evidence_links if item.source_type == "MFE_MAE_RESEARCH_RUN"]) == 1
    assert len([item for item in updated.evidence_links if item.source_type == "BACKTEST"]) == 1
    backtest_link = next(item for item in updated.evidence_links if item.source_type == "BACKTEST")
    assert backtest_link.quality == "MEDIUM"
    assert backtest_link.reported_quality == "HIGH"

    async with AsyncSessionLocal() as db:
        count = (
            await db.execute(
                select(func.count())
                .select_from(ResearchEvidenceLinkDB)
                .where(ResearchEvidenceLinkDB.iteration_id == iteration.iteration_id)
            )
        ).scalar_one()
    assert count == 2


@pytest.mark.asyncio
async def test_bottom_research_backtest_failure_records_warning(monkeypatch, research_store):
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="Bottom Research failure",
            objective="Keep run completion stable when backtest fails",
            hypothesis="Backtest errors should be warnings.",
        )
    )
    iteration = detail.iterations[0]

    async def fake_create_run(**kwargs):
        raise RuntimeError("backtest unavailable")

    monkeypatch.setattr("app.core.research_store.backtest_store.create_run", fake_create_run)
    run = _bottom_research_run("RUN_BOTTOM_FAIL_001", detail.loop.loop_id, iteration.iteration_id)

    updated = await research_store.close_bottom_research_backtest(
        iteration.iteration_id,
        run_id=run["runId"],
        run_data=run,
    )

    assert updated is not None
    assert updated.linked_backtest_id is None
    assert updated.metrics["mfe_mae_research_backtest_warning"] == "mfe_mae_research_backtest_error"
    assert "backtest unavailable" in updated.metrics["mfe_mae_research_backtest_error"]
    assert "mfe_mae_research_backtest_error" in updated.metrics["warnings"]


@pytest.mark.asyncio
async def test_bottom_research_skipped_output_records_warning_without_backtest(monkeypatch, research_store):
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="Bottom Research skipped",
            objective="Skip unusable Bottom Research output",
            hypothesis="Skipped output should not create a backtest.",
        )
    )
    iteration = detail.iterations[0]
    calls: list[dict] = []

    async def fake_create_run(**kwargs):
        calls.append(kwargs)
        return {}

    monkeypatch.setattr("app.core.research_store.backtest_store.create_run", fake_create_run)
    run = _bottom_research_run("RUN_BOTTOM_SKIP_001", detail.loop.loop_id, iteration.iteration_id, status="SKIPPED")

    updated = await research_store.close_bottom_research_backtest(
        iteration.iteration_id,
        run_id=run["runId"],
        run_data=run,
    )

    assert updated is not None
    assert calls == []
    assert updated.linked_backtest_id is None
    assert updated.metrics["mfe_mae_research_backtest_warning"] == "mfe_mae_research_status_not_usable:SKIPPED"


@pytest.mark.asyncio
async def test_bottom_research_backtest_route_missing_iteration_or_run_returns_404(research_store):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        missing_iteration = await client.post(
            "/api/research/iterations/RITER_MISSING/bottom-research/backtest",
            json={"run_id": "RUN_MISSING"},
        )

        detail = await research_store.create_loop(
            CreateResearchLoopRequest(
                title="Bottom Research missing run",
                objective="Missing linked run should stay a 404.",
                hypothesis="Retry cannot proceed without a run.",
            )
        )
        missing_run = await client.post(
            f"/api/research/iterations/{detail.iterations[0].iteration_id}/bottom-research/backtest",
            json={"run_id": "RUN_MISSING"},
        )

    assert missing_iteration.status_code == 404
    assert missing_run.status_code == 404


@pytest.mark.asyncio
async def test_bottom_research_backtest_route_records_warning_for_unlinked_run(research_store):
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="Bottom Research unlinked run",
            objective="Warn instead of failing when the run belongs elsewhere.",
            hypothesis="Retry should stay observable for unlinked runs.",
        )
    )
    iteration = detail.iterations[0]
    run = _bottom_research_run("RUN_BOTTOM_UNLINKED_001", detail.loop.loop_id, "RITER_OTHER")
    routes_analysis.runs_store[run["runId"]] = run

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            f"/api/research/iterations/{iteration.iteration_id}/bottom-research/backtest",
            json={"run_id": run["runId"], "reviewer": "route-test"},
        )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["linked_backtest_id"] is None
    assert data["metrics"]["bottom_research_backtest_warning"] == "run_not_linked_to_research_iteration"
    assert data["metrics"]["bottom_research_supporting_only"] is True
    assert data["metrics"]["simulation_only"] is True
    assert data["metrics"]["is_real_trade"] is False


@pytest.mark.asyncio
async def test_bottom_research_backtest_route_records_warning_for_missing_bottom_output(research_store):
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="Bottom Research missing output",
            objective="Warn instead of failing when Bottom output is absent.",
            hypothesis="Retry should expose missing bottomResearch.",
        )
    )
    iteration = detail.iterations[0]
    run = _bottom_research_run("RUN_BOTTOM_MISSING_001", detail.loop.loop_id, iteration.iteration_id)
    run.pop("bottomResearch")
    routes_analysis.runs_store[run["runId"]] = run

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            f"/api/research/iterations/{iteration.iteration_id}/bottom-research/backtest",
            json={"run_id": run["runId"], "reviewer": "route-test"},
        )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["linked_backtest_id"] is None
    assert data["metrics"]["mfe_mae_research_backtest_warning"] == "mfe_mae_research_status_not_usable:MISSING"
    assert data["metrics"]["bottom_research_supporting_only"] is True
    assert data["metrics"]["simulation_only"] is True
    assert data["metrics"]["is_real_trade"] is False


@pytest.mark.asyncio
async def test_bottom_research_backtest_route_passes_force_new_and_dedupes_evidence(monkeypatch, research_store):
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="Bottom Research route force",
            objective="Route passes force_new and keeps evidence idempotent.",
            hypothesis="Repeated retry should not duplicate evidence links.",
        )
    )
    iteration = detail.iterations[0]
    run = _bottom_research_run("RUN_BOTTOM_ROUTE_FORCE_001", detail.loop.loop_id, iteration.iteration_id)
    routes_analysis.runs_store[run["runId"]] = run
    calls: list[dict] = []
    backtest_run = {
        "run_id": "BT_BOTTOM_ROUTE_FORCE_001",
        "status": "COMPLETED",
        "parameters": {
            "signal_source": "BOTTOM_RESEARCH",
            "bottom_research_signal_hash": "SIG_ROUTE_HASH",
            "bottom_research_signal_count": 3,
        },
        "report": {
            "signal_source": "BOTTOM_RESEARCH",
            "total_return_pct": 0.8,
            "hit_rate": 0.5,
            "max_drawdown_pct": 0.03,
            "evidenceStrength": {
                "grade": "LOW",
                "canSupportResearchVerdict": False,
                "researchUsage": "supporting_only",
            },
            "provenance": {"bottomResearchVersion": "bottom-research-v1"},
        },
        "updated_at": "2026-05-20T00:00:00+00:00",
    }

    async def fake_create_run(**kwargs):
        calls.append(kwargs)
        return backtest_run

    async def fake_get_run(run_id: str):
        return backtest_run if run_id == backtest_run["run_id"] else None

    monkeypatch.setattr("app.core.research_store.backtest_store.create_run", fake_create_run)
    monkeypatch.setattr("app.core.research_store.backtest_store.get_run", fake_get_run)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        first = await client.post(
            f"/api/research/iterations/{iteration.iteration_id}/mfe-mae/backtest",
            json={"run_id": run["runId"], "force_new": True, "reviewer": "route-test"},
        )
        second = await client.post(
            f"/api/research/iterations/{iteration.iteration_id}/mfe-mae/backtest",
            json={"run_id": run["runId"], "reviewer": "route-test"},
        )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert calls[0]["force_new"] is True
    assert calls[1]["force_new"] is False
    data = second.json()
    assert data["linked_backtest_id"] == "BT_BOTTOM_ROUTE_FORCE_001"
    assert data["metrics"]["bottom_research_supporting_only"] is True
    assert data["metrics"]["simulation_only"] is True
    assert data["metrics"]["is_real_trade"] is False
    assert len([item for item in data["evidence_links"] if item["source_type"] == "MFE_MAE_RESEARCH_RUN"]) == 1
    assert len([item for item in data["evidence_links"] if item["source_type"] == "BACKTEST"]) == 1

    async with AsyncSessionLocal() as db:
        count = (
            await db.execute(
                select(func.count())
                .select_from(ResearchEvidenceLinkDB)
                .where(ResearchEvidenceLinkDB.iteration_id == iteration.iteration_id)
            )
        ).scalar_one()
    assert count == 2


@pytest.mark.asyncio
async def test_start_research_run_passes_mfe_mae_config_market_profile_and_quant_mode(monkeypatch, research_store):
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="Bottom Research start",
            objective="Start an MFE/MAE Path Research run from Research Lab",
            hypothesis="MFE/MAE starts should use low-frequency mode and market-aware config.",
        )
    )
    iteration = detail.iterations[0]
    captured = {}

    async def fake_create_analysis_run(request):
        captured["request"] = request
        return type("Response", (), {"run_id": "RUN_STARTED_BOTTOM", "status": "CREATED", "stream_url": "/stream"})()

    monkeypatch.setattr(routes_analysis, "create_analysis_run", fake_create_analysis_run)

    response = await routes_research.start_research_iteration_run_route(
        iteration.iteration_id,
        StartResearchRunRequest(
            symbol="0700.HK",
            task_type="mfe_mae_path_research",
            bottom_research_config={"repair_probability_threshold": 0.2},
        ),
    )

    request = captured["request"]
    assert response.run_id == "RUN_STARTED_BOTTOM"
    assert request.quant_engine_mode == "LOW_FREQ_MID_LONG"
    assert request.run_mode == "STANDARD_MODE"
    assert request.bottom_research_config["repair_probability_threshold"] == 0.2
    assert request.bottom_research_config["lookback_range"] == "2y"
    assert request.bottom_research_config["marketProfile"]["market"] == "HK"
    assert request.bottom_research_config["mae_avoid_pct"] == pytest.approx(0.14)
    assert request.research_iteration_id == iteration.iteration_id

    chinese_task_request = routes_research._research_iteration_analysis_request(
        StartResearchRunRequest(
            symbol="7203.T",
            task_type="\u9636\u6bb5\u5e95\u90e8\u7814\u7a76",
            run_mode="FAST_MODE",
        ),
        detail.loop.loop_id,
        iteration.iteration_id,
    )
    assert chinese_task_request.quant_engine_mode == "LOW_FREQ_MID_LONG"
    assert chinese_task_request.run_mode == "STANDARD_MODE"
    assert chinese_task_request.bottom_research_config["lookback_range"] == "2y"
    assert chinese_task_request.bottom_research_config["marketProfile"]["market"] == "JP"
    assert chinese_task_request.bottom_research_config["mae_avoid_pct"] == pytest.approx(0.11)


@pytest.mark.asyncio
async def test_create_sample_loop_from_latest_run_links_weak_backtest_without_accepting(monkeypatch, research_store):
    run_id = "RUN_SAMPLE_RESEARCH_001"
    run = {
        "runId": run_id,
        "status": "COMPLETED",
        "stockCode": "SAMPLE001.SZ",
        "stockName": "Sample Stock",
        "taskType": "research_iteration",
        "runMode": "STANDARD_MODE",
        "createdAt": "2026-05-20T01:00:00+00:00",
        "updatedAt": "2026-05-20T01:05:00+00:00",
        "compressedSummary": {"quality": {"score": 92, "level": "HIGH"}},
        "finalWriter": {"finalAction": "BUY"},
        "qiam": {"modelConfidenceFinal": 0.78},
        "dvg": {"status": "PASS"},
        "signalOps": {
            "signalStatus": "QUALIFIED",
            "riskPassed": True,
            "dvgPassed": True,
            "qiamPassed": True,
            "executionReachable": True,
            "triggerConditions": ["breakout"],
            "invalidationConditions": ["close below support"],
            "blockedReason": "",
        },
        "portfolio": {
            "portfolioCoverage": "HOLDINGS_CONNECTED",
            "snapshotId": "PF_SAMPLE_RESEARCH_001",
            "holdings": [{"symbol": "SAMPLE001.SZ", "quantity": 100}],
        },
        "portfolioSnapshot": {
            "snapshotId": "PF_SAMPLE_RESEARCH_001",
            "updatedAt": "2026-05-20T01:04:00+00:00",
            "positions": [{"symbol": "SAMPLE001.SZ", "quantity": 100}],
        },
    }
    monkeypatch.setitem(routes_analysis.runs_store, run_id, run)

    response = await research_store.create_sample_loop_from_latest_run(
        CreateSampleResearchLoopRequest(symbol="SAMPLE001.SZ", reviewer="tester", force_backtest=True)
    )

    assert response.created is True
    assert response.detail is not None
    iteration = response.detail.iterations[0]
    assert iteration.linked_run_id == run_id
    assert iteration.linked_backtest_id
    assert iteration.metrics["sample_loop"] is True
    assert iteration.metrics["backtest_created"] is True
    assert iteration.metrics["backtest_evidence_strength"]["canSupportResearchVerdict"] is False
    assert "weak-evidence" in response.detail.loop.tags
    run_link = next(item for item in iteration.evidence_links if item.source_type == "RUN")
    assert run_link.quality == "MEDIUM"
    assert run_link.reported_quality == "HIGH"
    portfolio_link = next(item for item in iteration.evidence_links if item.source_type == "PORTFOLIO_SNAPSHOT")
    assert portfolio_link.quality == "MEDIUM"
    assert portfolio_link.reported_quality == "HIGH"
    assert any(item.source_type == "BACKTEST" and item.quality == "LOW" for item in iteration.evidence_links)
    assert any("Backtest uses mock or fallback market data" in reason for reason in response.missing_reasons)

    verdict_inputs = await research_verdict_store.get_inputs(iteration.iteration_id)
    assert verdict_inputs is not None
    assert verdict_inputs.can_accept_feedback is False
    assert verdict_inputs.suggested_feedback_verdict == "PENDING"
    assert any("BACKTEST" in warning for warning in verdict_inputs.quality_warnings)


@pytest.mark.asyncio
async def test_attach_backtest_records_baseline_candidate_contract_and_supporting_only(monkeypatch, research_store):
    run_id = "RUN_RESEARCH_BT_PAIR_001"
    monkeypatch.setitem(
        routes_analysis.runs_store,
        run_id,
        {
            "runId": run_id,
            "status": "COMPLETED",
            "stockCode": "BTPAIR.SZ",
            "updatedAt": "2026-05-20T02:00:00+00:00",
            "compressedSummary": {"quality": {"score": 90, "level": "HIGH"}},
            "finalWriter": {"finalAction": "WAIT"},
            "qiam": {"modelConfidenceFinal": 0.8},
            "dvg": {"status": "PASS"},
            "signalOps": {"signalStatus": "QUALIFIED", "blockedReason": ""},
        },
    )

    backtest_store = BacktestStore()
    market_data = [
        {"date": "2026-01-01", "open": 10, "close": 10, "prev_close": 10},
        {"date": "2026-01-02", "open": 10.1, "close": 10.3, "prev_close": 10},
        {"date": "2026-01-05", "open": 10.3, "close": 10.6, "prev_close": 10.3},
    ]
    signals = [
        {"timestamp": "2026-01-01", "direction": "BUY", "signal_type": "BUY", "strength": 1},
    ]
    baseline = await backtest_store.create_run(
        symbol="BTPAIR.SZ",
        start_date="2026-01-01",
        end_date="2026-01-05",
        parameters={
            "benchmark_symbol": "000300.SH",
            "out_of_sample_start": "2026-01-05",
            "out_of_sample_end": "2026-01-05",
            "walk_forward": {"enabled": True, "folds": 2},
            "experiment_package_hash": "BASELINE_HASH",
        },
        market_data=market_data,
        signals=signals,
    )
    candidate = await backtest_store.create_run(
        symbol="BTPAIR.SZ",
        start_date="2026-01-01",
        end_date="2026-01-05",
        parameters={
            "benchmark_symbol": "000300.SH",
            "out_of_sample_start": "2026-01-05",
            "out_of_sample_end": "2026-01-05",
            "walk_forward": {"enabled": True, "folds": 2},
            "experiment_package_hash": "CANDIDATE_HASH",
        },
        market_data=market_data,
        signals=signals,
    )

    try:
        detail = await research_store.create_loop(
            CreateResearchLoopRequest(
                title="Backtest pair contract",
                objective="Keep baseline and candidate backtests traceable.",
                hypothesis="Weak backtest pair should stay supporting-only.",
            )
        )
        iteration = await research_store.attach_run(
            detail.iterations[0].iteration_id,
            AttachResearchRunRequest(run_id=run_id),
        )
        assert iteration is not None
        await research_store.attach_backtest(
            iteration.iteration_id,
            AttachResearchBacktestRequest(
                backtest_run_id=baseline["run_id"],
                role="baseline",
            ),
        )
        attached = await research_store.attach_backtest(
            iteration.iteration_id,
            AttachResearchBacktestRequest(
                backtest_run_id=candidate["run_id"],
                role="candidate",
            ),
        )

        assert attached is not None
        assert attached.metrics["baseline_backtest_id"] == baseline["run_id"]
        assert attached.metrics["candidate_backtest_id"] == candidate["run_id"]
        assert attached.metrics["candidate_backtest_review_conclusion"] == "SUPPORTING_ONLY"
        assert attached.metrics["backtest_supporting_only"] is True
        assert any(
            item.source_type == "BACKTEST"
            and item.source_id == baseline["run_id"]
            and "baseline" in item.label
            for item in attached.evidence_links
        )
        assert any(
            item.source_type == "BACKTEST"
            and item.source_id == candidate["run_id"]
            and "candidate" in item.label
            for item in attached.evidence_links
        )

        verdict_inputs = await research_verdict_store.get_inputs(attached.iteration_id)

        assert verdict_inputs is not None
        assert verdict_inputs.metrics["baseline_backtest_id"] == baseline["run_id"]
        assert verdict_inputs.metrics["candidate_backtest_id"] == candidate["run_id"]
        assert verdict_inputs.metrics["backtest_review_conclusion"] == "SUPPORTING_ONLY"
        assert verdict_inputs.metrics["backtest_experiment_package_hash"] == "CANDIDATE_HASH"
        assert verdict_inputs.metrics["baseline_backtest_experiment_package_hash"] == "BASELINE_HASH"
        assert verdict_inputs.metrics["backtest_research_usage"] == "supporting_only"
        assert verdict_inputs.can_accept_feedback is False
        assert any(item.source_type == "BACKTEST_COMPARE" for item in verdict_inputs.evidence)
        assert any("supporting evidence only" in warning for warning in verdict_inputs.quality_warnings)
    finally:
        await backtest_store.delete_run(baseline["run_id"])
        await backtest_store.delete_run(candidate["run_id"])


@pytest.mark.asyncio
async def test_attach_backtest_caps_primary_evidence_to_review_gate(monkeypatch, research_store):
    async def fake_get_run(run_id: str):
        assert run_id == "BT_PRIMARY_001"
        return {
            "run_id": run_id,
            "status": "COMPLETED",
            "report": {
                "total_return_pct": 0.28,
                "hit_rate": 0.72,
                "max_drawdown_pct": 0.04,
                "evidenceStrength": {
                    "grade": "HIGH",
                    "canSupportResearchVerdict": True,
                    "weakSample": False,
                    "researchUsage": "primary_evidence",
                },
                "limitations": [],
            },
            "updated_at": "2026-05-20T00:00:00+00:00",
        }

    monkeypatch.setattr("app.core.research_store.backtest_store.get_run", fake_get_run)
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="Backtest review-gate cap",
            objective="Backtest evidence must remain supporting-only inside Research Lab.",
            hypothesis="Even primary-looking backtest payloads are review inputs, not conclusions.",
        )
    )

    attached = await research_store.attach_backtest(
        detail.iterations[0].iteration_id,
        AttachResearchBacktestRequest(
            backtest_run_id="BT_PRIMARY_001",
            role="candidate",
            review_conclusion="PRIMARY_EVIDENCE_READY",
        ),
    )

    assert attached is not None
    evidence = attached.metrics["backtest_evidence_strength"]
    assert evidence["grade"] == "MEDIUM"
    assert evidence["reportedGrade"] == "HIGH"
    assert evidence["canSupportResearchVerdict"] is False
    assert evidence["can_support_research_verdict"] is False
    assert evidence["weakSample"] is True
    assert evidence["weak_sample"] is True
    assert evidence["researchUsage"] == "supporting_only"
    assert evidence["research_usage"] == "supporting_only"
    assert attached.metrics["backtest_review_conclusion"] == "SUPPORTING_ONLY"
    assert attached.metrics["candidate_backtest_review_conclusion"] == "SUPPORTING_ONLY"
    assert attached.metrics["backtest_supporting_only"] is True
    backtest_link = next(item for item in attached.evidence_links if item.source_type == "BACKTEST")
    assert backtest_link.quality == "MEDIUM"


@pytest.mark.asyncio
async def test_attach_backtest_reads_snake_case_primary_evidence_for_link_quality(monkeypatch, research_store):
    async def fake_get_run(run_id: str):
        assert run_id == "BT_SNAKE_PRIMARY_001"
        return {
            "run_id": run_id,
            "status": "COMPLETED",
            "report": {
                "total_return_pct": 0.31,
                "hit_rate": 0.76,
                "max_drawdown_pct": 0.03,
                "evidence_strength": {
                    "grade": "HIGH",
                    "can_support_research_verdict": True,
                    "weak_sample": False,
                    "research_usage": "primary_evidence",
                },
                "limitations": [],
            },
            "updated_at": "2026-05-20T00:10:00+00:00",
        }

    monkeypatch.setattr("app.core.research_store.backtest_store.get_run", fake_get_run)
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="Snake backtest review-gate cap",
            objective="Legacy snake-case backtest evidence must stay auditable and supporting-only.",
            hypothesis="Snake-case primary-looking backtest payloads are review inputs, not conclusions.",
        )
    )

    attached = await research_store.attach_backtest(
        detail.iterations[0].iteration_id,
        AttachResearchBacktestRequest(
            backtest_run_id="BT_SNAKE_PRIMARY_001",
            role="candidate",
            review_conclusion="RESEARCH_GRADE",
        ),
    )

    assert attached is not None
    evidence = attached.metrics["backtest_evidence_strength"]
    assert evidence["grade"] == "MEDIUM"
    assert evidence["reportedGrade"] == "HIGH"
    assert evidence["canSupportResearchVerdict"] is False
    assert evidence["can_support_research_verdict"] is False
    assert evidence["researchUsage"] == "supporting_only"
    assert evidence["research_usage"] == "supporting_only"
    assert attached.metrics["backtest_review_conclusion"] == "SUPPORTING_ONLY"
    backtest_link = next(item for item in attached.evidence_links if item.source_type == "BACKTEST")
    assert backtest_link.quality == "MEDIUM"
    assert backtest_link.reported_quality == "HIGH"


@pytest.mark.asyncio
async def test_attach_backtest_reads_reported_grade_audit_alias_for_link_quality(monkeypatch, research_store):
    async def fake_get_run(run_id: str):
        assert run_id == "BT_REPORTED_GRADE_AUDIT_001"
        return {
            "run_id": run_id,
            "status": "COMPLETED",
            "report": {
                "total_return_pct": 0.33,
                "hit_rate": 0.77,
                "max_drawdown_pct": 0.03,
                "evidence_strength": {
                    "reported_grade": "RESEARCH_GRADE",
                    "can_support_research_verdict": True,
                    "weak_sample": False,
                    "research_usage": "primary_evidence",
                },
                "limitations": [],
            },
            "updated_at": "2026-05-20T00:15:00+00:00",
        }

    monkeypatch.setattr("app.core.research_store.backtest_store.get_run", fake_get_run)
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="Reported-grade backtest audit cap",
            objective="Audit-only backtest grade aliases must stay visible but review-gated.",
            hypothesis="Reported research-grade audit aliases are context, not acceptance evidence.",
        )
    )

    attached = await research_store.attach_backtest(
        detail.iterations[0].iteration_id,
        AttachResearchBacktestRequest(
            backtest_run_id="BT_REPORTED_GRADE_AUDIT_001",
            role="candidate",
            review_conclusion="RESEARCH_GRADE",
        ),
    )

    assert attached is not None
    evidence = attached.metrics["backtest_evidence_strength"]
    assert evidence["grade"] == "MEDIUM"
    assert evidence["reportedGrade"] == "RESEARCH_GRADE"
    assert evidence["reported_grade"] == "RESEARCH_GRADE"
    assert evidence["canSupportResearchVerdict"] is False
    assert evidence["can_support_research_verdict"] is False
    assert evidence["weakSample"] is True
    assert evidence["weak_sample"] is True
    assert evidence["researchUsage"] == "supporting_only"
    assert evidence["research_usage"] == "supporting_only"
    assert attached.metrics["backtest_review_conclusion"] == "SUPPORTING_ONLY"
    backtest_link = next(item for item in attached.evidence_links if item.source_type == "BACKTEST")
    assert backtest_link.quality == "MEDIUM"
    assert backtest_link.reported_quality == "RESEARCH_GRADE"


@pytest.mark.asyncio
async def test_attach_backtest_conservatively_merges_conflicting_evidence_aliases(monkeypatch, research_store):
    async def fake_get_run(run_id: str):
        assert run_id == "BT_RESEARCH_CONFLICTING_ALIAS_001"
        return {
            "run_id": run_id,
            "status": "COMPLETED",
            "report": {
                "total_return_pct": 0.25,
                "hit_rate": 0.71,
                "max_drawdown_pct": 0.04,
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
                "limitations": [],
            },
            "updated_at": "2026-05-20T00:20:00+00:00",
        }

    monkeypatch.setattr("app.core.research_store.backtest_store.get_run", fake_get_run)
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="Conflicting backtest alias cap",
            objective="Research Lab must prefer the weakest alias when backtest evidence disagrees.",
            hypothesis="Conflicting legacy/canonical evidence aliases cannot upgrade a review-gated backtest.",
        )
    )

    attached = await research_store.attach_backtest(
        detail.iterations[0].iteration_id,
        AttachResearchBacktestRequest(
            backtest_run_id="BT_RESEARCH_CONFLICTING_ALIAS_001",
            role="candidate",
            review_conclusion="PRIMARY_EVIDENCE_READY",
        ),
    )

    assert attached is not None
    evidence = attached.metrics["backtest_evidence_strength"]
    assert evidence["grade"] == "LOW"
    assert evidence["reportedGrade"] == "HIGH"
    assert evidence["canSupportResearchVerdict"] is False
    assert evidence["can_support_research_verdict"] is False
    assert evidence["weakSample"] is True
    assert evidence["weak_sample"] is True
    assert evidence["researchUsage"] == "supporting_only"
    assert evidence["research_usage"] == "supporting_only"
    assert attached.metrics["backtest_review_conclusion"] == "SUPPORTING_ONLY"
    backtest_link = next(item for item in attached.evidence_links if item.source_type == "BACKTEST")
    assert backtest_link.quality == "LOW"


@pytest.mark.asyncio
async def test_create_sample_loop_route_reports_missing_run(monkeypatch):
    monkeypatch.setattr(routes_analysis, "runs_store", {})
    response = await routes_research.create_sample_research_loop_route(
        CreateSampleResearchLoopRequest(symbol="MISSING.SZ")
    )

    assert response.created is False
    assert response.detail is None
    assert response.missing_reasons == [
        "No completed or stale analysis run is available to seed a research loop."
    ]


@pytest.mark.asyncio
async def test_feedback_persists_first_class_evidence_and_feedback_tables(research_store):
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="Evidence tables",
            objective="Persist feedback and evidence as first-class records",
            hypothesis="Dedicated tables make provenance queryable.",
        )
    )
    iteration = detail.iterations[0]
    _register_analysis_run("RUN_TABLE_001")

    reviewed = await research_store.record_feedback(
        iteration.iteration_id,
        ResearchIterationFeedbackRequest(
            action="REVIEW",
            verdict="PENDING",
            note="First-class persistence check.",
            evidence_links=[
                ResearchEvidenceLink(
                    source_type="RUN",
                    source_id="RUN_TABLE_001",
                    label="Queryable run evidence",
                    quality="HIGH",
                    created_at="2026-05-20T00:00:00Z",
                )
            ],
        ),
    )
    assert reviewed is not None
    stored_link = next(item for item in reviewed.evidence_links if item.source_id == "RUN_TABLE_001")
    assert stored_link.quality == "MEDIUM"
    assert stored_link.reported_quality == "HIGH"
    reviewed_payload = reviewed.model_dump(by_alias=True)
    stored_payload = next(item for item in reviewed_payload["evidence_links"] if item["source_id"] == "RUN_TABLE_001")
    assert stored_payload["reportedQuality"] == "HIGH"

    async with AsyncSessionLocal() as db:
        evidence_count = await db.execute(select(func.count()).select_from(ResearchEvidenceLinkDB))
        feedback_count = await db.execute(select(func.count()).select_from(ResearchFeedbackEventDB))
        evidence = await db.execute(select(ResearchEvidenceLinkDB))
        feedback = await db.execute(select(ResearchFeedbackEventDB))

    evidence_row = evidence.scalar_one()
    feedback_row = feedback.scalar_one()
    assert evidence_count.scalar() == 1
    assert feedback_count.scalar() == 1
    assert evidence_row.iteration_id == iteration.iteration_id
    assert evidence_row.quality == "MEDIUM"
    assert evidence_row.summary_json["quality"] == "MEDIUM"
    assert evidence_row.summary_json["reportedQuality"] == "HIGH"
    assert feedback_row.action == "REVIEW"


@pytest.mark.asyncio
async def test_feedback_preserves_reported_quality_when_replaying_review_gated_link(research_store):
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="Replayed evidence audit",
            objective="Keep UI-replayed audit quality stable.",
            hypothesis="Review-gated links must retain their original reported quality.",
        )
    )
    iteration = detail.iterations[0]

    reviewed = await research_store.record_feedback(
        iteration.iteration_id,
        ResearchIterationFeedbackRequest(
            action="SEND_TO_FEEDBACK",
            verdict="PENDING",
            evidence_links=[
                ResearchEvidenceLink(
                    source_type="PATCH",
                    source_id="PATCH_REPLAYED_AUDIT_001",
                    label="Replayed patch evidence",
                    quality="MEDIUM",
                    reported_quality="HIGH",
                    created_at="2026-05-20T00:00:00Z",
                )
            ],
        ),
    )

    assert reviewed is not None
    stored_link = next(item for item in reviewed.evidence_links if item.source_id == "PATCH_REPLAYED_AUDIT_001")
    assert stored_link.quality == "MEDIUM"
    assert stored_link.reported_quality == "HIGH"
    stored_payload = next(
        item for item in reviewed.model_dump(by_alias=True)["evidence_links"]
        if item["source_id"] == "PATCH_REPLAYED_AUDIT_001"
    )
    assert stored_payload["quality"] == "MEDIUM"
    assert stored_payload["reportedQuality"] == "HIGH"

    async with AsyncSessionLocal() as db:
        evidence = await db.execute(
            select(ResearchEvidenceLinkDB).where(
                ResearchEvidenceLinkDB.source_id == "PATCH_REPLAYED_AUDIT_001"
            )
        )

    evidence_row = evidence.scalar_one()
    assert evidence_row.quality == "MEDIUM"
    assert evidence_row.summary_json["quality"] == "MEDIUM"
    assert evidence_row.summary_json["reportedQuality"] == "HIGH"
    assert evidence_row.summary_json["reported_quality"] == "HIGH"

    replayed_without_audit = await research_store.record_feedback(
        iteration.iteration_id,
        ResearchIterationFeedbackRequest(
            action="REPLAY_WITH_LEGACY_CLIENT",
            verdict="PENDING",
            evidence_links=[
                ResearchEvidenceLink(
                    source_type="PATCH",
                    source_id="PATCH_REPLAYED_AUDIT_001",
                    label="Legacy replayed patch evidence",
                    quality="MEDIUM",
                    created_at="2026-05-20T00:01:00Z",
                )
            ],
        ),
    )

    assert replayed_without_audit is not None
    replayed_link = next(
        item for item in replayed_without_audit.evidence_links
        if item.source_id == "PATCH_REPLAYED_AUDIT_001"
    )
    assert replayed_link.quality == "MEDIUM"
    assert replayed_link.reported_quality == "HIGH"

    async with AsyncSessionLocal() as db:
        replayed_evidence = await db.execute(
            select(ResearchEvidenceLinkDB).where(
                ResearchEvidenceLinkDB.source_id == "PATCH_REPLAYED_AUDIT_001"
            )
        )

    replayed_evidence_row = replayed_evidence.scalar_one()
    assert replayed_evidence_row.quality == "MEDIUM"
    assert replayed_evidence_row.summary_json["reportedQuality"] == "HIGH"
    assert replayed_evidence_row.summary_json["reported_quality"] == "HIGH"


@pytest.mark.asyncio
async def test_research_routes_update_attach_next_archive_and_gate_acceptance():
    detail = await routes_research.create_research_loop_route(
        CreateResearchLoopRequest(
            title="Route coverage",
            objective="Cover thin workflow routes",
            hypothesis="Routes should keep the iteration chain queryable.",
        )
    )
    iteration = detail.iterations[0]
    _register_analysis_run("RUN_ROUTE_001")
    route_backtest = await _register_backtest_run()

    updated_loop = await routes_research.update_research_loop_route(
        detail.loop.loop_id,
        UpdateResearchLoopRequest(tags=["route", "research"]),
    )
    fetched_iteration = await routes_research.research_iteration_detail(iteration.iteration_id)
    attached_run = await routes_research.attach_research_iteration_run_route(
        iteration.iteration_id,
        AttachResearchRunRequest(run_id="RUN_ROUTE_001"),
    )
    attached_backtest = await routes_research.attach_research_iteration_backtest_route(
        iteration.iteration_id,
        AttachResearchBacktestRequest(backtest_run_id=route_backtest["run_id"]),
    )
    cleared_links = await routes_research.update_research_iteration_route(
        iteration.iteration_id,
        UpdateResearchIterationRequest(
            linked_run_id=None,
            linked_backtest_id=None,
            metrics=None,
        ),
    )
    next_iteration = await routes_research.create_next_research_iteration_route(
        iteration.iteration_id,
        CreateNextResearchIterationRequest(hypothesis="Follow-up from route test."),
    )
    archived = await routes_research.archive_research_loop_route(
        detail.loop.loop_id,
        ArchiveResearchLoopRequest(note="Route archive check."),
    )

    assert updated_loop.loop.tags == ["route", "research"]
    assert fetched_iteration.iteration_id == iteration.iteration_id
    assert attached_run.linked_run_id == "RUN_ROUTE_001"
    assert attached_backtest.linked_backtest_id == route_backtest["run_id"]
    assert cleared_links.linked_run_id is None
    assert cleared_links.linked_backtest_id is None
    assert cleared_links.metrics == {}
    assert next_iteration.order == 2
    assert archived.loop.status == "ARCHIVED"

    with pytest.raises(HTTPException) as blocked:
        await routes_research.record_research_iteration_feedback_route(
            next_iteration.iteration_id,
            ResearchIterationFeedbackRequest(action="ACCEPT", verdict="ACCEPTED"),
        )
    assert blocked.value.status_code == 409

    with pytest.raises(HTTPException) as missing_reason:
        await routes_research.record_research_iteration_feedback_route(
            next_iteration.iteration_id,
            ResearchIterationFeedbackRequest(
                action="ACCEPT",
                verdict="ACCEPTED",
                override_blocking_reasons=True,
            ),
        )
    assert missing_reason.value.status_code == 400

    accepted = await routes_research.record_research_iteration_feedback_route(
        next_iteration.iteration_id,
        ResearchIterationFeedbackRequest(
            action="ACCEPT",
            verdict="ACCEPTED",
            override_blocking_reasons=True,
            override_reason="Manual research lead override after offline review.",
        ),
    )
    assert accepted.verdict == "ACCEPTED"
    assert accepted.metrics["verdict_gate_override"] is True
    assert accepted.metrics["verdict_gate_override_can_accept_feedback"] is False
    assert accepted.metrics["verdict_gate_override_evidence_usage"] == "review_gate_only"
    assert accepted.metrics["verdict_gate_override_strong_conclusion_allowed"] is False
    assert accepted.metrics["verdict_gate_override_simulation_only"] is True
    assert accepted.metrics["verdict_gate_override_is_real_trade"] is False
    assert accepted.metrics["verdict_gate_override_inputs_generated_at"]
    assert accepted.metrics["verdict_inputs_generated_at"] == accepted.metrics["verdict_gate_override_inputs_generated_at"]
    assert accepted.metrics["verdict_gate_override_blocking_reasons"]


@pytest.mark.asyncio
async def test_backtest_route_creates_research_verdict_inputs_from_run():
    backtest_store = BacktestStore()
    run = await backtest_store.create_run(
        symbol="000001.SZ",
        start_date="2026-04-01",
        end_date="2026-04-05",
        parameters={
            "signal_source": "MOCK",
            "data_source": "MOCK",
            "parameter_scan": {"enabled": True, "grid": {"signal_min_strength": [0.3]}},
            "walk_forward": {"enabled": True, "folds": 2},
            "simulation_only": True,
            "is_real_trade": False,
        },
        reuse_existing=False,
        force_new=True,
    )
    detail = await routes_research.create_research_loop_route(
        CreateResearchLoopRequest(
            title="Backtest verdict input route",
            objective="Create verdict inputs from a Backtest run.",
            hypothesis="Backtest evidence should feed Research verdict inputs.",
            target_modules=["backtest", "research_verdict"],
        )
    )
    iteration = detail.iterations[0]

    try:
        result = await routes_research.create_research_backtest_verdict_inputs_route(
            run["run_id"],
            CreateResearchBacktestVerdictInputsRequest(
                iteration_id=iteration.iteration_id,
                reviewer="route-test",
                role="candidate",
            ),
        )

        assert result.iteration.linked_backtest_id == run["run_id"]
        assert result.evidence_usage == "supporting_only"
        assert result.supporting_only is True
        assert result.simulation_only is True
        assert result.is_real_trade is False
        assert result.strong_conclusion_allowed is False
        assert result.verdict_inputs.iteration_id == iteration.iteration_id
        assert result.verdict_inputs.metrics["candidate_backtest_id"] == run["run_id"]
        assert result.verdict_inputs.metrics["backtest_research_usage"] == "supporting_only"
        assert any(
            item.source_type == "BACKTEST" and item.source_id == run["run_id"]
            for item in result.verdict_inputs.evidence
        )
    finally:
        await backtest_store.delete_run(run["run_id"])


@pytest.mark.asyncio
async def test_signalops_route_creates_research_tick_evidence(monkeypatch):
    signal = await signalops_store.create_signal(
        {
            "symbol": "000002.SZ",
            "stock_name": "SignalOps Evidence",
            "source_run_id": "RUN_SIGNALOPS_EVIDENCE_001",
            "review_fields": ["auto_paper_trading", "decision_card"],
            "metadata_json": {"source": "test_signalops_tick"},
        }
    )
    monkeypatch.setattr(
        auto_paper_trading_store,
        "get_status",
        lambda: {
            "last_tick_at": "2026-06-01T09:30:00+00:00",
            "last_tick_result": {
                "status": "COMPLETED",
                "signal_id": signal["signal_id"],
                "symbol": signal["symbol"],
                "updated_at": "2026-06-01T09:30:00+00:00",
                "message": "tick completed",
                "decision_card": {"action": "SIM_HOLD", "reason": "test tick evidence"},
                "module_evidence": {"version": "signalops_module_evidence_v1"},
                "portfolio_snapshot": {"snapshot_id": "PF_SIGNALOPS_EVIDENCE_001"},
            },
        },
    )
    detail = await routes_research.create_research_loop_route(
        CreateResearchLoopRequest(
            title="SignalOps tick evidence route",
            objective="Attach a SignalOps tick to Research verdict inputs.",
            hypothesis="SignalOps tick evidence should remain supporting-only.",
            target_modules=["signalops", "research_verdict"],
        )
    )
    iteration = detail.iterations[0]

    result = await routes_research.create_research_signalops_evidence_route(
        signal["signal_id"],
        CreateResearchSignalOpsEvidenceRequest(
            iteration_id=iteration.iteration_id,
            reviewer="route-test",
        ),
    )

    assert result.iteration.metrics["signalops_signal_id"] == signal["signal_id"]
    assert result.evidence_usage == "supporting_only"
    assert result.supporting_only is True
    assert result.simulation_only is True
    assert result.is_real_trade is False
    assert result.strong_conclusion_allowed is False
    assert result.iteration.metrics["signalops_tick_status"] == "COMPLETED"
    assert result.iteration.metrics["signalops_evidence_usage"] == "supporting_only"
    assert result.iteration.metrics["simulation_only"] is True
    assert result.iteration.metrics["is_real_trade"] is False
    assert result.verdict_inputs.iteration_id == iteration.iteration_id
    assert result.verdict_inputs.metrics["signalops_supporting_only"] is True
    signalops_links = [
        item
        for item in result.iteration.evidence_links
        if item.source_type in {"SIGNALOPS", "SIGNALOPS_TICK"}
    ]
    assert {item.source_type for item in signalops_links} == {"SIGNALOPS", "SIGNALOPS_TICK"}
    assert all(item.quality in {"LOW", "MEDIUM"} for item in signalops_links)
    signalops_verdict_evidence = [
        item
        for item in result.verdict_inputs.evidence
        if item.source_type in {"SIGNALOPS", "SIGNALOPS_TICK"}
    ]
    assert {item.source_type for item in signalops_verdict_evidence} == {"SIGNALOPS", "SIGNALOPS_TICK"}
    assert all(item.quality in {"LOW", "MEDIUM"} for item in signalops_verdict_evidence)
    assert any(
        item.source_type == "SIGNALOPS_TICK" and item.source_id.startswith(signal["signal_id"])
        for item in result.verdict_inputs.evidence
    )


@pytest.mark.asyncio
async def test_signalops_evidence_route_returns_404_for_missing_signal():
    detail = await routes_research.create_research_loop_route(
        CreateResearchLoopRequest(
            title="SignalOps missing signal route",
            objective="Missing SignalOps signals should stay a route-level 404.",
            hypothesis="A missing SignalOps signal must not attach Research evidence.",
            target_modules=["signalops", "research_verdict"],
        )
    )
    iteration = detail.iterations[0]

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/api/research/signalops/signals/SIG_MISSING_FOR_RESEARCH/evidence",
            json={"iteration_id": iteration.iteration_id, "reviewer": "route-test"},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "SignalOps signal not found"
    unchanged = await routes_research.research_iteration_detail(iteration.iteration_id)
    assert "signalops_signal_id" not in unchanged.metrics
    assert not any(item.source_type.startswith("SIGNALOPS") for item in unchanged.evidence_links)


@pytest.mark.asyncio
async def test_rd_agent_trace_preview_and_import_are_review_only():
    request = ResearchTraceImportRequest(
        trace={
            "trace_id": "RD_ROUTE_001",
            "title": "External RD trace",
            "goal": "Import trace without trusting external conclusion",
            "iterations": [
                {
                    "hypothesis": "External accepted result needs local review.",
                    "plan": "Import as external evidence.",
                    "verdict": "accept",
                    "evidence": "rd-agent/artifacts/summary.json",
                }
            ],
        },
        source_id="RD_ROUTE_001",
    )

    preview = await routes_research.preview_rd_agent_trace_route(request)
    imported = await routes_research.import_rd_agent_trace_route(request)
    traces = await routes_research.research_traces()
    traces_by_loop = await routes_research.research_traces(loop_id=imported.loop.loop_id)
    traces_by_iteration = await routes_research.research_traces(
        iteration_id=imported.iterations[0].iteration.iteration_id
    )
    traces_by_source = await routes_research.research_traces(source="rd-agent")
    traces_missing = await routes_research.research_traces(loop_id="RLOOP_MISSING")
    detail = await routes_research.research_trace_detail(imported.loop.loop_id)

    assert preview.imported is False
    assert imported.imported is True
    assert imported.iterations[0].external_verdict == "ACCEPTED"
    assert imported.iterations[0].iteration.verdict == "PENDING"
    assert imported.iterations[0].iteration.status == "EXTERNAL_IMPORTED"
    assert imported.iterations[0].iteration.metrics["external_review_only"] is True
    assert any(loop.loop_id == imported.loop.loop_id for loop in traces)
    assert [loop.loop_id for loop in traces_by_loop] == [imported.loop.loop_id]
    assert [loop.loop_id for loop in traces_by_iteration] == [imported.loop.loop_id]
    assert any(loop.loop_id == imported.loop.loop_id for loop in traces_by_source)
    assert traces_missing == []
    assert detail.iterations[0].evidence_links[0].source_type == "RD_AGENT_TRACE"


@pytest.mark.asyncio
async def test_rd_agent_trace_import_route_returns_400_for_budget_overflow():
    request = ResearchTraceImportRequest(
        trace={"iterations": [{"hypothesis": f"h{index}"} for index in range(MAX_TRACE_ITERATIONS + 1)]},
        source_id="RD_ROUTE_TOO_LARGE",
    )

    with pytest.raises(HTTPException) as exc:
        await routes_research.import_rd_agent_trace_route(request)

    assert exc.value.status_code == 400
    assert "iteration limit" in exc.value.detail
