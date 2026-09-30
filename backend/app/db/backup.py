from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import uuid
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Dict


def _now_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sqlite_integrity_check(path: str | Path) -> str:
    source = Path(path).resolve()
    with closing(sqlite3.connect(f"{source.as_uri()}?mode=ro&immutable=1", uri=True)) as conn:
        row = conn.execute("PRAGMA integrity_check").fetchone()
    return str(row[0] if row else "missing")


def backup_sqlite(source_db: str | Path, backup_dir: str | Path, *, label: str = "") -> Dict[str, Any]:
    source = Path(source_db).resolve()
    if not source.exists():
        raise FileNotFoundError(f"SQLite database not found: {source}")
    destination_dir = Path(backup_dir).resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)
    safe_label = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in label.strip())[:40]
    suffix = f"_{safe_label}" if safe_label else ""
    backup_file = destination_dir / f"{source.stem}_{_now_slug()}{suffix}_{uuid.uuid4().hex[:12]}.sqlite"

    with closing(sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True)) as src, closing(sqlite3.connect(str(backup_file))) as dst:
        src.backup(dst)

    checksum = sha256_file(backup_file)
    integrity = sqlite_integrity_check(backup_file)
    if integrity.lower() != "ok":
        raise ValueError(f"SQLite integrity check failed: {integrity}")
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_db": str(source),
        "backup_file": str(backup_file),
        "sha256": checksum,
        "size_bytes": backup_file.stat().st_size,
        "sqlite_integrity_check": integrity,
    }
    manifest_file = backup_file.with_suffix(f"{backup_file.suffix}.manifest.json")
    manifest_file.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest["manifest_file"] = str(manifest_file)
    return manifest


def restore_sqlite(
    backup_file: str | Path,
    target_db: str | Path,
    *,
    dry_run: bool = False,
    force: bool = False,
) -> Dict[str, Any]:
    backup = Path(backup_file).resolve()
    target = Path(target_db).resolve()
    if not backup.exists():
        raise FileNotFoundError(f"Backup file not found: {backup}")
    if backup == target:
        raise ValueError("Backup and target database must be different files.")
    _assert_no_sqlite_sidecars(backup)

    manifest_file = backup.with_suffix(f"{backup.suffix}.manifest.json")
    manifest = None
    validated_checksum = sha256_file(backup)
    if manifest_file.exists():
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        expected = manifest.get("sha256")
        if expected and expected != validated_checksum:
            raise ValueError("Backup checksum mismatch.")

    integrity = sqlite_integrity_check(backup)
    if integrity.lower() != "ok":
        raise ValueError(f"SQLite integrity check failed: {integrity}")

    result = {
        "backup_file": str(backup),
        "target_db": str(target),
        "dry_run": dry_run,
        "restored": False,
        "integrity": integrity,
        "manifest": manifest,
    }
    if dry_run:
        return result
    if target.exists() and not force:
        raise FileExistsError("Target database exists. Pass force=True to replace it.")

    target.parent.mkdir(parents=True, exist_ok=True)
    stage = target.with_name(f".{target.name}.restore_{uuid.uuid4().hex}.tmp")
    try:
        # Staging is newly owned and writable even when the source is read-only.
        shutil.copyfile(backup, stage)
        if sha256_file(stage) != validated_checksum or sqlite_integrity_check(stage).lower() != "ok":
            raise ValueError("Staged database validation failed.")
        with stage.open("r+b") as file:
            file.flush()
            os.fsync(file.fileno())
        previous_file = ""
        _assert_no_sqlite_sidecars(target)
        if target.exists():
            if not force:
                raise FileExistsError("Target database exists. Pass force=True to replace it.")
            with _exclusive_database_handle(target) as original:
                _assert_no_sqlite_sidecars(target)
                previous = target.with_name(f"{target.name}.pre_restore_{_now_slug()}_{uuid.uuid4().hex[:12]}")
                with previous.open("xb") as previous_output:
                    shutil.copyfileobj(original, previous_output)
                    previous_output.flush()
                    os.fsync(previous_output.fileno())
                previous_file = str(previous)
                _replace_protected_database(stage, target)
        else:
            # Atomic creation without overwriting a target created concurrently.
            os.link(stage, target)
    finally:
        stage.unlink(missing_ok=True)
    result["restored"] = True
    result["previous_file"] = previous_file
    return result


def _assert_no_sqlite_sidecars(target: Path) -> None:
    if any(Path(f"{target}{suffix}").exists() for suffix in ("-wal", "-shm", "-journal")):
        raise RuntimeError("SQLite WAL/SHM/journal files exist. Stop writers and checkpoint/close SQLite before restore; sidecars are never removed automatically.")


