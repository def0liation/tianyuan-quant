import { request } from './httpClient'
import {
  AgentRuntimeConfig,
  DataSourceHealth,
  LLMConfigTestResult,
  MarketDataAdapterConfig,
  MarketDataConfigTestResult,
  MarketDataStatusMatrix,
  UpdateMarketDataAdapterConfigPayload,
  UpsertLLMProfilePayload,
  UpsertMarketDataProfilePayload,
} from '../types'

const MARKET_DATA_ADAPTER_HEALTH_TIMEOUT_MS = 130000

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
  const value = record[key]
  if (value !== undefined && value !== null && typeof value !== 'string') {
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
  const value = record[key]
  if (value !== undefined && value !== null && typeof value !== 'boolean') {
    throw new Error(`Unexpected ${label} response: invalid ${key}`)
  }
}

function assertPlainRecord(value: unknown, label: string) {
  ensureRecord(value, label)
}

function assertStringRecord(value: unknown, label: string) {
  const record = ensureRecord(value, label)
  Object.entries(record).forEach(([key, item]) => {
    if (typeof item !== 'string') {
      throw new Error(`Unexpected ${label} response: invalid ${key}`)
    }
  })
}

function assertStringArray(value: unknown, label: string) {
  ensureArray(value, label).forEach((item, index) => {
    if (typeof item !== 'string') {
      throw new Error(`Unexpected ${label} response: invalid item ${index}`)
    }
  })
}

function assertRuntimeBaseUrlSecurity(value: unknown) {
  const security = ensureRecord(value, 'runtime base URL security')
  assertOptionalString(security, 'status', 'runtime base URL security')
  assertOptionalBoolean(security, 'allowed', 'runtime base URL security')
  assertOptionalBoolean(security, 'strict_mode_required', 'runtime base URL security')
  assertOptionalString(security, 'message', 'runtime base URL security')
  assertOptionalString(security, 'code', 'runtime base URL security')
  assertOptionalString(security, 'host', 'runtime base URL security')
  assertOptionalString(security, 'reason', 'runtime base URL security')
  assertOptionalString(security, 'confirmed_at', 'runtime base URL security')
  assertOptionalString(security, 'confirmed_by', 'runtime base URL security')
  if (security.allowed_hosts !== undefined && security.allowed_hosts !== null) {
    assertStringArray(security.allowed_hosts, 'runtime base URL security allowed_hosts')
  }
}

function assertRuntimeConfigAuditInfo(value: unknown) {
  const audit = ensureRecord(value, 'runtime config audit')
  assertOptionalString(audit, 'audit_id', 'runtime config audit')
  assertOptionalString(audit, 'action', 'runtime config audit')
  assertOptionalString(audit, 'actor', 'runtime config audit')
  assertOptionalString(audit, 'updated_at', 'runtime config audit')
  assertOptionalString(audit, 'summary', 'runtime config audit')
  assertOptionalBoolean(audit, 'key_material_recorded', 'runtime config audit')
}

function assertRuntimeHealthFields(record: Record<string, unknown>, label: string) {
  assertOptionalBoolean(record, 'egress_confirmed', label)
  assertOptionalString(record, 'egress_policy_status', label)
  assertOptionalString(record, 'egress_policy_message', label)
  assertOptionalString(record, 'health_status', label)
  assertOptionalBoolean(record, 'last_call_success', label)
  assertOptionalString(record, 'last_error', label)
  assertOptionalString(record, 'last_checked_at', label)
  assertOptionalString(record, 'last_test_status', label)
  assertOptionalString(record, 'last_test_message', label)
  assertOptionalString(record, 'last_live_call_at', label)
  assertOptionalNumber(record, 'last_latency_ms', label)
  assertOptionalString(record, 'last_config_audit_id', label)
  if (record.health_warnings !== undefined && record.health_warnings !== null) {
    assertStringArray(record.health_warnings, `${label} health_warnings`)
  }
  if (record.base_url_security !== undefined && record.base_url_security !== null) {
    assertRuntimeBaseUrlSecurity(record.base_url_security)
  }
  if (record.config_audit !== undefined && record.config_audit !== null) {
    assertRuntimeConfigAuditInfo(record.config_audit)
  }
  if (record.last_usage !== undefined && record.last_usage !== null) {
    assertPlainRecord(record.last_usage, `${label} last_usage`)
  }
}

