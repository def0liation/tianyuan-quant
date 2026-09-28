import asyncio

import pytest
from fastapi import HTTPException

from app.api import routes_data_reliability
from app.core.operator_context import OperatorContext, reset_current_operator, set_current_operator
from app.models.market_data import AdapterCapability, DataMode, DataSourceHealth, Freshness, MarketDataResponse


class FakeRegistry:
    def __init__(self):
        self.health_called = False
        self.quote_called = False
        self.aux_called = False

    def list_adapters(self):
        return [
            DataSourceHealth(
                adapter_id="fake",
                provider="fake_provider",
                label="Fake Adapter",
                capabilities=[AdapterCapability.REALTIME_QUOTE, AdapterCapability.FUNDAMENTALS],
                healthy=False,
                enabled=True,
                installed=True,
            )
        ]

    async def health_check_all(self):
        self.health_called = True
        return [
            DataSourceHealth(
                adapter_id="fake",
                provider="fake_provider",
                label="Fake Adapter",
                capabilities=[AdapterCapability.REALTIME_QUOTE],
                healthy=True,
                message="ok",
                latency_avg_ms=5,
                enabled=True,
                installed=True,
            )
        ]

    async def fetch_realtime_quote_with_fallback(self, *args, **kwargs):
        self.quote_called = True
        raise AssertionError("symbol check should skip disabled realtime source")

    async def fetch_auxiliary_with_fallback(self, *args, **kwargs):
        self.aux_called = True
        raise AssertionError("symbol check should skip disabled auxiliary source")


class UnconfiguredRegistry(FakeRegistry):
    def list_adapters(self):
        return [
            DataSourceHealth(
                adapter_id="tencent_finance",
                provider="tencent_finance",
                label="腾讯财经",
                capabilities=[AdapterCapability.REALTIME_QUOTE],
                healthy=False,
                enabled=True,
                installed=True,
            )
        ]

    async def health_check_all(self):
        self.health_called = True
        return [
            DataSourceHealth(
                adapter_id="tencent_finance",
                provider="tencent_finance",
                label="腾讯财经",
                capabilities=[AdapterCapability.REALTIME_QUOTE],
                configured=False,
                healthy=False,
                upstream_healthy=False,
                live_data_usable=False,
                message="未配置 TENCENT_FINANCE_BASE_URL",
                latency_avg_ms=3,
                enabled=True,
                installed=True,
            )
        ]


class SlowSymbolRegistry(FakeRegistry):
    async def fetch_realtime_quote_with_fallback(self, *args, **kwargs):
        self.quote_called = True
        await asyncio.sleep(10)

    async def fetch_auxiliary_with_fallback(self, *args, **kwargs):
        self.aux_called = True
        await asyncio.sleep(10)


class ArbitrationRegistry:
    def __init__(self, arbitration: dict | None = None):
        self.arbitration = arbitration or {
            "sourceConsensus": "DIVERGED",
            "selectedSource": "tushare",
            "conflicts": [{"field": "close", "severity": "HIGH"}],
            "dataQuality": {"reviewOnly": True},
        }

    async def fetch_historical_quote_with_fallback(self, *args, **kwargs):
        return [
            MarketDataResponse(
                symbol="603663",
                price=10.0,
                timestamp="2026-05-20",
                source="tushare_test",
                provider="tushare",
                freshness=Freshness.EOD,
                data_mode=DataMode.LIVE,
                extra={"arbitration": self.arbitration},
            )
        ]


def test_data_health_api_prefix_is_not_mounted():
    paths = {route.path for route in routes_data_reliability.router.routes}

    assert "/data-reliability/snapshot" in paths
    assert not any(path.startswith("/data-health") for path in paths)


@pytest.mark.asyncio
async def test_data_reliability_active_checks_require_operator_role():
    token = set_current_operator(OperatorContext(id="viewer", role="viewer", source="test"))
    try:
        with pytest.raises(HTTPException) as exc_info:
            await routes_data_reliability.post_data_reliability_adapters_check()
    finally:
        reset_current_operator(token)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["required_role"] == "operator"


