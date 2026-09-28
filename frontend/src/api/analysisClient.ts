import { getAuditLog as getAuditLogFromAuditClient } from './auditClient'
import { request } from './httpClient'
import {
  AgentNode,
  AnalysisJob,
  AnalysisJobAttempt,
  AnalysisJobSummary,
  AnalysisRun,
  AnalysisRunSummary,
  BackendHealth,
  DebateArtifacts,
  FinalReportAsset,
  QuantEngineMode,
  StartupStatus,
  TokenUsageSummary,
} from '../types'

const ANALYSIS_JOB_DIAGNOSTIC_TIMEOUT_MS = 45000
const ANALYSIS_RUN_HISTORY_TIMEOUT_MS = 30000

export interface CreateAnalysisPayload {
  symbol: string
  task_type: string
  run_mode: 'FAST_MODE' | 'STANDARD_MODE' | 'DEEP_MODE'
  quant_engine_mode?: QuantEngineMode
  bottom_research_config?: Record<string, any>
  scenario_id: string
  user_constraints: {
    position_ratio?: number
    shares?: number
    cost_price: number
    max_drawdown: number
    allow_add: boolean
    allow_t0: boolean
  }
  config_profile_id: string
  portfolio_snapshot_id?: string
  research_loop_id?: string
  research_iteration_id?: string
}

export interface CreateAnalysisResponse {
  run_id: string
  status: 'CREATED'
  stream_url: string
}

export interface StartAnalysisResponse {
  run_id: string
  status: 'RUNNING' | 'QUEUED' | 'FAILED'
}

export function createAnalysisRun(payload: CreateAnalysisPayload) {
  return request<unknown>('/analysis/runs', {
    method: 'POST',
    body: JSON.stringify(payload),
    timeoutMs: 60000,
  }).then(assertCreateAnalysisResponse)
}

export function startAnalysisRun(runId: string, payload?: { operator?: string }) {
  return request<unknown>(`/analysis/runs/${runId}/start`, {
    method: 'POST',
    body: JSON.stringify(payload ?? {}),
  }).then(assertStartAnalysisResponse)
}

export function cancelAnalysisRun(runId: string, payload?: { operator?: string }) {
  return request<unknown>(`/analysis/runs/${runId}/cancel`, {
    method: 'POST',
    body: JSON.stringify(payload ?? {}),
  }).then(assertAnalysisRunJobActionResponse)
}

export function retryAnalysisRun(runId: string, payload?: { from_node_id?: string; reason?: string; operator?: string }) {
  return request<unknown>(`/analysis/runs/${runId}/retry`, {
    method: 'POST',
    body: JSON.stringify(payload ?? {}),
  }).then(assertStartAnalysisResponse)
}

export function getAnalysisRunJob(runId: string) {
  return request<unknown>(`/analysis/runs/${runId}/job`).then((job) => assertAnalysisJob(job, 'analysis run job'))
}

function analysisJobSearchParams(limit = 100, offset = 0, statuses: string[] = []) {
  const search = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  statuses.forEach((status) => {
    if (status) search.append('status', status)
  })
  return search
}

export function getAnalysisJobs(limit = 100, offset = 0, statuses: string[] = []) {
  const search = analysisJobSearchParams(limit, offset, statuses)
  return request<unknown>(`/analysis/jobs?${search.toString()}`, { timeoutMs: ANALYSIS_JOB_DIAGNOSTIC_TIMEOUT_MS })
    .then(assertAnalysisJobs)
}

export function getAnalysisJobSummary(limit = 100, offset = 0, statuses: string[] = []) {
  const search = analysisJobSearchParams(limit, offset, statuses)
  return request<unknown>(`/analysis/jobs/summary?${search.toString()}`, { timeoutMs: ANALYSIS_JOB_DIAGNOSTIC_TIMEOUT_MS })
    .then(assertAnalysisJobSummary)
}

export async function getAnalysisJobAttempts(params: { runId?: string; limit?: number; offset?: number; statuses?: string[] } = {}) {
  const searchParams = new URLSearchParams()
  searchParams.set('limit', String(params.limit ?? 100))
  searchParams.set('offset', String(params.offset ?? 0))
  if (params.runId) {
    searchParams.set('run_id', params.runId)
  }
  for (const status of params.statuses ?? []) {
    searchParams.append('status', status)
  }
  const attempts = await request<unknown>(`/analysis/jobs/attempts?${searchParams.toString()}`, { timeoutMs: ANALYSIS_JOB_DIAGNOSTIC_TIMEOUT_MS })
  return assertAnalysisJobAttempts(attempts)
}

export async function getAnalysisRun(runId: string) {
  const run = await request<unknown>(`/analysis/runs/${runId}`, { timeoutMs: 30000 })
  return assertAnalysisRun(run)
}

export async function getAnalysisRuns() {
  const runs = await request<unknown>('/analysis/runs', { timeoutMs: ANALYSIS_RUN_HISTORY_TIMEOUT_MS })
  if (!Array.isArray(runs)) {
    throw new Error('Unexpected analysis runs response')
  }
  return runs.map(assertAnalysisRunSummary)
}

export function getAnalysisNodes(runId: string) {
  return request<unknown>(`/analysis/runs/${runId}/nodes`).then(assertAgentNodes)
}

export function getNodeDetail(runId: string, nodeId: string) {
  return request<unknown>(`/analysis/runs/${runId}/nodes/${nodeId}`).then((node) => assertAgentNode(node, 'analysis node detail'))
}

export function getBackendHealth() {
  return request<unknown>('/health').then(assertBackendHealth)
}

export function getStartupStatus(options: { timeoutMs?: number } = {}) {
  return request<unknown>('/startup/status', { timeoutMs: options.timeoutMs }).then(assertStartupStatus)
}

export interface ProductionHealthMetric {
  total?: number
  succeeded?: number
  failed?: number
  skipped?: number
  successRate?: number | null
  errorRate?: number | null
  failureRate?: number | null
  fallbackRate?: number | null
  fallbackOrMock?: number
  unavailable?: number
  totalTokens?: number
  currentCount?: number
  windowCount?: number
  jobTotal?: number
  status?: string
  totalEvents?: number
  observedErrors?: number
  consumedPercent?: number | null
  remainingPercent?: number | null
  runIds?: string[]
  failureReasons?: Array<{ reason: string; count: number }>
  sampleFailures?: Array<{ runId?: string; node?: string; status?: string; reason?: string }>
}

export interface ProductionHealthWindow {
  window: string
  runSuccessRate: ProductionHealthMetric
  llmCallFailureRate: ProductionHealthMetric
  marketDataFallbackRate: ProductionHealthMetric
  signalOpsTickSuccessRate: ProductionHealthMetric
  staleJobs: ProductionHealthMetric
  errorBudget: ProductionHealthMetric
}

export interface ProductionHealthAlert {
  severity: string
  metric: string
  window: string
  message: string
}

export interface ProductionHealthTrend {
  baselineWindow?: string
  runSuccessRateDelta?: number | null
  llmFailureRateDelta?: number | null
  llmSuccessRateDelta?: number | null
  marketDataFallbackRateDelta?: number | null
  signalOpsTickSuccessRateDelta?: number | null
}

export interface ProductionHealth {
  status: string
  generatedAt: string
  externalCalls: boolean
  windows: Record<string, ProductionHealthWindow>
  trend?: ProductionHealthTrend
  longTrend?: ProductionHealthTrend
  alerts: ProductionHealthAlert[]
  errorBudget: ProductionHealthMetric
  sourceErrors?: Record<string, string>
}

export interface BackendMetrics {
  generatedAt: string
  productionHealth?: ProductionHealth
}

export function getBackendMetrics() {
  return request<unknown>('/metrics', { timeoutMs: 30000 }).then(assertBackendMetrics)
}

export interface ProductionAlertOutboxEvent {
  id: string
  severity: string
  metric: string
  window: string
  message: string
  created_at: string
  delivery_status: string
  channel: string
  external_delivery?: boolean
  external_provider?: string
  delivery_attempted_at?: string
  delivery_attempt_count?: number
  delivery_attempt_limit?: number
  delivery_error?: string
  alert_rule_policy_schema?: string
  alert_rule_policy_status?: string
  alert_rule_source?: string
  alert_rule_provider?: string
  alert_rule_id?: string
  alert_routing_key?: string
  alert_escalation_target?: string
  alert_dedupe_window_seconds?: number
}

