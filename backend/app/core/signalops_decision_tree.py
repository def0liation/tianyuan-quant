from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


VERSION = 1
MIN_DOWNTREND_DAYS = 3
CONFIRM_REBOUND_DAYS = 2
NO_NEW_HIGH_END_DAYS = 2
MIN_EFFECTIVE_GAIN = 0.015
MIN_VALID_BRANCHES_FOR_TUNING = 3
CLOSED_TREE_LIMIT = 8
BRANCH_LIMIT = 80
TUNING_AUDIT_LIMIT = 20
THRESHOLD_TUNING_CAP = 0.05
POSITION_TUNING_CAP = 0.02
RATIO_FIELDS = [
    "watch_position_ratio",
    "probe_position_ratio",
    "positive_position_ratio",
    "breakout_position_ratio",
    "defensive_position_ratio",
    "existing_position_ratio",
    "strength_follow_position_ratio",
]
BUY_ACTIONS = {"SIM_BUY", "SIM_T_BUY"}
SELL_ACTIONS = {"SIM_SELL", "SIM_CLOSE", "SIM_T_SELL"}
EXECUTABLE_ACTIONS = BUY_ACTIONS | SELL_ACTIONS | {"SIM_SHORT", "SIM_COVER"}


def normalize_decision_tree_state(value: Any) -> Dict[str, Any]:
    state = value if isinstance(value, dict) else {}
    symbols = state.get("symbols") if isinstance(state.get("symbols"), dict) else {}
    return {
        "version": VERSION,
        "updated_at": str(state.get("updated_at") or ""),
        "symbols": {
            str(symbol): _normalize_symbol_state(symbol_state)
            for symbol, symbol_state in symbols.items()
            if str(symbol).strip()
        },
        "tuning_audit": [
            item for item in state.get("tuning_audit", []) if isinstance(item, dict)
        ][-TUNING_AUDIT_LIMIT:],
        "simulation_only": True,
        "is_real_trade": False,
    }


def compact_decision_tree_state(value: Any) -> Dict[str, Any]:
    state = normalize_decision_tree_state(value)
    compact_symbols: Dict[str, Any] = {}
    for symbol, symbol_state in state["symbols"].items():
        active = symbol_state.get("active_tree") if isinstance(symbol_state.get("active_tree"), dict) else {}
        closed = [item for item in symbol_state.get("closed_trees", []) if isinstance(item, dict)]
        latest_closed = closed[-1] if closed else {}
        compact_symbols[symbol] = {
            "status": symbol_state.get("status"),
            "candidate_low": symbol_state.get("candidate_low", {}),
            "last_context": symbol_state.get("last_context", {}),
            "last_review": _compact_review(symbol_state.get("last_review")),
            "last_tuning_audit": symbol_state.get("last_tuning_audit", {}),
            "active_tree": _compact_tree(active),
            "latest_closed_tree": _compact_tree(latest_closed),
            "closed_count": len(closed),
            "simulation_only": True,
            "is_real_trade": False,
        }
    return {
        **state,
        "symbols": compact_symbols,
        "tuning_audit": state.get("tuning_audit", [])[-5:],
    }


