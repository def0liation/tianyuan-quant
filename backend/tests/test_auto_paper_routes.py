import json

import pytest
from fastapi import FastAPI

from app.api import routes_auto_paper_trading
from app.core import auto_paper_trading as auto_module
from app.core.auto_paper_trading import auto_paper_trading_store


class FakeMarketResult:
    status = "READY"

    def __init__(self, symbol: str = "603663", price: float = 10.0, pct: float = 1.2):
        self.symbol = symbol
        self.price = price
        self.pct = pct

    def to_public_dict(self):
        return {
            "status": "READY",
            "provider": "fake",
            "profileId": "fake",
            "symbol": self.symbol,
            "quote": {
                "symbol": self.symbol,
                "price": self.price,
                "changePercent": self.pct,
            },
            "fetchedAt": "2026-05-20T00:00:00+00:00",
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


def ready_kline_payload(symbol="603663", period="daily", range_="3m"):
    snapshot = bottom_candidate_kline_snapshot()
    return snapshot.get(period) or snapshot["daily"]


@pytest.fixture(autouse=True)
def isolate_auto_store(tmp_path, monkeypatch):
    monkeypatch.setattr(auto_module, "STORAGE_FILE", tmp_path / "auto_paper_trading.json")
    auto_paper_trading_store.stop_background_loop()
    auto_paper_trading_store._loop_started_at = ""
    auto_paper_trading_store._loop_heartbeat_at = ""
    auto_paper_trading_store._loop_last_error = ""
    auto_paper_trading_store._last_storage_warning = ""
    yield
    auto_paper_trading_store.stop_background_loop()


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(routes_auto_paper_trading.router, prefix="/api")
    return app


async def asgi_json(app, method: str, path: str, json_body=None):
    route_path, _, query = path.partition("?")
    body = b""
    headers = [(b"host", b"testserver")]
    if json_body is not None:
        body = json.dumps(json_body).encode("utf-8")
        headers.append((b"content-type", b"application/json"))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": route_path,
        "raw_path": route_path.encode("ascii"),
        "query_string": query.encode("ascii"),
        "headers": headers,
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    request_sent = False
    sent = []

    async def receive():
        nonlocal request_sent
        if request_sent:
            return {"type": "http.disconnect"}
        request_sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        sent.append(message)

    await app(scope, receive, send)
    status = next(item["status"] for item in sent if item["type"] == "http.response.start")
    response_body = b"".join(item.get("body", b"") for item in sent if item["type"] == "http.response.body")
    return status, json.loads(response_body.decode("utf-8")) if response_body else None


@pytest.mark.asyncio
async def test_auto_paper_config_patch_and_status_routes(app):
    status_code, config = await asgi_json(
        app,
        "PATCH",
        "/api/signalops/auto-paper/config",
        {
            "enabled": True,
            "symbol": "603663",
            "stock_name": "Unit Test",
            "initial_buy_signal": "突破买入边界",
            "final_sell_signal": "跌破卖出边界",
            "initial_buy_signals": {"603663": "突破买入边界"},
            "final_sell_signals": {"603663": "跌破卖出边界"},
            "initial_cash": 120000,
            "max_position_ratio": 0.9,
            "commission_rate": 0.0001,
            "commission_min_fee": 5,
            "commission_min_trade_value": 50000,
            "tick_interval_seconds": 30,
            "use_llm": False,
        },
    )

    assert status_code == 200
    assert config["enabled"] is True
    assert config["symbol"] == "603663"
    assert config["stock_name"] == "Unit Test"
    assert config["initial_buy_signal"] == "突破买入边界"
    assert config["final_sell_signal"] == "跌破卖出边界"
    assert config["initial_buy_signals"]["603663"] == "突破买入边界"
    assert config["final_sell_signals"]["603663"] == "跌破卖出边界"
    assert config["initial_cash"] == 120000
    assert config["max_position_ratio"] == 0.5
    assert config["commission_rate"] == 0.0001
    assert config["commission_min_fee"] == 5
    assert config["commission_min_trade_value"] == 50000
    assert config["automation_mode"] == "SIMULATION"
    assert config["simulation_module"]["enabled"] is True
    assert config["simulation_module"]["order_namespace"] == "SIM_*"
    assert config["live_module"]["enabled"] is False
    assert config["live_module"]["execution_enabled"] is False
    assert config["live_module"]["order_router"] == "DISABLED"
    assert config["live_module"]["simulation_only"] is True
    assert config["live_module"]["is_real_trade"] is False

    status_code, status = await asgi_json(app, "GET", "/api/signalops/auto-paper/status")
    assert status_code == 200
    assert status["enabled"] is True
    assert status["automation_mode"] == "SIMULATION"
    assert status["automation_modules"]["active_module"] == "simulation"
    assert status["automation_modules"]["live"]["status"] == "CONFIGURED_DISABLED"
    assert status["automation_modules"]["live"]["simulation_only"] is True
    assert status["automation_modules"]["live"]["is_real_trade"] is False
    assert status["automation_modules"]["real_trade_enabled"] is False
    assert status["loop_running"] is False
    assert status["loop_health"] == "STOPPED"
    assert status["current_time"] == status["heartbeat_at"]
    assert status["tick_interval_seconds"] == 30
    assert status["next_tick_due_at"]
    assert status["seconds_until_next_tick"] == 0
    assert status["last_error"] == ""


@pytest.mark.asyncio
async def test_auto_paper_live_module_config_is_persisted_but_forced_disabled(app):
    status_code, config = await asgi_json(
        app,
        "PATCH",
        "/api/signalops/auto-paper/config",
        {
            "enabled": True,
            "symbol": "603663",
            "automation_mode": "LIVE_DISABLED",
            "live_module": {
                "enabled": True,
                "execution_enabled": True,
                "order_router": "BROKER_API",
                "broker_profile_id": "broker-test",
                "account_id": "acct-test",
                "max_order_value": 50000,
                "max_position_ratio": 0.2,
            },
        },
    )

    assert status_code == 200
    assert config["automation_mode"] == "SIMULATION"
    assert config["live_module"]["broker_profile_id"] == "broker-test"
    assert config["live_module"]["account_id"] == "acct-test"
    assert config["live_module"]["max_order_value"] == 50000
    assert config["live_module"]["max_position_ratio"] == 0.2
    assert config["live_module"]["enabled"] is False
    assert config["live_module"]["execution_enabled"] is False
    assert config["live_module"]["order_router"] == "DISABLED"
    assert config["live_module"]["simulation_only"] is True
    assert config["live_module"]["is_real_trade"] is False

    _, status = await asgi_json(app, "GET", "/api/signalops/auto-paper/status")
    assert status["automation_modules"]["live"]["simulation_only"] is True
    assert status["automation_modules"]["live"]["is_real_trade"] is False
    assert status["automation_modules"]["real_trade_enabled"] is False
    assert status["automation_modules"]["live_ready"] is False


@pytest.mark.asyncio
async def test_auto_paper_compact_read_routes_keep_ui_summary_without_heavy_snapshots(app):
    auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663",
        "stock_name": "Unit Test",
        "initial_cash": 120000,
        "automation_mode": "LIVE",
        "live_module": {
            "enabled": True,
            "execution_enabled": True,
            "order_router": "BROKER_API",
            "broker_profile_id": "compact-broker",
            "account_id": "compact-account",
            "max_order_value": 50000,
            "max_position_ratio": 0.2,
        },
    })
    state = auto_paper_trading_store._load_state()
    state["last_kline_snapshot_by_symbol"] = {
        "603663": {
            "daily": {
                "rows": [{"close": index} for index in range(200)],
            },
        },
    }
    state["last_tick_result"] = {
        "status": "COMPLETED",
        "symbol": "POOL",
        "results": [
            {
                "status": "COMPLETED",
                "symbol": "603663",
                "signal_id": "SIG_COMPACT",
                "market_snapshot": {
                    "quote": {
                        "symbol": "603663",
                        "name": "Unit Test",
                        "price": 10.0,
                        "changePercent": 1.2,
                        "unused_payload": "x" * 5000,
                    },
                },
                "kline_snapshot": {"rows": [{"close": index} for index in range(200)]},
                "decision": {
                    "decision_card": {
                        "action": "SIM_HOLD",
                        "reason": "compact test",
                        "capital_before": 120000,
                        "pre_buy_quality": {"status": "READY"},
                        "quant_core_path_risk_policy": "AVOID_NEW_BUY",
                        "quant_core_path_risk_avoids_new_buy": True,
                        "future_trend_probability": {"signalopsPolicyHint": "REVIEW_SIMULATION_ONLY"},
                        "review_fields": ["quant_core_path_risk", "future_trend_probability"],
                    },
                },
                "llm_trace": {"raw": "x" * 5000},
            },
        ],
    }
    state["last_research_review"] = {
        "status": "COMPLETED",
        "trading_date": "2026-05-27",
        "reviewed_symbols": [{"symbol": "603663", "raw": "x" * 1000}],
        "cleaned_records": [
            {"symbol": "603663", "latest_action": "SIM_HOLD", "order_count": 1},
            {"symbol": "600900", "latest_action": "NONE", "order_count": 0},
        ],
        "compressed_observation_history": {"total_count": 12, "by_symbol": {"600900": {"count": 5}}},
        "review_queue_state": {"observations": [{"raw": "x" * 5000}]},
        "tuning_update": {
            "application_status": "RECOMMENDED_ONLY",
            "application_reason": "sample too small",
            "performance_summary": {"global": {"win_rate": 0.5}},
            "compressed_observation_count": 12,
            "compressed_observation_history": {"total_count": 12, "by_symbol": {"600900": {"count": 5}}},
            "strategy_experiment": {"experiment_id": "exp-compact", "raw": "x" * 5000},
        },
    }
    state["review_queue_state"] = {
        "items": [],
        "observations": [{"symbol": "603663", "candidate_status": "READY_FOR_REVIEW"}],
        "counts": {"total": 1},
        "simulation_only": True,
        "is_real_trade": False,
    }
    auto_paper_trading_store._save_state(state)

    status_code, config = await asgi_json(app, "GET", "/api/signalops/auto-paper/config?compact=true")
    assert status_code == 200
    assert config["enabled"] is True
    assert config["symbol"] == "603663"
    assert config["automation_mode"] == "SIMULATION"
    assert config["live_module"]["broker_profile_id"] == "compact-broker"
    assert config["live_module"]["account_id"] == "compact-account"
    assert config["live_module"]["enabled"] is False
    assert config["live_module"]["execution_enabled"] is False
    assert config["live_module"]["order_router"] == "DISABLED"
    assert config["live_module"]["status"] == "CONFIGURED_DISABLED"
    assert config["live_module"]["simulation_only"] is True
    assert config["live_module"]["is_real_trade"] is False
    assert config["last_tick_result"] == {}
    assert config["last_kline_snapshot_by_symbol"] == {}
    assert config["last_research_review"] == {}
    assert config["review_queue_state"] == {}

    status_code, status = await asgi_json(app, "GET", "/api/signalops/auto-paper/status?compact=true")
    assert status_code == 200
    assert status["automation_modules"]["active_module"] == "simulation"
    assert status["automation_modules"]["live_ready"] is False
    assert status["automation_modules"]["real_trade_enabled"] is False
    assert status["automation_modules"]["live"]["broker_profile_id"] == "compact-broker"
    assert status["automation_modules"]["live"]["account_id"] == "compact-account"
    assert status["automation_modules"]["live"]["enabled"] is False
    assert status["automation_modules"]["live"]["execution_enabled"] is False
    assert status["automation_modules"]["live"]["order_router"] == "DISABLED"
    assert status["automation_modules"]["live"]["status"] == "CONFIGURED_DISABLED"
    assert status["automation_modules"]["live"]["simulation_only"] is True
    assert status["automation_modules"]["live"]["is_real_trade"] is False
    assert status["review_queue_state"]["observations"][0]["symbol"] == "603663"
    assert status["last_tick_result"]["results"][0]["symbol"] == "603663"
    assert status["last_tick_result"]["results"][0]["decision_card"]["action"] == "SIM_HOLD"
    assert status["last_tick_result"]["results"][0]["decision_card"]["quant_core_path_risk_avoids_new_buy"] is True
    assert status["last_tick_result"]["results"][0]["decision_card"]["future_trend_probability"]["signalopsPolicyHint"] == "REVIEW_SIMULATION_ONLY"
    assert "future_trend_probability" in status["last_tick_result"]["results"][0]["decision_card"]["review_fields"]
    assert status["last_tick_result"]["results"][0]["market_snapshot"]["quote"]["name"] == "Unit Test"
    assert "kline_snapshot" not in status["last_tick_result"]["results"][0]
    assert "llm_trace" not in status["last_tick_result"]["results"][0]
    assert status["last_research_review"]["tuning_update"]["application_status"] == "RECOMMENDED_ONLY"
    assert status["last_research_review"]["tuning_update"]["compressed_observation_count"] == 12
    assert len(status["last_research_review"]["cleaned_records"]) == 1
    assert status["last_research_review"]["cleaned_records"][0]["symbol"] == "603663"
    assert "review_queue_state" not in status["last_research_review"]


