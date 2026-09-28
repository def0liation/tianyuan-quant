import asyncio
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from ..core import analysis_job_store
from ..core.auto_paper_trading import auto_paper_trading_store
from ..core.observability import build_production_health_summary
from ..core.ops_log import ops_event_log
from ..core.production_alerts import production_alert_outbox
from ..core.startup_status import startup_status
from ..db.session import DB_PATH, DATABASE_URL, engine
from ..models.analysis import BackendHealth


router = APIRouter()
STARTED_AT = time.time()


@router.get("/health", response_model=BackendHealth)
async def get_health():
    return BackendHealth(
        status="ok",
        version="0.2.0",
        mode="api",
        tradingEnabled=False,
        autoOrderEnabled=False,
        lastCheck=datetime.now().isoformat(),
        latency=0,
    )


@router.get("/ready")
async def get_readiness():
    checks = {
        "database": await _check_database(),
        "storage": _check_storage(),
        "autoPaperTrading": _check_auto_paper(),
    }
    degraded = [name for name, check in checks.items() if check.get("status") != "ok"]
    payload = {
        "status": "ready" if not degraded else "degraded",
        "generatedAt": datetime.now().isoformat(),
        "degradedChecks": degraded,
        "checks": checks,
        "startup": await startup_status.snapshot(),
    }
    return JSONResponse(status_code=200 if not degraded else 503, content=payload)


@router.get("/startup/status")
async def get_startup_status():
    return await startup_status.snapshot()


@router.get("/metrics")
async def get_metrics():
    now = time.time()
    return {
        "service": "tianyuan-quant-agent-api",
        "generatedAt": datetime.now().isoformat(),
        "uptimeSeconds": round(now - STARTED_AT, 3),
        "runtime": {
            "mode": os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or "development",
            "databaseUrlKind": "sqlite" if DATABASE_URL.startswith("sqlite") else "external",
        },
        "analysisJobs": await asyncio.to_thread(_job_metrics),
        "autoPaperTrading": await asyncio.to_thread(_auto_paper_metrics),
        "storage": await asyncio.to_thread(_storage_metrics),
        "productionHealth": await asyncio.to_thread(_production_health_metrics),
    }


@router.get("/ops/alerts/status")
async def get_ops_alert_status(limit: int = 20):
    safe_limit = max(0, min(int(limit or 20), 100))
    return await asyncio.to_thread(production_alert_outbox.status, limit=safe_limit)


@router.get("/ops/alerts/export")
async def export_ops_alerts(limit: int = 100):
    safe_limit = max(1, min(int(limit or 100), 1000))
    return await asyncio.to_thread(production_alert_outbox.export_bundle, limit=safe_limit)


@router.post("/ops/alerts/export/handoff")
async def handoff_ops_alerts_export(limit: int = 100):
    safe_limit = max(1, min(int(limit or 100), 1000))
    return await asyncio.to_thread(production_alert_outbox.handoff_export_bundle, limit=safe_limit)


@router.post("/ops/alerts/dispatch")
async def dispatch_ops_alerts():
    production_health = await asyncio.to_thread(_production_health_metrics)
    result = await asyncio.to_thread(
        production_alert_outbox.dispatch_from_health,
        production_health,
        source="backend_status",
    )
    ops_event_log.record_event(
        {
            "event_type": "production_alert_dispatch",
            "level": "warning" if result.get("dispatched") else "info",
            "source": "ops_alerts",
            "path": "/api/ops/alerts/dispatch",
            "status_code": 200,
            "message": f"Production alert dispatch recorded {result.get('dispatched', 0)} event(s).",
            "context": {
                "dispatched": result.get("dispatched", 0),
                "deduplicated": result.get("deduplicated", 0),
                "production_health_status": result.get("production_health_status", ""),
                "external_delivery_enabled": result.get("external_delivery_enabled", False),
                "external_provider": result.get("external_provider", "disabled"),
                "external_delivery_status": result.get("external_delivery_status", "disabled"),
                "external_delivery_attempt_limit": result.get("external_delivery_attempt_limit", 0),
                "external_delivery_retry_backoff_seconds": result.get("external_delivery_retry_backoff_seconds", 0.0),
            },
        }
    )
    return result


@router.get("/ops/logs/status")
async def get_ops_log_status(
    limit: int = 20,
    level: str = "",
):
    safe_limit = max(0, min(int(limit or 20), 100))
    return await asyncio.to_thread(ops_event_log.status, limit=safe_limit, level=level)


@router.get("/ops/logs/query")
async def query_ops_logs(
    limit: int = 20,
    level: str = "",
    event_type: str = "",
    source: str = "",
    text: str = "",
    since: str = "",
):
    safe_limit = max(0, min(int(limit), 200))
    return await asyncio.to_thread(
        ops_event_log.query_events,
        limit=safe_limit,
        level=level,
        event_type=event_type,
        source=source,
        text=text,
        since=since,
    )


@router.get("/ops/logs/export")
async def export_ops_logs(
    limit: int = 100,
    level: str = "",
    since: str = "",
):
    safe_limit = max(1, min(int(limit or 100), 1000))
    return await asyncio.to_thread(ops_event_log.export_bundle, limit=safe_limit, level=level, since=since)


