import asyncio

from app.core.adapters import tencent_finance_adapter as tencent_finance_adapter_module
from app.core.adapters.ifind_adapter import IFindAdapter
from app.core.adapters.tencent_finance_adapter import TencentFinanceAdapter
from app.core.adapters.tongdaxin_adapter import TongdaxinAdapter
from app.models.market_data import AdapterCapability, DataMode, Freshness, MarketDataResponse


def _clear_env(monkeypatch, prefix: str) -> None:
    for suffix in (
        "BASE_URL",
        "API_KEY",
        "TOKEN",
        "QUOTE_PATH",
        "HISTORICAL_PATH",
        "AUXILIARY_PATH",
        "HEALTH_PATH",
    ):
        monkeypatch.delenv(f"{prefix}_{suffix}", raising=False)


class TestTencentFinanceAdapter:
    def test_metadata_and_capabilities(self):
        adapter = TencentFinanceAdapter()

        assert adapter.adapter_id == "tencent_finance"
        assert adapter.provider_name == "tencent_finance"
        assert adapter.label == "腾讯财经"
        assert adapter.requires_token is False
        assert AdapterCapability.REALTIME_QUOTE in adapter.capabilities
        assert AdapterCapability.INDEX in adapter.capabilities

    def test_missing_gateway_uses_public_realtime_quote(self, monkeypatch):
        _clear_env(monkeypatch, "TENCENT_FINANCE")
        adapter = TencentFinanceAdapter()

        def fake_public_quote(symbol, timeout_seconds):
            assert symbol == "603663"
            assert timeout_seconds == adapter.timeout_seconds
            return MarketDataResponse(
                symbol="603663",
                name="样本科技",
                price=12.34,
                source="tencent_public_quote",
                provider="tencent_finance",
                freshness=Freshness.REALTIME,
                data_mode=DataMode.LIVE,
            )

        monkeypatch.setattr(tencent_finance_adapter_module, "_fetch_tencent_public_quote_sync", fake_public_quote)

        health = asyncio.run(adapter.health_check())
        quote = asyncio.run(adapter.fetch_realtime_quote("603663"))

        assert health.configured is True
        assert health.healthy is True
        assert health.live_data_usable is True
        assert health.fallback_used is True
        assert "腾讯公开实时行情可用" in health.message
        assert quote.data_mode == DataMode.LIVE
        assert quote.source == "tencent_public_quote"
        assert quote.price == 12.34

    def test_public_quote_parser_converts_tencent_text_payload(self):
        fields = [""] * 38
        fields[1] = "样本科技"
        fields[2] = "603663"
        fields[3] = "12.34"
        fields[4] = "12.00"
        fields[5] = "12.10"
        fields[6] = "123456"
        fields[30] = "20260604100000"
        fields[31] = "0.34"
        fields[32] = "2.83"
        fields[33] = "12.50"
        fields[34] = "11.90"
        fields[37] = "12345678"
        raw = f'v_sh603663="{"~".join(fields)}";'

        result = tencent_finance_adapter_module._parse_tencent_public_quote(raw, "603663", "sh603663")

        assert result.data_mode == DataMode.LIVE
        assert result.source == "tencent_public_quote"
        assert result.provider == "tencent_finance"
        assert result.symbol == "603663"
        assert result.name == "样本科技"
        assert result.price == 12.34
        assert result.change_percent == 2.83
        assert result.volume == 123456
        assert result.timestamp == "2026-06-04 10:00:00"
        assert result.extra["preClose"] == 12.0
        assert result.extra["sourcePage"] == "https://stockapp.finance.qq.com/mstats/"

    def test_realtime_quote_uses_authorized_gateway_payload(self, monkeypatch):
        monkeypatch.setenv("TENCENT_FINANCE_BASE_URL", "https://gateway.example.test/tencent")
        adapter = TencentFinanceAdapter()

        def fake_request(operation, params):
            assert operation == "QUOTE"
            assert params["symbol"] == "603663"
            return {
                "data": {
                    "symbol": "603663",
                    "name": "样本科技",
                    "price": "12.34",
                    "changePercent": "1.2",
                    "volume": "123456",
                    "timestamp": "2026-06-04 10:00:00",
                },
                "freshness": "REALTIME",
            }

        adapter._request_json = fake_request

        result = asyncio.run(adapter.fetch_realtime_quote("603663"))

        assert result.data_mode == DataMode.LIVE
        assert result.provider == "tencent_finance"
        assert result.source == "tencent_finance_authorized_rest"
        assert result.price == 12.34
        assert result.change_percent == 1.2


class TestTongdaxinAdapter:
    def test_requires_authorized_token(self, monkeypatch):
        _clear_env(monkeypatch, "TONGDAXIN")
        monkeypatch.setenv("TONGDAXIN_BASE_URL", "https://gateway.example.test/tdx")
        adapter = TongdaxinAdapter()

        health = asyncio.run(adapter.health_check())

        assert health.configured is False
        assert health.healthy is False
        assert "TONGDAXIN_API_KEY" in health.message

    def test_health_check_passes_with_authorized_gateway(self, monkeypatch):
        monkeypatch.setenv("TONGDAXIN_BASE_URL", "https://gateway.example.test/tdx")
        monkeypatch.setenv("TONGDAXIN_TOKEN", "tdx-test-token")
        adapter = TongdaxinAdapter()

        def fake_request(operation, params):
            assert operation == "HEALTH"
            assert params["symbol"] == "603663"
            return {"healthy": True, "status": "READY"}

        adapter._request_json = fake_request

        health = asyncio.run(adapter.health_check())

        assert health.configured is True
        assert health.healthy is True
        assert health.live_data_usable is True


class TestIFindAdapter:
    def test_metadata_declares_full_coverage_capabilities(self):
        adapter = IFindAdapter()

        assert adapter.adapter_id == "ifind"
        assert adapter.label == "同花顺 iFinD"
        assert AdapterCapability.REALTIME_QUOTE in adapter.capabilities
        assert AdapterCapability.FUNDAMENTALS in adapter.capabilities
        assert AdapterCapability.MACRO in adapter.capabilities
        assert AdapterCapability.INDEX in adapter.capabilities

    def test_auxiliary_records_use_authorized_gateway_payload(self, monkeypatch):
        monkeypatch.setenv("IFIND_BASE_URL", "https://gateway.example.test/ifind")
        monkeypatch.setenv("IFIND_API_KEY", "ifind-test-token")
        adapter = IFindAdapter()

        def fake_request(operation, params):
            assert operation == "AUXILIARY"
            assert params == {"symbol": "603663", "category": "fundamentals"}
            return {
                "records": [
                    {"report_date": "2026-03-31", "revenue": 100},
                    {"report_date": "2025-12-31", "revenue": 90},
                ],
                "freshness": "EOD",
                "confidence": 0.91,
            }

        adapter._request_json = fake_request

        result = asyncio.run(adapter.fetch_auxiliary("603663", "fundamentals"))

        assert result.data_mode == DataMode.LIVE
        assert result.provider == "ifind"
        assert result.source == "ifind_authorized_rest"
        assert result.record_count == 2
        assert result.confidence == 0.91