export interface ProductionAlertRulePolicy {
  schema?: string
  policy_id?: string
  checked?: boolean
  configured?: boolean
  status?: string
  source?: string
  provider?: string
  sidecar_file?: string
  rule_count?: number
  message?: string
  issues?: string[]
  provider_acceptance?: {
    schema?: string
    checked?: boolean
    configured?: boolean
    reported?: boolean
    status?: string
    sidecar_file?: string
    source?: string
    provider?: string
    policy_id?: string
    provider_policy_id?: string
    rules_accepted?: number
    rules_total?: number
    accepted_rule_ids?: string[]
    missing_rule_ids?: string[]
    policy_id_matches?: boolean
    rule_count_matches?: boolean
    accepted_rule_ids_match?: boolean
    matches_policy?: boolean
    last_synced_at?: string
    routing_key?: string
    message?: string
    issues?: string[]
  }
  rules?: Array<{
    id?: string
    severity?: string
    metric?: string
    routing_key?: string
    escalation_target?: string
    dedupe_window_seconds?: number
  }>
}

export interface ProductionAlertChannelStatus {
  generated_at: string
  enabled: boolean
  channel: string
  external_delivery_enabled: boolean
  external_aggregation_ready?: boolean
  export_endpoint?: string
  export_schema?: string
  external_provider?: string
  external_delivery_status?: string
  external_delivery_attempt_limit?: number
  external_delivery_retry_backoff_seconds?: number
  alert_rule_policy?: ProductionAlertRulePolicy
  outbox_file: string
  queue_size: number
  last_event_at: string
  counts_by_severity: Record<string, number>
  retention_policy?: {
    mode?: string
    max_events?: number
    time_based_retention_enabled?: boolean
    max_age_days?: number | null
    prune_on_read_or_write?: boolean
  }
  redaction_policy?: {
    headers_logged?: boolean
    webhook_url_returned?: boolean
    bodies_logged?: boolean
    secret_patterns?: string[]
  }
  handoff_status?: {
    schema?: string
    configured?: boolean
    status?: string
    reason?: string
    handoff_destination?: string
    handoff_dir?: string
    bundle_schema?: string
    manifest_schema?: string
    requires_sanitized_export?: boolean
    writable?: boolean
    will_create_on_handoff?: boolean
    inventory?: {
      schema?: string
      checked?: boolean
      status?: string
      manifest_count?: number
      verified_count?: number
      missing_bundle_count?: number
      checksum_mismatch_count?: number
      invalid_manifest_count?: number
      latest_handoff_id?: string
      latest_handed_off_at?: string
      latest_bundle_checksum?: string
      issues?: string[]
    }
    shipper_status?: {
      schema?: string
      checked?: boolean
      reported?: boolean
      status?: string
      sidecar_file?: string
      reported_at?: string
      source?: string
      provider?: string
      remote_destination?: string
      remote_object_key?: string
      retention_policy_id?: string
      retention_status?: string
      custody_status?: string
      kms_key_ref?: string
      search_index?: string
      search_index_ready?: boolean
      last_handoff_id?: string
      last_bundle_checksum?: string
      matches_latest_inventory?: boolean
      deployment_reported?: boolean
      message?: string
      issues?: string[]
    }
  }
  latest: ProductionAlertOutboxEvent[]
}

export interface ProductionAlertExportBundle {
  generated_at: string
  schema: string
  channel: string
  source_channel: string
  external_delivery_enabled: boolean
  external_aggregation_ready: boolean
  export_endpoint: string
  export_schema: string
  external_provider?: string
  external_delivery_status?: string
  external_delivery_attempt_limit?: number
  external_delivery_retry_backoff_seconds?: number
  alert_rule_policy?: ProductionAlertRulePolicy
  outbox_file: string
  event_count: number
  total_event_count: number
  exported_count: number
  checksum: string
  retention_policy?: ProductionAlertChannelStatus['retention_policy']
  redaction_policy?: ProductionAlertChannelStatus['redaction_policy']
  events: ProductionAlertOutboxEvent[]
}

export interface ProductionAlertExportHandoff {
  generated_at: string
  schema: string
  status: string
  reason?: string
  handoff_destination: string
  handoff_requires_export_checksum?: boolean
  export_schema: string
  bundle_checksum: string
  event_count: number
  total_event_count: number
  exported_count: number
  external_delivery_enabled: boolean
  external_provider?: string
  external_delivery_status?: string
  external_aggregation_ready: boolean
  alert_rule_policy?: ProductionAlertRulePolicy
  handoff_id: string
  handoff_dir: string
  bundle_file: string
  manifest_file: string
  manifest?: {
    schema?: string
    handoff_id?: string
    status?: string
    handed_off_at?: string
    handoff_destination?: string
    bundle_file?: string
    manifest_file?: string
    bundle_checksum?: string
    export_schema?: string
    event_count?: number
    total_event_count?: number
    exported_count?: number
    external_delivery_enabled?: boolean
    external_provider?: string
    external_delivery_status?: string
    alert_rule_policy?: ProductionAlertRulePolicy
    retention_policy?: Record<string, unknown>
    redaction_policy?: ProductionAlertChannelStatus['redaction_policy']
    external_aggregation_ready?: boolean
  }
}

export interface ProductionAlertDispatchResult {
  generated_at: string
  channel: string
  external_delivery_enabled: boolean
  external_provider?: string
  external_delivery_status?: string
  external_delivery_attempt_limit?: number
  external_delivery_retry_backoff_seconds?: number
  alert_rule_policy?: ProductionAlertRulePolicy
  dispatched: number
  deduplicated: number
  production_health_status: string
  outbox_file: string
  events: ProductionAlertOutboxEvent[]
  status: ProductionAlertChannelStatus
}

export interface OpsLogEvent {
  id: string
  created_at: string
  event_type: string
  level: string
  source: string
  request_id: string
  method: string
  path: string
  status_code: number
  duration_ms: number
  client: string
  message: string
  context: Record<string, unknown>
}

export interface OpsLogStatus {
  generated_at: string
  enabled: boolean
  channel: string
  external_delivery_enabled: boolean
  external_aggregation_ready?: boolean
  query_endpoint?: string
  query_schema?: string
  export_endpoint?: string
  export_schema?: string
  log_file: string
  event_count: number
  counts_by_level: Record<string, number>
  counts_by_type: Record<string, number>
  retention_policy?: {
    mode?: string
    max_events?: number
    time_based_retention_enabled?: boolean
    max_age_days?: number | null
    prune_on_read_or_write?: boolean
  }
  redaction_policy?: {
    headers_logged?: boolean
    query_strings_logged?: boolean
    bodies_logged?: boolean
    secret_patterns?: string[]
  }
  handoff_status?: {
    schema?: string
    configured?: boolean
    status?: string
    reason?: string
    handoff_destination?: string
    handoff_dir?: string
    bundle_schema?: string
    manifest_schema?: string
    requires_sanitized_export?: boolean
    writable?: boolean
    will_create_on_handoff?: boolean
    inventory?: {
      schema?: string
      checked?: boolean
      status?: string
      manifest_count?: number
      verified_count?: number
      missing_bundle_count?: number
      checksum_mismatch_count?: number
      invalid_manifest_count?: number
      latest_handoff_id?: string
      latest_handed_off_at?: string
      latest_bundle_checksum?: string
      issues?: string[]
    }
    shipper_status?: {
      schema?: string
      checked?: boolean
      reported?: boolean
      status?: string
      sidecar_file?: string
      reported_at?: string
      source?: string
      provider?: string
      remote_destination?: string
      remote_object_key?: string
      retention_policy_id?: string
      retention_status?: string
      custody_status?: string
      kms_key_ref?: string
      search_index?: string
      search_index_ready?: boolean
      last_handoff_id?: string
      last_bundle_checksum?: string
      matches_latest_inventory?: boolean
      deployment_reported?: boolean
      message?: string
      issues?: string[]
    }
  }
  latest: OpsLogEvent[]
}

export interface OpsLogQueryResult {
  generated_at: string
  schema: string
  channel: string
  source_channel: string
  external_delivery_enabled: boolean
  external_aggregation_ready: boolean
  log_file: string
  event_count: number
  matched_count: number
  returned_count: number
  limit: number
  level_filter: string
  event_type_filter: string
  source_filter: string
  text_filter: string
  since: string
  retention_policy?: OpsLogStatus['retention_policy']
  redaction_policy?: OpsLogStatus['redaction_policy']
  events: OpsLogEvent[]
}

export interface OpsLogExportBundle {
  generated_at: string
  schema: string
  channel: string
  source_channel: string
  external_delivery_enabled: boolean
  external_aggregation_ready: boolean
  log_file: string
  event_count: number
  exported_count: number
  level_filter: string
  since: string
  checksum: string
  retention_policy?: OpsLogStatus['retention_policy']
  redaction_policy?: OpsLogStatus['redaction_policy']
  events: OpsLogEvent[]
}

