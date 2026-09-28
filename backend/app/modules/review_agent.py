from __future__ import annotations
from typing import Any, Dict

from .base_agent import BaseAgent, AgentResult


class ReviewAgent(BaseAgent):
    node = "review_agent"
    name = "Review Agent"
    stage = "review"

    def process(self, run_context: Dict[str, Any], prior_outputs: Dict[str, Any]) -> AgentResult:
        final_action = run_context.get("finalAction", "WAIT")
        signal_output = prior_outputs.get("signalops", {})
        signal_data = signal_output.get("data", {}) if isinstance(signal_output, dict) else {}
        execution_output = prior_outputs.get("execution", {})
        execution_data = execution_output.get("data", {}) if isinstance(execution_output, dict) else {}

        reasons = []
        attribution = {
            "decisionChain": [],
            "mistakeTags": [],
            "reviewNeeded": False,
        }

        qiam_output = prior_outputs.get("qiam", {})
        qiam_data = qiam_output.get("data", {}) if isinstance(qiam_output, dict) else {}

        dvg_output = prior_outputs.get("dvg_evidence_gate", {})
        dvg_data = dvg_output.get("data", {}) if isinstance(dvg_output, dict) else {}

        qiam_final = qiam_data.get("finalBuySuitability", "NEUTRAL")
        dvg_reliability = dvg_data.get("dataReliability", "MEDIUM")
        blocked_actions = execution_data.get("prohibitedActions", [])
        signal_status = signal_data.get("signalStatus", "WATCH")

        reasons.append(f"最终动作: {final_action}")
        reasons.append(f"QIAM 最终: {qiam_final}")
        reasons.append(f"DVG 可靠性: {dvg_reliability}")
        reasons.append(f"信号状态: {signal_status}")

        if final_action == "WAIT" and qiam_final == "NEUTRAL":
            attribution["decisionChain"].append("QIAM NEUTRAL → WAIT (合理)")
        elif final_action == "WAIT" and blocked_actions:
            attribution["decisionChain"].append(f"上游阻断 {blocked_actions} → WAIT (合理)")

        if dvg_reliability in ("LOW",):
            attribution["mistakeTags"].append("数据可靠性不足却继续分析")
            attribution["reviewNeeded"] = True

        if qiam_final == "BLOCK_BUY" and final_action not in ("WAIT", "REVIEW_ONLY"):
            attribution["mistakeTags"].append("QIAM BLOCK_BUY 后仍输出正向动作")
            attribution["reviewNeeded"] = True

        status = "PASS" if not attribution["reviewNeeded"] else "WARN"

        data = {
            "reviewType": "TRADE",
            "finalAction": final_action,
            "attribution": attribution,
            "mistakeTags": attribution["mistakeTags"],
            "reviewNeeded": attribution["reviewNeeded"],
            "conclusion": "决策链一致性复查完成" if not attribution["reviewNeeded"] else "发现问题条目需人工复核",
        }

        return AgentResult(
            node=self.node,
            status=status,
            confidence="HIGH" if not attribution["reviewNeeded"] else "MEDIUM",
            reasons=reasons,
            warnings=attribution["mistakeTags"] if attribution["mistakeTags"] else [],
            data=data,
            audit_id=self._audit(),
        )
