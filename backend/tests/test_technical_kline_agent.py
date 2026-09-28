import pytest

from app.api import routes_technical_kline
from app.core.case_library_store import case_library_store, review_tag_store
from app.core import technical_kline_governance_store
from app.core.technical_kline_agent import build_technical_kline_analysis, build_technical_signal_backtest
from app.modules.qiam import QiamAgent
from app.modules.scenario_engine import ScenarioEngineAgent
from app.modules.signalops import SignalopsAgent


def _payload(period: str, count: int):
    rows = []
    price = 10.0
    for index in range(count):
        price += 0.08 if index % 5 else -0.03
        rows.append(
            {
                "tradeDate": f"2025{1 + index // 28:02d}{1 + index % 28:02d}",
                "open": round(price - 0.05, 2),
                "high": round(price + 0.15, 2),
                "low": round(price - 0.2, 2),
                "close": round(price, 2),
                "volume": 1000 + index * 8,
            }
        )
    return {
        "period": period,
        "provider": "tushare",
        "status": "READY",
        "dataMode": "LIVE",
        "rows": rows,
    }


def _bearish_payload(period: str, count: int):
    rows = []
    price = 30.0
    for index in range(count):
        price -= 0.18 if index % 4 else 0.28
        rows.append(
            {
                "tradeDate": f"2025{1 + index // 28:02d}{1 + index % 28:02d}",
                "open": round(price + 0.08, 2),
                "high": round(price + 0.16, 2),
                "low": round(price - 0.18, 2),
                "close": round(price, 2),
                "volume": 1400 + index * 20,
            }
        )
    return {
        "period": period,
        "provider": "tushare",
        "status": "READY",
        "dataMode": "LIVE",
        "rows": rows,
    }


def _cyq_chip_payload(with_distribution: bool = True):
    latest_chips = (
        [
            {"tradeDate": "20260520", "price": 9.2, "percent": 0.12},
            {"tradeDate": "20260520", "price": 10.0, "percent": 0.24},
            {"tradeDate": "20260520", "price": 10.8, "percent": 0.28},
            {"tradeDate": "20260520", "price": 11.6, "percent": 0.18},
            {"tradeDate": "20260520", "price": 12.2, "percent": 0.18},
        ]
        if with_distribution
        else []
    )
    return {
        "status": "READY",
        "dataMode": "LIVE",
        "provider": "tushare",
        "source": "tushare_http",
        "latestTradeDate": "20260520",
        "recordCount": 6 if with_distribution else 1,
        "latestPerf": {
            "tradeDate": "20260520",
            "weightAvg": 10.8,
            "winnerRate": 0.42,
            "cost5Pct": 8.8,
            "cost15Pct": 9.4,
            "cost50Pct": 10.7,
            "cost85Pct": 11.8,
            "cost95Pct": 12.5,
        },
        "latestChips": latest_chips,
    }


def test_technical_kline_indicators_are_real_data_gated():
    analysis = build_technical_kline_analysis(
        "002846",
        {
            "daily": _payload("daily", 80),
            "weekly": _payload("weekly", 16),
            "monthly": _payload("monthly", 4),
        },
    )

    assert analysis["status"] in {"PASS", "WARN"}
    indicators = analysis["technicalIndicators"]
    assert indicators["macd"]["status"] == "AVAILABLE"
    assert indicators["macd"]["sampleCount"] == 80
    assert indicators["rsi"]["status"] == "AVAILABLE"
    assert indicators["kdj"]["status"] == "AVAILABLE"
    assert indicators["bollinger"]["status"] == "AVAILABLE"
    assert analysis["patterns"]["sampleCount"] == 80
    assert analysis["patterns"]["status"] in {"AVAILABLE", "NONE"}
    assert "mock" not in analysis["summaryForDownstream"].lower()
    assert "MA5=" in analysis["summaryForDownstream"]
    assert "MA10=" in analysis["summaryForDownstream"]
    assert "MA20=" in analysis["summaryForDownstream"]
    chip = analysis["chipAnalysis"]
    assert chip["status"] == "AVAILABLE"
    assert chip["source"] == "KLINE_VOLUME_PRICE_PROXY"
    assert chip["sourceKind"] == "I"
    assert chip["sampleCount"] == 60
    assert chip["averageCostProxy"] > 0
    assert chip["costZone"]["volumeRatio"] is not None
    assert "筹码" in analysis["summaryForDownstream"]
    assert "筹码解读" in analysis["summaryForDownstream"]
    assert chip["description"].rstrip("。") in analysis["summaryForDownstream"]
    assert "K 线成交量价格代理" in analysis["summaryForDownstream"]
    assert "主力控盘" not in analysis["summaryForDownstream"]


