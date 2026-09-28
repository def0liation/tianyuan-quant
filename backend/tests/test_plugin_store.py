import hashlib
import io
import json
import zipfile
from datetime import datetime, timedelta, timezone

import pytest

from app.core.plugin_runtime import DEFAULT_FORBIDDEN_TRADE_ACTIONS
from app.core.plugin_store import plugin_store


async def _register_readonly_plugin(plugin_id: str, version: str = "0.1.0"):
    return await plugin_store.register_plugin({
        "plugin_id": plugin_id,
        "version": version,
        "name": f"{plugin_id} Plugin",
        "agents": [
            {
                "agent_id": f"{plugin_id}_agent",
                "name": f"{plugin_id} Agent",
                "mode": "READ_ONLY",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object", "forbidden_actions": list(DEFAULT_FORBIDDEN_TRADE_ACTIONS)},
                "permissions": ["read:analysis_context"],
                "risk_level": "LOW",
                "can_emit_trade_action": False,
            }
        ],
        "permissions": ["read:analysis_context"],
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object", "forbidden_actions": list(DEFAULT_FORBIDDEN_TRADE_ACTIONS)},
        "risk_level": "LOW",
        "enabled": True,
        "manifest": {"runtime": "controlled_dag_plan_only"},
    })


@pytest.mark.asyncio
async def test_builtin_readonly_plugin_validates_and_can_toggle():
    plugins = await plugin_store.list_plugins()
    plugin = next((item for item in plugins if item["plugin_id"] == "technical_kline_readonly"), None)

    assert plugin is not None
    assert plugin["enabled"] is True
    assert plugin["agents"][0]["can_emit_trade_action"] is False

    validation = await plugin_store.validate_plugin(plugin["plugin_id"])
    assert validation["valid"] is True
    assert validation["failures"] == []
    assert validation["audit_id"].startswith("AUD_PLUGIN_VALIDATE")

    disabled = await plugin_store.set_enabled(plugin["plugin_id"], False)
    assert disabled["enabled"] is False
    enabled = await plugin_store.set_enabled(plugin["plugin_id"], True)
    assert enabled["enabled"] is True

    audit = await plugin_store.list_audit(plugin["plugin_id"])
    assert any(entry["action"] == "DISABLE" for entry in audit)
    assert any(entry["action"] == "ENABLE" for entry in audit)


@pytest.mark.asyncio
async def test_plugin_archive_disables_runtime_and_is_audited():
    plugin = await plugin_store.register_plugin({
        "plugin_id": "archive_lifecycle_plugin",
        "version": "0.1.0",
        "name": "Archive Lifecycle Plugin",
        "agents": [
            {
                "agent_id": "archive_lifecycle_agent",
                "name": "Archive Lifecycle Agent",
                "mode": "READ_ONLY",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object", "forbidden_actions": list(DEFAULT_FORBIDDEN_TRADE_ACTIONS)},
                "permissions": ["read:analysis_context"],
                "risk_level": "LOW",
                "can_emit_trade_action": False,
            }
        ],
        "permissions": ["read:analysis_context"],
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object", "forbidden_actions": list(DEFAULT_FORBIDDEN_TRADE_ACTIONS)},
        "risk_level": "LOW",
        "enabled": True,
        "manifest": {"runtime": "controlled_dag_plan_only"},
    })
    assert plugin["enabled"] is True
    assert plugin["lifecycle_status"] == "ACTIVE"

    archived = await plugin_store.archive_plugin(
        plugin["plugin_id"],
        actor="archive-admin",
        reason="no longer needed",
    )

    assert archived["enabled"] is False
    assert archived["lifecycle_status"] == "ARCHIVED"
    assert archived["archived_by"] == "archive-admin"
    assert archived["archived_at"]
    assert archived["manifest"]["lifecycle"]["archive_reason"] == "no longer needed"

    with pytest.raises(ValueError, match="Archived plugins cannot be enabled"):
        await plugin_store.set_enabled(plugin["plugin_id"], True, actor="archive-admin")

    audit = await plugin_store.list_audit(plugin["plugin_id"])
    assert any(entry["action"] == "ARCHIVE" and entry["actor"] == "archive-admin" for entry in audit)


