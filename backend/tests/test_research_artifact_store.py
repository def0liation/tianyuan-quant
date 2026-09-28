import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api import routes_analysis, routes_research
from app.core import knowledge_store
from app.core.case_library_store import case_library_store, error_ledger_store, knowledge_patch_store
from app.core import research_artifact_store as research_artifact_module
from app.core import research_store as research_store_module
from app.core.research_artifact_store import ResearchArtifactStore, research_artifact_store
from app.core.research_store import ResearchLoopStore
from app.db.models_research import ResearchArtifactMaterializationDB
from app.db.session import AsyncSessionLocal
from app.models.research import (
    CreateP2ClosedLoopSampleRequest,
    CreateResearchIterationRequest,
    CreateSampleResearchLoopRequest,
    CreateResearchLoopRequest,
    ResearchEvidenceLink,
    ResearchArtifactMaterializeRequest,
    ResearchIterationFeedbackRequest,
    UpdateResearchIterationRequest,
)


@pytest.fixture
def research_store():
    return ResearchLoopStore()


def test_artifact_evidence_link_caps_research_grade_aliases_to_review_gate():
    research_grade = research_artifact_module._evidence_link(
        "BACKTEST",
        "BT_ARTIFACT_RESEARCH_GRADE_001",
        "Materialized backtest",
        "RESEARCH_GRADE",
    )
    primary_ready = research_artifact_module._evidence_link(
        "EVALUATION",
        "EVAL_ARTIFACT_PRIMARY_READY_001",
        "Materialized evaluation",
        "PRIMARY_EVIDENCE_READY",
    )
    supporting_only = research_artifact_module._evidence_link(
        "BACKTEST",
        "BT_ARTIFACT_SUPPORTING_ONLY_001",
        "Supporting-only materialized backtest",
        "SUPPORTING_ONLY",
    )

    assert research_grade.quality == "MEDIUM"
    assert research_grade.reported_quality == "RESEARCH_GRADE"
    assert primary_ready.quality == "MEDIUM"
    assert primary_ready.reported_quality == "PRIMARY_EVIDENCE_READY"
    assert supporting_only.quality == "LOW"
    assert supporting_only.reported_quality == "SUPPORTING_ONLY"
    assert research_artifact_module._review_gate_quality("SUPPORTING_ONLY") == "LOW"


@pytest.fixture(autouse=True)
def temp_knowledge_store(monkeypatch, tmp_path):
    monkeypatch.setattr(knowledge_store, "STORAGE_FILE", tmp_path / "knowledge_iterations.json")


def sample_run(run_id: str = "RUN_RESEARCH_P5_001"):
    return {
        "runId": run_id,
        "auditId": "AUD_RESEARCH_P5_001",
        "stockCode": "603663",
        "stockName": "Unit Test Stock",
        "taskType": "research",
        "runMode": "STANDARD_MODE",
        "status": "COMPLETED",
        "finalAction": "WAIT",
        "finalWriter": {"finalAction": "WAIT"},
        "compressedSummary": {"quality": {"score": 88}},
        "qiam": {"modelConfidenceFinal": 0.78, "finalBuySuitability": "WATCH"},
        "dvg": {"status": "PASS"},
        "signalOps": {"signalStatus": "PAPER_TEST"},
        "rdResearch": {"iterationId": "placeholder"},
    }


@pytest.mark.asyncio
async def test_research_iteration_accepts_canonical_run_links_for_workflow_state(
    research_store, monkeypatch
):
    run = sample_run("RUN_RESEARCH_LINK_CANONICAL")
    monkeypatch.setattr(routes_analysis, "runs_store", {run["runId"]: run})
    monkeypatch.setattr(research_store_module, "load_persisted_runs", lambda: {})

    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="P5 canonical run link guard",
            objective="Canonical analysis run provenance should remain usable in Research Lab.",
        )
    )
    iteration = await research_store.create_iteration(
        detail.loop.loop_id,
        CreateResearchIterationRequest(
            hypothesis="Canonical run id can seed a research iteration.",
            linked_run_id=f" {run['runId']} ",
        ),
    )

    assert iteration is not None
    assert iteration.linked_run_id == run["runId"]

    updated = await research_store.update_iteration(
        iteration.iteration_id,
        UpdateResearchIterationRequest(linked_run_id=f" {run['runId']} "),
    )
    assert updated is not None
    assert updated.linked_run_id == run["runId"]

    feedback = await research_store.record_feedback(
        iteration.iteration_id,
        ResearchIterationFeedbackRequest(
            action="ATTACH_RUN",
            verdict="PENDING",
            linked_run_id=f" {run['runId']} ",
            evidence_links=[
                ResearchEvidenceLink(
                    source_type="run",
                    source_id=f" {run['runId']} ",
                    label="Canonical run evidence",
                    quality="HIGH",
                    created_at="2026-06-15T00:00:00+00:00",
                )
            ],
        ),
    )

    assert feedback is not None
    assert feedback.linked_run_id == run["runId"]
    assert any(
        link.source_type == "RUN" and link.source_id == run["runId"]
        for link in feedback.evidence_links
    )

    refreshed = await research_store.get_loop_detail(detail.loop.loop_id)
    assert refreshed is not None
    run_step = next(step for step in refreshed.workflow_state.steps if step.key == "run")
    assert run_step.status == "PASS"
    assert run_step.ref_id == run["runId"]


