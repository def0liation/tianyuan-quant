import { AnalysisRun, FinalWriterResult } from '../types'

export function buildFinalWriter(run: AnalysisRun): FinalWriterResult {
  if (run.killSwitch.level === 'HARD') {
    return {
      mode: 'HARD_RISK_FINAL_ONLY',
      finalAction: 'REJECT',
      humanConfirmationRequired: true,
      auditId: run.killSwitch.auditId,
      sections: [
        {
          title: '硬风险结论',
          content: 'Kill Switch HARD 已触发，所有交易路径已关闭，当前仅允许观察和复核。',
          riskLevel: 'HIGH',
          requiresConfirmation: true,
        },
      ],
    }
  }

  if (run.killSwitch.level === 'COMPLIANCE') {
    return {
      mode: 'COMPLIANCE_REFUSAL',
      finalAction: 'REJECT',
      humanConfirmationRequired: true,
      auditId: run.killSwitch.auditId,
      sections: [
        {
          title: '合规拒绝结论',
          content: '已触发合规红线，禁止所有交易相关执行，当前仅允许合规复核。',
          riskLevel: 'HIGH',
          requiresConfirmation: true,
        },
      ],
    }
  }

  return {
    mode: 'CONSERVATIVE',
    finalAction: run.finalAction,
    humanConfirmationRequired: true,
    auditId: run.finalWriter?.auditId ?? 'AUD_FW_AUTO',
    sections: [
      {
        title: '当前结论',
        content: '当前研究建议保持观察，必要时等待更完整的市场和数据验证。',
        riskLevel: 'MEDIUM',
        requiresConfirmation: true,
      },
      {
        title: '风险提示',
        content: 'QIAM raw 结果仅作为校准输入，不能直接作为交易决策。',
        riskLevel: 'MEDIUM',
        requiresConfirmation: true,
      },
    ],
  }
}