def update_decision_tree_after_tick(
    *,
    decision_tree_state: Any,
    symbol: str,
    stock_name: str = "",
    kline_snapshot: Dict[str, Any],
    decision: Dict[str, Any],
    decision_card: Dict[str, Any],
    portfolio_before: Optional[Dict[str, Any]],
    portfolio_after: Optional[Dict[str, Any]],
    order: Optional[Dict[str, Any]],
    warnings: List[str],
    config_snapshot: Dict[str, Any],
    now_iso: Optional[str] = None,
) -> Dict[str, Any]:
    now_iso = now_iso or _now_iso()
    symbol = str(symbol or "").strip()
    state = normalize_decision_tree_state(decision_tree_state)
    if not symbol:
        return {"state": state, "branch": {}, "active_tree": {}, "closed_review": {}, "tuning": {}, "warnings": ["missing_symbol"]}

    symbol_state = _normalize_symbol_state(state["symbols"].get(symbol))
    rows = _daily_rows(kline_snapshot)
    if len(rows) < 5:
        symbol_state["status"] = "DATA_INSUFFICIENT"
        symbol_state["last_context"] = _last_context(rows)
        _save_symbol_state(state, symbol, symbol_state, now_iso)
        return {
            "state": state,
            "branch": {},
            "active_tree": {},
            "closed_review": {},
            "tuning": {},
            "warnings": ["decision_tree_daily_kline_insufficient"],
        }

    active_tree = symbol_state.get("active_tree") if isinstance(symbol_state.get("active_tree"), dict) else {}
    if not active_tree:
        confirmed = _confirmed_bottom(rows)
        if not confirmed:
            symbol_state["status"] = "WAITING_FOR_CONFIRMED_LOW"
            symbol_state["candidate_low"] = _latest_candidate_low(rows)
            symbol_state["last_context"] = _last_context(rows)
            _save_symbol_state(state, symbol, symbol_state, now_iso)
            return {
                "state": state,
                "branch": {},
                "active_tree": {},
                "closed_review": {},
                "tuning": {},
                "warnings": ["decision_tree_low_not_confirmed"],
            }
        active_tree = _new_tree(symbol, stock_name, confirmed, rows, now_iso)

    active_tree = _refresh_tree(active_tree, rows, now_iso)
    branch = _build_branch(
        tree=active_tree,
        rows=rows,
        decision=decision,
        decision_card=decision_card,
        portfolio_before=portfolio_before,
        portfolio_after=portfolio_after,
        order=order,
        warnings=warnings,
        now_iso=now_iso,
    )
    branches = [
        item for item in active_tree.get("branches", []) if isinstance(item, dict)
    ][-BRANCH_LIMIT:]
    branches.append(branch)
    active_tree["branches"] = branches[-BRANCH_LIMIT:]
    active_tree["branch_count"] = len(active_tree["branches"])
    active_tree = _refresh_tree(active_tree, rows, now_iso)

    closed_review: Dict[str, Any] = {}
    tuning: Dict[str, Any] = {}
    knowledge_candidate: Dict[str, Any] = {}
    active_end = _end_context(active_tree)
    if active_end["ended"]:
        closed_review = _review_tree(active_tree, rows, active_end, now_iso)
        tuning = _build_tuning(config_snapshot, closed_review, now_iso)
        closed_tree = {
            **active_tree,
            "status": "CLOSED",
            "ended_at": now_iso,
            "end_context": active_end,
            "review": closed_review,
            "decision_tree_tuning": tuning,
            "simulation_only": True,
            "is_real_trade": False,
        }
        closed_trees = [item for item in symbol_state.get("closed_trees", []) if isinstance(item, dict)]
        closed_trees.append(closed_tree)
        symbol_state["closed_trees"] = closed_trees[-CLOSED_TREE_LIMIT:]
        symbol_state["active_tree"] = {}
        symbol_state["status"] = "CLOSED"
        symbol_state["last_review"] = closed_review
        symbol_state["last_tuning_audit"] = tuning
        knowledge_candidate = _knowledge_candidate_from_review(closed_review, tuning)
        if tuning.get("applied"):
            state["tuning_audit"] = [*state.get("tuning_audit", []), tuning][-TUNING_AUDIT_LIMIT:]
    else:
        symbol_state["active_tree"] = active_tree
        symbol_state["status"] = "ACTIVE"
        symbol_state["last_context"] = _last_context(rows)

    _save_symbol_state(state, symbol, symbol_state, now_iso)
    return {
        "state": state,
        "branch": branch,
        "active_tree": symbol_state.get("active_tree") or {},
        "closed_review": closed_review,
        "tuning": tuning,
        "knowledge_candidate": knowledge_candidate,
        "decision_tree_summary": _branch_tree_summary(symbol_state, active_tree, closed_review, tuning),
        "warnings": [],
    }


def _normalize_symbol_state(value: Any) -> Dict[str, Any]:
    item = value if isinstance(value, dict) else {}
    return {
        "status": str(item.get("status") or "WAITING_FOR_CONFIRMED_LOW"),
        "candidate_low": item.get("candidate_low") if isinstance(item.get("candidate_low"), dict) else {},
        "active_tree": item.get("active_tree") if isinstance(item.get("active_tree"), dict) else {},
        "closed_trees": [entry for entry in item.get("closed_trees", []) if isinstance(entry, dict)][-CLOSED_TREE_LIMIT:],
        "last_review": item.get("last_review") if isinstance(item.get("last_review"), dict) else {},
        "last_tuning_audit": item.get("last_tuning_audit") if isinstance(item.get("last_tuning_audit"), dict) else {},
        "last_context": item.get("last_context") if isinstance(item.get("last_context"), dict) else {},
        "simulation_only": True,
        "is_real_trade": False,
    }


def _save_symbol_state(state: Dict[str, Any], symbol: str, symbol_state: Dict[str, Any], now_iso: str) -> None:
    state["symbols"][symbol] = symbol_state
    state["updated_at"] = now_iso


