import pytest

from app.core.market_data_adapter import BaseMarketDataAdapter, MarketDataAdapterRegistry
from app.models.market_data import (
    AdapterCapability,
    AuxiliaryDataResponse,
    DataMode,
    DataSourceHealth,
    Freshness,
    MarketDataResponse,
)


def _hist_row(symbol: str, provider: str, price: float, volume: float, timestamp: str) -> MarketDataResponse:
    return MarketDataResponse(
        symbol=symbol,
        price=price,
        volume=volume,
        timestamp=timestamp,
        source=f"{provider}_test",
        provider=provider,
        freshness=Freshness.EOD,
        confidence=0.88,
        data_mode=DataMode.LIVE,
    )


class HistoricalAdapter(BaseMarketDataAdapter):
    capabilities = {AdapterCapability.HISTORICAL_QUOTE}

    def __init__(self, adapter_id: str, provider: str, priority: int, rows: list[MarketDataResponse]):
        self.adapter_id = adapter_id
        self.provider_name = provider
        self.priority = priority
        self.rows = rows

    async def fetch_realtime_quote(self, symbol: str) -> MarketDataResponse:
        return MarketDataResponse(symbol=symbol, error="unsupported")

    async def fetch_historical_quote(self, symbol: str, start: str, end: str):
        return self.rows

    async def fetch_auxiliary(self, symbol: str, category: str):
        return AuxiliaryDataResponse(category=category, error="unsupported")

    async def health_check(self):
        return DataSourceHealth(adapter_id=self.adapter_id, provider=self.provider_name, healthy=True)


class MoneyflowAdapter(BaseMarketDataAdapter):
    capabilities = {AdapterCapability.MONEYFLOW}

    def __init__(self, adapter_id: str, provider: str, priority: int, record_count: int):
        self.adapter_id = adapter_id
        self.provider_name = provider
        self.priority = priority
        self.record_count = record_count

    async def fetch_realtime_quote(self, symbol: str) -> MarketDataResponse:
        return MarketDataResponse(symbol=symbol, error="unsupported")

    async def fetch_historical_quote(self, symbol: str, start: str, end: str):
        return []

    async def fetch_auxiliary(self, symbol: str, category: str):
        return AuxiliaryDataResponse(
            category=category,
            source=f"{self.provider_name}_test",
            provider=self.provider_name,
            freshness=Freshness.EOD,
            confidence=0.88,
            data_mode=DataMode.LIVE,
            records=[{"idx": idx} for idx in range(self.record_count)],
            record_count=self.record_count,
        )

    async def health_check(self):
        return DataSourceHealth(adapter_id=self.adapter_id, provider=self.provider_name, healthy=True)


@pytest.mark.asyncio
async def test_historical_arbitration_marks_price_conflict_review_only():
    registry = MarketDataAdapterRegistry()
    registry.register(
        HistoricalAdapter(
            "tushare_hist",
            "tushare",
            1,
            [_hist_row("603663", "tushare", 10.0, 1000, "20260520")],
        )
    )
    registry.register(
        HistoricalAdapter(
            "akshare_hist",
            "akshare",
            2,
            [_hist_row("603663", "akshare", 12.0, 1000, "2026-05-20")],
        )
    )

    rows = await registry.fetch_historical_quote_with_fallback(
        "603663", "2026-05-20", "2026-05-20", fallback_to_mock=False
    )

    assert rows
    assert rows[0].provider == "tushare"
    arbitration = rows[0].extra["arbitration"]
    assert arbitration["selectedSource"] == "tushare"
    assert arbitration["sourceConsensus"] == "DIVERGED"
    assert arbitration["dataQuality"]["reviewOnly"] is True
    assert any(conflict["field"] == "close" for conflict in arbitration["conflicts"])


@pytest.mark.asyncio
async def test_historical_arbitration_sorts_selected_rows_by_date():
    registry = MarketDataAdapterRegistry()
    registry.register(
        HistoricalAdapter(
            "tushare_hist",
            "tushare",
            1,
            [
                _hist_row("603663", "tushare", 11.0, 1000, "20260521"),
                _hist_row("603663", "tushare", 10.0, 1000, "20260520"),
            ],
        )
    )

    rows = await registry.fetch_historical_quote_with_fallback(
        "603663", "2026-05-20", "2026-05-21", fallback_to_mock=False
    )

    assert [row.timestamp for row in rows] == ["20260520", "20260521"]
    arbitration = rows[0].extra["arbitration"]
    assert arbitration["checkedSources"][0]["firstTimestamp"] == "20260520"
    assert arbitration["checkedSources"][0]["lastTimestamp"] == "20260521"


@pytest.mark.asyncio
async def test_moneyflow_arbitration_prefers_akshare_over_adapter_priority():
    registry = MarketDataAdapterRegistry()
    registry.register(MoneyflowAdapter("tushare_moneyflow", "tushare", 1, 10))
    registry.register(MoneyflowAdapter("akshare_moneyflow", "akshare", 2, 11))

    result = await registry.fetch_auxiliary_with_fallback(
        "603663", "moneyflow", fallback_to_mock=False
    )

    assert result.provider == "akshare"
    arbitration = result.extra["arbitration"]
    assert arbitration["selectedSource"] == "akshare"
    assert arbitration["sourceConsensus"] == "CONSENSUS"
    assert arbitration["dataQuality"]["reviewOnly"] is False
    assert [source["source"] for source in arbitration["checkedSources"]] == ["tushare", "akshare"]
