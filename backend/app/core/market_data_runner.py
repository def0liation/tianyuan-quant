from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from ..models.agent_runtime import MarketDataConfigTestResult, MarketDataProfile
from ..models.market_data import DataMode
from .agent_runtime_store import (
    get_default_market_data_profile,
    get_market_data_profile,
    record_market_data_profile_test_result,
    test_market_data_profile,
)
from .market_data_egress_policy import (
    MarketDataEgressBlockedError,
    assert_market_data_egress_allowed,
)

logger = logging.getLogger(__name__)


TUSHARE_PROVIDER = "tushare"
TUSHARE_HTTP_ENDPOINT = "https://api.tushare.pro"
TUSHARE_DEFAULT_API_NAME = "realtime_quote"
TUSHARE_DEFAULT_FIELDS = "NAME,TS_CODE,DATE,TIME,OPEN,PRE_CLOSE,PRICE,HIGH,LOW,VOLUME,AMOUNT"
TUSHARE_RESERVED_EXTRA_PARAMS = {"api_name", "fields", "src"}


@dataclass
class MarketDataFetchResult:
    status: str
    provider: str
    profile_id: str
    symbol: str
    quote: Dict[str, Any]
    raw_snapshot: Any = None
    error: str = ""
    latency_ms: int = 0
    fetched_at: str = ""

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "provider": self.provider,
            "profileId": self.profile_id,
            "symbol": self.symbol,
            "quote": self.quote,
            "rawSnapshot": self.raw_snapshot,
            "error": self.error,
            "latencyMs": self.latency_ms,
            "fetchedAt": self.fetched_at,
        }


class MarketDataSourceUnavailable(RuntimeError):
    """Raised when an upstream market-data source is unavailable or malformed."""


async def hydrate_run_with_market_data(
    run_data: Dict[str, Any],
    symbol: str,
) -> Dict[str, Any]:
    if _forced_mock_market_data_enabled():
        return _hydrate_run_with_mock_market_data(run_data, symbol)

    profile = get_default_market_data_profile()
    field_result = test_market_data_profile(profile.id)

    if field_result.status not in {"READY", "CONFIGURED"}:
        run_data["marketData"] = {
            "status": field_result.status,
            "provider": profile.provider,
            "profileId": profile.id,
            "symbol": symbol,
            "quote": {},
            "error": field_result.message,
            "details": field_result.details,
            "fetchedAt": datetime.now(timezone.utc).isoformat(),
        }
        run_data["dataSources"] = _build_data_sources_report(
            MarketDataFetchResult(status="FAILED", provider=profile.provider, profile_id=profile.id, symbol=symbol, quote={}, error=field_result.message or "profile not ready"),
            profile,
        )
        return run_data

    try:
        registry_result = await _try_fetch_via_registry(symbol)
    except Exception:
        registry_result = None

    if registry_result is not None and registry_result.error == "":
        run_data["marketData"] = registry_result.to_public_dict()
        stock_name = registry_result.name or registry_result.symbol
        if registry_result.data_mode in (DataMode.LIVE, DataMode.FALLBACK):
            run_data["stockName"] = str(stock_name)
        auxiliary_results = await _fetch_auxiliary_via_registry(symbol)
        run_data["dataSources"] = _build_enhanced_data_sources_report(
            registry_result, auxiliary_results, profile
        )
        run_data["auxiliaryData"] = auxiliary_results
    else:
        try:
            result = await fetch_market_data(profile, symbol)
        except Exception as exc:
            logger.exception("fetch_market_data failed for %s", symbol)
            result = MarketDataFetchResult(
                status="FAILED",
                provider=profile.provider,
                profile_id=profile.id,
                symbol=symbol,
                quote={},
                error="数据获取失败，请稍后重试",
                fetched_at=datetime.now(timezone.utc).isoformat(),
            )

        run_data["marketData"] = result.to_public_dict()
        stock_name = result.quote.get("name")
        if result.status == "READY" and stock_name:
            run_data["stockName"] = str(stock_name)

        auxiliary_results = await fetch_auxiliary_data_sources(symbol, profile)
        run_data["dataSources"] = _build_data_sources_report(result, profile, auxiliary_results)
        run_data["auxiliaryData"] = auxiliary_results

    _sync_top_level_data_mode(run_data)
    return run_data


def _forced_mock_market_data_enabled() -> bool:
    value = (
        os.getenv("TIANYUAN_FORCE_MOCK_MARKET_DATA", "")
        or os.getenv("TIANYUAN_MARKET_DATA_MODE", "")
    ).strip().lower()
    return value in {"1", "true", "yes", "on", "mock", "smoke"}


def _hydrate_run_with_mock_market_data(run_data: Dict[str, Any], symbol: str) -> Dict[str, Any]:
    fetched_at = datetime.now(timezone.utc).isoformat()
    quote = {
        "name": run_data.get("stockName") or symbol,
        "price": 10.0,
        "open": 10.0,
        "preClose": 10.0,
        "high": 10.0,
        "low": 10.0,
        "changePercent": 0.0,
        "volume": 0,
        "amount": 0,
    }
    run_data["marketData"] = MarketDataFetchResult(
        status="READY",
        provider="MOCK",
        profile_id="smoke_mock_market_data",
        symbol=symbol,
        quote=quote,
        raw_snapshot={"source": "TIANYUAN_FORCE_MOCK_MARKET_DATA"},
        fetched_at=fetched_at,
    ).to_public_dict()
    run_data["dataSources"] = {
        "sources": {
            "realtime_quote": {
                "name": "Mock realtime quote",
                "provider": "MOCK",
                "icon": "BarChart3",
                "status": "READY",
                "detail": "Smoke-safe mock quote; no external market-data request was made.",
                "fetchedAt": fetched_at,
                "available": True,
                "error": "",
                "category": "market",
            }
        },
        "summary": {
            "availableCount": 1,
            "totalCount": 1,
            "availableRatio": "1/1",
            "overallStatus": "READY",
            "overallDataMode": "MOCK",
            "generatedAt": fetched_at,
        },
    }
    run_data["auxiliaryData"] = {}
    run_data["dataMode"] = "MOCK"
    return run_data


