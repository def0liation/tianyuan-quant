from __future__ import annotations
from typing import Any, Dict

from .base_agent import BaseAgent, AgentResult


class FinalWriterAgent(BaseAgent):
    node = "final_writer"
    name = "Final Writer"
    stage = "output"
    rule_engine_only = True

    def process(self, run_context: Dict[str, Any], prior_outputs: Dict[str, Any]) -> AgentResult:
        ks = run_context.get("killSwitch", {})
        ks_level = ks.get("level", "NONE")
        ks_active = ks.get("active", False)

        dvg_output = prior_outputs.get("dvg_gate") or prior_outputs.get("dvg_evidence_gate", {})
        risk_output = prior_outputs.get("risk_firewall", {})
        qiam_output = prior_outputs.get("quant_engine") or prior_outputs.get("qiam", {})
        atrade_output = prior_outputs.get("trade_micro") or prior_outputs.get("atrade", {})
        portfolio_output = prior_outputs.get("portfolio", {})
        execution_output = prior_outputs.get("execution", {})

        dvg_data = {**(run_context.get("dvg", {}) or {}), **_payload_data(dvg_output)}
        qiam_data = {**(run_context.get("qiam", {}) or {}), **_payload_data(qiam_output)}
        portfolio_data = {**(run_context.get("portfolio", {}) or {}), **_payload_data(portfolio_output)}
        execution_data = {**(run_context.get("execution", {}) or {}), **_payload_data(execution_output)}

        if ks_level == "COMPLIANCE":
            mode = "COMPLIANCE_REJECT"
        elif ks_level == "HARD":
            mode = "HARD_RISK_FINAL_ONLY"
        elif ks_level == "SOFT":
            mode = "CONSERVATIVE"
        else:
            mode = "NORMAL"

        final_action = "WAIT"
        reasons = []

        if mode in ("HARD_RISK_FINAL_ONLY", "COMPLIANCE_REJECT"):
            final_action = "WAIT"
            reasons.append("Kill Switch 触发，进入保守输出模式")
        elif qiam_data.get("finalBuySuitability") == "NEUTRAL":
            final_action = "WAIT"
            reasons.append("QIAM 最终买入适宜性为中性，不建议买入或加仓")
        elif not portfolio_data.get("allowAddPosition", False):
            final_action = "WAIT"
            reasons.append("Portfolio 禁止加仓，维持当前仓位观察")
        elif "BUY_CANDIDATE" in execution_data.get("prohibitedActions", []):
            final_action = "WAIT"
            reasons.append("Execution 明确禁止买入候选，维持观察")
        elif execution_data.get("allowedActions") == []:
            final_action = "WAIT"
            reasons.append("Execution 路径受限")
        elif "BUY_CANDIDATE" in execution_data.get("allowedActions", []):
            final_action = "BUY_CANDIDATE"
            reasons.append("上游仅允许买入候选，仍需人工确认，不能自动下单")
        else:
            final_action = "HOLD"

        reasons.extend([
            f"Final Writer 模式: {mode} (UPSTREAM_ONLY)",
            f"最终动作为: {final_action}",
            f"DVG 数据可靠性: {dvg_data.get('dataReliability', 'MEDIUM')}",
            "不重新推理，仅转述上游判断",
        ])

        data = {
            "mode": mode,
            "finalAction": final_action,
            "humanConfirmationRequired": True,
            "finalDecisionCap": "UPSTREAM_ONLY",
            "dvgReliability": dvg_data.get("dataReliability", "MEDIUM"),
            "sections": [
                {
                    "title": "规则引擎结论",
                    "content": "以上结论由规则引擎根据上游门禁结果生成，非大模型推理。Final Writer 仅忠实地转述各模块的规则判断，不生成新结论。最终动作为 {}，由各门禁环节的规则共同决定。".format(final_action),
                    "riskLevel": "MEDIUM",
                    "requiresConfirmation": True,
                },
                {
                    "title": "数据与风险说明",
                    "content": "DVG 数据可靠性: {}；QIAM 最终校准: {}；Portfolio 加仓允许: {}；Execution 可执行动作: {}。以上均为上游模块的规则判断，非大模型推断。".format(
                        dvg_data.get("dataReliability", "MEDIUM"),
                        qiam_data.get("finalBuySuitability", "NEUTRAL"),
                        portfolio_data.get("allowAddPosition", False),
                        execution_data.get("allowedActions", []) or "无",
                    ),
                    "riskLevel": "MEDIUM",
                    "requiresConfirmation": True,
                },
            ],
        }

        return AgentResult(
            node=self.node,
            status="PASS" if mode == "NORMAL" else "REVIEW_ONLY",
            allowed_actions=["WAIT", "REVIEW_ONLY", "HOLD"],
            blocked_actions=["BUY_CANDIDATE", "ADD_CANDIDATE"] if mode in ("HARD_RISK_FINAL_ONLY", "COMPLIANCE_REJECT") else [],
            hard_stop=False,
            confidence="HIGH",
            reasons=reasons,
            data=data,
            audit_id=self._audit(),
        )


def _payload_data(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    return data if isinstance(data, dict) else payload
