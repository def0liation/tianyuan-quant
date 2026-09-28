import asyncio
import httpx
import pytest

from app.api import routes_backtest
from app.core import backtest_store as backtest_store_module
from app.core.backtest_store import BacktestStore
from app.core.research_store import ResearchLoopStore
from app.core.signalops_store import signalops_store
from app.main import app
from app.models.research import AttachResearchBacktestRequest, CreateResearchLoopRequest


async def _create_signalops_signal(symbol: str, run_id: str = "RUN_SAMPLE_SIGNAL"):
    return await signalops_store.upsert_from_run(
        {
            "runId": run_id,
            "stockCode": symbol,
            "stockName": "SignalOps Sample",
            "dvg": {"allowedOutputLevel": "FULL"},
            "qiam": {"finalBuySuitability": "BUY"},
            "portfolio": {"allowAddPosition": True},
            "finalWriter": {"finalAction": "BUY"},
            "signalOps": {
                "signalStatus": "QUALIFIED",
                "riskPassed": True,
                "dvgPassed": True,
                "qiamPassed": True,
                "executionReachable": True,
                "triggerConditions": ["sample breakout"],
                "invalidationConditions": ["sample invalidation"],
                "reviewFields": [],
                "blockedReason": "",
            },
        }
    )


@pytest.mark.asyncio
async def test_signalops_sample_api_persists_signals_and_weak_provenance(monkeypatch):
    symbol = "BTSAMPLE01"
    await _create_signalops_signal(symbol)

    async def fake_fetch(symbol: str, start_date: str, end_date: str):
        return [
            {"date": "2026-01-01", "open": 10, "close": 10, "prev_close": 10},
            {"date": "2026-01-02", "open": 10.5, "close": 11, "prev_close": 10},
            {"date": "2026-01-05", "open": 11, "close": 11.2, "prev_close": 11},
        ]

    monkeypatch.setattr("app.core.backtest_store.fetch_historical_for_backtest", fake_fetch)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/api/backtest/signalops-sample",
            json={
                "symbol": symbol,
                "start_date": "2026-01-01",
                "end_date": "2026-01-05",
                "signal_date": "2026-01-01",
            },
        )

    assert response.status_code == 200
    data = response.json()
    run_id = data["run_id"]
    report = data["run"]["report"]

    try:
        assert data["signal_source"] == "SIGNALOPS"
        assert data["market_data_source"] == "TUSHARE"
        assert data["sample_window"]["tradingDays"] == 3
        assert data["evidence_strength"]["canSupportResearchVerdict"] is False
        assert data["evidence_strength"]["weakSample"] is True
        assert data["limitations"]
        assert report["provenance"]["signalSource"] == "SIGNALOPS"
        assert report["provenance"]["sourceSignalIds"]
        assert report["evidenceStrength"]["canSupportResearchVerdict"] is False

        store = BacktestStore()
        signals = await store.get_signals(run_id)
        assert len(signals) == 1
        assert signals[0]["metadata_json"]["source"] == "SIGNALOPS_LIFECYCLE_FALLBACK"
        assert signals[0]["metadata_json"]["source_detail"] == "SIGNALOPS_LIFECYCLE_FALLBACK"
        assert signals[0]["metadata_json"]["signalops_version"] == "AUTO_PAPER_V2"
    finally:
        await BacktestStore().delete_run(run_id)


@pytest.mark.asyncio
async def test_research_backtest_canonical_routes_and_legacy_read_compatibility():
    symbol = "BTCANON01"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/api/research/backtest/runs",
            json={
                "symbol": symbol,
                "start_date": "2026-02-01",
                "end_date": "2026-02-05",
                "parameters": {"data_source": "MOCK", "signal_source": "NONE"},
            },
        )
        assert response.status_code == 200, response.text
        run_id = response.json()["run_id"]

        legacy_response = await client.get(f"/api/backtest/runs/{run_id}")
        package_response = await client.get(f"/api/research/backtest/runs/{run_id}/experiment-package")
        legacy_package_response = await client.get(f"/api/backtest/runs/{run_id}/experiment-package")
        summary_response = await client.get("/api/research/backtest/summary")

    try:
        assert legacy_response.status_code == 200, legacy_response.text
        assert legacy_response.json()["run_id"] == run_id
        assert package_response.status_code == 200, package_response.text
        package = package_response.json()
        assert package["package_id"].startswith("BTEP_")
        assert package["run_id"] == run_id
        assert package["manifest"]["schemaVersion"] == "backtest_experiment_package_v1"
        assert package["manifest"]["hashes"]["dataPackageHash"] == package["run"]["report"]["provenance"]["dataPackageHash"]
        assert package["simulation_only"] is True
        assert package["is_real_trade"] is False
        assert legacy_package_response.status_code == 200, legacy_package_response.text
        assert legacy_package_response.json()["package_id"] == package["package_id"]
        assert summary_response.status_code == 200, summary_response.text
        assert summary_response.json()["completed_runs"] >= 1
    finally:
        await BacktestStore().delete_run(run_id)


