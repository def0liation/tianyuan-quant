import { request } from './httpClient'

export type GlobalMarketDataMode = 'LIVE' | 'FALLBACK' | 'STALE' | 'UNAVAILABLE'
export type GlobalMarketFreshness = 'REALTIME' | 'POST_CLOSE_PENDING_EOD' | 'EOD' | 'STALE' | 'UNKNOWN'
export type GlobalMarketSourceConsensus = 'NO_DATA' | 'SINGLE_SOURCE' | 'CONSENSUS' | 'DIVERGED'

export interface GlobalMarketKlineRow {
  tradeDate: string
  open: number
  high: number
  low: number
  close: number
  preClose?: number | null
  change?: number | null
  pctChange?: number | null
  volume?: number | null
  amount?: number | null
  derived?: boolean
  sourceId?: string
}

export interface GlobalMarketSourceChainItem {
  sourceId: string
  provider: string
  source: string
  apiName: string
  status: 'READY' | 'FAILED'
  dataMode: GlobalMarketDataMode
  freshness?: GlobalMarketFreshness
  tradeDate?: string
  recordCount: number
  confidence: number
  message: string
  error: string
}

export interface GlobalMarketSourceConflict {
  field: string
  severity: 'HIGH' | 'MEDIUM' | 'LOW'
  primarySource: string
  otherSource: string
  sector?: string
  message?: string
  primaryValue?: string | number | null
  otherValue?: string | number | null
  absoluteDiff?: number
  relativeDiff?: number
  tolerance?: number
}

export interface GlobalMarketArbitration {
  capability: string
  selectedSource: string
  sourceConsensus: GlobalMarketSourceConsensus
  resolution: string
  checkedSources: GlobalMarketSourceChainItem[]
  conflicts: GlobalMarketSourceConflict[]
  dataQuality: {
    score: number
    level: 'HIGH' | 'MEDIUM' | 'LOW' | 'REVIEW_ONLY'
    reviewOnly: boolean
    highConflictCount: number
    mediumConflictCount: number
  }
  generatedAt: string
}

export interface GlobalMarketIndex {
  key: string
  symbol: string
  name: string
  exchange: string
  apiName: string
  status: 'READY' | 'FAILED'
  dataMode: GlobalMarketDataMode
  selectedProvider: string
  selectedSource: string
  fallbackUsed: boolean
  freshness: GlobalMarketFreshness
  sourceConsensus: GlobalMarketSourceConsensus
  reviewOnly: boolean
  range: '4m'
  recordCount: number
  lastTradeDate?: string
  latestQuoteTime?: string
  latest?: GlobalMarketKlineRow & { ma5?: number | null; ma10?: number | null; ma20?: number | null }
  rows: GlobalMarketKlineRow[]
  dailyRenderMode: 'TUSHARE_EOD' | 'TUSHARE_STALE' | 'UNAVAILABLE'
  dailyRenderMessage: string
  sourceChain: GlobalMarketSourceChainItem[]
  arbitration?: GlobalMarketArbitration
  conflicts: GlobalMarketSourceConflict[]
  message: string
  error: string
}

export interface GlobalMarketFundFlowRow {
  tradeDate: string
  netAmount: number
  mainNetAmount: number
  smallNetAmount: number
}

export interface GlobalMarketFundFlow {
  status: 'READY' | 'FAILED'
  dataMode: GlobalMarketDataMode
  provider: string
  apiName: string
  selectedProvider: string
  selectedSource: string
  fallbackUsed: boolean
  freshness: GlobalMarketFreshness
  sourceConsensus: GlobalMarketSourceConsensus
  reviewOnly: boolean
  latestDate: string
  netAmount: number | null
  mainNetAmount: number | null
  smallNetAmount: number | null
  unit: string
  rows: GlobalMarketFundFlowRow[]
  sourceChain: GlobalMarketSourceChainItem[]
  arbitration?: GlobalMarketArbitration
  conflicts: GlobalMarketSourceConflict[]
  message: string
  error: string
}

export interface GlobalMarketTemperature {
  score: number
  label: string
  status: 'PASS' | 'WARN' | 'FAIL'
  trendScore: number
  breadthScore: number
  flowScore: number
  risingCount: number
  fallingCount: number
  reasons: string[]
  reviewOnly?: boolean
}

