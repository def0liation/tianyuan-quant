import pytest
import asyncio
import json
from datetime import datetime, timedelta
from uuid import uuid4
from sqlalchemy import func, select

from app.core import auto_paper_trading as auto_module
from app.core import backtest_store as backtest_store_module
from app.core.backtest_store import BacktestStore, normalize_tushare_daily_records
from app.core.backtest_engine import run_backtest
from app.core.signalops_store import signalops_store
from app.core.strategy_stability_quality import label_triple_barrier_event
from app.db.models_backtest import BacktestRunDB
from app.db.session import AsyncSessionLocal


def _fake_universe():
    return [
        {"symbol": "000001.SZ", "stock_name": "平安银行", "industry": "银行", "market": "主板", "exchange": "SZSE", "list_date": "1991-04-03"},
        {"symbol": "600000.SH", "stock_name": "浦发银行", "industry": "银行", "market": "主板", "exchange": "SSE", "list_date": "1999-11-10"},
        {"symbol": "300001.SZ", "stock_name": "特锐德", "industry": "电力设备", "market": "创业板", "exchange": "SZSE", "list_date": "2009-10-30"},
    ]


def _fake_random_market_rows(symbol: str, start_date: str, end_date: str):
    start = datetime.fromisoformat(start_date[:10])
    end = datetime.fromisoformat(end_date[:10])
    rows = []
    current = start
    close = 10.0 + (sum(ord(ch) for ch in symbol) % 5)
    index = 0
    while current <= end:
        if current.weekday() < 5:
            prev_close = close
            if index % 10 == 0:
                close = prev_close * 1.012
            elif index % 10 == 5:
                close = prev_close * 0.968
            else:
                close = prev_close * 1.001
            rows.append({
                "date": current.date().isoformat(),
                "symbol": symbol,
                "open": round((prev_close + close) / 2, 4),
                "high": round(max(prev_close, close) * 1.01, 4),
                "low": round(min(prev_close, close) * 0.99, 4),
                "close": round(close, 4),
                "prev_close": round(prev_close, 4),
                "volume": 100000 + index,
                "amount": 1000000 + index,
            })
            index += 1
        current += timedelta(days=1)
    return rows


def _fake_buy_only_market_rows(symbol: str, start_date: str, end_date: str):
    start = datetime.fromisoformat(start_date[:10])
    end = datetime.fromisoformat(end_date[:10])
    rows = []
    current = start
    close = 10.0 + (sum(ord(ch) for ch in symbol) % 5)
    index = 0
    while current <= end:
        if current.weekday() < 5:
            prev_close = close
            close = prev_close * (1.012 if index % 10 == 0 else 1.001)
            rows.append({
                "date": current.date().isoformat(),
                "symbol": symbol,
                "open": round((prev_close + close) / 2, 4),
                "high": round(max(prev_close, close) * 1.01, 4),
                "low": round(min(prev_close, close) * 0.99, 4),
                "close": round(close, 4),
                "prev_close": round(prev_close, 4),
                "volume": 100000 + index,
                "amount": 1000000 + index,
            })
            index += 1
        current += timedelta(days=1)
    return rows


def _fake_bottom_research_market_rows(symbol: str, start_date: str, end_date: str):
    start = datetime.fromisoformat(start_date[:10])
    end = datetime.fromisoformat(end_date[:10])
    rows = []
    current = start
    close = 80.0
    index = 0
    while current <= end:
        if current.weekday() < 5:
            cycle = index % 64
            prev_close = close
            if cycle < 22:
                close *= 0.986
            elif cycle < 42:
                close *= 1.014
            else:
                close *= 0.998
            rows.append({
                "date": current.date().isoformat(),
                "symbol": symbol,
                "open": round((prev_close + close) / 2, 4),
                "high": round(max(prev_close, close) * 1.018, 4),
                "low": round(min(prev_close, close) * 0.982, 4),
                "close": round(close, 4),
                "prev_close": round(prev_close, 4),
                "volume": 500000 + index * 1000,
                "amount": 5000000 + index * 10000,
            })
            index += 1
        current += timedelta(days=1)
    return rows


async def _wait_random_job(store: BacktestStore, job_id: str):
    for _ in range(80):
        job = await store.get_signalops_random_validation_job(job_id)
        if job and job["status"] in {"COMPLETED", "FAILED", "CANCELLED"}:
            return job
        await asyncio.sleep(0.05)
    raise AssertionError("SignalOps random validation job did not finish")


async def _wait_parameter_scan_job(store: BacktestStore, job_id: str):
    for _ in range(80):
        job = await store.get_parameter_scan_job(job_id)
        if job and job["status"] in {"COMPLETED", "FAILED", "CANCELLED"}:
            return job
        await asyncio.sleep(0.05)
    raise AssertionError("Backtest parameter scan job did not finish")


async def _backtest_run_count(symbol: str) -> int:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(func.count()).select_from(BacktestRunDB).where(BacktestRunDB.symbol == symbol)
        )
        return int(result.scalar_one())


def test_normalize_tushare_daily_records_sorts_and_maps_fields():
    rows = normalize_tushare_daily_records(
        [
            {
                "ts_code": "000001.SZ",
                "trade_date": "20260102",
                "open": 11,
                "high": 12,
                "low": 10,
                "close": 11.5,
                "pre_close": 10.8,
                "vol": 1000,
                "amount": 12000,
            },
            {
                "ts_code": "000001.SZ",
                "trade_date": "20260101",
                "open": 10,
                "high": 11,
                "low": 9.8,
                "close": 10.8,
                "pre_close": 10,
                "vol": 900,
                "amount": 9500,
            },
        ],
        "000001.SZ",
    )

    assert [row["date"] for row in rows] == ["2026-01-01", "2026-01-02"]
    assert rows[0]["prev_close"] == 10
    assert rows[1]["volume"] == 1000


@pytest.mark.asyncio
async def test_backtest_store_reuses_same_fingerprint_and_force_new_creates_new_run():
    store = BacktestStore()
    symbol = f"BTDEDUPE{uuid4().hex[:6].upper()}"
    first = await store.create_run(
        symbol=symbol,
        start_date="2026-01-01",
        end_date="2026-01-10",
        parameters={"data_source": "MOCK", "signal_source": "NONE", "slippage_bps": 10},
    )
    second = await store.create_run(
        symbol=symbol,
        start_date="2026-01-01",
        end_date="2026-01-10",
        parameters={"data_source": "MOCK", "signal_source": "NONE", "slippage_bps": 10},
    )
    forced = await store.create_run(
        symbol=symbol,
        start_date="2026-01-01",
        end_date="2026-01-10",
        parameters={"data_source": "MOCK", "signal_source": "NONE", "slippage_bps": 10},
        force_new=True,
    )

    try:
        assert second["run_id"] == first["run_id"]
        assert second["parameters"]["dedupe_reused"] is True
        assert forced["run_id"] != first["run_id"]
        assert first["parameters"]["backtest_fingerprint"] == forced["parameters"]["backtest_fingerprint"]
        assert await _backtest_run_count(symbol) == 2
    finally:
        await store.delete_run(first["run_id"])
        await store.delete_run(forced["run_id"])


@pytest.mark.asyncio
async def test_backtest_store_fingerprint_lock_prevents_concurrent_duplicates():
    store = BacktestStore()
    symbol = f"BTLOCK{uuid4().hex[:6].upper()}"

    results = await asyncio.gather(*[
        store.create_run(
            symbol=symbol,
            start_date="2026-02-01",
            end_date="2026-02-10",
            parameters={"data_source": "MOCK", "signal_source": "NONE", "commission_bps": 3},
        )
        for _ in range(5)
    ])

    try:
        run_ids = {item["run_id"] for item in results}
        assert len(run_ids) == 1
        assert await _backtest_run_count(symbol) == 1
        assert any(item["parameters"].get("dedupe_reused") for item in results[1:])
    finally:
        await store.delete_run(results[0]["run_id"])


@pytest.mark.asyncio
async def test_backtest_store_forces_simulation_boundary_on_created_runs():
    store = BacktestStore()
    symbol = f"BTSIM{uuid4().hex[:6].upper()}"
    result = await store.create_run(
        symbol=symbol,
        start_date="2026-01-01",
        end_date="2026-01-10",
        parameters={
            "data_source": "MOCK",
            "signal_source": "NONE",
            "simulation_only": False,
            "is_real_trade": True,
        },
        reuse_existing=False,
        force_new=True,
    )

    try:
        assert result["parameters"]["simulation_only"] is True
        assert result["parameters"]["is_real_trade"] is False
        package = await store.get_experiment_package(result["run_id"])
        assert package is not None
        assert package["simulation_only"] is True
        assert package["is_real_trade"] is False
        assert package["manifest"]["simulationOnly"] is True
        assert package["manifest"]["isRealTrade"] is False
        assert package["reproducibility"]["parameters"]["simulation_only"] is True
        assert package["reproducibility"]["parameters"]["is_real_trade"] is False
    finally:
        await store.delete_run(result["run_id"])


def test_backtest_report_provenance_caps_reported_real_trade_context():
    market_data = _fake_random_market_rows("000001.SZ", "2026-01-01", "2026-01-05")
    signalops_report = run_backtest(
        symbol="000001.SZ",
        stock_name="Ping An Bank",
        start_date="2026-01-01",
        end_date="2026-01-05",
        initial_capital=100000.0,
        market_data=market_data,
        signals=[],
        patch_params={
            "signalops_version": "AUTO_PAPER_V2",
            "signalops_context": {
                "signalOpsVersion": "AUTO_PAPER_V2",
                "simulationOnly": False,
                "isRealTrade": True,
            },
        },
        data_source="MOCK",
        signal_source="SIGNALOPS",
    )
    signalops_provenance = signalops_report.provenance
    assert signalops_provenance["simulationOnly"] is True
    assert signalops_provenance["isRealTrade"] is False
    assert signalops_provenance["reportedSimulationOnly"] is False
    assert signalops_provenance["reportedIsRealTrade"] is True

    mfe_report = run_backtest(
        symbol="000001.SZ",
        stock_name="Ping An Bank",
        start_date="2026-01-01",
        end_date="2026-01-05",
        initial_capital=100000.0,
        market_data=market_data,
        signals=[],
        patch_params={
            "mfe_mae_research_model_version": "mfe-mae-v1",
            "mfe_mae_research_context": {
                "model_version": "mfe-mae-v1",
                "simulation_only": False,
                "is_real_trade": True,
            },
        },
        data_source="MOCK",
        signal_source="MFE_MAE_PATH_RESEARCH",
    )
    mfe_provenance = mfe_report.provenance
    assert mfe_provenance["simulationOnly"] is True
    assert mfe_provenance["isRealTrade"] is False
    assert mfe_provenance["reportedSimulationOnly"] is False
    assert mfe_provenance["reportedIsRealTrade"] is True


def test_triple_barrier_label_identifies_take_profit_stop_and_vertical():
    profit_rows = [{"date": f"2026-05-{day:02d}", "open": 10, "high": 10.1, "low": 9.9, "close": 10} for day in range(1, 18)]
    profit_rows[15] = {"date": "2026-05-16", "open": 10, "high": 10.9, "low": 10.1, "close": 10.8}
    profit = label_triple_barrier_event(profit_rows, "2026-05-15", horizon_days=5)
    assert profit["triple_barrier_label"] == 1
    assert profit["first_barrier"] == "TAKE_PROFIT"

    stop_rows = [{"date": f"2026-06-{day:02d}", "open": 10, "high": 10.1, "low": 9.9, "close": 10} for day in range(1, 18)]
    stop_rows[15] = {"date": "2026-06-16", "open": 10, "high": 10.1, "low": 9.2, "close": 9.3}
    stop = label_triple_barrier_event(stop_rows, "2026-06-15", horizon_days=5)
    assert stop["triple_barrier_label"] == -1
    assert stop["first_barrier"] in {"STOP_LOSS", "SUPPORT_BREAK"}

    vertical_rows = [{"date": f"2026-07-{day:02d}", "open": 10, "high": 10.04, "low": 9.96, "close": 10} for day in range(1, 18)]
    vertical = label_triple_barrier_event(vertical_rows, "2026-07-15", horizon_days=2)
    assert vertical["triple_barrier_label"] == 0
    assert vertical["first_barrier"] == "VERTICAL"


@pytest.mark.asyncio
async def test_backtest_store_prefers_tushare_daily(monkeypatch):
    async def fake_fetch(symbol: str, start_date: str, end_date: str):
        return [
            {"date": "2026-01-01", "open": 10, "close": 10, "prev_close": 10},
            {"date": "2026-01-02", "open": 11, "close": 11, "prev_close": 10},
            {"date": "2026-01-03", "open": 12, "close": 12, "prev_close": 11},
        ]

    monkeypatch.setattr(backtest_store_module, "fetch_historical_for_backtest", fake_fetch)
    monkeypatch.setattr(
        backtest_store_module,
        "generate_mock_signals",
        lambda *args, **kwargs: [
            {
                "timestamp": "2026-01-01",
                "signal_type": "BUY",
                "direction": "BUY",
                "strength": 1.0,
                "source_node": "quant_engine",
            }
        ],
    )

    store = BacktestStore()
    result = await store.create_run(
        symbol="000001.SZ",
        start_date="2026-01-01",
        end_date="2026-01-03",
    )

    try:
        assert result["report"]["data_source"] == "TUSHARE"
        assert result["report"]["data_error"] is None
        assert result["report"]["data_points"] == 3
    finally:
        await store.delete_run(result["run_id"])