@pytest.mark.asyncio
async def test_auto_paper_tick_route_forced_and_blocked(app, monkeypatch):
    async def fake_fetch_market_data(profile, symbol):
        return FakeMarketResult(symbol=symbol, price=10.0, pct=1.2)

    monkeypatch.setattr(auto_module, "fetch_market_data", fake_fetch_market_data)
    monkeypatch.setattr(
        auto_module,
        "get_kline_payload",
        ready_kline_payload,
    )

    await asgi_json(
        app,
        "PATCH",
        "/api/signalops/auto-paper/config",
        {
            "enabled": True,
            "symbol": "603663",
            "stock_name": "Unit Test",
            "initial_cash": 100000,
            "min_order_value": 1000,
            "tick_interval_seconds": 60,
            "min_order_interval_seconds": 5,
            "use_llm": False,
        },
    )

    status_code, forced_data = await asgi_json(app, "POST", "/api/signalops/auto-paper/tick", {"force": True})
    assert status_code == 200
    assert forced_data["status"] == "COMPLETED"
    assert forced_data["decision"]["action"] == "SIM_BUY"
    assert forced_data["decision"]["simulation_only"] is True
    assert forced_data["decision"]["is_real_trade"] is False
    assert forced_data["decision"]["pre_buy_quality"]["simulation_only"] is True
    assert forced_data["decision"]["pre_buy_quality"]["is_real_trade"] is False
    assert "kline_signal_quality" in forced_data["decision"]["pre_buy_quality"]["components"]
    assert forced_data["decision_card"]["action"] == "SIM_BUY"
    assert "kline_signal_quality" in forced_data["decision_card"]
    assert forced_data["decision"]["decision_card"]["action"] == "SIM_BUY"
    assert forced_data["decision"]["decision_card"]["budget_used"] == 15000
    assert forced_data["decision"]["decision_card"]["pre_buy_quality"]["grade"] == forced_data["decision"]["pre_buy_quality"]["grade"]
    assert "pre_buy_quality" in forced_data["decision"]["decision_card"]["review_fields"]
    assert forced_data["decision"]["decision_card"]["cash_available"] == 84995
    assert forced_data["decision"]["decision_card"]["commission_fee"] == 5
    assert forced_data["module_evidence"]["version"] == "signalops_module_evidence_v1"
    assert forced_data["module_evidence"]["sequence"][-1] == "signalops_llm_decision"
    assert "quant_core" in forced_data["module_evidence"]["sequence"]
    assert {"dvg_evidence_gate", "risk_firewall", "trade_micro", "execution", "anti_conclusion"} <= set(forced_data["module_evidence"]["sequence"])
    assert forced_data["module_evidence"]["automation_modules"]["active_module"] == "simulation"
    assert forced_data["module_evidence"]["trade_boundary"]["allowed_order_namespace"] == "SIM_*"
    assert forced_data["module_evidence"]["trade_boundary"]["live_module_status"] == "CONFIGURED_DISABLED"
    assert forced_data["module_evidence"]["dvg"]["simulation_only"] is True
    assert forced_data["module_evidence"]["riskFirewall"]["simulation_only"] is True
    assert forced_data["module_evidence"]["tradeMicro"]["is_real_trade"] is False
    assert forced_data["module_evidence"]["execution"]["is_real_trade"] is False
    assert forced_data["module_evidence"]["antiConclusion"]["simulation_only"] is True
    assert forced_data["module_evidence"]["qiam"]["probabilitySource"] == "RULE_DERIVED"
    assert forced_data["module_evidence"]["quantCore"]["sourceNode"] == "quant_core"
    assert forced_data["module_evidence"]["quantCore"]["coreInterpretation"]["actionBoundary"] == "READ_ONLY_NO_PERMISSION_CHANGE"
    visual_panel = forced_data["module_evidence"]["quantCore"]["coreInterpretation"]["visualDecisionPanel"]
    assert visual_panel["version"] == "quant_core_visual_decision_panel_v1"
    assert visual_panel["actionBoundary"] == "READ_ONLY_NO_PERMISSION_CHANGE"
    assert visual_panel["simulation_only"] is True
    assert visual_panel["is_real_trade"] is False
    assert forced_data["decision"]["moduleEvidence"]["version"] == "signalops_module_evidence_v1"
    assert forced_data["portfolio_snapshot"]["sourceType"] == "SIGNALOPS_SIM"
    assert forced_data["portfolio_snapshot"]["positionCount"] == 1
    assert forced_data["portfolio_snapshot"]["simulation_only"] is True
    assert forced_data["portfolio_snapshot"]["is_real_trade"] is False
    assert forced_data["order"]["simulation_only"] is True
    assert forced_data["order"]["is_real_trade"] is False
    assert forced_data["order"]["risk_constraints"]["decision_card"]["position_value"] == 15000

    _, status = await asgi_json(app, "GET", "/api/signalops/auto-paper/status")
    assert status["last_tick_at"]
    assert status["last_success_at"]
    assert status["last_tick_result"]["status"] == "COMPLETED"
    assert status["last_tick_result"]["decision"]["decision_card"]["capital_before"] == 100000
    assert status["last_tick_result"]["decision"]["pre_buy_quality"]["simulation_only"] is True
    assert status["last_tick_result"]["module_evidence"]["version"] == "signalops_module_evidence_v1"
    assert status["last_module_evidence"]["version"] == "signalops_module_evidence_v1"
    assert status["last_tick_result"]["portfolio_snapshot"]["sourceType"] == "SIGNALOPS_SIM"
    assert status["last_portfolio_snapshot"]["sourceType"] == "SIGNALOPS_SIM"
    assert status["last_tick_result"]["decision_card"]["action"] == "SIM_BUY"
    assert status["last_error"] == ""
    assert status["seconds_until_next_tick"] is not None

    await asgi_json(app, "PATCH", "/api/signalops/auto-paper/config", {"enabled": True, "symbol": ""})
    status_code, blocked_data = await asgi_json(app, "POST", "/api/signalops/auto-paper/tick", {"force": True})
    assert status_code == 200
    assert blocked_data["status"] == "BLOCKED"
    assert blocked_data["decision"]["decision_card"]["action"] == "SIM_HOLD"
    assert blocked_data["decision"]["decision_card"]["capital_before"] == 0
    assert blocked_data["config"]["enabled"] is False


