import { request } from './httpClient'
import {
  PluginArtifactCleanupResult,
  PluginArtifactUploadResult,
  PluginAuditItem,
  PluginItem,
  PluginRuntimePlan,
  PluginSandboxRunResult,
  PluginUsageHistoryResponse,
  PluginUsageStatsItem,
  PluginValidateResult,
} from '../types'

export type PluginUpgradePayload = PluginItem & {
  reason?: string
  package_artifact?: Record<string, any>
  migration_steps?: Array<Record<string, any>>
}

function ensureRecord(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(`Unexpected ${label} response`)
  }
  return value as Record<string, unknown>
}

function ensureArray<T = unknown>(value: unknown, label: string): T[] {
  if (!Array.isArray(value)) {
    throw new Error(`Unexpected ${label} response`)
  }
  return value as T[]
}

function requireString(record: Record<string, unknown>, key: string, label: string) {
  if (typeof record[key] !== 'string') {
    throw new Error(`Unexpected ${label} response: missing ${key}`)
  }
}

function requireText(record: Record<string, unknown>, key: string, label: string) {
  if (typeof record[key] !== 'string' || !record[key].trim()) {
    throw new Error(`Unexpected ${label} response: missing ${key}`)
  }
}

function requireNumber(record: Record<string, unknown>, key: string, label: string) {
  if (typeof record[key] !== 'number' || !Number.isFinite(record[key])) {
    throw new Error(`Unexpected ${label} response: missing ${key}`)
  }
}

function requireBoolean(record: Record<string, unknown>, key: string, label: string) {
  if (typeof record[key] !== 'boolean') {
    throw new Error(`Unexpected ${label} response: missing ${key}`)
  }
}

function assertOptionalString(record: Record<string, unknown>, key: string, label: string) {
  if (record[key] !== undefined && record[key] !== null && typeof record[key] !== 'string') {
    throw new Error(`Unexpected ${label} response: invalid ${key}`)
  }
}

function assertOptionalNumber(record: Record<string, unknown>, key: string, label: string) {
  if (record[key] !== undefined && record[key] !== null && (typeof record[key] !== 'number' || !Number.isFinite(record[key]))) {
    throw new Error(`Unexpected ${label} response: invalid ${key}`)
  }
}

function assertOptionalBoolean(record: Record<string, unknown>, key: string, label: string) {
  if (record[key] !== undefined && record[key] !== null && typeof record[key] !== 'boolean') {
    throw new Error(`Unexpected ${label} response: invalid ${key}`)
  }
}

function assertStringArray(value: unknown, label: string) {
  ensureArray(value, label).forEach((item) => {
    if (typeof item !== 'string') {
      throw new Error(`Unexpected ${label} response`)
    }
  })
}

function assertRecordArray(value: unknown, label: string) {
  ensureArray(value, label).forEach((item) => ensureRecord(item, label))
}

function assertNumberRecord(value: unknown, label: string) {
  const record = ensureRecord(value, label)
  Object.entries(record).forEach(([key, entry]) => {
    if (typeof entry !== 'number' || !Number.isFinite(entry)) {
      throw new Error(`Unexpected ${label} response: invalid ${key}`)
    }
  })
}

