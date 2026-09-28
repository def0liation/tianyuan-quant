import pytest
from uuid import uuid4

from fastapi import HTTPException

from app.api import routes_analysis
from app.core.final_report_store import final_report_store
from app.core.signalops_store import signalops_store
from app.db.repositories import RunRepository


def _sample_run(run_id: str, symbol: str = "603663") -> dict:
    return {
        "runId": run_id,
        "auditId": f"AUD_{run_id}",
        "stockCode": symbol,
        "stockName": "Unit Test Stock",
        "taskType": "position_review",
        "dataMode": "REAL",
        "status": "COMPLETED",
        "finalAction": "WAIT",
        "killSwitch": {"active": False, "level": "NONE", "finalWriterMode": "NORMAL"},
        "dvg": {"allowedOutputLevel": "FULL"},
        "qiam": {"finalBuySuitability": "BUY"},
        "signalOps": {"signalStatus": "QUALIFIED", "blockedReason": ""},
        "dataSources": {"summary": {"availableCount": 3, "totalCount": 3}},
        "finalWriter": {
            "mode": "NORMAL",
            "finalAction": "WAIT",
            "humanConfirmationRequired": True,
            "auditId": f"AUD_FW_{run_id}",
            "sections": [
                {
                    "title": "Conclusion",
                    "content": "Hold current position and wait for trigger confirmation.",
                    "riskLevel": "LOW",
                    "requiresConfirmation": True,
                }
            ],
        },
    }


@pytest.mark.asyncio
async def test_final_report_upsert_updates_existing_run_report():
    run_id = f"RUN_RPT_{uuid4().hex[:8]}"
    run = _sample_run(run_id)

    first = await final_report_store.upsert_from_run(run)
    assert first is not None
    assert first["run_id"] == run_id
    assert first["final_action"] == "WAIT"
    assert first["summary"].startswith("Hold current position")

    run["finalWriter"] = {
        **run["finalWriter"],
        "finalAction": "REVIEW_ONLY",
        "sections": [
            {
                "title": "Conclusion",
                "content": "Review only after DVG evidence changes.",
                "riskLevel": "MEDIUM",
                "requiresConfirmation": True,
            }
        ],
    }
    second = await final_report_store.upsert_from_run(run)

    assert second["report_id"] == first["report_id"]
    assert second["final_action"] == "REVIEW_ONLY"
    assert second["sections"][0]["content"].startswith("Review only")


@pytest.mark.asyncio
async def test_final_report_routes_create_lazy_asset_and_list(monkeypatch):
    run_id = f"RUN_ROUTE_RPT_{uuid4().hex[:8]}"
    symbol = f"RT{uuid4().hex[:6].upper()}"
    run = _sample_run(run_id, symbol=symbol)
    snapshot = dict(routes_analysis.runs_store)
    saved: list[dict] = []
    monkeypatch.setattr(routes_analysis, "save_run", lambda item: saved.append(item.copy()))
    routes_analysis.runs_store.clear()
    routes_analysis.runs_store[run_id] = run

    try:
        report = await routes_analysis.get_analysis_run_report(run_id)
        assert report["run_id"] == run_id
        assert report["symbol"] == symbol
        assert saved[-1]["finalReportAsset"]["reportId"] == report["report_id"]

        listed = await routes_analysis.list_final_reports(symbol=symbol, limit=10)
        assert any(item["report_id"] == report["report_id"] for item in listed)

        loaded = await routes_analysis.get_final_report(report["report_id"])
        assert loaded["report_id"] == report["report_id"]
    finally:
        routes_analysis.runs_store.clear()
        routes_analysis.runs_store.update(snapshot)


@pytest.mark.asyncio
async def test_final_report_route_returns_404_when_unavailable():
    run_id = f"RUN_NO_RPT_{uuid4().hex[:8]}"
    snapshot = dict(routes_analysis.runs_store)
    routes_analysis.runs_store.clear()
    routes_analysis.runs_store[run_id] = {"runId": run_id, "status": "COMPLETED"}

    try:
        with pytest.raises(HTTPException) as exc:
            await routes_analysis.get_analysis_run_report(run_id)
        assert exc.value.status_code == 404
    finally:
        routes_analysis.runs_store.clear()
        routes_analysis.runs_store.update(snapshot)


@pytest.mark.asyncio
async def test_delete_run_cleans_report_and_unreferenced_signal_assets():
    run_id = f"RUN_DELETE_RPT_{uuid4().hex[:8]}"
    symbol = f"DL{uuid4().hex[:6].upper()}"
    run = _sample_run(run_id, symbol=symbol)
    await RunRepository().save(run)
    report = await final_report_store.upsert_from_run(run)
    signal = await signalops_store.upsert_from_run(run)

    deleted = await RunRepository().delete_by_run_id(run_id)

    assert deleted == 1
    assert await final_report_store.get_by_report_id(report["report_id"]) is None
    remaining = await signalops_store.list_signals(symbol=symbol, limit=10)
    assert all(item["signal_id"] != signal["signal_id"] for item in remaining)
