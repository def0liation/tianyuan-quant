import copy
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest

from app.api import routes_analysis
from app.core import agent_runtime_store, analysis_job_store, analysis_run_registry, analysis_worker, file_utils
from app.core.cold_archive import StorageCorruptionError


def _run(run_id, status, job=None, marker="old"):
    return {
        "runId": run_id,
        "status": status,
        "createdAt": "2000-01-01T00:00:00",
        "updatedAt": "2000-01-01T00:00:00",
        "nodes": [{"id": "final_writer", "status": "WAIT", "isRunning": False, "outputSummary": marker}],
        "finalWriter": {"marker": marker},
        "agentResults": [{"node": "final_writer", "status": "WAIT", "data": {"output_summary": marker}}],
        "job": job or {},
    }


@pytest.mark.asyncio
async def test_detail_refreshes_external_worker_completed_artifacts():
    run_id = "RUN_AUDIT_EXTERNAL_COMPLETED"
    queued = analysis_job_store.start_job(run_id)
    queued.update(created_at="2000-01-01T00:00:00+00:00", updated_at="2000-01-01T00:00:00+00:00", queued_at="2000-01-01T00:00:00+00:00")
    routes_analysis.runs_store[run_id] = _run(run_id, "QUEUED", queued)
    completed = analysis_job_store.mark_completed(run_id)
    persisted = _run(run_id, "COMPLETED", completed, "worker-result")
    persisted["updatedAt"] = datetime.now().isoformat()
    agent_runtime_store.save_run(persisted)

    detail = await routes_analysis.get_analysis_run(run_id)

    assert detail["status"] == "COMPLETED"
    assert detail["finalWriter"]["marker"] == "worker-result"
    assert detail["agentResults"][0]["data"]["output_summary"] == "worker-result"
    assert agent_runtime_store.get_run(run_id)["status"] == "COMPLETED"
    assert analysis_job_store.get_sqlite_job(run_id)["status"] == "COMPLETED"


def test_watchdog_never_overwrites_completed_run_from_stale_cache():
    run_id = "RUN_AUDIT_WATCHDOG_COMPLETED"
    queued = analysis_job_store.start_job(run_id)
    queued.update(created_at="2000-01-01T00:00:00+00:00", updated_at="2000-01-01T00:00:00+00:00", queued_at="2000-01-01T00:00:00+00:00")
    routes_analysis.runs_store[run_id] = _run(run_id, "QUEUED", queued)
    completed = analysis_job_store.mark_completed(run_id)
    persisted = _run(run_id, "COMPLETED", completed, "worker-result")
    persisted["updatedAt"] = datetime.now().isoformat()
    agent_runtime_store.save_run(persisted)

    result = routes_analysis._reconcile_loaded_analysis_run_jobs(source="regression")

    assert result["runs"] == 0
    assert routes_analysis.runs_store[run_id]["status"] == "COMPLETED"
    assert agent_runtime_store.get_run(run_id)["finalWriter"]["marker"] == "worker-result"
    assert analysis_job_store.get_job(run_id)["status"] == "COMPLETED"


@pytest.mark.parametrize("consumer", ["registry_get", "registry_iter", "research_by_id"])
def test_direct_consumer_refreshes_worker_completion_without_analysis_get(consumer):
    run_id = "RUN_AUDIT_DIRECT_" + consumer.upper()
    queued = analysis_job_store.start_job(run_id)
    routes_analysis.runs_store[run_id] = _run(run_id, "CREATED", queued)
    completed = analysis_job_store.mark_completed(run_id)
    persisted = _run(run_id, "COMPLETED", completed, "independent-worker-result")
    persisted["updatedAt"] = datetime.now(timezone.utc).isoformat()
    agent_runtime_store.save_run(persisted)

    if consumer == "registry_get":
        run = analysis_run_registry.get_run(run_id)
    elif consumer == "registry_iter":
        run = dict(analysis_run_registry.iter_runs())[run_id]
    else:
        run = routes_analysis.research_loop_store._completed_or_stale_run_by_id(run_id)

    assert run is not None
    assert run["status"] == "COMPLETED"
    assert run["finalWriter"]["marker"] == "independent-worker-result"


