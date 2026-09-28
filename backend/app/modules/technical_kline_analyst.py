from __future__ import annotations

from typing import Any, Dict

from ..core.kline_service import get_multi_period_kline_payloads
from ..core.technical_kline_agent import build_technical_kline_analysis
from ..core.tushare_chip_service import get_tushare_chip_payload
from .base_agent import BaseAgent, AgentResult


class TechnicalKlineAnalystAgent(BaseAgent):
    node = "technical_kline_analyst"
    name = "Technical Kline Analyst"
    stage = "analysis"
    rule_engine_only = True

    def process(self, run_context: Dict[str, Any], prior_outputs: Dict[str, Any]) -> AgentResult:
        symbol = str(run_context.get("stockCode") or run_context.get("symbol") or "")
        payloads = get_multi_period_kline_payloads(symbol)
        chip_payload = get_tushare_chip_payload(symbol)
        config = run_context.get("technicalKlineConfig")
        analysis = build_technical_kline_analysis(symbol, payloads, config if isinstance(config, dict) else None, chip_payload)
        status = str(analysis.get("status") or "WARN")
        bias = str(analysis.get("technicalBias") or "INSUFFICIENT_DATA")
        quality = analysis.get("dataQuality") or {}

        missing_data = list(quality.get("issues") or [])
        warnings = list(analysis.get("risks") or [])
        reasons = [
            analysis.get("summaryForDownstream") or "技术面 K 线分析未生成摘要。",
            f"真实 K 线样本：日线 {quality.get('dailyCount', 0)}，周线 {quality.get('weeklyCount', 0)}，月线 {quality.get('monthlyCount', 0)}。",
        ]

        return AgentResult(
            node=self.node,
            status=status,
            allowed_actions=["REVIEW_ONLY"],
            blocked_actions=list(analysis.get("forbiddenActions") or []),
            hard_stop=False,
            final_decision_cap="NO_DIRECT_TRADE_ACTION",
            confidence=_confidence_label(analysis.get("confidence")),
            reasons=reasons,
            missing_data=missing_data,
            warnings=warnings,
            data=analysis,
            audit_id=self._audit(),
            skipped_reason="真实 K 线不足，技术面 Agent 跳过。" if bias == "INSUFFICIENT_DATA" else None,
        )


def _confidence_label(value: Any) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value >= 0.75:
            return "HIGH"
        if value >= 0.45:
            return "MEDIUM"
        return "LOW"
    return "UNKNOWN"
