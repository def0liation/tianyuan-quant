from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from ..core.plugin_sandbox import PluginSandboxError, execute_plugin_sandbox
from ..core.plugin_runtime import plugin_runtime_planner
from ..core.plugin_store import MAX_PLUGIN_ARTIFACT_BYTES, plugin_store
from ..core.operator_context import current_operator
from ..models.plugins import (
    ArchivePluginRequest,
    PluginArtifactCleanupRequest,
    PluginArtifactCleanupResult,
    PluginArtifactUploadResult,
    PluginAuditItem,
    PluginItem,
    PluginSandboxRunRequest,
    PluginSandboxRunResult,
    PluginRuntimePlan,
    PluginUsageHistoryResponse,
    PluginUsageStatsItem,
    PluginValidateResult,
    RegisterPluginRequest,
    UpgradePluginRequest,
)


router = APIRouter()


@router.get("/plugins", response_model=list[PluginItem])
async def list_plugins():
    return await plugin_store.list_plugins()


@router.get("/plugins/runtime/plan", response_model=PluginRuntimePlan)
async def get_plugin_runtime_plan():
    plugins = await plugin_store.list_plugins()
    return plugin_runtime_planner.build_plan(plugins)


@router.get("/plugins/usage/stats", response_model=list[PluginUsageStatsItem])
async def get_plugin_usage_stats():
    return await plugin_store.list_usage_stats()


@router.get("/plugins/usage/history", response_model=PluginUsageHistoryResponse)
async def get_plugin_usage_history(days: int = Query(90, ge=1, le=365)):
    return await plugin_store.list_usage_history(days=days)


@router.post("/plugins/artifacts/cleanup", response_model=PluginArtifactCleanupResult)
async def cleanup_plugin_artifacts(request: PluginArtifactCleanupRequest | None = None):
    operator = current_operator()
    payload = request or PluginArtifactCleanupRequest()
    return await plugin_store.cleanup_expired_artifacts(
        dry_run=payload.dry_run,
        actor=operator.id,
        reason=payload.reason,
    )


@router.post("/plugins", response_model=PluginItem)
async def register_plugin(request: RegisterPluginRequest):
    try:
        return await plugin_store.register_plugin(request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc), "reason": "PLUGIN_MANIFEST_INVALID"}) from exc


@router.post("/plugins/{plugin_id}/enable", response_model=PluginItem)
async def enable_plugin(plugin_id: str):
    try:
        plugin = await plugin_store.set_enabled(plugin_id, True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc), "reason": "PLUGIN_MANIFEST_INVALID"}) from exc
    if not plugin:
        raise HTTPException(status_code=404, detail={"message": "Plugin not found", "reason": "PLUGIN_NOT_FOUND"})
    return plugin


@router.post("/plugins/{plugin_id}/disable", response_model=PluginItem)
async def disable_plugin(plugin_id: str):
    plugin = await plugin_store.set_enabled(plugin_id, False)
    if not plugin:
        raise HTTPException(status_code=404, detail={"message": "Plugin not found", "reason": "PLUGIN_NOT_FOUND"})
    return plugin


@router.post("/plugins/{plugin_id}/upgrade", response_model=PluginItem)
async def upgrade_plugin(plugin_id: str, request: UpgradePluginRequest):
    operator = current_operator()
    payload = request.model_dump(exclude={"reason"})
    try:
        plugin = await plugin_store.upgrade_plugin(
            plugin_id,
            payload,
            actor=operator.id,
            reason=request.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc), "reason": "PLUGIN_UPGRADE_INVALID"}) from exc
    if not plugin:
        raise HTTPException(status_code=404, detail={"message": "Plugin not found", "reason": "PLUGIN_NOT_FOUND"})
    return plugin


@router.post("/plugins/{plugin_id}/archive", response_model=PluginItem)
async def archive_plugin(plugin_id: str, request: ArchivePluginRequest | None = None):
    operator = current_operator()
    plugin = await plugin_store.archive_plugin(
        plugin_id,
        actor=operator.id,
        reason=(request.reason if request else ""),
    )
    if not plugin:
        raise HTTPException(status_code=404, detail={"message": "Plugin not found", "reason": "PLUGIN_NOT_FOUND"})
    return plugin


