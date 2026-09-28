from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

StartJob = Callable[..., dict]


class AnalysisRunStartError(Exception):
    status_code = 500

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class AnalysisRunStartConflict(AnalysisRunStartError):
    status_code = 409


@dataclass(frozen=True)
class StartPreflight:
    status: str
    should_start: bool


@dataclass(frozen=True)
class StartRunResult:
    status: str
    should_schedule_background_task: bool


def check_start_preflight(run: dict, *, terminal_statuses: set[str]) -> StartPreflight:
    current_status = str(run.get("status") or "")
    if current_status == "RUNNING":
        return StartPreflight(status="RUNNING", should_start=False)
    if current_status == "QUEUED":
        return StartPreflight(status="QUEUED", should_start=False)
    if current_status in terminal_statuses:
        raise AnalysisRunStartConflict(f"Run is already in terminal status: {current_status}")
    return StartPreflight(status=current_status, should_start=True)


def prepare_start(
    run: dict,
    run_id: str,
    *,
    execution_mode: str,
    payload: dict | None,
    start_job: StartJob,
) -> StartRunResult:
    run["status"] = "QUEUED" if execution_mode == "worker" else "RUNNING"
    run["updatedAt"] = datetime.now().isoformat()
    run["streamEvents"] = []

    retry_from_node_id = str((run.get("retry") or {}).get("from_node_id") or "")
    operator = str((payload or {}).get("operator") or "local_workbench")
    job = start_job(run_id, retry_from_node_id=retry_from_node_id, operator=operator)
    run["job"] = job

    if execution_mode == "worker":
        _append_worker_queue_events(run, run_id, run["updatedAt"], execution_mode)
        return StartRunResult(status="QUEUED", should_schedule_background_task=False)

    return StartRunResult(status="RUNNING", should_schedule_background_task=True)


def _append_worker_queue_events(run: dict, run_id: str, queued_at: str, execution_mode: str) -> None:
    run.setdefault("auditLog", []).append(
        {
            "timestamp": queued_at,
            "runId": run_id,
            "node": "system",
            "eventType": "RUN_QUEUED",
            "message": "Analysis run queued for local SQLite worker.",
            "statusBefore": "CREATED",
            "statusAfter": "QUEUED",
            "inputHash": f"hash-input-{run_id}",
            "outputHash": "hash-output-system-RUN_QUEUED",
            "auditId": f"AUD_QUEUE_{run_id}",
        }
    )
    run.setdefault("streamEvents", []).append(
        {
            "event_type": "RUN_QUEUED",
            "run_id": run_id,
            "node_id": "system",
            "message": "Analysis run queued for local SQLite worker.",
            "payload": {
                "executionMode": execution_mode,
                "simulation_only": True,
                "is_real_trade": False,
            },
            "audit_id": f"AUD_QUEUE_{run_id}",
            "timestamp": queued_at,
        }
    )
