import json
from types import SimpleNamespace

import httpx
import pytest

from app.api import routes_agents
from app.core import agent_runtime_store, http_auth, market_data_adapter
from app.main import app


@pytest.fixture(autouse=True)
def isolated_auth(monkeypatch):
    for name in (
        "API_WRITE_TOKEN", "SUPER_API_WRITE_TOKEN", "API_ADMIN_TOKEN", "SUPER_API_ADMIN_TOKEN",
        "API_OPERATOR_TOKEN", "SUPER_API_OPERATOR_TOKEN", "API_RESEARCHER_TOKEN",
        "SUPER_API_RESEARCHER_TOKEN", "API_VIEWER_TOKEN", "SUPER_API_VIEWER_TOKEN",
        "API_AUTH_MODE", "APP_ENV", "ENVIRONMENT",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("API_AUTH_MODE", "strict")
    for role in ("admin", "operator", "researcher", "viewer"):
        monkeypatch.setenv(f"API_{role.upper()}_TOKEN", f"audit-{role}-fixture")


CONFIG_WRITES = (
    ("/api/agents/data-sources", {"tushare_token": "synthetic-change-fixture"}),
    ("/api/agents/market-data/adapters/tushare/config", {"enabled": False}),
)


@pytest.mark.asyncio
@pytest.mark.parametrize("path,body", CONFIG_WRITES)
@pytest.mark.parametrize("role", ("viewer", "researcher", "operator"))
async def test_global_market_configuration_requires_admin(monkeypatch, path, body, role):
    calls = []
    monkeypatch.setattr(routes_agents, "save_data_sources_config", lambda *args: calls.append(args) or {})
    monkeypatch.setattr(routes_agents, "update_market_data_adapter_config", lambda *args: calls.append(args) or SimpleNamespace(model_dump=lambda: {}))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://audit.local") as client:
        response = await client.put(path, json=body, headers={
            "Authorization": f"Bearer audit-{role}-fixture", "X-Operator-Role": "admin",
        })
    assert response.status_code == 403
    assert response.json()["detail"]["required_role"] == "admin"
    assert calls == []


@pytest.mark.asyncio
async def test_admin_data_source_write_remains_available():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://audit.local") as client:
        response = await client.put("/api/agents/data-sources", json={"tushare_token": "synthetic-admin-fixture"},
                                    headers={"Authorization": "Bearer audit-admin-fixture"})
    assert response.status_code == 200
    assert agent_runtime_store.get_data_sources_config()["tushare_token"] == "synthetic-admin-fixture"


@pytest.fixture
def fake_health_registry(monkeypatch):
    calls = []
    health = SimpleNamespace(to_public_dict=lambda: {"adapter_id": "tushare", "status": "READY"})
    class Registry:
        async def health_check_all(self):
            calls.append("all")
            return [health]
        async def build_status_matrix(self):
            calls.append("matrix")
            return SimpleNamespace(to_public_dict=lambda: {"status": "READY"})
        async def health_check_adapter(self, _adapter_id):
            calls.append("adapter")
            return health
        def list_adapters(self):
            return [health]
    monkeypatch.setattr(market_data_adapter, "register_default_market_data_adapters", lambda: Registry())
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ("true", "True", "1", "on", "yes", "t", "T", "y", "Y", "false&live_check=true"))
@pytest.mark.parametrize("mode", ("strict", "write", "write_protect"))
@pytest.mark.parametrize("role", ("viewer", "researcher"))
async def test_active_get_requires_authenticated_operator(monkeypatch, fake_health_registry, query, mode, role):
    monkeypatch.setenv("API_AUTH_MODE", mode)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://audit.local") as client:
        response = await client.get(f"/api/agents/market-data/adapters?live_check={query}", headers={
            "Authorization": f"Bearer audit-{role}-fixture", "X-Operator-Role": "admin",
        })
    assert response.status_code == 403
    assert fake_health_registry == []


