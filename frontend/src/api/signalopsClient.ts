import { request } from './httpClient'
import {
  AgentSimulationCaseItem,
  AutoPaperTradingCommandPayload,
  AutoPaperTradingCommandResult,
  AutoPaperTradingConfig,
  AutoPaperTradingTickResult,
  CleanedSignalRecord,
  CreateSignalPayload,
  PaperFillPayload,
  PaperOrderItem,
  PaperOrderPayload,
  PaperPositionItem,
  PaperPortfolioItem,
  PaperPortfolioPayload,
  SignalOpsReviewDecisionAction,
  SignalOpsReviewDecisionRecord,
  SignalOpsReviewQueueState,
  SignalOpsDecisionTreeReview,
  SignalOpsDecisionTreeState,
  SignalOpsExperimentValidationState,
  SignalOpsResearchReview,
  SignalDetail,
  SignalItem,
  SignalReviewItem,
  SignalReviewPayload,
  SignalTransitionItem,
  SignalTransitionPayload,
  TuningUpdate,
  UpdateSignalConditionsPayload,
  UpdateAutoPaperTradingConfigPayload,
} from '../types'

export type AutoPaperTradingStatusResponse = {
  enabled?: boolean
  automation_mode?: string
  automation_modules?: Record<string, unknown>
  loop_running?: boolean
  loop_health?: string
  loop_last_error?: string
  loop_started_at?: string
  loop_heartbeat_at?: string
  heartbeat_at?: string
  current_time?: string
  last_tick_at?: string
  last_success_at?: string
  last_error?: string | null
  config_updated_at?: string
  tick_interval_seconds?: number
  next_tick_due_at?: string | null
  seconds_until_next_tick?: number | null
  last_tick_result?: Record<string, unknown>
  last_module_evidence?: Record<string, unknown>
  last_portfolio_snapshot?: Record<string, unknown>
  last_research_review?: SignalOpsResearchReview | null
  compressed_observation_history?: Record<string, unknown> | null
  review_queue_state?: SignalOpsReviewQueueState | null
  review_decisions?: SignalOpsReviewDecisionRecord[]
  review_decision_event_ledger?: Record<string, unknown> | null
  experiment_validation_state?: SignalOpsExperimentValidationState | null
  random_validation_state?: Record<string, unknown> | null
  decision_tree_state?: SignalOpsDecisionTreeState | null
  storage_warning?: string
  [key: string]: unknown
}

export type { SignalOpsDecisionCard } from '../types'

export type AutoPaperTradingReviewDecisionEventExport = {
  schema: string
  generated_at: string
  returned_event_count: number
  total_event_count: number
  latest_event_hash?: string
  bundle_checksum: string
  export_signature_status?: string
  export_signature?: Record<string, unknown> | null
  events: Array<Record<string, unknown>>
  ledger_file?: string
  append_only?: boolean
  warnings?: string[]
  simulation_only?: boolean
  is_real_trade?: boolean
}

export type AutoPaperTradingReviewDecisionEventVerification = {
  schema: string
  status: string
  valid: boolean
  checked_at?: string
  signature_status?: string
  schema_valid?: boolean
  checksum_valid?: boolean
  signature_valid?: boolean
  payload_checksum_valid?: boolean
  signed_fields_valid?: boolean
  signing_key_ref_valid?: boolean
  latest_event_hash_valid?: boolean
  returned_event_count_valid?: boolean
  total_event_count_valid?: boolean
  boundary_valid?: boolean
  signature_boundary_valid?: boolean
  provided_bundle_checksum?: string
  expected_bundle_checksum?: string
  signing_key_ref?: string
  expected_signing_key_ref?: string
  event_count?: number
  warnings?: string[]
  append_only?: boolean
  simulation_only?: boolean
  is_real_trade?: boolean
}

export type AutoPaperTradingReviewDecisionEventHandoff = {
  schema: string
  status: string
  created_at?: string
  reason?: string
  handoff_id?: string
  handoff_dir?: string
  handoff_destination?: string
  handoff_requires_signature?: boolean
  bundle_file?: string
  manifest_file?: string
  bundle_checksum?: string
  export_signature_status?: string
  verification?: AutoPaperTradingReviewDecisionEventVerification | Record<string, unknown>
  shipper_status?: Record<string, unknown>
  manifest?: Record<string, unknown>
  append_only?: boolean
  simulation_only?: boolean
  is_real_trade?: boolean
}