def _daily_rows(kline_snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    payload = kline_snapshot.get("daily") if isinstance(kline_snapshot, dict) else None
    if not isinstance(payload, dict) and isinstance(kline_snapshot, dict) and isinstance(kline_snapshot.get("rows"), list):
        payload = kline_snapshot
    raw_rows = payload.get("rows") if isinstance(payload, dict) else []
    rows: List[Dict[str, Any]] = []
    for item in raw_rows if isinstance(raw_rows, list) else []:
        if not isinstance(item, dict):
            continue
        open_price = _to_float(item.get("open"))
        high = _to_float(item.get("high"))
        low = _to_float(item.get("low"))
        close = _to_float(item.get("close"))
        trade_date = str(item.get("tradeDate") or item.get("trade_date") or item.get("date") or "").strip()
        if None in (open_price, high, low, close) or not trade_date:
            continue
        rows.append({
            "trade_date": trade_date,
            "open": float(open_price),
            "high": float(high),
            "low": float(low),
            "close": float(close),
        })
    rows.sort(key=lambda row: str(row["trade_date"]))
    ma5_values = _moving_average([row["close"] for row in rows], 5)
    for index, row in enumerate(rows):
        row["ma5"] = ma5_values[index]
    return rows


def _confirmed_bottom(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if len(rows) < MIN_DOWNTREND_DAYS + CONFIRM_REBOUND_DAYS + 1:
        return {}
    for low_index in range(len(rows) - CONFIRM_REBOUND_DAYS - 1, MIN_DOWNTREND_DAYS - 1, -1):
        low_row = rows[low_index]
        down_rows = rows[low_index - MIN_DOWNTREND_DAYS:low_index + 1]
        confirm_rows = rows[low_index + 1:low_index + 1 + CONFIRM_REBOUND_DAYS]
        if len(confirm_rows) < CONFIRM_REBOUND_DAYS:
            continue
        closes_down = all(down_rows[pos]["close"] > down_rows[pos + 1]["close"] for pos in range(len(down_rows) - 1))
        lows_down = all(down_rows[pos]["low"] >= down_rows[pos + 1]["low"] for pos in range(len(down_rows) - 1))
        if not closes_down or not lows_down:
            continue
        if low_row["low"] != min(row["low"] for row in down_rows):
            continue
        if any(row["low"] < low_row["low"] for row in confirm_rows):
            continue
        if not all(row["close"] > low_row["close"] for row in confirm_rows):
            continue
        if confirm_rows[-1]["close"] < confirm_rows[0]["close"]:
            continue
        return _low_context(low_row, low_index, confirmed=True)
    return {}


def _latest_candidate_low(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {}
    latest_window = rows[-(MIN_DOWNTREND_DAYS + 1):]
    low_index = max(0, len(rows) - len(latest_window))
    min_pos = min(range(len(latest_window)), key=lambda pos: latest_window[pos]["low"])
    return _low_context(latest_window[min_pos], low_index + min_pos, confirmed=False)


def _low_context(row: Dict[str, Any], index: int, *, confirmed: bool) -> Dict[str, Any]:
    return {
        "date": row["trade_date"],
        "index": index,
        "low": round(row["low"], 6),
        "close": round(row["close"], 6),
        "confirmed": confirmed,
    }


def _new_tree(symbol: str, stock_name: str, bottom: Dict[str, Any], rows: List[Dict[str, Any]], now_iso: str) -> Dict[str, Any]:
    basis = {"symbol": symbol, "start_date": bottom.get("date"), "start_low": bottom.get("low")}
    tree = {
        "tree_id": f"SIGTREE_{_stable_hash(basis)[:12]}",
        "version": VERSION,
        "symbol": symbol,
        "stock_name": stock_name,
        "status": "ACTIVE",
        "created_at": now_iso,
        "updated_at": now_iso,
        "start": bottom,
        "branches": [],
        "branch_count": 0,
        "simulation_only": True,
        "is_real_trade": False,
    }
    return _refresh_tree(tree, rows, now_iso)


def _refresh_tree(tree: Dict[str, Any], rows: List[Dict[str, Any]], now_iso: str) -> Dict[str, Any]:
    start_date = str((tree.get("start") or {}).get("date") or "")
    scoped = [row for row in rows if str(row["trade_date"]) >= start_date] if start_date else rows
    if not scoped:
        scoped = rows[-1:]
    peak_index, peak_row = max(enumerate(scoped), key=lambda pair: pair[1]["high"])
    latest = scoped[-1]
    start_low = _to_float((tree.get("start") or {}).get("low")) or latest["low"]
    peak_gain_pct = _safe_ratio(peak_row["high"] - start_low, start_low)
    latest_gain_pct = _safe_ratio(latest["close"] - start_low, start_low)
    stagnant_days = max(0, len(scoped) - peak_index - 1)
    close_below_ma5 = latest.get("ma5") is not None and latest["close"] < latest["ma5"]
    tree.update({
        "updated_at": now_iso,
        "peak": {
            "date": peak_row["trade_date"],
            "price": round(peak_row["high"], 6),
            "gain_pct": _round_or_none(peak_gain_pct),
        },
        "current": {
            "date": latest["trade_date"],
            "open": round(latest["open"], 6),
            "high": round(latest["high"], 6),
            "low": round(latest["low"], 6),
            "close": round(latest["close"], 6),
            "ma5": _round_or_none(latest.get("ma5")),
            "latest_gain_pct": _round_or_none(latest_gain_pct),
            "close_below_ma5": close_below_ma5,
            "stagnant_days_after_peak": stagnant_days,
            "near_end": stagnant_days >= 1 and close_below_ma5,
        },
        "metrics": {
            "peak_gain_pct": _round_or_none(peak_gain_pct),
            "latest_gain_pct": _round_or_none(latest_gain_pct),
            "stagnant_days_after_peak": stagnant_days,
            "close_below_ma5": close_below_ma5,
            "ma5": _round_or_none(latest.get("ma5")),
        },
    })
    return tree


def _build_branch(
    *,
    tree: Dict[str, Any],
    rows: List[Dict[str, Any]],
    decision: Dict[str, Any],
    decision_card: Dict[str, Any],
    portfolio_before: Optional[Dict[str, Any]],
    portfolio_after: Optional[Dict[str, Any]],
    order: Optional[Dict[str, Any]],
    warnings: List[str],
    now_iso: str,
) -> Dict[str, Any]:
    latest = rows[-1]
    branches = [item for item in tree.get("branches", []) if isinstance(item, dict)]
    action = str(decision.get("action") or decision_card.get("action") or "SIM_HOLD").upper()
    order_summary = _order_summary(order)
    blockers = [str(item) for item in warnings if item]
    if order_summary.get("error"):
        blockers.append(str(order_summary["error"]))
    pre_buy_quality = decision.get("pre_buy_quality") if isinstance(decision.get("pre_buy_quality"), dict) else {}
    action_policy = decision_card.get("action_policy") or pre_buy_quality.get("action_policy") or pre_buy_quality.get("actionPolicy")
    branch = {
        "branch_id": f"{tree.get('tree_id')}:BR{len(branches) + 1:03d}",
        "tree_id": tree.get("tree_id"),
        "sequence": len(branches) + 1,
        "created_at": now_iso,
        "trade_date": latest["trade_date"],
        "action": action,
        "strategy_intent": str(decision.get("strategyIntent") or ""),
        "reason": str(decision.get("reason") or decision_card.get("reason") or ""),
        "source": str(decision.get("source") or ""),
        "price": _round_or_none(_to_float(decision.get("price")) or latest["close"]),
        "ma5": _round_or_none(latest.get("ma5")),
        "stage_low": tree.get("start", {}),
        "peak": tree.get("peak", {}),
        "current_return_pct": _round_or_none(_safe_ratio(latest["close"] - (_to_float((tree.get("start") or {}).get("low")) or latest["low"]), (_to_float((tree.get("start") or {}).get("low")) or latest["low"]))),
        "peak_return_pct": (tree.get("peak") or {}).get("gain_pct"),
        "portfolio_before": _portfolio_summary(portfolio_before),
        "portfolio_after": _portfolio_summary(portfolio_after),
        "order_summary": order_summary,
        "kline_signal_quality": decision.get("kline_signal_quality") if isinstance(decision.get("kline_signal_quality"), dict) else {},
        "strategy_stability_quality": decision.get("strategy_stability_quality") if isinstance(decision.get("strategy_stability_quality"), dict) else {},
        "blockers": blockers,
        "decision_snapshot": {
            "position_ratio": decision.get("positionRatio"),
            "position_ratio_source": decision.get("positionRatioSource"),
            "buy_change_threshold_pct": decision.get("buyChangeThresholdPct"),
            "close_change_threshold_pct": decision.get("closeChangeThresholdPct"),
            "action_policy": action_policy,
        },
        "simulation_only": True,
        "is_real_trade": False,
    }
    return branch


def _order_summary(order: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    order = order or {}
    fill = order.get("simulated_fill") if isinstance(order.get("simulated_fill"), dict) else {}
    return {
        "order_id": order.get("order_id"),
        "action": order.get("action"),
        "fill_status": order.get("fill_status"),
        "error": order.get("error"),
        "simulated_price": _round_or_none(order.get("simulated_price")),
        "simulated_quantity": _round_or_none(order.get("simulated_quantity")),
        "filled_price": _round_or_none(fill.get("filled_price")),
        "filled_quantity": _round_or_none(fill.get("filled_quantity")),
        "fees": _round_or_none(fill.get("fees")),
    }


def _portfolio_summary(portfolio: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    portfolio = portfolio or {}
    return {
        "available_cash": _round_or_none(portfolio.get("available_cash")),
        "market_value": _round_or_none(portfolio.get("market_value")),
        "initial_cash": _round_or_none(portfolio.get("initial_cash")),
        "max_drawdown": _round_or_none(portfolio.get("max_drawdown")),
    }


def _end_context(tree: Dict[str, Any]) -> Dict[str, Any]:
    current = tree.get("current") if isinstance(tree.get("current"), dict) else {}
    metrics = tree.get("metrics") if isinstance(tree.get("metrics"), dict) else {}
    stagnant_days = int(metrics.get("stagnant_days_after_peak") or 0)
    close_below_ma5 = bool(metrics.get("close_below_ma5"))
    ended = stagnant_days >= NO_NEW_HIGH_END_DAYS and close_below_ma5
    return {
        "ended": ended,
        "reason": "peak_gain_stalled_and_close_below_ma5" if ended else "active",
        "stagnant_days_after_peak": stagnant_days,
        "close_below_ma5": close_below_ma5,
        "current_date": current.get("date"),
        "current_close": current.get("close"),
        "ma5": current.get("ma5"),
        "simulation_only": True,
        "is_real_trade": False,
    }


def _review_tree(tree: Dict[str, Any], rows: List[Dict[str, Any]], end_context: Dict[str, Any], now_iso: str) -> Dict[str, Any]:
    branches = [item for item in tree.get("branches", []) if isinstance(item, dict)]
    branch_reviews = [_review_branch(branch, rows, tree) for branch in branches]
    counts = {
        "correct": sum(1 for item in branch_reviews if item["decision_correctness"] == "CORRECT"),
        "wrong": sum(1 for item in branch_reviews if item["decision_correctness"] == "WRONG"),
        "partial": sum(1 for item in branch_reviews if item["decision_correctness"] == "PARTIAL"),
        "skipped": sum(1 for item in branch_reviews if item["decision_correctness"] == "SKIPPED"),
    }
    review = {
        "review_id": f"SIGTREE_REVIEW_{_stable_hash({'tree_id': tree.get('tree_id'), 'ended_at': now_iso})[:12]}",
        "tree_id": tree.get("tree_id"),
        "symbol": tree.get("symbol"),
        "status": "COMPLETED",
        "created_at": now_iso,
        "start": tree.get("start", {}),
        "peak": tree.get("peak", {}),
        "end_context": end_context,
        "branch_count": len(branches),
        "branch_reviews": branch_reviews,
        "counts": counts,
        "correct_count": counts["correct"],
        "wrong_count": counts["wrong"],
        "partial_count": counts["partial"],
        "skipped_count": counts["skipped"],
        "review_fields": [
            "decision_correctness",
            "execution_quality",
            "data_quality",
            "decision_tree_tuning",
            "simulation_only",
            "is_real_trade",
        ],
        "simulation_only": True,
        "is_real_trade": False,
    }
    return review


def _review_branch(branch: Dict[str, Any], rows: List[Dict[str, Any]], tree: Dict[str, Any]) -> Dict[str, Any]:
    action = str(branch.get("action") or "SIM_HOLD").upper()
    branch_date = str(branch.get("trade_date") or "")
    branch_index = next((index for index, row in enumerate(rows) if str(row.get("trade_date")) == branch_date), len(rows) - 1)
    branch_price = _to_float(branch.get("price")) or rows[branch_index]["close"]
    future_rows = rows[branch_index + 1:] or rows[branch_index:]
    future_high = max((row["high"] for row in future_rows), default=branch_price)
    future_low = min((row["low"] for row in future_rows), default=branch_price)
    end_close = rows[-1]["close"]
    future_gain = _safe_ratio(future_high - branch_price, branch_price)
    future_drop = _safe_ratio(future_low - branch_price, branch_price)
    final_gain = _safe_ratio(end_close - branch_price, branch_price)
    blockers = [str(item) for item in branch.get("blockers", []) if item]
    data_quality = _branch_data_quality(branch)
    execution_quality = _branch_execution_quality(action, branch)
    if data_quality == "LOW":
        correctness = "SKIPPED"
        reason = "low_data_quality"
    elif action in BUY_ACTIONS:
        if blockers and not (branch.get("order_summary") or {}).get("order_id"):
            correctness = "SKIPPED"
            reason = "buy_blocked_before_execution"
        elif future_gain >= MIN_EFFECTIVE_GAIN:
            correctness = "CORRECT"
            reason = "buy_captured_effective_upside"
        elif final_gain < 0:
            correctness = "WRONG"
            reason = "buy_failed_before_ma5_lifecycle_end"
        else:
            correctness = "PARTIAL"
            reason = "buy_no_clear_edge"
    elif action == "SIM_HOLD":
        if blockers or future_gain < MIN_EFFECTIVE_GAIN:
            correctness = "CORRECT"
            reason = "hold_avoided_weak_or_blocked_branch"
        else:
            correctness = "WRONG"
            reason = "hold_missed_effective_upside"
    elif action in SELL_ACTIONS:
        if future_gain >= MIN_EFFECTIVE_GAIN:
            correctness = "WRONG"
            reason = "sell_before_later_effective_high"
        elif future_gain <= 0.005:
            correctness = "CORRECT"
            reason = "sell_before_lifecycle_breakdown"
        else:
            correctness = "PARTIAL"
            reason = "sell_edge_unclear"
    elif action == "SIM_SHORT":
        if future_drop <= -MIN_EFFECTIVE_GAIN:
            correctness = "CORRECT"
            reason = "short_captured_downside_observation"
        elif future_gain >= MIN_EFFECTIVE_GAIN:
            correctness = "WRONG"
            reason = "short_fought_effective_rebound"
        else:
            correctness = "PARTIAL"
            reason = "short_edge_unclear"
    elif action == "SIM_COVER":
        if future_gain >= MIN_EFFECTIVE_GAIN or future_drop > -0.005:
            correctness = "CORRECT"
            reason = "cover_avoided_rebound_or_no_more_downside"
        elif future_drop <= -MIN_EFFECTIVE_GAIN:
            correctness = "WRONG"
            reason = "cover_before_more_downside"
        else:
            correctness = "PARTIAL"
            reason = "cover_edge_unclear"
    else:
        correctness = "SKIPPED"
        reason = "unsupported_or_non_trade_action"
    return {
        "branch_id": branch.get("branch_id"),
        "trade_date": branch_date,
        "action": action,
        "decision_correctness": correctness,
        "execution_quality": execution_quality,
        "data_quality": data_quality,
        "reason": reason,
        "future_peak_gain_pct": _round_or_none(future_gain),
        "future_drawdown_pct": _round_or_none(future_drop),
        "final_gain_pct": _round_or_none(final_gain),
        "blockers": blockers,
        "simulation_only": True,
        "is_real_trade": False,
    }


def _branch_data_quality(branch: Dict[str, Any]) -> str:
    blockers = " ".join(str(item).lower() for item in branch.get("blockers", []))
    if branch.get("ma5") is None:
        return "LOW"
    if "market_data_unavailable" in blockers or "daily_kline_unavailable" in blockers:
        return "LOW"
    kline = branch.get("kline_signal_quality") if isinstance(branch.get("kline_signal_quality"), dict) else {}
    status = str(kline.get("status") or "").upper()
    if status in {"UNAVAILABLE", "FAILED", "INSUFFICIENT_DATA", "INSUFFICIENT_READY_EMPTY"}:
        return "LOW"
    return "MEDIUM"


def _branch_execution_quality(action: str, branch: Dict[str, Any]) -> str:
    order_summary = branch.get("order_summary") if isinstance(branch.get("order_summary"), dict) else {}
    if action == "SIM_HOLD":
        return "SKIPPED"
    if order_summary.get("error"):
        return "BLOCKED"
    if action in EXECUTABLE_ACTIONS and order_summary.get("fill_status") == "FILLED":
        return "OK"
    if action in EXECUTABLE_ACTIONS and order_summary.get("order_id"):
        return "PARTIAL"
    return "SKIPPED"


def _build_tuning(config: Dict[str, Any], review: Dict[str, Any], now_iso: str) -> Dict[str, Any]:
    branch_reviews = [item for item in review.get("branch_reviews", []) if isinstance(item, dict)]
    valid = [
        item for item in branch_reviews
        if item.get("decision_correctness") != "SKIPPED" and item.get("data_quality") != "LOW"
    ]
    before = _tunable_snapshot(config)
    after = dict(before)
    base = {
        "tuning_id": f"SIGTREE_TUNE_{_stable_hash({'review_id': review.get('review_id')})[:12]}",
        "source_tree_id": review.get("tree_id"),
        "review_id": review.get("review_id"),
        "created_at": now_iso,
        "before": before,
        "after": after,
        "applied": False,
        "applied_parameters": {},
        "reason": "",
        "branch_evidence": [
            {
                "branch_id": item.get("branch_id"),
                "action": item.get("action"),
                "decision_correctness": item.get("decision_correctness"),
                "reason": item.get("reason"),
            }
            for item in branch_reviews
        ],
        "simulation_only": True,
        "is_real_trade": False,
    }
    if len(valid) < MIN_VALID_BRANCHES_FOR_TUNING:
        return {**base, "reason": "insufficient_valid_decision_branches"}
    if all(str(item.get("action") or "").upper() == "SIM_HOLD" or item.get("execution_quality") == "BLOCKED" for item in valid):
        return {**base, "reason": "hold_or_blocked_only_sample"}

    wrong_buy = sum(1 for item in valid if item.get("action") in BUY_ACTIONS and item.get("decision_correctness") == "WRONG")
    correct_buy = sum(1 for item in valid if item.get("action") in BUY_ACTIONS and item.get("decision_correctness") == "CORRECT")
    missed_hold = sum(1 for item in valid if item.get("action") == "SIM_HOLD" and item.get("decision_correctness") == "WRONG")
    wrong_sell = sum(1 for item in valid if item.get("action") in SELL_ACTIONS and item.get("decision_correctness") == "WRONG")
    correct_sell = sum(1 for item in valid if item.get("action") in SELL_ACTIONS and item.get("decision_correctness") == "CORRECT")

    buy_delta = 0.0
    close_delta = 0.0
    ratio_delta = 0.0
    reasons: List[str] = []
    if wrong_buy > correct_buy:
        buy_delta += THRESHOLD_TUNING_CAP
        ratio_delta -= POSITION_TUNING_CAP
        reasons.append("tighten_after_wrong_buys")
    if missed_hold > 0 and wrong_buy <= correct_buy:
        buy_delta -= THRESHOLD_TUNING_CAP
        ratio_delta += POSITION_TUNING_CAP
        reasons.append("loosen_after_missed_hold_upside")
    if wrong_sell > correct_sell:
        close_delta -= THRESHOLD_TUNING_CAP
        reasons.append("delay_close_after_early_sells")

    if not reasons:
        return {**base, "reason": "no_directional_tuning_signal"}

    after["buy_change_threshold_pct"] = round(_clamp(before["buy_change_threshold_pct"] + buy_delta, 0.1, 5.0), 4)
    after["close_change_threshold_pct"] = round(_clamp(before["close_change_threshold_pct"] + close_delta, -5.0, -0.2), 4)
    for field in RATIO_FIELDS:
        after[field] = round(_clamp(before[field] + ratio_delta, 0.0, 0.85), 4)
    applied = {
        key: value
        for key, value in after.items()
        if abs(float(value) - float(before.get(key, value))) >= 0.000001
    }
    return {
        **base,
        "after": after,
        "applied": bool(applied),
        "applied_parameters": applied,
        "reason": ",".join(reasons),
        "review_counts": review.get("counts", {}),
    }


def _knowledge_candidate_from_review(review: Dict[str, Any], tuning: Dict[str, Any]) -> Dict[str, Any]:
    if not review:
        return {}
    tree_id = str(review.get("tree_id") or "")
    symbol = str(review.get("symbol") or "")
    counts = review.get("counts") if isinstance(review.get("counts"), dict) else {}
    start = review.get("start") if isinstance(review.get("start"), dict) else {}
    peak = review.get("peak") if isinstance(review.get("peak"), dict) else {}
    end_context = review.get("end_context") if isinstance(review.get("end_context"), dict) else {}
    return {
        "category": "SIGNALOPS_DECISION_TREE",
        "title": f"SignalOps decision tree review {symbol} {tree_id}",
        "thesis": (
            f"Decision tree {tree_id} closed after peak gain stalled and close fell below MA5; "
            f"correct={counts.get('correct', 0)}, wrong={counts.get('wrong', 0)}, partial={counts.get('partial', 0)}."
        ),
        "evidence": [
            f"tree_id={tree_id}",
            f"symbol={symbol}",
            f"start={start.get('date')} low={start.get('low')}",
            f"peak={peak.get('date')} price={peak.get('price')} gain={peak.get('gain_pct')}",
            f"end={end_context.get('current_date')} close={end_context.get('current_close')} ma5={end_context.get('ma5')}",
            f"tuning_applied={bool(tuning.get('applied'))} reason={tuning.get('reason')}",
        ],
        "decision_impact": "Use this candidate to refine SignalOps simulated thresholds and position sizing only.",
        "guardrail_notes": [
            "Simulation-only evidence; never creates real brokerage orders.",
            "Does not bypass K-line, stability, A-share T+1, limit, fee, or board-lot gates.",
        ],
        "tags": ["signalops", "decision-tree", "auto-paper", "simulation-only"],
        "confidence": "MEDIUM" if int(counts.get("correct", 0) or 0) + int(counts.get("wrong", 0) or 0) >= 3 else "LOW",
    }


def _tunable_snapshot(config: Dict[str, Any]) -> Dict[str, float]:
    snapshot = {
        "buy_change_threshold_pct": _clamp(_to_float(config.get("buy_change_threshold_pct")) or 0.5, 0.1, 5.0),
        "close_change_threshold_pct": _clamp(_to_float(config.get("close_change_threshold_pct")) or -2.0, -5.0, -0.2),
    }
    for field in RATIO_FIELDS:
        snapshot[field] = _clamp(_to_float(config.get(field)) or 0.0, 0.0, 0.85)
    return snapshot


def _branch_tree_summary(symbol_state: Dict[str, Any], active_tree: Dict[str, Any], review: Dict[str, Any], tuning: Dict[str, Any]) -> Dict[str, Any]:
    tree = symbol_state.get("active_tree") if isinstance(symbol_state.get("active_tree"), dict) and symbol_state.get("active_tree") else active_tree
    return {
        "status": symbol_state.get("status"),
        "tree_id": tree.get("tree_id"),
        "start": tree.get("start", {}),
        "peak": tree.get("peak", {}),
        "current": tree.get("current", {}),
        "branch_count": tree.get("branch_count", 0),
        "closed_review": _compact_review(review),
        "decision_tree_tuning": tuning,
        "simulation_only": True,
        "is_real_trade": False,
    }


def _compact_tree(tree: Any) -> Dict[str, Any]:
    tree = tree if isinstance(tree, dict) else {}
    if not tree:
        return {}
    branches = [item for item in tree.get("branches", []) if isinstance(item, dict)]
    return {
        "tree_id": tree.get("tree_id"),
        "symbol": tree.get("symbol"),
        "stock_name": tree.get("stock_name"),
        "status": tree.get("status"),
        "start": tree.get("start", {}),
        "peak": tree.get("peak", {}),
        "current": tree.get("current", {}),
        "metrics": tree.get("metrics", {}),
        "branch_count": tree.get("branch_count", len(branches)),
        "branches": branches[-12:],
        "end_context": tree.get("end_context", {}),
        "review": _compact_review(tree.get("review")),
        "decision_tree_tuning": tree.get("decision_tree_tuning", {}),
        "simulation_only": True,
        "is_real_trade": False,
    }


def _compact_review(review: Any) -> Dict[str, Any]:
    review = review if isinstance(review, dict) else {}
    if not review:
        return {}
    branch_reviews = [item for item in review.get("branch_reviews", []) if isinstance(item, dict)]
    return {
        "review_id": review.get("review_id"),
        "tree_id": review.get("tree_id"),
        "symbol": review.get("symbol"),
        "status": review.get("status"),
        "created_at": review.get("created_at"),
        "start": review.get("start", {}),
        "peak": review.get("peak", {}),
        "end_context": review.get("end_context", {}),
        "branch_count": review.get("branch_count", len(branch_reviews)),
        "counts": review.get("counts", {}),
        "branch_reviews": branch_reviews[-12:],
        "simulation_only": True,
        "is_real_trade": False,
    }


def _last_context(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {"status": "NO_DAILY_ROWS", "simulation_only": True, "is_real_trade": False}
    latest = rows[-1]
    return {
        "status": "READY",
        "date": latest["trade_date"],
        "close": round(latest["close"], 6),
        "low": round(latest["low"], 6),
        "high": round(latest["high"], 6),
        "ma5": _round_or_none(latest.get("ma5")),
        "simulation_only": True,
        "is_real_trade": False,
    }


def _moving_average(values: List[float], window: int) -> List[Optional[float]]:
    result: List[Optional[float]] = []
    for index in range(len(values)):
        if index + 1 < window:
            result.append(None)
            continue
        sample = values[index + 1 - window:index + 1]
        result.append(sum(sample) / window)
    return result


def _stable_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _safe_ratio(numerator: float, denominator: float) -> float:
    if abs(denominator) < 0.000001:
        return 0.0
    return numerator / denominator


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_or_none(value: Any) -> Optional[float]:
    parsed = _to_float(value)
    if parsed is None:
        return None
    return round(parsed, 6)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(float(value), high))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
