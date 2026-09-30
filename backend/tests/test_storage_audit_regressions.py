"""Behavioral regressions for non-destructive local storage maintenance."""

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from hashlib import sha256

import pytest

from app.core import backtest_store, file_utils, knowledge_store
from app.core.ops_log import OpsEventLog
from app.models.knowledge import CreateKnowledgeItemRequest, ReviewKnowledgeItemRequest


def _scan_request():
    return {
        "symbol": "STORAGE_AUDIT",
        "start_date": "2026-04-01",
        "end_date": "2026-04-05",
        "parameter_grid": {"signal_min_strength": [0.5]},
        "max_combinations": 1,
    }


def _scan_job(job_id, status, *, lease_expires_at=None):
    now = datetime.now(timezone.utc).isoformat()
    return {
        "jobId": job_id, "status": status, "progressStep": status,
        "request": _scan_request(), "createdAt": now, "updatedAt": now,
        "leaseStatus": "LEASED" if lease_expires_at else "UNCLAIMED",
        "leaseId": "audit-lease" if lease_expires_at else "",
        "leaseOwner": "another-worker" if lease_expires_at else "",
        "leaseExpiresAt": lease_expires_at,
        "attemptCount": 1 if lease_expires_at else 0,
        "currentAttemptId": f"{job_id}-attempt-1" if lease_expires_at else None,
        "attempts": ([{
            "attemptId": f"{job_id}-attempt-1", "attemptNumber": 1,
            "status": "RUNNING", "progressStep": "RUNNING",
            "startedAt": now, "leaseStatus": "LEASED",
            "leaseOwner": "another-worker", "leaseId": "audit-lease",
            "leaseExpiresAt": lease_expires_at,
        }] if lease_expires_at else []),
    }


def _reject_replace(*_args, **_kwargs):
    raise OSError("injected atomic replacement failure")


def test_json_atomic_failure_keeps_previous_bytes_and_removes_temporary_file(monkeypatch, tmp_path):
    path = tmp_path / "state.json"
    before = b'{"previous": "complete"}\n'
    path.write_bytes(before)
    monkeypatch.setattr(file_utils.os, "replace", _reject_replace)
    with pytest.raises(OSError):
        file_utils.write_json_atomic(path, {"next": "value"})
    assert path.read_bytes() == before
    assert list(tmp_path.glob("*.tmp")) == []


def test_ops_bad_line_keeps_valid_events_and_damage_evidence(monkeypatch, tmp_path):
    path = tmp_path / "ops.jsonl"
    monkeypatch.setenv("OPS_LOG_FILE", str(path))
    raw_bad_line = b'{"broken": evidence that must survive}\n'
    good_events = [{"id": f"event-{index}", "level": "info", "message": "valid"} for index in range(105)]
    before = b"".join(json.dumps(event).encode() + b"\n" for event in good_events[:3])
    before += raw_bad_line
    before += b"".join(json.dumps(event).encode() + b"\n" for event in good_events[3:])
    path.write_bytes(before)
    log = OpsEventLog(max_events=100)
    status = log.status(limit=100)
    assert status["event_count"] == 75
    assert len(path.read_text(encoding="utf-8").splitlines()) == 75
    assert status["storage_integrity"]["invalid_line_count"] == 1
    evidence = list(tmp_path.rglob("*.corrupt.*"))
    assert evidence and any(item.read_bytes() == before for item in evidence)
    history = log.query_events(text="event-0", limit=200)
    assert [event["id"] for event in history["events"]] == ["event-0"]
    assert status["retention_policy"]["deletion_enabled"] is False


def test_ops_atomic_trim_failure_preserves_all_old_events(monkeypatch, tmp_path):
    path = tmp_path / "ops.jsonl"
    monkeypatch.setenv("OPS_LOG_FILE", str(path))
    events = [{"id": f"event-{index}", "level": "info"} for index in range(105)]
    before = "".join(json.dumps(event) + "\n" for event in events).encode()
    path.write_bytes(before)
    monkeypatch.setattr(file_utils.os, "replace", _reject_replace)
    with pytest.raises(OSError):
        OpsEventLog(max_events=100).status()
    assert path.read_bytes() == before


