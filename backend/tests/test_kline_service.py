from datetime import date

import httpx
import pytest

from app.api import routes_kline
from app.core import kline_service
from app.main import app
from app.models.agent_runtime import MarketDataProfile


class FixedDate(date):
    @classmethod
    def today(cls):
        return cls(2026, 5, 23)


def test_monthly_kline_two_year_range_requests_two_year_window(monkeypatch):
    captured = {}
    profile = MarketDataProfile(
        id="tushare-live",
        label="Tushare Live",
        provider="tushare",
        api_key="token",
        enabled=True,
    )

    def fake_call(_profile, api_name, params):
        captured["api_name"] = api_name
        captured["params"] = params
        return {"items": []}

    monkeypatch.setattr(kline_service, "date", FixedDate)
    monkeypatch.setattr(kline_service, "get_default_market_data_profile", lambda: profile)
    monkeypatch.setattr(kline_service, "_call_tushare_http_api_raw", fake_call)
    monkeypatch.setattr(
        kline_service,
        "_tushare_records_from_payload",
        lambda _payload: [
            {
                "trade_date": "20260522",
                "open": 10,
                "high": 12,
                "low": 9,
                "close": 11,
            }
        ],
    )
    kline_service._KLINE_CACHE.clear()

    try:
        payload = kline_service.get_kline_payload("000001.SZ", "monthly", "2y")
    finally:
        kline_service._KLINE_CACHE.clear()

    assert captured["api_name"] == "monthly"
    assert captured["params"]["start_date"] == "20240523"
    assert captured["params"]["end_date"] == "20260523"
    assert payload["range"] == "2y"
    assert payload["recordCount"] == 1


def test_weekly_kline_half_year_range_requests_six_month_window(monkeypatch):
    captured = {}
    profile = MarketDataProfile(
        id="tushare-live",
        label="Tushare Live",
        provider="tushare",
        api_key="token",
        enabled=True,
    )

    def fake_call(_profile, api_name, params):
        captured["api_name"] = api_name
        captured["params"] = params
        return {"items": []}

    monkeypatch.setattr(kline_service, "date", FixedDate)
    monkeypatch.setattr(kline_service, "get_default_market_data_profile", lambda: profile)
    monkeypatch.setattr(kline_service, "_call_tushare_http_api_raw", fake_call)
    monkeypatch.setattr(
        kline_service,
        "_tushare_records_from_payload",
        lambda _payload: [
            {
                "trade_date": "20260522",
                "open": 10,
                "high": 12,
                "low": 9,
                "close": 11,
            }
        ],
    )
    kline_service._KLINE_CACHE.clear()

    try:
        payload = kline_service.get_kline_payload("000001.SZ", "weekly", "6m")
    finally:
        kline_service._KLINE_CACHE.clear()

    assert captured["api_name"] == "weekly"
    assert captured["params"]["start_date"] == "20251123"
    assert captured["params"]["end_date"] == "20260523"
    assert payload["range"] == "6m"
    assert payload["recordCount"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("range_", ["6m", "2y"])
async def test_kline_route_accepts_extended_ranges(monkeypatch, range_):
    monkeypatch.setattr(
        routes_kline,
        "get_kline_payload",
        lambda symbol, period, range_: {
            "symbol": symbol,
            "period": period,
            "range": range_,
            "status": "READY",
            "dataMode": "LIVE",
            "provider": "tushare",
            "rows": [],
        },
    )

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get(f"/api/market-data/kline?symbol=000001.SZ&period=monthly&range={range_}")

    assert response.status_code == 200
    assert response.json()["range"] == range_
