from __future__ import annotations

import math
from statistics import mean
from typing import Any, Dict, List, Optional


READY_STATUSES = {"READY", "OK", "SUCCESS"}
DEFAULT_VERTICAL_BARRIER_DAYS = 10
DEFAULT_TAKE_PROFIT_ATR = 1.5
DEFAULT_STOP_LOSS_ATR = 1.0
META_MODEL_MIN_SAMPLES = 200
META_GATE_MIN_SAMPLES = 5


def evaluate_strategy_stability_quality(
    symbol: str,
    kline_snapshot: Dict[str, Any],
    *,
    kline_quality: Optional[Dict[str, Any]] = None,
    performance_stats: Optional[Dict[str, Any]] = None,
    current_price: Optional[float] = None,
) -> Dict[str, Any]:
    daily_payload = _period_payload(kline_snapshot, "daily")
    rows = _rows(daily_payload)
    kline_quality = kline_quality if isinstance(kline_quality, dict) else {}
    performance_stats = performance_stats if isinstance(performance_stats, dict) else {}
    evidence_refs = [_evidence_ref(symbol, "daily", daily_payload)]

    if str(daily_payload.get("status") or "").upper() not in READY_STATUSES or len(rows) < 20:
        return _empty_stability_quality(
            symbol=symbol,
            status="BLOCKED",
            reason="strategy_stability_kline_sample_unavailable",
            evidence_refs=evidence_refs,
            kline_quality=kline_quality,
            performance_stats=performance_stats,
        )

    close = _number(current_price) or rows[-1]["close"]
    closes = [row["close"] for row in rows]
    highs = [row["high"] for row in rows]
    lows = [row["low"] for row in rows]
    volumes = [row.get("volume") for row in rows if row.get("volume") is not None]
    returns = _return_series(closes)
    atr_values = _atr_series(highs, lows, closes, 14)
    atr = atr_values[-1] if atr_values else _fallback_atr(rows, close)
    atr_pct = _safe_ratio(atr, close) or 0.0
    atr_pct_series = [
        _safe_ratio(value, closes[index + 14])
        for index, value in enumerate(atr_values)
        if index + 14 < len(closes)
    ]
    atr_pct_series = [float(value) for value in atr_pct_series if value is not None]
    atr_percentile = _rank_leq(atr_pct_series[-60:], atr_pct)
    realized_vol_values = _rolling_realized_vol(returns, 20)
    realized_vol = realized_vol_values[-1] if realized_vol_values else 0.0
    realized_vol_percentile = _rank_leq(realized_vol_values[-60:], realized_vol)
    volume_ratio = _volume_ratio(rows, 5, 20)
    volume_percentile = _rank_leq([float(value) for value in volumes[-60:]], volumes[-1] if volumes else None)

    ma20 = _sma(closes, 20)
    ma60 = _sma(closes, 60)
    ma20_prev = _window_mean(closes[-25:-5]) if len(closes) >= 25 else None
    ma20_slope = _ratio_delta(ma20, ma20_prev) or 0.0
    support_basis = lows[:-1] or lows
    support20 = min(support_basis[-20:])
    support60 = min(support_basis[-60:]) if len(support_basis) >= 60 else support20
    support_distance_atr = (close - support20) / atr if atr and atr > 0 else 0.0
    high60 = max(highs[-60:]) if len(highs) >= 60 else max(highs)
    drawdown_from_high = _safe_ratio(close - high60, high60) or 0.0
    last_return = returns[-1] if returns else 0.0

    kline_risk = kline_quality.get("risk_invalidation") if isinstance(kline_quality.get("risk_invalidation"), dict) else {}
    kline_policy = str(kline_quality.get("action_policy") or kline_quality.get("actionPolicy") or "").upper()
    kline_score = _clamp(_number(kline_quality.get("final_score") or kline_quality.get("score")) or 0.0, 0.0, 100.0)
    kline_invalidated = str(kline_risk.get("status") or "").upper() == "INVALIDATE"

    regime = _regime_state(
        close=close,
        ma20=ma20,
        ma60=ma60,
        ma20_slope=ma20_slope,
        support20=support20,
        atr_percentile=atr_percentile,
        realized_vol_percentile=realized_vol_percentile,
        drawdown_from_high=drawdown_from_high,
        last_return=last_return,
        kline_invalidated=kline_invalidated,
    )
    volatility = _volatility_state(
        atr_pct=atr_pct,
        atr_percentile=atr_percentile,
        realized_vol=realized_vol,
        realized_vol_percentile=realized_vol_percentile,
    )
    drawdown_throttle = _drawdown_throttle(drawdown_from_high)
    meta_gate = _meta_label_gate(performance_stats)

    max_position_ratio = 0.50
    max_step_ratio = 0.20
    position_multiplier = 1.0
    buy_threshold_delta = 0.0
    action_policy = "ALLOW"
    reasons: List[str] = []

    if kline_invalidated or kline_policy == "HOLD":
        action_policy = "HOLD"
        max_position_ratio = 0.0
        max_step_ratio = 0.0
        position_multiplier = 0.0
        buy_threshold_delta = 0.45
        reasons.append("kline_gate_blocks_stability_layer")
    elif meta_gate["status"] == "BLOCK":
        action_policy = "HOLD"
        max_position_ratio = 0.0
        max_step_ratio = 0.0
        position_multiplier = 0.0
        buy_threshold_delta = 0.35
        reasons.append("meta_label_gate_blocks_buy")
    elif regime["status"] in {"DOWNTREND", "HIGH_VOL_STRESS"}:
        action_policy = "REDUCE"
        max_position_ratio = 0.10 if regime["status"] == "HIGH_VOL_STRESS" else 0.05
        max_step_ratio = 0.05
        position_multiplier = 0.55
        buy_threshold_delta = 0.20
        reasons.append("regime_caps_probe_only")
    elif volatility["status"] == "HIGH":
        action_policy = "REDUCE"
        max_position_ratio = 0.15
        max_step_ratio = 0.08
        position_multiplier = 0.70
        buy_threshold_delta = 0.12
        reasons.append("high_volatility_caps_position")
    elif drawdown_throttle["status"] == "THROTTLE":
        action_policy = "REDUCE"
        max_position_ratio = 0.20
        max_step_ratio = 0.10
        position_multiplier = 0.80
        buy_threshold_delta = 0.08
        reasons.append("recent_drawdown_throttles_position")
    elif meta_gate["status"] == "REDUCE":
        action_policy = "REDUCE"
        max_position_ratio = 0.25
        max_step_ratio = 0.10
        position_multiplier = 0.85
        buy_threshold_delta = 0.08
        reasons.append("meta_label_gate_reduces_size")
    else:
        reasons.append("strategy_stability_allows_rule_gate")

    regime_component = regime["score"] / 100
    volatility_component = volatility["score"] / 100
    kline_component = kline_score / 100
    drawdown_component = drawdown_throttle["score"] / 100
    meta_component = meta_gate["score"] / 100
    stability_score = round(
        100
        * (
            regime_component * 0.25
            + volatility_component * 0.20
            + kline_component * 0.25
            + drawdown_component * 0.15
            + meta_component * 0.15
        )
    )
    if action_policy == "HOLD":
        grade = "BLOCKED"
    elif stability_score >= 78:
        grade = "A"
    elif stability_score >= 64:
        grade = "B"
    elif stability_score >= 50:
        grade = "C"
    else:
        grade = "D"

    volatility_sizing_policy = {
        "method": "signalops_volatility_sizing_v1",
        "max_position_ratio": round(max_position_ratio, 4),
        "max_step_position_ratio": round(max_step_ratio, 4),
        "position_ratio_multiplier": round(position_multiplier, 4),
        "probe_only": action_policy == "REDUCE",
        "forbid_confirm": regime["status"] in {"DOWNTREND", "HIGH_VOL_STRESS"} or volatility["status"] == "HIGH",
        "simulation_only": True,
        "is_real_trade": False,
    }
    stability_strategy = {
        "method": "signalops_strategy_stability_v1",
        "uses": [
            "atr_normalized_support_distance",
            "rolling_volatility_percentile",
            "volume_percentile",
            "drawdown_throttle",
            "bayesian_meta_label_gate",
        ],
        "requires_backtest_before_review": True,
        "simulation_only": True,
        "is_real_trade": False,
    }

    return {
        "version": 1,
        "symbol": symbol,
        "status": "READY",
        "stability_score": stability_score,
        "score": stability_score,
        "grade": grade,
        "regime_state": regime,
        "volatility_state": volatility,
        "drawdown_throttle": drawdown_throttle,
        "confidence_floor": meta_gate["wilson_win_rate_lower_bound"],
        "confidence_floor_detail": {
            "method": "wilson_lower_bound_95",
            "sample_count": meta_gate["sample_count"],
            "wilson_win_rate_lower_bound": meta_gate["wilson_win_rate_lower_bound"],
        },
        "action_policy": action_policy,
        "actionPolicy": action_policy,
        "buyThresholdDelta": round(buy_threshold_delta, 4),
        "positionRatioMultiplier": round(position_multiplier, 4),
        "volatility_sizing_policy": volatility_sizing_policy,
        "stability_strategy": stability_strategy,
        "meta_label_gate": meta_gate,
        "triple_barrier_summary": {
            "status": "OFFLINE_ONLY",
            "vertical_barrier_days": DEFAULT_VERTICAL_BARRIER_DAYS,
            "take_profit_atr": DEFAULT_TAKE_PROFIT_ATR,
            "stop_loss_atr": DEFAULT_STOP_LOSS_ATR,
            "simulation_only": True,
            "is_real_trade": False,
        },
        "metrics": {
            "close": round(close, 6),
            "ma20": _round_or_none(ma20),
            "ma60": _round_or_none(ma60),
            "ma20_slope": round(ma20_slope, 6),
            "atr14": _round_or_none(atr),
            "atr_pct": round(atr_pct, 6),
            "atr_percentile": _round_or_none(atr_percentile),
            "realized_vol20": round(realized_vol, 6),
            "realized_vol_percentile": _round_or_none(realized_vol_percentile),
            "volume_ratio_5v20": _round_or_none(volume_ratio),
            "volume_percentile": _round_or_none(volume_percentile),
            "support20": round(support20, 6),
            "support60": round(support60, 6),
            "support_distance_atr": round(support_distance_atr, 6),
            "drawdown_from_60d_high": round(drawdown_from_high, 6),
        },
        "reasons": [*reasons, *regime.get("reasons", []), *volatility.get("reasons", [])][:14],
        "evidence_refs": evidence_refs,
        "simulation_only": True,
        "is_real_trade": False,
    }


