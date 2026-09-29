"""Synthetic storage only: deployment, restore and readiness regressions."""
import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import uuid
from contextlib import closing
from pathlib import Path

import pytest

from app.core.startup_status import StartupStatusRegistry
from app.db import backup as backup_module


def make_database(path, value="original"):
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE sample (value TEXT)")
        connection.execute("INSERT INTO sample VALUES (?)", (value,))
        connection.commit()
    return path


def read_database(path):
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute("SELECT value FROM sample").fetchone()[0]


def test_backup_does_not_overwrite_previous_same_second_backup(tmp_path, monkeypatch):
    source = make_database(tmp_path / "source.sqlite")
    monkeypatch.setattr(backup_module, "_now_slug", lambda: "20260929T000000Z")
    first = backup_module.backup_sqlite(source, tmp_path / "backups")
    with sqlite3.connect(source) as connection:
        connection.execute("UPDATE sample SET value='later'")
    second = backup_module.backup_sqlite(source, tmp_path / "backups")
    assert first["backup_file"] != second["backup_file"]
    assert read_database(first["backup_file"]) == "original"
    assert read_database(second["backup_file"]) == "later"


def test_restore_rejects_active_wal_database_and_preserves_bytes(tmp_path):
    source = make_database(tmp_path / "backup.sqlite", "restored")
    target = make_database(tmp_path / "active.sqlite")
    with sqlite3.connect(target) as active:
        active.execute("PRAGMA journal_mode=WAL")
        active.execute("BEGIN IMMEDIATE")
        active.execute("UPDATE sample SET value='in-flight'")
        before = target.read_bytes()
        with pytest.raises((RuntimeError, PermissionError, OSError)):
            backup_module.restore_sqlite(source, target, force=True)
        assert target.read_bytes() == before
        active.rollback()
    assert read_database(target) == "original"


def test_restore_rejects_idle_open_database_handle(tmp_path):
    if os.name != "nt":
        pytest.skip("Windows share-mode contract; non-Windows overwrite is rejected separately")
    source = make_database(tmp_path / "backup.sqlite", "restored")
    target = make_database(tmp_path / "target.sqlite")
    active = sqlite3.connect(target)
    active.execute("SELECT value FROM sample").fetchone()
    try:
        with pytest.raises((RuntimeError, PermissionError, OSError)):
            backup_module.restore_sqlite(source, target, force=True)
        assert read_database(target) == "original"
    finally:
        active.close()


def test_restore_validates_staged_copy_before_touching_target(tmp_path, monkeypatch):
    source = make_database(tmp_path / "backup.sqlite", "restored")
    target = make_database(tmp_path / "target.sqlite")
    original_copy = backup_module.shutil.copyfile

    def corrupt_staged_copy(src, dst, *args, **kwargs):
        result = original_copy(src, dst, *args, **kwargs)
        if Path(src) == source:
            Path(dst).write_bytes(b"synthetic corrupted stage")
        return result

    monkeypatch.setattr(backup_module.shutil, "copyfile", corrupt_staged_copy)
    before = target.read_bytes()
    with pytest.raises((ValueError, sqlite3.DatabaseError)):
        backup_module.restore_sqlite(source, target, force=True)
    assert target.read_bytes() == before


@pytest.mark.parametrize("target_name", ["target.sqlite", "x.sqlite", "very-long-target-name.sqlite", "中文.sqlite", "emoji😀.sqlite"])
def test_restore_preserves_previous_and_dry_run_does_not_write(tmp_path, target_name):
    source = make_database(tmp_path / "backup.sqlite", "restored")
    target = make_database(tmp_path / target_name)
    before = target.read_bytes()
    dry = backup_module.restore_sqlite(source, target, dry_run=True)
    assert dry["restored"] is False
    assert target.read_bytes() == before
    if os.name != "nt":
        with pytest.raises(RuntimeError):
            backup_module.restore_sqlite(source, target, force=True)
        return
    result = backup_module.restore_sqlite(source, target, force=True)
    assert read_database(target) == "restored"
    assert read_database(result["previous_file"]) == "original"


