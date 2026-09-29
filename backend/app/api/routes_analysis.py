import copy
from datetime import datetime, timedelta, timezone
import logging
import os
import uuid
import asyncio
import json
import sqlite3

from fastapi import APIRouter, HTTPException, Path, Query

from ..core.constants import NODE_ID_PATH_PATTERN, RUN_ID_PATH_PATTERN
from ..core.agent_executor import execute_run_with_llm
from ..core import (
    agent_runtime_store,
    analysis_job_store,
    analysis_run_create,
    analysis_run_compare,
    analysis_run_persistence,
    analysis_run_retry,
    analysis_run_start,
)
from ..core.analysis_lifecycle_service import bind_analysis_lifecycle
from ..core.file_utils import write_json_atomic
from ..core.analysis_dashboard_summary import build_analysis_dashboard_summary
from ..core.analysis_run_registry import bind_analysis_run_store
from ..core.data_pipeline import compression_artifact_path, mark_summary_persisted, summarize_run
from ..core.agent_framework import (
    apply_agent_framework_to_run,
    normalize_run_artifacts,
)
from ..core.final_report_store import final_report_store
from ..core.agent_runtime_store import get_runtime_summary, load_persisted_runs
from ..core.knowledge_store import create_learning_candidate_from_run, get_active_knowledge_context
from ..core.market_data_runner import hydrate_run_with_market_data
from ..core.portfolio_store import get_snapshot, normalize_symbol
from ..core.plugin_runtime import plugin_runtime_planner
from ..core.plugin_store import plugin_store
from ..core.research_store import research_loop_store
from ..mock.scenarios import mock_scenarios
from ..models.analysis import (
    AgentNodeBoundary,
    AnalysisRun,
    CreateAnalysisRequest,
    CreateAnalysisResponse,
    StartAnalysisResponse,
)
from ..db.repositories import RunRepository


router = APIRouter()
logger = logging.getLogger(__name__)
CREATE_MARKET_DATA_HYDRATION_TIMEOUT_SECONDS = 8.0
MARKET_DATA_PREFLIGHT_BLOCKED_CATEGORY = "MARKET_DATA_PREFLIGHT_BLOCKED"
MARKET_DATA_PREFLIGHT_FAILED_NODE_ID = "data_reliability_engine"
MARKET_DATA_PREFLIGHT_BLOCK_REASON = "实时行情拉取失败，已在启动前阻断；未调用大模型 Agent。"
MARKET_DATA_PREFLIGHT_SKIP_REASON = "实时行情不可用，未调用大模型 Agent。"
MARKET_DATA_PREFLIGHT_BLOCKED_PATHS = [
    "LLM_AGENT_EXECUTION",
    "DOWNSTREAM_ANALYSIS",
    "BUY_CANDIDATE",
    "ADD_CANDIDATE",
]


async def _runtime_summary_with_plugin_plan() -> dict:
    runtime_summary = get_runtime_summary()
    plugins = await plugin_store.list_plugins()
    runtime_summary["pluginRuntimePlan"] = plugin_runtime_planner.build_plan(plugins)
    return runtime_summary


def _create_market_data_hydration_timeout_seconds() -> float:
    raw_value = (
        os.getenv("ANALYSIS_CREATE_MARKET_DATA_TIMEOUT_SECONDS")
        or os.getenv("TIANYUAN_CREATE_MARKET_DATA_TIMEOUT_SECONDS")
        or ""
    ).strip()
    if not raw_value:
        return CREATE_MARKET_DATA_HYDRATION_TIMEOUT_SECONDS
    try:
        return max(0.1, float(raw_value))
    except ValueError:
        logger.warning("Invalid create market data timeout value: %s", raw_value)
        return CREATE_MARKET_DATA_HYDRATION_TIMEOUT_SECONDS