@router.post("/ops/logs/export/handoff")
async def handoff_ops_logs_export(
    limit: int = 100,
    level: str = "",
    since: str = "",
):
    safe_limit = max(1, min(int(limit or 100), 1000))
    return await asyncio.to_thread(ops_event_log.handoff_export_bundle, limit=safe_limit, level=level, since=since)


async def _check_database() -> Dict[str, Any]:
    started = time.perf_counter()
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {
            "status": "ok",
            "latencyMs": round((time.perf_counter() - started) * 1000, 3),
        }
    except Exception as exc:
        return {
            "status": "error",
            "latencyMs": round((time.perf_counter() - started) * 1000, 3),
            "message": "Database readiness check failed.",
            "errorType": type(exc).__name__,
        }


def _check_storage() -> Dict[str, Any]:
    paths = {
        "database": DB_PATH.parent,
        "appStorage": Path(__file__).resolve().parents[1] / "storage",
        "jobStore": analysis_job_store.STORAGE_FILE.parent,
    }
    failed = []
    details = {}
    for name, path in paths.items():
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".ready_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            details[name] = {"writable": True}
        except Exception as exc:
            failed.append(name)
            details[name] = {
                "writable": False,
                "message": "Storage readiness probe failed.",
                "errorType": type(exc).__name__,
            }
    return {
        "status": "ok" if not failed else "error",
        "failed": failed,
        "details": details,
    }


def _check_auto_paper() -> Dict[str, Any]:
    try:
        status = auto_paper_trading_store.get_status()
        loop_health = str(status.get("loop_health") or "UNKNOWN")
        return {
            "status": "ok" if loop_health in {"DISABLED", "HEALTHY", "STARTING"} else "warn",
            "enabled": bool(status.get("enabled")),
            "loopRunning": bool(status.get("loop_running")),
            "loopHealth": loop_health,
            "lastError": status.get("last_error") or status.get("loop_last_error") or "",
            "heartbeatAt": status.get("heartbeat_at") or "",
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


def _job_metrics() -> Dict[str, Any]:
    try:
        jobs = analysis_job_store.list_jobs(limit=200)
    except Exception as exc:
        return {"available": False, "error": str(exc), "total": 0, "byStatus": {}}
    by_status: Dict[str, int] = {}
    for job in jobs:
        status = str(job.get("status") or "UNKNOWN")
        by_status[status] = by_status.get(status, 0) + 1
    return {
        "available": True,
        "total": len(jobs),
        "byStatus": by_status,
        "latestUpdatedAt": jobs[0].get("updated_at") if jobs else "",
    }


def _auto_paper_metrics() -> Dict[str, Any]:
    try:
        status = auto_paper_trading_store.get_status()
    except Exception as exc:
        return {"available": False, "error": str(exc)}
    return {
        "available": True,
        "enabled": bool(status.get("enabled")),
        "loopHealth": status.get("loop_health"),
        "loopRunning": bool(status.get("loop_running")),
        "lastSuccessAt": status.get("last_success_at"),
        "lastError": status.get("last_error") or status.get("loop_last_error") or "",
        "nextTickDueAt": status.get("next_tick_due_at"),
    }


def _storage_metrics() -> Dict[str, Any]:
    app_storage = Path(__file__).resolve().parents[1] / "storage"
    database_bytes = DB_PATH.stat().st_size if DB_PATH.exists() else 0
    app_storage_files = 0
    if app_storage.exists():
        try:
            app_storage_files = sum(1 for item in app_storage.iterdir() if item.is_file())
        except OSError:
            app_storage_files = 0
    return {
        "databasePath": str(DB_PATH),
        "databaseBytes": database_bytes,
        "appStoragePath": str(app_storage),
        "appStorageFiles": app_storage_files,
    }


def _production_health_metrics() -> Dict[str, Any]:
    source_errors: Dict[str, str] = {}
    try:
        runs = _analysis_runs_for_observability(limit=500)
    except Exception as exc:
        runs = []
        source_errors["analysisRuns"] = str(exc)

    try:
        jobs = analysis_job_store.list_jobs(limit=500)
    except Exception as exc:
        jobs = []
        source_errors["analysisJobs"] = str(exc)

    try:
        auto_paper_status = auto_paper_trading_store.get_status()
    except Exception as exc:
        auto_paper_status = {}
        source_errors["autoPaperTrading"] = str(exc)

    return build_production_health_summary(
        runs=runs,
        jobs=jobs,
        auto_paper_status=auto_paper_status,
        generated_at=_observability_now(),
        source_errors=source_errors,
    )


def _analysis_runs_for_observability(limit: int = 500) -> List[Dict[str, Any]]:
    from ..core.analysis_run_registry import iter_runs

    runs: List[Dict[str, Any]] = []
    for _run_id, run in iter_runs():
        runs.append(run)
    runs.sort(key=lambda item: item.get("updatedAt") or item.get("createdAt") or "", reverse=True)
    return runs[:limit]


def _observability_now() -> datetime:
    return datetime.now(timezone.utc)