def test_storage_bundle_restores_complete_stopped_checkpoint_and_validates_hashes(tmp_path):
    source = make_database(tmp_path / "source.sqlite", "checkpoint")
    app_storage = tmp_path / "app-storage"
    for name, content in {
        "agent_runtime.json": '{"source":"synthetic"}',
        "runs/run.json": '{"simulation_only":true}',
        "plugins/custom.json": '{"enabled":false}',
        "runtime-secrets.vault.json": '{"encrypted":"synthetic-not-a-secret"}',
        "runtime-secrets.key": "synthetic-key-only",
    }.items():
        file = app_storage / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content, encoding="utf-8")
    external = tmp_path / "external-archive"
    external.mkdir()
    (external / "batch.json").write_text('{"archive":"synthetic"}', encoding="utf-8")
    assert callable(getattr(backup_module, "backup_storage_bundle", None)), "Complete storage bundle entry is missing"
    bundle = backup_module.backup_storage_bundle(source, app_storage, tmp_path / "bundles", extra_paths={"archive": external})
    directory = Path(bundle["bundle_dir"])
    before = {str(file.relative_to(directory)): file.read_bytes() for file in directory.rglob("*") if file.is_file()}
    verified = backup_module.verify_storage_bundle(directory)
    assert verified["valid"] is True
    assert {str(file.relative_to(directory)): file.read_bytes() for file in directory.rglob("*") if file.is_file()} == before
    restored_db = tmp_path / "new" / "db.sqlite"
    restored_storage = tmp_path / "new" / "app-storage"
    restored_archive = tmp_path / "new" / "archive"
    result = backup_module.restore_storage_bundle(directory, restored_db, restored_storage, extra_targets={"archive": restored_archive})
    assert result["restored"] is True
    assert read_database(restored_db) == "checkpoint"
    assert (restored_storage / "runtime-secrets.key").read_text() == "synthetic-key-only"
    assert (restored_storage / "runs/run.json").read_text() == '{"simulation_only":true}'
    assert (restored_archive / "batch.json").read_text() == '{"archive":"synthetic"}'
    with pytest.raises(FileExistsError):
        backup_module.restore_storage_bundle(directory, restored_db, restored_storage, extra_targets={"archive": restored_archive})
    manifest = json.loads((directory / "manifest.json").read_text())
    protected_file = directory / manifest["files"][0]["path"]
    protected_file.write_bytes(b"tampered synthetic fixture")
    with pytest.raises(ValueError):
        backup_module.verify_storage_bundle(directory)


def test_startup_returned_error_is_error_and_required_failure_never_core_ready(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)

    async def run():
        registry = StartupStatusRegistry()
        async def returned_failure():
            return {"status": "error", "message": "synthetic migration failure"}
        result = await registry.run_component("database_migrations", "core", returned_failure, required=True)
        assert result["status"] == "error"
        await registry.mark_core_ready()
        await registry.mark_finished()
        snapshot = await registry.snapshot()
        assert snapshot["components"][0]["status"] == "ERROR"
        assert snapshot["coreReady"] is False
        assert snapshot["ready"] is False
    asyncio.run(run())


def test_startup_required_returned_error_fails_fast_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    async def run():
        async def returned_failure():
            return {"status": "error", "message": "synthetic failure"}
        with pytest.raises(RuntimeError):
            await StartupStatusRegistry().run_component("database_migrations", "core", returned_failure, required=True)
    asyncio.run(run())


