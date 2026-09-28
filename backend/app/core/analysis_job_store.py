import json
import logging
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .file_utils import write_json_atomic
from ..db.session import DATABASE_URL, DB_PATH


def _storage_file_from_env() -> Path:
    raw_path = os.getenv("TIANYUAN_ANALYSIS_JOBS_FILE", "").strip()
    if raw_path:
        return Path(raw_path).expanduser()
    return Path(__file__).resolve().parents[1] / "storage" / "analysis_jobs.json"


STORAGE_FILE = _storage_file_from_env()
logger = logging.getLogger(__name__)

TERMINAL_JOB_STATUSES = {"COMPLETED", "FAILED", "CANCELLED", "STALE"}
STALE_RECOVERABLE_JOB_STATUSES = {"PENDING", "QUEUED", "RUNNING", "CANCEL_REQUESTED"}
ACTIVE_JOB_STATUSES = {"PENDING", "QUEUED", "RUNNING", "CANCEL_REQUESTED"}
LEASE_PROTECTED_JOB_STATUSES = {"RUNNING", "CANCEL_REQUESTED"}
DEFAULT_OPERATOR = "local_workbench"
DEFAULT_QUEUE_NAME = "analysis"
DEFAULT_CONCURRENCY_GROUP = "analysis"
DEFAULT_CONCURRENCY_LIMIT = 1
DEFAULT_WORKER_ID = "in_process_analysis_worker"
DEFAULT_LEASE_SECONDS = 60
EXTERNAL_QUEUE_STATUS_SCHEMA_VERSION = "analysis_job_external_queue_status_v1"
EXTERNAL_QUEUE_STATUS_FILE_ENVS = (
    "TIANYUAN_ANALYSIS_JOB_EXTERNAL_QUEUE_STATUS_FILE",
    "ANALYSIS_JOB_EXTERNAL_QUEUE_STATUS_FILE",
)
ALLOWED_EXTERNAL_QUEUE_STATUSES = {"READY", "DEGRADED", "FAILED", "UNKNOWN"}
EXTERNAL_QUEUE_STATUS_MAX_BYTES = 64 * 1024
EXTERNAL_QUEUE_LOCAL_MODE = "LOCAL_JSON_SQLITE_DIAGNOSTIC"
SECRET_TEXT_PATTERN = re.compile(
    r"(authorization|bearer|token|api[_-]?key|secret|password|credential)",
    re.IGNORECASE,
)


def _sqlite_path_from_database_url(url: str) -> Path | None:
    if not url.startswith("sqlite"):
        return None
    for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
        if url.startswith(prefix):
            raw_path = url[len(prefix) :]
            if raw_path == ":memory:":
                return None
            return Path(raw_path)
    return DB_PATH


SQLITE_DB_FILE = _sqlite_path_from_database_url(DATABASE_URL)
DEFAULT_SQLITE_TIMEOUT_SECONDS = 0.25


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_state() -> Dict[str, Any]:
    if not STORAGE_FILE.exists():
        return {"version": 1, "jobs": {}, "updated_at": _now()}
    try:
        with STORAGE_FILE.open("r", encoding="utf-8") as file:
            state = json.load(file)
    except (json.JSONDecodeError, OSError):
        return {"version": 1, "jobs": {}, "updated_at": _now(), "warning": "job_store_recovered"}
    state.setdefault("version", 1)
    state.setdefault("jobs", {})
    return state


def _save_state(state: Dict[str, Any]) -> None:
    state["updated_at"] = _now()
    write_json_atomic(STORAGE_FILE, state)


def _sqlite_file() -> Path | None:
    if SQLITE_DB_FILE is None:
        return None
    return Path(SQLITE_DB_FILE)


def _sqlite_connect() -> sqlite3.Connection:
    db_file = _sqlite_file()
    if db_file is None:
        raise sqlite3.OperationalError("analysis job sqlite mirror is disabled for this database url")
    db_file.parent.mkdir(parents=True, exist_ok=True)
    timeout_seconds = _sqlite_timeout_seconds()
    conn = sqlite3.connect(str(db_file), timeout=timeout_seconds)
    conn.execute(f"PRAGMA busy_timeout = {int(timeout_seconds * 1000)}")
    conn.row_factory = sqlite3.Row
    return conn


def _sqlite_timeout_seconds() -> float:
    raw_value = os.getenv("TIANYUAN_SQLITE_JOB_TIMEOUT_SECONDS", "")
    try:
        value = float(raw_value) if raw_value else DEFAULT_SQLITE_TIMEOUT_SECONDS
    except ValueError:
        value = DEFAULT_SQLITE_TIMEOUT_SECONDS
    return max(0.05, min(value, 5.0))


def _lease_seconds() -> int:
    raw_value = os.getenv("TIANYUAN_ANALYSIS_JOB_LEASE_SECONDS", "")
    try:
        value = int(raw_value) if raw_value else DEFAULT_LEASE_SECONDS
    except ValueError:
        value = DEFAULT_LEASE_SECONDS
    return max(5, min(value, 3600))


def _is_sqlite_locked(exc: BaseException) -> bool:
    return isinstance(exc, sqlite3.OperationalError) and "database is locked" in str(exc).lower()


def _is_sqlite_duplicate_column(exc: BaseException) -> bool:
    return isinstance(exc, sqlite3.OperationalError) and "duplicate column name" in str(exc).lower()


def _external_queue_status_file() -> Path | None:
    for env_name in EXTERNAL_QUEUE_STATUS_FILE_ENVS:
        raw_path = os.getenv(env_name, "").strip()
        if raw_path:
            return Path(raw_path).expanduser()
    return None


def _safe_sidecar_text(value: Any, *, default: str = "", max_length: int = 160) -> str:
    text = str(value if value is not None else default).replace("\r", " ").replace("\n", " ").strip()
    if not text:
        return default
    if SECRET_TEXT_PATTERN.search(text):
        return "[redacted]"
    return text[:max_length]


def _safe_sidecar_int(value: Any, *, default: int = 0, max_value: int = 1_000_000) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(0, min(parsed, max_value))


def _safe_optional_sidecar_int(value: Any, *, max_value: int = 31_536_000) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, min(parsed, max_value))


def _base_external_queue_status() -> Dict[str, Any]:
    return {
        "schema": EXTERNAL_QUEUE_STATUS_SCHEMA_VERSION,
        "checked": False,
        "reported": False,
        "status": "NOT_CONFIGURED",
        "sidecar_file": "",
        "reported_at": "",
        "source": "local_sidecar",
        "provider": "",
        "queue_name": DEFAULT_QUEUE_NAME,
        "lease_backend": "",
        "claim_backend": "",
        "claim_status": "",
        "idempotency_scope": "",
        "audit_stream": "",
        "dead_letter_queue": "",
        "dead_letter_count": 0,
        "visibility_timeout_seconds": None,
        "lease_renewal_status": "",
        "worker_pool": "",
        "active_workers": 0,
        "pending_jobs": 0,
        "running_jobs": 0,
        "oldest_pending_age_seconds": None,
        "message": "external queue sidecar is not configured",
        "deployment_reported": False,
        "local_queue_mode": EXTERNAL_QUEUE_LOCAL_MODE,
        "issues": [],
    }


