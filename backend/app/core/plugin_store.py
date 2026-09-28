import hashlib
import io
import json
import os
import re
import uuid
import zipfile
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, select

from .plugin_sandbox import run_declarative_plugin_sandbox
from .plugin_runtime import DEFAULT_FORBIDDEN_TRADE_ACTIONS, validate_plugin_manifest
from ..db.models import PluginAuditDB, PluginRegistryDB
from ..db.session import AsyncSessionLocal


PLUGIN_ROOT = Path(__file__).resolve().parents[1] / "plugins"
MAX_PLUGIN_ARTIFACT_BYTES = 2 * 1024 * 1024
MAX_PLUGIN_ARTIFACT_ARCHIVE_ENTRIES = 200
MAX_PLUGIN_ARTIFACT_UNCOMPRESSED_BYTES = 10 * 1024 * 1024
DEFAULT_PLUGIN_ARTIFACT_RETENTION_DAYS = 180
MAX_PLUGIN_ARTIFACT_RETENTION_DAYS = 3650
SECRET_TEXT_PATTERN = re.compile(
    r"(authorization|bearer|token|api[_-]?key|secret|password|credential)",
    re.IGNORECASE,
)
REDACTED_AUDIT_VALUE = "[redacted]"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _audit_id(plugin_id: str, action: str) -> str:
    return f"AUD_PLUGIN_{action}_{plugin_id}_{uuid.uuid4().hex[:6]}"


def _lifecycle_from_manifest(manifest: Any) -> Dict[str, Any]:
    if not isinstance(manifest, dict):
        return {"status": "ACTIVE"}
    lifecycle = manifest.get("lifecycle")
    if isinstance(lifecycle, dict):
        status = str(lifecycle.get("status") or "ACTIVE").upper()
        return {**lifecycle, "status": status}
    if manifest.get("archived") is True:
        return {
            "status": "ARCHIVED",
            "archived_at": str(manifest.get("archived_at") or ""),
            "archived_by": str(manifest.get("archived_by") or ""),
            "archive_reason": str(manifest.get("archive_reason") or ""),
        }
    return {"status": "ACTIVE"}


def _is_archived_manifest(manifest: Any) -> bool:
    return _lifecycle_from_manifest(manifest).get("status") == "ARCHIVED"


def _version_key(version: Any) -> tuple[int, ...] | None:
    parts: List[int] = []
    for segment in str(version or "").split("."):
        digits = ""
        for character in segment:
            if character.isdigit():
                digits += character
            else:
                break
        if not digits:
            return None
        parts.append(int(digits))
    return tuple(parts) if parts else None


def _is_version_downgrade(next_version: Any, current_version: Any) -> bool:
    next_key = _version_key(next_version)
    current_key = _version_key(current_version)
    if not next_key or not current_key:
        return False
    width = max(len(next_key), len(current_key))
    return next_key + (0,) * (width - len(next_key)) < current_key + (0,) * (width - len(current_key))


def _artifact_storage_root() -> Path:
    raw = os.getenv("TIANYUAN_PLUGIN_ARTIFACT_DIR", "").strip()
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[1] / "storage" / "plugin_artifacts"


def _safe_artifact_segment(value: Any, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip()).strip("._-")
    return (cleaned[:96] or fallback).strip("._-") or fallback


