from __future__ import annotations

from statistics import mean
from typing import Any, Dict, List, Optional


READY_STATUSES = {"READY", "OK", "SUCCESS"}


def evaluate_kline_signal_quality(
    symbol: str,
    kline_snapshot: Dict[str, Any],
    *,
    current_price: Optional[float] = None,
) -> Dict[str, Any]:
    """Score K-line quality for SignalOps simulation buy decisions.

    The output is intentionally JSON-shaped and conservative: it may tighten or
    block simulated buys, but it never produces a real-trading instruction.
    """

    daily_payload = _period_payload(kline_snapshot, "daily")
    daily_status = str(daily_payload.get("status") or "").upper()
    rows = _rows(daily_payload)
    evidence_refs = [_evidence_ref(symbol, "daily", daily_payload)]

    if daily_status not in READY_STATUSES:
        return _empty_quality(
            symbol=symbol,
            action_policy="HOLD",
            grade="BLOCKED",
            status=daily_status or "UNAVAILABLE",
            reason="daily_kline_unavailable",
            evidence_refs=evidence_refs,
        )

    if not rows:
        return _empty_quality(
            symbol=symbol,
            action_policy="HOLD",
            grade="BLOCKED",
            status="INSUFFICIENT_READY_EMPTY",
            reason="daily_kline_ready_without_rows",
            evidence_refs=evidence_refs,
        )

    if len(rows) < 20:
        return _empty_quality(
            symbol=symbol,
            action_policy="HOLD",
            grade="BLOCKED",
            status="INSUFFICIENT_DATA",
            reason="daily_kline_sample_below_20",
            evidence_refs=evidence_refs,
        )

    close = _number(current_price) or rows[-1]["close"]
    closes = [row["close"] for row in rows]
    highs = [row["high"] for row in rows]
    lows = [row["low"] for row in rows]
    volumes = [row.get("volume") for row in rows if row.get("volume") is not None]
    ma20 = _sma(closes, 20)
    ma60 = _sma(closes, 60)
    ma20_prev = _window_mean(closes[-25:-5]) if len(closes) >= 25 else None
    ma20_slope = _ratio_delta(ma20, ma20_prev)
    support_basis = lows[:-1] or lows
    support20 = min(support_basis[-20:])
    support60 = min(support_basis[-60:]) if len(support_basis) >= 60 else support20
    distance_to_support20 = _safe_ratio(close - support20, close)
    distance_to_support60 = _safe_ratio(close - support60, close)
    previous_close = closes[-2] if len(closes) >= 2 else close
    last_return = _safe_ratio(close - previous_close, previous_close)
    lower_lows = len(lows) >= 3 and lows[-1] < lows[-2] < lows[-3]

    rsi_values = _rsi_series(closes, 14)
    rsi = rsi_values[-1] if rsi_values else None
    prior_rsi = rsi_values[-2] if len(rsi_values) >= 2 else None
    oversold_rebound = rsi is not None and prior_rsi is not None and prior_rsi <= 35 and rsi > prior_rsi

    atr_values = _atr_series(highs, lows, closes, 14)
    atr = atr_values[-1] if atr_values else None
    atr_avg20 = _window_mean(atr_values[-20:]) if len(atr_values) >= 20 else None
    atr_contracting = atr is not None and atr_avg20 is not None and atr <= atr_avg20 * 0.92

    bollinger_widths = _bollinger_widths(closes, 20)
    bollinger_width = bollinger_widths[-1] if bollinger_widths else None
    compression_rank = _rank_leq(bollinger_widths[-60:], bollinger_width)
    volatility_compressed = compression_rank is not None and compression_rank <= 0.35

    volume_ratio = _volume_ratio(rows, 5, 20)
    volume_available = volume_ratio is not None and len(volumes) >= 20
    shrink_stop = bool(
        volume_ratio is not None
        and volume_ratio <= 0.85
        and last_return >= -0.002
        and close >= support20
    )
    breakout_confirmed = bool(
        volume_ratio is not None
        and ma20 is not None
        and close > ma20
        and volume_ratio >= 1.15
        and last_return > 0.003
    )
    high_volume_decline = bool(volume_ratio is not None and volume_ratio >= 1.25 and last_return < -0.015)
    support_broken = close < support20
    risk_invalidated = support_broken or (high_volume_decline and ma20 is not None and close < ma20) or (lower_lows and ma20 is not None and close < ma20)

    trend = _trend_component(close, ma20, ma60, ma20_slope, support20)
    bottom = _bottom_component(
        close=close,
        support20=support20,
        support60=support60,
        distance_to_support20=distance_to_support20,
        distance_to_support60=distance_to_support60,
        oversold_rebound=oversold_rebound,
        atr_contracting=atr_contracting,
        volatility_compressed=volatility_compressed,
        shrink_stop=shrink_stop,
        support_broken=support_broken,
    )
    volatility = _volatility_component(
        volatility_compressed=volatility_compressed,
        atr=atr,
        close=close,
        support_broken=support_broken,
    )
    volume_price = _volume_component(
        volume_available=volume_available,
        volume_ratio=volume_ratio,
        shrink_stop=shrink_stop,
        breakout_confirmed=breakout_confirmed,
        high_volume_decline=high_volume_decline,
    )
    multi = _multi_timeframe_component(symbol, kline_snapshot, evidence_refs)
    risk = {
        "score": 0 if risk_invalidated else 82,
        "status": "INVALIDATE" if risk_invalidated else "CLEAR",
        "support_broken": support_broken,
        "high_volume_decline": high_volume_decline,
        "consecutive_lower_lows": lower_lows,
        "reasons": _risk_reasons(support_broken, high_volume_decline, lower_lows),
    }

    final_score = round(
        trend["score"] * 0.25
        + bottom["score"] * 0.25
        + volatility["score"] * 0.15
        + volume_price["score"] * 0.15
        + multi["score"] * 0.10
        + risk["score"] * 0.10
    )
    action_policy, ladder_stage = _policy_from_score(
        final_score=final_score,
        risk_invalidated=risk_invalidated,
        breakout_confirmed=breakout_confirmed,
        close_above_ma20=ma20 is not None and close >= ma20,
        multi_status=str(multi["status"]),
    )
    grade = _grade(final_score, action_policy)
    target_ratio = {
        "PROBE": 0.15,
        "CONFIRM": 0.35,
        "FOLLOW_THROUGH": 0.50,
    }.get(ladder_stage, 0.0)
    reasons = [
        *trend["reasons"],
        *bottom["reasons"],
        *volatility["reasons"],
        *volume_price["reasons"],
        *multi["reasons"],
        *risk["reasons"],
    ]
    if not reasons:
        reasons.append("kline_quality_neutral")

    return {
        "version": 1,
        "symbol": symbol,
        "status": "READY",
        "final_score": final_score,
        "score": final_score,
        "grade": grade,
        "action_policy": action_policy,
        "actionPolicy": action_policy,
        "trend_regime": trend,
        "bottom_stage_score": bottom,
        "volatility_compression": volatility,
        "volume_price_confirmation": volume_price,
        "multi_timeframe_alignment": multi,
        "risk_invalidation": risk,
        "ladder_stage": ladder_stage,
        "ladder_buy_policy": {
            "stage": ladder_stage,
            "target_position_ratio": target_ratio,
            "max_position_ratio": 0.50,
            "max_step_position_ratio": 0.20,
            "invalidate_on": risk["reasons"],
            "simulation_only": True,
            "is_real_trade": False,
        },
        "kline_strategy": {
            "method": "signalops_kline_quality_v1",
            "allow_actions": ["SIM_HOLD", "SIM_BUY", "SIM_T_BUY", "SIM_CLOSE"],
            "requires_backtest_before_review": True,
            "simulation_only": True,
            "is_real_trade": False,
        },
        "buyThresholdDelta": _buy_threshold_delta(action_policy, ladder_stage),
        "positionRatioMultiplier": 1.0,
        "metrics": {
            "close": round(close, 6),
            "ma20": _round_or_none(ma20),
            "ma60": _round_or_none(ma60),
            "ma20_slope": _round_or_none(ma20_slope),
            "support20": round(support20, 6),
            "support60": round(support60, 6),
            "distance_to_support20": _round_or_none(distance_to_support20),
            "distance_to_support60": _round_or_none(distance_to_support60),
            "last_return": _round_or_none(last_return),
            "rsi14": _round_or_none(rsi),
            "atr14": _round_or_none(atr),
            "bollinger_bandwidth": _round_or_none(bollinger_width),
            "bollinger_compression_rank": _round_or_none(compression_rank),
            "volume_ratio_5v20": _round_or_none(volume_ratio),
        },
        "reasons": reasons[:12],
        "evidence_refs": evidence_refs,
        "simulation_only": True,
        "is_real_trade": False,
    }


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
    rows: List[Dict[str, float]] = []
    for item in raw_rows:
        if not isinstance(item, dict):
            continue
        open_price = _number(item.get("open"))
        high = _number(item.get("high"))
        low = _number(item.get("low"))
        close = _number(item.get("close"))
        if None in (open_price, high, low, close):
            continue
        rows.append({
            "open": float(open_price),
            "high": float(high),
            "low": float(low),
            "close": float(close),
            "volume": _number(item.get("volume")),
        })
    return rows