@pytest.mark.asyncio
async def test_plugin_upgrade_records_history_and_reactivates_new_version():
    plugin = await plugin_store.register_plugin({
        "plugin_id": "upgrade_lifecycle_plugin",
        "version": "0.1.0",
        "name": "Upgrade Lifecycle Plugin",
        "agents": [
            {
                "agent_id": "upgrade_lifecycle_agent",
                "name": "Upgrade Lifecycle Agent",
                "mode": "READ_ONLY",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object", "forbidden_actions": list(DEFAULT_FORBIDDEN_TRADE_ACTIONS)},
                "permissions": ["read:analysis_context"],
                "risk_level": "LOW",
                "can_emit_trade_action": False,
            }
        ],
        "permissions": ["read:analysis_context"],
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object", "forbidden_actions": list(DEFAULT_FORBIDDEN_TRADE_ACTIONS)},
        "risk_level": "LOW",
        "enabled": True,
        "manifest": {"runtime": "controlled_dag_plan_only"},
    })
    await plugin_store.archive_plugin(plugin["plugin_id"], actor="archive-admin", reason="retired")

    upgraded = await plugin_store.upgrade_plugin(
        plugin["plugin_id"],
        {
            **plugin,
            "version": "0.2.0",
            "enabled": True,
            "manifest": {"runtime": "controlled_dag_plan_only"},
            "package_artifact": {
                "artifact_id": "upgrade_lifecycle_plugin@0.2.0",
                "source": "unit-test",
                "checksum": "sha256:test",
                "artifact_type": "manifest_only",
            },
            "migration_steps": [
                {
                    "step_id": "copy_manifest",
                    "kind": "metadata_only",
                    "description": "Copy reviewed manifest metadata.",
                }
            ],
        },
        actor="upgrade-admin",
        reason="new reviewed package",
    )

    assert upgraded["version"] == "0.2.0"
    assert upgraded["enabled"] is True
    assert upgraded["lifecycle_status"] == "ACTIVE"
    assert upgraded["upgraded_by"] == "upgrade-admin"
    assert upgraded["upgrade_from_version"] == "0.1.0"
    assert upgraded["package_artifact_id"] == "upgrade_lifecycle_plugin@0.2.0"
    assert upgraded["package_checksum"] == "sha256:test"
    assert upgraded["package_artifact_verified"] is False
    assert upgraded["manifest"]["package_artifact"]["source"] == "unit-test"
    assert upgraded["manifest"]["package_migration"]["steps"][0]["step_id"] == "copy_manifest"
    assert upgraded["manifest"]["lifecycle"]["upgrade_reason"] == "new reviewed package"
    assert upgraded["manifest"]["lifecycle"]["package_checksum"] == "sha256:test"
    assert upgraded["manifest"]["upgrade_history"][-1]["previous_lifecycle_status"] == "ARCHIVED"
    assert upgraded["manifest"]["upgrade_history"][-1]["package_checksum"] == "sha256:test"

    audit = await plugin_store.list_audit(plugin["plugin_id"])
    assert any(
        entry["action"] == "UPGRADE"
        and entry["actor"] == "upgrade-admin"
        and entry["payload_json"]["package_artifact"]["checksum"] == "sha256:test"
        for entry in audit
    )


@pytest.mark.asyncio
async def test_plugin_upgrade_rejects_same_or_lower_version():
    plugin = await plugin_store.register_plugin({
        "plugin_id": "upgrade_version_guard_plugin",
        "version": "1.2.0",
        "name": "Upgrade Version Guard Plugin",
        "agents": [
            {
                "agent_id": "upgrade_version_guard_agent",
                "name": "Upgrade Version Guard Agent",
                "mode": "READ_ONLY",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object", "forbidden_actions": list(DEFAULT_FORBIDDEN_TRADE_ACTIONS)},
                "permissions": ["read:analysis_context"],
                "risk_level": "LOW",
                "can_emit_trade_action": False,
            }
        ],
        "permissions": ["read:analysis_context"],
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object", "forbidden_actions": list(DEFAULT_FORBIDDEN_TRADE_ACTIONS)},
        "risk_level": "LOW",
        "enabled": True,
        "manifest": {"runtime": "controlled_dag_plan_only"},
    })

    with pytest.raises(ValueError, match="requires a new version"):
        await plugin_store.upgrade_plugin(plugin["plugin_id"], {**plugin, "version": "1.2.0"})
    with pytest.raises(ValueError, match="cannot downgrade"):
        await plugin_store.upgrade_plugin(plugin["plugin_id"], {**plugin, "version": "1.1.9"})


@pytest.mark.asyncio
async def test_plugin_upgrade_rejects_code_execution_migration_step():
    plugin = await plugin_store.register_plugin({
        "plugin_id": "upgrade_migration_guard_plugin",
        "version": "0.1.0",
        "name": "Upgrade Migration Guard Plugin",
        "agents": [
            {
                "agent_id": "upgrade_migration_guard_agent",
                "name": "Upgrade Migration Guard Agent",
                "mode": "READ_ONLY",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object", "forbidden_actions": list(DEFAULT_FORBIDDEN_TRADE_ACTIONS)},
                "permissions": ["read:analysis_context"],
                "risk_level": "LOW",
                "can_emit_trade_action": False,
            }
        ],
        "permissions": ["read:analysis_context"],
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object", "forbidden_actions": list(DEFAULT_FORBIDDEN_TRADE_ACTIONS)},
        "risk_level": "LOW",
        "enabled": True,
        "manifest": {"runtime": "controlled_dag_plan_only"},
    })

    with pytest.raises(ValueError, match="cannot require code execution"):
        await plugin_store.upgrade_plugin(
            plugin["plugin_id"],
            {
                **plugin,
                "version": "0.2.0",
                "migration_steps": [{"step_id": "run_script", "requires_code_execution": True}],
            },
        )


