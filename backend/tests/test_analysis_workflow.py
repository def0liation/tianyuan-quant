import asyncio
import copy
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from app.api import routes_analysis, routes_research
from app.core import (
    agent_runtime_store,
    analysis_worker,
    research_verdict_store,
)
from app.main import app
from app.mock.scenarios import mock_scenarios
from app.models.analysis import CreateAnalysisRequest
from app.models.portfolio import HoldingPosition, PortfolioSnapshot


def _startup_index_run(run_id: str = "RUN_20260525_120000_lazy0001") -> dict:
    return {
        "runId": run_id,
        "status": "COMPLETED",
        "stockCode": "603663",
        "stockName": "KLD",
        "taskType": "position_review",
        "runMode": "STANDARD_MODE",
        "finalAction": "WAIT",
        "createdAt": "2026-05-25T12:00:00",
        "updatedAt": "2026-05-25T12:01:00",
        "nodes": [{"id": "router", "name": "Router", "status": "PASS"}],
        "agentResults": [],
        "auditLog": [],
    }


def test_analysis_run_summary_index_does_not_force_full_history_load(monkeypatch):
    routes_analysis.runs_store.clear()
    monkeypatch.setattr(routes_analysis, "_analysis_history_loaded", False)
    index_path = routes_analysis._history_index_path()
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps([
            {
                "runId": "RUN_20260525_120000_lazy0001",
                "stockCode": "603663",
                "status": "COMPLETED",
                "createdAt": "2026-05-25T12:00:00",
                "updatedAt": "2026-05-25T12:01:00",
            }
        ]),
        encoding="utf-8",
    )

    summaries = routes_analysis._list_analysis_run_summaries_sync()

    assert summaries == [
        {
            "runId": "RUN_20260525_120000_lazy0001",
            "stockCode": "603663",
            "status": "COMPLETED",
            "createdAt": "2026-05-25T12:00:00",
            "updatedAt": "2026-05-25T12:01:00",
        }
    ]
    assert routes_analysis.runs_store == {}


def test_analysis_run_summary_index_fast_path_after_history_loaded(monkeypatch):
    routes_analysis.runs_store.clear()
    monkeypatch.setattr(routes_analysis, "_analysis_history_loaded", True)
    index_summary = {
        "runId": "RUN_20260525_120000_indexed001",
        "stockCode": "603663",
        "stockName": "KLD",
        "taskType": "position_review",
        "runMode": "STANDARD_MODE",
        "status": "COMPLETED",
        "finalAction": "WAIT",
        "createdAt": "2026-05-25T12:00:00",
        "updatedAt": "2026-05-25T12:01:00",
    }
    index_path = routes_analysis._history_index_path()
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps([index_summary]), encoding="utf-8")

    def fail_full_history_load():
        raise AssertionError("summary list should not load full persisted history")

    def fail_per_summary_job_lookup(run_id: str):
        raise AssertionError(f"summary list should not look up indexed job {run_id}")

    monkeypatch.setattr(routes_analysis, "load_persisted_runs", fail_full_history_load)
    monkeypatch.setattr(routes_analysis.analysis_job_store, "get_job", fail_per_summary_job_lookup)

    summaries = routes_analysis._list_analysis_run_summaries_sync()

    assert summaries == [index_summary]
    assert routes_analysis.runs_store == {}


def test_warm_analysis_history_index_uses_existing_summary_index_fast_path(monkeypatch):
    routes_analysis.runs_store.clear()
    monkeypatch.setattr(routes_analysis, "_analysis_history_loaded", False)
    monkeypatch.setattr(routes_analysis, "_analysis_history_loading", False)
    index_summary = {
        "runId": "RUN_20260525_120000_indexed001",
        "stockCode": "603663",
        "stockName": "KLD",
        "taskType": "position_review",
        "runMode": "STANDARD_MODE",
        "status": "COMPLETED",
        "finalAction": "WAIT",
        "createdAt": "2026-05-25T12:00:00",
        "updatedAt": "2026-05-25T12:01:00",
    }
    agent_runtime_store.RUNS_DIR.mkdir(parents=True, exist_ok=True)
    for idx in range(178):
        (agent_runtime_store.RUNS_DIR / f"RUN_20260525_120000_{idx:03d}.json").write_text(
            "{not-valid-json",
            encoding="utf-8",
        )
    index_path = routes_analysis._history_index_path()
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps([index_summary]), encoding="utf-8")

    def fail_full_history_load():
        raise AssertionError("startup warmup should not load full persisted history when index exists")

    def fail_global_reconcile(source: str = "query"):
        raise AssertionError(f"startup warmup should not run global reconciliation from {source}")

    def fail_per_summary_job_lookup(run_id: str):
        raise AssertionError(f"startup warmup should not look up indexed job {run_id}")

    monkeypatch.setattr(routes_analysis, "load_persisted_runs", fail_full_history_load)
    monkeypatch.setattr(routes_analysis, "_reconcile_analysis_run_jobs", fail_global_reconcile)
    monkeypatch.setattr(routes_analysis.analysis_job_store, "get_job", fail_per_summary_job_lookup)

    result = routes_analysis.warm_analysis_history_index()

    assert result == {"loaded": 0, "indexed": 1}
    assert routes_analysis._analysis_history_loaded is True
    assert routes_analysis.runs_store == {}


def test_warm_analysis_history_index_rebuilds_when_summary_index_is_corrupt(monkeypatch):
    routes_analysis.runs_store.clear()
    monkeypatch.setattr(routes_analysis, "_analysis_history_loaded", False)
    monkeypatch.setattr(routes_analysis, "_analysis_history_loading", False)
    run = _startup_index_run("RUN_20260525_120000_rebuild001")
    routes_analysis._history_index_path().write_text("{not-valid-json", encoding="utf-8")
    written_summaries: list[dict] = []

    monkeypatch.setattr(routes_analysis, "load_persisted_runs", lambda: {run["runId"]: run})
    monkeypatch.setattr(routes_analysis, "_reconcile_analysis_run_jobs", lambda **_: None)
    monkeypatch.setattr(routes_analysis, "_write_summary_index", lambda summaries: written_summaries.extend(summaries))

    result = routes_analysis.warm_analysis_history_index()

    assert result == {"loaded": 1, "indexed": 1}
    assert routes_analysis.runs_store == {run["runId"]: run}
    assert [summary["runId"] for summary in written_summaries] == [run["runId"]]


def test_analysis_run_summary_index_overlays_loaded_recovered_run(monkeypatch, tmp_path):
    saved: list[dict] = []
    run_id = "RUN_20260525_120000_recovered001"
    index_summary = {
        "runId": run_id,
        "stockCode": "603663",
        "stockName": "KLD",
        "taskType": "position_review",
        "runMode": "STANDARD_MODE",
        "status": "RUNNING",
        "finalAction": "WAIT",
        "createdAt": "2000-01-01T00:00:00",
        "updatedAt": "2000-01-01T00:00:00",
    }
    index_path = routes_analysis._history_index_path()
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps([index_summary]), encoding="utf-8")
    monkeypatch.setattr(
        routes_analysis,
        "runs_store",
        {
            run_id: {
                **index_summary,
                "nodes": [{"id": "router", "status": "RUNNING", "isRunning": True}],
                "auditLog": [],
                "streamEvents": [],
            }
        },
    )
    monkeypatch.setattr(routes_analysis, "save_run", lambda run_data: saved.append(run_data.copy()))
    monkeypatch.setattr(routes_analysis.analysis_job_store, "STORAGE_FILE", tmp_path / "analysis_jobs.json")

    result = routes_analysis._list_analysis_run_summaries_sync()

    assert result[0]["runId"] == run_id
    assert result[0]["status"] == "STALE"
    assert result[0]["failureCategory"] == "STALE_RUN_RECOVERY"
    assert "watchdog" in result[0]["failReason"]
    assert result[0]["job"]["status"] == "STALE"
    assert saved and saved[-1]["status"] == "STALE"


def test_analysis_run_detail_lazy_loads_single_persisted_run(monkeypatch):
    routes_analysis.runs_store.clear()
    monkeypatch.setattr(routes_analysis, "_analysis_history_loaded", False)
    run = _startup_index_run()
    agent_runtime_store.save_run(run)

    loaded = routes_analysis._get_run_or_load(run["runId"])

    assert loaded is not None
    assert loaded["runId"] == run["runId"]
    assert routes_analysis.runs_store == {run["runId"]: loaded}


@pytest.mark.asyncio
async def test_analysis_run_detail_does_not_reconcile_unrelated_history(monkeypatch):
    requested_id = "RUN_DETAIL_FASTPATH_REQUESTED"
    unrelated_id = "RUN_DETAIL_FASTPATH_UNRELATED"
    requested = copy.deepcopy(mock_scenarios["normal_pass"])
    requested["runId"] = requested_id
    requested["auditId"] = f"AUD_{requested_id}"
    requested["status"] = "COMPLETED"
    requested["createdAt"] = "2026-05-25T12:00:00"
    requested["updatedAt"] = "2026-05-25T12:01:00"
    if isinstance(requested.get("finalWriter"), dict):
        requested["finalWriter"]["auditId"] = f"AUD_FW_{requested_id}"
    for event in requested.get("auditLog", []):
        event["runId"] = requested_id
        event["auditId"] = f"AUD_EVENT_{requested_id}"
    unrelated = {
        **_startup_index_run(unrelated_id),
        "status": "RUNNING",
        "updatedAt": "2000-01-01T00:00:00",
        "nodes": [{"id": "router", "name": "Router", "status": "RUNNING", "isRunning": True}],
    }
    monkeypatch.setattr(routes_analysis, "runs_store", {requested_id: requested, unrelated_id: unrelated})
    monkeypatch.setattr(routes_analysis.analysis_job_store, "get_job", lambda _run_id: None)
    monkeypatch.setattr(
        routes_analysis,
        "_reconcile_analysis_run_jobs",
        lambda source="detail": (_ for _ in ()).throw(AssertionError("detail should not run global reconciliation")),
    )

    result = await routes_analysis.get_analysis_run(requested_id)

    assert result["runId"] == requested_id
    assert routes_analysis.runs_store[unrelated_id]["status"] == "RUNNING"