function assertPluginItem(value: unknown): PluginItem {
  const plugin = ensureRecord(value, 'plugin item')
  requireText(plugin, 'plugin_id', 'plugin item')
  requireString(plugin, 'version', 'plugin item')
  requireString(plugin, 'name', 'plugin item')
  requireString(plugin, 'description', 'plugin item')
  assertRecordArray(plugin.agents, 'plugin item agents')
  assertStringArray(plugin.permissions, 'plugin item permissions')
  ensureRecord(plugin.input_schema, 'plugin item input_schema')
  ensureRecord(plugin.output_schema, 'plugin item output_schema')
  requireString(plugin, 'risk_level', 'plugin item')
  requireBoolean(plugin, 'enabled', 'plugin item')
  requireString(plugin, 'source', 'plugin item')
  assertOptionalString(plugin, 'lifecycle_status', 'plugin item')
  assertOptionalString(plugin, 'archived_at', 'plugin item')
  assertOptionalString(plugin, 'archived_by', 'plugin item')
  assertOptionalString(plugin, 'upgraded_at', 'plugin item')
  assertOptionalString(plugin, 'upgraded_by', 'plugin item')
  assertOptionalString(plugin, 'upgrade_from_version', 'plugin item')
  assertOptionalString(plugin, 'package_artifact_id', 'plugin item')
  assertOptionalString(plugin, 'package_checksum', 'plugin item')
  assertOptionalBoolean(plugin, 'package_artifact_verified', 'plugin item')
  assertOptionalString(plugin, 'package_artifact_storage_path', 'plugin item')
  assertOptionalString(plugin, 'package_scan_status', 'plugin item')
  assertOptionalString(plugin, 'package_hash_scan_status', 'plugin item')
  assertOptionalString(plugin, 'package_external_scan_status', 'plugin item')
  assertOptionalString(plugin, 'package_external_scan_provider', 'plugin item')
  assertOptionalString(plugin, 'package_retention_expires_at', 'plugin item')
  assertOptionalNumber(plugin, 'package_retention_days', 'plugin item')
  ensureRecord(plugin.manifest, 'plugin item manifest')
  requireString(plugin, 'created_at', 'plugin item')
  requireString(plugin, 'updated_at', 'plugin item')
  return value as PluginItem
}

function assertPluginList(value: unknown): PluginItem[] {
  return ensureArray(value, 'plugin list').map(assertPluginItem)
}

function assertPluginArtifactUploadResult(value: unknown): PluginArtifactUploadResult {
  const result = ensureRecord(value, 'plugin artifact upload')
  requireText(result, 'plugin_id', 'plugin artifact upload')
  requireString(result, 'version', 'plugin artifact upload')
  requireText(result, 'artifact_id', 'plugin artifact upload')
  requireString(result, 'artifact_type', 'plugin artifact upload')
  requireString(result, 'source', 'plugin artifact upload')
  requireString(result, 'filename', 'plugin artifact upload')
  requireString(result, 'content_type', 'plugin artifact upload')
  requireNumber(result, 'size_bytes', 'plugin artifact upload')
  requireText(result, 'checksum', 'plugin artifact upload')
  requireString(result, 'checksum_algorithm', 'plugin artifact upload')
  requireString(result, 'expected_checksum', 'plugin artifact upload')
  requireString(result, 'storage_path', 'plugin artifact upload')
  requireString(result, 'stored_at', 'plugin artifact upload')
  requireString(result, 'stored_by', 'plugin artifact upload')
  requireBoolean(result, 'verified', 'plugin artifact upload')
  requireBoolean(result, 'recorded_only', 'plugin artifact upload')
  requireString(result, 'hash_scan_status', 'plugin artifact upload')
  ensureRecord(result.hash_scan, 'plugin artifact upload hash_scan')
  requireString(result, 'scan_status', 'plugin artifact upload')
  requireString(result, 'scan_summary', 'plugin artifact upload')
  assertStringArray(result.scan_warnings, 'plugin artifact upload scan_warnings')
  ensureRecord(result.scan, 'plugin artifact upload scan')
  requireString(result, 'external_scan_status', 'plugin artifact upload')
  requireString(result, 'external_scan_provider', 'plugin artifact upload')
  requireBoolean(result, 'external_scan_required', 'plugin artifact upload')
  ensureRecord(result.external_scan, 'plugin artifact upload external_scan')
  requireNumber(result, 'retention_days', 'plugin artifact upload')
  requireString(result, 'retention_expires_at', 'plugin artifact upload')
  ensureRecord(result.retention_policy, 'plugin artifact upload retention_policy')
  requireString(result, 'notes', 'plugin artifact upload')
  return value as PluginArtifactUploadResult
}

function assertPluginArtifactCleanupItem(value: unknown) {
  const item = ensureRecord(value, 'plugin artifact cleanup item')
  requireText(item, 'plugin_id', 'plugin artifact cleanup item')
  requireString(item, 'artifact_id', 'plugin artifact cleanup item')
  requireString(item, 'storage_path', 'plugin artifact cleanup item')
  requireString(item, 'retention_expires_at', 'plugin artifact cleanup item')
  requireString(item, 'status', 'plugin artifact cleanup item')
  requireBoolean(item, 'exists', 'plugin artifact cleanup item')
  requireNumber(item, 'size_bytes', 'plugin artifact cleanup item')
  requireString(item, 'error', 'plugin artifact cleanup item')
  assertOptionalString(item, 'resolved_path', 'plugin artifact cleanup item')
}