def test_technical_kline_prefers_tushare_cyq_chip_payload():
    analysis = build_technical_kline_analysis(
        "002846",
        {
            "daily": _payload("daily", 80),
            "weekly": _payload("weekly", 16),
            "monthly": _payload("monthly", 4),
        },
        chip_payload=_cyq_chip_payload(),
    )

    chip = analysis["chipAnalysis"]
    assert chip["status"] == "AVAILABLE"
    assert chip["source"] == "TUSHARE_CYQ_CHIPS"
    assert chip["sourceKind"] == "C"
    assert chip["tradeDate"] == "20260520"
    assert chip["winnerRate"] == 0.42
    assert chip["costPercentiles"]["cost50Pct"] == 10.7
    assert chip["distributionSample"]
    assert "真实 Tushare 筹码" in analysis["summaryForDownstream"]
    assert "K 线成交量价格代理" not in analysis["summaryForDownstream"]
    assert "主力控盘" not in analysis["summaryForDownstream"]
    assert "BUY" not in analysis["summaryForDownstream"]
    assert "SELL" not in analysis["summaryForDownstream"]


def test_technical_kline_uses_cyq_perf_when_distribution_is_missing():
    analysis = build_technical_kline_analysis(
        "002846",
        {
            "daily": _payload("daily", 80),
            "weekly": _payload("weekly", 16),
            "monthly": _payload("monthly", 4),
        },
        chip_payload=_cyq_chip_payload(with_distribution=False),
    )

    chip = analysis["chipAnalysis"]
    assert chip["source"] == "TUSHARE_CYQ_PERF"
    assert chip["sourceKind"] == "C"
    assert chip["winnerRate"] == 0.42
    assert chip["overheadVolumeRatio"] is None
    assert "真实 Tushare 筹码" in analysis["summaryForDownstream"]


def test_technical_kline_falls_back_to_kline_proxy_when_cyq_unavailable():
    analysis = build_technical_kline_analysis(
        "002846",
        {
            "daily": _payload("daily", 80),
            "weekly": _payload("weekly", 16),
            "monthly": _payload("monthly", 4),
        },
        chip_payload={"status": "FAILED", "error": "permission denied"},
    )

    chip = analysis["chipAnalysis"]
    assert chip["source"] == "KLINE_VOLUME_PRICE_PROXY"
    assert chip["sourceKind"] == "I"
    assert "K 线成交量价格代理" in analysis["summaryForDownstream"]


def test_technical_kline_indicators_skip_when_daily_data_is_insufficient():
    analysis = build_technical_kline_analysis(
        "002846",
        {
            "daily": _payload("daily", 12),
            "weekly": _payload("weekly", 3),
            "monthly": _payload("monthly", 1),
        },
    )

    assert analysis["status"] == "SKIPPED"
    assert analysis["technicalBias"] == "INSUFFICIENT_DATA"
    assert analysis["technicalIndicators"]["macd"]["status"] == "UNAVAILABLE"
    assert analysis["patterns"]["status"] == "UNAVAILABLE"
    assert analysis["chipAnalysis"]["status"] == "UNAVAILABLE"
    assert analysis["chipAnalysis"]["sourceKind"] == "U"
    assert analysis["caseClassification"] == "insufficient_data"


