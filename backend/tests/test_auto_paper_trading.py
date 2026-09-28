import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core import auto_paper_trading as auto_module
from app.core.auto_paper_trading import auto_paper_trading_store
from app.core.signalops_decision_tree import update_decision_tree_after_tick
from app.core.signalops_store import signalops_store
from app.db.models import AgentSimulationCaseDB, HoldingPositionDB, PaperOrderDB, PaperPortfolioDB, PortfolioSnapshotDB
from app.db.models_research import ResearchIterationDB
from app.db.session import AsyncSessionLocal


def test_compact_module_payload_forces_simulation_boundary():
    compact = auto_module._compact_module_payload(
        {
            "status": "PASS",
            "score": 91,
            "simulation_only": False,
            "is_real_trade": True,
        },
        ["status", "score", "simulation_only", "is_real_trade"],
    )

    assert compact["status"] == "PASS"
    assert compact["score"] == 91
    assert compact["simulation_only"] is True
    assert compact["is_real_trade"] is False


class FakeMarketResult:
    status = "READY"

    def to_public_dict(self):
        return {
            "status": "READY",
            "provider": "fake",
            "profileId": "fake",
            "symbol": "603663",
            "quote": {
                "symbol": "603663",
                "price": 10.0,
                "changePercent": 1.2,
            },
            "fetchedAt": "2026-05-18T00:00:00+00:00",
        }


class NamedMarketResult:
    status = "READY"

    def __init__(self, symbol: str, name: str):
        self.symbol = symbol
        self.name = name

    def to_public_dict(self):
        return {
            "status": "READY",
            "provider": "fake",
            "profileId": "fake",
            "symbol": self.symbol,
            "quote": {
                "symbol": self.symbol,
                "name": self.name,
                "price": 10.0,
                "changePercent": 1.2,
            },
            "fetchedAt": "2026-05-18T00:00:00+00:00",
        }


class FractionalLotMarketResult:
    status = "READY"

    def to_public_dict(self):
        return {
            "status": "READY",
            "provider": "fake",
            "profileId": "fake",
            "symbol": "603663",
            "quote": {
                "symbol": "603663",
                "price": 23.76,
                "changePercent": 1.2,
            },
            "fetchedAt": "2026-05-18T00:00:00+00:00",
        }


class FlatMarketResult:
    status = "READY"

    def to_public_dict(self):
        return {
            "status": "READY",
            "provider": "fake",
            "profileId": "fake",
            "symbol": "603663",
            "quote": {
                "symbol": "603663",
                "price": 10.0,
                "changePercent": 0.1,
            },
            "fetchedAt": "2026-05-18T00:00:00+00:00",
        }


class StrongMarketResult:
    status = "READY"

    def to_public_dict(self):
        return {
            "status": "READY",
            "provider": "fake",
            "profileId": "fake",
            "symbol": "603663",
            "quote": {
                "symbol": "603663",
                "price": 10.0,
                "changePercent": 2.5,
            },
            "fetchedAt": "2026-05-18T00:00:00+00:00",
        }


class WeakMarketResult:
    status = "READY"

    def to_public_dict(self):
        return {
            "status": "READY",
            "provider": "fake",
            "profileId": "fake",
            "symbol": "603663",
            "quote": {
                "symbol": "603663",
                "price": 10.0,
                "changePercent": -2.5,
            },
            "fetchedAt": "2026-05-18T00:00:00+00:00",
        }


class LimitUpMarketResult:
    status = "READY"

    def to_public_dict(self):
        return {
            "status": "READY",
            "provider": "fake",
            "profileId": "fake",
            "symbol": "603663",
            "quote": {
                "symbol": "603663",
                "price": 11.0,
                "changePercent": 10.0,
            },
            "fetchedAt": "2026-05-18T00:00:00+00:00",
        }


class LimitDownMarketResult:
    status = "READY"

    def to_public_dict(self):
        return {
            "status": "READY",
            "provider": "fake",
            "profileId": "fake",
            "symbol": "603663",
            "quote": {
                "symbol": "603663",
                "price": 9.0,
                "changePercent": -10.0,
            },
            "fetchedAt": "2026-05-18T00:00:00+00:00",
        }


class FakeLLMResult:
    status = "COMPLETED"
    error = ""

    def to_public_dict(self):
        return {
            "status": "COMPLETED",
            "parsedJson": {"action": "SIM_HOLD"},
        }


class BuyLLMResult:
    status = "COMPLETED"
    error = ""

    def to_public_dict(self):
        return {
            "status": "COMPLETED",
            "parsedJson": {"action": "SIM_BUY", "positionRatio": 0.5},
        }


def kline_payload(closes, *, period="daily", volumes=None, status="READY"):
    rows = []
    for index, close in enumerate(closes):
        volume = volumes[index] if volumes and index < len(volumes) else 1000 + index
        rows.append({
            "tradeDate": f"2026{1 + (index // 28):02d}{1 + (index % 28):02d}",
            "open": round(close * 0.995, 4),
            "high": round(close * 1.015, 4),
            "low": round(close * 0.985, 4),
            "close": round(close, 4),
            "volume": volume,
        })
    return {
        "status": status,
        "period": period,
        "recordCount": len(rows),
        "rows": rows,
    }


def bottom_candidate_kline_snapshot():
    closes = []
    price = 12.0
    for _ in range(40):
        price -= 0.06
        closes.append(price)
    for _ in range(25):
        price += 0.004
        closes.append(price)
    for _ in range(15):
        price += 0.018
        closes.append(price)
    volumes = [1700] * 40 + [900] * 25 + [650] * 15
    weekly = [9.6, 9.45, 9.4, 9.45, 9.55, 9.7, 9.85, 9.95]
    monthly = [9.4, 9.55, 9.8]
    return {
        "daily": kline_payload(closes, volumes=volumes),
        "weekly": kline_payload(weekly, period="weekly"),
        "monthly": kline_payload(monthly, period="monthly"),
    }


def broken_support_kline_snapshot():
    closes = [12 - index * 0.03 for index in range(55)] + [10.2, 10.1, 9.9, 9.6, 9.2]
    volumes = [1000] * 55 + [1800, 1900, 2100, 2300, 2500]
    return {
        "daily": kline_payload(closes, volumes=volumes),
        "weekly": kline_payload([11.4, 11.1, 10.8, 10.4, 10.0, 9.7], period="weekly"),
        "monthly": kline_payload([11.2, 10.5, 9.8], period="monthly"),
    }


def high_volatility_kline_snapshot():
    rows = []
    price = 10.0
    for index in range(75):
        price += 0.08 if index % 2 == 0 else -0.06
        rows.append({
            "tradeDate": f"2026{1 + (index // 28):02d}{1 + (index % 28):02d}",
            "open": round(price * 0.99, 4),
            "high": round(price * 1.09, 4),
            "low": round(price * 0.91, 4),
            "close": round(price, 4),
            "volume": 1000 + index * 12,
        })
    return {
        "daily": {"status": "READY", "period": "daily", "recordCount": len(rows), "rows": rows},
        "weekly": kline_payload([9.8, 9.9, 10.0, 10.1, 10.2, 10.25, 10.3], period="weekly"),
        "monthly": kline_payload([9.7, 10.0, 10.2], period="monthly"),
    }


def ready_kline_payload(symbol="603663", period="daily", range_="3m"):
    snapshot = bottom_candidate_kline_snapshot()
    return snapshot.get(period) or snapshot["daily"]


def decision_tree_snapshot(rows):
    return {
        "daily": {
            "status": "READY",
            "period": "daily",
            "recordCount": len(rows),
            "rows": rows,
        }
    }


def decision_tree_rows(items):
    rows = []
    for index, (close, low, high) in enumerate(items, start=1):
        rows.append({
            "tradeDate": f"202605{index:02d}",
            "open": round(close * 0.995, 4),
            "high": high,
            "low": low,
            "close": close,
            "volume": 1000 + index,
        })
    return rows


def update_test_decision_tree(state, rows, action="SIM_HOLD", warnings=None):
    return update_decision_tree_after_tick(
        decision_tree_state=state,
        symbol="603663",
        stock_name="Unit Test",
        kline_snapshot=decision_tree_snapshot(rows),
        decision={
            "action": action,
            "reason": f"unit_{action.lower()}",
            "source": "unit_test",
            "positionRatio": 0.35,
            "positionRatioSource": "unit_test",
            "buyChangeThresholdPct": 0.5,
            "closeChangeThresholdPct": -2.0,
            "kline_signal_quality": {"status": "READY", "action_policy": "PROBE"},
            "strategy_stability_quality": {"status": "HEALTHY", "action_policy": "ALLOW"},
        },
        decision_card={"action": action, "reason": f"card_{action.lower()}", "action_policy": "PROBE"},
        portfolio_before={"available_cash": 100000, "market_value": 0, "initial_cash": 100000},
        portfolio_after={"available_cash": 95000, "market_value": 5000, "initial_cash": 100000},
        order=None,
        warnings=warnings or [],
        config_snapshot={
            "buy_change_threshold_pct": 0.5,
            "close_change_threshold_pct": -2.0,
            "watch_position_ratio": 0.15,
            "probe_position_ratio": 0.35,
            "positive_position_ratio": 0.5,
            "breakout_position_ratio": 0.65,
            "defensive_position_ratio": 0.25,
            "existing_position_ratio": 0.45,
            "strength_follow_position_ratio": 0.65,
        },
        now_iso="2026-05-27T00:00:00+00:00",
    )


def ready_kline_quality(symbol="603663", current_price=10.0):
    return auto_module.evaluate_kline_signal_quality(
        symbol,
        bottom_candidate_kline_snapshot(),
        current_price=current_price,
    )


async def age_paper_orders(signal_id: str, created_at: str = "2026-05-17T00:00:00+00:00") -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(PaperOrderDB).where(PaperOrderDB.signal_id == signal_id))
        for record in result.scalars().all():
            record.created_at = created_at
            record.updated_at = created_at
        await db.commit()


@pytest.fixture(autouse=True)
def isolate_auto_store(tmp_path, monkeypatch):
    monkeypatch.setattr(auto_module, "STORAGE_FILE", tmp_path / "auto_paper_trading.json")
    yield
    auto_paper_trading_store.stop_background_loop()


def test_signalops_decision_tree_waits_for_confirmed_low():
    rows = decision_tree_rows([
        (10.0, 9.9, 10.1),
        (9.7, 9.6, 9.8),
        (9.4, 9.3, 9.5),
        (9.2, 9.1, 9.3),
        (9.05, 8.95, 9.1),
    ])

    result = update_test_decision_tree({}, rows, action="SIM_BUY")
    symbol_state = result["state"]["symbols"]["603663"]

    assert result["branch"] == {}
    assert symbol_state["status"] == "WAITING_FOR_CONFIRMED_LOW"
    assert symbol_state["candidate_low"]["low"] == 8.95
    assert result["state"]["simulation_only"] is True
    assert result["state"]["is_real_trade"] is False


def test_signalops_decision_tree_creates_active_branch_after_rebound():
    rows = decision_tree_rows([
        (10.0, 9.9, 10.1),
        (9.7, 9.6, 9.8),
        (9.4, 9.3, 9.5),
        (9.1, 9.0, 9.2),
        (9.3, 9.05, 9.4),
        (9.5, 9.1, 9.6),
    ])

    result = update_test_decision_tree({}, rows, action="SIM_BUY")
    symbol_state = result["state"]["symbols"]["603663"]
    active = symbol_state["active_tree"]

    assert symbol_state["status"] == "ACTIVE"
    assert active["start"]["low"] == 9.0
    assert active["branch_count"] == 1
    assert result["branch"]["action"] == "SIM_BUY"
    assert result["branch"]["ma5"] is not None
    assert result["branch"]["simulation_only"] is True
    assert result["branch"]["is_real_trade"] is False


def test_signalops_decision_tree_does_not_end_on_single_condition():
    base_rows = decision_tree_rows([
        (10.0, 9.9, 10.1),
        (9.7, 9.6, 9.8),
        (9.4, 9.3, 9.5),
        (9.1, 9.0, 9.2),
        (9.3, 9.05, 9.4),
        (9.5, 9.1, 9.6),
    ])
    started = update_test_decision_tree({}, base_rows, action="SIM_HOLD")

    stale_without_ma5_break = decision_tree_rows([
        (10.0, 9.9, 10.1),
        (9.7, 9.6, 9.8),
        (9.4, 9.3, 9.5),
        (9.1, 9.0, 9.2),
        (9.3, 9.05, 9.4),
        (9.5, 9.1, 9.6),
        (10.0, 9.7, 10.2),
        (9.9, 9.6, 10.1),
        (9.8, 9.5, 10.0),
    ])
    still_active = update_test_decision_tree(started["state"], stale_without_ma5_break, action="SIM_HOLD")
    assert still_active["closed_review"] == {}
    assert still_active["state"]["symbols"]["603663"]["status"] == "ACTIVE"

    new_high_with_ma5_break = decision_tree_rows([
        (10.0, 9.9, 10.1),
        (9.7, 9.6, 9.8),
        (9.4, 9.3, 9.5),
        (9.1, 9.0, 9.2),
        (9.3, 9.05, 9.4),
        (9.5, 9.1, 9.6),
        (10.0, 9.7, 10.2),
        (9.2, 9.1, 10.4),
    ])
    still_active = update_test_decision_tree(started["state"], new_high_with_ma5_break, action="SIM_HOLD")
    assert still_active["closed_review"] == {}
    assert still_active["state"]["symbols"]["603663"]["status"] == "ACTIVE"


