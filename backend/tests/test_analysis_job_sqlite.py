import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app.core import analysis_job_store, file_utils as file_utils_module


def _isolate_job_store(monkeypatch, tmp_path):
    monkeypatch.setattr(analysis_job_store, "STORAGE_FILE", tmp_path / "analysis_jobs.json")
    monkeypatch.setattr(analysis_job_store, "SQLITE_DB_FILE", tmp_path / "analysis_jobs.db")


def test_job_store_storage_file_can_be_redirected_by_env(monkeypatch, tmp_path):
    target = tmp_path / "isolated" / "analysis_jobs.json"
    monkeypatch.setenv("TIANYUAN_ANALYSIS_JOBS_FILE", str(target))

    assert analysis_job_store._storage_file_from_env() == target


def test_job_store_json_replace_retries_windows_permission_error(monkeypatch, tmp_path):
    _isolate_job_store(monkeypatch, tmp_path)
    calls = {"count": 0}
    real_os_replace = file_utils_module.os.replace

    def flaky_replace(source, target):
        if calls["count"] == 0 and str(source).endswith(".tmp"):
            calls["count"] += 1
            raise PermissionError("temporary Windows file lock")
        calls["count"] += 1
        return real_os_replace(source, target)

    monkeypatch.setattr(file_utils_module.os, "replace", flaky_replace)
    monkeypatch.setattr(file_utils_module.time, "sleep", lambda _seconds: None)

    analysis_job_store._save_state({"version": 1, "jobs": {"RUN_RETRY": {"status": "QUEUED"}}})

    assert calls["count"] == 2
    assert analysis_job_store.STORAGE_FILE.exists()
    assert analysis_job_store._load_state()["jobs"]["RUN_RETRY"]["status"] == "QUEUED"


def test_job_lifecycle_is_mirrored_to_sqlite(monkeypatch, tmp_path):
    _isolate_job_store(monkeypatch, tmp_path)
    run_id = "RUN_SQLITE_LIFECYCLE_001"

    queued = analysis_job_store.start_job(run_id, operator="tester")
    running = analysis_job_store.mark_running(run_id, worker_id="worker-a", operator="tester")
    heartbeat = analysis_job_store.record_worker_heartbeat(
        run_id,
        worker_id="worker-a",
        operator="tester",
        metrics={"active_jobs": 1, "concurrency_limit": 1},
    )
    failed = analysis_job_store.mark_failed(run_id, "node failed", "dvg_gate", operator="tester")

    sqlite_job = analysis_job_store.get_sqlite_job(run_id)

    assert queued["status"] == "QUEUED"
    assert running["status"] == "RUNNING"
    assert heartbeat["worker_id"] == "worker-a"
    assert failed["status"] == "FAILED"
    assert sqlite_job is not None
    assert sqlite_job["run_id"] == run_id
    assert sqlite_job["status"] == "FAILED"
    assert sqlite_job["attempt"] == 1
    assert sqlite_job["queue_name"] == "analysis"
    assert sqlite_job["concurrency_group"] == "analysis"
    assert sqlite_job["concurrency_limit"] == 1
    assert sqlite_job["worker_id"] == "worker-a"
    assert sqlite_job["worker_heartbeat_at"]
    assert sqlite_job["failed_node_id"] == "dvg_gate"
    assert sqlite_job["last_error"] == "node failed"
    assert [event["event"] for event in sqlite_job["history"]] == [
        "JOB_QUEUED",
        "JOB_RUNNING",
        "WORKER_HEARTBEAT",
        "JOB_FAILED",
    ]
    attempts = analysis_job_store.list_sqlite_attempts(run_id=run_id)
    assert len(attempts) == 1
    assert attempts[0]["attempt"] == 1
    assert attempts[0]["job_id"] == queued["job_id"]
    assert attempts[0]["status"] == "FAILED"
    assert attempts[0]["worker_id"] == "worker-a"
    assert attempts[0]["failed_node_id"] == "dvg_gate"


class _EmptyPragmaResult:
    def fetchall(self):
        return []