def test_technical_kline_prompt_governance_metadata_is_traceable():
    analysis = build_technical_kline_analysis(
        "002846",
        {
            "daily": _payload("daily", 80),
            "weekly": _payload("weekly", 16),
            "monthly": _payload("monthly", 4),
        },
        {"caseClassification": "misjudge"},
    )

    governance = analysis["promptGovernance"]
    config = analysis["analysisConfig"]
    assert governance["version"].startswith("technical-kline-prompt")
    assert len(governance["promptHash"]) == 16
    assert config["movingAverageWindows"] == {"short": 5, "medium": 10, "long": 20}
    assert config["riskThresholds"]["highVolumeRatio"] == 1.25
    assert len(config["configHash"]) == 16
    assert analysis["caseClassification"] == "misjudge"


@pytest.mark.asyncio
async def test_technical_kline_governance_route_exposes_prompt_and_config_metadata():
    payload = await routes_technical_kline.get_technical_kline_governance(
        ma_short=6,
        ma_medium=12,
        ma_long=24,
        volume_recent=None,
        volume_baseline=None,
        support_short=None,
        support_long=None,
        high_volume_ratio=1.5,
        near_support_distance=None,
        near_resistance_distance=None,
        case_classification="misjudge",
    )

    assert payload["promptGovernance"]["version"].startswith("technical-kline-prompt")
    assert payload["analysisConfig"]["movingAverageWindows"]["short"] == 6
    assert payload["analysisConfig"]["riskThresholds"]["highVolumeRatio"] == 1.5
    assert payload["caseClassification"]["selected"] == "misjudge"


