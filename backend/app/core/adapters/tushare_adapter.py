from __future__ import annotations

import importlib
import importlib.util
import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

from ..market_data_adapter import BaseMarketDataAdapter
from ..market_data_egress_policy import assert_market_data_egress_allowed
from ...models.agent_runtime import MarketDataProfile
from ...models.market_data import (
    AdapterCapability,
    AuxiliaryDataResponse,
    DataMode,
    DataSourceHealth,
    Freshness,
    MarketDataResponse,
)


def _last_quarter_end(today: Any) -> str:
    from datetime import date, timedelta
    if not isinstance(today, date):
        today = date.today()
    quarter_months = {1: 3, 2: 6, 3: 9, 4: 12}
    quarter = (today.month - 1) // 3
    if quarter == 0:
        year = today.year - 1
        month = 12
    else:
        year = today.year
        month = quarter_months[quarter]
    next_month = date(year, month, 28) + timedelta(days=4)
    return (next_month - timedelta(days=next_month.day)).strftime("%Y%m%d")


TUSHARE_HTTP_ENDPOINT = "https://api.tushare.pro"
TUSHARE_DEFAULT_FIELDS = "NAME,TS_CODE,DATE,TIME,OPEN,PRE_CLOSE,PRICE,HIGH,LOW,VOLUME,AMOUNT"
TUSHARE_RESERVED_EXTRA_PARAMS = {"api_name", "fields", "src"}
TUSHARE_HEALTH_CHECK_TIMEOUT_SECONDS = 120.0


def _default_tushare_profile() -> MarketDataProfile:
    return MarketDataProfile(
        id="default-tushare",
        label="Tushare A-share realtime",
        provider="tushare",
        base_url=TUSHARE_HTTP_ENDPOINT,
        quote_path="",
        symbol_query_param="ts_code",
        auth_mode="token",
        api_key="",
        api_key_header="",
        api_key_query_param="token",
        timeout_seconds=20,
        enabled=True,
        extra_query_params={
            "api_name": "realtime_quote",
            "src": "dc",
            "fields": TUSHARE_DEFAULT_FIELDS,
        },
        price_path="price",
        name_path="name",
        change_percent_path="pct_change",
        volume_path="volume",
        timestamp_path="time",
    )


