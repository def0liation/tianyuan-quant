"""验收清单 §28.3 – Tushare 适配器测试"""
import asyncio
import logging
import time

import pytest
from unittest.mock import patch, MagicMock

from app.core.adapters import tushare_adapter as tushare_adapter_module
from app.core.adapters.tushare_adapter import TushareAdapter
from app.models.agent_runtime import MarketDataProfile
from app.models.market_data import (
    AdapterCapability,
    DataMode,
    Freshness,
    MarketDataResponse,
    AuxiliaryDataResponse,
)


class TestTushareAdapterMetadata:
    def test_adapter_metadata(self):
        adapter = TushareAdapter()
        assert adapter.adapter_id == "tushare"
        assert adapter.provider_name == "tushare"
        assert adapter.priority == 1
        assert adapter.label == "Tushare (官方)"

    def test_capabilities(self):
        adapter = TushareAdapter()
        assert AdapterCapability.REALTIME_QUOTE in adapter.capabilities
        assert AdapterCapability.HISTORICAL_QUOTE in adapter.capabilities
        assert AdapterCapability.FUNDAMENTALS in adapter.capabilities
        assert AdapterCapability.ANNOUNCEMENTS in adapter.capabilities
        assert AdapterCapability.MONEYFLOW in adapter.capabilities
        assert AdapterCapability.CHIP in adapter.capabilities
        assert adapter.can_handle(AdapterCapability.REALTIME_QUOTE) is True
        assert adapter.can_handle(AdapterCapability.INDEX) is False


class TestTushareIsInstalled:
    def test_is_installed_when_available(self):
        with patch("importlib.util.find_spec", return_value=MagicMock()):
            adapter = TushareAdapter()
            assert adapter._is_installed() is True

    def test_is_installed_when_missing(self):
        with patch("importlib.util.find_spec", return_value=None):
            adapter = TushareAdapter()
            assert adapter._is_installed() is False


class TestTushareWithoutToken:
    def test_realtime_quote_returns_mock_when_no_api_key(self):
        import asyncio
        adapter = TushareAdapter()
        result = asyncio.run(adapter.fetch_realtime_quote("603663"))
        assert result.error == "Tushare token is missing"
        assert result.data_mode == DataMode.MOCK

    def test_auxiliary_returns_mock_when_no_api_key(self):
        import asyncio
        adapter = TushareAdapter()
        result = asyncio.run(adapter.fetch_auxiliary("603663", "fundamentals"))
        assert result.error == "Tushare token is missing"
        assert result.data_mode == DataMode.MOCK

    def test_historical_returns_empty_when_no_api_key(self):
        import asyncio
        adapter = TushareAdapter()
        result = asyncio.run(adapter.fetch_historical_quote("603663", "2025-01-01", "2025-01-10"))
        assert result == []

    def test_health_check_reports_missing_token(self):
        import asyncio
        adapter = TushareAdapter()
        health = asyncio.run(adapter.health_check())
        assert health.healthy is False
        assert health.message == "Token is missing"