@pytest.mark.asyncio
async def test_technical_kline_governance_can_be_saved_rolled_back_and_record_cases(monkeypatch, tmp_path):
    monkeypatch.setattr(technical_kline_governance_store, "STORAGE_FILE", tmp_path / "technical_kline_governance.json")
    saved = await routes_technical_kline.put_technical_kline_governance(
        routes_technical_kline.TechnicalKlineGovernanceUpdateRequest(
            ma_short=7,
            ma_medium=14,
            ma_long=28,
            high_volume_ratio=1.8,
            case_classification="misjudge",
            changed_by="test",
            change_reason="tighten technical kline governance",
        )
    )

    assert saved["analysisConfig"]["movingAverageWindows"]["short"] == 7
    assert saved["analysisConfig"]["riskThresholds"]["highVolumeRatio"] == 1.8
    assert saved["caseClassification"]["selected"] == "misjudge"
    assert saved["savedGovernance"]["updatedBy"] == "test"

    default_read = await routes_technical_kline.get_technical_kline_governance(
        ma_short=None,
        ma_medium=None,
        ma_long=None,
        volume_recent=None,
        volume_baseline=None,
        support_short=None,
        support_long=None,
        high_volume_ratio=None,
        near_support_distance=None,
        near_resistance_distance=None,
        case_classification=None,
    )
    assert default_read["analysisConfig"]["movingAverageWindows"]["short"] == 7

    case = await routes_technical_kline.record_technical_kline_case(
        routes_technical_kline.TechnicalKlineCaseRecordRequest(
            symbol="002846",
            classification="misjudge",
            note="MA signal failed in review.",
            run_id="RUN_TK_001",
            analysis_status="WARN",
            technical_bias="BULLISH",
            config_hash=saved["analysisConfig"]["configHash"],
            prompt_version=saved["promptGovernance"]["version"],
        )
    )
    assert case["classification"] == "misjudge"
    assert case["caseId"].startswith("TKCASE_")
    assert case["caseLibraryCaseId"].startswith("CASE_")
    assert case["caseLibraryStatus"] == "MIRRORED"

    mirrored_cases = await case_library_store.list_cases(symbol="002846")
    assert mirrored_cases[0]["case_id"] == case["caseLibraryCaseId"]
    assert mirrored_cases[0]["review_status"] == "REVIEWED"
    assert mirrored_cases[0]["conclusion_correct"] is False
    assert "technical_kline:misjudge" in mirrored_cases[0]["tags"]
    tags = await review_tag_store.list_tags(case_id=case["caseLibraryCaseId"])
    assert {tag["tag_type"] for tag in tags} >= {"MODULE", "CASE_CLASSIFICATION", "TECHNICAL_BIAS"}

    refreshed = await routes_technical_kline.get_technical_kline_governance(
        ma_short=None,
        ma_medium=None,
        ma_long=None,
        volume_recent=None,
        volume_baseline=None,
        support_short=None,
        support_long=None,
        high_volume_ratio=None,
        near_support_distance=None,
        near_resistance_distance=None,
        case_classification=None,
    )
    case_impact = refreshed["savedGovernance"]["caseImpact"]
    assert case_impact["policy"]["usage"] == "REVIEW_ONLY_PARAMETER_GOVERNANCE"
    assert case_impact["policy"]["tradeActionPolicy"] == "NO_DIRECT_TRADE_ACTION"
    assert case_impact["status"] == "LOW_SAMPLE"
    assert case_impact["totalCases"] == 1
    assert case_impact["classificationCounts"]["misjudge"] == 1
    assert case_impact["misjudgeRate"] == pytest.approx(1.0)
    assert case_impact["currentConfig"]["configHash"] == saved["analysisConfig"]["configHash"]
    assert case_impact["currentConfig"]["caseCount"] == 1
    assert case_impact["byConfigHash"][0]["configHash"] == saved["analysisConfig"]["configHash"]
    assert case_impact["representativeCaseSet"]["status"] == "LOW_COVERAGE"
    assert case_impact["representativeCaseSet"]["blocking"] is False
    assert case_impact["representativeCaseSet"]["boundary"] == "REVIEW_ONLY_NO_TRADE_ACTION"
    assert "valid" in case_impact["representativeCaseSet"]["missingClassifications"]
    assert "insufficient_data" in case_impact["representativeCaseSet"]["missingClassifications"]
    assert case_impact["parameterVersionReview"]["status"] == "LOW_CURRENT_CONFIG_SAMPLE"
    assert case_impact["parameterVersionReview"]["boundary"] == "REVIEW_ONLY_NO_TRADE_ACTION"
    assert case_impact["longWindowRegression"]["status"] == "LOW_COVERAGE"
    assert case_impact["longWindowRegression"]["action"] == "expand_long_window_review_history"
    assert case_impact["longWindowRegression"]["boundary"] == "REVIEW_ONLY_NO_TRADE_ACTION"
    assert case_impact["longWindowRegression"]["tradeActionPolicy"] == "NO_DIRECT_TRADE_ACTION"
    assert case_impact["longWindowRegression"]["blocking"] is False
    assert "LONG_WINDOW_REGRESSION_NOT_READY" in case_impact["warnings"]

    rolled_back = await routes_technical_kline.rollback_technical_kline_governance(
        routes_technical_kline.TechnicalKlineGovernanceRollbackRequest(
            changed_by="test",
            reason="restore defaults",
        )
    )
    assert rolled_back["analysisConfig"]["movingAverageWindows"]["short"] == 5
    assert rolled_back["caseClassification"]["selected"] == "rule_derived"
    assert rolled_back["savedGovernance"]["cases"][0]["caseId"] == case["caseId"]