export interface OpsLogExportHandoff {
  generated_at: string
  schema: string
  status: string
  reason?: string
  handoff_destination: string
  handoff_requires_export_checksum?: boolean
  export_schema: string
  bundle_checksum: string
  event_count: number
  exported_count: number
  level_filter: string
  since: string
  external_delivery_enabled: boolean
  external_aggregation_ready: boolean
  handoff_id: string
  handoff_dir: string
  bundle_file: string
  manifest_file: string
  manifest?: {
    schema?: string
    handoff_id?: string
    status?: string
    handed_off_at?: string
    handoff_destination?: string
    bundle_file?: string
    manifest_file?: string
    bundle_checksum?: string
    export_schema?: string
    event_count?: number
    exported_count?: number
    level_filter?: string
    since?: string
    retention_policy?: Record<string, unknown>
    redaction_policy?: OpsLogStatus['redaction_policy']
    external_delivery_enabled?: boolean
    external_aggregation_ready?: boolean
  }
}

export function getProductionAlertStatus(limit = 20) {
  return request<unknown>(`/ops/alerts/status?limit=${limit}`, { timeoutMs: 30000 }).then(assertProductionAlertChannelStatus)
}

export function getProductionAlertExport(limit = 100) {
  return request<unknown>(`/ops/alerts/export?limit=${limit}`, { timeoutMs: 30000 }).then(assertProductionAlertExportBundle)
}

export function handoffProductionAlertExport(limit = 100) {
  return request<unknown>(`/ops/alerts/export/handoff?limit=${limit}`, {
    method: 'POST',
    body: JSON.stringify({}),
    timeoutMs: 30000,
  }).then(assertProductionAlertExportHandoff)
}

export function dispatchProductionAlerts() {
  return request<unknown>('/ops/alerts/dispatch', {
    method: 'POST',
    body: JSON.stringify({}),
    timeoutMs: 30000,
  }).then(assertProductionAlertDispatchResult)
}

export function getOpsLogStatus(limit = 20, level = '') {
  const search = new URLSearchParams({ limit: String(limit) })
  if (level) search.set('level', level)
  return request<unknown>(`/ops/logs/status?${search.toString()}`, { timeoutMs: 30000 }).then(assertOpsLogStatus)
}

export function queryOpsLogs(params: { limit?: number; level?: string; eventType?: string; source?: string; text?: string; since?: string } = {}) {
  const search = new URLSearchParams({ limit: String(params.limit ?? 20) })
  if (params.level) search.set('level', params.level)
  if (params.eventType) search.set('event_type', params.eventType)
  if (params.source) search.set('source', params.source)
  if (params.text) search.set('text', params.text)
  if (params.since) search.set('since', params.since)
  return request<unknown>(`/ops/logs/query?${search.toString()}`, { timeoutMs: 30000 }).then(assertOpsLogQueryResult)
}

export function getOpsLogExport(limit = 100, level = '', since = '') {
  const search = new URLSearchParams({ limit: String(limit) })
  if (level) search.set('level', level)
  if (since) search.set('since', since)
  return request<unknown>(`/ops/logs/export?${search.toString()}`, { timeoutMs: 30000 }).then(assertOpsLogExportBundle)
}

export function handoffOpsLogExport(limit = 100, level = '', since = '') {
  const search = new URLSearchParams({ limit: String(limit) })
  if (level) search.set('level', level)
  if (since) search.set('since', since)
  return request<unknown>(`/ops/logs/export/handoff?${search.toString()}`, {
    method: 'POST',
    body: JSON.stringify({}),
    timeoutMs: 30000,
  }).then(assertOpsLogExportHandoff)
}

export function getAuditLog(runId: string) {
  return getAuditLogFromAuditClient(runId)
}

export function getAnalysisDebate(runId: string) {
  return request<unknown>(`/analysis/runs/${runId}/debate`).then(assertAnalysisDebateResponse)
}

export function getAnalysisRunReport(runId: string) {
  return request<unknown>(`/analysis/runs/${runId}/report`).then(assertFinalReportAsset)
}

export function getFinalReports(params?: { symbol?: string; limit?: number }) {
  const search = new URLSearchParams()
  if (params?.symbol) search.set('symbol', params.symbol)
  if (params?.limit) search.set('limit', String(params.limit))
  const suffix = search.toString() ? `?${search.toString()}` : ''
  return request<unknown>(`/analysis/reports${suffix}`).then(assertFinalReportAssets)
}

export function deleteAnalysisRun(runId: string) {
  return request<unknown>(`/analysis/runs/${runId}`, {
    method: 'DELETE',
  }).then(assertDeleteAnalysisRunResponse)
}

export interface RunCompareResult {
  leftRun: AnalysisRunSummary
  rightRun: AnalysisRunSummary
  generatedAt: string
  changedCount: number
  summary: string[]
  diffs: Array<{
    key: string
    label: string
    left: unknown
    right: unknown
    changed: boolean
    impact: string
  }>
}

export async function compareAnalysisRuns(left: string, right: string) {
  const params = new URLSearchParams({ left, right })
  const result = await request<unknown>(`/analysis/runs/compare?${params.toString()}`, {
    timeoutMs: 30000,
  })
  return assertRunCompareResult(result)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}

function hasTextField(record: Record<string, unknown>, field: string) {
  return typeof record[field] === 'string' && String(record[field]).trim().length > 0
}

function hasStringField(record: Record<string, unknown>, field: string) {
  return typeof record[field] === 'string'
}

function hasFiniteNumberField(record: Record<string, unknown>, field: string) {
  return typeof record[field] === 'number' && Number.isFinite(record[field])
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string')
}

