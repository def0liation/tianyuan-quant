import asyncio
import logging

from app.core import market_data_runner
from app.models.agent_runtime import MarketDataProfile


def _tushare_profile(profile_id: str = "tushare-test") -> MarketDataProfile:
    return MarketDataProfile(
        id=profile_id,
        label="Tushare test",
        provider="tushare",
        base_url="http://api.tushare.pro",
        quote_path="",
        symbol_query_param="ts_code",
        auth_mode="token",
        api_key="test-token",
        api_key_query_param="token",
        timeout_seconds=3,
        enabled=True,
        extra_query_params={"api_name": "realtime_quote", "src": "dc"},
    )


def _fallback_payload(ts_code: str):
    record = {
        "name": "Test Stock",
        "ts_code": ts_code,
        "price": "12.34",
        "pre_close": "12.00",
        "volume": "1000",
        "date": "2026-05-20",
        "time": "15:00:00",
    }
    fields = list(record.keys())
    return {
        "source": "tushare_compatible_sina",
        "api_name": "realtime_quote",
        "params": {"ts_code": ts_code, "src": "sina"},
        "records": [record],
        "data": {"fields": fields, "items": [[record[field] for field in fields]]},
    }


def test_hydrate_run_with_forced_mock_market_data_skips_external_profiles(monkeypatch):
    monkeypatch.setenv("TIANYUAN_FORCE_MOCK_MARKET_DATA", "1")
    monkeypatch.setattr(
        market_data_runner,
        "get_default_market_data_profile",
        lambda: (_ for _ in ()).throw(AssertionError("profile lookup should be skipped")),
    )

    run = {"stockName": "Smoke Holding"}
    result = asyncio.run(market_data_runner.hydrate_run_with_market_data(run, "603663"))

    assert result["marketData"]["status"] == "READY"
    assert result["marketData"]["provider"] == "MOCK"
    assert result["marketData"]["quote"]["name"] == "Smoke Holding"
    assert result["dataSources"]["summary"]["overallDataMode"] == "MOCK"
    assert result["dataMode"] == "MOCK"


class _BrokenTushareSdk:
    @staticmethod
    def set_token(token: str) -> None:
        return None

    @staticmethod
    def realtime_quote(ts_code: str, src: str):
        raise RuntimeError("Expecting value: line 1 column 1 (char 0)")


def test_tushare_realtime_sdk_failure_falls_back_without_error_traceback(monkeypatch, caplog):
    market_data_runner._MARKET_DATA_CACHE.clear()
    profile = _tushare_profile("tushare-fallback")

    monkeypatch.setattr(
        market_data_runner.importlib,
        "import_module",
        lambda name: _BrokenTushareSdk if name == "tushare" else __import__(name),
    )
    monkeypatch.setattr(
        market_data_runner,
        "_call_tushare_realtime_quote_sina",
        lambda ts_code, requested_src, fallback_reason, timeout_seconds: _fallback_payload(ts_code),
    )

    caplog.set_level(logging.WARNING, logger=market_data_runner.__name__)

    result = asyncio.run(market_data_runner.fetch_market_data(profile, "603663"))
    cached_result = asyncio.run(market_data_runner.fetch_market_data(profile, "603663"))

    assert result.status == "READY"
    assert result.error == ""
    assert result.quote["source"] == "tushare_compatible_sina"
    assert result.quote["price"] == 12.34
    assert cached_result.status == "READY"
    assert cached_result.quote == result.quote
    assert any("falling back to Sina" in record.message for record in caplog.records)
    assert not any(record.levelno >= logging.ERROR for record in caplog.records)
    assert not any(record.exc_info for record in caplog.records)


def test_tushare_realtime_both_sources_fail_returns_failed_without_traceback(monkeypatch, caplog):
    market_data_runner._MARKET_DATA_CACHE.clear()
    profile = _tushare_profile("tushare-all-down")

    monkeypatch.setattr(
        market_data_runner.importlib,
        "import_module",
        lambda name: _BrokenTushareSdk if name == "tushare" else __import__(name),
    )

    def _raise_unavailable(ts_code, requested_src, fallback_reason, timeout_seconds):
        raise market_data_runner.MarketDataSourceUnavailable("fallback down")

    monkeypatch.setattr(
        market_data_runner,
        "_call_tushare_realtime_quote_sina",
        _raise_unavailable,
    )
    caplog.set_level(logging.WARNING, logger=market_data_runner.__name__)

    result = asyncio.run(market_data_runner.fetch_market_data(profile, "603663"))

    assert result.status == "FAILED"
    assert result.quote == {}
    assert "fallback down" in result.error
    assert any("market data source unavailable" in record.message for record in caplog.records)
    assert not any(record.levelno >= logging.ERROR for record in caplog.records)
    assert not any(record.exc_info for record in caplog.records)


def test_market_data_cache_key_changes_when_api_key_changes(monkeypatch):
    market_data_runner._MARKET_DATA_CACHE.clear()
    calls = []

    def fake_call(profile: MarketDataProfile, symbol: str):
        calls.append(profile.api_key)
        return {
            "name": "Token Scoped Quote",
            "price": 10 + len(calls),
            "token_seen": profile.api_key,
        }

    monkeypatch.setattr(market_data_runner, "_call_market_data_profile", fake_call)
    base_profile = MarketDataProfile(
        id="token-cache",
        label="Token cache",
        provider="generic_rest",
        base_url="https://quotes.example.test",
        auth_mode="query",
        api_key="token-a",
        enabled=True,
    )

    first = asyncio.run(market_data_runner.fetch_market_data(base_profile, "603663"))
    cached = asyncio.run(market_data_runner.fetch_market_data(base_profile, "603663"))
    rotated = asyncio.run(
        market_data_runner.fetch_market_data(
            base_profile.model_copy(update={"api_key": "token-b"}),
            "603663",
        )
    )

    assert first.quote["price"] == cached.quote["price"]
    assert rotated.quote["price"] != first.quote["price"]
    assert calls == ["token-a", "token-b"]