def label_triple_barrier_event(
    market_data: List[Dict[str, Any]],
    entry_date: str,
    *,
    horizon_days: int = DEFAULT_VERTICAL_BARRIER_DAYS,
    take_profit_atr: float = DEFAULT_TAKE_PROFIT_ATR,
    stop_loss_atr: float = DEFAULT_STOP_LOSS_ATR,
) -> Dict[str, Any]:
    rows = _market_rows(market_data)
    if not rows:
        return _empty_triple_barrier_label(entry_date, "market_data_unavailable")
    entry_index = next((index for index, row in enumerate(rows) if row["date"] >= entry_date), -1)
    if entry_index < 0:
        return _empty_triple_barrier_label(entry_date, "entry_date_outside_market_data")
    entry = rows[entry_index]
    prior_rows = rows[: entry_index + 1]
    highs = [row["high"] for row in prior_rows]
    lows = [row["low"] for row in prior_rows]
    closes = [row["close"] for row in prior_rows]
    atr_values = _atr_series(highs, lows, closes, 14)
    atr = atr_values[-1] if atr_values else _fallback_atr(prior_rows, entry["close"])
    support_basis = [row["low"] for row in rows[:entry_index]]
    support20 = min(support_basis[-20:]) if support_basis else entry["close"] - atr
    profit_barrier = entry["close"] + take_profit_atr * atr
    stop_barrier = entry["close"] - stop_loss_atr * atr
    label = 0
    first_barrier = "VERTICAL"
    time_to_barrier = 0
    max_high = entry["close"]
    min_low = entry["close"]
    support_break = False
    horizon_rows = rows[entry_index + 1 : entry_index + 1 + max(1, int(horizon_days))]
    for offset, row in enumerate(horizon_rows, start=1):
        max_high = max(max_high, row["high"])
        min_low = min(min_low, row["low"])
        support_break = support_break or row["low"] < support20
        if row["low"] <= stop_barrier or support_break:
            label = -1
            first_barrier = "STOP_LOSS" if row["low"] <= stop_barrier else "SUPPORT_BREAK"
            time_to_barrier = offset
            break
        if row["high"] >= profit_barrier:
            label = 1
            first_barrier = "TAKE_PROFIT"
            time_to_barrier = offset
            break
    if time_to_barrier == 0:
        time_to_barrier = len(horizon_rows)
    return {
        "entry_date": entry["date"],
        "entry_price": round(entry["close"], 6),
        "triple_barrier_label": label,
        "first_barrier": first_barrier,
        "time_to_barrier": time_to_barrier,
        "max_adverse_excursion": round((_safe_ratio(min_low - entry["close"], entry["close"]) or 0.0), 6),
        "max_favorable_excursion": round((_safe_ratio(max_high - entry["close"], entry["close"]) or 0.0), 6),
        "atr14": round(atr, 6),
        "take_profit_barrier": round(profit_barrier, 6),
        "stop_loss_barrier": round(stop_barrier, 6),
        "support20": round(support20, 6),
        "support_break": support_break,
        "vertical_barrier_days": horizon_days,
        "simulation_only": True,
        "is_real_trade": False,
    }