@pytest.mark.asyncio
async def test_research_iteration_rejects_legacy_or_forged_run_links_before_workflow_state(
    research_store, monkeypatch
):
    legacy_run_id = "RUN_MOCK_RESEARCH_LINK_LEGACY"
    legacy_run = sample_run(legacy_run_id)
    legacy_run["auditId"] = "AUD_RUN_MOCK_RESEARCH_LINK_LEGACY"
    monkeypatch.setattr(routes_analysis, "runs_store", {})
    monkeypatch.setattr(
        research_store_module,
        "load_persisted_runs",
        lambda: {legacy_run_id: legacy_run},
    )

    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="P5 forged run link guard",
            objective="Legacy or forged analysis run ids must not enter Research Lab workflow state.",
        )
    )
    iteration = await research_store.create_iteration(
        detail.loop.loop_id,
        CreateResearchIterationRequest(
            hypothesis="Legacy run id must not seed a research iteration.",
            linked_run_id=legacy_run_id,
        ),
    )

    assert iteration is not None
    assert iteration.linked_run_id is None
    assert "linked_run_id_missing_or_legacy_ignored" in iteration.metrics["warnings"]

    updated = await research_store.update_iteration(
        iteration.iteration_id,
        UpdateResearchIterationRequest(linked_run_id="RUN_FORGED_RESEARCH_LINK"),
    )
    assert updated is not None
    assert updated.linked_run_id is None
    assert "linked_run_id_missing_or_legacy_ignored" in updated.metrics["warnings"]

    feedback = await research_store.record_feedback(
        iteration.iteration_id,
        ResearchIterationFeedbackRequest(
            action="ATTACH_RUN",
            verdict="PENDING",
            linked_run_id="RUN_FORGED_RESEARCH_LINK",
            evidence_links=[
                ResearchEvidenceLink(
                    source_type="RUN",
                    source_id="RUN_FORGED_RESEARCH_LINK",
                    label="Forged run evidence",
                    quality="HIGH",
                    created_at="2026-06-15T00:00:00+00:00",
                )
            ],
        ),
    )

    assert feedback is not None
    assert feedback.linked_run_id is None
    assert "linked_run_id_missing_or_legacy_ignored" in feedback.metrics["warnings"]
    assert all(link.source_type != "RUN" for link in feedback.evidence_links)

    refreshed = await research_store.get_loop_detail(detail.loop.loop_id)
    assert refreshed is not None
    run_step = next(step for step in refreshed.workflow_state.steps if step.key == "run")
    assert run_step.status == "WAIT"
    assert run_step.ref_id is None
    assert "No linked analysis run for the current iteration." in refreshed.workflow_state.blocking_reasons


@pytest.mark.asyncio
async def test_research_iteration_keeps_forged_backtest_evidence_links_review_only_before_workflow_state(
    research_store,
):
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="P5 forged backtest evidence guard",
            objective="Missing backtest ids must not enter Research Lab evidence review.",
        )
    )
    iteration = await research_store.create_iteration(
        detail.loop.loop_id,
        CreateResearchIterationRequest(
            hypothesis="Forged backtest id must not seed a research iteration.",
        ),
    )

    feedback = await research_store.record_feedback(
        iteration.iteration_id,
        ResearchIterationFeedbackRequest(
            action="ATTACH_BACKTEST",
            verdict="PENDING",
            linked_backtest_id="BT_FORGED_RESEARCH_LINK",
            evidence_links=[
                ResearchEvidenceLink(
                    source_type="BACKTEST",
                    source_id="BT_FORGED_RESEARCH_LINK",
                    label="Forged backtest evidence",
                    quality="HIGH",
                    created_at="2026-06-15T00:00:00+00:00",
                )
            ],
        ),
    )

    assert feedback is not None
    assert feedback.linked_backtest_id is None
    assert "linked_backtest_id_missing_ignored" in feedback.metrics["warnings"]
    backtest_link = next(link for link in feedback.evidence_links if link.source_type == "BACKTEST")
    assert backtest_link.source_id == "BT_FORGED_RESEARCH_LINK"
    assert backtest_link.quality == "MEDIUM"
    assert backtest_link.reported_quality == "HIGH"

    refreshed = await research_store.get_loop_detail(detail.loop.loop_id)
    assert refreshed is not None
    evidence_step = next(step for step in refreshed.workflow_state.steps if step.key == "evidence")
    assert evidence_step.status == "WARN"
    assert evidence_step.evidence_strength == "LOW"
    assert "linked_backtest_id_missing_ignored" in evidence_step.missing_items
    assert "Linked backtest is missing; attach a persisted backtest run." in evidence_step.missing_items