export interface GlobalMarketSectorRankRow {
  rank: number | null
  name: string
  code: string
  latest: number | null
  change: number | null
  pctChange: number | null
  marketCap: number | null
  turnoverRate: number | null
  risingCount: number | null
  fallingCount: number | null
  leadingStock: string
  leadingStockPctChange: number | null
}

export interface GlobalMarketSectorRankCandidate {
  sourceId: string
  provider: string
  source: string
  apiName: string
  status: 'READY' | 'FAILED'
  dataMode: GlobalMarketDataMode
  recordCount: number
  confidence: number
  message: string
  error: string
}

export interface GlobalMarketSectorRankConflict {
  field: string
  severity: 'HIGH' | 'MEDIUM' | 'LOW'
  primarySource: string
  otherSource: string
  sector?: string
  message?: string
  primaryValue?: string | number | null
  otherValue?: string | number | null
  absoluteDiff?: number
  relativeDiff?: number
  tolerance?: number
}

export interface GlobalMarketSectorRankArbitration {
  capability: string
  selectedSource: string
  sourceConsensus: 'NO_DATA' | 'SINGLE_SOURCE' | 'CONSENSUS' | 'DIVERGED'
  resolution: string
  checkedSources: GlobalMarketSectorRankCandidate[]
  conflicts: GlobalMarketSectorRankConflict[]
  dataQuality: {
    score: number
    level: 'HIGH' | 'MEDIUM' | 'LOW' | 'REVIEW_ONLY'
    reviewOnly: boolean
    highConflictCount: number
    mediumConflictCount: number
  }
  generatedAt: string
}

export interface GlobalMarketSectorRank {
  status: 'READY' | 'FAILED'
  dataMode: GlobalMarketDataMode
  provider: string
  source: string
  apiName: string
  boardType: 'industry'
  tradeDate: string
  fetchedAt: string
  recordCount: number
  selectedProvider?: string
  selectedSource?: string
  sourceCount?: { ready: number; total: number }
  candidateSources?: GlobalMarketSectorRankCandidate[]
  arbitration?: GlobalMarketSectorRankArbitration
  top: GlobalMarketSectorRankRow[]
  bottom: GlobalMarketSectorRankRow[]
  rows: GlobalMarketSectorRankRow[]
  message: string
  error: string
}

export interface GlobalMarketOverview {
  status: 'READY' | 'PARTIAL' | 'FAILED'
  dataMode: GlobalMarketDataMode
  provider: string
  range: '4m'
  fetchedAt: string
  refreshIntervalSeconds: number
  indices: GlobalMarketIndex[]
  fundFlow: GlobalMarketFundFlow
  sectorRank: GlobalMarketSectorRank
  temperature: GlobalMarketTemperature
  message: string
  error: string
}