@pytest.mark.asyncio
async def test_analysis_run_detail_adds_dashboard_summary_without_persisting(monkeypatch):
    run_id = "RUN_DETAIL_DASHBOARD_SUMMARY"
    requested = copy.deepcopy(mock_scenarios["normal_pass"])
    requested["runId"] = run_id
    requested["auditId"] = f"AUD_{run_id}"
    requested.pop("dashboardSummary", None)
    if isinstance(requested.get("finalWriter"), dict):
        requested["finalWriter"]["auditId"] = f"AUD_FW_{run_id}"
    for event in requested.get("auditLog", []):
        event["runId"] = run_id
        event["auditId"] = f"AUD_EVENT_{run_id}"
    monkeypatch.setattr(routes_analysis, "runs_store", {run_id: requested})
    monkeypatch.setattr(routes_analysis.analysis_job_store, "get_job", lambda _run_id: None)

    result = await routes_analysis.get_analysis_run(run_id)

    summary = result["dashboardSummary"]
    assert summary["schema"] == "analysis_dashboard_summary_v1"
    assert summary["decisionState"] == result["finalWriter"]["finalAction"]
    assert summary["tradeBoundary"] == {
        "simulationOnly": True,
        "isRealTrade": False,
        "humanConfirmationRequired": result["finalWriter"].get("humanConfirmationRequired") is not False,
    }
    assert summary["metrics"]["sourceTotalCount"] >= summary["metrics"]["sourceReadyCount"]
    assert isinstance(summary["blockers"], list)
    assert isinstance(summary["warnings"], list)
    assert isinstance(summary["nextReview"], list)
    assert "dashboardSummary" not in routes_analysis.runs_store[run_id]


@pytest.mark.asyncio
async def test_analysis_run_detail_normalizes_nullable_stream_event_node_ids(monkeypatch):
    run_id = "RUN_DETAIL_STREAM_EVENT_NORMALIZE"
    requested = copy.deepcopy(mock_scenarios["normal_pass"])
    requested["runId"] = run_id
    requested["auditId"] = f"AUD_{run_id}"
    if isinstance(requested.get("finalWriter"), dict):
        requested["finalWriter"]["auditId"] = f"AUD_FW_{run_id}"
    for event in requested.get("auditLog", []):
        event["runId"] = run_id
        event["auditId"] = f"AUD_EVENT_{run_id}"
    requested["streamEvents"] = [
        {
            "event_type": "RUN_STARTED",
            "run_id": run_id,
            "node_id": None,
            "message": "Analysis run started.",
            "payload": {},
            "audit_id": f"AUD_START_{run_id}",
            "timestamp": "2026-05-25T12:00:00",
        }
    ]
    monkeypatch.setattr(routes_analysis, "runs_store", {run_id: requested})
    monkeypatch.setattr(routes_analysis.analysis_job_store, "get_job", lambda _run_id: None)

    result = await routes_analysis.get_analysis_run(run_id)

    assert result["streamEvents"][0]["node_id"] == "system"


def test_warm_analysis_history_uses_snapshot_when_runs_store_changes(monkeypatch):
    routes_analysis.runs_store.clear()
    routes_analysis.runs_store["RUN_EXISTING"] = _startup_index_run("RUN_EXISTING")
    monkeypatch.setattr(routes_analysis, "_analysis_history_loaded", False)
    monkeypatch.setattr(routes_analysis, "load_persisted_runs", lambda: {})
    monkeypatch.setattr(routes_analysis, "_reconcile_analysis_run_jobs", lambda **_: None)
    monkeypatch.setattr(routes_analysis, "_write_summary_index", lambda summaries: None)

    original_summary = routes_analysis._summary_from_run

    def mutating_summary(run: dict):
        routes_analysis.runs_store.setdefault("RUN_ADDED_DURING_WARM", _startup_index_run("RUN_ADDED_DURING_WARM"))
        return original_summary(run)

    monkeypatch.setattr(routes_analysis, "_summary_from_run", mutating_summary)

    result = routes_analysis.warm_analysis_history_index()

    assert result["indexed"] == 1
    assert "RUN_ADDED_DURING_WARM" in routes_analysis.runs_store


def test_analysis_run_save_and_delete_keep_summary_index_current():
    routes_analysis.runs_store.clear()
    run = _startup_index_run()

    routes_analysis.save_run(run)
    summaries = routes_analysis._load_summary_index()

    assert [item["runId"] for item in summaries] == [run["runId"]]
    assert summaries[0]["stockCode"] == "603663"

    assert routes_analysis.delete_run(run["runId"]) is True
    assert routes_analysis._load_summary_index() == []


@pytest.mark.asyncio
async def test_create_analysis_run_infers_and_accepts_quant_engine_mode(monkeypatch):
    runs_store: dict = {}

    async def fake_runtime_summary():
        return {"agents": []}

    async def fake_hydrate_run_with_market_data(run_data: dict, symbol: str):
        run_data["marketData"] = {"symbol": symbol, "status": "MOCKED"}
        return run_data

    async def fake_persist_run(run_data: dict, run_id: str, symbol: str):
        return None

    monkeypatch.setattr(routes_analysis, "runs_store", runs_store)
    monkeypatch.setattr(routes_analysis, "_runtime_summary_with_plugin_plan", fake_runtime_summary)
    monkeypatch.setattr(routes_analysis, "hydrate_run_with_market_data", fake_hydrate_run_with_market_data)
    monkeypatch.setattr(routes_analysis, "_persist_run", fake_persist_run)
    monkeypatch.setattr(routes_analysis, "get_active_knowledge_context", lambda: [])

    inferred = await routes_analysis.create_analysis_run(
        CreateAnalysisRequest(
            symbol="603663",
            task_type="持仓复核",
            run_mode="STANDARD_MODE",
            scenario_id="qiam_discounted",
            user_constraints={},
            config_profile_id="default",
        )
    )
    explicit = await routes_analysis.create_analysis_run(
        CreateAnalysisRequest(
            symbol="603663",
            task_type="持仓复核",
            run_mode="STANDARD_MODE",
            scenario_id="qiam_discounted",
            user_constraints={},
            config_profile_id="default",
            quant_engine_mode="HIGH_FREQ_SHORT",
        )
    )

    assert runs_store[inferred.run_id]["quantEngine"]["mode"] == "LOW_FREQ_MID_LONG"
    assert runs_store[explicit.run_id]["quantEngine"]["mode"] == "HIGH_FREQ_SHORT"
    assert runs_store[explicit.run_id]["agentRuntime"]["quantEngineMode"] == "HIGH_FREQ_SHORT"


@pytest.mark.asyncio
async def test_create_analysis_run_degrades_when_market_data_hydration_times_out(monkeypatch):
    runs_store: dict = {}
    entered_hydration = asyncio.Event()

    async def fake_runtime_summary():
        return {"agents": []}

    async def slow_hydrate_run_with_market_data(run_data: dict, symbol: str):
        entered_hydration.set()
        await asyncio.sleep(1)
        run_data["marketData"] = {"symbol": symbol, "status": "READY"}
        return run_data

    async def fake_persist_run(run_data: dict, run_id: str, symbol: str):
        return None

    def fake_apply_agent_framework_to_run(run_data: dict, request: dict, runtime_summary: dict):
        run_data["agentRuntime"] = runtime_summary
        return run_data

    monkeypatch.setenv("ANALYSIS_CREATE_MARKET_DATA_TIMEOUT_SECONDS", "0.01")
    monkeypatch.setattr(routes_analysis, "runs_store", runs_store)
    monkeypatch.setattr(routes_analysis, "_runtime_summary_with_plugin_plan", fake_runtime_summary)
    monkeypatch.setattr(routes_analysis, "hydrate_run_with_market_data", slow_hydrate_run_with_market_data)
    monkeypatch.setattr(routes_analysis, "_persist_run", fake_persist_run)
    monkeypatch.setattr(routes_analysis, "apply_agent_framework_to_run", fake_apply_agent_framework_to_run)
    monkeypatch.setattr(routes_analysis, "get_active_knowledge_context", lambda: [])

    created = await routes_analysis.create_analysis_run(
        CreateAnalysisRequest(
            symbol="603663",
            task_type="持仓复核",
            run_mode="STANDARD_MODE",
            scenario_id="qiam_discounted",
            user_constraints={},
            config_profile_id="default",
        )
    )

    run = runs_store[created.run_id]
    assert entered_hydration.is_set()
    assert run["status"] == "CREATED"
    assert run["marketData"]["status"] == "FAILED"
    assert run["marketData"]["details"]["reason"] == "CREATE_MARKET_DATA_TIMEOUT"
    assert run["dataSources"]["summary"]["overallDataMode"] == "UNAVAILABLE"
    assert run["dataMode"] == "UNAVAILABLE"
    assert any(event["eventType"] == "MARKET_DATA_CREATE_DEGRADED" for event in run["auditLog"])


def _market_data_unavailable_run(run_id: str = "RUN_MARKET_BLOCK_001") -> dict:
    return {
        "runId": run_id,
        "runMode": "STANDARD_MODE",
        "environment": "API_ORCHESTRATED",
        "stockCode": "603663",
        "stockName": "",
        "taskType": "持仓复核",
        "userPosition": {},
        "nodes": [
            {"id": "orchestrator", "name": "Orchestrator", "status": "WAIT", "isRunning": False, "isSkipped": False, "isBlocked": False, "rawJson": {}, "auditId": "AUD_ORCH"},
            {"id": "data_reliability_engine", "name": "数据可靠性引擎", "status": "WAIT", "isRunning": False, "isSkipped": False, "isBlocked": False, "rawJson": {}, "auditId": "AUD_DATA_RELIABILITY_ENGINE"},
            {"id": "dvg_gate", "name": "DVG Gate", "status": "WAIT", "isRunning": False, "isSkipped": False, "isBlocked": False, "rawJson": {}, "auditId": "AUD_DVG"},
            {"id": "final_writer", "name": "Final Writer", "status": "WAIT", "isRunning": False, "isSkipped": False, "isBlocked": False, "rawJson": {}, "auditId": "AUD_FINAL"},
        ],
        "agentRuntime": {"enabledNodeOrder": ["orchestrator", "data_reliability_engine", "dvg_gate", "final_writer"]},
        "dvg": {
            "status": "WARN",
            "dataReliability": "MEDIUM",
            "confirmedRatio": 0,
            "inferredRatio": 0,
            "unknownRatio": 1,
            "coreUnknownCount": 0,
            "freshnessStatus": "UNKNOWN",
            "sourceIntegrity": "UNKNOWN",
            "hallucinationRiskScore": 0,
            "hallucinationRiskLevel": "MEDIUM",
            "criticalMissingData": [],
            "dataConflicts": [],
            "allowedOutputLevel": "REVIEW_ONLY",
            "qiamPermission": "REVIEW_ONLY",
            "scenarioPermission": "REVIEW_ONLY",
            "executionPermission": "REVIEW_ONLY",
            "finalDecisionCap": "WAIT",
            "hardStop": False,
        },
        "risk": {},
        "atrade": {},
        "market": {},
        "factorSlicing": {},
        "chipKb": {},
        "qiam": {},
        "portfolio": {},
        "execution": {"allowedActions": ["WAIT"], "forbiddenActions": []},
        "signalOps": {},
        "paperTrading": {},
        "marketData": {
            "status": "FAILED",
            "provider": "create_preflight",
            "symbol": "603663",
            "quote": {},
            "error": "行情水合超时，任务已先创建；请在运行台查看降级状态。",
            "details": {"reason": "CREATE_MARKET_DATA_TIMEOUT", "stage": "create_analysis_run"},
        },
        "dataSources": {
            "sources": {
                "realtime_quote": {
                    "name": "实时行情",
                    "provider": "create_preflight",
                    "icon": "BarChart3",
                    "status": "FAILED",
                    "detail": "行情水合超时，任务已先创建；请在运行台查看降级状态。",
                    "available": False,
                    "error": "行情水合超时，任务已先创建；请在运行台查看降级状态。",
                    "category": "行情",
                    "dataMode": "UNAVAILABLE",
                }
            },
            "summary": {
                "availableCount": 0,
                "totalCount": 1,
                "availableRatio": "0/1",
                "overallStatus": "ALL_MOCK",
                "overallDataMode": "UNAVAILABLE",
                "generatedAt": "2026-05-20T10:00:00",
            },
        },
        "dataMode": "UNAVAILABLE",
        "agentOutputs": {},
        "llmTrace": [],
        "agentResults": [],
        "dagEvents": [],
        "skippedNodes": [],
        "finalAction": "WAIT",
        "killSwitch": {"active": False, "level": "NONE", "triggerNode": "", "triggerRule": "", "blockedPaths": [], "allowedPaths": ["WAIT"], "finalWriterMode": "NORMAL", "auditId": "AUD_KS_NONE"},
        "auditLog": [],
        "streamEvents": [],
        "createdAt": "2026-05-20T10:00:00",
        "updatedAt": "2026-05-20T10:00:00",
        "status": "CREATED",
    }


