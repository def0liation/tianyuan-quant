import json
import sqlite3
from datetime import datetime, timedelta

import pytest

from app.api import routes_analysis


def _write_jobs(path, jobs):
    path.write_text(json.dumps({"version": 1, "jobs": jobs}, ensure_ascii=False), encoding="utf-8")


@pytest.mark.asyncio
async def test_jobs_list_reconciles_stale_pending_run_and_job(monkeypatch, tmp_path):
    run_id = "RUN_RECONCILE_PENDING_001"
    storage_file = tmp_path / "analysis_jobs.json"
    _write_jobs(
        storage_file,
        {
            run_id: {
                "job_id": f"JOB_{run_id}",
                "run_id": run_id,
                "status": "PENDING",
                "attempt": 1,
                "created_at": "2000-01-01T00:00:00+00:00",
                "updated_at": "2000-01-01T00:00:00+00:00",
                "history": [],
            }
        },
    )
    saved: list[dict] = []
    monkeypatch.setattr(routes_analysis.analysis_job_store, "STORAGE_FILE", storage_file)
    monkeypatch.setattr(routes_analysis, "analysis_tasks", {})
    monkeypatch.setattr(
        routes_analysis,
        "runs_store",
        {
            run_id: {
                "runId": run_id,
                "status": "PENDING",
                "createdAt": "2000-01-01T00:00:00",
                "updatedAt": "2000-01-01T00:00:00",
                "nodes": [{"id": "orchestrator", "status": "RUNNING", "isRunning": True}],
                "auditLog": [],
                "streamEvents": [],
            }
        },
    )
    monkeypatch.setattr(routes_analysis, "save_run", lambda run_data: saved.append(run_data.copy()))

    jobs = await routes_analysis.list_analysis_jobs(limit=10)

    assert jobs[0]["run_id"] == run_id
    assert jobs[0]["status"] == "STALE"
    assert routes_analysis.runs_store[run_id]["status"] == "STALE"
    assert routes_analysis.runs_store[run_id]["recovery"]["statusBefore"] == "PENDING"
    assert routes_analysis.runs_store[run_id]["job"]["status"] == "STALE"
    assert routes_analysis.runs_store[run_id]["nodes"][0]["status"] == "FAIL"
    assert saved and saved[-1]["status"] == "STALE"


@pytest.mark.asyncio
async def test_job_detail_reconciles_stale_job_without_run_storage_write(monkeypatch, tmp_path):
    run_id = "RUN_RECONCILE_JOB_ONLY_001"
    storage_file = tmp_path / "analysis_jobs.json"
    _write_jobs(
        storage_file,
        {
            run_id: {
                "job_id": f"JOB_{run_id}",
                "run_id": run_id,
                "status": "RUNNING",
                "attempt": 1,
                "created_at": "2000-01-01T00:00:00+00:00",
                "updated_at": "2000-01-01T00:00:00+00:00",
                "started_at": "2000-01-01T00:00:00+00:00",
                "history": [],
            }
        },
    )
    saved: list[dict] = []
    monkeypatch.setattr(routes_analysis.analysis_job_store, "STORAGE_FILE", storage_file)
    monkeypatch.setattr(routes_analysis, "analysis_tasks", {})
    monkeypatch.setattr(routes_analysis, "runs_store", {})
    monkeypatch.setattr(routes_analysis, "save_run", lambda run_data: saved.append(run_data.copy()))

    job = await routes_analysis.get_analysis_run_job(run_id)

    assert job["run_id"] == run_id
    assert job["status"] == "STALE"
    assert job["last_operator"] == "watchdog"
    assert job["recovery"]["statusBefore"] == "RUNNING"
    assert saved == []


@pytest.mark.asyncio
async def test_job_attempts_endpoint_exposes_retry_history(monkeypatch, tmp_path):
    run_id = "RUN_ATTEMPT_HISTORY_001"
    storage_file = tmp_path / "analysis_jobs.json"
    sqlite_file = tmp_path / "analysis_jobs.db"
    monkeypatch.setattr(routes_analysis.analysis_job_store, "STORAGE_FILE", storage_file)
    monkeypatch.setattr(routes_analysis.analysis_job_store, "SQLITE_DB_FILE", sqlite_file)
    monkeypatch.setattr(routes_analysis, "analysis_tasks", {})
    monkeypatch.setattr(routes_analysis, "runs_store", {})

    first = routes_analysis.analysis_job_store.start_job(run_id, operator="tester")
    routes_analysis.analysis_job_store.mark_running(run_id, worker_id="worker-a", operator="tester")
    routes_analysis.analysis_job_store.mark_failed(run_id, "node failed", "risk_gate", operator="tester")
    retried = routes_analysis.analysis_job_store.start_job(run_id, retry_from_node_id="risk_gate", operator="tester")

    attempts = await routes_analysis.list_analysis_job_attempts(run_id=run_id, limit=10, offset=0, status=None)
    paged_attempts = await routes_analysis.list_analysis_job_attempts(run_id=run_id, limit=1, offset=1, status=None)
    failed_attempts = await routes_analysis.list_analysis_job_attempts(run_id=run_id, limit=10, status=["FAILED"])
    queued_summary = await routes_analysis.summarize_analysis_jobs(limit=1, offset=0, status=["QUEUED"])

    assert [(attempt["attempt"], attempt["status"]) for attempt in attempts] == [
        (1, "FAILED"),
        (2, "QUEUED"),
    ]
    assert attempts[0]["job_id"] == first["job_id"]
    assert attempts[0]["worker_id"] == "worker-a"
    assert attempts[0]["failed_node_id"] == "risk_gate"
    assert attempts[1]["job_id"] == retried["job_id"]
    assert attempts[1]["retry_from_node_id"] == "risk_gate"
    assert [(attempt["attempt"], attempt["status"]) for attempt in paged_attempts] == [(2, "QUEUED")]
    assert failed_attempts == [attempts[0]]
    assert queued_summary["statuses"] == ["QUEUED"]
    assert queued_summary["filtered_count"] >= 1
    assert queued_summary["counts_by_status"]["QUEUED"] >= 1
    assert queued_summary["has_more"] is False