function assertPluginArtifactCleanupResult(value: unknown): PluginArtifactCleanupResult {
  const result = ensureRecord(value, 'plugin artifact cleanup')
  requireString(result, 'status', 'plugin artifact cleanup')
  requireBoolean(result, 'dry_run', 'plugin artifact cleanup')
  requireString(result, 'cleanup_at', 'plugin artifact cleanup')
  requireString(result, 'storage_root', 'plugin artifact cleanup')
  requireNumber(result, 'scanned_plugin_count', 'plugin artifact cleanup')
  requireNumber(result, 'expired_count', 'plugin artifact cleanup')
  requireNumber(result, 'candidate_count', 'plugin artifact cleanup')
  requireNumber(result, 'would_delete_count', 'plugin artifact cleanup')
  requireNumber(result, 'deleted_count', 'plugin artifact cleanup')
  requireNumber(result, 'missing_count', 'plugin artifact cleanup')
  requireNumber(result, 'skipped_count', 'plugin artifact cleanup')
  requireNumber(result, 'error_count', 'plugin artifact cleanup')
  ensureArray(result.items, 'plugin artifact cleanup items').forEach(assertPluginArtifactCleanupItem)
  return value as PluginArtifactCleanupResult
}

function assertPluginAuditItem(value: unknown): PluginAuditItem {
  const item = ensureRecord(value, 'plugin audit item')
  requireText(item, 'audit_id', 'plugin audit item')
  requireText(item, 'plugin_id', 'plugin audit item')
  requireString(item, 'action', 'plugin audit item')
  requireString(item, 'actor', 'plugin audit item')
  requireString(item, 'message', 'plugin audit item')
  ensureRecord(item.payload_json, 'plugin audit item payload_json')
  requireString(item, 'created_at', 'plugin audit item')
  return value as PluginAuditItem
}

function assertPluginAuditList(value: unknown): PluginAuditItem[] {
  return ensureArray(value, 'plugin audit list').map(assertPluginAuditItem)
}

function assertPluginUsageStatsItem(value: unknown): PluginUsageStatsItem {
  const item = ensureRecord(value, 'plugin usage stats item')
  requireText(item, 'plugin_id', 'plugin usage stats item')
  requireNumber(item, 'window_event_limit', 'plugin usage stats item')
  requireNumber(item, 'total_audit_events', 'plugin usage stats item')
  requireNumber(item, 'sandbox_run_count', 'plugin usage stats item')
  requireNumber(item, 'sandbox_block_count', 'plugin usage stats item')
  requireNumber(item, 'execute_preview_count', 'plugin usage stats item')
  requireNumber(item, 'execute_preview_failed_count', 'plugin usage stats item')
  requireNumber(item, 'validation_count', 'plugin usage stats item')
  requireNumber(item, 'lifecycle_event_count', 'plugin usage stats item')
  assertNumberRecord(item.action_counts, 'plugin usage stats action_counts')
  assertNumberRecord(item.status_counts, 'plugin usage stats status_counts')
  requireString(item, 'last_action', 'plugin usage stats item')
  requireString(item, 'last_status', 'plugin usage stats item')
  requireString(item, 'last_actor', 'plugin usage stats item')
  requireString(item, 'last_audit_id', 'plugin usage stats item')
  requireString(item, 'last_run_at', 'plugin usage stats item')
  requireNumber(item, 'last_elapsed_ms', 'plugin usage stats item')
  requireNumber(item, 'average_elapsed_ms', 'plugin usage stats item')
  requireNumber(item, 'max_elapsed_ms', 'plugin usage stats item')
  return value as PluginUsageStatsItem
}

function assertPluginUsageStatsList(value: unknown): PluginUsageStatsItem[] {
  return ensureArray(value, 'plugin usage stats list').map(assertPluginUsageStatsItem)
}

