import pytest
from uuid import uuid4

from app.core.signalops_store import signalops_store


@pytest.mark.asyncio
async def test_signal_lifecycle_blocks_qualified_when_dvg_review_only():
    signal = await signalops_store.create_signal({
        "symbol": "603663",
        "stock_name": "三祥新材",
        "source_run_id": "RUN_P2_REVIEW_ONLY",
        "risk_passed": True,
        "dvg_passed": False,
        "dvg_status": "REVIEW_ONLY",
        "qiam_passed": True,
        "trigger_conditions": ["突破平台"],
        "invalidation_conditions": ["跌破止损线"],
    })

    transition, error = await signalops_store.transition_signal(signal["signal_id"], {
        "target_status": "QUALIFIED",
        "reason": "try qualified",
        "gate_context": {"basic_analysis_completed": True},
    })

    assert transition is not None
    assert transition["passed"] is False
    assert transition["simulation_only"] is True
    assert transition["is_real_trade"] is False
    assert "DVG REVIEW_ONLY" in error

    detail = await signalops_store.get_signal_detail(signal["signal_id"])
    assert detail["signal"]["status"] == "IDEA"
    assert detail["signal"]["audit_id"]
    assert detail["transitions"][0]["simulation_only"] is True
    assert detail["transitions"][0]["is_real_trade"] is False


@pytest.mark.asyncio
async def test_signal_conditions_can_be_updated_before_paper_test():
    signal = await signalops_store.create_signal({
        "symbol": "603663",
        "source_run_id": "RUN_P2_CONDITION_OPTIONS",
        "risk_passed": True,
        "dvg_passed": True,
        "qiam_passed": True,
    })

    updated = await signalops_store.update_signal_conditions(signal["signal_id"], {
        "trigger_conditions": ["volume_breakout", "price_reclaims_ma20"],
        "invalidation_conditions": ["close_below_ma20"],
        "review_fields": ["volume", "trend"],
    })

    assert updated is not None
    assert updated["trigger_conditions"] == ["volume_breakout", "price_reclaims_ma20"]
    assert updated["invalidation_conditions"] == ["close_below_ma20"]
    assert updated["review_fields"] == ["volume", "trend"]

    transition, error = await signalops_store.transition_signal(signal["signal_id"], {
        "target_status": "PAPER_TEST",
        "reason": "enter paper test after condition selection",
    })

    assert error is None
    assert transition["passed"] is True
    assert transition["simulation_only"] is True
    assert transition["is_real_trade"] is False


@pytest.mark.asyncio
async def test_signal_conditions_patch_preserves_omitted_lists():
    signal = await signalops_store.create_signal({
        "symbol": "603663",
        "source_run_id": "RUN_P2_CONDITION_PATCH",
        "risk_passed": True,
        "dvg_passed": True,
        "qiam_passed": True,
        "trigger_conditions": ["volume_breakout"],
        "invalidation_conditions": ["close_below_ma20"],
        "review_fields": ["volume"],
    })

    updated = await signalops_store.update_signal_conditions(signal["signal_id"], {
        "review_fields": ["volume", "trend"],
    })

    assert updated is not None
    assert updated["trigger_conditions"] == ["volume_breakout"]
    assert updated["invalidation_conditions"] == ["close_below_ma20"]
    assert updated["review_fields"] == ["volume", "trend"]


