from __future__ import annotations
from typing import Any, Dict

from .base_agent import BaseAgent, AgentResult

TASK_TYPES = {
    "position_review": "持仓复核",
    "opportunity": "交易机会发现",
    "risk_check": "风险排查",
    "strategy_backtest": "策略回测",
    "signal_verification": "信号验证",
}

RUN_MODE_MAP = {
    "fast": "FAST_MODE",
    "standard": "STANDARD_MODE",
    "deep": "DEEP_MODE",
}


class RouterAgent(BaseAgent):
    node = "router"
    name = "Router"
    stage = "control"

    def process(self, run_context: Dict[str, Any], prior_outputs: Dict[str, Any]) -> AgentResult:
        task_type = run_context.get("taskType", "持仓复核")
        run_mode = run_context.get("runMode", "STANDARD_MODE")
        symbol = run_context.get("stockCode", "UNKNOWN")
        user_position = run_context.get("userPosition", {})

        reasons = [
            f"任务类型识别为: {task_type}",
            f"运行模式: {run_mode}",
            f"标的代码: {symbol}",
            f"当前持仓比例: {user_position.get('currentPositionRatio', 0) * 100:.0f}%",
        ]

        data = {
            "taskType": task_type,
            "runMode": run_mode,
            "symbol": symbol,
            "requiredAgents": [],
            "missingInputs": [],
        }

        if not user_position.get("maxAcceptableDrawdown"):
            data["missingInputs"].append("最大可接受回撤")
        if not user_position.get("plannedPeriod"):
            data["missingInputs"].append("计划持仓周期")

        return AgentResult(
            node=self.node,
            status="PASS",
            confidence="HIGH",
            reasons=reasons,
            data=data,
            audit_id=self._audit(),
        )
