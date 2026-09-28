from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
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
    with sqlite3.connect(str(path)) as conn:
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
    backup_file = destination_dir / f"{source.stem}_{_now_slug()}{suffix}.sqlite"

    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as src, sqlite3.connect(str(backup_file)) as dst:
        src.backup(dst)

    checksum = sha256_file(backup_file)
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_db": str(source),
        "backup_file": str(backup_file),
        "sha256": checksum,
        "size_bytes": backup_file.stat().st_size,
        "sqlite_integrity_check": sqlite_integrity_check(backup_file),
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

    manifest_file = backup.with_suffix(f"{backup.suffix}.manifest.json")
    manifest = None
    if manifest_file.exists():
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        expected = manifest.get("sha256")
        actual = sha256_file(backup)
        if expected and expected != actual:
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
    previous_file = ""
    if target.exists():
        previous = target.with_name(f"{target.name}.pre_restore_{_now_slug()}")
        shutil.copy2(target, previous)
        previous_file = str(previous)
    shutil.copy2(backup, target)
    result["restored"] = True
    result["previous_file"] = previous_file
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="SQLite backup and restore helper.")
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

    args = parser.parse_args()
    if args.command == "backup":
        payload = backup_sqlite(args.source_db, args.backup_dir, label=args.label)
    else:
        payload = restore_sqlite(args.backup_file, args.target_db, dry_run=args.dry_run, force=args.force)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
