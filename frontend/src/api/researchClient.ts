import { request } from './httpClient'
import {
  LinkedProjectRef,
  ResearchEvidenceLink,
  ResearchFeedbackEvent,
  ResearchArtifactMaterializeResult,
  ResearchBacktestVerdictInputsResponse,
  ResearchHypothesisDraftPayload,
  ResearchHypothesisDraftResponse,
  ResearchIteration,
  ResearchIterationMetrics,
  ResearchIterationPatchPayload,
  ResearchLoop,
  ResearchLoopDetail,
  ResearchLoopUpdatePayload,
  ResearchSignalOpsEvidenceResponse,
  ResearchSummary,
  ResearchTraceDetail,
  ResearchTraceImportPayload,
  ResearchTraceImportResult,
  ResearchTraceSummary,
  ResearchVerdictInputs,
} from '../types'

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

function hasTextField(record: Record<string, unknown>, field: string) {
  return typeof record[field] === 'string' && String(record[field]).trim().length > 0
}

function hasStringField(record: Record<string, unknown>, field: string) {
  return typeof record[field] === 'string'
}

function hasNumberField(record: Record<string, unknown>, field: string) {
  return typeof record[field] === 'number' && Number.isFinite(record[field])
}

function hasBooleanField(record: Record<string, unknown>, field: string) {
  return typeof record[field] === 'boolean'
}

function requireTextFields(record: Record<string, unknown>, fields: string[], label: string) {
  const missing = fields.filter((field) => !hasTextField(record, field))
  if (missing.length > 0) {
    throw new Error(`Unexpected ${label} response: missing ${missing.slice(0, 5).join(', ')}`)
  }
}

function requireStringFields(record: Record<string, unknown>, fields: string[], label: string) {
  const missing = fields.filter((field) => !hasStringField(record, field))
  if (missing.length > 0) {
    throw new Error(`Unexpected ${label} response: missing ${missing.slice(0, 5).join(', ')}`)
  }
}

function assertOptionalStringField(record: Record<string, unknown>, field: string, label: string) {
  if (record[field] !== undefined && record[field] !== null && typeof record[field] !== 'string') {
    throw new Error(`Unexpected ${label} response: ${field} must be a string`)
  }
}

function requireArrayFields(record: Record<string, unknown>, fields: string[], label: string) {
  const missing = fields.filter((field) => !Array.isArray(record[field]))
  if (missing.length > 0) {
    throw new Error(`Unexpected ${label} response: missing ${missing.slice(0, 5).join(', ')}`)
  }
}

function assertStringArray(value: unknown, label: string) {
  ensureArray(value, label).forEach((item) => {
    if (typeof item !== 'string') {
      throw new Error(`Unexpected ${label} response`)
    }
  })
}

function assertReviewGateBoundary(record: Record<string, unknown>, label: string, requireStrength = false) {
  requireTextFields(record, ['evidence_usage'], label)
  if (requireStrength) {
    requireTextFields(record, ['evidence_strength'], label)
  }
  if (
    !hasBooleanField(record, 'simulation_only')
    || !hasBooleanField(record, 'is_real_trade')
    || !hasBooleanField(record, 'strong_conclusion_allowed')
  ) {
    throw new Error(`Unexpected ${label} response: missing review boundary booleans`)
  }

  const usage = String(record.evidence_usage)
  const strength = String(record.evidence_strength || '').toUpperCase()
  if (
    record.strong_conclusion_allowed === true
    || strength === 'HIGH'
    || strength.includes('STRONG')
    || usage === 'primary_evidence'
  ) {
    throw new Error(`Unexpected ${label} response: workflow evidence must not become a strong conclusion`)
  }
  if (strength === 'SUPPORTING_ONLY') {
    throw new Error(`Unexpected ${label} response: workflow evidence must use LOW review-gate strength instead of legacy SUPPORTING_ONLY`)
  }
  if (usage !== 'review_gate_only' || record.simulation_only !== true || record.is_real_trade !== false) {
    throw new Error(`Unexpected ${label} response: workflow review must stay simulation-only`)
  }
}

function hasStrongEvidenceQuality(value: unknown) {
  const quality = String(value || '').toUpperCase()
  return (
    quality === 'HIGH'
    || quality === 'PASS'
    || quality === 'READY'
    || quality === 'RESEARCH_GRADE'
    || quality === 'PRIMARY_EVIDENCE_READY'
    || quality.includes('STRONG')
    || quality.includes('PRIMARY')
  )
}

function assertReviewGateEvidenceQuality(record: Record<string, unknown>, label: string) {
  if (hasStrongEvidenceQuality(record.quality)) {
    throw new Error(`Unexpected ${label} response: verdict evidence must stay review-gate strength`)
  }
}

