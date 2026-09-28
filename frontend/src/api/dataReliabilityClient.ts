import { request } from './httpClient'
import { DataSourceHealth } from '../types'

export interface DataReliabilitySummary {
  generatedAt: string
  adapterCount: number
  checkedCount?: number
  healthyCount: number
  partialCount?: number
  failedCount: number
  overallStatus: string
  lastFailureReasons: Array<{
    adapterId: string
    provider: string
    message: string
    diagnosis: string
  }>
  partialReasons?: Array<{
    adapterId: string
    provider: string
    message: string
    diagnosis: string
  }>
}

export interface DataReliabilityAdapter extends DataSourceHealth {
  priority?: number | null
  timeoutSeconds?: number | null
  requiresToken?: boolean
  note?: string
  status?: string
  diagnosis?: string
}

export interface DataReliabilityMatrix {
  categories: Record<string, Record<string, DataReliabilityAdapter>>
  generatedAt: string
}

export interface DataReliabilityExternalMonitorStatus {
  schema: string
  checked: boolean
  reported: boolean
  status: string
  sidecarFile: string
  reportedAt: string
  source: string
  provider: string
  monitorBackend: string
  monitorStatus: string
  freshnessStatus: string
  retentionPolicyId: string
  retentionStatus: string
  retentionDays?: number | null
  retentionExpiresAt: string
  outageCount: number
  degradedSourceCount: number
  staleSourceCount: number
  latencyP95Ms?: number | null
  latestIncidentAt: string
  searchIndex: string
  searchIndexReady: boolean
  message: string
  deploymentReported: boolean
  localEventTrail: string
  issues: string[]
}

export interface DataReliabilitySnapshot {
  generatedAt: string
  summary: DataReliabilitySummary
  adapters: DataReliabilityAdapter[]
  matrix: DataReliabilityMatrix
  config: {
    dataSources: {
      tushare_token_set: boolean
      tushare_token_mask?: string
      sources: Array<{
        key: string
        name: string
        enabled: boolean
        tier_label?: string
        required_credits?: number
        provider_apis?: Record<string, string>
        providers?: string[]
      }>
    }
    adapterConfigs: Array<{
      adapter_id: string
      provider: string
      label: string
      enabled: boolean
      priority: number
      timeout_seconds: number
      requires_token: boolean
      capabilities?: string[]
      note: string
    }>
  }
  history: DataReliabilityHistoryItem[]
  events?: DataReliabilityEventItem[]
  externalMonitorStatus?: DataReliabilityExternalMonitorStatus
}

export interface SymbolHealthResult {
  symbol: string
  generatedAt: string
  overallStatus: string
  results: Array<{
    category: string
    status: string
    healthy: boolean
    provider: string
    adapterId: string
    latencyMs: number
    recordCount: number
    freshness: string
    error: string
    message: string
    diagnosis: string
    fallbackChain: Array<Record<string, unknown>>
  }>
}

export interface DataReliabilityHistoryItem {
  id: number
  checkType: string
  symbol: string
  adapterId: string
  provider: string
  category: string
  status: string
  healthy: boolean
  upstreamHealthy?: boolean | null
  liveDataUsable?: boolean | null
  fallbackUsed?: boolean | null
  latencyMs: number
  message: string
  error: string
  diagnosis?: string
  createdAt: string
}