def _sync_top_level_data_mode(run_data: Dict[str, Any]) -> None:
    summary = (run_data.get("dataSources") or {}).get("summary") or {}
    overall_mode = summary.get("overallDataMode")
    if overall_mode:
        run_data["dataMode"] = overall_mode


async def _try_fetch_via_registry(symbol: str):
    try:
        from .market_data_adapter import register_default_market_data_adapters

        registry = register_default_market_data_adapters()

        return await registry.fetch_realtime_quote_with_fallback(symbol, fallback_to_mock=False)
    except Exception as exc:
        logger.info("Adapter registry fetch skipped: %s", exc)
        return None


async def _fetch_auxiliary_via_registry(symbol: str) -> Dict[str, Any]:
    try:
        from .market_data_adapter import register_default_market_data_adapters
        from .agent_runtime_store import get_data_sources_config

        registry = register_default_market_data_adapters()
        config = get_data_sources_config()
        config_sources = {s.get("key"): s for s in config.get("sources", [])}
        has_token = bool(config.get("tushare_token", ""))
        results: Dict[str, Any] = {}
        for category in ["fundamentals", "announcements", "moneyflow", "chip", "macro"]:
            cfg = config_sources.get(category, {})
            if not bool(cfg.get("enabled", False)) or not has_token:
                continue
            try:
                aux_result = await registry.fetch_auxiliary_with_fallback(
                    symbol, category, fallback_to_mock=False
                )
                results[category] = {
                    "status": "READY" if aux_result.error == "" else "FAILED",
                    "record_count": aux_result.record_count,
                    "sample": aux_result.records[0] if aux_result.records else None,
                    "records": aux_result.records,
                    "error": aux_result.error,
                    "provider": aux_result.provider,
                    "freshness": aux_result.freshness.value,
                    "confidence": aux_result.confidence,
                    "dataMode": aux_result.data_mode.value,
                    "extra": aux_result.extra,
                    "arbitration": aux_result.extra.get("arbitration"),
                    "configured": True,
                    "degradationChain": [
                        step.to_public_dict() if hasattr(step, "to_public_dict") else step for step in aux_result.degradation_chain
                    ],
                }
            except Exception as exc:
                logger.exception("fetch_auxiliary_via_registry failed for %s", category)
                results[category] = {
                    "status": "FAILED",
                    "record_count": 0,
                    "sample": None,
                    "error": "数据获取失败，请稍后重试",
                    "configured": True,
                }
        special_cfg = config_sources.get("special_data", {})
        if bool(special_cfg.get("enabled", False)) and has_token and "stk_factor" in str(special_cfg.get("tushare_api", "")):
            try:
                results["special_data"] = await _fetch_tushare_stk_factor_data(
                    symbol,
                    get_default_market_data_profile(),
                )
            except Exception:
                logger.exception("fetch_auxiliary_via_registry failed for special_data")
                results["special_data"] = {
                    "status": "FAILED",
                    "record_count": 0,
                    "sample": None,
                    "error": "数据获取失败，请稍后重试",
                    "configured": True,
                }
        return results
    except Exception:
        return {}


async def test_market_data_profile_connection(
    profile_id: str,
    live_call: bool = False,
    symbol: str | None = None,
) -> MarketDataConfigTestResult:
    field_result = test_market_data_profile(profile_id)
    if not live_call or field_result.status not in {"READY", "CONFIGURED"}:
        record_market_data_profile_test_result(profile_id, field_result, live_call=False)
        return field_result

    try:
        profile = get_market_data_profile(profile_id)
    except KeyError:
        return MarketDataConfigTestResult(
            profile_id=profile_id,
            status="NOT_FOUND",
            message="Market data profile does not exist.",
        )

    test_symbol = symbol or "603663"
    result = await fetch_market_data(profile, test_symbol)
    if result.status != "READY":
        failed = MarketDataConfigTestResult(
            profile_id=profile_id,
            status=result.status,
            message="Live market data connection failed.",
            details={
                "error": result.error,
                "provider": result.provider,
                "symbol": test_symbol,
                "latency_ms": result.latency_ms,
                "live_call": True,
            },
        )
        record_market_data_profile_test_result(profile_id, failed, live_call=True)
        return failed

    succeeded = MarketDataConfigTestResult(
        profile_id=profile_id,
        status="READY",
        message=f"Live market data connection succeeded for sample symbol {test_symbol}.",
        details={
            "provider": result.provider,
            "symbol": test_symbol,
            "quote": result.quote,
            "latency_ms": result.latency_ms,
            "live_call": True,
        },
    )
    record_market_data_profile_test_result(profile_id, succeeded, live_call=True)
    return succeeded


_MARKET_DATA_CACHE: Dict[str, Dict[str, Any]] = {}
_MARKET_DATA_CACHE_TTL = 30


