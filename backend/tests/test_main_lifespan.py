import asyncio

import pytest

from app import main as main_module
from app.core.startup_status import StartupStatusRegistry


@pytest.mark.asyncio
async def test_app_lifespan_runs_startup_and_shutdown(monkeypatch):
    events: list[str] = []

    async def fake_startup():
        events.append("startup")

    async def fake_shutdown():
        events.append("shutdown")

    monkeypatch.setattr(main_module, "startup_event", fake_startup)
    monkeypatch.setattr(main_module, "shutdown_event", fake_shutdown)

    async with main_module.app.router.lifespan_context(main_module.app):
        events.append("inside")

    assert events == ["startup", "inside", "shutdown"]


@pytest.mark.asyncio
async def test_market_data_warmup_skips_external_checks_in_mock_mode(monkeypatch):
    monkeypatch.setenv("TIANYUAN_FORCE_MOCK_MARKET_DATA", "1")

    def fail_if_called():
        raise AssertionError("mock-mode startup must not call external market data warmup")

    monkeypatch.setattr(
        "app.core.market_data_adapter.register_default_market_data_adapters",
        fail_if_called,
    )

    result = await main_module._warm_market_data_status()

    assert result == {"status": "SKIPPED", "reason": "mock_market_data_mode"}


@pytest.mark.asyncio
async def test_auto_paper_loop_warmup_skips_background_loop_in_mock_mode(monkeypatch):
    monkeypatch.setenv("TIANYUAN_MARKET_DATA_MODE", "mock")

    def fail_if_called():
        raise AssertionError("mock-mode startup must not start the auto paper background loop")

    monkeypatch.setattr(main_module.auto_paper_trading_store, "start_background_loop", fail_if_called)

    result = await main_module._warm_auto_paper_loop()

    assert result == {"status": "SKIPPED", "reason": "mock_market_data_mode"}


@pytest.mark.asyncio
async def test_startup_status_preserves_skipped_component_details():
    registry = StartupStatusRegistry()

    async def skipped_component():
        return {"status": "SKIPPED", "reason": "mock_market_data_mode"}

    result = await registry.run_component("market_data_status", "optional", skipped_component)
    await registry.mark_finished()

    snapshot = await registry.snapshot()
    component = next(item for item in snapshot["components"] if item["name"] == "market_data_status")

    assert result == {"status": "SKIPPED", "reason": "mock_market_data_mode"}
    assert component["status"] == "SKIPPED"
    assert component["details"]["reason"] == "mock_market_data_mode"
    assert snapshot["phase"] == "READY"


@pytest.mark.asyncio
async def test_optional_startup_warmers_run_local_components_concurrently_and_defer_market_data(monkeypatch):
    await main_module.startup_status.reset()
    monkeypatch.setattr(main_module, "startup_market_data_status_task", None)
    local_names = [
        "analysis_history",
        "research_summary",
        "backtest_summary",
        "plugin_defaults",
        "auto_paper_loop",
    ]
    started = {name: asyncio.Event() for name in local_names}
    release_local = asyncio.Event()
    market_entered = asyncio.Event()
    release_market = asyncio.Event()

    def local_warmer(name: str):
        async def _warm():
            started[name].set()
            await release_local.wait()
            return {"component": name}

        return _warm

    async def slow_market_data_status():
        market_entered.set()
        await release_market.wait()
        return {"status": "OK", "component": "market_data_status"}

    monkeypatch.setattr(main_module, "_warm_analysis_history", local_warmer("analysis_history"))
    monkeypatch.setattr(main_module, "_warm_research_summary", local_warmer("research_summary"))
    monkeypatch.setattr(main_module, "_warm_backtest_summary", local_warmer("backtest_summary"))
    monkeypatch.setattr(main_module, "_warm_plugin_defaults", local_warmer("plugin_defaults"))
    monkeypatch.setattr(main_module, "_warm_auto_paper_loop", local_warmer("auto_paper_loop"))
    monkeypatch.setattr(main_module, "_warm_market_data_status", slow_market_data_status)

    warmup_task = asyncio.create_task(main_module._run_optional_startup_warmers())
    try:
        for event in started.values():
            await asyncio.wait_for(event.wait(), timeout=1)

        release_local.set()
        await asyncio.wait_for(warmup_task, timeout=1)
        await asyncio.sleep(0)
        snapshot = await main_module.startup_status.snapshot()
        statuses = {item["name"]: item["status"] for item in snapshot["components"]}

        assert snapshot["phase"] == "READY"
        assert snapshot["ready"] is True
        assert all(statuses[name] == "OK" for name in local_names)
        assert statuses["market_data_status"] == "RUNNING"
        assert market_entered.is_set()

        release_market.set()
        await asyncio.wait_for(main_module.startup_market_data_status_task, timeout=1)
        snapshot = await main_module.startup_status.snapshot()
        market_component = next(item for item in snapshot["components"] if item["name"] == "market_data_status")
        assert snapshot["phase"] == "READY"
        assert market_component["status"] == "OK"
        assert "elapsedMs" in market_component
    finally:
        release_local.set()
        release_market.set()
        if not warmup_task.done():
            warmup_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await warmup_task
        if (
            main_module.startup_market_data_status_task
            and not main_module.startup_market_data_status_task.done()
        ):
            main_module.startup_market_data_status_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await main_module.startup_market_data_status_task
        await main_module.startup_status.reset()