async def _hydrate_created_run_with_market_data(run_data: dict, symbol: str) -> dict:
    timeout_seconds = _create_market_data_hydration_timeout_seconds()
    try:
        return await asyncio.wait_for(
            hydrate_run_with_market_data(run_data, symbol),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        error = f"Market data hydration timed out after {timeout_seconds:g}s during run creation."
        logger.warning("%s symbol=%s run_id=%s", error, symbol, run_data.get("runId"))
        _mark_create_market_data_degraded(
            run_data,
            symbol,
            error="行情水合超时，任务已先创建；请在运行台查看降级状态。",
            reason_code="CREATE_MARKET_DATA_TIMEOUT",
            timeout_seconds=timeout_seconds,
        )
        return run_data
    except Exception as exc:
        logger.warning(
            "Market data hydration failed during run creation for %s run_id=%s: %s",
            symbol,
            run_data.get("runId"),
            exc,
        )
        _mark_create_market_data_degraded(
            run_data,
            symbol,
            error="行情水合失败，任务已先创建；请在运行台查看降级状态。",
            reason_code="CREATE_MARKET_DATA_FAILED",
        )
        return run_data


def _mark_create_market_data_degraded(
    run_data: dict,
    symbol: str,
    *,
    error: str,
    reason_code: str,
    timeout_seconds: float | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    details: dict[str, object] = {
        "reason": reason_code,
        "stage": "create_analysis_run",
    }
    if timeout_seconds is not None:
        details["timeout_seconds"] = timeout_seconds

    run_data["marketData"] = {
        "status": "FAILED",
        "provider": "create_preflight",
        "profileId": "",
        "symbol": symbol,
        "quote": {},
        "error": error,
        "details": details,
        "fetchedAt": now,
    }
    run_data["dataSources"] = {
        "sources": {
            "realtime_quote": {
                "name": "实时行情",
                "provider": "create_preflight",
                "icon": "BarChart3",
                "status": "FAILED",
                "detail": error,
                "fetchedAt": now,
                "available": False,
                "error": error,
                "category": "行情",
                "dataMode": "UNAVAILABLE",
                "freshness": "",
                "confidence": 0,
                "degradationChain": [
                    {
                        "step": "create_market_data_hydration",
                        "status": "FAILED",
                        "reason": reason_code,
                    }
                ],
            }
        },
        "summary": {
            "availableCount": 0,
            "totalCount": 1,
            "availableRatio": "0/1",
            "overallStatus": "ALL_MOCK",
            "overallDataMode": "UNAVAILABLE",
            "generatedAt": now,
        },
    }
    run_data["auxiliaryData"] = {}
    run_data["dataMode"] = "UNAVAILABLE"
    run_data.setdefault("auditLog", []).append(
        {
            "eventType": "MARKET_DATA_CREATE_DEGRADED",
            "runId": run_data.get("runId", ""),
            "auditId": run_data.get("auditId", ""),
            "timestamp": now,
            "details": {**details, "error": error},
        }
    )


def _is_market_data_preflight_unavailable(run: dict) -> bool:
    market_data = run.get("marketData") if isinstance(run.get("marketData"), dict) else {}
    data_sources = run.get("dataSources") if isinstance(run.get("dataSources"), dict) else {}
    sources = data_sources.get("sources") if isinstance(data_sources.get("sources"), dict) else {}
    realtime_quote = sources.get("realtime_quote") if isinstance(sources.get("realtime_quote"), dict) else {}
    summary = data_sources.get("summary") if isinstance(data_sources.get("summary"), dict) else {}

    market_status = str(market_data.get("status") or "").upper()
    realtime_status = str(realtime_quote.get("status") or "").upper()
    realtime_mode = str(realtime_quote.get("dataMode") or "").upper()
    run_data_mode = str(run.get("dataMode") or "").upper()
    summary_mode = str(summary.get("overallDataMode") or "").upper()
    realtime_available = realtime_quote.get("available")

    return (
        market_status in {"FAILED", "ERROR"}
        or realtime_status in {"FAILED", "ERROR"}
        or realtime_mode == "UNAVAILABLE"
        or run_data_mode == "UNAVAILABLE"
        or summary_mode == "UNAVAILABLE"
        or (realtime_available is False and realtime_status in {"FAILED", "ERROR", "UNAVAILABLE"})
    )


def _market_data_preflight_error(run: dict) -> str:
    market_data = run.get("marketData") if isinstance(run.get("marketData"), dict) else {}
    data_sources = run.get("dataSources") if isinstance(run.get("dataSources"), dict) else {}
    sources = data_sources.get("sources") if isinstance(data_sources.get("sources"), dict) else {}
    realtime_quote = sources.get("realtime_quote") if isinstance(sources.get("realtime_quote"), dict) else {}
    details = market_data.get("details") if isinstance(market_data.get("details"), dict) else {}
    reason = (
        market_data.get("error")
        or realtime_quote.get("error")
        or realtime_quote.get("detail")
        or details.get("reason")
        or "实时行情不可用"
    )
    return str(reason)


def _market_data_preflight_failure_payload(run: dict) -> dict:
    market_data = run.get("marketData") if isinstance(run.get("marketData"), dict) else {}
    data_sources = run.get("dataSources") if isinstance(run.get("dataSources"), dict) else {}
    sources = data_sources.get("sources") if isinstance(data_sources.get("sources"), dict) else {}
    realtime_quote = sources.get("realtime_quote") if isinstance(sources.get("realtime_quote"), dict) else {}
    return {
        "failureCategory": MARKET_DATA_PREFLIGHT_BLOCKED_CATEGORY,
        "failedNodeId": MARKET_DATA_PREFLIGHT_FAILED_NODE_ID,
        "reason": _market_data_preflight_error(run),
        "marketDataStatus": market_data.get("status"),
        "marketDataProvider": market_data.get("provider"),
        "realtimeQuoteStatus": realtime_quote.get("status"),
        "realtimeQuoteAvailable": realtime_quote.get("available"),
        "dataMode": run.get("dataMode"),
        "llmSuppressed": True,
    }


def _append_market_data_preflight_block_events(run: dict, run_id: str, blocked_at: str, reason: str) -> None:
    payload = _market_data_preflight_failure_payload(run)
    run["streamEvents"] = [
        {
            "event_type": "NODE_FINISHED",
            "run_id": run_id,
            "node_id": MARKET_DATA_PREFLIGHT_FAILED_NODE_ID,
            "message": reason,
            "payload": {**payload, "status": "FAIL"},
            "audit_id": f"AUD_{run_id}_MARKET_DATA_PREFLIGHT_NODE",
            "timestamp": blocked_at,
        },
        {
            "event_type": "RUN_FAILED",
            "run_id": run_id,
            "node_id": MARKET_DATA_PREFLIGHT_FAILED_NODE_ID,
            "message": reason,
            "payload": payload,
            "audit_id": f"AUD_{run_id}_MARKET_DATA_PREFLIGHT_FAILED",
            "timestamp": blocked_at,
        },
    ]
    run.setdefault("auditLog", []).extend(
        [
            {
                "timestamp": blocked_at,
                "runId": run_id,
                "node": MARKET_DATA_PREFLIGHT_FAILED_NODE_ID,
                "eventType": "NODE_FINISHED",
                "message": reason,
                "statusBefore": "WAIT",
                "statusAfter": "FAIL",
                "inputHash": f"hash-input-{MARKET_DATA_PREFLIGHT_FAILED_NODE_ID}",
                "outputHash": f"hash-output-{MARKET_DATA_PREFLIGHT_FAILED_NODE_ID}-market-data-blocked",
                "auditId": f"AUD_{run_id}_MARKET_DATA_PREFLIGHT_NODE",
            },
            {
                "timestamp": blocked_at,
                "runId": run_id,
                "node": MARKET_DATA_PREFLIGHT_FAILED_NODE_ID,
                "eventType": "RUN_FAILED",
                "message": reason,
                "statusBefore": "CREATED",
                "statusAfter": "FAILED",
                "inputHash": f"hash-input-{run_id}",
                "outputHash": f"hash-output-{run_id}-market-data-blocked",
                "auditId": f"AUD_{run_id}_MARKET_DATA_PREFLIGHT_FAILED",
            },
        ]
    )


def _active_downstream_nodes_after(run: dict, node_id: str) -> set[str]:
    runtime = run.get("agentRuntime") if isinstance(run.get("agentRuntime"), dict) else {}
    enabled_order = runtime.get("enabledNodeOrder") if isinstance(runtime.get("enabledNodeOrder"), list) else []
    ordered_ids = [str(item) for item in enabled_order if str(item)]
    if node_id in ordered_ids:
        return set(ordered_ids[ordered_ids.index(node_id) + 1 :])

    node_ids = [str(node.get("id") or "") for node in run.get("nodes") or [] if isinstance(node, dict)]
    if node_id in node_ids:
        return set(node_ids[node_ids.index(node_id) + 1 :])
    return set()


def _stash_market_data_preflight_previous_artifacts(run: dict) -> None:
    block = run.setdefault("marketDataPreflightBlock", {})
    if isinstance(block.get("previousArtifacts"), dict):
        return
    block["previousArtifacts"] = {
        key: copy.deepcopy(run.get(key))
        for key in (
            "nodes",
            "guardrailHub",
            "dvg",
            "execution",
            "signalOps",
            "finalWriter",
            "finalAction",
            "killSwitch",
            "agentResults",
            "dagEvents",
            "skippedNodes",
            "tokenUsage",
            "debateArtifacts",
            "orchestratorPlan",
            "finalContext",
        )
    }


def _restore_market_data_preflight_previous_artifacts(run: dict) -> None:
    block = run.get("marketDataPreflightBlock") if isinstance(run.get("marketDataPreflightBlock"), dict) else {}
    previous = block.get("previousArtifacts") if isinstance(block.get("previousArtifacts"), dict) else {}
    if not previous:
        return
    for key, value in previous.items():
        if value is None:
            run.pop(key, None)
        else:
            run[key] = copy.deepcopy(value)
    run.pop("marketDataPreflightBlock", None)


def _mark_market_data_preflight_nodes(run: dict, reason: str) -> None:
    _stash_market_data_preflight_previous_artifacts(run)
    downstream_ids = _active_downstream_nodes_after(run, MARKET_DATA_PREFLIGHT_FAILED_NODE_ID)
    has_failed_node = False

    for node in run.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or "")
        if node_id == MARKET_DATA_PREFLIGHT_FAILED_NODE_ID:
            has_failed_node = True
            node["status"] = "FAIL"
            node["isRunning"] = False
            node["isSkipped"] = False
            node["isBlocked"] = True
            node["duration"] = 0
            node["outputSummary"] = "实时行情拉取失败，启动前阻断。"
            node["missingData"] = ["实时行情"]
            node["downgradeReasons"] = [reason]
            node["blockedPaths"] = list(MARKET_DATA_PREFLIGHT_BLOCKED_PATHS)
            raw_json = dict(node.get("rawJson") or {})
            raw_json["marketDataPreflight"] = _market_data_preflight_failure_payload(run)
            node["rawJson"] = raw_json
        elif node_id in downstream_ids:
            node["status"] = "SKIPPED"
            node["isRunning"] = False
            node["isSkipped"] = True
            node["isBlocked"] = True
            node["duration"] = 0
            node["outputSummary"] = ""
            node["downgradeReasons"] = [MARKET_DATA_PREFLIGHT_SKIP_REASON]
            node["blockedPaths"] = list(MARKET_DATA_PREFLIGHT_BLOCKED_PATHS)

    if not has_failed_node:
        run.setdefault("nodes", []).append(
            {
                "id": MARKET_DATA_PREFLIGHT_FAILED_NODE_ID,
                "name": "数据可靠性引擎",
                "status": "FAIL",
                "isRunning": False,
                "isSkipped": False,
                "isBlocked": True,
                "duration": 0,
                "auditId": "AUD_DATA_RELIABILITY_ENGINE",
                "inputSummary": "实时行情启动前检查。",
                "outputSummary": "实时行情拉取失败，启动前阻断。",
                "missingData": ["实时行情"],
                "downgradeReasons": [reason],
                "blockedPaths": list(MARKET_DATA_PREFLIGHT_BLOCKED_PATHS),
                "allowedNextActions": [],
                "rawJson": {"marketDataPreflight": _market_data_preflight_failure_payload(run)},
            }
        )


def _mark_market_data_preflight_artifacts(run: dict, reason: str) -> None:
    _mark_market_data_preflight_nodes(run, reason)
    run["finalAction"] = "WAIT"
    run["killSwitch"] = {
        "active": True,
        "level": "HARD",
        "triggerNode": MARKET_DATA_PREFLIGHT_FAILED_NODE_ID,
        "triggerRule": MARKET_DATA_PREFLIGHT_BLOCKED_CATEGORY,
        "blockedPaths": list(MARKET_DATA_PREFLIGHT_BLOCKED_PATHS),
        "allowedPaths": ["WAIT", "REVIEW_ONLY", "HOLD"],
        "finalWriterMode": "HARD_RISK_FINAL_ONLY",
        "auditId": f"AUD_KS_{MARKET_DATA_PREFLIGHT_FAILED_NODE_ID.upper()}",
    }
    dvg = dict(run.get("dvg") or {})
    critical_missing = list(dvg.get("criticalMissingData") or [])
    if "实时行情" not in critical_missing:
        critical_missing.append("实时行情")
    data_conflicts = list(dvg.get("dataConflicts") or [])
    market_error = _market_data_preflight_error(run)
    if market_error not in data_conflicts:
        data_conflicts.append(market_error)
    dvg.update(
        {
            "status": "BLOCK_BUY",
            "dataReliability": "LOW",
            "freshnessStatus": "FAILED",
            "sourceIntegrity": "FAILED",
            "hallucinationRiskLevel": "HIGH",
            "criticalMissingData": critical_missing,
            "dataConflicts": data_conflicts,
            "allowedOutputLevel": "BLOCK_BUY",
            "qiamPermission": "BLOCKED",
            "scenarioPermission": "BLOCKED",
            "executionPermission": "BLOCKED",
            "finalDecisionCap": "BLOCK_BUY",
            "hardStop": True,
        }
    )
    run["dvg"] = dvg
    run["guardrailHub"] = {
        "status": "BLOCK_BUY",
        "finalDecisionCap": "BLOCK_BUY",
        "killSwitch": run["killSwitch"],
        "dvg": dvg,
        "risk": dict(run.get("risk") or {}),
        "atrade": dict(run.get("atrade") or {}),
        "gateResults": {
            "dataPreflight": {
                "status": "BLOCK_BUY",
                "reason": reason,
                "failedNodeId": MARKET_DATA_PREFLIGHT_FAILED_NODE_ID,
            }
        },
        "warnings": [reason],
        "auditId": f"AUD_KS_{MARKET_DATA_PREFLIGHT_FAILED_NODE_ID.upper()}",
        "preflightBlock": True,
    }
    execution = dict(run.get("execution") or {})
    execution.update(
        {
            "allowedActions": ["WAIT", "REVIEW_ONLY"],
            "prohibitedActions": ["BUY_CANDIDATE", "ADD_CANDIDATE", "EXECUTION_BUY"],
            "forbiddenActions": list(MARKET_DATA_PREFLIGHT_BLOCKED_PATHS),
            "executionReachability": "NOT_REACHABLE",
            "manualConfirmationItems": ["实时行情不可用，执行前必须人工确认。"],
        }
    )
    run["execution"] = execution
    signal_ops = dict(run.get("signalOps") or {})
    signal_ops.update(
        {
            "signalStatus": "WATCH",
            "riskPassed": False,
            "dvgPassed": False,
            "executionReachable": False,
            "blockedReason": reason,
        }
    )
    run["signalOps"] = signal_ops
    final_writer = dict(run.get("finalWriter") or {})
    final_writer.update(
        {
            "mode": "HARD_RISK_FINAL_ONLY",
            "finalAction": "WAIT",
            "humanConfirmationRequired": True,
            "llmSuppressed": True,
            "blockedReason": reason,
        }
    )
    run["finalWriter"] = final_writer
    normalize_run_artifacts(run)


def _reset_market_data_preflight_retry_nodes(run: dict) -> None:
    retry_from_node_id = str((run.get("retry") or {}).get("from_node_id") or "")
    downstream_ids = _active_downstream_nodes_after(run, retry_from_node_id or MARKET_DATA_PREFLIGHT_FAILED_NODE_ID)
    retry_node_ids = set(downstream_ids)
    if retry_from_node_id:
        retry_node_ids.add(retry_from_node_id)

    for node in run.get("nodes") or []:
        if not isinstance(node, dict) or str(node.get("id") or "") not in retry_node_ids:
            continue
        node["isSkipped"] = False
        node["isBlocked"] = False
        node["missingData"] = []
        node["downgradeReasons"] = []
        node["blockedPaths"] = []


async def _block_start_for_market_data_preflight(run_id: str, run: dict, payload: dict | None) -> StartAnalysisResponse:
    blocked_at = datetime.now().isoformat()
    reason = MARKET_DATA_PREFLIGHT_BLOCK_REASON
    operator = str((payload or {}).get("operator") or "local_workbench")

    _mark_market_data_preflight_artifacts(run, reason)
    run["status"] = "FAILED"
    run["failureCategory"] = MARKET_DATA_PREFLIGHT_BLOCKED_CATEGORY
    run["failReason"] = reason
    run["updatedAt"] = blocked_at
    run["cancelRequested"] = False
    run.setdefault("llmTrace", [])
    run.setdefault("agentOutputs", {})

    job = analysis_job_store.start_job(run_id, operator=operator)
    run["job"] = analysis_job_store.mark_failed(
        run_id,
        reason,
        MARKET_DATA_PREFLIGHT_FAILED_NODE_ID,
        operator=operator,
    )
    _append_market_data_preflight_block_events(run, run_id, blocked_at, reason)
    run["marketDataPreflightBlock"] = {
        **(run.get("marketDataPreflightBlock") if isinstance(run.get("marketDataPreflightBlock"), dict) else {}),
        "status": "BLOCKED",
        "blockedAt": blocked_at,
        "reason": _market_data_preflight_error(run),
        "failedNodeId": MARKET_DATA_PREFLIGHT_FAILED_NODE_ID,
        "jobId": job.get("job_id", ""),
        "llmSuppressed": True,
    }

    runs_store[run_id] = run
    save_run(run)
    await _persist_run(run, run_id, run.get("stockCode", ""))
    await _update_research_iteration_from_run(
        run,
        action="RUN_FAILED",
        status="RUN_FAILED",
        note="Analysis run blocked before LLM execution because realtime market data was unavailable.",
    )
    return StartAnalysisResponse(run_id=run_id, status="FAILED")


def _is_legacy_mock_run(run_id: str, run: dict | None) -> bool:
    """Hide pre-real-data demo runs so they cannot be mistaken for live analysis."""
    if str(run_id).startswith("RUN_HISTORY_") or str(run_id).startswith("RUN_MOCK_"):
        return True
    if not isinstance(run, dict):
        return False
    if str(run.get("runId", "")).startswith(("RUN_HISTORY_", "RUN_MOCK_")):
        return True
    if str(run.get("auditId", "")).startswith(("AUD_RUN_MOCK", "AUD_MOCK")):
        return True
    final_writer = run.get("finalWriter") or {}
    if str(final_writer.get("auditId", "")).startswith("AUD_FW_MOCK"):
        return True
    for event in run.get("auditLog") or []:
        if not isinstance(event, dict):
            continue
        if str(event.get("runId", "")).startswith("RUN_MOCK_"):
            return True
        if str(event.get("auditId", "")).startswith(("AUD_MOCK", "AUD_NORMAL", "AUD_DISCOUNT")):
            return True
    return False


def _has_items(value: object) -> bool:
    if isinstance(value, dict):
        return bool(value)
    if isinstance(value, list):
        return bool(value)
    return False


def _is_unmaterialized_run_shell(run_id: str, run: dict | None) -> bool:
    """Hide abandoned local run shells that never materialized an execution DAG."""
    if not isinstance(run, dict):
        return False
    status = str(run.get("status") or "").upper()
    if status not in {"CREATED", "PENDING", "QUEUED", "RUNNING", STALE_RUN_STATUS}:
        return False
    if _has_items(run.get("nodes")) or _has_items(run.get("agentResults")):
        return False
    if str(run.get("stockName") or "").strip():
        return False
    if run.get("compressedSummary") or run.get("finalReportAsset"):
        return False

    if status == STALE_RUN_STATUS:
        recovery = run.get("recovery") if isinstance(run.get("recovery"), dict) else {}
        return (
            run.get("failureCategory") == "STALE_RUN_RECOVERY"
            or recovery.get("statusAfter") == STALE_RUN_STATUS
            or "watchdog" in str(run.get("failReason") or "").lower()
        )

    job = run.get("job") if isinstance(run.get("job"), dict) else {}
    job_status = str(job.get("status") or "").upper()
    return not job_status or job_status in {"PENDING", "QUEUED", "RUNNING", "CANCEL_REQUESTED"}


STALE_RUN_STATUS = "STALE"
TERMINAL_RUN_STATUSES = {"COMPLETED", "FAILED", STALE_RUN_STATUS, "CANCELLED"}
STALE_RECOVERABLE_RUN_STATUSES = {"RUNNING", "PENDING", "QUEUED"}
DEFAULT_STALE_RUN_TIMEOUT = timedelta(hours=2)
DEFAULT_ORPHANED_RUN_TIMEOUT = timedelta(seconds=60)


def _analysis_run_stale_after() -> timedelta:
    raw_seconds = os.getenv("ANALYSIS_RUN_STALE_AFTER_SECONDS")
    raw_minutes = os.getenv("ANALYSIS_RUN_STALE_AFTER_MINUTES")
    try:
        if raw_seconds:
            seconds = int(raw_seconds)
            return timedelta(seconds=max(seconds, 1))
        if raw_minutes:
            minutes = int(raw_minutes)
            return timedelta(minutes=max(minutes, 1))
    except ValueError:
        logger.warning("Invalid analysis stale timeout env; using default.")
    return DEFAULT_STALE_RUN_TIMEOUT


def _analysis_run_orphaned_after() -> timedelta:
    raw_seconds = os.getenv("ANALYSIS_RUN_ORPHANED_AFTER_SECONDS")
    try:
        if raw_seconds:
            return timedelta(seconds=max(int(raw_seconds), 1))
    except ValueError:
        logger.warning("Invalid orphaned analysis timeout env; using default.")
    return DEFAULT_ORPHANED_RUN_TIMEOUT


def _analysis_execution_mode() -> str:
    return "worker" if os.getenv("ANALYSIS_EXECUTION_MODE", "").strip().lower() == "worker" else "in_process"


def _parse_run_timestamp(value: object) -> datetime | None:
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
    if parsed.tzinfo is not None:
        return parsed.astimezone().replace(tzinfo=None)
    return parsed


@analysis_job_store._serialized_job_state
def _recover_stale_running_runs(
    store: dict[str, dict],
    *,
    now: datetime | None = None,
    stale_after: timedelta | None = None,
    active_run_ids: set[str] | None = None,
    orphaned_after: timedelta | None = None,
    source: str = "query",
) -> int:
    now = now or datetime.now()
    stale_after = stale_after or _analysis_run_stale_after()
    active_run_ids = active_run_ids or set()
    orphaned_after = orphaned_after or _analysis_run_orphaned_after()
    if analysis_job_store._load_state().get("warning"):
        return 0
    recovered = 0
    for run_id, run in list(store.items()):
        if not isinstance(run, dict):
            continue
        if run_id not in active_run_ids:
            persisted = agent_runtime_store.get_run(run_id)
            if isinstance(persisted, dict):
                run.clear()
                run.update(persisted)
        current_job = analysis_job_store.get_job(run_id)
        if current_job:
            run["job"] = current_job
            if current_job.get("status") in analysis_job_store.TERMINAL_JOB_STATUSES:
                continue
            lease_expires_at = _parse_run_timestamp(current_job.get("lease_expires_at"))
            if current_job.get("status") in analysis_job_store.LEASE_PROTECTED_JOB_STATUSES and lease_expires_at and now < lease_expires_at:
                continue
        if run.get("status") not in STALE_RECOVERABLE_RUN_STATUSES:
            continue
        if _is_legacy_mock_run(run_id, run):
            continue
        stale_timeout = stale_after
        is_stale = _is_stale_running_run(run, now, stale_after)
        if not is_stale and _is_orphaned_running_run(
            run_id,
            run,
            now,
            active_run_ids=active_run_ids,
            orphaned_after=orphaned_after,
        ):
            is_stale = True
            stale_timeout = orphaned_after
        if not is_stale:
            continue
        if not _mark_run_stale(run_id, run, now, stale_timeout, source):
            continue
        try:
            save_run(run)
        except Exception:
            logger.exception("Failed to persist stale recovery for run %s", run_id)
        recovered += 1
    return recovered


def _is_stale_running_run(run: dict, now: datetime, stale_after: timedelta) -> bool:
    last_activity = _latest_run_activity_at(run)
    if last_activity is None:
        return True
    return now - last_activity >= stale_after


def _is_orphaned_running_run(
    run_id: str,
    run: dict,
    now: datetime,
    *,
    active_run_ids: set[str],
    orphaned_after: timedelta,
) -> bool:
    if run.get("status") != "RUNNING" or run_id in active_run_ids:
        return False
    job = run.get("job") if isinstance(run.get("job"), dict) else {}
    job_status = str(job.get("status") or "").upper()
    if job_status and job_status not in {"PENDING", "QUEUED", "RUNNING", "CANCEL_REQUESTED"}:
        return False
    last_activity = _latest_run_activity_at(run)
    if last_activity is None:
        return True
    return now - last_activity >= orphaned_after


def _latest_run_activity_at(run: dict) -> datetime | None:
    job = run.get("job") if isinstance(run.get("job"), dict) else {}
    candidates = [
        _parse_run_timestamp(job.get("worker_heartbeat_at")),
        _parse_run_timestamp(job.get("updated_at")),
        _parse_run_timestamp(job.get("started_at")),
        _parse_run_timestamp(run.get("updatedAt")),
        _parse_run_timestamp(run.get("createdAt")),
    ]
    parsed = [item for item in candidates if item is not None]
    return max(parsed) if parsed else None


def _mark_run_stale(
    run_id: str,
    run: dict,
    now: datetime,
    stale_after: timedelta,
    source: str,
) -> bool:
    recovered_at = now.isoformat()
    last_updated_at = run.get("updatedAt") or run.get("createdAt") or ""
    status_before = str(run.get("status") or "RUNNING")
    audit_id = f"AUD_STALE_{run_id}"
    reason = (
        f"分析运行由 watchdog 自动恢复：任务长时间停留在 {status_before}，"
        f"自 {last_updated_at or '未知时间'} 后没有更新。"
    )
    recovery = {
        "status": STALE_RUN_STATUS,
        "reason": reason,
        "source": source,
        "statusBefore": status_before,
        "statusAfter": STALE_RUN_STATUS,
        "lastUpdatedAt": last_updated_at,
        "recoveredAt": recovered_at,
        "staleAfterSeconds": int(stale_after.total_seconds()),
        "auditId": audit_id,
    }

    job = analysis_job_store.mark_stale(run_id, reason, _failed_node_from_run(run), operator="watchdog")
    if job.get("status") != STALE_RUN_STATUS or job.get("state_update_rejected"):
        run["job"] = job
        return False

    run["status"] = STALE_RUN_STATUS
    run["failureCategory"] = "STALE_RUN_RECOVERY"
    run["failReason"] = reason
    run["recovery"] = recovery
    run.setdefault("recoveryEvents", []).append(recovery)
    run["updatedAt"] = recovered_at

    for node in run.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        if node.get("isRunning") or node.get("status") == "RUNNING":
            node["isRunning"] = False
            node["status"] = "FAIL"
            node.setdefault("downgradeReasons", []).append(reason)

    run["job"] = job

    run.setdefault("streamEvents", []).append(
        {
            "event_type": "RUN_STALE_RECOVERED",
            "run_id": run_id,
            "node_id": "system",
            "message": reason,
            "payload": recovery,
            "audit_id": audit_id,
            "timestamp": recovered_at,
        }
    )
    run.setdefault("auditLog", []).append(
        {
            "timestamp": recovered_at,
            "runId": run_id,
            "node": "system",
            "eventType": "RUN_STALE_RECOVERED",
            "message": reason,
            "statusBefore": status_before,
            "statusAfter": STALE_RUN_STATUS,
            "inputHash": f"hash-input-{run_id}",
            "outputHash": "hash-output-system-RUN_STALE_RECOVERED",
            "auditId": audit_id,
        }
    )
    return True


def _active_analysis_task_run_ids() -> set[str]:
    return {run_id for run_id, task in analysis_tasks.items() if task and not task.done()}


def _reconcile_analysis_run_jobs(source: str = "query") -> dict[str, int]:
    stale_after = _analysis_run_stale_after()
    orphaned_after = _analysis_run_orphaned_after()
    run_now = datetime.now()
    job_now = datetime.now(timezone.utc)
    active_run_ids = _active_analysis_task_run_ids()
    recovered_runs = _recover_stale_running_runs(
        runs_store,
        now=run_now,
        stale_after=stale_after,
        active_run_ids=active_run_ids,
        orphaned_after=orphaned_after,
        source=source,
    )
    recovered_jobs = analysis_job_store.reconcile_stale_jobs(
        stale_after_seconds=int(stale_after.total_seconds()),
        now=job_now,
        active_run_ids=active_run_ids,
        operator="watchdog",
    )
    saved_runs = 0
    for job in recovered_jobs:
        run_id = str(job.get("run_id") or "")
        run = runs_store.get(run_id)
        if not isinstance(run, dict) or _is_legacy_mock_run(run_id, run):
            continue
        if run.get("status") == STALE_RUN_STATUS:
            run["job"] = job
            try:
                save_run(run)
                saved_runs += 1
            except Exception:
                logger.exception("Failed to persist stale job reconciliation for run %s", run_id)
    return {"runs": recovered_runs, "jobs": len(recovered_jobs), "savedRuns": saved_runs}


def _loaded_recoverable_runs(run_ids: set[str] | None = None) -> dict[str, dict]:
    active_run_ids = _active_analysis_task_run_ids()
    selected: dict[str, dict] = {}
    requested_run_ids = {str(run_id) for run_id in run_ids or set() if str(run_id)}
    for store_run_id, run in list(runs_store.items()):
        if not isinstance(run, dict):
            continue
        run_id = str(run.get("runId") or store_run_id)
        if requested_run_ids and run_id not in requested_run_ids and store_run_id not in requested_run_ids:
            continue
        run = _get_run_or_load(run_id) or run
        status = str(run.get("status") or "").upper()
        if run_id in active_run_ids or status in STALE_RECOVERABLE_RUN_STATUSES:
            selected[run_id] = run
    return selected


def _reconcile_loaded_analysis_run_jobs(
    source: str = "query",
    *,
    run_ids: set[str] | None = None,
) -> dict[str, int]:
    selected_runs = _loaded_recoverable_runs(run_ids)
    if not selected_runs:
        return {"runs": 0, "jobs": 0, "savedRuns": 0}
    recovered_runs = _recover_stale_running_runs(
        selected_runs,
        now=datetime.now(),
        stale_after=_analysis_run_stale_after(),
        active_run_ids=_active_analysis_task_run_ids(),
        orphaned_after=_analysis_run_orphaned_after(),
        source=source,
    )
    return {"runs": recovered_runs, "jobs": 0, "savedRuns": 0}


def _list_analysis_jobs_sync(limit: int, offset: int = 0, statuses: list[str] | None = None) -> list[dict]:
    _reconcile_analysis_run_jobs(source="jobs_list")
    return analysis_job_store.list_jobs(limit=limit, offset=offset, statuses=statuses)


def _summarize_analysis_jobs_sync(limit: int, offset: int = 0, statuses: list[str] | None = None) -> dict:
    _reconcile_analysis_run_jobs(source="jobs_summary")
    summary = analysis_job_store.summarize_jobs(limit=limit, offset=offset, statuses=statuses)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **summary,
    }


