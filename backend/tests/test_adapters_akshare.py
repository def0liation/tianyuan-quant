"""Acceptance tests for the AkShare adapter."""
import asyncio
from unittest.mock import MagicMock, patch

from app.core.adapters.akshare_adapter import AkShareAdapter
from app.models.market_data import (
    AdapterCapability,
    AuxiliaryDataResponse,
    DataMode,
    MarketDataResponse,
)


class TestAkShareAdapterMetadata:
    def test_adapter_metadata(self):
        adapter = AkShareAdapter()
        assert adapter.adapter_id == "akshare"
        assert adapter.provider_name == "akshare"
        assert adapter.priority == 2
        assert adapter.label == "AkShare (东方财富)"

    def test_capabilities(self):
        adapter = AkShareAdapter()
        assert AdapterCapability.REALTIME_QUOTE not in adapter.capabilities
        assert AdapterCapability.HISTORICAL_QUOTE in adapter.capabilities
        assert AdapterCapability.FUNDAMENTALS in adapter.capabilities
        assert AdapterCapability.MONEYFLOW in adapter.capabilities
        assert AdapterCapability.CHIP not in adapter.capabilities
        assert adapter.can_handle(AdapterCapability.REALTIME_QUOTE) is False
        assert adapter.can_handle(AdapterCapability.HISTORICAL_QUOTE) is True


class TestAkShareIsInstalled:
    def test_is_installed_when_available(self):
        with patch("importlib.util.find_spec", return_value=MagicMock()):
            adapter = AkShareAdapter()
            assert adapter._is_installed() is True

    def test_is_installed_when_missing(self):
        with patch("importlib.util.find_spec", return_value=None):
            adapter = AkShareAdapter()
            assert adapter._is_installed() is False


class TestAkShareNotInstalled:
    def test_realtime_quote_returns_mock_when_not_installed(self):
        with patch("importlib.util.find_spec", return_value=None):
            adapter = AkShareAdapter()
            result = asyncio.run(adapter.fetch_realtime_quote("603663"))
        assert result.error == "akshare package is not installed"
        assert result.data_mode == DataMode.MOCK

    def test_auxiliary_returns_mock_when_not_installed(self):
        with patch("importlib.util.find_spec", return_value=None):
            adapter = AkShareAdapter()
            result = asyncio.run(adapter.fetch_auxiliary("603663", "fundamentals"))
        assert result.error == "akshare package is not installed"
        assert result.data_mode == DataMode.MOCK

    def test_health_check_reports_not_installed(self):
        with patch("importlib.util.find_spec", return_value=None):
            adapter = AkShareAdapter()
            health = asyncio.run(adapter.health_check())
        assert health.healthy is False
        assert health.installed is False
        assert "not installed" in health.message.lower()

    def test_historical_returns_empty_when_not_installed(self):
        with patch("importlib.util.find_spec", return_value=None):
            adapter = AkShareAdapter()
            result = asyncio.run(adapter.fetch_historical_quote("603663", "2025-01-01", "2025-01-10"))
        assert result == []


class TestAkShareSymbolNormalization:
    def test_extracts_six_digit_code(self):
        from app.core.adapters.akshare_adapter import _akshare_code

        assert _akshare_code("603663") == "603663"
        assert _akshare_code("sh603663") == "603663"
        assert _akshare_code("603663.SH") == "603663"

    def test_handles_short_code(self):
        from app.core.adapters.akshare_adapter import _akshare_code

        assert _akshare_code("100") == "100"


class TestAkShareAuxiliaryUnsupported:
    def test_unsupported_category_returns_error(self):
        adapter = AkShareAdapter()
        adapter._installed = True
        result = asyncio.run(adapter.fetch_auxiliary("603663", "unknown_category"))
        assert "does not support" in result.error.lower()
        assert result.data_mode == DataMode.MOCK

    def test_chip_category_returns_mock_not_supported(self):
        adapter = AkShareAdapter()
        adapter._installed = True
        result = asyncio.run(adapter.fetch_auxiliary("603663", "chip"))
        assert "does not support" in result.error.lower()
        assert result.data_mode == DataMode.MOCK