@pytest.mark.asyncio
async def test_auto_paper_review_decision_route_persists_and_applies_simulation_candidate(app, monkeypatch, tmp_path):
    monkeypatch.setenv("AUTO_PAPER_REVIEW_DECISION_EXPORT_SIGNING_KEY", "unit-review-event-export-secret")
    monkeypatch.setenv("AUTO_PAPER_REVIEW_DECISION_EXPORT_SIGNING_KEY_REF", "unit-test-key-ref")
    handoff_dir = tmp_path / "review-event-handoff"
    monkeypatch.setenv("AUTO_PAPER_REVIEW_DECISION_EXPORT_HANDOFF_DIR", str(handoff_dir))
    auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663",
        "stock_name": "Unit Test",
        "initial_cash": 100000,
        "use_llm": False,
    })
    state = auto_paper_trading_store._load_state()
    state["review_queue_state"] = {
        "version": 1,
        "updated_at": "2026-05-20T00:00:00+00:00",
        "items": [
            {
                "id": "rq-test",
                "queue_item_id": "rq-test",
                "experiment_id": "signalops-exp-test",
                "symbol": "603663",
                "candidate_status": "READY_FOR_REVIEW",
                "promotion_status": "READY_FOR_REVIEW",
                "review_allowed": True,
                "evidence_quality": "MEDIUM",
                "benchmark_comparison": {"symbol": "000300.SH", "available": True, "status": "AVAILABLE"},
                "baseline_config": {"buy_change_threshold_pct": 0.5, "factor_adjustments": {}},
                "candidate_config": {
                    "buy_change_threshold_pct": 0.8,
                    "close_change_threshold_pct": -1.8,
                    "watch_position_ratio": 0.12,
                    "probe_position_ratio": 0.30,
                    "positive_position_ratio": 0.45,
                    "breakout_position_ratio": 0.60,
                    "defensive_position_ratio": 0.20,
                    "existing_position_ratio": 0.40,
                    "strength_follow_position_ratio": 0.60,
                    "factor_adjustments": {"ai_dynamic_probe": {"buy_threshold_delta": 0.1}},
                },
                "simulation_only": True,
                "is_real_trade": False,
            }
        ],
        "observations": [],
        "counts": {"ready_for_review": 1},
        "simulation_only": True,
        "is_real_trade": False,
    }
    auto_paper_trading_store._save_state(state)

    status_code, result = await asgi_json(
        app,
        "POST",
        "/api/signalops/auto-paper/review-decisions",
        {
            "queue_item_id": "rq-test",
            "action": "APPROVE_SIMULATION_CANDIDATE",
            "reviewer": "human",
            "reason": "route approval stays simulation only",
        },
    )

    assert status_code == 200
    assert result["status"] == "COMPLETED"
    assert result["decision"]["result_status"] == "APPLIED_TO_SIMULATION"
    assert result["decision"]["simulation_only"] is True
    assert result["decision"]["is_real_trade"] is False
    assert result["decision"]["parameter_diff_checksum"].startswith("sigops-paramdiff-")
    assert result["decision"]["parameter_diff_summary"]["policy_id"] == "signalops_candidate_parameter_diff_v1"
    assert result["decision"]["parameter_diff_summary"]["source"] == "server_generated"
    assert result["decision"]["parameter_diff_summary"]["status"] == "CHANGED"
    assert result["decision"]["parameter_diff_summary"]["changed_count"] >= 1
    assert result["decision"]["review_decision_summary"]["parameter_diff_checksum"] == result["decision"]["parameter_diff_checksum"]
    assert result["decision"]["review_event_hash"].startswith("sigops-reviewevent-")
    assert result["decision"]["review_decision_summary"]["review_event_hash"] == result["decision"]["review_event_hash"]
    assert result["config"]["buy_change_threshold_pct"] == 0.8
    assert result["config"]["factor_adjustments"]["ai_dynamic_probe"]["buy_threshold_delta"] == 0.1
    assert result["config"]["review_decisions"][-1]["action"] == "APPROVE_SIMULATION_CANDIDATE"
    assert result["config"]["review_decisions"][-1]["parameter_diff_checksum"] == result["decision"]["parameter_diff_checksum"]
    assert result["config"]["review_queue_state"]["items"][0]["candidate_status"] == "APPLIED_TO_SIMULATION"
    assert result["config"]["review_queue_state"]["items"][0]["reviewed_parameter_diff_checksum"] == result["decision"]["parameter_diff_checksum"]
    assert result["config"]["review_queue_state"]["items"][0]["review_event_hash"] == result["decision"]["review_event_hash"]

    _, status = await asgi_json(app, "GET", "/api/signalops/auto-paper/status")
    assert status["review_decisions"][-1]["action"] == "APPROVE_SIMULATION_CANDIDATE"
    assert status["review_decisions"][-1]["parameter_diff_checksum"] == result["decision"]["parameter_diff_checksum"]
    assert status["review_decision_event_ledger"]["event_count"] == 1
    assert status["review_decision_event_ledger"]["latest_event_hash"] == result["decision"]["review_event_hash"]
    assert status["review_queue_state"]["items"][0]["candidate_status"] == "APPLIED_TO_SIMULATION"
    assert status["review_queue_state"]["items"][0]["reviewed_parameter_diff_checksum"] == result["decision"]["parameter_diff_checksum"]
    assert status["experiment_validation_state"]["simulation_only"] is True

    _, event_export = await asgi_json(app, "GET", "/api/signalops/auto-paper/review-decision-events?limit=10")
    assert event_export["schema"] == "signalops_review_decision_event_export_v1"
    assert event_export["append_only"] is True
    assert event_export["simulation_only"] is True
    assert event_export["is_real_trade"] is False
    assert event_export["bundle_checksum"].startswith("sigops-reviewevents-")
    assert event_export["export_signature_status"] == "SIGNED"
    assert event_export["export_signature"]["schema"] == "signalops_review_decision_event_export_signature_v1"
    assert event_export["export_signature"]["algorithm"] == "HMAC-SHA256"
    assert event_export["export_signature"]["signature"].startswith("sigops-reviewevents-hmac-")
    assert event_export["export_signature"]["payload_checksum"] == event_export["bundle_checksum"]
    assert event_export["export_signature"]["signing_key_ref"] == "unit-test-key-ref"
    assert event_export["export_signature"]["simulation_only"] is True
    assert event_export["export_signature"]["is_real_trade"] is False
    assert event_export["latest_event_hash"] == result["decision"]["review_event_hash"]
    assert event_export["events"][-1]["parameter_diff_checksum"] == result["decision"]["parameter_diff_checksum"]

    verify_status, verification = await asgi_json(
        app,
        "POST",
        "/api/signalops/auto-paper/review-decision-events/verify",
        {"bundle": event_export},
    )
    assert verify_status == 200
    assert verification["schema"] == "signalops_review_decision_event_export_verification_v1"
    assert verification["status"] == "VALID"
    assert verification["valid"] is True
    assert verification["checksum_valid"] is True
    assert verification["signature_valid"] is True
    assert verification["payload_checksum_valid"] is True
    assert verification["signed_fields_valid"] is True
    assert verification["signing_key_ref_valid"] is True
    assert verification["boundary_valid"] is True
    assert verification["signature_boundary_valid"] is True
    assert verification["provided_bundle_checksum"] == event_export["bundle_checksum"]
    assert verification["expected_bundle_checksum"] == event_export["bundle_checksum"]

    bad_signature_export = json.loads(json.dumps(event_export))
    bad_signature_export["export_signature"]["signature"] = "sigops-reviewevents-hmac-tampered"
    _, bad_signature_verification = await asgi_json(
        app,
        "POST",
        "/api/signalops/auto-paper/review-decision-events/verify",
        {"bundle": bad_signature_export},
    )
    assert bad_signature_verification["status"] == "INVALID"
    assert bad_signature_verification["valid"] is False
    assert bad_signature_verification["checksum_valid"] is True
    assert bad_signature_verification["signature_valid"] is False

    tampered_event_export = json.loads(json.dumps(event_export))
    tampered_event_export["events"][-1]["parameter_diff_checksum"] = "sigops-paramdiff-tampered"
    _, tampered_event_verification = await asgi_json(
        app,
        "POST",
        "/api/signalops/auto-paper/review-decision-events/verify",
        {"bundle": tampered_event_export},
    )
    assert tampered_event_verification["status"] == "INVALID"
    assert tampered_event_verification["valid"] is False
    assert tampered_event_verification["checksum_valid"] is False
    assert tampered_event_verification["signature_valid"] is False

    handoff_status, handoff = await asgi_json(
        app,
        "POST",
        "/api/signalops/auto-paper/review-decision-events/handoff?limit=10",
    )
    assert handoff_status == 200
    assert handoff["schema"] == "signalops_review_decision_event_export_handoff_v1"
    assert handoff["status"] == "HANDED_OFF"
    assert handoff["handoff_destination"] == "LOCAL_DEPLOYMENT_HANDOFF_DIR"
    assert handoff["handoff_requires_signature"] is True
    assert handoff["verification"]["status"] == "VALID"
    assert handoff["verification"]["valid"] is True
    assert handoff["bundle_checksum"] == event_export["bundle_checksum"]
    assert handoff["manifest"]["schema"] == "signalops_review_decision_event_export_handoff_manifest_v1"
    assert handoff["manifest"]["retention_policy"]["custody"] == "deployment_owned_after_handoff"
    assert handoff["manifest"]["retention_policy"]["requires_signed_export"] is True
    assert handoff["manifest"]["simulation_only"] is True
    assert handoff["manifest"]["is_real_trade"] is False
    bundle_path = handoff_dir / handoff["bundle_file"]
    manifest_path = handoff_dir / handoff["manifest_file"]
    assert bundle_path.exists()
    assert manifest_path.exists()
    persisted_bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    persisted_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert persisted_bundle["bundle_checksum"] == event_export["bundle_checksum"]
    assert persisted_manifest["handoff_id"] == handoff["handoff_id"]
    assert persisted_manifest["bundle_file"] == handoff["bundle_file"]
    sidecar_payload = {
        "schema": "signalops_review_decision_event_export_shipper_status_v1",
        "status": "DELIVERED",
        "reported_at": "2026-06-02T00:00:00+00:00",
        "source": "unit-test-shipper",
        "provider": "object-store",
        "remote_destination": "s3://unit-test/signalops?token=unit-secret",
        "object_key": f"signalops/{handoff['handoff_id']}.json",
        "retention_policy_id": "signalops-review-events-retention-30d",
        "retention_status": "RETAINED",
        "custody_status": "KMS_RETAINED",
        "kms_key_ref": "kms://unit-test/key?secret=unit-secret",
        "search_index": "signalops-review-event-artifacts",
        "search_index_ready": True,
        "last_handoff_id": handoff["handoff_id"],
        "last_bundle_checksum": event_export["bundle_checksum"],
        "last_latest_event_hash": result["decision"]["review_event_hash"],
        "message": "uploaded token=unit-secret",
    }
    (handoff_dir / "shipper_status.json").write_text(json.dumps(sidecar_payload), encoding="utf-8")
    _, status_with_handoff = await asgi_json(app, "GET", "/api/signalops/auto-paper/status")
    handoff_shipper_status = status_with_handoff["review_decision_event_ledger"]["handoff_shipper_status"]
    assert handoff_shipper_status["schema"] == "signalops_review_decision_event_export_shipper_status_v1"
    assert handoff_shipper_status["status"] == "DELIVERED"
    assert handoff_shipper_status["provider"] == "object-store"
    assert handoff_shipper_status["retention_status"] == "RETAINED"
    assert handoff_shipper_status["custody_status"] == "KMS_RETAINED"
    assert handoff_shipper_status["search_index_ready"] is True
    assert handoff_shipper_status["matches_latest_handoff"] is True
    assert handoff_shipper_status["matches_latest_export"] is True
    assert "unit-secret" not in json.dumps(handoff_shipper_status)

    rotated_state = auto_paper_trading_store._load_state()
    rotated_state["review_decisions"] = []
    rotated_state["review_queue_state"] = {"version": 1, "items": [], "observations": [], "counts": {}}
    auto_paper_trading_store._save_state(rotated_state)
    _, rotated_export = await asgi_json(app, "GET", "/api/signalops/auto-paper/review-decision-events?limit=10")
    assert rotated_export["total_event_count"] == 1
    assert rotated_export["export_signature_status"] == "SIGNED"
    assert rotated_export["export_signature"]["payload_checksum"] == rotated_export["bundle_checksum"]
    assert rotated_export["latest_event_hash"] == result["decision"]["review_event_hash"]
    assert rotated_export["events"][-1]["decision_id"] == result["decision"]["decision_id"]


