import hashlib
import json
import random
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from ..models.backtest import BacktestReport, BacktestTradeItem, BacktestSignalItem, BacktestComparison


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generate_id(prefix: str) -> str:
    return f"{prefix}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


DEFAULT_PRICE_LIMIT = 0.10
T_PLUS_ONE_DAYS = 1
BACKTEST_ENGINE_VERSION = "research_metadata_v2"
MIN_MEDIUM_SAMPLE_DAYS = 20
MIN_MEDIUM_SAMPLE_TRADES = 10
MIN_STRONG_SAMPLE_DAYS = 60
MIN_STRONG_SAMPLE_TRADES = 30
MIN_STRONG_SAMPLE_SIGNALS = 10


def _parse_date(ds: str) -> datetime:
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(ds.strip(), fmt)
        except ValueError:
            pass
    raise ValueError(f"Cannot parse date: {ds}")


def _check_t_plus_one(
    direction: str,
    entry_date: datetime,
    current_date: datetime,
    held_shares: int,
    quantity: int,
) -> Tuple[bool, str]:
    if direction.upper() != "SELL":
        return True, ""
    if held_shares <= 0:
        return True, ""
    if (current_date - entry_date).days < T_PLUS_ONE_DAYS:
        return False, "T+1 rule: cannot sell within 1 day of purchase"
    return True, ""


def _check_price_limit(price: float, prev_close: float, limit_pct: float = DEFAULT_PRICE_LIMIT) -> Tuple[bool, str]:
    if prev_close <= 0:
        return True, ""
    lower = prev_close * (1 - limit_pct)
    upper = prev_close * (1 + limit_pct)
    if price < lower:
        return False, f"Price {price:.2f} below limit-down {lower:.2f}"
    if price > upper:
        return False, f"Price {price:.2f} above limit-up {upper:.2f}"
    return True, ""


def _apply_slippage(price: float, direction: str, slippage_bps: float) -> float:
    factor = 1 + (slippage_bps / 10000) if direction.upper() == "BUY" else 1 - (slippage_bps / 10000)
    return round(price * factor, 2)


def _trade_cost(amount: float, direction: str, commission_bps: float, stamp_tax_bps: float, min_commission: float) -> Tuple[float, float, float]:
    commission = amount * max(commission_bps, 0.0) / 10000
    if commission_bps > 0 and amount > 0:
        commission = max(commission, max(min_commission, 0.0))
    stamp_tax = amount * max(stamp_tax_bps, 0.0) / 10000 if direction.upper() == "SELL" else 0.0
    total = commission + stamp_tax
    return round(total, 4), round(commission, 4), round(stamp_tax, 4)


def _build_equity_snapshot(date_str: str, capital: float, position_pnl: float) -> Dict[str, Any]:
    return {"date": date_str, "capital": round(capital, 2), "position_pnl": round(position_pnl, 2)}


def _compute_drawdown(equity_curve: List[Dict[str, Any]]) -> Tuple[float, float]:
    if not equity_curve:
        return 0.0, 0.0
    peak = equity_curve[0]["capital"]
    max_dd = 0.0
    max_dd_pct = 0.0
    for pt in equity_curve:
        capital = pt["capital"]
        if capital > peak:
            peak = capital
        dd = peak - capital
        dd_pct = dd / peak if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct
    return round(max_dd, 2), round(max_dd_pct, 4)


def _compute_sharpe(daily_returns: List[float]) -> float:
    if not daily_returns or len(daily_returns) < 2:
        return 0.0
    mean_r = sum(daily_returns) / len(daily_returns)
    var_r = sum((r - mean_r) ** 2 for r in daily_returns) / (len(daily_returns) - 1) if len(daily_returns) > 1 else 0.0
    std_r = var_r ** 0.5
    if std_r == 0:
        return 0.0
    return round((mean_r / std_r) * (252 ** 0.5), 2)


def _payload_hash(value: Any) -> str:
    payload = json.dumps(value or {}, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _parameter_hash(parameters: Dict[str, Any]) -> str:
    return _payload_hash(parameters or {})


def _experiment_package_hash(parameters: Dict[str, Any], symbol: str, start_date: str, end_date: str) -> str:
    configured = str(parameters.get("experiment_package_hash") or "").strip()
    if configured:
        return configured
    package = {
        "symbol": symbol,
        "start_date": start_date,
        "end_date": end_date,
        "parameters": {
            key: value
            for key, value in (parameters or {}).items()
            if key != "experiment_package_hash"
        },
    }
    return _parameter_hash(package)


def _walk_forward_contract(parameters: Dict[str, Any]) -> Dict[str, Any]:
    value = parameters.get("walk_forward", parameters.get("walkForward", parameters.get("walk_forward_validation")))
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, list):
        return {"enabled": bool(value), "windows": value}
    if isinstance(value, bool):
        return {"enabled": value}
    if value not in (None, ""):
        return {"enabled": True, "mode": str(value)}
    return {"enabled": False, "reason": "not_configured"}


def _parameter_scan_contract(parameters: Dict[str, Any]) -> Dict[str, Any]:
    value = parameters.get("parameter_scan", parameters.get("parameterScan", parameters.get("param_scan")))
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, list):
        return {"enabled": bool(value), "grid": value, "trialCount": len(value)}
    if isinstance(value, bool):
        return {"enabled": value}
    if value not in (None, ""):
        return {"enabled": True, "mode": str(value)}
    try:
        trial_count = int(parameters.get("trial_count") or parameters.get("parameter_trial_count") or 0)
    except (TypeError, ValueError):
        trial_count = 0
    if trial_count > 1:
        return {"enabled": True, "trialCount": trial_count, "source": "trial_count"}
    return {"enabled": False, "reason": "not_configured"}


