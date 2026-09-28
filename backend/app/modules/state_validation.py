from __future__ import annotations
from typing import Any, Dict

from .base_agent import BaseAgent, AgentResult


class StateValidationAgent(BaseAgent):
    node = "state_validation"
    name = "State Validation"
    stage = "control"

    def process(self, run_context: Dict[str, Any], prior_outputs: Dict[str, Any]) -> AgentResult:
        requires = ["stockCode", "taskType", "runMode", "userPosition"]
        missing = []

        for field in requires:
            value = run_context.get(field)
            if value is None or (isinstance(value, (list, dict, str)) and not value):
                missing.append(field)

        user_position = run_context.get("userPosition", {})
        if user_position:
            if not user_position.get("currentPositionRatio") and not user_position.get("currentShares"):
                missing.append("持仓信息（百分比或股数）")

        status = "PASS" if not missing else "WARN"
        reasons = (
            [f"所有必填字段完整性验证通过 ({len(requires)} 项)"]
            if not missing
            else [f"缺少 {len(missing)} 项必填信息: {', '.join(missing)}"]
        )

        warnings = [f"缺失字段: {f}" for f in missing]
        data = {
            "requiredFields": requires,
            "missingFields": missing,
            "allPresent": len(missing) == 0,
            "schemaVersion": run_context.get("schemaVersion", "10.2"),
        }

        return AgentResult(
            node=self.node,
            status=status,
            confidence="HIGH" if not missing else "MEDIUM",
            reasons=reasons,
            missing_data=missing,
            warnings=warnings,
            data=data,
            audit_id=self._audit(),
        )