function assertPluginUsageHistoryBucket(value: unknown) {
  const item = ensureRecord(value, 'plugin usage history item')
  requireText(item, 'plugin_id', 'plugin usage history item')
  requireString(item, 'bucket_start', 'plugin usage history item')
  requireString(item, 'bucket_label', 'plugin usage history item')
  requireNumber(item, 'total_audit_events', 'plugin usage history item')
  requireNumber(item, 'sandbox_run_count', 'plugin usage history item')
  requireNumber(item, 'sandbox_block_count', 'plugin usage history item')
  requireNumber(item, 'execute_preview_count', 'plugin usage history item')
  requireNumber(item, 'execute_preview_failed_count', 'plugin usage history item')
  requireNumber(item, 'validation_count', 'plugin usage history item')
  requireNumber(item, 'lifecycle_event_count', 'plugin usage history item')
  assertNumberRecord(item.action_counts, 'plugin usage history action_counts')
  assertNumberRecord(item.status_counts, 'plugin usage history status_counts')
  requireString(item, 'last_action', 'plugin usage history item')
  requireString(item, 'last_status', 'plugin usage history item')
  requireString(item, 'last_actor', 'plugin usage history item')
  requireString(item, 'last_audit_id', 'plugin usage history item')
  requireString(item, 'last_run_at', 'plugin usage history item')
  requireNumber(item, 'last_elapsed_ms', 'plugin usage history item')
  requireNumber(item, 'average_elapsed_ms', 'plugin usage history item')
  requireNumber(item, 'max_elapsed_ms', 'plugin usage history item')
}

function assertPluginUsageHistoryResponse(value: unknown): PluginUsageHistoryResponse {
  const response = ensureRecord(value, 'plugin usage history')
  requireString(response, 'generated_at', 'plugin usage history')
  requireString(response, 'bucket', 'plugin usage history')
  requireNumber(response, 'days', 'plugin usage history')
  requireNumber(response, 'plugin_count', 'plugin usage history')
  ensureArray(response.items, 'plugin usage history items').forEach(assertPluginUsageHistoryBucket)
  return value as PluginUsageHistoryResponse
}

function assertPluginValidateResult(value: unknown): PluginValidateResult {
  const result = ensureRecord(value, 'plugin validate')
  requireText(result, 'plugin_id', 'plugin validate')
  requireBoolean(result, 'valid', 'plugin validate')
  assertStringArray(result.failures, 'plugin validate failures')
  assertStringArray(result.warnings, 'plugin validate warnings')
  requireText(result, 'audit_id', 'plugin validate')
  return value as PluginValidateResult
}

function assertPluginRuntimeSchemaStatus(value: unknown) {
  const status = ensureRecord(value, 'plugin runtime schema status')
  requireBoolean(status, 'valid', 'plugin runtime schema status')
  requireBoolean(status, 'input_schema_declared', 'plugin runtime schema status')
  requireBoolean(status, 'output_schema_declared', 'plugin runtime schema status')
  assertStringArray(status.failures, 'plugin runtime schema failures')
}

function assertPluginPermissionSandbox(value: unknown) {
  const sandbox = ensureRecord(value, 'plugin permission sandbox')
  requireString(sandbox, 'mode', 'plugin permission sandbox')
  requireBoolean(sandbox, 'allowed', 'plugin permission sandbox')
  assertStringArray(sandbox.allowed_permissions, 'plugin permission sandbox allowed_permissions')
  assertStringArray(sandbox.blocked_permissions, 'plugin permission sandbox blocked_permissions')
  requireString(sandbox, 'code_execution', 'plugin permission sandbox')
  requireString(sandbox, 'filesystem_access', 'plugin permission sandbox')
  requireString(sandbox, 'network_access', 'plugin permission sandbox')
}