@pytest.mark.asyncio
async def test_start_blocks_when_realtime_market_data_is_unavailable(monkeypatch, tmp_path):
    saved: list[dict] = []
    persisted: list[dict] = []
    run = _market_data_unavailable_run()
    run_id = run["runId"]

    async def fake_persist_run(run_data: dict, next_run_id: str, symbol: str):
        persisted.append({"run_id": next_run_id, "status": run_data.get("status"), "symbol": symbol})

    async def fail_execute_run_with_llm(next_run_id: str, store: dict):
        raise AssertionError("LLM execution should not start when realtime market data is unavailable")

    monkeypatch.setattr(routes_analysis, "runs_store", {run_id: run})
    monkeypatch.setattr(routes_analysis, "analysis_tasks", {})
    monkeypatch.setattr(routes_analysis, "save_run", lambda run_data: saved.append(copy.deepcopy(run_data)))
    monkeypatch.setattr(routes_analysis, "_persist_run", fake_persist_run)
    monkeypatch.setattr(routes_analysis, "execute_run_with_llm", fail_execute_run_with_llm)
    monkeypatch.setattr(routes_analysis.analysis_job_store, "STORAGE_FILE", tmp_path / "analysis_jobs.json")
    monkeypatch.setattr(routes_analysis.analysis_job_store, "SQLITE_DB_FILE", tmp_path / "analysis_jobs.db")

    result = await routes_analysis.start_analysis_run(run_id)

    assert result.status == "FAILED"
    assert routes_analysis.analysis_tasks == {}
    assert run["status"] == "FAILED"
    assert run["failureCategory"] == "MARKET_DATA_PREFLIGHT_BLOCKED"
    assert "未调用大模型 Agent" in run["failReason"]
    assert run["job"]["status"] == "FAILED"
    assert run["job"]["failed_node_id"] == "data_reliability_engine"
    assert run["llmTrace"] == []
    assert run["nodes"][1]["id"] == "data_reliability_engine"
    assert run["nodes"][1]["status"] == "FAIL"
    assert run["nodes"][1]["isBlocked"] is True
    assert run["nodes"][2]["status"] == "SKIPPED"
    assert run["streamEvents"][0]["event_type"] == "NODE_FINISHED"
    assert run["streamEvents"][0]["node_id"] == "data_reliability_engine"
    assert run["streamEvents"][1]["event_type"] == "RUN_FAILED"
    assert run["streamEvents"][1]["payload"]["llmSuppressed"] is True
    assert persisted == [{"run_id": run_id, "status": "FAILED", "symbol": "603663"}]
    assert saved and saved[-1]["status"] == "FAILED"


@pytest.mark.asyncio
async def test_worker_mode_market_data_unavailable_blocks_without_queue(monkeypatch, tmp_path):
    run = _market_data_unavailable_run("RUN_MARKET_BLOCK_WORKER_001")
    run_id = run["runId"]

    async def fake_persist_run(run_data: dict, next_run_id: str, symbol: str):
        return None

    monkeypatch.setenv("ANALYSIS_EXECUTION_MODE", "worker")
    monkeypatch.setattr(routes_analysis, "runs_store", {run_id: run})
    monkeypatch.setattr(routes_analysis, "analysis_tasks", {})
    monkeypatch.setattr(routes_analysis, "save_run", lambda run_data: None)
    monkeypatch.setattr(routes_analysis, "_persist_run", fake_persist_run)
    monkeypatch.setattr(routes_analysis.analysis_job_store, "STORAGE_FILE", tmp_path / "analysis_jobs.json")
    monkeypatch.setattr(routes_analysis.analysis_job_store, "SQLITE_DB_FILE", tmp_path / "analysis_jobs.db")

    result = await routes_analysis.start_analysis_run(run_id)

    assert result.status == "FAILED"
    assert routes_analysis.analysis_tasks == {}
    assert run["status"] == "FAILED"
    assert run["job"]["status"] == "FAILED"
    assert run["job"]["failed_node_id"] == "data_reliability_engine"
    assert not any(event["event_type"] == "RUN_QUEUED" for event in run["streamEvents"])


@pytest.mark.asyncio
async def test_retry_market_data_preflight_block_rehydrates_before_restart(monkeypatch, tmp_path):
    started: list[tuple[str, dict | None]] = []
    hydrated_symbols: list[str] = []
    run = _market_data_unavailable_run("RUN_MARKET_BLOCK_RETRY_001")
    run_id = run["runId"]

    async def fake_persist_run(run_data: dict, next_run_id: str, symbol: str):
        return None

    async def fake_hydrate_run_with_market_data(run_data: dict, symbol: str):
        hydrated_symbols.append(symbol)
        run_data["marketData"] = {
            "status": "READY",
            "provider": "test",
            "symbol": symbol,
            "quote": {"price": 10.5},
            "error": "",
        }
        run_data["dataSources"] = {
            "sources": {
                "realtime_quote": {
                    "name": "实时行情",
                    "provider": "test",
                    "icon": "BarChart3",
                    "status": "READY",
                    "detail": "ready",
                    "available": True,
                    "category": "行情",
                    "dataMode": "LIVE",
                }
            },
            "summary": {
                "availableCount": 1,
                "totalCount": 1,
                "availableRatio": "1/1",
                "overallStatus": "READY",
                "overallDataMode": "LIVE",
                "generatedAt": "2026-05-20T10:01:00",
            },
        }
        run_data["dataMode"] = "LIVE"
        return run_data

    async def fake_start_analysis_run(next_run_id: str, payload: dict | None = None):
        started.append((next_run_id, payload))
        data_node = next(node for node in run["nodes"] if node["id"] == "data_reliability_engine")
        dvg_node = next(node for node in run["nodes"] if node["id"] == "dvg_gate")
        assert run["marketData"]["status"] == "READY"
        assert run["dataMode"] == "LIVE"
        assert data_node["status"] == "WAIT"
        assert data_node["isBlocked"] is False
        assert dvg_node["isSkipped"] is False
        return SimpleNamespace(run_id=next_run_id, status="RUNNING")

    monkeypatch.setattr(routes_analysis, "runs_store", {run_id: run})
    monkeypatch.setattr(routes_analysis, "analysis_tasks", {})
    monkeypatch.setattr(routes_analysis, "save_run", lambda run_data: None)
    monkeypatch.setattr(routes_analysis, "_persist_run", fake_persist_run)
    monkeypatch.setattr(routes_analysis.analysis_job_store, "STORAGE_FILE", tmp_path / "analysis_jobs.json")
    monkeypatch.setattr(routes_analysis.analysis_job_store, "SQLITE_DB_FILE", tmp_path / "analysis_jobs.db")

    blocked = await routes_analysis.start_analysis_run(run_id)
    assert blocked.status == "FAILED"

    monkeypatch.setattr(routes_analysis, "hydrate_run_with_market_data", fake_hydrate_run_with_market_data)
    monkeypatch.setattr(routes_analysis, "start_analysis_run", fake_start_analysis_run)

    result = await routes_analysis.retry_analysis_run(run_id)

    assert result.status == "RUNNING"
    assert hydrated_symbols == ["603663"]
    assert started == [(run_id, {"operator": "local_workbench"})]
    assert run["retry"]["from_node_id"] == "data_reliability_engine"