export type AutoPaperTradingDailyReviewResult = {
  status: string
  message: string
  trading_date: string
  loop_id?: string | null
  iteration_id?: string | null
  reviewed_symbols: Array<Record<string, unknown>>
  case_ids: string[]
  evidence_links: Array<Record<string, unknown>>
  tuning_update: TuningUpdate
  cleaned_records: CleanedSignalRecord[]
  review_queue_state?: SignalOpsReviewQueueState
  review_decisions?: SignalOpsReviewDecisionRecord[]
  experiment_validation_state?: SignalOpsExperimentValidationState
  decision_tree_reviews?: SignalOpsDecisionTreeReview[]
  warnings: string[]
  config: AutoPaperTradingConfig
}

export type AutoPaperTradingReviewDecisionResult = {
  status: string
  message: string
  decision: SignalOpsReviewDecisionRecord | Record<string, unknown>
  queue_item: Record<string, unknown>
  config: AutoPaperTradingConfig
  warnings: string[]
}

function ensureArray<T = unknown>(value: unknown, label: string): T[] {
  if (!Array.isArray(value)) {
    throw new Error(`Unexpected ${label} response`)
  }
  return value as T[]
}

function ensureRecord(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(`Unexpected ${label} response`)
  }
  return value as Record<string, unknown>
}

function asRecord(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return {}
  }
  return value as Record<string, unknown>
}

function hasKeys(value: Record<string, unknown>): boolean {
  return Object.keys(value).length > 0
}

function assertStringArray(value: unknown, label: string) {
  if (!Array.isArray(value) || value.some((item) => typeof item !== 'string')) {
    throw new Error(`Unexpected ${label} response`)
  }
}

function assertOptionalStringArray(root: Record<string, unknown>, key: string, label: string) {
  if (root[key] !== undefined) {
    assertStringArray(root[key], label)
  }
}

function requireString(record: Record<string, unknown>, key: string, label: string) {
  if (typeof record[key] !== 'string') {
    throw new Error(`Unexpected ${label} response`)
  }
}

function requireBoolean(record: Record<string, unknown>, key: string, label: string) {
  if (typeof record[key] !== 'boolean') {
    throw new Error(`Unexpected ${label} response`)
  }
}

function requireFiniteNumber(record: Record<string, unknown>, key: string, label: string) {
  if (typeof record[key] !== 'number' || !Number.isFinite(record[key])) {
    throw new Error(`Unexpected ${label} response`)
  }
}

function assertSimulationOnlyRecordBoundary(value: unknown, label: string) {
  const record = asRecord(value)
  if (!hasKeys(record)) return
  if (record.simulation_only === false || record.is_real_trade === true) {
    throw new Error(`${label} broke SignalOps simulation-only boundary`)
  }
}

function assertRequiredSimulationOnlyRecordBoundary(value: unknown, label: string) {
  const record = ensureRecord(value, label)
  if (record.simulation_only !== true || record.is_real_trade !== false) {
    throw new Error(`${label} broke SignalOps simulation-only boundary`)
  }
}

function assertSignalOpsAutomationBoundary(value: unknown, label: string) {
  const root = ensureRecord(value, label) as Record<string, unknown>
  const config = asRecord(root.config)
  const source = hasKeys(config) ? config : root
  const modules = asRecord(source.automation_modules)
  const sourceSimulation = asRecord(source.simulation_module)
  const moduleSimulation = asRecord(modules.simulation)
  const simulation = hasKeys(sourceSimulation) ? sourceSimulation : moduleSimulation
  const sourceLive = asRecord(source.live_module)
  const moduleLive = asRecord(modules.live)
  const live = hasKeys(sourceLive) ? sourceLive : moduleLive
  const mode = String(source.automation_mode || modules.mode || '').toUpperCase()

  if (mode && mode !== 'SIMULATION' && mode !== 'LIVE_DISABLED') {
    throw new Error(`${label} returned unsupported SignalOps automation mode`)
  }
  if (modules.active_module !== undefined && String(modules.active_module).toLowerCase() !== 'simulation') {
    throw new Error(`${label} used a non-simulation SignalOps automation module`)
  }
  if (modules.real_trade_enabled === true || modules.live_ready === true) {
    throw new Error(`${label} enabled SignalOps live trading flags`)
  }
  assertSimulationOnlyRecordBoundary(simulation, `${label} simulation module`)
  if (!hasKeys(live)) {
    throw new Error(`${label} is missing SignalOps live module boundary`)
  }
  if (live.enabled === true || live.execution_enabled === true || live.is_real_trade === true || live.simulation_only === false) {
    throw new Error(`${label} enabled SignalOps live trading boundary`)
  }
  if (live.order_router !== undefined && live.order_router !== 'DISABLED') {
    throw new Error(`${label} returned an enabled SignalOps live order router`)
  }
}

