from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from ...models.market_data import (
    AdapterCapability,
    AuxiliaryDataResponse,
    DataMode,
    DataSourceHealth,
    Freshness,
    MarketDataResponse,
)
from ..market_data_adapter import BaseMarketDataAdapter
from ..market_data_egress_policy import assert_market_data_egress_allowed


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _EgressProfile:
    provider: str
    base_url: str
    quote_path: str = ""
    api_key: str = ""


class AuthorizedRestMarketDataAdapter(BaseMarketDataAdapter):
    """Authorized market-data REST gateway adapter.

    Commercial providers have different SDKs and licensed gateway shapes. This
    adapter keeps the runtime contract stable: a deployment supplies an
    authorized base URL and optional token, while the quant system receives the
    existing MarketDataResponse/AuxiliaryDataResponse models.
    """

    env_prefix: str = ""
    requires_token: bool = True
    quote_path_default = "quote"
    historical_path_default = "historical"
    auxiliary_path_default = "auxiliary"
    health_path_default = "health"

    async def fetch_realtime_quote(self, symbol: str) -> MarketDataResponse:
        configured, message = self._configuration_status()
        if not configured:
            return self._unconfigured_quote(symbol, message)

        try:
            payload = await asyncio.to_thread(
                self._request_json,
                "QUOTE",
                {"symbol": symbol},
            )
            return self._quote_from_payload(symbol, payload)
        except Exception as exc:
            logger.warning(
                "%s realtime_quote unavailable for %s: %s",
                self.adapter_id,
                symbol,
                _short_error(exc),
            )
            return MarketDataResponse(
                symbol=symbol,
                source=self.adapter_id,
                provider=self.provider_name,
                fetched_at=self._now_iso(),
                freshness=Freshness.UNKNOWN,
                confidence=0.0,
                error="授权行情源实时行情不可用，请检查网关、权限或白名单配置。",
                data_mode=DataMode.MOCK,
            )

    async def fetch_historical_quote(
        self, symbol: str, start: str, end: str
    ) -> List[MarketDataResponse]:
        configured, _message = self._configuration_status()
        if not configured:
            return []

        try:
            payload = await asyncio.to_thread(
                self._request_json,
                "HISTORICAL",
                {"symbol": symbol, "start": start, "end": end},
            )
            records = _records_from_payload(payload)
            results = [self._quote_from_record(symbol, record, default_freshness=Freshness.EOD) for record in records]
            results.sort(key=lambda item: item.timestamp)
            return results
        except Exception as exc:
            logger.warning(
                "%s historical_quote unavailable for %s: %s",
                self.adapter_id,
                symbol,
                _short_error(exc),
            )
            return []

    async def fetch_auxiliary(self, symbol: str, category: str) -> AuxiliaryDataResponse:
        capability = self._category_to_capability(category)
        if capability is None or capability not in self.capabilities:
            return AuxiliaryDataResponse(
                category=category,
                source=self.adapter_id,
                provider=self.provider_name,
                error=f"{self.label or self.adapter_id} does not support auxiliary category: {category}",
                data_mode=DataMode.MOCK,
            )

        configured, message = self._configuration_status()
        if not configured:
            return AuxiliaryDataResponse(
                category=category,
                source=self.adapter_id,
                provider=self.provider_name,
                error=message,
                data_mode=DataMode.MOCK,
            )

        try:
            payload = await asyncio.to_thread(
                self._request_json,
                "AUXILIARY",
                {"symbol": symbol, "category": category},
            )
            error = _payload_error(payload)
            if error:
                return AuxiliaryDataResponse(
                    category=category,
                    source=f"{self.adapter_id}_authorized_rest",
                    provider=self.provider_name,
                    error=error,
                    data_mode=DataMode.MOCK,
                )
            records = _records_from_payload(payload)
            if not records:
                return AuxiliaryDataResponse(
                    category=category,
                    source=f"{self.adapter_id}_authorized_rest",
                    provider=self.provider_name,
                    error="授权行情源返回空记录，可能未开通该数据能力。",
                    data_mode=DataMode.MOCK,
                )
            return AuxiliaryDataResponse(
                category=category,
                source=f"{self.adapter_id}_authorized_rest",
                provider=self.provider_name,
                fetched_at=self._now_iso(),
                freshness=_freshness_from_payload(payload, Freshness.EOD),
                confidence=_confidence_from_payload(payload, 0.84),
                data_mode=DataMode.LIVE,
                records=records,
                record_count=len(records),
                extra=_safe_extra(payload),
            )
        except Exception as exc:
            logger.warning(
                "%s fetch_auxiliary %s unavailable for %s: %s",
                self.adapter_id,
                category,
                symbol,
                _short_error(exc),
            )
            return AuxiliaryDataResponse(
                category=category,
                source=self.adapter_id,
                provider=self.provider_name,
                error="授权行情源辅助数据不可用，请检查网关、权限或白名单配置。",
                data_mode=DataMode.MOCK,
            )

    async def health_check(self) -> DataSourceHealth:
        started = time.perf_counter()
        configured, message = self._configuration_status()
        if not configured:
            return DataSourceHealth(
                adapter_id=self.adapter_id,
                provider=self.provider_name,
                label=self.label,
                capabilities=list(self.capabilities),
                configured=False,
                healthy=False,
                upstream_healthy=False,
                live_data_usable=False,
                last_error=message,
                last_check_at=self._now_iso(),
                latency_avg_ms=int((time.perf_counter() - started) * 1000),
                message=message,
                enabled=self.enabled,
                installed=True,
            )

        try:
            payload = await asyncio.to_thread(
                self._request_json,
                "HEALTH",
                {"symbol": self._health_symbol()},
            )
            error = _payload_error(payload)
            healthy = not error and _payload_bool(payload, "healthy", True)
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
                last_error=error,
                last_check_at=self._now_iso(),
                latency_avg_ms=latency,
                message=error or "OK",
                enabled=self.enabled,
                installed=True,
            )
        except Exception as exc:
            latency = int((time.perf_counter() - started) * 1000)
            message = f"授权行情源健康检查失败：{_short_error(exc)}"
            return DataSourceHealth(
                adapter_id=self.adapter_id,
                provider=self.provider_name,
                label=self.label,
                capabilities=list(self.capabilities),
                configured=True,
                healthy=False,
                upstream_healthy=False,
                live_data_usable=False,
                last_error=message,
                last_check_at=self._now_iso(),
                latency_avg_ms=latency,
                message=message,
                enabled=self.enabled,
                installed=True,
            )

    def _configuration_status(self) -> tuple[bool, str]:
        base_url = self._base_url()
        if not base_url:
            return False, f"未配置 {self.env_prefix}_BASE_URL，{self.label or self.adapter_id} 不会参与真实数据决策。"
        if self.requires_token and not self._api_key():
            return False, f"未配置 {self.env_prefix}_API_KEY 或 {self.env_prefix}_TOKEN。"
        return True, "configured"

    def _base_url(self) -> str:
        return os.getenv(f"{self.env_prefix}_BASE_URL", "").strip()

    def _api_key(self) -> str:
        return (
            os.getenv(f"{self.env_prefix}_API_KEY", "").strip()
            or os.getenv(f"{self.env_prefix}_TOKEN", "").strip()
        )

    def _health_symbol(self) -> str:
        return os.getenv(f"{self.env_prefix}_HEALTH_SYMBOL", "603663").strip() or "603663"

    def _path_for(self, operation: str) -> str:
        defaults = {
            "QUOTE": self.quote_path_default,
            "HISTORICAL": self.historical_path_default,
            "AUXILIARY": self.auxiliary_path_default,
            "HEALTH": self.health_path_default,
        }
        return os.getenv(f"{self.env_prefix}_{operation}_PATH", defaults[operation]).strip()

    def _request_json(self, operation: str, params: Mapping[str, str]) -> Any:
        base_url = self._base_url()
        path = self._path_for(operation)
        endpoint = urljoin(f"{base_url.rstrip('/')}/", path.lstrip("/")) if path else base_url
        query_params = {
            "adapter": self.adapter_id,
            "operation": operation.lower(),
            **{key: value for key, value in params.items() if value not in (None, "")},
        }
        separator = "&" if "?" in endpoint else "?"
        url = f"{endpoint}{separator}{urlencode(query_params)}"
        assert_market_data_egress_allowed(
            _EgressProfile(
                provider=self.provider_name,
                base_url=base_url,
                quote_path=endpoint,
                api_key=self._api_key(),
            ),
            endpoint=url,
        )
        request = Request(url, headers=self._headers(), method="GET")
        with urlopen(request, timeout=self.timeout_seconds) as response:
            raw = response.read().decode("utf-8-sig", errors="replace")
        if not raw.strip():
            raise RuntimeError("empty response")
        return json.loads(raw)

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "TianyuanQuant/market-data-adapter",
        }
        api_key = self._api_key()
        if api_key:
            header_name = os.getenv(f"{self.env_prefix}_AUTH_HEADER", "Authorization").strip() or "Authorization"
            scheme = os.getenv(f"{self.env_prefix}_AUTH_SCHEME", "Bearer").strip()
            headers[header_name] = f"{scheme} {api_key}".strip() if scheme else api_key
        return headers

    def _quote_from_payload(self, symbol: str, payload: Any) -> MarketDataResponse:
        error = _payload_error(payload)
        if error:
            return self._unconfigured_quote(symbol, error)
        record = _record_from_payload(payload)
        if not record:
            raise RuntimeError("no quote record returned")
        return self._quote_from_record(symbol, record, default_freshness=Freshness.REALTIME)

    def _quote_from_record(
        self,
        symbol: str,
        record: Mapping[str, Any],
        *,
        default_freshness: Freshness,
    ) -> MarketDataResponse:
        return MarketDataResponse(
            symbol=str(_first(record, "symbol", "ts_code", "code") or symbol),
            name=str(_first(record, "name", "stock_name", "security_name") or ""),
            price=_to_float(_first(record, "price", "close", "last", "current")),
            change_percent=_to_float(_first(record, "change_percent", "changePercent", "pct_change", "pctChg")),
            volume=_to_float(_first(record, "volume", "vol", "turnover_volume")),
            timestamp=str(_first(record, "timestamp", "time", "trade_time", "tradeDate", "date") or ""),
            source=f"{self.adapter_id}_authorized_rest",
            provider=self.provider_name,
            fetched_at=self._now_iso(),
            freshness=_freshness_from_payload(record, default_freshness),
            confidence=_confidence_from_payload(record, 0.86),
            data_mode=DataMode.LIVE,
            extra=_market_extra(record),
        )

    def _unconfigured_quote(self, symbol: str, message: str) -> MarketDataResponse:
        return MarketDataResponse(
            symbol=symbol,
            source=self.adapter_id,
            provider=self.provider_name,
            fetched_at=self._now_iso(),
            freshness=Freshness.UNKNOWN,
            confidence=0.0,
            error=message,
            data_mode=DataMode.MOCK,
        )

    @staticmethod
    def _category_to_capability(category: str) -> AdapterCapability | None:
        mapping = {
            "fundamentals": AdapterCapability.FUNDAMENTALS,
            "announcements": AdapterCapability.ANNOUNCEMENTS,
            "news": AdapterCapability.ANNOUNCEMENTS,
            "moneyflow": AdapterCapability.MONEYFLOW,
            "chip": AdapterCapability.CHIP,
            "macro": AdapterCapability.MACRO,
            "index": AdapterCapability.INDEX,
            "index_sector": AdapterCapability.INDEX,
        }
        return mapping.get(str(category or "").strip().lower())


