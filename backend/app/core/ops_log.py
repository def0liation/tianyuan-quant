from __future__ import annotations

import json
import os
import re
import threading
import uuid
from hashlib import sha256
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .cold_archive import (
    StorageCorruptionError, append_batch, archive_dir, empty_manifest, hot_limit,
    load_records, quarantine_file,
)
from .file_utils import file_state_lock, write_json_atomic, write_text_atomic


DEFAULT_MAX_EVENTS = 1000
MAX_RETENTION_DAYS = 3650
EXPORT_SCHEMA_VERSION = "ops_log_export_v1"
QUERY_SCHEMA_VERSION = "ops_log_query_v1"
EXPORT_HANDOFF_SCHEMA_VERSION = "ops_log_export_handoff_v1"
EXPORT_HANDOFF_MANIFEST_SCHEMA_VERSION = "ops_log_export_handoff_manifest_v1"
EXPORT_SHIPPER_STATUS_SCHEMA_VERSION = "ops_log_export_shipper_status_v1"
EXPORT_SHIPPER_STATUS_FILE = "shipper_status.json"
SECRET_PATTERN = re.compile(r"(api[_-]?key|token|secret|authorization)=([^,\s]+)", re.IGNORECASE)
ALLOWED_LEVELS = {"debug", "info", "warning", "error", "critical"}
ALLOWED_SHIPPER_STATUSES = {"DELIVERED", "PENDING", "FAILED", "UNKNOWN"}


def _now_iso() -> str:
    return _now_dt().isoformat()


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _default_log_file() -> Path:
    return Path(__file__).resolve().parents[1] / "storage" / "ops_events.jsonl"


def _export_handoff_dir() -> Path | None:
    configured = os.getenv("OPS_LOG_EXPORT_HANDOFF_DIR", "").strip()
    return Path(configured).expanduser() if configured else None