@pytest.mark.asyncio
async def test_materialize_blocks_legacy_linked_run_from_artifacts(
    research_store, monkeypatch
):
    legacy_run_id = "RUN_MOCK_RESEARCH_P5_LEGACY"
    legacy_run = sample_run(legacy_run_id)
    legacy_run["auditId"] = "AUD_RUN_MOCK_RESEARCH_P5_LEGACY"
    monkeypatch.setattr(routes_analysis, "runs_store", {})
    monkeypatch.setattr(
        research_artifact_module,
        "load_persisted_runs",
        lambda: {legacy_run_id: legacy_run},
    )
    monkeypatch.setattr(
        research_store_module,
        "load_persisted_runs",
        lambda: {legacy_run_id: legacy_run},
    )
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="P5 legacy run materialization guard",
            objective="Legacy mock runs must not create Research Lab downstream artifacts.",
            hypothesis="Materialization blocks non-canonical run provenance.",
            target_modules=["research_lab", "knowledge"],
        )
    )
    iteration = detail.iterations[0]
    updated = await research_store.record_feedback(
        iteration.iteration_id,
        ResearchIterationFeedbackRequest(
            action="PATCH",
            verdict="PATCH_REQUIRED",
            status="PATCH_REQUIRED",
            linked_run_id=legacy_run_id,
            note="Attempt to materialize from legacy run.",
        ),
    )
    assert updated is not None
    assert updated.linked_run_id is None
    assert "linked_run_id_missing_or_legacy_ignored" in updated.metrics["warnings"]

    result = await research_artifact_store.materialize_iteration_artifacts(
        iteration.iteration_id,
        ResearchArtifactMaterializeRequest(
            run_evaluation=True,
            reviewer="unit",
            note="Legacy linked run should block materialization.",
        ),
    )

    assert result is not None
    assert result.case is None
    assert result.knowledge_item is None
    assert result.error_entry is None
    assert result.patch is None
    assert result.evaluation is None
    assert "linked_run_required_artifacts_blocked" in result.warnings

    cases = await case_library_store.list_cases(limit=100)
    errors = await error_ledger_store.list_entries(limit=100)
    patches = await knowledge_patch_store.list_patches(limit=100)
    assert all(item["run_id"] != legacy_run_id for item in cases)
    assert all(item["run_id"] != legacy_run_id for item in errors)
    assert all(
        item["patch_content"].get("research_iteration_id") != iteration.iteration_id
        for item in patches
    )


@pytest.mark.asyncio
async def test_materialize_requires_linked_run_before_creating_artifacts(
    research_store, monkeypatch
):
    monkeypatch.setattr(routes_analysis, "runs_store", {})
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="P5 missing run materialization guard",
            objective="Research Lab artifacts must not be created from fallback run data.",
            hypothesis="Canonical run provenance is required before materialization.",
            target_modules=["research_lab", "knowledge"],
        )
    )
    iteration = detail.iterations[0]
    updated = await research_store.record_feedback(
        iteration.iteration_id,
        ResearchIterationFeedbackRequest(
            action="PATCH",
            verdict="PATCH_REQUIRED",
            status="PATCH_REQUIRED",
            note="Attempt to materialize without linked run.",
        ),
    )
    assert updated is not None

    result = await research_artifact_store.materialize_iteration_artifacts(
        iteration.iteration_id,
        ResearchArtifactMaterializeRequest(
            run_evaluation=True,
            reviewer="unit",
            note="Missing linked run should block materialization.",
        ),
    )

    assert result is not None
    assert result.case is None
    assert result.knowledge_item is None
    assert result.error_entry is None
    assert result.patch is None
    assert result.evaluation is None
    assert result.provenance_chain == [f"loop:{iteration.loop_id}", f"iteration:{iteration.iteration_id}"]
    assert "linked_run_required_artifacts_blocked" in result.warnings

    cases = await case_library_store.list_cases(limit=100)
    errors = await error_ledger_store.list_entries(limit=100)
    patches = await knowledge_patch_store.list_patches(limit=100)
    assert all(item["run_id"] != iteration.iteration_id for item in cases)
    assert all(item["run_id"] != iteration.iteration_id for item in errors)
    assert all(
        item["patch_content"].get("research_iteration_id") != iteration.iteration_id
        for item in patches
    )