@pytest.mark.asyncio
async def test_backtest_store_falls_back_to_mock_when_tushare_fails(monkeypatch):
    async def fake_fetch(symbol: str, start_date: str, end_date: str):
        raise RuntimeError("network unavailable")

    monkeypatch.setattr(backtest_store_module, "fetch_historical_for_backtest", fake_fetch)
    monkeypatch.setattr(
        backtest_store_module,
        "generate_mock_market_data",
        lambda *args, **kwargs: [
            {"date": "2026-01-01", "open": 10, "close": 10, "prev_close": 10},
        ],
    )
    monkeypatch.setattr(backtest_store_module, "generate_mock_signals", lambda *args, **kwargs: [])

    store = BacktestStore()
    result = await store.create_run(
        symbol="000001.SZ",
        start_date="2026-01-01",
        end_date="2026-01-01",
    )

    try:
        assert result["report"]["data_source"] == "MOCK_FALLBACK"
        assert "历史数据获取失败" in result["report"]["data_error"]
        assert result["report"]["data_points"] == 1
    finally:
        await store.delete_run(result["run_id"])


@pytest.mark.asyncio
async def test_backtest_store_can_use_signalops_lifecycle_signals(monkeypatch):
    symbol = f"BT{uuid4().hex[:6].upper()}"
    await signalops_store.upsert_from_run(
        {
            "runId": f"RUN_BT_SIG_{uuid4().hex[:8]}",
            "stockCode": symbol,
            "stockName": "Backtest Signal",
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
                "triggerConditions": ["breakout"],
                "invalidationConditions": ["close below base"],
                "reviewFields": [],
                "blockedReason": "",
            },
        }
    )

    async def fake_fetch(symbol: str, start_date: str, end_date: str):
        return [
            {"date": "2026-01-01", "open": 10, "close": 10, "prev_close": 10},
            {"date": "2026-01-02", "open": 11, "close": 12, "prev_close": 10},
            {"date": "2026-01-03", "open": 12, "close": 13, "prev_close": 12},
        ]

    monkeypatch.setattr(backtest_store_module, "fetch_historical_for_backtest", fake_fetch)
    store = BacktestStore()
    result = await store.create_run(
        symbol=symbol,
        start_date="2026-01-01",
        end_date="2026-01-03",
        parameters={"signal_source": "SIGNALOPS", "signal_date": "2026-01-01"},
    )

    try:
        assert result["report"]["signal_source"] == "SIGNALOPS"
        assert result["report"]["signal_source_count"] == 1
        assert result["report"]["total_signals"] == 1
        assert result["report"]["signal_log"][0]["source_node"] == "signalops_lifecycle"
        assert result["report"]["signal_log"][0]["metadata_json"]["source"] == "SIGNALOPS_LIFECYCLE_FALLBACK"
        assert result["report"]["signal_log"][0]["metadata_json"]["source_detail"] == "SIGNALOPS_LIFECYCLE_FALLBACK"
        assert result["report"]["signal_log"][0]["metadata_json"]["signalops_version"] == "AUTO_PAPER_V2"
    finally:
        await store.delete_run(result["run_id"])


@pytest.mark.asyncio
async def test_backtest_store_can_use_bottom_research_watch_signals():
    symbol = f"BTBOT{uuid4().hex[:6].upper()}"
    start_date = "2024-01-02"
    end_date = "2025-03-31"
    rows = _fake_bottom_research_market_rows(symbol, start_date, end_date)
    store = BacktestStore()
    result = await store.create_run(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        market_data=rows,
        market_data_source="TUSHARE",
        parameters={
            "signal_source": "BOTTOM_RESEARCH",
            "bottom_research_config": {"repair_probability_threshold": 0.20},
        },
    )

    try:
        assert result["report"]["signal_source"] == "MFE_MAE_PATH_RESEARCH"
        assert result["parameters"]["bottom_research_model_version"]
        assert result["parameters"]["mfe_mae_research_model_version"]
        assert "bottom_research_signal_hash" in result["parameters"]
        assert "mfe_mae_research_signal_hash" in result["parameters"]
        assert result["report"]["provenance"]["mfeMaeResearchVersion"]
        assert result["report"]["provenance"]["bottomResearchVersion"]
        assert all(item["source_node"] == "mfe_mae_path_research" for item in result["report"]["signal_log"])
        assert all(item["metadata_json"]["simulation_only"] is True for item in result["report"]["signal_log"])
        assert all(item["metadata_json"]["is_real_trade"] is False for item in result["report"]["signal_log"])
        assert all(item["direction"] == "WATCH" for item in result["report"]["signal_log"])
    finally:
        await store.delete_run(result["run_id"])


@pytest.mark.asyncio
async def test_signalops_backtest_prefers_auto_paper_v2_context(monkeypatch, tmp_path):
    monkeypatch.setattr(auto_module, "STORAGE_FILE", tmp_path / "auto_paper_trading.json")
    symbol = f"BT{uuid4().hex[:6].upper()}"
    state = auto_module.auto_paper_trading_store._load_state()
    state.update(
        {
            "symbol": symbol,
            "stock_name": "Auto Paper Sync",
            "commission_rate": 0.0001,
            "commission_min_fee": 5.0,
            "stamp_duty_rate": 0.0005,
            "initial_buy_signal": "user buy boundary",
            "final_sell_signal": "user sell boundary",
            "review_queue_state": {
                "items": [{"queue_item_id": "rq-sync", "symbol": symbol}],
                "counts": {"ready_for_review": 1},
                "simulation_only": True,
                "is_real_trade": False,
            },
            "cleaned_record_history": [
                {
                    "record_id": "REC_AUTO_BUY",
                    "signal_id": "SIG_AUTO_SYNC",
                    "signal_date": "2026-01-01",
                    "symbol": symbol,
                    "latest_action": "SIM_BUY",
                    "order_count": 1,
                    "sample_quality": "MEDIUM",
                    "evidence_refs": [{"source_type": "TEST", "source_id": "REC_AUTO_BUY"}],
                },
                {
                    "record_id": "REC_AUTO_SELL",
                    "signal_date": "2026-01-03",
                    "symbol": symbol,
                    "latest_action": "SIM_SELL",
                    "order_count": 1,
                    "sample_quality": "MEDIUM",
                },
            ],
            "compressed_observation_history": {
                "total_count": 1,
                "recent": [
                    {
                        "record_id": "REC_AUTO_HOLD",
                        "signal_date": "2026-01-02",
                        "symbol": symbol,
                        "latest_action": "SIM_HOLD",
                    }
                ],
            },
        }
    )
    auto_module.auto_paper_trading_store._save_state(state)

    async def fake_fetch(symbol: str, start_date: str, end_date: str):
        return [
            {"date": "2026-01-01", "open": 10, "close": 10, "prev_close": 10},
            {"date": "2026-01-02", "open": 10.2, "close": 10.3, "prev_close": 10},
            {"date": "2026-01-03", "open": 10.4, "close": 10.5, "prev_close": 10.3},
        ]

    monkeypatch.setattr(backtest_store_module, "fetch_historical_for_backtest", fake_fetch)
    store = BacktestStore()
    result = await store.create_run(
        symbol=symbol,
        start_date="2026-01-01",
        end_date="2026-01-03",
        parameters={"signal_source": "SIGNALOPS"},
    )

    try:
        report = result["report"]
        assert report["signal_source"] == "SIGNALOPS"
        assert report["signal_source_count"] == 3
        assert report["total_signals"] == 3
        assert report["total_trades"] == 2
        assert report["buy_signals"] == 1
        assert report["sell_signals"] == 1
        assert result["parameters"]["commission_bps"] == 1.0
        assert result["parameters"]["stamp_tax_bps"] == 5.0
        assert result["parameters"]["min_commission"] == 5.0
        assert result["parameters"]["t_plus_one"] is True

        signal_log = report["signal_log"]
        assert [item["metadata_json"]["record_id"] for item in signal_log] == [
            "REC_AUTO_BUY",
            "REC_AUTO_HOLD",
            "REC_AUTO_SELL",
        ]
        assert signal_log[0]["metadata_json"]["source"] == "SIGNALOPS_AUTO_PAPER"
        assert signal_log[0]["metadata_json"]["signalops_version"] == "AUTO_PAPER_V2"
        assert signal_log[1]["direction"] == "HOLD"
        assert signal_log[1]["signal_type"] == "SIGNALOPS_AUTO_SIM_HOLD"
        assert signal_log[1]["source_node"] == "signalops_auto_paper_cleaned_history"
        assert signal_log[1]["metadata_json"]["sample_quality"] == "SUPPORTING_ONLY"

        provenance = report["provenance"]
        assert provenance["signalOpsVersion"] == "AUTO_PAPER_V2"
        assert provenance["signalOpsSourceMode"] == "AUTO"
        assert provenance["simulationOnly"] is True
        assert provenance["isRealTrade"] is False
        assert provenance["cleanedRecordCount"] == 3
        assert provenance["tradeRecordCount"] == 2
        assert provenance["compressedObservationCount"] == 1
        assert provenance["reviewQueueSyncStatus"] == "SYNCED"
        assert provenance["executionRules"]["market"] == "A_SHARE_PAPER_SANDBOX"
        assert provenance["signalBoundary"]["initial_buy_signal"] == "user buy boundary"
        assert report["researchContract"]["signalOpsVersion"] == "AUTO_PAPER_V2"
    finally:
        await store.delete_run(result["run_id"])


def test_signalops_replay_caps_strong_sample_quality_to_medium():
    replay = backtest_store_module._build_signalops_replay_signals(
        records=[
            {
                "record_id": "REC_STRONG_TRAIN",
                "signal_date": "2026-05-11",
                "symbol": "603663",
                "latest_action": "SIM_BUY",
                "order_count": 1,
                "sample_quality": "STRONG",
            },
            {
                "record_id": "REC_HIGH_VALIDATION",
                "signal_date": "2026-05-18",
                "symbol": "603663",
                "latest_action": "SIM_SELL",
                "order_count": 1,
                "sample_quality": "HIGH",
            },
        ],
        symbol="603663",
        train_window={"start": "2026-05-11", "end": "2026-05-11"},
        validation_window={"start": "2026-05-18", "end": "2026-05-18"},
    )

    assert replay["sample_quality"] == "MEDIUM"
    assert replay["candidate_train"][0]["metadata_json"]["sample_quality"] == "MEDIUM"
    assert replay["candidate_validation"][0]["metadata_json"]["sample_quality"] == "MEDIUM"


@pytest.mark.asyncio
async def test_signalops_random_validation_job_syncs_micro_adjustment(monkeypatch, tmp_path):
    monkeypatch.setattr(auto_module, "STORAGE_FILE", tmp_path / "auto_paper_trading.json")

    async def fake_universe():
        return _fake_universe()

    async def fake_fetch(symbol: str, start_date: str, end_date: str):
        return _fake_random_market_rows(symbol, start_date, end_date)

    monkeypatch.setattr(backtest_store_module, "fetch_a_share_stock_universe", fake_universe)
    monkeypatch.setattr(backtest_store_module, "fetch_historical_for_backtest", fake_fetch)
    state = auto_module.auto_paper_trading_store._load_state()
    state.update({
        "buy_change_threshold_pct": 0.5,
        "close_change_threshold_pct": -2.0,
        "existing_position_ratio": 0.45,
        "watch_position_ratio": 0.15,
        "positive_position_ratio": 0.5,
        "breakout_position_ratio": 0.65,
    })
    auto_module.auto_paper_trading_store._save_state(state)

    store = BacktestStore()
    created = await store.create_signalops_random_validation_job({
        "mode": "VALIDATE_AND_FEEDBACK",
        "seed": 42,
        "history_years": 10,
        "min_window_days": 365,
        "max_window_days": 365,
        "min_trading_days": 200,
    })
    done = await _wait_random_job(store, created["jobId"])

    assert done["status"] == "COMPLETED"
    assert done["simulationOnly"] is True
    assert done["isRealTrade"] is False
    assert done["reviewQueueSyncStatus"] == "SYNCED"
    assert len(done["sampleWindows"]) == 2
    assert done["sampleWindows"][0]["symbol"] != done["sampleWindows"][1]["symbol"]
    assert all(item["windowDays"] >= 365 for item in done["sampleWindows"])
    assert all(item["tradingDays"] >= 200 for item in done["sampleWindows"])
    assert done["dataQuality"]["trusted"] is True
    assert done["evidenceLevel"] == "MEDIUM"
    deltas = done["appliedAdjustment"]["deltas"]
    assert abs(deltas.get("buy_change_threshold_pct", 0.0)) <= 0.05
    assert abs(deltas.get("existing_position_ratio", 0.0)) <= 0.02

    config = auto_module.auto_paper_trading_store.get_config()
    random_state = config.random_validation_state
    assert random_state["latest_job_id"] == created["jobId"]
    assert random_state["latest_summary"]["evidence_level"] == "MEDIUM"
    assert random_state["latest_summary"]["review_queue_sync_status"] == "SYNCED"
    assert random_state["simulation_only"] is True
    assert random_state["is_real_trade"] is False