@pytest.mark.asyncio
async def test_plugin_artifact_upload_stores_server_hash_and_updates_manifest(monkeypatch, tmp_path):
    monkeypatch.setenv("TIANYUAN_PLUGIN_ARTIFACT_DIR", str(tmp_path / "plugin-artifacts"))
    monkeypatch.setenv("TIANYUAN_PLUGIN_ARTIFACT_RETENTION_DAYS", "30")
    plugin = await plugin_store.register_plugin({
        "plugin_id": "artifact_upload_plugin",
        "version": "0.3.0",
        "name": "Artifact Upload Plugin",
        "agents": [
            {
                "agent_id": "artifact_upload_agent",
                "name": "Artifact Upload Agent",
                "mode": "READ_ONLY",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object", "forbidden_actions": list(DEFAULT_FORBIDDEN_TRADE_ACTIONS)},
                "permissions": ["read:analysis_context"],
                "risk_level": "LOW",
                "can_emit_trade_action": False,
            }
        ],
        "permissions": ["read:analysis_context"],
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object", "forbidden_actions": list(DEFAULT_FORBIDDEN_TRADE_ACTIONS)},
        "risk_level": "LOW",
        "enabled": True,
        "manifest": {"runtime": "controlled_dag_plan_only"},
    })
    content = b'{"plugin":"artifact_upload_plugin","version":"0.3.0"}'
    checksum = f"sha256:{hashlib.sha256(content).hexdigest()}"

    uploaded = await plugin_store.upload_package_artifact(
        plugin["plugin_id"],
        filename="artifact-upload-plugin.json",
        content_type="application/json",
        content=content,
        expected_checksum=checksum,
        actor="artifact-admin",
        reason="reviewed package upload",
    )

    assert uploaded["plugin_id"] == plugin["plugin_id"]
    assert uploaded["artifact_type"] == "uploaded_package"
    assert uploaded["checksum"] == checksum
    assert uploaded["expected_checksum"] == checksum
    assert uploaded["verified"] is True
    assert uploaded["recorded_only"] is False
    assert uploaded["hash_scan_status"] == "PASSED"
    assert uploaded["hash_scan"]["scanner"] == "local_sha256_denylist"
    assert uploaded["scan_status"] == "PASSED"
    assert uploaded["scan"]["archive_format"] == "none"
    assert uploaded["retention_days"] == 30
    assert uploaded["retention_expires_at"]
    stored_path = tmp_path / "plugin-artifacts" / uploaded["storage_path"]
    assert stored_path.read_bytes() == content

    refreshed = await plugin_store.get_plugin(plugin["plugin_id"])
    assert refreshed["package_artifact_id"] == uploaded["artifact_id"]
    assert refreshed["package_checksum"] == checksum
    assert refreshed["package_artifact_verified"] is True
    assert refreshed["package_artifact_storage_path"] == uploaded["storage_path"]
    assert refreshed["package_hash_scan_status"] == "PASSED"
    assert refreshed["package_scan_status"] == "PASSED"
    assert refreshed["package_retention_days"] == 30
    assert refreshed["package_retention_expires_at"] == uploaded["retention_expires_at"]
    assert refreshed["manifest"]["package_artifact"]["storage_path"] == uploaded["storage_path"]
    assert refreshed["manifest"]["package_artifact"]["hash_scan_status"] == "PASSED"
    assert refreshed["manifest"]["package_artifact"]["scan_status"] == "PASSED"
    assert refreshed["manifest"]["package_storage"]["status"] == "STORED_VERIFIED"
    assert refreshed["manifest"]["package_storage"]["scan_status"] == "PASSED"
    assert refreshed["manifest"]["lifecycle"]["package_artifact_verified"] is True

    upgraded = await plugin_store.upgrade_plugin(
        plugin["plugin_id"],
        {
            **refreshed,
            "version": "0.4.0",
            "package_artifact": uploaded,
            "migration_steps": [
                {
                    "step_id": "verified_upload_upgrade",
                    "kind": "artifact_storage_verified",
                    "description": "Use the stored and sha256-verified package artifact.",
                }
            ],
        },
        actor="artifact-admin",
        reason="upgrade from verified upload",
    )
    assert upgraded["version"] == "0.4.0"
    assert upgraded["package_checksum"] == checksum
    assert upgraded["manifest"]["package_artifact"]["artifact_type"] == "uploaded_package"
    assert upgraded["manifest"]["package_artifact"]["storage_path"] == uploaded["storage_path"]
    assert upgraded["manifest"]["package_artifact"]["hash_scan_status"] == "PASSED"
    assert upgraded["manifest"]["package_artifact"]["scan_status"] == "PASSED"
    assert upgraded["manifest"]["package_artifact"]["retention_days"] == 30
    assert upgraded["manifest"]["package_migration"]["steps"][0]["kind"] == "artifact_storage_verified"

    audit = await plugin_store.list_audit(plugin["plugin_id"])
    assert any(
        entry["action"] == "ARTIFACT_UPLOAD"
        and entry["actor"] == "artifact-admin"
        and entry["payload_json"]["verification"]["computed_checksum"] == checksum
        and entry["payload_json"]["hash_scan"]["status"] == "PASSED"
        and entry["payload_json"]["scan"]["status"] == "PASSED"
        and entry["payload_json"]["retention_policy"]["retention_days"] == 30
        for entry in audit
    )


