from __future__ import annotations
from typing import Any, Dict

from .base_agent import BaseAgent, AgentResult


class ChipKbAgent(BaseAgent):
    node = "chip_kb"
    name = "Chip KB"
    stage = "data"

    def process(self, run_context: Dict[str, Any], prior_outputs: Dict[str, Any]) -> AgentResult:
        chip = run_context.get("chipKb", {})
        symbol = run_context.get("stockCode", "UNKNOWN")
        data_fetch_output = prior_outputs.get("data_fetch", {})
        df_data = data_fetch_output.get("data", {}) if isinstance(data_fetch_output, dict) else {}

        current_pool = chip.get("currentPool", "B")
        suggested_pool = chip.get("suggestedPool", "D")
        migration = chip.get("migrationDirection", "DOWNGRADE")
        risk_patches = chip.get("hitRiskPatches", [])
        positive_patches = chip.get("hitPositivePatches", [])
        data_confidence = chip.get("dataConfidenceLevel", 0.82)
        core_missing = chip.get("coreMissingData", ["主力流入数据"])

        reasons = []

        if migration == "DOWNGRADE":
            status = "WARN"
            reasons.append(f"筹码池评级: {current_pool} → {suggested_pool} (降级)")
            reasons.append(f"数据置信度: {data_confidence:.0%}")
        elif migration == "UPGRADE":
            status = "PASS"
            reasons.append(f"筹码池评级: {current_pool} → {suggested_pool} (升级)")
        else:
            status = "PASS"
            reasons.append(f"筹码池评级稳定: {current_pool}")

        if risk_patches:
            reasons.append(f"触发风险补丁: {', '.join(risk_patches)}")
        if positive_patches:
            reasons.append(f"正向补丁: {', '.join(positive_patches)}")

        warnings = []
        if data_confidence < 0.85:
            warnings.append(f"筹码数据来源为第三方估算，置信度仅 {data_confidence:.0%}")
        if core_missing:
            reasons.append(f"核心缺失: {', '.join(core_missing)}")
            warnings.append(f"缺失关键筹码数据: {', '.join(core_missing)}")

        data = {
            "symbol": symbol,
            "currentPool": current_pool,
            "suggestedPool": suggested_pool,
            "migrationDirection": migration,
            "hitRiskPatches": risk_patches,
            "hitPositivePatches": positive_patches,
            "dataConfidenceLevel": data_confidence,
            "coreMissingData": core_missing,
            "signalOpsMappingStatus": chip.get("signalOpsMappingStatus", "MAPPED"),
            "triggerConditions": chip.get("triggerConditions", ["资金面回撤", "消息面不确定"]),
            "invalidationConditions": chip.get("invalidationConditions", ["行业减速"]),
            "reviewCycle": chip.get("reviewCycle", 30),
        }

        return AgentResult(
            node=self.node,
            status=status,
            confidence="MEDIUM" if data_confidence < 0.85 else "HIGH",
            reasons=reasons,
            missing_data=core_missing,
            warnings=warnings,
            data=data,
            audit_id=self._audit(),
        )