function assertAutoPaperTradingConfigResponse(value: unknown): AutoPaperTradingConfig {
  const config = ensureRecord(value, 'auto-paper config') as unknown as AutoPaperTradingConfig
  assertSignalOpsAutomationBoundary(config, 'auto-paper config')
  assertSimulationOnlyRecordBoundary(config.review_queue_state, 'auto-paper config review queue')
  assertSimulationOnlyRecordBoundary(config.experiment_validation_state, 'auto-paper config experiment validation')
  assertSimulationOnlyRecordBoundary(config.random_validation_state, 'auto-paper config random validation')
  assertSimulationOnlyRecordBoundary(config.decision_tree_state, 'auto-paper config decision tree')
  if (config.review_decisions !== undefined) {
    ensureArray(config.review_decisions, 'auto-paper config review decisions').forEach((decision) => {
      assertSimulationOnlyRecordBoundary(decision, 'auto-paper config review decision')
    })
  }
  return config
}

function assertAutoPaperTradingStatusResponse(value: unknown): AutoPaperTradingStatusResponse {
  const status = ensureRecord(value, 'auto-paper status') as AutoPaperTradingStatusResponse
  assertSignalOpsAutomationBoundary(status, 'auto-paper status')
  assertSimulationOnlyRecordBoundary(status.last_tick_result, 'auto-paper status last tick')
  assertSimulationOnlyRecordBoundary(status.last_module_evidence, 'auto-paper status module evidence')
  assertSimulationOnlyRecordBoundary(status.last_portfolio_snapshot, 'auto-paper status portfolio snapshot')
  assertSimulationOnlyRecordBoundary(status.review_queue_state, 'auto-paper status review queue')
  assertSimulationOnlyRecordBoundary(status.experiment_validation_state, 'auto-paper status experiment validation')
  assertSimulationOnlyRecordBoundary(status.random_validation_state, 'auto-paper status random validation')
  assertSimulationOnlyRecordBoundary(status.decision_tree_state, 'auto-paper status decision tree')
  if (status.review_decisions !== undefined) {
    ensureArray(status.review_decisions, 'auto-paper status review decisions').forEach((decision) => {
      assertSimulationOnlyRecordBoundary(decision, 'auto-paper status review decision')
    })
  }
  return status
}

function assertAutoPaperTradingTickResult(value: unknown): AutoPaperTradingTickResult {
  const result = ensureRecord(value, 'auto-paper tick') as unknown as AutoPaperTradingTickResult
  const root = asRecord(result)
  assertSignalOpsAutomationBoundary(result, 'auto-paper tick')
  assertOptionalStringArray(root, 'warnings', 'auto-paper tick warnings')
  assertSimulationOnlyRecordBoundary(root.decision, 'auto-paper tick decision')
  assertSimulationOnlyRecordBoundary(root.decision_card, 'auto-paper tick decision card')
  assertSimulationOnlyRecordBoundary(root.module_evidence, 'auto-paper tick module evidence')
  assertSimulationOnlyRecordBoundary(root.portfolio_snapshot, 'auto-paper tick portfolio snapshot')
  assertSimulationOnlyRecordBoundary(root.order, 'auto-paper tick order')
  assertSimulationOnlyRecordBoundary(root.portfolio, 'auto-paper tick portfolio')
  const moduleEvidence = asRecord(root.module_evidence)
  const tradeBoundary = asRecord(moduleEvidence.trade_boundary)
  if (hasKeys(tradeBoundary)) {
    if (tradeBoundary.allowed_order_namespace !== undefined && tradeBoundary.allowed_order_namespace !== 'SIM_*') {
      throw new Error('auto-paper tick returned a non-simulation order namespace')
    }
    if (tradeBoundary.live_module_status !== undefined && tradeBoundary.live_module_status !== 'CONFIGURED_DISABLED') {
      throw new Error('auto-paper tick returned an enabled live module boundary')
    }
  }
  const automationModules = asRecord(moduleEvidence.automation_modules)
  if (hasKeys(automationModules) && automationModules.active_module !== 'simulation') {
    throw new Error('auto-paper tick module evidence used a non-simulation automation module')
  }
  if (Array.isArray(result.results)) {
    result.results.forEach((item) => assertSimulationOnlyRecordBoundary(item, 'auto-paper tick pooled result'))
  }
  return result
}

