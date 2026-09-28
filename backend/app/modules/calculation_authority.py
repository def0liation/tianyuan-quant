from __future__ import annotations
from typing import Any, Dict

from .base_agent import BaseAgent, AgentResult


class CalculationAuthorityAgent(BaseAgent):
    node = "calculation_authority"
    name = "Calculation Authority"
    stage = "control"

    def process(self, run_context: Dict[str, Any], prior_outputs: Dict[str, Any]) -> AgentResult:
        has_tools = run_context.get("hasCalculationTools", False)
        tool_status = run_context.get("calculationToolStatus", "UNKNOWN")

        reasons = []
        warnings = []
        blocked = []

        if tool_status == "FAILED":
            status = "WARN"
            reasons.append("计算工具状态异常，禁止精确计算")
            warnings.append("所有精确数值输出必须标记为估算")
            blocked = ["PRECISE_CALCULATION"]
        elif not has_tools and tool_status != "AVAILABLE":
            status = "WARN"
            reasons.append("无可用的精确计算工具")
            warnings.append("不允许 LLM 口算替代，精确数值必须标记 U")
            blocked = ["PRECISE_CALCULATION", "OPTIMAL_POSITION_SIZE", "PRECISE_STOP_LOSS"]
        else:
            status = "PASS"
            reasons.append("计算工具状态正常，可进行精确计算")

        data = {
            "hasCalculationTools": has_tools,
            "calculationToolStatus": tool_status,
            "allowedCalculationTypes": [] if blocked else ["POSITION", "STOP_LOSS", "TAKE_PROFIT", "SLIPPAGE", "IMPACT"],
            "forbiddenCalculationTypes": blocked,
            "llmCalculationProhibited": True,
        }

        return AgentResult(
            node=self.node,
            status=status,
            allowed_actions=[] if status == "PASS" else ["REVIEW_ONLY"],
            blocked_actions=blocked,
            hard_stop=False,
            confidence="HIGH" if status == "PASS" else "MEDIUM",
            reasons=reasons,
            warnings=warnings,
            data=data,
            audit_id=self._audit(),
        )
