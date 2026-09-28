import { PermissionItem } from '../types'

export function buildPermissionMatrix(runState: any): PermissionItem[] {
  return [
    {
      capability: 'FULL_REPORT',
      state: runState.dvg.status === 'PASS' ? 'ALLOW' : 'REVIEW_ONLY',
      sourceNode: 'DVG',
      reason: runState.dvg.status === 'PASS' ? 'DVG 允许完整输出' : 'DVG 进入 REVIEW_ONLY',
      requiresConfirmation: runState.killSwitch.level !== 'NONE',
    },
    {
      capability: 'QIAM_POSITIVE',
      state: runState.qiam.finalBuySuitability === 'FAVORABLE' ? 'ALLOW' : 'BLOCKED',
      sourceNode: 'QIAM',
      reason: runState.qiam.finalBuySuitability === 'FAVORABLE' ? 'QIAM 最终结果偏向 FAVORABLE' : 'QIAM 结果被折扣或阻断',
      requiresConfirmation: true,
    },
    {
      capability: 'BUY_CANDIDATE',
      state: runState.execution.executionReachability === 'REACHABLE' && runState.killSwitch.level === 'NONE' ? 'ALLOW' : 'BLOCKED',
      sourceNode: 'Execution',
      reason: runState.execution.executionReachability === 'REACHABLE' ? '执行可达且未触发 Kill Switch' : '执行不可达或 Kill Switch 阻断',
      requiresConfirmation: true,
    },
  ]
}