def test_signalops_decision_tree_closes_review_and_tuning_obeys_caps():
    rows_6 = decision_tree_rows([
        (10.0, 9.9, 10.1),
        (9.7, 9.6, 9.8),
        (9.4, 9.3, 9.5),
        (9.1, 9.0, 9.2),
        (9.3, 9.05, 9.4),
        (9.5, 9.1, 9.6),
    ])
    rows_8 = decision_tree_rows([
        (10.0, 9.9, 10.1),
        (9.7, 9.6, 9.8),
        (9.4, 9.3, 9.5),
        (9.1, 9.0, 9.2),
        (9.3, 9.05, 9.4),
        (9.5, 9.1, 9.6),
        (10.0, 9.7, 10.2),
        (9.9, 9.6, 10.1),
    ])
    rows_9 = decision_tree_rows([
        (10.0, 9.9, 10.1),
        (9.7, 9.6, 9.8),
        (9.4, 9.3, 9.5),
        (9.1, 9.0, 9.2),
        (9.3, 9.05, 9.4),
        (9.5, 9.1, 9.6),
        (10.0, 9.7, 10.2),
        (9.9, 9.6, 10.1),
        (9.4, 9.2, 10.0),
    ])

    first = update_test_decision_tree({}, rows_6, action="SIM_HOLD")
    second = update_test_decision_tree(first["state"], rows_8, action="SIM_BUY")
    closed = update_test_decision_tree(second["state"], rows_9, action="SIM_HOLD")

    review = closed["closed_review"]
    tuning = closed["tuning"]
    symbol_state = closed["state"]["symbols"]["603663"]

    assert symbol_state["status"] == "CLOSED"
    assert review["end_context"]["reason"] == "peak_gain_stalled_and_close_below_ma5"
    assert review["branch_count"] == 3
    assert review["counts"]["wrong"] >= 1
    assert tuning["applied"] is True
    assert tuning["after"]["buy_change_threshold_pct"] == pytest.approx(0.55)
    assert tuning["after"]["watch_position_ratio"] == pytest.approx(0.13)
    assert abs(tuning["after"]["buy_change_threshold_pct"] - tuning["before"]["buy_change_threshold_pct"]) <= 0.0500001
    assert abs(tuning["after"]["watch_position_ratio"] - tuning["before"]["watch_position_ratio"]) <= 0.0200001
    assert closed["knowledge_candidate"]["category"] == "SIGNALOPS_DECISION_TREE"
    assert review["simulation_only"] is True
    assert review["is_real_trade"] is False


def test_review_queue_state_accepts_decision_tree_observation_without_queue_item():
    observation = {
        "id": "dt-review-1",
        "queue_item_id": "dt-review-1",
        "symbol": "603663",
        "candidate_status": "RECOMMENDED_ONLY",
        "promotion_status": "RECOMMENDED_ONLY",
        "review_allowed": False,
        "review_decision": "CONTINUE_OBSERVING",
        "source": "signalops_decision_tree",
        "simulation_only": True,
        "is_real_trade": False,
    }

    state = auto_paper_trading_store._merge_review_queue_state({}, observation=observation)

    assert state["items"] == []
    assert state["observations"][-1]["queue_item_id"] == "dt-review-1"
    assert state["counts"]["recommended_only"] == 1
    assert state["simulation_only"] is True
    assert state["is_real_trade"] is False


def test_auto_paper_corrupted_config_returns_explainable_warning():
    auto_module.STORAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    auto_module.STORAGE_FILE.write_text("{not valid json", encoding="utf-8")

    config = auto_paper_trading_store.get_config()
    status = auto_paper_trading_store.get_status()

    assert "auto_paper_config_corrupted" in config.storage_warning
    assert config.last_error == config.storage_warning
    assert status["storage_warning"] == config.storage_warning
    assert status["last_error"] == config.storage_warning


def test_auto_paper_config_update_recovers_managed_pool_from_signal_ids():
    state = auto_paper_trading_store._load_state()
    state.update({
        "enabled": True,
        "symbol": "603663",
        "stock_name": "Unit A",
        "signal_ids": {
            "603663": "SIG_A",
            "600879": "SIG_B",
        },
        "initial_buy_signals": {"600879": "buy boundary"},
        "final_sell_signals": {"600879": "sell boundary"},
    })
    auto_paper_trading_store._save_state(state)

    config = auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663",
        "stock_name": "Unit A",
        "initial_cash": 100000,
    })

    assert config.symbol == "603663,600879"
    assert config.stock_name == "Unit A,600879"
    assert config.signal_ids["600879"] == "SIG_B"
    assert config.initial_buy_signals["600879"] == "buy boundary"
    assert config.final_sell_signals["600879"] == "sell boundary"


def test_auto_paper_save_state_uses_atomic_replace(monkeypatch):
    calls = []
    original_replace = auto_module.os.replace

    def tracking_replace(src, dst):
        calls.append((Path(src), Path(dst)))
        original_replace(src, dst)

    monkeypatch.setattr(auto_module.os, "replace", tracking_replace)

    config = auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663",
        "stock_name": "Unit Test",
    })

    assert config.symbol == "603663"
    assert calls
    temp_path, final_path = calls[-1]
    assert final_path == auto_module.STORAGE_FILE
    assert temp_path.name.startswith(f"{auto_module.STORAGE_FILE.name}.")
    assert temp_path.suffix == ".tmp"
    assert not temp_path.exists()
    persisted = json.loads(auto_module.STORAGE_FILE.read_text(encoding="utf-8"))
    assert persisted["symbol"] == "603663"
    assert persisted["stock_name"] == "Unit Test"


def test_auto_paper_a_share_price_limit_rate_by_board_and_risk_warning():
    assert auto_module._a_share_limit_rate_pct("603663", "Unit Test") == 10.0
    assert auto_module._a_share_limit_rate_pct("000001", "*ST Unit") == 5.0
    assert auto_module._a_share_limit_rate_pct("300001", "Unit Test") == 20.0
    assert auto_module._a_share_limit_rate_pct("688001", "Unit Test") == 20.0
    assert auto_module._a_share_limit_rate_pct("920001", "Unit Test") == 30.0


@pytest.mark.asyncio
async def test_auto_paper_tick_creates_sim_buy_without_manual_intervention(monkeypatch):
    async def fake_fetch_market_data(profile, symbol):
        return FakeMarketResult()

    monkeypatch.setattr(auto_module, "fetch_market_data", fake_fetch_market_data)
    monkeypatch.setattr(auto_module, "get_kline_payload", ready_kline_payload)

    auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663",
        "stock_name": "Unit Test",
        "initial_buy_signal": "AI 可在突破时自主建仓",
        "final_sell_signal": "AI 复盘判定失效时自主退出",
        "initial_buy_signals": {"603663": "AI 可在突破时自主建仓"},
        "final_sell_signals": {"603663": "AI 复盘判定失效时自主退出"},
        "initial_cash": 100000,
        "max_position_ratio": 0.5,
        "min_order_value": 1000,
        "use_llm": False,
        "realtime_interval_seconds": 1,
        "tick_interval_seconds": 5,
        "min_order_interval_seconds": 5,
    })

    result = await auto_paper_trading_store.tick(force=True)

    assert result["status"] == "COMPLETED"
    assert result["decision"]["action"] == "SIM_BUY"
    assert result["decision_card"]["action"] == "SIM_BUY"
    assert result["decision"]["pre_buy_quality"]["simulation_only"] is True
    assert result["decision"]["pre_buy_quality"]["is_real_trade"] is False
    assert {"score", "grade", "action_policy", "components", "reasons", "evidence_refs"} <= set(result["decision"]["pre_buy_quality"])
    decision_card = result["decision"]["decision_card"]
    assert decision_card["action"] == "SIM_BUY"
    assert decision_card["pre_buy_quality"]["grade"] == result["decision"]["pre_buy_quality"]["grade"]
    assert "pre_buy_quality" in decision_card["review_fields"]
    assert decision_card["capital_before"] == 100000
    assert decision_card["capital_after"] == 99995
    assert decision_card["cash_available"] == 84995
    assert decision_card["position_value"] == 15000
    assert decision_card["budget_used"] == 15000
    assert decision_card["commission_fee"] == 5
    assert decision_card["research_tuning_refs"][0]["source"] == "auto_paper_config"
    assert result["decision"]["userSignalBoundary"]["initial_buy_signal"] == "AI 可在突破时自主建仓"
    assert result["decision"]["userSignalBoundary"]["final_sell_signal"] == "AI 复盘判定失效时自主退出"
    assert result["order"]["action"] == "SIM_BUY"
    assert result["order"]["decision_card"]["budget_used"] == 15000
    assert result["order"]["simulated_fill"]["fees"] == 5
    assert result["order"]["risk_constraints"]["commission_fee"] == 5
    assert result["order"]["risk_constraints"]["execution_rules"]["t_plus_one_long_sell"] is True
    assert result["order"]["risk_constraints"]["decision_card"]["action"] == "SIM_BUY"
    assert result["order"]["simulation_only"] is True
    assert result["order"]["is_real_trade"] is False
    assert result["portfolio_snapshot"]["sourceType"] == "SIGNALOPS_SIM"
    assert result["portfolio_snapshot"]["positionCount"] == 1
    assert result["portfolio_snapshot"]["simulation_only"] is True
    assert result["portfolio_snapshot"]["is_real_trade"] is False
    assert result["config"].symbol == "603663"

    detail = await signalops_store.get_signal_detail(result["config"].signal_id)
    assert detail["signal"]["status"] == "PAPER_TEST"
    assert any("AI 可在突破时自主建仓" in item for item in detail["signal"]["trigger_conditions"])
    assert any("AI 复盘判定失效时自主退出" in item for item in detail["signal"]["invalidation_conditions"])
    assert detail["transitions"][-1]["actor"] == "auto_paper_trader"
    positions = await signalops_store.list_paper_positions(result["config"].signal_id)
    assert positions[0]["capital_attribution"]["position_value"] == 15000
    assert positions[0]["capital_attribution"]["exposure_value"] == 15000
    async with AsyncSessionLocal() as db:
        snapshot = (
            await db.execute(
                select(PortfolioSnapshotDB).where(PortfolioSnapshotDB.snapshot_id == result["portfolio_snapshot"]["snapshotId"])
            )
        ).scalar_one()
        holding = (
            await db.execute(
                select(HoldingPositionDB).where(HoldingPositionDB.snapshot_id == result["portfolio_snapshot"]["snapshotId"])
            )
        ).scalar_one()
    assert snapshot.source_type == "SIGNALOPS_SIM"
    assert holding.symbol == "603663"
    assert holding.shares == 1500


def test_kline_signal_quality_scores_bottom_candidate_and_invalidation():
    empty = auto_module.evaluate_kline_signal_quality(
        "603663",
        {"daily": {"status": "READY", "rows": []}},
        current_price=10.0,
    )
    assert empty["action_policy"] == "HOLD"
    assert empty["grade"] == "BLOCKED"
    assert empty["reasons"] == ["daily_kline_ready_without_rows"]

    candidate = auto_module.evaluate_kline_signal_quality(
        "603663",
        bottom_candidate_kline_snapshot(),
        current_price=9.95,
    )

    assert candidate["simulation_only"] is True
    assert candidate["is_real_trade"] is False
    assert candidate["final_score"] >= 55
    assert candidate["action_policy"] in {"PROBE", "LADDER_BUY"}
    assert candidate["ladder_buy_policy"]["target_position_ratio"] <= 0.5
    assert candidate["bottom_stage_score"]["score"] >= 45
    assert candidate["kline_strategy"]["requires_backtest_before_review"] is True

    broken = auto_module.evaluate_kline_signal_quality(
        "603663",
        broken_support_kline_snapshot(),
        current_price=9.2,
    )

    assert broken["action_policy"] == "HOLD"
    assert broken["ladder_stage"] == "INVALIDATE"
    assert broken["risk_invalidation"]["status"] == "INVALIDATE"


def test_strategy_stability_quality_caps_high_volatility_probe():
    kline_quality = {
        "status": "READY",
        "action_policy": "PROBE",
        "actionPolicy": "PROBE",
        "final_score": 66,
        "score": 66,
        "risk_invalidation": {"status": "CLEAR", "reasons": []},
    }

    stability = auto_module.evaluate_strategy_stability_quality(
        "603663",
        high_volatility_kline_snapshot(),
        kline_quality=kline_quality,
        performance_stats={"trade_count": 2, "wins": 1, "win_rate": 0.5, "expectancy": 0.01},
        current_price=10.6,
    )

    assert stability["simulation_only"] is True
    assert stability["is_real_trade"] is False
    assert stability["action_policy"] == "REDUCE"
    assert stability["volatility_sizing_policy"]["max_position_ratio"] <= 0.15
    assert stability["volatility_sizing_policy"]["forbid_confirm"] is True
    assert stability["meta_label_gate"]["status"] == "INSUFFICIENT_SAMPLE"


def test_auto_paper_decision_meta_label_gate_blocks_llm_buy_without_position():
    config = auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663",
        "stock_name": "Unit Test",
        "initial_cash": 100000,
        "min_order_value": 1000,
        "use_llm": True,
        "performance_stats": {
            "global": {
                "all": {
                    "trade_count": 8,
                    "wins": 0,
                    "win_rate": 0.0,
                    "expectancy": -0.03,
                    "max_drawdown": -0.12,
                    "confidence": 0.8,
                    "quality_status": "POOR",
                }
            }
        },
    })

    decision = auto_paper_trading_store._decide(
        config,
        {"available_cash": 100000, "market_value": 0},
        {"status": "READY", "quote": {"price": 10.0, "changePercent": 1.2}},
        bottom_candidate_kline_snapshot(),
        {"status": "COMPLETED", "parsedJson": {"action": "SIM_BUY", "positionRatio": 0.5}},
    )

    stability = decision["pre_buy_quality"]["components"]["strategy_stability_quality"]
    assert decision["action"] == "SIM_HOLD"
    assert decision["quantity"] == 0
    assert decision["strategyIntent"] == "performance_quality_hold"
    assert stability["meta_label_gate"]["status"] == "BLOCK"
    assert stability["action_policy"] == "HOLD"


