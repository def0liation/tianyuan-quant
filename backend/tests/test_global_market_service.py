import json
from datetime import datetime

from app.core import global_market_service
from app.models.agent_runtime import MarketDataProfile


def _profile(api_key: str = "token") -> MarketDataProfile:
    return MarketDataProfile(
        id="global-market-test",
        label="Global market test",
        provider="tushare",
        base_url="http://api.tushare.pro",
        api_key=api_key,
        enabled=True,
        timeout_seconds=3,
    )


def _kline_payload(ts_code: str, close_offset: float = 0.0):
    fields = ["ts_code", "trade_date", "open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount"]
    items = []
    base = 3000.0 if ts_code != "399006.SZ" else 1900.0
    for day in range(1, 23):
        close = base + day * 8 + close_offset
        pct = 0.4 if day == 22 else 0.1
        if ts_code == "399001.SZ" and day == 22:
            pct = -0.2
        items.append([
            ts_code,
            f"202605{day:02d}",
            close - 5,
            close + 10,
            close - 12,
            close,
            close - 4,
            4,
            pct,
            100000 + day,
            200000 + day,
        ])
    return {"data": {"fields": fields, "items": items}}


def _moneyflow_payload():
    fields = [
        "trade_date",
        "net_mf_amount",
        "buy_lg_amount",
        "buy_elg_amount",
        "sell_lg_amount",
        "sell_elg_amount",
        "buy_sm_amount",
        "buy_md_amount",
        "sell_sm_amount",
        "sell_md_amount",
    ]
    items = [
        ["20260520", 120_000_000.0, 1000.0, 800.0, 700.0, 400.0, 500.0, 600.0, 400.0, 300.0],
    ]
    return {"data": {"fields": fields, "items": items}}


def _sector_rank_payload():
    return {
        "status": "READY",
        "dataMode": "LIVE",
        "provider": "akshare",
        "source": "eastmoney",
        "apiName": "stock_board_industry_name_em",
        "boardType": "industry",
        "tradeDate": "20260520",
        "fetchedAt": "2026-05-20T03:00:00+00:00",
        "recordCount": 2,
        "top": [
            {
                "rank": 1,
                "name": "半导体",
                "code": "BK1036",
                "latest": 1234.5,
                "change": 24.5,
                "pctChange": 2.8,
                "marketCap": 1000000000.0,
                "turnoverRate": 3.2,
                "risingCount": 40,
                "fallingCount": 5,
                "leadingStock": "测试科技",
                "leadingStockPctChange": 10.0,
            }
        ],
        "bottom": [
            {
                "rank": 2,
                "name": "银行",
                "code": "BK0475",
                "latest": 800.0,
                "change": -4.0,
                "pctChange": -0.5,
                "marketCap": 900000000.0,
                "turnoverRate": 0.8,
                "risingCount": 8,
                "fallingCount": 16,
                "leadingStock": "测试银行",
                "leadingStockPctChange": 1.0,
            }
        ],
        "rows": [],
        "message": "实时行业板块涨跌幅榜返回 2 条记录。",
        "error": "",
    }


def _disable_akshare_market_sources(monkeypatch):
    def failed_index(definition, fetched_at):
        return global_market_service._failed_market_source(
            source_id="akshare_index_spot",
            provider="akshare",
            source="eastmoney",
            api_name="stock_zh_index_spot_em",
            message="akshare unavailable",
            fetched_at=fetched_at,
        )

    def failed_fund_flow(fetched_at):
        return global_market_service._failed_market_source(
            source_id="akshare_market_fund_flow",
            provider="akshare",
            source="eastmoney",
            api_name="stock_market_fund_flow",
            message="akshare fund flow unavailable",
            fetched_at=fetched_at,
        )

    monkeypatch.setattr(global_market_service, "_fetch_akshare_index_quote_source", failed_index)
    monkeypatch.setattr(global_market_service, "_fetch_akshare_fund_flow_source", failed_fund_flow)


def _ready_index_source(source_id: str, provider: str, trade_date: str, close: float, pct: float, volume: float = 1000.0):
    return global_market_service._ready_market_source(
        source_id=source_id,
        provider=provider,
        source="eastmoney" if provider == "akshare" else "tushare",
        api_name="stock_zh_index_spot_em" if provider == "akshare" else "index_daily",
        data_mode="LIVE" if provider == "akshare" else "FALLBACK",
        freshness="REALTIME" if provider == "akshare" else "EOD",
        trade_date=trade_date,
        fetched_at="2026-05-22T07:10:00+00:00",
        confidence=0.88 if provider == "akshare" else 0.82,
        record_count=1,
        latest={
            "tradeDate": trade_date,
            "open": close - 5,
            "high": close + 8,
            "low": close - 9,
            "close": close,
            "pctChange": pct,
            "volume": volume,
            "amount": volume * close,
        },
        rows=[],
        message=f"{provider} ready",
    )