@pytest.mark.asyncio
async def test_data_reliability_snapshot_is_read_only(monkeypatch):
    registry = FakeRegistry()
    monkeypatch.delenv("TIANYUAN_DATA_RELIABILITY_EXTERNAL_MONITOR_STATUS_FILE", raising=False)
    monkeypatch.delenv("DATA_RELIABILITY_EXTERNAL_MONITOR_STATUS_FILE", raising=False)
    monkeypatch.setattr(routes_data_reliability, "register_default_market_data_adapters", lambda: registry)
    monkeypatch.setattr(
        routes_data_reliability,
        "get_market_data_adapter_configs",
        lambda: [],
    )
    monkeypatch.setattr(
        routes_data_reliability,
        "get_data_sources_config",
        lambda: {"tushare_token": "", "sources": []},
    )

    snapshot = await routes_data_reliability.get_data_reliability_snapshot()

    assert snapshot["summary"]["adapterCount"] == 1
    assert snapshot["summary"]["checkedCount"] == 0
    assert snapshot["adapters"][0]["adapterId"] == "fake"
    assert "fake" in snapshot["matrix"]["categories"]["realtime_quote"]
    assert snapshot["externalMonitorStatus"]["status"] == "NOT_CONFIGURED"
    assert registry.health_called is False


def test_data_reliability_external_monitor_status_defaults_to_not_configured(monkeypatch):
    monkeypatch.delenv("TIANYUAN_DATA_RELIABILITY_EXTERNAL_MONITOR_STATUS_FILE", raising=False)
    monkeypatch.delenv("DATA_RELIABILITY_EXTERNAL_MONITOR_STATUS_FILE", raising=False)

    status = routes_data_reliability._external_monitor_status()

    assert status["schema"] == "data_reliability_external_monitor_status_v1"
    assert status["checked"] is False
    assert status["reported"] is False
    assert status["status"] == "NOT_CONFIGURED"
    assert status["deploymentReported"] is False
    assert status["localEventTrail"] == "DataAdapterEventDB"


@pytest.mark.asyncio
async def test_data_reliability_snapshot_reports_external_monitor_sidecar(monkeypatch, tmp_path):
    registry = FakeRegistry()
    sidecar = tmp_path / "data_reliability_external_monitor.json"
    sidecar.write_text(
        """
{
  "schema": "data_reliability_external_monitor_status_v1",
  "status": "DEGRADED",
  "reported_at": "2026-06-02T09:00:00+00:00",
  "source": "deployment_monitor",
  "provider": "provider-monitor",
  "monitor_backend": "prometheus",
  "monitor_status": "LATENCY_ELEVATED",
  "freshness_status": "STALE_SOURCE_WINDOW",
  "retention_policy_id": "retention-90d",
  "retention_status": "ENFORCED",
  "retention_days": 90,
  "retention_expires_at": "2026-08-31T00:00:00+00:00",
  "outage_count": 1,
  "degraded_source_count": 2,
  "stale_source_count": 3,
  "latency_p95_ms": 1440,
  "latest_incident_at": "2026-06-02T08:50:00+00:00",
  "search_index": "data-reliability-index",
  "search_index_ready": true,
  "message": "token=secret should not leak",
  "issues": ["api_key=hidden", "latency_above_slo"]
}
""".strip(),
        encoding="utf-8-sig",
    )
    monkeypatch.setenv("DATA_RELIABILITY_EXTERNAL_MONITOR_STATUS_FILE", str(sidecar))
    monkeypatch.delenv("TIANYUAN_DATA_RELIABILITY_EXTERNAL_MONITOR_STATUS_FILE", raising=False)
    monkeypatch.setattr(routes_data_reliability, "register_default_market_data_adapters", lambda: registry)
    monkeypatch.setattr(routes_data_reliability, "get_market_data_adapter_configs", lambda: [])
    monkeypatch.setattr(routes_data_reliability, "get_data_sources_config", lambda: {"tushare_token": "", "sources": []})

    snapshot = await routes_data_reliability.get_data_reliability_snapshot()
    status = snapshot["externalMonitorStatus"]

    assert status["schema"] == "data_reliability_external_monitor_status_v1"
    assert status["checked"] is True
    assert status["reported"] is True
    assert status["deploymentReported"] is True
    assert status["status"] == "DEGRADED"
    assert status["provider"] == "provider-monitor"
    assert status["monitorBackend"] == "prometheus"
    assert status["monitorStatus"] == "LATENCY_ELEVATED"
    assert status["freshnessStatus"] == "STALE_SOURCE_WINDOW"
    assert status["retentionPolicyId"] == "retention-90d"
    assert status["retentionStatus"] == "ENFORCED"
    assert status["retentionDays"] == 90
    assert status["outageCount"] == 1
    assert status["degradedSourceCount"] == 2
    assert status["staleSourceCount"] == 3
    assert status["latencyP95Ms"] == 1440
    assert status["searchIndexReady"] is True
    assert status["message"] == "[redacted]"
    assert status["issues"] == ["[redacted]", "latency_above_slo"]


