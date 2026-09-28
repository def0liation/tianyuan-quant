from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta

from app.core.agent_executor import _mirror_quant_core_prior_outputs
from app.core.agent_framework import normalize_run_artifacts
from app.core.bottom_research import build_bottom_research_analysis


PATH_RISK_BUCKETS = [2.0, 5.0, 8.0, 10.0, 15.0, 20.0]
PATH_RISK_PROXY_FIELDS = {"mfeProxy", "maeProxy", "riskRewardProxy"}


def _assert_quant_core_legacy_marker(payload: dict) -> None:
    assert payload["legacyCompatibilityOnly"] is True
    assert payload["canonicalNode"] == "quant_core"
    assert payload["activeNode"] is False


def _market_data(*, high_risk: bool = False) -> dict:
    return {
        "marketSentiment": "BEARISH" if high_risk else "BULLISH",
        "volatilityIndex": 98 if high_risk else 35,
        "liquidityIndex": 5 if high_risk else 82,
        "institutionalActivity": "MEDIUM",
        "retailSentiment": "NEUTRAL",
        "sectorRotation": [],
        "macroIndicators": {},
        "regimeClassification": "高波动" if high_risk else "稳态",
    }


def _technical_payload(*, high_risk: bool = False) -> dict:
    payload = {
        "agent": "technical_kline_analyst",
        "status": "PASS",
        "technicalBias": "BULLISH",
        "confidence": 0.82,
        "dataQuality": {
            "provider": "tushare",
            "dataMode": "LIVE",
            "dailyCount": 88,
            "weeklyCount": 16,
            "monthlyCount": 6,
        },
        "volumePrice": {"status": "AVAILABLE", "volumeRatio5v20": 1.05},
        "chipAnalysis": {
            "status": "AVAILABLE",
            "source": "KLINE_VOLUME_PRICE_PROXY",
            "overheadVolumeRatio": 0.10,
            "supportVolumeRatio": 0.48,
            "costZone": {"volumeRatio": 0.36},
        },
    }
    if high_risk:
        payload.update(
            {
                "trend": {"close": 10.0, "ma20": 10.6, "return20d": -0.11, "return60d": -0.18},
                "volumePrice": {"status": "AVAILABLE", "volumeRatio5v20": 2.9},
                "supportResistance": {
                    "support20d": 9.96,
                    "support60d": 9.60,
                    "distanceToSupport20d": 0.004,
                    "distanceToResistance20d": 0.016,
                },
                "chipAnalysis": {
                    "status": "AVAILABLE",
                    "source": "KLINE_VOLUME_PRICE_PROXY",
                    "overheadVolumeRatio": 0.74,
                    "supportVolumeRatio": 0.02,
                    "costZone": {"volumeRatio": 0.04},
                },
            }
        )
    else:
        payload.update(
            {
                "trend": {"close": 10.0, "ma20": 9.7, "return20d": 0.06, "return60d": 0.10},
                "supportResistance": {
                    "support20d": 8.90,
                    "support60d": 8.40,
                    "distanceToSupport20d": 0.11,
                    "distanceToResistance20d": 0.08,
                },
            }
        )
    return payload


def _bottom_rows(count: int = 260) -> list[dict]:
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
        prev_close = rows[-1]["close"] if rows else price
        rows.append(
            {
                "date": ds,
                "open": round((prev_close + price) / 2, 4),
                "high": round(price * 1.018, 4),
                "low": round(price * 0.982, 4),
                "close": round(price, 4),
                "prev_close": round(prev_close, 4),
                "volume": 1_000_000 + index * 1000,
                "amount": 10_000_000 + index * 1000,
            }
        )
    return rows


def _run_payload(*, high_risk: bool = False) -> dict:
    qiam = {
        "finalBuySuitability": "FAVORABLE",
        "discountFactor": 1.0,
        "probabilityBandUp": 0.45 if high_risk else 0.58,
        "probabilityBandDown": 0.82 if high_risk else 0.12,
        "modelConfidenceFinal": 0.74,
        "probabilitySource": "RULE_DERIVED",
    }
    technical = _technical_payload(high_risk=high_risk)
    market = _market_data(high_risk=high_risk)
    return {
        "runId": "RUN_MFE_MAE_CHAIN_HIGH" if high_risk else "RUN_MFE_MAE_CHAIN_READY",
        "stockCode": "000001.SZ",
        "stockName": "Ping An",
        "taskType": "持仓复核",
        "runMode": "STANDARD_MODE",
        "quantEngine": {"mode": "HIGH_FREQ_SHORT"},
        "market": market,
        "marketTechnical": {
            "market": market,
            "technicalKline": technical,
            "alignment": "CONFLICT" if high_risk else "ALIGNED_BULLISH",
            "confidence": 0.78,
        },
        "technicalKline": technical,
        "mfeMaeResearch": build_bottom_research_analysis("000001.SZ", rows=_bottom_rows()),
        "bottomResearch": build_bottom_research_analysis("000001.SZ", rows=_bottom_rows()),
        "factorSlicing": {
            "mode": "AUTO",
            "factorStability": 0.72,
            "missingFactorData": [],
            "factorDataSource": "RULE_DERIVED",
        },
        "dvg": {"dataReliability": "HIGH", "criticalMissingData": []},
        "qiam": qiam,
        "quantCore": None,
        "execution": {"allowedActions": ["REVIEW_ONLY"], "forbiddenActions": ["BUY_CANDIDATE"]},
        "signalOps": {"signalStatus": "WATCH", "blockedReason": "manual_watch"},
        "finalAction": "WAIT",
        "finalContext": {"conclusion_derivation_inputs": {}},
        "nodes": [],
        "agentModuleResults": {},
    }


