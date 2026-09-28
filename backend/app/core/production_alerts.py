from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import request as url_request
from urllib.error import HTTPError, URLError


DEFAULT_MAX_EVENTS = 500
EXPORT_SCHEMA_VERSION = "production_alert_outbox_export_v1"
EXPORT_HANDOFF_SCHEMA_VERSION = "production_alert_outbox_export_handoff_v1"
EXPORT_HANDOFF_MANIFEST_SCHEMA_VERSION = "production_alert_outbox_export_handoff_manifest_v1"
EXPORT_SHIPPER_STATUS_SCHEMA_VERSION = "production_alert_outbox_export_shipper_status_v1"
ALERT_RULE_POLICY_SCHEMA_VERSION = "production_alert_rule_policy_v1"
ALERT_RULE_PROVIDER_ACCEPTANCE_SCHEMA_VERSION = "production_alert_rule_provider_acceptance_v1"
EXPORT_SHIPPER_STATUS_FILE = "shipper_status.json"
SECRET_PATTERN = re.compile(r"(api[_-]?key|token|secret|authorization)=([^,\s]+)", re.IGNORECASE)
ALLOWED_SHIPPER_STATUSES = {"DELIVERED", "PENDING", "FAILED", "UNKNOWN"}
ALLOWED_ALERT_RULE_PROVIDER_ACCEPTANCE_STATUSES = {"ACCEPTED", "PENDING", "FAILED", "UNKNOWN"}
ALERT_RULE_POLICY_MAX_BYTES = 65536
ALERT_RULE_PROVIDER_ACCEPTANCE_MAX_BYTES = 65536


