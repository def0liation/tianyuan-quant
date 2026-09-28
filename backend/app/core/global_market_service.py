from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..models.agent_runtime import MarketDataProfile
from .agent_runtime_store import get_default_market_data_profile
from .market_data_runner import (
    _call_tushare_http_api_raw,
    _normalize_tushare_symbol,
    _tushare_records_from_payload,
)


INDEX_DEFINITIONS = [
    {"key": "csi300", "symbol": "000300.SH", "name": "沪深300", "exchange": "SH"},
    {"key": "shanghai", "symbol": "000001.SH", "name": "上证指数", "exchange": "SH"},
    {"key": "shenzhen", "symbol": "399001.SZ", "name": "深证成指", "exchange": "SZ"},
    {"key": "chinext", "symbol": "399006.SZ", "name": "创业板指", "exchange": "SZ"},
]

INDEX_SPOT_CATEGORIES = ("沪深重要指数", "上证系列指数", "深证系列指数", "中证系列指数")
CHINA_TZ = timezone(timedelta(hours=8))
INDEX_PRICE_REL_TOLERANCE = 0.0005
INDEX_PCT_ABS_TOLERANCE = 0.03
INDEX_VOLUME_REL_TOLERANCE = 0.05
FUND_FLOW_REL_TOLERANCE = 0.10
FUND_FLOW_ABS_TOLERANCE = 50_000_000
SECTOR_SOURCE_PRIORITIES = {
    "eastmoney_clist": 0,
    "akshare_eastmoney": 1,
    "akshare_ths_summary": 2,
    "tushare_dc_index": 3,
    "tushare_moneyflow_ind_ths": 4,
}
SECTOR_PCT_ABS_TOLERANCE = 0.8

_GLOBAL_MARKET_CACHE: Dict[str, Dict[str, Any]] = {}
_GLOBAL_MARKET_CACHE_TTL = 15
_GLOBAL_MARKET_TRADING_REFRESH_SECONDS = 300
_GLOBAL_MARKET_EOD_REFRESH_SECONDS = 300
_TUSHARE_INDEX_DAILY_MAX_RETRIES = 1
_TUSHARE_INDEX_DAILY_RETRY_DELAY_SECONDS = 0.2

A_SHARE_MORNING_START_MINUTE = 9 * 60 + 30
A_SHARE_MORNING_END_MINUTE = 11 * 60 + 30
A_SHARE_AFTERNOON_START_MINUTE = 13 * 60
A_SHARE_AFTERNOON_END_MINUTE = 15 * 60


def get_global_market_payload(range_: str = "4m") -> Dict[str, Any]:
    profile = get_default_market_data_profile()
    cache_key = f"{profile.id}:{_profile_cache_fingerprint(profile)}:{range_}"
    cached = _GLOBAL_MARKET_CACHE.get(cache_key)
    if cached and time.time() - cached.get("_cached_at", 0) < _GLOBAL_MARKET_CACHE_TTL:
        return {key: value for key, value in cached.items() if key != "_cached_at"}

    payload = _fetch_global_market_payload(profile, range_)
    if payload.get("status") in {"READY", "PARTIAL"}:
        _GLOBAL_MARKET_CACHE[cache_key] = {**payload, "_cached_at": time.time()}
    return payload