function assertSupportingSignalOpsEvidenceQuality(record: Record<string, unknown>, label: string) {
  const sourceType = String(record.source_type || '').toUpperCase()
  if (sourceType !== 'SIGNALOPS' && sourceType !== 'SIGNALOPS_TICK') {
    return
  }
  if (hasStrongEvidenceQuality(record.quality)) {
    throw new Error(`Unexpected ${label} response: SignalOps evidence must stay supporting-only and cannot become a strong conclusion`)
  }
}

function truthyMetric(value: unknown) {
  if (typeof value === 'boolean') return value
  if (typeof value === 'number') return value !== 0
  const text = String(value || '').trim().toLowerCase()
  return ['1', 'true', 'yes', 'y', 'pass', 'passed', 'accepted', 'ready'].includes(text)
}

function hasMetric(record: Record<string, unknown>, field: string) {
  return record[field] !== undefined && record[field] !== null && String(record[field]).trim() !== ''
}

function metricText(record: Record<string, unknown>, field: string) {
  return String(record[field] || '').trim()
}

function assertResearchVerdictAcceptanceBoundary(inputs: Record<string, unknown>, metrics: Record<string, unknown>) {
  if (inputs.can_accept_feedback !== true) {
    return
  }
  const blockingReasons = ensureArray(inputs.blocking_reasons, 'research verdict blocking_reasons')
  const qualityWarnings = ensureArray(inputs.quality_warnings, 'research verdict quality_warnings')
  if (blockingReasons.length > 0 || qualityWarnings.length > 0) {
    throw new Error('Unexpected research verdict inputs response: accepted feedback cannot include blockers or quality warnings')
  }

  if (
    hasMetric(metrics, 'backtest_can_support_research_verdict')
    && !truthyMetric(metrics.backtest_can_support_research_verdict)
  ) {
    throw new Error('Unexpected research verdict inputs response: accepted feedback cannot rely on unsupported backtest evidence')
  }
  if (
    truthyMetric(metrics.backtest_weak_sample)
    || truthyMetric(metrics.backtest_weakSample)
    || truthyMetric(metrics.weak_sample)
    || truthyMetric(metrics.weakSample)
  ) {
    throw new Error('Unexpected research verdict inputs response: accepted feedback cannot rely on weak-sample backtest evidence')
  }

  const usage = metricText(metrics, 'backtest_research_usage').toLowerCase()
  const reviewConclusion = metricText(metrics, 'backtest_review_conclusion').toUpperCase()
  const evidenceGrade = metricText(metrics, 'backtest_evidence_grade').toUpperCase()
  if (usage === 'supporting_only' || reviewConclusion === 'SUPPORTING_ONLY') {
    throw new Error('Unexpected research verdict inputs response: accepted feedback cannot promote supporting-only backtest evidence')
  }
  if (['MISSING', 'UNKNOWN', 'LOW', 'SUPPORTING_ONLY', 'WEAK', 'WARN', 'REVIEW', 'REVIEW_ONLY', 'MEDIUM'].includes(evidenceGrade)) {
    throw new Error('Unexpected research verdict inputs response: accepted feedback requires high-grade backtest evidence')
  }
}

function assertResearchLoop(value: unknown): ResearchLoop {
  const loop = ensureRecord(value, 'research loop')
  requireTextFields(loop, ['loop_id', 'title', 'objective', 'status', 'action_target', 'owner', 'source', 'created_at', 'updated_at'], 'research loop')
  requireArrayFields(loop, ['tags', 'linked_projects'], 'research loop')
  if (!hasNumberField(loop, 'iteration_count')) {
    throw new Error('Unexpected research loop response: missing iteration_count')
  }
  assertStringArray(loop.tags, 'research loop tags')
  return value as ResearchLoop
}

function assertResearchEvidenceLink(value: unknown): ResearchEvidenceLink {
  const evidence = ensureRecord(value, 'research evidence link')
  requireTextFields(evidence, ['source_type', 'source_id', 'created_at'], 'research evidence link')
  requireStringFields(evidence, ['label', 'quality'], 'research evidence link')
  assertOptionalStringField(evidence, 'reportedQuality', 'research evidence link')
  assertOptionalStringField(evidence, 'reported_quality', 'research evidence link')
  assertReviewGateEvidenceQuality(evidence, 'research evidence link')
  assertSupportingSignalOpsEvidenceQuality(evidence, 'research evidence link')
  return value as ResearchEvidenceLink
}

function assertResearchFeedbackEvent(value: unknown): ResearchFeedbackEvent {
  const feedback = ensureRecord(value, 'research feedback event')
  requireTextFields(feedback, ['event_id', 'action', 'created_at'], 'research feedback event')
  requireStringFields(feedback, ['verdict', 'note', 'reviewer'], 'research feedback event')
  return value as ResearchFeedbackEvent
}