@pytest.mark.asyncio
async def test_plugin_artifact_upload_ingests_required_external_scan_verdict(monkeypatch, tmp_path):
    artifact_root = tmp_path / "plugin-artifacts"
    scan_root = tmp_path / "external-scan"
    scan_root.mkdir()
    monkeypatch.setenv("TIANYUAN_PLUGIN_ARTIFACT_DIR", str(artifact_root))
    monkeypatch.setenv("TIANYUAN_PLUGIN_ARTIFACT_EXTERNAL_SCAN_DIR", str(scan_root))
    monkeypatch.setenv("TIANYUAN_PLUGIN_ARTIFACT_EXTERNAL_SCAN_REQUIRED", "1")
    plugin = await _register_readonly_plugin("artifact_external_scan_plugin")
    content = b'{"plugin":"artifact_external_scan_plugin","version":"0.1.0"}'
    digest = hashlib.sha256(content).hexdigest()
    checksum = f"sha256:{digest}"
    (scan_root / f"{digest}.json").write_text(
        json.dumps({
            "schema": "plugin_artifact_external_scan_verdict_v1",
            "status": "PASSED",
            "checksum": f"sha256:{digest}",
            "scanner": "unit-test-av",
            "signature_version": "2026.06.01",
            "engine_version": "engine-1.2.3",
            "definitions_updated_at": "2026-06-02T00:00:00+00:00",
            "provider_status": "READY",
            "threat_intel_status": "CURRENT",
            "scan_id": "scan-unit-test-1",
            "summary": "No malware detected by unit test scanner.",
            "warnings": ["token=hidden"],
        }),
        encoding="utf-8-sig",
    )

    uploaded = await plugin_store.upload_package_artifact(
        plugin["plugin_id"],
        filename="external-scan-plugin.json",
        content_type="application/json",
        content=content,
        actor="artifact-admin",
    )

    assert uploaded["external_scan_status"] == "PASSED"
    assert uploaded["external_scan_provider"] == "unit-test-av"
    assert uploaded["external_scan_required"] is True
    assert uploaded["external_scan"]["schema"] == "plugin_artifact_external_scan_verdict_v1"
    assert uploaded["external_scan"]["artifact_checksum"] == checksum
    assert uploaded["external_scan"]["matches_artifact_checksum"] is True
    assert uploaded["external_scan"]["signature_version"] == "2026.06.01"
    assert uploaded["external_scan"]["engine_version"] == "engine-1.2.3"
    assert uploaded["external_scan"]["definitions_updated_at"] == "2026-06-02T00:00:00+00:00"
    assert uploaded["external_scan"]["provider_status"] == "READY"
    assert uploaded["external_scan"]["threat_intel_status"] == "CURRENT"
    assert uploaded["external_scan"]["scan_id"] == "scan-unit-test-1"
    assert uploaded["external_scan"]["warnings"] == ["[redacted]"]
    assert (artifact_root / uploaded["storage_path"]).exists()

    refreshed = await plugin_store.get_plugin(plugin["plugin_id"])
    artifact = refreshed["manifest"]["package_artifact"]
    assert artifact["external_scan_status"] == "PASSED"
    assert refreshed["package_external_scan_status"] == "PASSED"
    assert refreshed["package_external_scan_provider"] == "unit-test-av"
    assert refreshed["manifest"]["package_storage"]["external_scan_required"] is True
    assert refreshed["manifest"]["lifecycle"]["package_external_scan_status"] == "PASSED"

    audit = await plugin_store.list_audit(plugin["plugin_id"])
    assert any(
        entry["action"] == "ARTIFACT_UPLOAD"
        and entry["payload_json"]["external_scan"]["status"] == "PASSED"
        and entry["payload_json"]["external_scan"]["scanner"] == "unit-test-av"
        for entry in audit
    )


