from __future__ import annotations

import asyncio
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from ..core.agent_runtime_store import (
    get_data_sources_config,
    get_market_data_adapter_configs,
    public_data_sources_config,
)
from ..core.kline_service import get_kline_payload
from ..core.market_data_adapter import register_default_market_data_adapters
from ..core.operator_context import current_operator, role_allows
from ..core.pet_alerts import pet_alert_center
from ..db.session import AsyncSessionLocal
from ..db import models as m


router = APIRouter()


EXTERNAL_MONITOR_STATUS_SCHEMA_VERSION = "data_reliability_external_monitor_status_v1"
EXTERNAL_MONITOR_STATUS_FILE_ENVS = (
    "TIANYUAN_DATA_RELIABILITY_EXTERNAL_MONITOR_STATUS_FILE",
    "DATA_RELIABILITY_EXTERNAL_MONITOR_STATUS_FILE",
)
EXTERNAL_MONITOR_STATUS_MAX_BYTES = 64 * 1024
ALLOWED_EXTERNAL_MONITOR_STATUSES = {"READY", "DEGRADED", "FAILED", "UNKNOWN"}
DATA_RELIABILITY_SYMBOL_CHECK_TASK_TIMEOUT_SECONDS = 30.0
SECRET_TEXT_PATTERN = re.compile(
    r"(authorization|bearer|token|api[_-]?key|secret|password|credential)",
    re.IGNORECASE,
)


class SymbolHealthRequest(BaseModel):
    symbol: str


class SymbolArbitrationRequest(BaseModel):
    symbol: str
    start: str = ""
    end: str = ""
    categories: List[str] = []


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_operator_role() -> None:
    operator = current_operator()
    if role_allows(operator.role, "operator"):
        return
    raise HTTPException(
        status_code=403,
        detail={
            "message": "Operator role is required for data reliability active checks.",
            "required_role": "operator",
            "scope": "data_reliability_active_check",
            "operator": operator.as_payload(),
        },
    )


def _external_monitor_status_file() -> Path | None:
    for env_name in EXTERNAL_MONITOR_STATUS_FILE_ENVS:
        raw_path = os.getenv(env_name, "").strip()
        if raw_path:
            return Path(raw_path).expanduser()
    return None


def _safe_sidecar_text(value: Any, *, default: str = "", max_length: int = 160) -> str:
    text = str(value if value is not None else default).replace("\r", " ").replace("\n", " ").strip()
    if not text:
        return default
    if SECRET_TEXT_PATTERN.search(text):
        return "[redacted]"
    return text[:max_length]


def _safe_sidecar_int(value: Any, *, default: int = 0, max_value: int = 1_000_000) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(0, min(parsed, max_value))


def _safe_optional_sidecar_int(value: Any, *, max_value: int = 31_536_000) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, min(parsed, max_value))


def _safe_sidecar_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "ready", "ok"}
    return bool(value)


def _base_external_monitor_status() -> Dict[str, Any]:
    return {
        "schema": EXTERNAL_MONITOR_STATUS_SCHEMA_VERSION,
        "checked": False,
        "reported": False,
        "status": "NOT_CONFIGURED",
        "sidecarFile": "",
        "reportedAt": "",
        "source": "local_sidecar",
        "provider": "",
        "monitorBackend": "",
        "monitorStatus": "",
        "freshnessStatus": "",
        "retentionPolicyId": "",
        "retentionStatus": "",
        "retentionDays": None,
        "retentionExpiresAt": "",
        "outageCount": 0,
        "degradedSourceCount": 0,
        "staleSourceCount": 0,
        "latencyP95Ms": None,
        "latestIncidentAt": "",
        "searchIndex": "",
        "searchIndexReady": False,
        "message": "external data-reliability monitor sidecar is not configured",
        "deploymentReported": False,
        "localEventTrail": "DataAdapterEventDB",
        "issues": [],
    }