function assertResearchIteration(value: unknown): ResearchIteration {
  const iteration = ensureRecord(value, 'research iteration')
  requireTextFields(iteration, ['iteration_id', 'loop_id', 'status', 'hypothesis', 'verdict', 'created_at', 'updated_at'], 'research iteration')
  requireStringFields(iteration, ['plan'], 'research iteration')
  requireArrayFields(iteration, ['target_modules', 'evidence_links', 'feedback_events'], 'research iteration')
  if (!hasNumberField(iteration, 'order')) {
    throw new Error('Unexpected research iteration response')
  }
  assertStringArray(iteration.target_modules, 'research iteration target_modules')
  ensureRecord(iteration.metrics, 'research iteration metrics')
  ensureArray(iteration.evidence_links, 'research iteration evidence_links').forEach(assertResearchEvidenceLink)
  ensureArray(iteration.feedback_events, 'research iteration feedback_events').forEach(assertResearchFeedbackEvent)
  return value as ResearchIteration
}

function assertResearchWorkflowStep(value: unknown) {
  const step = ensureRecord(value, 'research workflow step')
  requireTextFields(step, ['key', 'label', 'status'], 'research workflow step')
  requireStringFields(
    step,
    ['detail', 'source', 'source_timestamp', 'evidence_strength', 'next_action', 'next_action_label'],
    'research workflow step',
  )
  requireArrayFields(step, ['missing_items'], 'research workflow step')
  assertStringArray(step.missing_items, 'research workflow step missing_items')
  assertReviewGateBoundary(step, 'research workflow step', true)
}

function assertResearchWorkflowState(value: unknown) {
  const workflowState = ensureRecord(value, 'research workflow state')
  requireTextFields(workflowState, ['maturity_level', 'maturity_label', 'stage', 'next_action', 'next_action_label', 'evidence_strength'], 'research workflow state')
  requireArrayFields(workflowState, ['maturity_reasons', 'blocking_reasons', 'steps'], 'research workflow state')
  if (!hasNumberField(workflowState, 'maturity_score')) {
    throw new Error('Unexpected research workflow state response: missing maturity_score')
  }
  assertStringArray(workflowState.maturity_reasons, 'research workflow maturity_reasons')
  assertStringArray(workflowState.blocking_reasons, 'research workflow blocking_reasons')
  ensureArray(workflowState.steps, 'research workflow steps').forEach(assertResearchWorkflowStep)
  assertReviewGateBoundary(workflowState, 'research workflow state')
}

function assertResearchLoopDetail(value: unknown): ResearchLoopDetail {
  const detail = ensureRecord(value, 'research loop detail')
  assertResearchLoop(detail.loop)
  ensureArray(detail.iterations, 'research loop detail iterations').forEach(assertResearchIteration)
  if (detail.workflow_state !== undefined && detail.workflow_state !== null) {
    assertResearchWorkflowState(detail.workflow_state)
  }
  return value as ResearchLoopDetail
}

function assertResearchSampleLoopResponse(value: unknown): ResearchSampleLoopResponse {
  const result = ensureRecord(value, 'research sample loop')
  if (!hasBooleanField(result, 'created')) {
    throw new Error('Unexpected research sample loop response: missing created')
  }
  requireArrayFields(result, ['missing_reasons'], 'research sample loop')
  assertStringArray(result.missing_reasons, 'research sample loop missing_reasons')
  ensureRecord(result.context, 'research sample loop context')
  if (result.detail !== undefined && result.detail !== null) {
    assertResearchLoopDetail(result.detail)
  }
  return value as ResearchSampleLoopResponse
}

function assertP2ClosedLoopStep(value: unknown): P2ClosedLoopStepStatus {
  const step = ensureRecord(value, 'P2 closed-loop step')
  requireTextFields(step, ['key', 'label', 'status'], 'P2 closed-loop step')
  requireStringFields(step, ['note', 'evidence_strength', 'next_action', 'next_action_label'], 'P2 closed-loop step')
  requireArrayFields(step, ['missing_items'], 'P2 closed-loop step')
  assertStringArray(step.missing_items, 'P2 closed-loop step missing_items')
  assertReviewGateBoundary(step, 'P2 closed-loop step', true)
  return value as P2ClosedLoopStepStatus
}