def _replace_protected_database(stage: Path, target: Path) -> None:
    """Rename with Windows POSIX semantics while the old inode remains guarded.

    MoveFileEx (os.replace) attempts another open of the guarded target and fails
    its sharing check. FileRenameInfoEx replaces the name without releasing the
    no-read/write protection; unsupported Windows/filesystems fail safely.
    """
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    rename = kernel32.SetFileInformationByHandle
    rename.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    rename.restype = wintypes.BOOL
    target_name = str(target)
    name_bytes = target_name.encode("utf-16-le")
    class RenameInfo(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("RootDirectory", wintypes.HANDLE), ("FileNameLength", wintypes.DWORD), ("FileName", wintypes.WCHAR * (len(name_bytes) // 2 + 1))]
    info = RenameInfo(0x1 | 0x2, None, len(name_bytes), target_name)
    handle = create_file(str(stage), 0x10000, 0x7, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not rename(handle, 22, ctypes.byref(info), ctypes.sizeof(info)):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        close_handle(handle)


@contextmanager
def _exclusive_database_handle(target: Path):
    """Windows denies existing/new SQLite read/write handles until replacement.

    POSIX rename cannot prevent an idle connection from writing its old inode.
    On those systems restore to a new path and switch only after stopping the app.
    """
    if os.name != "nt":
        raise RuntimeError("Existing database replacement requires Windows exclusive sharing protection. Restore to a new path, stop the application, then switch its database path.")
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    # FILE_SHARE_DELETE permits this process's atomic replacement but denies all
    # read/write opens, including a currently idle SQLite connection.
    handle = create_file(str(target), 0x80000000, 0x4, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise PermissionError("Database is open or cannot be exclusively protected. Stop the application and close SQLite before restore.")
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        close_handle(handle)
        raise
    with os.fdopen(descriptor, "rb") as file:
        yield file


def _copy_storage(source: Path, destination: Path) -> str:
    if source.is_symlink():
        raise ValueError("Storage bundle inputs must not be symbolic links.")
    if source.is_dir():
        for item in source.rglob("*"):
            if item.is_symlink():
                raise ValueError("Storage bundle inputs must not contain symbolic links.")
        shutil.copytree(source, destination)
        return "directory"
    if not source.is_file():
        raise FileNotFoundError("Storage bundle input is missing.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return "file"


def backup_storage_bundle(
    source_db: str | Path,
    app_storage: str | Path,
    bundle_dir: str | Path,
    *,
    extra_paths: Dict[str, str | Path] | None = None,
) -> Dict[str, Any]:
    """SQLite online backup plus all storage files; stop writers for one checkpoint.

    Online SQLite backup is transactional only for SQLite. JSON/vault/archive
    files are independent snapshots and cannot claim cross-store consistency.
    """
    storage = Path(app_storage).absolute()
    destination_root = Path(bundle_dir).resolve()
    if set(extra_paths or {}) & {"database", "app-storage"}:
        raise ValueError("Extra storage names cannot replace the database or app-storage component.")
    inputs = {"app-storage": storage, **{name: Path(value).absolute() for name, value in (extra_paths or {}).items()}}
    for name, source in inputs.items():
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
            raise ValueError("Extra storage names must use letters, digits, hyphens or underscores.")
        if source.is_dir() and (destination_root == source.resolve() or source.resolve() in destination_root.parents):
            raise ValueError("Bundle output must stay outside all source storage trees.")
    if not storage.is_dir():
        raise FileNotFoundError("App storage directory is missing.")
    destination_root.mkdir(parents=True, exist_ok=True)
    destination = Path(tempfile.mkdtemp(prefix=f"storage_{_now_slug()}_", dir=destination_root))
    database = backup_sqlite(source_db, destination / "database")
    _copy_storage(storage, destination / "app-storage")
    extras: Dict[str, Any] = {}
    for name, source in inputs.items():
        if name == "app-storage":
            continue
        relative = f"extras/{name}"
        extras[name] = {"path": relative, "kind": _copy_storage(source, destination / relative)}
    files = [
        {"path": file.relative_to(destination).as_posix(), "size_bytes": file.stat().st_size, "sha256": sha256_file(file)}
        for file in sorted(destination.rglob("*")) if file.is_file()
    ]
    manifest = {
        "schema": "tianyuan-storage-bundle-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "database": Path(database["backup_file"]).relative_to(destination).as_posix(),
        "app_storage": "app-storage",
        "extras": extras,
        "consistency": "independent_snapshots",
        "requires_stopped_writers_for_consistent_checkpoint": True,
        "files": files,
    }
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    verify_storage_bundle(destination)
    return {"bundle_dir": str(destination), "file_count": len(files), "consistency": manifest["consistency"], "requires_stopped_writers_for_consistent_checkpoint": True}


def _bundle_path(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or "\\" in relative:
        raise ValueError("Invalid bundle path.")
    parts = PurePosixPath(relative)
    if parts.is_absolute() or not parts.parts or any(part in {"..", "."} or ":" in part for part in parts.parts):
        raise ValueError("Bundle paths must be relative and remain inside the bundle.")
    path = root.joinpath(*parts.parts)
    if any(parent.is_symlink() for parent in (path, *path.parents) if parent == root or root in parent.parents):
        raise ValueError("Bundle paths must not contain symbolic links.")
    if root not in path.resolve().parents:
        raise ValueError("Bundle path escapes the bundle.")
    return path


def verify_storage_bundle(bundle_dir: str | Path) -> Dict[str, Any]:
    """Read-only checksum/integrity validation; never opens SQLite writable."""
    root = Path(bundle_dir).resolve()
    manifest_path = root / "manifest.json"
    if manifest_path.is_symlink():
        raise ValueError("Bundle manifest must not be a symbolic link.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema") != "tianyuan-storage-bundle-v1" or not isinstance(manifest.get("files"), list) or not isinstance(manifest.get("extras", {}), dict):
        raise ValueError("Unsupported or invalid storage bundle manifest.")
    declared = set()
    for item in manifest["files"]:
        if not isinstance(item, dict):
            raise ValueError("Invalid storage bundle file entry.")
        relative = item.get("path")
        file = _bundle_path(root, relative)
        if relative in declared or not file.is_file() or file.stat().st_size != item.get("size_bytes") or sha256_file(file) != item.get("sha256"):
            raise ValueError("Storage bundle file size/hash mismatch or duplicate entry.")
        declared.add(relative)
    actual = {file.relative_to(root).as_posix() for file in root.rglob("*") if file.is_file() and file != manifest_path}
    if actual != declared:
        raise ValueError("Storage bundle contains missing or unlisted files.")
    database = _bundle_path(root, manifest["database"])
    if sqlite_integrity_check(database).lower() != "ok":
        raise ValueError("Storage bundle SQLite integrity check failed.")
    if not _bundle_path(root, manifest["app_storage"]).is_dir():
        raise ValueError("Storage bundle app storage directory is missing.")
    for name, item in manifest.get("extras", {}).items():
        if name in {"database", "app-storage"} or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name) or not isinstance(item, dict) or item.get("kind") not in {"directory", "file"}:
            raise ValueError("Invalid extra storage entry.")
        path = _bundle_path(root, item["path"])
        if (item["kind"] == "directory" and not path.is_dir()) or (item["kind"] == "file" and not path.is_file()):
            raise ValueError("Extra storage input is missing.")
    return {"valid": True, "bundle_dir": str(root), "file_count": len(declared), "manifest": manifest}


def restore_storage_bundle(
    bundle_dir: str | Path,
    target_db: str | Path,
    target_app_storage: str | Path,
    *,
    extra_targets: Dict[str, str | Path] | None = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Publish into fresh destinations only, then switch a stopped application.

    Multiple filesystem roots cannot be atomically replaced as one transaction.
    Staging validates the whole checkpoint before publication; partial failures
    move already-published outputs back to retained diagnostic staging paths.
    """
    verified = verify_storage_bundle(bundle_dir)
    root = Path(verified["bundle_dir"])
    manifest = verified["manifest"]
    if set(extra_targets or {}) != set(manifest.get("extras", {})):
        raise ValueError("Specify a target for every extra storage component in the bundle.")
    targets = {"database": Path(target_db).resolve(), "app-storage": Path(target_app_storage).resolve(), **{name: Path(value).resolve() for name, value in (extra_targets or {}).items()}}
    for name, target in targets.items():
        if target.exists():
            raise FileExistsError("Bundle restore never overwrites existing destinations; restore into new paths and switch a stopped application.")
        if root == target or root in target.parents or any(other != name and (target == value or target in value.parents or value in target.parents) for other, value in targets.items()):
            raise ValueError("Restore targets must be separate and outside the bundle.")
    result = {"bundle_dir": str(root), "target_db": str(targets["database"]), "target_app_storage": str(targets["app-storage"]), "dry_run": dry_run, "restored": False}
    if dry_run:
        return result
    stages: Dict[str, Path] = {}
    published = []
    try:
        for name, target in targets.items():
            target.parent.mkdir(parents=True, exist_ok=True)
            stage = target.with_name(f".{target.name}.bundle_restore_{uuid.uuid4().hex}.tmp")
            stages[name] = stage
            if name == "database":
                restore_sqlite(_bundle_path(root, manifest["database"]), stage)
                expected = next(item for item in manifest["files"] if item["path"] == manifest["database"])
                if stage.stat().st_size != expected["size_bytes"] or sha256_file(stage) != expected["sha256"]:
                    raise ValueError("Staged storage bundle database validation failed.")
            else:
                relative = manifest["app_storage"] if name == "app-storage" else manifest["extras"][name]["path"]
                _copy_storage(_bundle_path(root, relative), stage)
                expected_files = {
                    item["path"] for item in manifest["files"]
                    if item["path"] == relative or item["path"].startswith(f"{relative}/")
                }
                actual_files = (
                    {f"{relative}/{file.relative_to(stage).as_posix()}" for file in stage.rglob("*") if file.is_file()}
                    if stage.is_dir() else {relative}
                )
                if actual_files != expected_files:
                    raise ValueError("Staged storage bundle contains missing or unlisted files.")
                for item in manifest["files"]:
                    if item["path"] == relative or item["path"].startswith(f"{relative}/"):
                        suffix = item["path"][len(relative):].lstrip("/")
                        staged_file = stage / suffix if suffix else stage
                        if sha256_file(staged_file) != item["sha256"]:
                            raise ValueError("Staged storage bundle validation failed.")
        for name in [key for key in targets if key != "database"] + ["database"]:
            target = targets[name]
            if target.exists():
                raise FileExistsError("A restore destination was created concurrently.")
            directory = stages[name].is_dir()
            if directory:
                os.rename(stages[name], target)
            else:
                os.link(stages[name], target)
            published.append(name)
            if not directory:
                stages[name].unlink()
    except BaseException:
        for name in reversed(published):
            if stages[name].exists() and targets[name].samefile(stages[name]):
                targets[name].unlink()  # Keep the diagnostic staging hardlink.
            else:
                os.replace(targets[name], stages[name])
        raise
    result["restored"] = True
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="SQLite and complete storage bundle backup/restore. Stop application writers for a cross-store checkpoint; bundle restore only publishes to new paths.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    backup_parser = subparsers.add_parser("backup")
    backup_parser.add_argument("--source-db", required=True)
    backup_parser.add_argument("--backup-dir", required=True)
    backup_parser.add_argument("--label", default="")

    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("--backup-file", required=True)
    restore_parser.add_argument("--target-db", required=True)
    restore_parser.add_argument("--dry-run", action="store_true")
    restore_parser.add_argument("--force", action="store_true")

    bundle_backup = subparsers.add_parser("bundle-backup")
    bundle_backup.add_argument("--source-db", required=True)
    bundle_backup.add_argument("--app-storage", required=True)
    bundle_backup.add_argument("--bundle-dir", required=True)
    bundle_backup.add_argument("--extra", action="append", default=[], metavar="NAME=PATH")
    bundle_verify = subparsers.add_parser("bundle-verify")
    bundle_verify.add_argument("--bundle-dir", required=True)
    bundle_restore = subparsers.add_parser("bundle-restore")
    bundle_restore.add_argument("--bundle-dir", required=True)
    bundle_restore.add_argument("--target-db", required=True)
    bundle_restore.add_argument("--target-app-storage", required=True)
    bundle_restore.add_argument("--extra-target", action="append", default=[], metavar="NAME=PATH")
    bundle_restore.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()
    if args.command == "backup":
        payload = backup_sqlite(args.source_db, args.backup_dir, label=args.label)
    elif args.command == "restore":
        payload = restore_sqlite(args.backup_file, args.target_db, dry_run=args.dry_run, force=args.force)
    elif args.command == "bundle-backup":
        payload = backup_storage_bundle(args.source_db, args.app_storage, args.bundle_dir, extra_paths=_named_paths(args.extra))
    elif args.command == "bundle-verify":
        payload = verify_storage_bundle(args.bundle_dir)
    else:
        payload = restore_storage_bundle(args.bundle_dir, args.target_db, args.target_app_storage, extra_targets=_named_paths(args.extra_target), dry_run=args.dry_run)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _named_paths(items: list[str]) -> Dict[str, str]:
    paths = {}
    for item in items:
        name, separator, value = item.partition("=")
        if not separator or not value or name in paths or name in {"database", "app-storage"}:
            raise ValueError("Extra paths require unique NAME=PATH pairs, excluding database/app-storage.")
        paths[name] = value
    return paths


if __name__ == "__main__":
    main()