def normalize_research_contract_parameters(
    parameters: Optional[Dict[str, Any]],
    symbol: str,
    start_date: str,
    end_date: str,
) -> Dict[str, Any]:
    normalized = dict(parameters or {})
    normalized["simulation_only"] = True
    normalized["is_real_trade"] = False
    normalized.setdefault("benchmark_symbol", symbol)
    normalized.setdefault("out_of_sample_start", "")
    normalized.setdefault("out_of_sample_end", "")
    normalized.setdefault("walk_forward", _walk_forward_contract(normalized))
    normalized.setdefault("parameter_scan", _parameter_scan_contract(normalized))
    if not str(normalized.get("experiment_package_hash") or "").strip():
        normalized["experiment_package_hash"] = _experiment_package_hash(
            normalized,
            symbol,
            start_date,
            end_date,
        )
    return normalized


def _canonical_rows(rows: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    canonical: List[Dict[str, Any]] = []
    for row in rows or []:
        if isinstance(row, dict):
            canonical.append(dict(row))
        else:
            canonical.append({"value": row})
    return sorted(
        canonical,
        key=lambda row: (
            str(row.get("date") or row.get("timestamp") or ""),
            str(row.get("symbol") or ""),
            str(row.get("signal_id") or row.get("record_id") or ""),
        ),
    )


def _backtest_package_hashes(
    *,
    symbol: str,
    start_date: str,
    end_date: str,
    parameters: Dict[str, Any],
    market_data: List[Dict[str, Any]],
    signals: List[Dict[str, Any]],
    benchmark_market_data: Optional[List[Dict[str, Any]]],
) -> Dict[str, str]:
    parameter_hash = _parameter_hash(parameters)
    market_data_hash = _payload_hash(_canonical_rows(market_data))
    signal_package_hash = _payload_hash(_canonical_rows(signals))
    benchmark_data_hash = _payload_hash(_canonical_rows(benchmark_market_data))
    data_package_hash = _payload_hash(
        {
            "symbol": symbol,
            "start_date": start_date,
            "end_date": end_date,
            "parameterHash": parameter_hash,
            "marketDataHash": market_data_hash,
            "signalPackageHash": signal_package_hash,
            "benchmarkDataHash": benchmark_data_hash,
        }
    )
    return {
        "parameterHash": parameter_hash,
        "marketDataHash": market_data_hash,
        "signalPackageHash": signal_package_hash,
        "benchmarkDataHash": benchmark_data_hash,
        "dataPackageHash": data_package_hash,
    }


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _round_pct(value: float) -> float:
    return round(value, 4)


def _benchmark_snapshot(
    symbol: str,
    trading_dates: List[str],
    data_by_date: Dict[str, Dict[str, Any]],
    data_source: str,
    parameters: Dict[str, Any],
    benchmark_market_data: Optional[List[Dict[str, Any]]] = None,
    benchmark_data_source: str = "",
    benchmark_error: Optional[str] = None,
) -> Dict[str, Any]:
    benchmark_symbol = str(parameters.get("benchmark_symbol") or symbol or "").strip()
    if not trading_dates:
        return {
            "type": "symbol_buy_hold",
            "symbol": benchmark_symbol,
            "available": False,
            "reason": "No trading dates in sample window.",
        }

    requires_external_benchmark = bool(benchmark_symbol and benchmark_symbol != symbol)
    benchmark_by_date: Dict[str, Dict[str, Any]] = {}
    benchmark_dates: List[str] = []
    benchmark_source = benchmark_data_source or data_source
    benchmark_type = str(parameters.get("benchmark_type") or ("external_buy_hold" if requires_external_benchmark else "symbol_buy_hold"))
    benchmark_note = "Uses tested symbol buy-and-hold baseline."
    if benchmark_market_data:
        for row in benchmark_market_data:
            ds = str(row.get("date", "")).strip()
            if ds:
                benchmark_by_date[ds] = row
        benchmark_dates = [ds for ds in sorted(benchmark_by_date) if trading_dates[0] <= ds <= trading_dates[-1]]
        benchmark_source = benchmark_data_source or "CUSTOM"
        benchmark_note = "Uses independent benchmark market data."
    elif requires_external_benchmark:
        return {
            "type": benchmark_type,
            "symbol": benchmark_symbol,
            "startDate": trading_dates[0],
            "endDate": trading_dates[-1],
            "dataSource": benchmark_source or "UNAVAILABLE",
            "dataError": benchmark_error,
            "available": False,
            "reason": benchmark_error or "Benchmark market data is unavailable for the configured benchmark symbol.",
        }
    else:
        benchmark_by_date = data_by_date
        benchmark_dates = trading_dates

    if not benchmark_dates:
        return {
            "type": benchmark_type,
            "symbol": benchmark_symbol,
            "startDate": trading_dates[0],
            "endDate": trading_dates[-1],
            "dataSource": benchmark_source or "UNAVAILABLE",
            "dataError": benchmark_error,
            "available": False,
            "reason": "Benchmark market data has no rows in the sample window.",
        }

    first = benchmark_by_date.get(benchmark_dates[0], {})
    last = benchmark_by_date.get(benchmark_dates[-1], {})
    start_price = _as_float(first.get("close") or first.get("open"))
    end_price = _as_float(last.get("close") or last.get("open"))
    return_pct = ((end_price - start_price) / start_price * 100) if start_price > 0 else 0.0
    available = start_price > 0 and end_price > 0
    return {
        "type": benchmark_type,
        "symbol": benchmark_symbol,
        "startDate": benchmark_dates[0],
        "endDate": benchmark_dates[-1],
        "startPrice": round(start_price, 4),
        "endPrice": round(end_price, 4),
        "returnPct": round(return_pct, 2),
        "dataSource": benchmark_source,
        "dataError": benchmark_error,
        "available": available,
        "reason": "" if available else "Benchmark start or end price is unavailable.",
        "note": benchmark_note,
    }


def _out_of_sample_window(parameters: Dict[str, Any], sample_start: str, sample_end: str) -> Dict[str, Any]:
    start = str(parameters.get("out_of_sample_start") or "").strip()
    end = str(parameters.get("out_of_sample_end") or "").strip()
    configured = bool(start and end)
    return {
        "configured": configured,
        "startDate": start,
        "endDate": end,
        "overlapsSample": bool(configured and not (end < sample_start or start > sample_end)),
        "reason": "" if configured else "No out-of-sample window configured; result is in-sample only.",
    }


def _research_contract(
    parameters: Dict[str, Any],
    *,
    benchmark: Dict[str, Any],
    out_of_sample: Dict[str, Any],
    sample_start: str,
    sample_end: str,
) -> Dict[str, Any]:
    walk_forward = _walk_forward_contract(parameters)
    parameter_scan = _parameter_scan_contract(parameters)
    return {
        "walk_forward": walk_forward,
        "walk_forward_configured": bool(walk_forward.get("enabled")),
        "parameter_scan": parameter_scan,
        "parameter_scan_configured": bool(parameter_scan.get("enabled")),
        "out_of_sample_start": out_of_sample.get("startDate") or "",
        "out_of_sample_end": out_of_sample.get("endDate") or "",
        "out_of_sample_configured": bool(out_of_sample.get("configured")),
        "out_of_sample_overlaps_sample": bool(out_of_sample.get("overlapsSample")),
        "benchmark_symbol": benchmark.get("symbol") or parameters.get("benchmark_symbol") or "",
        "experiment_package_hash": parameters.get("experiment_package_hash") or "",
        "sample_start": sample_start,
        "sample_end": sample_end,
    }


def _first_bool(source: Dict[str, Any], *keys: str) -> Optional[bool]:
    for key in keys:
        value = source.get(key)
        if isinstance(value, bool):
            return value
    return None


def _signalops_report_metadata(parameters: Dict[str, Any]) -> Dict[str, Any]:
    context = parameters.get("signalops_context") if isinstance(parameters.get("signalops_context"), dict) else {}
    version = context.get("signalOpsVersion") or parameters.get("signalops_version")
    if not version:
        return {}
    metadata = {
        "signalOpsVersion": version,
        "signalOpsSourceMode": context.get("signalOpsSourceMode") or parameters.get("signalops_source_mode") or "AUTO",
        "simulationOnly": True,
        "isRealTrade": False,
        "executionRules": context.get("executionRules") if isinstance(context.get("executionRules"), dict) else {},
        "signalBoundary": context.get("signalBoundary") if isinstance(context.get("signalBoundary"), dict) else {},
        "cleanedRecordCount": int(context.get("cleanedRecordCount") or 0),
        "tradeRecordCount": int(context.get("tradeRecordCount") or 0),
        "compressedObservationCount": int(context.get("compressedObservationCount") or 0),
        "reviewQueueSyncStatus": context.get("reviewQueueSyncStatus") or "NOT_SYNCED",
    }
    reported_simulation_only = _first_bool(context, "simulationOnly", "simulation_only")
    reported_is_real_trade = _first_bool(context, "isRealTrade", "is_real_trade")
    if reported_simulation_only is False:
        metadata["reportedSimulationOnly"] = reported_simulation_only
    if reported_is_real_trade is True:
        metadata["reportedIsRealTrade"] = reported_is_real_trade
    return metadata


def _bottom_research_report_metadata(parameters: Dict[str, Any]) -> Dict[str, Any]:
    context = (
        parameters.get("mfe_mae_research_context")
        if isinstance(parameters.get("mfe_mae_research_context"), dict)
        else parameters.get("bottom_research_context")
        if isinstance(parameters.get("bottom_research_context"), dict)
        else {}
    )
    version = context.get("model_version") or parameters.get("mfe_mae_research_model_version") or parameters.get("bottom_research_model_version")
    if not version:
        return {}
    metadata = {
        "mfeMaeResearchVersion": version,
        "mfeMaeResearchSignalHash": parameters.get("mfe_mae_research_signal_hash")
        or parameters.get("bottom_research_signal_hash")
        or "",
        "mfeMaeResearchSignalCount": int(
            parameters.get("mfe_mae_research_signal_count")
            if parameters.get("mfe_mae_research_signal_count") is not None
            else parameters.get("bottom_research_signal_count") or 0
        ),
        "mfeMaeResearchDataWindow": parameters.get("mfe_mae_research_data_window")
        or parameters.get("bottom_research_data_window")
        or {},
        "bottomResearchVersion": version,
        "bottomResearchSignalHash": parameters.get("bottom_research_signal_hash") or "",
        "bottomResearchSignalCount": int(parameters.get("bottom_research_signal_count") or 0),
        "bottomResearchDataWindow": parameters.get("bottom_research_data_window") or {},
        "simulationOnly": True,
        "isRealTrade": False,
        "tradeActionPolicy": context.get("trade_action_policy") or "REVIEW_ONLY_NOT_TRADE_INSTRUCTION",
    }
    reported_simulation_only = _first_bool(context, "simulationOnly", "simulation_only")
    reported_is_real_trade = _first_bool(context, "isRealTrade", "is_real_trade")
    if reported_simulation_only is False:
        metadata["reportedSimulationOnly"] = reported_simulation_only
    if reported_is_real_trade is True:
        metadata["reportedIsRealTrade"] = reported_is_real_trade
    return metadata


def _sample_quality(
    *,
    data_points: int,
    trading_days: int,
    total_trades: int,
    total_signals: int,
    data_source: str,
    signal_source: str,
    out_of_sample: Dict[str, Any],
    walk_forward: Dict[str, Any],
    parameter_scan: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any], List[str]]:
    limitations: List[str] = []
    if trading_days < MIN_MEDIUM_SAMPLE_DAYS:
        limitations.append(f"Sample has only {trading_days} trading days; minimum medium threshold is {MIN_MEDIUM_SAMPLE_DAYS}.")
    if total_trades < MIN_MEDIUM_SAMPLE_TRADES:
        limitations.append(f"Sample has only {total_trades} executed trades; minimum medium threshold is {MIN_MEDIUM_SAMPLE_TRADES}.")
    if total_signals < MIN_STRONG_SAMPLE_SIGNALS:
        limitations.append(f"Sample has only {total_signals} signals; strong evidence expects at least {MIN_STRONG_SAMPLE_SIGNALS}.")
    if str(data_source).upper() in {"MOCK", "MOCK_FALLBACK"}:
        limitations.append(f"Market data source is {data_source}; use live/verified data before treating this as strong evidence.")
    if str(signal_source).upper() in {"MOCK", "NONE"}:
        limitations.append(f"Signal source is {signal_source}; use SignalOps or audited signals for research claims.")
    if not out_of_sample.get("configured"):
        limitations.append("No out-of-sample segment is configured.")
    if not walk_forward.get("enabled"):
        limitations.append("No walk-forward validation is configured.")
    if not parameter_scan.get("enabled"):
        limitations.append("No parameter scan is configured.")

    if (
        trading_days >= MIN_STRONG_SAMPLE_DAYS
        and total_trades >= MIN_STRONG_SAMPLE_TRADES
        and total_signals >= MIN_STRONG_SAMPLE_SIGNALS
        and str(data_source).upper() not in {"MOCK", "MOCK_FALLBACK"}
        and str(signal_source).upper() not in {"MOCK", "NONE"}
        and out_of_sample.get("configured")
        and walk_forward.get("enabled")
        and parameter_scan.get("enabled")
    ):
        grade = "HIGH"
        confidence = 0.82
    elif trading_days >= MIN_MEDIUM_SAMPLE_DAYS and total_trades >= MIN_MEDIUM_SAMPLE_TRADES:
        grade = "MEDIUM"
        confidence = 0.55
    else:
        grade = "LOW"
        confidence = 0.25

    statistical = {
        "grade": grade,
        "confidence": confidence,
        "sampleSize": {
            "dataPoints": data_points,
            "tradingDays": trading_days,
            "signals": total_signals,
            "trades": total_trades,
        },
        "thresholds": {
            "mediumTradingDays": MIN_MEDIUM_SAMPLE_DAYS,
            "mediumTrades": MIN_MEDIUM_SAMPLE_TRADES,
            "strongTradingDays": MIN_STRONG_SAMPLE_DAYS,
            "strongTrades": MIN_STRONG_SAMPLE_TRADES,
            "strongSignals": MIN_STRONG_SAMPLE_SIGNALS,
        },
        "warnings": limitations,
    }
    review_grade = "MEDIUM" if grade == "HIGH" else grade
    evidence = {
        "grade": review_grade,
        "calculatedCanSupportResearchVerdict": grade == "HIGH",
        "canSupportResearchVerdict": False,
        "weakSample": True,
        "researchUsage": "supporting_only",
        "limitations": limitations,
    }
    if review_grade != grade:
        evidence["reportedGrade"] = grade
    return statistical, evidence, limitations


