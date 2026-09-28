from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta

from app.core import agent_executor
from app.core.bottom_research import (
    DEFAULT_BOTTOM_RESEARCH_CONFIG,
    build_bottom_research_analysis,
    build_bottom_research_signals,
    feature_vector_for_index,
    label_bottom_repair_event,
    log_euclidean_distance_spd,
    riemannian_distance_spd,
    shrink_covariance,
    tangent_space_vector,
)
from app.core.mfe_mae_path_risk_research import (
    build_mfe_mae_label_records,
    evaluate_mfe_mae_path_risk_walk_forward,
)
from app.modules.base_agent import AgentResult
from app.modules.bottom_research import BottomResearchAgent


def _synthetic_bottom_rows(count: int = 260) -> list[dict]:
    rows: list[dict] = []
    price = 100.0
    start = date(2024, 1, 2)
    for index in range(count):
        cycle = index % 64
        if cycle < 22:
            price *= 0.986
        elif cycle < 42:
            price *= 1.014
        else:
            price *= 0.998
        ds = (start + timedelta(days=index)).isoformat()
        prev = rows[-1]["close"] if rows else price
        rows.append(
            {
                "date": ds,
                "open": round((prev + price) / 2, 4),
                "high": round(price * 1.018, 4),
                "low": round(price * 0.982, 4),
                "close": round(price, 4),
                "prev_close": round(prev, 4),
                "volume": 1_000_000 + (index % 30) * 10_000,
                "amount": 10_000_000 + index * 1000,
            }
        )
    return rows


def _synthetic_path_risk_rows(count: int = 100) -> list[dict]:
    rows: list[dict] = []
    start = date(2024, 1, 2)
    for index in range(count):
        close = 100.0 + index * 0.50
        rows.append(
            {
                "tradeDate": (start + timedelta(days=index)).strftime("%Y%m%d"),
                "open": round(close - 0.12, 4),
                "high": round(close + 1.00 + index * 0.03, 4),
                "low": round(close - 1.00 - index * 0.04, 4),
                "close": round(close, 4),
                "volume": 1_000_000 + index * 5000,
            }
        )
    return rows


def test_riemannian_spd_metrics_are_stable_and_positive():
    samples = [
        [0.01, 0.02, 0.10, 0.00],
        [0.02, 0.03, 0.05, 0.01],
        [-0.01, 0.02, -0.02, -0.01],
        [0.00, 0.01, 0.00, 0.00],
    ]
    cov = shrink_covariance(samples)
    shifted = shrink_covariance([[value * 1.5 for value in row] for row in samples])

    assert riemannian_distance_spd(cov, cov) < 1e-6
    assert log_euclidean_distance_spd(cov, cov) < 1e-6
    assert riemannian_distance_spd(cov, shifted) > 0
    assert len(tangent_space_vector(shifted, cov)) >= 4
    assert all(cov[index][index] > 0 for index in range(len(cov)))


def test_mfe_mae_label_records_use_complete_windows_and_expected_values():
    rows = [
        {"date": "2024-01-01", "open": 99, "high": 101, "low": 98, "close": 100},
        {"date": "2024-01-02", "open": 101, "high": 110, "low": 95, "close": 105},
        {"date": "2024-01-03", "open": 106, "high": 120, "low": 90, "close": 110},
        {"date": "2024-01-04", "open": 111, "high": 118, "low": 92, "close": 112},
        {"date": "2024-01-05", "open": 113, "high": 119, "low": 93, "close": 115},
    ]

    records = build_mfe_mae_label_records(rows, horizon_days=2)

    assert len(records) == 3
    first = records[0]
    assert first["tradeDate"] == "2024-01-01"
    assert first["entryPrice"] == 100.0
    assert first["horizonDays"] == 2
    assert first["labelWindowStart"] == "2024-01-02"
    assert first["labelWindowEnd"] == "2024-01-03"
    assert abs(first["mfeLabel"] - 0.20) < 1e-12
    assert abs(first["maeLabel"] - -0.10) < 1e-12
    assert abs(first["maeAbsLabel"] - 0.10) < 1e-12
    assert abs(first["riskRewardLabel"] - (0.20 / (0.10 + 1e-6))) < 1e-12
    assert first["labelStatus"] == "LABELED_HISTORICAL"
    assert first["simulation_only"] is True
    assert first["is_real_trade"] is False
    assert "2024-01-04" not in {item["tradeDate"] for item in records}
    assert "2024-01-05" not in {item["tradeDate"] for item in records}