function assertPluginExecutionSandbox(value: unknown) {
  const sandbox = ensureRecord(value, 'plugin execution sandbox')
  requireText(sandbox, 'plugin_id', 'plugin execution sandbox')
  requireText(sandbox, 'agent_id', 'plugin execution sandbox')
  requireString(sandbox, 'mode', 'plugin execution sandbox')
  requireBoolean(sandbox, 'allowed', 'plugin execution sandbox')
  requireBoolean(sandbox, 'hot_reload_allowed', 'plugin execution sandbox')
  requireString(sandbox, 'execution_kind', 'plugin execution sandbox')
  requireString(sandbox, 'code_execution', 'plugin execution sandbox')
  requireBoolean(sandbox, 'direct_code_execution', 'plugin execution sandbox')
  requireString(sandbox, 'filesystem_access', 'plugin execution sandbox')
  requireString(sandbox, 'network_access', 'plugin execution sandbox')
  ensureRecord(sandbox.resource_limits, 'plugin execution sandbox resource_limits')
  requireBoolean(sandbox, 'custom_resource_limits', 'plugin execution sandbox')
  assertStringArray(sandbox.resource_limit_warnings, 'plugin execution sandbox resource_limit_warnings')
  ensureRecord(sandbox.schema_validation, 'plugin execution sandbox schema_validation')
  ensureRecord(sandbox.permission_boundary, 'plugin execution sandbox permission_boundary')
  ensureRecord(sandbox.risk_boundary, 'plugin execution sandbox risk_boundary')
  requireBoolean(sandbox, 'audit_required', 'plugin execution sandbox')
  requireBoolean(sandbox, 'rollback_supported', 'plugin execution sandbox')
  requireBoolean(sandbox, 'trade_action_hard_block', 'plugin execution sandbox')
  assertStringArray(sandbox.block_reasons, 'plugin execution sandbox block_reasons')
}

function assertPluginRiskGate(value: unknown) {
  const gate = ensureRecord(value, 'plugin risk gate')
  requireString(gate, 'risk_level', 'plugin risk gate')
  requireBoolean(gate, 'allowed', 'plugin risk gate')
  assertStringArray(gate.required_gates, 'plugin risk gate required_gates')
  assertStringArray(gate.forbidden_trade_actions, 'plugin risk gate forbidden_trade_actions')
  requireBoolean(gate, 'trade_actions_allowed', 'plugin risk gate')
  assertStringArray(gate.block_reasons, 'plugin risk gate block_reasons')
}

function assertPluginRuntimeAgentPlan(value: unknown) {
  const agent = ensureRecord(value, 'plugin runtime agent plan')
  requireText(agent, 'plugin_id', 'plugin runtime agent plan')
  requireString(agent, 'plugin_name', 'plugin runtime agent plan')
  requireText(agent, 'agent_id', 'plugin runtime agent plan')
  requireString(agent, 'agent_name', 'plugin runtime agent plan')
  requireText(agent, 'dag_node_id', 'plugin runtime agent plan')
  requireNumber(agent, 'plan_step', 'plugin runtime agent plan')
  requireBoolean(agent, 'enabled', 'plugin runtime agent plan')
  requireBoolean(agent, 'eligible', 'plugin runtime agent plan')
  requireString(agent, 'registration_status', 'plugin runtime agent plan')
  ensureRecord(agent.dag_registration, 'plugin runtime agent dag_registration')
  ensureRecord(agent.input_schema, 'plugin runtime agent input_schema')
  ensureRecord(agent.output_schema, 'plugin runtime agent output_schema')
  assertStringArray(agent.permissions, 'plugin runtime agent permissions')
  assertPluginRuntimeSchemaStatus(agent.schema_status)
  assertPluginPermissionSandbox(agent.permission_sandbox)
  assertPluginRiskGate(agent.risk_gate)
  assertPluginExecutionSandbox(agent.execution_sandbox)
  assertStringArray(agent.validation_failures, 'plugin runtime agent validation_failures')
  requireBoolean(agent, 'can_execute_code', 'plugin runtime agent plan')
  requireBoolean(agent, 'direct_execution', 'plugin runtime agent plan')
}

function assertPluginRuntimePlan(value: unknown): PluginRuntimePlan {
  const plan = ensureRecord(value, 'plugin runtime plan')
  requireString(plan, 'generated_at', 'plugin runtime plan')
  requireString(plan, 'status', 'plugin runtime plan')
  requireString(plan, 'sandbox_status', 'plugin runtime plan')
  requireNumber(plan, 'enabled_plugin_count', 'plugin runtime plan')
  requireNumber(plan, 'enabled_agent_count', 'plugin runtime plan')
  requireNumber(plan, 'registered_dag_node_count', 'plugin runtime plan')
  requireNumber(plan, 'hot_reload_agent_count', 'plugin runtime plan')
  ensureRecord(plan.resource_summary, 'plugin runtime plan resource_summary')
  ensureArray(plan.agents, 'plugin runtime plan agents').forEach(assertPluginRuntimeAgentPlan)
  assertStringArray(plan.forbidden_trade_actions, 'plugin runtime plan forbidden_trade_actions')
  assertStringArray(plan.required_gates, 'plugin runtime plan required_gates')
  assertStringArray(plan.notes, 'plugin runtime plan notes')
  return value as PluginRuntimePlan
}

