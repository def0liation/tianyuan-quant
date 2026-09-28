from __future__ import annotations
from typing import Any, Dict

from ..core.quant_engine_modes import (
    HIGH_FREQ_SHORT,
    LOW_FREQ_MID_LONG,
    quant_engine_profile,
    quant_engine_profile_from_run,
    split_missing_data_for_mode,
)
from .base_agent import BaseAgent, AgentResult


class DvgEvidenceGateAgent(BaseAgent):
    node = "dvg_evidence_gate"
    name = "DVG Evidence Gate"
    stage = "guardrail"
    rule_engine_only = True

    QIAM_DISCOUNT_RULES = {
        "ALLOW": 1.0,
        "ALLOW_WITH_DISCOUNT": 0.70,
        "REVIEW_ONLY": 0.0,
        "BLOCKED": 0.0,
    }

    def process(self, run_context: Dict[str, Any], prior_outputs: Dict[str, Any]) -> AgentResult:
        dvg = run_context.get("dvg", {})
        if not isinstance(dvg, dict):
            dvg = {}
        quant_profile = quant_engine_profile_from_run(run_context)
        active_mode = quant_profile["mode"]

        evidence = _derive_evidence_from_sources(run_context, dvg)
        modules = _evaluate_dvg_modules(evidence, run_context.get("taskType"))
        active_module = modules[active_mode]
        status = active_module["status"]
        allowed_output = active_module["allowedOutputLevel"]
        qiam_perm = active_module["qiamPermission"]
        hard_stop = active_module["hardStop"]
        confirmed_ratio = active_module["confirmedRatio"]
        inferred_ratio = active_module["inferredRatio"]
        unknown_ratio = active_module["unknownRatio"]
        core_unknown_count = active_module["coreUnknownCount"]
        hallucination_score = active_module["hallucinationRiskScore"]
        critical_missing = active_module["criticalMissingData"]
        ignored_missing = active_module["ignoredMissingData"]

        has_level2 = not any("Level-2" in str(item) for item in critical_missing)
        has_depth = not any("盘口深度" in str(item) for item in critical_missing)

        reasons = [
            f"DVG active module: {active_module['label']} ({active_mode})",
            f"DVG 数据可靠性评定: 确认 {confirmed_ratio:.0%}, 推断 {inferred_ratio:.0%}, 未知 {unknown_ratio:.0%}",
            f"关键缺失项: {core_unknown_count}项",
            f"幻觉风险评估: {hallucination_score}分 ({'HIGH' if hallucination_score >= 75 else 'MEDIUM' if hallucination_score >= 38 else 'LOW'})",
        ]
        if ignored_missing:
            reasons.append(f"当前模式忽略高频微观结构缺失: {', '.join(str(item) for item in ignored_missing)}")

        warnings = []
        if not has_level2:
            warnings.append("无 Level-2 不得判断封单强弱")
            reasons.append("缺少 Level-2 逐笔成交，禁止判断封单强弱")
        if not has_depth:
            warnings.append("盘口深度不足，无法评估流动性冲击成本")
        if ignored_missing:
            warnings.append("低频中长线 DVG 记录高频缺失为 ignoredMissingData，不压低 Quant Engine/QIAM。")
        warnings.append(f"下游权限限制为 {allowed_output}")

        data = {
            "status": status,
            "quantEngineMode": active_mode,
            "activeModule": active_module["moduleId"],
            "activeModuleLabel": active_module["label"],
            "parameterProfile": quant_profile["parameterProfile"],
            "dataReliability": active_module["dataReliability"],
            "confirmedRatio": confirmed_ratio,
            "inferredRatio": inferred_ratio,
            "unknownRatio": unknown_ratio,
            "coreUnknownCount": core_unknown_count,
            "qiamPermission": qiam_perm,
            "scenarioPermission": active_module["scenarioPermission"],
            "executionPermission": active_module["executionPermission"],
            "allowedOutputLevel": allowed_output,
            "finalDecisionCap": active_module["finalDecisionCap"],
            "hardStop": hard_stop,
            "hallucinationRiskScore": hallucination_score,
            "hallucinationRiskLevel": "HIGH" if hallucination_score >= 75 else "MEDIUM" if hallucination_score >= 38 else "LOW",
            "freshnessStatus": evidence["freshnessStatus"],
            "sourceIntegrity": active_module["sourceIntegrity"],
            "criticalMissingData": critical_missing,
            "ignoredMissingData": ignored_missing,
            "rawCriticalMissingData": evidence["criticalMissingData"],
            "rawCoreUnknownCount": evidence["coreUnknownCount"],
            "dataConflicts": evidence["dataConflicts"],
            "provenance": evidence["provenance"],
            "dvgModules": {
                "highFrequencyTrading": modules[HIGH_FREQ_SHORT],
                "lowFrequencyMidLong": modules[LOW_FREQ_MID_LONG],
            },
        }

        return AgentResult(
            node=self.node,
            status=status,
            allowed_actions=["REVIEW_ONLY"] if allowed_output != "FULL" else [],
            blocked_actions=["BUY_CANDIDATE", "ADD_CANDIDATE"] if hard_stop else (["CHASE"] if allowed_output != "FULL" else []),
            hard_stop=hard_stop,
            final_decision_cap=data["finalDecisionCap"],
            confidence="MEDIUM" if status == "WARN" else ("LOW" if hard_stop else "HIGH"),
            reasons=reasons,
            missing_data=critical_missing,
            warnings=warnings,
            data=data,
            audit_id=self._audit(),
        )


