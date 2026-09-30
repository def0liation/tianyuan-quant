"""Exports must retain cold audit history within the public bundle limit."""

import json
from datetime import datetime, timedelta, timezone
from hashlib import sha256

import pytest

from app.core.cold_archive import StorageCorruptionError
from app.core.ops_log import OpsEventLog


def _events(count):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        {
            "id": f"event-{index:04d}",
            "created_at": (start + timedelta(seconds=index)).isoformat(),
            "level": "warning" if index % 2 == 0 else "info",
            "message": "audit fixture",
        }
        for index in range(count)
    ]


@pytest.fixture
def archived_log(monkeypatch, tmp_path):
    path = tmp_path / "ops.jsonl"
    monkeypatch.setenv("OPS_LOG_FILE", str(path))
    monkeypatch.setenv("OPS_LOG_MAX_EVENTS", "100")
    monkeypatch.setenv("OPS_LOG_ARCHIVE_DIR", str(tmp_path / "cold"))
    monkeypatch.delenv("OPS_LOG_RETENTION_DAYS", raising=False)
    monkeypatch.delenv("TIANYUAN_OPS_LOG_RETENTION_DAYS", raising=False)
    events = _events(405)
    path.write_text("".join(json.dumps(event) + "\n" for event in events[:355]), encoding="utf-8")
    log = OpsEventLog()
    assert log.status()["event_count"] == 75
    with path.open("a", encoding="utf-8") as handle:
        handle.write("".join(json.dumps(event) + "\n" for event in events[355:]))
    assert log.status()["event_count"] == 75
    manifest = json.loads(path.with_name("ops.jsonl.archive-manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["batches"]) == 1
    assert len(manifest["pending_records"]) == 50
    return log


def test_export_includes_cold_batches_buffer_and_hot_events(archived_log):
    bundle = archived_log.export_bundle(limit=500)

    assert bundle["event_count"] == 405
    assert bundle["exported_count"] == 405
    assert [event["id"] for event in bundle["events"]] == [f"event-{index:04d}" for index in range(405)]
    encoded = json.dumps(bundle["events"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert bundle["checksum"] == f"sha256:{sha256(encoded).hexdigest()}"


def test_export_filters_cold_and_hot_history_before_applying_limit(archived_log):
    since = "2026-01-01T00:04:30Z"
    bundle = archived_log.export_bundle(limit=100, level="WARNING", since=since)

    assert bundle["event_count"] == 405
    assert bundle["level_filter"] == "warning"
    assert bundle["since"] == since
    assert [event["id"] for event in bundle["events"]] == [f"event-{index:04d}" for index in range(270, 405, 2)]
    bounded = archived_log.export_bundle(limit=5, level="warning", since=since)
    assert [event["id"] for event in bounded["events"]] == ["event-0396", "event-0398", "event-0400", "event-0402", "event-0404"]


@pytest.mark.parametrize(("limit", "count", "first"), [(0, 100, "event-0305"), (-5, 1, "event-0404"), (1, 1, "event-0404")])
def test_export_retains_existing_limit_normalization(archived_log, limit, count, first):
    bundle = archived_log.export_bundle(limit=limit)
    assert bundle["exported_count"] == count
    assert bundle["events"][0]["id"] == first


def test_export_caps_bundle_at_1000_independently_of_hot_retention(archived_log):
    path = archived_log.log_file()
    with path.open("a", encoding="utf-8") as handle:
        handle.write("".join(json.dumps(event) + "\n" for event in _events(1205)[405:]))

    bundle = archived_log.export_bundle(limit=2000)
    assert bundle["event_count"] == 1205
    assert bundle["exported_count"] == 1000
    assert [event["id"] for event in bundle["events"]] == [f"event-{index:04d}" for index in range(205, 1205)]


def test_export_invalid_since_is_ignored_and_future_since_is_empty(archived_log):
    bundle = archived_log.export_bundle(limit=500, since="invalid")
    assert bundle["since"] == ""
    assert bundle["exported_count"] == 405
    empty = archived_log.export_bundle(since="2027-01-01T00:00:00Z")
    assert empty["event_count"] == 405
    assert empty["exported_count"] == 0
    assert empty["events"] == []
    assert empty["checksum"] == f"sha256:{sha256(b'[]').hexdigest()}"


@pytest.mark.parametrize("damage", ["missing", "checksum"])
def test_damaged_archive_cannot_produce_a_partial_export_or_handoff(archived_log, monkeypatch, tmp_path, damage):
    batch = next((tmp_path / "cold").glob("batch-*.json"))
    if damage == "missing":
        batch.unlink()
    else:
        batch.write_bytes(b"{}")
    handoff_dir = tmp_path / "handoff"
    monkeypatch.setenv("OPS_LOG_EXPORT_HANDOFF_DIR", str(handoff_dir))
    hot_before = archived_log.log_file().read_bytes()

    with pytest.raises(StorageCorruptionError):
        archived_log.export_bundle()
    with pytest.raises(StorageCorruptionError):
        archived_log.handoff_export_bundle()
    assert archived_log.log_file().read_bytes() == hot_before
    assert not handoff_dir.exists()