@pytest.mark.asyncio
async def test_plugin_artifact_upload_rejects_external_scan_checksum_mismatch(monkeypatch, tmp_path):
    artifact_root = tmp_path / "plugin-artifacts"
    scan_root = tmp_path / "external-scan"
    scan_root.mkdir()
    monkeypatch.setenv("TIANYUAN_PLUGIN_ARTIFACT_DIR", str(artifact_root))
    monkeypatch.setenv("TIANYUAN_PLUGIN_ARTIFACT_EXTERNAL_SCAN_DIR", str(scan_root))
    monkeypatch.setenv("TIANYUAN_PLUGIN_ARTIFACT_EXTERNAL_SCAN_REQUIRED", "1")
    plugin = await _register_readonly_plugin("artifact_external_scan_checksum_mismatch_plugin")
    content = b'{"plugin":"artifact_external_scan_checksum_mismatch_plugin","version":"0.1.0"}'
    digest = hashlib.sha256(content).hexdigest()
    (scan_root / f"{digest}.json").write_text(
        json.dumps({
            "status": "PASSED",
            "checksum": "sha256:" + ("0" * 64),
            "scanner": "unit-test-av",
        }),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="external malware scan checksum mismatch"):
        await plugin_store.upload_package_artifact(
            plugin["plugin_id"],
            filename="checksum-mismatch-external-scan.json",
            content_type="application/json",
            content=content,
            actor="artifact-admin",
        )
    assert not artifact_root.exists()


@pytest.mark.asyncio
async def test_plugin_artifact_upload_rejects_missing_required_external_scan(monkeypatch, tmp_path):
    artifact_root = tmp_path / "plugin-artifacts"
    scan_root = tmp_path / "external-scan"
    scan_root.mkdir()
    monkeypatch.setenv("TIANYUAN_PLUGIN_ARTIFACT_DIR", str(artifact_root))
    monkeypatch.setenv("TIANYUAN_PLUGIN_ARTIFACT_EXTERNAL_SCAN_DIR", str(scan_root))
    monkeypatch.setenv("TIANYUAN_PLUGIN_ARTIFACT_EXTERNAL_SCAN_REQUIRED", "true")
    plugin = await _register_readonly_plugin("artifact_external_scan_missing_plugin")

    with pytest.raises(ValueError, match="external malware scan verdict is required"):
        await plugin_store.upload_package_artifact(
            plugin["plugin_id"],
            filename="missing-external-scan.json",
            content_type="application/json",
            content=b'{"scan":"missing"}',
            actor="artifact-admin",
        )
    assert not artifact_root.exists()


@pytest.mark.asyncio
async def test_plugin_artifact_upload_rejects_blocked_external_scan(monkeypatch, tmp_path):
    artifact_root = tmp_path / "plugin-artifacts"
    scan_root = tmp_path / "external-scan"
    scan_root.mkdir()
    monkeypatch.setenv("TIANYUAN_PLUGIN_ARTIFACT_DIR", str(artifact_root))
    monkeypatch.setenv("TIANYUAN_PLUGIN_ARTIFACT_EXTERNAL_SCAN_DIR", str(scan_root))
    plugin = await _register_readonly_plugin("artifact_external_scan_blocked_plugin")
    content = b'{"scan":"blocked"}'
    digest = hashlib.sha256(content).hexdigest()
    (scan_root / f"{digest}.json").write_text(
        json.dumps({
            "status": "BLOCKED",
            "scanner": "unit-test-av",
            "threats": ["EICAR-Test-File"],
            "summary": "Known malicious artifact.",
        }),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="external malware scan blocked"):
        await plugin_store.upload_package_artifact(
            plugin["plugin_id"],
            filename="blocked-external-scan.json",
            content_type="application/json",
            content=content,
            actor="artifact-admin",
        )
    assert not artifact_root.exists()


@pytest.mark.asyncio
async def test_plugin_artifact_upload_records_zip_scan_warning(monkeypatch, tmp_path):
    monkeypatch.setenv("TIANYUAN_PLUGIN_ARTIFACT_DIR", str(tmp_path / "plugin-artifacts"))
    plugin = await _register_readonly_plugin("artifact_zip_scan_plugin")
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        archive.writestr("plugin.json", '{"plugin_id":"artifact_zip_scan_plugin"}')
        archive.writestr("runner.py", "print('review only')")

    uploaded = await plugin_store.upload_package_artifact(
        plugin["plugin_id"],
        filename="artifact-zip-scan.zip",
        content_type="application/zip",
        content=content.getvalue(),
        actor="artifact-admin",
    )

    assert uploaded["scan_status"] == "WARN"
    assert uploaded["scan"]["archive_format"] == "zip"
    assert uploaded["scan"]["archive_entry_count"] == 2
    assert uploaded["scan"]["code_like_entry_count"] == 1
    assert uploaded["scan_warnings"]

    refreshed = await plugin_store.get_plugin(plugin["plugin_id"])
    assert refreshed["package_scan_status"] == "WARN"
    assert refreshed["manifest"]["package_artifact"]["scan"]["code_like_entry_count"] == 1