@pytest.mark.asyncio
async def test_signalops_random_validation_requires_complete_trade_loop(monkeypatch, tmp_path):
    monkeypatch.setattr(auto_module, "STORAGE_FILE", tmp_path / "auto_paper_trading.json")

    async def fake_universe():
        return _fake_universe()

    async def fake_fetch(symbol: str, start_date: str, end_date: str):
        return _fake_buy_only_market_rows(symbol, start_date, end_date)

    monkeypatch.setattr(backtest_store_module, "fetch_a_share_stock_universe", fake_universe)
    monkeypatch.setattr(backtest_store_module, "fetch_historical_for_backtest", fake_fetch)

    state = auto_module.auto_paper_trading_store._load_state()
    state.update({
        "buy_change_threshold_pct": 0.5,
        "close_change_threshold_pct": -2.0,
        "existing_position_ratio": 0.45,
    })
    auto_module.auto_paper_trading_store._save_state(state)

    store = BacktestStore()
    created = await store.create_signalops_random_validation_job({
        "mode": "VALIDATE_AND_FEEDBACK",
        "seed": 42,
        "min_window_days": 365,
        "max_window_days": 365,
        "min_trading_days": 200,
    })
    done = await _wait_random_job(store, created["jobId"])

    assert done["status"] == "COMPLETED"
    assert done["evidenceLevel"] == "WEAK"
    assert done["dataQuality"]["completeTradeLoop"] is False
    assert "missing_complete_trade_loop" in done["rejectionReasons"]
    assert "weak_evidence" in done["rejectionReasons"]
    assert done["appliedAdjustment"]["shouldApply"] is False
    assert done["appliedAdjustment"]["applied"] is False
    assert done["reviewQueueSyncStatus"] == "SYNCED"

    config = auto_module.auto_paper_trading_store.get_config()
    random_state = config.random_validation_state
    assert random_state["latest_job_id"] == created["jobId"]
    assert random_state["latest_summary"]["evidence_level"] == "WEAK"
    assert random_state["latest_summary"]["review_queue_sync_status"] == "SYNCED"
    assert random_state["latest_summary"]["applied_adjustment"]["applied"] is False


@pytest.mark.asyncio
async def test_signalops_random_validation_validate_only_does_not_apply(monkeypatch, tmp_path):
    monkeypatch.setattr(auto_module, "STORAGE_FILE", tmp_path / "auto_paper_trading.json")

    async def fake_universe():
        return _fake_universe()

    async def fake_fetch(symbol: str, start_date: str, end_date: str):
        return _fake_random_market_rows(symbol, start_date, end_date)

    monkeypatch.setattr(backtest_store_module, "fetch_a_share_stock_universe", fake_universe)
    monkeypatch.setattr(backtest_store_module, "fetch_historical_for_backtest", fake_fetch)

    store = BacktestStore()
    created = await store.create_signalops_random_validation_job({
        "mode": "VALIDATE_ONLY",
        "seed": 42,
        "min_window_days": 365,
        "max_window_days": 365,
        "min_trading_days": 200,
    })
    done = await _wait_random_job(store, created["jobId"])

    assert done["status"] == "COMPLETED"
    assert done["appliedAdjustment"]["applied"] is False
    assert "validate_only_mode" in done["rejectionReasons"]
    random_state = auto_module.auto_paper_trading_store.get_config().random_validation_state
    assert random_state["latest_job_id"] == created["jobId"]
    assert random_state["latest_summary"]["applied_adjustment"]["applied"] is False


@pytest.mark.asyncio
async def test_signalops_random_validation_job_can_be_cancelled(monkeypatch, tmp_path):
    monkeypatch.setattr(auto_module, "STORAGE_FILE", tmp_path / "auto_paper_trading.json")

    async def fake_universe():
        return _fake_universe()

    async def slow_fetch(symbol: str, start_date: str, end_date: str):
        await asyncio.sleep(1)
        return _fake_random_market_rows(symbol, start_date, end_date)

    monkeypatch.setattr(backtest_store_module, "fetch_a_share_stock_universe", fake_universe)
    monkeypatch.setattr(backtest_store_module, "fetch_historical_for_backtest", slow_fetch)

    store = BacktestStore()
    created = await store.create_signalops_random_validation_job({"mode": "VALIDATE_AND_FEEDBACK", "seed": 7})
    cancelled = await store.cancel_signalops_random_validation_job(created["jobId"])
    await asyncio.sleep(0)
    done = await store.get_signalops_random_validation_job(created["jobId"])

    assert cancelled["status"] == "CANCELLED"
    assert done["status"] == "CANCELLED"


@pytest.mark.asyncio
async def test_signalops_auto_paper_cost_defaults_do_not_override_explicit_parameters(monkeypatch, tmp_path):
    monkeypatch.setattr(auto_module, "STORAGE_FILE", tmp_path / "auto_paper_trading.json")
    symbol = f"BT{uuid4().hex[:6].upper()}"
    state = auto_module.auto_paper_trading_store._load_state()
    state.update(
        {
            "symbol": symbol,
            "stock_name": "Cost Defaults",
            "commission_rate": 0.0002,
            "commission_min_fee": 6.0,
            "stamp_duty_rate": 0.001,
            "cleaned_record_history": [
                {
                    "record_id": "REC_COST_BUY",
                    "signal_date": "2026-02-02",
                    "symbol": symbol,
                    "latest_action": "SIM_BUY",
                    "order_count": 1,
                    "sample_quality": "MEDIUM",
                }
            ],
        }
    )
    auto_module.auto_paper_trading_store._save_state(state)

    async def fake_fetch(symbol: str, start_date: str, end_date: str):
        return [{"date": "2026-02-02", "open": 10, "close": 10, "prev_close": 10}]

    monkeypatch.setattr(backtest_store_module, "fetch_historical_for_backtest", fake_fetch)
    store = BacktestStore()
    default_run = await store.create_run(
        symbol=symbol,
        start_date="2026-02-02",
        end_date="2026-02-02",
        parameters={"signal_source": "SIGNALOPS"},
    )
    override_run = await store.create_run(
        symbol=symbol,
        start_date="2026-02-02",
        end_date="2026-02-02",
        parameters={
            "signal_source": "SIGNALOPS",
            "commission_bps": 7,
            "stamp_tax_bps": 8,
            "min_commission": 1,
            "t_plus_one": False,
        },
    )

    try:
        assert default_run["parameters"]["commission_bps"] == 2.0
        assert default_run["parameters"]["stamp_tax_bps"] == 10.0
        assert default_run["parameters"]["min_commission"] == 6.0
        assert default_run["parameters"]["t_plus_one"] is True
        assert default_run["report"]["tradingCost"]["commissionBps"] == 2.0
        assert default_run["report"]["tradingCost"]["stampTaxBps"] == 10.0

        assert override_run["parameters"]["commission_bps"] == 7
        assert override_run["parameters"]["stamp_tax_bps"] == 8
        assert override_run["parameters"]["min_commission"] == 1
        assert override_run["parameters"]["t_plus_one"] is False
        assert override_run["report"]["tradingCost"]["commissionBps"] == 7.0
        assert override_run["report"]["tradingCost"]["stampTaxBps"] == 8.0
        assert override_run["report"]["executionConstraints"]["tPlusOne"] is False
    finally:
        await store.delete_run(default_run["run_id"])
        await store.delete_run(override_run["run_id"])


@pytest.mark.asyncio
async def test_signalops_backtest_filters_by_source_run_id(monkeypatch):
    symbol = f"BT{uuid4().hex[:6].upper()}"
    await signalops_store.create_signal(
        {
            "symbol": symbol,
            "stock_name": "Old Signal",
            "source_run_id": "RUN_OLD_SIGNAL",
            "trigger_conditions": ["old"],
        }
    )
    await signalops_store.create_signal(
        {
            "symbol": symbol,
            "stock_name": "Target Signal",
            "source_run_id": "RUN_TARGET_SIGNAL",
            "trigger_conditions": ["target"],
        }
    )

    async def fake_fetch(symbol: str, start_date: str, end_date: str):
        return [
            {"date": "2026-01-01", "open": 10, "close": 10, "prev_close": 10},
            {"date": "2026-01-02", "open": 10, "close": 10.2, "prev_close": 10},
        ]

    monkeypatch.setattr(backtest_store_module, "fetch_historical_for_backtest", fake_fetch)
    store = BacktestStore()
    result = await store.create_run(
        symbol=symbol,
        start_date="2026-01-01",
        end_date="2026-01-02",
        parameters={
            "signal_source": "SIGNALOPS",
            "signal_date": "2026-01-01",
            "source_run_id": "RUN_TARGET_SIGNAL",
        },
    )

    try:
        assert result["report"]["signal_source"] == "SIGNALOPS"
        assert result["report"]["signal_source_count"] == 1
        assert result["report"]["signal_log"][0]["metadata_json"]["source_run_id"] == "RUN_TARGET_SIGNAL"
    finally:
        await store.delete_run(result["run_id"])


@pytest.mark.asyncio
async def test_signalops_signals_outside_backtest_range_are_not_injected(monkeypatch):
    symbol = f"BT{uuid4().hex[:6].upper()}"
    await signalops_store.upsert_from_run(
        {
            "runId": f"RUN_BT_OUT_{uuid4().hex[:8]}",
            "stockCode": symbol,
            "finalWriter": {"finalAction": "BUY"},
            "signalOps": {
                "signalStatus": "QUALIFIED",
                "riskPassed": True,
                "dvgPassed": True,
                "qiamPassed": True,
                "executionReachable": True,
                "triggerConditions": ["setup"],
                "invalidationConditions": ["invalid"],
            },
        }
    )

    async def fake_fetch(symbol: str, start_date: str, end_date: str):
        return [{"date": "2026-01-01", "open": 10, "close": 10, "prev_close": 10}]

    monkeypatch.setattr(backtest_store_module, "fetch_historical_for_backtest", fake_fetch)
    store = BacktestStore()
    result = await store.create_run(
        symbol=symbol,
        start_date="2026-01-01",
        end_date="2026-01-01",
        parameters={"signal_source": "SIGNALOPS"},
    )

    try:
        assert result["report"]["signal_source"] == "SIGNALOPS"
        assert result["report"]["signal_source_count"] == 0
        assert result["report"]["total_signals"] == 0
    finally:
        await store.delete_run(result["run_id"])


def test_backtest_uses_trading_days_and_keeps_last_valid_valuation():
    report = run_backtest(
        symbol="000001.SZ",
        stock_name="Ping An",
        start_date="2026-01-01",
        end_date="2026-01-04",
        initial_capital=100000,
        market_data=[
            {"date": "2026-01-01", "open": 10, "close": 10, "prev_close": 10},
            {"date": "2026-01-03", "open": 12, "close": 12, "prev_close": 10},
        ],
        signals=[{"timestamp": "2026-01-01", "direction": "BUY", "signal_type": "BUY", "strength": 1}],
        patch_params={"data_source": "CUSTOM"},
        data_source="CUSTOM",
    )

    assert [item["date"] for item in report.equity_curve] == ["2026-01-01", "2026-01-03"]
    assert report.final_capital > 100000


def test_backtest_executes_sell_when_t_plus_one_is_disabled():
    report = run_backtest(
        symbol="000001.SZ",
        stock_name="Ping An",
        start_date="2026-01-01",
        end_date="2026-01-01",
        initial_capital=100000,
        market_data=[{"date": "2026-01-01", "open": 10, "close": 10, "prev_close": 10}],
        signals=[
            {"timestamp": "2026-01-01", "direction": "BUY", "signal_type": "BUY", "strength": 1},
            {"timestamp": "2026-01-01", "direction": "SELL", "signal_type": "SELL", "strength": 1},
        ],
        patch_params={"t_plus_one": False},
        data_source="CUSTOM",
    )

    assert report.total_trades == 2
    assert report.sell_signals == 1
    assert report.t_plus_one_blocked == 0


def test_backtest_hold_signal_does_not_count_as_sell_or_price_limit_block():
    report = run_backtest(
        symbol="000001.SZ",
        stock_name="Ping An",
        start_date="2026-01-01",
        end_date="2026-01-01",
        initial_capital=100000,
        market_data=[{"date": "2026-01-01", "open": 20, "close": 20, "prev_close": 10}],
        signals=[{"timestamp": "2026-01-01", "direction": "HOLD", "signal_type": "SIGNALOPS_WATCH", "strength": 1}],
        data_source="CUSTOM",
    )

    assert report.total_signals == 1
    assert report.sell_signals == 0
    assert report.total_trades == 0
    assert report.price_limit_blocked == 0