def _clamp_component_score(value: float) -> int:
    return int(round(max(0.0, min(value, 100.0))))


def _research_grade_score(
    *,
    trading_days: int,
    total_trades: int,
    total_signals: int,
    benchmark: Dict[str, Any],
    out_of_sample: Dict[str, Any],
    walk_forward: Dict[str, Any],
    parameter_scan: Dict[str, Any],
    max_drawdown_pct: float,
    execution_constraints: Dict[str, Any],
    statistical_confidence: Dict[str, Any],
) -> Dict[str, Any]:
    sample_ratio = (
        min(trading_days / MIN_STRONG_SAMPLE_DAYS, 1.0)
        + min(total_trades / MIN_STRONG_SAMPLE_TRADES, 1.0)
        + min(total_signals / MIN_STRONG_SAMPLE_SIGNALS, 1.0)
    ) / 3
    sample_score = _clamp_component_score(sample_ratio * 100)

    out_of_sample_configured = bool(out_of_sample.get("configured"))
    out_of_sample_score = 100 if out_of_sample_configured and out_of_sample.get("overlapsSample") else (40 if out_of_sample_configured else 0)

    walk_forward_enabled = bool(walk_forward.get("enabled"))
    walk_forward_score = 100 if walk_forward_enabled and (walk_forward.get("windows") or walk_forward.get("folds") or walk_forward.get("validation_window")) else (70 if walk_forward_enabled else 0)

    parameter_scan_enabled = bool(parameter_scan.get("enabled"))
    scan_grid = parameter_scan.get("grid")
    trial_count = _as_float(parameter_scan.get("trialCount") or parameter_scan.get("trial_count"))
    scan_width = len(scan_grid) if isinstance(scan_grid, list) else len(scan_grid) if isinstance(scan_grid, dict) else 0
    if parameter_scan_enabled and (trial_count >= 3 or scan_width >= 2):
        parameter_scan_score = 100
    elif parameter_scan_enabled:
        parameter_scan_score = 70
    else:
        parameter_scan_score = 0

    benchmark_available = bool(benchmark.get("available"))
    excess_return = _as_float(benchmark.get("excessReturnPct"))
    if not benchmark_available:
        benchmark_score = 0
    elif excess_return >= 2:
        benchmark_score = 100
    elif excess_return >= 0:
        benchmark_score = 70
    else:
        benchmark_score = _clamp_component_score(70 + excess_return * 10)

    if max_drawdown_pct <= 0.05:
        drawdown_score = 100
    elif max_drawdown_pct <= 0.15:
        drawdown_score = _clamp_component_score(100 - ((max_drawdown_pct - 0.05) / 0.10) * 30)
    elif max_drawdown_pct <= 0.30:
        drawdown_score = _clamp_component_score(70 - ((max_drawdown_pct - 0.15) / 0.15) * 45)
    else:
        drawdown_score = 20

    blocked = int(execution_constraints.get("tPlusOneBlocked") or 0) + int(execution_constraints.get("priceLimitBlocked") or 0)
    execution_denominator = max(total_signals, total_trades, 1)
    execution_score = _clamp_component_score(100 - (blocked / execution_denominator) * 100)

    confidence = _as_float(statistical_confidence.get("confidence"))
    confidence_grade = str(statistical_confidence.get("grade") or "LOW").upper()
    confidence_score = _clamp_component_score(confidence * 100)
    if confidence_grade == "HIGH":
        confidence_score = max(confidence_score, 80)
    elif confidence_grade == "MEDIUM":
        confidence_score = max(confidence_score, 55)

    components = [
        {"key": "sample_count", "label": "Sample count", "score": sample_score, "weight": 18, "value": {"tradingDays": trading_days, "trades": total_trades, "signals": total_signals}},
        {"key": "out_of_sample", "label": "Out-of-sample coverage", "score": out_of_sample_score, "weight": 14, "value": out_of_sample},
        {"key": "walk_forward", "label": "Walk-forward validation", "score": walk_forward_score, "weight": 12, "value": walk_forward},
        {"key": "parameter_scan", "label": "Parameter scan", "score": parameter_scan_score, "weight": 10, "value": parameter_scan},
        {"key": "benchmark_excess", "label": "Benchmark excess return", "score": benchmark_score, "weight": 16, "value": {"available": benchmark_available, "excessReturnPct": benchmark.get("excessReturnPct")}},
        {"key": "max_drawdown", "label": "Maximum drawdown", "score": drawdown_score, "weight": 12, "value": {"maxDrawdownPct": max_drawdown_pct}},
        {"key": "execution_constraints", "label": "Execution constraints", "score": execution_score, "weight": 10, "value": {"blockedSignals": blocked, "totalSignals": total_signals}},
        {"key": "statistical_confidence", "label": "Statistical confidence", "score": confidence_score, "weight": 8, "value": statistical_confidence},
    ]
    total_weight = sum(int(component["weight"]) for component in components) or 1
    score = _clamp_component_score(sum(float(component["score"]) * int(component["weight"]) for component in components) / total_weight)
    calculated_band = "RESEARCH_GRADE" if score >= 80 else ("REVIEWABLE" if score >= 60 else "SUPPORTING_ONLY")
    band = "REVIEWABLE" if calculated_band == "RESEARCH_GRADE" else calculated_band
    return {
        "score": score,
        "band": band,
        "calculatedBand": calculated_band,
        "researchUsage": "supporting_only",
        "canSupportResearchVerdict": False,
        "supportingOnly": True,
        "components": components,
        "thresholds": {
            "researchGrade": 80,
            "reviewable": 60,
        },
    }