def _list_analysis_job_attempts_sync(
    *,
    run_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
    statuses: list[str] | None = None,
) -> list[dict]:
    _reconcile_analysis_run_jobs(source="job_attempts_list")
    try:
        return analysis_job_store.list_sqlite_attempts(run_id=run_id, limit=limit, offset=offset, statuses=statuses)
    except sqlite3.OperationalError as exc:
        if analysis_job_store._is_sqlite_locked(exc):
            logger.warning("Skipped listing analysis job attempts from locked SQLite mirror; falling back to JSON.")
            return analysis_job_store.list_json_attempts(run_id=run_id, limit=limit, offset=offset, statuses=statuses)
        raise


def _coerce_query_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_query_string(value) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _coerce_query_list(value) -> list[str] | None:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str) and value.strip():
        return [value]
    return None


def _get_analysis_run_job_sync(run_id: str) -> dict | None:
    _reconcile_analysis_run_jobs(source="job_detail")
    return analysis_job_store.get_job(run_id)


def _list_analysis_run_summaries_sync() -> list[dict]:
    index_summaries = _load_summary_index()
    loaded_recoverable_run_ids = set(_loaded_recoverable_runs())
    _reconcile_loaded_analysis_run_jobs(source="list")
    if index_summaries or not runs_store:
        return _summaries_with_loaded_overrides(
            index_summaries,
            force_overlay_run_ids=loaded_recoverable_run_ids,
        )

    summaries = []
    for run_id, run in list(runs_store.items()):
        if _is_legacy_mock_run(run_id, run):
            runs_store.pop(run_id, None)
            continue
        summary = _summary_from_run(run)
        if summary:
            summaries.append(summary)

    return _sort_summaries(summaries)


