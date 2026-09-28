/**
 * Coalesces concurrent identical async work behind a single in-flight promise,
 * keyed by a caller-supplied string. While a request for `key` is pending, any
 * additional callers receive the same promise instead of issuing a duplicate
 * request; the entry is cleared once the promise settles so later calls start
 * fresh.
 *
 * This generalizes the ad-hoc in-flight guards that previously lived inside
 * individual stores (e.g. the run-history loader). It performs pure
 * de-duplication only — it never serves data older than the current concurrent
 * request — so it is safe to apply without TTL/staleness concerns.
 */
const inFlight = new Map<string, Promise<unknown>>()

export function dedupeInFlight<T>(key: string, factory: () => Promise<T>): Promise<T> {
  const existing = inFlight.get(key)
  if (existing) {
    return existing as Promise<T>
  }
  const pending = (async () => {
    try {
      return await factory()
    } finally {
      inFlight.delete(key)
    }
  })()
  inFlight.set(key, pending)
  return pending
}
