import json
import asyncio
import threading
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app import main as app_main
from app.api import routes_health
from app.core.startup_status import startup_status
from app.main import app


async def asgi_json(method: str, path: str, json_body=None, headers=None):
    body = b""
    request_headers = [(b"host", b"testserver")]
    for name, value in (headers or {}).items():
        request_headers.append((name.lower().encode("ascii"), value.encode("utf-8")))
    if json_body is not None:
        body = json.dumps(json_body).encode("utf-8")
        request_headers.append((b"content-type", b"application/json"))

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "headers": request_headers,
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    request_sent = False
    sent = []

    async def receive():
        nonlocal request_sent
        if request_sent:
            return {"type": "http.disconnect"}
        request_sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        sent.append(message)

    await app(scope, receive, send)
    start = next(item for item in sent if item["type"] == "http.response.start")
    response_body = b"".join(item.get("body", b"") for item in sent if item["type"] == "http.response.body")
    response_headers = {name.decode("latin1").lower(): value.decode("latin1") for name, value in start.get("headers", [])}
    return start["status"], json.loads(response_body.decode("utf-8")) if response_body else None, response_headers


@pytest.mark.asyncio
async def test_request_id_is_returned_on_public_health():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/health", headers={"X-Request-ID": "unit-request-1"})
    data = response.json()

    assert response.status_code == 200
    assert data["status"] == "ok"
    assert response.headers["x-request-id"] == "unit-request-1"
    assert float(response.headers["x-response-time-ms"]) >= 0


@pytest.mark.asyncio
async def test_ops_request_log_records_requests_without_query_headers_or_body(monkeypatch, tmp_path):
    log_file = tmp_path / "ops_events.jsonl"
    handoff_dir = tmp_path / "ops_log_handoff"
    monkeypatch.setenv("OPS_LOG_FILE", str(log_file))
    monkeypatch.setenv("OPS_LOG_EXPORT_HANDOFF_DIR", str(handoff_dir))
    monkeypatch.delenv("OPS_LOG_RETENTION_DAYS", raising=False)
    monkeypatch.delenv("TIANYUAN_OPS_LOG_RETENTION_DAYS", raising=False)
    routes_health.ops_event_log.clear()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get(
            "/api/health?token=unit-secret",
            headers={"X-Request-ID": "ops-log-request", "Authorization": "Bearer hidden"},
        )
        status_response = await client.get("/api/ops/logs/status?limit=10")
        query_response = await client.get(
            "/api/ops/logs/query?limit=10&level=info&event_type=http_request&source=api&text=ops-log-request&since=2026-01-01T00:00:00Z"
        )
        export_response = await client.get("/api/ops/logs/export?limit=10")
        handoff_response = await client.post("/api/ops/logs/export/handoff?limit=10")
        invalid_filter_response = await client.get("/api/ops/logs/status?level=not-a-level&limit=10")

    assert response.status_code == 200
    assert status_response.status_code == 200
    assert query_response.status_code == 200
    assert export_response.status_code == 200
    assert handoff_response.status_code == 200
    assert invalid_filter_response.status_code == 200
    assert log_file.exists()

    status = status_response.json()
    assert status["enabled"] is True
    assert status["channel"] == "local_file_jsonl"
    assert status["external_delivery_enabled"] is False
    assert status["external_aggregation_ready"] is True
    assert status["query_endpoint"] == "/api/ops/logs/query"
    assert status["query_schema"] == "ops_log_query_v1"
    assert status["export_endpoint"] == "/api/ops/logs/export"
    assert status["export_schema"] == "ops_log_export_v1"
    assert status["log_file"] == str(log_file)
    assert status["event_count"] >= 1
    assert status["counts_by_level"]["info"] >= 1
    assert status["counts_by_type"]["http_request"] >= 1
    assert status["retention_policy"]["mode"] == "local_bounded_event_count"
    assert status["retention_policy"]["max_events"] >= 100
    assert status["retention_policy"]["time_based_retention_enabled"] is False
    assert status["retention_policy"]["max_age_days"] is None
    assert status["redaction_policy"]["headers_logged"] is False
    assert status["redaction_policy"]["query_strings_logged"] is False
    assert status["redaction_policy"]["bodies_logged"] is False
    assert status["handoff_status"]["schema"] == "ops_log_export_handoff_status_v1"
    assert status["handoff_status"]["configured"] is True
    assert status["handoff_status"]["status"] in {"PENDING_CREATE", "READY"}
    assert status["handoff_status"]["handoff_destination"] == "LOCAL_DEPLOYMENT_HANDOFF_DIR"
    assert status["handoff_status"]["manifest_schema"] == "ops_log_export_handoff_manifest_v1"
    assert status["handoff_status"]["requires_sanitized_export"] is True
    assert status["handoff_status"]["inventory"]["schema"] == "ops_log_export_handoff_inventory_v1"
    assert status["handoff_status"]["inventory"]["checked"] is True
    assert status["handoff_status"]["inventory"]["status"] == "EMPTY"
    assert status["handoff_status"]["shipper_status"]["schema"] == "ops_log_export_shipper_status_v1"
    assert status["handoff_status"]["shipper_status"]["checked"] is True
    assert status["handoff_status"]["shipper_status"]["reported"] is False
    assert status["handoff_status"]["shipper_status"]["status"] == "NOT_REPORTED"

    health_events = [
        event for event in status["latest"]
        if event["event_type"] == "http_request" and event["request_id"] == "ops-log-request"
    ]
    assert health_events
    event = health_events[0]
    assert event["method"] == "GET"
    assert event["path"] == "/api/health"
    assert event["status_code"] == 200

    serialized = json.dumps(event, sort_keys=True).lower()
    assert "unit-secret" not in serialized
    assert "authorization" not in serialized
    assert "bearer hidden" not in serialized

    queried = query_response.json()
    assert queried["schema"] == "ops_log_query_v1"
    assert queried["channel"] == "local_file_jsonl_query"
    assert queried["source_channel"] == "local_file_jsonl"
    assert queried["external_aggregation_ready"] is True
    assert queried["external_delivery_enabled"] is False
    assert queried["level_filter"] == "info"
    assert queried["event_type_filter"] == "http_request"
    assert queried["source_filter"] == "api"
    assert queried["text_filter"] == "ops-log-request"
    assert queried["since"] == "2026-01-01T00:00:00Z"
    assert queried["matched_count"] >= 1
    assert queried["returned_count"] >= 1
    assert any(
        item["event_type"] == "http_request" and item["request_id"] == "ops-log-request"
        for item in queried["events"]
    )
    serialized_query_events = json.dumps(queried["events"], sort_keys=True).lower()
    assert "unit-secret" not in serialized_query_events
    assert "authorization" not in serialized_query_events
    assert "bearer hidden" not in serialized_query_events

    exported = export_response.json()
    assert exported["schema"] == "ops_log_export_v1"
    assert exported["channel"] == "local_file_jsonl_export"
    assert exported["source_channel"] == "local_file_jsonl"
    assert exported["external_aggregation_ready"] is True
    assert exported["external_delivery_enabled"] is False
    assert exported["exported_count"] >= 1
    assert exported["checksum"].startswith("sha256:")
    assert any(
        item["event_type"] == "http_request" and item["request_id"] == "ops-log-request"
        for item in exported["events"]
    )
    serialized_export = json.dumps(exported, sort_keys=True).lower()
    assert "unit-secret" not in serialized_export
    assert "bearer hidden" not in serialized_export

    handoff = handoff_response.json()
    assert handoff["schema"] == "ops_log_export_handoff_v1"
    assert handoff["status"] == "HANDED_OFF"
    assert handoff["handoff_destination"] == "LOCAL_DEPLOYMENT_HANDOFF_DIR"
    assert handoff["bundle_checksum"].startswith("sha256:")
    assert handoff["event_count"] >= 1
    assert handoff["exported_count"] >= 1
    assert handoff["manifest"]["schema"] == "ops_log_export_handoff_manifest_v1"
    assert handoff["manifest"]["retention_policy"]["custody"] == "deployment_owned_after_handoff"
    assert handoff["manifest"]["retention_policy"]["requires_sanitized_export"] is True
    assert handoff["manifest"]["bundle_checksum"] == handoff["bundle_checksum"]

    bundle_path = handoff_dir / handoff["bundle_file"]
    manifest_path = handoff_dir / handoff["manifest_file"]
    assert bundle_path.exists()
    assert manifest_path.exists()
    persisted_bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    persisted_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert persisted_bundle["schema"] == "ops_log_export_v1"
    assert persisted_bundle["checksum"] == handoff["bundle_checksum"]
    assert persisted_manifest["handoff_id"] == handoff["handoff_id"]
    assert persisted_manifest["bundle_checksum"] == handoff["bundle_checksum"]
    assert persisted_manifest["exported_count"] == handoff["exported_count"]
    (handoff_dir / "shipper_status.json").write_text(
        json.dumps(
            {
                "schema": "ops_log_export_shipper_status_v1",
                "status": "DELIVERED",
                "reported_at": "2026-06-02T13:55:00+00:00",
                "source": "unit-test-shipper",
                "provider": "object-store",
                "remote_destination": "s3://unit-ops-log/archive?token=unit-secret",
                "remote_object_key": "ops-log/unit-handoff.json",
                "retention_policy_id": "ops-log-retention-30d",
                "retention_status": "RETAINED",
                "custody_status": "KMS_RETAINED",
                "kms_key_ref": "kms://unit-key?token=unit-secret",
                "search_index": "ops-log-index",
                "search_index_ready": True,
                "last_handoff_id": handoff["handoff_id"],
                "last_bundle_checksum": handoff["bundle_checksum"],
                "message": "uploaded token=unit-secret",
            }
        ),
        encoding="utf-8-sig",
    )
    serialized_handoff = json.dumps(handoff, sort_keys=True).lower()
    serialized_persisted_bundle = json.dumps(persisted_bundle, sort_keys=True).lower()
    assert "unit-secret" not in serialized_handoff
    assert "bearer hidden" not in serialized_handoff
    assert "unit-secret" not in serialized_persisted_bundle
    assert "bearer hidden" not in serialized_persisted_bundle

    post_handoff_status = routes_health.ops_event_log.status(limit=5)
    inventory = post_handoff_status["handoff_status"]["inventory"]
    assert inventory["schema"] == "ops_log_export_handoff_inventory_v1"
    assert inventory["checked"] is True
    assert inventory["status"] == "VERIFIED"
    assert inventory["manifest_count"] >= 1
    assert inventory["verified_count"] >= 1
    assert inventory["missing_bundle_count"] == 0
    assert inventory["checksum_mismatch_count"] == 0
    assert inventory["invalid_manifest_count"] == 0
    assert inventory["latest_handoff_id"] == handoff["handoff_id"]
    assert inventory["latest_bundle_checksum"] == handoff["bundle_checksum"]
    shipper_status = post_handoff_status["handoff_status"]["shipper_status"]
    assert shipper_status["schema"] == "ops_log_export_shipper_status_v1"
    assert shipper_status["checked"] is True
    assert shipper_status["reported"] is True
    assert shipper_status["status"] == "DELIVERED"
    assert shipper_status["provider"] == "object-store"
    assert shipper_status["remote_object_key"] == "ops-log/unit-handoff.json"
    assert shipper_status["retention_policy_id"] == "ops-log-retention-30d"
    assert shipper_status["retention_status"] == "RETAINED"
    assert shipper_status["custody_status"] == "KMS_RETAINED"
    assert shipper_status["kms_key_ref"] == "kms://unit-key?token=[REDACTED]"
    assert shipper_status["search_index"] == "ops-log-index"
    assert shipper_status["search_index_ready"] is True
    assert shipper_status["last_handoff_id"] == handoff["handoff_id"]
    assert shipper_status["last_bundle_checksum"] == handoff["bundle_checksum"]
    assert shipper_status["matches_latest_inventory"] is True
    serialized_shipper_status = json.dumps(shipper_status, sort_keys=True).lower()
    assert "unit-secret" not in serialized_shipper_status
    assert "[redacted]" in serialized_shipper_status

    invalid_filter_status = invalid_filter_response.json()
    assert any(
        item["event_type"] == "http_request" and item["request_id"] == "ops-log-request"
        for item in invalid_filter_status["latest"]
    )


