import type { AnalysisRun, BackendHealth, PaperTradingResult } from '../types'

const SIM_ORDER_NAMESPACE = 'SIM_*'

function nonEmptyText(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

export function paperTradingBoundaryViolation(paperTrading?: Partial<PaperTradingResult> | null): string | null {
  if (!paperTrading) {
    return null
  }

  if (paperTrading.simulation_only === false) {
    return '纸面交易边界异常：simulation_only 必须保持 true。'
  }

  if (paperTrading.is_real_trade === true) {
    return '纸面交易边界异常：is_real_trade 必须保持 false。'
  }

  const namespace = nonEmptyText(
    paperTrading.allowed_order_namespace
      ?? paperTrading.orderNamespace
      ?? paperTrading.order_namespace,
  )
  if (namespace && namespace !== SIM_ORDER_NAMESPACE) {
    return '纸面交易边界异常：订单命名空间必须保持 SIM_*。'
  }

  const action = nonEmptyText(
    paperTrading.action
      ?? paperTrading.paper_action
      ?? paperTrading.latest_action,
  ).toUpperCase()
  if (action && !action.startsWith('SIM_')) {
    return '纸面交易边界异常：纸面交易动作必须使用 SIM_*。'
  }

  return null
}

export function assertBackendSafe(backendHealth?: BackendHealth): string | null {
  if (!backendHealth) {
    return '未检测到后端服务，当前仅允许 mock 模式。'
  }

  if (backendHealth.tradingEnabled) {
    return '后端安全异常：tradingEnabled 必须为 false，已禁用运行按钮。'
  }

  if (backendHealth.autoOrderEnabled) {
    return '后端安全异常：autoOrderEnabled 必须为 false，已禁用运行按钮。'
  }

  return null
}

export function assertFinalWriterSafe(run: AnalysisRun): string | null {
  if (run.qiam.rawBuySuitability === 'FAVORABLE' && run.qiam.finalBuySuitability !== 'FAVORABLE') {
    return 'QIAM raw FAVORABLE 不能直接进入最终主结论。'
  }

  const paperBoundaryViolation = paperTradingBoundaryViolation(run.paperTrading)
  if (paperBoundaryViolation) {
    return paperBoundaryViolation
  }

  if (run.paperTrading.simulatedProfit > 0) {
    return '纸面交易结果仅用于观察验证，不代表未来收益。'
  }

  if (run.execution.executionReachability === 'NOT_REACHABLE' && run.execution.allowedActions.includes('BUY_CANDIDATE')) {
    return 'Execution 不可达时不得显示普通交易计划。'
  }

  if (run.killSwitch.level === 'HARD' && run.killSwitch.blockedPaths.length > 0) {
    return 'Kill Switch HARD 已触发，对应路径必须截断。'
  }

  return null
}

export function assertQiamDisplaySafe(_run: AnalysisRun): boolean {
  return false
}

export function assertPaperTradingDisplaySafe(run: AnalysisRun): boolean {
  return paperTradingBoundaryViolation(run.paperTrading) === null
}