function assertAgentLLMProfile(value: unknown) {
  const profile = ensureRecord(value, 'agent LLM profile')
  requireString(profile, 'id', 'agent LLM profile')
  requireString(profile, 'label', 'agent LLM profile')
  requireString(profile, 'provider', 'agent LLM profile')
  requireString(profile, 'base_url', 'agent LLM profile')
  requireString(profile, 'model', 'agent LLM profile')
  assertOptionalBoolean(profile, 'configured', 'agent LLM profile')
  assertOptionalBoolean(profile, 'auth_available', 'agent LLM profile')
  requireBoolean(profile, 'api_key_set', 'agent LLM profile')
  assertOptionalString(profile, 'api_key_mask', 'agent LLM profile')
  requireNumber(profile, 'temperature', 'agent LLM profile')
  requireNumber(profile, 'max_tokens', 'agent LLM profile')
  requireNumber(profile, 'timeout_seconds', 'agent LLM profile')
  requireBoolean(profile, 'enabled', 'agent LLM profile')
  assertStringRecord(profile.extra_headers, 'agent LLM profile extra_headers')
  assertRuntimeHealthFields(profile, 'agent LLM profile')
}

function assertMarketDataProfile(value: unknown) {
  const profile = ensureRecord(value, 'market data profile')
  requireString(profile, 'id', 'market data profile')
  requireString(profile, 'label', 'market data profile')
  requireString(profile, 'provider', 'market data profile')
  requireString(profile, 'base_url', 'market data profile')
  requireString(profile, 'quote_path', 'market data profile')
  requireString(profile, 'symbol_query_param', 'market data profile')
  requireString(profile, 'auth_mode', 'market data profile')
  requireBoolean(profile, 'api_key_set', 'market data profile')
  assertOptionalString(profile, 'api_key_mask', 'market data profile')
  requireString(profile, 'api_key_header', 'market data profile')
  requireString(profile, 'api_key_query_param', 'market data profile')
  requireNumber(profile, 'timeout_seconds', 'market data profile')
  requireBoolean(profile, 'enabled', 'market data profile')
  assertStringRecord(profile.extra_headers, 'market data profile extra_headers')
  assertStringRecord(profile.extra_query_params, 'market data profile extra_query_params')
  requireString(profile, 'price_path', 'market data profile')
  requireString(profile, 'name_path', 'market data profile')
  requireString(profile, 'change_percent_path', 'market data profile')
  requireString(profile, 'volume_path', 'market data profile')
  requireString(profile, 'timestamp_path', 'market data profile')
  assertRuntimeHealthFields(profile, 'market data profile')
}

function assertAgentDeployment(value: unknown) {
  const agent = ensureRecord(value, 'agent runtime deployment')
  requireString(agent, 'id', 'agent runtime deployment')
  requireString(agent, 'name', 'agent runtime deployment')
  requireString(agent, 'stage', 'agent runtime deployment')
  requireString(agent, 'role', 'agent runtime deployment')
  requireString(agent, 'system_prompt_ref', 'agent runtime deployment')
  requireString(agent, 'llm_profile_id', 'agent runtime deployment')
  requireString(agent, 'status', 'agent runtime deployment')
  requireBoolean(agent, 'enabled', 'agent runtime deployment')
  assertOptionalString(agent, 'prompt_file', 'agent runtime deployment')
  assertOptionalString(agent, 'prompt_hash', 'agent runtime deployment')
  assertOptionalString(agent, 'node_type', 'agent runtime deployment')
  assertStringArray(agent.tool_scope, 'agent runtime deployment tool_scope')
  assertStringArray(agent.next_nodes, 'agent runtime deployment next_nodes')
  assertStringArray(agent.run_modes, 'agent runtime deployment run_modes')
  if (agent.allow_trade_action === true) {
    throw new Error('Unexpected agent runtime deployment response: allow_trade_action must remain false')
  }
  if (agent.final_decision_cap !== undefined && agent.final_decision_cap !== 'NO_DIRECT_TRADE_ACTION') {
    throw new Error('Unexpected agent runtime deployment response: final_decision_cap must remain NO_DIRECT_TRADE_ACTION')
  }
}