class TushareAdapter(BaseMarketDataAdapter):
    adapter_id = "tushare"
    provider_name = "tushare"
    label = "Tushare (官方)"
    priority = 1
    capabilities = {
        AdapterCapability.REALTIME_QUOTE,
        AdapterCapability.HISTORICAL_QUOTE,
        AdapterCapability.FUNDAMENTALS,
        AdapterCapability.ANNOUNCEMENTS,
        AdapterCapability.MONEYFLOW,
        AdapterCapability.CHIP,
        AdapterCapability.MACRO,
    }
    timeout_seconds = 20

    def __init__(self, profile: MarketDataProfile | None = None):
        self._profile = profile or _default_tushare_profile()
        self.timeout_seconds = self._profile.timeout_seconds
        self._sdk_available = importlib.util.find_spec("tushare") is not None

    def update_profile(self, profile: MarketDataProfile) -> None:
        self._profile = profile
        self.timeout_seconds = profile.timeout_seconds

    def _is_installed(self) -> bool:
        return self._sdk_available

    async def fetch_realtime_quote(self, symbol: str) -> MarketDataResponse:
        profile = self._profile
        ts_code = _normalize_tushare_symbol(symbol)
        src = str(profile.extra_query_params.get("src") or "dc").strip() or "dc"

        try:
            if not profile.api_key:
                return MarketDataResponse(
                    symbol=symbol,
                    error="Tushare token is missing",
                    provider=self.provider_name,
                    confidence=0.0,
                    data_mode=DataMode.MOCK,
                )
            assert_market_data_egress_allowed(profile)

            if self._sdk_available:
                try:
                    return await self._sdk_realtime_quote(ts_code, src)
                except Exception as exc:
                    logger.warning(
                        "Tushare SDK realtime_quote unavailable for %s; falling back to Sina: %s",
                        symbol,
                        _safe_tushare_error(exc),
                    )

            return await self._sina_fallback(ts_code, src)
        except Exception as exc:
            logger.warning(
                "Tushare realtime_quote unavailable for %s: %s",
                symbol,
                _safe_tushare_error(exc),
            )
            return MarketDataResponse(
                symbol=symbol,
                source="tushare",
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
        profile = self._profile
        ts_code = _normalize_tushare_symbol(symbol)
        if not profile.api_key:
            return []

        try:
            payload = await self._call_tushare_http_api(
                profile, "daily", {
                    "ts_code": ts_code,
                    "start_date": start.replace("-", ""),
                    "end_date": end.replace("-", ""),
                }
            )
            records = _tushare_records_from_payload(payload)
            results: List[MarketDataResponse] = []
            for record in records:
                price = _coerce_number(record.get("close"))
                pre_close = _coerce_number(record.get("pre_close"))
                change_pct = None
                if price is not None and pre_close not in (None, 0):
                    change_pct = (price - pre_close) / pre_close * 100
                results.append(MarketDataResponse(
                    symbol=symbol,
                    name=str(record.get("name", "")),
                    price=price,
                    change_percent=round(change_pct, 2) if change_pct is not None else None,
                    volume=_coerce_number(record.get("vol")),
                    timestamp=str(record.get("trade_date", "")),
                    source="tushare_http",
                    provider=self.provider_name,
                    fetched_at=datetime.now(timezone.utc).isoformat(),
                    freshness=Freshness.EOD,
                    confidence=0.88,
                    data_mode=DataMode.LIVE,
                ))
            return results
        except Exception:
            logger.exception("Tushare fetch_historical_quote failed for %s (%s-%s)", symbol, start, end)
            return []

    async def fetch_auxiliary(self, symbol: str, category: str) -> AuxiliaryDataResponse:
        profile = self._profile
        ts_code = _normalize_tushare_symbol(symbol)
        if not profile.api_key:
            return AuxiliaryDataResponse(
                category=category,
                source="tushare",
                provider=self.provider_name,
                error="Tushare token is missing",
                data_mode=DataMode.MOCK,
            )

        from datetime import date, timedelta

        today = date.today()
        yesterday = today - timedelta(days=1)
        last_quarter_end = _last_quarter_end(today)
        thirty_days_ago = today - timedelta(days=30)

        api_map = {
            "fundamentals": ("income_vip", {"ts_code": ts_code, "period": last_quarter_end}),
            "announcements": ("disclosure_date", {"ts_code": ts_code}),
            "moneyflow": ("moneyflow_mkt_dc", {"ts_code": ts_code, "trade_date": yesterday.strftime("%Y%m%d")}),
        }
        if category == "macro":
            return await self._fetch_macro(profile)
        if category == "chip":
            from ..tushare_chip_service import fetch_tushare_chip_payload

            chip_payload = await asyncio.to_thread(
                fetch_tushare_chip_payload,
                profile,
                symbol,
                "3m",
                use_cache=False,
            )
            records = list(chip_payload.get("perfRows") or []) + list(chip_payload.get("chipRows") or [])
            if chip_payload.get("status") != "READY":
                return AuxiliaryDataResponse(
                    category=category,
                    source="tushare",
                    provider=self.provider_name,
                    error=chip_payload.get("error") or chip_payload.get("message") or "Tushare chip APIs returned no records",
                    data_mode=DataMode.MOCK,
                    extra=chip_payload,
                )
            return AuxiliaryDataResponse(
                category=category,
                source="tushare_http",
                provider=self.provider_name,
                fetched_at=datetime.now(timezone.utc).isoformat(),
                freshness=Freshness.EOD,
                confidence=0.9 if not chip_payload.get("error") else 0.72,
                data_mode=DataMode.LIVE,
                records=records,
                record_count=len(records),
                extra=chip_payload,
            )
        if category not in api_map:
            return AuxiliaryDataResponse(
                category=category,
                error=f"Tushare does not support auxiliary category: {category}",
                data_mode=DataMode.MOCK,
            )

        api_name, params = api_map[category]
        try:
            payload = await self._call_tushare_http_api(profile, api_name, params)
            records = _tushare_records_from_payload(payload)
            return AuxiliaryDataResponse(
                category=category,
                source="tushare_http",
                provider=self.provider_name,
                fetched_at=datetime.now(timezone.utc).isoformat(),
                freshness=Freshness.EOD,
                confidence=0.88,
                data_mode=DataMode.LIVE,
                records=records,
                record_count=len(records),
            )
        except Exception as exc:
            logger.exception("Tushare fetch_auxiliary %s failed for %s", category, symbol)
            return AuxiliaryDataResponse(
                category=category,
                source="tushare",
                provider=self.provider_name,
                error=_safe_tushare_error(exc),
                data_mode=DataMode.MOCK,
            )

    async def _fetch_macro(self, profile: MarketDataProfile) -> AuxiliaryDataResponse:
        records: List[Dict[str, Any]] = []
        errors: List[str] = []
        from datetime import date

        year = date.today().year
        api_calls = [
            ("cn_cpi", {"start_m": f"{year - 1}01", "end_m": f"{year}12"}),
            ("cn_gdp", {"start_q": f"{year - 2}Q1", "end_q": f"{year}Q4"}),
            ("shibor_lpr", {}),
        ]

        for api_name, params in api_calls:
            try:
                payload = await self._call_tushare_http_api(profile, api_name, params)
                api_records = _tushare_records_from_payload(payload)
                if api_records:
                    latest = api_records[0]
                    latest["_api_name"] = api_name
                    records.append(latest)
            except Exception as exc:
                logger.info("Tushare macro API %s unavailable: %s", api_name, exc)
                errors.append(f"{api_name}: {_safe_tushare_error(exc)}")

        if not records:
            return AuxiliaryDataResponse(
                category="macro",
                source="tushare",
                provider=self.provider_name,
                error="Tushare macro APIs returned no records"
                + (f"; failures: {'; '.join(errors)}" if errors else ""),
                data_mode=DataMode.MOCK,
            )

        return AuxiliaryDataResponse(
            category="macro",
            source="tushare_http",
            provider=self.provider_name,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            freshness=Freshness.EOD,
            confidence=0.82 if not errors else 0.62,
            data_mode=DataMode.LIVE,
            records=records,
            record_count=len(records),
        )

    async def health_check(self) -> DataSourceHealth:
        started = time.perf_counter()
        check_timeout = min(
            max(float(self.timeout_seconds or self._profile.timeout_seconds or 1), 1.0),
            TUSHARE_HEALTH_CHECK_TIMEOUT_SECONDS,
        )
        try:
            if not self._profile.api_key:
                return DataSourceHealth(
                    adapter_id=self.adapter_id,
                    provider=self.provider_name,
                    label=self.label,
                    capabilities=list(self.capabilities),
                    healthy=False,
                    message="Token is missing",
                    enabled=self.enabled,
                    installed=self._sdk_available,
                )
            assert_market_data_egress_allowed(self._profile)

            upstream_healthy = True
            live_data_usable = True
            fallback_used = False
            last_error = ""
            if self._sdk_available:
                ts_code = "603663.SH"
                try:
                    healthy, message = await asyncio.wait_for(
                        asyncio.to_thread(self._sdk_health_check_sync, ts_code),
                        timeout=check_timeout,
                    )
                    upstream_healthy = healthy
                    live_data_usable = healthy
                    last_error = "" if healthy else message
                except asyncio.TimeoutError:
                    raise
                except Exception as exc:
                    sdk_error = _safe_tushare_error(exc)
                    logger.warning(
                        "Tushare SDK health check unavailable; probing Sina fallback: %s",
                        sdk_error,
                    )
                    try:
                        await asyncio.wait_for(
                            asyncio.to_thread(self._sina_health_check_sync, check_timeout),
                            timeout=check_timeout,
                        )
                    except Exception as fallback_exc:
                        fallback_error = _safe_tushare_error(fallback_exc)
                        raise RuntimeError(
                            f"Tushare SDK realtime unavailable: {sdk_error}; "
                            f"Sina fallback unavailable: {fallback_error}"
                        ) from fallback_exc
                    healthy = True
                    message = _tushare_health_fallback_message(sdk_error)
                    fallback_used = True
                    last_error = sdk_error
            else:
                await asyncio.wait_for(
                    asyncio.to_thread(self._sina_health_check_sync, check_timeout),
                    timeout=check_timeout,
                )
                healthy = True
                message = "OK (Sina fallback available)"
                fallback_used = True

            latency = int((time.perf_counter() - started) * 1000)
            return DataSourceHealth(
                adapter_id=self.adapter_id,
                provider=self.provider_name,
                label=self.label,
                capabilities=list(self.capabilities),
                healthy=healthy,
                upstream_healthy=upstream_healthy,
                live_data_usable=live_data_usable,
                fallback_used=fallback_used,
                last_error=last_error,
                last_check_at=datetime.now(timezone.utc).isoformat(),
                latency_avg_ms=latency,
                message=message,
                enabled=self.enabled,
                installed=self._sdk_available,
            )
        except asyncio.TimeoutError:
            latency = int((time.perf_counter() - started) * 1000)
            message = f"health check timed out after {check_timeout:g}s"
            return DataSourceHealth(
                adapter_id=self.adapter_id,
                provider=self.provider_name,
                label=self.label,
                capabilities=list(self.capabilities),
                healthy=False,
                upstream_healthy=False,
                live_data_usable=False,
                last_error=message,
                last_check_at=datetime.now(timezone.utc).isoformat(),
                latency_avg_ms=latency,
                message=message,
                enabled=self.enabled,
                installed=self._sdk_available,
            )
        except Exception as exc:
            latency = int((time.perf_counter() - started) * 1000)
            error = _safe_tushare_error(exc)
            logger.exception("Tushare health_check failed")
            return DataSourceHealth(
                adapter_id=self.adapter_id,
                provider=self.provider_name,
                label=self.label,
                capabilities=list(self.capabilities),
                healthy=False,
                upstream_healthy=False,
                live_data_usable=False,
                last_error=error,
                last_check_at=datetime.now(timezone.utc).isoformat(),
                latency_avg_ms=latency,
                message=_tushare_health_failure_message(error),
                enabled=self.enabled,
                installed=self._sdk_available,
            )

    def _sdk_health_check_sync(self, ts_code: str) -> tuple[bool, str]:
        tushare = importlib.import_module("tushare")
        if hasattr(tushare, "set_token"):
            tushare.set_token(self._profile.api_key)
        if not hasattr(tushare, "realtime_quote"):
            raise RuntimeError("Installed Tushare SDK does not provide realtime_quote.")
        frame = tushare.realtime_quote(ts_code=ts_code, src="dc")
        records = _dataframe_to_records(frame)
        healthy = bool(records)
        return healthy, f"OK, {len(records)} records" if healthy else "no records returned"

    def _sina_health_check_sync(self, timeout_seconds: float) -> None:
        _call_tushare_realtime_quote_sina_sync("603663.SH", "sina", timeout_seconds)

    async def _sdk_realtime_quote(self, ts_code: str, src: str) -> MarketDataResponse:
        tushare = importlib.import_module("tushare")
        if hasattr(tushare, "set_token"):
            tushare.set_token(self._profile.api_key)
        if not hasattr(tushare, "realtime_quote"):
            raise RuntimeError("Installed Tushare SDK does not provide realtime_quote.")

        frame = tushare.realtime_quote(ts_code=ts_code, src=src)
        records = _dataframe_to_records(frame)
        if not records:
            raise RuntimeError(f"Tushare realtime_quote returned no rows for {ts_code}.")

        record = records[0]
        price = _coerce_number(record.get("price"))
        pre_close = _coerce_number(record.get("pre_close"))
        change_pct = None
        if price is not None and pre_close not in (None, 0):
            change_pct = (price - pre_close) / pre_close * 100

        return MarketDataResponse(
            symbol=ts_code,
            name=str(record.get("name", "")),
            price=price,
            change_percent=round(change_pct, 2) if change_pct is not None else None,
            volume=_coerce_number(record.get("volume")),
            timestamp=str(record.get("time", record.get("trade_time", ""))),
            source="tushare_sdk",
            provider=self.provider_name,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            freshness=Freshness.REALTIME,
            confidence=0.90,
            data_mode=DataMode.LIVE,
        )

    async def _sina_fallback(self, ts_code: str, src: str) -> MarketDataResponse:
        import asyncio
        result = await asyncio.to_thread(
            _call_tushare_realtime_quote_sina_sync, ts_code, src, self._profile.timeout_seconds
        )
        return result

    async def _call_tushare_http_api(
        self, profile: MarketDataProfile, api_name: str, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        import asyncio
        return await asyncio.to_thread(_call_tushare_http_api_sync, profile, api_name, params)


def _call_tushare_realtime_quote_sina_sync(
    ts_code: str, src: str, timeout_seconds: float
) -> MarketDataResponse:
    sina_symbol = _tushare_to_sina_symbol(ts_code)
    endpoint = f"https://hq.sinajs.cn/list={sina_symbol}"
    request = Request(
        endpoint,
        headers={
            "Accept": "*/*",
            "Referer": "https://finance.sina.com.cn",
            "User-Agent": "Mozilla/5.0",
        },
        method="GET",
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        text = response.read().decode("gb18030", errors="replace")

    match = re.search(r'="(.*)";', text)
    if not match:
        raise RuntimeError(f"Sina realtime fallback returned unexpected response for {ts_code}.")

    values = match.group(1).split(",")
    if len(values) < 32 or not values[0]:
        raise RuntimeError(f"Sina realtime fallback returned no quote row for {ts_code}.")

    price = _coerce_number(values[3])
    pre_close = _coerce_number(values[2])
    change_pct = None
    if price is not None and pre_close not in (None, 0):
        change_pct = (price - pre_close) / pre_close * 100

    return MarketDataResponse(
        symbol=ts_code,
        name=values[0],
        price=price,
        change_percent=round(change_pct, 2) if change_pct is not None else None,
        volume=_coerce_number(values[8]),
        timestamp=f"{values[30]} {values[31]}" if len(values) > 31 else "",
        source="tushare_compatible_sina",
        provider="sina",
        fetched_at=datetime.now(timezone.utc).isoformat(),
        freshness=Freshness.REALTIME,
        confidence=0.70,
        data_mode=DataMode.FALLBACK,
    )


def _call_tushare_http_api_sync(
    profile: MarketDataProfile, api_name: str, params: Dict[str, Any]
) -> Dict[str, Any]:
    assert_market_data_egress_allowed(profile)
    endpoint = profile.base_url or TUSHARE_HTTP_ENDPOINT
    body = {
        "api_name": api_name,
        "token": profile.api_key,
        "params": params,
        "fields": "",
    }
    request = Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            **profile.extra_headers,
        },
        method="POST",
    )
    with urlopen(request, timeout=profile.timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8"))
    code = payload.get("code")
    if code not in (None, 0):
        raise RuntimeError(f"Tushare {api_name} failed with code {code}: {payload.get('msg') or 'unknown error'}")
    payload["source"] = "tushare_http"
    payload["api_name"] = api_name
    payload["params"] = body["params"]
    payload["records"] = _tushare_records_from_payload(payload)
    return payload


def _normalize_tushare_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper().replace("_", ".")
    if not normalized:
        return normalized
    if "." in normalized:
        code, exchange = normalized.split(".", 1)
        return f"{code}.{exchange}"
    compact = re.sub(r"[^0-9A-Z]", "", normalized)
    if compact.startswith(("SH", "SZ", "BJ")) and len(compact) > 2:
        return f"{compact[2:]}.{compact[:2]}"
    digits = re.sub(r"\D", "", compact)
    if len(digits) == 6:
        if digits.startswith(("60", "68", "90", "50", "51", "52", "56", "58", "11", "13")):
            return f"{digits}.SH"
        if digits.startswith(("8", "4", "92")):
            return f"{digits}.BJ"
        return f"{digits}.SZ"
    return normalized


def _tushare_to_sina_symbol(ts_code: str) -> str:
    code, _, exchange = ts_code.partition(".")
    exchange = exchange.lower()
    if exchange == "sh":
        return f"sh{code}"
    if exchange == "sz":
        return f"sz{code}"
    if exchange == "bj":
        return f"bj{code}"
    return code.lower()


def _dataframe_to_records(frame: Any) -> list[Dict[str, Any]]:
    if frame is None:
        return []
    if hasattr(frame, "to_dict"):
        raw_records = frame.to_dict(orient="records")
    elif isinstance(frame, list):
        raw_records = frame
    else:
        raw_records = [frame]
    records: list[Dict[str, Any]] = []
    for item in raw_records:
        if isinstance(item, dict):
            records.append({str(k).strip().lower(): _json_safe_value(v) for k, v in item.items()})
    return records


def _tushare_records_from_payload(payload: Dict[str, Any]) -> list[Dict[str, Any]]:
    if isinstance(payload.get("records"), list):
        return payload["records"]
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    fields = data.get("fields")
    items = data.get("items")
    if not isinstance(fields, list) or not isinstance(items, list):
        return []
    records: list[Dict[str, Any]] = []
    for row in items:
        if isinstance(row, list):
            records.append({
                str(field).strip().lower(): _json_safe_value(value)
                for field, value in zip(fields, row)
            })
    return records


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, float) and value != value:
        return None
    if value is None or isinstance(value, str) or (isinstance(value, (int, float)) and not isinstance(value, bool)):
        return value
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (TypeError, ValueError):
            pass
    return str(value)


def _safe_tushare_error(exc: Exception) -> str:
    message = str(exc).strip()
    if not message:
        return "Tushare 数据获取失败"
    return message[:300]


def _tushare_health_failure_message(error: str) -> str:
    text = str(error or "").strip()
    lower = text.lower()
    if "sina fallback unavailable" in lower:
        return f"Tushare 实时行情主源和 Sina 降级源均不可用：{text}"
    if "remote end closed connection" in lower or "connection aborted" in lower:
        return "Tushare 实时行情上游连接被断开；通常是东财实时接口临时不可用、网络代理拦截或本机到该接口不稳定。"
    if "jsondecodeerror" in lower or "expecting value" in lower:
        return "Tushare 实时行情上游返回了非 JSON 内容；通常是东财实时接口临时不可用或被网络代理拦截。"
    if "does not provide realtime_quote" in lower:
        return "当前 tushare SDK 不支持 realtime_quote，请升级 tushare 后再检测实时行情。"
    return f"Tushare 实时行情健康检查失败：{text or '未知错误'}"


def _tushare_health_fallback_message(error: str) -> str:
    primary = _tushare_health_failure_message(error)
    return f"{primary} 已自动回退到 Sina 实时行情，实时数据仍可用。"


def _coerce_number(value: Any) -> float | None:
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