@pytest.mark.asyncio
async def test_create_analysis_run_attaches_portfolio_snapshot_with_normalized_symbol_and_audit(monkeypatch):
    runs_store: dict = {}
    snapshot = PortfolioSnapshot(
        snapshotId="PF_TEST_NORMALIZED",
        sourceType="CSV",
        sourceName="imported holdings",
        totalAssets=100000,
        cash=88000,
        stockMarketValue=12000,
        totalPositionRatio=0.12,
        maxSinglePositionRatio=0.12,
        positionCount=1,
        importedAt="2026-05-27T00:00:00+00:00",
        updatedAt="2026-05-27T00:00:00+00:00",
        positions=[
            HoldingPosition(
                symbol="603663",
                name="科伦药业",
                shares=600,
                availableShares=500,
                costPrice=20,
                marketValue=12000,
                weight=0.12,
                updatedAt="2026-05-27T00:00:00+00:00",
            )
        ],
    )
    snapshot.evidenceUsage = "primary"
    snapshot.evidenceStrength = "HIGH"
    snapshot.simulationOnly = False
    snapshot.isRealTrade = True
    snapshot.strongConclusionAllowed = True

    async def fake_runtime_summary():
        return {"agents": []}

    async def fake_hydrate_run_with_market_data(run_data: dict, symbol: str):
        run_data["marketData"] = {"symbol": symbol, "status": "MOCKED"}
        return run_data

    async def fake_persist_run(run_data: dict, run_id: str, symbol: str):
        return None

    async def fake_get_snapshot(snapshot_id: str):
        assert snapshot_id == snapshot.snapshotId
        return snapshot

    monkeypatch.setattr(routes_analysis, "runs_store", runs_store)
    monkeypatch.setattr(routes_analysis, "_runtime_summary_with_plugin_plan", fake_runtime_summary)
    monkeypatch.setattr(routes_analysis, "hydrate_run_with_market_data", fake_hydrate_run_with_market_data)
    monkeypatch.setattr(routes_analysis, "_persist_run", fake_persist_run)
    monkeypatch.setattr(routes_analysis, "get_snapshot", fake_get_snapshot)
    monkeypatch.setattr(routes_analysis, "get_active_knowledge_context", lambda: [])

    created = await routes_analysis.create_analysis_run(
        CreateAnalysisRequest(
            symbol="603663.SZ",
            task_type="持仓复核",
            run_mode="STANDARD_MODE",
            scenario_id="qiam_discounted",
            user_constraints={"allow_add": True},
            config_profile_id="default",
            portfolio_snapshot_id=snapshot.snapshotId,
        )
    )

    run = runs_store[created.run_id]
    assert run["portfolioSnapshot"]["snapshotId"] == snapshot.snapshotId
    assert run["portfolioSnapshot"]["evidenceUsage"] == "supporting_only"
    assert run["portfolioSnapshot"]["evidenceStrength"] == "PENDING"
    assert run["portfolioSnapshot"]["simulationOnly"] is True
    assert run["portfolioSnapshot"]["isRealTrade"] is False
    assert run["portfolioSnapshot"]["strongConclusionAllowed"] is False
    assert run["portfolio"]["portfolioCoverage"] == "HOLDINGS_CONNECTED"
    assert run["portfolio"]["snapshotId"] == snapshot.snapshotId
    assert run["portfolio"]["evidenceUsage"] == "supporting_only"
    assert run["portfolio"]["evidenceStrength"] == "PENDING"
    assert run["portfolio"]["simulationOnly"] is True
    assert run["portfolio"]["isRealTrade"] is False
    assert run["portfolio"]["strongConclusionAllowed"] is False
    assert run["portfolio"]["provenance"]["sourceType"] == "PORTFOLIO_SNAPSHOT"
    assert run["portfolio"]["provenance"]["snapshotId"] == snapshot.snapshotId
    assert run["portfolio"]["provenance"]["evidenceUsage"] == "supporting_only"
    assert run["portfolio"]["singleStockPosition"] == 0.12
    assert run["userPosition"]["currentShares"] == 600
    assert run["userPosition"]["currentPositionRatio"] == 0.12
    assert run["userPosition"]["sellableBottomWarehouse"] is True
    assert run["stockName"] == "科伦药业"
    assert any(event["eventType"] == "PORTFOLIO_SNAPSHOT_ATTACHED" for event in run["auditLog"])


@pytest.mark.asyncio
async def test_create_analysis_run_keeps_missing_snapshot_symbol_warning_when_add_allowed(monkeypatch):
    runs_store: dict = {}
    snapshot = PortfolioSnapshot(
        snapshotId="PF_TEST_MISMATCH",
        sourceType="CSV",
        sourceName="imported holdings",
        totalAssets=100000,
        stockMarketValue=20000,
        totalPositionRatio=0.2,
        positionCount=1,
        importedAt="2026-05-27T00:00:00+00:00",
        updatedAt="2026-05-27T00:00:00+00:00",
        positions=[
            HoldingPosition(
                symbol="000001",
                name="平安银行",
                shares=1000,
                availableShares=1000,
                costPrice=20,
                marketValue=20000,
                weight=0.2,
            )
        ],
    )

    async def fake_runtime_summary():
        return {"agents": []}

    async def fake_hydrate_run_with_market_data(run_data: dict, symbol: str):
        run_data["marketData"] = {"symbol": symbol, "status": "MOCKED"}
        return run_data

    async def fake_persist_run(run_data: dict, run_id: str, symbol: str):
        return None

    async def fake_get_snapshot(snapshot_id: str):
        assert snapshot_id == snapshot.snapshotId
        return snapshot

    monkeypatch.setattr(routes_analysis, "runs_store", runs_store)
    monkeypatch.setattr(routes_analysis, "_runtime_summary_with_plugin_plan", fake_runtime_summary)
    monkeypatch.setattr(routes_analysis, "hydrate_run_with_market_data", fake_hydrate_run_with_market_data)
    monkeypatch.setattr(routes_analysis, "_persist_run", fake_persist_run)
    monkeypatch.setattr(routes_analysis, "get_snapshot", fake_get_snapshot)
    monkeypatch.setattr(routes_analysis, "get_active_knowledge_context", lambda: [])

    created = await routes_analysis.create_analysis_run(
        CreateAnalysisRequest(
            symbol="603663.SZ",
            task_type="持仓复核",
            run_mode="STANDARD_MODE",
            scenario_id="qiam_discounted",
            user_constraints={"allow_add": True},
            config_profile_id="default",
            portfolio_snapshot_id=snapshot.snapshotId,
        )
    )

    reasons = runs_store[created.run_id]["portfolio"]["restrictionReasons"]
    assert "Selected snapshot has no holding row for this symbol." in reasons
    assert "仅用户允许加仓候选；仍需 DVG、QIAM、执行层全部通过后才可能升级" in reasons


@pytest.mark.asyncio
async def test_get_analysis_run_http_preserves_agent_module_results(monkeypatch):
    run_id = "RUN_CONTRACT_AGENT_MODULE_RESULTS"
    run = copy.deepcopy(mock_scenarios["normal_pass"])
    run["runId"] = run_id
    run["auditId"] = "AUD_CONTRACT_RUN"
    run["agentModuleResults"] = {
        "quant_core": {
            "status": "PASS",
            "data": {"contract": "preserved"},
        }
    }
    if isinstance(run.get("finalWriter"), dict):
        run["finalWriter"]["auditId"] = "AUD_CONTRACT_FW"
    for event in run.get("auditLog", []):
        event["runId"] = run_id
        event["auditId"] = "AUD_CONTRACT_EVENT"

    monkeypatch.setattr(routes_analysis, "runs_store", {run_id: run})
    monkeypatch.setattr(routes_analysis, "_reconcile_analysis_run_jobs", lambda source="detail": None)
    monkeypatch.setattr(routes_analysis.analysis_job_store, "get_job", lambda _run_id: None)
    monkeypatch.setattr(routes_analysis, "save_run", lambda run_data: None)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get(f"/api/analysis/runs/{run_id}")

    assert response.status_code == 200
    assert response.json()["agentModuleResults"]["quant_core"]["data"]["contract"] == "preserved"


@pytest.mark.asyncio
async def test_get_analysis_run_repairs_quant_engine_display_chain(monkeypatch):
    run_id = "RUN_20260523_142159_63100fda"
    run = {
        "runId": run_id,
        "status": "COMPLETED",
        "createdAt": "2026-05-23T14:21:59",
        "updatedAt": "2026-05-23T14:26:05",
        "stockCode": "603663",
        "taskType": "持仓复核",
        "runMode": "STANDARD_MODE",
        "quantEngine": {"mode": "LOW_FREQ_MID_LONG"},
        "dataSources": {
            "sources": {
                "quote": {
                    "name": "实时行情",
                    "status": "READY",
                    "dataMode": "LIVE",
                    "available": True,
                    "provider": "tushare",
                },
            },
        },
        "marketData": {"freshness": "REALTIME", "quote": {"changePercent": 0}},
        "market": {"regimeClassification": "高波动"},
        "technicalKline": {
            "agent": "technical_kline_analyst",
            "status": "WARN",
            "technicalBias": "BULLISH",
            "confidence": 0.86,
            "dataQuality": {
                "provider": "tushare",
                "dataMode": "LIVE",
                "dailyCount": 76,
            },
            "summaryForDownstream": "canonical LIVE Tushare K-line",
        },
        "atrade": {"level2Available": False, "depthAvailable": False},
        "dvg": {
            "qiamPermission": "ALLOW_WITH_DISCOUNT",
            "criticalMissingData": ["技术面 K 线真实数据校验", "Level-2 逐笔成交", "盘口深度"],
            "hallucinationRiskScore": 31,
        },
        "factorSlicing": {
            "factorDataSource": "TUSHARE_STK_FACTOR",
            "missingFactorData": [],
            "factors": [{"name": "Value", "weight": 0.35, "contribution": 0.01, "confidence": 0.72}],
        },
        "factorEngine": {"engineMode": "FULL", "factorCount": 1},
        "calculationAuthority": {
            "hasCalculationTools": False,
            "calculationToolStatus": "UNKNOWN",
            "llmCalculationProhibited": True,
        },
        "qiam": {
            "rawBuySuitability": "FAVORABLE",
            "probabilitySource": "RULE_DERIVED",
            "missingData": ["QIAM 输入尚未完成拉取"],
            "discountFactor": 0.44625,
            "finalBuySuitability": "REVIEW_ONLY",
            "downgradeReasons": [
                "缺少QIAM 输入尚未完成拉取: ×0.85",
                "DVG ALLOW_WITH_DISCOUNT: ×0.70",
                "technicalKline low confidence=0.00: x0.75",
            ],
            "technicalKlineConstraint": {
                "observed": True,
                "bias": "INSUFFICIENT_DATA",
                "confidence": 0.0,
                "appliedFactor": 0.75,
                "downgradeReason": "technicalKline low confidence=0.00: x0.75",
            },
        },
        "agentModuleResults": {
            "dvg_gate": {
                "data": {
                    "qiamPermission": "ALLOW_WITH_DISCOUNT",
                    "criticalMissingData": ["技术面 K 线真实数据校验", "Level-2 逐笔成交", "盘口深度"],
                }
            },
            "quant_engine": {
                "data": {
                    "missingData": ["QIAM 输入尚未完成拉取"],
                    "downgradeReasons": [
                        "缺少QIAM 输入尚未完成拉取: ×0.85",
                        "DVG ALLOW_WITH_DISCOUNT: ×0.70",
                        "technicalKline low confidence=0.00: x0.75",
                    ],
                }
            },
        },
        "agentResults": [
            {
                "node": "quant_engine",
                "reasons": ["DVG ALLOW_WITH_DISCOUNT: ×0.70"],
                "data": {"downgradeReasons": ["technicalKline low confidence=0.00: x0.75"]},
            }
        ],
        "nodes": [
            {"id": "dvg_gate", "name": "DVG Gate", "status": "WARN", "isSkipped": False, "auditId": "AUD_DVG"},
            {
                "id": "quant_engine",
                "name": "Quant Engine",
                "status": "WARN",
                "isSkipped": False,
                "auditId": "AUD_QIAM",
                "missingData": ["因子输入尚未完成拉取"],
                "downgradeReasons": ["DVG ALLOW_WITH_DISCOUNT: ×0.70"],
                "outputSummary": "technicalKline low confidence=0.00: x0.75",
                "rawJson": {
                    "llmRunner": {
                        "content": "QIAM 输入尚未完成拉取; DVG ALLOW_WITH_DISCOUNT; technicalKline low confidence=0.00"
                    }
                },
            },
        ],
    }
    saved: list[dict] = []

    monkeypatch.setattr(routes_analysis, "runs_store", {run_id: run})
    monkeypatch.setattr(routes_analysis, "_reconcile_analysis_run_jobs", lambda source="detail": None)
    monkeypatch.setattr(routes_analysis.analysis_job_store, "get_job", lambda _run_id: None)
    monkeypatch.setattr(routes_analysis, "save_run", lambda run_data: saved.append(run_data.copy()))

    result = await routes_analysis.get_analysis_run(run_id)

    assert result["dvg"]["qiamPermission"] == "ALLOW"
    assert result["dvg"]["criticalMissingData"] == []
    assert result["qiam"]["missingData"] == []
    assert result["qiam"]["discountFactor"] == pytest.approx(1.0)
    assert result["qiam"]["downgradeReasons"] == []
    assert result["qiam"]["remediationItems"] == []
    quant_agent = next(item for item in result["agentResults"] if item["node"] == "quant_engine")
    serialized_quant = str(quant_agent)
    assert "QIAM 输入尚未完成" not in serialized_quant
    assert "DVG ALLOW_WITH_DISCOUNT" not in serialized_quant
    assert "technicalKline low confidence=0.00" not in serialized_quant
    assert saved