def _record_from_payload(payload: Any) -> Mapping[str, Any]:
    if isinstance(payload, Mapping):
        for key in ("data", "quote", "record", "result"):
            value = payload.get(key)
            if isinstance(value, Mapping):
                return value
        return payload
    return {}


def _records_from_payload(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, Mapping)]
    if not isinstance(payload, Mapping):
        return []
    for key in ("records", "items", "data", "quotes", "klines", "result"):
        value = payload.get(key)
        if isinstance(value, list):
            return [dict(item) for item in value if isinstance(item, Mapping)]
        if isinstance(value, Mapping):
            nested = _records_from_payload(value)
            if nested:
                return nested
    return []


def _payload_error(payload: Any) -> str:
    if not isinstance(payload, Mapping):
        return ""
    error = _first(payload, "error", "last_error", "message")
    status = str(_first(payload, "status", "code") or "").upper()
    if status in {"FAILED", "ERROR", "NOT_CONFIGURED", "UNAUTHORIZED", "FORBIDDEN"} and error:
        return _short_text(error)
    if isinstance(error, str) and error and status not in {"", "READY", "OK", "SUCCESS", "200"}:
        return _short_text(error)
    return ""


def _payload_bool(payload: Any, key: str, default: bool) -> bool:
    if not isinstance(payload, Mapping) or key not in payload:
        return default
    value = payload.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "ready", "ok", "success"}
    return bool(value)