class _DuplicateColumnConnection:
    def __init__(self):
        self.alter_statements = []

    def execute(self, sql):
        if sql.startswith("PRAGMA table_info("):
            return _EmptyPragmaResult()
        self.alter_statements.append(sql)
        raise sqlite3.OperationalError("duplicate column name: lease_expires_at")


def test_ensure_sqlite_columns_treats_duplicate_column_as_idempotent():
    conn = _DuplicateColumnConnection()

    analysis_job_store._ensure_sqlite_columns(
        conn,
        "analysis_jobs",
        {"lease_expires_at": "TEXT DEFAULT ''"},
    )

    assert conn.alter_statements == [
        "ALTER TABLE analysis_jobs ADD COLUMN lease_expires_at TEXT DEFAULT ''",
    ]


def test_ensure_sqlite_columns_still_raises_unrelated_operational_error():
    class FailingConnection(_DuplicateColumnConnection):
        def execute(self, sql):
            if sql.startswith("PRAGMA table_info("):
                return _EmptyPragmaResult()
            raise sqlite3.OperationalError("near bad_column: syntax error")

    with pytest.raises(sqlite3.OperationalError, match="syntax error"):
        analysis_job_store._ensure_sqlite_columns(
            FailingConnection(),
            "analysis_jobs",
            {"bad_column": "BAD SQL"},
        )


def test_sqlite_jobs_are_queryable_by_status_and_survive_missing_json(monkeypatch, tmp_path):
    _isolate_job_store(monkeypatch, tmp_path)
    now = datetime.now(timezone.utc).isoformat()
    analysis_job_store.upsert_sqlite_job(
        {
            "run_id": "RUN_PENDING",
            "job_id": "JOB_RUN_PENDING",
            "status": "PENDING",
            "created_at": now,
            "updated_at": now,
        }
    )
    analysis_job_store.start_job("RUN_QUEUED")
    analysis_job_store.start_job("RUN_RUNNING")
    analysis_job_store.mark_running("RUN_RUNNING", worker_id="worker-a")
    analysis_job_store.start_job("RUN_CANCEL_REQUESTED")
    analysis_job_store.request_cancel("RUN_CANCEL_REQUESTED")
    analysis_job_store.start_job("RUN_CANCELLED")
    analysis_job_store.mark_cancelled("RUN_CANCELLED")
    analysis_job_store.start_job("RUN_FAILED")
    analysis_job_store.mark_failed("RUN_FAILED", "failed")
    analysis_job_store.start_job("RUN_STALE")
    analysis_job_store.mark_stale("RUN_STALE", "stale")
    analysis_job_store.start_job("RUN_COMPLETED")
    analysis_job_store.mark_completed("RUN_COMPLETED")

    jobs = analysis_job_store.list_sqlite_jobs(limit=20)
    statuses = {job["status"] for job in jobs}

    assert {
        "PENDING",
        "QUEUED",
        "RUNNING",
        "CANCEL_REQUESTED",
        "CANCELLED",
        "FAILED",
        "STALE",
        "COMPLETED",
    }.issubset(statuses)
    assert [job["run_id"] for job in analysis_job_store.list_sqlite_jobs(statuses=["RUNNING"])] == ["RUN_RUNNING"]

    analysis_job_store.STORAGE_FILE.unlink()

    assert analysis_job_store.get_job("RUN_COMPLETED")["status"] == "COMPLETED"
    assert any(job["run_id"] == "RUN_FAILED" for job in analysis_job_store.list_jobs(limit=20))


