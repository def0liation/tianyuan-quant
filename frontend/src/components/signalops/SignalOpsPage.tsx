import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { CheckCircle2, ChevronDown, ChevronUp, Eye, FlaskConical, Play, Plus, RefreshCw, Save, Square, Trash2, Wrench, XCircle } from 'lucide-react'
import { createResearchSignalOpsEvidence } from '../../api/researchClient'
import {
  createSignal,
  getAutoPaperTradingConfig,
  getAutoPaperTradingReviewDecisionEvents,
  getAutoPaperTradingStatus,
  handoffAutoPaperTradingReviewDecisionEvents,
  getPaperPortfolio,
  getSignal,
  listPaperOrders,
  listPaperPositions,
  listSignals,
  recordAutoPaperTradingReviewDecision,
  reviewSignal,
  runAutoPaperTradingCommand,
  runAutoPaperTradingDailyReview,
  runAutoPaperTradingTick,
  transitionSignal,
  type AutoPaperTradingDailyReviewResult,
  type AutoPaperTradingReviewDecisionEventHandoff,
  type AutoPaperTradingReviewDecisionEventVerification,
  type AutoPaperTradingStatusResponse,
  updateAutoPaperTradingConfig,
  updateSignalConditions,
  verifyAutoPaperTradingReviewDecisionEventExport,
} from '../../api/signalopsClient'
import { useAnalysisStore } from '../../store/useAnalysisStore'
import {
  AutoPaperTradingCommandResult,
  AutoPaperTradingConfig,
  AutoPaperTradingTickResult,
  CleanedSignalRecord,
  EvidenceQuality,
  KlineEvidencePackage,
  KlineSignalQuality,
  PaperOrderItem,
  PaperPositionItem,
  PaperPortfolioItem,
  PerformanceBucket,
  PerformanceStats,
  SignalOpsDecisionCard,
  SignalOpsDecisionTree,
  SignalOpsDecisionTreeBranch,
  SignalOpsDecisionTreeReview,
  SignalOpsDecisionTreeState,
  SignalOpsReviewDecision,
  SignalOpsReviewDecisionAction,
  SignalOpsReviewQueueItem,
  SignalDetail,
  SignalOpsExperimentValidationAttempt,
  SignalItem,
  SignalOpsStatus,
  StabilityEvidencePackage,
  StrategyStabilityQuality,
  TuningUpdate,
  UpdateAutoPaperTradingConfigPayload,
} from '../../types'
import { Badge } from '../common/Badge'
import { Card } from '../common/Card'
import { EvidenceLedger, FactorBarStack, TableShell } from '../common/Material'
import { formatDateTime } from '../../utils/format'
import { roleAllows, useOperatorContext, type OperatorRole } from '../../store/operatorContext'

type AutoPaperFormState = {
  enabled: boolean
  newSymbol: string
  initialBuySignal: string
  finalSellSignal: string
  initialCash: string
  minOrderValue: string
  commissionRatePct: string
  commissionMinFee: string
  commissionMinTradeValue: string
  stampDutyRatePct: string
  tickIntervalSeconds: string
  minOrderIntervalSeconds: string
  realtimeIntervalSeconds: string
  klineIntervalSeconds: string
  weeklyMonthlyIntervalSeconds: string
  useLlm: boolean
  maxLlmCallsPerDay: string
  minLlmIntervalMinutes: string
  autoFill: boolean
}

type AutoPaperNumericField = Extract<
  keyof AutoPaperFormState,
  | 'initialCash'
  | 'minOrderValue'
  | 'commissionRatePct'
  | 'commissionMinFee'
  | 'commissionMinTradeValue'
  | 'stampDutyRatePct'
  | 'tickIntervalSeconds'
  | 'minOrderIntervalSeconds'
  | 'realtimeIntervalSeconds'
  | 'klineIntervalSeconds'
  | 'weeklyMonthlyIntervalSeconds'
  | 'maxLlmCallsPerDay'
  | 'minLlmIntervalMinutes'
>

type AutoPaperNumericRule = {
  label: string
  min: number
  max?: number
  integer?: boolean
  unit?: string
}

type AutoPaperNumericValues = {
  initialCash: number
  minOrderValue: number
  commissionRatePct: number
  commissionMinFee: number
  commissionMinTradeValue: number
  stampDutyRatePct: number
  tickIntervalSeconds: number
  minOrderIntervalSeconds: number
  realtimeIntervalSeconds: number
  klineIntervalSeconds: number
  weeklyMonthlyIntervalSeconds: number
  maxLlmCallsPerDay: number
  minLlmIntervalMinutes: number
}

type AutoPaperFormValidationErrors = Partial<Record<AutoPaperNumericField, string>>

type SignalOpsResearchEvidenceNotice = {
  iterationId: string
  evidenceCount: number
  engineVerdict: string
  canAccept: boolean
  blockers: string[]
  evidenceUsage: 'supporting_only'
  supportingOnly: true
  simulationOnly: true
  isRealTrade: false
  strongConclusionAllowed: false
}

type EditableSignalState = {
  triggerConditions: string
  invalidationConditions: string
  reviewFields: string
  transitionTarget: SignalOpsStatus
  reviewNote: string
}

type ReviewQueueFilters = {
  risk: string
  status: string
  quality: string
  symbol: string
  source: string
}

type SignalOpsAutomationSummary = {
  managedStockCount: number
  pendingReviewCount: number
  healthStatus: string
  healthTone: 'default' | 'good' | 'warn' | 'bad'
  lastAutoReview: string
  lastExperimentValidation: string
  lastRandomValidation: string
  randomValidationEvidence: string
  randomValidationRan: boolean
  randomValidationApplied: boolean
  candidateStatus: string
  loopRunning: boolean
  simulationOnly: boolean
  isRealTrade: boolean
}

type SignalOpsReviewWindowState = {
  isOpen: boolean
  activeItem: SignalOpsReviewQueueItem | null
  pendingCount: number
  filteredCount: number
  totalCount: number
}

type SignalOpsManualInterventionGroup = {
  canWrite: boolean
  canOperate: boolean
  canManageConfig: boolean
  writeDisabledReason?: string
  operateDisabledReason?: string
  configDisabledReason?: string
}

type SignalOpsPoolOverview = {
  totalCash: number
  totalMarketValue: number
  totalFloatingPnl: number
  capitalBase: number
  totalAssets: number
  pnlRate: number | null
  holdingPnlRate: number | null
}

const DEFAULT_REVIEW_QUEUE_FILTERS: ReviewQueueFilters = {
  risk: 'ALL',
  status: 'ALL',
  quality: 'ALL',
  symbol: 'ALL',
  source: 'ALL',
}

const STATUS_FLOW: SignalOpsStatus[] = [
  'IDEA',
  'WATCH',
  'PAPER_TEST',
  'QUALIFIED',
  'TRADE_PLAN',
  'MANUAL_CONFIRMED',
  'EXECUTION_REVIEW',
  'PATCH_REQUIRED',
  'REVIEW_ONLY',
  'CLOSED',
]

const ORDER_PREVIEW_LIMIT = 5

const AUTO_PAPER_NUMERIC_RULES: Record<AutoPaperNumericField, AutoPaperNumericRule> = {
  initialCash: { label: '股票池资金', min: 1, unit: '元' },
  minOrderValue: { label: '最小下单金额', min: 0, unit: '元' },
  commissionRatePct: { label: '佣金率', min: 0, max: 5, unit: '%' },
  commissionMinFee: { label: '最低手续费', min: 0, unit: '元' },
  commissionMinTradeValue: { label: '最低计费金额', min: 0, unit: '元' },
  stampDutyRatePct: { label: '卖出印花税', min: 0, max: 5, unit: '%' },
  tickIntervalSeconds: { label: '跟进间隔', min: 5, integer: true, unit: '秒' },
  minOrderIntervalSeconds: { label: '最小下单间隔', min: 5, integer: true, unit: '秒' },
  realtimeIntervalSeconds: { label: '实时行情间隔', min: 1, integer: true, unit: '秒' },
  klineIntervalSeconds: { label: 'K 线间隔', min: 60, integer: true, unit: '秒' },
  weeklyMonthlyIntervalSeconds: { label: '周/月线间隔', min: 3600, integer: true, unit: '秒' },
  maxLlmCallsPerDay: { label: '每日 LLM 调用次数', min: 0, max: 200, integer: true, unit: '次' },
  minLlmIntervalMinutes: { label: 'LLM 最小间隔', min: 1, max: 1440, integer: true, unit: '分钟' },
}

const AUTO_PAPER_NUMERIC_FIELDS = Object.keys(AUTO_PAPER_NUMERIC_RULES) as AutoPaperNumericField[]

const DEFAULT_AUTO_CONFIG: AutoPaperTradingConfig = {
  enabled: false,
  automation_mode: 'SIMULATION',
  simulation_module: {
    name: 'simulation',
    enabled: true,
    execution_mode: 'PAPER',
    order_namespace: 'SIM_*',
    simulation_only: true,
    is_real_trade: false,
    status: 'ACTIVE',
  },
  live_module: {
    name: 'live',
    enabled: false,
    execution_enabled: false,
    order_router: 'DISABLED',
    broker_profile_id: '',
    account_id: '',
    max_order_value: 0,
    max_position_ratio: 0,
    require_manual_confirmation: true,
    require_kill_switch_clear: true,
    status: 'CONFIGURED_DISABLED',
    simulation_only: true,
    is_real_trade: false,
  },
  symbol: '',
  stock_name: '',
  signal_id: null,
  signal_ids: {},
  initial_buy_signal: '',
  final_sell_signal: '',
  initial_buy_signals: {},
  final_sell_signals: {},
  initial_cash: 100000,
  max_position_ratio: 0.5,
  min_order_value: 1000,
  commission_rate: 0.0001,
  commission_min_fee: 5,
  commission_min_trade_value: 50000,
  stamp_duty_rate: 0.0005,
  realtime_interval_seconds: 30,
  kline_interval_seconds: 300,
  weekly_monthly_interval_seconds: 86400,
  tick_interval_seconds: 60,
  min_order_interval_seconds: 900,
  use_llm: true,
  max_llm_calls_per_day: 6,
  min_llm_interval_minutes: 120,
  auto_fill: true,
  adaptive_tuning_enabled: true,
  buy_change_threshold_pct: 0.5,
  close_change_threshold_pct: -2,
  watch_position_ratio: 0.15,
  probe_position_ratio: 0.35,
  positive_position_ratio: 0.5,
  breakout_position_ratio: 0.65,
  defensive_position_ratio: 0.25,
  existing_position_ratio: 0.45,
  strength_follow_position_ratio: 0.65,
  factor_adjustments: {},
  performance_stats: {},
  last_research_review_date: '',
  last_research_review: {},
  updated_at: '',
  last_tick_at: '',
  last_market_fetch_at: '',
  last_kline_fetch_at: '',
  last_weekly_monthly_fetch_at: '',
  last_llm_at: '',
  last_order_at: '',
  last_market_fetch_by_symbol: {},
  last_kline_fetch_by_symbol: {},
  last_weekly_monthly_fetch_by_symbol: {},
  last_kline_snapshot_by_symbol: {},
  last_order_by_symbol: {},
  llm_budget_date: '',
  llm_calls_used_today: 0,
  llm_gate_status: '',
  last_llm_close_call_date: '',
  last_decision: {},
  last_module_evidence: {},
  last_portfolio_snapshot: {},
  last_tick_result: {},
  cleaned_record_history: [],
  review_queue_state: { version: 1, items: [], observations: [], counts: {}, simulation_only: true, is_real_trade: false },
  review_decisions: [],
  experiment_validation_state: { version: 1, attempts: {}, counts: {}, simulation_only: true, is_real_trade: false },
  random_validation_state: { version: 1, attempts: [], counts: {}, simulation_only: true, is_real_trade: false },
  decision_tree_state: { version: 1, symbols: {}, tuning_audit: [], simulation_only: true, is_real_trade: false },
  last_success_at: '',
  last_error: '',
  storage_warning: '',
}