def _run_missing_framework_nodes(run: dict) -> bool:
    nodes = run.get("nodes")
    return not isinstance(nodes, list) or not nodes


async def _ensure_run_framework_ready(run_id: str, run: dict) -> bool:
    if not _run_missing_framework_nodes(run):
        return False
    runtime_summary = await _runtime_summary_with_plugin_plan()
    request_payload = {
        "symbol": run.get("stockCode") or run.get("symbol") or "UNKNOWN",
        "task_type": run.get("taskType") or run.get("task_type") or "position_review",
        "run_mode": run.get("runMode") or run.get("run_mode") or "STANDARD_MODE",
    }
    rebuilt = apply_agent_framework_to_run(run, request_payload, runtime_summary)
    if rebuilt is not run:
        run.clear()
        run.update(rebuilt)
    return True


RUN_SUMMARY_INDEX_NAME = "analysis_run_index.json"
runs_store: dict[str, dict] = {}
bind_analysis_run_store(lambda: runs_store, _is_legacy_mock_run, loader=lambda run_id: _get_run_or_load(run_id))
analysis_tasks: dict[str, asyncio.Task] = {}
_analysis_history_loaded = False
_analysis_history_loading = False


def _history_index_path():
    return agent_runtime_store.RUNS_DIR.parent / RUN_SUMMARY_INDEX_NAME