async def fetch_market_data(
    profile: MarketDataProfile,
    symbol: str,
) -> MarketDataFetchResult:
    cache_key = f"{profile.id}:{_market_data_profile_cache_fingerprint(profile)}:{symbol}"
    cached = _MARKET_DATA_CACHE.get(cache_key)
    if cached and (time.time() - cached.get("_cached_at", 0)) < _MARKET_DATA_CACHE_TTL:
        return MarketDataFetchResult(**{k: v for k, v in cached.items() if k != "_cached_at"})

    started = time.perf_counter()
    try:
        response = await asyncio.to_thread(_call_market_data_profile, profile, symbol)
    except MarketDataEgressBlockedError as exc:
        result = MarketDataFetchResult(
            status="BLOCKED",
            provider=profile.provider,
            profile_id=profile.id,
            symbol=symbol,
            quote={},
            error=exc.decision.message,
            latency_ms=int((time.perf_counter() - started) * 1000),
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )
        _record_market_data_fetch_health(profile, result)
        return result
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError, MarketDataSourceUnavailable) as exc:
        error_message = _format_market_data_source_error(exc)
        logger.warning(
            "market data source unavailable for %s via %s: %s",
            symbol,
            profile.provider,
            error_message,
        )
        result = MarketDataFetchResult(
            status="FAILED",
            provider=profile.provider,
            profile_id=profile.id,
            symbol=symbol,
            quote={},
            error=error_message,
            latency_ms=int((time.perf_counter() - started) * 1000),
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )
        _record_market_data_fetch_health(profile, result)
        return result
    except Exception as exc:
        logger.exception("fetch_market_data internal failed for %s", symbol)
        result = MarketDataFetchResult(
            status="FAILED",
            provider=profile.provider,
            profile_id=profile.id,
            symbol=symbol,
            quote={},
            error="数据获取失败，请稍后重试",
            latency_ms=int((time.perf_counter() - started) * 1000),
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )
        _record_market_data_fetch_health(profile, result)
        return result

    result = MarketDataFetchResult(
        status="READY",
        provider=profile.provider,
        profile_id=profile.id,
        symbol=symbol,
        quote=_normalize_quote(profile, symbol, response),
        raw_snapshot=_safe_raw_snapshot(response),
        latency_ms=int((time.perf_counter() - started) * 1000),
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )
    _MARKET_DATA_CACHE[cache_key] = {**result.__dict__, "_cached_at": time.time()}
    _record_market_data_fetch_health(profile, result)
    return result


def _record_market_data_fetch_health(profile: MarketDataProfile, result: MarketDataFetchResult) -> None:
    try:
        get_market_data_profile(profile.id)
    except KeyError:
        return

    details: Dict[str, Any] = {
        "provider": result.provider,
        "symbol": result.symbol,
        "latency_ms": result.latency_ms,
        "live_call": True,
    }
    if result.error:
        details["error"] = result.error
    if result.quote:
        details["quote_source"] = result.quote.get("source") or result.quote.get("provider") or result.provider
        details["quote_timestamp"] = result.quote.get("timestamp") or result.quote.get("date") or result.fetched_at
    record_market_data_profile_test_result(
        profile.id,
        MarketDataConfigTestResult(
            profile_id=profile.id,
            status=result.status,
            message=(
                f"Live market data connection succeeded for {result.symbol}."
                if result.status == "READY"
                else result.error or "Live market data connection failed."
            ),
            details=details,
        ),
        live_call=True,
    )