@pytest.mark.asyncio
async def test_paper_portfolio_records_sim_actions_only_and_creates_knowledge_case():
    signal = await signalops_store.create_signal({
        "symbol": "603663",
        "source_run_id": "RUN_P2_PAPER",
        "risk_passed": True,
        "dvg_passed": True,
        "qiam_passed": True,
        "execution_reachable": True,
        "trigger_conditions": ["价格放量突破"],
        "invalidation_conditions": ["收盘跌破突破位"],
    })
    transition, error = await signalops_store.transition_signal(signal["signal_id"], {
        "target_status": "PAPER_TEST",
        "reason": "enter paper test",
    })
    assert error is None
    assert transition["passed"] is True

    portfolio, error = await signalops_store.create_paper_portfolio(signal["signal_id"], {
        "initial_cash": 100000,
        "risk_budget": {"max_single_symbol_weight": 0.2},
    })
    assert error is None
    assert portfolio["simulation_only"] is True
    assert portfolio["is_real_trade"] is False

    order, error = await signalops_store.create_paper_order(signal["signal_id"], {
        "action": "SIM_BUY",
        "action_reason": "only paper-test validation",
        "simulated_price": 10,
        "simulated_quantity": 100,
        "risk_constraints": {"simulation_only": True, "is_real_trade": False},
        "data_snapshot_hash": "hash-paper-test",
    })
    assert error is None
    assert order["action"] == "SIM_BUY"
    assert order["simulation_only"] is True
    assert order["is_real_trade"] is False

    invalid_order, error = await signalops_store.create_paper_order(signal["signal_id"], {
        "action": "BUY",
        "simulated_price": 10,
        "simulated_quantity": 100,
        "simulation_only": False,
        "is_real_trade": True,
    })
    assert invalid_order is None
    assert "SIM_BUY" in error

    filled, error = await signalops_store.fill_paper_order(signal["signal_id"], order["order_id"], {
        "filled_price": 10,
        "filled_quantity": 100,
        "fees": 1,
        "slippage": 0.001,
    })
    assert error is None
    assert filled["fill_status"] == "FILLED"
    portfolio_after_fill = await signalops_store.get_paper_portfolio(signal["signal_id"])

    repeated, error = await signalops_store.fill_paper_order(signal["signal_id"], order["order_id"], {
        "filled_price": 99,
        "filled_quantity": 999,
        "fees": 99,
    })
    assert error is None
    assert repeated["fill_status"] == "FILLED"
    portfolio_after_repeat = await signalops_store.get_paper_portfolio(signal["signal_id"])
    assert portfolio_after_repeat["available_cash"] == portfolio_after_fill["available_cash"]
    assert portfolio_after_repeat["market_value"] == portfolio_after_fill["market_value"]

    case, error = await signalops_store.create_agent_simulation_case(signal["signal_id"], {
        "source_paper_order_id": order["order_id"],
        "outcome": {"future_return": 0.02},
        "failure_tags": [],
    })
    assert error is None
    assert case["case_source"] == "AGENT_SIMULATION"
    assert case["operator_type"] == "AGENT"
    assert case["simulation_only"] is True
    assert case["is_real_trade"] is False


@pytest.mark.asyncio
async def test_paper_portfolio_allows_sandbox_actions_before_trade_gates_pass():
    signal = await signalops_store.create_signal({
        "symbol": "603663",
        "source_run_id": "RUN_P2_SANDBOX",
        "risk_passed": False,
        "dvg_passed": False,
        "qiam_passed": False,
        "execution_reachable": False,
        "trigger_conditions": [],
        "invalidation_conditions": [],
    })

    portfolio, error = await signalops_store.create_paper_portfolio(signal["signal_id"], {
        "initial_cash": 100000,
    })
    assert error is None
    assert portfolio["simulation_only"] is True
    assert portfolio["is_real_trade"] is False

    order, error = await signalops_store.create_paper_order(signal["signal_id"], {
        "action": "SIM_BUY",
        "action_reason": "sandbox exploration despite incomplete gates",
        "simulated_price": 10,
        "simulated_quantity": 100,
        "risk_constraints": {"simulation_only": True, "is_real_trade": False},
    })

    assert error is None
    assert order["action"] == "SIM_BUY"
    assert order["risk_constraints"]["simulation_only"] is True
    assert order["risk_constraints"]["is_real_trade"] is False
    assert "risk_not_passed" in order["risk_constraints"]["paper_gate_warnings"]
    assert "missing_trigger_conditions" not in order["risk_constraints"]["paper_gate_warnings"]


@pytest.mark.asyncio
async def test_paper_order_still_blocks_new_risk_when_kill_switch_active():
    signal = await signalops_store.create_signal({
        "symbol": "603663",
        "source_run_id": "RUN_P2_KILL_SWITCH",
        "risk_passed": False,
    })
    portfolio, error = await signalops_store.create_paper_portfolio(signal["signal_id"], {
        "initial_cash": 100000,
    })
    assert error is None
    assert portfolio is not None

    order, error = await signalops_store.create_paper_order(signal["signal_id"], {
        "action": "SIM_BUY",
        "simulated_price": 10,
        "simulated_quantity": 100,
        "risk_constraints": {"kill_switch_active": True},
    })

    assert order is None
    assert "SIM_HOLD" in error


@pytest.mark.asyncio
async def test_paper_positions_are_listed_and_marked_to_market():
    symbol = f"UT{uuid4().hex[:8].upper()}"
    signal = await signalops_store.create_signal({
        "symbol": symbol,
        "source_run_id": f"RUN_POS_{uuid4().hex[:8]}",
        "risk_passed": False,
    })
    portfolio, error = await signalops_store.create_paper_portfolio(signal["signal_id"], {
        "initial_cash": 100000,
    })
    assert error is None

    order, error = await signalops_store.create_paper_order(signal["signal_id"], {
        "action": "SIM_BUY",
        "simulated_price": 10,
        "simulated_quantity": 137.5,
        "risk_constraints": {"simulation_only": True, "is_real_trade": False},
    })
    assert error is None
    assert order["simulated_quantity"] == 100

    filled, error = await signalops_store.fill_paper_order(signal["signal_id"], order["order_id"], {
        "filled_price": 10,
        "filled_quantity": 137.5,
    })
    assert error is None
    assert filled["fill_status"] == "FILLED"
    assert filled["simulated_fill"]["filled_quantity"] == 100

    positions = await signalops_store.list_paper_positions(signal["signal_id"])
    assert len(positions) == 1
    assert positions[0]["symbol"] == symbol
    assert positions[0]["quantity"] == 100
    assert positions[0]["current_value"] == 1000
    assert positions[0]["simulation_only"] is True
    assert positions[0]["is_real_trade"] is False

    marked = await signalops_store.mark_paper_portfolio_to_market(signal["signal_id"], 12)
    assert marked["market_value"] == 1200
    assert marked["available_cash"] == portfolio["initial_cash"] - 1000

    positions = await signalops_store.list_paper_positions(signal["signal_id"])
    assert positions[0]["current_value"] == 1200
    assert positions[0]["floating_pnl"] == 200
    assert positions[0]["simulation_only"] is True
    assert positions[0]["is_real_trade"] is False