def test_knowledge_failed_write_keeps_old_complete_state(monkeypatch, tmp_path):
    path = tmp_path / "knowledge.json"
    monkeypatch.setattr(knowledge_store, "STORAGE_FILE", path)
    original = knowledge_store.create_knowledge_item(CreateKnowledgeItemRequest(title="Original", thesis="Keep me"))
    before = path.read_bytes()
    monkeypatch.setattr(file_utils.os, "replace", _reject_replace)
    with pytest.raises(OSError):
        knowledge_store.create_knowledge_item(CreateKnowledgeItemRequest(title="Next", thesis="Reject failed save"))
    assert path.read_bytes() == before
    assert [item.item_id for item in knowledge_store.list_knowledge_items()] == [original.item_id]


def test_knowledge_cold_candidates_remain_reviewable_and_do_not_change_status(monkeypatch, tmp_path):
    path = tmp_path / "knowledge.json"
    monkeypatch.setattr(knowledge_store, "STORAGE_FILE", path)
    monkeypatch.setenv("KNOWLEDGE_HOT_MAX_ITEMS", "3")
    first = knowledge_store.create_learning_candidate_from_run({"runId": "RUN_ARCHIVE_0"})
    for index in range(1, 8):
        knowledge_store.create_learning_candidate_from_run({"runId": f"RUN_ARCHIVE_{index}"})
    hot = json.loads(path.read_text(encoding="utf-8"))
    assert len(hot["items"]) <= 3
    assert knowledge_store.get_knowledge_summary().total == 8
    assert knowledge_store.get_knowledge_summary().pending_count == 8
    again = knowledge_store.create_learning_candidate_from_run({"runId": "RUN_ARCHIVE_0"})
    assert again.item_id == first.item_id
    approved = knowledge_store.review_knowledge_item(first.item_id, ReviewKnowledgeItemRequest(action="APPROVE"))
    assert approved.status == "ACTIVE"
    assert any(item["itemId"] == first.item_id for item in knowledge_store.get_active_knowledge_context())
    assert any(item["item_id"] == first.item_id for item in json.loads(path.read_text())["items"])
    forced = knowledge_store.create_learning_candidate_from_run({"runId": "RUN_ARCHIVE_0"}, force=True)
    assert forced.item_id != first.item_id
    assert knowledge_store.get_knowledge_summary().total == 9


@pytest.mark.asyncio
async def test_scan_failed_durable_write_is_rejected_before_scheduling(monkeypatch, tmp_path):
    path = tmp_path / "scan_jobs.json"
    monkeypatch.setattr(backtest_store, "PARAMETER_SCAN_JOB_STORE_FILE", path)
    store = backtest_store.BacktestStore()
    scheduled = []
    monkeypatch.setattr(store, "_schedule_parameter_scan_job", scheduled.append)
    monkeypatch.setattr(file_utils.os, "replace", _reject_replace)
    with pytest.raises(OSError):
        await store.create_parameter_scan_job(_scan_request())
    assert store._parameter_scan_jobs == {}
    assert scheduled == []
    assert not path.exists()


@pytest.mark.asyncio
async def test_scan_corrupt_state_cannot_be_overwritten_by_empty_queue(monkeypatch, tmp_path):
    path = tmp_path / "scan_jobs.json"
    monkeypatch.setattr(backtest_store, "PARAMETER_SCAN_JOB_STORE_FILE", path)
    before = b'{"jobs": {"existing": "incomplete but irreplaceable"'
    path.write_bytes(before)
    store = backtest_store.BacktestStore()
    with pytest.raises(OSError):
        await store.create_parameter_scan_job(_scan_request())
    assert path.read_bytes() == before
    evidence = list(tmp_path.rglob("*.corrupt.*"))
    assert evidence and any(item.read_bytes() == before for item in evidence)
    assert store._parameter_scan_tasks == {}