def _freshness_from_payload(payload: Any, default: Freshness) -> Freshness:
    if isinstance(payload, Mapping):
        raw = str(_first(payload, "freshness", "freshnessStatus") or "").upper()
        if raw in Freshness.__members__:
            return Freshness[raw]
        for item in Freshness:
            if raw == item.value:
                return item
    return default


def _confidence_from_payload(payload: Any, default: float) -> float:
    if isinstance(payload, Mapping):
        value = _to_float(_first(payload, "confidence", "quality", "score"))
        if value is not None:
            return max(0.0, min(value, 1.0))
    return default


def _market_extra(record: Mapping[str, Any]) -> Dict[str, Any]:
    keys = (
        "open",
        "high",
        "low",
        "amount",
        "turnoverRate",
        "turnover_rate",
        "preClose",
        "pre_close",
        "sector",
        "market",
    )
    return {key: record[key] for key in keys if key in record}


def _safe_extra(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {}
    return {
        key: value
        for key, value in payload.items()
        if key not in {"records", "items", "data", "result", "token", "api_key", "authorization"}
    }


def _first(record: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in record and record[key] not in (None, ""):
            return record[key]
    return None


def _to_float(value: Any) -> float | None:
    if value in (None, "", "-") or isinstance(value, bool):
        return None
    try:
        return float(str(value).replace(",", "").rstrip("%"))
    except (TypeError, ValueError):
        return None


def _short_error(exc: Exception) -> str:
    return _short_text(str(exc).strip() or exc.__class__.__name__)


def _short_text(value: Any) -> str:
    return str(value or "").strip()[:220]