function assertP2ClosedLoopSampleResponse(value: unknown): P2ClosedLoopSampleResponse {
  const result = ensureRecord(value, 'P2 closed-loop sample')
  if (!hasBooleanField(result, 'created') || !hasBooleanField(result, 'simulation_only') || !hasBooleanField(result, 'is_real_trade')) {
    throw new Error('Unexpected P2 closed-loop sample response: missing boundary booleans')
  }
  if (result.simulation_only !== true || result.is_real_trade !== false) {
    throw new Error('Unexpected P2 closed-loop sample response: sample must stay simulation-only')
  }
  const steps = ensureArray(result.steps, 'P2 closed-loop steps')
  if (steps.length === 0) {
    throw new Error('Unexpected P2 closed-loop sample response: missing review steps')
  }
  steps.forEach(assertP2ClosedLoopStep)
  assertStringArray(result.warnings, 'P2 closed-loop warnings')
  if (result.knowledge_version_id) {
    requireStringFields(result, ['knowledge_version_status'], 'P2 closed-loop sample')
  }
  if (result.sample_loop !== undefined && result.sample_loop !== null) {
    assertResearchSampleLoopResponse(result.sample_loop)
  }
  return value as P2ClosedLoopSampleResponse
}

function assertResearchVerdictInputs(value: unknown): ResearchVerdictInputs {
  const inputs = ensureRecord(value, 'research verdict inputs')
  requireTextFields(
    inputs,
    ['iteration_id', 'loop_id', 'status', 'current_verdict', 'engine_verdict', 'suggested_feedback_verdict', 'generated_at'],
    'research verdict inputs',
  )
  if (!hasNumberField(inputs, 'confidence') || !hasBooleanField(inputs, 'can_accept_feedback')) {
    throw new Error('Unexpected research verdict inputs response')
  }
  const metrics = ensureRecord(inputs.metrics, 'research verdict metrics')
  ensureRecord(inputs.baseline, 'research verdict baseline')
  ensureRecord(inputs.current, 'research verdict current')
  requireArrayFields(inputs, ['blocking_reasons', 'quality_warnings', 'comparison', 'evidence'], 'research verdict inputs')
  assertStringArray(inputs.blocking_reasons, 'research verdict blocking_reasons')
  assertStringArray(inputs.quality_warnings, 'research verdict quality_warnings')
  ensureArray(inputs.comparison, 'research verdict comparison rows').forEach(assertResearchMetricComparisonRow)
  ensureArray(inputs.evidence, 'research verdict evidence rows').forEach(assertResearchVerdictEvidence)
  assertResearchVerdictAcceptanceBoundary(inputs, metrics)
  return value as ResearchVerdictInputs
}

function assertResearchMetricComparisonRow(value: unknown) {
  const row = ensureRecord(value, 'research verdict comparison row')
  requireTextFields(row, ['key'], 'research verdict comparison row')
  requireStringFields(row, ['label', 'quality', 'warning'], 'research verdict comparison row')
}

function assertResearchVerdictEvidence(value: unknown) {
  const evidence = ensureRecord(value, 'research verdict evidence row')
  requireTextFields(evidence, ['source_type', 'source_id', 'created_at'], 'research verdict evidence row')
  requireStringFields(evidence, ['label', 'quality', 'summary'], 'research verdict evidence row')
  assertOptionalStringField(evidence, 'reportedQuality', 'research verdict evidence row')
  assertOptionalStringField(evidence, 'reported_quality', 'research verdict evidence row')
  ensureRecord(evidence.metrics, 'research verdict evidence metrics')
  assertReviewGateEvidenceQuality(evidence, 'research verdict evidence row')
  assertSupportingSignalOpsEvidenceQuality(evidence, 'research verdict evidence row')
}

function assertResearchActionSelection(value: unknown) {
  const selection = ensureRecord(value, 'research action selection')
  requireTextFields(selection, ['target', 'rule_id', 'reason'], 'research action selection')
  if (!hasNumberField(selection, 'confidence')) {
    throw new Error('Unexpected research action selection response: missing confidence')
  }
  assertStringArray(selection.evidence, 'research action selection evidence')
}

function assertResearchHypothesisDraft(value: unknown) {
  const draft = ensureRecord(value, 'research hypothesis draft item')
  requireTextFields(draft, ['hypothesis', 'action_target'], 'research hypothesis draft item')
  requireStringFields(draft, ['plan', 'rationale', 'source'], 'research hypothesis draft item')
  requireArrayFields(draft, ['target_modules'], 'research hypothesis draft item')
  assertStringArray(draft.target_modules, 'research hypothesis draft target_modules')
  if (draft.targetModules !== undefined) {
    assertStringArray(draft.targetModules, 'research hypothesis draft targetModules')
  }
  if (draft.modules !== undefined) {
    assertStringArray(draft.modules, 'research hypothesis draft modules')
  }
  if (draft.evidence !== undefined) {
    ensureArray(draft.evidence, 'research hypothesis draft evidence')
  }
}

