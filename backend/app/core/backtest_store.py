import asyncio
import hashlib
import json
import logging
import os
import random
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, func, desc, delete as sa_delete

from ..db.session import AsyncSessionLocal
from ..db.models_backtest import BacktestRunDB, BacktestTradeDB, BacktestSignalDB
from ..db.models_research import ResearchEvidenceLinkDB, ResearchIterationDB
from ..core.backtest_engine import (
    run_backtest,
    run_comparison,
    generate_mock_market_data,
    generate_mock_signals,
    normalize_research_contract_parameters,
)
from ..core.bottom_research import (
    BOTTOM_RESEARCH_MODEL_VERSION,
    build_bottom_research_signals,
    stable_payload_hash,
)
from ..models.backtest import BacktestReport, BacktestComparison
from ..core.file_utils import write_json_atomic
from ..core.agent_runtime_store import get_default_market_data_profile
from ..core.market_data_runner import (
    _call_tushare_http_api_raw,
    _normalize_tushare_symbol,
    _tushare_records_from_payload,
)
from ..core.signalops_store import signalops_store
from ..core.strategy_stability_quality import stability_validation_report


logger = logging.getLogger(__name__)


class BacktestRunReferencedError(ValueError):
    def __init__(self, run_id: str, references: List[str]) -> None:
        self.run_id = run_id
        self.references = references
        super().__init__("Backtest run is referenced by Research evidence and cannot be deleted.")

SIGNALOPS_BACKTEST_VERSION = "AUTO_PAPER_V2"
SIGNALOPS_AUTO_SOURCE = "SIGNALOPS_AUTO_PAPER"
SIGNALOPS_LIFECYCLE_SOURCE = "SIGNALOPS_LIFECYCLE_FALLBACK"
SIGNALOPS_AUTO_SOURCE_NODE = "signalops_auto_paper_cleaned_history"
SIGNALOPS_LIFECYCLE_SOURCE_NODE = "signalops_lifecycle"
SIGNALOPS_RANDOM_SOURCE_NODE = "signalops_random_strategy_replay"
BOTTOM_RESEARCH_SOURCE = "BOTTOM_RESEARCH"
BOTTOM_RESEARCH_SOURCE_NODE = "bottom_research"
MFE_MAE_RESEARCH_SOURCE = "MFE_MAE_PATH_RESEARCH"
MFE_MAE_RESEARCH_SOURCE_NODE = "mfe_mae_path_research"
SIGNALOPS_RANDOM_JOB_TERMINAL_STATUSES = {"COMPLETED", "FAILED", "CANCELLED"}
SIGNALOPS_RANDOM_DEFAULT_MIN_WINDOW_DAYS = 365
SIGNALOPS_RANDOM_DEFAULT_MAX_WINDOW_DAYS = 540
SIGNALOPS_RANDOM_DEFAULT_MIN_TRADING_DAYS = 200
SIGNALOPS_RANDOM_MAX_SAMPLE_ATTEMPTS = 12
SIGNALOPS_RANDOM_THRESHOLD_CAP = 0.05
SIGNALOPS_RANDOM_POSITION_CAP = 0.02
BACKTEST_PARAMETER_SCAN_MAX_COMBINATIONS = 20
BACKTEST_PARAMETER_SCAN_MAX_WINDOWS = 4
PARAMETER_SCAN_JOB_STORE_SCHEMA = "backtest_parameter_scan_jobs_v1"
PARAMETER_SCAN_JOB_QUEUE_MODE = "LOCAL_DURABLE_JSON"
PARAMETER_SCAN_JOB_RECOVERABLE_STATUSES = {"QUEUED", "RUNNING", "RECOVERING"}
PARAMETER_SCAN_JOB_ATTEMPT_ACTIVE_STATUSES = {"QUEUED", "RUNNING", "RECOVERING"}
PARAMETER_SCAN_JOB_MAX_ATTEMPTS_RETAINED = 20
SIGNALOPS_RANDOM_TUNABLE_FIELDS = {
    "buy_change_threshold_pct",
    "close_change_threshold_pct",
    "watch_position_ratio",
    "probe_position_ratio",
    "positive_position_ratio",
    "breakout_position_ratio",
    "defensive_position_ratio",
    "existing_position_ratio",
    "strength_follow_position_ratio",
}


def _parameter_scan_job_store_file_from_env() -> Path:
    configured = os.getenv("BACKTEST_PARAMETER_SCAN_JOB_STORE_FILE", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[1] / "storage" / "backtest_parameter_scan_jobs.json"


def _parameter_scan_job_lease_seconds_from_env() -> int:
    try:
        configured = int(os.getenv("BACKTEST_PARAMETER_SCAN_JOB_LEASE_SECONDS", "3600"))
    except ValueError:
        configured = 3600
    return max(30, min(configured, 86_400))


def _parameter_scan_job_handoff_dir_from_env() -> Optional[Path]:
    configured = os.getenv("BACKTEST_PARAMETER_SCAN_HANDOFF_DIR", "").strip()
    if not configured:
        return None
    return Path(configured).expanduser()


PARAMETER_SCAN_JOB_HANDOFF_SHIPPER_STATUS_SCHEMA = "backtest_parameter_scan_job_handoff_shipper_status_v1"
PARAMETER_SCAN_JOB_HANDOFF_SHIPPER_STATUS_FILE = "shipper_status.json"
PARAMETER_SCAN_JOB_HANDOFF_ALLOWED_SHIPPER_STATUSES = {"DELIVERED", "PENDING", "FAILED", "UNKNOWN"}
PARAMETER_SCAN_JOB_HANDOFF_SECRET_PATTERN = re.compile(
    r"(api[_-]?key|token|secret|authorization)=([^,\s]+)",
    re.IGNORECASE,
)
PARAMETER_SCAN_JOB_STORE_FILE = _parameter_scan_job_store_file_from_env()
PARAMETER_SCAN_JOB_LEASE_SECONDS = _parameter_scan_job_lease_seconds_from_env()
PARAMETER_SCAN_JOB_WORKER_ID = f"local-backtest-worker-{os.getpid()}-{uuid.uuid4().hex[:8]}"


def _is_mfe_mae_research_source(value: Any) -> bool:
    return str(value or "").strip().upper() in {MFE_MAE_RESEARCH_SOURCE, BOTTOM_RESEARCH_SOURCE}
SIGNALOPS_SIM_ACTION_DIRECTIONS = {
    "SIM_BUY": "BUY",
    "SIM_T_BUY": "BUY",
    "SIM_COVER": "BUY",
    "BUY": "BUY",
    "LONG": "BUY",
    "SIM_SELL": "SELL",
    "SIM_CLOSE": "SELL",
    "SIM_T_SELL": "SELL",
    "SIM_SHORT": "SELL",
    "SELL": "SELL",
    "SHORT": "SELL",
    "CLOSE": "SELL",
    "COVER": "BUY",
    "SIM_HOLD": "HOLD",
    "HOLD": "HOLD",
    "WAIT": "HOLD",
}

BACKTEST_FINGERPRINT_SCHEMA = "backtest_fingerprint_v1"
BACKTEST_FINGERPRINT_VOLATILE_KEYS = {
    "backtest_fingerprint",
    "benchmark_comparison",
    "created_at",
    "createdAt",
    "data_error",
    "dedupe_reused",
    "elapsed_ms",
    "error",
    "force_new",
    "generated_at",
    "generatedAt",
    "id",
    "limitations",
    "research_evidence_package",
    "reuse_existing",
    "reviewQueueSummary",
    "run_id",
    "signalops_context",
    "updated_at",
    "updatedAt",
    "walk_forward_run_ids",
    "warning",
    "warnings",
}
BACKTEST_FINGERPRINT_COST_KEYS = (
    "commission_bps",
    "stamp_tax_bps",
    "slippage_bps",
    "min_commission",
    "t_plus_one",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _lease_is_active(lease_expires_at: Any, now: datetime) -> bool:
    expires_at = _parse_datetime(lease_expires_at)
    return bool(expires_at and expires_at > now)


def _generate_id(prefix: str) -> str:
    return f"{prefix}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


def _tushare_date(ds: str) -> str:
    value = str(ds or "").strip()
    if len(value) == 8 and value.isdigit():
        return value
    return value.replace("-", "")[:8]


def _iso_date(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text[:10]


def _stable_payload_hash(value: Any, length: int = 16) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:length]


def _stable_experiment_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _stable_experiment_payload(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key) not in {"updated_at", "generated_at", "created_at"}
        }
    if isinstance(value, list):
        return [_stable_experiment_payload(item) for item in value]
    return value


def _fingerprint_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _fingerprint_payload(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key) not in BACKTEST_FINGERPRINT_VOLATILE_KEYS
        }
    if isinstance(value, list):
        return [_fingerprint_payload(item) for item in value]
    if isinstance(value, float):
        return round(value, 8)
    return value


def _float_fingerprint_value(value: Any, default: float = 0.0) -> float:
    try:
        return round(float(value), 8)
    except (TypeError, ValueError):
        return default


def _int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_handoff_text(value: Any, limit: int = 240) -> str:
    text = "" if value is None else str(value).strip()
    text = PARAMETER_SCAN_JOB_HANDOFF_SECRET_PATTERN.sub(r"\1=[REDACTED]", text)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _parameter_scan_job_idempotency_key(payload: Any) -> str:
    return f"bt-parameter-scan-{_stable_payload_hash(_fingerprint_payload(payload), length=24)}"


def _fingerprint_symbol(value: Any) -> str:
    return str(value or "").strip().upper()


def _backtest_fingerprint_payload(
    *,
    symbol: str,
    patch_id: Optional[str],
    case_id: Optional[str],
    start_date: str,
    end_date: str,
    initial_capital: float,
    scenario_label: str,
    parameters: Dict[str, Any],
    market_data: Optional[List[Dict[str, Any]]] = None,
    market_data_source: str = "",
    signals: Optional[List[Dict[str, Any]]] = None,
    benchmark_market_data: Optional[List[Dict[str, Any]]] = None,
    benchmark_data_source: str = "",
    benchmark_error: Optional[str] = None,
) -> Dict[str, Any]:
    params = _fingerprint_payload(parameters or {})
    basis: Dict[str, Any] = {
        "schema": BACKTEST_FINGERPRINT_SCHEMA,
        "symbol": _fingerprint_symbol(symbol),
        "symbol_token": _symbol_token(symbol),
        "start_date": _iso_date(start_date),
        "end_date": _iso_date(end_date),
        "initial_capital": _float_fingerprint_value(initial_capital),
        "patch_id": str(patch_id or ""),
        "case_id": str(case_id or ""),
        "scenario_label": str(scenario_label or ""),
        "signal_source": str((parameters or {}).get("signal_source") or "MOCK").strip().upper(),
        "signal_date": _iso_date((parameters or {}).get("signal_date")),
        "signalops_source_mode": str((parameters or {}).get("signalops_source_mode") or "").strip().upper(),
        "signalops_version": str((parameters or {}).get("signalops_version") or "").strip().upper(),
        "benchmark_symbol": _fingerprint_symbol((parameters or {}).get("benchmark_symbol")),
        "experiment_package_hash": str((parameters or {}).get("experiment_package_hash") or ""),
        "cost_model": {
            key: _fingerprint_payload((parameters or {}).get(key))
            for key in BACKTEST_FINGERPRINT_COST_KEYS
            if key in (parameters or {})
        },
        "parameters": params,
        "market_data_source": str(market_data_source or "").strip().upper(),
        "benchmark_data_source": str(benchmark_data_source or "").strip().upper(),
        "benchmark_error": str(benchmark_error or ""),
    }
    if market_data is not None:
        basis["market_data_hash"] = _stable_payload_hash(_fingerprint_payload(market_data), length=24)
    if signals is not None:
        basis["signals_hash"] = _stable_payload_hash(_fingerprint_payload(signals), length=24)
    if benchmark_market_data is not None:
        basis["benchmark_market_data_hash"] = _stable_payload_hash(_fingerprint_payload(benchmark_market_data), length=24)
    return basis


def _backtest_fingerprint(**kwargs: Any) -> str:
    return _stable_payload_hash(_backtest_fingerprint_payload(**kwargs), length=32)


def _parameter_scan_combinations(parameter_grid: Dict[str, List[Any]], max_combinations: int) -> List[Dict[str, Any]]:
    if not isinstance(parameter_grid, dict) or not parameter_grid:
        raise ValueError("parameter_grid must include at least one parameter.")
    limit = max(1, min(int(max_combinations or 1), BACKTEST_PARAMETER_SCAN_MAX_COMBINATIONS))
    keys = [str(key) for key in parameter_grid.keys() if str(key).strip()]
    if not keys:
        raise ValueError("parameter_grid must include at least one named parameter.")

    values_by_key: List[List[Any]] = []
    for key in keys:
        raw_values = parameter_grid.get(key)
        if isinstance(raw_values, list):
            values = raw_values
        else:
            values = [raw_values]
        values = [item for item in values if item is not None]
        if not values:
            raise ValueError(f"parameter_grid.{key} must include at least one value.")
        values_by_key.append(values)

    combinations: List[Dict[str, Any]] = []

    def build(index: int, current: Dict[str, Any]) -> None:
        if len(combinations) >= limit:
            return
        if index >= len(keys):
            combinations.append(dict(current))
            return
        key = keys[index]
        for value in values_by_key[index]:
            current[key] = value
            build(index + 1, current)
            if len(combinations) >= limit:
                break
        current.pop(key, None)

    build(0, {})
    return combinations