def test_readiness_uses_effective_sqlite_path_and_preserves_existing_probe(tmp_path, monkeypatch):
    from app.api import routes_health
    effective = tmp_path / "actual-db" / "runtime.sqlite"
    effective.parent.mkdir()
    make_database(effective)
    wrong = tmp_path / "wrong-default" / "runtime.sqlite"
    sentinel = effective.parent / ".ready_probe"
    sentinel.write_text("must not be overwritten")
    monkeypatch.setattr(routes_health, "DATABASE_URL", f"sqlite+aiosqlite:///{effective}")
    monkeypatch.setattr(routes_health, "DB_PATH", wrong)
    assert routes_health._check_storage()["status"] == "ok"
    assert sentinel.read_text() == "must not be overwritten"
    assert not wrong.parent.exists()
    assert routes_health._storage_metrics()["databasePath"] == str(effective)


@pytest.mark.parametrize("corrupt", [False, True])
def test_powershell_backup_empty_label_absolute_path_and_native_exit(tmp_path, corrupt):
    if os.name != "nt":
        pytest.skip("PowerShell executable integration is a Windows contract")
    project = Path(__file__).resolve().parents[2]
    source = tmp_path / "absolute input.sqlite"
    if corrupt:
        source.write_bytes(b"not a database")
    else:
        make_database(source)
    env = {**os.environ, "PYTHON": sys.executable}
    proc = subprocess.run(["powershell.exe", "-NoProfile", "-File", str(project / "scripts/db-backup.ps1"), "-SourceDb", str(source), "-BackupDir", str(tmp_path / "absolute backups")], cwd=project, env=env, capture_output=True, text=True)
    if corrupt:
        assert proc.returncode != 0
    else:
        assert proc.returncode == 0, proc.stderr
        created = list((tmp_path / "absolute backups").glob("*.sqlite"))
        assert len(created) == 1, proc.stdout + proc.stderr
        assert read_database(created[0]) == "original"


@pytest.mark.parametrize("command", ["backup", "restore"])
def test_powershell_propagates_native_database_failure(command):
    if os.name != "nt":
        pytest.skip("PowerShell executable integration is a Windows contract")
    project = Path(__file__).resolve().parents[2]
    fixture = project / ".tmp" / "db-backup-restore-drill" / uuid.uuid4().hex
    fixture.mkdir(parents=True)
    corrupt = fixture / "corrupt.sqlite"
    corrupt.write_bytes(b"synthetic invalid sqlite")
    if command == "backup":
        arguments = ["-SourceDb", str(corrupt.relative_to(project)), "-BackupDir", str((fixture / "backups").relative_to(project)), "-Label", "synthetic"]
    else:
        arguments = ["-BackupFile", str(corrupt), "-TargetDb", str(fixture / "restore.sqlite"), "-DryRun"]
    proc = subprocess.run(["powershell.exe", "-NoProfile", "-File", str(project / f"scripts/db-{command}.ps1"), *arguments], cwd=project, env={**os.environ, "PYTHON": sys.executable}, capture_output=True, text=True)
    assert proc.returncode != 0, proc.stdout + proc.stderr


@pytest.mark.parametrize("failing", [False, True])
def test_backend_runner_cleans_only_successful_owned_temp_paths(failing):
    if os.name != "nt":
        pytest.skip("PowerShell executable integration is a Windows contract")
    project = Path(__file__).resolve().parents[2]
    fixture = project / ".tmp" / "runner-fixtures" / uuid.uuid4().hex
    fixture.mkdir(parents=True)
    test_file = fixture / "test_synthetic.py"
    test_file.write_text("def test_synthetic(tmp_path):\n    (tmp_path / 'diagnostic.txt').write_text('synthetic')\n    assert " + ("False" if failing else "True") + "\n")
    historical = project / ".tmp" / ("historical-" + uuid.uuid4().hex)
    historical.mkdir()
    (historical / "keep.txt").write_text("historical diagnostic")
    before = set((project / ".tmp").glob("pytest-basetemp-*"))
    env = {**os.environ, "TIANYUAN_BACKEND_TEST_PYTHON": sys.executable, "LOCALAPPDATA": str(fixture / "local-appdata")}
    proc = subprocess.run(["powershell.exe", "-NoProfile", "-File", str(project / "scripts/test-backend.ps1"), str(test_file), "-q"], cwd=project, env=env, capture_output=True, text=True)
    assert (proc.returncode != 0) == failing, proc.stdout + proc.stderr
    new_basetemps = set((project / ".tmp").glob("pytest-basetemp-*")) - before
    new_systemtemps = list((fixture / "local-appdata/Temp/tianyuan-quant-agent-ui").glob("pytest-temp-*"))
    assert bool(new_basetemps) == failing
    assert bool(new_systemtemps) == failing
    assert (historical / "keep.txt").read_text() == "historical diagnostic"