def _empty_quality(
    *,
    symbol: str,
    action_policy: str,
    grade: str,
    status: str,
    reason: str,
    evidence_refs: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "version": 1,
        "symbol": symbol,
        "status": status,
        "final_score": 0,
        "score": 0,
        "grade": grade,
        "action_policy": action_policy,
        "actionPolicy": action_policy,
        "trend_regime": {"score": 0, "status": status, "reasons": [reason]},
        "bottom_stage_score": {"score": 0, "status": status, "reasons": [reason]},
        "volatility_compression": {"score": 0, "status": status, "reasons": [reason]},
        "volume_price_confirmation": {"score": 0, "status": status, "reasons": [reason]},
        "multi_timeframe_alignment": {"score": 0, "status": status, "reasons": [reason]},
        "risk_invalidation": {"score": 0, "status": "DATA_BLOCK", "reasons": [reason]},
        "ladder_stage": "OBSERVE" if action_policy == "ALLOW" else "INVALIDATE",
        "ladder_buy_policy": {
            "stage": "OBSERVE" if action_policy == "ALLOW" else "INVALIDATE",
            "target_position_ratio": 0.0,
            "max_position_ratio": 0.50,
            "max_step_position_ratio": 0.20,
            "invalidate_on": [reason],
            "simulation_only": True,
            "is_real_trade": False,
        },
        "kline_strategy": {
            "method": "signalops_kline_quality_v1",
            "allow_actions": ["SIM_HOLD", "SIM_BUY", "SIM_T_BUY", "SIM_CLOSE"],
            "requires_backtest_before_review": True,
            "simulation_only": True,
            "is_real_trade": False,
        },
        "buyThresholdDelta": 0.0 if action_policy == "ALLOW" else 0.30,
        "positionRatioMultiplier": 1.0,
        "metrics": {},
        "reasons": [reason],
        "evidence_refs": evidence_refs,
        "simulation_only": True,
        "is_real_trade": False,
    }