function assertResearchHypothesisDraftResponse(value: unknown): ResearchHypothesisDraftResponse {
  const result = ensureRecord(value, 'research hypothesis draft')
  requireTextFields(result, ['draft_id', 'loop_id', 'status', 'llm_status', 'created_at'], 'research hypothesis draft')
  assertResearchActionSelection(result.action_selection)
  ensureRecord(result.prompt_provenance, 'research hypothesis prompt provenance')
  ensureArray(result.drafts, 'research hypothesis drafts').forEach(assertResearchHypothesisDraft)
  if (!hasBooleanField(result, 'confirmation_required') || !hasBooleanField(result, 'auto_run_started')) {
    throw new Error('Unexpected research hypothesis draft response')
  }
  return value as ResearchHypothesisDraftResponse
}

function assertResearchArtifactMaterializeResult(value: unknown): ResearchArtifactMaterializeResult {
  const result = ensureRecord(value, 'research artifact materialization')
  assertResearchIteration(result.iteration)
  requireArrayFields(result, ['provenance_chain', 'warnings'], 'research artifact materialization')
  assertStringArray(result.provenance_chain, 'research artifact materialization provenance_chain')
  assertStringArray(result.warnings, 'research artifact materialization warnings')
  return value as ResearchArtifactMaterializeResult
}

function assertSupportingOnlyResearchBridgeBoundary(result: Record<string, unknown>, label: string) {
  requireTextFields(result, ['evidence_usage'], label)
  if (
    !hasBooleanField(result, 'supporting_only')
    || !hasBooleanField(result, 'simulation_only')
    || !hasBooleanField(result, 'is_real_trade')
    || !hasBooleanField(result, 'strong_conclusion_allowed')
  ) {
    throw new Error(`Unexpected ${label} response: missing boundary booleans`)
  }
  if (
    result.evidence_usage !== 'supporting_only'
    || result.supporting_only !== true
    || result.simulation_only !== true
    || result.is_real_trade !== false
    || result.strong_conclusion_allowed !== false
  ) {
    throw new Error(`Unexpected ${label} response: research evidence bridge must stay supporting-only and simulation-only`)
  }
}

function assertResearchBacktestVerdictInputsResponse(value: unknown): ResearchBacktestVerdictInputsResponse {
  const result = ensureRecord(value, 'research backtest verdict inputs')
  assertResearchIteration(result.iteration)
  assertResearchVerdictInputs(result.verdict_inputs)
  assertSupportingOnlyResearchBridgeBoundary(result, 'research backtest verdict inputs')
  return value as ResearchBacktestVerdictInputsResponse
}

function assertResearchSignalOpsEvidenceResponse(value: unknown): ResearchSignalOpsEvidenceResponse {
  const result = ensureRecord(value, 'research SignalOps evidence')
  assertResearchIteration(result.iteration)
  assertResearchVerdictInputs(result.verdict_inputs)
  assertSupportingOnlyResearchBridgeBoundary(result, 'research SignalOps evidence')
  return value as ResearchSignalOpsEvidenceResponse
}

interface ResearchTraceImportApiResponse {
  imported: boolean
  loop?: ResearchLoop | null
  loop_preview: {
    title: string
    objective: string
    tags?: string[]
  }
  iterations: Array<{
    order: number
    iteration?: ResearchIteration | null
    hypothesis: string
    external_verdict: string
    evidence_count: number
  }>
  external_source: Record<string, unknown>
  warnings: string[]
}

function assertResearchTraceImportApiResponse(value: unknown): ResearchTraceImportApiResponse {
  const result = ensureRecord(value, 'research trace import')
  if (!hasBooleanField(result, 'imported')) {
    throw new Error('Unexpected research trace import response: missing imported')
  }
  const preview = ensureRecord(result.loop_preview, 'research trace import preview')
  requireTextFields(preview, ['title', 'objective'], 'research trace import preview')
  if (preview.tags !== undefined) {
    assertStringArray(preview.tags, 'research trace import preview tags')
  }
  ensureRecord(result.external_source, 'research trace import external source')
  ensureArray(result.iterations, 'research trace import iterations').forEach(assertResearchTraceImportIteration)
  assertStringArray(result.warnings, 'research trace import warnings')
  if (result.loop !== undefined && result.loop !== null) {
    assertResearchLoop(result.loop)
  }
  return value as ResearchTraceImportApiResponse
}

function assertResearchTraceImportIteration(value: unknown) {
  const iteration = ensureRecord(value, 'research trace import iteration')
  requireTextFields(iteration, ['hypothesis', 'external_verdict'], 'research trace import iteration')
  if (!hasNumberField(iteration, 'order') || !hasNumberField(iteration, 'evidence_count')) {
    throw new Error('Unexpected research trace import iteration response')
  }
  if (iteration.iteration !== undefined && iteration.iteration !== null) {
    assertResearchIteration(iteration.iteration)
  }
}