def _summary_from_run(run: dict, *, include_job_lookup: bool = True) -> dict | None:
    run_id = str(run.get("runId") or "")
    if not run_id or _is_legacy_mock_run(run_id, run) or _is_unmaterialized_run_shell(run_id, run):
        return None
    compressed = bool(run.get("compressedSummary"))
    compressed_summary = run.get("compressedSummary") or {}
    return {
        "runId": run_id,
        "stockCode": run.get("stockCode", ""),
        "stockName": run.get("stockName", ""),
        "taskType": run.get("taskType", ""),
        "runMode": run.get("runMode", ""),
        "status": run.get("status", ""),
        "failReason": run.get("failReason", ""),
        "failureCategory": run.get("failureCategory", ""),
        "recovery": run.get("recovery"),
        "job": (analysis_job_store.get_job(run_id) if include_job_lookup else None) or run.get("job"),
        "finalAction": run.get("finalWriter", {}).get("finalAction") or run.get("finalAction", "WAIT"),
        "createdAt": run.get("createdAt", ""),
        "updatedAt": run.get("updatedAt", ""),
        "compressed": compressed,
        "compressedAt": compressed_summary.get("compressed_at")
            or compressed_summary.get("created_at")
            or run.get("compressedAt"),
        "compressedArtifactPath": compression_artifact_path(run_id) if compressed else None,
    }


def _sort_summaries(summaries: list[dict]) -> list[dict]:
    return sorted(
        summaries,
        key=lambda item: item.get("updatedAt") or item.get("createdAt") or "",
        reverse=True,
    )


def _load_summary_index() -> list[dict]:
    path = _history_index_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict) and item.get("runId")]


def _write_summary_index(summaries: list[dict]) -> None:
    path = _history_index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _sort_summaries(summaries)
    write_json_atomic(path, payload)


def _index_with_run_summary(run: dict) -> list[dict]:
    summary = _summary_from_run(run)
    current = [item for item in _load_summary_index() if item.get("runId") != run.get("runId")]
    if summary:
        current.append(summary)
    return _sort_summaries(current)


def _remove_run_from_summary_index(run_id: str) -> None:
    _write_summary_index([item for item in _load_summary_index() if item.get("runId") != run_id])


def _loaded_summary_overlay_runs(
    index_summaries: list[dict],
    *,
    force_overlay_run_ids: set[str] | None = None,
) -> list[tuple[str, dict]]:
    indexed_ids = {str(item.get("runId")) for item in index_summaries if item.get("runId")}
    forced_ids = {str(run_id) for run_id in force_overlay_run_ids or set() if str(run_id)}
    include_all_loaded = not indexed_ids
    active_run_ids = _active_analysis_task_run_ids()
    overlays: list[tuple[str, dict]] = []
    for store_run_id, run in list(runs_store.items()):
        if not isinstance(run, dict):
            continue
        run_id = str(run.get("runId") or store_run_id)
        status = str(run.get("status") or "").upper()
        if (
            include_all_loaded
            or run_id not in indexed_ids
            or run_id in forced_ids
            or store_run_id in forced_ids
            or run_id in active_run_ids
            or status in STALE_RECOVERABLE_RUN_STATUSES
            or _is_legacy_mock_run(run_id, run)
            or _is_unmaterialized_run_shell(run_id, run)
        ):
            overlays.append((run_id, run))
    return overlays


def _summaries_with_loaded_overrides(
    index_summaries: list[dict],
    *,
    force_overlay_run_ids: set[str] | None = None,
) -> list[dict]:
    by_id = {str(item.get("runId")): item for item in index_summaries if item.get("runId")}
    for run_id, run in _loaded_summary_overlay_runs(
        index_summaries,
        force_overlay_run_ids=force_overlay_run_ids,
    ):
        summary = _summary_from_run(run)
        if summary:
            by_id[summary["runId"]] = summary
        else:
            by_id.pop(run_id, None)
    return _sort_summaries(list(by_id.values()))


@analysis_job_store._serialized_job_state
def save_run(run_data: dict) -> None:
    agent_runtime_store.save_run(run_data)
    try:
        _write_summary_index(_index_with_run_summary(run_data))
    except Exception:
        logger.exception("Failed to update analysis run summary index for %s", run_data.get("runId"))


def delete_run(run_id: str) -> bool:
    deleted = agent_runtime_store.delete_run(run_id)
    if deleted:
        try:
            _remove_run_from_summary_index(run_id)
        except Exception:
            logger.exception("Failed to remove analysis run summary index entry for %s", run_id)
    return deleted


def _get_run_or_load(run_id: str) -> dict | None:
    if not agent_runtime_store.valid_run_storage_id(run_id):
        return None
    if agent_runtime_store.is_run_hidden(run_id):
        runs_store.pop(run_id, None)
        return None
    run = runs_store.get(run_id)
    if isinstance(run, dict) and run_id in _active_analysis_task_run_ids():
        return run
    loaded = agent_runtime_store.get_run(run_id)
    if not isinstance(loaded, dict) or _is_legacy_mock_run(run_id, loaded):
        return run if isinstance(run, dict) else None
    if isinstance(run, dict):
        run.clear()
        run.update(loaded)
        return run
    runs_store[run_id] = loaded
    return loaded


def _require_run_or_404(run_id: str) -> dict:
    run = _get_run_or_load(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if _is_legacy_mock_run(run_id, run):
        runs_store.pop(run_id, None)
        raise HTTPException(status_code=410, detail="Legacy mock run has been hidden. Please create a new real-data task.")
    return run


def warm_analysis_history_index() -> dict[str, int]:
    global _analysis_history_loaded, _analysis_history_loading
    if _analysis_history_loading:
        return {"loaded": len(runs_store), "indexed": len(_load_summary_index())}
    _analysis_history_loading = True
    try:
        index_summaries = _load_summary_index()
        if index_summaries:
            if not runs_store:
                _analysis_history_loaded = True
                return {"loaded": 0, "indexed": len(index_summaries)}
            loaded_recoverable_run_ids = set(_loaded_recoverable_runs())
            _reconcile_loaded_analysis_run_jobs(source="startup_warm")
            summaries = _summaries_with_loaded_overrides(
                index_summaries,
                force_overlay_run_ids=loaded_recoverable_run_ids,
            )
            if summaries != index_summaries:
                _write_summary_index(summaries)
            _analysis_history_loaded = True
            return {"loaded": len(runs_store), "indexed": len(summaries)}

        loaded = {
            run_id: run
            for run_id, run in load_persisted_runs().items()
            if not _is_legacy_mock_run(run_id, run)
        }
        loaded.update({run_id: run for run_id, run in list(runs_store.items()) if isinstance(run, dict)})
        runs_store.clear()
        runs_store.update(loaded)
        _reconcile_analysis_run_jobs(source="startup_warm")
        summaries = []
        for run in list(runs_store.values()):
            summary = _summary_from_run(run)
            if summary:
                summaries.append(summary)
        _write_summary_index(summaries)
        _analysis_history_loaded = True
        return {"loaded": len(runs_store), "indexed": len(summaries)}
    finally:
        _analysis_history_loading = False


def initialize_history_runs():
    """初始化一些模拟历史项目"""
    scenario_keys = list(mock_scenarios.keys())
    stock_codes = ["603663", "000001", "000002", "600519", "601318"]
    stock_names = ["柯利达", "平安银行", "万科A", "贵州茅台", "中国平安"]
    
    for i in range(5):
        scenario_key = scenario_keys[i % len(scenario_keys)]
        base_scenario = mock_scenarios[scenario_key]
        
        run_id = f"RUN_HISTORY_{datetime.now().strftime('%Y%m%d')}_{i:03d}"
        created_at = (datetime.now() - timedelta(hours=i * 3 + 1)).isoformat()
        updated_at = (datetime.now() - timedelta(hours=i * 3)).isoformat()
        
        run_data = {
            **base_scenario,
            "runId": run_id,
            "auditId": f"AUD_{run_id}",
            "stockCode": stock_codes[i],
            "stockName": stock_names[i],
            "createdAt": created_at,
            "updatedAt": updated_at,
            "status": "COMPLETED",
        }
        
        runs_store[run_id] = run_data
        save_run(run_data)

if os.getenv("SEED_MOCK_HISTORY") == "1":
    initialize_history_runs()


def _real_run_seed(template: dict) -> dict:
    return analysis_run_create.real_run_seed(template)


@router.post("/analysis/runs", response_model=CreateAnalysisResponse)
async def create_analysis_run(request: CreateAnalysisRequest):
    run_id = f"RUN_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:8]}"
    research_loop_id = await _validate_research_context(
        request.research_loop_id,
        request.research_iteration_id,
    )
    scenario_template = copy.deepcopy(mock_scenarios.get(request.scenario_id, mock_scenarios["qiam_discounted"]))
    runtime_summary = await _runtime_summary_with_plugin_plan()
    try:
        run_data = await analysis_run_create.build_created_run(
            request=request,
            run_id=run_id,
            research_loop_id=research_loop_id,
            scenario_template=scenario_template,
            runtime_summary=runtime_summary,
            knowledge_context=get_active_knowledge_context(),
            get_snapshot=get_snapshot,
            normalize_symbol=normalize_symbol,
            hydrate_run_with_market_data=_hydrate_created_run_with_market_data,
            apply_agent_framework_to_run=apply_agent_framework_to_run,
        )
    except analysis_run_create.AnalysisRunCreateError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    if request.research_iteration_id:
        await _update_research_iteration_from_run(
            run_data,
            action="ATTACH_RUN",
            status="RUN_CREATED",
            note="Analysis run created from research context.",
        )

    runs_store[run_id] = run_data

    await _persist_run(run_data, run_id, request.symbol)

    return CreateAnalysisResponse(
        run_id=run_id,
        status="CREATED",
        stream_url=f"/api/analysis/runs/{run_id}/stream",
    )


@router.post("/analysis/runs/{run_id}/start", response_model=StartAnalysisResponse)
async def start_analysis_run(run_id: str, payload: dict | None = None):
    run = _get_run_or_load(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    _reconcile_analysis_run_jobs(source="start")

    run = _get_run_or_load(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    try:
        preflight = analysis_run_start.check_start_preflight(run, terminal_statuses=TERMINAL_RUN_STATUSES)
    except analysis_run_start.AnalysisRunStartError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    if not preflight.should_start:
        return StartAnalysisResponse(run_id=run_id, status=preflight.status)

    if await _ensure_run_framework_ready(run_id, run):
        save_run(run)

    if _is_market_data_preflight_unavailable(run):
        return await _block_start_for_market_data_preflight(run_id, run, payload)

    execution_mode = _analysis_execution_mode()
    start_result = analysis_run_start.prepare_start(
        run,
        run_id,
        execution_mode=execution_mode,
        payload=payload,
        start_job=analysis_job_store.start_job,
    )
    runs_store[run_id] = run
    save_run(run)
    if not start_result.should_schedule_background_task:
        return StartAnalysisResponse(run_id=run_id, status=start_result.status)

    analysis_tasks[run_id] = asyncio.create_task(
        _execute_and_persist_run(run_id, expected_job_id=str((run.get("job") or {}).get("job_id") or ""))
    )

    return StartAnalysisResponse(
        run_id=run_id,
        status=start_result.status,
    )


@router.get("/analysis/jobs")
async def list_analysis_jobs(
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=10000),
    status: list[str] | None = Query(default=None),
):
    limit_value = _coerce_query_int(limit, 100)
    offset_value = _coerce_query_int(offset, 0)
    return await asyncio.to_thread(_list_analysis_jobs_sync, limit_value, offset_value, _coerce_query_list(status))


@router.get("/analysis/jobs/summary")
async def summarize_analysis_jobs(
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=10000),
    status: list[str] | None = Query(default=None),
):
    limit_value = _coerce_query_int(limit, 100)
    offset_value = _coerce_query_int(offset, 0)
    return await asyncio.to_thread(_summarize_analysis_jobs_sync, limit_value, offset_value, _coerce_query_list(status))


@router.get("/analysis/jobs/attempts")
async def list_analysis_job_attempts(
    run_id: str | None = Query(default=None, pattern=RUN_ID_PATH_PATTERN),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=10000),
    status: list[str] | None = Query(default=None),
):
    limit_value = _coerce_query_int(limit, 100)
    offset_value = _coerce_query_int(offset, 0)
    return await asyncio.to_thread(
        _list_analysis_job_attempts_sync,
        run_id=_coerce_query_string(run_id),
        limit=limit_value,
        offset=offset_value,
        statuses=_coerce_query_list(status),
    )


