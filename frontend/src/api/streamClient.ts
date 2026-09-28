import { EventSourcePolyfill } from 'event-source-polyfill'
import { reportError } from '../utils/errorReport'

export type StreamMessage = {
  event_type: string
  run_id?: string
  node_id?: string
  message?: string
  payload?: any
  audit_id?: string
  timestamp?: string
}

export type StreamHandlers = {
  onOpen?: () => void
  onMessage: (message: StreamMessage) => void
  onError?: (error: Event) => void
  onClose?: () => void
  onReconnect?: (attempt: number) => void
}

export type StreamOptions = {
  maxRetries?: number
  retryDelayMs?: number
  authToken?: string
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}

function optionalStringField(record: Record<string, unknown>, field: string) {
  const value = record[field]
  if (value === undefined || value === null) return undefined
  if (typeof value !== 'string') {
    throw new Error(`Unexpected SSE stream message: ${field} must be a string`)
  }
  return value
}

export function assertStreamMessage(value: unknown): StreamMessage {
  if (!isRecord(value)) {
    throw new Error('Unexpected SSE stream message')
  }
  const eventType = value.event_type
  if (typeof eventType !== 'string' || eventType.trim().length === 0) {
    throw new Error('Unexpected SSE stream message: missing event_type')
  }
  return {
    event_type: eventType,
    run_id: optionalStringField(value, 'run_id'),
    node_id: optionalStringField(value, 'node_id'),
    message: optionalStringField(value, 'message'),
    payload: value.payload,
    audit_id: optionalStringField(value, 'audit_id'),
    timestamp: optionalStringField(value, 'timestamp'),
  }
}

export function connectRunStream(runId: string, handlers: StreamHandlers, options: StreamOptions = {}) {
  const maxRetries = options.maxRetries ?? 5
  const retryDelayMs = options.retryDelayMs ?? 1200
  let isClosed = false
  let isTerminal = false
  let retryCount = 0
  let retryTimer: number | undefined
  let eventSource: EventSource | undefined
  const terminalEvents = new Set([
    'RUN_FINISHED',
    'RUN_FAILED',
    'RUN_CANCELLED',
    'RUN_STALE_RECOVERED',
    'RUN_NOT_FOUND',
    'RUN_REMOVED',
    'STREAM_TIMEOUT',
  ])

  const closeStream = () => {
    if (isClosed) return
    isClosed = true
    if (retryTimer) {
      window.clearTimeout(retryTimer)
    }
    eventSource?.close()
    handlers.onClose?.()
  }

  const connect = () => {
    eventSource?.close()
    const headers = streamHeaders(options)
    eventSource = new EventSourcePolyfill(
      streamUrl(runId),
      headers ? { headers } : undefined,
    ) as EventSource

    eventSource.onopen = () => {
      retryCount = 0
      handlers.onOpen?.()
    }

    eventSource.onmessage = (event) => {
      try {
        const data = assertStreamMessage(JSON.parse(event.data) as unknown)
        handlers.onMessage(data)
        if (terminalEvents.has(data.event_type)) {
          isTerminal = true
          closeStream()
        }
      } catch (error) {
        reportError('SSE 消息解析失败', error, { eventType: (event as { type?: string })?.type })
      }
    }

    eventSource.addEventListener('done', () => {
      isTerminal = true
      closeStream()
    })

    eventSource.onerror = (event) => {
      if (isClosed || isTerminal) return
      eventSource?.close()
      handlers.onError?.(event)
      if (retryCount >= maxRetries) {
        closeStream()
        return
      }
      retryCount += 1
      handlers.onReconnect?.(retryCount)
      retryTimer = window.setTimeout(connect, retryDelayMs * retryCount)
    }
  }

  connect()

  return () => {
    closeStream()
  }
}

function streamUrl(runId: string) {
  return `/api/analysis/runs/${encodeURIComponent(runId)}/stream`
}

function streamHeaders(options: StreamOptions) {
  const token = options.authToken?.trim()
  return token ? { Authorization: `Bearer ${token}` } : undefined
}
