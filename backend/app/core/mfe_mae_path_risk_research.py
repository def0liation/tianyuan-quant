from __future__ import annotations

import math
from statistics import mean
from typing import Any, Dict, List, Optional, Sequence


MFE_MAE_PATH_RISK_RESEARCH_VERSION = "mfe_mae_path_risk_research_v1"
MFE_MAE_PATH_RESEARCH_VERSION = "mfe_mae_path_research_v2"
MFE_MAE_CONDITIONAL_QUANTILE_EVALUATION_VERSION = "mfe_mae_conditional_quantile_evaluation_v1"
RANK_IC_MODE = "single_symbol_time_series_spearman"
SIMULATION_ONLY = True
IS_REAL_TRADE = False
EPSILON = 1e-6
MIN_WALK_FORWARD_SAMPLES = 30

DEFAULT_MFE_MAE_PATH_RESEARCH_CONFIG: Dict[str, Any] = {
    "lookback_range": "2y",
    "horizon_days": 20,
    "horizon_days_list": [5, 20, 60],
    "min_history_rows": 90,
    "quantile_levels": [0.5, 0.8, 0.9],
    "favorable_mfe_threshold_pct": 0.06,
    "favorable_probability_threshold": 0.55,
    "mae_warning_pct": 0.06,
    "mae_avoid_pct": 0.12,
    "risk_reward_floor": 1.20,
    "max_research_position_pct": 0.30,
}

PATH_RISK_BUCKETS = [0.02, 0.05, 0.08, 0.10, 0.15, 0.20]
CONDITIONAL_QUANTILE_TARGETS = ("mfe", "maeAbs", "riskReward")
CONDITIONAL_QUANTILE_LEVELS = (0.5, 0.8, 0.9)


def build_mfe_mae_label_records(rows: Any, horizon_days: int = 20) -> List[Dict[str, Any]]:
    """Build historical MFE/MAE labels from normalized OHLCV rows."""

    horizon = _positive_int(horizon_days, 20)
    normalized_rows = _normalize_ohlcv_rows(rows)
    if horizon <= 0 or len(normalized_rows) <= horizon:
        return []

    records: List[Dict[str, Any]] = []
    for index in range(len(normalized_rows) - horizon):
        current = normalized_rows[index]
        future_rows = normalized_rows[index + 1 : index + 1 + horizon]
        if len(future_rows) != horizon:
            continue

        entry_close = current["close"]
        if entry_close <= 0:
            continue

        future_high = max(row["high"] for row in future_rows)
        future_low = min(row["low"] for row in future_rows)
        future_close = float(future_rows[-1]["close"])
        mfe_label = (future_high - entry_close) / entry_close
        mae_label = (future_low - entry_close) / entry_close
        actual_forward_return = (future_close - entry_close) / entry_close
        actual_up_label = 1 if actual_forward_return > 0 else 0
        actual_down_label = 1 if actual_forward_return < 0 else 0
        mae_abs_label = abs(min(0.0, mae_label))
        risk_reward_label = mfe_label / (mae_abs_label + EPSILON)
        entry_range_proxy = max(0.0, (current["high"] - current["low"]) / entry_close)
        entry_body_proxy = abs(current["close"] - current["open"]) / entry_close

        records.append(
            {
                "tradeDate": current["date"],
                "entryPrice": entry_close,
                "entryOpen": current["open"],
                "entryHigh": current["high"],
                "entryLow": current["low"],
                "horizonDays": horizon,
                "labelWindowStart": future_rows[0]["date"],
                "labelWindowEnd": future_rows[-1]["date"],
                "mfeLabel": mfe_label,
                "maeLabel": mae_label,
                "maeAbsLabel": mae_abs_label,
                "riskRewardLabel": risk_reward_label,
                "actualForwardReturn": actual_forward_return,
                "actualUpLabel": actual_up_label,
                "actualDownLabel": actual_down_label,
                "actualDirection": "UP" if actual_up_label else ("DOWN" if actual_down_label else "FLAT"),
                "entryRiskProxy": entry_range_proxy,
                "entryBodyProxy": entry_body_proxy,
                "labelStatus": "LABELED_HISTORICAL",
                "simulation_only": SIMULATION_ONLY,
                "is_real_trade": IS_REAL_TRADE,
            }
        )
    return records


def evaluate_mfe_mae_path_risk_walk_forward(records: Any) -> Dict[str, Any]:
    """Evaluate MFE/MAE labels with a deterministic train-before-test proxy."""

    input_records = records if isinstance(records, list) else []
    labeled_records, excluded_trade_dates = _normalize_labeled_records(input_records)
    base = {
        "version": MFE_MAE_PATH_RISK_RESEARCH_VERSION,
        "rankIcMode": RANK_IC_MODE,
        "leakagePolicy": (
            "records_require_LABELED_HISTORICAL; "
            "proxy_scores_use_entry_day_fields_only; "
            "folds_train_end_before_test_start; "
            "unlabeled_nowcast_excluded"
        ),
        "simulation_only": SIMULATION_ONLY,
        "is_real_trade": IS_REAL_TRADE,
    }
    conditional_quantile_evaluation = evaluate_mfe_mae_conditional_quantiles(input_records)

    if len(labeled_records) < MIN_WALK_FORWARD_SAMPLES:
        return {
            **base,
            "status": "SUPPORTING_ONLY",
            "rankIc": None,
            "quantileCoverage": _empty_quantile_coverage(),
            "conditionalQuantileEvaluation": conditional_quantile_evaluation,
            "folds": [],
            "sampleQuality": _sample_quality(
                input_count=len(input_records),
                labeled_count=len(labeled_records),
                excluded_trade_dates=excluded_trade_dates,
                fold_count=0,
                evaluated_test_count=0,
                status="SUPPORTING_ONLY",
                reasons=["insufficient_labeled_samples"],
            ),
        }

    folds: List[Dict[str, Any]] = []
    all_scores: List[float] = []
    all_targets: List[float] = []
    q80_hits = 0
    q90_hits = 0
    evaluated_count = 0
    q80_thresholds: List[float] = []
    q90_thresholds: List[float] = []

    for fold in _walk_forward_windows(labeled_records):
        train = fold["train"]
        test = fold["test"]
        train_mae_abs = [record["maeAbsLabel"] for record in train]
        q80 = _quantile(train_mae_abs, 0.80)
        q90 = _quantile(train_mae_abs, 0.90)
        q80_thresholds.append(q80)
        q90_thresholds.append(q90)

        scores = [_entry_proxy_score(record, q80) for record in test]
        targets = [record["maeAbsLabel"] for record in test]
        fold_q80_hits = sum(1 for value in targets if value <= q80)
        fold_q90_hits = sum(1 for value in targets if value <= q90)
        fold_rank_ic = _spearman(scores, targets)

        all_scores.extend(scores)
        all_targets.extend(targets)
        q80_hits += fold_q80_hits
        q90_hits += fold_q90_hits
        evaluated_count += len(test)

        folds.append(
            {
                "foldIndex": len(folds) + 1,
                "trainStart": train[0]["tradeDate"],
                "trainEnd": train[-1]["tradeDate"],
                "testStart": test[0]["tradeDate"],
                "testEnd": test[-1]["tradeDate"],
                "trainCount": len(train),
                "testCount": len(test),
                "q80MaeAbsThreshold": q80,
                "q90MaeAbsThreshold": q90,
                "q80Coverage": _safe_divide(fold_q80_hits, len(test)),
                "q90Coverage": _safe_divide(fold_q90_hits, len(test)),
                "rankIc": fold_rank_ic,
                "scoreMode": "entry_day_range_proxy_scaled_by_train_q80_mae_abs",
            }
        )

    if not folds or evaluated_count <= 0:
        return {
            **base,
            "status": "SUPPORTING_ONLY",
            "rankIc": None,
            "quantileCoverage": _empty_quantile_coverage(),
            "conditionalQuantileEvaluation": conditional_quantile_evaluation,
            "folds": [],
            "sampleQuality": _sample_quality(
                input_count=len(input_records),
                labeled_count=len(labeled_records),
                excluded_trade_dates=excluded_trade_dates,
                fold_count=0,
                evaluated_test_count=0,
                status="SUPPORTING_ONLY",
                reasons=["no_valid_walk_forward_fold"],
            ),
        }

    q80_coverage = _safe_divide(q80_hits, evaluated_count)
    q90_coverage = _safe_divide(q90_hits, evaluated_count)
    return {
        **base,
        "status": "READY",
        "rankIc": _spearman(all_scores, all_targets),
        "quantileCoverage": {
            "q80": {
                "coverage": q80_coverage,
                "thresholdMean": _rounded_mean(q80_thresholds),
                "testCount": evaluated_count,
            },
            "q90": {
                "coverage": q90_coverage,
                "thresholdMean": _rounded_mean(q90_thresholds),
                "testCount": evaluated_count,
            },
            "q80Coverage": q80_coverage,
            "q90Coverage": q90_coverage,
            "evaluatedTestCount": evaluated_count,
        },
        "conditionalQuantileEvaluation": conditional_quantile_evaluation,
        "folds": folds,
        "sampleQuality": _sample_quality(
            input_count=len(input_records),
            labeled_count=len(labeled_records),
            excluded_trade_dates=excluded_trade_dates,
            fold_count=len(folds),
            evaluated_test_count=evaluated_count,
            status="READY",
            reasons=[],
        ),
    }


