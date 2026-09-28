import { useSyncExternalStore } from 'react'

export type OperatorRole = 'viewer' | 'researcher' | 'operator' | 'admin'

export interface OperatorContext {
  id: string
  role: OperatorRole
  apiTokenSet: boolean
  apiTokenRevision: number
}

const STORAGE_KEY = 'super.operatorContext'
const API_TOKEN_STORAGE_KEY = 'super.operatorApiToken'
const DEFAULT_CONTEXT: OperatorContext = {
  id: 'local_workbench',
  role: 'admin',
  apiTokenSet: false,
  apiTokenRevision: 0,
}
const ROLES: OperatorRole[] = ['viewer', 'researcher', 'operator', 'admin']
const CHANGE_EVENT = 'super:operator-context-change'
let apiAuthToken = readStoredApiToken()
let apiAuthTokenRevision = 0
let cachedContext: OperatorContext | null = null

function readStoredApiToken() {
  if (typeof window === 'undefined') return ''
  try {
    return window.sessionStorage.getItem(API_TOKEN_STORAGE_KEY)?.trim() ?? ''
  } catch {
    return ''
  }
}

function writeStoredApiToken(token: string) {
  if (typeof window === 'undefined') return
  try {
    if (token) {
      window.sessionStorage.setItem(API_TOKEN_STORAGE_KEY, token)
    } else {
      window.sessionStorage.removeItem(API_TOKEN_STORAGE_KEY)
    }
  } catch {
    // Keep the in-memory token path working if session storage is unavailable.
  }
}

function isRole(value: string): value is OperatorRole {
  return ROLES.includes(value as OperatorRole)
}

function normalizeId(value: unknown) {
  const cleaned = String(value ?? '').trim()
  return (cleaned || DEFAULT_CONTEXT.id).slice(0, 64)
}

function normalizeRole(value: unknown): OperatorRole {
  const cleaned = String(value ?? '').trim().toLowerCase()
  return isRole(cleaned) ? cleaned : DEFAULT_CONTEXT.role
}

function sameContext(left: OperatorContext | null, right: OperatorContext) {
  return Boolean(
    left &&
      left.id === right.id &&
      left.role === right.role &&
      left.apiTokenSet === right.apiTokenSet &&
      left.apiTokenRevision === right.apiTokenRevision,
  )
}

function readStoredContextRaw(): OperatorContext {
  if (typeof window === 'undefined') return DEFAULT_CONTEXT
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return { ...DEFAULT_CONTEXT, apiTokenSet: Boolean(apiAuthToken), apiTokenRevision: apiAuthTokenRevision }
    const parsed = JSON.parse(raw) as Partial<OperatorContext>
    return {
      id: normalizeId(parsed.id),
      role: normalizeRole(parsed.role),
      apiTokenSet: Boolean(apiAuthToken),
      apiTokenRevision: apiAuthTokenRevision,
    }
  } catch {
    return { ...DEFAULT_CONTEXT, apiTokenSet: Boolean(apiAuthToken), apiTokenRevision: apiAuthTokenRevision }
  }
}

function readStoredContext(): OperatorContext {
  const next = readStoredContextRaw()
  if (sameContext(cachedContext, next)) {
    return cachedContext as OperatorContext
  }
  cachedContext = next
  return next
}

function emitChange() {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new Event(CHANGE_EVENT))
}

export function getOperatorContext(): OperatorContext {
  return readStoredContext()
}

export function setOperatorContext(next: Partial<OperatorContext>) {
  if (typeof window === 'undefined') return
  const current = readStoredContext()
  const value: OperatorContext = {
    id: normalizeId(next.id ?? current.id),
    role: normalizeRole(next.role ?? current.role),
    apiTokenSet: Boolean(apiAuthToken),
    apiTokenRevision: apiAuthTokenRevision,
  }
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ id: value.id, role: value.role }))
  emitChange()
}

export function getOperatorHeaders() {
  const context = getOperatorContext()
  const headers: Record<string, string> = {
    'X-Operator-ID': context.id,
    'X-Operator-Role': context.role,
  }
  const token = getOperatorApiToken()
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }
  return headers
}

export function getOperatorApiToken() {
  return apiAuthToken
}

export function setOperatorApiToken(token: string) {
  const nextToken = token.trim()
  if (nextToken !== apiAuthToken) {
    apiAuthTokenRevision += 1
  }
  apiAuthToken = nextToken
  writeStoredApiToken(nextToken)
  emitChange()
}

export function clearOperatorApiToken() {
  if (apiAuthToken) {
    apiAuthTokenRevision += 1
  }
  apiAuthToken = ''
  writeStoredApiToken('')
  emitChange()
}

export function roleAllows(role: OperatorRole, required: OperatorRole) {
  return ROLES.indexOf(role) >= ROLES.indexOf(required)
}

export function useOperatorContext() {
  return useSyncExternalStore(
    (onStoreChange) => {
      if (typeof window === 'undefined') return () => undefined
      window.addEventListener(CHANGE_EVENT, onStoreChange)
      window.addEventListener('storage', onStoreChange)
      return () => {
        window.removeEventListener(CHANGE_EVENT, onStoreChange)
        window.removeEventListener('storage', onStoreChange)
      }
    },
    readStoredContext,
    () => DEFAULT_CONTEXT,
  )
}

export const operatorRoles = ROLES
