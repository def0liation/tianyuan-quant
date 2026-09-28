import { request } from './httpClient'

export type KlinePeriod = 'daily' | 'weekly' | 'monthly'
export type KlineRange = '3m' | '6m' | '2y'

export interface KlineRow {
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
}

export interface KlineResponse {
  symbol: string
  period: KlinePeriod
  range: KlineRange
  apiName: string
  provider: string
  status: 'READY' | 'FAILED'
  dataMode: 'LIVE' | 'UNAVAILABLE'
  fetchedAt: string
  recordCount: number
  lastTradeDate?: string
  rows: KlineRow[]
  message: string
  error: string
}

const RANGE_BY_PERIOD: Record<KlinePeriod, KlineRange> = {
  daily: '3m',
  weekly: '6m',
  monthly: '2y',
}

export function getKline(symbol: string, period: KlinePeriod) {
  const params = new URLSearchParams({ symbol, period, range: RANGE_BY_PERIOD[period] })
  return request<unknown>(`/market-data/kline?${params.toString()}`).then(assertKlineResponse)
}

function ensureRecord(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(`Unexpected ${label} response`)
  }
  return value as Record<string, unknown>
}

function ensureArray(value: unknown, label: string): unknown[] {
  if (!Array.isArray(value)) {
    throw new Error(`Unexpected ${label} response`)
  }
  return value
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

function assertOptionalNumber(record: Record<string, unknown>, key: string, label: string) {
  const value = record[key]
  if (value !== undefined && value !== null && (typeof value !== 'number' || Number.isNaN(value))) {
    throw new Error(`Unexpected ${label} response: invalid ${key}`)
  }
}

function assertOptionalString(record: Record<string, unknown>, key: string, label: string) {
  const value = record[key]
  if (value !== undefined && value !== null && typeof value !== 'string') {
    throw new Error(`Unexpected ${label} response: invalid ${key}`)
  }
}

function assertKlinePeriod(value: unknown) {
  if (value !== 'daily' && value !== 'weekly' && value !== 'monthly') {
    throw new Error('Unexpected K-line response: invalid period')
  }
}

function assertKlineRange(value: unknown) {
  if (value !== '3m' && value !== '6m' && value !== '2y') {
    throw new Error('Unexpected K-line response: invalid range')
  }
}

function assertKlineRow(value: unknown): KlineRow {
  const row = ensureRecord(value, 'K-line row')
  requireString(row, 'tradeDate', 'K-line row')
  requireNumber(row, 'open', 'K-line row')
  requireNumber(row, 'high', 'K-line row')
  requireNumber(row, 'low', 'K-line row')
  requireNumber(row, 'close', 'K-line row')
  assertOptionalNumber(row, 'preClose', 'K-line row')
  assertOptionalNumber(row, 'change', 'K-line row')
  assertOptionalNumber(row, 'pctChange', 'K-line row')
  assertOptionalNumber(row, 'volume', 'K-line row')
  assertOptionalNumber(row, 'amount', 'K-line row')
  return value as KlineRow
}

function assertKlineResponse(value: unknown): KlineResponse {
  const response = ensureRecord(value, 'K-line')
  requireString(response, 'symbol', 'K-line')
  assertKlinePeriod(response.period)
  assertKlineRange(response.range)
  requireString(response, 'apiName', 'K-line')
  requireString(response, 'provider', 'K-line')
  if (response.status !== 'READY' && response.status !== 'FAILED') {
    throw new Error('Unexpected K-line response: invalid status')
  }
  if (response.dataMode !== 'LIVE' && response.dataMode !== 'UNAVAILABLE') {
    throw new Error('Unexpected K-line response: invalid dataMode')
  }
  requireString(response, 'fetchedAt', 'K-line')
  requireNumber(response, 'recordCount', 'K-line')
  assertOptionalString(response, 'lastTradeDate', 'K-line')
  ensureArray(response.rows, 'K-line rows').forEach(assertKlineRow)
  requireString(response, 'message', 'K-line')
  requireString(response, 'error', 'K-line')
  return value as KlineResponse
}