def _market_data_profile_cache_fingerprint(profile: MarketDataProfile) -> str:
    payload = {
        "provider": profile.provider,
        "base_url": profile.base_url,
        "quote_path": profile.quote_path,
        "symbol_query_param": profile.symbol_query_param,
        "auth_mode": profile.auth_mode,
        "api_key_hash": hashlib.sha256(profile.api_key.encode("utf-8")).hexdigest()[:12] if profile.api_key else "",
        "api_key_header": profile.api_key_header,
        "api_key_query_param": profile.api_key_query_param,
        "enabled": profile.enabled,
        "extra_query_params": profile.extra_query_params,
        "price_path": profile.price_path,
        "name_path": profile.name_path,
        "change_percent_path": profile.change_percent_path,
        "volume_path": profile.volume_path,
        "timestamp_path": profile.timestamp_path,
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _call_market_data_profile(profile: MarketDataProfile, symbol: str) -> Any:
    if profile.provider.lower() == TUSHARE_PROVIDER:
        assert_market_data_egress_allowed(profile)
        return _call_tushare_profile(profile, symbol)

    endpoint = _market_data_endpoint(profile, symbol)
    assert_market_data_egress_allowed(profile, endpoint=endpoint)
    headers = {
        "Accept": "application/json",
        **profile.extra_headers,
    }

    auth_mode = profile.auth_mode.lower()
    if profile.api_key and auth_mode == "bearer":
        headers["Authorization"] = f"Bearer {profile.api_key}"
    elif profile.api_key and auth_mode == "header":
        headers[profile.api_key_header or "Authorization"] = profile.api_key

    request = Request(endpoint, headers=headers, method="GET")
    with urlopen(request, timeout=profile.timeout_seconds) as response:
        body = response.read().decode("utf-8")
    return json.loads(body)


def _call_tushare_profile(profile: MarketDataProfile, symbol: str) -> Any:
    api_name = str(profile.extra_query_params.get("api_name") or TUSHARE_DEFAULT_API_NAME).strip()
    if not profile.api_key:
        raise RuntimeError("Tushare token is missing. Save the token in the market data profile first.")

    if api_name == "realtime_quote":
        return _call_tushare_realtime_quote_sdk(profile, symbol)
    return _call_tushare_http_api(profile, symbol, api_name)


def _call_tushare_realtime_quote_sdk(profile: MarketDataProfile, symbol: str) -> Dict[str, Any]:
    ts_code = _normalize_tushare_symbol(symbol)
    src = str(profile.extra_query_params.get("src") or "dc").strip() or "dc"

    try:
        tushare = importlib.import_module("tushare")
    except ImportError as exc:
        return _call_tushare_realtime_quote_sina(
            ts_code,
            requested_src=src,
            fallback_reason="tushare_sdk_missing",
            timeout_seconds=profile.timeout_seconds,
        )

    if hasattr(tushare, "set_token"):
        tushare.set_token(profile.api_key)
    if not hasattr(tushare, "realtime_quote"):
        raise RuntimeError("Installed Tushare SDK does not provide realtime_quote. Upgrade tushare to 1.3.3 or newer.")

    try:
        frame = tushare.realtime_quote(ts_code=ts_code, src=src)
        records = _dataframe_to_records(frame)
        if not records:
            raise RuntimeError(f"Tushare realtime_quote returned no rows for {ts_code}.")

        fields = list(records[0].keys())
        return {
            "source": "tushare_sdk",
            "api_name": "realtime_quote",
            "params": {"ts_code": ts_code, "src": src},
            "records": records,
            "data": {
                "fields": fields,
                "items": [[record.get(field) for field in fields] for record in records],
            },
        }
    except Exception as exc:
        logger.warning(
            "tushare realtime_quote unavailable for %s; falling back to Sina: %s",
            ts_code,
            _safe_source_error(exc),
        )
        return _call_tushare_realtime_quote_sina(
            ts_code,
            requested_src=src,
            fallback_reason="tushare_sdk_error",
            timeout_seconds=profile.timeout_seconds,
        )


def _call_tushare_realtime_quote_sina(
    ts_code: str,
    requested_src: str,
    fallback_reason: str,
    timeout_seconds: int,
) -> Dict[str, Any]:
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
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            text = response.read().decode("gb18030", errors="replace")
    except Exception as exc:
        logger.warning(
            "tushare sina fallback unavailable for %s: %s",
            ts_code,
            _safe_source_error(exc),
        )
        raise MarketDataSourceUnavailable(
            "Tushare SDK 与新浪行情均无法连接，请检查网络环境或稍后重试"
        )

    match = re.search(r'="(.*)";', text)
    if not match:
        raise RuntimeError(f"Sina realtime fallback returned an unexpected response for {ts_code}.")

    values = match.group(1).split(",")
    if len(values) < 32 or not values[0]:
        raise RuntimeError(f"Sina realtime fallback returned no quote row for {ts_code}.")

    record = _sina_realtime_record(ts_code, values)
    fields = list(record.keys())
    return {
        "source": "tushare_compatible_sina",
        "api_name": "realtime_quote",
        "params": {
            "ts_code": ts_code,
            "src": "sina",
            "requested_src": requested_src,
            "fallback_reason": fallback_reason,
        },
        "records": [record],
        "data": {
            "fields": fields,
            "items": [[record.get(field) for field in fields]],
        },
    }


def _sina_realtime_record(ts_code: str, values: list[str]) -> Dict[str, Any]:
    record = {
        "name": values[0],
        "ts_code": ts_code,
        "open": values[1],
        "pre_close": values[2],
        "price": values[3],
        "high": values[4],
        "low": values[5],
        "bid": values[6],
        "ask": values[7],
        "volume": values[8],
        "amount": values[9],
        "date": values[30],
        "time": values[31],
    }
    bid_offset = 10
    ask_offset = 20
    for level in range(1, 6):
        record[f"b{level}_v"] = values[bid_offset + (level - 1) * 2]
        record[f"b{level}_p"] = values[bid_offset + (level - 1) * 2 + 1]
        record[f"a{level}_v"] = values[ask_offset + (level - 1) * 2]
        record[f"a{level}_p"] = values[ask_offset + (level - 1) * 2 + 1]
    return {_normalize_tushare_record_key(key): _json_safe_value(value) for key, value in record.items()}


def _call_tushare_http_api(profile: MarketDataProfile, symbol: str, api_name: str) -> Dict[str, Any]:
    endpoint = profile.base_url or TUSHARE_HTTP_ENDPOINT
    if profile.quote_path.startswith("http://") or profile.quote_path.startswith("https://"):
        endpoint = profile.quote_path
    elif profile.quote_path:
        endpoint = f"{endpoint.rstrip('/')}/{profile.quote_path.lstrip('/')}"
    assert_market_data_egress_allowed(profile, endpoint=endpoint)

    body = {
        "api_name": api_name,
        "token": profile.api_key,
        "params": _tushare_params(profile, symbol, api_name),
        "fields": str(profile.extra_query_params.get("fields") or "").strip(),
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
        raise MarketDataSourceUnavailable(
            f"Tushare {api_name} failed with code {code}: {payload.get('msg') or 'unknown error'}"
        )

    payload["source"] = "tushare_http"
    payload["api_name"] = api_name
    payload["params"] = body["params"]
    payload["records"] = _tushare_records_from_payload(payload)
    return payload


def _tushare_params(profile: MarketDataProfile, symbol: str, api_name: str) -> Dict[str, Any]:
    params = {
        key: value
        for key, value in profile.extra_query_params.items()
        if key not in TUSHARE_RESERVED_EXTRA_PARAMS
    }
    symbol_key = profile.symbol_query_param or "ts_code"
    if symbol_key:
        params[symbol_key] = _normalize_tushare_symbol(symbol)
    if api_name in {"rt_min", "rt_min_daily"} and "freq" not in params:
        params["freq"] = "1MIN"
    return params


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
            records.append({_normalize_tushare_record_key(key): _json_safe_value(value) for key, value in item.items()})
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
                _normalize_tushare_record_key(field): _json_safe_value(value)
                for field, value in zip(fields, row)
            })
    return records