function assertAgentRuntimeConfig(value: unknown): AgentRuntimeConfig {
  const config = ensureRecord(value, 'agent runtime config')
  requireString(config, 'default_llm_profile_id', 'agent runtime config')
  requireString(config, 'default_market_data_profile_id', 'agent runtime config')
  requireNumber(config, 'max_parallel_agents', 'agent runtime config')
  requireString(config, 'updated_at', 'agent runtime config')
  ensureArray(config.llm_profiles, 'agent runtime llm_profiles').forEach(assertAgentLLMProfile)
  ensureArray(config.market_data_profiles, 'agent runtime market_data_profiles').forEach(assertMarketDataProfile)
  ensureArray(config.agents, 'agent runtime agents').forEach(assertAgentDeployment)
  return value as AgentRuntimeConfig
}

function assertLLMConfigTestResult(value: unknown): LLMConfigTestResult {
  const result = ensureRecord(value, 'LLM config test result')
  requireString(result, 'profile_id', 'LLM config test result')
  requireString(result, 'status', 'LLM config test result')
  requireString(result, 'message', 'LLM config test result')
  if (result.details !== undefined && result.details !== null) {
    assertPlainRecord(result.details, 'LLM config test result details')
  }
  return value as LLMConfigTestResult
}

function assertMarketDataConfigTestResult(value: unknown): MarketDataConfigTestResult {
  const result = ensureRecord(value, 'market data config test result')
  requireString(result, 'profile_id', 'market data config test result')
  requireString(result, 'status', 'market data config test result')
  requireString(result, 'message', 'market data config test result')
  if (result.details !== undefined && result.details !== null) {
    assertPlainRecord(result.details, 'market data config test result details')
  }
  return value as MarketDataConfigTestResult
}

function assertDataSourceHealth(value: unknown): DataSourceHealth {
  const health = ensureRecord(value, 'market data adapter health')
  requireString(health, 'adapterId', 'market data adapter health')
  requireString(health, 'provider', 'market data adapter health')
  requireString(health, 'label', 'market data adapter health')
  assertStringArray(health.capabilities, 'market data adapter health capabilities')
  assertOptionalBoolean(health, 'configured', 'market data adapter health')
  requireBoolean(health, 'healthy', 'market data adapter health')
  assertOptionalBoolean(health, 'upstreamHealthy', 'market data adapter health')
  assertOptionalBoolean(health, 'liveDataUsable', 'market data adapter health')
  assertOptionalBoolean(health, 'fallbackUsed', 'market data adapter health')
  assertOptionalString(health, 'lastError', 'market data adapter health')
  assertOptionalString(health, 'freshness', 'market data adapter health')
  requireString(health, 'lastCheckAt', 'market data adapter health')
  requireNumber(health, 'latencyAvgMs', 'market data adapter health')
  requireString(health, 'message', 'market data adapter health')
  requireBoolean(health, 'enabled', 'market data adapter health')
  requireBoolean(health, 'installed', 'market data adapter health')
  assertOptionalString(health, 'healthCheckMode', 'market data adapter health')
  return value as DataSourceHealth
}

function assertDataSourceHealthList(value: unknown): DataSourceHealth[] {
  return ensureArray(value, 'market data adapter health list').map(assertDataSourceHealth)
}

function assertMarketDataAdapterConfig(value: unknown): MarketDataAdapterConfig {
  const config = ensureRecord(value, 'market data adapter config')
  requireString(config, 'adapter_id', 'market data adapter config')
  requireString(config, 'provider', 'market data adapter config')
  requireString(config, 'label', 'market data adapter config')
  requireBoolean(config, 'enabled', 'market data adapter config')
  requireNumber(config, 'priority', 'market data adapter config')
  requireNumber(config, 'timeout_seconds', 'market data adapter config')
  requireBoolean(config, 'requires_token', 'market data adapter config')
  if (config.capabilities !== undefined && config.capabilities !== null) {
    assertStringArray(config.capabilities, 'market data adapter config capabilities')
  }
  requireString(config, 'note', 'market data adapter config')
  return value as MarketDataAdapterConfig
}