export function getResearchSummary() {
  return request<unknown>('/research/summary').then((summary) => {
    ensureRecord(summary, 'research summary')
    const record = summary as Record<string, unknown>
    if (!hasNumberField(record, 'total_loops') || !hasNumberField(record, 'active_loops') || !hasNumberField(record, 'total_iterations')) {
      throw new Error('Unexpected research summary response')
    }
    return summary as ResearchSummary
  })
}

export function getResearchLoops(filters: { status?: string } = {}) {
  const params = new URLSearchParams()
  if (filters.status) params.set('status', filters.status)
  const query = params.toString()
  return request<unknown>(`/research/loops${query ? `?${query}` : ''}`).then((loops) =>
    ensureArray(loops, 'research loops list').map(assertResearchLoop),
  )
}

export function getResearchLoop(loopId: string) {
  return request<unknown>(`/research/loops/${loopId}`).then(assertResearchLoopDetail)
}

export function createResearchLoop(payload: {
  title: string
  objective: string
  hypothesis?: string
  plan?: string
  action_target?: string
  owner?: string
  tags?: string[]
  target_modules?: string[]
  linked_projects?: LinkedProjectRef[]
}) {
  return request<unknown>('/research/loops', {
    method: 'POST',
    body: JSON.stringify(payload),
  }).then(assertResearchLoopDetail)
}

export interface ResearchSampleLoopResponse {
  created: boolean
  detail?: ResearchLoopDetail | null
  missing_reasons: string[]
  context: Record<string, unknown>
  artifact_context?: Record<string, unknown>
}

export interface P2ClosedLoopStepStatus {
  key: string
  label: string
  status: string
  ref_id?: string | null
  note: string
  evidence_usage: 'review_gate_only' | (string & {})
  evidence_strength: 'MEDIUM' | 'LOW' | 'MISSING' | 'PENDING' | 'UNKNOWN' | (string & {})
  simulation_only: boolean
  is_real_trade: boolean
  strong_conclusion_allowed: boolean
  missing_items: string[]
  next_action: string
  next_action_label: string
}

export interface P2ClosedLoopSampleResponse {
  created: boolean
  simulation_only: boolean
  is_real_trade: boolean
  portfolio_snapshot_id?: string | null
  run_id?: string | null
  signal_id?: string | null
  backtest_run_id?: string | null
  loop_id?: string | null
  iteration_id?: string | null
  case_id?: string | null
  knowledge_item_id?: string | null
  patch_id?: string | null
  evaluation_id?: string | null
  knowledge_version_id?: string | null
  knowledge_version_status?: string | null
  sample_loop?: ResearchSampleLoopResponse | null
  steps: P2ClosedLoopStepStatus[]
  warnings: string[]
}

export function createResearchSampleLoopFromLatestRun(payload: {
  run_id?: string
  symbol?: string
  force_backtest?: boolean
  materialize_artifacts?: boolean
  run_evaluation?: boolean
  reviewer?: string
} = {}) {
  return request<unknown>('/research/sample-loop/from-latest-run', {
    method: 'POST',
    body: JSON.stringify(payload),
    timeoutMs: 30000,
  }).then(assertResearchSampleLoopResponse)
}

export function createP2ClosedLoopSample(payload: {
  symbol?: string
  stock_name?: string
  portfolio_snapshot_id?: string
  force_backtest?: boolean
  materialize_artifacts?: boolean
  run_evaluation?: boolean
  promote_knowledge_version?: boolean
  reviewer?: string
} = {}) {
  return request<unknown>('/research/p2/closed-loop-sample', {
    method: 'POST',
    body: JSON.stringify(payload),
    timeoutMs: 45000,
  }).then(assertP2ClosedLoopSampleResponse)
}

export function updateResearchLoop(loopId: string, payload: ResearchLoopUpdatePayload) {
  return request<unknown>(`/research/loops/${loopId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  }).then(assertResearchLoopDetail)
}

export function archiveResearchLoop(loopId: string, payload: {
  reviewer?: string
  note?: string
} = {}) {
  return request<unknown>(`/research/loops/${loopId}/archive`, {
    method: 'POST',
    body: JSON.stringify(payload),
  }).then(assertResearchLoopDetail)
}

export function createResearchIteration(loopId: string, payload: {
  hypothesis: string
  plan?: string
  target_modules?: string[]
  linked_run_id?: string
  metrics?: ResearchIterationMetrics
}) {
  return request<unknown>(`/research/loops/${loopId}/iterations`, {
    method: 'POST',
    body: JSON.stringify(payload),
  }).then(assertResearchIteration)
}

export function patchResearchIteration(iterationId: string, payload: ResearchIterationPatchPayload) {
  return request<unknown>(`/research/iterations/${iterationId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  }).then(assertResearchIteration)
}

