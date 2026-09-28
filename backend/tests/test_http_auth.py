import asyncio
import json
from urllib.parse import urlsplit

import pytest

from app.core import agent_runtime_store
from app.core import auto_paper_trading as auto_module
from app.core.auto_paper_trading import auto_paper_trading_store
from app.main import app
from app.models.agent_runtime import UpsertLLMProfileRequest, UpsertMarketDataProfileRequest


AUTH_ENV_VARS = (
    "API_AUTH_MODE",
    "API_WRITE_TOKEN",
    "SUPER_API_WRITE_TOKEN",
    "API_ADMIN_TOKEN",
    "SUPER_API_ADMIN_TOKEN",
    "API_OPERATOR_TOKEN",
    "SUPER_API_OPERATOR_TOKEN",
    "API_RESEARCHER_TOKEN",
    "SUPER_API_RESEARCHER_TOKEN",
    "API_VIEWER_TOKEN",
    "SUPER_API_VIEWER_TOKEN",
    "APP_ENV",
    "ENVIRONMENT",
    "LOCAL_OPERATOR_ID",
    "LOCAL_OPERATOR_ROLE",
    "SUPER_OPERATOR_ID",
    "SUPER_OPERATOR_ROLE",
)

QUERY_TOKEN_PARAM_NAMES = ("token", "api_key", "apiKey", "super_api_key", "superApiKey")


async def asgi_raw(method: str, path: str, json_body=None, headers=None):
    body = b""
    request_headers = [(b"host", b"testserver")]
    for name, value in (headers or {}).items():
        request_headers.append((name.lower().encode("ascii"), value.encode("utf-8")))
    if json_body is not None:
        body = json.dumps(json_body).encode("utf-8")
        request_headers.append((b"content-type", b"application/json"))

    parsed_path = urlsplit(path)
    clean_path = parsed_path.path or path
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": clean_path,
        "raw_path": clean_path.encode("ascii"),
        "query_string": parsed_path.query.encode("ascii"),
        "headers": request_headers,
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    request_sent = False
    response_complete = False
    sent = []

    async def receive():
        nonlocal request_sent
        if request_sent:
            while not response_complete:
                await asyncio.sleep(0)
            return {"type": "http.disconnect"}
        request_sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        nonlocal response_complete
        sent.append(message)
        if message["type"] == "http.response.body" and not message.get("more_body", False):
            response_complete = True

    await app(scope, receive, send)
    status = next(item["status"] for item in sent if item["type"] == "http.response.start")
    response_headers = {
        name.decode("latin1"): value.decode("latin1")
        for item in sent
        if item["type"] == "http.response.start"
        for name, value in item.get("headers", [])
    }
    response_body = b"".join(item.get("body", b"") for item in sent if item["type"] == "http.response.body")
    return status, response_headers, response_body


async def asgi_json(method: str, path: str, json_body=None, headers=None):
    status, _headers, response_body = await asgi_raw(method, path, json_body=json_body, headers=headers)
    return status, json.loads(response_body.decode("utf-8")) if response_body else None


@pytest.fixture(autouse=True)
def clear_auth_env(monkeypatch):
    for name in AUTH_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.mark.asyncio
async def test_dev_mode_allows_write_without_token():
    status, data = await asgi_json(
        "POST",
        "/api/config/validate",
        {"changes": {"run_mode_default": "DEEP_MODE"}},
    )

    assert status == 200
    assert data["passed"] is True


@pytest.mark.asyncio
async def test_viewer_cannot_write_even_in_dev_mode():
    status, data = await asgi_json(
        "POST",
        "/api/config/validate",
        {"changes": {}},
        headers={"X-Operator-ID": "viewer-user", "X-Operator-Role": "viewer"},
    )

    assert status == 403
    assert data["detail"]["message"] == "Operator role is not allowed for this write."
    assert data["detail"]["required_role"] == "researcher"
    assert data["detail"]["scope"] == "api_write"
    assert data["detail"]["operator"] == {
        "id": "viewer-user",
        "role": "viewer",
        "source": "header",
    }


