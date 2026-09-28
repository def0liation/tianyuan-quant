import pytest

from app.api import routes_stream
from app.core.operator_context import current_operator, reset_current_operator


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
)


class FakeWebSocket:
    def __init__(self, *, headers=None, query_params=None):
        self.headers = headers or {}
        self.query_params = query_params or {}
        self.scope = {}
        self.closed = []
        self.accepted = False
        self.sent_json = []

    async def accept(self):
        self.accepted = True

    async def send_json(self, payload):
        self.sent_json.append(payload)

    async def close(self, code=1000, reason=None):
        self.closed.append({"code": code, "reason": reason})


@pytest.fixture(autouse=True)
def clear_auth_env(monkeypatch):
    for name in AUTH_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.mark.asyncio
async def test_websocket_auth_allows_dev_mode_without_token():
    ws = FakeWebSocket()

    authorized, operator_token = await routes_stream._authorize_websocket(ws)

    assert authorized is True
    assert operator_token is None
    assert ws.closed == []


@pytest.mark.asyncio
async def test_websocket_auth_rejects_strict_mode_without_configured_token(monkeypatch):
    monkeypatch.setenv("API_AUTH_MODE", "strict")
    ws = FakeWebSocket()

    authorized, operator_token = await routes_stream._authorize_websocket(ws)

    assert authorized is False
    assert operator_token is None
    assert ws.closed == [{"code": 1008, "reason": "API authentication token is not configured."}]


@pytest.mark.asyncio
async def test_websocket_auth_rejects_missing_or_bad_token(monkeypatch):
    monkeypatch.setenv("API_AUTH_MODE", "strict")
    monkeypatch.setenv("API_OPERATOR_TOKEN", "operator-secret")

    missing = FakeWebSocket()
    bad = FakeWebSocket(headers={"authorization": "Bearer wrong-secret"})

    missing_authorized, _ = await routes_stream._authorize_websocket(missing)
    bad_authorized, _ = await routes_stream._authorize_websocket(bad)

    assert missing_authorized is False
    assert bad_authorized is False
    assert missing.closed == [{"code": 1008, "reason": "API authentication required."}]
    assert bad.closed == [{"code": 1008, "reason": "API authentication required."}]


@pytest.mark.asyncio
async def test_websocket_auth_binds_operator_to_bearer_token(monkeypatch):
    monkeypatch.setenv("API_AUTH_MODE", "strict")
    monkeypatch.setenv("API_RESEARCHER_TOKEN", "research-secret")
    ws = FakeWebSocket(headers={"authorization": "Bearer research-secret"})

    authorized, operator_token = await routes_stream._authorize_websocket(ws)
    try:
        assert authorized is True
        assert ws.closed == []
        assert ws.scope["state"]["operator"].as_payload() == {
            "id": "api_researcher",
            "role": "researcher",
            "source": "api_token",
        }
        assert current_operator().role == "researcher"
    finally:
        reset_current_operator(operator_token)


@pytest.mark.asyncio
async def test_websocket_auth_accepts_query_token(monkeypatch):
    monkeypatch.setenv("API_AUTH_MODE", "strict")
    monkeypatch.setenv("API_OPERATOR_TOKEN", "operator-secret")
    ws = FakeWebSocket(query_params={"api_key": "operator-secret"})

    authorized, operator_token = await routes_stream._authorize_websocket(ws)
    try:
        assert authorized is True
        assert ws.scope["state"]["operator"].role == "operator"
        assert ws.closed == []
    finally:
        reset_current_operator(operator_token)


@pytest.mark.asyncio
async def test_generate_events_closes_after_stale_terminal_event(monkeypatch):
    run = {
        "runId": "RUN_STALE_STREAM_UNIT",
        "status": "STALE",
        "streamEvents": [
            {
                "event_type": "RUN_STALE_RECOVERED",
                "run_id": "RUN_STALE_STREAM_UNIT",
                "node_id": "system",
                "message": "watchdog recovered stale run",
            }
        ],
    }
    monkeypatch.setattr(routes_stream, "get_run", lambda run_id: run)
    monkeypatch.setattr(routes_stream, "contains_run", lambda run_id: True)

    chunks = []
    async for chunk in routes_stream.generate_events("RUN_STALE_STREAM_UNIT"):
        chunks.append(chunk)

    assert any("RUN_STALE_RECOVERED" in chunk for chunk in chunks)
    assert chunks[-1] == "event: done\ndata: {}\n\n"
    assert len(chunks) == 2