export function attachResearchIterationRun(iterationId: string, payload: {
  run_id: string
  reviewer?: string
  note?: string
}) {
  return request<unknown>(`/research/iterations/${iterationId}/attach-run`, {
    method: 'POST',
    body: JSON.stringify(payload),
  }).then(assertResearchIteration)
}

export function attachResearchIterationBacktest(iterationId: string, payload: {
  backtest_id: string
  reviewer?: string
  note?: string
}) {
  return request<unknown>(`/research/iterations/${iterationId}/attach-backtest`, {
    method: 'POST',
    body: JSON.stringify({
      backtest_run_id: payload.backtest_id,
      reviewer: payload.reviewer,
      note: payload.note,
    }),
  }).then(assertResearchIteration)
}

export function retryBottomResearchBacktest(iterationId: string, payload: {
  run_id?: string
  force_new?: boolean
  reviewer?: string
} = {}) {
  return request<unknown>(`/research/iterations/${iterationId}/mfe-mae/backtest`, {
    method: 'POST',
    body: JSON.stringify(payload),
    timeoutMs: 30000,
  }).then(assertResearchIteration)
}

export function createNextResearchIteration(iterationId: string, payload: {
  hypothesis: string
  plan?: string
  target_modules?: string[]
  reviewer?: string
  note?: string
}) {
  return request<unknown>(`/research/iterations/${iterationId}/next`, {
    method: 'POST',
    body: JSON.stringify(payload),
  }).then(assertResearchIteration)
}

export function draftResearchHypotheses(loopId: string, payload: ResearchHypothesisDraftPayload) {
  return request<unknown>(`/research/loops/${loopId}/hypotheses/draft`, {
    method: 'POST',
    body: JSON.stringify(payload),
    timeoutMs: payload.use_llm ? 45000 : 15000,
  }).then(assertResearchHypothesisDraftResponse)
}

export function confirmResearchHypothesisDraft(draftId: string, payload: {
  selected_index?: number
  reviewer?: string
  note?: string
}) {
  return request<unknown>(`/research/hypothesis-drafts/${draftId}/confirm`, {
    method: 'POST',
    body: JSON.stringify(payload),
  }).then(assertResearchIteration)
}

export function recordResearchIterationFeedback(iterationId: string, payload: {
  action: string
  verdict: string
  note?: string
  reviewer?: string
  status?: string
  linked_run_id?: string
  linked_backtest_id?: string
  linked_case_id?: string
  linked_knowledge_item_id?: string
  linked_patch_id?: string
  metrics?: ResearchIterationMetrics
  evidence_links?: ResearchEvidenceLink[]
  override_blocking_reasons?: boolean
  override_reason?: string
}) {
  return request<unknown>(`/research/iterations/${iterationId}/feedback`, {
    method: 'POST',
    body: JSON.stringify(payload),
  }).then(assertResearchIteration)
}

export function getResearchVerdictInputs(iterationId: string, filters: {
  baseline_run_id?: string
  candidate_run_id?: string
} = {}) {
  const params = new URLSearchParams()
  if (filters.baseline_run_id) params.set('baseline_run_id', filters.baseline_run_id)
  if (filters.candidate_run_id) params.set('candidate_run_id', filters.candidate_run_id)
  const query = params.toString()
  return request<unknown>(`/research/iterations/${iterationId}/verdict-inputs${query ? `?${query}` : ''}`).then(assertResearchVerdictInputs)
}

export function refreshResearchVerdictInputs(iterationId: string, filters: {
  baseline_run_id?: string
  candidate_run_id?: string
} = {}) {
  const params = new URLSearchParams()
  if (filters.baseline_run_id) params.set('baseline_run_id', filters.baseline_run_id)
  if (filters.candidate_run_id) params.set('candidate_run_id', filters.candidate_run_id)
  const query = params.toString()
  return request<unknown>(`/research/iterations/${iterationId}/verdict-inputs/refresh${query ? `?${query}` : ''}`, {
    method: 'POST',
  }).then(assertResearchVerdictInputs)
}

export function createResearchBacktestVerdictInputs(runId: string, payload: {
  iteration_id: string
  reviewer?: string
  note?: string
  role?: string
  review_conclusion?: string
  refresh?: boolean
}) {
  return request<unknown>(`/research/backtest/runs/${runId}/verdict-inputs`, {
    method: 'POST',
    body: JSON.stringify(payload),
  }).then(assertResearchBacktestVerdictInputsResponse)
}

export function createResearchSignalOpsEvidence(signalId: string, payload: {
  iteration_id: string
  reviewer?: string
  note?: string
  refresh?: boolean
}) {
  return request<unknown>(`/research/signalops/signals/${signalId}/evidence`, {
    method: 'POST',
    body: JSON.stringify(payload),
  }).then(assertResearchSignalOpsEvidenceResponse)
}

