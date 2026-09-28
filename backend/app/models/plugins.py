from typing import Any, Dict, List

from pydantic import BaseModel, Field


class PluginAgentDeclaration(BaseModel):
    agent_id: str
    name: str = ""
    description: str = ""
    mode: str = "READ_ONLY"
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    output_schema: Dict[str, Any] = Field(default_factory=dict)
    permissions: List[str] = Field(default_factory=list)
    risk_level: str = "LOW"
    can_emit_trade_action: bool = False
    manifest: Dict[str, Any] = Field(default_factory=dict)


class PluginItem(BaseModel):
    plugin_id: str
    version: str = "0.1.0"
    name: str = ""
    description: str = ""
    agents: List[Dict[str, Any]] = Field(default_factory=list)
    permissions: List[str] = Field(default_factory=list)
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    output_schema: Dict[str, Any] = Field(default_factory=dict)
    risk_level: str = "LOW"
    enabled: bool = True
    source: str = "registry"
    lifecycle_status: str = "ACTIVE"
    archived_at: str = ""
    archived_by: str = ""
    upgraded_at: str = ""
    upgraded_by: str = ""
    upgrade_from_version: str = ""
    package_artifact_id: str = ""
    package_checksum: str = ""
    package_artifact_verified: bool = False
    package_artifact_storage_path: str = ""
    package_scan_status: str = ""
    package_hash_scan_status: str = ""
    package_external_scan_status: str = ""
    package_external_scan_provider: str = ""
    package_retention_expires_at: str = ""
    package_retention_days: int = 0
    manifest: Dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class PluginAuditItem(BaseModel):
    audit_id: str
    plugin_id: str
    action: str
    actor: str = "system"
    message: str = ""
    payload_json: Dict[str, Any] = Field(default_factory=dict)
    created_at: str


class PluginUsageStatsItem(BaseModel):
    plugin_id: str
    window_event_limit: int = 1000
    total_audit_events: int = 0
    sandbox_run_count: int = 0
    sandbox_block_count: int = 0
    execute_preview_count: int = 0
    execute_preview_failed_count: int = 0
    validation_count: int = 0
    lifecycle_event_count: int = 0
    action_counts: Dict[str, int] = Field(default_factory=dict)
    status_counts: Dict[str, int] = Field(default_factory=dict)
    last_action: str = ""
    last_status: str = ""
    last_actor: str = ""
    last_audit_id: str = ""
    last_run_at: str = ""
    last_elapsed_ms: float = 0.0
    average_elapsed_ms: float = 0.0
    max_elapsed_ms: float = 0.0


class PluginUsageHistoryBucket(BaseModel):
    plugin_id: str
    bucket_start: str
    bucket_label: str = ""
    total_audit_events: int = 0
    sandbox_run_count: int = 0
    sandbox_block_count: int = 0
    execute_preview_count: int = 0
    execute_preview_failed_count: int = 0
    validation_count: int = 0
    lifecycle_event_count: int = 0
    action_counts: Dict[str, int] = Field(default_factory=dict)
    status_counts: Dict[str, int] = Field(default_factory=dict)
    last_action: str = ""
    last_status: str = ""
    last_actor: str = ""
    last_audit_id: str = ""
    last_run_at: str = ""
    last_elapsed_ms: float = 0.0
    average_elapsed_ms: float = 0.0
    max_elapsed_ms: float = 0.0


class PluginUsageHistoryResponse(BaseModel):
    generated_at: str
    bucket: str = "day"
    days: int = 90
    plugin_count: int = 0
    items: List[PluginUsageHistoryBucket] = Field(default_factory=list)


class PluginArtifactUploadResult(BaseModel):
    plugin_id: str
    version: str
    artifact_id: str
    artifact_type: str = "uploaded_package"
    source: str = "api_upload"
    filename: str = ""
    content_type: str = "application/octet-stream"
    size_bytes: int = 0
    checksum: str
    checksum_algorithm: str = "sha256"
    expected_checksum: str = ""
    storage_path: str = ""
    stored_at: str = ""
    stored_by: str = ""
    verified: bool = True
    recorded_only: bool = False
    hash_scan_status: str = ""
    hash_scan: Dict[str, Any] = Field(default_factory=dict)
    scan_status: str = ""
    scan_summary: str = ""
    scan_warnings: List[str] = Field(default_factory=list)
    scan: Dict[str, Any] = Field(default_factory=dict)
    external_scan_status: str = ""
    external_scan_provider: str = ""
    external_scan_required: bool = False
    external_scan: Dict[str, Any] = Field(default_factory=dict)
    retention_days: int = 0
    retention_expires_at: str = ""
    retention_policy: Dict[str, Any] = Field(default_factory=dict)
    notes: str = ""


class PluginArtifactCleanupRequest(BaseModel):
    dry_run: bool = True
    reason: str = ""


class PluginArtifactCleanupItem(BaseModel):
    plugin_id: str
    artifact_id: str = ""
    storage_path: str = ""
    retention_expires_at: str = ""
    status: str = ""
    exists: bool = False
    size_bytes: int = 0
    error: str = ""
    resolved_path: str = ""