def _external_monitor_status() -> Dict[str, Any]:
    status = _base_external_monitor_status()
    sidecar_file = _external_monitor_status_file()
    if sidecar_file is None:
        return status

    status.update(
        {
            "checked": True,
            "status": "NOT_REPORTED",
            "sidecarFile": str(sidecar_file),
            "message": "external data-reliability monitor sidecar file was not reported",
            "issues": ["sidecar_file_missing"],
        }
    )
    if not sidecar_file.exists():
        return status

    try:
        if sidecar_file.stat().st_size > EXTERNAL_MONITOR_STATUS_MAX_BYTES:
            status.update(
                {
                    "reported": True,
                    "status": "INVALID",
                    "message": "external data-reliability monitor sidecar exceeds the read limit",
                    "issues": ["sidecar_file_too_large"],
                }
            )
            return status
        payload = json.loads(sidecar_file.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError) as exc:
        status.update(
            {
                "reported": True,
                "status": "INVALID",
                "message": _safe_sidecar_text(f"invalid external data-reliability monitor sidecar: {exc}", max_length=200),
                "issues": ["sidecar_file_invalid"],
            }
        )
        return status

    if not isinstance(payload, dict):
        status.update(
            {
                "reported": True,
                "status": "INVALID",
                "message": "external data-reliability monitor sidecar payload is not an object",
                "issues": ["sidecar_payload_invalid"],
            }
        )
        return status

    if payload.get("schema") != EXTERNAL_MONITOR_STATUS_SCHEMA_VERSION:
        status.update(
            {
                "reported": True,
                "status": "INVALID",
                "message": "external data-reliability monitor sidecar schema mismatch",
                "issues": ["sidecar_schema_mismatch"],
            }
        )
        return status

    reported_status = str(payload.get("status") or "UNKNOWN").strip().upper()
    issues = payload.get("issues")
    safe_issues = [
        _safe_sidecar_text(issue, max_length=120)
        for issue in (issues if isinstance(issues, list) else [])
    ][:12]
    if reported_status not in ALLOWED_EXTERNAL_MONITOR_STATUSES:
        safe_issues.append("sidecar_status_invalid")
        reported_status = "UNKNOWN"

    status.update(
        {
            "reported": True,
            "status": reported_status,
            "reportedAt": _safe_sidecar_text(payload.get("reported_at"), max_length=80),
            "source": _safe_sidecar_text(payload.get("source"), default="deployment_sidecar", max_length=80),
            "provider": _safe_sidecar_text(payload.get("provider"), max_length=80),
            "monitorBackend": _safe_sidecar_text(payload.get("monitor_backend"), max_length=120),
            "monitorStatus": _safe_sidecar_text(payload.get("monitor_status"), max_length=80),
            "freshnessStatus": _safe_sidecar_text(payload.get("freshness_status"), max_length=80),
            "retentionPolicyId": _safe_sidecar_text(payload.get("retention_policy_id"), max_length=120),
            "retentionStatus": _safe_sidecar_text(payload.get("retention_status"), max_length=80),
            "retentionDays": _safe_optional_sidecar_int(payload.get("retention_days")),
            "retentionExpiresAt": _safe_sidecar_text(payload.get("retention_expires_at"), max_length=80),
            "outageCount": _safe_sidecar_int(payload.get("outage_count")),
            "degradedSourceCount": _safe_sidecar_int(payload.get("degraded_source_count")),
            "staleSourceCount": _safe_sidecar_int(payload.get("stale_source_count")),
            "latencyP95Ms": _safe_optional_sidecar_int(payload.get("latency_p95_ms"), max_value=3_600_000),
            "latestIncidentAt": _safe_sidecar_text(payload.get("latest_incident_at"), max_length=80),
            "searchIndex": _safe_sidecar_text(payload.get("search_index"), max_length=160),
            "searchIndexReady": _safe_sidecar_bool(payload.get("search_index_ready")),
            "message": _safe_sidecar_text(payload.get("message"), max_length=200),
            "deploymentReported": True,
            "issues": [issue for issue in safe_issues if issue],
        }
    )
    return status


def _diagnose(error: str, healthy: bool, record_count: int = 0) -> str:
    text = (error or "").lower()
    if healthy or record_count > 0:
        return "OK"
    if "token" in text or "401" in text or "permission" in text or "权限" in error or "积分" in error:
        return "TOKEN_OR_PERMISSION"
    if "timeout" in text or "timed out" in text:
        return "NETWORK_TIMEOUT"
    if "no adapter" in text:
        return "ADAPTER_DISABLED_OR_MISSING"
    if "no records" in text or "empty" in text:
        return "SYMBOL_NO_DATA"
    if error:
        return "ADAPTER_ERROR"
    return "UNKNOWN"