def test_auto_paper_decision_uses_quant_core_path_risk_before_buy():
    config = auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663",
        "stock_name": "Unit Test",
        "initial_cash": 100000,
        "min_order_value": 1000,
        "use_llm": True,
    })
    module_evidence = {
        "version": "signalops_module_evidence_v1",
        "quantCore": {
            "coreInterpretation": {
                "status": "READY",
                "actionBoundary": "READ_ONLY_NO_PERMISSION_CHANGE",
                "pathRiskFilter": {
                    "status": "READY",
                    "riskPolicy": "AVOID_NEW_BUY",
                    "actionBoundary": "READ_ONLY_NO_PERMISSION_CHANGE",
                    "labelStatus": "UNLABELED_NOWCAST_PROXY_ONLY",
                    "sampleQuality": {"dataMode": "LIVE", "dailyCount": 120},
                    "leakagePolicy": "runtime_uses_entry_day_technical_proxy_only",
                    "downsideRiskScore": 86,
                    "maxRiskGradient": 0.42,
                    "mfeMaeProxy": {
                        "mfeProxy": 0.02,
                        "maeProxy": 0.11,
                        "riskRewardProxy": 0.18,
                    },
                },
                "futureTrendProbability": {
                    "version": "quant_core_future_trend_probability_v1",
                    "source": "QIAM_MFE_MAE_TECHNICAL_SYNTHESIS",
                    "points": [{
                        "horizonDays": 20,
                        "calibratedUpProbability": 0.28,
                        "calibratedDownProbability": 0.58,
                        "confidence": 0.72,
                        "calibrationStatus": "READY",
                    }],
                    "calibration": {"status": "READY", "sampleCount": 80, "brierUp": 0.19, "brierDown": 0.21},
                    "decisionFeedback": {
                        "signalopsPolicyHint": "SIMULATION_REDUCE_OR_REVIEW_ONLY",
                        "actionBoundary": "READ_ONLY_NO_REAL_TRADE_PERMISSION_CHANGE",
                    },
                },
            },
        },
    }

    decision = auto_paper_trading_store._decide(
        config,
        {"available_cash": 100000, "market_value": 0},
        {"status": "READY", "quote": {"price": 10.0, "changePercent": 1.2}},
        bottom_candidate_kline_snapshot(),
        {"status": "COMPLETED", "parsedJson": {"action": "SIM_BUY", "positionRatio": 0.5}},
        module_evidence,
    )
    decision_card = auto_paper_trading_store._build_decision_card(
        config=config,
        decision=decision,
        portfolio_before={"available_cash": 100000, "market_value": 0, "initial_cash": 100000},
        portfolio_after={"available_cash": 100000, "market_value": 0, "initial_cash": 100000},
        order=None,
        warnings=[],
    )

    assert decision["action"] == "SIM_HOLD"
    assert decision["strategyIntent"] == "quant_core_path_risk_hold"
    assert decision["quantCorePathRiskPolicy"] == "AVOID_NEW_BUY"
    assert decision["quantCorePathRiskBuyBlocked"] is True
    assert decision["moduleEvidence"]["version"] == "signalops_module_evidence_v1"
    assert decision_card["quant_core_path_risk"]["riskPolicy"] == "AVOID_NEW_BUY"
    assert decision_card["quant_core_path_risk"]["actionBoundary"] == "READ_ONLY_NO_PERMISSION_CHANGE"
    assert decision_card["quant_core_path_risk"]["labelStatus"] == "UNLABELED_NOWCAST_PROXY_ONLY"
    assert decision_card["quant_core_path_risk"]["sampleQuality"]["dataMode"] == "LIVE"
    assert decision_card["quant_core_path_risk"]["leakagePolicy"] == "runtime_uses_entry_day_technical_proxy_only"
    assert decision_card["quant_core_path_risk"]["simulation_only"] is True
    assert decision_card["quant_core_path_risk"]["is_real_trade"] is False
    assert decision_card["future_trend_probability"]["signalopsPolicyHint"] == "SIMULATION_REDUCE_OR_REVIEW_ONLY"
    assert decision_card["future_trend_probability"]["actionBoundary"] == "READ_ONLY_NO_REAL_TRADE_PERMISSION_CHANGE"
    assert "quant_core_path_risk" in decision_card["review_fields"]
    assert "future_trend_probability" in decision_card["review_fields"]
    assert "quant_core_path_risk_avoid_new_buy" in decision_card["blockers"]


def test_avoid_new_buy_only_blocks_new_buy_and_does_not_resize_short():
    config = auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663",
        "stock_name": "Unit Test",
        "initial_cash": 100000,
        "min_order_value": 1000,
        "use_llm": False,
    })
    module_evidence = {
        "version": "signalops_module_evidence_v1",
        "quantCore": {
            "coreInterpretation": {
                "status": "READY",
                "actionBoundary": "READ_ONLY_NO_PERMISSION_CHANGE",
                "pathRiskFilter": {
                    "status": "READY",
                    "riskPolicy": "AVOID_NEW_BUY",
                    "downsideRiskScore": 86,
                    "maxRiskGradient": 0.42,
                    "mfeMaeProxy": {
                        "mfeProxy": 0.02,
                        "maeProxy": 0.11,
                        "riskRewardProxy": 0.18,
                    },
                    "provenance": {"actionBoundary": "READ_ONLY_NO_PERMISSION_CHANGE"},
                },
            },
        },
    }

    decision = auto_paper_trading_store._decide(
        config,
        {"available_cash": 100000, "market_value": 0},
        WeakMarketResult().to_public_dict(),
        bottom_candidate_kline_snapshot(),
        None,
        module_evidence,
    )
    decision_card = auto_paper_trading_store._build_decision_card(
        config=config,
        decision=decision,
        portfolio_before={"available_cash": 100000, "market_value": 0, "initial_cash": 100000},
        portfolio_after={"available_cash": 100000, "market_value": 0, "initial_cash": 100000},
        order=None,
        warnings=[],
    )

    assert decision["action"] == "SIM_SHORT"
    assert decision["strategyIntent"] == "open_short"
    assert decision["positionRatio"] == pytest.approx(0.15)
    assert decision["quantity"] == 1500
    assert decision["quantCorePathRiskPolicy"] == "AVOID_NEW_BUY"
    assert decision["quantCorePathRiskAvoidsNewBuy"] is True
    assert decision["quantCorePathRiskBuyBlocked"] is False
    assert "quant_core_path_risk_avoid_new_buy" not in decision_card["blockers"]


def test_strategy_stability_meta_gate_normalizes_drawdown_sign():
    for max_drawdown in (-0.12, 0.12):
        stability = auto_module.evaluate_strategy_stability_quality(
            "603663",
            bottom_candidate_kline_snapshot(),
            kline_quality=ready_kline_quality(),
            performance_stats={
                "trade_count": 20,
                "wins": 14,
                "win_rate": 0.7,
                "expectancy": 0.02,
                "max_drawdown": max_drawdown,
            },
            current_price=10.0,
        )

        assert stability["meta_label_gate"]["status"] == "REDUCE"
        assert stability["meta_label_gate"]["max_drawdown_pressure"] == pytest.approx(0.12)
        assert stability["action_policy"] == "REDUCE"


def test_auto_paper_decision_keeps_kline_invalidation_close_after_llm_hold():
    config = auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663",
        "stock_name": "Unit Test",
        "initial_cash": 100000,
        "min_order_value": 1000,
        "use_llm": True,
    })

    decision = auto_paper_trading_store._decide(
        config,
        {"available_cash": 50000, "market_value": 50000},
        {"status": "READY", "quote": {"price": 9.2, "changePercent": 0.1}},
        broken_support_kline_snapshot(),
        {"status": "COMPLETED", "parsedJson": {"action": "SIM_HOLD"}},
    )

    assert decision["action"] == "SIM_CLOSE"
    assert decision["strategyIntent"] == "kline_invalidation_close"
    assert decision["kline_signal_quality"]["risk_invalidation"]["status"] == "INVALIDATE"


def test_auto_paper_decision_keeps_kline_invalidation_hold_after_llm_buy_without_position():
    config = auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663",
        "stock_name": "Unit Test",
        "initial_cash": 100000,
        "min_order_value": 1000,
        "use_llm": True,
    })

    decision = auto_paper_trading_store._decide(
        config,
        {"available_cash": 100000, "market_value": 0},
        {"status": "READY", "quote": {"price": 9.2, "changePercent": 1.2}},
        broken_support_kline_snapshot(),
        {"status": "COMPLETED", "parsedJson": {"action": "SIM_BUY"}},
    )

    assert decision["action"] == "SIM_HOLD"
    assert decision["strategyIntent"] == "kline_invalidation_hold"
    assert decision["quantity"] == 0
    assert decision["kline_signal_quality"]["risk_invalidation"]["status"] == "INVALIDATE"


def test_auto_paper_decision_caps_probe_buy_with_ladder_policy():
    config = auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663",
        "stock_name": "Unit Test",
        "initial_cash": 100000,
        "min_order_value": 1000,
        "use_llm": False,
    })

    decision = auto_paper_trading_store._decide(
        config,
        {"available_cash": 100000, "market_value": 0},
        {"status": "READY", "quote": {"price": 10.0, "changePercent": 1.2}},
        bottom_candidate_kline_snapshot(),
        None,
    )

    assert decision["action"] == "SIM_BUY"
    assert decision["quantity"] <= 1500
    assert decision["targetCashValue"] <= 15000
    assert decision["kline_signal_quality"]["action_policy"] in {"PROBE", "LADDER_BUY"}
    assert decision["ladderBuyPolicy"]["target_position_ratio"] <= 0.5
    assert "kline_signal_quality" in decision["pre_buy_quality"]["components"]


@pytest.mark.asyncio
async def test_auto_paper_tick_holds_buy_when_kline_unavailable(monkeypatch):
    async def fake_fetch_market_data(profile, symbol):
        return FakeMarketResult()

    monkeypatch.setattr(auto_module, "fetch_market_data", fake_fetch_market_data)
    monkeypatch.setattr(
        auto_module,
        "get_kline_payload",
        lambda symbol, period, range_: {"status": "FAILED", "period": period, "rows": [], "recordCount": 0},
    )

    auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663",
        "stock_name": "Unit Test",
        "initial_cash": 100000,
        "min_order_value": 1000,
        "use_llm": False,
        "realtime_interval_seconds": 1,
        "tick_interval_seconds": 5,
        "min_order_interval_seconds": 5,
    })

    result = await auto_paper_trading_store.tick(force=True)

    assert result["status"] == "COMPLETED"
    assert result["decision"]["action"] == "SIM_HOLD"
    assert result["order"] is None
    assert result["decision"]["strategyIntent"] == "kline_quality_hold"
    assert result["decision"]["kline_signal_quality"]["action_policy"] == "HOLD"
    assert result["decision_card"]["kline_signal_quality"]["action_policy"] == "HOLD"


def test_auto_paper_fetch_kline_snapshot_reuses_cached_payload(monkeypatch):
    monkeypatch.setattr(auto_module, "get_kline_payload", ready_kline_payload)
    config = auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663",
        "stock_name": "Unit Test",
        "kline_interval_seconds": 300,
        "weekly_monthly_interval_seconds": 86400,
    })

    first = auto_paper_trading_store._fetch_kline_snapshot(config, force=True)
    assert first["daily"]["rows"]

    def fail_kline_fetch(symbol, period, range_):
        raise AssertionError("cached K-line snapshot should be reused before refresh interval")

    monkeypatch.setattr(auto_module, "get_kline_payload", fail_kline_fetch)
    cached = auto_paper_trading_store._fetch_kline_snapshot(auto_paper_trading_store.get_config(), force=False)

    assert cached["cache_status"] == "CACHED"
    assert cached["daily"]["rows"] == first["daily"]["rows"]


@pytest.mark.asyncio
async def test_auto_paper_tick_fetches_kline_snapshot_off_event_loop(monkeypatch):
    async def fake_fetch_market_data(profile, symbol):
        return FakeMarketResult()

    to_thread_calls = []

    async def fake_to_thread(func, *args, **kwargs):
        to_thread_calls.append(func.__name__)
        return func(*args, **kwargs)

    monkeypatch.setattr(auto_module, "fetch_market_data", fake_fetch_market_data)
    monkeypatch.setattr(auto_module, "get_kline_payload", ready_kline_payload)
    monkeypatch.setattr(auto_module.asyncio, "to_thread", fake_to_thread)

    auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663",
        "stock_name": "Unit Test",
        "initial_cash": 100000,
        "max_position_ratio": 0.5,
        "min_order_value": 1000,
        "use_llm": False,
        "tick_interval_seconds": 5,
        "min_order_interval_seconds": 5,
    })

    result = await auto_paper_trading_store.tick(force=True)

    assert result["status"] == "COMPLETED"
    assert "_fetch_kline_snapshot" in to_thread_calls


@pytest.mark.asyncio
async def test_auto_paper_tick_ignores_manual_max_position_ratio(monkeypatch):
    async def fake_fetch_market_data(profile, symbol):
        return FakeMarketResult()

    monkeypatch.setattr(auto_module, "fetch_market_data", fake_fetch_market_data)
    monkeypatch.setattr(auto_module, "get_kline_payload", ready_kline_payload)

    auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663",
        "stock_name": "Unit Test",
        "initial_cash": 100000,
        "max_position_ratio": 0.9,
        "min_order_value": 1000,
        "use_llm": False,
        "realtime_interval_seconds": 1,
        "tick_interval_seconds": 5,
        "min_order_interval_seconds": 5,
    })

    result = await auto_paper_trading_store.tick(force=True)

    assert result["status"] == "COMPLETED"
    assert result["decision"]["positionRatio"] == 0.15
    assert result["decision"]["positionRatioSource"] == "ai_dynamic_positive"
    assert result["order"]["simulated_quantity"] == 1500
    assert result["config"].max_position_ratio == 0.5