@pytest.mark.asyncio
async def test_sample_loop_route_can_materialize_p2_closed_loop_artifacts(monkeypatch):
    run = sample_run("RUN_RESEARCH_P2_SAMPLE_001")
    run["stockCode"] = "P2SAMPLE.SZ"
    run["stockName"] = "P2 Sample"
    run["portfolioSnapshot"] = {
        "snapshotId": "PSNAP_P2_SAMPLE",
        "updatedAt": "2026-05-20T01:02:00+00:00",
        "positions": [
            {
                "symbol": "P2SAMPLE.SZ",
                "name": "P2 Sample",
                "shares": 1000,
                "weight": 0.1,
            }
        ],
    }
    run["portfolio"] = {
        "portfolioCoverage": "HOLDINGS_CONNECTED",
        "snapshotId": "PSNAP_P2_SAMPLE",
        "holdings": run["portfolioSnapshot"]["positions"],
    }
    monkeypatch.setattr(routes_analysis, "runs_store", {run["runId"]: run})

    response = await routes_research.create_sample_research_loop_route(
        CreateSampleResearchLoopRequest(
            symbol="P2SAMPLE.SZ",
            force_backtest=True,
            materialize_artifacts=True,
            run_evaluation=True,
            reviewer="unit",
        )
    )

    assert response.created is True
    assert response.detail is not None
    iteration = response.detail.iterations[0]
    assert iteration.linked_run_id == run["runId"]
    assert iteration.linked_backtest_id
    assert iteration.linked_knowledge_item_id == response.artifact_context["knowledge_item_id"]
    assert response.context["portfolio_snapshot_id"] == "PSNAP_P2_SAMPLE"
    assert response.context["artifact_context"]["case_id"] == response.artifact_context["case_id"]
    assert response.artifact_context["knowledge_item_id"]
    assert any(item.source_type == "PORTFOLIO_SNAPSHOT" for item in iteration.evidence_links)
    assert any(item.source_type == "KNOWLEDGE" for item in iteration.evidence_links)


@pytest.mark.asyncio
async def test_p2_closed_loop_sample_route_creates_portfolio_run_backtest_research_knowledge(monkeypatch):
    async def fake_hydrate_run_with_market_data(run_data: dict, symbol: str):
        run_data["marketData"] = {"symbol": symbol, "status": "READY", "quote": {"price": 10.5}}
        run_data["dataSources"] = {
            "sources": {
                "quote": {
                    "name": "Quote",
                    "provider": "unit",
                    "icon": "BarChart3",
                    "status": "READY",
                    "detail": "unit quote",
                    "available": True,
                    "category": "quote",
                    "dataMode": "LIVE",
                }
            },
            "summary": {
                "availableCount": 1,
                "totalCount": 1,
                "availableRatio": "1/1",
                "overallStatus": "READY",
                "overallDataMode": "LIVE",
                "generatedAt": "2026-05-20T01:00:00+00:00",
            },
        }
        return run_data

    def fake_apply_agent_framework_to_run(run_data: dict, request: dict, runtime_summary: dict):
        run_data["agentRuntime"] = runtime_summary
        return run_data

    monkeypatch.setattr(routes_analysis, "runs_store", {})
    monkeypatch.setattr(routes_analysis, "hydrate_run_with_market_data", fake_hydrate_run_with_market_data)
    monkeypatch.setattr(routes_analysis, "apply_agent_framework_to_run", fake_apply_agent_framework_to_run)
    monkeypatch.setattr(routes_analysis, "get_active_knowledge_context", lambda: [])

    response = await routes_research.create_p2_closed_loop_sample_route(
        CreateP2ClosedLoopSampleRequest(
            symbol="P2FULL.SZ",
            stock_name="P2 Full Sample",
            force_backtest=True,
            materialize_artifacts=True,
            run_evaluation=True,
            reviewer="unit",
        )
    )

    assert response.created is True
    assert response.portfolio_snapshot_id
    assert response.run_id
    assert response.signal_id
    assert response.backtest_run_id
    assert response.loop_id
    assert response.iteration_id
    assert response.case_id
    assert response.knowledge_item_id
    assert response.patch_id
    assert response.evaluation_id
    assert response.knowledge_version_id
    assert response.sample_loop and response.sample_loop.detail
    assert {step.key for step in response.steps} == {
        "portfolio",
        "run",
        "signalops",
        "backtest",
        "research",
        "knowledge",
        "case",
        "evaluation",
        "knowledge_version",
    }
    step_by_key = {step.key: step for step in response.steps}
    for step in response.steps:
        assert step.evidence_usage == "review_gate_only"
        assert step.evidence_strength not in {"HIGH", "STRONG", "PRIMARY_EVIDENCE"}
        assert step.simulation_only is True
        assert step.is_real_trade is False
        assert step.strong_conclusion_allowed is False
    assert all(
        step.status == "PASS"
        for key, step in step_by_key.items()
        if key not in {"backtest", "knowledge_version"}
    )
    assert step_by_key["backtest"].status == "WARN"
    assert step_by_key["backtest"].evidence_strength in {"LOW", "MEDIUM", "UNKNOWN"}
    assert step_by_key["backtest"].next_action == "review_evidence"
    assert any(
        "supporting evidence" in item or "mock or fallback" in item
        for item in step_by_key["backtest"].missing_items
    )
    assert response.knowledge_version_status == "review"
    assert step_by_key["knowledge_version"].status == "WARN"
    assert step_by_key["knowledge_version"].evidence_strength in {"LOW", "MEDIUM"}
    assert step_by_key["knowledge_version"].next_action == "review_knowledge_version"
    assert any(
        "cannot activate feedback acceptance" in item
        for item in step_by_key["knowledge_version"].missing_items
    )


