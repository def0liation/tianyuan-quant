from __future__ import annotations
from typing import Any, Dict

from ..core.quant_engine_modes import (
    quant_engine_profile_from_run,
    split_missing_data_for_mode,
)
from .base_agent import BaseAgent, AgentResult


_QIAM_SCORE_DEFAULTS = {
    "expectedPayoffQuality": 0.65,
    "regimeFit": 0.7,
    "momentumQuality": 0.55,
    "volatilityCondition": 0.6,
    "liquidityAdjustedSignal": 0.58,
    "modelConfidenceRaw": 0.75,
    "modelConfidenceFinal": 0.62,
    "overfitRisk": 0.2,
    "distributionDrift": 0.15,
    "decisionEffect": 0.8,
}

_QIAM_PENDING_MARKERS = ("QIAM 输入尚未完成", "QIAM 输入尚未完成拉取")


class QiamAgent(BaseAgent):
    node = "qiam"
    name = "QIAM"
    stage = "analysis"
    rule_engine_only = True

    DATA_GAP_DISCOUNT = {
        "Level-2": 0.60,
        "Level2": 0.60,
        "L2": 0.60,
        "二级行情": 0.60,
        "Level-2 成交量": 0.60,
        "盘口深度": 0.70,
        "资金流分解": 0.75,
        "筹码/股东户数": 0.80,
        "模型版本": 0.50,
        "样本外验证": 0.50,
        "walk-forward": 0.70,
        "分布漂移检测": 0.75,
    }

    MODEL_RISK_DISCOUNT = {
        "regime_fit_UNKNOWN": 0.70,
        "volatility_DANGEROUS": 0.50,
        "liquidity_UNKNOWN": 0.60,
        "overfit_HIGH": 0.40,
        "drift_SEVERE": 0.30,
    }

    def process(self, run_context: Dict[str, Any], prior_outputs: Dict[str, Any]) -> AgentResult:
        quant_profile = quant_engine_profile_from_run(run_context)
        quant_mode = quant_profile["mode"]
        qiam = run_context.get("qiam", {})
        if not isinstance(qiam, dict):
            qiam = {}
        dvg_output = _prior_output(prior_outputs, "dvg_gate", "dvg_evidence_gate")
        dvg_data = {**(run_context.get("dvg", {}) or {}), **_payload_data(dvg_output)}
        technical_data = _technical_data_for_qiam(run_context, prior_outputs)
        technical_constraint = _technical_constraint(technical_data)

        raw_buy = qiam.get("rawBuySuitability", "NEUTRAL")
        dvg_perm = dvg_data.get("qiamPermission", "ALLOW_WITH_DISCOUNT")

        critical_missing = _as_list(dvg_data.get("criticalMissingData", []))
        raw_missing_value = qiam.get("missingData")
        raw_missing_data = _as_list(raw_missing_value if raw_missing_value is not None else ["Level-2", "盘口深度"])
        if _qiam_looks_pending_seed(qiam) and _quant_engine_submodules_completed(run_context, prior_outputs):
            raw_missing_data = [item for item in raw_missing_data if not _is_qiam_pending_marker(item)]
            raw_missing_data = _unique_list(raw_missing_data + _factor_missing_data_for_qiam(run_context, prior_outputs))
        missing_data, ignored_missing_data = split_missing_data_for_mode(
            raw_missing_data,
            quant_mode,
            run_context.get("taskType"),
        )

        discount = 1.0
        downgrades = []

        if dvg_perm == "BLOCKED" or dvg_perm == "REVIEW_ONLY":
            discount = 0.0
            downgrades.append(f"DVG {dvg_perm}: discount_factor = 0")
        else:
            for item in missing_data:
                for key, factor in self.DATA_GAP_DISCOUNT.items():
                    if key in str(item):
                        discount *= factor
                        downgrades.append(f"缺少{item}: ×{factor:.2f}")
                        break
                else:
                    discount *= 0.85
                    downgrades.append(f"缺少{item}: ×0.85")

            if dvg_perm == "ALLOW_WITH_DISCOUNT":
                discount *= 0.70
                downgrades.append("DVG ALLOW_WITH_DISCOUNT: ×0.70")

        if technical_constraint["appliedFactor"] < 1.0:
            discount *= technical_constraint["appliedFactor"]
            downgrades.append(technical_constraint["downgradeReason"])

        if discount >= 0.85:
            final_buy = raw_buy
        elif discount >= 0.60:
            final_buy = "NEUTRAL" if raw_buy == "FAVORABLE" else raw_buy
        elif discount >= 0.40:
            final_buy = "REVIEW_ONLY" if raw_buy != "BLOCK_BUY" else "BLOCK_BUY"
        elif discount > 0:
            final_buy = "REVIEW_ONLY"
        else:
            final_buy = "BLOCK_BUY"

        bottom_adjustment = _bottom_research_adjustment(
            run_context,
            final_buy,
            str(dvg_perm or ""),
            technical_constraint,
            discount,
        )
        if bottom_adjustment["applied"]:
            final_buy = bottom_adjustment["afterFinalBuySuitability"]
            if bottom_adjustment["direction"] == "DOWN":
                downgrades.append(bottom_adjustment["reason"])

        reasons = [
            f"原始买入适宜性: {raw_buy}",
            f"综合折扣因子: {discount:.2f} ({len(downgrades)}项折扣)",
            f"最终买入适宜性: {final_buy}",
        ]
        if bottom_adjustment["observed"]:
            reasons.append(
                "MFE/MAE路径研究校准: {direction} {before}→{after}; {reason}".format(
                    direction=bottom_adjustment["direction"],
                    before=bottom_adjustment["beforeFinalBuySuitability"],
                    after=bottom_adjustment["afterFinalBuySuitability"],
                    reason=bottom_adjustment["reason"],
                )
            )
        reasons.extend(downgrades[:3])

        warnings = [f"折扣后: raw {raw_buy} → final {final_buy}"]
        if final_buy == "NEUTRAL":
            warnings.append("QIAM 不构成买入信号，仅作量化校准")
        if final_buy == "BLOCK_BUY":
            warnings.append("QIAM 阻断买入，禁止正向使用")
        if dvg_perm == "ALLOW_WITH_DISCOUNT":
            warnings.append("DVG 限制 QIAM 需折价运行")
        if technical_constraint["observed"]:
            warnings.append("Technical Kline and MFE/MAE Path Research can calibrate QIAM only within guarded one-step limits.")
        if bottom_adjustment["observed"]:
            warnings.append("MFE/MAE Path Research participates in controlled one-step QIAM calibration; it cannot create trade permission.")
        if ignored_missing_data:
            warnings.append("低频中长线模式下，Level-2/盘口/分时/逐笔等高频缺失项只记录为不适用，不进入 QIAM 折扣。")
        probability_context = {**run_context, "dvg": {**(run_context.get("dvg") or {}), **dvg_data}}
        probability_up, probability_sideways, probability_down = _derive_probability_bands(
            probability_context,
            qiam,
            final_buy,
            discount,
            missing_data,
        )
        remediation_items = _build_remediation_items(
            missing_data,
            critical_missing,
            dvg_perm,
            technical_constraint,
            downgrades,
        )

        data = {
            "calculationMode": "STANDARD",
            "quantEngineMode": quant_mode,
            "parameterProfile": quant_profile["parameterProfile"],
            "dvgPermission": dvg_perm != "BLOCKED",
            "rawBuySuitability": raw_buy,
            "discountFactor": discount,
            "finalBuySuitability": final_buy,
            "probabilityBandUp": probability_up,
            "probabilityBandSideways": probability_sideways,
            "probabilityBandDown": probability_down,
            "probabilitySource": "RULE_DERIVED",
            "expectedPayoffQuality": _qiam_score_value(qiam, "expectedPayoffQuality"),
            "regimeFit": _qiam_score_value(qiam, "regimeFit"),
            "momentumQuality": _qiam_score_value(qiam, "momentumQuality"),
            "volatilityCondition": _qiam_score_value(qiam, "volatilityCondition"),
            "liquidityAdjustedSignal": _qiam_score_value(qiam, "liquidityAdjustedSignal"),
            "modelConfidenceRaw": _qiam_score_value(qiam, "modelConfidenceRaw"),
            "modelConfidenceFinal": _qiam_score_value(qiam, "modelConfidenceFinal"),
            "overfitRisk": _qiam_score_value(qiam, "overfitRisk"),
            "distributionDrift": _qiam_score_value(qiam, "distributionDrift"),
            "decisionEffect": _qiam_score_value(qiam, "decisionEffect"),
            "missingData": missing_data,
            "ignoredMissingData": ignored_missing_data,
            "downgradeReasons": downgrades,
            "remediationItems": remediation_items,
            "technicalKlineConstraint": technical_constraint,
            "bottomResearchAdjustment": bottom_adjustment,
            "mfeMaePathResearchAdjustment": bottom_adjustment,
        }

        return AgentResult(
            node=self.node,
            status="PASS" if final_buy == "FAVORABLE" else ("WARN" if final_buy == "NEUTRAL" else "REVIEW_ONLY"),
            allowed_actions=([] if final_buy == "FAVORABLE" else ["REVIEW_ONLY"]),
            blocked_actions=["BUY_CANDIDATE", "ADD_CANDIDATE"] if final_buy == "BLOCK_BUY" else [],
            hard_stop=(final_buy == "BLOCK_BUY"),
            confidence="HIGH" if final_buy == "FAVORABLE" else "MEDIUM",
            reasons=reasons,
            missing_data=missing_data,
            warnings=warnings,
            data=data,
            audit_id=self._audit(),
        )


