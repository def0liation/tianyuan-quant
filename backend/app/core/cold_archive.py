"""Small immutable batch archive for local JSON stores; it never deletes history.

The hot state's manifest is the commit point. A failed hot write can leave an
unreferenced batch, but cannot publish a partially written state or erase history.
The manifest keeps at most 249 staged cold records; small overflows become a
batch at 250 records, rather than creating one file per event or review update.
"""

from __future__ import annotations

import json
import os
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable

from .file_utils import write_bytes_atomic


MIN_ARCHIVE_BATCH_RECORDS = 250


class StorageCorruptionError(OSError):
    """A persisted store cannot safely be treated as an empty store."""


def hot_limit(env_name: str, default: int = 1000) -> int:
    try:
        return max(1, int(os.getenv(env_name, str(default))))
    except ValueError:
        return default


def archive_dir(owner: Path, env_name: str) -> Path:
    configured = os.getenv(env_name, "").strip()
    return Path(configured).expanduser() if configured else owner.with_name(f"{owner.stem}.archive")


def empty_manifest() -> dict[str, Any]:
    return {"schema": "local_cold_archive_manifest_v1", "batches": [], "pending_records": {}, "deletion_enabled": False}


def _manifest(value: Any) -> dict[str, Any]:
    if value is None:
        return empty_manifest()
    if not isinstance(value, dict) or value.get("schema") != "local_cold_archive_manifest_v1":
        raise StorageCorruptionError("Invalid cold archive manifest; storage is read-only.")
    if not isinstance(value.get("batches"), list):
        raise StorageCorruptionError("Invalid cold archive batches; storage is read-only.")
    pending = value.get("pending_records", {})
    if not isinstance(pending, dict) or any(not isinstance(item, dict) for item in pending.values()):
        raise StorageCorruptionError("Invalid pending cold records; storage is read-only.")
    return {**value, "batches": list(value["batches"]), "pending_records": dict(pending), "deletion_enabled": False}


def load_records(directory: Path, manifest: Any) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    normalized = _manifest(manifest)
    for batch in normalized["batches"]:
        if not isinstance(batch, dict):
            raise StorageCorruptionError("Invalid cold archive batch descriptor.")
        name = batch.get("file")
        if not isinstance(name, str) or Path(name).name != name or not name.endswith(".json"):
            raise StorageCorruptionError("Invalid cold archive file name.")
        path = directory / name
        try:
            raw = path.read_bytes()
            if sha256(raw).hexdigest() != batch.get("sha256"):
                raise StorageCorruptionError("Cold archive checksum mismatch; storage is read-only.")
            payload = json.loads(raw)
        except (OSError, ValueError) as exc:
            raise StorageCorruptionError("Cold archive cannot be loaded; storage is read-only.") from exc
        data = payload.get("records") if isinstance(payload, dict) else None
        if (
            not isinstance(payload, dict)
            or payload.get("schema") != "local_cold_archive_batch_v1"
            or not isinstance(data, dict)
            or len(data) != batch.get("record_count")
            or any(not isinstance(item, dict) for item in data.values())
        ):
            raise StorageCorruptionError("Invalid cold archive records; storage is read-only.")
        records.update(data)
    records.update(normalized["pending_records"])
    return records


def append_batch(
    directory: Path, manifest: Any, records: dict[str, dict[str, Any]], *, force_flush: bool = False,
) -> dict[str, Any]:
    output = _manifest(manifest)
    if not records:
        return output
    buffered = {**output["pending_records"], **records}
    if len(buffered) < MIN_ARCHIVE_BATCH_RECORDS and not force_flush:
        output["pending_records"] = buffered
        return output
    payload = {"schema": "local_cold_archive_batch_v1", "records": buffered}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    checksum = sha256(raw).hexdigest()
    name = f"batch-{len(output['batches']):08d}-{checksum}.json"
    path = directory / name
    if not path.exists():
        write_bytes_atomic(path, raw)
    elif path.read_bytes() != raw:
        raise StorageCorruptionError("Existing archive batch differs from its checksum.")
    output["batches"].append({"file": name, "sha256": checksum, "record_count": len(buffered)})
    output["pending_records"] = {}
    return output


def split_hot_records(
    records: dict[str, dict[str, Any]],
    cold_records: dict[str, dict[str, Any]],
    *,
    max_hot: int,
    keep_hot: Callable[[dict[str, Any]], bool],
    sort_key: Callable[[dict[str, Any]], Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Move excess records in batches to a 75% low watermark, preserving pins.

    Unchanged cold records stay cold. A reviewed cold item becomes a hot overlay,
    so updates never rewrite every historical batch or mutate business status.
    """
    candidates = {key: value for key, value in records.items() if keep_hot(value) or cold_records.get(key) != value}
    if len(candidates) <= max_hot:
        return candidates, {}
    pinned = {key: value for key, value in candidates.items() if keep_hot(value)}
    target = max(len(pinned), max(1, max_hot * 3 // 4))
    eligible = sorted(((key, value) for key, value in candidates.items() if key not in pinned), key=lambda pair: sort_key(pair[1]), reverse=True)
    hot = {**pinned, **dict(eligible[:max(0, target - len(pinned))])}
    archived = {key: value for key, value in candidates.items() if key not in hot}
    return hot, archived


def quarantine_file(path: Path, raw: bytes | None = None) -> dict[str, Any]:
    """Keep exact damaged bytes privately; never return their contents to callers."""
    original = path.read_bytes() if raw is None else raw
    digest = sha256(original).hexdigest()
    evidence = path.with_name(f"{path.name}.corrupt.{digest}")
    if not evidence.exists():
        write_bytes_atomic(evidence, original)
    elif evidence.read_bytes() != original:
        raise StorageCorruptionError("Corruption evidence checksum mismatch.")
    return {"file": str(evidence), "sha256": digest, "byte_count": len(original)}
