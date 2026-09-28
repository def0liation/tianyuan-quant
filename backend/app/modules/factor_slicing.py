from __future__ import annotations
from typing import Any, Dict

from ..core.quant_engine_modes import HIGH_FREQ_SHORT, LOW_FREQ_MID_LONG, quant_engine_profile_from_run
from .base_agent import BaseAgent, AgentResult


class FactorSlicingAgent(BaseAgent):
    node = "factor_slicing"
    name = "Factor Slicing"
    stage = "analysis"
    rule_engine_only = True

    def process(self, run_context: Dict[str, Any], prior_outputs: Dict[str, Any]) -> AgentResult:
        mode = "AUTO"
        quant_profile = quant_engine_profile_from_run(run_context)
        market_data = run_context.get("marketData") or {}
        quote = market_data.get("quote") or {}
        auxiliary = run_context.get("auxiliaryData") or {}
        factors, missing_factor_data = _derive_factors(quote, market_data, auxiliary, quant_profile)
        stability = round(sum(f.get("confidence", 0.0) for f in factors) / max(1, len(factors)), 4)
        fused_output = prior_outputs.get("market_technical_analyst", {})
        fused_data = _payload_data(fused_output)
        fused_market = fused_data.get("market") if isinstance(fused_data.get("market"), dict) else {}
        market_output = prior_outputs.get("market_regime", {})
        market_data_output = market_output.get("data", {}) if isinstance(market_output, dict) else {}
        market_data_output = {**market_data_output, **fused_market}
        regime = market_data_output.get("regimeClassification") or (run_context.get("market") or {}).get("regimeClassification") or "UNKNOWN"

        reasons = []
        for f in factors:
            reasons.append(f"{f['name']}因子: 权重 {f['weight']:.2f}, 贡献度 {f['contribution']:.2f}")

        reasons.append(f"因子稳定性: {stability:.2f} ({'稳定' if stability >= 0.7 else '波动'})")

        warnings = []
        if missing_factor_data:
            warnings.append(f"缺失因子数据: {', '.join(missing_factor_data)}")
        if stability < 0.7:
            warnings.append(f"因子稳定性偏低 ({stability:.2f})，因子暴露可能变化")

        source_info = _factor_source_info(auxiliary)
        data = {
            "mode": mode,
            "factors": [{"name": f["name"], "weight": f["weight"], "contribution": f["contribution"], "confidence": f.get("confidence", 0.7)} for f in factors],
            "factorClusters": _factor_clusters(factors),
            "regimeClassification": regime,
            "factorStability": stability,
            "missingFactorData": missing_factor_data,
            "factorDataSource": "RULE_DERIVED",
            "provenance": {
                "sourceType": "DERIVED",
                "note": "由当前行情、资金流/财务辅助数据推算；缺失项不会回填模板 Value/Momentum/Liquidity 数值",
            },
        }
        data["factorDataSource"] = source_info["factorDataSource"]
        data["quantEngineMode"] = quant_profile["mode"]
        data["parameterProfile"] = quant_profile["parameterProfile"]
        data["provenance"] = {
            **data.get("provenance", {}),
            **source_info["provenance"],
            "note": source_info["note"],
            "quantEngineMode": quant_profile["mode"],
        }

        return AgentResult(
            node=self.node,
            status="PASS" if stability >= 0.7 else "WARN",
            confidence="HIGH" if stability >= 0.7 else "MEDIUM",
            reasons=reasons,
            missing_data=missing_factor_data if stability < 0.7 else [],
            warnings=warnings,
            data=data,
            audit_id=self._audit(),
        )