def run_backtest(
    symbol: str,
    stock_name: str,
    start_date: str,
    end_date: str,
    initial_capital: float,
    market_data: List[Dict[str, Any]],
    signals: List[Dict[str, Any]],
    patch_params: Optional[Dict[str, Any]] = None,
    data_source: str = "MOCK",
    data_error: Optional[str] = None,
    signal_source: str = "MOCK",
    benchmark_market_data: Optional[List[Dict[str, Any]]] = None,
    benchmark_data_source: str = "",
    benchmark_error: Optional[str] = None,
) -> BacktestReport:
    if not market_data:
        return BacktestReport(data_source=data_source, data_error=data_error, data_points=0, signal_source=signal_source)

    param = normalize_research_contract_parameters(patch_params, symbol, start_date, end_date)
    package_hashes = _backtest_package_hashes(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        parameters=param,
        market_data=market_data,
        signals=signals,
        benchmark_market_data=benchmark_market_data,
    )
    slippage_bps = _as_float(param.get("slippage_bps"), 10.0)
    commission_bps = _as_float(param.get("commission_bps"), 0.0)
    stamp_tax_bps = _as_float(param.get("stamp_tax_bps"), 0.0)
    min_commission = _as_float(param.get("min_commission"), 0.0)
    price_limit_pct = _as_float(param.get("price_limit_pct"), DEFAULT_PRICE_LIMIT)
    t_plus_one = param.get("t_plus_one", True)
    signal_min_strength = _as_float(param.get("signal_min_strength"), 0.3)
    manual_review_accepted = param.get("manual_review_accepted", True)
    trade_quantity_pct = _as_float(param.get("trade_quantity_pct"), 0.20)

    run_id = _generate_id("BT")

    equity_curve: List[Dict[str, Any]] = []
    trade_log: List[BacktestTradeItem] = []
    signal_log: List[BacktestSignalItem] = []

    capital = initial_capital
    positions: Dict[str, Dict[str, Any]] = {}
    total_slippage = 0.0
    total_transaction_cost = 0.0
    total_commission = 0.0
    total_stamp_tax = 0.0
    t_plus_one_blocked = 0
    price_limit_blocked = 0
    daily_returns: List[float] = []
    prev_capital = initial_capital

    start_dt = _parse_date(start_date)
    end_dt = _parse_date(end_date)
    start_key = start_dt.strftime("%Y-%m-%d")
    end_key = end_dt.strftime("%Y-%m-%d")

    data_by_date: Dict[str, Dict[str, Any]] = {}
    for row in market_data:
        ds = str(row.get("date", "")).strip()
        if ds:
            data_by_date[ds] = row
    trading_dates = [ds for ds in sorted(data_by_date) if start_key <= ds <= end_key]
    if not trading_dates:
        return BacktestReport(
            data_source=data_source,
            data_error=data_error or "No market data in requested backtest range.",
            data_points=len(market_data),
            signal_source=signal_source,
            signal_source_count=len(signals),
        )

    signals_by_date: Dict[str, List[Dict[str, Any]]] = {}
    for sig in signals:
        ds = str(sig.get("timestamp", "")).strip()[:10]
        if ds:
            signals_by_date.setdefault(ds, []).append(sig)

    last_close = 0.0
    for ds in trading_dates:
        current_dt = _parse_date(ds)
        row = data_by_date[ds]
        prev_close = float(row.get("prev_close", 0)) if row else 0.0
        close = float(row.get("close", 0)) if row else 0.0
        open_price = float(row.get("open", 0)) if row else 0.0
        if close <= 0:
            continue
        last_close = close

        day_signals = signals_by_date.get(ds, [])
        day_pnl = 0.0

        for sig in day_signals:
            signal_type = str(sig.get("signal_type", "BUY"))
            direction = str(sig.get("direction", "BUY")).upper()
            strength = float(sig.get("strength", 0.5))
            source_node = str(sig.get("source_node", ""))

            signal_item = BacktestSignalItem(
                signal_id=_generate_id("SIG"),
                run_id=run_id,
                signal_type=signal_type,
                direction=direction,
                strength=strength,
                price=close,
                timestamp=sig.get("timestamp", ds),
                source_node=source_node,
                metadata_json=sig.get("metadata_json", {}),
            )
            signal_log.append(signal_item)

            if strength < signal_min_strength:
                continue
            if direction in ("HOLD", "WAIT", "WATCH"):
                continue

            use_price = open_price if open_price > 0 else close
            if use_price <= 0:
                continue

            limit_ok, limit_msg = _check_price_limit(use_price, prev_close, price_limit_pct)
            if not limit_ok:
                price_limit_blocked += 1
                continue

            exec_price = _apply_slippage(use_price, direction, slippage_bps)
            sl = abs(exec_price - use_price)

            quantity = max(1, int((capital * trade_quantity_pct) / exec_price))

            if direction == "SELL":
                for pos_sym, pos in positions.items():
                    if pos["quantity"] > 0:
                        if t_plus_one:
                            t_ok, t_msg = _check_t_plus_one(
                                "SELL",
                                _parse_date(pos["entry_date"]),
                                current_dt,
                                pos["quantity"],
                                quantity,
                            )
                            if not t_ok:
                                t_plus_one_blocked += 1
                                continue
                        sell_qty = min(quantity, pos["quantity"])
                        sell_amount = exec_price * sell_qty
                        trade_cost, commission, stamp_tax = _trade_cost(
                            sell_amount,
                            "SELL",
                            commission_bps,
                            stamp_tax_bps,
                            min_commission,
                        )
                        pnl = (exec_price - pos["entry_price"]) * sell_qty - trade_cost
                        day_pnl += pnl
                        total_slippage += sl * sell_qty
                        total_transaction_cost += trade_cost
                        total_commission += commission
                        total_stamp_tax += stamp_tax
                        capital += sell_amount - trade_cost
                        pos["quantity"] -= sell_qty
                        trade_log.append(BacktestTradeItem(
                            trade_id=_generate_id("TRD"),
                            run_id=run_id,
                            direction="SELL",
                            price=exec_price,
                            quantity=sell_qty,
                            amount=sell_amount,
                            slippage=sl,
                            timestamp=ds,
                            reason=f"Signal: {signal_type}",
                            realized_pnl=pnl,
                        ))
                continue

            if direction in ("BUY", "LONG"):
                cost = exec_price * quantity
                if cost > capital * 0.95:
                    quantity = max(1, int((capital * 0.95) / exec_price))
                    cost = exec_price * quantity
                trade_cost, commission, stamp_tax = _trade_cost(
                    cost,
                    "BUY",
                    commission_bps,
                    stamp_tax_bps,
                    min_commission,
                )
                if cost + trade_cost > capital * 0.95:
                    quantity = max(1, int((capital * 0.95) / (exec_price * (1 + commission_bps / 10000))))
                    cost = exec_price * quantity
                    trade_cost, commission, stamp_tax = _trade_cost(
                        cost,
                        "BUY",
                        commission_bps,
                        stamp_tax_bps,
                        min_commission,
                    )
                capital -= cost + trade_cost
                total_slippage += sl * quantity
                total_transaction_cost += trade_cost
                total_commission += commission
                total_stamp_tax += stamp_tax
                positions.setdefault(symbol, {"quantity": 0, "entry_price": 0.0, "entry_date": ds})
                positions[symbol]["quantity"] += quantity
                positions[symbol]["entry_price"] = (
                    (positions[symbol]["entry_price"] * (positions[symbol]["quantity"] - quantity) + cost)
                    / positions[symbol]["quantity"]
                    if positions[symbol]["quantity"] > 0
                    else exec_price
                )
                positions[symbol]["entry_date"] = ds
                trade_log.append(BacktestTradeItem(
                    trade_id=_generate_id("TRD"),
                    run_id=run_id,
                    direction="BUY",
                    price=exec_price,
                    quantity=quantity,
                    amount=cost,
                    slippage=sl,
                    timestamp=ds,
                    reason=f"Signal: {signal_type}",
                    realized_pnl=None,
                ))

        position_value = sum(
            pos["quantity"] * close for pos in positions.values() if pos["quantity"] > 0
        )
        total_equity = capital + position_value
        equity_curve.append(_build_equity_snapshot(ds, total_equity, position_value))

        if prev_capital > 0:
            daily_returns.append((total_equity - prev_capital) / prev_capital)
        prev_capital = total_equity

    final_position_value = sum(
        pos["quantity"] * last_close for pos in positions.values() if pos["quantity"] > 0
    )
    final_capital = capital + final_position_value
    total_pnl = final_capital - initial_capital
    total_return_pct = (total_pnl / initial_capital * 100) if initial_capital > 0 else 0.0

    winning = sum(1 for t in trade_log if (t.realized_pnl or 0) > 0)
    losing = sum(1 for t in trade_log if (t.realized_pnl or 0) < 0)
    total_trades = len(trade_log)
    hit_rate = round(winning / total_trades, 4) if total_trades > 0 else 0.0

    buy_sigs = sum(1 for s in signal_log if s.direction in ("BUY", "LONG"))
    sell_sigs = sum(1 for s in signal_log if s.direction in ("SELL", "SHORT"))
    false_positives = sum(1 for t in trade_log if t.direction == "SELL" and (t.realized_pnl or 0) < 0)
    false_positive_rate = round(false_positives / buy_sigs, 4) if buy_sigs > 0 else 0.0

    max_dd, max_dd_pct = _compute_drawdown(equity_curve)
    sharpe = _compute_sharpe(daily_returns)

    manual_pass_rate = 0.75 if manual_review_accepted else 0.0
    if total_trades > 0:
        manual_pass_rate = round(
            (winning + (false_positives * 0.5)) / total_trades, 2
        )

    actual_start = trading_dates[0] if trading_dates else start_key
    actual_end = trading_dates[-1] if trading_dates else end_key
    out_of_sample = _out_of_sample_window(param, actual_start, actual_end)
    benchmark = _benchmark_snapshot(
        symbol,
        trading_dates,
        data_by_date,
        data_source,
        param,
        benchmark_market_data=benchmark_market_data,
        benchmark_data_source=benchmark_data_source,
        benchmark_error=benchmark_error,
    )
    if benchmark.get("available"):
        benchmark["excessReturnPct"] = round(total_return_pct - _as_float(benchmark.get("returnPct")), 2)
    research_contract = _research_contract(
        param,
        benchmark=benchmark,
        out_of_sample=out_of_sample,
        sample_start=actual_start,
        sample_end=actual_end,
    )
    signalops_meta = _signalops_report_metadata(param)
    if signalops_meta:
        research_contract.update(signalops_meta)
    bottom_research_meta = _bottom_research_report_metadata(param)
    if bottom_research_meta:
        research_contract.update(bottom_research_meta)
    walk_forward = _walk_forward_contract(param)
    parameter_scan = _parameter_scan_contract(param)

    sample_window = {
        "requestedStartDate": start_key,
        "requestedEndDate": end_key,
        "actualStartDate": actual_start,
        "actualEndDate": actual_end,
        "calendarDays": (_parse_date(end_key) - _parse_date(start_key)).days + 1,
        "tradingDays": len(equity_curve),
        "dataPoints": len(market_data),
        "signals": len(signal_log),
        "trades": total_trades,
        "isSmallSample": len(equity_curve) < MIN_MEDIUM_SAMPLE_DAYS or total_trades < MIN_MEDIUM_SAMPLE_TRADES,
    }
    trading_cost = {
        "model": "bps_per_trade",
        "commissionBps": commission_bps,
        "stampTaxBps": stamp_tax_bps,
        "minCommission": min_commission,
        "totalCost": round(total_transaction_cost, 2),
        "totalCommission": round(total_commission, 2),
        "totalStampTax": round(total_stamp_tax, 2),
        "includedInCapital": True,
    }
    slippage_report = {
        "model": "fixed_bps",
        "slippageBps": slippage_bps,
        "totalSlippage": round(total_slippage, 2),
        "includedInExecutionPrice": True,
    }
    execution_constraints = {
        "tPlusOne": bool(t_plus_one),
        "tPlusOneBlocked": t_plus_one_blocked,
        "priceLimitPct": price_limit_pct,
        "priceLimitBlocked": price_limit_blocked,
        "tradeQuantityPct": trade_quantity_pct,
        "signalMinStrength": signal_min_strength,
        "manualReviewAccepted": bool(manual_review_accepted),
        "executionReachabilityMode": str(param.get("execution_reachability_mode") or "backtest_constraints_only"),
    }
    statistical, evidence_strength, limitations = _sample_quality(
        data_points=len(market_data),
        trading_days=len(equity_curve),
        total_trades=total_trades,
        total_signals=len(signal_log),
        data_source=data_source,
        signal_source=signal_source,
        out_of_sample=out_of_sample,
        walk_forward=walk_forward,
        parameter_scan=parameter_scan,
    )
    research_grade = _research_grade_score(
        trading_days=len(equity_curve),
        total_trades=total_trades,
        total_signals=len(signal_log),
        benchmark=benchmark,
        out_of_sample=out_of_sample,
        walk_forward=walk_forward,
        parameter_scan=parameter_scan,
        max_drawdown_pct=max_dd_pct,
        execution_constraints=execution_constraints,
        statistical_confidence=statistical,
    )
    evidence_strength["researchGradeScore"] = research_grade["score"]
    evidence_strength["researchGradeBand"] = research_grade["band"]
    evidence_strength["calculatedResearchGradeBand"] = research_grade.get("calculatedBand") or research_grade["band"]
    evidence_strength["researchUsage"] = research_grade["researchUsage"]
    evidence_strength["canSupportResearchVerdict"] = bool(research_grade["canSupportResearchVerdict"])
    evidence_strength["weakSample"] = True
    if not any("Backtest evidence is review-gated" in item for item in limitations):
        limitations.append("Backtest evidence is review-gated supporting_only; it cannot become a primary research conclusion by itself.")
    if research_grade["score"] < 80 and not any("Research grade score below" in item for item in limitations):
        limitations.append("Research grade score below 80; keep this backtest as supporting_only evidence.")
    validation_protocol = {
        "version": "backtest_research_validation_protocol_v1",
        "parameterScan": parameter_scan,
        "walkForward": walk_forward,
        "outOfSample": out_of_sample,
        "benchmark": {
            "symbol": benchmark.get("symbol") or "",
            "available": bool(benchmark.get("available")),
            "type": benchmark.get("type") or "",
        },
        "packageHashes": package_hashes,
        "researchGradeComponents": [str(item.get("key")) for item in research_grade.get("components", [])],
        "requiredForResearchGrade": [
            "sufficient_sample_count",
            "out_of_sample_window",
            "walk_forward_validation",
            "parameter_scan",
            "benchmark_available",
            "execution_constraints",
            "statistical_confidence",
        ],
    }
    source_signal_ids = [
        str(item.metadata_json.get("signal_id"))
        for item in signal_log
        if isinstance(item.metadata_json, dict) and item.metadata_json.get("signal_id")
    ]
    provenance = {
        "engineVersion": BACKTEST_ENGINE_VERSION,
        "generatedAt": _now_iso(),
        "parameterHash": package_hashes["parameterHash"],
        "marketDataHash": package_hashes["marketDataHash"],
        "signalPackageHash": package_hashes["signalPackageHash"],
        "benchmarkDataHash": package_hashes["benchmarkDataHash"],
        "dataPackageHash": package_hashes["dataPackageHash"],
        "experimentPackageHash": research_contract["experiment_package_hash"],
        "researchContract": research_contract,
        "dataSource": data_source,
        "dataError": data_error,
        "signalSource": signal_source,
        "signalSourceCount": len(signals),
        "sourceSignalIds": source_signal_ids,
        "symbol": symbol,
        "stockName": stock_name,
    }
    if signalops_meta:
        provenance.update(signalops_meta)
    if bottom_research_meta:
        provenance.update(bottom_research_meta)

    return BacktestReport(
        data_source=data_source,
        data_error=data_error,
        data_points=len(market_data),
        signal_source=signal_source,
        signal_source_count=len(signals),
        total_trades=total_trades,
        winning_trades=winning,
        losing_trades=losing,
        hit_rate=hit_rate,
        false_positive_rate=false_positive_rate,
        total_pnl=round(total_pnl, 2),
        max_drawdown=max_dd,
        max_drawdown_pct=max_dd_pct,
        sharpe_ratio=sharpe,
        total_signals=len(signal_log),
        buy_signals=buy_sigs,
        sell_signals=sell_sigs,
        manual_review_pass_rate=manual_pass_rate,
        t_plus_one_blocked=t_plus_one_blocked,
        price_limit_blocked=price_limit_blocked,
        slippage_total=round(total_slippage, 2),
        final_capital=round(final_capital, 2),
        total_return_pct=round(total_return_pct, 2),
        benchmark=benchmark,
        sampleWindow=sample_window,
        tradingCost=trading_cost,
        slippage=slippage_report,
        executionConstraints=execution_constraints,
        outOfSampleWindow=out_of_sample,
        statisticalConfidence=statistical,
        evidenceStrength=evidence_strength,
        researchGradeScore=research_grade,
        limitations=limitations,
        provenance=provenance,
        researchContract=research_contract,
        validationProtocol=validation_protocol,
        equity_curve=equity_curve,
        trade_log=trade_log,
        signal_log=signal_log,
    )


