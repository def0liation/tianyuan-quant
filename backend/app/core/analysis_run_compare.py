from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

LoadRun = Callable[[str], dict | None]
IsLegacyRun = Callable[[str, dict | None], bool]
RunFieldGetter = Callable[[dict], object]


class AnalysisRunCompareError(Exception):
    status_code = 500

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class AnalysisRunCompareBadRequest(AnalysisRunCompareError):
    status_code = 400


class AnalysisRunCompareNotFound(AnalysisRunCompareError):
    status_code = 404


def compare_runs(
    left_id: str,
    right_id: str,
    *,
    load_run: LoadRun,
    is_legacy_run: IsLegacyRun,
) -> dict:
    if not left_id or not right_id:
        raise AnalysisRunCompareBadRequest("Both left and right run ids are required")

    left = load_run(left_id)
    right = load_run(right_id)
    if left is None or is_legacy_run(left_id, left):
        raise AnalysisRunCompareNotFound(f"Left run not found: {left_id}")
    if right is None or is_legacy_run(right_id, right):
        raise AnalysisRunCompareNotFound(f"Right run not found: {right_id}")

    modules: list[tuple[str, str, RunFieldGetter]] = [
        ("final", "最终动作", lambda r: r.get("finalWriter", {}).get("finalAction") or r.get("finalAction")),
        (
            "final_mode",
            "最终输出模式",
            lambda r: r.get("finalWriter", {}).get("mode") or r.get("killSwitch", {}).get("finalWriterMode"),
        ),
        ("final_audit", "最终输出审计 ID", lambda r: r.get("finalWriter", {}).get("auditId")),
        ("final_sections", "最终输出章节", _final_writer_sections),
        ("dvg", "DVG 数据可靠性", lambda r: r.get("dvg", {}).get("dataReliability")),
        (
            "dvg_cap",
            "DVG 决策上限",
            lambda r: r.get("dvg", {}).get("finalDecisionCap") or r.get("dvg", {}).get("allowedOutputLevel"),
        ),
        ("dvg_missing", "DVG 缺失数据", lambda r: r.get("dvg", {}).get("criticalMissingData", [])),
        ("qiam_up", "QIAM 上行概率", lambda r: r.get("qiam", {}).get("probabilityBandUp")),
        ("qiam_final", "QIAM 最终适宜性", lambda r: r.get("qiam", {}).get("finalBuySuitability")),
        ("portfolio", "组合覆盖", lambda r: r.get("portfolio", {}).get("portfolioCoverage")),
        ("portfolio_add", "组合加仓许可", lambda r: r.get("portfolio", {}).get("allowAddPosition")),
        ("execution", "执行可达性", lambda r: r.get("execution", {}).get("executionReachability")),
        ("execution_actions", "执行允许动作", lambda r: r.get("execution", {}).get("allowedActions", [])),
        ("signal_status", "SignalOps 状态", lambda r: r.get("signalOps", {}).get("signalStatus")),
        ("signal_blocked", "SignalOps 阻断原因", _signalops_blocked_reason),
        ("signal_triggers", "SignalOps 触发条件", lambda r: r.get("signalOps", {}).get("triggerConditions", [])),
        ("signal_invalidations", "SignalOps 失效条件", lambda r: r.get("signalOps", {}).get("invalidationConditions", [])),
        ("data_mode", "数据模式", lambda r: r.get("dataMode")),
        ("source_summary", "数据源摘要", _data_source_summary),
        ("source_fallback", "数据源降级错误", _data_source_fallback_errors),
        ("agent_statuses", "Agent 状态", _agent_statuses),
    ]
    diffs = []
    for key, label, getter in modules:
        left_value = getter(left)
        right_value = getter(right)
        changed = left_value != right_value
        diffs.append(
            {
                "key": key,
                "label": label,
                "left": left_value,
                "right": right_value,
                "changed": changed,
                "impact": _diff_impact(key, left_value, right_value) if changed else "无变化。",
            }
        )

    changed_items = [item for item in diffs if item["changed"]]
    return {
        "leftRun": _compare_run_summary(left),
        "rightRun": _compare_run_summary(right),
        "generatedAt": datetime.now().isoformat(),
        "changedCount": len(changed_items),
        "summary": _compare_summary(changed_items),
        "diffs": diffs,
    }