def _enabled_source_keys() -> set[str]:
    config = get_data_sources_config()
    return {
        str(item.get("key"))
        for item in config.get("sources", [])
        if isinstance(item, dict) and item.get("enabled")
    }


def _config_snapshot() -> Dict[str, Any]:
    data_sources = public_data_sources_config(get_data_sources_config())
    adapter_configs = [config.model_dump() for config in get_market_data_adapter_configs()]
    return {
        "dataSources": data_sources,
        "adapterConfigs": adapter_configs,
    }


def _adapter_config_map() -> Dict[str, Dict[str, Any]]:
    return {config.adapter_id: config.model_dump() for config in get_market_data_adapter_configs()}


def _adapter_metadata() -> List[Dict[str, Any]]:
    registry = register_default_market_data_adapters()
    config_by_id = _adapter_config_map()
    adapters = []
    for health in registry.list_adapters():
        item = health.to_public_dict()
        config = config_by_id.get(item.get("adapterId", ""), {})
        item["priority"] = config.get("priority")
        item["timeoutSeconds"] = config.get("timeout_seconds")
        item["requiresToken"] = config.get("requires_token", False)
        item["note"] = config.get("note", "")
        adapters.append(item)
    adapters.sort(key=lambda item: (item.get("priority") if item.get("priority") is not None else 999, item.get("adapterId", "")))
    return adapters


async def _history_rows(limit: int = 50) -> List[Dict[str, Any]]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(m.DataHealthCheckDB).order_by(m.DataHealthCheckDB.created_at.desc()).limit(min(limit, 200)))
        rows = result.scalars().all()
        history: List[Dict[str, Any]] = []
        for row in rows:
            payload = row.payload_json or {}
            history.append({
                "id": row.id,
                "checkType": row.check_type,
                "symbol": row.symbol,
                "adapterId": row.adapter_id,
                "provider": row.provider,
                "category": row.category,
                "status": row.status,
                "configured": payload.get("configured"),
                "healthy": row.healthy,
                "upstreamHealthy": payload.get("upstreamHealthy"),
                "liveDataUsable": payload.get("liveDataUsable"),
                "fallbackUsed": payload.get("fallbackUsed"),
                "latencyMs": row.latency_ms,
                "message": row.message,
                "error": row.error,
                "diagnosis": payload.get("diagnosis", ""),
                "createdAt": row.created_at,
            })
        return history


async def _event_rows(limit: int = 50) -> List[Dict[str, Any]]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(m.DataAdapterEventDB).order_by(m.DataAdapterEventDB.created_at.desc()).limit(min(limit, 200)))
        rows = result.scalars().all()
        events: List[Dict[str, Any]] = []
        for row in rows:
            payload = row.payload_json or {}
            events.append({
                "id": row.id,
                "symbol": row.symbol,
                "adapterId": row.adapter_id,
                "provider": row.provider,
                "category": row.category,
                "eventType": row.event_type,
                "message": row.message,
                "error": row.error,
                "diagnosis": payload.get("diagnosis", ""),
                "status": payload.get("status", ""),
                "healthy": payload.get("healthy"),
                "fallbackUsed": payload.get("fallbackUsed"),
                "upstreamHealthy": payload.get("upstreamHealthy"),
                "liveDataUsable": payload.get("liveDataUsable"),
                "latencyMs": payload.get("latencyMs"),
                "recordCount": payload.get("recordCount"),
                "createdAt": row.created_at,
            })
        return events