@pytest.mark.asyncio
async def test_auto_paper_review_decision_event_handoff_blocks_unsigned_export(app, monkeypatch, tmp_path):
    monkeypatch.delenv("AUTO_PAPER_REVIEW_DECISION_EXPORT_SIGNING_KEY", raising=False)
    handoff_dir = tmp_path / "review-event-handoff"
    monkeypatch.setenv("AUTO_PAPER_REVIEW_DECISION_EXPORT_HANDOFF_DIR", str(handoff_dir))

    status_code, result = await asgi_json(
        app,
        "POST",
        "/api/signalops/auto-paper/review-decision-events/handoff?limit=5",
    )

    assert status_code == 200
    assert result["schema"] == "signalops_review_decision_event_export_handoff_v1"
    assert result["status"] == "BLOCKED"
    assert result["handoff_requires_signature"] is True
    assert result["verification"]["status"] == "UNSIGNED"
    assert result["verification"]["valid"] is False
    assert result["bundle_file"] == ""
    assert result["manifest_file"] == ""
    if handoff_dir.exists():
        assert not any(handoff_dir.glob("*.json"))


@pytest.mark.asyncio
async def test_auto_paper_review_decision_blocks_unready_candidate_without_mutating_queue(app):
    auto_paper_trading_store.update_config({
        "enabled": True,
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
                "id": "rq-low",
                "queue_item_id": "rq-low",
                "experiment_id": "signalops-exp-low",
                "symbol": "603663",
                "candidate_status": "READY_FOR_REVIEW",
                "promotion_status": "READY_FOR_REVIEW",
                "review_allowed": False,
                "review_decision": "PENDING_REVIEW",
                "evidence_quality": "LOW",
                "candidate_config": {"buy_change_threshold_pct": 2.0},
                "simulation_only": True,
                "is_real_trade": False,
            }
        ],
        "observations": [],
        "counts": {"ready_for_review": 1},
        "simulation_only": True,
        "is_real_trade": False,
    }
    auto_paper_trading_store._save_state(state)

    status_code, result = await asgi_json(
        app,
        "POST",
        "/api/signalops/auto-paper/review-decisions",
        {
            "queue_item_id": "rq-low",
            "action": "APPROVE_SIMULATION_CANDIDATE",
            "reviewer": "human",
            "reason": "should stay blocked because evidence quality is low",
        },
    )

    assert status_code == 200
    assert result["status"] == "BLOCKED"
    assert result["decision"]["result_status"] == "BLOCKED"
    assert "low_quality_evidence" in result["warnings"]
    assert result["config"]["buy_change_threshold_pct"] == 0.5
    assert result["config"]["review_queue_state"]["items"][0]["review_decision"] == "PENDING_REVIEW"
    assert result["config"]["review_queue_state"]["items"][0]["candidate_status"] == "READY_FOR_REVIEW"