def _market_data_endpoint(profile: MarketDataProfile, symbol: str) -> str:
    if profile.quote_path.startswith("http://") or profile.quote_path.startswith("https://"):
        endpoint = profile.quote_path
    elif profile.quote_path:
        endpoint = f"{profile.base_url.rstrip('/')}/{profile.quote_path.lstrip('/')}"
    else:
        endpoint = profile.base_url

    encoded_symbol = quote(symbol, safe="")
    symbol_is_path_param = "{symbol}" in endpoint
    endpoint = endpoint.replace("{symbol}", encoded_symbol)

    split = urlsplit(endpoint)
    query = dict(parse_qsl(split.query, keep_blank_values=True))
    query.update({key: str(value) for key, value in profile.extra_query_params.items()})
    if not symbol_is_path_param and profile.symbol_query_param:
        query[profile.symbol_query_param] = symbol
    if profile.api_key and profile.auth_mode.lower() == "query":
        query[profile.api_key_query_param or "apikey"] = profile.api_key

    return urlunsplit(
        (
            split.scheme,
            split.netloc,
            split.path,
            urlencode(query),
            split.fragment,
        )
    )


def _normalize_quote(
    profile: MarketDataProfile,
    symbol: str,
    response: Any,
) -> Dict[str, Any]:
    if profile.provider.lower() == TUSHARE_PROVIDER:
        return _normalize_tushare_quote(symbol, response)

    return {
        "symbol": _first_value(response, [profile.symbol_query_param, "symbol", "ticker", "code"]) or symbol,
        "name": _path_or_common(response, profile.name_path, ["name", "stockName", "shortName", "securityName"]),
        "price": _coerce_number(
            _path_or_common(
                response,
                profile.price_path,
                ["price", "last", "lastPrice", "latestPrice", "current", "close", "c", "p"],
            )
        ),
        "changePercent": _coerce_number(
            _path_or_common(
                response,
                profile.change_percent_path,
                ["changePercent", "percent", "pctChg", "change_rate", "dp"],
            )
        ),
        "volume": _coerce_number(
            _path_or_common(response, profile.volume_path, ["volume", "vol", "v", "成交量"])
        ),
        "timestamp": _path_or_common(
            response,
            profile.timestamp_path,
            ["timestamp", "time", "datetime", "date", "t"],
        ),
    }


def _normalize_tushare_quote(symbol: str, response: Any) -> Dict[str, Any]:
    record = _first_record(response)
    ts_code = _value_by_keys(record, ["ts_code", "code"]) or _normalize_tushare_symbol(symbol)
    price = _coerce_number(_value_by_keys(record, ["price", "close", "last", "current"]))
    pre_close = _coerce_number(_value_by_keys(record, ["pre_close", "preclose", "y_close"]))
    change = _coerce_number(_value_by_keys(record, ["change"]))
    if change is None and price is not None and pre_close not in (None, 0):
        change = price - pre_close

    change_percent = _coerce_number(_value_by_keys(record, ["pct_change", "pct_chg", "change_percent"]))
    if change_percent is None and change is not None and pre_close not in (None, 0):
        change_percent = (change / pre_close) * 100

    quote = {
        "symbol": ts_code,
        "name": _value_by_keys(record, ["name", "stock_name", "security_name"]),
        "price": price,
        "change": change,
        "changePercent": change_percent,
        "open": _coerce_number(_value_by_keys(record, ["open"])),
        "high": _coerce_number(_value_by_keys(record, ["high"])),
        "low": _coerce_number(_value_by_keys(record, ["low"])),
        "preClose": pre_close,
        "volume": _coerce_number(_value_by_keys(record, ["volume", "vol"])),
        "amount": _coerce_number(_value_by_keys(record, ["amount"])),
        "bid": _coerce_number(_value_by_keys(record, ["bid", "b1_p"])),
        "ask": _coerce_number(_value_by_keys(record, ["ask", "a1_p"])),
        "timestamp": _tushare_timestamp(record),
    }
    if isinstance(response, dict):
        quote["apiName"] = response.get("api_name")
        quote["source"] = response.get("source")
    return quote


def _first_record(payload: Any) -> Dict[str, Any]:
    records = _tushare_records_from_payload(payload) if isinstance(payload, dict) else []
    if records:
        return records[0]
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        return payload[0]
    if isinstance(payload, dict):
        return payload
    return {}


def _value_by_keys(record: Dict[str, Any], keys: Iterable[str]) -> Any:
    normalized = {_normalize_key(key) for key in keys}
    for key, value in record.items():
        if _normalize_key(str(key)) in normalized:
            return value
    return None


def _tushare_timestamp(record: Dict[str, Any]) -> Any:
    timestamp = _value_by_keys(record, ["trade_time", "datetime", "timestamp"])
    if timestamp:
        return timestamp

    date = _value_by_keys(record, ["date", "trade_date"])
    time_value = _value_by_keys(record, ["time"])
    if date and time_value:
        return f"{date} {time_value}"
    return date or time_value


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


def _normalize_tushare_record_key(key: Any) -> str:
    return str(key).strip().lower()


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


def _path_or_common(response: Any, path: str, keys: Iterable[str]) -> Any:
    if path:
        value = _extract_path(response, path)
        if value is not None:
            return value
    return _first_value(response, keys)