@pytest.mark.asyncio
async def test_upsert_from_run_creates_and_advances_signal_lifecycle():
    symbol = f"UT{uuid4().hex[:8].upper()}"
    first_run = {
        "runId": f"RUN_AUTO_{uuid4().hex[:8]}",
        "stockCode": symbol,
        "stockName": "Unit Test Signal",
        "dataMode": "REAL",
        "finalWriter": {"auditId": "AUD_AUTO_FIRST", "finalAction": "WATCH"},
        "dvg": {"allowedOutputLevel": "FULL"},
        "qiam": {"finalBuySuitability": "BUY"},
        "execution": {"allowedActions": ["SIM_BUY"]},
        "portfolio": {"allowAddPosition": True},
        "signalOps": {
            "signalStatus": "PAPER_TEST",
            "riskPassed": True,
            "dvgPassed": True,
            "qiamPassed": True,
            "executionReachable": False,
            "triggerConditions": ["breakout confirmed"],
            "invalidationConditions": [],
            "reviewFields": ["volume"],
            "blockedReason": "",
        },
    }

    signal = await signalops_store.upsert_from_run(first_run)

    assert signal is not None
    assert signal["symbol"] == symbol
    assert signal["status"] == "PAPER_TEST"
    assert signal["source_run_id"] == first_run["runId"]
    assert signal["latest_run_id"] == first_run["runId"]
    assert first_run["runId"] in signal["attached_runs"]

    second_run = {
        **first_run,
        "runId": f"RUN_AUTO_{uuid4().hex[:8]}",
        "finalWriter": {"auditId": "AUD_AUTO_SECOND", "finalAction": "BUY"},
        "signalOps": {
            **first_run["signalOps"],
            "signalStatus": "QUALIFIED",
            "invalidationConditions": ["close below trigger base"],
        },
    }
    advanced = await signalops_store.upsert_from_run(second_run)

    assert advanced["signal_id"] == signal["signal_id"]
    assert advanced["status"] == "QUALIFIED"
    assert advanced["latest_run_id"] == second_run["runId"]
    assert first_run["runId"] in advanced["attached_runs"]
    assert second_run["runId"] in advanced["attached_runs"]

    detail = await signalops_store.get_signal_detail(signal["signal_id"])
    transitions = detail["transitions"]
    assert [item["to_status"] for item in transitions[-2:]] == ["PAPER_TEST", "QUALIFIED"]
    assert all(item["passed"] for item in transitions[-2:])


@pytest.mark.asyncio
async def test_upsert_from_run_records_failed_gate_without_forcing_qualified():
    symbol = f"UT{uuid4().hex[:8].upper()}"
    run = {
        "runId": f"RUN_AUTO_BLOCK_{uuid4().hex[:8]}",
        "stockCode": symbol,
        "stockName": "Blocked Signal",
        "dvg": {"allowedOutputLevel": "REVIEW_ONLY"},
        "qiam": {"finalBuySuitability": "BUY"},
        "portfolio": {"allowAddPosition": True},
        "signalOps": {
            "signalStatus": "QUALIFIED",
            "riskPassed": True,
            "dvgPassed": False,
            "qiamPassed": True,
            "executionReachable": True,
            "triggerConditions": ["setup present"],
            "invalidationConditions": [],
            "reviewFields": ["dvg evidence"],
            "blockedReason": "DVG review required",
        },
    }

    signal = await signalops_store.upsert_from_run(run)

    assert signal is not None
    assert signal["status"] == "IDEA"
    assert "QUALIFIED requires invalidation_conditions" not in signal["blocked_reason"]
    assert "DVG must pass before QUALIFIED" in signal["blocked_reason"]
    detail = await signalops_store.get_signal_detail(signal["signal_id"])
    assert detail["transitions"][-1]["to_status"] == "QUALIFIED"
    assert detail["transitions"][-1]["passed"] is False
    checks = {item["key"]: item["passed"] for item in detail["transitions"][-1]["gate_checks"]}
    assert checks["ai_invalidation_allowed"] is True
    assert checks["dvg_passed"] is False
    assert checks["dvg_not_review_only"] is False