def _derive_factors(
    quote: Dict[str, Any],
    market_data: Dict[str, Any],
    auxiliary: Dict[str, Any],
    quant_profile: Dict[str, Any] | None = None,
) -> tuple[list[Dict[str, float | str]], list[str]]:
    missing: list[str] = []
    profile = quant_profile or {}
    quant_mode = profile.get("mode") or HIGH_FREQ_SHORT
    weights = (profile.get("parameterProfile") or {}).get("factorWeights") or {}
    quote_ready = market_data.get("status") == "READY" and str(market_data.get("provider") or "") != "mock"
    change_percent = _number(quote.get("changePercent") or market_data.get("changePercent"))
    volume = _number(quote.get("volume") or market_data.get("volume"))
    amount = _number(quote.get("amount") or (market_data.get("extra") or {}).get("amount"))

    fundamentals_ready = _aux_ready(auxiliary, "fundamentals")
    moneyflow_ready = _aux_ready(auxiliary, "moneyflow")
    stock_factor_records = _aux_records(auxiliary, "special_data")
    stock_factor = _latest_factor_record(stock_factor_records) if _aux_ready(auxiliary, "special_data") else {}

    if stock_factor:
        factors: list[Dict[str, float | str]] = []
        if fundamentals_ready:
            factors.append(
                {
                    "name": "Value",
                    "weight": _weight(weights, "Value", 0.25),
                    "contribution": _value_contribution(auxiliary),
                    "confidence": 0.72 if quant_mode == LOW_FREQ_MID_LONG else 0.68,
                }
            )
            if quant_mode == LOW_FREQ_MID_LONG:
                factors.append(
                    {
                        "name": "Quality",
                        "weight": _weight(weights, "Quality", 0.25),
                        "contribution": _quality_contribution(auxiliary),
                        "confidence": 0.74,
                    }
                )
        elif quant_mode == LOW_FREQ_MID_LONG:
            missing.append("估值/财务因子")
            missing.append("质量/基本面因子")
        factors.extend(
            [
                {
                    "name": "Momentum",
                    "weight": _weight(weights, "Momentum", 0.35),
                    "contribution": _stock_factor_momentum_contribution(stock_factor, change_percent),
                    "confidence": 0.78 if quant_mode == LOW_FREQ_MID_LONG else 0.86,
                },
                {
                    "name": "Volatility",
                    "weight": _weight(weights, "Volatility", 0.15),
                    "contribution": _stock_factor_volatility_contribution(stock_factor),
                    "confidence": 0.72 if quant_mode == LOW_FREQ_MID_LONG else 0.78,
                },
            ]
        )
        if quant_mode == HIGH_FREQ_SHORT:
            factors.insert(
                -1,
                {
                    "name": "Liquidity",
                    "weight": _weight(weights, "Liquidity", 0.25),
                    "contribution": _stock_factor_liquidity_contribution(stock_factor, volume, amount),
                    "confidence": 0.82,
                },
            )
    if stock_factor:
        return factors, missing

    value_confidence = 0.65 if fundamentals_ready else 0.0
    value_contribution = _value_contribution(auxiliary) if fundamentals_ready else 0.0
    if not fundamentals_ready:
        missing.append("估值/财务因子")

    momentum_confidence = 0.72 if quote_ready and change_percent is not None else 0.0
    momentum_contribution = round(max(-0.12, min(0.12, (change_percent or 0.0) / 10)), 4)
    if not quote_ready or change_percent is None:
        missing.append("动量因子行情输入")

    liquidity_confidence = 0.70 if quote_ready and (volume is not None or amount is not None) else (0.55 if moneyflow_ready else 0.0)
    liquidity_contribution = _liquidity_contribution(volume, amount)
    if liquidity_confidence == 0:
        missing.append("换手率/成交额/资金流")

    volatility_confidence = 0.62 if quote_ready and change_percent is not None else 0.0
    volatility_contribution = round(max(-0.08, min(0.08, -abs(change_percent or 0.0) / 120)), 4)
    if volatility_confidence == 0:
        missing.append("波动率因子行情输入")

    factors = [
        {"name": "Value", "weight": _weight(weights, "Value", 0.30), "contribution": value_contribution, "confidence": value_confidence},
    ]
    if quant_mode == LOW_FREQ_MID_LONG:
        quality_confidence = 0.70 if fundamentals_ready else 0.0
        quality_contribution = _quality_contribution(auxiliary) if fundamentals_ready else 0.0
        if not fundamentals_ready:
            missing.append("质量/基本面因子")
        factors.append(
            {
                "name": "Quality",
                "weight": _weight(weights, "Quality", 0.25),
                "contribution": quality_contribution,
                "confidence": quality_confidence,
            }
        )
    factors.extend(
        [
            {"name": "Momentum", "weight": _weight(weights, "Momentum", 0.35), "contribution": momentum_contribution, "confidence": momentum_confidence},
            {"name": "Volatility", "weight": _weight(weights, "Volatility", 0.15), "contribution": volatility_contribution, "confidence": volatility_confidence},
        ]
    )
    if quant_mode == HIGH_FREQ_SHORT:
        factors.insert(
            2,
            {"name": "Liquidity", "weight": _weight(weights, "Liquidity", 0.25), "contribution": liquidity_contribution, "confidence": liquidity_confidence},
        )
    return factors, list(dict.fromkeys(missing))


def _payload_data(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def _weight(weights: Dict[str, Any], key: str, fallback: float) -> float:
    value = weights.get(key)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return fallback


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().rstrip("%"))
        except ValueError:
            return None
    return None


def _aux_ready(auxiliary: Dict[str, Any], key: str) -> bool:
    item = auxiliary.get(key) if isinstance(auxiliary, dict) else None
    return isinstance(item, dict) and item.get("status") == "READY" and not item.get("error")


def _aux_records(auxiliary: Dict[str, Any], key: str) -> list[Dict[str, Any]]:
    item = auxiliary.get(key) if isinstance(auxiliary, dict) else None
    if not isinstance(item, dict) or item.get("status") != "READY":
        return []
    records = item.get("records")
    if isinstance(records, list):
        return [record for record in records if isinstance(record, dict)]
    sample = item.get("sample")
    return [sample] if isinstance(sample, dict) else []