def test_mfe_mae_label_record_for_t_ignores_prices_after_label_window():
    rows = _synthetic_path_risk_rows(16)
    horizon = 3
    before = build_mfe_mae_label_records(rows, horizon_days=horizon)
    target = before[2]

    mutated = deepcopy(rows)
    outside_window_index = 2 + horizon + 1
    mutated[outside_window_index]["high"] *= 25
    mutated[outside_window_index]["low"] *= 0.05
    mutated[outside_window_index]["close"] *= 4
    after = build_mfe_mae_label_records(mutated, horizon_days=horizon)

    after_by_date = {record["tradeDate"]: record for record in after}
    assert after_by_date[target["tradeDate"]] == target


def test_mfe_mae_walk_forward_uses_train_before_test_and_excludes_nowcast():
    records = build_mfe_mae_label_records(_synthetic_path_risk_rows(95), horizon_days=5)
    nowcast = dict(records[-1])
    nowcast.update(
        {
            "tradeDate": "2099-01-01",
            "labelStatus": "UNLABELED_NOWCAST",
            "mfeLabel": 999.0,
            "maeLabel": -999.0,
            "maeAbsLabel": 999.0,
            "riskRewardLabel": -999.0,
        }
    )

    result = evaluate_mfe_mae_path_risk_walk_forward([*records, nowcast])

    assert result["status"] == "READY"
    assert result["sampleQuality"]["labeledCount"] == len(records)
    assert result["sampleQuality"]["excludedCount"] == 1
    assert result["sampleQuality"]["latestExcludedTradeDate"] == "2099-01-01"
    assert result["quantileCoverage"]["evaluatedTestCount"] == result["sampleQuality"]["evaluatedTestCount"]
    conditional = result["conditionalQuantileEvaluation"]
    assert conditional["status"] == "READY"
    assert conditional["sampleQuality"]["labeledCount"] == len(records)
    assert conditional["sampleQuality"]["excludedCount"] == 1
    assert conditional["sampleQuality"]["latestExcludedTradeDate"] == "2099-01-01"
    assert conditional["targetCoverage"]["evaluatedTestCount"] == conditional["sampleQuality"]["evaluatedTestCount"]
    assert conditional["labelStatus"] == "LABELED_HISTORICAL_ONLY_NOWCAST_EXCLUDED"
    assert conditional["actionBoundary"] == "RESEARCH_ONLY_NO_PERMISSION_CHANGE"
    assert conditional["simulation_only"] is True
    assert conditional["is_real_trade"] is False
    for fold in conditional["folds"]:
        assert fold["trainEnd"] < fold["testStart"]
        assert fold["testEnd"] < "2099-01-01"
    for fold in result["folds"]:
        assert fold["trainEnd"] < fold["testStart"]
        assert fold["testEnd"] < "2099-01-01"

    insufficient = evaluate_mfe_mae_path_risk_walk_forward(records[:10])
    assert insufficient["status"] == "SUPPORTING_ONLY"
    assert insufficient["folds"] == []
    assert insufficient["rankIc"] is None
    assert insufficient["conditionalQuantileEvaluation"]["status"] == "SUPPORTING_ONLY"
    assert insufficient["conditionalQuantileEvaluation"]["targetCoverage"]["evaluatedTestCount"] == 0


