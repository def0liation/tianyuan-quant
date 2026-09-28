import { getOperatorHeaders } from '../store/operatorContext'

const BASE_URL = '/api'

type RequestOptions = RequestInit & {
  timeoutMs?: number
}

export class ApiError extends Error {
  status: number
  statusText: string
  detail: unknown
  payload: unknown

  constructor(message: string, status: number, statusText: string, detail: unknown, payload: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.statusText = statusText
    this.detail = detail
    this.payload = payload
  }
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const controller = new AbortController()
  const { timeoutMs = 15000, signal: callerSignal, ...fetchOptions } = options
  let timedOut = false
  const abortFromCaller = () => controller.abort()
  if (callerSignal?.aborted) {
    controller.abort()
  } else {
    callerSignal?.addEventListener('abort', abortFromCaller, { once: true })
  }
  const timeout = setTimeout(() => {
    timedOut = true
    controller.abort()
  }, timeoutMs)
  const headers = new Headers(fetchOptions.headers)
  if (!(fetchOptions.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  Object.entries(getOperatorHeaders()).forEach(([key, value]) => headers.set(key, value))

  try {
    const response = await fetch(`${BASE_URL}${path}`, {
      ...fetchOptions,
      signal: controller.signal,
      headers,
    })
    const rawText = await response.text()
    const payload = parseResponsePayload(rawText)

    if (!response.ok) {
      const detail = payload.detail
      const rawMessage = payload.message
        || (typeof detail === 'string' ? detail : detail?.message)
        || rawText
        || response.statusText
      throw new ApiError(
        formatHttpErrorMessage(response.status, rawMessage, response.statusText),
        response.status,
        response.statusText,
        detail,
        payload,
      )
    }

    return payload as T
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      if (callerSignal?.aborted && !timedOut) {
        throw error
      }
      throw new Error('请求超时，请检查后端、行情接口或模型接口是否可用。')
    }
    if (error instanceof TypeError) {
      throw new Error('无法连接后端服务，请确认后端已启动；如果刚刚保存过代码，请等待后端重载完成后重试。')
    }
    throw error
  } finally {
    clearTimeout(timeout)
    callerSignal?.removeEventListener('abort', abortFromCaller)
  }
}

function parseResponsePayload(text: string) {
  if (!text) {
    return {}
  }
  try {
    return JSON.parse(text)
  } catch {
    return { message: text }
  }
}

function formatHttpErrorMessage(status: number, message: string, statusText: string) {
  const normalized = message.trim()
  if (status >= 500 && (!normalized || normalized === statusText || /internal server error/i.test(normalized))) {
    return '后端服务连接中断或正在重启，请稍后重试。'
  }
  return normalized || statusText || `HTTP ${status}`
}