def _factor_source_info(auxiliary: Dict[str, Any]) -> Dict[str, Any]:
    records = _aux_records(auxiliary, "special_data")
    latest = _latest_factor_record(records)
    if _aux_ready(auxiliary, "special_data") and latest:
        source = auxiliary.get("special_data") or {}
        return {
            "factorDataSource": "TUSHARE_STK_FACTOR",
            "provenance": {
                "sourceType": "LIVE",
                "provider": source.get("provider", "tushare"),
                "apiName": source.get("api_name", "stk_factor"),
                "recordCount": source.get("record_count", len(records)),
                "tradeDate": latest.get("trade_date") or latest.get("tradeDate"),
            },
            "note": "Tushare stk_factor supplied the Quant Engine factor inputs for this run.",
        }
    return {
        "factorDataSource": "RULE_DERIVED",
        "provenance": {"sourceType": "DERIVED"},
        "note": "由当前行情、资金流和财务辅助数据推算；缺失项不会回填模板 Value/Momentum/Liquidity 数值。",
    }


def _latest_factor_record(records: list[Dict[str, Any]]) -> Dict[str, Any]:
    if not records:
        return {}
    return max(records, key=lambda record: str(record.get("trade_date") or record.get("tradeDate") or ""))


def _value_contribution(auxiliary: Dict[str, Any]) -> float:
    record = next(iter(_aux_records(auxiliary, "fundamentals")), {})
    for key in ("roe", "roe_dt", "grossprofit_margin", "profit_yoy", "basic_eps"):
        value = _number(record.get(key))
        if value is not None:
            return round(max(-0.12, min(0.12, value / 100)), 4)
    return 0.03


def _quality_contribution(auxiliary: Dict[str, Any]) -> float:
    record = next(iter(_aux_records(auxiliary, "fundamentals")), {})
    score = 0.0
    hits = 0
    for key in ("grossprofit_margin", "roe", "roe_dt", "profit_yoy"):
        value = _number(record.get(key))
        if value is not None:
            score += max(-0.08, min(0.08, value / 150))
            hits += 1
    if hits:
        return round(score / hits, 4)
    return _value_contribution(auxiliary)


def _liquidity_contribution(volume: float | None, amount: float | None) -> float:
    import math

    base = amount if amount and amount > 0 else volume
    if not base:
        return 0.0
    return round(max(0.0, min(0.12, (math.log10(base + 1) - 5) / 50)), 4)


def _stock_factor_momentum_contribution(record: Dict[str, Any], fallback_change: float | None) -> float:
    pct = _first_number(record, "pct_chg", "pct_change", "change_percent")
    if pct is None:
        pct = fallback_change
    if pct is not None:
        return round(max(-0.12, min(0.12, pct / 10)), 4)

    rsi = _first_number(record, "rsi_6", "rsi", "rsi_qfq_6")
    macd = _first_number(record, "macd", "macd_dif", "macd_qfq")
    score = 0.0
    if rsi is not None:
        score += (rsi - 50) / 500
    if macd is not None:
        score += max(-0.05, min(0.05, macd / 10))
    return round(max(-0.12, min(0.12, score)), 4)


def _stock_factor_liquidity_contribution(
    record: Dict[str, Any],
    fallback_volume: float | None,
    fallback_amount: float | None,
) -> float:
    turnover = _first_number(record, "turnover_rate", "turnover_rate_f", "turnover")
    if turnover is not None:
        return round(max(0.0, min(0.12, turnover / 100)), 4)
    amount = _first_number(record, "amount", "vol") or fallback_amount
    volume = _first_number(record, "volume") or fallback_volume
    return _liquidity_contribution(volume, amount)


def _stock_factor_volatility_contribution(record: Dict[str, Any]) -> float:
    upper = _first_number(record, "boll_upper", "boll_upper_qfq")
    lower = _first_number(record, "boll_lower", "boll_lower_qfq")
    mid = _first_number(record, "boll_mid", "boll_mid_qfq")
    if upper is not None and lower is not None and mid and mid > 0:
        width = max(0.0, (upper - lower) / mid)
        return round(max(-0.08, min(0.08, (0.18 - width) / 2)), 4)
    cci = _first_number(record, "cci", "cci_qfq")
    if cci is not None:
        return round(max(-0.08, min(0.08, -abs(cci) / 2000)), 4)
    return 0.0


def _first_number(record: Dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _number(record.get(key))
        if value is not None:
            return value
    return None


def _factor_clusters(factors: list[Dict[str, Any]]) -> list[str]:
    clusters = []
    if any(f.get("name") == "Value" and f.get("confidence", 0) > 0 for f in factors):
        clusters.append("基本面")
    if any(f.get("name") == "Momentum" and f.get("confidence", 0) > 0 for f in factors):
        clusters.append("动量")
    if any(f.get("name") == "Liquidity" and f.get("confidence", 0) > 0 for f in factors):
        clusters.append("流动性")
    if any(f.get("name") == "Volatility" and f.get("confidence", 0) > 0 for f in factors):
        clusters.append("波动率")
    if any(f.get("name") == "Quality" and f.get("confidence", 0) > 0 for f in factors):
        clusters.append("质量")
    return clusters or ["缺失"]