def _prior_output(prior_outputs: Dict[str, Any], *keys: str) -> Dict[str, Any]:
    for key in keys:
        value = prior_outputs.get(key)
        if isinstance(value, dict) and value:
            return value
    return {}


def _payload_data(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def _technical_data_for_qiam(run_context: Dict[str, Any], prior_outputs: Dict[str, Any]) -> Dict[str, Any]:
    canonical = run_context.get("technicalKline")
    canonical_data = canonical if isinstance(canonical, dict) else {}
    fused_output = _prior_output(prior_outputs, "market_technical_analyst")
    fused_data = _payload_data(fused_output)
    fused_technical = fused_data.get("technicalKline") if isinstance(fused_data.get("technicalKline"), dict) else {}
    technical_output = _prior_output(prior_outputs, "technical_kline_analyst")
    prior_data = _payload_data(technical_output)
    prior_data = {**prior_data, **fused_technical}

    if _verified_technical_kline(canonical_data):
        return {**prior_data, **canonical_data}
    return {**canonical_data, **prior_data}


def _verified_technical_kline(technical: Dict[str, Any]) -> bool:
    if not isinstance(technical, dict):
        return False
    quality = technical.get("dataQuality") or {}
    if not isinstance(quality, dict):
        return False
    return (
        technical.get("agent") == "technical_kline_analyst"
        and technical.get("status") in {"PASS", "WARN"}
        and quality.get("provider") == "tushare"
        and quality.get("dataMode") == "LIVE"
        and _int_value(quality.get("dailyCount")) >= 30
    )


def _int_value(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return 0
    return 0


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _unique_list(values: list[Any]) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for value in values:
        key = str(value)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _qiam_score_value(qiam: Dict[str, Any], field: str) -> float:
    default = _QIAM_SCORE_DEFAULTS[field]
    value = qiam.get(field)
    number = _number(value)
    if number is None:
        return default
    if number == 0 and _qiam_looks_pending_seed(qiam):
        return default
    return number


def _qiam_looks_pending_seed(qiam: Dict[str, Any]) -> bool:
    source = str(qiam.get("probabilitySource") or "").upper()
    if source == "PENDING":
        return True
    missing_data = qiam.get("missingData") or []
    if not isinstance(missing_data, list):
        missing_data = [missing_data]
    return any(_is_qiam_pending_marker(item) for item in missing_data)


def _is_qiam_pending_marker(value: Any) -> bool:
    return any(marker in str(value) for marker in _QIAM_PENDING_MARKERS)


def _quant_engine_submodules_completed(run_context: Dict[str, Any], prior_outputs: Dict[str, Any]) -> bool:
    factor_slicing = _merged_context_output(run_context, prior_outputs, "factorSlicing", "factor_slicing")
    factor_engine = _merged_context_output(run_context, prior_outputs, "factorEngine", "factor_engine")
    calculation_authority = _merged_context_output(
        run_context,
        prior_outputs,
        "calculationAuthority",
        "calculation_authority",
    )
    return (
        _factor_slicing_completed(factor_slicing)
        and _factor_engine_completed(factor_engine)
        and _calculation_authority_completed(calculation_authority)
    )


def _merged_context_output(
    run_context: Dict[str, Any],
    prior_outputs: Dict[str, Any],
    context_key: str,
    prior_key: str,
) -> Dict[str, Any]:
    canonical = run_context.get(context_key)
    canonical_data = canonical if isinstance(canonical, dict) else {}
    prior_data = _payload_data(_prior_output(prior_outputs, prior_key))
    return {**prior_data, **canonical_data}


def _factor_missing_data_for_qiam(run_context: Dict[str, Any], prior_outputs: Dict[str, Any]) -> list[Any]:
    factor_slicing = _merged_context_output(run_context, prior_outputs, "factorSlicing", "factor_slicing")
    return [
        item
        for item in _as_list(factor_slicing.get("missingFactorData", []))
        if not _is_qiam_pending_marker(item)
    ]


def _factor_slicing_completed(data: Dict[str, Any]) -> bool:
    if not isinstance(data, dict) or not data:
        return False
    source = str(data.get("factorDataSource") or (data.get("provenance") or {}).get("sourceType") or "").upper()
    if not source or "PENDING" in source:
        return False
    missing = _as_list(data.get("missingFactorData", []))
    if any(_is_qiam_pending_marker(item) for item in missing):
        return False
    factors = data.get("factors")
    factor_count = _int_value(data.get("factorCount"))
    return (isinstance(factors, list) and len(factors) > 0) or factor_count > 0


def _factor_engine_completed(data: Dict[str, Any]) -> bool:
    if not isinstance(data, dict) or not data:
        return False
    mode = str(data.get("engineMode") or data.get("mode") or "").upper()
    if not mode or "PENDING" in mode:
        return False
    return mode not in {"WAIT", "CREATED"}


def _calculation_authority_completed(data: Dict[str, Any]) -> bool:
    if not isinstance(data, dict) or not data:
        return False
    status = str(data.get("calculationToolStatus") or data.get("authorityStatus") or "").upper()
    if "PENDING" in status or status in {"WAIT", "CREATED"}:
        return False
    return True


def _build_remediation_items(
    missing_data: list[Any],
    critical_missing: list[Any],
    dvg_permission: str,
    technical_constraint: Dict[str, Any],
    downgrade_reasons: list[str],
) -> list[Dict[str, str]]:
    items: list[Dict[str, str]] = []

    for missing in missing_data:
        missing_text = str(missing)
        reason = _matching_downgrade_reason(downgrade_reasons, missing_text) or f"缺少{missing_text}"
        if "QIAM" in missing_text and "尚未完成" in missing_text:
            _append_remediation(
                items,
                reason=reason,
                category="QIAM_INPUT",
                severity="BLOCKING",
                action="重新运行 Quant Engine，确认 factor_slicing、factor_engine、calculation_authority 均已完成并写回；不要复用创建态或运行中的 QIAM 占位结果。",
                verification="刷新运行后，QIAM missingData 不再包含该项，probabilitySource=RULE_DERIVED，Raw/Final 置信和分项评分不再全部为 0%。",
            )
        else:
            _append_remediation(
                items,
                reason=reason,
                category="DATA_GAP",
                severity="WARN",
                action="补齐该缺失数据源后重跑 Quant Engine；若当前是低频中长线模式，先确认该项是否应被 ignoredMissingData 排除。",
                verification="QIAM 折扣原因中该缺失项消失，discountFactor 回升，ignoredMissingData 只保留当前模式不适用的高频数据。",
            )

    dvg_perm = str(dvg_permission or "").upper()
    if dvg_perm == "ALLOW_WITH_DISCOUNT":
        detail = "、".join(str(item) for item in critical_missing[:3]) or "DVG 仍有未完全通过的输入"
        _append_remediation(
            items,
            reason="DVG ALLOW_WITH_DISCOUNT: ×0.70",
            category="DVG",
            severity="WARN",
            action=f"查看 DVG 数据门禁详情并补齐或复核：{detail}；修复后重跑 DVG 与 Quant Engine。",
            verification="DVG qiamPermission 变为 ALLOW，QIAM 折扣原因中不再出现 ALLOW_WITH_DISCOUNT。",
        )
    elif dvg_perm in {"BLOCKED", "REVIEW_ONLY"}:
        detail = "、".join(str(item) for item in critical_missing[:3]) or "DVG 关键门禁未通过"
        _append_remediation(
            items,
            reason=f"DVG {dvg_perm}: discount_factor = 0",
            category="DVG",
            severity="BLOCKING",
            action=f"先修复 DVG 关键缺失或冲突项：{detail}；在门禁放行前不要使用 QIAM 作为正向信号。",
            verification="DVG qiamPermission 变为 ALLOW 或 ALLOW_WITH_DISCOUNT，QIAM finalBuySuitability 不再因 DVG 被硬阻断。",
        )

    technical_reason = str(technical_constraint.get("downgradeReason") or "")
    if technical_constraint.get("observed") and technical_reason:
        _append_remediation(
            items,
            reason=technical_reason,
            category="TECHNICAL_KLINE",
            severity="WARN",
            action="重跑 Technical Kline Analyst，确认 Tushare 日/周/月 K 线为 LIVE 且日线样本不少于 30；若 run_context 已有通过校验的 canonical technicalKline，应优先使用该结果。",
            verification="QIAM technicalKlineConstraint confidence 高于 0.45，或 bias 不再是 INSUFFICIENT_DATA/BEARISH 导致的折扣原因。",
        )

    return items


def _matching_downgrade_reason(downgrade_reasons: list[str], needle: str) -> str | None:
    for reason in downgrade_reasons:
        if needle in reason:
            return reason
    return None


def _append_remediation(
    items: list[Dict[str, str]],
    *,
    reason: str,
    category: str,
    action: str,
    verification: str,
    severity: str,
) -> None:
    key = (category, reason)
    if any((item.get("category"), item.get("reason")) == key for item in items):
        return
    items.append(
        {
            "reason": reason,
            "category": category,
            "action": action,
            "verification": verification,
            "severity": severity,
        }
    )


_SUITABILITY_ORDER = ["BLOCK_BUY", "REVIEW_ONLY", "NEUTRAL", "FAVORABLE"]


def _bottom_research_adjustment(
    run_context: Dict[str, Any],
    final_buy: str,
    dvg_permission: str,
    technical_constraint: Dict[str, Any],
    discount: float,
) -> Dict[str, Any]:
    bottom = run_context.get("bottomResearch")
    if not isinstance(bottom, dict) or not bottom:
        return _bottom_adjustment_payload(
            observed=False,
            applied=False,
            direction="NONE",
            reason="bottom_research_missing",
            before=final_buy,
            after=final_buy,
        )

    evidence = _bottom_adjustment_evidence(bottom, technical_constraint, dvg_permission, discount)
    status = str(bottom.get("status") or "").upper()
    if status not in {"PASS", "WARN"}:
        return _bottom_adjustment_payload(
            observed=True,
            applied=False,
            direction="NONE",
            reason=f"bottom_research_status_{status or 'UNKNOWN'}",
            before=final_buy,
            after=final_buy,
            evidence=evidence,
            blocked_reasons=["bottom_research_not_usable"],
        )

    repair = evidence["bottomRepairProbability"]
    breakdown = evidence["breakdownRiskProbability"]
    threshold = evidence["repairThreshold"]
    evidence_grade = str(evidence["evidenceGrade"] or "").upper()
    trend_bias = str(evidence["trendBias"] or "").upper()
    technical_bias = str(technical_constraint.get("bias") or "UNKNOWN").upper()
    dvg_perm = str(dvg_permission or "").upper()

    negative_signal = (
        (breakdown is not None and breakdown >= 0.50)
        or trend_bias == "DOWN"
        or str(evidence["regimeState"] or "").upper() == "BREAKDOWN_RISK"
        or (technical_bias == "BEARISH" and repair is not None and repair >= threshold)
    )
    if negative_signal:
        reason = (
            "MFE/MAE path research conflict with bearish technical: one-step down"
            if technical_bias == "BEARISH" and repair is not None and repair >= threshold
            else "MFE/MAE MAE breach risk: one-step down"
        )
        after = _step_suitability(final_buy, -1)
        if after == final_buy:
            return _bottom_adjustment_payload(
                observed=True,
                applied=False,
                direction="DOWN",
                reason="already_at_lower_bound",
                before=final_buy,
                after=final_buy,
                evidence=evidence,
            )
        return _bottom_adjustment_payload(
            observed=True,
            applied=True,
            direction="DOWN",
            reason=reason,
            before=final_buy,
            after=after,
            evidence=evidence,
        )

    positive_signal = (
        repair is not None
        and repair >= threshold
        and (breakdown is None or breakdown < 0.35)
        and trend_bias in {"UP", "SIDEWAYS"}
        and evidence_grade in {"MEDIUM", "HIGH"}
    )
    if positive_signal:
        blocked_reasons: list[str] = []
        if dvg_perm != "ALLOW":
            blocked_reasons.append(f"dvg_permission_{dvg_perm or 'UNKNOWN'}")
        if technical_bias in {"BEARISH", "INSUFFICIENT_DATA"}:
            blocked_reasons.append(f"technical_{technical_bias.lower()}")
        if discount < 0.85:
            blocked_reasons.append("discount_factor_below_positive_threshold")
        if final_buy == "BLOCK_BUY":
            blocked_reasons.append("final_buy_blocked")
        if blocked_reasons:
            return _bottom_adjustment_payload(
                observed=True,
                applied=False,
                direction="UP",
                reason="positive_mfe_mae_path_research_blocked_by_guardrails",
                before=final_buy,
                after=final_buy,
                evidence=evidence,
                blocked_reasons=blocked_reasons,
            )
        after = _step_suitability(final_buy, 1)
        if after == final_buy:
            return _bottom_adjustment_payload(
                observed=True,
                applied=False,
                direction="UP",
                reason="already_at_upper_bound",
                before=final_buy,
                after=final_buy,
                evidence=evidence,
            )
        return _bottom_adjustment_payload(
            observed=True,
            applied=True,
            direction="UP",
            reason="MFE/MAE favorable path probability dominant: one-step up",
            before=final_buy,
            after=after,
            evidence=evidence,
        )

    return _bottom_adjustment_payload(
        observed=True,
        applied=False,
        direction="NONE",
        reason="mfe_mae_path_research_neutral_or_low_confidence",
        before=final_buy,
        after=final_buy,
        evidence=evidence,
    )


def _bottom_adjustment_evidence(
    bottom: Dict[str, Any],
    technical_constraint: Dict[str, Any],
    dvg_permission: str,
    discount: float,
) -> Dict[str, Any]:
    current = bottom.get("currentPrediction") if isinstance(bottom.get("currentPrediction"), dict) else {}
    synthesis = bottom.get("trendSynthesis") if isinstance(bottom.get("trendSynthesis"), dict) else {}
    primary_horizon = _int_value(synthesis.get("primaryHorizonDays") or current.get("horizonDays") or (bottom.get("config") or {}).get("horizon_days") or 20)
    forecasts = bottom.get("horizonForecasts") if isinstance(bottom.get("horizonForecasts"), list) else []
    primary_forecast = next(
        (item for item in forecasts if isinstance(item, dict) and _int_value(item.get("horizonDays")) == primary_horizon),
        {},
    )
    diagnostics = bottom.get("modelDiagnostics") if isinstance(bottom.get("modelDiagnostics"), dict) else {}
    mfe_probability = _number(
        current.get("mfeFavorableProbability")
        if current
        else bottom.get("mfeFavorableProbability")
    )
    mae_probability = _number(
        current.get("maeBreachProbability")
        if current
        else bottom.get("maeBreachProbability")
    )
    return {
        "primaryHorizonDays": primary_horizon,
        "researchType": bottom.get("researchType") or "MFE_MAE_PATH_RESEARCH",
        "mfeFavorableProbability": mfe_probability,
        "maeBreachProbability": mae_probability,
        "mfeProxy": _number(current.get("mfeProxy") if current else bottom.get("mfeProxy")),
        "maeProxy": _number(current.get("maeProxy") if current else bottom.get("maeProxy")),
        "riskRewardProxy": _number(current.get("riskRewardProxy") if current else bottom.get("riskRewardProxy")),
        "riskPolicy": current.get("riskPolicy") if current else bottom.get("riskPolicy"),
        "bottomRepairProbability": mfe_probability
        if mfe_probability is not None
        else _number(current.get("bottomRepairProbability") if current else bottom.get("bottomRepairProbability")),
        "breakdownRiskProbability": mae_probability
        if mae_probability is not None
        else _number(current.get("breakdownRiskProbability") if current else bottom.get("breakdownRiskProbability")),
        "regimeState": current.get("regimeState") if current else bottom.get("regimeState"),
        "trendBias": synthesis.get("primaryTrendBias") or primary_forecast.get("trendBias"),
        "horizonAlignment": synthesis.get("horizonAlignment"),
        "evidenceGrade": primary_forecast.get("evidenceGrade") or diagnostics.get("evidenceGrade"),
        "repairThreshold": _number((bottom.get("config") or {}).get("favorable_probability_threshold"))
        or _number((bottom.get("config") or {}).get("repair_probability_threshold"))
        or 0.55,
        "technicalBias": technical_constraint.get("bias"),
        "technicalConfidence": technical_constraint.get("confidence"),
        "dvgPermission": dvg_permission,
        "discountFactor": round(discount, 6),
    }


def _bottom_adjustment_payload(
    *,
    observed: bool,
    applied: bool,
    direction: str,
    reason: str,
    before: str,
    after: str,
    evidence: Dict[str, Any] | None = None,
    blocked_reasons: list[str] | None = None,
) -> Dict[str, Any]:
    return {
        "observed": observed,
        "applied": applied,
        "direction": direction,
        "reason": reason,
        "beforeFinalBuySuitability": before,
        "afterFinalBuySuitability": after,
        "maxStep": 1,
        "policy": "CONTROLLED_ONE_STEP_QIAM_CALIBRATION",
        "canCreateTradeAction": False,
        "evidence": evidence or {},
        "blockedReasons": blocked_reasons or [],
    }


def _step_suitability(value: str, delta: int) -> str:
    value = str(value or "NEUTRAL").upper()
    if value not in _SUITABILITY_ORDER:
        value = "NEUTRAL"
    index = _SUITABILITY_ORDER.index(value)
    next_index = max(0, min(len(_SUITABILITY_ORDER) - 1, index + delta))
    return _SUITABILITY_ORDER[next_index]


def _technical_constraint(technical: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(technical, dict) or not technical:
        return {
            "observed": False,
            "bias": "UNKNOWN",
            "confidence": None,
            "appliedFactor": 1.0,
            "downgradeReason": "",
            "canIncreaseProbability": False,
        }

    bias = str(technical.get("technicalBias") or "UNKNOWN").upper()
    confidence = _number(technical.get("confidence"))
    factor = 1.0
    reason = ""

    if bias == "BEARISH":
        factor = 0.65
        reason = f"technicalKline BEARISH confidence={_format_confidence(confidence)}: x0.65"
    elif bias == "INSUFFICIENT_DATA":
        factor = 0.85
        reason = "technicalKline insufficient_data: x0.85"

    if confidence is not None and confidence < 0.45:
        confidence_factor = 0.85 if confidence >= 0.30 else 0.75
        if confidence_factor < factor or factor == 1.0:
            factor = confidence_factor
            reason = f"technicalKline low confidence={confidence:.2f}: x{confidence_factor:.2f}"

    return {
        "observed": True,
        "bias": bias,
        "confidence": confidence,
        "appliedFactor": round(factor, 4),
        "downgradeReason": reason,
        "canIncreaseProbability": False,
        "summary": technical.get("summaryForDownstream", ""),
    }


def _format_confidence(value: float | None) -> str:
    return "unknown" if value is None else f"{value:.2f}"


def _derive_probability_bands(
    run_context: Dict[str, Any],
    qiam: Dict[str, Any],
    final_buy: str,
    discount: float,
    missing_data: list[Any],
) -> tuple[float, float, float]:
    up = 0.33
    sideways = 0.34
    down = 0.33

    quote = (run_context.get("marketData") or {}).get("quote") or {}
    change_percent = _number(quote.get("changePercent") or quote.get("pct_change")) or 0.0
    momentum = max(-0.18, min(0.18, change_percent / 10))
    if momentum >= 0:
        up += momentum
        down -= momentum * 0.55
    else:
        down += abs(momentum)
        up -= abs(momentum) * 0.55

    if final_buy == "FAVORABLE":
        up += 0.08 * max(0.4, discount)
    elif final_buy == "NEUTRAL":
        sideways += 0.08
    elif final_buy == "REVIEW_ONLY":
        sideways += 0.06
        down += 0.04
    elif final_buy == "BLOCK_BUY":
        down += 0.14

    dvg = run_context.get("dvg") or {}
    reliability = str(dvg.get("dataReliability", "")).upper()
    if reliability == "HIGH":
        up += 0.04
    elif reliability == "MEDIUM":
        sideways += 0.04
    elif reliability == "LOW":
        down += 0.08

    market = run_context.get("market") or {}
    sentiment = str(market.get("marketSentiment", "")).upper()
    if sentiment == "BULLISH":
        up += 0.04
    elif sentiment == "BEARISH":
        down += 0.05
    elif sentiment == "NEUTRAL":
        sideways += 0.03

    execution = run_context.get("execution") or {}
    reachability = str(execution.get("executionReachability", "")).upper()
    if reachability == "REACHABLE":
        up += 0.03
    elif reachability in {"NOT_REACHABLE", "UNREACHABLE"}:
        down += 0.08

    atrade = run_context.get("atrade") or {}
    liquidity_risk = str(atrade.get("liquidityRisk", "")).upper()
    if liquidity_risk == "HIGH":
        down += 0.08
    elif liquidity_risk == "MEDIUM":
        sideways += 0.04

    factor_missing = (run_context.get("factorSlicing") or {}).get("missingFactorData") or []
    missing_count = len(missing_data) + len(factor_missing) + len(dvg.get("criticalMissingData") or [])
    if missing_count > 0:
        sideways += min(0.1, missing_count * 0.025)
        up -= min(0.05, missing_count * 0.01)

    bottom = run_context.get("bottomResearch")
    if isinstance(bottom, dict):
        current = bottom.get("currentPrediction") if isinstance(bottom.get("currentPrediction"), dict) else {}
        repair = _number(current.get("bottomRepairProbability") if current else bottom.get("bottomRepairProbability"))
        breakdown = _number(current.get("breakdownRiskProbability") if current else bottom.get("breakdownRiskProbability"))
        if repair is not None and repair >= 0.60 and (breakdown is None or breakdown < 0.35):
            up += 0.06
            sideways += 0.02
        if breakdown is not None and breakdown >= 0.50:
            down += 0.08
        synthesis = bottom.get("trendSynthesis") if isinstance(bottom.get("trendSynthesis"), dict) else {}
        if synthesis.get("evidenceConflict"):
            sideways += 0.06

    return _normalize_probability(up, sideways, down)


def _normalize_probability(up: float, sideways: float, down: float) -> tuple[float, float, float]:
    values = [max(0.05, up), max(0.05, sideways), max(0.05, down)]
    total = sum(values)
    normalized = [round(value / total, 4) for value in values]
    drift = round(1.0 - sum(normalized), 4)
    normalized[1] = round(normalized[1] + drift, 4)
    return normalized[0], normalized[1], normalized[2]


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().rstrip("%"))
        except ValueError:
            return None
    return None