def test_mfe_mae_walk_forward_reports_rank_ic_and_quantile_coverage():
    records = build_mfe_mae_label_records(_synthetic_path_risk_rows(110), horizon_days=5)

    result = evaluate_mfe_mae_path_risk_walk_forward(records)

    assert result["status"] == "READY"
    assert result["rankIcMode"] == "single_symbol_time_series_spearman"
    assert "rankIc" in result
    assert result["rankIc"] is not None
    assert "q80" in result["quantileCoverage"]
    assert "q90" in result["quantileCoverage"]
    assert result["quantileCoverage"]["q80"]["coverage"] is not None
    assert result["quantileCoverage"]["q90"]["coverage"] is not None
    assert result["quantileCoverage"]["q80Coverage"] is not None
    assert result["quantileCoverage"]["q90Coverage"] is not None
    conditional = result["conditionalQuantileEvaluation"]
    assert conditional["version"] == "mfe_mae_conditional_quantile_evaluation_v1"
    assert conditional["status"] == "READY"
    assert conditional["method"] == "walk_forward_empirical_conditioned_quantile_v1"
    assert conditional["conditioning"]["quantileLevels"] == [0.5, 0.8, 0.9]
    assert conditional["targetCoverage"]["mfe"]["q50"]["coverage"] is not None
    assert conditional["targetCoverage"]["mfe"]["q80"]["coverage"] is not None
    assert conditional["targetCoverage"]["mfe"]["q90"]["coverage"] is not None
    assert conditional["targetCoverage"]["maeAbs"]["q80"]["coverage"] is not None
    assert conditional["targetCoverage"]["riskReward"]["q50"]["coverage"] is not None
    assert conditional["rankIc"]["mfeQ80ToMfe"] is not None
    assert conditional["rankIc"]["maeQ80ToMaeAbs"] is not None


def test_bottom_label_uses_future_window_but_features_do_not():
    rows = _synthetic_bottom_rows(150)
    cfg = dict(DEFAULT_BOTTOM_RESEARCH_CONFIG, horizon_days=20)
    index = 90
    before_features = feature_vector_for_index(rows, index, cfg)["features"]
    before_label = label_bottom_repair_event(rows, index, cfg)

    mutated = deepcopy(rows)
    for offset in range(index + 1, min(len(mutated), index + 21)):
        mutated[offset]["low"] *= 0.70
        mutated[offset]["high"] *= 0.75
        mutated[offset]["close"] *= 0.75

    after_features = feature_vector_for_index(mutated, index, cfg)["features"]
    after_label = label_bottom_repair_event(mutated, index, cfg)

    assert after_features == before_features
    assert after_label["breakdownLabel"] == 1
    assert after_label != before_label