def _latest_adapter_checks(history: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    latest: Dict[str, Dict[str, Any]] = {}
    for row in history:
        if row.get("checkType") != "adapter_check":
            continue
        adapter_id = str(row.get("adapterId") or "")
        if adapter_id and adapter_id not in latest:
            latest[adapter_id] = row
    return latest


def _merge_latest_health(adapters: List[Dict[str, Any]], history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    latest = _latest_adapter_checks(history)
    merged = []
    for adapter in adapters:
        item = dict(adapter)
        check = latest.get(str(item.get("adapterId") or ""))
        if check:
            item["healthy"] = bool(check.get("healthy"))
            if check.get("configured") is not None:
                item["configured"] = bool(check.get("configured"))
            item["upstreamHealthy"] = (
                bool(check.get("upstreamHealthy"))
                if check.get("upstreamHealthy") is not None
                else bool(check.get("healthy"))
            )
            item["liveDataUsable"] = (
                bool(check.get("liveDataUsable"))
                if check.get("liveDataUsable") is not None
                else bool(check.get("healthy"))
            )
            item["fallbackUsed"] = bool(check.get("fallbackUsed")) if check.get("fallbackUsed") is not None else item.get("fallbackUsed", False)
            item["lastError"] = "" if check.get("healthy") else check.get("message") or check.get("error", "")
            item["message"] = check.get("message") or check.get("error") or item.get("message", "")
            item["lastCheckAt"] = check.get("createdAt") or item.get("lastCheckAt", "")
            item["latencyAvgMs"] = check.get("latencyMs") or item.get("latencyAvgMs", 0)
            item["status"] = check.get("status", "UNKNOWN")
            item["diagnosis"] = check.get("diagnosis", "")
        else:
            item["status"] = "NOT_CHECKED" if item.get("enabled") else "DISABLED"
            item["diagnosis"] = ""
        merged.append(item)
    return merged


def _summary_from_adapters(adapters: List[Dict[str, Any]]) -> Dict[str, Any]:
    checked = [item for item in adapters if item.get("status") not in {"NOT_CHECKED", "DISABLED"}]
    partial = [item for item in checked if _adapter_partial(item)]
    healthy = [item for item in checked if item.get("healthy") and item not in partial]
    failed = [item for item in checked if not item.get("healthy") and not item.get("upstreamHealthy")]
    if not checked:
        overall = "UNKNOWN"
    elif failed and (healthy or partial):
        overall = "PARTIAL"
    elif failed:
        overall = "FAILED"
    elif partial:
        overall = "PARTIAL"
    else:
        overall = "READY"
    return {
        "generatedAt": _now(),
        "adapterCount": len(adapters),
        "checkedCount": len(checked),
        "healthyCount": len(healthy),
        "partialCount": len(partial),
        "failedCount": len(failed),
        "overallStatus": overall,
        "lastFailureReasons": [
            {
                "adapterId": item.get("adapterId"),
                "provider": item.get("provider"),
                "message": item.get("message"),
                "diagnosis": item.get("diagnosis") or _diagnose(item.get("message", ""), False),
            }
            for item in failed[:5]
        ],
        "partialReasons": [
            {
                "adapterId": item.get("adapterId"),
                "provider": item.get("provider"),
                "message": item.get("message"),
                "diagnosis": item.get("diagnosis") or "PARTIAL_UPSTREAM",
            }
            for item in partial[:5]
        ],
    }


def _adapter_partial(item: Dict[str, Any]) -> bool:
    status = str(item.get("status") or "").upper()
    if status == "PARTIAL":
        return True
    upstream_healthy = item.get("upstreamHealthy")
    live_data_usable = item.get("liveDataUsable")
    if upstream_healthy is None or live_data_usable is None:
        return False
    return bool(upstream_healthy) and not bool(live_data_usable)


def _capability_matrix(adapters: List[Dict[str, Any]]) -> Dict[str, Any]:
    categories = {
        "realtime_quote": "REALTIME_QUOTE",
        "historical_quote": "HISTORICAL_QUOTE",
        "kline_quote": "HISTORICAL_QUOTE",
        "fundamentals": "FUNDAMENTALS",
        "announcements": "ANNOUNCEMENTS",
        "moneyflow": "MONEYFLOW",
        "chip": "CHIP",
        "macro": "MACRO",
        "index_sector": "INDEX",
    }
    matrix: Dict[str, Dict[str, Any]] = {}
    for category, capability in categories.items():
        matrix[category] = {
            str(adapter.get("adapterId")): adapter
            for adapter in adapters
            if capability in set(adapter.get("capabilities", []))
        }
    return {"categories": matrix, "generatedAt": _now()}


def _event_type_from_check(payload: Dict[str, Any]) -> str:
    status = str(payload.get("status") or "").upper()
    check_type = str(payload.get("checkType") or "").lower()
    fallback_used = bool(payload.get("fallbackUsed"))
    fallback_chain = payload.get("fallbackChain") or []

    if status == "SKIPPED":
        return "SOURCE_SKIPPED"
    if status == "PARTIAL" or fallback_used:
        return "ADAPTER_PARTIAL" if check_type == "adapter_check" else "SOURCE_FALLBACK"
    if status in {"FAILED", "ERROR"} or not payload.get("healthy", False):
        return "ADAPTER_FAILED" if check_type == "adapter_check" else "SOURCE_FAILED"
    if isinstance(fallback_chain, list) and fallback_chain:
        return "SOURCE_FALLBACK"
    return "ADAPTER_READY" if check_type == "adapter_check" else "SOURCE_READY"


def _event_payload_from_check(payload: Dict[str, Any]) -> Dict[str, Any]:
    keys = {
        "checkType",
        "status",
        "healthy",
        "diagnosis",
        "fallbackUsed",
        "upstreamHealthy",
        "liveDataUsable",
        "latencyMs",
        "recordCount",
        "freshness",
        "fallbackChain",
    }
    return {key: payload.get(key) for key in keys if key in payload}


async def _save_check(payload: Dict[str, Any]) -> None:
    async with AsyncSessionLocal() as db:
        check_row = m.DataHealthCheckDB(
            check_type=payload.get("checkType", ""),
            symbol=payload.get("symbol", ""),
            adapter_id=payload.get("adapterId", ""),
            provider=payload.get("provider", ""),
            category=payload.get("category", ""),
            status=payload.get("status", ""),
            healthy=payload.get("healthy", False),
            latency_ms=payload.get("latencyMs", 0),
            message=payload.get("message", ""),
            error=payload.get("error", ""),
            payload_json={**payload, "configSnapshot": _config_snapshot()},
        )
        event_payload = _event_payload_from_check(payload)
        event_row = m.DataAdapterEventDB(
            symbol=payload.get("symbol", ""),
            adapter_id=payload.get("adapterId", ""),
            provider=payload.get("provider", ""),
            category=payload.get("category", ""),
            event_type=_event_type_from_check(payload),
            message=payload.get("message", ""),
            error=payload.get("error", ""),
            payload_json=event_payload,
        )
        db.add(check_row)
        db.add(event_row)
        await db.commit()


def _timeout_result(symbol: str, category: str, started: float) -> Dict[str, Any]:
    timeout_seconds = DATA_RELIABILITY_SYMBOL_CHECK_TASK_TIMEOUT_SECONDS
    message = f"Data reliability {category} check timed out after {timeout_seconds:g}s."
    return {
        "checkType": "symbol_coverage_check",
        "symbol": symbol,
        "category": category,
        "status": "FAILED",
        "healthy": False,
        "provider": "data_reliability",
        "adapterId": "timeout_guard",
        "latencyMs": int((time.perf_counter() - started) * 1000),
        "recordCount": 0,
        "freshness": "",
        "error": message,
        "message": message,
        "diagnosis": "NETWORK_TIMEOUT",
        "fallbackChain": [],
        "raw": {},
    }


def _error_result(symbol: str, category: str, started: float, error: Exception) -> Dict[str, Any]:
    message = str(error)[:300] or "Data reliability check failed."
    return {
        "checkType": "symbol_coverage_check",
        "symbol": symbol,
        "category": category,
        "status": "FAILED",
        "healthy": False,
        "provider": "data_reliability",
        "adapterId": "exception_guard",
        "latencyMs": int((time.perf_counter() - started) * 1000),
        "recordCount": 0,
        "freshness": "",
        "error": message,
        "message": message,
        "diagnosis": _diagnose(message, False),
        "fallbackChain": [],
        "raw": {},
    }


async def _completed_symbol_result(result: Dict[str, Any]) -> Dict[str, Any]:
    return result


async def _check_realtime_quote(symbol: str, registry: Any) -> Dict[str, Any]:
    started = time.perf_counter()
    category = "realtime_quote"
    try:
        quote = await asyncio.wait_for(
            registry.fetch_realtime_quote_with_fallback(symbol, fallback_to_mock=False),
            timeout=DATA_RELIABILITY_SYMBOL_CHECK_TASK_TIMEOUT_SECONDS,
        )
        quote_public = quote.to_public_dict()
        healthy = quote_public.get("status") == "READY"
        return {
            "checkType": "symbol_coverage_check",
            "symbol": symbol,
            "category": category,
            "status": quote_public.get("status"),
            "healthy": healthy,
            "provider": quote_public.get("provider", ""),
            "adapterId": quote_public.get("source", ""),
            "latencyMs": int((time.perf_counter() - started) * 1000),
            "recordCount": 1 if healthy else 0,
            "freshness": quote_public.get("freshness"),
            "error": quote_public.get("error", ""),
            "message": quote_public.get("error", "") or "Realtime quote returned.",
            "diagnosis": _diagnose(quote_public.get("error", ""), healthy),
            "fallbackChain": quote_public.get("degradationChain", []),
            "raw": quote_public,
        }
    except asyncio.TimeoutError:
        return _timeout_result(symbol, category, started)
    except Exception as exc:
        return _error_result(symbol, category, started, exc)


async def _check_kline_period(symbol: str, period: str) -> Dict[str, Any]:
    started = time.perf_counter()
    category = f"kline_{period}"
    try:
        payload = await asyncio.wait_for(
            asyncio.to_thread(get_kline_payload, symbol, period, "3m"),
            timeout=DATA_RELIABILITY_SYMBOL_CHECK_TASK_TIMEOUT_SECONDS,
        )
        healthy = payload.get("status") == "READY" and payload.get("dataMode") == "LIVE" and payload.get("recordCount", 0) > 0
        return {
            "checkType": "symbol_coverage_check",
            "symbol": symbol,
            "category": category,
            "status": "READY" if healthy else "FAILED",
            "healthy": healthy,
            "provider": payload.get("provider", "tushare"),
            "adapterId": payload.get("apiName", period),
            "latencyMs": int((time.perf_counter() - started) * 1000),
            "recordCount": payload.get("recordCount", 0),
            "freshness": payload.get("fetchedAt"),
            "error": payload.get("error", ""),
            "message": payload.get("message", "") or f"Kline {period} check finished.",
            "diagnosis": _diagnose(payload.get("error", "") or payload.get("message", ""), healthy, payload.get("recordCount", 0)),
            "fallbackChain": [],
            "raw": payload,
        }
    except asyncio.TimeoutError:
        return _timeout_result(symbol, category, started)
    except Exception as exc:
        return _error_result(symbol, category, started, exc)


async def _check_auxiliary_category(symbol: str, category: str, registry: Any) -> Dict[str, Any]:
    started = time.perf_counter()
    try:
        aux = await asyncio.wait_for(
            registry.fetch_auxiliary_with_fallback(symbol, category, fallback_to_mock=False),
            timeout=DATA_RELIABILITY_SYMBOL_CHECK_TASK_TIMEOUT_SECONDS,
        )
        public = aux.to_public_dict()
        healthy = not public.get("error") and public.get("recordCount", 0) > 0
        return {
            "checkType": "symbol_coverage_check",
            "symbol": symbol,
            "category": category,
            "status": "READY" if healthy else "FAILED",
            "healthy": healthy,
            "provider": public.get("provider", ""),
            "adapterId": public.get("source", ""),
            "latencyMs": int((time.perf_counter() - started) * 1000),
            "recordCount": public.get("recordCount", 0),
            "freshness": public.get("freshness"),
            "error": public.get("error", ""),
            "message": public.get("error", "") or f"{public.get('recordCount', 0)} records returned.",
            "diagnosis": _diagnose(public.get("error", ""), healthy, public.get("recordCount", 0)),
            "fallbackChain": public.get("degradationChain", []),
            "raw": public,
        }
    except asyncio.TimeoutError:
        return _timeout_result(symbol, category, started)
    except Exception as exc:
        return _error_result(symbol, category, started, exc)


@router.get("/data-reliability/adapters")
async def get_data_reliability_adapters():
    history = await _history_rows(50)
    return _merge_latest_health(_adapter_metadata(), history)


@router.post("/data-reliability/adapters/check")
async def post_data_reliability_adapters_check():
    _require_operator_role()
    registry = register_default_market_data_adapters()
    started = time.perf_counter()
    health = [item.to_public_dict() for item in await registry.health_check_all()]
    elapsed = int((time.perf_counter() - started) * 1000)
    check_payloads: List[Dict[str, Any]] = []
    for item in health:
        upstream_healthy = bool(item.get("upstreamHealthy")) if item.get("upstreamHealthy") is not None else bool(item.get("healthy"))
        live_data_usable = bool(item.get("liveDataUsable")) if item.get("liveDataUsable") is not None else bool(item.get("healthy"))
        if item.get("configured") is False:
            status = "NOT_CONFIGURED"
        else:
            status = "READY" if item.get("healthy") and live_data_usable else ("PARTIAL" if item.get("healthy") or upstream_healthy else "FAILED")
        payload = {
            "checkType": "adapter_check",
            "adapterId": item.get("adapterId", ""),
            "provider": item.get("provider", ""),
            "status": status,
            "healthy": item.get("healthy", False),
            "configured": item.get("configured", True),
            "enabled": item.get("enabled", True),
            "upstreamHealthy": upstream_healthy,
            "liveDataUsable": live_data_usable,
            "fallbackUsed": bool(item.get("fallbackUsed")),
            "latencyMs": item.get("latencyAvgMs") or elapsed,
            "message": item.get("message", ""),
            "error": "" if item.get("healthy") else item.get("message", ""),
        }
        await _save_check(payload)
        check_payloads.append(payload)
    pet_alert_center.report_data_reliability(check_payloads)
    return health


@router.get("/data-reliability/summary")
async def get_data_reliability_summary():
    return _summary_from_adapters(await get_data_reliability_adapters())


@router.get("/data-reliability/matrix")
async def get_data_reliability_matrix():
    return _capability_matrix(await get_data_reliability_adapters())


@router.get("/data-reliability/snapshot")
async def get_data_reliability_snapshot():
    history = await _history_rows(50)
    events = await _event_rows(50)
    adapters = _merge_latest_health(_adapter_metadata(), history)
    return {
        "generatedAt": _now(),
        "summary": _summary_from_adapters(adapters),
        "adapters": adapters,
        "matrix": _capability_matrix(adapters),
        "config": _config_snapshot(),
        "history": history,
        "events": events,
        "externalMonitorStatus": _external_monitor_status(),
    }


@router.post("/data-reliability/symbol-check")
async def post_symbol_health_check(request: SymbolHealthRequest):
    _require_operator_role()
    symbol = request.symbol.strip()
    registry = register_default_market_data_adapters()
    categories = ["fundamentals", "announcements", "moneyflow", "chip", "macro"]
    enabled_sources = _enabled_source_keys()
    checks = []
    if "realtime_quote" in enabled_sources:
        checks.append(_check_realtime_quote(symbol, registry))
    else:
        checks.append(_completed_symbol_result(_skipped_result(symbol, "realtime_quote", "Source disabled in data_sources_config.")))

    for period in ("daily", "weekly", "monthly"):
        category = f"kline_{period}"
        if "kline_quote" not in enabled_sources:
            checks.append(_completed_symbol_result(_skipped_result(symbol, category, "K-line source disabled in data_sources_config.")))
            continue
        checks.append(_check_kline_period(symbol, period))

    for category in categories:
        if category not in enabled_sources:
            checks.append(_completed_symbol_result(_skipped_result(symbol, category, "Source disabled in data_sources_config.")))
            continue
        checks.append(_check_auxiliary_category(symbol, category, registry))

    results = list(await asyncio.gather(*checks))
    for result in results:
        await _save_check(result)

    return {
        "symbol": symbol,
        "generatedAt": _now(),
        "overallStatus": "READY" if all(item["healthy"] for item in results) else "PARTIAL" if any(item["healthy"] for item in results) else "FAILED",
        "results": results,
    }


@router.post("/data-reliability/symbol-arbitration")
async def post_symbol_arbitration(request: SymbolArbitrationRequest):
    _require_operator_role()
    symbol = request.symbol.strip()
    today = datetime.now(timezone.utc).date()
    end = request.end.strip() if request.end else today.isoformat()
    start = request.start.strip() if request.start else (today - timedelta(days=45)).isoformat()
    categories = set(request.categories or [
        "realtime_quote",
        "historical_quote",
        "fundamentals",
        "announcements",
        "moneyflow",
        "chip",
        "macro",
    ])
    registry = register_default_market_data_adapters()
    results: Dict[str, Any] = {}

    if "realtime_quote" in categories:
        quote = await registry.fetch_realtime_quote_with_fallback(symbol, fallback_to_mock=False)
        results["realtime_quote"] = quote.to_public_dict()

    if "historical_quote" in categories or "kline_quote" in categories:
        rows = await registry.fetch_historical_quote_with_fallback(symbol, start, end, fallback_to_mock=False)
        arbitration = rows[0].extra.get("arbitration") if rows else None
        results["historical_quote"] = {
            "status": "READY" if rows else "FAILED",
            "symbol": symbol,
            "start": start,
            "end": end,
            "recordCount": len(rows),
            "provider": rows[0].provider if rows else "",
            "source": rows[0].source if rows else "",
            "freshness": rows[0].freshness.value if rows else "",
            "dataMode": rows[0].data_mode.value if rows else "MOCK",
            "arbitration": arbitration,
            "sample": rows[-1].to_public_dict() if rows else None,
        }

    for category in ["fundamentals", "announcements", "moneyflow", "chip", "macro"]:
        if category not in categories:
            continue
        aux = await registry.fetch_auxiliary_with_fallback(symbol, category, fallback_to_mock=False)
        results[category] = aux.to_public_dict()

    arbitrations = _collect_arbitrations(results)
    conflicts = [
        conflict
        for arbitration in arbitrations
        for conflict in arbitration.get("conflicts", [])
    ]
    single_source_count = sum(
        1
        for arbitration in arbitrations
        if str(arbitration.get("sourceConsensus") or "").upper() == "SINGLE_SOURCE"
    )
    review_only = any(
        bool((arbitration.get("dataQuality") or {}).get("reviewOnly"))
        for arbitration in arbitrations
    )
    ready_count = sum(1 for item in results.values() if _arbitration_result_ready(item))
    if review_only:
        overall = "REVIEW_ONLY"
    elif conflicts:
        overall = "DIVERGED"
    elif single_source_count:
        overall = "SINGLE_SOURCE"
    elif ready_count == len(results) and results:
        overall = "CONSENSUS"
    elif ready_count > 0:
        overall = "PARTIAL"
    else:
        overall = "FAILED"

    return {
        "symbol": symbol,
        "generatedAt": _now(),
        "range": {"start": start, "end": end},
        "overallStatus": overall,
        "summary": {
            "readyCount": ready_count,
            "categoryCount": len(results),
            "arbitratedCategoryCount": len(arbitrations),
            "singleSourceCount": single_source_count,
            "conflictCount": len(conflicts),
            "reviewOnly": review_only,
            "conflicts": conflicts,
        },
        "results": results,
    }


def _collect_arbitrations(results: Dict[str, Any]) -> List[Dict[str, Any]]:
    arbitrations: List[Dict[str, Any]] = []
    for item in results.values():
        if not isinstance(item, dict):
            continue
        arbitration = item.get("arbitration")
        if arbitration is None:
            extra = item.get("extra") or {}
            arbitration = extra.get("arbitration") if isinstance(extra, dict) else None
        if isinstance(arbitration, dict):
            arbitrations.append(arbitration)
    return arbitrations


def _arbitration_result_ready(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    status = str(item.get("status") or "").upper()
    if status == "READY":
        return True
    data_mode = str(item.get("dataMode") or "").upper()
    return data_mode in {"LIVE", "FALLBACK", "MIXED"} and not item.get("error")


def _skipped_result(symbol: str, category: str, message: str) -> Dict[str, Any]:
    return {
        "checkType": "symbol_coverage_check",
        "symbol": symbol,
        "category": category,
        "status": "SKIPPED",
        "healthy": False,
        "provider": "",
        "adapterId": "",
        "latencyMs": 0,
        "recordCount": 0,
        "freshness": "",
        "error": "",
        "message": message,
        "diagnosis": "SOURCE_DISABLED",
        "fallbackChain": [],
        "raw": {},
    }


@router.get("/data-reliability/history")
async def get_data_reliability_history(limit: int = 50):
    return await _history_rows(limit)


@router.get("/data-reliability/events")
async def get_data_reliability_events(limit: int = 50):
    return await _event_rows(limit)