def _daily_rows(last_day: int = 21):
    rows = []
    for day in range(1, last_day + 1):
        close = 3000.0 + day
        rows.append(
            {
                "tradeDate": f"202605{day:02d}",
                "open": close - 2,
                "high": close + 4,
                "low": close - 5,
                "close": close,
                "preClose": close - 1,
                "change": 1.0,
                "pctChange": 0.03,
                "volume": 1000.0 + day,
                "amount": 2000.0 + day,
            }
        )
    return rows


def _ready_tushare_daily_source(last_day: int = 21):
    rows = _daily_rows(last_day)
    return global_market_service._ready_market_source(
        source_id="tushare_index_daily",
        provider="tushare",
        source="tushare",
        api_name="index_daily",
        data_mode="FALLBACK",
        freshness="EOD" if last_day == 22 else "STALE",
        trade_date=rows[-1]["tradeDate"],
        fetched_at="2026-05-22T02:00:00+00:00",
        confidence=0.82,
        record_count=len(rows),
        latest=rows[-1],
        rows=rows,
        message="tushare daily ready",
    )


def _ready_fund_source(source_id: str, provider: str, trade_date: str, net_amount: float):
    return global_market_service._ready_market_source(
        source_id=source_id,
        provider=provider,
        source="eastmoney" if provider == "akshare" else "tushare",
        api_name="stock_market_fund_flow" if provider == "akshare" else "moneyflow_mkt_dc",
        data_mode="LIVE" if provider == "akshare" else "FALLBACK",
        freshness="REALTIME" if provider == "akshare" else "EOD",
        trade_date=trade_date,
        fetched_at="2026-05-22T07:10:00+00:00",
        confidence=0.86 if provider == "akshare" else 0.82,
        record_count=1,
        latest={
            "tradeDate": trade_date,
            "netAmount": net_amount,
            "mainNetAmount": net_amount,
            "smallNetAmount": 0.0,
        },
        rows=[
            {
                "tradeDate": trade_date,
                "netAmount": net_amount,
                "mainNetAmount": net_amount,
                "smallNetAmount": 0.0,
            }
        ],
        message=f"{provider} ready",
    )


def test_global_market_payload_builds_indices_flow_and_temperature(monkeypatch):
    global_market_service._GLOBAL_MARKET_CACHE.clear()
    _disable_akshare_market_sources(monkeypatch)
    monkeypatch.setattr(global_market_service, "get_default_market_data_profile", lambda: _profile())
    monkeypatch.setattr(global_market_service, "_fetch_sector_rank_payload", _sector_rank_payload)

    def fake_call(profile, api_name, params):
        if api_name == "index_daily":
            return _kline_payload(params["ts_code"])
        if api_name == "moneyflow_mkt_dc":
            return _moneyflow_payload()
        raise AssertionError(api_name)

    monkeypatch.setattr(global_market_service, "_call_tushare_http_api_raw", fake_call)

    payload = global_market_service.get_global_market_payload()

    assert payload["status"] == "READY"
    assert payload["dataMode"] == "LIVE"
    assert payload["range"] == "4m"
    assert len(payload["indices"]) == 4
    assert payload["indices"][0]["name"] == "沪深300"
    assert payload["indices"][0]["latest"]["ma5"] is not None
    assert payload["indices"][0]["latest"]["ma10"] is not None
    assert payload["indices"][0]["latest"]["ma20"] is not None
    assert payload["fundFlow"]["status"] == "READY"
    assert payload["fundFlow"]["unit"] == "元"
    assert payload["fundFlow"]["netAmount"] == 120_000_000.0
    assert payload["temperature"]["score"] > 50
    assert payload["temperature"]["flowScore"] == 51
    assert payload["temperature"]["risingCount"] == 3
    assert payload["sectorRank"]["status"] == "READY"
    assert payload["sectorRank"]["top"][0]["name"] == "半导体"


def test_global_market_payload_without_token_does_not_call_upstream(monkeypatch):
    global_market_service._GLOBAL_MARKET_CACHE.clear()
    _disable_akshare_market_sources(monkeypatch)
    monkeypatch.setattr(global_market_service, "get_default_market_data_profile", lambda: _profile(api_key=""))
    monkeypatch.setattr(global_market_service, "_fetch_sector_rank_payload", _sector_rank_payload)

    def fail_call(*args, **kwargs):
        raise AssertionError("tushare upstream should not be called without token")

    monkeypatch.setattr(global_market_service, "_call_tushare_http_api_raw", fail_call)

    payload = global_market_service.get_global_market_payload()

    assert payload["status"] == "PARTIAL"
    assert payload["dataMode"] == "LIVE"
    assert payload["indices"][0]["status"] == "FAILED"
    assert payload["temperature"]["label"] == "不可用"
    assert payload["sectorRank"]["status"] == "READY"


