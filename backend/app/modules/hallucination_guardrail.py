from __future__ import annotations
from typing import Any, Dict

from .base_agent import BaseAgent, AgentResult


class HallucinationGuardrailAgent(BaseAgent):
    node = "hallucination_guardrail"
    name = "Hallucination Guardrail"
    stage = "guardrail"

    def process(self, run_context: Dict[str, Any], prior_outputs: Dict[str, Any]) -> AgentResult:
        dvg_output = prior_outputs.get("dvg_evidence_gate", {})
        dvg_data = dvg_output.get("data", {}) if isinstance(dvg_output, dict) else {}

        hallucination_score = dvg_data.get("hallucinationRiskScore", 38)
        hallucination_level = dvg_data.get("hallucinationRiskLevel", "MEDIUM")
        allowed_output = dvg_data.get("allowedOutputLevel", "FULL")

        reasons = []
        warnings = []
        blocked = []

        if hallucination_score >= 75:
            status = "BLOCK_BUY"
            reasons.append(f"幻觉风险评分 {hallucination_score} (HIGH)，触发硬阻断")
            warnings.append("幻觉风险极高，Final Writer 只允许输出硬风险/合规拒绝模板")
            blocked = ["FULL_OUTPUT", "SECTION_DETAILED", "SECTION_BUY", "SECTION_RECOMMEND"]
        elif hallucination_score >= 50:
            status = "WARN"
            reasons.append(f"幻觉风险评分 {hallucination_score} (MEDIUM-HIGH)")
            warnings.append("限制 Final Writer 不得输出详细推理、具体数值和买入建议")
            blocked = ["SECTION_DETAILED", "SECTION_BUY"]
        elif hallucination_score >= 38:
            status = "WARN"
            reasons.append(f"幻觉风险评分 {hallucination_score} (MEDIUM)")
            warnings.append("建议限制 Final Writer 输出精度")
        else:
            status = "PASS"
            reasons.append(f"幻觉风险评分 {hallucination_score} (LOW)，正常输出")

        if allowed_output == "BLOCK_BUY":
            status = "BLOCK_BUY"
            reasons.append("DVG 已将输出级别限制为 BLOCK_BUY")

        data = {
            "hallucinationRiskScore": hallucination_score,
            "hallucinationRiskLevel": hallucination_level,
            "allowedOutputLevel": allowed_output,
            "restrictedSections": blocked,
            "guardrailActive": hallucination_score >= 50,
        }

        return AgentResult(
            node=self.node,
            status=status,
            allowed_actions=["REVIEW_ONLY"] if blocked else [],
            blocked_actions=blocked,
            hard_stop=hallucination_score >= 75,
            confidence="LOW" if hallucination_score >= 75 else "MEDIUM",
            reasons=reasons,
            warnings=warnings,
            data=data,
            audit_id=self._audit(),
        )