def _compare_run_summary(run: dict) -> dict:
    return {
        "runId": run.get("runId"),
        "stockCode": run.get("stockCode"),
        "stockName": run.get("stockName"),
        "runMode": run.get("runMode"),
        "status": run.get("status"),
        "finalAction": run.get("finalWriter", {}).get("finalAction") or run.get("finalAction"),
        "dataMode": run.get("dataMode"),
        "createdAt": run.get("createdAt"),
        "updatedAt": run.get("updatedAt"),
    }


def _final_writer_sections(run: dict) -> list[dict]:
    sections = run.get("finalWriter", {}).get("sections", [])
    if not isinstance(sections, list):
        return []
    return [
        {
            "title": item.get("title", ""),
            "riskLevel": item.get("riskLevel", ""),
            "requiresConfirmation": item.get("requiresConfirmation", True),
            "contentPreview": str(item.get("content", ""))[:160],
        }
        for item in sections
        if isinstance(item, dict)
    ]


def _data_source_summary(run: dict) -> dict:
    summary = (run.get("dataSources", {}) or {}).get("summary", {}) or {}
    return {
        "availableCount": summary.get("availableCount"),
        "totalCount": summary.get("totalCount"),
        "availableRatio": summary.get("availableRatio"),
        "overallStatus": summary.get("overallStatus"),
        "overallDataMode": summary.get("overallDataMode"),
    }


def _data_source_fallback_errors(run: dict) -> list[str]:
    sources = (run.get("dataSources", {}) or {}).get("sources", {}) or {}
    errors: list[str] = []
    for key, source in sources.items():
        if not isinstance(source, dict):
            continue
        chain = source.get("fallbackChain") or source.get("degradationChain") or []
        for step in chain:
            if isinstance(step, dict) and step.get("error"):
                errors.append(f"{key}:{step.get('adapterId') or step.get('provider')}:{step.get('error')}")
    return errors[:12]


def _agent_statuses(run: dict) -> dict:
    results = run.get("agentResults") or []
    if not isinstance(results, list):
        return {}
    return {
        str(item.get("node") or item.get("id")): item.get("status")
        for item in results
        if isinstance(item, dict) and (item.get("node") or item.get("id"))
    }


def _signalops_blocked_reason(run: dict) -> str:
    reason = str((run.get("signalOps", {}) or {}).get("blockedReason") or "").strip()
    if reason in {"等待真实 Agent 运行", "等待真实 Agent 运行."}:
        return ""
    return reason


def _diff_impact(key: str, left: object, right: object) -> str:
    if key == "final":
        return f"最终动作从 {left} 变为 {right}；请重点复核下方 DVG、QIAM 和执行可达性差异。"
    if key.startswith("final_"):
        return "最终输出发生变化；复用结论前请检查章节文本和审计归因。"
    if key.startswith("dvg"):
        return "数据验证结果发生变化；结论可信度或输出权限可能不同。"
    if key.startswith("qiam"):
        return "量化适宜性发生变化；概率分布或折扣因子可能影响最终动作。"
    if key.startswith("portfolio"):
        return "组合来源或约束发生变化；真实持仓可能改变仓位上限和执行限制。"
    if key.startswith("execution"):
        return "执行可达性发生变化；这不是买入许可，但会影响允许的执行路径。"
    if key.startswith("signal"):
        return "SignalOps 生命周期发生变化；观察、模拟验证或合格状态需要复核。"
    if key.startswith("source") or key == "data_mode":
        return "数据源覆盖发生变化；请到数据源健康页面查看适配器层原因。"
    if key == "agent_statuses":
        return "一个或多个 Agent 状态发生变化；比较结论前请复核 DAG 和审计详情。"
    return "字段值发生变化。"


def _compare_summary(changed_items: list[dict]) -> list[str]:
    if not changed_items:
        return ["两次运行未检测到关键差异。"]
    return [item["impact"] for item in changed_items[:5]]
