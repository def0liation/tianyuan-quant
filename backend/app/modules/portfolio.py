from __future__ import annotations
from typing import Any, Dict

from .base_agent import BaseAgent, AgentResult


class PortfolioAgent(BaseAgent):
    node = "portfolio"
    name = "Portfolio"
    stage = "risk"
    rule_engine_only = True

    def process(self, run_context: Dict[str, Any], prior_outputs: Dict[str, Any]) -> AgentResult:
        portfolio = run_context.get("portfolio", {})
        user_position = run_context.get("userPosition", {})

        current_pos = user_position.get("currentPositionRatio", portfolio.get("singleStockPosition", 0.12))
        single_cap = portfolio.get("singleStockPositionCap", 0.15)
        max_drawdown = user_position.get("maxAcceptableDrawdown", portfolio.get("maxDrawdownConstraint", 0.08))
        allow_add = portfolio.get("allowAddPosition", False)
        holdings = portfolio.get("holdings") if isinstance(portfolio.get("holdings"), list) else []
        has_real_holdings = bool(holdings)
        industry = _industry_exposure_from_holdings(holdings) if has_real_holdings else {}
        theme_conc = _theme_concentration_from_holdings(holdings) if has_real_holdings else 0.0
        risk_factor_conc = _same_risk_concentration_from_holdings(holdings) if has_real_holdings else 0.0

        reasons = [
            f"当前单票仓位: {current_pos:.0%}，上限: {single_cap:.0%}",
            "组合敞口: 已接入持仓明细" if has_real_holdings else "组合敞口: 未接入账户或持仓明细，仅使用用户输入的单票仓位",
        ]

        warnings = []
        blocked = []

        remaining = single_cap - current_pos
        if remaining <= 0.03:
            allow_add = False
            warnings.append(f"加仓空间仅剩 {remaining:.0%}，容错率极低")
            reasons.append("单票仓位接近上限，禁止加仓")

        if has_real_holdings and any(v > 0.3 for v in industry.values()):
            warnings.append("存在行业集中风险")

        if has_real_holdings and theme_conc > 0.25:
            warnings.append(f"主题集中度 {theme_conc:.0%}，偏高")
        if not has_real_holdings:
            warnings.append("未接入真实持仓明细，行业敞口、主题集中度、同质风险因子不可计算")

        if not allow_add:
            blocked = ["ADD_CANDIDATE"]
            reasons.append("不建议对该标的继续加仓")

        data = {
            "currentTotalPosition": current_pos,
            "singleStockPosition": current_pos,
            "singleStockPositionCap": single_cap,
            "industryExposure": industry,
            "styleExposure": _style_exposure_from_holdings(holdings) if has_real_holdings else {},
            "themeConcentration": theme_conc,
            "sameRiskFactorConcentration": risk_factor_conc,
            "maxDrawdownConstraint": max_drawdown,
            "allowAddPosition": allow_add,
            "allowHeavyPosition": bool(not blocked),
            "restrictionReasons": warnings,
            "portfolioCoverage": "HOLDINGS_CONNECTED" if has_real_holdings else "USER_INPUT_ONLY",
            "provenance": {
                "sourceType": "USER_INPUT" if not has_real_holdings else "DERIVED",
                "note": "公共行情无法获取用户真实账户持仓；未导入持仓时不再展示模板行业敞口",
            },
        }

        return AgentResult(
            node=self.node,
            status="WARN" if blocked else "PASS",
            allowed_actions=["WAIT", "REVIEW_ONLY", "HOLD"],
            blocked_actions=blocked,
            hard_stop=False,
            confidence="MEDIUM",
            reasons=reasons,
            warnings=warnings,
            data=data,
            audit_id=self._audit(),
        )


def _holding_weight(holding: Dict[str, Any]) -> float:
    for key in ("positionRatio", "weight", "ratio", "currentPositionRatio"):
        value = holding.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return max(0.0, float(value))
    return 0.0


def _group_exposure(holdings: list[Any], key: str) -> Dict[str, float]:
    exposure: Dict[str, float] = {}
    for item in holdings:
        if not isinstance(item, dict):
            continue
        label = str(item.get(key) or "").strip()
        weight = _holding_weight(item)
        if label and weight > 0:
            exposure[label] = exposure.get(label, 0.0) + weight
    total = sum(exposure.values())
    if total > 1.0:
        exposure = {label: value / total for label, value in exposure.items()}
    return {label: round(value, 4) for label, value in exposure.items()}


def _industry_exposure_from_holdings(holdings: list[Any]) -> Dict[str, float]:
    return _group_exposure(holdings, "industry")


def _style_exposure_from_holdings(holdings: list[Any]) -> Dict[str, float]:
    return _group_exposure(holdings, "style")


def _theme_concentration_from_holdings(holdings: list[Any]) -> float:
    exposure = _group_exposure(holdings, "theme")
    return round(max(exposure.values(), default=0.0), 4)


def _same_risk_concentration_from_holdings(holdings: list[Any]) -> float:
    exposure = _group_exposure(holdings, "riskFactor")
    return round(max(exposure.values(), default=0.0), 4)