export interface DataReliabilityEventItem {
  id: number
  symbol: string
  adapterId: string
  provider: string
  category: string
  eventType: string
  message: string
  error: string
  diagnosis?: string
  status?: string
  healthy?: boolean | null
  fallbackUsed?: boolean | null
  upstreamHealthy?: boolean | null
  liveDataUsable?: boolean | null
  latencyMs?: number | null
  recordCount?: number | null
  createdAt: string
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
  if (record[key] !== undefined && record[key] !== null && (typeof record[key] !== 'number' || Number.isNaN(record[key]))) {
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

function assertReasonRow(value: unknown, label: string) {
  const row = ensureRecord(value, label)
  requireString(row, 'adapterId', label)
  requireString(row, 'provider', label)
  requireString(row, 'message', label)
  requireString(row, 'diagnosis', label)
}

function assertDataReliabilitySummary(value: unknown): DataReliabilitySummary {
  const summary = ensureRecord(value, 'data health summary')
  requireString(summary, 'generatedAt', 'data health summary')
  requireNumber(summary, 'adapterCount', 'data health summary')
  assertOptionalNumber(summary, 'checkedCount', 'data health summary')
  requireNumber(summary, 'healthyCount', 'data health summary')
  assertOptionalNumber(summary, 'partialCount', 'data health summary')
  requireNumber(summary, 'failedCount', 'data health summary')
  requireString(summary, 'overallStatus', 'data health summary')
  ensureArray(summary.lastFailureReasons, 'data health summary failure reasons').forEach((row) =>
    assertReasonRow(row, 'data health summary failure reason'),
  )
  if (summary.partialReasons !== undefined) {
    ensureArray(summary.partialReasons, 'data health summary partial reasons').forEach((row) =>
      assertReasonRow(row, 'data health summary partial reason'),
    )
  }
  return value as DataReliabilitySummary
}

function assertDataReliabilityAdapter(value: unknown, label = 'data reliability adapter'): DataReliabilityAdapter {
  const adapter = ensureRecord(value, label)
  requireString(adapter, 'adapterId', label)
  requireString(adapter, 'provider', label)
  requireString(adapter, 'label', label)
  assertStringArray(adapter.capabilities, `${label} capabilities`)
  assertOptionalBoolean(adapter, 'configured', label)
  requireBoolean(adapter, 'healthy', label)
  assertOptionalBoolean(adapter, 'upstreamHealthy', label)
  assertOptionalBoolean(adapter, 'liveDataUsable', label)
  assertOptionalBoolean(adapter, 'fallbackUsed', label)
  assertOptionalString(adapter, 'lastError', label)
  assertOptionalString(adapter, 'freshness', label)
  requireString(adapter, 'lastCheckAt', label)
  requireNumber(adapter, 'latencyAvgMs', label)
  requireString(adapter, 'message', label)
  requireBoolean(adapter, 'enabled', label)
  requireBoolean(adapter, 'installed', label)
  assertOptionalNumber(adapter, 'priority', label)
  assertOptionalNumber(adapter, 'timeoutSeconds', label)
  assertOptionalBoolean(adapter, 'requiresToken', label)
  assertOptionalString(adapter, 'note', label)
  assertOptionalString(adapter, 'status', label)
  assertOptionalString(adapter, 'diagnosis', label)
  return value as DataReliabilityAdapter
}

function assertDataReliabilityMatrix(value: unknown): DataReliabilityMatrix {
  const matrix = ensureRecord(value, 'data health matrix')
  requireString(matrix, 'generatedAt', 'data health matrix')
  const categories = ensureRecord(matrix.categories, 'data health matrix categories')
  Object.values(categories).forEach((category) => {
    const entries = ensureRecord(category, 'data health matrix category')
    Object.values(entries).forEach((adapter) => assertDataReliabilityAdapter(adapter, 'data reliability matrix adapter'))
  })
  return value as DataReliabilityMatrix
}

function assertDataReliabilityConfig(value: unknown) {
  const config = ensureRecord(value, 'data health config')
  const dataSources = ensureRecord(config.dataSources, 'data health data sources config')
  requireBoolean(dataSources, 'tushare_token_set', 'data health data sources config')
  assertOptionalString(dataSources, 'tushare_token_mask', 'data health data sources config')
  ensureArray(dataSources.sources, 'data health data source entries').forEach((source) => {
    const row = ensureRecord(source, 'data health data source entry')
    requireString(row, 'key', 'data health data source entry')
    requireString(row, 'name', 'data health data source entry')
    requireBoolean(row, 'enabled', 'data health data source entry')
    assertOptionalString(row, 'tier_label', 'data health data source entry')
    assertOptionalNumber(row, 'required_credits', 'data health data source entry')
    assertOptionalStringMap(row, 'provider_apis', 'data health data source entry')
    if (row.providers !== undefined && row.providers !== null) {
      assertStringArray(row.providers, 'data health data source entry providers')
    }
  })
  ensureArray(config.adapterConfigs, 'data health adapter configs').forEach((adapterConfig) => {
    const row = ensureRecord(adapterConfig, 'data health adapter config')
    requireString(row, 'adapter_id', 'data health adapter config')
    requireString(row, 'provider', 'data health adapter config')
    requireString(row, 'label', 'data health adapter config')
    requireBoolean(row, 'enabled', 'data health adapter config')
    requireNumber(row, 'priority', 'data health adapter config')
    requireNumber(row, 'timeout_seconds', 'data health adapter config')
    requireBoolean(row, 'requires_token', 'data health adapter config')
    if (row.capabilities !== undefined && row.capabilities !== null) {
      assertStringArray(row.capabilities, 'data health adapter config capabilities')
    }
    requireString(row, 'note', 'data health adapter config')
  })
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

function assertDataReliabilityHistoryItem(value: unknown): DataReliabilityHistoryItem {
  const item = ensureRecord(value, 'data health history item')
  requireNumber(item, 'id', 'data health history item')
  requireString(item, 'checkType', 'data health history item')
  requireString(item, 'symbol', 'data health history item')
  requireString(item, 'adapterId', 'data health history item')
  requireString(item, 'provider', 'data health history item')
  requireString(item, 'category', 'data health history item')
  requireString(item, 'status', 'data health history item')
  requireBoolean(item, 'healthy', 'data health history item')
  assertOptionalBoolean(item, 'upstreamHealthy', 'data health history item')
  assertOptionalBoolean(item, 'liveDataUsable', 'data health history item')
  assertOptionalBoolean(item, 'fallbackUsed', 'data health history item')
  requireNumber(item, 'latencyMs', 'data health history item')
  requireString(item, 'message', 'data health history item')
  requireString(item, 'error', 'data health history item')
  assertOptionalString(item, 'diagnosis', 'data health history item')
  requireString(item, 'createdAt', 'data health history item')
  return value as DataReliabilityHistoryItem
}

function assertDataReliabilityEventItem(value: unknown): DataReliabilityEventItem {
  const item = ensureRecord(value, 'data health event item')
  requireNumber(item, 'id', 'data health event item')
  requireString(item, 'symbol', 'data health event item')
  requireString(item, 'adapterId', 'data health event item')
  requireString(item, 'provider', 'data health event item')
  requireString(item, 'category', 'data health event item')
  requireString(item, 'eventType', 'data health event item')
  requireString(item, 'message', 'data health event item')
  requireString(item, 'error', 'data health event item')
  assertOptionalString(item, 'diagnosis', 'data health event item')
  assertOptionalString(item, 'status', 'data health event item')
  assertOptionalBoolean(item, 'healthy', 'data health event item')
  assertOptionalBoolean(item, 'fallbackUsed', 'data health event item')
  assertOptionalBoolean(item, 'upstreamHealthy', 'data health event item')
  assertOptionalBoolean(item, 'liveDataUsable', 'data health event item')
  assertOptionalNumber(item, 'latencyMs', 'data health event item')
  assertOptionalNumber(item, 'recordCount', 'data health event item')
  requireString(item, 'createdAt', 'data health event item')
  return value as DataReliabilityEventItem
}

function assertDataReliabilityExternalMonitorStatus(value: unknown): DataReliabilityExternalMonitorStatus {
  const status = ensureRecord(value, 'data health external monitor status')
  requireString(status, 'schema', 'data health external monitor status')
  if (status.schema !== 'data_reliability_external_monitor_status_v1') {
    throw new Error('Unexpected data reliability external monitor status response: schema mismatch')
  }
  requireBoolean(status, 'checked', 'data health external monitor status')
  requireBoolean(status, 'reported', 'data health external monitor status')
  requireString(status, 'status', 'data health external monitor status')
  requireString(status, 'sidecarFile', 'data health external monitor status')
  requireString(status, 'reportedAt', 'data health external monitor status')
  requireString(status, 'source', 'data health external monitor status')
  requireString(status, 'provider', 'data health external monitor status')
  requireString(status, 'monitorBackend', 'data health external monitor status')
  requireString(status, 'monitorStatus', 'data health external monitor status')
  requireString(status, 'freshnessStatus', 'data health external monitor status')
  requireString(status, 'retentionPolicyId', 'data health external monitor status')
  requireString(status, 'retentionStatus', 'data health external monitor status')
  assertOptionalNumber(status, 'retentionDays', 'data health external monitor status')
  requireString(status, 'retentionExpiresAt', 'data health external monitor status')
  requireNumber(status, 'outageCount', 'data health external monitor status')
  requireNumber(status, 'degradedSourceCount', 'data health external monitor status')
  requireNumber(status, 'staleSourceCount', 'data health external monitor status')
  assertOptionalNumber(status, 'latencyP95Ms', 'data health external monitor status')
  requireString(status, 'latestIncidentAt', 'data health external monitor status')
  requireString(status, 'searchIndex', 'data health external monitor status')
  requireBoolean(status, 'searchIndexReady', 'data health external monitor status')
  requireString(status, 'message', 'data health external monitor status')
  requireBoolean(status, 'deploymentReported', 'data health external monitor status')
  requireString(status, 'localEventTrail', 'data health external monitor status')
  assertStringArray(status.issues, 'data health external monitor status issues')
  return value as DataReliabilityExternalMonitorStatus
}

function assertDataReliabilitySnapshot(value: unknown): DataReliabilitySnapshot {
  const snapshot = ensureRecord(value, 'data health snapshot')
  requireString(snapshot, 'generatedAt', 'data health snapshot')
  assertDataReliabilitySummary(snapshot.summary)
  ensureArray(snapshot.adapters, 'data health snapshot adapters').forEach((adapter) =>
    assertDataReliabilityAdapter(adapter, 'data reliability snapshot adapter'),
  )
  assertDataReliabilityMatrix(snapshot.matrix)
  assertDataReliabilityConfig(snapshot.config)
  ensureArray(snapshot.history, 'data health snapshot history').forEach(assertDataReliabilityHistoryItem)
  if (snapshot.events !== undefined) {
    ensureArray(snapshot.events, 'data health snapshot events').forEach(assertDataReliabilityEventItem)
  }
  if (snapshot.externalMonitorStatus !== undefined && snapshot.externalMonitorStatus !== null) {
    assertDataReliabilityExternalMonitorStatus(snapshot.externalMonitorStatus)
  }
  return value as DataReliabilitySnapshot
}

function assertSymbolHealthResult(value: unknown): SymbolHealthResult {
  const result = ensureRecord(value, 'symbol health result')
  requireString(result, 'symbol', 'symbol health result')
  requireString(result, 'generatedAt', 'symbol health result')
  requireString(result, 'overallStatus', 'symbol health result')
  ensureArray(result.results, 'symbol health result rows').forEach((rowValue) => {
    const row = ensureRecord(rowValue, 'symbol health result row')
    requireString(row, 'category', 'symbol health result row')
    requireString(row, 'status', 'symbol health result row')
    requireBoolean(row, 'healthy', 'symbol health result row')
    requireString(row, 'provider', 'symbol health result row')
    requireString(row, 'adapterId', 'symbol health result row')
    requireNumber(row, 'latencyMs', 'symbol health result row')
    requireNumber(row, 'recordCount', 'symbol health result row')
    assertOptionalString(row, 'freshness', 'symbol health result row')
    requireString(row, 'error', 'symbol health result row')
    requireString(row, 'message', 'symbol health result row')
    requireString(row, 'diagnosis', 'symbol health result row')
    ensureArray(row.fallbackChain, 'symbol health result fallback chain')
  })
  return value as SymbolHealthResult
}

export function getDataReliabilitySnapshot() {
  return request<unknown>('/data-reliability/snapshot', { timeoutMs: 15000 }).then(assertDataReliabilitySnapshot)
}

export function getDataReliabilitySummary() {
  return request<unknown>('/data-reliability/summary', { timeoutMs: 15000 }).then(assertDataReliabilitySummary)
}

export function getDataReliabilityAdapters() {
  return request<unknown>('/data-reliability/adapters', { timeoutMs: 15000 }).then((items) =>
    ensureArray(items, 'data reliability adapters').map((item) => assertDataReliabilityAdapter(item, 'data reliability adapter')),
  )
}

export function checkDataReliabilityAdapters() {
  return request<unknown>('/data-reliability/adapters/check', { method: 'POST', timeoutMs: 45000 }).then((items) =>
    ensureArray(items, 'data reliability adapter check results').map((item) => assertDataReliabilityAdapter(item, 'data reliability adapter check result')),
  )
}

export function getDataReliabilityMatrix() {
  return request<unknown>('/data-reliability/matrix', { timeoutMs: 15000 }).then(assertDataReliabilityMatrix)
}

export function checkSymbolHealth(symbol: string) {
  return request<unknown>('/data-reliability/symbol-check', {
    method: 'POST',
    body: JSON.stringify({ symbol }),
    timeoutMs: 45000,
  }).then(assertSymbolHealthResult)
}

export function getDataReliabilityHistory() {
  return request<unknown>('/data-reliability/history').then((items) =>
    ensureArray(items, 'data reliability history').map(assertDataReliabilityHistoryItem),
  )
}

export function getDataReliabilityEvents() {
  return request<unknown>('/data-reliability/events').then((items) =>
    ensureArray(items, 'data reliability events').map(assertDataReliabilityEventItem),
  )
}