export async function getGlobalMarketOverview() {
  const payload = await request<unknown>('/market-data/global?range=4m', { timeoutMs: 60000 })
  return normalizeGlobalMarketOverview(assertGlobalMarketOverviewPayload(payload))
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function assertRecord(value: unknown, label: string): Record<string, unknown> {
  if (!isRecord(value)) {
    throw new Error(`${label} must be an object`)
  }
  return value
}

function assertOptionalStringField(record: Record<string, unknown>, field: string, label: string) {
  if (record[field] !== undefined && typeof record[field] !== 'string') {
    throw new Error(`${label}.${field} must be a string`)
  }
}

function assertOptionalNumberField(record: Record<string, unknown>, field: string, label: string) {
  if (record[field] !== undefined && (typeof record[field] !== 'number' || !Number.isFinite(record[field]))) {
    throw new Error(`${label}.${field} must be a number`)
  }
}

function assertRequiredStringField(record: Record<string, unknown>, field: string, label: string) {
  if (typeof record[field] !== 'string') {
    throw new Error(`${label}.${field} must be a string`)
  }
}

function assertRequiredNumberField(record: Record<string, unknown>, field: string, label: string) {
  if (typeof record[field] !== 'number' || !Number.isFinite(record[field])) {
    throw new Error(`${label}.${field} must be a finite number`)
  }
}

function assertOptionalNullableNumberField(record: Record<string, unknown>, field: string, label: string) {
  const value = record[field]
  if (value !== undefined && value !== null && (typeof value !== 'number' || !Number.isFinite(value))) {
    throw new Error(`${label}.${field} must be a finite number or null`)
  }
}

function assertOptionalBooleanField(record: Record<string, unknown>, field: string, label: string) {
  if (record[field] !== undefined && typeof record[field] !== 'boolean') {
    throw new Error(`${label}.${field} must be a boolean`)
  }
}

function assertOptionalScalarConflictValue(record: Record<string, unknown>, field: string, label: string) {
  const value = record[field]
  if (
    value !== undefined &&
    value !== null &&
    typeof value !== 'string' &&
    (typeof value !== 'number' || !Number.isFinite(value))
  ) {
    throw new Error(`${label}.${field} must be a string, finite number, or null`)
  }
}

function assertOptionalObjectField(record: Record<string, unknown>, field: string, label: string) {
  if (record[field] !== undefined && !isRecord(record[field])) {
    throw new Error(`${label}.${field} must be an object`)
  }
}

function assertOptionalArrayField(record: Record<string, unknown>, field: string, label: string) {
  if (record[field] !== undefined && !Array.isArray(record[field])) {
    throw new Error(`${label}.${field} must be an array`)
  }
}

function assertArrayItemsObject(value: unknown, label: string) {
  if (!Array.isArray(value)) return
  value.forEach((item, index) => {
    if (!isRecord(item)) {
      throw new Error(`${label}[${index}] must be an object`)
    }
  })
}

function assertArrayItemsString(value: unknown, label: string) {
  if (!Array.isArray(value)) return
  value.forEach((item, index) => {
    if (typeof item !== 'string') {
      throw new Error(`${label}[${index}] must be a string`)
    }
  })
}

function assertGlobalMarketKlineRow(value: unknown, label: string) {
  const row = assertRecord(value, label)
  assertRequiredStringField(row, 'tradeDate', label)
  assertRequiredNumberField(row, 'open', label)
  assertRequiredNumberField(row, 'high', label)
  assertRequiredNumberField(row, 'low', label)
  assertRequiredNumberField(row, 'close', label)
  assertOptionalNullableNumberField(row, 'preClose', label)
  assertOptionalNullableNumberField(row, 'change', label)
  assertOptionalNullableNumberField(row, 'pctChange', label)
  assertOptionalNullableNumberField(row, 'volume', label)
  assertOptionalNullableNumberField(row, 'amount', label)
  assertOptionalNullableNumberField(row, 'ma5', label)
  assertOptionalNullableNumberField(row, 'ma10', label)
  assertOptionalNullableNumberField(row, 'ma20', label)
  assertOptionalBooleanField(row, 'derived', label)
  assertOptionalStringField(row, 'sourceId', label)
}

function hasRequiredKlineFields(value: unknown): value is GlobalMarketKlineRow {
  if (!isRecord(value)) return false
  return (
    typeof value.tradeDate === 'string' &&
    typeof value.open === 'number' &&
    Number.isFinite(value.open) &&
    typeof value.high === 'number' &&
    Number.isFinite(value.high) &&
    typeof value.low === 'number' &&
    Number.isFinite(value.low) &&
    typeof value.close === 'number' &&
    Number.isFinite(value.close)
  )
}

function assertGlobalMarketSourceChainItem(value: unknown, label: string) {
  const source = assertRecord(value, label)
  assertOptionalStringField(source, 'sourceId', label)
  assertOptionalStringField(source, 'provider', label)
  assertOptionalStringField(source, 'source', label)
  assertOptionalStringField(source, 'apiName', label)
  assertOptionalStringField(source, 'status', label)
  assertOptionalStringField(source, 'dataMode', label)
  assertOptionalStringField(source, 'freshness', label)
  assertOptionalStringField(source, 'tradeDate', label)
  assertOptionalNumberField(source, 'recordCount', label)
  assertOptionalNumberField(source, 'confidence', label)
  assertOptionalStringField(source, 'message', label)
  assertOptionalStringField(source, 'error', label)
}

function assertGlobalMarketConflict(value: unknown, label: string) {
  const conflict = assertRecord(value, label)
  assertOptionalStringField(conflict, 'field', label)
  assertOptionalStringField(conflict, 'severity', label)
  assertOptionalStringField(conflict, 'primarySource', label)
  assertOptionalStringField(conflict, 'otherSource', label)
  assertOptionalStringField(conflict, 'sector', label)
  assertOptionalStringField(conflict, 'message', label)
  assertOptionalScalarConflictValue(conflict, 'primaryValue', label)
  assertOptionalScalarConflictValue(conflict, 'otherValue', label)
  assertOptionalNumberField(conflict, 'absoluteDiff', label)
  assertOptionalNumberField(conflict, 'relativeDiff', label)
  assertOptionalNumberField(conflict, 'tolerance', label)
}

function assertGlobalMarketFundFlowRow(value: unknown, label: string) {
  const row = assertRecord(value, label)
  assertRequiredStringField(row, 'tradeDate', label)
  assertRequiredNumberField(row, 'netAmount', label)
  assertRequiredNumberField(row, 'mainNetAmount', label)
  assertRequiredNumberField(row, 'smallNetAmount', label)
}

function assertGlobalMarketSectorRankRow(value: unknown, label: string) {
  const row = assertRecord(value, label)
  assertOptionalNullableNumberField(row, 'rank', label)
  assertRequiredStringField(row, 'name', label)
  assertOptionalStringField(row, 'code', label)
  assertOptionalNullableNumberField(row, 'latest', label)
  assertOptionalNullableNumberField(row, 'change', label)
  assertOptionalNullableNumberField(row, 'pctChange', label)
  assertOptionalNullableNumberField(row, 'marketCap', label)
  assertOptionalNullableNumberField(row, 'turnoverRate', label)
  assertOptionalNullableNumberField(row, 'risingCount', label)
  assertOptionalNullableNumberField(row, 'fallingCount', label)
  assertOptionalStringField(row, 'leadingStock', label)
  assertOptionalNullableNumberField(row, 'leadingStockPctChange', label)
}

function assertGlobalMarketArbitration(value: unknown, label: string) {
  const arbitration = assertRecord(value, label)
  assertOptionalStringField(arbitration, 'capability', label)
  assertOptionalStringField(arbitration, 'selectedSource', label)
  assertOptionalStringField(arbitration, 'sourceConsensus', label)
  assertOptionalStringField(arbitration, 'resolution', label)
  assertOptionalStringField(arbitration, 'generatedAt', label)
  assertOptionalArrayField(arbitration, 'checkedSources', label)
  assertOptionalArrayField(arbitration, 'conflicts', label)
  if (Array.isArray(arbitration.checkedSources)) {
    arbitration.checkedSources.forEach((source, index) => {
      assertGlobalMarketSourceChainItem(source, `${label}.checkedSources[${index}]`)
    })
  }
  if (Array.isArray(arbitration.conflicts)) {
    arbitration.conflicts.forEach((conflict, index) => {
      assertGlobalMarketConflict(conflict, `${label}.conflicts[${index}]`)
    })
  }
  if (isRecord(arbitration.dataQuality)) {
    assertOptionalNumberField(arbitration.dataQuality, 'score', `${label}.dataQuality`)
    assertOptionalStringField(arbitration.dataQuality, 'level', `${label}.dataQuality`)
    assertOptionalBooleanField(arbitration.dataQuality, 'reviewOnly', `${label}.dataQuality`)
    assertOptionalNumberField(arbitration.dataQuality, 'highConflictCount', `${label}.dataQuality`)
    assertOptionalNumberField(arbitration.dataQuality, 'mediumConflictCount', `${label}.dataQuality`)
  }
}

function assertGlobalMarketOverviewPayload(value: unknown): Partial<GlobalMarketOverview> {
  const payload = assertRecord(value, 'Global market overview response')
  assertOptionalStringField(payload, 'status', 'Global market overview response')
  assertOptionalStringField(payload, 'dataMode', 'Global market overview response')
  assertOptionalStringField(payload, 'provider', 'Global market overview response')
  assertOptionalStringField(payload, 'range', 'Global market overview response')
  assertOptionalStringField(payload, 'fetchedAt', 'Global market overview response')
  assertOptionalStringField(payload, 'message', 'Global market overview response')
  assertOptionalStringField(payload, 'error', 'Global market overview response')
  assertOptionalNumberField(payload, 'refreshIntervalSeconds', 'Global market overview response')
  assertOptionalArrayField(payload, 'indices', 'Global market overview response')
  assertArrayItemsObject(payload.indices, 'Global market overview response.indices')
  assertOptionalObjectField(payload, 'fundFlow', 'Global market overview response')
  assertOptionalObjectField(payload, 'sectorRank', 'Global market overview response')
  assertOptionalObjectField(payload, 'temperature', 'Global market overview response')

  if (Array.isArray(payload.indices)) {
    payload.indices.forEach((index, offset) => {
      const indexRecord = assertRecord(index, `Global market overview response.indices[${offset}]`)
      assertOptionalArrayField(indexRecord, 'rows', `Global market overview response.indices[${offset}]`)
      assertOptionalArrayField(indexRecord, 'sourceChain', `Global market overview response.indices[${offset}]`)
      assertOptionalArrayField(indexRecord, 'conflicts', `Global market overview response.indices[${offset}]`)
      if (indexRecord.latest !== undefined && indexRecord.latest !== null && !isRecord(indexRecord.latest)) {
        throw new Error(`Global market overview response.indices[${offset}].latest must be an object or null`)
      }
      assertOptionalObjectField(indexRecord, 'arbitration', `Global market overview response.indices[${offset}]`)
      if (isRecord(indexRecord.latest) && Object.keys(indexRecord.latest).length > 0) {
        assertGlobalMarketKlineRow(indexRecord.latest, `Global market overview response.indices[${offset}].latest`)
      }
      if (Array.isArray(indexRecord.rows)) {
        indexRecord.rows.forEach((row, rowOffset) => {
          assertGlobalMarketKlineRow(row, `Global market overview response.indices[${offset}].rows[${rowOffset}]`)
        })
      }
      if (Array.isArray(indexRecord.sourceChain)) {
        indexRecord.sourceChain.forEach((source, sourceOffset) => {
          assertGlobalMarketSourceChainItem(source, `Global market overview response.indices[${offset}].sourceChain[${sourceOffset}]`)
        })
      }
      if (isRecord(indexRecord.arbitration)) {
        assertGlobalMarketArbitration(indexRecord.arbitration, `Global market overview response.indices[${offset}].arbitration`)
      }
      if (Array.isArray(indexRecord.conflicts)) {
        indexRecord.conflicts.forEach((conflict, conflictOffset) => {
          assertGlobalMarketConflict(conflict, `Global market overview response.indices[${offset}].conflicts[${conflictOffset}]`)
        })
      }
    })
  }

  if (isRecord(payload.fundFlow)) {
    assertOptionalArrayField(payload.fundFlow, 'rows', 'Global market overview response.fundFlow')
    assertOptionalArrayField(payload.fundFlow, 'sourceChain', 'Global market overview response.fundFlow')
    assertOptionalArrayField(payload.fundFlow, 'conflicts', 'Global market overview response.fundFlow')
    assertOptionalObjectField(payload.fundFlow, 'arbitration', 'Global market overview response.fundFlow')
    if (Array.isArray(payload.fundFlow.rows)) {
      payload.fundFlow.rows.forEach((row, offset) => {
        assertGlobalMarketFundFlowRow(row, `Global market overview response.fundFlow.rows[${offset}]`)
      })
    }
    if (Array.isArray(payload.fundFlow.sourceChain)) {
      payload.fundFlow.sourceChain.forEach((source, offset) => {
        assertGlobalMarketSourceChainItem(source, `Global market overview response.fundFlow.sourceChain[${offset}]`)
      })
    }
    if (isRecord(payload.fundFlow.arbitration)) {
      assertGlobalMarketArbitration(payload.fundFlow.arbitration, 'Global market overview response.fundFlow.arbitration')
    }
    if (Array.isArray(payload.fundFlow.conflicts)) {
      payload.fundFlow.conflicts.forEach((conflict, offset) => {
        assertGlobalMarketConflict(conflict, `Global market overview response.fundFlow.conflicts[${offset}]`)
      })
    }
  }

  if (isRecord(payload.sectorRank)) {
    assertOptionalArrayField(payload.sectorRank, 'rows', 'Global market overview response.sectorRank')
    assertOptionalArrayField(payload.sectorRank, 'top', 'Global market overview response.sectorRank')
    assertOptionalArrayField(payload.sectorRank, 'bottom', 'Global market overview response.sectorRank')
    assertOptionalArrayField(payload.sectorRank, 'candidateSources', 'Global market overview response.sectorRank')
    assertOptionalObjectField(payload.sectorRank, 'sourceCount', 'Global market overview response.sectorRank')
    assertOptionalObjectField(payload.sectorRank, 'arbitration', 'Global market overview response.sectorRank')
    if (Array.isArray(payload.sectorRank.rows)) {
      payload.sectorRank.rows.forEach((row, offset) => {
        assertGlobalMarketSectorRankRow(row, `Global market overview response.sectorRank.rows[${offset}]`)
      })
    }
    if (Array.isArray(payload.sectorRank.top)) {
      payload.sectorRank.top.forEach((row, offset) => {
        assertGlobalMarketSectorRankRow(row, `Global market overview response.sectorRank.top[${offset}]`)
      })
    }
    if (Array.isArray(payload.sectorRank.bottom)) {
      payload.sectorRank.bottom.forEach((row, offset) => {
        assertGlobalMarketSectorRankRow(row, `Global market overview response.sectorRank.bottom[${offset}]`)
      })
    }
    if (Array.isArray(payload.sectorRank.candidateSources)) {
      payload.sectorRank.candidateSources.forEach((source, offset) => {
        assertGlobalMarketSourceChainItem(source, `Global market overview response.sectorRank.candidateSources[${offset}]`)
      })
    }
    if (isRecord(payload.sectorRank.arbitration)) {
      assertGlobalMarketArbitration(payload.sectorRank.arbitration, 'Global market overview response.sectorRank.arbitration')
    }
  }

  if (isRecord(payload.temperature)) {
    assertOptionalNumberField(payload.temperature, 'score', 'Global market overview response.temperature')
    assertOptionalStringField(payload.temperature, 'label', 'Global market overview response.temperature')
    assertOptionalStringField(payload.temperature, 'status', 'Global market overview response.temperature')
    assertOptionalNumberField(payload.temperature, 'trendScore', 'Global market overview response.temperature')
    assertOptionalNumberField(payload.temperature, 'breadthScore', 'Global market overview response.temperature')
    assertOptionalNumberField(payload.temperature, 'flowScore', 'Global market overview response.temperature')
    assertOptionalNumberField(payload.temperature, 'risingCount', 'Global market overview response.temperature')
    assertOptionalNumberField(payload.temperature, 'fallingCount', 'Global market overview response.temperature')
    assertOptionalBooleanField(payload.temperature, 'reviewOnly', 'Global market overview response.temperature')
    assertOptionalArrayField(payload.temperature, 'reasons', 'Global market overview response.temperature')
    assertArrayItemsString(payload.temperature.reasons, 'Global market overview response.temperature.reasons')
  }

  return payload as Partial<GlobalMarketOverview>
}

function asArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? value as T[] : []
}

