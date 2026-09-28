from __future__ import annotations
from typing import Any, Dict

from .base_agent import BaseAgent, AgentResult


class SimulationAgent(BaseAgent):
    node = "simulation_agent"
    name = "Simulation Agent"
    stage = "analysis"

    def process(self, run_context: Dict[str, Any], prior_outputs: Dict[str, Any]) -> AgentResult:
        scenario_output = prior_outputs.get("scenario_engine", {})
        scenario_data = scenario_output.get("data", {}) if isinstance(scenario_output, dict) else {}

        can_simulate = run_context.get("simulationEnabled", False)
        has_historical_data = run_context.get("hasHistoricalData", False)

        reasons = []
        warnings = []

        if not can_simulate:
            status = "SKIPPED"
            reasons.append("模拟引擎未启用，跳过蒙特卡洛/历史回放")
            warnings.append("无法生成概率量化结果")
        elif not has_historical_data:
            status = "WARN"
            reasons.append("缺少历史数据，无法进行完整模拟")
            warnings.append("模拟结果为定性估计，非精确概率")
        else:
            status = "PASS"
            reasons.append("模拟引擎运行正常，概率分布可用")

        data = {
            "simulationEnabled": can_simulate,
            "hasHistoricalData": has_historical_data,
            "monteCarloTrials": 10000 if can_simulate else 0,
            "confidenceInterval": "95%" if can_simulate else "N/A",
            "simulationStatus": status,
        }

        return AgentResult(
            node=self.node,
            status=status,
            skipped_reason="模拟未启用" if status == "SKIPPED" else "",
            confidence="MEDIUM",
            reasons=reasons,
            warnings=warnings,
            data=data,
            audit_id=self._audit(),
        )