def evaluate_mfe_mae_conditional_quantiles(records: Any) -> Dict[str, Any]:
    """Evaluate train-before-test empirical conditional quantiles for MFE/MAE labels."""

    input_records = records if isinstance(records, list) else []
    labeled_records, excluded_trade_dates = _normalize_labeled_records(input_records)
    base = {
        "version": MFE_MAE_CONDITIONAL_QUANTILE_EVALUATION_VERSION,
        "status": "SUPPORTING_ONLY",
        "method": "walk_forward_empirical_conditioned_quantile_v1",
        "conditioning": {
            "modelType": "empirical_train_window_no_persisted_ml",
            "features": ["entryRiskProxy", "entryBodyProxy"],
            "grouping": "entryRiskProxy_tercile_with_full_train_fallback",
            "quantileLevels": [0.5, 0.8, 0.9],
            "runtimePredictionPolicy": "research_only_not_deterministic_price_prediction",
        },
        "rankIcMode": RANK_IC_MODE,
        "leakagePolicy": (
            "records_require_LABELED_HISTORICAL; "
            "folds_train_end_before_test_start; "
            "condition_buckets_fit_on_train_only; "
            "UNLABELED_NOWCAST excluded"
        ),
        "actionBoundary": "RESEARCH_ONLY_NO_PERMISSION_CHANGE",
        "labelStatus": "LABELED_HISTORICAL_ONLY_NOWCAST_EXCLUDED",
        "simulation_only": SIMULATION_ONLY,
        "is_real_trade": IS_REAL_TRADE,
    }

    if len(labeled_records) < MIN_WALK_FORWARD_SAMPLES:
        return {
            **base,
            "folds": [],
            "targetCoverage": _empty_conditional_quantile_coverage(),
            "rankIc": _empty_conditional_rank_ic(),
            "sampleQuality": _sample_quality(
                input_count=len(input_records),
                labeled_count=len(labeled_records),
                excluded_trade_dates=excluded_trade_dates,
                fold_count=0,
                evaluated_test_count=0,
                status="SUPPORTING_ONLY",
                reasons=["insufficient_labeled_samples"],
            ),
        }

    folds: List[Dict[str, Any]] = []
    evaluated_count = 0
    aggregate_predictions: Dict[str, Dict[float, List[float]]] = _empty_target_quantile_lists()
    aggregate_actuals: Dict[str, List[float]] = {"mfe": [], "maeAbs": [], "riskReward": []}
    aggregate_hits: Dict[str, Dict[float, int]] = _empty_target_quantile_counts()

    for fold in _walk_forward_windows(labeled_records):
        train = fold["train"]
        test = fold["test"]
        thresholds = _condition_thresholds(train)
        fold_predictions: Dict[str, Dict[float, List[float]]] = _empty_target_quantile_lists()
        fold_actuals: Dict[str, List[float]] = {"mfe": [], "maeAbs": [], "riskReward": []}
        fold_hits: Dict[str, Dict[float, int]] = _empty_target_quantile_counts()
        fallback_count = 0

        for record in test:
            conditioned_train, used_fallback = _conditioned_train_records(train, record, thresholds)
            fallback_count += 1 if used_fallback else 0
            prediction = _target_quantiles(conditioned_train)
            actual = _target_actuals(record)
            for target, actual_value in actual.items():
                fold_actuals[target].append(actual_value)
                aggregate_actuals[target].append(actual_value)
                for level in CONDITIONAL_QUANTILE_LEVELS:
                    predicted_value = prediction[target][level]
                    fold_predictions[target][level].append(predicted_value)
                    aggregate_predictions[target][level].append(predicted_value)
                    if actual_value <= predicted_value:
                        fold_hits[target][level] += 1
                        aggregate_hits[target][level] += 1
            evaluated_count += 1

        fold_count = len(test)
        folds.append(
            {
                "foldIndex": len(folds) + 1,
                "trainStart": train[0]["tradeDate"],
                "trainEnd": train[-1]["tradeDate"],
                "testStart": test[0]["tradeDate"],
                "testEnd": test[-1]["tradeDate"],
                "trainCount": len(train),
                "testCount": fold_count,
                "conditionFallbackCount": fallback_count,
                "quantileCoverage": _conditional_coverage_payload(fold_hits, fold_predictions, fold_count),
                "rankIc": _conditional_rank_ic(fold_predictions, fold_actuals),
            }
        )

    if not folds or evaluated_count <= 0:
        return {
            **base,
            "folds": [],
            "targetCoverage": _empty_conditional_quantile_coverage(),
            "rankIc": _empty_conditional_rank_ic(),
            "sampleQuality": _sample_quality(
                input_count=len(input_records),
                labeled_count=len(labeled_records),
                excluded_trade_dates=excluded_trade_dates,
                fold_count=0,
                evaluated_test_count=0,
                status="SUPPORTING_ONLY",
                reasons=["no_valid_walk_forward_fold"],
            ),
        }

    return {
        **base,
        "status": "READY",
        "folds": folds,
        "targetCoverage": _conditional_coverage_payload(aggregate_hits, aggregate_predictions, evaluated_count),
        "rankIc": _conditional_rank_ic(aggregate_predictions, aggregate_actuals),
        "sampleQuality": _sample_quality(
            input_count=len(input_records),
            labeled_count=len(labeled_records),
            excluded_trade_dates=excluded_trade_dates,
            fold_count=len(folds),
            evaluated_test_count=evaluated_count,
            status="READY",
            reasons=[],
        ),
    }