def summarize_triple_barrier_labels(
    market_data: List[Dict[str, Any]],
    signals: Optional[List[Dict[str, Any]]],
    *,
    horizon_days: int = DEFAULT_VERTICAL_BARRIER_DAYS,
) -> Dict[str, Any]:
    buy_signals = [
        signal
        for signal in signals or []
        if str(signal.get("direction") or signal.get("signal_type") or "").upper() in {"BUY", "LONG", "SIGNALOPS_REPLAY_BUY"}
    ]
    labels = [
        label_triple_barrier_event(
            market_data,
            _signal_date(signal),
            horizon_days=horizon_days,
        )
        for signal in buy_signals
        if _signal_date(signal)
    ]
    counts = {
        "take_profit": sum(1 for item in labels if item.get("triple_barrier_label") == 1),
        "stop_loss": sum(1 for item in labels if item.get("triple_barrier_label") == -1),
        "vertical": sum(1 for item in labels if item.get("triple_barrier_label") == 0),
    }
    return {
        "method": "triple_barrier_atr_v1",
        "status": "READY" if labels else "EMPTY",
        "sample_count": len(labels),
        "vertical_barrier_days": horizon_days,
        "take_profit_atr": DEFAULT_TAKE_PROFIT_ATR,
        "stop_loss_atr": DEFAULT_STOP_LOSS_ATR,
        "counts": counts,
        "hit_rate": round(counts["take_profit"] / len(labels), 6) if labels else 0.0,
        "stop_rate": round(counts["stop_loss"] / len(labels), 6) if labels else 0.0,
        "avg_max_adverse_excursion": round(mean([item["max_adverse_excursion"] for item in labels]), 6) if labels else 0.0,
        "avg_max_favorable_excursion": round(mean([item["max_favorable_excursion"] for item in labels]), 6) if labels else 0.0,
        "labels": labels[-20:],
        "simulation_only": True,
        "is_real_trade": False,
    }


