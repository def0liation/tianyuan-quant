from __future__ import annotations
from typing import Any, Dict

from .base_agent import BaseAgent, AgentResult


class SectorRotationAgent(BaseAgent):
    node = "sector_rotation"
    name = "Sector Rotation"
    stage = "analysis"

    def process(self, run_context: Dict[str, Any], prior_outputs: Dict[str, Any]) -> AgentResult:
        market = run_context.get("market", {})
        sectors = market.get("sectorRotation", [])
        sentiment = market.get("marketSentiment", "NEUTRAL")
        inst_activity = market.get("institutionalActivity", "MEDIUM")

        reasons = []
        warnings = []

        rotation_strength = "MEDIUM"

        if not sectors:
            status = "WARN"
            reasons.append("板块轮动数据不可用，无法判断资金流向")
            warnings.append("缺少板块轮动数据")
        elif len(sectors) >= 3:
            status = "WARN"
            reasons.append(f"多板块活跃 ({', '.join(sectors)})，轮动加速")
            warnings.append("板块轮动过快，风格切换风险上升")
            rotation_strength = "HIGH"
        elif len(sectors) >= 1:
            status = "PASS"
            reasons.append(f"当前热点板块: {', '.join(sectors)}")
            rotation_strength = "MEDIUM"
        else:
            status = "PASS"
            reasons.append("板块轮动处于正常状态")

        if sentiment == "EXTREME_GREED" or sentiment == "EXTREME_FEAR":
            warnings.append(f"市场情绪极端 ({sentiment})，板块轮动可能异常")
            rotation_strength = "HIGH"

        data = {
            "activeSectors": sectors,
            "rotationStrength": rotation_strength,
            "institutionalActivity": inst_activity,
            "marketSentiment": sentiment,
            "styleBias": "价值" if "金融" in sectors else "成长",
            "rotationWarning": len(warnings) > 0,
        }

        return AgentResult(
            node=self.node,
            status=status,
            confidence="MEDIUM" if status == "WARN" else "HIGH",
            reasons=reasons,
            warnings=warnings,
            data=data,
            audit_id=self._audit(),
        )