def test_technical_kline_case_impact_reports_representative_set_and_version_delta(monkeypatch, tmp_path):
    monkeypatch.setattr(technical_kline_governance_store, "STORAGE_FILE", tmp_path / "technical_kline_governance.json")
    current_hash = "cfg-current-parameter-version"
    baseline_hash = "cfg-baseline-parameter-version"
    for symbol, classification, config_hash in [
        ("600010", "valid", baseline_hash),
        ("600011", "misjudge", baseline_hash),
        ("600012", "insufficient_data", baseline_hash),
        ("600020", "valid", current_hash),
        ("600021", "misjudge", current_hash),
        ("600022", "insufficient_data", current_hash),
        ("600023", "valid", current_hash),
        ("600024", "misjudge", current_hash),
    ]:
        technical_kline_governance_store.record_case(
            {
                "symbol": symbol,
                "classification": classification,
                "note": f"{classification} representative case",
                "run_id": f"RUN_{symbol}",
                "analysis_status": "WARN" if classification == "misjudge" else "PASS",
                "technical_bias": "BULLISH",
                "config_hash": config_hash,
                "prompt_version": "technical-kline-prompt-v1",
            }
        )

    state = technical_kline_governance_store.public_governance_state(
        current_config_hash=current_hash,
        current_prompt_version="technical-kline-prompt-v1",
    )
    impact = state["caseImpact"]

    assert len(state["cases"]) == 8
    assert impact["representativeCaseSet"]["status"] == "READY"
    assert impact["representativeCaseSet"]["reviewedCaseCount"] == 8
    assert impact["representativeCaseSet"]["uniqueSymbolCount"] == 8
    assert impact["representativeCaseSet"]["missingClassifications"] == []
    assert impact["parameterVersionReview"]["status"] == "READY_FOR_REVIEW"
    assert impact["parameterVersionReview"]["currentConfigCaseCount"] == 5
    assert impact["parameterVersionReview"]["baselineConfigCount"] == 1
    assert impact["parameterVersionReview"]["comparison"]["baselineConfigHash"] == baseline_hash
    assert impact["parameterVersionReview"]["comparison"]["misjudgeRateDelta"] == pytest.approx(0.0667)
    assert impact["parameterVersionReview"]["boundary"] == "REVIEW_ONLY_NO_TRADE_ACTION"
    assert impact["longWindowRegression"]["policyId"] == "technical_kline_long_window_regression_v1"
    assert impact["longWindowRegression"]["status"] == "READY_FOR_REVIEW"
    assert impact["longWindowRegression"]["action"] == "review_long_window_parameter_regression"
    assert impact["longWindowRegression"]["minimumReviewedCases"] == 8
    assert impact["longWindowRegression"]["reviewedCaseCount"] == 8
    assert impact["longWindowRegression"]["configVersionCount"] == 2
    assert impact["longWindowRegression"]["baselineConfigCount"] == 1
    assert impact["longWindowRegression"]["currentConfigCaseCount"] == 5
    assert impact["longWindowRegression"]["baselineCaseCount"] == 3
    assert impact["longWindowRegression"]["retainedCaseLimit"] == 200
    assert impact["longWindowRegression"]["windows"][0]["scope"] == "last_200_governance_cases"
    assert impact["longWindowRegression"]["boundary"] == "REVIEW_ONLY_NO_TRADE_ACTION"
    assert impact["longWindowRegression"]["tradeActionPolicy"] == "NO_DIRECT_TRADE_ACTION"
    assert impact["longWindowRegression"]["blocking"] is False
    assert impact["warnings"] == []


