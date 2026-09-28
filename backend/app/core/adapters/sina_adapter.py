from __future__ import annotations

import importlib.util
import logging
import re
import time
from datetime import datetime, timezone
from typing import List
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

from ..market_data_adapter import BaseMarketDataAdapter
from ...models.market_data import (
    AdapterCapability,
    AuxiliaryDataResponse,
    DataMode,
    DataSourceHealth,
    Freshness,
    MarketDataResponse,
)


def _to_sina_symbol(raw_symbol: str) -> str:
    symbol = raw_symbol.strip()
    code = re.sub(r"[^0-9]", "", symbol)
    if not code:
        return symbol.lower()
    digits = code[:6] if len(code) >= 6 else code
    if digits.startswith(("60", "68", "90", "50", "51", "52", "56", "58", "11", "13")):
        return f"sh{digits}"
    return f"sz{digits}"


class SinaAdapter(BaseMarketDataAdapter):
    adapter_id = "sina"
    provider_name = "sina"
    label = "新浪财经"
    priority = 4
    capabilities = {
        AdapterCapability.REALTIME_QUOTE,
        AdapterCapability.MONEYFLOW,
    }
    timeout_seconds = 10

    def _is_installed(self) -> bool:
        return True

    async def fetch_realtime_quote(self, symbol: str) -> MarketDataResponse:
        sina_symbol = _to_sina_symbol(symbol)
        endpoint = f"https://hq.sinajs.cn/list={sina_symbol}"
        try:
            import asyncio
            result = await asyncio.to_thread(self._fetch_sync, endpoint, sina_symbol)
            return result
        except Exception:
            logger.exception("Sina realtime_quote failed for %s", symbol)
            return MarketDataResponse(
                symbol=symbol,
                source="sina",
                provider=self.provider_name,
                fetched_at=datetime.now(timezone.utc).isoformat(),
                freshness=Freshness.UNKNOWN,
                confidence=0.0,
                error="数据获取失败，请稍后重试",
                data_mode=DataMode.MOCK,
            )

    async def fetch_historical_quote(
        self, symbol: str, start: str, end: str
    ) -> List[MarketDataResponse]:
        return []

    async def fetch_auxiliary(self, symbol: str, category: str) -> AuxiliaryDataResponse:
        if category != "moneyflow":
            return AuxiliaryDataResponse(
                category=category,
                source="sina",
                provider=self.provider_name,
                error=f"Sina does not support auxiliary category: {category}",
                data_mode=DataMode.MOCK,
            )

        try:
            import asyncio
            code = re.sub(r"[^0-9]", "", symbol)[:6]
            endpoint = f"https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.ssf?bankuaipici={code}"
            result = await asyncio.to_thread(self._fetch_moneyflow_sync, endpoint)
            return result
        except Exception:
            logger.exception("Sina fetch_auxiliary %s failed for %s", category, symbol)
            return AuxiliaryDataResponse(
                category=category,
                source="sina",
                provider=self.provider_name,
                error="数据获取失败，请稍后重试",
                data_mode=DataMode.MOCK,
            )

    async def health_check(self) -> DataSourceHealth:
        started = time.perf_counter()
        try:
            import asyncio
            await asyncio.to_thread(self._quick_check)
            latency = int((time.perf_counter() - started) * 1000)
            return DataSourceHealth(
                adapter_id=self.adapter_id,
                provider=self.provider_name,
                label=self.label,
                capabilities=list(self.capabilities),
                healthy=True,
                last_check_at=datetime.now(timezone.utc).isoformat(),
                latency_avg_ms=latency,
                message="OK",
                enabled=self.enabled,
                installed=True,
            )
        except Exception:
            latency = int((time.perf_counter() - started) * 1000)
            logger.exception("Sina health_check failed")
            return DataSourceHealth(
                adapter_id=self.adapter_id,
                provider=self.provider_name,
                label=self.label,
                capabilities=list(self.capabilities),
                healthy=False,
                last_check_at=datetime.now(timezone.utc).isoformat(),
                latency_avg_ms=latency,
                message="健康检查失败，请稍后重试",
                enabled=self.enabled,
                installed=True,
            )

    def _fetch_sync(self, endpoint: str, sina_symbol: str) -> MarketDataResponse:
        request = Request(
            endpoint,
            headers={
                "Accept": "*/*",
                "Referer": "https://finance.sina.com.cn",
                "User-Agent": "Mozilla/5.0",
            },
            method="GET",
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            text = response.read().decode("gb18030", errors="replace")

        match = re.search(r'="(.*)";', text)
        if not match:
            raise RuntimeError(f"Sina returned unexpected response for {sina_symbol}.")

        values = match.group(1).split(",")
        if len(values) < 32 or not values[0]:
            raise RuntimeError(f"Sina returned no quote for {sina_symbol}.")

        price = _coerce_number(values[3])
        pre_close = _coerce_number(values[2])
        change_pct = None
        if price is not None and pre_close not in (None, 0):
            change_pct = (price - pre_close) / pre_close * 100

        return MarketDataResponse(
            symbol=sina_symbol,
            name=values[0],
            price=price,
            change_percent=round(change_pct, 2) if change_pct is not None else None,
            volume=_coerce_number(values[8]),
            timestamp=f"{values[30]} {values[31]}" if len(values) > 31 else "",
            source="sina_http",
            provider=self.provider_name,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            freshness=Freshness.REALTIME,
            confidence=0.70,
            data_mode=DataMode.LIVE,
        )

    def _fetch_moneyflow_sync(self, endpoint: str) -> AuxiliaryDataResponse:
        import json as json_mod
        request = Request(
            endpoint,
            headers={
                "Accept": "application/json",
                "Referer": "https://finance.sina.com.cn",
                "User-Agent": "Mozilla/5.0",
            },
            method="GET",
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            raw = response.read().decode("gb18030", errors="replace")
        try:
            data = json_mod.loads(raw)
        except json_mod.JSONDecodeError:
            data = []

        records = data if isinstance(data, list) else [data]
        return AuxiliaryDataResponse(
            category="moneyflow",
            source="sina_http",
            provider=self.provider_name,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            freshness=Freshness.DELAYED_15MIN,
            confidence=0.65,
            data_mode=DataMode.LIVE,
            records=records,
            record_count=len(records),
        )

    def _quick_check(self) -> None:
        endpoint = "https://hq.sinajs.cn/list=sh603663"
        request = Request(
            endpoint,
            headers={"Referer": "https://finance.sina.com.cn"},
            method="GET",
        )
        with urlopen(request, timeout=10) as resp:
            resp.read()


def _coerce_number(value: object) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and value != value:
            return None
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "").rstrip("%")
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None