@pytest.mark.asyncio
async def test_auto_paper_review_decision_blocks_missing_benchmark(app):
    auto_paper_trading_store.update_config({
        "enabled": True,
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
                "id": "rq-no-benchmark",
                "queue_item_id": "rq-no-benchmark",
                "experiment_id": "signalops-exp-no-benchmark",
                "symbol": "603663",
                "candidate_status": "READY_FOR_REVIEW",
                "promotion_status": "READY_FOR_REVIEW",
                "review_allowed": True,
                "review_decision": "PENDING_REVIEW",
                "evidence_quality": "MEDIUM",
                "benchmark_comparison": {"symbol": "000300.SH", "available": False, "status": "UNAVAILABLE"},
                "candidate_config": {"buy_change_threshold_pct": 2.0},
                "simulation_only": True,
                "is_real_trade": False,
            }
        ],
        "observations": [],
        "counts": {"ready_for_review": 1},
        "simulation_only": True,
        "is_real_trade": False,
    }
    auto_paper_trading_store._save_state(state)

    status_code, result = await asgi_json(
        app,
        "POST",
        "/api/signalops/auto-paper/review-decisions",
        {
            "queue_item_id": "rq-no-benchmark",
            "action": "APPROVE_SIMULATION_CANDIDATE",
            "reviewer": "human",
            "reason": "should stay blocked because benchmark is unavailable",
        },
    )

    assert status_code == 200
    assert result["status"] == "BLOCKED"
    assert "benchmark_unavailable" in result["warnings"]
    assert result["config"]["buy_change_threshold_pct"] == 0.5


