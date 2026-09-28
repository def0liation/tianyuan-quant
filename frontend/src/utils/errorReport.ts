/**
 * Unified error reporting service.
 * In development: logs to console.
 * In production: logs sanitized diagnostics locally until a dedicated
 * frontend error ingestion endpoint exists.
 */

const IS_DEV = typeof window !== 'undefined' && window.location.hostname === 'localhost'

type ErrorContext = Record<string, unknown>
const SENSITIVE_KEY_PATTERN = /(authorization|bearer|token|api[_-]?key|secret|password|credential)/i
const SENSITIVE_TEXT_PATTERN = /((?:authorization|bearer|token|api[_-]?key|secret|password|credential)\s*[:=]\s*)([^,;&\s"'}]+)/gi
const BEARER_VALUE_PATTERN = /(Bearer\s+)[A-Za-z0-9._~+/=-]+/gi

function formatContext(ctx?: ErrorContext): string {
  if (!ctx || Object.keys(ctx).length === 0) return ''
  try {
    return ' | ' + JSON.stringify(ctx)
  } catch {
    return ' | [unserializable context]'
  }
}

export function reportError(message: string, error?: unknown, ctx?: ErrorContext): void {
  const contextStr = formatContext(ctx)
  const errorDetail = error instanceof Error ? error.message : error != null ? String(error) : ''

  if (IS_DEV) {
    console.error(`[ErrorReport] ${message}${contextStr}`, errorDetail || '')
    return
  }

  // In production, strip stack traces and report only safe data
  const safePayload: Record<string, unknown> = {
    message: message.slice(0, 500),
    context: ctx != null ? sanitizeContext(ctx) : undefined,
  }
  if (errorDetail) {
    safePayload.error = redactSensitiveText(errorDetail, 300)
  }

  console.error('[ErrorReport]', {
    level: 'error',
    source: 'frontend',
    title: message.slice(0, 120),
    detail: safePayload,
  })
}

export function reportWarning(message: string, ctx?: ErrorContext): void {
  if (IS_DEV) {
    console.warn(`[WarnReport] ${message}${formatContext(ctx)}`)
    return
  }
  // Warnings are only logged locally; not sent to backend
}

function sanitizeContext(ctx: ErrorContext): ErrorContext {
  const sanitized: ErrorContext = {}
  for (const [key, value] of Object.entries(ctx)) {
    sanitized[key] = sanitizeValue(key, value)
  }
  return sanitized
}

function sanitizeValue(key: string, value: unknown, depth = 0): unknown {
  if (SENSITIVE_KEY_PATTERN.test(key)) {
    return '[redacted]'
  }
  if (value instanceof Error) {
    return redactSensitiveText(value.message, 200)
  }
  if (typeof value === 'string') {
    return redactSensitiveText(value, 300)
  }
  if (value == null || typeof value === 'number' || typeof value === 'boolean') {
    return value
  }
  if (Array.isArray(value)) {
    if (depth >= 3) return '[array]'
    return value.slice(0, 20).map((item, index) => sanitizeValue(String(index), item, depth + 1))
  }
  if (typeof value === 'object') {
    if (depth >= 3) return '[object]'
    const sanitized: ErrorContext = {}
    for (const [childKey, childValue] of Object.entries(value as Record<string, unknown>).slice(0, 50)) {
      sanitized[childKey] = sanitizeValue(childKey, childValue, depth + 1)
    }
    return sanitized
  }
  return String(value)
}

function redactSensitiveText(value: string, maxLength: number): string {
  const redacted = value
    .replace(BEARER_VALUE_PATTERN, '$1[redacted]')
    .replace(SENSITIVE_TEXT_PATTERN, '$1[redacted]')
  return redacted.length > maxLength ? redacted.slice(0, maxLength) + '...' : redacted
}
