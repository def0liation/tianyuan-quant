from __future__ import annotations

from typing import Any, Dict, List

from ..core.kline_service import get_multi_period_kline_payloads
from ..core.technical_kline_agent import build_technical_kline_analysis
from ..core.tushare_chip_service import get_tushare_chip_payload
from .base_agent import BaseAgent, AgentResult
from .market_regime import MarketRegimeAgent


class MarketTechnicalAnalystAgent(BaseAgent):
    node = "market_technical_analyst"
    name = "Market Technical Analyst"
    stage = "analysis"
    rule_engine_only = True

    def process(self, run_context: Dict[str, Any], prior_outputs: Dict[str, Any]) -> AgentResult:
        market_result = MarketRegimeAgent().process(run_context, prior_outputs)
        market = dict(market_result.data or {})

        symbol = str(run_context.get("stockCode") or run_context.get("symbol") or "")
        payloads = get_multi_period_kline_payloads(symbol)
        chip_payload = get_tushare_chip_payload(symbol)
        config = run_context.get("technicalKlineConfig")
        technical = build_technical_kline_analysis(
            symbol,
            payloads,
            config if isinstance(config, dict) else None,
            chip_payload,
        )

        alignment = _alignment(market, technical)
        confidence_value = _combined_confidence(market_result.confidence, technical)
        status = _combined_status(str(market_result.status or "WARN"), str(technical.get("status") or "WARN"))
        summary = _summary(market, technical, alignment, confidence_value)
        warnings = _unique(
            list(market_result.warnings or [])
            + list(technical.get("risks") or [])
            + _alignment_warnings(alignment)
        )
        quality = technical.get("dataQuality") if isinstance(technical.get("dataQuality"), dict) else {}
        missing_data = _unique(list(market_result.missing_data or []) + list(quality.get("issues") or []))

        data = {
            "agent": self.node,
            "status": status,
            "market": market,
            "technicalKline": technical,
            "alignment": alignment,
            "confidence": confidence_value,
            "summaryForDownstream": summary,
            "warnings": warnings,
        }

        return AgentResult(
            node=self.node,
            status=status,
            allowed_actions=["REVIEW_ONLY"],
            blocked_actions=list(technical.get("forbiddenActions") or []),
            hard_stop=False,
            final_decision_cap="NO_DIRECT_TRADE_ACTION",
            confidence=_confidence_label(confidence_value),
            reasons=[summary],
            missing_data=missing_data,
            warnings=warnings,
            data=data,
            audit_id=self._audit(),
            skipped_reason=(
                "technical_kline_insufficient_data"
                if str(technical.get("technicalBias") or "").upper() == "INSUFFICIENT_DATA"
                else None
            ),
        )


def _combined_status(market_status: str, technical_status: str) -> str:
    statuses = {market_status.upper(), technical_status.upper()}
    if "FAILED" in statuses:
        return "WARN"
    if statuses <= {"PASS"}:
        return "PASS"
    return "WARN"


def _alignment(market: Dict[str, Any], technical: Dict[str, Any]) -> str:
    sentiment = str(market.get("marketSentiment") or "NEUTRAL").upper()
    bias = str(technical.get("technicalBias") or "UNKNOWN").upper()
    if bias == "INSUFFICIENT_DATA":
        return "TECHNICAL_INSUFFICIENT_DATA"
    if sentiment == "BULLISH" and bias == "BULLISH":
        return "ALIGNED_BULLISH"
    if sentiment == "BEARISH" and bias == "BEARISH":
        return "ALIGNED_BEARISH"
    if sentiment in {"BULLISH", "BEARISH"} and bias in {"BULLISH", "BEARISH"} and sentiment != bias:
        return "CONFLICT"
    return "NEUTRAL_OR_MIXED"


def _combined_confidence(market_confidence: Any, technical: Dict[str, Any]) -> float:
    technical_confidence = _number(technical.get("confidence"))
    if technical_confidence is None:
        technical_confidence = 0.0
    market_score = {"HIGH": 0.75, "MEDIUM": 0.55, "LOW": 0.35}.get(str(market_confidence or "").upper(), 0.45)
    return round(max(0.0, min(0.92, (technical_confidence * 0.65) + (market_score * 0.35))), 4)


def _summary(market: Dict[str, Any], technical: Dict[str, Any], alignment: str, confidence: float) -> str:
    return (
        "Market/technical fused context: "
        f"marketSentiment={market.get('marketSentiment', 'UNKNOWN')}; "
        f"regime={market.get('regimeClassification', 'UNKNOWN')}; "
        f"technicalBias={technical.get('technicalBias', 'UNKNOWN')}; "
        f"alignment={alignment}; confidence={confidence:.0%}. "
        f"{technical.get('summaryForDownstream', '')}"
    ).strip()


def _alignment_warnings(alignment: str) -> List[str]:
    if alignment == "CONFLICT":
        return ["market_technical_conflict"]
    if alignment == "TECHNICAL_INSUFFICIENT_DATA":
        return ["technical_kline_insufficient_data"]
    return []


def _confidence_label(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "UNKNOWN"
    if number >= 0.75:
        return "HIGH"
    if number >= 0.45:
        return "MEDIUM"
    return "LOW"


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().rstrip("%"))
        except ValueError:
            return None
    return None


def _unique(values: List[Any]) -> List[Any]:
    result: List[Any] = []
    seen: set[str] = set()
    for value in values:
        key = str(value)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result
