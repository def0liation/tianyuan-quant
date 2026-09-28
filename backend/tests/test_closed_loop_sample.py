import pytest
import httpx
from sqlalchemy import func, select

from app.api import routes_analysis, routes_research
from app.core.case_library_store import knowledge_patch_store
from app.core.evaluation_store import knowledge_version_store
from app.core import knowledge_store
from app.core.research_artifact_store import research_artifact_store
from app.core.signalops_store import signalops_store
from app.db import models as m
from app.db import models_backtest as mb
from app.db import models_case_library as mc
from app.db import models_research as mr
from app.db.session import AsyncSessionLocal
from app.main import app
from app.models.research import (
    CreateSampleResearchLoopRequest,
    ResearchArtifactMaterializeRequest,
)


@pytest.fixture(autouse=True)
def temp_knowledge_store(monkeypatch, tmp_path):
    monkeypatch.setattr(knowledge_store, "STORAGE_FILE", tmp_path / "knowledge_iterations.json")


def _sample_run(run_id: str = "RUN_CLOSED_LOOP_SAMPLE_001") -> dict:
    return {
        "runId": run_id,
        "auditId": f"AUD_{run_id}",
        "stockCode": "P2WEAK.SZ",
        "stockName": "P2 Weak Sample",
        "taskType": "P2_CLOSED_LOOP_SAMPLE",
        "runMode": "STANDARD_MODE",
        "status": "COMPLETED",
        "createdAt": "2026-05-20T01:00:00+00:00",
        "updatedAt": "2026-05-20T01:00:00+00:00",
        "finalAction": "WAIT",
        "finalWriter": {"finalAction": "WAIT", "humanConfirmationRequired": True},
        "compressedSummary": {"quality": {"score": 82, "level": "MEDIUM"}},
        "qiam": {"modelConfidenceFinal": 0.72, "finalBuySuitability": "WATCH"},
        "dvg": {"status": "PASS"},
        "signalOps": {
            "signalStatus": "WATCH",
            "riskPassed": True,
            "dvgPassed": True,
            "qiamPassed": True,
            "executionReachable": True,
            "triggerConditions": ["sample trigger"],
            "invalidationConditions": ["sample invalidation"],
        },
        "portfolioSnapshot": {
            "snapshotId": "PSNAP_CLOSED_LOOP_SAMPLE",
            "updatedAt": "2026-05-20T01:00:00+00:00",
            "positions": [
                {
                    "symbol": "P2WEAK.SZ",
                    "name": "P2 Weak Sample",
                    "shares": 1000,
                    "weight": 0.1,
                }
            ],
        },
        "portfolio": {
            "portfolioCoverage": "HOLDINGS_CONNECTED",
            "snapshotId": "PSNAP_CLOSED_LOOP_SAMPLE",
            "holdings": [
                {
                    "symbol": "P2WEAK.SZ",
                    "name": "P2 Weak Sample",
                    "shares": 1000,
                    "weight": 0.1,
                }
            ],
        },
    }


async def _table_count(model) -> int:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(func.count()).select_from(model))
        return int(result.scalar_one())