def run_comparison(
    before_report: Optional[BacktestReport],
    after_report: Optional[BacktestReport],
) -> BacktestComparison:
    if not before_report or not after_report:
        return BacktestComparison(before=before_report, after=after_report)

    hit_rate_delta = round(after_report.hit_rate - before_report.hit_rate, 4)
    drawdown_delta = round(after_report.max_drawdown_pct - before_report.max_drawdown_pct, 4)
    false_positive_delta = round(after_report.false_positive_rate - before_report.false_positive_rate, 4)
    pnl_delta = round(after_report.total_pnl - before_report.total_pnl, 2)
    return_delta = round(after_report.total_return_pct - before_report.total_return_pct, 2)

    if hit_rate_delta > 0 and drawdown_delta < 0:
        verdict = "IMPROVED"
    elif hit_rate_delta >= -0.01 and drawdown_delta <= 0.01:
        verdict = "NO_REGRESSION"
    else:
        verdict = "REGRESSED"

    return BacktestComparison(
        before=before_report,
        after=after_report,
        hit_rate_delta=hit_rate_delta,
        drawdown_delta=drawdown_delta,
        false_positive_delta=false_positive_delta,
        pnl_delta=pnl_delta,
        return_delta=return_delta,
        verdict=verdict,
        researchContract=_comparison_research_contract(before_report, after_report),
    )