def _profile_cache_fingerprint(profile: MarketDataProfile) -> str:
    payload = {
        "provider": profile.provider,
        "base_url": profile.base_url,
        "enabled": profile.enabled,
        "api_key_hash": hashlib.sha256(profile.api_key.encode("utf-8")).hexdigest()[:12] if profile.api_key else "",
        "extra_query_params": profile.extra_query_params,
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _fetch_global_market_payload(profile: MarketDataProfile, range_: str) -> Dict[str, Any]:
    fetched_at = _now_iso()
    today = _cn_now().date()
    start_date = today - timedelta(days=120)
    start = start_date.strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")
    timeout_seconds = _global_market_timeout_seconds(profile)
    deadline = time.time() + timeout_seconds
    executor = ThreadPoolExecutor(max_workers=len(INDEX_DEFINITIONS) + 2)
    try:
        index_futures = [
            (item, executor.submit(_fetch_index_payload, profile, item, start, end, range_))
            for item in INDEX_DEFINITIONS
        ]
        fund_flow_future = executor.submit(_fetch_fund_flow_payload, profile, start, end)
        sector_future = executor.submit(_fetch_sector_rank_payload)
        indices = [
            _future_result_or(
                future,
                lambda message, item=item: _empty_index(item, range_, message),
                f"{item['name']} source arbitration timeout.",
                _remaining_timeout_seconds(deadline),
            )
            for item, future in index_futures
        ]
        fund_flow = _future_result_or(
            fund_flow_future,
            lambda message: _empty_fund_flow(message, error=message),
            "Fund flow source arbitration timeout.",
            _remaining_timeout_seconds(deadline),
        )
        sector_rank = _future_result_or(
            sector_future,
            lambda message: _empty_sector_rank(message, fetched_at),
            "Sector rank source arbitration timeout.",
            _remaining_timeout_seconds(deadline),
        )
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    temperature = _build_market_temperature(indices, fund_flow)

    ready_count = sum(1 for item in indices if item["status"] == "READY")
    sector_ready = sector_rank.get("status") == "READY"
    fund_flow_ready = fund_flow.get("status") == "READY"
    if ready_count == len(indices) and fund_flow_ready and sector_ready:
        status = "READY"
    elif ready_count > 0 or sector_ready or fund_flow_ready:
        status = "PARTIAL"
    else:
        status = "FAILED"

    data_mode = _overview_data_mode(indices, fund_flow, sector_rank)
    messages = [f"已获取 {ready_count}/{len(indices)} 个核心指数。"]
    if sector_ready:
        messages.append(f"实时板块榜返回 {sector_rank.get('recordCount', 0)} 条。")
    elif sector_rank.get("message"):
        messages.append(sector_rank["message"])
    error = ""
    if status == "FAILED":
        error = "核心指数与实时板块榜均未返回。"
    elif not sector_ready and sector_rank.get("error"):
        error = f"实时板块榜不可用：{sector_rank['error']}"
    return {
        "status": status,
        "dataMode": data_mode,
        "provider": "tushare+akshare+arbitration",
        "range": range_,
        "fetchedAt": fetched_at,
        "refreshIntervalSeconds": _global_market_refresh_interval_seconds(),
        "indices": indices,
        "fundFlow": fund_flow,
        "sectorRank": sector_rank,
        "temperature": temperature,
        "message": " ".join(messages),
        "error": error,
    }


def _fetch_index_payload(
    profile: MarketDataProfile,
    definition: Dict[str, str],
    start: str,
    end: str,
    range_: str,
) -> Dict[str, Any]:
    fetched_at = _now_iso()
    in_trading_session = _is_a_share_trading_session()
    timeout_seconds = _global_market_source_timeout_seconds(profile)
    deadline = time.time() + timeout_seconds
    executor = ThreadPoolExecutor(max_workers=2 if in_trading_session else 1)
    try:
        tushare_future = executor.submit(_fetch_tushare_index_source, profile, definition, start, end, range_, fetched_at)
        quote_future = (
            executor.submit(_fetch_akshare_index_quote_source, definition, fetched_at)
            if in_trading_session
            else None
        )
        tushare_source = _future_result_or(
            tushare_future,
            lambda message: _failed_market_source(
                source_id="tushare_index_daily",
                provider="tushare",
                source="tushare",
                api_name="index_daily",
                message=message,
                fetched_at=fetched_at,
                error=message,
            ),
            f"{definition['name']} Tushare index_daily timeout.",
            _remaining_timeout_seconds(deadline),
        )
        sources = [tushare_source]
        if quote_future:
            quote_source = _future_result_or(
                quote_future,
                lambda message: _failed_market_source(
                    source_id="akshare_index_spot",
                    provider="akshare",
                    source="eastmoney",
                    api_name="stock_zh_index_spot_em",
                    message=message,
                    fetched_at=fetched_at,
                    error=message,
                ),
                f"{definition['name']} AkShare realtime quote timeout.",
                _remaining_timeout_seconds(deadline),
            )
            sources.insert(0, quote_source)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    return _arbitrate_index_sources(definition, range_, sources, fetched_at)


def _fetch_tushare_index_source(
    profile: MarketDataProfile,
    definition: Dict[str, str],
    start: str,
    end: str,
    range_: str,
    fetched_at: str,
) -> Dict[str, Any]:
    symbol = _normalize_tushare_symbol(definition["symbol"])
    unavailable_reason = _tushare_unavailable_reason(profile)
    if unavailable_reason:
        return _failed_market_source(
            source_id="tushare_index_daily",
            provider="tushare",
            source="tushare",
            api_name="index_daily",
            message=unavailable_reason,
            fetched_at=fetched_at,
            error=unavailable_reason,
        )

    try:
        payload = _call_tushare_index_daily_with_retry(
            _global_market_source_profile(profile),
            symbol,
            start,
            end,
        )
        rows = _normalize_kline_rows(_tushare_records_from_payload(payload))
    except Exception as exc:
        return _failed_market_source(
            source_id="tushare_index_daily",
            provider="tushare",
            source="tushare",
            api_name="index_daily",
            message=f"Tushare index_daily 获取失败：{str(exc)[:240]}",
            fetched_at=fetched_at,
            error=str(exc)[:300],
        )

    if not rows:
        return _failed_market_source(
            source_id="tushare_index_daily",
            provider="tushare",
            source="tushare",
            api_name="index_daily",
            message="Tushare index_daily 未返回记录。",
            fetched_at=fetched_at,
            error="empty index_daily response",
        )

    latest = rows[-1]
    close_values = [row["close"] for row in rows]
    ma5 = _moving_average(close_values, 5)
    ma10 = _moving_average(close_values, 10)
    ma20 = _moving_average(close_values, 20)
    latest_with_ma = {
        **latest,
        "ma5": ma5[-1] if ma5 else None,
        "ma10": ma10[-1] if ma10 else None,
        "ma20": ma20[-1] if ma20 else None,
    }
    freshness = "EOD" if latest["tradeDate"] == _today_trade_date() else "STALE"
    return _ready_market_source(
        source_id="tushare_index_daily",
        provider="tushare",
        source="tushare",
        api_name="index_daily",
        data_mode="FALLBACK",
        freshness=freshness,
        trade_date=latest["tradeDate"],
        fetched_at=fetched_at,
        confidence=0.82 if freshness == "EOD" else 0.64,
        record_count=len(rows),
        latest=latest_with_ma,
        rows=rows,
        message=f"{definition['name']} 返回 {len(rows)} 条 Tushare 指数日 K。",
    )


def _fetch_akshare_index_quote_source(definition: Dict[str, str], fetched_at: str) -> Dict[str, Any]:
    try:
        ak = _get_akshare_module()
    except Exception as exc:
        return _failed_market_source(
            source_id="akshare_index_spot",
            provider="akshare",
            source="eastmoney",
            api_name="stock_zh_index_spot_em",
            message=f"AkShare 不可用，无法获取实时指数行情：{str(exc)[:180]}",
            fetched_at=fetched_at,
            error=str(exc)[:300],
        )

    target_code = _index_code(definition)
    last_error = ""
    for category in INDEX_SPOT_CATEGORIES:
        try:
            df = ak.stock_zh_index_spot_em(symbol=category)
            records = _records_from_dataframe(df)
        except Exception as exc:
            last_error = str(exc)[:300]
            continue
        record = _find_record_by_code(records, target_code)
        if not record:
            continue
        latest = _normalize_akshare_index_quote_record(record)
        if not latest:
            continue
        return _ready_market_source(
            source_id="akshare_index_spot",
            provider="akshare",
            source="eastmoney",
            api_name="stock_zh_index_spot_em",
            data_mode="LIVE",
            freshness="REALTIME",
            trade_date=_today_trade_date(),
            fetched_at=fetched_at,
            confidence=0.88,
            record_count=1,
            latest=latest,
            rows=[],
            message=f"AkShare 实时指数行情返回 {definition['name']}。",
        )

    return _failed_market_source(
        source_id="akshare_index_spot",
        provider="akshare",
        source="eastmoney",
        api_name="stock_zh_index_spot_em",
        message=f"AkShare stock_zh_index_spot_em 未返回 {definition['name']} 实时行情。",
        fetched_at=fetched_at,
        error=last_error or "index quote not found",
    )


def _empty_index(
    definition: Dict[str, str],
    range_: str,
    error: str,
    *,
    source_chain: List[Dict[str, Any]] | None = None,
    arbitration: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    source_chain = source_chain or []
    arbitration = arbitration or _market_arbitration_payload(
        capability="index_quote",
        selected=None,
        sources=[],
        conflicts=[],
    )
    return {
        "key": definition["key"],
        "symbol": _normalize_tushare_symbol(definition["symbol"]),
        "name": definition["name"],
        "exchange": definition["exchange"],
        "apiName": "index_daily",
        "status": "FAILED",
        "dataMode": "UNAVAILABLE",
        "selectedProvider": "",
        "selectedSource": "",
        "fallbackUsed": False,
        "freshness": "UNKNOWN",
        "sourceConsensus": arbitration.get("sourceConsensus", "NO_DATA"),
        "reviewOnly": bool((arbitration.get("dataQuality") or {}).get("reviewOnly")),
        "range": range_,
        "recordCount": 0,
        "dailyRenderMode": "UNAVAILABLE",
        "dailyRenderMessage": error,
        "sourceChain": source_chain,
        "arbitration": arbitration,
        "conflicts": arbitration.get("conflicts", []),
        "rows": [],
        "message": error,
        "error": error,
    }


def _fetch_fund_flow_payload(profile: MarketDataProfile, start: str, end: str) -> Dict[str, Any]:
    fetched_at = _now_iso()
    timeout_seconds = _global_market_source_timeout_seconds(profile)
    deadline = time.time() + timeout_seconds
    executor = ThreadPoolExecutor(max_workers=2)
    try:
        akshare_future = executor.submit(_fetch_akshare_fund_flow_source, fetched_at)
        tushare_future = executor.submit(_fetch_tushare_fund_flow_source, profile, start, end, fetched_at)
        sources = [
            _future_result_or(
                akshare_future,
                lambda message: _failed_market_source(
                    source_id="akshare_market_fund_flow",
                    provider="akshare",
                    source="eastmoney",
                    api_name="stock_market_fund_flow",
                    message=message,
                    fetched_at=fetched_at,
                    error=message,
                ),
                "AkShare stock_market_fund_flow timeout.",
                _remaining_timeout_seconds(deadline),
            ),
            _future_result_or(
                tushare_future,
                lambda message: _failed_market_source(
                    source_id="tushare_moneyflow_mkt_dc",
                    provider="tushare",
                    source="tushare",
                    api_name="moneyflow_mkt_dc",
                    message=message,
                    fetched_at=fetched_at,
                    error=message,
                ),
                "Tushare moneyflow_mkt_dc timeout.",
                _remaining_timeout_seconds(deadline),
            ),
        ]
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    return _arbitrate_fund_flow_sources(sources, fetched_at)


def _fetch_tushare_fund_flow_source(profile: MarketDataProfile, start: str, end: str, fetched_at: str) -> Dict[str, Any]:
    unavailable_reason = _tushare_unavailable_reason(profile)
    if unavailable_reason:
        return _failed_market_source(
            source_id="tushare_moneyflow_mkt_dc",
            provider="tushare",
            source="tushare",
            api_name="moneyflow_mkt_dc",
            message=unavailable_reason,
            fetched_at=fetched_at,
            error=unavailable_reason,
        )

    try:
        payload = _call_tushare_http_api_raw(
            _global_market_source_profile(profile),
            "moneyflow_mkt_dc",
            {"start_date": start, "end_date": end},
        )
        rows = _normalize_fund_flow_rows(_tushare_records_from_payload(payload))
    except Exception as exc:
        return _failed_market_source(
            source_id="tushare_moneyflow_mkt_dc",
            provider="tushare",
            source="tushare",
            api_name="moneyflow_mkt_dc",
            message=f"Tushare moneyflow_mkt_dc 获取失败：{str(exc)[:240]}",
            fetched_at=fetched_at,
            error=str(exc)[:300],
        )

    if not rows:
        return _failed_market_source(
            source_id="tushare_moneyflow_mkt_dc",
            provider="tushare",
            source="tushare",
            api_name="moneyflow_mkt_dc",
            message="Tushare moneyflow_mkt_dc 未返回资金流记录。",
            fetched_at=fetched_at,
            error="empty moneyflow response",
        )

    latest = rows[-1]
    latest_date = latest["tradeDate"]
    freshness = "EOD" if latest_date == _today_trade_date() else "STALE"
    return _ready_market_source(
        source_id="tushare_moneyflow_mkt_dc",
        provider="tushare",
        source="tushare",
        api_name="moneyflow_mkt_dc",
        data_mode="FALLBACK",
        freshness=freshness,
        trade_date=latest_date,
        fetched_at=fetched_at,
        confidence=0.82 if freshness == "EOD" else 0.64,
        record_count=len(rows),
        latest=latest,
        rows=rows,
        message=f"Tushare 资金流返回 {len(rows)} 条记录。",
    )


def _fetch_akshare_fund_flow_source(fetched_at: str) -> Dict[str, Any]:
    try:
        ak = _get_akshare_module()
    except Exception as exc:
        return _failed_market_source(
            source_id="akshare_market_fund_flow",
            provider="akshare",
            source="eastmoney",
            api_name="stock_market_fund_flow",
            message=f"AkShare 不可用，无法获取今日资金流：{str(exc)[:180]}",
            fetched_at=fetched_at,
            error=str(exc)[:300],
        )

    try:
        df = ak.stock_market_fund_flow()
        rows = _normalize_fund_flow_rows(_records_from_dataframe(df))
    except Exception as exc:
        return _failed_market_source(
            source_id="akshare_market_fund_flow",
            provider="akshare",
            source="eastmoney",
            api_name="stock_market_fund_flow",
            message=f"AkShare stock_market_fund_flow 获取失败：{str(exc)[:240]}",
            fetched_at=fetched_at,
            error=str(exc)[:300],
        )

    if not rows:
        return _failed_market_source(
            source_id="akshare_market_fund_flow",
            provider="akshare",
            source="eastmoney",
            api_name="stock_market_fund_flow",
            message="AkShare stock_market_fund_flow 未返回资金流记录。",
            fetched_at=fetched_at,
            error="empty market fund flow response",
        )

    latest = rows[-1]
    latest_date = latest["tradeDate"]
    freshness = "REALTIME" if latest_date == _today_trade_date() else "STALE"
    return _ready_market_source(
        source_id="akshare_market_fund_flow",
        provider="akshare",
        source="eastmoney",
        api_name="stock_market_fund_flow",
        data_mode="LIVE" if freshness == "REALTIME" else "FALLBACK",
        freshness=freshness,
        trade_date=latest_date,
        fetched_at=fetched_at,
        confidence=0.86 if freshness == "REALTIME" else 0.62,
        record_count=len(rows),
        latest=latest,
        rows=rows,
        message=f"AkShare 今日资金流返回 {len(rows)} 条记录。",
    )


def _empty_fund_flow(
    message: str,
    error: str | None = None,
    *,
    source_chain: List[Dict[str, Any]] | None = None,
    arbitration: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    source_chain = source_chain or []
    arbitration = arbitration or _market_arbitration_payload(
        capability="fund_flow",
        selected=None,
        sources=[],
        conflicts=[],
    )
    return {
        "status": "FAILED",
        "dataMode": "UNAVAILABLE",
        "provider": "tushare",
        "apiName": "moneyflow_mkt_dc",
        "selectedProvider": "",
        "selectedSource": "",
        "fallbackUsed": False,
        "freshness": "UNKNOWN",
        "sourceConsensus": arbitration.get("sourceConsensus", "NO_DATA"),
        "reviewOnly": bool((arbitration.get("dataQuality") or {}).get("reviewOnly")),
        "latestDate": "",
        "netAmount": None,
        "mainNetAmount": None,
        "smallNetAmount": None,
        "unit": "元",
        "rows": [],
        "sourceChain": source_chain,
        "arbitration": arbitration,
        "conflicts": arbitration.get("conflicts", []),
        "message": message,
        "error": error or message,
    }


def _ready_market_source(
    *,
    source_id: str,
    provider: str,
    source: str,
    api_name: str,
    data_mode: str,
    freshness: str,
    trade_date: str,
    fetched_at: str,
    confidence: float,
    record_count: int,
    latest: Dict[str, Any],
    rows: List[Dict[str, Any]],
    message: str,
) -> Dict[str, Any]:
    return {
        "sourceId": source_id,
        "status": "READY",
        "dataMode": data_mode,
        "provider": provider,
        "source": source,
        "apiName": api_name,
        "freshness": freshness,
        "tradeDate": _date_to_yyyymmdd(trade_date) or trade_date,
        "fetchedAt": fetched_at,
        "confidence": confidence,
        "recordCount": record_count,
        "latest": latest,
        "rows": rows,
        "message": message,
        "error": "",
    }


def _failed_market_source(
    *,
    source_id: str,
    provider: str,
    source: str,
    api_name: str,
    message: str,
    fetched_at: str,
    error: str | None = None,
) -> Dict[str, Any]:
    return {
        "sourceId": source_id,
        "status": "FAILED",
        "dataMode": "UNAVAILABLE",
        "provider": provider,
        "source": source,
        "apiName": api_name,
        "freshness": "UNKNOWN",
        "tradeDate": "",
        "fetchedAt": fetched_at,
        "confidence": 0.0,
        "recordCount": 0,
        "latest": {},
        "rows": [],
        "message": message,
        "error": error or message,
    }


def _arbitrate_index_sources(
    definition: Dict[str, str],
    range_: str,
    sources: List[Dict[str, Any]],
    fetched_at: str,
) -> Dict[str, Any]:
    valid = _valid_market_sources(sources)
    if not valid:
        errors = [f"{source.get('provider')}:{source.get('error') or source.get('message')}" for source in sources]
        arbitration = _market_arbitration_payload(
            capability="index_quote",
            selected=None,
            sources=sources,
            conflicts=[],
        )
        payload = _empty_index(
            definition,
            range_,
            "指数实时与 Tushare 回退源均不可用。",
            source_chain=_market_source_summaries(sources),
            arbitration=arbitration,
        )
        payload["error"] = "；".join(errors)
        return payload

    selected, conflicts = _select_market_source(valid, _index_source_conflicts)
    selected_latest = _latest_with_tushare_ma(selected.get("latest") or {}, sources)
    arbitration = _market_arbitration_payload(
        capability="index_quote",
        selected=selected,
        sources=sources,
        conflicts=conflicts,
    )
    rows = _rows_from_source(sources, "tushare_index_daily") or selected.get("rows", [])
    source_chain = _market_source_summaries(sources)
    rows, selected_latest, daily_render_mode, daily_render_message = _build_index_daily_render(
        definition,
        rows,
        selected_latest,
    )
    index_data_mode = selected.get("dataMode", "LIVE")
    index_freshness = selected.get("freshness", "UNKNOWN")
    conflict_count = len(conflicts)
    message = (
        f"{definition['name']} 已仲裁 {len(valid)}/{len(sources)} 个可用来源，"
        f"采用 {selected.get('provider')} · {selected.get('apiName')}，"
        f"发现 {conflict_count} 项冲突。"
    )
    return {
        "key": definition["key"],
        "symbol": _normalize_tushare_symbol(definition["symbol"]),
        "name": definition["name"],
        "exchange": definition["exchange"],
        "apiName": selected.get("apiName", ""),
        "status": "READY",
        "dataMode": index_data_mode,
        "selectedProvider": selected.get("provider", ""),
        "selectedSource": selected.get("sourceId", ""),
        "fallbackUsed": selected.get("provider") != "akshare",
        "freshness": index_freshness,
        "sourceConsensus": arbitration.get("sourceConsensus", "NO_DATA"),
        "reviewOnly": bool((arbitration.get("dataQuality") or {}).get("reviewOnly")),
        "range": range_,
        "recordCount": len(rows),
        "lastTradeDate": rows[-1].get("tradeDate", "") if rows else selected.get("tradeDate", ""),
        "dailyRenderMode": daily_render_mode,
        "dailyRenderMessage": daily_render_message,
        "latestQuoteTime": selected.get("fetchedAt", fetched_at),
        "latest": selected_latest,
        "rows": rows,
        "sourceChain": source_chain,
        "arbitration": arbitration,
        "conflicts": conflicts,
        "message": message,
        "error": _market_failed_source_summary(sources),
    }


def _arbitrate_fund_flow_sources(sources: List[Dict[str, Any]], fetched_at: str) -> Dict[str, Any]:
    valid = _valid_market_sources(sources)
    if not valid:
        errors = [f"{source.get('provider')}:{source.get('error') or source.get('message')}" for source in sources]
        arbitration = _market_arbitration_payload(
            capability="fund_flow",
            selected=None,
            sources=sources,
            conflicts=[],
        )
        return _empty_fund_flow(
            "资金流 AkShare 与 Tushare 回退源均不可用。",
            error="；".join(errors),
            source_chain=_market_source_summaries(sources),
            arbitration=arbitration,
        )

    selected, conflicts = _select_market_source(valid, _fund_flow_source_conflicts)
    arbitration = _market_arbitration_payload(
        capability="fund_flow",
        selected=selected,
        sources=sources,
        conflicts=conflicts,
    )
    latest = selected.get("latest") or {}
    conflict_count = len(conflicts)
    return {
        "status": "READY",
        "dataMode": selected.get("dataMode", "LIVE"),
        "provider": "multi-source",
        "apiName": selected.get("apiName", ""),
        "selectedProvider": selected.get("provider", ""),
        "selectedSource": selected.get("sourceId", ""),
        "fallbackUsed": selected.get("provider") != "akshare",
        "freshness": selected.get("freshness", "UNKNOWN"),
        "sourceConsensus": arbitration.get("sourceConsensus", "NO_DATA"),
        "reviewOnly": bool((arbitration.get("dataQuality") or {}).get("reviewOnly")),
        "latestDate": selected.get("tradeDate", ""),
        "netAmount": latest.get("netAmount"),
        "mainNetAmount": latest.get("mainNetAmount"),
        "smallNetAmount": latest.get("smallNetAmount"),
        "unit": "元",
        "rows": selected.get("rows", []),
        "sourceChain": _market_source_summaries(sources),
        "arbitration": arbitration,
        "conflicts": conflicts,
        "message": (
            f"资金流已仲裁 {len(valid)}/{len(sources)} 个可用来源，"
            f"采用 {selected.get('provider')} · {selected.get('apiName')}，"
            f"发现 {conflict_count} 项冲突。"
        ),
        "error": _market_failed_source_summary(sources),
    }


def _select_market_source(
    valid: List[Dict[str, Any]],
    conflict_factory: Any,
) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    akshare = next((source for source in valid if source.get("provider") == "akshare"), None)
    tushare = next((source for source in valid if source.get("provider") == "tushare"), None)
    conflicts: List[Dict[str, Any]] = []
    if akshare and tushare and _source_trade_date(akshare) == _source_trade_date(tushare):
        conflicts = conflict_factory(akshare, tushare)

    if akshare and not tushare:
        return akshare, conflicts
    if tushare and not akshare:
        return tushare, conflicts
    if akshare and tushare:
        ak_date = _source_trade_date(akshare)
        ts_date = _source_trade_date(tushare)
        if ak_date == ts_date:
            return (tushare if _is_post_close() else akshare), conflicts
        if ak_date == _today_trade_date():
            selected = {**akshare}
            if _is_post_close() and ts_date != _today_trade_date():
                selected["freshness"] = "POST_CLOSE_PENDING_EOD"
            return selected, conflicts
        if ts_date and (not ak_date or ts_date > ak_date):
            return tushare, conflicts
        return akshare, conflicts

    return max(valid, key=lambda source: (str(source.get("tradeDate") or ""), float(source.get("confidence") or 0))), conflicts


def _market_arbitration_payload(
    *,
    capability: str,
    selected: Dict[str, Any] | None,
    sources: List[Dict[str, Any]],
    conflicts: List[Dict[str, Any]],
) -> Dict[str, Any]:
    valid_sources = _valid_market_sources(sources)
    valid_dates = {str(source.get("tradeDate") or "") for source in valid_sources if source.get("tradeDate")}
    if not valid_sources:
        consensus = "NO_DATA"
    elif len(valid_sources) == 1 or len(valid_dates) > 1:
        consensus = "SINGLE_SOURCE"
    elif conflicts:
        consensus = "DIVERGED"
    else:
        consensus = "CONSENSUS"
    high_count = sum(1 for conflict in conflicts if conflict.get("severity") == "HIGH")
    medium_count = sum(1 for conflict in conflicts if conflict.get("severity") == "MEDIUM")
    review_only = bool(conflicts)
    if consensus == "CONSENSUS":
        score = 0.95
    elif consensus == "SINGLE_SOURCE":
        score = 0.75
    elif consensus == "DIVERGED":
        score = 0.55
    else:
        score = 0.0
    score = max(0.0, score - high_count * 0.25 - medium_count * 0.1)
    return {
        "capability": capability,
        "selectedSource": selected.get("sourceId", "") if selected else "",
        "sourceConsensus": consensus,
        "resolution": "SOURCE_PRIORITY_REVIEW_ONLY" if review_only else "SOURCE_PRIORITY",
        "checkedSources": _market_source_summaries(sources),
        "conflicts": conflicts,
        "dataQuality": {
            "score": round(score, 3),
            "level": "REVIEW_ONLY" if review_only else ("HIGH" if score >= 0.8 else "MEDIUM" if score >= 0.55 else "LOW"),
            "reviewOnly": review_only,
            "highConflictCount": high_count,
            "mediumConflictCount": medium_count,
        },
        "generatedAt": _now_iso(),
    }


def _index_source_conflicts(primary: Dict[str, Any], other: Dict[str, Any]) -> List[Dict[str, Any]]:
    conflicts: List[Dict[str, Any]] = []
    primary_latest = primary.get("latest") or {}
    other_latest = other.get("latest") or {}
    _append_relative_conflict(
        conflicts,
        field="close",
        primary=primary,
        primary_value=primary_latest.get("close"),
        other=other,
        other_value=other_latest.get("close"),
        tolerance=INDEX_PRICE_REL_TOLERANCE,
        severity="HIGH",
        message="指数价格与 Tushare 日终数据不一致。",
    )
    _append_absolute_conflict(
        conflicts,
        field="pctChange",
        primary=primary,
        primary_value=primary_latest.get("pctChange"),
        other=other,
        other_value=other_latest.get("pctChange"),
        tolerance=INDEX_PCT_ABS_TOLERANCE,
        severity="HIGH",
        message="指数涨跌幅与 Tushare 日终数据不一致。",
    )
    for field in ("volume", "amount"):
        _append_relative_conflict(
            conflicts,
            field=field,
            primary=primary,
            primary_value=primary_latest.get(field),
            other=other,
            other_value=other_latest.get(field),
            tolerance=INDEX_VOLUME_REL_TOLERANCE,
            severity="MEDIUM",
            message="指数成交量/成交额与 Tushare 日终数据不一致。",
        )
    return conflicts


def _fund_flow_source_conflicts(primary: Dict[str, Any], other: Dict[str, Any]) -> List[Dict[str, Any]]:
    conflicts: List[Dict[str, Any]] = []
    primary_net = _to_float((primary.get("latest") or {}).get("netAmount"))
    other_net = _to_float((other.get("latest") or {}).get("netAmount"))
    if primary_net is None or other_net is None:
        return conflicts
    diff = abs(primary_net - other_net)
    baseline = max(abs(primary_net), abs(other_net), 1.0)
    relative_diff = diff / baseline
    if relative_diff > FUND_FLOW_REL_TOLERANCE and diff > FUND_FLOW_ABS_TOLERANCE:
        conflicts.append(
            {
                "field": "netAmount",
                "severity": "HIGH",
                "primarySource": str(primary.get("sourceId") or primary.get("provider") or ""),
                "otherSource": str(other.get("sourceId") or other.get("provider") or ""),
                "primaryValue": primary_net,
                "otherValue": other_net,
                "absoluteDiff": round(diff, 4),
                "relativeDiff": round(relative_diff, 6),
                "tolerance": FUND_FLOW_REL_TOLERANCE,
                "message": "资金流净额与 Tushare 日终数据冲突。",
            }
        )
    return conflicts


def _append_relative_conflict(
    conflicts: List[Dict[str, Any]],
    *,
    field: str,
    primary: Dict[str, Any],
    primary_value: Any,
    other: Dict[str, Any],
    other_value: Any,
    tolerance: float,
    severity: str,
    message: str,
) -> None:
    primary_number = _to_float(primary_value)
    other_number = _to_float(other_value)
    if primary_number is None or other_number is None:
        return
    baseline = max(abs(primary_number), abs(other_number), 1.0)
    relative_diff = abs(primary_number - other_number) / baseline
    if relative_diff <= tolerance:
        return
    conflicts.append(
        {
            "field": field,
            "severity": severity,
            "primarySource": str(primary.get("sourceId") or primary.get("provider") or ""),
            "otherSource": str(other.get("sourceId") or other.get("provider") or ""),
            "primaryValue": primary_number,
            "otherValue": other_number,
            "absoluteDiff": round(abs(primary_number - other_number), 4),
            "relativeDiff": round(relative_diff, 6),
            "tolerance": tolerance,
            "message": message,
        }
    )


def _append_absolute_conflict(
    conflicts: List[Dict[str, Any]],
    *,
    field: str,
    primary: Dict[str, Any],
    primary_value: Any,
    other: Dict[str, Any],
    other_value: Any,
    tolerance: float,
    severity: str,
    message: str,
) -> None:
    primary_number = _to_float(primary_value)
    other_number = _to_float(other_value)
    if primary_number is None or other_number is None:
        return
    diff = abs(primary_number - other_number)
    if diff <= tolerance:
        return
    conflicts.append(
        {
            "field": field,
            "severity": severity,
            "primarySource": str(primary.get("sourceId") or primary.get("provider") or ""),
            "otherSource": str(other.get("sourceId") or other.get("provider") or ""),
            "primaryValue": primary_number,
            "otherValue": other_number,
            "absoluteDiff": round(diff, 4),
            "tolerance": tolerance,
            "message": message,
        }
    )


def _valid_market_sources(sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        source
        for source in sources
        if source.get("status") == "READY" and source.get("latest") and not source.get("error")
    ]


def _market_source_summaries(sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "sourceId": source.get("sourceId", ""),
            "provider": source.get("provider", ""),
            "source": source.get("source", ""),
            "apiName": source.get("apiName", ""),
            "status": source.get("status", "FAILED"),
            "dataMode": source.get("dataMode", "UNAVAILABLE"),
            "freshness": source.get("freshness", "UNKNOWN"),
            "tradeDate": source.get("tradeDate", ""),
            "recordCount": source.get("recordCount", 0),
            "confidence": source.get("confidence", 0.0),
            "message": source.get("message", ""),
            "error": source.get("error", ""),
        }
        for source in sources
    ]


def _market_failed_source_summary(sources: List[Dict[str, Any]]) -> str:
    failed = [
        f"{source.get('provider')}:{source.get('error') or source.get('message')}"
        for source in sources
        if source.get("status") != "READY"
    ]
    return "；".join(failed[:3])


def _source_trade_date(source: Dict[str, Any]) -> str:
    return _date_to_yyyymmdd(source.get("tradeDate")) or ""


def _rows_from_source(sources: List[Dict[str, Any]], source_id: str) -> List[Dict[str, Any]]:
    for source in sources:
        if source.get("sourceId") == source_id and source.get("status") == "READY":
            return source.get("rows", [])
    return []


def _latest_with_tushare_ma(latest: Dict[str, Any], sources: List[Dict[str, Any]]) -> Dict[str, Any]:
    result = dict(latest)
    tushare = next(
        (source for source in sources if source.get("sourceId") == "tushare_index_daily" and source.get("status") == "READY"),
        None,
    )
    if not tushare:
        return result
    tushare_latest = tushare.get("latest") or {}
    for key in ("ma5", "ma10", "ma20"):
        if result.get(key) is None and tushare_latest.get(key) is not None:
            result[key] = tushare_latest.get(key)
    return result


def _build_index_daily_render(
    definition: Dict[str, str],
    rows: List[Dict[str, Any]],
    selected_latest: Dict[str, Any],
) -> tuple[List[Dict[str, Any]], Dict[str, Any], str, str]:
    daily_rows = [dict(row) for row in rows]
    if not daily_rows:
        return daily_rows, selected_latest, "UNAVAILABLE", f"{definition['name']} Tushare 日 K 不可用。"

    today = _today_trade_date()
    latest_daily_date = _date_to_yyyymmdd(daily_rows[-1].get("tradeDate"))
    if latest_daily_date == today:
        return (
            daily_rows,
            _latest_daily_row_with_ma(daily_rows),
            "TUSHARE_EOD",
            f"{definition['name']} 使用 Tushare 当日日 K。",
        )

    if _is_a_share_trading_session():
        message = f"{definition['name']} 交易时段不合成实时日 K，日 K 保留 Tushare 最新可用数据。"
    else:
        message = f"{definition['name']} 非交易时段直接使用 Tushare 最新日 K。"
    return daily_rows, selected_latest, "TUSHARE_STALE", message


def _latest_daily_row_with_ma(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {}
    latest = dict(rows[-1])
    close_values = [_to_float(row.get("close")) for row in rows]
    numeric_closes = [value for value in close_values if value is not None]
    if len(numeric_closes) != len(rows):
        return latest
    ma5 = _moving_average(numeric_closes, 5)
    ma10 = _moving_average(numeric_closes, 10)
    ma20 = _moving_average(numeric_closes, 20)
    latest["ma5"] = ma5[-1] if ma5 else None
    latest["ma10"] = ma10[-1] if ma10 else None
    latest["ma20"] = ma20[-1] if ma20 else None
    return latest


def _overview_data_mode(indices: List[Dict[str, Any]], fund_flow: Dict[str, Any], sector_rank: Dict[str, Any]) -> str:
    modes = [str(item.get("dataMode") or "") for item in [*indices, fund_flow, sector_rank] if item.get("status") == "READY"]
    if "LIVE" in modes:
        return "LIVE"
    if "FALLBACK" in modes:
        return "FALLBACK"
    return "UNAVAILABLE"


def _tushare_unavailable_reason(profile: MarketDataProfile) -> str:
    if not profile.enabled:
        return "行情 Profile 未启用，Tushare 回退源不可用。"
    if not profile.api_key:
        return "未配置 Tushare Token，Tushare 回退源不可用。"
    return ""


def _call_tushare_index_daily_with_retry(
    profile: MarketDataProfile,
    symbol: str,
    start: str,
    end: str,
) -> Dict[str, Any]:
    params = {"ts_code": symbol, "start_date": start, "end_date": end}
    last_exc: Exception | None = None
    for attempt in range(_TUSHARE_INDEX_DAILY_MAX_RETRIES + 1):
        try:
            payload = _call_tushare_http_api_raw(profile, "index_daily", params)
            payload["retryCount"] = attempt
            return payload
        except Exception as exc:
            last_exc = exc
            if attempt >= _TUSHARE_INDEX_DAILY_MAX_RETRIES or not _is_transient_market_fetch_error(exc):
                raise
            time.sleep(_TUSHARE_INDEX_DAILY_RETRY_DELAY_SECONDS)
    if last_exc:
        raise last_exc
    raise RuntimeError("Tushare index_daily failed without an exception.")


def _is_transient_market_fetch_error(exc: Exception) -> bool:
    message = str(exc).lower()
    transient_markers = (
        "timed out",
        "timeout",
        "handshake",
        "_ssl",
        "urlopen error",
        "connection reset",
        "connection aborted",
        "remote end closed",
        "temporarily unavailable",
    )
    return any(marker in message for marker in transient_markers)


def _future_result_or(future: Any, fallback_factory: Any, timeout_message: str, timeout_seconds: float) -> Dict[str, Any]:
    try:
        return future.result(timeout=timeout_seconds)
    except TimeoutError:
        future.cancel()
        return fallback_factory(timeout_message)
    except Exception as exc:
        return fallback_factory(str(exc)[:240])


def _remaining_timeout_seconds(deadline: float) -> float:
    return max(0.1, deadline - time.time())


def _global_market_timeout_seconds(profile: MarketDataProfile) -> int:
    return min(10, max(6, int(profile.timeout_seconds or 6)))


def _global_market_source_timeout_seconds(profile: MarketDataProfile) -> int:
    return min(6, max(4, int(profile.timeout_seconds or 6)))


def _global_market_source_profile(profile: MarketDataProfile) -> MarketDataProfile:
    timeout = _global_market_source_timeout_seconds(profile)
    if int(profile.timeout_seconds or timeout) == timeout:
        return profile
    return profile.model_copy(update={"timeout_seconds": timeout})


def _global_market_refresh_interval_seconds() -> int:
    return _GLOBAL_MARKET_TRADING_REFRESH_SECONDS if _is_a_share_trading_session() else _GLOBAL_MARKET_EOD_REFRESH_SECONDS


def _fetch_sector_rank_payload() -> Dict[str, Any]:
    fetched_at = _now_iso()
    profile = get_default_market_data_profile()
    timeout_seconds = _global_market_source_timeout_seconds(profile)
    deadline = time.time() + timeout_seconds
    executor = ThreadPoolExecutor(max_workers=4)
    try:
        akshare_future = executor.submit(_fetch_akshare_sector_rank_payload, fetched_at)
        tushare_dc_future = executor.submit(_fetch_tushare_dc_index_sector_rank_payload, profile, fetched_at)
        akshare_ths_future = executor.submit(_fetch_akshare_ths_sector_rank_payload, fetched_at)
        tushare_future = executor.submit(_fetch_tushare_sector_rank_payload, profile, fetched_at)
        sources = [
            _future_result_or(
                akshare_future,
                lambda message: _failed_sector_source(
                    source_id="akshare_eastmoney",
                    provider="akshare",
                    source="eastmoney",
                    api_name="stock_board_industry_name_em",
                    message=message,
                    fetched_at=fetched_at,
                ),
                "AkShare stock_board_industry_name_em timeout.",
                _remaining_timeout_seconds(deadline),
            ),
            _future_result_or(
                tushare_dc_future,
                lambda message: _failed_sector_source(
                    source_id="tushare_dc_index",
                    provider="tushare",
                    source="eastmoney",
                    api_name="dc_index",
                    message=message,
                    fetched_at=fetched_at,
                ),
                "Tushare dc_index timeout.",
                _remaining_timeout_seconds(deadline),
            ),
            _future_result_or(
                akshare_ths_future,
                lambda message: _failed_sector_source(
                    source_id="akshare_ths_summary",
                    provider="akshare",
                    source="ths",
                    api_name="stock_board_industry_summary_ths",
                    message=message,
                    fetched_at=fetched_at,
                ),
                "AkShare stock_board_industry_summary_ths timeout.",
                _remaining_timeout_seconds(deadline),
            ),
            _future_result_or(
                tushare_future,
                lambda message: _failed_sector_source(
                    source_id="tushare_moneyflow_ind_ths",
                    provider="tushare",
                    source="ths",
                    api_name="moneyflow_ind_ths",
                    message=message,
                    fetched_at=fetched_at,
                ),
                "Tushare moneyflow_ind_ths timeout.",
                _remaining_timeout_seconds(deadline),
            ),
        ]
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    return _arbitrate_sector_rank_sources(sources, fetched_at)


def _fetch_akshare_sector_rank_payload(fetched_at: str) -> Dict[str, Any]:
    eastmoney_source = _fetch_eastmoney_sector_rank_payload(fetched_at)
    if eastmoney_source.get("status") != "READY":
        eastmoney_source["sourceId"] = "akshare_eastmoney"
        eastmoney_source["provider"] = "akshare"
        eastmoney_source["apiName"] = "stock_board_industry_name_em"
        eastmoney_source["message"] = f"AkShare/EastMoney 快速源不可用：{eastmoney_source.get('message', '')}"
    return eastmoney_source


def _fetch_eastmoney_sector_rank_payload(fetched_at: str) -> Dict[str, Any]:
    url = "https://17.push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": "1",
        "pz": "100",
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": "m:90 t:2 f:!50",
        "fields": (
            "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21,"
            "f23,f24,f25,f26,f22,f33,f11,f62,f128,f136,f115,f152,f124,f107,f104,f105,"
            "f140,f141,f207,f208,f209,f222"
        ),
    }
    try:
        request = Request(
            f"{url}?{urlencode(params)}",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urlopen(request, timeout=2.5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        diff = ((payload.get("data") or {}).get("diff") or []) if isinstance(payload, dict) else []
        records = _eastmoney_sector_rank_records(diff if isinstance(diff, list) else [])
        rows = _normalize_sector_rank_rows(records)
    except Exception as exc:
        return _failed_sector_source(
            source_id="eastmoney_clist",
            provider="eastmoney",
            source="eastmoney",
            api_name="qt_clist_industry_board",
            message=f"EastMoney 行业板块收盘榜获取失败：{str(exc)[:240]}",
            fetched_at=fetched_at,
            error=str(exc)[:300],
        )

    if not rows:
        return _failed_sector_source(
            source_id="eastmoney_clist",
            provider="eastmoney",
            source="eastmoney",
            api_name="qt_clist_industry_board",
            message="EastMoney 行业板块收盘榜未返回记录。",
            fetched_at=fetched_at,
            error="empty sector rank response",
        )

    trade_date = _sector_rank_snapshot_trade_date()
    in_session = _is_a_share_trading_session()
    return _ready_sector_source(
        source_id="eastmoney_clist",
        provider="eastmoney",
        source="eastmoney",
        api_name="qt_clist_industry_board",
        fetched_at=fetched_at,
        confidence=0.90 if in_session else 0.72,
        rows=rows,
        message=f"EastMoney 行业板块榜返回 {len(rows)} 条记录，按交易日 {trade_date} 定格。",
        trade_date=trade_date,
        data_mode="LIVE" if in_session else "FALLBACK",
    )


def _eastmoney_sector_rank_records(items: List[Any]) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    sortable = [item for item in items if isinstance(item, dict)]
    sortable.sort(
        key=lambda item: _to_float(item.get("f3")) if _to_float(item.get("f3")) is not None else -9999,
        reverse=True,
    )
    for index, item in enumerate(sortable, start=1):
        records.append(
            {
                "排名": index,
                "板块名称": item.get("f14"),
                "板块代码": item.get("f12"),
                "最新价": item.get("f2"),
                "涨跌幅": item.get("f3"),
                "涨跌额": item.get("f4"),
                "总市值": item.get("f20"),
                "换手率": item.get("f8"),
                "上涨家数": item.get("f104"),
                "下跌家数": item.get("f105"),
                "领涨股票": item.get("f128"),
                "领涨股票-涨跌幅": item.get("f136"),
            }
        )
    return records


def _fetch_akshare_ths_sector_rank_payload(fetched_at: str) -> Dict[str, Any]:
    try:
        ak = _get_akshare_module()
    except Exception as exc:
        return _failed_sector_source(
            source_id="akshare_ths_summary",
            provider="akshare",
            source="ths",
            api_name="stock_board_industry_summary_ths",
            message=f"AkShare 不可用，无法获取同花顺行业板块榜：{str(exc)[:180]}",
            fetched_at=fetched_at,
            error=str(exc)[:300],
        )

    try:
        df = ak.stock_board_industry_summary_ths()
        rows = _normalize_sector_rank_rows(_records_from_dataframe(df))
    except Exception as exc:
        return _failed_sector_source(
            source_id="akshare_ths_summary",
            provider="akshare",
            source="ths",
            api_name="stock_board_industry_summary_ths",
            message=f"AkShare stock_board_industry_summary_ths 获取失败：{str(exc)[:240]}",
            fetched_at=fetched_at,
            error=str(exc)[:300],
        )

    if not rows:
        return _failed_sector_source(
            source_id="akshare_ths_summary",
            provider="akshare",
            source="ths",
            api_name="stock_board_industry_summary_ths",
            message="AkShare stock_board_industry_summary_ths 未返回行业板块排行记录。",
            fetched_at=fetched_at,
            error="empty sector rank response",
        )

    trade_date = _sector_rank_snapshot_trade_date()
    in_session = _is_a_share_trading_session()
    return _ready_sector_source(
        source_id="akshare_ths_summary",
        provider="akshare",
        source="ths",
        api_name="stock_board_industry_summary_ths",
        fetched_at=fetched_at,
        confidence=0.84 if in_session else 0.70,
        rows=rows,
        message=f"AkShare 同花顺行业板块榜返回 {len(rows)} 条记录，按交易日 {trade_date} 定格。",
        trade_date=trade_date,
        data_mode="LIVE" if in_session else "FALLBACK",
    )


def _fetch_tushare_dc_index_sector_rank_payload(profile: MarketDataProfile, fetched_at: str) -> Dict[str, Any]:
    if not profile.enabled:
        return _failed_sector_source(
            source_id="tushare_dc_index",
            provider="tushare",
            source="eastmoney",
            api_name="dc_index",
            message="Tushare 东财板块源未启用。",
            fetched_at=fetched_at,
            error="market data profile disabled",
        )
    if not profile.api_key:
        return _failed_sector_source(
            source_id="tushare_dc_index",
            provider="tushare",
            source="eastmoney",
            api_name="dc_index",
            message="未配置 Tushare Token，东财板块候选源不可用。",
            fetched_at=fetched_at,
            error="missing tushare token",
        )

    today = _cn_now().date()
    today_value = today.strftime("%Y%m%d")
    try:
        payload = _call_tushare_http_api_raw(
            _global_market_source_profile(profile),
            "dc_index",
            {"trade_date": today_value, "idx_type": "行业板块"},
        )
        records = _tushare_records_from_payload(payload)
        if not records:
            payload = _call_tushare_http_api_raw(
                _global_market_source_profile(profile),
                "dc_index",
                {
                    "start_date": (today - timedelta(days=10)).strftime("%Y%m%d"),
                    "end_date": today_value,
                    "idx_type": "行业板块",
                },
            )
            records = _latest_trade_date_records(_tushare_records_from_payload(payload))
        rows = _normalize_sector_rank_rows(_normalize_tushare_dc_sector_records(records))
    except Exception as exc:
        return _failed_sector_source(
            source_id="tushare_dc_index",
            provider="tushare",
            source="eastmoney",
            api_name="dc_index",
            message=f"Tushare dc_index 获取失败：{str(exc)[:240]}",
            fetched_at=fetched_at,
            error=str(exc)[:300],
        )

    if not rows:
        return _failed_sector_source(
            source_id="tushare_dc_index",
            provider="tushare",
            source="eastmoney",
            api_name="dc_index",
            message="Tushare dc_index 未返回行业板块排行记录。",
            fetched_at=fetched_at,
            error="empty sector rank response",
        )

    latest_trade_date = str(records[0].get("trade_date") or today_value) if records else today_value
    return _ready_sector_source(
        source_id="tushare_dc_index",
        provider="tushare",
        source="eastmoney",
        api_name="dc_index",
        fetched_at=fetched_at,
        confidence=0.82 if latest_trade_date == today_value else 0.68,
        rows=rows,
        message=f"Tushare 东财行业板块源返回 {len(rows)} 条记录，交易日 {latest_trade_date}。",
        trade_date=latest_trade_date,
        data_mode="LIVE" if latest_trade_date == today_value else "FALLBACK",
    )


def _fetch_tushare_sector_rank_payload(profile: MarketDataProfile, fetched_at: str) -> Dict[str, Any]:
    if not profile.enabled:
        return _failed_sector_source(
            source_id="tushare_moneyflow_ind_ths",
            provider="tushare",
            source="ths",
            api_name="moneyflow_ind_ths",
            message="Tushare 行业资金流源未启用。",
            fetched_at=fetched_at,
            error="market data profile disabled",
        )
    if not profile.api_key:
        return _failed_sector_source(
            source_id="tushare_moneyflow_ind_ths",
            provider="tushare",
            source="ths",
            api_name="moneyflow_ind_ths",
            message="未配置 Tushare Token，行业资金流候选源不可用。",
            fetched_at=fetched_at,
            error="missing tushare token",
        )

    today = _cn_now().date()
    trade_date = today.strftime("%Y%m%d")
    try:
        payload = _call_tushare_http_api_raw(
            _global_market_source_profile(profile),
            "moneyflow_ind_ths",
            {"trade_date": trade_date},
        )
        records = _tushare_records_from_payload(payload)
        if not records:
            payload = _call_tushare_http_api_raw(
                _global_market_source_profile(profile),
                "moneyflow_ind_ths",
                {
                    "start_date": (today - timedelta(days=10)).strftime("%Y%m%d"),
                    "end_date": trade_date,
                },
            )
            records = _latest_trade_date_records(_tushare_records_from_payload(payload))
        rows = _normalize_sector_rank_rows(records)
    except Exception as exc:
        return _failed_sector_source(
            source_id="tushare_moneyflow_ind_ths",
            provider="tushare",
            source="ths",
            api_name="moneyflow_ind_ths",
            message=f"Tushare moneyflow_ind_ths 获取失败：{str(exc)[:240]}",
            fetched_at=fetched_at,
            error=str(exc)[:300],
        )

    if not rows:
        return _failed_sector_source(
            source_id="tushare_moneyflow_ind_ths",
            provider="tushare",
            source="ths",
            api_name="moneyflow_ind_ths",
            message="Tushare moneyflow_ind_ths 未返回行业排行记录。",
            fetched_at=fetched_at,
            error="empty sector rank response",
        )

    latest_trade_date = str(records[0].get("trade_date") or trade_date) if records else trade_date
    return _ready_sector_source(
        source_id="tushare_moneyflow_ind_ths",
        provider="tushare",
        source="ths",
        api_name="moneyflow_ind_ths",
        fetched_at=fetched_at,
        confidence=0.80 if latest_trade_date == trade_date else 0.64,
        rows=rows,
        message=f"Tushare 行业资金流候选源返回 {len(rows)} 条记录，交易日 {latest_trade_date}。",
        trade_date=latest_trade_date,
        data_mode="LIVE" if latest_trade_date == trade_date else "FALLBACK",
    )


def _ready_sector_source(
    *,
    source_id: str,
    provider: str,
    source: str,
    api_name: str,
    fetched_at: str,
    confidence: float,
    rows: List[Dict[str, Any]],
    message: str,
    trade_date: str | None = None,
    data_mode: str = "LIVE",
) -> Dict[str, Any]:
    ranked = _sort_sector_rows(rows)
    bottom = sorted(
        [row for row in ranked if isinstance(row.get("pctChange"), (int, float))],
        key=lambda item: item["pctChange"],
    )[:10]
    return {
        "sourceId": source_id,
        "status": "READY",
        "dataMode": data_mode,
        "provider": provider,
        "source": source,
        "apiName": api_name,
        "boardType": "industry",
        "tradeDate": trade_date or _sector_rank_snapshot_trade_date(),
        "fetchedAt": fetched_at,
        "recordCount": len(ranked),
        "confidence": confidence,
        "top": ranked[:10],
        "bottom": bottom,
        "rows": ranked,
        "message": message,
        "error": "",
    }


def _failed_sector_source(
    *,
    source_id: str,
    provider: str,
    source: str,
    api_name: str,
    message: str,
    fetched_at: str,
    error: str | None = None,
) -> Dict[str, Any]:
    return {
        "sourceId": source_id,
        "status": "FAILED",
        "dataMode": "UNAVAILABLE",
        "provider": provider,
        "source": source,
        "apiName": api_name,
        "boardType": "industry",
        "tradeDate": date.today().strftime("%Y%m%d"),
        "fetchedAt": fetched_at,
        "recordCount": 0,
        "confidence": 0.0,
        "top": [],
        "bottom": [],
        "rows": [],
        "message": message,
        "error": error or message,
    }


def _arbitrate_sector_rank_sources(sources: List[Dict[str, Any]], fetched_at: str) -> Dict[str, Any]:
    valid = [source for source in sources if source.get("status") == "READY" and source.get("rows")]
    if not valid:
        message = "实时板块涨跌幅榜所有候选源均不可用。"
        errors = [f"{source.get('provider')}: {source.get('error') or source.get('message')}" for source in sources]
        return _empty_sector_rank(
            message,
            fetched_at,
            error="; ".join(errors),
            candidate_sources=_sector_candidate_summaries(sources),
            arbitration=_sector_arbitration_payload(
                selected=None,
                sources=sources,
                conflicts=[],
            ),
        )

    selected = min(
        valid,
        key=lambda source: (
            SECTOR_SOURCE_PRIORITIES.get(str(source.get("sourceId")), 99),
            -float(source.get("confidence") or 0.0),
            -int(source.get("recordCount") or 0),
        ),
    )
    conflicts: List[Dict[str, Any]] = []
    for source in valid:
        if source is selected:
            continue
        conflicts.extend(_sector_rank_conflicts(selected, source))

    arbitration = _sector_arbitration_payload(
        selected=selected,
        sources=sources,
        conflicts=conflicts,
    )
    conflict_count = len(conflicts)
    valid_count = len(valid)
    source_count = len(sources)
    message = (
        f"实时板块榜已仲裁 {valid_count}/{source_count} 个可用来源，"
        f"采用 {selected.get('provider')} · {selected.get('apiName')}，"
        f"发现 {conflict_count} 项冲突。"
    )
    return {
        "status": "READY",
        "dataMode": selected.get("dataMode", "LIVE"),
        "provider": "multi-source",
        "source": selected.get("source", ""),
        "apiName": selected.get("apiName", ""),
        "boardType": "industry",
        "tradeDate": selected.get("tradeDate") or date.today().strftime("%Y%m%d"),
        "fetchedAt": fetched_at,
        "recordCount": selected.get("recordCount", 0),
        "selectedProvider": selected.get("provider", ""),
        "selectedSource": selected.get("sourceId", ""),
        "sourceCount": {"ready": valid_count, "total": source_count},
        "candidateSources": _sector_candidate_summaries(sources),
        "arbitration": arbitration,
        "top": selected.get("top", []),
        "bottom": selected.get("bottom", []),
        "rows": selected.get("rows", []),
        "message": message,
        "error": "" if valid_count == source_count else _sector_failed_source_summary(sources),
    }


def _sort_sector_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ranked = sorted(
        rows,
        key=lambda item: item["pctChange"] if isinstance(item.get("pctChange"), (int, float)) else -9999,
        reverse=True,
    )
    return [{**row, "rank": index + 1} for index, row in enumerate(ranked)]


def _sector_candidate_summaries(sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "sourceId": source.get("sourceId", ""),
            "provider": source.get("provider", ""),
            "source": source.get("source", ""),
            "apiName": source.get("apiName", ""),
            "status": source.get("status", "FAILED"),
            "dataMode": source.get("dataMode", "UNAVAILABLE"),
            "recordCount": source.get("recordCount", 0),
            "confidence": source.get("confidence", 0.0),
            "message": source.get("message", ""),
            "error": source.get("error", ""),
        }
        for source in sources
    ]


def _sector_arbitration_payload(
    *,
    selected: Dict[str, Any] | None,
    sources: List[Dict[str, Any]],
    conflicts: List[Dict[str, Any]],
) -> Dict[str, Any]:
    valid_sources = [source for source in sources if source.get("status") == "READY" and source.get("rows")]
    if not valid_sources:
        consensus = "NO_DATA"
    elif len(valid_sources) == 1:
        consensus = "SINGLE_SOURCE"
    elif conflicts:
        consensus = "DIVERGED"
    else:
        consensus = "CONSENSUS"
    high_count = sum(1 for conflict in conflicts if conflict.get("severity") == "HIGH")
    medium_count = sum(1 for conflict in conflicts if conflict.get("severity") == "MEDIUM")
    review_only = bool(conflicts)
    if consensus == "CONSENSUS":
        score = 0.95
    elif consensus == "SINGLE_SOURCE":
        score = 0.75
    elif consensus == "DIVERGED":
        score = 0.55
    else:
        score = 0.0
    score = max(0.0, score - high_count * 0.25 - medium_count * 0.1)
    return {
        "capability": "sector_rank",
        "selectedSource": selected.get("sourceId", "") if selected else "",
        "sourceConsensus": consensus,
        "resolution": "SOURCE_PRIORITY_REVIEW_ONLY" if review_only else "SOURCE_PRIORITY",
        "checkedSources": _sector_candidate_summaries(sources),
        "conflicts": conflicts,
        "dataQuality": {
            "score": round(score, 3),
            "level": "REVIEW_ONLY" if review_only else ("HIGH" if score >= 0.8 else "MEDIUM" if score >= 0.55 else "LOW"),
            "reviewOnly": review_only,
            "highConflictCount": high_count,
            "mediumConflictCount": medium_count,
        },
        "generatedAt": _now_iso(),
    }


def _sector_rank_conflicts(primary: Dict[str, Any], other: Dict[str, Any]) -> List[Dict[str, Any]]:
    conflicts: List[Dict[str, Any]] = []
    primary_rows = primary.get("rows") or []
    other_rows = other.get("rows") or []
    primary_source = str(primary.get("sourceId") or primary.get("provider") or "")
    other_source = str(other.get("sourceId") or other.get("provider") or "")
    primary_top = primary_rows[:10]
    other_top = other_rows[:10]
    primary_keys = [_sector_row_key(row) for row in primary_top if _sector_row_key(row)]
    other_keys = [_sector_row_key(row) for row in other_top if _sector_row_key(row)]
    overlap = sorted(set(primary_keys) & set(other_keys))

    if primary_top and other_top and _sector_row_key(primary_top[0]) != _sector_row_key(other_top[0]):
        conflicts.append(
            {
                "field": "topRank",
                "severity": "MEDIUM",
                "primarySource": primary_source,
                "otherSource": other_source,
                "primaryValue": primary_top[0].get("name") or primary_top[0].get("code"),
                "otherValue": other_top[0].get("name") or other_top[0].get("code"),
                "message": "候选源给出的最强板块不一致。",
            }
        )

    if not overlap and primary_keys and other_keys:
        conflicts.append(
            {
                "field": "coverage",
                "severity": "HIGH",
                "primarySource": primary_source,
                "otherSource": other_source,
                "primaryCount": len(primary_keys),
                "otherCount": len(other_keys),
                "overlapCount": 0,
                "message": "候选源 Top10 板块没有交集。",
            }
        )
        return conflicts

    primary_by_key = {_sector_row_key(row): row for row in primary_rows if _sector_row_key(row)}
    other_by_key = {_sector_row_key(row): row for row in other_rows if _sector_row_key(row)}
    for key in overlap[:5]:
        primary_pct = _to_float(primary_by_key.get(key, {}).get("pctChange"))
        other_pct = _to_float(other_by_key.get(key, {}).get("pctChange"))
        if primary_pct is None or other_pct is None:
            continue
        diff = abs(primary_pct - other_pct)
        if diff <= SECTOR_PCT_ABS_TOLERANCE:
            continue
        conflicts.append(
            {
                "field": "pctChange",
                "severity": "HIGH" if diff >= SECTOR_PCT_ABS_TOLERANCE * 2 else "MEDIUM",
                "primarySource": primary_source,
                "otherSource": other_source,
                "sector": primary_by_key[key].get("name") or key,
                "primaryValue": primary_pct,
                "otherValue": other_pct,
                "absoluteDiff": round(diff, 4),
                "tolerance": SECTOR_PCT_ABS_TOLERANCE,
            }
        )
    return conflicts


def _sector_row_key(row: Dict[str, Any]) -> str:
    code = str(row.get("code") or "").strip().lower()
    if code:
        return code
    name = str(row.get("name") or "").strip().lower()
    return "".join(ch for ch in name if ch.isalnum())


def _sector_failed_source_summary(sources: List[Dict[str, Any]]) -> str:
    failed = [
        f"{source.get('provider')}:{source.get('error') or source.get('message')}"
        for source in sources
        if source.get("status") != "READY"
    ]
    return "；".join(failed[:3])


def _empty_sector_rank(
    message: str,
    fetched_at: str | None = None,
    error: str | None = None,
    candidate_sources: List[Dict[str, Any]] | None = None,
    arbitration: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    return {
        "status": "FAILED",
        "dataMode": "UNAVAILABLE",
        "provider": "multi-source",
        "source": "sector-arbitration",
        "apiName": "sector_rank_arbitration",
        "boardType": "industry",
        "tradeDate": date.today().strftime("%Y%m%d"),
        "fetchedAt": fetched_at or _now_iso(),
        "recordCount": 0,
        "selectedProvider": "",
        "selectedSource": "",
        "sourceCount": {"ready": 0, "total": len(candidate_sources or [])},
        "candidateSources": candidate_sources or [],
        "arbitration": arbitration or _sector_arbitration_payload(selected=None, sources=[], conflicts=[]),
        "top": [],
        "bottom": [],
        "rows": [],
        "message": message,
        "error": error or message,
    }


def _get_akshare_module() -> Any:
    if importlib.util.find_spec("akshare") is None:
        raise RuntimeError("akshare package is not installed")
    return importlib.import_module("akshare")


def _records_from_dataframe(df: Any) -> List[Dict[str, Any]]:
    if hasattr(df, "to_dict"):
        records = df.to_dict(orient="records")
        return records if isinstance(records, list) else []
    return df if isinstance(df, list) else []


def _index_code(definition: Dict[str, str]) -> str:
    return "".join(ch for ch in definition["symbol"] if ch.isdigit())[:6]


def _find_record_by_code(records: List[Dict[str, Any]], target_code: str) -> Dict[str, Any] | None:
    for record in records:
        code = str(_first_value(record, ("代码", "指数代码", "symbol", "ts_code", "code")) or "")
        if "".join(ch for ch in code if ch.isdigit())[:6] == target_code:
            return record
    return None


def _normalize_akshare_index_quote_record(record: Dict[str, Any]) -> Dict[str, Any] | None:
    close = _first_float(record, ("最新价", "最新", "close", "price", "latest"))
    if close is None:
        return None
    open_price = _first_float(record, ("今开", "开盘", "open")) or close
    high = _first_float(record, ("最高", "high")) or close
    low = _first_float(record, ("最低", "low")) or close
    pre_close = _first_float(record, ("昨收", "pre_close", "preClose"))
    change = _first_float(record, ("涨跌额", "change"))
    pct_change = _first_float(record, ("涨跌幅", "pct_chg", "pct_change", "change_percent"))
    if pct_change is None and pre_close not in (None, 0):
        pct_change = ((close - pre_close) / pre_close) * 100
    return {
        "tradeDate": _today_trade_date(),
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "preClose": pre_close,
        "change": change,
        "pctChange": pct_change,
        "volume": _first_float(record, ("成交量", "volume", "vol")),
        "amount": _first_float(record, ("成交额", "amount")),
    }


def _normalize_tushare_dc_sector_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for record in records:
        normalized.append(
            {
                **record,
                "industry": record.get("name") or record.get("industry"),
                "leading_stock": record.get("leading") or record.get("leading_stock"),
                "leading_stock_pct_change": record.get("leading_pct") or record.get("leading_stock_pct_change"),
                "market_cap": record.get("total_mv") or record.get("market_cap"),
                "rising_count": record.get("up_num") or record.get("rising_count"),
                "falling_count": record.get("down_num") or record.get("falling_count"),
            }
        )
    return normalized


def _latest_trade_date_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    dated = [record for record in records if record.get("trade_date")]
    if not dated:
        return records
    latest = max(str(record.get("trade_date") or "") for record in dated)
    return [record for record in dated if str(record.get("trade_date") or "") == latest]


def _normalize_sector_rank_rows(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for index, record in enumerate(records, start=1):
        name = str(_first_value(record, ("板块名称", "板块", "名称", "行业", "industry", "index_name", "name")) or "").strip()
        if not name:
            continue
        pct_change = _first_float(record, ("涨跌幅", "change_pct", "pct_chg", "pct_change", "pct_change_rate"))
        rows.append(
            {
                "rank": _to_int(_first_value(record, ("排名", "序号", "rank"))) or index,
                "name": name,
                "code": str(_first_value(record, ("板块代码", "代码", "ts_code", "index_code", "code")) or "").strip(),
                "latest": _first_float(record, ("最新价", "最新", "均价", "close", "price", "latest")),
                "change": _first_float(record, ("涨跌额", "change")),
                "pctChange": pct_change,
                "marketCap": _first_float(record, ("总市值", "market_cap")),
                "turnoverRate": _first_float(record, ("换手率", "turnover_rate")),
                "risingCount": _to_int(_first_value(record, ("上涨家数", "rising_count"))),
                "fallingCount": _to_int(_first_value(record, ("下跌家数", "falling_count"))),
                "leadingStock": str(_first_value(record, ("领涨股票", "领涨股", "leading_stock")) or "").strip(),
                "leadingStockPctChange": _first_float(record, ("领涨股票-涨跌幅", "领涨股-涨跌幅", "leading_stock_pct_change")),
            }
        )
    return rows


def _normalize_kline_rows(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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


def _normalize_fund_flow_rows(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for record in records:
        trade_date = _date_to_yyyymmdd(_first_value(record, ("trade_date", "date", "日期", "时间"))) or ""
        if not trade_date:
            continue
        main_buy = sum(
            _to_float(record.get(key)) or 0.0
            for key in ("buy_lg_amount", "buy_elg_amount", "buy_lg_amt", "buy_elg_amt")
        )
        main_sell = sum(
            _to_float(record.get(key)) or 0.0
            for key in ("sell_lg_amount", "sell_elg_amount", "sell_lg_amt", "sell_elg_amt")
        )
        small_buy = sum(
            _to_float(record.get(key)) or 0.0
            for key in ("buy_sm_amount", "buy_md_amount", "buy_sm_amt", "buy_md_amt")
        )
        small_sell = sum(
            _to_float(record.get(key)) or 0.0
            for key in ("sell_sm_amount", "sell_md_amount", "sell_sm_amt", "sell_md_amt")
        )
        direct_main_net = _first_float(
            record,
            ("mainNetAmount", "主力净流入-净额", "主力净流入净额", "主力净流入", "主力净额"),
        )
        mid_net = _first_float(record, ("中单净流入-净额", "中单净流入净额", "中单净流入"))
        direct_small_net = _first_float(record, ("小单净流入-净额", "小单净流入净额", "小单净流入"))
        main_net = direct_main_net if direct_main_net is not None else main_buy - main_sell
        small_net = (
            (mid_net or 0.0) + (direct_small_net or 0.0)
            if mid_net is not None or direct_small_net is not None
            else small_buy - small_sell
        )
        net_amount = _first_float(
            record,
            ("net_mf_amount", "net_amount", "net_buy_amount", "net_inflow", "net_mf_amt", "净流入", "净额"),
        )
        if net_amount is None:
            net_amount = main_net if direct_main_net is not None else main_net + small_net
        rows.append(
            {
                "tradeDate": trade_date,
                "netAmount": net_amount,
                "mainNetAmount": main_net,
                "smallNetAmount": small_net,
                "raw": record,
            }
        )
    rows.sort(key=lambda item: item["tradeDate"])
    return rows


def _build_market_temperature(indices: List[Dict[str, Any]], fund_flow: Dict[str, Any]) -> Dict[str, Any]:
    ready_indices = [item for item in indices if item.get("status") == "READY" and item.get("latest")]
    review_only = any(item.get("reviewOnly") for item in ready_indices) or bool(fund_flow.get("reviewOnly"))
    if not ready_indices:
        return {
            "score": 0,
            "label": "不可用",
            "status": "FAIL",
            "trendScore": 0,
            "breadthScore": 0,
            "flowScore": 0,
            "risingCount": 0,
            "fallingCount": 0,
            "reasons": ["指数 K 线不可用"],
            "reviewOnly": False,
        }

    trend_scores = [_index_trend_score(item) for item in ready_indices]
    trend_score = sum(trend_scores) / len(trend_scores)
    rising_count = sum(1 for item in ready_indices if (_to_float(item["latest"].get("pctChange")) or 0) > 0)
    falling_count = sum(1 for item in ready_indices if (_to_float(item["latest"].get("pctChange")) or 0) < 0)
    breadth_score = (rising_count / len(ready_indices)) * 100
    flow_score = _fund_flow_score(fund_flow)
    score = round((trend_score * 0.45) + (breadth_score * 0.35) + (flow_score * 0.20))
    label, status = _temperature_label(score)
    reasons = [
        f"上涨指数 {rising_count}/{len(ready_indices)}",
        f"趋势得分 {round(trend_score)}",
    ]
    if review_only:
        label = "需复核"
        status = "WARN"
        reasons.insert(0, "指数或资金流存在多源冲突，市场温度仅供人工复核。")
    if fund_flow.get("status") == "READY":
        reasons.append(f"资金净流 {round(_to_float(fund_flow.get('netAmount')) or 0, 2)} 万元")
    else:
        reasons.append("资金流缺失")

    return {
        "score": score,
        "label": label,
        "status": status,
        "trendScore": round(trend_score),
        "breadthScore": round(breadth_score),
        "flowScore": round(flow_score),
        "risingCount": rising_count,
        "fallingCount": falling_count,
        "reasons": reasons,
        "reviewOnly": review_only,
    }


def _index_trend_score(index_payload: Dict[str, Any]) -> float:
    latest = index_payload.get("latest") or {}
    pct_change = _to_float(latest.get("pctChange")) or 0.0
    close = _to_float(latest.get("close"))
    ma20 = _to_float(latest.get("ma20"))
    score = 50 + pct_change * 6
    if close is not None and ma20 is not None:
        score += 10 if close >= ma20 else -10
    return _clamp(score, 0, 100)


def _fund_flow_score(fund_flow: Dict[str, Any]) -> float:
    if fund_flow.get("status") != "READY":
        return 50
    net_amount = _to_float(fund_flow.get("netAmount"))
    if net_amount is None:
        return 50
    return _clamp(50 + (net_amount / 100_000_000), 0, 100)


def _temperature_label(score: int) -> tuple[str, str]:
    if score >= 75:
        return "过热", "WARN"
    if score >= 60:
        return "偏暖", "PASS"
    if score >= 45:
        return "中性", "WARN"
    if score >= 30:
        return "偏冷", "WARN"
    return "冰点", "FAIL"


def _empty_overview(message: str, fetched_at: str, range_: str) -> Dict[str, Any]:
    indices = [_empty_index(item, range_, message) for item in INDEX_DEFINITIONS]
    return {
        "status": "FAILED",
        "dataMode": "UNAVAILABLE",
        "provider": "tushare+akshare+arbitration",
        "range": range_,
        "fetchedAt": fetched_at,
        "refreshIntervalSeconds": _global_market_refresh_interval_seconds(),
        "indices": indices,
        "fundFlow": _empty_fund_flow(message),
        "sectorRank": _empty_sector_rank(message, fetched_at),
        "temperature": {
            "score": 0,
            "label": "不可用",
            "status": "FAIL",
            "trendScore": 0,
            "breadthScore": 0,
            "flowScore": 0,
            "risingCount": 0,
            "fallingCount": 0,
            "reasons": [message],
            "reviewOnly": False,
        },
        "message": message,
        "error": message,
    }


def _moving_average(values: List[float], window: int) -> List[float | None]:
    result: List[float | None] = []
    total = 0.0
    for index, value in enumerate(values):
        total += value
        if index >= window:
            total -= values[index - window]
        if index < window - 1:
            result.append(None)
        else:
            result.append(total / window)
    return result


def _first_float(record: Dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = _to_float(record.get(key))
        if value is not None:
            return value
    return None


def _first_value(record: Dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return value
    return None


def _to_int(value: Any) -> int | None:
    number = _to_float(value)
    if number is None:
        return None
    return int(number)


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "").rstrip("%"))
    except (TypeError, ValueError):
        return None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _date_to_yyyymmdd(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    digits = "".join(ch for ch in text[:19] if ch.isdigit())
    if len(digits) >= 8:
        return digits[:8]
    return ""


def _cn_now() -> datetime:
    return datetime.now(CHINA_TZ)


def _today_trade_date() -> str:
    return _cn_now().strftime("%Y%m%d")


def _closed_trading_dates() -> set[str]:
    raw = os.getenv("AUTO_PAPER_CLOSED_TRADING_DATES", "")
    return {item.strip() for item in raw.split(",") if item.strip()}


def _is_a_share_trading_day(local_date: date) -> bool:
    closed_dates = _closed_trading_dates()
    return (
        local_date.weekday() < 5
        and local_date.isoformat() not in closed_dates
        and local_date.strftime("%Y%m%d") not in closed_dates
    )


def _latest_a_share_trading_date(local_date: date) -> str:
    cursor = local_date
    for _ in range(14):
        if _is_a_share_trading_day(cursor):
            return cursor.strftime("%Y%m%d")
        cursor -= timedelta(days=1)
    return local_date.strftime("%Y%m%d")


def _sector_rank_snapshot_trade_date() -> str:
    now = _cn_now()
    local_date = now.date()
    minute = now.hour * 60 + now.minute
    if _is_a_share_trading_day(local_date) and minute >= A_SHARE_MORNING_START_MINUTE:
        return local_date.strftime("%Y%m%d")
    return _latest_a_share_trading_date(local_date - timedelta(days=1))


def _is_a_share_trading_session() -> bool:
    now = _cn_now()
    local_date = now.date()
    if not _is_a_share_trading_day(local_date):
        return False

    minute = now.hour * 60 + now.minute
    in_morning = A_SHARE_MORNING_START_MINUTE <= minute <= A_SHARE_MORNING_END_MINUTE
    in_afternoon = A_SHARE_AFTERNOON_START_MINUTE <= minute < A_SHARE_AFTERNOON_END_MINUTE
    return in_morning or in_afternoon


def _is_post_close() -> bool:
    now = _cn_now()
    return now.hour > 15 or (now.hour == 15 and now.minute >= 0)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
