from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.request import Request, urlopen

from ...models.market_data import AdapterCapability, DataMode, DataSourceHealth, Freshness, MarketDataResponse
from ..market_data_egress_policy import assert_market_data_egress_allowed
from .authorized_rest_adapter import AuthorizedRestMarketDataAdapter

logger = logging.getLogger(__name__)

TENCENT_PUBLIC_MSTATS_URL = "https://stockapp.finance.qq.com/mstats/"
TENCENT_PUBLIC_QUOTE_BASE_URL = "https://qt.gtimg.cn"
TENCENT_PUBLIC_QUOTE_SOURCE = "tencent_public_quote"
TENCENT_PUBLIC_QUOTE_MESSAGE = "腾讯公开实时行情可用；历史行情、公告和资金流仍需配置授权网关。"


class TencentFinanceAdapter(AuthorizedRestMarketDataAdapter):
    adapter_id = "tencent_finance"
    provider_name = "tencent_finance"
    label = "腾讯财经"
    priority = 2
    env_prefix = "TENCENT_FINANCE"
    requires_token = False
    capabilities = {
        AdapterCapability.REALTIME_QUOTE,
        AdapterCapability.HISTORICAL_QUOTE,
        AdapterCapability.ANNOUNCEMENTS,
        AdapterCapability.MONEYFLOW,
        AdapterCapability.INDEX,
    }
    timeout_seconds = 12

    async def fetch_realtime_quote(self, symbol: str) -> MarketDataResponse:
        if self._uses_authorized_gateway():
            return await super().fetch_realtime_quote(symbol)
        try:
            return await asyncio.to_thread(
                _fetch_tencent_public_quote_sync,
                symbol,
                self.timeout_seconds,
            )
        except Exception as exc:
            logger.warning("Tencent public quote unavailable for %s: %s", symbol, _short_error(exc))
            return MarketDataResponse(
                symbol=symbol,
                source=TENCENT_PUBLIC_QUOTE_SOURCE,
                provider=self.provider_name,
                fetched_at=self._now_iso(),
                freshness=Freshness.UNKNOWN,
                confidence=0.0,
                error=f"腾讯公开实时行情不可用：{_short_error(exc)}",
                data_mode=DataMode.MOCK,
            )

    async def health_check(self) -> DataSourceHealth:
        if self._uses_authorized_gateway():
            return await super().health_check()

        started = time.perf_counter()
        try:
            quote = await asyncio.to_thread(
                _fetch_tencent_public_quote_sync,
                self._health_symbol(),
                self.timeout_seconds,
            )
            healthy = quote.price is not None and not quote.error
            message = TENCENT_PUBLIC_QUOTE_MESSAGE if healthy else quote.error
            latency = int((time.perf_counter() - started) * 1000)
            return DataSourceHealth(
                adapter_id=self.adapter_id,
                provider=self.provider_name,
                label=self.label,
                capabilities=list(self.capabilities),
                configured=True,
                healthy=healthy,
                upstream_healthy=healthy,
                live_data_usable=healthy,
                fallback_used=True,
                last_error="" if healthy else message,
                last_check_at=self._now_iso(),
                latency_avg_ms=latency,
                message=message,
                enabled=self.enabled,
                installed=True,
            )
        except Exception as exc:
            message = f"腾讯公开实时行情不可用：{_short_error(exc)}"
            return DataSourceHealth(
                adapter_id=self.adapter_id,
                provider=self.provider_name,
                label=self.label,
                capabilities=list(self.capabilities),
                configured=True,
                healthy=False,
                upstream_healthy=False,
                live_data_usable=False,
                fallback_used=True,
                last_error=message,
                last_check_at=self._now_iso(),
                latency_avg_ms=int((time.perf_counter() - started) * 1000),
                message=message,
                enabled=self.enabled,
                installed=True,
            )

    def _uses_authorized_gateway(self) -> bool:
        base_url = os.getenv(f"{self.env_prefix}_BASE_URL", "").strip()
        if not base_url:
            return False
        normalized = base_url.rstrip("/").lower()
        return not (
            normalized == TENCENT_PUBLIC_QUOTE_BASE_URL
            or normalized == TENCENT_PUBLIC_MSTATS_URL.rstrip("/")
        )