function normalizeDataMode(value?: string): GlobalMarketDataMode {
  if (value === 'LIVE' || value === 'FALLBACK' || value === 'STALE') return value
  return 'UNAVAILABLE'
}

function normalizeFreshness(value?: string): GlobalMarketFreshness {
  if (value === 'REALTIME' || value === 'POST_CLOSE_PENDING_EOD' || value === 'EOD' || value === 'STALE') return value
  return 'UNKNOWN'
}

function normalizeConsensus(value?: string): GlobalMarketSourceConsensus {
  if (value === 'SINGLE_SOURCE' || value === 'CONSENSUS' || value === 'DIVERGED') return value
  return 'NO_DATA'
}

function normalizeSourceChain(value?: unknown): GlobalMarketSourceChainItem[] {
  return asArray<Partial<GlobalMarketSourceChainItem>>(value).map((source) => ({
    sourceId: source.sourceId || '',
    provider: source.provider || '',
    source: source.source || '',
    apiName: source.apiName || '',
    status: source.status === 'READY' ? 'READY' : 'FAILED',
    dataMode: normalizeDataMode(source.dataMode),
    freshness: normalizeFreshness(source.freshness),
    tradeDate: source.tradeDate || '',
    recordCount: typeof source.recordCount === 'number' ? source.recordCount : 0,
    confidence: typeof source.confidence === 'number' ? source.confidence : 0,
    message: source.message || '',
    error: source.error || '',
  }))
}

