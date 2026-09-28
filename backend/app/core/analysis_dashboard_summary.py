from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping


SCHEMA = "analysis_dashboard_summary_v1"


def build_analysis_dashboard_summary(run: Mapping[str, Any]) -> dict[str, Any]:
    """Build a read-only dashboard projection for the analysis detail response."""
    final_writer = _as_mapping(run.get("finalWriter"))
    dvg = _as_mapping(run.get("dvg"))
    execution = _as_mapping(run.get("execution"))
    kill_switch = _as_mapping(run.get("killSwitch"))
    portfolio = _as_mapping(run.get("portfolio"))
    user_position = _as_mapping(run.get("userPosition"))
    data_sources = _as_mapping(run.get("dataSources"))
    data_sources_summary = _as_mapping(data_sources.get("summary"))

    final_action = str(final_writer.get("finalAction") or run.get("finalAction") or "WAIT")
    source_ready_count, source_total_count = _source_counts(data_sources)
    active_agent_count, blocked_agent_count = _agent_counts(run)
    current_position_pct = _ratio_to_percent(user_position.get("currentPositionRatio"))
    single_stock_cap_pct = _ratio_to_percent(portfolio.get("singleStockPositionCap"))
    cap_remaining_pct = single_stock_cap_pct - current_position_pct
    evidence_score = _evidence_score(
        source_ready_count=source_ready_count,
        source_total_count=source_total_count,
        data_reliability=str(dvg.get("dataReliability") or ""),
    )
    human_confirmation_required = final_writer.get("humanConfirmationRequired") is not False

    blockers = _blockers(
        final_action=final_action,
        dvg=dvg,
        execution=execution,
        kill_switch=kill_switch,
        blocked_agent_count=blocked_agent_count,
    )
    warnings = _warnings(run, dvg=dvg, data_sources=data_sources, data_sources_summary=data_sources_summary)
    next_review = _next_review(
        blockers=blockers,
        warnings=warnings,
        final_action=final_action,
        human_confirmation_required=human_confirmation_required,
    )

    return {
        "schema": SCHEMA,
        "generatedAt": datetime.now().isoformat(),
        "decisionState": final_action,
        "headline": _headline(final_action=final_action, blockers=blockers, warnings=warnings),
        "tradeBoundary": {
            "simulationOnly": True,
            "isRealTrade": False,
            "humanConfirmationRequired": human_confirmation_required,
        },
        "metrics": {
            "evidenceScore": evidence_score,
            "sourceReadyCount": source_ready_count,
            "sourceTotalCount": source_total_count,
            "activeAgentCount": active_agent_count,
            "blockedAgentCount": blocked_agent_count,
            "currentPositionPct": round(current_position_pct, 4),
            "singleStockCapPct": round(single_stock_cap_pct, 4),
            "capRemainingPct": round(cap_remaining_pct, 4),
        },
        "blockers": blockers[:6],
        "warnings": warnings[:6],
        "nextReview": next_review[:5],
    }


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().replace("%", ""))
        except ValueError:
            return default
    return default


def _ratio_to_percent(value: Any) -> float:
    numeric = _as_number(value)
    return numeric * 100 if abs(numeric) <= 1 else numeric


def _source_counts(data_sources: Mapping[str, Any]) -> tuple[int, int]:
    summary = _as_mapping(data_sources.get("summary"))
    if summary:
        ready = int(_as_number(summary.get("availableCount")))
        total = int(_as_number(summary.get("totalCount")))
        if total > 0:
            return max(0, ready), max(0, total)

    sources = _as_mapping(data_sources.get("sources"))
    total = len(sources)
    ready = sum(1 for source in sources.values() if _as_mapping(source).get("available") is True)
    return ready, total


def _agent_counts(run: Mapping[str, Any]) -> tuple[int, int]:
    agent_results = _as_list(run.get("agentResults"))
    if agent_results:
        rows = [_as_mapping(item) for item in agent_results]
        active = sum(1 for item in rows if str(item.get("status") or "").upper() != "SKIPPED")
        blocked = sum(
            1
            for item in rows
            if str(item.get("status") or "").upper() in {"BLOCK", "BLOCKED", "FAIL", "FAILED"}
            or item.get("hard_stop") is True
        )
        return active, blocked

    nodes = [_as_mapping(item) for item in _as_list(run.get("nodes"))]
    active = sum(1 for item in nodes if item.get("isSkipped") is not True)
    blocked = sum(
        1
        for item in nodes
        if item.get("isBlocked") is True
        or str(item.get("status") or "").upper() in {"BLOCK", "BLOCKED", "FAIL", "FAILED"}
    )
    return active, blocked


