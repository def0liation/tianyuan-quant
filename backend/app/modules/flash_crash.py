from __future__ import annotations
from typing import Any, Dict

from .base_agent import BaseAgent, AgentResult


class FlashCrashAgent(BaseAgent):
    node = "flash_crash"
    name = "Flash Crash / Liquidity Trap"
    stage = "guardrail"

    def process(self, run_context: Dict[str, Any], prior_outputs: Dict[str, Any]) -> AgentResult:
        atrade = run_context.get("atrade", {})
        market = run_context.get("market", {})
        risk = run_context.get("risk", {})

        vacuum = atrade.get("flashCrashVacuumStatus", False)
        liquidity_risk = atrade.get("liquidityRisk", "MEDIUM")
        vol_index = market.get("volatilityIndex", 52)
        liq_index = market.get("liquidityIndex", 58)

        reasons = []
        warnings = []
        blocked = []

        is_vacuum = vacuum
        is_extreme_vol = vol_index > 80
        is_liq_crisis = liq_index < 20
        is_liquidity_high = liquidity_risk == "HIGH"

        if is_vacuum:
            status = "BLOCK_BUY"
            reasons.append("检测到闪崩真空状态，立即阻断所有正向交易")
            warnings.append("闪崩真空: 盘口流动性消失，无法正常成交")
            blocked = ["ALL_TRADE_RELATED"]
        elif is_extreme_vol and is_liq_crisis:
            status = "BLOCK_BUY"
            reasons.append(f"极端波动 ({vol_index}) + 流动性危机 ({liq_index})")
            warnings.append("双重极端条件触发，阻断买入")
            blocked = ["BUY_CANDIDATE", "ADD_CANDIDATE", "CHASE", "MARKET_ORDER"]
        elif is_extreme_vol:
            status = "WARN"
            reasons.append(f"波动率指数极高 ({vol_index})，存在闪崩风险")
            warnings.append("建议限制市价单和追涨操作")
            blocked = ["CHASE", "MARKET_ORDER"]
        elif is_liquidity_high:
            status = "WARN"
            reasons.append("流动性风险偏高，存在流动性陷阱可能")
            warnings.append("注意滑点和成交量异常")
        elif is_liq_crisis:
            status = "WARN"
            reasons.append(f"流动性指数偏低 ({liq_index})，存在流动性陷阱")
            warnings.append("限制大额订单执行")
        else:
            status = "PASS"
            reasons.append("未检测到闪崩或流动性陷阱信号")

        data = {
            "flashCrashVacuum": is_vacuum,
            "extremeVolatility": is_extreme_vol,
            "liquidityCrisis": is_liq_crisis,
            "volatilityIndex": vol_index,
            "liquidityIndex": liq_index,
            "status": status,
        }

        return AgentResult(
            node=self.node,
            status=status,
            allowed_actions=["WAIT", "REVIEW_ONLY", "HOLD"],
            blocked_actions=blocked,
            hard_stop=is_vacuum,
            confidence="LOW" if is_vacuum else ("MEDIUM" if status == "WARN" else "HIGH"),
            reasons=reasons,
            warnings=warnings,
            data=data,
            audit_id=self._audit(),
        )