@pytest.mark.asyncio
async def test_auto_paper_review_decision_blocks_superseded_candidate(app):
    auto_paper_trading_store.update_config({
        "enabled": True,
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
                "id": "rq-old",
                "queue_item_id": "rq-old",
                "experiment_id": "signalops-exp-old",
                "symbol": "603663",
                "candidate_status": "SUPERSEDED",
                "promotion_status": "SUPERSEDED",
                "review_allowed": True,
                "review_decision": "PENDING_REVIEW",
                "evidence_quality": "MEDIUM",
                "candidate_config": {"buy_change_threshold_pct": 2.0},
                "simulation_only": True,
                "is_real_trade": False,
            }
        ],
        "observations": [],
        "counts": {"superseded": 1},
        "simulation_only": True,
        "is_real_trade": False,
    }
    auto_paper_trading_store._save_state(state)

    status_code, result = await asgi_json(
        app,
        "POST",
        "/api/signalops/auto-paper/review-decisions",
        {
            "queue_item_id": "rq-old",
            "action": "APPROVE_SIMULATION_CANDIDATE",
            "reviewer": "human",
            "reason": "old candidate should not apply",
        },
    )

    assert status_code == 200
    assert result["status"] == "BLOCKED"
    assert "candidate_superseded" in result["warnings"]
    assert result["config"]["buy_change_threshold_pct"] == 0.5
    assert result["config"]["review_queue_state"]["items"][0]["candidate_status"] == "SUPERSEDED"