function assertAutoPaperTradingDailyReviewResult(value: unknown): AutoPaperTradingDailyReviewResult {
  const result = ensureRecord(value, 'auto-paper daily review') as AutoPaperTradingDailyReviewResult
  const root = asRecord(result)
  assertSignalOpsAutomationBoundary(result, 'auto-paper daily review')
  assertStringArray(result.case_ids, 'auto-paper daily review case ids')
  assertStringArray(result.warnings, 'auto-paper daily review warnings')
  ensureArray(result.reviewed_symbols, 'auto-paper daily review reviewed symbols').forEach((item) => {
    assertSimulationOnlyRecordBoundary(item, 'auto-paper daily review reviewed symbol')
  })
  ensureArray(result.evidence_links, 'auto-paper daily review evidence links')
  ensureArray(result.cleaned_records, 'auto-paper daily review cleaned records').forEach((record) => {
    assertSimulationOnlyRecordBoundary(record, 'auto-paper daily review cleaned record')
  })
  assertSimulationOnlyRecordBoundary(root.review_queue_state, 'auto-paper daily review queue')
  assertSimulationOnlyRecordBoundary(root.experiment_validation_state, 'auto-paper daily review experiment validation')
  assertSimulationOnlyRecordBoundary(root.random_validation_state, 'auto-paper daily review random validation')
  ensureArray(result.decision_tree_reviews || [], 'auto-paper daily review decision tree reviews').forEach((review) => {
    assertSimulationOnlyRecordBoundary(review, 'auto-paper daily review decision tree review')
  })
  ensureArray(result.review_decisions || [], 'auto-paper daily review decisions').forEach((decision) => {
    assertSimulationOnlyRecordBoundary(decision, 'auto-paper daily review decision')
  })
  return result
}

function assertAutoPaperTradingCommandResult(value: unknown): AutoPaperTradingCommandResult {
  const result = ensureRecord(value, 'auto-paper command') as unknown as AutoPaperTradingCommandResult
  const root = asRecord(result)
  assertSignalOpsAutomationBoundary(result, 'auto-paper command')
  assertStringArray(result.warnings, 'auto-paper command warnings')
  assertSimulationOnlyRecordBoundary(root.order, 'auto-paper command order')
  assertSimulationOnlyRecordBoundary(root.portfolio, 'auto-paper command portfolio')
  const order = asRecord(root.order)
  if (hasKeys(order)) {
    const action = String(order.action || '')
    if (action && !action.startsWith('SIM_')) {
      throw new Error('auto-paper command returned a non-simulation order action')
    }
    assertSimulationOnlyRecordBoundary(order.risk_constraints, 'auto-paper command risk constraints')
  }
  return result
}

function assertAutoPaperTradingReviewDecisionResult(value: unknown): AutoPaperTradingReviewDecisionResult {
  const result = ensureRecord(value, 'auto-paper review decision') as AutoPaperTradingReviewDecisionResult
  const root = result as Record<string, unknown>
  assertSignalOpsAutomationBoundary(result, 'auto-paper review decision')
  assertStringArray(result.warnings, 'auto-paper review decision warnings')
  assertSimulationOnlyRecordBoundary(root.decision, 'auto-paper review decision record')
  assertSimulationOnlyRecordBoundary(root.queue_item, 'auto-paper review decision queue item')
  const decision = asRecord(root.decision)
  assertSimulationOnlyRecordBoundary(decision.parameter_diff_summary, 'auto-paper review decision parameter diff')
  return result
}

function assertReviewDecisionEventExport(value: unknown): AutoPaperTradingReviewDecisionEventExport {
  const result = ensureRecord(value, 'auto-paper review decision event export') as AutoPaperTradingReviewDecisionEventExport
  const root = result as Record<string, unknown>
  assertStringArray(result.warnings || [], 'auto-paper review decision event export warnings')
  if (root.append_only !== true || root.simulation_only !== true || root.is_real_trade !== false) {
    throw new Error('auto-paper review decision event export broke append-only simulation boundary')
  }
  ensureArray(result.events, 'auto-paper review decision event export events')
  return result
}