class TestTushareHealthCheckIsolation:
    def test_sdk_health_check_uses_adapter_timeout_setting(self, monkeypatch):
        profile = MarketDataProfile(
            id="tushare-config-timeout",
            label="Tushare config timeout",
            provider="tushare",
            api_key="token",
            timeout_seconds=3,
        )
        adapter = TushareAdapter(profile=profile)
        adapter._sdk_available = True
        adapter.timeout_seconds = 40
        captured_timeouts = []
        real_wait_for = tushare_adapter_module.asyncio.wait_for

        async def capture_wait_for(awaitable, timeout):
            captured_timeouts.append(timeout)
            return await real_wait_for(awaitable, timeout=timeout)

        monkeypatch.setattr(tushare_adapter_module.asyncio, "wait_for", capture_wait_for)
        monkeypatch.setattr(adapter, "_sdk_health_check_sync", lambda ts_code: (True, "OK"))

        health = asyncio.run(adapter.health_check())

        assert health.healthy is True
        assert captured_timeouts == [40]

    def test_sdk_health_check_times_out_without_blocking_event_loop(self, monkeypatch):
        profile = MarketDataProfile(
            id="tushare-timeout",
            label="Tushare timeout",
            provider="tushare",
            api_key="token",
            timeout_seconds=60,
        )
        adapter = TushareAdapter(profile=profile)
        adapter._sdk_available = True

        class SlowFrame:
            def to_dict(self, orient):
                assert orient == "records"
                return [{"price": 1}]

        class SlowTushare:
            def set_token(self, token):
                assert token == "token"

            def realtime_quote(self, ts_code, src):
                time.sleep(0.2)
                return SlowFrame()

        monkeypatch.setattr(tushare_adapter_module, "TUSHARE_HEALTH_CHECK_TIMEOUT_SECONDS", 0.01)
        monkeypatch.setattr(tushare_adapter_module.importlib, "import_module", lambda name: SlowTushare())

        health = asyncio.run(adapter.health_check())

        assert health.healthy is False
        assert health.upstream_healthy is False
        assert health.live_data_usable is False
        assert "timed out" in health.last_error

    def test_sdk_health_check_exception_uses_sina_fallback(self, monkeypatch):
        profile = MarketDataProfile(
            id="tushare-error",
            label="Tushare error",
            provider="tushare",
            api_key="token",
            timeout_seconds=3,
        )
        adapter = TushareAdapter(profile=profile)
        adapter._sdk_available = True

        class FailingTushare:
            def set_token(self, token):
                assert token == "token"

            def realtime_quote(self, ts_code, src):
                raise RuntimeError("upstream unavailable")

        monkeypatch.setattr(tushare_adapter_module.importlib, "import_module", lambda name: FailingTushare())
        monkeypatch.setattr(adapter, "_sina_health_check_sync", lambda timeout_seconds: None)

        health = asyncio.run(adapter.health_check())

        assert health.healthy is True
        assert health.upstream_healthy is True
        assert health.live_data_usable is True
        assert health.fallback_used is True
        assert health.last_error == "upstream unavailable"
        assert "已自动回退到 Sina 实时行情" in health.message

    def test_sdk_health_check_exception_returns_unhealthy_when_fallback_fails(self, monkeypatch):
        profile = MarketDataProfile(
            id="tushare-error",
            label="Tushare error",
            provider="tushare",
            api_key="token",
            timeout_seconds=3,
        )
        adapter = TushareAdapter(profile=profile)
        adapter._sdk_available = True

        class FailingTushare:
            def set_token(self, token):
                assert token == "token"

            def realtime_quote(self, ts_code, src):
                raise RuntimeError("upstream unavailable")

        monkeypatch.setattr(tushare_adapter_module.importlib, "import_module", lambda name: FailingTushare())
        monkeypatch.setattr(
            adapter,
            "_sina_health_check_sync",
            lambda timeout_seconds: (_ for _ in ()).throw(RuntimeError("sina unavailable")),
        )

        health = asyncio.run(adapter.health_check())

        assert health.healthy is False
        assert health.upstream_healthy is False
        assert health.live_data_usable is False
        assert health.fallback_used is False
        assert health.last_error == (
            "Tushare SDK realtime unavailable: upstream unavailable; "
            "Sina fallback unavailable: sina unavailable"
        )
        assert health.message.startswith("Tushare 实时行情主源和 Sina 降级源均不可用")


class TestTushareSdkFallback:
    def test_sdk_failure_falls_back_to_sina_without_traceback(self, monkeypatch, caplog):
        profile = MarketDataProfile(
            id="tushare-test",
            label="Tushare test",
            provider="tushare",
            api_key="token",
            timeout_seconds=3,
            extra_query_params={"src": "dc"},
        )
        adapter = TushareAdapter(profile=profile)
        adapter._sdk_available = True

        async def fail_sdk(ts_code: str, src: str):
            raise RuntimeError("Expecting value: line 1 column 1 (char 0)")

        async def fallback(ts_code: str, src: str):
            return MarketDataResponse(
                symbol=ts_code,
                source="tushare_compatible_sina",
                provider="sina",
                freshness=Freshness.REALTIME,
                confidence=0.7,
                data_mode=DataMode.FALLBACK,
            )

        monkeypatch.setattr(adapter, "_sdk_realtime_quote", fail_sdk)
        monkeypatch.setattr(adapter, "_sina_fallback", fallback)
        caplog.set_level(logging.WARNING, logger="app.core.adapters.tushare_adapter")

        result = asyncio.run(adapter.fetch_realtime_quote("603663"))

        assert result.provider == "sina"
        assert result.data_mode == DataMode.FALLBACK
        assert any("falling back to Sina" in record.message for record in caplog.records)
        assert not any(record.levelno >= logging.ERROR for record in caplog.records)
        assert not any(record.exc_info for record in caplog.records)