@pytest.mark.asyncio
async def test_researcher_cannot_use_high_risk_writes():
    protected_requests = [
        ("PATCH", "/api/config/runtime", {"changes": {"run_mode_default": "DEEP_MODE"}}, "admin", "config_runtime"),
        ("POST", "/api/config/external-restore", {}, "admin", "config_external_restore"),
        ("POST", "/api/ops/alerts/dispatch", {}, "admin", "ops_alert_dispatch"),
        ("POST", "/api/ops/alerts/export/handoff", {}, "admin", "ops_alert_export_handoff"),
        ("POST", "/api/ops/logs/export/handoff", {}, "admin", "ops_log_export_handoff"),
        ("PATCH", "/api/agents/runtime", {}, "admin", "agents_runtime"),
        ("PUT", "/api/agents/runtime/llm-profiles/default", {}, "admin", "agents_runtime"),
        ("PUT", "/api/agents/runtime/market-data-profiles/default", {}, "admin", "agents_runtime"),
        ("PATCH", "/api/agents/unit-agent/llm", {}, "admin", "agents_runtime"),
        ("POST", "/api/agents/runtime/test", {}, "admin", "agents_runtime"),
        ("POST", "/api/agents/runtime/validate-config", {}, "admin", "agents_runtime"),
        ("POST", "/api/agents/runtime/market-data/test", {}, "admin", "agents_runtime"),
        ("PUT", "/api/technical-kline/governance", {}, "admin", "technical_kline_governance"),
        ("POST", "/api/technical-kline/governance/rollback", {}, "admin", "technical_kline_governance"),
        ("POST", "/api/plugins", {}, "admin", "plugins"),
        ("POST", "/api/plugins/artifacts/cleanup", {}, "admin", "plugins"),
        ("POST", "/api/plugins/technical_kline_readonly/artifacts", {}, "admin", "plugins"),
        ("POST", "/api/case-library/knowledge-versions/KV_UNIT/rollback", {}, "admin", "knowledge_version_rollback"),
        ("PATCH", "/api/signalops/auto-paper/config", {"enabled": True}, "admin", "signalops_config"),
        ("POST", "/api/signalops/auto-paper/tick", {"force": True}, "operator", "signalops_command"),
        ("POST", "/api/signalops/auto-paper/daily-review", {"force": True}, "operator", "signalops_command"),
        ("POST", "/api/signalops/auto-paper/command", {}, "operator", "signalops_command"),
        ("POST", "/api/signalops/auto-paper/review-decisions", {}, "operator", "signalops_command"),
        ("POST", "/api/signalops/auto-paper/review-decision-events/verify", {}, "operator", "signalops_command"),
        ("POST", "/api/signalops/auto-paper/review-decision-events/handoff", {}, "operator", "signalops_command"),
        ("PATCH", "/api/signals/SIG_UNIT/conditions", {}, "operator", "signalops_lifecycle"),
        ("POST", "/api/signals/SIG_UNIT/transition", {}, "operator", "signalops_lifecycle"),
        ("POST", "/api/signals/SIG_UNIT/review", {}, "operator", "signalops_lifecycle"),
        ("POST", "/api/signalops/SIG_UNIT/paper-orders", {}, "operator", "signalops_paper_trading"),
        ("POST", "/api/signalops/SIG_UNIT/paper-orders/ORDER_UNIT/fill", {}, "operator", "signalops_paper_trading"),
        ("DELETE", "/api/analysis/runs/RUN_UNIT", None, "admin", "delete"),
        ("DELETE", "/api/research/backtest/runs/BT_UNIT", None, "admin", "delete"),
        ("DELETE", "/api/portfolio/snapshots/PF_UNIT", None, "admin", "delete"),
        ("DELETE", "/api/case-library/cases/CASE_UNIT", None, "admin", "delete"),
    ]

    for method, path, body, required_role, policy_scope in protected_requests:
        status, data = await asgi_json(
            method,
            path,
            body,
            headers={"X-Operator-ID": "research-user", "X-Operator-Role": "researcher"},
        )

        assert status == 403
        assert data["detail"]["required_role"] == required_role
        assert data["detail"]["scope"] == policy_scope
        assert data["detail"]["operator"]["role"] == "researcher"