function normalizeConflicts(value?: unknown): GlobalMarketSourceConflict[] {
  return asArray<GlobalMarketSourceConflict>(value)
}

function normalizeArbitration(value?: Partial<GlobalMarketArbitration>): GlobalMarketArbitration | undefined {
  if (!value) return undefined
  return {
    capability: value.capability || '',
    selectedSource: value.selectedSource || '',
    sourceConsensus: normalizeConsensus(value.sourceConsensus),
    resolution: value.resolution || '',
    checkedSources: normalizeSourceChain(value.checkedSources),
    conflicts: normalizeConflicts(value.conflicts),
    dataQuality: {
      score: typeof value.dataQuality?.score === 'number' ? value.dataQuality.score : 0,
      level: value.dataQuality?.level || 'LOW',
      reviewOnly: Boolean(value.dataQuality?.reviewOnly),
      highConflictCount: typeof value.dataQuality?.highConflictCount === 'number' ? value.dataQuality.highConflictCount : 0,
      mediumConflictCount: typeof value.dataQuality?.mediumConflictCount === 'number' ? value.dataQuality.mediumConflictCount : 0,
    },
    generatedAt: value.generatedAt || '',
  }
}

function normalizeIndex(index: Partial<GlobalMarketIndex>): GlobalMarketIndex {
  const rawDailyRenderMode = String(index.dailyRenderMode || '')
  const rows = asArray<GlobalMarketKlineRow>(index.rows)
  const arbitration = normalizeArbitration(index.arbitration)
  const conflicts = normalizeConflicts(index.conflicts ?? arbitration?.conflicts)
  const dailyRenderMode = rawDailyRenderMode === 'TUSHARE_EOD' || rawDailyRenderMode === 'TUSHARE_STALE'
    ? rawDailyRenderMode
    : 'UNAVAILABLE'
  return {
    key: index.key || '',
    symbol: index.symbol || '',
    name: index.name || index.symbol || index.key || 'Unknown',
    exchange: index.exchange || '',
    apiName: index.apiName || '',
    status: index.status === 'READY' ? 'READY' : 'FAILED',
    dataMode: normalizeDataMode(index.dataMode),
    selectedProvider: index.selectedProvider || '',
    selectedSource: index.selectedSource || '',
    fallbackUsed: Boolean(index.fallbackUsed),
    freshness: normalizeFreshness(index.freshness),
    sourceConsensus: normalizeConsensus(index.sourceConsensus ?? arbitration?.sourceConsensus),
    reviewOnly: Boolean(index.reviewOnly || arbitration?.dataQuality?.reviewOnly),
    range: '4m',
    recordCount: typeof index.recordCount === 'number' ? index.recordCount : rows.length,
    lastTradeDate: index.lastTradeDate,
    latestQuoteTime: index.latestQuoteTime,
    latest: hasRequiredKlineFields(index.latest) ? index.latest : undefined,
    rows,
    dailyRenderMode,
    dailyRenderMessage: index.dailyRenderMessage || '',
    sourceChain: normalizeSourceChain(index.sourceChain),
    arbitration,
    conflicts,
    message: index.message || '',
    error: index.error || '',
  }
}