@pytest.mark.asyncio
async def test_plugin_artifact_upload_rejects_blocked_sha256(monkeypatch, tmp_path):
    artifact_root = tmp_path / "plugin-artifacts"
    monkeypatch.setenv("TIANYUAN_PLUGIN_ARTIFACT_DIR", str(artifact_root))
    plugin = await _register_readonly_plugin("artifact_blocked_hash_plugin")
    content = b'{"plugin":"blocked"}'
    digest = hashlib.sha256(content).hexdigest()
    monkeypatch.setenv("TIANYUAN_PLUGIN_ARTIFACT_BLOCKED_SHA256", f"sha256:{digest}")

    with pytest.raises(ValueError, match="blocked by the local denylist"):
        await plugin_store.upload_package_artifact(
            plugin["plugin_id"],
            filename="blocked-package.json",
            content_type="application/json",
            content=content,
            actor="artifact-admin",
        )
    assert not artifact_root.exists()


@pytest.mark.asyncio
async def test_plugin_artifact_upload_rejects_unsafe_zip_entries(monkeypatch, tmp_path):
    artifact_root = tmp_path / "plugin-artifacts"
    monkeypatch.setenv("TIANYUAN_PLUGIN_ARTIFACT_DIR", str(artifact_root))
    plugin = await _register_readonly_plugin("artifact_zip_path_guard_plugin")
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        archive.writestr("../escape.txt", "do not store")

    with pytest.raises(ValueError, match="archive entry is unsafe"):
        await plugin_store.upload_package_artifact(
            plugin["plugin_id"],
            filename="unsafe-plugin.zip",
            content_type="application/zip",
            content=content.getvalue(),
            actor="artifact-admin",
        )
    assert not artifact_root.exists()


@pytest.mark.asyncio
async def test_plugin_artifact_cleanup_dry_run_keeps_expired_file(monkeypatch, tmp_path):
    monkeypatch.setenv("TIANYUAN_PLUGIN_ARTIFACT_DIR", str(tmp_path / "plugin-artifacts"))
    monkeypatch.setenv("TIANYUAN_PLUGIN_ARTIFACT_RETENTION_DAYS", "1")
    plugin = await _register_readonly_plugin("artifact_cleanup_dry_run_plugin")
    uploaded = await plugin_store.upload_package_artifact(
        plugin["plugin_id"],
        filename="cleanup-dry-run.json",
        content_type="application/json",
        content=b'{"cleanup":"dry-run"}',
        actor="cleanup-admin",
    )
    stored_path = tmp_path / "plugin-artifacts" / uploaded["storage_path"]
    assert stored_path.exists()
    future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()

    result = await plugin_store.cleanup_expired_artifacts(
        dry_run=True,
        now=future,
        actor="cleanup-admin",
        reason="dry-run retention check",
    )

    assert result["dry_run"] is True
    assert result["expired_count"] >= 1
    assert result["candidate_count"] >= 1
    assert result["would_delete_count"] >= 1
    assert result["deleted_count"] == 0
    assert any(
        item["plugin_id"] == plugin["plugin_id"]
        and item["artifact_id"] == uploaded["artifact_id"]
        and item["status"] == "WOULD_DELETE"
        for item in result["items"]
    )
    assert stored_path.exists()

    audit = await plugin_store.list_audit(plugin["plugin_id"])
    assert not any(entry["action"] == "ARTIFACT_CLEANUP" for entry in audit)


@pytest.mark.asyncio
async def test_plugin_artifact_cleanup_deletes_expired_file_and_audits(monkeypatch, tmp_path):
    monkeypatch.setenv("TIANYUAN_PLUGIN_ARTIFACT_DIR", str(tmp_path / "plugin-artifacts"))
    monkeypatch.setenv("TIANYUAN_PLUGIN_ARTIFACT_RETENTION_DAYS", "1")
    plugin = await _register_readonly_plugin("artifact_cleanup_delete_plugin")
    uploaded = await plugin_store.upload_package_artifact(
        plugin["plugin_id"],
        filename="cleanup-delete.json",
        content_type="application/json",
        content=b'{"cleanup":"delete"}',
        actor="cleanup-admin",
    )
    stored_path = tmp_path / "plugin-artifacts" / uploaded["storage_path"]
    assert stored_path.exists()
    future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()

    result = await plugin_store.cleanup_expired_artifacts(
        dry_run=False,
        now=future,
        actor="cleanup-admin",
        reason="retention expired",
    )

    assert result["dry_run"] is False
    assert result["deleted_count"] >= 1
    assert any(
        item["plugin_id"] == plugin["plugin_id"]
        and item["artifact_id"] == uploaded["artifact_id"]
        and item["status"] == "DELETED"
        for item in result["items"]
    )
    assert not stored_path.exists()

    refreshed = await plugin_store.get_plugin(plugin["plugin_id"])
    assert refreshed["manifest"]["package_artifact"]["cleanup_status"] == "DELETED"
    assert refreshed["manifest"]["lifecycle"]["package_cleanup_status"] == "DELETED"
    audit = await plugin_store.list_audit(plugin["plugin_id"])
    assert any(
        entry["action"] == "ARTIFACT_CLEANUP"
        and entry["actor"] == "cleanup-admin"
        and entry["payload_json"]["dry_run"] is False
        for entry in audit
    )