@pytest.mark.asyncio
async def test_started_run_persists_final_background_state(monkeypatch, tmp_path):
    runs_store: dict = {}
    persisted: list[dict] = []
    learning_candidates: list[str] = []
    completed_persisted = asyncio.Event()

    async def fake_hydrate_run_with_market_data(run_data: dict, symbol: str):
        run_data["marketData"] = {"symbol": symbol, "status": "MOCKED"}
        return run_data

    def fake_apply_agent_framework_to_run(run_data: dict, request: dict, runtime_summary: dict):
        run_data["agentRuntime"] = runtime_summary
        return run_data

    async def fake_persist_run(run_data: dict, run_id: str, symbol: str):
        persisted.append(
            {
                "run_id": run_id,
                "status": run_data.get("status"),
                "symbol": symbol,
                "stream_event_count": len(run_data.get("streamEvents", [])),
            }
        )
        if run_data.get("status") == "COMPLETED":
            completed_persisted.set()

    async def fake_execute_run_with_llm(run_id: str, store: dict):
        store[run_id]["status"] = "COMPLETED"
        store[run_id]["updatedAt"] = "2026-05-11T12:00:00"
        store[run_id].setdefault("streamEvents", []).append(
            {
                "event_type": "RUN_FINISHED",
                "run_id": run_id,
                "node_id": "final_writer",
                "message": "finished",
                "audit_id": f"AUD_{run_id}_DONE",
                "timestamp": "2026-05-11T12:00:00",
            }
        )

    def fake_create_learning_candidate(run_data: dict):
        learning_candidates.append(run_data["runId"])

    monkeypatch.setattr(routes_analysis, "runs_store", runs_store)
    monkeypatch.setattr(routes_analysis, "get_runtime_summary", lambda: {"agents": []})
    monkeypatch.setattr(routes_analysis, "get_active_knowledge_context", lambda: [])
    monkeypatch.setattr(
        routes_analysis,
        "hydrate_run_with_market_data",
        fake_hydrate_run_with_market_data,
    )
    monkeypatch.setattr(
        routes_analysis,
        "apply_agent_framework_to_run",
        fake_apply_agent_framework_to_run,
    )
    monkeypatch.setattr(routes_analysis, "_persist_run", fake_persist_run)
    monkeypatch.setattr(routes_analysis, "execute_run_with_llm", fake_execute_run_with_llm)
    monkeypatch.setattr(routes_analysis, "create_learning_candidate_from_run", fake_create_learning_candidate)
    monkeypatch.setattr(routes_analysis.analysis_job_store, "STORAGE_FILE", tmp_path / "analysis_jobs.json")

    created = await routes_analysis.create_analysis_run(
        CreateAnalysisRequest(
            symbol="603663",
            task_type="position_review",
            run_mode="STANDARD_MODE",
            scenario_id="qiam_discounted",
            user_constraints={},
            config_profile_id="default",
        )
    )

    started = await routes_analysis.start_analysis_run(created.run_id)
    await asyncio.wait_for(completed_persisted.wait(), timeout=1)

    assert started.status == "RUNNING"
    assert runs_store[created.run_id]["status"] == "COMPLETED"
    assert runs_store[created.run_id]["job"]["status"] == "COMPLETED"
    assert runs_store[created.run_id]["job"]["attempt"] == 1
    assert runs_store[created.run_id]["knowledgeContext"] == []
    assert learning_candidates == [created.run_id]
    assert persisted[0]["status"] == "CREATED"
    assert persisted[-1] == {
        "run_id": created.run_id,
        "status": "COMPLETED",
        "symbol": "603663",
        "stream_event_count": 1,
    }


@pytest.mark.asyncio
async def test_worker_mode_start_queues_without_background_task(monkeypatch, tmp_path):
    saved: list[dict] = []
    run_id = "RUN_WORKER_QUEUE_001"
    run = {
        "runId": run_id,
        "status": "CREATED",
        "stockCode": "603663",
        "nodes": [{"id": "orchestrator", "status": "WAIT", "isSkipped": False}],
        "streamEvents": [],
        "auditLog": [],
    }

    monkeypatch.setenv("ANALYSIS_EXECUTION_MODE", "worker")
    monkeypatch.setattr(routes_analysis, "runs_store", {run_id: run})
    monkeypatch.setattr(routes_analysis, "analysis_tasks", {})
    monkeypatch.setattr(routes_analysis, "save_run", lambda run_data: saved.append(run_data.copy()))
    monkeypatch.setattr(routes_analysis.analysis_job_store, "STORAGE_FILE", tmp_path / "analysis_jobs.json")
    monkeypatch.setattr(routes_analysis.analysis_job_store, "SQLITE_DB_FILE", tmp_path / "analysis_jobs.db")

    result = await routes_analysis.start_analysis_run(run_id)

    assert result.status == "QUEUED"
    assert routes_analysis.analysis_tasks == {}
    assert run["status"] == "QUEUED"
    assert run["job"]["status"] == "QUEUED"
    assert run["streamEvents"][-1]["event_type"] == "RUN_QUEUED"
    assert run["streamEvents"][-1]["payload"]["simulation_only"] is True
    assert run["streamEvents"][-1]["payload"]["is_real_trade"] is False
    assert saved and saved[-1]["status"] == "QUEUED"


@pytest.mark.asyncio
async def test_worker_mode_http_create_start_detail_preserves_created_run(monkeypatch):
    async def fake_hydrate_run_with_market_data(run_data: dict, symbol: str):
        run_data["dataMode"] = "MOCK"
        run_data["dataSources"] = {
            "summary": {"overallStatus": "READY", "overallDataMode": "MOCK"},
            "sources": {},
        }
        run_data["marketData"] = {"symbol": symbol, "status": "MOCKED"}
        return run_data

    def fake_apply_agent_framework_to_run(run_data: dict, request: dict, runtime_summary: dict):
        run_data["agentRuntime"] = runtime_summary
        run_data["nodes"] = [{"id": "orchestrator", "status": "WAIT", "isSkipped": False}]
        run_data["agentResults"] = []
        return run_data

    monkeypatch.setenv("ANALYSIS_EXECUTION_MODE", "worker")
    monkeypatch.setattr(routes_analysis, "get_runtime_summary", lambda: {"agents": []})
    monkeypatch.setattr(routes_analysis, "get_active_knowledge_context", lambda: [])
    monkeypatch.setattr(
        routes_analysis,
        "hydrate_run_with_market_data",
        fake_hydrate_run_with_market_data,
    )
    monkeypatch.setattr(
        routes_analysis,
        "apply_agent_framework_to_run",
        fake_apply_agent_framework_to_run,
    )

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        portfolio_response = await client.post(
            "/api/portfolio/manual",
            json={
                "sourceName": "worker detail regression",
                "accountName": "smoke",
                "cash": 50000,
                "availableCash": 50000,
                "totalAssets": 100000,
                "positions": [
                    {
                        "symbol": "SMOKE001.SZ",
                        "name": "Smoke Holding",
                        "shares": 1000,
                        "availableShares": 1000,
                        "costPrice": 18.5,
                        "marketValue": 18500,
                        "pnl": 0,
                    }
                ],
            },
        )
        assert portfolio_response.status_code == 200
        snapshot_id = portfolio_response.json()["snapshotId"]

        create_response = await client.post(
            "/api/analysis/runs",
            json={
                "symbol": "SMOKE001.SZ",
                "task_type": "mfe_mae_path_research",
                "run_mode": "STANDARD_MODE",
                "scenario_id": "qiam_discounted",
                "user_constraints": {
                    "position_ratio": 0.12,
                    "cost_price": 18.5,
                    "max_drawdown": 0.08,
                    "allow_add": False,
                    "allow_t0": False,
                },
                "config_profile_id": "default",
                "portfolio_snapshot_id": snapshot_id,
            },
        )
        assert create_response.status_code == 200
        run_id = create_response.json()["run_id"]

        start_response = await client.post(f"/api/analysis/runs/{run_id}/start")
        assert start_response.status_code == 200
        assert start_response.json()["status"] == "QUEUED"

        detail_response = await client.get(f"/api/analysis/runs/{run_id}")
        assert detail_response.status_code == 200
        detail = detail_response.json()
        assert detail["runId"] == run_id
        assert detail["status"] == "QUEUED"
        assert detail["job"]["status"] == "QUEUED"
        assert detail["portfolio"]["snapshotId"] == snapshot_id
        assert detail["portfolio"]["portfolioCoverage"] == "HOLDINGS_CONNECTED"

        queued_event = routes_analysis.runs_store[run_id]["streamEvents"][-1]
        assert queued_event["event_type"] == "RUN_QUEUED"
        assert queued_event["payload"]["simulation_only"] is True
        assert queued_event["payload"]["is_real_trade"] is False


def test_analysis_worker_uses_core_lifecycle_facade():
    source = Path(analysis_worker.__file__).read_text(encoding="utf-8")

    assert "routes_analysis" not in source
    assert "analysis_lifecycle_service" in source


def test_research_paths_use_core_lifecycle_facade_for_analysis_calls():
    route_source = Path(routes_research.__file__).read_text(encoding="utf-8")
    verdict_source = Path(research_verdict_store.__file__).read_text(encoding="utf-8")

    assert "from . import routes_analysis" not in route_source
    assert "from ..api import routes_analysis" not in verdict_source
    assert "routes_analysis." not in route_source
    assert "routes_analysis." not in verdict_source
    assert "analysis_lifecycle_service" in route_source
    assert "analysis_lifecycle_service" in verdict_source