@pytest.mark.asyncio
async def test_adapter_check_is_explicit_and_recorded(monkeypatch):
    registry = FakeRegistry()
    monkeypatch.setattr(routes_data_reliability, "register_default_market_data_adapters", lambda: registry)
    monkeypatch.setattr(routes_data_reliability, "get_market_data_adapter_configs", lambda: [])
    monkeypatch.setattr(routes_data_reliability, "get_data_sources_config", lambda: {"tushare_token": "", "sources": []})

    checked = await routes_data_reliability.post_data_reliability_adapters_check()
    snapshot = await routes_data_reliability.get_data_reliability_snapshot()
    events = await routes_data_reliability.get_data_reliability_events()

    assert checked[0]["adapterId"] == "fake"
    assert registry.health_called is True
    assert snapshot["summary"]["checkedCount"] == 1
    assert snapshot["summary"]["healthyCount"] == 1
    assert snapshot["events"][0]["adapterId"] == "fake"
    assert snapshot["events"][0]["eventType"] == "ADAPTER_READY"
    assert events[0]["eventType"] == "ADAPTER_READY"


@pytest.mark.asyncio
async def test_adapter_check_records_unconfigured_authorized_source(monkeypatch):
    registry = UnconfiguredRegistry()
    monkeypatch.setattr(routes_data_reliability, "register_default_market_data_adapters", lambda: registry)
    monkeypatch.setattr(routes_data_reliability, "get_market_data_adapter_configs", lambda: [])
    monkeypatch.setattr(routes_data_reliability, "get_data_sources_config", lambda: {"tushare_token": "", "sources": []})

    checked = await routes_data_reliability.post_data_reliability_adapters_check()
    snapshot = await routes_data_reliability.get_data_reliability_snapshot()

    assert checked[0]["adapterId"] == "tencent_finance"
    assert checked[0]["configured"] is False
    assert snapshot["adapters"][0]["configured"] is False
    assert snapshot["events"][0]["status"] == "NOT_CONFIGURED"
    assert snapshot["events"][0]["eventType"] == "ADAPTER_FAILED"


def test_merge_latest_health_preserves_partial_adapter_flags():
    adapters = [
        {
            "adapterId": "akshare",
            "healthy": False,
            "upstreamHealthy": False,
            "liveDataUsable": False,
            "fallbackUsed": False,
            "message": "",
        }
    ]
    history = [
        {
            "checkType": "adapter_check",
            "adapterId": "akshare",
            "status": "PARTIAL",
            "healthy": True,
            "upstreamHealthy": True,
            "liveDataUsable": False,
            "fallbackUsed": False,
            "message": "historical and moneyflow usable; realtime disabled",
            "createdAt": "2026-05-20T00:00:00+00:00",
            "latencyMs": 12,
        }
    ]

    merged = routes_data_reliability._merge_latest_health(adapters, history)

    assert merged[0]["healthy"] is True
    assert merged[0]["upstreamHealthy"] is True
    assert merged[0]["liveDataUsable"] is False
    assert merged[0]["status"] == "PARTIAL"


def test_summary_counts_partial_adapters_separately():
    summary = routes_data_reliability._summary_from_adapters(
        [
            {
                "adapterId": "akshare",
                "provider": "akshare",
                "status": "PARTIAL",
                "healthy": True,
                "upstreamHealthy": True,
                "liveDataUsable": False,
                "message": "historical and moneyflow usable; realtime disabled",
            },
            {
                "adapterId": "sina",
                "provider": "sina",
                "status": "READY",
                "healthy": True,
                "upstreamHealthy": True,
                "liveDataUsable": True,
                "message": "OK",
            },
        ]
    )

    assert summary["overallStatus"] == "PARTIAL"
    assert summary["healthyCount"] == 1
    assert summary["partialCount"] == 1
    assert summary["failedCount"] == 0
    assert summary["partialReasons"][0]["adapterId"] == "akshare"


def test_event_type_from_check_classifies_adapter_and_source_states():
    assert routes_data_reliability._event_type_from_check(
        {"checkType": "adapter_check", "status": "READY", "healthy": True}
    ) == "ADAPTER_READY"
    assert routes_data_reliability._event_type_from_check(
        {"checkType": "adapter_check", "status": "PARTIAL", "healthy": True, "liveDataUsable": False}
    ) == "ADAPTER_PARTIAL"
    assert routes_data_reliability._event_type_from_check(
        {"checkType": "symbol_coverage_check", "status": "READY", "healthy": True, "fallbackChain": [{"from": "primary"}]}
    ) == "SOURCE_FALLBACK"
    assert routes_data_reliability._event_type_from_check(
        {"checkType": "symbol_coverage_check", "status": "SKIPPED", "healthy": False}
    ) == "SOURCE_SKIPPED"


