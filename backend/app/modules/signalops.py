from __future__ import annotations
from typing import Any, Dict

from .base_agent import BaseAgent, AgentResult


class SignalopsAgent(BaseAgent):
    node = "signalops"
    name = "SignalOps"
    stage = "ops"
    rule_engine_only = True

    def process(self, run_context: Dict[str, Any], prior_outputs: Dict[str, Any]) -> AgentResult:
        signal = run_context.get("signalOps", {})
        dvg_output = _prior_output(prior_outputs, "dvg_gate", "dvg_evidence_gate")
        risk_output = prior_outputs.get("risk_firewall", {})
        qiam_output = _prior_output(prior_outputs, "quant_engine", "qiam")
        atrade_output = _prior_output(prior_outputs, "trade_micro", "atrade")
        fused_output = _prior_output(prior_outputs, "market_technical_analyst")
        fused_data = _payload_data(fused_output)
        fused_technical = fused_data.get("technicalKline") if isinstance(fused_data.get("technicalKline"), dict) else {}
        technical_output = _prior_output(prior_outputs, "technical_kline_analyst")

        dvg_data = {**(run_context.get("dvg", {}) or {}), **_payload_data(dvg_output)}
        qiam_data = {**(run_context.get("qiam", {}) or {}), **_payload_data(qiam_output)}
        atrade_data = {**(run_context.get("atrade", {}) or {}), **_payload_data(atrade_output)}
        technical_data = {**_payload_data(technical_output), **fused_technical, **(run_context.get("technicalKline", {}) or {})}
        technical_conditions = _technical_conditions(technical_data)

        risk_passed = not (risk_output.get("hard_stop", False) if isinstance(risk_output, dict) else False)
        dvg_passed = dvg_data.get("allowedOutputLevel", "FULL") != "BLOCK_BUY"
        qiam_passed = qiam_data.get("finalBuySuitability", "NEUTRAL") != "BLOCK_BUY"
        exec_reachable = atrade_data.get("executionReachability", "CONDITIONALLY_REACHABLE") == "REACHABLE"
        technical_passed = not technical_conditions["blocking"]

        reasons = []
        blocked = []
        warnings = []
        trigger_conditions = signal.get("triggerConditions") or [
            "AI will evaluate trigger conditions during automatic paper trading."
        ]
        invalidation_conditions = signal.get("invalidationConditions") or [
            "AI will evaluate invalidation conditions during automatic paper trading."
        ]
        trigger_conditions = list(trigger_conditions) + technical_conditions["observation"]
        invalidation_conditions = list(invalidation_conditions) + technical_conditions["invalidation"]
        blocked_reason = ""

        if risk_passed and dvg_passed and qiam_passed and exec_reachable and technical_passed:
            signal_status = "QUALIFIED"
            reasons.append("Core gates passed; trigger and invalidation conditions are delegated to AI follow-up.")
        else:
            signal_status = "PAPER_TEST"
            blocked_reason = "Auto paper sandbox only; real trade gates are not fully passed."
            reasons.append("Automatic paper trading can continue in sandbox; trigger and invalidation conditions are delegated to AI follow-up.")
            if not risk_passed:
                warnings.append("Risk gate is advisory for PAPER_TEST simulation and still blocks QUALIFIED or real trading.")
                blocked.append("QUALIFIED")
            if not dvg_passed:
                warnings.append("DVG gate is advisory for PAPER_TEST simulation and still blocks QUALIFIED or real trading.")
                blocked.append("QUALIFIED")
            if not qiam_passed:
                warnings.append("QIAM gate is advisory for PAPER_TEST simulation and still blocks QUALIFIED or real trading.")
                blocked.extend(["QUALIFIED", "TRADE_PLAN"])
            if not exec_reachable:
                warnings.append("Execution is not fully reachable; real trade plan remains blocked.")
                blocked.extend(["TRADE_PLAN", "MANUAL_CONFIRMED"])
            if not technical_passed:
                warnings.append("Technical Kline invalidation is active; SignalOps remains paper/signal only.")
                blocked.extend(["QUALIFIED", "TRADE_PLAN", "MANUAL_CONFIRMED"])
            blocked = sorted(set(blocked), key=blocked.index)

        data = {
            "signalStatus": signal_status,
            "riskPassed": risk_passed,
            "dvgPassed": dvg_passed,
            "qiamPassed": qiam_passed,
            "executionReachable": exec_reachable,
            "technicalPassed": technical_passed,
            "triggerConditions": trigger_conditions,
            "invalidationConditions": invalidation_conditions,
            "technicalObservationConditions": technical_conditions["observation"],
            "technicalInvalidationConditions": technical_conditions["invalidation"],
            "simulationOnly": True,
            "isRealTrade": False,
            "reviewFields": signal.get("reviewFields", ["财务数据", "市场环境"]),
            "blockedReason": blocked_reason,
        }

        return AgentResult(
            node=self.node,
            status="PASS" if signal_status == "QUALIFIED" else "WARN",
            allowed_actions=["WATCH", "PAPER_TEST", "SIGNAL_ONLY"],
            blocked_actions=blocked,
            hard_stop=False,
            confidence="HIGH" if signal_status == "QUALIFIED" else "MEDIUM",
            reasons=reasons,
            warnings=warnings or ([blocked_reason] if blocked_reason else []),
            data=data,
            audit_id=self._audit(),
        )


def _technical_conditions(technical: Dict[str, Any]) -> Dict[str, Any]:
    observation = []
    invalidation = []
    blocking = False
    if not isinstance(technical, dict) or not technical:
        return {"observation": observation, "invalidation": invalidation, "blocking": blocking}

    bias = str(technical.get("technicalBias") or "").upper()
    trend = technical.get("trend") if isinstance(technical.get("trend"), dict) else {}
    support = technical.get("supportResistance") if isinstance(technical.get("supportResistance"), dict) else {}
    volume = technical.get("volumePrice") if isinstance(technical.get("volumePrice"), dict) else {}
    multi_period = technical.get("multiPeriod") if isinstance(technical.get("multiPeriod"), dict) else {}
    close = _number(trend.get("close"))
    ma20 = _number(trend.get("ma20"))
    support20 = _number(support.get("support20d"))
    return20d = _number(trend.get("return20d")) or 0.0
    volume_ratio = _number(volume.get("volumeRatio5v20"))

    observation.append("Observe close vs MA20 and 20-day support in simulation only.")
    if bias == "BEARISH" or (close is not None and ma20 is not None and close < ma20):
        invalidation.append("Invalidate paper signal if close remains below MA20.")
        blocking = True
    if close is not None and support20 is not None and close < support20:
        invalidation.append("Invalidate paper signal if close breaks 20-day support.")
        blocking = True
    if volume_ratio is not None and volume_ratio >= 1.25 and return20d < 0:
        invalidation.append("Invalidate paper signal on high-volume decline.")
        blocking = True
    if str(multi_period.get("alignment") or "").upper() == "MIXED":
        invalidation.append("Keep paper signal under review while weekly/monthly cycles diverge.")

    return {"observation": observation, "invalidation": invalidation, "blocking": blocking}


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