@pytest.mark.asyncio
async def test_materialize_iteration_artifacts_links_case_knowledge_error_patch_and_evaluation(research_store):
    run = sample_run()
    routes_analysis.runs_store[run["runId"]] = run

    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="P5 artifact loop",
            objective="Materialize research outputs into reusable assets.",
            hypothesis="Regressed evidence should create a patch candidate.",
            target_modules=["signalops", "knowledge"],
        )
    )
    iteration = detail.iterations[0]
    await research_store.record_feedback(
        iteration.iteration_id,
        ResearchIterationFeedbackRequest(
            action="PATCH",
            verdict="PATCH_REQUIRED",
            status="PATCH_REQUIRED",
            linked_run_id=run["runId"],
            note="Regression requires a patch candidate.",
        ),
    )

    result = await research_artifact_store.materialize_iteration_artifacts(
        iteration.iteration_id,
        ResearchArtifactMaterializeRequest(
            run_evaluation=True,
            note="Create P5 closed-loop artifacts.",
            reviewer="unit",
        ),
    )

    assert result is not None
    assert result.case is not None
    assert result.knowledge_item is not None
    assert result.error_entry is not None
    assert result.patch is not None
    assert result.evaluation is not None
    assert result.iteration.linked_case_id == result.case.case_id
    assert result.iteration.linked_knowledge_item_id == result.knowledge_item.item_id
    assert result.iteration.linked_patch_id == result.patch.patch_id
    assert result.knowledge_item.source_run_id == run["runId"]
    assert f"iteration:{iteration.iteration_id}" in result.knowledge_item.tags
    assert result.error_entry.attribution["iteration_id"] == iteration.iteration_id
    assert result.patch.source_case_id == result.case.case_id
    assert result.patch.source_error_id == result.error_entry.entry_id
    assert result.patch.patch_content["research_iteration_id"] == iteration.iteration_id
    assert result.evaluation.patch_id == result.patch.patch_id
    assert f"run:{run['runId']}" in result.provenance_chain
    assert any(item.source_type == "PATCH" for item in result.iteration.evidence_links)


@pytest.mark.asyncio
async def test_materialize_iteration_artifacts_is_idempotent(research_store):
    run = sample_run("RUN_RESEARCH_P5_002")
    routes_analysis.runs_store[run["runId"]] = run
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="P5 idempotent loop",
            objective="Repeated materialization should reuse linked assets.",
            hypothesis="Accepted evidence can become a reusable patch candidate.",
            target_modules=["case_library"],
        )
    )
    iteration = detail.iterations[0]
    await research_store.record_feedback(
        iteration.iteration_id,
        ResearchIterationFeedbackRequest(
            action="ACCEPT",
            verdict="ACCEPTED",
            status="ACCEPTED",
            linked_run_id=run["runId"],
        ),
    )

    request = ResearchArtifactMaterializeRequest(create_error_entry=False, run_evaluation=False)
    first = await research_artifact_store.materialize_iteration_artifacts(iteration.iteration_id, request)
    second = await research_artifact_store.materialize_iteration_artifacts(iteration.iteration_id, request)

    assert first is not None and second is not None
    assert first.case and second.case
    assert first.knowledge_item and second.knowledge_item
    assert first.patch and second.patch
    assert first.case.case_id == second.case.case_id
    assert first.knowledge_item.item_id == second.knowledge_item.item_id
    assert first.patch.patch_id == second.patch.patch_id

    cases = await case_library_store.list_cases(limit=50)
    patches = await knowledge_patch_store.list_patches(limit=50)
    errors = await error_ledger_store.list_entries(limit=50)
    assert len([item for item in cases if item["run_id"] == run["runId"]]) == 1
    assert len([item for item in patches if item["patch_content"].get("research_iteration_id") == iteration.iteration_id]) == 1
    assert errors == []