@pytest.mark.asyncio
async def test_job_attempts_endpoint_falls_back_to_json_when_sqlite_is_locked(monkeypatch, tmp_path):
    run_id = "RUN_ATTEMPT_LOCKED_JSON_001"
    storage_file = tmp_path / "analysis_jobs.json"
    _write_jobs(
        storage_file,
        {
            run_id: {
                "job_id": f"JOB_{run_id}_1",
                "run_id": run_id,
                "status": "QUEUED",
                "attempt": 1,
                "queue_name": "analysis",
                "concurrency_group": "analysis",
                "created_at": "2026-06-02T06:00:00+00:00",
                "updated_at": "2026-06-02T06:01:00+00:00",
                "queued_at": "2026-06-02T06:01:00+00:00",
                "history": [{"event": "JOB_QUEUED", "attempt": 1}],
            }
        },
    )
    monkeypatch.setattr(routes_analysis.analysis_job_store, "STORAGE_FILE", storage_file)
    monkeypatch.setattr(routes_analysis, "_reconcile_analysis_run_jobs", lambda source="query": {"runs": 0, "jobs": 0})

    def locked_attempts(**_kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(routes_analysis.analysis_job_store, "list_sqlite_attempts", locked_attempts)

    attempts = await routes_analysis.list_analysis_job_attempts(run_id=run_id, limit=10, offset=0, status=None)
    queued_attempts = await routes_analysis.list_analysis_job_attempts(run_id=run_id, limit=10, offset=0, status=["QUEUED"])
    failed_attempts = await routes_analysis.list_analysis_job_attempts(run_id=run_id, limit=10, offset=0, status=["FAILED"])

    assert len(attempts) == 1
    assert attempts[0]["run_id"] == run_id
    assert attempts[0]["job_id"] == f"JOB_{run_id}_1"
    assert attempts[0]["attempt"] == 1
    assert attempts[0]["status"] == "QUEUED"
    assert attempts[0]["lease_status"] == "UNCLAIMED"
    assert attempts[0]["history"] == [{"event": "JOB_QUEUED", "attempt": 1}]
    assert queued_attempts == attempts
    assert failed_attempts == []


@pytest.mark.asyncio
async def test_job_summary_reports_external_queue_sidecar_status(monkeypatch, tmp_path):
    storage_file = tmp_path / "analysis_jobs.json"
    sqlite_file = tmp_path / "analysis_jobs.db"
    sidecar_file = tmp_path / "external_queue_status.json"
    run_id = "RUN_EXTERNAL_QUEUE_STATUS_001"
    _write_jobs(
        storage_file,
        {
            run_id: {
                "job_id": f"JOB_{run_id}_1",
                "run_id": run_id,
                "status": "QUEUED",
                "attempt": 1,
                "created_at": "2026-06-02T07:00:00+00:00",
                "updated_at": "2026-06-02T07:01:00+00:00",
            }
        },
    )
    monkeypatch.setattr(routes_analysis.analysis_job_store, "STORAGE_FILE", storage_file)
    monkeypatch.setattr(routes_analysis.analysis_job_store, "SQLITE_DB_FILE", sqlite_file)
    monkeypatch.setenv("TIANYUAN_ANALYSIS_JOB_EXTERNAL_QUEUE_STATUS_FILE", str(sidecar_file))
    monkeypatch.setattr(routes_analysis, "_reconcile_analysis_run_jobs", lambda source="query": {"runs": 0, "jobs": 0})

    missing_summary = await routes_analysis.summarize_analysis_jobs(limit=10, offset=0, status=None)

    missing_external = missing_summary["external_queue_status"]
    assert missing_external["schema"] == "analysis_job_external_queue_status_v1"
    assert missing_external["checked"] is True
    assert missing_external["reported"] is False
    assert missing_external["status"] == "NOT_REPORTED"
    assert missing_external["local_queue_mode"] == "LOCAL_JSON_SQLITE_DIAGNOSTIC"

    sidecar_file.write_text(
        json.dumps(
            {
                "schema": "analysis_job_external_queue_status_v1",
                "status": "READY",
                "reported_at": "2026-06-02T07:02:00+00:00",
                "source": "deployment-queue-monitor",
                "provider": "redis",
                "queue_name": "analysis-prod",
                "lease_backend": "redlock",
                "claim_backend": "broker-claims",
                "claim_status": "READY",
                "idempotency_scope": "run_id+attempt",
                "audit_stream": "analysis-job-audit?token=unit-secret",
                "dead_letter_queue": "analysis-dlq",
                "dead_letter_count": 1,
                "visibility_timeout_seconds": 120,
                "lease_renewal_status": "READY",
                "worker_pool": "analysis-workers",
                "active_workers": 2,
                "pending_jobs": 3,
                "running_jobs": 1,
                "oldest_pending_age_seconds": 42,
                "message": "healthy token=unit-secret",
                "issues": ["authorization=Bearer unit-secret"],
            }
        ),
        encoding="utf-8-sig",
    )

    summary = await routes_analysis.summarize_analysis_jobs(limit=10, offset=0, status=None)

    external = summary["external_queue_status"]
    assert external["schema"] == "analysis_job_external_queue_status_v1"
    assert external["checked"] is True
    assert external["reported"] is True
    assert external["deployment_reported"] is True
    assert external["status"] == "READY"
    assert external["provider"] == "redis"
    assert external["queue_name"] == "analysis-prod"
    assert external["lease_backend"] == "redlock"
    assert external["claim_backend"] == "broker-claims"
    assert external["claim_status"] == "READY"
    assert external["idempotency_scope"] == "run_id+attempt"
    assert external["audit_stream"] == "[redacted]"
    assert external["dead_letter_queue"] == "analysis-dlq"
    assert external["dead_letter_count"] == 1
    assert external["visibility_timeout_seconds"] == 120
    assert external["lease_renewal_status"] == "READY"
    assert external["worker_pool"] == "analysis-workers"
    assert external["active_workers"] == 2
    assert external["pending_jobs"] == 3
    assert external["running_jobs"] == 1
    assert external["oldest_pending_age_seconds"] == 42
    assert external["message"] == "[redacted]"
    assert external["issues"] == ["[redacted]"]
    serialized = json.dumps(external).lower()
    assert "unit-secret" not in serialized
    assert "bearer" not in serialized


def test_orphaned_running_run_recovers_without_waiting_for_full_stale_timeout(monkeypatch, tmp_path):
    run_id = "RUN_ORPHANED_RUNNING_001"
    storage_file = tmp_path / "analysis_jobs.json"
    _write_jobs(storage_file, {})
    saved: list[dict] = []
    monkeypatch.setattr(routes_analysis.analysis_job_store, "STORAGE_FILE", storage_file)
    monkeypatch.setattr(routes_analysis, "save_run", lambda run_data: saved.append(run_data.copy()))
    store = {
        run_id: {
            "runId": run_id,
            "status": "RUNNING",
            "createdAt": "2026-05-21T15:00:00",
            "updatedAt": "2026-05-21T15:00:00",
            "job": {
                "status": "RUNNING",
                "worker_heartbeat_at": "2026-05-21T15:00:00",
                "updated_at": "2026-05-21T15:00:00",
            },
            "nodes": [],
            "auditLog": [],
            "streamEvents": [],
        }
    }

    recovered = routes_analysis._recover_stale_running_runs(
        store,
        now=datetime(2026, 5, 21, 15, 1, 30),
        stale_after=timedelta(hours=2),
        orphaned_after=timedelta(seconds=60),
        active_run_ids=set(),
        source="test",
    )

    assert recovered == 1
    assert store[run_id]["status"] == "STALE"
    assert store[run_id]["job"]["status"] == "STALE"
    assert store[run_id]["recovery"]["staleAfterSeconds"] == 60
    assert saved and saved[-1]["status"] == "STALE"


def test_active_running_run_is_not_recovered_as_orphaned(monkeypatch, tmp_path):
    run_id = "RUN_ACTIVE_RUNNING_001"
    storage_file = tmp_path / "analysis_jobs.json"
    _write_jobs(storage_file, {})
    monkeypatch.setattr(routes_analysis.analysis_job_store, "STORAGE_FILE", storage_file)
    store = {
        run_id: {
            "runId": run_id,
            "status": "RUNNING",
            "createdAt": "2026-05-21T15:00:00",
            "updatedAt": "2026-05-21T15:00:00",
            "job": {"status": "RUNNING", "worker_heartbeat_at": "2026-05-21T15:00:00"},
            "nodes": [{"id": "orchestrator", "status": "RUNNING", "isRunning": True}],
            "auditLog": [],
            "streamEvents": [],
        }
    }

    recovered = routes_analysis._recover_stale_running_runs(
        store,
        now=datetime(2026, 5, 21, 15, 10, 0),
        stale_after=timedelta(hours=2),
        orphaned_after=timedelta(seconds=60),
        active_run_ids={run_id},
        source="test",
    )

    assert recovered == 0
    assert store[run_id]["status"] == "RUNNING"
