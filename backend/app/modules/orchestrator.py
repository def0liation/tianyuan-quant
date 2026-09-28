from __future__ import annotations
from typing import Any, Dict

from .base_agent import BaseAgent, AgentResult
from ..core.agent_framework import RUN_MODE_NODES, KILL_SWITCH_RULES


class OrchestratorAgent(BaseAgent):
    node = "orchestrator"
    name = "Orchestrator"
    stage = "control"

    def process(self, run_context: Dict[str, Any], prior_outputs: Dict[str, Any]) -> AgentResult:
        run_mode = run_context.get("runMode", "STANDARD_MODE")
        enabled_nodes = list(RUN_MODE_NODES.get(run_mode, RUN_MODE_NODES["STANDARD_MODE"]))

        mandatory = ["router", "data_fetch", "dvg_evidence_gate", "risk_firewall", "execution", "final_writer"]
        conditional = [n for n in enabled_nodes if n not in mandatory]

        ks_rules = []
        for rule_id, rule in KILL_SWITCH_RULES.items():
            ks_rules.append(f"{rule_id} -> {rule['level']} -> {rule.get('final_writer_mode', 'N/A')}")

        reasons = [
            f"编排运行模式: {run_mode}",
            f"启用节点({len(enabled_nodes)}): {', '.join(enabled_nodes)}",
            f"强制节点: {', '.join(mandatory)}",
            f"Kill Switch 规则已就位: {len(ks_rules)}条",
        ]

        data = {
            "mode": run_mode,
            "mandatory_nodes": mandatory,
            "conditional_nodes": conditional,
            "enabled_nodes": enabled_nodes,
            "kill_switch_rules": ks_rules,
            "final_writer_mode": "NORMAL",
        }

        return AgentResult(
            node=self.node,
            status="PASS",
            confidence="HIGH",
            reasons=reasons,
            data=data,
            audit_id=self._audit(),
        )
