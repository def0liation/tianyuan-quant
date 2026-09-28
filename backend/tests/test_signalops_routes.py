import json

import pytest
from fastapi import FastAPI

from app.api import routes_signalops
from app.core.signalops_store import signalops_store


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(routes_signalops.router, prefix="/api")
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
async def test_create_signal_route_ignores_client_supplied_gate_evidence(app):
    status, data = await asgi_json(
        app,
        "POST",
        "/api/signals",
        {
            "symbol": "603663",
            "risk_passed": True,
            "dvg_passed": True,
            "dvg_status": "PASS",
            "qiam_passed": True,
            "qiam_status": "BUY",
            "execution_reachable": True,
            "portfolio_allowed": True,
        },
    )

    assert status == 200
    assert data["risk_passed"] is False
    assert data["dvg_passed"] is False
    assert data["qiam_passed"] is False
    assert data["execution_reachable"] is False
    assert data["portfolio_allowed"] is False
    assert "risk_passed" in data["metadata_json"]["client_gate_fields_ignored"]


@pytest.mark.asyncio
async def test_transition_route_rejects_client_managed_gate_context(app):
    signal = await signalops_store.create_signal({"symbol": "603663", "source_run_id": "RUN_ROUTE_GATE"})

    status, data = await asgi_json(
        app,
        "POST",
        f"/api/signals/{signal['signal_id']}/transition",
        {
            "target_status": "MANUAL_CONFIRMED",
            "gate_context": {"manual_confirmed": True, "execution_completed": True},
        },
    )

    assert status == 400
    assert data["detail"]["reason"] == "SIGNAL_GATE_CONTEXT_SERVER_MANAGED"
    assert data["detail"]["server_managed_keys"] == ["execution_completed", "manual_confirmed"]


@pytest.mark.asyncio
async def test_signal_review_route_returns_simulation_boundary(app):
    signal = await signalops_store.create_signal({"symbol": "603663", "source_run_id": "RUN_ROUTE_REVIEW"})

    status, data = await asgi_json(
        app,
        "POST",
        f"/api/signals/{signal['signal_id']}/review",
        {
            "reviewer": "human",
            "review_type": "MANUAL",
            "decision": "APPROVE",
            "note": "review stays in simulation boundary",
            "review_fields": ["risk", "dvg"],
            "simulation_only": False,
            "is_real_trade": True,
        },
    )

    assert status == 200
    assert data["simulation_only"] is True
    assert data["is_real_trade"] is False

    detail = await signalops_store.get_signal_detail(signal["signal_id"])
    assert detail["reviews"][0]["simulation_only"] is True
    assert detail["reviews"][0]["is_real_trade"] is False


@pytest.mark.asyncio
async def test_paper_portfolio_allow_missing_returns_null_without_changing_default_404(app):
    signal = await signalops_store.create_signal({"symbol": "603663", "source_run_id": "RUN_ROUTE_PORTFOLIO"})

    status, data = await asgi_json(app, "GET", f"/api/signalops/{signal['signal_id']}/paper-portfolio")
    assert status == 404
    assert data["detail"]["reason"] == "PAPER_PORTFOLIO_NOT_FOUND"

    status, data = await asgi_json(
        app,
        "GET",
        f"/api/signalops/{signal['signal_id']}/paper-portfolio?allow_missing=true",
    )
    assert status == 200
    assert data is None

    status, data = await asgi_json(app, "GET", "/api/signalops/UNKNOWN_SIGNAL/paper-portfolio?allow_missing=true")
    assert status == 200
    assert data is None
