import { request } from './httpClient'
import { ConfigProfile, ConfigSchemaItem, ConfigDraft, PolicyCheckResult } from '../types'

export interface ConfigChangePayload {
  changes: Record<string, any>
}

export interface RuntimeConfigPatchResult {
  status: 'APPLIED'
  profile_id: string
  version: number
  audit_id: string
}

export interface ConfigDraftApplyResult {
  status: 'APPLIED'
  version: number
  rollback_version: number
  audit_id: string
}

export interface ConfigRollbackResult {
  status: 'ROLLED_BACK'
  current_version: number
  rollback_target_version?: number
  audit_id: string
}

export function getCurrentConfig() {
  return request<unknown>('/config/current').then(assertConfigProfile)
}

export function getConfigSchema() {
  return request<unknown>('/config/schema').then(assertConfigSchema)
}

export function patchRuntimeConfig(payload: ConfigChangePayload) {
  return request<unknown>('/config/runtime', {
    method: 'PATCH',
    body: JSON.stringify(payload),
  }).then(assertRuntimeConfigPatchResult)
}

export function validateConfigChange(payload: ConfigChangePayload) {
  return request<unknown>('/config/validate', {
    method: 'POST',
    body: JSON.stringify(payload),
  }).then(assertPolicyCheckResult)
}

export function createConfigDraft(payload: { changes: Record<string, any>; reason: string }) {
  return request<unknown>('/config/drafts', {
    method: 'POST',
    body: JSON.stringify(payload),
  }).then(assertConfigDraft)
}

export function applyConfigDraft(draftId: string) {
  return request<unknown>(`/config/drafts/${draftId}/apply`, {
    method: 'POST',
  }).then(assertConfigDraftApplyResult)
}

export function rollbackConfig(payload: { target_version: number; reason: string }) {
  return request<unknown>('/config/rollback', {
    method: 'POST',
    body: JSON.stringify(payload),
  }).then(assertConfigRollbackResult)
}

export interface ExternalConfigRestorePayload {
  profile_id: string
  target_version?: number
  audit_id?: string
  reason: string
  approval_id: string
  approved_by?: string
  confirm_secret_safe: boolean
}