def wilson_win_rate_lower_bound(wins: float, total: float, z: float = 1.96) -> float:
    total = float(total or 0.0)
    if total <= 0:
        return 0.0
    wins = _clamp(float(wins or 0.0), 0.0, total)
    phat = wins / total
    denominator = 1.0 + z * z / total
    centre = phat + z * z / (2.0 * total)
    margin = z * math.sqrt((phat * (1.0 - phat) + z * z / (4.0 * total)) / total)
    return round(max(0.0, (centre - margin) / denominator), 6)


def stability_validation_report(
    *,
    baseline_report: Dict[str, Any],
    candidate_report: Dict[str, Any],
    candidate_train_report: Dict[str, Any],
    train_window: Dict[str, str],
    validation_window: Dict[str, str],
    candidate_config: Dict[str, Any],
    market_data: Optional[List[Dict[str, Any]]] = None,
    candidate_train_signals: Optional[List[Dict[str, Any]]] = None,
    candidate_validation_signals: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    train_trades = int(candidate_train_report.get("total_trades") or 0)
    validation_trades = int(candidate_report.get("total_trades") or 0)
    train_wins = float(candidate_train_report.get("winning_trades") or 0.0)
    validation_wins = float(candidate_report.get("winning_trades") or 0.0)
    train_wilson = wilson_win_rate_lower_bound(train_wins, train_trades)
    validation_wilson = wilson_win_rate_lower_bound(validation_wins, validation_trades)
    horizon_days = int(
        _number(
            _nested_get(candidate_config, "stability_strategy", "vertical_barrier_days")
            or _nested_get(candidate_config, "meta_label_gate", "vertical_barrier_days")
        )
        or DEFAULT_VERTICAL_BARRIER_DAYS
    )
    trial_count = int(_number(candidate_config.get("candidate_trial_count") or candidate_config.get("trial_count") or 1) or 1)
    validation_expectancy = _expectancy_pct(candidate_report)
    baseline_expectancy = _expectancy_pct(baseline_report)
    multiple_testing_penalty = round(math.log1p(max(trial_count, 1)) * 0.012, 6)
    deflated_expectancy = round(validation_expectancy - multiple_testing_penalty, 6)
    multiple_testing_passed = trial_count <= 20 or (
        deflated_expectancy > baseline_expectancy and validation_trades >= 5 and validation_wilson >= 0.20
    )
    purged = _purged_embargo_report(
        train_window=train_window,
        validation_window=validation_window,
        embargo_days=horizon_days,
    )
    triple_barrier = {
        "train": summarize_triple_barrier_labels(market_data or [], candidate_train_signals, horizon_days=horizon_days),
        "validation": summarize_triple_barrier_labels(market_data or [], candidate_validation_signals, horizon_days=horizon_days),
    }
    return {
        "method": "signalops_strategy_stability_validation_v1",
        "status": "PASSED" if multiple_testing_passed and purged["embargo_satisfied"] else "FAILED",
        "purged_walk_forward": purged,
        "wilson_win_rate_lower_bound": {
            "train": train_wilson,
            "validation": validation_wilson,
            "method": "wilson_lower_bound_95",
        },
        "after_cost_expectancy_pct": {
            "baseline_validation": baseline_expectancy,
            "candidate_validation": validation_expectancy,
            "deflated_candidate_validation": deflated_expectancy,
        },
        "multiple_testing": {
            "candidate_trial_count": trial_count,
            "penalty_pct": multiple_testing_penalty,
            "passed": multiple_testing_passed,
        },
        "mae_mfe": {
            "train_avg_mae": triple_barrier["train"]["avg_max_adverse_excursion"],
            "train_avg_mfe": triple_barrier["train"]["avg_max_favorable_excursion"],
            "validation_avg_mae": triple_barrier["validation"]["avg_max_adverse_excursion"],
            "validation_avg_mfe": triple_barrier["validation"]["avg_max_favorable_excursion"],
        },
        "triple_barrier_summary": triple_barrier,
        "simulation_only": True,
        "is_real_trade": False,
    }


def _empty_stability_quality(
    *,
    symbol: str,
    status: str,
    reason: str,
    evidence_refs: List[Dict[str, Any]],
    kline_quality: Dict[str, Any],
    performance_stats: Dict[str, Any],
) -> Dict[str, Any]:
    meta_gate = _meta_label_gate(performance_stats)
    return {
        "version": 1,
        "symbol": symbol,
        "status": status,
        "stability_score": 0,
        "score": 0,
        "grade": "BLOCKED",
        "regime_state": {"score": 0, "status": "UNKNOWN", "reasons": [reason]},
        "volatility_state": {"score": 0, "status": "UNKNOWN", "reasons": [reason]},
        "drawdown_throttle": {"score": 0, "status": "UNKNOWN", "reasons": [reason]},
        "confidence_floor": meta_gate["wilson_win_rate_lower_bound"],
        "confidence_floor_detail": {"method": "wilson_lower_bound_95", "sample_count": meta_gate["sample_count"]},
        "action_policy": "HOLD",
        "actionPolicy": "HOLD",
        "buyThresholdDelta": 0.45,
        "positionRatioMultiplier": 0.0,
        "volatility_sizing_policy": {
            "method": "signalops_volatility_sizing_v1",
            "max_position_ratio": 0.0,
            "max_step_position_ratio": 0.0,
            "probe_only": True,
            "forbid_confirm": True,
            "simulation_only": True,
            "is_real_trade": False,
        },
        "stability_strategy": {
            "method": "signalops_strategy_stability_v1",
            "requires_backtest_before_review": True,
            "simulation_only": True,
            "is_real_trade": False,
        },
        "meta_label_gate": meta_gate,
        "triple_barrier_summary": {
            "status": "OFFLINE_ONLY",
            "vertical_barrier_days": DEFAULT_VERTICAL_BARRIER_DAYS,
            "simulation_only": True,
            "is_real_trade": False,
        },
        "metrics": {},
        "reasons": [reason],
        "evidence_refs": evidence_refs,
        "kline_signal_quality_status": kline_quality.get("status"),
        "simulation_only": True,
        "is_real_trade": False,
    }


def _regime_state(**kwargs: Any) -> Dict[str, Any]:
    close = kwargs["close"]
    ma20 = kwargs["ma20"]
    ma60 = kwargs["ma60"]
    ma20_slope = kwargs["ma20_slope"]
    support20 = kwargs["support20"]
    atr_percentile = kwargs["atr_percentile"] or 0.0
    realized_vol_percentile = kwargs["realized_vol_percentile"] or 0.0
    drawdown = kwargs["drawdown_from_high"]
    last_return = kwargs["last_return"]
    if kwargs["kline_invalidated"] or close < support20:
        return {"score": 5, "status": "DOWNTREND", "reasons": ["support_or_kline_invalidated"]}
    if (atr_percentile >= 0.85 or realized_vol_percentile >= 0.85) and (last_return < -0.01 or drawdown <= -0.10):
        return {"score": 18, "status": "HIGH_VOL_STRESS", "reasons": ["high_volatility_stress"]}
    if ma20 is not None and ma60 is not None and close >= ma20 >= ma60 * 0.98 and ma20_slope >= 0:
        return {"score": 86, "status": "TREND_UP", "reasons": ["ma20_above_ma60_with_positive_slope"]}
    if ma20 is not None and close >= ma20 and ma20_slope >= -0.002 and drawdown > -0.18:
        return {"score": 72, "status": "RECOVERY_CONFIRMED", "reasons": ["price_recovered_above_flat_ma20"]}
    if ma20 is not None and close < ma20 and ma20_slope < -0.002:
        return {"score": 24, "status": "DOWNTREND", "reasons": ["close_below_falling_ma20"]}
    return {"score": 56, "status": "RANGE", "reasons": ["range_bound_or_mixed_regime"]}


def _volatility_state(**kwargs: Any) -> Dict[str, Any]:
    atr_pct = kwargs["atr_pct"]
    atr_percentile = kwargs["atr_percentile"] or 0.0
    realized_vol_percentile = kwargs["realized_vol_percentile"] or 0.0
    if atr_pct >= 0.06 or atr_percentile >= 0.85 or realized_vol_percentile >= 0.85:
        return {"score": 30, "status": "HIGH", "reasons": ["volatility_percentile_high"]}
    if atr_percentile <= 0.35 and realized_vol_percentile <= 0.40:
        return {"score": 76, "status": "COMPRESSED", "reasons": ["volatility_percentile_compressed"]}
    return {"score": 58, "status": "NORMAL", "reasons": ["volatility_regime_normal"]}


def _drawdown_throttle(drawdown_from_high: float) -> Dict[str, Any]:
    if drawdown_from_high <= -0.18:
        return {"score": 22, "status": "THROTTLE", "drawdown_from_high": round(drawdown_from_high, 6), "reasons": ["recent_drawdown_deep"]}
    if drawdown_from_high <= -0.10:
        return {"score": 45, "status": "THROTTLE", "drawdown_from_high": round(drawdown_from_high, 6), "reasons": ["recent_drawdown_moderate"]}
    return {"score": 78, "status": "CLEAR", "drawdown_from_high": round(drawdown_from_high, 6), "reasons": ["drawdown_throttle_clear"]}


def _meta_label_gate(performance_stats: Dict[str, Any]) -> Dict[str, Any]:
    trade_count = _number(performance_stats.get("trade_count")) or 0.0
    win_rate = _number(performance_stats.get("win_rate")) or 0.0
    wins = _number(performance_stats.get("wins"))
    if wins is None:
        wins = win_rate * trade_count
    expectancy = _number(performance_stats.get("expectancy")) or _number(performance_stats.get("avg_pnl_rate")) or 0.0
    max_drawdown = _number(performance_stats.get("max_drawdown")) or 0.0
    max_drawdown_pressure = abs(max_drawdown)
    wilson = wilson_win_rate_lower_bound(wins, trade_count)
    if trade_count < META_GATE_MIN_SAMPLES:
        status = "INSUFFICIENT_SAMPLE"
        score = 58
        reason = "meta_label_sample_insufficient"
        enabled = False
    elif wilson < 0.25 and expectancy < 0:
        status = "BLOCK"
        score = 15
        reason = "wilson_floor_and_expectancy_negative"
        enabled = True
    elif wilson < 0.35 or expectancy < -0.005 or max_drawdown_pressure >= 0.10:
        status = "REDUCE"
        score = 42
        reason = "meta_label_floor_requires_size_reduction"
        enabled = True
    else:
        status = "ALLOW"
        score = 76
        reason = "meta_label_gate_allows"
        enabled = True
    posterior_win_rate = (wins + 4.0) / (trade_count + 8.0) if trade_count > 0 else 0.5
    return {
        "method": "bayesian_bucket_meta_label_v1",
        "enabled": enabled,
        "model_ready": trade_count >= META_MODEL_MIN_SAMPLES,
        "required_model_samples": META_MODEL_MIN_SAMPLES,
        "min_gate_samples": META_GATE_MIN_SAMPLES,
        "sample_count": int(trade_count),
        "wins": round(wins, 4),
        "posterior_win_rate": round(posterior_win_rate, 6),
        "wilson_win_rate_lower_bound": wilson,
        "expectancy": round(expectancy, 6),
        "max_drawdown": round(max_drawdown, 6),
        "max_drawdown_pressure": round(max_drawdown_pressure, 6),
        "status": status,
        "score": score,
        "action_policy": "HOLD" if status == "BLOCK" else "REDUCE" if status == "REDUCE" else "ALLOW",
        "reasons": [reason],
        "simulation_only": True,
        "is_real_trade": False,
    }


def _purged_embargo_report(*, train_window: Dict[str, str], validation_window: Dict[str, str], embargo_days: int) -> Dict[str, Any]:
    train_end = str(train_window.get("end") or "")
    validation_start = str(validation_window.get("start") or "")
    gap_days = _date_gap_days(train_end, validation_start)
    satisfied = gap_days is not None and gap_days >= max(1, embargo_days)
    return {
        "method": "purged_walk_forward_embargo_v1",
        "embargo_days": embargo_days,
        "train_end": train_end,
        "validation_start": validation_start,
        "gap_days": gap_days,
        "embargo_satisfied": satisfied,
        "reasons": [] if satisfied else ["purged_embargo_overlap_risk"],
    }


def _date_gap_days(start: str, end: str) -> Optional[int]:
    from datetime import date

    try:
        left = date.fromisoformat(start[:10])
        right = date.fromisoformat(end[:10])
    except ValueError:
        return None
    return (right - left).days


def _expectancy_pct(report: Dict[str, Any]) -> float:
    trades = int(report.get("total_trades") or 0)
    if trades <= 0:
        return 0.0
    return round(float(report.get("total_return_pct") or 0.0) / trades, 6)


def _period_payload(snapshot: Dict[str, Any], period: str) -> Dict[str, Any]:
    if not isinstance(snapshot, dict):
        return {}
    payload = snapshot.get(period)
    if isinstance(payload, dict):
        return payload
    if period == "daily" and isinstance(snapshot.get("rows"), list):
        return snapshot
    return {}


def _rows(payload: Dict[str, Any]) -> List[Dict[str, float]]:
    raw_rows = payload.get("rows") if isinstance(payload, dict) else None
    if not isinstance(raw_rows, list):
        return []
    return _market_rows(raw_rows)


def _market_rows(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        close = _number(item.get("close"))
        open_price = _number(item.get("open")) or close
        high = _number(item.get("high"))
        low = _number(item.get("low"))
        if close is None or open_price is None:
            continue
        if high is None:
            high = max(open_price, close)
        if low is None:
            low = min(open_price, close)
        rows.append({
            "date": str(item.get("date") or item.get("tradeDate") or item.get("timestamp") or f"ROW_{index:04d}"),
            "open": float(open_price),
            "high": float(high),
            "low": float(low),
            "close": float(close),
            "volume": _number(item.get("volume") or item.get("vol")),
        })
    return rows


def _empty_triple_barrier_label(entry_date: str, reason: str) -> Dict[str, Any]:
    return {
        "entry_date": entry_date,
        "triple_barrier_label": 0,
        "first_barrier": "UNAVAILABLE",
        "time_to_barrier": 0,
        "max_adverse_excursion": 0.0,
        "max_favorable_excursion": 0.0,
        "reason": reason,
        "simulation_only": True,
        "is_real_trade": False,
    }


def _signal_date(signal: Dict[str, Any]) -> str:
    return str(signal.get("timestamp") or signal.get("date") or signal.get("signal_date") or "")[:10]


def _return_series(closes: List[float]) -> List[float]:
    return [
        (closes[index] - closes[index - 1]) / closes[index - 1]
        for index in range(1, len(closes))
        if closes[index - 1] != 0
    ]


def _rolling_realized_vol(returns: List[float], window: int) -> List[float]:
    values: List[float] = []
    if len(returns) < window:
        return values
    for index in range(window, len(returns) + 1):
        sample = returns[index - window:index]
        avg = mean(sample)
        variance = mean([(value - avg) ** 2 for value in sample])
        values.append(variance ** 0.5)
    return values


def _atr_series(highs: List[float], lows: List[float], closes: List[float], window: int) -> List[float]:
    if len(closes) <= window:
        return []
    true_ranges: List[float] = []
    for index in range(1, len(closes)):
        true_ranges.append(max(
            highs[index] - lows[index],
            abs(highs[index] - closes[index - 1]),
            abs(lows[index] - closes[index - 1]),
        ))
    return [mean(true_ranges[index - window:index]) for index in range(window, len(true_ranges) + 1)]


def _fallback_atr(rows: List[Dict[str, Any]], close: float) -> float:
    ranges = [abs(row["high"] - row["low"]) for row in rows[-14:] if row.get("high") is not None and row.get("low") is not None]
    value = mean(ranges) if ranges else close * 0.01
    return max(value, close * 0.005, 0.000001)


def _sma(values: List[float], window: int) -> Optional[float]:
    if len(values) < window:
        return None
    return mean(values[-window:])


def _window_mean(values: List[float]) -> Optional[float]:
    return mean(values) if values else None


def _safe_ratio(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _ratio_delta(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    if current is None or previous in (None, 0):
        return None
    return (current - previous) / previous


def _rank_leq(values: List[float], current: Optional[float]) -> Optional[float]:
    if current is None or not values:
        return None
    return sum(1 for value in values if value <= current) / len(values)


def _volume_ratio(rows: List[Dict[str, Any]], short_window: int, long_window: int) -> Optional[float]:
    volumes = [row.get("volume") for row in rows if row.get("volume") is not None]
    if len(volumes) < long_window:
        return None
    long_avg = mean(volumes[-long_window:])
    if long_avg <= 0:
        return None
    return mean(volumes[-short_window:]) / long_avg


def _evidence_ref(symbol: str, period: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    status = str(payload.get("status") or "UNKNOWN").upper() if isinstance(payload, dict) else "UNKNOWN"
    return {
        "source_type": "STRATEGY_STABILITY",
        "source_id": f"{symbol}:{period}",
        "label": f"strategy_stability_kline_status:{status}",
        "quality": "MEDIUM" if status in READY_STATUSES else "LOW",
    }


def _nested_get(value: Dict[str, Any], *keys: str) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _number(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))


def _round_or_none(value: Optional[float]) -> Optional[float]:
    return round(value, 6) if value is not None else None