@pytest.mark.asyncio
async def test_symbol_arbitration_summarizes_review_only_conflicts(monkeypatch):
    monkeypatch.setattr(routes_data_reliability, "register_default_market_data_adapters", lambda: ArbitrationRegistry())

    result = await routes_data_reliability.post_symbol_arbitration(
        routes_data_reliability.SymbolArbitrationRequest(
            symbol="603663",
            start="2026-05-20",
            end="2026-05-20",
            categories=["historical_quote"],
        )
    )

    assert result["overallStatus"] == "REVIEW_ONLY"
    assert result["summary"]["conflictCount"] == 1
    assert result["results"]["historical_quote"]["arbitration"]["selectedSource"] == "tushare"


@pytest.mark.asyncio
async def test_symbol_arbitration_does_not_call_single_source_consensus(monkeypatch):
    monkeypatch.setattr(
        routes_data_reliability,
        "register_default_market_data_adapters",
        lambda: ArbitrationRegistry(
            {
                "sourceConsensus": "SINGLE_SOURCE",
                "selectedSource": "tushare",
                "conflicts": [],
                "dataQuality": {"reviewOnly": False},
            }
        ),
    )

    result = await routes_data_reliability.post_symbol_arbitration(
        routes_data_reliability.SymbolArbitrationRequest(
            symbol="603663",
            start="2026-05-20",
            end="2026-05-20",
            categories=["historical_quote"],
        )
    )

    assert result["overallStatus"] == "SINGLE_SOURCE"
    assert result["summary"]["singleSourceCount"] == 1
    assert result["summary"]["conflictCount"] == 0


@pytest.mark.asyncio
async def test_symbol_check_respects_disabled_source_config(monkeypatch):
    registry = FakeRegistry()
    monkeypatch.setattr(routes_data_reliability, "register_default_market_data_adapters", lambda: registry)
    monkeypatch.setattr(routes_data_reliability, "get_market_data_adapter_configs", lambda: [])
    monkeypatch.setattr(
        routes_data_reliability,
        "get_data_sources_config",
        lambda: {
            "tushare_token": "",
            "sources": [
                {"key": "realtime_quote", "enabled": False},
                {"key": "kline_quote", "enabled": False},
                {"key": "fundamentals", "enabled": False},
                {"key": "announcements", "enabled": False},
                {"key": "moneyflow", "enabled": False},
                {"key": "chip", "enabled": False},
                {"key": "macro", "enabled": False},
            ],
        },
    )

    result = await routes_data_reliability.post_symbol_health_check(routes_data_reliability.SymbolHealthRequest(symbol="002846"))
    events = await routes_data_reliability.get_data_reliability_events()
    history = await routes_data_reliability.get_data_reliability_history()

    assert result["overallStatus"] == "FAILED"
    assert {item["diagnosis"] for item in result["results"]} == {"SOURCE_DISABLED"}
    assert len(history) == len(result["results"])
    assert {item["eventType"] for item in events} == {"SOURCE_SKIPPED"}
    assert registry.quote_called is False
    assert registry.aux_called is False


@pytest.mark.asyncio
async def test_symbol_check_records_slow_sources_as_timeout_rows(monkeypatch):
    registry = SlowSymbolRegistry()
    monkeypatch.setattr(routes_data_reliability, "register_default_market_data_adapters", lambda: registry)
    monkeypatch.setattr(routes_data_reliability, "get_market_data_adapter_configs", lambda: [])
    monkeypatch.setattr(routes_data_reliability, "DATA_RELIABILITY_SYMBOL_CHECK_TASK_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(
        routes_data_reliability,
        "get_data_sources_config",
        lambda: {
            "tushare_token": "",
            "sources": [
                {"key": "realtime_quote", "enabled": True},
                {"key": "kline_quote", "enabled": False},
                {"key": "fundamentals", "enabled": True},
                {"key": "announcements", "enabled": False},
                {"key": "moneyflow", "enabled": False},
                {"key": "chip", "enabled": False},
                {"key": "macro", "enabled": False},
            ],
        },
    )

    result = await routes_data_reliability.post_symbol_health_check(routes_data_reliability.SymbolHealthRequest(symbol="002846"))
    events = await routes_data_reliability.get_data_reliability_events()
    by_category = {item["category"]: item for item in result["results"]}

    assert result["overallStatus"] == "FAILED"
    assert by_category["realtime_quote"]["diagnosis"] == "NETWORK_TIMEOUT"
    assert by_category["fundamentals"]["diagnosis"] == "NETWORK_TIMEOUT"
    assert by_category["kline_daily"]["status"] == "SKIPPED"
    assert "SOURCE_FAILED" in {item["eventType"] for item in events}
    assert registry.quote_called is True
    assert registry.aux_called is True