def test_mfe_mae_chain_ready_path_syncs_quant_core_and_final_context():
    run = _run_payload()

    normalize_run_artifacts(run)

    interpretation = run["quantCore"]["coreInterpretation"]
    path_risk = interpretation["pathRiskFilter"]
    visual = interpretation["visualDecisionPanel"]
    final_context_path_risk = run["finalContext"]["conclusion_derivation_inputs"]["core_interpretation"]["pathRiskFilter"]
    final_context_visual = run["finalContext"]["conclusion_derivation_inputs"]["core_interpretation"]["visualDecisionPanel"]
    assert path_risk == final_context_path_risk
    assert visual == final_context_visual
    assert path_risk["status"] == "READY"
    assert visual["status"] == "READY"
    assert visual["version"] == "quant_core_visual_decision_panel_v1"
    assert visual["directionProbability"]["actionBoundary"] == "READ_ONLY_NO_PERMISSION_CHANGE"
    assert visual["pathPayoffProxy"]["actionBoundary"] == "READ_ONLY_NO_PERMISSION_CHANGE"
    assert visual["probabilityOddsMatrix"]["zone"] in {"PRIORITY", "WATCH", "FILTER"}
    assert set(path_risk["mfeMaeProxy"]) == PATH_RISK_PROXY_FIELDS
    assert [item["drawdownPct"] for item in path_risk["riskCurve"]] == PATH_RISK_BUCKETS
    assert path_risk["actionBoundary"] == "READ_ONLY_NO_PERMISSION_CHANGE"
    assert path_risk["labelStatus"] == "UNLABELED_NOWCAST_PROXY_ONLY"
    assert path_risk["sampleQuality"]["dataMode"] == "LIVE"
    assert path_risk["sampleQuality"]["dailyCount"] == 88
    assert "no_future_mfe_mae_labels" in path_risk["leakagePolicy"]
    assert path_risk["simulation_only"] is True
    assert path_risk["is_real_trade"] is False
    assert path_risk["provenance"]["actionBoundary"] == "READ_ONLY_NO_PERMISSION_CHANGE"
    assert "technicalKline.dataQuality" in path_risk["provenance"]["inputFields"]
    assert interpretation["actionBoundary"] == "READ_ONLY_NO_PERMISSION_CHANGE"
    assert any(item["key"] == "pathRisk" for item in interpretation["dimensions"])
    mfe_context = run["finalContext"]["conclusion_derivation_inputs"]["mfe_mae_path_research"]
    assert mfe_context["mfe_favorable_probability"] == run["mfeMaeResearch"]["mfeFavorableProbability"]
    assert mfe_context["mae_breach_probability"] == run["mfeMaeResearch"]["maeBreachProbability"]
    assert mfe_context["risk_reward_proxy"] == run["mfeMaeResearch"]["riskRewardProxy"]


def test_mfe_mae_chain_high_risk_remains_read_only_for_actions_and_prior_outputs():
    run = _run_payload(high_risk=True)
    original_qiam = deepcopy(run["qiam"])
    original_execution = deepcopy(run["execution"])
    original_signal_ops = deepcopy(run["signalOps"])
    original_final_action = run["finalAction"]
    prior_outputs = {
        "qiam": {"finalBuySuitability": "STALE_QIAM"},
        "quant_engine": {"finalBuySuitability": "STALE_QUANT_ENGINE"},
    }

    normalize_run_artifacts(run)

    interpretation = run["quantCore"]["coreInterpretation"]
    path_risk = interpretation["pathRiskFilter"]
    visual = interpretation["visualDecisionPanel"]
    assert path_risk["riskPolicy"] in {"THROTTLE", "AVOID_NEW_BUY"}
    assert visual["riskGradient"]["riskPolicy"] == path_risk["riskPolicy"]
    assert visual["probabilityOddsMatrix"]["zone"] in {"WATCH", "FILTER"}
    assert "path_risk_gradient_high" in interpretation["riskFlags"]
    assert any(item["key"] == "path_risk_qiam_divergence" for item in interpretation["conflicts"])
    assert run["qiam"] == original_qiam
    assert run["execution"] == original_execution
    assert run["signalOps"] == original_signal_ops
    assert run["finalAction"] == original_final_action

    mirror_output = {
        **run["quantCore"],
        "qiam": dict(run["qiam"]),
        "legacyAgentOutputs": {
            "qiam": dict(run["qiam"]),
            "quant_engine": dict(run["qiam"]),
        },
    }
    _mirror_quant_core_prior_outputs(prior_outputs, mirror_output)
    for key in ("qiam", "quant_engine"):
        assert prior_outputs[key]["finalBuySuitability"] == "FAVORABLE"
        _assert_quant_core_legacy_marker(prior_outputs[key])
        assert "pathRiskFilter" not in prior_outputs[key]
        assert "coreInterpretation" not in prior_outputs[key]
        assert prior_outputs[key] != path_risk