function assertReviewDecisionEventVerification(value: unknown): AutoPaperTradingReviewDecisionEventVerification {
  const result = ensureRecord(value, 'auto-paper review decision event verification') as AutoPaperTradingReviewDecisionEventVerification
  const root = result as Record<string, unknown>
  assertStringArray(result.warnings || [], 'auto-paper review decision event verification warnings')
  if (root.simulation_only !== true || root.is_real_trade !== false) {
    throw new Error('auto-paper review decision event verification broke simulation boundary')
  }
  return result
}

function assertReviewDecisionEventHandoff(value: unknown): AutoPaperTradingReviewDecisionEventHandoff {
  const result = ensureRecord(value, 'auto-paper review decision event handoff') as AutoPaperTradingReviewDecisionEventHandoff
  const root = result as Record<string, unknown>
  if (root.simulation_only !== true || root.is_real_trade !== false) {
    throw new Error('auto-paper review decision event handoff broke simulation boundary')
  }
  return result
}

function assertSignalItem(value: unknown): SignalItem {
  const signal = ensureRecord(value, 'SignalOps signal')
  requireString(signal, 'signal_id', 'SignalOps signal')
  requireString(signal, 'symbol', 'SignalOps signal')
  requireString(signal, 'stock_name', 'SignalOps signal')
  requireString(signal, 'status', 'SignalOps signal')
  requireString(signal, 'audit_id', 'SignalOps signal')
  requireBoolean(signal, 'risk_passed', 'SignalOps signal')
  requireBoolean(signal, 'dvg_passed', 'SignalOps signal')
  requireString(signal, 'dvg_status', 'SignalOps signal')
  requireBoolean(signal, 'qiam_passed', 'SignalOps signal')
  requireString(signal, 'qiam_status', 'SignalOps signal')
  requireBoolean(signal, 'execution_reachable', 'SignalOps signal')
  requireBoolean(signal, 'portfolio_allowed', 'SignalOps signal')
  assertStringArray(signal.trigger_conditions, 'SignalOps signal trigger conditions')
  assertStringArray(signal.invalidation_conditions, 'SignalOps signal invalidation conditions')
  assertStringArray(signal.review_fields, 'SignalOps signal review fields')
  assertStringArray(signal.attached_runs, 'SignalOps signal attached runs')
  requireString(signal, 'blocked_reason', 'SignalOps signal')
  ensureRecord(signal.metadata_json, 'SignalOps signal metadata')
  requireString(signal, 'created_at', 'SignalOps signal')
  requireString(signal, 'updated_at', 'SignalOps signal')
  return value as SignalItem
}

function assertSignalGateCheck(value: unknown): void {
  const gate = ensureRecord(value, 'SignalOps transition gate check')
  requireString(gate, 'key', 'SignalOps transition gate check')
  requireBoolean(gate, 'passed', 'SignalOps transition gate check')
  requireString(gate, 'message', 'SignalOps transition gate check')
}

function assertSignalTransitionItem(value: unknown): SignalTransitionItem {
  const transition = ensureRecord(value, 'SignalOps transition')
  requireString(transition, 'transition_id', 'SignalOps transition')
  requireString(transition, 'signal_id', 'SignalOps transition')
  requireString(transition, 'from_status', 'SignalOps transition')
  requireString(transition, 'to_status', 'SignalOps transition')
  requireString(transition, 'audit_id', 'SignalOps transition')
  requireString(transition, 'actor', 'SignalOps transition')
  requireString(transition, 'reason', 'SignalOps transition')
  ensureArray(transition.gate_checks, 'SignalOps transition gate checks').forEach(assertSignalGateCheck)
  requireBoolean(transition, 'passed', 'SignalOps transition')
  assertRequiredSimulationOnlyRecordBoundary(transition, 'SignalOps transition')
  requireString(transition, 'created_at', 'SignalOps transition')
  return value as SignalTransitionItem
}

function assertSignalReviewItem(value: unknown): SignalReviewItem {
  const review = ensureRecord(value, 'SignalOps review')
  requireString(review, 'review_id', 'SignalOps review')
  requireString(review, 'signal_id', 'SignalOps review')
  requireString(review, 'audit_id', 'SignalOps review')
  requireString(review, 'reviewer', 'SignalOps review')
  requireString(review, 'review_type', 'SignalOps review')
  requireString(review, 'decision', 'SignalOps review')
  requireString(review, 'note', 'SignalOps review')
  assertStringArray(review.review_fields, 'SignalOps review fields')
  assertRequiredSimulationOnlyRecordBoundary(review, 'SignalOps review')
  requireString(review, 'created_at', 'SignalOps review')
  return value as SignalReviewItem
}