@pytest.mark.asyncio
async def test_scan_another_instance_keeps_active_lease_and_attempt(monkeypatch, tmp_path):
    path = tmp_path / "scan_jobs.json"
    monkeypatch.setattr(backtest_store, "PARAMETER_SCAN_JOB_STORE_FILE", path)
    expiry = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    job = _scan_job("LEASED_SCAN", "RUNNING", lease_expires_at=expiry)
    path.write_text(json.dumps({"jobs": {job["jobId"]: job}}), encoding="utf-8")
    store = backtest_store.BacktestStore()
    restored = store._parameter_scan_jobs["LEASED_SCAN"]
    assert restored["status"] == "RUNNING"
    assert restored["leaseId"] == "audit-lease"
    assert restored["leaseOwner"] == "another-worker"
    assert restored["attempts"][0]["status"] == "RUNNING"
    assert restored["recoveryAttemptCount"] == 0
    assert await store._start_parameter_scan_job_attempt("LEASED_SCAN") is None


@pytest.mark.asyncio
async def test_scan_cold_terminal_jobs_are_readable_and_active_jobs_stay_hot(monkeypatch, tmp_path):
    path = tmp_path / "scan_jobs.json"
    monkeypatch.setattr(backtest_store, "PARAMETER_SCAN_JOB_STORE_FILE", path)
    monkeypatch.setenv("BACKTEST_PARAMETER_SCAN_HOT_MAX_JOBS", "3")
    jobs = {f"DONE_{index}": _scan_job(f"DONE_{index}", "COMPLETED") for index in range(8)}
    jobs["PENDING_SCAN"] = _scan_job("PENDING_SCAN", "QUEUED")
    path.write_text(json.dumps({"jobs": jobs}), encoding="utf-8")
    store = backtest_store.BacktestStore()
    store._persist_parameter_scan_jobs_locked()
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert len(persisted["jobs"]) <= 3
    assert persisted["jobs"]["PENDING_SCAN"]["status"] in {"QUEUED", "RECOVERING"}
    recreated = backtest_store.BacktestStore()
    historical = await recreated.get_parameter_scan_job("DONE_0")
    assert historical["status"] == "COMPLETED"
    assert historical["durable"] is True


@pytest.mark.asyncio
async def test_scan_stale_instances_cannot_claim_one_job_twice(monkeypatch, tmp_path):
    path = tmp_path / "scan_jobs.json"
    monkeypatch.setattr(backtest_store, "PARAMETER_SCAN_JOB_STORE_FILE", path)
    path.write_text(json.dumps({"jobs": {"SHARED_SCAN": _scan_job("SHARED_SCAN", "QUEUED")}}), encoding="utf-8")
    first = backtest_store.BacktestStore()
    stale = backtest_store.BacktestStore()
    attempt = await first._start_parameter_scan_job_attempt("SHARED_SCAN")
    assert attempt is not None
    lease = json.loads(path.read_text())["jobs"]["SHARED_SCAN"]["leaseId"]
    assert await stale._start_parameter_scan_job_attempt("SHARED_SCAN") is None
    persisted = json.loads(path.read_text())["jobs"]["SHARED_SCAN"]
    assert persisted["leaseId"] == lease
    assert persisted["attemptCount"] == 1


@pytest.mark.asyncio
async def test_scan_stale_instances_keep_each_others_accepted_jobs(monkeypatch, tmp_path):
    path = tmp_path / "scan_jobs.json"
    monkeypatch.setattr(backtest_store, "PARAMETER_SCAN_JOB_STORE_FILE", path)
    first = backtest_store.BacktestStore()
    stale = backtest_store.BacktestStore()
    monkeypatch.setattr(first, "_schedule_parameter_scan_job", lambda _job_id: None)
    monkeypatch.setattr(stale, "_schedule_parameter_scan_job", lambda _job_id: None)
    accepted_first = await first.create_parameter_scan_job(_scan_request())
    accepted_second = await stale.create_parameter_scan_job(_scan_request())
    persisted = json.loads(path.read_text())["jobs"]
    assert set(persisted) == {accepted_first["jobId"], accepted_second["jobId"]}