@pytest.mark.asyncio
async def test_auto_paper_command_force_closes_and_removes_symbol(monkeypatch):
    async def fake_fetch_market_data(profile, symbol):
        return FakeMarketResult()

    monkeypatch.setattr(auto_module, "fetch_market_data", fake_fetch_market_data)
    monkeypatch.setattr(auto_module, "get_kline_payload", ready_kline_payload)

    auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663",
        "stock_name": "Unit Test",
        "initial_cash": 100000,
        "min_order_value": 1000,
        "use_llm": False,
        "realtime_interval_seconds": 1,
        "tick_interval_seconds": 5,
        "min_order_interval_seconds": 5,
    })

    tick = await auto_paper_trading_store.tick(force=True)
    await age_paper_orders(tick["config"].signal_id)
    command = await auto_paper_trading_store.command(
        symbol="603663",
        command="FORCE_CLOSE_AND_REMOVE",
        reason="unit test forced close",
    )

    assert command["status"] == "COMPLETED"
    assert command["order"]["action"] == "SIM_CLOSE"
    assert command["order"]["fill_status"] == "FILLED"
    assert command["config"].symbol == ""
    assert command["config"].enabled is False

    positions = await signalops_store.list_paper_positions(tick["config"].signal_id)
    assert positions == []
    detail = await signalops_store.get_signal_detail(tick["config"].signal_id)
    assert detail["signal"]["status"] == "CLOSED"


@pytest.mark.asyncio
async def test_auto_paper_command_force_open_buy_uses_realtime_price(monkeypatch):
    async def fake_fetch_market_data(profile, symbol):
        return FlatMarketResult()

    monkeypatch.setattr(auto_module, "fetch_market_data", fake_fetch_market_data)
    monkeypatch.setattr(auto_module, "get_kline_payload", ready_kline_payload)

    auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663",
        "stock_name": "Unit Test",
        "initial_cash": 100000,
        "min_order_value": 1000,
        "use_llm": False,
        "realtime_interval_seconds": 1,
        "tick_interval_seconds": 5,
        "min_order_interval_seconds": 5,
    })

    command = await auto_paper_trading_store.command(
        symbol="603663",
        command="FORCE_OPEN_BUY",
        reason="unit test forced open buy",
    )

    assert command["status"] == "COMPLETED"
    assert command["order"]["action"] == "SIM_BUY"
    assert command["order"]["fill_status"] == "FILLED"
    assert command["order"]["simulated_price"] == 10.0
    assert command["order"]["simulated_quantity"] == 1500
    assert command["order"]["risk_constraints"]["manual_command"] == "FORCE_OPEN_BUY"
    assert command["order"]["risk_constraints"]["ai_position_ratio"] == 0.15
    assert command["order"]["risk_constraints"]["position_ratio_source"] == "ai_dynamic_watch"
    assert command["order"]["risk_constraints"]["available_cash_before_order"] == 100000
    assert command["order"]["risk_constraints"]["target_cash_value"] == 15000
    assert command["order"]["simulation_only"] is True
    assert command["order"]["is_real_trade"] is False

    positions = await signalops_store.list_paper_positions(command["signal_id"])
    assert positions[0]["quantity"] == 1500
    detail = await signalops_store.get_signal_detail(command["signal_id"])
    assert detail["signal"]["status"] == "PAPER_TEST"


@pytest.mark.asyncio
async def test_auto_paper_command_force_open_buy_cannot_bypass_kline_gate(monkeypatch):
    async def fake_fetch_market_data(profile, symbol):
        return FlatMarketResult()

    monkeypatch.setattr(auto_module, "fetch_market_data", fake_fetch_market_data)
    monkeypatch.setattr(
        auto_module,
        "get_kline_payload",
        lambda symbol, period, range_: {"status": "READY", "period": period, "rows": [], "recordCount": 0},
    )

    auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663",
        "stock_name": "Unit Test",
        "initial_cash": 100000,
        "min_order_value": 1000,
        "use_llm": False,
        "realtime_interval_seconds": 1,
        "tick_interval_seconds": 5,
        "min_order_interval_seconds": 5,
    })

    command = await auto_paper_trading_store.command(
        symbol="603663",
        command="FORCE_OPEN_BUY",
        reason="unit test forced open buy",
    )

    assert command["status"] == "BLOCKED"
    assert command["order"]["error"] == "kline_quality_buy_blocked"
    assert command["order"]["rule_context"]["action_policy"] == "HOLD"
    assert "order_error:kline_quality_buy_blocked" in command["warnings"]
    assert command["config"].last_decision["decision_card"]["action"] == "SIM_BUY"
    assert "order_error:kline_quality_buy_blocked" in command["config"].last_decision["decision_card"]["blockers"]

    detail = await signalops_store.get_signal_detail(command["signal_id"])
    assert detail["signal"]["status"] == "IDEA"
    assert not any("AI decision: SIM_BUY" in item for item in detail["signal"].get("trigger_conditions", []))

    orders = await signalops_store.list_paper_orders(command["signal_id"])
    assert not any(
        order.get("action") in {"SIM_BUY", "SIM_T_BUY"}
        and str(order.get("fill_status") or "").upper() == "FILLED"
        for order in orders
    )


@pytest.mark.asyncio
async def test_auto_paper_command_force_open_buy_cannot_bypass_quant_core_path_risk(monkeypatch):
    async def fake_fetch_market_data(profile, symbol):
        return FlatMarketResult()

    monkeypatch.setattr(auto_module, "fetch_market_data", fake_fetch_market_data)
    monkeypatch.setattr(auto_module, "get_kline_payload", ready_kline_payload)
    monkeypatch.setattr(
        auto_paper_trading_store,
        "_build_module_evidence",
        lambda *args, **kwargs: {
            "version": "signalops_module_evidence_v1",
            "quantCore": {
                "coreInterpretation": {
                    "actionBoundary": "READ_ONLY_NO_PERMISSION_CHANGE",
                    "pathRiskFilter": {
                        "status": "READY",
                        "riskPolicy": "AVOID_NEW_BUY",
                        "downsideRiskScore": 88,
                        "maxRiskGradient": 0.52,
                        "mfeMaeProxy": {"mfeProxy": 0.02, "maeProxy": 0.12, "riskRewardProxy": 0.17},
                        "provenance": {"actionBoundary": "READ_ONLY_NO_PERMISSION_CHANGE"},
                    },
                },
            },
            "simulation_only": True,
            "is_real_trade": False,
        },
    )

    auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663",
        "stock_name": "Unit Test",
        "initial_cash": 100000,
        "min_order_value": 1000,
        "use_llm": False,
        "realtime_interval_seconds": 1,
        "tick_interval_seconds": 5,
        "min_order_interval_seconds": 5,
    })

    command = await auto_paper_trading_store.command(
        symbol="603663",
        command="FORCE_OPEN_BUY",
        reason="unit test forced open buy",
    )

    assert command["status"] == "BLOCKED"
    assert command["order"]["error"] == "quant_core_path_risk_buy_blocked"
    assert command["order"]["rule_context"]["risk_policy"] == "AVOID_NEW_BUY"
    assert "order_error:quant_core_path_risk_buy_blocked" in command["warnings"]
    assert command["config"].last_decision["moduleEvidence"]["version"] == "signalops_module_evidence_v1"
    assert command["config"].last_decision["quantCorePathRiskPolicy"] == "AVOID_NEW_BUY"
    assert command["config"].last_decision["decision_card"]["quant_core_path_risk_policy"] == "AVOID_NEW_BUY"
    assert "quant_core_path_risk_avoid_new_buy" in command["config"].last_decision["decision_card"]["blockers"]

    detail = await signalops_store.get_signal_detail(command["signal_id"])
    assert detail["signal"]["status"] == "IDEA"
    orders = await signalops_store.list_paper_orders(command["signal_id"])
    assert not any(
        order.get("action") in {"SIM_BUY", "SIM_T_BUY"}
        and str(order.get("fill_status") or "").upper() == "FILLED"
        for order in orders
    )


@pytest.mark.asyncio
async def test_auto_paper_order_creation_cannot_bypass_strategy_stability_gate():
    config = auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663",
        "stock_name": "Unit Test",
        "initial_cash": 100000,
        "min_order_value": 1000,
        "use_llm": False,
    })
    kline_quality = ready_kline_quality(current_price=10.0)
    stability_quality = {
        "status": "READY",
        "action_policy": "HOLD",
        "actionPolicy": "HOLD",
        "meta_label_gate": {"status": "BLOCK", "reasons": ["wilson_floor_and_expectancy_negative"]},
        "reasons": ["meta_label_gate_blocks_buy"],
        "simulation_only": True,
        "is_real_trade": False,
    }
    decision = {
        "action": "SIM_BUY",
        "price": 10.0,
        "quantity": 1000,
        "changePercent": 1.2,
        "pre_buy_quality": {
            "action_policy": "HOLD",
            "components": {
                "kline_signal_quality": kline_quality,
                "strategy_stability_quality": stability_quality,
            },
            "simulation_only": True,
            "is_real_trade": False,
        },
        "kline_signal_quality": kline_quality,
        "strategy_stability_quality": stability_quality,
        "simulation_only": True,
        "is_real_trade": False,
    }

    order = await auto_paper_trading_store._maybe_create_order(
        config,
        "SIG_STABILITY_BLOCK",
        {"available_cash": 100000, "market_value": 0},
        decision,
        True,
    )

    assert order["error"] == "strategy_stability_buy_blocked"
    assert order["rule_context"]["meta_label_status"] == "BLOCK"


@pytest.mark.asyncio
async def test_auto_paper_command_force_open_buy_never_tops_up_available_cash(monkeypatch):
    async def fake_fetch_market_data(profile, symbol):
        return StrongMarketResult()

    monkeypatch.setattr(auto_module, "fetch_market_data", fake_fetch_market_data)
    monkeypatch.setattr(auto_module, "get_kline_payload", ready_kline_payload)

    auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663",
        "stock_name": "Unit Test",
        "initial_cash": 100000,
        "min_order_value": 1000,
        "use_llm": False,
        "realtime_interval_seconds": 1,
        "tick_interval_seconds": 5,
        "min_order_interval_seconds": 5,
    })

    config = auto_paper_trading_store.get_config()
    signal = await auto_paper_trading_store._ensure_signal(config)
    portfolio, error = await signalops_store.create_paper_portfolio(signal["signal_id"], {
        "initial_cash": 100000,
        "risk_budget": {"test": "low_cash_preserved"},
        "created_by_agent": "test",
    })
    assert error is None
    assert portfolio

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(PaperPortfolioDB).where(PaperPortfolioDB.signal_id == signal["signal_id"]))
        record = result.scalar_one()
        record.available_cash = 21000
        await db.commit()

    command = await auto_paper_trading_store.command(
        symbol="603663",
        command="FORCE_OPEN_BUY",
        reason="unit test low available cash",
    )

    assert command["status"] == "COMPLETED"
    assert command["order"]["simulated_price"] == 10.0
    assert command["order"]["simulated_quantity"] == 300
    assert command["order"]["simulated_quantity"] * command["order"]["simulated_price"] <= 21000
    assert command["order"]["risk_constraints"]["available_cash_before_order"] == 21000
    assert command["order"]["risk_constraints"]["target_cash_value"] == 3150
    assert command["order"]["risk_constraints"]["ai_position_ratio"] == 0.15
    assert command["order"]["simulated_fill"]["fees"] == 5
    assert command["portfolio"]["available_cash"] == 17995


@pytest.mark.asyncio
async def test_auto_paper_tick_uses_integer_board_lots(monkeypatch):
    async def fake_fetch_market_data(profile, symbol):
        return FractionalLotMarketResult()

    monkeypatch.setattr(auto_module, "fetch_market_data", fake_fetch_market_data)
    monkeypatch.setattr(auto_module, "get_kline_payload", ready_kline_payload)

    auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663",
        "stock_name": "Unit Test",
        "initial_cash": 10_000_000,
        "max_position_ratio": 0.5,
        "min_order_value": 1000,
        "use_llm": False,
        "realtime_interval_seconds": 1,
        "tick_interval_seconds": 5,
        "min_order_interval_seconds": 5,
    })

    result = await auto_paper_trading_store.tick(force=True)

    assert result["status"] == "COMPLETED"
    assert result["order"]["simulated_quantity"] == 63_100
    assert result["order"]["simulated_quantity"] % 100 == 0
    assert result["order"]["simulated_fill"]["filled_quantity"] == 63_100

    positions = await signalops_store.list_paper_positions(result["config"].signal_id)
    assert positions[0]["quantity"] == 63_100
    assert positions[0]["quantity"] % 100 == 0


@pytest.mark.asyncio
async def test_auto_paper_tick_can_open_simulated_short(monkeypatch):
    async def fake_fetch_market_data(profile, symbol):
        return WeakMarketResult()

    monkeypatch.setattr(auto_module, "fetch_market_data", fake_fetch_market_data)
    monkeypatch.setattr(auto_module, "get_kline_payload", ready_kline_payload)

    auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663",
        "stock_name": "Unit Test",
        "initial_cash": 100000,
        "min_order_value": 1000,
        "use_llm": False,
        "realtime_interval_seconds": 1,
        "tick_interval_seconds": 5,
        "min_order_interval_seconds": 5,
    })

    result = await auto_paper_trading_store.tick(force=True)

    assert result["status"] == "COMPLETED"
    assert result["decision"]["action"] == "SIM_SHORT"
    assert result["decision"]["strategyIntent"] == "open_short"
    assert result["order"]["action"] == "SIM_SHORT"
    assert result["order"]["risk_constraints"]["strategy_intent"] == "open_short"

    positions = await signalops_store.list_paper_positions(result["config"].signal_id)
    assert positions[0]["quantity"] == -1500
    assert positions[0]["current_value"] == -15000

    portfolio = await signalops_store.get_paper_portfolio(result["config"].signal_id)
    assert result["order"]["simulated_fill"]["fees"] == 5
    assert portfolio["available_cash"] == 114995
    assert portfolio["market_value"] == -15000


@pytest.mark.asyncio
async def test_auto_paper_tick_covers_simulated_short_on_rebound(monkeypatch):
    market = {"result": WeakMarketResult()}

    async def fake_fetch_market_data(profile, symbol):
        return market["result"]

    monkeypatch.setattr(auto_module, "fetch_market_data", fake_fetch_market_data)
    monkeypatch.setattr(auto_module, "get_kline_payload", ready_kline_payload)

    auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663",
        "stock_name": "Unit Test",
        "initial_cash": 100000,
        "min_order_value": 1000,
        "use_llm": False,
        "realtime_interval_seconds": 1,
        "tick_interval_seconds": 5,
        "min_order_interval_seconds": 5,
    })

    opened = await auto_paper_trading_store.tick(force=True)
    market["result"] = FakeMarketResult()
    covered = await auto_paper_trading_store.tick(force=True)

    assert opened["order"]["action"] == "SIM_SHORT"
    assert covered["decision"]["action"] == "SIM_COVER"
    assert covered["order"]["action"] == "SIM_COVER"

    positions = await signalops_store.list_paper_positions(covered["config"].signal_id)
    assert positions == []

    portfolio = await signalops_store.get_paper_portfolio(covered["config"].signal_id)
    assert portfolio["available_cash"] == 99990
    assert portfolio["market_value"] == 0


