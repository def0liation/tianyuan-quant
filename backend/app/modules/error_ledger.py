from __future__ import annotations
from typing import Any, Dict

from .base_agent import BaseAgent, AgentResult


class ErrorLedgerAgent(BaseAgent):
    node = "error_ledger"
    name = "Error Ledger Agent"
    stage = "review"

    def process(self, run_context: Dict[str, Any], prior_outputs: Dict[str, Any]) -> AgentResult:
        llm_trace = run_context.get("llmTrace", [])
        agent_outputs = run_context.get("agentOutputs", {})
        module_results = run_context.get("agentModuleResults", {})

        errors = []
        warnings = []
        reasons = []

        for trace in llm_trace:
            if isinstance(trace, dict) and trace.get("status") == "FAILED":
                node = trace.get("nodeId", trace.get("node", ""))
                error_msg = trace.get("error", "Unknown LLM error")
                errors.append({
                    "node": node,
                    "error_type": "LLM_FAILURE",
                    "error_reason": error_msg[:200],
                    "repeated_count": 1,
                })
                reasons.append(f"LLM 失败: {node} - {error_msg[:80]}")

        for agent_id, output in module_results.items():
            if isinstance(output, dict) and output.get("status") in ("ERROR", "BLOCK", "BLOCK_BUY"):
                errors.append({
                    "node": agent_id,
                    "error_type": "MODULE_BLOCK",
                    "error_reason": output.get("reasons", [""])[0] if output.get("reasons") else "模块阻断",
                    "repeated_count": 1,
                })
                reasons.append(f"模块阻断: {agent_id}")

        if not errors:
            reasons.append("未发现新增错误记录")
            status = "PASS"
        else:
            status = "WARN"
            warnings.append(f"发现 {len(errors)} 条错误记录")

        data = {
            "errorCount": len(errors),
            "errors": errors[:10],
            "errorTypes": list(set(e.get("error_type", "") for e in errors)),
            "patchRequired": len(errors) > 0,
            "ledgerStatus": "ACTIVE" if errors else "CLEAN",
        }

        return AgentResult(
            node=self.node,
            status=status,
            confidence="MEDIUM",
            reasons=reasons,
            warnings=warnings,
            data=data,
            audit_id=self._audit(),
        )