def test_bearish_technical_kline_only_discounts_qiam_probability():
    neutral_qiam = QiamAgent().process(
        {
            "qiam": {"rawBuySuitability": "FAVORABLE", "missingData": []},
            "dvg": {"qiamPermission": "ALLOW"},
            "marketData": {"quote": {"changePercent": 0}},
        },
        {},
    )
    bearish_technical = build_technical_kline_analysis(
        "002846",
        {
            "daily": _bearish_payload("daily", 80),
            "weekly": _bearish_payload("weekly", 16),
            "monthly": _payload("monthly", 4),
        },
    )
    bearish_qiam = QiamAgent().process(
        {
            "qiam": {"rawBuySuitability": "FAVORABLE", "missingData": []},
            "dvg": {"qiamPermission": "ALLOW"},
            "marketData": {"quote": {"changePercent": 0}},
        },
        {"technical_kline_analyst": bearish_technical},
    )

    assert bearish_technical["technicalBias"] == "BEARISH"
    assert bearish_qiam.data["technicalKlineConstraint"]["canIncreaseProbability"] is False
    assert bearish_qiam.data["technicalKlineConstraint"]["appliedFactor"] < 1
    assert any("technicalKline" in reason for reason in bearish_qiam.data["downgradeReasons"])
    assert bearish_qiam.data["finalBuySuitability"] != "FAVORABLE"
    assert bearish_qiam.data["probabilityBandUp"] <= neutral_qiam.data["probabilityBandUp"]


def test_bearish_technical_kline_adds_scenario_and_signalops_invalidations():
    bearish_technical = build_technical_kline_analysis(
        "002846",
        {
            "daily": _bearish_payload("daily", 80),
            "weekly": _bearish_payload("weekly", 16),
            "monthly": _payload("monthly", 4),
        },
    )

    scenario = ScenarioEngineAgent().process(
        {"dvg": {"scenarioPermission": "ALLOW", "criticalMissingData": []}},
        {"technical_kline_analyst": bearish_technical},
    )
    signalops = SignalopsAgent().process(
        {
            "dvg": {"allowedOutputLevel": "FULL"},
            "qiam": {"finalBuySuitability": "FAVORABLE"},
            "atrade": {"executionReachability": "REACHABLE"},
            "signalOps": {},
        },
        {"technical_kline_analyst": bearish_technical},
    )

    codes = {item["code"] for item in scenario.data["technicalInvalidationScenarios"]}
    assert "BREAK_MA20_OR_20D_SUPPORT" in codes
    assert signalops.data["simulationOnly"] is True
    assert signalops.data["isRealTrade"] is False
    assert signalops.data["signalStatus"] == "PAPER_TEST"
    assert signalops.data["technicalInvalidationConditions"]


def test_technical_kline_patterns_detect_gap_up():
    daily = _payload("daily", 80)
    previous_close = daily["rows"][-2]["close"]
    daily["rows"][-1].update(
        {
            "open": round(previous_close * 1.04, 2),
            "high": round(previous_close * 1.06, 2),
            "low": round(previous_close * 1.03, 2),
            "close": round(previous_close * 1.05, 2),
        }
    )

    analysis = build_technical_kline_analysis(
        "002846",
        {
            "daily": daily,
            "weekly": _payload("weekly", 16),
            "monthly": _payload("monthly", 4),
        },
    )

    codes = {item["code"] for item in analysis["patterns"]["items"]}
    assert "GAP_UP" in codes
    assert "形态" in analysis["summaryForDownstream"]


def test_technical_signal_backtest_validates_bias_tags_without_trade_actions():
    result = build_technical_signal_backtest(
        "002846",
        {
            "daily": _payload("daily", 80),
            "weekly": _payload("weekly", 16),
            "monthly": _payload("monthly", 4),
        },
        horizon_days=5,
    )

    assert result["status"] in {"PASS", "WARN"}
    assert result["sampleCount"] == 80
    assert result["totalObservations"] > 0
    assert result["evaluatedSignals"] >= 0
    assert set(result["byBias"]) == {"BULLISH", "BEARISH"}
    assert result["tradeActionPolicy"] == "NO_DIRECT_TRADE_ACTION"
    assert "BUY" not in result["summary"]
    assert "SELL" not in result["summary"]


def test_technical_signal_backtest_skips_when_daily_data_is_insufficient():
    result = build_technical_signal_backtest(
        "002846",
        {"daily": _payload("daily", 20)},
        horizon_days=10,
    )

    assert result["status"] == "SKIPPED"
    assert result["evaluatedSignals"] == 0
    assert result["hitRate"] is None