@pytest.mark.asyncio
async def test_force_open_buy_blocks_when_simulated_short_exists(monkeypatch):
    async def fake_fetch_market_data(profile, symbol):
        return WeakMarketResult()

    monkeypatch.setattr(auto_module, "fetch_market_data", fake_fetch_market_data)
    monkeypatch.setattr(auto_module, "get_kline_payload", ready_kline_payload)

    auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663",
        "stock_name": "Unit Test",
        "initial_cash": 100000,
        "min_order_value": 1000,
        "use_llm": False,
        "realtime_interval_seconds": 1,
        "tick_interval_seconds": 5,
        "min_order_interval_seconds": 5,
    })

    opened = await auto_paper_trading_store.tick(force=True)
    command = await auto_paper_trading_store.command(
        symbol="603663",
        command="FORCE_OPEN_BUY",
        reason="unit test should not open long over short",
    )

    assert opened["order"]["action"] == "SIM_SHORT"
    assert command["status"] == "BLOCKED"
    assert command["order"] is None
    assert "position_already_open" in command["warnings"]

    positions = await signalops_store.list_paper_positions(opened["config"].signal_id)
    assert positions[0]["quantity"] == -1500


@pytest.mark.asyncio
async def test_short_cover_fill_recomputes_portfolio_market_value_at_fill_price(monkeypatch):
    async def fake_fetch_market_data(profile, symbol):
        return WeakMarketResult()

    monkeypatch.setattr(auto_module, "fetch_market_data", fake_fetch_market_data)
    monkeypatch.setattr(auto_module, "get_kline_payload", ready_kline_payload)

    auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663",
        "stock_name": "Unit Test",
        "initial_cash": 100000,
        "min_order_value": 1000,
        "use_llm": False,
        "realtime_interval_seconds": 1,
        "tick_interval_seconds": 5,
        "min_order_interval_seconds": 5,
    })

    opened = await auto_paper_trading_store.tick(force=True)
    cover_order, error = await signalops_store.create_paper_order(opened["config"].signal_id, {
        "agent_id": "unit_test",
        "action": "SIM_COVER",
        "action_reason": "cover at a higher price",
        "simulated_price": 12.0,
        "simulated_quantity": 1500,
        "risk_constraints": {"simulation_only": True, "is_real_trade": False},
    })
    assert error is None
    assert cover_order

    filled, fill_error = await signalops_store.fill_paper_order(opened["config"].signal_id, cover_order["order_id"], {
        "filled_price": 12.0,
        "filled_quantity": 1500,
        "fees": 0.0,
        "slippage": 0.0,
    })

    assert fill_error is None
    assert filled["fill_status"] == "FILLED"
    assert await signalops_store.list_paper_positions(opened["config"].signal_id) == []

    portfolio = await signalops_store.get_paper_portfolio(opened["config"].signal_id)
    assert portfolio["available_cash"] == 96995
    assert portfolio["market_value"] == 0


@pytest.mark.asyncio
async def test_auto_paper_tick_can_sell_partial_position_for_t_trade(monkeypatch):
    market = {"result": FakeMarketResult()}

    async def fake_fetch_market_data(profile, symbol):
        return market["result"]

    monkeypatch.setattr(auto_module, "fetch_market_data", fake_fetch_market_data)
    monkeypatch.setattr(auto_module, "get_kline_payload", ready_kline_payload)

    auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663",
        "stock_name": "Unit Test",
        "initial_cash": 100000,
        "min_order_value": 1000,
        "use_llm": False,
        "realtime_interval_seconds": 1,
        "tick_interval_seconds": 5,
        "min_order_interval_seconds": 5,
    })

    opened = await auto_paper_trading_store.tick(force=True)
    await age_paper_orders(opened["config"].signal_id)
    market["result"] = StrongMarketResult()
    t_trade = await auto_paper_trading_store.tick(force=True)

    assert opened["order"]["action"] == "SIM_BUY"
    assert t_trade["decision"]["action"] == "SIM_T_SELL"
    assert t_trade["decision"]["strategyIntent"] == "t_sell"
    assert t_trade["order"]["action"] == "SIM_T_SELL"

    positions = await signalops_store.list_paper_positions(t_trade["config"].signal_id)
    assert positions[0]["quantity"] == 1000


@pytest.mark.asyncio
async def test_auto_paper_blocks_same_day_long_sell_for_a_share_t_plus_one(monkeypatch):
    market = {"result": FakeMarketResult()}

    async def fake_fetch_market_data(profile, symbol):
        return market["result"]

    monkeypatch.setattr(auto_module, "fetch_market_data", fake_fetch_market_data)
    monkeypatch.setattr(auto_module, "get_kline_payload", ready_kline_payload)

    auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663",
        "stock_name": "Unit Test",
        "initial_cash": 100000,
        "min_order_value": 1000,
        "use_llm": False,
        "realtime_interval_seconds": 1,
        "tick_interval_seconds": 5,
        "min_order_interval_seconds": 5,
    })

    opened = await auto_paper_trading_store.tick(force=True)
    market["result"] = StrongMarketResult()
    blocked = await auto_paper_trading_store.tick(force=True)

    assert opened["order"]["action"] == "SIM_BUY"
    assert blocked["decision"]["action"] == "SIM_T_SELL"
    assert blocked["order"]["error"] == "a_share_t_plus_one_blocked"
    assert "order_error:a_share_t_plus_one_blocked" in blocked["warnings"]

    positions = await signalops_store.list_paper_positions(blocked["config"].signal_id)
    assert positions[0]["quantity"] == 1500


@pytest.mark.asyncio
async def test_auto_paper_blocks_limit_up_buy_and_limit_down_sell():
    auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663",
        "stock_name": "Unit Test",
        "initial_cash": 100000,
        "min_order_value": 1000,
        "use_llm": False,
    })

    config = auto_paper_trading_store.get_config()
    signal = await auto_paper_trading_store._ensure_signal(config)
    portfolio, error = await signalops_store.create_paper_portfolio(signal["signal_id"], {
        "initial_cash": 100000,
        "risk_budget": {"test": "a_share_price_limits"},
        "created_by_agent": "test",
    })
    assert error is None
    assert portfolio

    limit_up = LimitUpMarketResult().to_public_dict()["quote"]
    blocked_buy = await auto_paper_trading_store._maybe_create_order(
        config,
        signal["signal_id"],
        portfolio,
        {
            "action": "SIM_BUY",
            "reason": "unit test limit up",
            "price": limit_up["price"],
            "quantity": 100,
            "changePercent": limit_up["changePercent"],
            "source": "unit_test",
            "simulation_only": True,
            "is_real_trade": False,
        },
        force=True,
    )

    assert blocked_buy["error"] == "a_share_limit_up_buy_blocked"
    assert blocked_buy["rule_context"]["limit_rate_pct"] == 10.0
    assert blocked_buy["rule_context"]["at_limit_up"] is True

    limit_down = LimitDownMarketResult().to_public_dict()["quote"]
    blocked_sell = await auto_paper_trading_store._maybe_create_order(
        config,
        signal["signal_id"],
        portfolio,
        {
            "action": "SIM_CLOSE",
            "reason": "unit test limit down",
            "price": limit_down["price"],
            "quantity": 100,
            "changePercent": limit_down["changePercent"],
            "source": "unit_test",
            "simulation_only": True,
            "is_real_trade": False,
        },
        force=True,
    )

    assert blocked_sell["error"] == "a_share_limit_down_sell_blocked"
    assert blocked_sell["rule_context"]["limit_rate_pct"] == 10.0
    assert blocked_sell["rule_context"]["at_limit_down"] is True


@pytest.mark.asyncio
async def test_auto_paper_non_force_order_waits_outside_a_share_session(monkeypatch):
    monkeypatch.setattr(auto_module, "_now", lambda: datetime(2026, 5, 18, 4, 0, tzinfo=timezone.utc))
    auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663",
        "stock_name": "Unit Test",
        "initial_cash": 100000,
        "min_order_value": 1000,
        "use_llm": False,
    })

    config = auto_paper_trading_store.get_config()
    signal = await auto_paper_trading_store._ensure_signal(config)
    portfolio, error = await signalops_store.create_paper_portfolio(signal["signal_id"], {
        "initial_cash": 100000,
        "risk_budget": {"test": "a_share_session_gate"},
        "created_by_agent": "test",
    })
    assert error is None
    assert portfolio

    decision = {
        "action": "SIM_BUY",
        "reason": "unit test lunch break",
        "price": 10.0,
        "quantity": 100,
        "changePercent": 1.0,
        "source": "unit_test",
        "kline_signal_quality": ready_kline_quality(current_price=10.0),
        "simulation_only": True,
        "is_real_trade": False,
    }
    blocked = await auto_paper_trading_store._maybe_create_order(config, signal["signal_id"], portfolio, decision, force=False)
    assert blocked["error"] == "a_share_trading_session_closed"
    assert blocked["rule_context"]["status"] == "NON_TRADING_SESSION"

    allowed = await auto_paper_trading_store._maybe_create_order(config, signal["signal_id"], portfolio, decision, force=True)
    assert allowed["action"] == "SIM_BUY"
    assert allowed["risk_constraints"]["a_share_session"]["force_override"] is True
    assert allowed["risk_constraints"]["a_share_price_limit"]["at_limit_up"] is False


@pytest.mark.asyncio
async def test_auto_paper_applies_sell_side_stamp_duty_after_t_plus_one(monkeypatch):
    market = {"result": FakeMarketResult()}

    async def fake_fetch_market_data(profile, symbol):
        return market["result"]

    monkeypatch.setattr(auto_module, "fetch_market_data", fake_fetch_market_data)
    monkeypatch.setattr(auto_module, "get_kline_payload", ready_kline_payload)

    auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663",
        "stock_name": "Unit Test",
        "initial_cash": 100000,
        "min_order_value": 1000,
        "use_llm": False,
        "realtime_interval_seconds": 1,
        "tick_interval_seconds": 5,
        "min_order_interval_seconds": 5,
    })

    opened = await auto_paper_trading_store.tick(force=True)
    await age_paper_orders(opened["config"].signal_id)
    market["result"] = StrongMarketResult()
    sold = await auto_paper_trading_store.tick(force=True)

    assert opened["order"]["action"] == "SIM_BUY"
    assert sold["order"]["action"] == "SIM_T_SELL"
    trade_amount = sold["order"]["simulated_price"] * sold["order"]["simulated_quantity"]
    expected_stamp = round(trade_amount * 0.0005, 6)
    expected_total_fee = round(sold["order"]["risk_constraints"]["commission_fee"] + expected_stamp, 6)
    assert sold["order"]["risk_constraints"]["stamp_duty_fee"] == expected_stamp
    assert sold["order"]["risk_constraints"]["total_fee"] == expected_total_fee
    assert sold["order"]["simulated_fill"]["fees"] == expected_total_fee
    assert sold["order"]["decision_card"]["stamp_duty_fee"] == expected_stamp
    assert sold["order"]["decision_card"]["total_fee"] == expected_total_fee


@pytest.mark.asyncio
async def test_auto_paper_sell_without_long_position_reports_position_error(monkeypatch):
    auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663",
        "stock_name": "Unit Test",
        "initial_cash": 100000,
        "min_order_value": 1000,
        "use_llm": False,
    })

    config = auto_paper_trading_store.get_config()
    signal = await auto_paper_trading_store._ensure_signal(config)
    portfolio, error = await signalops_store.create_paper_portfolio(signal["signal_id"], {
        "initial_cash": 100000,
        "risk_budget": {"test": "no_long_position"},
        "created_by_agent": "test",
    })
    assert error is None
    assert portfolio

    order = await auto_paper_trading_store._maybe_create_order(
        config,
        signal["signal_id"],
        portfolio,
        {
            "action": "SIM_CLOSE",
            "reason": "unit test no long position",
            "price": 10.0,
            "quantity": 100,
            "source": "unit_test",
            "simulation_only": True,
            "is_real_trade": False,
        },
        force=True,
    )

    assert order == {"error": "no_long_position_to_reduce"}


@pytest.mark.asyncio
async def test_auto_paper_llm_buy_override_recomputes_board_lot_quantity(monkeypatch):
    async def fake_fetch_market_data(profile, symbol):
        return FlatMarketResult()

    async def fake_run_agent_llm(agent_id, run_data, context):
        return BuyLLMResult()

    monkeypatch.setattr(auto_module, "_now", lambda: datetime(2026, 5, 18, 2, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(auto_module, "fetch_market_data", fake_fetch_market_data)
    monkeypatch.setattr(auto_module, "run_agent_llm", fake_run_agent_llm)
    monkeypatch.setattr(auto_module, "get_kline_payload", ready_kline_payload)

    auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663",
        "stock_name": "Unit Test",
        "initial_cash": 100000,
        "min_order_value": 1000,
        "use_llm": True,
        "max_llm_calls_per_day": 6,
        "min_llm_interval_minutes": 120,
        "realtime_interval_seconds": 1,
        "tick_interval_seconds": 5,
        "min_order_interval_seconds": 5,
    })

    result = await auto_paper_trading_store.tick(force=True)

    assert result["status"] == "COMPLETED"
    assert result["decision"]["action"] == "SIM_BUY"
    assert result["order"]["action"] == "SIM_BUY"
    assert result["order"]["simulated_quantity"] == 1500
    assert result["order"]["simulated_quantity"] % 100 == 0