def _extract_path(payload: Any, path: str) -> Any:
    if not path:
        return None
    parts = [part for part in path.strip().strip("/").split("/") if part] if path.startswith("/") else path.split(".")
    current = payload
    for raw_part in parts:
        part = raw_part.strip()
        if isinstance(current, list):
            if not part.isdigit():
                return None
            index = int(part)
            if index >= len(current):
                return None
            current = current[index]
        elif isinstance(current, dict):
            if part not in current:
                return None
            current = current[part]
        else:
            return None
    return current


def _first_value(payload: Any, keys: Iterable[str]) -> Any:
    normalized_keys = {_normalize_key(key) for key in keys if key}
    if isinstance(payload, dict):
        for key, value in payload.items():
            if _normalize_key(str(key)) in normalized_keys:
                return value
        for value in payload.values():
            found = _first_value(value, keys)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _first_value(item, keys)
            if found is not None:
                return found
    return None


def _normalize_key(key: str) -> str:
    return "".join(character for character in key.lower() if character.isalnum())


def _coerce_number(value: Any) -> Optional[float]:
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


def _safe_raw_snapshot(response: Any) -> Any:
    try:
        serialized = json.dumps(response, ensure_ascii=False)
    except TypeError:
        return str(response)[:6000]
    if len(serialized) <= 6000:
        return response
    return serialized[:6000] + "...[truncated]"


def _format_transport_error(exc: BaseException) -> str:
    if isinstance(exc, HTTPError):
        body = exc.read().decode("utf-8", errors="replace")
        return f"HTTP {exc.code}: {body[:500]}"
    return "网络请求失败，请稍后重试"


def _format_market_data_source_error(exc: BaseException) -> str:
    if isinstance(exc, MarketDataSourceUnavailable):
        message = _safe_source_error(exc)
        if "Tushare SDK" in message:
            return "Tushare SDK 与新浪行情均无法连接，请检查网络环境或稍后重试"
        return message or "行情源暂不可用，请稍后重试"
    if isinstance(exc, json.JSONDecodeError):
        return "行情源返回了非 JSON 响应，请稍后重试"
    if isinstance(exc, (HTTPError, URLError, TimeoutError, OSError)):
        return _format_transport_error(exc)
    return _safe_source_error(exc)


def _safe_source_error(exc: BaseException) -> str:
    message = str(exc).strip()
    if message:
        return message[:500]
    return exc.__class__.__name__


async def fetch_auxiliary_data_sources(
    symbol: str,
    profile: MarketDataProfile,
) -> Dict[str, Any]:
    """Fetch enabled auxiliary data sources used by Data Reliability Engine and Quant Engine."""
    from .agent_runtime_store import get_data_sources_config

    config = get_data_sources_config()
    config_sources = {s.get("key"): s for s in config.get("sources", [])}
    has_token = bool(config.get("tushare_token", ""))
    ts_code = _normalize_tushare_symbol(symbol)

    results: Dict[str, Any] = {}

    for key, api_name, params_builder in [
        ("fundamentals", "income_vip", lambda: {"ts_code": ts_code, "period": "20241231"}),
        ("announcements", "disclosure_date", lambda: {"ts_code": ts_code}),
        ("moneyflow", "moneyflow_mkt_dc", lambda: {"ts_code": ts_code, "trade_date": "20250102"}),
        ("chip", "cyq_perf/cyq_chips", lambda: {"ts_code": ts_code}),
        ("macro", "cn_cpi", lambda: {}),
        ("special_data", "stk_factor", lambda: {}),
    ]:
        cfg = config_sources.get(key, {})
        enabled = bool(cfg.get("enabled", False))
        if not enabled or not has_token:
            continue
        try:
            if key == "special_data":
                results[key] = await _fetch_tushare_stk_factor_data(symbol, profile)
            elif key == "chip":
                from .tushare_chip_service import fetch_tushare_chip_payload

                chip_payload = await asyncio.to_thread(
                    fetch_tushare_chip_payload,
                    profile,
                    symbol,
                    "3m",
                    use_cache=False,
                )
                chip_records = list(chip_payload.get("perfRows") or []) + list(chip_payload.get("chipRows") or [])
                results[key] = {
                    "status": "READY" if chip_payload.get("status") == "READY" else "FAILED",
                    "provider": "tushare",
                    "source": chip_payload.get("source", "tushare_http"),
                    "api_name": "cyq_perf/cyq_chips",
                    "record_count": len(chip_records),
                    "sample": chip_payload.get("latestPerf") or (chip_records[0] if chip_records else None),
                    "records": chip_records,
                    "error": chip_payload.get("error", ""),
                    "dataMode": chip_payload.get("dataMode", "UNAVAILABLE"),
                    "freshness": "EOD",
                    "confidence": 0.9 if chip_payload.get("status") == "READY" and not chip_payload.get("error") else 0.72,
                    "extra": chip_payload,
                }
            else:
                result = await asyncio.to_thread(
                    _call_tushare_http_api_raw,
                    profile,
                    api_name,
                    params_builder(),
                )
                records = _tushare_records_from_payload(result)
                results[key] = {
                    "status": "READY",
                    "record_count": len(records),
                    "sample": records[0] if records else None,
                    "records": records,
                    "error": "",
                }
        except Exception as exc:
            logger.exception("fetch_auxiliary_data_sources failed for %s", key)
            results[key] = {
                "status": "FAILED",
                "record_count": 0,
                "sample": None,
                "error": "数据获取失败，请稍后重试",
            }

    return results


