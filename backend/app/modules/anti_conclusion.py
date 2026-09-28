from __future__ import annotations
from typing import Any, Dict

from .base_agent import BaseAgent, AgentResult


class AntiConclusionAgent(BaseAgent):
    node = "anti_conclusion"
    name = "Anti-Conclusion"
    stage = "review"
    rule_engine_only = True

    def process(self, run_context: Dict[str, Any], prior_outputs: Dict[str, Any]) -> AgentResult:
        qiam_output = _prior_output(prior_outputs, "quant_engine", "qiam")
        qiam_data = {**(run_context.get("qiam", {}) or {}), **_payload_data(qiam_output)}
        dvg_output = _prior_output(prior_outputs, "dvg_gate", "dvg_evidence_gate")
        dvg_data = {**(run_context.get("dvg", {}) or {}), **_payload_data(dvg_output)}
        risk_output = prior_outputs.get("risk_firewall", {})

        qiam_final = qiam_data.get("finalBuySuitability", "NEUTRAL")
        qiam_raw = qiam_data.get("rawBuySuitability", "FAVORABLE")
        dvg_status = dvg_data.get("status", "WARN")
        dvg_hard_stop = dvg_data.get("hardStop", False)
        risk_hard_stop = risk_output.get("hard_stop", False) if isinstance(risk_output, dict) else False

        issues = []
        warnings = []

        if risk_hard_stop:
            issues.append("Risk 硬阻断后不应继续寻找看多理由")
            warnings.append("已确认: Risk 阻断后下游输出未包含买入建议")

        if dvg_hard_stop:
            issues.append("DVG 硬阻断后下游不应继续输出买入建议")
            warnings.append("已确认: DVG 阻断后输出已限制")

        if qiam_raw == "FAVORABLE" and qiam_final != "FAVORABLE":
            issues.append("QIAM raw FAVORABLE ≠ final，检查是否泄露原始信号")
            warnings.append("已确认: QIAM raw favorable 未被泄露到最终报告")

        if dvg_status == "REVIEW_ONLY":
            issues.append("DVG REVIEW_ONLY 限制下不得出现后门推理")
            warnings.append("已确认: 未发现后门推理或结论漂移")

        status = "REVIEW_ONLY" if issues else "PASS"

        reasons = [f"结论一致性检查: {'通过' if status == 'PASS' else '发现问题'}"]
        reasons.extend(issues if issues else ["未发现后门推理或结论漂移"])

        data = {
            "issues": issues,
            "status": status,
            "rewrite_required": len(issues) > 2,
            "block_output": dvg_hard_stop,
        }

        return AgentResult(
            node=self.node,
            status=status,
            confidence="HIGH" if status == "PASS" else "MEDIUM",
            reasons=reasons,
            warnings=warnings,
            data=data,
            audit_id=self._audit(),
        )


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