@pytest.mark.asyncio
async def test_materialize_iteration_artifacts_is_idempotent_under_concurrency(research_store):
    run = sample_run("RUN_RESEARCH_P5_CONCURRENT")
    routes_analysis.runs_store[run["runId"]] = run
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="P5 concurrent loop",
            objective="Concurrent materialization should not duplicate assets.",
            hypothesis="Accepted evidence can be materialized once.",
            target_modules=["signalops", "knowledge"],
        )
    )
    iteration = detail.iterations[0]
    await research_store.record_feedback(
        iteration.iteration_id,
        ResearchIterationFeedbackRequest(
            action="ACCEPT",
            verdict="ACCEPTED",
            status="ACCEPTED",
            linked_run_id=run["runId"],
        ),
    )

    request = ResearchArtifactMaterializeRequest(create_error_entry=False, run_evaluation=False)
    first, second = await asyncio.gather(
        research_artifact_store.materialize_iteration_artifacts(iteration.iteration_id, request),
        research_artifact_store.materialize_iteration_artifacts(iteration.iteration_id, request),
    )

    assert first is not None and second is not None
    assert first.case and second.case
    assert first.knowledge_item and second.knowledge_item
    assert first.patch and second.patch
    assert first.case.case_id == second.case.case_id
    assert first.knowledge_item.item_id == second.knowledge_item.item_id
    assert first.patch.patch_id == second.patch.patch_id

    detail = await research_store.get_loop_detail(iteration.loop_id)
    assert detail is not None
    materialize_events = [
        event for event in detail.iterations[0].feedback_events
        if event.action == "MATERIALIZE_ARTIFACTS"
    ]
    assert len(materialize_events) == 1

    cases = await case_library_store.list_cases(limit=50)
    patches = await knowledge_patch_store.list_patches(limit=50)
    assert len([item for item in cases if item["run_id"] == run["runId"]]) == 1
    assert len([item for item in patches if item["patch_content"].get("research_iteration_id") == iteration.iteration_id]) == 1


@pytest.mark.asyncio
async def test_materialize_iteration_artifacts_is_idempotent_across_store_instances(research_store, monkeypatch):
    run = sample_run("RUN_RESEARCH_P5_CROSS_PROCESS")
    routes_analysis.runs_store[run["runId"]] = run
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="P5 durable idempotent loop",
            objective="Separate materializer instances should still serialize through the database.",
            hypothesis="Accepted evidence must create one durable asset set.",
            target_modules=["signalops", "knowledge"],
        )
    )
    iteration = detail.iterations[0]
    await research_store.record_feedback(
        iteration.iteration_id,
        ResearchIterationFeedbackRequest(
            action="ACCEPT",
            verdict="ACCEPTED",
            status="ACCEPTED",
            linked_run_id=run["runId"],
        ),
    )

    original_create_case = case_library_store.create_case

    async def slow_create_case(*args, **kwargs):
        await asyncio.sleep(0.05)
        return await original_create_case(*args, **kwargs)

    monkeypatch.setattr(case_library_store, "create_case", slow_create_case)

    request = ResearchArtifactMaterializeRequest(create_error_entry=False, run_evaluation=False)
    first_store = ResearchArtifactStore()
    second_store = ResearchArtifactStore()
    first, second = await asyncio.gather(
        first_store.materialize_iteration_artifacts(iteration.iteration_id, request),
        second_store.materialize_iteration_artifacts(iteration.iteration_id, request),
    )

    assert first is not None and second is not None
    assert first.case and second.case
    assert first.knowledge_item and second.knowledge_item
    assert first.patch and second.patch
    assert first.case.case_id == second.case.case_id
    assert first.knowledge_item.item_id == second.knowledge_item.item_id
    assert first.patch.patch_id == second.patch.patch_id

    detail = await research_store.get_loop_detail(iteration.loop_id)
    assert detail is not None
    materialize_events = [
        event for event in detail.iterations[0].feedback_events
        if event.action == "MATERIALIZE_ARTIFACTS"
    ]
    assert len(materialize_events) == 1

    cases = await case_library_store.list_cases(limit=50)
    patches = await knowledge_patch_store.list_patches(limit=50)
    assert len([item for item in cases if item["run_id"] == run["runId"]]) == 1
    assert len([item for item in patches if item["patch_content"].get("research_iteration_id") == iteration.iteration_id]) == 1

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ResearchArtifactMaterializationDB).where(
                ResearchArtifactMaterializationDB.iteration_id == iteration.iteration_id
            )
        )
        record = result.scalar_one_or_none()
    assert record is not None
    assert record.status == "COMPLETED"