function normalizeFundFlow(fundFlow?: Partial<GlobalMarketFundFlow>): GlobalMarketFundFlow {
  const arbitration = normalizeArbitration(fundFlow?.arbitration)
  const conflicts = normalizeConflicts(fundFlow?.conflicts ?? arbitration?.conflicts)
  return {
    status: fundFlow?.status === 'READY' ? 'READY' : 'FAILED',
    dataMode: normalizeDataMode(fundFlow?.dataMode),
    provider: fundFlow?.provider || '',
    apiName: fundFlow?.apiName || '',
    selectedProvider: fundFlow?.selectedProvider || '',
    selectedSource: fundFlow?.selectedSource || '',
    fallbackUsed: Boolean(fundFlow?.fallbackUsed),
    freshness: normalizeFreshness(fundFlow?.freshness),
    sourceConsensus: normalizeConsensus(fundFlow?.sourceConsensus ?? arbitration?.sourceConsensus),
    reviewOnly: Boolean(fundFlow?.reviewOnly || arbitration?.dataQuality?.reviewOnly),
    latestDate: fundFlow?.latestDate || '',
    netAmount: fundFlow?.netAmount ?? null,
    mainNetAmount: fundFlow?.mainNetAmount ?? null,
    smallNetAmount: fundFlow?.smallNetAmount ?? null,
    unit: fundFlow?.unit || 'yuan',
    rows: asArray<GlobalMarketFundFlowRow>(fundFlow?.rows),
    sourceChain: normalizeSourceChain(fundFlow?.sourceChain),
    arbitration,
    conflicts,
    message: fundFlow?.message || '',
    error: fundFlow?.error || '',
  }
}

