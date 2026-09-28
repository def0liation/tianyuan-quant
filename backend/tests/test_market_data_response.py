"""验收清单 §28.1 – 统一响应模型测试"""
import pytest
from datetime import datetime, timezone
from app.models.market_data import (
    Freshness,
    DataMode,
    AdapterCapability,
    FallbackStep,
    MarketDataResponse,
    AuxiliaryDataResponse,
    DataSourceHealth,
    MarketDataStatusMatrix,
)


class TestFreshnessEnum:
    def test_freshness_values(self):
        assert Freshness.REALTIME.value == "REALTIME"
        assert Freshness.DELAYED_15MIN.value == "DELAYED_15MIN"
        assert Freshness.EOD.value == "EOD"
        assert Freshness.STALE.value == "STALE"
        assert Freshness.UNKNOWN.value == "UNKNOWN"

    def test_freshness_default(self):
        resp = MarketDataResponse(symbol="600001")
        assert resp.freshness == Freshness.UNKNOWN


class TestDataModeEnum:
    def test_data_mode_values(self):
        assert DataMode.LIVE.value == "LIVE"
        assert DataMode.MOCK.value == "MOCK"
        assert DataMode.MIXED.value == "MIXED"
        assert DataMode.FALLBACK.value == "FALLBACK"


class TestAdapterCapabilityEnum:
    def test_capabilities_exist(self):
        caps = {
            AdapterCapability.REALTIME_QUOTE,
            AdapterCapability.HISTORICAL_QUOTE,
            AdapterCapability.FUNDAMENTALS,
            AdapterCapability.ANNOUNCEMENTS,
            AdapterCapability.MONEYFLOW,
            AdapterCapability.CHIP,
            AdapterCapability.INDEX,
            AdapterCapability.BOND,
            AdapterCapability.FUTURES,
        }
        assert len(caps) == 9


class TestFallbackStep:
    def test_fallback_step_defaults(self):
        step = FallbackStep()
        assert step.adapter_id == ""
        assert step.provider == ""
        assert step.success is False
        assert step.latency_ms == 0

    def test_fallback_step_full(self):
        step = FallbackStep(
            adapter_id="tushare",
            provider="tushare",
            attempt_at="2026-05-12T10:00:00Z",
            success=True,
            latency_ms=150,
        )
        assert step.adapter_id == "tushare"
        assert step.success is True
        assert step.latency_ms == 150
        assert step.error == ""

    def test_fallback_step_failure_with_error(self):
        step = FallbackStep(
            adapter_id="akshare",
            provider="akshare",
            attempt_at="2026-05-12T10:00:01Z",
            success=False,
            error="Connection refused",
            latency_ms=5000,
        )
        assert step.success is False
        assert "Connection refused" in step.error
        assert step.latency_ms == 5000


class TestMarketDataResponse:
    def test_minimal_creation(self):
        resp = MarketDataResponse(symbol="600001")
        assert resp.symbol == "600001"
        assert resp.name == ""
        assert resp.price is None
        assert resp.confidence == 0.0
        assert resp.data_mode == DataMode.MOCK
        assert resp.degradation_chain == []

    def test_full_creation(self):
        resp = MarketDataResponse(
            symbol="600001",
            name="测试股",
            price=15.68,
            change_percent=2.35,
            volume=12000000,
            source="tushare_http",
            provider="tushare",
            fetched_at="2026-05-12T10:00:00Z",
            freshness=Freshness.REALTIME,
            confidence=0.90,
            data_mode=DataMode.LIVE,
            degradation_chain=[
                FallbackStep(
                    adapter_id="tushare",
                    provider="tushare",
                    success=True,
                    latency_ms=120,
                )
            ],
        )
        assert resp.price == 15.68
        assert resp.change_percent == 2.35
        assert resp.confidence == 0.90
        assert resp.freshness == Freshness.REALTIME
        assert len(resp.degradation_chain) == 1

    def test_confidence_range_validation(self):
        with pytest.raises(Exception):
            MarketDataResponse(symbol="T", confidence=1.5)
        with pytest.raises(Exception):
            MarketDataResponse(symbol="T", confidence=-0.1)
        resp = MarketDataResponse(symbol="T", confidence=0.75)
        assert resp.confidence == 0.75

    def test_to_public_dict_camelcase_keys(self):
        resp = MarketDataResponse(
            symbol="600001",
            name="测试",
            price=10.5,
            change_percent=1.2,
            freshness=Freshness.REALTIME,
            confidence=0.85,
            data_mode=DataMode.LIVE,
            degradation_chain=[
                FallbackStep(
                    adapter_id="tushare",
                    provider="tushare",
                    success=True,
                    latency_ms=50,
                )
            ],
        )
        d = resp.to_public_dict()
        assert d["symbol"] == "600001"
        assert d["price"] == 10.5
        assert d["changePercent"] == 1.2
        assert d["freshness"] == "REALTIME"
        assert d["confidence"] == 0.85
        assert d["dataMode"] == "LIVE"
        assert len(d["degradationChain"]) == 1
        assert d["degradationChain"][0]["latencyMs"] == 50

    def test_to_public_dict_error_mode(self):
        resp = MarketDataResponse(
            symbol="600001",
            error="Network timeout",
            freshness=Freshness.UNKNOWN,
            confidence=0.0,
            data_mode=DataMode.MOCK,
        )
        d = resp.to_public_dict()
        assert d["error"] == "Network timeout"
        assert d["dataMode"] == "MOCK"
        assert d["confidence"] == 0.0


