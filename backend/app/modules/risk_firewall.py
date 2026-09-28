from __future__ import annotations
from typing import Any, Dict

from .base_agent import BaseAgent, AgentResult


class RiskFirewallAgent(BaseAgent):
    node = "risk_firewall"
    name = "Risk Firewall"
    stage = "guardrail"
    rule_engine_only = True

    def process(self, run_context: Dict[str, Any], prior_outputs: Dict[str, Any]) -> AgentResult:
        risk = run_context.get("risk", {})
        dvg_result = prior_outputs.get("dvg_evidence_gate", {})
        user_position = run_context.get("userPosition", {})

        compliance = risk.get("complianceRedLines", [])
        hard_risks = (
            risk.get("f0IndividualHardRisks", [])
            + risk.get("f1ExtremeChipCollapse", [])
            + risk.get("f4ThreePartyFundResonanceOutflow", [])
        )
        liquidity = risk.get("l0AbsoluteLiquidityRedLine", [])
        systemic = risk.get("m0SystemicRisk", [])

        reasons = []
        warnings = []
        allowed = []
        blocked = []

        if compliance:
            status = "BLOCK"
            hard_stop = True
            reasons.append("触发合规红线")
            warnings.append("合规红线触发，禁止所有交易路径")
            blocked = ["ALL_TRADE_RELATED"]
        elif any(r.get("label", "") for r in hard_risks if isinstance(r, dict)):
            status = "BLOCK"
            hard_stop = True
            reasons.append("触发个股硬风险阻断")
            blocked = ["BUY_CANDIDATE", "ADD_CANDIDATE", "CHASE"]
        elif any(r for r in liquidity if isinstance(r, str) and r):
            status = "WARN"
            hard_stop = False
            reasons.append("流动性指标异常，建议关注")
            warnings.append("流动性异常风险")
            allowed = ["REVIEW_ONLY", "WAIT"]
        elif any(r for r in systemic if isinstance(r, str) and r):
            status = "WARN"
            hard_stop = False
            reasons.append("系统性风险处于中等水平")
            warnings.append("系统性风险预警")
            allowed = ["REVIEW_ONLY", "WAIT", "HOLD"]
        else:
            status = "PASS"
            hard_stop = False
            reasons.append("未触发合规红线和个股硬性风险")
            reasons.append("流动性指标在正常范围内")
            reasons.append("系统性风险处于中等水平")
            allowed = ["WAIT", "REVIEW_ONLY", "HOLD", "LIGHT_WATCH"]

        if not user_position.get("maxAcceptableDrawdown"):
            warnings.append("用户未提供最大回撤容忍度，按保守假设 8%")
        if not user_position.get("plannedPeriod"):
            warnings.append("用户未提供计划持仓周期")

        data = {
            "complianceRedLines": compliance,
            "hardRisks": hard_risks,
            "liquidityRisks": liquidity,
            "systemicRisks": systemic,
        }

        return AgentResult(
            node=self.node,
            status=status,
            allowed_actions=allowed,
            blocked_actions=blocked,
            hard_stop=hard_stop,
            final_decision_cap="BLOCK_BUY" if hard_stop else None,
            confidence="HIGH" if status == "PASS" else "MEDIUM",
            reasons=reasons,
            warnings=warnings,
            data=data,
            audit_id=self._audit(),
        )
