import shutil
import sqlite3
from pathlib import Path

import pytest

from app.db import backup


def _database(path, value):
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE marker(value TEXT)")
        connection.execute("INSERT INTO marker VALUES(?)", (value,))


def test_readonly_database_backup_can_restore_to_fresh_target(tmp_path):
    source = tmp_path / "source.db"
    _database(source, "preserved")
    saved = backup.backup_sqlite(source, tmp_path / "backups")
    backup_file = Path(saved["backup_file"])
    original = backup_file.read_bytes()
    backup_file.chmod(0o444)
    try:
        target = tmp_path / "new.db"
        result = backup.restore_sqlite(backup_file, target)
        assert result["restored"] is True
        with sqlite3.connect(target) as connection:
            assert connection.execute("SELECT value FROM marker").fetchone()[0] == "preserved"
        assert backup_file.read_bytes() == original
    finally:
        backup_file.chmod(0o666)


def test_bundle_database_is_bound_to_verified_manifest_after_staging(tmp_path, monkeypatch):
    source = tmp_path / "source.db"
    _database(source, "original")
    storage = tmp_path / "app"
    storage.mkdir()
    (storage / "history.json").write_text('{"runs":["preserved"]}', encoding="utf-8")
    bundle = backup.backup_storage_bundle(source, storage, tmp_path / "bundles")
    manifest = backup.verify_storage_bundle(bundle["bundle_dir"])["manifest"]
    bundle_db = Path(bundle["bundle_dir"]) / manifest["database"]
    alternate = tmp_path / "alternate.db"
    _database(alternate, "replaced")
    alternate_backup = backup.backup_sqlite(alternate, tmp_path / "alternate-backup")
    restore = backup.restore_sqlite

    def change_after_verification(*args, **kwargs):
        shutil.copy2(alternate_backup["backup_file"], bundle_db)
        shutil.copy2(alternate_backup["manifest_file"], bundle_db.with_suffix(bundle_db.suffix + ".manifest.json"))
        return restore(*args, **kwargs)

    monkeypatch.setattr(backup, "restore_sqlite", change_after_verification)
    target_db = tmp_path / "new.db"
    target_storage = tmp_path / "new-app"
    with pytest.raises(ValueError, match="Staged storage bundle"):
        backup.restore_storage_bundle(bundle["bundle_dir"], target_db, target_storage)
    assert not target_db.exists()
    assert not target_storage.exists()


def test_bundle_rejects_unlisted_file_added_after_verification(tmp_path, monkeypatch):
    source = tmp_path / "source.db"
    _database(source, "preserved")
    storage = tmp_path / "app"
    storage.mkdir()
    (storage / "history.json").write_text('{}', encoding="utf-8")
    bundle = backup.backup_storage_bundle(source, storage, tmp_path / "bundles")
    original_copy = backup._copy_storage
    bundle_storage = Path(bundle["bundle_dir"]) / "app-storage"

    def add_after_verification(source_path, destination):
        if source_path == bundle_storage:
            (source_path / "unlisted.json").write_text('{}', encoding="utf-8")
        return original_copy(source_path, destination)

    monkeypatch.setattr(backup, "_copy_storage", add_after_verification)
    target_db = tmp_path / "new.db"
    target_storage = tmp_path / "new-app"
    with pytest.raises(ValueError, match="Staged storage bundle"):
        backup.restore_storage_bundle(bundle["bundle_dir"], target_db, target_storage)
    assert not target_db.exists()
    assert not target_storage.exists()


def test_bundle_publish_cleanup_failure_rolls_back_current_file(tmp_path, monkeypatch):
    source = tmp_path / "source.db"
    _database(source, "preserved")
    storage = tmp_path / "app"
    storage.mkdir()
    (storage / "history.json").write_text('{}', encoding="utf-8")
    bundle = backup.backup_storage_bundle(source, storage, tmp_path / "bundles")
    target_db = tmp_path / "new.db"
    target_storage = tmp_path / "new-app"
    unlink = Path.unlink

    def fail_current_stage_cleanup(path, *args, **kwargs):
        if ".bundle_restore_" in path.name and target_db.exists():
            raise PermissionError("synthetic post-publication cleanup failure")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_current_stage_cleanup)
    with pytest.raises(PermissionError, match="synthetic"):
        backup.restore_storage_bundle(bundle["bundle_dir"], target_db, target_storage)
    assert not target_db.exists()
    assert not target_storage.exists()