def _trend_component(close: float, ma20: Optional[float], ma60: Optional[float], ma20_slope: Optional[float], support20: float) -> Dict[str, Any]:
    reasons: List[str] = []
    if ma20 is None:
        return {"score": 35, "status": "UNKNOWN", "reasons": ["ma20_unavailable"]}
    if close < support20 and (ma20_slope or 0.0) < 0:
        reasons.append("close_below_20d_support_with_falling_ma20")
        return {"score": 10, "status": "DOWN_TREND", "reasons": reasons}
    if close < ma20 and (ma20_slope or 0.0) < -0.002:
        reasons.append("close_below_falling_ma20")
        return {"score": 22, "status": "DOWN_TREND", "reasons": reasons}
    if ma60 is not None and close >= ma20 and ma20 >= ma60 * 0.98 and (ma20_slope or 0.0) >= 0:
        reasons.append("ma20_recovering_near_ma60")
        return {"score": 82, "status": "RECOVERY_TREND", "reasons": reasons}
    if close >= ma20 and (ma20_slope or 0.0) >= -0.002:
        reasons.append("close_back_above_flat_ma20")
        return {"score": 68, "status": "BASE_BUILDING", "reasons": reasons}
    reasons.append("trend_neutral_or_mixed")
    return {"score": 48, "status": "MIXED", "reasons": reasons}


