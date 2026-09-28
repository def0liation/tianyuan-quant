"""验收清单 §28.2 – 适配器注册中心与降级编排测试"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from app.core.market_data_adapter import (
    BaseMarketDataAdapter,
    MarketDataAdapterRegistry,
    get_adapter_registry,
    register_default_market_data_adapters,
    reset_adapter_registry,
)
from app.core import agent_runtime_store
from app.models.agent_runtime import UpdateMarketDataAdapterConfigRequest
from app.models.market_data import (
    AdapterCapability,
    AuxiliaryDataResponse,
    DataMode,
    DataSourceHealth,
    FallbackStep,
    Freshness,
    MarketDataResponse,
)


class FakeAdapter(BaseMarketDataAdapter):
    adapter_id = "fake"
    provider_name = "fake"
    label = "Fake Adapter"
    priority = 1
    capabilities = {AdapterCapability.REALTIME_QUOTE}

    async def fetch_realtime_quote(self, symbol: str) -> MarketDataResponse:
        return MarketDataResponse(
            symbol=symbol,
            source="fake",
            provider="fake",
            freshness=Freshness.REALTIME,
            confidence=0.9,
            data_mode=DataMode.LIVE,
        )

    async def fetch_historical_quote(self, symbol: str, start: str, end: str):
        return []

    async def fetch_auxiliary(self, symbol: str, category: str):
        return AuxiliaryDataResponse(category=category)

    async def health_check(self) -> DataSourceHealth:
        return DataSourceHealth(
            adapter_id=self.adapter_id,
            provider=self.provider_name,
            label=self.label,
            capabilities=list(self.capabilities),
            healthy=True,
            installed=True,
        )


class FailingAdapter(BaseMarketDataAdapter):
    adapter_id = "failing"
    provider_name = "failing"
    label = "Failing Adapter"
    priority = 1
    capabilities = {AdapterCapability.REALTIME_QUOTE}

    async def fetch_realtime_quote(self, symbol: str) -> MarketDataResponse:
        raise RuntimeError("always fails")

    async def fetch_historical_quote(self, symbol: str, start: str, end: str):
        return []

    async def fetch_auxiliary(self, symbol: str, category: str):
        return AuxiliaryDataResponse(category=category)

    async def health_check(self) -> DataSourceHealth:
        return DataSourceHealth(
            adapter_id=self.adapter_id,
            provider=self.provider_name,
            healthy=False,
            message="always fails",
            installed=True,
        )


class SlowAdapter(BaseMarketDataAdapter):
    adapter_id = "slow"
    provider_name = "slow"
    label = "Slow Adapter"
    priority = 0
    capabilities = {AdapterCapability.REALTIME_QUOTE}
    timeout_seconds = 1

    async def fetch_realtime_quote(self, symbol: str) -> MarketDataResponse:
        await asyncio.sleep(2)
        return MarketDataResponse(symbol=symbol)

    async def fetch_historical_quote(self, symbol: str, start: str, end: str):
        return []

    async def fetch_auxiliary(self, symbol: str, category: str):
        return AuxiliaryDataResponse(category=category)

    async def health_check(self) -> DataSourceHealth:
        return DataSourceHealth(
            adapter_id=self.adapter_id,
            provider=self.provider_name,
            healthy=True,
            installed=True,
        )


class SlowHealthAdapter(BaseMarketDataAdapter):
    adapter_id = "slow_health"
    provider_name = "slow_health"
    label = "Slow Health Adapter"
    priority = 1
    capabilities = {AdapterCapability.REALTIME_QUOTE}
    timeout_seconds = 0.01

    async def fetch_realtime_quote(self, symbol: str) -> MarketDataResponse:
        return MarketDataResponse(symbol=symbol)

    async def fetch_historical_quote(self, symbol: str, start: str, end: str):
        return []

    async def fetch_auxiliary(self, symbol: str, category: str):
        return AuxiliaryDataResponse(category=category)

    async def health_check(self) -> DataSourceHealth:
        await asyncio.sleep(1)
        return DataSourceHealth(adapter_id=self.adapter_id, provider=self.provider_name, healthy=True)


class MultiCapabilityHealthAdapter(BaseMarketDataAdapter):
    adapter_id = "multi_health"
    provider_name = "multi_health"
    label = "Multi Health Adapter"
    priority = 1
    capabilities = {
        AdapterCapability.REALTIME_QUOTE,
        AdapterCapability.FUNDAMENTALS,
        AdapterCapability.MONEYFLOW,
    }

    def __init__(self):
        self.health_calls = 0

    async def fetch_realtime_quote(self, symbol: str) -> MarketDataResponse:
        return MarketDataResponse(symbol=symbol)

    async def fetch_historical_quote(self, symbol: str, start: str, end: str):
        return []

    async def fetch_auxiliary(self, symbol: str, category: str):
        return AuxiliaryDataResponse(category=category)

    async def health_check(self) -> DataSourceHealth:
        self.health_calls += 1
        return DataSourceHealth(adapter_id=self.adapter_id, provider=self.provider_name, healthy=True)


class UnconfiguredHealthAdapter(BaseMarketDataAdapter):
    adapter_id = "unconfigured"
    provider_name = "unconfigured"
    label = "Unconfigured Adapter"
    priority = 1
    capabilities = {AdapterCapability.REALTIME_QUOTE}

    async def fetch_realtime_quote(self, symbol: str) -> MarketDataResponse:
        return MarketDataResponse(symbol=symbol)

    async def fetch_historical_quote(self, symbol: str, start: str, end: str):
        return []

    async def fetch_auxiliary(self, symbol: str, category: str):
        return AuxiliaryDataResponse(category=category)

    async def health_check(self) -> DataSourceHealth:
        return DataSourceHealth(
            adapter_id=self.adapter_id,
            provider=self.provider_name,
            configured=False,
            healthy=False,
            message="gateway missing",
        )


class TestRegistryBasic:
    def setup_method(self):
        reset_adapter_registry()

    def test_singleton(self):
        r1 = get_adapter_registry()
        r2 = get_adapter_registry()
        assert r1 is r2

    def test_reset(self):
        r1 = get_adapter_registry()
        reset_adapter_registry()
        r2 = get_adapter_registry()
        assert r1 is not r2

    def test_register_and_get(self):
        registry = get_adapter_registry()
        adapter = FakeAdapter()
        registry.register(adapter)
        assert registry.get_adapter("fake") is adapter

    def test_unregister(self):
        registry = get_adapter_registry()
        adapter = FakeAdapter()
        registry.register(adapter)
        registry.unregister("fake")
        assert registry.get_adapter("fake") is None

    def test_unregister_nonexistent(self):
        registry = get_adapter_registry()
        registry.unregister("nonexistent")


def test_default_adapter_registration_applies_runtime_config(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_runtime_store, "STORAGE_FILE", tmp_path / "agent_runtime.json")
    monkeypatch.setattr(agent_runtime_store, "RUNS_DIR", tmp_path / "runs")
    reset_adapter_registry()

    agent_runtime_store.update_market_data_adapter_config(
        "akshare",
        UpdateMarketDataAdapterConfigRequest(
            enabled=False,
            priority=9,
            timeout_seconds=25,
        ),
    )

    registry = register_default_market_data_adapters()
    adapter = registry.get_adapter("akshare")

    assert adapter is not None
    assert adapter.enabled is False
    assert adapter.priority == 9
    assert adapter.timeout_seconds == 25
    assert registry.get_adapter("tencent_finance") is not None
    assert registry.get_adapter("tongdaxin") is not None
    assert registry.get_adapter("ifind") is not None


@pytest.mark.asyncio
async def test_health_check_preserves_adapter_unconfigured_state():
    registry = MarketDataAdapterRegistry()
    adapter = UnconfiguredHealthAdapter()
    registry.register(adapter)

    health = await registry.health_check_adapter("unconfigured")

    assert health is not None
    assert health.configured is False
    assert health.healthy is False
    assert health.message == "gateway missing"


class TestCapabilityFiltering:
    def setup_method(self):
        reset_adapter_registry()

    def test_get_by_capability_empty(self):
        registry = get_adapter_registry()
        result = registry.get_adapters_by_capability(AdapterCapability.REALTIME_QUOTE)
        assert result == []

    def test_get_by_capability_match(self):
        registry = get_adapter_registry()
        adapter = FakeAdapter()
        registry.register(adapter)
        result = registry.get_adapters_by_capability(AdapterCapability.REALTIME_QUOTE)
        assert len(result) == 1
        assert result[0].adapter_id == "fake"

    def test_get_by_capability_no_match(self):
        registry = get_adapter_registry()
        adapter = FakeAdapter()
        registry.register(adapter)
        result = registry.get_adapters_by_capability(AdapterCapability.CHIP)
        assert result == []

    def test_priority_sorting(self):
        registry = get_adapter_registry()

        class HighPriority(BaseMarketDataAdapter):
            adapter_id = "high"
            provider_name = "high"
            priority = 1
            capabilities = {AdapterCapability.REALTIME_QUOTE}
            async def fetch_realtime_quote(self, symbol): return MarketDataResponse(symbol=symbol)
            async def fetch_historical_quote(self, symbol, start, end): return []
            async def fetch_auxiliary(self, symbol, category): return AuxiliaryDataResponse(category=category)
            async def health_check(self): return DataSourceHealth(adapter_id="high", provider="high")

        class LowPriority(BaseMarketDataAdapter):
            adapter_id = "low"
            provider_name = "low"
            priority = 10
            capabilities = {AdapterCapability.REALTIME_QUOTE}
            async def fetch_realtime_quote(self, symbol): return MarketDataResponse(symbol=symbol)
            async def fetch_historical_quote(self, symbol, start, end): return []
            async def fetch_auxiliary(self, symbol, category): return AuxiliaryDataResponse(category=category)
            async def health_check(self): return DataSourceHealth(adapter_id="low", provider="low")

        registry.register(LowPriority())
        registry.register(HighPriority())
        result = registry.get_adapters_by_capability(AdapterCapability.REALTIME_QUOTE)
        assert result[0].adapter_id == "high"
        assert result[1].adapter_id == "low"

    def test_disabled_adapter_excluded(self):
        registry = get_adapter_registry()
        adapter = FakeAdapter()
        adapter.enabled = False
        registry.register(adapter)
        result = registry.get_adapters_by_capability(AdapterCapability.REALTIME_QUOTE)
        assert result == []


class TestRegistryListAndHealth:
    def setup_method(self):
        reset_adapter_registry()

    def test_list_adapters_empty(self):
        registry = get_adapter_registry()
        assert registry.list_adapters() == []

    def test_list_adapters(self):
        registry = get_adapter_registry()
        registry.register(FakeAdapter())
        health_list = registry.list_adapters()
        assert len(health_list) == 1
        assert health_list[0].adapter_id == "fake"
        assert health_list[0].label == "Fake Adapter"

    @pytest.mark.asyncio
    async def test_health_check_all(self):
        registry = get_adapter_registry()
        registry.register(FakeAdapter())
        results = await registry.health_check_all()
        assert len(results) == 1
        assert results[0].healthy is True

    @pytest.mark.asyncio
    async def test_health_check_all_with_failing(self):
        registry = get_adapter_registry()
        registry.register(FailingAdapter())
        results = await registry.health_check_all()
        assert len(results) == 1
        assert results[0].healthy is False
        public = results[0].to_public_dict()
        assert public["installed"] is True
        assert public["upstreamHealthy"] is False
        assert public["liveDataUsable"] is False
        assert public["lastError"] == "always fails"

    @pytest.mark.asyncio
    async def test_health_check_all_timeout_returns_unhealthy_result(self):
        registry = get_adapter_registry()
        registry.register(SlowHealthAdapter())
        results = await registry.health_check_all()
        assert len(results) == 1
        assert results[0].healthy is False
        assert results[0].last_error == "timeout after 0.01s"


class TestFallbackOrchestration:
    def setup_method(self):
        reset_adapter_registry()

    @pytest.mark.asyncio
    async def test_successful_fetch_no_fallback(self):
        registry = get_adapter_registry()
        registry.register(FakeAdapter())
        result = await registry.fetch_realtime_quote_with_fallback("600001")
        assert result.data_mode == DataMode.LIVE
        assert result.confidence == 0.9
        assert len(result.degradation_chain) == 1
        assert result.degradation_chain[0].success is True
        assert result.degradation_chain[0].adapter_id == "fake"

    @pytest.mark.asyncio
    async def test_all_fail_fallback_to_mock(self):
        registry = get_adapter_registry()
        registry.register(FailingAdapter())
        result = await registry.fetch_realtime_quote_with_fallback("600001", fallback_to_mock=True)
        assert result.data_mode == DataMode.FALLBACK
        assert result.provider == "mock"
        assert len(result.degradation_chain) == 1
        assert result.degradation_chain[0].success is False

    @pytest.mark.asyncio
    async def test_all_fail_no_fallback_to_mock(self):
        registry = get_adapter_registry()
        registry.register(FailingAdapter())
        result = await registry.fetch_realtime_quote_with_fallback("600001", fallback_to_mock=False)
        assert result.data_mode == DataMode.FALLBACK
        assert "All adapters failed" in result.error
        assert len(result.degradation_chain) == 1

    @pytest.mark.asyncio
    async def test_no_adapters_registered(self):
        registry = get_adapter_registry()
        result = await registry.fetch_realtime_quote_with_fallback("600001")
        assert result.data_mode == DataMode.MOCK
        assert "No adapter available" in result.error or result.provider == "mock"

    @pytest.mark.asyncio
    async def test_timeout_falls_to_next(self):
        registry = get_adapter_registry()
        registry.register(SlowAdapter())
        registry.register(FakeAdapter())
        result = await registry.fetch_realtime_quote_with_fallback("600001")
        assert result.data_mode == DataMode.LIVE
        assert len(result.degradation_chain) >= 2
        assert any(step.adapter_id == "slow" and not step.success for step in result.degradation_chain)

    @pytest.mark.asyncio
    async def test_chain_preserved_across_fallback(self):
        class ChainFailing(BaseMarketDataAdapter):
            adapter_id = "chain_a"
            provider_name = "chain_a"
            priority = 1
            capabilities = {AdapterCapability.REALTIME_QUOTE}
            async def fetch_realtime_quote(self, symbol): raise RuntimeError("A failed")
            async def fetch_historical_quote(self, symbol, start, end): return []
            async def fetch_auxiliary(self, symbol, category): return AuxiliaryDataResponse(category=category)
            async def health_check(self): return DataSourceHealth(adapter_id="chain_a", provider="chain_a")

        registry = get_adapter_registry()
        registry.register(ChainFailing())
        registry.register(FakeAdapter())
        result = await registry.fetch_realtime_quote_with_fallback("600001")
        assert len(result.degradation_chain) >= 2
        assert result.degradation_chain[0].success is False
        assert result.degradation_chain[0].adapter_id == "chain_a"
        assert result.degradation_chain[-1].success is True
        assert result.degradation_chain[-1].adapter_id == "fake"


class TestAuxiliaryFallback:
    def setup_method(self):
        reset_adapter_registry()

    @pytest.mark.asyncio
    async def test_unknown_category(self):
        registry = get_adapter_registry()
        result = await registry.fetch_auxiliary_with_fallback("600001", "unknown_cat")
        assert "Unknown auxiliary category" in result.error

    @pytest.mark.asyncio
    async def test_no_adapters_for_category(self):
        registry = get_adapter_registry()
        registry.register(FakeAdapter())
        result = await registry.fetch_auxiliary_with_fallback("600001", "fundamentals")
        assert result.data_mode == DataMode.MOCK
        assert result.provider == "mock"


class TestStatusMatrix:
    def setup_method(self):
        reset_adapter_registry()

    @pytest.mark.asyncio
    async def test_build_status_matrix(self):
        registry = get_adapter_registry()
        registry.register(FakeAdapter())
        matrix = await registry.build_status_matrix()
        assert matrix.generated_at != ""
        assert "realtime_quote" in matrix.categories
        assert matrix.categories["realtime_quote"]["fake"].healthy is True

    @pytest.mark.asyncio
    async def test_build_status_matrix_checks_multi_capability_adapter_once(self):
        registry = get_adapter_registry()
        adapter = MultiCapabilityHealthAdapter()
        registry.register(adapter)
        matrix = await registry.build_status_matrix()
        assert matrix.categories["realtime_quote"]["multi_health"].healthy is True
        assert matrix.categories["fundamentals"]["multi_health"].healthy is True
        assert matrix.categories["moneyflow"]["multi_health"].healthy is True
        assert adapter.health_calls == 1