def _fetch_tencent_public_quote_sync(symbol: str, timeout_seconds: int) -> MarketDataResponse:
    market_code = _tencent_market_code(symbol)
    url = f"{TENCENT_PUBLIC_QUOTE_BASE_URL}/q={market_code}"
    assert_market_data_egress_allowed(
        SimpleNamespace(
            provider="tencent_finance",
            base_url=TENCENT_PUBLIC_QUOTE_BASE_URL,
            quote_path=url,
            api_key="",
        )
    )
    request = Request(
        url,
        headers={
            "Accept": "*/*",
            "Referer": TENCENT_PUBLIC_MSTATS_URL,
            "User-Agent": "Mozilla/5.0",
        },
        method="GET",
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        raw = response.read().decode("gb18030", errors="replace")
    return _parse_tencent_public_quote(raw, symbol, market_code)


def _parse_tencent_public_quote(raw: str, symbol: str, market_code: str) -> MarketDataResponse:
    match = re.search(r'v_[a-z0-9]+="([^"]*)"', raw or "", flags=re.IGNORECASE)
    if not match:
        raise RuntimeError("Tencent public quote returned unexpected response.")
    values = match.group(1).split("~")
    if len(values) < 4 or not values[1]:
        raise RuntimeError("Tencent public quote returned no quote row.")

    timestamp = _format_tencent_timestamp(_field(values, 30))
    return MarketDataResponse(
        symbol=_field(values, 2) or symbol,
        name=_field(values, 1),
        price=_to_float(_field(values, 3)),
        change_percent=_to_float(_field(values, 32)),
        volume=_to_float(_field(values, 6)),
        timestamp=timestamp,
        source=TENCENT_PUBLIC_QUOTE_SOURCE,
        provider="tencent_finance",
        fetched_at=datetime.now(timezone.utc).isoformat(),
        freshness=Freshness.REALTIME,
        confidence=0.72,
        data_mode=DataMode.LIVE,
        extra={
            "marketCode": market_code,
            "sourcePage": TENCENT_PUBLIC_MSTATS_URL,
            "open": _to_float(_field(values, 5)),
            "preClose": _to_float(_field(values, 4)),
            "change": _to_float(_field(values, 31)),
            "high": _to_float(_field(values, 33)),
            "low": _to_float(_field(values, 34)),
            "amount": _to_float(_field(values, 37)),
            "rawFieldCount": len(values),
        },
    )


def _tencent_market_code(symbol: str) -> str:
    raw = str(symbol or "").strip().lower().replace("_", ".")
    if re.fullmatch(r"(sh|sz)\d{6}", raw):
        return raw
    if re.fullmatch(r"\d{6}\.(sh|sz)", raw):
        code, market = raw.split(".", 1)
        return f"{market}{code}"
    code = re.sub(r"\D", "", raw)
    if not re.fullmatch(r"\d{6}", code):
        raise ValueError(f"Unsupported Tencent Finance symbol: {symbol}")
    prefix = "sh" if code.startswith(("5", "6", "9")) else "sz"
    return f"{prefix}{code}"


def _field(values: list[str], index: int) -> str:
    return values[index].strip() if index < len(values) else ""


def _to_float(value: str) -> float | None:
    if value in ("", "-", None):
        return None
    try:
        return float(str(value).replace(",", "").rstrip("%"))
    except (TypeError, ValueError):
        return None


def _format_tencent_timestamp(value: str) -> str:
    if re.fullmatch(r"\d{14}", value or ""):
        return f"{value[0:4]}-{value[4:6]}-{value[6:8]} {value[8:10]}:{value[10:12]}:{value[12:14]}"
    return value or ""


def _short_error(exc: Exception) -> str:
    text = str(exc).strip()
    return (text or "unknown error")[:240]