def test_global_market_cache_changes_when_token_changes(monkeypatch):
    global_market_service._GLOBAL_MARKET_CACHE.clear()
    _disable_akshare_market_sources(monkeypatch)
    token_state = {"value": "token-a"}

    monkeypatch.setattr(global_market_service, "get_default_market_data_profile", lambda: _profile(api_key=token_state["value"]))
    monkeypatch.setattr(global_market_service, "_fetch_sector_rank_payload", _sector_rank_payload)

    def fake_call(profile, api_name, params):
        if api_name == "index_daily":
            offset = 0.0 if profile.api_key == "token-a" else 100.0
            return _kline_payload(params["ts_code"], close_offset=offset)
        if api_name == "moneyflow_mkt_dc":
            return _moneyflow_payload()
        raise AssertionError(api_name)

    monkeypatch.setattr(global_market_service, "_call_tushare_http_api_raw", fake_call)

    first = global_market_service.get_global_market_payload()
    token_state["value"] = "token-b"
    second = global_market_service.get_global_market_payload()

    assert first["indices"][0]["latest"]["close"] != second["indices"][0]["latest"]["close"]


def test_tushare_index_daily_retries_transient_timeout(monkeypatch):
    calls = []
    monkeypatch.setattr(global_market_service, "_TUSHARE_INDEX_DAILY_RETRY_DELAY_SECONDS", 0)

    def fake_call(profile, api_name, params):
        calls.append({"api_name": api_name, "params": dict(params), "timeout_seconds": profile.timeout_seconds})
        if len(calls) == 1:
            raise RuntimeError("<urlopen error _ssl.c:1015: The handshake operation timed out>")
        return _kline_payload(params["ts_code"])

    monkeypatch.setattr(global_market_service, "_call_tushare_http_api_raw", fake_call)

    payload = global_market_service._fetch_tushare_index_source(
        _profile(),
        global_market_service.INDEX_DEFINITIONS[0],
        "20260201",
        "20260522",
        "4m",
        "2026-05-22T02:00:00+00:00",
    )

    assert payload["status"] == "READY"
    assert payload["sourceId"] == "tushare_index_daily"
    assert payload["recordCount"] == 22
    assert [call["api_name"] for call in calls] == ["index_daily", "index_daily"]
    assert calls[0]["params"]["ts_code"] == "000300.SH"
    assert calls[0]["timeout_seconds"] == 4


def test_index_arbitration_uses_akshare_when_tushare_missing(monkeypatch):
    monkeypatch.setattr(global_market_service, "_today_trade_date", lambda: "20260522")
    monkeypatch.setattr(global_market_service, "_is_post_close", lambda: False)
    akshare_ready = _ready_index_source("akshare_index_spot", "akshare", "20260522", 3010.0, 0.62)
    tushare_failed = global_market_service._failed_market_source(
        source_id="tushare_index_daily",
        provider="tushare",
        source="tushare",
        api_name="index_daily",
        message="tushare missing",
        fetched_at="2026-05-22T07:10:00+00:00",
    )

    payload = global_market_service._arbitrate_index_sources(
        global_market_service.INDEX_DEFINITIONS[0],
        "4m",
        [akshare_ready, tushare_failed],
        "2026-05-22T07:10:00+00:00",
    )

    assert payload["selectedSource"] == "akshare_index_spot"
    assert payload["fallbackUsed"] is False
    assert payload["sourceConsensus"] == "SINGLE_SOURCE"


def test_index_arbitration_falls_back_to_tushare_when_akshare_fails(monkeypatch):
    monkeypatch.setattr(global_market_service, "_today_trade_date", lambda: "20260522")
    akshare_failed = global_market_service._failed_market_source(
        source_id="akshare_index_spot",
        provider="akshare",
        source="eastmoney",
        api_name="stock_zh_index_spot_em",
        message="akshare missing",
        fetched_at="2026-05-22T07:10:00+00:00",
    )
    tushare_ready = _ready_index_source("tushare_index_daily", "tushare", "20260522", 3008.0, 0.60)

    payload = global_market_service._arbitrate_index_sources(
        global_market_service.INDEX_DEFINITIONS[0],
        "4m",
        [akshare_failed, tushare_ready],
        "2026-05-22T07:10:00+00:00",
    )

    assert payload["selectedSource"] == "tushare_index_daily"
    assert payload["fallbackUsed"] is True
    assert payload["dataMode"] == "FALLBACK"