@pytest.mark.asyncio
async def test_production_missing_token_rejects_representative_api_writes(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("API_WRITE_TOKEN", "unit-secret")

    protected_requests = [
        ("PATCH", "/api/config/runtime"),
        ("POST", "/api/config/external-restore"),
        ("POST", "/api/ops/alerts/dispatch"),
        ("POST", "/api/ops/alerts/export/handoff"),
        ("POST", "/api/ops/logs/export/handoff"),
        ("POST", "/api/signalops/auto-paper/command"),
        ("POST", "/api/signalops/auto-paper/review-decision-events/verify"),
        ("POST", "/api/signalops/auto-paper/review-decision-events/handoff"),
        ("POST", "/api/research/traces/import"),
        ("POST", "/api/plugins"),
        ("POST", "/api/plugins/artifacts/cleanup"),
        ("POST", "/api/plugins/technical_kline_readonly/artifacts"),
        ("PUT", "/api/agents/runtime/llm-profiles/default"),
    ]
    for method, path in protected_requests:
        status, data = await asgi_json(method, path, {})
        assert status == 401
        assert data["detail"] == "API write authentication required."


@pytest.mark.asyncio
async def test_strict_mode_rejects_bad_token(monkeypatch):
    monkeypatch.setenv("API_AUTH_MODE", "strict")
    monkeypatch.setenv("API_WRITE_TOKEN", "unit-secret")

    status, data = await asgi_json(
        "POST",
        "/api/config/validate",
        {"changes": {"run_mode_default": "DEEP_MODE"}},
        headers={"Authorization": "Bearer wrong-secret"},
    )

    assert status == 403
    assert data["detail"] == "Invalid API write token."


@pytest.mark.asyncio
async def test_strict_mode_requires_token_for_sensitive_reads(monkeypatch):
    monkeypatch.setenv("API_AUTH_MODE", "strict")
    monkeypatch.setenv("API_WRITE_TOKEN", "unit-secret")

    protected_reads = [
        ("/api/config/schema", lambda data: isinstance(data, list)),
        (
            "/api/signalops/auto-paper/review-decision-events?limit=1",
            lambda data: data["schema"] == "signalops_review_decision_event_export_v1",
        ),
    ]

    for path, validate_allowed in protected_reads:
        missing_status, missing_data = await asgi_json("GET", path)
        allowed_status, allowed_data = await asgi_json(
            "GET",
            path,
            headers={"Authorization": "Bearer unit-secret"},
        )

        assert missing_status == 401
        assert missing_data["detail"] == "API authentication required."
        assert allowed_status == 200
        assert validate_allowed(allowed_data)

    missing_status, missing_data = await asgi_json(
        "POST",
        "/api/signalops/auto-paper/review-decision-events/verify",
        {"bundle": {}},
    )
    allowed_status, allowed_data = await asgi_json(
        "POST",
        "/api/signalops/auto-paper/review-decision-events/verify",
        {"bundle": {}},
        headers={"Authorization": "Bearer unit-secret"},
    )

    assert missing_status == 401
    assert missing_data["detail"] == "API write authentication required."
    assert allowed_status == 200
    assert allowed_data["schema"] == "signalops_review_decision_event_export_verification_v1"
    assert allowed_data["status"] == "UNSIGNED"


@pytest.mark.asyncio
async def test_strict_mode_accepts_eventsource_stream_query_token(monkeypatch):
    monkeypatch.setenv("API_AUTH_MODE", "strict")
    monkeypatch.setenv("API_RESEARCHER_TOKEN", "research-secret")

    missing_status, missing_data = await asgi_json("GET", "/api/analysis/runs/RUN_UNIT/stream")
    allowed_status, allowed_headers, allowed_body = await asgi_raw(
        "GET",
        "/api/analysis/runs/RUN_UNIT/stream?api_key=research-secret",
    )

    assert missing_status == 401
    assert missing_data["detail"] == "API authentication required."
    assert allowed_status == 200
    assert allowed_headers["content-type"].startswith("text/event-stream")
    assert b"RUN_NOT_FOUND" in allowed_body


@pytest.mark.asyncio
async def test_strict_mode_rejects_query_token_on_non_stream_read(monkeypatch):
    monkeypatch.setenv("API_AUTH_MODE", "strict")
    monkeypatch.setenv("API_WRITE_TOKEN", "unit-secret")

    status, data = await asgi_json("GET", "/api/config/schema?api_key=unit-secret")

    assert status == 401
    assert data["detail"] == "API authentication required."


@pytest.mark.asyncio
async def test_strict_mode_query_token_auth_matrix_keeps_exception_stream_scoped(monkeypatch):
    monkeypatch.setenv("API_AUTH_MODE", "strict")
    monkeypatch.setenv("API_RESEARCHER_TOKEN", "research-secret")

    for token_param in QUERY_TOKEN_PARAM_NAMES:
        blocked_cases = [
            ("GET", f"/api/config/schema?{token_param}=research-secret", None, "API authentication required."),
            (
                "POST",
                f"/api/config/validate?{token_param}=research-secret",
                {"changes": {}},
                "API write authentication required.",
            ),
            ("DELETE", f"/api/analysis/runs/RUN_UNIT?{token_param}=research-secret", None, "API write authentication required."),
        ]
        for method, path, body, expected_detail in blocked_cases:
            status, data = await asgi_json(method, path, body)

            assert status == 401
            assert data["detail"] == expected_detail

        public_status, public_data = await asgi_json("GET", f"/api/health?{token_param}=research-secret")
        assert public_status == 200
        assert public_data["status"] == "ok"

        stream_status, stream_headers, stream_body = await asgi_raw(
            "GET",
            f"/api/analysis/runs/RUN_UNIT/stream?{token_param}=research-secret",
        )
        assert stream_status == 200
        assert stream_headers["content-type"].startswith("text/event-stream")
        assert b"RUN_NOT_FOUND" in stream_body


@pytest.mark.asyncio
async def test_write_mode_keeps_reads_public_but_protects_writes(monkeypatch):
    monkeypatch.setenv("API_AUTH_MODE", "write")
    monkeypatch.setenv("API_WRITE_TOKEN", "unit-secret")

    read_status, read_data = await asgi_json("GET", "/api/config/schema")
    write_status, write_data = await asgi_json("POST", "/api/config/validate", {"changes": {}})

    assert read_status == 200
    assert isinstance(read_data, list)
    assert write_status == 401
    assert write_data["detail"] == "API write authentication required."


@pytest.mark.asyncio
async def test_strict_mode_binds_operator_role_to_token_not_header(monkeypatch):
    monkeypatch.setenv("API_AUTH_MODE", "strict")
    monkeypatch.setenv("API_RESEARCHER_TOKEN", "research-secret")

    status, data = await asgi_json(
        "POST",
        "/api/signalops/auto-paper/command",
        {},
        headers={"Authorization": "Bearer research-secret", "X-Operator-Role": "admin"},
    )

    assert status == 403
    assert data["detail"]["required_role"] == "operator"
    assert data["detail"]["operator"] == {
        "id": "api_researcher",
        "role": "researcher",
        "source": "api_token",
    }


@pytest.mark.asyncio
async def test_runtime_public_response_redacts_sensitive_extra_fields_through_asgi(monkeypatch, tmp_path):
    monkeypatch.setenv("API_AUTH_MODE", "strict")
    monkeypatch.setenv("API_ADMIN_TOKEN", "admin-secret")
    monkeypatch.setattr(agent_runtime_store, "STORAGE_FILE", tmp_path / "agent_runtime.json")
    monkeypatch.setattr(agent_runtime_store, "RUNS_DIR", tmp_path / "runs")

    agent_runtime_store.upsert_llm_profile(
        "asgi_headers_llm",
        UpsertLLMProfileRequest(
            label="ASGI Headers LLM",
            provider="openai_compatible",
            base_url="https://api.openai.com/v1",
            model="asgi-model",
            api_key="sk-asgi-secret",
            extra_headers={
                "Authorization": "Bearer hidden",
                "X-API-Key": "hidden-key",
                "X-Trace-ID": "trace-visible",
            },
            enabled=True,
        ),
    )
    agent_runtime_store.upsert_market_data_profile(
        "asgi_headers_market",
        UpsertMarketDataProfileRequest(
            label="ASGI Headers Market",
            provider="generic_rest",
            base_url="https://quotes.example.test",
            api_key="market-asgi-secret",
            extra_headers={
                "Authorization": "Bearer market-hidden",
                "X-Trace-ID": "market-trace-visible",
            },
            extra_query_params={
                "token": "query-hidden",
                "region": "cn",
            },
            enabled=True,
        ),
    )

    status, data = await asgi_json(
        "GET",
        "/api/agents/runtime",
        headers={"Authorization": "Bearer admin-secret"},
    )

    assert status == 200
    response_text = json.dumps(data, ensure_ascii=False)
    assert "sk-asgi-secret" not in response_text
    assert "market-asgi-secret" not in response_text
    assert "Bearer hidden" not in response_text
    assert "hidden-key" not in response_text
    assert "market-hidden" not in response_text
    assert "query-hidden" not in response_text

    llm_profile = next(item for item in data["llm_profiles"] if item["id"] == "asgi_headers_llm")
    market_profile = next(item for item in data["market_data_profiles"] if item["id"] == "asgi_headers_market")
    assert llm_profile["extra_headers"]["Authorization"] == "<redacted>"
    assert llm_profile["extra_headers"]["X-API-Key"] == "<redacted>"
    assert llm_profile["extra_headers"]["X-Trace-ID"] == "trace-visible"
    assert market_profile["extra_headers"]["Authorization"] == "<redacted>"
    assert market_profile["extra_headers"]["X-Trace-ID"] == "market-trace-visible"
    assert market_profile["extra_query_params"]["token"] == "<redacted>"
    assert market_profile["extra_query_params"]["region"] == "cn"


@pytest.mark.asyncio
async def test_signalops_live_module_stays_disabled_through_strict_asgi(monkeypatch, tmp_path):
    monkeypatch.setenv("API_AUTH_MODE", "strict")
    monkeypatch.setenv("API_ADMIN_TOKEN", "admin-secret")
    monkeypatch.setattr(auto_module, "STORAGE_FILE", tmp_path / "auto_paper_trading.json")
    auto_paper_trading_store.stop_background_loop()
    auto_paper_trading_store._loop_started_at = ""
    auto_paper_trading_store._loop_heartbeat_at = ""
    auto_paper_trading_store._loop_last_error = ""
    auto_paper_trading_store._last_storage_warning = ""

    status, config = await asgi_json(
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
                "broker_profile_id": "broker-unit",
                "account_id": "acct-unit",
                "simulation_only": False,
                "is_real_trade": True,
            },
        },
        headers={"Authorization": "Bearer admin-secret"},
    )

    assert status == 200
    assert config["automation_mode"] == "SIMULATION"
    assert config["simulation_module"]["enabled"] is True
    assert config["simulation_module"]["order_namespace"] == "SIM_*"
    assert config["live_module"]["enabled"] is False
    assert config["live_module"]["execution_enabled"] is False
    assert config["live_module"]["order_router"] == "DISABLED"
    assert config["live_module"]["broker_profile_id"] == "broker-unit"
    assert config["live_module"]["account_id"] == "acct-unit"
    assert config["live_module"]["simulation_only"] is True
    assert config["live_module"]["is_real_trade"] is False

    status, data = await asgi_json(
        "GET",
        "/api/signalops/auto-paper/status",
        headers={"Authorization": "Bearer admin-secret"},
    )

    assert status == 200
    assert data["automation_mode"] == "SIMULATION"
    assert data["automation_modules"]["active_module"] == "simulation"
    assert data["automation_modules"]["real_trade_enabled"] is False
    assert data["automation_modules"]["live"]["status"] == "CONFIGURED_DISABLED"
    assert data["automation_modules"]["live"]["execution_enabled"] is False
    assert data["automation_modules"]["live"]["order_router"] == "DISABLED"
    assert data["automation_modules"]["live"]["simulation_only"] is True
    assert data["automation_modules"]["live"]["is_real_trade"] is False