@pytest.mark.asyncio
async def test_deferred_market_data_status_failure_does_not_revoke_ready_phase(monkeypatch):
    await main_module.startup_status.reset()
    monkeypatch.setattr(main_module, "startup_market_data_status_task", None)

    async def ok_component():
        return {"status": "OK"}

    async def failing_market_data_status():
        raise RuntimeError("market unavailable")

    monkeypatch.setattr(main_module, "_warm_analysis_history", ok_component)
    monkeypatch.setattr(main_module, "_warm_research_summary", ok_component)
    monkeypatch.setattr(main_module, "_warm_backtest_summary", ok_component)
    monkeypatch.setattr(main_module, "_warm_plugin_defaults", ok_component)
    monkeypatch.setattr(main_module, "_warm_auto_paper_loop", ok_component)
    monkeypatch.setattr(main_module, "_warm_market_data_status", failing_market_data_status)

    await main_module._run_optional_startup_warmers()
    await asyncio.wait_for(main_module.startup_market_data_status_task, timeout=1)

    snapshot = await main_module.startup_status.snapshot()
    market_component = next(item for item in snapshot["components"] if item["name"] == "market_data_status")

    assert snapshot["phase"] == "READY"
    assert snapshot["ready"] is True
    assert snapshot["degradedComponents"] == ["market_data_status"]
    assert market_component["status"] == "ERROR"
    assert market_component["error"].startswith("RuntimeError: market unavailable")

    await main_module.startup_status.reset()


@pytest.mark.asyncio
async def test_deferred_market_data_status_timeout_marks_error_without_waiting_for_completion(monkeypatch):
    await main_module.startup_status.reset()
    release_market = asyncio.Event()
    cancelled = asyncio.Event()

    async def blocked_market_data_status():
        try:
            await release_market.wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr(main_module, "MARKET_DATA_STATUS_WARMUP_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(main_module, "_warm_market_data_status", blocked_market_data_status)

    await main_module.startup_status.start_component("market_data_status", "optional")
    started = asyncio.get_running_loop().time()
    result = await main_module._finish_deferred_market_data_status_warmer()
    await asyncio.wait_for(cancelled.wait(), timeout=1)
    elapsed = asyncio.get_running_loop().time() - started
    snapshot = await main_module.startup_status.snapshot()
    market_component = next(item for item in snapshot["components"] if item["name"] == "market_data_status")

    assert result is None
    assert elapsed < 0.5
    assert market_component["status"] == "ERROR"
    assert market_component["error"] == "Timeout after 0.01s"

    release_market.set()
    await main_module.startup_status.reset()
