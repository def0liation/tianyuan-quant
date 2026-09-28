interface SkeletonProps {
  className?: string
}

/**
 * Base shimmer block. Compose with width/height utility classes.
 * Always decorative — wrap groups in a `role="status"` container with an sr-only label.
 */
export function Skeleton({ className = '' }: SkeletonProps) {
  return (
    <div
      aria-hidden="true"
      className={`animate-pulse rounded-[var(--institution-radius-sm)] bg-[var(--md-sys-color-surface-container-high)] ${className}`}
    />
  )
}

interface SkeletonTextProps {
  lines?: number
  className?: string
}

/** A stack of text-line skeletons with a shorter final line. */
export function SkeletonText({ lines = 3, className = '' }: SkeletonTextProps) {
  return (
    <div className={`space-y-2 ${className}`} aria-hidden="true">
      {Array.from({ length: Math.max(1, lines) }).map((_, index) => (
        <Skeleton
          key={index}
          className={`h-3 ${index === lines - 1 ? 'w-8/12' : 'w-full'}`}
        />
      ))}
    </div>
  )
}

interface PageSkeletonProps {
  /** Number of metric tiles to mock in the summary row. */
  tiles?: number
  label?: string
  helper?: string
}

/**
 * Full-page loading placeholder that approximates the standard page layout
 * (header → metric tiles → content surface). Used as the lazy-route Suspense
 * fallback so first navigation shows structure instead of a centered spinner.
 */
export function PageSkeleton({ tiles = 4, label = '加载中...', helper }: PageSkeletonProps) {
  return (
    <div role="status" aria-busy="true" className="space-y-4">
      <span className="sr-only">{helper ? `${label} ${helper}` : label}</span>

      <div className="material-page-header">
        <div className="min-w-0 flex-1 space-y-3">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-7 w-64 max-w-full" />
          <Skeleton className="h-3 w-80 max-w-full" />
        </div>
        <div className="flex shrink-0 gap-2">
          <Skeleton className="h-9 w-24" />
          <Skeleton className="h-9 w-24" />
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: Math.max(1, tiles) }).map((_, index) => (
          <div key={index} className="material-metric-tile space-y-3">
            <Skeleton className="h-3 w-20" />
            <Skeleton className="h-7 w-28" />
            <Skeleton className="h-3 w-24" />
          </div>
        ))}
      </div>

      <div className="material-surface space-y-3">
        <Skeleton className="h-4 w-40" />
        <SkeletonText lines={4} />
      </div>
    </div>
  )
}
