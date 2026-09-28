import { request } from './httpClient'
import {
  CompressionOverview,
  DataFingerprint,
  DataQualityScore,
  KnowledgeDistillationGroup,
  RunCompressionSummary,
} from '../types'

export function getDataPipelineOverview(limit = 50) {
  return request<unknown>(`/data-pipeline/overview?limit=${limit}`).then(assertCompressionOverview)
}

export function getRunQuality(runId: string) {
  return request<unknown>(`/data-pipeline/runs/${runId}/quality`).then(assertDataQualityScore)
}

export function getRunCompressionSummary(runId: string) {
  return request<unknown>(`/data-pipeline/runs/${runId}/summary`).then(assertRunCompressionSummary)
}

export function compressRun(runId: string) {
  return request<unknown>(`/data-pipeline/runs/${runId}/compress`, {
    method: 'POST',
  }).then(assertRunCompressionSummary)
}

export function getKnowledgeDistillationGroups(filters: {
  status?: string
  category?: string
  minGroupSize?: number
} = {}) {
  const params = new URLSearchParams()
  if (filters.status) params.set('status', filters.status)
  if (filters.category) params.set('category', filters.category)
  if (filters.minGroupSize) params.set('min_group_size', String(filters.minGroupSize))
  const query = params.toString()
  return request<unknown>(`/data-pipeline/knowledge/distill${query ? `?${query}` : ''}`).then(assertKnowledgeDistillationGroupList)
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

function assertOptionalString(record: Record<string, unknown>, key: string, label: string) {
  const value = record[key]
  if (value !== undefined && value !== null && typeof value !== 'string') {
    throw new Error(`Unexpected ${label} response: invalid ${key}`)
  }
}

function assertOptionalBoolean(record: Record<string, unknown>, key: string, label: string) {
  const value = record[key]
  if (value !== undefined && value !== null && typeof value !== 'boolean') {
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

function assertNumberRecord(value: unknown, label: string) {
  const record = ensureRecord(value, label)
  Object.entries(record).forEach(([key, item]) => {
    if (typeof item !== 'number' || Number.isNaN(item)) {
      throw new Error(`Unexpected ${label} response: invalid ${key}`)
    }
  })
}

function assertDataFingerprint(value: unknown): DataFingerprint {
  const fingerprint = ensureRecord(value, 'data fingerprint')
  requireString(fingerprint, 'namespace', 'data fingerprint')
  requireString(fingerprint, 'fingerprint', 'data fingerprint')
  requireNumber(fingerprint, 'size_bytes', 'data fingerprint')
  assertStringArray(fingerprint.canonical_keys, 'data fingerprint canonical_keys')
  requireString(fingerprint, 'created_at', 'data fingerprint')
  return value as DataFingerprint
}

function assertDataQualityScore(value: unknown): DataQualityScore {
  const quality = ensureRecord(value, 'data quality score')
  requireNumber(quality, 'score', 'data quality score')
  requireString(quality, 'level', 'data quality score')
  assertStringArray(quality.issues, 'data quality issues')
  assertStringArray(quality.strengths, 'data quality strengths')
  requireString(quality, 'source_coverage', 'data quality score')
  assertStringArray(quality.missing_critical_fields, 'data quality missing_critical_fields')
  return value as DataQualityScore
}

function assertRunCompressionSummary(value: unknown): RunCompressionSummary {
  const summary = ensureRecord(value, 'run compression summary')
  requireString(summary, 'run_id', 'run compression summary')
  requireString(summary, 'symbol', 'run compression summary')
  requireString(summary, 'stock_name', 'run compression summary')
  requireString(summary, 'status', 'run compression summary')
  requireString(summary, 'run_mode', 'run compression summary')
  requireString(summary, 'final_action', 'run compression summary')
  assertDataFingerprint(summary.data_fingerprint)
  assertDataQualityScore(summary.quality)
  assertStringArray(summary.keep_fields, 'run compression keep_fields')
  ensureRecord(summary.key_metrics, 'run compression key_metrics')
  requireString(summary, 'decision_summary', 'run compression summary')
  assertStringArray(summary.guardrail_summary, 'run compression guardrail_summary')
  assertStringArray(summary.evidence_summary, 'run compression evidence_summary')
  ensureRecord(summary.agent_summary, 'run compression agent_summary')
  requireNumber(summary, 'token_budget_estimate', 'run compression summary')
  requireString(summary, 'retention_action', 'run compression summary')
  requireString(summary, 'retention_reason', 'run compression summary')
  requireString(summary, 'created_at', 'run compression summary')
  assertOptionalBoolean(summary, 'compression_persisted', 'run compression summary')
  assertOptionalString(summary, 'artifact_path', 'run compression summary')
  assertOptionalString(summary, 'compressed_at', 'run compression summary')
  return value as RunCompressionSummary
}

function assertKnowledgeDistillationGroup(value: unknown): KnowledgeDistillationGroup {
  const group = ensureRecord(value, 'knowledge distillation group')
  requireString(group, 'group_id', 'knowledge distillation group')
  requireString(group, 'category', 'knowledge distillation group')
  requireString(group, 'fingerprint', 'knowledge distillation group')
  assertStringArray(group.item_ids, 'knowledge distillation item_ids')
  requireString(group, 'representative_item_id', 'knowledge distillation group')
  requireNumber(group, 'duplicate_count', 'knowledge distillation group')
  assertStringArray(group.shared_tags, 'knowledge distillation shared_tags')
  requireString(group, 'suggested_action', 'knowledge distillation group')
  requireString(group, 'reason', 'knowledge distillation group')
  return value as KnowledgeDistillationGroup
}

function assertKnowledgeDistillationGroupList(value: unknown): KnowledgeDistillationGroup[] {
  return ensureArray(value, 'knowledge distillation group list').map(assertKnowledgeDistillationGroup)
}

function assertCompressionOverview(value: unknown): CompressionOverview {
  const overview = ensureRecord(value, 'compression overview')
  requireNumber(overview, 'total_runs', 'compression overview')
  requireNumber(overview, 'summarized_runs', 'compression overview')
  requireNumber(overview, 'average_quality_score', 'compression overview')
  requireNumber(overview, 'high_quality_count', 'compression overview')
  requireNumber(overview, 'medium_quality_count', 'compression overview')
  requireNumber(overview, 'low_quality_count', 'compression overview')
  assertNumberRecord(overview.retention_actions, 'compression overview retention_actions')
  assertOptionalString(overview, 'latest_run_id', 'compression overview')
  return value as CompressionOverview
}