function assertSignalDetail(value: unknown): SignalDetail {
  const detail = ensureRecord(value, 'SignalOps detail')
  assertSignalItem(detail.signal)
  ensureArray(detail.transitions, 'SignalOps detail transitions').forEach(assertSignalTransitionItem)
  ensureArray(detail.reviews, 'SignalOps detail reviews').forEach(assertSignalReviewItem)
  return value as SignalDetail
}

function assertPaperPortfolioItem(value: unknown): PaperPortfolioItem {
  const portfolio = ensureRecord(value, 'SignalOps paper portfolio')
  requireString(portfolio, 'portfolio_id', 'SignalOps paper portfolio')
  requireString(portfolio, 'signal_id', 'SignalOps paper portfolio')
  requireString(portfolio, 'audit_id', 'SignalOps paper portfolio')
  requireString(portfolio, 'symbol', 'SignalOps paper portfolio')
  requireFiniteNumber(portfolio, 'initial_cash', 'SignalOps paper portfolio')
  requireFiniteNumber(portfolio, 'available_cash', 'SignalOps paper portfolio')
  requireFiniteNumber(portfolio, 'market_value', 'SignalOps paper portfolio')
  requireFiniteNumber(portfolio, 'max_drawdown', 'SignalOps paper portfolio')
  ensureRecord(portfolio.risk_budget, 'SignalOps paper portfolio risk budget')
  requireString(portfolio, 'created_by_agent', 'SignalOps paper portfolio')
  assertRequiredSimulationOnlyRecordBoundary(portfolio, 'SignalOps paper portfolio')
  requireString(portfolio, 'created_at', 'SignalOps paper portfolio')
  requireString(portfolio, 'updated_at', 'SignalOps paper portfolio')
  return value as PaperPortfolioItem
}

function assertOptionalPaperPortfolioItem(value: unknown): PaperPortfolioItem | null {
  if (value === null) return null
  return assertPaperPortfolioItem(value)
}

function assertPaperPositionItem(value: unknown): PaperPositionItem {
  const position = ensureRecord(value, 'SignalOps paper position')
  requireString(position, 'position_id', 'SignalOps paper position')
  requireString(position, 'portfolio_id', 'SignalOps paper position')
  requireString(position, 'signal_id', 'SignalOps paper position')
  requireString(position, 'symbol', 'SignalOps paper position')
  requireFiniteNumber(position, 'quantity', 'SignalOps paper position')
  requireFiniteNumber(position, 'virtual_cost', 'SignalOps paper position')
  requireFiniteNumber(position, 'current_value', 'SignalOps paper position')
  requireFiniteNumber(position, 'floating_pnl', 'SignalOps paper position')
  requireFiniteNumber(position, 'max_drawdown', 'SignalOps paper position')
  assertRequiredSimulationOnlyRecordBoundary(position, 'SignalOps paper position')
  requireString(position, 'updated_at', 'SignalOps paper position')
  return value as PaperPositionItem
}

function assertPaperOrderItem(value: unknown): PaperOrderItem {
  const order = ensureRecord(value, 'SignalOps paper order')
  requireString(order, 'order_id', 'SignalOps paper order')
  requireString(order, 'paper_portfolio_id', 'SignalOps paper order')
  requireString(order, 'signal_id', 'SignalOps paper order')
  requireString(order, 'audit_id', 'SignalOps paper order')
  requireString(order, 'agent_id', 'SignalOps paper order')
  requireString(order, 'action', 'SignalOps paper order')
  requireString(order, 'action_reason', 'SignalOps paper order')
  requireFiniteNumber(order, 'simulated_price', 'SignalOps paper order')
  requireFiniteNumber(order, 'simulated_quantity', 'SignalOps paper order')
  requireString(order, 'fill_status', 'SignalOps paper order')
  ensureRecord(order.risk_constraints, 'SignalOps paper order risk constraints')
  assertStringArray(order.invalidation_conditions, 'SignalOps paper order invalidation conditions')
  requireString(order, 'data_snapshot_hash', 'SignalOps paper order')
  ensureRecord(order.simulated_fill, 'SignalOps paper order simulated fill')
  assertRequiredSimulationOnlyRecordBoundary(order, 'SignalOps paper order')
  requireString(order, 'created_at', 'SignalOps paper order')
  requireString(order, 'updated_at', 'SignalOps paper order')
  return value as PaperOrderItem
}

