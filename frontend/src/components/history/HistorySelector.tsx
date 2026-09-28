import { useCallback, useState } from 'react'
import { History, Loader2, Trash2 } from 'lucide-react'
import { useAnalysisStore } from '../../store/useAnalysisStore'
import { useBackendStore } from '../../store/useBackendStore'
import { deleteAnalysisRun } from '../../api/analysisClient'
import { roleAllows, useOperatorContext } from '../../store/operatorContext'
import { formatDateTime } from '../../utils/format'
import { reportError, reportWarning } from '../../utils/errorReport'
import { visibleRunHistory } from '../../utils/runHistory'

const HISTORY_RETRY_DELAY_MS = 500

function delay(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

export function HistorySelector() {
  const { currentRunId, runHistory, loadRunHistory, selectRun } = useAnalysisStore()
  const { isBackendConnected, isCoreReady } = useBackendStore()
  const operator = useOperatorContext()
  const [isLoading, setIsLoading] = useState(false)
  const [isOpen, setIsOpen] = useState(false)
  const [loadError, setLoadError] = useState<string | undefined>()
  const canLoadHistory = isBackendConnected && isCoreReady
  const canDeleteAnalysisRuns = roleAllows(operator.role, 'admin')
  const deleteDisabledReason = canDeleteAnalysisRuns
    ? undefined
    : `分析运行删除需要 admin 权限。当前角色：${operator.role}。`

  const loadHistory = useCallback(async () => {
    setIsLoading(true)
    setLoadError(undefined)
    try {
      await loadRunHistory()
    } catch {
      await delay(HISTORY_RETRY_DELAY_MS)
      try {
        await loadRunHistory()
      } catch (retryError) {
        reportWarning('History refresh skipped', { retryError })
        setLoadError(retryError instanceof Error ? retryError.message : '历史项目加载失败')
      }
    } finally {
      setIsLoading(false)
    }
  }, [loadRunHistory])

  const handleSelect = async (runId: string) => {
    if (runId === currentRunId) {
      setIsOpen(false)
      return
    }
    setIsLoading(true)
    try {
      await selectRun(runId)
    } catch (error) {
      reportError('选择运行记录失败', error)
    } finally {
      setIsLoading(false)
      setIsOpen(false)
    }
  }

  const handleDelete = async (e: React.MouseEvent, runId: string, stockCode: string) => {
    e.stopPropagation()
    if (!canDeleteAnalysisRuns) {
      reportWarning('分析运行删除权限不足', { role: operator.role })
      return
    }
    if (!window.confirm(`确定删除 ${stockCode} (${runId}) 的所有历史数据？此操作不可恢复。`)) return
    setIsLoading(true)
    try {
      await deleteAnalysisRun(runId)
      await loadRunHistory()
    } catch (error) {
      reportError('删除运行记录失败', error)
    } finally {
      setIsLoading(false)
    }
  }

  const visibleRuns = visibleRunHistory(runHistory, { preserveRunIds: [currentRunId] })
  const currentRun = visibleRuns.find((r) => r.runId === currentRunId)

  return (
    <div className="relative">
      <button
        type="button"
        aria-expanded={isOpen}
        onClick={() => {
          const next = !isOpen
          setIsOpen(next)
          if (next && canLoadHistory) {
            void loadHistory()
          }
        }}
        className="block w-full cursor-pointer rounded-[var(--institution-radius-md)] border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface-container-low)] px-4 py-3 text-left text-sm transition hover:bg-[var(--md-sys-color-surface-container)]"
      >
        <div className="flex items-center justify-between">
          <div>
            <span className="flex items-center gap-1 text-xs text-[var(--md-sys-color-on-surface-variant)]">
              <History size={14} />
              历史项目
            </span>
            <div className="mt-1 w-full truncate bg-transparent text-sm font-semibold text-[var(--md-sys-color-on-surface)] outline-none">
              {currentRun ? (
                <span>{currentRun.stockCode} · {currentRun.finalAction}</span>
              ) : isLoading ? (
                <span className="text-[var(--md-sys-color-on-surface-variant)]">加载中...</span>
              ) : (
                <span className="text-[var(--md-sys-color-on-surface-variant)]">选择历史项目</span>
              )}
            </div>
          </div>
          {isLoading && <Loader2 size={16} className="animate-spin text-[var(--md-sys-color-primary)]" />}
        </div>
      </button>

      {isOpen && (
        <>
          <div
            className="fixed inset-0 z-40"
            onClick={() => setIsOpen(false)}
          />
          <div
            data-testid="history-selector-menu"
            className="absolute left-0 top-[calc(100%+0.5rem)] z-50 w-[min(30rem,calc(100vw-2rem))] overflow-hidden rounded-[var(--institution-radius-md)] border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface)] shadow-[0_18px_48px_rgba(15,23,42,0.18)]"
          >
            <div className="flex items-center justify-between border-b border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface-container-low)] px-3 py-2">
              <div className="min-w-0">
                <div className="text-xs font-semibold text-[var(--md-sys-color-on-surface)]">历史项目</div>
                <div className="mt-0.5 truncate text-[11px] text-[var(--md-sys-color-on-surface-variant)]">
                  选择已有 run；删除仅限 admin。
                </div>
              </div>
              <div className="ml-3 flex shrink-0 items-center gap-2">
                {isLoading ? <Loader2 size={14} className="animate-spin text-[var(--md-sys-color-primary)]" /> : null}
                <span className="rounded-full border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface)] px-2 py-0.5 text-[11px] font-medium text-[var(--md-sys-color-on-surface-variant)]">
                  {visibleRuns.length} 项
                </span>
              </div>
            </div>
            {loadError ? (
              <div className="border-b border-red-100 bg-red-50 px-3 py-2 text-xs text-red-700">
                <div className="font-medium">历史项目刷新失败</div>
                <div className="mt-0.5 break-words">{loadError}</div>
                <button
                  type="button"
                  onClick={() => void loadHistory()}
                  className="mt-2 rounded-[var(--institution-radius-sm)] border border-red-200 bg-white px-2 py-1 font-semibold text-red-700 hover:bg-red-50"
                >
                  重试
                </button>
              </div>
            ) : null}
            {isLoading && visibleRuns.length === 0 ? (
              <div className="flex items-center justify-center py-8 text-sm text-[var(--md-sys-color-on-surface-variant)]">
                <Loader2 size={20} className="mr-2 animate-spin" />
                加载中...
              </div>
            ) : visibleRuns.length === 0 ? (
              <div className="py-8 text-center text-sm text-[var(--md-sys-color-on-surface-variant)]">
                暂无历史项目
              </div>
            ) : (
              <div className="max-h-80 overflow-y-auto overscroll-contain py-1">
                {visibleRuns.map((run) => {
                  const isSelected = run.runId === currentRunId
                  const isFailure = ['FAILED', 'STALE', 'CANCELLED'].includes(run.status)
                  const finalActionClass = run.finalAction === 'BUY_CANDIDATE' || run.finalAction === 'ADD_CANDIDATE'
                    ? 'bg-green-100 text-green-800'
                    : run.finalAction === 'REJECT'
                      ? 'bg-red-100 text-red-800'
                      : run.finalAction === 'REVIEW_ONLY' || run.finalAction === 'WAIT'
                        ? 'bg-amber-100 text-amber-800'
                        : 'bg-slate-100 text-slate-800'

                  return (
                    <div
                      key={run.runId}
                      data-testid={`history-selector-row-${run.runId}`}
                      className={`group grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2 border-l-2 px-2 py-1 transition-colors ${
                        isSelected
                          ? 'border-[var(--md-sys-color-primary)] bg-[var(--md-sys-color-primary-container)]'
                          : 'border-transparent hover:bg-[var(--md-sys-color-surface-container-low)]'
                      }`}
                    >
                      <button
                        type="button"
                        onClick={() => handleSelect(run.runId)}
                        className="min-w-0 rounded-[var(--institution-radius-sm)] px-2 py-2 text-left outline-none transition focus-visible:ring-2 focus-visible:ring-[var(--md-sys-color-primary)]"
                      >
                        <div className="flex min-w-0 items-center gap-2">
                          <span className="shrink-0 font-mono text-sm font-semibold tabular-nums text-[var(--md-sys-color-on-surface)]">
                            {run.stockCode}
                          </span>
                          {run.stockName ? (
                            <span className="min-w-0 truncate text-sm font-medium text-[var(--md-sys-color-on-surface)]">
                              {run.stockName}
                            </span>
                          ) : null}
                          {isFailure ? (
                            <span className="shrink-0 rounded-full bg-red-100 px-1.5 py-0.5 text-[10px] font-semibold leading-none text-red-700">
                              {run.status}
                            </span>
                          ) : null}
                          {isSelected ? (
                            <span className="shrink-0 rounded-full bg-[var(--md-sys-color-surface)] px-1.5 py-0.5 text-[10px] font-semibold leading-none text-[var(--md-sys-color-primary)]">
                              当前
                            </span>
                          ) : null}
                        </div>
                        <div className="mt-1 flex min-w-0 items-center gap-1 overflow-hidden text-[11px] leading-4 text-[var(--md-sys-color-on-surface-variant)]">
                          <span className="shrink-0 whitespace-nowrap tabular-nums">{formatDateTime(run.updatedAt || run.createdAt)}</span>
                          <span className="shrink-0 text-[var(--md-sys-color-outline)]">·</span>
                          <span className="shrink-0 whitespace-nowrap">{run.runMode}</span>
                          <span className="shrink-0 text-[var(--md-sys-color-outline)]">·</span>
                          <span className="min-w-0 truncate font-mono">{run.runId}</span>
                        </div>
                      </button>
                      <div className="flex shrink-0 items-center gap-1.5 pr-1">
                        <span className={`inline-flex max-w-28 items-center truncate rounded-full px-2 py-0.5 text-xs font-semibold ${finalActionClass}`}>
                          {run.finalAction}
                        </span>
                        <button
                          type="button"
                          onClick={(e) => handleDelete(e, run.runId, run.stockCode)}
                          disabled={!canDeleteAnalysisRuns}
                          aria-label={deleteDisabledReason ?? `删除 ${run.stockCode} 运行`}
                          title={deleteDisabledReason ?? '删除此运行'}
                          className="material-icon-button material-icon-button-standard !h-8 !w-8 opacity-75 transition group-hover:opacity-100"
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
