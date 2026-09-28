from __future__ import annotations
from typing import Any, Dict

from .base_agent import BaseAgent, AgentResult


class MemoryAgent(BaseAgent):
    node = "memory_agent"
    name = "Memory Agent"
    stage = "data"

    def process(self, run_context: Dict[str, Any], prior_outputs: Dict[str, Any]) -> AgentResult:
        symbol = run_context.get("stockCode", "UNKNOWN")
        prior_runs = run_context.get("priorRunSummaries", [])
        signal_history = run_context.get("signalHistory", [])

        reasons = []
        memory_facts = []

        if prior_runs:
            reasons.append(f"加载了 {len(prior_runs)} 次历史分析记录")
            for pr in prior_runs[:3]:
                if isinstance(pr, dict):
                    memory_facts.append({
                        "runId": pr.get("runId", ""),
                        "finalAction": pr.get("finalAction", ""),
                        "dvgReliability": pr.get("dvgReliability", ""),
                    })
        else:
            reasons.append(f"标的 {symbol} 无历史分析记录，本次为首轮分析")

        if signal_history:
            reasons.append(f"加载了 {len(signal_history)} 条历史信号记录")

        data = {
            "symbol": symbol,
            "priorRunCount": len(prior_runs),
            "memoryFacts": memory_facts,
            "firstAnalysis": len(prior_runs) == 0,
            "signalHistoryCount": len(signal_history),
        }

        return AgentResult(
            node=self.node,
            status="PASS",
            confidence="HIGH" if prior_runs else "MEDIUM",
            reasons=reasons,
            data=data,
            audit_id=self._audit(),
        )