@pytest.mark.asyncio
async def test_materialize_iteration_artifacts_recovers_unlinked_partial_assets(research_store):
    run = sample_run("RUN_RESEARCH_P5_PARTIAL")
    routes_analysis.runs_store[run["runId"]] = run
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="P5 partial recovery loop",
            objective="Retry should reuse unlinked assets from a partial materialization failure.",
            hypothesis="Partial assets keep Research Lab provenance.",
            target_modules=["signalops", "knowledge"],
        )
    )
    iteration = detail.iterations[0]
    await research_store.record_feedback(
        iteration.iteration_id,
        ResearchIterationFeedbackRequest(
            action="PATCH",
            verdict="PATCH_REQUIRED",
            status="PATCH_REQUIRED",
            linked_run_id=run["runId"],
        ),
    )

    case = await case_library_store.create_case(run, reviewer="unit")
    reviewed_case = await case_library_store.update_case_review(
        case.case_id,
        {
            "tags": ["research_lab", f"iteration:{iteration.iteration_id}"],
            "review_status": "PENDING",
        },
    )
    error = await error_ledger_store.create_entry(
        run,
        {
            "node": "research_lab",
            "error_type": "RESEARCH_PATCH_REQUIRED",
            "error_reason": "partial failure recovery",
            "patch_required": True,
            "attribution": {
                "source": "research_lab",
                "loop_id": iteration.loop_id,
                "iteration_id": iteration.iteration_id,
            },
        },
    )
    patch = await knowledge_patch_store.create_patch(
        title="Partial recovery patch",
        reason="Created before feedback links were written.",
        affected_modules=["signalops", "knowledge"],
        patch_content={
            "research_loop_id": iteration.loop_id,
            "research_iteration_id": iteration.iteration_id,
            "engine_verdict": "PATCH_REQUIRED",
        },
        source_error_id=error.entry_id,
        source_case_id=case.case_id,
    )

    result = await research_artifact_store.materialize_iteration_artifacts(
        iteration.iteration_id,
        ResearchArtifactMaterializeRequest(run_evaluation=False),
    )

    assert result is not None
    assert result.case is not None
    assert result.error_entry is not None
    assert result.patch is not None
    assert reviewed_case is not None
    assert result.case.case_id == reviewed_case["case_id"]
    assert result.error_entry.entry_id == error.entry_id
    assert result.patch.patch_id == patch.patch_id
    assert result.iteration.linked_case_id == case.case_id
    assert result.iteration.linked_patch_id == patch.patch_id

    cases = await case_library_store.list_cases(limit=50)
    errors = await error_ledger_store.list_entries(limit=50)
    patches = await knowledge_patch_store.list_patches(limit=50)
    assert len([item for item in cases if item["run_id"] == run["runId"]]) == 1
    assert len([item for item in errors if item["attribution"].get("iteration_id") == iteration.iteration_id]) == 1
    assert len([item for item in patches if item["patch_content"].get("research_iteration_id") == iteration.iteration_id]) == 1


@pytest.mark.asyncio
async def test_materialize_patch_content_cannot_override_provenance(research_store):
    run = sample_run("RUN_RESEARCH_P5_RESERVED_PATCH")
    routes_analysis.runs_store[run["runId"]] = run
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="P5 reserved patch content",
            objective="Caller patch content must not override Research Lab provenance.",
            hypothesis="Patch provenance is system owned.",
            target_modules=["knowledge"],
        )
    )
    iteration = detail.iterations[0]
    await research_store.record_feedback(
        iteration.iteration_id,
        ResearchIterationFeedbackRequest(
            action="PATCH",
            verdict="PATCH_REQUIRED",
            status="PATCH_REQUIRED",
            linked_run_id=run["runId"],
        ),
    )

    result = await research_artifact_store.materialize_iteration_artifacts(
        iteration.iteration_id,
        ResearchArtifactMaterializeRequest(
            create_case=False,
            create_knowledge_item=False,
            create_error_entry=False,
            patch_content={
                "research_iteration_id": "CALLER_OVERRIDE",
                "engine_verdict": "CALLER_OVERRIDE",
                "frontend_action": "unit_test",
            },
        ),
    )

    assert result is not None
    assert result.patch is not None
    assert result.patch.patch_content["research_iteration_id"] == iteration.iteration_id
    assert result.patch.patch_content["engine_verdict"] != "CALLER_OVERRIDE"
    assert result.patch.patch_content["frontend_action"] == "unit_test"
    assert "patch_content_reserved_keys_ignored:engine_verdict,research_iteration_id" in result.warnings