def _evaluate_dvg_modules(evidence: Dict[str, Any], task_type: str | None) -> Dict[str, Dict[str, Any]]:
    return {
        HIGH_FREQ_SHORT: _evaluate_dvg_module(
            evidence,
            quant_engine_profile(HIGH_FREQ_SHORT, task_type),
            task_type,
        ),
        LOW_FREQ_MID_LONG: _evaluate_dvg_module(
            evidence,
            quant_engine_profile(LOW_FREQ_MID_LONG, task_type),
            task_type,
        ),
    }


def _evaluate_dvg_module(
    evidence: Dict[str, Any],
    quant_profile: Dict[str, Any],
    task_type: str | None,
) -> Dict[str, Any]:
    quant_mode = quant_profile["mode"]
    module = _module_definition(quant_mode)
    raw_missing = list(evidence.get("criticalMissingData") or [])
    critical_missing, ignored_missing = split_missing_data_for_mode(raw_missing, quant_mode, task_type)

    confirmed_count = _int_value(evidence.get("confirmedCount"), 0)
    inferred_count = _int_value(evidence.get("inferredCount"), 0)
    raw_unknown_count = _int_value(evidence.get("unknownCount"), evidence.get("coreUnknownCount") or len(raw_missing))
    ignored_unknown_count = min(raw_unknown_count, len(ignored_missing))
    core_unknown_count = max(0, raw_unknown_count - ignored_unknown_count)

    total = max(1, confirmed_count + inferred_count + core_unknown_count)
    confirmed_ratio = round(confirmed_count / total, 4)
    inferred_ratio = round(inferred_count / total, 4)
    unknown_ratio = round(core_unknown_count / total, 4)
    adjusted_hallucination_score = int(min(95, max(5, 10 + unknown_ratio * 70 + inferred_ratio * 25)))
    hallucination_score = (
        _int_value(evidence.get("hallucinationRiskScore"), adjusted_hallucination_score)
        if evidence.get("usesSyntheticCounts")
        else adjusted_hallucination_score
    )

    if hallucination_score >= 75:
        status = "BLOCK_BUY"
        allowed_output = "BLOCK_BUY"
        qiam_perm = "BLOCKED"
        scenario_perm = "BLOCKED"
        execution_perm = "BLOCKED"
        hard_stop = True
    elif core_unknown_count >= 2 or unknown_ratio >= 0.25:
        status = "WARN"
        allowed_output = "REVIEW_ONLY"
        qiam_perm = "ALLOW_WITH_DISCOUNT"
        scenario_perm = "ALLOW_WITH_DISCOUNT"
        execution_perm = "ALLOW_WITH_DISCOUNT"
        hard_stop = False
    elif confirmed_ratio >= 0.85:
        status = "PASS"
        allowed_output = "FULL"
        qiam_perm = "ALLOW"
        scenario_perm = "ALLOW"
        execution_perm = "ALLOW"
        hard_stop = False
    else:
        status = "WARN"
        allowed_output = "REVIEW_ONLY"
        qiam_perm = "ALLOW_WITH_DISCOUNT"
        scenario_perm = "ALLOW_WITH_DISCOUNT"
        execution_perm = "ALLOW_WITH_DISCOUNT"
        hard_stop = False

    if confirmed_ratio >= 0.85:
        data_reliability = "HIGH"
    elif confirmed_ratio >= 0.6:
        data_reliability = "MEDIUM"
    else:
        data_reliability = "LOW"

    raw_unknown_count_for_source = _int_value(evidence.get("unknownCount"), evidence.get("coreUnknownCount") or 0)
    if core_unknown_count == 0 and ignored_missing and raw_unknown_count_for_source > 0:
        source_integrity = "COMPLETE_FOR_MODE"
    elif core_unknown_count == 0:
        source_integrity = "COMPLETE"
    elif confirmed_count or inferred_count:
        source_integrity = "PARTIAL"
    else:
        source_integrity = "MISSING"

    return {
        **module,
        "quantEngineMode": quant_mode,
        "status": status,
        "dataReliability": data_reliability,
        "confirmedRatio": confirmed_ratio,
        "inferredRatio": inferred_ratio,
        "unknownRatio": unknown_ratio,
        "coreUnknownCount": core_unknown_count,
        "rawCoreUnknownCount": evidence["coreUnknownCount"],
        "hallucinationRiskScore": hallucination_score,
        "hallucinationRiskLevel": "HIGH" if hallucination_score >= 75 else "MEDIUM" if hallucination_score >= 38 else "LOW",
        "criticalMissingData": critical_missing,
        "ignoredMissingData": ignored_missing,
        "qiamPermission": qiam_perm,
        "scenarioPermission": scenario_perm,
        "executionPermission": execution_perm,
        "allowedOutputLevel": allowed_output,
        "finalDecisionCap": "BLOCK_BUY" if hard_stop else "WAIT",
        "hardStop": hard_stop,
        "sourceIntegrity": source_integrity,
    }