export interface ExternalConfigRestoreResult {
  status: 'RESTORED'
  profile_id: string
  target_version: number
  target_audit_id: string
  restore_audit_id: string
  approval_id: string
  approved_by: string
  applied_keys: string[]
  required_secret_ref_count: number
  skipped_redacted_paths: string[]
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
  if (typeof record[key] !== 'number' || Number.isNaN(record[key])) {
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
  const value = record[key]
  if (value !== undefined && value !== null && (typeof value !== 'number' || Number.isNaN(value))) {
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

function assertRequiredSecretRef(value: unknown) {
  const ref = ensureRecord(value, 'config version required secret ref')
  requireString(ref, 'path', 'config version required secret ref')
  requireString(ref, 'ref', 'config version required secret ref')
}

function assertApprovalGate(value: unknown) {
  const gate = ensureRecord(value, 'config version approval gate')
  requireBoolean(gate, 'required', 'config version approval gate')
  assertOptionalString(gate, 'status', 'config version approval gate')
  assertOptionalString(gate, 'scope', 'config version approval gate')
  assertOptionalString(gate, 'approver_role', 'config version approval gate')
  assertOptionalBoolean(gate, 'secret_vault_version_required', 'config version approval gate')
  assertOptionalString(gate, 'restore_source', 'config version approval gate')
  assertOptionalString(gate, 'reason', 'config version approval gate')
  if (gate.required_secret_refs !== undefined && gate.required_secret_refs !== null) {
    ensureArray(gate.required_secret_refs, 'config version required_secret_refs').forEach(assertRequiredSecretRef)
  }
}

function assertRollbackPolicy(value: unknown) {
  const policy = ensureRecord(value, 'config version rollback policy')
  requireBoolean(policy, 'supported', 'config version rollback policy')
  assertOptionalBoolean(policy, 'approval_required', 'config version rollback policy')
  assertOptionalBoolean(policy, 'secret_safe_required', 'config version rollback policy')
  assertOptionalString(policy, 'blocked_reason', 'config version rollback policy')
  if (policy.approval_gate !== undefined && policy.approval_gate !== null) {
    assertApprovalGate(policy.approval_gate)
  }
}

function assertConfigVersionItem(value: unknown): ConfigVersionItem {
  const item = ensureRecord(value, 'config version item')
  requireNumber(item, 'version', 'config version item')
  requireString(item, 'created_at', 'config version item')
  requireString(item, 'created_by', 'config version item')
  requireString(item, 'change_summary', 'config version item')
  requireText(item, 'audit_id', 'config version item')
  requireString(item, 'status', 'config version item')
  requireBoolean(item, 'rollback_available', 'config version item')
  assertOptionalString(item, 'profile_id', 'config version item')
  assertOptionalBoolean(item, 'approval_required', 'config version item')
  assertOptionalBoolean(item, 'snapshot_redacted', 'config version item')
  if (item.effective_scope !== undefined && item.effective_scope !== null) {
    assertStringArray(item.effective_scope, 'config version effective_scope')
  }
  if (item.rollback_policy !== undefined && item.rollback_policy !== null) {
    assertRollbackPolicy(item.rollback_policy)
  }
  return value as ConfigVersionItem
}

function assertConfigVersionList(value: unknown): ConfigVersionItem[] {
  return ensureArray(value, 'config version history').map(assertConfigVersionItem)
}

function assertExternalConfigRestoreResult(value: unknown): ExternalConfigRestoreResult {
  const result = ensureRecord(value, 'external config restore')
  if (result.status !== 'RESTORED') {
    throw new Error('Unexpected external config restore response: invalid status')
  }
  requireText(result, 'profile_id', 'external config restore')
  requireNumber(result, 'target_version', 'external config restore')
  requireText(result, 'target_audit_id', 'external config restore')
  requireText(result, 'restore_audit_id', 'external config restore')
  requireText(result, 'approval_id', 'external config restore')
  requireString(result, 'approved_by', 'external config restore')
  requireNumber(result, 'required_secret_ref_count', 'external config restore')
  assertStringArray(result.applied_keys, 'external config restore applied_keys')
  assertStringArray(result.skipped_redacted_paths, 'external config restore skipped_redacted_paths')
  return value as ExternalConfigRestoreResult
}

function assertRecordField(record: Record<string, unknown>, key: string, label: string) {
  ensureRecord(record[key], `${label} ${key}`)
}

function assertConfigProfile(value: unknown): ConfigProfile {
  const profile = ensureRecord(value, 'config profile')
  requireText(profile, 'profile_id', 'config profile')
  requireNumber(profile, 'version', 'config profile')
  assertRecordField(profile, 'locked_guardrails', 'config profile')
  assertRecordField(profile, 'safe_runtime_config', 'config profile')
  assertRecordField(profile, 'review_required_config', 'config profile')
  assertRecordField(profile, 'sandbox_config', 'config profile')
  requireString(profile, 'created_at', 'config profile')
  requireString(profile, 'updated_at', 'config profile')
  return value as ConfigProfile
}

function assertConfigSchemaItem(value: unknown): ConfigSchemaItem {
  const item = ensureRecord(value, 'config schema item')
  requireText(item, 'key', 'config schema item')
  requireString(item, 'label', 'config schema item')
  requireText(item, 'type', 'config schema item')
  requireText(item, 'layer', 'config schema item')
  requireBoolean(item, 'editable', 'config schema item')
  requireString(item, 'direction', 'config schema item')
  requireString(item, 'description', 'config schema item')
  if (item.min !== undefined && item.min !== null) requireNumber(item, 'min', 'config schema item')
  if (item.max !== undefined && item.max !== null) requireNumber(item, 'max', 'config schema item')
  if (item.options !== undefined && item.options !== null) assertStringArray(item.options, 'config schema item options')
  return value as ConfigSchemaItem
}

function assertConfigSchema(value: unknown): ConfigSchemaItem[] {
  return ensureArray(value, 'config schema').map(assertConfigSchemaItem)
}

function assertPolicyCheckResult(value: unknown): PolicyCheckResult {
  const result = ensureRecord(value, 'config policy check')
  requireBoolean(result, 'passed', 'config policy check')
  requireText(result, 'level', 'config policy check')
  assertStringArray(result.warnings, 'config policy check warnings')
  assertStringArray(result.blocked_reasons, 'config policy check blocked_reasons')
  assertRecordField(result, 'effective_changes', 'config policy check')
  return value as PolicyCheckResult
}

function assertConfigDraft(value: unknown): ConfigDraft {
  const draft = ensureRecord(value, 'config draft')
  requireText(draft, 'draft_id', 'config draft')
  requireText(draft, 'status', 'config draft')
  assertRecordField(draft, 'changes', 'config draft')
  requireString(draft, 'reason', 'config draft')
  assertRecordField(draft, 'policy_check', 'config draft')
  requireText(draft, 'audit_id', 'config draft')
  requireString(draft, 'created_at', 'config draft')
  return value as ConfigDraft
}

function assertRuntimeConfigPatchResult(value: unknown): RuntimeConfigPatchResult {
  const result = ensureRecord(value, 'runtime config patch')
  if (result.status !== 'APPLIED') {
    throw new Error('Unexpected runtime config patch response: invalid status')
  }
  requireText(result, 'profile_id', 'runtime config patch')
  requireNumber(result, 'version', 'runtime config patch')
  requireText(result, 'audit_id', 'runtime config patch')
  return value as RuntimeConfigPatchResult
}

function assertConfigDraftApplyResult(value: unknown): ConfigDraftApplyResult {
  const result = ensureRecord(value, 'config draft apply')
  if (result.status !== 'APPLIED') {
    throw new Error('Unexpected config draft apply response: invalid status')
  }
  requireNumber(result, 'version', 'config draft apply')
  requireNumber(result, 'rollback_version', 'config draft apply')
  requireText(result, 'audit_id', 'config draft apply')
  return value as ConfigDraftApplyResult
}

function assertConfigRollbackResult(value: unknown): ConfigRollbackResult {
  const result = ensureRecord(value, 'config rollback')
  if (result.status !== 'ROLLED_BACK') {
    throw new Error('Unexpected config rollback response: invalid status')
  }
  requireNumber(result, 'current_version', 'config rollback')
  if (result.rollback_target_version !== undefined && result.rollback_target_version !== null) {
    requireNumber(result, 'rollback_target_version', 'config rollback')
  }
  requireText(result, 'audit_id', 'config rollback')
  return value as ConfigRollbackResult
}

export function restoreExternalConfig(payload: ExternalConfigRestorePayload) {
  return request<unknown>('/config/external-restore', {
    method: 'POST',
    body: JSON.stringify(payload),
  }).then(assertExternalConfigRestoreResult)
}

export interface ConfigVersionItem {
  profile_id?: string
  version: number
  created_at: string
  created_by: string
  change_summary: string
  audit_id: string
  status: string
  rollback_available: boolean
  approval_required?: boolean
  effective_scope?: string[]
  snapshot_redacted?: boolean
  rollback_policy?: {
    supported: boolean
    approval_required?: boolean
    secret_safe_required?: boolean
    blocked_reason?: string
    approval_gate?: {
      required: boolean
      status?: string
      scope?: string
      approver_role?: string
      secret_vault_version_required?: boolean
      required_secret_refs?: Array<{
        path: string
        ref: string
      }>
      restore_source?: string
      reason?: string
    }
  }
}

export function getConfigVersions(includeExternal = false, filters: {
  profile_id?: string
  created_by?: string
  status?: string
  limit?: number
} = {}) {
  const params = new URLSearchParams()
  if (includeExternal) params.set('include_external', 'true')
  if (filters.profile_id) params.set('profile_id', filters.profile_id)
  if (filters.created_by) params.set('created_by', filters.created_by)
  if (filters.status) params.set('status', filters.status)
  if (filters.limit) params.set('limit', String(filters.limit))
  const query = params.toString()
  return request<unknown>(`/config/versions${query ? `?${query}` : ''}`).then(assertConfigVersionList)
}

export interface DataSourceItem {
  key: string
  name: string
  tushare_api: string
  enabled: boolean
  description: string
  required_credits?: number
  tier_label?: string
  provider_apis?: Record<string, string>
  providers?: string[]
}

export interface DataSourcesConfig {
  tushare_token: string
  tushare_token_set?: boolean
  tushare_token_mask?: string | null
  sources: DataSourceItem[]
}

export function getDataSourcesConfig() {
  return request<unknown>('/agents/data-sources').then(assertDataSourcesConfig)
}

export function putDataSourcesConfig(tushare_token?: string, sources?: DataSourceItem[]) {
  return request<unknown>('/agents/data-sources', {
    method: 'PUT',
    body: JSON.stringify({ tushare_token, sources }),
  }).then(assertDataSourcesConfig)
}

export interface DataSourceTestResult {
  key: string
  name: string
  status: 'READY' | 'FAILED' | 'NOT_CONFIGURED'
  message: string
  latency_ms?: number
  record_count?: number
  diagnosis?: string
  failed_apis?: string[]
  api_results?: Array<{
    api: string
    status: 'READY' | 'FAILED'
    record_count?: number
    diagnosis?: string
    error?: string
  }>
  error?: string
}

export function testDataSourceConnection(key: string) {
  return request<unknown>(`/agents/data-sources/${key}/test`, {
    method: 'POST',
  }).then(assertDataSourceTestResult)
}

function assertDataSourceItem(value: unknown): DataSourceItem {
  const item = ensureRecord(value, 'data source item')
  requireString(item, 'key', 'data source item')
  requireString(item, 'name', 'data source item')
  requireString(item, 'tushare_api', 'data source item')
  requireBoolean(item, 'enabled', 'data source item')
  requireString(item, 'description', 'data source item')
  assertOptionalNumber(item, 'required_credits', 'data source item')
  assertOptionalString(item, 'tier_label', 'data source item')
  assertOptionalStringMap(item, 'provider_apis', 'data source item')
  if (item.providers !== undefined && item.providers !== null) {
    assertStringArray(item.providers, 'data source item providers')
  }
  return value as DataSourceItem
}

function assertOptionalStringMap(record: Record<string, unknown>, key: string, label: string) {
  const value = record[key]
  if (value === undefined || value === null) return
  const map = ensureRecord(value, `${label} ${key}`)
  Object.values(map).forEach((entry) => {
    if (typeof entry !== 'string') {
      throw new Error(`Unexpected ${label} response: invalid ${key}`)
    }
  })
}

function assertDataSourcesConfig(value: unknown): DataSourcesConfig {
  const config = ensureRecord(value, 'data sources config')
  requireString(config, 'tushare_token', 'data sources config')
  assertOptionalBoolean(config, 'tushare_token_set', 'data sources config')
  assertOptionalString(config, 'tushare_token_mask', 'data sources config')
  ensureArray(config.sources, 'data sources config sources').forEach(assertDataSourceItem)
  return value as DataSourcesConfig
}

function assertDataSourceApiResult(value: unknown) {
  const result = ensureRecord(value, 'data source API test result')
  requireString(result, 'api', 'data source API test result')
  requireString(result, 'status', 'data source API test result')
  assertOptionalNumber(result, 'record_count', 'data source API test result')
  assertOptionalString(result, 'diagnosis', 'data source API test result')
  assertOptionalString(result, 'error', 'data source API test result')
}

function assertDataSourceTestResult(value: unknown): DataSourceTestResult {
  const result = ensureRecord(value, 'data source test result')
  requireString(result, 'key', 'data source test result')
  requireString(result, 'name', 'data source test result')
  requireString(result, 'status', 'data source test result')
  requireString(result, 'message', 'data source test result')
  assertOptionalNumber(result, 'latency_ms', 'data source test result')
  assertOptionalNumber(result, 'record_count', 'data source test result')
  assertOptionalString(result, 'diagnosis', 'data source test result')
  assertOptionalString(result, 'error', 'data source test result')
  if (result.failed_apis !== undefined && result.failed_apis !== null) {
    assertStringArray(result.failed_apis, 'data source test failed_apis')
  }
  if (result.api_results !== undefined && result.api_results !== null) {
    ensureArray(result.api_results, 'data source test api_results').forEach(assertDataSourceApiResult)
  }
  return value as DataSourceTestResult
}
