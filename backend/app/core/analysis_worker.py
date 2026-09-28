import argparse
import asyncio
import contextlib
import logging
import os
import socket
import uuid
from datetime import datetime
from typing import Any

from . import analysis_job_store, analysis_lifecycle_service

logger = logging.getLogger(__name__)

DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 1.0


def _default_worker_id() -> str:
    return os.getenv("ANALYSIS_WORKER_ID", "").strip() or f"analysis-worker-{socket.gethostname()}-{uuid.uuid4().hex[:8]}"


def _heartbeat_interval_seconds() -> float:
    try:
        return max(float(os.getenv("ANALYSIS_WORKER_HEARTBEAT_INTERVAL_SECONDS", DEFAULT_HEARTBEAT_INTERVAL_SECONDS)), 0.1)
    except (TypeError, ValueError):
        return DEFAULT_HEARTBEAT_INTERVAL_SECONDS


async def _record_heartbeat_until_done(
    run_id: str,
    *,
    worker_id: str,
    operator: str,
    interval_seconds: float | None = None,
) -> None:
    interval = interval_seconds if interval_seconds is not None else _heartbeat_interval_seconds()
    while True:
        latest_job = await asyncio.to_thread(analysis_job_store.get_job, run_id)
        if str((latest_job or {}).get("status") or "").upper() in {"CANCEL_REQUESTED", "CANCELLED"}:
            run = analysis_lifecycle_service.peek_run(run_id) or analysis_lifecycle_service.get_run(run_id)
            if isinstance(run, dict):
                run["cancelRequested"] = True
                run["job"] = latest_job
                run["updatedAt"] = datetime.now().isoformat()
                analysis_lifecycle_service.set_run(run_id, run, persist=True)
            await asyncio.sleep(interval)
            continue

        heartbeat_job = await asyncio.to_thread(
            analysis_job_store.record_worker_heartbeat,
            run_id,
            worker_id=worker_id,
            operator=operator,
            metrics={"heartbeat_at": datetime.now().isoformat()},
        )
        run = analysis_lifecycle_service.peek_run(run_id)
        if isinstance(run, dict):
            run["job"] = heartbeat_job
            analysis_lifecycle_service.set_run(run_id, run)
        await asyncio.sleep(interval)


async def run_worker_once(*, worker_id: str | None = None, operator: str = "analysis_worker") -> dict[str, Any]:
    resolved_worker_id = worker_id or _default_worker_id()
    job = await asyncio.to_thread(
        analysis_job_store.claim_next_job,
        worker_id=resolved_worker_id,
        operator=operator,
    )
    if not job:
        return {"claimed": False, "worker_id": resolved_worker_id}

    run_id = str(job.get("run_id") or "")

    run = analysis_lifecycle_service.get_run(run_id)
    if not isinstance(run, dict):
        failed_job = analysis_job_store.mark_failed(
            run_id,
            "Queued run was not found before worker execution.",
            operator=operator,
            worker_id=resolved_worker_id,
        )
        return {"claimed": True, "worker_id": resolved_worker_id, "run_id": run_id, "status": "FAILED", "job": failed_job}

    if run.get("cancelRequested"):
        analysis_lifecycle_service.mark_run_cancelled(run_id, run, "Analysis run cancelled before worker execution.")
        cancelled_job = analysis_job_store.mark_cancelled(
            run_id,
            "cancelled_before_execution",
            operator=operator,
            worker_id=resolved_worker_id,
        )
        run["job"] = cancelled_job
        analysis_lifecycle_service.set_run(run_id, run, persist=True)
        return {"claimed": True, "worker_id": resolved_worker_id, "run_id": run_id, "status": "CANCELLED", "job": cancelled_job}

    heartbeat_job = analysis_job_store.record_worker_heartbeat(
        run_id,
        worker_id=resolved_worker_id,
        operator=operator,
        metrics={"claimed_at": datetime.now().isoformat()},
    )
    run["status"] = "RUNNING"
    run["job"] = heartbeat_job
    run["updatedAt"] = datetime.now().isoformat()
    analysis_lifecycle_service.set_run(run_id, run, persist=True)

    heartbeat_task = asyncio.create_task(
        _record_heartbeat_until_done(
            run_id,
            worker_id=resolved_worker_id,
            operator=operator,
        )
    )
    try:
        await analysis_lifecycle_service.execute_and_persist_run(run_id, worker_id=resolved_worker_id)
    finally:
        heartbeat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat_task

    final_run = analysis_lifecycle_service.get_run(run_id) or {}
    final_job = analysis_job_store.get_job(run_id)
    return {
        "claimed": True,
        "worker_id": resolved_worker_id,
        "run_id": run_id,
        "status": final_run.get("status") or (final_job or {}).get("status"),
        "job": final_job,
    }


async def run_worker_loop(
    *,
    worker_id: str | None = None,
    interval_seconds: float = 1.0,
    once: bool = False,
    operator: str = "analysis_worker",
) -> None:
    resolved_worker_id = worker_id or _default_worker_id()
    while True:
        result = await run_worker_once(worker_id=resolved_worker_id, operator=operator)
        logger.info("Worker %s completed iteration: claimed=%s job_count=%s", resolved_worker_id, result.get("claimed"), result.get("job_count", "N/A"))
        if once:
            return
        if not result.get("claimed"):
            await asyncio.sleep(max(float(interval_seconds or 1.0), 0.1))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local SQLite analysis worker.")
    parser.add_argument("--once", action="store_true", help="Claim and execute at most one queued run.")
    parser.add_argument("--interval", type=float, default=1.0, help="Idle polling interval in seconds.")
    parser.add_argument("--worker-id", default="", help="Stable worker id for heartbeat/job history.")
    args = parser.parse_args()

    # Importing the app registers API-owned analysis lifecycle callbacks with
    # the core lifecycle facade before the standalone worker loop starts.
    from .. import main as _app_main  # noqa: F401

    asyncio.run(
        run_worker_loop(
            worker_id=args.worker_id or None,
            interval_seconds=args.interval,
            once=args.once,
        )
    )


if __name__ == "__main__":
    main()
