from __future__ import annotations

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List

from ..models.agent_runtime import MarketDataProfile
from .agent_runtime_store import get_default_market_data_profile
from .market_data_runner import (
    _call_tushare_http_api_raw,
    _normalize_tushare_symbol,
    _tushare_records_from_payload,
)


_CHIP_CACHE: Dict[str, Dict[str, Any]] = {}
_CHIP_CACHE_TTL = 90
_CHIP_HTTP_TIMEOUT_SECONDS = 8
_CHIP_TOTAL_BUDGET_SECONDS = 9


def get_tushare_chip_payload(symbol: str, range_: str = "3m") -> Dict[str, Any]:
    profile = get_default_market_data_profile()
    return fetch_tushare_chip_payload(profile, symbol, range_, use_cache=True)


def fetch_tushare_chip_payload(
    profile: MarketDataProfile,
    symbol: str,
    range_: str = "3m",
    *,
    use_cache: bool = True,
) -> Dict[str, Any]:
    normalized_symbol = _normalize_tushare_symbol(symbol)
    cache_key = f"{profile.id}:{_profile_cache_fingerprint(profile)}:{normalized_symbol}:chip:{range_}"
    if use_cache:
        cached = _CHIP_CACHE.get(cache_key)
        if cached and time.time() - cached.get("_cached_at", 0) < _CHIP_CACHE_TTL:
            return {key: value for key, value in cached.items() if key != "_cached_at"}

    payload = _fetch_tushare_chip_payload(profile, normalized_symbol, range_)
    if payload.get("status") == "READY" and use_cache:
        _CHIP_CACHE[cache_key] = {**payload, "_cached_at": time.time()}
    return payload


