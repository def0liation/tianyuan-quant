from __future__ import annotations

import copy
from typing import Any, Dict, List

from ..core.quant_engine_modes import quant_engine_profile_from_run
from .base_agent import AgentResult, BaseAgent
from .bottom_research import BottomResearchAgent
from .calculation_authority import CalculationAuthorityAgent
from .factor_engine import FactorEngineAgent
from .factor_slicing import FactorSlicingAgent
from .market_technical_analyst import MarketTechnicalAnalystAgent
from .qiam import QiamAgent
from .scenario_engine import ScenarioEngineAgent


CORE_INTERPRETATION_VERSION = "quant_core_interpretation_v1"
CORE_INTERPRETATION_ACTION_BOUNDARY = "READ_ONLY_NO_PERMISSION_CHANGE"
PATH_RISK_FILTER_VERSION = "mfe_mae_path_risk_filter_v1"
PATH_RISK_FILTER_METHOD = "daily_proxy_no_future_labels_v1"
PATH_RISK_HORIZON_DAYS = 20
PATH_RISK_DRAWDOWN_BUCKETS = [0.02, 0.05, 0.08, 0.10, 0.15, 0.20]
FUTURE_TREND_PROBABILITY_VERSION = "quant_core_future_trend_probability_v1"
FUTURE_TREND_CALIBRATION_METHOD = "rolling_reliability_bins_v1"
FUTURE_TREND_MIN_CALIBRATION_SAMPLES = 30
FUTURE_TREND_MAX_ADJUSTMENT = 0.10
VISUAL_DECISION_PANEL_VERSION = "quant_core_visual_decision_panel_v1"

CORE_INTERPRETATION_WEIGHTS: Dict[str, Dict[str, float]] = {
    "HIGH_FREQ_SHORT": {
        "qiam": 0.30,
        "technical": 0.30,
        "mfeMaeResearch": 0.15,
        "factor": 0.15,
        "marketScenario": 0.10,
    },
    "LOW_FREQ_MID_LONG": {
        "mfeMaeResearch": 0.30,
        "qiam": 0.25,
        "technical": 0.20,
        "factor": 0.15,
        "marketScenario": 0.10,
    },
}


class QuantCoreAgent(BaseAgent):
    node = "quant_core"
    name = "量化核心"
    stage = "analysis"
    rule_engine_only = True

    def process(self, run_context: Dict[str, Any], prior_outputs: Dict[str, Any]) -> AgentResult:
        run_mode = str(run_context.get("runMode") or "STANDARD_MODE").upper()
        context = copy.deepcopy(run_context)
        outputs = dict(prior_outputs)
        legacy_results: Dict[str, Dict[str, Any]] = {}
        legacy_agent_outputs: Dict[str, Dict[str, Any]] = {}

        market_result = MarketTechnicalAnalystAgent().process(context, outputs)
        _record_legacy_result(legacy_results, legacy_agent_outputs, market_result, "market_technical_analyst")
        _apply_market_technical_context(context, outputs, market_result.data)

        bottom_result = BottomResearchAgent().process(context, outputs)
        _record_legacy_result(legacy_results, legacy_agent_outputs, bottom_result, "bottom_research")
        _apply_context_value(context, outputs, "bottomResearch", "bottom_research", bottom_result.data)
        _apply_context_value(context, outputs, "mfeMaeResearch", "mfe_mae_path_research", bottom_result.data)

        factor_result = FactorSlicingAgent().process(context, outputs)
        _record_legacy_result(legacy_results, legacy_agent_outputs, factor_result, "factor_slicing")
        _apply_context_value(context, outputs, "factorSlicing", "factor_slicing", factor_result.data)

        factor_engine_result = FactorEngineAgent().process(context, outputs)
        _record_legacy_result(legacy_results, legacy_agent_outputs, factor_engine_result, "factor_engine")
        _apply_context_value(context, outputs, "factorEngine", "factor_engine", factor_engine_result.data)

        calculation_result = CalculationAuthorityAgent().process(context, outputs)
        _record_legacy_result(legacy_results, legacy_agent_outputs, calculation_result, "calculation_authority")
        _apply_context_value(context, outputs, "calculationAuthority", "calculation_authority", calculation_result.data)

        qiam_result = QiamAgent().process(context, outputs)
        _record_legacy_result(legacy_results, legacy_agent_outputs, qiam_result, "quant_engine")
        legacy_results["qiam"] = _quant_core_legacy_payload(qiam_result.to_dict())
        legacy_agent_outputs["qiam"] = _quant_core_legacy_payload(dict(qiam_result.data or {}))
        _apply_qiam_context(context, outputs, qiam_result.data)

        if run_mode == "FAST_MODE":
            scenario_result = _fast_mode_scenario_skip()
        else:
            scenario_result = ScenarioEngineAgent().process(context, outputs)
        _record_legacy_result(legacy_results, legacy_agent_outputs, scenario_result, "scenario_engine")
        outputs["scenario_engine"] = scenario_result.data

        quant_engine = context.get("quantEngine") if isinstance(context.get("quantEngine"), dict) else {}
        core_interpretation = build_quant_core_interpretation(
            context,
            marketTechnical=market_result.data,
            bottomResearch=bottom_result.data,
            factorSlicing=factor_result.data,
            qiam=qiam_result.data,
            scenario=scenario_result.data,
            quantEngine=quant_engine,
        )

        component_results = {
            "marketTechnical": market_result,
            "bottomResearch": bottom_result,
            "factorSlicing": factor_result,
            "factorEngine": factor_engine_result,
            "calculationAuthority": calculation_result,
            "qiam": qiam_result,
            "scenario": scenario_result,
        }
        warnings = _unique(_collect(component_results.values(), "warnings"))
        missing_data = _unique(_collect(component_results.values(), "missing_data"))
        status = _aggregate_status(component_results, run_mode)
        confidence = "HIGH" if status == "PASS" else ("MEDIUM" if status in {"WARN", "REVIEW_ONLY"} else "LOW")
        evidence_strength = "LOW" if missing_data or warnings or status in {"WARN", "REVIEW_ONLY", "SKIPPED", "FAIL", "ERROR"} else "MEDIUM"

        data = {
            "agent": self.node,
            "status": status,
            "actionBoundary": CORE_INTERPRETATION_ACTION_BOUNDARY,
            "evidenceUsage": "simulation_only",
            "evidenceStrength": evidence_strength,
            "simulation_only": True,
            "is_real_trade": False,
            "strongConclusionAllowed": False,
            "marketTechnical": market_result.data,
            "mfeMaeResearch": bottom_result.data,
            "bottomResearch": bottom_result.data,
            "factorSlicing": factor_result.data,
            "factorEngine": factor_engine_result.data,
            "calculationAuthority": calculation_result.data,
            "quantEngine": quant_engine,
            "qiam": qiam_result.data,
            "scenario": scenario_result.data,
            "coreInterpretation": core_interpretation,
            "legacyOutputs": legacy_results,
            "legacyAgentOutputs": legacy_agent_outputs,
            "warnings": warnings,
            "missingData": missing_data,
            "provenance": {
                "sourceNode": self.node,
                "actionBoundary": CORE_INTERPRETATION_ACTION_BOUNDARY,
                "evidenceUsage": "simulation_only",
                "evidenceStrength": evidence_strength,
                "simulation_only": True,
                "is_real_trade": False,
                "strongConclusionAllowed": False,
                "mergedNodes": [
                    "market_technical_analyst",
                    "bottom_research",
                    "mfe_mae_path_research",
                    "quant_engine",
                    "scenario_engine",
                ],
            },
        }

        return AgentResult(
            node=self.node,
            status=status,
            allowed_actions=["REVIEW_ONLY", "WATCH"],
            blocked_actions=_unique(_collect(component_results.values(), "blocked_actions")),
            hard_stop=bool(qiam_result.hard_stop),
            final_decision_cap="NO_DIRECT_TRADE_ACTION",
            confidence=confidence,
            reasons=[
                "量化核心统一编排市场状态、K线技术面、MFE/MAE路径研究、QIAM和情景引擎。",
                "MFE/MAE path research is the active research layer; QIAM calibration remains guarded to one step.",
            ],
            missing_data=missing_data,
            warnings=warnings,
            data=data,
            audit_id=self._audit(),
        )