class PluginArtifactCleanupResult(BaseModel):
    status: str
    dry_run: bool = True
    cleanup_at: str = ""
    storage_root: str = ""
    scanned_plugin_count: int = 0
    expired_count: int = 0
    candidate_count: int = 0
    would_delete_count: int = 0
    deleted_count: int = 0
    missing_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    items: List[PluginArtifactCleanupItem] = Field(default_factory=list)


class PluginValidateResult(BaseModel):
    plugin_id: str
    valid: bool
    failures: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    audit_id: str


class RegisterPluginRequest(BaseModel):
    plugin_id: str
    version: str = "0.1.0"
    name: str = ""
    description: str = ""
    agents: List[Dict[str, Any]] = Field(default_factory=list)
    permissions: List[str] = Field(default_factory=list)
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    output_schema: Dict[str, Any] = Field(default_factory=dict)
    risk_level: str = "LOW"
    enabled: bool = True
    manifest: Dict[str, Any] = Field(default_factory=dict)


class UpgradePluginRequest(RegisterPluginRequest):
    reason: str = ""
    package_artifact: Dict[str, Any] = Field(default_factory=dict)
    migration_steps: List[Dict[str, Any]] = Field(default_factory=list)


class ArchivePluginRequest(BaseModel):
    reason: str = ""


class PluginRuntimeSchemaStatus(BaseModel):
    valid: bool
    input_schema_declared: bool
    output_schema_declared: bool
    failures: List[str] = Field(default_factory=list)


class PluginPermissionSandbox(BaseModel):
    mode: str
    allowed: bool
    allowed_permissions: List[str] = Field(default_factory=list)
    blocked_permissions: List[str] = Field(default_factory=list)
    code_execution: str = "DISABLED"
    filesystem_access: str = "DENIED"
    network_access: str = "DENIED"


class PluginExecutionSandbox(BaseModel):
    plugin_id: str
    agent_id: str
    mode: str
    allowed: bool
    hot_reload_allowed: bool = False
    execution_kind: str = "controlled_dag_plan_only"
    code_execution: str = "DISABLED"
    direct_code_execution: bool = False
    filesystem_access: str = "DENIED"
    network_access: str = "DENIED"
    resource_limits: Dict[str, Any] = Field(default_factory=dict)
    custom_resource_limits: bool = False
    resource_limit_warnings: List[str] = Field(default_factory=list)
    schema_validation: Dict[str, Any] = Field(default_factory=dict)
    permission_boundary: Dict[str, Any] = Field(default_factory=dict)
    risk_boundary: Dict[str, Any] = Field(default_factory=dict)
    audit_required: bool = True
    rollback_supported: bool = True
    trade_action_hard_block: bool = True
    block_reasons: List[str] = Field(default_factory=list)


class PluginRiskGate(BaseModel):
    risk_level: str
    allowed: bool
    required_gates: List[str] = Field(default_factory=list)
    forbidden_trade_actions: List[str] = Field(default_factory=list)
    trade_actions_allowed: bool = False
    block_reasons: List[str] = Field(default_factory=list)


class PluginRuntimeAgentPlan(BaseModel):
    plugin_id: str
    plugin_name: str
    agent_id: str
    agent_name: str
    dag_node_id: str
    plan_step: int
    enabled: bool = True
    eligible: bool
    registration_status: str
    dag_registration: Dict[str, Any] = Field(default_factory=dict)
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    output_schema: Dict[str, Any] = Field(default_factory=dict)
    permissions: List[str] = Field(default_factory=list)
    schema_status: PluginRuntimeSchemaStatus
    permission_sandbox: PluginPermissionSandbox
    risk_gate: PluginRiskGate
    execution_sandbox: PluginExecutionSandbox
    validation_failures: List[str] = Field(default_factory=list)
    can_execute_code: bool = False
    direct_execution: bool = False


class PluginRuntimePlan(BaseModel):
    generated_at: str
    status: str
    sandbox_status: str = "EMPTY"
    enabled_plugin_count: int
    enabled_agent_count: int
    registered_dag_node_count: int = 0
    hot_reload_agent_count: int = 0
    resource_summary: Dict[str, Any] = Field(default_factory=dict)
    agents: List[PluginRuntimeAgentPlan] = Field(default_factory=list)
    forbidden_trade_actions: List[str] = Field(default_factory=list)
    required_gates: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class PluginSandboxRunRequest(BaseModel):
    input_payload: Dict[str, Any] = Field(default_factory=dict)
    actor: str = "human"


class PluginSandboxRunResult(BaseModel):
    plugin_id: str
    agent_id: str
    status: str
    mode: str
    audit_id: str
    actor: str
    started_at: str
    finished_at: str
    elapsed_ms: float
    output: Dict[str, Any] = Field(default_factory=dict)
    errors: List[str] = Field(default_factory=list)
    policy: Dict[str, Any] = Field(default_factory=dict)
