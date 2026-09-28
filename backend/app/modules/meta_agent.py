from __future__ import annotations
from typing import Any, Dict

from .base_agent import BaseAgent, AgentResult


class MetaAgent(BaseAgent):
    node = "meta_agent"
    name = "Meta-Agent"
    stage = "review"

    def process(self, run_context: Dict[str, Any], prior_outputs: Dict[str, Any]) -> AgentResult:
        error_ledger = run_context.get("errorLedger", [])
        repeated_errors = run_context.get("repeatedErrors", [])
        system_metrics = run_context.get("systemMetrics", {})

        reasons = []
        patch_candidates = []

        if error_ledger:
            reasons.append(f"发现 {len(error_ledger)} 条历史错误记录")
            for err in error_ledger[:3]:
                if isinstance(err, dict):
                    error_type = err.get("error_type", err.get("errorType", "UNKNOWN"))
                    node = err.get("node", "UNKNOWN")
                    count = err.get("repeated_count", err.get("repeatedCount", 1))
                    if count >= 3:
                        patch_candidates.append({
                            "title": f"{node} 重复错误 ({count}次)",
                            "type": error_type,
                            "affectedModule": node,
                            "reason": f"模块 {node} 发生 {count} 次 {error_type} 类型重复错误",
                            "risk": "MEDIUM",
                        })

        if repeated_errors:
            reasons.append(f"{len(repeated_errors)} 个模块存在重复失败模式")

        if system_metrics:
            cpu = system_metrics.get("cpuPercent", 0)
            memory = system_metrics.get("memoryPercent", 0)
            if cpu > 80 or memory > 80:
                reasons.append(f"系统资源预警: CPU {cpu}%, Memory {memory}%")

        status = "WARN" if patch_candidates else "PASS"
        reasons.append(f"生成 {len(patch_candidates)} 个候选补丁")

        if not patch_candidates:
            reasons.append("当前无不稳定模式需要自动修正")

        data = {
            "errorLedgerCount": len(error_ledger),
            "patchCandidates": patch_candidates,
            "patchCount": len(patch_candidates),
            "metaStatus": "CANDIDATE" if patch_candidates else "STABLE",
            "systemHealth": "WARN" if (system_metrics.get("cpuPercent", 0) > 80) else "OK",
        }

        return AgentResult(
            node=self.node,
            status=status,
            confidence="MEDIUM",
            reasons=reasons,
            data=data,
            audit_id=self._audit(),
        )