def build_quant_core_interpretation(
    run_context: Dict[str, Any],
    *,
    marketTechnical: Dict[str, Any] | None = None,
    bottomResearch: Dict[str, Any] | None = None,
    factorSlicing: Dict[str, Any] | None = None,
    qiam: Dict[str, Any] | None = None,
    scenario: Dict[str, Any] | None = None,
    quantEngine: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    market_technical = _dict_or_empty(marketTechnical or run_context.get("marketTechnical"))
    technical = _dict_or_empty(market_technical.get("technicalKline") or run_context.get("technicalKline"))
    bottom = _dict_or_empty(bottomResearch or run_context.get("bottomResearch"))
    factor = _dict_or_empty(factorSlicing or run_context.get("factorSlicing"))
    qiam_data = _dict_or_empty(qiam or run_context.get("qiam"))
    scenario_data = _dict_or_empty(scenario or run_context.get("scenario"))
    quant_engine = _dict_or_empty(quantEngine or run_context.get("quantEngine"))
    path_risk_filter = build_mfe_mae_path_risk_filter(
        run_context,
        marketTechnical=market_technical,
        qiam=qiam_data,
    )

    quant_mode = _quant_mode(run_context, quant_engine, qiam_data, factor)
    base_weights = CORE_INTERPRETATION_WEIGHTS.get(quant_mode, CORE_INTERPRETATION_WEIGHTS["HIGH_FREQ_SHORT"])
    raw_dimensions = [
        _qiam_dimension(qiam_data),
        _technical_dimension(technical),
        _bottom_dimension(bottom),
        _factor_dimension(factor),
        _market_scenario_dimension(run_context, market_technical, scenario_data),
    ]
    available_weight = sum(base_weights.get(item["key"], 0.0) for item in raw_dimensions if item.pop("_available", False))
    weight_adjusted = available_weight < 0.999
    weight_adjustment_reasons = [
        f"{item['label']}缺失或跳过，权重已归一化。"
        for item in raw_dimensions
        if base_weights.get(item["key"], 0.0) > 0 and item["weight"] == 0
    ]

    dimensions: List[Dict[str, Any]] = []
    weighted_score = 0.0
    weighted_confidence = 0.0
    for item in raw_dimensions:
        key = item["key"]
        raw_weight = base_weights.get(key, 0.0)
        normalized_weight = round(raw_weight / available_weight, 4) if item["weight"] and available_weight > 0 else 0.0
        item["weight"] = normalized_weight
        weighted_score += item["score"] * normalized_weight
        weighted_confidence += item["confidence"] * normalized_weight
        dimensions.append(item)

    coverage = min(1.0, max(0.0, available_weight))
    overall_score = round(weighted_score, 2) if available_weight > 0 else 0.0
    confidence = round(weighted_confidence * coverage, 4) if available_weight > 0 else 0.0
    conflicts = _interpretation_conflicts(qiam_data, technical, bottom, market_technical)
    conflicts.extend(_path_risk_conflicts(path_risk_filter, qiam_data))
    overall_bias = _overall_bias(overall_score, conflicts)
    status = _interpretation_status(overall_score, qiam_data, available_weight)
    risk_flags = _interpretation_risk_flags(raw_dimensions, qiam_data, technical, bottom, conflicts)
    risk_flags = _unique(risk_flags + _path_risk_flags(path_risk_filter))
    path_risk_dimension = _path_risk_dimension(path_risk_filter)
    dimensions.append(path_risk_dimension)
    future_trend_probability = build_future_trend_probability(
        bottom=bottom,
        qiam=qiam_data,
        technical=technical,
        dimensions=dimensions,
    )
    visual_decision_panel = build_visual_decision_panel(
        bottom=bottom,
        path_risk_filter=path_risk_filter,
        future_trend_probability=future_trend_probability,
    )

    weights = {item["key"]: item["weight"] for item in dimensions}
    return {
        "version": CORE_INTERPRETATION_VERSION,
        "status": status,
        "overallScore": overall_score,
        "overallBias": overall_bias,
        "confidence": confidence,
        "summary": _interpretation_summary(overall_score, overall_bias, confidence, conflicts, weight_adjusted),
        "weights": weights,
        "dimensions": dimensions,
        "conflicts": conflicts,
        "riskFlags": risk_flags,
        "weightAdjusted": weight_adjusted,
        "weightAdjustmentReasons": weight_adjustment_reasons,
        "actionBoundary": CORE_INTERPRETATION_ACTION_BOUNDARY,
        "quantEngineMode": quant_mode,
        "pathRiskFilter": path_risk_filter,
        "futureTrendProbability": future_trend_probability,
        "visualDecisionPanel": visual_decision_panel,
    }


def build_mfe_mae_path_risk_filter(
    run_context: Dict[str, Any],
    *,
    marketTechnical: Dict[str, Any] | None = None,
    qiam: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    market_technical = _dict_or_empty(marketTechnical or run_context.get("marketTechnical"))
    technical = _dict_or_empty(market_technical.get("technicalKline") or run_context.get("technicalKline"))
    qiam_data = _dict_or_empty(qiam or run_context.get("qiam"))
    market = _dict_or_empty(market_technical.get("market") or run_context.get("market"))
    dvg = _dict_or_empty(run_context.get("dvg"))
    trend = _dict_or_empty(technical.get("trend"))
    volume_price = _dict_or_empty(technical.get("volumePrice"))
    support_resistance = _dict_or_empty(technical.get("supportResistance"))
    chip = _dict_or_empty(technical.get("chipAnalysis"))
    quality = _dict_or_empty(technical.get("dataQuality"))

    limitations = [
        "MFE/MAE fields are daily proxies, not trained conditional quantile predictions.",
        "No future high/low labels are used at runtime.",
        "Level-2 order flow, real order book depth, full chip distribution, and valuation gap are not required in v1.",
        "Cross-market evidence from the source paper is recorded as a limitation, not as a runtime market-bias rule.",
    ]
    warnings: List[str] = []
    missing = _path_risk_missing_inputs(quality, trend, support_resistance)
    data_sample_quality = {
        "dataMode": str(quality.get("dataMode") or "UNAVAILABLE"),
        "dailyCount": _int_value(quality.get("dailyCount")),
        "provider": quality.get("provider"),
        "missingInputs": missing,
    }
    if missing:
        return {
            "version": PATH_RISK_FILTER_VERSION,
            "status": "INSUFFICIENT_DATA",
            "method": PATH_RISK_FILTER_METHOD,
            "horizonDays": PATH_RISK_HORIZON_DAYS,
            "actionBoundary": CORE_INTERPRETATION_ACTION_BOUNDARY,
            "labelStatus": "UNLABELED_NOWCAST_PROXY_ONLY",
            "sampleQuality": data_sample_quality,
            "leakagePolicy": "runtime_uses_entry_day_technical_proxy_only; no_future_mfe_mae_labels_or_external_order_book",
            "simulation_only": True,
            "is_real_trade": False,
            "mfeMaeProxy": {
                "mfeProxy": None,
                "maeProxy": None,
                "riskRewardProxy": None,
            },
            "riskCurve": [],
            "downsideRiskScore": None,
            "maxRiskGradient": None,
            "riskPolicy": "WATCH",
            "evidence": [],
            "warnings": missing,
            "limitations": limitations,
            "provenance": _path_risk_provenance(),
        }

    close = _number(trend.get("close")) or 0.0
    return20d = _number(trend.get("return20d")) or 0.0
    return60d = _number(trend.get("return60d")) or 0.0
    volume_ratio = _number(volume_price.get("volumeRatio5v20"))
    distance_support20 = max(0.0, _number(support_resistance.get("distanceToSupport20d")) or 0.0)
    distance_resistance20 = max(0.0, _number(support_resistance.get("distanceToResistance20d")) or 0.0)
    overhead_ratio = _number(chip.get("overheadVolumeRatio"))
    support_ratio = _number(chip.get("supportVolumeRatio"))
    cost_zone_ratio = _number(_dict_or_empty(chip.get("costZone")).get("volumeRatio"))
    qiam_up = _number(qiam_data.get("probabilityBandUp")) or 0.0
    qiam_down = _number(qiam_data.get("probabilityBandDown")) or 0.0

    if volume_ratio is None:
        warnings.append("volume_price_ratio_missing")
        volume_ratio = 1.0
    if overhead_ratio is None:
        warnings.append("overhead_volume_proxy_missing")
        overhead_ratio = 0.0
    if support_ratio is None:
        warnings.append("support_volume_proxy_missing")
        support_ratio = 0.0
    if cost_zone_ratio is None:
        warnings.append("cost_zone_proxy_missing")
        cost_zone_ratio = 0.0

    negative_momentum = _clamp((-return20d * 5.0) + (-return60d * 2.0), 0.0, 1.0)
    volume_pressure = _clamp((volume_ratio - 1.0) / 1.5, 0.0, 1.0) if return20d <= 0 else _clamp((volume_ratio - 1.5) / 2.0, 0.0, 0.5)
    overhang_pressure = _clamp(overhead_ratio / 0.45, 0.0, 1.0)
    support_density = _clamp(max(support_ratio, cost_zone_ratio * 0.5) / 0.45, 0.0, 1.0)
    sell_pressure = _clamp(
        (negative_momentum * 0.35)
        + (volume_pressure * 0.25)
        + (overhang_pressure * 0.25)
        + (_clamp(qiam_down, 0.0, 1.0) * 0.15),
        0.0,
        1.0,
    )
    base_liquidity_gap = _liquidity_gap_from_market(market, dvg)
    market_panic = _market_panic_proxy(market, qiam_down)

    mfe_proxy = _clamp(
        (distance_resistance20 * 0.50)
        + (max(return20d, 0.0) * 0.40)
        + (_clamp(qiam_up, 0.0, 1.0) * 0.05)
        + ((1.0 - overhang_pressure) * 0.03),
        0.005,
        0.35,
    )
    mae_proxy = _clamp(
        0.04
        + (sell_pressure * 0.08)
        + (base_liquidity_gap * 0.05)
        + (market_panic * 0.04)
        - (support_density * 0.03),
        0.005,
        0.30,
    )
    risk_reward_proxy = mfe_proxy / (mae_proxy + 0.000001)

    risk_curve = _path_risk_curve(
        sell_pressure=sell_pressure,
        liquidity_gap=base_liquidity_gap,
        market_panic=market_panic,
        support_density=support_density,
        distance_support20=distance_support20,
        negative_momentum=negative_momentum,
        overhang_pressure=overhang_pressure,
    )
    max_risk_gradient = max((item["riskGradient"] for item in risk_curve), default=0.0)
    mae_pressure = _clamp(mae_proxy / 0.15, 0.0, 1.0)
    max_gradient_pressure = _clamp(max_risk_gradient / 8.0, 0.0, 1.0)
    downside_risk_score = round(
        100.0
        * (
            (0.35 * mae_pressure)
            + (0.25 * max_gradient_pressure)
            + (0.20 * sell_pressure)
            + (0.10 * base_liquidity_gap)
            + (0.10 * market_panic)
        ),
        2,
    )
    risk_policy = _path_risk_policy(downside_risk_score)

    evidence = [
        f"close={close:.4f}",
        f"return20d={return20d:.2%}",
        f"distanceToSupport20d={distance_support20:.2%}",
        f"distanceToResistance20d={distance_resistance20:.2%}",
        f"sellPressure={sell_pressure:.2f}",
        f"maxRiskGradient={max_risk_gradient:.2f}",
    ]
    if str(chip.get("source") or "").upper() == "KLINE_VOLUME_PRICE_PROXY":
        warnings.append("chip_distribution_is_kline_volume_price_proxy")

    return {
        "version": PATH_RISK_FILTER_VERSION,
        "status": "READY",
        "method": PATH_RISK_FILTER_METHOD,
        "horizonDays": PATH_RISK_HORIZON_DAYS,
        "actionBoundary": CORE_INTERPRETATION_ACTION_BOUNDARY,
        "labelStatus": "UNLABELED_NOWCAST_PROXY_ONLY",
        "sampleQuality": data_sample_quality,
        "leakagePolicy": "runtime_uses_entry_day_technical_proxy_only; no_future_mfe_mae_labels_or_external_order_book",
        "simulation_only": True,
        "is_real_trade": False,
        "mfeMaeProxy": {
            "mfeProxy": round(mfe_proxy, 6),
            "maeProxy": round(mae_proxy, 6),
            "riskRewardProxy": round(risk_reward_proxy, 4),
        },
        "riskCurve": risk_curve,
        "downsideRiskScore": downside_risk_score,
        "maxRiskGradient": round(max_risk_gradient, 4),
        "riskPolicy": risk_policy,
        "evidence": evidence,
        "warnings": _unique(warnings),
        "limitations": limitations,
        "provenance": _path_risk_provenance(),
    }


def _path_risk_missing_inputs(
    quality: Dict[str, Any],
    trend: Dict[str, Any],
    support_resistance: Dict[str, Any],
) -> List[str]:
    missing: List[str] = []
    if str(quality.get("dataMode") or "").upper() != "LIVE":
        missing.append("technical_kline_live_daily_data_missing")
    if _int_value(quality.get("dailyCount")) < 30:
        missing.append("technical_kline_daily_count_below_30")
    close = _number(trend.get("close"))
    if close is None or close <= 0:
        missing.append("technical_trend_close_missing")
    for key in ("support20d", "support60d", "distanceToSupport20d", "distanceToResistance20d"):
        if _number(support_resistance.get(key)) is None:
            missing.append(f"support_resistance_{key}_missing")
    return missing


def _liquidity_gap_from_market(market: Dict[str, Any], dvg: Dict[str, Any]) -> float:
    liquidity_index = _number(market.get("liquidityIndex"))
    if liquidity_index is not None:
        return _clamp(1.0 - (liquidity_index / 100.0), 0.0, 1.0)
    reliability = str(dvg.get("dataReliability") or "").upper()
    return {
        "HIGH": 0.20,
        "MEDIUM": 0.45,
        "LOW": 0.70,
    }.get(reliability, 0.50)


def _market_panic_proxy(market: Dict[str, Any], qiam_down: float) -> float:
    sentiment = str(market.get("marketSentiment") or "").upper()
    regime = str(market.get("regimeClassification") or "").upper()
    volatility = _number(market.get("volatilityIndex"))
    score = 0.0
    if sentiment == "BEARISH":
        score += 0.35
    elif sentiment == "BULLISH":
        score -= 0.10
    if "PANIC" in regime or "恐慌" in regime:
        score += 0.45
    if "高波动" in regime or "HIGH_VOL" in regime:
        score += 0.25
    if volatility is not None:
        score += _clamp((volatility - 60.0) / 40.0, 0.0, 0.50)
    score += _clamp(qiam_down, 0.0, 1.0) * 0.20
    return _clamp(score, 0.0, 1.0)


def _path_risk_curve(
    *,
    sell_pressure: float,
    liquidity_gap: float,
    market_panic: float,
    support_density: float,
    distance_support20: float,
    negative_momentum: float,
    overhang_pressure: float,
) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    previous_score: float | None = None
    previous_bucket: float | None = None
    for bucket in PATH_RISK_DRAWDOWN_BUCKETS:
        support_break_pressure = _clamp((bucket - distance_support20) / (bucket + 0.02), 0.0, 1.0)
        bucket_liquidity_gap = _clamp(liquidity_gap + (bucket / 0.20 * 0.35) - (support_density * 0.20), 0.0, 1.0)
        bucket_support_density = _clamp(support_density * (1.0 - (support_break_pressure * 0.65)), 0.0, 1.0)
        stop_loss_density = _clamp(
            (support_break_pressure * 0.45)
            + (negative_momentum * 0.35)
            + (overhang_pressure * 0.20),
            0.0,
            1.0,
        )
        risk_potential = _clamp(
            (0.30 * sell_pressure)
            + (0.25 * bucket_liquidity_gap)
            + (0.20 * stop_loss_density)
            + (0.15 * market_panic)
            - (0.10 * bucket_support_density),
            0.0,
            1.0,
        )
        risk_score = risk_potential * 100.0
        if previous_score is None or previous_bucket is None:
            gradient = 0.0
        else:
            gradient = max(0.0, (risk_score - previous_score) / ((bucket - previous_bucket) * 100.0))
        result.append({
            "drawdownPct": round(bucket * 100.0, 2),
            "riskPotential": round(risk_score, 2),
            "riskGradient": round(gradient, 4),
            "components": {
                "sellPressure": round(sell_pressure, 4),
                "liquidityGap": round(bucket_liquidity_gap, 4),
                "stopLossDensity": round(stop_loss_density, 4),
                "marketPanic": round(market_panic, 4),
                "supportDensity": round(bucket_support_density, 4),
            },
        })
        previous_score = risk_score
        previous_bucket = bucket
    return result


def _path_risk_policy(score: float | None) -> str:
    if score is None:
        return "WATCH"
    if score < 40:
        return "NORMAL"
    if score < 60:
        return "WATCH"
    if score < 75:
        return "THROTTLE"
    return "AVOID_NEW_BUY"


def _path_risk_dimension(path_risk_filter: Dict[str, Any]) -> Dict[str, Any]:
    status = str(path_risk_filter.get("status") or "INSUFFICIENT_DATA").upper()
    score = _number(path_risk_filter.get("downsideRiskScore"))
    policy = str(path_risk_filter.get("riskPolicy") or "WATCH").upper()
    confidence = 0.0 if status != "READY" else 0.58
    if score is None:
        dimension_score = 0.0
        bias = "UNKNOWN"
    else:
        dimension_score = 100.0 - score
        bias = "BEARISH" if policy in {"THROTTLE", "AVOID_NEW_BUY"} else ("SIDEWAYS" if policy == "WATCH" else "BULLISH")
    proxy = _dict_or_empty(path_risk_filter.get("mfeMaeProxy"))
    evidence = [
        f"riskPolicy={policy}",
        f"downsideRiskScore={_display_number(score)}",
        f"riskRewardProxy={_display_number(proxy.get('riskRewardProxy'))}",
        f"maxRiskGradient={_display_number(path_risk_filter.get('maxRiskGradient'))}",
    ]
    return {
        "key": "pathRisk",
        "label": "MFE/MAE路径风险",
        "score": round(_clamp(dimension_score, 0.0, 100.0), 2),
        "bias": bias,
        "confidence": confidence,
        "weight": 0.0,
        "evidence": evidence,
        "warnings": _unique(_as_text_list(path_risk_filter.get("warnings")) + _as_text_list(path_risk_filter.get("limitations"))[:2]),
    }


def _path_risk_conflicts(path_risk_filter: Dict[str, Any], qiam: Dict[str, Any]) -> List[Dict[str, Any]]:
    if str(path_risk_filter.get("status") or "").upper() != "READY":
        return []
    policy = str(path_risk_filter.get("riskPolicy") or "").upper()
    final_buy = str(qiam.get("finalBuySuitability") or "").upper()
    if final_buy != "FAVORABLE" or policy not in {"THROTTLE", "AVOID_NEW_BUY"}:
        return []
    severity = "BLOCKING_CONTEXT" if policy == "AVOID_NEW_BUY" else "WARN"
    return [{
        "key": "path_risk_qiam_divergence",
        "severity": severity,
        "message": "QIAM 显示有利，但 MFE/MAE 路径风险过滤器提示下行路径风险偏高；该冲突只用于解释，不改变交易权限。",
        "evidence": [
            f"finalBuySuitability={final_buy}",
            f"riskPolicy={policy}",
            f"downsideRiskScore={_display_number(path_risk_filter.get('downsideRiskScore'))}",
        ],
    }]


def _path_risk_flags(path_risk_filter: Dict[str, Any]) -> List[str]:
    if str(path_risk_filter.get("status") or "").upper() != "READY":
        return []
    policy = str(path_risk_filter.get("riskPolicy") or "").upper()
    flags: List[str] = []
    if policy in {"THROTTLE", "AVOID_NEW_BUY"}:
        flags.append("path_risk_gradient_high")
    if policy == "AVOID_NEW_BUY":
        flags.append("path_risk_avoid_new_buy_read_only")
    return flags


def _path_risk_provenance() -> Dict[str, Any]:
    return {
        "sourceNode": "quant_core",
        "source": "existing_run_payload_only",
        "actionBoundary": CORE_INTERPRETATION_ACTION_BOUNDARY,
        "simulation_only": True,
        "is_real_trade": False,
        "inputFields": [
            "technicalKline.trend",
            "technicalKline.volumePrice",
            "technicalKline.supportResistance",
            "technicalKline.chipAnalysis",
            "technicalKline.dataQuality",
            "marketTechnical.market",
            "qiam",
            "dvg",
        ],
    }


def _qiam_dimension(qiam: Dict[str, Any]) -> Dict[str, Any]:
    final_buy = str(qiam.get("finalBuySuitability") or "").upper()
    if not final_buy and not qiam:
        return _unavailable_dimension("qiam", "QIAM适宜性", "QIAM 尚无输出。")
    base_score = {
        "FAVORABLE": 78.0,
        "NEUTRAL": 55.0,
        "REVIEW_ONLY": 42.0,
        "BLOCK_BUY": 18.0,
    }.get(final_buy, 50.0)
    up = _number(qiam.get("probabilityBandUp"))
    down = _number(qiam.get("probabilityBandDown"))
    if up is not None and down is not None:
        probability_score = _clamp(50.0 + ((up - down) * 50.0), 0.0, 100.0)
        score = (base_score * 0.65) + (probability_score * 0.35)
    else:
        score = base_score
    confidence = _number(qiam.get("modelConfidenceFinal"))
    if confidence is None or confidence <= 0:
        confidence = 0.55 if str(qiam.get("probabilitySource") or "").upper() == "RULE_DERIVED" else 0.35
    return _dimension(
        key="qiam",
        label="QIAM适宜性",
        score=score,
        bias=_qiam_bias(final_buy),
        confidence=confidence,
        evidence=[
            f"finalBuySuitability={final_buy or 'UNKNOWN'}",
            f"discountFactor={_display_number(qiam.get('discountFactor'))}",
            f"probabilityBandUp={_display_percent(up)}",
            f"probabilityBandDown={_display_percent(down)}",
        ],
        warnings=_as_text_list(qiam.get("downgradeReasons"))[:4] + _as_text_list(qiam.get("missingData"))[:3],
    )


def _technical_dimension(technical: Dict[str, Any]) -> Dict[str, Any]:
    bias = str(technical.get("technicalBias") or "").upper()
    status = str(technical.get("status") or "").upper()
    if not technical or status == "SKIPPED" or bias in {"", "UNKNOWN", "INSUFFICIENT_DATA"}:
        return _unavailable_dimension("technical", "K线技术面", "K线技术面缺失、跳过或样本不足。")
    score = {
        "BULLISH": 76.0,
        "BEARISH": 24.0,
        "SIDEWAYS": 54.0,
        "MIXED": 50.0,
        "NEUTRAL": 52.0,
    }.get(bias, 50.0)
    confidence = _number(technical.get("confidence"))
    quality = _dict_or_empty(technical.get("dataQuality"))
    daily_count = _int_value(quality.get("dailyCount"))
    if daily_count and daily_count < 30:
        confidence = min(confidence or 0.35, 0.35)
    return _dimension(
        key="technical",
        label="K线技术面",
        score=score,
        bias=_technical_bias(bias),
        confidence=confidence if confidence is not None else 0.45,
        evidence=[
            f"technicalBias={bias}",
            f"confidence={_display_number(confidence)}",
            f"dailyCount={daily_count}",
            str(technical.get("summaryForDownstream") or ""),
        ],
        warnings=_as_text_list(technical.get("risks")) + _as_text_list(quality.get("issues")),
    )


def _bottom_dimension(bottom: Dict[str, Any]) -> Dict[str, Any]:
    status = str(bottom.get("status") or "").upper()
    regime = str(bottom.get("regimeState") or "").upper()
    repair = _number(bottom.get("mfeFavorableProbability") or bottom.get("bottomRepairProbability"))
    breakdown = _number(bottom.get("maeBreachProbability") or bottom.get("breakdownRiskProbability"))
    if not bottom or status == "SKIPPED" or regime == "DISABLED_BY_RUN_MODE" or (repair is None and breakdown is None):
        return _unavailable_dimension("mfeMaeResearch", "MFE/MAE路径研究", "MFE/MAE路径研究缺失或当前模式未启用。")
    repair_value = repair if repair is not None else 0.5
    breakdown_value = breakdown if breakdown is not None else 0.5
    score = _clamp(50.0 + ((repair_value - breakdown_value) * 50.0), 0.0, 100.0)
    synthesis = _dict_or_empty(bottom.get("trendSynthesis"))
    trend_bias = str(synthesis.get("primaryTrendBias") or "").upper()
    confidence = _number(synthesis.get("confidence"))
    diagnostics = _dict_or_empty(bottom.get("modelDiagnostics"))
    if confidence is None:
        confidence = 0.65 if diagnostics.get("status") == "READY" else 0.45
    return _dimension(
        key="mfeMaeResearch",
        label="MFE/MAE路径研究",
        score=score,
        bias=_bottom_bias(trend_bias, repair_value, breakdown_value),
        confidence=confidence,
        evidence=[
            f"regimeState={regime or 'UNKNOWN'}",
            f"mfeFavorable={_display_percent(repair)}",
            f"maeBreach={_display_percent(breakdown)}",
            f"riskRewardProxy={_display_number(bottom.get('riskRewardProxy'))}",
            str(synthesis.get("mainConclusion") or ""),
        ],
        warnings=_as_text_list(bottom.get("warnings")) + _as_text_list(synthesis.get("riskFlags")),
    )


def _factor_dimension(factor: Dict[str, Any]) -> Dict[str, Any]:
    if not factor or str(factor.get("factorDataSource") or "").upper() == "PENDING":
        return _unavailable_dimension("factor", "因子稳定性", "因子切片尚未形成稳定输出。")
    stability = _number(factor.get("factorStability"))
    missing = _as_text_list(factor.get("missingFactorData"))
    if stability is None and not missing:
        return _unavailable_dimension("factor", "因子稳定性", "因子稳定性缺失。")
    score = _clamp((stability if stability is not None else 0.5) * 100.0 - (len(missing) * 6.0), 0.0, 100.0)
    return _dimension(
        key="factor",
        label="因子稳定性",
        score=score,
        bias="BULLISH" if score >= 65 else ("BEARISH" if score <= 40 else "SIDEWAYS"),
        confidence=stability if stability is not None else 0.4,
        evidence=[
            f"mode={factor.get('mode', 'UNKNOWN')}",
            f"factorStability={_display_percent(stability)}",
            f"factorClusters={', '.join(_as_text_list(factor.get('factorClusters'))[:4])}",
        ],
        warnings=missing[:5],
    )


def _market_scenario_dimension(
    run_context: Dict[str, Any],
    market_technical: Dict[str, Any],
    scenario: Dict[str, Any],
) -> Dict[str, Any]:
    market = _dict_or_empty(market_technical.get("market") or run_context.get("market"))
    dvg = _dict_or_empty(run_context.get("dvg"))
    alignment = str(market_technical.get("alignment") or "").upper()
    sentiment = str(market.get("marketSentiment") or "").upper()
    scenario_permission = str(
        scenario.get("dvgPermission") or scenario.get("scenarioPermission") or dvg.get("scenarioPermission") or ""
    ).upper()
    if not market_technical and not scenario and not market:
        return _unavailable_dimension("marketScenario", "市场/情景一致性", "市场与情景输出缺失。")
    score = {
        "ALIGNED_BULLISH": 70.0,
        "ALIGNED_BEARISH": 32.0,
        "NEUTRAL_OR_MIXED": 52.0,
        "TECHNICAL_INSUFFICIENT_DATA": 42.0,
        "CONFLICT": 38.0,
    }.get(alignment, 50.0)
    if sentiment == "BULLISH":
        score += 5.0
    elif sentiment == "BEARISH":
        score -= 5.0
    if scenario_permission in {"BLOCKED", "REVIEW_ONLY", "NOT_RUN_IN_FAST_MODE"}:
        score -= 8.0
    confidence = _number(market_technical.get("confidence"))
    return _dimension(
        key="marketScenario",
        label="市场/情景一致性",
        score=_clamp(score, 0.0, 100.0),
        bias="BULLISH" if score >= 65 else ("BEARISH" if score <= 40 else "SIDEWAYS"),
        confidence=confidence if confidence is not None else 0.45,
        evidence=[
            f"marketSentiment={sentiment or 'UNKNOWN'}",
            f"alignment={alignment or 'UNKNOWN'}",
            f"scenarioPermission={scenario_permission or 'UNKNOWN'}",
        ],
        warnings=_as_text_list(market_technical.get("warnings")) + _as_text_list(scenario.get("warnings")),
    )


def _interpretation_conflicts(
    qiam: Dict[str, Any],
    technical: Dict[str, Any],
    bottom: Dict[str, Any],
    market_technical: Dict[str, Any],
) -> List[Dict[str, Any]]:
    conflicts: List[Dict[str, Any]] = []
    final_buy = str(qiam.get("finalBuySuitability") or "").upper()
    technical_bias = str(technical.get("technicalBias") or "").upper()
    bottom_bias = _bottom_bias(
        str(_dict_or_empty(bottom.get("trendSynthesis")).get("primaryTrendBias") or "").upper(),
        _number(bottom.get("mfeFavorableProbability") or bottom.get("bottomRepairProbability")) or 0.5,
        _number(bottom.get("maeBreachProbability") or bottom.get("breakdownRiskProbability")) or 0.5,
    )
    breakdown = _number(bottom.get("maeBreachProbability") or bottom.get("breakdownRiskProbability")) or 0.0

    if final_buy == "FAVORABLE" and technical_bias == "BEARISH":
        conflicts.append({
            "key": "qiam_technical_divergence",
            "severity": "BLOCKING_CONTEXT" if breakdown >= 0.55 else "WARN",
            "message": "QIAM 显示有利，但 K线技术面看空，需要人工复核解释冲突。",
            "evidence": [f"finalBuySuitability={final_buy}", f"technicalBias={technical_bias}"],
        })
    if bottom_bias == "BULLISH" and technical_bias == "BEARISH":
        conflicts.append({
            "key": "mfe_mae_technical_divergence",
            "severity": "WARN",
            "message": "MFE/MAE路径研究偏有利，但 K线技术面仍看空。",
            "evidence": [f"mfeMaeBias={bottom_bias}", f"technicalBias={technical_bias}"],
        })
    if final_buy == "FAVORABLE" and breakdown >= 0.55:
        conflicts.append({
            "key": "mfe_mae_risk_qiam_divergence",
            "severity": "BLOCKING_CONTEXT",
            "message": "QIAM 有利与 MFE/MAE 路径风险偏高同时出现，解释层标记为强冲突。",
            "evidence": [f"finalBuySuitability={final_buy}", f"maeBreachRisk={breakdown:.0%}"],
        })
    if str(market_technical.get("alignment") or "").upper() == "CONFLICT":
        conflicts.append({
            "key": "market_technical_conflict",
            "severity": "WARN",
            "message": "市场状态与 K线技术面存在方向冲突。",
            "evidence": [f"alignment={market_technical.get('alignment')}"],
        })
    return conflicts


def _interpretation_risk_flags(
    dimensions: List[Dict[str, Any]],
    qiam: Dict[str, Any],
    technical: Dict[str, Any],
    bottom: Dict[str, Any],
    conflicts: List[Dict[str, Any]],
) -> List[str]:
    flags = [CORE_INTERPRETATION_ACTION_BOUNDARY]
    flags.extend(f"{item['label']}不可用" for item in dimensions if item["weight"] == 0)
    if _as_text_list(qiam.get("downgradeReasons")):
        flags.append("QIAM存在折扣原因")
    if str(technical.get("technicalBias") or "").upper() in {"BEARISH", "INSUFFICIENT_DATA"}:
        flags.append("K线技术面偏弱或数据不足")
    if (_number(bottom.get("maeBreachProbability") or bottom.get("breakdownRiskProbability")) or 0.0) >= 0.55:
        flags.append("MFE/MAE 路径风险偏高")
    if any(item.get("severity") == "BLOCKING_CONTEXT" for item in conflicts):
        flags.append("解释层存在强冲突，不等于交易阻断")
    return _unique(flags)


def _dimension(
    *,
    key: str,
    label: str,
    score: float,
    bias: str,
    confidence: float,
    evidence: List[str],
    warnings: List[str],
) -> Dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "score": round(_clamp(score, 0.0, 100.0), 2),
        "bias": bias,
        "confidence": round(_clamp(confidence, 0.0, 1.0), 4),
        "weight": 1.0,
        "evidence": [item for item in evidence if item],
        "warnings": _unique(warnings),
        "_available": True,
    }


def _unavailable_dimension(key: str, label: str, reason: str) -> Dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "score": 0.0,
        "bias": "UNKNOWN",
        "confidence": 0.0,
        "weight": 0.0,
        "evidence": [],
        "warnings": [reason],
        "_available": False,
    }