@pytest.mark.asyncio
async def test_auto_paper_review_decision_clamps_candidate_parameters(app):
    auto_paper_trading_store.update_config({
        "enabled": True,
        "symbol": "603663",
        "stock_name": "Unit Test",
        "initial_cash": 100000,
        "use_llm": False,
    })
    state = auto_paper_trading_store._load_state()
    state["review_queue_state"] = {
        "version": 1,
        "items": [
            {
                "id": "rq-clamp",
                "queue_item_id": "rq-clamp",
                "experiment_id": "signalops-exp-clamp",
                "symbol": "603663",
                "candidate_status": "READY_FOR_REVIEW",
                "promotion_status": "READY_FOR_REVIEW",
                "review_allowed": True,
                "evidence_quality": "MEDIUM",
                "benchmark_comparison": {"symbol": "000300.SH", "available": True, "status": "AVAILABLE"},
                "candidate_config": {
                    "buy_change_threshold_pct": 999,
                    "close_change_threshold_pct": -999,
                    "watch_position_ratio": 9,
                    "probe_position_ratio": -9,
                    "factor_adjustments": {"ai_dynamic_probe": {"buy_threshold_delta": 0.1}},
                },
                "simulation_only": True,
                "is_real_trade": False,
            }
        ],
        "observations": [],
        "counts": {"ready_for_review": 1},
        "simulation_only": True,
        "is_real_trade": False,
    }
    auto_paper_trading_store._save_state(state)

    status_code, result = await asgi_json(
        app,
        "POST",
        "/api/signalops/auto-paper/review-decisions",
        {
            "queue_item_id": "rq-clamp",
            "action": "APPROVE_SIMULATION_CANDIDATE",
            "reviewer": "human",
        },
    )

    assert status_code == 200
    assert result["status"] == "COMPLETED"
    assert result["config"]["buy_change_threshold_pct"] == 5.0
    assert result["config"]["close_change_threshold_pct"] == -5.0
    assert result["config"]["watch_position_ratio"] == 0.85
    assert result["config"]["probe_position_ratio"] == 0.0
    assert result["decision"]["applied_parameters"]["buy_change_threshold_pct"] == 5.0
    assert result["decision"]["applied_parameters"]["probe_position_ratio"] == 0.0