class TestAuxiliaryDataResponse:
    def test_default_creation(self):
        aux = AuxiliaryDataResponse(category="fundamentals")
        assert aux.category == "fundamentals"
        assert aux.records == []
        assert aux.record_count == 0
        assert aux.confidence == 0.0

    def test_full_creation(self):
        records = [{"pe": 15.2, "pb": 2.1}]
        aux = AuxiliaryDataResponse(
            category="fundamentals",
            source="tushare",
            provider="tushare",
            fetched_at="2026-05-12T10:00:00Z",
            freshness=Freshness.EOD,
            confidence=0.85,
            data_mode=DataMode.LIVE,
            records=records,
            record_count=1,
            degradation_chain=[
                FallbackStep(
                    adapter_id="tushare",
                    provider="tushare",
                    success=True,
                    latency_ms=200,
                )
            ],
        )
        assert aux.records == records
        assert aux.record_count == 1
        assert aux.confidence == 0.85
        assert aux.freshness == Freshness.EOD
        assert len(aux.degradation_chain) == 1

    def test_to_public_dict(self):
        aux = AuxiliaryDataResponse(
            category="moneyflow",
            source="sina",
            provider="sina",
            freshness=Freshness.DELAYED_15MIN,
            confidence=0.65,
            data_mode=DataMode.LIVE,
            records=[{"inflow": 100000}],
            record_count=1,
        )
        d = aux.to_public_dict()
        assert d["category"] == "moneyflow"
        assert d["recordCount"] == 1
        assert d["records"][0]["inflow"] == 100000
        assert d["freshness"] == "DELAYED_15MIN"


class TestDataSourceHealth:
    def test_default_health(self):
        h = DataSourceHealth(adapter_id="test", provider="test")
        assert h.adapter_id == "test"
        assert h.healthy is False
        assert h.installed is True
        assert h.enabled is True
        assert h.capabilities == []
        assert h.latency_avg_ms == 0

    def test_health_with_capabilities(self):
        h = DataSourceHealth(
            adapter_id="sina",
            provider="sina",
            label="新浪财经",
            capabilities=[AdapterCapability.REALTIME_QUOTE, AdapterCapability.MONEYFLOW],
            healthy=True,
            last_check_at="2026-05-12T10:00:00Z",
            latency_avg_ms=120,
            message="OK",
            enabled=True,
            installed=True,
        )
        assert h.healthy is True
        assert len(h.capabilities) == 2
        assert h.latency_avg_ms == 120
        assert h.label == "新浪财经"

    def test_to_public_dict(self):
        h = DataSourceHealth(
            adapter_id="sina",
            provider="sina",
            label="新浪",
            capabilities=[AdapterCapability.REALTIME_QUOTE],
            healthy=True,
            last_check_at="2026-05-12T10:00:00Z",
            latency_avg_ms=80,
            message="OK",
        )
        d = h.to_public_dict()
        assert d["adapterId"] == "sina"
        assert d["healthy"] is True
        assert d["latencyAvgMs"] == 80
        assert d["capabilities"] == ["REALTIME_QUOTE"]


class TestMarketDataStatusMatrix:
    def test_default_matrix(self):
        m = MarketDataStatusMatrix()
        assert m.categories == {}
        assert m.generated_at == ""

    def test_matrix_with_data(self):
        health = DataSourceHealth(
            adapter_id="tushare",
            provider="tushare",
            healthy=True,
            last_check_at="2026-05-12T10:00:00Z",
            latency_avg_ms=100,
        )
        m = MarketDataStatusMatrix(
            categories={"realtime_quote": {"tushare": health}},
            generated_at="2026-05-12T10:00:00Z",
        )
        assert "realtime_quote" in m.categories
        assert m.categories["realtime_quote"]["tushare"].healthy is True

    def test_to_public_dict(self):
        health = DataSourceHealth(
            adapter_id="sina",
            provider="sina",
            healthy=True,
            last_check_at="2026-05-12T10:00:00Z",
            latency_avg_ms=80,
        )
        m = MarketDataStatusMatrix(
            categories={"realtime_quote": {"sina": health}},
            generated_at="2026-05-12T10:00:00Z",
        )
        d = m.to_public_dict()
        assert d["generatedAt"] == "2026-05-12T10:00:00Z"
        assert d["categories"]["realtime_quote"]["sina"]["healthy"] is True
        assert d["categories"]["realtime_quote"]["sina"]["latencyAvgMs"] == 80