def test_trading_session_keeps_daily_k_on_tushare_rows_with_realtime_quote(monkeypatch):
    monkeypatch.setattr(
        global_market_service,
        "_cn_now",
        lambda: datetime(2026, 5, 22, 10, 0, tzinfo=global_market_service.CHINA_TZ),
    )
    tushare_ready = _ready_tushare_daily_source(last_day=21)
    akshare_ready = _ready_index_source("akshare_index_spot", "akshare", "20260522", 3023.0, 0.55)

    payload = global_market_service._arbitrate_index_sources(
        global_market_service.INDEX_DEFINITIONS[0],
        "4m",
        [akshare_ready, tushare_ready],
        "2026-05-22T02:00:00+00:00",
    )

    assert payload["status"] == "READY"
    assert payload["selectedSource"] == "akshare_index_spot"
    assert payload["dataMode"] == "LIVE"
    assert payload["dailyRenderMode"] == "TUSHARE_STALE"
    assert "minuteStatus" not in payload
    assert "minuteRows" not in payload
    assert "minuteMessage" not in payload
    assert payload["lastTradeDate"] == "20260521"
    assert payload["latest"]["close"] == 3023.0
    assert payload["rows"][-1]["tradeDate"] == "20260521"
    assert not payload["rows"][-1].get("derived")


def test_trading_session_keeps_tushare_daily_without_minute_payload(monkeypatch):
    monkeypatch.setattr(
        global_market_service,
        "_cn_now",
        lambda: datetime(2026, 5, 22, 10, 0, tzinfo=global_market_service.CHINA_TZ),
    )

    payload = global_market_service._arbitrate_index_sources(
        global_market_service.INDEX_DEFINITIONS[0],
        "4m",
        [_ready_tushare_daily_source(last_day=21)],
        "2026-05-22T02:00:00+00:00",
    )

    assert payload["status"] == "READY"
    assert "minuteStatus" not in payload
    assert "minuteRows" not in payload
    assert "minuteMessage" not in payload
    assert payload["dailyRenderMode"] == "TUSHARE_STALE"
    assert payload["rows"][-1]["tradeDate"] == "20260521"
    assert not payload["rows"][-1].get("derived")


def test_non_trading_session_skips_akshare_index_sources(monkeypatch):
    monkeypatch.setattr(
        global_market_service,
        "_cn_now",
        lambda: datetime(2026, 5, 22, 12, 0, tzinfo=global_market_service.CHINA_TZ),
    )
    monkeypatch.setattr(
        global_market_service,
        "_fetch_akshare_index_quote_source",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("quote should be skipped")),
    )
    monkeypatch.setattr(
        global_market_service,
        "_call_tushare_http_api_raw",
        lambda profile, api_name, params: _kline_payload(params["ts_code"]),
    )

    payload = global_market_service._fetch_index_payload(
        _profile(),
        global_market_service.INDEX_DEFINITIONS[0],
        "20260201",
        "20260522",
        "4m",
    )

    assert payload["status"] == "READY"
    assert payload["selectedSource"] == "tushare_index_daily"
    assert "minuteStatus" not in payload
    assert payload["dailyRenderMode"] == "TUSHARE_EOD"
    assert payload["rows"][-1]["tradeDate"] == "20260522"


def test_closed_trading_date_skips_intraday_sources(monkeypatch):
    monkeypatch.setenv("AUTO_PAPER_CLOSED_TRADING_DATES", "2026-05-22")
    monkeypatch.setattr(
        global_market_service,
        "_cn_now",
        lambda: datetime(2026, 5, 22, 10, 0, tzinfo=global_market_service.CHINA_TZ),
    )

    assert global_market_service._is_a_share_trading_session() is False


def test_global_market_refresh_interval_uses_trading_session(monkeypatch):
    monkeypatch.setattr(
        global_market_service,
        "_cn_now",
        lambda: datetime(2026, 5, 22, 10, 0, tzinfo=global_market_service.CHINA_TZ),
    )
    assert global_market_service._global_market_refresh_interval_seconds() == 300

    monkeypatch.setattr(
        global_market_service,
        "_cn_now",
        lambda: datetime(2026, 5, 22, 16, 0, tzinfo=global_market_service.CHINA_TZ),
    )
    assert global_market_service._global_market_refresh_interval_seconds() == 300


def test_tushare_today_daily_k_is_not_duplicated(monkeypatch):
    monkeypatch.setattr(
        global_market_service,
        "_cn_now",
        lambda: datetime(2026, 5, 22, 10, 0, tzinfo=global_market_service.CHINA_TZ),
    )
    tushare_ready = _ready_tushare_daily_source(last_day=22)

    payload = global_market_service._arbitrate_index_sources(
        global_market_service.INDEX_DEFINITIONS[0],
        "4m",
        [tushare_ready],
        "2026-05-22T02:00:00+00:00",
    )

    assert payload["dailyRenderMode"] == "TUSHARE_EOD"
    assert len(payload["rows"]) == 22
    assert not payload["rows"][-1].get("derived")


