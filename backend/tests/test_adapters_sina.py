"""验收清单 §28.4 – 新浪财经适配器测试"""
import pytest
from unittest.mock import patch, MagicMock

from app.core.adapters.sina_adapter import SinaAdapter, _to_sina_symbol, _coerce_number
from app.models.market_data import (
    AdapterCapability,
    DataMode,
    Freshness,
    MarketDataResponse,
)


class TestSinaSymbolConversion:
    def test_sh_stock(self):
        assert _to_sina_symbol("600001") == "sh600001"
        assert _to_sina_symbol("688001") == "sh688001"
        assert _to_sina_symbol("900901") == "sh900901"

    def test_sz_stock(self):
        assert _to_sina_symbol("000001") == "sz000001"
        assert _to_sina_symbol("002001") == "sz002001"
        assert _to_sina_symbol("300001") == "sz300001"

    def test_special_codes(self):
        assert _to_sina_symbol("603663") == "sh603663"

    def test_non_numeric(self):
        result = _to_sina_symbol("ABC")
        assert result == "abc"

    def test_strip_whitespace(self):
        assert _to_sina_symbol(" 600001 ") == "sh600001"

    def test_extra_chars(self):
        result = _to_sina_symbol("603663.XSHG")
        assert result == "sh603663"


class TestCoerceNumber:
    def test_int(self):
        assert _coerce_number(42) == 42.0

    def test_float(self):
        assert _coerce_number(3.14) == 3.14

    def test_str_int(self):
        assert _coerce_number("42") == 42.0

    def test_str_float(self):
        assert _coerce_number("15.68") == 15.68

    def test_str_with_comma(self):
        assert _coerce_number("1,234,567") == 1234567.0

    def test_str_with_percent(self):
        assert _coerce_number("3.5%") == 3.5

    def test_none(self):
        assert _coerce_number(None) is None

    def test_empty_str(self):
        assert _coerce_number("") is None

    def test_nan(self):
        import math
        assert _coerce_number(float('nan')) is None

    def test_invalid_str(self):
        assert _coerce_number("abc") is None


class TestSinaAdapterProperties:
    def test_adapter_metadata(self):
        adapter = SinaAdapter()
        assert adapter.adapter_id == "sina"
        assert adapter.provider_name == "sina"
        assert adapter.priority == 4
        assert adapter.label == "新浪财经"

    def test_capabilities(self):
        adapter = SinaAdapter()
        assert AdapterCapability.REALTIME_QUOTE in adapter.capabilities
        assert AdapterCapability.MONEYFLOW in adapter.capabilities
        assert adapter.can_handle(AdapterCapability.REALTIME_QUOTE) is True
        assert adapter.can_handle(AdapterCapability.CHIP) is False

    def test_is_installed(self):
        adapter = SinaAdapter()
        assert adapter._is_installed() is True


class TestSinaFetchSync:
    def test_successful_parse(self):
        adapter = SinaAdapter()
        raw_line = '测试股="测试科技,15.50,15.30,15.68,15.70,15.20,15.68,15.69,12000000,185000000,0,15.68,15.60,100,15.58,50,15.57,80,15.55,120,15.68,80,15.69,100,2026-05-12,10:00:00,00,0,0,0,0,0,0";'

        with patch("app.core.adapters.sina_adapter.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = raw_line.encode("gb18030")
            mock_resp.__enter__.return_value = mock_resp
            mock_urlopen.return_value = mock_resp

            result = adapter._fetch_sync("https://hq.sinajs.cn/list=sh600001", "sh600001")

        assert result.symbol == "sh600001"
        assert result.name == "测试科技"
        assert result.price == 15.68
        assert result.change_percent is not None
        assert abs(result.change_percent - 2.48) < 0.1
        assert result.volume == 12000000
        assert result.freshness == Freshness.REALTIME
        assert result.confidence == 0.70
        assert result.data_mode == DataMode.LIVE
        assert result.timestamp is not None

    def test_unexpected_format(self):
        adapter = SinaAdapter()
        raw_line = '="";'

        with patch("app.core.adapters.sina_adapter.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = raw_line.encode("gb18030")
            mock_resp.__enter__.return_value = mock_resp
            mock_urlopen.return_value = mock_resp

            with pytest.raises(RuntimeError, match="no quote"):
                adapter._fetch_sync("https://hq.sinajs.cn/list=sh000000", "sh000000")

    def test_network_error(self):
        adapter = SinaAdapter()

        with patch("app.core.adapters.sina_adapter.urlopen", side_effect=OSError("Connection refused")):
            with pytest.raises(OSError, match="Connection refused"):
                adapter._fetch_sync("https://hq.sinajs.cn/list=sh600001", "sh600001")


class TestSinaAuxiliary:
    def test_unsupported_category(self):
        adapter = SinaAdapter()
        result = asyncio_sync(adapter.fetch_auxiliary("600001", "fundamentals"))
        assert result.data_mode == DataMode.MOCK
        assert "does not support" in result.error

    def test_historical_quote_returns_empty(self):
        adapter = SinaAdapter()
        result = asyncio_sync(adapter.fetch_historical_quote("600001", "2026-01-01", "2026-05-01"))
        assert result == []


def asyncio_sync(coro):
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, coro)
            return future.result(timeout=10)
    else:
        return asyncio.run(coro)
