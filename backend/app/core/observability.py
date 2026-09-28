from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional


DEFAULT_WINDOWS_HOURS = (24, 24 * 7, 24 * 30)
DEFAULT_ERROR_BUDGET_TARGET = 0.95
SUCCESS_STATUSES = {"COMPLETED"}
RUN_TERMINAL_STATUSES = {"COMPLETED", "FAILED", "STALE", "CANCELLED"}
LLM_SUCCESS_STATUSES = {"COMPLETED"}
LLM_FAILURE_STATUSES = {"FAILED", "ERROR"}
LLM_SKIPPED_STATUSES = {"SKIPPED", "BLOCKED", "NOT_REQUESTED"}
SIGNALOPS_SUCCESS_STATUSES = {"COMPLETED"}
SIGNALOPS_FAILURE_STATUSES = {"ERROR", "PARTIAL", "BLOCKED", "FAILED"}
SECRET_TEXT_PATTERN = re.compile(r"(api[_-]?key|access[_-]?token|auth[_-]?token|token|secret|authorization)\s*[:=]\s*([^,\s&]+)", re.IGNORECASE)


def build_production_health_summary(
    *,
    runs: Iterable[Dict[str, Any]],
    jobs: Iterable[Dict[str, Any]],
    auto_paper_status: Dict[str, Any] | None,
    generated_at: datetime | None = None,
    source_errors: Dict[str, str] | None = None,
    windows_hours: Iterable[int] = DEFAULT_WINDOWS_HOURS,
    target_success_rate: float = DEFAULT_ERROR_BUDGET_TARGET,
) -> Dict[str, Any]:
    now = _ensure_utc(generated_at or datetime.now(timezone.utc))
    window_values = list(windows_hours) or list(DEFAULT_WINDOWS_HOURS)
    run_items = [item for item in runs if isinstance(item, dict)]
    job_items = [item for item in jobs if isinstance(item, dict)]
    tick_samples = _signalops_tick_samples(auto_paper_status or {})
    windows: Dict[str, Any] = {}
    for hours in window_values:
        label = _window_label(hours)
        window_start = now - timedelta(hours=hours)
        window_runs = [
            run for run in run_items
            if _item_in_window(run, window_start, now, ("updatedAt", "createdAt", "timestamp"))
        ]
        window_jobs = [
            job for job in job_items
            if _item_in_window(job, window_start, now, ("updated_at", "finished_at", "started_at", "created_at"))
        ]
        window_ticks = [
            sample for sample in tick_samples
            if _item_in_window(sample, window_start, now, ("updated_at", "timestamp", "last_tick_at"))
        ]
        windows[label] = _window_metrics(
            label=label,
            hours=hours,
            runs=window_runs,
            jobs=window_jobs,
            all_jobs=job_items,
            tick_samples=window_ticks,
            target_success_rate=target_success_rate,
        )

    primary_label = _window_label(window_values[0])
    primary = windows.get(primary_label) or next(iter(windows.values()), {})
    alerts = _build_alerts(windows, target_success_rate)
    errors = {
        key: value
        for key, value in (source_errors or {}).items()
        if value
    }
    if errors:
        alerts.append({
            "severity": "warning",
            "metric": "sourceAvailability",
            "window": "current",
            "message": "One or more local observability sources could not be read.",
            "details": errors,
        })

    return {
        "status": _overall_status(alerts, primary.get("errorBudget", {}).get("status")),
        "generatedAt": now.isoformat(),
        "externalCalls": False,
        "coverage": {
            "runHistory": "analysis_runs_store",
            "llmCalls": "run_llm_trace",
            "marketData": "run_data_sources",
            "signalOpsTicks": "auto_paper_last_tick",
            "jobs": "analysis_job_store",
            "signalOpsTickHistory": "latest_only",
        },
        "windows": windows,
        "trend": _trend_vs_baseline(windows, primary_label, _window_label(24 * 7)),
        "longTrend": _trend_vs_baseline(windows, primary_label, _window_label(24 * 30)),
        "alerts": alerts,
        "errorBudget": primary.get("errorBudget", {}),
        "sourceErrors": errors,
    }