def external_queue_status() -> Dict[str, Any]:
    status = _base_external_queue_status()
    sidecar_file = _external_queue_status_file()
    if sidecar_file is None:
        return status

    status.update(
        {
            "checked": True,
            "status": "NOT_REPORTED",
            "sidecar_file": str(sidecar_file),
            "message": "external queue sidecar file was not reported",
            "issues": ["sidecar_file_missing"],
        }
    )
    if not sidecar_file.exists():
        return status

    try:
        if sidecar_file.stat().st_size > EXTERNAL_QUEUE_STATUS_MAX_BYTES:
            status.update(
                {
                    "status": "INVALID",
                    "message": "external queue sidecar file exceeds the read limit",
                    "issues": ["sidecar_file_too_large"],
                }
            )
            return status
        payload = json.loads(sidecar_file.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError) as exc:
        status.update(
            {
                "status": "INVALID",
                "message": _safe_sidecar_text(f"invalid external queue sidecar: {exc}", max_length=200),
                "issues": ["sidecar_file_invalid"],
            }
        )
        return status

    if not isinstance(payload, dict):
        status.update(
            {
                "status": "INVALID",
                "message": "external queue sidecar payload is not an object",
                "issues": ["sidecar_payload_invalid"],
            }
        )
        return status

    if payload.get("schema") != EXTERNAL_QUEUE_STATUS_SCHEMA_VERSION:
        status.update(
            {
                "status": "INVALID",
                "message": "external queue sidecar schema mismatch",
                "issues": ["sidecar_schema_mismatch"],
            }
        )
        return status

    reported_status = str(payload.get("status") or "UNKNOWN").strip().upper()
    issues = payload.get("issues")
    safe_issues = [
        _safe_sidecar_text(issue, max_length=120)
        for issue in (issues if isinstance(issues, list) else [])
    ][:12]
    if reported_status not in ALLOWED_EXTERNAL_QUEUE_STATUSES:
        safe_issues.append("sidecar_status_invalid")
        reported_status = "UNKNOWN"

    status.update(
        {
            "reported": True,
            "status": reported_status,
            "reported_at": _safe_sidecar_text(payload.get("reported_at"), max_length=80),
            "source": _safe_sidecar_text(payload.get("source"), default="deployment_sidecar", max_length=80),
            "provider": _safe_sidecar_text(payload.get("provider"), max_length=80),
            "queue_name": _safe_sidecar_text(payload.get("queue_name"), default=DEFAULT_QUEUE_NAME, max_length=80),
            "lease_backend": _safe_sidecar_text(payload.get("lease_backend"), max_length=80),
            "claim_backend": _safe_sidecar_text(payload.get("claim_backend"), max_length=80),
            "claim_status": _safe_sidecar_text(payload.get("claim_status"), max_length=80),
            "idempotency_scope": _safe_sidecar_text(payload.get("idempotency_scope"), max_length=120),
            "audit_stream": _safe_sidecar_text(payload.get("audit_stream"), max_length=160),
            "dead_letter_queue": _safe_sidecar_text(payload.get("dead_letter_queue"), max_length=120),
            "dead_letter_count": _safe_sidecar_int(payload.get("dead_letter_count")),
            "visibility_timeout_seconds": _safe_optional_sidecar_int(payload.get("visibility_timeout_seconds")),
            "lease_renewal_status": _safe_sidecar_text(payload.get("lease_renewal_status"), max_length=80),
            "worker_pool": _safe_sidecar_text(payload.get("worker_pool"), max_length=80),
            "active_workers": _safe_sidecar_int(payload.get("active_workers")),
            "pending_jobs": _safe_sidecar_int(payload.get("pending_jobs")),
            "running_jobs": _safe_sidecar_int(payload.get("running_jobs")),
            "oldest_pending_age_seconds": _safe_optional_sidecar_int(payload.get("oldest_pending_age_seconds")),
            "message": _safe_sidecar_text(payload.get("message"), max_length=200),
            "deployment_reported": True,
            "issues": [issue for issue in safe_issues if issue],
        }
    )
    return status