@pytest.mark.asyncio
async def test_ops_log_export_handoff_is_disabled_without_deployment_dir(monkeypatch, tmp_path):
    log_file = tmp_path / "ops_events_disabled_handoff.jsonl"
    monkeypatch.setenv("OPS_LOG_FILE", str(log_file))
    monkeypatch.delenv("OPS_LOG_EXPORT_HANDOFF_DIR", raising=False)
    routes_health.ops_event_log.clear()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        await client.get("/api/health", headers={"X-Request-ID": "ops-log-disabled-handoff"})
        handoff_response = await client.post("/api/ops/logs/export/handoff?limit=10")

    assert handoff_response.status_code == 200
    handoff = handoff_response.json()
    assert handoff["schema"] == "ops_log_export_handoff_v1"
    assert handoff["status"] == "DISABLED"
    assert handoff["handoff_destination"] == "NOT_CONFIGURED"
    assert handoff["reason"] == "OPS_LOG_EXPORT_HANDOFF_DIR is not configured."
    assert handoff["bundle_file"] == ""
    assert handoff["manifest_file"] == ""
    assert handoff["manifest"] == {}
    assert handoff["bundle_checksum"].startswith("sha256:")

    status = routes_health.ops_event_log.status(limit=5)
    assert status["handoff_status"]["schema"] == "ops_log_export_handoff_status_v1"
    assert status["handoff_status"]["configured"] is False
    assert status["handoff_status"]["status"] == "NOT_CONFIGURED"
    assert status["handoff_status"]["handoff_destination"] == "NOT_CONFIGURED"
    assert status["handoff_status"]["inventory"]["schema"] == "ops_log_export_handoff_inventory_v1"
    assert status["handoff_status"]["inventory"]["checked"] is False
    assert status["handoff_status"]["inventory"]["status"] == "NOT_CONFIGURED"
    assert status["handoff_status"]["shipper_status"]["schema"] == "ops_log_export_shipper_status_v1"
    assert status["handoff_status"]["shipper_status"]["checked"] is False
    assert status["handoff_status"]["shipper_status"]["status"] == "NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_ops_log_time_based_retention_prunes_old_events(monkeypatch, tmp_path):
    log_file = tmp_path / "ops_events_retention.jsonl"
    monkeypatch.setenv("OPS_LOG_FILE", str(log_file))
    monkeypatch.setenv("OPS_LOG_RETENTION_DAYS", "1")
    handoff_dir = tmp_path / "handoff"
    monkeypatch.setenv("OPS_LOG_EXPORT_HANDOFF_DIR", str(handoff_dir))
    routes_health.ops_event_log.clear()

    old_event = {
        "id": "old-retention-event",
        "created_at": (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(),
        "event_type": "retention_probe",
        "level": "info",
        "source": "test",
        "message": "old event should be pruned",
    }
    fresh_event = {
        "id": "fresh-retention-event",
        "created_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        "event_type": "retention_probe",
        "level": "warning",
        "source": "test",
        "message": "fresh event should remain",
    }
    log_file.write_text(
        json.dumps(old_event, sort_keys=True) + "\n" + json.dumps(fresh_event, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        status_response = await client.get("/api/ops/logs/status?limit=20")
        export_response = await client.get("/api/ops/logs/export?limit=20")
        filtered_response = await client.get("/api/ops/logs/export", params={"since": fresh_event["created_at"], "level": "warning"})
        handoff_response = await client.post("/api/ops/logs/export/handoff?limit=20&level=info")

    assert status_response.status_code == 200
    status = status_response.json()
    assert status["retention_policy"]["mode"] == "local_bounded_event_count_and_age"
    assert status["retention_policy"]["time_based_retention_enabled"] is True
    assert status["retention_policy"]["max_age_days"] == 1
    assert status["retention_policy"]["prune_on_read_or_write"] is True
    assert all(item["id"] != "old-retention-event" for item in status["latest"])
    assert any(item["id"] == "fresh-retention-event" for item in status["latest"])

    assert export_response.status_code == 200
    exported = export_response.json()
    assert exported["retention_policy"]["max_age_days"] == 1
    assert any(item["id"] == "old-retention-event" for item in exported["events"])
    assert any(item["id"] == "fresh-retention-event" for item in exported["events"])

    assert filtered_response.status_code == 200
    assert [item["id"] for item in filtered_response.json()["events"]] == ["fresh-retention-event"]
    assert handoff_response.status_code == 200
    handoff = handoff_response.json()
    assert handoff["status"] == "HANDED_OFF"
    bundle = json.loads((handoff_dir / handoff["bundle_file"]).read_text(encoding="utf-8"))
    manifest = json.loads((handoff_dir / handoff["manifest_file"]).read_text(encoding="utf-8"))
    assert "old-retention-event" in [item["id"] for item in bundle["events"]]
    assert "fresh-retention-event" not in [item["id"] for item in bundle["events"]]
    assert manifest["event_count"] == handoff["event_count"] == bundle["event_count"]
    assert manifest["exported_count"] == handoff["exported_count"] == len(bundle["events"])
    assert manifest["bundle_checksum"] == handoff["bundle_checksum"] == bundle["checksum"]

    persisted = log_file.read_text(encoding="utf-8")
    assert "old-retention-event" not in persisted
    assert "fresh-retention-event" in persisted


@pytest.mark.asyncio
async def test_ready_reports_degraded_when_dependency_check_fails(monkeypatch):
    await startup_status.reset()
    await startup_status.mark_core_ready()
    async def fake_database_check():
        return {"status": "error", "message": "db unavailable"}

    monkeypatch.setattr(routes_health, "_check_database", fake_database_check)
    monkeypatch.setattr(routes_health, "_check_storage", lambda: {"status": "ok"})
    monkeypatch.setattr(routes_health, "_check_auto_paper", lambda: {"status": "ok", "enabled": False})

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/ready")
    data = response.json()

    assert response.status_code == 503
    assert data["status"] == "degraded"
    assert data["degradedChecks"] == ["database"]
    assert data["checks"]["database"]["message"] == "db unavailable"


@pytest.mark.asyncio
async def test_ready_redacts_local_database_and_storage_paths(monkeypatch):
    monkeypatch.setattr(routes_health, "_check_auto_paper", lambda: {"status": "ok", "enabled": False})

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/ready")
    data = response.json()

    assert response.status_code in {200, 503}
    serialized_checks = json.dumps(data["checks"], ensure_ascii=False)
    assert "databasePath" not in serialized_checks
    assert "appStoragePath" not in serialized_checks
    assert str(routes_health.DB_PATH) not in serialized_checks
    assert all("path" not in detail for detail in data["checks"]["storage"]["details"].values())


@pytest.mark.asyncio
async def test_startup_status_reports_core_and_degraded_optional_components():
    await startup_status.reset()

    async def ok_component():
        return "ok"

    async def failing_component():
        raise RuntimeError("warmup failed")

    await startup_status.run_component("database_schema", "core", ok_component, required=True)
    await startup_status.mark_core_ready()
    await startup_status.mark_warming()
    await startup_status.run_component("research_summary", "optional", failing_component)
    await startup_status.mark_finished()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/startup/status")
    data = response.json()

    assert response.status_code == 200
    assert data["phase"] == "DEGRADED"
    assert data["coreReady"] is True
    assert data["ready"] is False
    assert data["degradedComponents"] == ["research_summary"]
    assert {item["name"]: item["status"] for item in data["components"]} == {
        "database_schema": "OK",
        "research_summary": "ERROR",
    }

    await startup_status.reset()


@pytest.mark.asyncio
async def test_health_stays_available_while_optional_startup_component_runs():
    await startup_status.reset()
    await startup_status.start_component("research_summary", "optional")
    await startup_status.mark_warming()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/health")
    data = response.json()

    assert response.status_code == 200
    assert data["status"] == "ok"

    await startup_status.reset()


@pytest.mark.asyncio
async def test_optional_startup_timeout_marks_degraded_without_losing_core_readiness():
    await startup_status.reset()

    async def slow_component():
        await asyncio.sleep(1)

    await startup_status.mark_core_ready()
    await startup_status.mark_warming()
    await startup_status.run_component(
        "market_data_status",
        "optional",
        slow_component,
        timeout_seconds=0.01,
    )
    await startup_status.mark_finished()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/startup/status")
    data = response.json()

    assert response.status_code == 200
    assert data["phase"] == "DEGRADED"
    assert data["coreReady"] is True
    assert data["ready"] is False
    assert data["degradedComponents"] == ["market_data_status"]
    component = next(item for item in data["components"] if item["name"] == "market_data_status")
    assert component["status"] == "ERROR"
    assert component["error"].startswith("Timeout after")

    await startup_status.reset()


@pytest.mark.asyncio
async def test_market_data_warmup_does_not_block_core_health(monkeypatch):
    entered = threading.Event()
    release = threading.Event()

    class BlockingRegistry:
        async def build_status_matrix(self):
            entered.set()
            release.wait(timeout=2)
            return None

    def register_blocking_registry():
        return BlockingRegistry()

    from app.core import market_data_adapter

    monkeypatch.setattr(market_data_adapter, "register_default_market_data_adapters", register_blocking_registry)

    task = asyncio.create_task(app_main._warm_market_data_status())
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
    finally:
        release.set()
        await asyncio.wait_for(task, timeout=1)


@pytest.mark.asyncio
async def test_metrics_exposes_job_and_background_loop_shape(monkeypatch):
    monkeypatch.setattr(routes_health, "_observability_now", lambda: datetime(2026, 5, 21, 12, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(routes_health, "_analysis_runs_for_observability", lambda limit=500: [])
    monkeypatch.setattr(
        routes_health.analysis_job_store,
        "list_jobs",
        lambda limit=200: [
            {"run_id": "RUN_A", "status": "COMPLETED", "updated_at": "2026-05-20T10:00:00"},
            {"run_id": "RUN_B", "status": "FAILED", "updated_at": "2026-05-20T09:00:00"},
        ],
    )
    monkeypatch.setattr(
        routes_health.auto_paper_trading_store,
        "get_status",
        lambda: {
            "enabled": True,
            "loop_health": "HEALTHY",
            "loop_running": True,
            "last_success_at": "2026-05-20T10:00:00",
            "last_error": "",
            "next_tick_due_at": "2026-05-20T10:01:00",
        },
    )

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/metrics")
    data = response.json()

    assert response.status_code == 200
    assert data["analysisJobs"]["total"] == 2
    assert data["analysisJobs"]["byStatus"] == {"COMPLETED": 1, "FAILED": 1}
    assert data["autoPaperTrading"]["loopHealth"] == "HEALTHY"
    assert "databaseBytes" in data["storage"]
    assert data["productionHealth"]["externalCalls"] is False
    assert data["productionHealth"]["windows"]["24h"]["runSuccessRate"]["total"] == 0


@pytest.mark.asyncio
async def test_metrics_exposes_production_health_aggregates_without_live_calls(monkeypatch):
    monkeypatch.setattr(routes_health, "_observability_now", lambda: datetime(2026, 5, 21, 12, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(
        routes_health,
        "_analysis_runs_for_observability",
        lambda limit=500: [
            {
                "runId": "RUN_OK",
                "status": "COMPLETED",
                "updatedAt": "2026-05-21T11:00:00+00:00",
                "llmTrace": [
                    {"status": "COMPLETED", "totalTokens": 120},
                    {"nodeId": "final_writer", "status": "FAILED", "error": "provider failed token=unit-secret"},
                ],
                "dataMode": "LIVE",
                "dataSources": {
                    "summary": {"overallDataMode": "LIVE", "overallStatus": "READY"},
                    "sources": {"realtime_quote": {"dataMode": "LIVE", "degradationChain": []}},
                },
            },
            {
                "runId": "RUN_BAD",
                "status": "FAILED",
                "updatedAt": "2026-05-21T10:00:00+00:00",
                "llmTrace": [
                    {"nodeId": "orchestrator", "status": "FAILED", "error": "timeout sk-unit-secret"},
                    {"status": "SKIPPED", "error": "profile disabled"},
                ],
                "dataMode": "MIXED",
                "dataSources": {
                    "summary": {"overallDataMode": "MIXED", "overallStatus": "PARTIAL"},
                    "sources": {
                        "realtime_quote": {
                            "dataMode": "FALLBACK",
                            "degradationChain": [{"provider": "sina", "error": "primary failed"}],
                        }
                    },
                },
            },
            {
                "runId": "RUN_OLD",
                "status": "FAILED",
                "updatedAt": "2026-05-10T10:00:00+00:00",
                "llmTrace": [{"status": "FAILED"}],
                "dataMode": "MOCK",
            },
            {
                "runId": "RUN_30D_BASELINE",
                "status": "COMPLETED",
                "updatedAt": "2026-04-25T10:00:00+00:00",
                "llmTrace": [
                    {"nodeId": "orchestrator", "status": "COMPLETED", "totalTokens": 42},
                    {"nodeId": "final_writer", "status": "FAILED", "error": "monthly writer failed"},
                ],
                "dataMode": "LIVE",
            },
            {
                "runId": "RUN_BASELINE",
                "status": "FAILED",
                "updatedAt": "2026-05-18T10:00:00+00:00",
                "llmTrace": [
                    {"nodeId": "orchestrator", "status": "FAILED", "error": "weekly baseline failed"},
                    {"nodeId": "final_writer", "status": "FAILED", "error": "weekly writer failed"},
                ],
                "dataMode": "MOCK",
            },
        ],
    )
    monkeypatch.setattr(
        routes_health.analysis_job_store,
        "list_jobs",
        lambda limit=500: [
            {"run_id": "RUN_STALE", "status": "STALE", "updated_at": "2026-05-21T11:30:00+00:00"},
            {"run_id": "RUN_OK", "status": "COMPLETED", "updated_at": "2026-05-21T11:10:00+00:00"},
        ],
    )
    monkeypatch.setattr(
        routes_health.auto_paper_trading_store,
        "get_status",
        lambda: {
            "enabled": True,
            "loop_health": "HEALTHY",
            "loop_running": True,
            "last_success_at": "2026-05-21T11:30:00+00:00",
            "last_error": "",
            "next_tick_due_at": "2026-05-21T12:01:00+00:00",
            "last_tick_result": {
                "status": "PARTIAL",
                "updated_at": "2026-05-21T11:30:00+00:00",
                "results": [
                    {"symbol": "600000", "status": "COMPLETED"},
                    {"symbol": "000001", "status": "ERROR"},
                ],
            },
        },
    )

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/metrics")
    data = response.json()
    health = data["productionHealth"]
    window = health["windows"]["24h"]
    baseline_window = health["windows"]["7d"]
    monthly_window = health["windows"]["30d"]

    assert response.status_code == 200
    assert health["externalCalls"] is False
    assert health["status"] == "critical"
    assert window["runSuccessRate"]["total"] == 2
    assert window["runSuccessRate"]["successRate"] == 0.5
    assert window["llmCallFailureRate"]["total"] == 3
    assert window["llmCallFailureRate"]["successRate"] == pytest.approx(1 / 3)
    assert window["llmCallFailureRate"]["failed"] == 2
    assert window["llmCallFailureRate"]["failureReasons"] == [
        {"reason": "provider failed token=[REDACTED]", "count": 1},
        {"reason": "timeout sk-...", "count": 1},
    ]
    assert window["llmCallFailureRate"]["sampleFailures"] == [
        {"runId": "RUN_OK", "node": "final_writer", "status": "FAILED", "reason": "provider failed token=[REDACTED]"},
        {"runId": "RUN_BAD", "node": "orchestrator", "status": "FAILED", "reason": "timeout sk-..."},
    ]
    serialized_health = json.dumps(window["llmCallFailureRate"], sort_keys=True)
    assert "unit-secret" not in serialized_health
    assert "sk-unit-secret" not in serialized_health
    assert window["marketDataFallbackRate"]["fallbackOrMock"] == 1
    assert window["marketDataFallbackRate"]["fallbackRate"] == 0.5
    assert window["signalOpsTickSuccessRate"]["total"] == 2
    assert window["signalOpsTickSuccessRate"]["successRate"] == 0.5
    assert window["staleJobs"]["currentCount"] == 1
    assert baseline_window["llmCallFailureRate"]["successRate"] == pytest.approx(0.2)
    assert monthly_window["runSuccessRate"]["total"] == 5
    assert monthly_window["runSuccessRate"]["successRate"] == pytest.approx(0.4)
    assert monthly_window["llmCallFailureRate"]["successRate"] == pytest.approx(0.25)
    assert health["trend"]["baselineWindow"] == "7d"
    assert health["trend"]["runSuccessRateDelta"] == pytest.approx(1 / 6, abs=1e-6)
    assert health["trend"]["llmFailureRateDelta"] == pytest.approx(-2 / 15, abs=1e-6)
    assert health["trend"]["llmSuccessRateDelta"] == pytest.approx(2 / 15, abs=1e-6)
    assert health["longTrend"]["baselineWindow"] == "30d"
    assert health["longTrend"]["runSuccessRateDelta"] == pytest.approx(0.1, abs=1e-6)
    assert health["longTrend"]["llmFailureRateDelta"] == pytest.approx(-1 / 12, abs=1e-6)
    assert health["longTrend"]["llmSuccessRateDelta"] == pytest.approx(1 / 12, abs=1e-6)
    assert health["errorBudget"]["status"] == "exhausted"
    assert any(alert["metric"] == "errorBudget" for alert in health["alerts"])


@pytest.mark.asyncio
async def test_ops_alert_dispatch_records_local_outbox_and_dedupes(monkeypatch, tmp_path):
    outbox_file = tmp_path / "production_alerts.jsonl"
    ops_log_file = tmp_path / "ops_events.jsonl"
    handoff_dir = tmp_path / "production_alert_handoff"
    monkeypatch.setenv("PRODUCTION_ALERT_OUTBOX_FILE", str(outbox_file))
    monkeypatch.setenv("OPS_LOG_FILE", str(ops_log_file))
    monkeypatch.setenv("PRODUCTION_ALERT_EXPORT_HANDOFF_DIR", str(handoff_dir))
    monkeypatch.delenv("PRODUCTION_ALERT_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("PRODUCTION_ALERT_RULE_POLICY_FILE", raising=False)
    monkeypatch.delenv("PRODUCTION_ALERT_RULE_PROVIDER_ACCEPTANCE_FILE", raising=False)
    monkeypatch.setattr(
        routes_health,
        "_production_health_metrics",
        lambda: {
            "status": "critical",
            "generatedAt": "2026-05-21T12:00:00+00:00",
            "externalCalls": False,
            "alerts": [
                {
                    "severity": "critical",
                    "metric": "errorBudget",
                    "window": "24h",
                    "message": "Error budget is exhausted token=unit-secret",
                    "value": 120.0,
                    "threshold": 80,
                    "runIds": ["RUN_STALE"],
                }
            ],
        },
    )
    routes_health.production_alert_outbox.clear()
    routes_health.ops_event_log.clear()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        first_response = await client.post("/api/ops/alerts/dispatch", json={})
        second_response = await client.post("/api/ops/alerts/dispatch", json={})
        status_response = await client.get("/api/ops/alerts/status?limit=5")
        export_response = await client.get("/api/ops/alerts/export?limit=5")
        handoff_response = await client.post("/api/ops/alerts/export/handoff?limit=5")
        ops_log_response = await client.get("/api/ops/logs/status?level=warning&limit=5")

    assert first_response.status_code == 200
    first = first_response.json()
    assert first["channel"] == "local_file_outbox"
    assert first["external_delivery_enabled"] is False
    assert first["external_provider"] == "disabled"
    assert first["external_delivery_status"] == "disabled"
    assert first["external_delivery_attempt_limit"] == 0
    assert first["alert_rule_policy"]["schema"] == "production_alert_rule_policy_v1"
    assert first["alert_rule_policy"]["status"] == "DEFAULT"
    assert first["alert_rule_policy"]["rule_count"] == 3
    assert first["alert_rule_policy"]["provider_acceptance"]["schema"] == "production_alert_rule_provider_acceptance_v1"
    assert first["alert_rule_policy"]["provider_acceptance"]["status"] == "NOT_CONFIGURED"
    assert first["dispatched"] == 1
    assert first["deduplicated"] == 0
    assert first["events"][0]["metric"] == "errorBudget"
    assert first["events"][0]["alert_rule_id"] == "critical_ops_page"
    assert first["events"][0]["alert_routing_key"] == "ops-critical"
    assert first["events"][0]["alert_escalation_target"] == "admin_oncall"
    assert first["events"][0]["alert_rule_policy_status"] == "DEFAULT"
    assert "[REDACTED]" in first["events"][0]["message"]
    assert outbox_file.exists()

    assert second_response.status_code == 200
    second = second_response.json()
    assert second["dispatched"] == 0
    assert second["deduplicated"] == 1

    assert status_response.status_code == 200
    assert handoff_response.status_code == 200
    status = status_response.json()
    assert status["queue_size"] == 1
    assert status["external_aggregation_ready"] is True
    assert status["export_endpoint"] == "/api/ops/alerts/export"
    assert status["export_schema"] == "production_alert_outbox_export_v1"
    assert status["alert_rule_policy"]["schema"] == "production_alert_rule_policy_v1"
    assert status["alert_rule_policy"]["status"] == "DEFAULT"
    assert status["alert_rule_policy"]["rules"][0]["id"] == "critical_ops_page"
    assert status["alert_rule_policy"]["provider_acceptance"]["status"] == "NOT_CONFIGURED"
    assert status["retention_policy"]["mode"] == "local_bounded_event_count"
    assert status["redaction_policy"]["webhook_url_returned"] is False
    assert status["handoff_status"]["schema"] == "production_alert_outbox_export_handoff_status_v1"
    assert status["handoff_status"]["configured"] is True
    assert status["handoff_status"]["status"] in {"PENDING_CREATE", "READY"}
    assert status["handoff_status"]["handoff_destination"] == "LOCAL_DEPLOYMENT_HANDOFF_DIR"
    assert status["handoff_status"]["manifest_schema"] == "production_alert_outbox_export_handoff_manifest_v1"
    assert status["handoff_status"]["requires_sanitized_export"] is True
    assert status["handoff_status"]["inventory"]["schema"] == "production_alert_outbox_export_handoff_inventory_v1"
    assert status["handoff_status"]["inventory"]["checked"] is True
    assert status["handoff_status"]["inventory"]["status"] == "EMPTY"
    assert status["handoff_status"]["shipper_status"]["schema"] == "production_alert_outbox_export_shipper_status_v1"
    assert status["handoff_status"]["shipper_status"]["checked"] is True
    assert status["handoff_status"]["shipper_status"]["reported"] is False
    assert status["handoff_status"]["shipper_status"]["status"] == "NOT_REPORTED"
    assert status["counts_by_severity"] == {"critical": 1}
    assert status["latest"][0]["delivery_status"] == "recorded"
    assert status["latest"][0]["delivery_attempt_count"] == 0
    assert status["latest"][0]["alert_rule_id"] == "critical_ops_page"

    assert export_response.status_code == 200
    exported = export_response.json()
    assert exported["schema"] == "production_alert_outbox_export_v1"
    assert exported["channel"] == "local_file_outbox_export"
    assert exported["source_channel"] == "local_file_outbox"
    assert exported["external_aggregation_ready"] is True
    assert exported["export_endpoint"] == "/api/ops/alerts/export"
    assert exported["export_schema"] == "production_alert_outbox_export_v1"
    assert exported["alert_rule_policy"]["schema"] == "production_alert_rule_policy_v1"
    assert exported["alert_rule_policy"]["status"] == "DEFAULT"
    assert exported["alert_rule_policy"]["provider_acceptance"]["status"] == "NOT_CONFIGURED"
    assert exported["outbox_file"] == str(outbox_file)
    assert exported["event_count"] == 1
    assert exported["total_event_count"] == 1
    assert exported["exported_count"] == 1
    assert exported["checksum"].startswith("sha256:")
    assert exported["events"][0]["metric"] == "errorBudget"
    assert exported["events"][0]["alert_rule_id"] == "critical_ops_page"
    assert "[REDACTED]" in exported["events"][0]["message"]
    assert exported["redaction_policy"]["webhook_url_returned"] is False
    serialized_export = json.dumps(exported, sort_keys=True).lower()
    assert "unit-secret" not in serialized_export
    assert "alerts.example.invalid" not in serialized_export

    handoff = handoff_response.json()
    assert handoff["schema"] == "production_alert_outbox_export_handoff_v1"
    assert handoff["status"] == "HANDED_OFF"
    assert handoff["handoff_destination"] == "LOCAL_DEPLOYMENT_HANDOFF_DIR"
    assert handoff["bundle_checksum"] == exported["checksum"]
    assert handoff["event_count"] == 1
    assert handoff["total_event_count"] == 1
    assert handoff["exported_count"] == 1
    assert handoff["external_provider"] == "disabled"
    assert handoff["alert_rule_policy"]["schema"] == "production_alert_rule_policy_v1"
    assert handoff["manifest"]["schema"] == "production_alert_outbox_export_handoff_manifest_v1"
    assert handoff["manifest"]["alert_rule_policy"]["schema"] == "production_alert_rule_policy_v1"
    assert handoff["manifest"]["retention_policy"]["custody"] == "deployment_owned_after_handoff"
    assert handoff["manifest"]["retention_policy"]["requires_sanitized_export"] is True
    assert handoff["manifest"]["bundle_checksum"] == handoff["bundle_checksum"]

    bundle_path = handoff_dir / handoff["bundle_file"]
    manifest_path = handoff_dir / handoff["manifest_file"]
    assert bundle_path.exists()
    assert manifest_path.exists()
    persisted_bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    persisted_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert persisted_bundle["schema"] == "production_alert_outbox_export_v1"
    assert persisted_bundle["checksum"] == handoff["bundle_checksum"]
    assert persisted_bundle["events"][0]["alert_rule_id"] == "critical_ops_page"
    assert persisted_manifest["handoff_id"] == handoff["handoff_id"]
    assert persisted_manifest["bundle_checksum"] == handoff["bundle_checksum"]
    assert persisted_manifest["exported_count"] == handoff["exported_count"]
    (handoff_dir / "shipper_status.json").write_text(
        json.dumps(
            {
                "schema": "production_alert_outbox_export_shipper_status_v1",
                "status": "DELIVERED",
                "reported_at": "2026-06-02T13:55:30+00:00",
                "source": "unit-test-alert-shipper",
                "provider": "alert-archive",
                "remote_destination": "s3://unit-alerts/archive?token=unit-secret",
                "remote_object_key": "alerts/unit-handoff.json",
                "retention_policy_id": "alert-retention-30d",
                "retention_status": "RETAINED",
                "custody_status": "KMS_RETAINED",
                "kms_key_ref": "kms://alert-key?token=unit-secret",
                "search_index": "production-alert-index",
                "search_index_ready": "ready",
                "last_handoff_id": handoff["handoff_id"],
                "last_bundle_checksum": handoff["bundle_checksum"],
                "message": "archived token=unit-secret",
            }
        ),
        encoding="utf-8-sig",
    )
    serialized_handoff = json.dumps(handoff, sort_keys=True).lower()
    serialized_persisted_bundle = json.dumps(persisted_bundle, sort_keys=True).lower()
    assert "unit-secret" not in serialized_handoff
    assert "alerts.example.invalid" not in serialized_handoff
    assert "unit-secret" not in serialized_persisted_bundle
    assert "alerts.example.invalid" not in serialized_persisted_bundle

    post_handoff_status = routes_health.production_alert_outbox.status(limit=5)
    inventory = post_handoff_status["handoff_status"]["inventory"]
    assert inventory["schema"] == "production_alert_outbox_export_handoff_inventory_v1"
    assert inventory["checked"] is True
    assert inventory["status"] == "VERIFIED"
    assert inventory["manifest_count"] >= 1
    assert inventory["verified_count"] >= 1
    assert inventory["missing_bundle_count"] == 0
    assert inventory["checksum_mismatch_count"] == 0
    assert inventory["invalid_manifest_count"] == 0
    assert inventory["latest_handoff_id"] == handoff["handoff_id"]
    assert inventory["latest_bundle_checksum"] == handoff["bundle_checksum"]
    shipper_status = post_handoff_status["handoff_status"]["shipper_status"]
    assert shipper_status["schema"] == "production_alert_outbox_export_shipper_status_v1"
    assert shipper_status["checked"] is True
    assert shipper_status["reported"] is True
    assert shipper_status["status"] == "DELIVERED"
    assert shipper_status["provider"] == "alert-archive"
    assert shipper_status["remote_object_key"] == "alerts/unit-handoff.json"
    assert shipper_status["retention_policy_id"] == "alert-retention-30d"
    assert shipper_status["retention_status"] == "RETAINED"
    assert shipper_status["custody_status"] == "KMS_RETAINED"
    assert shipper_status["kms_key_ref"] == "kms://alert-key?token=[REDACTED]"
    assert shipper_status["search_index"] == "production-alert-index"
    assert shipper_status["search_index_ready"] is True
    assert shipper_status["last_handoff_id"] == handoff["handoff_id"]
    assert shipper_status["last_bundle_checksum"] == handoff["bundle_checksum"]
    assert shipper_status["matches_latest_inventory"] is True
    serialized_shipper_status = json.dumps(shipper_status, sort_keys=True).lower()
    assert "unit-secret" not in serialized_shipper_status
    assert "[redacted]" in serialized_shipper_status

    assert ops_log_response.status_code == 200
    ops_log_status = ops_log_response.json()
    assert ops_log_status["log_file"] == str(ops_log_file)
    warning_events = [
        event for event in ops_log_status["latest"]
        if event["event_type"] == "production_alert_dispatch"
    ]
    assert warning_events
    assert warning_events[0]["level"] == "warning"
    assert warning_events[0]["context"]["dispatched"] == 1


@pytest.mark.asyncio
async def test_ops_alert_dispatch_applies_custom_rule_policy_sidecar(monkeypatch, tmp_path):
    outbox_file = tmp_path / "production_alerts_rules.jsonl"
    policy_file = tmp_path / "alert_rule_policy.json"
    acceptance_file = tmp_path / "alert_rule_provider_acceptance.json"
    monkeypatch.setenv("PRODUCTION_ALERT_OUTBOX_FILE", str(outbox_file))
    monkeypatch.setenv("PRODUCTION_ALERT_RULE_POLICY_FILE", str(policy_file))
    monkeypatch.setenv("PRODUCTION_ALERT_RULE_PROVIDER_ACCEPTANCE_FILE", str(acceptance_file))
    monkeypatch.delenv("PRODUCTION_ALERT_WEBHOOK_URL", raising=False)
    policy_file.write_text(
        json.dumps(
            {
                "schema": "production_alert_rule_policy_v1",
                "policy_id": "pd-policy-v1",
                "source": "deployment-rules token=unit-secret",
                "provider": "pagerduty",
                "message": "loaded authorization=unit-secret",
                "rules": [
                    {
                        "id": "pd-error-budget-critical",
                        "severity": "critical",
                        "metric": "errorBudget",
                        "routing_key": "pd-critical",
                        "escalation_target": "pagerduty-service token=unit-secret",
                        "dedupe_window_seconds": 900,
                    },
                    {
                        "id": "fallback-warning",
                        "severity": "warning",
                        "metric": "*",
                        "routing_key": "ops-warning",
                        "escalation_target": "operator_review",
                        "dedupe_window_seconds": 1800,
                    },
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8-sig",
    )
    acceptance_file.write_text(
        json.dumps(
            {
                "schema": "production_alert_rule_provider_acceptance_v1",
                "status": "ACCEPTED",
                "reported_at": "2026-06-02T16:05:00+00:00",
                "last_synced_at": "2026-06-02T16:04:58+00:00",
                "source": "deployment-provider token=unit-secret",
                "provider": "pagerduty",
                "policy_id": "pd-policy-v1",
                "provider_policy_id": "pd-provider-policy",
                "rules_accepted": 2,
                "rules_total": 2,
                "accepted_rule_ids": ["pd-error-budget-critical", "fallback-warning"],
                "routing_key": "pd-critical",
                "message": "accepted authorization=unit-secret",
            },
            sort_keys=True,
        ),
        encoding="utf-8-sig",
    )
    monkeypatch.setattr(
        routes_health,
        "_production_health_metrics",
        lambda: {
            "status": "critical",
            "generatedAt": "2026-06-02T15:05:00+00:00",
            "externalCalls": False,
            "alerts": [
                {
                    "severity": "critical",
                    "metric": "errorBudget",
                    "window": "24h",
                    "message": "Error budget exhausted",
                    "value": 120.0,
                    "threshold": 80,
                }
            ],
        },
    )
    routes_health.production_alert_outbox.clear()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        dispatch_response = await client.post("/api/ops/alerts/dispatch", json={})
        status_response = await client.get("/api/ops/alerts/status?limit=5")
        export_response = await client.get("/api/ops/alerts/export?limit=5")

    assert dispatch_response.status_code == 200
    dispatch = dispatch_response.json()
    policy = dispatch["alert_rule_policy"]
    assert policy["schema"] == "production_alert_rule_policy_v1"
    assert policy["policy_id"] == "pd-policy-v1"
    assert policy["checked"] is True
    assert policy["configured"] is True
    assert policy["status"] == "READY"
    assert policy["provider"] == "pagerduty"
    assert policy["source"] == "deployment-rules token=[REDACTED]"
    assert policy["message"] == "loaded authorization=[REDACTED]"
    assert policy["rule_count"] == 2
    acceptance = policy["provider_acceptance"]
    assert acceptance["schema"] == "production_alert_rule_provider_acceptance_v1"
    assert acceptance["checked"] is True
    assert acceptance["configured"] is True
    assert acceptance["reported"] is True
    assert acceptance["status"] == "ACCEPTED"
    assert acceptance["provider"] == "pagerduty"
    assert acceptance["policy_id"] == "pd-policy-v1"
    assert acceptance["provider_policy_id"] == "pd-provider-policy"
    assert acceptance["rules_accepted"] == 2
    assert acceptance["rules_total"] == 2
    assert acceptance["accepted_rule_ids"] == ["pd-error-budget-critical", "fallback-warning"]
    assert acceptance["missing_rule_ids"] == []
    assert acceptance["policy_id_matches"] is True
    assert acceptance["rule_count_matches"] is True
    assert acceptance["accepted_rule_ids_match"] is True
    assert acceptance["matches_policy"] is True
    assert acceptance["source"] == "deployment-provider token=[REDACTED]"
    assert acceptance["message"] == "accepted authorization=[REDACTED]"
    event = dispatch["events"][0]
    assert event["alert_rule_policy_status"] == "READY"
    assert event["alert_rule_source"] == "deployment-rules token=[REDACTED]"
    assert event["alert_rule_provider"] == "pagerduty"
    assert event["alert_rule_id"] == "pd-error-budget-critical"
    assert event["alert_routing_key"] == "pd-critical"
    assert event["alert_escalation_target"] == "pagerduty-service token=[REDACTED]"
    assert event["alert_dedupe_window_seconds"] == 900

    status = status_response.json()
    assert status["alert_rule_policy"]["status"] == "READY"
    assert status["alert_rule_policy"]["provider_acceptance"]["status"] == "ACCEPTED"
    assert status["alert_rule_policy"]["provider_acceptance"]["matches_policy"] is True
    assert status["latest"][0]["alert_rule_id"] == "pd-error-budget-critical"

    exported = export_response.json()
    assert exported["alert_rule_policy"]["status"] == "READY"
    assert exported["alert_rule_policy"]["provider_acceptance"]["status"] == "ACCEPTED"
    assert exported["events"][0]["alert_routing_key"] == "pd-critical"
    serialized = json.dumps(exported, sort_keys=True).lower()
    assert "unit-secret" not in serialized
    assert "[redacted]" in serialized


@pytest.mark.asyncio
async def test_ops_alert_export_handoff_is_disabled_without_deployment_dir(monkeypatch, tmp_path):
    outbox_file = tmp_path / "production_alerts_disabled_handoff.jsonl"
    monkeypatch.setenv("PRODUCTION_ALERT_OUTBOX_FILE", str(outbox_file))
    monkeypatch.delenv("PRODUCTION_ALERT_EXPORT_HANDOFF_DIR", raising=False)
    routes_health.production_alert_outbox.clear()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        handoff_response = await client.post("/api/ops/alerts/export/handoff?limit=5")

    assert handoff_response.status_code == 200
    handoff = handoff_response.json()
    assert handoff["schema"] == "production_alert_outbox_export_handoff_v1"
    assert handoff["status"] == "DISABLED"
    assert handoff["handoff_destination"] == "NOT_CONFIGURED"
    assert handoff["reason"] == "PRODUCTION_ALERT_EXPORT_HANDOFF_DIR is not configured."
    assert handoff["bundle_file"] == ""
    assert handoff["manifest_file"] == ""
    assert handoff["manifest"] == {}
    assert handoff["bundle_checksum"].startswith("sha256:")

    status = routes_health.production_alert_outbox.status(limit=5)
    assert status["handoff_status"]["schema"] == "production_alert_outbox_export_handoff_status_v1"
    assert status["handoff_status"]["configured"] is False
    assert status["handoff_status"]["status"] == "NOT_CONFIGURED"
    assert status["handoff_status"]["handoff_destination"] == "NOT_CONFIGURED"
    assert status["handoff_status"]["inventory"]["schema"] == "production_alert_outbox_export_handoff_inventory_v1"
    assert status["handoff_status"]["inventory"]["checked"] is False
    assert status["handoff_status"]["inventory"]["status"] == "NOT_CONFIGURED"
    assert status["handoff_status"]["shipper_status"]["schema"] == "production_alert_outbox_export_shipper_status_v1"
    assert status["handoff_status"]["shipper_status"]["checked"] is False
    assert status["handoff_status"]["shipper_status"]["status"] == "NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_ops_alert_dispatch_can_deliver_to_configured_webhook(monkeypatch, tmp_path):
    outbox_file = tmp_path / "production_alerts_webhook.jsonl"
    ops_log_file = tmp_path / "ops_events_webhook.jsonl"
    delivered: list[dict] = []
    monkeypatch.setenv("PRODUCTION_ALERT_OUTBOX_FILE", str(outbox_file))
    monkeypatch.setenv("OPS_LOG_FILE", str(ops_log_file))
    monkeypatch.setenv("PRODUCTION_ALERT_WEBHOOK_URL", "https://alerts.example.invalid/webhook?token=unit-secret")
    monkeypatch.setenv("PRODUCTION_ALERT_WEBHOOK_TIMEOUT_SECONDS", "0.5")
    monkeypatch.delenv("PRODUCTION_ALERT_WEBHOOK_MAX_ATTEMPTS", raising=False)
    monkeypatch.setattr(
        routes_health,
        "_production_health_metrics",
        lambda: {
            "status": "critical",
            "generatedAt": "2026-05-21T12:30:00+00:00",
            "externalCalls": False,
            "alerts": [
                {
                    "severity": "warning",
                    "metric": "runSuccessRate",
                    "window": "24h",
                    "message": "Run success rate below threshold authorization=hidden",
                    "value": 0.5,
                    "threshold": 0.8,
                }
            ],
        },
    )

    def fake_send_webhook(event, production_health):
        delivered.append({"event": dict(event), "production_health": dict(production_health)})

    monkeypatch.setattr(routes_health.production_alert_outbox, "_send_webhook_event", fake_send_webhook)
    routes_health.production_alert_outbox.clear()
    routes_health.ops_event_log.clear()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        dispatch_response = await client.post("/api/ops/alerts/dispatch", json={})
        status_response = await client.get("/api/ops/alerts/status?limit=5")
        export_response = await client.get("/api/ops/alerts/export?limit=5")

    assert dispatch_response.status_code == 200
    result = dispatch_response.json()
    assert result["external_delivery_enabled"] is True
    assert result["external_provider"] == "generic_webhook"
    assert result["external_delivery_status"] == "ready"
    assert result["external_delivery_attempt_limit"] == 1
    assert result["dispatched"] == 1
    assert result["events"][0]["external_delivery"] is True
    assert result["events"][0]["external_provider"] == "generic_webhook"
    assert result["events"][0]["delivery_status"] == "delivered"
    assert result["events"][0]["delivery_attempt_count"] == 1
    assert result["events"][0]["delivery_attempt_limit"] == 1
    assert result["events"][0]["delivery_error"] == ""
    assert "hidden" not in json.dumps(result["events"][0], sort_keys=True).lower()
    assert delivered and delivered[0]["event"]["metric"] == "runSuccessRate"

    assert status_response.status_code == 200
    status = status_response.json()
    assert status["external_delivery_enabled"] is True
    assert status["external_provider"] == "generic_webhook"
    assert status["latest"][0]["delivery_status"] == "delivered"
    assert status["latest"][0]["delivery_attempt_count"] == 1

    assert export_response.status_code == 200
    exported = export_response.json()
    assert exported["external_delivery_enabled"] is True
    assert exported["external_provider"] == "generic_webhook"
    assert exported["external_aggregation_ready"] is True
    assert exported["checksum"].startswith("sha256:")
    assert "unit-secret" not in json.dumps(exported, sort_keys=True).lower()
    assert "alerts.example.invalid" not in json.dumps(exported, sort_keys=True).lower()


@pytest.mark.asyncio
async def test_ops_alert_dispatch_retries_configured_webhook_failure(monkeypatch, tmp_path):
    outbox_file = tmp_path / "production_alerts_webhook_retry.jsonl"
    ops_log_file = tmp_path / "ops_events_webhook_retry.jsonl"
    attempts: list[str] = []
    monkeypatch.setenv("PRODUCTION_ALERT_OUTBOX_FILE", str(outbox_file))
    monkeypatch.setenv("OPS_LOG_FILE", str(ops_log_file))
    monkeypatch.setenv("PRODUCTION_ALERT_WEBHOOK_URL", "https://alerts.example.invalid/webhook?token=unit-secret")
    monkeypatch.setenv("PRODUCTION_ALERT_WEBHOOK_TIMEOUT_SECONDS", "0.5")
    monkeypatch.setenv("PRODUCTION_ALERT_WEBHOOK_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("PRODUCTION_ALERT_WEBHOOK_RETRY_BACKOFF_SECONDS", "0")
    monkeypatch.setattr(
        routes_health,
        "_production_health_metrics",
        lambda: {
            "status": "degraded",
            "generatedAt": "2026-05-21T12:45:00+00:00",
            "externalCalls": False,
            "alerts": [
                {
                    "severity": "warning",
                    "metric": "llmFailureRate",
                    "window": "24h",
                    "message": "LLM failure rate above threshold token=retry-secret",
                    "value": 0.35,
                    "threshold": 0.2,
                }
            ],
        },
    )

    def flaky_send_webhook(event, production_health):
        attempts.append(str(event["delivery_attempt_count"]))
        if len(attempts) == 1:
            raise RuntimeError("temporary webhook failure token=retry-secret")

    monkeypatch.setattr(routes_health.production_alert_outbox, "_send_webhook_event", flaky_send_webhook)
    routes_health.production_alert_outbox.clear()
    routes_health.ops_event_log.clear()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        dispatch_response = await client.post("/api/ops/alerts/dispatch", json={})
        status_response = await client.get("/api/ops/alerts/status?limit=5")

    assert dispatch_response.status_code == 200
    result = dispatch_response.json()
    event = result["events"][0]
    assert result["external_delivery_attempt_limit"] == 3
    assert result["external_delivery_retry_backoff_seconds"] == 0.0
    assert attempts == ["1", "2"]
    assert event["delivery_status"] == "delivered"
    assert event["delivery_attempt_count"] == 2
    assert event["delivery_attempt_limit"] == 3
    assert event["delivery_error"] == ""
    assert "retry-secret" not in json.dumps(event, sort_keys=True)

    assert status_response.status_code == 200
    status = status_response.json()
    assert status["latest"][0]["delivery_status"] == "delivered"
    assert status["latest"][0]["delivery_attempt_count"] == 2


@pytest.mark.asyncio
async def test_ops_alert_dispatch_records_failed_webhook_after_retry_limit(monkeypatch, tmp_path):
    outbox_file = tmp_path / "production_alerts_webhook_failed.jsonl"
    ops_log_file = tmp_path / "ops_events_webhook_failed.jsonl"
    attempts: list[int] = []
    monkeypatch.setenv("PRODUCTION_ALERT_OUTBOX_FILE", str(outbox_file))
    monkeypatch.setenv("OPS_LOG_FILE", str(ops_log_file))
    monkeypatch.setenv("PRODUCTION_ALERT_WEBHOOK_URL", "https://alerts.example.invalid/webhook?token=unit-secret")
    monkeypatch.setenv("PRODUCTION_ALERT_WEBHOOK_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("PRODUCTION_ALERT_WEBHOOK_RETRY_BACKOFF_SECONDS", "0")
    monkeypatch.setattr(
        routes_health,
        "_production_health_metrics",
        lambda: {
            "status": "critical",
            "generatedAt": "2026-05-21T13:00:00+00:00",
            "externalCalls": False,
            "alerts": [
                {
                    "severity": "critical",
                    "metric": "staleJobs",
                    "window": "24h",
                    "message": "Stale jobs above threshold authorization=retry-secret",
                    "value": 5,
                    "threshold": 0,
                }
            ],
        },
    )

    def failing_send_webhook(event, production_health):
        attempts.append(int(event["delivery_attempt_count"]))
        raise RuntimeError("provider unavailable authorization=retry-secret")

    monkeypatch.setattr(routes_health.production_alert_outbox, "_send_webhook_event", failing_send_webhook)
    routes_health.production_alert_outbox.clear()
    routes_health.ops_event_log.clear()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        dispatch_response = await client.post("/api/ops/alerts/dispatch", json={})

    assert dispatch_response.status_code == 200
    result = dispatch_response.json()
    event = result["events"][0]
    assert attempts == [1, 2, 3]
    assert event["delivery_status"] == "failed"
    assert event["delivery_attempt_count"] == 3
    assert event["delivery_attempt_limit"] == 3
    assert "[REDACTED]" in event["delivery_error"]
    assert "retry-secret" not in json.dumps(event, sort_keys=True)
    assert outbox_file.exists()