def _quant_mode(
    run_context: Dict[str, Any],
    quant_engine: Dict[str, Any],
    qiam: Dict[str, Any],
    factor: Dict[str, Any],
) -> str:
    explicit = (
        quant_engine.get("mode")
        or qiam.get("quantEngineMode")
        or factor.get("quantEngineMode")
    )
    if explicit:
        return str(explicit).upper()
    return str(quant_engine_profile_from_run(run_context).get("mode") or "HIGH_FREQ_SHORT").upper()


def _overall_bias(score: float, conflicts: List[Dict[str, Any]]) -> str:
    if any(item.get("severity") == "BLOCKING_CONTEXT" for item in conflicts):
        return "MIXED"
    if score >= 65:
        return "BULLISH"
    if score <= 40:
        return "BEARISH"
    return "SIDEWAYS" if 45 <= score <= 55 else "MIXED"


def _interpretation_status(score: float, qiam: Dict[str, Any], available_weight: float) -> str:
    if available_weight <= 0:
        return "SKIPPED"
    if str(qiam.get("finalBuySuitability") or "").upper() == "BLOCK_BUY" or score < 40:
        return "REVIEW_ONLY"
    return "PASS" if score >= 65 else "WARN"


def _interpretation_summary(
    score: float,
    bias: str,
    confidence: float,
    conflicts: List[Dict[str, Any]],
    weight_adjusted: bool,
) -> str:
    conflict_text = "；存在解释层强冲突" if any(item.get("severity") == "BLOCKING_CONTEXT" for item in conflicts) else ""
    weight_text = "；部分维度缺失已重分配权重" if weight_adjusted else ""
    return f"核心解读综合分 {score:.1f}，方向={bias}，证据置信度={confidence:.0%}{conflict_text}{weight_text}。该模块只读，不改变交易权限。"


