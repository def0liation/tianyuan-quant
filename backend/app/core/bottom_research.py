from __future__ import annotations

import hashlib
import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import mean, pstdev
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

from .mfe_mae_path_risk_research import (
    DEFAULT_MFE_MAE_PATH_RESEARCH_CONFIG,
    MFE_MAE_PATH_RESEARCH_VERSION,
    build_mfe_mae_label_records,
    build_mfe_mae_path_research_analysis,
    evaluate_mfe_mae_path_risk_walk_forward,
    normalize_mfe_mae_path_research_config,
)


BOTTOM_RESEARCH_MODEL_VERSION = MFE_MAE_PATH_RESEARCH_VERSION

DEFAULT_BOTTOM_RESEARCH_CONFIG: Dict[str, Any] = {
    **DEFAULT_MFE_MAE_PATH_RESEARCH_CONFIG,
    "lookback_range": "2y",
    "horizon_days": 20,
    "horizon_days_list": [5, 20, 60],
    "cov_window": 20,
    "min_drawdown_pct": 0.12,
    "downside_tolerance_pct": 0.05,
    "recovery_return_pct": 0.08,
    "repair_probability_threshold": 0.60,
    "max_research_position_pct": 0.30,
}

MARKET_ADAPTIVE_MFE_CONFIG_KEYS = {
    "favorable_mfe_threshold_pct",
    "mae_warning_pct",
    "mae_avoid_pct",
}

FEATURE_NAMES = [
    "return_5d",
    "return_20d",
    "return_60d",
    "drawdown_120d",
    "distance_to_support_60d",
    "distance_to_resistance_60d",
    "volatility_20d",
    "range_ratio_20d",
    "volume_zscore_20d",
    "riemann_airm_distance",
    "riemann_logeuclidean_distance",
    "riemann_tangent_norm",
]


@dataclass
class ModelResult:
    status: str
    probability: Optional[float]
    predictions: Dict[str, float]
    diagnostics: Dict[str, Any]