@pytest.mark.asyncio
async def test_auto_paper_tick_persists_structured_error(monkeypatch):
    async def fake_fetch_market_data(profile, symbol):
        raise RuntimeError("market data offline")

    monkeypatch.setattr(auto_module, "fetch_market_data", fake_fetch_market_data)
    monkeypatch.setattr(auto_module, "get_kline_payload", ready_kline_payload)

    auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663",
        "stock_name": "Unit Test",
        "initial_cash": 100000,
        "use_llm": False,
        "realtime_interval_seconds": 1,
        "tick_interval_seconds": 5,
        "min_order_interval_seconds": 5,
    })

    result = await auto_paper_trading_store.tick(force=True)
    config = auto_paper_trading_store.get_config()

    assert result["status"] == "ERROR"
    assert "market data offline" in result["message"]
    assert "market data offline" in config.last_error
    assert config.last_tick_result["status"] == "ERROR"
    assert "market data offline" in config.last_tick_result["warnings"][0]


@pytest.mark.asyncio
async def test_auto_paper_tick_tracks_multiple_symbols_independently(monkeypatch):
    fetched: list[str] = []

    async def fake_fetch_market_data(profile, symbol):
        fetched.append(symbol)
        return FakeMarketResult()

    monkeypatch.setattr(auto_module, "fetch_market_data", fake_fetch_market_data)
    monkeypatch.setattr(auto_module, "get_kline_payload", ready_kline_payload)

    auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663,600879",
        "stock_name": "Unit A,Unit B",
        "initial_cash": 100000,
        "max_position_ratio": 0.5,
        "min_order_value": 1000,
        "use_llm": False,
        "realtime_interval_seconds": 30,
        "tick_interval_seconds": 5,
        "min_order_interval_seconds": 5,
    })

    result = await auto_paper_trading_store.tick(force=False)
    config = auto_paper_trading_store.get_config()

    assert result["status"] == "COMPLETED"
    assert [item["symbol"] for item in result["results"]] == ["603663", "600879"]
    assert fetched == ["603663", "600879"]
    assert set(config.signal_ids) >= {"603663", "600879"}
    assert set(config.last_market_fetch_by_symbol) >= {"603663", "600879"}

    for symbol, signal_id in config.signal_ids.items():
        if symbol in {"603663", "600879"}:
            portfolio = await signalops_store.get_paper_portfolio(signal_id)
            assert portfolio is not None
            assert portfolio["symbol"] == symbol
            assert portfolio["initial_cash"] == 50000
            assert portfolio["risk_budget"]["global_pool_cash"] == 100000
            assert portfolio["risk_budget"]["per_symbol_budget"] == 50000


@pytest.mark.asyncio
async def test_auto_paper_tick_backfills_symbol_placeholder_names_from_quote(monkeypatch):
    names = {
        "603663": "Quote Name A",
        "600879": "Quote Name B",
    }

    async def fake_fetch_market_data(profile, symbol):
        return NamedMarketResult(symbol, names[symbol])

    monkeypatch.setattr(auto_module, "fetch_market_data", fake_fetch_market_data)
    monkeypatch.setattr(auto_module, "get_kline_payload", ready_kline_payload)

    auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663,600879",
        "stock_name": "603663,600879",
        "initial_cash": 100000,
        "min_order_value": 1000,
        "use_llm": False,
        "realtime_interval_seconds": 30,
        "tick_interval_seconds": 5,
        "min_order_interval_seconds": 5,
    })

    result = await auto_paper_trading_store.tick(force=False)
    config = auto_paper_trading_store.get_config()

    assert result["status"] == "COMPLETED"
    assert config.stock_name == "Quote Name A,Quote Name B"
    for symbol, signal_id in config.signal_ids.items():
        if symbol in names:
            detail = await signalops_store.get_signal_detail(signal_id)
            assert detail is not None
            assert detail["signal"]["stock_name"] == names[symbol]


@pytest.mark.asyncio
async def test_auto_paper_llm_only_runs_during_trading_session(monkeypatch):
    calls = {"count": 0}

    async def fake_fetch_market_data(profile, symbol):
        return FakeMarketResult()

    async def fake_run_agent_llm(agent_id, run_data, context):
        calls["count"] += 1
        return FakeLLMResult()

    monkeypatch.setattr(auto_module, "_now", lambda: datetime(2026, 5, 18, 2, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(auto_module, "fetch_market_data", fake_fetch_market_data)
    monkeypatch.setattr(auto_module, "run_agent_llm", fake_run_agent_llm)
    monkeypatch.setattr(auto_module, "get_kline_payload", ready_kline_payload)

    auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663",
        "stock_name": "Unit Test",
        "use_llm": True,
        "max_llm_calls_per_day": 6,
        "min_llm_interval_minutes": 120,
        "realtime_interval_seconds": 1,
        "tick_interval_seconds": 5,
        "min_order_interval_seconds": 5,
    })

    result = await auto_paper_trading_store.tick(force=True)

    assert result["status"] == "COMPLETED"
    assert calls["count"] == 1
    assert result["config"].llm_gate_status == "TRADING_SESSION"
    assert result["config"].llm_calls_used_today == 1
    assert result["decision"]["action"] == "SIM_HOLD"
    assert result["order"] is None


@pytest.mark.asyncio
async def test_auto_paper_llm_blocked_during_lunch_break(monkeypatch):
    calls = {"count": 0}

    async def fake_fetch_market_data(profile, symbol):
        return FakeMarketResult()

    async def fake_run_agent_llm(agent_id, run_data, context):
        calls["count"] += 1
        return FakeLLMResult()

    monkeypatch.setattr(auto_module, "_now", lambda: datetime(2026, 5, 18, 4, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(auto_module, "fetch_market_data", fake_fetch_market_data)
    monkeypatch.setattr(auto_module, "run_agent_llm", fake_run_agent_llm)
    monkeypatch.setattr(auto_module, "get_kline_payload", ready_kline_payload)

    auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663",
        "stock_name": "Unit Test",
        "use_llm": True,
        "max_llm_calls_per_day": 6,
        "min_llm_interval_minutes": 120,
        "realtime_interval_seconds": 1,
        "tick_interval_seconds": 5,
        "min_order_interval_seconds": 5,
    })

    result = await auto_paper_trading_store.tick(force=True)

    assert result["status"] == "COMPLETED"
    assert calls["count"] == 0
    assert "llm_gate_lunch_break" in result["warnings"]
    assert result["config"].llm_gate_status == "LUNCH_BREAK"
    assert result["config"].llm_calls_used_today == 0


@pytest.mark.asyncio
async def test_auto_paper_llm_allows_only_one_after_close_review(monkeypatch):
    calls = {"count": 0}

    async def fake_fetch_market_data(profile, symbol):
        return FakeMarketResult()

    async def fake_run_agent_llm(agent_id, run_data, context):
        calls["count"] += 1
        return FakeLLMResult()

    monkeypatch.setattr(auto_module, "_now", lambda: datetime(2026, 5, 18, 7, 10, tzinfo=timezone.utc))
    monkeypatch.setattr(auto_module, "fetch_market_data", fake_fetch_market_data)
    monkeypatch.setattr(auto_module, "run_agent_llm", fake_run_agent_llm)
    monkeypatch.setattr(auto_module, "get_kline_payload", ready_kline_payload)

    auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663",
        "stock_name": "Unit Test",
        "use_llm": True,
        "max_llm_calls_per_day": 6,
        "min_llm_interval_minutes": 120,
        "realtime_interval_seconds": 1,
        "tick_interval_seconds": 5,
        "min_order_interval_seconds": 5,
    })

    first = await auto_paper_trading_store.tick(force=True)
    second = await auto_paper_trading_store.tick(force=True)

    assert calls["count"] == 1
    assert first["config"].llm_gate_status == "AFTER_CLOSE_REVIEW"
    assert first["config"].last_llm_close_call_date == "2026-05-18"
    assert second["config"].llm_gate_status == "AFTER_CLOSE_REVIEW_USED"
    assert "llm_gate_after_close_review_used" in second["warnings"]
    assert second["config"].llm_calls_used_today == 1


@pytest.mark.asyncio
async def test_auto_paper_after_close_creates_research_daily_review(monkeypatch):
    async def fake_fetch_market_data(profile, symbol):
        return FakeMarketResult()

    monkeypatch.setattr(auto_module, "_now", lambda: datetime(2026, 5, 18, 7, 20, tzinfo=timezone.utc))
    monkeypatch.setattr(auto_module, "fetch_market_data", fake_fetch_market_data)
    monkeypatch.setattr(auto_module, "get_kline_payload", ready_kline_payload)

    auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663",
        "stock_name": "Unit Test",
        "initial_cash": 100000,
        "min_order_value": 1000,
        "use_llm": False,
        "realtime_interval_seconds": 1,
        "tick_interval_seconds": 5,
        "min_order_interval_seconds": 5,
    })

    result = await auto_paper_trading_store.tick(force=True)
    review = result["daily_review"]
    config = auto_paper_trading_store.get_config()

    assert review["status"] == "COMPLETED"
    assert review["trading_date"] == "2026-05-18"
    assert review["loop_id"].startswith("RLOOP_")
    assert review["iteration_id"].startswith("RITER_")
    assert review["case_ids"]
    assert config.last_research_review_date == "2026-05-18"
    assert config.last_research_review["iteration_id"] == review["iteration_id"]

    detail = await signalops_store.get_signal_detail(result["signal_id"])
    assert detail["reviews"][0]["review_type"] == "AUTO_DAILY"

    async with AsyncSessionLocal() as db:
        research_count = (await db.execute(select(ResearchIterationDB))).scalars().all()
        case_count = (await db.execute(select(AgentSimulationCaseDB))).scalars().all()

    assert len(research_count) == 1
    assert len(case_count) == 1


@pytest.mark.asyncio
async def test_auto_paper_auto_tick_runs_after_close_daily_review_once(monkeypatch):
    clock = {"now": datetime(2026, 5, 18, 6, 50, tzinfo=timezone.utc)}

    async def fake_fetch_market_data(profile, symbol):
        return FakeMarketResult()

    monkeypatch.setattr(auto_module, "_now", lambda: clock["now"])
    monkeypatch.setattr(auto_module, "fetch_market_data", fake_fetch_market_data)
    monkeypatch.setattr(auto_module, "get_kline_payload", ready_kline_payload)

    auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663",
        "stock_name": "Unit Test",
        "initial_cash": 100000,
        "min_order_value": 1000,
        "use_llm": False,
        "realtime_interval_seconds": 1,
        "tick_interval_seconds": 5,
        "min_order_interval_seconds": 5,
    })

    before_close = await auto_paper_trading_store.tick()
    assert "daily_review" not in before_close

    clock["now"] = datetime(2026, 5, 18, 7, 20, tzinfo=timezone.utc)
    after_close = await auto_paper_trading_store.tick()
    review = after_close["daily_review"]
    first_config = auto_paper_trading_store.get_config()

    assert review["status"] == "COMPLETED"
    assert review["trading_date"] == "2026-05-18"
    assert first_config.last_research_review_date == "2026-05-18"

    clock["now"] = datetime(2026, 5, 18, 7, 20, 6, tzinfo=timezone.utc)
    second_after_close = await auto_paper_trading_store.tick()
    second_config = auto_paper_trading_store.get_config()

    assert "daily_review" not in second_after_close
    assert second_config.last_research_review_date == "2026-05-18"

    async with AsyncSessionLocal() as db:
        research_iterations = (await db.execute(select(ResearchIterationDB))).scalars().all()

    assert len(research_iterations) == 1


@pytest.mark.asyncio
async def test_daily_research_review_tightens_next_day_parameters_after_negative_pnl(monkeypatch):
    clock = {"now": datetime(2026, 5, 18, 2, 0, tzinfo=timezone.utc)}

    async def fake_fetch_market_data(profile, symbol):
        return FakeMarketResult()

    monkeypatch.setattr(auto_module, "_now", lambda: clock["now"])
    monkeypatch.setattr(auto_module, "fetch_market_data", fake_fetch_market_data)
    monkeypatch.setattr(auto_module, "get_kline_payload", ready_kline_payload)

    auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663",
        "stock_name": "Unit Test",
        "initial_cash": 100000,
        "min_order_value": 1000,
        "use_llm": False,
        "realtime_interval_seconds": 1,
        "tick_interval_seconds": 5,
        "min_order_interval_seconds": 5,
    })

    tick = await auto_paper_trading_store.tick(force=True)
    await signalops_store.mark_paper_portfolio_to_market(tick["signal_id"], 9.0)

    clock["now"] = datetime(2026, 5, 18, 7, 20, tzinfo=timezone.utc)
    review = await auto_paper_trading_store.run_daily_research_review(force=True)
    config = auto_paper_trading_store.get_config()

    assert review["status"] == "COMPLETED"
    assert "strategy_experiment" in review["review_fields"]
    assert review["tuning_update"]["risk_tightened"] is True
    assert review["tuning_update"]["application_status"] == "RECOMMENDED_ONLY"
    assert "insufficient_trade_count" in review["tuning_update"]["application_reason"]
    assert review["tuning_update"]["strategy_experiment"]["promotion_status"] == "RECOMMENDED_ONLY"
    assert review["tuning_update"]["strategy_experiment"]["winner_config_id"] == "baseline"
    assert review["tuning_update"]["candidate_factor_adjustments"]["ai_dynamic_positive"]["buy_threshold_delta"] > 0
    assert "ai_dynamic_positive" not in review["tuning_update"]["applied_factor_adjustments"]
    assert config.buy_change_threshold_pct == 0.5
    assert config.close_change_threshold_pct == -2.0
    assert "ai_dynamic_positive" not in config.factor_adjustments
    assert len(config.cleaned_record_history) == 1
    assert config.performance_stats["global"]["all"]["trade_count"] == 1
    assert config.performance_stats["global"]["all"]["failures"] == 1
    assert config.performance_stats["factors"]["ai_dynamic_positive"]["failures"] == 1
    tuned_buy_threshold = config.buy_change_threshold_pct
    tuned_close_threshold = config.close_change_threshold_pct

    skipped = await auto_paper_trading_store.run_daily_research_review()
    config_after_skip = auto_paper_trading_store.get_config()

    assert skipped["status"] == "SKIPPED"
    assert skipped["warnings"] == ["daily_review_already_completed"]
    assert config_after_skip.buy_change_threshold_pct == tuned_buy_threshold
    assert config_after_skip.close_change_threshold_pct == tuned_close_threshold

    async with AsyncSessionLocal() as db:
        research_iterations = (await db.execute(select(ResearchIterationDB))).scalars().all()

    assert len(research_iterations) == 1

    decision = auto_paper_trading_store._decide(
        config,
        {"available_cash": 100000, "market_value": 0},
        {"quote": {"price": 10.0, "changePercent": 0.55}},
        bottom_candidate_kline_snapshot(),
        None,
    )
    assert decision["action"] == "SIM_BUY"
    assert decision["buyChangeThresholdPct"] == 0.5
    assert decision["performanceQuality"]["status"] == "LOW_SAMPLE"