def test_mfe_mae_bottom_research_evaluation_is_labeled_history_only():
    bottom = build_bottom_research_analysis("000001.SZ", rows=_bottom_rows())

    evaluation = bottom["modelDiagnostics"]["mfeMaePathRiskEvaluation"]
    assert evaluation["version"] == "mfe_mae_path_risk_research_v1"
    assert evaluation["status"] == "READY"
    assert evaluation["rankIcMode"] == "single_symbol_time_series_spearman"
    assert "unlabeled_nowcast_excluded" in evaluation["leakagePolicy"]
    assert evaluation["quantileCoverage"]["evaluatedTestCount"] == evaluation["sampleQuality"]["evaluatedTestCount"]
    assert evaluation["sampleQuality"]["latestExcludedTradeDate"] == bottom["provenance"]["lastTradeDate"]
    conditional = bottom["modelDiagnostics"]["conditionalQuantileEvaluation"]
    assert conditional["version"] == "mfe_mae_conditional_quantile_evaluation_v1"
    assert conditional["status"] == "READY"
    assert conditional["targetCoverage"]["evaluatedTestCount"] == conditional["sampleQuality"]["evaluatedTestCount"]
    assert conditional["sampleQuality"]["latestExcludedTradeDate"] == bottom["provenance"]["lastTradeDate"]
    assert conditional["targetCoverage"]["mfe"]["q80"]["coverage"] is not None
    assert conditional["targetCoverage"]["maeAbs"]["q90"]["coverage"] is not None
    assert conditional["actionBoundary"] == "RESEARCH_ONLY_NO_PERMISSION_CHANGE"
    assert conditional["simulation_only"] is True
    assert conditional["is_real_trade"] is False
    for fold in evaluation["folds"]:
        assert fold["trainEnd"] < fold["testStart"]
        assert fold["testEnd"] < bottom["provenance"]["lastTradeDate"]
    for fold in conditional["folds"]:
        assert fold["trainEnd"] < fold["testStart"]
        assert fold["testEnd"] < bottom["provenance"]["lastTradeDate"]
    assert evaluation["simulation_only"] is True
    assert evaluation["is_real_trade"] is False


def test_mfe_mae_market_profiles_cover_cross_market_constraints_and_missing_external_data():
    cases = [
        (
            "000001.SZ",
            "CN_A",
            {
                "currency": "CNY",
                "dailyPriceLimitPct": 0.10,
                "tPlusOne": True,
                "defaultLotSize": 100,
                "maeAvoidPct": 0.105,
                "requiredAdjustment": "daily_limit_board_aware_mae",
            },
        ),
        (
            "0700.HK",
            "HK",
            {
                "currency": "HKD",
                "dailyPriceLimitPct": None,
                "tPlusOne": False,
                "defaultLotSize": None,
                "maeAvoidPct": 0.14,
                "requiredAdjustment": "no_daily_price_limit_use_tail_multiplier",
            },
        ),
        (
            "SPY",
            "US_ETF",
            {
                "currency": "USD",
                "dailyPriceLimitPct": None,
                "tPlusOne": False,
                "defaultLotSize": 1,
                "maeAvoidPct": 0.10,
                "requiredAdjustment": "usd_proxy_tracking_error_review",
            },
        ),
        (
            "7203.T",
            "JP",
            {
                "currency": "JPY",
                "dailyPriceLimitPct": None,
                "tPlusOne": False,
                "defaultLotSize": 100,
                "maeAvoidPct": 0.11,
                "requiredAdjustment": "jp_market_recalibration_required",
            },
        ),
    ]

    for symbol, expected_market, expected in cases:
        bottom = build_bottom_research_analysis(symbol, rows=_bottom_rows())
        profile = bottom["marketProfile"]
        config_profile = bottom["config"]["marketProfile"]

        assert profile == config_profile
        assert profile["market"] == expected_market
        assert profile["currency"] == expected["currency"]
        assert profile["dailyPriceLimitPct"] == expected["dailyPriceLimitPct"]
        assert profile["tPlusOne"] is expected["tPlusOne"]
        assert profile["defaultLotSize"] == expected["defaultLotSize"]
        assert profile["sampleSegmentation"] == "market_specific_recalibration_required"
        assert profile["transferabilityStatus"].endswith("_RECALIBRATION_REQUIRED")
        assert expected["requiredAdjustment"] in profile["formulaAdjustments"]
        assert {"level2_order_flow", "real_order_book_depth", "full_chip_distribution", "valuation_gap"} <= set(profile["missingExternalData"])
        assert round(bottom["config"]["mae_avoid_pct"], 6) == expected["maeAvoidPct"]
        assert bottom["positionEnvelope"]["marketAdaptation"] == expected_market
        assert bottom["simulation_only"] is True
        assert bottom["is_real_trade"] is False