function assertAgentSimulationCaseItem(value: unknown): AgentSimulationCaseItem {
  const item = ensureRecord(value, 'SignalOps simulation case')
  requireString(item, 'case_id', 'SignalOps simulation case')
  requireString(item, 'case_source', 'SignalOps simulation case')
  requireString(item, 'operator_type', 'SignalOps simulation case')
  requireString(item, 'source_signal_id', 'SignalOps simulation case')
  requireString(item, 'source_paper_order_id', 'SignalOps simulation case')
  requireString(item, 'agent_id', 'SignalOps simulation case')
  requireString(item, 'audit_id', 'SignalOps simulation case')
  assertRequiredSimulationOnlyRecordBoundary(item, 'SignalOps simulation case')
  ensureRecord(item.outcome, 'SignalOps simulation case outcome')
  assertStringArray(item.failure_tags, 'SignalOps simulation case failure tags')
  requireString(item, 'knowledge_candidate_status', 'SignalOps simulation case')
  requireString(item, 'created_at', 'SignalOps simulation case')
  requireString(item, 'updated_at', 'SignalOps simulation case')
  return value as AgentSimulationCaseItem
}

export function createSignal(payload: CreateSignalPayload) {
  return request<unknown>('/signals', {
    method: 'POST',
    body: JSON.stringify(payload),
  }).then(assertSignalItem)
}

export function listSignals(params: { status?: string; symbol?: string; limit?: number } = {}) {
  const qs = new URLSearchParams()
  if (params.status) qs.set('status', params.status)
  if (params.symbol) qs.set('symbol', params.symbol)
  if (params.limit) qs.set('limit', String(params.limit))
  return request<unknown>(`/signals${qs.toString() ? `?${qs.toString()}` : ''}`).then((items) =>
    ensureArray(items, 'signals list').map(assertSignalItem),
  )
}

export function getSignal(signalId: string) {
  return request<unknown>(`/signals/${signalId}`).then(assertSignalDetail)
}

export function transitionSignal(signalId: string, payload: SignalTransitionPayload) {
  return request<unknown>(`/signals/${signalId}/transition`, {
    method: 'POST',
    body: JSON.stringify(payload),
  }).then(assertSignalTransitionItem)
}

export function attachSignalRun(signalId: string, runId: string, auditId?: string) {
  return request<unknown>(`/signals/${signalId}/attach-run`, {
    method: 'POST',
    body: JSON.stringify({ run_id: runId, audit_id: auditId }),
  }).then(assertSignalItem)
}

export function updateSignalConditions(signalId: string, payload: UpdateSignalConditionsPayload) {
  return request<unknown>(`/signals/${signalId}/conditions`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  }).then(assertSignalItem)
}

export function reviewSignal(signalId: string, payload: SignalReviewPayload) {
  return request<unknown>(`/signals/${signalId}/review`, {
    method: 'POST',
    body: JSON.stringify(payload),
  }).then(assertSignalReviewItem)
}

export function createPaperPortfolio(signalId: string, payload: PaperPortfolioPayload) {
  return request<unknown>(`/signalops/${signalId}/paper-portfolio`, {
    method: 'POST',
    body: JSON.stringify(payload),
  }).then(assertPaperPortfolioItem)
}

export function getPaperPortfolio(signalId: string, options: { allowMissing?: boolean } = {}) {
  const qs = options.allowMissing ? '?allow_missing=true' : ''
  return request<unknown>(`/signalops/${signalId}/paper-portfolio${qs}`).then(assertOptionalPaperPortfolioItem)
}

export function listPaperOrders(signalId: string) {
  return request<unknown>(`/signalops/${signalId}/paper-orders`).then((items) =>
    ensureArray(items, 'paper orders list').map(assertPaperOrderItem),
  )
}

export function listPaperPositions(signalId: string) {
  return request<unknown>(`/signalops/${signalId}/paper-positions`).then((items) =>
    ensureArray(items, 'paper positions list').map(assertPaperPositionItem),
  )
}

export function createPaperOrder(signalId: string, payload: PaperOrderPayload) {
  return request<unknown>(`/signalops/${signalId}/paper-orders`, {
    method: 'POST',
    body: JSON.stringify(payload),
  }).then(assertPaperOrderItem)
}