def test_bottom_research_analysis_produces_research_only_probabilities():
    rows = _synthetic_bottom_rows()
    result = build_bottom_research_analysis("000001.SZ", rows=rows)
    current_prediction = result["currentPrediction"]
    history = result["probabilitySeries"]

    assert result["agent"] == "mfe_mae_path_research"
    assert result["legacyAgent"] == "bottom_research"
    assert result["researchType"] == "MFE_MAE_PATH_RESEARCH"
    assert result["marketProfile"]["market"] == "CN_A"
    assert result["mfeMaeFormulaConfig"]["labelFormula"]["mfeLabel"] == "max(high[t+1:t+H]) / close[t] - 1"
    assert result["status"] in {"PASS", "WARN"}
    assert result["actionBoundary"] == "RESEARCH_ONLY_NO_PERMISSION_CHANGE"
    assert result["labelStatus"] == "UNLABELED_NOWCAST"
    assert result["simulation_only"] is True
    assert result["is_real_trade"] is False
    assert result["sampleQuality"]["labeledCount"] > 0
    assert "UNLABELED_NOWCAST" in result["leakagePolicy"]
    assert result["positionEnvelope"]["policy"] == "REVIEW_ONLY_NOT_TRADE_INSTRUCTION"
    assert result["positionEnvelope"]["simulation_only"] is True
    assert result["positionEnvelope"]["is_real_trade"] is False
    assert "BUY" not in result.get("allowedActions", [])
    assert result["modelDiagnostics"]["leakagePolicy"].startswith("features_use_rows_ending_at_t")
    mfe_mae_evaluation = result["modelDiagnostics"]["mfeMaePathRiskEvaluation"]
    assert mfe_mae_evaluation["version"] == "mfe_mae_path_risk_research_v1"
    assert mfe_mae_evaluation["status"] == "READY"
    assert mfe_mae_evaluation["rankIcMode"] == "single_symbol_time_series_spearman"
    assert "unlabeled_nowcast_excluded" in mfe_mae_evaluation["leakagePolicy"]
    assert set(mfe_mae_evaluation["quantileCoverage"]) >= {"q80", "q90", "q80Coverage", "q90Coverage"}
    assert mfe_mae_evaluation["sampleQuality"]["latestExcludedTradeDate"] == result["provenance"]["lastTradeDate"]
    assert mfe_mae_evaluation["simulation_only"] is True
    assert mfe_mae_evaluation["is_real_trade"] is False
    conditional = result["modelDiagnostics"]["conditionalQuantileEvaluation"]
    assert conditional["version"] == "mfe_mae_conditional_quantile_evaluation_v1"
    assert conditional["status"] == "READY"
    assert conditional["sampleQuality"]["latestExcludedTradeDate"] == result["provenance"]["lastTradeDate"]
    assert conditional["targetCoverage"]["maeAbs"]["q80"]["coverage"] is not None
    assert conditional["actionBoundary"] == "RESEARCH_ONLY_NO_PERMISSION_CHANGE"
    assert conditional["labelStatus"] == "LABELED_HISTORICAL_ONLY_NOWCAST_EXCLUDED"
    assert conditional["simulation_only"] is True
    assert conditional["is_real_trade"] is False
    assert result["config"]["horizon_days_list"] == [5, 20, 60]
    assert [item["horizonDays"] for item in result["horizonForecasts"]] == [5, 20, 60]
    assert [item["horizonDays"] for item in result["horizonProbabilitySeries"]] == [5, 20, 60]
    horizon_paths = {item["horizonDays"]: item["series"] for item in result["horizonProbabilitySeries"]}
    for horizon_days in (5, 20):
        path = horizon_paths[horizon_days]
        assert any(point.get("repairProb") is not None for point in path[:-1])
        assert any(point.get("breakdownRisk") is not None for point in path[:-1])
        assert path[-1]["date"] == result["provenance"]["lastTradeDate"]
        assert path[-1]["predictionRepairProb"] is not None
        assert path[-1]["predictionBreakdownRisk"] is not None
        assert path[-1]["labelStatus"] == "UNLABELED_NOWCAST"
    assert result["trendSynthesis"]["primaryHorizonDays"] == 20
    assert result["qiamAdjustmentPreview"]["maxStep"] == 1
    assert result["qiamAdjustmentPreview"]["canCreateTradeAction"] is False
    primary = next(item for item in result["horizonForecasts"] if item["horizonDays"] == 20)
    assert primary["currentPrediction"]["tradeDate"] == result["provenance"]["lastTradeDate"]
    assert primary["sampleCount"] == result["modelDiagnostics"]["sampleCount"]
    assert current_prediction["tradeDate"] == result["provenance"]["lastTradeDate"]
    assert current_prediction["mfeFavorableProbability"] == round(result["mfeFavorableProbability"], 6)
    assert current_prediction["maeBreachProbability"] == round(result["maeBreachProbability"], 6)
    assert current_prediction["mfeProxy"] == round(result["mfeProxy"], 6)
    assert current_prediction["riskPolicy"] == result["riskPolicy"]
    assert current_prediction["labelStatus"] == "UNLABELED_NOWCAST"
    assert current_prediction["horizonDays"] == result["config"]["horizon_days"]
    assert current_prediction["simulation_only"] is True
    assert current_prediction["is_real_trade"] is False
    assert history[-1]["tradeDate"] == result["provenance"]["lastTradeDate"]
    assert history[-1]["labelStatus"] == "UNLABELED_NOWCAST"
    assert "actualForwardReturn" not in history[-1]
    assert "actualUpLabel" not in history[-1]
    assert "actualDownLabel" not in history[-1]
    assert history[-2]["tradeDate"] < result["provenance"]["lastTradeDate"]
    assert history[-2]["labelWindowEnd"] == result["provenance"]["lastTradeDate"]
    assert history[-2]["actualDirection"] in {"UP", "DOWN", "FLAT"}
    assert history[-2]["actualUpLabel"] in {0, 1}
    assert history[-2]["actualDownLabel"] in {0, 1}
    assert isinstance(history[-2]["actualForwardReturn"], float)