async def _fetch_tushare_stk_factor_data(
    symbol: str,
    profile: MarketDataProfile,
) -> Dict[str, Any]:
    ts_code = _normalize_tushare_symbol(symbol)
    today = datetime.now(timezone.utc).date()
    params = {
        "ts_code": ts_code,
        "start_date": (today - timedelta(days=45)).strftime("%Y%m%d"),
        "end_date": today.strftime("%Y%m%d"),
    }
    result = await asyncio.to_thread(
        _call_tushare_http_api_raw,
        profile,
        "stk_factor",
        params,
    )
    records = _tushare_records_from_payload(result)
    fetched_at = datetime.now(timezone.utc).isoformat()
    return {
        "status": "READY" if records else "FAILED",
        "record_count": len(records),
        "sample": records[0] if records else None,
        "records": records,
        "error": "" if records else "Tushare stk_factor returned no records",
        "provider": "tushare",
        "source": "tushare_http",
        "api_name": "stk_factor",
        "configured": True,
        "fetchedAt": fetched_at,
        "freshness": "EOD",
        "confidence": 0.88 if records else 0.0,
        "dataMode": "LIVE" if records else "MOCK",
        "params": params,
    }


def _call_tushare_http_api_raw(
    profile: MarketDataProfile,
    api_name: str,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    endpoint = profile.base_url or TUSHARE_HTTP_ENDPOINT
    assert_market_data_egress_allowed(profile, endpoint=endpoint)
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


def _build_data_sources_report(
    quote_result: MarketDataFetchResult,
    profile: Any,
    auxiliary_results: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    from .agent_runtime_store import get_data_sources_config

    now = datetime.now(timezone.utc).isoformat()
    provider = profile.provider if hasattr(profile, "provider") else "tushare"
    config = get_data_sources_config()
    config_sources = {s.get("key"): s for s in config.get("sources", [])}
    has_token = bool(config.get("tushare_token", ""))
    aux = auxiliary_results or {}

    def _source(key: str, name: str, icon: str, category: str, api_name: str, detail_ready: str, detail_disabled: str) -> Dict[str, Any]:
        cfg = config_sources.get(key, {})
        enabled = bool(cfg.get("enabled", False))
        if key == "realtime_quote":
            status = quote_result.status if quote_result.status == "READY" else "FAILED"
            detail = "逐笔成交实时推送" if status == "READY" else ("拉取失败" if quote_result.error else "未配置或网络不通")
            available = status == "READY"
            error = quote_result.error if status != "READY" else ""
        elif key in aux:
            aux_result = aux[key]
            status = "READY" if aux_result.get("status") == "READY" else "FAILED"
            record_count = aux_result.get("record_count", 0)
            detail = f"成功获取 {record_count} 条记录" if status == "READY" else f"拉取失败: {aux_result.get('error', '未知错误')}"
            available = status == "READY"
            error = aux_result.get("error", "")
        elif enabled and has_token:
            status = "NOT_CONFIGURED"
            detail = f"已启用 tushare {api_name} 接口，待下次运行任务时拉取"
            available = False
            error = ""
        elif enabled and not has_token:
            status = "NOT_CONFIGURED"
            detail = "已启用但未设置 tushare token，请先在设置中填写 token"
            available = False
            error = "missing token"
        else:
            status = "NOT_CONFIGURED"
            detail = detail_disabled
            available = False
            error = ""

        return {
            "name": name,
            "provider": provider,
            "icon": icon,
            "status": status,
            "detail": detail,
            "fetchedAt": quote_result.fetched_at if key == "realtime_quote" else now,
            "available": available,
            "error": error,
            "category": category,
        }

    sources = {
        "realtime_quote": _source("realtime_quote", "实时行情", "BarChart3", "行情", "realtime_quote", "逐笔成交实时推送", "暂未启用"),
        "fundamentals": _source("fundamentals", "财务数据", "FileText", "基本面", "income_vip", "tushare 财务数据", "暂未启用，使用模拟季报数据"),
        "announcements": _source("announcements", "公告数据", "Clock", "消息面", "disclosure_date", "tushare 财报披露计划", "暂未启用，使用 Mock 近 30 日公告"),
        "moneyflow": _source("moneyflow", "资金流向", "Layers", "资金面", "moneyflow_mkt_dc", "tushare 资金流数据", "暂未启用，缺少主力资金数据"),
        "chip": _source("chip", "筹码分布", "Target", "筹码面", "cyq_perf/cyq_chips", "tushare 每日筹码及胜率 / 每日筹码分布", "暂未启用，真实筹码接口不可用时仅使用 K 线代理估算"),
        "macro": _source("macro", "宏观指标", "Gauge", "宏观面", "cn_cpi/cn_gdp/shibor_lpr", "tushare 宏观指标", "暂未启用，宏观指标不展示模板值"),
        "special_data": _source("special_data", "特色因子数据", "Cpu", "因子面", "stk_factor", "tushare stk_factor", "暂未启用，量化因子使用规则推算"),
    }

    source_list = list(sources.values())
    available_count = sum(1 for s in source_list if s["available"])
    total_count = len(source_list)

    return {
        "sources": sources,
        "summary": {
            "availableCount": available_count,
            "totalCount": total_count,
            "availableRatio": f"{available_count}/{total_count}",
            "overallStatus": "PARTIAL" if 0 < available_count < total_count else ("READY" if available_count == total_count else "ALL_MOCK"),
            "generatedAt": now,
        },
    }


def _chain_error_summary(chain: Any) -> str:
    if not isinstance(chain, list):
        return ""
    parts: list[str] = []
    for step in chain:
        if not isinstance(step, dict):
            continue
        if step.get("success"):
            continue
        error = step.get("error")
        if error:
            parts.append(f"{step.get('provider') or step.get('adapterId') or step.get('adapter_id')}: {error}")
    return "；".join(parts[:2])


def _build_enhanced_data_sources_report(
    quote_result: Any,
    auxiliary_results: Dict[str, Any],
    profile: Any,
) -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    provider = getattr(profile, "provider", "tushare")
    degradation_chain = getattr(quote_result, "degradation_chain", [])
    chain_dicts = [step.model_dump() if hasattr(step, "model_dump") else step for step in degradation_chain]
    quote_freshness = getattr(quote_result, "freshness", None)
    quote_freshness_str = quote_freshness.value if hasattr(quote_freshness, "value") else str(quote_freshness or "")
    quote_confidence = getattr(quote_result, "confidence", None)
    quote_extra = getattr(quote_result, "extra", {}) or {}
    aux = auxiliary_results or {}

    def _source(key: str, name: str, icon: str, category: str) -> Dict[str, Any]:
        if key == "realtime_quote":
            status = getattr(quote_result, "data_mode", None)
            status_str = status.value if hasattr(status, "value") else str(status or "")
            has_error = bool(getattr(quote_result, "error", ""))
            available = not has_error and status_str in ("LIVE", "FALLBACK", "MIXED")
            return {
                "name": name,
                "provider": getattr(quote_result, "provider", provider),
                "icon": icon,
                "status": "READY" if available else "FAILED",
                "detail": f"源: {getattr(quote_result, 'source', 'unknown')}" if available else (getattr(quote_result, "error", "") or "拉取失败"),
                "fetchedAt": getattr(quote_result, "fetched_at", now),
                "available": available,
                "error": getattr(quote_result, "error", ""),
                "category": category,
                "dataMode": status_str,
                "freshness": quote_freshness_str,
                "confidence": quote_confidence,
                "degradationChain": chain_dicts,
                "extra": quote_extra,
                "arbitration": quote_extra.get("arbitration"),
            }
        elif key in aux:
            aux_result = aux[key]
            aux_status = aux_result.get("status", "")
            available = aux_status == "READY" and not aux_result.get("error")
            record_count = aux_result.get("record_count", 0)
            chain_summary = _chain_error_summary(aux_result.get("degradationChain", []))
            detail = (
                f"成功获取 {record_count} 条记录"
                if available
                else f"本标的拉取失败: {chain_summary or aux_result.get('error', '未知错误')}"
            )
            return {
                "name": name,
                "provider": aux_result.get("provider", provider),
                "icon": icon,
                "status": aux_status if aux_status == "READY" else "FAILED",
                "detail": detail,
                "fetchedAt": now,
                "available": available,
                "error": aux_result.get("error", ""),
                "category": category,
                "dataMode": aux_result.get("dataMode", "MOCK"),
                "freshness": aux_result.get("freshness", ""),
                "confidence": aux_result.get("confidence", None),
                "degradationChain": aux_result.get("degradationChain", []),
                "extra": aux_result.get("extra", {}),
                "arbitration": aux_result.get("arbitration") or (aux_result.get("extra", {}) or {}).get("arbitration"),
            }
        else:
            return {
                "name": name,
                "provider": provider,
                "icon": icon,
                "status": "NOT_CONFIGURED",
                "detail": "暂未启用",
                "fetchedAt": now,
                "available": False,
                "error": "",
                "category": category,
                "dataMode": "MOCK",
                "freshness": "",
                "confidence": None,
                "degradationChain": [],
            }

    sources = {
        "realtime_quote": _source("realtime_quote", "实时行情", "BarChart3", "行情"),
        "fundamentals": _source("fundamentals", "财务数据", "FileText", "基本面"),
        "announcements": _source("announcements", "公告数据", "Clock", "消息面"),
        "moneyflow": _source("moneyflow", "资金流向", "Layers", "资金面"),
        "chip": _source("chip", "筹码分布", "Target", "筹码面"),
        "macro": _source("macro", "宏观指标", "Gauge", "宏观面"),
        "special_data": _source("special_data", "特色因子数据", "Cpu", "因子面"),
    }

    source_list = list(sources.values())
    available_count = sum(1 for s in source_list if s["available"])
    total_count = len(source_list)
    data_modes = {s.get("dataMode", "MOCK") for s in source_list}
    arbitrations = [s.get("arbitration") for s in source_list if s.get("arbitration")]
    arbitration_conflicts = []
    for arbitration in arbitrations:
        if isinstance(arbitration, dict):
            arbitration_conflicts.extend(arbitration.get("conflicts", []))
    arbitration_review_only = any(
        bool((arbitration.get("dataQuality") or {}).get("reviewOnly"))
        for arbitration in arbitrations
        if isinstance(arbitration, dict)
    )
    overall_data_mode: str
    if data_modes == {"LIVE"}:
        overall_data_mode = "LIVE"
    elif "LIVE" in data_modes or "FALLBACK" in data_modes:
        overall_data_mode = "MIXED"
    else:
        overall_data_mode = "MOCK"

    return {
        "sources": sources,
        "summary": {
            "availableCount": available_count,
            "totalCount": total_count,
            "availableRatio": f"{available_count}/{total_count}",
            "overallStatus": "READY" if available_count == total_count else ("PARTIAL" if available_count > 0 else "ALL_MOCK"),
            "overallDataMode": overall_data_mode,
            "arbitration": {
                "reviewOnly": arbitration_review_only,
                "conflictCount": len(arbitration_conflicts),
                "conflicts": arbitration_conflicts,
            },
            "generatedAt": now,
        },
    }
