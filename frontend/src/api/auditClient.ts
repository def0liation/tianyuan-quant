import { request } from './httpClient'
import { AuditLogEvent } from '../types'

export async function getAuditLog(runId: string) {
  return request<unknown>(`/analysis/runs/${runId}/audit`).then(assertAuditLogEvents)
}

function ensureRecord(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(`Unexpected ${label} response`)
  }
  return value as Record<string, unknown>
}

function requireString(record: Record<string, unknown>, key: string, label: string) {
  if (typeof record[key] !== 'string') {
    throw new Error(`Unexpected ${label} response: missing ${key}`)
  }
}

function assertAuditLogEvent(value: unknown): AuditLogEvent {
  const event = ensureRecord(value, 'audit log event')
  requireString(event, 'timestamp', 'audit log event')
  requireString(event, 'runId', 'audit log event')
  requireString(event, 'node', 'audit log event')
  requireString(event, 'eventType', 'audit log event')
  requireString(event, 'message', 'audit log event')
  requireString(event, 'statusBefore', 'audit log event')
  requireString(event, 'statusAfter', 'audit log event')
  requireString(event, 'inputHash', 'audit log event')
  requireString(event, 'outputHash', 'audit log event')
  requireString(event, 'auditId', 'audit log event')
  return value as AuditLogEvent
}

function assertAuditLogEvents(value: unknown): AuditLogEvent[] {
  if (!Array.isArray(value)) {
    throw new Error('Unexpected audit log response')
  }
  return value.map(assertAuditLogEvent)
}
