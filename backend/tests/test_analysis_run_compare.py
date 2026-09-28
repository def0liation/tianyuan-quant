from copy import deepcopy

import httpx
import pytest

from app.api import routes_analysis
from app.core import analysis_run_compare
from app.main import app


@pytest.fixture(autouse=True)
def restore_runs_store():
    snapshot = deepcopy(routes_analysis.runs_store)
    yield
    routes_analysis.runs_store.clear()
    routes_analysis.runs_store.update(snapshot)


def _run(run_id: str, final_action: str, signal_status: str):
    return {
        "runId": run_id,
        "stockCode": "002846",
        "stockName": "英联股份",
        "runMode": "STANDARD_MODE",
        "status": "COMPLETED",
        "dataMode": "LIVE",
        "createdAt": "2026-05-17T10:00:00",
        "updatedAt": "2026-05-17T10:01:00",
        "dvg": {
            "dataReliability": "MEDIUM",
            "finalDecisionCap": "NO_BUY",
            "criticalMissingData": ["公告数据"],
        },
        "qiam": {"probabilityBandUp": 0.42, "finalBuySuitability": "NEUTRAL"},
        "portfolio": {"portfolioCoverage": "HOLDINGS_CONNECTED", "allowAddPosition": False},
        "execution": {"executionReachability": "REACHABLE", "allowedActions": ["WAIT"]},
        "signalOps": {
            "signalStatus": signal_status,
            "blockedReason": "DVG REVIEW_ONLY",
            "triggerConditions": ["数据修复"],
            "invalidationConditions": [],
        },
        "finalWriter": {
            "finalAction": final_action,
            "mode": "NORMAL",
            "auditId": f"AUD_{run_id}",
            "sections": [
                {
                    "title": "当前动作",
                    "content": f"当前动作为 {final_action}",
                    "riskLevel": "MEDIUM",
                    "requiresConfirmation": True,
                }
            ],
        },
        "dataSources": {
            "summary": {
                "availableCount": 2,
                "totalCount": 6,
                "availableRatio": "2/6",
                "overallStatus": "PARTIAL",
                "overallDataMode": "LIVE",
            },
            "sources": {
                "chip": {
                    "fallbackChain": [
                        {"adapterId": "tushare", "provider": "tushare", "error": "no records"}
                    ]
                }
            },
        },
        "agentResults": [
            {"node": "dvg_gate", "status": "WARN"},
            {"node": "final_writer", "status": "PASS"},
        ],
    }


def test_compare_runs_includes_decision_snapshot_fields():
    left = _run("RUN_LEFT", "WAIT", "WATCH")
    right = _run("RUN_RIGHT", "PAPER_TEST_ONLY", "PAPER_TEST")
    right["dataSources"]["summary"]["availableCount"] = 4
    right["agentResults"][0]["status"] = "PASS"
    routes_analysis.runs_store.clear()
    routes_analysis.runs_store.update({"RUN_LEFT": left, "RUN_RIGHT": right})

    result = routes_analysis._compare_runs("RUN_LEFT", "RUN_RIGHT")
    diffs = {item["key"]: item for item in result["diffs"]}

    assert diffs["final"]["label"] == "最终动作"
    assert diffs["final_mode"]["label"] == "最终输出模式"
    assert diffs["signal_blocked"]["label"] == "SignalOps 阻断原因"
    assert diffs["final"]["changed"] is True
    assert "最终动作从 WAIT 变为 PAPER_TEST_ONLY" in diffs["final"]["impact"]
    assert diffs["final_sections"]["changed"] is True
    assert "最终输出发生变化" in diffs["final_sections"]["impact"]
    assert diffs["signal_status"]["changed"] is True
    assert diffs["source_summary"]["changed"] is True
    assert diffs["source_fallback"]["left"] == ["chip:tushare:no records"]
    assert diffs["agent_statuses"]["changed"] is True
    assert result["summary"]
    assert all("changed" not in item for item in result["summary"])