def _ensure_sqlite_table() -> None:
    with _sqlite_connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS analysis_jobs (
                run_id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                attempt INTEGER DEFAULT 0,
                max_attempts INTEGER DEFAULT 3,
                queue_name TEXT DEFAULT 'analysis',
                priority INTEGER DEFAULT 0,
                concurrency_group TEXT DEFAULT 'analysis',
                concurrency_limit INTEGER DEFAULT 1,
                worker_id TEXT DEFAULT '',
                worker_heartbeat_at TEXT DEFAULT '',
                lease_expires_at TEXT DEFAULT '',
                lease_status TEXT DEFAULT '',
                lease_seconds INTEGER DEFAULT 60,
                operator TEXT DEFAULT 'local_workbench',
                last_operator TEXT DEFAULT 'local_workbench',
                last_error TEXT DEFAULT '',
                failed_node_id TEXT DEFAULT '',
                retry_from_node_id TEXT DEFAULT '',
                resume_from_node_id TEXT DEFAULT '',
                retry_of_job_id TEXT DEFAULT '',
                same_input_retry INTEGER DEFAULT 0,
                stale_reason TEXT DEFAULT '',
                created_at TEXT DEFAULT '',
                updated_at TEXT DEFAULT '',
                queued_at TEXT DEFAULT '',
                started_at TEXT DEFAULT '',
                finished_at TEXT DEFAULT '',
                cancel_requested_at TEXT DEFAULT '',
                history_json TEXT DEFAULT '[]',
                recovery_json TEXT DEFAULT '{}',
                payload_json TEXT DEFAULT '{}'
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS analysis_job_attempts (
                run_id TEXT NOT NULL,
                attempt INTEGER NOT NULL,
                job_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                queue_name TEXT DEFAULT 'analysis',
                concurrency_group TEXT DEFAULT 'analysis',
                worker_id TEXT DEFAULT '',
                worker_heartbeat_at TEXT DEFAULT '',
                lease_expires_at TEXT DEFAULT '',
                lease_status TEXT DEFAULT '',
                lease_seconds INTEGER DEFAULT 60,
                operator TEXT DEFAULT 'local_workbench',
                last_operator TEXT DEFAULT 'local_workbench',
                last_error TEXT DEFAULT '',
                failed_node_id TEXT DEFAULT '',
                retry_from_node_id TEXT DEFAULT '',
                resume_from_node_id TEXT DEFAULT '',
                retry_of_job_id TEXT DEFAULT '',
                same_input_retry INTEGER DEFAULT 0,
                stale_reason TEXT DEFAULT '',
                created_at TEXT DEFAULT '',
                updated_at TEXT DEFAULT '',
                queued_at TEXT DEFAULT '',
                started_at TEXT DEFAULT '',
                finished_at TEXT DEFAULT '',
                history_json TEXT DEFAULT '[]',
                payload_json TEXT DEFAULT '{}',
                PRIMARY KEY (run_id, attempt)
            )
            """
        )
        _ensure_sqlite_columns(
            conn,
            "analysis_jobs",
            {
                "lease_expires_at": "TEXT DEFAULT ''",
                "lease_status": "TEXT DEFAULT ''",
                "lease_seconds": f"INTEGER DEFAULT {DEFAULT_LEASE_SECONDS}",
            },
        )
        _ensure_sqlite_columns(
            conn,
            "analysis_job_attempts",
            {
                "lease_expires_at": "TEXT DEFAULT ''",
                "lease_status": "TEXT DEFAULT ''",
                "lease_seconds": f"INTEGER DEFAULT {DEFAULT_LEASE_SECONDS}",
            },
        )
        for name, column in {
            "ix_analysis_jobs_job_id": "job_id",
            "ix_analysis_jobs_status": "status",
            "ix_analysis_jobs_queue_name": "queue_name",
            "ix_analysis_jobs_concurrency_group": "concurrency_group",
            "ix_analysis_jobs_worker_id": "worker_id",
            "ix_analysis_jobs_worker_heartbeat_at": "worker_heartbeat_at",
            "ix_analysis_jobs_lease_expires_at": "lease_expires_at",
            "ix_analysis_jobs_lease_status": "lease_status",
            "ix_analysis_jobs_created_at": "created_at",
            "ix_analysis_jobs_updated_at": "updated_at",
            "ix_analysis_jobs_queued_at": "queued_at",
            "ix_analysis_jobs_started_at": "started_at",
            "ix_analysis_jobs_finished_at": "finished_at",
            "ix_analysis_jobs_cancel_requested_at": "cancel_requested_at",
        }.items():
            conn.execute(f"CREATE INDEX IF NOT EXISTS {name} ON analysis_jobs ({column})")
        for name, column in {
            "ix_analysis_job_attempts_job_id": "job_id",
            "ix_analysis_job_attempts_status": "status",
            "ix_analysis_job_attempts_queue_name": "queue_name",
            "ix_analysis_job_attempts_concurrency_group": "concurrency_group",
            "ix_analysis_job_attempts_worker_id": "worker_id",
            "ix_analysis_job_attempts_lease_status": "lease_status",
            "ix_analysis_job_attempts_updated_at": "updated_at",
            "ix_analysis_job_attempts_finished_at": "finished_at",
        }.items():
            conn.execute(f"CREATE INDEX IF NOT EXISTS {name} ON analysis_job_attempts ({column})")
        conn.commit()


def _ensure_sqlite_columns(conn: sqlite3.Connection, table: str, columns: Dict[str, str]) -> None:
    existing_columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for column, definition in columns.items():
        if column not in existing_columns:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            except sqlite3.OperationalError as exc:
                if _is_sqlite_duplicate_column(exc):
                    existing_columns.add(column)
                    continue
                raise
            existing_columns.add(column)


def _decode_json(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return default


def _encode_json(value: Any, default: Any) -> str:
    if value is None:
        value = default
    return json.dumps(value, ensure_ascii=False)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _apply_lease_metadata(job: Dict[str, Any]) -> Dict[str, Any]:
    lease_seconds = _lease_seconds()
    status = str(job.get("status") or "").upper()
    job["lease_seconds"] = lease_seconds

    if status in {"RUNNING", "CANCEL_REQUESTED"}:
        heartbeat_at = str(job.get("worker_heartbeat_at") or "").strip()
        parsed_heartbeat = _parse_timestamp(heartbeat_at)
        if parsed_heartbeat is None:
            job["lease_expires_at"] = ""
            job["lease_status"] = "UNLEASED" if not heartbeat_at else "UNKNOWN"
            return job

        expires_at = parsed_heartbeat + timedelta(seconds=lease_seconds)
        job["lease_expires_at"] = expires_at.isoformat()
        job["lease_status"] = "EXPIRED" if datetime.now(timezone.utc) >= expires_at else "ACTIVE"
        return job

    if status in {"PENDING", "QUEUED"}:
        job["lease_expires_at"] = ""
        job["lease_status"] = "UNCLAIMED"
        return job

    job["lease_expires_at"] = ""
    job["lease_status"] = "RELEASED" if job.get("worker_id") or job.get("worker_heartbeat_at") else "UNCLAIMED"
    return job


def _normalize_job(job: Dict[str, Any]) -> Dict[str, Any]:
    run_id = str(job.get("run_id") or "").strip()
    if not run_id:
        raise ValueError("analysis job requires run_id")
    base = _base_job(run_id)
    normalized = {**base, **job}
    normalized["run_id"] = run_id
    normalized["job_id"] = str(normalized.get("job_id") or f"JOB_{run_id}")
    normalized["status"] = str(normalized.get("status") or "PENDING").upper()
    normalized["attempt"] = _as_int(normalized.get("attempt"), 0)
    normalized["max_attempts"] = _as_int(normalized.get("max_attempts"), 3)
    normalized["priority"] = _as_int(normalized.get("priority"), 0)
    normalized["concurrency_limit"] = max(_as_int(normalized.get("concurrency_limit"), DEFAULT_CONCURRENCY_LIMIT), 1)
    normalized["queue_name"] = str(normalized.get("queue_name") or DEFAULT_QUEUE_NAME)
    normalized["concurrency_group"] = str(normalized.get("concurrency_group") or DEFAULT_CONCURRENCY_GROUP)
    normalized["worker_id"] = str(normalized.get("worker_id") or "")
    normalized["worker_heartbeat_at"] = str(normalized.get("worker_heartbeat_at") or "")
    normalized["lease_expires_at"] = str(normalized.get("lease_expires_at") or "")
    normalized["lease_status"] = str(normalized.get("lease_status") or "")
    normalized["lease_seconds"] = _as_int(normalized.get("lease_seconds"), DEFAULT_LEASE_SECONDS)
    normalized["operator"] = _clean_operator(normalized.get("operator"))
    normalized["last_operator"] = _clean_operator(normalized.get("last_operator") or normalized["operator"])
    normalized["last_error"] = str(normalized.get("last_error") or "")
    normalized["failed_node_id"] = str(normalized.get("failed_node_id") or "")
    normalized["retry_from_node_id"] = str(normalized.get("retry_from_node_id") or "")
    normalized["resume_from_node_id"] = str(normalized.get("resume_from_node_id") or "")
    normalized["retry_of_job_id"] = str(normalized.get("retry_of_job_id") or "")
    normalized["same_input_retry"] = bool(normalized.get("same_input_retry"))
    normalized["stale_reason"] = str(normalized.get("stale_reason") or "")
    for key in ("created_at", "updated_at", "queued_at", "started_at", "finished_at", "cancel_requested_at"):
        normalized[key] = str(normalized.get(key) or "")
    history = normalized.get("history")
    normalized["history"] = history if isinstance(history, list) else []
    recovery = normalized.get("recovery")
    normalized["recovery"] = recovery if isinstance(recovery, dict) else {}
    return _apply_lease_metadata(normalized)


def _row_to_job(row: sqlite3.Row) -> Dict[str, Any]:
    payload = _decode_json(row["payload_json"], {})
    job = payload if isinstance(payload, dict) else {}
    job.update(
        {
            "run_id": row["run_id"],
            "job_id": row["job_id"],
            "status": row["status"],
            "attempt": _as_int(row["attempt"], 0),
            "max_attempts": _as_int(row["max_attempts"], 3),
            "queue_name": row["queue_name"] or DEFAULT_QUEUE_NAME,
            "priority": _as_int(row["priority"], 0),
            "concurrency_group": row["concurrency_group"] or DEFAULT_CONCURRENCY_GROUP,
            "concurrency_limit": max(_as_int(row["concurrency_limit"], DEFAULT_CONCURRENCY_LIMIT), 1),
            "worker_id": row["worker_id"] or "",
            "worker_heartbeat_at": row["worker_heartbeat_at"] or "",
            "lease_expires_at": row["lease_expires_at"] or "",
            "lease_status": row["lease_status"] or "",
            "lease_seconds": _as_int(row["lease_seconds"], DEFAULT_LEASE_SECONDS),
            "operator": row["operator"] or DEFAULT_OPERATOR,
            "last_operator": row["last_operator"] or DEFAULT_OPERATOR,
            "last_error": row["last_error"] or "",
            "failed_node_id": row["failed_node_id"] or "",
            "retry_from_node_id": row["retry_from_node_id"] or "",
            "resume_from_node_id": row["resume_from_node_id"] or "",
            "retry_of_job_id": row["retry_of_job_id"] or "",
            "same_input_retry": bool(row["same_input_retry"]),
            "stale_reason": row["stale_reason"] or "",
            "created_at": row["created_at"] or "",
            "updated_at": row["updated_at"] or "",
            "queued_at": row["queued_at"] or "",
            "started_at": row["started_at"] or "",
            "finished_at": row["finished_at"] or "",
            "cancel_requested_at": row["cancel_requested_at"] or "",
            "history": _decode_json(row["history_json"], []),
            "recovery": _decode_json(row["recovery_json"], {}),
        }
    )
    return _sanitize_active_job(_apply_lease_metadata(job))


def _row_to_attempt(row: sqlite3.Row) -> Dict[str, Any]:
    payload = _decode_json(row["payload_json"], {})
    attempt = payload if isinstance(payload, dict) else {}
    attempt.update(
        {
            "run_id": row["run_id"],
            "attempt": _as_int(row["attempt"], 0),
            "job_id": row["job_id"],
            "status": row["status"],
            "queue_name": row["queue_name"] or DEFAULT_QUEUE_NAME,
            "concurrency_group": row["concurrency_group"] or DEFAULT_CONCURRENCY_GROUP,
            "worker_id": row["worker_id"] or "",
            "worker_heartbeat_at": row["worker_heartbeat_at"] or "",
            "lease_expires_at": row["lease_expires_at"] or "",
            "lease_status": row["lease_status"] or "",
            "lease_seconds": _as_int(row["lease_seconds"], DEFAULT_LEASE_SECONDS),
            "operator": row["operator"] or DEFAULT_OPERATOR,
            "last_operator": row["last_operator"] or DEFAULT_OPERATOR,
            "last_error": row["last_error"] or "",
            "failed_node_id": row["failed_node_id"] or "",
            "retry_from_node_id": row["retry_from_node_id"] or "",
            "resume_from_node_id": row["resume_from_node_id"] or "",
            "retry_of_job_id": row["retry_of_job_id"] or "",
            "same_input_retry": bool(row["same_input_retry"]),
            "stale_reason": row["stale_reason"] or "",
            "created_at": row["created_at"] or "",
            "updated_at": row["updated_at"] or "",
            "queued_at": row["queued_at"] or "",
            "started_at": row["started_at"] or "",
            "finished_at": row["finished_at"] or "",
            "history": _decode_json(row["history_json"], []),
        }
    )
    return _apply_lease_metadata(attempt)


def _sanitize_active_job(job: Dict[str, Any] | None) -> Dict[str, Any] | None:
    if not isinstance(job, dict):
        return job
    sanitized = _apply_lease_metadata(dict(job))
    status = str(sanitized.get("status") or "").upper()
    if status not in ACTIVE_JOB_STATUSES and not _is_stale_retry_failure_carryover(sanitized):
        return sanitized
    sanitized["failed_node_id"] = ""
    if status in ACTIVE_JOB_STATUSES:
        sanitized["stale_reason"] = ""
    return sanitized


def _is_stale_retry_failure_carryover(job: Dict[str, Any]) -> bool:
    if str(job.get("status") or "").upper() != "STALE":
        return False
    failed_node_id = str(job.get("failed_node_id") or "")
    if not failed_node_id or failed_node_id != str(job.get("retry_from_node_id") or ""):
        return False
    if not str(job.get("last_error") or "").startswith("Analysis job recovered as stale:"):
        return False
    recovery = job.get("recovery") if isinstance(job.get("recovery"), dict) else {}
    return not str(recovery.get("previousLastError") or "")


def _lease_rejection(
    job: Dict[str, Any],
    *,
    attempted_worker_id: str,
    actor: str,
    event: str,
) -> Dict[str, Any]:
    rejected = _normalize_job(dict(job))
    current_worker_id = str(rejected.get("worker_id") or "")
    rejected["lease_update_rejected"] = True
    rejected["lease_rejection_reason"] = "WORKER_LEASE_OWNER_MISMATCH"
    rejected["attempted_worker_id"] = attempted_worker_id
    rejected["current_worker_id"] = current_worker_id
    rejected["last_operator"] = actor
    rejected["rejected_event"] = event
    return rejected


def _reject_if_worker_mismatch(
    job: Dict[str, Any],
    *,
    worker_id: str | None,
    actor: str,
    event: str,
) -> Dict[str, Any] | None:
    attempted_worker_id = str(worker_id or "").strip()
    if not attempted_worker_id:
        return None
    status = str(job.get("status") or "").upper()
    if status not in LEASE_PROTECTED_JOB_STATUSES:
        return None
    current_worker_id = str(job.get("worker_id") or "").strip()
    if current_worker_id and current_worker_id != attempted_worker_id:
        return _lease_rejection(
            job,
            attempted_worker_id=attempted_worker_id,
            actor=actor,
            event=event,
        )
    return None


def _json_job_is_newer_or_equal(json_job: Dict[str, Any], sqlite_job: Dict[str, Any] | None) -> bool:
    if sqlite_job is None:
        return True
    json_activity = _job_activity_at(json_job)
    sqlite_activity = _job_activity_at(sqlite_job)
    if json_activity is None:
        return sqlite_activity is None
    if sqlite_activity is None:
        return True
    return json_activity >= sqlite_activity


def upsert_sqlite_job(job: Dict[str, Any]) -> Dict[str, Any]:
    normalized = _normalize_job(job)
    _ensure_sqlite_table()
    payload = dict(normalized)
    params = {
        "run_id": normalized["run_id"],
        "job_id": normalized["job_id"],
        "status": normalized["status"],
        "attempt": normalized["attempt"],
        "max_attempts": normalized["max_attempts"],
        "queue_name": normalized["queue_name"],
        "priority": normalized["priority"],
        "concurrency_group": normalized["concurrency_group"],
        "concurrency_limit": normalized["concurrency_limit"],
        "worker_id": normalized["worker_id"],
        "worker_heartbeat_at": normalized["worker_heartbeat_at"],
        "lease_expires_at": normalized["lease_expires_at"],
        "lease_status": normalized["lease_status"],
        "lease_seconds": normalized["lease_seconds"],
        "operator": normalized["operator"],
        "last_operator": normalized["last_operator"],
        "last_error": normalized["last_error"],
        "failed_node_id": normalized["failed_node_id"],
        "retry_from_node_id": normalized["retry_from_node_id"],
        "resume_from_node_id": normalized["resume_from_node_id"],
        "retry_of_job_id": normalized["retry_of_job_id"],
        "same_input_retry": 1 if normalized["same_input_retry"] else 0,
        "stale_reason": normalized["stale_reason"],
        "created_at": normalized["created_at"],
        "updated_at": normalized["updated_at"],
        "queued_at": normalized["queued_at"],
        "started_at": normalized["started_at"],
        "finished_at": normalized["finished_at"],
        "cancel_requested_at": normalized["cancel_requested_at"],
        "history_json": _encode_json(normalized["history"], []),
        "recovery_json": _encode_json(normalized["recovery"], {}),
        "payload_json": _encode_json(payload, {}),
    }
    update_columns = [key for key in params if key != "run_id"]
    assignments = ", ".join(f"{key}=excluded.{key}" for key in update_columns)
    with _sqlite_connect() as conn:
        conn.execute(
            f"""
            INSERT INTO analysis_jobs (
                run_id, job_id, status, attempt, max_attempts, queue_name, priority,
                concurrency_group, concurrency_limit, worker_id, worker_heartbeat_at,
                lease_expires_at, lease_status, lease_seconds,
                operator, last_operator, last_error, failed_node_id, retry_from_node_id,
                resume_from_node_id, retry_of_job_id, same_input_retry, stale_reason,
                created_at, updated_at, queued_at, started_at, finished_at,
                cancel_requested_at, history_json, recovery_json, payload_json
            ) VALUES (
                :run_id, :job_id, :status, :attempt, :max_attempts, :queue_name, :priority,
                :concurrency_group, :concurrency_limit, :worker_id, :worker_heartbeat_at,
                :lease_expires_at, :lease_status, :lease_seconds,
                :operator, :last_operator, :last_error, :failed_node_id, :retry_from_node_id,
                :resume_from_node_id, :retry_of_job_id, :same_input_retry, :stale_reason,
                :created_at, :updated_at, :queued_at, :started_at, :finished_at,
                :cancel_requested_at, :history_json, :recovery_json, :payload_json
            )
            ON CONFLICT(run_id) DO UPDATE SET {assignments}
            """,
            params,
        )
        _upsert_attempt_with_conn(conn, normalized)
        conn.commit()
    return normalized


def _upsert_attempt_with_conn(conn: sqlite3.Connection, job: Dict[str, Any]) -> None:
    attempt = _as_int(job.get("attempt"), 0)
    if attempt <= 0:
        return
    payload = dict(job)
    params = {
        "run_id": job["run_id"],
        "attempt": attempt,
        "job_id": job["job_id"],
        "status": job["status"],
        "queue_name": job["queue_name"],
        "concurrency_group": job["concurrency_group"],
        "worker_id": job["worker_id"],
        "worker_heartbeat_at": job["worker_heartbeat_at"],
        "lease_expires_at": job["lease_expires_at"],
        "lease_status": job["lease_status"],
        "lease_seconds": job["lease_seconds"],
        "operator": job["operator"],
        "last_operator": job["last_operator"],
        "last_error": job["last_error"],
        "failed_node_id": job["failed_node_id"],
        "retry_from_node_id": job["retry_from_node_id"],
        "resume_from_node_id": job["resume_from_node_id"],
        "retry_of_job_id": job["retry_of_job_id"],
        "same_input_retry": 1 if job["same_input_retry"] else 0,
        "stale_reason": job["stale_reason"],
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
        "queued_at": job["queued_at"],
        "started_at": job["started_at"],
        "finished_at": job["finished_at"],
        "history_json": _encode_json(job["history"], []),
        "payload_json": _encode_json(payload, {}),
    }
    update_columns = [key for key in params if key not in {"run_id", "attempt"}]
    assignments = ", ".join(f"{key}=excluded.{key}" for key in update_columns)
    conn.execute(
        f"""
        INSERT INTO analysis_job_attempts (
            run_id, attempt, job_id, status, queue_name, concurrency_group,
            worker_id, worker_heartbeat_at, lease_expires_at, lease_status, lease_seconds,
            operator, last_operator, last_error,
            failed_node_id, retry_from_node_id, resume_from_node_id, retry_of_job_id,
            same_input_retry, stale_reason, created_at, updated_at, queued_at,
            started_at, finished_at, history_json, payload_json
        ) VALUES (
            :run_id, :attempt, :job_id, :status, :queue_name, :concurrency_group,
            :worker_id, :worker_heartbeat_at, :lease_expires_at, :lease_status, :lease_seconds,
            :operator, :last_operator, :last_error,
            :failed_node_id, :retry_from_node_id, :resume_from_node_id, :retry_of_job_id,
            :same_input_retry, :stale_reason, :created_at, :updated_at, :queued_at,
            :started_at, :finished_at, :history_json, :payload_json
        )
        ON CONFLICT(run_id, attempt) DO UPDATE SET {assignments}
        """,
        params,
    )


def _mirror_job_to_sqlite(job: Dict[str, Any]) -> None:
    try:
        upsert_sqlite_job(job)
    except (OSError, sqlite3.Error, ValueError) as exc:
        if _is_sqlite_locked(exc):
            logger.warning("Skipped analysis job SQLite mirror because the database is locked.")
            return
        logger.exception("Failed to mirror analysis job %s to SQLite.", job.get("run_id"))


def _mirror_state_to_sqlite(state: Dict[str, Any]) -> None:
    jobs = state.get("jobs", {})
    if not isinstance(jobs, dict):
        return
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        try:
            sqlite_job = get_sqlite_job(str(job.get("run_id") or ""))
            if _json_job_is_newer_or_equal(job, sqlite_job):
                upsert_sqlite_job(job)
        except (OSError, sqlite3.Error, ValueError) as exc:
            if _is_sqlite_locked(exc):
                logger.warning("Skipped analysis job SQLite state mirror because the database is locked.")
                return
            logger.exception("Failed to mirror existing analysis job state to SQLite.")


def get_sqlite_job(run_id: str) -> Optional[Dict[str, Any]]:
    if not run_id:
        return None
    if _sqlite_file() is None:
        return None
    _ensure_sqlite_table()
    with _sqlite_connect() as conn:
        row = conn.execute("SELECT * FROM analysis_jobs WHERE run_id = ?", (run_id,)).fetchone()
    return _row_to_job(row) if row else None


def list_sqlite_jobs(
    limit: int = 100,
    statuses: Iterable[str] | None = None,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    if _sqlite_file() is None:
        return []
    _ensure_sqlite_table()
    limit = max(min(int(limit or 100), 1000), 1)
    offset = max(int(offset or 0), 0)
    status_values = [str(status).upper() for status in (statuses or []) if str(status or "").strip()]
    with _sqlite_connect() as conn:
        if status_values:
            placeholders = ", ".join("?" for _ in status_values)
            rows = conn.execute(
                f"""
                SELECT * FROM analysis_jobs
                WHERE status IN ({placeholders})
                ORDER BY COALESCE(updated_at, created_at, '') DESC
                LIMIT ?
                OFFSET ?
                """,
                (*status_values, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM analysis_jobs
                ORDER BY COALESCE(updated_at, created_at, '') DESC
                LIMIT ?
                OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
    return [_row_to_job(row) for row in rows]


def summarize_sqlite_jobs(statuses: Iterable[str] | None = None) -> Dict[str, Any]:
    if _sqlite_file() is None:
        return {}
    _ensure_sqlite_table()
    status_values = [str(status).upper() for status in (statuses or []) if str(status or "").strip()]
    with _sqlite_connect() as conn:
        rows = conn.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM analysis_jobs
            GROUP BY status
            """
        ).fetchall()
        counts_by_status = {
            str(row["status"] or "UNKNOWN").upper(): int(row["count"] or 0)
            for row in rows
        }
        total_count = sum(counts_by_status.values())
        if status_values:
            placeholders = ", ".join("?" for _ in status_values)
            filtered_count = int(conn.execute(
                f"SELECT COUNT(*) FROM analysis_jobs WHERE status IN ({placeholders})",
                tuple(status_values),
            ).fetchone()[0] or 0)
        else:
            filtered_count = total_count
    return {
        "total_count": total_count,
        "filtered_count": filtered_count,
        "counts_by_status": counts_by_status,
        "statuses": status_values,
    }