@router.get("/analysis/runs/{run_id}/job")
async def get_analysis_run_job(run_id: str = Path(..., pattern=RUN_ID_PATH_PATTERN)):
    job = await asyncio.to_thread(_get_analysis_run_job_sync, run_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/analysis/runs/{run_id}/cancel")
async def cancel_analysis_run(run_id: str = Path(..., pattern=RUN_ID_PATH_PATTERN), payload: dict | None = None):
    run = _get_run_or_load(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.get("status") in {"COMPLETED", "FAILED", STALE_RUN_STATUS, "CANCELLED"}:
        raise HTTPException(status_code=409, detail=f"Run is already in terminal status: {run.get('status')}")

    operator = str((payload or {}).get("operator") or "local_workbench")
    previous_status = str(run.get("status") or "").upper()
    existing_job = analysis_job_store.get_job(run_id) or run.get("job") or {}
    existing_job_status = str(existing_job.get("status") or "").upper() if isinstance(existing_job, dict) else ""
    job = analysis_job_store.request_cancel(run_id, operator=operator)
    run["cancelRequested"] = True
    run["job"] = job
    run["updatedAt"] = datetime.now().isoformat()
    task = analysis_tasks.get(run_id)
    if task and not task.done():
        _mark_run_cancelled(run_id, run, reason="Analysis run cancelled by operator request.")
        job = analysis_job_store.mark_cancelled(run_id, "cancelled_by_user", operator=operator)
        run["job"] = job
        task.cancel()
    else:
        if previous_status == "RUNNING" or existing_job_status == "RUNNING":
            save_run(run)
            return {"run_id": run_id, "status": run.get("status"), "job": job}
        _mark_run_cancelled(run_id, run, reason="Analysis run cancelled before execution started.")
        job = analysis_job_store.mark_cancelled(run_id, "cancelled_before_execution", operator=operator)
        run["job"] = job
    save_run(run)
    return {"run_id": run_id, "status": run.get("status"), "job": job}


@router.post("/analysis/runs/{run_id}/retry")
async def retry_analysis_run(run_id: str = Path(..., pattern=RUN_ID_PATH_PATTERN), payload: dict | None = None):
    run = _get_run_or_load(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    payload = payload or {}
    operator = str(payload.get("operator") or "local_workbench")
    retry_market_data_preflight = run.get("failureCategory") == MARKET_DATA_PREFLIGHT_BLOCKED_CATEGORY
    if retry_market_data_preflight and not payload.get("from_node_id"):
        payload = {**payload, "from_node_id": MARKET_DATA_PREFLIGHT_FAILED_NODE_ID}
    if retry_market_data_preflight:
        _restore_market_data_preflight_previous_artifacts(run)
    job = analysis_job_store.get_job(run_id)
    try:
        analysis_run_retry.prepare_retry(run, payload, job=job)
    except analysis_run_retry.AnalysisRunRetryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    if retry_market_data_preflight:
        _reset_market_data_preflight_retry_nodes(run)
        hydrated = await _hydrate_created_run_with_market_data(run, str(run.get("stockCode") or run.get("symbol") or ""))
        if hydrated is not run:
            run.clear()
            run.update(hydrated)
    with analysis_job_store.job_state_lock():
        run["job"] = analysis_job_store.start_job(
            run_id,
            retry_from_node_id=str((run.get("retry") or {}).get("from_node_id") or ""),
            operator=operator,
        )
        save_run(run)
    return await start_analysis_run(run_id, {"operator": operator})


def _mark_run_cancelled(run_id: str, run: dict, reason: str) -> None:
    if run.get("status") == "CANCELLED":
        return
    cancelled_at = datetime.now().isoformat()
    run["status"] = "CANCELLED"
    run["failureCategory"] = "USER_CANCELLED"
    run["failReason"] = reason
    run["cancelRequested"] = True
    run["updatedAt"] = cancelled_at

    for node in run.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        if node.get("isRunning") or node.get("status") == "RUNNING":
            node["isRunning"] = False
            node["status"] = "CANCELLED"
            node.setdefault("downgradeReasons", []).append(reason)

    run.setdefault("streamEvents", []).append(
        {
            "event_type": "RUN_CANCELLED",
            "run_id": run_id,
            "node_id": "system",
            "message": reason,
            "payload": {"cancelRequested": True},
            "audit_id": f"AUD_CANCEL_{run_id}",
            "timestamp": cancelled_at,
        }
    )
    run.setdefault("auditLog", []).append(
        {
            "timestamp": cancelled_at,
            "runId": run_id,
            "node": "system",
            "eventType": "RUN_CANCELLED",
            "message": reason,
            "statusBefore": "RUNNING",
            "statusAfter": "CANCELLED",
            "inputHash": f"hash-input-{run_id}",
            "outputHash": "hash-output-system-RUN_CANCELLED",
            "auditId": f"AUD_CANCEL_{run_id}",
        }
    )


def _first_failed_node_id(run: dict) -> str:
    return analysis_run_retry.first_failed_node_id(run)


def _coerce_retry_node_id(run: dict, retry_from_node_id: str) -> str:
    return analysis_run_retry.coerce_retry_node_id(run, retry_from_node_id)


def _retry_legacy_node_id(run: dict, node_id: str) -> str:
    return analysis_run_retry.retry_legacy_node_id(run, node_id)


def _next_retryable_node_id(nodes: list[dict], start_index: int) -> str:
    return analysis_run_retry.next_retryable_node_id(nodes, start_index)


def _normalize_non_executable_plugin_observations_for_retry(run: dict) -> None:
    analysis_run_retry.normalize_non_executable_plugin_observations_for_retry(run)


def _prepare_nodes_for_retry(run: dict, retry_from_node_id: str) -> None:
    analysis_run_retry.prepare_nodes_for_retry(run, retry_from_node_id)


def _failed_node_from_run(run: dict) -> str:
    return analysis_run_retry.failed_node_from_run(run)


async def _validate_research_context(
    loop_id: str | None,
    iteration_id: str | None,
) -> str | None:
    if iteration_id:
        iterations = await research_loop_store.list_iterations()
        match = next((item for item in iterations if item.iteration_id == iteration_id), None)
        if match is None:
            raise HTTPException(status_code=404, detail="Research iteration not found")
        if loop_id and match.loop_id != loop_id:
            raise HTTPException(status_code=400, detail="Research loop and iteration do not match")
        return match.loop_id
    if loop_id:
        detail = await research_loop_store.get_loop_detail(loop_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="Research loop not found")
    return loop_id


@router.delete("/analysis/runs/{run_id}")
async def delete_analysis_run(run_id: str = Path(..., pattern=RUN_ID_PATH_PATTERN)):
    if _get_run_or_load(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")

    if not delete_run(run_id):
        raise HTTPException(status_code=409, detail="Run could not be deleted; persisted history was retained.")
    runs_store.pop(run_id, None)

    try:
        repo = RunRepository()
        await repo.delete_by_run_id(run_id)
    except Exception as exc:
        logger.exception("Failed to delete run %s from DB", run_id)

    return {"deleted": run_id}


@router.get("/analysis/runs")
async def list_analysis_runs():
    return await asyncio.to_thread(_list_analysis_run_summaries_sync)


@router.get("/analysis/runs/compare")
async def compare_analysis_runs_get(left: str, right: str):
    return _compare_runs(left, right)


@router.post("/analysis/runs/compare")
async def compare_analysis_runs_post(payload: dict):
    return _compare_runs(str(payload.get("left", "")), str(payload.get("right", "")))


@router.get("/analysis/reports")
async def list_final_reports(
    symbol: str | None = None,
    limit: int = Query(50, ge=1, le=200),
):
    return await final_report_store.list_reports(symbol=symbol, limit=limit)


@router.get("/analysis/reports/{report_id}")
async def get_final_report(report_id: str = Path(..., min_length=1)):
    report = await final_report_store.get_by_report_id(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


def _compare_runs(left_id: str, right_id: str) -> dict:
    try:
        return analysis_run_compare.compare_runs(
            left_id,
            right_id,
            load_run=_get_run_or_load,
            is_legacy_run=_is_legacy_mock_run,
        )
    except analysis_run_compare.AnalysisRunCompareError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/analysis/runs/{run_id}", response_model=AnalysisRun)
async def get_analysis_run(run_id: str):
    run = _get_run_or_load(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    _reconcile_loaded_analysis_run_jobs(source="detail", run_ids={run_id})
    run = _get_run_or_load(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if _is_legacy_mock_run(run_id, run):
        runs_store.pop(run_id, None)
        raise HTTPException(status_code=410, detail="Legacy mock run has been hidden. Please create a new real-data task.")

    job = analysis_job_store.get_job(run_id)
    if job:
        run["job"] = job
    before = _run_detail_artifact_snapshot(run)
    normalize_run_artifacts(run)
    stream_events_changed = _normalize_run_stream_events(run)
    if before != _run_detail_artifact_snapshot(run) or stream_events_changed:
        save_run(run)
    runs_store[run_id] = run
    response_run = dict(run)
    response_run["dashboardSummary"] = build_analysis_dashboard_summary(response_run)
    return response_run


def _normalize_run_stream_events(run: dict) -> bool:
    events = run.get("streamEvents")
    if not isinstance(events, list):
        return False

    changed = False
    fallback_run_id = str(run.get("runId") or "")
    for event in events:
        if not isinstance(event, dict):
            continue
        event_type = _normalize_stream_event_string(event, "event_type", "RUN_EVENT", blank_default=True)
        changed = _set_stream_event_string(event, "event_type", event_type) or changed
        changed = _set_stream_event_string(event, "run_id", fallback_run_id, blank_default=True) or changed
        changed = _set_stream_event_string(event, "node_id", "system", blank_default=True) or changed
        changed = _set_stream_event_string(event, "message", "") or changed
        changed = _set_stream_event_string(event, "audit_id", f"AUD_STREAM_{event_type}", blank_default=True) or changed
        changed = _set_stream_event_string(event, "timestamp", "") or changed
    return changed


def _normalize_stream_event_string(event: dict, field: str, default: str, *, blank_default: bool = False) -> str:
    value = event.get(field)
    if isinstance(value, str):
        if blank_default and not value.strip():
            return default
        return value
    if value is None:
        return default
    return str(value)


def _set_stream_event_string(event: dict, field: str, default: str, *, blank_default: bool = False) -> bool:
    normalized = _normalize_stream_event_string(event, field, default, blank_default=blank_default)
    if event.get(field) == normalized:
        return False
    event[field] = normalized
    return True


def _run_detail_artifact_snapshot(run: dict) -> dict:
    return copy.deepcopy(
        {
            "market": run.get("market"),
            "marketTechnical": run.get("marketTechnical"),
            "quantCore": run.get("quantCore"),
            "dvg": run.get("dvg"),
            "qiam": run.get("qiam"),
            "quantEngine": run.get("quantEngine"),
            "technicalKline": run.get("technicalKline"),
            "mfeMaeResearch": run.get("mfeMaeResearch"),
            "bottomResearch": run.get("bottomResearch"),
            "agentModuleResults": run.get("agentModuleResults"),
            "agentResults": run.get("agentResults"),
            "skippedNodes": run.get("skippedNodes"),
            "dagEvents": run.get("dagEvents"),
            "tokenUsage": run.get("tokenUsage"),
            "debateArtifacts": run.get("debateArtifacts"),
        }
    )


@router.get("/analysis/runs/{run_id}/report")
async def get_analysis_run_report(run_id: str = Path(..., pattern=RUN_ID_PATH_PATTERN)):
    run = _require_run_or_404(run_id)
    report = await final_report_store.get_by_run_id(run_id)
    if report:
        return report
    report = await final_report_store.upsert_from_run(run)
    if not report:
        raise HTTPException(status_code=404, detail="Final Writer report not available")
    run["finalReportAsset"] = {
        "reportId": report["report_id"],
        "auditId": report["audit_id"],
        "updatedAt": report["updated_at"],
    }
    save_run(run)
    return report


@router.get("/analysis/runs/{run_id}/nodes", response_model=list[AgentNodeBoundary])
async def get_analysis_nodes(run_id: str):
    run = _require_run_or_404(run_id)
    return run["nodes"]


@router.get("/analysis/runs/{run_id}/agents")
async def get_analysis_agent_results(run_id: str):
    run = _require_run_or_404(run_id)
    return run.get("agentResults", [])


@router.get("/analysis/runs/{run_id}/dag-events")
async def get_analysis_dag_events(run_id: str):
    run = _require_run_or_404(run_id)
    return run.get("dagEvents", [])


@router.get("/analysis/runs/{run_id}/debate")
async def get_analysis_debate(run_id: str):
    run = _require_run_or_404(run_id)
    return {
        "debateArtifacts": run.get("debateArtifacts", {}),
        "tokenUsage": run.get("tokenUsage", {}),
    }


@router.get("/analysis/runs/{run_id}/nodes/{node_id}", response_model=AgentNodeBoundary)
async def get_node_detail(run_id: str = Path(..., pattern=RUN_ID_PATH_PATTERN), node_id: str = Path(..., pattern=NODE_ID_PATH_PATTERN)):
    run = _require_run_or_404(run_id)
    nodes = run["nodes"]
    node = next((item for item in nodes if item["id"] == node_id), None)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    return node


async def _persist_run(run_data: dict, run_id: str, symbol: str):
    await analysis_run_persistence.persist_run(
        run_data,
        run_id,
        symbol,
        save_run=save_run,
        logger=logger,
    )


def _job_lease_update_rejected(job: dict | None) -> bool:
    return isinstance(job, dict) and bool(job.get("lease_update_rejected") or job.get("state_update_rejected"))


def _restore_persisted_run_after_lease_rejection(run_id: str, rejected_job: dict) -> None:
    current_job = analysis_job_store.get_job(run_id) or rejected_job
    logger.warning(
        "Rejected analysis job update for run %s because durable state/lease changed: current=%s attempted=%s event=%s",
        run_id,
        rejected_job.get("current_worker_id"),
        rejected_job.get("attempted_worker_id"),
        rejected_job.get("rejected_event"),
    )
    persisted_run = agent_runtime_store.get_run(run_id)
    if isinstance(persisted_run, dict):
        restored = dict(persisted_run)
        restored["job"] = current_job
        runs_store[run_id] = restored
        return
    if run_id in runs_store and isinstance(runs_store[run_id], dict):
        runs_store[run_id]["job"] = current_job


async def _execute_and_persist_run(
    run_id: str, *, worker_id: str | None = None, expected_job_id: str | None = None,
):
    execution_worker_id = worker_id or analysis_job_store.DEFAULT_WORKER_ID
    execution_job_id = expected_job_id
    try:
        run_data = _get_run_or_load(run_id)
        if run_data:
            initial_job = analysis_job_store.get_job(run_id) or run_data.get("job") or {}
            execution_job_id = expected_job_id or str((run_data.get("job") or initial_job).get("job_id") or "")
            rejected = analysis_job_store._reject_if_worker_mismatch(
                initial_job,
                worker_id=execution_worker_id,
                actor="analysis_worker",
                event="EXECUTION_START",
                expected_job_id=execution_job_id,
            )
            if rejected:
                _restore_persisted_run_after_lease_rejection(run_id, rejected)
                return
            if await _ensure_run_framework_ready(run_id, run_data):
                save_run(run_data)
            pending_job = analysis_job_store.get_job(run_id) or run_data.get("job") or {}
            if run_data.get("cancelRequested") or str(pending_job.get("status") or "").upper() == "CANCEL_REQUESTED":
                _mark_run_cancelled(run_id, run_data, "Analysis run cancelled before execution started.")
                job = analysis_job_store.mark_cancelled(
                    run_id,
                    run_data.get("failReason") or "cancelled_before_execution",
                    worker_id=execution_worker_id,
                    expected_job_id=execution_job_id,
                )
                if _job_lease_update_rejected(job):
                    _restore_persisted_run_after_lease_rejection(run_id, job)
                    return
                run_data["job"] = job
                save_run(run_data)
                await _persist_run(run_data, run_id, run_data.get("stockCode", ""))
                await _update_research_iteration_from_run(
                    run_data,
                    action="RUN_CANCELLED",
                    status="RUN_CANCELLED",
                    note="Guarded analysis run was cancelled before execution.",
                )
                return
            run_data["status"] = "RUNNING"
            run_data["updatedAt"] = datetime.now().isoformat()
            job = analysis_job_store.mark_running(run_id, worker_id=execution_worker_id, expected_job_id=execution_job_id)
            if _job_lease_update_rejected(job):
                _restore_persisted_run_after_lease_rejection(run_id, job)
                return
            run_data["job"] = job
            runs_store[run_id] = run_data
            save_run(run_data)

        await execute_run_with_llm(run_id, runs_store)
        latest_job = analysis_job_store.get_job(run_id) or {}
        latest_job_status = str(latest_job.get("status") or "").upper() if isinstance(latest_job, dict) else ""
        persisted_run = agent_runtime_store.get_run(run_id)
        persisted_cancel_requested = (
            isinstance(persisted_run, dict)
            and (
                bool(persisted_run.get("cancelRequested"))
                or str(persisted_run.get("status") or "").upper() == "CANCELLED"
            )
        )
        if latest_job_status in {"CANCEL_REQUESTED", "CANCELLED"} or persisted_cancel_requested:
            run_data = runs_store.get(run_id) or persisted_run or {}
            _mark_run_cancelled(run_id, run_data, "Analysis run cancelled by operator request.")
            job = analysis_job_store.mark_cancelled(
                run_id,
                run_data.get("failReason") or "cancelled_by_user",
                worker_id=execution_worker_id,
                expected_job_id=execution_job_id,
            )
            if _job_lease_update_rejected(job):
                _restore_persisted_run_after_lease_rejection(run_id, job)
                return
            run_data["job"] = job
            runs_store[run_id] = run_data
            save_run(run_data)
            await _persist_run(run_data, run_id, run_data.get("stockCode", ""))
            await _update_research_iteration_from_run(
                run_data,
                action="RUN_CANCELLED",
                status="RUN_CANCELLED",
                note="Guarded analysis run was cancelled.",
            )
            return
        run_data = runs_store.get(run_id)
        if not run_data:
            analysis_job_store.mark_failed(
                run_id,
                "Run disappeared during execution.",
                worker_id=execution_worker_id,
                expected_job_id=execution_job_id,
            )
            return
        status = run_data.get("status")
        if status == "COMPLETED":
            job = analysis_job_store.mark_completed(run_id, worker_id=execution_worker_id, expected_job_id=execution_job_id)
        elif status == "CANCELLED":
            job = analysis_job_store.mark_cancelled(
                run_id,
                run_data.get("failReason") or "cancelled",
                worker_id=execution_worker_id,
                expected_job_id=execution_job_id,
            )
        elif status == "FAILED":
            job = analysis_job_store.mark_failed(
                run_id,
                run_data.get("failReason") or "Analysis run failed.",
                _failed_node_from_run(run_data),
                worker_id=execution_worker_id,
                expected_job_id=execution_job_id,
            )
        else:
            job = analysis_job_store.get_job(run_id) or run_data.get("job")
        if _job_lease_update_rejected(job):
            _restore_persisted_run_after_lease_rejection(run_id, job)
            return
        run_data["job"] = job
        try:
            if status != "CANCELLED":
                run_data["compressedSummary"] = mark_summary_persisted(run_data, summarize_run(run_data)).model_dump()
        except Exception:
            logger.exception("Failed to summarize run %s", run_id)
        await _persist_run(run_data, run_id, run_data.get("stockCode", ""))
        if status == "COMPLETED":
            try:
                create_learning_candidate_from_run(run_data)
            except Exception:
                logger.exception("Failed to create learning candidate for run %s", run_id)
            await _update_research_iteration_from_run(
                run_data,
                action="RUN_COMPLETED",
                status="RUN_COMPLETED",
                note="Guarded analysis run completed.",
            )
        elif status == "CANCELLED":
            await _update_research_iteration_from_run(
                run_data,
                action="RUN_CANCELLED",
                status="RUN_CANCELLED",
                note="Guarded analysis run was cancelled.",
            )
        elif run_data.get("rdResearch"):
            await _update_research_iteration_from_run(
                run_data,
                action="RUN_UPDATED",
                status=str(run_data.get("status") or "RUN_UPDATED"),
                note="Guarded analysis run updated.",
            )
    except asyncio.CancelledError:
        run_data = runs_store.get(run_id)
        if run_data:
            _mark_run_cancelled(run_id, run_data, "Analysis run cancelled by operator request.")
            job = analysis_job_store.mark_cancelled(
                run_id,
                run_data.get("failReason") or "cancelled_by_user",
                worker_id=execution_worker_id,
                expected_job_id=execution_job_id,
            )
            if _job_lease_update_rejected(job):
                _restore_persisted_run_after_lease_rejection(run_id, job)
                return
            run_data["job"] = job
            save_run(run_data)
            try:
                await _persist_run(run_data, run_id, run_data.get("stockCode", ""))
                await _update_research_iteration_from_run(
                    run_data,
                    action="RUN_CANCELLED",
                    status="RUN_CANCELLED",
                    note="Guarded analysis run was cancelled.",
                )
            except Exception:
                logger.exception("Failed to persist cancelled run %s", run_id)
    except Exception as exc:
        logger.exception("Background task failed for run %s", run_id)
        try:
            runs_store[run_id]["status"] = "FAILED"
            runs_store[run_id]["updatedAt"] = datetime.now().isoformat()
            runs_store[run_id]["failReason"] = "Internal execution error. Please check backend logs."
            runs_store[run_id]["failureCategory"] = "BACKGROUND_TASK_FAILED"
            job = analysis_job_store.mark_failed(
                run_id,
                str(exc) or runs_store[run_id]["failReason"],
                _failed_node_from_run(runs_store[run_id]),
                worker_id=execution_worker_id,
                expected_job_id=execution_job_id,
            )
            if _job_lease_update_rejected(job):
                _restore_persisted_run_after_lease_rejection(run_id, job)
                return
            runs_store[run_id]["job"] = job
            save_run(runs_store[run_id])
            await _update_research_iteration_from_run(
                runs_store[run_id],
                action="RUN_FAILED",
                status="RUN_FAILED",
                note="Guarded analysis run failed.",
            )
        except Exception:
            pass
    finally:
        task = analysis_tasks.get(run_id)
        if task is asyncio.current_task():
            analysis_tasks.pop(run_id, None)


bind_analysis_lifecycle(
    run_store_provider=lambda: runs_store,
    load_run=lambda run_id: _get_run_or_load(run_id),
    save_run=lambda run_data: save_run(run_data),
    mark_run_cancelled=lambda run_id, run_data, reason: _mark_run_cancelled(run_id, run_data, reason),
    execute_and_persist_run=lambda run_id, worker_id=None, expected_job_id=None: _execute_and_persist_run(
        run_id, worker_id=worker_id, expected_job_id=expected_job_id,
    ),
    create_run=lambda request: create_analysis_run(request),
    start_run=lambda run_id, payload=None: start_analysis_run(run_id, payload),
    persist_run=lambda run_data, run_id, symbol: _persist_run(run_data, run_id, symbol),
    compare_runs=lambda left_id, right_id: _compare_runs(left_id, right_id),
)


async def _update_research_iteration_from_run(
    run_data: dict,
    *,
    action: str,
    status: str,
    note: str,
) -> None:
    rd_research = run_data.get("rdResearch") or {}
    iteration_id = rd_research.get("iterationId")
    if not iteration_id:
        return
    try:
        from ..models.research import ResearchIterationFeedbackRequest

        compressed = run_data.get("compressedSummary") or {}
        final_writer = run_data.get("finalWriter") or {}
        qiam = run_data.get("qiam") or {}
        dvg = run_data.get("dvg") or {}
        await research_loop_store.record_feedback(
            iteration_id,
            ResearchIterationFeedbackRequest(
                action=action,
                verdict="PENDING",
                status=status,
                note=note,
                linked_run_id=run_data.get("runId"),
                metrics={
                    "run_status": run_data.get("status"),
                    "final_action": final_writer.get("finalAction") or run_data.get("finalAction"),
                    "quality_score": compressed.get("quality", {}).get("score"),
                    "qiam_confidence": qiam.get("modelConfidenceFinal"),
                    "dvg_status": dvg.get("status"),
                },
            ),
        )
        rd_research["status"] = status
        rd_research["stage"] = status
        rd_research["linkedRunId"] = run_data.get("runId")
        run_data["rdResearch"] = rd_research
        if action == "RUN_COMPLETED":
            try:
                await research_loop_store.close_bottom_research_backtest(
                    iteration_id,
                    run_id=run_data.get("runId"),
                    run_data=run_data,
                    force_new=False,
                    reviewer="system",
                )
            except Exception:
                logger.exception("Failed to close MFE/MAE Path Research backtest loop for run %s", run_data.get("runId"))
    except Exception:
        logger.exception("Failed to update research iteration from run %s", run_data.get("runId"))


def _default_mock_data_sources() -> dict:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    return {
        "sources": {
            "realtime_quote": {
                "name": "实时行情",
                "provider": "tushare",
                "icon": "BarChart3",
                "status": "READY",
                "detail": "Tushare SDK realtime_quote 成功返回",
                "fetchedAt": now,
                "available": True,
                "error": "",
                "category": "行情",
            },
            "fundamentals": {
                "name": "财务数据",
                "provider": "tushare",
                "icon": "FileText",
                "status": "NOT_CONFIGURED",
                "detail": "暂未接入 tushare 财务接口 (income/balance/cashflow)，当前使用最近一期季报模拟数据",
                "available": False,
                "category": "基本面",
            },
            "announcements": {
                "name": "公告数据",
                "provider": "tushare",
                "icon": "Clock",
                "status": "NOT_CONFIGURED",
                "detail": "暂未接入 tushare 公告接口 (disclosure_date)，当前使用 Mock 模拟近 30 日公告",
                "available": False,
                "category": "消息面",
            },
            "moneyflow": {
                "name": "资金流向",
                "provider": "tushare",
                "icon": "Layers",
                "status": "NOT_CONFIGURED",
                "detail": "暂未接入 tushare 资金流接口 (moneyflow)，缺少主力/散户/大单资金流向数据",
                "available": False,
                "category": "资金面",
            },
            "chip": {
                "name": "筹码分布",
                "provider": "tushare",
                "icon": "Target",
                "status": "NOT_CONFIGURED",
                "detail": "暂未启用 tushare cyq_perf/cyq_chips；无权限或失败时仅使用 K 线代理估算",
                "available": False,
                "category": "筹码面",
            },
        },
        "summary": {
            "availableCount": 0,
            "totalCount": 5,
            "availableRatio": "0/5",
            "overallStatus": "ALL_MOCK",
            "generatedAt": now,
        },
    }