def test_auxiliary_fetch_includes_tushare_stk_factor(monkeypatch):
    profile = _tushare_profile("tushare-factor")

    from app.core import agent_runtime_store

    monkeypatch.setattr(
        agent_runtime_store,
        "get_data_sources_config",
        lambda: {
            "tushare_token": "test-token",
            "sources": [
                {
                    "key": "special_data",
                    "enabled": True,
                    "tushare_api": "concept/concept_detail/broker_recommend/top_inst/stk_factor",
                }
            ],
        },
    )

    calls = []

    def fake_call(profile_arg, api_name, params):
        calls.append((profile_arg.id, api_name, params))
        return {
            "records": [
                {
                    "ts_code": "603663.SH",
                    "trade_date": "20260520",
                    "pct_chg": 1.8,
                    "turnover_rate": 2.4,
                }
            ]
        }

    monkeypatch.setattr(market_data_runner, "_call_tushare_http_api_raw", fake_call)

    result = asyncio.run(market_data_runner.fetch_auxiliary_data_sources("603663", profile))

    assert len(calls) == 1
    assert calls[0][0] == "tushare-factor"
    assert calls[0][1] == "stk_factor"
    assert calls[0][2]["ts_code"] == "603663.SH"
    assert calls[0][2]["start_date"] <= calls[0][2]["end_date"]
    assert result["special_data"]["status"] == "READY"
    assert result["special_data"]["provider"] == "tushare"
    assert result["special_data"]["api_name"] == "stk_factor"
    assert result["special_data"]["record_count"] == 1

    report = market_data_runner._build_data_sources_report(
        market_data_runner.MarketDataFetchResult(
            status="READY",
            provider="tushare",
            profile_id=profile.id,
            symbol="603663",
            quote={},
        ),
        profile,
        result,
    )
    assert report["sources"]["special_data"]["status"] == "READY"
    assert report["sources"]["special_data"]["available"] is True


def test_auxiliary_fetch_uses_tushare_cyq_chip_apis(monkeypatch):
    profile = _tushare_profile("tushare-chip")

    from app.core import agent_runtime_store

    monkeypatch.setattr(
        agent_runtime_store,
        "get_data_sources_config",
        lambda: {
            "tushare_token": "test-token",
            "sources": [
                {
                    "key": "chip",
                    "enabled": True,
                    "tushare_api": "cyq_perf/cyq_chips",
                }
            ],
        },
    )

    calls = []

    def fake_call(profile_arg, api_name, params):
        calls.append((api_name, params))
        if api_name == "cyq_perf":
            return {
                "records": [
                    {
                        "ts_code": "603663.SH",
                        "trade_date": "20260520",
                        "weight_avg": 10.8,
                        "winner_rate": 42.0,
                        "cost_5pct": 8.8,
                        "cost_15pct": 9.4,
                        "cost_50pct": 10.7,
                        "cost_85pct": 11.8,
                        "cost_95pct": 12.5,
                    }
                ]
            }
        if api_name == "cyq_chips":
            return {
                "records": [
                    {"ts_code": "603663.SH", "trade_date": "20260520", "price": 10.8, "percent": 24.0},
                    {"ts_code": "603663.SH", "trade_date": "20260520", "price": 11.6, "percent": 18.0},
                ]
            }
        raise AssertionError(api_name)

    from app.core import tushare_chip_service

    monkeypatch.setattr(market_data_runner, "_call_tushare_http_api_raw", fake_call)
    monkeypatch.setattr(tushare_chip_service, "_call_tushare_http_api_raw", fake_call)

    result = asyncio.run(market_data_runner.fetch_auxiliary_data_sources("603663", profile))

    assert [call[0] for call in calls] == ["cyq_perf", "cyq_chips"]
    assert all(call[1]["ts_code"] == "603663.SH" for call in calls)
    assert result["chip"]["status"] == "READY"
    assert result["chip"]["api_name"] == "cyq_perf/cyq_chips"
    assert result["chip"]["record_count"] == 3
    assert result["chip"]["extra"]["latestPerf"]["winnerRate"] == 0.42
    assert result["chip"]["extra"]["latestChips"][0]["percent"] == 0.24


def test_auxiliary_chip_source_reports_missing_token_without_call(monkeypatch):
    profile = _tushare_profile("tushare-chip-missing-token")

    from app.core import agent_runtime_store

    monkeypatch.setattr(
        agent_runtime_store,
        "get_data_sources_config",
        lambda: {
            "tushare_token": "",
            "sources": [
                {
                    "key": "chip",
                    "enabled": True,
                    "tushare_api": "cyq_perf/cyq_chips",
                }
            ],
        },
    )

    def fail_call(*args, **kwargs):
        raise AssertionError("tushare upstream should not be called without token")

    from app.core import tushare_chip_service

    monkeypatch.setattr(market_data_runner, "_call_tushare_http_api_raw", fail_call)
    monkeypatch.setattr(tushare_chip_service, "_call_tushare_http_api_raw", fail_call)

    result = asyncio.run(market_data_runner.fetch_auxiliary_data_sources("603663", profile))
    report = market_data_runner._build_data_sources_report(
        market_data_runner.MarketDataFetchResult(
            status="READY",
            provider="tushare",
            profile_id=profile.id,
            symbol="603663",
            quote={},
        ),
        profile,
        result,
    )

    assert "chip" not in result
    assert report["sources"]["chip"]["status"] == "NOT_CONFIGURED"
    assert "未设置 tushare token" in report["sources"]["chip"]["detail"]