@pytest.mark.asyncio
@pytest.mark.parametrize("path", (
    "/api/agents/market-data/adapters?live_check=true",
    "/api/agents/market-data/adapters?live_check=t",
    "/api/agents/market-data/adapters?live_check=y",
    "/api/agents/market-data/status",
))
@pytest.mark.parametrize("mode", ("write", "write_protect"))
async def test_write_mode_active_get_rejects_anonymous_header_admin(monkeypatch, fake_health_registry, path, mode):
    monkeypatch.setenv("API_AUTH_MODE", mode)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://audit.local") as client:
        response = await client.get(path, headers={"X-Operator-Role": "admin"})
    assert response.status_code == 401
    assert fake_health_registry == []


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", (
    ("GET", "/api/agents/market-data/status"),
    ("POST", "/api/agents/market-data/adapters/tushare/health"),
    ("POST", "/api/agents/data-sources/audit-source/test"),
))
async def test_active_checks_reject_researcher(fake_health_registry, method, path):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://audit.local") as client:
        response = await client.request(method, path, headers={"Authorization": "Bearer audit-researcher-fixture"})
    assert response.status_code == 403
    assert fake_health_registry == []


@pytest.mark.asyncio
async def test_metadata_reads_and_operator_active_check_remain_available(monkeypatch, fake_health_registry):
    monkeypatch.setenv("API_AUTH_MODE", "write")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://audit.local") as client:
        metadata = await client.get("/api/agents/market-data/adapters?live_check=true&live_check=false")
        active = await client.get("/api/agents/market-data/adapters?live_check=1",
                                  headers={"Authorization": "Bearer audit-operator-fixture"})
    assert metadata.status_code == 200
    assert active.status_code == 200
    assert fake_health_registry == ["all"]


@pytest.mark.asyncio
async def test_operator_can_read_active_status(fake_health_registry):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://audit.local") as client:
        response = await client.get("/api/agents/market-data/status",
                                    headers={"Authorization": "Bearer audit-operator-fixture"})
    assert response.status_code == 200
    assert response.json()["status"] == "READY"
    assert fake_health_registry == ["matrix"]


def test_tushare_raw_and_sync_validate_the_actual_destination(monkeypatch):
    from app.core import market_data_runner
    from app.core.adapters import tushare_adapter
    from app.core.market_data_egress_policy import MarketDataEgressBlockedError
    from app.models.agent_runtime import MarketDataProfile
    monkeypatch.setenv("MARKET_DATA_EGRESS_MODE", "strict")
    for name in ("MARKET_DATA_BASE_URL_ALLOWLIST", "MARKET_DATA_EGRESS_ALLOWLIST", "MARKET_DATA_ALLOWED_HOSTS"):
        monkeypatch.delenv(name, raising=False)
    profile = MarketDataProfile(id="audit", label="audit", provider="tushare", enabled=True,
        api_key="synthetic-token", base_url="https://outside-audit.invalid", quote_path="https://api.tushare.pro")
    calls = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def read(self): return json.dumps({"code": 0, "data": {"fields": [], "items": []}}).encode()
    def fake_open(*args, **_kwargs):
        calls.append(args)
        return Response()
    monkeypatch.setattr(market_data_runner, "urlopen", fake_open)
    monkeypatch.setattr(tushare_adapter, "urlopen", fake_open)
    for call in (market_data_runner._call_tushare_http_api_raw, tushare_adapter._call_tushare_http_api_sync):
        with pytest.raises(MarketDataEgressBlockedError):
            call(profile, "daily", {})
    assert calls == []


def test_tushare_raw_ignores_unused_quote_override_and_keeps_official_base(monkeypatch):
    from app.core import market_data_runner
    from app.core.adapters import tushare_adapter
    from app.models.agent_runtime import MarketDataProfile
    monkeypatch.setenv("MARKET_DATA_EGRESS_MODE", "strict")
    profile = MarketDataProfile(id="audit", label="audit", provider="tushare", enabled=True,
        api_key="synthetic-token", base_url="https://api.tushare.pro", quote_path="https://outside-audit.invalid")
    calls = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def read(self): return json.dumps({"code": 0, "data": {"fields": [], "items": []}}).encode()
    def fake_open(request, **_kwargs):
        calls.append(request.full_url)
        return Response()
    monkeypatch.setattr(market_data_runner, "urlopen", fake_open)
    monkeypatch.setattr(tushare_adapter, "urlopen", fake_open)
    for call in (market_data_runner._call_tushare_http_api_raw, tushare_adapter._call_tushare_http_api_sync):
        call(profile, "daily", {})
    assert calls == ["https://api.tushare.pro", "https://api.tushare.pro"]
