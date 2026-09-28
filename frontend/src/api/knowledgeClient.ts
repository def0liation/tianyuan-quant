import { request } from './httpClient'
import { KnowledgeItem, KnowledgeSummary } from '../types'

export interface CreateKnowledgeItemPayload {
  category: string
  title: string
  thesis: string
  evidence: string[]
  decision_impact: string
  guardrail_notes: string[]
  tags: string[]
  confidence: string
  source_run_id?: string
}

export function getKnowledgeSummary() {
  return request<unknown>('/knowledge/summary').then(assertKnowledgeSummary)
}

export function getKnowledgeItems(filters: { status?: string; category?: string } = {}) {
  const params = new URLSearchParams()
  if (filters.status) params.set('status', filters.status)
  if (filters.category) params.set('category', filters.category)
  const query = params.toString()
  return request<unknown>(`/knowledge/items${query ? `?${query}` : ''}`).then(assertKnowledgeItemList)
}

export function knowledgeSubmissionConfidence(value: string): 'MEDIUM' | 'LOW' {
  const normalized = value.trim().toUpperCase()
  if (normalized === 'HIGH' || normalized === 'MEDIUM') return 'MEDIUM'
  return 'LOW'
}

function sanitizeCreateKnowledgeItemPayload(payload: CreateKnowledgeItemPayload): CreateKnowledgeItemPayload {
  const sourceRunId = payload.source_run_id?.trim()
  const sanitized: CreateKnowledgeItemPayload = {
    ...payload,
    confidence: knowledgeSubmissionConfidence(payload.confidence),
  }
  if (sourceRunId) {
    sanitized.source_run_id = sourceRunId
  } else {
    delete sanitized.source_run_id
  }
  return sanitized
}

export function createKnowledgeItem(payload: CreateKnowledgeItemPayload) {
  return request<unknown>('/knowledge/items', {
    method: 'POST',
    body: JSON.stringify(sanitizeCreateKnowledgeItemPayload(payload)),
  }).then(assertKnowledgeItem)
}

export function reviewKnowledgeItem(itemId: string, payload: {
  action: 'APPROVE' | 'REJECT' | 'ARCHIVE'
  reviewer?: string
  note?: string
}) {
  return request<unknown>(`/knowledge/items/${itemId}/review`, {
    method: 'POST',
    body: JSON.stringify(payload),
  }).then(assertKnowledgeItem)
}

export function generateKnowledgeFromRun(runId: string, force = false) {
  return request<unknown>(`/knowledge/from-run/${runId}`, {
    method: 'POST',
    body: JSON.stringify({ force }),
  }).then(assertKnowledgeItem)
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

function requireBoolean(record: Record<string, unknown>, key: string, label: string) {
  if (typeof record[key] !== 'boolean') {
    throw new Error(`Unexpected ${label} response: missing ${key}`)
  }
}

function assertOptionalString(record: Record<string, unknown>, key: string, label: string) {
  const value = record[key]
  if (value !== undefined && value !== null && typeof value !== 'string') {
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

function assertKnowledgeItemBoundary(item: Record<string, unknown>) {
  requireString(item, 'evidence_usage', 'knowledge item')
  requireString(item, 'evidence_strength', 'knowledge item')
  requireBoolean(item, 'simulation_only', 'knowledge item')
  requireBoolean(item, 'is_real_trade', 'knowledge item')
  requireBoolean(item, 'strong_conclusion_allowed', 'knowledge item')

  const evidenceUsage = String(item.evidence_usage)

  if (item.strong_conclusion_allowed === true || isStrongEvidenceValue(item.evidence_strength) || isStrongEvidenceValue(evidenceUsage)) {
    throw new Error('Unexpected knowledge item response: knowledge evidence must not become a strong conclusion')
  }
  if (evidenceUsage !== 'supporting_only' || item.simulation_only !== true || item.is_real_trade !== false) {
    throw new Error('Unexpected knowledge item response: active knowledge must stay simulation-only supporting evidence')
  }
}

function assertKnowledgeItem(value: unknown): KnowledgeItem {
  const item = ensureRecord(value, 'knowledge item')
  requireString(item, 'item_id', 'knowledge item')
  requireNumber(item, 'version', 'knowledge item')
  requireString(item, 'status', 'knowledge item')
  requireString(item, 'category', 'knowledge item')
  assertOptionalString(item, 'source_run_id', 'knowledge item')
  assertOptionalString(item, 'source_audit_id', 'knowledge item')
  requireBoolean(item, 'source_run_verified', 'knowledge item')
  requireString(item, 'title', 'knowledge item')
  requireString(item, 'thesis', 'knowledge item')
  assertStringArray(item.evidence, 'knowledge item evidence')
  requireString(item, 'decision_impact', 'knowledge item')
  assertStringArray(item.guardrail_notes, 'knowledge item guardrail_notes')
  assertStringArray(item.tags, 'knowledge item tags')
  requireString(item, 'confidence', 'knowledge item')
  assertKnowledgeItemBoundary(item)
  requireString(item, 'created_at', 'knowledge item')
  requireString(item, 'updated_at', 'knowledge item')
  assertOptionalString(item, 'reviewed_at', 'knowledge item')
  assertOptionalString(item, 'reviewer', 'knowledge item')
  assertOptionalString(item, 'review_note', 'knowledge item')
  return value as KnowledgeItem
}

function assertKnowledgeItemList(value: unknown): KnowledgeItem[] {
  return ensureArray(value, 'knowledge item list').map(assertKnowledgeItem)
}

function assertKnowledgeSummary(value: unknown): KnowledgeSummary {
  const summary = ensureRecord(value, 'knowledge summary')
  requireNumber(summary, 'total', 'knowledge summary')
  requireNumber(summary, 'active_count', 'knowledge summary')
  requireNumber(summary, 'pending_count', 'knowledge summary')
  requireNumber(summary, 'rejected_count', 'knowledge summary')
  requireNumber(summary, 'archived_count', 'knowledge summary')
  requireNumber(summary, 'latest_version', 'knowledge summary')
  assertNumberRecord(summary.categories, 'knowledge summary categories')
  requireString(summary, 'updated_at', 'knowledge summary')
  return value as KnowledgeSummary
}