export function materializeResearchIterationArtifacts(iterationId: string, payload: {
  create_case?: boolean
  create_knowledge_item?: boolean
  create_error_entry?: boolean
  create_patch?: boolean
  run_evaluation?: boolean
  force?: boolean
  reviewer?: string
  note?: string
  patch_content?: Record<string, unknown>
} = {}) {
  return request<unknown>(`/research/iterations/${iterationId}/artifacts/materialize`, {
    method: 'POST',
    body: JSON.stringify(payload),
  }).then(assertResearchArtifactMaterializeResult)
}

export function getResearchTraces(filters: {
  loop_id?: string
  iteration_id?: string
  source?: string
} = {}) {
  const params = new URLSearchParams()
  if (filters.loop_id) params.set('loop_id', filters.loop_id)
  if (filters.iteration_id) params.set('iteration_id', filters.iteration_id)
  if (filters.source) params.set('source', filters.source)
  const query = params.toString()
  return request<unknown>(`/research/traces${query ? `?${query}` : ''}`)
    .then((loops) => ensureArray(loops, 'research traces list').map(assertResearchLoop))
    .then((loops) => loops.map(loopToTraceSummary))
}

export function getResearchTrace(traceId: string) {
  return request<unknown>(`/research/traces/${traceId}`).then(assertResearchLoopDetail).then(loopDetailToTraceDetail)
}

export function importResearchTrace(payload: ResearchTraceImportPayload) {
  return request<unknown>('/research/traces/import', {
    method: 'POST',
    body: JSON.stringify({
      trace: payload.trace,
      source_id: payload.run_id || payload.iteration_id || payload.loop_id || payload.source,
      dry_run: false,
      note: payload.title ? `Imported from ${payload.title}` : '',
    }),
    timeoutMs: 30000,
  }).then(assertResearchTraceImportApiResponse).then((result) => {
    const trace = importResultToTraceDetail(result)
    return {
      trace,
      warnings: result.warnings || [],
    } satisfies ResearchTraceImportResult
  })
}

function loopToTraceSummary(loop: ResearchLoop): ResearchTraceSummary {
  return {
    trace_id: loop.loop_id,
    source: loop.source || 'rd-agent',
    title: loop.title,
    status: loop.status,
    loop_id: loop.loop_id,
    imported_at: loop.created_at,
    updated_at: loop.updated_at,
    summary: loop.objective,
    metadata: {
      action_target: loop.action_target,
      tags: loop.tags,
      linked_projects: loop.linked_projects,
      iteration_count: loop.iteration_count,
    },
  }
}

function loopDetailToTraceDetail(detail: ResearchLoopDetail): ResearchTraceDetail {
  const summary = loopToTraceSummary(detail.loop)
  return {
    ...summary,
    events: detail.iterations.flatMap((iteration) =>
      iteration.feedback_events.map((event) => ({
        ...event,
        iteration_id: iteration.iteration_id,
      })),
    ),
    artifacts: detail.iterations.flatMap((iteration) =>
      iteration.evidence_links.map((link) => ({
        ...link,
        iteration_id: iteration.iteration_id,
      })),
    ),
    raw_trace: {
      loop: detail.loop,
      iterations: detail.iterations,
    },
  }
}

function importResultToTraceDetail(result: {
  loop?: ResearchLoop | null
  loop_preview: {
    title: string
    objective: string
  }
  iterations: Array<{
    iteration?: ResearchIteration | null
    hypothesis: string
    external_verdict: string
    evidence_count: number
  }>
  external_source: Record<string, unknown>
}): ResearchTraceDetail {
  const loop = result.loop
  const sourceId = String(result.external_source?.source_id || loop?.loop_id || 'rd-agent-trace')
  const traceId = loop?.loop_id || sourceId
  return {
    trace_id: traceId,
    source: String(result.external_source?.source || loop?.source || 'rd-agent'),
    title: loop?.title || result.loop_preview.title,
    status: loop?.status || 'PREVIEW',
    loop_id: loop?.loop_id || null,
    imported_at: String(result.external_source?.imported_at || loop?.created_at || ''),
    updated_at: loop?.updated_at || String(result.external_source?.imported_at || ''),
    summary: loop?.objective || result.loop_preview.objective,
    metadata: {
      external_source: result.external_source,
      iteration_count: result.iterations.length,
    },
    events: result.iterations.map((item) => ({
      hypothesis: item.hypothesis,
      external_verdict: item.external_verdict,
      iteration_id: item.iteration?.iteration_id,
    })),
    artifacts: result.iterations.map((item) => ({
      hypothesis: item.hypothesis,
      evidence_count: item.evidence_count,
      iteration_id: item.iteration?.iteration_id,
    })),
    raw_trace: result as unknown as Record<string, unknown>,
  }
}