@pytest.mark.asyncio
async def test_worker_once_claims_queued_run_and_executes(monkeypatch, tmp_path):
    saved: list[dict] = []
    persisted: list[dict] = []
    learning_candidates: list[str] = []
    run_id = "RUN_WORKER_EXECUTE_001"
    run = {
        "runId": run_id,
        "status": "QUEUED",
        "stockCode": "603663",
        "nodes": [{"id": "final_writer", "status": "WAIT", "isRunning": False}],
        "streamEvents": [],
        "auditLog": [],
    }

    async def fake_execute_run_with_llm(next_run_id: str, store: dict):
        assert next_run_id == run_id
        store[next_run_id]["status"] = "COMPLETED"
        store[next_run_id]["streamEvents"].append(
            {
                "event_type": "RUN_FINISHED",
                "run_id": next_run_id,
                "node_id": "system",
                "message": "finished",
                "audit_id": f"AUD_{next_run_id}_DONE",
                "timestamp": "2026-05-11T12:00:00",
            }
        )

    async def fake_persist_run(run_data: dict, next_run_id: str, symbol: str):
        persisted.append({"run_id": next_run_id, "status": run_data.get("status"), "symbol": symbol})

    monkeypatch.setattr(routes_analysis, "runs_store", {run_id: run})
    monkeypatch.setattr(routes_analysis, "analysis_tasks", {})
    monkeypatch.setattr(routes_analysis, "save_run", lambda run_data: saved.append(run_data.copy()))
    monkeypatch.setattr(routes_analysis, "_persist_run", fake_persist_run)
    monkeypatch.setattr(routes_analysis, "execute_run_with_llm", fake_execute_run_with_llm)
    monkeypatch.setattr(routes_analysis, "create_learning_candidate_from_run", lambda run_data: learning_candidates.append(run_data["runId"]))
    monkeypatch.setattr(routes_analysis, "summarize_run", lambda run_data: {})
    monkeypatch.setattr(
        routes_analysis,
        "mark_summary_persisted",
        lambda run_data, summary: SimpleNamespace(model_dump=lambda: {"persisted": True}),
    )
    monkeypatch.setattr(routes_analysis.analysis_job_store, "STORAGE_FILE", tmp_path / "analysis_jobs.json")
    monkeypatch.setattr(routes_analysis.analysis_job_store, "SQLITE_DB_FILE", tmp_path / "analysis_jobs.db")
    routes_analysis.analysis_job_store.start_job(run_id, operator="tester")

    result = await analysis_worker.run_worker_once(worker_id="worker-test", operator="tester")

    assert result["claimed"] is True
    assert result["run_id"] == run_id
    assert result["status"] == "COMPLETED"
    assert run["job"]["status"] == "COMPLETED"
    assert run["job"]["worker_id"] == "worker-test"
    assert "JOB_CLAIMED" in [event["event"] for event in run["job"]["history"]]
    assert "WORKER_HEARTBEAT" in [event["event"] for event in run["job"]["history"]]
    assert persisted == [{"run_id": run_id, "status": "COMPLETED", "symbol": "603663"}]
    assert learning_candidates == [run_id]
    assert saved


@pytest.mark.asyncio
async def test_worker_heartbeat_updates_while_run_is_executing(monkeypatch, tmp_path):
    run_id = "RUN_WORKER_HEARTBEAT_001"
    run = {
        "runId": run_id,
        "status": "QUEUED",
        "stockCode": "603663",
        "nodes": [{"id": "final_writer", "status": "WAIT", "isRunning": False}],
        "streamEvents": [],
        "auditLog": [],
    }

    async def fake_execute_run_with_llm(next_run_id: str, store: dict):
        assert next_run_id == run_id
        await asyncio.sleep(0.25)
        store[next_run_id]["status"] = "COMPLETED"

    async def fake_persist_run(run_data: dict, next_run_id: str, symbol: str):
        return None

    monkeypatch.setenv("ANALYSIS_WORKER_HEARTBEAT_INTERVAL_SECONDS", "0.01")
    monkeypatch.setattr(routes_analysis, "runs_store", {run_id: run})
    monkeypatch.setattr(routes_analysis, "save_run", lambda run_data: None)
    monkeypatch.setattr(routes_analysis, "_persist_run", fake_persist_run)
    monkeypatch.setattr(routes_analysis, "execute_run_with_llm", fake_execute_run_with_llm)
    monkeypatch.setattr(routes_analysis, "create_learning_candidate_from_run", lambda run_data: None)
    monkeypatch.setattr(routes_analysis, "summarize_run", lambda run_data: {})
    monkeypatch.setattr(
        routes_analysis,
        "mark_summary_persisted",
        lambda run_data, summary: SimpleNamespace(model_dump=lambda: {"persisted": True}),
    )
    monkeypatch.setattr(routes_analysis.analysis_job_store, "STORAGE_FILE", tmp_path / "analysis_jobs.json")
    monkeypatch.setattr(routes_analysis.analysis_job_store, "SQLITE_DB_FILE", tmp_path / "analysis_jobs.db")
    routes_analysis.analysis_job_store.start_job(run_id, operator="tester")

    result = await analysis_worker.run_worker_once(worker_id="worker-heartbeat", operator="tester")

    heartbeat_events = [
        event for event in result["job"]["history"]
        if event["event"] == "WORKER_HEARTBEAT"
    ]
    assert result["status"] == "COMPLETED"
    assert len(heartbeat_events) >= 2
    assert result["job"]["worker_id"] == "worker-heartbeat"


@pytest.mark.asyncio
async def test_worker_running_cancel_request_is_observed_by_heartbeat(monkeypatch, tmp_path):
    run_id = "RUN_WORKER_CANCEL_RUNNING_001"
    run = {
        "runId": run_id,
        "status": "QUEUED",
        "stockCode": "603663",
        "nodes": [{"id": "final_writer", "status": "WAIT", "isRunning": False}],
        "streamEvents": [],
        "auditLog": [],
    }

    async def fake_execute_run_with_llm(next_run_id: str, store: dict):
        assert next_run_id == run_id
        routes_analysis.analysis_job_store.request_cancel(run_id, operator="frontend")
        for _ in range(50):
            if store[next_run_id].get("cancelRequested"):
                raise asyncio.CancelledError()
            await asyncio.sleep(0.01)
        raise AssertionError("worker heartbeat did not propagate cancelRequested")

    async def fake_persist_run(run_data: dict, next_run_id: str, symbol: str):
        return None

    monkeypatch.setenv("ANALYSIS_WORKER_HEARTBEAT_INTERVAL_SECONDS", "0.01")
    monkeypatch.setattr(routes_analysis, "runs_store", {run_id: run})
    monkeypatch.setattr(routes_analysis, "save_run", lambda run_data: None)
    monkeypatch.setattr(routes_analysis, "_persist_run", fake_persist_run)
    monkeypatch.setattr(routes_analysis, "execute_run_with_llm", fake_execute_run_with_llm)
    monkeypatch.setattr(routes_analysis.analysis_job_store, "STORAGE_FILE", tmp_path / "analysis_jobs.json")
    monkeypatch.setattr(routes_analysis.analysis_job_store, "SQLITE_DB_FILE", tmp_path / "analysis_jobs.db")
    routes_analysis.analysis_job_store.start_job(run_id, operator="tester")

    result = await analysis_worker.run_worker_once(worker_id="worker-cancel", operator="tester")

    assert result["status"] == "CANCELLED"
    assert run["cancelRequested"] is True
    assert result["job"]["status"] == "CANCELLED"
    assert run["streamEvents"][-1]["event_type"] == "RUN_CANCELLED"


@pytest.mark.asyncio
async def test_cancel_running_worker_run_keeps_request_for_worker(monkeypatch, tmp_path):
    saved: list[dict] = []
    run_id = "RUN_WORKER_EXTERNAL_CANCEL_001"
    run = {
        "runId": run_id,
        "status": "RUNNING",
        "stockCode": "603663",
        "nodes": [{"id": "final_writer", "status": "RUNNING", "isRunning": True}],
        "streamEvents": [],
        "auditLog": [],
    }

    monkeypatch.setattr(routes_analysis, "runs_store", {run_id: run})
    monkeypatch.setattr(routes_analysis, "analysis_tasks", {})
    monkeypatch.setattr(routes_analysis, "save_run", lambda run_data: saved.append(run_data.copy()))
    monkeypatch.setattr(routes_analysis.analysis_job_store, "STORAGE_FILE", tmp_path / "analysis_jobs.json")
    monkeypatch.setattr(routes_analysis.analysis_job_store, "SQLITE_DB_FILE", tmp_path / "analysis_jobs.db")
    routes_analysis.analysis_job_store.start_job(run_id, operator="tester")
    run["job"] = routes_analysis.analysis_job_store.mark_running(run_id, worker_id="worker-external", operator="tester")

    result = await routes_analysis.cancel_analysis_run(run_id)

    assert result["status"] == "RUNNING"
    assert result["job"]["status"] == "CANCEL_REQUESTED"
    assert run["cancelRequested"] is True
    assert run["job"]["status"] == "CANCEL_REQUESTED"
    assert run["streamEvents"] == []
    assert saved and saved[-1]["status"] == "RUNNING"


@pytest.mark.asyncio
async def test_worker_cancel_request_cannot_be_overwritten_by_late_completion(monkeypatch, tmp_path):
    saved: list[dict] = []
    persisted: list[dict] = []
    research_updates: list[str] = []
    run_id = "RUN_WORKER_CANCEL_LATE_COMPLETE_001"
    run = {
        "runId": run_id,
        "status": "QUEUED",
        "stockCode": "603663",
        "nodes": [{"id": "final_writer", "status": "WAIT", "isRunning": False}],
        "streamEvents": [],
        "auditLog": [],
    }

    async def fake_execute_run_with_llm(next_run_id: str, store: dict):
        assert next_run_id == run_id
        await routes_analysis.cancel_analysis_run(next_run_id)
        store[next_run_id]["status"] = "COMPLETED"

    async def fake_persist_run(run_data: dict, next_run_id: str, symbol: str):
        persisted.append({"run_id": next_run_id, "status": run_data.get("status"), "symbol": symbol})

    async def fake_update_research_iteration_from_run(run_data: dict, *, action: str, status: str, note: str):
        research_updates.append(status)

    monkeypatch.setattr(routes_analysis, "runs_store", {run_id: run})
    monkeypatch.setattr(routes_analysis, "analysis_tasks", {})
    monkeypatch.setattr(routes_analysis, "save_run", lambda run_data: saved.append(run_data.copy()))
    monkeypatch.setattr(routes_analysis, "_persist_run", fake_persist_run)
    monkeypatch.setattr(routes_analysis, "execute_run_with_llm", fake_execute_run_with_llm)
    monkeypatch.setattr(routes_analysis, "_update_research_iteration_from_run", fake_update_research_iteration_from_run)
    monkeypatch.setattr(routes_analysis.analysis_job_store, "STORAGE_FILE", tmp_path / "analysis_jobs.json")
    monkeypatch.setattr(routes_analysis.analysis_job_store, "SQLITE_DB_FILE", tmp_path / "analysis_jobs.db")
    routes_analysis.analysis_job_store.start_job(run_id, operator="tester")

    result = await analysis_worker.run_worker_once(worker_id="worker-cancel", operator="tester")

    assert result["status"] == "CANCELLED"
    assert run["status"] == "CANCELLED"
    assert result["job"]["status"] == "CANCELLED"
    assert run["job"]["status"] == "CANCELLED"
    assert run["streamEvents"][-1]["event_type"] == "RUN_CANCELLED"
    assert persisted == [{"run_id": run_id, "status": "CANCELLED", "symbol": "603663"}]
    assert research_updates == ["RUN_CANCELLED"]
    assert saved and saved[-1]["status"] == "CANCELLED"