def test_ops_interrupted_archive_commit_recovers_without_duplicate_history(monkeypatch, tmp_path):
    path = tmp_path / "ops.jsonl"
    monkeypatch.setenv("OPS_LOG_FILE", str(path))
    events = [{"id": f"event-{index}", "level": "info"} for index in range(105)]
    path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
    original_replace = file_utils.os.replace
    manifest_writes = 0

    def fail_final_manifest(source, target):
        nonlocal manifest_writes
        if str(target).endswith(".archive-manifest.json"):
            manifest_writes += 1
            if manifest_writes == 2:
                raise OSError("injected manifest commit interruption")
        return original_replace(source, target)

    monkeypatch.setattr(file_utils.os, "replace", fail_final_manifest)
    with pytest.raises(OSError):
        OpsEventLog(max_events=100).status()
    assert len(path.read_text().splitlines()) == 75
    monkeypatch.setattr(file_utils.os, "replace", original_replace)
    history = OpsEventLog(max_events=100).query_events(limit=200)
    assert history["event_count"] == 105
    assert {event["id"] for event in history["events"]} == {f"event-{index}" for index in range(105)}
    assert history["storage_integrity"]["status"] == "OK"


def test_damaged_cold_batch_refuses_write_and_preserves_hot_bytes(monkeypatch, tmp_path):
    path = tmp_path / "knowledge.json"
    cold = tmp_path / "knowledge.archive"
    cold.mkdir()
    payload = b'[]'
    (cold / "bad.json").write_bytes(payload)
    before = json.dumps({
        "items": [], "archive": {
            "schema": "local_cold_archive_manifest_v1", "batches": [{
                "file": "bad.json", "sha256": sha256(payload).hexdigest(), "record_count": 0,
            }],
        },
    }).encode()
    path.write_bytes(before)
    monkeypatch.setattr(knowledge_store, "STORAGE_FILE", path)
    with pytest.raises(OSError):
        knowledge_store.create_knowledge_item(CreateKnowledgeItemRequest(title="New", thesis="Must reject damaged history"))
    assert path.read_bytes() == before
    assert (cold / "bad.json").read_bytes() == payload


def test_failed_knowledge_archive_publication_keeps_previous_history(monkeypatch, tmp_path):
    path = tmp_path / "knowledge.json"
    monkeypatch.setattr(knowledge_store, "STORAGE_FILE", path)
    monkeypatch.setenv("KNOWLEDGE_HOT_MAX_ITEMS", "3")
    originals = [knowledge_store.create_knowledge_item(CreateKnowledgeItemRequest(title=f"Item {index}", thesis="Preserve")) for index in range(3)]
    before = path.read_bytes()
    original_replace = file_utils.os.replace

    def fail_hot_write(source, target):
        if target == path:
            raise OSError("injected hot manifest publication failure")
        return original_replace(source, target)

    monkeypatch.setattr(file_utils.os, "replace", fail_hot_write)
    with pytest.raises(OSError):
        knowledge_store.create_knowledge_item(CreateKnowledgeItemRequest(title="Rejected", thesis="Do not publish"))
    assert path.read_bytes() == before
    assert {item.item_id for item in knowledge_store.list_knowledge_items()} == {item.item_id for item in originals}


