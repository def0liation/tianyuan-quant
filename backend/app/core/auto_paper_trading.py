from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import json
import os
import re
import tempfile
import time as time_module
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from ..models.auto_paper_trading import AutoPaperTradingConfig
from ..models.portfolio import HoldingPosition
from .agent_runtime_store import get_default_market_data_profile
from .kline_service import get_kline_payload
from .kline_signal_quality import evaluate_kline_signal_quality
from .llm_runner import run_agent_llm
from .market_data_runner import fetch_market_data
from .pet_alerts import pet_alert_center
from .portfolio_store import build_snapshot, save_snapshot
from .signalops_store import signalops_store
from .signalops_decision_tree import (
    normalize_decision_tree_state,
    update_decision_tree_after_tick,
)
from .strategy_stability_quality import evaluate_strategy_stability_quality
from .technical_kline_agent import build_technical_kline_analysis
from .bottom_research import build_bottom_research_analysis
from ..modules.anti_conclusion import AntiConclusionAgent
from ..modules.atrade import ATradeAgent
from ..modules.calculation_authority import CalculationAuthorityAgent
from ..modules.dvg_evidence_gate import DvgEvidenceGateAgent
from ..modules.execution import ExecutionAgent
from ..modules.factor_engine import FactorEngineAgent
from ..modules.factor_slicing import FactorSlicingAgent
from ..modules.market_regime import MarketRegimeAgent
from ..modules.qiam import QiamAgent
from ..modules.quant_core import QuantCoreAgent, build_quant_core_interpretation
from ..modules.risk_firewall import RiskFirewallAgent


STORAGE_FILE = Path(__file__).resolve().parents[1] / "storage" / "auto_paper_trading.json"
SIM_ACTIONS = {
    "SIM_BUY",
    "SIM_SELL",
    "SIM_HOLD",
    "SIM_REBALANCE",
    "SIM_CLOSE",
    "SIM_T_BUY",
    "SIM_T_SELL",
    "SIM_SHORT",
    "SIM_COVER",
}
AUTO_PAPER_COMMANDS = {"FORCE_OPEN_BUY", "FORCE_CLOSE", "REMOVE_SYMBOL", "FORCE_CLOSE_AND_REMOVE"}
LIFECYCLE_FLOW = ["IDEA", "WATCH", "PAPER_TEST", "QUALIFIED", "TRADE_PLAN", "MANUAL_CONFIRMED", "EXECUTION_REVIEW", "CLOSED"]
BOARD_LOT_SIZE = 100
DEFAULT_COMMISSION_RATE = 0.0001
DEFAULT_COMMISSION_MIN_FEE = 5.0
DEFAULT_COMMISSION_MIN_TRADE_VALUE = 50000.0
DEFAULT_STAMP_DUTY_RATE = 0.0005
CHINA_TZ = ZoneInfo("Asia/Shanghai")
MORNING_SESSION_START = time(9, 30)
MORNING_SESSION_END = time(11, 30)
AFTERNOON_SESSION_START = time(13, 0)
AFTERNOON_SESSION_END = time(15, 0)
PRICE_LIMIT_TOLERANCE_PCT = 0.02
PERFORMANCE_STATS_VERSION = 1
PERFORMANCE_PRIOR_DECAY = 0.94
TUNING_MIN_TRADE_COUNT = 5
TUNING_MIN_EVIDENCE_WEIGHT = 6.0
TUNING_MIN_CONFIDENCE = 0.45
CLEANED_RECORD_HISTORY_LIMIT = 120
REVIEW_DECISION_HISTORY_LIMIT = 100
REVIEW_QUEUE_ITEM_LIMIT = 50
REVIEW_PARAMETER_DIFF_ROW_LIMIT = 8
REVIEW_DECISION_EVENT_EXPORT_LIMIT = 500
DEFAULT_EXPERIMENT_BENCHMARK_SYMBOL = "000300.SH"
EVIDENCE_QUALITY_VALUES = {"STRONG", "MEDIUM", "LOW", "SUPPORTING_ONLY"}
PROMOTION_STATUSES = {
    "BACKTEST_PENDING",
    "RECOMMENDED_ONLY",
    "READY_FOR_REVIEW",
    "APPLIED_TO_SIMULATION",
    "REJECTED",
    "SUPERSEDED",
    "EXPIRED",
    "NO_CHANGE",
}
REVIEW_DECISION_ACTIONS = {
    "APPROVE_SIMULATION_CANDIDATE",
    "REJECT_CANDIDATE",
    "CONTINUE_OBSERVING",
    "REQUEST_PATCH",
}
AUTOMATION_MODE_SIMULATION = "SIMULATION"
AUTOMATION_MODE_LIVE = "LIVE_DISABLED"
logger = logging.getLogger(__name__)


def _review_decision_event_file() -> Path:
    configured = os.getenv("AUTO_PAPER_REVIEW_DECISION_EVENT_FILE", "").strip()
    return Path(configured).expanduser() if configured else STORAGE_FILE.with_name("auto_paper_review_decision_events.jsonl")


def _review_decision_export_signing_key() -> str:
    return os.getenv("AUTO_PAPER_REVIEW_DECISION_EXPORT_SIGNING_KEY", "").strip()


def _review_decision_export_signing_key_ref() -> str:
    configured = os.getenv("AUTO_PAPER_REVIEW_DECISION_EXPORT_SIGNING_KEY_REF", "").strip()
    return configured or "env:AUTO_PAPER_REVIEW_DECISION_EXPORT_SIGNING_KEY"


def _review_decision_export_handoff_dir() -> Optional[Path]:
    configured = os.getenv("AUTO_PAPER_REVIEW_DECISION_EXPORT_HANDOFF_DIR", "").strip()
    return Path(configured).expanduser() if configured else None


REVIEW_DECISION_EXPORT_HANDOFF_SHIPPER_STATUS_SCHEMA = "signalops_review_decision_event_export_shipper_status_v1"
REVIEW_DECISION_EXPORT_HANDOFF_SHIPPER_STATUS_FILE = "shipper_status.json"
REVIEW_DECISION_EXPORT_HANDOFF_ALLOWED_SHIPPER_STATUSES = {"DELIVERED", "PENDING", "FAILED", "UNKNOWN"}
REVIEW_DECISION_EXPORT_HANDOFF_SECRET_PATTERN = re.compile(
    r"(api[_-]?key|token|secret|authorization)=([^,\s]+)",
    re.IGNORECASE,
)


def _safe_review_handoff_text(value: Any, limit: int = 240) -> str:
    text = "" if value is None else str(value).strip()
    text = REVIEW_DECISION_EXPORT_HANDOFF_SECRET_PATTERN.sub(r"\1=[REDACTED]", text)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _parse_time(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _elapsed_seconds(value: str) -> float:
    parsed = _parse_time(value)
    if not parsed:
        return 10**9
    return (_now() - parsed).total_seconds()


def _clamp_float(value: Any, default: float, low: float, high: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(low, min(parsed, high))


def _clamp_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(low, min(parsed, high))


def _board_lot_quantity(value: Any) -> int:
    try:
        quantity = float(value)
    except (TypeError, ValueError):
        return 0
    if quantity < BOARD_LOT_SIZE:
        return 0
    return int(quantity // BOARD_LOT_SIZE) * BOARD_LOT_SIZE


def _parse_symbols(value: str) -> list[str]:
    normalized = str(value or "").replace("，", ",").replace("；", ",").replace(";", ",").replace("\n", ",")
    symbols: list[str] = []
    for item in normalized.split(","):
        symbol = item.strip()
        if symbol and symbol not in symbols:
            symbols.append(symbol)
    return symbols


def _split_stock_names(value: Any) -> list[str]:
    return [
        item.strip()
        for item in str(value or "")
        .replace("\uff0c", ",")
        .replace("\uff1b", ",")
        .replace(";", ",")
        .replace("\n", ",")
        .split(",")
    ]


def _symbol_token(value: Any) -> str:
    normalized = str(value or "").strip().upper()
    normalized = re.sub(r"\.(SH|SZ|BJ)$", "", normalized)
    return re.sub(r"[^A-Z0-9]", "", normalized)


def _is_symbol_placeholder(symbol: str, stock_name: Any) -> bool:
    name = str(stock_name or "").strip()
    if not name:
        return True
    symbol_token = _symbol_token(symbol)
    name_token = re.sub(r"[^A-Z0-9]", "", name.upper())
    if not symbol_token or not name_token:
        return False
    return name_token in {
        symbol_token,
        f"{symbol_token}SH",
        f"{symbol_token}SZ",
        f"{symbol_token}BJ",
    }


def _stock_name_for_symbol(config: AutoPaperTradingConfig, symbol: str, index: int) -> str:
    names = _split_stock_names(config.stock_name)
    if len(names) > index and names[index]:
        return names[index]
    if len(names) == 1:
        return names[0]
    return symbol


def _resolved_stock_name_from_market_snapshot(symbol: str, market_snapshot: Dict[str, Any]) -> str:
    quote = market_snapshot.get("quote") if isinstance(market_snapshot, dict) else {}
    quote = quote if isinstance(quote, dict) else {}
    for key in ("name", "stockName", "stock_name", "securityName"):
        name = str(quote.get(key) or "").strip()
        if name and not _is_symbol_placeholder(symbol, name):
            return name
    return ""


def _merge_stock_name_into_state(state: Dict[str, Any], symbol: str, stock_name: str) -> bool:
    name = str(stock_name or "").strip()
    if not name or _is_symbol_placeholder(symbol, name):
        return False
    symbols = _parse_symbols(str(state.get("symbol") or ""))
    if symbol not in symbols:
        return False
    names = _split_stock_names(state.get("stock_name"))
    changed = False
    next_names: list[str] = []
    for index, current_symbol in enumerate(symbols):
        current_name = names[index] if index < len(names) else ""
        if current_symbol == symbol and _is_symbol_placeholder(current_symbol, current_name):
            current_name = name
            changed = True
        next_names.append(current_name or current_symbol)
    if changed:
        state["stock_name"] = ",".join(next_names)
    return changed


def _clean_symbol_text_map(value: Any) -> Dict[str, str]:
    if not isinstance(value, dict):
        return {}
    cleaned: Dict[str, str] = {}
    for raw_symbol, raw_text in value.items():
        symbol = str(raw_symbol or "").strip()
        text = str(raw_text or "").strip()
        if symbol and text:
            cleaned[symbol] = text
    return cleaned


def _sync_managed_symbol_pool(state: Dict[str, Any]) -> None:
    symbols = _parse_symbols(str(state.get("symbol") or ""))
    signal_ids = state.get("signal_ids") if isinstance(state.get("signal_ids"), dict) else {}
    for raw_symbol in signal_ids:
        symbol = str(raw_symbol or "").strip()
        if symbol and symbol not in symbols:
            symbols.append(symbol)
    state["symbol"] = ",".join(symbols)

    names = _split_stock_names(state.get("stock_name"))
    if not symbols:
        state["stock_name"] = str(state.get("stock_name") or "").strip()
        state["enabled"] = False
        return

    next_names: list[str] = []
    for index, symbol in enumerate(symbols):
        current_name = names[index] if index < len(names) else ""
        next_names.append(current_name or symbol)
    state["stock_name"] = ",".join(next_names)
    if not state.get("signal_id"):
        state["signal_id"] = signal_ids.get(symbols[0])


def _model_dump(model: Any) -> Dict[str, Any]:
    return model.model_dump() if hasattr(model, "model_dump") else model.dict()


def _default_simulation_module() -> Dict[str, Any]:
    return {
        "name": "simulation",
        "enabled": True,
        "execution_mode": "PAPER",
        "order_namespace": "SIM_*",
        "portfolio_type": "paper",
        "simulation_only": True,
        "is_real_trade": False,
        "status": "ACTIVE",
    }


def _default_live_module() -> Dict[str, Any]:
    return {
        "name": "live",
        "enabled": False,
        "execution_enabled": False,
        "order_router": "DISABLED",
        "broker_profile_id": "",
        "account_id": "",
        "max_order_value": 0.0,
        "max_position_ratio": 0.0,
        "require_manual_confirmation": True,
        "require_kill_switch_clear": True,
        "status": "CONFIGURED_DISABLED",
        "disabled_reason": "Live trading configuration is recorded but not used by SignalOps automation.",
        "simulation_only": True,
        "is_real_trade": False,
    }


def _normalize_simulation_module(value: Any) -> Dict[str, Any]:
    payload = value if isinstance(value, dict) else {}
    return {
        **_default_simulation_module(),
        **{
            key: payload[key]
            for key in ("name", "portfolio_type")
            if key in payload and str(payload[key]).strip()
        },
        "enabled": bool(payload.get("enabled", True)),
        "execution_mode": "PAPER",
        "order_namespace": "SIM_*",
        "simulation_only": True,
        "is_real_trade": False,
        "status": "ACTIVE" if payload.get("enabled", True) is not False else "PAUSED",
    }


def _normalize_live_module(value: Any) -> Dict[str, Any]:
    payload = value if isinstance(value, dict) else {}
    normalized = _default_live_module()
    for key in ("broker_profile_id", "account_id"):
        normalized[key] = str(payload.get(key) or "").strip()
    normalized["max_order_value"] = _clamp_float(payload.get("max_order_value"), 0.0, 0.0, 1_000_000_000.0)
    normalized["max_position_ratio"] = _clamp_float(payload.get("max_position_ratio"), 0.0, 0.0, 1.0)
    normalized["require_manual_confirmation"] = True
    normalized["require_kill_switch_clear"] = True
    normalized["enabled"] = False
    normalized["execution_enabled"] = False
    normalized["order_router"] = "DISABLED"
    normalized["status"] = "CONFIGURED_DISABLED"
    normalized["simulation_only"] = True
    normalized["is_real_trade"] = False
    return normalized


def _normalize_automation_state(state: Dict[str, Any]) -> None:
    requested_mode = str(state.get("automation_mode") or AUTOMATION_MODE_SIMULATION).upper()
    state["automation_mode"] = AUTOMATION_MODE_SIMULATION if requested_mode != AUTOMATION_MODE_LIVE else AUTOMATION_MODE_SIMULATION
    state["simulation_module"] = _normalize_simulation_module(state.get("simulation_module"))
    state["live_module"] = _normalize_live_module(state.get("live_module"))


def _automation_modules(config_or_state: Any) -> Dict[str, Any]:
    payload = _model_dump(config_or_state) if hasattr(config_or_state, "model_dump") else dict(config_or_state or {})
    simulation = _normalize_simulation_module(payload.get("simulation_module"))
    live = _normalize_live_module(payload.get("live_module"))
    return {
        "mode": AUTOMATION_MODE_SIMULATION,
        "simulation": simulation,
        "live": live,
        "active_module": "simulation",
        "live_ready": False,
        "real_trade_enabled": False,
        "routing_policy": "SignalOps automation writes only SIM_* paper orders. Live config is persisted for future wiring but ignored by ticks, daily review, and commands.",
    }


def _combined_status_from_modules(values: list[Any]) -> str:
    statuses: set[str] = set()
    for value in values:
        if isinstance(value, dict):
            statuses.add(str(value.get("status") or "WARN").upper())
    if any(status in {"FAILED", "ERROR"} for status in statuses):
        return "WARN"
    return "PASS" if statuses and statuses <= {"PASS", "READY"} else "WARN"


def _compact_module_payload(value: Any, keys: list[str]) -> Dict[str, Any]:
    payload = value if isinstance(value, dict) else {}
    compact = {key: payload.get(key) for key in keys if key in payload}
    compact["simulation_only"] = True
    compact["is_real_trade"] = False
    return compact


def _unique_text(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _module_path_risk_filter(module_evidence: Any) -> Dict[str, Any]:
    evidence = module_evidence if isinstance(module_evidence, dict) else {}
    quant_core = evidence.get("quantCore") if isinstance(evidence.get("quantCore"), dict) else {}
    interpretation = (
        quant_core.get("coreInterpretation")
        if isinstance(quant_core.get("coreInterpretation"), dict)
        else {}
    )
    path_risk = interpretation.get("pathRiskFilter") if isinstance(interpretation.get("pathRiskFilter"), dict) else {}
    return path_risk


def _module_path_risk_summary(module_evidence: Any) -> Dict[str, Any]:
    path_risk = _module_path_risk_filter(module_evidence)
    if not path_risk:
        return {}
    proxy = path_risk.get("mfeMaeProxy") if isinstance(path_risk.get("mfeMaeProxy"), dict) else {}
    provenance = path_risk.get("provenance") if isinstance(path_risk.get("provenance"), dict) else {}
    return {
        "status": path_risk.get("status"),
        "riskPolicy": str(path_risk.get("riskPolicy") or "").upper(),
        "downsideRiskScore": path_risk.get("downsideRiskScore"),
        "maxRiskGradient": path_risk.get("maxRiskGradient"),
        "mfeProxy": proxy.get("mfeProxy"),
        "maeProxy": proxy.get("maeProxy"),
        "riskRewardProxy": proxy.get("riskRewardProxy"),
        "actionBoundary": path_risk.get("actionBoundary") or provenance.get("actionBoundary"),
        "labelStatus": path_risk.get("labelStatus"),
        "sampleQuality": path_risk.get("sampleQuality"),
        "leakagePolicy": path_risk.get("leakagePolicy"),
        "simulation_only": True,
        "is_real_trade": False,
    }


def _module_future_trend_probability(module_evidence: Any) -> Dict[str, Any]:
    evidence = module_evidence if isinstance(module_evidence, dict) else {}
    quant_core = evidence.get("quantCore") if isinstance(evidence.get("quantCore"), dict) else {}
    interpretation = (
        quant_core.get("coreInterpretation")
        if isinstance(quant_core.get("coreInterpretation"), dict)
        else {}
    )
    future = interpretation.get("futureTrendProbability") if isinstance(interpretation.get("futureTrendProbability"), dict) else {}
    if not future:
        return {}
    points = future.get("points") if isinstance(future.get("points"), list) else []
    primary = next((item for item in points if isinstance(item, dict)), {})
    calibration = future.get("calibration") if isinstance(future.get("calibration"), dict) else {}
    feedback = future.get("decisionFeedback") if isinstance(future.get("decisionFeedback"), dict) else {}
    return {
        "version": future.get("version"),
        "source": future.get("source"),
        "horizonDays": primary.get("horizonDays"),
        "calibratedUpProbability": primary.get("calibratedUpProbability"),
        "calibratedDownProbability": primary.get("calibratedDownProbability"),
        "confidence": primary.get("confidence"),
        "calibrationStatus": primary.get("calibrationStatus") or calibration.get("status"),
        "sampleCount": calibration.get("sampleCount"),
        "brierUp": calibration.get("brierUp"),
        "brierDown": calibration.get("brierDown"),
        "signalopsPolicyHint": feedback.get("signalopsPolicyHint"),
        "actionBoundary": feedback.get("actionBoundary") or future.get("actionBoundary"),
        "simulation_only": True,
        "is_real_trade": False,
    }


def _compact_portfolio_snapshot(value: Any) -> Dict[str, Any]:
    snapshot = value if isinstance(value, dict) else {}
    if not snapshot:
        return {}
    return {
        key: snapshot.get(key)
        for key in [
            "snapshotId",
            "sourceType",
            "sourceName",
            "accountName",
            "totalAssets",
            "stockMarketValue",
            "cash",
            "availableCash",
            "totalPositionRatio",
            "positionCount",
            "qualityStatus",
            "importedAt",
            "updatedAt",
            "simulation_only",
            "is_real_trade",
        ]
        if key in snapshot
    }


def _capital_snapshot(portfolio: Optional[Dict[str, Any]]) -> Dict[str, float]:
    portfolio = portfolio or {}
    cash = _clamp_float(portfolio.get("available_cash"), 0.0, 0.0, 1_000_000_000.0)
    position_value = _clamp_float(portfolio.get("market_value"), 0.0, -1_000_000_000.0, 1_000_000_000.0)
    initial_cash = _clamp_float(portfolio.get("initial_cash"), 0.0, 0.0, 1_000_000_000.0)
    total_assets = cash + position_value
    return {
        "capital": round(total_assets, 6),
        "cash_available": round(cash, 6),
        "position_value": round(position_value, 6),
        "initial_cash": round(initial_cash, 6),
    }


def _commission_amount(config: AutoPaperTradingConfig, trade_amount: float) -> float:
    amount = _clamp_float(trade_amount, 0.0, 0.0, 1_000_000_000.0)
    if amount <= 0:
        return 0.0
    rate = _clamp_float(getattr(config, "commission_rate", DEFAULT_COMMISSION_RATE), DEFAULT_COMMISSION_RATE, 0.0, 0.1)
    min_fee = _clamp_float(getattr(config, "commission_min_fee", DEFAULT_COMMISSION_MIN_FEE), DEFAULT_COMMISSION_MIN_FEE, 0.0, 1_000_000.0)
    min_trade_value = _clamp_float(
        getattr(config, "commission_min_trade_value", DEFAULT_COMMISSION_MIN_TRADE_VALUE),
        DEFAULT_COMMISSION_MIN_TRADE_VALUE,
        0.0,
        1_000_000_000.0,
    )
    if min_fee > 0 and min_trade_value > 0 and amount < min_trade_value:
        return round(min_fee, 6)
    return round(amount * rate, 6)


def _stamp_duty_amount(config: AutoPaperTradingConfig, action: str, trade_amount: float) -> float:
    amount = _clamp_float(trade_amount, 0.0, 0.0, 1_000_000_000.0)
    if amount <= 0 or action not in {"SIM_SELL", "SIM_CLOSE", "SIM_T_SELL"}:
        return 0.0
    rate = _clamp_float(getattr(config, "stamp_duty_rate", DEFAULT_STAMP_DUTY_RATE), DEFAULT_STAMP_DUTY_RATE, 0.0, 0.01)
    return round(amount * rate, 6)


def _affordable_board_lot_quantity(available_cash: float, price: float, config: AutoPaperTradingConfig) -> int:
    cash = _clamp_float(available_cash, 0.0, 0.0, 1_000_000_000.0)
    trade_price = _clamp_float(price, 0.0, 0.0, 1_000_000_000.0)
    if cash <= 0 or trade_price <= 0:
        return 0
    high_lots = int(cash // (trade_price * BOARD_LOT_SIZE))
    low = 0
    best = 0
    while low <= high_lots:
        mid = (low + high_lots) // 2
        quantity = mid * BOARD_LOT_SIZE
        amount = quantity * trade_price
        if amount + _commission_amount(config, amount) <= cash:
            best = quantity
            low = mid + 1
        else:
            high_lots = mid - 1
    return best


def _closed_trading_dates() -> set[str]:
    raw = os.getenv("AUTO_PAPER_CLOSED_TRADING_DATES", "")
    return {item.strip() for item in raw.split(",") if item.strip()}


def _llm_gate(state: Dict[str, Any]) -> Dict[str, Any]:
    local_now = _now().astimezone(CHINA_TZ)
    local_time = local_now.time()
    local_date = local_now.date().isoformat()
    is_trading_day = local_now.weekday() < 5 and local_date not in _closed_trading_dates()
    if not is_trading_day:
        return {"allowed": False, "status": "NON_TRADING_DAY", "date": local_date, "close_review": False}

    in_morning = MORNING_SESSION_START <= local_time <= MORNING_SESSION_END
    in_afternoon = AFTERNOON_SESSION_START <= local_time < AFTERNOON_SESSION_END
    if in_morning or in_afternoon:
        return {"allowed": True, "status": "TRADING_SESSION", "date": local_date, "close_review": False}

    if local_time >= AFTERNOON_SESSION_END:
        already_used = state.get("last_llm_close_call_date") == local_date
        return {
            "allowed": not already_used,
            "status": "AFTER_CLOSE_REVIEW_USED" if already_used else "AFTER_CLOSE_REVIEW",
            "date": local_date,
            "close_review": True,
        }

    if MORNING_SESSION_END < local_time < AFTERNOON_SESSION_START:
        status = "LUNCH_BREAK"
    else:
        status = "OUT_OF_SESSION"
    return {"allowed": False, "status": status, "date": local_date, "close_review": False}


def _a_share_session_gate(*, force: bool = False) -> Dict[str, Any]:
    local_now = _now().astimezone(CHINA_TZ)
    local_time = local_now.time()
    local_date = local_now.date().isoformat()
    is_trading_day = local_now.weekday() < 5 and local_date not in _closed_trading_dates()
    in_session = (
        MORNING_SESSION_START <= local_time <= MORNING_SESSION_END
        or AFTERNOON_SESSION_START <= local_time < AFTERNOON_SESSION_END
    )
    status = "TRADING_SESSION" if is_trading_day and in_session else "NON_TRADING_SESSION"
    allowed = is_trading_day and in_session
    if force and not allowed:
        status = f"{status}_FORCE_OVERRIDE"
        allowed = True
    return {
        "allowed": allowed,
        "status": status,
        "date": local_date,
        "local_time": local_time.isoformat(timespec="minutes"),
        "force_override": force and status.endswith("FORCE_OVERRIDE"),
    }


def _a_share_limit_rate_pct(symbol: str, stock_name: str = "") -> float:
    normalized_symbol = str(symbol or "").strip()
    if normalized_symbol.startswith(("300", "301", "688")):
        return 20.0
    if normalized_symbol.startswith(("8", "4", "920")):
        return 30.0
    if _is_a_share_risk_warning_name(stock_name) and normalized_symbol.startswith(("0", "6")):
        return 5.0
    return 10.0


def _is_a_share_risk_warning_name(stock_name: str) -> bool:
    normalized_name = str(stock_name or "").upper().replace("＊", "*")
    return bool(re.search(r"(^|[^A-Z0-9])(S\*ST|SST|\*ST|ST)(?=$|[^A-Z0-9])", normalized_name))


def _a_share_price_limit_context(config: AutoPaperTradingConfig, change_percent: Any) -> Dict[str, Any]:
    limit_rate_pct = _a_share_limit_rate_pct(config.symbol, config.stock_name)
    pct = _clamp_float(change_percent, 0.0, -100.0, 1000.0)
    return {
        "change_percent": pct,
        "limit_rate_pct": limit_rate_pct,
        "tolerance_pct": PRICE_LIMIT_TOLERANCE_PCT,
        "at_limit_up": pct >= limit_rate_pct - PRICE_LIMIT_TOLERANCE_PCT,
        "at_limit_down": pct <= -limit_rate_pct + PRICE_LIMIT_TOLERANCE_PCT,
    }


def _record_pnl_rate(record: Dict[str, Any]) -> float:
    return _clamp_float(record.get("pnl_rate"), 0.0, -1.0, 1.0)


def _record_drawdown(record: Dict[str, Any]) -> float:
    return abs(_clamp_float(record.get("max_drawdown"), 0.0, -1.0, 0.0))


def _record_has_order(record: Dict[str, Any]) -> bool:
    return int(record.get("order_count") or 0) > 0


def _record_is_failure(record: Dict[str, Any]) -> bool:
    return _record_has_order(record) and (bool(record.get("invalidation_triggered")) or _record_pnl_rate(record) < -0.01)


def _record_is_win(record: Dict[str, Any]) -> bool:
    return _record_has_order(record) and not bool(record.get("invalidation_triggered")) and _record_pnl_rate(record) > 0.01


def _record_sample_weight(record: Dict[str, Any]) -> float:
    has_order = _record_has_order(record)
    evidence_scale = min(max(abs(_record_pnl_rate(record)), _record_drawdown(record)) / 0.10, 0.50)
    invalidation_bonus = 0.15 if record.get("invalidation_triggered") else 0.0
    base = 1.0 if has_order else 0.35
    return _clamp_float(base * (1.0 + evidence_scale + invalidation_bonus), base, 0.20, 1.65)


def _record_trading_date(record: Dict[str, Any]) -> str:
    value = str(record.get("trading_date") or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value
    cleaned_at = str(record.get("cleaned_at") or "").strip()
    return cleaned_at[:10] if re.fullmatch(r"\d{4}-\d{2}-\d{2}", cleaned_at[:10]) else ""


def _stable_json_hash(value: Any, length: int = 12) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:length]


def _stable_parameter_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _flatten_parameter_config(value: Any, prefix: str = "") -> list[Dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    rows: list[Dict[str, Any]] = []
    for key in sorted(str(item) for item in value.keys()):
        item = value.get(key)
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(item, dict):
            rows.extend(_flatten_parameter_config(item, path))
        else:
            rows.append({"key": path, "value": item})
    return rows


def _parameter_diff_summary(baseline_config: Any, candidate_config: Any) -> Dict[str, Any]:
    baseline_rows = _flatten_parameter_config(baseline_config)
    candidate_rows = _flatten_parameter_config(candidate_config)
    baseline_by_key = {str(row["key"]): row.get("value") for row in baseline_rows}
    candidate_by_key = {str(row["key"]): row.get("value") for row in candidate_rows}
    keys = sorted(set(baseline_by_key) | set(candidate_by_key))
    rows: list[Dict[str, Any]] = []
    changed_count = 0
    added_count = 0
    removed_count = 0
    unchanged_count = 0
    for key in keys:
        has_baseline = key in baseline_by_key
        has_candidate = key in candidate_by_key
        baseline = baseline_by_key.get(key)
        candidate = candidate_by_key.get(key)
        if has_baseline and has_candidate:
            if _stable_parameter_value(baseline) == _stable_parameter_value(candidate):
                change_type = "UNCHANGED"
                unchanged_count += 1
            else:
                change_type = "CHANGED"
                changed_count += 1
        elif has_candidate:
            change_type = "ADDED"
            added_count += 1
        else:
            change_type = "REMOVED"
            removed_count += 1
        rows.append({
            "key": key,
            "baseline": baseline if has_baseline else None,
            "candidate": candidate if has_candidate else None,
            "change_type": change_type,
        })
    changed_rows = [row for row in rows if row["change_type"] != "UNCHANGED"]
    visible_rows = changed_rows if changed_rows else rows
    total_changed = changed_count + added_count + removed_count
    status = "EMPTY" if not rows else "CHANGED" if total_changed else "UNCHANGED"
    return {
        "policy_id": "signalops_candidate_parameter_diff_v1",
        "status": status,
        "changed_count": changed_count,
        "added_count": added_count,
        "removed_count": removed_count,
        "unchanged_count": unchanged_count,
        "total_parameter_count": len(rows),
        "visible_row_count": min(len(visible_rows), REVIEW_PARAMETER_DIFF_ROW_LIMIT),
        "truncated": len(visible_rows) > REVIEW_PARAMETER_DIFF_ROW_LIMIT,
        "rows": visible_rows[:REVIEW_PARAMETER_DIFF_ROW_LIMIT],
        "source": "server_generated",
        "simulation_only": True,
        "is_real_trade": False,
    }


def _parameter_diff_snapshot_from_queue_item(
    queue_item: Dict[str, Any],
    baseline_config: Dict[str, Any],
    candidate_config: Dict[str, Any],
) -> tuple[Dict[str, Any], str]:
    strategy_experiment = (
        queue_item.get("strategy_experiment")
        if isinstance(queue_item.get("strategy_experiment"), dict)
        else {}
    )
    existing_summary = queue_item.get("parameter_diff_summary")
    if not isinstance(existing_summary, dict):
        existing_summary = strategy_experiment.get("parameter_diff_summary")
    if isinstance(existing_summary, dict) and existing_summary.get("rows") is not None:
        summary = dict(existing_summary)
        summary["rows"] = [
            dict(row)
            for row in summary.get("rows", [])
            if isinstance(row, dict)
        ]
    else:
        summary = _parameter_diff_summary(baseline_config, candidate_config)
    summary.setdefault("policy_id", "signalops_candidate_parameter_diff_v1")
    summary.setdefault("source", "server_generated")
    summary.setdefault("status", "EMPTY")
    summary.setdefault("changed_count", 0)
    summary.setdefault("added_count", 0)
    summary.setdefault("removed_count", 0)
    summary.setdefault("unchanged_count", 0)
    summary.setdefault("total_parameter_count", len(summary.get("rows", [])))
    summary.setdefault("visible_row_count", len(summary.get("rows", [])))
    summary.setdefault("truncated", False)
    for key in (
        "changed_count",
        "added_count",
        "removed_count",
        "unchanged_count",
        "total_parameter_count",
        "visible_row_count",
    ):
        try:
            summary[key] = int(summary.get(key) or 0)
        except (TypeError, ValueError):
            summary[key] = 0
    summary["simulation_only"] = True
    summary["is_real_trade"] = False
    checksum = f"sigops-paramdiff-{_stable_json_hash(summary, length=16)}"
    return summary, checksum


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


def _signalops_experiment_package_hash(
    *,
    baseline_config: Dict[str, Any],
    candidate_config: Dict[str, Any],
    train_window: Dict[str, Any],
    validation_window: Dict[str, Any],
    cleaned_records: list[Dict[str, Any]],
    benchmark_symbol: str = DEFAULT_EXPERIMENT_BENCHMARK_SYMBOL,
) -> str:
    payload = {
        "version": 1,
        "baseline_config": _stable_experiment_payload(baseline_config),
        "candidate_config": _stable_experiment_payload(candidate_config),
        "train_window": {
            "start": str(train_window.get("start") or ""),
            "end": str(train_window.get("end") or ""),
        },
        "validation_window": {
            "start": str(validation_window.get("start") or ""),
            "end": str(validation_window.get("end") or ""),
        },
        "cost_model": {
            "commission_rate": baseline_config.get("commission_rate"),
            "stamp_duty_rate": baseline_config.get("stamp_duty_rate"),
            "commission_min_fee": baseline_config.get("commission_min_fee"),
        },
        "market_data_source": "signalops_json_state",
        "benchmark_symbol": benchmark_symbol,
        "sample_record_ids": [
            str(item.get("record_id") or _cleaned_record_identity(item))
            for item in cleaned_records
            if isinstance(item, dict)
        ],
    }
    return f"sigops-{_stable_json_hash(payload, length=16)}"


def _record_outcome(record: Dict[str, Any]) -> str:
    if _record_is_win(record):
        return "WIN"
    if _record_is_failure(record):
        return "FAILURE"
    if _record_has_order(record):
        return "NEUTRAL"
    return "NO_TRADE"


def _record_sample_quality(record: Dict[str, Any]) -> str:
    current = str(record.get("sample_quality") or "").strip().upper()
    if current in EVIDENCE_QUALITY_VALUES:
        return current
    if not _record_trading_date(record):
        return "LOW"
    if not _record_has_order(record):
        return "SUPPORTING_ONLY"
    outcome = _record_outcome(record)
    if outcome in {"WIN", "FAILURE"}:
        has_direct_evidence = bool(record.get("latest_order_id") or record.get("decision_id") or record.get("signal_id"))
        return "STRONG" if has_direct_evidence else "MEDIUM"
    return "MEDIUM"


def _normalize_evidence_refs(record: Dict[str, Any], record_id: str) -> list[Dict[str, Any]]:
    raw_refs = record.get("evidence_refs")
    refs = [dict(item) for item in raw_refs if isinstance(item, dict)] if isinstance(raw_refs, list) else []
    if record.get("signal_id"):
        refs.append({
            "source_type": "SIGNALOPS",
            "source_id": str(record.get("signal_id")),
            "label": "SignalOps lifecycle signal",
        })
    if record.get("latest_order_id"):
        refs.append({
            "source_type": "PAPER_ORDER",
            "source_id": str(record.get("latest_order_id")),
            "label": "SignalOps paper order",
        })
    if not refs:
        refs.append({
            "source_type": "CLEANED_SIGNAL_RECORD",
            "source_id": record_id,
            "label": "SignalOps cleaned record",
        })
    deduped: Dict[str, Dict[str, Any]] = {}
    for ref in refs:
        source_type = str(ref.get("source_type") or ref.get("source") or "UNKNOWN").strip().upper()
        source_id = str(ref.get("source_id") or ref.get("id") or "").strip()
        if not source_id:
            continue
        key = f"{source_type}:{source_id}"
        deduped[key] = {**ref, "source_type": source_type, "source_id": source_id}
    return list(deduped.values())


def _normalize_cleaned_record(raw: Dict[str, Any]) -> Dict[str, Any]:
    record = dict(raw)
    trading_date = _record_trading_date(record)
    signal_date = str(record.get("signal_date") or trading_date or "").strip()
    symbol = str(record.get("symbol") or "UNKNOWN").strip() or "UNKNOWN"
    latest_order_id = str(record.get("latest_order_id") or "").strip()
    signal_id = str(record.get("signal_id") or "").strip()
    source_type = str(record.get("source_type") or "SIGNALOPS_DAILY_REVIEW").strip().upper()
    identity_basis = {
        "signal_date": signal_date,
        "symbol": symbol,
        "signal_id": signal_id,
        "latest_order_id": latest_order_id,
        "latest_action": str(record.get("latest_action") or ""),
        "pnl_rate": _record_pnl_rate(record),
        "order_count": int(record.get("order_count") or 0),
    }
    record_id = str(record.get("record_id") or f"csr-{_stable_json_hash(identity_basis, length=16)}").strip()
    source_id = str(record.get("source_id") or signal_id or latest_order_id or record_id).strip()
    decision_id = str(record.get("decision_id") or latest_order_id or record_id).strip()
    record.update({
        "record_id": record_id,
        "trading_date": trading_date or signal_date,
        "signal_date": signal_date or trading_date,
        "symbol": symbol,
        "source_type": source_type,
        "source_id": source_id,
        "decision_id": decision_id,
        "outcome": str(record.get("outcome") or _record_outcome(record)).strip().upper(),
        "simulation_only": True,
        "is_real_trade": False,
    })
    record["evidence_refs"] = _normalize_evidence_refs(record, record_id)
    record["sample_quality"] = _record_sample_quality(record)
    return record


def _cleaned_record_identity(record: Dict[str, Any]) -> str:
    record_id = str(record.get("record_id") or "").strip()
    if record_id:
        return record_id
    key = {
        "trading_date": _record_trading_date(record),
        "symbol": str(record.get("symbol") or ""),
        "latest_order_id": str(record.get("latest_order_id") or ""),
        "latest_action": str(record.get("latest_action") or ""),
        "pnl_rate": _record_pnl_rate(record),
        "order_count": int(record.get("order_count") or 0),
    }
    return _stable_json_hash(key, length=16)


def _capped_cleaned_record_history(records: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    deduped: Dict[str, Dict[str, Any]] = {}
    for raw in records:
        if not isinstance(raw, dict):
            continue
        record = _normalize_cleaned_record(raw)
        deduped[_cleaned_record_identity(record)] = record
    ordered = sorted(
        deduped.values(),
        key=lambda item: (
            _record_trading_date(item),
            str(item.get("cleaned_at") or ""),
            str(item.get("symbol") or ""),
            str(item.get("latest_order_id") or ""),
        ),
    )
    return ordered[-CLEANED_RECORD_HISTORY_LIMIT:]


def _capped_trade_record_history(records: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    deduped: Dict[str, Dict[str, Any]] = {}
    for raw in records:
        if not isinstance(raw, dict):
            continue
        record = _normalize_cleaned_record(raw)
        if not _record_has_order(record):
            continue
        deduped[_cleaned_record_identity(record)] = record
    ordered = sorted(
        deduped.values(),
        key=lambda item: (
            _record_trading_date(item),
            str(item.get("cleaned_at") or ""),
            str(item.get("symbol") or ""),
            str(item.get("latest_order_id") or ""),
        ),
    )
    return ordered[-CLEANED_RECORD_HISTORY_LIMIT:]


def _compact_observation_record(record: Dict[str, Any]) -> Dict[str, Any]:
    tags = record.get("failure_tags") if isinstance(record.get("failure_tags"), list) else []
    triggers = record.get("trigger_conditions") if isinstance(record.get("trigger_conditions"), list) else []
    trading_date = _record_trading_date(record)
    signal_date = str(record.get("signal_date") or "").strip()
    if not trading_date and re.fullmatch(r"\d{4}-\d{2}-\d{2}", signal_date):
        trading_date = signal_date
    dated_record = {**record, "trading_date": trading_date}
    return {
        "record_id": str(record.get("record_id") or _cleaned_record_identity(dated_record)),
        "trading_date": trading_date,
        "symbol": str(record.get("symbol") or "UNKNOWN"),
        "latest_action": str(record.get("latest_action") or "NONE").upper(),
        "signal_status": str(record.get("signal_status") or ""),
        "sample_quality": _record_sample_quality(dated_record),
        "failure_tags": [str(item) for item in tags[:4]],
        "trigger_conditions": [str(item) for item in triggers[:3]],
        "simulation_only": True,
        "is_real_trade": False,
    }


def _empty_compressed_observation_history() -> Dict[str, Any]:
    return {
        "version": 1,
        "updated_at": "",
        "total_count": 0,
        "compressed_count": 0,
        "buckets": [],
        "recent": [],
        "by_symbol": {},
        "by_date": {},
        "simulation_only": True,
        "is_real_trade": False,
    }


def _normalize_compressed_observation_history(value: Any) -> Dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    summary = _empty_compressed_observation_history()
    summary["updated_at"] = str(raw.get("updated_at") or "")
    summary["total_count"] = int(_clamp_float(raw.get("total_count"), 0.0, 0.0, 1_000_000.0))
    summary["compressed_count"] = int(_clamp_float(raw.get("compressed_count"), summary["total_count"], 0.0, 1_000_000.0))
    buckets = [dict(item) for item in raw.get("buckets", []) if isinstance(item, dict)]
    normalized_buckets = []
    for bucket in buckets[:12]:
        normalized_buckets.append({
            "bucket_id": str(bucket.get("bucket_id") or _stable_json_hash(bucket)),
            "latest_action": str(bucket.get("latest_action") or "NONE").upper(),
            "sample_quality": str(bucket.get("sample_quality") or "SUPPORTING_ONLY").upper(),
            "signal_status": str(bucket.get("signal_status") or ""),
            "failure_tags": [str(item) for item in (bucket.get("failure_tags") if isinstance(bucket.get("failure_tags"), list) else [])[:4]],
            "trigger_conditions": [str(item) for item in (bucket.get("trigger_conditions") if isinstance(bucket.get("trigger_conditions"), list) else [])[:3]],
            "count": int(_clamp_float(bucket.get("count"), 0.0, 0.0, 1_000_000.0)),
            "latest_date": str(bucket.get("latest_date") or ""),
            "symbols": {
                str(key): int(_clamp_float(value, 0.0, 0.0, 1_000_000.0))
                for key, value in (bucket.get("symbols") if isinstance(bucket.get("symbols"), dict) else {}).items()
            },
        })
    summary["buckets"] = sorted(normalized_buckets, key=lambda item: (int(item.get("count") or 0), str(item.get("latest_date") or "")), reverse=True)[:8]
    summary["recent"] = [
        _compact_observation_record(item)
        for item in raw.get("recent", [])
        if isinstance(item, dict)
    ][-5:]
    summary["by_symbol"] = {
        str(key): {
            "count": int(_clamp_float(as_value.get("count") if isinstance(as_value, dict) else as_value, 0.0, 0.0, 1_000_000.0)),
            "latest_date": str(as_value.get("latest_date") or "") if isinstance(as_value, dict) else "",
        }
        for key, as_value in (raw.get("by_symbol") if isinstance(raw.get("by_symbol"), dict) else {}).items()
    }
    summary["by_date"] = {
        str(key): int(_clamp_float(value, 0.0, 0.0, 1_000_000.0))
        for key, value in (raw.get("by_date") if isinstance(raw.get("by_date"), dict) else {}).items()
    }
    return summary


def _compress_observation_history(current: Any, records: list[Dict[str, Any]]) -> Dict[str, Any]:
    summary = _normalize_compressed_observation_history(current)
    buckets_by_id = {
        str(bucket.get("bucket_id")): dict(bucket)
        for bucket in summary.get("buckets", [])
        if isinstance(bucket, dict)
    }
    recent = [dict(item) for item in summary.get("recent", []) if isinstance(item, dict)]
    by_symbol = {
        str(key): dict(value) if isinstance(value, dict) else {"count": int(value), "latest_date": ""}
        for key, value in (summary.get("by_symbol") if isinstance(summary.get("by_symbol"), dict) else {}).items()
    }
    by_date = {
        str(key): int(value)
        for key, value in (summary.get("by_date") if isinstance(summary.get("by_date"), dict) else {}).items()
    }
    total_count = int(summary.get("total_count") or 0)

    for raw in records:
        if not isinstance(raw, dict):
            continue
        record = _normalize_cleaned_record(raw)
        if _record_has_order(record):
            continue
        compact = _compact_observation_record(record)
        date = str(compact.get("trading_date") or "")
        symbol = str(compact.get("symbol") or "UNKNOWN")
        bucket_basis = {
            "latest_action": compact.get("latest_action"),
            "signal_status": compact.get("signal_status"),
            "sample_quality": compact.get("sample_quality"),
            "failure_tags": compact.get("failure_tags"),
            "trigger_conditions": compact.get("trigger_conditions"),
        }
        bucket_id = f"obs-{_stable_json_hash(bucket_basis, length=12)}"
        bucket = buckets_by_id.setdefault(bucket_id, {
            "bucket_id": bucket_id,
            **bucket_basis,
            "count": 0,
            "latest_date": "",
            "symbols": {},
        })
        bucket["count"] = int(bucket.get("count") or 0) + 1
        bucket["latest_date"] = max(str(bucket.get("latest_date") or ""), date)
        symbols = bucket.get("symbols") if isinstance(bucket.get("symbols"), dict) else {}
        symbols[symbol] = int(symbols.get(symbol) or 0) + 1
        bucket["symbols"] = dict(sorted(symbols.items(), key=lambda item: item[1], reverse=True)[:12])

        symbol_summary = by_symbol.setdefault(symbol, {"count": 0, "latest_date": ""})
        symbol_summary["count"] = int(symbol_summary.get("count") or 0) + 1
        symbol_summary["latest_date"] = max(str(symbol_summary.get("latest_date") or ""), date)
        if date:
            by_date[date] = int(by_date.get(date) or 0) + 1
        recent.append(compact)
        total_count += 1

    summary["updated_at"] = _now_iso()
    summary["total_count"] = total_count
    summary["compressed_count"] = total_count
    summary["buckets"] = sorted(
        buckets_by_id.values(),
        key=lambda item: (int(item.get("count") or 0), str(item.get("latest_date") or "")),
        reverse=True,
    )[:8]
    summary["recent"] = sorted(recent, key=lambda item: (str(item.get("trading_date") or ""), str(item.get("symbol") or "")))[-5:]
    summary["by_symbol"] = dict(
        sorted(by_symbol.items(), key=lambda item: (int(item[1].get("count") or 0), str(item[1].get("latest_date") or "")), reverse=True)[:32]
    )
    summary["by_date"] = dict(sorted(by_date.items(), key=lambda item: item[0])[-30:])
    summary["simulation_only"] = True
    summary["is_real_trade"] = False
    return summary


def _record_window_metrics(records: list[Dict[str, Any]]) -> Dict[str, Any]:
    trade_records = [record for record in records if _record_has_order(record)]
    wins = [record for record in trade_records if _record_is_win(record)]
    failures = [record for record in trade_records if _record_is_failure(record)]
    sample_quality_counts: Dict[str, int] = {}
    for record in records:
        quality = _record_sample_quality(record)
        sample_quality_counts[quality] = sample_quality_counts.get(quality, 0) + 1
    trade_qualities = [_record_sample_quality(record) for record in trade_records]
    if not trade_records:
        evidence_quality = "SUPPORTING_ONLY" if records else "LOW"
    elif any(item == "LOW" for item in trade_qualities):
        evidence_quality = "LOW"
    elif any(item == "SUPPORTING_ONLY" for item in trade_qualities):
        evidence_quality = "SUPPORTING_ONLY"
    elif all(item == "STRONG" for item in trade_qualities):
        evidence_quality = "STRONG"
    else:
        evidence_quality = "MEDIUM"
    evidence_weight = sum(_record_sample_weight(record) for record in records)
    avg_pnl_rate = (
        sum(_record_pnl_rate(record) * _record_sample_weight(record) for record in records) / evidence_weight
        if evidence_weight
        else 0.0
    )
    max_drawdown = max([_record_drawdown(record) for record in records] or [0.0])
    trade_count = len(trade_records)
    return {
        "sample_count": len(records),
        "trade_count": trade_count,
        "evidence_weight": round(evidence_weight, 4),
        "confidence": round(min(1.0, (evidence_weight / 6) ** 0.5) if evidence_weight else 0.0, 4),
        "wins": len(wins),
        "failures": len(failures),
        "win_rate": round(len(wins) / trade_count if trade_count else 0.0, 6),
        "failure_rate": round(len(failures) / trade_count if trade_count else 0.0, 6),
        "avg_pnl_rate": round(avg_pnl_rate, 6),
        "max_drawdown": round(-max_drawdown, 6),
        "sample_quality_counts": sample_quality_counts,
        "evidence_quality": evidence_quality,
    }


def _split_walk_forward_windows(records: list[Dict[str, Any]]) -> tuple[list[Dict[str, Any]], list[Dict[str, Any]], Dict[str, Any], Dict[str, Any]]:
    dated_records = [record for record in records if _record_trading_date(record)]
    dates = sorted({_record_trading_date(record) for record in dated_records})
    if len(dates) < 2:
        return [], [], {"start": "", "end": "", "dates": []}, {"start": "", "end": "", "dates": []}
    validation_date_count = max(1, min(len(dates) - 1, round(len(dates) * 0.34)))
    train_dates = set(dates[:-validation_date_count])
    validation_dates = set(dates[-validation_date_count:])
    train_records = [record for record in dated_records if _record_trading_date(record) in train_dates]
    validation_records = [record for record in dated_records if _record_trading_date(record) in validation_dates]
    train_window = {
        "start": dates[0],
        "end": dates[-validation_date_count - 1],
        "dates": sorted(train_dates),
    }
    validation_window = {
        "start": dates[-validation_date_count],
        "end": dates[-1],
        "dates": sorted(validation_dates),
    }
    return train_records, validation_records, train_window, validation_window


def _normalize_review_queue_state(value: Any) -> Dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    items = [dict(item) for item in raw.get("items", []) if isinstance(item, dict)]
    observations = [dict(item) for item in raw.get("observations", []) if isinstance(item, dict)]
    return {
        "version": 1,
        "updated_at": str(raw.get("updated_at") or ""),
        "items": items[-REVIEW_QUEUE_ITEM_LIMIT:],
        "observations": observations[-REVIEW_QUEUE_ITEM_LIMIT:],
        "counts": raw.get("counts") if isinstance(raw.get("counts"), dict) else {},
        "simulation_only": True,
        "is_real_trade": False,
    }


def _normalize_experiment_validation_state(value: Any) -> Dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    raw_attempts = raw.get("attempts") if isinstance(raw.get("attempts"), dict) else {}
    attempts = {
        str(key): dict(item)
        for key, item in raw_attempts.items()
        if str(key).strip() and isinstance(item, dict)
    }
    ordered = sorted(
        attempts.items(),
        key=lambda pair: str(pair[1].get("updated_at") or pair[1].get("created_at") or ""),
    )[-REVIEW_QUEUE_ITEM_LIMIT:]
    attempts = dict(ordered)
    return {
        "version": 1,
        "updated_at": str(raw.get("updated_at") or ""),
        "latest_experiment_package_hash": str(raw.get("latest_experiment_package_hash") or ""),
        "attempts": attempts,
        "counts": raw.get("counts") if isinstance(raw.get("counts"), dict) else {
            "total": len(attempts),
            "ready_for_review": sum(1 for item in attempts.values() if item.get("promotion_status") == "READY_FOR_REVIEW"),
            "backtest_pending": sum(1 for item in attempts.values() if item.get("promotion_status") == "BACKTEST_PENDING"),
            "sync_failed": sum(1 for item in attempts.values() if item.get("review_queue_sync_status") == "FAILED"),
        },
        "simulation_only": True,
        "is_real_trade": False,
    }


def _normalize_random_validation_state(value: Any) -> Dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    raw_attempts = raw.get("attempts") if isinstance(raw.get("attempts"), list) else []
    attempts = [dict(item) for item in raw_attempts if isinstance(item, dict)][-REVIEW_QUEUE_ITEM_LIMIT:]
    drift = raw.get("strategy_drift_summary") if isinstance(raw.get("strategy_drift_summary"), dict) else {}
    return {
        "version": 1,
        "updated_at": str(raw.get("updated_at") or ""),
        "latest_job_id": str(raw.get("latest_job_id") or ""),
        "latest_summary": raw.get("latest_summary") if isinstance(raw.get("latest_summary"), dict) else {},
        "attempts": attempts,
        "counts": raw.get("counts") if isinstance(raw.get("counts"), dict) else {
            "total": len(attempts),
            "applied": sum(1 for item in attempts if (item.get("applied_adjustment") or {}).get("applied")),
            "strong": sum(1 for item in attempts if item.get("evidence_level") == "STRONG"),
            "medium": sum(1 for item in attempts if item.get("evidence_level") == "MEDIUM"),
            "weak": sum(1 for item in attempts if item.get("evidence_level") == "WEAK"),
        },
        "strategy_drift_summary": drift,
        "simulation_only": True,
        "is_real_trade": False,
    }


def _random_validation_drift_summary(attempts: list[Dict[str, Any]]) -> Dict[str, Any]:
    cumulative: Dict[str, float] = {}
    applied_count = 0
    last_applied: Dict[str, Any] = {}
    for item in attempts:
        adjustment = item.get("applied_adjustment") if isinstance(item.get("applied_adjustment"), dict) else {}
        if not adjustment.get("applied"):
            continue
        applied_count += 1
        last_applied = adjustment
        for key, delta in (adjustment.get("deltas") if isinstance(adjustment.get("deltas"), dict) else {}).items():
            try:
                cumulative[str(key)] = round(cumulative.get(str(key), 0.0) + float(delta), 6)
            except (TypeError, ValueError):
                continue
    return {
        "applied_count": applied_count,
        "cumulative_deltas": cumulative,
        "latest_applied_adjustment": last_applied,
        "simulation_only": True,
        "is_real_trade": False,
    }


def _upsert_experiment_validation_state(
    current: Any,
    result: Dict[str, Any],
    *,
    review_queue_sync_status: str = "",
) -> Dict[str, Any]:
    state = _normalize_experiment_validation_state(current)
    experiment_hash = str(result.get("experiment_package_hash") or "").strip()
    if not experiment_hash:
        return state
    now = _now_iso()
    validation = result.get("walk_forward_validation") if isinstance(result.get("walk_forward_validation"), dict) else {}
    benchmark = result.get("benchmark_comparison") if isinstance(result.get("benchmark_comparison"), dict) else {}
    research_package = (
        result.get("research_evidence_package")
        if isinstance(result.get("research_evidence_package"), dict)
        else {}
    )
    attempts = state.get("attempts") if isinstance(state.get("attempts"), dict) else {}
    previous = attempts.get(experiment_hash) if isinstance(attempts.get(experiment_hash), dict) else {}
    sync_status = str(review_queue_sync_status or result.get("review_queue_sync_status") or "NOT_SYNCED").strip().upper()
    record = {
        **previous,
        "experiment_package_hash": experiment_hash,
        "status": validation.get("status") or result.get("promotion_status") or "BACKTEST_PENDING",
        "promotion_status": result.get("promotion_status") or "BACKTEST_PENDING",
        "walk_forward_run_ids": result.get("walk_forward_run_ids") if isinstance(result.get("walk_forward_run_ids"), dict) else {},
        "walk_forward_validation": validation,
        "benchmark_comparison": benchmark,
        "benchmark_unavailable_reason": result.get("benchmark_unavailable_reason") or benchmark.get("unavailable_reason") or benchmark.get("reason") or "",
        "research_evidence_package": research_package,
        "review_queue_sync_status": sync_status,
        "warnings": result.get("warnings") if isinstance(result.get("warnings"), list) else [],
        "created_at": previous.get("created_at") or now,
        "updated_at": now,
        "simulation_only": True,
        "is_real_trade": False,
    }
    attempts[experiment_hash] = record
    ordered = sorted(
        attempts.items(),
        key=lambda pair: str(pair[1].get("updated_at") or pair[1].get("created_at") or ""),
    )[-REVIEW_QUEUE_ITEM_LIMIT:]
    attempts = dict(ordered)
    return {
        "version": 1,
        "updated_at": now,
        "latest_experiment_package_hash": experiment_hash,
        "attempts": attempts,
        "counts": {
            "total": len(attempts),
            "ready_for_review": sum(1 for item in attempts.values() if item.get("promotion_status") == "READY_FOR_REVIEW"),
            "backtest_pending": sum(1 for item in attempts.values() if item.get("promotion_status") == "BACKTEST_PENDING"),
            "recommended_only": sum(1 for item in attempts.values() if item.get("promotion_status") == "RECOMMENDED_ONLY"),
            "sync_failed": sum(1 for item in attempts.values() if item.get("review_queue_sync_status") == "FAILED"),
        },
        "simulation_only": True,
        "is_real_trade": False,
    }


def _review_decision_record(value: Any) -> list[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)][-REVIEW_DECISION_HISTORY_LIMIT:]


def _is_low_risk_auto_approval_candidate(item: Dict[str, Any]) -> bool:
    candidate_status = str(item.get("candidate_status") or item.get("promotion_status") or "").strip().upper()
    review_decision = str(item.get("review_decision") or "PENDING_REVIEW").strip().upper()
    evidence_package = item.get("evidence_package") if isinstance(item.get("evidence_package"), dict) else {}
    evidence_quality = str(
        item.get("evidence_quality")
        or item.get("sample_quality")
        or evidence_package.get("sample_quality")
        or ""
    ).strip().upper()
    validation = item.get("walk_forward_validation") if isinstance(item.get("walk_forward_validation"), dict) else {}
    benchmark = (
        item.get("benchmark_comparison")
        if isinstance(item.get("benchmark_comparison"), dict)
        else validation.get("benchmark_comparison")
        if isinstance(validation.get("benchmark_comparison"), dict)
        else {}
    )
    return (
        candidate_status == "READY_FOR_REVIEW"
        and review_decision in {"", "PENDING_REVIEW"}
        and str(item.get("risk_level") or "").strip().upper() == "LOW"
        and item.get("review_allowed") is True
        and evidence_quality not in {"LOW", "SUPPORTING_ONLY"}
        and bool(benchmark.get("available"))
        and item.get("simulation_only") is not False
        and not bool(item.get("is_real_trade"))
    )


def _empty_pre_buy_quality(symbol: str = "", reason: str = "not_evaluated") -> Dict[str, Any]:
    return {
        "score": 0,
        "grade": "WAIT",
        "action_policy": "HOLD",
        "components": {},
        "reasons": [reason],
        "evidence_refs": [],
        "symbol": symbol,
        "simulation_only": True,
        "is_real_trade": False,
        "status": "UNOBSERVED",
        "actionPolicy": "HOLD",
    }


def _kline_quality_from_decision(decision: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(decision, dict):
        return {}
    if isinstance(decision.get("kline_signal_quality"), dict):
        return decision["kline_signal_quality"]
    pre_buy_quality = (
        decision.get("pre_buy_quality")
        if isinstance(decision.get("pre_buy_quality"), dict)
        else decision.get("performanceQuality")
        if isinstance(decision.get("performanceQuality"), dict)
        else {}
    )
    if isinstance(pre_buy_quality.get("kline_signal_quality"), dict):
        return pre_buy_quality["kline_signal_quality"]
    components = pre_buy_quality.get("components") if isinstance(pre_buy_quality.get("components"), dict) else {}
    if isinstance(components.get("kline_signal_quality"), dict):
        return components["kline_signal_quality"]
    risk_constraints = decision.get("risk_constraints") if isinstance(decision.get("risk_constraints"), dict) else {}
    if isinstance(risk_constraints.get("kline_signal_quality"), dict):
        return risk_constraints["kline_signal_quality"]
    return {}


def _kline_buy_gate_context(decision: Dict[str, Any]) -> Dict[str, Any]:
    kline_quality = _kline_quality_from_decision(decision)
    action_policy = str(
        kline_quality.get("action_policy")
        or kline_quality.get("actionPolicy")
        or ""
    ).upper()
    risk = kline_quality.get("risk_invalidation") if isinstance(kline_quality.get("risk_invalidation"), dict) else {}
    risk_status = str(risk.get("status") or "").upper()
    reasons = []
    if isinstance(kline_quality.get("reasons"), list):
        reasons.extend(str(item) for item in kline_quality["reasons"] if item)
    if isinstance(risk.get("reasons"), list):
        reasons.extend(str(item) for item in risk["reasons"] if item)
    missing_quality = not bool(kline_quality)
    return {
        "blocked": missing_quality or action_policy == "HOLD" or risk_status == "INVALIDATE",
        "missing_quality": missing_quality,
        "action_policy": action_policy or "UNKNOWN",
        "risk_status": risk_status or "UNKNOWN",
        "reasons": reasons or (["kline_quality_missing"] if missing_quality else []),
        "kline_signal_quality": kline_quality,
        "simulation_only": True,
        "is_real_trade": False,
    }


def _strategy_stability_from_decision(decision: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(decision, dict):
        return {}
    if isinstance(decision.get("strategy_stability_quality"), dict):
        return decision["strategy_stability_quality"]
    pre_buy_quality = (
        decision.get("pre_buy_quality")
        if isinstance(decision.get("pre_buy_quality"), dict)
        else decision.get("performanceQuality")
        if isinstance(decision.get("performanceQuality"), dict)
        else {}
    )
    if isinstance(pre_buy_quality.get("strategy_stability_quality"), dict):
        return pre_buy_quality["strategy_stability_quality"]
    components = pre_buy_quality.get("components") if isinstance(pre_buy_quality.get("components"), dict) else {}
    if isinstance(components.get("strategy_stability_quality"), dict):
        return components["strategy_stability_quality"]
    risk_constraints = decision.get("risk_constraints") if isinstance(decision.get("risk_constraints"), dict) else {}
    if isinstance(risk_constraints.get("strategy_stability_quality"), dict):
        return risk_constraints["strategy_stability_quality"]
    return {}


def _strategy_stability_buy_gate_context(decision: Dict[str, Any]) -> Dict[str, Any]:
    stability_quality = _strategy_stability_from_decision(decision)
    action_policy = str(
        stability_quality.get("action_policy")
        or stability_quality.get("actionPolicy")
        or ""
    ).upper()
    meta_gate = stability_quality.get("meta_label_gate") if isinstance(stability_quality.get("meta_label_gate"), dict) else {}
    reasons = []
    if isinstance(stability_quality.get("reasons"), list):
        reasons.extend(str(item) for item in stability_quality["reasons"] if item)
    if isinstance(meta_gate.get("reasons"), list):
        reasons.extend(str(item) for item in meta_gate["reasons"] if item)
    return {
        "blocked": bool(stability_quality) and action_policy == "HOLD",
        "missing_quality": not bool(stability_quality),
        "action_policy": action_policy or "UNKNOWN",
        "meta_label_status": str(meta_gate.get("status") or "UNKNOWN").upper(),
        "reasons": reasons,
        "strategy_stability_quality": stability_quality,
        "simulation_only": True,
        "is_real_trade": False,
    }


def _quant_core_path_risk_buy_gate_context(decision: Dict[str, Any]) -> Dict[str, Any]:
    path_risk = decision.get("quantCorePathRisk") if isinstance(decision.get("quantCorePathRisk"), dict) else {}
    if not path_risk:
        module_evidence = decision.get("moduleEvidence") if isinstance(decision.get("moduleEvidence"), dict) else {}
        path_risk = _module_path_risk_summary(module_evidence)
    risk_policy = str(decision.get("quantCorePathRiskPolicy") or path_risk.get("riskPolicy") or "").upper()
    return {
        "blocked": bool(decision.get("quantCorePathRiskBuyBlocked")) or risk_policy == "AVOID_NEW_BUY",
        "risk_policy": risk_policy or "UNKNOWN",
        "path_risk": path_risk,
        "action_boundary": path_risk.get("actionBoundary") or "READ_ONLY_NO_PERMISSION_CHANGE",
        "simulation_only": True,
        "is_real_trade": False,
    }


def _performance_key(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    if not text:
        text = fallback
    return text[:120]


def _performance_bucket(current: Any, records: list[Dict[str, Any]]) -> Dict[str, Any]:
    prior = current if isinstance(current, dict) else {}
    decay = _clamp_float(prior.get("prior_decay"), PERFORMANCE_PRIOR_DECAY, 0.0, 1.0)
    prior_sample_count = _clamp_float(prior.get("sample_count"), 0.0, 0.0, 1_000_000.0) * decay
    prior_trade_count = _clamp_float(prior.get("trade_count"), 0.0, 0.0, 1_000_000.0) * decay
    prior_wins = _clamp_float(prior.get("wins"), 0.0, 0.0, 1_000_000.0) * decay
    prior_failures = _clamp_float(prior.get("failures"), 0.0, 0.0, 1_000_000.0) * decay
    prior_no_trade = _clamp_float(prior.get("no_trade_count"), 0.0, 0.0, 1_000_000.0) * decay
    prior_pnl_sum = _clamp_float(prior.get("pnl_rate_sum"), 0.0, -1_000_000.0, 1_000_000.0) * decay
    prior_gross_win = _clamp_float(prior.get("gross_win_rate"), 0.0, 0.0, 1_000_000.0) * decay
    prior_gross_loss = _clamp_float(prior.get("gross_loss_rate"), 0.0, 0.0, 1_000_000.0) * decay

    trade_records = [record for record in records if _record_has_order(record)]
    wins = [record for record in trade_records if _record_is_win(record)]
    failures = [record for record in trade_records if _record_is_failure(record)]
    no_trade_count = sum(1 for record in records if not _record_has_order(record))
    pnl_sum = sum(_record_pnl_rate(record) for record in trade_records)
    gross_win = sum(max(_record_pnl_rate(record), 0.0) for record in trade_records)
    gross_loss = sum(abs(min(_record_pnl_rate(record), 0.0)) for record in trade_records)

    sample_count = prior_sample_count + len(records)
    trade_count = prior_trade_count + len(trade_records)
    wins_count = prior_wins + len(wins)
    failures_count = prior_failures + len(failures)
    no_trade_total = prior_no_trade + no_trade_count
    pnl_rate_sum = prior_pnl_sum + pnl_sum
    gross_win_rate = prior_gross_win + gross_win
    gross_loss_rate = prior_gross_loss + gross_loss
    win_rate = wins_count / trade_count if trade_count else 0.0
    avg_pnl_rate = pnl_rate_sum / trade_count if trade_count else 0.0
    expectancy = avg_pnl_rate
    profit_factor = 999.0 if gross_loss_rate <= 0 and gross_win_rate > 0 else (gross_win_rate / gross_loss_rate if gross_loss_rate > 0 else 0.0)
    prior_drawdown = _clamp_float(prior.get("max_drawdown"), 0.0, -1.0, 0.0)
    current_drawdown = -max([_record_drawdown(record) for record in trade_records] or [0.0])
    max_drawdown = min(prior_drawdown, current_drawdown)
    confidence = min(1.0, (trade_count / 12) ** 0.5) if trade_count else 0.0
    if trade_count < TUNING_MIN_TRADE_COUNT:
        quality_status = "LOW_SAMPLE"
    elif expectancy < -0.005 or win_rate < 0.35 or max_drawdown <= -0.08:
        quality_status = "POOR"
    elif expectancy > 0.005 and win_rate >= 0.55 and max_drawdown > -0.08:
        quality_status = "HEALTHY"
    else:
        quality_status = "WATCH"

    return {
        "sample_count": round(sample_count, 4),
        "trade_count": round(trade_count, 4),
        "wins": round(wins_count, 4),
        "failures": round(failures_count, 4),
        "no_trade_count": round(no_trade_total, 4),
        "win_rate": round(win_rate, 6),
        "avg_pnl_rate": round(avg_pnl_rate, 6),
        "expectancy": round(expectancy, 6),
        "profit_factor": round(profit_factor, 6),
        "max_drawdown": round(max_drawdown, 6),
        "confidence": round(confidence, 4),
        "pnl_rate_sum": round(pnl_rate_sum, 6),
        "gross_win_rate": round(gross_win_rate, 6),
        "gross_loss_rate": round(gross_loss_rate, 6),
        "quality_status": quality_status,
        "prior_decay": decay,
        "updated_at": _now_iso(),
    }


class AutoPaperTradingStore:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._loop_started_at = ""
        self._loop_heartbeat_at = ""
        self._loop_last_error = ""
        self._last_storage_warning = ""

    def get_config(self) -> AutoPaperTradingConfig:
        state = self._load_state()
        state["llm_gate_status"] = _llm_gate(state)["status"]
        return AutoPaperTradingConfig(**state)

    def get_status(self) -> Dict[str, Any]:
        config = self.get_config()
        now = _now()
        now_iso = now.isoformat()
        next_tick_due_at: Optional[str] = None
        seconds_until_next_tick: Optional[int] = None
        last_tick_at = _parse_time(config.last_tick_at)
        if config.enabled:
            if last_tick_at:
                due_at = last_tick_at + timedelta(seconds=config.tick_interval_seconds)
                next_tick_due_at = due_at.isoformat()
                seconds_until_next_tick = max(0, int((due_at - now).total_seconds()))
            else:
                next_tick_due_at = now_iso
                seconds_until_next_tick = 0

        storage_warning = self._last_storage_warning or config.storage_warning
        loop_health = self._loop_health()
        return {
            "enabled": config.enabled,
            "automation_mode": config.automation_mode,
            "automation_modules": _automation_modules(config),
            "loop_running": self._task is not None and not self._task.done(),
            "loop_health": loop_health,
            "loop_last_error": self._loop_last_error,
            "loop_started_at": self._loop_started_at,
            "loop_heartbeat_at": self._loop_heartbeat_at,
            "heartbeat_at": now_iso,
            "current_time": now_iso,
            "last_tick_at": config.last_tick_at,
            "last_success_at": config.last_success_at,
            "last_error": config.last_error or storage_warning,
            "config_updated_at": config.updated_at,
            "tick_interval_seconds": config.tick_interval_seconds,
            "next_tick_due_at": next_tick_due_at,
            "seconds_until_next_tick": seconds_until_next_tick,
            "last_tick_result": config.last_tick_result,
            "last_module_evidence": config.last_module_evidence,
            "last_portfolio_snapshot": config.last_portfolio_snapshot,
            "last_research_review": config.last_research_review,
            "compressed_observation_history": config.compressed_observation_history,
            "review_queue_state": config.review_queue_state,
            "review_decisions": config.review_decisions,
            "review_decision_event_ledger": self.get_review_decision_event_ledger_status(),
            "experiment_validation_state": config.experiment_validation_state,
            "random_validation_state": config.random_validation_state,
            "decision_tree_state": config.decision_tree_state,
            "storage_warning": storage_warning,
        }

    def get_review_decision_event_ledger_status(self) -> Dict[str, Any]:
        events, warnings, total_count = self._read_review_decision_events(
            limit=1,
            include_total=True,
        )
        latest_event = events[-1] if events else {}
        return {
            "schema": "signalops_review_decision_event_ledger_v1",
            "event_count": total_count,
            "latest_event_hash": str(latest_event.get("event_hash") or ""),
            "latest_decision_id": str(latest_event.get("decision_id") or ""),
            "ledger_file": _review_decision_event_file().name,
            "handoff_shipper_status": self.get_review_decision_event_handoff_shipper_status(),
            "append_only": True,
            "warnings": warnings,
            "simulation_only": True,
            "is_real_trade": False,
        }

    def _latest_review_decision_event_handoff_manifest(self, handoff_dir: Path) -> Dict[str, Any]:
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
                manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(manifest, dict):
                continue
            if manifest.get("schema") != "signalops_review_decision_event_export_handoff_manifest_v1":
                continue
            return {
                "handoff_id": _safe_review_handoff_text(manifest.get("handoff_id"), 160),
                "bundle_checksum": _safe_review_handoff_text(manifest.get("bundle_checksum"), 160),
                "manifest_file": _safe_review_handoff_text(manifest_path.name, 240),
                "bundle_file": _safe_review_handoff_text(manifest.get("bundle_file"), 240),
                "handed_off_at": _safe_review_handoff_text(manifest.get("handed_off_at"), 80),
                "latest_event_hash": _safe_review_handoff_text(manifest.get("latest_event_hash"), 160),
                "event_count": _clamp_int(manifest.get("event_count"), 0, 0, REVIEW_DECISION_EVENT_EXPORT_LIMIT),
                "total_event_count": _clamp_int(manifest.get("total_event_count"), 0, 0, 1_000_000),
            }
        return {}

    def get_review_decision_event_handoff_shipper_status(self) -> Dict[str, Any]:
        handoff_dir = _review_decision_export_handoff_dir()
        base = {
            "schema": REVIEW_DECISION_EXPORT_HANDOFF_SHIPPER_STATUS_SCHEMA,
            "checked": False,
            "configured": False,
            "reported": False,
            "status": "NOT_CONFIGURED",
            "reason": "AUTO_PAPER_REVIEW_DECISION_EXPORT_HANDOFF_DIR is not configured.",
            "handoff_destination": "NOT_CONFIGURED",
            "handoff_dir": "",
            "sidecar_file": "",
            "source": "",
            "provider": "",
            "remote_destination": "",
            "object_key": "",
            "retention_policy_id": "",
            "retention_status": "",
            "custody_status": "",
            "kms_key_ref": "",
            "search_index": "",
            "search_index_ready": False,
            "last_handoff_id": "",
            "last_bundle_checksum": "",
            "last_latest_event_hash": "",
            "latest_handoff_id": "",
            "latest_bundle_checksum": "",
            "latest_manifest_file": "",
            "latest_event_hash": "",
            "matches_latest_handoff": False,
            "matches_latest_export": False,
            "deployment_reported": False,
            "message": "",
            "issues": [],
            "append_only": True,
            "simulation_only": True,
            "is_real_trade": False,
        }
        if handoff_dir is None:
            return base

        latest_manifest = self._latest_review_decision_event_handoff_manifest(handoff_dir)
        latest_handoff_id = _safe_review_handoff_text(latest_manifest.get("handoff_id"), 160)
        latest_bundle_checksum = _safe_review_handoff_text(latest_manifest.get("bundle_checksum"), 160)
        latest_manifest_file = _safe_review_handoff_text(latest_manifest.get("manifest_file"), 240)
        latest_event_hash = _safe_review_handoff_text(latest_manifest.get("latest_event_hash"), 160)
        configured_base = {
            **base,
            "checked": True,
            "configured": True,
            "status": "NOT_REPORTED",
            "reason": "",
            "handoff_destination": "LOCAL_DEPLOYMENT_HANDOFF_DIR",
            "handoff_dir": str(handoff_dir),
            "latest_handoff_id": latest_handoff_id,
            "latest_bundle_checksum": latest_bundle_checksum,
            "latest_manifest_file": latest_manifest_file,
            "latest_event_hash": latest_event_hash,
        }
        if not handoff_dir.exists():
            return {
                **configured_base,
                "status": "EMPTY",
                "reason": "No SignalOps review decision event handoff manifest has been written yet.",
            }

        sidecar_path = handoff_dir / REVIEW_DECISION_EXPORT_HANDOFF_SHIPPER_STATUS_FILE
        if not sidecar_path.exists():
            return {
                **configured_base,
                "sidecar_file": str(sidecar_path),
                "issues": [] if latest_handoff_id else ["no_handoff_manifest"],
            }

        try:
            if sidecar_path.stat().st_size > 65536:
                return {
                    **configured_base,
                    "reported": True,
                    "status": "INVALID",
                    "sidecar_file": str(sidecar_path),
                    "issues": ["sidecar_too_large"],
                }
            payload = json.loads(sidecar_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return {
                **configured_base,
                "reported": True,
                "status": "INVALID",
                "sidecar_file": str(sidecar_path),
                "issues": ["invalid_sidecar_json"],
            }
        if not isinstance(payload, dict) or payload.get("schema") != REVIEW_DECISION_EXPORT_HANDOFF_SHIPPER_STATUS_SCHEMA:
            return {
                **configured_base,
                "reported": True,
                "status": "INVALID",
                "sidecar_file": str(sidecar_path),
                "issues": ["unexpected_sidecar_schema"],
            }

        raw_status = _safe_review_handoff_text(payload.get("status"), 32).upper() or "UNKNOWN"
        status = raw_status if raw_status in REVIEW_DECISION_EXPORT_HANDOFF_ALLOWED_SHIPPER_STATUSES else "UNKNOWN"
        issues: list[str] = []
        if status != raw_status:
            issues.append(f"unexpected_status:{raw_status}")

        last_handoff_id = _safe_review_handoff_text(payload.get("last_handoff_id") or payload.get("lastHandoffId"), 160)
        last_bundle_checksum = _safe_review_handoff_text(payload.get("last_bundle_checksum") or payload.get("lastBundleChecksum"), 160)
        last_latest_event_hash = _safe_review_handoff_text(payload.get("last_latest_event_hash") or payload.get("lastLatestEventHash"), 160)
        matches_latest_handoff = False
        if latest_handoff_id and last_handoff_id == latest_handoff_id:
            matches_latest_handoff = not (
                last_bundle_checksum
                and latest_bundle_checksum
                and last_bundle_checksum != latest_bundle_checksum
            )
            if not matches_latest_handoff:
                issues.append("bundle_checksum_mismatch_with_latest_handoff")
        elif latest_handoff_id:
            issues.append("handoff_id_mismatch_with_latest_handoff")
        else:
            issues.append("no_handoff_manifest")

        matches_latest_export = matches_latest_handoff
        if last_latest_event_hash and latest_event_hash and last_latest_event_hash != latest_event_hash:
            matches_latest_export = False
            issues.append("latest_event_hash_mismatch")

        return {
            **configured_base,
            "reported": True,
            "status": status,
            "sidecar_file": str(sidecar_path),
            "source": _safe_review_handoff_text(payload.get("source"), 120) or "deployment_shipper",
            "provider": _safe_review_handoff_text(payload.get("provider"), 120),
            "remote_destination": _safe_review_handoff_text(payload.get("remote_destination") or payload.get("remoteDestination"), 240),
            "object_key": _safe_review_handoff_text(payload.get("object_key") or payload.get("objectKey"), 240),
            "retention_policy_id": _safe_review_handoff_text(payload.get("retention_policy_id") or payload.get("retentionPolicyId"), 120),
            "retention_status": _safe_review_handoff_text(payload.get("retention_status") or payload.get("retentionStatus"), 80),
            "custody_status": _safe_review_handoff_text(payload.get("custody_status") or payload.get("custodyStatus"), 80),
            "kms_key_ref": _safe_review_handoff_text(payload.get("kms_key_ref") or payload.get("kmsKeyRef"), 120),
            "search_index": _safe_review_handoff_text(payload.get("search_index") or payload.get("searchIndex"), 120),
            "search_index_ready": bool(payload.get("search_index_ready") or payload.get("searchIndexReady")),
            "last_handoff_id": last_handoff_id,
            "last_bundle_checksum": last_bundle_checksum,
            "last_latest_event_hash": last_latest_event_hash,
            "matches_latest_handoff": matches_latest_handoff,
            "matches_latest_export": matches_latest_export,
            "deployment_reported": True,
            "message": _safe_review_handoff_text(payload.get("message"), 240),
            "issues": issues[:10],
        }

    def export_review_decision_events(self, limit: int = 100) -> Dict[str, Any]:
        bounded_limit = _clamp_int(limit, 100, 1, REVIEW_DECISION_EVENT_EXPORT_LIMIT)
        events, warnings, total_count = self._read_review_decision_events(
            limit=bounded_limit,
            include_total=True,
        )
        latest_event = events[-1] if events else {}
        bundle_payload = {
            "schema": "signalops_review_decision_event_export_v1",
            "events": events,
            "total_event_count": total_count,
            "latest_event_hash": str(latest_event.get("event_hash") or ""),
        }
        bundle_checksum = f"sigops-reviewevents-{_stable_json_hash(bundle_payload, length=20)}"
        signing_payload = {
            **bundle_payload,
            "returned_event_count": len(events),
            "bundle_checksum": bundle_checksum,
            "ledger_file": _review_decision_event_file().name,
            "append_only": True,
            "simulation_only": True,
            "is_real_trade": False,
        }
        signature = self._sign_review_decision_event_export(signing_payload)
        return {
            **bundle_payload,
            "generated_at": _now_iso(),
            "returned_event_count": len(events),
            "bundle_checksum": bundle_checksum,
            "ledger_file": _review_decision_event_file().name,
            "append_only": True,
            "warnings": warnings,
            "export_signature_status": "SIGNED" if signature else "UNSIGNED",
            "export_signature": signature,
            "simulation_only": True,
            "is_real_trade": False,
        }

    def verify_review_decision_event_export(self, export_payload: Dict[str, Any]) -> Dict[str, Any]:
        payload = export_payload if isinstance(export_payload, dict) else {}
        warnings: list[str] = []
        if not isinstance(export_payload, dict):
            warnings.append("export_payload_not_object")
        events = payload.get("events") if isinstance(payload.get("events"), list) else []
        if not isinstance(payload.get("events"), list):
            warnings.append("events_not_array")
        latest_event = events[-1] if events and isinstance(events[-1], dict) else {}
        latest_event_hash = str(payload.get("latest_event_hash") or "")
        latest_event_hash_valid = latest_event_hash == str(latest_event.get("event_hash") or "")
        returned_event_count = payload.get("returned_event_count")
        returned_event_count_valid = returned_event_count == len(events)
        total_event_count = payload.get("total_event_count")
        total_event_count_valid = isinstance(total_event_count, int) and total_event_count >= len(events)
        bundle_payload = {
            "schema": payload.get("schema"),
            "events": events,
            "total_event_count": total_event_count,
            "latest_event_hash": latest_event_hash,
        }
        expected_bundle_checksum = f"sigops-reviewevents-{_stable_json_hash(bundle_payload, length=20)}"
        provided_bundle_checksum = str(payload.get("bundle_checksum") or "")
        checksum_valid = bool(provided_bundle_checksum) and provided_bundle_checksum == expected_bundle_checksum
        signing_payload = {
            **bundle_payload,
            "returned_event_count": returned_event_count,
            "bundle_checksum": provided_bundle_checksum,
            "ledger_file": payload.get("ledger_file"),
            "append_only": payload.get("append_only"),
            "simulation_only": payload.get("simulation_only"),
            "is_real_trade": payload.get("is_real_trade"),
        }
        signature = payload.get("export_signature") if isinstance(payload.get("export_signature"), dict) else {}
        signature_status = str(payload.get("export_signature_status") or ("SIGNED" if signature else "UNSIGNED")).upper()
        signing_key = _review_decision_export_signing_key()
        expected_signature = self._sign_review_decision_event_export(signing_payload) if signing_key else None
        signature_value = str(signature.get("signature") or "")
        expected_signature_value = str((expected_signature or {}).get("signature") or "")
        signature_valid = bool(signature_value and expected_signature_value) and hmac.compare_digest(
            signature_value,
            expected_signature_value,
        )
        signed_fields_valid = signature.get("signed_fields") == (expected_signature or {}).get("signed_fields")
        signing_key_ref = str(signature.get("signing_key_ref") or "")
        expected_signing_key_ref = _review_decision_export_signing_key_ref() if signing_key else ""
        signing_key_ref_valid = bool(signing_key_ref and expected_signing_key_ref) and signing_key_ref == expected_signing_key_ref
        payload_checksum_valid = (
            str(signature.get("payload_checksum") or "") == provided_bundle_checksum
            and provided_bundle_checksum == expected_bundle_checksum
        )
        signature_schema_valid = signature.get("schema") == "signalops_review_decision_event_export_signature_v1"
        signature_algorithm_valid = signature.get("algorithm") == "HMAC-SHA256"
        schema_valid = payload.get("schema") == "signalops_review_decision_event_export_v1"
        boundary_valid = payload.get("append_only") is True and payload.get("simulation_only") is True and payload.get("is_real_trade") is False
        signature_boundary_valid = signature.get("simulation_only") is True and signature.get("is_real_trade") is False
        if signature_status == "SIGNED" and not signature:
            warnings.append("signature_missing")
        if signature and not signing_key:
            warnings.append("signing_key_missing")
        if not latest_event_hash_valid:
            warnings.append("latest_event_hash_mismatch")
        if not returned_event_count_valid:
            warnings.append("returned_event_count_mismatch")
        if not checksum_valid:
            warnings.append("bundle_checksum_mismatch")

        valid = all([
            schema_valid,
            boundary_valid,
            latest_event_hash_valid,
            returned_event_count_valid,
            total_event_count_valid,
            checksum_valid,
            bool(signature),
            bool(signing_key),
            signature_schema_valid,
            signature_algorithm_valid,
            signature_valid,
            signed_fields_valid,
            signing_key_ref_valid,
            payload_checksum_valid,
            signature_boundary_valid,
        ])
        if valid:
            status = "VALID"
        elif signature and not signing_key:
            status = "KEY_MISSING"
        elif not signature:
            status = "UNSIGNED"
        else:
            status = "INVALID"
        return {
            "schema": "signalops_review_decision_event_export_verification_v1",
            "status": status,
            "valid": valid,
            "checked_at": _now_iso(),
            "signature_status": signature_status,
            "schema_valid": schema_valid,
            "checksum_valid": checksum_valid,
            "signature_valid": signature_valid,
            "payload_checksum_valid": payload_checksum_valid,
            "signed_fields_valid": signed_fields_valid,
            "signing_key_ref_valid": signing_key_ref_valid,
            "signature_schema_valid": signature_schema_valid,
            "signature_algorithm_valid": signature_algorithm_valid,
            "latest_event_hash_valid": latest_event_hash_valid,
            "returned_event_count_valid": returned_event_count_valid,
            "total_event_count_valid": total_event_count_valid,
            "boundary_valid": boundary_valid,
            "signature_boundary_valid": signature_boundary_valid,
            "provided_bundle_checksum": provided_bundle_checksum,
            "expected_bundle_checksum": expected_bundle_checksum,
            "signing_key_ref": signing_key_ref,
            "expected_signing_key_ref": expected_signing_key_ref,
            "event_count": len(events),
            "warnings": warnings,
            "append_only": True,
            "simulation_only": True,
            "is_real_trade": False,
        }

    def handoff_review_decision_event_export(self, limit: int = 100) -> Dict[str, Any]:
        handoff_dir = _review_decision_export_handoff_dir()
        bundle = self.export_review_decision_events(limit=limit)
        verification = self.verify_review_decision_event_export(bundle)
        base_payload = {
            "schema": "signalops_review_decision_event_export_handoff_v1",
            "created_at": _now_iso(),
            "bundle_checksum": bundle.get("bundle_checksum"),
            "export_signature_status": bundle.get("export_signature_status"),
            "verification": verification,
            "handoff_destination": "LOCAL_DEPLOYMENT_HANDOFF_DIR" if handoff_dir else "NOT_CONFIGURED",
            "handoff_requires_signature": True,
            "append_only": True,
            "simulation_only": True,
            "is_real_trade": False,
        }
        if handoff_dir is None:
            return {
                **base_payload,
                "status": "DISABLED",
                "reason": "AUTO_PAPER_REVIEW_DECISION_EXPORT_HANDOFF_DIR is not configured.",
                "handoff_id": "",
                "bundle_file": "",
                "manifest_file": "",
            }
        if not verification.get("valid"):
            return {
                **base_payload,
                "status": "BLOCKED",
                "reason": "Signed export verification must be VALID before handoff.",
                "handoff_id": "",
                "bundle_file": "",
                "manifest_file": "",
                "handoff_dir": str(handoff_dir),
            }

        handed_off_at = _now_iso()
        checksum = str(bundle.get("bundle_checksum") or "sigops-reviewevents-unknown")
        checksum_slug = re.sub(r"[^A-Za-z0-9_-]+", "-", checksum).strip("-") or "unknown"
        timestamp_slug = re.sub(r"[^0-9A-Za-z]+", "", handed_off_at)[:20] or "now"
        handoff_id = f"sigops-reviewevents-handoff-{timestamp_slug}-{checksum_slug[-24:]}"
        bundle_file = f"{handoff_id}.json"
        manifest_file = f"{handoff_id}.manifest.json"
        manifest = {
            "schema": "signalops_review_decision_event_export_handoff_manifest_v1",
            "handoff_id": handoff_id,
            "status": "HANDED_OFF",
            "handed_off_at": handed_off_at,
            "handoff_destination": "LOCAL_DEPLOYMENT_HANDOFF_DIR",
            "bundle_file": bundle_file,
            "manifest_file": manifest_file,
            "bundle_checksum": bundle.get("bundle_checksum"),
            "export_signature_status": bundle.get("export_signature_status"),
            "export_signature": bundle.get("export_signature"),
            "verification_status": verification.get("status"),
            "verification_schema": verification.get("schema"),
            "event_count": bundle.get("returned_event_count"),
            "total_event_count": bundle.get("total_event_count"),
            "latest_event_hash": bundle.get("latest_event_hash"),
            "retention_policy": {
                "policy_id": "signalops_review_event_deployment_handoff_v1",
                "custody": "deployment_owned_after_handoff",
                "requires_signed_export": True,
                "requires_valid_verification": True,
            },
            "append_only": True,
            "simulation_only": True,
            "is_real_trade": False,
        }
        try:
            handoff_dir.mkdir(parents=True, exist_ok=True)
            self._write_json_atomic(handoff_dir / bundle_file, bundle)
            self._write_json_atomic(handoff_dir / manifest_file, manifest)
        except Exception as exc:
            logger.warning("SignalOps review event export handoff failed: %s", exc)
            return {
                **base_payload,
                "status": "FAILED",
                "reason": f"handoff_write_failed: {exc}",
                "handoff_id": handoff_id,
                "bundle_file": bundle_file,
                "manifest_file": manifest_file,
                "handoff_dir": str(handoff_dir),
            }
        return {
            **base_payload,
            "status": "HANDED_OFF",
            "reason": "",
            "handoff_id": handoff_id,
            "handoff_dir": str(handoff_dir),
            "bundle_file": bundle_file,
            "manifest_file": manifest_file,
            "shipper_status": self.get_review_decision_event_handoff_shipper_status(),
            "manifest": manifest,
        }

    def _sign_review_decision_event_export(self, signing_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        signing_key = _review_decision_export_signing_key()
        if not signing_key:
            return None
        canonical_payload = json.dumps(signing_payload, ensure_ascii=False, sort_keys=True, default=str)
        digest = hmac.new(signing_key.encode("utf-8"), canonical_payload.encode("utf-8"), hashlib.sha256).hexdigest()
        return {
            "schema": "signalops_review_decision_event_export_signature_v1",
            "algorithm": "HMAC-SHA256",
            "signature": f"sigops-reviewevents-hmac-{digest}",
            "payload_checksum": signing_payload.get("bundle_checksum"),
            "signing_key_ref": _review_decision_export_signing_key_ref(),
            "signed_fields": [
                "schema",
                "events",
                "total_event_count",
                "latest_event_hash",
                "returned_event_count",
                "bundle_checksum",
                "ledger_file",
                "append_only",
                "simulation_only",
                "is_real_trade",
            ],
            "simulation_only": True,
            "is_real_trade": False,
        }

    def update_config(self, updates: Dict[str, Any]) -> AutoPaperTradingConfig:
        current = self._load_state()
        storage_warning = str(current.get("storage_warning") or "")
        if storage_warning:
            current["storage_warning"] = ""
            if current.get("last_error") == storage_warning:
                current["last_error"] = ""
        clean = {key: value for key, value in updates.items() if value is not None}
        clean.pop("max_position_ratio", None)
        symbol_was_provided = "symbol" in clean
        current.update(clean)
        _normalize_automation_state(current)
        current["symbol"] = ",".join(_parse_symbols(str(current.get("symbol") or "")))
        current["stock_name"] = str(current.get("stock_name") or "").strip()
        current["signal_ids"] = current.get("signal_ids") if isinstance(current.get("signal_ids"), dict) else {}
        if symbol_was_provided and not current["symbol"]:
            current["signal_ids"] = {}
        current["initial_buy_signals"] = _clean_symbol_text_map(current.get("initial_buy_signals"))
        current["final_sell_signals"] = _clean_symbol_text_map(current.get("final_sell_signals"))
        current["initial_buy_signal"] = str(current.get("initial_buy_signal") or "").strip()
        current["final_sell_signal"] = str(current.get("final_sell_signal") or "").strip()
        for key in [
            "last_market_fetch_by_symbol",
            "last_kline_fetch_by_symbol",
            "last_weekly_monthly_fetch_by_symbol",
            "last_order_by_symbol",
            "last_tick_result",
            "last_module_evidence",
            "last_portfolio_snapshot",
            "factor_adjustments",
            "performance_stats",
            "last_research_review",
            "review_queue_state",
            "experiment_validation_state",
            "random_validation_state",
            "decision_tree_state",
        ]:
            current[key] = current.get(key) if isinstance(current.get(key), dict) else {}
        current["cleaned_record_history"] = (
            current.get("cleaned_record_history")
            if isinstance(current.get("cleaned_record_history"), list)
            else []
        )
        current_observation_summary = _normalize_compressed_observation_history(current.get("compressed_observation_history"))
        current["compressed_observation_history"] = (
            _compress_observation_history(current_observation_summary, current["cleaned_record_history"])
            if not int(current_observation_summary.get("total_count") or 0)
            else current_observation_summary
        )
        current["cleaned_record_history"] = _capped_trade_record_history(current["cleaned_record_history"])
        current["review_queue_state"] = _normalize_review_queue_state(current.get("review_queue_state"))
        current["review_decisions"] = _review_decision_record(current.get("review_decisions"))
        current["experiment_validation_state"] = _normalize_experiment_validation_state(current.get("experiment_validation_state"))
        current["random_validation_state"] = _normalize_random_validation_state(current.get("random_validation_state"))
        current["decision_tree_state"] = normalize_decision_tree_state(current.get("decision_tree_state"))
        _sync_managed_symbol_pool(current)
        current["initial_cash"] = _clamp_float(current.get("initial_cash"), 100000.0, 1.0, 1_000_000_000.0)
        current["max_position_ratio"] = _clamp_float(current.get("max_position_ratio"), 0.5, 0.01, 1.0)
        current["min_order_value"] = _clamp_float(current.get("min_order_value"), 1000.0, 0.0, 1_000_000_000.0)
        current["commission_rate"] = _clamp_float(
            current.get("commission_rate"),
            DEFAULT_COMMISSION_RATE,
            0.0,
            0.1,
        )
        current["commission_min_fee"] = _clamp_float(
            current.get("commission_min_fee"),
            DEFAULT_COMMISSION_MIN_FEE,
            0.0,
            1_000_000.0,
        )
        current["commission_min_trade_value"] = _clamp_float(
            current.get("commission_min_trade_value"),
            DEFAULT_COMMISSION_MIN_TRADE_VALUE,
            0.0,
            1_000_000_000.0,
        )
        current["stamp_duty_rate"] = _clamp_float(
            current.get("stamp_duty_rate"),
            DEFAULT_STAMP_DUTY_RATE,
            0.0,
            0.01,
        )
        current["realtime_interval_seconds"] = _clamp_int(current.get("realtime_interval_seconds"), 30, 1, 3600)
        current["kline_interval_seconds"] = _clamp_int(current.get("kline_interval_seconds"), 300, 60, 86400)
        current["weekly_monthly_interval_seconds"] = _clamp_int(current.get("weekly_monthly_interval_seconds"), 86400, 3600, 604800)
        current["tick_interval_seconds"] = _clamp_int(current.get("tick_interval_seconds"), 60, 5, 3600)
        current["min_order_interval_seconds"] = _clamp_int(current.get("min_order_interval_seconds"), 900, 5, 86400)
        current["max_llm_calls_per_day"] = _clamp_int(current.get("max_llm_calls_per_day"), 6, 0, 200)
        current["min_llm_interval_minutes"] = _clamp_int(current.get("min_llm_interval_minutes"), 120, 1, 1440)
        current["buy_change_threshold_pct"] = _clamp_float(current.get("buy_change_threshold_pct"), 0.5, 0.1, 5.0)
        current["close_change_threshold_pct"] = _clamp_float(current.get("close_change_threshold_pct"), -2.0, -5.0, -0.2)
        current["watch_position_ratio"] = _clamp_float(current.get("watch_position_ratio"), 0.15, 0.0, 0.85)
        current["probe_position_ratio"] = _clamp_float(current.get("probe_position_ratio"), 0.35, 0.0, 0.85)
        current["positive_position_ratio"] = _clamp_float(current.get("positive_position_ratio"), 0.50, 0.0, 0.85)
        current["breakout_position_ratio"] = _clamp_float(current.get("breakout_position_ratio"), 0.65, 0.0, 0.85)
        current["defensive_position_ratio"] = _clamp_float(current.get("defensive_position_ratio"), 0.25, 0.0, 0.85)
        current["existing_position_ratio"] = _clamp_float(current.get("existing_position_ratio"), 0.45, 0.0, 0.85)
        current["strength_follow_position_ratio"] = _clamp_float(current.get("strength_follow_position_ratio"), 0.65, 0.0, 0.85)
        current["llm_gate_status"] = _llm_gate(current)["status"]
        current["updated_at"] = _now_iso()
        if not current["symbol"]:
            current["enabled"] = False
        self._save_state(current)
        return AutoPaperTradingConfig(**current)

    async def tick(self, force: bool = False) -> Dict[str, Any]:
        config = self.get_config()
        symbols = _parse_symbols(config.symbol)
        if len(symbols) <= 1:
            try:
                result = await self._tick_one(force=force)
            except Exception as exc:  # noqa: BLE001 - tick must return structured state to the UI.
                result = self._exception_result(config, exc)
            result = await self._append_daily_review_if_due(result, force=force)
            return self._remember_tick_result(result)

        if not config.enabled and not force:
            return self._result("SKIPPED", "自动模拟交易未启用。", config, warnings=[])
        if not symbols:
            return self._result("BLOCKED", "请先设置股票代码。", config, warnings=[])
        if not force and _elapsed_seconds(config.last_tick_at) < config.tick_interval_seconds:
            return self._result("SKIPPED", "未到下一次自动跟进时间。", config, warnings=[])

        state = self._load_state()
        state["last_tick_at"] = _now_iso()
        state["last_error"] = ""
        self._save_state(state)

        results: list[Dict[str, Any]] = []
        warnings: list[str] = []
        for index, symbol in enumerate(symbols):
            symbol_config = AutoPaperTradingConfig(**{
                **_model_dump(config),
                "symbol": symbol,
                "stock_name": _stock_name_for_symbol(config, symbol, index),
                "initial_cash": config.initial_cash / len(symbols),
            })
            try:
                result = await self._tick_one(
                    force=force,
                    symbol_override=symbol,
                    stock_name_override=symbol_config.stock_name,
                    initial_cash_override=symbol_config.initial_cash,
                    touch_tick=False,
                    skip_tick_gate=True,
                )
            except Exception as exc:  # noqa: BLE001 - keep the rest of the pool running.
                result = self._exception_result(symbol_config, exc)
            results.append(result)
            warnings.extend([f"{symbol}:{item}" for item in result.get("warnings", [])])

        state = self._load_state()
        config = AutoPaperTradingConfig(**state)
        primary = results[0] if results else {}
        error_results = [item for item in results if item.get("status") == "ERROR"]
        status = "COMPLETED"
        if error_results and len(error_results) == len(results):
            status = "ERROR"
        elif error_results:
            status = "PARTIAL"
        result = {
            "status": status,
            "message": f"自动模拟交易已完成 {len(results)} 只股票跟进。",
            "config": config,
            "market_snapshot": primary.get("market_snapshot", {}),
            "kline_snapshot": primary.get("kline_snapshot", {}),
            "decision": primary.get("decision", {}),
            "decision_card": primary.get("decision_card") or (primary.get("decision", {}) or {}).get("decision_card", {}),
            "decision_tree_branch": primary.get("decision_tree_branch") or (primary.get("decision", {}) or {}).get("decision_tree_branch", {}),
            "decision_tree_review": primary.get("decision_tree_review", {}),
            "order": primary.get("order"),
            "portfolio": primary.get("portfolio"),
            "llm_trace": primary.get("llm_trace"),
            "warnings": warnings,
            "results": results,
        }
        if error_results:
            result["message"] = f"auto_paper_pool_tick_{status.lower()}: {len(error_results)} of {len(results)} symbols failed."
        result = await self._append_daily_review_if_due(result, force=force)
        return self._remember_tick_result(result)

    async def command(self, symbol: str, command: str, reason: str = "") -> Dict[str, Any]:
        normalized = _parse_symbols(symbol)
        target = normalized[0] if normalized else ""
        action = str(command or "").upper()
        if action not in AUTO_PAPER_COMMANDS:
            config = self.get_config()
            return {
                "status": "BLOCKED",
                "message": "Unsupported auto paper command.",
                "symbol": target,
                "signal_id": None,
                "config": config,
                "order": None,
                "portfolio": None,
                "warnings": ["unsupported_command"],
            }
        if not target:
            config = self.get_config()
            return {
                "status": "BLOCKED",
                "message": "Symbol is required.",
                "symbol": "",
                "signal_id": None,
                "config": config,
                "order": None,
                "portfolio": None,
                "warnings": ["symbol_required"],
            }

        async with self._lock:
            state = self._load_state()
            config = AutoPaperTradingConfig(**state)
            signal_ids = state.get("signal_ids") if isinstance(state.get("signal_ids"), dict) else {}
            signal_id = signal_ids.get(target) or (state.get("signal_id") if config.symbol == target else None)
            warnings: list[str] = []
            order: Optional[Dict[str, Any]] = None
            portfolio: Optional[Dict[str, Any]] = None
            close_blocked = False
            symbols = _parse_symbols(str(state.get("symbol") or ""))
            if action == "FORCE_OPEN_BUY" and target not in symbols:
                state["last_error"] = "force_open_buy_symbol_not_in_auto_pool"
                state["updated_at"] = _now_iso()
                self._save_state(state)
                return {
                    "status": "BLOCKED",
                    "message": "Symbol is not in the auto paper stock pool.",
                    "symbol": target,
                    "signal_id": signal_id,
                    "config": AutoPaperTradingConfig(**state),
                    "order": None,
                    "portfolio": None,
                    "warnings": ["symbol_not_in_auto_pool"],
                }

            if action == "FORCE_OPEN_BUY":
                symbol_index = symbols.index(target) if target in symbols else 0
                command_config = AutoPaperTradingConfig(**{
                    **_model_dump(config),
                    "symbol": target,
                    "stock_name": _stock_name_for_symbol(config, target, symbol_index),
                    "initial_cash": config.initial_cash / len(symbols) if symbols else config.initial_cash,
                    "auto_fill": True,
                    "use_llm": False,
                })
                signal = await self._ensure_signal(command_config)
                signal_id = signal["signal_id"]
                state = self._load_state()
                portfolio, error = await signalops_store.create_paper_portfolio(signal_id, {
                    "initial_cash": command_config.initial_cash,
                    "risk_budget": {
                        "position_ratio_mode": "AI_DYNAMIC_AVAILABLE_CASH",
                        "auto_paper_trading": True,
                        "manual_command": "FORCE_OPEN_BUY",
                        "global_pool_cash": config.initial_cash,
                        "per_symbol_budget": command_config.initial_cash,
                    },
                    "created_by_agent": "auto_paper_trader",
                })
                if error or not portfolio:
                    warnings.append(f"portfolio_error:{error or 'portfolio_not_available'}")
                else:
                    synced = await signalops_store.sync_paper_portfolio_budget(signal_id, command_config.initial_cash, {
                        "position_ratio_mode": "AI_DYNAMIC_AVAILABLE_CASH",
                        "auto_paper_trading": True,
                        "manual_command": "FORCE_OPEN_BUY",
                        "global_pool_cash": config.initial_cash,
                        "per_symbol_budget": command_config.initial_cash,
                    }, preserve_available_cash=True)
                    if synced:
                        portfolio = synced
                    positions = await signalops_store.list_paper_positions(signal_id)
                    open_quantity = sum(
                        _board_lot_quantity(
                            abs(_clamp_float(item.get("quantity"), 0.0, -1_000_000_000.0, 1_000_000_000.0))
                        )
                        for item in positions
                        if item.get("symbol") == target
                    )
                    if open_quantity > 0:
                        warnings.append("position_already_open")
                    else:
                        market_snapshot = await self._fetch_market_snapshot(command_config, force=True)
                        quote = market_snapshot.get("quote") if isinstance(market_snapshot, dict) else {}
                        quote = quote if isinstance(quote, dict) else {}
                        price = _clamp_float(quote.get("price"), 0.0, 0.0, 1_000_000_000.0)
                        if market_snapshot.get("status") != "READY" or price <= 0:
                            warnings.append(market_snapshot.get("error") or "market_data_unavailable")
                        else:
                            marked = await signalops_store.mark_paper_portfolio_to_market(signal_id, price)
                            if marked:
                                portfolio = marked
                            available_cash = _clamp_float(portfolio.get("available_cash"), 0.0, 0.0, 1_000_000_000.0)
                            position_ratio, position_ratio_source = self._ai_position_ratio(portfolio, market_snapshot, None, command_config)
                            kline_snapshot = self._fetch_kline_snapshot(command_config, force=True)
                            module_evidence = self._build_module_evidence(command_config, portfolio, market_snapshot, kline_snapshot)
                            path_risk_summary = _module_path_risk_summary(module_evidence)
                            path_risk_policy = str(path_risk_summary.get("riskPolicy") or "").upper()
                            future_trend_probability = _module_future_trend_probability(module_evidence)
                            future_policy_hint = str(future_trend_probability.get("signalopsPolicyHint") or "").upper()
                            performance_quality = self._performance_quality_context(
                                command_config,
                                target,
                                position_ratio_source,
                                market_snapshot,
                                kline_snapshot,
                            )
                            position_ratio = _clamp_float(
                                position_ratio * _clamp_float(performance_quality.get("positionRatioMultiplier"), 1.0, 0.2, 1.3),
                                position_ratio,
                                0.0,
                                0.85,
                            )
                            path_risk_throttled = False
                            path_risk_buy_blocked = False
                            future_trend_review_required = False
                            if path_risk_policy == "THROTTLE":
                                throttled_ratio = min(position_ratio, 0.20)
                                path_risk_throttled = throttled_ratio < position_ratio
                                position_ratio = throttled_ratio
                            elif path_risk_policy == "AVOID_NEW_BUY":
                                path_risk_buy_blocked = True
                            if future_policy_hint == "SIMULATION_REDUCE_OR_REVIEW_ONLY":
                                reduced_ratio = min(position_ratio, 0.15)
                                future_trend_review_required = reduced_ratio < position_ratio
                                position_ratio = reduced_ratio
                            elif future_policy_hint == "REVIEW_SIMULATION_ONLY_INSUFFICIENT_CALIBRATION":
                                future_trend_review_required = True
                            ladder_policy = (
                                performance_quality.get("ladderBuyPolicy")
                                if isinstance(performance_quality.get("ladderBuyPolicy"), dict)
                                else {}
                            )
                            ladder_target_ratio = _clamp_float(ladder_policy.get("target_position_ratio"), 0.0, 0.0, 0.50)
                            if ladder_target_ratio > 0:
                                position_ratio = min(position_ratio, ladder_target_ratio)
                            target_value = min(available_cash, available_cash * position_ratio)
                            target_quantity = _board_lot_quantity(target_value / price)
                            quantity = min(target_quantity, _affordable_board_lot_quantity(available_cash, price, command_config))
                            if quantity <= 0 or quantity * price < command_config.min_order_value:
                                warnings.append("insufficient_simulated_cash")
                            else:
                                local_date = _now().astimezone(CHINA_TZ).date().isoformat()
                                decision = {
                                    "action": "SIM_BUY",
                                    "reason": reason or "User instructed Agent to force an open-position SIM_BUY today.",
                                    "price": price,
                                    "quantity": quantity,
                                    "source": "manual_ai_command",
                                    "command": "FORCE_OPEN_BUY",
                                    "commandDate": local_date,
                                    "positionRatio": position_ratio,
                                    "positionRatioSource": position_ratio_source,
                                    "performanceQuality": performance_quality,
                                    "pre_buy_quality": performance_quality,
                                    "kline_signal_quality": performance_quality.get("kline_signal_quality"),
                                    "klineStrategy": performance_quality.get("klineStrategy"),
                                    "ladderBuyPolicy": performance_quality.get("ladderBuyPolicy"),
                                    "moduleEvidence": module_evidence,
                                    "quantCorePathRisk": path_risk_summary,
                                    "quantCorePathRiskPolicy": path_risk_policy,
                                    "quantCorePathRiskThrottled": path_risk_throttled,
                                    "quantCorePathRiskAvoidsNewBuy": path_risk_policy == "AVOID_NEW_BUY",
                                    "quantCorePathRiskBuyBlocked": path_risk_buy_blocked,
                                    "futureTrendProbability": future_trend_probability,
                                    "futureTrendReviewRequired": future_trend_review_required,
                                    "availableCashBeforeOrder": available_cash,
                                    "targetCashValue": target_value,
                                    "simulation_only": True,
                                    "is_real_trade": False,
                                }
                                portfolio_before_order = portfolio
                                order = await self._maybe_create_order(command_config, signal_id, portfolio, decision, force=True)
                                if order and order.get("error"):
                                    warnings.append(f"order_error:{order['error']}")
                                elif order:
                                    conditions = self._ai_conditions(command_config, decision, market_snapshot, kline_snapshot)
                                    signal = await signalops_store.update_signal_conditions(signal_id, {
                                        **conditions,
                                        "review_fields": ["auto_paper_trading", "manual_open_buy_command", "market_data"],
                                    }) or signal
                                    lifecycle_warning = await self._advance_to_paper_test(signal)
                                    if lifecycle_warning:
                                        warnings.append(lifecycle_warning)
                                portfolio = await signalops_store.get_paper_portfolio(signal_id) or portfolio
                                decision_card = self._build_decision_card(
                                    config=command_config,
                                    decision=decision,
                                    portfolio_before=portfolio_before_order,
                                    portfolio_after=portfolio,
                                    order=order,
                                    warnings=warnings,
                                )
                                decision["decision_card"] = decision_card
                                if order is not None:
                                    risk_constraints = order.get("risk_constraints") if isinstance(order.get("risk_constraints"), dict) else {}
                                    order["risk_constraints"] = {**risk_constraints, "decision_card": decision_card}
                                    order["decision_card"] = decision_card
                                state = self._load_state()
                                state["last_decision"] = decision
                                state["last_module_evidence"] = module_evidence
                                if order and not order.get("error"):
                                    state["last_order_at"] = _now_iso()
                                    order_map = state.get("last_order_by_symbol") if isinstance(state.get("last_order_by_symbol"), dict) else {}
                                    order_map[target] = state["last_order_at"]
                                    state["last_order_by_symbol"] = order_map

            if not signal_id:
                warnings.append("signal_not_found")
            else:
                portfolio = await signalops_store.get_paper_portfolio(signal_id)

            if action in {"FORCE_CLOSE", "FORCE_CLOSE_AND_REMOVE"} and signal_id and portfolio:
                positions = await signalops_store.list_paper_positions(signal_id)
                signed_quantity = sum(_clamp_float(item.get("quantity"), 0.0, -1_000_000_000.0, 1_000_000_000.0) for item in positions if item.get("symbol") == target)
                quantity = _board_lot_quantity(abs(signed_quantity))
                price = self._close_price_from_positions(positions, target)
                if quantity > 0 and price > 0:
                    command_config = AutoPaperTradingConfig(**{
                        **_model_dump(config),
                        "symbol": target,
                        "stock_name": target,
                        "auto_fill": True,
                    })
                    decision = {
                        "action": "SIM_COVER" if signed_quantity < 0 else "SIM_CLOSE",
                        "reason": reason or "User forced AI paper close from SignalOps stock pool.",
                        "price": price,
                        "quantity": quantity,
                        "source": "manual_ai_command",
                        "positionRatio": 0.0,
                        "positionRatioSource": "forced_close_command",
                        "strategyIntent": "forced_cover_short" if signed_quantity < 0 else "forced_close_long",
                        "simulation_only": True,
                        "is_real_trade": False,
                    }
                    decision["decision_card"] = self._build_decision_card(
                        config=command_config,
                        decision=decision,
                        portfolio_before=portfolio,
                        portfolio_after=portfolio,
                        order=None,
                        warnings=warnings,
                    )
                    portfolio_before_order = portfolio
                    order = await self._maybe_create_order(command_config, signal_id, portfolio, decision, force=True)
                    portfolio = await signalops_store.get_paper_portfolio(signal_id) or portfolio
                    decision_card = self._build_decision_card(
                        config=command_config,
                        decision=decision,
                        portfolio_before=portfolio_before_order,
                        portfolio_after=portfolio,
                        order=order,
                        warnings=warnings,
                    )
                    decision["decision_card"] = decision_card
                    if order is not None:
                        risk_constraints = order.get("risk_constraints") if isinstance(order.get("risk_constraints"), dict) else {}
                        order["risk_constraints"] = {**risk_constraints, "decision_card": decision_card}
                        order["decision_card"] = decision_card
                    state["last_decision"] = decision
                    if order and order.get("error"):
                        warnings.append(f"order_error:{order['error']}")
                        close_blocked = True
                    elif order:
                        state["last_order_at"] = _now_iso()
                        order_map = state.get("last_order_by_symbol") if isinstance(state.get("last_order_by_symbol"), dict) else {}
                        order_map[target] = state["last_order_at"]
                        state["last_order_by_symbol"] = order_map
                else:
                    warnings.append("no_open_board_lot_position")

            if action == "REMOVE_SYMBOL" or (action == "FORCE_CLOSE_AND_REMOVE" and not close_blocked):
                state = self._remove_symbol_from_state(state, target)
                if signal_id:
                    _, error = await signalops_store.transition_signal(signal_id, {
                        "target_status": "CLOSED",
                        "actor": "auto_paper_trader",
                        "reason": reason or "Auto paper trading symbol removed after forced paper close.",
                        "gate_context": {"auto_paper_command": action, "simulation_only": True},
                    })
                    if error:
                        warnings.append(f"signal_close_failed:{error}")

            command_status = "COMPLETED"
            message = "Auto paper command completed."
            if action == "FORCE_OPEN_BUY" and (not order or bool(order.get("error"))):
                command_status = "BLOCKED"
                message = "Forced open buy was not placed."
                if not warnings:
                    warnings.append("order_not_created")
            if action in {"FORCE_CLOSE", "FORCE_CLOSE_AND_REMOVE"} and close_blocked:
                command_status = "BLOCKED"
                message = "Forced close was not placed."
            state["last_error"] = "" if command_status == "COMPLETED" else message
            state["updated_at"] = _now_iso()
            self._save_state(state)
            next_config = AutoPaperTradingConfig(**state)
            return {
                "status": command_status,
                "message": message,
                "symbol": target,
                "signal_id": signal_id,
                "config": next_config,
                "order": order,
                "portfolio": portfolio,
                "warnings": warnings,
            }

    async def record_experiment_validation_state(self, result: Dict[str, Any]) -> Dict[str, Any]:
        async with self._lock:
            state = self._load_state()
            state["experiment_validation_state"] = _upsert_experiment_validation_state(
                state.get("experiment_validation_state"),
                result,
                review_queue_sync_status=str(result.get("review_queue_sync_status") or "NOT_SYNCED"),
            )
            last_review = state.get("last_research_review") if isinstance(state.get("last_research_review"), dict) else {}
            if last_review:
                last_review["experiment_validation_state"] = state["experiment_validation_state"]
                state["last_research_review"] = last_review
            state["updated_at"] = _now_iso()
            self._save_state(state)
            return state["experiment_validation_state"]

    async def record_random_validation_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        now = _now_iso()
        job_id = str(result.get("jobId") or "").strip()
        if not job_id:
            return {}
        async with self._lock:
            state = self._load_state()
            random_state = _normalize_random_validation_state(state.get("random_validation_state"))
            adjustment = dict(result.get("appliedAdjustment") if isinstance(result.get("appliedAdjustment"), dict) else {})
            candidate_config = result.get("candidateConfig") if isinstance(result.get("candidateConfig"), dict) else {}
            baseline_config = result.get("baselineConfig") if isinstance(result.get("baselineConfig"), dict) else {}
            tunable_fields = {
                "buy_change_threshold_pct": (0.1, 5.0, 0.05),
                "close_change_threshold_pct": (-5.0, -0.2, 0.05),
                "watch_position_ratio": (0.0, 0.85, 0.02),
                "probe_position_ratio": (0.0, 0.85, 0.02),
                "positive_position_ratio": (0.0, 0.85, 0.02),
                "breakout_position_ratio": (0.0, 0.85, 0.02),
                "defensive_position_ratio": (0.0, 0.85, 0.02),
                "existing_position_ratio": (0.0, 0.85, 0.02),
                "strength_follow_position_ratio": (0.0, 0.85, 0.02),
            }
            applied_parameters: Dict[str, Any] = {}
            deltas: Dict[str, float] = {}
            should_apply = bool(adjustment.get("shouldApply"))
            if should_apply:
                for key, (low, high, max_delta) in tunable_fields.items():
                    if key not in candidate_config:
                        continue
                    current_value = _clamp_float(state.get(key), _clamp_float(baseline_config.get(key), 0.0, low, high), low, high)
                    requested_value = _clamp_float(candidate_config.get(key), current_value, low, high)
                    requested_delta = requested_value - current_value
                    safe_delta = max(-max_delta, min(max_delta, requested_delta))
                    next_value = _clamp_float(current_value + safe_delta, current_value, low, high)
                    if abs(next_value - current_value) < 0.000001:
                        continue
                    state[key] = next_value
                    applied_parameters[key] = next_value
                    deltas[key] = round(next_value - current_value, 6)
            adjustment = {
                **adjustment,
                "applied": bool(applied_parameters),
                "appliedParameters": applied_parameters,
                "deltas": deltas,
                "appliedAt": now if applied_parameters else "",
                "simulation_only": True,
                "is_real_trade": False,
            }
            summary = {
                "job_id": job_id,
                "status": result.get("status"),
                "mode": result.get("mode"),
                "seed": result.get("seed"),
                "evidence_level": result.get("evidenceLevel"),
                "sample_windows": result.get("sampleWindows") if isinstance(result.get("sampleWindows"), list) else [],
                "data_quality": result.get("dataQuality") if isinstance(result.get("dataQuality"), dict) else {},
                "baseline_results": result.get("baselineResults") if isinstance(result.get("baselineResults"), dict) else {},
                "candidate_results": result.get("candidateResults") if isinstance(result.get("candidateResults"), dict) else {},
                "applied_adjustment": adjustment,
                "rejection_reasons": result.get("rejectionReasons") if isinstance(result.get("rejectionReasons"), list) else [],
                "review_queue_sync_status": result.get("reviewQueueSyncStatus") or "SYNCED",
                "created_at": result.get("createdAt") or now,
                "updated_at": now,
                "simulation_only": True,
                "is_real_trade": False,
            }
            attempts = [*random_state.get("attempts", []), summary][-REVIEW_QUEUE_ITEM_LIMIT:]
            random_state = {
                "version": 1,
                "updated_at": now,
                "latest_job_id": job_id,
                "latest_summary": summary,
                "attempts": attempts,
                "counts": {
                    "total": len(attempts),
                    "applied": sum(1 for item in attempts if (item.get("applied_adjustment") or {}).get("applied")),
                    "strong": sum(1 for item in attempts if item.get("evidence_level") == "STRONG"),
                    "medium": sum(1 for item in attempts if item.get("evidence_level") == "MEDIUM"),
                    "weak": sum(1 for item in attempts if item.get("evidence_level") == "WEAK"),
                },
                "strategy_drift_summary": _random_validation_drift_summary(attempts),
                "simulation_only": True,
                "is_real_trade": False,
            }
            state["random_validation_state"] = random_state

            queue_state = _normalize_review_queue_state(state.get("review_queue_state"))
            observation = {
                "id": f"rq-signalops-random-{job_id[-24:]}",
                "queue_item_id": f"rq-signalops-random-{job_id[-24:]}",
                "experiment_id": f"signalops-random-validation-{job_id[-24:]}",
                "symbol": ",".join(str(item.get("symbol") or "") for item in summary["sample_windows"] if isinstance(item, dict)),
                "title": f"SignalOps random validation {job_id[-8:]}",
                "candidate_status": "APPLIED_TO_SIMULATION" if adjustment.get("applied") else "RECOMMENDED_ONLY",
                "promotion_status": "APPLIED_TO_SIMULATION" if adjustment.get("applied") else "RECOMMENDED_ONLY",
                "review_allowed": False,
                "review_decision": "CONTINUE_OBSERVING",
                "risk_level": "LOW" if adjustment.get("applied") else "MEDIUM",
                "evidence_quality": summary["evidence_level"],
                "reason": ",".join(summary["rejection_reasons"]) or ("random_validation_micro_adjusted" if adjustment.get("applied") else "random_validation_recorded"),
                "random_validation_summary": summary,
                "evidence_package": {
                    "source": "signalops_random_validation",
                    "job_id": job_id,
                    "sample_quality": summary["evidence_level"],
                    "simulation_only": True,
                    "is_real_trade": False,
                },
                "created_at": now,
                "updated_at": now,
                "simulation_only": True,
                "is_real_trade": False,
            }
            observations = [
                item for item in queue_state.get("observations", [])
                if str(item.get("queue_item_id") or item.get("id") or "") != observation["queue_item_id"]
            ]
            observations.append(observation)
            items = [item for item in queue_state.get("items", []) if isinstance(item, dict)]
            state["review_queue_state"] = {
                "version": 1,
                "updated_at": now,
                "items": items[-REVIEW_QUEUE_ITEM_LIMIT:],
                "observations": observations[-REVIEW_QUEUE_ITEM_LIMIT:],
                "counts": {
                    **(queue_state.get("counts") if isinstance(queue_state.get("counts"), dict) else {}),
                    "random_validation": len(observations),
                    "random_validation_applied": sum(
                        1
                        for item in observations
                        if isinstance(item.get("random_validation_summary"), dict)
                        and isinstance(item["random_validation_summary"].get("applied_adjustment"), dict)
                        and item["random_validation_summary"]["applied_adjustment"].get("applied")
                    ),
                },
                "simulation_only": True,
                "is_real_trade": False,
            }
            last_review = state.get("last_research_review") if isinstance(state.get("last_research_review"), dict) else {}
            last_review["random_validation_state"] = random_state
            last_review["review_queue_state"] = state["review_queue_state"]
            state["last_research_review"] = last_review
            state["updated_at"] = now
            self._save_state(state)
            return random_state

    async def _auto_approve_low_risk_candidates(self) -> list[Dict[str, Any]]:
        state = self._load_state()
        queue_state = _normalize_review_queue_state(state.get("review_queue_state"))
        candidates = [
            dict(item)
            for item in queue_state.get("items", [])
            if isinstance(item, dict) and _is_low_risk_auto_approval_candidate(item)
        ]
        decisions: list[Dict[str, Any]] = []
        for item in candidates:
            result = await self.record_review_decision({
                "queue_item_id": item.get("queue_item_id") or item.get("id") or "",
                "experiment_id": item.get("experiment_id") or "",
                "signal_id": item.get("signal_id") or None,
                "symbol": item.get("symbol") or "",
                "action": "APPROVE_SIMULATION_CANDIDATE",
                "reviewer": "auto_low_risk_reviewer",
                "reason": "low_risk_auto_approval",
                "evidence_refs": item.get("evidence_refs") if isinstance(item.get("evidence_refs"), list) else [],
                "review_fields": [
                    "review_queue_state",
                    "low_risk_auto_approval",
                    "strategy_experiment",
                    "simulation_only",
                    "is_real_trade",
                ],
            })
            decision = result.get("decision") if isinstance(result, dict) else {}
            if isinstance(decision, dict) and decision:
                decisions.append(decision)
        return decisions

    async def record_backtest_experiment_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        experiment_hash = str(result.get("experiment_package_hash") or "").strip()
        if not experiment_hash:
            return {}
        promotion_status = str(result.get("promotion_status") or "BACKTEST_PENDING").strip().upper()
        validation = result.get("walk_forward_validation") if isinstance(result.get("walk_forward_validation"), dict) else {}
        benchmark_comparison = result.get("benchmark_comparison") if isinstance(result.get("benchmark_comparison"), dict) else {}
        research_package = result.get("research_evidence_package") if isinstance(result.get("research_evidence_package"), dict) else {}
        walk_forward_run_ids = result.get("walk_forward_run_ids") if isinstance(result.get("walk_forward_run_ids"), dict) else {}
        stability_evidence_package = (
            result.get("stability_evidence_package")
            if isinstance(result.get("stability_evidence_package"), dict)
            else research_package.get("stability_evidence_package")
            if isinstance(research_package.get("stability_evidence_package"), dict)
            else {}
        )
        sample_quality = str(validation.get("sample_quality") or research_package.get("sample_quality") or "LOW").upper()
        benchmark_available = bool(benchmark_comparison.get("available"))
        review_allowed = (
            promotion_status == "READY_FOR_REVIEW"
            and sample_quality not in {"LOW", "SUPPORTING_ONLY"}
            and benchmark_available
        )
        next_queue_state: Dict[str, Any] = {}

        async with self._lock:
            state = self._load_state()
            state["experiment_validation_state"] = _upsert_experiment_validation_state(
                state.get("experiment_validation_state"),
                result,
                review_queue_sync_status=str(result.get("review_queue_sync_status") or "SYNCED"),
            )
            queue_state = _normalize_review_queue_state(state.get("review_queue_state"))
            updated_any = False

            def item_hash(item: Dict[str, Any]) -> str:
                evidence_package = item.get("evidence_package") if isinstance(item.get("evidence_package"), dict) else {}
                strategy = item.get("strategy_experiment") if isinstance(item.get("strategy_experiment"), dict) else {}
                return str(
                    item.get("experiment_package_hash")
                    or evidence_package.get("experiment_package_hash")
                    or strategy.get("experiment_package_hash")
                    or ""
                ).strip()

            def update_item(item: Dict[str, Any]) -> Dict[str, Any]:
                nonlocal updated_any
                if item_hash(item) != experiment_hash:
                    return item
                updated_any = True
                evidence_package = item.get("evidence_package") if isinstance(item.get("evidence_package"), dict) else {}
                strategy = item.get("strategy_experiment") if isinstance(item.get("strategy_experiment"), dict) else {}
                strategy = {
                    **strategy,
                    "experiment_package_hash": experiment_hash,
                    "promotion_status": promotion_status,
                    "walk_forward_run_ids": walk_forward_run_ids,
                    "benchmark_comparison": benchmark_comparison,
                    "evidence_package": {
                        **evidence_package,
                        "research_evidence_package": research_package,
                        "stability_evidence_package": stability_evidence_package or evidence_package.get("stability_evidence_package", {}),
                    },
                    "simulation_only": True,
                    "is_real_trade": False,
                }
                return {
                    **item,
                    "candidate_status": promotion_status,
                    "promotion_status": promotion_status,
                    "lifecycle_status": promotion_status,
                    "experiment_package_hash": experiment_hash,
                    "walk_forward_validation": validation,
                    "walk_forward_run_ids": walk_forward_run_ids,
                    "benchmark_comparison": benchmark_comparison,
                    "research_evidence_package": research_package,
                    "stability_evidence_package": stability_evidence_package or item.get("stability_evidence_package", {}),
                    "strategy_experiment": strategy,
                    "evidence_package": {
                        **evidence_package,
                        "experiment_package_hash": experiment_hash,
                        "sample_quality": sample_quality,
                        "walk_forward_run_ids": walk_forward_run_ids,
                        "benchmark_comparison": benchmark_comparison,
                        "research_evidence_package": research_package,
                        "stability_evidence_package": stability_evidence_package or evidence_package.get("stability_evidence_package", {}),
                    },
                    "evidence_quality": sample_quality,
                    "review_allowed": review_allowed,
                    "review_decision": "PENDING_REVIEW" if review_allowed else "CONTINUE_OBSERVING",
                    "reason": ",".join(validation.get("reasons") or []) or str(item.get("reason") or ""),
                    "updated_at": _now_iso(),
                    "simulation_only": True,
                    "is_real_trade": False,
                }

            combined = [
                update_item(dict(item))
                for item in [
                    *[item for item in queue_state.get("items", []) if isinstance(item, dict)],
                    *[item for item in queue_state.get("observations", []) if isinstance(item, dict)],
                ]
            ]
            if not updated_any:
                baseline_run = result.get("baseline_run") if isinstance(result.get("baseline_run"), dict) else {}
                candidate_run = result.get("candidate_run") if isinstance(result.get("candidate_run"), dict) else {}
                symbol = str(candidate_run.get("symbol") or baseline_run.get("symbol") or "POOL")
                queue_item_id = f"rq-signalops-exp-{experiment_hash[:24]}"
                standalone_status = promotion_status if promotion_status != "READY_FOR_REVIEW" else "BACKTEST_PENDING"
                combined.append({
                    "id": queue_item_id,
                    "queue_item_id": queue_item_id,
                    "experiment_id": f"signalops-exp-{experiment_hash[:24]}",
                    "experiment_package_hash": experiment_hash,
                    "symbol": symbol,
                    "title": f"SignalOps backtest experiment {experiment_hash[:8]}",
                    "candidate_status": standalone_status,
                    "promotion_status": standalone_status,
                    "lifecycle_status": standalone_status,
                    "review_allowed": False,
                    "review_decision": "CONTINUE_OBSERVING",
                    "risk_level": "MEDIUM",
                    "evidence_quality": sample_quality,
                    "reason": "signalops_candidate_queue_item_not_found",
                    "walk_forward_validation": validation,
                    "walk_forward_run_ids": walk_forward_run_ids,
                    "benchmark_comparison": benchmark_comparison,
                    "research_evidence_package": research_package,
                    "stability_evidence_package": stability_evidence_package,
                    "evidence_package": {
                        "experiment_package_hash": experiment_hash,
                        "sample_quality": sample_quality,
                        "walk_forward_run_ids": walk_forward_run_ids,
                        "benchmark_comparison": benchmark_comparison,
                        "research_evidence_package": research_package,
                        "stability_evidence_package": stability_evidence_package,
                    },
                    "created_at": _now_iso(),
                    "updated_at": _now_iso(),
                    "simulation_only": True,
                    "is_real_trade": False,
                })

            next_items = [
                item for item in combined
                if item.get("candidate_status") == "READY_FOR_REVIEW" and item.get("review_allowed")
            ][-REVIEW_QUEUE_ITEM_LIMIT:]
            next_observations = [
                item for item in combined
                if not (item.get("candidate_status") == "READY_FOR_REVIEW" and item.get("review_allowed"))
            ][-REVIEW_QUEUE_ITEM_LIMIT:]
            state["review_queue_state"] = {
                "version": 1,
                "updated_at": _now_iso(),
                "items": next_items,
                "observations": next_observations,
                "counts": {
                    "ready_for_review": sum(1 for item in next_items if item.get("candidate_status") == "READY_FOR_REVIEW"),
                    "backtest_pending": sum(1 for item in next_observations if item.get("candidate_status") == "BACKTEST_PENDING"),
                    "recommended_only": sum(1 for item in next_observations if item.get("candidate_status") == "RECOMMENDED_ONLY"),
                    "applied_to_simulation": sum(1 for item in combined if item.get("candidate_status") == "APPLIED_TO_SIMULATION"),
                    "rejected": sum(1 for item in combined if item.get("candidate_status") == "REJECTED"),
                    "superseded": sum(1 for item in combined if item.get("candidate_status") == "SUPERSEDED"),
                    "expired": sum(1 for item in combined if item.get("candidate_status") == "EXPIRED"),
                },
                "simulation_only": True,
                "is_real_trade": False,
            }
            last_review = state.get("last_research_review") if isinstance(state.get("last_research_review"), dict) else {}
            tuning = last_review.get("tuning_update") if isinstance(last_review.get("tuning_update"), dict) else {}
            experiment = tuning.get("strategy_experiment") if isinstance(tuning.get("strategy_experiment"), dict) else {}
            candidate_package = tuning.get("candidate_evidence_package") if isinstance(tuning.get("candidate_evidence_package"), dict) else {}
            tuning_hash = str(
                experiment.get("experiment_package_hash")
                or candidate_package.get("experiment_package_hash")
                or ""
            ).strip()
            if tuning_hash == experiment_hash:
                tuning["application_status"] = promotion_status
                tuning["application_reason"] = ",".join(validation.get("reasons") or []) or "signalops_backtest_experiment_recorded"
                tuning["walk_forward_validation"] = validation
                tuning["walk_forward_run_ids"] = walk_forward_run_ids
                tuning["benchmark_comparison"] = benchmark_comparison
                experiment["promotion_status"] = promotion_status
                experiment["walk_forward_run_ids"] = walk_forward_run_ids
                experiment["benchmark_comparison"] = benchmark_comparison
                tuning["strategy_experiment"] = experiment
                if isinstance(tuning.get("candidate_evidence_package"), dict):
                    tuning["candidate_evidence_package"] = {
                        **tuning["candidate_evidence_package"],
                        "walk_forward_run_ids": walk_forward_run_ids,
                        "benchmark_comparison": benchmark_comparison,
                        "research_evidence_package": research_package,
                        "stability_evidence_package": stability_evidence_package or tuning["candidate_evidence_package"].get("stability_evidence_package", {}),
                    }
                last_review["tuning_update"] = tuning
                last_review["review_queue_state"] = state["review_queue_state"]
                last_review["experiment_validation_state"] = state["experiment_validation_state"]
                state["last_research_review"] = last_review
            state["updated_at"] = _now_iso()
            self._save_state(state)
            next_queue_state = state["review_queue_state"]

        auto_approved = await self._auto_approve_low_risk_candidates()
        if auto_approved:
            state = self._load_state()
            return _normalize_review_queue_state(state.get("review_queue_state"))
        return next_queue_state

    async def record_review_decision(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        action = str(payload.get("action") or "").strip().upper()
        if action not in REVIEW_DECISION_ACTIONS:
            config = self.get_config()
            return {
                "status": "BLOCKED",
                "message": "Unsupported SignalOps review decision action.",
                "decision": {
                    "action": action,
                    "result_status": "BLOCKED",
                    "reason": "unsupported_review_decision_action",
                    "simulation_only": True,
                    "is_real_trade": False,
                },
                "queue_item": {},
                "config": config,
                "warnings": ["unsupported_review_decision_action"],
            }

        async with self._lock:
            state = self._load_state()
            queue_state = _normalize_review_queue_state(state.get("review_queue_state"))
            all_items = [
                *[dict(item) for item in queue_state.get("items", []) if isinstance(item, dict)],
                *[dict(item) for item in queue_state.get("observations", []) if isinstance(item, dict)],
            ]
            requested_queue_id = str(payload.get("queue_item_id") or "").strip()
            requested_experiment_id = str(payload.get("experiment_id") or "").strip()
            requested_signal_id = str(payload.get("signal_id") or "").strip()
            queue_item = None
            for item in all_items:
                if requested_queue_id and requested_queue_id in {
                    str(item.get("queue_item_id") or ""),
                    str(item.get("id") or ""),
                }:
                    queue_item = item
                    break
                if requested_experiment_id and requested_experiment_id == str(item.get("experiment_id") or ""):
                    queue_item = item
                    break
                if requested_signal_id and requested_signal_id == str(item.get("signal_id") or ""):
                    queue_item = item
                    break

            if queue_item is None:
                config = AutoPaperTradingConfig(**state)
                return {
                    "status": "BLOCKED",
                    "message": "SignalOps review queue item was not found.",
                    "decision": {
                        "action": action,
                        "result_status": "BLOCKED",
                        "reason": "review_queue_item_not_found",
                        "simulation_only": True,
                        "is_real_trade": False,
                    },
                    "queue_item": {},
                    "config": config,
                    "warnings": ["review_queue_item_not_found"],
                }

            now = _now_iso()
            reviewer = str(payload.get("reviewer") or "human").strip() or "human"
            reason = str(payload.get("reason") or "").strip()
            candidate_config = queue_item.get("candidate_config") if isinstance(queue_item.get("candidate_config"), dict) else {}
            baseline_config = queue_item.get("baseline_config") if isinstance(queue_item.get("baseline_config"), dict) else {}
            parameter_diff_summary, parameter_diff_checksum = _parameter_diff_snapshot_from_queue_item(
                queue_item,
                baseline_config,
                candidate_config,
            )
            reviewed_parameter_count = int(parameter_diff_summary.get("total_parameter_count") or 0)
            reviewed_parameter_changed_count = int(parameter_diff_summary.get("changed_count") or 0)
            candidate_status = str(queue_item.get("candidate_status") or queue_item.get("promotion_status") or "").strip().upper()
            queue_evidence_package = queue_item.get("evidence_package") if isinstance(queue_item.get("evidence_package"), dict) else {}
            evidence_quality = str(
                queue_item.get("evidence_quality")
                or queue_item.get("sample_quality")
                or queue_evidence_package.get("sample_quality")
                or ""
            ).strip().upper()
            queue_validation = queue_item.get("walk_forward_validation") if isinstance(queue_item.get("walk_forward_validation"), dict) else {}
            queue_benchmark = (
                queue_item.get("benchmark_comparison")
                if isinstance(queue_item.get("benchmark_comparison"), dict)
                else queue_validation.get("benchmark_comparison")
                if isinstance(queue_validation.get("benchmark_comparison"), dict)
                else {}
            )
            expires_at = _parse_time(str(queue_item.get("expires_at") or ""))
            if expires_at and expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            expired = bool(expires_at and expires_at < _now())
            original_queue_item = dict(queue_item)
            result_status = "CONTINUE_OBSERVING"
            warnings: list[str] = []
            applied_parameters: Dict[str, Any] = {}
            applied_factor_adjustments: Dict[str, Any] = (
                state.get("factor_adjustments") if isinstance(state.get("factor_adjustments"), dict) else {}
            )
            tunable_fields = {
                "buy_change_threshold_pct": (0.1, 5.0),
                "close_change_threshold_pct": (-5.0, -0.2),
                "watch_position_ratio": (0.0, 0.85),
                "probe_position_ratio": (0.0, 0.85),
                "positive_position_ratio": (0.0, 0.85),
                "breakout_position_ratio": (0.0, 0.85),
                "defensive_position_ratio": (0.0, 0.85),
                "existing_position_ratio": (0.0, 0.85),
                "strength_follow_position_ratio": (0.0, 0.85),
            }

            if action == "APPROVE_SIMULATION_CANDIDATE":
                if candidate_status in {"SUPERSEDED", "EXPIRED", "REJECTED", "APPLIED_TO_SIMULATION"}:
                    result_status = "BLOCKED"
                    warnings.append(f"candidate_{candidate_status.lower()}")
                elif expired:
                    result_status = "BLOCKED"
                    warnings.append("candidate_expired")
                elif evidence_quality in {"LOW", "SUPPORTING_ONLY"}:
                    result_status = "BLOCKED"
                    warnings.append("low_quality_evidence")
                elif not queue_benchmark.get("available"):
                    result_status = "BLOCKED"
                    warnings.append("benchmark_unavailable")
                elif candidate_status != "READY_FOR_REVIEW" or not queue_item.get("review_allowed"):
                    result_status = "BLOCKED"
                    warnings.append("candidate_not_ready_for_review")
                else:
                    for key, (low, high) in tunable_fields.items():
                        if key in candidate_config:
                            current_value = _clamp_float(state.get(key), 0.0, low, high)
                            safe_value = _clamp_float(candidate_config[key], current_value, low, high)
                            state[key] = safe_value
                            applied_parameters[key] = safe_value
                    if isinstance(candidate_config.get("factor_adjustments"), dict):
                        applied_factor_adjustments = dict(candidate_config["factor_adjustments"])
                        state["factor_adjustments"] = applied_factor_adjustments
                    result_status = "APPLIED_TO_SIMULATION"
                    queue_item["candidate_status"] = "APPLIED_TO_SIMULATION"
                    queue_item["promotion_status"] = "APPLIED_TO_SIMULATION"
                    queue_item["winner_config_id"] = "candidate"
                    queue_item["applied_at"] = now
            elif action == "REJECT_CANDIDATE":
                result_status = "REJECTED"
                queue_item["candidate_status"] = "REJECTED"
                queue_item["promotion_status"] = "REJECTED"
                queue_item["winner_config_id"] = "baseline"
            elif action == "REQUEST_PATCH":
                result_status = "PATCH_REQUESTED"
                queue_item["candidate_status"] = "REQUEST_PATCH"
                queue_item["promotion_status"] = "RECOMMENDED_ONLY"
                queue_item["patch_request"] = {
                    "source": "signalops_review_queue",
                    "experiment_id": queue_item.get("experiment_id"),
                    "baseline_config": baseline_config,
                    "candidate_config": candidate_config,
                    "reason": reason or queue_item.get("reason") or "review_requested_patch",
                    "simulation_only": True,
                    "is_real_trade": False,
                }
            else:
                result_status = "CONTINUE_OBSERVING"
                queue_item["candidate_status"] = candidate_status or "RECOMMENDED_ONLY"

            if result_status == "BLOCKED":
                queue_item = original_queue_item
            else:
                queue_item["review_decision"] = action
                queue_item["reviewer"] = reviewer
                queue_item["review_reason"] = reason
                queue_item["reviewed_at"] = now
                queue_item["reviewed_parameter_diff_checksum"] = parameter_diff_checksum
                queue_item["reviewed_parameter_diff_summary"] = parameter_diff_summary
                queue_item["updated_at"] = now
                queue_item["simulation_only"] = True
                queue_item["is_real_trade"] = False

            review_fields = (
                payload.get("review_fields")
                if isinstance(payload.get("review_fields"), list)
                else [
                    "review_queue_state",
                    "strategy_experiment",
                    "simulation_only",
                    "is_real_trade",
                ]
            )
            for field in ("parameter_diff_summary", "parameter_diff_checksum", "review_event_hash"):
                if field not in review_fields:
                    review_fields.append(field)

            decision_record = {
                "decision_id": f"review-{_stable_json_hash({'item': queue_item.get('queue_item_id'), 'action': action, 'reviewer': reviewer, 'time': now}, length=16)}",
                "queue_item_id": queue_item.get("queue_item_id") or queue_item.get("id"),
                "experiment_id": queue_item.get("experiment_id"),
                "signal_id": payload.get("signal_id") or queue_item.get("signal_id"),
                "symbol": payload.get("symbol") or queue_item.get("symbol"),
                "action": action,
                "result_status": result_status,
                "reviewer": reviewer,
                "reason": reason,
                "review_reason": reason,
                "supersedes": queue_item.get("supersedes") or queue_item.get("superseded_by") or "",
                "evidence_refs": payload.get("evidence_refs") if isinstance(payload.get("evidence_refs"), list) else queue_item.get("evidence_refs", []),
                "review_fields": review_fields,
                "applied_parameters": applied_parameters,
                "applied_factor_adjustments": applied_factor_adjustments if result_status == "APPLIED_TO_SIMULATION" else {},
                "parameter_diff_summary": parameter_diff_summary,
                "parameter_diff_checksum": parameter_diff_checksum,
                "reviewed_parameter_count": reviewed_parameter_count,
                "reviewed_parameter_changed_count": reviewed_parameter_changed_count,
                "review_decision_summary": {
                    "candidate_status_before": candidate_status,
                    "candidate_status_after": queue_item.get("candidate_status"),
                    "evidence_quality": evidence_quality,
                    "review_allowed": bool(queue_item.get("review_allowed")),
                    "expired": expired,
                    "parameter_diff_checksum": parameter_diff_checksum,
                    "parameter_diff_status": parameter_diff_summary.get("status"),
                    "reviewed_parameter_count": reviewed_parameter_count,
                    "reviewed_parameter_changed_count": reviewed_parameter_changed_count,
                    "simulation_only": True,
                    "is_real_trade": False,
                },
                "created_at": now,
                "simulation_only": True,
                "is_real_trade": False,
            }
            review_event = self._build_review_decision_event(
                decision_record=decision_record,
                queue_item=queue_item,
                now=now,
            )
            decision_record["review_event_hash"] = review_event["event_hash"]
            decision_record["review_event_previous_hash"] = review_event.get("previous_event_hash", "")
            decision_record["review_event_schema"] = review_event["schema"]
            decision_record["review_decision_summary"]["review_event_hash"] = review_event["event_hash"]
            if result_status != "BLOCKED":
                queue_item["review_event_hash"] = review_event["event_hash"]

            next_items: list[Dict[str, Any]] = []
            next_observations: list[Dict[str, Any]] = []
            item_key = str(queue_item.get("queue_item_id") or queue_item.get("id") or queue_item.get("experiment_id") or "")
            for item in queue_state.get("items", []):
                key = str(item.get("queue_item_id") or item.get("id") or item.get("experiment_id") or "")
                next_items.append(queue_item if key == item_key else item)
            for item in queue_state.get("observations", []):
                key = str(item.get("queue_item_id") or item.get("id") or item.get("experiment_id") or "")
                next_observations.append(queue_item if key == item_key else item)
            if not any(str(item.get("queue_item_id") or item.get("id") or item.get("experiment_id") or "") == item_key for item in next_items + next_observations):
                next_items.append(queue_item)

            state["review_queue_state"] = {
                "version": 1,
                "updated_at": now,
                "items": next_items[-REVIEW_QUEUE_ITEM_LIMIT:],
                "observations": next_observations[-REVIEW_QUEUE_ITEM_LIMIT:],
                "counts": {
                    "ready_for_review": sum(1 for item in next_items if item.get("candidate_status") == "READY_FOR_REVIEW"),
                    "applied_to_simulation": sum(1 for item in next_items + next_observations if item.get("candidate_status") == "APPLIED_TO_SIMULATION"),
                    "rejected": sum(1 for item in next_items + next_observations if item.get("candidate_status") == "REJECTED"),
                    "backtest_pending": sum(1 for item in next_observations if item.get("candidate_status") == "BACKTEST_PENDING"),
                    "recommended_only": sum(1 for item in next_observations if item.get("candidate_status") == "RECOMMENDED_ONLY"),
                    "superseded": sum(1 for item in next_items + next_observations if item.get("candidate_status") == "SUPERSEDED"),
                    "expired": sum(1 for item in next_items + next_observations if item.get("candidate_status") == "EXPIRED"),
                },
                "simulation_only": True,
                "is_real_trade": False,
            }
            review_decisions = _review_decision_record(state.get("review_decisions"))
            review_decisions.append(decision_record)
            state["review_decisions"] = review_decisions[-REVIEW_DECISION_HISTORY_LIMIT:]

            last_review = state.get("last_research_review") if isinstance(state.get("last_research_review"), dict) else {}
            tuning = last_review.get("tuning_update") if isinstance(last_review.get("tuning_update"), dict) else {}
            experiment = tuning.get("strategy_experiment") if isinstance(tuning.get("strategy_experiment"), dict) else {}
            if queue_item.get("experiment_id") and queue_item.get("experiment_id") == experiment.get("experiment_id"):
                if result_status == "APPLIED_TO_SIMULATION":
                    tuning["application_status"] = "APPLIED_TO_SIMULATION"
                    tuning["application_reason"] = "approved_simulation_candidate"
                    tuning["applied_parameters"] = applied_parameters
                    tuning["next_parameters"] = applied_parameters
                    tuning["applied_factor_adjustments"] = applied_factor_adjustments
                    tuning["factor_adjustments"] = applied_factor_adjustments
                    experiment["promotion_status"] = "APPLIED_TO_SIMULATION"
                    experiment["winner_config_id"] = "candidate"
                elif result_status == "REJECTED":
                    tuning["application_status"] = "REJECTED"
                    tuning["application_reason"] = "review_rejected_candidate"
                    experiment["promotion_status"] = "REJECTED"
                    experiment["winner_config_id"] = "baseline"
                tuning["strategy_experiment"] = experiment
                last_review["tuning_update"] = tuning
                last_review["review_queue_state"] = state["review_queue_state"]
                last_review["review_decisions"] = state["review_decisions"]
                state["last_research_review"] = last_review

            state["updated_at"] = now
            self._save_state(state)
            try:
                self._append_review_decision_event(review_event)
            except OSError as exc:
                warning = f"review_decision_event_append_failed: {exc}"
                warnings.append(warning)
                self._last_storage_warning = warning
            config = AutoPaperTradingConfig(**state)
            status = "COMPLETED" if result_status != "BLOCKED" else "BLOCKED"
            return {
                "status": status,
                "message": f"SignalOps review decision {result_status}.",
                "decision": decision_record,
                "queue_item": queue_item,
                "config": config,
                "warnings": warnings,
            }

    async def _append_daily_review_if_due(self, result: Dict[str, Any], *, force: bool = False) -> Dict[str, Any]:
        config = self.get_config()
        if not config.adaptive_tuning_enabled:
            return result
        state = self._load_state()
        gate = self._daily_review_gate(state)
        if not gate["allowed"]:
            return result
        review = await self.run_daily_research_review(
            force=force,
            trading_date=str(gate["date"]),
            reviewer="auto_research_reviewer",
        )
        result["daily_review"] = self._jsonable(review)
        return result

    def _daily_review_gate(self, state: Dict[str, Any]) -> Dict[str, Any]:
        local_now = _now().astimezone(CHINA_TZ)
        local_date = local_now.date().isoformat()
        is_trading_day = local_now.weekday() < 5 and local_date not in _closed_trading_dates()
        if not is_trading_day:
            return {"allowed": False, "status": "NON_TRADING_DAY", "date": local_date}
        if local_now.time() < AFTERNOON_SESSION_END:
            return {"allowed": False, "status": "BEFORE_CLOSE", "date": local_date}
        if state.get("last_research_review_date") == local_date:
            return {"allowed": False, "status": "ALREADY_REVIEWED", "date": local_date}
        return {"allowed": True, "status": "AFTER_CLOSE", "date": local_date}

    async def run_daily_research_review(
        self,
        *,
        force: bool = False,
        trading_date: Optional[str] = None,
        reviewer: str = "auto_research_reviewer",
    ) -> Dict[str, Any]:
        from ..models.research import (
            CreateResearchIterationRequest,
            ResearchEvidenceLink,
            ResearchIterationFeedbackRequest,
        )
        from .research_store import research_loop_store

        state = self._load_state()
        config = AutoPaperTradingConfig(**state)
        review_date = (trading_date or _now().astimezone(CHINA_TZ).date().isoformat()).strip()
        if not force and state.get("last_research_review_date") == review_date:
            last_review = state.get("last_research_review") if isinstance(state.get("last_research_review"), dict) else {}
            return {
                "status": "SKIPPED",
                "message": f"SignalOps daily review already ran for {review_date}.",
                "trading_date": review_date,
                "loop_id": last_review.get("loop_id"),
                "iteration_id": last_review.get("iteration_id"),
                "reviewed_symbols": last_review.get("reviewed_symbols", []),
                "case_ids": last_review.get("case_ids", []),
                "evidence_links": last_review.get("evidence_links", []),
                "review_fields": last_review.get("review_fields", []),
                "tuning_update": last_review.get("tuning_update", {}),
                "cleaned_records": last_review.get("cleaned_records", []),
                "review_queue_state": last_review.get("review_queue_state", config.review_queue_state),
                "review_decisions": last_review.get("review_decisions", config.review_decisions),
                "experiment_validation_state": last_review.get("experiment_validation_state", config.experiment_validation_state),
                "decision_tree_reviews": last_review.get("decision_tree_reviews", []),
                "warnings": ["daily_review_already_completed"],
                "config": config,
            }

        symbols = _parse_symbols(config.symbol)
        if not symbols:
            return {
                "status": "SKIPPED",
                "message": "No auto-paper symbols are configured for SignalOps daily review.",
                "trading_date": review_date,
                "loop_id": None,
                "iteration_id": None,
                "reviewed_symbols": [],
                "case_ids": [],
                "evidence_links": [],
                "review_fields": [],
                "tuning_update": {},
                "cleaned_records": [],
                "review_queue_state": config.review_queue_state,
                "review_decisions": config.review_decisions,
                "experiment_validation_state": config.experiment_validation_state,
                "warnings": ["no_symbols_configured"],
                "config": config,
            }

        signal_ids = state.get("signal_ids") if isinstance(state.get("signal_ids"), dict) else {}
        cleaned_records: list[Dict[str, Any]] = []
        reviewed_symbols: list[Dict[str, Any]] = []
        case_ids: list[str] = []
        evidence_links: list[ResearchEvidenceLink] = []
        warnings: list[str] = []

        for symbol in symbols:
            signal_id = signal_ids.get(symbol) or (state.get("signal_id") if config.symbol == symbol else None)
            if not signal_id:
                warnings.append(f"{symbol}:signal_not_materialized")
                continue
            detail = await signalops_store.get_signal_detail(str(signal_id))
            if not detail:
                warnings.append(f"{symbol}:signal_not_found")
                continue
            signal = detail["signal"]
            portfolio = await signalops_store.get_paper_portfolio(str(signal_id))
            positions = await signalops_store.list_paper_positions(str(signal_id))
            orders = await signalops_store.list_paper_orders(str(signal_id))
            day_orders = [
                order for order in orders
                if self._local_date_from_iso(str(order.get("created_at") or "")) == review_date
            ]
            if not day_orders and force and orders:
                day_orders = [orders[0]]
            cleaned = self._clean_daily_signal_record(
                trading_date=review_date,
                symbol=symbol,
                signal=signal,
                portfolio=portfolio or {},
                positions=positions,
                orders=orders,
                day_orders=day_orders,
                config=config,
            )
            cleaned_records.append(cleaned)
            reviewed_symbols.append({
                "symbol": symbol,
                "signal_id": signal_id,
                "order_count": cleaned["order_count"],
                "pnl_rate": cleaned["pnl_rate"],
                "invalidation_triggered": cleaned["invalidation_triggered"],
            })

            await signalops_store.create_review(str(signal_id), {
                "reviewer": reviewer,
                "review_type": "AUTO_DAILY",
                "decision": "PATCH_REQUIRED" if cleaned["invalidation_triggered"] else "REVIEWED",
                "note": (
                    f"Daily SignalOps paper review for {review_date}: "
                    f"orders={cleaned['order_count']}, pnl_rate={cleaned['pnl_rate']:.4f}, "
                    f"factor_sources={','.join(cleaned['factor_sources']) or 'none'}."
                ),
                "review_fields": [
                    "auto_paper_daily_review",
                    "cleaned_trade_record",
                    "research_lab_feedback",
                    "adaptive_tuning",
                ],
            })

            latest_order = day_orders[0] if day_orders else None
            if latest_order and latest_order.get("order_id"):
                case, error = await signalops_store.create_agent_simulation_case(str(signal_id), {
                    "source_paper_order_id": latest_order["order_id"],
                    "outcome": cleaned,
                    "failure_tags": cleaned["failure_tags"],
                    "knowledge_candidate_status": "REVIEWING",
                })
                if error:
                    warnings.append(f"{symbol}:case_error:{error}")
                elif case and case.get("case_id"):
                    case_ids.append(str(case["case_id"]))
                    evidence_links.append(ResearchEvidenceLink(
                        source_type="SIM_CASE",
                        source_id=str(case["case_id"]),
                        label=f"SignalOps paper case {symbol}",
                        quality="MEDIUM" if cleaned["order_count"] else "LOW",
                        created_at=str(case.get("created_at") or _now_iso()),
                    ))
            if signal_id:
                evidence_links.append(ResearchEvidenceLink(
                    source_type="SIGNALOPS",
                    source_id=str(signal_id),
                    label=f"SignalOps lifecycle {symbol}",
                    quality="MEDIUM",
                    created_at=str(signal.get("updated_at") or _now_iso()),
                ))

        if not cleaned_records:
            return {
                "status": "SKIPPED",
                "message": f"No SignalOps paper records were available for {review_date}.",
                "trading_date": review_date,
                "loop_id": None,
                "iteration_id": None,
                "reviewed_symbols": reviewed_symbols,
                "case_ids": case_ids,
                "evidence_links": [item.model_dump() for item in evidence_links],
                "review_fields": [],
                "tuning_update": {},
                "cleaned_records": [],
                "review_queue_state": config.review_queue_state,
                "review_decisions": config.review_decisions,
                "experiment_validation_state": config.experiment_validation_state,
                "warnings": warnings or ["no_cleaned_records"],
                "config": config,
            }

        loop_detail = await self._ensure_daily_research_loop(reviewer)
        previous_history = (
            state.get("cleaned_record_history")
            if isinstance(state.get("cleaned_record_history"), list)
            else []
        )
        compressed_observation_history = _compress_observation_history(
            state.get("compressed_observation_history"),
            cleaned_records,
        )
        cleaned_record_history = _capped_trade_record_history([*previous_history, *cleaned_records])
        evidence_payload = [item.model_dump() for item in evidence_links]
        tuning_update = self._build_daily_tuning_update(
            config,
            cleaned_records,
            cleaned_record_history=cleaned_record_history,
            compressed_observation_history=compressed_observation_history,
            evidence_links=evidence_payload,
            review_date=review_date,
        )
        queue_item = self._review_queue_item_from_tuning(
            tuning_update=tuning_update,
            review_date=review_date,
            reviewed_symbols=reviewed_symbols,
            evidence_links=evidence_payload,
        )
        next_review_queue_state = self._merge_review_queue_state(
            state.get("review_queue_state"),
            queue_item=queue_item,
        )
        iteration = await research_loop_store.create_iteration(
            loop_detail.loop.loop_id,
            CreateResearchIterationRequest(
                hypothesis=(
                    f"SignalOps paper outcomes on {review_date} should adjust AI buy trigger, "
                    "invalidation, and position sizing parameters for the next trading day."
                ),
                plan=(
                    "Clean paper orders and portfolio state, persist cases/evidence, "
                    "then feed conservative parameter deltas back into auto-paper decisions."
                ),
                target_modules=["signalops", "factor_engine", "qiam", "data_pipeline", "case_library"],
                metrics={
                    "trading_date": review_date,
                    "source": "signalops_daily_auto_review",
                    "cleaned_record_count": len(cleaned_records),
                    "candidate_status": tuning_update.get("application_status"),
                    "candidate_evidence_package": tuning_update.get("candidate_evidence_package"),
                    "review_queue_item_id": queue_item.get("queue_item_id") if queue_item else None,
                },
            ),
        )
        if iteration is None:
            raise RuntimeError("SignalOps daily Research Lab loop was not available")

        feedback = await research_loop_store.record_feedback(
            iteration.iteration_id,
            ResearchIterationFeedbackRequest(
                action="SIGNALOPS_DAILY_AUTO_REVIEW",
                verdict="PATCH_REQUIRED" if tuning_update.get("risk_tightened") else "PENDING",
                status="DAILY_REVIEWED",
                note=(
                    f"SignalOps daily paper review cleaned {len(cleaned_records)} symbol records "
                    f"and prepared next-day parameter deltas for {review_date}."
                ),
                reviewer=reviewer,
                linked_case_id=case_ids[0] if case_ids else None,
                metrics={
                    "trading_date": review_date,
                    "reviewed_symbols": reviewed_symbols,
                    "cleaned_records": cleaned_records,
                    "case_ids": case_ids,
                    "tuning_update": tuning_update,
                    "candidate_evidence_package": tuning_update.get("candidate_evidence_package"),
                    "review_queue_state": next_review_queue_state,
                    "simulation_only": True,
                    "is_real_trade": False,
                },
                evidence_links=evidence_links,
            ),
        )
        iteration_id = feedback.iteration_id if feedback else iteration.iteration_id

        state = self._load_state()
        next_params = tuning_update.get("applied_parameters") if isinstance(tuning_update.get("applied_parameters"), dict) else {}
        for key, value in next_params.items():
            state[key] = value
        if isinstance(tuning_update.get("performance_stats"), dict):
            state["performance_stats"] = tuning_update["performance_stats"]
        state["cleaned_record_history"] = cleaned_record_history
        state["compressed_observation_history"] = compressed_observation_history
        state["review_queue_state"] = next_review_queue_state
        if (
            tuning_update.get("application_status") == "APPLIED_TO_SIMULATION"
            and isinstance(tuning_update.get("applied_factor_adjustments"), dict)
        ):
            state["factor_adjustments"] = tuning_update["applied_factor_adjustments"]
        review_fields = [
            "cleaned_records",
            "cleaned_record_history",
            "tuning_update",
            "strategy_experiment",
            "candidate_factor_adjustments",
            "applied_factor_adjustments",
            "walk_forward_validation",
            "candidate_evidence_package",
            "review_queue_state",
            "evidence_links",
            "simulation_only",
            "is_real_trade",
        ]
        summary = {
            "status": "COMPLETED",
            "message": f"SignalOps daily review completed for {review_date}.",
            "trading_date": review_date,
            "loop_id": loop_detail.loop.loop_id,
            "iteration_id": iteration_id,
            "reviewed_symbols": reviewed_symbols,
            "case_ids": case_ids,
            "evidence_links": evidence_payload,
            "review_fields": review_fields,
            "tuning_update": tuning_update,
            "cleaned_records": cleaned_records,
            "compressed_observation_history": compressed_observation_history,
            "review_queue_state": next_review_queue_state,
            "review_decisions": _review_decision_record(state.get("review_decisions")),
            "experiment_validation_state": _normalize_experiment_validation_state(state.get("experiment_validation_state")),
            "decision_tree_reviews": (
                state.get("last_research_review", {}).get("decision_tree_reviews", [])
                if isinstance(state.get("last_research_review"), dict)
                else []
            ),
            "warnings": warnings,
            "updated_at": _now_iso(),
        }
        state["last_research_review_date"] = review_date
        state["last_research_review"] = summary
        state["updated_at"] = _now_iso()
        self._save_state(state)
        auto_approved = await self._auto_approve_low_risk_candidates()
        if auto_approved:
            state = self._load_state()
            latest_summary = state.get("last_research_review") if isinstance(state.get("last_research_review"), dict) else {}
            if latest_summary:
                latest_warnings = latest_summary.get("warnings") if isinstance(latest_summary.get("warnings"), list) else warnings
                summary = {
                    **summary,
                    **latest_summary,
                    "warnings": [*[item for item in latest_warnings if isinstance(item, str)], "low_risk_auto_approved"],
                }
        next_config = AutoPaperTradingConfig(**state)
        return {**summary, "config": next_config}

    async def _ensure_daily_research_loop(self, reviewer: str):
        from ..models.research import CreateResearchLoopRequest, LinkedProjectRef
        from .research_store import research_loop_store

        loops = await research_loop_store.list_loops()
        for loop in loops:
            tags = {str(tag).lower() for tag in loop.tags}
            if "signalops-auto-review" in tags and loop.status != "ARCHIVED":
                detail = await research_loop_store.get_loop_detail(loop.loop_id)
                if detail:
                    return detail
        return await research_loop_store.create_loop(
            CreateResearchLoopRequest(
                title="SignalOps daily paper-trading research loop",
                objective=(
                    "Connect AI paper-trading outcomes with Research Lab so cleaned cases "
                    "can tune buy triggers, invalidation rules, and position sizing."
                ),
                hypothesis="",
                plan="Daily after-close review creates evidence, cases, and conservative next-day parameter deltas.",
                action_target="factor",
                owner=reviewer,
                tags=["signalops", "auto-paper", "signalops-auto-review", "closed-loop"],
                target_modules=["signalops", "factor_engine", "qiam", "data_pipeline", "case_library"],
                linked_projects=[
                    LinkedProjectRef(
                        project="super",
                        module="signalops_auto_paper",
                        path="backend/app/core/auto_paper_trading.py",
                        expected_version="current",
                        sync_status="LINKED",
                        note="Daily SignalOps paper-trading review and adaptive tuning source.",
                    )
                ],
            )
        )

    def _clean_daily_signal_record(
        self,
        *,
        trading_date: str,
        symbol: str,
        signal: Dict[str, Any],
        portfolio: Dict[str, Any],
        positions: list[Dict[str, Any]],
        orders: list[Dict[str, Any]],
        day_orders: list[Dict[str, Any]],
        config: AutoPaperTradingConfig,
    ) -> Dict[str, Any]:
        latest_order = day_orders[0] if day_orders else None
        action_counts: Dict[str, int] = {}
        filled_value = 0.0
        total_fees = 0.0
        factor_sources: list[str] = []
        for order in day_orders:
            action = str(order.get("action") or "UNKNOWN").upper()
            action_counts[action] = action_counts.get(action, 0) + 1
            fill = order.get("simulated_fill") if isinstance(order.get("simulated_fill"), dict) else {}
            price = _clamp_float(fill.get("filled_price") or order.get("simulated_price"), 0.0, 0.0, 1_000_000_000.0)
            qty = _clamp_float(fill.get("filled_quantity") or order.get("simulated_quantity"), 0.0, 0.0, 1_000_000_000.0)
            if str(order.get("fill_status") or "").upper() == "FILLED":
                filled_value += price * qty
                total_fees += _clamp_float(fill.get("fees"), 0.0, 0.0, 1_000_000_000.0)
            risk = order.get("risk_constraints") if isinstance(order.get("risk_constraints"), dict) else {}
            source = str(risk.get("position_ratio_source") or "").strip()
            if source and source not in factor_sources:
                factor_sources.append(source)

        portfolio_risk = portfolio.get("risk_budget") if isinstance(portfolio.get("risk_budget"), dict) else {}
        portfolio_source = str(portfolio_risk.get("position_ratio_source") or "").strip()
        if portfolio_source and portfolio_source not in factor_sources:
            factor_sources.append(portfolio_source)

        available_cash = _clamp_float(portfolio.get("available_cash"), 0.0, 0.0, 1_000_000_000.0)
        market_value = _clamp_float(portfolio.get("market_value"), 0.0, -1_000_000_000.0, 1_000_000_000.0)
        initial_cash = _clamp_float(portfolio.get("initial_cash"), config.initial_cash, 1.0, 1_000_000_000.0)
        position_pnl = sum(_clamp_float(item.get("floating_pnl"), 0.0, -1_000_000_000.0, 1_000_000_000.0) for item in positions)
        total_assets = available_cash + market_value
        portfolio_pnl = total_assets - initial_cash
        pnl = position_pnl if positions else portfolio_pnl
        pnl_rate = pnl / initial_cash if initial_cash > 0 else 0.0
        max_drawdown = min(
            [_clamp_float(item.get("max_drawdown"), 0.0, -1.0, 0.0) for item in positions] or [0.0]
        )
        latest_action = str(latest_order.get("action") if latest_order else "NONE").upper()
        close_threshold_rate = config.close_change_threshold_pct / 100
        invalidation_triggered = (
            latest_action in {"SIM_SELL", "SIM_CLOSE", "SIM_COVER"}
            or pnl_rate <= min(-0.01, close_threshold_rate)
            or max_drawdown <= min(-0.01, close_threshold_rate)
        )
        failure_tags = []
        if invalidation_triggered:
            failure_tags.append("AI_INVALIDATION_REVIEW")
        if pnl_rate < -0.01:
            failure_tags.append("PAPER_PNL_NEGATIVE")
        if not day_orders:
            failure_tags.append("NO_TODAY_ORDER")
        metadata = signal.get("metadata_json") if isinstance(signal.get("metadata_json"), dict) else {}
        signal_boundary = metadata.get("user_signal_boundary") if isinstance(metadata.get("user_signal_boundary"), dict) else {}

        record = {
            "trading_date": trading_date,
            "signal_date": trading_date,
            "symbol": symbol,
            "signal_id": signal.get("signal_id"),
            "signal_status": signal.get("status"),
            "source_type": "SIGNALOPS_DAILY_REVIEW",
            "source_id": signal.get("signal_id"),
            "trigger_conditions": list(signal.get("trigger_conditions") or []),
            "invalidation_conditions": list(signal.get("invalidation_conditions") or []),
            "user_initial_buy_signal": str(signal_boundary.get("initial_buy_signal") or config.initial_buy_signal or ""),
            "user_final_sell_signal": str(signal_boundary.get("final_sell_signal") or config.final_sell_signal or ""),
            "order_count": len(day_orders),
            "all_order_count": len(orders),
            "action_counts": action_counts,
            "latest_action": latest_action,
            "latest_order_id": latest_order.get("order_id") if latest_order else None,
            "filled_value": round(filled_value, 6),
            "total_fees": round(total_fees, 6),
            "available_cash": round(available_cash, 6),
            "market_value": round(market_value, 6),
            "initial_cash": round(initial_cash, 6),
            "floating_pnl": round(pnl, 6),
            "pnl_rate": round(pnl_rate, 6),
            "max_drawdown": round(max_drawdown, 6),
            "invalidation_triggered": invalidation_triggered,
            "factor_sources": factor_sources,
            "failure_tags": failure_tags,
            "simulation_only": True,
            "is_real_trade": False,
            "cleaned_at": _now_iso(),
        }
        return _normalize_cleaned_record(record)

    def _build_performance_stats(
        self,
        current_stats: Dict[str, Any],
        cleaned_records: list[Dict[str, Any]],
    ) -> Dict[str, Any]:
        stats = current_stats if isinstance(current_stats, dict) else {}
        grouped: Dict[str, Dict[str, list[Dict[str, Any]]]] = {
            "global": {"all": []},
            "symbols": {},
            "factors": {},
            "triggers": {},
        }
        for record in cleaned_records:
            grouped["global"]["all"].append(record)
            symbol = _performance_key(record.get("symbol"), "UNKNOWN")
            grouped["symbols"].setdefault(symbol, []).append(record)
            sources = record.get("factor_sources") if isinstance(record.get("factor_sources"), list) else []
            for source in sources or ["unattributed_factor"]:
                grouped["factors"].setdefault(_performance_key(source, "unattributed_factor"), []).append(record)
            trigger_conditions = record.get("trigger_conditions") if isinstance(record.get("trigger_conditions"), list) else []
            if not trigger_conditions:
                fallback_trigger = record.get("user_initial_buy_signal") or "unattributed_trigger"
                trigger_conditions = [fallback_trigger]
            for trigger in trigger_conditions[:5]:
                grouped["triggers"].setdefault(_performance_key(trigger, "unattributed_trigger"), []).append(record)

        next_stats: Dict[str, Any] = {
            "version": PERFORMANCE_STATS_VERSION,
            "updated_at": _now_iso(),
        }
        for section, section_records in grouped.items():
            previous_section = stats.get(section) if isinstance(stats.get(section), dict) else {}
            next_section = dict(previous_section)
            for key, records in section_records.items():
                next_section[key] = _performance_bucket(previous_section.get(key), records)
            next_stats[section] = next_section
        return next_stats

    def _performance_summary(self, performance_stats: Dict[str, Any]) -> Dict[str, Any]:
        stats = performance_stats if isinstance(performance_stats, dict) else {}
        global_stats = as_global if isinstance((as_global := stats.get("global")), dict) else {}
        global_bucket = global_stats.get("all") if isinstance(global_stats.get("all"), dict) else {}
        factors = stats.get("factors") if isinstance(stats.get("factors"), dict) else {}
        triggers = stats.get("triggers") if isinstance(stats.get("triggers"), dict) else {}
        factor_rank = sorted(
            (
                {"key": key, **value}
                for key, value in factors.items()
                if isinstance(value, dict)
            ),
            key=lambda item: (
                _clamp_float(item.get("confidence"), 0.0, 0.0, 1.0),
                _clamp_float(item.get("trade_count"), 0.0, 0.0, 1_000_000.0),
            ),
            reverse=True,
        )
        low_quality_triggers = sorted(
            (
                {"key": key, **value}
                for key, value in triggers.items()
                if isinstance(value, dict)
                and str(value.get("quality_status") or "") in {"POOR", "LOW_SAMPLE"}
            ),
            key=lambda item: (
                str(item.get("quality_status") or "") == "POOR",
                _clamp_float(item.get("confidence"), 0.0, 0.0, 1.0),
                _clamp_float(item.get("trade_count"), 0.0, 0.0, 1_000_000.0),
            ),
            reverse=True,
        )
        return {
            "global": global_bucket,
            "top_factors": factor_rank[:5],
            "low_quality_triggers": low_quality_triggers[:5],
            "min_trade_count": TUNING_MIN_TRADE_COUNT,
            "min_evidence_weight": TUNING_MIN_EVIDENCE_WEIGHT,
            "min_confidence": TUNING_MIN_CONFIDENCE,
        }

    def _walk_forward_validation(
        self,
        *,
        cleaned_record_history: list[Dict[str, Any]],
        candidate_direction: str,
    ) -> Dict[str, Any]:
        capped_history = _capped_trade_record_history(cleaned_record_history)
        train_records, validation_records, train_window, validation_window = _split_walk_forward_windows(capped_history)
        train_metrics = _record_window_metrics(train_records)
        validation_metrics = _record_window_metrics(validation_records)
        train_trade_count = int(train_metrics["trade_count"])
        train_evidence_weight = _clamp_float(train_metrics["evidence_weight"], 0.0, 0.0, 1_000_000.0)
        train_confidence = _clamp_float(train_metrics["confidence"], 0.0, 0.0, 1.0)
        validation_trade_count = int(validation_metrics["trade_count"])
        validation_win_rate = _clamp_float(validation_metrics["win_rate"], 0.0, 0.0, 1.0)
        validation_failure_rate = _clamp_float(validation_metrics["failure_rate"], 0.0, 0.0, 1.0)
        validation_avg_pnl_rate = _clamp_float(validation_metrics["avg_pnl_rate"], 0.0, -1.0, 1.0)
        validation_drawdown = abs(_clamp_float(validation_metrics["max_drawdown"], 0.0, -1.0, 0.0))
        train_win_rate = _clamp_float(train_metrics["win_rate"], 0.0, 0.0, 1.0)
        train_avg_pnl_rate = _clamp_float(train_metrics["avg_pnl_rate"], 0.0, -1.0, 1.0)
        train_drawdown = abs(_clamp_float(train_metrics["max_drawdown"], 0.0, -1.0, 0.0))
        sample_ready = (
            train_trade_count >= TUNING_MIN_TRADE_COUNT
            and train_evidence_weight >= TUNING_MIN_EVIDENCE_WEIGHT
            and train_confidence >= TUNING_MIN_CONFIDENCE
        )
        validation_ready = validation_trade_count >= 3 and bool(validation_window.get("dates"))
        non_overlapping_windows = bool(
            train_window.get("end")
            and validation_window.get("start")
            and str(train_window["end"]) < str(validation_window["start"])
        )
        quality_ready = (
            train_metrics.get("evidence_quality") not in {"LOW", "SUPPORTING_ONLY"}
            and validation_metrics.get("evidence_quality") not in {"LOW", "SUPPORTING_ONLY"}
        )
        win_rate_not_down = validation_win_rate >= train_win_rate
        expectancy_improved = validation_avg_pnl_rate > train_avg_pnl_rate
        drawdown_not_worse = validation_drawdown <= train_drawdown + 0.000001
        net_after_cost_positive = validation_avg_pnl_rate > 0
        support_ready = (
            candidate_direction in {"risk_tighten", "opportunity_expand"}
            and win_rate_not_down
            and expectancy_improved
            and drawdown_not_worse
            and net_after_cost_positive
        )
        passed = sample_ready and validation_ready and non_overlapping_windows and quality_ready and support_ready
        reasons = []
        if train_trade_count < TUNING_MIN_TRADE_COUNT:
            reasons.append("insufficient_trade_count")
        if train_evidence_weight < TUNING_MIN_EVIDENCE_WEIGHT:
            reasons.append("insufficient_evidence_weight")
        if train_confidence < TUNING_MIN_CONFIDENCE:
            reasons.append("insufficient_confidence")
        if not validation_ready:
            reasons.append("insufficient_validation_trade_count")
        if not non_overlapping_windows:
            reasons.append("overlapping_or_missing_walk_forward_windows")
        if not quality_ready:
            reasons.append("low_quality_evidence")
        if not win_rate_not_down:
            reasons.append("validation_win_rate_declined")
        if not expectancy_improved:
            reasons.append("validation_expectancy_not_improved")
        if not drawdown_not_worse:
            reasons.append("validation_drawdown_worsened")
        if not net_after_cost_positive:
            reasons.append("validation_after_cost_not_positive")
        if not support_ready:
            reasons.append("validation_direction_not_confirmed")
        validation_status = "PASSED" if passed else "FAILED" if bool(train_window.get("dates")) and not non_overlapping_windows else "PENDING"
        return {
            "status": validation_status,
            "method": "capped_trade_record_history_v1",
            "candidate_direction": candidate_direction,
            "history_limit": CLEANED_RECORD_HISTORY_LIMIT,
            "history_count": len(capped_history),
            "train_window": train_window,
            "validation_window": validation_window,
            "train_metrics": train_metrics,
            "validation_metrics": validation_metrics,
            "checks": {
                "train_trade_count_min": TUNING_MIN_TRADE_COUNT,
                "validation_trade_count_min": 3,
                "non_overlapping_windows": non_overlapping_windows,
                "quality_ready": quality_ready,
                "win_rate_not_down": win_rate_not_down,
                "expectancy_improved": expectancy_improved,
                "drawdown_not_worse": drawdown_not_worse,
                "after_cost_positive": net_after_cost_positive,
            },
            "sample_quality": validation_metrics.get("evidence_quality") or "LOW",
            "trade_count": train_trade_count,
            "evidence_weight": round(train_evidence_weight, 4),
            "confidence": round(train_confidence, 4),
            "win_rate": train_metrics["win_rate"],
            "avg_pnl_rate": train_metrics["avg_pnl_rate"],
            "max_drawdown": train_metrics["max_drawdown"],
            "reasons": reasons,
            "simulation_only": True,
            "is_real_trade": False,
        }

    def _latest_kline_evidence_package(self, config: AutoPaperTradingConfig) -> Dict[str, Any]:
        decision = config.last_decision if isinstance(config.last_decision, dict) else {}
        pre_buy_quality = (
            decision.get("pre_buy_quality")
            if isinstance(decision.get("pre_buy_quality"), dict)
            else decision.get("performanceQuality")
            if isinstance(decision.get("performanceQuality"), dict)
            else {}
        )
        components = pre_buy_quality.get("components") if isinstance(pre_buy_quality.get("components"), dict) else {}
        kline_quality = (
            decision.get("kline_signal_quality")
            if isinstance(decision.get("kline_signal_quality"), dict)
            else pre_buy_quality.get("kline_signal_quality")
            if isinstance(pre_buy_quality.get("kline_signal_quality"), dict)
            else components.get("kline_signal_quality")
            if isinstance(components.get("kline_signal_quality"), dict)
            else {}
        )
        strategy_stability_quality = (
            decision.get("strategy_stability_quality")
            if isinstance(decision.get("strategy_stability_quality"), dict)
            else pre_buy_quality.get("strategy_stability_quality")
            if isinstance(pre_buy_quality.get("strategy_stability_quality"), dict)
            else components.get("strategy_stability_quality")
            if isinstance(components.get("strategy_stability_quality"), dict)
            else {}
        )
        if not kline_quality:
            kline_quality = evaluate_kline_signal_quality(config.symbol, {}, current_price=None)
        ladder_policy = kline_quality.get("ladder_buy_policy") if isinstance(kline_quality.get("ladder_buy_policy"), dict) else {}
        kline_strategy = kline_quality.get("kline_strategy") if isinstance(kline_quality.get("kline_strategy"), dict) else {}
        package_basis = {
            "symbol": config.symbol,
            "final_score": kline_quality.get("final_score") or kline_quality.get("score"),
            "action_policy": kline_quality.get("action_policy") or kline_quality.get("actionPolicy"),
            "ladder_stage": kline_quality.get("ladder_stage"),
            "strategy": kline_strategy,
            "ladder": ladder_policy,
        }
        return {
            "package_id": f"kline-evidence-{_stable_json_hash(package_basis)}",
            "source": "signalops_kline_quality",
            "symbol": config.symbol,
            "kline_signal_quality": kline_quality,
            "kline_strategy": kline_strategy,
            "ladder_buy_policy": ladder_policy,
            "score": kline_quality.get("final_score") or kline_quality.get("score") or 0,
            "grade": kline_quality.get("grade") or "WAIT",
            "action_policy": kline_quality.get("action_policy") or kline_quality.get("actionPolicy") or "HOLD",
            "simulation_only": True,
            "is_real_trade": False,
        }

    def _latest_stability_evidence_package(self, config: AutoPaperTradingConfig) -> Dict[str, Any]:
        decision = config.last_decision if isinstance(config.last_decision, dict) else {}
        pre_buy_quality = (
            decision.get("pre_buy_quality")
            if isinstance(decision.get("pre_buy_quality"), dict)
            else decision.get("performanceQuality")
            if isinstance(decision.get("performanceQuality"), dict)
            else {}
        )
        components = pre_buy_quality.get("components") if isinstance(pre_buy_quality.get("components"), dict) else {}
        stability_quality = (
            decision.get("strategy_stability_quality")
            if isinstance(decision.get("strategy_stability_quality"), dict)
            else pre_buy_quality.get("strategy_stability_quality")
            if isinstance(pre_buy_quality.get("strategy_stability_quality"), dict)
            else components.get("strategy_stability_quality")
            if isinstance(components.get("strategy_stability_quality"), dict)
            else {}
        )
        if not stability_quality:
            kline_quality = (
                decision.get("kline_signal_quality")
                if isinstance(decision.get("kline_signal_quality"), dict)
                else pre_buy_quality.get("kline_signal_quality")
                if isinstance(pre_buy_quality.get("kline_signal_quality"), dict)
                else components.get("kline_signal_quality")
                if isinstance(components.get("kline_signal_quality"), dict)
                else evaluate_kline_signal_quality(config.symbol, {}, current_price=None)
            )
            stability_quality = evaluate_strategy_stability_quality(
                config.symbol,
                {},
                kline_quality=kline_quality,
                performance_stats={},
                current_price=None,
            )
        stability_strategy = stability_quality.get("stability_strategy") if isinstance(stability_quality.get("stability_strategy"), dict) else {}
        meta_label_gate = stability_quality.get("meta_label_gate") if isinstance(stability_quality.get("meta_label_gate"), dict) else {}
        sizing_policy = stability_quality.get("volatility_sizing_policy") if isinstance(stability_quality.get("volatility_sizing_policy"), dict) else {}
        package_basis = {
            "symbol": config.symbol,
            "stability_score": stability_quality.get("stability_score") or stability_quality.get("score"),
            "action_policy": stability_quality.get("action_policy") or stability_quality.get("actionPolicy"),
            "regime": (stability_quality.get("regime_state") or {}).get("status") if isinstance(stability_quality.get("regime_state"), dict) else "",
            "stability_strategy": stability_strategy,
            "meta_label_gate": meta_label_gate,
            "volatility_sizing_policy": sizing_policy,
        }
        return {
            "package_id": f"stability-evidence-{_stable_json_hash(package_basis)}",
            "source": "signalops_strategy_stability",
            "symbol": config.symbol,
            "strategy_stability_quality": stability_quality,
            "stability_strategy": stability_strategy,
            "meta_label_gate": meta_label_gate,
            "volatility_sizing_policy": sizing_policy,
            "score": stability_quality.get("stability_score") or stability_quality.get("score") or 0,
            "grade": stability_quality.get("grade") or "WAIT",
            "action_policy": stability_quality.get("action_policy") or stability_quality.get("actionPolicy") or "HOLD",
            "simulation_only": True,
            "is_real_trade": False,
        }

    def _build_daily_tuning_update(
        self,
        config: AutoPaperTradingConfig,
        cleaned_records: list[Dict[str, Any]],
        *,
        cleaned_record_history: Optional[list[Dict[str, Any]]] = None,
        compressed_observation_history: Optional[Dict[str, Any]] = None,
        evidence_links: Optional[list[Dict[str, Any]]] = None,
        review_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        kline_evidence_package = self._latest_kline_evidence_package(config)
        stability_evidence_package = self._latest_stability_evidence_package(config)

        def average(values: list[float]) -> float:
            return sum(values) / len(values) if values else 0.0

        performance_stats = self._build_performance_stats(config.performance_stats, cleaned_records)
        performance_summary = self._performance_summary(performance_stats)
        candidate_records = _capped_trade_record_history(cleaned_record_history or cleaned_records)
        observation_summary = (
            _normalize_compressed_observation_history(compressed_observation_history)
            if compressed_observation_history is not None
            else _compress_observation_history({}, cleaned_records)
        )
        evidence_links = evidence_links or []
        trade_count = sum(1 for item in candidate_records if _record_has_order(item))
        current_no_trade_count = sum(1 for item in cleaned_records if isinstance(item, dict) and not _record_has_order(item))
        compressed_observation_count = int(observation_summary.get("total_count") or 0)
        failures = [item for item in candidate_records if _record_is_failure(item)]
        wins = [item for item in candidate_records if _record_is_win(item)]
        sample_count = len(candidate_records)
        weighted_total = sum(_record_sample_weight(item) for item in candidate_records)
        failure_weight = sum(_record_sample_weight(item) for item in failures)
        win_weight = sum(_record_sample_weight(item) for item in wins)
        prior_weight = 2.4 if sample_count else 0.0
        prior_rate = 0.25 if sample_count else 0.0
        failure_rate = (
            (failure_weight + prior_rate * prior_weight) / (weighted_total + prior_weight)
            if weighted_total + prior_weight > 0
            else 0.0
        )
        win_rate = (
            (win_weight + prior_rate * prior_weight) / (weighted_total + prior_weight)
            if weighted_total + prior_weight > 0
            else 0.0
        )
        no_trade_rate = (
            compressed_observation_count / (sample_count + compressed_observation_count)
            if sample_count + compressed_observation_count
            else 0.0
        )
        avg_pnl_rate = average([_record_pnl_rate(item) for item in candidate_records])
        avg_loss_rate = (
            sum(abs(min(_record_pnl_rate(item), 0.0)) * _record_sample_weight(item) for item in failures) / failure_weight
            if failure_weight
            else 0.0
        )
        avg_win_rate = (
            sum(max(_record_pnl_rate(item), 0.0) * _record_sample_weight(item) for item in wins) / win_weight
            if win_weight
            else 0.0
        )
        max_drawdown = max([_record_drawdown(item) for item in candidate_records] or [0.0])
        loss_severity = _clamp_float(avg_loss_rate / 0.08, 0.0, 0.0, 1.0)
        win_strength = _clamp_float(avg_win_rate / 0.08, 0.0, 0.0, 1.0)
        drawdown_pressure = _clamp_float(max_drawdown / 0.08, 0.0, 0.0, 1.0)
        confidence = min(1.0, (weighted_total / 6) ** 0.5) if weighted_total else 0.0

        risk_pressure = (
            failure_rate * 0.42
            + loss_severity * 0.30
            + drawdown_pressure * 0.18
            + no_trade_rate * 0.05
        )
        opportunity_pressure = win_rate * 0.36 + win_strength * 0.30
        signed_pressure = risk_pressure - opportunity_pressure
        nonlinear_adjustment = confidence * (signed_pressure / (1.0 + abs(signed_pressure)))
        if abs(nonlinear_adjustment) < 0.015:
            nonlinear_adjustment = 0.0
        buy_delta = _clamp_float(
            nonlinear_adjustment * 0.50 + (loss_severity * confidence * 0.08 if nonlinear_adjustment > 0 else 0.0),
            0.0,
            -0.20,
            0.45,
        )
        close_delta = _clamp_float(
            nonlinear_adjustment * 0.34 + (drawdown_pressure * confidence * 0.08 if nonlinear_adjustment > 0 else 0.0),
            0.0,
            -0.25,
            0.45,
        )
        ratio_multiplier = _clamp_float(1.0 - nonlinear_adjustment * 0.22, 1.0, 0.78, 1.10)

        ratio_fields = [
            "watch_position_ratio",
            "probe_position_ratio",
            "positive_position_ratio",
            "breakout_position_ratio",
            "defensive_position_ratio",
            "existing_position_ratio",
            "strength_follow_position_ratio",
        ]
        before = {
            "buy_change_threshold_pct": config.buy_change_threshold_pct,
            "close_change_threshold_pct": config.close_change_threshold_pct,
            **{field: getattr(config, field) for field in ratio_fields},
        }
        next_parameters = {
            "buy_change_threshold_pct": round(
                _clamp_float(config.buy_change_threshold_pct + buy_delta, 0.5, 0.1, 5.0),
                4,
            ),
            "close_change_threshold_pct": round(
                _clamp_float(config.close_change_threshold_pct + close_delta, -2.0, -5.0, -0.2),
                4,
            ),
        }
        for field in ratio_fields:
            next_parameters[field] = round(
                _clamp_float(getattr(config, field) * ratio_multiplier, getattr(config, field), 0.0, 0.85),
                4,
            )

        factor_adjustments = dict(config.factor_adjustments or {})
        source_stats: Dict[str, Dict[str, float]] = {}
        for record in candidate_records:
            for source in record.get("factor_sources") or ["unattributed_factor"]:
                stats = source_stats.setdefault(
                    str(source),
                    {
                        "sample_count": 0,
                        "wins": 0,
                        "losses": 0,
                        "win_weight": 0.0,
                        "loss_weight": 0.0,
                        "evidence_weight": 0.0,
                        "pnl_sum": 0.0,
                        "drawdown_max": 0.0,
                        "loss_sum": 0.0,
                    },
                )
                stats["sample_count"] += 1
                current_pnl = _record_pnl_rate(record)
                current_weight = _record_sample_weight(record)
                stats["evidence_weight"] += current_weight
                stats["pnl_sum"] += current_pnl * current_weight
                stats["drawdown_max"] = max(stats["drawdown_max"], _record_drawdown(record))
                if _record_is_failure(record):
                    stats["losses"] += 1
                    stats["loss_weight"] += current_weight
                    stats["loss_sum"] += abs(min(current_pnl, 0.0)) * current_weight
                elif _record_is_win(record):
                    stats["wins"] += 1
                    stats["win_weight"] += current_weight
        for source, stats in source_stats.items():
            current = factor_adjustments.get(source) if isinstance(factor_adjustments.get(source), dict) else {}
            prior_decay = _clamp_float(current.get("prior_decay"), 0.88, 0.0, 1.0)
            losses = _clamp_float(current.get("losses"), 0.0, 0.0, 10_000.0) * prior_decay + float(stats["losses"])
            wins_count = _clamp_float(current.get("wins"), 0.0, 0.0, 10_000.0) * prior_decay + float(stats["wins"])
            sample_count = _clamp_float(current.get("sample_count"), 0.0, 0.0, 10_000.0) * prior_decay + float(stats["sample_count"])
            weighted_losses = _clamp_float(current.get("weighted_losses"), 0.0, 0.0, 10_000.0) * prior_decay + stats["loss_weight"]
            weighted_wins = _clamp_float(current.get("weighted_wins"), 0.0, 0.0, 10_000.0) * prior_decay + stats["win_weight"]
            evidence_weight = (
                _clamp_float(current.get("evidence_weight"), 0.0, 0.0, 10_000.0) * prior_decay
                + stats["evidence_weight"]
            )
            source_confidence = min(1.0, (evidence_weight / 8) ** 0.5) if evidence_weight else 0.0
            source_edge = (weighted_wins - weighted_losses) / (evidence_weight + 3.0)
            recent_avg_pnl = stats["pnl_sum"] / max(stats["evidence_weight"], 0.000001)
            recent_loss_severity = _clamp_float(
                (stats["loss_sum"] / max(stats["loss_weight"], 0.000001)) / 0.08,
                0.0,
                0.0,
                1.0,
            ) if stats["loss_weight"] else 0.0
            recent_drawdown_pressure = _clamp_float(stats["drawdown_max"] / 0.08, 0.0, 0.0, 1.0)
            source_risk = -source_edge
            factor_adjustments[source] = {
                "sample_count": round(sample_count, 4),
                "wins": round(wins_count, 4),
                "losses": round(losses, 4),
                "weighted_wins": round(weighted_wins, 4),
                "weighted_losses": round(weighted_losses, 4),
                "evidence_weight": round(evidence_weight, 4),
                "position_ratio_delta": round(
                    _clamp_float((source_edge * 0.18 - recent_drawdown_pressure * 0.03) * source_confidence, 0.0, -0.10, 0.10),
                    4,
                ),
                "buy_threshold_delta": round(
                    _clamp_float((source_risk * 0.16 + recent_loss_severity * 0.08) * source_confidence, 0.0, -0.10, 0.25),
                    4,
                ),
                "invalidation_delta": round(
                    _clamp_float((source_risk * 0.14 + recent_drawdown_pressure * 0.08) * source_confidence, 0.0, -0.20, 0.30),
                    4,
                ),
                "confidence": round(source_confidence, 4),
                "recent_avg_pnl_rate": round(recent_avg_pnl, 6),
                "recent_max_drawdown": round(-stats["drawdown_max"], 6),
                "prior_decay": prior_decay,
                "updated_at": _now_iso(),
            }

        recommended_parameters = next_parameters
        risk_tightened = nonlinear_adjustment > 0.02 or len(failures) > len(wins)
        risk_supported = nonlinear_adjustment > 0 and (
            failure_rate > win_rate or avg_pnl_rate < 0 or max_drawdown >= 0.03
        )
        opportunity_supported = nonlinear_adjustment < 0 and (
            win_rate > failure_rate and avg_pnl_rate > 0 and max_drawdown < 0.08
        )
        if risk_supported or risk_tightened:
            candidate_direction = "risk_tighten"
        elif opportunity_supported or nonlinear_adjustment < -0.02:
            candidate_direction = "opportunity_expand"
        else:
            candidate_direction = "neutral"
        walk_forward_validation = self._walk_forward_validation(
            cleaned_record_history=candidate_records,
            candidate_direction=candidate_direction,
        )
        benchmark_comparison = {
            "symbol": DEFAULT_EXPERIMENT_BENCHMARK_SYMBOL,
            "available": False,
            "status": "UNAVAILABLE",
            "reason": "dedicated_backtest_signalops_experiment_required",
            "simulation_only": True,
            "is_real_trade": False,
        }
        walk_forward_validation["benchmark_comparison"] = benchmark_comparison
        walk_forward_validation["checks"]["benchmark_available"] = False
        factor_adjustments_changed = factor_adjustments != (config.factor_adjustments or {})
        has_parameter_delta = False
        for key, value in recommended_parameters.items():
            current_value = _clamp_float(getattr(config, key), 0.0, -1_000_000_000.0, 1_000_000_000.0)
            recommended_value = _clamp_float(value, current_value, -1_000_000_000.0, 1_000_000_000.0)
            if abs(recommended_value - current_value) >= 0.0001:
                has_parameter_delta = True
                break
        has_recommendation = has_parameter_delta or factor_adjustments_changed
        if not has_recommendation:
            application_status = "SKIPPED"
            application_reason = "no_parameter_delta"
        elif walk_forward_validation["status"] == "PASSED":
            application_status = "BACKTEST_PENDING"
            application_reason = "dedicated_backtest_validation_pending"
        elif (
            walk_forward_validation["status"] == "PENDING"
            and walk_forward_validation["train_metrics"].get("evidence_quality") not in {"LOW", "SUPPORTING_ONLY"}
            and int(walk_forward_validation["train_metrics"].get("trade_count") or 0) >= TUNING_MIN_TRADE_COUNT
        ):
            application_status = "BACKTEST_PENDING"
            application_reason = ",".join(walk_forward_validation["reasons"]) or "walk_forward_validation_pending"
        else:
            application_status = "RECOMMENDED_ONLY"
            application_reason = ",".join(walk_forward_validation["reasons"]) or "walk_forward_validation_pending"
        applied_parameters = {}
        candidate_factor_adjustments = factor_adjustments
        applied_factor_adjustments = config.factor_adjustments or {}
        next_parameters = applied_parameters
        baseline_config = {**before, "factor_adjustments": config.factor_adjustments or {}}
        candidate_config = {
            **recommended_parameters,
            "factor_adjustments": candidate_factor_adjustments,
            "kline_strategy": kline_evidence_package.get("kline_strategy", {}),
            "ladder_buy_policy": kline_evidence_package.get("ladder_buy_policy", {}),
            "stability_strategy": stability_evidence_package.get("stability_strategy", {}),
            "meta_label_gate": stability_evidence_package.get("meta_label_gate", {}),
            "volatility_sizing_policy": stability_evidence_package.get("volatility_sizing_policy", {}),
        }
        after = {
            **before,
            "factor_adjustments": applied_factor_adjustments,
        }
        experiment_basis = {
            "review_date": review_date,
            "candidate_direction": candidate_direction,
            "baseline_config": baseline_config,
            "candidate_config": candidate_config,
            "history_count": len(candidate_records),
            "compressed_observation_count": compressed_observation_count,
            "kline_evidence_package": kline_evidence_package,
            "stability_evidence_package": stability_evidence_package,
        }
        experiment_package_hash = _signalops_experiment_package_hash(
            baseline_config=baseline_config,
            candidate_config=candidate_config,
            train_window=walk_forward_validation.get("train_window") or {},
            validation_window=walk_forward_validation.get("validation_window") or {},
            cleaned_records=candidate_records,
        )
        experiment_basis["experiment_package_hash"] = experiment_package_hash
        promotion_status = application_status if application_status != "SKIPPED" else "NO_CHANGE"
        strategy_experiment = {
            "experiment_id": f"signalops-exp-{_stable_json_hash(experiment_basis)}",
            "experiment_package_hash": experiment_package_hash,
            "baseline_config": baseline_config,
            "candidate_config": candidate_config,
            "candidate_reason": application_reason,
            "promotion_gate": {
                "name": "signalops_backtest_experiment_v1",
                "status": walk_forward_validation["status"],
                "candidate_direction": candidate_direction,
                "required_outcome": "READY_FOR_REVIEW",
                "validation": walk_forward_validation,
                "benchmark_comparison": benchmark_comparison,
            },
            "winner_config_id": "baseline",
            "promotion_status": promotion_status,
            "evidence_links": evidence_links,
            "walk_forward_run_ids": {},
            "benchmark_comparison": benchmark_comparison,
            "kline_evidence_package": kline_evidence_package,
            "stability_evidence_package": stability_evidence_package,
            "simulation_only": True,
            "is_real_trade": False,
        }
        candidate_evidence_package = {
            "package_id": f"signalops-evidence-{_stable_json_hash({**experiment_basis, 'evidence_links': evidence_links})}",
            "experiment_package_hash": experiment_package_hash,
            "review_date": review_date,
            "candidate_status": promotion_status,
            "sample_quality": walk_forward_validation.get("sample_quality") or "LOW",
            "benchmark_comparison": benchmark_comparison,
            "walk_forward_run_ids": {},
            "walk_forward_summary": {
                "status": walk_forward_validation.get("status"),
                "train_window": walk_forward_validation.get("train_window"),
                "validation_window": walk_forward_validation.get("validation_window"),
                "checks": walk_forward_validation.get("checks"),
                "reasons": walk_forward_validation.get("reasons"),
            },
            "compressed_observation_history": observation_summary,
            "research_evidence_package": {
                "source": "signalops_daily_review",
                "experiment_package_hash": experiment_package_hash,
                "backtest_status": "BACKTEST_PENDING" if application_status == "BACKTEST_PENDING" else application_status,
                "supporting_only": True,
                "evidence_links": evidence_links,
                "simulation_only": True,
                "is_real_trade": False,
            },
            "strategy_experiment_id": strategy_experiment["experiment_id"],
            "kline_evidence_package": kline_evidence_package,
            "stability_evidence_package": stability_evidence_package,
            "evidence_links": evidence_links,
            "simulation_only": True,
            "is_real_trade": False,
        }
        strategy_experiment["evidence_package"] = candidate_evidence_package
        review_fields = [
            "strategy_experiment",
            "candidate_factor_adjustments",
            "applied_factor_adjustments",
            "walk_forward_validation",
            "candidate_evidence_package",
            "kline_evidence_package",
            "stability_evidence_package",
            "performance_stats",
            "evidence_links",
            "simulation_only",
            "is_real_trade",
        ]
        return {
            "review_reason": "daily_after_close_auto_review",
            "adjustment_model": "weighted_bayesian_decay_v3",
            "sample_count": len(candidate_records),
            "current_sample_count": len(cleaned_records),
            "current_no_trade_count": current_no_trade_count,
            "cleaned_record_history_count": len(candidate_records),
            "compressed_observation_count": compressed_observation_count,
            "compressed_observation_history": observation_summary,
            "trade_count": trade_count,
            "evidence_weight": round(weighted_total, 4),
            "wins": len(wins),
            "failures": len(failures),
            "risk_tightened": risk_tightened,
            "tuning_confidence": round(confidence, 4),
            "risk_pressure": round(risk_pressure, 6),
            "opportunity_pressure": round(opportunity_pressure, 6),
            "nonlinear_adjustment": round(nonlinear_adjustment, 6),
            "avg_pnl_rate": round(avg_pnl_rate, 6),
            "avg_loss_rate": round(avg_loss_rate, 6),
            "avg_win_rate": round(avg_win_rate, 6),
            "max_drawdown": round(-max_drawdown, 6),
            "no_trade_rate": round(no_trade_rate, 6),
            "buy_delta": round(buy_delta, 4),
            "close_delta": round(close_delta, 4),
            "position_ratio_multiplier": round(ratio_multiplier, 4),
            "performance_stats": performance_stats,
            "performance_summary": performance_summary,
            "recommended_parameters": recommended_parameters,
            "applied_parameters": applied_parameters,
            "application_status": application_status,
            "application_reason": application_reason,
            "walk_forward_validation": walk_forward_validation,
            "strategy_experiment": strategy_experiment,
            "candidate_evidence_package": candidate_evidence_package,
            "kline_evidence_package": kline_evidence_package,
            "stability_evidence_package": stability_evidence_package,
            "before": before,
            "next_parameters": next_parameters,
            "candidate_factor_adjustments": candidate_factor_adjustments,
            "applied_factor_adjustments": applied_factor_adjustments,
            "factor_adjustments": applied_factor_adjustments,
            "after": after,
            "review_fields": review_fields,
            "evidence_links": evidence_links,
            "simulation_only": True,
            "is_real_trade": False,
        }

    def _review_queue_item_from_tuning(
        self,
        *,
        tuning_update: Dict[str, Any],
        review_date: str,
        reviewed_symbols: list[Dict[str, Any]],
        evidence_links: list[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        application_status = str(tuning_update.get("application_status") or "").strip().upper()
        if application_status not in {"READY_FOR_REVIEW", "BACKTEST_PENDING", "RECOMMENDED_ONLY"}:
            return None
        strategy_experiment = tuning_update.get("strategy_experiment") if isinstance(tuning_update.get("strategy_experiment"), dict) else {}
        experiment_id = str(strategy_experiment.get("experiment_id") or "").strip()
        if not experiment_id:
            return None
        validation = tuning_update.get("walk_forward_validation") if isinstance(tuning_update.get("walk_forward_validation"), dict) else {}
        evidence_package = (
            tuning_update.get("candidate_evidence_package")
            if isinstance(tuning_update.get("candidate_evidence_package"), dict)
            else strategy_experiment.get("evidence_package")
            if isinstance(strategy_experiment.get("evidence_package"), dict)
            else {}
        )
        symbols = [str(item.get("symbol") or "").strip() for item in reviewed_symbols if isinstance(item, dict)]
        symbols = [item for item in symbols if item]
        queue_item_id = f"rq-{experiment_id}"
        sample_quality = str(evidence_package.get("sample_quality") or validation.get("sample_quality") or "LOW").upper()
        review_allowed = application_status == "READY_FOR_REVIEW" and sample_quality not in {"LOW", "SUPPORTING_ONLY"}
        experiment_package_hash = str(
            strategy_experiment.get("experiment_package_hash")
            or evidence_package.get("experiment_package_hash")
            or ""
        ).strip()
        benchmark_comparison = (
            evidence_package.get("benchmark_comparison")
            if isinstance(evidence_package.get("benchmark_comparison"), dict)
            else strategy_experiment.get("benchmark_comparison")
            if isinstance(strategy_experiment.get("benchmark_comparison"), dict)
            else {}
        )
        kline_evidence_package = (
            evidence_package.get("kline_evidence_package")
            if isinstance(evidence_package.get("kline_evidence_package"), dict)
            else tuning_update.get("kline_evidence_package")
            if isinstance(tuning_update.get("kline_evidence_package"), dict)
            else strategy_experiment.get("kline_evidence_package")
            if isinstance(strategy_experiment.get("kline_evidence_package"), dict)
            else {}
        )
        stability_evidence_package = (
            evidence_package.get("stability_evidence_package")
            if isinstance(evidence_package.get("stability_evidence_package"), dict)
            else tuning_update.get("stability_evidence_package")
            if isinstance(tuning_update.get("stability_evidence_package"), dict)
            else strategy_experiment.get("stability_evidence_package")
            if isinstance(strategy_experiment.get("stability_evidence_package"), dict)
            else {}
        )
        baseline_config = strategy_experiment.get("baseline_config") if isinstance(strategy_experiment.get("baseline_config"), dict) else {}
        candidate_config = strategy_experiment.get("candidate_config") if isinstance(strategy_experiment.get("candidate_config"), dict) else {}
        parameter_diff_summary = _parameter_diff_summary(baseline_config, candidate_config)
        strategy_experiment_payload = {
            **strategy_experiment,
            "baseline_config": baseline_config,
            "candidate_config": candidate_config,
            "parameter_diff_summary": parameter_diff_summary,
            "simulation_only": True,
            "is_real_trade": False,
        }
        expires_at = (_now() + timedelta(days=30)).isoformat()
        return {
            "id": queue_item_id,
            "queue_item_id": queue_item_id,
            "experiment_id": experiment_id,
            "experiment_package_hash": experiment_package_hash,
            "signal_id": "",
            "symbol": ",".join(symbols) if symbols else "POOL",
            "title": f"SignalOps candidate {review_date}",
            "candidate_status": application_status,
            "promotion_status": application_status,
            "lifecycle_status": application_status,
            "review_decision": "CONTINUE_OBSERVING" if not review_allowed else "PENDING_REVIEW",
            "review_allowed": review_allowed,
            "risk_level": "HIGH" if tuning_update.get("risk_tightened") else "MEDIUM",
            "evidence_quality": sample_quality,
            "reason": str(tuning_update.get("application_reason") or ""),
            "baseline_config": baseline_config,
            "candidate_config": candidate_config,
            "candidate_reason": strategy_experiment.get("candidate_reason"),
            "strategy_experiment": strategy_experiment_payload,
            "parameter_diff_summary": parameter_diff_summary,
            "walk_forward_validation": validation,
            "walk_forward_run_ids": strategy_experiment.get("walk_forward_run_ids") if isinstance(strategy_experiment.get("walk_forward_run_ids"), dict) else {},
            "benchmark_comparison": benchmark_comparison,
            "kline_evidence_package": kline_evidence_package,
            "stability_evidence_package": stability_evidence_package,
            "evidence_package": evidence_package,
            "research_evidence_package": evidence_package.get("research_evidence_package") if isinstance(evidence_package.get("research_evidence_package"), dict) else {},
            "evidence_refs": evidence_links,
            "review_fields": [
                "strategy_experiment",
                "experiment_package_hash",
                "walk_forward_validation",
                "benchmark_comparison",
                "candidate_evidence_package",
                "stability_evidence_package",
                "parameter_diff_summary",
                "simulation_only",
                "is_real_trade",
            ],
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "expires_at": expires_at,
            "simulation_only": True,
            "is_real_trade": False,
        }

    def _merge_review_queue_state(
        self,
        current: Any,
        *,
        queue_item: Optional[Dict[str, Any]] = None,
        observation: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        state = _normalize_review_queue_state(current)
        items = [dict(item) for item in state.get("items", []) if isinstance(item, dict)]
        observations = [dict(item) for item in state.get("observations", []) if isinstance(item, dict)]
        if queue_item:
            key = str(queue_item.get("queue_item_id") or queue_item.get("id") or queue_item.get("experiment_id") or "")
            new_experiment_id = str(queue_item.get("experiment_id") or "")
            new_symbol = str(queue_item.get("symbol") or "")
            supersedable_statuses = {"READY_FOR_REVIEW", "BACKTEST_PENDING", "RECOMMENDED_ONLY"}

            def maybe_supersede(existing: Dict[str, Any]) -> Dict[str, Any]:
                existing_key = str(existing.get("queue_item_id") or existing.get("id") or existing.get("experiment_id") or "")
                existing_experiment_id = str(existing.get("experiment_id") or "")
                existing_symbol = str(existing.get("symbol") or "")
                existing_status = str(existing.get("candidate_status") or existing.get("promotion_status") or "").upper()
                if (
                    existing_key
                    and existing_key != key
                    and existing_experiment_id != new_experiment_id
                    and existing_symbol == new_symbol
                    and existing_status in supersedable_statuses
                ):
                    return {
                        **existing,
                        "candidate_status": "SUPERSEDED",
                        "promotion_status": "SUPERSEDED",
                        "lifecycle_status": "SUPERSEDED",
                        "review_allowed": False,
                        "review_decision": "CONTINUE_OBSERVING",
                        "superseded_by": key,
                        "updated_at": _now_iso(),
                        "simulation_only": True,
                        "is_real_trade": False,
                    }
                return existing

            items = [maybe_supersede(item) for item in items]
            observations = [maybe_supersede(item) for item in observations]
            items = [
                item for item in items
                if str(item.get("queue_item_id") or item.get("id") or item.get("experiment_id") or "") != key
            ]
            if queue_item.get("review_allowed"):
                items.append(queue_item)
            else:
                observations.append(queue_item)
        if observation:
            observations.append(observation)
        items = items[-REVIEW_QUEUE_ITEM_LIMIT:]
        observations = observations[-REVIEW_QUEUE_ITEM_LIMIT:]
        return {
            "version": 1,
            "updated_at": _now_iso(),
            "items": items,
            "observations": observations,
            "counts": {
                "ready_for_review": sum(1 for item in items if item.get("candidate_status") == "READY_FOR_REVIEW"),
                "backtest_pending": sum(1 for item in observations if item.get("candidate_status") == "BACKTEST_PENDING"),
                "recommended_only": sum(1 for item in observations if item.get("candidate_status") == "RECOMMENDED_ONLY"),
                "applied_to_simulation": sum(1 for item in items + observations if item.get("candidate_status") == "APPLIED_TO_SIMULATION"),
                "rejected": sum(1 for item in items + observations if item.get("candidate_status") == "REJECTED"),
                "superseded": sum(1 for item in items + observations if item.get("candidate_status") == "SUPERSEDED"),
                "expired": sum(1 for item in items + observations if item.get("candidate_status") == "EXPIRED"),
            },
            "simulation_only": True,
            "is_real_trade": False,
        }

    def _local_date_from_iso(self, value: str) -> str:
        if not value:
            return ""
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return ""
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(CHINA_TZ).date().isoformat()

    async def _tick_one(
        self,
        force: bool = False,
        *,
        symbol_override: Optional[str] = None,
        stock_name_override: Optional[str] = None,
        initial_cash_override: Optional[float] = None,
        touch_tick: bool = True,
        skip_tick_gate: bool = False,
    ) -> Dict[str, Any]:
        async with self._lock:
            config = self.get_config()
            if symbol_override:
                config = AutoPaperTradingConfig(**{
                    **_model_dump(config),
                    "symbol": symbol_override,
                    "stock_name": stock_name_override or config.stock_name or symbol_override,
                    "initial_cash": initial_cash_override if initial_cash_override is not None else config.initial_cash,
                })
            warnings: list[str] = []
            if not config.enabled and not force:
                return self._result("SKIPPED", "自动模拟交易未启用。", config, warnings=warnings)
            if not config.symbol:
                return self._result("BLOCKED", "请先设置股票代码。", config, warnings=warnings)
            if not force and not skip_tick_gate and _elapsed_seconds(config.last_tick_at) < config.tick_interval_seconds:
                return self._result("SKIPPED", "未到下一次自动跟进时间。", config, warnings=warnings)

            state = self._load_state()
            if touch_tick:
                state["last_tick_at"] = _now_iso()
            state["last_error"] = ""
            self._save_state(state)
            config = AutoPaperTradingConfig(**{
                **state,
                "symbol": config.symbol,
                "stock_name": config.stock_name,
                "initial_cash": config.initial_cash,
            })

            signal = await self._ensure_signal(config)
            portfolio, error = await signalops_store.create_paper_portfolio(signal["signal_id"], {
                "initial_cash": config.initial_cash,
                "risk_budget": {
                    "position_ratio_mode": "AI_DYNAMIC",
                    "auto_paper_trading": True,
                    "global_pool_cash": self.get_config().initial_cash,
                    "per_symbol_budget": config.initial_cash,
                },
                "created_by_agent": "auto_paper_trader",
            })
            if error:
                state["last_error"] = error
                self._save_state(state)
                return self._result("BLOCKED", error, AutoPaperTradingConfig(**state), warnings=warnings)

            market_snapshot = await self._fetch_market_snapshot(config, force)
            resolved_stock_name = _resolved_stock_name_from_market_snapshot(config.symbol, market_snapshot)
            if resolved_stock_name and _is_symbol_placeholder(config.symbol, config.stock_name):
                state = self._load_state()
                if _merge_stock_name_into_state(state, config.symbol, resolved_stock_name):
                    self._save_state(state)
                config = AutoPaperTradingConfig(**{
                    **_model_dump(config),
                    "stock_name": resolved_stock_name,
                })
                if _is_symbol_placeholder(signal.get("symbol") or config.symbol, signal.get("stock_name")):
                    signal = await signalops_store.update_signal_stock_name(signal["signal_id"], resolved_stock_name) or signal
            if market_snapshot.get("status") != "READY":
                warnings.append(market_snapshot.get("error") or "market_data_unavailable")
            else:
                quote = market_snapshot.get("quote") or {}
                mark_price = _clamp_float(quote.get("price"), 0.0, 0.0, 1_000_000_000.0)
                marked = await signalops_store.mark_paper_portfolio_to_market(signal["signal_id"], mark_price)
                if marked:
                    portfolio = marked
            synced = await signalops_store.sync_paper_portfolio_budget(signal["signal_id"], config.initial_cash, {
                "position_ratio_mode": "AI_DYNAMIC",
                "auto_paper_trading": True,
                "global_pool_cash": self.get_config().initial_cash,
                "per_symbol_budget": config.initial_cash,
            })
            if synced:
                portfolio = synced

            kline_snapshot = await asyncio.to_thread(self._fetch_kline_snapshot, config, force)
            module_evidence = self._build_module_evidence(config, portfolio, market_snapshot, kline_snapshot)
            llm_trace = await self._maybe_call_llm(
                config,
                portfolio,
                market_snapshot,
                kline_snapshot,
                module_evidence,
                warnings,
            )
            decision = self._decide(config, portfolio, market_snapshot, kline_snapshot, llm_trace, module_evidence)
            synced = await signalops_store.sync_paper_portfolio_budget(signal["signal_id"], config.initial_cash, {
                "position_ratio_mode": "AI_DYNAMIC",
                "ai_position_ratio": decision.get("positionRatio"),
                "position_ratio_source": decision.get("positionRatioSource"),
                "auto_paper_trading": True,
                "global_pool_cash": self.get_config().initial_cash,
                "per_symbol_budget": config.initial_cash,
            })
            if synced:
                portfolio = synced
            decision["decision_card"] = self._build_decision_card(
                config=config,
                decision=decision,
                portfolio_before=portfolio,
                portfolio_after=portfolio,
                order=None,
                warnings=warnings,
            )
            conditions = self._ai_conditions(config, decision, market_snapshot, kline_snapshot)
            signal = await signalops_store.update_signal_conditions(signal["signal_id"], {
                **conditions,
                "review_fields": ["auto_paper_trading", "ai_generated_conditions", "market_data", "llm_budget"],
            }) or signal
            lifecycle_warning = await self._advance_to_paper_test(signal)
            if lifecycle_warning:
                warnings.append(lifecycle_warning)
            order = await self._maybe_create_order(config, signal["signal_id"], portfolio, decision, force)
            if order and order.get("error"):
                warnings.append(f"order_error:{order['error']}")
            latest_portfolio = await signalops_store.get_paper_portfolio(signal["signal_id"]) or portfolio
            decision_card = self._build_decision_card(
                config=config,
                decision=decision,
                portfolio_before=portfolio,
                portfolio_after=latest_portfolio,
                order=order,
                warnings=warnings,
            )
            decision["decision_card"] = decision_card
            if order is not None:
                risk_constraints = order.get("risk_constraints") if isinstance(order.get("risk_constraints"), dict) else {}
                order["risk_constraints"] = {**risk_constraints, "decision_card": decision_card}
                order["decision_card"] = decision_card

            state = self._load_state()
            decision_tree_update = update_decision_tree_after_tick(
                decision_tree_state=state.get("decision_tree_state"),
                symbol=config.symbol,
                stock_name=config.stock_name,
                kline_snapshot=kline_snapshot,
                decision=decision,
                decision_card=decision_card,
                portfolio_before=portfolio,
                portfolio_after=latest_portfolio,
                order=order,
                warnings=warnings,
                config_snapshot={**state, "symbol": config.symbol, "stock_name": config.stock_name, "initial_cash": config.initial_cash},
            )
            state["decision_tree_state"] = decision_tree_update["state"]
            for item in decision_tree_update.get("warnings") or []:
                warnings.append(str(item))
            branch = decision_tree_update.get("branch") if isinstance(decision_tree_update.get("branch"), dict) else {}
            tree_summary = decision_tree_update.get("decision_tree_summary") if isinstance(decision_tree_update.get("decision_tree_summary"), dict) else {}
            if branch:
                decision["decision_tree_branch"] = branch
                decision["decision_tree_summary"] = tree_summary
            if tree_summary:
                decision["decision_tree_summary"] = tree_summary
            tuning = decision_tree_update.get("tuning") if isinstance(decision_tree_update.get("tuning"), dict) else {}
            applied_params = tuning.get("applied_parameters") if isinstance(tuning.get("applied_parameters"), dict) else {}
            for key, value in applied_params.items():
                state[key] = value
            closed_review = (
                decision_tree_update.get("closed_review")
                if isinstance(decision_tree_update.get("closed_review"), dict)
                else {}
            )
            if closed_review:
                knowledge_candidate = (
                    decision_tree_update.get("knowledge_candidate")
                    if isinstance(decision_tree_update.get("knowledge_candidate"), dict)
                    else {}
                )
                knowledge_item_id = ""
                if knowledge_candidate:
                    try:
                        from .knowledge_store import create_knowledge_item
                        from ..models.knowledge import CreateKnowledgeItemRequest

                        knowledge_item = create_knowledge_item(CreateKnowledgeItemRequest(**knowledge_candidate))
                        knowledge_item_id = knowledge_item.item_id
                    except Exception as exc:  # noqa: BLE001 - knowledge write must not break simulation.
                        warnings.append(f"decision_tree_knowledge_candidate_failed:{type(exc).__name__}")
                if knowledge_item_id:
                    closed_review = {**closed_review, "knowledge_item_id": knowledge_item_id}
                last_review = state.get("last_research_review") if isinstance(state.get("last_research_review"), dict) else {}
                existing_reviews = (
                    last_review.get("decision_tree_reviews")
                    if isinstance(last_review.get("decision_tree_reviews"), list)
                    else []
                )
                state["last_research_review"] = {
                    **last_review,
                    "status": last_review.get("status") or "DECISION_TREE_REVIEWED",
                    "message": last_review.get("message") or "SignalOps decision tree lifecycle review completed.",
                    "decision_tree_reviews": [*existing_reviews, closed_review][-10:],
                    "updated_at": _now_iso(),
                    "simulation_only": True,
                    "is_real_trade": False,
                }
                observation = {
                    "id": f"dt-{closed_review.get('review_id')}",
                    "queue_item_id": f"dt-{closed_review.get('review_id')}",
                    "symbol": config.symbol,
                    "title": f"SignalOps decision tree {config.symbol}",
                    "candidate_status": "APPLIED_TO_SIMULATION" if tuning.get("applied") else "RECOMMENDED_ONLY",
                    "promotion_status": "APPLIED_TO_SIMULATION" if tuning.get("applied") else "RECOMMENDED_ONLY",
                    "review_allowed": False,
                    "review_decision": "CONTINUE_OBSERVING",
                    "risk_level": "MEDIUM",
                    "evidence_quality": "MEDIUM" if closed_review.get("branch_count", 0) >= 3 else "LOW",
                    "reason": tuning.get("reason") or closed_review.get("end_context", {}).get("reason"),
                    "decision_tree_review": closed_review,
                    "decision_tree_tuning": tuning,
                    "knowledge_item_id": knowledge_item_id,
                    "source": "signalops_decision_tree",
                    "created_at": _now_iso(),
                    "updated_at": _now_iso(),
                    "simulation_only": True,
                    "is_real_trade": False,
                }
                state["review_queue_state"] = self._merge_review_queue_state(
                    state.get("review_queue_state"),
                    observation=observation,
                )

            decision_card = self._build_decision_card(
                config=AutoPaperTradingConfig(**{
                    **state,
                    "symbol": config.symbol,
                    "stock_name": config.stock_name,
                    "initial_cash": config.initial_cash,
                }),
                decision=decision,
                portfolio_before=portfolio,
                portfolio_after=latest_portfolio,
                order=order,
                warnings=warnings,
            )
            decision["decision_card"] = decision_card
            if order is not None:
                risk_constraints = order.get("risk_constraints") if isinstance(order.get("risk_constraints"), dict) else {}
                order["risk_constraints"] = {
                    **risk_constraints,
                    "decision_tree_branch": branch,
                    "decision_card": decision_card,
                }
                order["decision_card"] = decision_card
                if order.get("order_id") and not order.get("error"):
                    updated_order = await signalops_store.update_paper_order_risk_constraints(
                        signal["signal_id"],
                        str(order["order_id"]),
                        {
                            "decision_tree_branch": branch,
                            "decision_card": decision_card,
                        },
                    )
                    if updated_order:
                        order = updated_order
            portfolio_snapshot: Dict[str, Any] = {}
            try:
                latest_positions = await signalops_store.list_paper_positions(signal["signal_id"])
                portfolio_snapshot = await self._persist_signalops_portfolio_snapshot(
                    config=config,
                    signal_id=signal["signal_id"],
                    portfolio=latest_portfolio,
                    positions=latest_positions,
                    reason="auto_paper_tick",
                )
            except Exception as exc:  # noqa: BLE001 - snapshot persistence must not stop paper automation.
                warnings.append(f"signalops_portfolio_snapshot_failed:{type(exc).__name__}")
            signal_ids = state.get("signal_ids") if isinstance(state.get("signal_ids"), dict) else {}
            signal_ids[config.symbol] = signal["signal_id"]
            state["signal_ids"] = signal_ids
            state["signal_id"] = signal["signal_id"]
            if len(_parse_symbols(state.get("symbol", ""))) <= 1:
                state["stock_name"] = signal.get("stock_name") or config.stock_name
            state["last_decision"] = decision
            state["last_module_evidence"] = module_evidence
            if portfolio_snapshot:
                state["last_portfolio_snapshot"] = portfolio_snapshot
            state["last_error"] = ""
            if order and not order.get("error"):
                state["last_order_at"] = _now_iso()
                order_map = state.get("last_order_by_symbol") if isinstance(state.get("last_order_by_symbol"), dict) else {}
                order_map[config.symbol] = state["last_order_at"]
                state["last_order_by_symbol"] = order_map
            self._save_state(state)
            config = AutoPaperTradingConfig(**{
                **state,
                "symbol": config.symbol,
                "stock_name": config.stock_name,
                "initial_cash": config.initial_cash,
            })
            return {
                "status": "COMPLETED",
                "message": "自动模拟交易已完成一次跟进。",
                "symbol": signal.get("symbol") or config.symbol,
                "signal_id": signal["signal_id"],
                "config": config,
                "market_snapshot": market_snapshot,
                "kline_snapshot": kline_snapshot,
                "decision": decision,
                "decision_card": decision_card,
                "module_evidence": module_evidence,
                "portfolio_snapshot": portfolio_snapshot,
                "decision_tree_branch": branch,
                "decision_tree_review": closed_review,
                "order": order,
                "portfolio": latest_portfolio,
                "llm_trace": llm_trace,
                "warnings": warnings,
            }

    def start_background_loop(self) -> None:
        if self._task and not self._task.done():
            return
        self._loop_started_at = _now_iso()
        self._loop_heartbeat_at = self._loop_started_at
        self._loop_last_error = ""
        self._task = asyncio.create_task(self._run_loop())

    def stop_background_loop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None

    def _loop_health(self) -> str:
        if self._task is None:
            return "STOPPED"
        if self._task.cancelled():
            return "STOPPED"
        if self._task.done():
            try:
                exc = self._task.exception()
            except asyncio.CancelledError:
                return "STOPPED"
            if exc:
                self._loop_last_error = f"{type(exc).__name__}: {exc}"
                return "FAILED"
            return "STOPPED"
        return "RUNNING"

    async def _run_loop(self) -> None:
        while True:
            try:
                self._loop_heartbeat_at = _now_iso()
                config = self.get_config()
                if config.enabled:
                    await self.tick(force=False)
                await asyncio.sleep(max(5, min(config.tick_interval_seconds, 60)))
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - keep the loop alive and expose health.
                self._loop_last_error = f"{type(exc).__name__}: {exc}"
                await asyncio.sleep(30)

    async def _ensure_signal(self, config: AutoPaperTradingConfig) -> Dict[str, Any]:
        state = self._load_state()
        signal_ids = state.get("signal_ids") if isinstance(state.get("signal_ids"), dict) else {}
        candidate_id = signal_ids.get(config.symbol) or config.signal_id
        boundary = self._signal_boundary_context(config)
        if candidate_id:
            detail = await signalops_store.get_signal_detail(candidate_id)
            if detail and detail["signal"]["symbol"] == config.symbol:
                return detail["signal"]

        signal = await signalops_store.create_signal({
            "symbol": config.symbol,
            "stock_name": config.stock_name,
            "risk_passed": False,
            "dvg_passed": False,
            "qiam_passed": False,
            "execution_reachable": False,
            "trigger_conditions": [
                f"用户初始买入信号：{boundary['initial_buy_signal']}"
            ] if boundary["initial_buy_signal"] else [],
            "invalidation_conditions": [
                f"用户最终卖出信号：{boundary['final_sell_signal']}"
            ] if boundary["final_sell_signal"] else [],
            "review_fields": ["auto_paper_trading", "market_data", "llm_budget", "user_signal_boundary"],
            "metadata_json": {
                "source": "auto_paper_trading",
                "simulation_only": True,
                "is_real_trade": False,
                "automation_mode": "AI_FULLY_AUTONOMOUS",
                "user_signal_boundary": boundary,
                "execution_rules": self._execution_rules_context(config),
            },
        })
        state = self._load_state()
        signal_ids = state.get("signal_ids") if isinstance(state.get("signal_ids"), dict) else {}
        signal_ids[config.symbol] = signal["signal_id"]
        state["signal_ids"] = signal_ids
        state["signal_id"] = signal["signal_id"]
        self._save_state(state)
        return signal

    async def _fetch_market_snapshot(self, config: AutoPaperTradingConfig, force: bool) -> Dict[str, Any]:
        state = self._load_state()
        per_symbol = state.get("last_market_fetch_by_symbol") if isinstance(state.get("last_market_fetch_by_symbol"), dict) else {}
        fallback_at = config.last_market_fetch_at if len(_parse_symbols(state.get("symbol", ""))) <= 1 else ""
        last_fetch_at = per_symbol.get(config.symbol) or fallback_at
        if not force and _elapsed_seconds(last_fetch_at) < config.realtime_interval_seconds:
            return {"status": "SKIPPED", "message": "realtime interval not due"}
        fetched_at = _now_iso()
        state["last_market_fetch_at"] = fetched_at
        per_symbol[config.symbol] = fetched_at
        state["last_market_fetch_by_symbol"] = per_symbol
        self._save_state(state)
        profile = get_default_market_data_profile()
        result = await fetch_market_data(profile, config.symbol)
        return result.to_public_dict()

    def _fetch_kline_snapshot(self, config: AutoPaperTradingConfig, force: bool) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        state = self._load_state()
        daily_map = state.get("last_kline_fetch_by_symbol") if isinstance(state.get("last_kline_fetch_by_symbol"), dict) else {}
        weekly_map = state.get("last_weekly_monthly_fetch_by_symbol") if isinstance(state.get("last_weekly_monthly_fetch_by_symbol"), dict) else {}
        snapshot_map = state.get("last_kline_snapshot_by_symbol") if isinstance(state.get("last_kline_snapshot_by_symbol"), dict) else {}
        cached_snapshot = snapshot_map.get(config.symbol) if isinstance(snapshot_map.get(config.symbol), dict) else {}
        fallback_daily_at = config.last_kline_fetch_at if len(_parse_symbols(state.get("symbol", ""))) <= 1 else ""
        fallback_weekly_at = config.last_weekly_monthly_fetch_at if len(_parse_symbols(state.get("symbol", ""))) <= 1 else ""
        if force or _elapsed_seconds(daily_map.get(config.symbol) or fallback_daily_at) >= config.kline_interval_seconds:
            payload["daily"] = get_kline_payload(config.symbol, "daily", "3m")
            state = self._load_state()
            daily_at = _now_iso()
            state["last_kline_fetch_at"] = daily_at
            daily_map = state.get("last_kline_fetch_by_symbol") if isinstance(state.get("last_kline_fetch_by_symbol"), dict) else {}
            daily_map[config.symbol] = daily_at
            state["last_kline_fetch_by_symbol"] = daily_map
            self._save_state(state)
        if force or _elapsed_seconds(weekly_map.get(config.symbol) or fallback_weekly_at) >= config.weekly_monthly_interval_seconds:
            payload["weekly"] = get_kline_payload(config.symbol, "weekly", "3m")
            payload["monthly"] = get_kline_payload(config.symbol, "monthly", "3m")
            state = self._load_state()
            weekly_at = _now_iso()
            state["last_weekly_monthly_fetch_at"] = weekly_at
            weekly_map = state.get("last_weekly_monthly_fetch_by_symbol") if isinstance(state.get("last_weekly_monthly_fetch_by_symbol"), dict) else {}
            weekly_map[config.symbol] = weekly_at
            state["last_weekly_monthly_fetch_by_symbol"] = weekly_map
            self._save_state(state)
        if payload:
            state = self._load_state()
            snapshot_map = state.get("last_kline_snapshot_by_symbol") if isinstance(state.get("last_kline_snapshot_by_symbol"), dict) else {}
            cached_snapshot = snapshot_map.get(config.symbol) if isinstance(snapshot_map.get(config.symbol), dict) else {}
            merged_snapshot = {**cached_snapshot, **payload}
            snapshot_map[config.symbol] = merged_snapshot
            state["last_kline_snapshot_by_symbol"] = snapshot_map
            self._save_state(state)
            return merged_snapshot
        if cached_snapshot:
            return {
                **cached_snapshot,
                "cache_status": "CACHED",
                "message": "kline interval not due; reused last cached kline snapshot",
            }
        return {"status": "SKIPPED", "message": "kline interval not due"}

    def _build_module_evidence(
        self,
        config: AutoPaperTradingConfig,
        portfolio: Dict[str, Any],
        market_snapshot: Dict[str, Any],
        kline_snapshot: Dict[str, Any],
    ) -> Dict[str, Any]:
        warnings: list[str] = []
        payloads = kline_snapshot if isinstance(kline_snapshot, dict) else {}
        daily_payload = payloads.get("daily") if isinstance(payloads.get("daily"), dict) else payloads
        run_context: Dict[str, Any] = {
            "runId": f"SIGOPS_MODULES_{_now().strftime('%Y%m%d_%H%M%S')}",
            "stockCode": config.symbol,
            "stockName": config.stock_name,
            "taskType": "SignalOps automated simulation decision",
            "marketData": market_snapshot,
            "paperPortfolio": portfolio,
            "quantEngine": {"mode": "LOW_FREQ_MID_LONG"},
            "hasCalculationTools": True,
            "calculationToolStatus": "AVAILABLE",
            "dvg": {
                "qiamPermission": "ALLOW_WITH_DISCOUNT",
                "dataReliability": "MEDIUM",
                "scenarioPermission": "REVIEW_ONLY",
                "executionPermission": "ALLOW_WITH_DISCOUNT",
            },
            "risk": {},
            "atrade": {
                "t1Status": True,
                "priceLimitStatus": "NORMAL",
                "level2Available": False,
                "depthAvailable": False,
                "executionReachability": "CONDITIONALLY_REACHABLE",
                "liquidityRisk": "MEDIUM",
                "slippageLimit": 0.005,
                "participationLimit": 0.1,
            },
            "userPosition": {
                "plannedPeriod": "SignalOps paper automation",
                "maxAcceptableDrawdown": 0.08,
                "sellableBottomWarehouse": True,
            },
            "portfolio": {
                "allowAddPosition": _clamp_float(portfolio.get("available_cash"), 0.0, 0.0, 1_000_000_000.0) >= config.min_order_value,
                "paperOnly": True,
            },
            "execution": {"executionReachability": "CONDITIONALLY_REACHABLE"},
        }
        prior_outputs: Dict[str, Any] = {}

        dvg_result = self._safe_agent_call("dvg_evidence_gate", DvgEvidenceGateAgent(), run_context, prior_outputs, warnings)
        dvg = dvg_result.get("data") if isinstance(dvg_result.get("data"), dict) else {}
        dvg = {**dvg, "status": dvg_result.get("status"), "hard_stop": dvg_result.get("hard_stop", False)}
        run_context["dvg"] = {**run_context["dvg"], **dvg}
        prior_outputs["dvg_evidence_gate"] = dvg_result
        prior_outputs["dvg_gate"] = dvg_result

        risk_result = self._safe_agent_call("risk_firewall", RiskFirewallAgent(), run_context, prior_outputs, warnings)
        risk_firewall = risk_result.get("data") if isinstance(risk_result.get("data"), dict) else {}
        risk_firewall = {
            **risk_firewall,
            "status": risk_result.get("status"),
            "hard_stop": risk_result.get("hard_stop", False),
            "blockedActions": risk_result.get("blocked_actions") or [],
        }
        run_context["riskFirewall"] = risk_firewall
        prior_outputs["risk_firewall"] = risk_result

        atrade_result = self._safe_agent_call("trade_micro", ATradeAgent(), run_context, prior_outputs, warnings)
        trade_micro = atrade_result.get("data") if isinstance(atrade_result.get("data"), dict) else {}
        trade_micro = {
            **trade_micro,
            "status": atrade_result.get("status"),
            "blockedActions": atrade_result.get("blocked_actions") or [],
        }
        run_context["atrade"] = {**run_context["atrade"], **trade_micro}
        prior_outputs["trade_micro"] = atrade_result
        prior_outputs["atrade"] = atrade_result

        technical = self._safe_module_call("technical_kline", lambda: build_technical_kline_analysis(config.symbol, payloads), warnings)
        run_context["technicalKline"] = technical
        market_result = self._safe_agent_call("market_regime", MarketRegimeAgent(), run_context, prior_outputs, warnings)
        market = market_result.get("data") if isinstance(market_result.get("data"), dict) else {}
        run_context["market"] = market
        prior_outputs["market_regime"] = market_result
        market_technical = {
            "agent": "market_technical_analyst",
            "status": _combined_status_from_modules([market_result, technical]),
            "market": market,
            "technicalKline": technical,
            "alignment": self._market_technical_alignment(market, technical),
            "confidence": technical.get("confidence", 0.0) if isinstance(technical, dict) else 0.0,
            "summaryForDownstream": "SignalOps fused deterministic market and K-line context.",
            "warnings": warnings[:],
        }
        run_context["marketTechnical"] = market_technical
        prior_outputs["market_technical_analyst"] = {"data": market_technical, "status": market_technical["status"]}

        bottom = self._safe_module_call("mfe_mae_path_research", lambda: build_bottom_research_analysis(config.symbol, daily_payload), warnings)
        run_context["bottomResearch"] = bottom
        run_context["mfeMaeResearch"] = bottom
        prior_outputs["bottom_research"] = {"data": bottom, "status": bottom.get("status")}

        factor_result = self._safe_agent_call("factor_slicing", FactorSlicingAgent(), run_context, prior_outputs, warnings)
        factor = factor_result.get("data") if isinstance(factor_result.get("data"), dict) else {}
        run_context["factorSlicing"] = factor
        prior_outputs["factor_slicing"] = factor_result
        factor_engine_result = self._safe_agent_call("factor_engine", FactorEngineAgent(), run_context, prior_outputs, warnings)
        factor_engine = factor_engine_result.get("data") if isinstance(factor_engine_result.get("data"), dict) else {}
        run_context["factorEngine"] = factor_engine
        prior_outputs["factor_engine"] = factor_engine_result
        calculation_result = self._safe_agent_call("calculation_authority", CalculationAuthorityAgent(), run_context, prior_outputs, warnings)
        calculation = calculation_result.get("data") if isinstance(calculation_result.get("data"), dict) else {}
        run_context["calculationAuthority"] = calculation
        prior_outputs["calculation_authority"] = calculation_result
        qiam_result = self._safe_agent_call("qiam", QiamAgent(), run_context, prior_outputs, warnings)
        qiam = qiam_result.get("data") if isinstance(qiam_result.get("data"), dict) else {}
        run_context["qiam"] = qiam
        prior_outputs["qiam"] = qiam_result

        quant_core_result = self._safe_agent_call("quant_core", QuantCoreAgent(), run_context, prior_outputs, warnings)
        quant_core = quant_core_result.get("data") if isinstance(quant_core_result.get("data"), dict) else {}
        core_interpretation = quant_core.get("coreInterpretation") if isinstance(quant_core.get("coreInterpretation"), dict) else {}
        if not core_interpretation:
            core_interpretation = self._safe_module_call(
                "quant_core_interpretation",
                lambda: build_quant_core_interpretation(
                    run_context,
                    marketTechnical=market_technical,
                    bottomResearch=bottom,
                    factorSlicing=factor,
                    qiam=qiam,
                    scenario={"scenarioPermission": "REVIEW_ONLY", "dvgPermission": "REVIEW_ONLY"},
                    quantEngine=run_context["quantEngine"],
                ),
                warnings,
            )
            quant_core = {
                "agent": "quant_core",
                "status": core_interpretation.get("status"),
                "coreInterpretation": core_interpretation,
                "provenance": {"sourceNode": "quant_core_interpretation_fallback"},
            }
        run_context["quantCore"] = quant_core
        prior_outputs["quant_core"] = quant_core_result

        execution_result = self._safe_agent_call("execution", ExecutionAgent(), run_context, prior_outputs, warnings)
        execution = execution_result.get("data") if isinstance(execution_result.get("data"), dict) else {}
        execution = {
            **execution,
            "status": execution_result.get("status"),
            "blockedActions": execution_result.get("blocked_actions") or [],
        }
        run_context["execution"] = {**run_context["execution"], **execution}
        prior_outputs["execution"] = execution_result

        anti_result = self._safe_agent_call("anti_conclusion", AntiConclusionAgent(), run_context, prior_outputs, warnings)
        anti_conclusion = anti_result.get("data") if isinstance(anti_result.get("data"), dict) else {}
        run_context["antiConclusion"] = anti_conclusion
        prior_outputs["anti_conclusion"] = anti_result

        return {
            "version": "signalops_module_evidence_v1",
            "generated_at": _now_iso(),
            "symbol": config.symbol,
            "automation_modules": _automation_modules(config),
            "sequence": [
                "market_data",
                "dvg_evidence_gate",
                "risk_firewall",
                "trade_micro",
                "technical_kline",
                "mfe_mae_path_research",
                "factor_slicing",
                "factor_engine",
                "calculation_authority",
                "qiam",
                "quant_core",
                "quant_core_interpretation",
                "execution",
                "anti_conclusion",
                "signalops_llm_decision",
            ],
            "llm_policy": "SignalOps LLM may judge only after deterministic module evidence is computed.",
            "trade_boundary": {
                "simulation_only": True,
                "is_real_trade": False,
                "allowed_order_namespace": "SIM_*",
                "live_module_status": "CONFIGURED_DISABLED",
            },
            "dvg": _compact_module_payload(dvg, ["status", "quantEngineMode", "dataReliability", "qiamPermission", "scenarioPermission", "executionPermission", "allowedOutputLevel", "hardStop", "hallucinationRiskLevel"]),
            "riskFirewall": _compact_module_payload(risk_firewall, ["status", "hard_stop", "blockedActions", "complianceRedLines", "hardRisks", "liquidityRisks", "systemicRisks"]),
            "tradeMicro": _compact_module_payload(trade_micro, ["status", "blockedActions", "t1Status", "priceLimitStatus", "executionReachability", "liquidityRisk", "slippageLimit", "participationLimit"]),
            "market": _compact_module_payload(market, ["marketSentiment", "regimeClassification", "volatilityIndex", "liquidityIndex"]),
            "technicalKline": _compact_module_payload(technical, ["status", "technicalBias", "confidence", "dataQuality", "trend", "supportResistance", "summaryForDownstream"]),
            "mfeMaeResearch": _compact_module_payload(bottom, ["status", "regimeState", "mfeFavorableProbability", "maeBreachProbability", "riskPolicy", "trendSynthesis", "modelDiagnostics"]),
            "factorSlicing": _compact_module_payload(factor, ["mode", "quantEngineMode", "factorStability", "factorDataSource", "factorClusters", "missingFactorData"]),
            "factorEngine": _compact_module_payload(factor_engine, ["engineMode", "quantEngineMode", "factorCount", "factorStability", "validationEnabled"]),
            "calculationAuthority": _compact_module_payload(calculation, ["calculationToolStatus", "allowedCalculationTypes", "forbiddenCalculationTypes", "llmCalculationProhibited"]),
            "qiam": _compact_module_payload(qiam, ["quantEngineMode", "finalBuySuitability", "discountFactor", "probabilityBandUp", "probabilityBandSideways", "probabilityBandDown", "probabilitySource", "downgradeReasons"]),
            "quantCore": {
                "sourceNode": quant_core.get("agent") or "quant_core",
                "status": quant_core.get("status") or quant_core_result.get("status"),
                "coreInterpretation": _compact_module_payload(core_interpretation, ["version", "status", "overallScore", "overallBias", "confidence", "summary", "riskFlags", "actionBoundary", "quantEngineMode", "pathRiskFilter", "futureTrendProbability", "visualDecisionPanel"]),
                "provenance": _compact_module_payload(quant_core.get("provenance") if isinstance(quant_core.get("provenance"), dict) else {}, ["sourceNode", "simulation_only", "is_real_trade", "mergedNodes"]),
            },
            "execution": _compact_module_payload(execution, ["status", "blockedActions", "allowedActions", "prohibitedActions", "executionReachability", "batchPaths", "forbiddenActions"]),
            "antiConclusion": _compact_module_payload(anti_conclusion, ["status", "issues", "rewrite_required", "block_output"]),
            "warnings": _unique_text(warnings),
            "simulation_only": True,
            "is_real_trade": False,
        }

    def _safe_module_call(self, name: str, factory: Any, warnings: list[str]) -> Dict[str, Any]:
        try:
            value = factory()
            return value if isinstance(value, dict) else {}
        except Exception as exc:  # noqa: BLE001 - module evidence must not stop the automation loop.
            warnings.append(f"{name}_evidence_failed:{type(exc).__name__}")
            return {"status": "FAILED", "error": type(exc).__name__, "simulation_only": True, "is_real_trade": False}

    def _safe_agent_call(
        self,
        name: str,
        agent: Any,
        run_context: Dict[str, Any],
        prior_outputs: Dict[str, Any],
        warnings: list[str],
    ) -> Dict[str, Any]:
        try:
            result = agent.process(run_context, prior_outputs)
            return result.to_dict()
        except Exception as exc:  # noqa: BLE001 - module evidence must not stop the automation loop.
            warnings.append(f"{name}_evidence_failed:{type(exc).__name__}")
            return {"node": name, "status": "FAILED", "data": {"status": "FAILED", "error": type(exc).__name__}}

    def _market_technical_alignment(self, market: Dict[str, Any], technical: Dict[str, Any]) -> str:
        sentiment = str(market.get("marketSentiment") or "NEUTRAL").upper()
        bias = str(technical.get("technicalBias") or "UNKNOWN").upper()
        if bias == "INSUFFICIENT_DATA":
            return "TECHNICAL_INSUFFICIENT_DATA"
        if sentiment == "BULLISH" and bias == "BULLISH":
            return "ALIGNED_BULLISH"
        if sentiment == "BEARISH" and bias == "BEARISH":
            return "ALIGNED_BEARISH"
        if sentiment in {"BULLISH", "BEARISH"} and bias in {"BULLISH", "BEARISH"} and sentiment != bias:
            return "CONFLICT"
        return "NEUTRAL_OR_MIXED"

    async def _persist_signalops_portfolio_snapshot(
        self,
        *,
        config: AutoPaperTradingConfig,
        signal_id: str,
        portfolio: Dict[str, Any],
        positions: list[Dict[str, Any]],
        reason: str,
    ) -> Dict[str, Any]:
        valid_positions = [item for item in positions if isinstance(item, dict) and abs(_clamp_float(item.get("quantity"), 0.0, -1_000_000_000.0, 1_000_000_000.0)) > 0]
        if not valid_positions:
            return {}
        holdings: list[HoldingPosition] = []
        for item in valid_positions:
            quantity = _clamp_float(item.get("quantity"), 0.0, -1_000_000_000.0, 1_000_000_000.0)
            signed_value = _clamp_float(item.get("current_value"), 0.0, -1_000_000_000.0, 1_000_000_000.0)
            market_value = abs(signed_value)
            cost_price = abs(_clamp_float(item.get("virtual_cost"), 0.0, -1_000_000_000.0, 1_000_000_000.0))
            if cost_price <= 0 and abs(quantity) > 0:
                cost_price = market_value / abs(quantity) if market_value > 0 else 0.0
            holdings.append(
                HoldingPosition(
                    symbol=str(item.get("symbol") or config.symbol).upper(),
                    name=config.stock_name,
                    shares=abs(quantity),
                    availableShares=abs(quantity) if quantity > 0 else 0.0,
                    costPrice=cost_price,
                    marketValue=market_value,
                    pnl=_clamp_float(item.get("floating_pnl"), 0.0, -1_000_000_000.0, 1_000_000_000.0),
                    riskFactor="SIGNALOPS_SIMULATION",
                    raw={
                        **item,
                        "signal_id": signal_id,
                        "source": "signalops_auto_paper",
                        "snapshot_reason": reason,
                        "position_side": "SHORT" if quantity < 0 else "LONG",
                        "simulation_only": True,
                        "is_real_trade": False,
                    },
                )
            )
        cash = _clamp_float(portfolio.get("available_cash"), 0.0, 0.0, 1_000_000_000.0)
        stock_value = sum(item.marketValue for item in holdings)
        total_assets = max(
            _clamp_float(portfolio.get("initial_cash"), 0.0, 0.0, 1_000_000_000.0),
            cash + stock_value,
            stock_value,
        )
        snapshot = build_snapshot(
            holdings,
            [],
            source_type="SIGNALOPS_SIM",
            source_name=f"SignalOps paper portfolio {signal_id}",
            account_name="SignalOps paper sandbox",
            cash=cash,
            available_cash=cash,
            total_assets=total_assets,
        )
        saved = await save_snapshot(snapshot)
        return {
            "snapshotId": saved.snapshotId,
            "sourceType": saved.sourceType,
            "sourceName": saved.sourceName,
            "accountName": saved.accountName,
            "totalAssets": saved.totalAssets,
            "stockMarketValue": saved.stockMarketValue,
            "cash": saved.cash,
            "availableCash": saved.availableCash,
            "totalPositionRatio": saved.totalPositionRatio,
            "positionCount": saved.positionCount,
            "qualityStatus": saved.qualityStatus,
            "importedAt": saved.importedAt,
            "updatedAt": saved.updatedAt,
            "simulation_only": True,
            "is_real_trade": False,
        }

    async def _maybe_call_llm(
        self,
        config: AutoPaperTradingConfig,
        portfolio: Dict[str, Any],
        market_snapshot: Dict[str, Any],
        kline_snapshot: Dict[str, Any],
        module_evidence: Dict[str, Any],
        warnings: list[str],
    ) -> Optional[Dict[str, Any]]:
        self._reset_llm_budget_if_needed()
        config = AutoPaperTradingConfig(**{
            **_model_dump(self.get_config()),
            "symbol": config.symbol,
            "stock_name": config.stock_name,
        })
        if not config.use_llm or config.max_llm_calls_per_day <= 0:
            return None
        gate = _llm_gate(_model_dump(config))
        state = self._load_state()
        state["llm_gate_status"] = gate["status"]
        self._save_state(state)
        if not gate["allowed"]:
            warnings.append(f"llm_gate_{str(gate['status']).lower()}")
            return None
        if config.llm_calls_used_today >= config.max_llm_calls_per_day:
            warnings.append("llm_daily_budget_exhausted")
            return None
        if not gate["close_review"] and _elapsed_seconds(config.last_llm_at) < config.min_llm_interval_minutes * 60:
            return None

        run_data = {
            "runId": f"AUTO_PAPER_{_now().strftime('%Y%m%d_%H%M%S')}",
            "stockCode": config.symbol,
            "stockName": config.stock_name,
            "marketData": market_snapshot,
            "paperPortfolio": portfolio,
            "klineSnapshot": kline_snapshot,
            "moduleEvidence": module_evidence,
            "quantCore": module_evidence.get("quantCore") if isinstance(module_evidence, dict) else {},
            "researchTuning": self._research_tuning_context(config),
            "userSignalBoundary": self._signal_boundary_context(config),
            "executionRules": self._execution_rules_context(config),
            "signalOps": {"signalStatus": "PAPER_SANDBOX"},
            "finalContext": {
                "task": "First read deterministic moduleEvidence, including quant-core interpretation, QIAM, K-line, MFE/MAE, factor, and calculation-authority outputs. Then return only a SignalOps simulation decision. Human inputs are limited to symbol, initial buy signal, and final sell signal; AI must decide position sizing, buy, sell, T-trade, short, review, data cleaning, and knowledge tuning while obeying A-share T+1 and commission rules. Never propose real trading.",
                "allowedActions": sorted(SIM_ACTIONS),
                "deterministicModulesFirst": True,
            },
        }
        result = await run_agent_llm("signalops", run_data, {})
        if result.status == "COMPLETED":
            state = self._load_state()
            state["last_llm_at"] = _now_iso()
            state["llm_calls_used_today"] = int(state.get("llm_calls_used_today") or 0) + 1
            state["llm_budget_date"] = gate["date"]
            state["llm_gate_status"] = gate["status"]
            if gate["close_review"]:
                state["last_llm_close_call_date"] = gate["date"]
            self._save_state(state)
        else:
            warnings.append(f"llm_{result.status.lower()}: {result.error}")
        return result.to_public_dict()

    def _performance_quality_context(
        self,
        config: AutoPaperTradingConfig,
        symbol: str,
        factor_source: str,
        market_snapshot: Dict[str, Any],
        kline_snapshot: Dict[str, Any],
    ) -> Dict[str, Any]:
        stats = config.performance_stats if isinstance(config.performance_stats, dict) else {}
        symbols = stats.get("symbols") if isinstance(stats.get("symbols"), dict) else {}
        factors = stats.get("factors") if isinstance(stats.get("factors"), dict) else {}
        global_stats = stats.get("global") if isinstance(stats.get("global"), dict) else {}
        symbol_stats = symbols.get(symbol) if isinstance(symbols.get(symbol), dict) else {}
        factor_stats = factors.get(factor_source) if isinstance(factors.get(factor_source), dict) else {}
        fallback_stats = global_stats.get("all") if isinstance(global_stats.get("all"), dict) else {}
        primary_stats = factor_stats or symbol_stats or fallback_stats
        trade_count = _clamp_float(primary_stats.get("trade_count"), 0.0, 0.0, 1_000_000.0)
        confidence = _clamp_float(primary_stats.get("confidence"), 0.0, 0.0, 1.0)
        win_rate = _clamp_float(primary_stats.get("win_rate"), 0.0, 0.0, 1.0)
        expectancy = _clamp_float(primary_stats.get("expectancy"), 0.0, -1.0, 1.0)
        max_drawdown = _clamp_float(primary_stats.get("max_drawdown"), 0.0, -1.0, 0.0)
        market_status = str(market_snapshot.get("status") or "").upper()
        kline_statuses = {
            key: value.get("status")
            for key, value in kline_snapshot.items()
            if isinstance(value, dict)
        }
        quote = market_snapshot.get("quote") if isinstance(market_snapshot.get("quote"), dict) else {}
        kline_quality = evaluate_kline_signal_quality(
            symbol,
            kline_snapshot if isinstance(kline_snapshot, dict) else {},
            current_price=_clamp_float(quote.get("price"), 0.0, 0.0, 1_000_000_000.0),
        )
        strategy_stability_quality = evaluate_strategy_stability_quality(
            symbol,
            kline_snapshot if isinstance(kline_snapshot, dict) else {},
            kline_quality=kline_quality,
            performance_stats=primary_stats,
            current_price=_clamp_float(quote.get("price"), 0.0, 0.0, 1_000_000_000.0),
        )
        buy_threshold_delta = 0.0
        position_ratio_multiplier = 1.0
        action_policy = "ALLOW"
        reasons: list[str] = []
        quality_status = str(primary_stats.get("quality_status") or "UNOBSERVED")
        if trade_count < TUNING_MIN_TRADE_COUNT or confidence < TUNING_MIN_CONFIDENCE:
            quality_status = "LOW_SAMPLE"
            reasons.append("样本不足，仅观察")
        elif win_rate < 0.25 and expectancy < 0 and confidence >= 0.60:
            quality_status = "POOR"
            buy_threshold_delta = 0.35
            position_ratio_multiplier = 0.70
            action_policy = "HOLD"
            reasons.append("历史同类样本胜率和期望收益偏弱，模拟买入降级观察")
        elif win_rate < 0.35 or expectancy < -0.005 or max_drawdown <= -0.08:
            quality_status = "POOR"
            buy_threshold_delta = 0.25
            position_ratio_multiplier = 0.78
            reasons.append("历史同类样本偏弱，收紧模拟买入阈值和仓位")
        elif win_rate >= 0.55 and expectancy > 0.005 and max_drawdown > -0.08:
            quality_status = "HEALTHY"
            buy_threshold_delta = -0.10
            position_ratio_multiplier = 1.05
            reasons.append("历史同类样本质量较好，允许小幅放宽模拟参数")
        else:
            quality_status = quality_status if quality_status in {"WATCH", "HEALTHY", "POOR"} else "WATCH"
            reasons.append("历史同类样本保持观察")
        if market_status and market_status not in {"READY", "OK", "SUCCESS"}:
            buy_threshold_delta = max(buy_threshold_delta, 0.20)
            position_ratio_multiplier = min(position_ratio_multiplier, 0.85)
            reasons.append("行情数据质量不足，收紧模拟买入")
        kline_policy = str(kline_quality.get("action_policy") or kline_quality.get("actionPolicy") or "").upper()
        if kline_policy == "HOLD":
            action_policy = "HOLD"
            buy_threshold_delta = max(buy_threshold_delta, _clamp_float(kline_quality.get("buyThresholdDelta"), 0.30, 0.0, 1.0))
            position_ratio_multiplier = min(position_ratio_multiplier, 0.70)
            reasons.append("K线质量评分未通过，模拟买入降级观察")
        elif kline_policy in {"PROBE", "LADDER_BUY"}:
            buy_threshold_delta += _clamp_float(kline_quality.get("buyThresholdDelta"), 0.0, -0.5, 0.5)
            reasons.append(f"K线质量评分进入{str(kline_quality.get('ladder_stage') or kline_policy)}阶段")
        stability_policy = str(
            strategy_stability_quality.get("action_policy")
            or strategy_stability_quality.get("actionPolicy")
            or ""
        ).upper()
        if stability_policy == "HOLD":
            action_policy = "HOLD"
            buy_threshold_delta = max(
                buy_threshold_delta,
                _clamp_float(strategy_stability_quality.get("buyThresholdDelta"), 0.35, 0.0, 1.0),
            )
            position_ratio_multiplier = min(
                position_ratio_multiplier,
                _clamp_float(strategy_stability_quality.get("positionRatioMultiplier"), 0.0, 0.0, 1.0),
            )
            reasons.append("Strategy stability gate blocked simulated buy risk.")
        elif stability_policy == "REDUCE":
            buy_threshold_delta += _clamp_float(strategy_stability_quality.get("buyThresholdDelta"), 0.0, -0.5, 0.5)
            position_ratio_multiplier = min(
                position_ratio_multiplier,
                _clamp_float(strategy_stability_quality.get("positionRatioMultiplier"), 0.85, 0.0, 1.0),
            )
            reasons.append("Strategy stability gate reduced simulated position size.")
        sample_component = _clamp_float(trade_count / TUNING_MIN_TRADE_COUNT, 0.0, 0.0, 1.0)
        confidence_component = _clamp_float(confidence, 0.0, 0.0, 1.0)
        win_component = _clamp_float(win_rate, 0.0, 0.0, 1.0)
        expectancy_component = _clamp_float((expectancy + 0.04) / 0.10, 0.4, 0.0, 1.0)
        drawdown_component = _clamp_float(1.0 - abs(max_drawdown) / 0.12, 1.0, 0.0, 1.0)
        market_component = 1.0 if not market_status or market_status in {"READY", "OK", "SUCCESS"} else 0.45
        kline_raw_score = _clamp_float(kline_quality.get("final_score") or kline_quality.get("score"), 0.0, 0.0, 100.0)
        kline_component = kline_raw_score / 100
        score = round(
            100
            * (
                sample_component * 0.15
                + confidence_component * 0.15
                + win_component * 0.20
                + expectancy_component * 0.15
                + drawdown_component * 0.12
                + market_component * 0.08
                + kline_component * 0.15
            )
        )
        if action_policy == "HOLD":
            grade = "BLOCKED"
        elif trade_count < TUNING_MIN_TRADE_COUNT or confidence < TUNING_MIN_CONFIDENCE:
            grade = "WAIT"
        elif score >= 80:
            grade = "A"
        elif score >= 65:
            grade = "B"
        elif score >= 50:
            grade = "C"
        else:
            grade = "D"
        components = {
            "sample": round(sample_component, 4),
            "confidence": round(confidence_component, 4),
            "win_rate": round(win_component, 4),
            "expectancy": round(expectancy_component, 4),
            "drawdown": round(drawdown_component, 4),
            "market_data": round(market_component, 4),
            "kline_signal_quality": kline_quality,
            "strategy_stability_quality": strategy_stability_quality,
        }
        evidence_refs = [
            {
                "source_type": "PERFORMANCE_STATS",
                "source_id": f"factor:{factor_source}" if factor_stats else f"symbol:{symbol}" if symbol_stats else "global:all",
                "label": "SignalOps rolling pre-buy quality",
                "quality": quality_status,
            },
            {
                "source_type": "MARKET_DATA",
                "source_id": symbol,
                "label": f"market_status:{market_status or 'UNKNOWN'}",
                "quality": "MEDIUM" if market_component >= 1.0 else "LOW",
            },
        ]
        for period, status in kline_statuses.items():
            evidence_refs.append({
                "source_type": "KLINE",
                "source_id": f"{symbol}:{period}",
                "label": f"kline_status:{status}",
                "quality": "MEDIUM" if str(status).upper() in {"READY", "OK", "SUCCESS"} else "LOW",
            })
        evidence_refs.extend([
            item
            for item in kline_quality.get("evidence_refs", [])
            if isinstance(item, dict)
        ])
        return {
            "score": score,
            "grade": grade,
            "action_policy": action_policy,
            "components": components,
            "evidence_refs": evidence_refs,
            "status": quality_status,
            "actionPolicy": action_policy,
            "buyThresholdDelta": round(buy_threshold_delta, 4),
            "positionRatioMultiplier": round(position_ratio_multiplier, 4),
            "source": factor_source,
            "symbol": symbol,
            "metrics": primary_stats,
            "marketStatus": market_status or "UNKNOWN",
            "klineStatuses": kline_statuses,
            "kline_signal_quality": kline_quality,
            "klineStrategy": kline_quality.get("kline_strategy") if isinstance(kline_quality.get("kline_strategy"), dict) else {},
            "ladderBuyPolicy": kline_quality.get("ladder_buy_policy") if isinstance(kline_quality.get("ladder_buy_policy"), dict) else {},
            "strategy_stability_quality": strategy_stability_quality,
            "stabilityStrategy": strategy_stability_quality.get("stability_strategy") if isinstance(strategy_stability_quality.get("stability_strategy"), dict) else {},
            "metaLabelGate": strategy_stability_quality.get("meta_label_gate") if isinstance(strategy_stability_quality.get("meta_label_gate"), dict) else {},
            "volatilitySizingPolicy": strategy_stability_quality.get("volatility_sizing_policy") if isinstance(strategy_stability_quality.get("volatility_sizing_policy"), dict) else {},
            "reasons": reasons,
            "simulation_only": True,
            "is_real_trade": False,
        }

    def _decide(
        self,
        config: AutoPaperTradingConfig,
        portfolio: Dict[str, Any],
        market_snapshot: Dict[str, Any],
        kline_snapshot: Dict[str, Any],
        llm_trace: Optional[Dict[str, Any]],
        module_evidence: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        quote = market_snapshot.get("quote") or {}
        price = _clamp_float(quote.get("price"), 0.0, 0.0, 1_000_000_000.0)
        pct = _clamp_float(quote.get("changePercent"), 0.0, -100.0, 1000.0)
        available_cash = _clamp_float(portfolio.get("available_cash"), 0.0, 0.0, 1_000_000_000.0)
        market_value = _clamp_float(portfolio.get("market_value"), 0.0, -1_000_000_000.0, 1_000_000_000.0)
        total_assets = max(available_cash + market_value, 1.0)
        long_value = max(market_value, 0.0)
        short_value = abs(min(market_value, 0.0))
        position_ratio, position_ratio_source = self._ai_position_ratio(portfolio, market_snapshot, llm_trace, config)
        signal_boundary = self._signal_boundary_context(config)
        factor_adjustment = self._factor_adjustment_for(position_ratio_source, config)
        performance_quality = self._performance_quality_context(
            config,
            config.symbol,
            position_ratio_source,
            market_snapshot,
            kline_snapshot,
        )
        position_ratio = _clamp_float(
            position_ratio * _clamp_float(performance_quality.get("positionRatioMultiplier"), 1.0, 0.2, 1.3),
            position_ratio,
            0.0,
            0.85,
        )
        buy_threshold = _clamp_float(
            config.buy_change_threshold_pct
            + _clamp_float(factor_adjustment.get("buy_threshold_delta"), 0.0, -1.0, 1.0),
            config.buy_change_threshold_pct,
            0.1,
            5.0,
        )
        buy_threshold = _clamp_float(
            buy_threshold + _clamp_float(performance_quality.get("buyThresholdDelta"), 0.0, -1.0, 1.0),
            config.buy_change_threshold_pct,
            0.1,
            5.0,
        )
        kline_quality = (
            performance_quality.get("kline_signal_quality")
            if isinstance(performance_quality.get("kline_signal_quality"), dict)
            else performance_quality.get("components", {}).get("kline_signal_quality")
            if isinstance(performance_quality.get("components"), dict)
            else {}
        )
        components = performance_quality.get("components") if isinstance(performance_quality.get("components"), dict) else {}
        strategy_stability_quality = (
            performance_quality.get("strategy_stability_quality")
            if isinstance(performance_quality.get("strategy_stability_quality"), dict)
            else components.get("strategy_stability_quality")
            if isinstance(components.get("strategy_stability_quality"), dict)
            else {}
        )
        volatility_sizing_policy = (
            strategy_stability_quality.get("volatility_sizing_policy")
            if isinstance(strategy_stability_quality.get("volatility_sizing_policy"), dict)
            else {}
        )
        stability_max_position_ratio = _clamp_float(
            volatility_sizing_policy.get("max_position_ratio"),
            0.85,
            0.0,
            0.85,
        )
        if volatility_sizing_policy:
            position_ratio = min(position_ratio, stability_max_position_ratio)
        path_risk_summary = _module_path_risk_summary(module_evidence)
        path_risk_policy = str(path_risk_summary.get("riskPolicy") or "").upper()
        future_trend_probability = _module_future_trend_probability(module_evidence)
        future_policy_hint = str(future_trend_probability.get("signalopsPolicyHint") or "").upper()
        path_risk_throttled = False
        path_risk_avoid_new_buy = False
        path_risk_buy_blocked = False
        future_trend_review_required = False
        if path_risk_policy == "THROTTLE":
            throttled_ratio = min(position_ratio, 0.20)
            path_risk_throttled = throttled_ratio < position_ratio
            position_ratio = throttled_ratio
        elif path_risk_policy == "AVOID_NEW_BUY":
            path_risk_avoid_new_buy = True
        if future_policy_hint == "SIMULATION_REDUCE_OR_REVIEW_ONLY":
            reduced_ratio = min(position_ratio, 0.15)
            future_trend_review_required = reduced_ratio < position_ratio
            position_ratio = reduced_ratio
        elif future_policy_hint == "REVIEW_SIMULATION_ONLY_INSUFFICIENT_CALIBRATION":
            future_trend_review_required = True
        close_threshold = _clamp_float(
            config.close_change_threshold_pct
            + _clamp_float(factor_adjustment.get("invalidation_delta"), 0.0, -1.0, 1.0),
            config.close_change_threshold_pct,
            -5.0,
            -0.2,
        )

        action = "SIM_HOLD"
        reason = "自动沙箱判断：无足够价格或趋势优势，保持观察。"
        quantity = 0.0
        strategy_intent = "observe"
        ladder_policy = kline_quality.get("ladder_buy_policy") if isinstance(kline_quality.get("ladder_buy_policy"), dict) else {}
        ladder_target_ratio = _clamp_float(ladder_policy.get("target_position_ratio"), 0.0, 0.0, 0.50)
        ladder_step_ratio = _clamp_float(ladder_policy.get("max_step_position_ratio"), 0.20, 0.05, 0.20)
        if volatility_sizing_policy:
            ladder_target_ratio = min(ladder_target_ratio, stability_max_position_ratio)
            ladder_step_ratio = min(
                ladder_step_ratio,
                _clamp_float(volatility_sizing_policy.get("max_step_position_ratio"), ladder_step_ratio, 0.0, 0.20),
            )
        if ladder_target_ratio > 0:
            current_position_ratio = _clamp_float(long_value / total_assets if total_assets else 0.0, 0.0, 0.0, 1.0)
            if current_position_ratio <= 0:
                position_ratio = min(position_ratio, ladder_target_ratio)
            else:
                position_ratio = min(position_ratio, max(current_position_ratio, min(ladder_target_ratio, current_position_ratio + ladder_step_ratio)))
        target_value = min(available_cash, total_assets * position_ratio)
        kline_risk = kline_quality.get("risk_invalidation") if isinstance(kline_quality.get("risk_invalidation"), dict) else {}
        kline_invalidated = str(kline_risk.get("status") or "").upper() == "INVALIDATE"
        kline_policy = str(kline_quality.get("action_policy") or kline_quality.get("actionPolicy") or "").upper()
        kline_status = str(kline_quality.get("status") or "").upper()
        kline_data_blocked = (
            kline_policy == "HOLD"
            and (
                str(kline_risk.get("status") or "").upper() == "DATA_BLOCK"
                or kline_status in {"UNAVAILABLE", "FAILED", "SKIPPED"}
                or kline_status.startswith("INSUFFICIENT")
            )
        )
        if kline_invalidated and price > 0 and long_value > 0:
            action = "SIM_CLOSE"
            quantity = _board_lot_quantity(long_value / price)
            target_value = long_value
            strategy_intent = "kline_invalidation_close"
            reason = "K线质量评分触发失效条件，平掉模拟观察仓。"
        elif kline_invalidated:
            reason = "K线质量评分触发失效条件，停止新的模拟买入。"
            strategy_intent = "kline_invalidation_hold"
        elif price > 0 and long_value <= 0 and short_value <= 0 and pct >= buy_threshold and target_value >= config.min_order_value:
            action = "SIM_BUY"
            quantity = _board_lot_quantity(target_value / price)
            strategy_intent = "open_long"
            reason = "自动沙箱判断：实时涨幅转强且模拟仓无持仓，建立模拟观察仓。"
        elif price > 0 and long_value <= 0 and short_value <= 0 and pct <= close_threshold:
            short_target_value = min(total_assets * min(position_ratio, 0.35), total_assets * 0.35)
            if short_target_value >= config.min_order_value:
                action = "SIM_SHORT"
                quantity = _board_lot_quantity(short_target_value / price)
                target_value = short_target_value
                strategy_intent = "open_short"
                reason = "自动沙箱判断：实时跌幅触发模拟做空观察仓，仅记录 SIM_SHORT 沙箱敞口。"
        elif price > 0 and long_value > 0 and pct <= close_threshold:
            action = "SIM_CLOSE"
            quantity = _board_lot_quantity(long_value / price)
            target_value = long_value
            strategy_intent = "close_long"
            reason = "自动沙箱判断：实时跌幅触发模拟风控，平掉模拟观察仓。"
        elif price > 0 and long_value > 0 and pct >= max(buy_threshold + 0.8, 1.5):
            t_value = min(long_value * 0.35, total_assets * max(min(position_ratio, 0.35), 0.15))
            if t_value >= config.min_order_value:
                action = "SIM_T_SELL"
                quantity = _board_lot_quantity(t_value / price)
                target_value = t_value
                strategy_intent = "t_sell"
                reason = "自动沙箱判断：持仓标的快速拉升，卖出部分模拟仓做 T，保留底仓观察。"
        elif price > 0 and long_value > 0 and available_cash > 0 and close_threshold < pct <= buy_threshold:
            t_value = min(available_cash, total_assets * min(max(position_ratio * 0.5, 0.10), 0.25))
            if t_value >= config.min_order_value:
                action = "SIM_T_BUY"
                quantity = _board_lot_quantity(t_value / price)
                target_value = t_value
                strategy_intent = "t_buy"
                reason = "自动沙箱判断：持仓标的回落但未触发失效，买回部分模拟仓做 T。"
        elif price > 0 and short_value > 0 and pct >= buy_threshold:
            action = "SIM_COVER"
            quantity = _board_lot_quantity(short_value / price)
            target_value = short_value
            strategy_intent = "cover_short"
            reason = "自动沙箱判断：做空观察仓遇到反弹，回补 SIM_SHORT 沙箱敞口。"

        llm_action = self._llm_action(llm_trace)
        if llm_action:
            action = llm_action
            if action in {"SIM_BUY", "SIM_T_BUY"}:
                quantity = _board_lot_quantity(target_value / price) if price > 0 else 0
                strategy_intent = "llm_t_buy" if action == "SIM_T_BUY" else "llm_open_long"
            elif action in {"SIM_SELL", "SIM_CLOSE", "SIM_T_SELL"}:
                base_value = long_value * (0.35 if action == "SIM_T_SELL" else 1.0)
                quantity = _board_lot_quantity(base_value / price) if price > 0 else 0
                strategy_intent = "llm_t_sell" if action == "SIM_T_SELL" else "llm_reduce_long"
            elif action == "SIM_SHORT":
                short_target_value = total_assets * min(position_ratio, 0.35)
                quantity = _board_lot_quantity(short_target_value / price) if price > 0 else 0
                target_value = short_target_value
                strategy_intent = "llm_open_short"
            elif action == "SIM_COVER":
                quantity = _board_lot_quantity(short_value / price) if price > 0 else 0
                target_value = short_value
                strategy_intent = "llm_cover_short"
            elif action == "SIM_REBALANCE":
                desired_value = total_assets * position_ratio
                delta_value = desired_value - market_value
                if price > 0 and abs(delta_value) >= config.min_order_value:
                    action = "SIM_BUY" if delta_value > 0 else "SIM_SELL"
                    quantity = _board_lot_quantity(abs(delta_value) / price)
                    reason = f"LLM sandbox rebalance converted to {action}; only SIM_* paper orders are allowed."
                else:
                    action = "SIM_HOLD"
                    quantity = 0
                    reason = "LLM sandbox rebalance was below the minimum paper order threshold."
            elif action == "SIM_HOLD":
                quantity = 0
            reason = f"LLM 沙箱建议：{action}。自动系统仍只写入模拟订单。"

        if kline_invalidated and price > 0 and long_value > 0:
            action = "SIM_CLOSE"
            quantity = _board_lot_quantity(long_value / price)
            target_value = long_value
            strategy_intent = "kline_invalidation_close"
            reason = "K-line invalidation overrides LLM/rule output and closes the simulated long observation position."
        elif kline_invalidated:
            action = "SIM_HOLD"
            quantity = 0
            target_value = 0
            strategy_intent = "kline_invalidation_hold"
            reason = "K-line invalidation blocks new simulated risk; no simulated buy is allowed."
        elif path_risk_avoid_new_buy and action in {"SIM_BUY", "SIM_T_BUY"}:
            path_risk_buy_blocked = True
            action = "SIM_HOLD"
            quantity = 0
            target_value = 0
            strategy_intent = "quant_core_path_risk_hold"
            reason = "Quant Core MFE/MAE path risk is AVOID_NEW_BUY; SignalOps keeps the simulated account out of new buy risk."
        elif future_policy_hint == "SIMULATION_REDUCE_OR_REVIEW_ONLY" and action in {"SIM_BUY", "SIM_T_BUY"}:
            action = "SIM_HOLD"
            quantity = 0
            target_value = 0
            strategy_intent = "future_trend_probability_review"
            reason = "Calibrated future-trend probability favors downside; SignalOps keeps the simulated account in review-only mode."

        if action in {"SIM_BUY", "SIM_T_BUY"} and (
            performance_quality.get("action_policy") == "HOLD"
            or performance_quality.get("actionPolicy") == "HOLD"
        ):
            action = "SIM_HOLD"
            quantity = 0
            kline_policy = str(kline_quality.get("action_policy") or kline_quality.get("actionPolicy") or "").upper()
            if kline_policy == "HOLD":
                strategy_intent = "kline_quality_hold"
                reason = "AI paper trading held: K-line quality is below the simulated buy gate."
            else:
                strategy_intent = "performance_quality_hold"
                reason = "AI paper trading held: rolling SignalOps performance quality is below the simulated buy gate."
        if action == "SIM_HOLD" and strategy_intent == "observe" and long_value <= 0 and kline_data_blocked:
            strategy_intent = "kline_quality_hold"
            reason = "AI paper trading held: K-line data is unavailable or insufficient for the simulated buy gate."

        quantity = _board_lot_quantity(quantity)
        if action in {"SIM_BUY", "SIM_SELL", "SIM_CLOSE", "SIM_T_BUY", "SIM_T_SELL", "SIM_SHORT", "SIM_COVER"} and quantity <= 0:
            action = "SIM_HOLD"
            reason = "AI paper trading skipped: available size is below one 100-share board lot."
            strategy_intent = "below_board_lot"

        return {
            "action": action,
            "reason": reason,
            "price": price,
            "quantity": quantity,
            "changePercent": pct,
            "source": "llm_budgeted" if llm_action else "rules_with_market_data",
            "positionRatio": position_ratio,
            "positionRatioSource": position_ratio_source,
            "strategyIntent": strategy_intent,
            "buyChangeThresholdPct": buy_threshold,
            "closeChangeThresholdPct": close_threshold,
            "researchFactorAdjustment": factor_adjustment,
            "moduleEvidence": module_evidence or {},
            "quantCorePathRisk": path_risk_summary,
            "quantCorePathRiskPolicy": path_risk_policy,
            "quantCorePathRiskThrottled": path_risk_throttled,
            "quantCorePathRiskAvoidsNewBuy": path_risk_avoid_new_buy,
            "quantCorePathRiskBuyBlocked": path_risk_buy_blocked,
            "futureTrendProbability": future_trend_probability,
            "futureTrendReviewRequired": future_trend_review_required,
            "performanceQuality": performance_quality,
            "pre_buy_quality": performance_quality,
            "kline_signal_quality": kline_quality,
            "strategy_stability_quality": strategy_stability_quality,
            "klineStrategy": kline_quality.get("kline_strategy") if isinstance(kline_quality, dict) and isinstance(kline_quality.get("kline_strategy"), dict) else {},
            "ladderBuyPolicy": ladder_policy,
            "stabilityStrategy": strategy_stability_quality.get("stability_strategy") if isinstance(strategy_stability_quality.get("stability_strategy"), dict) else {},
            "metaLabelGate": strategy_stability_quality.get("meta_label_gate") if isinstance(strategy_stability_quality.get("meta_label_gate"), dict) else {},
            "volatilitySizingPolicy": volatility_sizing_policy,
            "userSignalBoundary": signal_boundary,
            "executionRules": self._execution_rules_context(config),
            "availableCashBeforeOrder": available_cash,
            "targetCashValue": target_value,
            "klineStatus": {key: value.get("status") for key, value in kline_snapshot.items() if isinstance(value, dict)},
            "simulation_only": True,
            "is_real_trade": False,
        }

    def _ai_position_ratio(
        self,
        portfolio: Dict[str, Any],
        market_snapshot: Dict[str, Any],
        llm_trace: Optional[Dict[str, Any]],
        config: Optional[AutoPaperTradingConfig] = None,
    ) -> tuple[float, str]:
        config = config or self.get_config()
        parsed = llm_trace.get("parsedJson") if isinstance(llm_trace, dict) else None
        if isinstance(parsed, dict):
            for key in ("positionRatio", "targetPositionRatio", "maxPositionRatio"):
                if key not in parsed:
                    continue
                value = _clamp_float(parsed.get(key), -1.0, -1.0, 100.0)
                if value >= 0:
                    if value > 1:
                        value = value / 100
                    return self._apply_factor_position_ratio(value, "llm_dynamic_position", config)

        quote = market_snapshot.get("quote") if isinstance(market_snapshot, dict) else {}
        quote = quote if isinstance(quote, dict) else {}
        pct = _clamp_float(quote.get("changePercent"), 0.0, -100.0, 1000.0)
        price = _clamp_float(quote.get("price"), 0.0, 0.0, 1_000_000_000.0)
        market_value = _clamp_float(portfolio.get("market_value"), 0.0, 0.0, 1_000_000_000.0)
        if price <= 0:
            return (0.0, "ai_dynamic_no_price")
        if market_value > 0:
            if pct <= config.close_change_threshold_pct:
                return (0.0, "ai_dynamic_risk_close")
            if pct < 0:
                return self._apply_factor_position_ratio(config.defensive_position_ratio, "ai_dynamic_defensive_hold", config)
            if pct >= 2.0:
                return self._apply_factor_position_ratio(config.strength_follow_position_ratio, "ai_dynamic_strength_follow", config)
            return self._apply_factor_position_ratio(config.existing_position_ratio, "ai_dynamic_existing_position", config)
        if pct >= 2.0:
            return self._apply_factor_position_ratio(config.breakout_position_ratio, "ai_dynamic_breakout", config)
        if pct >= 1.0:
            return self._apply_factor_position_ratio(config.positive_position_ratio, "ai_dynamic_positive", config)
        if pct >= config.buy_change_threshold_pct:
            return self._apply_factor_position_ratio(config.probe_position_ratio, "ai_dynamic_probe", config)
        return self._apply_factor_position_ratio(config.watch_position_ratio, "ai_dynamic_watch", config)

    def _factor_adjustment_for(self, source: str, config: AutoPaperTradingConfig) -> Dict[str, Any]:
        adjustments = config.factor_adjustments if isinstance(config.factor_adjustments, dict) else {}
        adjustment = adjustments.get(source)
        return adjustment if isinstance(adjustment, dict) else {}

    def _apply_factor_position_ratio(
        self,
        value: float,
        source: str,
        config: AutoPaperTradingConfig,
    ) -> tuple[float, str]:
        adjustment = self._factor_adjustment_for(source, config)
        delta = _clamp_float(adjustment.get("position_ratio_delta"), 0.0, -0.3, 0.3)
        return (_clamp_float(value + delta, value, 0.0, 0.85), source)

    def _research_tuning_context(self, config: AutoPaperTradingConfig) -> Dict[str, Any]:
        return {
            "adaptiveTuningEnabled": config.adaptive_tuning_enabled,
            "buyChangeThresholdPct": config.buy_change_threshold_pct,
            "closeChangeThresholdPct": config.close_change_threshold_pct,
            "factorAdjustments": config.factor_adjustments,
            "performanceStats": config.performance_stats,
            "lastResearchReviewDate": config.last_research_review_date,
            "lastResearchReview": config.last_research_review,
            "userSignalBoundary": self._signal_boundary_context(config),
            "executionRules": self._execution_rules_context(config),
        }

    def _signal_boundary_context(self, config: AutoPaperTradingConfig) -> Dict[str, Any]:
        initial_map = config.initial_buy_signals if isinstance(config.initial_buy_signals, dict) else {}
        final_map = config.final_sell_signals if isinstance(config.final_sell_signals, dict) else {}
        initial_signal = str(initial_map.get(config.symbol) or config.initial_buy_signal or "").strip()
        final_signal = str(final_map.get(config.symbol) or config.final_sell_signal or "").strip()
        return {
            "symbol": config.symbol,
            "initial_buy_signal": initial_signal,
            "final_sell_signal": final_signal,
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

    def _execution_rules_context(self, config: AutoPaperTradingConfig) -> Dict[str, Any]:
        return {
            "market": "A_SHARE_PAPER_SANDBOX",
            "board_lot_size": BOARD_LOT_SIZE,
            "t_plus_one_long_sell": True,
            "trading_sessions": ["09:30-11:30", "13:00-15:00"],
            "trading_calendar_source": "weekday_plus_AUTO_PAPER_CLOSED_TRADING_DATES",
            "price_limit_rule": "main_board_10pct_st_5pct_star_chinext_20pct_bse_30pct",
            "force_order_session_override_allowed": True,
            "commission_rate": config.commission_rate,
            "commission_min_fee": config.commission_min_fee,
            "commission_min_trade_value": config.commission_min_trade_value,
            "commission_rule": "fee is commission_min_fee when turnover is below commission_min_trade_value; otherwise turnover * commission_rate",
            "stamp_duty_rate": config.stamp_duty_rate,
            "stamp_duty_side": "sell_only",
            "simulation_only": True,
            "is_real_trade": False,
        }

    def _research_tuning_refs(self, config: AutoPaperTradingConfig, decision: Dict[str, Any]) -> list[Dict[str, Any]]:
        refs: list[Dict[str, Any]] = [
            {
                "source": "auto_paper_config",
                "adaptive_tuning_enabled": config.adaptive_tuning_enabled,
                "buy_change_threshold_pct": decision.get("buyChangeThresholdPct", config.buy_change_threshold_pct),
                "close_change_threshold_pct": decision.get("closeChangeThresholdPct", config.close_change_threshold_pct),
                "position_ratio": decision.get("positionRatio"),
                "position_ratio_source": decision.get("positionRatioSource"),
            }
        ]
        factor = decision.get("researchFactorAdjustment")
        if isinstance(factor, dict) and factor:
            refs.append({
                "source": "research_factor_adjustment",
                "position_ratio_source": decision.get("positionRatioSource"),
                **factor,
            })
        if config.last_research_review_date:
            refs.append({
                "source": "last_research_review",
                "date": config.last_research_review_date,
                "status": config.last_research_review.get("status") if isinstance(config.last_research_review, dict) else None,
                "iteration_id": config.last_research_review.get("iteration_id") if isinstance(config.last_research_review, dict) else None,
            })
        return refs

    def _build_decision_card(
        self,
        *,
        config: AutoPaperTradingConfig,
        decision: Dict[str, Any],
        portfolio_before: Optional[Dict[str, Any]],
        portfolio_after: Optional[Dict[str, Any]],
        order: Optional[Dict[str, Any]],
        warnings: list[str],
    ) -> Dict[str, Any]:
        before = _capital_snapshot(portfolio_before)
        after = _capital_snapshot(portfolio_after or portfolio_before)
        order = order or {}
        action = str(decision.get("action") or order.get("action") or "SIM_HOLD").upper()
        blockers = [str(item) for item in warnings if item]
        order_error = str(order.get("error") or "")
        if order_error:
            blockers.append(order_error)
        module_evidence = decision.get("moduleEvidence") if isinstance(decision.get("moduleEvidence"), dict) else {}
        quant_core_path_risk = (
            decision.get("quantCorePathRisk")
            if isinstance(decision.get("quantCorePathRisk"), dict)
            else _module_path_risk_summary(module_evidence)
        )
        future_trend_probability = (
            decision.get("futureTrendProbability")
            if isinstance(decision.get("futureTrendProbability"), dict)
            else _module_future_trend_probability(module_evidence)
        )
        if (
            (
                decision.get("quantCorePathRiskBuyBlocked")
                and action == "SIM_HOLD"
                and str(decision.get("strategyIntent") or "") == "quant_core_path_risk_hold"
            )
            or order_error == "quant_core_path_risk_buy_blocked"
        ):
            blockers.append("quant_core_path_risk_avoid_new_buy")
        elif decision.get("quantCorePathRiskThrottled"):
            blockers.append("quant_core_path_risk_throttle")
        if decision.get("futureTrendReviewRequired"):
            blockers.append("future_trend_probability_review")
        price = _clamp_float(
            order.get("simulated_price") or decision.get("price"),
            0.0,
            0.0,
            1_000_000_000.0,
        )
        quantity = _clamp_float(
            order.get("simulated_quantity") or decision.get("quantity"),
            0.0,
            0.0,
            1_000_000_000.0,
        )
        budget_used = price * quantity if action in SIM_ACTIONS and action != "SIM_HOLD" and not order.get("error") else 0.0
        risk_constraints = order.get("risk_constraints") if isinstance(order.get("risk_constraints"), dict) else {}
        fill = order.get("simulated_fill") if isinstance(order.get("simulated_fill"), dict) else {}
        pre_buy_quality = (
            decision.get("pre_buy_quality")
            if isinstance(decision.get("pre_buy_quality"), dict)
            else decision.get("performanceQuality")
            if isinstance(decision.get("performanceQuality"), dict)
            else _empty_pre_buy_quality(config.symbol)
        )
        components = pre_buy_quality.get("components") if isinstance(pre_buy_quality.get("components"), dict) else {}
        kline_quality = (
            decision.get("kline_signal_quality")
            if isinstance(decision.get("kline_signal_quality"), dict)
            else pre_buy_quality.get("kline_signal_quality")
            if isinstance(pre_buy_quality.get("kline_signal_quality"), dict)
            else components.get("kline_signal_quality")
            if isinstance(components.get("kline_signal_quality"), dict)
            else {}
        )
        strategy_stability_quality = (
            decision.get("strategy_stability_quality")
            if isinstance(decision.get("strategy_stability_quality"), dict)
            else pre_buy_quality.get("strategy_stability_quality")
            if isinstance(pre_buy_quality.get("strategy_stability_quality"), dict)
            else components.get("strategy_stability_quality")
            if isinstance(components.get("strategy_stability_quality"), dict)
            else {}
        )
        commission_fee = _clamp_float(
            risk_constraints.get("commission_fee"),
            _commission_amount(config, budget_used) if budget_used else 0.0,
            0.0,
            1_000_000_000.0,
        )
        stamp_duty_fee = _clamp_float(
            risk_constraints.get("stamp_duty_fee"),
            _stamp_duty_amount(config, action, budget_used) if budget_used else 0.0,
            0.0,
            1_000_000_000.0,
        )
        total_fee = _clamp_float(
            fill.get("fees") if "fees" in fill else risk_constraints.get("total_fee"),
            commission_fee + stamp_duty_fee,
            0.0,
            1_000_000_000.0,
        )
        return {
            "action": action,
            "reason": str(decision.get("reason") or order.get("action_reason") or ""),
            "capital_before": before["capital"],
            "capital_after": after["capital"],
            "cash_available": after["cash_available"],
            "position_value": after["position_value"],
            "budget_used": round(budget_used, 6),
            "commission_fee": round(commission_fee, 6),
            "stamp_duty_fee": round(stamp_duty_fee, 6),
            "total_fee": round(total_fee, 6),
            "blockers": blockers,
            "pre_buy_quality": pre_buy_quality,
            "kline_signal_quality": kline_quality,
            "strategy_stability_quality": strategy_stability_quality,
            "kline_strategy": kline_quality.get("kline_strategy") if isinstance(kline_quality.get("kline_strategy"), dict) else {},
            "ladder_buy_policy": kline_quality.get("ladder_buy_policy") if isinstance(kline_quality.get("ladder_buy_policy"), dict) else {},
            "stability_strategy": strategy_stability_quality.get("stability_strategy") if isinstance(strategy_stability_quality.get("stability_strategy"), dict) else {},
            "meta_label_gate": strategy_stability_quality.get("meta_label_gate") if isinstance(strategy_stability_quality.get("meta_label_gate"), dict) else {},
            "volatility_sizing_policy": strategy_stability_quality.get("volatility_sizing_policy") if isinstance(strategy_stability_quality.get("volatility_sizing_policy"), dict) else {},
            "quant_core_path_risk": quant_core_path_risk,
            "quant_core_path_risk_policy": decision.get("quantCorePathRiskPolicy") or quant_core_path_risk.get("riskPolicy"),
            "quant_core_path_risk_avoids_new_buy": bool(decision.get("quantCorePathRiskAvoidsNewBuy")),
            "future_trend_probability": future_trend_probability,
            "decision_tree": decision.get("decision_tree_summary") if isinstance(decision.get("decision_tree_summary"), dict) else {},
            "action_policy": pre_buy_quality.get("action_policy") or pre_buy_quality.get("actionPolicy") or "HOLD",
            "review_fields": [
                "pre_buy_quality",
                "kline_signal_quality",
                "strategy_stability_quality",
                "quant_core_path_risk",
                "future_trend_probability",
                "decision_tree",
                "ladder_buy_policy",
                "stability_strategy",
                "meta_label_gate",
                "volatility_sizing_policy",
                "research_tuning_refs",
                "capital_attribution",
                "execution_rules",
                "simulation_only",
                "is_real_trade",
            ],
            "research_tuning_refs": self._research_tuning_refs(config, decision),
            "capital_attribution": {
                "cash_before": before["cash_available"],
                "cash_after": after["cash_available"],
                "position_value_before": before["position_value"],
                "position_value_after": after["position_value"],
                "initial_cash": after["initial_cash"] or before["initial_cash"],
                "commission_fee": round(commission_fee, 6),
                "stamp_duty_fee": round(stamp_duty_fee, 6),
                "total_fee": round(total_fee, 6),
            },
            "simulation_only": True,
            "is_real_trade": False,
        }

    def _ai_conditions(
        self,
        config: AutoPaperTradingConfig,
        decision: Dict[str, Any],
        market_snapshot: Dict[str, Any],
        kline_snapshot: Dict[str, Any],
    ) -> Dict[str, list[str]]:
        action = str(decision.get("action") or "SIM_HOLD").upper()
        pct = _clamp_float(decision.get("changePercent"), 0.0, -100.0, 1000.0)
        price = _clamp_float(decision.get("price"), 0.0, 0.0, 1_000_000_000.0)
        source = str(decision.get("source") or "rules_with_market_data")
        market_status = str(market_snapshot.get("status") or "UNKNOWN")
        kline_status = ", ".join(
            f"{key}:{value.get('status')}"
            for key, value in kline_snapshot.items()
            if isinstance(value, dict) and value.get("status")
        ) or "kline_cached_or_skipped"
        boundary = self._signal_boundary_context(config)

        trigger_conditions = [
            f"AI decision: {action}",
            f"Realtime quote status: {market_status}, price={price}, change={pct}%",
            f"Decision source: {source}",
        ]
        if boundary["initial_buy_signal"]:
            trigger_conditions.append(f"User initial buy signal boundary: {boundary['initial_buy_signal']}")
        factor_adjustment = decision.get("researchFactorAdjustment")
        if isinstance(factor_adjustment, dict) and factor_adjustment:
            trigger_conditions.append(
                "Research Lab factor adjustment: "
                f"position_delta={factor_adjustment.get('position_ratio_delta', 0)}, "
                f"buy_threshold_delta={factor_adjustment.get('buy_threshold_delta', 0)}"
            )
        kline_quality = decision.get("kline_signal_quality") if isinstance(decision.get("kline_signal_quality"), dict) else {}
        if kline_quality:
            trigger_conditions.append(
                "Kline quality: "
                f"score={kline_quality.get('final_score', kline_quality.get('score', '-'))}, "
                f"policy={kline_quality.get('action_policy') or kline_quality.get('actionPolicy') or '-'}, "
                f"stage={kline_quality.get('ladder_stage') or '-'}"
            )
        if action in {"SIM_BUY", "SIM_T_BUY"}:
            trigger_conditions.append("AI judged the paper sandbox can open or add an observation position.")
        elif action in {"SIM_SELL", "SIM_CLOSE", "SIM_T_SELL"}:
            trigger_conditions.append("AI judged the paper sandbox should close the observation position.")
        elif action == "SIM_SHORT":
            trigger_conditions.append("AI judged the paper sandbox should open a simulated short observation position.")
        elif action == "SIM_COVER":
            trigger_conditions.append("AI judged the paper sandbox should cover a simulated short observation position.")
        else:
            trigger_conditions.append("AI judged no new paper risk is required on this tick.")

        invalidation_conditions = [
            "AI will re-evaluate invalidation on every automatic follow-up tick.",
            "Paper position can be closed when realtime weakness, data risk, or LLM evidence deteriorates.",
            f"Research Lab close threshold: change <= {decision.get('closeChangeThresholdPct', '-')}%.",
            f"Kline context: {kline_status}",
        ]
        if boundary["final_sell_signal"]:
            invalidation_conditions.append(f"User final sell signal boundary: {boundary['final_sell_signal']}")
        risk_invalidation = kline_quality.get("risk_invalidation") if isinstance(kline_quality.get("risk_invalidation"), dict) else {}
        for item in risk_invalidation.get("reasons", []) if isinstance(risk_invalidation.get("reasons"), list) else []:
            invalidation_conditions.append(f"Kline invalidation: {item}")
        return {
            "trigger_conditions": trigger_conditions,
            "invalidation_conditions": invalidation_conditions,
        }

    async def _advance_to_paper_test(self, signal: Dict[str, Any]) -> str:
        status = str(signal.get("status") or "IDEA").upper()
        try:
            current_index = LIFECYCLE_FLOW.index(status)
            paper_index = LIFECYCLE_FLOW.index("PAPER_TEST")
        except ValueError:
            return f"lifecycle_unknown_status:{status}"
        if current_index >= paper_index:
            return ""

        transition, error = await signalops_store.transition_signal(signal["signal_id"], {
            "target_status": "PAPER_TEST",
            "actor": "auto_paper_trader",
            "reason": "Auto paper trading entered AI paper sandbox lifecycle.",
            "gate_context": {"basic_analysis_completed": True},
        })
        if error:
            return f"lifecycle_transition_blocked:{error}"
        if transition and not transition.get("passed", False):
            return "lifecycle_transition_not_passed"
        return ""

    def _llm_action(self, llm_trace: Optional[Dict[str, Any]]) -> Optional[str]:
        if not llm_trace or llm_trace.get("status") != "COMPLETED":
            return None
        parsed = llm_trace.get("parsedJson")
        if not isinstance(parsed, dict):
            return None
        value = str(parsed.get("action") or parsed.get("paper_action") or parsed.get("finalAction") or "").upper()
        return value if value in SIM_ACTIONS else None

    async def _a_share_sellable_long_quantity(
        self,
        signal_id: str,
        symbol: str,
        price: float,
        portfolio: Dict[str, Any],
    ) -> Dict[str, Any]:
        positions = await signalops_store.list_paper_positions(signal_id)
        current_long_quantity = 0
        for item in positions:
            if item.get("symbol") != symbol:
                continue
            quantity = _clamp_float(item.get("quantity"), 0.0, -1_000_000_000.0, 1_000_000_000.0)
            if quantity > 0:
                current_long_quantity += _board_lot_quantity(quantity)
        if current_long_quantity <= 0 and price > 0:
            long_value = max(_clamp_float(portfolio.get("market_value"), 0.0, -1_000_000_000.0, 1_000_000_000.0), 0.0)
            current_long_quantity = _board_lot_quantity(long_value / price)

        local_today = _now().astimezone(CHINA_TZ).date().isoformat()
        today_buy_quantity = 0
        orders = await signalops_store.list_paper_orders(signal_id)
        for order in orders:
            if str(order.get("fill_status") or "").upper() != "FILLED":
                continue
            if str(order.get("action") or "").upper() not in {"SIM_BUY", "SIM_T_BUY"}:
                continue
            if self._local_date_from_iso(str(order.get("created_at") or "")) != local_today:
                continue
            fill = order.get("simulated_fill") if isinstance(order.get("simulated_fill"), dict) else {}
            quantity = fill.get("filled_quantity") or order.get("simulated_quantity")
            today_buy_quantity += _board_lot_quantity(quantity)

        sellable_quantity = _board_lot_quantity(max(current_long_quantity - today_buy_quantity, 0))
        return {
            "sellable_quantity": sellable_quantity,
            "current_long_quantity": current_long_quantity,
            "today_buy_quantity": today_buy_quantity,
            "local_trading_date": local_today,
        }

    async def _maybe_create_order(
        self,
        config: AutoPaperTradingConfig,
        signal_id: str,
        portfolio: Dict[str, Any],
        decision: Dict[str, Any],
        force: bool,
    ) -> Optional[Dict[str, Any]]:
        action = decision.get("action", "SIM_HOLD")
        if action not in SIM_ACTIONS:
            return None
        if action == "SIM_HOLD":
            return None
        state = self._load_state()
        order_map = state.get("last_order_by_symbol") if isinstance(state.get("last_order_by_symbol"), dict) else {}
        fallback_at = config.last_order_at if len(_parse_symbols(state.get("symbol", ""))) <= 1 else ""
        last_order_at = order_map.get(config.symbol) or fallback_at
        if not force and _elapsed_seconds(last_order_at) < config.min_order_interval_seconds:
            return None
        session_gate = _a_share_session_gate(force=force)
        if not session_gate["allowed"]:
            return {"error": "a_share_trading_session_closed", "rule_context": session_gate}
        price_limit = _a_share_price_limit_context(config, decision.get("changePercent"))
        if action in {"SIM_BUY", "SIM_T_BUY", "SIM_COVER"} and price_limit["at_limit_up"]:
            return {"error": "a_share_limit_up_buy_blocked", "rule_context": price_limit}
        if action in {"SIM_SELL", "SIM_CLOSE", "SIM_T_SELL", "SIM_SHORT"} and price_limit["at_limit_down"]:
            return {"error": "a_share_limit_down_sell_blocked", "rule_context": price_limit}
        if action in {"SIM_BUY", "SIM_T_BUY"}:
            kline_gate = _kline_buy_gate_context(decision)
            if kline_gate["blocked"]:
                return {"error": "kline_quality_buy_blocked", "rule_context": kline_gate}
            stability_gate = _strategy_stability_buy_gate_context(decision)
            if stability_gate["blocked"]:
                return {"error": "strategy_stability_buy_blocked", "rule_context": stability_gate}
            path_risk_gate = _quant_core_path_risk_buy_gate_context(decision)
            if path_risk_gate["blocked"]:
                return {"error": "quant_core_path_risk_buy_blocked", "rule_context": path_risk_gate}
        simulated_price = _clamp_float(decision.get("price"), 0.0, 0.0, 1_000_000_000.0)
        simulated_quantity = _board_lot_quantity(decision.get("quantity") or 0.0)
        if action in {"SIM_BUY", "SIM_SELL", "SIM_CLOSE", "SIM_T_BUY", "SIM_T_SELL", "SIM_SHORT", "SIM_COVER"}:
            if simulated_price <= 0:
                return {"error": "invalid_simulated_price"}
            if simulated_quantity <= 0:
                return {"error": "invalid_simulated_quantity"}
        if action in {"SIM_BUY", "SIM_T_BUY", "SIM_COVER"}:
            available_cash = _clamp_float(portfolio.get("available_cash"), 0.0, 0.0, 1_000_000_000.0)
            affordable_quantity = _affordable_board_lot_quantity(available_cash, simulated_price, config)
            if affordable_quantity <= 0:
                return {"error": "insufficient_simulated_cash"}
            simulated_quantity = min(simulated_quantity, affordable_quantity)
        if action == "SIM_SHORT":
            available_cash = _clamp_float(portfolio.get("available_cash"), 0.0, 0.0, 1_000_000_000.0)
            market_value = _clamp_float(portfolio.get("market_value"), 0.0, -1_000_000_000.0, 1_000_000_000.0)
            total_assets = max(available_cash + market_value, 1.0)
            max_short_quantity = _board_lot_quantity((total_assets * 0.35) / simulated_price) if simulated_price > 0 else 0
            if max_short_quantity <= 0:
                return {"error": "insufficient_simulated_margin"}
            simulated_quantity = min(simulated_quantity, max_short_quantity)
        if action in {"SIM_SELL", "SIM_CLOSE", "SIM_T_SELL"}:
            long_value = max(_clamp_float(portfolio.get("market_value"), 0.0, -1_000_000_000.0, 1_000_000_000.0), 0.0)
            available_quantity = _board_lot_quantity(long_value / simulated_price) if simulated_price > 0 else 0
            if available_quantity <= 0:
                return {"error": "no_long_position_to_reduce"}
            t_plus_one = await self._a_share_sellable_long_quantity(signal_id, config.symbol, simulated_price, portfolio)
            available_quantity = min(available_quantity, int(t_plus_one["sellable_quantity"]))
            if available_quantity <= 0:
                return {"error": "a_share_t_plus_one_blocked", "rule_context": t_plus_one}
            simulated_quantity = min(simulated_quantity, available_quantity)
        if action == "SIM_COVER":
            short_value = abs(min(_clamp_float(portfolio.get("market_value"), 0.0, -1_000_000_000.0, 1_000_000_000.0), 0.0))
            coverable_quantity = _board_lot_quantity(short_value / simulated_price) if simulated_price > 0 else 0
            if coverable_quantity <= 0:
                return {"error": "no_short_position_to_cover"}
            simulated_quantity = min(simulated_quantity, coverable_quantity)

        trade_amount = simulated_price * simulated_quantity
        commission_fee = _commission_amount(config, trade_amount)
        stamp_duty_fee = _stamp_duty_amount(config, action, trade_amount)
        total_fee = round(commission_fee + stamp_duty_fee, 6)
        execution_rules = self._execution_rules_context(config)
        order, error = await signalops_store.create_paper_order(signal_id, {
            "agent_id": "auto_paper_trader",
            "action": action,
            "action_reason": decision.get("reason", ""),
            "simulated_price": simulated_price,
            "simulated_quantity": simulated_quantity,
            "risk_constraints": {
                "simulation_only": True,
                "is_real_trade": False,
                "auto_paper_trading": True,
                "llm_budgeted": decision.get("source") == "llm_budgeted",
                "manual_command": decision.get("command"),
                "command_date": decision.get("commandDate"),
                "ai_position_ratio": decision.get("positionRatio"),
                "position_ratio_source": decision.get("positionRatioSource"),
                "buy_change_threshold_pct": decision.get("buyChangeThresholdPct"),
                "close_change_threshold_pct": decision.get("closeChangeThresholdPct"),
                "research_factor_adjustment": decision.get("researchFactorAdjustment"),
                "pre_buy_quality": decision.get("pre_buy_quality") or decision.get("performanceQuality"),
                "kline_signal_quality": decision.get("kline_signal_quality"),
                "strategy_stability_quality": decision.get("strategy_stability_quality"),
                "quant_core_path_risk": decision.get("quantCorePathRisk") or _module_path_risk_summary(decision.get("moduleEvidence")),
                "quant_core_path_risk_policy": decision.get("quantCorePathRiskPolicy"),
                "future_trend_probability": decision.get("futureTrendProbability") or _module_future_trend_probability(decision.get("moduleEvidence")),
                "decision_tree_branch": decision.get("decision_tree_branch"),
                "kline_strategy": decision.get("klineStrategy"),
                "ladder_buy_policy": decision.get("ladderBuyPolicy"),
                "stability_strategy": decision.get("stabilityStrategy"),
                "meta_label_gate": decision.get("metaLabelGate"),
                "volatility_sizing_policy": decision.get("volatilitySizingPolicy"),
                "user_signal_boundary": decision.get("userSignalBoundary"),
                "execution_rules": decision.get("executionRules") or execution_rules,
                "commission_rate": config.commission_rate,
                "commission_min_fee": config.commission_min_fee,
                "commission_min_trade_value": config.commission_min_trade_value,
                "commission_fee": commission_fee,
                "stamp_duty_rate": config.stamp_duty_rate,
                "stamp_duty_fee": stamp_duty_fee,
                "total_fee": total_fee,
                "a_share_session": session_gate,
                "a_share_price_limit": price_limit,
                "available_cash_before_order": decision.get("availableCashBeforeOrder"),
                "target_cash_value": decision.get("targetCashValue"),
                "strategy_intent": decision.get("strategyIntent"),
                "review_fields": [
                    "pre_buy_quality",
                    "kline_signal_quality",
                    "strategy_stability_quality",
                    "quant_core_path_risk",
                    "future_trend_probability",
                    "decision_tree_branch",
                    "ladder_buy_policy",
                    "stability_strategy",
                    "meta_label_gate",
                    "volatility_sizing_policy",
                    "research_factor_adjustment",
                    "user_signal_boundary",
                    "execution_rules",
                    "decision_card",
                    "simulation_only",
                    "is_real_trade",
                ],
                "decision_card": decision.get("decision_card"),
            },
            "data_snapshot_hash": f"AUTO:{config.symbol}:{_now().strftime('%Y%m%d%H%M%S')}",
        })
        if error or not order:
            return {"error": error or "order_failed"}
        if config.auto_fill:
            filled, fill_error = await signalops_store.fill_paper_order(signal_id, order["order_id"], {
                "filled_price": order["simulated_price"],
                "filled_quantity": order["simulated_quantity"],
                "fees": total_fee,
                "slippage": 0.0,
                "rule_checks": [
                    {"key": "simulation_only", "passed": True},
                    {"key": "auto_paper_trading", "passed": True},
                    {"key": "a_share_trading_session", "passed": True, "context": session_gate},
                    {"key": "a_share_price_limit", "passed": True, "context": price_limit},
                    {"key": "a_share_t_plus_one", "passed": True},
                    {"key": "commission_applied", "passed": commission_fee >= 0, "fee": commission_fee},
                    {"key": "stamp_duty_applied", "passed": stamp_duty_fee >= 0, "fee": stamp_duty_fee},
                ],
            })
            return filled or {"error": fill_error or "fill_failed", **order}
        return order

    def _close_price_from_positions(self, positions: list[Dict[str, Any]], symbol: str) -> float:
        for item in positions:
            if item.get("symbol") != symbol:
                continue
            quantity = _clamp_float(item.get("quantity"), 0.0, -1_000_000_000.0, 1_000_000_000.0)
            current_value = _clamp_float(item.get("current_value"), 0.0, -1_000_000_000.0, 1_000_000_000.0)
            if quantity != 0 and current_value != 0:
                return abs(current_value / quantity)
            cost = _clamp_float(item.get("virtual_cost"), 0.0, 0.0, 1_000_000_000.0)
            if cost > 0:
                return cost
        return 0.0

    def _remove_symbol_from_state(self, state: Dict[str, Any], symbol: str) -> Dict[str, Any]:
        symbols = _parse_symbols(str(state.get("symbol") or ""))
        names = [
            item.strip()
            for item in str(state.get("stock_name") or "").replace("；", ",").replace("，", ",").split(",")
            if item.strip()
        ]
        try:
            index = symbols.index(symbol)
        except ValueError:
            index = -1
        next_symbols = [item for item in symbols if item != symbol]
        if index >= 0 and index < len(names):
            next_names = [name for idx, name in enumerate(names) if idx != index]
        else:
            next_names = names

        state["symbol"] = ",".join(next_symbols)
        state["stock_name"] = ",".join(next_names)
        state["enabled"] = bool(next_symbols) and bool(state.get("enabled"))
        signal_ids = state.get("signal_ids") if isinstance(state.get("signal_ids"), dict) else {}
        signal_ids.pop(symbol, None)
        state["signal_ids"] = signal_ids
        for key in [
            "last_market_fetch_by_symbol",
            "last_kline_fetch_by_symbol",
            "last_weekly_monthly_fetch_by_symbol",
            "last_kline_snapshot_by_symbol",
            "last_order_by_symbol",
            "initial_buy_signals",
            "final_sell_signals",
        ]:
            mapping = state.get(key) if isinstance(state.get(key), dict) else {}
            mapping.pop(symbol, None)
            state[key] = mapping
        state["signal_id"] = signal_ids.get(next_symbols[0]) if next_symbols else None
        return state

    def _reset_llm_budget_if_needed(self) -> None:
        state = self._load_state()
        today = _now().astimezone(CHINA_TZ).date().isoformat()
        if state.get("llm_budget_date") != today:
            state["llm_budget_date"] = today
            state["llm_calls_used_today"] = 0
            self._save_state(state)

    def _exception_result(self, config: AutoPaperTradingConfig, exc: Exception) -> Dict[str, Any]:
        message = f"auto_paper_tick_failed:{type(exc).__name__}: {exc}"
        decision = {
            "action": "SIM_HOLD",
            "reason": message,
            "pre_buy_quality": _empty_pre_buy_quality(config.symbol, "tick_exception"),
            "simulation_only": True,
            "is_real_trade": False,
        }
        decision_card = self._build_decision_card(
            config=config,
            decision=decision,
            portfolio_before=None,
            portfolio_after=None,
            order=None,
            warnings=[message],
        )
        decision["decision_card"] = decision_card
        return {
            "status": "ERROR",
            "message": message,
            "symbol": config.symbol,
            "signal_id": config.signal_id,
            "config": config,
            "market_snapshot": {},
            "kline_snapshot": {},
            "decision": decision,
            "decision_card": decision_card,
            "order": None,
            "portfolio": None,
            "llm_trace": None,
            "warnings": [message],
        }

    def _jsonable(self, value: Any) -> Any:
        if hasattr(value, "model_dump"):
            return self._jsonable(value.model_dump())
        if isinstance(value, dict):
            return {str(key): self._jsonable(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._jsonable(item) for item in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    def _tick_result_summary(self, result: Dict[str, Any]) -> Dict[str, Any]:
        keys = [
            "status",
            "message",
            "symbol",
            "signal_id",
            "market_snapshot",
            "kline_snapshot",
            "decision",
            "decision_card",
            "module_evidence",
            "portfolio_snapshot",
            "decision_tree_branch",
            "decision_tree_review",
            "order",
            "portfolio",
            "llm_trace",
            "daily_review",
            "warnings",
        ]
        summary = {key: self._jsonable(result.get(key)) for key in keys if key in result}
        if result.get("results"):
            summary["results"] = [self._tick_result_summary(item) for item in result.get("results", [])]
        summary["updated_at"] = _now_iso()
        return summary

    def _remember_tick_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        state = self._load_state()
        summary = self._tick_result_summary(result)
        state["last_tick_result"] = summary
        if result.get("status") in {"ERROR", "PARTIAL", "BLOCKED"}:
            state["last_error"] = str(result.get("message") or "auto_paper_tick_failed")
        elif result.get("status") not in {"BLOCKED"}:
            state["last_error"] = ""
        if result.get("status") == "COMPLETED":
            state["last_success_at"] = summary["updated_at"]
        state["updated_at"] = _now_iso()
        self._save_state(state)
        result["config"] = AutoPaperTradingConfig(**state)
        try:
            pet_alert_center.report_auto_paper_tick(result)
        except Exception:  # noqa: BLE001 - pet alerts must never break paper trading.
            logger.exception("Failed to report auto paper pet alert")
        return result

    def _result(
        self,
        status: str,
        message: str,
        config: AutoPaperTradingConfig,
        *,
        warnings: list[str],
    ) -> Dict[str, Any]:
        decision = {
            "action": "SIM_HOLD",
            "reason": message,
            "pre_buy_quality": _empty_pre_buy_quality(config.symbol, "tick_not_evaluated"),
            "simulation_only": True,
            "is_real_trade": False,
        }
        decision_card = self._build_decision_card(
            config=config,
            decision=decision,
            portfolio_before=None,
            portfolio_after=None,
            order=None,
            warnings=warnings,
        )
        decision["decision_card"] = decision_card
        return {
            "status": status,
            "message": message,
            "config": config,
            "market_snapshot": {},
            "kline_snapshot": {},
            "decision": decision,
            "decision_card": decision_card,
            "order": None,
            "portfolio": None,
            "llm_trace": None,
            "warnings": warnings,
        }

    def _read_review_decision_events(
        self,
        *,
        limit: int = 100,
        include_total: bool = False,
    ) -> tuple[list[Dict[str, Any]], list[str], int]:
        event_file = _review_decision_event_file()
        if not event_file.exists():
            return [], [], 0
        warnings: list[str] = []
        events: list[Dict[str, Any]] = []
        try:
            lines = event_file.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            return [], [f"review_decision_event_read_failed: {exc}"], 0

        for index, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                warnings.append(f"review_decision_event_line_invalid:{index}")
                continue
            if isinstance(parsed, dict):
                events.append(parsed)
            else:
                warnings.append(f"review_decision_event_line_not_object:{index}")

        total_count = len(events) if include_total else 0
        bounded_limit = _clamp_int(limit, 100, 1, REVIEW_DECISION_EVENT_EXPORT_LIMIT)
        return events[-bounded_limit:], warnings[-10:], total_count

    def _build_review_decision_event(
        self,
        *,
        decision_record: Dict[str, Any],
        queue_item: Dict[str, Any],
        now: str,
    ) -> Dict[str, Any]:
        latest_events, _, _ = self._read_review_decision_events(limit=1, include_total=True)
        previous_event_hash = str(latest_events[-1].get("event_hash") or "") if latest_events else ""
        parameter_diff_summary = (
            decision_record.get("parameter_diff_summary")
            if isinstance(decision_record.get("parameter_diff_summary"), dict)
            else {}
        )
        event = {
            "schema": "signalops_review_decision_event_v1",
            "event_type": "SIGNALOPS_REVIEW_DECISION",
            "created_at": now,
            "decision_id": decision_record.get("decision_id"),
            "queue_item_id": decision_record.get("queue_item_id"),
            "experiment_id": decision_record.get("experiment_id"),
            "signal_id": decision_record.get("signal_id"),
            "symbol": decision_record.get("symbol"),
            "action": decision_record.get("action"),
            "result_status": decision_record.get("result_status"),
            "reviewer": decision_record.get("reviewer"),
            "reason": decision_record.get("reason"),
            "parameter_diff_checksum": decision_record.get("parameter_diff_checksum"),
            "parameter_diff_summary": parameter_diff_summary,
            "reviewed_parameter_count": decision_record.get("reviewed_parameter_count", 0),
            "reviewed_parameter_changed_count": decision_record.get("reviewed_parameter_changed_count", 0),
            "candidate_status_after": queue_item.get("candidate_status"),
            "review_decision_summary": decision_record.get("review_decision_summary", {}),
            "previous_event_hash": previous_event_hash,
            "append_only": True,
            "simulation_only": True,
            "is_real_trade": False,
        }
        event["event_hash"] = f"sigops-reviewevent-{_stable_json_hash(event, length=20)}"
        return event

    def _append_review_decision_event(self, event: Dict[str, Any]) -> None:
        event_file = _review_decision_event_file()
        event_file.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(event, ensure_ascii=False, sort_keys=True)
        with event_file.open("a", encoding="utf-8") as handle:
            handle.write(payload)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _load_state(self) -> Dict[str, Any]:
        default_state = _model_dump(AutoPaperTradingConfig(updated_at=_now_iso()))
        if STORAGE_FILE.exists():
            try:
                loaded = json.loads(STORAGE_FILE.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                warning = f"auto_paper_config_corrupted: {exc}"
                self._last_storage_warning = warning
                return {**default_state, "last_error": warning, "storage_warning": warning}
            except OSError as exc:
                warning = f"auto_paper_config_read_failed: {exc}"
                self._last_storage_warning = warning
                return {**default_state, "last_error": warning, "storage_warning": warning}
            if not isinstance(loaded, dict):
                warning = "auto_paper_config_corrupted: root value is not an object"
                self._last_storage_warning = warning
                return {**default_state, "last_error": warning, "storage_warning": warning}
            self._last_storage_warning = ""
            merged = {**default_state, **loaded, "storage_warning": loaded.get("storage_warning", "")}
            _normalize_automation_state(merged)
            merged["signal_ids"] = merged.get("signal_ids") if isinstance(merged.get("signal_ids"), dict) else {}
            merged["initial_buy_signals"] = _clean_symbol_text_map(merged.get("initial_buy_signals"))
            merged["final_sell_signals"] = _clean_symbol_text_map(merged.get("final_sell_signals"))
            if not isinstance(merged.get("cleaned_record_history"), list):
                merged["cleaned_record_history"] = []
            if not isinstance(merged.get("compressed_observation_history"), dict):
                merged["compressed_observation_history"] = {}
            if not isinstance(merged.get("last_module_evidence"), dict):
                merged["last_module_evidence"] = {}
            if not isinstance(merged.get("last_portfolio_snapshot"), dict):
                merged["last_portfolio_snapshot"] = {}
            raw_record_history = merged["cleaned_record_history"]
            observation_summary = _normalize_compressed_observation_history(merged.get("compressed_observation_history"))
            merged["compressed_observation_history"] = (
                _compress_observation_history(observation_summary, raw_record_history)
                if not int(observation_summary.get("total_count") or 0)
                else observation_summary
            )
            merged["cleaned_record_history"] = _capped_trade_record_history(raw_record_history)
            if not isinstance(merged.get("last_kline_snapshot_by_symbol"), dict):
                merged["last_kline_snapshot_by_symbol"] = {}
            merged["review_queue_state"] = _normalize_review_queue_state(merged.get("review_queue_state"))
            merged["review_decisions"] = _review_decision_record(merged.get("review_decisions"))
            merged["experiment_validation_state"] = _normalize_experiment_validation_state(merged.get("experiment_validation_state"))
            merged["random_validation_state"] = _normalize_random_validation_state(merged.get("random_validation_state"))
            merged["decision_tree_state"] = normalize_decision_tree_state(merged.get("decision_tree_state"))
            _sync_managed_symbol_pool(merged)
            return merged
        self._last_storage_warning = ""
        _normalize_automation_state(default_state)
        _sync_managed_symbol_pool(default_state)
        return default_state

    def _save_state(self, state: Dict[str, Any]) -> None:
        STORAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(state, ensure_ascii=False, indent=2)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f"{STORAGE_FILE.name}.",
            suffix=".tmp",
            dir=str(STORAGE_FILE.parent),
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            self._replace_state_file(tmp_name)
            self._last_storage_warning = ""
        except Exception:
            try:
                Path(tmp_name).unlink(missing_ok=True)
            finally:
                raise

    def _write_json_atomic(self, target: Path, payload: Dict[str, Any]) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=str(target.parent),
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(serialized)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, target)
        except Exception:
            try:
                Path(tmp_name).unlink(missing_ok=True)
            finally:
                raise

    def _replace_state_file(self, tmp_name: str) -> None:
        for attempt in range(6):
            try:
                os.replace(tmp_name, STORAGE_FILE)
                return
            except PermissionError:
                if attempt >= 5:
                    raise
                time_module.sleep(0.05 * (attempt + 1))


auto_paper_trading_store = AutoPaperTradingStore()