function assertMarketDataAdapterConfigList(value: unknown): MarketDataAdapterConfig[] {
  return ensureArray(value, 'market data adapter config list').map(assertMarketDataAdapterConfig)
}

function assertMarketDataStatusMatrix(value: unknown): MarketDataStatusMatrix {
  const matrix = ensureRecord(value, 'market data status matrix')
  const categories = ensureRecord(matrix.categories, 'market data status categories')
  Object.values(categories).forEach((category) => {
    const adapters = ensureRecord(category, 'market data status category')
    Object.values(adapters).forEach(assertDataSourceHealth)
  })
  requireString(matrix, 'generatedAt', 'market data status matrix')
  return value as MarketDataStatusMatrix
}

export function getAgentRuntime() {
  return request<unknown>('/agents/runtime').then(assertAgentRuntimeConfig)
}

export function updateAgentRuntime(payload: {
  default_llm_profile_id?: string
  default_market_data_profile_id?: string
  max_parallel_agents?: number
  apply_default_to_all_agents?: boolean
}) {
  return request<unknown>('/agents/runtime', {
    method: 'PATCH',
    body: JSON.stringify(payload),
  }).then(assertAgentRuntimeConfig)
}

export function upsertLLMProfile(profileId: string, payload: UpsertLLMProfilePayload) {
  return request<unknown>(`/agents/runtime/llm-profiles/${profileId}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  }).then(assertAgentRuntimeConfig)
}

export function upsertMarketDataProfile(profileId: string, payload: UpsertMarketDataProfilePayload) {
  return request<unknown>(`/agents/runtime/market-data-profiles/${profileId}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  }).then(assertAgentRuntimeConfig)
}

export function updateAgentLLM(agentId: string, payload: {
  llm_profile_id?: string
  enabled?: boolean
}) {
  return request<unknown>(`/agents/${agentId}/llm`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  }).then(assertAgentRuntimeConfig)
}

export function testLLMProfile(profileId: string, liveCall = false) {
  return request<unknown>('/agents/runtime/test', {
    method: 'POST',
    body: JSON.stringify({ profile_id: profileId, live_call: liveCall }),
    timeoutMs: liveCall ? 25000 : 15000,
  }).then(assertLLMConfigTestResult)
}

export function validateLLMProfileConfig(config: {
  provider: string
  base_url: string
  model: string
  api_key: string
  enabled: boolean
}) {
  return request<unknown>('/agents/runtime/validate-config', {
    method: 'POST',
    body: JSON.stringify(config),
    timeoutMs: 5000,
  }).then(assertLLMConfigTestResult)
}

export function testMarketDataProfile(profileId: string, payload: { symbol?: string; live_call?: boolean }) {
  return request<unknown>('/agents/runtime/market-data/test', {
    method: 'POST',
    body: JSON.stringify({ profile_id: profileId, ...payload }),
  }).then(assertMarketDataConfigTestResult)
}

export function getMarketDataAdapters(options: { liveCheck?: boolean } = {}) {
  const qs = options.liveCheck ? '?live_check=true' : ''
  return request<unknown>(`/agents/market-data/adapters${qs}`, { timeoutMs: options.liveCheck ? MARKET_DATA_ADAPTER_HEALTH_TIMEOUT_MS : 10000 })
    .then(assertDataSourceHealthList)
}

export function getMarketDataAdapterConfigs() {
  return request<unknown>('/agents/market-data/adapters/config').then(assertMarketDataAdapterConfigList)
}

export function putMarketDataAdapterConfig(adapterId: string, payload: UpdateMarketDataAdapterConfigPayload) {
  return request<unknown>(`/agents/market-data/adapters/${adapterId}/config`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  }).then(assertMarketDataAdapterConfig)
}

export function postAdapterHealth(adapterId: string) {
  return request<unknown>(`/agents/market-data/adapters/${adapterId}/health`, {
    method: 'POST',
    timeoutMs: MARKET_DATA_ADAPTER_HEALTH_TIMEOUT_MS,
  }).then(assertDataSourceHealth)
}

export function getMarketDataStatus() {
  return request<unknown>('/agents/market-data/status').then(assertMarketDataStatusMatrix)
}