def test_backtest_report_includes_research_grade_metadata_and_weak_sample_gate():
    report = run_backtest(
        symbol="000001.SZ",
        stock_name="Ping An",
        start_date="2026-01-01",
        end_date="2026-01-05",
        initial_capital=100000,
        market_data=[
            {"date": "2026-01-01", "open": 10, "close": 10, "prev_close": 10},
            {"date": "2026-01-02", "open": 10.2, "close": 10.4, "prev_close": 10},
            {"date": "2026-01-05", "open": 10.5, "close": 10.7, "prev_close": 10.4},
        ],
        signals=[{"timestamp": "2026-01-01", "direction": "BUY", "signal_type": "BUY", "strength": 1}],
        patch_params={"commission_bps": 3, "stamp_tax_bps": 5, "slippage_bps": 12},
        data_source="MOCK",
        signal_source="SIGNALOPS",
    )

    payload = report.model_dump(mode="json")

    assert payload["benchmark"]["type"] == "symbol_buy_hold"
    assert payload["sampleWindow"]["tradingDays"] == 3
    assert payload["sampleWindow"]["isSmallSample"] is True
    assert payload["tradingCost"]["commissionBps"] == 3
    assert payload["tradingCost"]["includedInCapital"] is True
    assert payload["slippage"]["slippageBps"] == 12
    assert payload["executionConstraints"]["tPlusOne"] is True
    assert payload["outOfSampleWindow"]["configured"] is False
    assert payload["statisticalConfidence"]["grade"] == "LOW"
    assert payload["evidenceStrength"]["grade"] == "LOW"
    assert payload["evidenceStrength"]["canSupportResearchVerdict"] is False
    assert payload["evidenceStrength"]["researchUsage"] == "supporting_only"
    assert payload["researchGradeScore"]["score"] < 60
    assert payload["researchGradeScore"]["band"] == "SUPPORTING_ONLY"
    assert payload["researchGradeScore"]["supportingOnly"] is True
    assert {item["key"] for item in payload["researchGradeScore"]["components"]} == {
        "sample_count",
        "out_of_sample",
        "walk_forward",
        "parameter_scan",
        "benchmark_excess",
        "max_drawdown",
        "execution_constraints",
        "statistical_confidence",
    }
    assert any("Market data source is MOCK" in item for item in payload["limitations"])
    assert any("No walk-forward validation is configured" in item for item in payload["limitations"])
    assert any("No parameter scan is configured" in item for item in payload["limitations"])
    assert any("Research grade score below 80" in item for item in payload["limitations"])
    assert payload["provenance"]["engineVersion"] == "research_metadata_v2"
    assert payload["provenance"]["dataPackageHash"]
    assert payload["provenance"]["marketDataHash"]
    assert payload["provenance"]["signalPackageHash"]
    assert payload["validationProtocol"]["parameterScan"]["enabled"] is False
    assert payload["validationProtocol"]["walkForward"]["enabled"] is False
    assert payload["validationProtocol"]["packageHashes"]["dataPackageHash"] == payload["provenance"]["dataPackageHash"]
    assert "parameter_scan" in payload["validationProtocol"]["researchGradeComponents"]


def test_backtest_high_quality_report_stays_review_gated_supporting_only():
    market_data = []
    benchmark_data = []
    current = datetime.fromisoformat("2026-01-01")
    close = 10.0
    benchmark_close = 10.0
    while len(market_data) < 70:
        if current.weekday() < 5:
            prev_close = close
            close = round(prev_close * 1.004, 4)
            benchmark_prev_close = benchmark_close
            benchmark_close = round(benchmark_prev_close * 1.0005, 4)
            market_data.append({
                "date": current.date().isoformat(),
                "open": round((prev_close + close) / 2, 4),
                "high": round(close * 1.01, 4),
                "low": round(prev_close * 0.99, 4),
                "close": close,
                "prev_close": prev_close,
            })
            benchmark_data.append({
                "date": current.date().isoformat(),
                "open": round((benchmark_prev_close + benchmark_close) / 2, 4),
                "high": round(benchmark_close * 1.001, 4),
                "low": round(benchmark_prev_close * 0.999, 4),
                "close": benchmark_close,
                "prev_close": benchmark_prev_close,
            })
        current += timedelta(days=1)
    signals = [
        {
            "timestamp": row["date"],
            "direction": "BUY" if index % 2 == 0 else "SELL",
            "signal_type": "BUY" if index % 2 == 0 else "SELL",
            "strength": 1,
        }
        for index, row in enumerate(market_data[:64])
    ]

    report = run_backtest(
        symbol="000001.SZ",
        stock_name="Ping An",
        start_date=market_data[0]["date"],
        end_date=market_data[-1]["date"],
        initial_capital=100000,
        market_data=market_data,
        signals=signals,
        patch_params={
            "benchmark_symbol": "000300.SH",
            "out_of_sample_start": market_data[55]["date"],
            "out_of_sample_end": market_data[-1]["date"],
            "walk_forward": {"enabled": True, "folds": 3},
            "parameter_scan": {"enabled": True, "grid": {"signal_min_strength": [0.3, 0.7]}},
        },
        data_source="CUSTOM",
        signal_source="SIGNALOPS",
        benchmark_market_data=benchmark_data,
        benchmark_data_source="CUSTOM",
    )

    payload = report.model_dump(mode="json")
    evidence = payload["evidenceStrength"]
    research_grade = payload["researchGradeScore"]

    assert payload["statisticalConfidence"]["grade"] == "HIGH"
    assert evidence["reportedGrade"] == "HIGH"
    assert evidence["grade"] == "MEDIUM"
    assert evidence["canSupportResearchVerdict"] is False
    assert evidence["weakSample"] is True
    assert evidence["researchUsage"] == "supporting_only"
    assert evidence["researchGradeBand"] == "REVIEWABLE"
    assert evidence["calculatedResearchGradeBand"] == "RESEARCH_GRADE"
    assert research_grade["score"] >= 80
    assert research_grade["band"] == "REVIEWABLE"
    assert research_grade["calculatedBand"] == "RESEARCH_GRADE"
    assert research_grade["canSupportResearchVerdict"] is False
    assert research_grade["supportingOnly"] is True
    assert any("review-gated supporting_only" in item for item in payload["limitations"])


@pytest.mark.asyncio
async def test_backtest_json_contract_carries_research_validation_fields():
    store = BacktestStore()
    patch_id = f"PATCH_BT_CONTRACT_{uuid4().hex[:8]}"
    market_data = [
        {"date": "2026-01-01", "open": 10, "close": 10, "prev_close": 10},
        {"date": "2026-01-02", "open": 10.2, "close": 10.4, "prev_close": 10},
        {"date": "2026-01-05", "open": 10.4, "close": 10.8, "prev_close": 10.4},
    ]
    signals = [
        {"timestamp": "2026-01-01", "direction": "BUY", "signal_type": "BUY", "strength": 1},
    ]
    parameters = {
        "benchmark_symbol": "000300.SH",
        "out_of_sample_start": "2026-01-05",
        "out_of_sample_end": "2026-01-05",
        "walk_forward": {"enabled": True, "folds": 2},
        "parameter_scan": {"enabled": True, "grid": {"signal_min_strength": [0.3, 0.5]}},
        "experiment_package_hash": "EXP_PACKAGE_HASH_001",
        "signal_source": "CUSTOM",
    }

    first = await store.create_run(
        symbol="000001.SZ",
        patch_id=patch_id,
        start_date="2026-01-01",
        end_date="2026-01-05",
        parameters=parameters,
        market_data=market_data,
        signals=signals,
    )
    second = await store.create_run(
        symbol="000001.SZ",
        patch_id=patch_id,
        start_date="2026-01-01",
        end_date="2026-01-05",
        parameters=parameters,
        market_data=market_data,
        signals=signals,
        force_new=True,
    )

    try:
        assert second["parameters"]["benchmark_symbol"] == "000300.SH"
        assert second["parameters"]["out_of_sample_start"] == "2026-01-05"
        assert second["parameters"]["out_of_sample_end"] == "2026-01-05"
        assert second["parameters"]["walk_forward"]["enabled"] is True
        assert second["parameters"]["parameter_scan"]["enabled"] is True
        assert second["parameters"]["experiment_package_hash"] == "EXP_PACKAGE_HASH_001"

        contract = second["report"]["researchContract"]
        assert contract["benchmark_symbol"] == "000300.SH"
        assert contract["out_of_sample_start"] == "2026-01-05"
        assert contract["out_of_sample_end"] == "2026-01-05"
        assert contract["out_of_sample_configured"] is True
        assert contract["walk_forward"] == {"enabled": True, "folds": 2}
        assert contract["walk_forward_configured"] is True
        assert contract["parameter_scan"]["enabled"] is True
        assert contract["parameter_scan_configured"] is True
        assert contract["experiment_package_hash"] == "EXP_PACKAGE_HASH_001"
        assert second["report"]["benchmark"]["symbol"] == "000300.SH"
        assert second["report"]["outOfSampleWindow"]["configured"] is True
        assert "researchGradeScore" in second["report"]
        assert second["report"]["researchGradeScore"]["components"][0]["key"] == "sample_count"
        assert second["report"]["validationProtocol"]["packageHashes"]["dataPackageHash"]
        assert second["report"]["provenance"]["dataPackageHash"] == second["report"]["validationProtocol"]["packageHashes"]["dataPackageHash"]

        comparison_contract = second["comparison"]["researchContract"]
        assert comparison_contract["candidate_experiment_package_hash"] == "EXP_PACKAGE_HASH_001"
        assert comparison_contract["benchmark_symbol"] == "000300.SH"
        assert comparison_contract["walk_forward"]["enabled"] is True
    finally:
        await store.delete_run(first["run_id"])
        await store.delete_run(second["run_id"])


@pytest.mark.asyncio
async def test_backtest_parameter_scan_creates_bounded_runs_and_best_summary():
    store = BacktestStore()
    market_data = [
        {"date": "2026-02-02", "open": 10, "close": 10.0, "prev_close": 10.0},
        {"date": "2026-02-03", "open": 10.4, "close": 10.6, "prev_close": 10.0},
        {"date": "2026-02-04", "open": 10.8, "close": 11.0, "prev_close": 10.6},
        {"date": "2026-02-05", "open": 11.0, "close": 11.2, "prev_close": 11.0},
    ]
    signals = [
        {"timestamp": "2026-02-02", "direction": "BUY", "signal_type": "BUY", "strength": 0.5},
        {"timestamp": "2026-02-03", "direction": "BUY", "signal_type": "BUY", "strength": 1.0},
        {"timestamp": "2026-02-05", "direction": "SELL", "signal_type": "SELL", "strength": 1.0},
    ]

    result = await store.create_parameter_scan(
        symbol="000001.SZ",
        start_date="2026-02-02",
        end_date="2026-02-05",
        base_parameters={
            "signal_source": "CUSTOM",
            "data_source": "CUSTOM",
            "walk_forward": {"enabled": True, "folds": 2},
            "out_of_sample_start": "2026-02-04",
            "out_of_sample_end": "2026-02-05",
        },
        parameter_grid={
            "signal_min_strength": [0.3, 0.9],
            "trade_quantity_pct": [0.1, 0.2],
        },
        max_combinations=3,
        ranking_metric="research_grade_score",
        market_data=market_data,
        market_data_source="CUSTOM",
        signals=signals,
        reuse_existing=False,
        force_new=True,
    )

    try:
        assert result["status"] == "COMPLETED"
        assert result["simulation_only"] is True
        assert result["is_real_trade"] is False
        assert len(result["combinations"]) == 3
        assert len(result["run_ids"]) == 3
        assert result["best_run_id"] in result["run_ids"]
        assert result["summary"]["totalCombinations"] == 3
        assert result["summary"]["rankingMetric"] == "research_grade_score"
        assert result["summary"]["supportingOnlyCount"] == 3
        assert result["summary"]["bestValidationProtocol"]["parameterScan"]["enabled"] is True
        assert all(run["parameters"]["parameter_scan"]["enabled"] is True for run in result["runs"])
        assert all(run["parameters"]["parameter_scan"]["rankingMetric"] == "research_grade_score" for run in result["runs"])
        assert all(run["parameters"]["simulation_only"] is True for run in result["runs"])
        assert all(run["parameters"]["is_real_trade"] is False for run in result["runs"])
        assert all(run["report"]["validationProtocol"]["parameterScan"]["enabled"] is True for run in result["runs"])
        assert all(run["report"]["researchContract"]["parameter_scan_configured"] is True for run in result["runs"])
        history = await store.list_parameter_scans(symbol="000001.SZ", limit=5)
        history_item = next(item for item in history if item["scan_id"] == result["scan_id"])
        assert history_item["status"] == "COMPLETED"
        assert set(history_item["run_ids"]) == set(result["run_ids"])
        assert history_item["best_run_id"] == result["best_run_id"]
        assert history_item["best_score"] == result["best_score"]
        assert history_item["trial_count"] == 3
        assert history_item["summary"]["totalCombinations"] == 3
        assert history_item["summary"]["bestValidationProtocol"]["parameterScan"]["enabled"] is True
        assert history_item["simulation_only"] is True
        assert history_item["is_real_trade"] is False
    finally:
        for run_id in result["run_ids"]:
            await store.delete_run(run_id)