@pytest.mark.asyncio
async def test_plugin_artifact_cleanup_rejects_manifest_path_escape(monkeypatch, tmp_path):
    artifact_root = tmp_path / "plugin-artifacts"
    outside = tmp_path / "outside.txt"
    outside.write_text("must remain", encoding="utf-8")
    monkeypatch.setenv("TIANYUAN_PLUGIN_ARTIFACT_DIR", str(artifact_root))
    expired_at = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    plugin = await plugin_store.register_plugin({
        "plugin_id": "artifact_cleanup_escape_plugin",
        "version": "0.1.0",
        "name": "Artifact Cleanup Escape Plugin",
        "agents": [
            {
                "agent_id": "artifact_cleanup_escape_agent",
                "name": "Artifact Cleanup Escape Agent",
                "mode": "READ_ONLY",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object", "forbidden_actions": list(DEFAULT_FORBIDDEN_TRADE_ACTIONS)},
                "permissions": ["read:analysis_context"],
                "risk_level": "LOW",
                "can_emit_trade_action": False,
            }
        ],
        "permissions": ["read:analysis_context"],
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object", "forbidden_actions": list(DEFAULT_FORBIDDEN_TRADE_ACTIONS)},
        "risk_level": "LOW",
        "enabled": True,
        "manifest": {
            "runtime": "controlled_dag_plan_only",
            "package_artifact": {
                "artifact_id": "escape-artifact",
                "artifact_type": "uploaded_package",
                "storage_path": "../outside.txt",
                "retention_expires_at": expired_at,
                "verified": True,
                "scan_status": "PASSED",
            },
        },
    })

    result = await plugin_store.cleanup_expired_artifacts(
        dry_run=False,
        actor="cleanup-admin",
        reason="path escape guard",
    )

    assert result["deleted_count"] == 0
    assert any(
        item["plugin_id"] == plugin["plugin_id"]
        and item["status"] == "SKIPPED_UNSAFE_PATH"
        for item in result["items"]
    )
    assert outside.read_text(encoding="utf-8") == "must remain"
    refreshed = await plugin_store.get_plugin(plugin["plugin_id"])
    assert refreshed["manifest"]["package_artifact"]["cleanup_status"] == "SKIPPED_UNSAFE_PATH"


@pytest.mark.asyncio
async def test_plugin_upgrade_rejects_forged_uploaded_artifact_cleanup_target(monkeypatch, tmp_path):
    artifact_root = tmp_path / "plugin-artifacts"
    monkeypatch.setenv("TIANYUAN_PLUGIN_ARTIFACT_DIR", str(artifact_root))
    monkeypatch.setenv("TIANYUAN_PLUGIN_ARTIFACT_RETENTION_DAYS", "30")
    plugin = await _register_readonly_plugin("artifact_forged_upgrade_plugin")
    uploaded = await plugin_store.upload_package_artifact(
        plugin["plugin_id"],
        filename="legit-package.json",
        content_type="application/json",
        content=b'{"package":"legit"}',
        actor="artifact-admin",
    )
    stored_path = artifact_root / uploaded["storage_path"]
    assert stored_path.exists()

    forged = {
        **uploaded,
        "artifact_id": "forged-cleanup-target",
        "retention_days": 1,
        "retention_expires_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
    }
    with pytest.raises(ValueError, match="metadata mismatch"):
        await plugin_store.upgrade_plugin(
            plugin["plugin_id"],
            {
                **plugin,
                "version": "0.2.0",
                "package_artifact": forged,
                "migration_steps": [{"step_id": "forged", "kind": "metadata_only"}],
            },
            actor="artifact-admin",
            reason="forged cleanup metadata",
        )

    result = await plugin_store.cleanup_expired_artifacts(
        dry_run=False,
        now=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        actor="cleanup-admin",
        reason="forged cleanup regression",
    )

    assert stored_path.exists()
    assert not any(
        item["plugin_id"] == plugin["plugin_id"] and item["status"] == "DELETED"
        for item in result["items"]
    )