@pytest.mark.asyncio
async def test_strict_mode_accepts_valid_bearer_token(monkeypatch):
    monkeypatch.setenv("API_AUTH_MODE", "strict")
    monkeypatch.setenv("SUPER_API_WRITE_TOKEN", "unit-secret")

    status, data = await asgi_json(
        "POST",
        "/api/config/validate",
        {"changes": {"run_mode_default": "DEEP_MODE"}},
        headers={"Authorization": "Bearer unit-secret", "X-Operator-Role": "researcher"},
    )

    assert status == 200
    assert data["passed"] is True


@pytest.mark.asyncio
async def test_strict_mode_accepts_api_key_header(monkeypatch):
    monkeypatch.setenv("API_AUTH_MODE", "strict")
    monkeypatch.setenv("API_WRITE_TOKEN", "unit-secret")

    status, data = await asgi_json(
        "POST",
        "/api/config/validate",
        {"changes": {"run_mode_default": "DEEP_MODE"}},
        headers={"X-API-Key": "unit-secret"},
    )

    assert status == 200
    assert data["passed"] is True


@pytest.mark.asyncio
async def test_production_health_get_is_public(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("API_WRITE_TOKEN", "unit-secret")

    status, data = await asgi_json("GET", "/api/health")

    assert status == 200
    assert data["status"] == "ok"