def test_compare_runs_suppresses_signalops_pending_placeholder():
    left = _run("RUN_LEFT_PENDING", "WAIT", "WATCH")
    right = _run("RUN_RIGHT_PENDING", "WAIT", "WATCH")
    left["signalOps"]["blockedReason"] = "等待真实 Agent 运行"
    right["signalOps"]["blockedReason"] = "等待真实 Agent 运行"
    routes_analysis.runs_store.clear()
    routes_analysis.runs_store.update({"RUN_LEFT_PENDING": left, "RUN_RIGHT_PENDING": right})

    result = routes_analysis._compare_runs("RUN_LEFT_PENDING", "RUN_RIGHT_PENDING")
    diff = {item["key"]: item for item in result["diffs"]}["signal_blocked"]

    assert diff["label"] == "SignalOps 阻断原因"
    assert diff["left"] == ""
    assert diff["right"] == ""
    assert diff["changed"] is False


def test_route_compare_delegates_to_core_compare_service(monkeypatch):
    calls: dict[str, object] = {}

    def fake_compare_runs(left_id: str, right_id: str, *, load_run, is_legacy_run) -> dict:
        calls["left_id"] = left_id
        calls["right_id"] = right_id
        calls["load_run"] = load_run
        calls["is_legacy_run"] = is_legacy_run
        return {"leftRun": {}, "rightRun": {}, "changedCount": 0, "summary": [], "diffs": []}

    monkeypatch.setattr(routes_analysis.analysis_run_compare, "compare_runs", fake_compare_runs)

    result = routes_analysis._compare_runs("RUN_ROUTE_LEFT", "RUN_ROUTE_RIGHT")

    assert result["changedCount"] == 0
    assert calls == {
        "left_id": "RUN_ROUTE_LEFT",
        "right_id": "RUN_ROUTE_RIGHT",
        "load_run": routes_analysis._get_run_or_load,
        "is_legacy_run": routes_analysis._is_legacy_mock_run,
    }


@pytest.mark.asyncio
async def test_compare_runs_get_endpoint_returns_public_diff_payload():
    left = _run("RUN_LEFT_API", "WAIT", "WATCH")
    right = _run("RUN_RIGHT_API", "PAPER_TEST_ONLY", "PAPER_TEST")
    routes_analysis.runs_store.clear()
    routes_analysis.runs_store.update({"RUN_LEFT_API": left, "RUN_RIGHT_API": right})

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            "/api/analysis/runs/compare",
            params={"left": "RUN_LEFT_API", "right": "RUN_RIGHT_API"},
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["leftRun"]["runId"] == "RUN_LEFT_API"
    assert payload["rightRun"]["runId"] == "RUN_RIGHT_API"
    assert payload["changedCount"] > 0
    diff_keys = {item["key"] for item in payload["diffs"]}
    assert {"final", "signal_status"}.issubset(diff_keys)


@pytest.mark.asyncio
async def test_compare_runs_post_endpoint_preserves_not_found_error_body():
    routes_analysis.runs_store.clear()
    routes_analysis.runs_store["RUN_LEFT_API"] = _run("RUN_LEFT_API", "WAIT", "WATCH")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/analysis/runs/compare",
            json={"left": "RUN_LEFT_API", "right": "RUN_MISSING_API"},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Right run not found: RUN_MISSING_API"


def test_core_compare_rejects_legacy_runs_without_fastapi_dependency():
    left = _run("RUN_LEFT_CORE", "WAIT", "WATCH")
    right = _run("RUN_LEGACY_CORE", "WAIT", "WATCH")
    runs = {"RUN_LEFT_CORE": left, "RUN_LEGACY_CORE": right}

    with pytest.raises(analysis_run_compare.AnalysisRunCompareNotFound) as exc_info:
        analysis_run_compare.compare_runs(
            "RUN_LEFT_CORE",
            "RUN_LEGACY_CORE",
            load_run=runs.get,
            is_legacy_run=lambda run_id, _run_data: run_id == "RUN_LEGACY_CORE",
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Right run not found: RUN_LEGACY_CORE"