@pytest.mark.asyncio
async def test_plugin_artifact_upload_rejects_checksum_mismatch(monkeypatch, tmp_path):
    monkeypatch.setenv("TIANYUAN_PLUGIN_ARTIFACT_DIR", str(tmp_path / "plugin-artifacts"))
    plugin = await plugin_store.register_plugin({
        "plugin_id": "artifact_checksum_guard_plugin",
        "version": "0.1.0",
        "name": "Artifact Checksum Guard Plugin",
        "agents": [
            {
                "agent_id": "artifact_checksum_guard_agent",
                "name": "Artifact Checksum Guard Agent",
                "mode": "READ_ONLY",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object", "forbidden_actions": list(DEFAULT_FORBIDDEN_TRADE_ACTIONS)},
                "permissions": ["read:analysis_context"],
                "risk_level": "LOW",
                "can_emit_trade_action": False,
            }
        ],
        "permissions": ["read:analysis_context"],
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object", "forbidden_actions": list(DEFAULT_FORBIDDEN_TRADE_ACTIONS)},
        "risk_level": "LOW",
        "enabled": True,
        "manifest": {"runtime": "controlled_dag_plan_only"},
    })

    with pytest.raises(ValueError, match="checksum mismatch"):
        await plugin_store.upload_package_artifact(
            plugin["plugin_id"],
            filename="bad-package.json",
            content_type="application/json",
            content=b"not the reviewed package",
            expected_checksum="sha256:" + ("0" * 64),
            actor="artifact-admin",
        )


@pytest.mark.asyncio
async def test_plugin_usage_history_returns_daily_buckets_from_persistent_audit():
    plugin = await plugin_store.register_plugin({
        "plugin_id": "usage_history_plugin",
        "version": "0.1.0",
        "name": "Usage History Plugin",
        "agents": [
            {
                "agent_id": "usage_history_agent",
                "name": "Usage History Agent",
                "mode": "READ_ONLY",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object", "forbidden_actions": list(DEFAULT_FORBIDDEN_TRADE_ACTIONS)},
                "permissions": ["read:analysis_context"],
                "risk_level": "LOW",
                "can_emit_trade_action": False,
            }
        ],
        "permissions": ["read:analysis_context"],
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object", "forbidden_actions": list(DEFAULT_FORBIDDEN_TRADE_ACTIONS)},
        "risk_level": "LOW",
        "enabled": True,
        "manifest": {"runtime": "controlled_dag_plan_only"},
    })
    await plugin_store.record_audit(
        plugin["plugin_id"],
        "SANDBOX_RUN",
        "Plugin sandbox run COMPLETED for agent usage_history_agent.",
        {"result": {"status": "COMPLETED", "elapsed_ms": 12.5}},
        actor="history-worker",
    )

    history = await plugin_store.list_usage_history(days=30)
    buckets = [
        item for item in history["items"]
        if item["plugin_id"] == plugin["plugin_id"] and item["total_audit_events"] > 0
    ]

    assert history["bucket"] == "day"
    assert history["days"] == 30
    assert buckets
    latest = buckets[-1]
    assert latest["action_counts"]["REGISTER"] >= 1
    assert latest["action_counts"]["SANDBOX_RUN"] == 1
    assert latest["sandbox_run_count"] == 1
    assert latest["status_counts"]["COMPLETED"] == 1
    assert latest["last_actor"] == "history-worker"
    assert latest["last_elapsed_ms"] == 12.5
    assert latest["average_elapsed_ms"] == 12.5


@pytest.mark.asyncio
async def test_plugin_audit_redacts_sensitive_payload_fields():
    plugin = await _register_readonly_plugin("audit_redaction_plugin")
    recorded = await plugin_store.record_audit(
        plugin["plugin_id"],
        "SANDBOX_RUN",
        "Plugin sandbox run COMPLETED for agent usage_history_agent.",
        {
            "status": "COMPLETED",
            "api_key": "sk-unit-secret",
            "nested": {
                "Authorization": "Bearer unit-secret",
                "safe": "kept",
            },
            "warnings": ["token=hidden", "ordinary warning"],
        },
        actor="audit-worker",
    )
    audit = await plugin_store.list_audit(plugin["plugin_id"])
    latest = next(entry for entry in audit if entry["audit_id"] == recorded["audit_id"])

    assert recorded["payload_json"]["api_key"] == "[redacted]"
    assert latest["payload_json"]["api_key"] == "[redacted]"
    assert latest["payload_json"]["nested"]["Authorization"] == "[redacted]"
    assert latest["payload_json"]["nested"]["safe"] == "kept"
    assert latest["payload_json"]["warnings"] == ["[redacted]", "ordinary warning"]


@pytest.mark.asyncio
async def test_plugin_manifest_rejects_trade_action_output():
    with pytest.raises(ValueError) as exc:
        await plugin_store.register_plugin({
            "plugin_id": "unsafe_trade_plugin",
            "version": "0.1.0",
            "agents": [
                {
                    "agent_id": "unsafe_agent",
                    "can_emit_trade_action": True,
                }
            ],
            "permissions": ["read:analysis_context"],
            "output_schema": {"forbidden_actions": ["BUY", "SELL", "ADD", "REDUCE"]},
        })

    assert "cannot emit trade actions" in str(exc.value)