def test_daily_tuning_uses_confidence_and_severity_weighting():
    def record(pnl_rate, max_drawdown, invalidation, source, order_count=1, trading_date="2026-05-18"):
        return {
            "trading_date": trading_date,
            "pnl_rate": pnl_rate,
            "max_drawdown": max_drawdown,
            "invalidation_triggered": invalidation,
            "factor_sources": [source],
            "order_count": order_count,
        }

    config = auto_paper_trading_store.get_config()
    mild = auto_paper_trading_store._build_daily_tuning_update(
        config,
        [record(-0.015, -0.012, True, "ai_dynamic_probe")],
    )
    severe = auto_paper_trading_store._build_daily_tuning_update(
        config,
        [
            record(-0.12, -0.11, True, "ai_dynamic_probe", trading_date="2026-05-11"),
            record(-0.07, -0.09, True, "ai_dynamic_probe", trading_date="2026-05-12"),
            record(-0.04, -0.05, True, "ai_dynamic_probe", trading_date="2026-05-13"),
            record(-0.03, -0.04, True, "ai_dynamic_probe", trading_date="2026-05-14"),
            record(-0.025, -0.03, True, "ai_dynamic_probe", trading_date="2026-05-15"),
            record(0.035, -0.005, False, "ai_dynamic_probe", trading_date="2026-05-18"),
            record(0.045, -0.005, False, "ai_dynamic_probe", trading_date="2026-05-19"),
            record(0.055, -0.005, False, "ai_dynamic_probe", trading_date="2026-05-20"),
        ],
    )

    assert mild["adjustment_model"] == "weighted_bayesian_decay_v3"
    assert mild["application_status"] == "RECOMMENDED_ONLY"
    assert severe["application_status"] == "BACKTEST_PENDING"
    assert severe["walk_forward_validation"]["method"] == "capped_trade_record_history_v1"
    assert severe["walk_forward_validation"]["status"] == "PASSED"
    assert severe["walk_forward_validation"]["checks"]["validation_trade_count_min"] == 3
    assert severe["walk_forward_validation"]["checks"]["benchmark_available"] is False
    assert severe["strategy_experiment"]["promotion_status"] == "BACKTEST_PENDING"
    assert severe["strategy_experiment"]["experiment_package_hash"].startswith("sigops-")
    assert severe["strategy_experiment"]["winner_config_id"] == "baseline"
    assert "kline_strategy" in severe["strategy_experiment"]["candidate_config"]
    assert "ladder_buy_policy" in severe["strategy_experiment"]["candidate_config"]
    assert severe["candidate_evidence_package"]["kline_evidence_package"]["simulation_only"] is True
    assert severe["kline_evidence_package"]["kline_signal_quality"]["simulation_only"] is True
    assert {
        "experiment_id",
        "experiment_package_hash",
        "baseline_config",
        "candidate_config",
        "candidate_reason",
        "promotion_gate",
        "winner_config_id",
        "promotion_status",
        "evidence_links",
    } <= set(severe["strategy_experiment"])
    assert severe["tuning_confidence"] > mild["tuning_confidence"]
    assert severe["nonlinear_adjustment"] > mild["nonlinear_adjustment"]
    assert severe["recommended_parameters"]["buy_change_threshold_pct"] > mild["recommended_parameters"]["buy_change_threshold_pct"]
    assert severe["recommended_parameters"]["close_change_threshold_pct"] > mild["recommended_parameters"]["close_change_threshold_pct"]
    assert severe["recommended_parameters"]["probe_position_ratio"] < mild["recommended_parameters"]["probe_position_ratio"]
    assert severe["next_parameters"] == {}
    assert severe["candidate_factor_adjustments"]["ai_dynamic_probe"]["buy_threshold_delta"] > mild["candidate_factor_adjustments"]["ai_dynamic_probe"]["buy_threshold_delta"]
    assert severe["candidate_factor_adjustments"]["ai_dynamic_probe"]["position_ratio_delta"] < mild["candidate_factor_adjustments"]["ai_dynamic_probe"]["position_ratio_delta"]
    assert "ai_dynamic_probe" not in severe["applied_factor_adjustments"]


def test_daily_tuning_experiment_package_hash_is_stable_and_sample_sensitive():
    def record(pnl_rate, trading_date, order_id):
        return {
            "trading_date": trading_date,
            "symbol": "603663",
            "latest_order_id": order_id,
            "pnl_rate": pnl_rate,
            "max_drawdown": min(pnl_rate, 0),
            "invalidation_triggered": pnl_rate < 0,
            "factor_sources": ["ai_dynamic_probe"],
            "order_count": 1,
        }

    records = [
        record(-0.12, "2026-05-11", "ORD_1"),
        record(-0.07, "2026-05-12", "ORD_2"),
        record(-0.04, "2026-05-13", "ORD_3"),
        record(-0.03, "2026-05-14", "ORD_4"),
        record(-0.025, "2026-05-15", "ORD_5"),
        record(0.035, "2026-05-18", "ORD_6"),
        record(0.045, "2026-05-19", "ORD_7"),
        record(0.055, "2026-05-20", "ORD_8"),
    ]
    config = auto_paper_trading_store.get_config()
    first = auto_paper_trading_store._build_daily_tuning_update(config, records, review_date="2026-05-20")
    second = auto_paper_trading_store._build_daily_tuning_update(config, records, review_date="2026-05-20")
    changed = auto_paper_trading_store._build_daily_tuning_update(
        config,
        [*records[:-1], record(0.055, "2026-05-20", "ORD_CHANGED")],
        review_date="2026-05-20",
    )

    first_hash = first["strategy_experiment"]["experiment_package_hash"]
    assert first_hash == second["strategy_experiment"]["experiment_package_hash"]
    assert first_hash != changed["strategy_experiment"]["experiment_package_hash"]
    assert first["candidate_evidence_package"]["experiment_package_hash"] == first_hash


def test_review_queue_item_includes_server_parameter_diff_summary():
    def record(pnl_rate, max_drawdown, invalidation, trading_date):
        return {
            "trading_date": trading_date,
            "symbol": "603663",
            "pnl_rate": pnl_rate,
            "max_drawdown": max_drawdown,
            "invalidation_triggered": invalidation,
            "factor_sources": ["ai_dynamic_probe"],
            "order_count": 1,
        }

    config = auto_paper_trading_store.get_config()
    tuning = auto_paper_trading_store._build_daily_tuning_update(
        config,
        [
            record(-0.12, -0.11, True, "2026-05-11"),
            record(-0.07, -0.09, True, "2026-05-12"),
            record(-0.04, -0.05, True, "2026-05-13"),
            record(-0.03, -0.04, True, "2026-05-14"),
            record(-0.025, -0.03, True, "2026-05-15"),
            record(0.035, -0.005, False, "2026-05-18"),
            record(0.045, -0.005, False, "2026-05-19"),
            record(0.055, -0.005, False, "2026-05-20"),
        ],
        review_date="2026-05-20",
    )

    item = auto_paper_trading_store._review_queue_item_from_tuning(
        tuning_update=tuning,
        review_date="2026-05-20",
        reviewed_symbols=[{"symbol": "603663"}],
        evidence_links=[],
    )

    assert item is not None
    summary = item["parameter_diff_summary"]
    assert summary["policy_id"] == "signalops_candidate_parameter_diff_v1"
    assert summary["source"] == "server_generated"
    assert summary["status"] == "CHANGED"
    assert summary["changed_count"] >= 1
    assert summary["total_parameter_count"] >= summary["changed_count"]
    assert summary["simulation_only"] is True
    assert summary["is_real_trade"] is False
    assert any(row["key"] == "buy_change_threshold_pct" for row in summary["rows"])
    assert item["strategy_experiment"]["parameter_diff_summary"] == summary
    assert item["strategy_experiment"]["baseline_config"] == item["baseline_config"]
    assert item["strategy_experiment"]["candidate_config"] == item["candidate_config"]
    assert "parameter_diff_summary" in item["review_fields"]


def test_cleaned_record_history_normalizes_required_quality_fields():
    records = auto_module._capped_cleaned_record_history([
        {
            "trading_date": "2026-05-18",
            "symbol": "603663",
            "signal_id": "SIG_1",
            "latest_order_id": "ORD_1",
            "latest_action": "SIM_BUY",
            "pnl_rate": 0.035,
            "max_drawdown": -0.005,
            "order_count": 1,
            "invalidation_triggered": False,
        },
        {
            "trading_date": "2026-05-18",
            "symbol": "002846",
            "signal_id": "SIG_2",
            "latest_action": "NONE",
            "pnl_rate": 0,
            "max_drawdown": 0,
            "order_count": 0,
            "invalidation_triggered": False,
        },
    ])

    traded = records[1] if records[1]["symbol"] == "603663" else records[0]
    idle = records[0] if records[0]["symbol"] == "002846" else records[1]

    assert {
        "record_id",
        "signal_date",
        "symbol",
        "source_type",
        "source_id",
        "decision_id",
        "outcome",
        "pnl_rate",
        "sample_quality",
        "evidence_refs",
    } <= set(traded)
    assert traded["outcome"] == "WIN"
    assert traded["sample_quality"] == "STRONG"
    assert traded["simulation_only"] is True
    assert traded["is_real_trade"] is False
    assert idle["outcome"] == "NO_TRADE"
    assert idle["sample_quality"] == "SUPPORTING_ONLY"


def test_low_quality_walk_forward_cannot_be_ready_for_review():
    def record(trading_date, pnl_rate):
        return {
            "trading_date": trading_date,
            "symbol": "603663",
            "pnl_rate": pnl_rate,
            "max_drawdown": min(pnl_rate, 0),
            "invalidation_triggered": pnl_rate < 0,
            "factor_sources": ["ai_dynamic_probe"],
            "order_count": 1,
            "sample_quality": "LOW",
        }

    config = auto_paper_trading_store.get_config()
    update = auto_paper_trading_store._build_daily_tuning_update(
        config,
        [
            record("2026-05-11", -0.08),
            record("2026-05-12", -0.07),
            record("2026-05-13", -0.06),
            record("2026-05-14", -0.05),
            record("2026-05-15", -0.04),
            record("2026-05-18", 0.04),
            record("2026-05-19", 0.05),
            record("2026-05-20", 0.06),
        ],
    )

    assert update["application_status"] == "RECOMMENDED_ONLY"
    assert update["walk_forward_validation"]["status"] == "PENDING"
    assert "low_quality_evidence" in update["walk_forward_validation"]["reasons"]
    assert update["applied_parameters"] == {}
    assert update["strategy_experiment"]["winner_config_id"] == "baseline"


