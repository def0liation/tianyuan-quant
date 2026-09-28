import { request } from './httpClient'
import type {
  BacktestExperimentPackageResponse,
  BacktestParameterScanHistoryItem,
  BacktestParameterScanJob,
  BacktestParameterScanJobHandoff,
  BacktestRequest,
  BacktestParameterScanRequest,
  BacktestParameterScanResponse,
  BacktestRunItem,
  BacktestTradeItem,
  BacktestSignalItem,
  BacktestSummary,
  SignalOpsExperimentRequest,
  SignalOpsExperimentResponse,
  SignalOpsRandomValidationJob,
  SignalOpsRandomValidationRequest,
} from '../types'

const BACKTEST_API_BASE = '/research/backtest'

type BacktestReadOptions = {
  signal?: AbortSignal
}

export interface SignalOpsBacktestSampleRequest {
  symbol?: string
  signal_id?: string
  source_run_id?: string
  start_date?: string
  end_date?: string
  signal_date?: string
  initial_capital?: number
  data_source?: string
  reuse_existing?: boolean
  force_new?: boolean
}

export interface SignalOpsBacktestSampleResponse {
  run_id: string
  signal_source: string
  market_data_source: string
  sample_window: Record<string, any>
  evidence_strength: Record<string, any>
  limitations: string[]
  run: BacktestRunItem
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

function ensureArray<T = unknown>(value: unknown, label: string): T[] {
  if (!Array.isArray(value)) {
    throw new Error(`Unexpected ${label} response`)
  }
  return value as T[]
}

function assertStringArray(value: unknown, label: string) {
  ensureArray(value, label).forEach((item) => {
    if (typeof item !== 'string') {
      throw new Error(`Unexpected ${label} response`)
    }
  })
}

function requireFiniteNumber(record: Record<string, unknown>, key: string, label: string) {
  if (typeof record[key] !== 'number' || !Number.isFinite(record[key])) {
    throw new Error(`Unexpected ${label} response`)
  }
}

function assertSnakeSimulationBoundary(value: unknown, label: string, required = true) {
  const record = ensureRecord(value, label)
  if (required && (record.simulation_only !== true || record.is_real_trade !== false)) {
    throw new Error(`${label} broke Backtest simulation-only boundary`)
  }
  if (!required && (record.simulation_only === false || record.is_real_trade === true)) {
    throw new Error(`${label} broke Backtest simulation-only boundary`)
  }
}

function assertCamelSimulationBoundary(value: unknown, label: string, required = true) {
  const record = ensureRecord(value, label)
  if (required && (record.simulationOnly !== true || record.isRealTrade !== false)) {
    throw new Error(`${label} broke Backtest simulation-only boundary`)
  }
  if (!required && (record.simulationOnly === false || record.isRealTrade === true)) {
    throw new Error(`${label} broke Backtest simulation-only boundary`)
  }
}

function isStrongBacktestEvidenceValue(value: unknown) {
  const normalized = String(value || '').trim().toUpperCase()
  return normalized === 'HIGH'
    || normalized === 'RESEARCH_GRADE'
    || normalized === 'PRIMARY_EVIDENCE_READY'
    || normalized.includes('STRONG')
    || normalized.includes('PRIMARY')
}

function assertBacktestEvidenceBoundary(
  evidenceInput: unknown,
  researchGradeInput: unknown,
  label: string,
) {
  const evidence = asRecord(evidenceInput)
  const researchGrade = asRecord(researchGradeInput)
  if (Object.keys(evidence).length === 0 && Object.keys(researchGrade).length === 0) return

  const researchUsage = String(
    evidence.researchUsage
      || evidence.research_usage
      || researchGrade.researchUsage
      || researchGrade.research_usage
      || '',
  ).toLowerCase()
  const researchBand = String(
    researchGrade.band
      || evidence.researchGradeBand
      || evidence.research_grade_band
      || '',
  ).toUpperCase()
  const supportingOnly = Boolean(
    evidence.weakSample === true
    || evidence.weak_sample === true
    || researchGrade.supportingOnly === true
    || researchGrade.supporting_only === true
    || researchUsage === 'supporting_only'
    || researchBand === 'SUPPORTING_ONLY',
  )

  if (researchUsage === 'primary_evidence') {
    throw new Error(`${label} evidence must not become primary_evidence`)
  }
  if (
    supportingOnly
    && (
      evidence.canSupportResearchVerdict === true
      || evidence.can_support_research_verdict === true
      || isStrongBacktestEvidenceValue(evidence.grade)
      || isStrongBacktestEvidenceValue(researchBand)
    )
  ) {
    throw new Error(`${label} supporting-only evidence must not become a strong conclusion`)
  }
}

function assertBacktestReportBoundary(value: unknown, label: string) {
  const report = asRecord(value)
  if (Object.keys(report).length === 0) return

  const reportLabel = `${label} report`
  const reportProvenanceLabel = `${label} report provenance`
  const provenance = asRecord(report.provenance)
  if (Object.keys(provenance).length > 0) {
    assertCamelSimulationBoundary(provenance, reportProvenanceLabel, false)
  }

  assertBacktestEvidenceBoundary(report.evidenceStrength, report.researchGradeScore, reportLabel)
  if (report.evidence_strength !== undefined || report.research_grade_score !== undefined) {
    assertBacktestEvidenceBoundary(report.evidence_strength, report.research_grade_score, `${reportLabel} legacy aliases`)
  }
}

function assertBacktestRunItem(value: unknown, label = 'backtest run'): BacktestRunItem {
  const run = ensureRecord(value, label)
  ensureRecord(run.parameters, `${label} parameters`)
  assertSnakeSimulationBoundary(run.parameters, `${label} parameters`, false)
  assertBacktestReportBoundary(run.report, label)
  return value as BacktestRunItem
}

function assertBacktestSignalItem(value: unknown): BacktestSignalItem {
  const signal = ensureRecord(value, 'backtest signal')
  assertSnakeSimulationBoundary(asRecord(signal.metadata_json), 'backtest signal metadata', false)
  return value as BacktestSignalItem
}

function assertBacktestParameterScanResponse(value: unknown): BacktestParameterScanResponse {
  const scan = ensureRecord(value, 'backtest parameter scan')
  assertSnakeSimulationBoundary(scan, 'backtest parameter scan')
  ensureRecord(scan.parameter_grid, 'backtest parameter scan grid')
  ensureArray(scan.combinations, 'backtest parameter scan combinations')
  assertStringArray(scan.run_ids, 'backtest parameter scan run_ids')
  ensureRecord(scan.summary, 'backtest parameter scan summary')
  ensureArray(scan.runs, 'backtest parameter scan runs').forEach((run) => assertBacktestRunItem(run, 'backtest parameter scan run'))
  if (scan.windows !== undefined) {
    ensureArray(scan.windows, 'backtest parameter scan windows')
  }
  return value as BacktestParameterScanResponse
}

function assertBacktestParameterScanHistoryItem(value: unknown): BacktestParameterScanHistoryItem {
  const scan = ensureRecord(value, 'backtest parameter scan history item')
  assertSnakeSimulationBoundary(scan, 'backtest parameter scan history item')
  ensureRecord(scan.parameter_grid, 'backtest parameter scan history grid')
  ensureArray(scan.combinations, 'backtest parameter scan history combinations')
  assertStringArray(scan.run_ids, 'backtest parameter scan history run_ids')
  ensureRecord(scan.summary, 'backtest parameter scan history summary')
  if (scan.windows !== undefined) {
    ensureArray(scan.windows, 'backtest parameter scan history windows')
  }
  return value as BacktestParameterScanHistoryItem
}

function assertBacktestParameterScanJob(value: unknown): BacktestParameterScanJob {
  const job = ensureRecord(value, 'backtest parameter scan job')
  assertCamelSimulationBoundary(job, 'backtest parameter scan job')
  if (job.runIds !== undefined) {
    assertStringArray(job.runIds, 'backtest parameter scan job runIds')
  }
  if (job.scan !== undefined && job.scan !== null) {
    assertBacktestParameterScanResponse(job.scan)
  }
  if (job.attempts !== undefined) {
    ensureArray(job.attempts, 'backtest parameter scan job attempts').forEach((attempt) => {
      assertCamelSimulationBoundary(attempt, 'backtest parameter scan job attempt', false)
    })
  }
  assertCamelSimulationBoundary(asRecord(job.handoffStatus), 'backtest parameter scan job handoff status', false)
  return value as BacktestParameterScanJob
}

function assertBacktestParameterScanJobHandoff(value: unknown): BacktestParameterScanJobHandoff {
  const handoff = ensureRecord(value, 'backtest parameter scan job handoff')
  assertCamelSimulationBoundary(handoff, 'backtest parameter scan job handoff')
  if (handoff.appendOnly !== true) {
    throw new Error('backtest parameter scan job handoff broke append-only boundary')
  }
  ensureRecord(handoff.manifest, 'backtest parameter scan job handoff manifest')
  return value as BacktestParameterScanJobHandoff
}

function assertBacktestExperimentPackage(value: unknown): BacktestExperimentPackageResponse {
  const experimentPackage = ensureRecord(value, 'backtest experiment package')
  assertSnakeSimulationBoundary(experimentPackage, 'backtest experiment package')
  ensureRecord(experimentPackage.manifest, 'backtest experiment package manifest')
  ensureRecord(experimentPackage.hashes, 'backtest experiment package hashes')
  ensureRecord(experimentPackage.reproducibility, 'backtest experiment package reproducibility')
  assertBacktestRunItem(experimentPackage.run, 'backtest experiment package run')
  ensureArray(experimentPackage.trades, 'backtest experiment package trades')
  ensureArray(experimentPackage.signals, 'backtest experiment package signals').forEach(assertBacktestSignalItem)
  return value as BacktestExperimentPackageResponse
}

function assertSignalOpsBacktestSampleResponse(value: unknown): SignalOpsBacktestSampleResponse {
  const sample = ensureRecord(value, 'SignalOps backtest sample')
  assertStringArray(sample.limitations, 'SignalOps backtest sample limitations')
  ensureRecord(sample.sample_window, 'SignalOps backtest sample window')
  const sampleEvidence = ensureRecord(sample.evidence_strength, 'SignalOps backtest sample evidence strength')
  assertBacktestEvidenceBoundary(sampleEvidence, {}, 'SignalOps backtest sample evidence strength')
  assertBacktestRunItem(sample.run, 'SignalOps backtest sample run')
  return value as SignalOpsBacktestSampleResponse
}

function assertSignalOpsExperimentResponse(value: unknown): SignalOpsExperimentResponse {
  const experiment = ensureRecord(value, 'SignalOps backtest experiment')
  assertSnakeSimulationBoundary(experiment, 'SignalOps backtest experiment')
  assertStringArray(experiment.warnings || [], 'SignalOps backtest experiment warnings')
  ensureRecord(experiment.walk_forward_run_ids, 'SignalOps backtest experiment run ids')
  ensureRecord(experiment.walk_forward_validation, 'SignalOps backtest experiment validation')
  ensureRecord(experiment.benchmark_comparison, 'SignalOps backtest experiment benchmark')
  assertSnakeSimulationBoundary(experiment.research_evidence_package, 'SignalOps backtest experiment research evidence', false)
  assertBacktestRunItem(experiment.baseline_run, 'SignalOps backtest experiment baseline run')
  assertBacktestRunItem(experiment.candidate_run, 'SignalOps backtest experiment candidate run')
  return value as SignalOpsExperimentResponse
}

function assertSignalOpsRandomValidationJob(value: unknown): SignalOpsRandomValidationJob {
  const job = ensureRecord(value, 'SignalOps random validation job')
  assertCamelSimulationBoundary(job, 'SignalOps random validation job', false)
  return value as SignalOpsRandomValidationJob
}

function assertBacktestDeleteResult(value: unknown): { deleted: string } {
  const result = ensureRecord(value, 'backtest delete result')
  if (typeof result.deleted !== 'string') {
    throw new Error('Unexpected backtest delete result response')
  }
  return value as { deleted: string }
}

function assertBacktestSummary(value: unknown): BacktestSummary {
  const summary = ensureRecord(value, 'backtest summary')
  requireFiniteNumber(summary, 'total_runs', 'backtest summary')
  requireFiniteNumber(summary, 'completed_runs', 'backtest summary')
  requireFiniteNumber(summary, 'pending_runs', 'backtest summary')
  return value as BacktestSummary
}

export async function createBacktestRun(data: BacktestRequest): Promise<BacktestRunItem> {
  return request<unknown>(`${BACKTEST_API_BASE}/runs`, {
    method: 'POST',
    body: JSON.stringify(data),
  }).then((run) => assertBacktestRunItem(run, 'created backtest run'))
}

export async function createBacktestParameterScan(
  data: BacktestParameterScanRequest,
): Promise<BacktestParameterScanResponse> {
  return request<unknown>(`${BACKTEST_API_BASE}/parameter-scan`, {
    method: 'POST',
    body: JSON.stringify(data),
    timeoutMs: 60000,
  }).then(assertBacktestParameterScanResponse)
}

export async function createBacktestParameterScanJob(
  data: BacktestParameterScanRequest,
): Promise<BacktestParameterScanJob> {
  return request<unknown>(`${BACKTEST_API_BASE}/parameter-scan/jobs`, {
    method: 'POST',
    body: JSON.stringify(data),
    timeoutMs: 30000,
  }).then(assertBacktestParameterScanJob)
}

export async function getBacktestParameterScanJob(jobId: string): Promise<BacktestParameterScanJob> {
  return request<unknown>(`${BACKTEST_API_BASE}/parameter-scan/jobs/${jobId}`, {
    timeoutMs: 30000,
  }).then(assertBacktestParameterScanJob)
}

export async function cancelBacktestParameterScanJob(jobId: string): Promise<BacktestParameterScanJob> {
  return request<unknown>(`${BACKTEST_API_BASE}/parameter-scan/jobs/${jobId}/cancel`, {
    method: 'POST',
    timeoutMs: 30000,
  }).then(assertBacktestParameterScanJob)
}

export async function handoffBacktestParameterScanJob(jobId: string): Promise<BacktestParameterScanJobHandoff> {
  return request<unknown>(`${BACKTEST_API_BASE}/parameter-scan/jobs/${jobId}/handoff`, {
    method: 'POST',
    timeoutMs: 30000,
  }).then(assertBacktestParameterScanJobHandoff)
}

export async function listBacktestParameterScans(params?: {
  symbol?: string
  limit?: number
}, options: BacktestReadOptions = {}): Promise<BacktestParameterScanHistoryItem[]> {
  const qs = new URLSearchParams()
  if (params?.symbol) qs.set('symbol', params.symbol)
  if (params?.limit) qs.set('limit', String(params.limit))
  const path = `${BACKTEST_API_BASE}/parameter-scans${qs.toString() ? '?' + qs.toString() : ''}`
  return request<unknown>(path, { signal: options.signal }).then((items) =>
    ensureArray(items, 'backtest parameter scan history').map(assertBacktestParameterScanHistoryItem),
  )
}

export async function createSignalOpsBacktestSample(
  data: SignalOpsBacktestSampleRequest = {},
): Promise<SignalOpsBacktestSampleResponse> {
  return request<unknown>(`${BACKTEST_API_BASE}/signalops-sample`, {
    method: 'POST',
    body: JSON.stringify(data),
  }).then(assertSignalOpsBacktestSampleResponse)
}

export async function createSignalOpsExperiment(
  data: SignalOpsExperimentRequest,
): Promise<SignalOpsExperimentResponse> {
  return request<unknown>(`${BACKTEST_API_BASE}/signalops-experiment`, {
    method: 'POST',
    body: JSON.stringify(data),
    timeoutMs: 60000,
  }).then(assertSignalOpsExperimentResponse)
}

export async function createSignalOpsRandomValidationJob(
  data: SignalOpsRandomValidationRequest = {},
): Promise<SignalOpsRandomValidationJob> {
  return request<unknown>(`${BACKTEST_API_BASE}/signalops-random-validation/jobs`, {
    method: 'POST',
    body: JSON.stringify(data),
    timeoutMs: 30000,
  }).then(assertSignalOpsRandomValidationJob)
}

export async function getSignalOpsRandomValidationJob(jobId: string): Promise<SignalOpsRandomValidationJob> {
  return request<unknown>(`${BACKTEST_API_BASE}/signalops-random-validation/jobs/${jobId}`, {
    timeoutMs: 30000,
  }).then(assertSignalOpsRandomValidationJob)
}

export async function cancelSignalOpsRandomValidationJob(jobId: string): Promise<SignalOpsRandomValidationJob> {
  return request<unknown>(`${BACKTEST_API_BASE}/signalops-random-validation/jobs/${jobId}/cancel`, {
    method: 'POST',
    timeoutMs: 30000,
  }).then(assertSignalOpsRandomValidationJob)
}

export async function listBacktestRuns(params?: {
  patch_id?: string
  case_id?: string
  symbol?: string
  status?: string
  limit?: number
}, options: BacktestReadOptions = {}): Promise<BacktestRunItem[]> {
  const qs = new URLSearchParams()
  if (params?.patch_id) qs.set('patch_id', params.patch_id)
  if (params?.case_id) qs.set('case_id', params.case_id)
  if (params?.symbol) qs.set('symbol', params.symbol)
  if (params?.status) qs.set('status', params.status)
  if (params?.limit) qs.set('limit', String(params.limit))
  const path = `${BACKTEST_API_BASE}/runs${qs.toString() ? '?' + qs.toString() : ''}`
  return request<unknown>(path, { signal: options.signal }).then((items) =>
    ensureArray(items, 'backtest runs').map((run) => assertBacktestRunItem(run, 'backtest run')),
  )
}

export async function getBacktestRun(runId: string, options: BacktestReadOptions = {}): Promise<BacktestRunItem> {
  return request<unknown>(`${BACKTEST_API_BASE}/runs/${runId}`, { signal: options.signal }).then((run) =>
    assertBacktestRunItem(run, 'backtest run'),
  )
}

export async function getBacktestTrades(runId: string, options: BacktestReadOptions = {}): Promise<BacktestTradeItem[]> {
  return request<unknown>(`${BACKTEST_API_BASE}/runs/${runId}/trades`, { signal: options.signal }).then((items) =>
    ensureArray<BacktestTradeItem>(items, 'backtest trades'),
  )
}

export async function getBacktestSignals(runId: string, options: BacktestReadOptions = {}): Promise<BacktestSignalItem[]> {
  return request<unknown>(`${BACKTEST_API_BASE}/runs/${runId}/signals`, { signal: options.signal }).then((items) =>
    ensureArray(items, 'backtest signals').map(assertBacktestSignalItem),
  )
}

export async function getBacktestExperimentPackage(
  runId: string,
  options: BacktestReadOptions = {},
): Promise<BacktestExperimentPackageResponse> {
  return request<unknown>(`${BACKTEST_API_BASE}/runs/${runId}/experiment-package`, {
    signal: options.signal,
    timeoutMs: 30000,
  }).then(assertBacktestExperimentPackage)
}

export async function deleteBacktestRun(runId: string): Promise<{ deleted: string }> {
  return request<unknown>(`${BACKTEST_API_BASE}/runs/${runId}`, { method: 'DELETE' }).then(assertBacktestDeleteResult)
}

export async function getBacktestSummary(options: BacktestReadOptions = {}): Promise<BacktestSummary> {
  return request<unknown>(`${BACKTEST_API_BASE}/summary`, { signal: options.signal }).then(assertBacktestSummary)
}
