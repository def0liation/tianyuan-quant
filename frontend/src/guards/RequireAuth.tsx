import { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { roleAllows, useOperatorContext, type OperatorRole } from '../store/operatorContext'
import { useBackendStore } from '../store/useBackendStore'

interface RequireAuthProps {
  children: ReactNode
  /** Minimum role required to access this route. Default: 'viewer' (everyone). */
  role?: OperatorRole
  /** Whether the backend must be connected. Default: false. */
  requireBackend?: boolean
  /** Redirect path when unauthorized. Default: '/' */
  fallbackPath?: string
}

/**
 * Route-level access guard.
 *
 * Checks:
 *  1. Backend connectivity (optional, off by default).
 *  2. Operator role against the minimum required role.
 *
 * If denied, redirects to `fallbackPath` with `replace`.
 */
export function RequireAuth({
  children,
  role = 'viewer',
  requireBackend = false,
  fallbackPath = '/',
}: RequireAuthProps) {
  const operator = useOperatorContext()
  const { isBackendConnected } = useBackendStore()

  if (requireBackend && !isBackendConnected) {
    return <Navigate to={fallbackPath} replace />
  }

  if (!roleAllows(operator.role, role)) {
    return <Navigate to={fallbackPath} replace />
  }

  return <>{children}</>
}
