"""Readiness must reflect the real simulation loop states on a fresh deployment."""
import asyncio
import json

import httpx
import pytest

from app.api import routes_health
from app.core import auto_paper_trading
from app.core.startup_status import startup_status
from app.main import app


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "enabled,loop_state,expected_status",
    [
        (False, "STOPPED", 200),
        (False, "RUNNING", 200),
        (True, "RUNNING", 200),
        (True, "STOPPED", 503),
        (True, "FAILED", 503),
        (False, "FAILED", 503),
    ],
)
async def test_ready_uses_actual_simulation_loop_states(
    monkeypatch, tmp_path, enabled, loop_state, expected_status
):
    state_file = tmp_path / "auto_paper_trading.json"
    state_file.write_text(json.dumps({"enabled": enabled, "symbol": "SYNTHETIC", "simulation_module": {"enabled": enabled}}), encoding="utf-8")
    monkeypatch.setattr(auto_paper_trading, "STORAGE_FILE", state_file)
    store = auto_paper_trading.AutoPaperTradingStore()
    monkeypatch.setattr(routes_health, "auto_paper_trading_store", store)
    if loop_state == "RUNNING":
        store._task = asyncio.create_task(asyncio.Event().wait())
    elif loop_state == "FAILED":
        async def fail_loop():
            raise RuntimeError("synthetic loop failure")
        store._task = asyncio.create_task(fail_loop())
        await asyncio.gather(store._task, return_exceptions=True)
    await startup_status.reset()
    await startup_status.mark_core_ready()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get("/api/ready")
        payload = response.json()
        check = payload["checks"]["autoPaperTrading"]
        assert check["loopHealth"] == loop_state
        assert check["enabled"] is enabled
        assert response.status_code == expected_status, payload
        assert ("autoPaperTrading" in payload["degradedChecks"]) == (expected_status == 503)
    finally:
        if store._task is not None and not store._task.done():
            store._task.cancel()
            await asyncio.gather(store._task, return_exceptions=True)
        await startup_status.reset()


@pytest.mark.asyncio
async def test_disabled_simulation_loop_does_not_mask_required_startup_failure(monkeypatch, tmp_path):
    state_file = tmp_path / "auto_paper_trading.json"
    state_file.write_text('{"enabled": false}', encoding="utf-8")
    monkeypatch.setattr(auto_paper_trading, "STORAGE_FILE", state_file)
    monkeypatch.setattr(routes_health, "auto_paper_trading_store", auto_paper_trading.AutoPaperTradingStore())
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("REQUIRE_DB_MIGRATIONS", raising=False)
    await startup_status.reset()
    async def fail_migration():
        return {"status": "error"}
    await startup_status.run_component("database_migrations", "core", fail_migration, required=True)
    await startup_status.mark_core_ready()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get("/api/ready")
        payload = response.json()
        assert payload["checks"]["autoPaperTrading"]["status"] == "ok"
        assert response.status_code == 503
        assert "startup" in payload["degradedChecks"]
        assert payload["startup"]["coreReady"] is False
    finally:
        await startup_status.reset()
