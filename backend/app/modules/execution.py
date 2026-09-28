from __future__ import annotations
from typing import Any, Dict

from .base_agent import BaseAgent, AgentResult


class ExecutionAgent(BaseAgent):
    node = "execution"
    name = "Execution"
    stage = "risk"
    rule_engine_only = True

    def process(self, run_context: Dict[str, Any], prior_outputs: Dict[str, Any]) -> AgentResult:
        execution = run_context.get("execution", {})
        dvg_output = _prior_output(prior_outputs, "dvg_gate", "dvg_evidence_gate")
        qiam_output = _prior_output(prior_outputs, "quant_engine", "qiam")
        atrade_output = _prior_output(prior_outputs, "trade_micro", "atrade")
        portfolio_output = prior_outputs.get("portfolio", {})
        risk_output = prior_outputs.get("risk_firewall", {})

        dvg_data = {**(run_context.get("dvg", {}) or {}), **_payload_data(dvg_output)}
        qiam_data = {**(run_context.get("qiam", {}) or {}), **_payload_data(qiam_output)}
        atrade_data = {**(run_context.get("atrade", {}) or {}), **_payload_data(atrade_output)}
        portfolio_data = {**(run_context.get("portfolio", {}) or {}), **_payload_data(portfolio_output)}

        exec_perm = dvg_data.get("executionPermission", "ALLOW_WITH_DISCOUNT")
        qiam_final = qiam_data.get("finalBuySuitability", "NEUTRAL")
        allow_add = portfolio_data.get("allowAddPosition", False)
        risk_stop = risk_output.get("hard_stop", False) if isinstance(risk_output, dict) else False
        atrade_reachability = atrade_data.get("executionReachability", execution.get("executionReachability", "CONDITIONALLY_REACHABLE"))
        data_mode = str(run_context.get("dataMode") or "").upper()
        reliable_data = data_mode not in {"MOCK", "LEGACY_TEMPLATE"} and dvg_data.get("dataReliability") == "HIGH"

        reasons = []
        warnings = []
        allowed = []
        blocked = []

        if risk_stop:
            status = "BLOCK_BUY"
            reasons.append("Risk Firewall 触发硬风险阻断，执行路径被限制")
            blocked = ["BUY_CANDIDATE", "ADD_CANDIDATE", "CHASE", "EXECUTION_BUY"]
            allowed = ["WAIT", "REVIEW_ONLY"]
        elif atrade_reachability == "NOT_REACHABLE":
            status = "BLOCK_BUY"
            reasons.append("Trade Micro 判定成交不可达，禁止生成买入或加仓路径")
            blocked = ["BUY_CANDIDATE", "ADD_CANDIDATE", "CHASE", "EXECUTION_BUY"]
            allowed = ["WAIT", "REVIEW_ONLY"]
        elif exec_perm == "BLOCKED":
            status = "BLOCK_BUY"
            reasons.append("DVG 阻断执行权限")
            blocked = ["BUY_CANDIDATE", "ADD_CANDIDATE", "EXECUTION_BUY"]
            allowed = ["WAIT", "REVIEW_ONLY"]
        elif qiam_final == "BLOCK_BUY":
            status = "BLOCK_BUY"
            reasons.append("QIAM 最终买入适宜性为 BLOCK_BUY")
            blocked = ["BUY_CANDIDATE", "ADD_CANDIDATE"]
            allowed = ["WAIT", "REVIEW_ONLY"]
        elif qiam_final == "NEUTRAL" and not allow_add:
            status = "REVIEW_ONLY"
            reasons.append("QIAM 中性 + Portfolio 禁止加仓 → 限制执行")
            blocked = ["BUY_CANDIDATE", "ADD_CANDIDATE"]
            allowed = ["WAIT", "REVIEW_ONLY"]
        elif qiam_final != "FAVORABLE":
            status = "REVIEW_ONLY"
            reasons.append(f"QIAM 最终适宜性为 {qiam_final}，不能升级为买入候选")
            blocked = ["BUY_CANDIDATE", "ADD_CANDIDATE"]
            allowed = ["WAIT", "REVIEW_ONLY", "HOLD"]
        elif not allow_add:
            status = "REVIEW_ONLY"
            reasons.append("Portfolio 未允许加仓，不能升级为买入候选")
            blocked = ["BUY_CANDIDATE", "ADD_CANDIDATE"]
            allowed = ["WAIT", "REVIEW_ONLY", "HOLD"]
        elif atrade_reachability == "CONDITIONALLY_REACHABLE":
            status = "WARN"
            reasons.append("成交仅有条件可达，执行层只能保留观察和复核路径")
            blocked = ["BUY_CANDIDATE", "ADD_CANDIDATE", "CHASE", "AUTO_ORDER"]
            allowed = ["WAIT", "REVIEW_ONLY", "HOLD"]
        elif exec_perm != "ALLOW":
            status = "WARN"
            reasons.append(f"执行权限限制为 {exec_perm}")
            allowed = ["WAIT", "REVIEW_ONLY"]
            blocked = ["CHASE", "AUTO_ORDER"]
        elif not reliable_data:
            status = "REVIEW_ONLY"
            reasons.append("数据模式或 DVG 可靠性不足，不能升级为买入候选")
            blocked = ["BUY_CANDIDATE", "ADD_CANDIDATE"]
            allowed = ["WAIT", "REVIEW_ONLY", "HOLD"]
        else:
            status = "PASS"
            reasons.append("执行前置条件满足，但仍只生成候选动作，不能自动下单")
            allowed = ["WAIT", "REVIEW_ONLY", "HOLD", "BUY_CANDIDATE"]

        warnings.append("执行可达性只表示成交条件，不代表系统允许实盘买入")
        warnings.append("系统不自动下单，所有交易动作必须人工确认")
        if blocked:
            warnings.append(f"禁止动作: {', '.join(blocked)}")
        if allowed:
            warnings.append(f"允许动作: {', '.join(allowed)}")

        if status == "BLOCK_BUY":
            reachability = "NOT_REACHABLE"
        elif atrade_reachability == "CONDITIONALLY_REACHABLE" or status in {"WARN", "REVIEW_ONLY"}:
            reachability = "CONDITIONALLY_REACHABLE"
        else:
            reachability = "REACHABLE"

        data = {
            "allowedActions": allowed,
            "prohibitedActions": blocked,
            "executionReachability": reachability,
            "batchPaths": ["限价单", "分批买入"] if "BUY_CANDIDATE" not in blocked else [],
            "slippageLimit": execution.get("slippageLimit", 0.005),
            "participationLimit": execution.get("participationLimit", 0.1),
            "manualConfirmationItems": ["所有执行动作需要人工复核"],
            "forbiddenActions": ["自动下单", "市价追涨"],
        }

        return AgentResult(
            node=self.node,
            status=status,
            allowed_actions=allowed,
            blocked_actions=blocked,
            hard_stop=False,
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