def normalize_bottom_research_config(
    config: Optional[Dict[str, Any]] = None,
    *,
    symbol: str = "",
    auxiliary_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    user_config = config if isinstance(config, dict) else {}
    payload = dict(DEFAULT_BOTTOM_RESEARCH_CONFIG)
    payload.update({key: value for key, value in user_config.items() if value is not None})
    mfe_config = dict(payload)
    for key in MARKET_ADAPTIVE_MFE_CONFIG_KEYS:
        if key not in user_config:
            mfe_config.pop(key, None)
    mfe_payload = normalize_mfe_mae_path_research_config(
        mfe_config,
        symbol=symbol,
        auxiliary_data=auxiliary_data,
    )
    payload.update(mfe_payload)

    payload["lookback_range"] = str(payload.get("lookback_range") or "2y")
    payload["horizon_days"] = _int_between(payload.get("horizon_days"), 5, 60, 20)
    payload["horizon_days_list"] = _normalize_horizon_days_list(
        payload.get("horizon_days_list"),
        payload["horizon_days"],
    )
    payload["cov_window"] = _int_between(payload.get("cov_window"), 10, 80, 20)
    payload["min_drawdown_pct"] = _float_between(payload.get("min_drawdown_pct"), 0.02, 0.60, 0.12)
    payload["downside_tolerance_pct"] = _float_between(payload.get("downside_tolerance_pct"), 0.01, 0.30, 0.05)
    payload["recovery_return_pct"] = _float_between(payload.get("recovery_return_pct"), 0.02, 0.80, 0.08)
    payload["repair_probability_threshold"] = _float_between(
        payload.get("repair_probability_threshold"),
        0.20,
        0.95,
        0.60,
    )
    payload["max_research_position_pct"] = _float_between(payload.get("max_research_position_pct"), 0.0, 0.50, 0.30)
    return payload


def _normalize_horizon_days_list(value: Any, primary_horizon: int) -> List[int]:
    raw_values = value if isinstance(value, list) else DEFAULT_BOTTOM_RESEARCH_CONFIG["horizon_days_list"]
    horizons: List[int] = []
    for item in raw_values:
        horizon = _int_between(item, 5, 60, 0)
        if horizon and horizon not in horizons:
            horizons.append(horizon)
    if primary_horizon not in horizons:
        horizons.append(primary_horizon)
    if not horizons:
        horizons = [5, 20, 60]
    sorted_horizons = sorted(horizons)
    if len(sorted_horizons) <= 5:
        return sorted_horizons
    other_horizons = [horizon for horizon in sorted_horizons if horizon != primary_horizon][:4]
    return sorted(other_horizons + [primary_horizon])


def build_bottom_research_analysis(
    symbol: str,
    daily_payload: Optional[Dict[str, Any]] = None,
    *,
    rows: Optional[List[Dict[str, Any]]] = None,
    auxiliary_data: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    cfg = normalize_bottom_research_config(config, symbol=symbol, auxiliary_data=auxiliary_data)
    return build_mfe_mae_path_research_analysis(
        symbol,
        daily_payload,
        rows=rows,
        auxiliary_data=auxiliary_data,
        config=cfg,
    )

    warnings: List[str] = []
    missing_data: List[str] = []
    normalized_rows = normalize_price_rows(rows if rows is not None else (daily_payload or {}).get("rows"))
    provider = str((daily_payload or {}).get("provider") or "custom").lower()
    data_mode = str((daily_payload or {}).get("dataMode") or ("LIVE" if rows is not None else "UNAVAILABLE"))
    status = str((daily_payload or {}).get("status") or ("READY" if rows is not None else "FAILED"))

    max_horizon = max(cfg["horizon_days_list"] or [cfg["horizon_days"]])
    min_required = max(90, cfg["cov_window"] + max_horizon + 35)
    if status != "READY" and rows is None:
        missing_data.append("tushare_daily_kline_unavailable")
    if len(normalized_rows) < min_required:
        missing_data.append(f"daily_kline_less_than_{min_required}")

    if missing_data:
        return _supporting_only_payload(
            symbol=symbol,
            cfg=cfg,
            rows=normalized_rows,
            provider=provider,
            data_mode=data_mode,
            missing_data=missing_data,
            warnings=warnings,
            reason="insufficient_or_unavailable_kline",
        )

    latest_features = feature_vector_for_index(normalized_rows, len(normalized_rows) - 1, cfg)
    latest_riemann = latest_features.get("riemannianFeatures", {})
    horizon_forecasts = [
        _build_horizon_forecast(
            normalized_rows,
            cfg,
            horizon_days,
            latest_features["features"],
            normalized_rows[-1]["date"],
        )
        for horizon_days in cfg["horizon_days_list"]
    ]
    primary_forecast = _primary_horizon_forecast(horizon_forecasts, cfg["horizon_days"])
    feature_records = primary_forecast.get("featureRecords") if isinstance(primary_forecast.get("featureRecords"), list) else []
    if not feature_records:
        return _supporting_only_payload(
            symbol=symbol,
            cfg=cfg,
            rows=normalized_rows,
            provider=provider,
            data_mode=data_mode,
            missing_data=["feature_frame_empty"],
            warnings=warnings,
            reason="feature_frame_empty",
        )

    bottom_model = primary_forecast["bottomModel"]
    breakdown_model = primary_forecast["breakdownModel"]

    if bottom_model.status != "READY":
        warnings.append("bottom_repair_model_supporting_only")
    if breakdown_model.status != "READY":
        warnings.append("breakdown_risk_model_supporting_only")

    bottom_probability = bottom_model.probability
    breakdown_probability = breakdown_model.probability
    threshold = cfg["repair_probability_threshold"]
    regime_state = _regime_state(bottom_probability, breakdown_probability, threshold)
    position_envelope = _position_envelope(bottom_probability, breakdown_probability, cfg)
    probability_series = _probability_series(feature_records, bottom_model.predictions, breakdown_model.predictions)
    current_prediction = _current_prediction(
        trade_date=normalized_rows[-1]["date"],
        bottom_probability=bottom_probability,
        breakdown_probability=breakdown_probability,
        regime_state=regime_state,
        cfg=cfg,
    )
    evidence_grade = _evidence_grade(bottom_model.diagnostics, breakdown_model.diagnostics)
    horizon_probability_series = _horizon_probability_series(horizon_forecasts)
    public_horizon_forecasts = [_public_horizon_forecast(item) for item in horizon_forecasts]
    trend_synthesis = _trend_synthesis(public_horizon_forecasts, cfg)
    qiam_adjustment_preview = _qiam_adjustment_preview(primary_forecast, trend_synthesis, cfg)
    mfe_mae_label_records = build_mfe_mae_label_records(normalized_rows, cfg["horizon_days"])
    mfe_mae_path_risk_evaluation = evaluate_mfe_mae_path_risk_walk_forward(
        [
            *mfe_mae_label_records,
            {
                "tradeDate": normalized_rows[-1]["date"],
                "horizonDays": cfg["horizon_days"],
                "labelStatus": "UNLABELED_NOWCAST",
                "simulation_only": True,
                "is_real_trade": False,
            },
        ]
    )

    diagnostics = {
        "status": "READY" if bottom_model.status == "READY" and breakdown_model.status == "READY" else "SUPPORTING_ONLY",
        "modelVersion": BOTTOM_RESEARCH_MODEL_VERSION,
        "featureVersion": "riemannian-covariance-v1",
        "sampleCount": len(feature_records),
        "leakagePolicy": "features_use_rows_ending_at_t; labels_use_future_window_only_for_historical_training",
        "bottomRepairModel": bottom_model.diagnostics,
        "breakdownRiskModel": breakdown_model.diagnostics,
        "walkForward": {
            "bottomRepair": bottom_model.diagnostics.get("walkForward", {}),
            "breakdownRisk": breakdown_model.diagnostics.get("walkForward", {}),
        },
        "evidenceGrade": evidence_grade,
        "horizonCount": len(public_horizon_forecasts),
        "auxiliaryInputs": _auxiliary_summary(auxiliary_data),
        "mfeMaePathRiskEvaluation": mfe_mae_path_risk_evaluation,
    }

    return {
        "agent": "bottom_research",
        "status": "PASS" if diagnostics["status"] == "READY" else "WARN",
        "bottomRepairProbability": bottom_probability,
        "breakdownRiskProbability": breakdown_probability,
        "regimeState": regime_state,
        "riemannianFeatures": latest_riemann,
        "modelDiagnostics": diagnostics,
        "positionEnvelope": position_envelope,
        "missingData": missing_data,
        "warnings": warnings,
        "provenance": {
            "sourceNode": "bottom_research",
            "modelVersion": BOTTOM_RESEARCH_MODEL_VERSION,
            "provider": provider,
            "dataMode": data_mode,
            "lookbackRange": cfg["lookback_range"],
            "dailyCount": len(normalized_rows),
            "firstTradeDate": normalized_rows[0]["date"],
            "lastTradeDate": normalized_rows[-1]["date"],
            "configHash": stable_payload_hash(cfg),
            "simulation_only": True,
            "is_real_trade": False,
            "generatedAt": _now_iso(),
        },
        "probabilitySeries": probability_series[-120:],
        "currentPrediction": current_prediction,
        "horizonProbabilitySeries": horizon_probability_series,
        "horizonForecasts": public_horizon_forecasts,
        "trendSynthesis": trend_synthesis,
        "qiamAdjustmentPreview": qiam_adjustment_preview,
        "config": cfg,
    }


def build_bottom_research_signals(
    symbol: str,
    market_data: List[Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    cfg = normalize_bottom_research_config(config, symbol=symbol)
    analysis = build_bottom_research_analysis(symbol, rows=market_data, config=cfg)
    favorable_threshold = cfg.get("favorable_mfe_threshold_pct", 0.06)
    risk_floor = cfg.get("risk_reward_floor", 1.2)
    signals: List[Dict[str, Any]] = []

    for item in analysis.get("probabilitySeries") or []:
        favorable = _number(item.get("mfeFavorableProbability") or item.get("bottomRepairProbability"))
        breach = _number(item.get("maeBreachProbability") or item.get("breakdownRiskProbability"))
        risk_reward = _number(item.get("riskRewardLabel") or item.get("riskRewardProxy"))
        if favorable is None or breach is None:
            continue
        if favorable < favorable_threshold and (risk_reward is None or risk_reward < risk_floor):
            continue
        if breach > min(0.55, favorable):
            continue
        strength = max(0.0, min(1.0, favorable * (1.0 - min(0.90, breach))))
        signals.append(
            {
                "timestamp": item["tradeDate"],
                "symbol": symbol,
                "signal_type": "MFE_MAE_PATH_REWARD_WATCH",
                "direction": "WATCH",
                "strength": round(strength, 4),
                "source_node": "mfe_mae_path_research",
                "metadata_json": {
                    "source": "MFE_MAE_PATH_RESEARCH",
                    "legacy_source": "BOTTOM_RESEARCH",
                    "model_version": BOTTOM_RESEARCH_MODEL_VERSION,
                    "mfe_favorable_probability": round(favorable, 6),
                    "mae_breach_probability": round(breach, 6),
                    "risk_reward": round(risk_reward, 6) if risk_reward is not None else None,
                    "bottom_repair_probability": round(favorable, 6),
                    "breakdown_risk_probability": round(breach, 6),
                    "regime_state": item.get("regimeState", ""),
                    "simulation_only": True,
                    "is_real_trade": False,
                    "trade_action_policy": "REVIEW_ONLY_NOT_TRADE_INSTRUCTION",
                },
            }
        )

    signal_hash = stable_payload_hash(signals, length=24)
    metadata = {
        "signal_source": "MFE_MAE_PATH_RESEARCH",
        "legacy_signal_source": "BOTTOM_RESEARCH",
        "source_node": "mfe_mae_path_research",
        "legacy_source_node": "bottom_research",
        "signal_count": len(signals),
        "signal_hash": signal_hash,
        "model_version": BOTTOM_RESEARCH_MODEL_VERSION,
        "config": cfg,
        "analysis_status": analysis.get("status"),
        "model_diagnostics": analysis.get("modelDiagnostics", {}),
        "simulation_only": True,
        "is_real_trade": False,
    }
    return signals, metadata


def normalize_price_rows(raw_rows: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw_rows, list):
        return []
    rows: List[Dict[str, Any]] = []
    previous_close: Optional[float] = None
    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        ds = _date_text(raw.get("tradeDate") or raw.get("date") or raw.get("trade_date"))
        open_price = _number(raw.get("open"))
        high = _number(raw.get("high"))
        low = _number(raw.get("low"))
        close = _number(raw.get("close"))
        if not ds or None in (open_price, high, low, close) or close <= 0:
            continue
        prev_close = _number(raw.get("prev_close") or raw.get("preClose") or raw.get("pre_close")) or previous_close or close
        rows.append(
            {
                "date": ds,
                "tradeDate": ds.replace("-", ""),
                "open": float(open_price),
                "high": max(float(high), float(low), float(close), float(open_price)),
                "low": min(float(high), float(low), float(close), float(open_price)),
                "close": float(close),
                "prev_close": float(prev_close),
                "volume": _number(raw.get("volume") or raw.get("vol")) or 0.0,
                "amount": _number(raw.get("amount")) or 0.0,
            }
        )
        previous_close = float(close)
    rows.sort(key=lambda item: item["date"])
    return rows


def build_feature_records(rows: List[Dict[str, Any]], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    cfg = normalize_bottom_research_config(config)
    horizon = cfg["horizon_days"]
    start_index = max(cfg["cov_window"] + 20, 60)
    records: List[Dict[str, Any]] = []
    for index in range(start_index, len(rows) - horizon):
        feature_payload = feature_vector_for_index(rows, index, cfg)
        label_payload = label_bottom_repair_event(rows, index, cfg)
        records.append(
            {
                "tradeDate": rows[index]["date"],
                "features": feature_payload["features"],
                "riemannianFeatures": feature_payload["riemannianFeatures"],
                **label_payload,
            }
        )
    return records


def feature_vector_for_index(rows: List[Dict[str, Any]], index: int, config: Dict[str, Any]) -> Dict[str, Any]:
    cfg = normalize_bottom_research_config(config)
    index = max(0, min(index, len(rows) - 1))
    close = rows[index]["close"]
    closes = [row["close"] for row in rows[: index + 1]]
    highs = [row["high"] for row in rows[: index + 1]]
    lows = [row["low"] for row in rows[: index + 1]]
    volumes = [row.get("volume", 0.0) for row in rows[: index + 1]]
    returns = _return_series(closes)

    support_60 = min(lows[-60:]) if len(lows) >= 2 else close
    resistance_60 = max(highs[-60:]) if len(highs) >= 2 else close
    rolling_high_120 = max(highs[-120:]) if highs else close
    drawdown = _safe_ratio(rolling_high_120 - close, rolling_high_120) or 0.0
    volume_zscore = _zscore(volumes[-20:], volumes[-1] if volumes else 0.0)
    range_values = [
        _safe_ratio(row["high"] - row["low"], row["close"]) or 0.0
        for row in rows[max(0, index - 19) : index + 1]
    ]
    current_cov = rolling_covariance_matrix(rows, index, cfg["cov_window"])
    center_cov = rolling_covariance_center(rows, index, cfg["cov_window"])
    airm = riemannian_distance_spd(current_cov, center_cov)
    loge = log_euclidean_distance_spd(current_cov, center_cov)
    tangent = tangent_space_vector(current_cov, center_cov)
    tangent_norm = math.sqrt(sum(value * value for value in tangent))

    features = {
        "return_5d": _window_return(closes, 5),
        "return_20d": _window_return(closes, 20),
        "return_60d": _window_return(closes, 60),
        "drawdown_120d": drawdown,
        "distance_to_support_60d": _safe_ratio(close - support_60, close) or 0.0,
        "distance_to_resistance_60d": _safe_ratio(resistance_60 - close, close) or 0.0,
        "volatility_20d": _std(returns[-20:]),
        "range_ratio_20d": mean(range_values) if range_values else 0.0,
        "volume_zscore_20d": volume_zscore,
        "riemann_airm_distance": airm,
        "riemann_logeuclidean_distance": loge,
        "riemann_tangent_norm": tangent_norm,
    }
    return {
        "features": {name: _finite_float(features.get(name), 0.0) for name in FEATURE_NAMES},
        "riemannianFeatures": {
            "covWindow": cfg["cov_window"],
            "airmDistance": round(airm, 6),
            "logEuclideanDistance": round(loge, 6),
            "tangentSpaceVector": [round(value, 6) for value in tangent[:6]],
            "tangentNorm": round(tangent_norm, 6),
            "currentCovariance": _round_matrix(current_cov),
            "stateCenterCovariance": _round_matrix(center_cov),
            "featureBasis": ["daily_return", "intraday_range", "volume_change", "gap_return"],
        },
    }


def label_bottom_repair_event(rows: List[Dict[str, Any]], index: int, config: Dict[str, Any]) -> Dict[str, Any]:
    cfg = normalize_bottom_research_config(config)
    horizon = cfg["horizon_days"]
    current = rows[index]
    close = current["close"]
    prior_high = max(row["high"] for row in rows[max(0, index - 120) : index + 1])
    drawdown = _safe_ratio(prior_high - close, prior_high) or 0.0
    future_rows = rows[index + 1 : index + 1 + horizon]
    if not future_rows or close <= 0:
        return {
            "bottomLabel": 0,
            "breakdownLabel": 0,
            "labelWindowStart": "",
            "labelWindowEnd": "",
            "labelReason": "future_window_unavailable",
        }

    future_low = min(row["low"] for row in future_rows)
    future_high = max(row["high"] for row in future_rows)
    downside_breach = future_low <= close * (1.0 - cfg["downside_tolerance_pct"])
    repair_hit = future_high >= close * (1.0 + cfg["recovery_return_pct"])
    enough_drawdown = drawdown >= cfg["min_drawdown_pct"]
    bottom_label = 1 if enough_drawdown and not downside_breach and repair_hit else 0
    breakdown_label = 1 if downside_breach else 0
    return {
        "bottomLabel": bottom_label,
        "breakdownLabel": breakdown_label,
        "labelWindowStart": future_rows[0]["date"],
        "labelWindowEnd": future_rows[-1]["date"],
        "labelReason": {
            "enoughDrawdown": enough_drawdown,
            "drawdownPct": round(drawdown, 6),
            "downsideBreach": downside_breach,
            "repairHit": repair_hit,
            "futureLowReturn": round((_safe_ratio(future_low - close, close) or 0.0), 6),
            "futureHighReturn": round((_safe_ratio(future_high - close, close) or 0.0), 6),
        },
    }


def train_probability_model(
    records: List[Dict[str, Any]],
    latest_features: Dict[str, float],
    *,
    label_key: str,
    prediction_key: str,
) -> ModelResult:
    labels = [int(record.get(label_key) or 0) for record in records]
    positives = sum(labels)
    negatives = len(labels) - positives
    diagnostics: Dict[str, Any] = {
        "label": label_key,
        "prediction": prediction_key,
        "sampleCount": len(labels),
        "positiveCount": positives,
        "negativeCount": negatives,
        "featureNames": FEATURE_NAMES,
    }
    if len(records) < 80 or positives < 5 or negatives < 5:
        diagnostics.update(
            {
                "status": "SUPPORTING_ONLY",
                "reason": "insufficient_class_balance_or_samples",
                "walkForward": {"folds": [], "brier": None, "prAuc": None},
            }
        )
        return ModelResult("SUPPORTING_ONLY", None, {}, diagnostics)

    sklearn_result = _train_with_sklearn(records, latest_features, labels)
    if sklearn_result is not None:
        diagnostics.update(sklearn_result["diagnostics"])
        return ModelResult("READY", sklearn_result["probability"], sklearn_result["predictions"], diagnostics)

    fallback_result = _train_with_gradient_descent(records, latest_features, labels)
    diagnostics.update(fallback_result["diagnostics"])
    return ModelResult("READY", fallback_result["probability"], fallback_result["predictions"], diagnostics)


def shrink_covariance(matrix: Sequence[Sequence[float]], alpha: float = 0.10) -> List[List[float]]:
    np = _numpy()
    if np is None:
        return _fallback_shrink_covariance(matrix, alpha)
    arr = np.asarray(matrix, dtype=float)
    if arr.ndim != 2:
        arr = arr.reshape((-1, 1))
    if arr.shape[0] <= 1:
        cov = np.eye(max(1, arr.shape[1]), dtype=float) * 1e-4
    else:
        cov = np.cov(arr, rowvar=False)
        if cov.ndim == 0:
            cov = np.asarray([[float(cov)]])
    diag = np.diag(np.diag(cov))
    shrunk = (1.0 - alpha) * cov + alpha * diag
    shrunk = shrunk + np.eye(shrunk.shape[0]) * 1e-6
    return shrunk.astype(float).tolist()


def riemannian_distance_spd(matrix_a: Sequence[Sequence[float]], matrix_b: Sequence[Sequence[float]]) -> float:
    np = _numpy()
    if np is None:
        return _frobenius_distance(matrix_a, matrix_b)
    a = _spd_array(matrix_a)
    b = _spd_array(matrix_b)
    eigvals, eigvecs = np.linalg.eigh(a)
    eigvals = np.maximum(eigvals, 1e-8)
    inv_sqrt = eigvecs @ np.diag(1.0 / np.sqrt(eigvals)) @ eigvecs.T
    middle = inv_sqrt @ b @ inv_sqrt
    middle_eigvals = np.maximum(np.linalg.eigvalsh(middle), 1e-8)
    return float(np.sqrt(np.sum(np.log(middle_eigvals) ** 2)))


def log_euclidean_distance_spd(matrix_a: Sequence[Sequence[float]], matrix_b: Sequence[Sequence[float]]) -> float:
    np = _numpy()
    if np is None:
        return _frobenius_distance(matrix_a, matrix_b)
    log_a = _matrix_log_spd(_spd_array(matrix_a))
    log_b = _matrix_log_spd(_spd_array(matrix_b))
    return float(np.linalg.norm(log_a - log_b, ord="fro"))


def tangent_space_vector(matrix: Sequence[Sequence[float]], center: Sequence[Sequence[float]]) -> List[float]:
    np = _numpy()
    if np is None:
        return [float(value) for row in matrix for value in row][:10]
    current_log = _matrix_log_spd(_spd_array(matrix))
    center_log = _matrix_log_spd(_spd_array(center))
    delta = current_log - center_log
    values: List[float] = []
    for row in range(delta.shape[0]):
        for col in range(row, delta.shape[1]):
            values.append(float(delta[row, col]))
    return values


def rolling_covariance_matrix(rows: List[Dict[str, Any]], index: int, window: int) -> List[List[float]]:
    start = max(1, index - window + 1)
    matrix: List[List[float]] = []
    for current in range(start, index + 1):
        prev = rows[current - 1]
        row = rows[current]
        prev_close = prev["close"] or row["prev_close"] or row["close"]
        prev_volume = prev.get("volume") or row.get("volume") or 1.0
        matrix.append(
            [
                _safe_ratio(row["close"] - prev_close, prev_close) or 0.0,
                _safe_ratio(row["high"] - row["low"], row["close"]) or 0.0,
                math.log(max(row.get("volume") or 1.0, 1.0) / max(prev_volume, 1.0)),
                _safe_ratio(row["open"] - prev_close, prev_close) or 0.0,
            ]
        )
    return shrink_covariance(matrix)


def rolling_covariance_center(rows: List[Dict[str, Any]], index: int, window: int) -> List[List[float]]:
    centers: List[List[List[float]]] = []
    step = max(5, window // 2)
    for end in range(max(window + 1, index - window * 4), max(window + 1, index - window + 1), step):
        centers.append(rolling_covariance_matrix(rows, end, window))
    if not centers:
        return rolling_covariance_matrix(rows, max(0, index - window), window)
    dimension = len(centers[0])
    result = [[0.0 for _ in range(dimension)] for _ in range(dimension)]
    for matrix in centers:
        for row in range(dimension):
            for col in range(dimension):
                result[row][col] += matrix[row][col] / len(centers)
    return result


def stable_payload_hash(value: Any, length: int = 16) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:length]


def _train_with_sklearn(
    records: List[Dict[str, Any]],
    latest_features: Dict[str, float],
    labels: List[int],
) -> Optional[Dict[str, Any]]:
    try:
        from sklearn.linear_model import SGDClassifier
        from sklearn.metrics import average_precision_score, brier_score_loss
        from sklearn.preprocessing import StandardScaler
    except (ImportError, OSError, ValueError, RuntimeError) as exc:
        logger.warning("sklearn not available — skipping ML model training (%s: %s)", type(exc).__name__, exc)
        return None

    np = _numpy()
    if np is None:
        return None

    x_all = np.asarray([_feature_row(record["features"]) for record in records], dtype=float)
    y_all = np.asarray(labels, dtype=int)
    predictions: Dict[str, float] = {}
    fold_metrics: List[Dict[str, Any]] = []
    fold_count = 4
    min_train = max(50, len(records) // 3)
    fold_size = max(10, (len(records) - min_train) // fold_count)

    for fold_index in range(fold_count):
        test_start = min_train + fold_index * fold_size
        if test_start >= len(records) - 5:
            break
        test_end = len(records) if fold_index == fold_count - 1 else min(len(records), test_start + fold_size)
        train_y = y_all[:test_start]
        test_y = y_all[test_start:test_end]
        if len(set(train_y.tolist())) < 2 or len(test_y) == 0:
            continue
        scaler = StandardScaler()
        train_x = scaler.fit_transform(x_all[:test_start])
        test_x = scaler.transform(x_all[test_start:test_end])
        classifier = SGDClassifier(
            loss="log_loss",
            penalty="l2",
            alpha=0.0005,
            class_weight="balanced",
            max_iter=2000,
            tol=1e-4,
            random_state=17,
        )
        classifier.fit(train_x, train_y)
        probs = classifier.predict_proba(test_x)[:, 1]
        for record, probability in zip(records[test_start:test_end], probs):
            predictions[record["tradeDate"]] = float(probability)
        fold_metrics.append(
            {
                "fold": fold_index + 1,
                "trainEnd": records[test_start - 1]["tradeDate"],
                "testStart": records[test_start]["tradeDate"],
                "testEnd": records[test_end - 1]["tradeDate"],
                "testSamples": int(len(test_y)),
                "positiveRate": round(float(np.mean(test_y)), 6),
                "brier": round(float(brier_score_loss(test_y, probs)), 6),
                "prAuc": round(float(average_precision_score(test_y, probs)), 6) if len(set(test_y.tolist())) > 1 else None,
            }
        )

    scaler = StandardScaler()
    final_x = scaler.fit_transform(x_all)
    final_model = SGDClassifier(
        loss="log_loss",
        penalty="l2",
        alpha=0.0005,
        class_weight="balanced",
        max_iter=2000,
        tol=1e-4,
        random_state=17,
    )
    final_model.fit(final_x, y_all)
    latest_x = scaler.transform(np.asarray([_feature_row(latest_features)], dtype=float))
    probability = float(final_model.predict_proba(latest_x)[0, 1])
    return {
        "probability": max(0.0, min(1.0, probability)),
        "predictions": predictions,
        "diagnostics": {
            "status": "READY",
            "trainer": "SGDClassifier(loss=log_loss)",
            "standardization": "fold_local_standard_scaler",
            "classBalance": "balanced",
            "calibration": "walk_forward_probability_monitoring",
            "walkForward": _walk_forward_summary(fold_metrics),
        },
    }


def _train_with_gradient_descent(
    records: List[Dict[str, Any]],
    latest_features: Dict[str, float],
    labels: List[int],
) -> Dict[str, Any]:
    x_all = [_feature_row(record["features"]) for record in records]
    means, scales = _standardization(x_all)
    x_scaled = [_scale_row(row, means, scales) for row in x_all]
    y_all = [int(value) for value in labels]
    predictions: Dict[str, float] = {}
    fold_metrics: List[Dict[str, Any]] = []
    fold_count = 4
    min_train = max(50, len(records) // 3)
    fold_size = max(10, (len(records) - min_train) // fold_count)

    for fold_index in range(fold_count):
        test_start = min_train + fold_index * fold_size
        if test_start >= len(records) - 5:
            break
        test_end = len(records) if fold_index == fold_count - 1 else min(len(records), test_start + fold_size)
        train_y = y_all[:test_start]
        test_y = y_all[test_start:test_end]
        if len(set(train_y)) < 2 or not test_y:
            continue
        fold_means, fold_scales = _standardization(x_all[:test_start])
        train_x = [_scale_row(row, fold_means, fold_scales) for row in x_all[:test_start]]
        test_x = [_scale_row(row, fold_means, fold_scales) for row in x_all[test_start:test_end]]
        weights, bias = _fit_logistic(train_x, train_y)
        probs = [_predict_logistic(row, weights, bias) for row in test_x]
        for record, probability in zip(records[test_start:test_end], probs):
            predictions[record["tradeDate"]] = float(probability)
        fold_metrics.append(
            {
                "fold": fold_index + 1,
                "trainEnd": records[test_start - 1]["tradeDate"],
                "testStart": records[test_start]["tradeDate"],
                "testEnd": records[test_end - 1]["tradeDate"],
                "testSamples": len(test_y),
                "positiveRate": round(sum(test_y) / len(test_y), 6),
                "brier": round(_brier(test_y, probs), 6),
                "prAuc": round(_average_precision(test_y, probs), 6) if len(set(test_y)) > 1 else None,
            }
        )

    weights, bias = _fit_logistic(x_scaled, y_all)
    latest_scaled = _scale_row(_feature_row(latest_features), means, scales)
    return {
        "probability": _predict_logistic(latest_scaled, weights, bias),
        "predictions": predictions,
        "diagnostics": {
            "status": "READY",
            "trainer": "fallback_logistic_gradient_descent",
            "standardization": "fold_local_standard_scaler",
            "classBalance": "inverse_frequency_weights",
            "calibration": "walk_forward_probability_monitoring",
            "walkForward": _walk_forward_summary(fold_metrics),
        },
    }


def _supporting_only_payload(
    *,
    symbol: str,
    cfg: Dict[str, Any],
    rows: List[Dict[str, Any]],
    provider: str,
    data_mode: str,
    missing_data: List[str],
    warnings: List[str],
    reason: str,
) -> Dict[str, Any]:
    return {
        "agent": "bottom_research",
        "status": "SKIPPED" if not rows else "WARN",
        "bottomRepairProbability": None,
        "breakdownRiskProbability": None,
        "regimeState": "SUPPORTING_ONLY",
        "riemannianFeatures": {},
        "modelDiagnostics": {
            "status": "SUPPORTING_ONLY",
            "reason": reason,
            "modelVersion": BOTTOM_RESEARCH_MODEL_VERSION,
            "sampleCount": len(rows),
            "leakagePolicy": "features_use_rows_ending_at_t; labels_use_future_window_only_for_historical_training",
            "evidenceGrade": "LOW",
        },
        "positionEnvelope": {
            "maxResearchPositionPct": cfg["max_research_position_pct"],
            "suggestedResearchPositionPct": 0.0,
            "policy": "REVIEW_ONLY_NOT_TRADE_INSTRUCTION",
            "simulation_only": True,
            "is_real_trade": False,
        },
        "missingData": missing_data,
        "warnings": warnings,
        "provenance": {
            "sourceNode": "bottom_research",
            "modelVersion": BOTTOM_RESEARCH_MODEL_VERSION,
            "provider": provider,
            "dataMode": data_mode,
            "lookbackRange": cfg["lookback_range"],
            "dailyCount": len(rows),
            "firstTradeDate": rows[0]["date"] if rows else "",
            "lastTradeDate": rows[-1]["date"] if rows else "",
            "configHash": stable_payload_hash(cfg),
            "simulation_only": True,
            "is_real_trade": False,
            "generatedAt": _now_iso(),
        },
        "probabilitySeries": [],
        "horizonProbabilitySeries": [],
        "horizonForecasts": [],
        "trendSynthesis": {
            "primaryHorizonDays": cfg["horizon_days"],
            "primaryTrendBias": "INSUFFICIENT_DATA",
            "mainConclusion": "MFE/MAE路径研究样本不足，暂不形成趋势概率结论。",
            "horizonAlignment": "INSUFFICIENT_DATA",
            "evidenceConflict": False,
            "keyDrivers": [],
            "riskFlags": missing_data[:4],
            "simulation_only": True,
            "is_real_trade": False,
        },
        "qiamAdjustmentPreview": {
            "direction": "NONE",
            "reason": reason,
            "maxStep": 1,
            "policy": "CONTROLLED_ONE_STEP_QIAM_CALIBRATION_PREVIEW",
            "canCreateTradeAction": False,
        },
        "config": cfg,
    }


def _regime_state(bottom_probability: Optional[float], breakdown_probability: Optional[float], threshold: float) -> str:
    if bottom_probability is None or breakdown_probability is None:
        return "SUPPORTING_ONLY"
    if breakdown_probability >= 0.60 and breakdown_probability >= bottom_probability:
        return "BREAKDOWN_RISK"
    if bottom_probability >= threshold and breakdown_probability <= 0.45:
        return "BOTTOM_REPAIR_ZONE"
    if bottom_probability >= threshold:
        return "BOTTOM_REPAIR_WATCH"
    return "NEUTRAL"


def _position_envelope(
    bottom_probability: Optional[float],
    breakdown_probability: Optional[float],
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    suggested = 0.0
    if bottom_probability is not None and breakdown_probability is not None:
        edge = max(0.0, bottom_probability - max(0.30, breakdown_probability))
        suggested = min(cfg["max_research_position_pct"], edge * cfg["max_research_position_pct"])
    return {
        "maxResearchPositionPct": cfg["max_research_position_pct"],
        "suggestedResearchPositionPct": round(suggested, 6),
        "policy": "REVIEW_ONLY_NOT_TRADE_INSTRUCTION",
        "constraints": [
            "Does not create BUY/ADD/SELL permission.",
            "DVG, Risk, QIAM, and Execution remain authoritative.",
            "Simulation-only evidence; human review required.",
        ],
        "simulation_only": True,
        "is_real_trade": False,
    }


def _build_horizon_forecast(
    rows: List[Dict[str, Any]],
    cfg: Dict[str, Any],
    horizon_days: int,
    latest_features: Dict[str, float],
    latest_trade_date: str,
) -> Dict[str, Any]:
    horizon_cfg = dict(cfg, horizon_days=horizon_days)
    records = build_feature_records(rows, horizon_cfg)
    if not records:
        empty_model = ModelResult(
            "SUPPORTING_ONLY",
            None,
            {},
            {
                "status": "SUPPORTING_ONLY",
                "reason": "feature_frame_empty",
                "sampleCount": 0,
                "walkForward": {"folds": [], "foldCount": 0, "brier": None, "prAuc": None},
            },
        )
        return _horizon_forecast_payload(
            horizon_days=horizon_days,
            latest_trade_date=latest_trade_date,
            bottom_model=empty_model,
            breakdown_model=empty_model,
            feature_records=[],
            cfg=horizon_cfg,
        )

    bottom_model = train_probability_model(
        records,
        latest_features,
        label_key="bottomLabel",
        prediction_key="bottomRepairProbability",
    )
    breakdown_model = train_probability_model(
        records,
        latest_features,
        label_key="breakdownLabel",
        prediction_key="breakdownRiskProbability",
    )
    return _horizon_forecast_payload(
        horizon_days=horizon_days,
        latest_trade_date=latest_trade_date,
        bottom_model=bottom_model,
        breakdown_model=breakdown_model,
        feature_records=records,
        cfg=horizon_cfg,
    )


def _horizon_forecast_payload(
    *,
    horizon_days: int,
    latest_trade_date: str,
    bottom_model: ModelResult,
    breakdown_model: ModelResult,
    feature_records: List[Dict[str, Any]],
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    bottom_probability = bottom_model.probability
    breakdown_probability = breakdown_model.probability
    threshold = cfg["repair_probability_threshold"]
    regime_state = _regime_state(bottom_probability, breakdown_probability, threshold)
    up, sideways, down = _trend_probabilities(bottom_probability, breakdown_probability)
    evidence_grade = _evidence_grade(bottom_model.diagnostics, breakdown_model.diagnostics)
    confidence = _forecast_confidence(bottom_model.diagnostics, breakdown_model.diagnostics, evidence_grade)
    return {
        "horizonDays": horizon_days,
        "status": "READY" if bottom_model.status == "READY" and breakdown_model.status == "READY" else "SUPPORTING_ONLY",
        "bottomRepairProbability": bottom_probability,
        "breakdownRiskProbability": breakdown_probability,
        "trendProbabilities": {
            "up": up,
            "sideways": sideways,
            "down": down,
        },
        "trendBias": _trend_bias(up, sideways, down),
        "confidence": confidence,
        "sampleCount": len(feature_records),
        "evidenceGrade": evidence_grade,
        "regimeState": regime_state,
        "currentPrediction": _current_prediction(
            trade_date=latest_trade_date,
            bottom_probability=bottom_probability,
            breakdown_probability=breakdown_probability,
            regime_state=regime_state,
            cfg=cfg,
        ),
        "modelDiagnostics": {
            "status": "READY" if bottom_model.status == "READY" and breakdown_model.status == "READY" else "SUPPORTING_ONLY",
            "bottomRepairModel": bottom_model.diagnostics,
            "breakdownRiskModel": breakdown_model.diagnostics,
            "walkForward": {
                "bottomRepair": bottom_model.diagnostics.get("walkForward", {}),
                "breakdownRisk": breakdown_model.diagnostics.get("walkForward", {}),
            },
        },
        "featureRecords": feature_records,
        "bottomModel": bottom_model,
        "breakdownModel": breakdown_model,
    }


def _primary_horizon_forecast(forecasts: List[Dict[str, Any]], primary_horizon: int) -> Dict[str, Any]:
    for forecast in forecasts:
        if forecast.get("horizonDays") == primary_horizon:
            return forecast
    return forecasts[0] if forecasts else {}


def _public_horizon_forecast(forecast: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: value
        for key, value in forecast.items()
        if key not in {"featureRecords", "bottomModel", "breakdownModel"}
    }


def _horizon_probability_series(horizon_forecasts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    paths: List[Dict[str, Any]] = []
    for forecast in horizon_forecasts:
        horizon_days = forecast.get("horizonDays")
        if not isinstance(horizon_days, int):
            continue
        records = forecast.get("featureRecords") if isinstance(forecast.get("featureRecords"), list) else []
        bottom_model = forecast.get("bottomModel")
        breakdown_model = forecast.get("breakdownModel")
        series: List[Dict[str, Any]] = []
        if isinstance(bottom_model, ModelResult) and isinstance(breakdown_model, ModelResult):
            series = [
                _public_probability_point(item)
                for item in _probability_series(records, bottom_model.predictions, breakdown_model.predictions)[-120:]
            ]
        prediction_point = _prediction_probability_point(forecast.get("currentPrediction"))
        if prediction_point and (not series or str(prediction_point["date"]) > str(series[-1].get("date") or "")):
            series.append(prediction_point)
        paths.append(
            {
                "horizonDays": horizon_days,
                "series": series,
            }
        )
    return paths


def _public_probability_point(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "date": item.get("tradeDate"),
        "repairProb": item.get("bottomRepairProbability"),
        "breakdownRisk": item.get("breakdownRiskProbability"),
        "bottomLabel": item.get("bottomLabel"),
        "breakdownLabel": item.get("breakdownLabel"),
        "regimeState": item.get("regimeState"),
        "labelWindowStart": item.get("labelWindowStart"),
        "labelWindowEnd": item.get("labelWindowEnd"),
    }


def _prediction_probability_point(current_prediction: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(current_prediction, dict):
        return None
    trade_date = str(current_prediction.get("tradeDate") or "").strip()
    repair = _number(current_prediction.get("bottomRepairProbability"))
    breakdown = _number(current_prediction.get("breakdownRiskProbability"))
    if not trade_date or (repair is None and breakdown is None):
        return None
    return {
        "date": trade_date,
        "repairProb": None,
        "breakdownRisk": None,
        "predictionRepairProb": round(repair, 6) if repair is not None else None,
        "predictionBreakdownRisk": round(breakdown, 6) if breakdown is not None else None,
        "regimeState": current_prediction.get("regimeState"),
        "labelStatus": current_prediction.get("labelStatus") or "UNLABELED_NOWCAST",
        "horizonDays": current_prediction.get("horizonDays"),
        "simulation_only": current_prediction.get("simulation_only", True),
        "is_real_trade": current_prediction.get("is_real_trade", False),
    }


def _trend_probabilities(
    bottom_probability: Optional[float],
    breakdown_probability: Optional[float],
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    if bottom_probability is None or breakdown_probability is None:
        return None, None, None
    up = 0.25 + bottom_probability * 0.55 - breakdown_probability * 0.25
    down = 0.20 + breakdown_probability * 0.65 - bottom_probability * 0.20
    sideways = 0.35 + max(0.0, 0.50 - abs(bottom_probability - breakdown_probability)) * 0.20
    values = [max(0.05, up), max(0.05, sideways), max(0.05, down)]
    total = sum(values)
    normalized = [round(value / total, 6) for value in values]
    drift = round(1.0 - sum(normalized), 6)
    normalized[1] = round(normalized[1] + drift, 6)
    return normalized[0], normalized[1], normalized[2]


def _trend_bias(
    up: Optional[float],
    sideways: Optional[float],
    down: Optional[float],
) -> str:
    if up is None or sideways is None or down is None:
        return "INSUFFICIENT_DATA"
    if up >= down + 0.10 and up >= sideways:
        return "UP"
    if down >= up + 0.10 and down >= sideways:
        return "DOWN"
    return "SIDEWAYS"


def _forecast_confidence(
    bottom: Dict[str, Any],
    breakdown: Dict[str, Any],
    evidence_grade: str,
) -> float:
    if bottom.get("status") != "READY" or breakdown.get("status") != "READY":
        return 0.25
    sample_count = min(int(bottom.get("sampleCount") or 0), int(breakdown.get("sampleCount") or 0))
    score = 0.45 + min(0.25, sample_count / 1000)
    if evidence_grade == "MEDIUM":
        score += 0.10
    for diagnostics in (bottom, breakdown):
        brier = (diagnostics.get("walkForward") or {}).get("brier")
        if _metric_ok(brier, 0.20):
            score += 0.05
        elif brier is not None and not _metric_ok(brier, 0.28):
            score -= 0.05
    return round(max(0.20, min(0.90, score)), 6)


def _trend_synthesis(horizon_forecasts: List[Dict[str, Any]], cfg: Dict[str, Any]) -> Dict[str, Any]:
    primary = _primary_horizon_forecast(horizon_forecasts, cfg["horizon_days"])
    ready_forecasts = [item for item in horizon_forecasts if item.get("status") == "READY"]
    biases = [str(item.get("trendBias") or "") for item in ready_forecasts if item.get("trendBias")]
    up_count = sum(1 for bias in biases if bias == "UP")
    down_count = sum(1 for bias in biases if bias == "DOWN")
    conflict = up_count > 0 and down_count > 0
    primary_bias = str(primary.get("trendBias") or "INSUFFICIENT_DATA")
    repair = _number(primary.get("bottomRepairProbability"))
    breakdown = _number(primary.get("breakdownRiskProbability"))
    threshold = cfg["repair_probability_threshold"]

    if not ready_forecasts:
        conclusion = "MFE/MAE路径研究样本不足，暂不形成趋势概率结论。"
    elif conflict:
        conclusion = "多周期趋势存在分歧，维持观察并等待技术面确认。"
    elif primary_bias == "UP" and repair is not None and repair >= threshold and (breakdown is None or breakdown < 0.35):
        conclusion = "MFE路径偏有利，但仍需 QIAM、技术面和风险门禁共同确认。"
    elif primary_bias == "DOWN" or (breakdown is not None and breakdown >= 0.50):
        conclusion = "MAE路径风险仍偏高，维持观察与风险复核。"
    else:
        conclusion = "未来趋势暂不明确，维持区间观察。"

    return {
        "primaryHorizonDays": cfg["horizon_days"],
        "primaryTrendBias": primary_bias,
        "mainConclusion": conclusion,
        "horizonAlignment": "CONFLICT" if conflict else ("ALIGNED" if len(set(biases)) == 1 and biases else "MIXED"),
        "evidenceConflict": conflict,
        "keyDrivers": _trend_key_drivers(primary, ready_forecasts, threshold),
        "riskFlags": _trend_risk_flags(primary, ready_forecasts),
        "simulation_only": True,
        "is_real_trade": False,
    }


def _trend_key_drivers(primary: Dict[str, Any], forecasts: List[Dict[str, Any]], threshold: float) -> List[str]:
    drivers: List[str] = []
    repair = _number(primary.get("bottomRepairProbability"))
    breakdown = _number(primary.get("breakdownRiskProbability"))
    if repair is not None:
        drivers.append(f"{primary.get('horizonDays', 20)}日MFE有利概率 {repair:.1%}")
        if repair >= threshold:
            drivers.append("主周期MFE有利概率超过研究阈值")
    if breakdown is not None:
        drivers.append(f"{primary.get('horizonDays', 20)}日MAE跌破风险 {breakdown:.1%}")
    aligned = [item for item in forecasts if item.get("trendBias") == primary.get("trendBias")]
    if len(aligned) >= 2:
        drivers.append(f"{len(aligned)} 个周期趋势方向一致")
    return drivers[:4]


def _trend_risk_flags(primary: Dict[str, Any], forecasts: List[Dict[str, Any]]) -> List[str]:
    flags: List[str] = []
    breakdown = _number(primary.get("breakdownRiskProbability"))
    if breakdown is not None and breakdown >= 0.50:
        flags.append("主周期MAE跌破风险偏高")
    if any(item.get("status") != "READY" for item in forecasts):
        flags.append("部分周期样本或正负样本不足")
    biases = {str(item.get("trendBias") or "") for item in forecasts if item.get("trendBias")}
    if "UP" in biases and "DOWN" in biases:
        flags.append("短中长周期趋势冲突")
    if not flags:
        flags.append("仍需技术面、QIAM 和 DVG 门禁确认")
    return flags[:4]


def _qiam_adjustment_preview(
    primary: Dict[str, Any],
    synthesis: Dict[str, Any],
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    repair = _number(primary.get("bottomRepairProbability"))
    breakdown = _number(primary.get("breakdownRiskProbability"))
    direction = "NONE"
    reason = "no_bottom_research_edge"
    if breakdown is not None and breakdown >= 0.50:
        direction = "DOWN"
        reason = "breakdown_risk_high"
    elif repair is not None and repair >= cfg["repair_probability_threshold"] and (breakdown is None or breakdown < 0.35):
        direction = "UP"
        reason = "repair_probability_dominant"
    elif synthesis.get("evidenceConflict"):
        direction = "CONFLICT"
        reason = "multi_horizon_conflict"
    return {
        "direction": direction,
        "reason": reason,
        "maxStep": 1,
        "policy": "CONTROLLED_ONE_STEP_QIAM_CALIBRATION_PREVIEW",
        "canCreateTradeAction": False,
    }


def _probability_series(
    records: List[Dict[str, Any]],
    bottom_predictions: Dict[str, float],
    breakdown_predictions: Dict[str, float],
) -> List[Dict[str, Any]]:
    series: List[Dict[str, Any]] = []
    for record in records:
        trade_date = record["tradeDate"]
        bottom = bottom_predictions.get(trade_date)
        breakdown = breakdown_predictions.get(trade_date)
        series.append(
            {
                "tradeDate": trade_date,
                "bottomRepairProbability": round(bottom, 6) if bottom is not None else None,
                "breakdownRiskProbability": round(breakdown, 6) if breakdown is not None else None,
                "bottomLabel": record.get("bottomLabel"),
                "breakdownLabel": record.get("breakdownLabel"),
                "regimeState": _regime_state(bottom, breakdown, 0.60),
                "labelWindowStart": record.get("labelWindowStart"),
                "labelWindowEnd": record.get("labelWindowEnd"),
            }
        )
    return series


def _current_prediction(
    *,
    trade_date: str,
    bottom_probability: Optional[float],
    breakdown_probability: Optional[float],
    regime_state: str,
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "tradeDate": trade_date,
        "bottomRepairProbability": round(bottom_probability, 6) if bottom_probability is not None else None,
        "breakdownRiskProbability": round(breakdown_probability, 6) if breakdown_probability is not None else None,
        "regimeState": regime_state,
        "labelStatus": "UNLABELED_NOWCAST",
        "horizonDays": cfg["horizon_days"],
        "simulation_only": True,
        "is_real_trade": False,
    }


def _evidence_grade(bottom: Dict[str, Any], breakdown: Dict[str, Any]) -> str:
    if bottom.get("status") != "READY" or breakdown.get("status") != "READY":
        return "LOW"
    sample_count = min(int(bottom.get("sampleCount") or 0), int(breakdown.get("sampleCount") or 0))
    bottom_brier = ((bottom.get("walkForward") or {}).get("brier"))
    breakdown_brier = ((breakdown.get("walkForward") or {}).get("brier"))
    if sample_count >= 220 and _metric_ok(bottom_brier, 0.24) and _metric_ok(breakdown_brier, 0.24):
        return "MEDIUM"
    return "LOW"


def _auxiliary_summary(auxiliary_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(auxiliary_data, dict):
        return {"available": False, "keys": []}
    return {
        "available": bool(auxiliary_data),
        "keys": sorted(str(key) for key in auxiliary_data.keys())[:20],
    }


def _walk_forward_summary(folds: List[Dict[str, Any]]) -> Dict[str, Any]:
    briers = [float(item["brier"]) for item in folds if item.get("brier") is not None]
    pr_aucs = [float(item["prAuc"]) for item in folds if item.get("prAuc") is not None]
    return {
        "folds": folds,
        "foldCount": len(folds),
        "brier": round(mean(briers), 6) if briers else None,
        "prAuc": round(mean(pr_aucs), 6) if pr_aucs else None,
    }


def _feature_row(features: Dict[str, float]) -> List[float]:
    return [_finite_float(features.get(name), 0.0) for name in FEATURE_NAMES]


def _standardization(rows: List[List[float]]) -> Tuple[List[float], List[float]]:
    columns = list(zip(*rows))
    means = [mean(col) if col else 0.0 for col in columns]
    scales = [pstdev(col) or 1.0 for col in columns]
    return means, scales


def _scale_row(row: List[float], means: List[float], scales: List[float]) -> List[float]:
    return [
        (float(value) - means[index]) / (scales[index] or 1.0)
        for index, value in enumerate(row)
    ]


def _fit_logistic(rows: List[List[float]], labels: List[int]) -> Tuple[List[float], float]:
    if not rows:
        return [], 0.0
    weights = [0.0 for _ in rows[0]]
    bias = 0.0
    positive_count = sum(labels) or 1
    negative_count = len(labels) - sum(labels) or 1
    lr = 0.05
    for _ in range(800):
        grad_w = [0.0 for _ in weights]
        grad_b = 0.0
        for row, label in zip(rows, labels):
            pred = _predict_logistic(row, weights, bias)
            class_weight = len(labels) / (2 * positive_count) if label == 1 else len(labels) / (2 * negative_count)
            error = (pred - label) * class_weight
            for index, value in enumerate(row):
                grad_w[index] += error * value
            grad_b += error
        denom = max(1, len(rows))
        weights = [weight - lr * (grad / denom + 0.001 * weight) for weight, grad in zip(weights, grad_w)]
        bias -= lr * grad_b / denom
    return weights, bias


def _predict_logistic(row: List[float], weights: List[float], bias: float) -> float:
    score = bias + sum(weight * value for weight, value in zip(weights, row))
    if score >= 0:
        z = math.exp(-score)
        return 1.0 / (1.0 + z)
    z = math.exp(score)
    return z / (1.0 + z)


def _brier(labels: List[int], probs: List[float]) -> float:
    return mean([(float(prob) - int(label)) ** 2 for label, prob in zip(labels, probs)]) if labels else 0.0


def _average_precision(labels: List[int], probs: List[float]) -> float:
    ordered = sorted(zip(probs, labels), key=lambda item: item[0], reverse=True)
    positives = sum(labels)
    if positives <= 0:
        return 0.0
    hits = 0
    precision_sum = 0.0
    for index, (_, label) in enumerate(ordered, start=1):
        if label:
            hits += 1
            precision_sum += hits / index
    return precision_sum / positives


def _return_series(closes: List[float]) -> List[float]:
    values: List[float] = []
    for index in range(1, len(closes)):
        values.append(_safe_ratio(closes[index] - closes[index - 1], closes[index - 1]) or 0.0)
    return values


def _window_return(closes: List[float], window: int) -> float:
    if len(closes) <= window:
        return 0.0
    return _safe_ratio(closes[-1] - closes[-window - 1], closes[-window - 1]) or 0.0


def _zscore(values: List[float], current: float) -> float:
    clean = [float(value) for value in values if value is not None]
    if len(clean) < 3:
        return 0.0
    sigma = pstdev(clean)
    if sigma <= 1e-12:
        return 0.0
    return (float(current) - mean(clean)) / sigma


def _std(values: Iterable[float]) -> float:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    if len(clean) < 2:
        return 0.0
    return pstdev(clean)


def _round_matrix(matrix: Sequence[Sequence[float]]) -> List[List[float]]:
    return [[round(_finite_float(value, 0.0), 8) for value in row] for row in matrix]


def _fallback_shrink_covariance(matrix: Sequence[Sequence[float]], alpha: float) -> List[List[float]]:
    rows = [[float(value) for value in row] for row in matrix]
    dimension = len(rows[0]) if rows else 1
    if len(rows) < 2:
        return [[1e-4 if row == col else 0.0 for col in range(dimension)] for row in range(dimension)]
    columns = list(zip(*rows))
    means = [mean(col) for col in columns]
    cov = [[0.0 for _ in range(dimension)] for _ in range(dimension)]
    for row in rows:
        for i in range(dimension):
            for j in range(dimension):
                cov[i][j] += (row[i] - means[i]) * (row[j] - means[j]) / (len(rows) - 1)
    for i in range(dimension):
        for j in range(dimension):
            if i != j:
                cov[i][j] *= 1.0 - alpha
            if i == j:
                cov[i][j] += 1e-6
    return cov


def _frobenius_distance(matrix_a: Sequence[Sequence[float]], matrix_b: Sequence[Sequence[float]]) -> float:
    total = 0.0
    for row_a, row_b in zip(matrix_a, matrix_b):
        for value_a, value_b in zip(row_a, row_b):
            total += (float(value_a) - float(value_b)) ** 2
    return math.sqrt(total)


def _spd_array(matrix: Sequence[Sequence[float]]) -> Any:
    np = _numpy()
    arr = np.asarray(matrix, dtype=float)
    if arr.ndim != 2 or arr.shape[0] != arr.shape[1]:
        size = max(arr.shape) if arr.size else 1
        arr = np.eye(size) * 1e-4
    return (arr + arr.T) / 2.0 + np.eye(arr.shape[0]) * 1e-8


def _matrix_log_spd(matrix: Any) -> Any:
    np = _numpy()
    eigvals, eigvecs = np.linalg.eigh(matrix)
    eigvals = np.maximum(eigvals, 1e-8)
    return eigvecs @ np.diag(np.log(eigvals)) @ eigvecs.T


def _numpy() -> Any:
    try:
        import numpy as np

        return np
    except (ImportError, OSError, ValueError, RuntimeError) as exc:
        logger.warning("numpy not available — skipping numeric fallback (%s: %s)", type(exc).__name__, exc)
        return None


def _metric_ok(value: Any, max_value: float) -> bool:
    number = _number(value)
    return number is not None and number <= max_value


def _safe_ratio(numerator: float, denominator: float) -> Optional[float]:
    if denominator in (0, None):
        return None
    try:
        return float(numerator) / float(denominator)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _number(value: Any) -> Optional[float]:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        parsed = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _finite_float(value: Any, fallback: float) -> float:
    number = _number(value)
    return fallback if number is None else float(number)


def _int_between(value: Any, low: int, high: int, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = fallback
    return max(low, min(high, parsed))


def _float_between(value: Any, low: float, high: float, fallback: float) -> float:
    number = _number(value)
    parsed = fallback if number is None else number
    return max(low, min(high, parsed))


def _date_text(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text[:10]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