function assertPluginSandboxRunResult(value: unknown): PluginSandboxRunResult {
  const result = ensureRecord(value, 'plugin sandbox run')
  requireText(result, 'plugin_id', 'plugin sandbox run')
  requireText(result, 'agent_id', 'plugin sandbox run')
  requireString(result, 'status', 'plugin sandbox run')
  requireString(result, 'mode', 'plugin sandbox run')
  requireText(result, 'audit_id', 'plugin sandbox run')
  requireString(result, 'actor', 'plugin sandbox run')
  requireString(result, 'started_at', 'plugin sandbox run')
  requireString(result, 'finished_at', 'plugin sandbox run')
  requireNumber(result, 'elapsed_ms', 'plugin sandbox run')
  ensureRecord(result.output, 'plugin sandbox run output')
  assertStringArray(result.errors, 'plugin sandbox run errors')
  ensureRecord(result.policy, 'plugin sandbox run policy')
  return value as PluginSandboxRunResult
}

export function listPlugins() {
  return request<unknown>('/plugins').then(assertPluginList)
}

export function getPluginRuntimePlan() {
  return request<unknown>('/plugins/runtime/plan').then(assertPluginRuntimePlan)
}

export function getPluginUsageStats() {
  return request<unknown>('/plugins/usage/stats').then(assertPluginUsageStatsList)
}

export function getPluginUsageHistory(days = 90) {
  return request<unknown>(`/plugins/usage/history?days=${days}`).then(assertPluginUsageHistoryResponse)
}

export function enablePlugin(pluginId: string) {
  return request<unknown>(`/plugins/${pluginId}/enable`, { method: 'POST' }).then(assertPluginItem)
}

export function disablePlugin(pluginId: string) {
  return request<unknown>(`/plugins/${pluginId}/disable`, { method: 'POST' }).then(assertPluginItem)
}

export function upgradePlugin(pluginId: string, payload: PluginUpgradePayload) {
  return request<unknown>(`/plugins/${pluginId}/upgrade`, {
    method: 'POST',
    body: JSON.stringify(payload),
  }).then(assertPluginItem)
}

export function uploadPluginArtifact(pluginId: string, file: File, payload: { expected_checksum?: string; reason?: string } = {}) {
  const form = new FormData()
  form.append('file', file)
  form.append('expected_checksum', payload.expected_checksum ?? '')
  form.append('reason', payload.reason ?? '')
  return request<unknown>(`/plugins/${pluginId}/artifacts`, {
    method: 'POST',
    body: form,
    timeoutMs: 30000,
  }).then(assertPluginArtifactUploadResult)
}

export function cleanupPluginArtifacts(payload: { dry_run?: boolean; reason?: string } = {}) {
  return request<unknown>('/plugins/artifacts/cleanup', {
    method: 'POST',
    body: JSON.stringify({
      dry_run: payload.dry_run ?? true,
      reason: payload.reason ?? '',
    }),
  }).then(assertPluginArtifactCleanupResult)
}

export function archivePlugin(pluginId: string, payload: { reason?: string } = {}) {
  return request<unknown>(`/plugins/${pluginId}/archive`, {
    method: 'POST',
    body: JSON.stringify(payload),
  }).then(assertPluginItem)
}

export function validatePlugin(pluginId: string) {
  return request<unknown>(`/plugins/${pluginId}/validate`, { method: 'POST' }).then(assertPluginValidateResult)
}

export function runPluginSandbox(pluginId: string, agentId: string, payload: { input_payload: Record<string, any> }) {
  return request<unknown>(`/plugins/${pluginId}/agents/${agentId}/sandbox-run`, {
    method: 'POST',
    body: JSON.stringify(payload),
  }).then(assertPluginSandboxRunResult)
}

export function getPluginAudit(pluginId: string) {
  return request<unknown>(`/plugins/${pluginId}/audit`).then(assertPluginAuditList)
}
