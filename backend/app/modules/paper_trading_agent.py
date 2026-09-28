from __future__ import annotations
from typing import Any, Dict

from .base_agent import BaseAgent, AgentResult


class PaperTradingAgent(BaseAgent):
    node = "paper_trading_agent"
    name = "Paper Trading Agent"
    stage = "ops"

    def process(self, run_context: Dict[str, Any], prior_outputs: Dict[str, Any]) -> AgentResult:
        paper = run_context.get("paperTrading", {})
        signal_output = prior_outputs.get("signalops", {})
        signal_data = signal_output.get("data", {}) if isinstance(signal_output, dict) else {}
        signal_status = signal_data.get("signalStatus", "PAPER_TEST")
        entry_assumptions = paper.get("entryAssumptions", paper.get("entry_assumptions", []))
        invalidation_conditions = paper.get("invalidationConditions", paper.get("invalidation_conditions", []))
        tracked_symbols = paper.get("trackedSymbols", paper.get("tracked_symbols", []))
        simulation_actions = paper.get("simulationActions", paper.get("simulation_actions", []))

        reasons = []
        warnings = []

        if signal_status == "CLOSED":
            status = "SKIPPED"
            reasons.append("信号已关闭，自动模拟交易不再新增动作")
        elif not tracked_symbols and not simulation_actions and not entry_assumptions:
            status = "WARN"
            reasons.append("自动模拟交易等待股票池、行情或 AI 动作输入")
            warnings.append("未发现股票池或模拟动作，本轮仅保留沙箱观察状态")
        else:
            status = "ACTIVE"
            reasons.append("自动模拟交易沙箱已启动，AI 可按行情自行记录 SIM_* 动作")
            if tracked_symbols:
                reasons.append(f"股票池: {', '.join(tracked_symbols[:5])}")
            if entry_assumptions:
                reasons.append(f"AI 入场假设: {', '.join(entry_assumptions[:3])}")

        if invalidation_conditions:
            reasons.append(f"AI 失效判断: {', '.join(invalidation_conditions[:3])}")

        data = {
            "status": status,
            "observationPeriod": paper.get("observationPeriod", 14),
            "entryAssumptions": entry_assumptions,
            "invalidationConditions": invalidation_conditions,
            "trackedSymbols": tracked_symbols,
            "simulationActions": simulation_actions,
            "simulatedProfit": paper.get("simulatedProfit", 0.0),
            "maxDrawdown": paper.get("maxDrawdown", 0.0),
            "triggeredInvalidation": paper.get("triggeredInvalidation", False),
            "writtenToLedger": paper.get("writtenToLedger", False),
            "triggeredErrorLedger": paper.get("triggeredErrorLedger", False),
            "slippageAssumption": 0.005,
            "simulationOnly": True,
            "isRealTrade": False,
        }

        return AgentResult(
            node=self.node,
            status=status,
            skipped_reason="信号已关闭" if status == "SKIPPED" else "",
            confidence="MEDIUM",
            reasons=reasons,
            warnings=warnings,
            data=data,
            audit_id=self._audit(),
        )
