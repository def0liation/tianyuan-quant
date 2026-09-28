from __future__ import annotations

import copy
import hashlib
import json
from statistics import mean, pstdev
from typing import Any, Dict, List, Tuple


PERIODS = ("daily", "weekly", "monthly")

TECHNICAL_KLINE_AGENT_PROMPT = """# Technical Kline Analyst Agent

你是技术面 K 线分析 Agent，只解释真实 Tushare K 线数据反映出的价格结构。

硬性规则：
1. 只能使用 provider=tushare、dataMode=LIVE、status=READY 的日线/周线/月线 K 线。
2. 如果日线少于 30 条，必须输出 SKIPPED 与 INSUFFICIENT_DATA，不得生成技术面结论。
3. 如果无法获取真实 K 线，不得补 mock、不得随机生成、不得用模板值代替。
4. 只能输出技术面偏向、风险、支撑阻力、量价关系、Tushare 筹码接口解读或筹码成本代理和数据质量，不得输出 BUY、SELL、ADD、REDUCE、追涨、下单等交易动作。
5. 周线少于 6 条或月线少于 3 条时，只能降低置信度，不能伪造多周期共振。
6. 成交量缺失超过 30% 时，禁止做量价背离或放量缩量判断。
7. 所有结论必须能追溯到输入字段：open/high/low/close/volume/tradeDate，或 Tushare cyq_perf/cyq_chips 字段。
8. 筹码分析优先使用 Tushare cyq_perf/cyq_chips；不可用时才降级为 K 线成交量价格代理。必须标明数据来源，不得判断主力控盘或封单强弱。

输出必须是严格 JSON：
{
  "agent": "technical_kline_analyst",
  "status": "PASS|WARN|SKIPPED",
  "technicalBias": "BULLISH|NEUTRAL|BEARISH|INSUFFICIENT_DATA",
  "confidence": 0.0,
  "dataQuality": {
    "provider": "tushare",
    "dataMode": "LIVE|UNAVAILABLE",
    "dailyCount": 0,
    "weeklyCount": 0,
    "monthlyCount": 0,
    "volumeMissingRatio": 0.0,
    "issues": []
  },
  "trend": {
    "close": 0.0,
    "ma5": 0.0,
    "ma10": 0.0,
    "ma20": 0.0,
    "return20d": 0.0,
    "structure": ""
  },
  "volumePrice": {
    "status": "AVAILABLE|UNAVAILABLE",
    "volumeRatio5v20": 0.0,
    "description": ""
  },
  "supportResistance": {
    "support20d": 0.0,
    "resistance20d": 0.0,
    "support60d": 0.0,
    "resistance60d": 0.0,
    "distanceToSupport20d": 0.0,
    "distanceToResistance20d": 0.0
  },
  "technicalIndicators": {
    "macd": {"status": "AVAILABLE|UNAVAILABLE", "window": "EMA12/EMA26/DEA9", "sampleCount": 0, "dif": 0.0, "dea": 0.0, "histogram": 0.0, "signal": ""},
    "rsi": {"status": "AVAILABLE|UNAVAILABLE", "window": 14, "sampleCount": 0, "value": 0.0, "signal": ""},
    "kdj": {"status": "AVAILABLE|UNAVAILABLE", "window": 9, "sampleCount": 0, "k": 0.0, "d": 0.0, "j": 0.0, "signal": ""},
    "bollinger": {"status": "AVAILABLE|UNAVAILABLE", "window": 20, "sampleCount": 0, "mid": 0.0, "upper": 0.0, "lower": 0.0, "bandwidth": 0.0, "position": 0.0, "signal": ""}
  },
  "patterns": {
    "status": "AVAILABLE|UNAVAILABLE|NONE",
    "sampleCount": 0,
    "items": [{"code": "", "label": "", "severity": "INFO|WARN", "description": ""}]
  },
  "chipAnalysis": {
    "status": "AVAILABLE|UNAVAILABLE",
    "source": "TUSHARE_CYQ_CHIPS|TUSHARE_CYQ_PERF|KLINE_VOLUME_PRICE_PROXY|UNAVAILABLE",
    "sourceKind": "C|I|U",
    "sampleCount": 0,
    "tradeDate": "",
    "averageCostProxy": 0.0,
    "closeToCostPct": 0.0,
    "winnerRate": 0.0,
    "costPercentiles": {"cost5Pct": 0.0, "cost15Pct": 0.0, "cost50Pct": 0.0, "cost85Pct": 0.0, "cost95Pct": 0.0},
    "costZone": {"low": 0.0, "high": 0.0, "volumeRatio": 0.0},
    "overheadVolumeRatio": 0.0,
    "supportVolumeRatio": 0.0,
    "distributionSample": [{"price": 0.0, "percent": 0.0}],
    "concentrationLevel": "HIGH|MEDIUM|LOW|UNKNOWN",
    "pressureLevel": "HIGH|MEDIUM|LOW|UNKNOWN",
    "supportLevel": "HIGH|MEDIUM|LOW|UNKNOWN",
    "signal": "",
    "description": "",
    "warnings": []
  },
  "risks": [],
  "forbiddenActions": ["BUY", "SELL", "ADD", "REDUCE", "CHASE", "AUTO_ORDER"],
  "summaryForDownstream": ""
}
"""

TECHNICAL_KLINE_PROMPT_VERSION = "technical-kline-prompt-v1.3"
TECHNICAL_KLINE_PROMPT_CHANGED_BY = "codex"
TECHNICAL_KLINE_PROMPT_CHANGE_REASON = "Prefer Tushare cyq chip APIs before inferred K-line chip proxy without trade actions."
TECHNICAL_KLINE_PROMPT_ROLLBACK_VERSION = "technical-kline-prompt-v1.0"
TECHNICAL_KLINE_CASE_CLASSIFICATIONS = {"valid", "misjudge", "insufficient_data"}

DEFAULT_TECHNICAL_KLINE_CONFIG: Dict[str, Any] = {
    "version": "technical-kline-config-v1",
    "minimumSamples": {"daily": 30, "weekly": 6, "monthly": 3},
    "movingAverageWindows": {"short": 5, "medium": 10, "long": 20},
    "volumeWindows": {"recent": 5, "baseline": 20},
    "supportResistanceWindows": {"short": 20, "long": 60},
    "riskThresholds": {
        "bullishReturn20d": 0.05,
        "bearishReturn20d": -0.05,
        "clearBearishReturn20d": -0.08,
        "nearSupportDistance": 0.025,
        "nearResistanceDistance": 0.025,
        "highVolumeRatio": 1.25,
        "lowVolumeRatio": 0.75,
        "volumePriceReturn": 0.03,
    },
}