@pytest.mark.asyncio
async def test_parameter_scan_history_keeps_legacy_primary_evidence_supporting_only():
    store = BacktestStore()
    market_data = [
        {"date": "2026-03-02", "open": 10, "close": 10.0, "prev_close": 10.0},
        {"date": "2026-03-03", "open": 10.2, "close": 10.5, "prev_close": 10.0},
        {"date": "2026-03-04", "open": 10.6, "close": 10.8, "prev_close": 10.5},
        {"date": "2026-03-05", "open": 10.9, "close": 11.0, "prev_close": 10.8},
    ]
    signals = [
        {"timestamp": "2026-03-02", "direction": "BUY", "signal_type": "BUY", "strength": 1.0},
        {"timestamp": "2026-03-05", "direction": "SELL", "signal_type": "SELL", "strength": 1.0},
    ]
    result = await store.create_parameter_scan(
        symbol="BTLEGACYSCAN",
        start_date="2026-03-02",
        end_date="2026-03-05",
        base_parameters={"signal_source": "CUSTOM", "data_source": "CUSTOM"},
        parameter_grid={"signal_min_strength": [0.5]},
        max_combinations=1,
        ranking_metric="research_grade_score",
        market_data=market_data,
        market_data_source="CUSTOM",
        signals=signals,
        reuse_existing=False,
        force_new=True,
    )

    try:
        polluted_run_id = result["run_ids"][0]
        async with AsyncSessionLocal() as db:
            record = (
                await db.execute(
                    select(BacktestRunDB).where(BacktestRunDB.run_id == polluted_run_id)
                )
            ).scalar_one()
            report = dict(record.report or {})
            report["evidenceStrength"] = {
                "grade": "HIGH",
                "canSupportResearchVerdict": True,
                "researchUsage": "primary_evidence",
                "weakSample": False,
            }
            report["researchGradeScore"] = {
                "score": 95,
                "band": "RESEARCH_GRADE",
                "canSupportResearchVerdict": True,
                "researchUsage": "primary_evidence",
                "supportingOnly": False,
            }
            record.report = report
            await db.commit()

        history = await store.list_parameter_scans(symbol="BTLEGACYSCAN", limit=5)
        history_item = next(item for item in history if item["scan_id"] == result["scan_id"])

        assert history_item["summary"]["supportingOnlyCount"] == len(result["run_ids"])
        assert history_item["summary"]["researchVerdictReadyCount"] == 0
        assert history_item["summary"]["scores"] == [
            {
                "run_id": polluted_run_id,
                "score": history_item["summary"]["scores"][0]["score"],
                "combination": {"signal_min_strength": 0.5},
                "combinationIndex": 1,
                "window": {
                    "start": "2026-03-02",
                    "end": "2026-03-05",
                    "label": "primary",
                },
                "windowIndex": 1,
                "researchUsage": "supporting_only",
                "canSupportResearchVerdict": False,
            }
        ]
    finally:
        for run_id in result["run_ids"]:
            await store.delete_run(run_id)


@pytest.mark.asyncio
async def test_backtest_parameter_scan_runs_each_combination_across_windows():
    store = BacktestStore()
    result = await store.create_parameter_scan(
        symbol="BTWINDOW01",
        start_date="2026-02-01",
        end_date="2026-02-10",
        base_parameters={
            "signal_source": "MOCK",
            "data_source": "MOCK",
            "walk_forward": {"enabled": True, "mode": "bounded_parameter_scan", "folds": 2},
        },
        parameter_grid={"signal_min_strength": [0.3, 0.6]},
        windows=[
            {"start": "2026-02-01", "end": "2026-02-05", "label": "train"},
            {"start": "2026-02-06", "end": "2026-02-10", "label": "validation"},
        ],
        max_combinations=2,
        ranking_metric="research_grade_score",
        reuse_existing=False,
        force_new=True,
    )

    try:
        assert result["status"] == "COMPLETED"
        assert result["window_count"] == 2
        assert result["trial_count"] == 4
        assert len(result["combinations"]) == 2
        assert len(result["run_ids"]) == 4
        assert result["best_run_id"] in result["run_ids"]
        assert result["summary"]["totalCombinations"] == 2
        assert result["summary"]["totalTrials"] == 4
        assert result["summary"]["windowCount"] == 2
        assert {run["start_date"] for run in result["runs"]} == {"2026-02-01", "2026-02-06"}
        assert {run["end_date"] for run in result["runs"]} == {"2026-02-05", "2026-02-10"}
        assert {run["parameters"]["parameter_scan"]["windowIndex"] for run in result["runs"]} == {1, 2}
        assert {run["parameters"]["parameter_scan"]["combinationIndex"] for run in result["runs"]} == {1, 2}
        assert all(run["parameters"]["parameter_scan"]["trialCount"] == 4 for run in result["runs"])
        assert all(run["parameters"]["parameter_scan"]["windowCount"] == 2 for run in result["runs"])
        assert all(run["parameters"]["simulation_only"] is True for run in result["runs"])
        assert all(run["parameters"]["is_real_trade"] is False for run in result["runs"])

        history = await store.list_parameter_scans(symbol="BTWINDOW01", limit=5)
        history_item = next(item for item in history if item["scan_id"] == result["scan_id"])
        assert history_item["window_count"] == 2
        assert history_item["trial_count"] == 4
        assert len(history_item["combinations"]) == 2
        assert len(history_item["windows"]) == 2
        assert history_item["summary"]["totalCombinations"] == 2
        assert history_item["summary"]["totalTrials"] == 4
        assert history_item["summary"]["windowCount"] == 2
        assert set(history_item["run_ids"]) == set(result["run_ids"])
        assert history_item["best_run_id"] == result["best_run_id"]
        assert history_item["simulation_only"] is True
        assert history_item["is_real_trade"] is False
    finally:
        for run_id in result["run_ids"]:
            await store.delete_run(run_id)


@pytest.mark.asyncio
async def test_backtest_parameter_scan_job_completes_and_retains_scan_result(monkeypatch, tmp_path):
    monkeypatch.setattr(backtest_store_module, "PARAMETER_SCAN_JOB_STORE_FILE", tmp_path / "backtest_parameter_scan_jobs.json")
    store = BacktestStore()
    created = await store.create_parameter_scan_job({
        "symbol": "BTSCANJOB01",
        "start_date": "2026-04-01",
        "end_date": "2026-04-08",
        "base_parameters": {
            "signal_source": "MOCK",
            "data_source": "MOCK",
            "walk_forward": {"enabled": True, "mode": "bounded_parameter_scan", "folds": 2},
        },
        "parameter_grid": {"signal_min_strength": [0.3, 0.6]},
        "windows": [
            {"start": "2026-04-01", "end": "2026-04-04", "label": "early"},
            {"start": "2026-04-05", "end": "2026-04-08", "label": "late"},
        ],
        "max_combinations": 2,
        "ranking_metric": "research_grade_score",
        "reuse_existing": False,
        "force_new": True,
    })
    done = await _wait_parameter_scan_job(store, created["jobId"])
    run_ids = list(done.get("runIds") or [])

    try:
        assert created["status"] == "QUEUED"
        assert created["queueMode"] == "LOCAL_DURABLE_JSON"
        assert created["durable"] is True
        assert created["recovered"] is False
        assert created["idempotencyKey"].startswith("bt-parameter-scan-")
        assert created["attemptCount"] in {0, 1}
        assert created["leaseStatus"] in {"UNCLAIMED", "LEASED", "RELEASED"}
        assert created["leaseSeconds"] >= 30
        assert done["status"] == "COMPLETED"
        assert done["simulationOnly"] is True
        assert done["isRealTrade"] is False
        assert done["queueMode"] == "LOCAL_DURABLE_JSON"
        assert done["durable"] is True
        assert done["idempotencyKey"] == created["idempotencyKey"]
        assert done["leaseStatus"] == "RELEASED"
        assert done["leaseOwner"].startswith("local-backtest-worker-")
        assert done["leaseId"].startswith(done["currentAttemptId"])
        assert done["leaseReleasedAt"]
        assert done["attemptCount"] == 1
        assert done["currentAttemptId"] == done["attempts"][-1]["attemptId"]
        assert done["lastAttemptStatus"] == "COMPLETED"
        assert len(done["attempts"]) == 1
        assert done["attempts"][0]["attemptNumber"] == 1
        assert done["attempts"][0]["status"] == "COMPLETED"
        assert done["attempts"][0]["idempotencyKey"] == done["idempotencyKey"]
        assert done["attempts"][0]["leaseStatus"] == "RELEASED"
        assert done["attempts"][0]["leaseOwner"] == done["leaseOwner"]
        assert done["attempts"][0]["leaseId"] == done["leaseId"]
        assert done["attempts"][0]["leaseReleasedAt"]
        assert done["scanId"].startswith("BTS_")
        assert done["totalCombinations"] == 2
        assert done["totalTrials"] == 4
        assert done["windowCount"] == 2
        assert len(run_ids) == 4
        assert done["bestRunId"] in run_ids
        assert done["scan"]["scan_id"] == done["scanId"]
        assert done["scan"]["summary"]["totalTrials"] == 4
        assert done["attempts"][0]["scanId"] == done["scanId"]
        assert set(done["attempts"][0]["runIds"]) == set(run_ids)
        assert done["attempts"][0]["bestRunId"] == done["bestRunId"]
        history = await store.list_parameter_scans(symbol="BTSCANJOB01", limit=5)
        history_item = next(item for item in history if item["scan_id"] == done["scanId"])
        assert history_item["trial_count"] == 4
        assert history_item["summary"]["totalTrials"] == 4
        persisted = json.loads((tmp_path / "backtest_parameter_scan_jobs.json").read_text(encoding="utf-8"))
        persisted_job = persisted["jobs"][created["jobId"]]
        assert persisted_job["status"] == "COMPLETED"
        assert persisted_job["queueMode"] == "LOCAL_DURABLE_JSON"
        assert persisted_job["durable"] is True
        assert persisted_job["idempotencyKey"] == done["idempotencyKey"]
        assert persisted_job["leaseStatus"] == "RELEASED"
        assert persisted_job["leaseId"] == done["leaseId"]
        assert persisted_job["attemptCount"] == 1
        assert persisted_job["attempts"][0]["status"] == "COMPLETED"
        assert persisted_job["attempts"][0]["leaseStatus"] == "RELEASED"
        assert "handoffStatus" not in persisted_job
        reloaded = await BacktestStore().get_parameter_scan_job(created["jobId"])
        assert reloaded is not None
        assert reloaded["status"] == "COMPLETED"
        assert reloaded["scanId"] == done["scanId"]
        assert reloaded["idempotencyKey"] == done["idempotencyKey"]
        assert reloaded["attemptCount"] == 1
        assert reloaded["lastAttemptStatus"] == "COMPLETED"
        assert reloaded["leaseStatus"] == "RELEASED"
        handoff_dir = tmp_path / "backtest-parameter-scan-handoff"
        monkeypatch.setenv("BACKTEST_PARAMETER_SCAN_HANDOFF_DIR", str(handoff_dir))
        handoff = await store.handoff_parameter_scan_job(created["jobId"])
        assert handoff is not None
        assert handoff["schema"] == "backtest_parameter_scan_job_handoff_v1"
        assert handoff["status"] == "HANDED_OFF"
        assert handoff["jobId"] == created["jobId"]
        assert handoff["scanId"] == done["scanId"]
        assert handoff["jobStatus"] == "COMPLETED"
        assert handoff["handoffDestination"] == "LOCAL_DEPLOYMENT_HANDOFF_DIR"
        assert handoff["handoffRequiresCompletedJob"] is True
        assert handoff["bundleChecksum"].startswith("bt-parameter-scan-handoff-")
        assert handoff["simulationOnly"] is True
        assert handoff["isRealTrade"] is False
        assert handoff["manifest"]["schema"] == "backtest_parameter_scan_job_handoff_manifest_v1"
        assert handoff["manifest"]["retentionPolicy"]["custody"] == "deployment_owned_after_handoff"
        bundle_path = handoff_dir / handoff["bundleFile"]
        manifest_path = handoff_dir / handoff["manifestFile"]
        assert bundle_path.exists()
        assert manifest_path.exists()
        persisted_bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        persisted_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert persisted_bundle["schema"] == "backtest_parameter_scan_job_handoff_bundle_v1"
        assert persisted_bundle["bundleChecksum"] == handoff["bundleChecksum"]
        assert persisted_bundle["job"]["jobId"] == created["jobId"]
        assert persisted_bundle["scan"]["scan_id"] == done["scanId"]
        assert persisted_manifest["handoffId"] == handoff["handoffId"]
        assert persisted_manifest["bundleChecksum"] == handoff["bundleChecksum"]
        assert persisted_manifest["simulationOnly"] is True
        assert persisted_manifest["isRealTrade"] is False
        sidecar_payload = {
            "schema": "backtest_parameter_scan_job_handoff_shipper_status_v1",
            "status": "DELIVERED",
            "reportedAt": "2026-06-02T00:00:00+00:00",
            "source": "unit-test-shipper",
            "provider": "object-store",
            "remoteDestination": "s3://unit-test/backtest?token=unit-secret",
            "objectKey": f"backtest/{handoff['handoffId']}.json",
            "retentionPolicyId": "backtest-parameter-scan-retention-30d",
            "retentionStatus": "RETAINED",
            "custodyStatus": "RETAINED",
            "searchIndex": "backtest-parameter-scan-artifacts",
            "searchIndexReady": True,
            "lastHandoffId": handoff["handoffId"],
            "lastBundleChecksum": handoff["bundleChecksum"],
            "lastJobId": created["jobId"],
            "lastScanId": done["scanId"],
            "message": "uploaded secret=unit-secret",
        }
        (handoff_dir / "shipper_status.json").write_text(json.dumps(sidecar_payload), encoding="utf-8")
        with_handoff_status = await store.get_parameter_scan_job(created["jobId"])
        handoff_status = with_handoff_status["handoffStatus"]
        assert handoff_status["schema"] == "backtest_parameter_scan_job_handoff_shipper_status_v1"
        assert handoff_status["status"] == "DELIVERED"
        assert handoff_status["provider"] == "object-store"
        assert handoff_status["retentionStatus"] == "RETAINED"
        assert handoff_status["custodyStatus"] == "RETAINED"
        assert handoff_status["searchIndexReady"] is True
        assert handoff_status["matchesLatestHandoff"] is True
        assert handoff_status["matchesJob"] is True
        assert "unit-secret" not in json.dumps(handoff_status)
    finally:
        for run_id in run_ids:
            await store.delete_run(run_id)


