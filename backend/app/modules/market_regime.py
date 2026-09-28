from __future__ import annotations
from typing import Any, Dict

from .base_agent import BaseAgent, AgentResult


class MarketRegimeAgent(BaseAgent):
    node = "market_regime"
    name = "Market Regime"
    stage = "analysis"
    rule_engine_only = True

    def process(self, run_context: Dict[str, Any], prior_outputs: Dict[str, Any]) -> AgentResult:
        market_data = run_context.get("marketData") or {}
        quote = market_data.get("quote") or {}
        auxiliary = run_context.get("auxiliaryData") or {}

        quote_ready = market_data.get("status") == "READY" and str(market_data.get("provider") or "") != "mock"
        change_percent = _number(quote.get("changePercent") or market_data.get("changePercent"))
        volume = _number(quote.get("volume") or market_data.get("volume"))
        amount = _number(quote.get("amount") or (market_data.get("extra") or {}).get("amount"))

        sentiment = _sentiment_from_change(change_percent) if quote_ready else "NEUTRAL"
        vol_index = _volatility_index(change_percent) if quote_ready else 0
        liq_index = _liquidity_index(volume, amount) if quote_ready else 0
        inst_activity = _institution_activity(auxiliary)
        retail = _retail_sentiment(change_percent, inst_activity) if quote_ready else "NEUTRAL"
        sectors = _sector_rotation(auxiliary)
        macro = _macro_indicators(auxiliary)

        provenance = {
            "marketSentiment": _source("DERIVED" if quote_ready else "MISSING", market_data.get("provider"), "由当前标的涨跌幅推算市场情绪代理值"),
            "volatilityIndex": _source("DERIVED" if quote_ready else "MISSING", market_data.get("provider"), "由当前标的涨跌幅绝对值归一化推算，不是外部波动率指数"),
            "liquidityIndex": _source("DERIVED" if quote_ready and (volume is not None or amount is not None) else "MISSING", market_data.get("provider"), "由成交量/成交额归一化推算"),
            "institutionalActivity": _source("DERIVED" if _aux_ready(auxiliary, "moneyflow") else "MISSING", _aux_provider(auxiliary, "moneyflow"), "由资金流接口推算；无资金流时不展示模板结论"),
            "retailSentiment": _source("DERIVED" if quote_ready else "MISSING", market_data.get("provider"), "由涨跌幅与资金流代理推算"),
            "sectorRotation": _source("LIVE" if sectors else "MISSING", _aux_provider(auxiliary, "moneyflow"), "需要行业/板块或资金流数据；未接入时为空"),
            "macroIndicators": _source("LIVE" if macro else "MISSING", _aux_provider(auxiliary, "macro"), "来自宏观数据源；未接入时不再回填 2.8/4.5/3.65 模板值"),
        }

        reasons = [
            f"市场情绪: {sentiment}，波动率指数: {vol_index}",
            f"机构活跃度: {inst_activity}，散户情绪: {retail}",
            f"流动性指数: {liq_index}",
            f"板块轮动方向: {', '.join(sectors) if sectors else '未接入'}",
            f"宏观: CPI {macro.get('cpi', 'N/A')}%, GDP {macro.get('gdp', 'N/A')}%",
        ]

        warnings = []
        if not quote_ready:
            warnings.append("实时行情不可用，市场情绪/波动率/流动性不再使用模板值")
        if not macro:
            warnings.append("宏观指标未接入真实数据源，页面应显示未接入")
        if not sectors:
            warnings.append("板块轮动未接入真实行业/板块数据源")
        if quote_ready and vol_index > 70:
            warnings.append("波动率偏高，市场情绪可能极端化")
        elif quote_ready and vol_index < 30:
            warnings.append("波动率极低，可能酝酿突破")

        data = {
            "marketSentiment": sentiment,
            "volatilityIndex": vol_index,
            "liquidityIndex": liq_index,
            "institutionalActivity": inst_activity,
            "retailSentiment": retail,
            "sectorRotation": sectors,
            "macroIndicators": macro,
            "regimeClassification": "震荡" if 30 <= vol_index <= 70 else ("高波动" if vol_index > 70 else "低波动"),
            "provenance": provenance,
        }

        return AgentResult(
            node=self.node,
            status="PASS" if quote_ready else "WARN",
            confidence="MEDIUM" if quote_ready else "LOW",
            reasons=reasons,
            warnings=warnings,
            data=data,
            audit_id=self._audit(),
        )


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().rstrip("%"))
        except ValueError:
            return None
    return None