def _profile_cache_fingerprint(profile: MarketDataProfile) -> str:
    payload = {
        "provider": profile.provider,
        "base_url": profile.base_url,
        "auth_mode": profile.auth_mode,
        "enabled": profile.enabled,
        "extra_query_params": profile.extra_query_params,
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _fast_chip_profile(profile: MarketDataProfile) -> MarketDataProfile:
    timeout_seconds = min(profile.timeout_seconds, _CHIP_HTTP_TIMEOUT_SECONDS)
    return profile.model_copy(update={"timeout_seconds": timeout_seconds})


def _fetch_chip_api_rows(
    profile: MarketDataProfile,
    api_name: str,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    payload = _call_tushare_http_api_raw(profile, api_name, params)
    records = _tushare_records_from_payload(payload)
    rows = _normalize_perf_rows(records) if api_name == "cyq_perf" else _normalize_chip_rows(records)
    return {
        "api": api_name,
        "status": "READY",
        "record_count": len(rows),
        "rows": rows,
    }


def _fetch_tushare_chip_payload(profile: MarketDataProfile, normalized_symbol: str, range_: str) -> Dict[str, Any]:
    if not profile.enabled:
        return _empty_response(normalized_symbol, range_, "行情 Profile 未启用，未拉取 Tushare 筹码接口。")
    if not profile.api_key:
        return _empty_response(normalized_symbol, range_, "未配置 Tushare Token，未拉取 Tushare 筹码接口。")

    today = date.today()
    start_date = today - timedelta(days=120)
    params = {
        "ts_code": normalized_symbol,
        "start_date": start_date.strftime("%Y%m%d"),
        "end_date": today.strftime("%Y%m%d"),
    }
    api_results: List[Dict[str, Any]] = []
    errors: List[str] = []
    perf_rows: List[Dict[str, Any]] = []
    chip_rows: List[Dict[str, Any]] = []
    chip_profile = _fast_chip_profile(profile)

    results_by_api: Dict[str, Dict[str, Any]] = {}
    executor = ThreadPoolExecutor(max_workers=2)
    futures = {
        executor.submit(_fetch_chip_api_rows, chip_profile, api_name, params): api_name
        for api_name in ("cyq_perf", "cyq_chips")
    }
    try:
        done, pending = wait(futures, timeout=_CHIP_TOTAL_BUDGET_SECONDS)
        for future in done:
            api_name = futures[future]
            try:
                results_by_api[api_name] = future.result()
            except Exception as exc:
                results_by_api[api_name] = {"api": api_name, "status": "FAILED", "error": str(exc)[:300]}
        for future in pending:
            api_name = futures[future]
            future.cancel()
            results_by_api[api_name] = {
                "api": api_name,
                "status": "FAILED",
                "error": f"timeout after {_CHIP_TOTAL_BUDGET_SECONDS}s",
            }
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    for api_name in ("cyq_perf", "cyq_chips"):
        result = results_by_api.get(api_name) or {"api": api_name, "status": "FAILED", "error": "no result"}
        if result.get("status") == "READY":
            if api_name == "cyq_perf":
                perf_rows = result.get("rows", [])
            else:
                chip_rows = result.get("rows", [])
            api_results.append({"api": api_name, "status": "READY", "record_count": result.get("record_count", 0)})
        else:
            error = str(result.get("error") or "unknown error")[:300]
            errors.append(f"{api_name}: {error}")
            api_results.append({"api": api_name, "status": "FAILED", "error": error})

    if not perf_rows and not chip_rows:
        return _empty_response(
            normalized_symbol,
            range_,
            "Tushare cyq_perf/cyq_chips 未返回可用筹码数据，已降级为 K 线代理。",
            errors,
            api_results,
        )

    latest_perf = _latest_by_trade_date(perf_rows)
    latest_chip_date = _latest_trade_date(chip_rows)
    latest_chips = [row for row in chip_rows if row.get("tradeDate") == latest_chip_date] if latest_chip_date else []
    latest_trade_date = max(
        [value for value in [latest_perf.get("tradeDate") if latest_perf else "", latest_chip_date] if value],
        default="",
    )
    record_count = len(perf_rows) + len(chip_rows)

    return {
        "symbol": normalized_symbol,
        "range": range_,
        "provider": "tushare",
        "status": "READY",
        "dataMode": "LIVE",
        "source": "tushare_http",
        "apiNames": ["cyq_perf", "cyq_chips"],
        "apiResults": api_results,
        "fetchedAt": _now_iso(),
        "recordCount": record_count,
        "latestTradeDate": latest_trade_date,
        "perfRows": perf_rows,
        "chipRows": chip_rows,
        "latestPerf": latest_perf,
        "latestChips": latest_chips,
        "message": f"Tushare 筹码接口返回 {record_count} 条记录。",
        "error": "；".join(errors),
    }


def _normalize_perf_rows(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for record in records:
        trade_date = str(record.get("trade_date") or record.get("tradeDate") or "")
        if not trade_date:
            continue
        rows.append(
            {
                "tsCode": record.get("ts_code") or record.get("tsCode"),
                "tradeDate": trade_date,
                "hisLow": _to_float(record.get("his_low")),
                "hisHigh": _to_float(record.get("his_high")),
                "cost5Pct": _to_float(record.get("cost_5pct")),
                "cost15Pct": _to_float(record.get("cost_15pct")),
                "cost50Pct": _to_float(record.get("cost_50pct")),
                "cost85Pct": _to_float(record.get("cost_85pct")),
                "cost95Pct": _to_float(record.get("cost_95pct")),
                "weightAvg": _to_float(record.get("weight_avg")),
                "winnerRate": _to_ratio(record.get("winner_rate")),
            }
        )
    rows.sort(key=lambda item: item["tradeDate"])
    return rows


def _normalize_chip_rows(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for record in records:
        trade_date = str(record.get("trade_date") or record.get("tradeDate") or "")
        price = _to_float(record.get("price"))
        percent = _to_ratio(record.get("percent"))
        if not trade_date or price is None or percent is None:
            continue
        rows.append(
            {
                "tsCode": record.get("ts_code") or record.get("tsCode"),
                "tradeDate": trade_date,
                "price": price,
                "percent": percent,
            }
        )
    rows.sort(key=lambda item: (item["tradeDate"], item["price"]))
    return rows


def _latest_by_trade_date(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {}
    return max(rows, key=lambda item: str(item.get("tradeDate") or ""))


def _latest_trade_date(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return ""
    return max(str(item.get("tradeDate") or "") for item in rows)


def _empty_response(
    symbol: str,
    range_: str,
    message: str,
    errors: List[str] | None = None,
    api_results: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    return {
        "symbol": _normalize_tushare_symbol(symbol),
        "range": range_,
        "provider": "tushare",
        "status": "FAILED",
        "dataMode": "UNAVAILABLE",
        "source": "tushare_http",
        "apiNames": ["cyq_perf", "cyq_chips"],
        "apiResults": api_results or [],
        "fetchedAt": _now_iso(),
        "recordCount": 0,
        "latestTradeDate": "",
        "perfRows": [],
        "chipRows": [],
        "latestPerf": {},
        "latestChips": [],
        "message": message,
        "error": "；".join(errors or []) or message,
    }


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _to_ratio(value: Any) -> float | None:
    number = _to_float(value)
    if number is None:
        return None
    return number / 100 if abs(number) > 1 else number


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
