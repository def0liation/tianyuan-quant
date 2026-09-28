from __future__ import annotations
from typing import Any, Dict

from .base_agent import BaseAgent, AgentResult


class ScenarioEngineAgent(BaseAgent):
    node = "scenario_engine"
    name = "Scenario Engine"
    stage = "analysis"
    rule_engine_only = True

    def process(self, run_context: Dict[str, Any], prior_outputs: Dict[str, Any]) -> AgentResult:
        dvg_output = _prior_output(prior_outputs, "dvg_gate", "dvg_evidence_gate")
        dvg_data = {**(run_context.get("dvg", {}) or {}), **_payload_data(dvg_output)}
        fused_output = _prior_output(prior_outputs, "market_technical_analyst")
        fused_data = _payload_data(fused_output)
        fused_technical = fused_data.get("technicalKline") if isinstance(fused_data.get("technicalKline"), dict) else {}
        technical_output = _prior_output(prior_outputs, "technical_kline_analyst")
        technical_data = {**_payload_data(technical_output), **fused_technical, **(run_context.get("technicalKline", {}) or {})}
        technical_invalidations = _technical_invalidations(technical_data)

        scenario_perm = dvg_data.get("scenarioPermission", "ALLOW_WITH_DISCOUNT")
        missing = dvg_data.get("criticalMissingData", [])
        missing_note = "、".join(missing[:3]) if missing else "当前已接入数据"

        bullish_premise = f"缺失项补齐后再复核：{missing_note}"
        base_premise = "维持当前已验证数据状态，不新增买入结论"
        bearish_premise = f"关键数据继续缺失或新增风险：{missing_note}"

        if technical_invalidations:
            bearish_premise = f"{bearish_premise}; technical invalidation: {technical_invalidations[0]['label']}"

        reasons = [
            f"乐观情景前提: {bullish_premise}",
            f"基准情景前提: {base_premise}",
            f"悲观情景前提: {bearish_premise}",
            "情景分析为定性参考框架，不作为交易决策的直接依据",
        ]

        warnings = []
        if technical_invalidations:
            warnings.append("Technical Kline invalidation scenarios are active; Scenario Engine cannot upgrade buy intent.")
        if scenario_perm != "ALLOW":
            warnings.append(f"Scenario Engine 权限限制为 {scenario_perm}")
            reasons.append(f"DVG 限制 Scenario 权限为 {scenario_perm}")

        data = {
            "bullish": {"premise": bullish_premise, "probability": "qualitative"},
            "base": {"premise": base_premise, "probability": "qualitative"},
            "bearish": {"premise": bearish_premise, "probability": "qualitative"},
            "dvgPermission": scenario_perm,
            "technicalInvalidationScenarios": technical_invalidations,
        }

        return AgentResult(
            node=self.node,
            status="PASS" if scenario_perm == "ALLOW" else "WARN",
            confidence="MEDIUM",
            reasons=reasons,
            warnings=warnings,
            data=data,
            audit_id=self._audit(),
        )


def _technical_invalidations(technical: Dict[str, Any]) -> list[Dict[str, Any]]:
    if not isinstance(technical, dict) or not technical:
        return []
    trend = technical.get("trend") if isinstance(technical.get("trend"), dict) else {}
    support = technical.get("supportResistance") if isinstance(technical.get("supportResistance"), dict) else {}
    volume = technical.get("volumePrice") if isinstance(technical.get("volumePrice"), dict) else {}
    multi_period = technical.get("multiPeriod") if isinstance(technical.get("multiPeriod"), dict) else {}
    bias = str(technical.get("technicalBias") or "").upper()
    close = _number(trend.get("close"))
    ma20 = _number(trend.get("ma20"))
    support20 = _number(support.get("support20d"))
    return20d = _number(trend.get("return20d")) or 0.0
    volume_ratio = _number(volume.get("volumeRatio5v20"))

    scenarios: list[Dict[str, Any]] = []
    if bias == "BEARISH" or (close is not None and ma20 is not None and close < ma20) or (
        close is not None and support20 is not None and close < support20
    ):
        scenarios.append(
            {
                "code": "BREAK_MA20_OR_20D_SUPPORT",
                "label": "Break below MA20 or 20-day support",
                "source": "technical_kline_analyst",
            }
        )
    if volume_ratio is not None and volume_ratio >= 1.25 and return20d < 0:
        scenarios.append(
            {
                "code": "HIGH_VOLUME_DECLINE",
                "label": "High-volume decline",
                "source": "technical_kline_analyst",
            }
        )
    if str(multi_period.get("alignment") or "").upper() == "MIXED":
        scenarios.append(
            {
                "code": "WEEKLY_MONTHLY_DIVERGENCE",
                "label": "Weekly/monthly cycle divergence",
                "source": "technical_kline_analyst",
            }
        )
    return scenarios


def _prior_output(prior_outputs: Dict[str, Any], *keys: str) -> Dict[str, Any]:
    for key in keys:
        value = prior_outputs.get(key)
        if isinstance(value, dict) and value:
            return value
    return {}


def _payload_data(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().replace(",", "").rstrip("%"))
        except ValueError:
            return None
    return None