@pytest.mark.asyncio
async def test_backtest_parameter_scan_job_lease_blocks_duplicate_attempt_claim(monkeypatch, tmp_path):
    monkeypatch.setattr(backtest_store_module, "PARAMETER_SCAN_JOB_STORE_FILE", tmp_path / "backtest_parameter_scan_jobs.json")
    store = BacktestStore()
    job_id = f"BTSJOB_LEASE_{uuid4().hex[:8].upper()}"
    request = {
        "symbol": "BTLEASE01",
        "start_date": "2026-04-01",
        "end_date": "2026-04-08",
        "base_parameters": {"signal_source": "MOCK", "data_source": "MOCK"},
        "parameter_grid": {"signal_min_strength": [0.3]},
        "max_combinations": 1,
    }
    now = "2026-06-02T00:00:00+00:00"
    async with store._parameter_scan_jobs_lock:
        store._parameter_scan_jobs[job_id] = {
            "jobId": job_id,
            "status": "QUEUED",
            "progressStep": "QUEUED",
            "request": request,
            "scan": None,
            "scanId": "",
            "runIds": [],
            "bestRunId": None,
            "totalCombinations": 0,
            "totalTrials": 0,
            "windowCount": 0,
            "simulationOnly": True,
            "isRealTrade": False,
            "error": None,
            "createdAt": now,
            "updatedAt": now,
            "queueMode": "LOCAL_DURABLE_JSON",
            "storageSchema": "backtest_parameter_scan_jobs_v1",
            "durable": True,
            "recovered": False,
            "recoveredAt": None,
            "recoveryAttemptCount": 0,
            "idempotencyKey": "bt-parameter-scan-lease-test",
            "attemptCount": 0,
            "currentAttemptId": None,
            "lastAttemptStatus": None,
            "attempts": [],
            "leaseOwner": "",
            "leaseId": "",
            "leaseStatus": "UNCLAIMED",
            "leaseAcquiredAt": None,
            "leaseExpiresAt": None,
            "leaseReleasedAt": None,
            "leaseSeconds": 3600,
        }
        store._persist_parameter_scan_jobs_locked()

    first_attempt_id = await store._start_parameter_scan_job_attempt(job_id)
    second_attempt_id = await store._start_parameter_scan_job_attempt(job_id)
    async with store._parameter_scan_jobs_lock:
        running = json.loads(json.dumps(store._public_parameter_scan_job(store._parameter_scan_jobs[job_id])))

    assert first_attempt_id
    assert second_attempt_id is None
    assert running["status"] == "RUNNING"
    assert running["leaseStatus"] == "LEASED"
    assert running["leaseOwner"].startswith("local-backtest-worker-")
    assert running["leaseId"].startswith(first_attempt_id)
    assert running["leaseExpiresAt"]
    assert running["attemptCount"] == 1
    assert len(running["attempts"]) == 1
    assert running["attempts"][0]["status"] == "RUNNING"
    assert running["attempts"][0]["leaseStatus"] == "LEASED"
    assert running["attempts"][0]["leaseId"] == running["leaseId"]

    final = await store._finish_parameter_scan_job_attempt(
        job_id,
        first_attempt_id,
        status="COMPLETED",
        updates={
            "scan": {"scan_id": "BTS_LEASE_TEST", "summary": {"totalTrials": 0}},
            "scanId": "BTS_LEASE_TEST",
            "runIds": [],
            "bestRunId": None,
        },
    )
    assert final["status"] == "COMPLETED"
    assert final["leaseStatus"] == "RELEASED"
    assert final["leaseReleasedAt"]
    assert final["attemptCount"] == 1
    assert final["attempts"][0]["status"] == "COMPLETED"
    assert final["attempts"][0]["leaseStatus"] == "RELEASED"