export function fillPaperOrder(signalId: string, orderId: string, payload: PaperFillPayload) {
  return request<unknown>(`/signalops/${signalId}/paper-orders/${orderId}/fill`, {
    method: 'POST',
    body: JSON.stringify(payload),
  }).then(assertPaperOrderItem)
}

export function createAgentSimulationCase(signalId: string, sourcePaperOrderId: string) {
  return request<unknown>(`/signalops/${signalId}/paper-cases`, {
    method: 'POST',
    body: JSON.stringify({
      source_paper_order_id: sourcePaperOrderId,
      knowledge_candidate_status: 'REVIEWING',
      outcome: { source: 'paper_order', review_required: true },
    }),
  }).then(assertAgentSimulationCaseItem)
}

export function listKnowledgeCases(source = 'AGENT_SIMULATION') {
  return request<unknown>(`/knowledge/cases?source=${encodeURIComponent(source)}`).then((items) =>
    ensureArray(items, 'knowledge cases list').map(assertAgentSimulationCaseItem),
  )
}

export function getAutoPaperTradingConfig() {
  return request<unknown>('/signalops/auto-paper/config?compact=true', {
    timeoutMs: 30000,
  }).then(assertAutoPaperTradingConfigResponse)
}

export function getAutoPaperTradingStatus() {
  return request<unknown>('/signalops/auto-paper/status?compact=true', {
    timeoutMs: 30000,
  }).then(assertAutoPaperTradingStatusResponse)
}

export function updateAutoPaperTradingConfig(payload: UpdateAutoPaperTradingConfigPayload) {
  return request<unknown>('/signalops/auto-paper/config', {
    method: 'PATCH',
    body: JSON.stringify(payload),
  }).then(assertAutoPaperTradingConfigResponse)
}

export function runAutoPaperTradingTick(force = false) {
  return request<unknown>('/signalops/auto-paper/tick', {
    method: 'POST',
    body: JSON.stringify({ force }),
    timeoutMs: 30000,
  }).then(assertAutoPaperTradingTickResult)
}

export function runAutoPaperTradingDailyReview(payload: {
  force?: boolean
  trading_date?: string
  reviewer?: string
} = {}) {
  return request<unknown>('/signalops/auto-paper/daily-review', {
    method: 'POST',
    body: JSON.stringify(payload),
    timeoutMs: 45000,
  }).then(assertAutoPaperTradingDailyReviewResult)
}

export function runAutoPaperTradingCommand(payload: AutoPaperTradingCommandPayload) {
  return request<unknown>('/signalops/auto-paper/command', {
    method: 'POST',
    body: JSON.stringify(payload),
    timeoutMs: 30000,
  }).then(assertAutoPaperTradingCommandResult)
}

export function recordAutoPaperTradingReviewDecision(payload: {
  queue_item_id?: string
  experiment_id?: string
  signal_id?: string | null
  symbol?: string
  action: SignalOpsReviewDecisionAction
  reviewer?: string
  reason?: string
  evidence_refs?: Array<Record<string, unknown>>
  review_fields?: string[]
}) {
  return request<unknown>('/signalops/auto-paper/review-decisions', {
    method: 'POST',
    body: JSON.stringify(payload),
    timeoutMs: 30000,
  }).then(assertAutoPaperTradingReviewDecisionResult)
}

export function getAutoPaperTradingReviewDecisionEvents(limit = 100) {
  const qs = new URLSearchParams()
  qs.set('limit', String(limit))
  return request<unknown>(`/signalops/auto-paper/review-decision-events?${qs.toString()}`)
    .then(assertReviewDecisionEventExport)
}

export function verifyAutoPaperTradingReviewDecisionEventExport(bundle: AutoPaperTradingReviewDecisionEventExport | Record<string, unknown>) {
  return request<unknown>('/signalops/auto-paper/review-decision-events/verify', {
    method: 'POST',
    body: JSON.stringify({ bundle }),
    timeoutMs: 30000,
  }).then(assertReviewDecisionEventVerification)
}

export function handoffAutoPaperTradingReviewDecisionEvents(limit = 100) {
  const qs = new URLSearchParams()
  qs.set('limit', String(limit))
  return request<unknown>(`/signalops/auto-paper/review-decision-events/handoff?${qs.toString()}`, {
    method: 'POST',
    timeoutMs: 30000,
  }).then(assertReviewDecisionEventHandoff)
}