def infer_mfe_mae_market_profile(symbol: str, auxiliary_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Infer the market microstructure profile used to adapt MFE/MAE thresholds."""

    code = str(symbol or "").strip().upper()
    auxiliary = auxiliary_data if isinstance(auxiliary_data, dict) else {}
    stock_name = str(auxiliary.get("stockName") or auxiliary.get("stock_name") or "").upper()
    is_st = "ST" in stock_name or code.startswith("ST")
    asset_type = str(auxiliary.get("assetType") or auxiliary.get("asset_type") or "").upper()

    if code.endswith(".HK") or code.endswith(".HKG") or (code.isdigit() and len(code) <= 5):
        return {
            "market": "HK",
            "exchange": "HKEX",
            "currency": "HKD",
            "dailyPriceLimitPct": None,
            "tPlusOne": False,
            "defaultLotSize": None,
            "downsideTailMultiplier": 1.22,
            "liquidityRiskMultiplier": 1.18,
            "formulaAdjustments": [
                "no_daily_price_limit_use_tail_multiplier",
                "hk_liquidity_gap_weight_up",
                "board_lot_unknown_review_only",
            ],
            "sampleSegmentation": "market_specific_recalibration_required",
            "transferabilityStatus": "HK_RECALIBRATION_REQUIRED",
            "missingExternalData": ["level2_order_flow", "real_order_book_depth", "full_chip_distribution", "valuation_gap"],
        }

    if code.endswith(".T") or code.endswith(".JP") or code in {"^N225", "N225", "EWJ"}:
        return {
            "market": "JP",
            "exchange": "JPX",
            "currency": "JPY",
            "dailyPriceLimitPct": None,
            "tPlusOne": False,
            "defaultLotSize": 100,
            "downsideTailMultiplier": 1.08,
            "liquidityRiskMultiplier": 1.04,
            "formulaAdjustments": [
                "jp_market_recalibration_required",
                "jpy_proxy_tracking_error_review",
                "lot_size_review_required",
            ],
            "sampleSegmentation": "market_specific_recalibration_required",
            "transferabilityStatus": "JP_RECALIBRATION_REQUIRED",
            "missingExternalData": ["level2_order_flow", "real_order_book_depth", "full_chip_distribution", "valuation_gap"],
        }

    if (
        code.startswith("^")
        or code.endswith(".US")
        or code.endswith(".NYSE")
        or code.endswith(".NASDAQ")
        or code.endswith(".AMEX")
        or asset_type in {"ETF", "US_ETF", "EQUITY_US"}
        or code in {"SPY", "QQQ", "DIA", "IWM", "VOO", "IVV", "EFA", "EWH"}
    ):
        is_etf = asset_type.endswith("ETF") or code in {"SPY", "QQQ", "DIA", "IWM", "VOO", "IVV", "EFA", "EWH"}
        return {
            "market": "US_ETF" if is_etf else "US",
            "exchange": "US_MARKET",
            "currency": "USD",
            "dailyPriceLimitPct": None,
            "tPlusOne": False,
            "defaultLotSize": 1,
            "downsideTailMultiplier": 1.04 if is_etf else 1.10,
            "liquidityRiskMultiplier": 0.96 if is_etf else 1.02,
            "formulaAdjustments": [
                "us_no_daily_price_limit_tail_review",
                "usd_proxy_tracking_error_review" if is_etf else "single_name_gap_risk_review",
                "fractional_lot_not_assumed",
            ],
            "sampleSegmentation": "market_specific_recalibration_required",
            "transferabilityStatus": "US_RECALIBRATION_REQUIRED",
            "missingExternalData": ["level2_order_flow", "real_order_book_depth", "full_chip_distribution", "valuation_gap"],
        }

    if code.endswith(".BJ"):
        limit_pct = 0.30
        exchange = "BSE"
    elif code.endswith(".SH") and code.startswith("688"):
        limit_pct = 0.20
        exchange = "SSE_STAR"
    elif code.endswith(".SZ") and code.startswith("300"):
        limit_pct = 0.20
        exchange = "SZSE_CHINEXT"
    elif code.endswith(".SH") or code.endswith(".SZ") or (code.isdigit() and len(code) == 6):
        limit_pct = 0.05 if is_st else 0.10
        exchange = "CN_A"
    else:
        return {
            "market": "UNKNOWN",
            "exchange": "UNKNOWN",
            "currency": "",
            "dailyPriceLimitPct": None,
            "tPlusOne": False,
            "defaultLotSize": None,
            "downsideTailMultiplier": 1.12,
            "liquidityRiskMultiplier": 1.10,
            "formulaAdjustments": [
                "unknown_market_review_only",
                "market_specific_recalibration_required",
            ],
            "sampleSegmentation": "market_specific_recalibration_required",
            "transferabilityStatus": "UNKNOWN_REVIEW_ONLY",
            "missingExternalData": ["level2_order_flow", "real_order_book_depth", "full_chip_distribution", "valuation_gap"],
        }

    return {
        "market": "CN_A",
        "exchange": exchange,
        "currency": "CNY",
        "dailyPriceLimitPct": limit_pct,
        "tPlusOne": True,
        "defaultLotSize": 100,
        "downsideTailMultiplier": 1.0 if limit_pct <= 0.10 else 1.06,
        "liquidityRiskMultiplier": 1.0,
        "formulaAdjustments": [
            "daily_limit_board_aware_mae",
            "t_plus_one_exit_constraint",
            "a_share_lot_size_100",
        ],
        "sampleSegmentation": "market_specific_recalibration_required",
        "transferabilityStatus": "CN_A_RECALIBRATION_REQUIRED",
        "missingExternalData": ["level2_order_flow", "real_order_book_depth", "full_chip_distribution", "valuation_gap"],
    }


def normalize_mfe_mae_path_research_config(
    config: Optional[Dict[str, Any]] = None,
    *,
    symbol: str = "",
    auxiliary_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    profile = infer_mfe_mae_market_profile(symbol, auxiliary_data)
    payload = dict(DEFAULT_MFE_MAE_PATH_RESEARCH_CONFIG)
    if profile["market"] == "CN_A":
        payload.update(
            {
                "favorable_mfe_threshold_pct": 0.055,
                "mae_warning_pct": 0.05,
                "mae_avoid_pct": max(0.09, min(0.18, float(profile.get("dailyPriceLimitPct") or 0.10) * 1.05)),
            }
        )
    elif profile["market"] == "HK":
        payload.update(
            {
                "favorable_mfe_threshold_pct": 0.075,
                "mae_warning_pct": 0.075,
                "mae_avoid_pct": 0.14,
            }
        )
    elif profile["market"] in {"US", "US_ETF"}:
        payload.update(
            {
                "favorable_mfe_threshold_pct": 0.045 if profile["market"] == "US_ETF" else 0.065,
                "mae_warning_pct": 0.045 if profile["market"] == "US_ETF" else 0.065,
                "mae_avoid_pct": 0.10 if profile["market"] == "US_ETF" else 0.13,
            }
        )
    elif profile["market"] == "JP":
        payload.update(
            {
                "favorable_mfe_threshold_pct": 0.055,
                "mae_warning_pct": 0.055,
                "mae_avoid_pct": 0.11,
            }
        )

    if isinstance(config, dict):
        payload.update({key: value for key, value in config.items() if value is not None})

    horizon = _bounded_int(payload.get("horizon_days"), 5, 90, 20)
    payload["horizon_days"] = horizon
    payload["horizon_days_list"] = _normalize_horizon_days(payload.get("horizon_days_list"), horizon)
    payload["min_history_rows"] = _bounded_int(payload.get("min_history_rows"), 40, 400, 90)
    payload["quantile_levels"] = _normalize_quantile_levels(payload.get("quantile_levels"))
    payload["favorable_mfe_threshold_pct"] = _bounded_float(payload.get("favorable_mfe_threshold_pct"), 0.01, 0.50, 0.06)
    payload["favorable_probability_threshold"] = _bounded_float(payload.get("favorable_probability_threshold"), 0.10, 0.95, 0.55)
    payload["mae_warning_pct"] = _bounded_float(payload.get("mae_warning_pct"), 0.01, 0.50, 0.06)
    payload["mae_avoid_pct"] = _bounded_float(payload.get("mae_avoid_pct"), 0.02, 0.80, 0.12)
    payload["risk_reward_floor"] = _bounded_float(payload.get("risk_reward_floor"), 0.20, 10.0, 1.20)
    payload["max_research_position_pct"] = _bounded_float(payload.get("max_research_position_pct"), 0.0, 0.50, 0.30)
    payload["marketProfile"] = profile
    return payload


def build_mfe_mae_path_research_analysis(
    symbol: str,
    daily_payload: Optional[Dict[str, Any]] = None,
    *,
    rows: Optional[List[Dict[str, Any]]] = None,
    auxiliary_data: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the active MFE/MAE path research payload."""

    cfg = normalize_mfe_mae_path_research_config(config, symbol=symbol, auxiliary_data=auxiliary_data)
    provider = str((daily_payload or {}).get("provider") or "custom").lower()
    data_mode = str((daily_payload or {}).get("dataMode") or ("LIVE" if rows is not None else "UNAVAILABLE"))
    data_mode_upper = data_mode.upper()
    status = str((daily_payload or {}).get("status") or ("READY" if rows is not None else "FAILED"))
    status_upper = status.upper()
    normalized_rows = _normalize_research_rows(rows if rows is not None else (daily_payload or {}).get("rows"))
    profile = cfg["marketProfile"]
    max_horizon = max(cfg["horizon_days_list"] or [cfg["horizon_days"]])
    min_required = max(int(cfg["min_history_rows"]), max_horizon + MIN_WALK_FORWARD_SAMPLES + 5)
    warnings: List[str] = []
    missing_data: List[str] = []

    if status_upper != "READY" and rows is None:
        missing_data.append("daily_kline_unavailable")
    if daily_payload is not None and data_mode_upper != "LIVE":
        missing_data.append("daily_kline_non_live_data")
    if len(normalized_rows) < min_required:
        missing_data.append(f"daily_kline_less_than_{min_required}")

    if missing_data:
        return _mfe_mae_supporting_payload(
            symbol=symbol,
            cfg=cfg,
            rows=normalized_rows,
            provider=provider,
            data_mode=data_mode,
            missing_data=missing_data,
            warnings=warnings,
        )

    horizon_forecasts = [
        _build_mfe_mae_horizon_forecast(normalized_rows, cfg, horizon_days)
        for horizon_days in cfg["horizon_days_list"]
    ]
    primary = _primary_mfe_mae_forecast(horizon_forecasts, cfg["horizon_days"])
    current_prediction = dict(primary.get("currentPrediction") or {})
    probability_series = list(primary.get("probabilitySeries") or [])[-120:]
    horizon_probability_series = [
        {"horizonDays": item["horizonDays"], "series": item.get("probabilitySeries", [])[-120:]}
        for item in horizon_forecasts
    ]
    labeled_records = build_mfe_mae_label_records(normalized_rows, cfg["horizon_days"])
    evaluation = evaluate_mfe_mae_path_risk_walk_forward(
        [
            *labeled_records,
            {
                "tradeDate": normalized_rows[-1]["date"],
                "horizonDays": cfg["horizon_days"],
                "labelStatus": "UNLABELED_NOWCAST",
                "simulation_only": SIMULATION_ONLY,
                "is_real_trade": IS_REAL_TRADE,
            },
        ]
    )
    ready_forecasts = [item for item in horizon_forecasts if item.get("status") == "READY"]
    diagnostics_status = "READY" if primary.get("status") == "READY" and evaluation.get("status") == "READY" else "SUPPORTING_ONLY"
    evidence_grade = _mfe_mae_evidence_grade(evaluation, ready_forecasts)
    trend_synthesis = _mfe_mae_trend_synthesis(horizon_forecasts, primary, cfg)
    qiam_adjustment_preview = _mfe_mae_qiam_adjustment_preview(primary, trend_synthesis)
    formula_config = _mfe_mae_formula_config(cfg)

    conditional_quantile_evaluation = evaluation.get("conditionalQuantileEvaluation")
    sample_quality = (
        conditional_quantile_evaluation.get("sampleQuality")
        if isinstance(conditional_quantile_evaluation, dict)
        else evaluation.get("sampleQuality")
    )
    leakage_policy_value = (
        conditional_quantile_evaluation.get("leakagePolicy")
        if isinstance(conditional_quantile_evaluation, dict)
        else evaluation.get("leakagePolicy")
    ) or ""
    leakage_policy = str(leakage_policy_value)
    diagnostics = {
        "status": diagnostics_status,
        "modelVersion": MFE_MAE_PATH_RESEARCH_VERSION,
        "featureVersion": "mfe-mae-path-formula-v2",
        "sampleCount": len(labeled_records),
        "leakagePolicy": (
            "features_use_rows_ending_at_t; "
            "mfe_mae_labels_use_future_window_only_for_historical_training; "
            "unlabeled_nowcast_excluded"
        ),
        "rankIcMode": evaluation.get("rankIcMode"),
        "mfeMaePathRiskEvaluation": evaluation,
        "conditionalQuantileEvaluation": conditional_quantile_evaluation,
        "pathQuantiles": primary.get("pathQuantiles", {}),
        "marketProfile": profile,
        "formulaConfig": formula_config,
        "evidenceGrade": evidence_grade,
        "horizonCount": len(horizon_forecasts),
    }

    mfe_probability = _number(current_prediction.get("mfeFavorableProbability"))
    mae_probability = _number(current_prediction.get("maeBreachProbability"))
    risk_policy = str(current_prediction.get("riskPolicy") or "WATCH")
    return {
        "agent": "mfe_mae_path_research",
        "legacyAgent": "bottom_research",
        "researchType": "MFE_MAE_PATH_RESEARCH",
        "status": "PASS" if diagnostics_status == "READY" else "WARN",
        "modelVersion": MFE_MAE_PATH_RESEARCH_VERSION,
        "actionBoundary": "RESEARCH_ONLY_NO_PERMISSION_CHANGE",
        "labelStatus": current_prediction.get("labelStatus") or "UNLABELED_NOWCAST",
        "sampleQuality": sample_quality,
        "leakagePolicy": leakage_policy,
        "simulation_only": SIMULATION_ONLY,
        "is_real_trade": IS_REAL_TRADE,
        "mfeFavorableProbability": mfe_probability,
        "maeBreachProbability": mae_probability,
        "mfeProxy": current_prediction.get("mfeProxy"),
        "maeProxy": current_prediction.get("maeProxy"),
        "riskRewardProxy": current_prediction.get("riskRewardProxy"),
        "downsideRiskScore": current_prediction.get("downsideRiskScore"),
        "riskPolicy": risk_policy,
        "regimeState": current_prediction.get("regimeState"),
        "marketProfile": profile,
        "mfeMaeFormulaConfig": formula_config,
        "mfeMaePathModel": {
            "currentPrediction": current_prediction,
            "horizonForecasts": horizon_forecasts,
            "riskCurve": primary.get("riskCurve", []),
            "pathQuantiles": primary.get("pathQuantiles", {}),
            "labelFormula": formula_config["labelFormula"],
        },
        "bottomRepairProbability": mfe_probability,
        "breakdownRiskProbability": mae_probability,
        "riemannianFeatures": {
            "replacedBy": "MFE_MAE_PATH_RESEARCH",
            "featureBasis": ["mfeLabel", "maeLabel", "maeAbsLabel", "riskRewardLabel", "pathQuantiles"],
        },
        "modelDiagnostics": diagnostics,
        "positionEnvelope": {
            "policy": "REVIEW_ONLY_NOT_TRADE_INSTRUCTION",
            "maxResearchPositionPct": cfg["max_research_position_pct"],
            "simulation_only": SIMULATION_ONLY,
            "is_real_trade": IS_REAL_TRADE,
            "marketAdaptation": profile["market"],
        },
        "missingData": missing_data,
        "warnings": warnings,
        "provenance": {
            "sourceNode": "mfe_mae_path_research",
            "legacySourceNode": "bottom_research",
            "modelVersion": MFE_MAE_PATH_RESEARCH_VERSION,
            "provider": provider,
            "dataMode": data_mode,
            "lookbackRange": cfg["lookback_range"],
            "dailyCount": len(normalized_rows),
            "firstTradeDate": normalized_rows[0]["date"],
            "lastTradeDate": normalized_rows[-1]["date"],
            "market": profile["market"],
            "simulation_only": SIMULATION_ONLY,
            "is_real_trade": IS_REAL_TRADE,
        },
        "probabilitySeries": probability_series,
        "currentPrediction": current_prediction,
        "horizonProbabilitySeries": horizon_probability_series,
        "horizonForecasts": [_public_mfe_mae_horizon_forecast(item) for item in horizon_forecasts],
        "trendSynthesis": trend_synthesis,
        "qiamAdjustmentPreview": qiam_adjustment_preview,
        "config": cfg,
        "legacyCompatibility": {
            "bottomResearchAlias": True,
            "bottomRepairProbabilityMapsTo": "mfeFavorableProbability",
            "breakdownRiskProbabilityMapsTo": "maeBreachProbability",
        },
    }


def _build_mfe_mae_horizon_forecast(
    rows: List[Dict[str, Any]],
    cfg: Dict[str, Any],
    horizon_days: int,
) -> Dict[str, Any]:
    labels = build_mfe_mae_label_records(rows, horizon_days)
    profile = cfg["marketProfile"]
    min_samples = max(MIN_WALK_FORWARD_SAMPLES, min(80, len(rows) // 4))
    if len(labels) < min_samples:
        return {
            "horizonDays": horizon_days,
            "status": "SUPPORTING_ONLY",
            "sampleCount": len(labels),
            "reason": "insufficient_mfe_mae_labels",
            "probabilitySeries": [],
            "currentPrediction": _empty_current_prediction(rows, cfg, horizon_days),
            "pathQuantiles": {},
            "riskCurve": [],
        }

    features = _latest_path_features(rows)
    mfe_values = [float(item["mfeLabel"]) for item in labels]
    mae_abs_values = [float(item["maeAbsLabel"]) for item in labels]
    risk_reward_values = [float(item["riskRewardLabel"]) for item in labels]
    q50_mfe = _quantile(mfe_values, 0.50)
    q80_mfe = _quantile(mfe_values, 0.80)
    q90_mfe = _quantile(mfe_values, 0.90)
    q50_mae = _quantile(mae_abs_values, 0.50)
    q80_mae = _quantile(mae_abs_values, 0.80)
    q90_mae = _quantile(mae_abs_values, 0.90)
    q50_rr = _quantile(risk_reward_values, 0.50)

    downside_multiplier = float(profile.get("downsideTailMultiplier") or 1.0)
    liquidity_multiplier = float(profile.get("liquidityRiskMultiplier") or 1.0)
    momentum = features["return20d"]
    volatility = features["volatility20d"]
    range_ratio = features["rangeRatio20d"]
    liquidity_stress = features["liquidityStress"] * liquidity_multiplier
    limit_stress = _limit_board_stress(rows[-1], profile)
    mfe_proxy = max(0.0, q50_mfe + max(0.0, momentum) * 0.35 - liquidity_stress * 0.015)
    mae_proxy = max(
        0.0,
        (q80_mae * downside_multiplier)
        + max(0.0, -momentum) * 0.25
        + volatility * 0.20
        + range_ratio * 0.10
        + limit_stress * 0.05,
    )
    risk_reward_proxy = mfe_proxy / (mae_proxy + EPSILON)
    favorable_threshold = float(cfg["favorable_mfe_threshold_pct"])
    mae_warning = float(cfg["mae_warning_pct"])
    mae_avoid = float(cfg["mae_avoid_pct"])
    mfe_favorable_probability = _empirical_probability(mfe_values, favorable_threshold, mode="gte")
    mae_breach_probability = _empirical_probability(mae_abs_values, mae_warning, mode="gte")
    downside_risk_score = _downside_score(
        mae_breach_probability=mae_breach_probability,
        mae_proxy=mae_proxy,
        mae_avoid=mae_avoid,
        liquidity_stress=liquidity_stress,
        momentum=momentum,
        limit_stress=limit_stress,
        market=str(profile.get("market") or "UNKNOWN"),
    )
    risk_policy = _mfe_mae_risk_policy(downside_risk_score)
    current_prediction = {
        "tradeDate": rows[-1]["date"],
        "horizonDays": horizon_days,
        "labelStatus": "UNLABELED_NOWCAST",
        "mfeProxy": round(mfe_proxy, 6),
        "maeProxy": round(mae_proxy, 6),
        "riskRewardProxy": round(risk_reward_proxy, 6),
        "mfeFavorableProbability": round(mfe_favorable_probability, 6),
        "maeBreachProbability": round(mae_breach_probability, 6),
        "downsideRiskScore": round(downside_risk_score, 2),
        "riskPolicy": risk_policy,
        "regimeState": _mfe_mae_regime_state(risk_policy, risk_reward_proxy),
        "market": profile.get("market"),
        "simulation_only": SIMULATION_ONLY,
        "is_real_trade": IS_REAL_TRADE,
        "bottomRepairProbability": round(mfe_favorable_probability, 6),
        "breakdownRiskProbability": round(mae_breach_probability, 6),
    }
    path_quantiles = {
        "mfe": {"q50": round(q50_mfe, 6), "q80": round(q80_mfe, 6), "q90": round(q90_mfe, 6)},
        "maeAbs": {"q50": round(q50_mae, 6), "q80": round(q80_mae, 6), "q90": round(q90_mae, 6)},
        "riskReward": {"q50": round(q50_rr, 6)},
    }
    series = _mfe_mae_probability_series(
        labels,
        cfg,
        horizon_days,
        mfe_favorable_probability,
        mae_breach_probability,
        current_prediction,
    )
    return {
        "horizonDays": horizon_days,
        "status": "READY",
        "sampleCount": len(labels),
        "mfeFavorableProbability": round(mfe_favorable_probability, 6),
        "maeBreachProbability": round(mae_breach_probability, 6),
        "mfeProxy": round(mfe_proxy, 6),
        "maeProxy": round(mae_proxy, 6),
        "riskRewardProxy": round(risk_reward_proxy, 6),
        "downsideRiskScore": round(downside_risk_score, 2),
        "riskPolicy": risk_policy,
        "trendProbabilities": _trend_probabilities_from_path(mfe_favorable_probability, mae_breach_probability),
        "trendBias": _trend_bias_from_path(risk_policy, risk_reward_proxy, mfe_favorable_probability, mae_breach_probability),
        "confidence": _forecast_confidence(len(labels), evaluation_status="READY"),
        "evidenceGrade": _forecast_evidence_grade(len(labels), risk_reward_proxy),
        "regimeState": current_prediction["regimeState"],
        "currentPrediction": current_prediction,
        "pathQuantiles": path_quantiles,
        "riskCurve": _build_mfe_mae_risk_curve(PATH_RISK_BUCKETS, mae_abs_values, profile),
        "probabilitySeries": series,
        "marketProfile": profile,
    }


def _mfe_mae_supporting_payload(
    *,
    symbol: str,
    cfg: Dict[str, Any],
    rows: List[Dict[str, Any]],
    provider: str,
    data_mode: str,
    missing_data: List[str],
    warnings: List[str],
) -> Dict[str, Any]:
    profile = cfg["marketProfile"]
    last_trade_date = rows[-1]["date"] if rows else None
    first_trade_date = rows[0]["date"] if rows else None
    current_prediction = _empty_current_prediction(rows, cfg, int(cfg["horizon_days"]))
    empty_evaluation = evaluate_mfe_mae_path_risk_walk_forward([])
    conditional_quantile_evaluation = empty_evaluation.get("conditionalQuantileEvaluation")
    sample_quality = (
        conditional_quantile_evaluation.get("sampleQuality")
        if isinstance(conditional_quantile_evaluation, dict)
        else empty_evaluation.get("sampleQuality")
    )
    if isinstance(sample_quality, dict):
        sample_quality = {
            **sample_quality,
            "dailyCount": len(rows),
            "dataMode": data_mode,
            "missingData": list(missing_data),
        }
    leakage_policy_value = (
        conditional_quantile_evaluation.get("leakagePolicy")
        if isinstance(conditional_quantile_evaluation, dict)
        else empty_evaluation.get("leakagePolicy")
    ) or "no_labels_generated_when_daily_history_is_insufficient"
    leakage_policy = str(leakage_policy_value)
    diagnostics = {
        "status": "SUPPORTING_ONLY",
        "modelVersion": MFE_MAE_PATH_RESEARCH_VERSION,
        "featureVersion": "mfe-mae-path-formula-v2",
        "sampleCount": 0,
        "leakagePolicy": "no_labels_generated_when_daily_history_is_insufficient",
        "mfeMaePathRiskEvaluation": empty_evaluation,
        "conditionalQuantileEvaluation": empty_evaluation.get("conditionalQuantileEvaluation"),
        "marketProfile": profile,
        "formulaConfig": _mfe_mae_formula_config(cfg),
        "evidenceGrade": "LOW",
    }
    return {
        "agent": "mfe_mae_path_research",
        "legacyAgent": "bottom_research",
        "researchType": "MFE_MAE_PATH_RESEARCH",
        "status": "SKIPPED",
        "modelVersion": MFE_MAE_PATH_RESEARCH_VERSION,
        "actionBoundary": "RESEARCH_ONLY_NO_PERMISSION_CHANGE",
        "labelStatus": current_prediction.get("labelStatus") or "INSUFFICIENT_DATA",
        "sampleQuality": sample_quality,
        "leakagePolicy": leakage_policy,
        "simulation_only": SIMULATION_ONLY,
        "is_real_trade": IS_REAL_TRADE,
        "mfeFavorableProbability": None,
        "maeBreachProbability": None,
        "mfeProxy": None,
        "maeProxy": None,
        "riskRewardProxy": None,
        "downsideRiskScore": None,
        "riskPolicy": "WATCH",
        "regimeState": "SUPPORTING_ONLY",
        "marketProfile": profile,
        "mfeMaeFormulaConfig": _mfe_mae_formula_config(cfg),
        "mfeMaePathModel": {
            "currentPrediction": current_prediction,
            "horizonForecasts": [],
            "riskCurve": [],
            "pathQuantiles": {},
            "labelFormula": _mfe_mae_formula_config(cfg)["labelFormula"],
        },
        "bottomRepairProbability": None,
        "breakdownRiskProbability": None,
        "riemannianFeatures": {"replacedBy": "MFE_MAE_PATH_RESEARCH"},
        "modelDiagnostics": diagnostics,
        "positionEnvelope": {
            "policy": "REVIEW_ONLY_NOT_TRADE_INSTRUCTION",
            "maxResearchPositionPct": cfg["max_research_position_pct"],
            "simulation_only": SIMULATION_ONLY,
            "is_real_trade": IS_REAL_TRADE,
            "marketAdaptation": profile["market"],
        },
        "missingData": missing_data,
        "warnings": warnings,
        "provenance": {
            "sourceNode": "mfe_mae_path_research",
            "legacySourceNode": "bottom_research",
            "modelVersion": MFE_MAE_PATH_RESEARCH_VERSION,
            "provider": provider,
            "dataMode": data_mode,
            "lookbackRange": cfg["lookback_range"],
            "dailyCount": len(rows),
            "firstTradeDate": first_trade_date,
            "lastTradeDate": last_trade_date,
            "market": profile["market"],
            "simulation_only": SIMULATION_ONLY,
            "is_real_trade": IS_REAL_TRADE,
        },
        "probabilitySeries": [],
        "currentPrediction": current_prediction,
        "horizonProbabilitySeries": [],
        "horizonForecasts": [],
        "trendSynthesis": {
            "primaryHorizonDays": cfg["horizon_days"],
            "primaryTrendBias": "INSUFFICIENT_DATA",
            "horizonAlignment": "INSUFFICIENT_DATA",
            "confidence": 0.0,
            "mainConclusion": "MFE/MAE path research skipped because daily OHLCV history is insufficient.",
            "riskFlags": missing_data,
            "keyDrivers": [],
            "evidenceConflict": False,
        },
        "qiamAdjustmentPreview": _mfe_mae_qiam_adjustment_preview({}, {}),
        "config": cfg,
        "legacyCompatibility": {
            "bottomResearchAlias": True,
            "bottomRepairProbabilityMapsTo": "mfeFavorableProbability",
            "breakdownRiskProbabilityMapsTo": "maeBreachProbability",
        },
    }


def _normalize_research_rows(raw_rows: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw_rows, list):
        return []
    rows: List[Dict[str, Any]] = []
    previous_close: Optional[float] = None
    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        ds = _date_text(raw.get("date") or raw.get("tradeDate") or raw.get("trade_date"))
        open_price = _number(raw.get("open"))
        high = _number(raw.get("high"))
        low = _number(raw.get("low"))
        close = _number(raw.get("close"))
        if not ds or None in (open_price, high, low, close) or close <= 0:
            continue
        prev_close = _number(raw.get("prev_close") or raw.get("preClose") or raw.get("pre_close")) or previous_close or close
        normalized_high = max(float(high), float(low), float(open_price), float(close))
        normalized_low = min(float(high), float(low), float(open_price), float(close))
        rows.append(
            {
                "date": ds,
                "tradeDate": ds.replace("-", ""),
                "open": float(open_price),
                "high": normalized_high,
                "low": normalized_low,
                "close": float(close),
                "prev_close": float(prev_close),
                "volume": _number(raw.get("volume") or raw.get("vol")) or 0.0,
                "amount": _number(raw.get("amount")) or 0.0,
            }
        )
        previous_close = float(close)
    rows.sort(key=lambda item: item["date"])
    return rows


def _latest_path_features(rows: List[Dict[str, Any]]) -> Dict[str, float]:
    closes = [float(item["close"]) for item in rows]
    ranges = [
        max(0.0, (float(item["high"]) - float(item["low"])) / max(float(item["close"]), EPSILON))
        for item in rows[-20:]
    ]
    returns = [
        (closes[index] - closes[index - 1]) / max(closes[index - 1], EPSILON)
        for index in range(1, len(closes))
    ]
    volume_values = [float(item.get("volume") or 0.0) for item in rows[-20:]]
    return {
        "return20d": _window_return_from_values(closes, 20),
        "return60d": _window_return_from_values(closes, 60),
        "volatility20d": _stddev(returns[-20:]),
        "rangeRatio20d": mean(ranges) if ranges else 0.0,
        "liquidityStress": _liquidity_stress(volume_values),
    }


def _mfe_mae_probability_series(
    labels: List[Dict[str, Any]],
    cfg: Dict[str, Any],
    horizon_days: int,
    favorable_probability: float,
    breach_probability: float,
    current_prediction: Dict[str, Any],
) -> List[Dict[str, Any]]:
    favorable_threshold = float(cfg["favorable_mfe_threshold_pct"])
    mae_warning = float(cfg["mae_warning_pct"])
    series: List[Dict[str, Any]] = []
    start_index = max(0, len(labels) - 119)
    for offset, item in enumerate(labels[start_index:], start=start_index):
        mfe = float(item["mfeLabel"])
        mae_abs = float(item["maeAbsLabel"])
        risk_reward = float(item["riskRewardLabel"])
        favorable = 1.0 if mfe >= favorable_threshold else 0.0
        breach = 1.0 if mae_abs >= mae_warning else 0.0
        prior = labels[max(0, offset - 60) : offset]
        prior_labeled = [
            row
            for row in prior
            if row.get("labelStatus") == "LABELED_HISTORICAL"
            and row.get("actualUpLabel") is not None
            and row.get("actualDownLabel") is not None
        ]
        if len(prior_labeled) >= 10:
            prediction_up = sum(float(row.get("actualUpLabel") or 0.0) for row in prior_labeled) / len(prior_labeled)
            prediction_down = sum(float(row.get("actualDownLabel") or 0.0) for row in prior_labeled) / len(prior_labeled)
        else:
            trend_probs = _trend_probabilities_from_path(favorable, breach)
            prediction_up = trend_probs["up"]
            prediction_down = trend_probs["down"]
        series.append(
            {
                "tradeDate": item["tradeDate"],
                "date": item["tradeDate"],
                "horizonDays": horizon_days,
                "mfeLabel": round(mfe, 6),
                "maeLabel": round(float(item["maeLabel"]), 6),
                "maeAbsLabel": round(mae_abs, 6),
                "riskRewardLabel": round(risk_reward, 6),
                "mfeFavorable": bool(favorable),
                "maeBreach": bool(breach),
                "mfeFavorableProbability": favorable,
                "maeBreachProbability": breach,
                "bottomRepairProbability": favorable,
                "breakdownRiskProbability": breach,
                "repairProb": favorable,
                "breakdownRisk": breach,
                "predictionUpProbability": round(prediction_up, 6),
                "predictionDownProbability": round(prediction_down, 6),
                "actualForwardReturn": round(float(item["actualForwardReturn"]), 6),
                "actualUpLabel": int(item["actualUpLabel"]),
                "actualDownLabel": int(item["actualDownLabel"]),
                "actualDirection": item["actualDirection"],
                "labelStatus": "LABELED_HISTORICAL",
                "labelWindowStart": item.get("labelWindowStart"),
                "labelWindowEnd": item.get("labelWindowEnd"),
                "simulation_only": SIMULATION_ONLY,
                "is_real_trade": IS_REAL_TRADE,
            }
        )
    series.append(
        {
            "tradeDate": current_prediction.get("tradeDate"),
            "date": current_prediction.get("tradeDate"),
            "horizonDays": horizon_days,
            "predictionMfeFavorableProbability": round(favorable_probability, 6),
            "predictionMaeBreachProbability": round(breach_probability, 6),
            "predictionRepairProb": round(favorable_probability, 6),
            "predictionBreakdownRisk": round(breach_probability, 6),
            "mfeProxy": current_prediction.get("mfeProxy"),
            "maeProxy": current_prediction.get("maeProxy"),
            "riskRewardProxy": current_prediction.get("riskRewardProxy"),
            "riskPolicy": current_prediction.get("riskPolicy"),
            "regimeState": current_prediction.get("regimeState"),
            "labelStatus": "UNLABELED_NOWCAST",
            "simulation_only": SIMULATION_ONLY,
            "is_real_trade": IS_REAL_TRADE,
        }
    )
    return series


def _primary_mfe_mae_forecast(forecasts: List[Dict[str, Any]], horizon_days: int) -> Dict[str, Any]:
    for item in forecasts:
        if int(item.get("horizonDays") or 0) == horizon_days:
            return item
    return forecasts[0] if forecasts else {}


def _public_mfe_mae_horizon_forecast(item: Dict[str, Any]) -> Dict[str, Any]:
    allowed = {
        "horizonDays",
        "status",
        "sampleCount",
        "mfeFavorableProbability",
        "maeBreachProbability",
        "mfeProxy",
        "maeProxy",
        "riskRewardProxy",
        "downsideRiskScore",
        "riskPolicy",
        "trendProbabilities",
        "trendBias",
        "confidence",
        "evidenceGrade",
        "regimeState",
        "currentPrediction",
        "pathQuantiles",
        "riskCurve",
        "marketProfile",
    }
    public = {key: value for key, value in item.items() if key in allowed}
    public["bottomRepairProbability"] = public.get("mfeFavorableProbability")
    public["breakdownRiskProbability"] = public.get("maeBreachProbability")
    return public


def _mfe_mae_trend_synthesis(
    forecasts: List[Dict[str, Any]],
    primary: Dict[str, Any],
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    ready = [item for item in forecasts if item.get("status") == "READY"]
    policies = [str(item.get("riskPolicy") or "WATCH") for item in ready]
    primary_policy = str(primary.get("riskPolicy") or "WATCH")
    primary_rr = _number(primary.get("riskRewardProxy")) or 0.0
    confidence = _forecast_confidence(sum(int(item.get("sampleCount") or 0) for item in ready), evaluation_status="READY")
    risk_flags = []
    if primary_policy in {"THROTTLE", "AVOID_NEW_BUY"}:
        risk_flags.append("mfe_mae_downside_path_risk_high")
    if any(policy != primary_policy for policy in policies):
        risk_flags.append("mfe_mae_horizon_policy_mixed")
    if primary_rr < float(cfg["risk_reward_floor"]):
        risk_flags.append("mfe_mae_risk_reward_below_floor")
    return {
        "primaryHorizonDays": cfg["horizon_days"],
        "primaryTrendBias": _trend_bias_from_path(
            primary_policy,
            primary_rr,
            _number(primary.get("mfeFavorableProbability")) or 0.0,
            _number(primary.get("maeBreachProbability")) or 0.0,
        ),
        "horizonAlignment": "ALIGNED" if len(set(policies)) <= 1 else "MIXED",
        "confidence": confidence,
        "mainConclusion": (
            f"MFE/MAE path research uses {cfg['horizon_days']}-day labels; "
            f"policy={primary_policy}, riskRewardProxy={primary_rr:.2f}."
        ),
        "riskFlags": risk_flags,
        "keyDrivers": [
            "MFE=max(high[t+1:t+H])/close[t]-1",
            "MAE=min(low[t+1:t+H])/close[t]-1",
            f"market={cfg['marketProfile']['market']}",
        ],
        "evidenceConflict": bool(risk_flags),
    }


def _mfe_mae_qiam_adjustment_preview(primary: Dict[str, Any], synthesis: Dict[str, Any]) -> Dict[str, Any]:
    policy = str(primary.get("riskPolicy") or "WATCH")
    direction = "DOWN" if policy in {"THROTTLE", "AVOID_NEW_BUY"} else "NONE"
    return {
        "observed": bool(primary),
        "applied": False,
        "direction": direction,
        "reason": (
            "mfe_mae_path_risk_high_review_only"
            if direction == "DOWN"
            else "mfe_mae_path_research_neutral_or_supporting_only"
        ),
        "beforeFinalBuySuitability": "",
        "afterFinalBuySuitability": "",
        "maxStep": 1,
        "policy": "MFE_MAE_RESEARCH_SUPPORTING_ONLY_NO_PERMISSION_CHANGE",
        "canCreateTradeAction": False,
        "evidence": {
            "riskPolicy": policy,
            "downsideRiskScore": primary.get("downsideRiskScore"),
            "riskRewardProxy": primary.get("riskRewardProxy"),
            "trendBias": synthesis.get("primaryTrendBias"),
        },
        "blockedReasons": [],
    }


def _mfe_mae_formula_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "version": "mfe-mae-formula-config-v2",
        "labelFormula": {
            "mfeLabel": "max(high[t+1:t+H]) / close[t] - 1",
            "maeLabel": "min(low[t+1:t+H]) / close[t] - 1",
            "maeAbsLabel": "abs(min(0, maeLabel))",
            "riskRewardLabel": "mfeLabel / (maeAbsLabel + epsilon)",
            "epsilon": EPSILON,
        },
        "runtimePolicy": {
            "latestTradeDate": "UNLABELED_NOWCAST",
            "rankIcMode": RANK_IC_MODE,
            "quantiles": cfg["quantile_levels"],
            "conditionalQuantileEvaluationVersion": MFE_MAE_CONDITIONAL_QUANTILE_EVALUATION_VERSION,
            "conditionalQuantileMethod": "walk_forward_empirical_conditioned_quantile_v1",
            "riskPolicyBuckets": {"normalLt": 40, "watchLt": 60, "throttleLt": 75, "avoidGte": 75},
        },
        "marketAdaptation": cfg["marketProfile"],
    }


def _empty_current_prediction(rows: List[Dict[str, Any]], cfg: Dict[str, Any], horizon_days: int) -> Dict[str, Any]:
    trade_date = rows[-1]["date"] if rows else None
    return {
        "tradeDate": trade_date,
        "horizonDays": horizon_days,
        "labelStatus": "UNLABELED_NOWCAST",
        "mfeProxy": None,
        "maeProxy": None,
        "riskRewardProxy": None,
        "mfeFavorableProbability": None,
        "maeBreachProbability": None,
        "downsideRiskScore": None,
        "riskPolicy": "WATCH",
        "regimeState": "SUPPORTING_ONLY",
        "market": cfg["marketProfile"]["market"],
        "simulation_only": SIMULATION_ONLY,
        "is_real_trade": IS_REAL_TRADE,
    }


def _build_mfe_mae_risk_curve(
    buckets: List[float],
    mae_abs_values: List[float],
    profile: Dict[str, Any],
) -> List[Dict[str, Any]]:
    q80 = _quantile(mae_abs_values, 0.80)
    q90 = _quantile(mae_abs_values, 0.90)
    tail_multiplier = float(profile.get("downsideTailMultiplier") or 1.0)
    points: List[Dict[str, Any]] = []
    previous = 0.0
    for bucket in buckets:
        empirical_tail = _empirical_probability(mae_abs_values, bucket, mode="gte")
        risk_potential = min(1.0, (empirical_tail * 0.65 + min(1.0, bucket / max(q90, EPSILON)) * 0.35) * tail_multiplier)
        gradient = max(0.0, risk_potential - previous)
        points.append(
            {
                "drawdownPct": round(bucket * 100.0, 2),
                "riskPotential": round(risk_potential, 6),
                "riskGradient": round(gradient, 6),
                "components": {
                    "empiricalTail": round(empirical_tail, 6),
                    "q80MaeAbs": round(q80, 6),
                    "q90MaeAbs": round(q90, 6),
                    "marketTailMultiplier": round(tail_multiplier, 6),
                },
            }
        )
        previous = risk_potential
    return points


def _downside_score(
    *,
    mae_breach_probability: float,
    mae_proxy: float,
    mae_avoid: float,
    liquidity_stress: float,
    momentum: float,
    limit_stress: float,
    market: str,
) -> float:
    market_addon = 6.0 if market == "HK" else 0.0
    score = (
        mae_breach_probability * 45.0
        + min(1.0, mae_proxy / max(mae_avoid, EPSILON)) * 28.0
        + min(1.0, liquidity_stress) * 12.0
        + min(1.0, max(0.0, -momentum) / 0.12) * 10.0
        + min(1.0, limit_stress) * 8.0
        + market_addon
    )
    return max(0.0, min(100.0, score))


def _mfe_mae_risk_policy(score: float) -> str:
    if score < 40:
        return "NORMAL"
    if score < 60:
        return "WATCH"
    if score < 75:
        return "THROTTLE"
    return "AVOID_NEW_BUY"


def _mfe_mae_regime_state(policy: str, risk_reward_proxy: float) -> str:
    if policy == "AVOID_NEW_BUY":
        return "MFE_MAE_AVOID_NEW_BUY"
    if policy == "THROTTLE":
        return "MFE_MAE_THROTTLE"
    if policy == "NORMAL" and risk_reward_proxy >= 1.5:
        return "MFE_MAE_FAVORABLE_PATH"
    return "MFE_MAE_WATCH"


def _mfe_mae_evidence_grade(evaluation: Dict[str, Any], forecasts: List[Dict[str, Any]]) -> str:
    if evaluation.get("status") != "READY" or not forecasts:
        return "LOW"
    evaluated = int(((evaluation.get("quantileCoverage") or {}).get("evaluatedTestCount") or 0))
    if evaluated >= 80 and len(forecasts) >= 3:
        return "HIGH"
    if evaluated >= 30:
        return "MEDIUM"
    return "LOW"


def _forecast_evidence_grade(sample_count: int, risk_reward_proxy: float) -> str:
    if sample_count >= 160 and risk_reward_proxy > 0:
        return "HIGH"
    if sample_count >= 60:
        return "MEDIUM"
    return "LOW"


def _forecast_confidence(sample_count: int, *, evaluation_status: str) -> float:
    base = min(0.82, 0.35 + sample_count / 400.0)
    if evaluation_status != "READY":
        base *= 0.65
    return round(max(0.0, min(0.9, base)), 4)


def _trend_probabilities_from_path(favorable_probability: float, breach_probability: float) -> Dict[str, float]:
    up = max(0.05, 0.25 + favorable_probability * 0.50 - breach_probability * 0.15)
    down = max(0.05, 0.20 + breach_probability * 0.55 - favorable_probability * 0.10)
    sideways = max(0.05, 1.0 - up - down)
    total = up + down + sideways
    return {
        "up": round(up / total, 6),
        "sideways": round(sideways / total, 6),
        "down": round(down / total, 6),
    }


def _trend_bias_from_path(
    risk_policy: str,
    risk_reward_proxy: float,
    favorable_probability: float,
    breach_probability: float,
) -> str:
    if risk_policy in {"THROTTLE", "AVOID_NEW_BUY"} or breach_probability >= 0.60:
        return "DOWN"
    if risk_reward_proxy >= 1.5 and favorable_probability > breach_probability:
        return "UP"
    return "SIDEWAYS"


def _limit_board_stress(row: Dict[str, Any], profile: Dict[str, Any]) -> float:
    limit_pct = profile.get("dailyPriceLimitPct")
    if not limit_pct:
        return 0.0
    prev_close = _number(row.get("prev_close")) or _number(row.get("close")) or 0.0
    close = _number(row.get("close")) or 0.0
    if prev_close <= 0 or close <= 0:
        return 0.0
    limit_down = prev_close * (1.0 - float(limit_pct))
    distance = (close - limit_down) / max(close, EPSILON)
    return max(0.0, min(1.0, 1.0 - distance / max(float(limit_pct), EPSILON)))


def _empirical_probability(values: List[float], threshold: float, *, mode: str) -> float:
    clean = [float(item) for item in values if math.isfinite(float(item))]
    if not clean:
        return 0.0
    if mode == "gte":
        return sum(1 for item in clean if item >= threshold) / len(clean)
    return sum(1 for item in clean if item <= threshold) / len(clean)


def _window_return_from_values(values: List[float], window: int) -> float:
    if len(values) <= window:
        return 0.0
    start = values[-window - 1]
    end = values[-1]
    return (end - start) / max(start, EPSILON)


def _stddev(values: List[float]) -> float:
    clean = [float(item) for item in values if math.isfinite(float(item))]
    if len(clean) < 2:
        return 0.0
    avg = mean(clean)
    return math.sqrt(sum((item - avg) ** 2 for item in clean) / len(clean))


def _liquidity_stress(values: List[float]) -> float:
    clean = [float(item) for item in values if math.isfinite(float(item)) and item > 0]
    if len(clean) < 5:
        return 0.35
    latest = clean[-1]
    avg = mean(clean)
    if avg <= 0:
        return 0.35
    return max(0.0, min(1.0, 1.0 - latest / (avg * 1.5)))


def _normalize_horizon_days(value: Any, primary_horizon: int) -> List[int]:
    raw_values = value if isinstance(value, list) else DEFAULT_MFE_MAE_PATH_RESEARCH_CONFIG["horizon_days_list"]
    horizons: List[int] = []
    for item in raw_values:
        horizon = _bounded_int(item, 5, 90, 0)
        if horizon and horizon not in horizons:
            horizons.append(horizon)
    if primary_horizon not in horizons:
        horizons.append(primary_horizon)
    return sorted(horizons or [primary_horizon])


def _normalize_quantile_levels(value: Any) -> List[float]:
    raw_values = value if isinstance(value, list) else DEFAULT_MFE_MAE_PATH_RESEARCH_CONFIG["quantile_levels"]
    levels: List[float] = []
    for item in raw_values:
        parsed = _number(item)
        if parsed is None:
            continue
        parsed = max(0.01, min(0.99, parsed))
        if parsed not in levels:
            levels.append(parsed)
    return sorted(levels or [0.5, 0.8, 0.9])


def _bounded_int(value: Any, lower: int, upper: int, fallback: int) -> int:
    parsed = _positive_int(value, fallback)
    return max(lower, min(upper, parsed))


def _bounded_float(value: Any, lower: float, upper: float, fallback: float) -> float:
    parsed = _number(value)
    if parsed is None:
        parsed = fallback
    return max(lower, min(upper, float(parsed)))


def _normalize_ohlcv_rows(raw_rows: Any) -> List[Dict[str, float | str]]:
    if not isinstance(raw_rows, list):
        return []

    rows: List[Dict[str, float | str]] = []
    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        ds = _date_text(raw.get("date") or raw.get("tradeDate") or raw.get("trade_date"))
        open_price = _number(raw.get("open"))
        high = _number(raw.get("high"))
        low = _number(raw.get("low"))
        close = _number(raw.get("close"))
        if not ds or None in (open_price, high, low, close) or close <= 0:
            continue
        normalized_high = max(float(high), float(low), float(open_price), float(close))
        normalized_low = min(float(high), float(low), float(open_price), float(close))
        rows.append(
            {
                "date": ds,
                "open": float(open_price),
                "high": normalized_high,
                "low": normalized_low,
                "close": float(close),
            }
        )

    rows.sort(key=lambda item: str(item["date"]))
    return rows


def _normalize_labeled_records(records: List[Any]) -> tuple[List[Dict[str, Any]], List[str]]:
    labeled: List[Dict[str, Any]] = []
    excluded_trade_dates: List[str] = []
    for raw in records:
        if not isinstance(raw, dict):
            continue
        trade_date = _date_text(raw.get("tradeDate") or raw.get("date") or raw.get("trade_date"))
        status = str(raw.get("labelStatus") or "LABELED_HISTORICAL").upper()
        if status != "LABELED_HISTORICAL":
            if trade_date:
                excluded_trade_dates.append(trade_date)
            continue

        mfe = _number(raw.get("mfeLabel"))
        mae = _number(raw.get("maeLabel"))
        mae_abs = _number(raw.get("maeAbsLabel"))
        if mae_abs is None and mae is not None:
            mae_abs = abs(min(0.0, mae))
        risk_reward = _number(raw.get("riskRewardLabel"))
        entry_price = _number(raw.get("entryPrice") or raw.get("entryClose") or raw.get("close"))
        if (
            not trade_date
            or mfe is None
            or mae is None
            or mae_abs is None
            or risk_reward is None
            or entry_price is None
            or entry_price <= 0
        ):
            continue

        labeled.append(
            {
                **raw,
                "tradeDate": trade_date,
                "entryPrice": float(entry_price),
                "mfeLabel": float(mfe),
                "maeLabel": float(mae),
                "maeAbsLabel": float(mae_abs),
                "riskRewardLabel": float(risk_reward),
                "entryRiskProxy": _number(raw.get("entryRiskProxy")),
                "entryBodyProxy": _number(raw.get("entryBodyProxy")),
            }
        )

    labeled.sort(key=lambda item: item["tradeDate"])
    return labeled, sorted(excluded_trade_dates)


def _walk_forward_windows(records: List[Dict[str, Any]]) -> List[Dict[str, List[Dict[str, Any]]]]:
    count = len(records)
    train_size = max(20, min(80, count // 2))
    remaining = count - train_size
    if remaining < 5:
        return []

    test_size = max(5, min(20, max(5, remaining // 3)))
    windows: List[Dict[str, List[Dict[str, Any]]]] = []
    test_start = train_size
    while test_start < count:
        test_end = min(count, test_start + test_size)
        if test_end - test_start < 3:
            break
        windows.append(
            {
                "train": records[:test_start],
                "test": records[test_start:test_end],
            }
        )
        test_start = test_end
    return windows


def _entry_proxy_score(record: Dict[str, Any], train_q80_mae_abs: float) -> float:
    entry_risk_proxy = _number(record.get("entryRiskProxy"))
    if entry_risk_proxy is None:
        entry_price = _number(record.get("entryPrice")) or 1.0
        entry_risk_proxy = math.log(max(entry_price, 1.0)) / 100.0
    return float(entry_risk_proxy) / (float(train_q80_mae_abs) + EPSILON)


def _empty_target_quantile_lists() -> Dict[str, Dict[float, List[float]]]:
    return {
        target: {level: [] for level in CONDITIONAL_QUANTILE_LEVELS}
        for target in CONDITIONAL_QUANTILE_TARGETS
    }


def _empty_target_quantile_counts() -> Dict[str, Dict[float, int]]:
    return {
        target: {level: 0 for level in CONDITIONAL_QUANTILE_LEVELS}
        for target in CONDITIONAL_QUANTILE_TARGETS
    }


def _condition_thresholds(train: List[Dict[str, Any]]) -> Dict[str, float]:
    values = [_condition_value(record) for record in train]
    return {
        "low": _quantile(values, 1.0 / 3.0),
        "high": _quantile(values, 2.0 / 3.0),
    }


def _conditioned_train_records(
    train: List[Dict[str, Any]],
    record: Dict[str, Any],
    thresholds: Dict[str, float],
) -> tuple[List[Dict[str, Any]], bool]:
    bucket = _condition_bucket(record, thresholds)
    conditioned = [
        item
        for item in train
        if _condition_bucket(item, thresholds) == bucket
    ]
    if len(conditioned) >= 8:
        return conditioned, False
    return train, True


def _condition_bucket(record: Dict[str, Any], thresholds: Dict[str, float]) -> str:
    value = _condition_value(record)
    low = float(thresholds.get("low") or 0.0)
    high = float(thresholds.get("high") or low)
    if value <= low:
        return "LOW"
    if value <= high:
        return "MID"
    return "HIGH"


def _condition_value(record: Dict[str, Any]) -> float:
    entry_risk_proxy = _number(record.get("entryRiskProxy"))
    entry_body_proxy = _number(record.get("entryBodyProxy"))
    if entry_risk_proxy is None:
        entry_price = _number(record.get("entryPrice")) or 1.0
        entry_risk_proxy = math.log(max(entry_price, 1.0)) / 100.0
    return max(0.0, float(entry_risk_proxy)) + max(0.0, float(entry_body_proxy or 0.0)) * 0.25


def _target_quantiles(records: List[Dict[str, Any]]) -> Dict[str, Dict[float, float]]:
    target_values = {
        "mfe": [float(record["mfeLabel"]) for record in records],
        "maeAbs": [float(record["maeAbsLabel"]) for record in records],
        "riskReward": [float(record["riskRewardLabel"]) for record in records],
    }
    return {
        target: {
            level: _quantile(values, level)
            for level in CONDITIONAL_QUANTILE_LEVELS
        }
        for target, values in target_values.items()
    }


def _target_actuals(record: Dict[str, Any]) -> Dict[str, float]:
    return {
        "mfe": float(record["mfeLabel"]),
        "maeAbs": float(record["maeAbsLabel"]),
        "riskReward": float(record["riskRewardLabel"]),
    }


def _conditional_coverage_payload(
    hits: Dict[str, Dict[float, int]],
    predictions: Dict[str, Dict[float, List[float]]],
    evaluated_count: int,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"evaluatedTestCount": evaluated_count}
    for target in CONDITIONAL_QUANTILE_TARGETS:
        target_payload: Dict[str, Any] = {"evaluatedTestCount": evaluated_count}
        for level in CONDITIONAL_QUANTILE_LEVELS:
            key = _quantile_key(level)
            coverage = _safe_divide(int(hits.get(target, {}).get(level, 0)), evaluated_count)
            target_payload[key] = {
                "coverage": coverage,
                "thresholdMean": _rounded_mean(predictions.get(target, {}).get(level, [])),
                "testCount": evaluated_count,
            }
            target_payload[f"{key}Coverage"] = coverage
        payload[target] = target_payload
    return payload


def _conditional_rank_ic(
    predictions: Dict[str, Dict[float, List[float]]],
    actuals: Dict[str, List[float]],
) -> Dict[str, Optional[float]]:
    payload: Dict[str, Optional[float]] = {}
    for target in CONDITIONAL_QUANTILE_TARGETS:
        actual_values = actuals.get(target, [])
        for level in CONDITIONAL_QUANTILE_LEVELS:
            key = f"{target}{_quantile_key(level).upper()}RankIc"
            payload[key] = _spearman(predictions.get(target, {}).get(level, []), actual_values)
    payload["mfeQ80ToMfe"] = payload.get("mfeQ80RankIc")
    payload["maeQ80ToMaeAbs"] = payload.get("maeAbsQ80RankIc")
    payload["riskRewardQ50ToRiskReward"] = payload.get("riskRewardQ50RankIc")
    return payload


def _empty_conditional_quantile_coverage() -> Dict[str, Any]:
    return _conditional_coverage_payload(
        _empty_target_quantile_counts(),
        _empty_target_quantile_lists(),
        0,
    )


def _empty_conditional_rank_ic() -> Dict[str, Optional[float]]:
    return _conditional_rank_ic(
        _empty_target_quantile_lists(),
        {target: [] for target in CONDITIONAL_QUANTILE_TARGETS},
    )


def _quantile_key(level: float) -> str:
    return f"q{int(round(level * 100))}"


def _quantile(values: Sequence[float], q: float) -> float:
    clean = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not clean:
        return 0.0
    if len(clean) == 1:
        return clean[0]
    position = (len(clean) - 1) * max(0.0, min(1.0, q))
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return clean[lower]
    weight = position - lower
    return clean[lower] * (1.0 - weight) + clean[upper] * weight


def _spearman(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    x_ranks = _ranks(xs)
    y_ranks = _ranks(ys)
    x_mean = mean(x_ranks)
    y_mean = mean(y_ranks)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_ranks, y_ranks))
    x_denom = math.sqrt(sum((x - x_mean) ** 2 for x in x_ranks))
    y_denom = math.sqrt(sum((y - y_mean) ** 2 for y in y_ranks))
    if x_denom <= EPSILON or y_denom <= EPSILON:
        return 0.0
    return round(numerator / (x_denom * y_denom), 6)


def _ranks(values: Sequence[float]) -> List[float]:
    ordered = sorted((float(value), index) for index, value in enumerate(values))
    ranks = [0.0 for _ in ordered]
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][0] == ordered[index][0]:
            end += 1
        rank = (index + 1 + end) / 2.0
        for _, original_index in ordered[index:end]:
            ranks[original_index] = rank
        index = end
    return ranks


def _sample_quality(
    *,
    input_count: int,
    labeled_count: int,
    excluded_trade_dates: List[str],
    fold_count: int,
    evaluated_test_count: int,
    status: str,
    reasons: List[str],
) -> Dict[str, Any]:
    return {
        "quality": "OK" if status == "READY" else "LOW",
        "inputCount": input_count,
        "labeledCount": labeled_count,
        "excludedCount": max(0, input_count - labeled_count),
        "latestExcludedTradeDate": excluded_trade_dates[-1] if excluded_trade_dates else None,
        "foldCount": fold_count,
        "evaluatedTestCount": evaluated_test_count,
        "minReadySamples": MIN_WALK_FORWARD_SAMPLES,
        "reasons": reasons,
    }


def _empty_quantile_coverage() -> Dict[str, Any]:
    return {
        "q80": {"coverage": None, "thresholdMean": None, "testCount": 0},
        "q90": {"coverage": None, "thresholdMean": None, "testCount": 0},
        "q80Coverage": None,
        "q90Coverage": None,
        "evaluatedTestCount": 0,
    }


def _rounded_mean(values: Sequence[float]) -> Optional[float]:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    if not clean:
        return None
    return round(mean(clean), 10)


def _safe_divide(numerator: int, denominator: int) -> Optional[float]:
    if denominator <= 0:
        return None
    return round(float(numerator) / float(denominator), 6)


def _positive_int(value: Any, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = fallback
    return parsed if parsed > 0 else fallback


def _number(value: Any) -> Optional[float]:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        parsed = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _date_text(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text[:10]