def _bottom_component(**kwargs: Any) -> Dict[str, Any]:
    score = 20
    reasons: List[str] = []
    if kwargs["support_broken"]:
        return {"score": 5, "status": "BROKEN_SUPPORT", "reasons": ["bottom_invalidated_by_support_break"]}
    if kwargs["distance_to_support20"] is not None and 0 <= kwargs["distance_to_support20"] <= 0.06:
        score += 22
        reasons.append("near_20d_support_without_break")
    if kwargs["distance_to_support60"] is not None and 0 <= kwargs["distance_to_support60"] <= 0.10:
        score += 12
        reasons.append("near_60d_support_without_break")
    if kwargs["oversold_rebound"]:
        score += 18
        reasons.append("rsi_oversold_rebound")
    if kwargs["atr_contracting"]:
        score += 14
        reasons.append("atr_contracting")
    if kwargs["volatility_compressed"]:
        score += 12
        reasons.append("bollinger_bandwidth_compressed")
    if kwargs["shrink_stop"]:
        score += 12
        reasons.append("shrink_volume_stop_decline")
    status = "BOTTOM_CANDIDATE" if score >= 60 else "OBSERVE"
    return {"score": min(score, 100), "status": status, "reasons": reasons or ["bottom_evidence_neutral"]}


def _volatility_component(*, volatility_compressed: bool, atr: Optional[float], close: float, support_broken: bool) -> Dict[str, Any]:
    if support_broken:
        return {"score": 10, "status": "BROKEN_SUPPORT", "reasons": ["volatility_invalidated_by_support_break"]}
    atr_pct = _safe_ratio(atr, close) if atr is not None else None
    if volatility_compressed:
        return {"score": 76, "status": "COMPRESSED", "reasons": ["volatility_compression_ready"]}
    if atr_pct is not None and atr_pct >= 0.06:
        return {"score": 34, "status": "HIGH_VOLATILITY", "reasons": ["atr_pct_high"]}
    return {"score": 52, "status": "NORMAL", "reasons": ["volatility_normal"]}


def _volume_component(
    *,
    volume_available: bool,
    volume_ratio: Optional[float],
    shrink_stop: bool,
    breakout_confirmed: bool,
    high_volume_decline: bool,
) -> Dict[str, Any]:
    if high_volume_decline:
        return {"score": 8, "status": "DISTRIBUTION_RISK", "reasons": ["high_volume_decline"]}
    if breakout_confirmed:
        return {"score": 82, "status": "BREAKOUT_CONFIRMED", "reasons": ["volume_breakout_confirmed"]}
    if shrink_stop:
        return {"score": 66, "status": "SHRINK_STOP", "reasons": ["volume_shrink_stop_decline"]}
    if not volume_available:
        return {"score": 42, "status": "UNAVAILABLE", "reasons": ["volume_data_unavailable"]}
    if volume_ratio is not None and volume_ratio >= 1.10:
        return {"score": 58, "status": "ACTIVE", "reasons": ["volume_activity_above_average"]}
    return {"score": 50, "status": "NEUTRAL", "reasons": ["volume_price_neutral"]}


def _multi_timeframe_component(symbol: str, snapshot: Dict[str, Any], evidence_refs: List[Dict[str, Any]]) -> Dict[str, Any]:
    weekly = _period_payload(snapshot, "weekly")
    monthly = _period_payload(snapshot, "monthly")
    evidence_refs.append(_evidence_ref(symbol, "weekly", weekly))
    evidence_refs.append(_evidence_ref(symbol, "monthly", monthly))
    weekly_rows = _rows(weekly)
    monthly_rows = _rows(monthly)
    if str(weekly.get("status") or "").upper() not in READY_STATUSES or len(weekly_rows) < 6:
        return {"score": 42, "status": "INSUFFICIENT", "reasons": ["weekly_kline_insufficient"]}

    weekly_close = weekly_rows[-1]["close"]
    weekly_ma6 = _sma([row["close"] for row in weekly_rows], 6)
    weekly_prev = _window_mean([row["close"] for row in weekly_rows[-10:-4]]) if len(weekly_rows) >= 10 else None
    weekly_slope = _ratio_delta(weekly_ma6, weekly_prev)
    weekly_ok = weekly_ma6 is not None and weekly_close >= weekly_ma6 and (weekly_slope or 0.0) >= -0.005

    monthly_ok = True
    if str(monthly.get("status") or "").upper() in READY_STATUSES and len(monthly_rows) >= 3:
        monthly_closes = [row["close"] for row in monthly_rows]
        monthly_ok = monthly_closes[-1] >= min(monthly_closes[-3:])

    if weekly_ok and monthly_ok:
        return {"score": 76, "status": "ALIGNED", "reasons": ["weekly_monthly_not_deteriorating"]}
    if weekly_ok:
        return {"score": 60, "status": "WEEKLY_RECOVERING", "reasons": ["weekly_recovering_monthly_unconfirmed"]}
    return {"score": 34, "status": "DIVERGED", "reasons": ["weekly_cycle_not_confirmed"]}


