import { PageSkeleton } from './Skeleton'

interface LoadingStateProps {
  label?: string
  helper?: string
}

/**
 * Shared loading placeholder used as the lazy-route Suspense fallback. Renders a
 * structured skeleton that approximates the standard page layout so first
 * navigation shows page structure instead of a bare centered spinner. The
 * `label`/`helper` text is exposed to assistive tech via a visually-hidden
 * announcement.
 */
export function LoadingState({
  label = '加载中...',
  helper = '正在等待数据，请稍候。',
}: LoadingStateProps) {
  return <PageSkeleton label={label} helper={helper} />
}