@pytest.mark.asyncio
async def test_terminal_run_cannot_be_restarted(monkeypatch):
    run_id = "RUN_TERMINAL_001"
    monkeypatch.setattr(routes_analysis, "runs_store", {run_id: {"runId": run_id, "status": "COMPLETED"}})

    with pytest.raises(HTTPException) as exc:
        await routes_analysis.start_analysis_run(run_id)

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_missing_framework_nodes_are_rebuilt_before_start(monkeypatch, tmp_path):
    run_id = "RUN_REBUILD_DAG_001"
    run = {
        "runId": run_id,
        "status": "CREATED",
        "stockCode": "603663",
        "taskType": "position_review",
        "runMode": "STANDARD_MODE",
        "nodes": [],
        "streamEvents": [],
    }

    async def fake_runtime_summary():
        return {"agents": []}

    def fake_apply_agent_framework_to_run(run_data: dict, request: dict, runtime_summary: dict):
        rebuilt = dict(run_data)
        rebuilt["agentRuntime"] = {
            **runtime_summary,
            "enabledNodeOrder": ["orchestrator", "quant_engine", "final_writer"],
        }
        rebuilt["nodes"] = [
            {"id": "orchestrator", "status": "WAIT", "isSkipped": False},
            {"id": "quant_engine", "status": "WAIT", "isSkipped": False},
            {"id": "final_writer", "status": "WAIT", "isSkipped": False},
        ]
        rebuilt["frameworkRequest"] = request
        return rebuilt

    monkeypatch.setattr(routes_analysis, "_runtime_summary_with_plugin_plan", fake_runtime_summary)
    monkeypatch.setattr(routes_analysis, "apply_agent_framework_to_run", fake_apply_agent_framework_to_run)

    changed = await routes_analysis._ensure_run_framework_ready(run_id, run)

    assert changed is True
    assert [node["id"] for node in run["nodes"]] == ["orchestrator", "quant_engine", "final_writer"]
    assert run["frameworkRequest"]["symbol"] == "603663"


@pytest.mark.asyncio
async def test_cancel_created_run_marks_job_and_audit(monkeypatch, tmp_path):
    saved: list[dict] = []
    run_id = "RUN_CANCEL_001"
    run = {
        "runId": run_id,
        "status": "CREATED",
        "stockCode": "603663",
        "nodes": [{"id": "dvg_gate", "status": "WAIT", "isRunning": False}],
        "auditLog": [],
        "streamEvents": [],
    }

    monkeypatch.setattr(routes_analysis, "runs_store", {run_id: run})
    monkeypatch.setattr(routes_analysis, "analysis_tasks", {})
    monkeypatch.setattr(routes_analysis, "save_run", lambda run_data: saved.append(run_data.copy()))
    monkeypatch.setattr(routes_analysis.analysis_job_store, "STORAGE_FILE", tmp_path / "analysis_jobs.json")

    result = await routes_analysis.cancel_analysis_run(run_id)

    assert result["status"] == "CANCELLED"
    assert result["job"]["status"] == "CANCELLED"
    assert run["failureCategory"] == "USER_CANCELLED"
    assert run["streamEvents"][-1]["event_type"] == "RUN_CANCELLED"
    assert run["auditLog"][-1]["eventType"] == "RUN_CANCELLED"
    assert saved and saved[-1]["status"] == "CANCELLED"


@pytest.mark.asyncio
async def test_cancelled_background_task_marks_run_and_job_cancelled(monkeypatch, tmp_path):
    saved: list[dict] = []
    persisted: list[dict] = []
    research_updates: list[str] = []
    run_id = "RUN_CANCEL_TASK_001"
    run = {
        "runId": run_id,
        "status": "RUNNING",
        "stockCode": "603663",
        "nodes": [{"id": "dvg_gate", "status": "RUNNING", "isRunning": True}],
        "auditLog": [],
        "streamEvents": [],
    }

    async def fake_execute_run_with_llm(next_run_id: str, store: dict):
        assert next_run_id == run_id
        assert store is routes_analysis.runs_store
        raise asyncio.CancelledError()

    async def fake_persist_run(run_data: dict, next_run_id: str, symbol: str):
        persisted.append({"run_id": next_run_id, "status": run_data.get("status"), "symbol": symbol})

    async def fake_update_research_iteration_from_run(run_data: dict, *, action: str, status: str, note: str):
        research_updates.append(status)

    monkeypatch.setattr(routes_analysis, "runs_store", {run_id: run})
    monkeypatch.setattr(routes_analysis, "save_run", lambda run_data: saved.append(run_data.copy()))
    monkeypatch.setattr(routes_analysis, "_persist_run", fake_persist_run)
    monkeypatch.setattr(routes_analysis, "execute_run_with_llm", fake_execute_run_with_llm)
    monkeypatch.setattr(routes_analysis, "_update_research_iteration_from_run", fake_update_research_iteration_from_run)
    monkeypatch.setattr(routes_analysis.analysis_job_store, "STORAGE_FILE", tmp_path / "analysis_jobs.json")
    run["job"] = routes_analysis.analysis_job_store.start_job(run_id, operator="test_operator")

    await routes_analysis._execute_and_persist_run(run_id)

    assert run["status"] == "CANCELLED"
    assert run["failureCategory"] == "USER_CANCELLED"
    assert run["nodes"][0]["status"] == "CANCELLED"
    assert run["job"]["status"] == "CANCELLED"
    assert run["job"]["last_operator"] == "test_operator"
    assert run["streamEvents"][-1]["event_type"] == "RUN_CANCELLED"
    assert saved and saved[-1]["status"] == "CANCELLED"
    assert persisted == [{"run_id": run_id, "status": "CANCELLED", "symbol": "603663"}]
    assert research_updates == ["RUN_CANCELLED"]


@pytest.mark.asyncio
async def test_retry_failed_run_resets_failed_suffix_and_preserves_prior_nodes(monkeypatch, tmp_path):
    started: list[str] = []
    saved: list[dict] = []
    run_id = "RUN_RETRY_001"
    run = {
        "runId": run_id,
        "status": "FAILED",
        "failReason": "old failure",
        "failureCategory": "LLM_FAILED",
        "updatedAt": "2026-05-20T10:00:00",
        "nodes": [
            {"id": "orchestrator", "status": "PASS", "isRunning": False, "rawJson": {"keep": True}, "outputSummary": "ok"},
            {"id": "dvg_gate", "status": "FAIL", "isRunning": False, "rawJson": {"llmRunner": {"status": "FAILED"}, "llmOutputText": "bad"}, "outputSummary": "bad"},
            {"id": "final_writer", "status": "WAIT", "isRunning": False, "rawJson": {"llmOutput": {"old": True}}, "outputSummary": "old"},
        ],
        "agentOutputs": {"orchestrator": {"ok": True}, "dvg_gate": {"bad": True}, "final_writer": {"old": True}},
        "agentModuleResults": {"dvg_gate": {"bad": True}},
        "llmTrace": [
            {"nodeId": "orchestrator", "status": "COMPLETED"},
            {"nodeId": "dvg_gate", "status": "FAILED"},
        ],
        "agentResults": [{"node": "orchestrator", "status": "PASS"}, {"node": "dvg_gate", "status": "FAIL"}],
    }

    async def fake_start_analysis_run(next_run_id: str, payload: dict | None = None):
        started.append(next_run_id)
        return SimpleNamespace(run_id=next_run_id, status="RUNNING")

    monkeypatch.setattr(routes_analysis, "runs_store", {run_id: run})
    monkeypatch.setattr(routes_analysis, "save_run", lambda run_data: saved.append(run_data.copy()))
    monkeypatch.setattr(routes_analysis, "start_analysis_run", fake_start_analysis_run)
    monkeypatch.setattr(routes_analysis.analysis_job_store, "STORAGE_FILE", tmp_path / "analysis_jobs.json")

    result = await routes_analysis.retry_analysis_run(run_id)

    assert result.status == "RUNNING"
    assert started == [run_id]
    assert run["retry"]["from_node_id"] == "dvg_gate"
    assert run["retry"]["previous_status"] == "FAILED"
    assert run["status"] == "CREATED"
    assert run["failReason"] == ""
    assert run["nodes"][0]["status"] == "PASS"
    assert run["nodes"][1]["status"] == "WAIT"
    assert run["nodes"][1]["outputSummary"] == ""
    assert "llmRunner" not in run["nodes"][1]["rawJson"]
    assert run["nodes"][2]["status"] == "WAIT"
    assert run["agentOutputs"] == {"orchestrator": {"ok": True}}
    assert run["llmTrace"] == [{"nodeId": "orchestrator", "status": "COMPLETED"}]
    assert run["agentResults"] == [{"node": "orchestrator", "status": "PASS"}]
    assert saved and saved[-1]["retry"]["from_node_id"] == "dvg_gate"