def test_file_state_lock_serializes_processes_and_is_reentrant(tmp_path):
    path = tmp_path / "counter.json"
    file_utils.write_json_atomic(path, {"count": 0})
    worker = """
import json, sys, time
from pathlib import Path
from app.core.file_utils import file_state_lock, write_json_atomic
path = Path(sys.argv[1])
for _ in range(20):
    with file_state_lock(path):
        with file_state_lock(path):
            count = json.loads(path.read_text())['count']
            time.sleep(0.002)
            write_json_atomic(path, {'count': count + 1})
"""
    workers = [subprocess.Popen([sys.executable, "-c", worker, str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
    for process in workers:
        stdout, stderr = process.communicate(timeout=20)
        assert process.returncode == 0, (stdout + stderr).decode(errors="replace")
    assert json.loads(path.read_text())["count"] == 40


def test_ops_age_archive_batches_small_writes_and_preserves_repeated_ids(monkeypatch, tmp_path):
    path = tmp_path / "ops.jsonl"
    monkeypatch.setenv("OPS_LOG_FILE", str(path))
    monkeypatch.setenv("OPS_LOG_RETENTION_DAYS", "1")
    old_timestamp = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    log = OpsEventLog(max_events=100)
    for index in range(260):
        assert log.record_event({
            "id": "legitimate-repeated-id", "created_at": old_timestamp,
            "message": "historical event", "context": {"ordinal": index},
        }) is not None
    assert len(list(tmp_path.rglob("batch-*.json"))) == 1
    history = log.query_events(limit=200)
    assert history["event_count"] == 260
    assert history["storage_integrity"]["archived_event_count"] == 260
    assert [event["context"]["ordinal"] for event in history["events"]] == list(range(259, 59, -1))
    assert [event["context"]["ordinal"] for event in log.query_events(text='"ordinal": 0')["events"]] == [0]


def test_knowledge_pinned_active_items_do_not_force_one_cold_file_per_candidate(monkeypatch, tmp_path):
    path = tmp_path / "knowledge.json"
    monkeypatch.setattr(knowledge_store, "STORAGE_FILE", path)
    monkeypatch.setenv("KNOWLEDGE_HOT_MAX_ITEMS", "1")
    active = knowledge_store.create_knowledge_item(CreateKnowledgeItemRequest(title="Active", thesis="Keep active"))
    knowledge_store.review_knowledge_item(active.item_id, ReviewKnowledgeItemRequest(action="APPROVE"))
    for index in range(5):
        knowledge_store.create_learning_candidate_from_run({"runId": f"RUN_PINNED_{index}"})
    assert list(tmp_path.rglob("batch-*.json")) == []
    summary = knowledge_store.get_knowledge_summary()
    assert summary.active_count == 1
    assert summary.pending_count == 5
    assert summary.total == 6


def test_knowledge_review_does_not_rewrite_unchanged_legacy_cold_history(monkeypatch, tmp_path):
    path = tmp_path / "knowledge.json"
    monkeypatch.setattr(knowledge_store, "STORAGE_FILE", path)
    monkeypatch.setenv("KNOWLEDGE_HOT_MAX_ITEMS", "3")
    legacy = [{
        "item_id": f"LEGACY_{index}", "status": "PENDING_REVIEW", "category": "RUN_REVIEW",
        "title": f"Legacy {index}", "thesis": "Preserve stored history",
        "created_at": (datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=index)).isoformat(),
        "updated_at": (datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=index)).isoformat(),
    } for index in range(260)]
    path.write_text(json.dumps({"items": legacy}), encoding="utf-8")
    knowledge_store.create_knowledge_item(CreateKnowledgeItemRequest(title="New", thesis="Create a hot item"))
    chunks = list(tmp_path.rglob("batch-*.json"))
    assert len(chunks) == 1
    before = chunks[0].read_bytes()
    approved = knowledge_store.review_knowledge_item("LEGACY_0", ReviewKnowledgeItemRequest(action="APPROVE"))
    assert approved.status == "ACTIVE"
    assert list(tmp_path.rglob("batch-*.json")) == chunks
    assert chunks[0].read_bytes() == before
    knowledge_store.create_learning_candidate_from_run({"runId": "RUN_AFTER_LEGACY_REVIEW"})
    assert list(tmp_path.rglob("batch-*.json")) == chunks
    assert knowledge_store.get_knowledge_summary().total == 262