@pytest.mark.asyncio
async def test_backtest_parameter_scan_history_routes_expose_retained_trials():
    symbol = "BTSCANROUTE01"
    run_ids: list[str] = []
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/api/research/backtest/parameter-scan",
            json={
                "symbol": symbol,
                "start_date": "2026-03-01",
                "end_date": "2026-03-08",
                "base_parameters": {
                    "signal_source": "MOCK",
                    "data_source": "MOCK",
                    "walk_forward": {"enabled": True, "folds": 2},
                },
                "parameter_grid": {"signal_min_strength": [0.3, 0.6]},
                "windows": [
                    {"start": "2026-03-01", "end": "2026-03-04", "label": "early"},
                    {"start": "2026-03-05", "end": "2026-03-08", "label": "late"},
                ],
                "max_combinations": 2,
                "reuse_existing": False,
                "force_new": True,
            },
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        run_ids = payload["run_ids"]
        history_response = await client.get(f"/api/research/backtest/parameter-scans?symbol={symbol}&limit=5")
        legacy_history_response = await client.get(f"/api/backtest/parameter-scans?symbol={symbol}&limit=5")

    try:
        assert payload["scan_id"].startswith("BTS_")
        assert payload["simulation_only"] is True
        assert payload["is_real_trade"] is False
        assert payload["window_count"] == 2
        assert payload["trial_count"] == 4
        assert payload["summary"]["totalCombinations"] == 2
        assert payload["summary"]["totalTrials"] == 4
        assert history_response.status_code == 200, history_response.text
        history = history_response.json()
        item = next(entry for entry in history if entry["scan_id"] == payload["scan_id"])
        assert set(item["run_ids"]) == set(run_ids)
        assert item["best_run_id"] == payload["best_run_id"]
        assert item["trial_count"] == 4
        assert item["window_count"] == 2
        assert item["summary"]["totalCombinations"] == 2
        assert item["summary"]["totalTrials"] == 4
        assert item["summary"]["bestValidationProtocol"]["parameterScan"]["enabled"] is True
        assert item["simulation_only"] is True
        assert item["is_real_trade"] is False
        assert legacy_history_response.status_code == 200, legacy_history_response.text
        assert any(entry["scan_id"] == payload["scan_id"] for entry in legacy_history_response.json())
    finally:
        for run_id in run_ids:
            await BacktestStore().delete_run(run_id)


@pytest.mark.asyncio
async def test_backtest_parameter_scan_job_routes_complete_and_expose_result(monkeypatch, tmp_path):
    monkeypatch.setattr(backtest_store_module, "PARAMETER_SCAN_JOB_STORE_FILE", tmp_path / "backtest_parameter_scan_jobs.json")
    handoff_dir = tmp_path / "backtest-parameter-scan-handoff"
    monkeypatch.setenv("BACKTEST_PARAMETER_SCAN_HANDOFF_DIR", str(handoff_dir))
    test_store = BacktestStore()
    monkeypatch.setattr(routes_backtest, "backtest_store", test_store)
    symbol = "BTSCANJOBROUTE01"
    run_ids: list[str] = []
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/api/research/backtest/parameter-scan/jobs",
            json={
                "symbol": symbol,
                "start_date": "2026-04-01",
                "end_date": "2026-04-08",
                "base_parameters": {
                    "signal_source": "MOCK",
                    "data_source": "MOCK",
                    "walk_forward": {"enabled": True, "folds": 2},
                },
                "parameter_grid": {"signal_min_strength": [0.3, 0.6]},
                "windows": [
                    {"start": "2026-04-01", "end": "2026-04-04", "label": "early"},
                    {"start": "2026-04-05", "end": "2026-04-08", "label": "late"},
                ],
                "max_combinations": 2,
                "reuse_existing": False,
                "force_new": True,
            },
        )
        assert response.status_code == 200, response.text
        job = response.json()
        for _ in range(80):
            job_response = await client.get(f"/api/research/backtest/parameter-scan/jobs/{job['jobId']}")
            assert job_response.status_code == 200, job_response.text
            job = job_response.json()
            if job["status"] in {"COMPLETED", "FAILED", "CANCELLED"}:
                break
            await asyncio.sleep(0.05)
        legacy_response = await client.get(f"/api/backtest/parameter-scan/jobs/{job['jobId']}")
        handoff_response = await client.post(f"/api/research/backtest/parameter-scan/jobs/{job['jobId']}/handoff")
        legacy_handoff_response = await client.post(f"/api/backtest/parameter-scan/jobs/{job['jobId']}/handoff")

    try:
        assert job["status"] == "COMPLETED"
        assert job["simulationOnly"] is True
        assert job["isRealTrade"] is False
        assert job["queueMode"] == "LOCAL_DURABLE_JSON"
        assert job["durable"] is True
        assert job["recovered"] is False
        assert job["idempotencyKey"].startswith("bt-parameter-scan-")
        assert job["leaseStatus"] == "RELEASED"
        assert job["leaseOwner"].startswith("local-backtest-worker-")
        assert job["leaseId"].startswith(job["currentAttemptId"])
        assert job["leaseReleasedAt"]
        assert job["attemptCount"] == 1
        assert job["lastAttemptStatus"] == "COMPLETED"
        assert job["currentAttemptId"] == job["attempts"][-1]["attemptId"]
        assert job["attempts"][-1]["status"] == "COMPLETED"
        assert job["attempts"][-1]["idempotencyKey"] == job["idempotencyKey"]
        assert job["attempts"][-1]["leaseStatus"] == "RELEASED"
        assert job["attempts"][-1]["leaseId"] == job["leaseId"]
        assert job["scanId"].startswith("BTS_")
        assert job["totalCombinations"] == 2
        assert job["totalTrials"] == 4
        assert job["windowCount"] == 2
        assert job["bestRunId"] in job["runIds"]
        assert job["scan"]["summary"]["totalTrials"] == 4
        assert job["attempts"][-1]["scanId"] == job["scanId"]
        run_ids = job["runIds"]
        assert legacy_response.status_code == 200, legacy_response.text
        assert legacy_response.json()["jobId"] == job["jobId"]
        assert legacy_response.json()["queueMode"] == "LOCAL_DURABLE_JSON"
        assert legacy_response.json()["idempotencyKey"] == job["idempotencyKey"]
        assert legacy_response.json()["attemptCount"] == 1
        assert handoff_response.status_code == 200, handoff_response.text
        handoff = handoff_response.json()
        assert handoff["schema"] == "backtest_parameter_scan_job_handoff_v1"
        assert handoff["status"] == "HANDED_OFF"
        assert handoff["jobId"] == job["jobId"]
        assert handoff["scanId"] == job["scanId"]
        assert handoff["jobStatus"] == "COMPLETED"
        assert handoff["handoffDestination"] == "LOCAL_DEPLOYMENT_HANDOFF_DIR"
        assert handoff["bundleChecksum"].startswith("bt-parameter-scan-handoff-")
        assert handoff["manifest"]["schema"] == "backtest_parameter_scan_job_handoff_manifest_v1"
        assert handoff["manifest"]["retentionPolicy"]["custody"] == "deployment_owned_after_handoff"
        assert handoff["simulationOnly"] is True
        assert handoff["isRealTrade"] is False
        assert (handoff_dir / handoff["bundleFile"]).exists()
        assert (handoff_dir / handoff["manifestFile"]).exists()
        assert legacy_handoff_response.status_code == 200, legacy_handoff_response.text
        assert legacy_handoff_response.json()["schema"] == "backtest_parameter_scan_job_handoff_v1"
    finally:
        for run_id in run_ids:
            await test_store.delete_run(run_id)