def test_trading_index_payload_omits_minute_fields(monkeypatch):
    monkeypatch.setattr(
        global_market_service,
        "_cn_now",
        lambda: datetime(2026, 5, 22, 10, 0, tzinfo=global_market_service.CHINA_TZ),
    )
    monkeypatch.setattr(
        global_market_service,
        "_fetch_akshare_index_quote_source",
        lambda definition, fetched_at: _ready_index_source("akshare_index_spot", "akshare", "20260522", 3022.0, 0.42),
    )
    monkeypatch.setattr(
        global_market_service,
        "_call_tushare_http_api_raw",
        lambda profile, api_name, params: _kline_payload(params["ts_code"]),
    )

    payload = global_market_service._fetch_index_payload(
        _profile(),
        global_market_service.INDEX_DEFINITIONS[0],
        "20260201",
        "20260522",
        "4m",
    )

    assert payload["status"] == "READY"
    assert payload["selectedSource"] == "akshare_index_spot"
    assert "minuteStatus" not in payload
    assert "minuteRows" not in payload
    assert "minuteMessage" not in payload


def test_post_close_akshare_today_tushare_yesterday_marks_pending_eod(monkeypatch):
    monkeypatch.setattr(global_market_service, "_today_trade_date", lambda: "20260522")
    monkeypatch.setattr(global_market_service, "_is_post_close", lambda: True)
    akshare_ready = _ready_index_source("akshare_index_spot", "akshare", "20260522", 3010.0, 0.62)
    tushare_yesterday = _ready_index_source("tushare_index_daily", "tushare", "20260521", 2990.0, -0.10)

    payload = global_market_service._arbitrate_index_sources(
        global_market_service.INDEX_DEFINITIONS[0],
        "4m",
        [akshare_ready, tushare_yesterday],
        "2026-05-22T07:10:00+00:00",
    )

    assert payload["selectedSource"] == "akshare_index_spot"
    assert payload["freshness"] == "POST_CLOSE_PENDING_EOD"
    assert payload["sourceConsensus"] == "SINGLE_SOURCE"


def test_same_day_sources_consensus_uses_tushare_after_close(monkeypatch):
    monkeypatch.setattr(global_market_service, "_today_trade_date", lambda: "20260522")
    monkeypatch.setattr(global_market_service, "_is_post_close", lambda: True)
    akshare_ready = _ready_index_source("akshare_index_spot", "akshare", "20260522", 3000.5, 0.62)
    tushare_ready = _ready_index_source("tushare_index_daily", "tushare", "20260522", 3000.0, 0.61)

    payload = global_market_service._arbitrate_index_sources(
        global_market_service.INDEX_DEFINITIONS[0],
        "4m",
        [akshare_ready, tushare_ready],
        "2026-05-22T07:10:00+00:00",
    )

    assert payload["selectedSource"] == "tushare_index_daily"
    assert payload["sourceConsensus"] == "CONSENSUS"
    assert payload["reviewOnly"] is False


def test_same_day_source_conflict_marks_review_only(monkeypatch):
    monkeypatch.setattr(global_market_service, "_today_trade_date", lambda: "20260522")
    monkeypatch.setattr(global_market_service, "_is_post_close", lambda: True)
    akshare_ready = _ready_index_source("akshare_index_spot", "akshare", "20260522", 3010.0, 0.62)
    tushare_ready = _ready_index_source("tushare_index_daily", "tushare", "20260522", 3000.0, 0.55)

    payload = global_market_service._arbitrate_index_sources(
        global_market_service.INDEX_DEFINITIONS[0],
        "4m",
        [akshare_ready, tushare_ready],
        "2026-05-22T07:10:00+00:00",
    )

    assert payload["sourceConsensus"] == "DIVERGED"
    assert payload["reviewOnly"] is True
    assert any(conflict["field"] == "close" for conflict in payload["conflicts"])


def test_same_day_medium_index_conflict_marks_review_only(monkeypatch):
    monkeypatch.setattr(global_market_service, "_today_trade_date", lambda: "20260522")
    monkeypatch.setattr(global_market_service, "_is_post_close", lambda: True)
    akshare_ready = _ready_index_source("akshare_index_spot", "akshare", "20260522", 3000.0, 0.60, volume=1000.0)
    tushare_ready = _ready_index_source("tushare_index_daily", "tushare", "20260522", 3000.0, 0.60, volume=1100.0)

    payload = global_market_service._arbitrate_index_sources(
        global_market_service.INDEX_DEFINITIONS[0],
        "4m",
        [akshare_ready, tushare_ready],
        "2026-05-22T07:10:00+00:00",
    )

    assert payload["sourceConsensus"] == "DIVERGED"
    assert payload["reviewOnly"] is True
    assert payload["arbitration"]["dataQuality"]["level"] == "REVIEW_ONLY"
    assert {conflict["field"] for conflict in payload["conflicts"]} == {"volume", "amount"}