def _parameter_scan_windows(
    start_date: str,
    end_date: str,
    windows: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    raw_windows = windows if isinstance(windows, list) else []
    for index, item in enumerate(raw_windows, start=1):
        if not isinstance(item, dict):
            continue
        start = _iso_date(item.get("start") or item.get("start_date"))
        end = _iso_date(item.get("end") or item.get("end_date"))
        if not start or not end:
            continue
        label = str(item.get("label") or f"window_{index}").strip()
        normalized.append({"start": start, "end": end, "label": label})
        if len(normalized) >= BACKTEST_PARAMETER_SCAN_MAX_WINDOWS:
            break

    if not normalized:
        start = _iso_date(start_date)
        end = _iso_date(end_date)
        if not start or not end:
            raise ValueError("start_date and end_date are required for parameter_scan windows.")
        normalized.append({"start": start, "end": end, "label": "primary"})
    return normalized


def _backtest_ranking_score(run: Dict[str, Any], ranking_metric: str) -> float:
    report = run.get("report") if isinstance(run.get("report"), dict) else {}
    metric = str(ranking_metric or "research_grade_score").strip().lower()
    if metric in {"return", "return_pct", "total_return_pct"}:
        return float(report.get("total_return_pct") or 0.0)
    if metric in {"sharpe", "sharpe_ratio"}:
        return float(report.get("sharpe_ratio") or 0.0)
    if metric in {"drawdown", "max_drawdown", "max_drawdown_pct"}:
        return -float(report.get("max_drawdown_pct") or 0.0)
    if metric in {"hit_rate", "win_rate"}:
        return float(report.get("hit_rate") or 0.0)
    grade = report.get("researchGradeScore") if isinstance(report.get("researchGradeScore"), dict) else {}
    return float(grade.get("score") or 0.0)


def _parameter_scan_review_gate_evidence(report: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "researchUsage": "supporting_only",
        "canSupportResearchVerdict": False,
    }


def _review_gate_research_grade_score(value: Any, *, snake_case: bool = False) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    normalized = dict(value)
    band = str(normalized.get("band") or "").strip().upper()
    if band == "RESEARCH_GRADE":
        normalized.setdefault("calculated_band" if snake_case else "calculatedBand", band)
        normalized["band"] = "REVIEWABLE"
    normalized["can_support_research_verdict" if snake_case else "canSupportResearchVerdict"] = False
    normalized["research_usage" if snake_case else "researchUsage"] = "supporting_only"
    normalized["supporting_only" if snake_case else "supportingOnly"] = True
    return normalized


def _review_gate_backtest_evidence_strength(value: Any, *, snake_case: bool = False) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    normalized = dict(value)
    grade = str(normalized.get("grade") or "").strip().upper()
    if grade not in {"", "LOW", "MEDIUM", "SUPPORTING_ONLY"}:
        normalized.setdefault("reported_grade" if snake_case else "reportedGrade", grade)
        normalized["grade"] = "MEDIUM"
    normalized["can_support_research_verdict" if snake_case else "canSupportResearchVerdict"] = False
    normalized["research_usage" if snake_case else "researchUsage"] = "supporting_only"
    normalized["weak_sample" if snake_case else "weakSample"] = True
    return normalized


def _review_gate_backtest_report(report: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(report)
    normalized["evidenceStrength"] = _review_gate_backtest_evidence_strength(
        normalized.get("evidenceStrength")
    )
    normalized["researchGradeScore"] = _review_gate_research_grade_score(
        normalized.get("researchGradeScore")
    )
    if "evidence_strength" in normalized:
        normalized["evidence_strength"] = _review_gate_backtest_evidence_strength(
            normalized.get("evidence_strength"),
            snake_case=True,
        )
    if "research_grade_score" in normalized:
        normalized["research_grade_score"] = _review_gate_research_grade_score(
            normalized.get("research_grade_score"),
            snake_case=True,
        )
    return normalized


def _json_contains_value(value: Any, expected: str) -> bool:
    if isinstance(value, dict):
        return any(_json_contains_value(item, expected) for item in value.values())
    if isinstance(value, list):
        return any(_json_contains_value(item, expected) for item in value)
    return str(value or "") == expected


def _date_value(value: str) -> datetime:
    text = _iso_date(value)
    return datetime.fromisoformat(text[:10])


def _clamp_float(value: Any, fallback: float, low: float, high: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = fallback
    return max(low, min(high, parsed))


def _model_dump(value: Any) -> Dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    return dict(value) if isinstance(value, dict) else {}


def _symbol_token(value: Any) -> str:
    normalized = str(value or "").strip().upper()
    for suffix in (".SH", ".SZ", ".BJ"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
            break
    return "".join(ch for ch in normalized if ch.isalnum())


def _symbol_matches(record_symbol: Any, symbol: Any) -> bool:
    record_text = str(record_symbol or "").strip().upper()
    symbol_text = str(symbol or "").strip().upper()
    if record_text == "POOL":
        return True
    if not record_text or not symbol_text:
        return False
    return record_text == symbol_text or _symbol_token(record_text) == _symbol_token(symbol_text)


def _split_csv(value: Any) -> List[str]:
    items: List[str] = []
    for raw in str(value or "").replace("；", ",").replace(";", ",").replace("\n", ",").split(","):
        item = raw.strip()
        if item and item not in items:
            items.append(item)
    return items


def _signalops_stock_pool(config_payload: Dict[str, Any]) -> List[Dict[str, str]]:
    symbols = _split_csv(config_payload.get("symbol"))
    names = _split_csv(config_payload.get("stock_name"))
    signal_ids = config_payload.get("signal_ids") if isinstance(config_payload.get("signal_ids"), dict) else {}
    return [
        {
            "symbol": symbol,
            "stock_name": names[index] if index < len(names) else "",
            "signal_id": str(signal_ids.get(symbol) or ""),
        }
        for index, symbol in enumerate(symbols)
    ]


def _signalops_signal_boundary(config_payload: Dict[str, Any], symbol: str) -> Dict[str, Any]:
    initial_map = config_payload.get("initial_buy_signals") if isinstance(config_payload.get("initial_buy_signals"), dict) else {}
    final_map = config_payload.get("final_sell_signals") if isinstance(config_payload.get("final_sell_signals"), dict) else {}
    normalized_symbol = str(symbol or "").strip()
    return {
        "symbol": normalized_symbol,
        "initial_buy_signal": str(initial_map.get(normalized_symbol) or config_payload.get("initial_buy_signal") or ""),
        "final_sell_signal": str(final_map.get(normalized_symbol) or config_payload.get("final_sell_signal") or ""),
        "human_inputs_only": ["symbol", "initial_buy_signal", "final_sell_signal"],
        "ai_controls": [
            "position_ratio",
            "buy",
            "sell",
            "t_trade",
            "short",
            "daily_review",
            "data_cleaning",
            "knowledge_tuning",
        ],
    }


def _signalops_review_queue_summary(config_payload: Dict[str, Any], status_payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    status_payload = status_payload or {}
    queue_state = status_payload.get("review_queue_state") or config_payload.get("review_queue_state")
    queue_state = queue_state if isinstance(queue_state, dict) else {}
    experiment_state = status_payload.get("experiment_validation_state") or config_payload.get("experiment_validation_state")
    experiment_state = experiment_state if isinstance(experiment_state, dict) else {}
    attempts = experiment_state.get("attempts") if isinstance(experiment_state.get("attempts"), dict) else {}
    failed = sum(1 for item in attempts.values() if isinstance(item, dict) and item.get("review_queue_sync_status") == "FAILED")
    pending = sum(
        1
        for item in attempts.values()
        if isinstance(item, dict) and item.get("review_queue_sync_status") in {"", None, "NOT_SYNCED", "PENDING"}
    )
    items = queue_state.get("items") if isinstance(queue_state.get("items"), list) else []
    observations = queue_state.get("observations") if isinstance(queue_state.get("observations"), list) else []
    if failed:
        sync_status = "FAILED"
    elif pending:
        sync_status = "PENDING"
    elif attempts or items or observations:
        sync_status = "SYNCED"
    else:
        sync_status = "NOT_SYNCED"
    return {
        "status": sync_status,
        "item_count": len(items),
        "observation_count": len(observations),
        "counts": queue_state.get("counts") if isinstance(queue_state.get("counts"), dict) else {},
        "failed_attempts": failed,
        "pending_attempts": pending,
        "simulation_only": bool(queue_state.get("simulation_only", True)),
        "is_real_trade": bool(queue_state.get("is_real_trade", False)),
        "updated_at": queue_state.get("updated_at") or experiment_state.get("updated_at") or "",
    }


def _load_signalops_backtest_context(symbol: str) -> Dict[str, Any]:
    try:
        from .auto_paper_trading import auto_paper_trading_store

        config = auto_paper_trading_store.get_config()
        status = auto_paper_trading_store.get_status()
        config_payload = _model_dump(config)
        execution_rules = auto_paper_trading_store._execution_rules_context(config)
    except Exception:
        logger.exception("failed to load SignalOps auto-paper context for backtest")
        config_payload = {}
        status = {}
        execution_rules = {
            "market": "A_SHARE_PAPER_SANDBOX",
            "t_plus_one_long_sell": True,
            "commission_rate": 0.0001,
            "commission_min_fee": 5.0,
            "stamp_duty_rate": 0.0005,
            "simulation_only": True,
            "is_real_trade": False,
        }
    review_summary = _signalops_review_queue_summary(config_payload, status)
    cleaned_history = config_payload.get("cleaned_record_history") if isinstance(config_payload.get("cleaned_record_history"), list) else []
    compressed_observation_history = (
        config_payload.get("compressed_observation_history")
        if isinstance(config_payload.get("compressed_observation_history"), dict)
        else {}
    )
    replay_history = _signalops_replay_history_with_compressed_observations(
        cleaned_history,
        compressed_observation_history,
    )
    return {
        "signalOpsVersion": SIGNALOPS_BACKTEST_VERSION,
        "signalOpsSourceMode": "AUTO",
        "source": SIGNALOPS_AUTO_SOURCE,
        "simulationOnly": True,
        "isRealTrade": False,
        "stockPool": _signalops_stock_pool(config_payload),
        "signalMapping": {
            "signal_ids": config_payload.get("signal_ids") if isinstance(config_payload.get("signal_ids"), dict) else {},
            "initial_buy_signals": config_payload.get("initial_buy_signals") if isinstance(config_payload.get("initial_buy_signals"), dict) else {},
            "final_sell_signals": config_payload.get("final_sell_signals") if isinstance(config_payload.get("final_sell_signals"), dict) else {},
        },
        "cleaned_record_history": replay_history,
        "cleanedRecordCount": len(replay_history),
        "tradeRecordCount": len(cleaned_history),
        "compressedObservationCount": int(compressed_observation_history.get("total_count") or 0),
        "reviewQueueSyncStatus": review_summary.get("status", "NOT_SYNCED"),
        "reviewQueueSummary": review_summary,
        "executionRules": execution_rules,
        "signalBoundary": _signalops_signal_boundary(config_payload, symbol),
        "commission_bps": float(config_payload.get("commission_rate") or execution_rules.get("commission_rate") or 0.0) * 10000,
        "stamp_tax_bps": float(config_payload.get("stamp_duty_rate") or execution_rules.get("stamp_duty_rate") or 0.0) * 10000,
        "min_commission": float(config_payload.get("commission_min_fee") or execution_rules.get("commission_min_fee") or 0.0),
        "t_plus_one": True,
    }


def _signalops_replay_history_with_compressed_observations(
    cleaned_history: List[Dict[str, Any]],
    compressed_observation_history: Dict[str, Any],
) -> List[Dict[str, Any]]:
    records = [dict(item) for item in cleaned_history if isinstance(item, dict)]
    seen = {
        str(record.get("record_id") or record.get("decision_id") or record.get("latest_order_id") or "")
        for record in records
    }
    recent = compressed_observation_history.get("recent") if isinstance(compressed_observation_history, dict) else []
    for raw in recent if isinstance(recent, list) else []:
        if not isinstance(raw, dict):
            continue
        record_id = str(raw.get("record_id") or "")
        if record_id and record_id in seen:
            continue
        signal_date = _iso_date(raw.get("signal_date") or raw.get("trading_date"))
        symbol = str(raw.get("symbol") or "").strip()
        if not signal_date or not symbol:
            continue
        replay_record = {
            **raw,
            "record_id": record_id or f"COMPRESSED_OBS_{signal_date}_{symbol}",
            "signal_date": signal_date,
            "trading_date": signal_date,
            "symbol": symbol,
            "latest_action": str(raw.get("latest_action") or "SIM_HOLD").upper(),
            "order_count": 0,
            "sample_quality": str(raw.get("sample_quality") or "SUPPORTING_ONLY").upper(),
            "source_type": raw.get("source_type") or "COMPRESSED_OBSERVATION",
            "simulation_only": True,
            "is_real_trade": False,
        }
        records.append(replay_record)
        seen.add(str(replay_record["record_id"]))
    return sorted(
        records,
        key=lambda item: (
            _signalops_record_date(item),
            str(item.get("record_id") or ""),
        ),
    )


def _signalops_public_context(context: Dict[str, Any]) -> Dict[str, Any]:
    public = {
        key: value
        for key, value in (context or {}).items()
        if key
        not in {
            "cleaned_record_history",
            "commission_bps",
            "stamp_tax_bps",
            "min_commission",
            "t_plus_one",
        }
    }
    public["cleanedRecordCount"] = int((context or {}).get("cleanedRecordCount") or 0)
    public["tradeRecordCount"] = int((context or {}).get("tradeRecordCount") or 0)
    public["compressedObservationCount"] = int((context or {}).get("compressedObservationCount") or 0)
    public["simulationOnly"] = True
    public["isRealTrade"] = False
    return public


def _setdefault_present(target: Dict[str, Any], key: str, value: Any) -> None:
    if key not in target or target.get(key) in (None, ""):
        target[key] = value


def _apply_signalops_backtest_defaults(parameters: Optional[Dict[str, Any]], symbol: str) -> Dict[str, Any]:
    params = dict(parameters or {})
    context = _load_signalops_backtest_context(symbol)
    _setdefault_present(params, "signalops_version", SIGNALOPS_BACKTEST_VERSION)
    _setdefault_present(params, "signalops_source_mode", "AUTO")
    _setdefault_present(params, "commission_bps", context.get("commission_bps", 0.0))
    _setdefault_present(params, "stamp_tax_bps", context.get("stamp_tax_bps", 0.0))
    _setdefault_present(params, "min_commission", context.get("min_commission", 0.0))
    _setdefault_present(params, "t_plus_one", True)
    context["signalOpsSourceMode"] = str(params.get("signalops_source_mode") or "AUTO").strip().upper()
    params["signalops_context"] = _signalops_public_context(context)
    return params


def _apply_bottom_research_backtest_defaults(parameters: Optional[Dict[str, Any]], symbol: str) -> Dict[str, Any]:
    params = dict(parameters or {})
    bottom_config = params.get("bottom_research_config") if isinstance(params.get("bottom_research_config"), dict) else {}
    _setdefault_present(params, "data_source", "AUTO")
    _setdefault_present(params, "signal_source", MFE_MAE_RESEARCH_SOURCE)
    _setdefault_present(params, "bottom_research_model_version", BOTTOM_RESEARCH_MODEL_VERSION)
    _setdefault_present(params, "mfe_mae_research_model_version", BOTTOM_RESEARCH_MODEL_VERSION)
    _setdefault_present(params, "manual_review_accepted", False)
    _setdefault_present(params, "signal_min_strength", 0.0)
    _setdefault_present(params, "trade_quantity_pct", 0.01)
    params["bottom_research_config"] = bottom_config
    params["mfe_mae_research_config"] = bottom_config
    context = {
        "symbol": symbol,
        "source_node": MFE_MAE_RESEARCH_SOURCE_NODE,
        "legacy_source_node": BOTTOM_RESEARCH_SOURCE_NODE,
        "model_version": BOTTOM_RESEARCH_MODEL_VERSION,
        "config_hash": stable_payload_hash(bottom_config),
        "simulation_only": True,
        "is_real_trade": False,
        "trade_action_policy": "REVIEW_ONLY_NOT_TRADE_INSTRUCTION",
    }
    params["mfe_mae_research_context"] = context
    params["bottom_research_context"] = context
    return params


def _window_bounds(value: Dict[str, Any], name: str) -> Dict[str, str]:
    start = _iso_date(value.get("start") or value.get("start_date") or value.get("startDate"))
    end = _iso_date(value.get("end") or value.get("end_date") or value.get("endDate"))
    if not start or not end:
        raise ValueError(f"{name} requires explicit start and end dates.")
    if end < start:
        raise ValueError(f"{name} end date must be on or after start date.")
    return {"start": start, "end": end}


def _experiment_expectancy_pct(report: Dict[str, Any]) -> float:
    trades = int(report.get("total_trades") or 0)
    if trades <= 0:
        return 0.0
    return round(float(report.get("total_return_pct") or 0.0) / trades, 6)


def _experiment_market_usable(report: Dict[str, Any]) -> bool:
    data_source = str(report.get("data_source") or "").upper()
    return bool(report.get("data_points")) and data_source not in {"MOCK", "MOCK_FALLBACK"}


def _float_value(record: Dict[str, Any], *keys: str, default: float = 0.0) -> float:
    for key in keys:
        value = record.get(key)
        if value in (None, ""):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return default


def _signalops_record_date(record: Dict[str, Any]) -> str:
    return _iso_date(
        record.get("signal_date")
        or record.get("trading_date")
        or record.get("updated_at")
        or record.get("created_at")
        or record.get("cleaned_at")
    )


def _signalops_record_quality(record: Dict[str, Any]) -> str:
    quality = str(record.get("sample_quality") or "LOW").strip().upper() or "LOW"
    if quality in {"STRONG", "HIGH", "PRIMARY", "PRIMARY_EVIDENCE", "PASS", "READY"}:
        return "MEDIUM"
    if quality in {"MEDIUM", "SUPPORTING_ONLY", "LOW"}:
        return quality
    return "LOW"


def _signalops_record_has_trade(record: Dict[str, Any]) -> bool:
    try:
        return int(record.get("order_count") or record.get("all_order_count") or 0) > 0
    except (TypeError, ValueError):
        return False


def _signalops_replay_direction(record: Dict[str, Any]) -> str:
    action = _signalops_record_action(record)
    mapped = SIGNALOPS_SIM_ACTION_DIRECTIONS.get(action)
    if mapped:
        return mapped
    outcome = str(record.get("outcome") or "").strip().upper()
    if any(token in action for token in ("SELL", "CLOSE", "EXIT", "CLEAR", "REDUCE")):
        return "SELL"
    if any(token in action for token in ("BUY", "LONG")):
        return "BUY"
    if _signalops_record_has_trade(record) and outcome in {"WIN", "FAILURE", "NEUTRAL"}:
        return "BUY"
    return "HOLD"


def _signalops_record_action(record: Dict[str, Any]) -> str:
    metadata = record.get("metadata_json") if isinstance(record.get("metadata_json"), dict) else {}
    decision = record.get("decision") if isinstance(record.get("decision"), dict) else {}
    for source in (record, metadata, decision):
        for key in ("latest_action", "final_action", "action", "decision_action"):
            value = str(source.get(key) or "").strip().upper()
            if value:
                return value
    return ""


def _signalops_replay_signal(
    record: Dict[str, Any],
    *,
    role: str,
    context: Optional[Dict[str, Any]] = None,
    include_hold: bool = False,
) -> Optional[Dict[str, Any]]:
    signal_date = _signalops_record_date(record)
    symbol = str(record.get("symbol") or "").strip()
    if not signal_date or not symbol:
        return None
    quality = _signalops_record_quality(record)
    direction = _signalops_replay_direction(record)
    if direction == "HOLD" and not include_hold:
        return None
    action = _signalops_record_action(record)
    signal_type = (
        f"SIGNALOPS_AUTO_{action}"
        if action and (action.startswith("SIM_") or action in SIGNALOPS_SIM_ACTION_DIRECTIONS)
        else f"SIGNALOPS_REPLAY_{direction}"
    )
    public_context = _signalops_public_context(context or {}) if context else {}
    return {
        "timestamp": signal_date,
        "symbol": symbol,
        "signal_type": signal_type,
        "direction": direction,
        "strength": 0.25 if direction == "HOLD" else 1.0 if quality not in {"LOW", "SUPPORTING_ONLY"} else 0.35,
        "source_node": SIGNALOPS_AUTO_SOURCE_NODE,
        "metadata_json": {
            "source": SIGNALOPS_AUTO_SOURCE,
            "signalops_version": SIGNALOPS_BACKTEST_VERSION,
            "signalops_source_mode": str((context or {}).get("signalOpsSourceMode") or "AUTO_PAPER"),
            "role": role,
            "record_id": record.get("record_id"),
            "signal_id": record.get("signal_id"),
            "latest_order_id": record.get("latest_order_id"),
            "source_type": record.get("source_type"),
            "source_id": record.get("source_id"),
            "decision_id": record.get("decision_id"),
            "outcome": record.get("outcome"),
            "latest_action": action,
            "sample_quality": quality,
            "evidence_refs": record.get("evidence_refs") if isinstance(record.get("evidence_refs"), list) else [],
            "simulation_only": True,
            "is_real_trade": False,
            "execution_rules": public_context.get("executionRules"),
            "signal_boundary": public_context.get("signalBoundary"),
        },
    }


def _quality_rank(value: str) -> int:
    ranks = {"MEDIUM": 2, "SUPPORTING_ONLY": 1, "LOW": 0}
    return ranks.get(str(value or "").upper(), 0)


def _combined_sample_quality(records: List[Dict[str, Any]]) -> str:
    if not records:
        return "LOW"
    qualities = [_signalops_record_quality(record) for record in records]
    if any(item == "LOW" for item in qualities):
        return "LOW"
    if any(item == "SUPPORTING_ONLY" for item in qualities):
        return "SUPPORTING_ONLY"
    return "MEDIUM"


def _build_signalops_replay_signals(
    *,
    records: List[Dict[str, Any]],
    symbol: str,
    train_window: Dict[str, str],
    validation_window: Dict[str, str],
) -> Dict[str, Any]:
    normalized_symbol = str(symbol or "").strip()
    train_records: List[Dict[str, Any]] = []
    validation_records: List[Dict[str, Any]] = []
    dropped_records: List[Dict[str, Any]] = []
    for raw in records:
        if not isinstance(raw, dict):
            continue
        record = dict(raw)
        if normalized_symbol and str(record.get("symbol") or "").strip() not in {normalized_symbol, "POOL"}:
            continue
        signal_date = _signalops_record_date(record)
        if not signal_date:
            dropped_records.append({**record, "drop_reason": "missing_signal_date"})
            continue
        if train_window["start"] <= signal_date <= train_window["end"]:
            train_records.append(record)
        elif validation_window["start"] <= signal_date <= validation_window["end"]:
            validation_records.append(record)
        else:
            dropped_records.append({**record, "drop_reason": "outside_experiment_window"})

    return {
        "baseline_train": [_signalops_replay_signal(record, role="baseline_train") for record in train_records],
        "candidate_train": [_signalops_replay_signal(record, role="candidate_train") for record in train_records],
        "baseline_validation": [_signalops_replay_signal(record, role="baseline_validation") for record in validation_records],
        "candidate_validation": [_signalops_replay_signal(record, role="candidate_validation") for record in validation_records],
        "train_records": train_records,
        "validation_records": validation_records,
        "dropped_records": dropped_records,
        "sample_quality": _combined_sample_quality([*train_records, *validation_records]),
    }


def _clean_replay_signal_list(value: List[Optional[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)]


def _config_uses_no_signals(config: Dict[str, Any]) -> bool:
    return str((config or {}).get("signal_source") or "").strip().upper() == "NONE"


SIGNALOPS_STRENGTH = {
    "IDEA": 0.1,
    "WATCH": 0.25,
    "PAPER_TEST": 0.55,
    "QUALIFIED": 0.75,
    "TRADE_PLAN": 0.85,
    "MANUAL_CONFIRMED": 0.95,
    "EXECUTION_REVIEW": 0.9,
}


def _date_in_range(value: str, start_date: str, end_date: str) -> bool:
    ds = _iso_date(value)
    return bool(ds and start_date <= ds <= end_date)


def _signal_date_in_range(value: str, start_date: str, end_date: str) -> str:
    ds = _iso_date(value)
    if _date_in_range(ds, start_date, end_date):
        return ds
    return ""


def _signalops_direction(signal: Dict[str, Any]) -> str:
    status = str(signal.get("status") or "").upper()
    metadata = signal.get("metadata_json") if isinstance(signal.get("metadata_json"), dict) else {}
    decision = signal.get("decision") if isinstance(signal.get("decision"), dict) else {}
    for source in (metadata, signal, decision):
        for key in ("final_action", "latest_action", "action", "decision_action"):
            action = str(source.get(key) or "").strip().upper()
            mapped = SIGNALOPS_SIM_ACTION_DIRECTIONS.get(action)
            if mapped:
                return mapped
            if action in {"SELL", "REDUCE", "CLEAR", "EXIT", "CLOSE"}:
                return "SELL"
            if action in {"BUY", "LONG"}:
                return "BUY"
    if status in {"PAPER_TEST", "QUALIFIED", "TRADE_PLAN", "MANUAL_CONFIRMED", "EXECUTION_REVIEW"}:
        return "BUY"
    return "HOLD"


def _signalops_lifecycle_is_auto(record: Dict[str, Any]) -> bool:
    metadata = record.get("metadata_json") if isinstance(record.get("metadata_json"), dict) else {}
    source = str(metadata.get("source") or record.get("source") or "").strip().upper()
    return bool(
        metadata.get("simulation_only") is True
        or source in {"AUTO_PAPER_TRADING", "SIGNALOPS_AUTO_PAPER"}
        or str(metadata.get("automation_mode") or "").strip().upper() in {"AI_FULLY_AUTONOMOUS", "AUTO_PAPER"}
    )


def _signalops_requested_signal_id(params: Dict[str, Any]) -> str:
    return str(params.get("signal_id") or params.get("signalops_signal_id") or "").strip()


def _signalops_requested_record_id(params: Dict[str, Any]) -> str:
    return str(params.get("record_id") or params.get("signalops_record_id") or "").strip()


def _select_signalops_auto_sample_record(
    context: Dict[str, Any],
    *,
    symbol: Optional[str] = None,
    signal_id: Optional[str] = None,
    source_run_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    records = context.get("cleaned_record_history") if isinstance(context.get("cleaned_record_history"), list) else []
    requested_signal_id = str(signal_id or "").strip()
    requested_run_id = str(source_run_id or "").strip()
    trade_candidate: Optional[Dict[str, Any]] = None
    hold_candidate: Optional[Dict[str, Any]] = None
    for raw in reversed(records):
        if not isinstance(raw, dict):
            continue
        record = dict(raw)
        if symbol and not _symbol_matches(record.get("symbol"), symbol):
            continue
        if requested_signal_id and str(record.get("signal_id") or "") != requested_signal_id:
            continue
        if requested_run_id and not _signalops_record_matches_run(record, requested_run_id):
            continue
        if not _signalops_record_date(record):
            continue
        if _signalops_replay_direction(record) == "HOLD":
            hold_candidate = hold_candidate or record
        else:
            trade_candidate = trade_candidate or record
    return trade_candidate or hold_candidate


def _build_signalops_auto_paper_signals(
    context: Dict[str, Any],
    symbol: str,
    start_date: str,
    end_date: str,
    params: Dict[str, Any],
) -> List[Dict[str, Any]]:
    records = context.get("cleaned_record_history") if isinstance(context.get("cleaned_record_history"), list) else []
    requested_signal_id = _signalops_requested_signal_id(params)
    requested_record_id = _signalops_requested_record_id(params)
    requested_run_id = str(params.get("source_run_id") or params.get("signalops_source_run_id") or "").strip()
    signals: List[Dict[str, Any]] = []
    for raw in records:
        if not isinstance(raw, dict):
            continue
        record = dict(raw)
        if not _symbol_matches(record.get("symbol"), symbol):
            continue
        if requested_signal_id and str(record.get("signal_id") or "") != requested_signal_id:
            continue
        if requested_record_id and str(record.get("record_id") or "") != requested_record_id:
            continue
        if requested_run_id and not _signalops_record_matches_run(record, requested_run_id):
            continue
        signal_date = _signalops_record_date(record)
        if not _date_in_range(signal_date, start_date, end_date):
            continue
        signal = _signalops_replay_signal(
            record,
            role="auto_paper_backtest",
            context={**context, "signalOpsSourceMode": str(params.get("signalops_source_mode") or "AUTO")},
            include_hold=True,
        )
        if signal:
            signals.append(signal)
    return _dedupe_signalops_signals(signals)


def _signalops_lifecycle_signal(
    record: Dict[str, Any],
    *,
    symbol: str,
    timestamp: str,
    status: str,
    context: Optional[Dict[str, Any]],
    source_label: str,
) -> Dict[str, Any]:
    public_context = _signalops_public_context(context or {}) if context else {}
    metadata = record.get("metadata_json") if isinstance(record.get("metadata_json"), dict) else {}
    return {
        "timestamp": timestamp,
        "symbol": symbol,
        "signal_type": f"SIGNALOPS_{status}",
        "direction": _signalops_direction(record),
        "strength": SIGNALOPS_STRENGTH.get(status, 0.2),
        "source_node": SIGNALOPS_LIFECYCLE_SOURCE_NODE,
        "metadata_json": {
            "source": source_label,
            "source_detail": source_label,
            "signalops_version": SIGNALOPS_BACKTEST_VERSION,
            "signalops_source_mode": "LIFECYCLE" if source_label == SIGNALOPS_LIFECYCLE_SOURCE else "AUTO",
            "signal_id": record.get("signal_id"),
            "audit_id": record.get("audit_id"),
            "source_run_id": record.get("source_run_id"),
            "latest_run_id": record.get("latest_run_id"),
            "lifecycle_status": status,
            "blocked_reason": record.get("blocked_reason", ""),
            "trigger_conditions": record.get("trigger_conditions", []),
            "invalidation_conditions": record.get("invalidation_conditions", []),
            "simulation_only": True,
            "is_real_trade": False,
            "lifecycle_metadata_source": metadata.get("source"),
            "execution_rules": public_context.get("executionRules"),
            "signal_boundary": public_context.get("signalBoundary"),
        },
    }


def _dedupe_signalops_signals(signals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for signal in signals:
        metadata = signal.get("metadata_json") if isinstance(signal.get("metadata_json"), dict) else {}
        identity = "|".join(
            [
                str(signal.get("timestamp") or ""),
                str(signal.get("symbol") or ""),
                str(signal.get("signal_type") or ""),
                str(signal.get("source_node") or ""),
                str(metadata.get("record_id") or metadata.get("signal_id") or metadata.get("latest_order_id") or metadata.get("source_id") or ""),
            ]
        )
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(signal)
    return deduped


async def fetch_signalops_signals_for_backtest(
    symbol: str,
    start_date: str,
    end_date: str,
    parameters: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    params = dict(parameters or {})
    start = _iso_date(start_date)
    end = _iso_date(end_date)
    source_mode = str(params.get("signalops_source_mode") or "AUTO").strip().upper()
    context = _load_signalops_backtest_context(symbol) if source_mode != "LIFECYCLE" else {}
    auto_signals = (
        _build_signalops_auto_paper_signals(context, symbol, start, end, params)
        if source_mode in {"AUTO", "AUTO_PAPER"}
        else []
    )
    if source_mode == "AUTO_PAPER":
        return auto_signals

    records = await signalops_store.list_signals(symbol=symbol, limit=int(params.get("signalops_limit", 100)))
    allowed_statuses = set(params.get("signalops_statuses") or SIGNALOPS_STRENGTH.keys())
    signal_date = str(params.get("signal_date") or "")
    requested_signal_id = _signalops_requested_signal_id(params)
    requested_run_id = str(params.get("source_run_id") or params.get("signalops_source_run_id") or "").strip()
    current_lifecycle_signals: List[Dict[str, Any]] = []
    fallback_lifecycle_signals: List[Dict[str, Any]] = []
    for record in records:
        if requested_signal_id and str(record.get("signal_id") or "") != requested_signal_id:
            continue
        if requested_run_id and not _signalops_record_matches_run(record, requested_run_id):
            continue
        status = str(record.get("status") or "").upper()
        if status not in allowed_statuses or status in {"CLOSED", "PATCH_REQUIRED"}:
            continue
        timestamp = _signal_date_in_range(signal_date or record.get("updated_at") or record.get("created_at") or start, start, end)
        if not timestamp:
            continue
        signal = _signalops_lifecycle_signal(
            record,
            symbol=symbol,
            timestamp=timestamp,
            status=status,
            context=context,
            source_label=SIGNALOPS_AUTO_SOURCE if _signalops_lifecycle_is_auto(record) else SIGNALOPS_LIFECYCLE_SOURCE,
        )
        if _signalops_lifecycle_is_auto(record):
            current_lifecycle_signals.append(signal)
        else:
            fallback_lifecycle_signals.append(signal)
    if source_mode == "LIFECYCLE":
        return _dedupe_signalops_signals([*current_lifecycle_signals, *fallback_lifecycle_signals])
    primary = [*auto_signals, *current_lifecycle_signals]
    if primary:
        return _dedupe_signalops_signals(primary)
    return _dedupe_signalops_signals(fallback_lifecycle_signals)


def fetch_bottom_research_signals_for_backtest(
    symbol: str,
    market_data: List[Dict[str, Any]],
    parameters: Optional[Dict[str, Any]] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    params = parameters or {}
    config = params.get("bottom_research_config") if isinstance(params.get("bottom_research_config"), dict) else {}
    signals, metadata = build_bottom_research_signals(symbol, market_data or [], config=config)
    for signal in signals:
        signal.setdefault("source_node", MFE_MAE_RESEARCH_SOURCE_NODE)
        metadata_json = signal.setdefault("metadata_json", {})
        metadata_json["source"] = MFE_MAE_RESEARCH_SOURCE
        metadata_json["legacy_source"] = BOTTOM_RESEARCH_SOURCE
        metadata_json["source_node"] = MFE_MAE_RESEARCH_SOURCE_NODE
        metadata_json["legacy_source_node"] = BOTTOM_RESEARCH_SOURCE_NODE
        metadata_json["bottom_research_signal_hash"] = metadata.get("signal_hash", "")
        metadata_json["mfe_mae_research_signal_hash"] = metadata.get("signal_hash", "")
        metadata_json["simulation_only"] = True
        metadata_json["is_real_trade"] = False
    return signals, metadata


def _signalops_record_matches_run(record: Dict[str, Any], run_id: str) -> bool:
    if not run_id:
        return True
    attached_runs = record.get("attached_runs") if isinstance(record.get("attached_runs"), list) else []
    candidates = {
        str(record.get("source_run_id") or ""),
        str(record.get("latest_run_id") or ""),
        str(record.get("source_id") or ""),
        str(record.get("run_id") or ""),
        *(str(item or "") for item in attached_runs),
    }
    return run_id in candidates


def normalize_tushare_daily_records(records: List[Dict[str, Any]], symbol: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for record in records:
        trade_date = _iso_date(record.get("trade_date") or record.get("date"))
        close = _float_value(record, "close")
        open_price = _float_value(record, "open", default=close)
        if not trade_date or close <= 0 or open_price <= 0:
            continue
        prev_close = _float_value(record, "pre_close", "prev_close", default=close)
        rows.append(
            {
                "date": trade_date,
                "symbol": record.get("ts_code") or symbol,
                "open": open_price,
                "high": _float_value(record, "high", default=max(open_price, close)),
                "low": _float_value(record, "low", default=min(open_price, close)),
                "close": close,
                "volume": _float_value(record, "vol", "volume"),
                "amount": _float_value(record, "amount"),
                "prev_close": prev_close,
            }
        )
    return sorted(rows, key=lambda row: row["date"])


def _market_data_response_to_daily_row(resp: Any, symbol: str) -> Dict[str, Any]:
    price = resp.price or 0
    extra = resp.extra if isinstance(resp.extra, dict) else {}
    open_price = extra.get("open", price)
    high = extra.get("high", price)
    low = extra.get("low", price)
    pre_close = extra.get("preClose", price)
    volume = resp.volume or 0
    amount = extra.get("amount", 0)
    return {
        "date": resp.timestamp[:10] if resp.timestamp else "",
        "symbol": symbol,
        "open": float(open_price or price),
        "high": float(high or price),
        "low": float(low or price),
        "close": float(price),
        "volume": float(volume or 0),
        "amount": float(amount or 0),
        "prev_close": float(pre_close or price),
    }


async def fetch_historical_for_backtest(symbol: str, start_date: str, end_date: str) -> List[Dict[str, Any]]:
    try:
        from .market_data_adapter import register_default_market_data_adapters

        registry = register_default_market_data_adapters()

        results = await registry.fetch_historical_quote_with_fallback(
            symbol, start_date, end_date, fallback_to_mock=False
        )
        if results:
            rows = [_market_data_response_to_daily_row(r, symbol) for r in results]
            rows = [r for r in rows if r["date"] and r["close"] > 0]
            if rows:
                return sorted(rows, key=lambda r: r["date"])
    except Exception:
        pass

    profile = get_default_market_data_profile()
    if profile.provider != "tushare":
        raise RuntimeError(f"Default market data profile is {profile.provider}, not tushare.")
    if not profile.api_key:
        raise RuntimeError("Tushare token is not configured.")

    payload = await asyncio.to_thread(
        _call_tushare_http_api_raw,
        profile,
        "daily",
        {
            "ts_code": _normalize_tushare_symbol(symbol),
            "start_date": _tushare_date(start_date),
            "end_date": _tushare_date(end_date),
        },
    )
    records = _tushare_records_from_payload(payload)
    rows = normalize_tushare_daily_records(records, symbol)
    if not rows:
        raise RuntimeError("Tushare daily returned no records for the requested range.")
    return rows


async def fetch_a_share_stock_universe() -> List[Dict[str, Any]]:
    profile = get_default_market_data_profile()
    if profile.provider != "tushare":
        raise RuntimeError(f"Default market data profile is {profile.provider}, not tushare.")
    if not profile.api_key:
        raise RuntimeError("Tushare token is not configured.")
    payload = await asyncio.to_thread(
        _call_tushare_http_api_raw,
        profile,
        "stock_basic",
        {"exchange": "", "list_status": "L"},
    )
    records = _tushare_records_from_payload(payload)
    universe: List[Dict[str, Any]] = []
    for raw in records:
        if not isinstance(raw, dict):
            continue
        symbol = str(raw.get("ts_code") or raw.get("symbol") or "").strip().upper()
        if not symbol.endswith((".SH", ".SZ", ".BJ")):
            continue
        name = str(raw.get("name") or raw.get("stock_name") or symbol).strip()
        universe.append({
            "symbol": symbol,
            "stock_name": name,
            "exchange": str(raw.get("exchange") or "").strip(),
            "market": str(raw.get("market") or "").strip(),
            "industry": str(raw.get("industry") or "").strip(),
            "area": str(raw.get("area") or "").strip(),
            "list_date": _iso_date(raw.get("list_date") or ""),
        })
    deduped: Dict[str, Dict[str, Any]] = {}
    for item in universe:
        deduped[item["symbol"]] = item
    return sorted(deduped.values(), key=lambda item: item["symbol"])


def _signalops_random_config_snapshot(config_payload: Dict[str, Any]) -> Dict[str, Any]:
    defaults = {
        "buy_change_threshold_pct": 0.5,
        "close_change_threshold_pct": -2.0,
        "watch_position_ratio": 0.15,
        "probe_position_ratio": 0.35,
        "positive_position_ratio": 0.50,
        "breakout_position_ratio": 0.65,
        "defensive_position_ratio": 0.25,
        "existing_position_ratio": 0.45,
        "strength_follow_position_ratio": 0.65,
        "commission_bps": float(config_payload.get("commission_rate") or 0.0001) * 10000,
        "stamp_tax_bps": float(config_payload.get("stamp_duty_rate") or 0.0005) * 10000,
        "min_commission": float(config_payload.get("commission_min_fee") or 5.0),
        "t_plus_one": True,
        "signal_source": "SIGNALOPS",
        "signalops_version": SIGNALOPS_BACKTEST_VERSION,
        "signalops_source_mode": "AUTO_PAPER",
        "data_source": "AUTO",
    }
    for key in SIGNALOPS_RANDOM_TUNABLE_FIELDS:
        if key in config_payload:
            defaults[key] = config_payload[key]
    defaults["trade_quantity_pct"] = _clamp_float(
        config_payload.get("existing_position_ratio") or config_payload.get("watch_position_ratio"),
        0.20,
        0.01,
        0.85,
    )
    return defaults


def _signalops_random_candidate_config(baseline: Dict[str, Any], first_report: Dict[str, Any]) -> Dict[str, Any]:
    candidate = dict(baseline)
    total_return = float(first_report.get("total_return_pct") or 0.0)
    max_drawdown = float(first_report.get("max_drawdown_pct") or 0.0)
    if total_return < 0 or max_drawdown > 0.08:
        candidate["buy_change_threshold_pct"] = _clamp_float(
            float(baseline.get("buy_change_threshold_pct") or 0.5) + SIGNALOPS_RANDOM_THRESHOLD_CAP,
            0.55,
            0.1,
            5.0,
        )
        candidate["close_change_threshold_pct"] = _clamp_float(
            float(baseline.get("close_change_threshold_pct") or -2.0) + SIGNALOPS_RANDOM_THRESHOLD_CAP,
            -1.95,
            -5.0,
            -0.2,
        )
        for key in (
            "watch_position_ratio",
            "probe_position_ratio",
            "positive_position_ratio",
            "breakout_position_ratio",
            "defensive_position_ratio",
            "existing_position_ratio",
            "strength_follow_position_ratio",
        ):
            candidate[key] = _clamp_float(
                float(baseline.get(key) or 0.2) - SIGNALOPS_RANDOM_POSITION_CAP,
                0.2,
                0.0,
                0.85,
            )
    else:
        candidate["buy_change_threshold_pct"] = _clamp_float(
            float(baseline.get("buy_change_threshold_pct") or 0.5) - SIGNALOPS_RANDOM_THRESHOLD_CAP,
            0.45,
            0.1,
            5.0,
        )
        candidate["positive_position_ratio"] = _clamp_float(
            float(baseline.get("positive_position_ratio") or 0.5) + SIGNALOPS_RANDOM_POSITION_CAP,
            0.52,
            0.0,
            0.85,
        )
        candidate["breakout_position_ratio"] = _clamp_float(
            float(baseline.get("breakout_position_ratio") or 0.65) + SIGNALOPS_RANDOM_POSITION_CAP,
            0.67,
            0.0,
            0.85,
        )
    candidate["trade_quantity_pct"] = _clamp_float(
        candidate.get("existing_position_ratio") or candidate.get("watch_position_ratio"),
        float(baseline.get("trade_quantity_pct") or 0.2),
        0.01,
        0.85,
    )
    return candidate


def _signalops_random_config_diff(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, float]:
    diff: Dict[str, float] = {}
    for key in sorted(SIGNALOPS_RANDOM_TUNABLE_FIELDS):
        if key not in after:
            continue
        try:
            delta = float(after.get(key)) - float(before.get(key))
        except (TypeError, ValueError):
            continue
        if abs(delta) > 0.000001:
            diff[key] = round(delta, 6)
    return diff


def _signalops_random_signals_from_market_data(
    *,
    symbol: str,
    market_data: List[Dict[str, Any]],
    config: Dict[str, Any],
    role: str,
) -> List[Dict[str, Any]]:
    buy_threshold = float(config.get("buy_change_threshold_pct") or 0.5)
    sell_threshold = float(config.get("close_change_threshold_pct") or -2.0)
    signals: List[Dict[str, Any]] = []
    for row in market_data:
        ds = _iso_date(row.get("date") or "")
        close = _float_value(row, "close")
        prev_close = _float_value(row, "prev_close", "pre_close", default=close)
        if not ds or close <= 0 or prev_close <= 0:
            continue
        change_pct = (close - prev_close) / prev_close * 100
        if change_pct >= buy_threshold:
            action = "SIM_BUY"
            direction = "BUY"
            strength = min(1.0, 0.65 + abs(change_pct) / 20)
        elif change_pct <= sell_threshold:
            action = "SIM_SELL"
            direction = "SELL"
            strength = min(1.0, 0.65 + abs(change_pct) / 20)
        else:
            action = "SIM_HOLD"
            direction = "HOLD"
            strength = 0.25
        signals.append({
            "timestamp": ds,
            "symbol": symbol,
            "signal_type": f"SIGNALOPS_AUTO_{action}",
            "direction": direction,
            "strength": round(strength, 4),
            "source_node": SIGNALOPS_RANDOM_SOURCE_NODE,
            "metadata_json": {
                "source": "SIGNALOPS_RANDOM_VALIDATION",
                "signalops_version": SIGNALOPS_BACKTEST_VERSION,
                "signalops_source_mode": "AUTO_PAPER",
                "role": role,
                "latest_action": action,
                "change_pct": round(change_pct, 4),
                "buy_change_threshold_pct": buy_threshold,
                "close_change_threshold_pct": sell_threshold,
                "simulation_only": True,
                "is_real_trade": False,
            },
        })
    return signals


def _random_validation_run_summary(run: Dict[str, Any]) -> Dict[str, Any]:
    report = run.get("report") if isinstance(run.get("report"), dict) else {}
    benchmark = report.get("benchmark") if isinstance(report.get("benchmark"), dict) else {}
    return {
        "runId": run.get("run_id"),
        "symbol": run.get("symbol"),
        "stockName": run.get("stock_name"),
        "startDate": run.get("start_date"),
        "endDate": run.get("end_date"),
        "totalReturnPct": report.get("total_return_pct", 0.0),
        "totalPnl": report.get("total_pnl", 0.0),
        "hitRate": report.get("hit_rate", 0.0),
        "maxDrawdownPct": report.get("max_drawdown_pct", 0.0),
        "totalTrades": report.get("total_trades", 0),
        "totalSignals": report.get("total_signals", 0),
        "buySignals": report.get("buy_signals", 0),
        "sellSignals": report.get("sell_signals", 0),
        "dataSource": report.get("data_source", ""),
        "tradingDays": (report.get("sampleWindow") or {}).get("tradingDays", 0),
        "buyHoldReturnPct": benchmark.get("returnPct", 0.0),
        "buyHoldAvailable": bool(benchmark.get("available")),
    }


class BacktestStore:
    def __init__(self) -> None:
        self._random_validation_jobs: Dict[str, Dict[str, Any]] = {}
        self._random_validation_tasks: Dict[str, asyncio.Task] = {}
        self._random_validation_lock = asyncio.Lock()
        restored_parameter_jobs, restored_changed = self._load_parameter_scan_jobs()
        self._parameter_scan_jobs: Dict[str, Dict[str, Any]] = restored_parameter_jobs
        self._parameter_scan_tasks: Dict[str, asyncio.Task] = {}
        self._parameter_scan_jobs_lock = asyncio.Lock()
        self._fingerprint_locks: Dict[str, asyncio.Lock] = {}
        self._fingerprint_locks_guard = asyncio.Lock()
        if restored_changed:
            self._save_parameter_scan_jobs_snapshot(dict(self._parameter_scan_jobs))

    def _load_parameter_scan_jobs(self) -> Tuple[Dict[str, Dict[str, Any]], bool]:
        store_file = PARAMETER_SCAN_JOB_STORE_FILE
        if not store_file.exists():
            return {}, False
        try:
            with store_file.open("r", encoding="utf-8") as file:
                state = json.load(file)
        except (json.JSONDecodeError, OSError):
            logger.exception("Backtest parameter scan job store could not be loaded")
            return {}, False
        raw_jobs = state.get("jobs") if isinstance(state, dict) else {}
        if not isinstance(raw_jobs, dict):
            return {}, False
        jobs: Dict[str, Dict[str, Any]] = {}
        changed = False
        for raw_job_id, raw_job in raw_jobs.items():
            job, job_changed = self._normalize_restored_parameter_scan_job(str(raw_job_id), raw_job)
            if not job:
                changed = True
                continue
            jobs[str(job["jobId"])] = job
            changed = changed or job_changed
        return jobs, changed

    def _parameter_scan_job_attempt_id(self, job_id: str, attempt_number: int) -> str:
        return f"{job_id}-attempt-{attempt_number}"

    def _normalize_parameter_scan_job_attempts(
        self,
        job: Dict[str, Any],
        now: str,
    ) -> bool:
        changed = False
        job_id = str(job.get("jobId") or "").strip()
        idempotency_key = str(job.get("idempotencyKey") or _parameter_scan_job_idempotency_key(job.get("request") or {}))
        raw_attempts = job.get("attempts") if isinstance(job.get("attempts"), list) else []
        attempts: List[Dict[str, Any]] = []
        seen_attempt_ids: set[str] = set()
        for index, raw_attempt in enumerate(raw_attempts, start=1):
            if not isinstance(raw_attempt, dict):
                changed = True
                continue
            attempt_number = _int_value(raw_attempt.get("attemptNumber") or raw_attempt.get("attempt"), index)
            if attempt_number <= 0:
                attempt_number = index
                changed = True
            attempt_id = str(raw_attempt.get("attemptId") or "").strip()
            if not attempt_id:
                attempt_id = self._parameter_scan_job_attempt_id(job_id, attempt_number)
                changed = True
            if attempt_id in seen_attempt_ids:
                changed = True
                continue
            seen_attempt_ids.add(attempt_id)
            status = str(raw_attempt.get("status") or "UNKNOWN").strip().upper()
            progress_step = str(raw_attempt.get("progressStep") or status).strip().upper()
            attempt = {
                "attemptId": attempt_id,
                "attemptNumber": attempt_number,
                "status": status,
                "progressStep": progress_step,
                "startedAt": str(raw_attempt.get("startedAt") or raw_attempt.get("createdAt") or now),
                "finishedAt": raw_attempt.get("finishedAt"),
                "error": raw_attempt.get("error"),
                "scanId": str(raw_attempt.get("scanId") or ""),
                "runIds": [str(item) for item in raw_attempt.get("runIds", [])] if isinstance(raw_attempt.get("runIds"), list) else [],
                "bestRunId": raw_attempt.get("bestRunId"),
                "idempotencyKey": str(raw_attempt.get("idempotencyKey") or idempotency_key),
                "queueMode": PARAMETER_SCAN_JOB_QUEUE_MODE,
                "leaseOwner": str(raw_attempt.get("leaseOwner") or job.get("leaseOwner") or ""),
                "leaseId": str(raw_attempt.get("leaseId") or job.get("leaseId") or ""),
                "leaseStatus": str(raw_attempt.get("leaseStatus") or job.get("leaseStatus") or "UNKNOWN").strip().upper(),
                "leaseAcquiredAt": raw_attempt.get("leaseAcquiredAt") or job.get("leaseAcquiredAt"),
                "leaseExpiresAt": raw_attempt.get("leaseExpiresAt") or job.get("leaseExpiresAt"),
                "leaseReleasedAt": raw_attempt.get("leaseReleasedAt") or job.get("leaseReleasedAt"),
                "leaseSeconds": _int_value(raw_attempt.get("leaseSeconds"), _int_value(job.get("leaseSeconds"), PARAMETER_SCAN_JOB_LEASE_SECONDS)),
                "recovered": bool(raw_attempt.get("recovered", job.get("recovered", False))),
                "recoveryAttemptCount": _int_value(raw_attempt.get("recoveryAttemptCount"), _int_value(job.get("recoveryAttemptCount"), 0)),
                "simulationOnly": bool(raw_attempt.get("simulationOnly", True)),
                "isRealTrade": bool(raw_attempt.get("isRealTrade", False)),
            }
            if attempt != raw_attempt:
                changed = True
            attempts.append(attempt)
        attempts.sort(key=lambda item: (_int_value(item.get("attemptNumber"), 0), str(item.get("attemptId") or "")))
        max_attempt_number = max([_int_value(item.get("attemptNumber"), 0) for item in attempts] + [0])
        attempt_count = max(_int_value(job.get("attemptCount"), 0), max_attempt_number)
        if len(attempts) > PARAMETER_SCAN_JOB_MAX_ATTEMPTS_RETAINED:
            attempts = attempts[-PARAMETER_SCAN_JOB_MAX_ATTEMPTS_RETAINED:]
            changed = True
        current_attempt_id = str(job.get("currentAttemptId") or "").strip()
        attempt_ids = {str(item.get("attemptId") or "") for item in attempts}
        if current_attempt_id and current_attempt_id not in attempt_ids:
            current_attempt_id = ""
            changed = True
        if not current_attempt_id:
            active_attempt = next(
                (item for item in reversed(attempts) if str(item.get("status") or "").upper() in PARAMETER_SCAN_JOB_ATTEMPT_ACTIVE_STATUSES),
                None,
            )
            current_attempt_id = str((active_attempt or (attempts[-1] if attempts else {})).get("attemptId") or "")
        last_attempt_status = str(job.get("lastAttemptStatus") or "").strip().upper()
        if attempts:
            latest_status = str(attempts[-1].get("status") or "").strip().upper()
            if not last_attempt_status or last_attempt_status != latest_status:
                last_attempt_status = latest_status
                changed = True
        job["attempts"] = attempts
        job["attemptCount"] = attempt_count
        job["currentAttemptId"] = current_attempt_id or None
        job["lastAttemptStatus"] = last_attempt_status or None
        job["idempotencyKey"] = idempotency_key
        return changed

    def _mark_interrupted_parameter_scan_job_attempt_locked(self, job: Dict[str, Any], now: str) -> bool:
        attempts = job.get("attempts") if isinstance(job.get("attempts"), list) else []
        current_attempt_id = str(job.get("currentAttemptId") or "").strip()
        active_attempt = next(
            (
                item
                for item in attempts
                if str(item.get("attemptId") or "") == current_attempt_id
                and str(item.get("status") or "").upper() in PARAMETER_SCAN_JOB_ATTEMPT_ACTIVE_STATUSES
            ),
            None,
        )
        if not active_attempt:
            active_attempt = next(
                (
                    item
                    for item in reversed(attempts)
                    if str(item.get("status") or "").upper() in PARAMETER_SCAN_JOB_ATTEMPT_ACTIVE_STATUSES
                ),
                None,
            )
        if not active_attempt:
            attempt_number = max(_int_value(job.get("attemptCount"), 0), len(attempts)) + 1
            active_attempt = {
                "attemptId": self._parameter_scan_job_attempt_id(str(job.get("jobId") or ""), attempt_number),
                "attemptNumber": attempt_number,
                "startedAt": str(job.get("updatedAt") or job.get("createdAt") or now),
                "scanId": str(job.get("scanId") or ""),
                "runIds": [str(item) for item in job.get("runIds", [])] if isinstance(job.get("runIds"), list) else [],
                "bestRunId": job.get("bestRunId"),
                "idempotencyKey": str(job.get("idempotencyKey") or _parameter_scan_job_idempotency_key(job.get("request") or {})),
                "queueMode": PARAMETER_SCAN_JOB_QUEUE_MODE,
                "leaseOwner": str(job.get("leaseOwner") or ""),
                "leaseId": str(job.get("leaseId") or ""),
                "leaseStatus": str(job.get("leaseStatus") or "EXPIRED").strip().upper(),
                "leaseAcquiredAt": job.get("leaseAcquiredAt"),
                "leaseExpiresAt": job.get("leaseExpiresAt"),
                "leaseReleasedAt": job.get("leaseReleasedAt"),
                "leaseSeconds": _int_value(job.get("leaseSeconds"), PARAMETER_SCAN_JOB_LEASE_SECONDS),
                "recovered": True,
                "recoveryAttemptCount": _int_value(job.get("recoveryAttemptCount"), 0),
                "simulationOnly": bool(job.get("simulationOnly", True)),
                "isRealTrade": bool(job.get("isRealTrade", False)),
            }
            attempts.append(active_attempt)
        active_attempt["status"] = "INTERRUPTED"
        active_attempt["progressStep"] = "INTERRUPTED"
        active_attempt["finishedAt"] = now
        active_attempt["error"] = active_attempt.get("error") or "Recovered after backend restart before terminal attempt state."
        active_attempt["recovered"] = True
        active_attempt["recoveryAttemptCount"] = _int_value(job.get("recoveryAttemptCount"), 0)
        active_attempt["leaseStatus"] = "EXPIRED"
        active_attempt["leaseReleasedAt"] = now
        job["attemptCount"] = max(_int_value(job.get("attemptCount"), 0), _int_value(active_attempt.get("attemptNumber"), 0))
        job["currentAttemptId"] = active_attempt.get("attemptId")
        job["lastAttemptStatus"] = "INTERRUPTED"
        job["attempts"] = attempts[-PARAMETER_SCAN_JOB_MAX_ATTEMPTS_RETAINED:]
        job["leaseStatus"] = "UNCLAIMED"
        job["leaseOwner"] = ""
        job["leaseId"] = ""
        job["leaseAcquiredAt"] = None
        job["leaseExpiresAt"] = None
        job["leaseReleasedAt"] = now
        return True

    def _normalize_restored_parameter_scan_job(
        self,
        fallback_job_id: str,
        raw_job: Any,
    ) -> Tuple[Optional[Dict[str, Any]], bool]:
        if not isinstance(raw_job, dict):
            return None, True
        now = _now()
        job = dict(raw_job)
        job_id = str(job.get("jobId") or fallback_job_id or "").strip()
        if not job_id:
            return None, True
        status = str(job.get("status") or "QUEUED").strip().upper()
        known_statuses = PARAMETER_SCAN_JOB_RECOVERABLE_STATUSES | SIGNALOPS_RANDOM_JOB_TERMINAL_STATUSES
        changed = False
        if status not in known_statuses:
            status = "FAILED"
            job["error"] = job.get("error") or "Unknown persisted Backtest parameter scan job status."
            changed = True
        job["jobId"] = job_id
        job["status"] = status
        job["progressStep"] = str(job.get("progressStep") or status).strip().upper()
        job["request"] = job.get("request") if isinstance(job.get("request"), dict) else {}
        job["scan"] = job.get("scan") if isinstance(job.get("scan"), dict) else None
        job["scanId"] = str(job.get("scanId") or "")
        job["runIds"] = [str(item) for item in job.get("runIds", [])] if isinstance(job.get("runIds"), list) else []
        job["bestRunId"] = job.get("bestRunId")
        job["totalCombinations"] = _int_value(job.get("totalCombinations"), 0)
        job["totalTrials"] = _int_value(job.get("totalTrials"), 0)
        job["windowCount"] = _int_value(job.get("windowCount"), 0)
        job["simulationOnly"] = bool(job.get("simulationOnly", True))
        job["isRealTrade"] = bool(job.get("isRealTrade", False))
        job["error"] = job.get("error")
        job["createdAt"] = str(job.get("createdAt") or now)
        job["updatedAt"] = str(job.get("updatedAt") or now)
        job["queueMode"] = PARAMETER_SCAN_JOB_QUEUE_MODE
        job["storageSchema"] = PARAMETER_SCAN_JOB_STORE_SCHEMA
        job["durable"] = True
        job["recovered"] = bool(job.get("recovered", False))
        job["recoveredAt"] = job.get("recoveredAt")
        job["idempotencyKey"] = str(job.get("idempotencyKey") or _parameter_scan_job_idempotency_key(job["request"]))
        job["leaseOwner"] = str(job.get("leaseOwner") or "")
        job["leaseId"] = str(job.get("leaseId") or "")
        job["leaseAcquiredAt"] = job.get("leaseAcquiredAt")
        job["leaseExpiresAt"] = job.get("leaseExpiresAt")
        job["leaseReleasedAt"] = job.get("leaseReleasedAt")
        job["leaseSeconds"] = _int_value(job.get("leaseSeconds"), PARAMETER_SCAN_JOB_LEASE_SECONDS)
        if job["status"] in SIGNALOPS_RANDOM_JOB_TERMINAL_STATUSES:
            default_lease_status = "RELEASED"
        elif job["leaseId"]:
            default_lease_status = "LEASED"
        else:
            default_lease_status = "UNCLAIMED"
        job["leaseStatus"] = str(job.get("leaseStatus") or default_lease_status).strip().upper()
        recovery_attempt_count = _int_value(job.get("recoveryAttemptCount"), 0)
        changed = self._normalize_parameter_scan_job_attempts(job, now) or changed
        if job["status"] in PARAMETER_SCAN_JOB_RECOVERABLE_STATUSES:
            job["status"] = "RECOVERING"
            job["progressStep"] = "RECOVERING"
            job["recovered"] = True
            job["recoveredAt"] = now
            job["recoveryAttemptCount"] = recovery_attempt_count + 1
            if status in {"RUNNING", "RECOVERING"}:
                changed = self._mark_interrupted_parameter_scan_job_attempt_locked(job, now) or changed
            else:
                job["leaseStatus"] = "UNCLAIMED"
                job["leaseOwner"] = ""
                job["leaseId"] = ""
                job["leaseAcquiredAt"] = None
                job["leaseExpiresAt"] = None
            job["updatedAt"] = now
            changed = True
        else:
            job["recoveryAttemptCount"] = recovery_attempt_count
        return job, changed

    def _save_parameter_scan_jobs_snapshot(self, jobs: Dict[str, Dict[str, Any]]) -> None:
        store_file = PARAMETER_SCAN_JOB_STORE_FILE
        state = {
            "schema": PARAMETER_SCAN_JOB_STORE_SCHEMA,
            "queueMode": PARAMETER_SCAN_JOB_QUEUE_MODE,
            "updatedAt": _now(),
            "jobs": {
                str(job_id): self._public_parameter_scan_job(job, include_handoff_status=False)
                for job_id, job in jobs.items()
                if isinstance(job, dict)
            },
        }
        try:
            write_json_atomic(store_file, state)
        except OSError:
            logger.exception("Backtest parameter scan job store could not be saved")

    def _persist_parameter_scan_jobs_locked(self) -> None:
        self._save_parameter_scan_jobs_snapshot(dict(self._parameter_scan_jobs))

    def _write_json_atomic(self, path: Path, payload: Dict[str, Any]) -> None:
        write_json_atomic(path, payload)

    def _latest_parameter_scan_job_handoff_manifest(
        self,
        handoff_dir: Path,
        job_id: str,
    ) -> Dict[str, Any]:
        if not handoff_dir.exists():
            return {}
        try:
            manifest_paths = sorted(
                handoff_dir.glob("*.manifest.json"),
                key=lambda item: item.stat().st_mtime if item.exists() else 0,
                reverse=True,
            )[:50]
        except OSError:
            return {}
        for manifest_path in manifest_paths:
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(manifest, dict):
                continue
            if manifest.get("schema") != "backtest_parameter_scan_job_handoff_manifest_v1":
                continue
            if str(manifest.get("jobId") or "") != job_id:
                continue
            return {
                "handoffId": _safe_handoff_text(manifest.get("handoffId"), 160),
                "bundleChecksum": _safe_handoff_text(manifest.get("bundleChecksum"), 160),
                "manifestFile": _safe_handoff_text(manifest_path.name, 240),
                "bundleFile": _safe_handoff_text(manifest.get("bundleFile"), 240),
                "handedOffAt": _safe_handoff_text(manifest.get("handedOffAt"), 80),
                "jobId": _safe_handoff_text(manifest.get("jobId"), 120),
                "scanId": _safe_handoff_text(manifest.get("scanId"), 120),
            }
        return {}

    def _parameter_scan_job_handoff_status(self, job: Dict[str, Any]) -> Dict[str, Any]:
        job_id = str(job.get("jobId") or "")
        scan_id = str(job.get("scanId") or "")
        handoff_dir = _parameter_scan_job_handoff_dir_from_env()
        base = {
            "schema": PARAMETER_SCAN_JOB_HANDOFF_SHIPPER_STATUS_SCHEMA,
            "checked": False,
            "configured": False,
            "reported": False,
            "status": "NOT_CONFIGURED",
            "reason": "BACKTEST_PARAMETER_SCAN_HANDOFF_DIR is not configured.",
            "handoffDestination": "NOT_CONFIGURED",
            "handoffDir": "",
            "sidecarFile": "",
            "source": "",
            "provider": "",
            "remoteDestination": "",
            "objectKey": "",
            "retentionPolicyId": "",
            "retentionStatus": "",
            "custodyStatus": "",
            "searchIndex": "",
            "searchIndexReady": False,
            "lastHandoffId": "",
            "lastBundleChecksum": "",
            "lastJobId": "",
            "lastScanId": "",
            "latestHandoffId": "",
            "latestBundleChecksum": "",
            "latestManifestFile": "",
            "matchesLatestHandoff": False,
            "matchesJob": False,
            "deploymentReported": False,
            "message": "",
            "issues": [],
        }
        if handoff_dir is None:
            return base

        latest_manifest = self._latest_parameter_scan_job_handoff_manifest(handoff_dir, job_id)
        latest_handoff_id = _safe_handoff_text(latest_manifest.get("handoffId"), 160)
        latest_bundle_checksum = _safe_handoff_text(latest_manifest.get("bundleChecksum"), 160)
        latest_manifest_file = _safe_handoff_text(latest_manifest.get("manifestFile"), 240)
        configured_base = {
            **base,
            "checked": True,
            "configured": True,
            "status": "NOT_REPORTED",
            "reason": "",
            "handoffDestination": "LOCAL_DEPLOYMENT_HANDOFF_DIR",
            "handoffDir": str(handoff_dir),
            "latestHandoffId": latest_handoff_id,
            "latestBundleChecksum": latest_bundle_checksum,
            "latestManifestFile": latest_manifest_file,
            "matchesJob": bool(latest_handoff_id),
        }
        if not handoff_dir.exists():
            return {
                **configured_base,
                "status": "EMPTY",
                "reason": "No Backtest parameter-scan handoff manifest has been written yet.",
            }

        sidecar_path = handoff_dir / PARAMETER_SCAN_JOB_HANDOFF_SHIPPER_STATUS_FILE
        if not sidecar_path.exists():
            return {
                **configured_base,
                "sidecarFile": str(sidecar_path),
                "issues": [] if latest_handoff_id else ["no_handoff_manifest_for_job"],
            }

        try:
            if sidecar_path.stat().st_size > 65536:
                return {
                    **configured_base,
                    "reported": True,
                    "status": "INVALID",
                    "sidecarFile": str(sidecar_path),
                    "issues": ["sidecar_too_large"],
                }
            payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {
                **configured_base,
                "reported": True,
                "status": "INVALID",
                "sidecarFile": str(sidecar_path),
                "issues": ["invalid_sidecar_json"],
            }
        if not isinstance(payload, dict) or payload.get("schema") != PARAMETER_SCAN_JOB_HANDOFF_SHIPPER_STATUS_SCHEMA:
            return {
                **configured_base,
                "reported": True,
                "status": "INVALID",
                "sidecarFile": str(sidecar_path),
                "issues": ["unexpected_sidecar_schema"],
            }

        raw_status = _safe_handoff_text(payload.get("status"), 32).upper() or "UNKNOWN"
        status = raw_status if raw_status in PARAMETER_SCAN_JOB_HANDOFF_ALLOWED_SHIPPER_STATUSES else "UNKNOWN"
        issues: List[str] = []
        if status != raw_status:
            issues.append(f"unexpected_status:{raw_status}")

        last_handoff_id = _safe_handoff_text(payload.get("lastHandoffId") or payload.get("last_handoff_id"), 160)
        last_bundle_checksum = _safe_handoff_text(payload.get("lastBundleChecksum") or payload.get("last_bundle_checksum"), 160)
        last_job_id = _safe_handoff_text(payload.get("lastJobId") or payload.get("last_job_id"), 120)
        last_scan_id = _safe_handoff_text(payload.get("lastScanId") or payload.get("last_scan_id"), 120)
        matches_latest = False
        if latest_handoff_id and last_handoff_id == latest_handoff_id:
            matches_latest = not (
                last_bundle_checksum
                and latest_bundle_checksum
                and last_bundle_checksum != latest_bundle_checksum
            )
            if not matches_latest:
                issues.append("bundle_checksum_mismatch_with_latest_handoff")
        elif latest_handoff_id:
            issues.append("handoff_id_mismatch_with_latest_handoff")
        else:
            issues.append("no_handoff_manifest_for_job")
        matches_job = (not last_job_id or last_job_id == job_id) and (not last_scan_id or last_scan_id == scan_id)
        if not matches_job:
            issues.append("job_or_scan_mismatch")

        return {
            **configured_base,
            "reported": True,
            "status": status,
            "sidecarFile": str(sidecar_path),
            "source": _safe_handoff_text(payload.get("source"), 120) or "deployment_shipper",
            "provider": _safe_handoff_text(payload.get("provider"), 120),
            "remoteDestination": _safe_handoff_text(payload.get("remoteDestination") or payload.get("remote_destination"), 240),
            "objectKey": _safe_handoff_text(payload.get("objectKey") or payload.get("object_key"), 240),
            "retentionPolicyId": _safe_handoff_text(payload.get("retentionPolicyId") or payload.get("retention_policy_id"), 120),
            "retentionStatus": _safe_handoff_text(payload.get("retentionStatus") or payload.get("retention_status"), 80),
            "custodyStatus": _safe_handoff_text(payload.get("custodyStatus") or payload.get("custody_status"), 80),
            "searchIndex": _safe_handoff_text(payload.get("searchIndex") or payload.get("search_index"), 120),
            "searchIndexReady": bool(payload.get("searchIndexReady") or payload.get("search_index_ready")),
            "lastHandoffId": last_handoff_id,
            "lastBundleChecksum": last_bundle_checksum,
            "lastJobId": last_job_id,
            "lastScanId": last_scan_id,
            "matchesLatestHandoff": matches_latest,
            "matchesJob": matches_job,
            "deploymentReported": True,
            "message": _safe_handoff_text(payload.get("message"), 240),
            "issues": issues[:10],
        }

    def _schedule_parameter_scan_job(self, job_id: str) -> bool:
        existing = self._parameter_scan_tasks.get(job_id)
        if existing and not existing.done():
            return True
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return False
        self._parameter_scan_tasks[job_id] = loop.create_task(self._run_parameter_scan_job(job_id))
        return True

    def _release_parameter_scan_job_lease_locked(self, job: Dict[str, Any], now: str, status: str = "RELEASED") -> None:
        job["leaseStatus"] = status
        job["leaseReleasedAt"] = now

    def _set_parameter_scan_job_attempt_terminal_locked(
        self,
        job: Dict[str, Any],
        *,
        attempt_id: Optional[str],
        status: str,
        now: str,
        error: Optional[str] = None,
        scan_id: str = "",
        run_ids: Optional[List[str]] = None,
        best_run_id: Any = None,
    ) -> None:
        attempts = job.get("attempts") if isinstance(job.get("attempts"), list) else []
        target_attempt = next(
            (item for item in attempts if str(item.get("attemptId") or "") == str(attempt_id or "")),
            None,
        )
        if not target_attempt:
            target_attempt = next(
                (
                    item
                    for item in reversed(attempts)
                    if str(item.get("status") or "").upper() in PARAMETER_SCAN_JOB_ATTEMPT_ACTIVE_STATUSES
                ),
                None,
            )
        if not target_attempt:
            return
        normalized_status = str(status or "").strip().upper()
        target_attempt["status"] = normalized_status
        target_attempt["progressStep"] = normalized_status
        target_attempt["finishedAt"] = now
        target_attempt["error"] = error
        if scan_id:
            target_attempt["scanId"] = scan_id
        if run_ids is not None:
            target_attempt["runIds"] = [str(item) for item in run_ids]
        if best_run_id is not None:
            target_attempt["bestRunId"] = best_run_id
        target_attempt["simulationOnly"] = bool(job.get("simulationOnly", True))
        target_attempt["isRealTrade"] = bool(job.get("isRealTrade", False))
        target_attempt["recovered"] = bool(job.get("recovered", False))
        target_attempt["recoveryAttemptCount"] = _int_value(job.get("recoveryAttemptCount"), 0)
        target_attempt["leaseOwner"] = str(target_attempt.get("leaseOwner") or job.get("leaseOwner") or "")
        target_attempt["leaseId"] = str(target_attempt.get("leaseId") or job.get("leaseId") or "")
        target_attempt["leaseStatus"] = "RELEASED"
        target_attempt["leaseAcquiredAt"] = target_attempt.get("leaseAcquiredAt") or job.get("leaseAcquiredAt")
        target_attempt["leaseExpiresAt"] = target_attempt.get("leaseExpiresAt") or job.get("leaseExpiresAt")
        target_attempt["leaseReleasedAt"] = now
        target_attempt["leaseSeconds"] = _int_value(target_attempt.get("leaseSeconds"), _int_value(job.get("leaseSeconds"), PARAMETER_SCAN_JOB_LEASE_SECONDS))
        job["attempts"] = attempts[-PARAMETER_SCAN_JOB_MAX_ATTEMPTS_RETAINED:]
        job["currentAttemptId"] = target_attempt.get("attemptId")
        job["lastAttemptStatus"] = normalized_status

    async def _start_parameter_scan_job_attempt(self, job_id: str) -> Optional[str]:
        async with self._parameter_scan_jobs_lock:
            job = self._parameter_scan_jobs.get(job_id)
            if not job or str(job.get("status") or "").upper() in SIGNALOPS_RANDOM_JOB_TERMINAL_STATUSES:
                return None
            now_dt = datetime.now(timezone.utc)
            now = now_dt.isoformat()
            idempotency_key = str(job.get("idempotencyKey") or _parameter_scan_job_idempotency_key(job.get("request") or {}))
            job["idempotencyKey"] = idempotency_key
            lease_seconds = max(30, min(_int_value(job.get("leaseSeconds"), PARAMETER_SCAN_JOB_LEASE_SECONDS), 86_400))
            job["leaseSeconds"] = lease_seconds
            attempts = job.get("attempts") if isinstance(job.get("attempts"), list) else []
            current_attempt_id = str(job.get("currentAttemptId") or "").strip()
            current_attempt = next(
                (item for item in attempts if str(item.get("attemptId") or "") == current_attempt_id),
                None,
            )
            if (
                str(job.get("leaseStatus") or "").upper() == "LEASED"
                and _lease_is_active(job.get("leaseExpiresAt"), now_dt)
                and current_attempt
                and str(current_attempt.get("status") or "").upper() in PARAMETER_SCAN_JOB_ATTEMPT_ACTIVE_STATUSES
            ):
                job["status"] = "RUNNING"
                job["progressStep"] = "RUNNING"
                job["updatedAt"] = now
                self._persist_parameter_scan_jobs_locked()
                return None
            if current_attempt and str(current_attempt.get("status") or "").upper() == "RUNNING":
                current_attempt["status"] = "INTERRUPTED"
                current_attempt["progressStep"] = "INTERRUPTED"
                current_attempt["finishedAt"] = now
                current_attempt["error"] = current_attempt.get("error") or "Lease expired before terminal attempt state."
                current_attempt["leaseStatus"] = "EXPIRED"
                current_attempt["leaseReleasedAt"] = now
                job["lastAttemptStatus"] = "INTERRUPTED"
            attempt_number = max(_int_value(job.get("attemptCount"), 0), len(attempts)) + 1
            attempt_id = self._parameter_scan_job_attempt_id(job_id, attempt_number)
            lease_id = f"{attempt_id}-lease-{uuid.uuid4().hex[:8]}"
            lease_expires_at = (now_dt + timedelta(seconds=lease_seconds)).isoformat()
            attempt = {
                "attemptId": attempt_id,
                "attemptNumber": attempt_number,
                "status": "RUNNING",
                "progressStep": "RUNNING",
                "startedAt": now,
                "finishedAt": None,
                "error": None,
                "scanId": "",
                "runIds": [],
                "bestRunId": None,
                "idempotencyKey": idempotency_key,
                "queueMode": PARAMETER_SCAN_JOB_QUEUE_MODE,
                "leaseOwner": PARAMETER_SCAN_JOB_WORKER_ID,
                "leaseId": lease_id,
                "leaseStatus": "LEASED",
                "leaseAcquiredAt": now,
                "leaseExpiresAt": lease_expires_at,
                "leaseReleasedAt": None,
                "leaseSeconds": lease_seconds,
                "recovered": bool(job.get("recovered", False)),
                "recoveryAttemptCount": _int_value(job.get("recoveryAttemptCount"), 0),
                "simulationOnly": True,
                "isRealTrade": False,
            }
            attempts.append(attempt)
            job["attempts"] = attempts[-PARAMETER_SCAN_JOB_MAX_ATTEMPTS_RETAINED:]
            job["attemptCount"] = attempt_number
            job["currentAttemptId"] = attempt_id
            job["lastAttemptStatus"] = "RUNNING"
            job["status"] = "RUNNING"
            job["progressStep"] = "RUNNING"
            job["error"] = None
            job["leaseOwner"] = PARAMETER_SCAN_JOB_WORKER_ID
            job["leaseId"] = lease_id
            job["leaseStatus"] = "LEASED"
            job["leaseAcquiredAt"] = now
            job["leaseExpiresAt"] = lease_expires_at
            job["leaseReleasedAt"] = None
            job["leaseSeconds"] = lease_seconds
            job["updatedAt"] = now
            self._persist_parameter_scan_jobs_locked()
            return attempt_id

    async def _finish_parameter_scan_job_attempt(
        self,
        job_id: str,
        attempt_id: Optional[str],
        *,
        status: str,
        error: Optional[str] = None,
        scan_id: str = "",
        run_ids: Optional[List[str]] = None,
        best_run_id: Any = None,
        updates: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        async with self._parameter_scan_jobs_lock:
            job = self._parameter_scan_jobs.get(job_id)
            if not job:
                return {}
            normalized_status = str(status or "").strip().upper()
            current_status = str(job.get("status") or "").upper()
            if current_status in SIGNALOPS_RANDOM_JOB_TERMINAL_STATUSES and current_status != normalized_status:
                return self._public_parameter_scan_job(job)
            if attempt_id and str(job.get("currentAttemptId") or "") != str(attempt_id):
                logger.warning(
                    "Ignoring stale Backtest parameter scan attempt terminal update for %s: %s is not current %s",
                    job_id,
                    attempt_id,
                    job.get("currentAttemptId"),
                )
                return self._public_parameter_scan_job(job)
            now = _now()
            if updates:
                job.update(updates)
            job["status"] = normalized_status
            job["progressStep"] = normalized_status
            job["error"] = error
            job["updatedAt"] = now
            if normalized_status in SIGNALOPS_RANDOM_JOB_TERMINAL_STATUSES:
                self._release_parameter_scan_job_lease_locked(job, now)
            self._set_parameter_scan_job_attempt_terminal_locked(
                job,
                attempt_id=attempt_id,
                status=normalized_status,
                now=now,
                error=error,
                scan_id=scan_id,
                run_ids=run_ids,
                best_run_id=best_run_id,
            )
            self._persist_parameter_scan_jobs_locked()
            return self._public_parameter_scan_job(job)

    async def create_parameter_scan_job(self, request: Dict[str, Any]) -> Dict[str, Any]:
        payload = dict(request or {})
        _parameter_scan_combinations(
            dict(payload.get("parameter_grid") or {}),
            int(payload.get("max_combinations") or 8),
        )
        _parameter_scan_windows(
            str(payload.get("start_date") or ""),
            str(payload.get("end_date") or ""),
            payload.get("windows") if isinstance(payload.get("windows"), list) else [],
        )
        job_id = _generate_id("BTSJOB")
        now = _now()
        idempotency_key = _parameter_scan_job_idempotency_key(payload)
        job = {
            "jobId": job_id,
            "status": "QUEUED",
            "progressStep": "QUEUED",
            "request": payload,
            "scan": None,
            "scanId": "",
            "runIds": [],
            "bestRunId": None,
            "totalCombinations": 0,
            "totalTrials": 0,
            "windowCount": 0,
            "simulationOnly": True,
            "isRealTrade": False,
            "error": None,
            "createdAt": now,
            "updatedAt": now,
            "queueMode": PARAMETER_SCAN_JOB_QUEUE_MODE,
            "storageSchema": PARAMETER_SCAN_JOB_STORE_SCHEMA,
            "durable": True,
            "recovered": False,
            "recoveredAt": None,
            "recoveryAttemptCount": 0,
            "idempotencyKey": idempotency_key,
            "attemptCount": 0,
            "currentAttemptId": None,
            "lastAttemptStatus": None,
            "attempts": [],
            "leaseOwner": "",
            "leaseId": "",
            "leaseStatus": "UNCLAIMED",
            "leaseAcquiredAt": None,
            "leaseExpiresAt": None,
            "leaseReleasedAt": None,
            "leaseSeconds": PARAMETER_SCAN_JOB_LEASE_SECONDS,
        }
        async with self._parameter_scan_jobs_lock:
            self._parameter_scan_jobs[job_id] = job
            self._persist_parameter_scan_jobs_locked()
        self._schedule_parameter_scan_job(job_id)
        return self._public_parameter_scan_job(job)

    async def get_parameter_scan_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        should_schedule = False
        async with self._parameter_scan_jobs_lock:
            job = self._parameter_scan_jobs.get(job_id)
            if job and str(job.get("status") or "").upper() in PARAMETER_SCAN_JOB_RECOVERABLE_STATUSES:
                should_schedule = True
            public_job = self._public_parameter_scan_job(job) if job else None
        if should_schedule:
            self._schedule_parameter_scan_job(job_id)
        return public_job

    async def cancel_parameter_scan_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        async with self._parameter_scan_jobs_lock:
            job = self._parameter_scan_jobs.get(job_id)
            if not job:
                return None
            if job.get("status") not in SIGNALOPS_RANDOM_JOB_TERMINAL_STATUSES:
                now = _now()
                job["status"] = "CANCELLED"
                job["progressStep"] = "CANCELLED"
                job["updatedAt"] = now
                self._release_parameter_scan_job_lease_locked(job, now)
                self._set_parameter_scan_job_attempt_terminal_locked(
                    job,
                    attempt_id=str(job.get("currentAttemptId") or ""),
                    status="CANCELLED",
                    now=now,
                    error=job.get("error"),
                    scan_id=str(job.get("scanId") or ""),
                    run_ids=[str(item) for item in job.get("runIds", [])] if isinstance(job.get("runIds"), list) else [],
                    best_run_id=job.get("bestRunId"),
                )
                task = self._parameter_scan_tasks.get(job_id)
                if task and not task.done():
                    task.cancel()
                self._persist_parameter_scan_jobs_locked()
            return self._public_parameter_scan_job(job)

    async def handoff_parameter_scan_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        async with self._parameter_scan_jobs_lock:
            job = self._parameter_scan_jobs.get(job_id)
            if not job:
                return None
            public_job = json.loads(json.dumps(self._public_parameter_scan_job(job, include_handoff_status=False), default=str))

        handoff_dir = _parameter_scan_job_handoff_dir_from_env()
        created_at = _now()
        base_payload = {
            "schema": "backtest_parameter_scan_job_handoff_v1",
            "createdAt": created_at,
            "jobId": public_job.get("jobId"),
            "scanId": public_job.get("scanId") or "",
            "jobStatus": public_job.get("status") or "",
            "handoffDestination": "LOCAL_DEPLOYMENT_HANDOFF_DIR" if handoff_dir else "NOT_CONFIGURED",
            "handoffRequiresCompletedJob": True,
            "queueMode": public_job.get("queueMode") or PARAMETER_SCAN_JOB_QUEUE_MODE,
            "idempotencyKey": public_job.get("idempotencyKey") or "",
            "bundleChecksum": "",
            "appendOnly": True,
            "simulationOnly": bool(public_job.get("simulationOnly", True)),
            "isRealTrade": bool(public_job.get("isRealTrade", False)),
        }
        if handoff_dir is None:
            return {
                **base_payload,
                "status": "DISABLED",
                "reason": "BACKTEST_PARAMETER_SCAN_HANDOFF_DIR is not configured.",
                "handoffId": "",
                "handoffDir": "",
                "bundleFile": "",
                "manifestFile": "",
                "manifest": {},
            }

        status = str(public_job.get("status") or "").strip().upper()
        scan = public_job.get("scan") if isinstance(public_job.get("scan"), dict) else None
        boundary_ok = bool(public_job.get("simulationOnly", True)) and not bool(public_job.get("isRealTrade", False))
        if status != "COMPLETED" or not scan or not public_job.get("scanId") or not boundary_ok:
            return {
                **base_payload,
                "status": "BLOCKED",
                "reason": "Backtest parameter scan job must be COMPLETED with simulation-only scan evidence before handoff.",
                "handoffId": "",
                "handoffDir": str(handoff_dir),
                "bundleFile": "",
                "manifestFile": "",
                "manifest": {},
            }

        bundle_payload = {
            "schema": "backtest_parameter_scan_job_handoff_bundle_v1",
            "createdAt": created_at,
            "jobId": public_job.get("jobId"),
            "scanId": public_job.get("scanId") or "",
            "jobStatus": status,
            "queueMode": public_job.get("queueMode") or PARAMETER_SCAN_JOB_QUEUE_MODE,
            "storageSchema": public_job.get("storageSchema") or PARAMETER_SCAN_JOB_STORE_SCHEMA,
            "idempotencyKey": public_job.get("idempotencyKey") or "",
            "attemptCount": _int_value(public_job.get("attemptCount"), 0),
            "currentAttemptId": public_job.get("currentAttemptId"),
            "lastAttemptStatus": public_job.get("lastAttemptStatus"),
            "leaseStatus": public_job.get("leaseStatus"),
            "leaseOwner": public_job.get("leaseOwner"),
            "leaseId": public_job.get("leaseId"),
            "totalCombinations": _int_value(public_job.get("totalCombinations"), 0),
            "totalTrials": _int_value(public_job.get("totalTrials"), 0),
            "windowCount": _int_value(public_job.get("windowCount"), 0),
            "runIds": [str(item) for item in public_job.get("runIds", [])] if isinstance(public_job.get("runIds"), list) else [],
            "bestRunId": public_job.get("bestRunId"),
            "job": public_job,
            "scan": scan,
            "retentionPolicy": {
                "policyId": "backtest_parameter_scan_job_deployment_handoff_v1",
                "custody": "deployment_owned_after_handoff",
                "requiresCompletedJob": True,
                "requiresSimulationOnly": True,
            },
            "appendOnly": True,
            "simulationOnly": True,
            "isRealTrade": False,
        }
        bundle_checksum = f"bt-parameter-scan-handoff-{_stable_payload_hash(bundle_payload, length=32)}"
        bundle = {**bundle_payload, "bundleChecksum": bundle_checksum}
        timestamp_slug = "".join(ch for ch in created_at if ch.isalnum())[:14] or "now"
        checksum_slug = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in bundle_checksum)[-32:]
        handoff_id = f"btps-handoff-{timestamp_slug}-{checksum_slug[-12:]}"
        bundle_file = f"{handoff_id}.json"
        manifest_file = f"{handoff_id}.manifest.json"
        manifest = {
            "schema": "backtest_parameter_scan_job_handoff_manifest_v1",
            "handoffId": handoff_id,
            "status": "HANDED_OFF",
            "handedOffAt": created_at,
            "handoffDestination": "LOCAL_DEPLOYMENT_HANDOFF_DIR",
            "bundleFile": bundle_file,
            "manifestFile": manifest_file,
            "bundleChecksum": bundle_checksum,
            "jobId": public_job.get("jobId"),
            "scanId": public_job.get("scanId") or "",
            "jobStatus": status,
            "queueMode": public_job.get("queueMode") or PARAMETER_SCAN_JOB_QUEUE_MODE,
            "idempotencyKey": public_job.get("idempotencyKey") or "",
            "attemptCount": _int_value(public_job.get("attemptCount"), 0),
            "leaseStatus": public_job.get("leaseStatus"),
            "runCount": len(bundle_payload["runIds"]),
            "bestRunId": public_job.get("bestRunId"),
            "retentionPolicy": bundle_payload["retentionPolicy"],
            "appendOnly": True,
            "simulationOnly": True,
            "isRealTrade": False,
        }
        try:
            self._write_json_atomic(handoff_dir / bundle_file, bundle)
            self._write_json_atomic(handoff_dir / manifest_file, manifest)
        except OSError as exc:
            logger.warning("Backtest parameter scan job handoff failed: %s", exc)
            return {
                **base_payload,
                "status": "FAILED",
                "reason": f"handoff_write_failed: {exc}",
                "handoffId": handoff_id,
                "handoffDir": str(handoff_dir),
                "bundleFile": bundle_file,
                "manifestFile": manifest_file,
                "manifest": {},
            }
        return {
            **base_payload,
            "status": "HANDED_OFF",
            "reason": "",
            "handoffId": handoff_id,
            "handoffDir": str(handoff_dir),
            "bundleFile": bundle_file,
            "manifestFile": manifest_file,
            "bundleChecksum": bundle_checksum,
            "manifest": manifest,
        }

    def _public_parameter_scan_job(
        self,
        job: Optional[Dict[str, Any]],
        *,
        include_handoff_status: bool = True,
    ) -> Dict[str, Any]:
        if not job:
            return {}
        public = {key: value for key, value in job.items() if not key.startswith("_")}
        if include_handoff_status:
            public["handoffStatus"] = self._parameter_scan_job_handoff_status(public)
        return public

    async def _update_parameter_scan_job(self, job_id: str, **updates: Any) -> Dict[str, Any]:
        async with self._parameter_scan_jobs_lock:
            job = self._parameter_scan_jobs[job_id]
            job.update(updates)
            job["updatedAt"] = _now()
            self._persist_parameter_scan_jobs_locked()
            return self._public_parameter_scan_job(job)

    async def _run_parameter_scan_job(self, job_id: str) -> None:
        attempt_id: Optional[str] = None
        try:
            async with self._parameter_scan_jobs_lock:
                job = self._parameter_scan_jobs.get(job_id)
                if not job or str(job.get("status") or "").upper() in SIGNALOPS_RANDOM_JOB_TERMINAL_STATUSES:
                    return
            attempt_id = await self._start_parameter_scan_job_attempt(job_id)
            if not attempt_id:
                return
            async with self._parameter_scan_jobs_lock:
                payload = dict(self._parameter_scan_jobs[job_id].get("request") or {})
            result = await self.create_parameter_scan(
                symbol=str(payload.get("symbol") or ""),
                stock_name=str(payload.get("stock_name") or ""),
                patch_id=payload.get("patch_id"),
                case_id=payload.get("case_id"),
                start_date=str(payload.get("start_date") or ""),
                end_date=str(payload.get("end_date") or ""),
                initial_capital=float(payload.get("initial_capital") or 100000.0),
                scenario_label=str(payload.get("scenario_label") or "Async parameter scan"),
                base_parameters=dict(payload.get("base_parameters") or {}),
                parameter_grid=dict(payload.get("parameter_grid") or {}),
                windows=payload.get("windows") if isinstance(payload.get("windows"), list) else [],
                max_combinations=int(payload.get("max_combinations") or 8),
                ranking_metric=str(payload.get("ranking_metric") or "research_grade_score"),
                reuse_existing=bool(payload.get("reuse_existing", True)),
                force_new=bool(payload.get("force_new", False)),
            )
            summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
            scan_id = str(result.get("scan_id") or "")
            run_ids = [str(item) for item in result.get("run_ids", [])]
            best_run_id = result.get("best_run_id")
            await self._finish_parameter_scan_job_attempt(
                job_id,
                attempt_id,
                status="COMPLETED",
                error=None,
                scan_id=scan_id,
                run_ids=run_ids,
                best_run_id=best_run_id,
                updates={
                    "scan": result,
                    "scanId": scan_id,
                    "runIds": run_ids,
                    "bestRunId": best_run_id,
                    "totalCombinations": int(summary.get("totalCombinations") or len(result.get("combinations") or [])),
                    "totalTrials": int(summary.get("totalTrials") or result.get("trial_count") or len(result.get("run_ids") or [])),
                    "windowCount": int(summary.get("windowCount") or result.get("window_count") or 0),
                    "simulationOnly": bool(result.get("simulation_only", True)),
                    "isRealTrade": bool(result.get("is_real_trade", False)),
                },
            )
        except asyncio.CancelledError:
            await self._finish_parameter_scan_job_attempt(job_id, attempt_id, status="CANCELLED")
        except Exception as exc:
            logger.exception("Backtest parameter scan job failed")
            await self._finish_parameter_scan_job_attempt(
                job_id,
                attempt_id,
                status="FAILED",
                error=str(exc),
            )

    async def create_signalops_random_validation_job(self, request: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = dict(request or {})
        mode = str(payload.get("mode") or "VALIDATE_AND_FEEDBACK").strip().upper()
        if mode not in {"VALIDATE_ONLY", "VALIDATE_AND_FEEDBACK"}:
            raise ValueError("mode must be VALIDATE_ONLY or VALIDATE_AND_FEEDBACK.")
        seed = payload.get("seed")
        if seed is None:
            seed = random.SystemRandom().randint(1, 2_147_483_647)
        try:
            seed = int(seed)
        except (TypeError, ValueError) as exc:
            raise ValueError("seed must be an integer.") from exc
        job_id = _generate_id("SIGOPS_RAND")
        now = _now()
        job = {
            "jobId": job_id,
            "status": "QUEUED",
            "progressStep": "QUEUED",
            "seed": seed,
            "mode": mode,
            "simulationOnly": True,
            "isRealTrade": False,
            "sampleWindows": [],
            "dataQuality": {},
            "baselineResults": {},
            "candidateResults": {},
            "evidenceLevel": "PENDING",
            "appliedAdjustment": {},
            "rejectionReasons": [],
            "reviewQueueSyncStatus": "NOT_SYNCED",
            "error": None,
            "createdAt": now,
            "updatedAt": now,
            "_request": payload,
        }
        async with self._random_validation_lock:
            self._random_validation_jobs[job_id] = job
        task = asyncio.create_task(self._run_signalops_random_validation_job(job_id))
        self._random_validation_tasks[job_id] = task
        return self._public_random_validation_job(job)

    async def get_signalops_random_validation_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        async with self._random_validation_lock:
            job = self._random_validation_jobs.get(job_id)
            return self._public_random_validation_job(job) if job else None

    async def cancel_signalops_random_validation_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        async with self._random_validation_lock:
            job = self._random_validation_jobs.get(job_id)
            if not job:
                return None
            if job.get("status") not in SIGNALOPS_RANDOM_JOB_TERMINAL_STATUSES:
                job["status"] = "CANCELLED"
                job["progressStep"] = "CANCELLED"
                job["updatedAt"] = _now()
                task = self._random_validation_tasks.get(job_id)
                if task and not task.done():
                    task.cancel()
            return self._public_random_validation_job(job)

    def _public_random_validation_job(self, job: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not job:
            return {}
        return {key: value for key, value in job.items() if not key.startswith("_")}

    async def _update_random_validation_job(self, job_id: str, **updates: Any) -> Dict[str, Any]:
        async with self._random_validation_lock:
            job = self._random_validation_jobs[job_id]
            job.update(updates)
            job["updatedAt"] = _now()
            return self._public_random_validation_job(job)

    async def _run_signalops_random_validation_job(self, job_id: str) -> None:
        try:
            await self._update_random_validation_job(job_id, status="RUNNING", progressStep="UNIVERSE")
            result = await self._execute_signalops_random_validation_job(job_id)
            result["status"] = "COMPLETED"
            result["progressStep"] = "COMPLETED"
            try:
                from .auto_paper_trading import auto_paper_trading_store

                result["reviewQueueSyncStatus"] = "SYNCED"
                await auto_paper_trading_store.record_random_validation_result(result)
            except Exception:
                logger.exception("failed to sync SignalOps random validation result")
                result["reviewQueueSyncStatus"] = "FAILED"
                result["rejectionReasons"] = [
                    *[str(item) for item in result.get("rejectionReasons", [])],
                    "review_queue_sync_failed",
                ]
            await self._update_random_validation_job(job_id, **result)
        except asyncio.CancelledError:
            await self._update_random_validation_job(job_id, status="CANCELLED", progressStep="CANCELLED")
        except Exception as exc:
            logger.exception("SignalOps random validation job failed")
            await self._update_random_validation_job(
                job_id,
                status="FAILED",
                progressStep="FAILED",
                error=str(exc),
                evidenceLevel="WEAK",
                rejectionReasons=[str(exc)],
            )

    async def _ensure_random_validation_not_cancelled(self, job_id: str) -> None:
        async with self._random_validation_lock:
            job = self._random_validation_jobs.get(job_id) or {}
            if job.get("status") == "CANCELLED":
                raise asyncio.CancelledError()

    async def _sample_signalops_random_window(
        self,
        *,
        rng: random.Random,
        universe: List[Dict[str, Any]],
        exclude_symbols: set[str],
        history_years: int,
        min_window_days: int,
        max_window_days: int,
        min_trading_days: int,
    ) -> Dict[str, Any]:
        available = [item for item in universe if item.get("symbol") not in exclude_symbols]
        if not available:
            raise ValueError("No A-share symbols are available for random validation.")
        buckets: Dict[str, List[Dict[str, Any]]] = {}
        for item in available:
            key = "|".join([
                str(item.get("industry") or "UNKNOWN"),
                str(item.get("market") or item.get("exchange") or "UNKNOWN"),
            ])
            buckets.setdefault(key, []).append(item)
        today = datetime.now(timezone.utc).date()
        earliest = today - timedelta(days=max(1, history_years) * 365)
        latest_start = today - timedelta(days=min_window_days)
        if latest_start <= earliest:
            latest_start = earliest + timedelta(days=1)
        failures: List[Dict[str, Any]] = []
        for attempt in range(1, SIGNALOPS_RANDOM_MAX_SAMPLE_ATTEMPTS + 1):
            bucket_key = rng.choice(sorted(buckets))
            stock = rng.choice(sorted(buckets[bucket_key], key=lambda item: item["symbol"]))
            window_days = rng.randint(min_window_days, max(min_window_days, max_window_days))
            span = max(1, (latest_start - earliest).days)
            start_date = (earliest + timedelta(days=rng.randint(0, span))).isoformat()
            end_date = (_date_value(start_date) + timedelta(days=window_days)).date().isoformat()
            if end_date > today.isoformat():
                end_date = today.isoformat()
            list_date = _iso_date(stock.get("list_date") or "")
            if list_date and list_date > start_date:
                failures.append({
                    "attempt": attempt,
                    "symbol": stock.get("symbol"),
                    "reason": "listed_after_sample_start",
                    "list_date": list_date,
                    "start_date": start_date,
                })
                continue
            try:
                rows = await fetch_historical_for_backtest(str(stock["symbol"]), start_date, end_date)
            except Exception as exc:
                failures.append({
                    "attempt": attempt,
                    "symbol": stock.get("symbol"),
                    "start_date": start_date,
                    "end_date": end_date,
                    "reason": str(exc),
                })
                continue
            trading_days = len({row.get("date") for row in rows if row.get("date")})
            if trading_days < min_trading_days:
                failures.append({
                    "attempt": attempt,
                    "symbol": stock.get("symbol"),
                    "start_date": start_date,
                    "end_date": end_date,
                    "trading_days": trading_days,
                    "reason": "insufficient_trading_days",
                })
                continue
            return {
                "symbol": stock["symbol"],
                "stock_name": stock.get("stock_name") or stock["symbol"],
                "start": start_date,
                "end": end_date,
                "windowDays": (_date_value(end_date) - _date_value(start_date)).days + 1,
                "tradingDays": trading_days,
                "stratum": bucket_key,
                "marketData": rows,
                "dataSource": "TUSHARE",
                "attempt": attempt,
                "failures": failures,
                "simulation_only": True,
                "is_real_trade": False,
            }
        raise ValueError(f"Unable to sample a one-year A-share validation window after {SIGNALOPS_RANDOM_MAX_SAMPLE_ATTEMPTS} attempts.")

    async def _execute_signalops_random_validation_job(self, job_id: str) -> Dict[str, Any]:
        async with self._random_validation_lock:
            job = dict(self._random_validation_jobs[job_id])
        request = job.get("_request") if isinstance(job.get("_request"), dict) else {}
        mode = str(job.get("mode") or "VALIDATE_AND_FEEDBACK")
        seed = int(job.get("seed") or 1)
        rng = random.Random(seed)
        history_years = max(1, min(20, int(request.get("history_years") or 10)))
        min_window_days = max(SIGNALOPS_RANDOM_DEFAULT_MIN_WINDOW_DAYS, int(request.get("min_window_days") or SIGNALOPS_RANDOM_DEFAULT_MIN_WINDOW_DAYS))
        max_window_days = max(min_window_days, int(request.get("max_window_days") or SIGNALOPS_RANDOM_DEFAULT_MAX_WINDOW_DAYS))
        min_trading_days = max(1, int(request.get("min_trading_days") or SIGNALOPS_RANDOM_DEFAULT_MIN_TRADING_DAYS))
        initial_capital = float(request.get("initial_capital") or 100000.0)
        benchmark_symbol = str(request.get("benchmark_symbol") or "").strip()

        universe = await fetch_a_share_stock_universe()
        if not universe:
            raise ValueError("A-share stock universe is empty.")
        universe_hash = _stable_payload_hash(
            [item.get("symbol") for item in universe],
            length=16,
        )
        await self._ensure_random_validation_not_cancelled(job_id)
        await self._update_random_validation_job(
            job_id,
            progressStep="SAMPLE_1",
            dataQuality={
                "universeSize": len(universe),
                "universeHash": universe_hash,
                "provider": "TUSHARE",
            },
        )

        first_sample = await self._sample_signalops_random_window(
            rng=rng,
            universe=universe,
            exclude_symbols=set(),
            history_years=history_years,
            min_window_days=min_window_days,
            max_window_days=max_window_days,
            min_trading_days=min_trading_days,
        )
        await self._ensure_random_validation_not_cancelled(job_id)
        await self._update_random_validation_job(job_id, progressStep="REPLAY_1", sampleWindows=[self._public_sample_window(first_sample)])

        from .auto_paper_trading import auto_paper_trading_store

        config_payload = _model_dump(auto_paper_trading_store.get_config())
        signalops_context = _signalops_public_context(_load_signalops_backtest_context(str(first_sample["symbol"])))
        baseline_config = _signalops_random_config_snapshot(config_payload)
        baseline_config["signalops_context"] = signalops_context
        if benchmark_symbol:
            baseline_config["benchmark_symbol"] = benchmark_symbol
        first_signals = _signalops_random_signals_from_market_data(
            symbol=str(first_sample["symbol"]),
            market_data=first_sample["marketData"],
            config=baseline_config,
            role="baseline_sample_1",
        )
        first_run = await self.create_run(
            symbol=str(first_sample["symbol"]),
            stock_name=str(first_sample.get("stock_name") or ""),
            start_date=str(first_sample["start"]),
            end_date=str(first_sample["end"]),
            initial_capital=initial_capital,
            scenario_label="SignalOps random validation sample 1",
            parameters={
                **baseline_config,
                "random_validation_job_id": job_id,
                "random_validation_role": "baseline_sample_1",
            },
            market_data=first_sample["marketData"],
            market_data_source=first_sample["dataSource"],
            signals=first_signals,
        )
        candidate_config = _signalops_random_candidate_config(baseline_config, first_run.get("report") or {})
        candidate_config["signalops_context"] = signalops_context
        await self._ensure_random_validation_not_cancelled(job_id)
        await self._update_random_validation_job(job_id, progressStep="SAMPLE_2")

        second_sample = await self._sample_signalops_random_window(
            rng=rng,
            universe=universe,
            exclude_symbols={str(first_sample["symbol"])},
            history_years=history_years,
            min_window_days=min_window_days,
            max_window_days=max_window_days,
            min_trading_days=min_trading_days,
        )
        sample_windows = [self._public_sample_window(first_sample), self._public_sample_window(second_sample)]
        await self._ensure_random_validation_not_cancelled(job_id)
        await self._update_random_validation_job(job_id, progressStep="BASELINE_2", sampleWindows=sample_windows)

        second_context = _signalops_public_context(_load_signalops_backtest_context(str(second_sample["symbol"])))
        baseline_config["signalops_context"] = second_context
        candidate_config["signalops_context"] = second_context
        baseline_signals = _signalops_random_signals_from_market_data(
            symbol=str(second_sample["symbol"]),
            market_data=second_sample["marketData"],
            config=baseline_config,
            role="baseline_sample_2",
        )
        baseline_run = await self.create_run(
            symbol=str(second_sample["symbol"]),
            stock_name=str(second_sample.get("stock_name") or ""),
            start_date=str(second_sample["start"]),
            end_date=str(second_sample["end"]),
            initial_capital=initial_capital,
            scenario_label="SignalOps random validation baseline",
            parameters={
                **baseline_config,
                "random_validation_job_id": job_id,
                "random_validation_role": "baseline_sample_2",
            },
            market_data=second_sample["marketData"],
            market_data_source=second_sample["dataSource"],
            signals=baseline_signals,
        )
        await self._ensure_random_validation_not_cancelled(job_id)
        await self._update_random_validation_job(job_id, progressStep="CANDIDATE_2")
        candidate_signals = _signalops_random_signals_from_market_data(
            symbol=str(second_sample["symbol"]),
            market_data=second_sample["marketData"],
            config=candidate_config,
            role="candidate_sample_2",
        )
        candidate_run = await self.create_run(
            symbol=str(second_sample["symbol"]),
            stock_name=str(second_sample.get("stock_name") or ""),
            start_date=str(second_sample["start"]),
            end_date=str(second_sample["end"]),
            initial_capital=initial_capital,
            scenario_label="SignalOps random validation candidate",
            parameters={
                **candidate_config,
                "random_validation_job_id": job_id,
                "random_validation_role": "candidate_sample_2",
            },
            market_data=second_sample["marketData"],
            market_data_source=second_sample["dataSource"],
            signals=candidate_signals,
        )
        await self._ensure_random_validation_not_cancelled(job_id)

        first_summary = _random_validation_run_summary(first_run)
        baseline_summary = _random_validation_run_summary(baseline_run)
        candidate_summary = _random_validation_run_summary(candidate_run)
        trusted_data = all(
            str(item.get("dataSource") or "").upper() not in {"MOCK", "MOCK_FALLBACK", ""}
            for item in (first_summary, baseline_summary, candidate_summary)
        )
        enough_days = all(int(item.get("tradingDays") or 0) >= min_trading_days for item in (first_summary, baseline_summary, candidate_summary))
        complete_trade_loop = int(candidate_summary.get("buySignals") or 0) > 0 and int(candidate_summary.get("sellSignals") or 0) > 0 and int(candidate_summary.get("totalTrades") or 0) >= 2
        candidate_not_worse = (
            float(candidate_summary.get("totalReturnPct") or 0.0) >= float(baseline_summary.get("totalReturnPct") or 0.0) - 0.01
            and float(candidate_summary.get("maxDrawdownPct") or 0.0) <= float(baseline_summary.get("maxDrawdownPct") or 0.0) + 0.005
        )
        beats_buy_hold = float(candidate_summary.get("totalReturnPct") or 0.0) >= float(candidate_summary.get("buyHoldReturnPct") or 0.0)
        rejection_reasons: List[str] = []
        if not trusted_data:
            rejection_reasons.append("untrusted_market_data")
        if not enough_days:
            rejection_reasons.append("insufficient_trading_days")
        if not complete_trade_loop:
            rejection_reasons.append("missing_complete_trade_loop")
        if not candidate_not_worse:
            rejection_reasons.append("candidate_worse_than_baseline")
        if trusted_data and enough_days and complete_trade_loop and candidate_not_worse and (
            beats_buy_hold or int(candidate_summary.get("totalTrades") or 0) > 0
        ):
            evidence_level = "MEDIUM"
        else:
            evidence_level = "WEAK"
        should_apply = (
            mode == "VALIDATE_AND_FEEDBACK"
            and evidence_level == "MEDIUM"
            and trusted_data
            and enough_days
            and complete_trade_loop
            and candidate_not_worse
        )
        if mode == "VALIDATE_ONLY":
            rejection_reasons.append("validate_only_mode")
        if evidence_level == "WEAK" and "weak_evidence" not in rejection_reasons:
            rejection_reasons.append("weak_evidence")
        diff = _signalops_random_config_diff(baseline_config, candidate_config)
        applied_adjustment = {
            "shouldApply": should_apply,
            "applied": False,
            "deltas": diff,
            "beforeConfig": {key: baseline_config.get(key) for key in sorted(SIGNALOPS_RANDOM_TUNABLE_FIELDS)},
            "afterConfig": {key: candidate_config.get(key) for key in sorted(SIGNALOPS_RANDOM_TUNABLE_FIELDS)},
            "reason": "random_validation_candidate_not_worse" if should_apply else ",".join(rejection_reasons),
            "rollbackToken": _stable_payload_hash({"job_id": job_id, "before": baseline_config}, length=16),
            "simulation_only": True,
            "is_real_trade": False,
        }
        data_quality = {
            "provider": "TUSHARE",
            "universeSize": len(universe),
            "universeHash": universe_hash,
            "trusted": trusted_data,
            "minTradingDays": min_trading_days,
            "enoughTradingDays": enough_days,
            "completeTradeLoop": complete_trade_loop,
            "sampleFailures": [
                *first_sample.get("failures", []),
                *second_sample.get("failures", []),
            ][-10:],
            "simulation_only": True,
            "is_real_trade": False,
        }
        await self._update_random_validation_job(job_id, progressStep="SYNC_SIGNALOPS")
        return {
            "jobId": job_id,
            "seed": seed,
            "mode": mode,
            "simulationOnly": True,
            "isRealTrade": False,
            "sampleWindows": sample_windows,
            "dataQuality": data_quality,
            "baselineResults": {
                "sample1": first_summary,
                "sample2": baseline_summary,
                "emptyBaseline": {"returnPct": 0.0},
                "buyHold": {
                    "sample2ReturnPct": baseline_summary.get("buyHoldReturnPct", 0.0),
                    "available": baseline_summary.get("buyHoldAvailable", False),
                },
            },
            "candidateResults": {
                "sample2": candidate_summary,
                "candidateNotWorse": candidate_not_worse,
                "beatsBuyHold": beats_buy_hold,
            },
            "evidenceLevel": evidence_level,
            "appliedAdjustment": applied_adjustment,
            "rejectionReasons": rejection_reasons,
            "reviewQueueSyncStatus": "NOT_SYNCED",
            "baselineConfig": baseline_config,
            "candidateConfig": candidate_config,
            "createdAt": job.get("createdAt") or _now(),
            "updatedAt": _now(),
        }

    def _public_sample_window(self, sample: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "symbol": sample.get("symbol"),
            "stockName": sample.get("stock_name"),
            "start": sample.get("start"),
            "end": sample.get("end"),
            "windowDays": sample.get("windowDays"),
            "tradingDays": sample.get("tradingDays"),
            "stratum": sample.get("stratum"),
            "dataSource": sample.get("dataSource"),
            "attempt": sample.get("attempt"),
            "simulation_only": True,
            "is_real_trade": False,
        }

    async def create_signalops_sample(
        self,
        symbol: Optional[str] = None,
        signal_id: Optional[str] = None,
        source_run_id: Optional[str] = None,
        start_date: str = "",
        end_date: str = "",
        signal_date: str = "",
        initial_capital: float = 100000.0,
        data_source: str = "AUTO",
        reuse_existing: bool = True,
        force_new: bool = False,
    ) -> Dict[str, Any]:
        requested_symbol = str(symbol or "").strip()
        auto_context = _load_signalops_backtest_context(requested_symbol)
        source_signal = _select_signalops_auto_sample_record(
            auto_context,
            symbol=requested_symbol or None,
            signal_id=signal_id,
            source_run_id=source_run_id,
        )
        sample_kind = "SIGNALOPS_AUTO_PAPER_REVIEW"
        source_mode = "AUTO_PAPER"
        if not source_signal:
            source_signal = await self._select_signalops_sample_signal(
                symbol=symbol,
                signal_id=signal_id,
                source_run_id=source_run_id,
            )
            sample_kind = "SIGNALOPS_LIFECYCLE_REVIEW"
            source_mode = "LIFECYCLE"
        if not source_signal:
            raise ValueError("No eligible SignalOps auto-paper or lifecycle signal is available for a backtest sample.")

        sample_symbol = str(source_signal.get("symbol") or symbol or "").strip()
        if sample_symbol == "POOL":
            pool = auto_context.get("stockPool") if isinstance(auto_context.get("stockPool"), list) else []
            first_pool = pool[0] if pool and isinstance(pool[0], dict) else {}
            sample_symbol = str(first_pool.get("symbol") or symbol or "").strip()
        if not sample_symbol:
            raise ValueError("SignalOps sample signal has no symbol.")

        sample_signal_date = _iso_date(
            signal_date
            or _signalops_record_date(source_signal)
            or source_signal.get("updated_at")
            or source_signal.get("created_at")
            or _now()
        )
        sample_start = _iso_date(start_date) or sample_signal_date
        sample_end = _iso_date(end_date)
        if not sample_end:
            try:
                sample_end = (datetime.fromisoformat(sample_start[:10]) + timedelta(days=30)).date().isoformat()
            except ValueError:
                sample_end = sample_start

        parameters = {
            "signal_source": "SIGNALOPS",
            "signal_id": source_signal.get("signal_id"),
            "signalops_record_id": source_signal.get("record_id"),
            "signal_date": sample_signal_date,
            "data_source": str(data_source or "AUTO").upper(),
            "signalops_version": SIGNALOPS_BACKTEST_VERSION,
            "signalops_source_mode": source_mode,
            "sample_kind": sample_kind,
        }
        if source_signal.get("source_run_id"):
            parameters["source_run_id"] = source_signal["source_run_id"]
        if source_run_id:
            parameters["source_run_id"] = source_run_id

        run = await self.create_run(
            symbol=sample_symbol,
            stock_name=str(source_signal.get("stock_name") or ""),
            start_date=sample_start,
            end_date=sample_end,
            initial_capital=initial_capital,
            scenario_label="SignalOps auto-paper sample" if source_mode == "AUTO_PAPER" else "SignalOps lifecycle sample",
            parameters=parameters,
            reuse_existing=reuse_existing,
            force_new=force_new,
        )
        report = run.get("report") or {}
        return {
            "run_id": run["run_id"],
            "signal_source": report.get("signal_source", "SIGNALOPS"),
            "market_data_source": report.get("data_source", "UNKNOWN"),
            "sample_window": report.get("sampleWindow", {}),
            "evidence_strength": report.get("evidenceStrength", {}),
            "limitations": report.get("limitations", []),
            "run": run,
        }

    async def create_signalops_experiment(
        self,
        *,
        symbol: str,
        stock_name: str = "",
        train_window: Dict[str, Any],
        validation_window: Dict[str, Any],
        baseline_config: Dict[str, Any],
        candidate_config: Dict[str, Any],
        experiment_package_hash: str,
        initial_capital: float = 100000.0,
        benchmark_symbol: str = "000300.SH",
        reviewer: str = "auto_backtest_runner",
        market_data: Optional[List[Dict[str, Any]]] = None,
        benchmark_market_data: Optional[List[Dict[str, Any]]] = None,
        cleaned_record_history: Optional[List[Dict[str, Any]]] = None,
        baseline_train_signals: Optional[List[Dict[str, Any]]] = None,
        candidate_train_signals: Optional[List[Dict[str, Any]]] = None,
        baseline_validation_signals: Optional[List[Dict[str, Any]]] = None,
        candidate_validation_signals: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        experiment_hash = str(experiment_package_hash or "").strip()
        if not experiment_hash:
            raise ValueError("experiment_package_hash is required.")
        train = _window_bounds(train_window, "train_window")
        validation = _window_bounds(validation_window, "validation_window")
        if train["end"] >= validation["start"]:
            raise ValueError("train_window must end before validation_window starts.")

        benchmark = str(benchmark_symbol or "000300.SH").strip() or "000300.SH"
        baseline_config = dict(baseline_config or {})
        candidate_config = dict(candidate_config or {})
        package_basis = {
            "symbol": symbol,
            "train_window": train,
            "validation_window": validation,
            "baseline_config": _stable_experiment_payload(baseline_config),
            "candidate_config": _stable_experiment_payload(candidate_config),
            "benchmark_symbol": benchmark,
            "cost_model": {
                "baseline": {
                    "commission_bps": baseline_config.get("commission_bps"),
                    "stamp_tax_bps": baseline_config.get("stamp_tax_bps"),
                    "slippage_bps": baseline_config.get("slippage_bps"),
                },
                "candidate": {
                    "commission_bps": candidate_config.get("commission_bps"),
                    "stamp_tax_bps": candidate_config.get("stamp_tax_bps"),
                    "slippage_bps": candidate_config.get("slippage_bps"),
                },
            },
        }
        computed_hash = _stable_payload_hash(package_basis, length=16)
        case_id = f"signalops-experiment-{experiment_hash}"
        patch_id = f"SIGOPS_EXP_{experiment_hash[:24]}"
        warnings: list[str] = []
        benchmark_error = ""
        benchmark_data_source = ""
        if benchmark_market_data is not None:
            benchmark_data_source = "CUSTOM"
        elif benchmark != symbol:
            try:
                benchmark_market_data = await fetch_historical_for_backtest(benchmark, train["start"], validation["end"])
                benchmark_data_source = "TUSHARE"
            except Exception as exc:
                logger.exception("fetch benchmark historical data failed for %s", benchmark)
                benchmark_error = str(exc)
                warnings.append("benchmark_unavailable")

        replay_records = cleaned_record_history
        if replay_records is None:
            try:
                from .auto_paper_trading import auto_paper_trading_store

                auto_config = auto_paper_trading_store.get_config()
                replay_records = auto_config.cleaned_record_history
            except Exception:
                logger.exception("failed to load SignalOps cleaned_record_history for experiment replay")
                replay_records = None

        replay_package: Dict[str, Any] = {}
        if isinstance(replay_records, list) and replay_records:
            replay_package = _build_signalops_replay_signals(
                records=replay_records,
                symbol=symbol,
                train_window=train,
                validation_window=validation,
            )
            if baseline_train_signals is None:
                baseline_train_signals = [] if _config_uses_no_signals(baseline_config) else _clean_replay_signal_list(replay_package["baseline_train"])
            if candidate_train_signals is None:
                candidate_train_signals = [] if _config_uses_no_signals(candidate_config) else _clean_replay_signal_list(replay_package["candidate_train"])
            if baseline_validation_signals is None:
                baseline_validation_signals = [] if _config_uses_no_signals(baseline_config) else _clean_replay_signal_list(replay_package["baseline_validation"])
            if candidate_validation_signals is None:
                candidate_validation_signals = [] if _config_uses_no_signals(candidate_config) else _clean_replay_signal_list(replay_package["candidate_validation"])
            if replay_package.get("dropped_records"):
                warnings.append("cleaned_record_history_records_dropped")
            package_basis["sample_record_ids"] = [
                str(record.get("record_id") or "")
                for record in [
                    *replay_package.get("train_records", []),
                    *replay_package.get("validation_records", []),
                ]
                if isinstance(record, dict)
            ]
            computed_hash = _stable_payload_hash(package_basis, length=16)

        def params(config: Dict[str, Any], role: str, window: Dict[str, str]) -> Dict[str, Any]:
            next_params = dict(config)
            next_params.setdefault("signal_source", "SIGNALOPS")
            next_params.setdefault("data_source", "AUTO")
            if str(next_params.get("signal_source") or "").strip().upper() == "SIGNALOPS":
                next_params.setdefault("signalops_version", SIGNALOPS_BACKTEST_VERSION)
                next_params.setdefault("signalops_source_mode", "AUTO_PAPER")
            next_params["benchmark_symbol"] = benchmark
            next_params["experiment_package_hash"] = experiment_hash
            next_params["out_of_sample_start"] = validation["start"]
            next_params["out_of_sample_end"] = validation["end"]
            next_params["walk_forward"] = {
                "enabled": True,
                "mode": "signalops_candidate_baseline",
                "role": role,
                "train_window": train,
                "validation_window": validation,
                "current_window": window,
            }
            return next_params

        baseline_train = await self.create_run(
            symbol=symbol,
            stock_name=stock_name,
            patch_id=f"{patch_id}_BASE_TRAIN",
            case_id=case_id,
            start_date=train["start"],
            end_date=train["end"],
            initial_capital=initial_capital,
            scenario_label="SignalOps baseline train",
            parameters=params(baseline_config, "baseline_train", train),
            market_data=market_data,
            signals=baseline_train_signals,
            benchmark_market_data=benchmark_market_data,
            benchmark_data_source=benchmark_data_source,
            benchmark_error=benchmark_error or None,
        )
        candidate_train = await self.create_run(
            symbol=symbol,
            stock_name=stock_name,
            patch_id=f"{patch_id}_CAND_TRAIN",
            case_id=case_id,
            start_date=train["start"],
            end_date=train["end"],
            initial_capital=initial_capital,
            scenario_label="SignalOps candidate train",
            parameters=params(candidate_config, "candidate_train", train),
            market_data=market_data,
            signals=candidate_train_signals,
            benchmark_market_data=benchmark_market_data,
            benchmark_data_source=benchmark_data_source,
            benchmark_error=benchmark_error or None,
        )
        baseline_validation = await self.create_run(
            symbol=symbol,
            stock_name=stock_name,
            patch_id=f"{patch_id}_BASE_VAL",
            case_id=case_id,
            start_date=validation["start"],
            end_date=validation["end"],
            initial_capital=initial_capital,
            scenario_label="SignalOps baseline validation",
            parameters=params(baseline_config, "baseline_validation", validation),
            market_data=market_data,
            signals=baseline_validation_signals,
            benchmark_market_data=benchmark_market_data,
            benchmark_data_source=benchmark_data_source,
            benchmark_error=benchmark_error or None,
        )
        candidate_validation = await self.create_run(
            symbol=symbol,
            stock_name=stock_name,
            patch_id=f"{patch_id}_CAND_VAL",
            case_id=case_id,
            start_date=validation["start"],
            end_date=validation["end"],
            initial_capital=initial_capital,
            scenario_label="SignalOps candidate validation",
            parameters=params(candidate_config, "candidate_validation", validation),
            market_data=market_data,
            signals=candidate_validation_signals,
            benchmark_market_data=benchmark_market_data,
            benchmark_data_source=benchmark_data_source,
            benchmark_error=benchmark_error or None,
        )

        baseline_report = baseline_validation.get("report") or {}
        candidate_report = candidate_validation.get("report") or {}
        candidate_train_report = candidate_train.get("report") or {}
        train_trade_count = int(candidate_train_report.get("total_trades") or 0)
        validation_trade_count = int(candidate_report.get("total_trades") or 0)
        baseline_expectancy = _experiment_expectancy_pct(baseline_report)
        candidate_expectancy = _experiment_expectancy_pct(candidate_report)
        win_rate_not_down = float(candidate_report.get("hit_rate") or 0.0) >= float(baseline_report.get("hit_rate") or 0.0)
        expectancy_improved = candidate_expectancy > baseline_expectancy
        drawdown_not_worse = float(candidate_report.get("max_drawdown_pct") or 0.0) <= float(baseline_report.get("max_drawdown_pct") or 0.0) + 0.000001
        after_cost_positive = float(candidate_report.get("total_return_pct") or 0.0) > 0
        market_usable = _experiment_market_usable(candidate_train_report) and _experiment_market_usable(candidate_report)
        candidate_benchmark = candidate_report.get("benchmark") if isinstance(candidate_report.get("benchmark"), dict) else {}
        benchmark_available = bool(benchmark and candidate_benchmark.get("available") and market_usable)
        replay_sample_quality = str(replay_package.get("sample_quality") or "MEDIUM").upper() if replay_package else "MEDIUM"
        sample_quality = (
            "MEDIUM"
            if (
                train_trade_count >= 5
                and validation_trade_count >= 3
                and market_usable
                and benchmark_available
                and replay_sample_quality not in {"LOW", "SUPPORTING_ONLY"}
            )
            else "LOW"
        )
        stability_report = stability_validation_report(
            baseline_report=baseline_report,
            candidate_report=candidate_report,
            candidate_train_report=candidate_train_report,
            train_window=train,
            validation_window=validation,
            candidate_config=candidate_config,
            market_data=market_data if isinstance(market_data, list) else [],
            candidate_train_signals=candidate_train_signals,
            candidate_validation_signals=candidate_validation_signals,
        )
        purged_embargo_satisfied = bool(
            (stability_report.get("purged_walk_forward") or {}).get("embargo_satisfied")
        )
        multiple_testing_passed = bool(
            (stability_report.get("multiple_testing") or {}).get("passed")
        )
        checks = {
            "train_trade_count_min": 5,
            "validation_trade_count_min": 3,
            "train_trade_count_ready": train_trade_count >= 5,
            "validation_trade_count_ready": validation_trade_count >= 3,
            "non_overlapping_windows": True,
            "purged_embargo_satisfied": purged_embargo_satisfied,
            "benchmark_available": benchmark_available,
            "market_data_usable": market_usable,
            "win_rate_not_down": win_rate_not_down,
            "expectancy_improved": expectancy_improved,
            "drawdown_not_worse": drawdown_not_worse,
            "after_cost_positive": after_cost_positive,
            "multiple_testing_passed": multiple_testing_passed,
            "sample_quality_not_low": sample_quality != "LOW",
        }
        reasons: list[str] = []
        if train_trade_count < 5:
            reasons.append("insufficient_train_trade_count")
        if validation_trade_count < 3:
            reasons.append("insufficient_validation_trade_count")
        if not market_usable:
            reasons.append("market_data_unavailable")
        benchmark_unavailable_reason = ""
        if not benchmark_available:
            reasons.append("benchmark_unavailable")
            benchmark_unavailable_reason = str(
                candidate_benchmark.get("reason")
                or benchmark_error
                or "benchmark data is unavailable for SignalOps experiment validation"
            )
        if replay_sample_quality in {"LOW", "SUPPORTING_ONLY"}:
            reasons.append("low_quality_replay_evidence")
        if not purged_embargo_satisfied:
            reasons.append("purged_embargo_overlap_risk")
        if not win_rate_not_down:
            reasons.append("validation_win_rate_declined")
        if not expectancy_improved:
            reasons.append("validation_expectancy_not_improved")
        if not drawdown_not_worse:
            reasons.append("validation_drawdown_worsened")
        if not after_cost_positive:
            reasons.append("validation_after_cost_not_positive")
        if not multiple_testing_passed:
            reasons.append("multiple_testing_penalty_not_passed")
        if sample_quality == "LOW":
            reasons.append("low_quality_evidence")

        passed = all(checks.values())
        pending = not market_usable or not benchmark_available
        validation_status = "PASSED" if passed else "PENDING" if pending else "FAILED"
        promotion_status = (
            "READY_FOR_REVIEW"
            if validation_status == "PASSED"
            else "BACKTEST_PENDING"
            if validation_status == "PENDING"
            else "RECOMMENDED_ONLY"
        )
        walk_forward_run_ids = {
            "baseline_train": baseline_train["run_id"],
            "candidate_train": candidate_train["run_id"],
            "baseline_validation": baseline_validation["run_id"],
            "candidate_validation": candidate_validation["run_id"],
        }
        benchmark_comparison = {
            "symbol": benchmark,
            "available": benchmark_available,
            "status": "AVAILABLE" if benchmark_available else "UNAVAILABLE",
            "reason": "" if benchmark_available else benchmark_unavailable_reason,
            "unavailable_reason": "" if benchmark_available else benchmark_unavailable_reason,
            "data_source": candidate_benchmark.get("dataSource") or benchmark_data_source or "",
            "benchmark_return_pct": candidate_benchmark.get("returnPct", 0.0),
            "baseline_return_pct": baseline_report.get("total_return_pct", 0.0),
            "candidate_return_pct": candidate_report.get("total_return_pct", 0.0),
            "baseline_expectancy_pct": baseline_expectancy,
            "candidate_expectancy_pct": candidate_expectancy,
            "candidate_excess_return_pct": round(
                float(candidate_report.get("total_return_pct") or 0.0)
                - float(baseline_report.get("total_return_pct") or 0.0),
                6,
            ),
        }
        walk_forward_validation = {
            "status": validation_status,
            "method": "signalops_backtest_experiment_v1",
            "train_window": train,
            "validation_window": validation,
            "train_metrics": {
                "trade_count": train_trade_count,
                "hit_rate": candidate_train_report.get("hit_rate", 0.0),
                "expectancy_pct": _experiment_expectancy_pct(candidate_train_report),
                "max_drawdown_pct": candidate_train_report.get("max_drawdown_pct", 0.0),
                "evidence_quality": sample_quality,
            },
            "validation_metrics": {
                "trade_count": validation_trade_count,
                "baseline_hit_rate": baseline_report.get("hit_rate", 0.0),
                "candidate_hit_rate": candidate_report.get("hit_rate", 0.0),
                "baseline_expectancy_pct": baseline_expectancy,
                "candidate_expectancy_pct": candidate_expectancy,
                "baseline_max_drawdown_pct": baseline_report.get("max_drawdown_pct", 0.0),
                "candidate_max_drawdown_pct": candidate_report.get("max_drawdown_pct", 0.0),
                "candidate_return_pct": candidate_report.get("total_return_pct", 0.0),
                "candidate_wilson_win_rate_lower_bound": (stability_report.get("wilson_win_rate_lower_bound") or {}).get("validation", 0.0),
                "candidate_deflated_expectancy_pct": (stability_report.get("after_cost_expectancy_pct") or {}).get("deflated_candidate_validation", 0.0),
                "candidate_avg_mae": (stability_report.get("mae_mfe") or {}).get("validation_avg_mae", 0.0),
                "candidate_avg_mfe": (stability_report.get("mae_mfe") or {}).get("validation_avg_mfe", 0.0),
                "evidence_quality": sample_quality,
            },
            "stability_validation_report": stability_report,
            "checks": checks,
            "sample_quality": sample_quality,
            "replay_sample_quality": replay_sample_quality,
            "replay_record_counts": {
                "train": len(replay_package.get("train_records", [])) if replay_package else 0,
                "validation": len(replay_package.get("validation_records", [])) if replay_package else 0,
                "dropped": len(replay_package.get("dropped_records", [])) if replay_package else 0,
            },
            "reasons": reasons,
            "simulation_only": True,
            "is_real_trade": False,
        }
        research_evidence_package = {
            "package_id": f"signalops-experiment-{_stable_payload_hash({'hash': experiment_hash, 'runs': walk_forward_run_ids}, length=16)}",
            "source": "signalops_backtest_experiment",
            "experiment_package_hash": experiment_hash,
            "computed_experiment_package_hash": computed_hash,
            "package_hash_matches_computed": computed_hash == experiment_hash,
            "walk_forward_run_ids": walk_forward_run_ids,
            "benchmark_comparison": benchmark_comparison,
            "benchmark_unavailable_reason": benchmark_unavailable_reason,
            "walk_forward_summary": {
                "status": validation_status,
                "train_window": train,
                "validation_window": validation,
                "reasons": reasons,
            },
            "stability_evidence_package": {
                "source": "signalops_strategy_stability_validation",
                "experiment_package_hash": experiment_hash,
                "stability_validation_report": stability_report,
                "triple_barrier_summary": stability_report.get("triple_barrier_summary"),
                "simulation_only": True,
                "is_real_trade": False,
            },
            "warnings": warnings,
            "reviewer": reviewer,
            "evidence_links": [
                {
                    "source_type": "BACKTEST",
                    "source_id": run_id,
                    "label": label,
                    "quality": sample_quality,
                    "created_at": _now(),
                }
                for label, run_id in walk_forward_run_ids.items()
            ],
            "simulation_only": True,
            "is_real_trade": False,
        }
        for run in (baseline_train, candidate_train, baseline_validation, candidate_validation):
            report = run.get("report") if isinstance(run.get("report"), dict) else {}
            report["walk_forward_run_ids"] = walk_forward_run_ids
            report["benchmark_comparison"] = benchmark_comparison
            report["research_evidence_package"] = research_evidence_package
            run["report"] = report
            comparison = run.get("comparison") if isinstance(run.get("comparison"), dict) else {}
            comparison["walk_forward_validation"] = walk_forward_validation
            comparison["benchmark_comparison"] = benchmark_comparison
            run["comparison"] = comparison

        run_payloads = {
            run["run_id"]: run
            for run in (baseline_train, candidate_train, baseline_validation, candidate_validation)
        }
        async with AsyncSessionLocal() as db:
            records = (
                await db.execute(select(BacktestRunDB).where(BacktestRunDB.run_id.in_(list(run_payloads.keys()))))
            ).scalars().all()
            for record in records:
                payload = run_payloads.get(record.run_id) or {}
                record.report = payload.get("report") or {}
                record.comparison = payload.get("comparison") or {}
                record.parameters = {
                    **(record.parameters or {}),
                    "walk_forward_run_ids": walk_forward_run_ids,
                    "benchmark_comparison": benchmark_comparison,
                }
                record.updated_at = _now()
            await db.commit()

        result_payload = {
            "status": "COMPLETED",
            "message": "SignalOps candidate experiment completed in simulation-only backtest mode.",
            "experiment_package_hash": experiment_hash,
            "promotion_status": promotion_status,
            "walk_forward_run_ids": walk_forward_run_ids,
            "walk_forward_validation": walk_forward_validation,
            "benchmark_comparison": benchmark_comparison,
            "benchmark_unavailable_reason": benchmark_unavailable_reason,
            "review_queue_sync_status": "NOT_SYNCED",
            "warnings": warnings,
            "research_evidence_package": research_evidence_package,
            "stability_evidence_package": research_evidence_package["stability_evidence_package"],
            "baseline_run": baseline_validation,
            "candidate_run": candidate_validation,
            "simulation_only": True,
            "is_real_trade": False,
        }
        try:
            from .auto_paper_trading import auto_paper_trading_store

            result_payload["review_queue_sync_status"] = "SYNCED"
            review_queue_state = await auto_paper_trading_store.record_backtest_experiment_result(result_payload)
            result_payload["research_evidence_package"]["review_queue_sync_status"] = "SYNCED"
            if review_queue_state:
                result_payload["research_evidence_package"]["review_queue_state"] = review_queue_state
        except Exception:
            logger.exception("failed to sync SignalOps experiment result to auto-paper review queue")
            result_payload["review_queue_sync_status"] = "FAILED"
            result_payload["warnings"] = [*result_payload["warnings"], "review_queue_sync_failed"]
            result_payload["research_evidence_package"]["review_queue_sync_status"] = "FAILED"
            try:
                from .auto_paper_trading import auto_paper_trading_store

                await auto_paper_trading_store.record_experiment_validation_state(result_payload)
            except Exception:
                logger.exception("failed to persist SignalOps experiment validation state after sync failure")
        return result_payload

    async def _select_signalops_sample_signal(
        self,
        symbol: Optional[str] = None,
        signal_id: Optional[str] = None,
        source_run_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        records = await signalops_store.list_signals(symbol=symbol, limit=100)
        requested_signal_id = str(signal_id or "").strip()
        requested_run_id = str(source_run_id or "").strip()
        eligible_statuses = set(SIGNALOPS_STRENGTH.keys()) - {"IDEA"}
        for record in records:
            status = str(record.get("status") or "").upper()
            if requested_signal_id and str(record.get("signal_id") or "") != requested_signal_id:
                continue
            if requested_run_id and not _signalops_record_matches_run(record, requested_run_id):
                continue
            if status not in eligible_statuses:
                continue
            return record
        return None

    async def create_run(
        self,
        symbol: str,
        stock_name: str = "",
        patch_id: Optional[str] = None,
        case_id: Optional[str] = None,
        start_date: str = "",
        end_date: str = "",
        initial_capital: float = 100000.0,
        scenario_label: str = "",
        parameters: Optional[Dict[str, Any]] = None,
        market_data: Optional[List[Dict[str, Any]]] = None,
        market_data_source: str = "",
        signals: Optional[List[Dict[str, Any]]] = None,
        benchmark_market_data: Optional[List[Dict[str, Any]]] = None,
        benchmark_data_source: str = "",
        benchmark_error: Optional[str] = None,
        reuse_existing: bool = True,
        force_new: bool = False,
    ) -> Dict[str, Any]:
        prepared_parameters = dict(parameters or {})
        if "reuse_existing" in prepared_parameters:
            reuse_existing = bool(prepared_parameters.pop("reuse_existing"))
        if "force_new" in prepared_parameters:
            force_new = bool(prepared_parameters.pop("force_new"))
        if str(prepared_parameters.get("signal_source") or "").strip().upper() == "SIGNALOPS":
            prepared_parameters = _apply_signalops_backtest_defaults(prepared_parameters, symbol)
        if _is_mfe_mae_research_source(prepared_parameters.get("signal_source")):
            prepared_parameters = _apply_bottom_research_backtest_defaults(prepared_parameters, symbol)
        prepared_parameters = normalize_research_contract_parameters(prepared_parameters, symbol, start_date, end_date)
        if _is_mfe_mae_research_source(prepared_parameters.get("signal_source")) and signals is None:
            if market_data is None:
                requested_source = str(prepared_parameters.get("data_source", "AUTO")).upper()
                if requested_source == "MOCK":
                    market_data = generate_mock_market_data(symbol, start_date, end_date)
                    market_data_source = "MOCK"
                else:
                    try:
                        market_data = await fetch_historical_for_backtest(symbol, start_date, end_date)
                        market_data_source = "TUSHARE"
                    except Exception:
                        logger.exception("fetch_historical_for_backtest failed for MFE/MAE Path Research %s", symbol)
                        market_data = generate_mock_market_data(symbol, start_date, end_date)
                        market_data_source = "MOCK_FALLBACK"
            signals, bottom_signal_meta = fetch_bottom_research_signals_for_backtest(symbol, market_data or [], prepared_parameters)
            prepared_parameters = {
                **prepared_parameters,
                "bottom_research_signal_hash": bottom_signal_meta.get("signal_hash", ""),
                "bottom_research_signal_count": bottom_signal_meta.get("signal_count", 0),
                "mfe_mae_research_signal_hash": bottom_signal_meta.get("signal_hash", ""),
                "mfe_mae_research_signal_count": bottom_signal_meta.get("signal_count", 0),
                "bottom_research_model_version": bottom_signal_meta.get("model_version", BOTTOM_RESEARCH_MODEL_VERSION),
                "mfe_mae_research_model_version": bottom_signal_meta.get("model_version", BOTTOM_RESEARCH_MODEL_VERSION),
                "bottom_research_data_window": {
                    "start_date": start_date,
                    "end_date": end_date,
                    "data_points": len(market_data or []),
                },
                "mfe_mae_research_data_window": {
                    "start_date": start_date,
                    "end_date": end_date,
                    "data_points": len(market_data or []),
                },
            }
        fingerprint = _backtest_fingerprint(
            symbol=symbol,
            patch_id=patch_id,
            case_id=case_id,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            scenario_label=scenario_label,
            parameters=prepared_parameters,
            market_data=market_data,
            market_data_source=market_data_source,
            signals=signals,
            benchmark_market_data=benchmark_market_data,
            benchmark_data_source=benchmark_data_source,
            benchmark_error=benchmark_error,
        )
        prepared_parameters["backtest_fingerprint"] = fingerprint

        should_reuse = bool(reuse_existing) and not bool(force_new)
        if should_reuse:
            existing = await self._find_completed_run_by_fingerprint(
                fingerprint=fingerprint,
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
            )
            if existing:
                return self._mark_dedupe_reused(existing)

            lock = await self._get_fingerprint_lock(fingerprint)
            async with lock:
                existing = await self._find_completed_run_by_fingerprint(
                    fingerprint=fingerprint,
                    symbol=symbol,
                    start_date=start_date,
                    end_date=end_date,
                )
                if existing:
                    return self._mark_dedupe_reused(existing)
                return await self._create_run_unlocked(
                    symbol=symbol,
                    stock_name=stock_name,
                    patch_id=patch_id,
                    case_id=case_id,
                    start_date=start_date,
                    end_date=end_date,
                    initial_capital=initial_capital,
                    scenario_label=scenario_label,
                    parameters=prepared_parameters,
                    market_data=market_data,
                    market_data_source=market_data_source,
                    signals=signals,
                    benchmark_market_data=benchmark_market_data,
                    benchmark_data_source=benchmark_data_source,
                    benchmark_error=benchmark_error,
                )

        return await self._create_run_unlocked(
            symbol=symbol,
            stock_name=stock_name,
            patch_id=patch_id,
            case_id=case_id,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            scenario_label=scenario_label,
            parameters=prepared_parameters,
            market_data=market_data,
            market_data_source=market_data_source,
            signals=signals,
            benchmark_market_data=benchmark_market_data,
            benchmark_data_source=benchmark_data_source,
            benchmark_error=benchmark_error,
        )

    async def _create_run_unlocked(
        self,
        symbol: str,
        stock_name: str = "",
        patch_id: Optional[str] = None,
        case_id: Optional[str] = None,
        start_date: str = "",
        end_date: str = "",
        initial_capital: float = 100000.0,
        scenario_label: str = "",
        parameters: Optional[Dict[str, Any]] = None,
        market_data: Optional[List[Dict[str, Any]]] = None,
        market_data_source: str = "",
        signals: Optional[List[Dict[str, Any]]] = None,
        benchmark_market_data: Optional[List[Dict[str, Any]]] = None,
        benchmark_data_source: str = "",
        benchmark_error: Optional[str] = None,
    ) -> Dict[str, Any]:
        parameters = dict(parameters or {})
        if str(parameters.get("signal_source") or "").strip().upper() == "SIGNALOPS":
            parameters = _apply_signalops_backtest_defaults(parameters, symbol)
        if _is_mfe_mae_research_source(parameters.get("signal_source")):
            parameters = _apply_bottom_research_backtest_defaults(parameters, symbol)
        parameters = normalize_research_contract_parameters(parameters, symbol, start_date, end_date)
        requested_source = str(parameters.get("data_source", "AUTO")).upper()
        requested_signal_source = str(parameters.get("signal_source", "MOCK")).upper()
        data_source = str(market_data_source or "CUSTOM").upper() if market_data is not None else "MOCK"
        signal_source = (
            "SIGNALOPS"
            if signals is not None and requested_signal_source == "SIGNALOPS"
            else MFE_MAE_RESEARCH_SOURCE
            if signals is not None and _is_mfe_mae_research_source(requested_signal_source)
            else "CUSTOM"
            if signals is not None
            else "MOCK"
        )
        data_error: Optional[str] = None

        if market_data is None:
            if requested_source == "MOCK":
                market_data = generate_mock_market_data(symbol, start_date, end_date)
                data_source = "MOCK"
            else:
                try:
                    market_data = await fetch_historical_for_backtest(symbol, start_date, end_date)
                    data_source = "TUSHARE"
                except Exception as exc:
                    logger.exception("fetch_historical_for_backtest failed for %s", symbol)
                    data_error = "历史数据获取失败，已使用模拟数据"
                    market_data = generate_mock_market_data(symbol, start_date, end_date)
                    data_source = "MOCK_FALLBACK"
        if signals is None:
            if requested_signal_source == "SIGNALOPS":
                signals = await fetch_signalops_signals_for_backtest(symbol, start_date, end_date, parameters)
                signal_source = "SIGNALOPS"
            elif _is_mfe_mae_research_source(requested_signal_source):
                signals, bottom_signal_meta = fetch_bottom_research_signals_for_backtest(symbol, market_data, parameters)
                parameters = {
                    **parameters,
                    "bottom_research_signal_hash": bottom_signal_meta.get("signal_hash", ""),
                    "bottom_research_signal_count": bottom_signal_meta.get("signal_count", 0),
                    "mfe_mae_research_signal_hash": bottom_signal_meta.get("signal_hash", ""),
                    "mfe_mae_research_signal_count": bottom_signal_meta.get("signal_count", 0),
                    "bottom_research_model_version": bottom_signal_meta.get("model_version", BOTTOM_RESEARCH_MODEL_VERSION),
                    "mfe_mae_research_model_version": bottom_signal_meta.get("model_version", BOTTOM_RESEARCH_MODEL_VERSION),
                    "bottom_research_data_window": {
                        "start_date": start_date,
                        "end_date": end_date,
                        "data_points": len(market_data or []),
                    },
                    "mfe_mae_research_data_window": {
                        "start_date": start_date,
                        "end_date": end_date,
                        "data_points": len(market_data or []),
                    },
                }
                signal_source = MFE_MAE_RESEARCH_SOURCE
            elif requested_signal_source == "NONE":
                signals = []
                signal_source = "NONE"
            else:
                signals = generate_mock_signals(symbol, start_date, end_date)
                signal_source = "MOCK"

        report: BacktestReport = run_backtest(
            symbol=symbol,
            stock_name=stock_name,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            market_data=market_data,
            signals=signals,
            patch_params=parameters,
            data_source=data_source,
            data_error=data_error,
            signal_source=signal_source,
            benchmark_market_data=benchmark_market_data,
            benchmark_data_source=benchmark_data_source,
            benchmark_error=benchmark_error,
        )

        run_id = _generate_id("BT")
        comparison = None

        if patch_id:
            prev_run = await self._get_latest_run_for_patch(patch_id)
            if prev_run and prev_run.get("report"):
                before_report = BacktestReport(**prev_run["report"])
                comparison = run_comparison(before_report, report)

        comparison_payload = comparison.model_dump(mode="json") if comparison else {}
        if report.researchContract:
            comparison_payload.setdefault("researchContract", report.researchContract)

        async with AsyncSessionLocal() as db:
            run = BacktestRunDB(
                run_id=run_id,
                patch_id=patch_id,
                case_id=case_id,
                symbol=symbol,
                stock_name=stock_name,
                scenario_label=scenario_label,
                status="COMPLETED",
                start_date=start_date,
                end_date=end_date,
                initial_capital=initial_capital,
                parameters=parameters,
                report=report.model_dump(mode="json"),
                comparison=comparison_payload,
                elapsed_ms=0,
                created_at=_now(),
                updated_at=_now(),
            )
            db.add(run)

            for trade in report.trade_log:
                db.add(BacktestTradeDB(
                    trade_id=trade.trade_id,
                    run_id=run_id,
                    direction=trade.direction,
                    price=trade.price,
                    quantity=trade.quantity,
                    amount=trade.amount,
                    slippage=trade.slippage,
                    timestamp=trade.timestamp,
                    reason=trade.reason,
                    realized_pnl=trade.realized_pnl,
                ))

            for sig in report.signal_log:
                db.add(BacktestSignalDB(
                    signal_id=sig.signal_id,
                    run_id=run_id,
                    signal_type=sig.signal_type,
                    direction=sig.direction,
                    strength=sig.strength,
                    price=sig.price,
                    timestamp=sig.timestamp,
                    source_node=sig.source_node,
                    metadata_json=sig.metadata_json,
                ))

            await db.commit()

        result = {
            "run_id": run_id,
            "patch_id": patch_id,
            "case_id": case_id,
            "symbol": symbol,
            "stock_name": stock_name,
            "scenario_label": scenario_label,
            "status": "COMPLETED",
            "start_date": start_date,
            "end_date": end_date,
            "initial_capital": initial_capital,
            "parameters": parameters,
            "report": report.model_dump(mode="json"),
            "comparison": comparison_payload,
            "error": None,
            "elapsed_ms": 0,
            "created_at": _now(),
            "updated_at": _now(),
        }

        if patch_id:
            await self._update_patch_backtest(patch_id, report)

        return result

    async def create_parameter_scan(
        self,
        *,
        symbol: str,
        stock_name: str = "",
        patch_id: Optional[str] = None,
        case_id: Optional[str] = None,
        start_date: str = "",
        end_date: str = "",
        initial_capital: float = 100000.0,
        scenario_label: str = "",
        base_parameters: Optional[Dict[str, Any]] = None,
        parameter_grid: Optional[Dict[str, List[Any]]] = None,
        max_combinations: int = 8,
        ranking_metric: str = "research_grade_score",
        market_data: Optional[List[Dict[str, Any]]] = None,
        market_data_source: str = "",
        signals: Optional[List[Dict[str, Any]]] = None,
        benchmark_market_data: Optional[List[Dict[str, Any]]] = None,
        benchmark_data_source: str = "",
        benchmark_error: Optional[str] = None,
        windows: Optional[List[Dict[str, Any]]] = None,
        reuse_existing: bool = True,
        force_new: bool = False,
    ) -> Dict[str, Any]:
        base = dict(base_parameters or {})
        grid = dict(parameter_grid or {})
        combinations = _parameter_scan_combinations(grid, max_combinations)
        scan_windows = _parameter_scan_windows(start_date, end_date, windows)
        scan_window = {
            "start": _iso_date(start_date) or scan_windows[0]["start"],
            "end": _iso_date(end_date) or scan_windows[-1]["end"],
        }
        trial_count = len(combinations) * len(scan_windows)
        capped_max_combinations = min(max(int(max_combinations or 1), 1), BACKTEST_PARAMETER_SCAN_MAX_COMBINATIONS)
        scan_id = f"BTS_{_stable_payload_hash({'symbol': symbol, 'scan_window': scan_window, 'windows': scan_windows, 'base': base, 'grid': grid}, length=12)}"
        run_payloads: List[Dict[str, Any]] = []
        score_rows: List[Dict[str, Any]] = []

        for index, combination in enumerate(combinations, start=1):
            for window_index, window in enumerate(scan_windows, start=1):
                parameters = {**base, **combination}
                parameters["simulation_only"] = True
                parameters["is_real_trade"] = False
                parameters["parameter_scan"] = {
                    "enabled": True,
                    "scanId": scan_id,
                    "grid": grid,
                    "combination": combination,
                    "combinationIndex": index,
                    "combinationCount": len(combinations),
                    "trialCount": trial_count,
                    "maxCombinations": capped_max_combinations,
                    "rankingMetric": ranking_metric,
                    "window": window,
                    "windowIndex": window_index,
                    "windowCount": len(scan_windows),
                    "windows": scan_windows,
                    "scanWindow": scan_window,
                }
                label_prefix = scenario_label or "Parameter scan"
                label_suffix = f"#{index}"
                if len(scan_windows) > 1:
                    label_suffix = f"{label_suffix} W{window_index}"
                run = await self.create_run(
                    symbol=symbol,
                    stock_name=stock_name,
                    patch_id=patch_id,
                    case_id=case_id,
                    start_date=window["start"],
                    end_date=window["end"],
                    initial_capital=initial_capital,
                    scenario_label=f"{label_prefix} {label_suffix}",
                    parameters=parameters,
                    market_data=market_data,
                    market_data_source=market_data_source,
                    signals=signals,
                    benchmark_market_data=benchmark_market_data,
                    benchmark_data_source=benchmark_data_source,
                    benchmark_error=benchmark_error,
                    reuse_existing=reuse_existing,
                    force_new=force_new,
                )
                score = _backtest_ranking_score(run, ranking_metric)
                report = run.get("report") if isinstance(run.get("report"), dict) else {}
                evidence = _parameter_scan_review_gate_evidence(report)
                score_rows.append({
                    "run_id": run.get("run_id"),
                    "score": score,
                    "combination": combination,
                    "combinationIndex": index,
                    "window": window,
                    "windowIndex": window_index,
                    "researchUsage": evidence.get("researchUsage") or "supporting_only",
                    "canSupportResearchVerdict": bool(evidence.get("canSupportResearchVerdict")),
                })
                run_payloads.append(run)

        best_row = max(score_rows, key=lambda item: float(item.get("score") or 0.0)) if score_rows else {}
        best_run_id = str(best_row.get("run_id") or "") or None
        best_run = next((run for run in run_payloads if run.get("run_id") == best_run_id), None)
        average_score = (
            sum(float(item.get("score") or 0.0) for item in score_rows) / len(score_rows)
            if score_rows
            else 0.0
        )
        summary = {
            "scanId": scan_id,
            "totalCombinations": len(combinations),
            "totalTrials": trial_count,
            "windowCount": len(scan_windows),
            "windows": scan_windows,
            "rankingMetric": ranking_metric,
            "bestRunId": best_run_id,
            "bestScore": round(float(best_row.get("score") or 0.0), 4) if best_row else 0.0,
            "averageScore": round(average_score, 4),
            "supportingOnlyCount": sum(1 for item in score_rows if item.get("researchUsage") == "supporting_only"),
            "researchVerdictReadyCount": sum(1 for item in score_rows if item.get("canSupportResearchVerdict")),
            "scores": score_rows,
            "simulationOnly": True,
            "isRealTrade": False,
        }
        if best_run:
            best_report = best_run.get("report") if isinstance(best_run.get("report"), dict) else {}
            summary["bestResearchGradeScore"] = best_report.get("researchGradeScore") or {}
            summary["bestValidationProtocol"] = best_report.get("validationProtocol") or {}

        return {
            "scan_id": scan_id,
            "status": "COMPLETED",
            "symbol": symbol,
            "start_date": start_date,
            "end_date": end_date,
            "ranking_metric": ranking_metric,
            "parameter_grid": grid,
            "combinations": combinations,
            "windows": scan_windows,
            "window_count": len(scan_windows),
            "run_ids": [str(run.get("run_id")) for run in run_payloads if run.get("run_id")],
            "best_run_id": best_run_id,
            "best_score": round(float(best_row.get("score") or 0.0), 4) if best_row else 0.0,
            "summary": summary,
            "runs": run_payloads,
            "trial_count": trial_count,
            "simulation_only": True,
            "is_real_trade": False,
        }

    async def list_parameter_scans(
        self,
        *,
        symbol: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        requested_limit = min(max(int(limit or 20), 1), 100)
        run_limit = min(max(requested_limit * 20, 100), 500)
        async with AsyncSessionLocal() as db:
            query = select(BacktestRunDB)
            if symbol:
                query = query.where(BacktestRunDB.symbol == symbol)
            query = query.order_by(desc(BacktestRunDB.created_at)).limit(run_limit)
            result = await db.execute(query)
            records = result.scalars().all()

        grouped: Dict[str, Dict[str, Any]] = {}
        for record in records:
            run = self._run_to_dict(record)
            parameters = run.get("parameters") if isinstance(run.get("parameters"), dict) else {}
            scan_meta = parameters.get("parameter_scan") if isinstance(parameters.get("parameter_scan"), dict) else {}
            scan_id = str(scan_meta.get("scanId") or scan_meta.get("scan_id") or "").strip()
            if scan_meta.get("enabled") is not True or not scan_id:
                continue
            ranking_metric = str(scan_meta.get("rankingMetric") or "research_grade_score")
            score = _backtest_ranking_score(run, ranking_metric)
            report = run.get("report") if isinstance(run.get("report"), dict) else {}
            evidence = _parameter_scan_review_gate_evidence(report)
            validation = report.get("validationProtocol") if isinstance(report.get("validationProtocol"), dict) else {}
            scan_window = scan_meta.get("scanWindow") if isinstance(scan_meta.get("scanWindow"), dict) else {}
            scan_windows = scan_meta.get("windows") if isinstance(scan_meta.get("windows"), list) else []
            current_window = scan_meta.get("window") if isinstance(scan_meta.get("window"), dict) else {
                "start": run.get("start_date") or "",
                "end": run.get("end_date") or "",
                "label": "primary",
            }
            try:
                configured_window_count = int(scan_meta.get("windowCount") or len(scan_windows) or 1)
            except (TypeError, ValueError):
                configured_window_count = len(scan_windows) or 1
            row = grouped.setdefault(scan_id, {
                "scan_id": scan_id,
                "status": "COMPLETED",
                "symbol": run.get("symbol") or "",
                "stock_name": run.get("stock_name") or "",
                "start_date": scan_window.get("start") or run.get("start_date") or "",
                "end_date": scan_window.get("end") or run.get("end_date") or "",
                "ranking_metric": ranking_metric,
                "parameter_grid": scan_meta.get("grid") if isinstance(scan_meta.get("grid"), dict) else {},
                "combinations": [],
                "windows": scan_windows if scan_windows else [],
                "window_count": configured_window_count,
                "run_ids": [],
                "best_run_id": None,
                "best_score": 0.0,
                "summary": {
                    "scanId": scan_id,
                    "totalCombinations": int(scan_meta.get("combinationCount") or 0),
                    "totalTrials": int(scan_meta.get("trialCount") or 0),
                    "windowCount": configured_window_count,
                    "windows": scan_windows if scan_windows else [],
                    "rankingMetric": ranking_metric,
                    "supportingOnlyCount": 0,
                    "researchVerdictReadyCount": 0,
                    "scores": [],
                    "simulationOnly": True,
                    "isRealTrade": False,
                },
                "trial_count": 0,
                "created_at": run.get("created_at") or "",
                "updated_at": run.get("updated_at") or "",
                "simulation_only": True,
                "is_real_trade": False,
                "_best_combination_index": None,
                "_best_window_index": None,
                "_combination_keys": set(),
                "_window_keys": {
                    _stable_payload_hash(item, length=16)
                    for item in scan_windows
                    if isinstance(item, dict)
                },
            })
            try:
                combination_index = int(scan_meta.get("combinationIndex") or 0)
            except (TypeError, ValueError):
                combination_index = 0
            try:
                window_index = int(scan_meta.get("windowIndex") or 0)
            except (TypeError, ValueError):
                window_index = 0
            row["run_ids"].append(str(run.get("run_id") or ""))
            combination = scan_meta.get("combination") if isinstance(scan_meta.get("combination"), dict) else {}
            combination_key = _stable_payload_hash(combination, length=16)
            if combination_key not in row["_combination_keys"]:
                row["combinations"].append(combination)
                row["_combination_keys"].add(combination_key)
            window_key = _stable_payload_hash(current_window, length=16)
            if window_key not in row["_window_keys"]:
                row["windows"].append(current_window)
                row["_window_keys"].add(window_key)
            row["window_count"] = max(int(row.get("window_count") or 0), configured_window_count, len(row["windows"]))
            row["summary"]["windowCount"] = row["window_count"]
            row["summary"]["windows"] = row["windows"]
            row["trial_count"] = len(row["run_ids"])
            row["status"] = "FAILED" if run.get("status") == "FAILED" else row["status"]
            if str(run.get("created_at") or "") < str(row.get("created_at") or run.get("created_at") or ""):
                row["created_at"] = run.get("created_at") or ""
            if str(run.get("updated_at") or "") > str(row.get("updated_at") or ""):
                row["updated_at"] = run.get("updated_at") or ""
            simulation_only = bool(parameters.get("simulation_only", True))
            is_real_trade = bool(parameters.get("is_real_trade", False))
            row["simulation_only"] = bool(row["simulation_only"] and simulation_only)
            row["is_real_trade"] = bool(row["is_real_trade"] or is_real_trade)
            row["summary"]["simulationOnly"] = row["simulation_only"]
            row["summary"]["isRealTrade"] = row["is_real_trade"]
            if evidence.get("researchUsage") == "supporting_only":
                row["summary"]["supportingOnlyCount"] += 1
            if evidence.get("canSupportResearchVerdict"):
                row["summary"]["researchVerdictReadyCount"] += 1
            score_row = {
                "run_id": run.get("run_id"),
                "score": score,
                "combination": combination,
                "combinationIndex": combination_index,
                "window": current_window,
                "windowIndex": window_index,
                "researchUsage": evidence.get("researchUsage") or "supporting_only",
                "canSupportResearchVerdict": bool(evidence.get("canSupportResearchVerdict")),
            }
            row["summary"]["scores"].append(score_row)
            current_best_index = row.get("_best_combination_index")
            current_best_window_index = row.get("_best_window_index")
            if (
                row["best_run_id"] is None
                or score > float(row.get("best_score") or 0.0)
                or (
                    score == float(row.get("best_score") or 0.0)
                    and combination_index > 0
                    and (
                        current_best_index is None
                        or combination_index < int(current_best_index or 0)
                        or (
                            combination_index == int(current_best_index or 0)
                            and window_index > 0
                            and (
                                current_best_window_index is None
                                or window_index < int(current_best_window_index or 0)
                            )
                        )
                    )
                )
            ):
                row["best_run_id"] = str(run.get("run_id") or "") or None
                row["best_score"] = round(float(score), 4)
                row["_best_combination_index"] = combination_index
                row["_best_window_index"] = window_index
                row["summary"]["bestRunId"] = row["best_run_id"]
                row["summary"]["bestScore"] = row["best_score"]
                row["summary"]["bestResearchGradeScore"] = report.get("researchGradeScore") or {}
                row["summary"]["bestValidationProtocol"] = validation

        scans = sorted(
            grouped.values(),
            key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
            reverse=True,
        )
        for scan in scans:
            scores = scan["summary"].get("scores") if isinstance(scan.get("summary"), dict) else []
            scan["summary"]["totalCombinations"] = len(scan.get("combinations") or [])
            scan["summary"]["totalTrials"] = int(scan.get("trial_count") or len(scan.get("run_ids") or []))
            scan["summary"]["averageScore"] = round(
                sum(float(item.get("score") or 0.0) for item in scores) / len(scores),
                4,
            ) if scores else 0.0
            scan.pop("_best_combination_index", None)
            scan.pop("_best_window_index", None)
            scan.pop("_combination_keys", None)
            scan.pop("_window_keys", None)
        return scans[:requested_limit]

    async def _get_fingerprint_lock(self, fingerprint: str) -> asyncio.Lock:
        async with self._fingerprint_locks_guard:
            lock = self._fingerprint_locks.get(fingerprint)
            if lock is None:
                lock = asyncio.Lock()
                self._fingerprint_locks[fingerprint] = lock
            return lock

    def _mark_dedupe_reused(self, run: Dict[str, Any]) -> Dict[str, Any]:
        payload = dict(run)
        payload["parameters"] = {**(payload.get("parameters") or {}), "dedupe_reused": True}
        return payload

    def _fingerprint_from_record(self, record: BacktestRunDB) -> str:
        parameters = record.parameters or {}
        stored = str(parameters.get("backtest_fingerprint") or "").strip()
        if stored:
            return stored
        return _backtest_fingerprint(
            symbol=record.symbol,
            patch_id=record.patch_id,
            case_id=record.case_id,
            start_date=record.start_date,
            end_date=record.end_date,
            initial_capital=record.initial_capital,
            scenario_label=record.scenario_label,
            parameters=parameters,
        )

    async def _find_completed_run_by_fingerprint(
        self,
        *,
        fingerprint: str,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> Optional[Dict[str, Any]]:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(BacktestRunDB)
                .where(
                    BacktestRunDB.status == "COMPLETED",
                    BacktestRunDB.symbol == symbol,
                    BacktestRunDB.start_date == start_date,
                    BacktestRunDB.end_date == end_date,
                )
                .order_by(desc(BacktestRunDB.created_at))
            )
            for record in result.scalars().all():
                if self._fingerprint_from_record(record) == fingerprint:
                    return self._run_to_dict(record)
        return None

    async def _get_latest_run_for_patch(self, patch_id: str) -> Optional[Dict[str, Any]]:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(BacktestRunDB)
                .where(BacktestRunDB.patch_id == patch_id)
                .order_by(desc(BacktestRunDB.created_at))
                .limit(1)
            )
            record = result.scalar_one_or_none()
            return self._run_to_dict(record) if record else None

    async def _update_patch_backtest(self, patch_id: str, report: BacktestReport) -> None:
        from ..core.case_library_store import knowledge_patch_store

        summary = {
            "hit_rate": report.hit_rate,
            "false_positive_rate": report.false_positive_rate,
            "max_drawdown_pct": report.max_drawdown_pct,
            "total_pnl": report.total_pnl,
            "total_return_pct": report.total_return_pct,
            "total_trades": report.total_trades,
            "winning_trades": report.winning_trades,
            "losing_trades": report.losing_trades,
            "sharpe_ratio": report.sharpe_ratio,
            "manual_review_pass_rate": report.manual_review_pass_rate,
            "t_plus_one_blocked": report.t_plus_one_blocked,
            "price_limit_blocked": report.price_limit_blocked,
            "slippage_total": report.slippage_total,
            "data_source": report.data_source,
            "data_points": report.data_points,
            "data_error": report.data_error,
            "signal_source": report.signal_source,
            "signal_source_count": report.signal_source_count,
            "benchmark": report.benchmark,
            "sampleWindow": report.sampleWindow,
            "tradingCost": report.tradingCost,
            "slippage": report.slippage,
            "executionConstraints": report.executionConstraints,
            "outOfSampleWindow": report.outOfSampleWindow,
            "statisticalConfidence": report.statisticalConfidence,
            "evidenceStrength": report.evidenceStrength,
            "researchGradeScore": report.researchGradeScore,
            "limitations": report.limitations,
            "provenance": report.provenance,
            "validationProtocol": report.validationProtocol,
        }
        full_result = report.model_dump(mode="json")

        await knowledge_patch_store.update_backtest_result(patch_id, {
            "summary": summary,
            "full_report": full_result,
            "updated_at": _now(),
        })

    async def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(BacktestRunDB).where(BacktestRunDB.run_id == run_id)
            )
            record = result.scalar_one_or_none()
            return self._run_to_dict(record) if record else None

    async def list_runs(
        self,
        patch_id: Optional[str] = None,
        case_id: Optional[str] = None,
        symbol: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        async with AsyncSessionLocal() as db:
            query = select(BacktestRunDB)
            if patch_id:
                query = query.where(BacktestRunDB.patch_id == patch_id)
            if case_id:
                query = query.where(BacktestRunDB.case_id == case_id)
            if symbol:
                query = query.where(BacktestRunDB.symbol == symbol)
            if status:
                query = query.where(BacktestRunDB.status == status)
            query = query.order_by(desc(BacktestRunDB.created_at)).limit(limit)
            result = await db.execute(query)
            records = result.scalars().all()
            return [self._run_to_dict(r) for r in records]

    async def get_trades(self, run_id: str) -> List[Dict[str, Any]]:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(BacktestTradeDB)
                .where(BacktestTradeDB.run_id == run_id)
                .order_by(BacktestTradeDB.timestamp)
            )
            records = result.scalars().all()
            return [self._trade_to_dict(r) for r in records]

    async def get_signals(self, run_id: str) -> List[Dict[str, Any]]:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(BacktestSignalDB)
                .where(BacktestSignalDB.run_id == run_id)
                .order_by(BacktestSignalDB.timestamp)
            )
            records = result.scalars().all()
            return [self._signal_to_dict(r) for r in records]

    async def get_experiment_package(self, run_id: str) -> Optional[Dict[str, Any]]:
        run = await self.get_run(run_id)
        if not run:
            return None
        trades = await self.get_trades(run_id)
        signals = await self.get_signals(run_id)
        report = run.get("report") if isinstance(run.get("report"), dict) else {}
        package_report = _review_gate_backtest_report(report)
        parameters = run.get("parameters") if isinstance(run.get("parameters"), dict) else {}
        provenance = report.get("provenance") if isinstance(report.get("provenance"), dict) else {}
        validation = report.get("validationProtocol") if isinstance(report.get("validationProtocol"), dict) else {}
        package_hashes = validation.get("packageHashes") if isinstance(validation.get("packageHashes"), dict) else {}

        hashes = {
            "parameterHash": provenance.get("parameterHash") or package_hashes.get("parameterHash") or "",
            "marketDataHash": provenance.get("marketDataHash") or package_hashes.get("marketDataHash") or "",
            "signalPackageHash": provenance.get("signalPackageHash") or package_hashes.get("signalPackageHash") or "",
            "benchmarkDataHash": provenance.get("benchmarkDataHash") or package_hashes.get("benchmarkDataHash") or "",
            "dataPackageHash": provenance.get("dataPackageHash") or package_hashes.get("dataPackageHash") or "",
        }
        generated_at = _now()
        research_grade = package_report.get("researchGradeScore") if isinstance(package_report.get("researchGradeScore"), dict) else {}
        simulation_only = bool(parameters.get("simulation_only", provenance.get("simulationOnly", True)))
        is_real_trade = bool(parameters.get("is_real_trade", provenance.get("isRealTrade", False)))
        package_run = dict(run)
        package_run["report"] = package_report
        manifest = {
            "schemaVersion": "backtest_experiment_package_v1",
            "runId": run_id,
            "symbol": run.get("symbol") or "",
            "window": {
                "start": run.get("start_date") or "",
                "end": run.get("end_date") or "",
            },
            "generatedAt": generated_at,
            "counts": {
                "trades": len(trades),
                "signals": len(signals),
                "equityCurve": len(report.get("equity_curve") if isinstance(report.get("equity_curve"), list) else []),
            },
            "hashes": hashes,
            "validationProtocol": validation,
            "researchUsage": "supporting_only",
            "researchGradeScore": research_grade,
            "limitations": report.get("limitations") if isinstance(report.get("limitations"), list) else [],
            "simulationOnly": simulation_only,
            "isRealTrade": is_real_trade,
        }
        package_id = f"BTEP_{_stable_payload_hash({'run_id': run_id, 'updated_at': run.get('updated_at'), 'hashes': hashes}, length=16)}"
        return {
            "package_id": package_id,
            "run_id": run_id,
            "generated_at": generated_at,
            "manifest": manifest,
            "hashes": hashes,
            "reproducibility": {
                "dataPackageHash": hashes.get("dataPackageHash") or "",
                "validationProtocol": validation,
                "parameters": parameters,
                "provenance": provenance,
            },
            "run": package_run,
            "trades": trades,
            "signals": signals,
            "simulation_only": simulation_only,
            "is_real_trade": is_real_trade,
        }

    async def research_references_for_run(self, run_id: str) -> List[str]:
        references: List[str] = []
        async with AsyncSessionLocal() as db:
            evidence_result = await db.execute(
                select(ResearchEvidenceLinkDB).where(
                    ResearchEvidenceLinkDB.source_type == "BACKTEST",
                    ResearchEvidenceLinkDB.source_id == run_id,
                )
            )
            for link in evidence_result.scalars().all():
                references.append(f"evidence_link:{link.link_id}")

            iteration_result = await db.execute(select(ResearchIterationDB))
            for iteration in iteration_result.scalars().all():
                if iteration.linked_backtest_id == run_id:
                    references.append(f"iteration:{iteration.iteration_id}:linked_backtest_id")
                if _json_contains_value(iteration.metrics or {}, run_id):
                    references.append(f"iteration:{iteration.iteration_id}:metrics")
                evidence_links = iteration.evidence_links if isinstance(iteration.evidence_links, list) else []
                for item in evidence_links:
                    if not isinstance(item, dict):
                        continue
                    if str(item.get("source_type") or "").upper() == "BACKTEST" and str(item.get("source_id") or "") == run_id:
                        references.append(f"iteration:{iteration.iteration_id}:evidence_links")
                        break
        return sorted(set(references))

    async def delete_run(self, run_id: str, protect_research_references: bool = False) -> bool:
        if protect_research_references:
            references = await self.research_references_for_run(run_id)
            if references:
                raise BacktestRunReferencedError(run_id, references)
        async with AsyncSessionLocal() as db:
            await db.execute(sa_delete(BacktestTradeDB).where(BacktestTradeDB.run_id == run_id))
            await db.execute(sa_delete(BacktestSignalDB).where(BacktestSignalDB.run_id == run_id))
            result = await db.execute(sa_delete(BacktestRunDB).where(BacktestRunDB.run_id == run_id))
            await db.commit()
            return result.rowcount > 0

    async def get_summary(self) -> Dict[str, Any]:
        async with AsyncSessionLocal() as db:
            total = await db.execute(select(func.count()).select_from(BacktestRunDB))
            total_count = total.scalar() or 0

            completed = await db.execute(
                select(func.count()).select_from(BacktestRunDB).where(BacktestRunDB.status == "COMPLETED")
            )
            completed_count = completed.scalar() or 0

            return {
                "total_runs": total_count,
                "completed_runs": completed_count,
                "pending_runs": total_count - completed_count,
            }

    def _run_to_dict(self, record: BacktestRunDB) -> Dict[str, Any]:
        if not record:
            return {}
        return {
            "run_id": record.run_id,
            "patch_id": record.patch_id,
            "case_id": record.case_id,
            "symbol": record.symbol,
            "stock_name": record.stock_name,
            "scenario_label": record.scenario_label,
            "status": record.status,
            "start_date": record.start_date,
            "end_date": record.end_date,
            "initial_capital": record.initial_capital,
            "parameters": record.parameters or {},
            "report": _review_gate_backtest_report(record.report or {}),
            "comparison": record.comparison or {},
            "error": record.error,
            "elapsed_ms": record.elapsed_ms,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }

    def _trade_to_dict(self, record: BacktestTradeDB) -> Dict[str, Any]:
        return {
            "trade_id": record.trade_id,
            "run_id": record.run_id,
            "direction": record.direction,
            "price": record.price,
            "quantity": record.quantity,
            "amount": record.amount,
            "slippage": record.slippage,
            "timestamp": record.timestamp,
            "reason": record.reason,
            "realized_pnl": record.realized_pnl,
        }

    def _signal_to_dict(self, record: BacktestSignalDB) -> Dict[str, Any]:
        return {
            "signal_id": record.signal_id,
            "run_id": record.run_id,
            "signal_type": record.signal_type,
            "direction": record.direction,
            "strength": record.strength,
            "price": record.price,
            "timestamp": record.timestamp,
            "source_node": record.source_node,
            "metadata_json": record.metadata_json or {},
        }


backtest_store = BacktestStore()