@pytest.mark.asyncio
async def test_retry_failed_run_resumes_after_non_executable_plugin_observation(monkeypatch, tmp_path):
    started: list[str] = []
    saved: list[dict] = []
    run_id = "RUN_RETRY_PLUGIN_001"
    plugin_node_id = "plugin:technical_kline_readonly:technical_kline_analyst"
    run = {
        "runId": run_id,
        "status": "FAILED",
        "failReason": "plugin failed",
        "failureCategory": "EXECUTION_FAILED",
        "updatedAt": "2026-05-21T12:00:00",
        "nodes": [
            {"id": "technical_kline_analyst", "status": "WARN", "isRunning": False, "rawJson": {}, "outputSummary": "warn"},
            {
                "id": plugin_node_id,
                "status": "FAIL",
                "isRunning": False,
                "isSkipped": False,
                "rawJson": {
                    "nodeType": "plugin_observation",
                    "dagRegistration": {"execution_mode": "PLAN_ONLY_NO_EXECUTION"},
                    "permissionSandbox": {"mode": "READ_ONLY_NO_CODE"},
                    "canExecuteCode": False,
                    "directExecution": False,
                },
                "outputSummary": "bad",
            },
            {"id": "quant_engine", "status": "WAIT", "isRunning": False, "rawJson": {"llmRunner": {"status": "FAILED"}}, "outputSummary": "old"},
            {"id": "final_writer", "status": "WAIT", "isRunning": False, "rawJson": {"llmOutputText": "old"}, "outputSummary": "old"},
        ],
        "agentOutputs": {"technical_kline_analyst": {"ok": True}, plugin_node_id: {"old": True}, "quant_engine": {"old": True}},
        "agentModuleResults": {plugin_node_id: {"old": True}, "quant_engine": {"old": True}},
        "llmTrace": [
            {"nodeId": "technical_kline_analyst", "status": "FAILED"},
            {"nodeId": "quant_engine", "status": "FAILED"},
        ],
        "agentResults": [
            {"node": "technical_kline_analyst", "status": "WARN"},
            {"node": "quant_engine", "status": "FAIL"},
        ],
    }

    async def fake_start_analysis_run(next_run_id: str, payload: dict | None = None):
        started.append(next_run_id)
        return SimpleNamespace(run_id=next_run_id, status="RUNNING")

    monkeypatch.setattr(routes_analysis, "runs_store", {run_id: run})
    monkeypatch.setattr(routes_analysis, "save_run", lambda run_data: saved.append(run_data.copy()))
    monkeypatch.setattr(routes_analysis, "start_analysis_run", fake_start_analysis_run)
    monkeypatch.setattr(routes_analysis.analysis_job_store, "STORAGE_FILE", tmp_path / "analysis_jobs.json")

    result = await routes_analysis.retry_analysis_run(run_id)

    plugin_node = run["nodes"][1]
    assert result.status == "RUNNING"
    assert started == [run_id]
    assert run["retry"]["from_node_id"] == "quant_engine"
    assert plugin_node["status"] == "REVIEW_ONLY"
    assert plugin_node["isSkipped"] is True
    assert plugin_node["rawJson"]["pluginObservation"]["status"] == "RECORDED_NO_EXECUTION"
    assert run["nodes"][2]["status"] == "WAIT"
    assert run["nodes"][2]["outputSummary"] == ""
    assert "llmRunner" not in run["nodes"][2]["rawJson"]
    assert run["agentOutputs"] == {"technical_kline_analyst": {"ok": True}, plugin_node_id: {"old": True}}
    assert run["llmTrace"] == [{"nodeId": "technical_kline_analyst", "status": "FAILED"}]
    assert run["agentResults"] == [{"node": "technical_kline_analyst", "status": "WARN"}]
    assert saved and saved[-1]["retry"]["from_node_id"] == "quant_engine"


def test_stale_running_run_recovery_writes_audit_and_reason(monkeypatch, tmp_path):
    saved: list[dict] = []
    run_id = "RUN_STALE_001"
    run = {
        "runId": run_id,
        "status": "RUNNING",
        "updatedAt": "2026-05-20T08:00:00",
        "createdAt": "2026-05-20T07:55:00",
        "nodes": [{"id": "final_writer", "status": "RUNNING", "isRunning": True}],
        "auditLog": [],
        "streamEvents": [],
    }

    monkeypatch.setattr(routes_analysis, "save_run", lambda run_data: saved.append(run_data.copy()))
    monkeypatch.setattr(routes_analysis.analysis_job_store, "STORAGE_FILE", tmp_path / "analysis_jobs.json")

    recovered = routes_analysis._recover_stale_running_runs(
        {run_id: run},
        now=datetime.fromisoformat("2026-05-20T11:00:00"),
        stale_after=timedelta(hours=2),
        source="test",
    )

    assert recovered == 1
    assert run["status"] == "STALE"
    assert "watchdog" in run["failReason"]
    assert run["failureCategory"] == "STALE_RUN_RECOVERY"
    assert run["updatedAt"] == "2026-05-20T11:00:00"
    assert run["recovery"]["statusBefore"] == "RUNNING"
    assert run["recovery"]["statusAfter"] == "STALE"
    assert run["recovery"]["source"] == "test"
    assert run["recoveryEvents"][-1]["auditId"] == f"AUD_STALE_{run_id}"
    assert run["auditLog"][-1]["eventType"] == "RUN_STALE_RECOVERED"
    assert run["streamEvents"][-1]["event_type"] == "RUN_STALE_RECOVERED"
    assert run["job"]["status"] == "STALE"
    assert run["job"]["last_operator"] == "watchdog"
    assert run["nodes"][0]["isRunning"] is False
    assert run["nodes"][0]["status"] == "FAIL"
    assert saved and saved[-1]["status"] == "STALE"


@pytest.mark.asyncio
async def test_stale_running_run_is_recovered_before_start(monkeypatch, tmp_path):
    saved: list[dict] = []
    run_id = "RUN_STALE_START_001"
    monkeypatch.setattr(
        routes_analysis,
        "runs_store",
        {
            run_id: {
                "runId": run_id,
                "status": "RUNNING",
                "updatedAt": "2000-01-01T00:00:00",
                "createdAt": "2000-01-01T00:00:00",
                "nodes": [],
                "auditLog": [],
                "streamEvents": [],
            }
        },
    )
    monkeypatch.setattr(routes_analysis, "save_run", lambda run_data: saved.append(run_data.copy()))
    monkeypatch.setattr(routes_analysis.analysis_job_store, "STORAGE_FILE", tmp_path / "analysis_jobs.json")

    with pytest.raises(HTTPException) as exc:
        await routes_analysis.start_analysis_run(run_id)

    assert exc.value.status_code == 409
    assert "STALE" in exc.value.detail
    assert routes_analysis.runs_store[run_id]["status"] == "STALE"
    assert routes_analysis.runs_store[run_id]["failReason"]
    assert saved and saved[-1]["status"] == "STALE"


@pytest.mark.asyncio
async def test_list_analysis_runs_exposes_recovered_failure_reason(monkeypatch, tmp_path):
    saved: list[dict] = []
    run_id = "RUN_STALE_LIST_001"
    monkeypatch.setattr(
        routes_analysis,
        "runs_store",
        {
            run_id: {
                "runId": run_id,
                "stockCode": "603663",
                "stockName": "stock",
                "taskType": "position_review",
                "runMode": "STANDARD_MODE",
                "status": "RUNNING",
                "finalAction": "WAIT",
                "createdAt": "2000-01-01T00:00:00",
                "updatedAt": "2000-01-01T00:00:00",
                "nodes": [],
                "auditLog": [],
                "streamEvents": [],
            }
        },
    )
    monkeypatch.setattr(routes_analysis, "save_run", lambda run_data: saved.append(run_data.copy()))
    monkeypatch.setattr(routes_analysis.analysis_job_store, "STORAGE_FILE", tmp_path / "analysis_jobs.json")

    result = await routes_analysis.list_analysis_runs()

    assert result[0]["runId"] == run_id
    assert result[0]["status"] == "STALE"
    assert result[0]["failureCategory"] == "STALE_RUN_RECOVERY"
    assert "watchdog" in result[0]["failReason"]
    assert result[0]["recovery"]["statusAfter"] == "STALE"
    assert result[0]["job"]["status"] == "STALE"
    assert saved and saved[-1]["status"] == "STALE"


@pytest.mark.asyncio
async def test_list_analysis_runs_hides_unmaterialized_zero_node_shells(monkeypatch):
    shell_id = "RUN_ZERO_NODE_SHELL_001"
    stale_with_dag_id = "RUN_REAL_STALE_WITH_DAG_001"
    completed_id = "RUN_COMPLETED_SUMMARY_001"
    monkeypatch.setattr(
        routes_analysis,
        "runs_store",
        {
            shell_id: {
                "runId": shell_id,
                "stockCode": "603663",
                "stockName": "",
                "taskType": "position_review",
                "runMode": "STANDARD_MODE",
                "status": "STALE",
                "finalAction": "WAIT",
                "createdAt": "2026-05-24T13:20:21",
                "updatedAt": "2026-05-24T21:42:03",
                "nodes": [],
                "agentResults": [],
                "auditLog": [],
                "streamEvents": [],
                "failureCategory": "STALE_RUN_RECOVERY",
                "failReason": "分析运行由 watchdog 自动恢复：任务长时间停留在 RUNNING。",
                "recovery": {"statusAfter": "STALE"},
            },
            stale_with_dag_id: {
                "runId": stale_with_dag_id,
                "stockCode": "603663",
                "stockName": "",
                "taskType": "position_review",
                "runMode": "STANDARD_MODE",
                "status": "STALE",
                "finalAction": "WAIT",
                "createdAt": "2026-05-24T13:10:00",
                "updatedAt": "2026-05-24T13:20:00",
                "nodes": [{"id": "orchestrator", "status": "FAIL", "isRunning": False}],
                "agentResults": [],
                "auditLog": [],
                "streamEvents": [],
                "failureCategory": "STALE_RUN_RECOVERY",
                "failReason": "watchdog recovered a real DAG run.",
                "recovery": {"statusAfter": "STALE"},
            },
            completed_id: {
                "runId": completed_id,
                "stockCode": "603663",
                "stockName": "",
                "taskType": "position_review",
                "runMode": "STANDARD_MODE",
                "status": "COMPLETED",
                "finalAction": "WAIT",
                "createdAt": "2026-05-24T12:00:00",
                "updatedAt": "2026-05-24T12:30:00",
                "nodes": [],
                "agentResults": [],
                "auditLog": [],
                "streamEvents": [],
                "compressedSummary": {"quality": {"score": 82}},
            },
        },
    )

    result = await routes_analysis.list_analysis_runs()

    run_ids = {item["runId"] for item in result}
    assert shell_id not in run_ids
    assert stale_with_dag_id in run_ids
    assert completed_id in run_ids


@pytest.mark.asyncio
async def test_create_run_rejects_missing_research_iteration(monkeypatch):
    monkeypatch.setattr(routes_analysis, "runs_store", {})

    with pytest.raises(HTTPException) as exc:
        await routes_analysis.create_analysis_run(
            CreateAnalysisRequest(
                symbol="603663",
                task_type="position_review",
                run_mode="STANDARD_MODE",
                scenario_id="qiam_discounted",
                user_constraints={},
                config_profile_id="default",
                research_iteration_id="RITER_MISSING",
            )
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Research iteration not found"


@pytest.mark.asyncio
async def test_research_iteration_loop_mismatch_returns_bad_request(monkeypatch):
    class FakeResearchLoopStore:
        async def list_iterations(self, loop_id=None):
            assert loop_id is None
            return [SimpleNamespace(iteration_id="RITER_LINKED", loop_id="RLOOP_A")]

    monkeypatch.setattr(routes_analysis, "research_loop_store", FakeResearchLoopStore())

    with pytest.raises(HTTPException) as exc:
        await routes_analysis._validate_research_context("RLOOP_B", "RITER_LINKED")

    assert exc.value.status_code == 400
    assert exc.value.detail == "Research loop and iteration do not match"