DEFAULT_ALERT_RULES = [
    {
        "id": "critical_ops_page",
        "severity": "critical",
        "metric": "*",
        "routing_key": "ops-critical",
        "escalation_target": "admin_oncall",
        "dedupe_window_seconds": 3600,
    },
    {
        "id": "warning_ops_notify",
        "severity": "warning",
        "metric": "*",
        "routing_key": "ops-warning",
        "escalation_target": "operator_review",
        "dedupe_window_seconds": 1800,
    },
    {
        "id": "info_record_only",
        "severity": "info",
        "metric": "*",
        "routing_key": "ops-info",
        "escalation_target": "record_only",
        "dedupe_window_seconds": 3600,
    },
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_outbox_file() -> Path:
    return Path(__file__).resolve().parents[1] / "storage" / "production_alerts.jsonl"


def _export_handoff_dir() -> Path | None:
    configured = os.getenv("PRODUCTION_ALERT_EXPORT_HANDOFF_DIR", "").strip()
    return Path(configured).expanduser() if configured else None


def _external_webhook_url() -> str:
    return os.getenv("PRODUCTION_ALERT_WEBHOOK_URL", "").strip()


def _external_webhook_timeout_seconds() -> float:
    raw_value = os.getenv("PRODUCTION_ALERT_WEBHOOK_TIMEOUT_SECONDS", "")
    try:
        value = float(raw_value) if raw_value else 3.0
    except ValueError:
        value = 3.0
    return max(0.5, min(value, 30.0))


def _external_webhook_max_attempts() -> int:
    raw_value = os.getenv("PRODUCTION_ALERT_WEBHOOK_MAX_ATTEMPTS", "")
    try:
        value = int(raw_value) if raw_value else 1
    except ValueError:
        value = 1
    return max(1, min(value, 5))


def _external_webhook_retry_backoff_seconds() -> float:
    raw_value = os.getenv("PRODUCTION_ALERT_WEBHOOK_RETRY_BACKOFF_SECONDS", "")
    try:
        value = float(raw_value) if raw_value else 0.0
    except ValueError:
        value = 0.0
    return max(0.0, min(value, 5.0))


def _external_provider_status() -> dict[str, Any]:
    webhook_url = _external_webhook_url()
    return {
        "external_delivery_enabled": bool(webhook_url),
        "external_provider": "generic_webhook" if webhook_url else "disabled",
        "external_delivery_status": "ready" if webhook_url else "disabled",
        "external_delivery_attempt_limit": _external_webhook_max_attempts() if webhook_url else 0,
        "external_delivery_retry_backoff_seconds": _external_webhook_retry_backoff_seconds() if webhook_url else 0.0,
    }


def _alert_rule_policy_file() -> Path | None:
    configured = os.getenv("PRODUCTION_ALERT_RULE_POLICY_FILE", "").strip()
    return Path(configured).expanduser() if configured else None


def _alert_rule_provider_acceptance_file() -> Path | None:
    configured = os.getenv("PRODUCTION_ALERT_RULE_PROVIDER_ACCEPTANCE_FILE", "").strip()
    return Path(configured).expanduser() if configured else None


def _safe_text(value: Any, limit: int = 320) -> str:
    text = "" if value is None else str(value).strip()
    text = SECRET_PATTERN.sub(r"\1=[REDACTED]", text)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _safe_scalar(value: Any) -> Any:
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _safe_text(value, 160)


def _safe_text_list(value: Any, *, limit: int = 50, item_limit: int = 120) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value[:limit]:
        text = _safe_text(item, item_limit)
        if text:
            items.append(text)
    return items


def _safe_dict(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    safe: dict[str, Any] = {}
    for key, raw in list(value.items())[:20]:
        safe_key = _safe_text(key, 80)
        if isinstance(raw, dict):
            safe[safe_key] = _safe_dict(raw)
        elif isinstance(raw, list):
            safe[safe_key] = [_safe_scalar(item) for item in raw[:20]]
        else:
            safe[safe_key] = _safe_scalar(raw)
    return safe


def _severity(value: Any) -> str:
    text = _safe_text(value, 24).lower()
    return text if text in {"info", "warning", "critical"} else "warning"


def _safe_int(value: Any, *, default: int = 0, minimum: int = 0, maximum: int = 86400) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = _safe_text(value, 16).lower()
    return text in {"1", "true", "yes", "y", "ready", "enabled"}


def _normalize_alert_rule(rule: Any, *, fallback_id: str) -> dict[str, Any] | None:
    if not isinstance(rule, dict):
        return None
    rule_id = _safe_text(rule.get("id"), 96) or fallback_id
    severity = _safe_text(rule.get("severity"), 24).lower() or "*"
    if severity not in {"critical", "warning", "info", "*"}:
        severity = "*"
    metric = _safe_text(rule.get("metric"), 120) or "*"
    return {
        "id": rule_id,
        "severity": severity,
        "metric": metric,
        "routing_key": _safe_text(rule.get("routing_key"), 120) or "ops-default",
        "escalation_target": _safe_text(rule.get("escalation_target"), 120) or "operator_review",
        "dedupe_window_seconds": _safe_int(
            rule.get("dedupe_window_seconds"),
            default=1800,
            minimum=60,
            maximum=86400,
        ),
    }


def _default_alert_rules() -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    for index, rule in enumerate(DEFAULT_ALERT_RULES):
        normalized = _normalize_alert_rule(rule, fallback_id=f"default_rule_{index + 1}")
        if normalized:
            rules.append(normalized)
    return rules


def _alert_rule_policy_base() -> dict[str, Any]:
    sidecar_file = _alert_rule_policy_file()
    base = {
        "schema": ALERT_RULE_POLICY_SCHEMA_VERSION,
        "policy_id": "builtin_default",
        "checked": False,
        "configured": False,
        "status": "DEFAULT",
        "source": "builtin_default",
        "provider": _external_provider_status().get("external_provider", "disabled"),
        "sidecar_file": "",
        "rule_count": 0,
        "rules": _default_alert_rules(),
        "message": "using builtin local alert routing policy",
        "issues": [],
    }
    base["rule_count"] = len(base["rules"])
    if sidecar_file is None:
        return base

    base.update(
        {
            "checked": True,
            "configured": True,
            "status": "NOT_REPORTED",
            "sidecar_file": str(sidecar_file),
            "message": "alert rule policy sidecar file was not reported",
            "issues": ["sidecar_file_missing"],
        }
    )
    if not sidecar_file.exists():
        return base

    try:
        if sidecar_file.stat().st_size > ALERT_RULE_POLICY_MAX_BYTES:
            return {
                **base,
                "status": "INVALID",
                "message": "alert rule policy sidecar exceeds the read limit",
                "issues": ["sidecar_file_too_large"],
            }
        payload = json.loads(sidecar_file.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            **base,
            "status": "INVALID",
            "message": _safe_text(f"invalid alert rule policy sidecar: {exc}", 240),
            "issues": ["sidecar_file_invalid"],
        }

    if not isinstance(payload, dict) or payload.get("schema") != ALERT_RULE_POLICY_SCHEMA_VERSION:
        return {
            **base,
            "status": "INVALID",
            "message": "alert rule policy sidecar schema mismatch",
            "issues": ["sidecar_schema_mismatch"],
        }

    raw_rules = payload.get("rules")
    rules: list[dict[str, Any]] = []
    if isinstance(raw_rules, list):
        for index, rule in enumerate(raw_rules[:50]):
            normalized = _normalize_alert_rule(rule, fallback_id=f"sidecar_rule_{index + 1}")
            if normalized:
                rules.append(normalized)
    if not rules:
        return {
            **base,
            "status": "INVALID",
            "source": _safe_text(payload.get("source"), 120) or "deployment_sidecar",
            "provider": _safe_text(payload.get("provider"), 120) or base["provider"],
            "message": "alert rule policy sidecar has no usable rules",
            "issues": ["sidecar_rules_missing"],
        }

    return {
        **base,
        "status": "READY",
        "policy_id": _safe_text(payload.get("policy_id"), 120) or "deployment_sidecar",
        "source": _safe_text(payload.get("source"), 120) or "deployment_sidecar",
        "provider": _safe_text(payload.get("provider"), 120) or base["provider"],
        "rule_count": len(rules),
        "rules": rules,
        "message": _safe_text(payload.get("message"), 240) or "deployment alert routing policy loaded",
        "issues": [
            _safe_text(issue, 120)
            for issue in (payload.get("issues") if isinstance(payload.get("issues"), list) else [])
        ][:10],
    }


def _alert_rule_ids(policy: dict[str, Any]) -> list[str]:
    rules = policy.get("rules") if isinstance(policy.get("rules"), list) else []
    return [
        _safe_text(rule.get("id"), 96)
        for rule in rules
        if isinstance(rule, dict) and _safe_text(rule.get("id"), 96)
    ]


def _alert_rule_provider_acceptance(policy: dict[str, Any]) -> dict[str, Any]:
    sidecar_file = _alert_rule_provider_acceptance_file()
    policy_id = _safe_text(policy.get("policy_id"), 120)
    policy_rule_ids = _alert_rule_ids(policy)
    base = {
        "schema": ALERT_RULE_PROVIDER_ACCEPTANCE_SCHEMA_VERSION,
        "checked": False,
        "configured": False,
        "reported": False,
        "status": "NOT_CONFIGURED",
        "sidecar_file": "",
        "source": "",
        "provider": "",
        "policy_id": policy_id,
        "provider_policy_id": "",
        "rules_accepted": 0,
        "rules_total": len(policy_rule_ids),
        "accepted_rule_ids": [],
        "missing_rule_ids": policy_rule_ids,
        "policy_id_matches": False,
        "rule_count_matches": False,
        "accepted_rule_ids_match": False,
        "matches_policy": False,
        "last_synced_at": "",
        "routing_key": "",
        "message": "alert rule provider acceptance sidecar is not configured",
        "issues": [],
    }
    if sidecar_file is None:
        return base

    base.update(
        {
            "checked": True,
            "configured": True,
            "status": "NOT_REPORTED",
            "sidecar_file": str(sidecar_file),
            "message": "alert rule provider acceptance sidecar file was not reported",
            "issues": ["sidecar_file_missing"],
        }
    )
    if not sidecar_file.exists():
        return base

    try:
        if sidecar_file.stat().st_size > ALERT_RULE_PROVIDER_ACCEPTANCE_MAX_BYTES:
            return {
                **base,
                "reported": True,
                "status": "INVALID",
                "message": "alert rule provider acceptance sidecar exceeds the read limit",
                "issues": ["sidecar_file_too_large"],
            }
        payload = json.loads(sidecar_file.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            **base,
            "reported": True,
            "status": "INVALID",
            "message": _safe_text(f"invalid alert rule provider acceptance sidecar: {exc}", 240),
            "issues": ["sidecar_file_invalid"],
        }

    if not isinstance(payload, dict) or payload.get("schema") != ALERT_RULE_PROVIDER_ACCEPTANCE_SCHEMA_VERSION:
        return {
            **base,
            "reported": True,
            "status": "INVALID",
            "message": "alert rule provider acceptance sidecar schema mismatch",
            "issues": ["sidecar_schema_mismatch"],
        }

    raw_status = _safe_text(payload.get("status"), 32).upper() or "UNKNOWN"
    status = raw_status if raw_status in ALLOWED_ALERT_RULE_PROVIDER_ACCEPTANCE_STATUSES else "UNKNOWN"
    reported_policy_id = _safe_text(payload.get("policy_id"), 120)
    provider_policy_id = _safe_text(payload.get("provider_policy_id"), 120)
    accepted_rule_ids = _safe_text_list(payload.get("accepted_rule_ids") or payload.get("rule_ids"), limit=100, item_limit=96)
    reported_rules_total = _safe_int(
        payload.get("rules_total"),
        default=len(policy_rule_ids),
        minimum=0,
        maximum=500,
    )
    reported_rules_accepted = _safe_int(
        payload.get("rules_accepted"),
        default=len(accepted_rule_ids),
        minimum=0,
        maximum=reported_rules_total if reported_rules_total else 500,
    )
    missing_rule_ids = [
        rule_id for rule_id in policy_rule_ids
        if accepted_rule_ids and rule_id not in set(accepted_rule_ids)
    ]
    policy_id_matches = bool(policy_id and reported_policy_id and policy_id == reported_policy_id)
    rule_count_matches = reported_rules_total == len(policy_rule_ids)
    if accepted_rule_ids:
        accepted_rule_ids_match = not missing_rule_ids
    else:
        accepted_rule_ids_match = reported_rules_accepted >= len(policy_rule_ids)
    matches_policy = policy_id_matches and rule_count_matches and accepted_rule_ids_match
    issues = [
        _safe_text(issue, 120)
        for issue in (payload.get("issues") if isinstance(payload.get("issues"), list) else [])
    ][:10]
    if raw_status != status:
        issues.append("unknown_status_reported")
    if not policy_id_matches:
        issues.append("policy_id_mismatch")
    if not rule_count_matches:
        issues.append("rule_count_mismatch")
    if not accepted_rule_ids_match:
        issues.append("accepted_rule_ids_mismatch")

    return {
        **base,
        "reported": True,
        "status": status,
        "source": _safe_text(payload.get("source"), 120) or "deployment_provider",
        "provider": _safe_text(payload.get("provider"), 120),
        "policy_id": reported_policy_id or policy_id,
        "provider_policy_id": provider_policy_id,
        "rules_accepted": reported_rules_accepted,
        "rules_total": reported_rules_total,
        "accepted_rule_ids": accepted_rule_ids,
        "missing_rule_ids": missing_rule_ids,
        "policy_id_matches": policy_id_matches,
        "rule_count_matches": rule_count_matches,
        "accepted_rule_ids_match": accepted_rule_ids_match,
        "matches_policy": matches_policy,
        "last_synced_at": _safe_text(payload.get("last_synced_at") or payload.get("reported_at"), 80),
        "routing_key": _safe_text(payload.get("routing_key"), 120),
        "message": _safe_text(payload.get("message"), 240),
        "issues": issues[:10],
    }


def _alert_rule_policy() -> dict[str, Any]:
    policy = _alert_rule_policy_base()
    return {
        **policy,
        "provider_acceptance": _alert_rule_provider_acceptance(policy),
    }


def _rule_matches_alert(rule: dict[str, Any], *, severity: str, metric: str) -> bool:
    rule_severity = str(rule.get("severity") or "*").lower()
    rule_metric = str(rule.get("metric") or "*")
    return (
        (rule_severity == "*" or rule_severity == severity)
        and (rule_metric == "*" or rule_metric == metric)
    )


def _select_alert_rule(alert: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    policy = _alert_rule_policy()
    severity = _severity(alert.get("severity"))
    metric = _safe_text(alert.get("metric"), 120)
    rules = policy.get("rules") if isinstance(policy.get("rules"), list) else []
    for rule in rules:
        if isinstance(rule, dict) and _rule_matches_alert(rule, severity=severity, metric=metric):
            return policy, rule
    fallback_rule = _normalize_alert_rule(
        {
            "id": "fallback_ops_review",
            "severity": "*",
            "metric": "*",
            "routing_key": "ops-review",
            "escalation_target": "operator_review",
            "dedupe_window_seconds": 1800,
        },
        fallback_id="fallback_ops_review",
    ) or {}
    return policy, fallback_rule


def _fingerprint(alert: dict[str, Any]) -> str:
    parts = [
        _severity(alert.get("severity")),
        _safe_text(alert.get("metric"), 80),
        _safe_text(alert.get("window"), 80),
        _safe_text(alert.get("message"), 240),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _export_checksum(events: list[dict[str, Any]]) -> str:
    encoded = json.dumps(events, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class ProductionAlertOutbox:
    """Local durable alert outbox for production health alerts.

    It always records to a JSONL file. Optional webhook delivery is disabled
    unless PRODUCTION_ALERT_WEBHOOK_URL is configured.
    """

    def __init__(self, max_events: int = DEFAULT_MAX_EVENTS) -> None:
        self._max_events = max(50, int(max_events or DEFAULT_MAX_EVENTS))
        self._lock = threading.RLock()

    def outbox_file(self) -> Path:
        configured = os.getenv("PRODUCTION_ALERT_OUTBOX_FILE", "").strip()
        return Path(configured).expanduser() if configured else _default_outbox_file()

    def status(self, *, limit: int = 20) -> dict[str, Any]:
        events = self._read_events()
        latest = events[-max(0, min(limit, 100)) :] if limit else []
        counts: dict[str, int] = {}
        for event in events:
            severity = _severity(event.get("severity"))
            counts[severity] = counts.get(severity, 0) + 1
        provider = _external_provider_status()
        return {
            "generated_at": _now_iso(),
            "enabled": True,
            "channel": "local_file_outbox",
            **provider,
            "alert_rule_policy": _alert_rule_policy(),
            "external_aggregation_ready": True,
            "export_endpoint": "/api/ops/alerts/export",
            "export_schema": EXPORT_SCHEMA_VERSION,
            "outbox_file": str(self.outbox_file()),
            "queue_size": len(events),
            "last_event_at": _safe_text(events[-1].get("created_at")) if events else "",
            "counts_by_severity": counts,
            "retention_policy": self.retention_policy(),
            "redaction_policy": self.redaction_policy(),
            "handoff_status": self.handoff_status(),
            "latest": list(reversed(latest)),
        }

    def handoff_status(self) -> dict[str, Any]:
        handoff_dir = _export_handoff_dir()
        if handoff_dir is None:
            inventory = self._handoff_inventory_status(None)
            return {
                "schema": "production_alert_outbox_export_handoff_status_v1",
                "configured": False,
                "status": "NOT_CONFIGURED",
                "reason": "PRODUCTION_ALERT_EXPORT_HANDOFF_DIR is not configured.",
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
            "schema": "production_alert_outbox_export_handoff_status_v1",
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
            "schema": "production_alert_outbox_export_handoff_inventory_v1",
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

    def export_bundle(self, *, limit: int = 100) -> dict[str, Any]:
        events = self._read_events()
        export_limit = max(1, min(int(limit or 100), self._max_events, 1000))
        exported = events[-export_limit:]
        provider = _external_provider_status()
        return {
            "generated_at": _now_iso(),
            "schema": EXPORT_SCHEMA_VERSION,
            "channel": "local_file_outbox_export",
            "source_channel": "local_file_outbox",
            **provider,
            "alert_rule_policy": _alert_rule_policy(),
            "external_aggregation_ready": True,
            "export_endpoint": "/api/ops/alerts/export",
            "export_schema": EXPORT_SCHEMA_VERSION,
            "outbox_file": str(self.outbox_file()),
            "event_count": len(events),
            "total_event_count": len(events),
            "exported_count": len(exported),
            "checksum": _export_checksum(exported),
            "retention_policy": self.retention_policy(),
            "redaction_policy": self.redaction_policy(),
            "events": exported,
        }

    def handoff_export_bundle(self, *, limit: int = 100) -> dict[str, Any]:
        bundle = self.export_bundle(limit=limit)
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
            "total_event_count": bundle.get("total_event_count", 0),
            "exported_count": bundle.get("exported_count", 0),
            "external_delivery_enabled": bundle.get("external_delivery_enabled", False),
            "external_provider": bundle.get("external_provider", "disabled"),
            "external_delivery_status": bundle.get("external_delivery_status", "disabled"),
            "external_aggregation_ready": True,
            "alert_rule_policy": bundle.get("alert_rule_policy", {}),
        }
        if handoff_dir is None:
            return {
                **base_payload,
                "reason": "PRODUCTION_ALERT_EXPORT_HANDOFF_DIR is not configured.",
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
        handoff_id = f"prod-alert-handoff-{timestamp_slug}-{checksum_slug[-16:]}"
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
            "total_event_count": bundle.get("total_event_count", 0),
            "exported_count": bundle.get("exported_count", 0),
            "external_delivery_enabled": bundle.get("external_delivery_enabled", False),
            "external_provider": bundle.get("external_provider", "disabled"),
            "external_delivery_status": bundle.get("external_delivery_status", "disabled"),
            "alert_rule_policy": bundle.get("alert_rule_policy", {}),
            "retention_policy": {
                "policy_id": "production_alert_deployment_handoff_v1",
                "custody": "deployment_owned_after_handoff",
                "requires_sanitized_export": True,
                "source_channel": bundle.get("source_channel"),
            },
            "redaction_policy": bundle.get("redaction_policy", {}),
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
        return {
            "mode": "local_bounded_event_count",
            "max_events": self._max_events,
            "time_based_retention_enabled": False,
            "max_age_days": None,
            "prune_on_read_or_write": True,
        }

    def redaction_policy(self) -> dict[str, Any]:
        return {
            "headers_logged": False,
            "webhook_url_returned": False,
            "bodies_logged": False,
            "secret_patterns": ["api_key", "token", "secret", "authorization"],
        }

    def dispatch_from_health(
        self,
        production_health: dict[str, Any],
        *,
        source: str = "manual",
    ) -> dict[str, Any]:
        alerts = [
            alert
            for alert in production_health.get("alerts", [])
            if isinstance(alert, dict)
        ] if isinstance(production_health, dict) else []

        with self._lock:
            existing = self._read_events_unlocked()
            seen = {str(event.get("fingerprint") or "") for event in existing}
            created: list[dict[str, Any]] = []
            deduplicated = 0
            for alert in alerts:
                event = self._event_from_alert(alert, production_health, source=source)
                if event["fingerprint"] in seen:
                    deduplicated += 1
                    continue
                seen.add(event["fingerprint"])
                created.append(event)

            if created:
                self._deliver_events(created, production_health)
                path = self.outbox_file()
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as handle:
                    for event in created:
                        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
                self._trim_unlocked()

        provider = _external_provider_status()
        return {
            "generated_at": _now_iso(),
            "channel": "local_file_outbox",
            **provider,
            "alert_rule_policy": _alert_rule_policy(),
            "dispatched": len(created),
            "deduplicated": deduplicated,
            "production_health_status": _safe_text(production_health.get("status") if isinstance(production_health, dict) else ""),
            "outbox_file": str(self.outbox_file()),
            "events": created,
            "status": self.status(limit=10),
        }

    def clear(self) -> None:
        with self._lock:
            path = self.outbox_file()
            if path.exists():
                path.unlink()

    def _event_from_alert(
        self,
        alert: dict[str, Any],
        production_health: dict[str, Any],
        *,
        source: str,
    ) -> dict[str, Any]:
        fingerprint = _fingerprint(alert)
        policy, rule = _select_alert_rule(alert)
        now = _now_iso()
        return {
            "id": f"prod_alert_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}",
            "fingerprint": fingerprint,
            "created_at": now,
            "source": _safe_text(source, 64) or "manual",
            "channel": "local_file_outbox",
            "delivery_status": "recorded",
            "external_delivery": False,
            "external_provider": "disabled",
            "delivery_attempted_at": "",
            "delivery_attempt_count": 0,
            "delivery_attempt_limit": 0,
            "delivery_error": "",
            "alert_rule_policy_schema": ALERT_RULE_POLICY_SCHEMA_VERSION,
            "alert_rule_policy_status": _safe_text(policy.get("status"), 32),
            "alert_rule_source": _safe_text(policy.get("source"), 120),
            "alert_rule_provider": _safe_text(policy.get("provider"), 120),
            "alert_rule_id": _safe_text(rule.get("id"), 96),
            "alert_routing_key": _safe_text(rule.get("routing_key"), 120),
            "alert_escalation_target": _safe_text(rule.get("escalation_target"), 120),
            "alert_dedupe_window_seconds": _safe_int(rule.get("dedupe_window_seconds"), default=1800, minimum=60, maximum=86400),
            "severity": _severity(alert.get("severity")),
            "metric": _safe_text(alert.get("metric"), 80),
            "window": _safe_text(alert.get("window"), 80),
            "message": _safe_text(alert.get("message"), 320),
            "value": _safe_scalar(alert.get("value")),
            "threshold": _safe_scalar(alert.get("threshold")),
            "details": _safe_dict(alert.get("details")),
            "run_ids": [_safe_text(item, 96) for item in (alert.get("runIds") or [])[:10]]
            if isinstance(alert.get("runIds"), list)
            else [],
            "production_health_status": _safe_text(production_health.get("status"), 48),
            "production_health_generated_at": _safe_text(production_health.get("generatedAt"), 80),
        }

    def _deliver_events(self, events: list[dict[str, Any]], production_health: dict[str, Any]) -> None:
        provider = _external_provider_status()
        if not provider["external_delivery_enabled"]:
            return
        attempt_limit = int(provider.get("external_delivery_attempt_limit") or 1)
        retry_backoff_seconds = float(provider.get("external_delivery_retry_backoff_seconds") or 0.0)
        for event in events:
            event["external_delivery"] = True
            event["external_provider"] = provider["external_provider"]
            event["delivery_attempt_limit"] = attempt_limit
            last_error = ""
            for attempt in range(1, attempt_limit + 1):
                event["delivery_attempt_count"] = attempt
                event["delivery_attempted_at"] = _now_iso()
                try:
                    self._send_webhook_event(event, production_health)
                except Exception as exc:  # noqa: BLE001 - delivery failures must not block local outbox persistence.
                    last_error = _safe_text(exc, 240)
                    if attempt < attempt_limit and retry_backoff_seconds:
                        time.sleep(retry_backoff_seconds)
                    continue
                event["delivery_status"] = "delivered"
                event["delivery_error"] = ""
                break
            else:
                event["delivery_status"] = "failed"
                event["delivery_error"] = last_error

    def _send_webhook_event(self, event: dict[str, Any], production_health: dict[str, Any]) -> None:
        webhook_url = _external_webhook_url()
        if not webhook_url:
            return
        payload = {
            "event": event,
            "production_health": {
                "status": _safe_text(production_health.get("status") if isinstance(production_health, dict) else "", 48),
                "generated_at": _safe_text(production_health.get("generatedAt") if isinstance(production_health, dict) else "", 80),
            },
        }
        data = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        req = url_request.Request(
            webhook_url,
            data=data,
            headers={"Content-Type": "application/json", "User-Agent": "tianyuan-quant-agent-alerts"},
            method="POST",
        )
        try:
            with url_request.urlopen(req, timeout=_external_webhook_timeout_seconds()) as response:
                status_code = getattr(response, "status", response.getcode())
                if int(status_code or 0) >= 400:
                    raise RuntimeError(f"webhook returned HTTP {status_code}")
        except HTTPError as exc:
            raise RuntimeError(f"webhook returned HTTP {exc.code}") from exc
        except URLError as exc:
            raise RuntimeError(f"webhook delivery failed: {exc.reason}") from exc

    def _read_events(self) -> list[dict[str, Any]]:
        with self._lock:
            return self._read_events_unlocked()

    def _read_events_unlocked(self) -> list[dict[str, Any]]:
        path = self.outbox_file()
        if not path.exists():
            return []
        events: list[dict[str, Any]] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                parsed = json.loads(line)
                if isinstance(parsed, dict):
                    events.append(parsed)
        except (OSError, json.JSONDecodeError):
            return []
        return events[-self._max_events :]

    def _trim_unlocked(self) -> None:
        path = self.outbox_file()
        events = self._read_events_unlocked()
        if len(events) < self._max_events or not path.exists():
            return
        path.write_text(
            "".join(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n" for event in events[-self._max_events :]),
            encoding="utf-8",
        )

    def _write_json_atomic(self, path: Path, payload: dict[str, Any]) -> None:
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        temp_path.replace(path)


production_alert_outbox = ProductionAlertOutbox()