class TestAkShareRuntimeProbes:
    def test_health_check_reports_available_when_history_and_moneyflow_work(self):
        adapter = AkShareAdapter()
        adapter._installed = True

        def ok_history(code, start, end):
            return [
                MarketDataResponse(
                    symbol=code,
                    price=45.73,
                    source="akshare_eastmoney_hist",
                    provider="akshare",
                    data_mode=DataMode.LIVE,
                )
            ]

        def ok_moneyflow(code):
            return AuxiliaryDataResponse(
                category="moneyflow",
                provider="akshare",
                data_mode=DataMode.LIVE,
                records=[{"date": "2026-05-20"}],
                record_count=1,
            )

        adapter._fetch_historical_sync = ok_history
        adapter._fetch_moneyflow_sync = ok_moneyflow

        health = asyncio.run(adapter.health_check())

        assert health.healthy is True
        assert health.upstream_healthy is True
        assert health.live_data_usable is False
        assert "可用" in health.message
        assert "push2" in health.message
        assert health.last_error == ""

    def test_health_check_reports_probe_failures_without_raising(self):
        adapter = AkShareAdapter()
        adapter._installed = True

        def timeout_history(code, start, end):
            raise TimeoutError("history timed out")

        def failing_moneyflow(code):
            raise RuntimeError("moneyflow unavailable")

        adapter._fetch_historical_sync = timeout_history
        adapter._fetch_moneyflow_sync = failing_moneyflow

        health = asyncio.run(adapter.health_check())

        assert health.healthy is False
        assert health.upstream_healthy is False
        assert health.live_data_usable is False
        assert "history timed out" in health.last_error
        assert "moneyflow unavailable" in health.last_error

    def test_fetch_historical_sync_maps_rows(self):
        adapter = AkShareAdapter()

        class FakeDataFrame:
            def to_dict(self, orient):
                assert orient == "records"
                return [
                    {
                        "日期": "2026-05-20",
                        "股票代码": "603663",
                        "开盘": 41.30,
                        "收盘": 45.73,
                        "最高": 45.73,
                        "最低": 40.96,
                        "成交量": 179355,
                        "成交额": 787861151.0,
                        "振幅": 11.47,
                        "涨跌幅": 10.01,
                        "涨跌额": 4.16,
                        "换手率": 4.24,
                    }
                ]

        with patch("akshare.stock_zh_a_hist", return_value=FakeDataFrame()) as stock_hist:
            results = adapter._fetch_historical_sync("603663", "2026-05-01", "2026-05-20")

        assert len(results) == 1
        result = results[0]
        assert result.data_mode == DataMode.LIVE
        assert result.source == "akshare_eastmoney_hist"
        assert result.symbol == "603663"
        assert result.price == 45.73
        assert result.change_percent == 10.01
        stock_hist.assert_called_once()
        assert stock_hist.call_args.kwargs["start_date"] == "20260501"
        assert stock_hist.call_args.kwargs["end_date"] == "20260520"
        assert stock_hist.call_args.kwargs["timeout"] == adapter.timeout_seconds

    def test_fetch_historical_sync_retries_transient_disconnect(self):
        adapter = AkShareAdapter()

        class FakeDataFrame:
            def to_dict(self, orient):
                assert orient == "records"
                return [{"timestamp": "2026-05-20"}]

        with patch(
            "akshare.stock_zh_a_hist",
            side_effect=[ConnectionError("remote disconnected"), FakeDataFrame()],
        ) as stock_hist:
            results = adapter._fetch_historical_sync("603663", "2026-05-01", "2026-05-20")

        assert len(results) == 1
        assert results[0].symbol == "603663"
        assert results[0].source == "akshare_eastmoney_hist"
        assert stock_hist.call_count == 2
        assert stock_hist.call_args.kwargs["timeout"] == adapter.timeout_seconds