function messageOf(error: unknown) {
  return displayMessage(error instanceof Error ? error.message : String(error || '未知错误'))
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function firstNonEmptyRecord(...values: unknown[]): Record<string, unknown> {
  for (const value of values) {
    const record = asRecord(value)
    if (Object.keys(record).length > 0) return record
  }
  return {}
}

function firstNonEmptyArray<T>(...values: Array<T[] | undefined | null>): T[] {
  for (const value of values) {
    if (Array.isArray(value) && value.length > 0) return value
  }
  return []
}

function isSkippedReview(value: unknown) {
  return String(asRecord(value).status || '').trim().toUpperCase() === 'SKIPPED'
}

function latestCompletedReview(currentReview: unknown, ...persistedReviews: unknown[]) {
  const current = asRecord(currentReview)
  if (Object.keys(current).length > 0 && !isSkippedReview(current)) return current
  return firstNonEmptyRecord(...persistedReviews, current)
}

function splitList(value: string) {
  return value
    .replace(/[;\n]/g, ',')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

function uniqueListInOrder(values: unknown[]) {
  const seen = new Set<string>()
  const result: string[] = []
  values.forEach((value) => {
    const normalized = String(value || '').trim()
    if (!normalized || seen.has(normalized)) return
    seen.add(normalized)
    result.push(normalized)
  })
  return result
}

function managedSymbolsFromConfig(config: Pick<AutoPaperTradingConfig, 'symbol' | 'signal_ids'>) {
  return uniqueListInOrder([
    ...splitList(config.symbol || ''),
    ...Object.keys(config.signal_ids || {}),
  ])
}

function listToText(value?: string[]) {
  return Array.isArray(value) ? value.join('\n') : ''
}

function textToList(value: string) {
  return value
    .split(/\n|,/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function compactId(value?: string | null) {
  const normalized = String(value || '').trim()
  if (!normalized) return '-'
  return normalized.length > 14 ? `${normalized.slice(0, 7)}...${normalized.slice(-5)}` : normalized
}

function numericFieldHelp(field: AutoPaperNumericField) {
  const rule = AUTO_PAPER_NUMERIC_RULES[field]
  const range = rule.max === undefined ? `不小于 ${rule.min}` : `${rule.min} - ${rule.max}`
  return `${range}${rule.unit || ''}${rule.integer ? '，请输入整数' : ''}`
}

function parseAutoPaperNumericField(value: string, rule: AutoPaperNumericRule) {
  const normalized = value.trim()
  if (!normalized) {
    return { error: `${rule.label}不能为空。` }
  }
  const parsed = Number(normalized)
  if (!Number.isFinite(parsed)) {
    return { error: `${rule.label}请输入有效数字。` }
  }
  if (parsed < rule.min) {
    return { error: `${rule.label}不能小于 ${rule.min}${rule.unit || ''}。` }
  }
  if (rule.max !== undefined && parsed > rule.max) {
    return { error: `${rule.label}不能大于 ${rule.max}${rule.unit || ''}。` }
  }
  if (rule.integer && !Number.isInteger(parsed)) {
    return { error: `${rule.label}必须是整数。` }
  }
  return { value: parsed }
}

function validateAutoPaperNumericInputs(form: AutoPaperFormState) {
  const values: Partial<AutoPaperNumericValues> = {}
  const errors: AutoPaperFormValidationErrors = {}
  AUTO_PAPER_NUMERIC_FIELDS.forEach((field) => {
    const result = parseAutoPaperNumericField(form[field], AUTO_PAPER_NUMERIC_RULES[field])
    if (result.error) {
      errors[field] = result.error
    } else {
      values[field] = result.value
    }
  })
  return { values: values as AutoPaperNumericValues, errors }
}

function fmtNumber(value: unknown, digits = 2) {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return '-'
  return parsed.toLocaleString(undefined, { maximumFractionDigits: digits })
}

function fmtMoney(value: unknown) {
  return fmtNumber(value, 2)
}

function fmtSignedMoney(value: unknown) {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return '-'
  if (parsed > 0) return `+${fmtMoney(parsed)}`
  if (parsed < 0) return `-${fmtMoney(Math.abs(parsed))}`
  return fmtMoney(0)
}

function pnlTone(value: unknown): 'default' | 'good' | 'bad' {
  const parsed = Number(value)
  if (!Number.isFinite(parsed) || parsed === 0) return 'default'
  return parsed > 0 ? 'good' : 'bad'
}

function poolCapitalBase(config: AutoPaperTradingConfig, portfolios: PaperPortfolioItem[]) {
  const configured = Number(config.initial_cash)
  if (Number.isFinite(configured) && configured > 0) return configured
  return portfolios.reduce((sum, item) => sum + Number(item.initial_cash || 0), 0)
}

function rateToPercentText(value: unknown) {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return '0.01'
  return String(Number((parsed * 100).toFixed(6)))
}

function fmtDate(value?: string | null) {
  return value ? formatDateTime(value) : '-'
}

function fmtDateOrLabel(value: unknown, fallback = '未运行') {
  const normalized = String(value || '').trim()
  return normalized ? fmtDate(normalized) : fallback
}

function queueCountSummary(queueCounts: Record<string, unknown>, reviewQueue: SignalOpsReviewQueueItem[]) {
  const explicitEntries = Object.entries(queueCounts)
    .filter(([, value]) => Number.isFinite(Number(value)) && Number(value) > 0)
  if (explicitEntries.length) {
    return explicitEntries.map(([key, value]) => `${displayCode(key)} ${fmtNumber(value, 0)}`).join(' / ')
  }
  if (!reviewQueue.length) return '暂无队列项目'

  const derived = new Map<string, number>()
  reviewQueue.forEach((item) => {
    const status = String(item.candidate_status || item.lifecycle_status || item.status || '').trim().toUpperCase()
    if (!status) return
    derived.set(status, (derived.get(status) || 0) + 1)
  })
  const summary = Array.from(derived.entries()).map(([key, value]) => `${displayCode(key)} ${value}`)
  return summary.length ? summary.join(' / ') : `总数 ${reviewQueue.length}`
}

type StockNameSources = {
  signals?: SignalItem[]
  tickResult?: AutoPaperTradingTickResult | null
  statusLastTickResult?: Record<string, unknown> | null
}

const STOCK_NAME_DISPLAY_LABELS: Record<string, string> = {
  'SignalOps Browser Smoke': '浏览器烟测样本',
}

function symbolToken(value: unknown) {
  const normalized = String(value || '').trim().toUpperCase().replace(/\.(SH|SZ|BJ)$/i, '')
  return normalized.replace(/[^A-Z0-9]/g, '')
}

function isSymbolNamePlaceholder(symbol: string, name?: string | null) {
  const stockName = String(name || '').trim()
  if (!stockName) return true
  const token = symbolToken(symbol)
  const nameToken = String(stockName).trim().toUpperCase().replace(/[^A-Z0-9]/g, '')
  if (!token || !nameToken) return false
  return [token, `${token}SH`, `${token}SZ`, `${token}BJ`].includes(nameToken)
}

function addStockName(nameBySymbol: Map<string, string>, symbol: unknown, name: unknown) {
  const key = symbolToken(symbol)
  const stockName = String(name || '').trim()
  if (!key || isSymbolNamePlaceholder(String(symbol || ''), stockName)) return
  const currentName = nameBySymbol.get(key)
  if (!currentName || isSymbolNamePlaceholder(String(symbol || ''), currentName)) {
    nameBySymbol.set(key, STOCK_NAME_DISPLAY_LABELS[stockName] || stockName)
  }
}

function addStockNamesFromTickResult(nameBySymbol: Map<string, string>, value: unknown) {
  const root = asRecord(value)
  const results = Array.isArray(root.results) ? root.results : []
  results.forEach((item) => addStockNamesFromTickResult(nameBySymbol, item))

  const marketSnapshot = asRecord(root.market_snapshot)
  const quote = asRecord(marketSnapshot.quote)
  const directQuote = Object.keys(quote).length ? quote : asRecord(root.quote)
  const symbol = root.symbol || marketSnapshot.symbol || directQuote.symbol
  addStockName(
    nameBySymbol,
    symbol,
    directQuote.name || directQuote.stockName || directQuote.stock_name || directQuote.securityName,
  )
}

function stockNamesForSymbols(config: AutoPaperTradingConfig, symbols: string[], sources: StockNameSources = {}) {
  const currentSymbols = managedSymbolsFromConfig(config)
  const currentNames = splitList(config.stock_name || '')
  const nameBySymbol = new Map<string, string>()
  currentSymbols.forEach((symbol, index) => {
    const matchedName = currentNames[index] || (currentSymbols.length === 1 ? currentNames[0] : '')
    addStockName(nameBySymbol, symbol, matchedName)
  })
  sources.signals?.forEach((signal) => addStockName(nameBySymbol, signal.symbol, signal.stock_name))
  addStockNamesFromTickResult(nameBySymbol, sources.statusLastTickResult)
  addStockNamesFromTickResult(nameBySymbol, sources.tickResult)
  return symbols.map((symbol) => nameBySymbol.get(symbolToken(symbol)) || symbol)
}

function selectableSignalId(preferredSignalId: unknown, config: AutoPaperTradingConfig, signalList: SignalItem[]) {
  const liveIds = new Set(signalList.map((signal) => signal.signal_id).filter(Boolean))
  const preferred = String(preferredSignalId || '').trim()
  if (preferred && liveIds.has(preferred)) return preferred
  const configSignalId = String(config.signal_id || '').trim()
  if (configSignalId && liveIds.has(configSignalId)) return configSignalId
  for (const symbol of managedSymbolsFromConfig(config)) {
    const matched = signalList.find((signal) => symbolToken(signal.symbol) === symbolToken(symbol))
    if (matched?.signal_id) return matched.signal_id
  }
  return signalList[0]?.signal_id || ''
}

function isSignalNotFoundError(error: unknown) {
  return String(error instanceof Error ? error.message : error || '').toLowerCase().includes('signal not found')
}

function symbolTextMapWithAdditions(existing: Record<string, string> | undefined, symbols: string[], value: string) {
  const text = value.trim()
  const next = { ...(existing || {}) }
  if (!text) return next
  symbols.forEach((symbol) => {
    next[symbol] = text
  })
  return next
}

function configToForm(config: AutoPaperTradingConfig): AutoPaperFormState {
  return {
    enabled: Boolean(config.enabled),
    newSymbol: '',
    initialBuySignal: String(config.initial_buy_signal || ''),
    finalSellSignal: String(config.final_sell_signal || ''),
    initialCash: String(config.initial_cash ?? 100000),
    minOrderValue: String(config.min_order_value ?? 1000),
    commissionRatePct: rateToPercentText(config.commission_rate ?? 0.0001),
    commissionMinFee: String(config.commission_min_fee ?? 5),
    commissionMinTradeValue: String(config.commission_min_trade_value ?? 50000),
    stampDutyRatePct: rateToPercentText(config.stamp_duty_rate ?? 0.0005),
    tickIntervalSeconds: String(config.tick_interval_seconds ?? 60),
    minOrderIntervalSeconds: String(config.min_order_interval_seconds ?? 900),
    realtimeIntervalSeconds: String(config.realtime_interval_seconds ?? 30),
    klineIntervalSeconds: String(config.kline_interval_seconds ?? 300),
    weeklyMonthlyIntervalSeconds: String(config.weekly_monthly_interval_seconds ?? 86400),
    useLlm: Boolean(config.use_llm),
    maxLlmCallsPerDay: String(config.max_llm_calls_per_day ?? 6),
    minLlmIntervalMinutes: String(config.min_llm_interval_minutes ?? 120),
    autoFill: Boolean(config.auto_fill),
  }
}

function editableFromSignal(signal?: SignalItem | null): EditableSignalState {
  return {
    triggerConditions: listToText(signal?.trigger_conditions),
    invalidationConditions: listToText(signal?.invalidation_conditions),
    reviewFields: listToText(signal?.review_fields),
    transitionTarget: signal?.status || 'PAPER_TEST',
    reviewNote: '',
  }
}

function extractDecisionCard(value: unknown): SignalOpsDecisionCard {
  const root = asRecord(value)
  const direct = asRecord(root.decision_card)
  if (Object.keys(direct).length) return direct as SignalOpsDecisionCard
  const decision = asRecord(root.decision)
  const decisionCard = asRecord(decision.decision_card)
  if (Object.keys(decisionCard).length) return decisionCard as SignalOpsDecisionCard
  const order = asRecord(root.order)
  const orderCard = asRecord(order.decision_card)
  if (Object.keys(orderCard).length) return orderCard as SignalOpsDecisionCard
  const riskConstraints = asRecord(order.risk_constraints)
  return asRecord(riskConstraints.decision_card) as SignalOpsDecisionCard
}

function firstDecisionCard(...values: unknown[]) {
  for (const value of values) {
    const card = extractDecisionCard(value)
    if (card.action) return card
  }
  return {} as SignalOpsDecisionCard
}

function paperOrderWarnings(order: PaperOrderItem) {
  const riskConstraints = asRecord(order.risk_constraints)
  const fill = asRecord(order.simulated_fill)
  const warnings = [
    ...(Array.isArray(riskConstraints.paper_gate_warnings) ? riskConstraints.paper_gate_warnings : []),
    ...(Array.isArray(fill.paper_gate_warnings) ? fill.paper_gate_warnings : []),
  ]
  return warnings.map(String).filter(Boolean)
}

function buildPaperOrderGovernance(order: PaperOrderItem) {
  const action = String(order.action || '').toUpperCase()
  const fillStatus = String(order.fill_status || '').toUpperCase()
  const warnings = paperOrderWarnings(order)
  const hasIds = Boolean(order.order_id && order.signal_id && order.audit_id)
  const simulationOnly = order.simulation_only === true
  const isRealTrade = order.is_real_trade === true
  const boundaryBroken = !simulationOnly || isRealTrade
  const actionInSimNamespace = action.startsWith('SIM_')
  const fillBlocked = Boolean(fillStatus && !['FILLED', 'OBSERVED', 'SKIPPED'].includes(fillStatus))

  let blocker = '无阻断，保持人工复核'
  if (boundaryBroken) {
    blocker = 'SignalOps paper order simulation-only boundary violated'
  } else if (!actionInSimNamespace) {
    blocker = 'Paper order action must stay in SIM_* namespace'
  } else if (!hasIds) {
    blocker = '缺少 order/signal/audit ID'
  } else if (warnings.length > 0) {
    blocker = `Paper gate warning: ${warnings[0]}`
  } else if (fillBlocked) {
    blocker = `模拟成交状态 ${fillStatus}`
  }

  const nextAction = boundaryBroken || !actionInSimNamespace
    ? '停止沉淀，先修复 SignalOps simulation-only 边界'
    : !hasIds
      ? '补齐 order/signal/audit 链接后再进入案例复盘'
      : warnings.length > 0 || fillBlocked
        ? '先复核 paper gate / 模拟成交状态'
        : '可进入 Case / Backtest / Research Lab 仅模拟复核'

  return {
    contextId: order.order_id || order.audit_id || order.signal_id || 'pending-paper-order',
    evidenceStrength: 'LOW',
    evidenceUsage: 'simulation_only',
    strongConclusionAllowed: false,
    blocker,
    nextAction,
    simulationOnly,
    isRealTrade,
  }
}

function typedDecisionTreeState(value: unknown): SignalOpsDecisionTreeState {
  const state = asRecord(value)
  return {
    ...state,
    symbols: asRecord(state.symbols) as SignalOpsDecisionTreeState['symbols'],
    tuning_audit: Array.isArray(state.tuning_audit) ? state.tuning_audit as SignalOpsDecisionTreeState['tuning_audit'] : [],
  } as SignalOpsDecisionTreeState
}

function compactDateValue(value: unknown) {
  const normalized = String(value || '').trim()
  return normalized || '-'
}

function compressedObservationCount(value: unknown) {
  const summary = asRecord(value)
  return numericValue(summary.total_count) ?? numericValue(summary.compressed_count) ?? 0
}

function compressedObservationSymbolCount(value: unknown, symbol: string) {
  const summary = asRecord(value)
  const bySymbol = asRecord(summary.by_symbol)
  const item = asRecord(bySymbol[symbol])
  return numericValue(item.count) ?? numericValue(bySymbol[symbol]) ?? 0
}

function compressedObservationWindow(value: unknown) {
  const byDate = asRecord(asRecord(value).by_date)
  const dates = Object.keys(byDate).filter(Boolean).sort()
  if (!dates.length) return '-'
  return dates.length === 1 ? dates[0] : `${dates[0]} -> ${dates[dates.length - 1]}`
}

function decisionTreeReviewCounts(review: SignalOpsDecisionTreeReview | Record<string, unknown>) {
  const counts = asRecord(review.counts)
  return {
    correct: Number(counts.correct ?? review.correct_count ?? 0) || 0,
    wrong: Number(counts.wrong ?? review.wrong_count ?? 0) || 0,
    partial: Number(counts.partial ?? review.partial_count ?? 0) || 0,
    skipped: Number(counts.skipped ?? review.skipped_count ?? 0) || 0,
  }
}

function decisionTreeBranches(tree: SignalOpsDecisionTree | Record<string, unknown>): SignalOpsDecisionTreeBranch[] {
  const branches = Array.isArray(tree.branches) ? tree.branches : []
  return branches.map((item) => asRecord(item) as SignalOpsDecisionTreeBranch)
}

function latestDecisionTreeReview(
  state: SignalOpsDecisionTreeState,
  tickResult: AutoPaperTradingTickResult | null,
  dailyReview: AutoPaperTradingDailyReviewResult | null,
): SignalOpsDecisionTreeReview {
  const fromTick = asRecord(tickResult?.decision_tree_review) as SignalOpsDecisionTreeReview
  if (Object.keys(fromTick).length) return fromTick
  const dailyReviews = Array.isArray(dailyReview?.decision_tree_reviews) ? dailyReview.decision_tree_reviews : []
  if (dailyReviews.length) return asRecord(dailyReviews[dailyReviews.length - 1]) as SignalOpsDecisionTreeReview
  const symbols = Object.values(asRecord(state.symbols))
    .map((item) => asRecord(item))
    .sort((left, right) => String(right.updated_at || '').localeCompare(String(left.updated_at || '')))
  for (const symbolState of symbols) {
    const lastReview = asRecord(symbolState.last_review) as SignalOpsDecisionTreeReview
    if (Object.keys(lastReview).length) return lastReview
    const latestClosed = asRecord(symbolState.latest_closed_tree)
    const closedReview = asRecord(latestClosed.review) as SignalOpsDecisionTreeReview
    if (Object.keys(closedReview).length) return closedReview
  }
  return {} as SignalOpsDecisionTreeReview
}

function extractKlineQuality(value: unknown): KlineSignalQuality {
  const root = asRecord(value)
  const direct = asRecord(root.kline_signal_quality)
  if (Object.keys(direct).length) return direct as KlineSignalQuality
  const preBuy = asRecord(root.pre_buy_quality)
  const preBuyDirect = asRecord(preBuy.kline_signal_quality)
  if (Object.keys(preBuyDirect).length) return preBuyDirect as KlineSignalQuality
  const components = asRecord(preBuy.components)
  const component = asRecord(components.kline_signal_quality)
  if (Object.keys(component).length) return component as KlineSignalQuality
  const card = extractDecisionCard(value)
  const cardDirect = asRecord(card.kline_signal_quality)
  if (Object.keys(cardDirect).length) return cardDirect as KlineSignalQuality
  const cardPreBuy = asRecord(card.pre_buy_quality)
  const cardComponents = asRecord(cardPreBuy.components)
  return asRecord(cardComponents.kline_signal_quality) as KlineSignalQuality
}

function klineEvidencePackage(value: unknown): KlineEvidencePackage {
  const root = asRecord(value)
  const direct = asRecord(root.kline_evidence_package)
  if (Object.keys(direct).length) return direct as KlineEvidencePackage
  const evidence = asRecord(root.evidence_package)
  return asRecord(evidence.kline_evidence_package) as KlineEvidencePackage
}

function klineQualityFromItem(item: SignalOpsReviewQueueItem): KlineSignalQuality {
  const packageQuality = asRecord(item.kline_evidence_package?.kline_signal_quality)
  if (Object.keys(packageQuality).length) return packageQuality as KlineSignalQuality
  const cardQuality = extractKlineQuality(item.decision_card)
  if (Object.keys(cardQuality).length) return cardQuality
  const candidateConfig = asRecord(item.strategy_experiment?.candidate_config)
  const strategy = asRecord(candidateConfig.kline_strategy)
  const ladder = asRecord(candidateConfig.ladder_buy_policy)
  if (Object.keys(strategy).length || Object.keys(ladder).length) {
    return {
      kline_strategy: strategy,
      ladder_buy_policy: ladder,
      action_policy: String((ladder as Record<string, unknown>).stage || ''),
    }
  }
  return {} as KlineSignalQuality
}

function extractStrategyStabilityQuality(value: unknown): StrategyStabilityQuality {
  const root = asRecord(value)
  const direct = asRecord(root.strategy_stability_quality)
  if (Object.keys(direct).length) return direct as StrategyStabilityQuality
  const preBuy = asRecord(root.pre_buy_quality)
  const preBuyDirect = asRecord(preBuy.strategy_stability_quality)
  if (Object.keys(preBuyDirect).length) return preBuyDirect as StrategyStabilityQuality
  const components = asRecord(preBuy.components)
  const component = asRecord(components.strategy_stability_quality)
  if (Object.keys(component).length) return component as StrategyStabilityQuality
  const card = extractDecisionCard(value)
  const cardDirect = asRecord(card.strategy_stability_quality)
  if (Object.keys(cardDirect).length) return cardDirect as StrategyStabilityQuality
  const cardPreBuy = asRecord(card.pre_buy_quality)
  const cardComponents = asRecord(cardPreBuy.components)
  return asRecord(cardComponents.strategy_stability_quality) as StrategyStabilityQuality
}

function stabilityEvidencePackage(value: unknown): StabilityEvidencePackage {
  const root = asRecord(value)
  const direct = asRecord(root.stability_evidence_package)
  if (Object.keys(direct).length) return direct as StabilityEvidencePackage
  const evidence = asRecord(root.evidence_package)
  return asRecord(evidence.stability_evidence_package) as StabilityEvidencePackage
}

function stabilityQualityFromItem(item: SignalOpsReviewQueueItem): StrategyStabilityQuality {
  const packageQuality = asRecord(item.stability_evidence_package?.strategy_stability_quality)
  if (Object.keys(packageQuality).length) return packageQuality as StrategyStabilityQuality
  const cardQuality = extractStrategyStabilityQuality(item.decision_card)
  if (Object.keys(cardQuality).length) return cardQuality
  const candidateConfig = asRecord(item.strategy_experiment?.candidate_config)
  const strategy = asRecord(candidateConfig.stability_strategy)
  const meta = asRecord(candidateConfig.meta_label_gate)
  const sizing = asRecord(candidateConfig.volatility_sizing_policy)
  if (Object.keys(strategy).length || Object.keys(meta).length || Object.keys(sizing).length) {
    return {
      stability_strategy: strategy,
      meta_label_gate: meta,
      volatility_sizing_policy: sizing,
      action_policy: String((meta as Record<string, unknown>).action_policy || ''),
    }
  }
  return {} as StrategyStabilityQuality
}

function latestOrder(orders: PaperOrderItem[]) {
  return [...orders].sort((a, b) => (b.updated_at || b.created_at).localeCompare(a.updated_at || a.created_at))[0]
}

function commandLabel(command: AutoPaperTradingCommandResult['status'] | string) {
  return displayCode(command)
}

const STATUS_LABELS: Record<string, string> = {
  IDEA: '想法',
  WATCH: '观察',
  PAPER_TEST: '模拟测试',
  QUALIFIED: '已验证',
  TRADE_PLAN: '交易计划',
  MANUAL_CONFIRMED: '人工确认',
  EXECUTION_REVIEW: '执行复核',
  PATCH_REQUIRED: '需要修正',
  REVIEW_ONLY: '仅复核',
  CLOSED: '已关闭',
  CREATED: '已创建',
  RUNNING: '运行中',
  COMPLETED: '已完成',
  ACTIVE: '运行中',
  SIMULATION: '模拟',
  LIVE: '实盘',
  CONFIGURED_DISABLED: '已配置但停用',
  SIGNALOPS_SIM: 'SignalOps模拟',
  BLOCKED: '已阻断',
  SKIPPED: '已跳过',
  FAILED: '失败',
  ERROR: '错误',
  STOPPED: '已停止',
  HEALTHY: '健康',
  READY: '就绪',
  PASS: '通过',
  WAIT: '等待',
  WARN: '警告',
  PASS_REVIEW: '通过审查',
  REJECT_SUGGESTION: '驳回建议',
  KEEP_WATCH: '继续观察',
  REQUEST_PATCH: '要求补丁',
  READY_FOR_REVIEW: '待审查',
  BACKTEST_PENDING: '验证中',
  RECOMMENDED_ONLY: '仅建议',
  APPLIED_TO_SIMULATION: '已应用到模拟',
  REJECTED: '已驳回',
  SUPERSEDED: '已被替代',
  EXPIRED: '已过期',
  AVAILABLE: '可用',
  UNAVAILABLE: '不可用',
  STRONG: '强证据',
  MEDIUM: '中等证据',
  LOW: '低质量',
  SUPPORTING_ONLY: '仅支持证据',
  HIGH: '高',
  PROBE: '小仓试探',
  CONFIRM: '确认加仓',
  FOLLOW_THROUGH: '跟随加仓',
  INVALIDATE: '失效',
  LADDER_BUY: '阶梯模拟',
  OBSERVE: '观察',
  DOWN_TREND: '下跌趋势',
  BASE_BUILDING: '筑底观察',
  RECOVERY_TREND: '修复趋势',
  BOTTOM_CANDIDATE: '底部候选',
  COMPRESSED: '波动压缩',
  BREAKOUT_CONFIRMED: '放量突破',
  SHRINK_STOP: '缩量止跌',
  ALIGNED: '多周期共振',
  DIVERGED: '周期分歧',
  TREND_UP: '趋势向上',
  RANGE: '区间震荡',
  DOWNTREND: '下跌状态',
  HIGH_VOL_STRESS: '高波动压力',
  RECOVERY_CONFIRMED: '修复确认',
  REDUCE: '降级限仓',
  BLOCK: '阻断',
  INSUFFICIENT_SAMPLE: '样本不足',
  READ_ONLY_NO_PERMISSION_CHANGE: '只读，不改权限',
  READ_ONLY_NO_REAL_TRADE_PERMISSION_CHANGE: '只读，不改实盘权限',
  RESEARCH_ONLY_NO_PERMISSION_CHANGE: '研究证据，不改权限',
  UNLABELED_NOWCAST_PROXY_ONLY: '未标注 nowcast 代理',
  UNLABELED_NOWCAST: '未标注 nowcast',
  LABELED_HISTORICAL_ONLY_NOWCAST_EXCLUDED: '仅历史标签，排除 nowcast',
  THROTTLE: '模拟限仓',
  AVOID_NEW_BUY: '阻止新买入',
  REVIEW_SIMULATION_ONLY: '仅模拟复核',
  SIMULATION_REDUCE_OR_REVIEW_ONLY: '模拟减仓或复核',
  REVIEW_SIMULATION_ONLY_INSUFFICIENT_CALIBRATION: '校准不足，仅模拟复核',
  SIMULATION_CONFIDENCE_SUPPORT_ONLY: '仅置信支持',
  SIMULATION_NEUTRAL_REVIEW: '中性复核',
  YES: '是',
  NO: '否',
}

const REVIEW_DECISION_LABELS: Record<SignalOpsReviewDecision, string> = {
  PASS_REVIEW: '通过审查',
  REJECT_SUGGESTION: '驳回建议',
  KEEP_WATCH: '继续观察',
  REQUEST_PATCH: '要求补丁',
}

const ACTION_LABELS: Record<string, string> = {
  SIM_BUY: '模拟买入',
  SIM_SELL: '模拟卖出',
  SIM_HOLD: '模拟观望',
  SIM_CLOSE: '模拟平仓',
  SIM_SHORT: '模拟做空',
  SIM_COVER: '模拟回补',
  SIM_T_BUY: '模拟做 T 买回',
  SIM_T_SELL: '模拟做 T 卖出',
  SIM_REBALANCE: '模拟调仓',
  FORCE_OPEN_BUY: '强制 AI 开仓',
  FORCE_CLOSE: '强制平仓',
  REMOVE_SYMBOL: '移出股票池',
  FORCE_CLOSE_AND_REMOVE: '平仓并移除',
  REVIEWED: '已复核',
}

const TUNING_PARAM_LABELS: Record<string, string> = {
  buy_change_threshold_pct: '买入触发阈值',
  close_change_threshold_pct: '失效平仓阈值',
  watch_position_ratio: '观察仓位',
  probe_position_ratio: '试探仓位',
  positive_position_ratio: '正向仓位',
  breakout_position_ratio: '突破仓位',
  defensive_position_ratio: '防守仓位',
  existing_position_ratio: '已有持仓仓位',
  strength_follow_position_ratio: '强势跟随仓位',
}

const MESSAGE_LABELS: Record<string, string> = {
  'Auto paper config saved.': '自动模拟交易配置已保存。',
  'Auto paper command completed.': '沙箱控制指令已完成。',
  'Forced open buy was not placed.': '强制 AI 开仓未生成模拟订单。',
  'Forced close was not placed.': '强制平仓未生成模拟订单。',
  'Unsupported auto paper command.': '不支持的沙箱控制指令。',
  'Symbol is required.': '请先填写股票代码。',
  'Symbol is not in the auto paper stock pool.': '该股票不在自动模拟股票池中。',
  'No active analysis run is selected.': '当前没有选中的分析运行。',
  'Select a signal first.': '请先选择一个信号。',
  'Signal conditions updated.': '信号条件已更新。',
  'Manual review recorded.': '人工复核已记录。',
  'Paper portfolio created.': '模拟组合已创建。',
  'Manual SignalOps review.': '人工 SignalOps 复核。',
  'SignalOps LLM may judge only after deterministic module evidence is computed.': 'SignalOps 大模型仅在确定性模块证据计算完成后判断。',
  quant_core_path_risk_avoid_new_buy: '量化核心 MFE/MAE 路径风险阻断新买入',
  quant_core_path_risk_throttle: '量化核心 MFE/MAE 路径风险压缩新仓位',
  a_share_t_plus_one_blocked: 'A 股 T+1 阻断：当天买入的股票不能当天卖出。',
  a_share_trading_session_closed: 'A 股交易时段阻断：自动模拟下单只在 09:30-11:30、13:00-15:00 执行。',
  a_share_limit_up_buy_blocked: 'A 股涨停方向阻断：接近涨停时不追买或回补。',
  a_share_limit_down_sell_blocked: 'A 股跌停方向阻断：接近跌停时不卖出或开空。',
  insufficient_simulated_cash: '模拟现金不足，已计入手续费后无法成交。',
  insufficient_trade_count: '训练样本不足',
  insufficient_evidence_weight: '证据权重不足',
  insufficient_confidence: '置信度不足',
  insufficient_validation_trade_count: '验证样本不足',
  overlapping_or_missing_walk_forward_windows: '样本窗口重叠或缺失',
  low_quality_evidence: '证据质量偏低',
  validation_win_rate_declined: '验证胜率下降',
  validation_expectancy_not_improved: '期望收益未改善',
  validation_drawdown_worsened: '验证回撤恶化',
  validation_after_cost_not_positive: '扣费后收益未转正',
  validation_direction_not_confirmed: '验证方向未确认',
}

function displayCode(value: unknown) {
  const normalized = String(value || '').trim()
  if (!normalized) return '-'
  return ACTION_LABELS[normalized] || STATUS_LABELS[normalized] || normalized
}

function displayModuleName(value: unknown) {
  const normalized = String(value || '').trim()
  if (!normalized) return '-'
  return displayCode(normalized.toUpperCase())
}

function displayMessage(value?: string | null): string {
  const message = String(value || '').trim()
  if (!message) return ''
  if (MESSAGE_LABELS[message]) return MESSAGE_LABELS[message]
  const dailyAlready = message.match(/^SignalOps daily review already ran for (.+)\.$/)
  if (dailyAlready) return `SignalOps 已在 ${dailyAlready[1]} 完成过收盘复盘。`
  const dailyCompleted = message.match(/^SignalOps daily review completed for (.+)\.$/)
  if (dailyCompleted) return `SignalOps 已完成 ${dailyCompleted[1]} 的收盘复盘。`
  const noPaperRecords = message.match(/^No SignalOps paper records were available for (.+)\.$/)
  if (noPaperRecords) return `${noPaperRecords[1]} 没有可用于复盘的 SignalOps 模拟记录。`
  const poolTick = message.match(/^auto_paper_pool_tick_(\w+): (\d+) of (\d+) symbols failed\.$/)
  if (poolTick) return `自动模拟股票池跟进${displayCode(poolTick[1].toUpperCase())}：${poolTick[2]}/${poolTick[3]} 只股票失败。`
  if (message.startsWith('order_error:')) return `订单阻断：${displayMessage(message.replace('order_error:', ''))}`
  if (message.startsWith('portfolio_error:')) return `模拟组合异常：${displayMessage(message.replace('portfolio_error:', ''))}`
  if (message.startsWith('Tick ')) return `单次跟进：${displayCode(message.slice(5))}`
  if (message.startsWith('Daily review ')) return `收盘复盘：${displayCode(message.slice(13))}`
  if (message.startsWith('Signal moved to ')) return `信号已流转到${displayCode(message.replace(/^Signal moved to /, '').replace(/\.$/, ''))}。`
  if (message.startsWith('Paper order promoted to case: ')) return `模拟订单已沉淀为案例：${message.replace('Paper order promoted to case: ', '')}`
  if (message.startsWith('Signal created: ')) return message.replace('Signal created:', '信号已创建：')
  return message
}

function splitReasonList(value?: string | null) {
  return String(value || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

function compactReasonLabel(value?: string | null) {
  const reasons = splitReasonList(value)
  if (reasons.length <= 1) {
    const label = displayMessage(value)
    return { summary: label || '-', detail: label || '-' }
  }
  const labels = reasons.map(displayMessage)
  return {
    summary: `${labels[0]}等 ${labels.length} 项`,
    detail: labels.join('、'),
  }
}

function CompactReason({ value }: { value?: string | null }) {
  const reason = compactReasonLabel(value)
  return (
    <span className="block max-w-full truncate" title={reason.detail} aria-label={reason.detail}>
      {reason.summary}
    </span>
  )
}

function yesNo(value: boolean) {
  return value ? '是' : '否'
}

function numericValue(value: unknown) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function fmtTuningValue(key: string, value: unknown) {
  const parsed = numericValue(value)
  if (parsed === null) return '-'
  if (key.includes('_ratio')) return `${fmtNumber(parsed * 100, 2)}%`
  if (key.includes('_pct')) return `${fmtNumber(parsed, 2)}%`
  return fmtNumber(parsed, 4)
}

type CandidateBaselineParameterRow = {
  key: string
  label: string
  baseline: string
  candidate: string
  changed: boolean
  changeType: string
}

const REVIEW_PARAM_MAX_LEAVES = 32
const REVIEW_PARAM_MAX_ROWS = 8

function safeDomId(value: unknown) {
  const normalized = String(value || '').trim().toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '')
  return normalized || 'item'
}

function stableParameterValue(value: unknown): string {
  if (value === undefined || value === null) return ''
  const parsed = numericValue(value)
  if (parsed !== null) return String(Number(parsed.toFixed(8)))
  if (Array.isArray(value)) return JSON.stringify(value)
  const record = asRecord(value)
  if (Object.keys(record).length) {
    return JSON.stringify(Object.keys(record).sort().reduce<Record<string, unknown>>((acc, key) => {
      acc[key] = record[key]
      return acc
    }, {}))
  }
  return String(value)
}

function formatReviewParameterValue(key: string, value: unknown) {
  if (value === undefined || value === null || value === '') return '-'
  const parsed = numericValue(value)
  if (parsed !== null) return fmtTuningValue(key, parsed)
  if (typeof value === 'boolean') return yesNo(value)
  if (Array.isArray(value)) return value.length ? value.map(displayCode).join(' / ') : '-'
  const record = asRecord(value)
  if (Object.keys(record).length) return JSON.stringify(record)
  return displayCode(value)
}

function flattenReviewParameterConfig(value: unknown, prefix = '', rows: Array<{ key: string; value: unknown }> = []) {
  if (rows.length >= REVIEW_PARAM_MAX_LEAVES) return rows
  const record = asRecord(value)
  if (!Object.keys(record).length) {
    if (prefix) rows.push({ key: prefix, value })
    return rows
  }
  Object.keys(record).sort().forEach((key) => {
    if (rows.length >= REVIEW_PARAM_MAX_LEAVES) return
    const nextValue = record[key]
    const nextKey = prefix ? `${prefix}.${key}` : key
    const nested = asRecord(nextValue)
    if (Object.keys(nested).length) {
      flattenReviewParameterConfig(nextValue, nextKey, rows)
    } else {
      rows.push({ key: nextKey, value: nextValue })
    }
  })
  return rows
}

function candidateBaselineParameterRows(item: SignalOpsReviewQueueItem): CandidateBaselineParameterRow[] {
  const summary = asRecord(item.parameter_diff_summary || asRecord(item.strategy_experiment).parameter_diff_summary)
  const summaryRows = Array.isArray(summary.rows) ? summary.rows.map(asRecord) : []
  if (summaryRows.length) {
    return summaryRows.slice(0, REVIEW_PARAM_MAX_ROWS).map((row) => {
      const key = String(row.key || '').trim()
      const shortKey = key.split('.').pop() || key
      const changeType = String(row.change_type || '').trim().toUpperCase()
      return {
        key,
        label: TUNING_PARAM_LABELS[key] || TUNING_PARAM_LABELS[shortKey] || key,
        baseline: formatReviewParameterValue(key, row.baseline),
        candidate: formatReviewParameterValue(key, row.candidate),
        changed: changeType !== 'UNCHANGED',
        changeType: changeType || 'CHANGED',
      }
    })
  }
  const experiment = asRecord(item.strategy_experiment)
  const baselineRows = flattenReviewParameterConfig(experiment.baseline_config)
  const candidateRows = flattenReviewParameterConfig(experiment.candidate_config)
  const baselineByKey = new Map(baselineRows.map((row) => [row.key, row.value]))
  const candidateByKey = new Map(candidateRows.map((row) => [row.key, row.value]))
  const keys = Array.from(new Set([...baselineByKey.keys(), ...candidateByKey.keys()])).sort()
  const rows = keys.map((key) => {
    const shortKey = key.split('.').pop() || key
    const baseline = baselineByKey.get(key)
    const candidate = candidateByKey.get(key)
    return {
      key,
      label: TUNING_PARAM_LABELS[key] || TUNING_PARAM_LABELS[shortKey] || key,
      baseline: formatReviewParameterValue(key, baseline),
      candidate: formatReviewParameterValue(key, candidate),
      changed: stableParameterValue(baseline) !== stableParameterValue(candidate),
      changeType: stableParameterValue(baseline) !== stableParameterValue(candidate) ? 'CHANGED' : 'UNCHANGED',
    }
  })
  const changedRows = rows.filter((row) => row.changed)
  return (changedRows.length ? changedRows : rows).slice(0, REVIEW_PARAM_MAX_ROWS)
}

function tuningValueApplied(currentValue: unknown, nextValue: unknown) {
  const current = numericValue(currentValue)
  const next = numericValue(nextValue)
  return current !== null && next !== null && Math.abs(current - next) < 0.0001
}

function fmtRate(value: unknown, digits = 1) {
  const parsed = numericValue(value)
  return parsed === null ? '-' : `${fmtNumber(parsed * 100, digits)}%`
}

function compactSampleQuality(value: unknown) {
  const record = asRecord(value)
  if (!Object.keys(record).length) return { summary: '-', detail: '-' }
  const status = String(record.status || '').trim()
  const dataMode = String(record.dataMode || '').trim()
  const dailyCount = numericValue(record.dailyCount)
  const labeledCount = numericValue(record.labeledCount)
  const evaluatedCount = numericValue(record.evaluatedTestCount)
  const foldCount = numericValue(record.foldCount)
  const gaps = [
    ...asStringList(record.missingInputs),
    ...asStringList(record.missingData),
    ...asStringList(record.reasons),
  ]
  const parts = [
    status ? displayCode(status) : '',
    dataMode ? displayCode(dataMode) : '',
    dailyCount !== null ? `日线${fmtNumber(dailyCount, 0)}` : '',
    labeledCount !== null ? `标签${fmtNumber(labeledCount, 0)}` : '',
    evaluatedCount !== null ? `验证${fmtNumber(evaluatedCount, 0)}` : '',
    foldCount !== null ? `fold${fmtNumber(foldCount, 0)}` : '',
    gaps.length ? `缺口${gaps.length}` : '',
  ].filter(Boolean)
  const detail = Object.entries(record)
    .map(([key, item]) => `${key}=${Array.isArray(item) ? item.join(',') : typeof item === 'object' && item !== null ? JSON.stringify(item) : String(item)}`)
    .join('；')
  return { summary: parts.join(' / ') || '已声明', detail: detail || '已声明' }
}

function qualityTone(status: unknown): 'default' | 'good' | 'warn' | 'bad' {
  const value = String(status || '').toUpperCase()
  if (value === 'HEALTHY') return 'good'
  if (value === 'POOR') return 'bad'
  if (value === 'LOW_SAMPLE') return 'warn'
  return 'default'
}

function factorToneFromValue(value: unknown): 'positive' | 'negative' | 'neutral' | 'data' {
  const parsed = numericValue(value)
  if (parsed === null) return 'data'
  if (parsed > 0) return 'positive'
  if (parsed < 0) return 'negative'
  return 'neutral'
}

function asStringList(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item || '').trim()).filter(Boolean) : []
}

function uniqueStrings(values: unknown[]): string[] {
  return Array.from(new Set(values.map((item) => String(item || '').trim()).filter(Boolean))).sort()
}

function typedPerformanceStats(value: unknown): PerformanceStats {
  return asRecord(value) as PerformanceStats
}

function typedTuningUpdate(value: unknown): TuningUpdate {
  return asRecord(value) as TuningUpdate
}

function evidenceQuality(value: unknown): EvidenceQuality | string {
  const normalized = String(value || '').trim().toUpperCase()
  return normalized || 'LOW'
}

function isWeakEvidenceQuality(value: unknown) {
  const quality = String(evidenceQuality(value)).toUpperCase()
  return ['WEAK', 'LOW', 'SUPPORTING_ONLY', 'UNKNOWN', 'WARN', 'WARNING', 'REVIEW', 'REVIEW_ONLY', 'PENDING', 'MISSING'].includes(quality)
}

function signalOpsReviewGovernanceStrength(value: unknown) {
  const quality = String(evidenceQuality(value)).toUpperCase()
  if (isWeakEvidenceQuality(quality)) return 'LOW'
  if (['HIGH', 'STRONG', 'PRIMARY', 'PRIMARY_EVIDENCE', 'PASS', 'READY'].includes(quality)) return 'MEDIUM'
  if (['RESEARCH_GRADE', 'PRIMARY_EVIDENCE_READY'].includes(quality)) return 'MEDIUM'
  return quality === 'MEDIUM' ? 'MEDIUM' : 'LOW'
}

function experimentValidationAttemptForHash(
  config: AutoPaperTradingConfig,
  experimentHash: string,
): SignalOpsExperimentValidationAttempt {
  const state = asRecord(config.experiment_validation_state)
  const attempts = asRecord(state.attempts)
  return asRecord(attempts[experimentHash]) as SignalOpsExperimentValidationAttempt
}

function latestExperimentValidationAttemptFromState(value: unknown): SignalOpsExperimentValidationAttempt {
  const state = asRecord(value)
  const latestHash = String(state.latest_experiment_package_hash || '').trim()
  const attempts = asRecord(state.attempts)
  if (latestHash && attempts[latestHash]) {
    return asRecord(attempts[latestHash]) as SignalOpsExperimentValidationAttempt
  }
  return Object.values(attempts)
    .map((item) => asRecord(item) as SignalOpsExperimentValidationAttempt)
    .sort((left, right) => (
      String(right.updated_at || right.created_at || '').localeCompare(String(left.updated_at || left.created_at || ''))
    ))[0] || {}
}

function conservativeReviewAllowed({
  item,
  candidateStatus,
  evidence,
  benchmark,
}: {
  item: Record<string, unknown>
  candidateStatus: string
  evidence: unknown
  benchmark: Record<string, unknown>
}) {
  if (Object.prototype.hasOwnProperty.call(item, 'review_allowed')) {
    return Boolean(item.review_allowed)
  }
  return candidateStatus === 'READY_FOR_REVIEW' && !isWeakEvidenceQuality(evidence) && Boolean(benchmark.available)
}

function backendActionForReviewDecision(decision: SignalOpsReviewDecision): SignalOpsReviewDecisionAction {
  if (decision === 'PASS_REVIEW') return 'APPROVE_SIMULATION_CANDIDATE'
  if (decision === 'REJECT_SUGGESTION') return 'REJECT_CANDIDATE'
  if (decision === 'REQUEST_PATCH') return 'REQUEST_PATCH'
  return 'CONTINUE_OBSERVING'
}

function uiDecisionFromBackendAction(action: unknown): SignalOpsReviewDecision {
  const normalized = String(action || '').toUpperCase()
  if (normalized === 'APPROVE_SIMULATION_CANDIDATE') return 'PASS_REVIEW'
  if (normalized === 'REJECT_CANDIDATE') return 'REJECT_SUGGESTION'
  if (normalized === 'REQUEST_PATCH') return 'REQUEST_PATCH'
  return 'KEEP_WATCH'
}

function cleanedRecordsFromReview(value: unknown): CleanedSignalRecord[] {
  const records = asRecord(value).cleaned_records
  return Array.isArray(records) ? records.map((item) => asRecord(item) as CleanedSignalRecord) : []
}

function persistedReviewQueueRecords(config: AutoPaperTradingConfig): Array<Record<string, unknown>> {
  const queueState = asRecord(config.review_queue_state)
  const items = Array.isArray(queueState.items) ? queueState.items : []
  const observations = Array.isArray(queueState.observations) ? queueState.observations : []
  return [...items, ...observations].map((item) => asRecord(item))
}

function performanceBucketForSignal(stats: PerformanceStats, signal: SignalItem): PerformanceBucket {
  const symbols = asRecord(stats.symbols)
  return asRecord(symbols[signal.symbol]) as PerformanceBucket
}

function orderTime(order?: PaperOrderItem | null) {
  return String(order?.updated_at || order?.created_at || '')
}

function latestOrderForSignal(orders: PaperOrderItem[], signalId: string) {
  return orders
    .filter((order) => order.signal_id === signalId)
    .sort((left, right) => orderTime(right).localeCompare(orderTime(left)))[0] || null
}

function collectDecisionSources(...values: unknown[]) {
  const sources: unknown[] = []
  values.forEach((value) => {
    if (!value) return
    sources.push(value)
    const results = asRecord(value).results
    if (Array.isArray(results)) sources.push(...results)
  })
  return sources
}

function sourceMatchesSignal(value: unknown, signal: SignalItem) {
  const root = asRecord(value)
  const decision = asRecord(root.decision)
  const order = asRecord(root.order)
  const signalId = String(root.signal_id || decision.signal_id || order.signal_id || '').trim()
  const symbol = String(root.symbol || decision.symbol || order.symbol || '').trim()
  return signalId === signal.signal_id || symbol === signal.symbol
}

function decisionCardForSignal(signal: SignalItem, latestOrderItem: PaperOrderItem | null, sources: unknown[]) {
  const orderCard = firstDecisionCard(latestOrderItem)
  if (orderCard.action) return orderCard
  for (const source of sources) {
    if (!sourceMatchesSignal(source, signal)) continue
    const card = firstDecisionCard(source)
    if (card.action) return card
  }
  return {} as SignalOpsDecisionCard
}

function actionReviewText(action: unknown) {
  const normalized = String(action || 'SIM_HOLD').trim().toUpperCase()
  if (!normalized) return 'SIM_HOLD / 模拟观望'
  return normalized.startsWith('SIM_') ? `${normalized} / ${displayCode(normalized)}` : displayCode(normalized)
}

function deriveReviewDecision({
  signal,
  bucket,
  cleanedRecord,
  tuning,
  blockers,
}: {
  signal: SignalItem
  bucket: PerformanceBucket
  cleanedRecord?: CleanedSignalRecord
  tuning: TuningUpdate
  blockers: string[]
}): { decision: SignalOpsReviewDecision; score: number; reason: string } {
  const qualityStatus = String(bucket.quality_status || '').toUpperCase()
  const status = String(signal.status || '').toUpperCase()
  if (status === 'PATCH_REQUIRED' || cleanedRecord?.invalidation_triggered === true || tuning.risk_tightened === true || qualityStatus === 'POOR') {
    return {
      decision: 'REQUEST_PATCH',
      score: 90,
      reason: cleanedRecord?.invalidation_triggered
        ? '日复盘触发失效条件，建议要求补丁。'
        : qualityStatus === 'POOR'
          ? '滚动表现质量偏弱，建议要求补丁。'
          : '复盘建议收紧策略，需要人工审查补丁方向。',
    }
  }
  if (status === 'REVIEW_ONLY' || blockers.length > 0 || signal.risk_passed === false || signal.dvg_passed === false || signal.qiam_passed === false || signal.execution_reachable === false) {
    return {
      decision: 'REJECT_SUGGESTION',
      score: 80,
      reason: blockers.length ? '存在阻断或执行约束，建议驳回本次建议。' : '网关仍未全部通过，建议驳回交易建议。',
    }
  }
  if (status === 'QUALIFIED' || qualityStatus === 'HEALTHY') {
    return {
      decision: 'PASS_REVIEW',
      score: 35,
      reason: '模拟表现和生命周期状态可通过本轮审查。',
    }
  }
  return {
    decision: 'KEEP_WATCH',
    score: qualityStatus === 'LOW_SAMPLE' ? 70 : 55,
    reason: qualityStatus === 'LOW_SAMPLE' ? '样本不足，继续观察。' : '暂无硬阻断，继续观察自动运行结果。',
  }
}

function deriveReviewQueueItems({
  signals,
  config,
  orders,
  decisionSources,
}: {
  signals: SignalItem[]
  config: AutoPaperTradingConfig
  orders: PaperOrderItem[]
  decisionSources: unknown[]
}): SignalOpsReviewQueueItem[] {
  const stats = typedPerformanceStats(config.performance_stats)
  const review = asRecord(config.last_research_review)
  const tuning = typedTuningUpdate(review.tuning_update)
  const cleanedRecords = cleanedRecordsFromReview(review)
  const persistedRecords = persistedReviewQueueRecords(config)
  const persistedBySignal = new Map<string, Record<string, unknown>>()
  const persistedBySymbol = new Map<string, Record<string, unknown>>()
  persistedRecords.forEach((item) => {
    const signalId = String(item.signal_id || '').trim()
    const symbol = String(item.symbol || '').trim()
    if (signalId) persistedBySignal.set(signalId, item)
    if (symbol && !symbol.includes(',')) persistedBySymbol.set(symbol, item)
  })
  const baseItems = signals.map((signal) => {
    const persisted = persistedBySignal.get(signal.signal_id) || persistedBySymbol.get(signal.symbol) || {}
    const latestOrderItem = latestOrderForSignal(orders, signal.signal_id)
    const card = decisionCardForSignal(signal, latestOrderItem, decisionSources)
    const persistedKlinePackage = klineEvidencePackage(persisted)
    const tuningKlinePackage = klineEvidencePackage(tuning)
    const klinePackage = Object.keys(asRecord(persistedKlinePackage)).length ? persistedKlinePackage : tuningKlinePackage
    const persistedStabilityPackage = stabilityEvidencePackage(persisted)
    const tuningStabilityPackage = stabilityEvidencePackage(tuning)
    const stabilityPackage = Object.keys(asRecord(persistedStabilityPackage)).length ? persistedStabilityPackage : tuningStabilityPackage
    const klineQuality = Object.keys(asRecord(klinePackage.kline_signal_quality)).length
      ? asRecord(klinePackage.kline_signal_quality) as KlineSignalQuality
      : extractKlineQuality(card)
    const stabilityQuality = Object.keys(asRecord(stabilityPackage.strategy_stability_quality)).length
      ? asRecord(stabilityPackage.strategy_stability_quality) as StrategyStabilityQuality
      : extractStrategyStabilityQuality(card)
    const bucket = performanceBucketForSignal(stats, signal)
    const cleanedRecord = cleanedRecords.find((item) => item.signal_id === signal.signal_id || item.symbol === signal.symbol)
    const cardBlockers = asStringList(card.blockers)
    const signalBlockers = signal.blocked_reason ? [signal.blocked_reason] : []
    const blockers = [...cardBlockers, ...signalBlockers]
    const review = deriveReviewDecision({ signal, bucket, cleanedRecord, tuning, blockers })
    const candidateStatus = String(persisted.candidate_status || persisted.promotion_status || tuning.application_status || '').toUpperCase()
    const persistedDecision = persisted.review_decision ? uiDecisionFromBackendAction(persisted.review_decision) : review.decision
    const quality = evidenceQuality(
      persisted.evidence_quality
      || persisted.sample_quality
      || cleanedRecord?.sample_quality
      || asRecord(tuning.walk_forward_validation).sample_quality
      || bucket.quality_status,
    )
    const benchmark = asRecord(persisted.benchmark_comparison || asRecord(persisted.walk_forward_validation).benchmark_comparison || asRecord(tuning.walk_forward_validation).benchmark_comparison)
    const experimentHash = String(persisted.experiment_package_hash || asRecord(persisted.evidence_package).experiment_package_hash || asRecord(tuning.candidate_evidence_package).experiment_package_hash || '')
    const validationAttempt = experimentValidationAttemptForHash(config, experimentHash)
    const reviewAllowed = conservativeReviewAllowed({
      item: persisted,
      candidateStatus,
      evidence: quality,
      benchmark: Object.keys(benchmark).length ? benchmark : asRecord(validationAttempt.benchmark_comparison),
    })
    const latestAction = String(cleanedRecord?.latest_action || card.action || latestOrderItem?.action || 'SIM_HOLD').toUpperCase()
    const updatedAt = String(cleanedRecord?.cleaned_at || orderTime(latestOrderItem) || signal.updated_at || config.updated_at || '')
    const tradeCount = numericValue(bucket.trade_count)
    const pnlRate = numericValue(cleanedRecord?.pnl_rate)
    const orderCount = numericValue(cleanedRecord?.all_order_count ?? cleanedRecord?.order_count)
    const klineScore = numericValue(klineQuality.final_score ?? klineQuality.score ?? klinePackage.score)
    const stabilityScore = numericValue(stabilityQuality.stability_score ?? stabilityQuality.score ?? stabilityPackage.score)
    const isRealTrade = Boolean(card.is_real_trade || latestOrderItem?.is_real_trade || cleanedRecord?.is_real_trade)
    const source = ['signals', 'performance_stats', 'last_research_review']
    if (latestOrderItem) source.push('orders')
    if (card.action && !latestOrderItem) source.push('latest_decision')
    if (Object.keys(asRecord(stabilityPackage)).length) source.push('strategy_stability')
    const indicators: SignalOpsReviewQueueItem['indicators'] = [
      { label: '胜率', value: fmtRate(bucket.win_rate), tone: qualityTone(bucket.quality_status) },
      { label: '样本', value: tradeCount === null ? '-' : fmtNumber(tradeCount, 0), tone: tradeCount !== null && tradeCount >= 5 ? 'good' : 'warn' },
      { label: '浮盈', value: pnlRate === null ? '-' : fmtRate(pnlRate), tone: pnlTone(pnlRate) },
      { label: '订单', value: orderCount === null ? '-' : fmtNumber(orderCount, 0) },
      { label: 'K线', value: klineScore === null ? '-' : fmtNumber(klineScore, 0), tone: klineScore !== null && klineScore >= 66 ? 'good' : klineScore !== null && klineScore < 55 ? 'warn' : 'default' },
      { label: '稳定性', value: stabilityScore === null ? '-' : fmtNumber(stabilityScore, 0), tone: stabilityScore !== null && stabilityScore >= 70 ? 'good' : stabilityScore !== null && stabilityScore < 55 ? 'warn' : 'default' },
    ]
    return {
      id: signal.signal_id,
      queue_item_id: String(persisted.queue_item_id || persisted.id || ''),
      experiment_id: String(persisted.experiment_id || asRecord(tuning.strategy_experiment).experiment_id || ''),
      signal_id: signal.signal_id,
      symbol: signal.symbol,
      stock_name: signal.stock_name,
      title: `${signal.symbol} ${signal.stock_name || ''}`.trim(),
      status: signal.status,
      candidate_status: candidateStatus || undefined,
      lifecycle_status: String(persisted.lifecycle_status || candidateStatus || ''),
      evidence_quality: quality,
      risk_level: String(persisted.risk_level || (blockers.length ? 'HIGH' : 'MEDIUM')),
      factor_sources: asStringList(persisted.factor_sources || cleanedRecord?.factor_sources),
      walk_forward_validation: asRecord(persisted.walk_forward_validation || tuning.walk_forward_validation),
      strategy_experiment: asRecord(persisted.strategy_experiment || tuning.strategy_experiment),
      parameter_diff_summary: asRecord(persisted.parameter_diff_summary || asRecord(persisted.strategy_experiment).parameter_diff_summary || asRecord(tuning.strategy_experiment).parameter_diff_summary),
      evidence_package: asRecord(persisted.evidence_package || tuning.candidate_evidence_package),
      kline_evidence_package: klinePackage,
      stability_evidence_package: stabilityPackage,
      experiment_package_hash: experimentHash,
      walk_forward_run_ids: asRecord(persisted.walk_forward_run_ids || asRecord(tuning.strategy_experiment).walk_forward_run_ids) as Record<string, string>,
      benchmark_comparison: benchmark,
      research_evidence_package: asRecord(persisted.research_evidence_package || asRecord(persisted.evidence_package).research_evidence_package || asRecord(tuning.candidate_evidence_package).research_evidence_package),
      experiment_validation_attempt: validationAttempt,
      review_allowed: reviewAllowed,
      review_decision: persistedDecision,
      review_label: REVIEW_DECISION_LABELS[persistedDecision],
      priority_score: review.score + (blockers.length * 5),
      pending: !['APPLIED_TO_SIMULATION', 'REJECTED', 'SUPERSEDED', 'EXPIRED'].includes(candidateStatus) && persistedDecision !== 'PASS_REVIEW',
      reason: String(persisted.reason || review.reason),
      expires_at: String(persisted.expires_at || ''),
      latest_action: latestAction,
      latest_order_id: cleanedRecord?.latest_order_id || latestOrderItem?.order_id || null,
      latest_order_updated_at: orderTime(latestOrderItem),
      decision_card: Object.keys(card).length ? card : undefined,
      performance_bucket: Object.keys(bucket).length ? bucket : undefined,
      cleaned_record: cleanedRecord,
      blockers,
      indicators,
      source,
      simulation_only: card.simulation_only !== false && latestOrderItem?.simulation_only !== false && cleanedRecord?.simulation_only !== false,
      is_real_trade: isRealTrade,
      updated_at: updatedAt,
    }
  })
  const signalIds = new Set(baseItems.map((item) => item.signal_id))
  const persistedOnly = persistedRecords
    .filter((item) => {
      const signalId = String(item.signal_id || '').trim()
      return !signalId || !signalIds.has(signalId)
    })
    .map((item) => {
      const candidateStatus = String(item.candidate_status || item.promotion_status || '').toUpperCase()
      const decision = uiDecisionFromBackendAction(item.review_decision)
      const queueId = String(item.queue_item_id || item.id || item.experiment_id || '')
      const symbol = String(item.symbol || 'POOL')
      const quality = evidenceQuality(item.evidence_quality || item.sample_quality)
      const benchmark = asRecord(item.benchmark_comparison || asRecord(item.walk_forward_validation).benchmark_comparison)
      const experimentHash = String(item.experiment_package_hash || asRecord(item.evidence_package).experiment_package_hash || '')
      const validationAttempt = experimentValidationAttemptForHash(config, experimentHash)
      const klinePackage = klineEvidencePackage(item)
      const stabilityPackage = stabilityEvidencePackage(item)
      const klineQuality = asRecord(klinePackage.kline_signal_quality) as KlineSignalQuality
      const klineScore = numericValue(klineQuality.final_score ?? klineQuality.score ?? klinePackage.score)
      const reviewAllowed = conservativeReviewAllowed({
        item,
        candidateStatus,
        evidence: quality,
        benchmark: Object.keys(benchmark).length ? benchmark : asRecord(validationAttempt.benchmark_comparison),
      })
      return {
        id: queueId || symbol,
        queue_item_id: queueId,
        experiment_id: String(item.experiment_id || ''),
        signal_id: String(item.signal_id || ''),
        symbol,
        title: String(item.title || symbol),
        status: candidateStatus || 'REVIEW_ONLY',
        candidate_status: candidateStatus || undefined,
        lifecycle_status: String(item.lifecycle_status || candidateStatus || ''),
        evidence_quality: quality,
        risk_level: String(item.risk_level || 'MEDIUM'),
        factor_sources: asStringList(item.factor_sources),
        walk_forward_validation: asRecord(item.walk_forward_validation),
        strategy_experiment: asRecord(item.strategy_experiment),
        parameter_diff_summary: asRecord(item.parameter_diff_summary || asRecord(item.strategy_experiment).parameter_diff_summary),
        evidence_package: asRecord(item.evidence_package),
        kline_evidence_package: klinePackage,
        stability_evidence_package: stabilityPackage,
        experiment_package_hash: experimentHash,
        walk_forward_run_ids: asRecord(item.walk_forward_run_ids) as Record<string, string>,
        benchmark_comparison: benchmark,
        research_evidence_package: asRecord(item.research_evidence_package || asRecord(item.evidence_package).research_evidence_package),
        experiment_validation_attempt: validationAttempt,
        review_allowed: reviewAllowed,
        review_decision: decision,
        review_label: REVIEW_DECISION_LABELS[decision],
        priority_score: candidateStatus === 'READY_FOR_REVIEW' ? 95 : 65,
        pending: !['APPLIED_TO_SIMULATION', 'REJECTED', 'SUPERSEDED', 'EXPIRED'].includes(candidateStatus),
        reason: String(item.reason || ''),
        expires_at: String(item.expires_at || ''),
        latest_action: 'SIM_HOLD',
        latest_order_id: null,
        blockers: [],
        indicators: [
          { label: 'Status', value: candidateStatus || '-' },
          { label: 'Quality', value: quality },
          { label: 'Risk', value: String(item.risk_level || 'MEDIUM') },
          { label: 'Kline', value: klineScore === null ? '-' : fmtNumber(klineScore, 0), tone: klineScore !== null && klineScore >= 66 ? 'good' : klineScore !== null && klineScore < 55 ? 'warn' : 'default' },
          { label: 'Review', value: reviewAllowed ? 'ready' : 'observe' },
        ],
        source: ['review_queue_state'],
        simulation_only: item.simulation_only !== false,
        is_real_trade: Boolean(item.is_real_trade),
        updated_at: String(item.updated_at || config.updated_at || ''),
      } as SignalOpsReviewQueueItem
    })
  return [...baseItems, ...persistedOnly].sort((left, right) => (
    right.priority_score - left.priority_score
    || String(right.updated_at || '').localeCompare(String(left.updated_at || ''))
  ))
}

type SignalListItemVariant = 'latest' | 'history' | 'auto-paper'

function isAutoPaperSignal(signal: SignalItem) {
  const metadata = asRecord(signal.metadata_json)
  const source = String(metadata.source || '').trim().toLowerCase()
  const hasAutomationMode = Object.prototype.hasOwnProperty.call(metadata, 'automation_mode')
  return source === 'auto_paper_trading' || hasAutomationMode
}

function signalGroupKey(signal: SignalItem) {
  return String(signal.symbol || signal.signal_id).trim() || signal.signal_id
}

function reviewItemKey(item: SignalOpsReviewQueueItem) {
  return [
    item.queue_item_id || item.id,
    item.experiment_id,
    item.signal_id,
    item.symbol,
    item.updated_at,
  ].map((value) => String(value || '').trim()).filter(Boolean).join(':') || item.title
}

function Metric({ label, value, tone = 'default' }: { label: string; value: React.ReactNode; tone?: 'default' | 'good' | 'warn' | 'bad' }) {
  const toneClass = tone === 'good'
    ? 'text-emerald-700'
    : tone === 'warn'
      ? 'text-amber-700'
      : tone === 'bad'
        ? 'text-rose-700'
        : 'text-slate-950'
  return (
    <div className="min-w-0 rounded-md border border-slate-200 bg-slate-50 p-3">
      <div className="min-w-0 text-xs font-medium text-slate-500">{label}</div>
      <div className={`mt-1 min-w-0 whitespace-normal break-words text-sm font-semibold ${toneClass}`}>{value}</div>
    </div>
  )
}

function TextInput({
  label,
  value,
  onChange,
  onKeyDown,
  placeholder,
  helperText,
  error,
  inputMode = 'text',
}: {
  label: string
  value: string
  onChange: (value: string) => void
  onKeyDown?: React.KeyboardEventHandler<HTMLInputElement>
  placeholder?: string
  helperText?: string
  error?: string
  inputMode?: React.HTMLAttributes<HTMLInputElement>['inputMode']
}) {
  return (
    <label className="block text-xs font-medium text-slate-600">
      {label}
      <input
        className={`mt-1 w-full rounded-md border px-3 py-2 text-sm text-slate-900 shadow-sm focus:outline-none ${error ? 'border-rose-300 bg-rose-50 focus:border-rose-500' : 'border-slate-200 focus:border-cyan-500'}`}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        inputMode={inputMode}
        aria-invalid={Boolean(error)}
      />
      {error ? (
        <span className="mt-1 block text-xs font-medium text-rose-700">{error}</span>
      ) : helperText ? (
        <span className="mt-1 block text-xs font-normal text-slate-500">{helperText}</span>
      ) : null}
    </label>
  )
}

function TextArea({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  placeholder?: string
}) {
  return (
    <label className="block text-xs font-medium text-slate-600">
      {label}
      <textarea
        className="mt-1 h-20 w-full rounded-md border border-slate-200 px-3 py-2 text-sm text-slate-900 shadow-sm focus:border-cyan-500 focus:outline-none"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
      />
    </label>
  )
}

function Toggle({ checked, label, onChange }: { checked: boolean; label: string; onChange: (value: boolean) => void }) {
  return (
    <label className="inline-flex items-center gap-2 text-sm font-medium text-slate-700">
      <input type="checkbox" className="h-4 w-4 rounded border-slate-300" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      {label}
    </label>
  )
}

function ActionButton({
  children,
  icon,
  onClick,
  disabled,
  title,
  testId,
  variant = 'secondary',
}: {
  children: React.ReactNode
  icon?: React.ReactNode
  onClick: () => void
  disabled?: boolean
  title?: string
  testId?: string
  variant?: 'primary' | 'danger' | 'secondary'
}) {
  const className = variant === 'primary'
    ? 'border-cyan-600 bg-cyan-600 text-white hover:bg-cyan-700'
    : variant === 'danger'
      ? 'border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100'
      : 'border-slate-200 bg-white text-slate-700 hover:bg-slate-50'
  return (
    <button
      type="button"
      className={`inline-flex min-h-9 max-w-full items-center justify-center gap-2 rounded-md border px-3 py-2 text-left text-sm font-medium leading-5 disabled:cursor-not-allowed disabled:opacity-50 ${className}`}
      disabled={disabled}
      onClick={onClick}
      title={title}
      data-testid={testId}
    >
      {icon}
      {children}
    </button>
  )
}

export function SignalOpsPage() {
  const currentRun = useAnalysisStore((state) => state.currentRun)
  const operator = useOperatorContext()
  const [searchParams] = useSearchParams()
  const [signals, setSignals] = useState<SignalItem[]>([])
  const [selectedSignalId, setSelectedSignalId] = useState('')
  const [detail, setDetail] = useState<SignalDetail | null>(null)
  const [portfolio, setPortfolio] = useState<PaperPortfolioItem | null>(null)
  const [positions, setPositions] = useState<PaperPositionItem[]>([])
  const [orders, setOrders] = useState<PaperOrderItem[]>([])
  const [poolPortfolios, setPoolPortfolios] = useState<PaperPortfolioItem[]>([])
  const [poolPositions, setPoolPositions] = useState<PaperPositionItem[]>([])
  const [poolOrders, setPoolOrders] = useState<PaperOrderItem[]>([])
  const [autoConfig, setAutoConfig] = useState<AutoPaperTradingConfig>(DEFAULT_AUTO_CONFIG)
  const [autoStatus, setAutoStatus] = useState<AutoPaperTradingStatusResponse | null>(null)
  const [form, setForm] = useState<AutoPaperFormState>(() => configToForm(DEFAULT_AUTO_CONFIG))
  const [editable, setEditable] = useState<EditableSignalState>(() => editableFromSignal(null))
  const [tickResult, setTickResult] = useState<AutoPaperTradingTickResult | null>(null)
  const [dailyReview, setDailyReview] = useState<AutoPaperTradingDailyReviewResult | null>(null)
  const [commandResult, setCommandResult] = useState<AutoPaperTradingCommandResult | null>(null)
  const [reviewExportVerification, setReviewExportVerification] = useState<AutoPaperTradingReviewDecisionEventVerification | null>(null)
  const [reviewExportHandoff, setReviewExportHandoff] = useState<AutoPaperTradingReviewDecisionEventHandoff | null>(null)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState('')
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [researchEvidenceNotice, setResearchEvidenceNotice] = useState<SignalOpsResearchEvidenceNotice | null>(null)
  const [formValidationErrors, setFormValidationErrors] = useState<AutoPaperFormValidationErrors>({})
  const [expandedSignalKeys, setExpandedSignalKeys] = useState<string[]>([])
  const [reviewFilters, setReviewFilters] = useState<ReviewQueueFilters>(DEFAULT_REVIEW_QUEUE_FILTERS)
  const [selectedReviewItemKey, setSelectedReviewItemKey] = useState('')
  const [isReviewWindowOpen, setIsReviewWindowOpen] = useState(false)
  const [isBoundaryWindowOpen, setIsBoundaryWindowOpen] = useState(false)
  const signalDetailRequestSeq = useRef(0)
  const refreshAllRequestSeq = useRef(0)
  const researchIterationId = (searchParams.get('iteration_id') || '').trim()
  const requestedSignalId = (searchParams.get('signal_id') || '').trim()
  const linkedRunId = (searchParams.get('run_id') || '').trim()
  const isLinkedRunPending = Boolean(linkedRunId && currentRun?.runId !== linkedRunId)
  const bridgeRun = isLinkedRunPending ? null : currentRun

  const configuredSymbols = useMemo(() => managedSymbolsFromConfig(autoConfig), [autoConfig])
  const stockNameSources = useMemo<StockNameSources>(() => ({
    signals,
    tickResult,
    statusLastTickResult: firstNonEmptyRecord(autoStatus?.last_tick_result, autoConfig.last_tick_result),
  }), [autoConfig.last_tick_result, autoStatus?.last_tick_result, signals, tickResult])
  const configuredSymbolNames = useMemo(
    () => stockNamesForSymbols(autoConfig, configuredSymbols, stockNameSources),
    [autoConfig, configuredSymbols, stockNameSources],
  )
  const selectedSignal = detail?.signal || signals.find((item) => item.signal_id === selectedSignalId) || null
  const combinedOrders = useMemo(() => {
    const byId = new Map<string, PaperOrderItem>()
    const allOrders = [...poolOrders, ...orders]
    allOrders.forEach((order) => {
      if (order.order_id) byId.set(order.order_id, order)
    })
    return Array.from(byId.values())
  }, [orders, poolOrders])
  const selectedVisibleOrders = useMemo(() => {
    const signalId = selectedSignal?.signal_id || selectedSignalId
    if (!signalId) return orders
    const byId = new Map<string, PaperOrderItem>()
    orders.forEach((order) => {
      if (order.order_id) byId.set(order.order_id, order)
    })
    combinedOrders.forEach((order) => {
      if (order.signal_id === signalId && order.order_id) byId.set(order.order_id, order)
    })
    return Array.from(byId.values())
  }, [combinedOrders, orders, selectedSignal?.signal_id, selectedSignalId])
  const selectedLatestOrder = useMemo(() => latestOrder(selectedVisibleOrders), [selectedVisibleOrders])
  const decisionCard = useMemo(
    () => firstDecisionCard(tickResult, autoStatus?.last_tick_result, autoConfig.last_tick_result, autoConfig.last_decision, selectedLatestOrder),
    [autoConfig.last_decision, autoConfig.last_tick_result, autoStatus?.last_tick_result, selectedLatestOrder, tickResult],
  )
  const decisionTreeState = useMemo(
    () => typedDecisionTreeState(firstNonEmptyRecord(autoStatus?.decision_tree_state, autoConfig.decision_tree_state)),
    [autoConfig.decision_tree_state, autoStatus?.decision_tree_state],
  )
  const aiStrategyReview = useMemo(() => {
    return latestCompletedReview(dailyReview, autoStatus?.last_research_review, autoConfig.last_research_review)
  }, [autoConfig.last_research_review, autoStatus?.last_research_review, dailyReview])
  const reviewDecisionSources = useMemo(
    () => collectDecisionSources(tickResult, autoStatus?.last_tick_result, autoConfig.last_tick_result, autoConfig.last_decision),
    [autoConfig.last_decision, autoConfig.last_tick_result, autoStatus?.last_tick_result, tickResult],
  )
  const reviewQueue = useMemo(
    () => deriveReviewQueueItems({
      signals,
      config: autoConfig,
      orders: combinedOrders,
      decisionSources: reviewDecisionSources,
    }),
    [autoConfig, combinedOrders, reviewDecisionSources, signals],
  )
  const reviewFilterOptions = useMemo(() => ({
    risks: uniqueStrings(reviewQueue.map((item) => item.risk_level)),
    statuses: uniqueStrings(reviewQueue.map((item) => item.candidate_status || item.status)),
    qualities: uniqueStrings(reviewQueue.map((item) => item.evidence_quality)),
    symbols: uniqueStrings(reviewQueue.map((item) => item.symbol)),
    sources: uniqueStrings(reviewQueue.flatMap((item) => item.factor_sources?.length ? item.factor_sources : item.source)),
  }), [reviewQueue])
  const filteredReviewQueue = useMemo(() => reviewQueue.filter((item) => {
    if (reviewFilters.risk !== 'ALL' && item.risk_level !== reviewFilters.risk) return false
    if (reviewFilters.status !== 'ALL' && (item.candidate_status || item.status) !== reviewFilters.status) return false
    if (reviewFilters.quality !== 'ALL' && item.evidence_quality !== reviewFilters.quality) return false
    if (reviewFilters.symbol !== 'ALL' && item.symbol !== reviewFilters.symbol) return false
    if (reviewFilters.source !== 'ALL') {
      const sources = item.factor_sources?.length ? item.factor_sources : item.source
      if (!sources.includes(reviewFilters.source)) return false
    }
    return true
  }), [reviewFilters, reviewQueue])
  const activeReviewItem = (
    filteredReviewQueue.find((item) => reviewItemKey(item) === selectedReviewItemKey)
    || filteredReviewQueue.find((item) => item.signal_id && item.signal_id === selectedSignalId)
    || filteredReviewQueue[0]
    || reviewQueue[0]
    || null
  )
  const automationSummary = useMemo<SignalOpsAutomationSummary>(() => {
    const queueState = firstNonEmptyRecord(autoStatus?.review_queue_state, autoConfig.review_queue_state)
    const validationState = firstNonEmptyRecord(autoStatus?.experiment_validation_state, autoConfig.experiment_validation_state)
    const randomValidationState = firstNonEmptyRecord(autoStatus?.random_validation_state, autoConfig.random_validation_state)
    const latestRandomSummary = asRecord(randomValidationState.latest_summary)
    const latestRandomAdjustment = asRecord(latestRandomSummary.applied_adjustment)
    const latestValidation = latestExperimentValidationAttemptFromState(validationState)
    const latestValidationAt = String(latestValidation.updated_at || latestValidation.created_at || '').trim()
    const latestRandomAt = String(latestRandomSummary.updated_at || latestRandomSummary.created_at || randomValidationState.updated_at || '').trim()
    const randomEvidence = String(latestRandomSummary.evidence_level || '').trim()
    const randomEvidenceReviewStrength = randomEvidence ? signalOpsReviewGovernanceStrength(randomEvidence) : 'LOW'
    const experimentValidationRan = Boolean(latestValidationAt || latestValidation.experiment_package_hash)
    const randomValidationRan = Boolean(latestRandomAt || latestRandomSummary.job_id || randomEvidence)
    const review = latestCompletedReview(dailyReview, autoStatus?.last_research_review, autoConfig.last_research_review)
    const candidateStatuses = uniqueStrings(reviewQueue.map((item) => item.candidate_status || item.lifecycle_status || item.status))
    const pendingCount = reviewQueue.filter((item) => item.pending).length
    const health = String(autoStatus?.loop_health || (autoStatus?.loop_running ? 'HEALTHY' : 'WAIT')).toUpperCase()
    const healthTone: SignalOpsAutomationSummary['healthTone'] = autoStatus?.last_error || autoConfig.last_error || health === 'ERROR' || health === 'FAILED'
      ? 'bad'
      : autoStatus?.loop_running
        ? 'good'
        : 'warn'

    return {
      managedStockCount: configuredSymbols.length,
      pendingReviewCount: pendingCount,
      healthStatus: health,
      healthTone,
      lastAutoReview: fmtDate(String(review.updated_at || review.trading_date || autoConfig.last_research_review_date || '')),
      lastExperimentValidation: experimentValidationRan ? fmtDateOrLabel(latestValidationAt, '已记录') : '未运行',
      lastRandomValidation: randomValidationRan ? fmtDateOrLabel(latestRandomAt, '已记录') : '未运行',
      randomValidationEvidence: randomValidationRan ? randomEvidenceReviewStrength : '未运行',
      randomValidationRan,
      randomValidationApplied: randomValidationRan && Boolean(latestRandomAdjustment.applied),
      candidateStatus: candidateStatuses[0] || '-',
      loopRunning: Boolean(autoStatus?.loop_running),
      simulationOnly: queueState.simulation_only !== false && latestValidation.simulation_only !== false,
      isRealTrade: Boolean(queueState.is_real_trade || latestValidation.is_real_trade),
    }
  }, [autoConfig, autoStatus, configuredSymbols.length, dailyReview, reviewQueue])
  const poolOverview = useMemo<SignalOpsPoolOverview>(() => {
    const totalCash = poolPortfolios.reduce((sum, item) => sum + Number(item.available_cash || 0), 0)
    const totalMarketValue = poolPortfolios.reduce((sum, item) => sum + Number(item.market_value || 0), 0)
    const totalFloatingPnl = poolPositions.reduce((sum, item) => sum + Number(item.floating_pnl || 0), 0)
    const capitalBase = poolCapitalBase(autoConfig, poolPortfolios)
    const totalAssets = capitalBase + totalFloatingPnl
    const totalPositionCost = poolPositions.reduce((sum, item) => {
      const quantity = Number(item.quantity || 0)
      const cost = Number(item.virtual_cost || 0)
      return sum + Math.abs(quantity * cost)
    }, 0)
    return {
      totalCash,
      totalMarketValue,
      totalFloatingPnl,
      capitalBase,
      totalAssets,
      pnlRate: capitalBase > 0 ? (totalFloatingPnl / capitalBase) * 100 : null,
      holdingPnlRate: totalPositionCost > 0 ? (totalFloatingPnl / totalPositionCost) * 100 : null,
    }
  }, [autoConfig, poolPortfolios, poolPositions])
  const automationModules = useMemo(() => {
    const statusModules = asRecord(autoStatus?.automation_modules)
    if (Object.keys(statusModules).length) return statusModules
    return {
      mode: autoConfig.automation_mode || 'SIMULATION',
      simulation: asRecord(autoConfig.simulation_module),
      live: asRecord(autoConfig.live_module),
      active_module: 'simulation',
      real_trade_enabled: false,
      live_ready: false,
    }
  }, [autoConfig, autoStatus])
  const latestModuleEvidence = useMemo(
    () => firstNonEmptyRecord(
      tickResult?.module_evidence,
      autoStatus?.last_module_evidence,
      asRecord(autoStatus?.last_tick_result).module_evidence,
      autoConfig.last_module_evidence,
      asRecord(autoConfig.last_tick_result).module_evidence,
      autoConfig.last_decision?.moduleEvidence,
    ),
    [autoConfig.last_decision, autoConfig.last_module_evidence, autoConfig.last_tick_result, autoStatus, tickResult],
  )
  const latestPortfolioSnapshot = useMemo(
    () => firstNonEmptyRecord(
      tickResult?.portfolio_snapshot,
      autoStatus?.last_portfolio_snapshot,
      asRecord(autoStatus?.last_tick_result).portfolio_snapshot,
      autoConfig.last_portfolio_snapshot,
      asRecord(autoConfig.last_tick_result).portfolio_snapshot,
    ),
    [autoConfig.last_portfolio_snapshot, autoConfig.last_tick_result, autoStatus, tickResult],
  )
  const reviewWindowState = useMemo<SignalOpsReviewWindowState>(() => ({
    isOpen: isReviewWindowOpen,
    activeItem: activeReviewItem,
    pendingCount: reviewQueue.filter((item) => item.pending).length,
    filteredCount: filteredReviewQueue.length,
    totalCount: reviewQueue.length,
  }), [activeReviewItem, filteredReviewQueue.length, isReviewWindowOpen, reviewQueue])
  const { lifecycleSignals, autoPaperSignals } = useMemo(() => {
    const lifecycleSignals: SignalItem[] = []
    const autoPaperSignals: SignalItem[] = []
    signals.forEach((signal) => {
      if (isAutoPaperSignal(signal)) {
        autoPaperSignals.push(signal)
      } else {
        lifecycleSignals.push(signal)
      }
    })
    autoPaperSignals.sort((left, right) => (right.updated_at || '').localeCompare(left.updated_at || ''))
    return { lifecycleSignals, autoPaperSignals }
  }, [signals])
  const visibleAutoPaperSignals = useMemo(() => {
    const selectedSignal = autoPaperSignals.find((signal) => signal.signal_id === selectedSignalId)
    const recentSignals = autoPaperSignals
      .filter((signal) => signal.signal_id !== selectedSignalId)
      .slice(0, selectedSignal ? 11 : 12)
    return selectedSignal ? [selectedSignal, ...recentSignals] : recentSignals
  }, [autoPaperSignals, selectedSignalId])
  const signalGroups = useMemo(() => {
    const groups: Array<{ key: string; latest: SignalItem; history: SignalItem[] }> = []
    const byKey = new Map<string, { key: string; latest: SignalItem; history: SignalItem[] }>()
    const orderedSignals = [...lifecycleSignals].sort((left, right) => (right.updated_at || '').localeCompare(left.updated_at || ''))
    orderedSignals.forEach((signal) => {
      const key = signalGroupKey(signal)
      const group = byKey.get(key)
      if (group) {
        group.history.push(signal)
        return
      }
      const nextGroup = { key, latest: signal, history: [] }
      byKey.set(key, nextGroup)
      groups.push(nextGroup)
    })
    return groups
  }, [lifecycleSignals])
  const canWriteSignalOps = roleAllows(operator.role, 'researcher')
  const canOperateSignalOps = roleAllows(operator.role, 'operator')
  const canManageSignalOpsConfig = roleAllows(operator.role, 'admin')
  const writeDisabledReason = canWriteSignalOps ? undefined : `当前角色 ${operator.role} 不能修改 SignalOps 生命周期。`
  const operateDisabledReason = canOperateSignalOps ? undefined : `当前角色 ${operator.role} 不能执行 SignalOps 沙箱控制指令。`
  const configDisabledReason = canManageSignalOpsConfig ? undefined : `当前角色 ${operator.role} 不能保存 SignalOps 运行配置。`
  const manualInterventionGroup = useMemo<SignalOpsManualInterventionGroup>(() => ({
    canWrite: canWriteSignalOps,
    canOperate: canOperateSignalOps,
    canManageConfig: canManageSignalOpsConfig,
    writeDisabledReason,
    operateDisabledReason,
    configDisabledReason,
  }), [canManageSignalOpsConfig, canOperateSignalOps, canWriteSignalOps, configDisabledReason, operateDisabledReason, writeDisabledReason])

  const setFormValue = useCallback(<K extends keyof AutoPaperFormState>(key: K, value: AutoPaperFormState[K]) => {
    setForm((current) => ({ ...current, [key]: value }))
    if (key in AUTO_PAPER_NUMERIC_RULES) {
      setFormValidationErrors((current) => {
        const numericKey = key as AutoPaperNumericField
        if (!current[numericKey]) return current
        const next = { ...current }
        delete next[numericKey]
        return next
      })
    }
  }, [])

  const toggleSignalHistory = useCallback((key: string) => {
    setExpandedSignalKeys((current) => (
      current.includes(key) ? current.filter((item) => item !== key) : [...current, key]
    ))
  }, [])

  const loadSignalArtifacts = useCallback(async (signalId: string) => {
    if (!signalId) {
      return { nextPortfolio: null, nextPositions: [] as PaperPositionItem[], nextOrders: [] as PaperOrderItem[] }
    }
    const [nextPortfolio, nextPositions, nextOrders] = await Promise.all([
      getPaperPortfolio(signalId, { allowMissing: true }).catch(() => null),
      listPaperPositions(signalId).catch(() => [] as PaperPositionItem[]),
      listPaperOrders(signalId).catch(() => [] as PaperOrderItem[]),
    ])
    return { nextPortfolio, nextPositions, nextOrders }
  }, [])

  const loadSignalDetail = useCallback(async (signalId: string) => {
    const requestSeq = signalDetailRequestSeq.current + 1
    signalDetailRequestSeq.current = requestSeq
    if (!signalId) {
      setDetail(null)
      setEditable(editableFromSignal(null))
      setPortfolio(null)
      setPositions([])
      setOrders([])
      return
    }
    const nextDetail = await getSignal(signalId)
    if (requestSeq !== signalDetailRequestSeq.current) return
    setDetail(nextDetail)
    setEditable(editableFromSignal(nextDetail.signal))
    const artifacts = await loadSignalArtifacts(signalId)
    if (requestSeq !== signalDetailRequestSeq.current) return
    setPortfolio(artifacts.nextPortfolio)
    setPositions(artifacts.nextPositions)
    setOrders(artifacts.nextOrders)
  }, [loadSignalArtifacts])

  const loadPoolDetails = useCallback(async (config: AutoPaperTradingConfig, signalList: SignalItem[]) => {
    const ids = new Set<string>()
    if (config.signal_id) ids.add(config.signal_id)
    Object.values(config.signal_ids || {}).forEach((id) => {
      if (id) ids.add(id)
    })
    managedSymbolsFromConfig(config).forEach((symbol) => {
      const matched = signalList.find((item) => item.symbol === symbol)
      if (matched) ids.add(matched.signal_id)
    })

    const portfolioItems: PaperPortfolioItem[] = []
    const positionItems: PaperPositionItem[] = []
    const orderItems: PaperOrderItem[] = []
    await Promise.all(Array.from(ids).map(async (signalId) => {
      const [nextPortfolio, nextPositions, nextOrders] = await Promise.all([
        getPaperPortfolio(signalId, { allowMissing: true }).catch(() => null),
        listPaperPositions(signalId).catch(() => [] as PaperPositionItem[]),
        listPaperOrders(signalId).catch(() => [] as PaperOrderItem[]),
      ])
      if (nextPortfolio) portfolioItems.push(nextPortfolio)
      positionItems.push(...nextPositions)
      orderItems.push(...nextOrders)
    }))
    return { portfolioItems, positionItems, orderItems }
  }, [])

  const refreshAll = useCallback(async (preferredSignalId?: string) => {
    const requestSeq = refreshAllRequestSeq.current + 1
    refreshAllRequestSeq.current = requestSeq
    const isLatestRequest = () => requestSeq === refreshAllRequestSeq.current
    setLoading(true)
    setError('')
    try {
      const [nextSignals, nextConfig, nextStatus] = await Promise.all([
        listSignals({ limit: 100 }),
        getAutoPaperTradingConfig(),
        getAutoPaperTradingStatus(),
      ])
      if (!isLatestRequest()) return
      setSignals(nextSignals)
      setAutoConfig(nextConfig)
      setAutoStatus(nextStatus)
      setForm(configToForm(nextConfig))
      const poolDetails = await loadPoolDetails(nextConfig, nextSignals)
      if (!isLatestRequest()) return
      setPoolPortfolios(poolDetails.portfolioItems)
      setPoolPositions(poolDetails.positionItems)
      setPoolOrders(poolDetails.orderItems)
      const nextSelected = selectableSignalId(preferredSignalId, nextConfig, nextSignals)
      if (!isLatestRequest()) return
      setSelectedSignalId(nextSelected)
      try {
        await loadSignalDetail(nextSelected)
      } catch (detailError) {
        if (!isLatestRequest()) return
        if (!isSignalNotFoundError(detailError)) throw detailError
        setSelectedSignalId('')
        await loadSignalDetail('')
      }
    } catch (err) {
      if (isLatestRequest()) setError(messageOf(err))
    } finally {
      if (isLatestRequest()) setLoading(false)
    }
  }, [loadPoolDetails, loadSignalDetail])

  useEffect(() => {
    void refreshAll(requestedSignalId)
  }, [refreshAll, requestedSignalId])

  const runTask = useCallback(async (label: string, task: () => Promise<void>) => {
    setBusy(label)
    setError('')
    setNotice('')
    try {
      await task()
    } catch (err) {
      setError(messageOf(err))
    } finally {
      setBusy('')
    }
  }, [])

  const handleSelectSignal = useCallback((signalId: string) => {
    setSelectedSignalId(signalId)
    void runTask('load-signal', async () => {
      try {
        await loadSignalDetail(signalId)
      } catch (err) {
        if (!isSignalNotFoundError(err)) throw err
        setSelectedSignalId('')
        await loadSignalDetail('')
        setNotice('Selected SignalOps record was removed; selection has been cleared.')
      }
    })
  }, [loadSignalDetail, runTask])

  const handleSelectReviewItem = useCallback((item: SignalOpsReviewQueueItem) => {
    setSelectedReviewItemKey(reviewItemKey(item))
    if (item.signal_id) {
      handleSelectSignal(item.signal_id)
    }
  }, [handleSelectSignal])

  const handleCreateFromRun = useCallback(() => {
    void runTask('create-from-run', async () => {
      if (!canWriteSignalOps) throw new Error(writeDisabledReason)
      if (isLinkedRunPending) throw new Error(`正在加载 URL 指定的分析运行：${linkedRunId}`)
      if (!bridgeRun) throw new Error('当前没有选中的分析运行。')
      const created = await createSignal({
        symbol: bridgeRun.stockCode,
        stock_name: bridgeRun.stockName,
        source_run_id: bridgeRun.runId,
        audit_id: bridgeRun.signalOps.auditId,
        risk_passed: bridgeRun.signalOps.riskPassed,
        dvg_passed: bridgeRun.signalOps.dvgPassed,
        dvg_status: bridgeRun.dvg.status,
        qiam_passed: bridgeRun.signalOps.qiamPassed,
        qiam_status: bridgeRun.qiam.finalBuySuitability,
        execution_reachable: bridgeRun.signalOps.executionReachable,
        portfolio_allowed: bridgeRun.portfolio.allowAddPosition,
        trigger_conditions: bridgeRun.signalOps.triggerConditions,
        invalidation_conditions: bridgeRun.signalOps.invalidationConditions,
        review_fields: bridgeRun.signalOps.reviewFields,
        metadata_json: {
          source: 'analysis_run',
          runId: bridgeRun.runId,
          finalAction: bridgeRun.finalAction,
          dataMode: bridgeRun.dataMode,
        },
      })
      setNotice(`信号已创建：${created.symbol} ${compactId(created.signal_id)}`)
      await refreshAll(created.signal_id)
    })
  }, [bridgeRun, canWriteSignalOps, isLinkedRunPending, linkedRunId, refreshAll, runTask, writeDisabledReason])

  const persistAutoConfig = useCallback(async ({ requireNewSymbol = false }: { requireNewSymbol?: boolean } = {}) => {
    const requestedSymbols = splitList(form.newSymbol)
    if (requireNewSymbol && requestedSymbols.length === 0) {
      throw new Error('请输入股票代码后再加入股票池。')
    }
    if (requireNewSymbol && !form.initialBuySignal.trim()) {
      throw new Error('请输入最初买入信号。')
    }
    if (requireNewSymbol && !form.finalSellSignal.trim()) {
      throw new Error('请输入最终卖出信号。')
    }
    const existingSymbols = managedSymbolsFromConfig(autoConfig)
    const nextSymbols = uniqueListInOrder([...existingSymbols, ...splitList(form.newSymbol)])
    const addedSymbols = nextSymbols.filter((symbol) => !existingSymbols.includes(symbol))
    if (requireNewSymbol && addedSymbols.length === 0) {
      throw new Error('该股票代码已在股票池中。')
    }
    const numericValidation = validateAutoPaperNumericInputs(form)
    setFormValidationErrors(numericValidation.errors)
    const firstNumericError = Object.values(numericValidation.errors)[0]
    if (firstNumericError) {
      throw new Error(firstNumericError)
    }
    const numericValues = numericValidation.values
    const payload: UpdateAutoPaperTradingConfigPayload = {
      enabled: requireNewSymbol ? true : form.enabled,
      symbol: nextSymbols.join(','),
      stock_name: stockNamesForSymbols(autoConfig, nextSymbols, stockNameSources).join(','),
      initial_buy_signal: form.initialBuySignal.trim(),
      final_sell_signal: form.finalSellSignal.trim(),
      initial_buy_signals: symbolTextMapWithAdditions(autoConfig.initial_buy_signals, addedSymbols, form.initialBuySignal),
      final_sell_signals: symbolTextMapWithAdditions(autoConfig.final_sell_signals, addedSymbols, form.finalSellSignal),
      initial_cash: numericValues.initialCash,
      min_order_value: numericValues.minOrderValue,
      commission_rate: numericValues.commissionRatePct / 100,
      commission_min_fee: numericValues.commissionMinFee,
      commission_min_trade_value: numericValues.commissionMinTradeValue,
      stamp_duty_rate: numericValues.stampDutyRatePct / 100,
      tick_interval_seconds: numericValues.tickIntervalSeconds,
      min_order_interval_seconds: numericValues.minOrderIntervalSeconds,
      realtime_interval_seconds: numericValues.realtimeIntervalSeconds,
      kline_interval_seconds: numericValues.klineIntervalSeconds,
      weekly_monthly_interval_seconds: numericValues.weeklyMonthlyIntervalSeconds,
      use_llm: requireNewSymbol ? true : form.useLlm,
      max_llm_calls_per_day: numericValues.maxLlmCallsPerDay,
      min_llm_interval_minutes: numericValues.minLlmIntervalMinutes,
      auto_fill: requireNewSymbol ? true : form.autoFill,
      adaptive_tuning_enabled: true,
    }
    const nextConfig = await updateAutoPaperTradingConfig(payload)
    setAutoConfig(nextConfig)
    setForm(configToForm(nextConfig))
    if (requireNewSymbol && addedSymbols.length > 0 && canOperateSignalOps) {
      try {
        const result = await runAutoPaperTradingTick(true)
        setTickResult(result)
        setAutoConfig(result.config)
        setForm(configToForm(result.config))
        setNotice(displayMessage(result.message) || `已加入并完成首次跟进：${addedSymbols.join(', ')}`)
        await refreshAll(result.signal_id || nextConfig.signal_id || selectedSignalId)
        return
      } catch (err) {
        setNotice(`已加入股票池：${addedSymbols.join(', ')}；首次跟进失败：${messageOf(err)}`)
        await refreshAll(nextConfig.signal_id || selectedSignalId)
        return
      }
    }
    setNotice(addedSymbols.length ? `已加入股票池：${addedSymbols.join(', ')}` : '自动模拟交易配置已保存。')
    await refreshAll(nextConfig.signal_id || selectedSignalId)
  }, [autoConfig, canOperateSignalOps, form, refreshAll, selectedSignalId, stockNameSources])

  const handleSaveAutoConfig = useCallback(() => {
    void runTask('save-config', async () => {
      if (!canManageSignalOpsConfig) throw new Error(configDisabledReason)
      await persistAutoConfig()
    })
  }, [canManageSignalOpsConfig, configDisabledReason, persistAutoConfig, runTask])

  const handleAddSymbolToPool = useCallback(() => {
    void runTask('add-symbol', async () => {
      if (!canManageSignalOpsConfig) throw new Error(configDisabledReason)
      await persistAutoConfig({ requireNewSymbol: true })
    })
  }, [canManageSignalOpsConfig, configDisabledReason, persistAutoConfig, runTask])

  const handleSymbolInputKeyDown = useCallback((event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter') {
      event.preventDefault()
      handleAddSymbolToPool()
    }
  }, [handleAddSymbolToPool])

  const handleRunTick = useCallback(() => {
    void runTask('tick', async () => {
      if (!canOperateSignalOps) throw new Error(operateDisabledReason)
      const result = await runAutoPaperTradingTick(true)
      setTickResult(result)
      setAutoConfig(result.config)
      setForm(configToForm(result.config))
      setNotice(displayMessage(result.message) || `单次跟进：${displayCode(result.status)}`)
      await refreshAll(result.signal_id || selectedSignalId)
    })
  }, [canOperateSignalOps, operateDisabledReason, refreshAll, runTask, selectedSignalId])

  const handleDailyReview = useCallback(() => {
    void runTask('daily-review', async () => {
      if (!canOperateSignalOps) throw new Error(operateDisabledReason)
      const result = await runAutoPaperTradingDailyReview({ reviewer: 'SignalOpsPage' })
      setDailyReview(result)
      setAutoConfig(result.config)
      setForm(configToForm(result.config))
      setNotice(displayMessage(result.message) || `收盘复盘：${displayCode(result.status)}`)
      await refreshAll(result.config.signal_id || selectedSignalId)
    })
  }, [canOperateSignalOps, operateDisabledReason, refreshAll, runTask, selectedSignalId])

  const handleCommand = useCallback((symbol: string, command: AutoPaperTradingCommandResult extends never ? never : 'FORCE_OPEN_BUY' | 'FORCE_CLOSE' | 'REMOVE_SYMBOL' | 'FORCE_CLOSE_AND_REMOVE') => {
    void runTask(command, async () => {
      if (!canOperateSignalOps) throw new Error(operateDisabledReason)
      const result = await runAutoPaperTradingCommand({
        symbol,
        command,
        reason: `SignalOps 控制台执行：${displayCode(command)}`,
      })
      setCommandResult(result)
      setNotice(displayMessage(result.message) || `${displayCode(command)}：${displayCode(result.status)}`)
      await refreshAll(result.signal_id || selectedSignalId)
    })
  }, [canOperateSignalOps, operateDisabledReason, refreshAll, runTask, selectedSignalId])

  const handleUpdateConditions = useCallback(() => {
    void runTask('update-conditions', async () => {
      if (!canOperateSignalOps) throw new Error(operateDisabledReason)
      if (!selectedSignalId) throw new Error('请先选择一个信号。')
      await updateSignalConditions(selectedSignalId, {
        trigger_conditions: textToList(editable.triggerConditions),
        invalidation_conditions: textToList(editable.invalidationConditions),
        review_fields: textToList(editable.reviewFields),
      })
      setNotice('信号条件已更新。')
      await refreshAll(selectedSignalId)
    })
  }, [canOperateSignalOps, editable, operateDisabledReason, refreshAll, runTask, selectedSignalId])

  const handleTransition = useCallback(() => {
    void runTask('transition', async () => {
      if (!canOperateSignalOps) throw new Error(operateDisabledReason)
      if (!selectedSignalId) throw new Error('请先选择一个信号。')
      await transitionSignal(selectedSignalId, {
        target_status: editable.transitionTarget,
        actor: 'SignalOpsPage',
        reason: `人工流转生命周期到 ${displayCode(editable.transitionTarget)}`,
      })
      setNotice(`信号已流转到${displayCode(editable.transitionTarget)}。`)
      await refreshAll(selectedSignalId)
    })
  }, [canOperateSignalOps, editable.transitionTarget, operateDisabledReason, refreshAll, runTask, selectedSignalId])

  const handleReview = useCallback(() => {
    void runTask('review', async () => {
      if (!canOperateSignalOps) throw new Error(operateDisabledReason)
      if (!selectedSignalId) throw new Error('请先选择一个信号。')
      await reviewSignal(selectedSignalId, {
        reviewer: 'human',
        review_type: 'MANUAL',
        decision: 'REVIEWED',
        note: editable.reviewNote || '人工 SignalOps 复核。',
        review_fields: textToList(editable.reviewFields),
      })
      setNotice('人工复核已记录。')
      await refreshAll(selectedSignalId)
    })
  }, [canOperateSignalOps, editable.reviewFields, editable.reviewNote, operateDisabledReason, refreshAll, runTask, selectedSignalId])

  const handleCreateResearchEvidence = useCallback(() => {
    void runTask('create-research-evidence', async () => {
      if (!canWriteSignalOps) throw new Error(writeDisabledReason)
      if (!researchIterationId) throw new Error('Open SignalOps from a Research iteration before creating evidence.')
      const signalId = selectedSignal?.signal_id || selectedSignalId
      if (!signalId) throw new Error('Select a SignalOps signal before creating evidence.')
      setResearchEvidenceNotice(null)
      const result = await createResearchSignalOpsEvidence(signalId, {
        iteration_id: researchIterationId,
        reviewer: 'SignalOpsPage',
        note: `Attach SignalOps tick evidence from ${signalId}.`,
      })
      setResearchEvidenceNotice({
        iterationId: result.iteration.iteration_id,
        evidenceCount: result.verdict_inputs.evidence.length,
        engineVerdict: result.verdict_inputs.engine_verdict,
        canAccept: result.verdict_inputs.can_accept_feedback,
        blockers: result.verdict_inputs.blocking_reasons,
        evidenceUsage: result.evidence_usage,
        supportingOnly: result.supporting_only,
        simulationOnly: result.simulation_only,
        isRealTrade: result.is_real_trade,
        strongConclusionAllowed: result.strong_conclusion_allowed,
      })
      setNotice(
        `Research evidence attached to ${compactId(result.iteration.iteration_id)}; verdict inputs now include ${result.verdict_inputs.evidence.length} evidence item(s).`,
      )
      await refreshAll(signalId)
    })
  }, [canWriteSignalOps, refreshAll, researchIterationId, runTask, selectedSignal, selectedSignalId, writeDisabledReason])

  const handleQueueReviewDecision = useCallback((item: SignalOpsReviewQueueItem, decision: SignalOpsReviewDecision) => {
    void runTask(`review-${decision}`, async () => {
      if (!canOperateSignalOps) throw new Error(operateDisabledReason)
      setSelectedReviewItemKey(reviewItemKey(item))
      const result = await recordAutoPaperTradingReviewDecision({
        queue_item_id: item.queue_item_id || item.id,
        experiment_id: item.experiment_id,
        signal_id: item.signal_id || undefined,
        symbol: item.symbol,
        action: backendActionForReviewDecision(decision),
        reviewer: 'human',
        reason: `${REVIEW_DECISION_LABELS[decision]}: ${item.reason}`,
        evidence_refs: Array.isArray(item.evidence_package?.evidence_links)
          ? item.evidence_package.evidence_links as Array<Record<string, unknown>>
          : [],
        review_fields: [
          'review_queue_state',
          'persistent_review_decision',
          'system_auto_run_human_review_only',
          `candidate_status:${item.candidate_status || '-'}`,
          `action:${item.latest_action}`,
          `simulation_only:${yesNo(item.simulation_only)}`,
          `is_real_trade:${yesNo(item.is_real_trade)}`,
        ],
      })
      setAutoConfig(result.config)
      setForm(configToForm(result.config))
      setNotice(`${item.symbol} ${REVIEW_DECISION_LABELS[decision]}已记录。`)
      await refreshAll(item.signal_id || selectedSignalId)
    })
  }, [canOperateSignalOps, operateDisabledReason, refreshAll, runTask, selectedSignalId])

  const handleVerifyReviewEventExport = useCallback(() => {
    void runTask('verify-review-event-export', async () => {
      if (!canOperateSignalOps) throw new Error(operateDisabledReason)
      const bundle = await getAutoPaperTradingReviewDecisionEvents(100)
      const verification = await verifyAutoPaperTradingReviewDecisionEventExport(bundle)
      setReviewExportVerification(verification)
      setNotice(`Review event export verification: ${displayCode(verification.status)} / events ${fmtNumber(verification.event_count || 0, 0)}`)
    })
  }, [canOperateSignalOps, operateDisabledReason, runTask])

  const handleHandoffReviewEventExport = useCallback(() => {
    void runTask('handoff-review-event-export', async () => {
      if (!canOperateSignalOps) throw new Error(operateDisabledReason)
      const handoff = await handoffAutoPaperTradingReviewDecisionEvents(100)
      setReviewExportHandoff(handoff)
      const handoffShipperStatus = asRecord(handoff.shipper_status)
      if (Object.keys(handoffShipperStatus).length > 0) {
        setAutoStatus((current) => ({
          ...(current || {}),
          review_decision_event_ledger: {
            ...asRecord(current?.review_decision_event_ledger),
            handoff_shipper_status: handoffShipperStatus,
          },
        } as AutoPaperTradingStatusResponse))
      }
      await refreshAll(selectedSignalId)
      const suffix = handoff.handoff_id ? ` / ${compactId(handoff.handoff_id)}` : ''
      setNotice(`Review event export handoff: ${displayCode(handoff.status)}${suffix}`)
    })
  }, [canOperateSignalOps, operateDisabledReason, refreshAll, runTask, selectedSignalId])

  const renderSignalListItem = (signal: SignalItem, variant: SignalListItemVariant = 'latest') => {
    const itemClass = signal.signal_id === selectedSignalId
      ? 'border-cyan-400 bg-cyan-50'
      : variant === 'history'
        ? 'border-slate-200 bg-slate-50 hover:bg-white'
        : variant === 'auto-paper'
          ? 'border-emerald-200 bg-emerald-50/70 hover:bg-emerald-50'
          : 'border-slate-200 bg-white hover:bg-slate-50'
    return (
      <button
        key={signal.signal_id}
        type="button"
        className={`min-w-0 w-full rounded-lg border p-3 text-left transition ${itemClass}`}
        onClick={() => handleSelectSignal(signal.signal_id)}
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="min-w-0 break-words font-medium text-slate-950">{signal.symbol} {signal.stock_name || ''}</div>
          <Badge status={signal.status}>{displayCode(signal.status)}</Badge>
        </div>
        <div className="mt-2 grid gap-2 text-xs text-slate-500 md:grid-cols-2">
          <span>信号 {compactId(signal.signal_id)}</span>
          <span>更新 {fmtDate(signal.updated_at)}</span>
          <span>风控 {signal.risk_passed ? '通过' : '等待'} / DVG {displayCode(signal.dvg_status)}</span>
          <span>QIAM {displayCode(signal.qiam_status)} / 执行 {yesNo(signal.execution_reachable)}</span>
        </div>
      </button>
    )
  }

  const poolPnlText = poolOverview.pnlRate === null
    ? fmtSignedMoney(poolOverview.totalFloatingPnl)
    : `${fmtSignedMoney(poolOverview.totalFloatingPnl)} / ${fmtNumber(poolOverview.pnlRate, 2)}%`
  const holdingPnlText = poolOverview.holdingPnlRate === null
    ? '-'
    : `${fmtSignedMoney(poolOverview.totalFloatingPnl)} / ${fmtNumber(poolOverview.holdingPnlRate, 2)}%`
  const topReviewItems = filteredReviewQueue.slice(0, 3)

  return (
    <div className="space-y-5">
      <section data-testid="signalops-console" className="overflow-hidden rounded-lg border border-slate-200 bg-white/90 shadow-sm shadow-slate-200/60">
        <div className="border-b border-slate-200 bg-slate-50/60 px-4 py-4 sm:px-5 lg:px-6">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
            <div className="min-w-0">
              <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">SignalOps 控制台</div>
              <h1 className="mt-1 text-2xl font-semibold leading-tight text-slate-950 sm:text-3xl">系统自动运行</h1>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
                自动模拟股票池、生命周期审查和策略复盘集中在这里；写操作仍需要角色权限，并且只进入模拟沙箱。
              </p>
            </div>
            <div className="flex min-w-0 flex-col gap-3 xl:items-end">
              <div className="flex flex-wrap gap-2">
                <Badge status={automationSummary.simulationOnly ? 'PASS' : 'WARN'} className="rounded-md">仅模拟：是</Badge>
                <Badge status={automationSummary.isRealTrade ? 'ERROR' : 'WAIT'} className="rounded-md">真实交易：否</Badge>
                <Badge status={automationSummary.healthTone === 'bad' ? 'ERROR' : automationSummary.healthTone === 'good' ? 'PASS' : 'WARN'} className="rounded-md">运行健康：{displayCode(automationSummary.healthStatus)}</Badge>
                <Badge status={automationSummary.pendingReviewCount > 0 ? 'WARN' : 'PASS'} className="rounded-md">待审查 {automationSummary.pendingReviewCount}</Badge>
                <Badge status="PASS" className="rounded-md">低风险自动审批：开</Badge>
              </div>
              <div className="flex w-full flex-wrap gap-2 xl:justify-end">
                <ActionButton onClick={() => void refreshAll(selectedSignalId)} disabled={loading || Boolean(busy)} icon={<RefreshCw size={16} />}>
                  刷新
                </ActionButton>
                <ActionButton
                  onClick={() => setIsReviewWindowOpen(true)}
                  disabled={loading && reviewWindowState.totalCount === 0}
                  icon={<Eye size={16} />}
                  variant="primary"
                  testId="signalops-open-review-window"
                >
                  打开审查窗口
                </ActionButton>
                <ActionButton onClick={() => setIsBoundaryWindowOpen(true)} disabled={Boolean(busy)} icon={<Wrench size={16} />} testId="signalops-open-boundary">
                  边界设置 / 异常接管
                </ActionButton>
              </div>
            </div>
          </div>
          <div data-testid="signalops-current-run-bridge" className="mt-4 rounded-lg border border-cyan-100 bg-white/80 p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="text-sm font-semibold text-slate-950">当前分析桥接</div>
              <ActionButton onClick={handleCreateFromRun} disabled={!bridgeRun || isLinkedRunPending || Boolean(busy) || !canWriteSignalOps} title={writeDisabledReason} icon={<Plus size={16} />}>
                创建信号
              </ActionButton>
            </div>
            {isLinkedRunPending ? (
              <div data-testid="signalops-current-run-loading" className="mt-3 text-sm text-slate-500">
                正在加载分析运行...
                {linkedRunId ? <span className="ml-2 break-all font-mono">{linkedRunId}</span> : null}
              </div>
            ) : bridgeRun ? (
              <div className="mt-3 space-y-3 text-sm text-slate-700">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge status={bridgeRun.status}>{bridgeRun.status}</Badge>
                  <span data-testid="signalops-current-run-symbol" className="font-medium">{bridgeRun.stockCode} {bridgeRun.stockName}</span>
                </div>
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                  <Metric label="运行" value={<span data-testid="signalops-current-run-id" className="break-all">{bridgeRun.runId}</span>} />
                  <Metric label="最终动作" value={displayCode(bridgeRun.finalAction)} />
                  <Metric label="信号状态" value={displayCode(bridgeRun.signalOps.signalStatus)} />
                  <Metric label="审计" value={compactId(bridgeRun.signalOps.auditId)} />
                </div>
              </div>
            ) : (
              <div className="mt-3 text-sm text-slate-500">当前没有选中的分析运行。</div>
            )}
          </div>
          <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
            <Metric label="托管股票数" value={automationSummary.managedStockCount || '-'} />
            <Metric label="实时盈亏" value={poolPnlText} tone={pnlTone(poolOverview.totalFloatingPnl)} />
            <Metric label="持仓市值" value={fmtMoney(poolOverview.totalMarketValue)} />
            <Metric label="可用现金" value={fmtMoney(poolOverview.totalCash)} tone="good" />
            <Metric label="最近自动复盘" value={automationSummary.lastAutoReview} />
            <Metric label="当前候选状态" value={displayCode(automationSummary.candidateStatus)} tone={automationSummary.pendingReviewCount > 0 ? 'warn' : 'default'} />
          </div>
          <div className="mt-4 grid gap-3 lg:grid-cols-2">
            <div className="rounded-md border border-slate-200 bg-white px-3 py-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="text-sm font-semibold text-slate-950">自动化模块</div>
                <Badge status={asRecord(automationModules.live).execution_enabled ? 'ERROR' : 'WAIT'}>
                  实盘未启用
                </Badge>
              </div>
              <div className="mt-3 grid gap-2 sm:grid-cols-3">
                <Metric label="当前模块" value={displayModuleName(automationModules.active_module || 'simulation')} tone="good" />
                <Metric label="模拟模块" value={displayCode(String(asRecord(automationModules.simulation).status || 'ACTIVE'))} tone="good" />
                <Metric label="实盘模块" value={displayCode(String(asRecord(automationModules.live).status || 'CONFIGURED_DISABLED'))} tone="warn" />
                <Metric label="组合快照" value={displayCode(String(latestPortfolioSnapshot.sourceType || '-'))} tone={Object.keys(latestPortfolioSnapshot).length ? 'good' : 'default'} />
                <Metric label="快照持仓" value={String(latestPortfolioSnapshot.positionCount ?? '-')} />
                <Metric label="快照ID" value={String(latestPortfolioSnapshot.snapshotId || '-')} />
              </div>
            </div>
            <div className="rounded-md border border-slate-200 bg-white px-3 py-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="text-sm font-semibold text-slate-950">确定性证据</div>
                <Badge status={Object.keys(latestModuleEvidence).length ? 'PASS' : 'WAIT'}>
                  {Object.keys(latestModuleEvidence).length ? '已就绪' : '等待中'}
                </Badge>
              </div>
              <div className="mt-3 grid gap-2 sm:grid-cols-3">
                <Metric label="量化核心" value={displayCode(String(asRecord(asRecord(latestModuleEvidence.quantCore).coreInterpretation).status || '-'))} />
                <Metric label="QIAM" value={displayCode(String(asRecord(latestModuleEvidence.qiam).finalBuySuitability || '-'))} />
                <Metric label="大模型策略" value={displayMessage(String(latestModuleEvidence.llm_policy || '-'))} />
                <Metric label="DVG" value={displayCode(String(asRecord(latestModuleEvidence.dvg).status || '-'))} />
                <Metric label="风险" value={displayCode(String(asRecord(latestModuleEvidence.riskFirewall).status || '-'))} />
                <Metric label="执行" value={displayCode(String(asRecord(latestModuleEvidence.execution).status || '-'))} />
              </div>
            </div>
          </div>
        </div>

        <div className="grid gap-4 px-4 py-4 sm:px-5 lg:grid-cols-[minmax(0,1.15fr)_minmax(300px,0.85fr)] lg:px-6">
          <ManagedPoolSnapshotPanel
            symbols={configuredSymbols}
            config={autoConfig}
            stockNameSources={stockNameSources}
            portfolios={poolPortfolios}
            positions={poolPositions}
            loading={loading}
          />
          <div className="min-w-0 rounded-lg border border-slate-200 bg-white p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="text-sm font-semibold text-slate-950">验证与策略状态</div>
                <div className="mt-1 text-xs text-slate-500">实验验证、随机验证和调参只影响模拟配置。</div>
              </div>
              <Badge status={automationSummary.randomValidationApplied ? 'PASS' : 'WAIT'}>
                {automationSummary.randomValidationApplied ? '已微调' : '观察中'}
              </Badge>
            </div>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <Metric label="最近实验验证" value={automationSummary.lastExperimentValidation} />
              <Metric label="最近随机验证" value={automationSummary.lastRandomValidation} tone={automationSummary.randomValidationApplied ? 'good' : 'default'} />
              <Metric label="随机验证证据" value={displayCode(automationSummary.randomValidationEvidence)} tone={automationSummary.randomValidationEvidence === 'LOW' ? 'warn' : 'default'} />
              <Metric label="随机微调" value={automationSummary.randomValidationRan ? (automationSummary.randomValidationApplied ? '已应用' : '未应用') : '未运行'} tone={automationSummary.randomValidationApplied ? 'good' : 'default'} />
              <Metric label="持仓总盈亏" value={holdingPnlText} tone={pnlTone(poolOverview.totalFloatingPnl)} />
              <Metric label="总资产" value={fmtMoney(poolOverview.totalAssets)} />
            </div>
          </div>
        </div>
      </section>

      {(error || notice) && (
        <div className={`rounded-lg border px-4 py-3 text-sm ${error ? 'border-rose-200 bg-rose-50 text-rose-800' : 'border-emerald-200 bg-emerald-50 text-emerald-800'}`}>
          {error || notice}
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <Card
          title="审查队列入口"
          action={<Badge status={automationSummary.pendingReviewCount > 0 ? 'WARN' : 'PASS'}>待审查 {automationSummary.pendingReviewCount}</Badge>}
        >
          <div className="flex flex-col gap-3">
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs leading-5 text-slate-600">
              队列从生命周期、回测验证、随机验证和模拟订单中归并；实际审查动作集中在审查窗口。
            </div>
            {topReviewItems.length ? topReviewItems.map((item) => (
              <button
                key={reviewItemKey(item)}
                type="button"
                className={`min-w-0 rounded-lg border p-3 text-left transition ${reviewItemKey(item) === (activeReviewItem ? reviewItemKey(activeReviewItem) : '') ? 'border-cyan-400 bg-cyan-50' : 'border-slate-200 bg-white hover:bg-slate-50'}`}
                onClick={() => handleSelectReviewItem(item)}
              >
                <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
                  <div className="min-w-0 break-words text-sm font-semibold text-slate-950">{item.title}</div>
                  <Badge status={item.pending ? 'WAIT' : 'PASS'}>{item.pending ? '待审查' : '已审查'}</Badge>
                </div>
                <div className="mt-2 break-words text-xs leading-5 text-slate-600">{item.reason}</div>
                <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-500">
                  <span>{item.symbol}</span>
                  <span>{displayCode(item.candidate_status || item.status)}</span>
                  <span>{fmtDate(item.updated_at)}</span>
                </div>
              </button>
            )) : (
              <div className="rounded-lg border border-dashed border-slate-200 p-4 text-sm text-slate-500">
                暂无待审查 SignalOps 记录。
              </div>
            )}
            <div className="flex flex-wrap gap-2">
              <ActionButton onClick={() => setIsReviewWindowOpen(true)} disabled={loading && reviewWindowState.totalCount === 0} icon={<Eye size={16} />} variant="primary" testId="signalops-open-review-window">
                打开审查窗口
              </ActionButton>
              <ActionButton onClick={() => setIsBoundaryWindowOpen(true)} disabled={Boolean(busy)} icon={<Wrench size={16} />}>
                进入边界设置
              </ActionButton>
            </div>
          </div>
        </Card>

        <Card title="选中信号详情">
          {selectedSignal ? (
            <div data-testid="signalops-selected-signal-detail" className="space-y-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="break-words text-lg font-semibold text-slate-950">{selectedSignal.symbol} {selectedSignal.stock_name || ''}</div>
                  <div data-testid="signalops-selected-signal-id" className="mt-1 text-xs text-slate-500">信号 {compactId(selectedSignal.signal_id)} / 更新 {fmtDate(selectedSignal.updated_at)}</div>
                </div>
                <Badge status={selectedSignal.status}>{displayCode(selectedSignal.status)}</Badge>
              </div>
              <div className="grid gap-3 md:grid-cols-4">
                <Metric label="模拟组合" value={portfolio ? fmtMoney(portfolio.available_cash) : '未创建'} />
                <Metric label="持仓数" value={positions.length} />
                <Metric label="订单数" value={selectedVisibleOrders.length} />
                <Metric label="执行可达" value={yesNo(selectedSignal.execution_reachable)} tone={selectedSignal.execution_reachable ? 'good' : 'warn'} />
              </div>

              {selectedSignal.blocked_reason ? (
                <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">{selectedSignal.blocked_reason}</div>
              ) : null}

              {researchIterationId ? (
                <div className="space-y-2 rounded-lg border border-cyan-200 bg-cyan-50 px-3 py-2 text-xs text-cyan-900">
                  <div data-testid="signalops-research-evidence-context" className="flex flex-wrap items-center justify-between gap-2">
                    <span>Research iteration {compactId(researchIterationId)}</span>
                    <ActionButton
                      onClick={handleCreateResearchEvidence}
                      disabled={Boolean(busy) || !canWriteSignalOps}
                      title={writeDisabledReason}
                      icon={<FlaskConical size={14} />}
                      testId="signalops-create-research-evidence"
                    >
                      Create Research evidence
                    </ActionButton>
                  </div>
                  {researchEvidenceNotice ? (
                    <div data-testid="signalops-research-evidence-boundary" className="leading-5">
                      <div>Research evidence attached to {compactId(researchEvidenceNotice.iterationId)}; verdict inputs now include {researchEvidenceNotice.evidenceCount} evidence item(s).</div>
                      <div>Engine verdict: {researchEvidenceNotice.engineVerdict}; can accept: {String(researchEvidenceNotice.canAccept)}; blockers: {researchEvidenceNotice.blockers.length}.</div>
                      <div>evidence_usage={researchEvidenceNotice.evidenceUsage} / supporting_only={String(researchEvidenceNotice.supportingOnly)} / simulation_only={String(researchEvidenceNotice.simulationOnly)} / is_real_trade={String(researchEvidenceNotice.isRealTrade)} / strong_conclusion_allowed={String(researchEvidenceNotice.strongConclusionAllowed)} / SIM_*</div>
                    </div>
                  ) : null}
                </div>
              ) : null}

              <div className="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_minmax(280px,0.42fr)] 2xl:items-start">
                <div className="space-y-3">
                  <AiStrategyReviewPanel review={aiStrategyReview} config={autoConfig} selectedSignal={selectedSignal} />
                  <PerformanceQualityPanel
                    config={autoConfig}
                    selectedSymbol={selectedSignal.symbol}
                  />
                  {decisionCard.action ? <DecisionCardPanel card={decisionCard} /> : null}
                </div>
                <SignalHistoryPanel detail={detail} />
              </div>

              <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
                <span>条件编辑、状态流转和人工复核属于边界操作。</span>
                <ActionButton onClick={() => setIsBoundaryWindowOpen(true)} disabled={Boolean(busy)} icon={<Wrench size={14} />}>
                  打开人工干预
                </ActionButton>
              </div>
              <OrdersPanel key={selectedSignalId} orders={selectedVisibleOrders} />
            </div>
          ) : (
            <div className="text-sm text-slate-500">请选择一条 SignalOps 生命周期记录，用于查看条件、复核和模拟订单。</div>
          )}
        </Card>
      </div>

      <Card title="信号列表">
        <div className="grid gap-3 lg:grid-cols-2 xl:grid-cols-3">
          {signalGroups.length === 0 ? (
            <div className="rounded-lg border border-dashed border-slate-200 p-4 text-sm text-slate-500">暂无 SignalOps 生命周期记录。</div>
          ) : signalGroups.map((group) => {
            const selectedInHistory = group.history.some((signal) => signal.signal_id === selectedSignalId)
            const isExpanded = expandedSignalKeys.includes(group.key) || selectedInHistory
            const selectedHistory = group.history.find((signal) => signal.signal_id === selectedSignalId)
            const visibleHistory = selectedHistory
              ? [selectedHistory, ...group.history.filter((signal) => signal.signal_id !== selectedSignalId).slice(0, 2)]
              : group.history.slice(0, 3)
            const compressedHistoryCount = Math.max(0, group.history.length - visibleHistory.length)
            return (
              <div key={group.key} className="min-w-0 space-y-2">
                {renderSignalListItem(group.latest)}
                {group.history.length > 0 ? (
                  <div className="space-y-2 border-l border-slate-200 pl-3">
                    <button
                      type="button"
                      className="inline-flex items-center gap-1 text-xs font-medium text-slate-600 hover:text-cyan-700"
                      onClick={() => toggleSignalHistory(group.key)}
                    >
                      {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                      {isExpanded ? '收起历史记录' : `显示最近 ${Math.min(group.history.length, 3)} 条历史记录`}
                    </button>
                    {isExpanded ? (
                      <div className="space-y-2">
                        {visibleHistory.map((signal) => renderSignalListItem(signal, 'history'))}
                        {compressedHistoryCount > 0 ? (
                          <div className="rounded-md border border-dashed border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-500">
                            已自动压缩 {compressedHistoryCount} 条更早历史记录，不再逐条展开。
                          </div>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </div>
            )
          })}
        </div>
      </Card>

      <Card title="自动模拟记录">
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-slate-600">
            <span>自动模拟交易生成的信号记录单独展示，不计入上方生命周期历史项目。</span>
            <Badge status={autoPaperSignals.length > 0 ? 'PASS' : 'WAIT'}>{autoPaperSignals.length} 条</Badge>
          </div>
          <div className="grid gap-3 lg:grid-cols-2 xl:grid-cols-3">
            {visibleAutoPaperSignals.length === 0 ? (
              <div className="rounded-lg border border-dashed border-slate-200 p-4 text-sm text-slate-500">暂无自动模拟记录。</div>
            ) : visibleAutoPaperSignals.map((signal) => renderSignalListItem(signal, 'auto-paper'))}
          </div>
          {autoPaperSignals.length > visibleAutoPaperSignals.length ? (
            <div className="rounded-md border border-dashed border-emerald-200 bg-emerald-50/70 px-3 py-2 text-xs text-emerald-700">
              已自动压缩 {autoPaperSignals.length - visibleAutoPaperSignals.length} 条更早自动模拟记录，不再进入生命周期历史项目。
            </div>
          ) : null}
        </div>
      </Card>

      <div className="grid gap-4 xl:grid-cols-2">
        <AutomationLogPanel
          autoConfig={autoConfig}
          autoStatus={autoStatus}
          role={operator.role}
          reviewQueue={reviewQueue}
          tickResult={tickResult}
          dailyReview={dailyReview}
          commandResult={commandResult}
          reviewExportVerification={reviewExportVerification}
          reviewExportHandoff={reviewExportHandoff}
          onVerifyReviewEventExport={handleVerifyReviewEventExport}
          onHandoffReviewEventExport={handleHandoffReviewEventExport}
          verificationBusy={busy === 'verify-review-event-export'}
          handoffBusy={busy === 'handoff-review-event-export'}
          canVerifyReviewEventExport={canOperateSignalOps}
          verifyDisabledReason={operateDisabledReason}
        />
        <DecisionTreePanel
          state={decisionTreeState}
          symbols={configuredSymbols}
          tickResult={tickResult}
          dailyReview={dailyReview}
        />
      </div>

      {reviewWindowState.isOpen ? (
        <ReviewWindow
          state={reviewWindowState}
          items={filteredReviewQueue}
          filters={reviewFilters}
          filterOptions={reviewFilterOptions}
          selectedItemKey={activeReviewItem ? reviewItemKey(activeReviewItem) : ''}
          loading={loading}
          busy={Boolean(busy)}
          canReview={manualInterventionGroup.canOperate}
          disabledReason={manualInterventionGroup.operateDisabledReason}
          onClose={() => setIsReviewWindowOpen(false)}
          onFiltersChange={setReviewFilters}
          onSelect={handleSelectReviewItem}
          onDecision={handleQueueReviewDecision}
        />
      ) : null}

      {isBoundaryWindowOpen ? (
        <BoundaryInterventionWindow
          role={operator.role}
          onClose={() => setIsBoundaryWindowOpen(false)}
        >
          <Card
            title="运行控制"
            action={(
              <ActionButton onClick={() => void refreshAll(selectedSignalId)} disabled={loading || Boolean(busy)} icon={<RefreshCw size={16} />}>
                刷新
              </ActionButton>
            )}
          >
            <div className="grid gap-3 md:grid-cols-4">
              <Metric label="系统自动运行" value={autoStatus?.loop_running ? '运行中' : '已停止'} tone={autoStatus?.loop_running ? 'good' : 'warn'} />
              <Metric label="健康状态" value={displayCode(autoStatus?.loop_health)} />
              <Metric label="上次跟进" value={fmtDate(autoStatus?.last_tick_at || autoConfig.last_tick_at)} />
              <Metric label="下次跟进" value={autoStatus?.seconds_until_next_tick == null ? '-' : `${autoStatus.seconds_until_next_tick} 秒`} />
            </div>
            <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs leading-5 text-slate-600">
              A 股规则：T+1、交易时段门、涨跌停方向约束已启用；佣金 {rateToPercentText(autoConfig.commission_rate)}%，低于 {fmtMoney(autoConfig.commission_min_trade_value)} 元按 {fmtMoney(autoConfig.commission_min_fee)} 元收取；卖出印花税 {rateToPercentText(autoConfig.stamp_duty_rate ?? 0.0005)}%。仅模拟：是；真实交易：否。
            </div>
            <OperatorPolicyPanel
              role={operator.role}
              operatorId={operator.id}
              canWrite={canWriteSignalOps}
              canOperate={canOperateSignalOps}
              canManageConfig={canManageSignalOpsConfig}
              writeDisabledReason={writeDisabledReason}
              operateDisabledReason={operateDisabledReason}
              configDisabledReason={configDisabledReason}
            />
            <details data-testid="signalops-manual-ops" className="mt-3 rounded-lg border border-slate-200 p-3">
              <summary className="cursor-pointer text-sm font-medium text-slate-700">人工接管/高级操作</summary>
              <div className="mt-3 flex flex-wrap gap-2">
                <ActionButton onClick={handleRunTick} disabled={Boolean(busy) || !canOperateSignalOps} title={operateDisabledReason} icon={<Play size={16} />} testId="signalops-run-tick">
                  强制跟进
                </ActionButton>
                <ActionButton onClick={handleDailyReview} disabled={Boolean(busy) || !canOperateSignalOps} title={operateDisabledReason} icon={<FlaskConical size={16} />} testId="signalops-run-daily-review">
                  收盘复盘
                </ActionButton>
              </div>
              <div className="mt-3">
                <ResultSnapshot tickResult={tickResult} dailyReview={dailyReview} commandResult={commandResult} />
              </div>
            </details>
          </Card>

          <Card title="托管配置与接入">
            <div className="grid gap-4 lg:grid-cols-2">
              <div className="space-y-3">
                <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
                  <TextInput
                    label="股票代码"
                    value={form.newSymbol}
                    onChange={(value) => setFormValue('newSymbol', value)}
                    onKeyDown={handleSymbolInputKeyDown}
                    placeholder="603663"
                  />
                  <ActionButton
                    onClick={handleAddSymbolToPool}
                    disabled={Boolean(busy) || !canManageSignalOpsConfig || splitList(form.newSymbol).length === 0 || !form.initialBuySignal.trim() || !form.finalSellSignal.trim()}
                    title={configDisabledReason}
                    icon={<Plus size={16} />}
                    variant="primary"
                  >
                    加入 AI 托管
                  </ActionButton>
                </div>
                <div className="grid gap-3 md:grid-cols-2">
                  <TextArea
                    label="最初买入信号"
                    value={form.initialBuySignal}
                    onChange={(value) => setFormValue('initialBuySignal', value)}
                    placeholder="例如：放量突破且 DVG/QIAM 未阻断，允许 AI 建立模拟观察仓"
                  />
                  <TextArea
                    label="最终卖出信号"
                    value={form.finalSellSignal}
                    onChange={(value) => setFormValue('finalSellSignal', value)}
                    placeholder="例如：跌破关键支撑、复盘失效或 AI 判断风险收益不再成立"
                  />
                </div>
                <div className="flex flex-wrap gap-2">
                  {configuredSymbols.length > 0 ? configuredSymbols.map((symbol, index) => (
                    <span key={symbol} className="inline-flex max-w-full items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-xs font-medium text-slate-700">
                      <span>{symbol}</span>
                      {configuredSymbolNames[index] && configuredSymbolNames[index] !== symbol ? <span className="truncate text-slate-500">{configuredSymbolNames[index]}</span> : null}
                    </span>
                  )) : (
                    <span className="text-xs text-slate-500">股票池暂无代码。</span>
                  )}
                </div>
                <details className="rounded-lg border border-slate-200 p-3">
                  <summary className="cursor-pointer text-sm font-medium text-slate-700">高级资金、运行和手续费参数</summary>
                  <div className="mt-3 grid gap-3 md:grid-cols-2">
                    <TextInput label="股票池资金" value={form.initialCash} onChange={(value) => setFormValue('initialCash', value)} inputMode="decimal" helperText={numericFieldHelp('initialCash')} error={formValidationErrors.initialCash} />
                    <TextInput label="最小下单金额" value={form.minOrderValue} onChange={(value) => setFormValue('minOrderValue', value)} inputMode="decimal" helperText={numericFieldHelp('minOrderValue')} error={formValidationErrors.minOrderValue} />
                    <TextInput label="跟进间隔（秒）" value={form.tickIntervalSeconds} onChange={(value) => setFormValue('tickIntervalSeconds', value)} inputMode="numeric" helperText={numericFieldHelp('tickIntervalSeconds')} error={formValidationErrors.tickIntervalSeconds} />
                    <TextInput label="最小下单间隔（秒）" value={form.minOrderIntervalSeconds} onChange={(value) => setFormValue('minOrderIntervalSeconds', value)} inputMode="numeric" helperText={numericFieldHelp('minOrderIntervalSeconds')} error={formValidationErrors.minOrderIntervalSeconds} />
                    <TextInput label="实时行情间隔（秒）" value={form.realtimeIntervalSeconds} onChange={(value) => setFormValue('realtimeIntervalSeconds', value)} inputMode="numeric" helperText={numericFieldHelp('realtimeIntervalSeconds')} error={formValidationErrors.realtimeIntervalSeconds} />
                    <TextInput label="K 线间隔（秒）" value={form.klineIntervalSeconds} onChange={(value) => setFormValue('klineIntervalSeconds', value)} inputMode="numeric" helperText={numericFieldHelp('klineIntervalSeconds')} error={formValidationErrors.klineIntervalSeconds} />
                    <TextInput label="周/月线间隔（秒）" value={form.weeklyMonthlyIntervalSeconds} onChange={(value) => setFormValue('weeklyMonthlyIntervalSeconds', value)} inputMode="numeric" helperText={numericFieldHelp('weeklyMonthlyIntervalSeconds')} error={formValidationErrors.weeklyMonthlyIntervalSeconds} />
                    <TextInput label="每日 LLM 调用次数" value={form.maxLlmCallsPerDay} onChange={(value) => setFormValue('maxLlmCallsPerDay', value)} inputMode="numeric" helperText={numericFieldHelp('maxLlmCallsPerDay')} error={formValidationErrors.maxLlmCallsPerDay} />
                    <TextInput label="LLM 最小间隔（分钟）" value={form.minLlmIntervalMinutes} onChange={(value) => setFormValue('minLlmIntervalMinutes', value)} inputMode="numeric" helperText={numericFieldHelp('minLlmIntervalMinutes')} error={formValidationErrors.minLlmIntervalMinutes} />
                  </div>
                  <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-3">
                    <div className="text-xs font-semibold text-slate-700">股市交易手续费</div>
                    <div className="mt-3 grid gap-3 md:grid-cols-4">
                      <TextInput label="佣金率（%）" value={form.commissionRatePct} onChange={(value) => setFormValue('commissionRatePct', value)} placeholder="0.01" inputMode="decimal" helperText={numericFieldHelp('commissionRatePct')} error={formValidationErrors.commissionRatePct} />
                      <TextInput label="最低手续费（元）" value={form.commissionMinFee} onChange={(value) => setFormValue('commissionMinFee', value)} placeholder="5" inputMode="decimal" helperText={numericFieldHelp('commissionMinFee')} error={formValidationErrors.commissionMinFee} />
                      <TextInput label="最低计费金额（元）" value={form.commissionMinTradeValue} onChange={(value) => setFormValue('commissionMinTradeValue', value)} placeholder="50000" inputMode="decimal" helperText={numericFieldHelp('commissionMinTradeValue')} error={formValidationErrors.commissionMinTradeValue} />
                      <TextInput label="卖出印花税（%）" value={form.stampDutyRatePct} onChange={(value) => setFormValue('stampDutyRatePct', value)} placeholder="0.05" inputMode="decimal" helperText={numericFieldHelp('stampDutyRatePct')} error={formValidationErrors.stampDutyRatePct} />
                    </div>
                    <div className="mt-2 text-xs text-slate-500">
                      默认按成交金额 0.01% 收取；单笔成交金额低于 50,000 元时按 5 元收取。
                    </div>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-4">
                    <Toggle checked={form.enabled} label="启用自动托管" onChange={(value) => setFormValue('enabled', value)} />
                    <Toggle checked={form.useLlm} label="条件允许时使用 LLM" onChange={(value) => setFormValue('useLlm', value)} />
                    <Toggle checked={form.autoFill} label="自动成交模拟订单" onChange={(value) => setFormValue('autoFill', value)} />
                  </div>
                  <div className="mt-3">
                    <ActionButton onClick={handleSaveAutoConfig} disabled={Boolean(busy) || !canManageSignalOpsConfig} title={configDisabledReason} icon={<Save size={16} />} variant="primary">
                      保存高级配置
                    </ActionButton>
                  </div>
                </details>
              </div>
              {decisionCard.action ? <DecisionCardPanel card={decisionCard} /> : null}
            </div>
          </Card>

          <Card title="选中信号人工干预">
            {selectedSignal ? (
              <div className="space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="min-w-0 break-words text-sm font-semibold text-slate-950">{selectedSignal.symbol} {selectedSignal.stock_name || ''}</div>
                  <Badge status={selectedSignal.status}>{displayCode(selectedSignal.status)}</Badge>
                </div>
                <EditableSignalPanel
                  editable={editable}
                  onChange={setEditable}
                  onUpdateConditions={handleUpdateConditions}
                  onTransition={handleTransition}
                  onReview={handleReview}
                  busy={Boolean(busy)}
                  canEdit={canOperateSignalOps}
                  disabledReason={operateDisabledReason}
                />
              </div>
            ) : (
              <div className="rounded-lg border border-dashed border-slate-200 p-4 text-sm text-slate-500">
                请先在主页面或审查窗口选择一条 SignalOps 生命周期记录。
              </div>
            )}
          </Card>

          <PoolPanel
            symbols={configuredSymbols}
            config={autoConfig}
            stockNameSources={stockNameSources}
            portfolios={poolPortfolios}
            positions={poolPositions}
            orders={poolOrders}
            loading={loading}
            onCommand={handleCommand}
            busy={Boolean(busy)}
            canControl={canOperateSignalOps}
            disabledReason={operateDisabledReason}
          />
        </BoundaryInterventionWindow>
      ) : null}
    </div>
  )
}

function DecisionTreePanel({
  state,
  symbols,
  tickResult,
  dailyReview,
}: {
  state: SignalOpsDecisionTreeState
  symbols: string[]
  tickResult: AutoPaperTradingTickResult | null
  dailyReview: AutoPaperTradingDailyReviewResult | null
}) {
  const stateSymbols = asRecord(state.symbols)
  const visibleSymbols = uniqueStrings([...symbols, ...Object.keys(stateSymbols)]).slice(0, 6)
  const rows = visibleSymbols.map((symbol) => ({
    symbol,
    state: asRecord(stateSymbols[symbol]),
  }))
  const activeRow = rows.find((row) => Object.keys(asRecord(row.state.active_tree)).length > 0)
  const fallbackRow = rows.find((row) => Object.keys(asRecord(row.state.latest_closed_tree)).length > 0) || rows[0]
  const selectedRow = activeRow || fallbackRow
  const symbolState = selectedRow ? selectedRow.state : {}
  const activeTree = asRecord(symbolState.active_tree) as SignalOpsDecisionTree
  const closedTree = asRecord(symbolState.latest_closed_tree) as SignalOpsDecisionTree
  const tree = Object.keys(activeTree).length ? activeTree : closedTree
  const start = asRecord(tree.start)
  const peak = asRecord(tree.peak)
  const current = asRecord(tree.current)
  const metrics = asRecord(tree.metrics)
  const review = latestDecisionTreeReview(state, tickResult, dailyReview)
  const reviewCounts = decisionTreeReviewCounts(review)
  const tuning = asRecord(symbolState.last_tuning_audit) as SignalOpsDecisionTreeReview
  const latestTuning = Object.keys(tuning).length ? tuning : asRecord(tree.decision_tree_tuning)
  const branches = decisionTreeBranches(tree).slice(-8).reverse()
  const reviewByBranch = new Map(
    (Array.isArray(review.branch_reviews) ? review.branch_reviews : [])
      .map((item) => {
        const branchReview = asRecord(item)
        return [String(branchReview.branch_id || ''), branchReview] as const
      })
      .filter(([branchId]) => branchId),
  )
  const statuses = rows.map((row) => String(row.state.status || '').toUpperCase()).filter(Boolean)
  const hasAnyState = rows.length > 0
  const dataInsufficient = statuses.length > 0 && statuses.every((status) => status === 'DATA_INSUFFICIENT')
  const hasTree = Object.keys(tree).length > 0
  const status = String(symbolState.status || (dataInsufficient ? 'DATA_INSUFFICIENT' : hasTree ? tree.status : 'WAITING_FOR_CONFIRMED_LOW'))
  const nearEnd = Boolean(current.near_end || (Number(metrics.stagnant_days_after_peak) >= 1 && metrics.close_below_ma5))

  return (
    <div className="h-full rounded-lg border border-slate-200 bg-white p-4 text-left">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-slate-950">每日决策树</div>
          <div className="mt-1 max-w-3xl text-xs text-slate-500">
            Lifecycle starts after a confirmed stage low and closes only when peak gain stalls and close breaks MA5. Simulation only.
          </div>
        </div>
        <Badge status={status === 'ACTIVE' ? 'PASS' : status === 'DATA_INSUFFICIENT' ? 'WARN' : 'WAIT'}>{displayCode(status)}</Badge>
      </div>

      {!hasAnyState ? (
        <div className="mt-3 rounded-md border border-dashed border-slate-200 p-4 text-sm text-slate-500">
          Waiting for managed symbols and daily K-line samples.
        </div>
      ) : dataInsufficient ? (
        <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
          Daily K-line sample is not enough to confirm a lifecycle or calculate MA5.
        </div>
      ) : !hasTree ? (
        <div className="mt-3 rounded-md border border-dashed border-slate-200 p-4 text-sm text-slate-500">
          Waiting for a confirmed stage low: at least three down days followed by two rebound days without a lower low.
        </div>
      ) : (
        <>
          <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-5">
            <Metric label="标的" value={selectedRow?.symbol || '-'} />
            <Metric label="决策树" value={compactId(String(tree.tree_id || ''))} />
            <Metric label="起点低点" value={`${compactDateValue(start.date)} / ${fmtNumber(start.low, 2)}`} />
            <Metric label="峰值涨幅" value={`${compactDateValue(peak.date)} / ${fmtRate(peak.gain_pct, 2)}`} tone={Number(peak.gain_pct) > 0 ? 'good' : 'default'} />
            <Metric label="当前价 / MA5" value={`${fmtNumber(current.close, 2)} / ${fmtNumber(current.ma5, 2)}`} tone={current.close_below_ma5 ? 'warn' : 'default'} />
            <Metric label="最新涨幅" value={fmtRate(current.latest_gain_pct, 2)} tone={Number(current.latest_gain_pct) >= 0 ? 'good' : 'bad'} />
            <Metric label="停滞天数" value={fmtNumber(metrics.stagnant_days_after_peak, 0)} tone={nearEnd ? 'warn' : 'default'} />
            <Metric label="分支数" value={fmtNumber(tree.branch_count || branches.length, 0)} />
            <Metric label="接近结束" value={nearEnd ? '是' : '否'} tone={nearEnd ? 'warn' : 'good'} />
            <Metric label="真实交易" value={tree.is_real_trade ? '是' : '否'} tone={tree.is_real_trade ? 'bad' : 'good'} />
          </div>

          <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(280px,0.8fr)]">
            <div className="min-w-0 rounded-md border border-slate-200 p-3">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">分支时间线</div>
              <div className="mt-3 space-y-2">
                {branches.length ? branches.map((branch, index) => {
                  const branchReview = reviewByBranch.get(String(branch.branch_id || '')) || {}
                  const order = asRecord(branch.order_summary)
                  const blockers = Array.isArray(branch.blockers) ? branch.blockers : []
                  const branchKey = String(branch.branch_id || `${branch.trade_date}-${branch.sequence}`)
                  return (
                    <div key={`${branchKey}:${index}`} className="min-w-0 rounded-md border border-slate-200 bg-slate-50 p-3">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="min-w-0 text-sm font-medium text-slate-900">
                          {compactDateValue(branch.trade_date)} · {displayCode(branch.action)} · {fmtNumber(branch.price, 2)}
                        </div>
                        <Badge status={String(branchReview.decision_correctness || 'WAIT')}>{displayCode(branchReview.decision_correctness || 'PENDING')}</Badge>
                      </div>
                      <div className="mt-2 break-words text-xs text-slate-600">{displayMessage(branch.reason || '') || '-'}</div>
                      <div className="mt-2 grid gap-2 text-xs text-slate-500 sm:grid-cols-3">
                        <span>MA5 {fmtNumber(branch.ma5, 2)}</span>
                        <span>Return {fmtRate(branch.current_return_pct, 2)}</span>
                        <span>Order {displayCode(order.fill_status || order.error || 'NONE')}</span>
                      </div>
                      {blockers.length ? (
                        <div className="mt-2 break-words text-xs text-amber-700">{blockers.slice(0, 3).map(displayMessage).join(' / ')}</div>
                      ) : null}
                    </div>
                  )
                }) : (
                  <div className="rounded-md border border-dashed border-slate-200 p-3 text-sm text-slate-500">
                    No branch has been generated for this lifecycle yet.
                  </div>
                )}
              </div>
            </div>

            <div className="min-w-0 rounded-md border border-slate-200 p-3">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">已关闭复核</div>
              {Object.keys(review).length ? (
                <div className="mt-3 space-y-3">
                  <div className="grid gap-2 sm:grid-cols-2">
                    <Metric label="复核" value={compactId(String(review.review_id || ''))} />
                    <Metric label="知识" value={compactId(String(review.knowledge_item_id || 'pending'))} />
                    <Metric label="正确" value={reviewCounts.correct} tone="good" />
                    <Metric label="错误" value={reviewCounts.wrong} tone={reviewCounts.wrong > 0 ? 'bad' : 'default'} />
                    <Metric label="部分正确" value={reviewCounts.partial} />
                    <Metric label="已跳过" value={reviewCounts.skipped} />
                  </div>
                  <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
                    End reason: {displayCode(asRecord(review.end_context).reason || 'active')}
                  </div>
                  <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
                    Tuning: {latestTuning.applied ? 'applied to simulation' : 'not applied'} · {displayCode(latestTuning.reason)}
                  </div>
                </div>
              ) : (
                <div className="mt-3 rounded-md border border-dashed border-slate-200 p-3 text-sm text-slate-500">
                  No closed lifecycle review yet.
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}

function AutomationLogPanel({
  autoConfig,
  autoStatus,
  role,
  reviewQueue,
  tickResult,
  dailyReview,
  commandResult,
  reviewExportVerification,
  reviewExportHandoff,
  onVerifyReviewEventExport,
  onHandoffReviewEventExport,
  verificationBusy,
  handoffBusy,
  canVerifyReviewEventExport,
  verifyDisabledReason,
}: {
  autoConfig: AutoPaperTradingConfig
  autoStatus: AutoPaperTradingStatusResponse | null
  role: OperatorRole
  reviewQueue: SignalOpsReviewQueueItem[]
  tickResult: AutoPaperTradingTickResult | null
  dailyReview: AutoPaperTradingDailyReviewResult | null
  commandResult: AutoPaperTradingCommandResult | null
  reviewExportVerification: AutoPaperTradingReviewDecisionEventVerification | null
  reviewExportHandoff: AutoPaperTradingReviewDecisionEventHandoff | null
  onVerifyReviewEventExport: () => void
  onHandoffReviewEventExport: () => void
  verificationBusy: boolean
  handoffBusy: boolean
  canVerifyReviewEventExport: boolean
  verifyDisabledReason?: string
}) {
  const queueState = firstNonEmptyRecord(autoStatus?.review_queue_state, autoConfig.review_queue_state)
  const validationAttempt = latestExperimentValidationAttemptFromState(firstNonEmptyRecord(autoStatus?.experiment_validation_state, autoConfig.experiment_validation_state))
  const randomValidationState = firstNonEmptyRecord(autoStatus?.random_validation_state, autoConfig.random_validation_state)
  const latestRandomSummary = asRecord(randomValidationState.latest_summary)
  const randomAdjustment = asRecord(latestRandomSummary.applied_adjustment)
  const driftSummary = asRecord(randomValidationState.strategy_drift_summary)
  const latestValidationAt = String(validationAttempt.updated_at || validationAttempt.created_at || '').trim()
  const latestRandomAt = String(latestRandomSummary.updated_at || latestRandomSummary.created_at || randomValidationState.updated_at || '').trim()
  const randomEvidence = String(latestRandomSummary.evidence_level || '').trim()
  const randomEvidenceReviewStrength = randomEvidence ? signalOpsReviewGovernanceStrength(randomEvidence) : 'LOW'
  const experimentValidationRan = Boolean(latestValidationAt || validationAttempt.experiment_package_hash)
  const randomValidationRan = Boolean(latestRandomAt || latestRandomSummary.job_id || randomEvidence)
  const decisions = firstNonEmptyArray(autoStatus?.review_decisions, autoConfig.review_decisions)
  const latestDecision = decisions[decisions.length - 1]
  const latestDecisionSummary = asRecord(latestDecision?.review_decision_summary)
  const latestDecisionDiffSummary = asRecord(latestDecision?.parameter_diff_summary)
  const latestDecisionDiffChecksum = String(latestDecision?.parameter_diff_checksum || latestDecisionSummary.parameter_diff_checksum || '').trim()
  const latestDecisionDiffStatus = latestDecisionDiffSummary.status || latestDecisionSummary.parameter_diff_status
  const reviewDecisionLedger = asRecord(autoStatus?.review_decision_event_ledger)
  const reviewDecisionLedgerHash = String(reviewDecisionLedger.latest_event_hash || '').trim()
  const reviewDecisionLedgerCount = Number(reviewDecisionLedger.event_count || 0)
  const reviewDecisionHandoffShipperStatus = asRecord(reviewDecisionLedger.handoff_shipper_status)
  const reviewDecisionHandoffShipperIssues = Array.isArray(reviewDecisionHandoffShipperStatus.issues)
    ? reviewDecisionHandoffShipperStatus.issues
    : []
  const autoApprovalDecisions = decisions.filter((item) => (
    item?.reviewer === 'auto_low_risk_reviewer'
    && item?.action === 'APPROVE_SIMULATION_CANDIDATE'
    && item?.result_status === 'APPLIED_TO_SIMULATION'
  ))
  const latestAutoApproval = autoApprovalDecisions[autoApprovalDecisions.length - 1]
  const queueCounts = asRecord(queueState.counts)
  const pendingCount = reviewQueue.filter((item) => item.pending).length
  const verificationWarnings = Array.isArray(reviewExportVerification?.warnings) ? reviewExportVerification.warnings : []

  return (
    <details data-testid="signalops-automation-log" className="h-full rounded-lg border border-slate-200 bg-slate-50 p-3 text-left">
      <summary className="cursor-pointer text-sm font-medium text-slate-700">自动化日志</summary>
      <div className="mt-3 grid gap-3 md:grid-cols-4">
        <Metric label="最近自动轮询" value={fmtDate(autoStatus?.last_tick_at || autoConfig.last_tick_at)} />
        <Metric label="最近成功" value={fmtDate(autoStatus?.last_success_at || autoConfig.last_success_at)} tone={autoStatus?.last_success_at || autoConfig.last_success_at ? 'good' : 'default'} />
        <Metric label="最近错误" value={displayMessage(autoStatus?.last_error || autoConfig.last_error) || '无'} tone={autoStatus?.last_error || autoConfig.last_error ? 'bad' : 'default'} />
        <Metric label="审查队列" value={`待审查 ${pendingCount} / 总数 ${reviewQueue.length}`} tone={pendingCount > 0 ? 'warn' : 'good'} />
        <Metric label="队列计数" value={queueCountSummary(queueCounts, reviewQueue)} />
        <Metric label="验证状态" value={displayCode(experimentValidationRan ? (validationAttempt.status || '已记录') : '未运行')} />
        <Metric label="同步" value={displayCode(experimentValidationRan ? (validationAttempt.review_queue_sync_status || '未同步') : '未运行')} tone={validationAttempt.review_queue_sync_status === 'FAILED' ? 'bad' : validationAttempt.review_queue_sync_status === 'SYNCED' ? 'good' : 'default'} />
        <Metric label="随机验证" value={randomValidationRan ? `${displayCode(randomEvidenceReviewStrength)} / ${fmtDateOrLabel(latestRandomAt, '已记录')}` : '未运行'} tone={randomEvidenceReviewStrength === 'LOW' ? 'warn' : 'default'} />
        <Metric label="随机微调" value={randomValidationRan ? (randomAdjustment.applied ? `已应用 ${fmtNumber(driftSummary.applied_count || 0, 0)} 次` : '未应用') : '未运行'} tone={randomAdjustment.applied ? 'good' : 'default'} />
        <Metric label="最近审查决策" value={latestDecision ? `${displayCode(latestDecision.action)} / ${fmtDate(latestDecision.created_at)}` : '暂无'} />
        <Metric label="差异校验和" value={latestDecisionDiffChecksum ? `${compactId(latestDecisionDiffChecksum)} / ${displayCode(latestDecisionDiffStatus)}` : '暂无'} />
        <Metric label="差异台账" value={reviewDecisionLedgerHash ? `事件 ${fmtNumber(reviewDecisionLedgerCount, 0)} / ${compactId(reviewDecisionLedgerHash)}` : '暂无'} />
        <Metric label="低风险自动审批" value={latestAutoApproval ? `${autoApprovalDecisions.length} 次 / ${fmtDate(latestAutoApproval.created_at)}` : '开启 / 暂无'} tone="good" />
      </div>
      <div data-testid="signalops-review-event-export-verification" className="mt-3 rounded-md border border-slate-200 bg-white p-3 text-xs text-slate-600">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <div className="font-medium text-slate-800">复核事件导出</div>
            <div>外部交接前验证签名包。</div>
          </div>
          <div className="flex flex-wrap gap-2 text-[11px] text-slate-500">
            <span data-testid="signalops-review-event-export-role">
              角色：{role}；复核导出：{canVerifyReviewEventExport ? 'operator+' : '已阻断'}
            </span>
            <span data-testid="signalops-review-event-export-disabled-reason">
              {verifyDisabledReason || '复核事件导出验证和交接需要 operator+ 权限。'}
            </span>
          </div>
          <button
            type="button"
            data-testid="signalops-verify-review-event-export"
            className="inline-flex items-center gap-1 rounded-md border border-slate-300 bg-white px-2 py-1 font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={verificationBusy || !canVerifyReviewEventExport}
            title={verifyDisabledReason}
            onClick={onVerifyReviewEventExport}
          >
            <CheckCircle2 size={14} />
            {verificationBusy ? 'Verifying...' : 'Verify signed export'}
          </button>
          <button
            type="button"
            data-testid="signalops-handoff-review-event-export"
            className="inline-flex items-center gap-1 rounded-md border border-slate-300 bg-white px-2 py-1 font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={handoffBusy || !canVerifyReviewEventExport}
            title={verifyDisabledReason}
            onClick={onHandoffReviewEventExport}
          >
            <Save size={14} />
            {handoffBusy ? 'Handing off...' : 'Handoff signed export'}
          </button>
        </div>
        {reviewExportVerification ? (
          <div data-testid="signalops-review-event-export-verification-status" className="mt-2 grid gap-2 md:grid-cols-4">
            <Metric label="Export verify / 导出验签" value={displayCode(reviewExportVerification.status)} tone={reviewExportVerification.valid ? 'good' : 'warn'} />
            <Metric label="校验和" value={yesNo(Boolean(reviewExportVerification.checksum_valid))} tone={reviewExportVerification.checksum_valid ? 'good' : 'bad'} />
            <Metric label="签名" value={yesNo(Boolean(reviewExportVerification.signature_valid))} tone={reviewExportVerification.signature_valid ? 'good' : 'bad'} />
            <Metric label="事件" value={fmtNumber(reviewExportVerification.event_count || 0, 0)} />
            {verificationWarnings.length ? (
              <div className="md:col-span-4 text-amber-700">{verificationWarnings.join(', ')}</div>
            ) : null}
          </div>
        ) : (
          <div data-testid="signalops-review-event-export-verification-status" className="mt-2 text-slate-500">
            Not verified in this session.
          </div>
        )}
        {reviewExportHandoff ? (
          <div data-testid="signalops-review-event-export-handoff-status" className="mt-2 grid gap-2 md:grid-cols-4">
            <Metric label="交接" value={displayCode(reviewExportHandoff.status)} tone={reviewExportHandoff.status === 'HANDED_OFF' ? 'good' : reviewExportHandoff.status === 'DISABLED' ? 'warn' : 'bad'} />
            <Metric label="包" value={reviewExportHandoff.bundle_checksum ? compactId(reviewExportHandoff.bundle_checksum) : '-'} />
            <Metric label="清单" value={reviewExportHandoff.manifest_file ? compactId(reviewExportHandoff.manifest_file) : '-'} />
            <Metric label="目标" value={displayCode(reviewExportHandoff.handoff_destination || '-')} />
            {reviewExportHandoff.reason ? (
              <div className="md:col-span-4 text-amber-700">{reviewExportHandoff.reason}</div>
            ) : null}
          </div>
        ) : (
          <div data-testid="signalops-review-event-export-handoff-status" className="mt-2 text-slate-500">
            No handoff in this session.
          </div>
        )}
        <div data-testid="signalops-review-event-export-shipper-status" className="mt-2 grid gap-2 md:grid-cols-4">
          <Metric label="交接器" value={displayCode(String(reviewDecisionHandoffShipperStatus.status || '-'))} tone={reviewDecisionHandoffShipperStatus.status === 'DELIVERED' ? 'good' : reviewDecisionHandoffShipperStatus.status === 'FAILED' || reviewDecisionHandoffShipperStatus.status === 'INVALID' ? 'bad' : 'warn'} />
          <Metric label="提供方" value={displayCode(String(reviewDecisionHandoffShipperStatus.provider || '-'))} />
          <Metric label="最新匹配" value={yesNo(Boolean(reviewDecisionHandoffShipperStatus.matches_latest_handoff))} tone={reviewDecisionHandoffShipperStatus.matches_latest_handoff ? 'good' : 'warn'} />
          <Metric label="搜索就绪" value={yesNo(Boolean(reviewDecisionHandoffShipperStatus.search_index_ready))} tone={reviewDecisionHandoffShipperStatus.search_index_ready ? 'good' : 'warn'} />
          <div className="md:col-span-4 text-slate-500">
            remote: {displayCode(String(reviewDecisionHandoffShipperStatus.remote_destination || '-'))}; object: {displayCode(String(reviewDecisionHandoffShipperStatus.object_key || '-'))}; retention: {displayCode(String(reviewDecisionHandoffShipperStatus.retention_policy_id || reviewDecisionHandoffShipperStatus.retention_status || '-'))}; export match {yesNo(Boolean(reviewDecisionHandoffShipperStatus.matches_latest_export))}.
          </div>
          {reviewDecisionHandoffShipperIssues.length ? (
            <div className="md:col-span-4 text-amber-700">{reviewDecisionHandoffShipperIssues.slice(0, 4).join(', ')}</div>
          ) : null}
        </div>
      </div>
      {autoStatus?.storage_warning || autoConfig.storage_warning ? (
        <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
          {displayMessage(autoStatus?.storage_warning || autoConfig.storage_warning)}
        </div>
      ) : null}
      <div className="mt-3">
        <ResultSnapshot
          tickResult={tickResult}
          lastTickResult={firstNonEmptyRecord(autoStatus?.last_tick_result, autoConfig.last_tick_result)}
          dailyReview={dailyReview}
          lastResearchReview={firstNonEmptyRecord(autoStatus?.last_research_review, autoConfig.last_research_review)}
          commandResult={commandResult}
        />
      </div>
    </details>
  )
}

function ReviewWindow({
  state,
  items,
  filters,
  filterOptions,
  selectedItemKey,
  loading,
  busy,
  canReview,
  disabledReason,
  onClose,
  onFiltersChange,
  onSelect,
  onDecision,
}: {
  state: SignalOpsReviewWindowState
  items: SignalOpsReviewQueueItem[]
  filters: ReviewQueueFilters
  filterOptions: {
    risks: string[]
    statuses: string[]
    qualities: string[]
    symbols: string[]
    sources: string[]
  }
  selectedItemKey: string
  loading: boolean
  busy: boolean
  canReview: boolean
  disabledReason?: string
  onClose: () => void
  onFiltersChange: (filters: ReviewQueueFilters) => void
  onSelect: (item: SignalOpsReviewQueueItem) => void
  onDecision: (item: SignalOpsReviewQueueItem, decision: SignalOpsReviewDecision) => void
}) {
  return (
    <div data-testid="signalops-review-window" className="fixed inset-0 z-40 flex justify-end bg-slate-950/30 p-2 backdrop-blur-sm sm:p-4">
      <section className="flex h-full w-full max-w-7xl flex-col overflow-hidden rounded-lg border border-slate-200 bg-white shadow-xl">
        <div className="sticky top-0 z-10 flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-white/95 px-4 py-3 backdrop-blur">
          <div>
            <div className="text-lg font-semibold text-slate-950">审查窗口</div>
            <div className="mt-1 text-xs text-slate-500">待审查 {state.pendingCount} / 筛选 {state.filteredCount} / 总数 {state.totalCount}</div>
          </div>
          <button
            type="button"
            className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-slate-200 text-slate-700 transition hover:bg-slate-50"
            onClick={onClose}
            title="关闭审查窗口"
          >
            <XCircle size={18} />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto bg-slate-50/50 p-4">
          <div className="grid gap-4 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
            <ReviewQueuePanel
              items={items}
              totalCount={state.totalCount}
              filters={filters}
              filterOptions={filterOptions}
              onFiltersChange={onFiltersChange}
              selectedItemKey={selectedItemKey}
              loading={loading}
              onSelect={onSelect}
            />
            <ReviewCardPanel
              item={state.activeItem}
              busy={busy}
              canReview={canReview}
              disabledReason={disabledReason}
              onDecision={onDecision}
            />
          </div>
        </div>
      </section>
    </div>
  )
}

function BoundaryInterventionWindow({
  role,
  onClose,
  children,
}: {
  role: OperatorRole
  onClose: () => void
  children: React.ReactNode
}) {
  return (
    <div data-testid="signalops-boundary-window" className="fixed inset-0 z-30 flex justify-end bg-slate-950/30 p-2 backdrop-blur-sm sm:p-4">
      <section className="flex h-full w-full max-w-7xl flex-col overflow-hidden rounded-lg border border-slate-200 bg-white shadow-xl">
        <div className="sticky top-0 z-10 flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-white/95 px-4 py-3 backdrop-blur">
          <div>
            <div className="text-lg font-semibold text-slate-950">边界设置 / 异常接管</div>
            <div className="mt-1 text-xs text-slate-500">人工入口已收敛到这里；当前角色 {role}。</div>
          </div>
          <button
            type="button"
            data-testid="signalops-close-boundary"
            className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-slate-200 text-slate-700 transition hover:bg-slate-50"
            onClick={onClose}
            title="关闭边界设置"
          >
            <XCircle size={18} />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto bg-slate-50/50 p-4">
          <div className="space-y-4">{children}</div>
        </div>
      </section>
    </div>
  )
}

function ManagedPoolSnapshotPanel({
  symbols,
  config,
  stockNameSources,
  portfolios,
  positions,
  loading,
}: {
  symbols: string[]
  config: AutoPaperTradingConfig
  stockNameSources: StockNameSources
  portfolios: PaperPortfolioItem[]
  positions: PaperPositionItem[]
  loading: boolean
}) {
  const totalCash = portfolios.reduce((sum, item) => sum + Number(item.available_cash || 0), 0)
  const totalMarketValue = portfolios.reduce((sum, item) => sum + Number(item.market_value || 0), 0)
  const totalFloatingPnl = positions.reduce((sum, item) => sum + Number(item.floating_pnl || 0), 0)
  const capitalBase = poolCapitalBase(config, portfolios)
  const totalAssets = capitalBase + totalFloatingPnl
  const totalPositionCost = positions.reduce((sum, item) => {
    const quantity = Number(item.quantity || 0)
    const cost = Number(item.virtual_cost || 0)
    return sum + Math.abs(quantity * cost)
  }, 0)
  const pnlRate = capitalBase > 0 ? (totalFloatingPnl / capitalBase) * 100 : null
  const holdingPnlRate = totalPositionCost > 0 ? (totalFloatingPnl / totalPositionCost) * 100 : null
  const isInitialLoading = loading && symbols.length === 0 && portfolios.length === 0 && positions.length === 0
  const symbolNames = stockNamesForSymbols(config, symbols, stockNameSources)
  const symbolNameBySymbol = new Map(symbols.map((symbol, index) => [symbolToken(symbol), symbolNames[index] || symbol]))
  const positionsBySymbol = positions.reduce((map, position) => {
    const current = map.get(position.symbol) || { quantity: 0, currentValue: 0, floatingPnl: 0 }
    current.quantity += Number(position.quantity || 0)
    current.currentValue += Number(position.current_value || 0)
    current.floatingPnl += Number(position.floating_pnl || 0)
    map.set(position.symbol, current)
    return map
  }, new Map<string, { quantity: number; currentValue: number; floatingPnl: number }>())
  const visiblePositions = Array.from(positionsBySymbol.entries())
    .sort((left, right) => Math.abs(right[1].floatingPnl) - Math.abs(left[1].floatingPnl))
    .slice(0, 4)
  const pnlSummary = pnlRate === null
    ? fmtSignedMoney(totalFloatingPnl)
    : `${fmtSignedMoney(totalFloatingPnl)} / ${fmtNumber(pnlRate, 2)}%`
  const holdingSummary = holdingPnlRate === null
    ? '-'
    : `${fmtSignedMoney(totalFloatingPnl)} / ${fmtNumber(holdingPnlRate, 2)}%`

  return (
    <div className="h-full w-full rounded-lg border border-slate-200 bg-white p-4 text-left">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-sm font-semibold text-slate-950">系统持仓盈亏</div>
          <div className="mt-1 text-xs text-slate-500">只读摘要，订单和人工接管仍在边界设置中。</div>
        </div>
        <Badge status={pnlTone(totalFloatingPnl) === 'bad' ? 'WARN' : 'PASS'}>股票池 {symbols.length}</Badge>
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-2 lg:grid-cols-5">
        <Metric label="实时盈亏" value={isInitialLoading ? '加载中...' : pnlSummary} tone={pnlTone(totalFloatingPnl)} />
        <Metric label="持仓总盈亏" value={isInitialLoading ? '-' : holdingSummary} tone={pnlTone(totalFloatingPnl)} />
        <Metric label="持仓市值" value={isInitialLoading ? '-' : fmtMoney(totalMarketValue)} />
        <Metric label="可用现金" value={isInitialLoading ? '-' : fmtMoney(totalCash)} tone="good" />
        <Metric label="总资产" value={isInitialLoading ? '-' : fmtMoney(totalAssets)} />
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(260px,0.8fr)]">
        <div className="min-w-0">
          <div className="text-xs font-semibold text-slate-500">股票池</div>
          <div className="mt-2 flex flex-wrap gap-2">
            {symbols.length ? symbols.map((symbol, index) => {
              const position = positionsBySymbol.get(symbol)
              return (
                <span key={symbol} className="inline-flex max-w-full items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-xs font-medium text-slate-700">
                  <span>{symbol}</span>
                  {symbolNames[index] && symbolNames[index] !== symbol ? <span className="truncate text-slate-500">{symbolNames[index]}</span> : null}
                  {position ? <span className={pnlTone(position.floatingPnl) === 'bad' ? 'text-rose-700' : pnlTone(position.floatingPnl) === 'good' ? 'text-emerald-700' : 'text-slate-500'}>{fmtSignedMoney(position.floatingPnl)}</span> : null}
                </span>
              )
            }) : (
              <span className="text-xs text-slate-500">{isInitialLoading ? '正在加载股票池...' : '股票池暂无代码。'}</span>
            )}
          </div>
        </div>
        <div className="min-w-0">
          <div className="text-xs font-semibold text-slate-500">当前持仓</div>
          <div className="mt-2 space-y-2">
            {visiblePositions.length ? visiblePositions.map(([symbol, position]) => {
              const stockName = symbolNameBySymbol.get(symbolToken(symbol)) || symbol
              return (
                <div key={symbol} className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
                  <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
                    <div className="min-w-0">
                      <div className="font-semibold text-slate-900">{symbol}</div>
                      {stockName !== symbol ? (
                        <div className="mt-0.5 max-w-full truncate font-medium text-slate-500" title={stockName}>{stockName}</div>
                      ) : null}
                    </div>
                    <div className={pnlTone(position.floatingPnl) === 'bad' ? 'shrink-0 font-semibold text-rose-700' : pnlTone(position.floatingPnl) === 'good' ? 'shrink-0 font-semibold text-emerald-700' : 'shrink-0 font-semibold text-slate-700'}>
                      <span className="mr-1 font-normal text-slate-500">盈亏</span>
                      {fmtSignedMoney(position.floatingPnl)}
                    </div>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-slate-500">
                    <span>数量 {fmtNumber(position.quantity, 0)} 股</span>
                    <span>市值 {fmtMoney(position.currentValue)}</span>
                  </div>
                </div>
              )
            }) : (
              <div className="rounded-md border border-dashed border-slate-200 p-3 text-xs text-slate-500">
                {isInitialLoading ? '正在加载持仓...' : '当前无模拟持仓。'}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function QueueFilterSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: string
  options: string[]
  onChange: (value: string) => void
}) {
  return (
    <label className="grid min-w-0 gap-1 text-xs text-slate-600">
      <span>{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full min-w-0 truncate rounded-md border border-slate-200 bg-white px-2 py-1 text-xs text-slate-800"
      >
        <option value="ALL">全部</option>
        {options.map((option) => (
          <option key={option} value={option}>{displayCode(option)}</option>
        ))}
      </select>
    </label>
  )
}

function ReviewQueuePanel({
  items,
  totalCount,
  filters,
  filterOptions,
  onFiltersChange,
  selectedItemKey,
  loading,
  onSelect,
}: {
  items: SignalOpsReviewQueueItem[]
  totalCount: number
  filters: ReviewQueueFilters
  filterOptions: {
    risks: string[]
    statuses: string[]
    qualities: string[]
    symbols: string[]
    sources: string[]
  }
  onFiltersChange: (filters: ReviewQueueFilters) => void
  selectedItemKey: string
  loading: boolean
  onSelect: (item: SignalOpsReviewQueueItem) => void
}) {
  const pendingCount = items.filter((item) => item.pending).length
  const updateFilter = (key: keyof ReviewQueueFilters, value: string) => {
    onFiltersChange({ ...filters, [key]: value })
  }
  return (
    <Card title="审查队列" action={<Badge status="WAIT">待审查 {pendingCount}</Badge>}>
      <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs font-medium text-slate-700">
        系统自动运行。
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        <QueueFilterSelect label="风险" value={filters.risk} options={filterOptions.risks} onChange={(value) => updateFilter('risk', value)} />
        <QueueFilterSelect label="状态" value={filters.status} options={filterOptions.statuses} onChange={(value) => updateFilter('status', value)} />
        <QueueFilterSelect label="质量" value={filters.quality} options={filterOptions.qualities} onChange={(value) => updateFilter('quality', value)} />
        <QueueFilterSelect label="股票" value={filters.symbol} options={filterOptions.symbols} onChange={(value) => updateFilter('symbol', value)} />
        <QueueFilterSelect label="来源" value={filters.source} options={filterOptions.sources} onChange={(value) => updateFilter('source', value)} />
      </div>
      <div className="mt-2 text-xs text-slate-500">筛选结果 {items.length} / {totalCount}</div>
      <div className="mt-3 space-y-2">
        {loading && items.length === 0 ? (
          <div className="rounded-md border border-dashed border-slate-200 p-4 text-sm text-slate-500">正在加载审查队列...</div>
        ) : null}
        {!loading && items.length === 0 ? (
          <div className="rounded-md border border-dashed border-slate-200 p-4 text-sm text-slate-500">暂无待审查 SignalOps 记录。</div>
        ) : null}
        {items.map((item) => {
          const key = reviewItemKey(item)
          const selected = key === selectedItemKey
          return (
            <button
              key={key}
              type="button"
              data-testid={`signalops-review-queue-item-${item.queue_item_id || item.id || item.symbol}`}
              className={`w-full rounded-md border p-3 text-left transition ${selected ? 'border-cyan-400 bg-cyan-50' : 'border-slate-200 bg-white hover:bg-slate-50'}`}
              onClick={() => onSelect(item)}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0 font-medium text-slate-950">{item.title}</div>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge status={item.pending ? 'WAIT' : 'PASS'}>{item.pending ? '待审查' : '已审查'}</Badge>
                  {item.candidate_status ? <Badge status={item.candidate_status}>{displayCode(item.candidate_status)}</Badge> : null}
                  {item.evidence_quality ? <Badge status={item.evidence_quality}>{displayCode(item.evidence_quality)}</Badge> : null}
                  <Badge status={item.review_decision}>{item.review_label}</Badge>
                </div>
              </div>
              <div className="mt-2 text-xs text-slate-600">{item.reason}</div>
              <div className="mt-2 grid gap-2 sm:grid-cols-4">
                {item.indicators.map((indicator) => (
                  <div key={indicator.label} className="rounded border border-slate-200 bg-white px-2 py-1">
                    <div className="text-[11px] text-slate-500">{indicator.label}</div>
                    <div className={`text-xs font-semibold ${indicator.tone === 'good' ? 'text-emerald-700' : indicator.tone === 'warn' ? 'text-amber-700' : indicator.tone === 'bad' ? 'text-rose-700' : 'text-slate-800'}`}>{indicator.value}</div>
                  </div>
                ))}
              </div>
              <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-500">
                <span>动作 {actionReviewText(item.latest_action)}</span>
                <span>更新 {fmtDate(item.updated_at)}</span>
              </div>
            </button>
          )
        })}
      </div>
    </Card>
  )
}

function ReviewCardPanel({
  item,
  busy,
  canReview,
  disabledReason,
  onDecision,
}: {
  item: SignalOpsReviewQueueItem | null
  busy: boolean
  canReview: boolean
  disabledReason?: string
  onDecision: (item: SignalOpsReviewQueueItem, decision: SignalOpsReviewDecision) => void
}) {
  const actions: Array<{ decision: SignalOpsReviewDecision; icon: React.ReactNode; variant?: 'primary' | 'danger' | 'secondary' }> = [
    { decision: 'PASS_REVIEW', icon: <CheckCircle2 size={16} />, variant: 'primary' },
    { decision: 'REJECT_SUGGESTION', icon: <XCircle size={16} />, variant: 'danger' },
    { decision: 'KEEP_WATCH', icon: <Eye size={16} /> },
    { decision: 'REQUEST_PATCH', icon: <Wrench size={16} /> },
  ]

  if (!item) {
    return (
      <Card title="审查卡" action={<Badge status="WAIT">待审查</Badge>}>
        <div className="grid gap-3 md:grid-cols-4">
          <Metric label="模拟动作" value="SIM_HOLD / 模拟观望" />
          <Metric label="仅模拟" value="是" tone="good" />
          <Metric label="真实交易" value="否" />
          <Metric label="系统自动运行" value="自动审批" />
        </div>
        <div className="mt-3 rounded-md border border-dashed border-slate-200 p-4 text-sm text-slate-500">
          暂无可展示的审查卡。
        </div>
      </Card>
    )
  }

  const candidateStatus = String(item.candidate_status || '').toUpperCase()
  const benchmark = asRecord(item.benchmark_comparison || item.walk_forward_validation?.benchmark_comparison)
  const runIds = asRecord(item.walk_forward_run_ids || asRecord(item.evidence_package).walk_forward_run_ids)
  const researchPackage = asRecord(item.research_evidence_package || asRecord(item.evidence_package).research_evidence_package)
  const experimentHash = String(item.experiment_package_hash || asRecord(item.evidence_package).experiment_package_hash || '')
  const validationAttempt = asRecord(item.experiment_validation_attempt)
  const syncStatus = String(validationAttempt.review_queue_sync_status || researchPackage.review_queue_sync_status || 'NOT_SYNCED').toUpperCase()
  const syncWarnings = asStringList(validationAttempt.warnings || researchPackage.warnings)
  const klineQuality = klineQualityFromItem(item)
  const klineRisk = asRecord(klineQuality.risk_invalidation)
  const klineLadder = asRecord(klineQuality.ladder_buy_policy || item.kline_evidence_package?.ladder_buy_policy)
  const klineTrend = asRecord(klineQuality.trend_regime)
  const klineBottom = asRecord(klineQuality.bottom_stage_score)
  const klineVolume = asRecord(klineQuality.volume_price_confirmation)
  const klineVolatility = asRecord(klineQuality.volatility_compression)
  const klineScore = numericValue(klineQuality.final_score ?? klineQuality.score ?? item.kline_evidence_package?.score)
  const bottomScore = numericValue(klineBottom.score)
  const klinePolicy = String(klineQuality.action_policy || klineQuality.actionPolicy || item.kline_evidence_package?.action_policy || '')
  const stabilityPackage = item.stability_evidence_package
  const stabilityQuality = stabilityQualityFromItem(item)
  const stabilityRegime = asRecord(stabilityQuality.regime_state)
  const stabilityVolatility = asRecord(stabilityQuality.volatility_state)
  const stabilityMetaGate = asRecord(stabilityQuality.meta_label_gate)
  const stabilitySizing = asRecord(stabilityQuality.volatility_sizing_policy || stabilityPackage?.volatility_sizing_policy)
  const stabilityScore = numericValue(stabilityQuality.stability_score ?? stabilityQuality.score ?? stabilityPackage?.score)
  const stabilityPolicy = String(stabilityQuality.action_policy || stabilityQuality.actionPolicy || stabilityPackage?.action_policy || '')
  const approveBlockers = [
    (!item.simulation_only || item.is_real_trade) ? 'SignalOps review simulation-only boundary violated' : '',
    candidateStatus !== 'READY_FOR_REVIEW' ? '候选未达到 READY_FOR_REVIEW' : '',
    item.review_allowed !== true ? '证据门禁未通过' : '',
    isWeakEvidenceQuality(item.evidence_quality) ? '证据质量偏弱' : '',
    benchmark.available !== true ? '基准不可用' : '',
    syncStatus === 'FAILED' ? '审查队列同步失败' : '',
  ].filter(Boolean)
  const approveBlocked = approveBlockers.length > 0
  const approveBlockedReason = approveBlockers.join(' / ')
  const candidateBaselineRows = candidateBaselineParameterRows(item)
  const candidateReason = String(asRecord(item.strategy_experiment).candidate_reason || '').trim()
  const parameterDiffSummary = asRecord(item.parameter_diff_summary || asRecord(item.strategy_experiment).parameter_diff_summary)
  const parameterDiffCounts = [
    `changed: ${Number(parameterDiffSummary.changed_count || 0)}`,
    `added: ${Number(parameterDiffSummary.added_count || 0)}`,
    `removed: ${Number(parameterDiffSummary.removed_count || 0)}`,
    `unchanged: ${Number(parameterDiffSummary.unchanged_count || 0)}`,
  ].join(' / ')
  const parameterDiffStatus = String(parameterDiffSummary.status || (candidateBaselineRows.some((row) => row.changed) ? 'CHANGED' : candidateBaselineRows.length ? 'UNCHANGED' : 'EMPTY'))
  const parameterDiffPolicy = String(parameterDiffSummary.policy_id || 'local_fallback')
  const governanceId = item.queue_item_id || item.experiment_id || item.signal_id || item.id
  const governanceEvidenceStrength = signalOpsReviewGovernanceStrength(item.evidence_quality)
  const governanceBlocker = item.blockers.length
    ? item.blockers.map(displayMessage).join(' / ')
    : approveBlocked
      ? approveBlockedReason
      : '无阻断；仍需人工复核'
  const governanceNextAction = approveBlocked
    ? '禁止通过审查；继续观察、驳回或要求补丁'
    : item.review_decision === 'PASS_REVIEW'
      ? '人工复核后仅写入模拟候选'
      : item.review_label || REVIEW_DECISION_LABELS[item.review_decision]
  const governanceEvidenceUsage = 'simulation_only'
  const governanceStrongConclusionAllowed = false
  const governanceBoundary = `simulation_only=${String(item.simulation_only)} / is_real_trade=${String(item.is_real_trade)} / evidence_usage=${governanceEvidenceUsage} / strong_conclusion_allowed=${String(governanceStrongConclusionAllowed)} / SIM_*`

  return (
    <Card title="审查卡" action={<Badge status={item.review_decision}>{item.review_label}</Badge>}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-base font-semibold text-slate-950">{item.title}</div>
          <div className="mt-1 text-xs text-slate-500">信号 {compactId(item.signal_id)} / {displayCode(item.status)}</div>
        </div>
        <Badge status={item.pending ? 'WAIT' : 'PASS'}>{item.pending ? '待审查' : '已审查'}</Badge>
      </div>
      <div
        data-testid={`signalops-review-governance-${safeDomId(governanceId)}`}
        className="mt-3 grid gap-2 rounded-md border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700 md:grid-cols-5"
      >
        <span className="min-w-0 break-words">
          <span className="text-slate-500">ID：</span>
          <span data-testid={`signalops-review-governance-id-${safeDomId(governanceId)}`}>{compactId(governanceId)}</span>
        </span>
        <span className="min-w-0 break-words">
          <span className="text-slate-500">证据强度：</span>
          <span data-testid={`signalops-review-evidence-strength-${safeDomId(governanceId)}`}>{displayCode(governanceEvidenceStrength)}</span>
        </span>
        <span className="min-w-0 break-words md:col-span-2">
          <span className="text-slate-500">阻断：</span>
          <span data-testid={`signalops-review-blocker-${safeDomId(governanceId)}`}>{governanceBlocker}</span>
        </span>
        <span className="min-w-0 break-words">
          <span className="text-slate-500">下一步：</span>
          <span data-testid={`signalops-review-next-action-${safeDomId(governanceId)}`}>{governanceNextAction}</span>
        </span>
        <span className="min-w-0 break-words font-medium text-slate-900 md:col-span-5" data-testid={`signalops-review-simulation-boundary-${safeDomId(governanceId)}`}>
          {governanceBoundary}
        </span>
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-4">
        <Metric label="模拟动作" value={actionReviewText(item.latest_action)} />
        <Metric label="仅模拟" value={yesNo(item.simulation_only)} tone={item.simulation_only ? 'good' : 'bad'} />
        <Metric label="真实交易" value={yesNo(item.is_real_trade)} tone={item.is_real_trade ? 'bad' : 'default'} />
        <Metric label="系统自动运行" value="自动审批" />
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-4">
        <Metric label="候选状态" value={displayCode(item.candidate_status)} tone={item.candidate_status === 'READY_FOR_REVIEW' ? 'good' : item.candidate_status === 'REJECTED' ? 'bad' : 'default'} />
        <Metric label="证据质量" value={displayCode(item.evidence_quality)} tone={isWeakEvidenceQuality(item.evidence_quality) ? 'warn' : 'good'} />
        <Metric label="风险等级" value={displayCode(item.risk_level)} tone={item.risk_level === 'HIGH' ? 'bad' : 'default'} />
        <Metric label="样本外验证" value={displayCode(item.walk_forward_validation?.status)} />
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-4">
        <Metric label="实验哈希" value={compactId(experimentHash)} />
        <Metric label="基准" value={`${String(benchmark.symbol || '000300.SH')} / ${displayCode(benchmark.status || (benchmark.available ? 'AVAILABLE' : 'UNAVAILABLE'))}`} tone={benchmark.available ? 'good' : 'warn'} />
        <Metric label="验证运行" value={compactId(String(runIds.candidate_validation || runIds.candidate || ''))} />
        <Metric label="研究包" value={compactId(String(researchPackage.package_id || asRecord(item.evidence_package).package_id || ''))} />
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-4">
        <Metric label="验证状态" value={displayCode(validationAttempt.status || item.walk_forward_validation?.status)} />
        <Metric label="同步" value={displayCode(syncStatus)} tone={syncStatus === 'SYNCED' ? 'good' : syncStatus === 'FAILED' ? 'bad' : 'warn'} />
        <Metric label="基准原因" value={displayCode(benchmark.unavailable_reason || benchmark.reason || (benchmark.available ? 'AVAILABLE' : 'UNAVAILABLE'))} tone={benchmark.available ? 'good' : 'warn'} />
        <Metric label="警告" value={syncWarnings.length ? syncWarnings.map(displayCode).join(' / ') : '-'} tone={syncWarnings.length ? 'warn' : 'default'} />
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-4">
        <Metric label="K线综合评分" value={klineScore === null ? '-' : fmtNumber(klineScore, 0)} tone={klineScore !== null && klineScore >= 66 ? 'good' : klineScore !== null && klineScore < 55 ? 'warn' : 'default'} />
        <Metric label="K线低位评分" value={bottomScore === null ? '-' : fmtNumber(bottomScore, 0)} tone={bottomScore !== null && bottomScore >= 60 ? 'good' : bottomScore !== null && bottomScore < 45 ? 'warn' : 'default'} />
        <Metric label="趋势状态" value={displayCode(klineTrend.status)} />
        <Metric label="当前建议" value={displayCode(klineLadder.stage || klinePolicy)} tone={String(klineRisk.status || '').toUpperCase() === 'INVALIDATE' ? 'bad' : klinePolicy === 'HOLD' ? 'warn' : 'good'} />
      </div>
      <div className="mt-3 rounded-md border border-emerald-100 bg-emerald-50 p-3 text-xs text-emerald-950">
        <div className="font-medium">K线证据</div>
        <div className="mt-1 grid gap-1 sm:grid-cols-2">
          <span>量价确认：{displayCode(klineVolume.status)}</span>
          <span>波动压缩：{displayCode(klineVolatility.status)}</span>
          <span>阶梯目标仓位：{fmtRate(Number(klineLadder.target_position_ratio || 0), 0)}</span>
          <span>单次加仓上限：{fmtRate(Number(klineLadder.max_step_position_ratio || 0), 0)}</span>
          <span>失效状态：{displayCode(klineRisk.status)}</span>
          <span>证据包：{compactId(item.kline_evidence_package?.package_id)}</span>
        </div>
        {asStringList(klineRisk.reasons).length ? (
          <div className="mt-2 text-amber-800">失效条件：{asStringList(klineRisk.reasons).map(displayCode).join(' / ')}</div>
        ) : null}
      </div>
      {Object.keys(asRecord(stabilityQuality)).length || Object.keys(asRecord(stabilityPackage)).length ? (
        <div className="mt-3 rounded-md border border-blue-100 bg-blue-50 p-3 text-xs text-blue-950">
          <div className="font-medium">稳定性门禁</div>
          <div className="mt-1 grid gap-1 sm:grid-cols-2">
            <span>综合评分：{stabilityScore === null ? '-' : fmtNumber(stabilityScore, 0)}</span>
            <span>当前策略：{displayCode(stabilityPolicy || '-')}</span>
            <span>市场状态：{displayCode(stabilityRegime.status)}</span>
            <span>波动状态：{displayCode(stabilityVolatility.status)}</span>
            <span>Meta 门禁：{displayCode(stabilityMetaGate.status)}</span>
            <span>胜率下界：{fmtRate(Number(stabilityMetaGate.wilson_win_rate_lower_bound || 0))}</span>
            <span>最大仓位：{fmtRate(Number(stabilitySizing.max_position_ratio || 0), 0)}</span>
            <span>单次上限：{fmtRate(Number(stabilitySizing.max_step_position_ratio || 0), 0)}</span>
          </div>
        </div>
      ) : null}
      {candidateBaselineRows.length ? (
        <div data-testid="signalops-review-candidate-baseline" className="mt-3 rounded-md border border-violet-100 bg-violet-50 p-3 text-xs text-violet-950">
          <div className="font-medium">Candidate / baseline parameters / 候选 / 基线参数</div>
          <div data-testid="signalops-review-parameter-diff-summary" className="mt-1 text-violet-800">
            Diff: {displayCode(parameterDiffStatus)} / {parameterDiffCounts} / policy: {parameterDiffPolicy}
            {parameterDiffSummary.truncated ? ' / truncated' : ''}
          </div>
          {candidateReason ? <div className="mt-1 text-violet-800">Reason: {displayMessage(candidateReason) || candidateReason}</div> : null}
          <div className="mt-2 grid gap-2 sm:grid-cols-2">
            {candidateBaselineRows.map((row) => (
              <div key={row.key} data-testid={`signalops-review-candidate-baseline-row-${safeDomId(row.key)}`} className="rounded border border-violet-100 bg-white px-2 py-1">
                <div className="font-medium text-violet-950">{row.label} <span className="font-normal text-violet-500">({displayCode(row.changeType)})</span></div>
                <div className="mt-1 grid gap-1 text-violet-800">
                  <span>Baseline: {row.baseline}</span>
                  <span>Candidate: {row.candidate}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}
      <div className="mt-3 rounded-md border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
        <div className="font-medium text-slate-800">证据包</div>
        <div className="mt-1 grid gap-1 sm:grid-cols-2">
          <span>实验：{compactId(item.experiment_id)}</span>
          <span>包：{compactId(String(item.evidence_package?.package_id || researchPackage.package_id || ''))}</span>
          <span>训练窗口：{String(asRecord(item.walk_forward_validation?.train_window).start || '-')} {'->'} {String(asRecord(item.walk_forward_validation?.train_window).end || '-')}</span>
          <span>验证窗口：{String(asRecord(item.walk_forward_validation?.validation_window).start || '-')} {'->'} {String(asRecord(item.walk_forward_validation?.validation_window).end || '-')}</span>
          <span>Baseline Run：{compactId(String(runIds.baseline_validation || ''))}</span>
          <span>候选运行：{compactId(String(runIds.candidate_validation || ''))}</span>
          <span>基准状态：{String(benchmark.reason || (benchmark.available ? 'available' : 'unavailable'))}</span>
          <span>过期时间：{fmtDate(item.expires_at)}</span>
        </div>
      </div>
      <div className="mt-3 rounded-md border border-cyan-100 bg-cyan-50 p-3 text-sm text-cyan-950">
        <div className="font-medium">审查建议：{item.review_label}</div>
        <div className="mt-1 text-xs text-cyan-800">{item.reason}</div>
      </div>
      <div className="mt-3 grid gap-2 text-xs text-slate-600 sm:grid-cols-2">
        <span>最近订单：{compactId(item.latest_order_id)}</span>
        <span>订单时间：{fmtDate(item.latest_order_updated_at)}</span>
        <span>数据来源：{item.source.join(' / ')}</span>
        <span>更新时间：{fmtDate(item.updated_at)}</span>
      </div>
      {item.blockers.length > 0 ? (
        <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
          阻断原因：{item.blockers.map(displayMessage).join(' / ')}
        </div>
      ) : null}
      {approveBlocked ? (
        <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
          通过审查已禁用：{approveBlockedReason}
        </div>
      ) : null}
      {item.decision_card ? (
        <div className="mt-3">
          <DecisionCardPanel card={item.decision_card} />
        </div>
      ) : (
        <div className="mt-3 rounded-md border border-dashed border-slate-200 p-3 text-xs text-slate-500">
          暂无最新决策卡片；审查卡仍按信号、胜率、复盘和订单记录给出人工审查建议。
        </div>
      )}
      <div className="mt-4 flex flex-wrap gap-2">
        {actions.map((action) => (
          <ActionButton
            key={action.decision}
            onClick={() => onDecision(item, action.decision)}
            disabled={busy || !canReview || (action.decision === 'PASS_REVIEW' && approveBlocked)}
            title={action.decision === 'PASS_REVIEW' && approveBlocked ? approveBlockedReason : disabledReason}
            icon={action.icon}
            variant={action.variant}
            testId={`signalops-review-decision-${action.decision}`}
          >
            {REVIEW_DECISION_LABELS[action.decision]}
          </ActionButton>
        ))}
      </div>
    </Card>
  )
}

function OperatorPolicyPanel({
  role,
  operatorId,
  canWrite,
  canOperate,
  canManageConfig,
  writeDisabledReason,
  operateDisabledReason,
  configDisabledReason,
}: {
  role: OperatorRole
  operatorId: string
  canWrite: boolean
  canOperate: boolean
  canManageConfig: boolean
  writeDisabledReason?: string
  operateDisabledReason?: string
  configDisabledReason?: string
}) {
  return (
    <div data-testid="signalops-operator-policy" className="mt-3 rounded-md border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold text-slate-800">操作员</span>
        <span className="rounded bg-slate-100 px-2 py-0.5">{operatorId}</span>
        <Badge status={canManageConfig ? 'PASS' : canOperate ? 'WARN' : canWrite ? 'REVIEW' : 'SKIPPED'}>角色 {role}</Badge>
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        <span data-testid="signalops-lifecycle-write-role" className={canWrite ? 'text-emerald-700' : 'text-slate-500'}>生命周期写入：{canWrite ? '允许' : '已阻断'}</span>
        <span data-testid="signalops-manual-control-role" className={canOperate ? 'text-emerald-700' : 'text-slate-500'}>人工控制：{canOperate ? 'operator+' : '已阻断'}</span>
        <span data-testid="signalops-runtime-config-role" className={canManageConfig ? 'text-emerald-700' : 'text-slate-500'}>运行时配置：{canManageConfig ? 'admin' : '需要 admin'}</span>
      </div>
      <div className="mt-2 grid gap-1 text-slate-500">
        <span data-testid="signalops-lifecycle-write-disabled-reason">
          {writeDisabledReason || 'SignalOps 生命周期写入需要 researcher+ 权限。'}
        </span>
        <span data-testid="signalops-manual-control-disabled-reason">
          {operateDisabledReason || 'SignalOps 人工控制需要 operator+ 权限。'}
        </span>
        <span data-testid="signalops-runtime-config-disabled-reason">
          {configDisabledReason || 'SignalOps 运行时配置写入需要 admin 权限。'}
        </span>
      </div>
    </div>
  )
}

function DecisionCardPanel({ card }: { card: SignalOpsDecisionCard }) {
  const attribution = asRecord(card.capital_attribution)
  const klineQuality = extractKlineQuality(card)
  const klineRisk = asRecord(klineQuality.risk_invalidation)
  const klineLadder = asRecord(klineQuality.ladder_buy_policy || card.ladder_buy_policy)
  const klineScore = numericValue(klineQuality.final_score ?? klineQuality.score)
  const stabilityQuality = extractStrategyStabilityQuality(card)
  const stabilityRegime = asRecord(stabilityQuality.regime_state)
  const stabilityMetaGate = asRecord(stabilityQuality.meta_label_gate || card.meta_label_gate)
  const stabilitySizing = asRecord(stabilityQuality.volatility_sizing_policy || card.volatility_sizing_policy)
  const stabilityScore = numericValue(stabilityQuality.stability_score ?? stabilityQuality.score)
  const quantCorePathRisk = asRecord(card.quant_core_path_risk)
  const futureTrendProbability = asRecord(card.future_trend_probability)
  const pathRiskAvoidsNewBuy = Boolean(card.quant_core_path_risk_avoids_new_buy)
  const pathRiskSampleQuality = compactSampleQuality(quantCorePathRisk.sampleQuality)
  const pathRiskLeakagePolicy = String(quantCorePathRisk.leakagePolicy || '').trim()
  const futureTrendUpProbability = numericValue(futureTrendProbability.calibratedUpProbability)
  const decisionLedgerRows = [
    ...(Object.keys(klineQuality).length ? [{
      label: 'K线质量',
      source: 'kline_evidence',
      status: displayCode(klineQuality.action_policy || klineQuality.actionPolicy),
      detail: `stage ${displayCode(klineLadder.stage || klineQuality.ladder_stage)} / risk ${displayCode(klineRisk.status)} / grade ${displayCode(klineQuality.grade)}`,
      strength: klineScore ?? 0,
    }] : []),
    ...(Object.keys(stabilityQuality).length ? [{
      label: '策略稳定性',
      source: 'stability_evidence',
      status: displayCode(stabilityQuality.action_policy || stabilityQuality.actionPolicy),
      detail: `regime ${displayCode(stabilityRegime.status)} / meta ${displayCode(stabilityMetaGate.status)} / max position ${fmtRate(Number(stabilitySizing.max_position_ratio || 0), 0)}`,
      strength: stabilityScore ?? 0,
    }] : []),
    ...(Object.keys(quantCorePathRisk).length ? [{
      label: '量化核心路径风险',
      source: 'quant_core_path',
      status: displayCode(quantCorePathRisk.riskPolicy || card.quant_core_path_risk_policy),
      detail: `boundary ${displayCode(quantCorePathRisk.actionBoundary)} / sample ${pathRiskSampleQuality.summary} / leakage ${pathRiskLeakagePolicy ? 'declared' : '-'}`,
      strength: numericValue(quantCorePathRisk.downsideRiskScore) ?? 0,
    }] : []),
    ...(Object.keys(futureTrendProbability).length ? [{
      label: '未来趋势校准',
      source: 'future_trend_probability',
      status: displayCode(futureTrendProbability.calibrationStatus),
      detail: `policy ${displayCode(futureTrendProbability.signalopsPolicyHint)} / samples ${fmtNumber(futureTrendProbability.sampleCount, 0)}`,
      strength: futureTrendUpProbability === null ? 0 : Math.round(futureTrendUpProbability * 100),
    }] : []),
  ]
  if (!card.action) {
    return (
      <div className="rounded-md border border-dashed border-slate-200 p-4 text-sm text-slate-500">
        暂无最新决策卡片。可以执行一次强制跟进，以生成资金归因。
      </div>
    )
  }
  return (
    <div className="rounded-md border border-cyan-100 bg-cyan-50 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm font-semibold text-cyan-950">决策卡片</div>
        <Badge status={String(card.action)}>{displayCode(card.action)}</Badge>
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <Metric label="变动前资金" value={fmtMoney(card.capital_before)} />
        <Metric label="变动后资金" value={fmtMoney(card.capital_after)} />
        <Metric label="可用现金" value={fmtMoney(card.cash_available)} />
        <Metric label="已用预算" value={fmtMoney(card.budget_used)} />
        <Metric label="佣金" value={fmtMoney(card.commission_fee)} />
        <Metric label="总交易费用" value={fmtMoney(card.total_fee ?? card.commission_fee)} />
      </div>
      <div className="mt-3 text-xs text-cyan-900">{displayMessage(String(card.reason || '-'))}</div>
      {decisionLedgerRows.length > 0 ? (
        <EvidenceLedger rows={decisionLedgerRows} className="mt-3 !rounded-lg !shadow-none" />
      ) : null}
      <div className="mt-2 grid gap-2 text-xs text-cyan-800 sm:grid-cols-2">
        <span>变动前持仓市值：{fmtMoney(attribution.position_value_before)}</span>
        <span>变动后持仓市值：{fmtMoney(attribution.position_value_after ?? card.position_value)}</span>
        <span>印花税归因：{fmtMoney(attribution.stamp_duty_fee ?? card.stamp_duty_fee ?? 0)}</span>
        <span>总费用归因：{fmtMoney(attribution.total_fee ?? card.total_fee ?? card.commission_fee)}</span>
        <span>仅模拟：{yesNo(card.simulation_only !== false)}</span>
        <span>真实交易：{yesNo(Boolean(card.is_real_trade))}</span>
      </div>
      {Object.keys(klineQuality).length ? (
        <div className="mt-3 rounded border border-cyan-200 bg-white/70 p-2 text-xs text-cyan-900">
          <div className="font-medium">K线评分：{klineScore === null ? '-' : fmtNumber(klineScore, 0)} / {displayCode(klineQuality.action_policy || klineQuality.actionPolicy)}</div>
          <div className="mt-1 grid gap-1 sm:grid-cols-2">
            <span>阶梯阶段：{displayCode(klineLadder.stage || klineQuality.ladder_stage)}</span>
            <span>目标仓位：{fmtRate(Number(klineLadder.target_position_ratio || 0), 0)}</span>
            <span>风险状态：{displayCode(klineRisk.status)}</span>
            <span>评分等级：{displayCode(klineQuality.grade)}</span>
          </div>
        </div>
      ) : null}
      {Object.keys(stabilityQuality).length ? (
        <div className="mt-3 rounded border border-cyan-200 bg-white/70 p-2 text-xs text-cyan-900">
          <div className="font-medium">稳定性评分：{stabilityScore === null ? '-' : fmtNumber(stabilityScore, 0)} / {displayCode(stabilityQuality.action_policy || stabilityQuality.actionPolicy)}</div>
          <div className="mt-1 grid gap-1 sm:grid-cols-2">
            <span>市场状态：{displayCode(stabilityRegime.status)}</span>
            <span>Meta：{displayCode(stabilityMetaGate.status)}</span>
            <span>胜率下界：{fmtRate(Number(stabilityMetaGate.wilson_win_rate_lower_bound || 0))}</span>
            <span>仓位上限：{fmtRate(Number(stabilitySizing.max_position_ratio || 0), 0)}</span>
          </div>
        </div>
      ) : null}
      {Object.keys(quantCorePathRisk).length ? (
        <div className="mt-3 rounded border border-cyan-200 bg-white/70 p-2 text-xs text-cyan-900">
          <div className="font-medium">量化核心路径风险：{displayCode(quantCorePathRisk.riskPolicy || card.quant_core_path_risk_policy)}</div>
          <div className="mt-1 grid gap-1 sm:grid-cols-2">
            <span>状态：{displayCode(quantCorePathRisk.status)}</span>
            <span>下行分：{fmtNumber(quantCorePathRisk.downsideRiskScore, 0)}</span>
            <span>MFE代理：{fmtRate(quantCorePathRisk.mfeProxy)}</span>
            <span>MAE代理：{fmtRate(quantCorePathRisk.maeProxy)}</span>
            <span>风险收益代理：{fmtNumber(quantCorePathRisk.riskRewardProxy, 2)}</span>
            <span>新买入边界：{yesNo(pathRiskAvoidsNewBuy)}</span>
            <span>动作边界：{displayCode(quantCorePathRisk.actionBoundary)}</span>
            <span>标签状态：{displayCode(quantCorePathRisk.labelStatus)}</span>
            <span className="min-w-0 truncate" title={pathRiskSampleQuality.detail}>样本质量：{pathRiskSampleQuality.summary}</span>
            <span className="min-w-0 truncate" title={pathRiskLeakagePolicy || '-'}>泄漏策略：{pathRiskLeakagePolicy ? '已声明' : '-'}</span>
          </div>
        </div>
      ) : null}
      {Object.keys(futureTrendProbability).length ? (
        <div className="mt-3 rounded border border-cyan-200 bg-white/70 p-2 text-xs text-cyan-900">
          <div className="font-medium">未来趋势校准：{displayCode(futureTrendProbability.signalopsPolicyHint)}</div>
          <div className="mt-1 grid gap-1 sm:grid-cols-2">
            <span>上行概率：{fmtRate(futureTrendProbability.calibratedUpProbability)}</span>
            <span>下行概率：{fmtRate(futureTrendProbability.calibratedDownProbability)}</span>
            <span>校准状态：{displayCode(futureTrendProbability.calibrationStatus)}</span>
            <span>样本数：{fmtNumber(futureTrendProbability.sampleCount, 0)}</span>
            <span>动作边界：{displayCode(futureTrendProbability.actionBoundary)}</span>
            <span>仅模拟：{yesNo(futureTrendProbability.simulation_only !== false)}</span>
          </div>
        </div>
      ) : null}
      {Array.isArray(card.blockers) && card.blockers.length > 0 ? (
        <div className="mt-2 rounded border border-cyan-200 bg-white/70 p-2 text-xs text-cyan-900">
          阻断原因：{card.blockers.map(displayMessage).join(' / ')}
        </div>
      ) : null}
    </div>
  )
}

function ResultSnapshot({
  tickResult,
  lastTickResult,
  dailyReview,
  lastResearchReview,
  commandResult,
}: {
  tickResult: AutoPaperTradingTickResult | null
  lastTickResult?: Record<string, unknown> | null
  dailyReview: AutoPaperTradingDailyReviewResult | null
  lastResearchReview?: unknown
  commandResult: AutoPaperTradingCommandResult | null
}) {
  const persistedTick = asRecord(lastTickResult)
  const review = dailyReview ? asRecord(dailyReview) : asRecord(lastResearchReview)
  const reviewedSymbols = Array.isArray(review.reviewed_symbols) ? review.reviewed_symbols.length : null
  const tickSummary = tickResult
    ? `${displayCode(tickResult.status)} / ${tickResult.symbol || '股票池'}`
    : Object.keys(persistedTick).length
      ? `${displayCode(persistedTick.status || '已记录')} / ${persistedTick.symbol || '股票池'}`
      : '暂无'
  const reviewSummary = dailyReview
    ? `${displayCode(dailyReview.status)} / ${dailyReview.reviewed_symbols.length} 只股票`
    : Object.keys(review).length
      ? `${displayCode(review.status || '已记录')} / ${reviewedSymbols === null ? '复盘记录' : `${reviewedSymbols} 只股票`} / ${fmtDate(String(review.updated_at || review.trading_date || ''))}`
      : '暂无'
  const commandSummary = commandResult ? `${commandLabel(commandResult.status)} / ${commandResult.symbol || '股票池'}` : '暂无人工控制指令'

  return (
    <div data-testid="signalops-result-snapshot" className="rounded-md border border-slate-200 p-4">
      <div className="text-sm font-semibold text-slate-950">最新操作</div>
      <div className="mt-3 space-y-2 text-xs text-slate-600">
        <div data-testid="signalops-tick-result-summary">单次跟进：{tickSummary}</div>
        <div data-testid="signalops-daily-review-summary">收盘复盘：{reviewSummary}</div>
        <div data-testid="signalops-command-result-summary">控制指令：{commandSummary}</div>
      </div>
    </div>
  )
}

function PoolPanel({
  symbols,
  config,
  stockNameSources,
  portfolios,
  positions,
  orders,
  loading,
  onCommand,
  busy,
  canControl,
  disabledReason,
}: {
  symbols: string[]
  config: AutoPaperTradingConfig
  stockNameSources: StockNameSources
  portfolios: PaperPortfolioItem[]
  positions: PaperPositionItem[]
  orders: PaperOrderItem[]
  loading: boolean
  onCommand: (symbol: string, command: 'FORCE_OPEN_BUY' | 'FORCE_CLOSE' | 'REMOVE_SYMBOL' | 'FORCE_CLOSE_AND_REMOVE') => void
  busy: boolean
  canControl: boolean
  disabledReason?: string
}) {
  const totalCash = portfolios.reduce((sum, item) => sum + Number(item.available_cash || 0), 0)
  const totalMarketValue = portfolios.reduce((sum, item) => sum + Number(item.market_value || 0), 0)
  const totalFloatingPnl = positions.reduce((sum, item) => sum + Number(item.floating_pnl || 0), 0)
  const totalPositionCost = positions.reduce((sum, item) => {
    const quantity = Number(item.quantity || 0)
    const cost = Number(item.virtual_cost || 0)
    return sum + Math.abs(quantity * cost)
  }, 0)
  const pnlRate = Number(config.initial_cash) > 0 ? (totalFloatingPnl / Number(config.initial_cash)) * 100 : null
  const holdingPnlRate = totalPositionCost > 0 ? (totalFloatingPnl / totalPositionCost) * 100 : null
  const isInitialLoading = loading && symbols.length === 0 && portfolios.length === 0 && positions.length === 0
  const symbolNames = stockNamesForSymbols(config, symbols, stockNameSources)
  const symbolNameBySymbol = new Map(symbols.map((symbol, index) => [symbolToken(symbol), symbolNames[index] || symbol]))
  const realtimePnlText = pnlRate === null ? fmtSignedMoney(totalFloatingPnl) : `${fmtSignedMoney(totalFloatingPnl)} / ${fmtNumber(pnlRate, 2)}%`
  const holdingPnlText = holdingPnlRate === null ? '-' : `${fmtSignedMoney(totalFloatingPnl)} / ${fmtNumber(holdingPnlRate, 2)}%`
  return (
    <Card title="股票池资金归因">
      <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Metric label="股票数量" value={isInitialLoading ? '加载中...' : symbols.length || '-'} />
        <Metric label="配置资金" value={isInitialLoading ? '-' : fmtMoney(config.initial_cash)} />
        <Metric label="可用现金" value={isInitialLoading ? '-' : fmtMoney(totalCash)} tone="good" />
        <Metric label="持仓市值" value={isInitialLoading ? '-' : fmtMoney(totalMarketValue)} />
        <Metric
          label="实时盈亏"
          value={isInitialLoading ? '-' : realtimePnlText}
          tone={pnlTone(totalFloatingPnl)}
        />
        <Metric
          label="持仓总盈亏"
          value={isInitialLoading ? '-' : holdingPnlText}
          tone={pnlTone(totalFloatingPnl)}
        />
      </div>
      <TableShell className="mt-4 !rounded-lg !shadow-none">
        <table className="institution-table min-w-full">
          <thead>
            <tr>
              <th>股票代码</th>
              <th>模拟组合</th>
              <th>现金</th>
              <th>持仓市值</th>
              <th>实时盈亏</th>
              <th>订单</th>
              <th>托管</th>
            </tr>
          </thead>
          <tbody>
            {isInitialLoading ? (
              <tr>
                <td className="py-6 text-center text-slate-500" colSpan={7}>正在加载股票池资金归因...</td>
              </tr>
            ) : symbols.map((symbol) => {
              const portfolio = portfolios.find((item) => item.symbol === symbol)
              const symbolFloatingPnl = positions
                .filter((item) => item.symbol === symbol)
                .reduce((sum, item) => sum + Number(item.floating_pnl || 0), 0)
              const symbolPnlTone = pnlTone(symbolFloatingPnl)
              const symbolOrders = orders.filter((item) => item.signal_id === portfolio?.signal_id)
              const stockName = symbolNameBySymbol.get(symbolToken(symbol)) || symbol
            return (
                <tr key={symbol}>
                  <td className="font-medium text-slate-900">
                    <div>{symbol}</div>
                    {stockName !== symbol ? <div className="mt-0.5 text-[11px] font-medium text-slate-500">{stockName}</div> : null}
                  </td>
                  <td className="text-slate-600">{compactId(portfolio?.portfolio_id)}</td>
                  <td className="text-slate-600">{fmtMoney(portfolio?.available_cash)}</td>
                  <td className="text-slate-600">{fmtMoney(portfolio?.market_value)}</td>
                  <td className={`font-medium ${symbolPnlTone === 'good' ? 'text-emerald-700' : symbolPnlTone === 'bad' ? 'text-rose-700' : 'text-slate-600'}`}>
                    {fmtSignedMoney(symbolFloatingPnl)}
                  </td>
                  <td className="text-slate-600">{symbolOrders.length}</td>
                  <td>
                    <Badge status="RUNNING">AI 托管</Badge>
                  </td>
                </tr>
              )
            })}
            {!isInitialLoading && symbols.length === 0 ? (
              <tr>
                <td className="py-6 text-center text-slate-500" colSpan={7}>暂无已配置股票。</td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </TableShell>
      {positions.length > 0 ? (
        <div className="mt-4 grid gap-3 md:grid-cols-3">
          {positions.map((position) => {
            const stockName = symbolNameBySymbol.get(symbolToken(position.symbol)) || position.symbol
            return (
              <Metric
                key={position.position_id}
                label={`${position.symbol}${stockName !== position.symbol ? ` ${stockName}` : ''} 持仓`}
                value={`${fmtNumber(position.quantity, 0)} 股 / ${fmtMoney(position.current_value)} / ${fmtSignedMoney(position.floating_pnl)}`}
                tone={pnlTone(position.floating_pnl)}
              />
            )
          })}
        </div>
      ) : null}
      {symbols.length > 0 ? (
        <details data-testid="signalops-pool-manual-ops" className="mt-4 rounded-md border border-slate-200 p-3">
          <summary className="cursor-pointer text-sm font-medium text-slate-700">人工接管/高级操作</summary>
          <div className="mt-3 space-y-2">
            {symbols.map((symbol) => {
              const stockName = symbolNameBySymbol.get(symbolToken(symbol)) || symbol
              const symbolTestId = symbolToken(symbol)
              return (
              <div key={symbol} className="flex flex-wrap items-center justify-between gap-2 rounded-md bg-slate-50 p-2 text-xs text-slate-600">
                <span className="font-medium text-slate-800">
                  {symbol}
                  {stockName !== symbol ? <span className="ml-2 text-slate-500">{stockName}</span> : null}
                </span>
                <div className="flex flex-wrap gap-2">
                  <ActionButton onClick={() => onCommand(symbol, 'FORCE_OPEN_BUY')} disabled={busy || !canControl} title={disabledReason} icon={<Play size={14} />} testId={`signalops-command-FORCE_OPEN_BUY-${symbolTestId}`}>
                    强制开仓
                  </ActionButton>
                  <ActionButton onClick={() => onCommand(symbol, 'FORCE_CLOSE')} disabled={busy || !canControl} title={disabledReason} icon={<Square size={14} />} testId={`signalops-command-FORCE_CLOSE-${symbolTestId}`}>
                    强制平仓
                  </ActionButton>
                  <ActionButton onClick={() => onCommand(symbol, 'REMOVE_SYMBOL')} disabled={busy || !canControl} title={disabledReason} icon={<Trash2 size={14} />} variant="danger" testId={`signalops-command-REMOVE_SYMBOL-${symbolTestId}`}>
                    移出托管
                  </ActionButton>
                  <ActionButton onClick={() => onCommand(symbol, 'FORCE_CLOSE_AND_REMOVE')} disabled={busy || !canControl} title={disabledReason} icon={<Trash2 size={14} />} variant="danger" testId={`signalops-command-FORCE_CLOSE_AND_REMOVE-${symbolTestId}`}>
                    平仓并移除
                  </ActionButton>
                </div>
              </div>
              )
            })}
          </div>
        </details>
      ) : null}
    </Card>
  )
}

function PerformanceQualityPanel({
  config,
  selectedSymbol,
}: {
  config: AutoPaperTradingConfig
  selectedSymbol: string
}) {
  const stats = asRecord(config.performance_stats)
  const globalStats = asRecord(asRecord(stats.global).all)
  const symbolStats = selectedSymbol ? asRecord(asRecord(stats.symbols)[selectedSymbol]) : {}
  const factorRows = Object.entries(asRecord(stats.factors))
    .map(([key, value]) => ({ key, stats: asRecord(value) }))
    .sort((left, right) => (numericValue(right.stats.confidence) ?? 0) - (numericValue(left.stats.confidence) ?? 0))
    .slice(0, 3)
  const lowQualityTriggers = Object.entries(asRecord(stats.triggers))
    .map(([key, value]) => ({ key, stats: asRecord(value) }))
    .filter((item) => ['POOR', 'LOW_SAMPLE'].includes(String(item.stats.quality_status || '').toUpperCase()))
    .sort((left, right) => (numericValue(right.stats.trade_count) ?? 0) - (numericValue(left.stats.trade_count) ?? 0))
    .slice(0, 3)
  const globalTradeCount = numericValue(globalStats.trade_count) ?? 0
  const globalStatus = String(globalStats.quality_status || (globalTradeCount > 0 ? 'WATCH' : 'LOW_SAMPLE'))
  const symbolTradeCount = numericValue(symbolStats.trade_count) ?? 0
  const symbolStatus = String(symbolStats.quality_status || (selectedSymbol ? 'LOW_SAMPLE' : 'UNOBSERVED'))
  const lastTuning = asRecord(asRecord(config.last_research_review).tuning_update)
  const applicationStatus = String(lastTuning.application_status || '-')
  const applicationReason = String(lastTuning.application_reason || '-')
  const factorBarRows = factorRows.map((item) => {
    const expectancy = numericValue(item.stats.expectancy)
    const winRate = numericValue(item.stats.win_rate)
    return {
      label: item.key,
      value: expectancy ?? winRate ?? 0,
      helper: `胜率 ${fmtRate(item.stats.win_rate)} / 期望 ${fmtRate(item.stats.expectancy)} / ${displayCode(item.stats.quality_status)}`,
      tone: factorToneFromValue(expectancy ?? winRate),
    }
  })
  const lowQualityTriggerRows = lowQualityTriggers.map((item) => ({
    label: item.key,
    value: numericValue(item.stats.win_rate) ?? 0,
    helper: `${displayCode(item.stats.quality_status)} / trades ${fmtNumber(item.stats.trade_count, 0)}`,
    tone: 'negative' as const,
  }))

  return (
    <div className="mt-4 rounded-md border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm font-semibold text-slate-950">胜率质量</div>
        <Badge status={globalStatus}>{globalStatus === 'LOW_SAMPLE' ? '样本不足，仅观察' : displayCode(globalStatus)}</Badge>
      </div>
      <div className="mt-3 grid gap-2 md:grid-cols-4">
        <Metric label="滚动胜率" value={fmtRate(globalStats.win_rate)} tone={qualityTone(globalStatus)} />
        <Metric label="交易样本" value={globalTradeCount || '-'} tone={globalTradeCount >= 5 ? 'good' : 'warn'} />
        <Metric label="期望收益" value={fmtRate(globalStats.expectancy)} tone={pnlTone(globalStats.expectancy)} />
        <Metric label="最大回撤" value={fmtRate(globalStats.max_drawdown)} tone={pnlTone(globalStats.max_drawdown)} />
      </div>
      <div className="mt-3 grid gap-2 md:grid-cols-3">
        <Metric label="置信度" value={fmtRate(globalStats.confidence)} />
        <Metric label={selectedSymbol ? `${selectedSymbol} 胜率` : '当前股票胜率'} value={symbolTradeCount ? fmtRate(symbolStats.win_rate) : '样本不足，仅观察'} tone={qualityTone(symbolStatus)} />
        <Metric
          label="最近调参"
          value={(
            <span className="block max-w-full truncate" title={`${displayCode(applicationStatus)} / ${compactReasonLabel(applicationReason).detail}`}>
              {displayCode(applicationStatus)} / {compactReasonLabel(applicationReason).summary}
            </span>
          )}
        />
      </div>
      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
          <div className="text-xs font-semibold text-slate-700">因子来源排行</div>
          <div className="mt-3 text-xs text-slate-600">
            {factorBarRows.length ? <FactorBarStack rows={factorBarRows} maxAbs={1} /> : (
              <div>暂无因子胜率样本。</div>
            )}
          </div>
        </div>
        <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
          <div className="text-xs font-semibold text-slate-700">低质量触发条件</div>
          <div className="mt-3 text-xs text-slate-600">
            {lowQualityTriggerRows.length ? <FactorBarStack rows={lowQualityTriggerRows} maxAbs={1} /> : (
              <div>暂无需要降权的触发条件。</div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function AiStrategyReviewPanel({
  review,
  config,
  selectedSignal,
}: {
  review: Record<string, unknown>
  config: AutoPaperTradingConfig
  selectedSignal: SignalItem
}) {
  const tuning = asRecord(review.tuning_update)
  const before = asRecord(tuning.before)
  const recommendedParameters = asRecord(tuning.recommended_parameters)
  const appliedParameters = asRecord(tuning.applied_parameters)
  const legacyNextParameters = asRecord(tuning.next_parameters)
  const nextParameters = Object.keys(recommendedParameters).length ? recommendedParameters : legacyNextParameters
  const performanceSummary = asRecord(tuning.performance_summary)
  const globalPerformance = asRecord(performanceSummary.global)
  const activeConfig = config as unknown as Record<string, unknown>
  const cleanedRecords = Array.isArray(review.cleaned_records) ? review.cleaned_records.map(asRecord) : []
  const tradeRecords = cleanedRecords.filter((item) => (numericValue(item.order_count) ?? 0) > 0)
  const selectedRecord = tradeRecords.find((item) => String(item.symbol || '') === selectedSignal.symbol)
  const compressedObservations = asRecord(tuning.compressed_observation_history || review.compressed_observation_history || config.compressed_observation_history)
  const compressedObservationTotal = compressedObservationCount(compressedObservations)
  const currentNoTradeCount = numericValue(tuning.current_no_trade_count)
    ?? cleanedRecords.filter((item) => (numericValue(item.order_count) ?? 0) <= 0).length
  const selectedCompressedObservationCount = compressedObservationSymbolCount(compressedObservations, selectedSignal.symbol)
  const sampleCount = numericValue(tuning.sample_count) ?? tradeRecords.length
  const tradeCount = numericValue(tuning.trade_count) ?? sampleCount
  const wins = numericValue(tuning.wins) ?? 0
  const failures = numericValue(tuning.failures) ?? 0
  const riskTightened = tuning.risk_tightened === true
  const applicationStatus = String(tuning.application_status || (Object.keys(legacyNextParameters).length ? 'APPLIED' : 'SKIPPED'))
  const applicationReason = String(tuning.application_reason || '-')
  const changedParams = Object.entries(nextParameters)
    .filter(([key, nextValue]) => {
      const beforeValue = before[key]
      return numericValue(beforeValue) !== null && numericValue(nextValue) !== null && Number(beforeValue) !== Number(nextValue)
    })
    .map(([key, nextValue]) => ({
      key,
      beforeValue: before[key],
      nextValue,
      currentValue: activeConfig[key],
      applied: applicationStatus === 'APPLIED' && tuningValueApplied(activeConfig[key], appliedParameters[key] ?? nextValue),
    }))
  const appliedCount = changedParams.filter((item) => item.applied).length
  const allChangedParamsApplied = changedParams.length > 0 && appliedCount === changedParams.length
  const appliedStatus = changedParams.length === 0
    ? '无需调整'
    : allChangedParamsApplied
      ? '已写入当前托管配置'
      : `${appliedCount}/${changedParams.length} 项已生效`
  const effectiveAppliedStatus = applicationStatus === 'RECOMMENDED_ONLY'
    ? '仅记录建议，未改配置'
    : applicationStatus === 'APPLIED'
      ? '已写入当前托管配置'
      : appliedStatus
  const pendingParamCount = Math.max(changedParams.length - appliedCount, 0)
  const strategyExperiment = asRecord(tuning.strategy_experiment)
  const promotionGate = asRecord(strategyExperiment.promotion_gate)
  const walkForwardValidation = asRecord(tuning.walk_forward_validation || promotionGate.validation)
  const trainMetrics = asRecord(walkForwardValidation.train_metrics)
  const validationMetrics = asRecord(walkForwardValidation.validation_metrics)
  const trainTradeCount = numericValue(trainMetrics.trade_count) ?? 0
  const validationTradeCount = numericValue(validationMetrics.trade_count) ?? 0
  const validationChecks = asRecord(walkForwardValidation.checks)
  const trainTradeMin = numericValue(validationChecks.train_trade_count_min) ?? 5
  const validationTradeMin = numericValue(validationChecks.validation_trade_count_min) ?? 3
  const validationWindow = asRecord(walkForwardValidation.validation_window)
  const benchmarkComparison = asRecord(strategyExperiment.benchmark_comparison || walkForwardValidation.benchmark_comparison)
  const experimentHash = String(strategyExperiment.experiment_package_hash || tuning.experiment_package_hash || '')
  const backtestReason = compactReasonLabel(applicationReason)
  const backtestGateNote = applicationStatus === 'BACKTEST_PENDING'
    ? `回测验证不会由下一次自动跟进触发；候选包生成后，需要专用 SignalOps 回测实验写回结果。当前仍停在验证中：${backtestReason.summary}。`
    : applicationStatus === 'READY_FOR_REVIEW'
      ? '回测验证已达到待审查门槛；下一步是审查通过并写入模拟托管配置。'
      : ''
  const activationNote = changedParams.length === 0
    ? '本次复盘没有参数变更，继续沿用当前托管配置。'
    : allChangedParamsApplied
      ? '已生效：参数已写入当前托管配置，下一次自动跟进会按这些值执行。'
      : applicationStatus === 'APPLIED_TO_SIMULATION'
        ? `已批准写入模拟，但当前托管配置仍有 ${pendingParamCount} 项未对齐；请刷新后复核配置写入结果。`
        : applicationStatus === 'BACKTEST_PENDING'
          ? '待生效：先等待回测验证和审查通过，写入模拟托管配置后，下一次自动跟进开始使用。'
          : applicationStatus === 'READY_FOR_REVIEW'
            ? '待生效：审查通过并写入模拟托管配置后，下一次自动跟进开始使用。'
            : applicationStatus === 'RECOMMENDED_ONLY'
              ? '仅记录建议：当前不会自动生效，需要形成候选并通过审查后才会写入托管配置。'
              : ['REJECTED', 'SUPERSEDED', 'EXPIRED'].includes(applicationStatus)
                ? '不会生效：该候选已驳回、过期或被新候选替代。'
                : '待生效：参数写入当前托管配置并与候选值对齐后，下一次自动跟进开始使用。'
  const hasReviewForDisplay = Boolean(Object.keys(review).length && Object.keys(tuning).length)
  const displayConclusion = !hasReviewForDisplay
    ? '等待复盘'
    : applicationStatus === 'RECOMMENDED_ONLY'
      ? '样本不足，仅观察'
      : riskTightened || failures > wins
        ? '建议收紧策略'
        : wins > failures
          ? '策略可小幅放宽'
          : '暂不调整策略'
  const reviewDate = String(review.trading_date || config.last_research_review_date || '-')
  const reviewUpdatedAt = String(review.updated_at || config.updated_at || '-')
  const hasReview = Boolean(Object.keys(review).length && Object.keys(tuning).length)
  const conclusion = !hasReview
    ? '等待复盘'
    : riskTightened || failures > wins
      ? '建议收紧策略'
      : wins > failures
        ? '策略可小幅放宽'
        : '暂不调整策略'

  if (!hasReview) {
    return (
      <div className="rounded-md border border-dashed border-slate-200 p-4 text-sm text-slate-500">
        暂无 AI 每日复盘结果。
      </div>
    )
  }

  return (
    <div className="rounded-md border border-cyan-100 bg-cyan-50 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm font-semibold text-cyan-950">AI 每日复盘策略</div>
        <Badge status={applicationStatus === 'RECOMMENDED_ONLY' ? 'WATCH' : riskTightened ? 'PATCH_REQUIRED' : 'REVIEWED'}>{displayConclusion || conclusion}</Badge>
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <Metric label="复盘日期" value={reviewDate} />
        <Metric label="交易验证样本" value={sampleCount || '-'} />
        <Metric label="观察压缩" value={compressedObservationTotal ? `${compressedObservationTotal} 条` : '-'} tone={currentNoTradeCount ? 'warn' : 'default'} />
        <Metric label="盈利样本" value={wins} tone={wins > 0 ? 'good' : 'default'} />
        <Metric label="失效样本" value={failures} tone={failures > 0 ? 'warn' : 'default'} />
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-3">
        <Metric label="交易样本" value={tradeCount || '-'} tone={tradeCount >= 5 ? 'good' : 'warn'} />
        <Metric label="滚动胜率" value={fmtRate(globalPerformance.win_rate)} tone={qualityTone(globalPerformance.quality_status)} />
        <Metric label="期望收益" value={fmtRate(globalPerformance.expectancy)} tone={pnlTone(globalPerformance.expectancy)} />
        <Metric label="调参原因" value={<CompactReason value={applicationReason} />} />
      </div>
      <div className="mt-3 rounded-md border border-cyan-200 bg-white/70 p-3 text-xs text-cyan-900">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="font-medium">参数生效确认</span>
          <Badge status={changedParams.length === 0 ? 'SKIPPED' : allChangedParamsApplied ? 'PASS' : 'WARN'}>
            {effectiveAppliedStatus}
          </Badge>
        </div>
        <div className="mt-2 text-cyan-800">
          复盘写入时间：{fmtDate(reviewUpdatedAt)}；确认方式：候选参数与当前托管配置逐项对齐。
        </div>
        <div className="mt-1 text-cyan-800">
          {activationNote}
        </div>
        {backtestGateNote ? (
          <div className="mt-2 rounded border border-cyan-200 bg-white/70 p-2 text-cyan-900">
            <div className="font-medium">回测验证状态</div>
            <div className="mt-1 text-cyan-800">{backtestGateNote}</div>
            <div className="mt-2 grid gap-1 text-cyan-800 sm:grid-cols-2">
              <span>候选包：{compactId(experimentHash)}</span>
              <span>目标结果：{displayCode(promotionGate.required_outcome || 'READY_FOR_REVIEW')}</span>
              <span>验证窗口：{compactDateValue(validationWindow.start)} 到 {compactDateValue(validationWindow.end)}</span>
              <span>基准：{displayCode(benchmarkComparison.status || (benchmarkComparison.available ? 'AVAILABLE' : 'UNAVAILABLE'))}</span>
              <span>训练成交：{fmtNumber(trainTradeCount, 0)} / {fmtNumber(trainTradeMin, 0)}</span>
              <span>验证成交：{fmtNumber(validationTradeCount, 0)} / {fmtNumber(validationTradeMin, 0)}</span>
              <span>观察压缩：{compressedObservationTotal ? `${fmtNumber(compressedObservationTotal, 0)} 条` : '-'}</span>
              <span>压缩窗口：{compressedObservationWindow(compressedObservations)}</span>
            </div>
          </div>
        ) : null}
      </div>
      {selectedRecord ? (
        <div className="mt-3 rounded-md border border-cyan-200 bg-white/70 p-3 text-xs text-cyan-900">
          <div className="font-medium">{selectedSignal.symbol} 单股复盘</div>
          <div className="mt-2 grid gap-2 sm:grid-cols-3">
            <span>最新动作：{displayCode(selectedRecord.latest_action)}</span>
            <span>浮动收益率：{fmtTuningValue('pnl_rate_pct', (numericValue(selectedRecord.pnl_rate) ?? 0) * 100)}</span>
            <span>触发失效：{yesNo(selectedRecord.invalidation_triggered === true)}</span>
          </div>
        </div>
      ) : selectedCompressedObservationCount ? (
        <div className="mt-3 rounded-md border border-cyan-200 bg-white/70 p-3 text-xs text-cyan-900">
          <div className="font-medium">{selectedSignal.symbol} 观察已压缩</div>
          <div className="mt-2 text-cyan-800">
            {fmtNumber(selectedCompressedObservationCount, 0)} 条 NONE / order_count=0 观察已进入压缩摘要，不在历史里逐条展开；回测验证只读取有效模拟成交。
          </div>
        </div>
      ) : null}
      <div className="mt-3 space-y-2 text-xs text-cyan-900">
        <div className="font-medium">策略参数调整</div>
        {changedParams.length > 0 ? changedParams.map(({ key, beforeValue, nextValue, currentValue, applied }) => (
          <div key={key} className="flex flex-wrap items-center justify-between gap-2 rounded border border-cyan-200 bg-white/70 px-3 py-2">
            <span>{TUNING_PARAM_LABELS[key] || key}</span>
            <span className="flex flex-wrap items-center justify-end gap-2 text-right">
              <span className="font-medium">{fmtTuningValue(key, beforeValue)} → {fmtTuningValue(key, nextValue)}</span>
              <span className="text-cyan-700">当前 {fmtTuningValue(key, currentValue)}</span>
              <Badge status={applied ? 'PASS' : 'WARN'}>{applied ? '已生效' : '待生效'}</Badge>
            </span>
          </div>
        )) : (
          <div className="rounded border border-cyan-200 bg-white/70 px-3 py-2">暂无参数变更，沿用当前策略。</div>
        )}
      </div>
    </div>
  )
}

function EditableSignalPanel({
  editable,
  onChange,
  onUpdateConditions,
  onTransition,
  onReview,
  busy,
  canEdit,
  disabledReason,
}: {
  editable: EditableSignalState
  onChange: (value: EditableSignalState) => void
  onUpdateConditions: () => void
  onTransition: () => void
  onReview: () => void
  busy: boolean
  canEdit: boolean
  disabledReason?: string
}) {
  const update = <K extends keyof EditableSignalState>(key: K, value: EditableSignalState[K]) => onChange({ ...editable, [key]: value })
  return (
    <div className="space-y-3">
      <label className="block text-xs font-medium text-slate-600">
        触发条件
        <textarea className="mt-1 h-24 w-full rounded-md border border-slate-200 p-2 text-sm" value={editable.triggerConditions} onChange={(event) => update('triggerConditions', event.target.value)} />
      </label>
      <label className="block text-xs font-medium text-slate-600">
        失效条件
        <textarea className="mt-1 h-24 w-full rounded-md border border-slate-200 p-2 text-sm" value={editable.invalidationConditions} onChange={(event) => update('invalidationConditions', event.target.value)} />
      </label>
      <label className="block text-xs font-medium text-slate-600">
        复核字段
        <textarea className="mt-1 h-20 w-full rounded-md border border-slate-200 p-2 text-sm" value={editable.reviewFields} onChange={(event) => update('reviewFields', event.target.value)} />
      </label>
      <div className="grid gap-3 md:grid-cols-2">
        <label className="block text-xs font-medium text-slate-600">
          目标状态
          <select className="mt-1 w-full rounded-md border border-slate-200 px-3 py-2 text-sm" value={editable.transitionTarget} onChange={(event) => update('transitionTarget', event.target.value as SignalOpsStatus)}>
            {STATUS_FLOW.map((status) => <option key={status} value={status}>{displayCode(status)}</option>)}
          </select>
        </label>
        <label className="block text-xs font-medium text-slate-600">
          复核备注
          <input className="mt-1 w-full rounded-md border border-slate-200 px-3 py-2 text-sm" value={editable.reviewNote} onChange={(event) => update('reviewNote', event.target.value)} />
        </label>
      </div>
      <div className="flex flex-wrap gap-2">
        <ActionButton onClick={onUpdateConditions} disabled={busy || !canEdit} title={disabledReason} icon={<Save size={16} />}>
          保存条件
        </ActionButton>
        <ActionButton onClick={onTransition} disabled={busy || !canEdit} title={disabledReason} icon={<Play size={16} />}>
          流转状态
        </ActionButton>
        <ActionButton onClick={onReview} disabled={busy || !canEdit} title={disabledReason} icon={<Plus size={16} />}>
          添加复核
        </ActionButton>
      </div>
    </div>
  )
}

function SignalHistoryPanel({ detail }: { detail: SignalDetail | null }) {
  const transitions = detail?.transitions || []
  const reviews = detail?.reviews || []
  return (
    <div className="grid min-w-0 gap-3 lg:grid-cols-2 2xl:grid-cols-1">
      <div className="min-w-0 overflow-hidden rounded-md border border-slate-200 p-3">
        <div className="flex min-w-0 items-center justify-between gap-2">
          <div className="text-sm font-semibold text-slate-950">生命周期</div>
          <span className="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-500">{transitions.length}</span>
        </div>
        <div className="mt-3 max-h-72 space-y-2 overflow-y-auto pr-1">
          {transitions.slice(0, 6).map((item) => (
            <div key={item.transition_id} className="min-w-0 overflow-hidden rounded-md bg-slate-50 p-2 text-xs leading-5 text-slate-600">
              <div className="grid min-w-0 gap-1 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start">
                <Badge status={item.to_status} className="max-w-full justify-self-start whitespace-normal text-left">{displayCode(item.from_status)} 到 {displayCode(item.to_status)}</Badge>
                <span className="min-w-0 break-words text-slate-500 [overflow-wrap:anywhere] sm:text-right">{fmtDate(item.created_at)}</span>
              </div>
              <div className="mt-1 min-w-0 max-h-16 overflow-y-auto whitespace-pre-wrap break-words pr-1 [overflow-wrap:anywhere]">{item.reason || '-'}</div>
            </div>
          ))}
          {transitions.length === 0 ? <div className="text-xs text-slate-500">暂无状态流转记录。</div> : null}
        </div>
      </div>
      <div className="min-w-0 overflow-hidden rounded-md border border-slate-200 p-3">
        <div className="flex min-w-0 items-center justify-between gap-2">
          <div className="text-sm font-semibold text-slate-950">复核记录</div>
          <span className="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-500">{reviews.length}</span>
        </div>
        <div className="mt-3 max-h-72 space-y-2 overflow-y-auto pr-1">
          {reviews.slice(0, 6).map((item) => (
            <div key={item.review_id} className="min-w-0 overflow-hidden rounded-md bg-slate-50 p-2 text-xs leading-5 text-slate-600">
              <div className="grid min-w-0 gap-1 sm:grid-cols-[auto_minmax(0,1fr)_auto] sm:items-start">
                <Badge status={item.decision} className="justify-self-start whitespace-normal text-left">{displayCode(item.decision)}</Badge>
                <span className="min-w-0 truncate" title={item.reviewer}>{item.reviewer}</span>
                <span className="min-w-0 break-words text-slate-500 [overflow-wrap:anywhere] sm:text-right">{fmtDate(item.created_at)}</span>
              </div>
              <div className="mt-1 min-w-0 max-h-16 overflow-y-auto whitespace-pre-wrap break-words pr-1 [overflow-wrap:anywhere]">{item.note || '-'}</div>
            </div>
          ))}
          {reviews.length === 0 ? <div className="text-xs text-slate-500">暂无复核记录。</div> : null}
        </div>
      </div>
    </div>
  )
}

function OrdersPanel({ orders }: { orders: PaperOrderItem[] }) {
  const [expanded, setExpanded] = useState(false)
  const sortedOrders = useMemo(
    () => [...orders].sort((left, right) => (right.updated_at || right.created_at || '').localeCompare(left.updated_at || left.created_at || '')),
    [orders],
  )
  const visibleOrders = expanded ? sortedOrders : sortedOrders.slice(0, ORDER_PREVIEW_LIMIT)
  const hiddenCount = Math.max(0, sortedOrders.length - visibleOrders.length)

  if (orders.length === 0) {
    return <div className="rounded-md border border-dashed border-slate-200 p-4 text-sm text-slate-500">该信号暂无模拟订单。</div>
  }
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
        <span>订单信息：展示最近 {Math.min(sortedOrders.length, ORDER_PREVIEW_LIMIT)} 条。</span>
        <span>信息沉淀：每日复盘自动完成。</span>
      </div>
      <TableShell className="!rounded-lg !shadow-none">
        <table className="institution-table min-w-full">
          <thead>
            <tr>
              <th>订单</th>
              <th>动作</th>
              <th>数量</th>
              <th>价格</th>
              <th>决策预算</th>
              <th>总费用</th>
              <th>更新时间</th>
            </tr>
          </thead>
          <tbody>
            {visibleOrders.map((order) => {
              const card = extractDecisionCard(order)
              const fill = asRecord(order.simulated_fill)
              const governance = buildPaperOrderGovernance(order)
              return (
                <Fragment key={order.order_id}>
                  <tr>
                    <td className="text-slate-600">{compactId(order.order_id)}</td>
                    <td><Badge status={order.action}>{displayCode(order.action)}</Badge></td>
                    <td className="text-slate-600">{fmtNumber(order.simulated_quantity, 0)}</td>
                    <td className="text-slate-600">{fmtMoney(order.simulated_price)}</td>
                    <td className="text-slate-600">{fmtMoney(card.budget_used)}</td>
                    <td className="text-slate-600">{fmtMoney(fill.fees ?? card.total_fee ?? card.commission_fee)}</td>
                    <td className="text-slate-600">{fmtDate(order.updated_at)}</td>
                  </tr>
                  <tr data-testid={`signalops-paper-order-governance-${order.order_id}`}>
                    <td colSpan={7} className="bg-slate-50">
                      <div className="grid gap-2 rounded-md border border-cyan-100 bg-cyan-50 p-2 text-[11px] text-slate-700 sm:grid-cols-2 xl:grid-cols-5">
                        <span data-testid={`signalops-paper-order-id-${order.order_id}`} className="min-w-0 break-all">
                          Order: {governance.contextId}
                        </span>
                        <span data-testid={`signalops-paper-order-evidence-strength-${order.order_id}`} className="min-w-0 break-words">
                          Evidence: {governance.evidenceStrength}
                        </span>
                        <span data-testid={`signalops-paper-order-blocker-${order.order_id}`} className="min-w-0 break-words">
                          Blocker: {governance.blocker}
                        </span>
                        <span data-testid={`signalops-paper-order-next-action-${order.order_id}`} className="min-w-0 break-words">
                          Next: {governance.nextAction}
                        </span>
                        <span data-testid={`signalops-paper-order-simulation-boundary-${order.order_id}`} className="min-w-0 break-words font-medium text-slate-900">
                          simulation_only={String(governance.simulationOnly)} / is_real_trade={String(governance.isRealTrade)} / evidence_usage={governance.evidenceUsage} / strong_conclusion_allowed={String(governance.strongConclusionAllowed)} / SIM_*
                        </span>
                      </div>
                    </td>
                  </tr>
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </TableShell>
      {sortedOrders.length > ORDER_PREVIEW_LIMIT ? (
        <button
          type="button"
          className="inline-flex items-center gap-1 text-xs font-medium text-slate-600 hover:text-cyan-700"
          onClick={() => setExpanded((current) => !current)}
        >
          {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          {expanded ? '收起历史订单' : `展开 ${hiddenCount} 条历史订单`}
        </button>
      ) : null}
    </div>
  )
}