def test_fund_flow_conflict_marks_review_only(monkeypatch):
    monkeypatch.setattr(global_market_service, "_today_trade_date", lambda: "20260522")
    monkeypatch.setattr(global_market_service, "_is_post_close", lambda: True)
    akshare_ready = _ready_fund_source("akshare_market_fund_flow", "akshare", "20260522", 220_000_000.0)
    tushare_ready = _ready_fund_source("tushare_moneyflow_mkt_dc", "tushare", "20260522", 100_000_000.0)

    payload = global_market_service._arbitrate_fund_flow_sources(
        [akshare_ready, tushare_ready],
        "2026-05-22T07:10:00+00:00",
    )

    assert payload["sourceConsensus"] == "DIVERGED"
    assert payload["reviewOnly"] is True
    assert payload["selectedSource"] == "tushare_moneyflow_mkt_dc"
    assert payload["conflicts"][0]["field"] == "netAmount"


def test_sector_rank_rows_are_normalized_and_sorted():
    rows = global_market_service._normalize_sector_rank_rows(
        [
            {"排名": 2, "板块名称": "银行", "板块代码": "BK0475", "涨跌幅": "-0.5%", "上涨家数": 8, "下跌家数": 16},
            {"排名": 1, "板块名称": "半导体", "板块代码": "BK1036", "涨跌幅": 2.8, "领涨股票": "测试科技", "领涨股票-涨跌幅": "10.0"},
        ]
    )

    ranked = sorted(rows, key=lambda item: item["pctChange"], reverse=True)

    assert ranked[0]["name"] == "半导体"
    assert ranked[0]["leadingStock"] == "测试科技"
    assert ranked[0]["leadingStockPctChange"] == 10.0
    assert ranked[1]["pctChange"] == -0.5


def test_sector_rank_arbitration_falls_back_to_tushare_source():
    fetched_at = "2026-05-21T03:00:00+00:00"
    akshare_failed = global_market_service._failed_sector_source(
        source_id="akshare_eastmoney",
        provider="akshare",
        source="eastmoney",
        api_name="stock_board_industry_name_em",
        message="akshare unavailable",
        fetched_at=fetched_at,
    )
    tushare_ready = global_market_service._ready_sector_source(
        source_id="tushare_moneyflow_ind_ths",
        provider="tushare",
        source="ths",
        api_name="moneyflow_ind_ths",
        fetched_at=fetched_at,
        confidence=0.80,
        rows=[
            {"name": "半导体", "code": "884123.TI", "pctChange": 2.4, "latest": 1234.0},
            {"name": "银行", "code": "884001.TI", "pctChange": -0.6, "latest": 900.0},
        ],
        message="tushare ready",
    )

    payload = global_market_service._arbitrate_sector_rank_sources([akshare_failed, tushare_ready], fetched_at)

    assert payload["status"] == "READY"
    assert payload["provider"] == "multi-source"
    assert payload["selectedSource"] == "tushare_moneyflow_ind_ths"
    assert payload["sourceCount"] == {"ready": 1, "total": 2}
    assert payload["arbitration"]["sourceConsensus"] == "SINGLE_SOURCE"
    assert payload["candidateSources"][0]["status"] == "FAILED"
    assert payload["top"][0]["name"] == "半导体"


