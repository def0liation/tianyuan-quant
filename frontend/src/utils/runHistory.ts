type RunHistoryItem = {
  runId?: string
  taskType?: string
}

const HIDDEN_HISTORY_TASK_TYPES = new Set(['P2_CLOSED_LOOP_SAMPLE'])

type RunHistoryVisibilityOptions = {
  preserveRunIds?: Array<string | null | undefined>
}

function preservedRunIds(options: RunHistoryVisibilityOptions) {
  return new Set(
    (options.preserveRunIds ?? [])
      .map((runId) => String(runId || '').trim())
      .filter(Boolean),
  )
}

export function isHiddenRunHistoryItem(run: RunHistoryItem, options: RunHistoryVisibilityOptions = {}) {
  const runId = String(run.runId || '').trim()
  if (runId && preservedRunIds(options).has(runId)) return false
  return HIDDEN_HISTORY_TASK_TYPES.has(String(run.taskType || '').trim())
}

export function visibleRunHistory<T extends RunHistoryItem>(history: T[], options: RunHistoryVisibilityOptions = {}) {
  return history.filter((run) => !isHiddenRunHistoryItem(run, options))
}