def _policy_from_score(
    *,
    final_score: int,
    risk_invalidated: bool,
    breakout_confirmed: bool,
    close_above_ma20: bool,
    multi_status: str,
) -> tuple[str, str]:
    if risk_invalidated:
        return "HOLD", "INVALIDATE"
    if final_score >= 78 and breakout_confirmed and multi_status in {"ALIGNED", "WEEKLY_RECOVERING"}:
        return "LADDER_BUY", "FOLLOW_THROUGH"
    if final_score >= 66 and close_above_ma20:
        return "LADDER_BUY", "CONFIRM"
    if final_score >= 55:
        return "PROBE", "PROBE"
    return "HOLD", "OBSERVE"


def _grade(final_score: int, action_policy: str) -> str:
    if action_policy == "HOLD" and final_score < 55:
        return "BLOCKED"
    if final_score >= 80:
        return "A"
    if final_score >= 68:
        return "B"
    if final_score >= 55:
        return "C"
    return "D"


def _buy_threshold_delta(action_policy: str, ladder_stage: str) -> float:
    if action_policy == "HOLD":
        return 0.30
    if ladder_stage == "FOLLOW_THROUGH":
        return -0.10
    if ladder_stage == "CONFIRM":
        return -0.05
    return 0.0


def _risk_reasons(support_broken: bool, high_volume_decline: bool, lower_lows: bool) -> List[str]:
    reasons: List[str] = []
    if support_broken:
        reasons.append("close_below_20d_support")
    if high_volume_decline:
        reasons.append("high_volume_decline")
    if lower_lows:
        reasons.append("consecutive_lower_lows")
    return reasons


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


def _rsi_series(closes: List[float], window: int) -> List[float]:
    if len(closes) <= window:
        return []
    values: List[float] = []
    for index in range(window, len(closes)):
        changes = [closes[pos] - closes[pos - 1] for pos in range(index - window + 1, index + 1)]
        gains = [max(change, 0.0) for change in changes]
        losses = [abs(min(change, 0.0)) for change in changes]
        avg_gain = mean(gains)
        avg_loss = mean(losses)
        if avg_loss == 0:
            values.append(100.0)
        else:
            rs = avg_gain / avg_loss
            values.append(100.0 - (100.0 / (1.0 + rs)))
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
    values: List[float] = []
    for index in range(window, len(true_ranges) + 1):
        values.append(mean(true_ranges[index - window:index]))
    return values


def _bollinger_widths(closes: List[float], window: int) -> List[float]:
    if len(closes) < window:
        return []
    values: List[float] = []
    for index in range(window, len(closes) + 1):
        sample = closes[index - window:index]
        mid = mean(sample)
        if mid <= 0:
            continue
        variance = mean([(value - mid) ** 2 for value in sample])
        std = variance ** 0.5
        values.append((4 * std) / mid)
    return values


def _rank_leq(values: List[float], current: Optional[float]) -> Optional[float]:
    if current is None or not values:
        return None
    return sum(1 for value in values if value <= current) / len(values)


def _volume_ratio(rows: List[Dict[str, float]], short_window: int, long_window: int) -> Optional[float]:
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
        "source_type": "KLINE",
        "source_id": f"{symbol}:{period}",
        "label": f"kline_{period}_status:{status}",
        "quality": "MEDIUM" if status in READY_STATUSES else "LOW",
    }


def _number(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _round_or_none(value: Optional[float]) -> Optional[float]:
    return round(value, 6) if value is not None else None