def test_sqlite_jobs_and_attempts_support_offset_pagination(monkeypatch, tmp_path):
    _isolate_job_store(monkeypatch, tmp_path)
    for index in range(3):
        run_id = f"RUN_PAGE_{index}"
        stamp = f"2026-06-01T00:00:0{index}+00:00"
        analysis_job_store.upsert_sqlite_job(
            {
                "run_id": run_id,
                "job_id": f"JOB_{run_id}",
                "status": "COMPLETED",
                "attempt": index + 1,
                "created_at": stamp,
                "updated_at": stamp,
                "history": [],
            }
        )

    first_page = analysis_job_store.list_sqlite_jobs(limit=1, offset=0)
    second_page = analysis_job_store.list_sqlite_jobs(limit=1, offset=1)
    empty_page = analysis_job_store.list_jobs(limit=1, offset=3)
    summary = analysis_job_store.summarize_jobs(limit=1, offset=1, statuses=["COMPLETED"])

    assert [job["run_id"] for job in first_page] == ["RUN_PAGE_2"]
    assert [job["run_id"] for job in second_page] == ["RUN_PAGE_1"]
    assert empty_page == []
    assert summary["source"] == "sqlite"
    assert summary["total_count"] == 3
    assert summary["filtered_count"] == 3
    assert summary["counts_by_status"] == {"COMPLETED": 3}
    assert summary["statuses"] == ["COMPLETED"]
    assert summary["limit"] == 1
    assert summary["offset"] == 1
    assert summary["has_more"] is True

    run_id = "RUN_ATTEMPT_PAGE"
    analysis_job_store.start_job(run_id, operator="tester")
    analysis_job_store.mark_running(run_id, operator="tester")
    analysis_job_store.mark_failed(run_id, "first failed", "risk_gate", operator="tester")
    analysis_job_store.start_job(run_id, retry_from_node_id="risk_gate", operator="tester")
    analysis_job_store.mark_running(run_id, operator="tester")
    analysis_job_store.mark_failed(run_id, "second failed", "dvg_gate", operator="tester")
    analysis_job_store.start_job(run_id, retry_from_node_id="dvg_gate", operator="tester")

    attempt_page = analysis_job_store.list_sqlite_attempts(run_id=run_id, limit=1, offset=1)

    assert [(attempt["attempt"], attempt["status"]) for attempt in attempt_page] == [(2, "FAILED")]


def test_claim_next_job_respects_concurrency_group_limit(monkeypatch, tmp_path):
    _isolate_job_store(monkeypatch, tmp_path)
    monkeypatch.setenv("TIANYUAN_ANALYSIS_JOB_LEASE_SECONDS", "30")
    analysis_job_store.start_job("RUN_CLAIM_A", operator="tester")
    analysis_job_store.start_job("RUN_CLAIM_B", operator="tester")

    claimed_a = analysis_job_store.claim_next_job(worker_id="worker-a", operator="tester")
    blocked = analysis_job_store.claim_next_job(worker_id="worker-b", operator="tester")

    assert claimed_a is not None
    assert claimed_a["run_id"] == "RUN_CLAIM_A"
    assert claimed_a["status"] == "RUNNING"
    assert claimed_a["worker_id"] == "worker-a"
    assert claimed_a["worker_heartbeat_at"]
    assert claimed_a["lease_status"] == "ACTIVE"
    assert claimed_a["lease_seconds"] == 30
    assert claimed_a["lease_expires_at"]
    assert claimed_a["history"][-1]["event"] == "JOB_CLAIMED"
    assert blocked is None

    analysis_job_store.mark_completed("RUN_CLAIM_A", operator="tester")
    completed_a = analysis_job_store.get_sqlite_job("RUN_CLAIM_A")
    claimed_b = analysis_job_store.claim_next_job(worker_id="worker-b", operator="tester")

    assert completed_a["lease_status"] == "RELEASED"
    assert completed_a["lease_expires_at"] == ""
    assert claimed_b is not None
    assert claimed_b["run_id"] == "RUN_CLAIM_B"
    assert claimed_b["status"] == "RUNNING"
    assert claimed_b["worker_id"] == "worker-b"


def test_worker_heartbeat_refreshes_lease_metadata(monkeypatch, tmp_path):
    _isolate_job_store(monkeypatch, tmp_path)
    monkeypatch.setenv("TIANYUAN_ANALYSIS_JOB_LEASE_SECONDS", "45")
    run_id = "RUN_LEASE_HEARTBEAT"

    analysis_job_store.start_job(run_id, operator="tester")
    heartbeat = analysis_job_store.record_worker_heartbeat(run_id, worker_id="worker-lease", operator="tester")
    sqlite_job = analysis_job_store.get_sqlite_job(run_id)
    attempt = analysis_job_store.list_sqlite_attempts(run_id=run_id)[0]

    heartbeat_at = datetime.fromisoformat(heartbeat["worker_heartbeat_at"])
    lease_expires_at = datetime.fromisoformat(heartbeat["lease_expires_at"])

    assert heartbeat["lease_status"] == "ACTIVE"
    assert sqlite_job["lease_status"] == "ACTIVE"
    assert attempt["lease_status"] == "ACTIVE"
    assert sqlite_job["lease_seconds"] == 45
    assert lease_expires_at - heartbeat_at == timedelta(seconds=45)


