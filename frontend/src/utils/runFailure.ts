import { AnalysisRun } from '../types'

export function isLlmUnavailableRun(run?: AnalysisRun | null): boolean {
  if (!run) return false
  const reason = run.failReason ?? ''
  return (
    run.finalWriter?.llmFailed === true ||
    run.finalWriter?.mode === 'LLM_UNAVAILABLE' ||
    reason.includes('所有 LLM') ||
    reason.includes('大模型 API 不可用')
  )
}

export function buildRunFailureNotice(run: AnalysisRun, titleSuffix: string) {
  const failureDescription = normalizeRunFailureReason(run.failReason)
  if (run.failureCategory === 'MARKET_DATA_PREFLIGHT_BLOCKED') {
    return {
      title: `实时行情不可用 - ${titleSuffix}`,
      description:
        failureDescription ||
        '实时行情拉取失败，任务已在启动前阻断。失败节点：data_reliability_engine。本次未调用大模型 Agent。',
      tags: ['启动前已阻断', '失败节点 data_reliability_engine', '未调用大模型 Agent'],
    }
  }

  if (run.status === 'CANCELLED') {
    return {
      title: `分析运行已取消 - ${titleSuffix}`,
      description: failureDescription || '任务已由操作者取消。已完成节点结果仍保留，可从失败节点或取消节点重新运行。',
      tags: ['运行已取消', '已保留完成节点结果', '可从失败节点重试'],
    }
  }

  if (isLlmUnavailableRun(run)) {
    return {
      title: `大模型 API 不可用 - ${titleSuffix}`,
      description:
        failureDescription ||
        '所有 Agent LLM 调用均失败。当前显示仅为规则引擎计算值，非大模型智能分析结果。请检查 API 密钥和网络连接后重试。',
      tags: ['所有 Agent LLM 调用失败', '当前为规则引擎降级输出', '建议检查 API 配置后重试'],
    }
  }

  return {
    title: `分析运行异常 - ${titleSuffix}`,
    description:
      failureDescription ||
      '后端执行链未能完整收束。已完成节点的结果仍可查看，但本次运行状态不代表所有 Agent LLM 调用失败。',
    tags: ['运行未完整收束', '已保留完成节点结果', '建议刷新或重新运行'],
  }
}

function normalizeRunFailureReason(reason?: string) {
  if (!reason) return ''
  if (reason.startsWith('Analysis run recovered by watchdog')) {
    return reason
      .replace('Analysis run recovered by watchdog: status was RUNNING with no update since', '分析运行由 watchdog 自动恢复：任务长时间停留在 RUNNING，自')
      .replace('an unknown timestamp', '未知时间')
      .replace(/\.$/, ' 后没有更新。')
  }
  return reason
}
