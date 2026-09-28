from __future__ import annotations

import calendar
import hashlib
import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List

from ..models.agent_runtime import MarketDataProfile
from .agent_runtime_store import get_default_market_data_profile
from .market_data_runner import (
    _call_tushare_http_api_raw,
    _normalize_tushare_symbol,
    _tushare_records_from_payload,
)


PERIOD_TO_API = {
    "daily": "daily",
    "weekly": "weekly",
    "monthly": "monthly",
}

_KLINE_CACHE: Dict[str, Dict[str, Any]] = {}
_KLINE_CACHE_TTL = 90


def get_kline_payload(symbol: str, period: str = "daily", range_: str = "3m") -> Dict[str, Any]:
    api_name = PERIOD_TO_API.get(period, "daily")
    normalized_symbol = _normalize_tushare_symbol(symbol)
    profile = get_default_market_data_profile()
    cache_key = f"{profile.id}:{_kline_profile_cache_fingerprint(profile)}:{normalized_symbol}:{period}:{range_}"
    cached = _KLINE_CACHE.get(cache_key)
    if cached and time.time() - cached.get("_cached_at", 0) < _KLINE_CACHE_TTL:
        return {key: value for key, value in cached.items() if key != "_cached_at"}

    payload = _fetch_kline_payload(profile, symbol, period, range_, api_name)
    if payload.get("status") == "READY":
        _KLINE_CACHE[cache_key] = {**payload, "_cached_at": time.time()}
    return payload


def _kline_profile_cache_fingerprint(profile: MarketDataProfile) -> str:
    payload = {
        "provider": profile.provider,
        "base_url": profile.base_url,
        "quote_path": profile.quote_path,
        "auth_mode": profile.auth_mode,
        "enabled": profile.enabled,
        "extra_query_params": profile.extra_query_params,
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def get_multi_period_kline_payloads(symbol: str) -> Dict[str, Dict[str, Any]]:
    return {
        period: get_kline_payload(symbol, period, "3m")
        for period in ("daily", "weekly", "monthly")
    }


def _fetch_kline_payload(
    profile: MarketDataProfile,
    symbol: str,
    period: str,
    range_: str,
    api_name: str,
) -> Dict[str, Any]:
    normalized_symbol = _normalize_tushare_symbol(symbol)

    if not profile.enabled:
        return _empty_response(
            symbol=symbol,
            period=period,
            api_name=api_name,
            range_=range_,
            message="行情 Profile 未启用，已停止绘制 K 线。",
        )

    if not profile.api_key:
        return _empty_response(
            symbol=symbol,
            period=period,
            api_name=api_name,
            range_=range_,
            message="未配置 Tushare Token，已停止绘制 K 线。",
        )

    today = date.today()
    start_date = _start_date_for_range(today, range_)
    params = {
        "ts_code": normalized_symbol,
        "start_date": start_date.strftime("%Y%m%d"),
        "end_date": today.strftime("%Y%m%d"),
    }

    try:
        payload = _call_tushare_http_api_raw(profile, api_name, params)
        records = _tushare_records_from_payload(payload)
        rows = _normalize_rows(records)
    except Exception as exc:
        error = str(exc)
        return _empty_response(
            symbol=symbol,
            period=period,
            api_name=api_name,
            range_=range_,
            message=f"Tushare {api_name} 获取失败，已停止绘制 K 线。",
            error=error[:300],
        )

    if not rows:
        return _empty_response(
            symbol=symbol,
            period=period,
            api_name=api_name,
            range_=range_,
            message=f"Tushare {api_name} 未返回真实 K 线记录，已停止绘制。",
        )

    return {
        "symbol": normalized_symbol,
        "period": period,
        "range": range_,
        "apiName": api_name,
        "provider": "tushare",
        "status": "READY",
        "dataMode": "LIVE",
        "fetchedAt": _now_iso(),
        "recordCount": len(rows),
        "lastTradeDate": rows[-1]["tradeDate"],
        "rows": rows,
        "message": f"Tushare {api_name} 返回 {len(rows)} 条真实 K 线记录。",
        "error": "",
    }


def _start_date_for_range(today: date, range_: str) -> date:
    if range_ == "2y":
        return _subtract_years(today, 2)
    if range_ == "6m":
        return _subtract_months(today, 6)
    return today - timedelta(days=120)


def _subtract_months(value: date, months: int) -> date:
    month_index = value.month - months - 1
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _subtract_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year - years)
    except ValueError:
        return value.replace(year=value.year - years, month=2, day=28)


def _empty_response(
    *,
    symbol: str,
    period: str,
    api_name: str,
    range_: str = "3m",
    message: str,
    error: str = "",
) -> Dict[str, Any]:
    return {
        "symbol": _normalize_tushare_symbol(symbol),
        "period": period,
        "range": range_,
        "apiName": api_name,
        "provider": "tushare",
        "status": "FAILED",
        "dataMode": "UNAVAILABLE",
        "fetchedAt": _now_iso(),
        "recordCount": 0,
        "rows": [],
        "message": message,
        "error": error or message,
    }


def _normalize_rows(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for record in records:
        trade_date = str(record.get("trade_date") or record.get("date") or "")
        open_price = _to_float(record.get("open"))
        high = _to_float(record.get("high"))
        low = _to_float(record.get("low"))
        close = _to_float(record.get("close"))
        if not trade_date or None in (open_price, high, low, close):
            continue
        rows.append(
            {
                "tradeDate": trade_date,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "preClose": _to_float(record.get("pre_close")),
                "change": _to_float(record.get("change")),
                "pctChange": _to_float(record.get("pct_chg") or record.get("pct_change")),
                "volume": _to_float(record.get("vol") or record.get("volume")),
                "amount": _to_float(record.get("amount")),
            }
        )
    rows.sort(key=lambda item: item["tradeDate"])
    return rows


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