def test_powershell_restore_preserves_dry_run_and_force_positive_contract():
    if os.name != "nt":
        pytest.skip("PowerShell executable integration is a Windows contract")
    project = Path(__file__).resolve().parents[2]
    fixture = project / ".tmp" / "db-backup-restore-drill" / uuid.uuid4().hex
    source = make_database(fixture / "source.sqlite", "new")
    target = make_database(fixture / "target.sqlite", "old")
    env = {**os.environ, "PYTHON": sys.executable}
    arguments = ["powershell.exe", "-NoProfile", "-File", str(project / "scripts/db-restore.ps1"), "-BackupFile", str(source), "-TargetDb", str(target)]
    dry = subprocess.run([*arguments, "-DryRun"], cwd=project, env=env, capture_output=True, text=True)
    assert dry.returncode == 0, dry.stdout + dry.stderr
    assert read_database(target) == "old"
    restored = subprocess.run([*arguments, "-Force"], cwd=project, env=env, capture_output=True, text=True)
    assert restored.returncode == 0, restored.stdout + restored.stderr
    assert read_database(target) == "new"
    previous = list(fixture.glob("target.sqlite.pre_restore_*"))
    assert len(previous) == 1
    assert read_database(previous[0]) == "old"


def test_backend_runner_retains_user_basetemp_and_restores_environment():
    if os.name != "nt":
        pytest.skip("PowerShell executable integration is a Windows contract")
    project = Path(__file__).resolve().parents[2]
    fixture = project / ".tmp" / "runner-fixtures" / uuid.uuid4().hex
    fixture.mkdir(parents=True)
    test_file = fixture / "test_synthetic.py"
    test_file.write_text("def test_synthetic(tmp_path):\n    (tmp_path / 'diagnostic.txt').write_text('synthetic')\n")
    user_base = fixture / "user-basetemp"
    def ps_quote(value):
        return "'" + str(value).replace("'", "''") + "'"
    command = "; ".join([
        "$env:TEMP='original-test-temp'", "$env:TMP='original-test-tmp'", "$env:PYTHONPATH='original-test-pythonpath'", "$env:UV_CACHE_DIR='original-test-cache'",
        "& " + ps_quote(project / "scripts/test-backend.ps1") + " " + ps_quote(test_file) + " '-q' " + ps_quote(f"--basetemp={user_base}"),
        "if ($env:TEMP -ne 'original-test-temp' -or $env:TMP -ne 'original-test-tmp' -or $env:PYTHONPATH -ne 'original-test-pythonpath' -or $env:UV_CACHE_DIR -ne 'original-test-cache') { throw 'Test runner changed caller environment' }",
    ])
    env = {**os.environ, "TIANYUAN_BACKEND_TEST_PYTHON": sys.executable, "LOCALAPPDATA": str(fixture / "local-appdata")}
    proc = subprocess.run(["powershell.exe", "-NoProfile", "-Command", command], cwd=project, env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert list(user_base.rglob("diagnostic.txt"))


def test_storage_bundle_rejects_path_traversal_without_external_io(tmp_path):
    source = make_database(tmp_path / "source.sqlite")
    storage = tmp_path / "app-storage"
    storage.mkdir()
    bundle = backup_module.backup_storage_bundle(source, storage, tmp_path / "bundles")
    root = Path(bundle["bundle_dir"])
    manifest_file = root / "manifest.json"
    manifest = json.loads(manifest_file.read_text())
    manifest["files"][0]["path"] = "../outside.sqlite"
    manifest_file.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        backup_module.verify_storage_bundle(root)
    assert not (root.parent / "outside.sqlite").exists()


def test_startup_legal_skip_and_optional_returned_error_keep_core_readiness(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    async def run():
        registry = StartupStatusRegistry()
        async def skipped():
            return {"status": "skipped", "reason": "explicit development test setting"}
        async def optional_failure():
            return {"status": "error", "message": "optional warmup unavailable"}
        await registry.run_component("database_migrations", "core", skipped, required=True)
        await registry.mark_core_ready()
        await registry.run_component("warmer", "optional", optional_failure)
        await registry.mark_finished()
        snapshot = await registry.snapshot()
        assert snapshot["coreReady"] is True
        assert snapshot["ready"] is False
        assert snapshot["degradedComponents"] == ["warmer"]
    asyncio.run(run())


def test_online_wal_backup_is_committed_snapshot_and_bundle_reports_independent_files(tmp_path):
    source = make_database(tmp_path / "active.sqlite")
    storage = tmp_path / "app-storage"
    storage.mkdir()
    (storage / "synthetic.json").write_text('{"fixture":true}')
    with closing(sqlite3.connect(source)) as active:
        active.execute("PRAGMA journal_mode=WAL")
        active.execute("BEGIN IMMEDIATE")
        active.execute("UPDATE sample SET value='not committed'")
        backup = backup_module.backup_sqlite(source, tmp_path / "backups")
        assert read_database(backup["backup_file"]) == "original"
        bundle = backup_module.backup_storage_bundle(source, storage, tmp_path / "bundles")
        assert bundle["consistency"] == "independent_snapshots"
        assert bundle["requires_stopped_writers_for_consistent_checkpoint"] is True
        active.rollback()


def test_failed_atomic_restore_preserves_target_and_previous(tmp_path, monkeypatch):
    if os.name != "nt":
        pytest.skip("Protected atomic replacement is a Windows contract")
    source = make_database(tmp_path / "source.sqlite", "new")
    target = make_database(tmp_path / "target.sqlite", "old")
    def fail_replace(stage, destination):
        raise OSError("synthetic rename failure")
    monkeypatch.setattr(backup_module, "_replace_protected_database", fail_replace)
    with pytest.raises(OSError):
        backup_module.restore_sqlite(source, target, force=True)
    assert read_database(target) == "old"
    previous = list(tmp_path.glob("target.sqlite.pre_restore_*"))
    assert len(previous) == 1
    assert read_database(previous[0]) == "old"


def test_bundle_stage_failure_leaves_all_existing_destinations_untouched(tmp_path, monkeypatch):
    source = make_database(tmp_path / "source.sqlite")
    storage = tmp_path / "app-storage"
    storage.mkdir()
    (storage / "runtime.json").write_text('{"original":true}')
    bundle = backup_module.backup_storage_bundle(source, storage, tmp_path / "bundles")
    root = Path(bundle["bundle_dir"])
    target_db = tmp_path / "new.sqlite"
    target_storage = tmp_path / "new-storage"
    copy_storage = backup_module._copy_storage
    def corrupt_copy(src, destination):
        kind = copy_storage(src, destination)
        if src == root / "app-storage":
            (destination / "runtime.json").write_text("corrupted stage")
        return kind
    monkeypatch.setattr(backup_module, "_copy_storage", corrupt_copy)
    with pytest.raises(ValueError):
        backup_module.restore_storage_bundle(root, target_db, target_storage)
    assert not target_db.exists()
    assert not target_storage.exists()
    assert (storage / "runtime.json").read_text() == '{"original":true}'