@pytest.mark.asyncio
async def test_signalops_sample_canonical_route_reuses_existing_run(monkeypatch):
    symbol = "BTSAMPLE02"
    await _create_signalops_signal(symbol, run_id="RUN_SAMPLE_SIGNAL_REUSE")

    async def fake_fetch(symbol: str, start_date: str, end_date: str):
        return [
            {"date": "2026-03-01", "open": 10, "close": 10, "prev_close": 10},
            {"date": "2026-03-02", "open": 10.2, "close": 10.4, "prev_close": 10},
            {"date": "2026-03-03", "open": 10.4, "close": 10.6, "prev_close": 10.4},
        ]

    monkeypatch.setattr("app.core.backtest_store.fetch_historical_for_backtest", fake_fetch)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        first = await client.post(
            "/api/research/backtest/signalops-sample",
            json={
                "symbol": symbol,
                "start_date": "2026-03-01",
                "end_date": "2026-03-03",
                "signal_date": "2026-03-01",
            },
        )
        second = await client.post(
            "/api/research/backtest/signalops-sample",
            json={
                "symbol": symbol,
                "start_date": "2026-03-01",
                "end_date": "2026-03-03",
                "signal_date": "2026-03-01",
            },
        )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    first_data = first.json()
    second_data = second.json()
    try:
        assert second_data["run_id"] == first_data["run_id"]
        assert second_data["run"]["parameters"]["dedupe_reused"] is True
    finally:
        await BacktestStore().delete_run(first_data["run_id"])


@pytest.mark.asyncio
async def test_referenced_backtest_delete_returns_409():
    store = BacktestStore()
    run = await store.create_run(
        symbol="BTREF01",
        start_date="2026-04-01",
        end_date="2026-04-05",
        parameters={"data_source": "MOCK", "signal_source": "NONE"},
    )
    research_store = ResearchLoopStore()
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="Referenced backtest",
            objective="Protect linked backtest evidence.",
            hypothesis="Deletion should be blocked while evidence points at the run.",
        )
    )
    await research_store.attach_backtest(
        detail.iterations[0].iteration_id,
        AttachResearchBacktestRequest(backtest_run_id=run["run_id"]),
    )

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.delete(f"/api/research/backtest/runs/{run['run_id']}")

    try:
        assert response.status_code == 409, response.text
        detail_payload = response.json()["detail"]
        assert detail_payload["message"] == "已被研究证据引用，不能删除"
        assert detail_payload["references"]
    finally:
        await store.delete_run(run["run_id"])