@pytest.mark.asyncio
async def test_materialize_patch_content_does_not_bypass_verdict_gate(research_store):
    run = sample_run("RUN_RESEARCH_P5_PENDING_PATCH_GATE")
    routes_analysis.runs_store[run["runId"]] = run
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="P5 pending patch gate",
            objective="Pending research should not create patch candidates only because payload has patch content.",
            hypothesis="Pending evidence still needs review.",
            target_modules=["knowledge"],
        )
    )
    iteration = detail.iterations[0]
    await research_store.record_feedback(
        iteration.iteration_id,
        ResearchIterationFeedbackRequest(
            action="REVIEW",
            verdict="PENDING",
            status="DRAFT",
            linked_run_id=run["runId"],
        ),
    )

    result = await research_artifact_store.materialize_iteration_artifacts(
        iteration.iteration_id,
        ResearchArtifactMaterializeRequest(
            create_case=False,
            create_knowledge_item=False,
            create_error_entry=False,
            patch_content={"frontend_action": "materialize"},
        ),
    )

    assert result is not None
    assert result.patch is None
    assert "patch_skipped_verdict_not_actionable" in result.warnings


@pytest.mark.asyncio
async def test_materialize_reuses_existing_patch_even_when_current_verdict_is_pending(research_store):
    run = sample_run("RUN_RESEARCH_P5_EXISTING_PATCH")
    routes_analysis.runs_store[run["runId"]] = run
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="P5 existing patch loop",
            objective="Existing patch links should stay reusable after a verdict reset.",
            hypothesis="A previously linked patch remains part of provenance.",
            target_modules=["knowledge"],
        )
    )
    iteration = detail.iterations[0]
    accepted = await research_store.record_feedback(
        iteration.iteration_id,
        ResearchIterationFeedbackRequest(
            action="ACCEPT",
            verdict="ACCEPTED",
            status="ACCEPTED",
            linked_run_id=run["runId"],
        ),
    )
    assert accepted is not None

    first = await research_artifact_store.materialize_iteration_artifacts(
        iteration.iteration_id,
        ResearchArtifactMaterializeRequest(create_error_entry=False),
    )
    assert first is not None and first.patch is not None

    await research_store.record_feedback(
        iteration.iteration_id,
        ResearchIterationFeedbackRequest(
            action="REVIEW",
            verdict="PENDING",
            status="DRAFT",
            linked_run_id=run["runId"],
        ),
    )
    second = await research_artifact_store.materialize_iteration_artifacts(
        iteration.iteration_id,
        ResearchArtifactMaterializeRequest(
            create_error_entry=False,
            run_evaluation=True,
            patch_content={"frontend_action": "materialize_and_evaluate"},
        ),
    )

    assert second is not None
    assert second.patch is not None
    assert second.patch.patch_id == first.patch.patch_id
    assert second.evaluation is not None
    assert "patch_skipped_verdict_not_actionable" not in second.warnings

    patches = await knowledge_patch_store.list_patches(limit=50)
    assert len([item for item in patches if item["patch_content"].get("research_iteration_id") == iteration.iteration_id]) == 1


@pytest.mark.asyncio
async def test_materialize_iteration_artifacts_route_returns_404_for_missing_iteration():
    with pytest.raises(HTTPException) as exc_info:
        await routes_research.materialize_research_iteration_artifacts(
            "RITER_MISSING",
            ResearchArtifactMaterializeRequest(),
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_materialize_iteration_artifacts_route_returns_409_when_locked(research_store, monkeypatch):
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="P5 locked loop",
            objective="A running materialization lease should return a retryable conflict.",
            hypothesis="Concurrent materialization is still running.",
            target_modules=["knowledge"],
        )
    )
    iteration = detail.iterations[0]
    async with AsyncSessionLocal() as db:
        db.add(
            ResearchArtifactMaterializationDB(
                iteration_id=iteration.iteration_id,
                status="RUNNING",
                owner_token="external-worker",
                request_json={},
                artifact_links={},
                started_at="2999-01-01T00:00:00+00:00",
                updated_at="2999-01-01T00:00:00+00:00",
            )
        )
        await db.commit()

    monkeypatch.setattr(research_artifact_module, "MATERIALIZATION_WAIT_TIMEOUT_SECONDS", 0)

    with pytest.raises(HTTPException) as exc_info:
        await routes_research.materialize_research_iteration_artifacts(
            iteration.iteration_id,
            ResearchArtifactMaterializeRequest(),
        )

    assert exc_info.value.status_code == 409