def _evidence_score(*, source_ready_count: int, source_total_count: int, data_reliability: str) -> float:
    if source_total_count > 0:
        source_score = source_ready_count / source_total_count
    else:
        source_score = 0.5
    reliability_score = {
        "HIGH": 1.0,
        "MEDIUM": 0.65,
        "LOW": 0.3,
    }.get(data_reliability.upper(), 0.5)
    return round(max(0.0, min(1.0, source_score * 0.55 + reliability_score * 0.45)), 4)


def _blockers(
    *,
    final_action: str,
    dvg: Mapping[str, Any],
    execution: Mapping[str, Any],
    kill_switch: Mapping[str, Any],
    blocked_agent_count: int,
) -> list[str]:
    rows: list[str] = []
    kill_level = str(kill_switch.get("level") or "NONE").upper()
    if kill_switch.get("active") is True or kill_level not in {"", "NONE"}:
        rows.append(f"Risk/Kill Switch {kill_level} 限制交易动作")
    if dvg.get("hardStop") is True:
        rows.append("DVG hard stop 阻断后续动作")
    output_level = str(dvg.get("allowedOutputLevel") or "").upper()
    if output_level in {"REVIEW_ONLY", "BLOCK_BUY"}:
        rows.append(f"DVG 输出级别为 {output_level}")
    reachability = str(execution.get("executionReachability") or "").upper()
    if reachability in {"NOT_REACHABLE", "UNREACHABLE"}:
        rows.append("Execution 不可达")
    if blocked_agent_count > 0:
        rows.append(f"{blocked_agent_count} 个 Agent 节点阻断或失败")
    if final_action in {"BUY_CANDIDATE", "ADD_CANDIDATE"}:
        rows.append("候选动作仍需 DVG、Risk、Execution 与人工确认")
    return _dedupe(rows)


def _warnings(
    run: Mapping[str, Any],
    *,
    dvg: Mapping[str, Any],
    data_sources: Mapping[str, Any],
    data_sources_summary: Mapping[str, Any],
) -> list[str]:
    rows: list[str] = []
    overall_status = str(data_sources_summary.get("overallStatus") or "").upper()
    if overall_status and overall_status != "READY":
        rows.append(f"数据源整体状态 {overall_status}")
    if str(dvg.get("dataReliability") or "").upper() in {"LOW", "MEDIUM"}:
        rows.append(f"DVG 数据可靠性 {dvg.get('dataReliability')}")
    for source in _as_mapping(data_sources.get("sources")).values():
        item = _as_mapping(source)
        if item.get("available") is not True:
            rows.append(f"{item.get('name') or item.get('provider') or '数据源'} 未就绪")
        if _as_list(item.get("fallbackChain")) or _as_list(item.get("degradationChain")):
            rows.append(f"{item.get('name') or item.get('provider') or '数据源'} 使用 fallback/降级链")
    missing = [
        *_as_list(dvg.get("criticalMissingData")),
        *_as_list(_as_mapping(run.get("qiam")).get("missingData")),
        *_as_list(_as_mapping(run.get("factorSlicing")).get("missingFactorData")),
    ]
    if missing:
        rows.append(f"存在 {len(missing)} 项关键缺失数据")
    final_writer_mode = str(_as_mapping(run.get("finalWriter")).get("mode") or "").upper()
    if final_writer_mode == "LLM_UNAVAILABLE":
        rows.append("Final Writer 处于 LLM_UNAVAILABLE")
    return _dedupe(rows)


def _next_review(
    *,
    blockers: list[str],
    warnings: list[str],
    final_action: str,
    human_confirmation_required: bool,
) -> list[str]:
    rows: list[str] = []
    if blockers:
        rows.append("先处理阻断项，再讨论任何候选动作")
    if warnings:
        rows.append("复核数据源、新鲜度、fallback 链和关键缺失字段")
    if final_action in {"BUY_CANDIDATE", "ADD_CANDIDATE"}:
        rows.append("候选动作只进入人工复核和模拟观察，不触发实盘")
    if human_confirmation_required:
        rows.append("执行前必须保留人工确认")
    rows.append("查看 Agent 链路定位结论来源与失败节点")
    return _dedupe(rows)


def _headline(*, final_action: str, blockers: list[str], warnings: list[str]) -> str:
    if blockers:
        return f"当前为 {final_action}，但首要约束是：{blockers[0]}。"
    if warnings:
        return f"当前为 {final_action}，需要先复核：{warnings[0]}。"
    return f"当前为 {final_action}，核心门禁未报告硬阻断；仍只作为模拟/人工复核工作台展示。"


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value).strip()))