def test_mfe_mae_research_non_live_daily_payload_is_supporting_only():
    rows = _synthetic_bottom_rows()
    result = build_bottom_research_analysis(
        "000001.SZ",
        {
            "status": "READY",
            "provider": "fixture",
            "dataMode": "MOCK",
            "rows": rows,
        },
    )

    assert result["status"] == "SKIPPED"
    assert result["regimeState"] == "SUPPORTING_ONLY"
    assert "daily_kline_non_live_data" in result["missingData"]
    assert result["actionBoundary"] == "RESEARCH_ONLY_NO_PERMISSION_CHANGE"
    assert result["labelStatus"] == "UNLABELED_NOWCAST"
    assert result["simulation_only"] is True
    assert result["is_real_trade"] is False
    assert result["sampleQuality"]["evaluatedTestCount"] == 0
    assert result["sampleQuality"]["dailyCount"] == len(rows)
    assert result["sampleQuality"]["dataMode"] == "MOCK"
    assert "UNLABELED_NOWCAST" in result["leakagePolicy"]


def test_bottom_research_horizon_list_is_configurable_and_primary_compatible():
    rows = _synthetic_bottom_rows(320)
    result = build_bottom_research_analysis(
        "000001.SZ",
        rows=rows,
        config={"horizon_days": 10, "horizon_days_list": [5, 10, 30]},
    )

    assert result["config"]["horizon_days"] == 10
    assert [item["horizonDays"] for item in result["horizonForecasts"]] == [5, 10, 30]
    assert result["currentPrediction"]["horizonDays"] == 10
    primary = next(item for item in result["horizonForecasts"] if item["horizonDays"] == 10)
    assert result["bottomRepairProbability"] == primary["bottomRepairProbability"]
    assert result["breakdownRiskProbability"] == primary["breakdownRiskProbability"]
    assert result["trendSynthesis"]["primaryHorizonDays"] == 10


def test_bottom_research_horizon_list_preserves_primary_when_truncated():
    rows = _synthetic_bottom_rows(360)
    result = build_bottom_research_analysis(
        "000001.SZ",
        rows=rows,
        config={"horizon_days": 60, "horizon_days_list": [5, 10, 15, 20, 25, 30]},
    )

    horizons = [item["horizonDays"] for item in result["horizonForecasts"]]
    assert len(horizons) == 5
    assert 60 in horizons
    assert result["config"]["horizon_days"] == 60
    assert result["currentPrediction"]["horizonDays"] == 60
    primary = next(item for item in result["horizonForecasts"] if item["horizonDays"] == 60)
    assert result["bottomRepairProbability"] == primary["bottomRepairProbability"]
    assert result["breakdownRiskProbability"] == primary["breakdownRiskProbability"]
    assert result["trendSynthesis"]["primaryHorizonDays"] == 60


