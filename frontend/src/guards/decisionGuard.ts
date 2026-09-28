import { AnalysisRun, FinalAction, FinalWriterMode } from '../types'

export function getFinalActionCap(run: AnalysisRun): FinalAction {
  if (run.dvg.status === 'BLOCK_BUY') {
    return 'REJECT'
  }

  if (run.dvg.status === 'REVIEW_ONLY' || run.dvg.hallucinationRiskScore >= 60) {
    return 'REVIEW_ONLY'
  }

  if (run.killSwitch.level === 'HARD' || run.killSwitch.level === 'COMPLIANCE') {
    return 'REJECT'
  }

  return run.finalAction
}

export function canShowBuyCandidate(run: AnalysisRun): boolean {
  return run.dvg.status === 'PASS' && run.qiam.finalBuySuitability === 'FAVORABLE' && run.execution.executionReachability === 'REACHABLE' && run.killSwitch.level === 'NONE'
}

export function canShowAddCandidate(run: AnalysisRun): boolean {
  return run.dvg.status === 'PASS' && run.qiam.finalBuySuitability !== 'BLOCK_BUY' && run.execution.executionReachability === 'REACHABLE' && run.killSwitch.level === 'NONE'
}

export function canShowExecutionPlan(run: AnalysisRun): boolean {
  return run.execution.executionReachability === 'REACHABLE' && run.killSwitch.level === 'NONE' && run.signalOps.signalStatus !== 'WATCH'
}

export function canShowQiamRawAsPrimary(_run: AnalysisRun): boolean {
  return false
}

export function canPromoteSignalOps(run: AnalysisRun): boolean {
  return run.risk.complianceRedLines.length === 0 && run.dvg.status === 'PASS' && run.qiam.finalBuySuitability !== 'BLOCK_BUY'
}

export function canShowPaperProfitAsPositive(_run: AnalysisRun): boolean {
  return false
}

export function getBlockedReasons(run: AnalysisRun): string[] {
  const reasons: string[] = []
  if (run.dvg.status === 'BLOCK_BUY') {
    reasons.push('DVG BLOCK_BUY 已触发，所有买入链路被截断。')
  }

  if (run.killSwitch.level === 'HARD') {
    reasons.push('Kill Switch HARD 已触发，交易路径已关闭。')
  }

  if (run.killSwitch.level === 'COMPLIANCE') {
    reasons.push('合规红线触发，所有交易相关路径已关闭。')
  }

  if (run.execution.executionReachability === 'NOT_REACHABLE') {
    reasons.push('当前执行不可达，禁止生成普通交易计划。')
  }

  return reasons
}

export function getFinalWriterMode(run: AnalysisRun): FinalWriterMode {
  if (run.killSwitch.level === 'HARD') {
    return 'HARD_RISK_FINAL_ONLY'
  }

  if (run.killSwitch.level === 'COMPLIANCE') {
    return 'COMPLIANCE_REFUSAL'
  }

  return run.finalWriter?.mode ?? 'CONSERVATIVE'
}