def _module_definition(quant_mode: str) -> Dict[str, Any]:
    if quant_mode == LOW_FREQ_MID_LONG:
        return {
            "moduleId": "dvg_low_frequency_mid_long",
            "label": "DVG Low-Frequency / Mid-Long Gate",
            "gatePolicy": "基本面、日/周/月 K 线、来源完整性和数据冲突参与门禁；Level-2、盘口、分时、逐笔等高频微观结构缺失仅记录为不适用。",
        }
    return {
        "moduleId": "dvg_high_frequency_trading",
        "label": "DVG High-Frequency Trading Gate",
        "gatePolicy": "Level-2、盘口深度、分时、逐笔、资金流分解等微观结构数据是高频交易门禁输入，缺失会限制 QIAM 和执行权限。",
    }


def _derive_evidence_from_sources(run_context: Dict[str, Any], dvg: Dict[str, Any]) -> Dict[str, Any]:
    data_sources = run_context.get("dataSources") or {}
    sources = data_sources.get("sources") or {}
    if not isinstance(sources, dict) or not sources:
        confirmed = _bounded_ratio(dvg.get("confirmedRatio"), 0.0)
        inferred = _bounded_ratio(dvg.get("inferredRatio"), 0.0)
        unknown = _bounded_ratio(dvg.get("unknownRatio"), 1.0)
        total = confirmed + inferred + unknown
        if total <= 0:
            confirmed, inferred, unknown = 0.0, 0.0, 1.0
        else:
            confirmed, inferred, unknown = confirmed / total, inferred / total, unknown / total
        missing = list(dvg.get("criticalMissingData") or ["数据源状态报告"])
        unknown_count = max(1, len(missing))
        total_count = max(unknown_count, int(round(unknown_count / unknown))) if unknown > 0 else unknown_count
        confirmed_count = int(round(confirmed * total_count))
        inferred_count = int(round(inferred * total_count))
        return {
            "confirmedRatio": round(confirmed, 4),
            "inferredRatio": round(inferred, 4),
            "unknownRatio": round(unknown, 4),
            "confirmedCount": confirmed_count,
            "inferredCount": inferred_count,
            "unknownCount": unknown_count,
            "coreUnknownCount": unknown_count,
            "hallucinationRiskScore": max(60, int(dvg.get("hallucinationRiskScore") or 60)),
            "usesSyntheticCounts": True,
            "criticalMissingData": missing,
            "freshnessStatus": dvg.get("freshnessStatus", "UNKNOWN"),
            "sourceIntegrity": dvg.get("sourceIntegrity", "LEGACY_TEMPLATE"),
            "dataConflicts": list(dvg.get("dataConflicts") or ["缺少数据来源报告，旧历史记录可能来自模板默认值"]),
            "provenance": {"sourceType": "LEGACY_TEMPLATE", "note": "未找到数据源状态报告，按历史模板记录处理"},
        }

    confirmed_count = 0
    inferred_count = 0
    unknown_count = 0
    missing: list[str] = []
    conflicts: list[str] = []

    for key, source in sources.items():
        if not isinstance(source, dict):
            continue
        name = str(source.get("name") or key)
        status = str(source.get("status") or "").upper()
        data_mode = str(source.get("dataMode") or "").upper()
        available = bool(source.get("available")) and status == "READY" and not source.get("error")
        provider = str(source.get("provider") or "")
        arbitration = source.get("arbitration") or (source.get("extra") or {}).get("arbitration") or {}
        arbitration_conflicts = arbitration.get("conflicts", []) if isinstance(arbitration, dict) else []
        arbitration_quality = arbitration.get("dataQuality", {}) if isinstance(arbitration, dict) else {}
        if arbitration_conflicts:
            conflicts.append(f"{name}: source arbitration conflicts={len(arbitration_conflicts)}")
        if arbitration_quality.get("reviewOnly"):
            unknown_count += 1
            missing.append(f"{name} source arbitration review")
            continue

        if available and provider != "mock" and data_mode in {"LIVE", "FALLBACK"}:
            confirmed_count += 1
        elif available and provider != "mock":
            inferred_count += 1
        else:
            unknown_count += 1
            missing.append(name)
            error = source.get("error")
            if error:
                conflicts.append(f"{name}: {error}")

    technical = run_context.get("technicalKline")
    if isinstance(technical, dict) and technical:
        quality = technical.get("dataQuality") or {}
        if (
            technical.get("status") in {"PASS", "WARN"}
            and technical.get("agent") == "technical_kline_analyst"
            and quality.get("provider") == "tushare"
            and quality.get("dataMode") == "LIVE"
            and int(quality.get("dailyCount") or 0) >= 30
        ):
            confirmed_count += 1
        else:
            unknown_count += 1
            missing.append("技术面 K 线真实数据校验")
            conflicts.append("技术面 K 线未通过真实 Tushare 数据门禁，禁止下游正向使用")

    atrade = run_context.get("atrade") or {}
    for field, label in (("level2Available", "Level-2 逐笔成交"), ("depthAvailable", "盘口深度")):
        if not bool(atrade.get(field)):
            unknown_count += 1
            missing.append(label)

    total = max(1, confirmed_count + inferred_count + unknown_count)
    confirmed_ratio = confirmed_count / total
    inferred_ratio = inferred_count / total
    unknown_ratio = unknown_count / total
    hallucination_score = int(min(95, max(5, 10 + unknown_ratio * 70 + inferred_ratio * 25)))

    quote = run_context.get("marketData") or {}
    freshness = str(quote.get("freshness") or "").upper()
    freshness_status = (
        "FRESH" if freshness in {"REALTIME", "DELAYED_15MIN"} else
        "MODERATE" if freshness == "EOD" else
        "STALE" if freshness == "STALE" else
        "UNKNOWN"
    )

    source_integrity = "COMPLETE" if unknown_count == 0 else ("PARTIAL" if confirmed_count or inferred_count else "MISSING")
    return {
        "confirmedRatio": round(confirmed_ratio, 4),
        "inferredRatio": round(inferred_ratio, 4),
        "unknownRatio": round(unknown_ratio, 4),
        "confirmedCount": confirmed_count,
        "inferredCount": inferred_count,
        "unknownCount": unknown_count,
        "coreUnknownCount": unknown_count,
        "hallucinationRiskScore": hallucination_score,
        "criticalMissingData": missing,
        "freshnessStatus": freshness_status,
        "sourceIntegrity": source_integrity,
        "dataConflicts": conflicts,
        "provenance": {
            "sourceType": "DATA_SOURCES_REPORT",
            "availableCount": confirmed_count + inferred_count,
            "totalCount": total,
            "note": "由本次运行的数据源可用性、provider 与 dataMode 计算，不再使用固定模板比例",
        },
    }


def _bounded_ratio(value: Any, fallback: float) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return max(0.0, min(1.0, float(value)))
    return fallback


def _int_value(value: Any, fallback: Any = 0) -> int:
    if isinstance(value, bool):
        return int(fallback or 0)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return int(fallback or 0)
    return int(fallback or 0)