def test_registry_old_binding_signature_preserves_memory_and_legacy_filter(monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(analysis_run_registry, "_run_store_provider", None)
        patch.setattr(analysis_run_registry, "_legacy_run_predicate", None)
        patch.setattr(analysis_run_registry, "_run_loader", None, raising=False)
        store = {
            "RUN_EPHEMERAL": {"runId": "RUN_EPHEMERAL", "status": "CREATED"},
            "RUN_MOCK_EPHEMERAL": {"runId": "RUN_MOCK_EPHEMERAL", "status": "COMPLETED"},
        }
        analysis_run_registry.bind_analysis_run_store(lambda: store, lambda run_id, _run: run_id.startswith("RUN_MOCK_"))

        assert analysis_run_registry.get_run("RUN_EPHEMERAL") is store["RUN_EPHEMERAL"]
        assert analysis_run_registry.get_run("RUN_MOCK_EPHEMERAL") is None
        assert analysis_run_registry.get_run("RUN_MOCK_EPHEMERAL", include_legacy=True) is store["RUN_MOCK_EPHEMERAL"]
        assert list(analysis_run_registry.iter_runs()) == [("RUN_EPHEMERAL", store["RUN_EPHEMERAL"])]


@pytest.mark.asyncio
async def test_registry_loader_keeps_active_in_process_progress(monkeypatch):
    import asyncio
    run_id = "RUN_AUDIT_REGISTRY_ACTIVE_PROGRESS"
    queued = analysis_job_store.start_job(run_id)
    persisted = _run(run_id, "RUNNING", queued, "persisted-progress")
    agent_runtime_store.save_run(persisted)
    active = _run(run_id, "RUNNING", queued, "active-progress")
    routes_analysis.runs_store[run_id] = active
    pending = asyncio.Future()
    monkeypatch.setattr(routes_analysis, "analysis_tasks", {run_id: pending})
    try:
        assert analysis_run_registry.get_run(run_id) is active
        assert dict(analysis_run_registry.iter_runs())[run_id]["finalWriter"]["marker"] == "active-progress"
    finally:
        pending.cancel()


def test_cancel_requested_survives_owner_heartbeat():
    run_id = "RUN_AUDIT_CANCEL_HEARTBEAT"
    analysis_job_store.start_job(run_id)
    analysis_job_store.mark_running(run_id, worker_id="worker-a")
    requested = analysis_job_store.request_cancel(run_id)

    heartbeat = analysis_job_store.record_worker_heartbeat(run_id, worker_id="worker-a")

    assert heartbeat["status"] == "CANCEL_REQUESTED"
    assert heartbeat["cancel_requested_at"] == requested["cancel_requested_at"]
    assert heartbeat["worker_heartbeat_at"] >= requested["worker_heartbeat_at"]
    assert heartbeat["lease_status"] == "ACTIVE"
    assert analysis_job_store.get_sqlite_job(run_id)["status"] == "CANCEL_REQUESTED"
    assert analysis_job_store._load_state()["jobs"][run_id]["status"] == "CANCEL_REQUESTED"


@pytest.mark.asyncio
async def test_worker_cancel_loop_renews_lease_while_waiting_for_execution(monkeypatch):
    import asyncio
    run_id = "RUN_AUDIT_CANCEL_RENEW_LEASE"
    analysis_job_store.start_job(run_id)
    analysis_job_store.mark_running(run_id, worker_id="worker-a")
    requested = analysis_job_store.request_cancel(run_id)
    run = _run(run_id, "RUNNING", requested)
    agent_runtime_store.save_run(run)

    async def stop_after_one_cycle(_interval):
        raise asyncio.CancelledError()

    with monkeypatch.context() as patch:
        patch.setattr(analysis_worker.asyncio, "sleep", stop_after_one_cycle)
        with pytest.raises(asyncio.CancelledError):
            await analysis_worker._record_heartbeat_until_done(run_id, worker_id="worker-a", operator="test")

    current = analysis_job_store.get_job(run_id)
    assert current["status"] == "CANCEL_REQUESTED"
    assert current["worker_heartbeat_at"] > requested["worker_heartbeat_at"]
    assert current["lease_expires_at"] > requested["lease_expires_at"]
    assert agent_runtime_store.get_run(run_id)["cancelRequested"] is True


def test_start_job_does_not_create_retry_while_cancel_requested():
    run_id = "RUN_AUDIT_CANCEL_NO_RETRY"
    analysis_job_store.start_job(run_id)
    analysis_job_store.mark_running(run_id, worker_id="worker-a")
    requested = analysis_job_store.request_cancel(run_id)

    result = analysis_job_store.start_job(run_id, retry_from_node_id="final_writer")

    assert result["status"] == "CANCEL_REQUESTED"
    assert result["attempt"] == 1
    assert result["job_id"] == requested["job_id"]


@pytest.mark.parametrize("terminal", ["COMPLETED", "FAILED", "CANCELLED"])
def test_terminal_job_rejects_watchdog_and_late_worker_updates(terminal):
    run_id = "RUN_AUDIT_TERMINAL_" + terminal
    analysis_job_store.start_job(run_id)
    analysis_job_store.mark_running(run_id, worker_id="worker-a")
    if terminal == "COMPLETED":
        finished = analysis_job_store.mark_completed(run_id, worker_id="worker-a")
    elif terminal == "FAILED":
        finished = analysis_job_store.mark_failed(run_id, "failure", worker_id="worker-a")
    else:
        finished = analysis_job_store.mark_cancelled(run_id, worker_id="worker-a")

    analysis_job_store.mark_stale(run_id, "outdated watchdog")
    analysis_job_store.mark_running(run_id, worker_id="worker-a")
    analysis_job_store.request_cancel(run_id)
    analysis_job_store.record_worker_heartbeat(run_id, worker_id="worker-a")

    persisted = analysis_job_store.get_job(run_id)
    assert persisted["status"] == terminal
    assert persisted["finished_at"] == finished["finished_at"]
    assert persisted["history"] == finished["history"]
    retry = analysis_job_store.start_job(run_id, retry_from_node_id="final_writer")
    assert retry["status"] == "QUEUED"
    assert retry["attempt"] == 2
    assert retry["retry_of_job_id"] == finished["job_id"]
    assert [(item["attempt"], item["status"]) for item in analysis_job_store.list_sqlite_attempts(run_id=run_id)] == [
        (1, terminal), (2, "QUEUED")
    ]


@pytest.mark.asyncio
async def test_completed_job_does_not_restart_provider_execution(monkeypatch):
    run_id = "RUN_AUDIT_COMPLETED_NO_EXECUTION"
    analysis_job_store.start_job(run_id)
    completed = analysis_job_store.mark_completed(run_id)
    agent_runtime_store.save_run(_run(run_id, "COMPLETED", completed, "completed-artifacts"))
    invoked = []

    async def ready(_run_id, _run):
        return False

    async def provider_execution(next_run_id, _store):
        invoked.append(next_run_id)

    monkeypatch.setattr(routes_analysis, "_ensure_run_framework_ready", ready)
    monkeypatch.setattr(routes_analysis, "execute_run_with_llm", provider_execution)

    await routes_analysis._execute_and_persist_run(run_id, worker_id="worker-a")

    assert invoked == []
    assert agent_runtime_store.get_run(run_id)["finalWriter"]["marker"] == "completed-artifacts"


@pytest.mark.asyncio
async def test_old_execution_cannot_complete_retry_owned_by_same_worker(monkeypatch):
    run_id = "RUN_AUDIT_SAME_WORKER_OLD_EXECUTION"
    first = analysis_job_store.start_job(run_id)
    original = _run(run_id, "QUEUED", first)
    agent_runtime_store.save_run(original)

    async def ready(_run_id, _run):
        return False

    async def finish_old_execution(next_run_id, store):
        analysis_job_store.mark_stale(next_run_id, "old worker lease expired")
        analysis_job_store.start_job(next_run_id, retry_from_node_id="final_writer")
        second = analysis_job_store.claim_next_job(worker_id="stable-worker")
        newer = _run(next_run_id, "RUNNING", second, "new-attempt-artifacts")
        newer["updatedAt"] = datetime.now().isoformat()
        agent_runtime_store.save_run(newer)
        store[next_run_id]["status"] = "COMPLETED"
        store[next_run_id]["updatedAt"] = datetime.now().isoformat()
        store[next_run_id]["finalWriter"]["marker"] = "old-attempt-artifacts"

    async def persist_locally(run_data, _run_id, _symbol):
        routes_analysis.save_run(run_data)

    monkeypatch.setattr(routes_analysis, "_ensure_run_framework_ready", ready)
    monkeypatch.setattr(routes_analysis, "execute_run_with_llm", finish_old_execution)
    monkeypatch.setattr(routes_analysis, "_persist_run", persist_locally)

    await routes_analysis._execute_and_persist_run(run_id, worker_id="stable-worker")

    current = analysis_job_store.get_job(run_id)
    assert current["attempt"] == 2
    assert current["worker_id"] == "stable-worker"
    assert current["status"] == "RUNNING"
    assert agent_runtime_store.get_run(run_id)["finalWriter"]["marker"] == "new-attempt-artifacts"


@pytest.mark.parametrize("operation", ["heartbeat", "completed", "failed", "cancelled", "running"])
def test_old_epoch_rejected_for_same_worker_id(operation):
    run_id = "RUN_AUDIT_EPOCH_" + operation.upper()
    analysis_job_store.start_job(run_id)
    first = analysis_job_store.claim_next_job(worker_id="stable-worker")
    analysis_job_store.mark_stale(run_id, "lease expired")
    analysis_job_store.start_job(run_id, retry_from_node_id="final_writer")
    current = analysis_job_store.claim_next_job(worker_id="stable-worker")
    before = analysis_job_store.STORAGE_FILE.read_bytes()
    functions = {
        "heartbeat": analysis_job_store.record_worker_heartbeat,
        "completed": analysis_job_store.mark_completed,
        "cancelled": analysis_job_store.mark_cancelled,
        "running": analysis_job_store.mark_running,
        "failed": lambda next_run_id, **kwargs: analysis_job_store.mark_failed(next_run_id, "old failure", **kwargs),
    }

    rejected = functions[operation](run_id, worker_id="stable-worker", expected_job_id=first["job_id"])

    assert first["job_id"] != current["job_id"]
    assert rejected["state_update_rejected"] is True
    assert rejected["lease_rejection_reason"] == "JOB_EPOCH_MISMATCH"
    assert rejected["job_id"] == current["job_id"]
    assert analysis_job_store.get_job(run_id)["status"] == "RUNNING"
    assert analysis_job_store.STORAGE_FILE.read_bytes() == before
    assert [(item["attempt"], item["status"]) for item in analysis_job_store.list_sqlite_attempts(run_id=run_id)] == [(1, "STALE"), (2, "RUNNING")]


def test_current_epoch_can_heartbeat_cancel_and_complete():
    run_id = "RUN_AUDIT_CURRENT_EPOCH"
    analysis_job_store.start_job(run_id)
    current = analysis_job_store.claim_next_job(worker_id="stable-worker")
    heartbeat = analysis_job_store.record_worker_heartbeat(run_id, worker_id="stable-worker", expected_job_id=current["job_id"])
    assert heartbeat["status"] == "RUNNING"
    assert not heartbeat.get("state_update_rejected")
    analysis_job_store.request_cancel(run_id)
    heartbeat = analysis_job_store.record_worker_heartbeat(run_id, worker_id="stable-worker", expected_job_id=current["job_id"])
    assert heartbeat["status"] == "CANCEL_REQUESTED"
    cancelled = analysis_job_store.mark_cancelled(run_id, worker_id="stable-worker", expected_job_id=current["job_id"])
    assert cancelled["status"] == "CANCELLED"
    retry = analysis_job_store.start_job(run_id, retry_from_node_id="final_writer")
    analysis_job_store.claim_next_job(worker_id="stable-worker")
    completed = analysis_job_store.mark_completed(run_id, worker_id="stable-worker", expected_job_id=retry["job_id"])
    assert completed["status"] == "COMPLETED"
    assert completed["attempt"] == 2


@pytest.mark.asyncio
async def test_old_worker_cannot_propagate_cancel_into_current_epoch():
    run_id = "RUN_AUDIT_OLD_CANCEL_PROPAGATION"
    analysis_job_store.start_job(run_id)
    first = analysis_job_store.claim_next_job(worker_id="stable-worker")
    analysis_job_store.mark_stale(run_id, "lease expired")
    analysis_job_store.start_job(run_id, retry_from_node_id="final_writer")
    current = analysis_job_store.claim_next_job(worker_id="stable-worker")
    requested = analysis_job_store.request_cancel(run_id)
    newer = _run(run_id, "RUNNING", current, "new-attempt-artifacts")
    agent_runtime_store.save_run(newer)
    routes_analysis.runs_store[run_id] = copy.deepcopy(newer)

    await analysis_worker._record_heartbeat_until_done(run_id, worker_id="stable-worker", operator="test", expected_job_id=first["job_id"])

    assert routes_analysis.runs_store[run_id].get("cancelRequested") is not True
    assert analysis_job_store.get_job(run_id)["worker_heartbeat_at"] == requested["worker_heartbeat_at"]
    assert agent_runtime_store.get_run(run_id)["finalWriter"]["marker"] == "new-attempt-artifacts"


@pytest.mark.asyncio
async def test_worker_refuses_retry_until_matching_run_payload_is_published(monkeypatch):
    run_id = "RUN_AUDIT_UNPUBLISHED_RETRY_PAYLOAD"
    analysis_job_store.start_job(run_id)
    completed = analysis_job_store.mark_completed(run_id)
    original = _run(run_id, "COMPLETED", completed, "old-complete-artifacts")
    agent_runtime_store.save_run(original)
    before = (agent_runtime_store.RUNS_DIR / (run_id + ".json")).read_bytes()
    analysis_job_store.start_job(run_id, retry_from_node_id="final_writer")
    invoked = []

    async def ready(_run_id, _run):
        return False

    async def provider(next_run_id, _store):
        invoked.append(next_run_id)

    monkeypatch.setattr(routes_analysis, "_ensure_run_framework_ready", ready)
    monkeypatch.setattr(routes_analysis, "execute_run_with_llm", provider)

    result = await analysis_worker.run_worker_once(worker_id="stable-worker")

    assert result["status"] == "FAILED"
    assert result["job"]["attempt"] == 2
    assert invoked == []
    assert (agent_runtime_store.RUNS_DIR / (run_id + ".json")).read_bytes() == before


def test_run_save_rejects_different_job_id_with_same_attempt():
    run_id = "RUN_AUDIT_SAVE_JOB_EPOCH"
    analysis_job_store.start_job(run_id)
    current_job = analysis_job_store.claim_next_job(worker_id="stable-worker")
    current = _run(run_id, "RUNNING", current_job, "current-artifacts")
    agent_runtime_store.save_run(current)
    stale = _run(run_id, "RUNNING", {**current_job, "job_id": "JOB_OLD_EPOCH"}, "old-artifacts")
    stale["updatedAt"] = "2100-01-01T00:00:00"

    agent_runtime_store.save_run(stale)

    assert agent_runtime_store.get_run(run_id)["finalWriter"]["marker"] == "current-artifacts"


def test_locked_sqlite_mutation_does_not_write_json_fallback(monkeypatch):
    run_id = "RUN_AUDIT_LOCKED_MUTATION"
    analysis_job_store.start_job(run_id)
    original_bytes = analysis_job_store.STORAGE_FILE.read_bytes()

    def locked_read(_run_id):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(analysis_job_store, "get_sqlite_job", locked_read)

    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        analysis_job_store.mark_running(run_id, worker_id="worker-a")
    assert analysis_job_store.STORAGE_FILE.read_bytes() == original_bytes


def test_sqlite_completion_wins_over_outdated_json_on_mutation():
    run_id = "RUN_AUDIT_SQLITE_AUTHORITY"
    analysis_job_store.start_job(run_id)
    running = analysis_job_store.mark_running(run_id, worker_id="worker-a")
    completed = copy.deepcopy(running)
    completed.update(status="COMPLETED", updated_at="2100-01-01T00:00:00+00:00", finished_at="2100-01-01T00:00:00+00:00")
    analysis_job_store.upsert_sqlite_job(completed)

    result = analysis_job_store.mark_stale(run_id, "outdated JSON snapshot")

    assert result["status"] == "COMPLETED"
    assert analysis_job_store.get_sqlite_job(run_id)["status"] == "COMPLETED"
    assert analysis_job_store.get_job(run_id)["finished_at"] == "2100-01-01T00:00:00+00:00"


def test_newer_clock_in_stale_json_cannot_downgrade_sqlite_terminal():
    run_id = "RUN_AUDIT_CLOCK_SKEW"
    analysis_job_store.start_job(run_id)
    running = analysis_job_store.mark_running(run_id, worker_id="worker-a")
    finished = analysis_job_store.mark_completed(run_id, worker_id="worker-a")
    running["updated_at"] = "2100-01-01T00:00:00+00:00"
    running["worker_heartbeat_at"] = "2100-01-01T00:00:00+00:00"
    analysis_job_store._save_state({"version": 1, "jobs": {run_id: running}})

    result = analysis_job_store.get_job(run_id)

    assert result["status"] == "COMPLETED"
    assert result["finished_at"] == finished["finished_at"]


def test_late_sqlite_snapshot_cannot_replace_completed_attempt():
    run_id = "RUN_AUDIT_SQLITE_LATE_SNAPSHOT"
    analysis_job_store.start_job(run_id)
    running = analysis_job_store.mark_running(run_id, worker_id="worker-a")
    analysis_job_store.mark_completed(run_id, worker_id="worker-a")
    running["updated_at"] = "2100-01-01T00:00:00+00:00"
    running["worker_heartbeat_at"] = "2100-01-01T00:00:00+00:00"

    analysis_job_store.upsert_sqlite_job(running)

    assert analysis_job_store.get_sqlite_job(run_id)["status"] == "COMPLETED"
    assert analysis_job_store.list_sqlite_attempts(run_id=run_id)[0]["status"] == "COMPLETED"


def test_sqlite_compare_and_set_keeps_completion_at_write_boundary(monkeypatch):
    run_id = "RUN_AUDIT_SQLITE_CAS_BOUNDARY"
    analysis_job_store.start_job(run_id)
    original_upsert = analysis_job_store.upsert_sqlite_job

    def finish_before_update(job, **kwargs):
        completed = copy.deepcopy(job)
        completed.update(status="COMPLETED", finished_at="2100-01-01T00:00:00+00:00")
        original_upsert(completed)
        return original_upsert(job, **kwargs)

    monkeypatch.setattr(analysis_job_store, "upsert_sqlite_job", finish_before_update)

    result = analysis_job_store.mark_running(run_id, worker_id="worker-a")

    assert result["status"] == "COMPLETED"
    assert result["state_update_rejected"] is True
    assert analysis_job_store.get_sqlite_job(run_id)["status"] == "COMPLETED"
    assert analysis_job_store._load_state()["jobs"][run_id]["status"] == "COMPLETED"
    assert "state_update_rejected" not in analysis_job_store._load_state()["jobs"][run_id]


def test_watchdog_preserves_valid_worker_lease_with_old_run_timestamp():
    run_id = "RUN_AUDIT_LIVE_WORKER_LEASE"
    analysis_job_store.start_job(run_id)
    running = analysis_job_store.mark_running(run_id, worker_id="worker-a")
    run = _run(run_id, "RUNNING", running)
    agent_runtime_store.save_run(run)
    routes_analysis.runs_store[run_id] = copy.deepcopy(run)

    result = routes_analysis._reconcile_loaded_analysis_run_jobs(source="regression")

    assert result["runs"] == 0
    assert analysis_job_store.get_sqlite_job(run_id)["status"] == "RUNNING"
    assert routes_analysis.runs_store[run_id]["status"] == "RUNNING"


def test_cross_process_old_state_save_keeps_other_jobs(monkeypatch, tmp_path):
    monkeypatch.setattr(analysis_job_store, "SQLITE_DB_FILE", None)
    storage_file = analysis_job_store.STORAGE_FILE
    analysis_job_store.start_job("RUN_AUDIT_INITIAL")
    ready = tmp_path / "ready"
    resume = tmp_path / "resume"
    script = """
import sys, time
from pathlib import Path
from app.core import analysis_job_store as jobs
jobs.STORAGE_FILE = Path(sys.argv[1])
jobs.SQLITE_DB_FILE = None
old_state = jobs._load_state()
Path(sys.argv[2]).touch()
deadline = time.monotonic() + 10
while not Path(sys.argv[3]).exists():
    if time.monotonic() > deadline:
        raise RuntimeError('parent did not release stale snapshot')
    time.sleep(0.01)
job = jobs._base_job('RUN_AUDIT_CHILD')
job['status'] = 'QUEUED'
job['attempt'] = 1
jobs._persist_job_state(old_state, 'RUN_AUDIT_CHILD', job)
"""
    proc = subprocess.Popen([sys.executable, "-c", script, str(storage_file), str(ready), str(resume)], env=os.environ.copy(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        import time
        deadline = time.monotonic() + 10
        while not ready.exists():
            if time.monotonic() > deadline or proc.poll() is not None:
                pytest.fail("child could not load its snapshot: " + proc.communicate(timeout=1)[1])
            time.sleep(0.01)
        analysis_job_store.start_job("RUN_AUDIT_PARENT")
        resume.touch()
        _, errors = proc.communicate(timeout=10)
        assert proc.returncode == 0, errors
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()

    state = analysis_job_store._load_state()
    assert set(state["jobs"]) == {"RUN_AUDIT_INITIAL", "RUN_AUDIT_PARENT", "RUN_AUDIT_CHILD"}


def test_stale_run_save_preserves_worker_final_artifacts():
    run_id = "RUN_AUDIT_SAVE_SNAPSHOT"
    queued = analysis_job_store.start_job(run_id)
    stale_snapshot = _run(run_id, "RUNNING", queued)
    finished = analysis_job_store.mark_completed(run_id)
    current = _run(run_id, "COMPLETED", finished, "worker-result")
    current["updatedAt"] = datetime.now().isoformat()
    agent_runtime_store.save_run(current)
    stale_snapshot["updatedAt"] = "2100-01-01T00:00:00"
    stale_snapshot["status"] = "STALE"

    agent_runtime_store.save_run(stale_snapshot)

    saved = agent_runtime_store.get_run(run_id)
    assert saved["status"] == "COMPLETED"
    assert saved["finalWriter"]["marker"] == "worker-result"
    assert saved["agentResults"][0]["data"]["output_summary"] == "worker-result"


def test_run_replace_failure_leaves_old_complete_json(monkeypatch):
    run_id = "RUN_AUDIT_ATOMIC_REPLACE"
    original = _run(run_id, "CREATED", marker="old-complete")
    agent_runtime_store.save_run(original)
    target = agent_runtime_store.RUNS_DIR / (run_id + ".json")
    original_bytes = target.read_bytes()

    def failed_replace(_source, _target, **_kwargs):
        raise OSError("simulated replacement failure")

    monkeypatch.setattr(file_utils, "atomic_replace_file", failed_replace)
    with pytest.raises(OSError, match="simulated replacement failure"):
        agent_runtime_store.save_run(_run(run_id, "RUNNING", marker="new"))

    assert target.read_bytes() == original_bytes
    assert json.loads(target.read_text(encoding="utf-8"))["finalWriter"]["marker"] == "old-complete"
    assert not list(agent_runtime_store.RUNS_DIR.glob("*.tmp"))


@pytest.mark.parametrize("raw", [
    b'{"version":1,"jobs":{"RUN_PRIVATE":',
    b'[{"private":"synthetic diagnostic marker"}]',
    b'{"version":1,"jobs":[{"private":"synthetic diagnostic marker"}]}',
])
@pytest.mark.parametrize("operation", ["start", "claim"])
def test_corrupt_job_store_refuses_publication_and_preserves_original_bytes(raw, operation):
    run_id = "RUN_AUDIT_CORRUPT_KEEP"
    original = analysis_job_store.start_job(run_id)
    analysis_job_store.STORAGE_FILE.write_bytes(raw)

    with pytest.raises(StorageCorruptionError):
        if operation == "start":
            analysis_job_store.start_job("RUN_AUDIT_CORRUPT_NEW")
        else:
            analysis_job_store.claim_next_job(worker_id="worker-a")

    assert analysis_job_store.STORAGE_FILE.read_bytes() == raw
    evidence = list(analysis_job_store.STORAGE_FILE.parent.glob("analysis_jobs.json.corrupt.*"))
    assert len(evidence) == 1
    assert evidence[0].read_bytes() == raw
    assert analysis_job_store.get_sqlite_job(run_id)["status"] == "QUEUED"
    assert analysis_job_store.get_sqlite_job(run_id)["history"] == original["history"]
    assert analysis_job_store.get_sqlite_job("RUN_AUDIT_CORRUPT_NEW") is None
    assert analysis_job_store.get_job(run_id)["status"] == "QUEUED"
    assert analysis_job_store.list_jobs()[0]["status"] == "QUEUED"
    assert analysis_job_store._load_state()["warning"] == "job_store_recovered"


def test_job_state_warning_cannot_be_saved_or_used_for_sql_publication():
    queued = analysis_job_store.start_job("RUN_AUDIT_CORRUPT_DIRECT")
    valid_snapshot = analysis_job_store._load_state()
    raw = b'{"version":1,"jobs":'
    analysis_job_store.STORAGE_FILE.write_bytes(raw)

    with pytest.raises(StorageCorruptionError):
        analysis_job_store._save_state(valid_snapshot)
    with pytest.raises(StorageCorruptionError):
        analysis_job_store.upsert_sqlite_job({**queued, "status": "COMPLETED"})
    with pytest.raises(StorageCorruptionError):
        analysis_job_store.record_worker_heartbeat(queued["run_id"], worker_id="worker-a")

    assert analysis_job_store.STORAGE_FILE.read_bytes() == raw
    assert analysis_job_store.get_sqlite_job(queued["run_id"])["status"] == "QUEUED"


@pytest.mark.parametrize("failure", [PermissionError, FileNotFoundError])
def test_job_read_failure_quarantines_readable_bytes_and_blocks_save(monkeypatch, failure):
    analysis_job_store.start_job("RUN_AUDIT_READ_FAILURE")
    target = analysis_job_store.STORAGE_FILE
    original_bytes = target.read_bytes()
    original_read = type(target).read_bytes
    failures = []

    def temporary_read_failure(path):
        if path == target and not failures:
            failures.append(True)
            raise failure("synthetic read failure")
        return original_read(path)

    monkeypatch.setattr(type(target), "read_bytes", temporary_read_failure)
    state = analysis_job_store._load_state()

    assert state["warning"] == "job_store_recovered"
    with pytest.raises(StorageCorruptionError):
        analysis_job_store._save_state(state)
    assert target.read_bytes() == original_bytes
    evidence = list(target.parent.glob("analysis_jobs.json.corrupt.*"))
    assert evidence[0].read_bytes() == original_bytes


def test_healthy_job_json_still_supports_worker_lifecycle():
    queued = analysis_job_store.start_job("RUN_AUDIT_HEALTHY_STATE")
    running = analysis_job_store.claim_next_job(worker_id="worker-a")
    completed = analysis_job_store.mark_completed(queued["run_id"], worker_id="worker-a", expected_job_id=running["job_id"])

    assert completed["status"] == "COMPLETED"
    assert "warning" not in analysis_job_store._load_state()
    assert analysis_job_store.get_sqlite_job(queued["run_id"])["status"] == "COMPLETED"


def test_run_timestamp_guard_accepts_local_naive_then_utc_and_rejects_older_write(monkeypatch):
    class LocalShanghaiDatetime(datetime):
        def astimezone(self, tz=None):
            value = self if self.tzinfo is not None else self.replace(tzinfo=timezone(timedelta(hours=8)))
            return datetime.astimezone(value, tz)

    monkeypatch.setattr(agent_runtime_store, "datetime", LocalShanghaiDatetime)
    run_id = "RUN_AUDIT_LOCAL_UTC_TIMESTAMP"
    created = _run(run_id, "CREATED", marker="created")
    created["updatedAt"] = "2026-09-29T18:00:00"
    agent_runtime_store.save_run(created)
    completed = _run(run_id, "COMPLETED", marker="current-completed")
    completed["updatedAt"] = "2026-09-29T10:00:02+00:00"

    agent_runtime_store.save_run(completed)

    assert agent_runtime_store.get_run(run_id)["status"] == "COMPLETED"
    assert agent_runtime_store.get_run(run_id)["finalWriter"]["marker"] == "current-completed"
    older = _run(run_id, "COMPLETED", marker="older-write")
    older["updatedAt"] = "2026-09-29T18:00:01"
    agent_runtime_store.save_run(older)
    assert agent_runtime_store.get_run(run_id)["finalWriter"]["marker"] == "current-completed"


def test_standalone_worker_can_start_without_http_application_import(monkeypatch):
    import builtins
    original_import = builtins.__import__

    def import_without_http_app(name, globals=None, locals=None, fromlist=(), level=0):
        if (name in {"app.main", "app"} and "main" in fromlist) or (name == "" and "main" in fromlist):
            raise ImportError("HTTP application initialization is unavailable in this worker")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", import_without_http_app)
    monkeypatch.setattr(sys, "argv", ["analysis_worker", "--once"])

    analysis_worker.main()


def test_fresh_worker_bootstrap_registers_callbacks_without_http_app(tmp_path):
    script = """
import builtins, sys
real_import = builtins.__import__
def no_http_app(name, globals=None, locals=None, fromlist=(), level=0):
    if name == 'app.main' or (name in {'app', ''} and 'main' in fromlist):
        raise ImportError('HTTP app must not be initialized by this worker')
    return real_import(name, globals, locals, fromlist, level)
builtins.__import__ = no_http_app
sys.argv = ['analysis_worker', '--once']
from app.core.analysis_worker import main
main()
from app.core import analysis_lifecycle_service
assert isinstance(analysis_lifecycle_service.run_store(), dict)
assert 'app.main' not in sys.modules
"""
    env = os.environ.copy()
    env["TIANYUAN_ANALYSIS_JOBS_FILE"] = str(tmp_path / "jobs.json")
    env["TIANYUAN_QUANT_DB_URL"] = "sqlite+aiosqlite:///" + str(tmp_path / "worker.db")
    result = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=20)

    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", ["COMPLETED", "FAILED", "CANCELLED"])
async def test_terminal_run_retry_preserves_new_attempt(terminal, monkeypatch):
    run_id = "RUN_AUDIT_ROUTE_RETRY_" + terminal
    analysis_job_store.start_job(run_id)
    if terminal == "COMPLETED":
        finished = analysis_job_store.mark_completed(run_id)
    elif terminal == "FAILED":
        finished = analysis_job_store.mark_failed(run_id, "failure", "final_writer")
    else:
        finished = analysis_job_store.mark_cancelled(run_id)
    original = _run(run_id, terminal, finished)
    original["updatedAt"] = datetime.now().isoformat()
    agent_runtime_store.save_run(original)
    monkeypatch.setenv("ANALYSIS_EXECUTION_MODE", "worker")

    async def framework_ready(_run_id, _run):
        return False

    monkeypatch.setattr(routes_analysis, "_ensure_run_framework_ready", framework_ready)
    response = await routes_analysis.retry_analysis_run(run_id, {"from_node_id": "final_writer"})

    assert response.status == "QUEUED"
    saved = agent_runtime_store.get_run(run_id)
    assert saved["status"] == "QUEUED"
    assert saved["job"]["attempt"] == 2
    assert saved["retry"]["previous_status"] == terminal
    assert analysis_job_store.get_sqlite_job(run_id)["attempt"] == 2
