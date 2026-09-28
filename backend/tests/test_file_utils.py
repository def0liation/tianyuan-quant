import json

import pytest

from app.core import file_utils


def test_write_json_atomic_writes_payload(tmp_path):
    target = tmp_path / "state.json"

    file_utils.write_json_atomic(target, {"version": 1, "items": ["a", "b"]})

    assert json.loads(target.read_text(encoding="utf-8")) == {"version": 1, "items": ["a", "b"]}
    assert list(tmp_path.glob("*.tmp")) == []


def test_write_json_atomic_creates_parent_directories(tmp_path):
    target = tmp_path / "nested" / "dir" / "state.json"

    file_utils.write_json_atomic(target, {"ok": True})

    assert json.loads(target.read_text(encoding="utf-8")) == {"ok": True}


def test_write_json_atomic_retries_transient_permission_error(monkeypatch, tmp_path):
    monkeypatch.setattr(file_utils.time, "sleep", lambda _seconds: None)
    real_replace = file_utils.os.replace
    attempts = []

    def flaky_replace(source, target):
        attempts.append((source, target))
        if len(attempts) < 3:
            raise PermissionError("target locked")
        return real_replace(source, target)

    monkeypatch.setattr(file_utils.os, "replace", flaky_replace)

    target = tmp_path / "state.json"
    file_utils.write_json_atomic(target, {"value": 42})

    assert len(attempts) == 3
    assert json.loads(target.read_text(encoding="utf-8")) == {"value": 42}
    assert list(tmp_path.glob("*.tmp")) == []


def test_write_json_atomic_cleans_up_temp_when_replace_permanently_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(file_utils.time, "sleep", lambda _seconds: None)

    def always_locked(_source, _target):
        raise PermissionError("target permanently locked")

    monkeypatch.setattr(file_utils.os, "replace", always_locked)

    target = tmp_path / "state.json"
    with pytest.raises(PermissionError):
        file_utils.write_json_atomic(target, {"value": 1})

    assert not target.exists()
    assert list(tmp_path.glob("*.tmp")) == []


def test_write_json_atomic_serializes_non_native_types(tmp_path):
    target = tmp_path / "state.json"

    file_utils.write_json_atomic(target, {"set_like": {"only", "strings"}, "path": tmp_path})

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert isinstance(payload["path"], str)