def _window_metrics(
    *,
    label: str,
    hours: int,
    runs: List[Dict[str, Any]],
    jobs: List[Dict[str, Any]],
    all_jobs: List[Dict[str, Any]],
    tick_samples: List[Dict[str, Any]],
    target_success_rate: float,
) -> Dict[str, Any]:
    run_rate = _run_success_rate(runs)
    llm_rate = _llm_call_failure_rate(runs)
    market_rate = _market_data_fallback_rate(runs)
    signalops_rate = _signalops_tick_success_rate(tick_samples)
    stale_jobs = _stale_job_count(jobs, all_jobs)
    error_budget = _error_budget(
        target_success_rate=target_success_rate,
        run_rate=run_rate,
        llm_rate=llm_rate,
        market_rate=market_rate,
        signalops_rate=signalops_rate,
        stale_jobs=stale_jobs,
    )
    return {
        "window": label,
        "windowHours": hours,
        "runSuccessRate": run_rate,
        "llmCallFailureRate": llm_rate,
        "marketDataFallbackRate": market_rate,
        "signalOpsTickSuccessRate": signalops_rate,
        "staleJobs": stale_jobs,
        "errorBudget": error_budget,
    }


def _run_success_rate(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    terminal_runs = [
        run for run in runs
        if str(run.get("status") or "").upper() in RUN_TERMINAL_STATUSES
    ]
    total = len(terminal_runs)
    succeeded = sum(1 for run in terminal_runs if str(run.get("status") or "").upper() in SUCCESS_STATUSES)
    cancelled = sum(1 for run in terminal_runs if str(run.get("status") or "").upper() == "CANCELLED")
    stale = sum(1 for run in terminal_runs if str(run.get("status") or "").upper() == "STALE")
    failed = total - succeeded
    return {
        "total": total,
        "succeeded": succeeded,
        "failed": failed,
        "cancelled": cancelled,
        "stale": stale,
        "successRate": _rate(succeeded, total),
        "errorRate": _rate(failed, total),
        "sampleRunIds": [str(run.get("runId") or run.get("run_id") or "") for run in terminal_runs[:10]],
    }


def _llm_call_failure_rate(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    completed = 0
    failed = 0
    skipped = 0
    total_tokens = 0
    failure_reason_counts: Dict[str, int] = {}
    sample_failures: List[Dict[str, str]] = []
    for run in runs:
        trace = run.get("llmTrace") if isinstance(run.get("llmTrace"), list) else []
        for item in trace:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or "").upper()
            if status in LLM_SUCCESS_STATUSES:
                completed += 1
            elif status in LLM_FAILURE_STATUSES:
                failed += 1
                reason = _llm_failure_reason(item)
                failure_reason_counts[reason] = failure_reason_counts.get(reason, 0) + 1
                if len(sample_failures) < 5:
                    sample_failures.append({
                        "runId": str(run.get("runId") or run.get("run_id") or ""),
                        "node": str(item.get("nodeId") or item.get("node") or item.get("agent") or ""),
                        "status": status,
                        "reason": reason,
                    })
            elif status in LLM_SKIPPED_STATUSES:
                skipped += 1
            else:
                continue
            total_tokens += _safe_int(item.get("totalTokens") or (item.get("usage") or {}).get("total_tokens"), 0)
    total_calls = completed + failed
    return {
        "total": total_calls,
        "succeeded": completed,
        "failed": failed,
        "skipped": skipped,
        "successRate": _rate(completed, total_calls),
        "failureRate": _rate(failed, total_calls),
        "totalTokens": total_tokens,
        "failureReasons": [
            {"reason": reason, "count": count}
            for reason, count in sorted(failure_reason_counts.items(), key=lambda pair: (-pair[1], pair[0]))[:5]
        ],
        "sampleFailures": sample_failures,
    }


def _llm_failure_reason(item: Dict[str, Any]) -> str:
    candidates = (
        item.get("failureReason"),
        item.get("failure_reason"),
        item.get("degradation_reason"),
        item.get("error"),
        item.get("errorMessage"),
        item.get("message"),
        item.get("finishReason"),
    )
    for candidate in candidates:
        text = _safe_llm_reason_text(candidate)
        if text:
            return text
    return "unspecified_failure"


def _safe_llm_reason_text(value: Any, limit: int = 160) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return ""
    redacted = SECRET_TEXT_PATTERN.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
    for marker in ("sk-", "Bearer "):
        index = redacted.find(marker)
        if index != -1:
            redacted = redacted[:index] + f"{marker}..."
    return redacted[:limit]


def _market_data_fallback_rate(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    observed = [run for run in runs if _has_market_data_observation(run)]
    fallback_count = sum(1 for run in observed if _run_has_market_data_fallback(run))
    unavailable_count = sum(1 for run in observed if _run_market_data_unavailable(run))
    return {
        "total": len(observed),
        "fallbackOrMock": fallback_count,
        "unavailable": unavailable_count,
        "fallbackRate": _rate(fallback_count, len(observed)),
        "sampleRunIds": [str(run.get("runId") or run.get("run_id") or "") for run in observed[:10]],
    }


def _signalops_tick_success_rate(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    counted = [
        item for item in samples
        if str(item.get("status") or "").upper() in SIGNALOPS_SUCCESS_STATUSES | SIGNALOPS_FAILURE_STATUSES
    ]
    total = len(counted)
    succeeded = sum(1 for item in counted if str(item.get("status") or "").upper() in SIGNALOPS_SUCCESS_STATUSES)
    failed = total - succeeded
    return {
        "total": total,
        "succeeded": succeeded,
        "failed": failed,
        "successRate": _rate(succeeded, total),
        "coverage": "latest_only",
        "sampleStatuses": [
            {
                "symbol": item.get("symbol") or "",
                "status": item.get("status") or "",
            }
            for item in counted[:10]
        ],
    }


def _stale_job_count(jobs: List[Dict[str, Any]], all_jobs: List[Dict[str, Any]]) -> Dict[str, Any]:
    stale_window = [job for job in jobs if str(job.get("status") or "").upper() == "STALE"]
    stale_current = [job for job in all_jobs if str(job.get("status") or "").upper() == "STALE"]
    return {
        "windowCount": len(stale_window),
        "currentCount": len(stale_current),
        "jobTotal": len(jobs),
        "runIds": [str(job.get("run_id") or job.get("runId") or "") for job in stale_current[:10]],
    }


def _error_budget(
    *,
    target_success_rate: float,
    run_rate: Dict[str, Any],
    llm_rate: Dict[str, Any],
    market_rate: Dict[str, Any],
    signalops_rate: Dict[str, Any],
    stale_jobs: Dict[str, Any],
) -> Dict[str, Any]:
    job_total = _safe_int(stale_jobs.get("jobTotal"), 0)
    stale_count = _safe_int(stale_jobs.get("windowCount"), 0)
    total_events = (
        _safe_int(run_rate.get("total"), 0)
        + _safe_int(llm_rate.get("total"), 0)
        + _safe_int(market_rate.get("total"), 0)
        + _safe_int(signalops_rate.get("total"), 0)
        + job_total
    )
    observed_errors = (
        _safe_int(run_rate.get("failed"), 0)
        + _safe_int(llm_rate.get("failed"), 0)
        + _safe_int(market_rate.get("fallbackOrMock"), 0)
        + _safe_int(signalops_rate.get("failed"), 0)
        + stale_count
    )
    allowed_errors = total_events * max(0.0, min(1.0, 1.0 - target_success_rate))
    if total_events <= 0:
        return {
            "targetSuccessRate": target_success_rate,
            "totalEvents": 0,
            "observedErrors": observed_errors,
            "allowedErrors": 0.0,
            "remainingErrors": 0.0,
            "consumedPercent": None,
            "remainingPercent": None,
            "status": "unknown",
        }
    consumed_percent = 100.0 if allowed_errors == 0 and observed_errors else (
        0.0 if allowed_errors == 0 else (observed_errors / allowed_errors) * 100.0
    )
    remaining_errors = allowed_errors - observed_errors
    return {
        "targetSuccessRate": target_success_rate,
        "totalEvents": total_events,
        "observedErrors": observed_errors,
        "allowedErrors": round(allowed_errors, 3),
        "remainingErrors": round(remaining_errors, 3),
        "consumedPercent": round(consumed_percent, 3),
        "remainingPercent": round(max(0.0, 100.0 - consumed_percent), 3),
        "status": "exhausted" if remaining_errors < 0 else ("burning" if consumed_percent >= 80 else "ok"),
    }


def _build_alerts(windows: Dict[str, Any], target_success_rate: float) -> List[Dict[str, Any]]:
    alerts: List[Dict[str, Any]] = []
    for label, metrics in windows.items():
        run_rate = metrics["runSuccessRate"]
        if run_rate["total"] and run_rate["successRate"] is not None and run_rate["successRate"] < target_success_rate:
            alerts.append(_alert("runSuccessRate", label, run_rate["successRate"], target_success_rate))

        llm_rate = metrics["llmCallFailureRate"]
        if llm_rate["total"] and llm_rate["failureRate"] is not None and llm_rate["failureRate"] > (1.0 - target_success_rate):
            alerts.append(_alert("llmCallFailureRate", label, llm_rate["failureRate"], 1.0 - target_success_rate, higher_is_bad=True))

        market_rate = metrics["marketDataFallbackRate"]
        if market_rate["total"] and market_rate["fallbackRate"] is not None and market_rate["fallbackRate"] > 0.2:
            alerts.append(_alert("marketDataFallbackRate", label, market_rate["fallbackRate"], 0.2, higher_is_bad=True))

        tick_rate = metrics["signalOpsTickSuccessRate"]
        if tick_rate["total"] and tick_rate["successRate"] is not None and tick_rate["successRate"] < target_success_rate:
            alerts.append(_alert("signalOpsTickSuccessRate", label, tick_rate["successRate"], target_success_rate))

        stale = metrics["staleJobs"]
        if stale["currentCount"] > 0:
            alerts.append({
                "severity": "critical" if stale["currentCount"] >= 3 else "warning",
                "metric": "staleJobs",
                "window": label,
                "message": "Stale analysis jobs are present in the local job store.",
                "value": stale["currentCount"],
                "threshold": 0,
                "runIds": stale["runIds"],
            })

        budget = metrics["errorBudget"]
        if budget.get("status") in {"burning", "exhausted"}:
            alerts.append({
                "severity": "critical" if budget["status"] == "exhausted" else "warning",
                "metric": "errorBudget",
                "window": label,
                "message": "Error budget is burning or exhausted for this observability window.",
                "value": budget.get("consumedPercent"),
                "threshold": 80,
            })
    return alerts


def _alert(
    metric: str,
    window: str,
    value: float,
    threshold: float,
    *,
    higher_is_bad: bool = False,
) -> Dict[str, Any]:
    critical = value > max(0.2, threshold * 2) if higher_is_bad else value < min(0.8, threshold)
    return {
        "severity": "critical" if critical else "warning",
        "metric": metric,
        "window": window,
        "message": f"{metric} breached deployment alert threshold.",
        "value": round(value, 6),
        "threshold": round(threshold, 6),
    }


def _overall_status(alerts: List[Dict[str, Any]], budget_status: str | None) -> str:
    if any(alert.get("severity") == "critical" for alert in alerts):
        return "critical"
    if alerts or budget_status == "burning":
        return "warning"
    if budget_status == "unknown":
        return "unknown"
    return "healthy"


def _trend_vs_baseline(windows: Dict[str, Any], primary_label: str, baseline_label: str) -> Dict[str, Any]:
    primary = windows.get(primary_label)
    baseline = windows.get(baseline_label)
    if not primary or not baseline or primary_label == baseline_label:
        return {}
    return {
        "baselineWindow": baseline_label,
        "runSuccessRateDelta": _delta(
            primary["runSuccessRate"].get("successRate"),
            baseline["runSuccessRate"].get("successRate"),
        ),
        "llmFailureRateDelta": _delta(
            primary["llmCallFailureRate"].get("failureRate"),
            baseline["llmCallFailureRate"].get("failureRate"),
        ),
        "llmSuccessRateDelta": _delta(
            primary["llmCallFailureRate"].get("successRate"),
            baseline["llmCallFailureRate"].get("successRate"),
        ),
        "marketDataFallbackRateDelta": _delta(
            primary["marketDataFallbackRate"].get("fallbackRate"),
            baseline["marketDataFallbackRate"].get("fallbackRate"),
        ),
        "signalOpsTickSuccessRateDelta": _delta(
            primary["signalOpsTickSuccessRate"].get("successRate"),
            baseline["signalOpsTickSuccessRate"].get("successRate"),
        ),
    }


def _signalops_tick_samples(status: Dict[str, Any]) -> List[Dict[str, Any]]:
    result = status.get("last_tick_result")
    if not isinstance(result, dict) or not result:
        return []
    timestamp = (
        result.get("updated_at")
        or result.get("timestamp")
        or status.get("last_tick_at")
        or status.get("last_success_at")
    )
    nested = result.get("results") if isinstance(result.get("results"), list) else []
    if nested:
        samples = []
        for item in nested:
            if isinstance(item, dict):
                samples.append({
                    "status": item.get("status"),
                    "symbol": item.get("symbol"),
                    "updated_at": item.get("updated_at") or timestamp,
                })
        return samples
    return [{
        "status": result.get("status"),
        "symbol": result.get("symbol") or status.get("symbol") or "",
        "updated_at": timestamp,
    }]


def _has_market_data_observation(run: Dict[str, Any]) -> bool:
    return bool(run.get("dataMode") or run.get("marketData") or run.get("dataSources"))


def _run_has_market_data_fallback(run: Dict[str, Any]) -> bool:
    mode = str(run.get("dataMode") or "").upper()
    if mode in {"FALLBACK", "MIXED", "MOCK", "UNAVAILABLE", "FAILED"}:
        return True
    market = run.get("marketData") if isinstance(run.get("marketData"), dict) else {}
    if str(market.get("status") or "").upper() not in {"", "READY"}:
        return True
    quote = market.get("quote") if isinstance(market.get("quote"), dict) else {}
    source = str(quote.get("source") or market.get("provider") or "").lower()
    if "fallback" in source or "mock" in source:
        return True
    data_sources = run.get("dataSources") if isinstance(run.get("dataSources"), dict) else {}
    summary = data_sources.get("summary") if isinstance(data_sources.get("summary"), dict) else {}
    overall = str(summary.get("overallDataMode") or "").upper()
    if overall and overall != "LIVE":
        return True
    sources = data_sources.get("sources") if isinstance(data_sources.get("sources"), dict) else {}
    for source_item in sources.values():
        if not isinstance(source_item, dict):
            continue
        source_mode = str(source_item.get("dataMode") or "").upper()
        if source_mode in {"FALLBACK", "MIXED", "MOCK", "UNAVAILABLE"}:
            return True
        if source_item.get("fallbackUsed"):
            return True
        chain = source_item.get("fallbackChain") or source_item.get("degradationChain")
        if isinstance(chain, list) and chain:
            return True
    return False


def _run_market_data_unavailable(run: Dict[str, Any]) -> bool:
    market = run.get("marketData") if isinstance(run.get("marketData"), dict) else {}
    if str(market.get("status") or "").upper() in {"FAILED", "BLOCKED", "UNAVAILABLE"}:
        return True
    data_sources = run.get("dataSources") if isinstance(run.get("dataSources"), dict) else {}
    summary = data_sources.get("summary") if isinstance(data_sources.get("summary"), dict) else {}
    return str(summary.get("overallStatus") or "").upper() == "ALL_MOCK"


def _item_in_window(
    item: Dict[str, Any],
    start: datetime,
    end: datetime,
    keys: Iterable[str],
) -> bool:
    timestamp = _first_timestamp(item, keys)
    if timestamp is None:
        return False
    return start <= timestamp <= end


def _first_timestamp(item: Dict[str, Any], keys: Iterable[str]) -> Optional[datetime]:
    for key in keys:
        parsed = _parse_timestamp(item.get(key))
        if parsed is not None:
            return parsed
    return None


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return _ensure_utc(parsed)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _window_label(hours: int) -> str:
    if hours == 24 * 7:
        return "7d"
    if hours == 24 * 30:
        return "30d"
    return f"{hours}h"


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 6)


def _delta(current: Any, baseline: Any) -> float | None:
    if current is None or baseline is None:
        return None
    return round(float(current) - float(baseline), 6)


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
