from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any


logger = logging.getLogger(__name__)

SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}
DEFAULT_ACTION_URL = "http://127.0.0.1:5174/signalops"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_text(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def _severity(value: Any) -> str:
    text = _safe_text(value, "info").lower()
    return text if text in SEVERITY_RANK else "info"


def _short(value: Any, limit: int = 220) -> str:
    text = _safe_text(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


class PetAlertCenter:
    def __init__(self, max_alerts: int = 200, dedupe_seconds: int = 180) -> None:
        self._max_alerts = max_alerts
        self._dedupe_seconds = dedupe_seconds
        self._alerts: list[dict[str, Any]] = []
        self._acked: set[str] = set()
        self._dedupe_seen: dict[str, float] = {}
        self._lock = threading.RLock()

    def clear(self) -> None:
        with self._lock:
            self._alerts.clear()
            self._acked.clear()
            self._dedupe_seen.clear()

    def report_alert(self, alert: dict[str, Any]) -> dict[str, Any] | None:
        try:
            return self._report_alert(alert)
        except Exception:  # noqa: BLE001 - alerting must never break the caller.
            logger.exception("Pet alert report failed")
            return None

    def _report_alert(self, alert: dict[str, Any]) -> dict[str, Any] | None:
        now = datetime.now(timezone.utc)
        created_at = _safe_text(alert.get("created_at"), now.isoformat())
        severity = _severity(alert.get("severity"))
        source = _safe_text(alert.get("source"), "system")
        title = _short(alert.get("title"), 80) or "Quant alert"
        message = _short(alert.get("message"), 260)
        symbol = _short(alert.get("symbol"), 32)
        event_type = _short(alert.get("event_type"), 64) or "GENERAL"
        dedupe_key = _short(alert.get("dedupe_key"), 160)
        action_url = _short(alert.get("action_url"), 220) or DEFAULT_ACTION_URL
        alert_id = _short(alert.get("id"), 96) or f"pet_alert_{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

        timestamp = now.timestamp()
        with self._lock:
            if dedupe_key:
                previous = self._dedupe_seen.get(dedupe_key)
                if previous is not None and timestamp - previous < self._dedupe_seconds:
                    return None
                self._dedupe_seen[dedupe_key] = timestamp

            item = {
                "id": alert_id,
                "severity": severity,
                "source": source,
                "title": title,
                "message": message,
                "symbol": symbol,
                "event_type": event_type,
                "created_at": created_at,
                "dedupe_key": dedupe_key,
                "action_url": action_url,
                "acknowledged": False,
            }
            self._alerts.append(item)
            if len(self._alerts) > self._max_alerts:
                removed = self._alerts[:-self._max_alerts]
                self._alerts = self._alerts[-self._max_alerts :]
                for old in removed:
                    self._acked.discard(str(old.get("id") or ""))
            return dict(item)

    def latest(self, after_id: str = "", min_severity: str = "info", limit: int = 20) -> dict[str, Any]:
        min_rank = SEVERITY_RANK.get(_severity(min_severity), 0)
        safe_limit = max(1, min(int(limit or 20), 100))
        with self._lock:
            start = 0
            if after_id:
                for index, item in enumerate(self._alerts):
                    if item.get("id") == after_id:
                        start = index + 1
                        break
            alerts = [
                {**item, "acknowledged": str(item.get("id") or "") in self._acked}
                for item in self._alerts[start:]
                if str(item.get("id") or "") not in self._acked
                and SEVERITY_RANK.get(str(item.get("severity") or "info"), 0) >= min_rank
            ][:safe_limit]
        return {
            "generated_at": _now_iso(),
            "count": len(alerts),
            "next_after_id": str(alerts[-1]["id"]) if alerts else after_id,
            "alerts": alerts,
        }

    def ack(self, alert_id: str) -> bool:
        normalized = _safe_text(alert_id)
        if not normalized:
            return False
        with self._lock:
            exists = any(item.get("id") == normalized for item in self._alerts)
            if exists:
                self._acked.add(normalized)
            return exists

    def status(self) -> dict[str, Any]:
        with self._lock:
            sources = sorted({_safe_text(item.get("source")) for item in self._alerts if item.get("source")})
            last_alert_at = _safe_text(self._alerts[-1].get("created_at")) if self._alerts else ""
            unacked = sum(1 for item in self._alerts if str(item.get("id") or "") not in self._acked)
            queue_size = len(self._alerts)
        return {
            "generated_at": _now_iso(),
            "enabled": True,
            "queue_size": queue_size,
            "unacknowledged_count": unacked,
            "last_alert_at": last_alert_at,
            "sources": sources,
            "min_supported_poll_seconds": 3,
        }

    def report_auto_paper_tick(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        created: list[dict[str, Any]] = []
        try:
            candidates = [result]
            if isinstance(result.get("results"), list):
                candidates.extend([item for item in result["results"] if isinstance(item, dict)])
            for item in candidates:
                alert = self._auto_paper_alert_from_result(item)
                if alert:
                    saved = self.report_alert(alert)
                    if saved:
                        created.append(saved)
        except Exception:  # noqa: BLE001 - alerting must never break trading simulation.
            logger.exception("Auto paper pet alert conversion failed")
        return created

    def _auto_paper_alert_from_result(self, result: dict[str, Any]) -> dict[str, Any] | None:
        status = _safe_text(result.get("status"), "").upper()
        order = result.get("order") if isinstance(result.get("order"), dict) else {}
        decision = result.get("decision") if isinstance(result.get("decision"), dict) else {}
        config = result.get("config")
        config_symbol = getattr(config, "symbol", "") if config is not None else ""
        symbol = _safe_text(result.get("symbol") or order.get("symbol") or decision.get("symbol") or config_symbol)
        action = _safe_text(order.get("action") or decision.get("action"), "").upper()
        message = _safe_text(result.get("message") or decision.get("reason") or order.get("action_reason"))
        signal_id = _safe_text(result.get("signal_id") or order.get("signal_id"))

        if order and action and action != "SIM_HOLD" and not order.get("error"):
            severity = "critical" if action in {"SIM_SELL", "SIM_CLOSE", "SIM_T_SELL"} else "warning"
            return {
                "severity": severity,
                "source": "signalops",
                "title": "Paper trading signal",
                "message": _short(f"Simulation-only {action} for {symbol or 'symbol'}: {message or 'order created'}"),
                "symbol": symbol,
                "event_type": "SIM_ORDER",
                "dedupe_key": f"signalops:{symbol}:{action}:{signal_id or order.get('order_id', '')}",
                "action_url": DEFAULT_ACTION_URL,
            }

        if status in {"ERROR", "PARTIAL", "BLOCKED"}:
            severity = "critical" if status == "ERROR" else "warning"
            return {
                "severity": severity,
                "source": "signalops",
                "title": "Watch tick attention",
                "message": _short(f"Simulation-only watch tick {status}: {message or 'needs review'}"),
                "symbol": symbol,
                "event_type": f"TICK_{status}",
                "dedupe_key": f"signalops:{symbol}:{status}:{message[:80]}",
                "action_url": DEFAULT_ACTION_URL,
            }
        return None

    def report_data_reliability(self, checks: list[dict[str, Any]]) -> dict[str, Any] | None:
        try:
            checked = [item for item in checks if item and item.get("enabled", True)]
            if not checked:
                return None
            failed = [item for item in checked if str(item.get("status") or "").upper() in {"FAILED", "ERROR"} or not item.get("healthy")]
            partial = [item for item in checked if str(item.get("status") or "").upper() == "PARTIAL"]
            if failed and len(failed) == len(checked):
                title = "Market data unavailable"
                severity = "critical"
                event_type = "DATA_SOURCE_FAILED"
                targets = failed
            elif failed or partial:
                title = "Market data degraded"
                severity = "warning"
                event_type = "DATA_SOURCE_PARTIAL"
                targets = (partial or []) + (failed or [])
            else:
                return None
            names = [
                _safe_text(item.get("adapterId") or item.get("provider"), "unknown")
                for item in targets[:4]
            ]
            return self.report_alert(
                {
                    "severity": severity,
                    "source": "data_reliability",
                    "title": title,
                    "message": _short(f"{len(targets)} market data adapter(s) need review: {', '.join(names)}"),
                    "event_type": event_type,
                    "dedupe_key": f"data_reliability:{event_type}:{','.join(sorted(names))}",
                    "action_url": "http://127.0.0.1:5174/data-reliability",
                }
            )
        except Exception:  # noqa: BLE001 - data-reliability alerting is best effort.
            logger.exception("Data reliability pet alert conversion failed")
            return None

    def report_data_health(self, checks: list[dict[str, Any]]) -> dict[str, Any] | None:
        return self.report_data_reliability(checks)


pet_alert_center = PetAlertCenter()