class TestTushareSymbolNormalization:
    def test_shanghai_code_returns_sh_suffix(self):
        from app.core.adapters.tushare_adapter import _normalize_tushare_symbol
        assert _normalize_tushare_symbol("603663") == "603663.SH"

    def test_shenzhen_code_returns_sz_suffix(self):
        from app.core.adapters.tushare_adapter import _normalize_tushare_symbol
        assert _normalize_tushare_symbol("000001") == "000001.SZ"

    def test_preserves_existing_suffix(self):
        from app.core.adapters.tushare_adapter import _normalize_tushare_symbol
        assert _normalize_tushare_symbol("603663.SH") == "603663.SH"

    def test_handles_underscore_separator(self):
        from app.core.adapters.tushare_adapter import _normalize_tushare_symbol
        assert _normalize_tushare_symbol("603663_SH") == "603663.SH"

    def test_sina_symbol_conversion(self):
        from app.core.adapters.tushare_adapter import _tushare_to_sina_symbol
        assert _tushare_to_sina_symbol("603663.SH") == "sh603663"
        assert _tushare_to_sina_symbol("000001.SZ") == "sz000001"


class TestTushareDataCoercion:
    def test_coerce_valid_float(self):
        from app.core.adapters.tushare_adapter import _coerce_number
        assert _coerce_number("12.34") == 12.34

    def test_coerce_integer(self):
        from app.core.adapters.tushare_adapter import _coerce_number
        assert _coerce_number(42) == 42.0

    def test_coerce_none_returns_none(self):
        from app.core.adapters.tushare_adapter import _coerce_number
        assert _coerce_number(None) is None

    def test_coerce_nan_returns_none(self):
        from app.core.adapters.tushare_adapter import _coerce_number
        assert _coerce_number(float("nan")) is None

    def test_coerce_empty_string_returns_none(self):
        from app.core.adapters.tushare_adapter import _coerce_number
        assert _coerce_number("") is None

    def test_coerce_string_with_comma(self):
        from app.core.adapters.tushare_adapter import _coerce_number
        assert _coerce_number("1,234.56") == 1234.56

    def test_coerce_percentage_string(self):
        from app.core.adapters.tushare_adapter import _coerce_number
        assert _coerce_number("3.14%") == 3.14


class TestTusharePayloadParsing:
    def test_empty_payload_returns_empty_list(self):
        from app.core.adapters.tushare_adapter import _tushare_records_from_payload
        assert _tushare_records_from_payload({}) == []

    def test_payload_with_records_field(self):
        from app.core.adapters.tushare_adapter import _tushare_records_from_payload
        payload = {"records": [{"a": 1}, {"b": 2}]}
        result = _tushare_records_from_payload(payload)
        assert len(result) == 2
        assert result[0] == {"a": 1}

    def test_payload_with_fields_and_items(self):
        from app.core.adapters.tushare_adapter import _tushare_records_from_payload
        payload = {
            "data": {
                "fields": ["close", "name"],
                "items": [[12.34, "测试"], [56.78, "名称"]],
            }
        }
        result = _tushare_records_from_payload(payload)
        assert len(result) == 2
        assert result[0]["close"] == 12.34
        assert result[1]["name"] == "名称"


class TestTushareSinaFallback:
    @patch("app.core.adapters.tushare_adapter.urlopen")
    def test_sina_fallback_parses_quote(self, mock_urlopen):
        from app.core.adapters.tushare_adapter import _call_tushare_realtime_quote_sina_sync

        raw = (
            'var hq_str_sh603663="三祥新材,11.50,11.80,12.34,12.50,11.20,'
            '11.80,11.90,12345678,15000000,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,'
            '2025-01-01,15:00:00,00,";'
        ).encode("gb18030")
        mock_urlopen.return_value.__enter__.return_value.read.return_value = raw

        result = _call_tushare_realtime_quote_sina_sync("603663.SH", "dc", 10)
        assert result.price == 12.34
        assert result.change_percent is not None
        assert result.volume == 12345678
        assert result.freshness == Freshness.REALTIME
        assert result.data_mode == DataMode.FALLBACK
        assert result.provider == "sina"

    @patch("app.core.adapters.tushare_adapter.urlopen")
    def test_sina_fallback_malformed_response_raises(self, mock_urlopen):
        from app.core.adapters.tushare_adapter import _call_tushare_realtime_quote_sina_sync

        mock_urlopen.return_value.__enter__.return_value.read.return_value = b"garbage"
        with pytest.raises(RuntimeError):
            _call_tushare_realtime_quote_sina_sync("603663.SH", "dc", 5)