@pytest.mark.asyncio
async def test_backtest_parameter_scan_job_recovers_persisted_running_job(monkeypatch, tmp_path):
    store_file = tmp_path / "backtest_parameter_scan_jobs.json"
    monkeypatch.setattr(backtest_store_module, "PARAMETER_SCAN_JOB_STORE_FILE", store_file)
    job_id = f"BTSJOB_RESTORE_{uuid4().hex[:8].upper()}"
    symbol = f"BTRESTORE{uuid4().hex[:6].upper()}"
    request = {
        "symbol": symbol,
        "start_date": "2026-05-01",
        "end_date": "2026-05-08",
        "base_parameters": {
            "signal_source": "MOCK",
            "data_source": "MOCK",
            "walk_forward": {"enabled": True, "mode": "bounded_parameter_scan", "folds": 2},
        },
        "parameter_grid": {"signal_min_strength": [0.4, 0.7]},
        "windows": [
            {"start": "2026-05-01", "end": "2026-05-04", "label": "early"},
            {"start": "2026-05-05", "end": "2026-05-08", "label": "late"},
        ],
        "max_combinations": 2,
        "ranking_metric": "research_grade_score",
        "reuse_existing": False,
        "force_new": True,
    }
    store_file.write_text(
        json.dumps(
            {
                "schema": "backtest_parameter_scan_jobs_v1",
                "queueMode": "LOCAL_DURABLE_JSON",
                "jobs": {
                    job_id: {
                        "jobId": job_id,
                        "status": "RUNNING",
                        "progressStep": "RUNNING",
                        "request": request,
                        "scan": None,
                        "scanId": "",
                        "runIds": [],
                        "bestRunId": None,
                        "totalCombinations": 0,
                        "totalTrials": 0,
                        "windowCount": 0,
                        "simulationOnly": True,
                        "isRealTrade": False,
                        "error": None,
                        "createdAt": "2026-05-01T00:00:00+00:00",
                        "updatedAt": "2026-05-01T00:00:01+00:00",
                        "queueMode": "LOCAL_DURABLE_JSON",
                        "storageSchema": "backtest_parameter_scan_jobs_v1",
                        "durable": True,
                        "recovered": False,
                        "recoveredAt": None,
                        "recoveryAttemptCount": 0,
                    }
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    store = BacktestStore()
    restored = await store.get_parameter_scan_job(job_id)
    restored_snapshot = json.loads(json.dumps(restored))
    done = await _wait_parameter_scan_job(store, job_id)
    run_ids = list(done.get("runIds") or [])

    try:
        assert restored_snapshot is not None
        assert restored_snapshot["status"] == "RECOVERING"
        assert restored_snapshot["progressStep"] == "RECOVERING"
        assert restored_snapshot["recovered"] is True
        assert restored_snapshot["recoveredAt"]
        assert restored_snapshot["recoveryAttemptCount"] == 1
        assert restored_snapshot["simulationOnly"] is True
        assert restored_snapshot["isRealTrade"] is False
        assert restored_snapshot["idempotencyKey"].startswith("bt-parameter-scan-")
        assert restored_snapshot["attemptCount"] == 1
        assert restored_snapshot["lastAttemptStatus"] == "INTERRUPTED"
        assert restored_snapshot["leaseStatus"] == "UNCLAIMED"
        assert restored_snapshot["attempts"][0]["status"] == "INTERRUPTED"
        assert restored_snapshot["attempts"][0]["leaseStatus"] == "EXPIRED"
        assert restored_snapshot["attempts"][0]["error"]
        assert done["status"] == "COMPLETED"
        assert done["queueMode"] == "LOCAL_DURABLE_JSON"
        assert done["durable"] is True
        assert done["recovered"] is True
        assert done["recoveryAttemptCount"] == 1
        assert done["idempotencyKey"] == restored_snapshot["idempotencyKey"]
        assert done["leaseStatus"] == "RELEASED"
        assert done["leaseOwner"].startswith("local-backtest-worker-")
        assert done["leaseId"].startswith(done["currentAttemptId"])
        assert done["attemptCount"] == 2
        assert done["lastAttemptStatus"] == "COMPLETED"
        assert [attempt["status"] for attempt in done["attempts"]] == ["INTERRUPTED", "COMPLETED"]
        assert [attempt["leaseStatus"] for attempt in done["attempts"]] == ["EXPIRED", "RELEASED"]
        assert done["attempts"][-1]["attemptNumber"] == 2
        assert done["attempts"][-1]["scanId"] == done["scanId"]
        assert done["scanId"].startswith("BTS_")
        assert done["totalCombinations"] == 2
        assert done["totalTrials"] == 4
        assert done["windowCount"] == 2
        assert done["simulationOnly"] is True
        assert done["isRealTrade"] is False
        assert len(run_ids) == 4
        persisted = json.loads(store_file.read_text(encoding="utf-8"))
        persisted_job = persisted["jobs"][job_id]
        assert persisted_job["status"] == "COMPLETED"
        assert persisted_job["recovered"] is True
        assert persisted_job["scanId"] == done["scanId"]
        assert persisted_job["idempotencyKey"] == done["idempotencyKey"]
        assert persisted_job["leaseStatus"] == "RELEASED"
        assert persisted_job["attemptCount"] == 2
        assert [attempt["status"] for attempt in persisted_job["attempts"]] == ["INTERRUPTED", "COMPLETED"]
        assert [attempt["leaseStatus"] for attempt in persisted_job["attempts"]] == ["EXPIRED", "RELEASED"]
    finally:
        for run_id in run_ids:
            await store.delete_run(run_id)


@pytest.mark.asyncio
async def test_backtest_experiment_package_exports_reproducible_hashes():
    store = BacktestStore()
    result = await store.create_run(
        symbol="000001.SZ",
        start_date="2026-02-02",
        end_date="2026-02-05",
        parameters={
            "signal_source": "MOCK",
            "data_source": "MOCK",
            "walk_forward": {"enabled": True, "folds": 2},
            "parameter_scan": {"enabled": True, "grid": {"signal_min_strength": [0.3]}},
            "simulation_only": True,
            "is_real_trade": False,
        },
        reuse_existing=False,
        force_new=True,
    )

    try:
        package = await store.get_experiment_package(result["run_id"])

        assert package is not None
        assert package["package_id"].startswith("BTEP_")
        assert package["run_id"] == result["run_id"]
        assert package["manifest"]["schemaVersion"] == "backtest_experiment_package_v1"
        assert package["manifest"]["runId"] == result["run_id"]
        assert package["manifest"]["hashes"]["dataPackageHash"] == result["report"]["provenance"]["dataPackageHash"]
        assert package["hashes"]["parameterHash"] == result["report"]["provenance"]["parameterHash"]
        assert package["reproducibility"]["validationProtocol"]["parameterScan"]["enabled"] is True
        assert package["reproducibility"]["parameters"]["simulation_only"] is True
        assert package["simulation_only"] is True
        assert package["is_real_trade"] is False
        assert package["run"]["run_id"] == result["run_id"]
        assert isinstance(package["trades"], list)
        assert isinstance(package["signals"], list)
    finally:
        await store.delete_run(result["run_id"])


@pytest.mark.asyncio
async def test_experiment_package_manifest_caps_legacy_primary_evidence():
    store = BacktestStore()
    result = await store.create_run(
        symbol="BTLEGACYPKG",
        start_date="2026-04-01",
        end_date="2026-04-05",
        parameters={
            "signal_source": "MOCK",
            "data_source": "MOCK",
            "simulation_only": True,
            "is_real_trade": False,
        },
        reuse_existing=False,
        force_new=True,
    )

    try:
        async with AsyncSessionLocal() as db:
            record = (
                await db.execute(
                    select(BacktestRunDB).where(BacktestRunDB.run_id == result["run_id"])
                )
            ).scalar_one()
            report = dict(record.report or {})
            report["evidenceStrength"] = {
                "grade": "HIGH",
                "canSupportResearchVerdict": True,
                "researchUsage": "primary_evidence",
                "weakSample": False,
            }
            report["researchGradeScore"] = {
                "score": 92,
                "band": "RESEARCH_GRADE",
                "canSupportResearchVerdict": True,
                "researchUsage": "primary_evidence",
                "supportingOnly": False,
            }
            record.report = report
            await db.commit()

        package = await store.get_experiment_package(result["run_id"])

        assert package is not None
        manifest = package["manifest"]
        assert manifest["researchUsage"] == "supporting_only"
        assert manifest["researchGradeScore"]["score"] == 92
        assert manifest["researchGradeScore"]["band"] == "REVIEWABLE"
        assert manifest["researchGradeScore"]["calculatedBand"] == "RESEARCH_GRADE"
        assert manifest["researchGradeScore"]["canSupportResearchVerdict"] is False
        assert manifest["researchGradeScore"]["researchUsage"] == "supporting_only"
        assert manifest["researchGradeScore"]["supportingOnly"] is True
        package_report = package["run"]["report"]
        assert package_report["evidenceStrength"]["grade"] == "MEDIUM"
        assert package_report["evidenceStrength"]["reportedGrade"] == "HIGH"
        assert package_report["evidenceStrength"]["canSupportResearchVerdict"] is False
        assert package_report["evidenceStrength"]["researchUsage"] == "supporting_only"
        assert package_report["evidenceStrength"]["weakSample"] is True
        assert package_report["researchGradeScore"]["band"] == "REVIEWABLE"
        assert package_report["researchGradeScore"]["calculatedBand"] == "RESEARCH_GRADE"
        assert package_report["researchGradeScore"]["canSupportResearchVerdict"] is False
        assert package_report["researchGradeScore"]["researchUsage"] == "supporting_only"
        assert package_report["researchGradeScore"]["supportingOnly"] is True
    finally:
        await store.delete_run(result["run_id"])


@pytest.mark.asyncio
async def test_get_and_list_runs_cap_legacy_primary_evidence_without_rewriting_record():
    store = BacktestStore()
    result = await store.create_run(
        symbol="BTLEGACYREAD",
        start_date="2026-04-06",
        end_date="2026-04-10",
        parameters={
            "signal_source": "MOCK",
            "data_source": "MOCK",
            "simulation_only": True,
            "is_real_trade": False,
        },
        reuse_existing=False,
        force_new=True,
    )

    try:
        async with AsyncSessionLocal() as db:
            record = (
                await db.execute(
                    select(BacktestRunDB).where(BacktestRunDB.run_id == result["run_id"])
                )
            ).scalar_one()
            report = dict(record.report or {})
            report["evidenceStrength"] = {
                "grade": "HIGH",
                "canSupportResearchVerdict": True,
                "researchUsage": "primary_evidence",
                "weakSample": False,
            }
            report["evidence_strength"] = {
                "grade": "HIGH",
                "can_support_research_verdict": True,
                "research_usage": "primary_evidence",
                "weak_sample": False,
            }
            report["researchGradeScore"] = {
                "score": 97,
                "band": "RESEARCH_GRADE",
                "canSupportResearchVerdict": True,
                "researchUsage": "primary_evidence",
                "supportingOnly": False,
            }
            report["research_grade_score"] = {
                "score": 98,
                "band": "RESEARCH_GRADE",
                "can_support_research_verdict": True,
                "research_usage": "primary_evidence",
                "supporting_only": False,
            }
            record.report = report
            await db.commit()

        detail = await store.get_run(result["run_id"])
        listed = await store.list_runs(symbol="BTLEGACYREAD", limit=5)
        listed_run = next(item for item in listed if item["run_id"] == result["run_id"])

        for outward_run in (detail, listed_run):
            report = outward_run["report"]
            assert report["evidenceStrength"]["grade"] == "MEDIUM"
            assert report["evidenceStrength"]["reportedGrade"] == "HIGH"
            assert report["evidenceStrength"]["canSupportResearchVerdict"] is False
            assert report["evidenceStrength"]["researchUsage"] == "supporting_only"
            assert report["evidenceStrength"]["weakSample"] is True
            assert report["evidence_strength"]["grade"] == "MEDIUM"
            assert report["evidence_strength"]["reported_grade"] == "HIGH"
            assert report["evidence_strength"]["can_support_research_verdict"] is False
            assert report["evidence_strength"]["research_usage"] == "supporting_only"
            assert report["evidence_strength"]["weak_sample"] is True
            assert report["researchGradeScore"]["score"] == 97
            assert report["researchGradeScore"]["band"] == "REVIEWABLE"
            assert report["researchGradeScore"]["calculatedBand"] == "RESEARCH_GRADE"
            assert report["researchGradeScore"]["canSupportResearchVerdict"] is False
            assert report["researchGradeScore"]["researchUsage"] == "supporting_only"
            assert report["researchGradeScore"]["supportingOnly"] is True
            assert report["research_grade_score"]["score"] == 98
            assert report["research_grade_score"]["band"] == "REVIEWABLE"
            assert report["research_grade_score"]["calculated_band"] == "RESEARCH_GRADE"
            assert report["research_grade_score"]["can_support_research_verdict"] is False
            assert report["research_grade_score"]["research_usage"] == "supporting_only"
            assert report["research_grade_score"]["supporting_only"] is True

        async with AsyncSessionLocal() as db:
            record = (
                await db.execute(
                    select(BacktestRunDB).where(BacktestRunDB.run_id == result["run_id"])
                )
            ).scalar_one()
            stored_report = dict(record.report or {})
            assert stored_report["evidenceStrength"]["grade"] == "HIGH"
            assert stored_report["evidenceStrength"]["researchUsage"] == "primary_evidence"
            assert stored_report["evidence_strength"]["grade"] == "HIGH"
            assert stored_report["evidence_strength"]["research_usage"] == "primary_evidence"
            assert stored_report["researchGradeScore"]["band"] == "RESEARCH_GRADE"
            assert stored_report["research_grade_score"]["band"] == "RESEARCH_GRADE"
    finally:
        await store.delete_run(result["run_id"])


@pytest.mark.asyncio
async def test_signalops_experiment_runner_requires_benchmark_before_review(monkeypatch, tmp_path):
    monkeypatch.setattr(auto_module, "STORAGE_FILE", tmp_path / "auto_paper_trading.json")
    market_data = [
        {"date": "2026-05-11", "open": 10, "close": 10, "prev_close": 10},
        {"date": "2026-05-12", "open": 10.2, "close": 10.4, "prev_close": 10},
        {"date": "2026-05-13", "open": 10.5, "close": 10.7, "prev_close": 10.4},
        {"date": "2026-05-14", "open": 10.8, "close": 11.0, "prev_close": 10.7},
        {"date": "2026-05-15", "open": 11.1, "close": 11.3, "prev_close": 11.0},
        {"date": "2026-05-26", "open": 11.4, "close": 11.7, "prev_close": 11.3},
        {"date": "2026-05-27", "open": 11.8, "close": 12.1, "prev_close": 11.7},
        {"date": "2026-05-28", "open": 12.2, "close": 12.5, "prev_close": 12.1},
    ]
    signals = [
        {"timestamp": date, "direction": "BUY", "signal_type": "BUY", "strength": 1}
        for date in ["2026-05-11", "2026-05-12", "2026-05-13", "2026-05-14", "2026-05-15"]
    ]
    validation_signals = [
        {"timestamp": date, "direction": "BUY", "signal_type": "BUY", "strength": 1}
        for date in ["2026-05-26", "2026-05-27", "2026-05-28"]
    ]
    benchmark_market_data = [
        {"date": "2026-05-11", "open": 3900, "close": 3910, "prev_close": 3900},
        {"date": "2026-05-12", "open": 3910, "close": 3920, "prev_close": 3910},
        {"date": "2026-05-13", "open": 3920, "close": 3930, "prev_close": 3920},
        {"date": "2026-05-14", "open": 3930, "close": 3940, "prev_close": 3930},
        {"date": "2026-05-15", "open": 3940, "close": 3950, "prev_close": 3940},
        {"date": "2026-05-26", "open": 3950, "close": 3960, "prev_close": 3950},
        {"date": "2026-05-27", "open": 3960, "close": 3970, "prev_close": 3960},
        {"date": "2026-05-28", "open": 3970, "close": 3980, "prev_close": 3970},
    ]
    store = BacktestStore()
    result = await store.create_signalops_experiment(
        symbol="603663",
        train_window={"start": "2026-05-11", "end": "2026-05-15"},
        validation_window={"start": "2026-05-26", "end": "2026-05-28"},
        baseline_config={"signal_source": "NONE"},
        candidate_config={"signal_source": "CUSTOM"},
        experiment_package_hash="EXP_SIGOPS_BENCH_PENDING",
        market_data=market_data,
        candidate_train_signals=signals,
        candidate_validation_signals=validation_signals,
        baseline_train_signals=[],
        baseline_validation_signals=[],
    )

    try:
        assert result["promotion_status"] == "BACKTEST_PENDING"
        assert result["benchmark_comparison"]["symbol"] == "000300.SH"
        assert result["benchmark_comparison"]["available"] is False
        assert "benchmark_unavailable" in result["walk_forward_validation"]["reasons"]
        candidate_run = await store.get_run(result["walk_forward_run_ids"]["candidate_validation"])
        assert candidate_run["report"]["benchmark_comparison"]["available"] is False
        assert candidate_run["report"]["research_evidence_package"]["experiment_package_hash"] == "EXP_SIGOPS_BENCH_PENDING"
    finally:
        for run_id in result["walk_forward_run_ids"].values():
            await store.delete_run(run_id)


@pytest.mark.asyncio
async def test_signalops_experiment_multiple_testing_penalty_blocks_ready_for_review(monkeypatch, tmp_path):
    monkeypatch.setattr(auto_module, "STORAGE_FILE", tmp_path / "auto_paper_trading.json")
    market_data = [
        {"date": "2026-05-11", "open": 10, "close": 10, "prev_close": 10},
        {"date": "2026-05-12", "open": 10.2, "close": 10.4, "prev_close": 10},
        {"date": "2026-05-13", "open": 10.5, "close": 10.7, "prev_close": 10.4},
        {"date": "2026-05-14", "open": 10.8, "close": 11.0, "prev_close": 10.7},
        {"date": "2026-05-15", "open": 11.1, "close": 11.3, "prev_close": 11.0},
        {"date": "2026-05-26", "open": 11.4, "close": 11.7, "prev_close": 11.3},
        {"date": "2026-05-27", "open": 11.8, "close": 12.1, "prev_close": 11.7},
        {"date": "2026-05-28", "open": 12.2, "close": 12.5, "prev_close": 12.1},
    ]
    benchmark_market_data = [
        {"date": row["date"], "open": 3900 + index * 10, "close": 3910 + index * 10, "prev_close": 3900 + index * 10}
        for index, row in enumerate(market_data)
    ]
    train_signals = [
        {"timestamp": date, "direction": "BUY", "signal_type": "BUY", "strength": 1}
        for date in ["2026-05-11", "2026-05-12", "2026-05-13", "2026-05-14", "2026-05-15"]
    ]
    validation_signals = [
        {"timestamp": date, "direction": "BUY", "signal_type": "BUY", "strength": 1}
        for date in ["2026-05-26", "2026-05-27", "2026-05-28"]
    ]
    store = BacktestStore()
    result = await store.create_signalops_experiment(
        symbol="603663",
        train_window={"start": "2026-05-11", "end": "2026-05-15"},
        validation_window={"start": "2026-05-26", "end": "2026-05-28"},
        baseline_config={"signal_source": "NONE"},
        candidate_config={"signal_source": "CUSTOM", "trial_count": 64},
        experiment_package_hash="EXP_SIGOPS_TRIAL_PENALTY",
        market_data=market_data,
        benchmark_market_data=benchmark_market_data,
        candidate_train_signals=train_signals,
        candidate_validation_signals=validation_signals,
        baseline_train_signals=[],
        baseline_validation_signals=[],
    )

    try:
        assert result["promotion_status"] == "RECOMMENDED_ONLY"
        assert result["walk_forward_validation"]["checks"]["multiple_testing_passed"] is False
        assert "multiple_testing_penalty_not_passed" in result["walk_forward_validation"]["reasons"]
    finally:
        for run_id in result["walk_forward_run_ids"].values():
            await store.delete_run(run_id)


@pytest.mark.asyncio
async def test_backtest_external_benchmark_does_not_reuse_symbol_market_data():
    store = BacktestStore()
    market_data = [
        {"date": "2026-05-18", "open": 10, "close": 10.5, "prev_close": 10},
        {"date": "2026-05-19", "open": 10.6, "close": 10.9, "prev_close": 10.5},
        {"date": "2026-05-20", "open": 11, "close": 11.2, "prev_close": 10.9},
    ]
    signals = [
        {"timestamp": "2026-05-18", "direction": "BUY", "signal_type": "BUY", "strength": 1},
    ]
    run = await store.create_run(
        symbol="603663",
        start_date="2026-05-18",
        end_date="2026-05-20",
        parameters={"benchmark_symbol": "000300.SH", "signal_source": "CUSTOM"},
        market_data=market_data,
        signals=signals,
    )
    try:
        benchmark = run["report"]["benchmark"]
        assert benchmark["symbol"] == "000300.SH"
        assert benchmark["available"] is False
        assert "Benchmark market data is unavailable" in benchmark["reason"]
    finally:
        await store.delete_run(run["run_id"])


@pytest.mark.asyncio
async def test_signalops_experiment_response_exposes_review_queue_sync_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(auto_module, "STORAGE_FILE", tmp_path / "auto_paper_trading.json")

    async def fail_sync(_result):
        raise RuntimeError("sync failed for test")

    monkeypatch.setattr(auto_module.auto_paper_trading_store, "record_backtest_experiment_result", fail_sync)
    market_data = [
        {"date": "2026-05-11", "open": 10, "close": 10, "prev_close": 10},
        {"date": "2026-05-12", "open": 10.2, "close": 10.4, "prev_close": 10},
        {"date": "2026-05-13", "open": 10.5, "close": 10.7, "prev_close": 10.4},
        {"date": "2026-05-18", "open": 10.8, "close": 11.0, "prev_close": 10.7},
    ]
    signals = [
        {"timestamp": "2026-05-11", "direction": "BUY", "signal_type": "BUY", "strength": 1},
    ]
    validation_signals = [
        {"timestamp": "2026-05-18", "direction": "BUY", "signal_type": "BUY", "strength": 1},
    ]
    store = BacktestStore()
    result = await store.create_signalops_experiment(
        symbol="603663",
        train_window={"start": "2026-05-11", "end": "2026-05-13"},
        validation_window={"start": "2026-05-18", "end": "2026-05-18"},
        baseline_config={"signal_source": "NONE"},
        candidate_config={"signal_source": "CUSTOM"},
        experiment_package_hash="EXP_SIGOPS_SYNC_FAIL",
        market_data=market_data,
        candidate_train_signals=signals,
        candidate_validation_signals=validation_signals,
        baseline_train_signals=[],
        baseline_validation_signals=[],
    )
    try:
        assert result["review_queue_sync_status"] == "FAILED"
        assert "review_queue_sync_failed" in result["warnings"]
        state = auto_module.auto_paper_trading_store.get_status()["experiment_validation_state"]
        assert state["attempts"]["EXP_SIGOPS_SYNC_FAIL"]["review_queue_sync_status"] == "FAILED"
    finally:
        for run_id in result["walk_forward_run_ids"].values():
            await store.delete_run(run_id)


@pytest.mark.asyncio
async def test_signalops_experiment_replay_uses_explicit_signal_date(monkeypatch, tmp_path):
    monkeypatch.setattr(auto_module, "STORAGE_FILE", tmp_path / "auto_paper_trading.json")
    state = auto_module.auto_paper_trading_store._load_state()
    state["cleaned_record_history"] = [
        {
            "record_id": "REC_TRAIN",
            "signal_date": "2026-05-11",
            "symbol": "603663",
            "latest_action": "SIM_BUY",
            "order_count": 1,
            "sample_quality": "MEDIUM",
            "evidence_refs": [{"source_type": "TEST", "source_id": "REC_TRAIN"}],
        },
        {
            "record_id": "REC_VALIDATION",
            "signal_date": "2026-05-18",
            "symbol": "603663",
            "latest_action": "SIM_BUY",
            "order_count": 1,
            "sample_quality": "MEDIUM",
            "evidence_refs": [{"source_type": "TEST", "source_id": "REC_VALIDATION"}],
        },
        {
            "record_id": "REC_OUTSIDE",
            "signal_date": "2026-04-30",
            "symbol": "603663",
            "latest_action": "SIM_BUY",
            "order_count": 1,
            "sample_quality": "MEDIUM",
            "evidence_refs": [{"source_type": "TEST", "source_id": "REC_OUTSIDE"}],
        },
        {
            "record_id": "REC_MISSING_DATE",
            "symbol": "603663",
            "latest_action": "SIM_BUY",
            "order_count": 1,
            "sample_quality": "MEDIUM",
            "evidence_refs": [{"source_type": "TEST", "source_id": "REC_MISSING_DATE"}],
        },
    ]
    auto_module.auto_paper_trading_store._save_state(state)
    market_data = [
        {"date": "2026-05-11", "open": 10, "close": 10.2, "prev_close": 10},
        {"date": "2026-05-12", "open": 10.3, "close": 10.4, "prev_close": 10.2},
        {"date": "2026-05-18", "open": 10.5, "close": 10.8, "prev_close": 10.4},
    ]
    benchmark_market_data = [
        {"date": "2026-05-11", "open": 3900, "close": 3910, "prev_close": 3900},
        {"date": "2026-05-12", "open": 3910, "close": 3920, "prev_close": 3910},
        {"date": "2026-05-18", "open": 3920, "close": 3930, "prev_close": 3920},
    ]
    store = BacktestStore()
    result = await store.create_signalops_experiment(
        symbol="603663",
        train_window={"start": "2026-05-11", "end": "2026-05-12"},
        validation_window={"start": "2026-05-18", "end": "2026-05-18"},
        baseline_config={"signal_source": "NONE"},
        candidate_config={},
        experiment_package_hash="EXP_SIGOPS_REPLAY_DATES",
        market_data=market_data,
        benchmark_market_data=benchmark_market_data,
    )
    try:
        counts = result["walk_forward_validation"]["replay_record_counts"]
        assert counts["train"] == 1
        assert counts["validation"] == 1
        assert counts["dropped"] == 2
        candidate_run = await store.get_run(result["walk_forward_run_ids"]["candidate_validation"])
        replay_record_ids = [
            signal["metadata_json"]["record_id"]
            for signal in candidate_run["report"]["signal_log"]
        ]
        assert replay_record_ids == ["REC_VALIDATION"]
    finally:
        for run_id in result["walk_forward_run_ids"].values():
            await store.delete_run(run_id)


@pytest.mark.asyncio
async def test_signalops_experiment_runner_promotes_only_when_sample_and_benchmark_pass(monkeypatch, tmp_path):
    monkeypatch.setattr(auto_module, "STORAGE_FILE", tmp_path / "auto_paper_trading.json")
    market_data = [
        {"date": "2026-05-11", "open": 10, "close": 10, "prev_close": 10},
        {"date": "2026-05-12", "open": 10.2, "close": 10.4, "prev_close": 10},
        {"date": "2026-05-13", "open": 10.5, "close": 10.7, "prev_close": 10.4},
        {"date": "2026-05-14", "open": 10.8, "close": 11.0, "prev_close": 10.7},
        {"date": "2026-05-15", "open": 11.1, "close": 11.3, "prev_close": 11.0},
        {"date": "2026-05-26", "open": 11.4, "close": 11.7, "prev_close": 11.3},
        {"date": "2026-05-27", "open": 11.8, "close": 12.1, "prev_close": 11.7},
        {"date": "2026-05-28", "open": 12.2, "close": 12.5, "prev_close": 12.1},
    ]
    train_signals = [
        {"timestamp": date, "direction": "BUY", "signal_type": "BUY", "strength": 1}
        for date in ["2026-05-11", "2026-05-12", "2026-05-13", "2026-05-14", "2026-05-15"]
    ]
    validation_signals = [
        {"timestamp": date, "direction": "BUY", "signal_type": "BUY", "strength": 1}
        for date in ["2026-05-26", "2026-05-27", "2026-05-28"]
    ]
    benchmark_market_data = [
        {"date": "2026-05-11", "open": 3900, "close": 3910, "prev_close": 3900},
        {"date": "2026-05-12", "open": 3910, "close": 3920, "prev_close": 3910},
        {"date": "2026-05-13", "open": 3920, "close": 3930, "prev_close": 3920},
        {"date": "2026-05-14", "open": 3930, "close": 3940, "prev_close": 3930},
        {"date": "2026-05-15", "open": 3940, "close": 3950, "prev_close": 3940},
        {"date": "2026-05-26", "open": 3950, "close": 3960, "prev_close": 3950},
        {"date": "2026-05-27", "open": 3960, "close": 3970, "prev_close": 3960},
        {"date": "2026-05-28", "open": 3970, "close": 3980, "prev_close": 3970},
    ]
    state = auto_module.auto_paper_trading_store._load_state()
    state["review_queue_state"] = {
        "version": 1,
        "items": [],
        "observations": [
            {
                "id": "rq-ready-sync",
                "queue_item_id": "rq-ready-sync",
                "experiment_id": "signalops-exp-ready-sync",
                "experiment_package_hash": "EXP_SIGOPS_READY",
                "symbol": "603663",
                "candidate_status": "BACKTEST_PENDING",
                "promotion_status": "BACKTEST_PENDING",
                "review_allowed": False,
                "candidate_config": {"buy_change_threshold_pct": 0.8},
                "baseline_config": {"buy_change_threshold_pct": 0.5},
                "simulation_only": True,
                "is_real_trade": False,
            }
        ],
        "counts": {"backtest_pending": 1},
        "simulation_only": True,
        "is_real_trade": False,
    }
    auto_module.auto_paper_trading_store._save_state(state)

    store = BacktestStore()
    result = await store.create_signalops_experiment(
        symbol="603663",
        train_window={"start": "2026-05-11", "end": "2026-05-15"},
        validation_window={"start": "2026-05-26", "end": "2026-05-28"},
        baseline_config={"signal_source": "NONE"},
        candidate_config={"signal_source": "CUSTOM"},
        experiment_package_hash="EXP_SIGOPS_READY",
        market_data=market_data,
        benchmark_market_data=benchmark_market_data,
        candidate_train_signals=train_signals,
        candidate_validation_signals=validation_signals,
        baseline_train_signals=[],
        baseline_validation_signals=[],
    )

    try:
        assert result["promotion_status"] == "READY_FOR_REVIEW"
        assert result["benchmark_comparison"]["symbol"] == "000300.SH"
        assert result["walk_forward_validation"]["status"] == "PASSED"
        assert result["walk_forward_validation"]["checks"]["benchmark_available"] is True
        assert result["walk_forward_validation"]["checks"]["purged_embargo_satisfied"] is True
        assert result["walk_forward_validation"]["checks"]["multiple_testing_passed"] is True
        assert result["walk_forward_validation"]["stability_validation_report"]["purged_walk_forward"]["embargo_days"] == 10
        assert "candidate_wilson_win_rate_lower_bound" in result["walk_forward_validation"]["validation_metrics"]
        assert result["research_evidence_package"]["stability_evidence_package"]["stability_validation_report"]["method"] == "signalops_strategy_stability_validation_v1"
        assert result["review_queue_sync_status"] == "SYNCED"
        assert result["walk_forward_validation"]["checks"]["train_trade_count_ready"] is True
        assert result["walk_forward_validation"]["checks"]["validation_trade_count_ready"] is True
        assert result["research_evidence_package"]["walk_forward_run_ids"]["candidate_validation"]
        auto_status = auto_module.auto_paper_trading_store.get_status()
        assert auto_status["review_queue_state"]["items"][0]["candidate_status"] == "READY_FOR_REVIEW"
        assert auto_status["review_queue_state"]["items"][0]["review_allowed"] is True
        assert auto_status["review_queue_state"]["items"][0]["stability_evidence_package"]["stability_validation_report"]["method"] == "signalops_strategy_stability_validation_v1"
        assert auto_status["experiment_validation_state"]["attempts"]["EXP_SIGOPS_READY"]["review_queue_sync_status"] == "SYNCED"
        repeated = await store.create_signalops_experiment(
            symbol="603663",
            train_window={"start": "2026-05-11", "end": "2026-05-15"},
            validation_window={"start": "2026-05-26", "end": "2026-05-28"},
            baseline_config={"signal_source": "NONE"},
            candidate_config={"signal_source": "CUSTOM"},
            experiment_package_hash="EXP_SIGOPS_READY",
            market_data=market_data,
            benchmark_market_data=benchmark_market_data,
            candidate_train_signals=train_signals,
            candidate_validation_signals=validation_signals,
            baseline_train_signals=[],
            baseline_validation_signals=[],
        )
        assert repeated["walk_forward_run_ids"] == result["walk_forward_run_ids"]
        assert repeated["candidate_run"]["parameters"]["dedupe_reused"] is True
        assert repeated["review_queue_sync_status"] == "SYNCED"
        repeated_status = auto_module.auto_paper_trading_store.get_status()
        assert repeated_status["experiment_validation_state"]["attempts"]["EXP_SIGOPS_READY"]["review_queue_sync_status"] == "SYNCED"
        candidate_run = await store.get_run(result["walk_forward_run_ids"]["candidate_validation"])
        assert candidate_run["comparison"]["walk_forward_validation"]["status"] == "PASSED"
        assert candidate_run["parameters"]["walk_forward_run_ids"]["candidate_validation"] == candidate_run["run_id"]
    finally:
        for run_id in result["walk_forward_run_ids"].values():
            await store.delete_run(run_id)
