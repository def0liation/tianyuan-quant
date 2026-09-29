import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.api import routes_analysis
from app.core import agent_runtime_store, analysis_job_store, file_utils
from app.core.cold_archive import StorageCorruptionError, load_records


def _seed_run(run_id, status, updated_at):
    job = analysis_job_store.start_job(run_id)
    if status == "COMPLETED":
        job = analysis_job_store.mark_completed(run_id)
    elif status == "FAILED":
        job = analysis_job_store.mark_failed(run_id, "failed node", "final_writer")
    elif status == "CANCELLED":
        job = analysis_job_store.mark_cancelled(run_id)
    elif status == "RUNNING":
        job = analysis_job_store.mark_running(run_id, worker_id="active-worker")
    run = {
        "runId": run_id,
        "status": status,
        "updatedAt": updated_at,
        "createdAt": updated_at,
        "job": job,
        "nodes": [{"id": "final_writer", "status": "WAIT", "outputSummary": run_id}],
        "finalWriter": {"marker": run_id},
        "agentResults": [{"node": "final_writer", "data": {"output_summary": run_id}}],
    }
    agent_runtime_store.save_run(run)
    return run


def _seed_history():
    return {
        run["runId"]: run
        for run in (
            _seed_run("RUN_ARCHIVE_A", "COMPLETED", "2000-01-01T00:00:00"),
            _seed_run("RUN_ARCHIVE_B", "FAILED", "2001-01-01T00:00:00"),
            _seed_run("RUN_ARCHIVE_C", "CANCELLED", "2002-01-01T00:00:00"),
            _seed_run("RUN_ARCHIVE_RUNNING", "RUNNING", "2003-01-01T00:00:00"),
            _seed_run("RUN_ARCHIVE_CREATED", "CREATED", "2004-01-01T00:00:00"),
        )
    }


def _hot_bytes():
    return {path.name: path.read_bytes() for path in agent_runtime_store.RUNS_DIR.glob("RUN_*.json")}


def test_run_archive_defaults_to_dry_run_and_preserves_hot_history():
    _seed_history()
    before = _hot_bytes()

    report = agent_runtime_store.archive_terminal_runs(max_hot=2)

    assert report["dry_run"] is True
    assert set(report["candidate_run_ids"]) == {"RUN_ARCHIVE_A", "RUN_ARCHIVE_B", "RUN_ARCHIVE_C"}
    assert report["archived_count"] == 0
    assert _hot_bytes() == before
    assert not (agent_runtime_store.RUNS_DIR / ".archive").exists()