def build_future_trend_probability(
    *,
    bottom: Dict[str, Any],
    qiam: Dict[str, Any],
    technical: Dict[str, Any],
    dimensions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    forecasts = _future_trend_forecasts(bottom)
    if not forecasts:
        forecasts = [{"horizonDays": _future_primary_horizon(bottom), "status": "SUPPORTING_ONLY"}]

    points: List[Dict[str, Any]] = []
    calibration_summaries: List[Dict[str, Any]] = []
    for forecast in forecasts:
        horizon = _int_value(forecast.get("horizonDays")) or _future_primary_horizon(bottom)
        raw = _raw_future_trend_probability(
            forecast=forecast,
            bottom=bottom,
            qiam=qiam,
            technical=technical,
            dimensions=dimensions,
        )
        history = _future_probability_history(bottom, horizon)
        calibration = _calibrate_future_trend_probability(
            history=history,
            raw_up=raw["up"],
            raw_down=raw["down"],
        )
        calibrated = _normalize_trend_probability(
            calibration["calibratedUpProbability"],
            calibration["calibratedDownProbability"],
        )
        calibration_summaries.append(calibration)
        points.append({
            "horizonDays": horizon,
            "rawUpProbability": round(raw["up"], 6),
            "rawDownProbability": round(raw["down"], 6),
            "rawSidewaysProbability": round(raw["sideways"], 6),
            "calibratedUpProbability": calibrated["up"],
            "calibratedDownProbability": calibrated["down"],
            "calibratedSidewaysProbability": calibrated["sideways"],
            "confidence": round(_clamp(raw["confidence"] * calibration["confidenceMultiplier"], 0.0, 1.0), 4),
            "calibrationStatus": calibration["status"],
            "sourceBreakdown": raw["sourceBreakdown"],
            "simulation_only": True,
            "is_real_trade": False,
        })

    primary_horizon = _future_primary_horizon(bottom)
    primary_calibration = next(
        (item for item in calibration_summaries if item["horizonDays"] == primary_horizon),
        calibration_summaries[0],
    )
    return {
        "version": FUTURE_TREND_PROBABILITY_VERSION,
        "source": "QIAM_MFE_MAE_TECHNICAL_SYNTHESIS",
        "points": points,
        "calibration": {
            "method": FUTURE_TREND_CALIBRATION_METHOD,
            "sampleCount": primary_calibration["sampleCount"],
            "brierUp": primary_calibration["brierUp"],
            "brierDown": primary_calibration["brierDown"],
            "reliabilityBins": primary_calibration["reliabilityBins"],
            "maxAdjustment": FUTURE_TREND_MAX_ADJUSTMENT,
            "leakagePolicy": (
                "historical calibration uses only completed forward-close windows; "
                "UNLABELED_NOWCAST is excluded"
            ),
            "status": primary_calibration["status"],
        },
        "decisionFeedback": {
            "target": "QUANT_CORE_AND_SIGNALOPS_SIMULATION",
            "actionBoundary": "READ_ONLY_NO_REAL_TRADE_PERMISSION_CHANGE",
            "signalopsPolicyHint": _signalops_policy_hint(points),
            "simulation_only": True,
            "is_real_trade": False,
        },
        "actionBoundary": CORE_INTERPRETATION_ACTION_BOUNDARY,
        "simulation_only": True,
        "is_real_trade": False,
    }


def build_visual_decision_panel(
    *,
    bottom: Dict[str, Any],
    path_risk_filter: Dict[str, Any],
    future_trend_probability: Dict[str, Any],
) -> Dict[str, Any]:
    primary_horizon = _future_primary_horizon(bottom)
    points = future_trend_probability.get("points") if isinstance(future_trend_probability.get("points"), list) else []
    primary_point = next(
        (item for item in points if isinstance(item, dict) and _int_value(item.get("horizonDays")) == primary_horizon),
        next((item for item in points if isinstance(item, dict)), {}),
    )
    up_probability = _first_number(primary_point.get("calibratedUpProbability"), primary_point.get("rawUpProbability"))
    down_probability = _first_number(primary_point.get("calibratedDownProbability"), primary_point.get("rawDownProbability"))
    sideways_probability = _first_number(primary_point.get("calibratedSidewaysProbability"), primary_point.get("rawSidewaysProbability"))
    if up_probability is not None and down_probability is not None and sideways_probability is None:
        sideways_probability = _clamp(1.0 - up_probability - down_probability, 0.0, 1.0)

    proxy = _dict_or_empty(path_risk_filter.get("mfeMaeProxy"))
    mfe_proxy = _first_number(proxy.get("mfeProxy"), bottom.get("mfeProxy"))
    mae_proxy = _first_number(proxy.get("maeProxy"), bottom.get("maeProxy"))
    risk_reward_proxy = _first_number(proxy.get("riskRewardProxy"), bottom.get("riskRewardProxy"))
    if risk_reward_proxy is None and mfe_proxy is not None and mae_proxy is not None:
        risk_reward_proxy = mfe_proxy / (mae_proxy + 0.000001)
    expected_path_value = None
    if up_probability is not None and down_probability is not None and mfe_proxy is not None and mae_proxy is not None:
        expected_path_value = (up_probability * mfe_proxy) - (down_probability * mae_proxy)

    downside_risk_score = _number(path_risk_filter.get("downsideRiskScore"))
    max_risk_gradient = _number(path_risk_filter.get("maxRiskGradient"))
    risk_policy = str(path_risk_filter.get("riskPolicy") or "WATCH").upper()
    path_status = str(path_risk_filter.get("status") or "INSUFFICIENT_DATA").upper()
    matrix_zone = _probability_odds_zone(
        up_probability=up_probability,
        down_probability=down_probability,
        risk_reward_proxy=risk_reward_proxy,
        downside_risk_score=downside_risk_score,
        risk_policy=risk_policy,
        path_status=path_status,
    )
    panel_status = "READY" if matrix_zone != "INSUFFICIENT_DATA" else "INSUFFICIENT_DATA"
    probability_source = (
        "FUTURE_TREND_PROBABILITY_CALIBRATED"
        if primary_point.get("calibratedUpProbability") is not None or primary_point.get("calibratedDownProbability") is not None
        else "FUTURE_TREND_PROBABILITY_RAW"
        if primary_point
        else "INSUFFICIENT_DATA"
    )
    payoff_source = (
        "PATH_RISK_FILTER_PROXY"
        if proxy.get("mfeProxy") is not None or proxy.get("maeProxy") is not None
        else "MFE_MAE_RESEARCH_PROXY"
        if mfe_proxy is not None or mae_proxy is not None
        else "INSUFFICIENT_DATA"
    )

    return {
        "version": VISUAL_DECISION_PANEL_VERSION,
        "status": panel_status,
        "directionProbability": {
            "horizonDays": _int_value(primary_point.get("horizonDays")) or primary_horizon,
            "upProbability": _round_or_none(up_probability, 6),
            "downProbability": _round_or_none(down_probability, 6),
            "sidewaysProbability": _round_or_none(sideways_probability, 6),
            "source": probability_source,
            "calibrationStatus": primary_point.get("calibrationStatus"),
            "confidence": _round_or_none(_number(primary_point.get("confidence")), 4),
            "actionBoundary": CORE_INTERPRETATION_ACTION_BOUNDARY,
            "simulation_only": True,
            "is_real_trade": False,
        },
        "pathPayoffProxy": {
            "mfeProxy": _round_or_none(mfe_proxy, 6),
            "maeProxy": _round_or_none(mae_proxy, 6),
            "riskRewardProxy": _round_or_none(risk_reward_proxy, 4),
            "expectedPathValueProxy": _round_or_none(expected_path_value, 6),
            "source": payoff_source,
            "actionBoundary": CORE_INTERPRETATION_ACTION_BOUNDARY,
            "simulation_only": True,
            "is_real_trade": False,
        },
        "riskGradient": {
            "status": path_status,
            "downsideRiskScore": _round_or_none(downside_risk_score, 2),
            "maxRiskGradient": _round_or_none(max_risk_gradient, 4),
            "riskPolicy": risk_policy,
            "actionBoundary": CORE_INTERPRETATION_ACTION_BOUNDARY,
            "simulation_only": True,
            "is_real_trade": False,
        },
        "probabilityOddsMatrix": {
            "upProbability": _round_or_none(up_probability, 6),
            "riskRewardProxy": _round_or_none(risk_reward_proxy, 4),
            "expectedPathValueProxy": _round_or_none(expected_path_value, 6),
            "zone": matrix_zone,
            "xAxis": "calibrated_up_probability",
            "yAxis": "risk_reward_proxy",
            "actionBoundary": CORE_INTERPRETATION_ACTION_BOUNDARY,
            "simulation_only": True,
            "is_real_trade": False,
        },
        "actionBoundary": CORE_INTERPRETATION_ACTION_BOUNDARY,
        "simulation_only": True,
        "is_real_trade": False,
    }


def _future_primary_horizon(bottom: Dict[str, Any]) -> int:
    synthesis = _dict_or_empty(bottom.get("trendSynthesis"))
    current = _dict_or_empty(bottom.get("currentPrediction"))
    config = _dict_or_empty(bottom.get("config"))
    return _int_value(synthesis.get("primaryHorizonDays") or current.get("horizonDays") or config.get("horizon_days")) or 20


def _future_trend_forecasts(bottom: Dict[str, Any]) -> List[Dict[str, Any]]:
    forecasts = [item for item in bottom.get("horizonForecasts", []) if isinstance(item, dict)]
    if forecasts:
        return sorted(forecasts, key=lambda item: _int_value(item.get("horizonDays")) or 999)
    current = _dict_or_empty(bottom.get("currentPrediction"))
    if current:
        return [{
            "horizonDays": _future_primary_horizon(bottom),
            "status": bottom.get("status"),
            "mfeFavorableProbability": current.get("mfeFavorableProbability") or bottom.get("mfeFavorableProbability"),
            "maeBreachProbability": current.get("maeBreachProbability") or bottom.get("maeBreachProbability"),
            "bottomRepairProbability": current.get("bottomRepairProbability") or bottom.get("bottomRepairProbability"),
            "breakdownRiskProbability": current.get("breakdownRiskProbability") or bottom.get("breakdownRiskProbability"),
            "confidence": _number(_dict_or_empty(bottom.get("trendSynthesis")).get("confidence")),
            "sampleCount": _number(_dict_or_empty(bottom.get("modelDiagnostics")).get("sampleCount")),
        }]
    return []


def _raw_future_trend_probability(
    *,
    forecast: Dict[str, Any],
    bottom: Dict[str, Any],
    qiam: Dict[str, Any],
    technical: Dict[str, Any],
    dimensions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    sources: List[Dict[str, Any]] = []
    qiam_up = _number(qiam.get("probabilityBandUp"))
    qiam_down = _number(qiam.get("probabilityBandDown"))
    qiam_confidence = _number(qiam.get("modelConfidenceFinal")) or 0.55
    if qiam_up is not None and qiam_down is not None:
        sources.append(_trend_source("qiam", qiam_up, qiam_down, 0.35, qiam_confidence))

    trend_probabilities = _dict_or_empty(forecast.get("trendProbabilities"))
    mfe_up = _number(trend_probabilities.get("up"))
    mfe_down = _number(trend_probabilities.get("down"))
    if mfe_up is None or mfe_down is None:
        repair = _number(
            forecast.get("mfeFavorableProbability")
            if forecast.get("mfeFavorableProbability") is not None
            else forecast.get("bottomRepairProbability")
            if forecast.get("bottomRepairProbability") is not None
            else bottom.get("mfeFavorableProbability")
            if bottom.get("mfeFavorableProbability") is not None
            else bottom.get("bottomRepairProbability")
        )
        breakdown = _number(
            forecast.get("maeBreachProbability")
            if forecast.get("maeBreachProbability") is not None
            else forecast.get("breakdownRiskProbability")
            if forecast.get("breakdownRiskProbability") is not None
            else bottom.get("maeBreachProbability")
            if bottom.get("maeBreachProbability") is not None
            else bottom.get("breakdownRiskProbability")
        )
        if repair is not None and breakdown is not None:
            mfe_up, mfe_down = _mfe_mae_to_trend_probabilities(repair, breakdown)
    if mfe_up is not None and mfe_down is not None:
        sources.append(_trend_source("mfe_mae_path", mfe_up, mfe_down, 0.35, _number(forecast.get("confidence")) or 0.55))

    tech_up, tech_down, tech_confidence = _technical_trend_probability(technical)
    if tech_up is not None and tech_down is not None:
        sources.append(_trend_source("technical_kline", tech_up, tech_down, 0.20, tech_confidence))

    dimension_up, dimension_down, dimension_confidence = _dimension_trend_probability(dimensions)
    if dimension_up is not None and dimension_down is not None:
        sources.append(_trend_source("quant_core_dimensions", dimension_up, dimension_down, 0.10, dimension_confidence))

    if not sources:
        sources.append(_trend_source("neutral_fallback", 0.33, 0.33, 1.0, 0.25))

    weight_total = sum(item["effectiveWeight"] for item in sources)
    up = sum(item["up"] * item["effectiveWeight"] for item in sources) / weight_total
    down = sum(item["down"] * item["effectiveWeight"] for item in sources) / weight_total
    normalized = _normalize_trend_probability(up, down)
    confidence = sum(item["confidence"] * item["effectiveWeight"] for item in sources) / weight_total
    return {**normalized, "confidence": confidence, "sourceBreakdown": sources}


def _trend_source(name: str, up: float, down: float, weight: float, confidence: float) -> Dict[str, Any]:
    normalized = _normalize_trend_probability(up, down)
    confidence_value = _clamp(confidence, 0.0, 1.0)
    return {
        "source": name,
        "up": normalized["up"],
        "down": normalized["down"],
        "sideways": normalized["sideways"],
        "weight": round(weight, 4),
        "confidence": round(confidence_value, 4),
        "effectiveWeight": max(0.0001, weight * max(0.20, confidence_value)),
    }


def _mfe_mae_to_trend_probabilities(repair: float, breakdown: float) -> tuple[float, float]:
    up = max(0.05, 0.25 + repair * 0.50 - breakdown * 0.15)
    down = max(0.05, 0.20 + breakdown * 0.55 - repair * 0.10)
    normalized = _normalize_trend_probability(up, down)
    return normalized["up"], normalized["down"]


def _technical_trend_probability(technical: Dict[str, Any]) -> tuple[float | None, float | None, float]:
    bias = str(technical.get("technicalBias") or "").upper()
    confidence = _number(technical.get("confidence")) or 0.35
    if bias == "BULLISH":
        return 0.62, 0.18, confidence
    if bias == "BEARISH":
        return 0.18, 0.62, confidence
    if bias in {"NEUTRAL", "SIDEWAYS", "MIXED"}:
        return 0.34, 0.34, confidence
    return None, None, 0.0


def _dimension_trend_probability(dimensions: List[Dict[str, Any]]) -> tuple[float | None, float | None, float]:
    usable = [
        item
        for item in dimensions
        if item.get("key") in {"factor", "marketScenario"}
        and _number(item.get("weight")) is not None
        and (_number(item.get("weight")) or 0.0) > 0
    ]
    if not usable:
        return None, None, 0.0
    weight_total = sum((_number(item.get("weight")) or 0.0) * max(0.20, _number(item.get("confidence")) or 0.35) for item in usable)
    up = 0.0
    down = 0.0
    confidence = 0.0
    for item in usable:
        weight = (_number(item.get("weight")) or 0.0) * max(0.20, _number(item.get("confidence")) or 0.35)
        score = _number(item.get("score")) or 50.0
        up_component = _clamp(0.20 + score / 200.0, 0.05, 0.80)
        down_component = _clamp(0.70 - score / 200.0, 0.05, 0.80)
        up += up_component * weight
        down += down_component * weight
        confidence += (_number(item.get("confidence")) or 0.35) * weight
    if weight_total <= 0:
        return None, None, 0.0
    normalized = _normalize_trend_probability(up / weight_total, down / weight_total)
    return normalized["up"], normalized["down"], confidence / weight_total


def _future_probability_history(bottom: Dict[str, Any], horizon_days: int) -> List[Dict[str, Any]]:
    horizon_series = bottom.get("horizonProbabilitySeries") if isinstance(bottom.get("horizonProbabilitySeries"), list) else []
    for item in horizon_series:
        if isinstance(item, dict) and _int_value(item.get("horizonDays")) == horizon_days and isinstance(item.get("series"), list):
            return [row for row in item["series"] if isinstance(row, dict)]
    if isinstance(bottom.get("probabilitySeries"), list):
        return [row for row in bottom["probabilitySeries"] if isinstance(row, dict) and (_int_value(row.get("horizonDays")) in {0, horizon_days})]
    return []


def _calibrate_future_trend_probability(
    *,
    history: List[Dict[str, Any]],
    raw_up: float,
    raw_down: float,
) -> Dict[str, Any]:
    labeled = [
        item
        for item in history
        if str(item.get("labelStatus") or "LABELED_HISTORICAL").upper() == "LABELED_HISTORICAL"
        and _number(item.get("actualUpLabel")) is not None
        and _number(item.get("actualDownLabel")) is not None
    ]
    sample_count = len(labeled)
    horizon = _int_value(labeled[-1].get("horizonDays")) if labeled else 0
    up_pairs = [(_history_prediction_probability(item, "up"), int(_number(item.get("actualUpLabel")) or 0)) for item in labeled]
    down_pairs = [(_history_prediction_probability(item, "down"), int(_number(item.get("actualDownLabel")) or 0)) for item in labeled]
    up_pairs = [(prob, label) for prob, label in up_pairs if prob is not None]
    down_pairs = [(prob, label) for prob, label in down_pairs if prob is not None]
    brier_up = _brier_score(up_pairs)
    brier_down = _brier_score(down_pairs)
    up_bins = _reliability_bins(up_pairs)
    down_bins = _reliability_bins(down_pairs)
    status = "READY" if sample_count >= FUTURE_TREND_MIN_CALIBRATION_SAMPLES else "INSUFFICIENT_SAMPLE"
    if status != "READY":
        up_adjustment = 0.0
        down_adjustment = 0.0
        confidence_multiplier = 0.75
    else:
        up_adjustment = _reliability_adjustment(up_bins, raw_up, sample_count)
        down_adjustment = _reliability_adjustment(down_bins, raw_down, sample_count)
        confidence_multiplier = 1.0
    return {
        "horizonDays": horizon,
        "status": status,
        "sampleCount": sample_count,
        "brierUp": brier_up,
        "brierDown": brier_down,
        "reliabilityBins": {"up": up_bins, "down": down_bins},
        "upAdjustment": round(up_adjustment, 6),
        "downAdjustment": round(down_adjustment, 6),
        "calibratedUpProbability": _clamp(raw_up + up_adjustment, 0.01, 0.94),
        "calibratedDownProbability": _clamp(raw_down + down_adjustment, 0.01, 0.94),
        "confidenceMultiplier": confidence_multiplier,
    }


def _history_prediction_probability(item: Dict[str, Any], direction: str) -> float | None:
    if direction == "up":
        value = _number(item.get("predictionUpProbability"))
        if value is not None:
            return _clamp(value, 0.0, 1.0)
    else:
        value = _number(item.get("predictionDownProbability"))
        if value is not None:
            return _clamp(value, 0.0, 1.0)
    repair = _number(item.get("predictionRepairProb") if item.get("predictionRepairProb") is not None else item.get("repairProb"))
    breakdown = _number(item.get("predictionBreakdownRisk") if item.get("predictionBreakdownRisk") is not None else item.get("breakdownRisk"))
    if repair is None or breakdown is None:
        return None
    up, down = _mfe_mae_to_trend_probabilities(repair, breakdown)
    return up if direction == "up" else down


def _brier_score(pairs: List[tuple[float, int]]) -> float | None:
    if not pairs:
        return None
    return round(sum((prob - label) ** 2 for prob, label in pairs) / len(pairs), 6)


def _reliability_bins(pairs: List[tuple[float, int]]) -> List[Dict[str, Any]]:
    bins: List[Dict[str, Any]] = []
    for index in range(5):
        low = index / 5.0
        high = (index + 1) / 5.0
        current = [(prob, label) for prob, label in pairs if prob >= low and (prob < high or index == 4)]
        count = len(current)
        if count:
            predicted = sum(prob for prob, _ in current) / count
            actual = (sum(label for _, label in current) + 1.0) / (count + 2.0)
        else:
            predicted = (low + high) / 2.0
            actual = None
        bins.append({
            "bin": f"{low:.1f}-{high:.1f}",
            "count": count,
            "predictedMean": round(predicted, 6),
            "actualRate": round(actual, 6) if actual is not None else None,
        })
    return bins


def _reliability_adjustment(bins: List[Dict[str, Any]], raw_probability: float, sample_count: int) -> float:
    candidates = [item for item in bins if item.get("actualRate") is not None and int(item.get("count") or 0) > 0]
    if not candidates:
        return 0.0
    selected = min(candidates, key=lambda item: abs(float(item["predictedMean"]) - raw_probability))
    raw_adjustment = float(selected["actualRate"]) - float(selected["predictedMean"])
    shrinkage = sample_count / (sample_count + 40.0)
    return _clamp(raw_adjustment * shrinkage, -FUTURE_TREND_MAX_ADJUSTMENT, FUTURE_TREND_MAX_ADJUSTMENT)


def _normalize_trend_probability(up: float, down: float) -> Dict[str, float]:
    up_value = _clamp(float(up), 0.01, 0.94)
    down_value = _clamp(float(down), 0.01, 0.94)
    total_directional = up_value + down_value
    if total_directional > 0.95:
        scale = 0.95 / total_directional
        up_value *= scale
        down_value *= scale
    sideways = _clamp(1.0 - up_value - down_value, 0.05, 0.98)
    total = up_value + down_value + sideways
    return {
        "up": round(up_value / total, 6),
        "down": round(down_value / total, 6),
        "sideways": round(sideways / total, 6),
    }


def _signalops_policy_hint(points: List[Dict[str, Any]]) -> str:
    primary = points[0] if points else {}
    up = _number(primary.get("calibratedUpProbability")) or 0.0
    down = _number(primary.get("calibratedDownProbability")) or 0.0
    status = str(primary.get("calibrationStatus") or "").upper()
    if status != "READY":
        return "REVIEW_SIMULATION_ONLY_INSUFFICIENT_CALIBRATION"
    if down >= up + 0.12:
        return "SIMULATION_REDUCE_OR_REVIEW_ONLY"
    if up >= down + 0.18:
        return "SIMULATION_CONFIDENCE_SUPPORT_ONLY"
    return "SIMULATION_NEUTRAL_REVIEW"


def _probability_odds_zone(
    *,
    up_probability: float | None,
    down_probability: float | None,
    risk_reward_proxy: float | None,
    downside_risk_score: float | None,
    risk_policy: str,
    path_status: str,
) -> str:
    if path_status != "READY" or up_probability is None or down_probability is None or risk_reward_proxy is None:
        return "INSUFFICIENT_DATA"
    if risk_policy == "AVOID_NEW_BUY" or (downside_risk_score is not None and downside_risk_score >= 75):
        return "FILTER"
    if down_probability >= up_probability + 0.12 or risk_reward_proxy < 1.0:
        return "FILTER"
    if up_probability >= 0.58 and risk_reward_proxy >= 1.8 and (downside_risk_score is None or downside_risk_score < 60):
        return "PRIORITY"
    return "WATCH"


def _qiam_bias(final_buy: str) -> str:
    if final_buy == "FAVORABLE":
        return "BULLISH"
    if final_buy == "BLOCK_BUY":
        return "BEARISH"
    return "SIDEWAYS" if final_buy == "NEUTRAL" else "MIXED"


def _technical_bias(bias: str) -> str:
    if bias == "BULLISH":
        return "BULLISH"
    if bias == "BEARISH":
        return "BEARISH"
    return "SIDEWAYS"


def _bottom_bias(trend_bias: str, repair: float, breakdown: float) -> str:
    if trend_bias in {"UP", "BULLISH", "UPWARD_ALIGNED"}:
        return "BULLISH"
    if trend_bias in {"DOWN", "BEARISH", "DOWNWARD_ALIGNED"}:
        return "BEARISH"
    if repair >= 0.65 and breakdown <= 0.35:
        return "BULLISH"
    if breakdown >= 0.55:
        return "BEARISH"
    return "SIDEWAYS"


def _dict_or_empty(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().rstrip("%")) / (100.0 if value.strip().endswith("%") else 1.0)
        except ValueError:
            return None
    return None


def _first_number(*values: Any) -> float | None:
    for value in values:
        number = _number(value)
        if number is not None:
            return number
    return None


def _round_or_none(value: Any, digits: int) -> float | None:
    number = _number(value)
    return round(number, digits) if number is not None else None


def _int_value(value: Any) -> int:
    number = _number(value)
    return int(number) if number is not None else 0


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _as_text_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _display_number(value: Any) -> str:
    number = _number(value)
    return f"{number:.2f}" if number is not None else "UNKNOWN"


def _display_percent(value: Any) -> str:
    number = _number(value)
    return f"{number:.0%}" if number is not None else "UNKNOWN"


def _record_legacy_result(
    legacy_results: Dict[str, Dict[str, Any]],
    legacy_agent_outputs: Dict[str, Dict[str, Any]],
    result: AgentResult,
    key: str,
) -> None:
    legacy_results[key] = _quant_core_legacy_payload(result.to_dict())
    legacy_agent_outputs[key] = _quant_core_legacy_payload(dict(result.data or {}))


def _quant_core_legacy_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    marked = dict(payload)
    marked["legacyCompatibilityOnly"] = True
    marked["canonicalNode"] = "quant_core"
    marked["activeNode"] = False
    return marked


def _apply_market_technical_context(context: Dict[str, Any], outputs: Dict[str, Any], data: Dict[str, Any]) -> None:
    context["marketTechnical"] = data
    outputs["market_technical_analyst"] = data
    market = data.get("market") if isinstance(data.get("market"), dict) else {}
    if market:
        context["market"] = {**(context.get("market") if isinstance(context.get("market"), dict) else {}), **market}
        outputs["market_regime"] = market
    technical = data.get("technicalKline") if isinstance(data.get("technicalKline"), dict) else {}
    if technical:
        context["technicalKline"] = {
            **(context.get("technicalKline") if isinstance(context.get("technicalKline"), dict) else {}),
            **technical,
        }
        outputs["technical_kline_analyst"] = technical


def _apply_context_value(
    context: Dict[str, Any],
    outputs: Dict[str, Any],
    context_key: str,
    output_key: str,
    data: Dict[str, Any],
) -> None:
    current = context.get(context_key) if isinstance(context.get(context_key), dict) else {}
    context[context_key] = {**current, **(data or {})}
    outputs[output_key] = context[context_key]


def _apply_qiam_context(context: Dict[str, Any], outputs: Dict[str, Any], data: Dict[str, Any]) -> None:
    _apply_context_value(context, outputs, "qiam", "quant_engine", data)
    outputs["qiam"] = context["qiam"]
    quant_engine = context.get("quantEngine") if isinstance(context.get("quantEngine"), dict) else {}
    if data.get("quantEngineMode"):
        quant_engine["mode"] = data["quantEngineMode"]
    if data.get("parameterProfile"):
        quant_engine["parameterProfile"] = data["parameterProfile"]
    if "ignoredMissingData" in data:
        quant_engine["ignoredMissingData"] = list(data.get("ignoredMissingData") or [])
    context["quantEngine"] = quant_engine


def _fast_mode_scenario_skip() -> AgentResult:
    return AgentResult(
        node="scenario_engine",
        status="SKIPPED",
        confidence="LOW",
        reasons=["Scenario Engine is not enabled in FAST_MODE."],
        warnings=["scenario_engine_disabled_in_fast_mode"],
        data={
            "agent": "scenario_engine",
            "status": "SKIPPED",
            "calculationMode": "NOT_AVAILABLE",
            "dvgPermission": "NOT_RUN_IN_FAST_MODE",
            "technicalInvalidationScenarios": [],
            "warnings": ["scenario_engine_disabled_in_fast_mode"],
        },
        skipped_reason="Scenario Engine does not run in FAST_MODE.",
    )


def _aggregate_status(component_results: Dict[str, AgentResult], run_mode: str) -> str:
    statuses = {
        key: str(result.status or "WARN").upper()
        for key, result in component_results.items()
    }
    if any(status in {"FAILED", "FAIL", "ERROR", "BLOCK"} for status in statuses.values()):
        return "WARN"
    if any(status == "REVIEW_ONLY" for status in statuses.values()):
        return "REVIEW_ONLY"
    ignored_skips = {"bottomResearch", "scenario"} if run_mode == "FAST_MODE" else set()
    material_statuses = [
        status
        for key, status in statuses.items()
        if not (key in ignored_skips and status == "SKIPPED")
    ]
    if any(status in {"WARN", "SKIPPED"} for status in material_statuses):
        return "WARN"
    return "PASS"


def _collect(results: Any, attr: str) -> List[Any]:
    values: List[Any] = []
    for result in results:
        current = getattr(result, attr, [])
        if isinstance(current, list):
            values.extend(current)
    return values


def _unique(values: List[Any]) -> List[Any]:
    result: List[Any] = []
    seen: set[str] = set()
    for value in values:
        key = str(value)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result
