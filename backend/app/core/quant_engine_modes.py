from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict


HIGH_FREQ_SHORT = "HIGH_FREQ_SHORT"
LOW_FREQ_MID_LONG = "LOW_FREQ_MID_LONG"


HIGH_FREQ_MISSING_MARKERS = (
    "Level-2",
    "Level2",
    "L2",
    "二级行情",
    "盘口深度",
    "分时",
    "逐笔",
    "资金流分解",
)


_PROFILES: Dict[str, Dict[str, Any]] = {
    HIGH_FREQ_SHORT: {
        "mode": HIGH_FREQ_SHORT,
        "label": "高频短线",
        "horizon": "短线 / 盘中到数日",
        "parameterProfile": {
            "factorWeights": {
                "Momentum": 0.40,
                "Liquidity": 0.30,
                "Volatility": 0.20,
                "Value": 0.10,
            },
            "requiredFactorNames": ["Momentum", "Liquidity", "Volatility"],
            "discountsHighFrequencyMissingData": True,
            "highFrequencyMissingMarkers": list(HIGH_FREQ_MISSING_MARKERS),
        },
        "ignoredMissingData": [],
    },
    LOW_FREQ_MID_LONG: {
        "mode": LOW_FREQ_MID_LONG,
        "label": "低频中长线",
        "horizon": "中长线 / 数周到数月",
        "parameterProfile": {
            "factorWeights": {
                "Value": 0.35,
                "Quality": 0.25,
                "Momentum": 0.25,
                "Volatility": 0.15,
            },
            "requiredFactorNames": ["Value", "Quality", "Momentum"],
            "discountsHighFrequencyMissingData": False,
            "highFrequencyMissingMarkers": list(HIGH_FREQ_MISSING_MARKERS),
        },
        "ignoredMissingData": [],
    },
}


def infer_quant_engine_mode(task_type: str | None) -> str:
    text = str(task_type or "").lower()
    if any(marker in text for marker in ("交易机会", "短线", "高频", "机会发现")):
        return HIGH_FREQ_SHORT
    if any(marker in text for marker in ("持仓", "风险", "中长线", "低频")):
        return LOW_FREQ_MID_LONG
    return HIGH_FREQ_SHORT


def normalize_quant_engine_mode(value: Any, task_type: str | None = None) -> str:
    mode = str(value or "").upper()
    if mode in _PROFILES:
        return mode
    return infer_quant_engine_mode(task_type)


def quant_engine_profile(mode: Any, task_type: str | None = None) -> Dict[str, Any]:
    normalized = normalize_quant_engine_mode(mode, task_type)
    return deepcopy(_PROFILES[normalized])


def quant_engine_profile_from_run(run_context: Dict[str, Any]) -> Dict[str, Any]:
    quant_engine = run_context.get("quantEngine")
    mode = quant_engine.get("mode") if isinstance(quant_engine, dict) else None
    return quant_engine_profile(mode, run_context.get("taskType"))


def is_high_frequency_missing_item(item: Any) -> bool:
    text = str(item)
    return any(marker in text for marker in HIGH_FREQ_MISSING_MARKERS)


def split_missing_data_for_mode(
    missing_data: list[Any],
    mode: Any,
    task_type: str | None = None,
) -> tuple[list[Any], list[Any]]:
    profile = quant_engine_profile(mode, task_type)
    if profile["mode"] != LOW_FREQ_MID_LONG:
        return list(missing_data), []

    applicable: list[Any] = []
    ignored: list[Any] = []
    for item in missing_data:
        if is_high_frequency_missing_item(item):
            ignored.append(item)
        else:
            applicable.append(item)
    return applicable, ignored
