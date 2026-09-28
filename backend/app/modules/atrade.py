from __future__ import annotations
from typing import Any, Dict

from .base_agent import BaseAgent, AgentResult


class ATradeAgent(BaseAgent):
    node = "atrade"
    name = "A-Trade Microstructure"
    stage = "analysis"
    rule_engine_only = True

    def process(self, run_context: Dict[str, Any], prior_outputs: Dict[str, Any]) -> AgentResult:
        atrade = run_context.get("atrade", {})
        user_position = run_context.get("userPosition", {})

        t1_status = atrade.get("t1Status", True)
        price_limit = atrade.get("priceLimitStatus", "NORMAL")
        level2_available = atrade.get("level2Available", False)
        depth_available = atrade.get("depthAvailable", False)
        execution_reachability = atrade.get("executionReachability", "REACHABLE")
        liquidity_risk = atrade.get("liquidityRisk", "MEDIUM")
        slippage_limit = atrade.get("slippageLimit", 0.005)
        st_delisting = atrade.get("stDelistingRisk", False)
        sellable = user_position.get("sellableBottomWarehouse", True)

        reasons = []
        warnings = []
        missing = []

        reasons.append(f"T+1 状态: {'正常' if t1_status else '受限'}")
        reasons.append(f"价格限制: {price_limit}")
        reasons.append(f"可卖底仓: {'存在' if sellable else '不存在'}")

        if st_delisting:
            reasons.append("ST/退市风险存在，需回避")
            warnings.append("ST/退市风险警示")
            status = "BLOCK_BUY"
            hard_stop = False
        elif execution_reachability == "NOT_REACHABLE":
            status = "BLOCK_BUY"
            hard_stop = False
            reasons.append("当前标的不具备成交可达性")
            warnings.append("执行不可达，禁止生成买入计划")
        elif liquidity_risk == "HIGH":
            status = "WARN"
            hard_stop = False
            reasons.append("流动性风险偏高")
            warnings.append("滑点限制: 0.5%, 参与度限制: 10%")
        elif not level2_available or not depth_available:
            status = "WARN"
            hard_stop = False
            reasons.append("成交可达性: 有条件可达")
        else:
            status = "PASS"
            hard_stop = False
            reasons.append("成交可达性: 可达")

        if not level2_available:
            missing.append("Level-2 逐笔成交")
            warnings.append("无 Level-2 无法判断封单强弱，追板策略风险极高")
            reasons.append("Level-2 不可用，无法准确评估盘口真实性")
        if not depth_available:
            missing.append("盘口深度")
            warnings.append("盘口深度缺失，滑点风险无法量化")
            reasons.append("盘口深度数据缺失，流动性冲击不确定")

        if status == "BLOCK_BUY":
            reachability = "NOT_REACHABLE"
        elif status == "WARN":
            reachability = "CONDITIONALLY_REACHABLE"
        else:
            reachability = "REACHABLE"

        data = {
            "t1Status": t1_status,
            "priceLimitStatus": price_limit,
            "level2Available": level2_available,
            "depthAvailable": depth_available,
            "executionReachability": reachability,
            "liquidityRisk": liquidity_risk,
            "slippageLimit": slippage_limit,
            "participationLimit": atrade.get("participationLimit", 0.1),
            "stDelistingRisk": st_delisting,
            "sellableBottomWarehouse": sellable,
        }

        return AgentResult(
            node=self.node,
            status=status,
            allowed_actions=["WAIT", "REVIEW_ONLY"] if status != "PASS" else [],
            blocked_actions=["BUY_CANDIDATE", "EXECUTION_BUY"] if status == "BLOCK_BUY" else (["CHASE"] if not level2_available else []),
            hard_stop=hard_stop,
            confidence="HIGH" if status == "PASS" else "MEDIUM",
            reasons=reasons,
            missing_data=missing,
            warnings=warnings,
            data=data,
            audit_id=self._audit(),
        )