@pytest.mark.asyncio
async def test_generate_events_closes_after_cancelled_terminal_event(monkeypatch):
    run = {
        "runId": "RUN_CANCELLED_STREAM_UNIT",
        "status": "CANCELLED",
        "streamEvents": [
            {
                "event_type": "RUN_CANCELLED",
                "run_id": "RUN_CANCELLED_STREAM_UNIT",
                "node_id": "system",
                "message": "operator cancelled run",
            }
        ],
    }
    monkeypatch.setattr(routes_stream, "get_run", lambda run_id: run)
    monkeypatch.setattr(routes_stream, "contains_run", lambda run_id: True)

    chunks = []
    async for chunk in routes_stream.generate_events("RUN_CANCELLED_STREAM_UNIT"):
        chunks.append(chunk)

    assert any("RUN_CANCELLED" in chunk for chunk in chunks)
    assert chunks[-1] == "event: done\ndata: {}\n\n"
    assert len(chunks) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "terminal_event_type"),
    [
        ("CANCELLED", "RUN_CANCELLED"),
        ("STALE", "RUN_STALE_RECOVERED"),
    ],
)
async def test_websocket_terminal_status_keeps_status_specific_event(monkeypatch, status, terminal_event_type):
    run_id = f"RUN_WS_{status}"
    run = {
        "runId": run_id,
        "status": status,
        "streamEvents": [
            {
                "event_type": terminal_event_type,
                "run_id": run_id,
                "node_id": "system",
                "message": f"{status} terminal event",
            }
        ],
    }
    monkeypatch.setattr(routes_stream, "get_run", lambda requested_run_id: run)

    ws = FakeWebSocket()

    await routes_stream.websocket_analysis_events(ws, run_id)

    assert ws.accepted is True
    assert [event["event_type"] for event in ws.sent_json] == [terminal_event_type]
    assert all(event["event_type"] != "RUN_FINISHED" for event in ws.sent_json)


@pytest.mark.asyncio
async def test_websocket_synthesizes_status_specific_terminal_event_when_missing(monkeypatch):
    run_id = "RUN_WS_STALE_WITHOUT_EVENT"
    run = {"runId": run_id, "status": "STALE", "streamEvents": []}
    monkeypatch.setattr(routes_stream, "get_run", lambda requested_run_id: run)

    ws = FakeWebSocket()

    await routes_stream.websocket_analysis_events(ws, run_id)

    assert ws.sent_json == [{"event_type": "RUN_STALE_RECOVERED", "run_id": run_id, "status": "STALE"}]


@pytest.mark.asyncio
async def test_websocket_reports_run_removed_after_initial_load(monkeypatch):
    run_id = "RUN_WS_REMOVED"
    responses = iter(
        [
            {"runId": run_id, "status": "RUNNING", "streamEvents": []},
            None,
        ]
    )
    monkeypatch.setattr(routes_stream, "get_run", lambda requested_run_id: next(responses))

    ws = FakeWebSocket()

    await routes_stream.websocket_analysis_events(ws, run_id)

    assert ws.accepted is True
    assert ws.sent_json == [
        {"event_type": "RUN_REMOVED", "run_id": run_id, "message": "Run no longer exists"}
    ]


@pytest.mark.asyncio
async def test_websocket_reports_stream_timeout(monkeypatch):
    run_id = "RUN_WS_TIMEOUT"
    run = {"runId": run_id, "status": "RUNNING", "streamEvents": []}
    timestamps = iter([0, 601])
    monkeypatch.setattr(routes_stream, "get_run", lambda requested_run_id: run)
    monkeypatch.setattr(routes_stream.time, "time", lambda: next(timestamps))

    ws = FakeWebSocket()

    await routes_stream.websocket_analysis_events(ws, run_id)

    assert ws.accepted is True
    assert ws.sent_json == [
        {
            "event_type": "STREAM_TIMEOUT",
            "run_id": run_id,
            "message": "Stream timeout after 600s",
        }
    ]