def _export_checksum(events: list[dict[str, Any]]) -> str:
    encoded = json.dumps(events, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{sha256(encoded).hexdigest()}"


def _safe_text(value: Any, limit: int = 320) -> str:
    text = "" if value is None else str(value).strip()
    text = SECRET_PATTERN.sub(r"\1=[REDACTED]", text)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _safe_level(value: Any) -> str:
    text = _safe_text(value, 24).lower()
    return text if text in ALLOWED_LEVELS else "info"


def _safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = _safe_text(value, 16).lower()
    return text in {"1", "true", "yes", "y", "ready", "enabled"}


def _filter_level(value: Any) -> str:
    text = _safe_text(value, 24).lower()
    return text if text in ALLOWED_LEVELS else ""


def _safe_dict(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    output: dict[str, Any] = {}
    for key, raw in list(value.items())[:30]:
        safe_key = _safe_text(key, 80)
        if isinstance(raw, dict):
            output[safe_key] = _safe_dict(raw)
        elif isinstance(raw, list):
            output[safe_key] = [_safe_text(item, 160) for item in raw[:30]]
        elif isinstance(raw, (int, float, bool)) or raw is None:
            output[safe_key] = raw
        else:
            output[safe_key] = _safe_text(raw, 160)
    return output


def _parse_timestamp(value: Any) -> datetime | None:
    text = _safe_text(value, 80)
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class OpsEventLog:
    """Local structured operations event log.

    This is a best-effort JSONL sink for request and ops events. It never raises
    to callers, and it intentionally avoids headers, bodies, and query strings.
    """

    def __init__(self, max_events: int = DEFAULT_MAX_EVENTS) -> None:
        self._max_events = max(100, hot_limit("OPS_LOG_MAX_EVENTS", int(max_events or DEFAULT_MAX_EVENTS)))
        self._lock = threading.RLock()
        self._invalid_lines: list[int] = []
        self._loaded_bytes = b""

    def log_file(self) -> Path:
        configured = os.getenv("OPS_LOG_FILE", "").strip()
        return Path(configured).expanduser() if configured else _default_log_file()

    def retention_days(self) -> int | None:
        raw_value = (
            os.getenv("OPS_LOG_RETENTION_DAYS", "").strip()
            or os.getenv("TIANYUAN_OPS_LOG_RETENTION_DAYS", "").strip()
        )
        if not raw_value:
            return None
        try:
            value = int(raw_value)
        except ValueError:
            return None
        if value <= 0:
            return None
        return min(value, MAX_RETENTION_DAYS)

    def record_event(self, event: dict[str, Any]) -> dict[str, Any] | None:
        try:
            return self._record_event(event)
        except Exception:
            return None

    def record_request(
        self,
        *,
        request_id: str,
        method: str,
        path: str,
        status_code: int,
        duration_ms: float,
        client: str = "",
        error: str = "",
    ) -> dict[str, Any] | None:
        level = "error" if status_code >= 500 else ("warning" if status_code >= 400 else "info")
        return self.record_event(
            {
                "event_type": "http_request",
                "level": level,
                "source": "api",
                "request_id": request_id,
                "method": method,
                "path": path,
                "status_code": status_code,
                "duration_ms": round(float(duration_ms), 3),
                "client": client,
                "message": error or f"{method} {path} -> {status_code}",
            }
        )

    def status(self, *, limit: int = 20, level: str = "") -> dict[str, Any]:
        events = self._read_events()
        normalized_level = _filter_level(level) if level else ""
        filtered = [
            event for event in events
            if not normalized_level or str(event.get("level") or "").lower() == normalized_level
        ]
        latest = filtered[-max(0, min(limit, 100)) :] if limit else []
        by_level: dict[str, int] = {}
        by_type: dict[str, int] = {}
        for event in events:
            level_name = _safe_level(event.get("level"))
            event_type = _safe_text(event.get("event_type"), 80) or "event"
            by_level[level_name] = by_level.get(level_name, 0) + 1
            by_type[event_type] = by_type.get(event_type, 0) + 1
        return {
            "generated_at": _now_iso(),
            "enabled": True,
            "channel": "local_file_jsonl",
            "external_delivery_enabled": False,
            "external_aggregation_ready": True,
            "query_endpoint": "/api/ops/logs/query",
            "query_schema": QUERY_SCHEMA_VERSION,
            "export_endpoint": "/api/ops/logs/export",
            "export_schema": EXPORT_SCHEMA_VERSION,
            "log_file": str(self.log_file()),
            "event_count": len(events),
            "counts_by_level": by_level,
            "counts_by_type": by_type,
            "retention_policy": self.retention_policy(),
            "storage_integrity": self.storage_integrity(),
            "redaction_policy": self.redaction_policy(),
            "handoff_status": self.handoff_status(),
            "latest": list(reversed(latest)),
        }

    def query_events(
        self,
        *,
        limit: int = 20,
        level: str = "",
        event_type: str = "",
        source: str = "",
        text: str = "",
        since: str = "",
    ) -> dict[str, Any]:
        events = self._read_history_events()
        normalized_level = _filter_level(level) if level else ""
        event_type_filter = _safe_text(event_type, 80).lower()
        source_filter = _safe_text(source, 80).lower()
        text_filter = _safe_text(text, 160).lower()
        since_dt = _parse_timestamp(since)
        try:
            query_limit = max(0, min(int(limit), 200))
        except (TypeError, ValueError):
            query_limit = 20

        filtered: list[dict[str, Any]] = []
        for event in events:
            if normalized_level and str(event.get("level") or "").lower() != normalized_level:
                continue
            if event_type_filter and str(event.get("event_type") or "").lower() != event_type_filter:
                continue
            if source_filter and str(event.get("source") or "").lower() != source_filter:
                continue
            if since_dt is not None:
                event_time = _parse_timestamp(event.get("created_at"))
                if event_time is None or event_time < since_dt:
                    continue
            if text_filter and text_filter not in self._event_search_text(event):
                continue
            filtered.append(event)

        returned = filtered[-query_limit:] if query_limit else []
        return {
            "generated_at": _now_iso(),
            "schema": QUERY_SCHEMA_VERSION,
            "channel": "local_file_jsonl_query",
            "source_channel": "local_file_jsonl",
            "external_delivery_enabled": False,
            "external_aggregation_ready": True,
            "log_file": str(self.log_file()),
            "event_count": len(events),
            "matched_count": len(filtered),
            "returned_count": len(returned),
            "limit": query_limit,
            "level_filter": normalized_level,
            "event_type_filter": event_type_filter,
            "source_filter": source_filter,
            "text_filter": text_filter,
            "since": since if since_dt is not None else "",
            "retention_policy": self.retention_policy(),
            "storage_integrity": self.storage_integrity(),
            "redaction_policy": self.redaction_policy(),
            "events": list(reversed(returned)),
        }

    def handoff_status(self) -> dict[str, Any]:
        handoff_dir = _export_handoff_dir()
        if handoff_dir is None:
            inventory = self._handoff_inventory_status(None)
            return {
                "schema": "ops_log_export_handoff_status_v1",
                "configured": False,
                "status": "NOT_CONFIGURED",
                "reason": "OPS_LOG_EXPORT_HANDOFF_DIR is not configured.",
                "handoff_destination": "NOT_CONFIGURED",
                "handoff_dir": "",
                "bundle_schema": EXPORT_SCHEMA_VERSION,
                "manifest_schema": EXPORT_HANDOFF_MANIFEST_SCHEMA_VERSION,
                "requires_sanitized_export": True,
                "writable": False,
                "will_create_on_handoff": False,
                "inventory": inventory,
                "shipper_status": self._handoff_shipper_status(None, inventory),
            }

        dir_exists = handoff_dir.exists()
        probe_path = handoff_dir if dir_exists else handoff_dir.parent
        probe_exists = probe_path.exists()
        writable = bool(probe_exists and os.access(probe_path, os.W_OK))
        status = "READY" if dir_exists and writable else "PENDING_CREATE" if writable else "UNWRITABLE"
        reason = "" if writable else f"handoff path or parent is not writable: {probe_path}"
        inventory = self._handoff_inventory_status(handoff_dir)
        return {
            "schema": "ops_log_export_handoff_status_v1",
            "configured": True,
            "status": status,
            "reason": reason,
            "handoff_destination": "LOCAL_DEPLOYMENT_HANDOFF_DIR",
            "handoff_dir": str(handoff_dir),
            "bundle_schema": EXPORT_SCHEMA_VERSION,
            "manifest_schema": EXPORT_HANDOFF_MANIFEST_SCHEMA_VERSION,
            "requires_sanitized_export": True,
            "writable": writable,
            "will_create_on_handoff": not dir_exists and writable,
            "inventory": inventory,
            "shipper_status": self._handoff_shipper_status(handoff_dir, inventory),
        }

    def _handoff_inventory_status(self, handoff_dir: Path | None) -> dict[str, Any]:
        base = {
            "schema": "ops_log_export_handoff_inventory_v1",
            "checked": False,
            "status": "NOT_CONFIGURED",
            "manifest_count": 0,
            "verified_count": 0,
            "missing_bundle_count": 0,
            "checksum_mismatch_count": 0,
            "invalid_manifest_count": 0,
            "latest_handoff_id": "",
            "latest_handed_off_at": "",
            "latest_bundle_checksum": "",
            "issues": [],
        }
        if handoff_dir is None:
            return base
        if not handoff_dir.exists():
            return {**base, "checked": True, "status": "EMPTY"}
        manifest_paths = sorted(
            handoff_dir.glob("*.manifest.json"),
            key=lambda item: item.stat().st_mtime if item.exists() else 0,
            reverse=True,
        )[:50]
        issues: list[str] = []
        verified_count = 0
        missing_bundle_count = 0
        checksum_mismatch_count = 0
        invalid_manifest_count = 0
        latest_handoff_id = ""
        latest_handed_off_at = ""
        latest_bundle_checksum = ""
        for manifest_path in manifest_paths:
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                invalid_manifest_count += 1
                issues.append(f"invalid_manifest:{manifest_path.name}")
                continue
            if not isinstance(manifest, dict) or manifest.get("schema") != EXPORT_HANDOFF_MANIFEST_SCHEMA_VERSION:
                invalid_manifest_count += 1
                issues.append(f"unexpected_manifest_schema:{manifest_path.name}")
                continue
            if not latest_handoff_id:
                latest_handoff_id = _safe_text(manifest.get("handoff_id"), 160)
                latest_handed_off_at = _safe_text(manifest.get("handed_off_at"), 80)
                latest_bundle_checksum = _safe_text(manifest.get("bundle_checksum"), 160)
            bundle_file = _safe_text(manifest.get("bundle_file"), 240)
            bundle_path = handoff_dir / bundle_file if bundle_file else handoff_dir / "__missing_bundle__"
            if not bundle_path.exists():
                missing_bundle_count += 1
                issues.append(f"missing_bundle:{bundle_file or manifest_path.name}")
                continue
            try:
                bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                checksum_mismatch_count += 1
                issues.append(f"invalid_bundle:{bundle_file}")
                continue
            if not isinstance(bundle, dict) or bundle.get("schema") != EXPORT_SCHEMA_VERSION:
                checksum_mismatch_count += 1
                issues.append(f"unexpected_bundle_schema:{bundle_file}")
                continue
            events = bundle.get("events")
            expected_checksum = str(manifest.get("bundle_checksum") or "")
            bundle_checksum = str(bundle.get("checksum") or "")
            recomputed_checksum = _export_checksum(events if isinstance(events, list) else [])
            if not expected_checksum or bundle_checksum != expected_checksum or recomputed_checksum != expected_checksum:
                checksum_mismatch_count += 1
                issues.append(f"checksum_mismatch:{bundle_file}")
                continue
            verified_count += 1
        status = "VERIFIED" if manifest_paths and verified_count == len(manifest_paths) else "DEGRADED" if issues else "EMPTY"
        return {
            **base,
            "checked": True,
            "status": status,
            "manifest_count": len(manifest_paths),
            "verified_count": verified_count,
            "missing_bundle_count": missing_bundle_count,
            "checksum_mismatch_count": checksum_mismatch_count,
            "invalid_manifest_count": invalid_manifest_count,
            "latest_handoff_id": latest_handoff_id,
            "latest_handed_off_at": latest_handed_off_at,
            "latest_bundle_checksum": latest_bundle_checksum,
            "issues": issues[:10],
        }

    def _handoff_shipper_status(self, handoff_dir: Path | None, inventory: dict[str, Any]) -> dict[str, Any]:
        base = {
            "schema": EXPORT_SHIPPER_STATUS_SCHEMA_VERSION,
            "checked": False,
            "reported": False,
            "status": "NOT_CONFIGURED",
            "sidecar_file": "",
            "reported_at": "",
            "source": "",
            "provider": "",
            "remote_destination": "",
            "remote_object_key": "",
            "retention_policy_id": "",
            "retention_status": "",
            "custody_status": "",
            "kms_key_ref": "",
            "search_index": "",
            "search_index_ready": False,
            "last_handoff_id": "",
            "last_bundle_checksum": "",
            "matches_latest_inventory": False,
            "deployment_reported": False,
            "message": "",
            "issues": [],
        }
        if handoff_dir is None:
            return base

        sidecar_path = handoff_dir / EXPORT_SHIPPER_STATUS_FILE
        if not sidecar_path.exists():
            return {
                **base,
                "checked": True,
                "status": "NOT_REPORTED",
                "sidecar_file": str(sidecar_path),
            }

        issues: list[str] = []
        try:
            if sidecar_path.stat().st_size > 65536:
                return {
                    **base,
                    "checked": True,
                    "reported": True,
                    "status": "INVALID",
                    "sidecar_file": str(sidecar_path),
                    "issues": ["sidecar_too_large"],
                }
            payload = json.loads(sidecar_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return {
                **base,
                "checked": True,
                "reported": True,
                "status": "INVALID",
                "sidecar_file": str(sidecar_path),
                "issues": ["invalid_sidecar_json"],
            }
        if not isinstance(payload, dict) or payload.get("schema") != EXPORT_SHIPPER_STATUS_SCHEMA_VERSION:
            return {
                **base,
                "checked": True,
                "reported": True,
                "status": "INVALID",
                "sidecar_file": str(sidecar_path),
                "issues": ["unexpected_sidecar_schema"],
            }

        raw_status = _safe_text(payload.get("status"), 32).upper() or "UNKNOWN"
        status = raw_status if raw_status in ALLOWED_SHIPPER_STATUSES else "UNKNOWN"
        if status != raw_status:
            issues.append(f"unexpected_status:{raw_status}")

        last_handoff_id = _safe_text(payload.get("last_handoff_id"), 160)
        last_bundle_checksum = _safe_text(payload.get("last_bundle_checksum"), 160)
        latest_handoff_id = _safe_text(inventory.get("latest_handoff_id"), 160)
        latest_bundle_checksum = _safe_text(inventory.get("latest_bundle_checksum"), 160)
        matches_latest = False
        if latest_handoff_id and last_handoff_id == latest_handoff_id:
            matches_latest = not (
                last_bundle_checksum
                and latest_bundle_checksum
                and last_bundle_checksum != latest_bundle_checksum
            )
            if not matches_latest:
                issues.append("bundle_checksum_mismatch_with_latest_inventory")
        elif latest_handoff_id:
            issues.append("handoff_id_mismatch_with_latest_inventory")
        else:
            issues.append("no_verified_handoff_inventory")

        return {
            **base,
            "checked": True,
            "reported": True,
            "status": status,
            "sidecar_file": str(sidecar_path),
            "reported_at": _safe_text(payload.get("reported_at"), 80),
            "source": _safe_text(payload.get("source"), 120) or "deployment_shipper",
            "provider": _safe_text(payload.get("provider"), 120),
            "remote_destination": _safe_text(payload.get("remote_destination"), 240),
            "remote_object_key": _safe_text(payload.get("remote_object_key"), 240),
            "retention_policy_id": _safe_text(payload.get("retention_policy_id"), 120),
            "retention_status": _safe_text(payload.get("retention_status"), 80),
            "custody_status": _safe_text(payload.get("custody_status"), 80),
            "kms_key_ref": _safe_text(payload.get("kms_key_ref"), 160),
            "search_index": _safe_text(payload.get("search_index"), 160),
            "search_index_ready": _safe_bool(payload.get("search_index_ready")),
            "last_handoff_id": last_handoff_id,
            "last_bundle_checksum": last_bundle_checksum,
            "matches_latest_inventory": matches_latest,
            "deployment_reported": True,
            "message": _safe_text(payload.get("message"), 240),
            "issues": issues[:10],
        }

    def export_bundle(self, *, limit: int = 100, level: str = "", since: str = "") -> dict[str, Any]:
        events = self._read_events()
        normalized_level = _filter_level(level) if level else ""
        since_dt = _parse_timestamp(since)
        filtered = []
        for event in events:
            if normalized_level and str(event.get("level") or "").lower() != normalized_level:
                continue
            if since_dt is not None:
                event_time = _parse_timestamp(event.get("created_at"))
                if event_time is None or event_time < since_dt:
                    continue
            filtered.append(event)
        export_limit = max(1, min(int(limit or 100), self._max_events, 1000))
        exported = filtered[-export_limit:]
        return {
            "generated_at": _now_iso(),
            "schema": EXPORT_SCHEMA_VERSION,
            "channel": "local_file_jsonl_export",
            "source_channel": "local_file_jsonl",
            "external_delivery_enabled": False,
            "external_aggregation_ready": True,
            "log_file": str(self.log_file()),
            "event_count": len(events),
            "exported_count": len(exported),
            "level_filter": normalized_level,
            "since": since if since_dt is not None else "",
            "checksum": _export_checksum(exported),
            "retention_policy": self.retention_policy(),
            "storage_integrity": self.storage_integrity(),
            "redaction_policy": self.redaction_policy(),
            "events": exported,
        }

    def handoff_export_bundle(self, *, limit: int = 100, level: str = "", since: str = "") -> dict[str, Any]:
        bundle = self.export_bundle(limit=limit, level=level, since=since)
        handoff_dir = _export_handoff_dir()
        base_payload = {
            "generated_at": _now_iso(),
            "schema": EXPORT_HANDOFF_SCHEMA_VERSION,
            "status": "DISABLED" if handoff_dir is None else "PENDING",
            "handoff_destination": "LOCAL_DEPLOYMENT_HANDOFF_DIR" if handoff_dir else "NOT_CONFIGURED",
            "handoff_requires_export_checksum": True,
            "export_schema": EXPORT_SCHEMA_VERSION,
            "bundle_checksum": bundle.get("checksum"),
            "event_count": bundle.get("event_count", 0),
            "exported_count": bundle.get("exported_count", 0),
            "level_filter": bundle.get("level_filter", ""),
            "since": bundle.get("since", ""),
            "external_delivery_enabled": False,
            "external_aggregation_ready": True,
        }
        if handoff_dir is None:
            return {
                **base_payload,
                "reason": "OPS_LOG_EXPORT_HANDOFF_DIR is not configured.",
                "handoff_id": "",
                "handoff_dir": "",
                "bundle_file": "",
                "manifest_file": "",
                "manifest": {},
            }

        handed_off_at = _now_iso()
        checksum = str(bundle.get("checksum") or "sha256:unknown")
        checksum_slug = re.sub(r"[^A-Za-z0-9_-]+", "-", checksum).strip("-") or "unknown"
        timestamp_slug = re.sub(r"[^0-9A-Za-z]+", "", handed_off_at)[:20] or "now"
        handoff_id = f"ops-log-handoff-{timestamp_slug}-{checksum_slug[-16:]}"
        bundle_file = f"{handoff_id}.json"
        manifest_file = f"{handoff_id}.manifest.json"
        manifest = {
            "schema": EXPORT_HANDOFF_MANIFEST_SCHEMA_VERSION,
            "handoff_id": handoff_id,
            "status": "HANDED_OFF",
            "handed_off_at": handed_off_at,
            "handoff_destination": "LOCAL_DEPLOYMENT_HANDOFF_DIR",
            "bundle_file": bundle_file,
            "manifest_file": manifest_file,
            "bundle_checksum": bundle.get("checksum"),
            "export_schema": bundle.get("schema"),
            "event_count": bundle.get("event_count", 0),
            "exported_count": bundle.get("exported_count", 0),
            "level_filter": bundle.get("level_filter", ""),
            "since": bundle.get("since", ""),
            "retention_policy": {
                "policy_id": "ops_log_deployment_handoff_v1",
                "custody": "deployment_owned_after_handoff",
                "requires_sanitized_export": True,
                "source_channel": bundle.get("source_channel"),
            },
            "redaction_policy": bundle.get("redaction_policy", {}),
            "external_delivery_enabled": False,
            "external_aggregation_ready": True,
        }
        try:
            handoff_dir.mkdir(parents=True, exist_ok=True)
            self._write_json_atomic(handoff_dir / bundle_file, bundle)
            self._write_json_atomic(handoff_dir / manifest_file, manifest)
        except Exception as exc:
            return {
                **base_payload,
                "status": "FAILED",
                "reason": f"handoff_write_failed: {exc}",
                "handoff_id": handoff_id,
                "handoff_dir": str(handoff_dir),
                "bundle_file": bundle_file,
                "manifest_file": manifest_file,
                "manifest": manifest,
            }
        return {
            **base_payload,
            "status": "HANDED_OFF",
            "reason": "",
            "handoff_id": handoff_id,
            "handoff_dir": str(handoff_dir),
            "bundle_file": bundle_file,
            "manifest_file": manifest_file,
            "manifest": manifest,
        }

    def retention_policy(self) -> dict[str, Any]:
        retention_days = self.retention_days()
        time_based_enabled = retention_days is not None
        return {
            "mode": "local_bounded_event_count_and_age" if time_based_enabled else "local_bounded_event_count",
            "max_events": self._max_events,
            "time_based_retention_enabled": time_based_enabled,
            "max_age_days": retention_days,
            "prune_on_read_or_write": time_based_enabled,
            "archive_on_read_or_write": True,
            "archive_dir": str(archive_dir(self.log_file(), "OPS_LOG_ARCHIVE_DIR")),
            "preserve_all_history": True,
            "deletion_enabled": False,
            "hot_low_watermark": max(1, self._max_events * 3 // 4),
            "history_query_includes_archive": True,
        }

    def _archive_manifest_file(self) -> Path:
        path = self.log_file()
        return path.with_name(f"{path.name}.archive-manifest.json")

    def _load_archive_manifest_unlocked(self) -> dict[str, Any]:
        path = self._archive_manifest_file()
        if not path.exists():
            return empty_manifest()
        try:
            manifest = json.loads(path.read_bytes())
            if not isinstance(manifest, dict) or manifest.get("schema") != "local_cold_archive_manifest_v1":
                raise ValueError("Invalid operations archive manifest")
            if not isinstance(manifest.get("batches"), list):
                raise ValueError("Invalid operations archive batches")
            if not isinstance(manifest.get("pending_records", {}), dict):
                raise ValueError("Invalid operations pending cold records")
            return manifest
        except (ValueError, UnicodeError) as exc:
            quarantine_file(path)
            raise StorageCorruptionError("Operations archive manifest is damaged; writes are disabled.") from exc

    def _recover_archive_transaction_unlocked(self) -> dict[str, Any]:
        manifest = self._load_archive_manifest_unlocked()
        pending = manifest.get("pending")
        if pending is None:
            return manifest
        if not isinstance(pending, dict) or not isinstance(pending.get("retained_text"), str):
            raise StorageCorruptionError("Operations archive transaction is damaged; writes are disabled.")
        path = self.log_file()
        current = path.read_bytes() if path.exists() else b""
        checksum = sha256(current).hexdigest()
        retained_text = pending["retained_text"]
        if sha256(retained_text.encode("utf-8")).hexdigest() != pending.get("retained_sha256"):
            raise StorageCorruptionError("Operations archive transaction checksum mismatch.")
        if checksum == pending.get("source_sha256"):
            write_text_atomic(path, retained_text)
        elif checksum != pending.get("retained_sha256"):
            raise StorageCorruptionError("Operations log changed during archive recovery; writes are disabled.")
        committed = {key: value for key, value in manifest.items() if key != "pending"}
        write_json_atomic(self._archive_manifest_file(), committed)
        return committed

    def storage_integrity(self) -> dict[str, Any]:
        with self._lock, file_state_lock(self.log_file()):
            manifest = self._load_archive_manifest_unlocked()
            sources = manifest.get("invalid_sources", [])
            invalid_count = sum(int(item.get("invalid_line_count") or 0) for item in sources)
            return {
                "status": "RECOVERY_PENDING" if manifest.get("pending") else "RECOVERED_WITH_ERRORS" if invalid_count else "OK",
                "invalid_line_count": invalid_count,
                "damaged_source_count": len(sources),
                "evidence_files": [item["file"] for item in sources],
                "archived_event_count": sum(int(item.get("record_count") or 0) for item in manifest["batches"]) + len(manifest.get("pending_records", {})),
                "deletion_enabled": False,
            }

    def redaction_policy(self) -> dict[str, Any]:
        return {
            "headers_logged": False,
            "query_strings_logged": False,
            "bodies_logged": False,
            "secret_patterns": ["api_key", "token", "secret", "authorization"],
        }

    def clear(self) -> None:
        with self._lock, file_state_lock(self.log_file()):
            path = self.log_file()
            if path.exists():
                path.unlink()

    def _record_event(self, event: dict[str, Any]) -> dict[str, Any]:
        item = {
            "id": _safe_text(event.get("id"), 96) or f"ops_evt_{_now_dt().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}",
            "created_at": _safe_text(event.get("created_at"), 80) or _now_iso(),
            "event_type": _safe_text(event.get("event_type"), 80) or "event",
            "level": _safe_level(event.get("level")),
            "source": _safe_text(event.get("source"), 80) or "system",
            "request_id": _safe_text(event.get("request_id"), 96),
            "method": _safe_text(event.get("method"), 16),
            "path": _safe_text(event.get("path"), 180),
            "status_code": int(event.get("status_code") or 0),
            "duration_ms": float(event.get("duration_ms") or 0.0),
            "client": _safe_text(event.get("client"), 120),
            "message": _safe_text(event.get("message"), 360),
            "context": _safe_dict(event.get("context")),
        }
        with self._lock, file_state_lock(self.log_file()):
            path = self.log_file()
            path.parent.mkdir(parents=True, exist_ok=True)
            self._recover_archive_transaction_unlocked()
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
            self._trim_unlocked()
        return item

    def _read_events(self) -> list[dict[str, Any]]:
        with self._lock, file_state_lock(self.log_file()):
            self._trim_unlocked()
            return self._read_events_unlocked()

    def _read_events_unlocked(self) -> list[dict[str, Any]]:
        return self._load_events_unlocked()

    def _read_history_events(self) -> list[dict[str, Any]]:
        with self._lock, file_state_lock(self.log_file()):
            self._trim_unlocked()
            manifest = self._load_archive_manifest_unlocked()
            cold = load_records(archive_dir(self.log_file(), "OPS_LOG_ARCHIVE_DIR"), manifest)
            return [*cold.values(), *self._read_events_unlocked()]

    def _load_events_unlocked(self) -> list[dict[str, Any]]:
        path = self.log_file()
        self._invalid_lines = []
        self._loaded_bytes = b""
        if not path.exists():
            return []
        events: list[dict[str, Any]] = []
        self._loaded_bytes = path.read_bytes()
        for number, line in enumerate(self._loaded_bytes.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
                if not isinstance(parsed, dict):
                    raise ValueError("Operations event must be an object")
            except (ValueError, UnicodeError):
                self._invalid_lines.append(number)
                continue
            events.append(parsed)
        return events

    def _retained_events_unlocked(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        retention_days = self.retention_days()
        if retention_days is not None:
            cutoff = _now_dt() - timedelta(days=retention_days)
            events = [
                event for event in events
                if self._event_is_within_retention(event, cutoff=cutoff)
            ]
        if len(events) > self._max_events:
            return events[-max(1, self._max_events * 3 // 4):]
        return events

    def _event_is_within_retention(self, event: dict[str, Any], *, cutoff: datetime) -> bool:
        event_time = _parse_timestamp(event.get("created_at"))
        if event_time is None:
            return True
        return event_time >= cutoff

    def _trim_unlocked(self) -> None:
        manifest = self._recover_archive_transaction_unlocked()
        path = self.log_file()
        if not path.exists():
            return
        events = self._load_events_unlocked()
        retained = self._retained_events_unlocked(events)
        if retained == events and not self._invalid_lines:
            return
        retained_ids = {id(event) for event in retained}
        moved = [event for event in events if id(event) not in retained_ids]
        new_manifest = append_batch(
            archive_dir(path, "OPS_LOG_ARCHIVE_DIR"), manifest,
            {f"{len(manifest['batches']):08d}:{len(manifest.get('pending_records', {})) + index:012d}": event for index, event in enumerate(moved)},
        )
        if self._invalid_lines:
            evidence = {**quarantine_file(path, self._loaded_bytes), "invalid_line_count": len(self._invalid_lines), "line_numbers": self._invalid_lines}
            sources = list(manifest.get("invalid_sources", []))
            if not any(item.get("sha256") == evidence["sha256"] for item in sources):
                sources.append(evidence)
            new_manifest["invalid_sources"] = sources
        retained_text = "".join(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n" for event in retained)
        pending = {
            "source_sha256": sha256(self._loaded_bytes).hexdigest(),
            "retained_sha256": sha256(retained_text.encode("utf-8")).hexdigest(),
            "retained_text": retained_text,
        }
        # Publish recoverable intent before replacing the hot file. Either old
        # bytes or all archived records remain available at every failure point.
        write_json_atomic(self._archive_manifest_file(), {**new_manifest, "pending": pending})
        write_text_atomic(path, retained_text)
        write_json_atomic(self._archive_manifest_file(), new_manifest)

    def _event_search_text(self, event: dict[str, Any]) -> str:
        fields = [
            event.get("id"),
            event.get("created_at"),
            event.get("event_type"),
            event.get("level"),
            event.get("source"),
            event.get("request_id"),
            event.get("method"),
            event.get("path"),
            event.get("status_code"),
            event.get("message"),
            event.get("context"),
        ]
        return json.dumps(fields, ensure_ascii=False, sort_keys=True, default=str).lower()

    def _write_json_atomic(self, path: Path, payload: dict[str, Any]) -> None:
        write_json_atomic(path, payload)


ops_event_log = OpsEventLog()