def _normalize_expected_sha256(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    digest = raw.split(":", 1)[1] if raw.startswith("sha256:") else raw
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Expected plugin artifact checksum must be a sha256 hex digest.")
    return f"sha256:{digest}"


def _blocked_artifact_sha256_digests() -> set[str]:
    raw = " ".join(
        value
        for value in (
            os.getenv("TIANYUAN_PLUGIN_ARTIFACT_BLOCKED_SHA256", "").strip(),
            os.getenv("PLUGIN_ARTIFACT_BLOCKED_SHA256", "").strip(),
        )
        if value
    )
    digests: set[str] = set()
    for token in re.split(r"[\s,;]+", raw):
        if not token:
            continue
        digest = token.lower().split(":", 1)[1] if token.lower().startswith("sha256:") else token.lower()
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Blocked plugin artifact checksum denylist must contain sha256 hex digests.")
        digests.add(digest)
    return digests


def _known_bad_hash_scan(checksum: str) -> Dict[str, Any]:
    digest = checksum.split(":", 1)[1] if checksum.startswith("sha256:") else checksum
    blocked_digests = _blocked_artifact_sha256_digests()
    scan = {
        "status": "PASSED",
        "scanner": "local_sha256_denylist",
        "scanned_at": _now(),
        "blocked": False,
        "blocked_digest_count": len(blocked_digests),
        "summary": "Local known-bad sha256 denylist check passed.",
    }
    if digest in blocked_digests:
        scan.update(
            {
                "status": "BLOCKED",
                "blocked": True,
                "summary": "Plugin artifact sha256 is blocked by the local denylist.",
            }
        )
        raise ValueError("Plugin artifact sha256 is blocked by the local denylist.")
    return scan


def _truthy_env(*names: str) -> bool:
    for name in names:
        raw = os.getenv(name, "").strip().lower()
        if raw in {"1", "true", "yes", "on", "required"}:
            return True
    return False


def _artifact_external_scan_dir() -> Path | None:
    raw = (
        os.getenv("TIANYUAN_PLUGIN_ARTIFACT_EXTERNAL_SCAN_DIR", "").strip()
        or os.getenv("PLUGIN_ARTIFACT_EXTERNAL_SCAN_DIR", "").strip()
    )
    return Path(raw) if raw else None


def _normalize_external_scan_status(value: Any) -> str:
    status = str(value or "").strip().upper().replace("-", "_")
    aliases = {
        "ALLOW": "PASSED",
        "ALLOWED": "PASSED",
        "CLEAN": "PASSED",
        "OK": "PASSED",
        "PASS": "PASSED",
        "PASSED": "PASSED",
        "WARNING": "WARN",
        "WARN": "WARN",
        "SUSPICIOUS": "WARN",
        "DENY": "BLOCKED",
        "DENIED": "BLOCKED",
        "MALICIOUS": "BLOCKED",
        "MALWARE": "BLOCKED",
        "BLOCK": "BLOCKED",
        "BLOCKED": "BLOCKED",
        "FAIL": "FAILED",
        "FAILED": "FAILED",
        "ERROR": "ERROR",
    }
    return aliases.get(status, status or "UNKNOWN")


def _external_artifact_scan(checksum: str, filename: str, size_bytes: int) -> Dict[str, Any]:
    digest = checksum.split(":", 1)[1] if checksum.startswith("sha256:") else checksum
    required = _truthy_env(
        "TIANYUAN_PLUGIN_ARTIFACT_EXTERNAL_SCAN_REQUIRED",
        "PLUGIN_ARTIFACT_EXTERNAL_SCAN_REQUIRED",
    )
    scan: Dict[str, Any] = {
        "status": "NOT_CONFIGURED",
        "scanner": "external_scan_sidecar",
        "source": "sidecar",
        "configured": False,
        "required": required,
        "scanned_at": _now(),
        "checksum": f"sha256:{digest}",
        "filename": filename,
        "size_bytes": size_bytes,
        "summary": "External malware scan verdict sidecar is not configured.",
        "warnings": [],
        "threats": [],
    }

    scan_dir = _artifact_external_scan_dir()
    if scan_dir is None:
        if required:
            raise ValueError("Plugin artifact external malware scan is required but no scan directory is configured.")
        return scan

    scan["configured"] = True
    root = scan_dir.resolve(strict=False)
    if not root.exists() or not root.is_dir():
        scan.update(
            {
                "status": "UNAVAILABLE",
                "summary": "External malware scan verdict directory is not available.",
            }
        )
        if required:
            raise ValueError("Plugin artifact external malware scan is required but the scan directory is unavailable.")
        return scan

    verdict_path = None
    for name in (f"{digest}.json", f"sha256_{digest}.json", f"sha256-{digest}.json"):
        candidate = (root / name).resolve(strict=False)
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        if candidate.is_file():
            verdict_path = candidate
            break

    if verdict_path is None:
        scan.update(
            {
                "status": "MISSING",
                "summary": "External malware scan verdict was not found for this artifact checksum.",
            }
        )
        if required:
            raise ValueError("Plugin artifact external malware scan verdict is required before upload.")
        return scan

    if verdict_path.stat().st_size > 64 * 1024:
        raise ValueError("Plugin artifact external malware scan verdict is too large.")
    try:
        verdict = json.loads(verdict_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Plugin artifact external malware scan verdict is invalid JSON.") from exc
    if not isinstance(verdict, dict):
        raise ValueError("Plugin artifact external malware scan verdict must be a JSON object.")

    declared_checksum = _normalize_sidecar_checksum(
        verdict.get("checksum") or verdict.get("artifact_checksum") or verdict.get("sha256")
    )
    if declared_checksum and declared_checksum != checksum:
        raise ValueError("Plugin artifact external malware scan checksum mismatch.")

    status = _normalize_external_scan_status(verdict.get("status") or verdict.get("verdict"))
    scanner = _safe_sidecar_text(verdict.get("scanner") or verdict.get("provider"), default="external_scan_sidecar", max_length=96)
    threats = _safe_sidecar_list(verdict.get("threats"), max_items=20, max_length=160)
    warnings = _safe_sidecar_list(verdict.get("warnings"), max_items=20, max_length=200)
    blocked = bool(verdict.get("blocked") or verdict.get("malicious")) or status in {"BLOCKED", "FAILED", "ERROR"}
    scan.update(
        {
            "schema": _safe_sidecar_text(verdict.get("schema"), max_length=80),
            "status": status,
            "scanner": scanner,
            "provider": scanner,
            "verdict_file": verdict_path.name,
            "scanned_at": _safe_sidecar_text(verdict.get("scanned_at"), default=scan["scanned_at"], max_length=80),
            "signature_version": _safe_sidecar_text(verdict.get("signature_version"), max_length=120),
            "engine_version": _safe_sidecar_text(verdict.get("engine_version"), max_length=120),
            "definitions_updated_at": _safe_sidecar_text(verdict.get("definitions_updated_at"), max_length=80),
            "provider_status": _safe_sidecar_text(verdict.get("provider_status"), max_length=80),
            "threat_intel_status": _safe_sidecar_text(verdict.get("threat_intel_status"), max_length=80),
            "scan_id": _safe_sidecar_text(verdict.get("scan_id") or verdict.get("vendor_scan_id"), max_length=160),
            "artifact_checksum": declared_checksum or checksum,
            "matches_artifact_checksum": True,
            "summary": _safe_sidecar_text(verdict.get("summary"), default=f"External malware scan returned {status}.", max_length=500),
            "blocked": blocked,
            "warnings": warnings,
            "threats": threats,
        }
    )
    if blocked:
        raise ValueError("Plugin artifact external malware scan blocked the upload.")
    if status not in {"PASSED", "WARN"}:
        raise ValueError("Plugin artifact external malware scan verdict must be PASSED or WARN.")
    return scan


def _artifact_retention_days() -> int:
    raw = (
        os.getenv("TIANYUAN_PLUGIN_ARTIFACT_RETENTION_DAYS", "").strip()
        or os.getenv("PLUGIN_ARTIFACT_RETENTION_DAYS", "").strip()
    )
    if not raw:
        return DEFAULT_PLUGIN_ARTIFACT_RETENTION_DAYS
    try:
        parsed = int(raw)
    except ValueError:
        return DEFAULT_PLUGIN_ARTIFACT_RETENTION_DAYS
    return min(max(parsed, 1), MAX_PLUGIN_ARTIFACT_RETENTION_DAYS)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_sidecar_text(value: Any, *, default: str = "", max_length: int = 160) -> str:
    text = str(value if value is not None else default).replace("\r", " ").replace("\n", " ").strip()
    if not text:
        return default
    if SECRET_TEXT_PATTERN.search(text):
        return "[redacted]"
    return text[:max_length]


def _safe_sidecar_list(value: Any, *, max_items: int = 20, max_length: int = 200) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        text
        for text in (
            _safe_sidecar_text(item, max_length=max_length)
            for item in value[:max_items]
        )
        if text
    ]


def _normalize_sidecar_checksum(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    digest = raw.split(":", 1)[1] if raw.startswith("sha256:") else raw
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        return ""
    return f"sha256:{digest}"


def _redact_sensitive_payload(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: Dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            redacted[key_text] = (
                REDACTED_AUDIT_VALUE
                if SECRET_TEXT_PATTERN.search(key_text)
                else _redact_sensitive_payload(item)
            )
        return redacted
    if isinstance(value, list):
        return [_redact_sensitive_payload(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_sensitive_payload(item) for item in value]
    if isinstance(value, str):
        return REDACTED_AUDIT_VALUE if SECRET_TEXT_PATTERN.search(value) else value
    return value


def _artifact_retention_policy(uploaded_at: str) -> Dict[str, Any]:
    days = _artifact_retention_days()
    uploaded_dt = datetime.fromisoformat(uploaded_at)
    expires_at = (uploaded_dt + timedelta(days=days)).isoformat()
    return {
        "status": "RETENTION_SCHEDULED",
        "retention_days": days,
        "expires_at": expires_at,
        "policy": f"retain uploaded plugin artifact for {days} day(s)",
        "cleanup_automatic": False,
    }


def _validate_upload_filename(value: Any) -> str:
    raw = str(value or "plugin-package.bin").strip() or "plugin-package.bin"
    normalized = raw.replace("\\", "/")
    posix = PurePosixPath(normalized)
    windows = PureWindowsPath(raw)
    if "\x00" in raw:
        raise ValueError("Plugin artifact filename contains an unsafe control character.")
    if raw in {".", ".."} or "/" in normalized or posix.is_absolute() or windows.drive or windows.is_absolute():
        raise ValueError("Plugin artifact filename must be a single safe file name.")
    if any(part in {"", ".", ".."} for part in posix.parts):
        raise ValueError("Plugin artifact filename must be a single safe file name.")
    return raw


def _validate_archive_entry_name(value: Any) -> str:
    raw = str(value or "")
    normalized = raw.replace("\\", "/").strip()
    posix = PurePosixPath(normalized)
    windows = PureWindowsPath(raw)
    if not normalized:
        raise ValueError("Plugin artifact archive contains an empty entry name.")
    if "\x00" in raw:
        raise ValueError("Plugin artifact archive contains an unsafe control character.")
    if posix.is_absolute() or windows.drive or windows.is_absolute():
        raise ValueError(f"Plugin artifact archive entry is not relative: {raw}")
    if any(part in {"", ".", ".."} for part in posix.parts):
        raise ValueError(f"Plugin artifact archive entry is unsafe: {raw}")
    return normalized


def _scan_plugin_artifact(filename: str, content_type: str, content: bytes) -> Dict[str, Any]:
    lower_filename = filename.lower()
    lower_content_type = content_type.lower()
    looks_like_zip = lower_filename.endswith(".zip") or "zip" in lower_content_type
    content_is_zip = zipfile.is_zipfile(io.BytesIO(content))
    scan: Dict[str, Any] = {
        "status": "PASSED",
        "scanner": "metadata_only_zip_path_guard",
        "scanned_at": _now(),
        "archive_format": "zip" if content_is_zip else "none",
        "archive_entry_count": 0,
        "archive_total_uncompressed_bytes": 0,
        "warnings": [],
        "blocked_reasons": [],
        "summary": "Metadata scan completed; no archive extraction or code execution was performed.",
    }
    if not content_is_zip:
        if looks_like_zip:
            raise ValueError("Plugin artifact zip scan failed: invalid zip archive.")
        return scan

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
    except zipfile.BadZipFile as exc:
        raise ValueError("Plugin artifact zip scan failed: invalid zip archive.") from exc

    if len(entries) > MAX_PLUGIN_ARTIFACT_ARCHIVE_ENTRIES:
        raise ValueError(
            f"Plugin artifact archive exceeds {MAX_PLUGIN_ARTIFACT_ARCHIVE_ENTRIES} metadata entries."
        )

    total_uncompressed = 0
    code_like_entries = 0
    manifest_entries = 0
    for entry in entries:
        name = _validate_archive_entry_name(entry.filename)
        if name.endswith("/"):
            continue
        entry_size = max(0, int(entry.file_size or 0))
        total_uncompressed += entry_size
        if total_uncompressed > MAX_PLUGIN_ARTIFACT_UNCOMPRESSED_BYTES:
            raise ValueError(
                f"Plugin artifact archive expands beyond {MAX_PLUGIN_ARTIFACT_UNCOMPRESSED_BYTES} bytes."
            )
        lower_name = name.lower()
        if lower_name.endswith(("manifest.json", "plugin.json", "plugin.yml", "plugin.yaml")):
            manifest_entries += 1
        if lower_name.endswith((".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".exe", ".dll", ".ps1", ".sh", ".bat", ".cmd")):
            code_like_entries += 1

    scan["archive_entry_count"] = len(entries)
    scan["archive_total_uncompressed_bytes"] = total_uncompressed
    scan["manifest_entry_count"] = manifest_entries
    scan["code_like_entry_count"] = code_like_entries
    if manifest_entries == 0:
        scan["warnings"].append("No plugin manifest file was visible in archive metadata.")
    if code_like_entries:
        scan["warnings"].append(
            "Archive contains code-like files; artifact is stored for review only and plugin code execution remains disabled."
        )
    if scan["warnings"]:
        scan["status"] = "WARN"
    return scan


def _package_artifact_from_upgrade(data: Dict[str, Any], plugin_id: str, version: str) -> Dict[str, Any]:
    raw = data.get("package_artifact") if isinstance(data.get("package_artifact"), dict) else {}
    checksum = str(raw.get("checksum") or f"sha256:metadata-only:{plugin_id}:{version}").strip()
    if not checksum:
        raise ValueError("Plugin package artifact checksum is required.")
    if ":" not in checksum:
        checksum = f"sha256:{checksum}"
    artifact = {
        "artifact_id": str(raw.get("artifact_id") or f"{plugin_id}@{version}").strip(),
        "artifact_type": str(raw.get("artifact_type") or "manifest_only").strip(),
        "source": str(raw.get("source") or "metadata_only").strip(),
        "checksum": checksum,
        "checksum_algorithm": str(raw.get("checksum_algorithm") or checksum.split(":", 1)[0]).strip(),
        "recorded_only": bool(raw.get("recorded_only", True)),
        "notes": str(raw.get("notes") or "No executable package artifact was imported.").strip(),
    }
    for key in (
        "filename",
        "content_type",
        "size_bytes",
        "storage_path",
        "stored_at",
        "stored_by",
        "verified",
        "expected_checksum",
        "hash_scan_status",
        "hash_scan",
        "scan_status",
        "scan_summary",
        "scan_warnings",
        "scan",
        "external_scan_status",
        "external_scan_provider",
        "external_scan",
        "external_scan_required",
        "retention_days",
        "retention_expires_at",
        "retention_policy",
    ):
        if key in raw:
            artifact[key] = raw[key]
    if artifact["artifact_type"] == "uploaded_package":
        artifact["recorded_only"] = False
        if not artifact.get("storage_path") or artifact.get("verified") is not True:
            raise ValueError("Uploaded plugin package artifact must include verified storage metadata.")
        if str(artifact.get("scan_status") or "PASSED").upper() not in {"PASSED", "WARN"}:
            raise ValueError("Uploaded plugin package artifact must pass metadata scanning before upgrade.")
        if str(artifact.get("hash_scan_status") or "PASSED").upper() != "PASSED":
            raise ValueError("Uploaded plugin package artifact must pass local hash scanning before upgrade.")
        external_scan_status = str(artifact.get("external_scan_status") or "").upper()
        if external_scan_status in {"BLOCKED", "FAILED", "ERROR"}:
            raise ValueError("Uploaded plugin package artifact must not be blocked by external malware scanning.")
        if artifact.get("external_scan_required") is True and external_scan_status not in {"PASSED", "WARN"}:
            raise ValueError("Uploaded plugin package artifact requires external malware scan evidence before upgrade.")
    return artifact


def _current_uploaded_artifact(manifest: Any) -> Dict[str, Any]:
    manifest = manifest if isinstance(manifest, dict) else {}
    artifact = manifest.get("package_artifact")
    if not isinstance(artifact, dict):
        return {}
    if str(artifact.get("artifact_type") or "").strip() != "uploaded_package":
        return {}
    return artifact


def _assert_uploaded_artifact_provenance(artifact: Dict[str, Any], current_manifest: Any) -> None:
    if str(artifact.get("artifact_type") or "").strip() != "uploaded_package":
        return
    current = _current_uploaded_artifact(current_manifest)
    if not current:
        raise ValueError("Uploaded plugin package artifact must first be stored by the server before upgrade.")
    required_matches = (
        "artifact_id",
        "storage_path",
        "checksum",
        "expected_checksum",
        "stored_at",
        "retention_expires_at",
        "hash_scan_status",
        "scan_status",
        "external_scan_status",
    )
    for key in required_matches:
        if str(current.get(key) or "").strip() != str(artifact.get(key) or "").strip():
            raise ValueError(f"Uploaded plugin package artifact metadata mismatch for {key}.")
    if current.get("verified") is not True or artifact.get("verified") is not True:
        raise ValueError("Uploaded plugin package artifact must use verified server storage metadata.")
    if current.get("recorded_only") is True or artifact.get("recorded_only") is True:
        raise ValueError("Uploaded plugin package artifact cannot be metadata-only.")
    if _safe_int(current.get("retention_days")) != _safe_int(artifact.get("retention_days")):
        raise ValueError("Uploaded plugin package artifact metadata mismatch for retention_days.")


def _package_migration_steps(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw_steps = data.get("migration_steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raw_steps = [
            {
                "step_id": "manifest_contract_upgrade",
                "kind": "metadata_only",
                "description": "Record plugin manifest/package metadata for the upgraded version.",
            }
        ]
    steps: List[Dict[str, Any]] = []
    for index, raw_step in enumerate(raw_steps):
        step = raw_step if isinstance(raw_step, dict) else {}
        step_id = str(step.get("step_id") or f"migration_step_{index + 1}").strip()
        steps.append(
            {
                "step_id": step_id,
                "kind": str(step.get("kind") or "metadata_only").strip(),
                "description": str(step.get("description") or step_id).strip(),
                "status": str(step.get("status") or "RECORDED").strip().upper(),
                "requires_code_execution": bool(step.get("requires_code_execution", False)),
            }
        )
    if any(step["requires_code_execution"] for step in steps):
        raise ValueError("Plugin package migration steps cannot require code execution.")
    return steps


def _audit_payload_status(action: str, payload: Any) -> str:
    payload = payload if isinstance(payload, dict) else {}
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    status = str(result.get("status") or payload.get("status") or "").strip().upper()
    if status:
        return status
    if action in {"SANDBOX_RUN", "EXECUTE_PREVIEW"}:
        return "COMPLETED"
    if action in {"SANDBOX_BLOCK", "EXECUTE_PREVIEW_FAILED"}:
        return "BLOCKED"
    return action


def _audit_payload_elapsed_ms(payload: Any) -> float:
    payload = payload if isinstance(payload, dict) else {}
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    raw = result.get("elapsed_ms", payload.get("elapsed_ms"))
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return 0.0


def _parse_audit_time(value: Any) -> Optional[datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _artifact_expiry_time(artifact: Dict[str, Any]) -> Optional[datetime]:
    policy = artifact.get("retention_policy") if isinstance(artifact.get("retention_policy"), dict) else {}
    return _parse_audit_time(artifact.get("retention_expires_at") or policy.get("expires_at"))


def _normalize_artifact_storage_path(value: Any) -> Path:
    raw = str(value or "").strip()
    normalized = raw.replace("\\", "/")
    posix = PurePosixPath(normalized)
    windows = PureWindowsPath(raw)
    if not normalized:
        raise ValueError("Plugin artifact storage path is empty.")
    if "\x00" in raw:
        raise ValueError("Plugin artifact storage path contains an unsafe control character.")
    if posix.is_absolute() or windows.drive or windows.is_absolute():
        raise ValueError(f"Plugin artifact storage path must be relative: {raw}")
    if any(part in {"", ".", ".."} for part in posix.parts):
        raise ValueError(f"Plugin artifact storage path is unsafe: {raw}")
    return Path(*posix.parts)


def _resolve_artifact_storage_path(storage_root: Path, storage_path: Any) -> Path:
    root = storage_root.resolve(strict=False)
    relative_path = _normalize_artifact_storage_path(storage_path)
    candidate = (root / relative_path).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Plugin artifact storage path escapes artifact root: {storage_path}") from exc
    return candidate


def _artifact_key(artifact: Dict[str, Any]) -> str:
    artifact_id = str(artifact.get("artifact_id") or "").strip()
    storage_path = str(artifact.get("storage_path") or "").strip()
    return f"{artifact_id}|{storage_path}"


def _artifact_matches(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    left_id = str(left.get("artifact_id") or "").strip()
    right_id = str(right.get("artifact_id") or "").strip()
    left_path = str(left.get("storage_path") or "").strip()
    right_path = str(right.get("storage_path") or "").strip()
    if left_id and right_id and left_id == right_id:
        return True
    return bool(left_path and right_path and left_path == right_path)


def _cleanup_candidate_artifacts(manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    seen: set[str] = set()
    raw_artifacts = manifest.get("package_artifacts") if isinstance(manifest.get("package_artifacts"), list) else []
    latest_artifact = manifest.get("package_artifact") if isinstance(manifest.get("package_artifact"), dict) else None
    for artifact in [latest_artifact, *raw_artifacts]:
        if not isinstance(artifact, dict):
            continue
        if artifact.get("artifact_type") != "uploaded_package":
            continue
        if not artifact.get("storage_path"):
            continue
        if str(artifact.get("cleanup_status") or "").upper() in {"DELETED", "MISSING"}:
            continue
        key = _artifact_key(artifact)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(deepcopy(artifact))
    return candidates


def _mark_artifact_cleanup(
    manifest: Dict[str, Any],
    target: Dict[str, Any],
    *,
    cleanup_status: str,
    cleanup_at: str,
    dry_run: bool,
    cleanup_error: str = "",
) -> None:
    cleanup_fields = {
        "cleanup_status": cleanup_status,
        "cleanup_at": cleanup_at,
        "cleanup_dry_run": dry_run,
        "cleanup_error": cleanup_error,
    }
    latest = manifest.get("package_artifact")
    if isinstance(latest, dict) and _artifact_matches(latest, target):
        latest.update(cleanup_fields)
    artifacts = manifest.get("package_artifacts")
    if isinstance(artifacts, list):
        for artifact in artifacts:
            if isinstance(artifact, dict) and _artifact_matches(artifact, target):
                artifact.update(cleanup_fields)
    lifecycle = _lifecycle_from_manifest(manifest)
    latest_after_update = manifest.get("package_artifact")
    if isinstance(latest_after_update, dict) and _artifact_matches(latest_after_update, target):
        lifecycle.update(
            {
                "package_cleanup_status": cleanup_status,
                "package_cleanup_at": cleanup_at,
                "package_cleanup_dry_run": dry_run,
            }
        )
        manifest["lifecycle"] = lifecycle


def _empty_usage_stats(plugin_id: str, *, window_event_limit: int) -> Dict[str, Any]:
    return {
        "plugin_id": plugin_id,
        "window_event_limit": window_event_limit,
        "total_audit_events": 0,
        "sandbox_run_count": 0,
        "sandbox_block_count": 0,
        "execute_preview_count": 0,
        "execute_preview_failed_count": 0,
        "validation_count": 0,
        "lifecycle_event_count": 0,
        "action_counts": {},
        "status_counts": {},
        "last_action": "",
        "last_status": "",
        "last_actor": "",
        "last_audit_id": "",
        "last_run_at": "",
        "last_elapsed_ms": 0.0,
        "average_elapsed_ms": 0.0,
        "max_elapsed_ms": 0.0,
    }


def _empty_usage_history_bucket(plugin_id: str, bucket_start: str) -> Dict[str, Any]:
    return {
        "plugin_id": plugin_id,
        "bucket_start": bucket_start,
        "bucket_label": bucket_start,
        "total_audit_events": 0,
        "sandbox_run_count": 0,
        "sandbox_block_count": 0,
        "execute_preview_count": 0,
        "execute_preview_failed_count": 0,
        "validation_count": 0,
        "lifecycle_event_count": 0,
        "action_counts": {},
        "status_counts": {},
        "last_action": "",
        "last_status": "",
        "last_actor": "",
        "last_audit_id": "",
        "last_run_at": "",
        "last_elapsed_ms": 0.0,
        "average_elapsed_ms": 0.0,
        "max_elapsed_ms": 0.0,
    }


DEFAULT_READONLY_PLUGIN = {
    "plugin_id": "technical_kline_readonly",
    "version": "0.1.0",
    "name": "Technical K-line Readonly Agent",
    "description": "Readonly technical-analysis plugin example. It can only emit review observations.",
    "agents": [
        {
            "agent_id": "technical_kline_analyst",
            "name": "Technical K-line Analyst",
            "mode": "READ_ONLY",
            "input_schema": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "kline": {"type": "array"},
                    "analysis_context": {"type": "object"},
                },
                "required": ["symbol"],
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "signals": {"type": "array"},
                    "risk_notes": {"type": "array"},
                },
                "forbidden_actions": list(DEFAULT_FORBIDDEN_TRADE_ACTIONS),
            },
            "permissions": ["read:market_data", "read:analysis_context", "read:technical_indicators"],
            "risk_level": "LOW",
            "can_emit_trade_action": False,
            "manifest": {"runtime": "controlled_dag_plan_only"},
        }
    ],
    "permissions": ["read:market_data", "read:analysis_context"],
    "input_schema": {"type": "object"},
    "output_schema": {
        "type": "object",
        "forbidden_actions": list(DEFAULT_FORBIDDEN_TRADE_ACTIONS),
    },
    "risk_level": "LOW",
    "enabled": True,
    "manifest": {
        "runtime": "controlled_dag_plan_only",
        "safety": "Risk/DVG/Execution/Anti-Conclusion gates required downstream",
    },
}


class PluginStore:
    async def list_plugins(self) -> List[Dict[str, Any]]:
        await self.ensure_default_plugins()
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(PluginRegistryDB).order_by(PluginRegistryDB.plugin_id))
            return [self._plugin_to_dict(record) for record in result.scalars().all()]

    async def get_plugin(self, plugin_id: str) -> Optional[Dict[str, Any]]:
        await self.ensure_default_plugins()
        async with AsyncSessionLocal() as db:
            record = (
                await db.execute(select(PluginRegistryDB).where(PluginRegistryDB.plugin_id == plugin_id))
            ).scalar_one_or_none()
            return self._plugin_to_dict(record) if record else None

    async def register_plugin(self, data: Dict[str, Any], source: str = "api") -> Dict[str, Any]:
        failures = self.validate_manifest(data)
        if failures:
            raise ValueError("; ".join(failures))
        async with AsyncSessionLocal() as db:
            existing = (
                await db.execute(select(PluginRegistryDB).where(PluginRegistryDB.plugin_id == data["plugin_id"]))
            ).scalar_one_or_none()
            if existing:
                self._apply_plugin(existing, data, source)
                record = existing
            else:
                record = PluginRegistryDB(
                    plugin_id=data["plugin_id"],
                    created_at=_now(),
                )
                self._apply_plugin(record, data, source)
                db.add(record)
            await self._add_audit(db, data["plugin_id"], "REGISTER", "system", "Plugin manifest registered.", data)
            await db.commit()
            await db.refresh(record)
            return self._plugin_to_dict(record)

    async def set_enabled(self, plugin_id: str, enabled: bool, actor: str = "human") -> Optional[Dict[str, Any]]:
        await self.ensure_default_plugins()
        async with AsyncSessionLocal() as db:
            record = (
                await db.execute(select(PluginRegistryDB).where(PluginRegistryDB.plugin_id == plugin_id))
            ).scalar_one_or_none()
            if not record:
                return None
            if enabled and _is_archived_manifest(record.manifest):
                raise ValueError("Archived plugins cannot be enabled; register a new plugin version to reactivate.")
            if enabled:
                failures = self.validate_manifest(self._plugin_to_dict(record))
                if failures:
                    raise ValueError("; ".join(failures))
            record.enabled = enabled
            record.updated_at = _now()
            await self._add_audit(
                db,
                plugin_id,
                "ENABLE" if enabled else "DISABLE",
                actor,
                f"Plugin enabled={enabled}.",
                {"enabled": enabled},
            )
            await db.commit()
            await db.refresh(record)
            return self._plugin_to_dict(record)

    async def archive_plugin(self, plugin_id: str, *, actor: str = "human", reason: str = "") -> Optional[Dict[str, Any]]:
        await self.ensure_default_plugins()
        archived_at = _now()
        async with AsyncSessionLocal() as db:
            record = (
                await db.execute(select(PluginRegistryDB).where(PluginRegistryDB.plugin_id == plugin_id))
            ).scalar_one_or_none()
            if not record:
                return None
            manifest = deepcopy(record.manifest or {})
            lifecycle = _lifecycle_from_manifest(manifest)
            lifecycle.update(
                {
                    "status": "ARCHIVED",
                    "archived_at": archived_at,
                    "archived_by": actor,
                    "archive_reason": reason,
                }
            )
            manifest["lifecycle"] = lifecycle
            record.manifest = manifest
            record.enabled = False
            record.updated_at = archived_at
            await self._add_audit(
                db,
                plugin_id,
                "ARCHIVE",
                actor,
                "Plugin archived and disabled.",
                {
                    "enabled": False,
                    "lifecycle_status": "ARCHIVED",
                    "archived_at": archived_at,
                    "reason": reason,
                },
            )
            await db.commit()
            await db.refresh(record)
            return self._plugin_to_dict(record)

    async def upgrade_plugin(
        self,
        plugin_id: str,
        data: Dict[str, Any],
        *,
        actor: str = "human",
        reason: str = "",
    ) -> Optional[Dict[str, Any]]:
        await self.ensure_default_plugins()
        payload = deepcopy(data)
        if payload.get("plugin_id") and payload["plugin_id"] != plugin_id:
            raise ValueError("Plugin upgrade payload plugin_id must match the path plugin_id.")
        payload["plugin_id"] = plugin_id
        upgraded_at = _now()

        async with AsyncSessionLocal() as db:
            record = (
                await db.execute(select(PluginRegistryDB).where(PluginRegistryDB.plugin_id == plugin_id))
            ).scalar_one_or_none()
            if not record:
                return None

            current = self._plugin_to_dict(record)
            next_version = str(payload.get("version") or "").strip()
            if not next_version:
                raise ValueError("Plugin upgrade requires a target version.")
            if next_version == str(record.version):
                raise ValueError("Plugin upgrade requires a new version.")
            if _is_version_downgrade(next_version, record.version):
                raise ValueError("Plugin upgrade cannot downgrade the registered version.")

            failures = self.validate_manifest(payload)
            if failures:
                raise ValueError("; ".join(failures))

            manifest = deepcopy(payload.get("manifest") or {})
            package_artifact = _package_artifact_from_upgrade(payload, plugin_id, next_version)
            _assert_uploaded_artifact_provenance(package_artifact, record.manifest)
            migration_steps = _package_migration_steps(payload)
            previous_manifest = record.manifest or {}
            previous_lifecycle = _lifecycle_from_manifest(previous_manifest)
            previous_history = previous_manifest.get("upgrade_history") if isinstance(previous_manifest, dict) else []
            if not isinstance(previous_history, list):
                previous_history = []
            history_entry = {
                "from_version": record.version,
                "to_version": next_version,
                "upgraded_at": upgraded_at,
                "upgraded_by": actor,
                "reason": reason,
                "previous_source": record.source,
                "previous_enabled": bool(record.enabled),
                "previous_lifecycle_status": str(previous_lifecycle.get("status") or "ACTIVE").upper(),
                "package_artifact_id": package_artifact["artifact_id"],
                "package_checksum": package_artifact["checksum"],
                "migration_step_count": len(migration_steps),
            }
            manifest["upgrade_history"] = [*previous_history[-9:], history_entry]
            manifest["package_artifact"] = package_artifact
            manifest["package_migration"] = {
                "status": "RECORDED",
                "recorded_at": upgraded_at,
                "recorded_by": actor,
                "from_version": record.version,
                "to_version": next_version,
                "steps": migration_steps,
            }
            lifecycle = _lifecycle_from_manifest(manifest)
            lifecycle.update(
                {
                    "status": "ACTIVE",
                    "upgraded_at": upgraded_at,
                    "upgraded_by": actor,
                    "upgrade_from_version": record.version,
                    "upgrade_to_version": next_version,
                    "upgrade_reason": reason,
                    "package_artifact_id": package_artifact["artifact_id"],
                    "package_checksum": package_artifact["checksum"],
                    "package_artifact_verified": bool(
                        package_artifact.get("verified") is True and package_artifact.get("recorded_only") is not True
                    ),
                    "package_artifact_storage_path": str(package_artifact.get("storage_path") or ""),
                }
            )
            manifest["lifecycle"] = lifecycle
            payload["manifest"] = manifest

            self._apply_plugin(record, payload, "api")
            await self._add_audit(
                db,
                plugin_id,
                "UPGRADE",
                actor,
                "Plugin upgraded to a new version.",
                {
                    "from_version": current["version"],
                    "to_version": next_version,
                    "reason": reason,
                    "previous_lifecycle_status": current["lifecycle_status"],
                    "enabled": bool(payload.get("enabled", True)),
                    "package_artifact": package_artifact,
                    "migration_steps": migration_steps,
                },
            )
            await db.commit()
            await db.refresh(record)
            return self._plugin_to_dict(record)

    async def upload_package_artifact(
        self,
        plugin_id: str,
        *,
        filename: str,
        content_type: str,
        content: bytes,
        expected_checksum: str = "",
        actor: str = "human",
        reason: str = "",
    ) -> Optional[Dict[str, Any]]:
        await self.ensure_default_plugins()
        if not content:
            raise ValueError("Plugin artifact upload is empty.")
        if len(content) > MAX_PLUGIN_ARTIFACT_BYTES:
            raise ValueError(f"Plugin artifact upload exceeds {MAX_PLUGIN_ARTIFACT_BYTES} bytes.")

        display_filename = _validate_upload_filename(filename or "plugin-package.bin")
        normalized_expected = _normalize_expected_sha256(expected_checksum)
        digest = hashlib.sha256(content).hexdigest()
        checksum = f"sha256:{digest}"
        if normalized_expected and normalized_expected != checksum:
            raise ValueError("Plugin artifact checksum mismatch.")
        hash_scan = _known_bad_hash_scan(checksum)
        scan = _scan_plugin_artifact(display_filename, content_type or "application/octet-stream", content)
        external_scan = _external_artifact_scan(checksum, display_filename, len(content))

        uploaded_at = _now()
        retention_policy = _artifact_retention_policy(uploaded_at)
        safe_plugin_id = _safe_artifact_segment(plugin_id, "plugin")
        safe_version = _safe_artifact_segment("pending", "version")
        safe_filename = _safe_artifact_segment(display_filename, "plugin-package.bin")
        storage_root = _artifact_storage_root()

        async with AsyncSessionLocal() as db:
            record = (
                await db.execute(select(PluginRegistryDB).where(PluginRegistryDB.plugin_id == plugin_id))
            ).scalar_one_or_none()
            if not record:
                return None

            safe_version = _safe_artifact_segment(record.version, "version")
            artifact_id = f"{plugin_id}@{record.version}:{digest[:12]}"
            storage_dir = storage_root / safe_plugin_id
            storage_dir.mkdir(parents=True, exist_ok=True)
            storage_filename = f"{safe_version}_{digest[:16]}_{safe_filename}"
            final_path = storage_dir / storage_filename
            temp_path = storage_dir / f".upload-{uuid.uuid4().hex[:12]}.tmp"
            temp_path.write_bytes(content)
            os.replace(temp_path, final_path)
            relative_path = Path(safe_plugin_id) / storage_filename

            artifact = {
                "artifact_id": artifact_id,
                "artifact_type": "uploaded_package",
                "source": "api_upload",
                "filename": display_filename,
                "content_type": content_type or "application/octet-stream",
                "size_bytes": len(content),
                "checksum": checksum,
                "checksum_algorithm": "sha256",
                "expected_checksum": normalized_expected,
                "hash_scan_status": hash_scan["status"],
                "hash_scan": hash_scan,
                "storage_path": relative_path.as_posix(),
                "stored_at": uploaded_at,
                "stored_by": actor,
                "verified": True,
                "recorded_only": False,
                "scan_status": scan["status"],
                "scan_summary": scan["summary"],
                "scan_warnings": scan["warnings"],
                "scan": scan,
                "external_scan_status": external_scan["status"],
                "external_scan_provider": str(external_scan.get("provider") or external_scan.get("scanner") or ""),
                "external_scan_required": bool(external_scan.get("required")),
                "external_scan": external_scan,
                "retention_days": retention_policy["retention_days"],
                "retention_expires_at": retention_policy["expires_at"],
                "retention_policy": retention_policy,
                "notes": "Uploaded plugin package artifact stored for review only; no code was executed or extracted.",
            }

            manifest = deepcopy(record.manifest or {})
            existing_artifacts = manifest.get("package_artifacts") if isinstance(manifest, dict) else []
            if not isinstance(existing_artifacts, list):
                existing_artifacts = []
            manifest["package_artifact"] = artifact
            manifest["package_artifacts"] = [*existing_artifacts[-19:], artifact]
            manifest["package_storage"] = {
                "status": "STORED_VERIFIED",
                "latest_artifact_id": artifact_id,
                "latest_checksum": checksum,
                "updated_at": uploaded_at,
                "updated_by": actor,
                "scan_status": scan["status"],
                "hash_scan_status": hash_scan["status"],
                "external_scan_status": external_scan["status"],
                "external_scan_provider": str(external_scan.get("provider") or external_scan.get("scanner") or ""),
                "external_scan_required": bool(external_scan.get("required")),
                "retention_expires_at": retention_policy["expires_at"],
                "executable_imported": False,
            }
            lifecycle = _lifecycle_from_manifest(manifest)
            lifecycle.update(
                {
                    "package_artifact_id": artifact_id,
                    "package_checksum": checksum,
                    "package_artifact_verified": True,
                    "package_uploaded_at": uploaded_at,
                    "package_uploaded_by": actor,
                    "package_scan_status": scan["status"],
                    "package_hash_scan_status": hash_scan["status"],
                    "package_external_scan_status": external_scan["status"],
                    "package_external_scan_provider": str(external_scan.get("provider") or external_scan.get("scanner") or ""),
                    "package_retention_expires_at": retention_policy["expires_at"],
                    "package_retention_days": retention_policy["retention_days"],
                }
            )
            manifest["lifecycle"] = lifecycle
            record.manifest = manifest
            record.updated_at = uploaded_at
            await self._add_audit(
                db,
                plugin_id,
                "ARTIFACT_UPLOAD",
                actor,
                "Plugin package artifact uploaded and sha256 verified.",
                {
                    "artifact": artifact,
                    "reason": reason,
                    "verification": {
                        "expected_checksum": normalized_expected,
                        "computed_checksum": checksum,
                        "matched": True,
                    },
                    "hash_scan": hash_scan,
                    "scan": scan,
                    "external_scan": external_scan,
                    "retention_policy": retention_policy,
                    "executable_imported": False,
                },
            )
            await db.commit()
            await db.refresh(record)
            return {
                "plugin_id": plugin_id,
                "version": record.version,
                **artifact,
            }

    async def cleanup_expired_artifacts(
        self,
        *,
        dry_run: bool = True,
        now: Any = None,
        actor: str = "system",
        reason: str = "",
    ) -> Dict[str, Any]:
        await self.ensure_default_plugins()
        cleanup_at = _now()
        cutoff = _parse_audit_time(now) if now else _parse_audit_time(cleanup_at)
        if cutoff is None:
            cutoff = datetime.now(timezone.utc)
        storage_root = _artifact_storage_root()
        result = {
            "status": "DRY_RUN" if dry_run else "COMPLETED",
            "dry_run": dry_run,
            "cleanup_at": cleanup_at,
            "storage_root": str(storage_root),
            "scanned_plugin_count": 0,
            "expired_count": 0,
            "candidate_count": 0,
            "would_delete_count": 0,
            "deleted_count": 0,
            "missing_count": 0,
            "skipped_count": 0,
            "error_count": 0,
            "items": [],
        }

        async with AsyncSessionLocal() as db:
            records = (await db.execute(select(PluginRegistryDB).order_by(PluginRegistryDB.plugin_id))).scalars().all()
            result["scanned_plugin_count"] = len(records)
            for record in records:
                manifest = deepcopy(record.manifest or {})
                changed = False
                plugin_actions: List[Dict[str, Any]] = []
                for artifact in _cleanup_candidate_artifacts(manifest):
                    expires_at = _artifact_expiry_time(artifact)
                    if expires_at is None or expires_at > cutoff:
                        continue

                    result["expired_count"] += 1
                    item = {
                        "plugin_id": record.plugin_id,
                        "artifact_id": str(artifact.get("artifact_id") or ""),
                        "storage_path": str(artifact.get("storage_path") or ""),
                        "retention_expires_at": expires_at.isoformat(),
                        "status": "",
                        "exists": False,
                        "size_bytes": 0,
                        "error": "",
                    }

                    try:
                        artifact_path = _resolve_artifact_storage_path(storage_root, artifact.get("storage_path"))
                    except ValueError as exc:
                        item["status"] = "SKIPPED_UNSAFE_PATH"
                        item["error"] = str(exc)
                        result["skipped_count"] += 1
                        result["error_count"] += 1
                        if not dry_run:
                            _mark_artifact_cleanup(
                                manifest,
                                artifact,
                                cleanup_status=item["status"],
                                cleanup_at=cleanup_at,
                                dry_run=dry_run,
                                cleanup_error=item["error"],
                            )
                            changed = True
                        result["items"].append(item)
                        plugin_actions.append(item)
                        continue

                    item["resolved_path"] = str(artifact_path)
                    if not artifact_path.exists():
                        item["status"] = "MISSING"
                        result["missing_count"] += 1
                        if not dry_run:
                            _mark_artifact_cleanup(
                                manifest,
                                artifact,
                                cleanup_status=item["status"],
                                cleanup_at=cleanup_at,
                                dry_run=dry_run,
                            )
                            changed = True
                        result["items"].append(item)
                        plugin_actions.append(item)
                        continue
                    if not artifact_path.is_file():
                        item["status"] = "SKIPPED_NOT_FILE"
                        result["skipped_count"] += 1
                        if not dry_run:
                            _mark_artifact_cleanup(
                                manifest,
                                artifact,
                                cleanup_status=item["status"],
                                cleanup_at=cleanup_at,
                                dry_run=dry_run,
                            )
                            changed = True
                        result["items"].append(item)
                        plugin_actions.append(item)
                        continue

                    result["candidate_count"] += 1
                    item["exists"] = True
                    item["size_bytes"] = artifact_path.stat().st_size
                    if dry_run:
                        item["status"] = "WOULD_DELETE"
                        result["would_delete_count"] += 1
                    else:
                        try:
                            artifact_path.unlink()
                            item["status"] = "DELETED"
                            result["deleted_count"] += 1
                            _mark_artifact_cleanup(
                                manifest,
                                artifact,
                                cleanup_status=item["status"],
                                cleanup_at=cleanup_at,
                                dry_run=dry_run,
                            )
                            changed = True
                        except OSError as exc:
                            item["status"] = "DELETE_FAILED"
                            item["error"] = str(exc)
                            result["skipped_count"] += 1
                            result["error_count"] += 1
                            _mark_artifact_cleanup(
                                manifest,
                                artifact,
                                cleanup_status=item["status"],
                                cleanup_at=cleanup_at,
                                dry_run=dry_run,
                                cleanup_error=item["error"],
                            )
                            changed = True
                    result["items"].append(item)
                    plugin_actions.append(item)

                if changed:
                    record.manifest = manifest
                    record.updated_at = cleanup_at
                    await self._add_audit(
                        db,
                        record.plugin_id,
                        "ARTIFACT_CLEANUP",
                        actor,
                        "Expired plugin package artifact cleanup completed.",
                        {
                            "dry_run": dry_run,
                            "reason": reason,
                            "cleanup_at": cleanup_at,
                            "items": plugin_actions,
                        },
                    )
            if not dry_run:
                await db.commit()
        return result

    async def validate_plugin(self, plugin_id: str) -> Optional[Dict[str, Any]]:
        plugin = await self.get_plugin(plugin_id)
        if not plugin:
            return None
        failures = self.validate_manifest(plugin)
        warnings: List[str] = []
        for agent in plugin.get("agents", []):
            if isinstance(agent, dict) and str(agent.get("risk_level", "LOW")).upper() != "LOW":
                warnings.append(
                    f"Plugin agent {agent.get('agent_id', 'UNKNOWN')} is non-LOW risk and requires runtime gate review."
                )
        audit_id = _audit_id(plugin_id, "VALIDATE")
        async with AsyncSessionLocal() as db:
            await self._add_audit(
                db,
                plugin_id,
                "VALIDATE",
                "system",
                "Plugin manifest validation completed.",
                {
                    "valid": not failures,
                    "failures": failures,
                    "warnings": warnings,
                },
                audit_id=audit_id,
            )
            await db.commit()
        return {
            "plugin_id": plugin_id,
            "valid": not failures,
            "failures": failures,
            "warnings": warnings,
            "audit_id": audit_id,
        }

    async def run_sandbox(
        self,
        plugin_id: str,
        agent_id: str,
        input_payload: Dict[str, Any],
        actor: str = "human",
    ) -> Optional[Dict[str, Any]]:
        plugin = await self.get_plugin(plugin_id)
        if not plugin:
            return None
        result, policy = run_declarative_plugin_sandbox(plugin, agent_id, input_payload, actor=actor)
        safe_result = _redact_sensitive_payload(result)
        safe_policy = _redact_sensitive_payload(policy)
        async with AsyncSessionLocal() as db:
            await self._add_audit(
                db,
                plugin_id,
                "SANDBOX_RUN" if safe_result["status"] == "COMPLETED" else "SANDBOX_BLOCK",
                actor,
                f"Plugin sandbox run {safe_result['status']} for agent {agent_id}.",
                {
                    "result": safe_result,
                    "policy": safe_policy,
                    "input_keys": sorted(input_payload.keys()),
                },
                audit_id=safe_result["audit_id"],
            )
            await db.commit()
        return safe_result

    async def list_audit(self, plugin_id: str) -> List[Dict[str, Any]]:
        await self.ensure_default_plugins()
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(PluginAuditDB)
                .where(PluginAuditDB.plugin_id == plugin_id)
                .order_by(desc(PluginAuditDB.created_at))
                .limit(100)
            )
            return [self._audit_to_dict(record) for record in result.scalars().all()]

    async def list_usage_stats(self, limit: int = 1000) -> List[Dict[str, Any]]:
        window_event_limit = max(1, min(int(limit or 1000), 5000))
        plugins = await self.list_plugins()
        stats: Dict[str, Dict[str, Any]] = {
            plugin["plugin_id"]: _empty_usage_stats(plugin["plugin_id"], window_event_limit=window_event_limit)
            for plugin in plugins
        }
        elapsed_totals: Dict[str, float] = {}
        elapsed_counts: Dict[str, int] = {}

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(PluginAuditDB).order_by(desc(PluginAuditDB.created_at)).limit(window_event_limit)
            )
            for record in result.scalars().all():
                item = self._audit_to_dict(record)
                plugin_id = item["plugin_id"]
                usage = stats.setdefault(
                    plugin_id,
                    _empty_usage_stats(plugin_id, window_event_limit=window_event_limit),
                )
                action = item["action"]
                payload = item["payload_json"]
                status = _audit_payload_status(action, payload)
                elapsed_ms = _audit_payload_elapsed_ms(payload)

                usage["total_audit_events"] += 1
                usage["action_counts"][action] = int(usage["action_counts"].get(action, 0)) + 1
                usage["status_counts"][status] = int(usage["status_counts"].get(status, 0)) + 1
                if action == "SANDBOX_RUN":
                    usage["sandbox_run_count"] += 1
                elif action == "SANDBOX_BLOCK":
                    usage["sandbox_block_count"] += 1
                elif action == "EXECUTE_PREVIEW":
                    usage["execute_preview_count"] += 1
                elif action == "EXECUTE_PREVIEW_FAILED":
                    usage["execute_preview_failed_count"] += 1
                elif action == "VALIDATE":
                    usage["validation_count"] += 1
                elif action in {"REGISTER", "ENABLE", "DISABLE", "ARCHIVE", "MIGRATE", "UPGRADE"}:
                    usage["lifecycle_event_count"] += 1

                if not usage["last_audit_id"]:
                    usage["last_action"] = action
                    usage["last_status"] = status
                    usage["last_actor"] = item["actor"]
                    usage["last_audit_id"] = item["audit_id"]
                    usage["last_run_at"] = item["created_at"]
                    usage["last_elapsed_ms"] = round(elapsed_ms, 3)
                if elapsed_ms > 0:
                    elapsed_totals[plugin_id] = elapsed_totals.get(plugin_id, 0.0) + elapsed_ms
                    elapsed_counts[plugin_id] = elapsed_counts.get(plugin_id, 0) + 1
                    usage["max_elapsed_ms"] = round(max(float(usage["max_elapsed_ms"]), elapsed_ms), 3)

        for plugin_id, usage in stats.items():
            count = elapsed_counts.get(plugin_id, 0)
            if count:
                usage["average_elapsed_ms"] = round(elapsed_totals[plugin_id] / count, 3)
        return [stats[plugin_id] for plugin_id in sorted(stats)]

    async def list_usage_history(self, days: int = 90) -> Dict[str, Any]:
        window_days = max(1, min(int(days or 90), 365))
        generated_at = _now()
        now_dt = datetime.now(timezone.utc)
        start_date = now_dt.date() - timedelta(days=window_days - 1)
        start_datetime = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
        plugins = await self.list_plugins()
        plugin_ids = sorted({plugin["plugin_id"] for plugin in plugins})
        bucket_dates = [(start_date + timedelta(days=offset)).isoformat() for offset in range(window_days)]
        buckets: Dict[tuple[str, str], Dict[str, Any]] = {
            (plugin_id, bucket_date): _empty_usage_history_bucket(plugin_id, bucket_date)
            for plugin_id in plugin_ids
            for bucket_date in bucket_dates
        }
        elapsed_totals: Dict[tuple[str, str], float] = {}
        elapsed_counts: Dict[tuple[str, str], int] = {}

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(PluginAuditDB)
                .where(PluginAuditDB.created_at >= start_datetime.isoformat())
                .order_by(PluginAuditDB.created_at)
            )
            for record in result.scalars().all():
                created_at = _parse_audit_time(record.created_at)
                if not created_at or created_at.date() < start_date:
                    continue
                item = self._audit_to_dict(record)
                plugin_id = item["plugin_id"]
                if plugin_id not in plugin_ids:
                    plugin_ids.append(plugin_id)
                bucket_date = created_at.date().isoformat()
                key = (plugin_id, bucket_date)
                usage = buckets.setdefault(key, _empty_usage_history_bucket(plugin_id, bucket_date))
                action = item["action"]
                payload = item["payload_json"]
                status = _audit_payload_status(action, payload)
                elapsed_ms = _audit_payload_elapsed_ms(payload)

                usage["total_audit_events"] += 1
                usage["action_counts"][action] = int(usage["action_counts"].get(action, 0)) + 1
                usage["status_counts"][status] = int(usage["status_counts"].get(status, 0)) + 1
                if action == "SANDBOX_RUN":
                    usage["sandbox_run_count"] += 1
                elif action == "SANDBOX_BLOCK":
                    usage["sandbox_block_count"] += 1
                elif action == "EXECUTE_PREVIEW":
                    usage["execute_preview_count"] += 1
                elif action == "EXECUTE_PREVIEW_FAILED":
                    usage["execute_preview_failed_count"] += 1
                elif action == "VALIDATE":
                    usage["validation_count"] += 1
                elif action in {
                    "REGISTER",
                    "ENABLE",
                    "DISABLE",
                    "ARCHIVE",
                    "MIGRATE",
                    "UPGRADE",
                    "ARTIFACT_UPLOAD",
                    "ARTIFACT_CLEANUP",
                }:
                    usage["lifecycle_event_count"] += 1

                usage["last_action"] = action
                usage["last_status"] = status
                usage["last_actor"] = item["actor"]
                usage["last_audit_id"] = item["audit_id"]
                usage["last_run_at"] = item["created_at"]
                usage["last_elapsed_ms"] = round(elapsed_ms, 3)
                if elapsed_ms > 0:
                    elapsed_totals[key] = elapsed_totals.get(key, 0.0) + elapsed_ms
                    elapsed_counts[key] = elapsed_counts.get(key, 0) + 1
                    usage["max_elapsed_ms"] = round(max(float(usage["max_elapsed_ms"]), elapsed_ms), 3)

        for key, usage in buckets.items():
            count = elapsed_counts.get(key, 0)
            if count:
                usage["average_elapsed_ms"] = round(elapsed_totals[key] / count, 3)

        sorted_plugin_ids = sorted(set(plugin_ids))
        items = [
            buckets[(plugin_id, bucket_date)]
            for plugin_id in sorted_plugin_ids
            for bucket_date in bucket_dates
            if (plugin_id, bucket_date) in buckets
        ]
        return {
            "generated_at": generated_at,
            "bucket": "day",
            "days": window_days,
            "plugin_count": len(sorted_plugin_ids),
            "items": items,
        }

    async def record_audit(
        self,
        plugin_id: str,
        action: str,
        message: str,
        payload: Dict[str, Any],
        *,
        actor: str = "system",
        audit_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        resolved_audit_id = audit_id or _audit_id(plugin_id, action)
        safe_payload = _redact_sensitive_payload(payload)
        async with AsyncSessionLocal() as db:
            await self._add_audit(
                db,
                plugin_id,
                action,
                actor,
                message,
                safe_payload,
                audit_id=resolved_audit_id,
            )
            await db.commit()
        return {
            "audit_id": resolved_audit_id,
            "plugin_id": plugin_id,
            "action": action,
            "actor": actor,
            "message": message,
            "payload_json": safe_payload,
            "created_at": _now(),
        }

    async def ensure_default_plugins(self) -> None:
        async with AsyncSessionLocal() as db:
            existing = (
                await db.execute(
                    select(PluginRegistryDB).where(
                        PluginRegistryDB.plugin_id == DEFAULT_READONLY_PLUGIN["plugin_id"]
                    )
                )
            ).scalar_one_or_none()
            if not existing:
                record = PluginRegistryDB(plugin_id=DEFAULT_READONLY_PLUGIN["plugin_id"], created_at=_now())
                self._apply_plugin(record, deepcopy(DEFAULT_READONLY_PLUGIN), "builtin")
                db.add(record)
                await self._add_audit(
                    db,
                    record.plugin_id,
                    "REGISTER",
                    "system",
                    "Builtin readonly plugin seeded.",
                    DEFAULT_READONLY_PLUGIN,
                )
            else:
                current = self._plugin_to_dict(existing)
                if self.validate_manifest(current):
                    refreshed = deepcopy(DEFAULT_READONLY_PLUGIN)
                    refreshed["enabled"] = bool(existing.enabled)
                    self._apply_plugin(existing, refreshed, "builtin")
                    await self._add_audit(
                        db,
                        existing.plugin_id,
                        "MIGRATE",
                        "system",
                        "Builtin readonly plugin runtime contract refreshed.",
                        refreshed,
                    )

            for manifest in self._load_file_manifests():
                if self.validate_manifest(manifest):
                    continue
                found = (
                    await db.execute(select(PluginRegistryDB).where(PluginRegistryDB.plugin_id == manifest["plugin_id"]))
                ).scalar_one_or_none()
                if not found:
                    record = PluginRegistryDB(plugin_id=manifest["plugin_id"], created_at=_now())
                    self._apply_plugin(record, manifest, "filesystem")
                    db.add(record)
                    await self._add_audit(
                        db,
                        record.plugin_id,
                        "REGISTER",
                        "system",
                        "Filesystem plugin discovered.",
                        manifest,
                    )
            await db.commit()

    def validate_manifest(self, data: Dict[str, Any]) -> List[str]:
        return validate_plugin_manifest(data)

    def _load_file_manifests(self) -> List[Dict[str, Any]]:
        if not PLUGIN_ROOT.exists():
            return []
        manifests: List[Dict[str, Any]] = []
        for path in PLUGIN_ROOT.glob("*/plugin.json"):
            try:
                manifests.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        return manifests

    def _apply_plugin(self, record: PluginRegistryDB, data: Dict[str, Any], source: str) -> None:
        record.version = data.get("version", "0.1.0")
        record.name = data.get("name", data.get("plugin_id", ""))
        record.description = data.get("description", "")
        record.agents = data.get("agents", [])
        record.permissions = data.get("permissions", [])
        record.input_schema = data.get("input_schema", {})
        record.output_schema = data.get("output_schema", {})
        record.risk_level = data.get("risk_level", "LOW")
        record.enabled = bool(data.get("enabled", True))
        record.source = source
        record.manifest = data.get("manifest", {})
        record.updated_at = _now()

    async def _add_audit(
        self,
        db,
        plugin_id: str,
        action: str,
        actor: str,
        message: str,
        payload: Dict[str, Any],
        audit_id: Optional[str] = None,
    ) -> None:
        safe_payload = _redact_sensitive_payload(payload)
        db.add(
            PluginAuditDB(
                audit_id=audit_id or _audit_id(plugin_id, action),
                plugin_id=plugin_id,
                action=action,
                actor=actor,
                message=message,
                payload_json=safe_payload,
                created_at=_now(),
            )
        )

    def _plugin_to_dict(self, record: PluginRegistryDB) -> Dict[str, Any]:
        manifest = record.manifest or {}
        lifecycle = _lifecycle_from_manifest(manifest)
        package_artifact = manifest.get("package_artifact") if isinstance(manifest.get("package_artifact"), dict) else {}
        return {
            "plugin_id": record.plugin_id,
            "version": record.version,
            "name": record.name,
            "description": record.description,
            "agents": record.agents or [],
            "permissions": record.permissions or [],
            "input_schema": record.input_schema or {},
            "output_schema": record.output_schema or {},
            "risk_level": record.risk_level,
            "enabled": record.enabled,
            "source": record.source,
            "manifest": manifest,
            "lifecycle_status": str(lifecycle.get("status") or "ACTIVE").upper(),
            "archived_at": str(lifecycle.get("archived_at") or ""),
            "archived_by": str(lifecycle.get("archived_by") or ""),
            "upgraded_at": str(lifecycle.get("upgraded_at") or ""),
            "upgraded_by": str(lifecycle.get("upgraded_by") or ""),
            "upgrade_from_version": str(lifecycle.get("upgrade_from_version") or ""),
            "package_artifact_id": str(lifecycle.get("package_artifact_id") or ""),
            "package_checksum": str(lifecycle.get("package_checksum") or ""),
            "package_artifact_verified": bool(
                lifecycle.get("package_artifact_verified") or package_artifact.get("verified") is True
            ),
            "package_artifact_storage_path": str(package_artifact.get("storage_path") or ""),
            "package_scan_status": str(
                lifecycle.get("package_scan_status") or package_artifact.get("scan_status") or ""
            ),
            "package_hash_scan_status": str(
                lifecycle.get("package_hash_scan_status") or package_artifact.get("hash_scan_status") or ""
            ),
            "package_external_scan_status": str(
                lifecycle.get("package_external_scan_status") or package_artifact.get("external_scan_status") or ""
            ),
            "package_external_scan_provider": str(
                lifecycle.get("package_external_scan_provider") or package_artifact.get("external_scan_provider") or ""
            ),
            "package_retention_expires_at": str(
                lifecycle.get("package_retention_expires_at") or package_artifact.get("retention_expires_at") or ""
            ),
            "package_retention_days": _safe_int(
                lifecycle.get("package_retention_days") or package_artifact.get("retention_days")
            ),
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }

    def _audit_to_dict(self, record: PluginAuditDB) -> Dict[str, Any]:
        return {
            "audit_id": record.audit_id,
            "plugin_id": record.plugin_id,
            "action": record.action,
            "actor": record.actor,
            "message": record.message,
            "payload_json": _redact_sensitive_payload(record.payload_json or {}),
            "created_at": record.created_at,
        }


plugin_store = PluginStore()