@pytest.mark.asyncio
async def test_review_decision_approval_applies_ready_candidate_to_simulation_only():
    def record(pnl_rate, max_drawdown, invalidation, trading_date):
        return {
            "trading_date": trading_date,
            "symbol": "603663",
            "pnl_rate": pnl_rate,
            "max_drawdown": max_drawdown,
            "invalidation_triggered": invalidation,
            "factor_sources": ["ai_dynamic_probe"],
            "order_count": 1,
        }

    config = auto_paper_trading_store.update_config({
        "symbol": "603663",
        "stock_name": "Unit Test",
        "initial_cash": 100000,
        "use_llm": False,
    })
    tuning = auto_paper_trading_store._build_daily_tuning_update(
        config,
        [
            record(-0.12, -0.11, True, "2026-05-11"),
            record(-0.07, -0.09, True, "2026-05-12"),
            record(-0.04, -0.05, True, "2026-05-13"),
            record(-0.03, -0.04, True, "2026-05-14"),
            record(-0.025, -0.03, True, "2026-05-15"),
            record(0.035, -0.005, False, "2026-05-18"),
            record(0.045, -0.005, False, "2026-05-19"),
            record(0.055, -0.005, False, "2026-05-20"),
        ],
        review_date="2026-05-20",
    )
    assert tuning["application_status"] == "BACKTEST_PENDING"

    item = auto_paper_trading_store._review_queue_item_from_tuning(
        tuning_update=tuning,
        review_date="2026-05-20",
        reviewed_symbols=[{"symbol": "603663"}],
        evidence_links=[],
    )
    item["candidate_status"] = "READY_FOR_REVIEW"
    item["promotion_status"] = "READY_FOR_REVIEW"
    item["review_allowed"] = True
    item["evidence_quality"] = "MEDIUM"
    item["benchmark_comparison"] = {"symbol": "000300.SH", "available": True, "status": "AVAILABLE"}
    state = auto_paper_trading_store._load_state()
    state["review_queue_state"] = auto_paper_trading_store._merge_review_queue_state(
        state.get("review_queue_state"),
        queue_item=item,
    )
    auto_paper_trading_store._save_state(state)

    result = await auto_paper_trading_store.record_review_decision({
        "queue_item_id": item["queue_item_id"],
        "action": "APPROVE_SIMULATION_CANDIDATE",
        "reviewer": "human",
        "reason": "approved for simulation only",
    })
    next_config = result["config"]

    assert result["status"] == "COMPLETED"
    assert result["decision"]["result_status"] == "APPLIED_TO_SIMULATION"
    assert result["decision"]["simulation_only"] is True
    assert result["decision"]["is_real_trade"] is False
    assert result["decision"]["parameter_diff_checksum"].startswith("sigops-paramdiff-")
    assert result["decision"]["parameter_diff_summary"]["policy_id"] == "signalops_candidate_parameter_diff_v1"
    assert result["decision"]["parameter_diff_summary"]["simulation_only"] is True
    assert result["decision"]["parameter_diff_summary"]["is_real_trade"] is False
    assert result["decision"]["review_decision_summary"]["parameter_diff_checksum"] == result["decision"]["parameter_diff_checksum"]
    assert "parameter_diff_checksum" in result["decision"]["review_fields"]
    assert "review_event_hash" in result["decision"]["review_fields"]
    assert result["queue_item"]["reviewed_parameter_diff_checksum"] == result["decision"]["parameter_diff_checksum"]
    assert result["queue_item"]["reviewed_parameter_diff_summary"] == result["decision"]["parameter_diff_summary"]
    assert result["decision"]["review_event_hash"].startswith("sigops-reviewevent-")
    assert result["queue_item"]["review_event_hash"] == result["decision"]["review_event_hash"]
    event_file = auto_module._review_decision_event_file()
    assert event_file.exists()
    event_lines = [json.loads(line) for line in event_file.read_text(encoding="utf-8").splitlines()]
    assert event_lines[-1]["event_hash"] == result["decision"]["review_event_hash"]
    assert event_lines[-1]["parameter_diff_checksum"] == result["decision"]["parameter_diff_checksum"]
    assert event_lines[-1]["parameter_diff_summary"] == result["decision"]["parameter_diff_summary"]
    exported_events = auto_paper_trading_store.export_review_decision_events(limit=10)
    assert exported_events["schema"] == "signalops_review_decision_event_export_v1"
    assert exported_events["bundle_checksum"].startswith("sigops-reviewevents-")
    assert exported_events["latest_event_hash"] == result["decision"]["review_event_hash"]
    assert exported_events["events"][-1]["decision_id"] == result["decision"]["decision_id"]
    assert next_config.buy_change_threshold_pct == tuning["recommended_parameters"]["buy_change_threshold_pct"]
    assert next_config.factor_adjustments == tuning["candidate_factor_adjustments"]
    status = auto_paper_trading_store.get_status()
    assert status["review_decisions"][-1]["action"] == "APPROVE_SIMULATION_CANDIDATE"
    assert status["review_decisions"][-1]["parameter_diff_checksum"] == result["decision"]["parameter_diff_checksum"]
    assert status["review_decision_event_ledger"]["event_count"] == 1
    assert status["review_decision_event_ledger"]["latest_event_hash"] == result["decision"]["review_event_hash"]
    assert status["review_queue_state"]["items"][-1]["candidate_status"] == "APPLIED_TO_SIMULATION"
    assert status["review_queue_state"]["items"][-1]["reviewed_parameter_diff_checksum"] == result["decision"]["parameter_diff_checksum"]


@pytest.mark.asyncio
async def test_low_risk_ready_candidate_auto_approves_after_backtest_sync():
    experiment_hash = "EXP_AUTO_LOW_RISK"
    auto_paper_trading_store.update_config({
        "symbol": "603663",
        "stock_name": "Unit Test",
        "initial_cash": 100000,
        "buy_change_threshold_pct": 0.5,
        "use_llm": False,
    })
    state = auto_paper_trading_store._load_state()
    state["review_queue_state"] = {
        "version": 1,
        "items": [
            {
                "id": "rq-auto-low",
                "queue_item_id": "rq-auto-low",
                "experiment_id": "signalops-exp-auto-low",
                "experiment_package_hash": experiment_hash,
                "symbol": "603663",
                "candidate_status": "BACKTEST_PENDING",
                "promotion_status": "BACKTEST_PENDING",
                "review_allowed": False,
                "review_decision": "CONTINUE_OBSERVING",
                "risk_level": "LOW",
                "evidence_quality": "MEDIUM",
                "candidate_config": {"buy_change_threshold_pct": 0.9},
                "simulation_only": True,
                "is_real_trade": False,
            }
        ],
        "observations": [],
        "counts": {"backtest_pending": 1},
        "simulation_only": True,
        "is_real_trade": False,
    }
    auto_paper_trading_store._save_state(state)

    queue_state = await auto_paper_trading_store.record_backtest_experiment_result({
        "experiment_package_hash": experiment_hash,
        "promotion_status": "READY_FOR_REVIEW",
        "walk_forward_validation": {
            "status": "PASS",
            "sample_quality": "MEDIUM",
            "reasons": ["validation_passed"],
        },
        "benchmark_comparison": {"symbol": "000300.SH", "available": True, "status": "AVAILABLE"},
        "research_evidence_package": {"sample_quality": "MEDIUM"},
        "walk_forward_run_ids": {
            "baseline_validation": "run-baseline",
            "candidate_validation": "run-candidate",
        },
    })

    config = auto_paper_trading_store.get_config()
    status = auto_paper_trading_store.get_status()

    assert config.buy_change_threshold_pct == 0.9
    assert queue_state["items"][0]["candidate_status"] == "APPLIED_TO_SIMULATION"
    assert status["review_decisions"][-1]["reviewer"] == "auto_low_risk_reviewer"
    assert status["review_decisions"][-1]["reason"] == "low_risk_auto_approval"
    assert "low_risk_auto_approval" in status["review_decisions"][-1]["review_fields"]
    assert status["review_decisions"][-1]["simulation_only"] is True
    assert status["review_decisions"][-1]["is_real_trade"] is False


@pytest.mark.asyncio
async def test_medium_risk_ready_candidate_still_requires_human_review_after_backtest_sync():
    experiment_hash = "EXP_AUTO_MEDIUM_RISK"
    auto_paper_trading_store.update_config({
        "symbol": "603663",
        "stock_name": "Unit Test",
        "initial_cash": 100000,
        "buy_change_threshold_pct": 0.5,
        "use_llm": False,
    })
    state = auto_paper_trading_store._load_state()
    state["review_queue_state"] = {
        "version": 1,
        "items": [
            {
                "id": "rq-auto-medium",
                "queue_item_id": "rq-auto-medium",
                "experiment_id": "signalops-exp-auto-medium",
                "experiment_package_hash": experiment_hash,
                "symbol": "603663",
                "candidate_status": "BACKTEST_PENDING",
                "promotion_status": "BACKTEST_PENDING",
                "review_allowed": False,
                "review_decision": "CONTINUE_OBSERVING",
                "risk_level": "MEDIUM",
                "evidence_quality": "MEDIUM",
                "candidate_config": {"buy_change_threshold_pct": 0.9},
                "simulation_only": True,
                "is_real_trade": False,
            }
        ],
        "observations": [],
        "counts": {"backtest_pending": 1},
        "simulation_only": True,
        "is_real_trade": False,
    }
    auto_paper_trading_store._save_state(state)

    queue_state = await auto_paper_trading_store.record_backtest_experiment_result({
        "experiment_package_hash": experiment_hash,
        "promotion_status": "READY_FOR_REVIEW",
        "walk_forward_validation": {
            "status": "PASS",
            "sample_quality": "MEDIUM",
            "reasons": ["validation_passed"],
        },
        "benchmark_comparison": {"symbol": "000300.SH", "available": True, "status": "AVAILABLE"},
        "research_evidence_package": {"sample_quality": "MEDIUM"},
        "walk_forward_run_ids": {
            "baseline_validation": "run-baseline",
            "candidate_validation": "run-candidate",
        },
    })

    config = auto_paper_trading_store.get_config()
    status = auto_paper_trading_store.get_status()

    assert config.buy_change_threshold_pct == 0.5
    assert queue_state["items"][0]["candidate_status"] == "READY_FOR_REVIEW"
    assert queue_state["items"][0]["review_decision"] == "PENDING_REVIEW"
    assert status["review_decisions"] == []


def test_daily_tuning_compresses_idle_samples_without_polluting_trade_history():
    def record(pnl_rate, max_drawdown, invalidation, source, order_count=1):
        return {
            "pnl_rate": pnl_rate,
            "max_drawdown": max_drawdown,
            "invalidation_triggered": invalidation,
            "factor_sources": [source],
            "order_count": order_count,
        }

    config = auto_paper_trading_store.update_config({
        "factor_adjustments": {
            "ai_dynamic_probe": {
                "sample_count": 10,
                "wins": 8,
                "losses": 2,
                "weighted_wins": 9.0,
                "weighted_losses": 2.0,
                "evidence_weight": 11.0,
                "prior_decay": 0.5,
            }
        }
    })
    idle_loss = auto_paper_trading_store._build_daily_tuning_update(
        config,
        [record(-0.03, -0.02, True, "ai_dynamic_probe", order_count=0)],
    )
    traded_loss = auto_paper_trading_store._build_daily_tuning_update(
        config,
        [record(-0.03, -0.02, True, "ai_dynamic_probe", order_count=1)],
    )

    traded_factor = traded_loss["candidate_factor_adjustments"]["ai_dynamic_probe"]

    assert idle_loss["sample_count"] == 0
    assert idle_loss["trade_count"] == 0
    assert idle_loss["current_no_trade_count"] == 1
    assert idle_loss["compressed_observation_count"] == 1
    assert idle_loss["compressed_observation_history"]["total_count"] == 1
    assert idle_loss["performance_stats"]["global"]["all"]["no_trade_count"] == 1
    assert "UNKNOWN" in idle_loss["compressed_observation_history"]["buckets"][0]["symbols"]
    assert traded_factor["sample_count"] == 6
    assert idle_loss["evidence_weight"] < traded_loss["evidence_weight"]


def test_daily_tuning_tracks_rolling_performance_stats():
    def record(symbol, pnl_rate, invalidation, source, trigger, order_count=1):
        return {
            "symbol": symbol,
            "pnl_rate": pnl_rate,
            "max_drawdown": min(pnl_rate, 0),
            "invalidation_triggered": invalidation,
            "factor_sources": [source],
            "trigger_conditions": [trigger],
            "order_count": order_count,
        }

    config = auto_paper_trading_store.get_config()
    update = auto_paper_trading_store._build_daily_tuning_update(
        config,
        [
            record("603663", 0.03, False, "ai_dynamic_probe", "breakout"),
            record("603663", -0.03, True, "ai_dynamic_probe", "breakout"),
            record("002846", 0.00, False, "ai_dynamic_watch", "observe", order_count=0),
        ],
    )

    global_stats = update["performance_stats"]["global"]["all"]
    assert global_stats["sample_count"] == 3
    assert global_stats["trade_count"] == 2
    assert global_stats["wins"] == 1
    assert global_stats["failures"] == 1
    assert global_stats["no_trade_count"] == 1
    assert global_stats["win_rate"] == 0.5
    assert update["performance_stats"]["symbols"]["603663"]["trade_count"] == 2
    assert update["performance_stats"]["factors"]["ai_dynamic_probe"]["win_rate"] == 0.5
    assert update["performance_stats"]["triggers"]["observe"]["no_trade_count"] == 1


def test_performance_quality_blocks_poor_simulated_buy():
    config = auto_paper_trading_store.update_config({
        "symbol": "603663",
        "stock_name": "Unit Test",
        "initial_cash": 100000,
        "min_order_value": 1000,
        "performance_stats": {
            "version": 1,
            "factors": {
                "ai_dynamic_probe": {
                    "trade_count": 8,
                    "sample_count": 8,
                    "wins": 1,
                    "failures": 7,
                    "win_rate": 0.125,
                    "expectancy": -0.03,
                    "max_drawdown": -0.12,
                    "confidence": 0.82,
                    "quality_status": "POOR",
                }
            },
        },
    })

    decision = auto_paper_trading_store._decide(
        config,
        {"available_cash": 100000, "market_value": 0},
        {"status": "READY", "quote": {"price": 10.0, "changePercent": 0.55}},
        {},
        None,
    )

    assert decision["action"] == "SIM_HOLD"
    assert decision["pre_buy_quality"]["action_policy"] == "HOLD"
    assert decision["pre_buy_quality"]["grade"] == "BLOCKED"
    assert decision["pre_buy_quality"]["score"] >= 0
    assert decision["pre_buy_quality"]["components"]["win_rate"] == 0.125
    assert decision["performanceQuality"]["actionPolicy"] == "HOLD"
    assert decision["performanceQuality"]["status"] == "POOR"
    assert decision["buyChangeThresholdPct"] > config.buy_change_threshold_pct


def test_clean_daily_record_treats_short_cover_as_invalidation_review():
    config = auto_paper_trading_store.get_config()

    record = auto_paper_trading_store._clean_daily_signal_record(
        trading_date="2026-05-20",
        symbol="603663",
        signal={
            "signal_id": "SIG_TEST",
            "status": "PAPER_TEST",
            "trigger_conditions": [],
            "invalidation_conditions": [],
        },
        portfolio={
            "available_cash": 100000,
            "market_value": 0,
            "initial_cash": 100000,
            "risk_budget": {},
        },
        positions=[],
        orders=[],
        day_orders=[{
            "order_id": "ORDER_TEST",
            "action": "SIM_COVER",
            "fill_status": "FILLED",
            "simulated_price": 12.0,
            "simulated_quantity": 1500,
            "risk_constraints": {"position_ratio_source": "ai_dynamic_watch"},
        }],
        config=config,
    )

    assert record["invalidation_triggered"] is True
    assert "AI_INVALIDATION_REVIEW" in record["failure_tags"]
    assert record["factor_sources"] == ["ai_dynamic_watch"]


@pytest.mark.asyncio
async def test_auto_paper_tick_respects_tick_interval(monkeypatch):
    async def fake_fetch_market_data(profile, symbol):
        return FakeMarketResult()

    monkeypatch.setattr(auto_module, "fetch_market_data", fake_fetch_market_data)
    auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663",
        "use_llm": False,
        "tick_interval_seconds": 60,
    })

    first = await auto_paper_trading_store.tick(force=False)
    second = await auto_paper_trading_store.tick(force=False)

    assert first["status"] == "COMPLETED"
    assert second["status"] == "SKIPPED"
    assert "未到下一次" in second["message"]