def list_sqlite_attempts(
    *,
    run_id: str | None = None,
    limit: int = 100,
    statuses: Iterable[str] | None = None,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    if _sqlite_file() is None:
        return []
    _ensure_sqlite_table()
    limit = max(min(int(limit or 100), 1000), 1)
    offset = max(int(offset or 0), 0)
    status_values = [str(status).upper() for status in (statuses or []) if str(status or "").strip()]
    requested_run_id = str(run_id or "").strip()
    conditions: list[str] = []
    params: list[Any] = []
    if requested_run_id:
        conditions.append("run_id = ?")
        params.append(requested_run_id)
    if status_values:
        placeholders = ", ".join("?" for _ in status_values)
        conditions.append(f"status IN ({placeholders})")
        params.extend(status_values)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    order_clause = "attempt ASC" if requested_run_id else "COALESCE(updated_at, created_at, '') DESC, run_id ASC, attempt ASC"
    with _sqlite_connect() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM analysis_job_attempts
            {where_clause}
            ORDER BY {order_clause}
            LIMIT ?
            OFFSET ?
            """,
            (*params, limit, offset),
        ).fetchall()
    return [_row_to_attempt(row) for row in rows]


def _job_to_attempt(job: Dict[str, Any]) -> Dict[str, Any]:
    normalized = _normalize_job(dict(job))
    return {
        "run_id": normalized["run_id"],
        "attempt": normalized["attempt"],
        "job_id": normalized["job_id"],
        "status": normalized["status"],
        "queue_name": normalized["queue_name"],
        "concurrency_group": normalized["concurrency_group"],
        "worker_id": normalized["worker_id"],
        "worker_heartbeat_at": normalized["worker_heartbeat_at"],
        "lease_expires_at": normalized["lease_expires_at"],
        "lease_status": normalized["lease_status"],
        "lease_seconds": normalized["lease_seconds"],
        "operator": normalized["operator"],
        "last_operator": normalized["last_operator"],
        "last_error": normalized["last_error"],
        "failed_node_id": normalized["failed_node_id"],
        "retry_from_node_id": normalized["retry_from_node_id"],
        "resume_from_node_id": normalized["resume_from_node_id"],
        "retry_of_job_id": normalized["retry_of_job_id"],
        "same_input_retry": normalized["same_input_retry"],
        "stale_reason": normalized["stale_reason"],
        "created_at": normalized["created_at"],
        "updated_at": normalized["updated_at"],
        "queued_at": normalized["queued_at"],
        "started_at": normalized["started_at"],
        "finished_at": normalized["finished_at"],
        "history": normalized["history"],
    }


def list_json_attempts(
    *,
    run_id: str | None = None,
    limit: int = 100,
    statuses: Iterable[str] | None = None,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    state = _load_state()
    limit = max(min(int(limit or 100), 1000), 1)
    offset = max(int(offset or 0), 0)
    status_values = [str(status).upper() for status in (statuses or []) if str(status or "").strip()]
    requested_run_id = str(run_id or "").strip()
    raw_jobs = state.get("jobs", {})
    jobs: list[Dict[str, Any]] = []
    if requested_run_id:
        job = raw_jobs.get(requested_run_id) if isinstance(raw_jobs, dict) else None
        if isinstance(job, dict):
            jobs = [job]
    elif isinstance(raw_jobs, dict):
        jobs = [job for job in raw_jobs.values() if isinstance(job, dict)]

    attempts = [_job_to_attempt(job) for job in jobs]
    if status_values:
        attempts = [
            attempt for attempt in attempts
            if str(attempt.get("status") or "").upper() in status_values
        ]
    if requested_run_id:
        attempts.sort(key=lambda item: int(item.get("attempt") or 0))
    else:
        attempts.sort(
            key=lambda item: item.get("updated_at") or item.get("created_at") or "",
            reverse=True,
        )
    return attempts[offset:offset + limit]


def claim_next_job(
    *,
    queue_name: str = DEFAULT_QUEUE_NAME,
    worker_id: str | None = None,
    operator: str | None = None,
) -> Optional[Dict[str, Any]]:
    if _sqlite_file() is None:
        return None
    state = _load_state()
    _mirror_state_to_sqlite(state)
    _ensure_sqlite_table()

    actor = _clean_operator(operator)
    claim_worker_id = str(worker_id or DEFAULT_WORKER_ID)
    queue = str(queue_name or DEFAULT_QUEUE_NAME)
    claimed: Dict[str, Any] | None = None
    claimed_at = _now()

    with _sqlite_connect() as conn:
        conn.isolation_level = None
        conn.execute("BEGIN IMMEDIATE")
        try:
            rows = conn.execute(
                """
                SELECT * FROM analysis_jobs
                WHERE queue_name = ? AND status = 'QUEUED'
                ORDER BY priority DESC, COALESCE(queued_at, created_at, '') ASC, created_at ASC
                LIMIT 50
                """,
                (queue,),
            ).fetchall()
            for row in rows:
                candidate = _row_to_job(row)
                active_count = int(
                    conn.execute(
                        """
                        SELECT COUNT(*) FROM analysis_jobs
                        WHERE queue_name = ?
                          AND concurrency_group = ?
                          AND status = 'RUNNING'
                          AND run_id != ?
                        """,
                        (
                            candidate["queue_name"],
                            candidate["concurrency_group"],
                            candidate["run_id"],
                        ),
                    ).fetchone()[0]
                )
                if active_count >= int(candidate.get("concurrency_limit") or DEFAULT_CONCURRENCY_LIMIT):
                    continue

                candidate["status"] = "RUNNING"
                candidate["started_at"] = candidate.get("started_at") or claimed_at
                candidate["updated_at"] = claimed_at
                candidate["worker_id"] = claim_worker_id
                candidate["worker_heartbeat_at"] = claimed_at
                candidate["last_operator"] = actor
                candidate["operator"] = candidate.get("operator") or actor
                candidate.setdefault("history", []).append(
                    {
                        "event": "JOB_CLAIMED",
                        "at": claimed_at,
                        "attempt": candidate.get("attempt", 0),
                        "operator": actor,
                        "worker_id": claim_worker_id,
                    }
                )
                normalized = _normalize_job(candidate)
                params = {
                    "run_id": normalized["run_id"],
                    "status": normalized["status"],
                    "worker_id": normalized["worker_id"],
                    "worker_heartbeat_at": normalized["worker_heartbeat_at"],
                    "lease_expires_at": normalized["lease_expires_at"],
                    "lease_status": normalized["lease_status"],
                    "lease_seconds": normalized["lease_seconds"],
                    "last_operator": normalized["last_operator"],
                    "operator": normalized["operator"],
                    "updated_at": normalized["updated_at"],
                    "started_at": normalized["started_at"],
                    "history_json": _encode_json(normalized["history"], []),
                    "recovery_json": _encode_json(normalized["recovery"], {}),
                    "payload_json": _encode_json(normalized, {}),
                }
                result = conn.execute(
                    """
                    UPDATE analysis_jobs
                    SET status = :status,
                        worker_id = :worker_id,
                        worker_heartbeat_at = :worker_heartbeat_at,
                        lease_expires_at = :lease_expires_at,
                        lease_status = :lease_status,
                        lease_seconds = :lease_seconds,
                        last_operator = :last_operator,
                        operator = :operator,
                        updated_at = :updated_at,
                        started_at = :started_at,
                        history_json = :history_json,
                        recovery_json = :recovery_json,
                        payload_json = :payload_json
                    WHERE run_id = :run_id AND status = 'QUEUED'
                    """,
                    params,
                )
                if result.rowcount == 1:
                    _upsert_attempt_with_conn(conn, normalized)
                    claimed = normalized
                    break
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    if claimed is None:
        return None
    state = _load_state()
    return _persist_job_state(state, claimed["run_id"], claimed)


def _persist_job_state(state: Dict[str, Any], run_id: str, job: Dict[str, Any]) -> Dict[str, Any]:
    normalized = _normalize_job(job)
    state["jobs"][run_id] = normalized
    _save_state(state)
    _mirror_job_to_sqlite(normalized)
    return normalized


def _existing_job(state: Dict[str, Any], run_id: str) -> Dict[str, Any] | None:
    job = state.get("jobs", {}).get(run_id)
    if isinstance(job, dict):
        return job
    try:
        return get_sqlite_job(run_id)
    except (OSError, sqlite3.Error) as exc:
        if _is_sqlite_locked(exc):
            logger.warning("Skipped loading existing analysis job %s from locked SQLite mirror.", run_id)
            return None
        logger.exception("Failed to load existing analysis job %s from SQLite.", run_id)
    return None


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
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


def _job_activity_at(job: Dict[str, Any]) -> Optional[datetime]:
    for key in ("worker_heartbeat_at", "updated_at", "started_at", "created_at"):
        parsed = _parse_timestamp(job.get(key))
        if parsed is not None:
            return parsed
    return None


def _base_job(run_id: str) -> Dict[str, Any]:
    created_at = _now()
    return {
        "job_id": f"JOB_{run_id}",
        "run_id": run_id,
        "status": "PENDING",
        "attempt": 0,
        "max_attempts": 3,
        "queue_name": DEFAULT_QUEUE_NAME,
        "priority": 0,
        "concurrency_group": DEFAULT_CONCURRENCY_GROUP,
        "concurrency_limit": DEFAULT_CONCURRENCY_LIMIT,
        "worker_id": "",
        "worker_heartbeat_at": "",
        "lease_expires_at": "",
        "lease_status": "UNCLAIMED",
        "lease_seconds": _lease_seconds(),
        "created_at": created_at,
        "updated_at": created_at,
        "queued_at": "",
        "started_at": "",
        "finished_at": "",
        "cancel_requested_at": "",
        "operator": DEFAULT_OPERATOR,
        "last_operator": DEFAULT_OPERATOR,
        "last_error": "",
        "failed_node_id": "",
        "retry_from_node_id": "",
        "resume_from_node_id": "",
        "retry_of_job_id": "",
        "same_input_retry": False,
        "history": [],
    }


def get_job(run_id: str) -> Optional[Dict[str, Any]]:
    state = _load_state()
    json_job = state.get("jobs", {}).get(run_id)
    try:
        sqlite_job = get_sqlite_job(run_id)
    except (OSError, sqlite3.Error) as exc:
        if _is_sqlite_locked(exc):
            logger.warning("Skipped reading analysis job %s from locked SQLite mirror.", run_id)
        else:
            logger.exception("Failed to read analysis job %s from SQLite.", run_id)
        sqlite_job = None
    if isinstance(json_job, dict) and _json_job_is_newer_or_equal(json_job, sqlite_job):
        _mirror_job_to_sqlite(json_job)
        try:
            sqlite_job = get_sqlite_job(run_id)
        except (OSError, sqlite3.Error) as exc:
            if _is_sqlite_locked(exc):
                logger.warning("Skipped rereading analysis job %s from locked SQLite mirror.", run_id)
            else:
                logger.exception("Failed to reread analysis job %s from SQLite.", run_id)
            sqlite_job = None
    return _sanitize_active_job(sqlite_job or json_job)


def list_jobs(limit: int = 100, offset: int = 0, statuses: Iterable[str] | None = None) -> List[Dict[str, Any]]:
    state = _load_state()
    _mirror_state_to_sqlite(state)
    limit = max(min(int(limit or 100), 1000), 1)
    offset = max(int(offset or 0), 0)
    status_values = [str(status).upper() for status in (statuses or []) if str(status or "").strip()]
    try:
        sqlite_jobs = list_sqlite_jobs(limit=limit, offset=offset, statuses=status_values)
        if _sqlite_file() is not None:
            return sqlite_jobs
    except (OSError, sqlite3.Error) as exc:
        if _is_sqlite_locked(exc):
            logger.warning("Skipped listing analysis jobs from locked SQLite mirror; falling back to JSON.")
        else:
            logger.exception("Failed to list analysis jobs from SQLite; falling back to JSON.")
    jobs = list(state.get("jobs", {}).values())
    if status_values:
        jobs = [job for job in jobs if str(job.get("status") or "").upper() in status_values]
    jobs.sort(key=lambda item: item.get("updated_at") or item.get("created_at") or "", reverse=True)
    return [_sanitize_active_job(job) or job for job in jobs[offset:offset + limit]]


def summarize_jobs(limit: int = 100, offset: int = 0, statuses: Iterable[str] | None = None) -> Dict[str, Any]:
    state = _load_state()
    _mirror_state_to_sqlite(state)
    limit = max(min(int(limit or 100), 1000), 1)
    offset = max(int(offset or 0), 0)
    status_values = [str(status).upper() for status in (statuses or []) if str(status or "").strip()]
    source = "json"
    external_queue = external_queue_status()
    try:
        sqlite_summary = summarize_sqlite_jobs(statuses=status_values)
        if _sqlite_file() is not None and sqlite_summary:
            source = "sqlite"
            filtered_count = int(sqlite_summary.get("filtered_count") or 0)
            return {
                **sqlite_summary,
                "limit": limit,
                "offset": offset,
                "has_more": offset + limit < filtered_count,
                "source": source,
                "external_queue_status": external_queue,
            }
    except (OSError, sqlite3.Error) as exc:
        if _is_sqlite_locked(exc):
            logger.warning("Skipped summarizing analysis jobs from locked SQLite mirror; falling back to JSON.")
        else:
            logger.exception("Failed to summarize analysis jobs from SQLite; falling back to JSON.")
    jobs = list(state.get("jobs", {}).values())
    counts_by_status: dict[str, int] = {}
    for job in jobs:
        status = str(job.get("status") or "UNKNOWN").upper()
        counts_by_status[status] = counts_by_status.get(status, 0) + 1
    if status_values:
        filtered_count = sum(
            1 for job in jobs
            if str(job.get("status") or "").upper() in status_values
        )
    else:
        filtered_count = len(jobs)
    return {
        "total_count": len(jobs),
        "filtered_count": filtered_count,
        "counts_by_status": counts_by_status,
        "statuses": status_values,
        "limit": limit,
        "offset": offset,
        "has_more": offset + limit < filtered_count,
        "source": source,
        "external_queue_status": external_queue,
    }


def reconcile_stale_jobs(
    *,
    stale_after_seconds: int,
    now: datetime | None = None,
    active_run_ids: set[str] | None = None,
    operator: str | None = None,
) -> List[Dict[str, Any]]:
    state = _load_state()
    jobs = state.get("jobs", {})
    if not isinstance(jobs, dict):
        return []
    _mirror_state_to_sqlite(state)
    try:
        for sqlite_job in list_sqlite_jobs(limit=1000, statuses=STALE_RECOVERABLE_JOB_STATUSES):
            run_id = str(sqlite_job.get("run_id") or "")
            json_job = jobs.get(run_id)
            if not isinstance(json_job, dict) or not _json_job_is_newer_or_equal(json_job, sqlite_job):
                jobs[run_id] = sqlite_job
    except (OSError, sqlite3.Error) as exc:
        if _is_sqlite_locked(exc):
            logger.warning("Skipped locked SQLite jobs during stale reconciliation.")
        else:
            logger.exception("Failed to include SQLite jobs during stale reconciliation.")
    active_run_ids = active_run_ids or set()
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    actor = _clean_operator(operator or "watchdog")
    stale_after_seconds = max(int(stale_after_seconds or 1), 1)
    recovered: List[Dict[str, Any]] = []

    for run_id, existing in list(jobs.items()):
        if run_id in active_run_ids or not isinstance(existing, dict):
            continue
        status_before = str(existing.get("status") or "PENDING")
        if status_before not in STALE_RECOVERABLE_JOB_STATUSES:
            continue
        last_activity = _job_activity_at(existing)
        if last_activity is not None and (now - last_activity).total_seconds() < stale_after_seconds:
            continue

        job = dict(existing)
        recovered_at = _now()
        last_activity_text = existing.get("updated_at") or existing.get("started_at") or existing.get("created_at") or ""
        reason = (
            f"Analysis job recovered as stale: status stayed {status_before} "
            f"without backend activity since {last_activity_text or 'unknown time'}."
        )
        job["status"] = "STALE"
        job["updated_at"] = recovered_at
        job["finished_at"] = recovered_at
        job["last_operator"] = actor
        job["operator"] = job.get("operator") or actor
        job["last_error"] = reason
        job["failed_node_id"] = ""
        job["stale_reason"] = reason
        job["recovery"] = {
            "statusBefore": status_before,
            "statusAfter": "STALE",
            "reason": reason,
            "lastActivityAt": last_activity_text,
            "recoveredAt": recovered_at,
            "staleAfterSeconds": stale_after_seconds,
            "previousLastError": existing.get("last_error", ""),
        }
        job.setdefault("history", []).append(
            {
                "event": "JOB_STALE",
                "at": recovered_at,
                "attempt": job.get("attempt", 0),
                "failed_node_id": job.get("failed_node_id", ""),
                "retry_from_node_id": job.get("retry_from_node_id", ""),
                "operator": actor,
                "reason": reason,
                "status_before": status_before,
            }
        )
        jobs[run_id] = job
        recovered.append(job)

    if recovered:
        state["jobs"] = jobs
        _save_state(state)
        for job in recovered:
            _mirror_job_to_sqlite(job)
    return recovered


def _clean_operator(operator: str | None) -> str:
    value = str(operator or "").strip()
    return value[:80] if value else DEFAULT_OPERATOR


def start_job(run_id: str, *, retry_from_node_id: str = "", operator: str | None = None) -> Dict[str, Any]:
    state = _load_state()
    job = dict(_existing_job(state, run_id) or _base_job(run_id))
    if job.get("status") not in TERMINAL_JOB_STATUSES and job.get("status") in {"RUNNING", "QUEUED"}:
        _mirror_job_to_sqlite(job)
        return job
    actor = _clean_operator(operator)
    previous_job_id = job.get("job_id", "")
    queued_at = _now()
    job["job_id"] = f"JOB_{run_id}_{int(job.get('attempt') or 0) + 1}"
    job["status"] = "QUEUED"
    job["attempt"] = int(job.get("attempt") or 0) + 1
    job["updated_at"] = queued_at
    job["queued_at"] = queued_at
    job["started_at"] = ""
    job["finished_at"] = ""
    job["cancel_requested_at"] = ""
    job["worker_id"] = ""
    job["worker_heartbeat_at"] = ""
    job["last_error"] = ""
    job["failed_node_id"] = ""
    job["stale_reason"] = ""
    job["retry_of_job_id"] = previous_job_id if previous_job_id and previous_job_id != job["job_id"] else ""
    job["retry_from_node_id"] = retry_from_node_id or ""
    job["resume_from_node_id"] = retry_from_node_id or ""
    job["same_input_retry"] = bool(retry_from_node_id)
    job["operator"] = job.get("operator") or actor
    job["last_operator"] = actor
    job.setdefault("history", []).append(
        {
            "event": "JOB_QUEUED",
            "at": job["updated_at"],
            "attempt": job["attempt"],
            "retry_from_node_id": job["retry_from_node_id"],
            "operator": actor,
        }
    )
    return _persist_job_state(state, run_id, job)


def mark_running(run_id: str, *, operator: str | None = None, worker_id: str | None = None) -> Dict[str, Any]:
    started_at = _now()
    resolved_worker_id = str(worker_id or DEFAULT_WORKER_ID)
    return _update_job(
        run_id,
        "RUNNING",
        operator=operator,
        started_at=started_at,
        worker_id=resolved_worker_id,
        worker_heartbeat_at=started_at,
        lease_worker_id=resolved_worker_id,
    )


def request_cancel(run_id: str, *, operator: str | None = None) -> Dict[str, Any]:
    return _update_job(run_id, "CANCEL_REQUESTED", operator=operator, cancel_requested_at=_now())


def mark_cancelled(
    run_id: str,
    reason: str = "cancelled_by_user",
    *,
    operator: str | None = None,
    worker_id: str | None = None,
) -> Dict[str, Any]:
    finished_at = _now()
    return _update_job(
        run_id,
        "CANCELLED",
        operator=operator,
        finished_at=finished_at,
        worker_heartbeat_at=finished_at,
        last_error=reason,
        lease_worker_id=worker_id,
    )


def mark_completed(run_id: str, *, operator: str | None = None, worker_id: str | None = None) -> Dict[str, Any]:
    finished_at = _now()
    return _update_job(
        run_id,
        "COMPLETED",
        operator=operator,
        finished_at=finished_at,
        worker_heartbeat_at=finished_at,
        last_error="",
        lease_worker_id=worker_id,
    )


def mark_failed(
    run_id: str,
    error: str,
    failed_node_id: str = "",
    *,
    operator: str | None = None,
    worker_id: str | None = None,
) -> Dict[str, Any]:
    finished_at = _now()
    return _update_job(
        run_id,
        "FAILED",
        operator=operator,
        finished_at=finished_at,
        worker_heartbeat_at=finished_at,
        last_error=error,
        failed_node_id=failed_node_id,
        lease_worker_id=worker_id,
    )


def mark_stale(run_id: str, reason: str, failed_node_id: str = "", *, operator: str | None = None) -> Dict[str, Any]:
    finished_at = _now()
    return _update_job(
        run_id,
        "STALE",
        operator=operator,
        finished_at=finished_at,
        worker_heartbeat_at=finished_at,
        last_error=reason,
        stale_reason=reason,
        failed_node_id=failed_node_id,
    )


def record_worker_heartbeat(
    run_id: str,
    *,
    worker_id: str | None = None,
    operator: str | None = None,
    metrics: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    state = _load_state()
    job = dict(_existing_job(state, run_id) or _base_job(run_id))
    if job.get("status") in TERMINAL_JOB_STATUSES:
        _mirror_job_to_sqlite(job)
        return job
    actor = _clean_operator(operator or job.get("last_operator") or job.get("operator"))
    rejected = _reject_if_worker_mismatch(
        job,
        worker_id=worker_id,
        actor=actor,
        event="WORKER_HEARTBEAT",
    )
    if rejected is not None:
        return rejected
    heartbeat_at = _now()
    job["status"] = "RUNNING"
    job["updated_at"] = heartbeat_at
    job["worker_id"] = str(worker_id or job.get("worker_id") or DEFAULT_WORKER_ID)
    job["worker_heartbeat_at"] = heartbeat_at
    job["last_operator"] = actor
    job["heartbeat_metrics"] = metrics or {}
    job.setdefault("history", []).append(
        {
            "event": "WORKER_HEARTBEAT",
            "at": heartbeat_at,
            "attempt": job.get("attempt", 0),
            "operator": actor,
            "worker_id": job["worker_id"],
            "metrics": metrics or {},
        }
    )
    return _persist_job_state(state, run_id, job)


def _update_job(run_id: str, status: str, operator: str | None = None, **updates: Any) -> Dict[str, Any]:
    state = _load_state()
    job = dict(_existing_job(state, run_id) or _base_job(run_id))
    actor = _clean_operator(operator or job.get("last_operator") or job.get("operator"))
    lease_worker_id = updates.pop("lease_worker_id", None)
    rejected = _reject_if_worker_mismatch(
        job,
        worker_id=lease_worker_id,
        actor=actor,
        event=f"JOB_{status}",
    )
    if rejected is not None:
        return rejected
    status_before = str(job.get("status") or "PENDING")
    job["status"] = status
    job["updated_at"] = _now()
    job["last_operator"] = actor
    job["operator"] = job.get("operator") or actor
    for key, value in updates.items():
        job[key] = value
    job.setdefault("history", []).append(
        {
            "event": f"JOB_{status}",
            "at": job["updated_at"],
            "attempt": job.get("attempt", 0),
            "failed_node_id": job.get("failed_node_id", ""),
            "retry_from_node_id": job.get("retry_from_node_id", ""),
            "operator": actor,
            "status_before": status_before,
            "worker_id": job.get("worker_id", ""),
            "worker_heartbeat_at": job.get("worker_heartbeat_at", ""),
        }
    )
    return _persist_job_state(state, run_id, job)