@pytest.mark.asyncio
async def test_closed_loop_sample_keeps_backtest_supporting_and_artifacts_idempotent(monkeypatch):
    run = _sample_run()
    monkeypatch.setattr(routes_analysis, "runs_store", {run["runId"]: run})

    response = await routes_research.create_sample_research_loop_route(
        CreateSampleResearchLoopRequest(
            run_id=run["runId"],
            symbol=run["stockCode"],
            force_backtest=True,
            materialize_artifacts=True,
            run_evaluation=True,
            reviewer="unit",
        )
    )

    assert response.created is True
    assert response.detail is not None
    assert response.artifact_context["case_id"]
    assert response.artifact_context["knowledge_item_id"]
    assert response.artifact_context["patch_id"]
    assert response.artifact_context["evaluation_id"]

    backtest_strength = response.context["backtest_evidence_strength"]
    assert backtest_strength["grade"] in {"LOW", "MEDIUM"}
    assert backtest_strength["weakSample"] is True
    assert backtest_strength["canSupportResearchVerdict"] is False
    assert backtest_strength["researchUsage"] == "supporting_only"
    assert any("supporting evidence" in reason for reason in response.missing_reasons)
    assert any("mock or fallback market data" in reason for reason in response.missing_reasons)

    iteration = response.detail.iterations[0]
    assert iteration.metrics["sample_loop"] is True
    assert iteration.metrics["sample_evidence_usage"] == "supporting_only"
    assert iteration.metrics["backtest_evidence_strength"] == backtest_strength
    assert iteration.metrics["backtest_sample_window"]["isSmallSample"] is True
    backtest_link = next(item for item in iteration.evidence_links if item.source_type == "BACKTEST")
    assert backtest_link.quality in {"LOW", "MEDIUM", "UNKNOWN"}
    assert backtest_link.quality != "HIGH"

    rematerialized = await research_artifact_store.materialize_iteration_artifacts(
        iteration.iteration_id,
        ResearchArtifactMaterializeRequest(
            create_case=True,
            create_knowledge_item=True,
            create_error_entry=True,
            create_patch=True,
            run_evaluation=True,
            reviewer="unit",
            note="Repeat closed-loop sample materialization.",
            patch_content={"source": "p2_closed_loop_sample"},
        ),
    )

    assert rematerialized is not None
    assert rematerialized.case and rematerialized.case.case_id == response.artifact_context["case_id"]
    assert rematerialized.knowledge_item
    assert rematerialized.knowledge_item.item_id == response.artifact_context["knowledge_item_id"]
    assert rematerialized.knowledge_item.confidence in {"LOW", "MEDIUM"}
    assert rematerialized.patch and rematerialized.patch.patch_id == response.artifact_context["patch_id"]
    assert rematerialized.evaluation
    assert rematerialized.evaluation.eval_id == response.artifact_context["evaluation_id"]
    rematerialized_links = {
        (item.source_type, item.source_id): item
        for item in rematerialized.iteration.evidence_links
    }
    knowledge_link = rematerialized_links[("KNOWLEDGE", rematerialized.knowledge_item.item_id)]
    evaluation_link = rematerialized_links[("EVALUATION", rematerialized.evaluation.eval_id)]
    assert knowledge_link.quality == rematerialized.knowledge_item.confidence
    assert evaluation_link.quality == "MEDIUM"
    materialized_link_keys = {
        ("CASE", rematerialized.case.case_id),
        ("KNOWLEDGE", rematerialized.knowledge_item.item_id),
        ("PATCH", rematerialized.patch.patch_id),
        ("EVALUATION", rematerialized.evaluation.eval_id),
    }
    assert all(
        rematerialized_links[key].quality not in {"HIGH", "PASS", "READY", "STRONG", "PRIMARY", "PRIMARY_EVIDENCE"}
        for key in materialized_link_keys
    )


@pytest.mark.asyncio
async def test_sample_loop_reuses_backtest_by_default_and_force_rebuilds(monkeypatch):
    run = _sample_run("RUN_CLOSED_LOOP_REUSE_001")
    monkeypatch.setattr(routes_analysis, "runs_store", {run["runId"]: run})

    first = await routes_research.create_sample_research_loop_route(
        CreateSampleResearchLoopRequest(
            run_id=run["runId"],
            symbol=run["stockCode"],
            reviewer="unit",
        )
    )
    second = await routes_research.create_sample_research_loop_route(
        CreateSampleResearchLoopRequest(
            run_id=run["runId"],
            symbol=run["stockCode"],
            reviewer="unit",
        )
    )
    forced = await routes_research.create_sample_research_loop_route(
        CreateSampleResearchLoopRequest(
            run_id=run["runId"],
            symbol=run["stockCode"],
            force_backtest=True,
            reviewer="unit",
        )
    )

    assert first.context["backtest_run_id"]
    assert second.context["backtest_run_id"] == first.context["backtest_run_id"]
    assert second.context["backtest_created"] is False
    assert forced.context["backtest_run_id"] != first.context["backtest_run_id"]
    assert forced.context["backtest_created"] is True
    assert await _table_count(mb.BacktestRunDB) == 2


