from __future__ import annotations
from typing import Any, Dict

from .base_agent import BaseAgent, AgentResult


class StateSerializationAgent(BaseAgent):
    node = "state_serialization"
    name = "State Serialization"
    stage = "output"

    def process(self, run_context: Dict[str, Any], prior_outputs: Dict[str, Any]) -> AgentResult:
        import hashlib
        import json

        state = {
            "runId": run_context.get("runId", ""),
            "stockCode": run_context.get("stockCode", ""),
            "runMode": run_context.get("runMode", ""),
            "taskType": run_context.get("taskType", ""),
            "finalAction": run_context.get("finalAction", "WAIT"),
        }

        final_writer_output = prior_outputs.get("final_writer", {})
        fw_data = final_writer_output.get("data", {}) if isinstance(final_writer_output, dict) else {}
        state["finalWriterMode"] = fw_data.get("mode", "NORMAL")

        ks = run_context.get("killSwitch", {})
        state["killSwitchLevel"] = ks.get("level", "NONE")

        state_str = json.dumps(state, sort_keys=True, default=str)
        checksum = hashlib.sha256(state_str.encode()).hexdigest()

        schema_ver = run_context.get("schemaVersion", "10.2")
        current_ver = "10.2"

        reasons = [f"State Snapshot 已生成，checksum: {checksum[:16]}"]
        warnings = []

        if schema_ver != current_ver:
            reasons.append(f"Schema 版本不兼容 ({schema_ver} vs {current_ver})")
            warnings.append("Schema 版本不匹配，恢复前需经过 State Validation")

        data = {
            "snapshot": state,
            "checksum": checksum,
            "schemaVersion": current_ver,
            "inputSchemaVersion": schema_ver,
            "compatible": schema_ver == current_ver,
            "snapshotType": "FULL",
        }

        return AgentResult(
            node=self.node,
            status="PASS" if schema_ver == current_ver else "WARN",
            confidence="HIGH",
            reasons=reasons,
            warnings=warnings,
            data=data,
            audit_id=self._audit(),
        )
