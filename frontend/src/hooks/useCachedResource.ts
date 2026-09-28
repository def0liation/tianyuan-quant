import { useCallback, useEffect, useRef, useState } from 'react'
import { dedupeInFlight } from '../api/requestCache'

const resourceCache = new Map<string, unknown>()

export interface CachedResource<T> {
  data: T | undefined
  error: unknown
  isLoading: boolean
  isValidating: boolean
  refresh: () => Promise<void>
}

/**
 * Stale-while-revalidate resource hook. On mount — and whenever `key` changes —
 * it renders any previously cached value for `key` immediately, then revalidates
 * in the background. Concurrent revalidations for the same key are de-duplicated
 * via {@link dedupeInFlight}. Pass `key = null` to disable fetching (e.g. when a
 * prerequisite such as the current run id is missing).
 *
 * This is an opt-in alternative to ad-hoc `useEffect` + `useState` fetching. It
 * does not touch the global request path, so polling/abort/timeout semantics
 * elsewhere are unaffected. The effect of caching is purely additive: revisiting
 * a page shows the last known value instantly instead of a blank loading state.
 */
export function useCachedResource<T>(key: string | null, fetcher: () => Promise<T>): CachedResource<T> {
  const [data, setData] = useState<T | undefined>(() =>
    key !== null ? (resourceCache.get(key) as T | undefined) : undefined,
  )
  const [error, setError] = useState<unknown>(undefined)
  const [isValidating, setIsValidating] = useState(false)

  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher

  const refresh = useCallback(async () => {
    if (key === null) return
    setIsValidating(true)
    setError(undefined)
    try {
      const value = await dedupeInFlight(`resource:${key}`, () => fetcherRef.current())
      resourceCache.set(key, value)
      setData(value)
    } catch (err) {
      setError(err)
    } finally {
      setIsValidating(false)
    }
  }, [key])

  useEffect(() => {
    if (key === null) {
      setData(undefined)
      setError(undefined)
      return
    }
    setData(resourceCache.get(key) as T | undefined)
    void refresh()
  }, [key, refresh])

  return {
    data,
    error,
    isLoading: data === undefined && isValidating,
    isValidating,
    refresh,
  }
}