def test_worker_heartbeat_rejects_non_owner(monkeypatch, tmp_path):
    _isolate_job_store(monkeypatch, tmp_path)
    run_id = "RUN_LEASE_HEARTBEAT_OWNER"

    analysis_job_store.start_job(run_id, operator="tester")
    claimed = analysis_job_store.claim_next_job(worker_id="worker-a", operator="tester")
    rejected = analysis_job_store.record_worker_heartbeat(run_id, worker_id="worker-b", operator="tester")
    sqlite_job = analysis_job_store.get_sqlite_job(run_id)

    assert claimed["worker_id"] == "worker-a"
    assert rejected["lease_update_rejected"] is True
    assert rejected["lease_rejection_reason"] == "WORKER_LEASE_OWNER_MISMATCH"
    assert rejected["current_worker_id"] == "worker-a"
    assert rejected["attempted_worker_id"] == "worker-b"
    assert rejected["rejected_event"] == "WORKER_HEARTBEAT"
    assert sqlite_job["status"] == "RUNNING"
    assert sqlite_job["worker_id"] == "worker-a"
    assert all(
        event.get("worker_id") != "worker-b"
        for event in sqlite_job["history"]
        if event.get("event") == "WORKER_HEARTBEAT"
    )


def test_terminal_update_rejects_non_owner_and_preserves_running_job(monkeypatch, tmp_path):
    _isolate_job_store(monkeypatch, tmp_path)
    run_id = "RUN_LEASE_TERMINAL_OWNER"

    analysis_job_store.start_job(run_id, operator="tester")
    analysis_job_store.claim_next_job(worker_id="worker-a", operator="tester")

    rejected = analysis_job_store.mark_completed(run_id, operator="tester", worker_id="worker-b")
    sqlite_job = analysis_job_store.get_sqlite_job(run_id)

    assert rejected["lease_update_rejected"] is True
    assert rejected["rejected_event"] == "JOB_COMPLETED"
    assert sqlite_job["status"] == "RUNNING"
    assert sqlite_job["worker_id"] == "worker-a"
    assert "JOB_COMPLETED" not in [event["event"] for event in sqlite_job["history"]]

    completed = analysis_job_store.mark_completed(run_id, operator="tester", worker_id="worker-a")

    assert completed["status"] == "COMPLETED"
    assert completed["lease_status"] == "RELEASED"


def test_claim_next_job_skips_cancel_requested(monkeypatch, tmp_path):
    _isolate_job_store(monkeypatch, tmp_path)
    analysis_job_store.start_job("RUN_CLAIM_CANCELLED", operator="tester")
    analysis_job_store.request_cancel("RUN_CLAIM_CANCELLED", operator="tester")

    assert analysis_job_store.claim_next_job(worker_id="worker-a", operator="tester") is None


def test_stale_reconciliation_updates_sqlite_only_job(monkeypatch, tmp_path):
    _isolate_job_store(monkeypatch, tmp_path)
    run_id = "RUN_SQLITE_STALE_001"
    analysis_job_store.upsert_sqlite_job(
        {
            "run_id": run_id,
            "job_id": f"JOB_{run_id}",
            "status": "RUNNING",
            "attempt": 1,
            "created_at": "2000-01-01T00:00:00+00:00",
            "updated_at": "2000-01-01T00:00:00+00:00",
            "started_at": "2000-01-01T00:00:00+00:00",
            "history": [],
        }
    )

    recovered = analysis_job_store.reconcile_stale_jobs(
        stale_after_seconds=60,
        now=datetime.fromisoformat("2100-01-01T01:00:00+00:00"),
        active_run_ids=set(),
        operator="watchdog",
    )

    sqlite_job = analysis_job_store.get_sqlite_job(run_id)
    json_job = analysis_job_store.get_job(run_id)

    assert len(recovered) == 1
    assert sqlite_job["status"] == "STALE"
    assert sqlite_job["recovery"]["statusBefore"] == "RUNNING"
    assert sqlite_job["last_operator"] == "watchdog"
    assert json_job["status"] == "STALE"
    assert json_job["failed_node_id"] == ""