def build_technical_kline_analysis(
    symbol: str,
    payloads: Dict[str, Dict[str, Any]],
    config: Dict[str, Any] | None = None,
    chip_payload: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    analysis_config = _analysis_config(config)
    prompt_governance = _prompt_governance()
    rows_by_period = {period: _rows(payloads.get(period)) for period in PERIODS}
    quality = _data_quality(payloads, rows_by_period, analysis_config)
    daily_rows = rows_by_period["daily"]
    min_daily = int(analysis_config["minimumSamples"]["daily"])

    if not _is_live_payload(payloads.get("daily")) or len(daily_rows) < min_daily:
        case_detail = _case_classification_detail("insufficient_data", "RULE_DERIVED", quality.get("issues", []))
        return {
            "agent": "technical_kline_analyst",
            "symbol": symbol,
            "status": "SKIPPED",
            "technicalBias": "INSUFFICIENT_DATA",
            "confidence": 0.0,
            "dataQuality": quality,
            "trend": {},
            "volumePrice": {"status": "UNAVAILABLE", "volumeRatio5v20": None, "description": "真实日线不足 30 条，技术面分析已跳过。"},
            "supportResistance": {},
            "technicalIndicators": _empty_indicators(len(daily_rows)),
            "patterns": _empty_patterns(len(daily_rows)),
            "chipAnalysis": _empty_chip_analysis(len(daily_rows), "真实日线不足，未生成筹码成本代理。"),
            "multiPeriod": _multi_period(rows_by_period),
            "risks": ["真实 Tushare 日线数据不足，禁止生成 K 线技术结论。"],
            "forbiddenActions": _forbidden_actions(),
            "summaryForDownstream": "K 线技术面 Agent 已跳过：真实日线不足 30 条或数据源不可用。",
            "promptGovernance": prompt_governance,
            "analysisConfig": analysis_config,
            "caseClassification": case_detail["classification"],
            "caseClassificationDetail": case_detail,
            "prompt": TECHNICAL_KLINE_AGENT_PROMPT,
        }

    trend = _trend(daily_rows, analysis_config)
    volume_price = _volume_price(daily_rows, quality["volumeMissingRatio"], analysis_config)
    support_resistance = _support_resistance(daily_rows, analysis_config)
    technical_indicators = _technical_indicators(daily_rows)
    patterns = _patterns(daily_rows, volume_price, analysis_config)
    chip_analysis = _chip_analysis_from_tushare(chip_payload, daily_rows) or _chip_analysis(daily_rows, quality["volumeMissingRatio"])
    multi_period = _multi_period(rows_by_period)
    risks = _risks(trend, volume_price, support_resistance, technical_indicators, patterns, quality, analysis_config)
    bias, score = _bias(trend, multi_period, analysis_config)
    confidence = _confidence(score, quality, multi_period)

    status = "PASS"
    if quality["issues"] or risks:
        status = "WARN"
    if bias == "BEARISH":
        status = "WARN"
    case_detail = _case_classification_detail(
        _case_classification(status, quality, config),
        "CONFIG_OVERRIDE" if _case_classification_override(config) else "RULE_DERIVED",
        quality.get("issues", []),
    )

    return {
        "agent": "technical_kline_analyst",
        "symbol": symbol,
        "status": status,
        "technicalBias": bias,
        "confidence": confidence,
        "dataQuality": quality,
        "trend": trend,
        "volumePrice": volume_price,
        "supportResistance": support_resistance,
        "technicalIndicators": technical_indicators,
        "patterns": patterns,
        "chipAnalysis": chip_analysis,
        "multiPeriod": multi_period,
        "risks": risks,
        "forbiddenActions": _forbidden_actions(),
        "summaryForDownstream": _summary(bias, confidence, trend, volume_price, support_resistance, technical_indicators, patterns, chip_analysis),
        "promptGovernance": prompt_governance,
        "analysisConfig": analysis_config,
        "caseClassification": case_detail["classification"],
        "caseClassificationDetail": case_detail,
        "prompt": TECHNICAL_KLINE_AGENT_PROMPT,
    }


def build_technical_signal_backtest(
    symbol: str,
    payloads: Dict[str, Dict[str, Any]],
    horizon_days: int = 5,
) -> Dict[str, Any]:
    rows_by_period = {period: _rows(payloads.get(period)) for period in PERIODS}
    daily_rows = rows_by_period["daily"]
    horizon_days = max(1, min(int(horizon_days or 5), 20))
    min_sample = 30
    required_count = min_sample + horizon_days

    if not _is_live_payload(payloads.get("daily")) or len(daily_rows) < required_count:
        return {
            "agent": "technical_kline_analyst",
            "symbol": symbol,
            "status": "SKIPPED",
            "horizonDays": horizon_days,
            "sampleCount": len(daily_rows),
            "requiredCount": required_count,
            "totalObservations": 0,
            "evaluatedSignals": 0,
            "neutralSkipped": 0,
            "hitRate": None,
            "averageForwardReturn": None,
            "byBias": _empty_backtest_buckets(),
            "recentSignals": [],
            "dataPolicy": "REAL_TUSHARE_KLINE_ONLY",
            "tradeActionPolicy": "NO_DIRECT_TRADE_ACTION",
            "summary": f"真实日线少于 {required_count} 条，技术面信号回测已跳过。",
        }

    evaluations: List[Dict[str, Any]] = []
    neutral_skipped = 0
    total_observations = max(0, len(daily_rows) - horizon_days - min_sample + 1)
    neutral_multi_period = {"weeklyReturn": None, "monthlyReturn": None, "alignment": "UNKNOWN"}

    for index in range(min_sample - 1, len(daily_rows) - horizon_days):
        sample = daily_rows[: index + 1]
        trend = _trend(sample)
        bias, score = _bias(trend, neutral_multi_period)
        if bias not in {"BULLISH", "BEARISH"}:
            neutral_skipped += 1
            continue

        close = _number(sample[-1].get("close")) or 0.0
        future_close = _number(daily_rows[index + horizon_days].get("close")) or 0.0
        if close <= 0 or future_close <= 0:
            continue

        forward_return = (future_close - close) / close
        hit = forward_return > 0 if bias == "BULLISH" else forward_return < 0
        confidence = _confidence(
            score,
            {
                "dailyCount": len(sample),
                "weeklyCount": 0,
                "monthlyCount": 0,
                "volumeMissingRatio": 0.0,
                "issues": [],
            },
            neutral_multi_period,
        )
        evaluations.append(
            {
                "tradeDate": str(sample[-1].get("tradeDate") or ""),
                "bias": bias,
                "confidence": confidence,
                "close": round(close, 4),
                "futureClose": round(future_close, 4),
                "forwardReturn": round(forward_return, 4),
                "hit": hit,
                "basis": trend.get("structure", ""),
            }
        )

    hit_rate = _hit_rate(evaluations)
    average_return = _average_forward_return(evaluations)
    return {
        "agent": "technical_kline_analyst",
        "symbol": symbol,
        "status": "PASS" if evaluations else "WARN",
        "horizonDays": horizon_days,
        "sampleCount": len(daily_rows),
        "requiredCount": required_count,
        "totalObservations": total_observations,
        "evaluatedSignals": len(evaluations),
        "neutralSkipped": neutral_skipped,
        "hitRate": hit_rate,
        "averageForwardReturn": average_return,
        "byBias": _backtest_buckets(evaluations),
        "recentSignals": evaluations[-12:],
        "dataPolicy": "REAL_TUSHARE_KLINE_ONLY",
        "tradeActionPolicy": "NO_DIRECT_TRADE_ACTION",
        "summary": _backtest_summary(len(evaluations), hit_rate, average_return, horizon_days),
    }


def build_technical_kline_governance(config: Dict[str, Any] | None = None) -> Dict[str, Any]:
    analysis_config = _analysis_config(config)
    return {
        "agent": "technical_kline_analyst",
        "promptGovernance": _prompt_governance(),
        "analysisConfig": analysis_config,
        "caseClassification": {
            "allowedValues": sorted(TECHNICAL_KLINE_CASE_CLASSIFICATIONS),
            "selected": _case_classification_override(config) or "rule_derived",
        },
        "dataPolicy": "REAL_TUSHARE_KLINE_ONLY",
        "tradeActionPolicy": "NO_DIRECT_TRADE_ACTION",
    }


def _rows(payload: Dict[str, Any] | None) -> List[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    raw_rows = payload.get("rows")
    if not isinstance(raw_rows, list):
        return []
    rows = [row for row in raw_rows if isinstance(row, dict) and _number(row.get("close")) is not None]
    rows.sort(key=lambda row: str(row.get("tradeDate") or ""))
    return rows


def _is_live_payload(payload: Dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    return (
        payload.get("status") == "READY"
        and payload.get("dataMode") == "LIVE"
        and payload.get("provider") == "tushare"
        and isinstance(payload.get("rows"), list)
        and len(payload.get("rows") or []) > 0
    )


def _data_quality(
    payloads: Dict[str, Dict[str, Any]],
    rows_by_period: Dict[str, List[Dict[str, Any]]],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    daily_rows = rows_by_period["daily"]
    minimums = config["minimumSamples"]
    volume_missing = 0.0
    if daily_rows:
        missing = sum(1 for row in daily_rows if _number(row.get("volume")) in (None, 0.0))
        volume_missing = round(missing / len(daily_rows), 4)

    issues: List[str] = []
    if not _is_live_payload(payloads.get("daily")):
        issues.append("日线真实数据不可用")
    if len(daily_rows) < int(minimums["daily"]):
        issues.append("日线少于 30 条")
    if not _is_live_payload(payloads.get("weekly")) or len(rows_by_period["weekly"]) < int(minimums["weekly"]):
        issues.append("周线不足 6 条，多周期置信度降低")
    if not _is_live_payload(payloads.get("monthly")) or len(rows_by_period["monthly"]) < int(minimums["monthly"]):
        issues.append("月线不足 3 条，多周期置信度降低")
    if volume_missing > 0.3:
        issues.append("成交量缺失超过 30%，禁用量价判断")

    return {
        "provider": "tushare",
        "dataMode": "LIVE" if _is_live_payload(payloads.get("daily")) else "UNAVAILABLE",
        "dailyCount": len(daily_rows),
        "weeklyCount": len(rows_by_period["weekly"]),
        "monthlyCount": len(rows_by_period["monthly"]),
        "volumeMissingRatio": volume_missing,
        "periodStatus": {
            period: {
                "status": (payloads.get(period) or {}).get("status", "FAILED"),
                "dataMode": (payloads.get(period) or {}).get("dataMode", "UNAVAILABLE"),
                "recordCount": len(rows_by_period[period]),
                "apiName": (payloads.get(period) or {}).get("apiName", period),
            }
            for period in PERIODS
        },
        "issues": issues,
    }


def _trend(rows: List[Dict[str, Any]], config: Dict[str, Any] | None = None) -> Dict[str, Any]:
    config = _analysis_config(config)
    ma_windows = config["movingAverageWindows"]
    short_window = int(ma_windows["short"])
    medium_window = int(ma_windows["medium"])
    long_window = int(ma_windows["long"])
    support_long_window = int(config["supportResistanceWindows"]["long"])
    close = _number(rows[-1].get("close")) or 0.0
    ma5 = _ma(rows, short_window)
    ma10 = _ma(rows, medium_window)
    ma20 = _ma(rows, long_window)
    return20d = _period_return(rows, long_window)
    return60d = _period_return(rows, min(support_long_window, len(rows) - 1))

    if close > ma5 > ma10 > ma20 and return20d > 0:
        structure = "短中期均线多头排列，价格在主要均线上方。"
    elif close < ma5 < ma10 < ma20 and return20d < 0:
        structure = "短中期均线空头排列，价格在主要均线下方。"
    elif close >= ma20:
        structure = "价格仍在 20 日均线上方，但均线结构未形成强趋势。"
    else:
        structure = "价格低于 20 日均线，趋势需要防守性复核。"

    return {
        "close": round(close, 4),
        "ma5": round(ma5, 4),
        "ma10": round(ma10, 4),
        "ma20": round(ma20, 4),
        "return20d": round(return20d, 4),
        "return60d": round(return60d, 4),
        "windows": {
            "maShort": short_window,
            "maMedium": medium_window,
            "maLong": long_window,
            "returnLong": long_window,
        },
        "structure": structure,
    }


def _volume_price(
    rows: List[Dict[str, Any]],
    volume_missing_ratio: float,
    config: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    config = _analysis_config(config)
    volume_windows = config["volumeWindows"]
    thresholds = config["riskThresholds"]
    recent_window = int(volume_windows["recent"])
    baseline_window = int(volume_windows["baseline"])
    high_volume_ratio = float(thresholds["highVolumeRatio"])
    low_volume_ratio = float(thresholds["lowVolumeRatio"])
    volume_price_return = float(thresholds["volumePriceReturn"])
    if volume_missing_ratio > 0.3:
        return {"status": "UNAVAILABLE", "volumeRatio5v20": None, "description": "成交量缺失过多，未生成量价判断。"}

    volumes = [_number(row.get("volume")) or 0.0 for row in rows]
    recent = [value for value in volumes[-recent_window:] if value > 0]
    base_start = -(recent_window + baseline_window)
    base = [value for value in volumes[base_start:-recent_window] if value > 0]
    if len(recent) < 3 or len(base) < 8:
        return {"status": "UNAVAILABLE", "volumeRatio5v20": None, "description": "成交量样本不足，未生成量价判断。"}

    ratio = mean(recent) / max(mean(base), 1.0)
    return20d = _period_return(rows, int(config["movingAverageWindows"]["long"]))
    if ratio >= high_volume_ratio and return20d > volume_price_return:
        description = "近 5 日成交量高于 20 日基准且价格上行，量价配合偏强。"
    elif ratio >= high_volume_ratio and return20d < -volume_price_return:
        description = "近 5 日放量但价格下行，存在放量承压风险。"
    elif ratio <= low_volume_ratio:
        description = "近 5 日成交量低于 20 日基准，价格信号有效性下降。"
    else:
        description = "成交量接近 20 日基准，量价信号中性。"

    return {"status": "AVAILABLE", "volumeRatio5v20": round(ratio, 4), "description": description}


def _empty_chip_analysis(sample_count: int = 0, reason: str = "成交量价格样本不足，未生成筹码成本代理。") -> Dict[str, Any]:
    return {
        "status": "UNAVAILABLE",
        "source": "UNAVAILABLE",
        "sourceKind": "U",
        "sampleCount": sample_count,
        "tradeDate": None,
        "averageCostProxy": None,
        "closeToCostPct": None,
        "winnerRate": None,
        "costPercentiles": {
            "cost5Pct": None,
            "cost15Pct": None,
            "cost50Pct": None,
            "cost85Pct": None,
            "cost95Pct": None,
        },
        "costZone": {"low": None, "high": None, "volumeRatio": None},
        "overheadVolumeRatio": None,
        "supportVolumeRatio": None,
        "distributionSample": [],
        "concentrationLevel": "UNKNOWN",
        "pressureLevel": "UNKNOWN",
        "supportLevel": "UNKNOWN",
        "signal": "UNAVAILABLE",
        "description": reason,
        "warnings": ["未接入真实筹码分布或股东户数，禁止据此判断主力控盘。"],
    }


def _chip_analysis_from_tushare(
    chip_payload: Dict[str, Any] | None,
    rows: List[Dict[str, Any]],
) -> Dict[str, Any] | None:
    if not chip_payload or chip_payload.get("status") != "READY" or not rows:
        return None

    latest_perf = chip_payload.get("latestPerf") if isinstance(chip_payload.get("latestPerf"), dict) else {}
    latest_chips = chip_payload.get("latestChips") if isinstance(chip_payload.get("latestChips"), list) else []
    close = _number(rows[-1].get("close")) or 0.0
    if close <= 0:
        return None

    average_cost = (
        _number(latest_perf.get("weightAvg"))
        or _number(latest_perf.get("cost50Pct"))
        or _weighted_chip_cost(latest_chips)
    )
    if not average_cost or average_cost <= 0:
        return None

    close_to_cost = (close - average_cost) / average_cost
    cost_percentiles = {
        "cost5Pct": _round_or_none(latest_perf.get("cost5Pct")),
        "cost15Pct": _round_or_none(latest_perf.get("cost15Pct")),
        "cost50Pct": _round_or_none(latest_perf.get("cost50Pct")),
        "cost85Pct": _round_or_none(latest_perf.get("cost85Pct")),
        "cost95Pct": _round_or_none(latest_perf.get("cost95Pct")),
    }
    cost_zone_low = _number(latest_perf.get("cost15Pct")) or average_cost * 0.97
    cost_zone_high = _number(latest_perf.get("cost85Pct")) or average_cost * 1.03
    cost_zone_ratio = _chip_distribution_ratio(latest_chips, lambda price: cost_zone_low <= price <= cost_zone_high)
    overhead_ratio = _chip_distribution_ratio(latest_chips, lambda price: price > close * 1.02)
    support_ratio = _chip_distribution_ratio(latest_chips, lambda price: price < close * 0.98)
    concentration_level = _chip_level(cost_zone_ratio, 0.45, 0.28) if cost_zone_ratio is not None else "UNKNOWN"
    pressure_level = _chip_level(overhead_ratio, 0.35, 0.18) if overhead_ratio is not None else "UNKNOWN"
    support_level = _chip_level(support_ratio, 0.4, 0.2) if support_ratio is not None else "UNKNOWN"
    winner_rate = _number(latest_perf.get("winnerRate"))
    source = "TUSHARE_CYQ_CHIPS" if latest_chips else "TUSHARE_CYQ_PERF"
    signal = _real_chip_signal(close_to_cost, overhead_ratio, support_ratio, winner_rate)
    description = _real_chip_description(
        source,
        close_to_cost,
        overhead_ratio,
        support_ratio,
        winner_rate,
    )

    return {
        "status": "AVAILABLE",
        "source": source,
        "sourceKind": "C",
        "sampleCount": len(latest_chips) or (1 if latest_perf else 0),
        "tradeDate": chip_payload.get("latestTradeDate") or latest_perf.get("tradeDate") or None,
        "averageCostProxy": round(average_cost, 4),
        "closeToCostPct": round(close_to_cost, 4),
        "winnerRate": _round_or_none(winner_rate, 4),
        "costPercentiles": cost_percentiles,
        "costZone": {
            "low": round(cost_zone_low, 4),
            "high": round(cost_zone_high, 4),
            "volumeRatio": _round_or_none(cost_zone_ratio, 4),
        },
        "overheadVolumeRatio": _round_or_none(overhead_ratio, 4),
        "supportVolumeRatio": _round_or_none(support_ratio, 4),
        "distributionSample": _chip_distribution_sample(latest_chips),
        "concentrationLevel": concentration_level,
        "pressureLevel": pressure_level,
        "supportLevel": support_level,
        "signal": signal,
        "description": description,
        "warnings": [
            "该筹码分析来自 Tushare cyq 接口参考数据，不代表绝对真实持仓。",
            "不得据此判断主力控盘或封单强弱。",
        ],
    }


def _chip_analysis(rows: List[Dict[str, Any]], volume_missing_ratio: float) -> Dict[str, Any]:
    sample = rows[-min(60, len(rows)):]
    valid_rows = [
        row
        for row in sample
        if (_number(row.get("close")) or 0.0) > 0 and (_number(row.get("volume")) or 0.0) > 0
    ]
    if volume_missing_ratio > 0.3:
        return _empty_chip_analysis(len(sample), "成交量缺失超过 30%，未生成筹码成本代理。")
    if len(valid_rows) < 20:
        return _empty_chip_analysis(len(valid_rows), "有效成交量价格样本少于 20 条，未生成筹码成本代理。")

    close = _number(rows[-1].get("close")) or 0.0
    total_volume = sum((_number(row.get("volume")) or 0.0) for row in valid_rows)
    if close <= 0 or total_volume <= 0:
        return _empty_chip_analysis(len(valid_rows))

    average_cost = sum(((_number(row.get("close")) or 0.0) * (_number(row.get("volume")) or 0.0)) for row in valid_rows) / total_volume
    close_to_cost = (close - average_cost) / average_cost if average_cost > 0 else 0.0
    cost_zone_low = average_cost * 0.97
    cost_zone_high = average_cost * 1.03
    zone_volume = sum(
        (_number(row.get("volume")) or 0.0)
        for row in valid_rows
        if cost_zone_low <= (_number(row.get("close")) or 0.0) <= cost_zone_high
    )
    overhead_volume = sum(
        (_number(row.get("volume")) or 0.0)
        for row in valid_rows
        if (_number(row.get("close")) or 0.0) > close * 1.02
    )
    support_volume = sum(
        (_number(row.get("volume")) or 0.0)
        for row in valid_rows
        if (_number(row.get("close")) or 0.0) < close * 0.98
    )

    cost_zone_ratio = zone_volume / total_volume
    overhead_ratio = overhead_volume / total_volume
    support_ratio = support_volume / total_volume
    concentration_level = _chip_level(cost_zone_ratio, 0.45, 0.28)
    pressure_level = _chip_level(overhead_ratio, 0.35, 0.18)
    support_level = _chip_level(support_ratio, 0.4, 0.2)

    if close_to_cost <= -0.05 and overhead_ratio >= 0.35:
        signal = "OVERHEAD_PRESSURE"
        description = f"收盘价低于近 {len(valid_rows)} 日成交量加权成本代理，且上方套牢量代理占比较高，反弹压力需要复核。"
    elif close_to_cost >= 0.05 and support_ratio >= 0.35:
        signal = "ABOVE_COST_WITH_SUPPORT"
        description = f"收盘价高于近 {len(valid_rows)} 日成交量加权成本代理，下方成交量代理较厚，结构支撑相对更明确。"
    elif abs(close_to_cost) <= 0.03:
        signal = "NEAR_COST_CENTER"
        description = f"收盘价贴近近 {len(valid_rows)} 日成交量加权成本代理，筹码成本代理处于均衡区，需要等待方向确认。"
    elif cost_zone_ratio < 0.28:
        signal = "LOW_CONCENTRATION"
        description = f"近 {len(valid_rows)} 日成交量价格分布较分散，筹码成本代理集中度偏低。"
    else:
        signal = "MIXED"
        description = f"近 {len(valid_rows)} 日筹码成本代理未形成单边压力或支撑，需结合趋势与量价继续复核。"

    return {
        "status": "AVAILABLE",
        "source": "KLINE_VOLUME_PRICE_PROXY",
        "sourceKind": "I",
        "sampleCount": len(valid_rows),
        "tradeDate": None,
        "averageCostProxy": round(average_cost, 4),
        "closeToCostPct": round(close_to_cost, 4),
        "winnerRate": None,
        "costPercentiles": {
            "cost5Pct": None,
            "cost15Pct": None,
            "cost50Pct": None,
            "cost85Pct": None,
            "cost95Pct": None,
        },
        "costZone": {
            "low": round(cost_zone_low, 4),
            "high": round(cost_zone_high, 4),
            "volumeRatio": round(cost_zone_ratio, 4),
        },
        "overheadVolumeRatio": round(overhead_ratio, 4),
        "supportVolumeRatio": round(support_ratio, 4),
        "distributionSample": [],
        "concentrationLevel": concentration_level,
        "pressureLevel": pressure_level,
        "supportLevel": support_level,
        "signal": signal,
        "description": description,
        "warnings": ["该筹码分析为 K 线成交量价格代理，非真实筹码分布或股东户数。", "不得据此判断主力控盘或封单强弱。"],
    }


def _chip_level(value: float, high_threshold: float, medium_threshold: float) -> str:
    if value >= high_threshold:
        return "HIGH"
    if value >= medium_threshold:
        return "MEDIUM"
    return "LOW"


def _weighted_chip_cost(chip_rows: List[Dict[str, Any]]) -> float | None:
    total_weight = 0.0
    weighted_sum = 0.0
    for row in chip_rows:
        price = _number(row.get("price"))
        percent = _chip_percent(row)
        if price is None or percent is None:
            continue
        weighted_sum += price * percent
        total_weight += percent
    if total_weight <= 0:
        return None
    return weighted_sum / total_weight


def _chip_distribution_ratio(chip_rows: List[Dict[str, Any]], predicate: Any) -> float | None:
    if not chip_rows:
        return None
    total = 0.0
    matched = 0.0
    for row in chip_rows:
        price = _number(row.get("price"))
        percent = _chip_percent(row)
        if price is None or percent is None:
            continue
        total += percent
        if predicate(price):
            matched += percent
    if total <= 0:
        return None
    return matched / total


def _chip_distribution_sample(chip_rows: List[Dict[str, Any]]) -> List[Dict[str, float]]:
    sample_rows = sorted(
        (
            {"price": _number(row.get("price")), "percent": _chip_percent(row)}
            for row in chip_rows
        ),
        key=lambda item: item.get("percent") or 0.0,
        reverse=True,
    )
    return [
        {"price": round(float(item["price"]), 4), "percent": round(float(item["percent"]), 4)}
        for item in sample_rows[:10]
        if item.get("price") is not None and item.get("percent") is not None
    ]


def _chip_percent(row: Dict[str, Any]) -> float | None:
    percent = _number(row.get("percent"))
    if percent is None:
        return None
    return percent / 100 if abs(percent) > 1 else percent


def _real_chip_signal(
    close_to_cost: float,
    overhead_ratio: float | None,
    support_ratio: float | None,
    winner_rate: float | None,
) -> str:
    if close_to_cost <= -0.05 and (overhead_ratio is None or overhead_ratio >= 0.35):
        return "TUSHARE_OVERHEAD_PRESSURE"
    if close_to_cost >= 0.05 and (support_ratio is None or support_ratio >= 0.35):
        return "TUSHARE_ABOVE_COST_WITH_SUPPORT"
    if winner_rate is not None and winner_rate <= 0.2:
        return "TUSHARE_LOW_WINNER_RATE"
    if abs(close_to_cost) <= 0.03:
        return "TUSHARE_NEAR_COST_CENTER"
    return "TUSHARE_MIXED"


def _real_chip_description(
    source: str,
    close_to_cost: float,
    overhead_ratio: float | None,
    support_ratio: float | None,
    winner_rate: float | None,
) -> str:
    source_label = "cyq_chips/cyq_perf" if source == "TUSHARE_CYQ_CHIPS" else "cyq_perf"
    parts = [f"真实 Tushare {source_label} 接口显示价格距平均成本 {close_to_cost:.1%}"]
    if winner_rate is not None:
        parts.append(f"胜率 {winner_rate:.1%}")
    if overhead_ratio is not None:
        parts.append(f"上方成本分布占比 {overhead_ratio:.1%}")
    if support_ratio is not None:
        parts.append(f"下方成本分布占比 {support_ratio:.1%}")
    if close_to_cost < -0.05:
        parts.append("价格位于平均成本下方，反弹压力需要复核")
    elif close_to_cost > 0.05:
        parts.append("价格位于平均成本上方，需继续观察支撑延续性")
    else:
        parts.append("价格贴近平均成本区，方向仍需结合趋势确认")
    return "，".join(parts) + "。"


def _round_or_none(value: Any, digits: int = 4) -> float | None:
    number = _number(value)
    if number is None:
        return None
    return round(number, digits)


def _support_resistance(rows: List[Dict[str, Any]], config: Dict[str, Any] | None = None) -> Dict[str, Any]:
    config = _analysis_config(config)
    sr_windows = config["supportResistanceWindows"]
    short_window = int(sr_windows["short"])
    long_window = int(sr_windows["long"])
    close = _number(rows[-1].get("close")) or 0.0
    last20 = rows[-short_window:]
    last60 = rows[-min(long_window, len(rows)):]
    support20 = min((_number(row.get("low")) or close) for row in last20)
    resistance20 = max((_number(row.get("high")) or close) for row in last20)
    support60 = min((_number(row.get("low")) or close) for row in last60)
    resistance60 = max((_number(row.get("high")) or close) for row in last60)

    return {
        "support20d": round(support20, 4),
        "resistance20d": round(resistance20, 4),
        "support60d": round(support60, 4),
        "resistance60d": round(resistance60, 4),
        "distanceToSupport20d": round((close - support20) / close, 4) if close else 0.0,
        "distanceToResistance20d": round((resistance20 - close) / close, 4) if close else 0.0,
        "windows": {"short": short_window, "long": long_window},
    }


def _empty_indicators(sample_count: int = 0) -> Dict[str, Any]:
    return {
        "macd": {"status": "UNAVAILABLE", "window": "EMA12/EMA26/DEA9", "sampleCount": sample_count, "dif": None, "dea": None, "histogram": None, "signal": "真实日线样本不足"},
        "rsi": {"status": "UNAVAILABLE", "window": 14, "sampleCount": sample_count, "value": None, "signal": "真实日线样本不足"},
        "kdj": {"status": "UNAVAILABLE", "window": 9, "sampleCount": sample_count, "k": None, "d": None, "j": None, "signal": "真实日线样本不足"},
        "bollinger": {"status": "UNAVAILABLE", "window": 20, "sampleCount": sample_count, "mid": None, "upper": None, "lower": None, "bandwidth": None, "position": None, "signal": "真实日线样本不足"},
    }


def _technical_indicators(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    closes = [_number(row.get("close")) or 0.0 for row in rows]
    highs = [_number(row.get("high")) or 0.0 for row in rows]
    lows = [_number(row.get("low")) or 0.0 for row in rows]
    return {
        "macd": _macd(closes),
        "rsi": _rsi(closes, 14),
        "kdj": _kdj(closes, highs, lows, 9),
        "bollinger": _bollinger(closes, 20),
    }


def _empty_patterns(sample_count: int = 0) -> Dict[str, Any]:
    return {
        "status": "UNAVAILABLE",
        "sampleCount": sample_count,
        "items": [],
    }


def _patterns(
    rows: List[Dict[str, Any]],
    volume_price: Dict[str, Any],
    config: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    config = _analysis_config(config)
    thresholds = config["riskThresholds"]
    high_volume_ratio = float(thresholds["highVolumeRatio"])
    low_volume_ratio = float(thresholds["lowVolumeRatio"])
    if len(rows) < 2:
        return _empty_patterns(len(rows))

    latest = rows[-1]
    previous = rows[-2]
    close = _number(latest.get("close")) or 0.0
    open_price = _number(latest.get("open")) or close
    high = _number(latest.get("high")) or max(open_price, close)
    low = _number(latest.get("low")) or min(open_price, close)
    previous_close = _number(previous.get("close")) or 0.0
    items: List[Dict[str, Any]] = []

    if previous_close > 0:
        gap = (open_price - previous_close) / previous_close
        if gap >= 0.02:
            items.append(_pattern_item("GAP_UP", "向上跳空", "WARN", f"最新开盘较前收盘高开 {gap:.1%}，需要确认缺口承接。"))
        elif gap <= -0.02:
            items.append(_pattern_item("GAP_DOWN", "向下跳空", "WARN", f"最新开盘较前收盘低开 {abs(gap):.1%}，短线结构承压。"))

    candle_range = max(high - low, 0.0)
    if candle_range > 0 and close > 0:
        upper_shadow = high - max(open_price, close)
        body = abs(close - open_price)
        if upper_shadow / candle_range >= 0.45 and upper_shadow / close >= 0.02 and upper_shadow > body:
            items.append(_pattern_item("LONG_UPPER_SHADOW", "长上影线", "WARN", "最新 K 线留下明显上影线，冲高回落有效性需要复核。"))

    volume_ratio = volume_price.get("volumeRatio5v20")
    return5d = _period_return(rows, min(5, len(rows) - 1))
    if isinstance(volume_ratio, (int, float)):
        if volume_ratio >= high_volume_ratio and return5d <= 0.02:
            items.append(_pattern_item("HIGH_VOLUME_STALL", "放量滞涨", "WARN", f"5 日量比 {volume_ratio:.2f}，但 5 日涨幅仅 {return5d:.1%}。"))
        elif volume_ratio <= low_volume_ratio and return5d >= 0.02:
            items.append(_pattern_item("LOW_VOLUME_REBOUND", "缩量反弹", "INFO", f"5 日量比 {volume_ratio:.2f}，价格反弹 {return5d:.1%}，反弹质量需继续观察。"))

    return {
        "status": "AVAILABLE" if items else "NONE",
        "sampleCount": len(rows),
        "items": items,
    }


def _pattern_item(code: str, label: str, severity: str, description: str) -> Dict[str, str]:
    return {
        "code": code,
        "label": label,
        "severity": severity,
        "description": description,
    }


def _macd(closes: List[float]) -> Dict[str, Any]:
    if len(closes) < 35:
        return {"status": "UNAVAILABLE", "window": "EMA12/EMA26/DEA9", "sampleCount": len(closes), "dif": None, "dea": None, "histogram": None, "signal": "MACD 需要至少 35 条真实日线"}
    ema12 = _ema_series(closes, 12)
    ema26 = _ema_series(closes, 26)
    dif_series = [fast - slow for fast, slow in zip(ema12, ema26)]
    dea_series = _ema_series(dif_series, 9)
    dif = dif_series[-1]
    dea = dea_series[-1]
    histogram = (dif - dea) * 2
    if dif > dea and histogram > 0:
        signal = "MACD 动能偏强"
    elif dif < dea and histogram < 0:
        signal = "MACD 动能偏弱"
    else:
        signal = "MACD 动能收敛"
    return {
        "status": "AVAILABLE",
        "window": "EMA12/EMA26/DEA9",
        "sampleCount": len(closes),
        "dif": round(dif, 4),
        "dea": round(dea, 4),
        "histogram": round(histogram, 4),
        "signal": signal,
    }


def _rsi(closes: List[float], window: int) -> Dict[str, Any]:
    if len(closes) < window + 1:
        return {"status": "UNAVAILABLE", "window": window, "sampleCount": len(closes), "value": None, "signal": f"RSI{window} 需要至少 {window + 1} 条真实日线"}
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    sample = changes[-window:]
    gains = [max(value, 0.0) for value in sample]
    losses = [abs(min(value, 0.0)) for value in sample]
    avg_gain = mean(gains)
    avg_loss = mean(losses)
    value = 100.0 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss))
    if value >= 70:
        signal = "RSI 偏热，追高有效性需复核"
    elif value <= 30:
        signal = "RSI 偏冷，弱势或超卖需结合趋势复核"
    else:
        signal = "RSI 处于中性区间"
    return {"status": "AVAILABLE", "window": window, "sampleCount": len(closes), "value": round(value, 2), "signal": signal}


def _kdj(closes: List[float], highs: List[float], lows: List[float], window: int) -> Dict[str, Any]:
    if len(closes) < window:
        return {"status": "UNAVAILABLE", "window": window, "sampleCount": len(closes), "k": None, "d": None, "j": None, "signal": f"KDJ{window} 需要至少 {window} 条真实日线"}
    k = 50.0
    d = 50.0
    for index in range(window - 1, len(closes)):
        low_window = min(lows[index - window + 1:index + 1])
        high_window = max(highs[index - window + 1:index + 1])
        rsv = 50.0 if high_window <= low_window else ((closes[index] - low_window) / (high_window - low_window)) * 100
        k = (2 / 3) * k + (1 / 3) * rsv
        d = (2 / 3) * d + (1 / 3) * k
    j = 3 * k - 2 * d
    if k > d and j >= 80:
        signal = "KDJ 高位偏强，需防波动"
    elif k < d and j <= 20:
        signal = "KDJ 低位偏弱，需防延续下探"
    elif k > d:
        signal = "KDJ 金叉结构"
    elif k < d:
        signal = "KDJ 死叉结构"
    else:
        signal = "KDJ 中性"
    return {"status": "AVAILABLE", "window": window, "sampleCount": len(closes), "k": round(k, 2), "d": round(d, 2), "j": round(j, 2), "signal": signal}


def _bollinger(closes: List[float], window: int) -> Dict[str, Any]:
    if len(closes) < window:
        return {"status": "UNAVAILABLE", "window": window, "sampleCount": len(closes), "mid": None, "upper": None, "lower": None, "bandwidth": None, "position": None, "signal": f"布林带需要至少 {window} 条真实日线"}
    sample = closes[-window:]
    mid = mean(sample)
    deviation = pstdev(sample)
    upper = mid + 2 * deviation
    lower = mid - 2 * deviation
    close = closes[-1]
    width = upper - lower
    position = (close - lower) / width if width > 0 else 0.5
    bandwidth = width / mid if mid else 0.0
    if position >= 0.85:
        signal = "价格接近布林上轨，追高需复核"
    elif position <= 0.15:
        signal = "价格接近布林下轨，弱势风险需复核"
    else:
        signal = "价格位于布林通道中部"
    return {
        "status": "AVAILABLE",
        "window": window,
        "sampleCount": len(closes),
        "mid": round(mid, 4),
        "upper": round(upper, 4),
        "lower": round(lower, 4),
        "bandwidth": round(bandwidth, 4),
        "position": round(position, 4),
        "signal": signal,
    }


def _multi_period(rows_by_period: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    weekly_rows = rows_by_period["weekly"]
    monthly_rows = rows_by_period["monthly"]
    weekly_return = _period_return(weekly_rows, min(6, len(weekly_rows) - 1)) if len(weekly_rows) >= 2 else None
    monthly_return = _period_return(monthly_rows, min(3, len(monthly_rows) - 1)) if len(monthly_rows) >= 2 else None

    alignment = "UNKNOWN"
    if weekly_return is not None and monthly_return is not None:
        if weekly_return > 0 and monthly_return > 0:
            alignment = "UPWARD_ALIGNED"
        elif weekly_return < 0 and monthly_return < 0:
            alignment = "DOWNWARD_ALIGNED"
        else:
            alignment = "MIXED"

    return {
        "weeklyReturn": round(weekly_return, 4) if weekly_return is not None else None,
        "monthlyReturn": round(monthly_return, 4) if monthly_return is not None else None,
        "alignment": alignment,
    }


def _bias(
    trend: Dict[str, Any],
    multi_period: Dict[str, Any],
    config: Dict[str, Any] | None = None,
) -> Tuple[str, float]:
    config = _analysis_config(config)
    thresholds = config["riskThresholds"]
    score = 0.0
    close = trend.get("close", 0.0)
    ma5 = trend.get("ma5", 0.0)
    ma10 = trend.get("ma10", 0.0)
    ma20 = trend.get("ma20", 0.0)
    return20d = trend.get("return20d", 0.0)

    if close > ma20:
        score += 1.0
    else:
        score -= 1.0
    if ma5 > ma10 > ma20:
        score += 1.25
    elif ma5 < ma10 < ma20:
        score -= 1.25
    if return20d > float(thresholds["bullishReturn20d"]):
        score += 1.0
    elif return20d < float(thresholds["bearishReturn20d"]):
        score -= 1.0

    weekly_return = multi_period.get("weeklyReturn")
    monthly_return = multi_period.get("monthlyReturn")
    if isinstance(weekly_return, (int, float)):
        score += 0.6 if weekly_return > 0 else -0.6
    if isinstance(monthly_return, (int, float)):
        score += 0.4 if monthly_return > 0 else -0.4

    if score >= 1.6:
        return "BULLISH", score
    if score <= -1.6:
        return "BEARISH", score
    return "NEUTRAL", score


def _confidence(score: float, quality: Dict[str, Any], multi_period: Dict[str, Any]) -> float:
    confidence = 0.48 + min(0.22, abs(score) * 0.05)
    if quality["dailyCount"] >= 60:
        confidence += 0.08
    if quality["weeklyCount"] >= 6:
        confidence += 0.05
    if quality["monthlyCount"] >= 3:
        confidence += 0.05
    if multi_period.get("alignment") in {"UPWARD_ALIGNED", "DOWNWARD_ALIGNED"}:
        confidence += 0.05
    confidence -= min(0.18, len(quality["issues"]) * 0.04)
    confidence -= min(0.12, quality["volumeMissingRatio"] * 0.2)
    return round(max(0.0, min(0.92, confidence)), 4)


def _risks(
    trend: Dict[str, Any],
    volume_price: Dict[str, Any],
    support_resistance: Dict[str, Any],
    technical_indicators: Dict[str, Any],
    patterns: Dict[str, Any],
    quality: Dict[str, Any],
    config: Dict[str, Any] | None = None,
) -> List[str]:
    config = _analysis_config(config)
    thresholds = config["riskThresholds"]
    risks = list(quality["issues"])
    if trend.get("return20d", 0) < float(thresholds["clearBearishReturn20d"]):
        risks.append("20 日收益率明显为负，短期趋势承压。")
    if support_resistance.get("distanceToSupport20d", 1) < float(thresholds["nearSupportDistance"]):
        risks.append("价格距离 20 日支撑较近，跌破后技术结构会转弱。")
    if support_resistance.get("distanceToResistance20d", 1) < float(thresholds["nearResistanceDistance"]):
        risks.append("价格接近 20 日压力位，追高有效性需要复核。")
    if volume_price.get("status") == "AVAILABLE" and (volume_price.get("volumeRatio5v20") or 0) >= float(thresholds["highVolumeRatio"]) and trend.get("return20d", 0) < 0:
        risks.append("放量下跌信号需要重点审查。")
    rsi = technical_indicators.get("rsi") or {}
    rsi_value = rsi.get("value")
    if isinstance(rsi_value, (int, float)):
        if rsi_value >= 70:
            risks.append("RSI 进入偏热区间，追高有效性需要复核。")
        elif rsi_value <= 30:
            risks.append("RSI 进入偏冷区间，需结合趋势确认是否为弱势延续。")
    bollinger = technical_indicators.get("bollinger") or {}
    boll_position = bollinger.get("position")
    if isinstance(boll_position, (int, float)):
        if boll_position >= 0.85:
            risks.append("价格接近布林上轨，短线波动风险上升。")
        elif boll_position <= 0.15:
            risks.append("价格接近布林下轨，需防趋势继续走弱。")
    for pattern in patterns.get("items") or []:
        if pattern.get("severity") == "WARN":
            risks.append(pattern.get("description") or pattern.get("label") or "技术形态风险需要复核。")
    return risks


def _summary(
    bias: str,
    confidence: float,
    trend: Dict[str, Any],
    volume_price: Dict[str, Any],
    support_resistance: Dict[str, Any],
    technical_indicators: Dict[str, Any],
    patterns: Dict[str, Any],
    chip_analysis: Dict[str, Any],
) -> str:
    bias_label = {
        "BULLISH": "偏强",
        "NEUTRAL": "中性",
        "BEARISH": "偏弱",
        "INSUFFICIENT_DATA": "数据不足",
    }.get(bias, bias)
    indicator_summary = _indicator_summary(technical_indicators)
    pattern_summary = _pattern_summary(patterns)
    ma_summary = _moving_average_summary(trend)
    chip_summary = _chip_analysis_summary(chip_analysis)
    return (
        f"技术面偏向={bias_label}，置信度={confidence:.0%}。"
        f"{trend.get('structure', '')}"
        f" 均线：{ma_summary}。"
        f" 量价：{volume_price.get('description', '')}"
        f" 筹码：{chip_summary}"
        f" 指标：{indicator_summary}"
        f" 形态：{pattern_summary}"
        f" 20日支撑={support_resistance.get('support20d', 'N/A')}，20日压力={support_resistance.get('resistance20d', 'N/A')}。"
        "该输出只供下游折扣和复核使用，不构成交易动作。"
    )


def _moving_average_summary(trend: Dict[str, Any]) -> str:
    return "，".join(
        f"{label}={_format_metric(trend.get(key))}"
        for key, label in (("ma5", "MA5"), ("ma10", "MA10"), ("ma20", "MA20"))
    )


def _format_metric(value: Any, digits: int = 2) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:.{digits}f}"
    return "N/A"


def _indicator_summary(indicators: Dict[str, Any]) -> str:
    parts: List[str] = []
    for key, label in (("macd", "MACD"), ("rsi", "RSI"), ("kdj", "KDJ"), ("bollinger", "布林带")):
        item = indicators.get(key) or {}
        if item.get("status") == "AVAILABLE":
            parts.append(str(item.get("signal") or label))
    return "；".join(parts[:3]) if parts else "指标样本不足"


def _chip_analysis_summary(chip_analysis: Dict[str, Any]) -> str:
    if chip_analysis.get("status") != "AVAILABLE":
        return str(chip_analysis.get("description") or "筹码成本代理不可用。")
    interpretation = str(chip_analysis.get("description") or "").strip().rstrip("。.")
    if not interpretation:
        interpretation = "筹码成本代理未形成明确单边压力或支撑，需结合趋势与量价继续复核"
    if chip_analysis.get("sourceKind") == "C":
        winner = chip_analysis.get("winnerRate")
        winner_part = f"，胜率={_format_pct(winner)}" if isinstance(winner, (int, float)) and not isinstance(winner, bool) else ""
        return (
            f"真实 Tushare 筹码：平均成本={_format_metric(chip_analysis.get('averageCostProxy'))}，"
            f"距成本={_format_pct(chip_analysis.get('closeToCostPct'))}{winner_part}，"
            f"上方压力={_format_pct(chip_analysis.get('overheadVolumeRatio'))}，"
            f"下方支撑={_format_pct(chip_analysis.get('supportVolumeRatio'))}；"
            f"筹码解读：{interpretation}；"
            "Tushare 筹码数据仅供参考，不代表绝对真实持仓。"
        )
    return (
        f"成本代理={_format_metric(chip_analysis.get('averageCostProxy'))}，"
        f"距成本={_format_pct(chip_analysis.get('closeToCostPct'))}，"
        f"上方压力={_format_pct(chip_analysis.get('overheadVolumeRatio'))}，"
        f"下方支撑={_format_pct(chip_analysis.get('supportVolumeRatio'))}；"
        f"筹码解读：{interpretation}；"
        "仅为 K 线成交量价格代理。"
    )


def _format_pct(value: Any, digits: int = 1) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:.{digits}%}"
    return "N/A"


def _pattern_summary(patterns: Dict[str, Any]) -> str:
    items = patterns.get("items") or []
    if not items:
        return "未触发重点形态"
    return "、".join(str(item.get("label") or item.get("code")) for item in items[:3])


def _empty_backtest_buckets() -> Dict[str, Dict[str, Any]]:
    return {
        "BULLISH": {"count": 0, "hitRate": None, "averageForwardReturn": None},
        "BEARISH": {"count": 0, "hitRate": None, "averageForwardReturn": None},
    }


def _backtest_buckets(evaluations: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    buckets = _empty_backtest_buckets()
    for bias in buckets:
        items = [item for item in evaluations if item.get("bias") == bias]
        buckets[bias] = {
            "count": len(items),
            "hitRate": _hit_rate(items),
            "averageForwardReturn": _average_forward_return(items),
        }
    return buckets


def _hit_rate(evaluations: List[Dict[str, Any]]) -> float | None:
    if not evaluations:
        return None
    hits = sum(1 for item in evaluations if item.get("hit") is True)
    return round(hits / len(evaluations), 4)


def _average_forward_return(evaluations: List[Dict[str, Any]]) -> float | None:
    returns = [item.get("forwardReturn") for item in evaluations if isinstance(item.get("forwardReturn"), (int, float))]
    if not returns:
        return None
    return round(mean(returns), 4)


def _backtest_summary(
    evaluated_signals: int,
    hit_rate: float | None,
    average_return: float | None,
    horizon_days: int,
) -> str:
    if evaluated_signals <= 0:
        return "滚动样本未产生偏强/偏弱标签，回测入口只记录验证不足，不生成交易动作。"
    hit_text = "N/A" if hit_rate is None else f"{hit_rate:.0%}"
    return_text = "N/A" if average_return is None else f"{average_return:.2%}"
    return (
        f"滚动技术面标签回测完成：{evaluated_signals} 个偏强/偏弱标签，"
        f"{horizon_days} 日方向命中率 {hit_text}，平均前瞻收益 {return_text}。"
        "该结果只验证标签质量，不构成交易动作。"
    )


def _analysis_config(config: Dict[str, Any] | None = None) -> Dict[str, Any]:
    merged = copy.deepcopy(DEFAULT_TECHNICAL_KLINE_CONFIG)
    if isinstance(config, dict):
        for key in ("minimumSamples", "movingAverageWindows", "volumeWindows", "supportResistanceWindows", "riskThresholds"):
            value = config.get(key)
            if isinstance(value, dict):
                merged[key].update(value)
        if isinstance(config.get("version"), str) and config["version"].strip():
            merged["version"] = config["version"].strip()

    merged["minimumSamples"] = {
        "daily": _safe_int(merged["minimumSamples"].get("daily"), 30, 1, 500),
        "weekly": _safe_int(merged["minimumSamples"].get("weekly"), 6, 1, 120),
        "monthly": _safe_int(merged["minimumSamples"].get("monthly"), 3, 1, 60),
    }
    merged["movingAverageWindows"] = {
        "short": _safe_int(merged["movingAverageWindows"].get("short"), 5, 2, 120),
        "medium": _safe_int(merged["movingAverageWindows"].get("medium"), 10, 2, 160),
        "long": _safe_int(merged["movingAverageWindows"].get("long"), 20, 2, 240),
    }
    merged["volumeWindows"] = {
        "recent": _safe_int(merged["volumeWindows"].get("recent"), 5, 1, 60),
        "baseline": _safe_int(merged["volumeWindows"].get("baseline"), 20, 2, 240),
    }
    merged["supportResistanceWindows"] = {
        "short": _safe_int(merged["supportResistanceWindows"].get("short"), 20, 2, 240),
        "long": _safe_int(merged["supportResistanceWindows"].get("long"), 60, 2, 500),
    }
    merged["riskThresholds"] = {
        "bullishReturn20d": _safe_float(merged["riskThresholds"].get("bullishReturn20d"), 0.05, -1.0, 1.0),
        "bearishReturn20d": _safe_float(merged["riskThresholds"].get("bearishReturn20d"), -0.05, -1.0, 1.0),
        "clearBearishReturn20d": _safe_float(merged["riskThresholds"].get("clearBearishReturn20d"), -0.08, -1.0, 1.0),
        "nearSupportDistance": _safe_float(merged["riskThresholds"].get("nearSupportDistance"), 0.025, 0.0, 1.0),
        "nearResistanceDistance": _safe_float(merged["riskThresholds"].get("nearResistanceDistance"), 0.025, 0.0, 1.0),
        "highVolumeRatio": _safe_float(merged["riskThresholds"].get("highVolumeRatio"), 1.25, 0.1, 10.0),
        "lowVolumeRatio": _safe_float(merged["riskThresholds"].get("lowVolumeRatio"), 0.75, 0.0, 10.0),
        "volumePriceReturn": _safe_float(merged["riskThresholds"].get("volumePriceReturn"), 0.03, 0.0, 1.0),
    }
    merged["configHash"] = _hash_payload({key: value for key, value in merged.items() if key != "configHash"})
    return merged


def _prompt_governance() -> Dict[str, Any]:
    return {
        "version": TECHNICAL_KLINE_PROMPT_VERSION,
        "promptHash": hashlib.sha256(TECHNICAL_KLINE_AGENT_PROMPT.encode("utf-8")).hexdigest()[:16],
        "changedBy": TECHNICAL_KLINE_PROMPT_CHANGED_BY,
        "changeReason": TECHNICAL_KLINE_PROMPT_CHANGE_REASON,
        "rollbackVersion": TECHNICAL_KLINE_PROMPT_ROLLBACK_VERSION,
        "outputMode": "STRICT_JSON",
        "tradeActionPolicy": "NO_DIRECT_TRADE_ACTION",
    }


def _case_classification(status: str, quality: Dict[str, Any], config: Dict[str, Any] | None) -> str:
    override = _case_classification_override(config)
    if override:
        return override
    if status == "SKIPPED" or quality.get("dataMode") != "LIVE" or int(quality.get("dailyCount") or 0) < 1:
        return "insufficient_data"
    return "valid"


def _case_classification_override(config: Dict[str, Any] | None) -> str:
    if not isinstance(config, dict):
        return ""
    value = str(config.get("caseClassification") or "").strip().lower()
    return value if value in TECHNICAL_KLINE_CASE_CLASSIFICATIONS else ""


def _case_classification_detail(classification: str, source: str, issues: List[Any]) -> Dict[str, Any]:
    return {
        "classification": classification,
        "source": source,
        "allowedValues": sorted(TECHNICAL_KLINE_CASE_CLASSIFICATIONS),
        "issues": [str(issue) for issue in issues[:8]],
    }


def _safe_int(value: Any, fallback: int, lower: int, upper: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = fallback
    return max(lower, min(upper, parsed))


def _safe_float(value: Any, fallback: float, lower: float, upper: float) -> float:
    parsed = _number(value)
    if parsed is None:
        parsed = fallback
    return max(lower, min(upper, float(parsed)))


def _hash_payload(payload: Dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _ma(rows: List[Dict[str, Any]], window: int) -> float:
    sample = rows[-window:] if len(rows) >= window else rows
    closes = [_number(row.get("close")) or 0.0 for row in sample]
    return mean(closes) if closes else 0.0


def _ema_series(values: List[float], window: int) -> List[float]:
    if not values:
        return []
    multiplier = 2 / (window + 1)
    ema_values = [values[0]]
    for value in values[1:]:
        ema_values.append((value - ema_values[-1]) * multiplier + ema_values[-1])
    return ema_values


def _period_return(rows: List[Dict[str, Any]], lookback: int) -> float:
    if len(rows) < 2:
        return 0.0
    index = max(0, len(rows) - 1 - lookback)
    start = _number(rows[index].get("close")) or 0.0
    end = _number(rows[-1].get("close")) or 0.0
    if start <= 0:
        return 0.0
    return (end - start) / start


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().replace(",", "").rstrip("%"))
        except ValueError:
            return None
    return None


def _forbidden_actions() -> List[str]:
    return ["BUY", "SELL", "ADD", "REDUCE", "CHASE", "AUTO_ORDER"]