function textValue(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function assertPaperTradingAction(action: unknown, label: string) {
  const normalized = textValue(action).toUpperCase()
  if (normalized && !normalized.startsWith('SIM_')) {
    throw new Error(`Unexpected analysis run response: paperTrading ${label} action must use SIM_*`)
  }
}

function assertPaperTradingNamespace(namespace: unknown, label: string) {
  const normalized = textValue(namespace)
  if (normalized && normalized !== 'SIM_*') {
    throw new Error(`Unexpected analysis run response: paperTrading ${label} order namespace must be SIM_*`)
  }
}

function assertPaperTradingRootBoundary(paperTrading: Record<string, unknown>) {
  const simulationFlags = [paperTrading.simulation_only, paperTrading.simulationOnly].filter((value) => typeof value === 'boolean')
  const realTradeFlags = [paperTrading.is_real_trade, paperTrading.isRealTrade].filter((value) => typeof value === 'boolean')
  if (!simulationFlags.length || simulationFlags.some((value) => value !== true)) {
    throw new Error('Unexpected analysis run response: paperTrading must declare simulation_only=true')
  }
  if (!realTradeFlags.length || realTradeFlags.some((value) => value !== false)) {
    throw new Error('Unexpected analysis run response: paperTrading must declare is_real_trade=false')
  }
  const namespace = textValue(paperTrading.allowed_order_namespace ?? paperTrading.orderNamespace ?? paperTrading.order_namespace)
  if (namespace !== 'SIM_*') {
    throw new Error('Unexpected analysis run response: paperTrading root order namespace must be SIM_*')
  }
}

function assertPaperTradingBoundary(paperTrading: Record<string, unknown>) {
  assertPaperTradingRootBoundary(paperTrading)
  if (paperTrading.simulation_only === false || paperTrading.simulationOnly === false) {
    throw new Error('Unexpected analysis run response: paperTrading simulation boundary forbids simulation_only=false')
  }
  if (paperTrading.is_real_trade === true || paperTrading.isRealTrade === true) {
    throw new Error('Unexpected analysis run response: paperTrading simulation boundary forbids is_real_trade=true')
  }

  assertPaperTradingNamespace(
    paperTrading.allowed_order_namespace ?? paperTrading.orderNamespace ?? paperTrading.order_namespace,
    'root',
  )
  assertPaperTradingAction(
    paperTrading.latest_action ?? paperTrading.paper_action ?? paperTrading.action,
    'root',
  )

  const simulationActions = paperTrading.simulationActions ?? paperTrading.simulation_actions
  if (Array.isArray(simulationActions)) {
    simulationActions.forEach((entry, index) => {
      if (!isRecord(entry)) return
      assertPaperTradingNamespace(
        entry.allowed_order_namespace ?? entry.orderNamespace ?? entry.order_namespace,
        `simulationActions ${index}`,
      )
      assertPaperTradingAction(entry.latest_action ?? entry.paper_action ?? entry.action, `simulationActions ${index}`)
    })
  }
}

function isStrongEvidenceValue(value: unknown) {
  const normalized = String(value || '').toUpperCase()
  return (
    normalized === 'HIGH'
    || normalized === 'RESEARCH_GRADE'
    || normalized === 'PRIMARY_EVIDENCE_READY'
    || normalized.includes('STRONG')
    || normalized.includes('PRIMARY')
  )
}

function assertPortfolioRunBoundary(portfolio: Record<string, unknown>) {
  if (
    !hasStringField(portfolio, 'evidenceUsage')
    || !hasStringField(portfolio, 'evidenceStrength')
    || typeof portfolio.simulationOnly !== 'boolean'
    || typeof portfolio.isRealTrade !== 'boolean'
    || typeof portfolio.strongConclusionAllowed !== 'boolean'
  ) {
    throw new Error('Unexpected analysis run response: portfolio must declare supporting-only simulation boundary')
  }

  if (
    portfolio.evidenceUsage !== 'supporting_only'
    || portfolio.simulationOnly !== true
    || portfolio.isRealTrade !== false
    || portfolio.strongConclusionAllowed !== false
    || isStrongEvidenceValue(portfolio.evidenceUsage)
    || isStrongEvidenceValue(portfolio.evidenceStrength)
  ) {
    throw new Error('Unexpected analysis run response: portfolio evidence must stay supporting-only and simulation-only')
  }

  if (portfolio.provenance !== undefined) {
    if (!isRecord(portfolio.provenance)) {
      throw new Error('Unexpected analysis run response: portfolio provenance must be an object')
    }
    if (
      portfolio.provenance.evidenceUsage !== 'supporting_only'
      || portfolio.provenance.simulationOnly !== true
      || portfolio.provenance.isRealTrade !== false
      || portfolio.provenance.strongConclusionAllowed !== false
      || isStrongEvidenceValue(portfolio.provenance.evidenceUsage)
      || isStrongEvidenceValue(portfolio.provenance.evidenceStrength)
    ) {
      throw new Error('Unexpected analysis run response: portfolio provenance must stay supporting-only and simulation-only')
    }
  }
}

function assertAgentNodeBoundary(node: Record<string, unknown>, label: string) {
  if (
    !hasStringField(node, 'evidenceUsage')
    || !hasStringField(node, 'evidenceStrength')
    || typeof node.simulationOnly !== 'boolean'
    || typeof node.isRealTrade !== 'boolean'
    || typeof node.strongConclusionAllowed !== 'boolean'
  ) {
    throw new Error(`Unexpected ${label} response: agent node must declare simulation-only evidence boundary`)
  }

  if (
    node.evidenceUsage !== 'simulation_only'
    || node.simulationOnly !== true
    || node.isRealTrade !== false
    || node.strongConclusionAllowed !== false
    || isStrongEvidenceValue(node.evidenceUsage)
    || isStrongEvidenceValue(node.evidenceStrength)
  ) {
    throw new Error(`Unexpected ${label} response: agent node evidence must stay simulation-only and non-strong`)
  }

  const rawJson = node.rawJson
  if (isRecord(rawJson)) {
    if (rawJson.simulationOnly !== undefined && rawJson.simulationOnly !== true) {
      throw new Error(`Unexpected ${label} response: agent node rawJson must keep simulationOnly=true`)
    }
    if (rawJson.isRealTrade !== undefined && rawJson.isRealTrade !== false) {
      throw new Error(`Unexpected ${label} response: agent node rawJson must keep isRealTrade=false`)
    }
    if (rawJson.strongConclusionAllowed !== undefined && rawJson.strongConclusionAllowed !== false) {
      throw new Error(`Unexpected ${label} response: agent node rawJson must keep strongConclusionAllowed=false`)
    }
    if (rawJson.allowTradeAction === true) {
      throw new Error(`Unexpected ${label} response: agent node rawJson must not allow direct trade actions`)
    }
  }
}

function assertReadOnlyQuantCorePayload(payload: Record<string, unknown>, label: string) {
  if (payload.actionBoundary !== undefined && payload.actionBoundary !== 'READ_ONLY_NO_PERMISSION_CHANGE') {
    throw new Error(`Unexpected analysis run response: ${label} actionBoundary must be READ_ONLY_NO_PERMISSION_CHANGE`)
  }
  if (payload.simulation_only !== undefined && payload.simulation_only !== true) {
    throw new Error(`Unexpected analysis run response: ${label} must keep simulation_only=true`)
  }
  if (payload.is_real_trade !== undefined && payload.is_real_trade !== false) {
    throw new Error(`Unexpected analysis run response: ${label} must keep is_real_trade=false`)
  }
  if (payload.strongConclusionAllowed !== undefined && payload.strongConclusionAllowed !== false) {
    throw new Error(`Unexpected analysis run response: ${label} must keep strongConclusionAllowed=false`)
  }
}

function assertQuantCoreBoundary(quantCore: Record<string, unknown>) {
  if (
    !hasStringField(quantCore, 'actionBoundary')
    || !hasStringField(quantCore, 'evidenceUsage')
    || !hasStringField(quantCore, 'evidenceStrength')
    || typeof quantCore.simulation_only !== 'boolean'
    || typeof quantCore.is_real_trade !== 'boolean'
    || typeof quantCore.strongConclusionAllowed !== 'boolean'
  ) {
    throw new Error('Unexpected analysis run response: quantCore must declare read-only simulation boundary')
  }

  if (
    quantCore.actionBoundary !== 'READ_ONLY_NO_PERMISSION_CHANGE'
    || quantCore.evidenceUsage !== 'simulation_only'
    || quantCore.simulation_only !== true
    || quantCore.is_real_trade !== false
    || quantCore.strongConclusionAllowed !== false
    || isStrongEvidenceValue(quantCore.evidenceUsage)
    || isStrongEvidenceValue(quantCore.evidenceStrength)
  ) {
    throw new Error('Unexpected analysis run response: quantCore evidence must stay read-only, simulation-only, and non-strong')
  }

  if (isRecord(quantCore.provenance)) {
    assertReadOnlyQuantCorePayload(quantCore.provenance, 'quantCore provenance')
    if (
      quantCore.provenance.evidenceUsage !== undefined
      && quantCore.provenance.evidenceUsage !== 'simulation_only'
    ) {
      throw new Error('Unexpected analysis run response: quantCore provenance evidenceUsage must be simulation_only')
    }
    if (isStrongEvidenceValue(quantCore.provenance.evidenceStrength)) {
      throw new Error('Unexpected analysis run response: quantCore provenance evidence must stay non-strong')
    }
  }
  if (isRecord(quantCore.coreInterpretation)) {
    assertReadOnlyQuantCorePayload(quantCore.coreInterpretation, 'quantCore coreInterpretation')
  }
}

function assertSimulationBoundaryPayload(payload: Record<string, unknown>, label: string) {
  if (payload.simulation_only === false || payload.simulationOnly === false) {
    throw new Error(`Unexpected analysis run response: ${label} simulation boundary forbids simulation_only=false`)
  }
  if (payload.is_real_trade === true || payload.isRealTrade === true) {
    throw new Error(`Unexpected analysis run response: ${label} simulation boundary forbids is_real_trade=true`)
  }

  const namespace = textValue(payload.allowed_order_namespace ?? payload.orderNamespace ?? payload.order_namespace)
  if (namespace && namespace !== 'SIM_*') {
    throw new Error(`Unexpected analysis run response: ${label} order namespace must be SIM_*`)
  }

  const action = textValue(payload.latest_action ?? payload.paper_action ?? payload.action).toUpperCase()
  if (action && !action.startsWith('SIM_')) {
    throw new Error(`Unexpected analysis run response: ${label} action must use SIM_*`)
  }
}

function assertBackendHealth(value: unknown): BackendHealth {
  if (!isRecord(value)) {
    throw new Error('Unexpected backend health response')
  }
  const missingFields: string[] = [
    ...(['status', 'version', 'mode', 'lastCheck'] as const).filter((field) => !hasTextField(value, field)),
    ...(['latency'] as const).filter((field) => !hasFiniteNumberField(value, field)),
  ]
  if (typeof value.tradingEnabled !== 'boolean') missingFields.push('tradingEnabled')
  if (typeof value.autoOrderEnabled !== 'boolean') missingFields.push('autoOrderEnabled')
  if (missingFields.length > 0) {
    throw new Error(`Unexpected backend health response: missing ${missingFields.join(', ')}`)
  }
  if (!['ok', 'error'].includes(String(value.status))) {
    throw new Error('Unexpected backend health response: unsupported status')
  }
  if (!['mock', 'api'].includes(String(value.mode))) {
    throw new Error('Unexpected backend health response: unsupported mode')
  }
  return value as unknown as BackendHealth
}

function assertStartupStatus(value: unknown): StartupStatus {
  if (!isRecord(value)) {
    throw new Error('Unexpected startup status response')
  }
  const missingFields: string[] = ['phase'].filter((field) => !hasTextField(value, field))
  if (typeof value.coreReady !== 'boolean') missingFields.push('coreReady')
  if (typeof value.ready !== 'boolean') missingFields.push('ready')
  if (!isStringArray(value.degradedComponents)) missingFields.push('degradedComponents')
  if (!Array.isArray(value.components)) missingFields.push('components')
  if (missingFields.length > 0) {
    throw new Error(`Unexpected startup status response: missing ${missingFields.join(', ')}`)
  }
  const components = value.components as unknown[]
  for (const [index, component] of components.entries()) {
    assertStartupComponentStatus(component, index)
  }
  return value as unknown as StartupStatus
}

function assertStartupComponentStatus(value: unknown, index: number) {
  if (!isRecord(value)) {
    throw new Error(`Unexpected startup component response: item ${index} must be an object`)
  }
  const missingFields: string[] = ['name', 'tier', 'status'].filter((field) => !hasTextField(value, field))
  if (value.required !== undefined && typeof value.required !== 'boolean') missingFields.push('required')
  if (value.elapsedMs !== undefined && !hasFiniteNumberField(value, 'elapsedMs')) missingFields.push('elapsedMs')
  if (value.details !== undefined && !isRecord(value.details)) missingFields.push('details')
  if (missingFields.length > 0) {
    throw new Error(`Unexpected startup component response: item ${index} missing ${missingFields.join(', ')}`)
  }
}

function assertBackendMetrics(value: unknown): BackendMetrics {
  if (!isRecord(value)) {
    throw new Error('Unexpected backend metrics response')
  }
  if (!hasTextField(value, 'generatedAt')) {
    throw new Error('Unexpected backend metrics response: missing generatedAt')
  }
  if (value.productionHealth !== undefined) {
    assertProductionHealth(value.productionHealth)
  }
  return value as unknown as BackendMetrics
}

function assertProductionHealth(value: unknown) {
  if (!isRecord(value)) {
    throw new Error('Unexpected production health response')
  }
  const missingFields: string[] = ['status', 'generatedAt'].filter((field) => !hasTextField(value, field))
  if (typeof value.externalCalls !== 'boolean') missingFields.push('externalCalls')
  if (!isRecord(value.windows)) missingFields.push('windows')
  if (!Array.isArray(value.alerts)) missingFields.push('alerts')
  if (!isRecord(value.errorBudget)) missingFields.push('errorBudget')
  if (missingFields.length > 0) {
    throw new Error(`Unexpected production health response: missing ${missingFields.join(', ')}`)
  }
  const windows = value.windows as Record<string, unknown>
  for (const [key, window] of Object.entries(windows)) {
    assertProductionHealthWindow(window, key)
  }
  const alerts = value.alerts as unknown[]
  for (const [index, alert] of alerts.entries()) {
    assertProductionHealthAlert(alert, index)
  }
  assertProductionHealthMetric(value.errorBudget, 'production health error budget')
  if (value.trend !== undefined) assertProductionHealthTrend(value.trend, 'production health trend')
  if (value.longTrend !== undefined) assertProductionHealthTrend(value.longTrend, 'production health long trend')
  if (value.sourceErrors !== undefined && !isRecord(value.sourceErrors)) {
    throw new Error('Unexpected production health response: sourceErrors must be an object')
  }
}

function assertProductionHealthWindow(value: unknown, key: string) {
  if (!isRecord(value)) {
    throw new Error(`Unexpected production health window response: ${key} must be an object`)
  }
  if (!hasTextField(value, 'window')) {
    throw new Error(`Unexpected production health window response: ${key} missing window`)
  }
  const metricFields = [
    'runSuccessRate',
    'llmCallFailureRate',
    'marketDataFallbackRate',
    'signalOpsTickSuccessRate',
    'staleJobs',
    'errorBudget',
  ]
  metricFields.forEach((field) => assertProductionHealthMetric(value[field], `production health ${key}.${field}`))
}

function assertProductionHealthMetric(value: unknown, label: string) {
  if (!isRecord(value)) {
    throw new Error(`Unexpected ${label} response`)
  }
  for (const [field, fieldValue] of Object.entries(value)) {
    if (fieldValue === null || fieldValue === undefined) continue
    if (field === 'status') {
      if (typeof fieldValue !== 'string') {
        throw new Error(`Unexpected ${label} response: ${field} must be a string`)
      }
      continue
    }
    if (field === 'failureReasons' || field === 'sampleFailures') {
      if (!Array.isArray(fieldValue) || fieldValue.some((item) => !isRecord(item))) {
        throw new Error(`Unexpected ${label} response: ${field} must be an object array`)
      }
      continue
    }
    if (field === 'runIds') {
      if (!Array.isArray(fieldValue) || fieldValue.some((item) => typeof item !== 'string')) {
        throw new Error(`Unexpected ${label} response: runIds must be a string array`)
      }
      continue
    }
    if (typeof fieldValue !== 'number' || !Number.isFinite(fieldValue)) {
      throw new Error(`Unexpected ${label} response: ${field} must be numeric`)
    }
  }
}

function assertProductionHealthAlert(value: unknown, index: number) {
  if (!isRecord(value)) {
    throw new Error(`Unexpected production health alert response: item ${index} must be an object`)
  }
  const missingFields = ['severity', 'metric', 'window', 'message'].filter((field) => !hasTextField(value, field))
  if (missingFields.length > 0) {
    throw new Error(`Unexpected production health alert response: item ${index} missing ${missingFields.join(', ')}`)
  }
}

function assertProductionHealthTrend(value: unknown, label: string) {
  if (!isRecord(value)) {
    throw new Error(`Unexpected ${label} response`)
  }
  for (const [field, fieldValue] of Object.entries(value)) {
    if (fieldValue === null || fieldValue === undefined) continue
    if (field === 'baselineWindow') {
      if (typeof fieldValue !== 'string') {
        throw new Error(`Unexpected ${label} response: baselineWindow must be a string`)
      }
      continue
    }
    if (typeof fieldValue !== 'number' || !Number.isFinite(fieldValue)) {
      throw new Error(`Unexpected ${label} response: ${field} must be numeric`)
    }
  }
}

function assertOptionalRecordFields(value: Record<string, unknown>, fields: string[], label: string, missingFields: string[]) {
  for (const field of fields) {
    if (value[field] !== undefined && !isRecord(value[field])) {
      missingFields.push(`${label}.${field}`)
    }
  }
}

function assertNumberRecord(value: unknown, label: string) {
  if (!isRecord(value)) {
    throw new Error(`Unexpected ${label} response: must be an object`)
  }
  for (const [field, fieldValue] of Object.entries(value)) {
    if (typeof fieldValue !== 'number' || !Number.isFinite(fieldValue)) {
      throw new Error(`Unexpected ${label} response: ${field} must be numeric`)
    }
  }
}

function assertProductionAlertEvent(value: unknown, label: string): ProductionAlertOutboxEvent {
  if (!isRecord(value)) {
    throw new Error(`Unexpected ${label} response`)
  }
  const missingFields = ['id', 'severity', 'metric', 'window', 'message', 'created_at', 'delivery_status', 'channel']
    .filter((field) => !hasTextField(value, field))
  if (value.external_delivery !== undefined && typeof value.external_delivery !== 'boolean') missingFields.push('external_delivery')
  for (const field of ['delivery_attempt_count', 'delivery_attempt_limit', 'alert_dedupe_window_seconds']) {
    if (value[field] !== undefined && !hasFiniteNumberField(value, field)) missingFields.push(field)
  }
  if (missingFields.length > 0) {
    throw new Error(`Unexpected ${label} response: missing ${missingFields.join(', ')}`)
  }
  return value as unknown as ProductionAlertOutboxEvent
}

function assertProductionAlertEvents(value: unknown, label: string): ProductionAlertOutboxEvent[] {
  if (!Array.isArray(value)) {
    throw new Error(`Unexpected ${label} response: events must be an array`)
  }
  return value.map((event, index) => assertProductionAlertEvent(event, `${label} event ${index}`))
}

function assertProductionAlertChannelStatus(value: unknown): ProductionAlertChannelStatus {
  if (!isRecord(value)) {
    throw new Error('Unexpected production alert channel status response')
  }
  const missingFields: string[] = [
    ...(['generated_at', 'channel', 'outbox_file'] as const).filter((field) => !hasTextField(value, field)),
    ...(['last_event_at'] as const).filter((field) => !hasStringField(value, field)),
    ...(['queue_size'] as const).filter((field) => !hasFiniteNumberField(value, field)),
  ]
  if (typeof value.enabled !== 'boolean') missingFields.push('enabled')
  if (typeof value.external_delivery_enabled !== 'boolean') missingFields.push('external_delivery_enabled')
  if (value.external_aggregation_ready !== undefined && typeof value.external_aggregation_ready !== 'boolean') missingFields.push('external_aggregation_ready')
  if (!isRecord(value.counts_by_severity)) missingFields.push('counts_by_severity')
  assertOptionalRecordFields(value, ['alert_rule_policy', 'retention_policy', 'redaction_policy', 'handoff_status'], 'production alert channel status', missingFields)
  if (missingFields.length > 0) {
    throw new Error(`Unexpected production alert channel status response: missing ${missingFields.join(', ')}`)
  }
  assertNumberRecord(value.counts_by_severity, 'production alert counts_by_severity')
  assertProductionAlertEvents(value.latest, 'production alert latest')
  return value as unknown as ProductionAlertChannelStatus
}

function assertProductionAlertExportBundle(value: unknown): ProductionAlertExportBundle {
  if (!isRecord(value)) {
    throw new Error('Unexpected production alert export response')
  }
  const missingFields: string[] = [
    ...(['generated_at', 'schema', 'channel', 'source_channel', 'export_endpoint', 'export_schema', 'outbox_file', 'checksum'] as const)
      .filter((field) => !hasTextField(value, field)),
    ...(['event_count', 'total_event_count', 'exported_count'] as const).filter((field) => !hasFiniteNumberField(value, field)),
  ]
  if (typeof value.external_delivery_enabled !== 'boolean') missingFields.push('external_delivery_enabled')
  if (typeof value.external_aggregation_ready !== 'boolean') missingFields.push('external_aggregation_ready')
  assertOptionalRecordFields(value, ['alert_rule_policy', 'retention_policy', 'redaction_policy'], 'production alert export', missingFields)
  if (missingFields.length > 0) {
    throw new Error(`Unexpected production alert export response: missing ${missingFields.join(', ')}`)
  }
  assertProductionAlertEvents(value.events, 'production alert export')
  return value as unknown as ProductionAlertExportBundle
}

function assertProductionAlertExportHandoff(value: unknown): ProductionAlertExportHandoff {
  if (!isRecord(value)) {
    throw new Error('Unexpected production alert export handoff response')
  }
  const missingFields: string[] = [
    ...(['generated_at', 'schema', 'status', 'handoff_destination', 'export_schema', 'bundle_checksum', 'handoff_id', 'handoff_dir', 'bundle_file', 'manifest_file'] as const)
      .filter((field) => !hasTextField(value, field)),
    ...(['event_count', 'total_event_count', 'exported_count'] as const).filter((field) => !hasFiniteNumberField(value, field)),
  ]
  if (typeof value.external_delivery_enabled !== 'boolean') missingFields.push('external_delivery_enabled')
  if (typeof value.external_aggregation_ready !== 'boolean') missingFields.push('external_aggregation_ready')
  assertOptionalRecordFields(value, ['alert_rule_policy', 'manifest'], 'production alert export handoff', missingFields)
  if (missingFields.length > 0) {
    throw new Error(`Unexpected production alert export handoff response: missing ${missingFields.join(', ')}`)
  }
  return value as unknown as ProductionAlertExportHandoff
}

function assertProductionAlertDispatchResult(value: unknown): ProductionAlertDispatchResult {
  if (!isRecord(value)) {
    throw new Error('Unexpected production alert dispatch response')
  }
  const missingFields: string[] = [
    ...(['generated_at', 'channel', 'production_health_status', 'outbox_file'] as const).filter((field) => !hasTextField(value, field)),
    ...(['dispatched', 'deduplicated'] as const).filter((field) => !hasFiniteNumberField(value, field)),
  ]
  if (typeof value.external_delivery_enabled !== 'boolean') missingFields.push('external_delivery_enabled')
  assertOptionalRecordFields(value, ['alert_rule_policy'], 'production alert dispatch', missingFields)
  if (missingFields.length > 0) {
    throw new Error(`Unexpected production alert dispatch response: missing ${missingFields.join(', ')}`)
  }
  assertProductionAlertEvents(value.events, 'production alert dispatch')
  assertProductionAlertChannelStatus(value.status)
  return value as unknown as ProductionAlertDispatchResult
}

function assertOpsLogEvent(value: unknown, label: string): OpsLogEvent {
  if (!isRecord(value)) {
    throw new Error(`Unexpected ${label} response`)
  }
  const requiredStringFields = ['id', 'created_at', 'event_type', 'level', 'source', 'request_id', 'method', 'path', 'client', 'message']
  const missingFields: string[] = [
    ...requiredStringFields.filter((field) => !hasStringField(value, field)),
    ...(['status_code', 'duration_ms'] as const).filter((field) => !hasFiniteNumberField(value, field)),
  ]
  if (!isRecord(value.context)) missingFields.push('context')
  if (missingFields.length > 0) {
    throw new Error(`Unexpected ${label} response: missing ${missingFields.join(', ')}`)
  }
  return value as unknown as OpsLogEvent
}

function assertOpsLogEvents(value: unknown, label: string): OpsLogEvent[] {
  if (!Array.isArray(value)) {
    throw new Error(`Unexpected ${label} response: events must be an array`)
  }
  return value.map((event, index) => assertOpsLogEvent(event, `${label} event ${index}`))
}

function assertOpsLogStatus(value: unknown): OpsLogStatus {
  if (!isRecord(value)) {
    throw new Error('Unexpected ops log status response')
  }
  const missingFields: string[] = [
    ...(['generated_at', 'channel', 'log_file'] as const).filter((field) => !hasTextField(value, field)),
    ...(['event_count'] as const).filter((field) => !hasFiniteNumberField(value, field)),
  ]
  if (typeof value.enabled !== 'boolean') missingFields.push('enabled')
  if (typeof value.external_delivery_enabled !== 'boolean') missingFields.push('external_delivery_enabled')
  if (value.external_aggregation_ready !== undefined && typeof value.external_aggregation_ready !== 'boolean') missingFields.push('external_aggregation_ready')
  if (!isRecord(value.counts_by_level)) missingFields.push('counts_by_level')
  if (!isRecord(value.counts_by_type)) missingFields.push('counts_by_type')
  assertOptionalRecordFields(value, ['retention_policy', 'redaction_policy', 'handoff_status'], 'ops log status', missingFields)
  if (missingFields.length > 0) {
    throw new Error(`Unexpected ops log status response: missing ${missingFields.join(', ')}`)
  }
  assertNumberRecord(value.counts_by_level, 'ops log counts_by_level')
  assertNumberRecord(value.counts_by_type, 'ops log counts_by_type')
  assertOpsLogEvents(value.latest, 'ops log latest')
  return value as unknown as OpsLogStatus
}

function assertOpsLogQueryResult(value: unknown): OpsLogQueryResult {
  if (!isRecord(value)) {
    throw new Error('Unexpected ops log query response')
  }
  const stringFields = ['generated_at', 'schema', 'channel', 'source_channel', 'log_file', 'level_filter', 'event_type_filter', 'source_filter', 'text_filter', 'since']
  const missingFields: string[] = [
    ...stringFields.filter((field) => !hasStringField(value, field)),
    ...(['event_count', 'matched_count', 'returned_count', 'limit'] as const).filter((field) => !hasFiniteNumberField(value, field)),
  ]
  if (typeof value.external_delivery_enabled !== 'boolean') missingFields.push('external_delivery_enabled')
  if (typeof value.external_aggregation_ready !== 'boolean') missingFields.push('external_aggregation_ready')
  assertOptionalRecordFields(value, ['retention_policy', 'redaction_policy'], 'ops log query', missingFields)
  if (missingFields.length > 0) {
    throw new Error(`Unexpected ops log query response: missing ${missingFields.join(', ')}`)
  }
  assertOpsLogEvents(value.events, 'ops log query')
  return value as unknown as OpsLogQueryResult
}

function assertOpsLogExportBundle(value: unknown): OpsLogExportBundle {
  if (!isRecord(value)) {
    throw new Error('Unexpected ops log export response')
  }
  const stringFields = ['generated_at', 'schema', 'channel', 'source_channel', 'log_file', 'level_filter', 'since', 'checksum']
  const missingFields: string[] = [
    ...stringFields.filter((field) => !hasStringField(value, field)),
    ...(['event_count', 'exported_count'] as const).filter((field) => !hasFiniteNumberField(value, field)),
  ]
  if (typeof value.external_delivery_enabled !== 'boolean') missingFields.push('external_delivery_enabled')
  if (typeof value.external_aggregation_ready !== 'boolean') missingFields.push('external_aggregation_ready')
  assertOptionalRecordFields(value, ['retention_policy', 'redaction_policy'], 'ops log export', missingFields)
  if (missingFields.length > 0) {
    throw new Error(`Unexpected ops log export response: missing ${missingFields.join(', ')}`)
  }
  assertOpsLogEvents(value.events, 'ops log export')
  return value as unknown as OpsLogExportBundle
}

function assertOpsLogExportHandoff(value: unknown): OpsLogExportHandoff {
  if (!isRecord(value)) {
    throw new Error('Unexpected ops log export handoff response')
  }
  const stringFields = [
    'generated_at',
    'schema',
    'status',
    'handoff_destination',
    'export_schema',
    'bundle_checksum',
    'level_filter',
    'since',
    'handoff_id',
    'handoff_dir',
    'bundle_file',
    'manifest_file',
  ]
  const missingFields: string[] = [
    ...stringFields.filter((field) => !hasStringField(value, field)),
    ...(['event_count', 'exported_count'] as const).filter((field) => !hasFiniteNumberField(value, field)),
  ]
  if (typeof value.external_delivery_enabled !== 'boolean') missingFields.push('external_delivery_enabled')
  if (typeof value.external_aggregation_ready !== 'boolean') missingFields.push('external_aggregation_ready')
  assertOptionalRecordFields(value, ['manifest'], 'ops log export handoff', missingFields)
  if (missingFields.length > 0) {
    throw new Error(`Unexpected ops log export handoff response: missing ${missingFields.join(', ')}`)
  }
  return value as unknown as OpsLogExportHandoff
}

function assertCreateAnalysisResponse(value: unknown): CreateAnalysisResponse {
  if (!isRecord(value)) {
    throw new Error('Unexpected create analysis response')
  }
  const missingFields = ['run_id', 'status', 'stream_url'].filter((field) => !hasTextField(value, field))
  if (missingFields.length > 0 || value.status !== 'CREATED') {
    throw new Error(`Unexpected create analysis response: missing ${missingFields.join(', ') || 'CREATED status'}`)
  }
  return value as unknown as CreateAnalysisResponse
}

function assertStartAnalysisResponse(value: unknown): StartAnalysisResponse {
  if (!isRecord(value)) {
    throw new Error('Unexpected start analysis response')
  }
  const missingFields = ['run_id', 'status'].filter((field) => !hasTextField(value, field))
  if (missingFields.length > 0 || !['RUNNING', 'QUEUED', 'FAILED'].includes(String(value.status))) {
    throw new Error(`Unexpected start analysis response: missing ${missingFields.join(', ') || 'RUNNING/QUEUED/FAILED status'}`)
  }
  return value as unknown as StartAnalysisResponse
}

function assertAnalysisRunJobActionResponse(value: unknown): { run_id: string; status: AnalysisRun['status']; job: AnalysisJob } {
  if (!isRecord(value)) {
    throw new Error('Unexpected analysis run job action response')
  }
  const missingFields = ['run_id', 'status'].filter((field) => !hasTextField(value, field))
  if (missingFields.length > 0) {
    throw new Error(`Unexpected analysis run job action response: missing ${missingFields.join(', ')}`)
  }
  assertAnalysisJob(value.job, 'analysis run job action')
  return value as unknown as { run_id: string; status: AnalysisRun['status']; job: AnalysisJob }
}

function assertAnalysisJobs(value: unknown): AnalysisJob[] {
  if (!Array.isArray(value)) {
    throw new Error('Unexpected analysis jobs response')
  }
  return value.map((job, index) => assertAnalysisJob(job, `analysis jobs item ${index}`))
}

function assertAnalysisJob(value: unknown, label: string): AnalysisJob {
  if (!isRecord(value)) {
    throw new Error(`Unexpected ${label} response`)
  }
  const requiredTextFields = ['job_id', 'run_id', 'status', 'created_at', 'updated_at']
  const missingFields: string[] = [
    ...requiredTextFields.filter((field) => !hasTextField(value, field)),
    ...(['attempt'] as const).filter((field) => !hasFiniteNumberField(value, field)),
  ]
  const optionalNumberFields = ['max_attempts', 'priority', 'concurrency_limit', 'lease_seconds']
  missingFields.push(...optionalNumberFields.filter((field) => value[field] !== undefined && !hasFiniteNumberField(value, field)))
  if (value.history !== undefined && !Array.isArray(value.history)) missingFields.push('history')
  if (value.same_input_retry !== undefined && typeof value.same_input_retry !== 'boolean') missingFields.push('same_input_retry')
  if (missingFields.length > 0) {
    throw new Error(`Unexpected ${label} response: missing ${missingFields.join(', ')}`)
  }
  return value as unknown as AnalysisJob
}

function assertAnalysisJobSummary(value: unknown): AnalysisJobSummary {
  if (!isRecord(value)) {
    throw new Error('Unexpected analysis job summary response')
  }
  const missingFields: string[] = [
    ...(['generated_at'] as const).filter((field) => !hasTextField(value, field)),
    ...(['total_count', 'filtered_count', 'limit', 'offset'] as const).filter((field) => !hasFiniteNumberField(value, field)),
  ]
  if (!isRecord(value.counts_by_status)) missingFields.push('counts_by_status')
  if (!isStringArray(value.statuses)) missingFields.push('statuses')
  if (typeof value.has_more !== 'boolean') missingFields.push('has_more')
  if (value.external_queue_status !== undefined && !isRecord(value.external_queue_status)) missingFields.push('external_queue_status')
  if (missingFields.length > 0) {
    throw new Error(`Unexpected analysis job summary response: missing ${missingFields.join(', ')}`)
  }
  return value as unknown as AnalysisJobSummary
}

function assertAgentNodes(value: unknown): AgentNode[] {
  if (!Array.isArray(value)) {
    throw new Error('Unexpected analysis nodes response')
  }
  return value.map((node, index) => assertAgentNode(node, `analysis node item ${index}`))
}

function assertAgentNode(value: unknown, label: string): AgentNode {
  if (!isRecord(value)) {
    throw new Error(`Unexpected ${label} response`)
  }
  const missingFields: string[] = [
    ...(['id', 'name', 'status', 'auditId'] as const).filter((field) => !hasTextField(value, field)),
    ...(['duration'] as const).filter((field) => !hasFiniteNumberField(value, field)),
  ]
  for (const field of ['isRunning', 'isSkipped', 'isBlocked']) {
    if (typeof value[field] !== 'boolean') missingFields.push(field)
  }
  for (const field of ['missingData', 'downgradeReasons', 'blockedPaths', 'allowedNextActions']) {
    if (value[field] !== undefined && !isStringArray(value[field])) missingFields.push(field)
  }
  if (missingFields.length > 0) {
    throw new Error(`Unexpected ${label} response: missing ${missingFields.join(', ')}`)
  }
  assertAgentNodeBoundary(value, label)
  return value as unknown as AgentNode
}

function assertAnalysisDebateResponse(value: unknown): { debateArtifacts: DebateArtifacts; tokenUsage: TokenUsageSummary } {
  if (!isRecord(value)) {
    throw new Error('Unexpected analysis debate response')
  }
  assertDebateArtifacts(value.debateArtifacts)
  assertTokenUsageSummary(value.tokenUsage)
  return value as unknown as { debateArtifacts: DebateArtifacts; tokenUsage: TokenUsageSummary }
}

function assertDebateArtifacts(value: unknown) {
  if (!isRecord(value)) {
    throw new Error('Unexpected debate artifacts response')
  }
  const missingFields = ['run_id', 'final_action', 'final_decision_cap', 'audit_id'].filter((field) => !hasTextField(value, field))
  if (!isRecord(value.kill_switch)) missingFields.push('kill_switch')
  if (!Array.isArray(value.turns)) missingFields.push('turns')
  if (!isRecord(value.summary)) missingFields.push('summary')
  if (missingFields.length > 0) {
    throw new Error(`Unexpected debate artifacts response: missing ${missingFields.join(', ')}`)
  }
}

function assertTokenUsageSummary(value: unknown) {
  if (!isRecord(value)) {
    throw new Error('Unexpected token usage summary response')
  }
  const missingFields = ['metering_status', 'note'].filter((field) => !hasStringField(value, field))
  if (!Array.isArray(value.rows)) missingFields.push('rows')
  if (!isRecord(value.totals)) {
    missingFields.push('totals')
  } else {
    missingFields.push(...(['prompt_tokens', 'completion_tokens', 'total_tokens', 'latency_ms'] as const).filter((field) => !hasFiniteNumberField(value.totals as Record<string, unknown>, field)))
  }
  if (missingFields.length > 0) {
    throw new Error(`Unexpected token usage summary response: missing ${missingFields.join(', ')}`)
  }
}

function assertFinalReportAssets(value: unknown): FinalReportAsset[] {
  if (!Array.isArray(value)) {
    throw new Error('Unexpected final reports response')
  }
  return value.map((report, index) => assertFinalReportAsset(report, index))
}

function assertFinalReportAsset(value: unknown, index?: number): FinalReportAsset {
  const label = index === undefined ? 'final report' : `final reports item ${index}`
  if (!isRecord(value)) {
    throw new Error(`Unexpected ${label} response`)
  }
  const requiredTextFields = [
    'report_id',
    'run_id',
    'audit_id',
    'symbol',
    'task_type',
    'data_mode',
    'final_action',
    'final_writer_mode',
    'summary',
    'created_at',
    'updated_at',
  ]
  const missingFields = requiredTextFields.filter((field) => !hasTextField(value, field))
  if (value.stock_name !== undefined && !hasStringField(value, 'stock_name')) missingFields.push('stock_name')
  if (typeof value.human_confirmation_required !== 'boolean') missingFields.push('human_confirmation_required')
  if (!Array.isArray(value.sections)) missingFields.push('sections')
  if (!isRecord(value.source_snapshot)) missingFields.push('source_snapshot')
  if (!isRecord(value.metadata)) missingFields.push('metadata')
  if (missingFields.length > 0) {
    throw new Error(`Unexpected ${label} response: missing ${missingFields.join(', ')}`)
  }
  return value as unknown as FinalReportAsset
}

function assertDeleteAnalysisRunResponse(value: unknown): { deleted: string } {
  if (!isRecord(value) || !hasTextField(value, 'deleted')) {
    throw new Error('Unexpected delete analysis run response')
  }
  return value as unknown as { deleted: string }
}

function assertAnalysisJobAttempts(value: unknown): AnalysisJobAttempt[] {
  if (!Array.isArray(value)) {
    throw new Error('Unexpected analysis job attempts response')
  }
  return value.map((item, index) => assertAnalysisJobAttempt(item, index))
}

function assertAnalysisJobAttempt(value: unknown, index: number): AnalysisJobAttempt {
  if (!isRecord(value)) {
    throw new Error(`Unexpected analysis job attempts response: item ${index} must be an object`)
  }

  const requiredTextFields = ['job_id', 'run_id', 'status', 'created_at', 'updated_at']
  const missingFields = [
    ...requiredTextFields.filter((field) => !hasTextField(value, field)),
    ...(['attempt'] as const).filter((field) => !hasFiniteNumberField(value, field)),
  ]
  if (missingFields.length > 0) {
    throw new Error(`Unexpected analysis job attempts response: item ${index} missing ${missingFields.join(', ')}`)
  }
  if (value.history !== undefined && !Array.isArray(value.history)) {
    throw new Error(`Unexpected analysis job attempts response: item ${index} history must be an array`)
  }

  return value as unknown as AnalysisJobAttempt
}

function assertRunCompareResult(value: unknown): RunCompareResult {
  if (!isRecord(value)) {
    throw new Error('Unexpected run compare response')
  }

  assertAnalysisRunSummary(value.leftRun)
  assertAnalysisRunSummary(value.rightRun)

  const missingFields = [
    ...(['generatedAt'] as const).filter((field) => !hasTextField(value, field)),
    ...(['changedCount'] as const).filter((field) => !hasFiniteNumberField(value, field)),
  ]
  if (missingFields.length > 0) {
    throw new Error(`Unexpected run compare response: missing ${missingFields.join(', ')}`)
  }

  if (!isStringArray(value.summary)) {
    throw new Error('Unexpected run compare response: summary must be a string array')
  }
  if (!Array.isArray(value.diffs)) {
    throw new Error('Unexpected run compare response: diffs must be an array')
  }

  for (const [index, diff] of value.diffs.entries()) {
    if (!isRecord(diff)) {
      throw new Error(`Unexpected run compare response: diff ${index} must be an object`)
    }
    const missingDiffFields = ['key', 'label', 'impact'].filter((field) => !hasTextField(diff, field))
    if (typeof diff.changed !== 'boolean') {
      missingDiffFields.push('changed')
    }
    if (missingDiffFields.length > 0) {
      throw new Error(`Unexpected run compare response: diff ${index} missing ${missingDiffFields.join(', ')}`)
    }
  }

  return value as unknown as RunCompareResult
}

function assertRunStreamEvent(value: unknown, index: number) {
  if (!isRecord(value)) {
    throw new Error(`Unexpected analysis run response: streamEvents ${index} must be an object`)
  }
  if (!hasTextField(value, 'event_type')) {
    throw new Error(`Unexpected analysis run response: streamEvents ${index} missing event_type`)
  }
  for (const field of ['run_id', 'node_id', 'message', 'audit_id', 'timestamp']) {
    if (value[field] !== undefined && !hasStringField(value, field)) {
      throw new Error(`Unexpected analysis run response: streamEvents ${index} ${field} must be a string`)
    }
  }
  if (value.payload !== undefined) {
    if (!isRecord(value.payload)) {
      throw new Error(`Unexpected analysis run response: streamEvents ${index} payload must be an object`)
    }
    assertSimulationBoundaryPayload(value.payload, `streamEvents ${index} payload`)
  }
}

function assertAnalysisRun(value: unknown): AnalysisRun {
  if (!isRecord(value)) {
    throw new Error('Unexpected analysis run response')
  }

  const requiredTextFields = [
    'runId',
    'runMode',
    'environment',
    'stockCode',
    // stockName is a display label and may be blank for API-created run shells.
    'taskType',
    'finalAction',
    'createdAt',
    'updatedAt',
    'status',
  ]
  const requiredObjectFields = [
    'userPosition',
    'dvg',
    'risk',
    'atrade',
    'market',
    'factorSlicing',
    'chipKb',
    'qiam',
    'portfolio',
    'execution',
    'signalOps',
    'paperTrading',
    'killSwitch',
  ]
  const streamEvents = value.streamEvents
  const missingFields = [
    ...requiredTextFields.filter((field) => !hasTextField(value, field)),
    ...requiredObjectFields.filter((field) => !isRecord(value[field])),
    ...(['nodes', 'auditLog'] as const).filter((field) => !Array.isArray(value[field])),
  ]
  if (streamEvents !== undefined && !Array.isArray(streamEvents)) {
    missingFields.push('streamEvents')
  }

  if (missingFields.length > 0) {
    throw new Error(`Unexpected analysis run response: missing ${missingFields.slice(0, 5).join(', ')}`)
  }

  assertPaperTradingBoundary(value.paperTrading as Record<string, unknown>)
  assertPortfolioRunBoundary(value.portfolio as Record<string, unknown>)
  if (value.quantCore !== undefined && value.quantCore !== null) {
    if (!isRecord(value.quantCore)) {
      throw new Error('Unexpected analysis run response: quantCore must be an object or null')
    }
    assertQuantCoreBoundary(value.quantCore)
  }
  const nodes = value.nodes as unknown[]
  nodes.forEach((node, index) => assertAgentNode(node, `analysis run node ${index}`))

  if (Array.isArray(streamEvents)) {
    streamEvents.forEach((event, index) => assertRunStreamEvent(event, index))
  }

  return value as unknown as AnalysisRun
}

function assertAnalysisRunSummary(value: unknown): AnalysisRunSummary {
  if (!isRecord(value)) {
    throw new Error('Unexpected analysis run summary response')
  }

  // Identity and display-critical fields — must be present.
  const requiredFields = ['runId', 'stockCode', 'status', 'taskType', 'createdAt']
  const missingFields = requiredFields.filter((field) => !hasTextField(value, field))
  if (missingFields.length > 0) {
    throw new Error(`Unexpected analysis run summary response: missing ${missingFields.slice(0, 5).join(', ')}`)
  }

  // Non-critical display/navigation fields — normalize with sensible defaults
  // but warn in dev to surface potential API contract drift.
  const safeDefault = <T extends string>(field: string, fallback: T): T => {
    const raw = (value as Record<string, unknown>)[field]
    if (typeof raw === 'string' && raw.trim()) return raw as T
    if (window.location.hostname === 'localhost') {
      console.warn(
        `[analysisClient] assertAnalysisRunSummary: "${field}" missing or empty, defaulting to "${fallback}"`,
      )
    }
    return fallback
  }

  const createdAt = value.createdAt as string
  const updatedAt = typeof value.updatedAt === 'string' && value.updatedAt.trim()
    ? value.updatedAt
    : createdAt
  return {
    ...value,
    stockName: typeof value.stockName === 'string' ? value.stockName : '',
    runMode: safeDefault('runMode', 'STANDARD_MODE'),
    finalAction: safeDefault('finalAction', 'WAIT'),
    createdAt,
    updatedAt,
  } as AnalysisRunSummary
}