def test_eastmoney_direct_sector_rank_uses_previous_close_on_non_trading_day(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        @staticmethod
        def read():
            return json.dumps({
                "data": {
                    "diff": [
                        {
                            "f2": 1234.5,
                            "f3": 2.8,
                            "f4": 24.5,
                            "f8": 3.2,
                            "f12": "BK1036",
                            "f14": "半导体",
                            "f20": 1000000000.0,
                            "f104": 40,
                            "f105": 5,
                            "f128": "测试科技",
                            "f136": 10.0,
                        },
                        {
                            "f2": 800.0,
                            "f3": -0.5,
                            "f4": -4.0,
                            "f8": 0.8,
                            "f12": "BK0475",
                            "f14": "银行",
                            "f20": 900000000.0,
                            "f104": 8,
                            "f105": 16,
                            "f128": "测试银行",
                            "f136": 1.0,
                        },
                    ]
                }
            }).encode("utf-8")

    monkeypatch.setattr(
        global_market_service,
        "_cn_now",
        lambda: datetime(2026, 5, 23, 10, 0, tzinfo=global_market_service.CHINA_TZ),
    )
    monkeypatch.setattr(global_market_service, "urlopen", lambda request, timeout: FakeResponse())

    payload = global_market_service._fetch_eastmoney_sector_rank_payload("2026-05-23T02:00:00+00:00")

    assert payload["status"] == "READY"
    assert payload["sourceId"] == "eastmoney_clist"
    assert payload["dataMode"] == "FALLBACK"
    assert payload["tradeDate"] == "20260522"
    assert payload["top"][0]["name"] == "半导体"
    assert payload["bottom"][0]["name"] == "银行"


def test_akshare_ths_sector_rank_uses_previous_close_on_non_trading_day(monkeypatch):
    class FakeFrame:
        @staticmethod
        def to_dict(orient):
            assert orient == "records"
            return [
                {
                    "序号": 1,
                    "板块": "元件",
                    "涨跌幅": 7.85,
                    "均价": 65.93,
                    "上涨家数": 61,
                    "下跌家数": 1,
                    "领涨股": "强达电路",
                    "领涨股-涨跌幅": 20.0,
                },
                {
                    "序号": 2,
                    "板块": "银行",
                    "涨跌幅": -0.5,
                    "均价": 8.0,
                    "上涨家数": 8,
                    "下跌家数": 16,
                    "领涨股": "测试银行",
                    "领涨股-涨跌幅": 1.0,
                },
            ]

    class FakeAkshare:
        @staticmethod
        def stock_board_industry_summary_ths():
            return FakeFrame()

    monkeypatch.setattr(
        global_market_service,
        "_cn_now",
        lambda: datetime(2026, 5, 23, 10, 0, tzinfo=global_market_service.CHINA_TZ),
    )
    monkeypatch.setattr(global_market_service, "_get_akshare_module", lambda: FakeAkshare())

    payload = global_market_service._fetch_akshare_ths_sector_rank_payload("2026-05-23T02:00:00+00:00")

    assert payload["status"] == "READY"
    assert payload["sourceId"] == "akshare_ths_summary"
    assert payload["dataMode"] == "FALLBACK"
    assert payload["tradeDate"] == "20260522"
    assert payload["top"][0]["name"] == "元件"
    assert payload["top"][0]["latest"] == 65.93
    assert payload["top"][0]["leadingStock"] == "强达电路"


def test_tushare_dc_index_sector_rank_uses_recent_available_trade_date(monkeypatch):
    calls = []

    def fake_call(profile, api_name, params):
        calls.append((api_name, params))
        if params.get("trade_date"):
            return {"data": {"fields": ["trade_date", "ts_code", "name", "pct_change"], "items": []}}
        return {
            "data": {
                "fields": [
                    "trade_date",
                    "ts_code",
                    "name",
                    "pct_change",
                    "leading",
                    "leading_pct",
                    "total_mv",
                    "turnover_rate",
                    "up_num",
                    "down_num",
                ],
                "items": [
                    ["20260519", "BK0001.DC", "old-sector", 0.5, "old-leader", 1.1, 100.0, 0.8, 3, 2],
                    ["20260520", "BK0002.DC", "semiconductor", 2.8, "leader-a", 10.0, 200.0, 3.2, 40, 5],
                    ["20260520", "BK0003.DC", "bank", -0.5, "leader-b", 1.0, 900.0, 0.6, 8, 16],
                ],
            }
        }

    monkeypatch.setattr(global_market_service, "_call_tushare_http_api_raw", fake_call)

    payload = global_market_service._fetch_tushare_dc_index_sector_rank_payload(_profile(), "2026-05-21T03:00:00+00:00")

    assert [call[0] for call in calls] == ["dc_index", "dc_index"]
    assert calls[0][1]["idx_type"] == "行业板块"
    assert payload["status"] == "READY"
    assert payload["sourceId"] == "tushare_dc_index"
    assert payload["dataMode"] == "FALLBACK"
    assert payload["tradeDate"] == "20260520"
    assert payload["recordCount"] == 2
    assert payload["top"][0]["name"] == "semiconductor"
    assert payload["top"][0]["leadingStock"] == "leader-a"
    assert payload["top"][0]["risingCount"] == 40


def test_tushare_moneyflow_sector_rank_uses_recent_available_trade_date(monkeypatch):
    calls = []

    def fake_call(profile, api_name, params):
        calls.append((api_name, params))
        if params.get("trade_date"):
            return {"data": {"fields": ["trade_date", "industry", "pct_change"], "items": []}}
        return {
            "data": {
                "fields": ["trade_date", "industry", "pct_change", "leading_stock", "leading_stock_pct_change"],
                "items": [
                    ["20260519", "old-sector", 0.5, "old-leader", 1.1],
                    ["20260522", "semiconductor", 2.8, "leader-a", 10.0],
                    ["20260522", "bank", -0.5, "leader-b", 1.0],
                ],
            }
        }

    monkeypatch.setattr(
        global_market_service,
        "_cn_now",
        lambda: datetime(2026, 5, 23, 10, 0, tzinfo=global_market_service.CHINA_TZ),
    )
    monkeypatch.setattr(global_market_service, "_call_tushare_http_api_raw", fake_call)

    payload = global_market_service._fetch_tushare_sector_rank_payload(_profile(), "2026-05-23T02:00:00+00:00")

    assert [call[0] for call in calls] == ["moneyflow_ind_ths", "moneyflow_ind_ths"]
    assert calls[0][1]["trade_date"] == "20260523"
    assert calls[1][1]["end_date"] == "20260523"
    assert payload["status"] == "READY"
    assert payload["dataMode"] == "FALLBACK"
    assert payload["tradeDate"] == "20260522"
    assert payload["recordCount"] == 2
    assert payload["top"][0]["name"] == "semiconductor"


def test_sector_rank_arbitration_prefers_tushare_dc_over_tushare_moneyflow_when_akshare_fails():
    fetched_at = "2026-05-21T03:00:00+00:00"
    akshare_failed = global_market_service._failed_sector_source(
        source_id="akshare_eastmoney",
        provider="akshare",
        source="eastmoney",
        api_name="stock_board_industry_name_em",
        message="akshare unavailable",
        fetched_at=fetched_at,
    )
    tushare_dc_ready = global_market_service._ready_sector_source(
        source_id="tushare_dc_index",
        provider="tushare",
        source="eastmoney",
        api_name="dc_index",
        fetched_at=fetched_at,
        confidence=0.82,
        rows=[{"name": "semiconductor", "code": "BK1036.DC", "pctChange": 2.8, "latest": 1234.0}],
        message="dc ready",
    )
    tushare_moneyflow_ready = global_market_service._ready_sector_source(
        source_id="tushare_moneyflow_ind_ths",
        provider="tushare",
        source="ths",
        api_name="moneyflow_ind_ths",
        fetched_at=fetched_at,
        confidence=0.80,
        rows=[{"name": "bank", "code": "881001.TI", "pctChange": 1.2, "latest": 900.0}],
        message="moneyflow ready",
    )

    payload = global_market_service._arbitrate_sector_rank_sources(
        [akshare_failed, tushare_dc_ready, tushare_moneyflow_ready],
        fetched_at,
    )

    assert payload["selectedSource"] == "tushare_dc_index"
    assert payload["sourceCount"] == {"ready": 2, "total": 3}


def test_sector_rank_arbitration_marks_conflicts_between_sources():
    fetched_at = "2026-05-21T03:00:00+00:00"
    akshare_ready = global_market_service._ready_sector_source(
        source_id="akshare_eastmoney",
        provider="akshare",
        source="eastmoney",
        api_name="stock_board_industry_name_em",
        fetched_at=fetched_at,
        confidence=0.88,
        rows=[
            {"name": "半导体", "code": "BK1036", "pctChange": 2.8, "latest": 1234.0},
            {"name": "银行", "code": "BK0475", "pctChange": -0.5, "latest": 800.0},
        ],
        message="akshare ready",
    )
    tushare_ready = global_market_service._ready_sector_source(
        source_id="tushare_moneyflow_ind_ths",
        provider="tushare",
        source="ths",
        api_name="moneyflow_ind_ths",
        fetched_at=fetched_at,
        confidence=0.80,
        rows=[
            {"name": "银行", "code": "BK0475", "pctChange": 2.2, "latest": 820.0},
            {"name": "半导体", "code": "BK1036", "pctChange": 0.1, "latest": 1230.0},
        ],
        message="tushare ready",
    )

    payload = global_market_service._arbitrate_sector_rank_sources([akshare_ready, tushare_ready], fetched_at)

    assert payload["selectedSource"] == "akshare_eastmoney"
    arbitration = payload["arbitration"]
    assert arbitration["sourceConsensus"] == "DIVERGED"
    assert arbitration["dataQuality"]["reviewOnly"] is True
    assert any(conflict["field"] == "pctChange" for conflict in arbitration["conflicts"])
    assert payload["message"].endswith("发现 3 项冲突。")


def test_sector_rank_medium_conflict_marks_review_only():
    fetched_at = "2026-05-21T03:00:00+00:00"
    akshare_ready = global_market_service._ready_sector_source(
        source_id="akshare_eastmoney",
        provider="akshare",
        source="eastmoney",
        api_name="stock_board_industry_name_em",
        fetched_at=fetched_at,
        confidence=0.88,
        rows=[
            {"name": "半导体", "code": "BK1036", "pctChange": 1.0, "latest": 1234.0},
            {"name": "银行", "code": "BK0475", "pctChange": 1.0, "latest": 800.0},
        ],
        message="akshare ready",
    )
    tushare_ready = global_market_service._ready_sector_source(
        source_id="tushare_moneyflow_ind_ths",
        provider="tushare",
        source="ths",
        api_name="moneyflow_ind_ths",
        fetched_at=fetched_at,
        confidence=0.80,
        rows=[
            {"name": "银行", "code": "BK0475", "pctChange": 1.0, "latest": 820.0},
            {"name": "半导体", "code": "BK1036", "pctChange": 1.0, "latest": 1230.0},
        ],
        message="tushare ready",
    )

    payload = global_market_service._arbitrate_sector_rank_sources([akshare_ready, tushare_ready], fetched_at)

    arbitration = payload["arbitration"]
    assert arbitration["sourceConsensus"] == "DIVERGED"
    assert arbitration["dataQuality"]["reviewOnly"] is True
    assert arbitration["dataQuality"]["level"] == "REVIEW_ONLY"
    assert [conflict["field"] for conflict in arbitration["conflicts"]] == ["topRank"]