def test_list_jobs_falls_back_to_json_when_sqlite_is_locked(monkeypatch, tmp_path):
    _isolate_job_store(monkeypatch, tmp_path)
    analysis_job_store.start_job("RUN_LOCKED_A")
    analysis_job_store.start_job("RUN_LOCKED_B")
    calls = []

    def locked_get_sqlite_job(run_id):
        calls.append(run_id)
        raise sqlite3.OperationalError("database is locked")

    def locked_list_sqlite_jobs(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(analysis_job_store, "get_sqlite_job", locked_get_sqlite_job)
    monkeypatch.setattr(analysis_job_store, "list_sqlite_jobs", locked_list_sqlite_jobs)

    jobs = analysis_job_store.list_jobs(limit=10)

    assert {job["run_id"] for job in jobs} == {"RUN_LOCKED_A", "RUN_LOCKED_B"}
    assert calls == ["RUN_LOCKED_A"]


def test_start_job_clears_previous_failure_fields(monkeypatch, tmp_path):
    _isolate_job_store(monkeypatch, tmp_path)
    run_id = "RUN_RETRY_CLEARS_FAILURE"

    analysis_job_store.start_job(run_id, operator="tester")
    analysis_job_store.mark_running(run_id, operator="tester")
    failed = analysis_job_store.mark_failed(run_id, "node failed", "dvg_gate", operator="tester")
    retried = analysis_job_store.start_job(run_id, retry_from_node_id="dvg_gate", operator="tester")

    assert failed["failed_node_id"] == "dvg_gate"
    assert retried["status"] == "QUEUED"
    assert retried["attempt"] == 2
    assert retried["failed_node_id"] == ""
    assert retried["last_error"] == ""
    assert retried["stale_reason"] == ""
    assert retried["retry_from_node_id"] == "dvg_gate"
    assert retried["resume_from_node_id"] == "dvg_gate"
    attempts = analysis_job_store.list_sqlite_attempts(run_id=run_id)
    assert [(attempt["attempt"], attempt["status"]) for attempt in attempts] == [
        (1, "FAILED"),
        (2, "QUEUED"),
    ]
    assert attempts[0]["failed_node_id"] == "dvg_gate"
    assert attempts[1]["retry_from_node_id"] == "dvg_gate"
    assert attempts[1]["retry_of_job_id"] == failed["job_id"]


def test_stale_reconciliation_does_not_keep_retry_source_as_failure(monkeypatch, tmp_path):
    _isolate_job_store(monkeypatch, tmp_path)
    run_id = "RUN_STALE_RETRY_SOURCE"

    analysis_job_store.start_job(run_id, operator="tester")
    analysis_job_store.mark_running(run_id, operator="tester")
    analysis_job_store.mark_failed(run_id, "node failed", "dvg_gate", operator="tester")
    analysis_job_store.start_job(run_id, retry_from_node_id="dvg_gate", operator="tester")
    analysis_job_store.mark_running(run_id, operator="tester")

    recovered = analysis_job_store.reconcile_stale_jobs(
        stale_after_seconds=60,
        now=datetime.fromisoformat("2100-01-01T01:00:00+00:00"),
        active_run_ids=set(),
        operator="watchdog",
    )

    assert len(recovered) == 1
    assert recovered[0]["status"] == "STALE"
    assert recovered[0]["failed_node_id"] == ""
    assert recovered[0]["retry_from_node_id"] == "dvg_gate"
    assert recovered[0]["history"][-1]["event"] == "JOB_STALE"
    assert recovered[0]["history"][-1]["failed_node_id"] == ""