@router.post("/plugins/{plugin_id}/artifacts", response_model=PluginArtifactUploadResult)
async def upload_plugin_artifact(
    plugin_id: str,
    file: UploadFile = File(...),
    expected_checksum: str = Form(""),
    reason: str = Form(""),
):
    operator = current_operator()
    content = await file.read(MAX_PLUGIN_ARTIFACT_BYTES + 1)
    try:
        result = await plugin_store.upload_package_artifact(
            plugin_id,
            filename=file.filename or "plugin-package.bin",
            content_type=file.content_type or "application/octet-stream",
            content=content,
            expected_checksum=expected_checksum,
            actor=operator.id,
            reason=reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc), "reason": "PLUGIN_ARTIFACT_INVALID"}) from exc
    if not result:
        raise HTTPException(status_code=404, detail={"message": "Plugin not found", "reason": "PLUGIN_NOT_FOUND"})
    return result


@router.post("/plugins/{plugin_id}/validate", response_model=PluginValidateResult)
async def validate_plugin(plugin_id: str):
    result = await plugin_store.validate_plugin(plugin_id)
    if not result:
        raise HTTPException(status_code=404, detail={"message": "Plugin not found", "reason": "PLUGIN_NOT_FOUND"})
    return result


@router.post("/plugins/{plugin_id}/agents/{agent_id}/sandbox-run", response_model=PluginSandboxRunResult)
async def run_plugin_sandbox(plugin_id: str, agent_id: str, request: PluginSandboxRunRequest):
    operator = current_operator()
    try:
        result = await plugin_store.run_sandbox(
            plugin_id,
            agent_id,
            request.input_payload,
            actor=operator.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc), "reason": "PLUGIN_AGENT_NOT_FOUND"}) from exc
    if not result:
        raise HTTPException(status_code=404, detail={"message": "Plugin not found", "reason": "PLUGIN_NOT_FOUND"})
    return result


@router.get("/plugins/{plugin_id}/audit", response_model=list[PluginAuditItem])
async def get_plugin_audit(plugin_id: str):
    plugin = await plugin_store.get_plugin(plugin_id)
    if not plugin:
        raise HTTPException(status_code=404, detail={"message": "Plugin not found", "reason": "PLUGIN_NOT_FOUND"})
    return await plugin_store.list_audit(plugin_id)


@router.post("/plugins/{plugin_id}/agents/{agent_id}/sandbox/execute-preview")
async def execute_plugin_preview(plugin_id: str, agent_id: str, payload: dict | None = None):
    plugin = await plugin_store.get_plugin(plugin_id)
    if not plugin:
        raise HTTPException(status_code=404, detail={"message": "Plugin not found", "reason": "PLUGIN_NOT_FOUND"})
    agent = next(
        (
            item for item in plugin.get("agents", [])
            if isinstance(item, dict) and str(item.get("agent_id") or item.get("id") or "") == agent_id
        ),
        None,
    )
    if not agent:
        raise HTTPException(status_code=404, detail={"message": "Plugin agent not found", "reason": "PLUGIN_AGENT_NOT_FOUND"})
    payload = payload or {}
    operator = current_operator()
    try:
        result = await execute_plugin_sandbox(
            plugin=plugin,
            agent=agent,
            input_payload=payload.get("input") if isinstance(payload.get("input"), dict) else {},
            operator=operator.id,
        )
    except PluginSandboxError as exc:
        await plugin_store.record_audit(
            plugin_id,
            "EXECUTE_PREVIEW_FAILED",
            str(exc),
            {"reason": exc.reason, **exc.payload},
            actor=operator.id,
        )
        raise HTTPException(status_code=400, detail={"message": str(exc), "reason": exc.reason, **exc.payload}) from exc
    await plugin_store.record_audit(
        plugin_id,
        "EXECUTE_PREVIEW",
        "Plugin sandbox preview completed.",
        {
            "agent_id": agent_id,
            "audit_id": result["audit_id"],
            "sandbox": result["sandbox"],
            "status": result["status"],
        },
        actor=operator.id,
        audit_id=result["audit_id"],
    )
    return result