@pytest.mark.asyncio
async def test_auto_paper_command_route_success_and_failure(app, monkeypatch):
    async def fake_fetch_market_data(profile, symbol):
        return FakeMarketResult(symbol=symbol, price=10.0, pct=0.1)

    monkeypatch.setattr(auto_module, "fetch_market_data", fake_fetch_market_data)
    monkeypatch.setattr(
        auto_module,
        "get_kline_payload",
        ready_kline_payload,
    )

    await asgi_json(
        app,
        "PATCH",
        "/api/signalops/auto-paper/config",
        {
            "enabled": True,
            "symbol": "603663",
            "stock_name": "Unit Test",
            "initial_cash": 100000,
            "min_order_value": 1000,
            "tick_interval_seconds": 60,
            "min_order_interval_seconds": 5,
            "use_llm": False,
        },
    )

    status_code, success_data = await asgi_json(
        app,
        "POST",
        "/api/signalops/auto-paper/command",
        {
            "symbol": "603663",
            "command": "FORCE_OPEN_BUY",
            "reason": "route test forced open",
        },
    )
    assert status_code == 200
    assert success_data["status"] == "COMPLETED"
    assert success_data["order"]["action"] == "SIM_BUY"
    assert success_data["order"]["simulation_only"] is True
    assert success_data["order"]["is_real_trade"] is False
    assert success_data["order"]["risk_constraints"]["manual_command"] == "FORCE_OPEN_BUY"
    assert success_data["order"]["risk_constraints"]["simulation_only"] is True
    assert success_data["order"]["risk_constraints"]["is_real_trade"] is False

    status_code, failure_data = await asgi_json(
        app,
        "POST",
        "/api/signalops/auto-paper/command",
        {
            "symbol": "603663",
            "command": "REAL_BUY",
            "reason": "route test unsupported command",
        },
    )
    assert status_code == 200
    assert failure_data["status"] == "BLOCKED"
    assert failure_data["warnings"] == ["unsupported_command"]