function normalizeSectorRank(sectorRank?: Partial<GlobalMarketSectorRank>): GlobalMarketSectorRank {
  const rows = asArray<GlobalMarketSectorRankRow>(sectorRank?.rows)
  return {
    status: sectorRank?.status === 'READY' ? 'READY' : 'FAILED',
    dataMode: normalizeDataMode(sectorRank?.dataMode),
    provider: sectorRank?.provider || '',
    source: sectorRank?.source || '',
    apiName: sectorRank?.apiName || '',
    boardType: 'industry',
    tradeDate: sectorRank?.tradeDate || '',
    fetchedAt: sectorRank?.fetchedAt || '',
    recordCount: typeof sectorRank?.recordCount === 'number' ? sectorRank.recordCount : rows.length,
    selectedProvider: sectorRank?.selectedProvider,
    selectedSource: sectorRank?.selectedSource,
    sourceCount: sectorRank?.sourceCount,
    candidateSources: asArray<GlobalMarketSectorRankCandidate>(sectorRank?.candidateSources),
    arbitration: sectorRank?.arbitration,
    top: asArray<GlobalMarketSectorRankRow>(sectorRank?.top),
    bottom: asArray<GlobalMarketSectorRankRow>(sectorRank?.bottom),
    rows,
    message: sectorRank?.message || '',
    error: sectorRank?.error || '',
  }
}

