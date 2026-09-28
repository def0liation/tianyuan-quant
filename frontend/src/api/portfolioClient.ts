import { request } from './httpClient'

export interface HoldingPosition {
  symbol: string
  name: string
  shares: number
  availableShares: number
  costPrice: number
  marketValue: number
  pnl: number
  industry: string
  style: string
  theme: string
  riskFactor: string
  weight: number
  updatedAt: string
}

export interface HoldingValidationIssue {
  rowNumber: number
  symbol: string
  field: string
  level: string
  message: string
}

export interface PortfolioSnapshotSummary {
  snapshotId: string
  sourceType: string
  sourceName: string
  accountName: string
  totalAssets: number
  stockMarketValue: number
  cash: number
  totalPositionRatio: number
  maxSinglePositionRatio: number
  positionCount: number
  qualityStatus: string
  issueCount: number
  brokerTemplateId: string
  brokerTemplateLabel: string
  templateConfidence: number
  templateWarnings: string[]
  evidenceUsage: 'supporting_only' | (string & {})
  evidenceStrength: 'MEDIUM' | 'LOW' | 'MISSING' | 'PENDING' | (string & {})
  simulationOnly: boolean
  isRealTrade: boolean
  strongConclusionAllowed: boolean
  importedAt: string
  updatedAt: string
}

export interface PortfolioSnapshot extends PortfolioSnapshotSummary {
  availableCash: number
  positions: HoldingPosition[]
  issues: HoldingValidationIssue[]
}

export interface ManualPortfolioPayload {
  sourceName: string
  accountName?: string
  totalAssets?: number
  cash?: number
  availableCash?: number
  positions: Array<Partial<HoldingPosition> & Pick<HoldingPosition, 'symbol'>>
}

export interface HoldingImportResponse {
  jobId: string
  status: string
  message: string
  snapshot: PortfolioSnapshot
}