def test_run_archive_roundtrip_keeps_every_record_and_is_idempotent():
    original = _seed_history()

    report = agent_runtime_store.archive_terminal_runs(max_hot=2, dry_run=False)

    assert report["archived_count"] == 3
    assert len(_hot_bytes()) == 2
    for run_id, run in original.items():
        assert agent_runtime_store.get_run(run_id) == run
    assert agent_runtime_store.load_persisted_runs() == original
    assert {item["runId"] for item in agent_runtime_store.list_runs()} == set(original)
    archive_dir = agent_runtime_store.RUNS_DIR / ".archive"
    manifest = json.loads((archive_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["deletion_enabled"] is False
    assert len(manifest["batches"]) == 1
    assert len(manifest["batches"][0]["sha256"]) == 64
    assert set(load_records(archive_dir, manifest)) == {"RUN_ARCHIVE_A", "RUN_ARCHIVE_B", "RUN_ARCHIVE_C"}
    second = agent_runtime_store.archive_terminal_runs(max_hot=2, dry_run=False)
    assert second["archived_count"] == 0
    assert len(list(archive_dir.glob("batch-*.json"))) == 1


def test_run_archive_keeps_terminal_payload_with_active_worker_job_hot():
    _seed_history()
    active = _seed_run("RUN_ARCHIVE_ACTIVE_TERMINAL_BODY", "RUNNING", "1990-01-01T00:00:00")
    active["status"] = "COMPLETED"
    agent_runtime_store.save_run(active)
    before = (agent_runtime_store.RUNS_DIR / "RUN_ARCHIVE_ACTIVE_TERMINAL_BODY.json").read_bytes()

    agent_runtime_store.archive_terminal_runs(max_hot=2, dry_run=False)

    assert (agent_runtime_store.RUNS_DIR / "RUN_ARCHIVE_ACTIVE_TERMINAL_BODY.json").read_bytes() == before
    assert analysis_job_store.get_job(active["runId"])["status"] == "RUNNING"
    assert agent_runtime_store.get_run(active["runId"])["finalWriter"]["marker"] == active["runId"]


def test_run_archive_manifest_failure_preserves_every_hot_file(monkeypatch):
    _seed_history()
    before = _hot_bytes()
    real_replace = file_utils.atomic_replace_file

    def fail_manifest(source, target, **kwargs):
        if Path(target).name == "manifest.json":
            raise OSError("simulated archive manifest failure")
        return real_replace(source, target, **kwargs)

    monkeypatch.setattr(file_utils, "atomic_replace_file", fail_manifest)

    with pytest.raises(OSError, match="simulated archive manifest failure"):
        agent_runtime_store.archive_terminal_runs(max_hot=2, dry_run=False)

    assert _hot_bytes() == before
    assert len(agent_runtime_store.list_runs()) == 5
    assert not (agent_runtime_store.RUNS_DIR / ".archive" / "manifest.json").exists()


def test_run_archive_checksum_mismatch_blocks_cold_reads_and_maintenance():
    _seed_history()
    agent_runtime_store.archive_terminal_runs(max_hot=2, dry_run=False)
    before = _hot_bytes()
    archive_dir = agent_runtime_store.RUNS_DIR / ".archive"
    block = next(archive_dir.glob("batch-*.json"))
    block.write_bytes(b"corrupted cold block")

    with pytest.raises(StorageCorruptionError):
        agent_runtime_store.get_run("RUN_ARCHIVE_A")
    with pytest.raises(StorageCorruptionError):
        agent_runtime_store.archive_terminal_runs(max_hot=2, dry_run=False)

    assert _hot_bytes() == before


@pytest.mark.asyncio
async def test_archived_terminal_run_retry_creates_current_hot_overlay(monkeypatch):
    _seed_history()
    agent_runtime_store.archive_terminal_runs(max_hot=2, dry_run=False)
    archive_dir = agent_runtime_store.RUNS_DIR / ".archive"
    block = next(archive_dir.glob("batch-*.json"))
    before = block.read_bytes()
    monkeypatch.setenv("ANALYSIS_EXECUTION_MODE", "worker")

    async def ready(_run_id, _run):
        return False

    monkeypatch.setattr(routes_analysis, "_ensure_run_framework_ready", ready)

    result = await routes_analysis.retry_analysis_run("RUN_ARCHIVE_A", {"from_node_id": "final_writer"})

    assert result.status == "QUEUED"
    current = agent_runtime_store.get_run("RUN_ARCHIVE_A")
    assert current["job"]["attempt"] == 2
    assert current["status"] == "QUEUED"
    assert (agent_runtime_store.RUNS_DIR / "RUN_ARCHIVE_A.json").exists()
    assert block.read_bytes() == before
    assert len(agent_runtime_store.list_runs()) == 5


@pytest.mark.asyncio
async def test_explicit_archive_delete_hides_run_without_erasing_cold_history():
    _seed_history()
    agent_runtime_store.archive_terminal_runs(max_hot=2, dry_run=False)
    archive_dir = agent_runtime_store.RUNS_DIR / ".archive"
    block = next(archive_dir.glob("batch-*.json"))
    before = block.read_bytes()

    result = await routes_analysis.delete_analysis_run("RUN_ARCHIVE_A")

    assert result["deleted"] == "RUN_ARCHIVE_A"
    assert agent_runtime_store.get_run("RUN_ARCHIVE_A") is None
    assert "RUN_ARCHIVE_A" not in agent_runtime_store.load_persisted_runs()
    assert block.read_bytes() == before
    manifest = json.loads((archive_dir / "manifest.json").read_text(encoding="utf-8"))
    assert load_records(archive_dir, manifest)["RUN_ARCHIVE_A"]["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_failed_archive_delete_does_not_acknowledge_or_drop_cache(monkeypatch):
    _seed_history()
    agent_runtime_store.archive_terminal_runs(max_hot=2, dry_run=False)
    routes_analysis.runs_store["RUN_ARCHIVE_A"] = agent_runtime_store.get_run("RUN_ARCHIVE_A")
    real_replace = file_utils.atomic_replace_file

    def fail_manifest(source, target, **kwargs):
        if Path(target).name == "manifest.json":
            raise OSError("simulated delete manifest failure")
        return real_replace(source, target, **kwargs)

    monkeypatch.setattr(file_utils, "atomic_replace_file", fail_manifest)

    with pytest.raises(HTTPException) as info:
        await routes_analysis.delete_analysis_run("RUN_ARCHIVE_A")

    assert info.value.status_code == 409
    assert routes_analysis.runs_store["RUN_ARCHIVE_A"]["status"] == "COMPLETED"
    assert agent_runtime_store.get_run("RUN_ARCHIVE_A")["status"] == "COMPLETED"