def _comparison_research_contract(
    before_report: BacktestReport,
    after_report: BacktestReport,
) -> Dict[str, Any]:
    before_contract = before_report.researchContract or before_report.provenance.get("researchContract") or {}
    after_contract = after_report.researchContract or after_report.provenance.get("researchContract") or {}
    return {
        "baseline_experiment_package_hash": before_contract.get("experiment_package_hash")
        or before_report.provenance.get("experimentPackageHash")
        or before_report.provenance.get("parameterHash"),
        "candidate_experiment_package_hash": after_contract.get("experiment_package_hash")
        or after_report.provenance.get("experimentPackageHash")
        or after_report.provenance.get("parameterHash"),
        "benchmark_symbol": after_contract.get("benchmark_symbol") or (after_report.benchmark or {}).get("symbol"),
        "walk_forward": after_contract.get("walk_forward") or {},
        "out_of_sample_start": after_contract.get("out_of_sample_start") or "",
        "out_of_sample_end": after_contract.get("out_of_sample_end") or "",
        "out_of_sample_configured": bool(after_contract.get("out_of_sample_configured")),
        "candidate_research_usage": (after_report.evidenceStrength or {}).get("researchUsage"),
        "baseline_research_usage": (before_report.evidenceStrength or {}).get("researchUsage"),
    }