export interface HoldingImportJob {
  jobId: string
  snapshotId?: string | null
  filename: string
  sourceType: string
  status: string
  rowsTotal: number
  rowsImported: number
  issueCount: number
  brokerTemplateId: string
  brokerTemplateLabel: string
  templateConfidence: number
  templateWarnings: string[]
  message: string
  importError?: Record<string, unknown> | null
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

function assertStringArray(value: unknown, label: string) {
  ensureArray(value, label).forEach((item) => {
    if (typeof item !== 'string') {
      throw new Error(`Unexpected ${label} response`)
    }
  })
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

function assertPortfolioSnapshotBoundary(snapshot: Record<string, unknown>, label: string) {
  requireString(snapshot, 'evidenceUsage', label)
  requireString(snapshot, 'evidenceStrength', label)
  requireBoolean(snapshot, 'simulationOnly', label)
  requireBoolean(snapshot, 'isRealTrade', label)
  requireBoolean(snapshot, 'strongConclusionAllowed', label)

  const evidenceUsage = String(snapshot.evidenceUsage)
  if (
    snapshot.strongConclusionAllowed === true
    || isStrongEvidenceValue(snapshot.evidenceStrength)
    || isStrongEvidenceValue(evidenceUsage)
  ) {
    throw new Error(`Unexpected ${label} response: portfolio evidence must not become a strong conclusion`)
  }
  if (evidenceUsage !== 'supporting_only' || snapshot.simulationOnly !== true || snapshot.isRealTrade !== false) {
    throw new Error(`Unexpected ${label} response: portfolio snapshots must stay simulation-only supporting evidence`)
  }
}

function assertHoldingPosition(value: unknown): HoldingPosition {
  const position = ensureRecord(value, 'holding position')
  requireText(position, 'symbol', 'holding position')
  requireString(position, 'name', 'holding position')
  requireNumber(position, 'shares', 'holding position')
  requireNumber(position, 'availableShares', 'holding position')
  requireNumber(position, 'costPrice', 'holding position')
  requireNumber(position, 'marketValue', 'holding position')
  requireNumber(position, 'pnl', 'holding position')
  requireString(position, 'industry', 'holding position')
  requireString(position, 'style', 'holding position')
  requireString(position, 'theme', 'holding position')
  requireString(position, 'riskFactor', 'holding position')
  requireNumber(position, 'weight', 'holding position')
  requireString(position, 'updatedAt', 'holding position')
  return value as HoldingPosition
}

function assertHoldingValidationIssue(value: unknown): HoldingValidationIssue {
  const issue = ensureRecord(value, 'holding validation issue')
  requireNumber(issue, 'rowNumber', 'holding validation issue')
  requireString(issue, 'symbol', 'holding validation issue')
  requireString(issue, 'field', 'holding validation issue')
  requireString(issue, 'level', 'holding validation issue')
  requireString(issue, 'message', 'holding validation issue')
  return value as HoldingValidationIssue
}

function assertPortfolioSnapshotSummary(value: unknown): PortfolioSnapshotSummary {
  const snapshot = ensureRecord(value, 'portfolio snapshot summary')
  requireText(snapshot, 'snapshotId', 'portfolio snapshot summary')
  requireString(snapshot, 'sourceType', 'portfolio snapshot summary')
  requireString(snapshot, 'sourceName', 'portfolio snapshot summary')
  requireString(snapshot, 'accountName', 'portfolio snapshot summary')
  requireNumber(snapshot, 'totalAssets', 'portfolio snapshot summary')
  requireNumber(snapshot, 'stockMarketValue', 'portfolio snapshot summary')
  requireNumber(snapshot, 'cash', 'portfolio snapshot summary')
  requireNumber(snapshot, 'totalPositionRatio', 'portfolio snapshot summary')
  requireNumber(snapshot, 'maxSinglePositionRatio', 'portfolio snapshot summary')
  requireNumber(snapshot, 'positionCount', 'portfolio snapshot summary')
  requireString(snapshot, 'qualityStatus', 'portfolio snapshot summary')
  requireNumber(snapshot, 'issueCount', 'portfolio snapshot summary')
  requireString(snapshot, 'brokerTemplateId', 'portfolio snapshot summary')
  requireString(snapshot, 'brokerTemplateLabel', 'portfolio snapshot summary')
  requireNumber(snapshot, 'templateConfidence', 'portfolio snapshot summary')
  assertStringArray(snapshot.templateWarnings, 'portfolio snapshot templateWarnings')
  assertPortfolioSnapshotBoundary(snapshot, 'portfolio snapshot summary')
  requireString(snapshot, 'importedAt', 'portfolio snapshot summary')
  requireString(snapshot, 'updatedAt', 'portfolio snapshot summary')
  return value as PortfolioSnapshotSummary
}

function assertPortfolioSnapshot(value: unknown): PortfolioSnapshot {
  const snapshot = ensureRecord(value, 'portfolio snapshot')
  assertPortfolioSnapshotSummary(snapshot)
  requireNumber(snapshot, 'availableCash', 'portfolio snapshot')
  ensureArray(snapshot.positions, 'portfolio snapshot positions').forEach(assertHoldingPosition)
  ensureArray(snapshot.issues, 'portfolio snapshot issues').forEach(assertHoldingValidationIssue)
  return value as PortfolioSnapshot
}

function assertHoldingImportResponse(value: unknown): HoldingImportResponse {
  const result = ensureRecord(value, 'portfolio import response')
  requireText(result, 'jobId', 'portfolio import response')
  requireString(result, 'status', 'portfolio import response')
  requireString(result, 'message', 'portfolio import response')
  assertPortfolioSnapshot(result.snapshot)
  return value as HoldingImportResponse
}

function assertHoldingImportJob(value: unknown): HoldingImportJob {
  const job = ensureRecord(value, 'portfolio import job')
  requireText(job, 'jobId', 'portfolio import job')
  assertOptionalString(job, 'snapshotId', 'portfolio import job')
  requireString(job, 'filename', 'portfolio import job')
  requireString(job, 'sourceType', 'portfolio import job')
  requireString(job, 'status', 'portfolio import job')
  requireNumber(job, 'rowsTotal', 'portfolio import job')
  requireNumber(job, 'rowsImported', 'portfolio import job')
  requireNumber(job, 'issueCount', 'portfolio import job')
  requireString(job, 'brokerTemplateId', 'portfolio import job')
  requireString(job, 'brokerTemplateLabel', 'portfolio import job')
  requireNumber(job, 'templateConfidence', 'portfolio import job')
  assertStringArray(job.templateWarnings, 'portfolio import job templateWarnings')
  requireString(job, 'message', 'portfolio import job')
  if (job.importError !== undefined && job.importError !== null) {
    ensureRecord(job.importError, 'portfolio import job importError')
  }
  requireString(job, 'createdAt', 'portfolio import job')
  return value as HoldingImportJob
}

function assertDeletePortfolioSnapshotResult(value: unknown): { deleted: string } {
  const result = ensureRecord(value, 'portfolio snapshot delete')
  requireText(result, 'deleted', 'portfolio snapshot delete')
  return value as { deleted: string }
}

export function listPortfolioSnapshots() {
  return request<unknown>('/portfolio/snapshots').then((items) => (
    ensureArray(items, 'portfolio snapshot list').map(assertPortfolioSnapshotSummary)
  ))
}

export function getPortfolioSnapshot(snapshotId: string) {
  return request<unknown>(`/portfolio/snapshots/${snapshotId}`).then(assertPortfolioSnapshot)
}

export function deletePortfolioSnapshot(snapshotId: string) {
  return request<unknown>(`/portfolio/snapshots/${snapshotId}`, {
    method: 'DELETE',
  }).then(assertDeletePortfolioSnapshotResult)
}

export function createManualPortfolioSnapshot(payload: ManualPortfolioPayload) {
  return request<unknown>('/portfolio/manual', {
    method: 'POST',
    body: JSON.stringify(payload),
  }).then(assertPortfolioSnapshot)
}

export function getPortfolioImportJob(jobId: string) {
  return request<unknown>(`/portfolio/imports/${jobId}`).then(assertHoldingImportJob)
}

export async function importPortfolioSnapshot(
  file: File,
  sourceName = 'uploaded-file',
  accountName = '',
  options: { cash?: number; availableCash?: number; totalAssets?: number } = {},
) {
  const form = new FormData()
  form.append('file', file)
  form.append('source_name', sourceName)
  form.append('account_name', accountName)
  form.append('cash', String(options.cash ?? 0))
  form.append('available_cash', String(options.availableCash ?? 0))
  form.append('total_assets', String(options.totalAssets ?? 0))
  return request<unknown>('/portfolio/imports', {
    method: 'POST',
    body: form,
  }).then(assertHoldingImportResponse)
}
