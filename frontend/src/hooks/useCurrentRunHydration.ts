import { useEffect, useMemo, useRef } from 'react'
import { useLocation } from 'react-router-dom'
import { useAnalysisStore } from '../store/useAnalysisStore'
import { useBackendStore } from '../store/useBackendStore'

const NON_ANALYSIS_RUN_QUERY_ROUTES = new Set(['/research-lab/backtest'])

function normalizeRunId(value: string | null) {
  const text = value?.trim() ?? ''
  return text.length > 0 ? text : ''
}

function queryRunId(pathname: string, search: string) {
  if (NON_ANALYSIS_RUN_QUERY_ROUTES.has(pathname)) return ''
  return normalizeRunId(new URLSearchParams(search).get('run_id'))
}

export function useCurrentRunHydration() {
  const location = useLocation()
  const { isBackendConnected, isCoreReady } = useBackendStore()
  const { currentRun, currentRunId, loadRunHistory, refreshRun } = useAnalysisStore()
  const inFlightKeyRef = useRef('')
  const linkedRunId = useMemo(
    () => queryRunId(location.pathname, location.search),
    [location.pathname, location.search],
  )

  useEffect(() => {
    if (!isBackendConnected || !isCoreReady) return

    if (linkedRunId) {
      if (currentRun && currentRunId === linkedRunId) return
      const attemptKey = `run:${linkedRunId}`
      if (inFlightKeyRef.current === attemptKey) return
      inFlightKeyRef.current = attemptKey
      refreshRun(linkedRunId)
        .catch(() => undefined)
        .finally(() => {
          if (inFlightKeyRef.current === attemptKey) {
            inFlightKeyRef.current = ''
          }
        })
      return
    }

    if (currentRun) return
    const attemptKey = `latest:${location.pathname}`
    if (inFlightKeyRef.current === attemptKey) return
    inFlightKeyRef.current = attemptKey
    loadRunHistory()
      .catch(() => undefined)
      .finally(() => {
        if (inFlightKeyRef.current === attemptKey) {
          inFlightKeyRef.current = ''
        }
      })
  }, [
    currentRun,
    currentRunId,
    isBackendConnected,
    isCoreReady,
    linkedRunId,
    loadRunHistory,
    location.pathname,
    refreshRun,
  ])
}