@pytest.mark.asyncio
async def test_p2_closed_loop_sample_route_materializes_full_chain(monkeypatch):
    async def fake_runtime_summary():
        return {"runtimeProfiles": [], "pluginRuntimePlan": {"mode": "READ_ONLY_NO_CODE"}}

    async def fake_hydrate_run_with_market_data(run_data: dict, symbol: str):
        run_data["stockName"] = f"Route {symbol}"
        run_data["dataMode"] = "LIVE"
        run_data["marketData"] = {
            "symbol": symbol,
            "provider": "unit-test",
            "dataMode": "LIVE",
            "latestPrice": 10.0,
        }
        run_data["dataSources"] = {
            "overallStatus": "READY",
            "overallDataMode": "LIVE",
            "sources": {},
        }
        return run_data

    def fake_apply_agent_framework_to_run(run_data: dict, request: dict, runtime_summary: dict):
        run_data["agentRuntime"] = runtime_summary
        run_data["agentResults"] = [
            {
                "audit_id": run_data.get("auditId") or f"AUD_{run_data['runId']}",
                "name": "orchestrator",
                "node": "orchestrator",
                "status": "PASS",
                "confidence": "HIGH",
                "data": {"source": "closed_loop_participation_smoke"},
            }
        ]
        return run_data

    monkeypatch.setattr(routes_analysis, "runs_store", {})
    monkeypatch.setattr(routes_analysis, "_runtime_summary_with_plugin_plan", fake_runtime_summary)
    monkeypatch.setattr(routes_analysis, "hydrate_run_with_market_data", fake_hydrate_run_with_market_data)
    monkeypatch.setattr(routes_analysis, "apply_agent_framework_to_run", fake_apply_agent_framework_to_run)
    monkeypatch.setattr(routes_analysis, "get_active_knowledge_context", lambda: [])
    monkeypatch.setattr(routes_analysis, "save_run", lambda _run_data: None)

    payload = {
        "symbol": "P2RT01.SZ",
        "stock_name": "P2 Route Sample",
        "force_backtest": True,
        "materialize_artifacts": True,
        "run_evaluation": True,
        "promote_knowledge_version": True,
        "reviewer": "route-test",
    }

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post("/api/research/p2/closed-loop-sample", json=payload)

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["created"] is True
    assert data["simulation_only"] is True
    assert data["is_real_trade"] is False
    assert data["portfolio_snapshot_id"]
    assert data["run_id"]
    assert data["signal_id"]
    assert data["backtest_run_id"]
    assert data["loop_id"]
    assert data["iteration_id"]
    assert data["case_id"]
    assert data["knowledge_item_id"]
    assert data["patch_id"]
    assert data["evaluation_id"]
    assert data["knowledge_version_id"]
    assert data["knowledge_version_status"] == "review"
    assert data["sample_loop"]["artifact_context"]["knowledge_version_status"] == "review"
    assert any("review status" in warning for warning in data["warnings"])

    version = await knowledge_version_store.get_version(data["knowledge_version_id"])
    assert version is not None
    assert version["status"] == "review"
    assert version["source_patch_id"] == data["patch_id"]
    assert version["evidence_usage"] == "review_gate_only"
    assert version["evidence_strength"] in {"LOW", "MEDIUM"}
    assert version["strong_conclusion_allowed"] is False

    patch = await knowledge_patch_store.get_patch(data["patch_id"])
    assert patch is not None
    assert patch["approval_status"] == "CANDIDATE"

    steps = {step["key"]: step for step in data["steps"]}
    assert set(steps) == {
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
    assert all(
        step["status"] == "PASS"
        for key, step in steps.items()
        if key not in {"backtest", "knowledge_version"}
    )
    assert steps["backtest"]["ref_id"] == data["backtest_run_id"]
    assert steps["backtest"]["status"] == "WARN"
    assert steps["backtest"]["evidence_strength"] in {"LOW", "MEDIUM", "UNKNOWN"}
    assert steps["backtest"]["next_action"] == "review_evidence"
    assert steps["backtest"]["next_action_label"] == "Review evidence"
    assert any(
        "supporting evidence" in item or "mock or fallback" in item
        for item in steps["backtest"]["missing_items"]
    )
    assert steps["knowledge_version"]["ref_id"] == data["knowledge_version_id"]
    assert steps["knowledge_version"]["status"] == "WARN"
    assert steps["knowledge_version"]["note"] == "Knowledge version staged for review"
    assert steps["knowledge_version"]["evidence_strength"] in {"LOW", "MEDIUM"}
    assert steps["knowledge_version"]["next_action"] == "review_knowledge_version"
    assert steps["knowledge_version"]["next_action_label"] == "Review knowledge version"
    assert any(
        "cannot activate feedback acceptance" in item
        for item in steps["knowledge_version"]["missing_items"]
    )
    for step in steps.values():
        assert step["evidence_usage"] == "review_gate_only"
        assert step["evidence_strength"] != "HIGH"
        assert step["simulation_only"] is True
        assert step["is_real_trade"] is False
        assert step["strong_conclusion_allowed"] is False
        assert isinstance(step["missing_items"], list)
        assert isinstance(step["next_action"], str)
        assert isinstance(step["next_action_label"], str)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        detail_response = await client.get(f"/api/research/loops/{data['loop_id']}")

    assert detail_response.status_code == 200, detail_response.text
    detail_data = detail_response.json()
    workflow_state = detail_data["workflow_state"]
    workflow_steps = {step["key"]: step for step in workflow_state["steps"]}
    assert workflow_steps["portfolio"]["ref_id"] == data["portfolio_snapshot_id"]
    assert workflow_steps["run"]["ref_id"] == data["run_id"]
    assert workflow_steps["backtest"]["ref_id"] == data["backtest_run_id"]
    assert workflow_steps["knowledge_version"]["ref_id"] == data["knowledge_version_id"]
    assert workflow_state["evidence_usage"] == "review_gate_only"
    assert workflow_state["simulation_only"] is True
    assert workflow_state["is_real_trade"] is False
    assert workflow_state["strong_conclusion_allowed"] is False
    for step in workflow_steps.values():
        assert step["evidence_usage"] == "review_gate_only"
        assert step["evidence_strength"] != "HIGH"
        assert step["simulation_only"] is True
        assert step["is_real_trade"] is False
        assert step["strong_conclusion_allowed"] is False
    assert workflow_state["stage"] == "needs_evidence_review"
    assert any("supporting-only" in reason or "mock or fallback" in reason for reason in workflow_state["blocking_reasons"])

    paper_portfolio, portfolio_error = await signalops_store.create_paper_portfolio(
        data["signal_id"],
        {
            "run_id": data["run_id"],
            "audit_id": f"AUD_PAPER_{data['run_id']}",
            "initial_cash": 100000,
            "risk_budget": {"source": "closed_loop_participation_smoke"},
        },
    )
    assert portfolio_error is None
    assert paper_portfolio and paper_portfolio["simulation_only"] is True
    assert paper_portfolio["is_real_trade"] is False

    paper_order, order_error = await signalops_store.create_paper_order(
        data["signal_id"],
        {
            "run_id": data["run_id"],
            "audit_id": f"AUD_PAPER_ORDER_{data['run_id']}",
            "action": "SIM_BUY",
            "action_reason": "closed-loop participation smoke",
            "simulated_price": 10.0,
            "simulated_quantity": 100,
            "risk_constraints": {"source": "closed_loop_participation_smoke"},
        },
    )
    assert order_error is None
    assert paper_order and paper_order["action"] == "SIM_BUY"
    assert paper_order["simulation_only"] is True
    assert paper_order["is_real_trade"] is False

    job = routes_analysis.analysis_job_store.start_job(
        data["run_id"],
        operator="closed-loop-participation-smoke",
    )
    assert job["run_id"] == data["run_id"]
    assert job["status"] == "QUEUED"

    assert await _table_count(m.AnalysisRunDB) >= 1
    assert await _table_count(m.AgentResultDB) >= 1
    assert routes_analysis.analysis_job_store.get_sqlite_job(data["run_id"])
    assert await _table_count(m.PortfolioSnapshotDB) >= 1
    assert await _table_count(m.HoldingPositionDB) >= 1
    assert await _table_count(m.SignalDB) >= 1
    assert await _table_count(m.PaperOrderDB) >= 1
    assert await _table_count(mb.BacktestRunDB) >= 1
    assert await _table_count(mb.BacktestSignalDB) >= 1
    assert await _table_count(mr.ResearchLoopDB) >= 1
    assert await _table_count(mr.ResearchIterationDB) >= 1
    assert await _table_count(mr.ResearchEvidenceLinkDB) >= 1
    assert await _table_count(mc.CaseLibraryDB) >= 1
    assert await _table_count(mc.KnowledgePatchDB) >= 1
    assert await _table_count(mc.KnowledgeVersionDB) >= 1
    assert await _table_count(mc.EvaluationRunDB) >= 1