def test_mfe_mae_research_adapts_a_share_and_hk_market_profiles():
    rows = _synthetic_bottom_rows(260)

    a_share = build_bottom_research_analysis("000001.SZ", rows=rows)
    hk_share = build_bottom_research_analysis("00700.HK", rows=rows)
    us_etf = build_bottom_research_analysis("SPY", rows=rows)
    japan = build_bottom_research_analysis("7203.T", rows=rows)

    assert a_share["marketProfile"]["market"] == "CN_A"
    assert a_share["marketProfile"]["dailyPriceLimitPct"] == 0.10
    assert "daily_limit_board_aware_mae" in a_share["marketProfile"]["formulaAdjustments"]
    assert a_share["marketProfile"]["transferabilityStatus"] == "CN_A_RECALIBRATION_REQUIRED"
    assert hk_share["marketProfile"]["market"] == "HK"
    assert hk_share["marketProfile"]["dailyPriceLimitPct"] is None
    assert hk_share["marketProfile"]["downsideTailMultiplier"] > a_share["marketProfile"]["downsideTailMultiplier"]
    assert "no_daily_price_limit_use_tail_multiplier" in hk_share["marketProfile"]["formulaAdjustments"]
    assert hk_share["mfeMaeFormulaConfig"]["marketAdaptation"]["market"] == "HK"
    assert "level2_order_flow" in hk_share["marketProfile"]["missingExternalData"]
    assert us_etf["marketProfile"]["market"] == "US_ETF"
    assert us_etf["marketProfile"]["currency"] == "USD"
    assert "us_no_daily_price_limit_tail_review" in us_etf["marketProfile"]["formulaAdjustments"]
    assert us_etf["marketProfile"]["transferabilityStatus"] == "US_RECALIBRATION_REQUIRED"
    assert japan["marketProfile"]["market"] == "JP"
    assert japan["marketProfile"]["currency"] == "JPY"
    assert "jp_market_recalibration_required" in japan["marketProfile"]["formulaAdjustments"]
    assert japan["marketProfile"]["transferabilityStatus"] == "JP_RECALIBRATION_REQUIRED"


def test_bottom_research_agent_skips_without_tushare(monkeypatch):
    monkeypatch.setattr(
        "app.modules.bottom_research.get_kline_payload",
        lambda symbol, period, range_: {
            "status": "FAILED",
            "provider": "tushare",
            "dataMode": "UNAVAILABLE",
            "rows": [],
        },
    )

    result = BottomResearchAgent().process({"stockCode": "000001.SZ", "runMode": "STANDARD_MODE"}, {})

    assert result.status == "SKIPPED"
    assert result.final_decision_cap == "NO_DIRECT_TRADE_ACTION"
    assert "BUY" in result.blocked_actions
    assert result.data["regimeState"] == "SUPPORTING_ONLY"


def test_executor_writes_bottom_research_without_qiam_uplift():
    run = {"qiam": {"finalBuySuitability": "NEUTRAL"}}
    data = {
        "agent": "bottom_research",
        "status": "PASS",
        "bottomRepairProbability": 0.82,
        "breakdownRiskProbability": 0.12,
        "regimeState": "BOTTOM_REPAIR_ZONE",
    }

    agent_executor._apply_agent_module_output_to_run(
        run,
        "bottom_research",
        AgentResult(node="bottom_research", status="PASS", data=data),
    )

    assert run["bottomResearch"]["bottomRepairProbability"] == 0.82
    assert run["qiam"]["finalBuySuitability"] == "NEUTRAL"


def test_bottom_research_backtest_signals_are_watch_only():
    rows = _synthetic_bottom_rows()
    signals, metadata = build_bottom_research_signals("000001.SZ", rows)

    assert metadata["signal_source"] == "MFE_MAE_PATH_RESEARCH"
    assert metadata["legacy_signal_source"] == "BOTTOM_RESEARCH"
    assert metadata["simulation_only"] is True
    assert metadata["is_real_trade"] is False
    assert all(signal["source_node"] == "mfe_mae_path_research" for signal in signals)
    assert all(signal["direction"] == "WATCH" for signal in signals)
    assert all(signal["metadata_json"]["simulation_only"] is True for signal in signals)