def generate_mock_market_data(
    symbol: str,
    start_date: str,
    end_date: str,
    base_price: float = 20.0,
) -> List[Dict[str, Any]]:
    start_dt = _parse_date(start_date)
    end_dt = _parse_date(end_date)
    current_dt = start_dt
    price = base_price
    rng = random.Random(42)

    data: List[Dict[str, Any]] = []
    while current_dt <= end_dt:
        ds = current_dt.strftime("%Y-%m-%d")
        prev_close = price
        change = rng.gauss(0, price * 0.025)
        change = max(-price * DEFAULT_PRICE_LIMIT, min(price * DEFAULT_PRICE_LIMIT, change))
        close = round(price + change, 2)
        open_price = round(prev_close + rng.uniform(-1, 1), 2)
        open_price = max(1, open_price)

        data.append({
            "date": ds,
            "symbol": symbol,
            "open": open_price,
            "high": round(max(open_price, close) + rng.uniform(0, 1), 2),
            "low": round(min(open_price, close) - rng.uniform(0, 1), 2),
            "close": close,
            "volume": rng.randint(100000, 5000000),
            "prev_close": prev_close,
        })

        price = close
        current_dt += timedelta(days=1)

    return data


def generate_mock_signals(
    symbol: str,
    start_date: str,
    end_date: str,
) -> List[Dict[str, Any]]:
    start_dt = _parse_date(start_date)
    end_dt = _parse_date(end_date)
    rng = random.Random(7)
    current_dt = start_dt

    signals: List[Dict[str, Any]] = []
    while current_dt <= end_dt:
        if rng.random() < 0.3:
            signals.append({
                "timestamp": current_dt.strftime("%Y-%m-%d"),
                "symbol": symbol,
                "signal_type": rng.choice(["BUY", "SELL"]),
                "direction": rng.choice(["BUY", "SELL"]),
                "strength": round(rng.uniform(0.1, 1.0), 2),
                "source_node": rng.choice(["quant_engine", "scenario_engine", "risk_firewall"]),
                "metadata_json": {"confidence": round(rng.uniform(0, 1), 2)},
            })
        current_dt += timedelta(days=1)

    return signals