function normalizeTemperature(temperature?: Partial<GlobalMarketTemperature>): GlobalMarketTemperature {
  return {
    score: typeof temperature?.score === 'number' ? temperature.score : 0,
    label: temperature?.label || '数据不足',
    status: temperature?.status || 'WARN',
    trendScore: typeof temperature?.trendScore === 'number' ? temperature.trendScore : 0,
    breadthScore: typeof temperature?.breadthScore === 'number' ? temperature.breadthScore : 0,
    flowScore: typeof temperature?.flowScore === 'number' ? temperature.flowScore : 0,
    risingCount: typeof temperature?.risingCount === 'number' ? temperature.risingCount : 0,
    fallingCount: typeof temperature?.fallingCount === 'number' ? temperature.fallingCount : 0,
    reasons: asArray<string>(temperature?.reasons),
    reviewOnly: Boolean(temperature?.reviewOnly),
  }
}

function normalizeGlobalMarketOverview(payload: Partial<GlobalMarketOverview>): GlobalMarketOverview {
  return {
    status: payload.status === 'READY' || payload.status === 'PARTIAL' ? payload.status : 'FAILED',
    dataMode: normalizeDataMode(payload.dataMode),
    provider: payload.provider || '',
    range: '4m',
    fetchedAt: payload.fetchedAt || '',
    refreshIntervalSeconds: typeof payload.refreshIntervalSeconds === 'number' ? payload.refreshIntervalSeconds : 300,
    indices: asArray<Partial<GlobalMarketIndex>>(payload.indices).map(normalizeIndex),
    fundFlow: normalizeFundFlow(payload.fundFlow),
    sectorRank: normalizeSectorRank(payload.sectorRank),
    temperature: normalizeTemperature(payload.temperature),
    message: payload.message || '',
    error: payload.error || '',
  }
}