def _sentiment_from_change(change_percent: float | None) -> str:
    if change_percent is None:
        return "NEUTRAL"
    if change_percent >= 1.5:
        return "BULLISH"
    if change_percent <= -1.5:
        return "BEARISH"
    return "NEUTRAL"


def _volatility_index(change_percent: float | None) -> int:
    if change_percent is None:
        return 0
    return int(max(5, min(95, 25 + abs(change_percent) * 14)))


def _liquidity_index(volume: float | None, amount: float | None) -> int:
    import math

    base = amount if amount and amount > 0 else volume
    if not base:
        return 0
    return int(max(5, min(95, 10 + math.log10(base + 1) * 8)))


def _aux_ready(auxiliary: Dict[str, Any], key: str) -> bool:
    item = auxiliary.get(key) if isinstance(auxiliary, dict) else None
    return isinstance(item, dict) and item.get("status") == "READY" and not item.get("error")


def _aux_provider(auxiliary: Dict[str, Any], key: str) -> str:
    item = auxiliary.get(key) if isinstance(auxiliary, dict) else None
    return str(item.get("provider") or "") if isinstance(item, dict) else ""


def _aux_records(auxiliary: Dict[str, Any], key: str) -> list[Dict[str, Any]]:
    item = auxiliary.get(key) if isinstance(auxiliary, dict) else None
    if not isinstance(item, dict) or item.get("status") != "READY":
        return []
    records = item.get("records")
    if isinstance(records, list):
        return [record for record in records if isinstance(record, dict)]
    sample = item.get("sample")
    return [sample] if isinstance(sample, dict) else []


def _institution_activity(auxiliary: Dict[str, Any]) -> str:
    records = _aux_records(auxiliary, "moneyflow")
    if not records:
        return "LOW"
    sample = records[0]
    score = 0.0
    for key in ("net_mf_amount", "net_amount", "主力净流入", "大单净额", "main_net_inflow"):
        value = _number(sample.get(key))
        if value is not None:
            score = value
            break
    if score > 0:
        return "HIGH"
    if score < 0:
        return "LOW"
    return "MEDIUM"


def _retail_sentiment(change_percent: float | None, institutional_activity: str) -> str:
    if change_percent is None:
        return "NEUTRAL"
    if change_percent > 2 and institutional_activity != "HIGH":
        return "OPTIMISTIC"
    if change_percent < -2:
        return "PESSIMISTIC"
    return "NEUTRAL"


def _sector_rotation(auxiliary: Dict[str, Any]) -> list[str]:
    records = _aux_records(auxiliary, "moneyflow")
    sectors: list[str] = []
    for record in records[:5]:
        for key in ("industry", "sector", "板块", "行业"):
            value = record.get(key)
            if value and str(value) not in sectors:
                sectors.append(str(value))
    return sectors


def _macro_indicators(auxiliary: Dict[str, Any]) -> Dict[str, float]:
    macro: Dict[str, float] = {}
    for record in _aux_records(auxiliary, "macro"):
        api = str(record.get("_api_name") or "").lower()
        if api == "cn_cpi" and "cpi" not in macro:
            value = _first_number(record, ("nt_yoy", "cpi", "value", "yoy"))
            if value is not None:
                macro["cpi"] = round(value, 2)
        elif api == "cn_gdp" and "gdp" not in macro:
            value = _first_number(record, ("gdp_yoy", "gdp", "yoy", "pi_yoy"))
            if value is not None:
                macro["gdp"] = round(value, 2)
        elif api == "shibor_lpr" and "policyRate" not in macro:
            value = _first_number(record, ("1y", "lpr1y", "rate_1y", "one_year"))
            if value is not None:
                macro["policyRate"] = round(value, 2)
    return macro


def _first_number(record: Dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = _number(record.get(key))
        if value is not None:
            return value
    return None


def _source(source_type: str, provider: Any, note: str) -> Dict[str, Any]:
    return {
        "sourceType": source_type,
        "provider": str(provider or ""),
        "note": note,
    }
