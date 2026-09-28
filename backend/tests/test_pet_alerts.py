import json

import pytest
from fastapi import FastAPI

from app.api import routes_pet_alerts
from app.core.pet_alerts import pet_alert_center


@pytest.fixture(autouse=True)
def clear_alerts():
    pet_alert_center.clear()
    yield
    pet_alert_center.clear()


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(routes_pet_alerts.router, prefix="/api")
    return app


async def asgi_json(app, method: str, path: str, json_body=None):
    body = b""
    headers = [(b"host", b"testserver")]
    raw_path, _, query = path.partition("?")
    if json_body is not None:
        body = json.dumps(json_body).encode("utf-8")
        headers.append((b"content-type", b"application/json"))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": raw_path,
        "raw_path": raw_path.encode("ascii"),
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
async def test_pet_alert_routes_handle_empty_queue(app):
    status_code, status = await asgi_json(app, "GET", "/api/pet/alerts/status")
    assert status_code == 200
    assert status["queue_size"] == 0
    assert status["unacknowledged_count"] == 0

    status_code, latest = await asgi_json(app, "GET", "/api/pet/alerts/latest")
    assert status_code == 200
    assert latest["count"] == 0
    assert latest["alerts"] == []


@pytest.mark.asyncio
async def test_pet_alert_defaults_dedupe_and_ack(app):
    first = pet_alert_center.report_alert({"dedupe_key": "same"})
    duplicate = pet_alert_center.report_alert({"dedupe_key": "same"})

    assert first is not None
    assert duplicate is None
    assert first["severity"] == "info"
    assert first["title"] == "Quant alert"

    status_code, latest = await asgi_json(app, "GET", "/api/pet/alerts/latest?min_severity=info")
    assert status_code == 200
    assert latest["count"] == 1

    alert_id = latest["alerts"][0]["id"]
    status_code, ack = await asgi_json(app, "POST", f"/api/pet/alerts/{alert_id}/ack")
    assert status_code == 200
    assert ack == {"id": alert_id, "acknowledged": True}

    _, latest_after_ack = await asgi_json(app, "GET", "/api/pet/alerts/latest")
    assert latest_after_ack["count"] == 0


def test_auto_paper_result_generates_simulation_only_alert():
    created = pet_alert_center.report_auto_paper_tick(
        {
            "status": "COMPLETED",
            "symbol": "603663",
            "signal_id": "sig-1",
            "message": "tick ok",
            "order": {
                "order_id": "order-1",
                "action": "SIM_BUY",
                "symbol": "603663",
                "action_reason": "breakout",
            },
        }
    )

    assert len(created) == 1
    assert created[0]["source"] == "signalops"
    assert created[0]["event_type"] == "SIM_ORDER"
    assert "Simulation-only" in created[0]["message"]


def test_data_reliability_partial_generates_warning():
    alert = pet_alert_center.report_data_reliability(
        [
            {"adapterId": "akshare", "status": "PARTIAL", "healthy": True},
            {"adapterId": "tushare", "status": "READY", "healthy": True},
        ]
    )

    assert alert is not None
    assert alert["severity"] == "warning"
    assert alert["source"] == "data_reliability"
    assert alert["dedupe_key"].startswith("data_reliability:")
