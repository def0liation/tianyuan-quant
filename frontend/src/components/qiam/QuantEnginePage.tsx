import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { useAnalysisStore } from '../../store/useAnalysisStore'
import { SectionTitle } from '../common/SectionTitle'
import { Badge } from '../common/Badge'
import { Card } from '../common/Card'
import { FactorBarStack, MetricTile } from '../common/Material'
import { SourceBadge, SourceNote } from '../common/SourceBadge'
import { buildQiamProbabilityView } from '../../utils/conclusionInsights'
import { factorKind, qiamProbabilityKind } from '../../utils/dataProvenance'
import type { AnalysisRun, FactorSlicingResult, QiamRemediationItem } from '../../types'

function pct(value: number | null | undefined) {
  if (typeof value !== 'number' || Number.isNaN(value)) return 'N/A'
  return `${(value * 100).toFixed(1)}%`
}

function suitabilityStatus(value: string) {
  if (value === 'FAVORABLE') return 'PASS'
  if (value === 'NEUTRAL') return 'WARN'
  if (value === 'REVIEW_ONLY') return 'REVIEW_ONLY'
  return 'BLOCK_BUY'
}

function qiamOutputUnknown(qiam: AnalysisRun['qiam'], keys: string[]) {
  const output = qiam.llmOutput
  if (!output || typeof output !== 'object') return false
  return keys.some((key) => String(output[key] ?? '').toUpperCase() === 'UNKNOWN')
}

function scoreBarWidth(value: number | undefined) {
  if (typeof value !== 'number' || Number.isNaN(value)) return 0
  return Math.max(0, Math.min(100, value * 100))
}

function isPendingFactorRun(factor: FactorSlicingResult) {
  const source = String(factor.factorDataSource ?? factor.provenance?.sourceType ?? '').toUpperCase()
  return source.includes('PENDING') || (
    factor.factors.length === 0
    && factor.missingFactorData.some((item) => item.includes('尚未完成拉取'))
  )
}

function factorMissingExplanation(run: AnalysisRun, factor: FactorSlicingResult) {
  if (isPendingFactorRun(factor)) {
    if (run.status === 'CREATED') {
      return '当前运行只完成了任务创建，Quant Engine 尚未开始执行，因子切割仍是创建态占位数据。启动或重跑分析后会重新拉取行情、财务和资金流输入。'
    }
    if (run.status === 'RUNNING') {
      return '当前运行仍在执行中，因子切割还没有完成写回；待 Quant Engine 节点结束后会刷新为真实推导结果。'
    }
    return '当前运行的 factorSlicing 仍是 PENDING：Tushare 配置不会自动回填旧运行或异常运行；新建并启动分析后，dataSources.special_data / stk_factor 会先写入辅助数据，再由 Quant Engine 使用。'
  }

  if (factor.factors.length === 0) {
    return 'Quant Engine 已运行，但没有得到可用因子。通常是行情、财务、资金流或成交量输入全部不可用，无法形成 Value / Momentum / Liquidity 因子。'
  }

  return 'Quant Engine 已生成部分因子，但下列输入仍缺失，因此对应因子的置信度或稳定性被降级。'
}

function fallbackQiamRemediationItem(reason: string): QiamRemediationItem {
  const upperReason = reason.toUpperCase()
  if (reason.includes('QIAM') && reason.includes('尚未完成')) {
    return {
      reason,
      category: 'QIAM_INPUT',
      severity: 'BLOCKING',
      action: '重新运行 Quant Engine，确认 factor_slicing、factor_engine、calculation_authority 均已完成并写回；不要复用创建态或运行中的 QIAM 占位结果。',
      verification: '刷新运行后，QIAM missingData 不再包含该项，probabilitySource=RULE_DERIVED，Raw/Final 置信和分项评分不再全部为 0%。',
    }
  }
  if (upperReason.includes('DVG')) {
    return {
      reason,
      category: 'DVG',
      severity: upperReason.includes('BLOCKED') || upperReason.includes('REVIEW_ONLY') ? 'BLOCKING' : 'WARN',
      action: '查看 DVG 数据门禁详情，补齐 criticalMissingData 或解决数据冲突后重跑 DVG 与 Quant Engine。',
      verification: 'DVG qiamPermission 变为 ALLOW，QIAM 折扣原因中不再出现 DVG 折扣或硬阻断。',
    }
  }
  if (upperReason.includes('TECHNICALKLINE')) {
    return {
      reason,
      category: 'TECHNICAL_KLINE',
      severity: 'WARN',
      action: '重跑 Technical Kline Analyst，确认 Tushare 日/周/月 K 线为 LIVE 且日线样本不少于 30；若已有 canonical technicalKline，应优先使用该结果。',
      verification: 'QIAM technicalKlineConstraint confidence 高于 0.45，或不再出现 insufficient_data / low confidence 折扣。',
    }
  }
  return {
    reason,
    category: 'DATA_GAP',
    severity: 'WARN',
    action: '补齐该缺失数据源后重跑 Quant Engine；低频中长线模式下先确认该项是否应被 ignoredMissingData 排除。',
    verification: 'QIAM 折扣原因中该缺失项消失，discountFactor 回升。',
  }
}

function qiamRemediationItems(qiam: AnalysisRun['qiam']) {
  const backendItems = Array.isArray(qiam.remediationItems) ? qiam.remediationItems : []
  if (backendItems.length > 0) return backendItems
  return qiam.downgradeReasons.map(fallbackQiamRemediationItem)
}

function remediationCategoryLabel(category: string) {
  if (category === 'QIAM_INPUT') return 'QIAM 输入'
  if (category === 'DVG') return 'DVG 门禁'
  if (category === 'TECHNICAL_KLINE') return 'K 线'
  if (category === 'DATA_GAP') return '数据缺口'
  return category || 'MFE/MAE项'
}

function remediationStatus(item: QiamRemediationItem) {
  if (item.severity === 'BLOCKING') return 'BLOCK'
  if (item.severity === 'WARN') return 'WARN'
  return 'PASS'
}

function quantModeLabel(mode: string | undefined) {
  if (mode === 'HIGH_FREQ_SHORT') return '高频短线'
  if (mode === 'LOW_FREQ_MID_LONG') return '低频中长线'
  return mode || '未标记'
}

function quantModeHorizon(mode: string | undefined) {
  if (mode === 'HIGH_FREQ_SHORT') return '短线 / 盘中到数日'
  if (mode === 'LOW_FREQ_MID_LONG') return '中长线 / 数周到数月'
  return '历史运行未记录 Quant Engine 模式'
}

function formatWeights(weights: Record<string, number> | undefined) {
  if (!weights) return []
  return Object.entries(weights).map(([name, value]) => ({
    name,
    value: `${(value * 100).toFixed(0)}%`,
  }))
}

function bottomAdjustmentLabel(adjustment?: AnalysisRun['qiam']['bottomResearchAdjustment']) {
  if (!adjustment) return '未生成'
  const direction = String(adjustment.direction || 'NONE').toUpperCase()
  const before = adjustment.beforeFinalBuySuitability || '-'
  const after = adjustment.afterFinalBuySuitability || before
  if (adjustment.applied && direction === 'UP') return `上调一档 ${before} → ${after}`
  if (adjustment.applied && direction === 'DOWN') return `下调一档 ${before} → ${after}`
  if (direction === 'CONFLICT') return '证据冲突，未校准'
  if ((adjustment.blockedReasons || []).length > 0) return '正向校准已阻断'
  return '未校准'
}

function bottomAdjustmentStatus(adjustment?: AnalysisRun['qiam']['bottomResearchAdjustment']) {
  const direction = String(adjustment?.direction || 'NONE').toUpperCase()
  if (!adjustment) return 'WARN'
  if (adjustment.applied && direction === 'UP') return 'PASS'
  if (adjustment.applied && direction === 'DOWN') return 'WARN'
  if (direction === 'CONFLICT' || (adjustment.blockedReasons || []).length > 0) return 'WARN'
  return 'REVIEW_ONLY'
}

export function QuantEnginePage() {
  const { currentRun } = useAnalysisStore()

  if (!currentRun) return <div className="text-sm text-slate-500">加载中...</div>

  const factor = currentRun.factorSlicing
  const qiam = currentRun.qiam
  const probabilityView = buildQiamProbabilityView(currentRun)
  const factorSourceKind = factorKind(currentRun)
  const probabilitySourceKind = qiamProbabilityKind(currentRun)
  const factorExplanation = factorMissingExplanation(currentRun, factor)
  const quantEngine = currentRun.quantEngine
  const quantEngineMode = quantEngine?.mode || qiam.quantEngineMode || factor.quantEngineMode
  const parameterProfile = quantEngine?.parameterProfile || qiam.parameterProfile || factor.parameterProfile
  const factorWeights = formatWeights(parameterProfile?.factorWeights)
  const ignoredMissingData = quantEngine?.ignoredMissingData || qiam.ignoredMissingData || []
  const remediationItems = qiamRemediationItems(qiam)
  const bottomResearch = currentRun.mfeMaeResearch ?? currentRun.bottomResearch
  const bottomResearchAdjustment = qiam.mfeMaePathResearchAdjustment || qiam.bottomResearchAdjustment || bottomResearch?.qiamAdjustmentPreview
  const bottomResearchAdjustmentReasons = [
    ...(bottomResearchAdjustment?.blockedReasons || []),
    bottomResearchAdjustment?.reason,
  ].filter(Boolean).slice(0, 3)

  const probabilityData = probabilityView.rows
  const scoreItems = [
    { label: '体制适配', value: qiam.regimeFit, outputKeys: ['regime_fit', 'regimeFit'] },
    { label: '动量质量', value: qiam.momentumQuality, outputKeys: ['momentum_quality', 'momentumQuality'] },
    { label: '波动条件', value: qiam.volatilityCondition, outputKeys: ['volatility_condition', 'volatilityCondition'] },
    { label: '流动性信号', value: qiam.liquidityAdjustedSignal, outputKeys: ['liquidity_adjusted_signal', 'liquidityAdjustedSignal'] },
    { label: '决策影响', value: qiam.decisionEffect, outputKeys: ['decision_effect', 'decisionEffect'] },
    { label: '期望回报', value: qiam.expectedPayoffQuality, outputKeys: ['expected_payoff_quality', 'expectedPayoffQuality'] },
  ].map((item) => ({
    ...item,
    missing: item.value === 0 && qiamOutputUnknown(qiam, item.outputKeys),
  }))
  const hasMissingScores = scoreItems.some((item) => item.missing)

  return (
    <div className="space-y-6">
      <SectionTitle title="量化引擎" subtitle="因子切割、因子引擎、计算校验和 QIAM 适宜性的统一流水线。" dataMode={currentRun?.dataMode} />

      <Card title="模式参数">
        <div className="grid gap-4 lg:grid-cols-[220px_1fr_1fr]">
          <div className="space-y-1">
            <div className="text-xs font-medium text-slate-500">当前模式</div>
            <div className="text-lg font-semibold text-slate-950">{quantEngine?.label || quantModeLabel(String(quantEngineMode || ''))}</div>
            <div className="text-xs text-slate-500">{quantEngine?.horizon || quantModeHorizon(String(quantEngineMode || ''))}</div>
          </div>
          <div>
            <div className="mb-2 text-xs font-medium text-slate-500">核心因子权重</div>
            <div className="flex flex-wrap gap-2">
              {factorWeights.length > 0 ? factorWeights.map((item) => (
                <Badge key={item.name} status="PASS">{item.name} {item.value}</Badge>
              )) : <span className="text-sm text-slate-500">暂无参数权重</span>}
            </div>
          </div>
          <div>
            <div className="mb-2 text-xs font-medium text-slate-500">低频忽略的高频缺失</div>
            {ignoredMissingData.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {ignoredMissingData.map((item, index) => (
                  <Badge key={`${item}-${index}`} status="WARN">{item}</Badge>
                ))}
              </div>
            ) : (
              <div className="text-sm text-slate-500">
                {quantEngineMode === 'LOW_FREQ_MID_LONG'
                  ? '当前没有高频缺失项需要忽略。'
                  : quantEngineMode === 'HIGH_FREQ_SHORT'
                    ? '高频短线模式会把相关缺失纳入折扣。'
                    : '历史运行未记录模式，无法判断是否有忽略项。'}
              </div>
            )}
          </div>
        </div>
      </Card>

      {bottomResearch ? (
        <Card title="MFE/MAE路径研究摘要">
          <div className="grid gap-4 lg:grid-cols-[1fr_1fr_1.2fr_1.4fr]">
            <MetricTile label="MFE有利概率" value={pct(bottomResearch.mfeFavorableProbability ?? bottomResearch.bottomRepairProbability)} tone="success" />
            <MetricTile label="MAE跌破风险" value={pct(bottomResearch.maeBreachProbability ?? bottomResearch.breakdownRiskProbability)} tone="danger" />
            <div>
              <div className="text-xs font-medium text-slate-500">QIAM 校准</div>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <Badge status={bottomAdjustmentStatus(bottomResearchAdjustment)}>{bottomAdjustmentLabel(bottomResearchAdjustment)}</Badge>
              </div>
              {bottomResearchAdjustmentReasons.length > 0 ? (
                <div className="mt-2 text-xs leading-5 text-slate-500">
                  {bottomResearchAdjustmentReasons.join('；')}
                </div>
              ) : null}
            </div>
            <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs leading-5 text-slate-600">
              {bottomResearch.trendSynthesis?.mainConclusion || 'MFE/MAE路径研究仅提供概率型趋势证据。'} QIAM 只接受受控一档校准；不生成交易动作，也不绕过 DVG、Risk、QIAM、Execution。
            </div>
          </div>
        </Card>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[
          { label: '因子模式', value: factor.mode, status: 'PASS' },
          { label: '因子稳定性', value: pct(factor.factorStability), status: factor.factorStability > 0.7 ? 'PASS' : 'WARN' },
          { label: 'QIAM Raw', value: qiam.rawBuySuitability === 'FAVORABLE' ? '有利' : qiam.rawBuySuitability === 'NEUTRAL' ? '中性' : '不利', status: suitabilityStatus(qiam.rawBuySuitability) },
          { label: 'QIAM Final', value: qiam.finalBuySuitability === 'FAVORABLE' ? '有利' : qiam.finalBuySuitability === 'NEUTRAL' ? '中性' : '阻断', status: suitabilityStatus(qiam.finalBuySuitability) },
        ].map((item) => (
          <MetricTile
            key={item.label}
            label={item.label}
            value={item.value}
            helper={item.status}
            tone={item.status === 'PASS' ? 'success' : item.status === 'FAIL' ? 'danger' : 'warning'}
          />
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
        <Card title="因子详情" action={<SourceBadge kind={factorSourceKind} />}>
          <div className="space-y-3">
            {factor.factors.length > 0 ? factor.factors.map((f, i) => (
              <div key={i} className="flex items-center gap-4 rounded-md bg-slate-50 p-3">
                <div className="flex-1">
                  <div className="font-medium text-slate-900">{f.name}</div>
                  <div className="text-xs text-slate-500">权重: {(f.weight * 100).toFixed(0)}%</div>
                </div>
                <div className="text-right">
                  <div className="font-medium text-slate-900">{(f.contribution * 100).toFixed(2)}%</div>
                  <div className="text-xs text-slate-500">置信: {(f.confidence * 100).toFixed(0)}%</div>
                </div>
                <div className="h-2 w-24 rounded-full bg-slate-200">
                  <div className="h-2 rounded-full bg-cyan-500" style={{ width: `${f.confidence * 100}%` }} />
                </div>
              </div>
            )) : (
              <div className="rounded-md border border-amber-100 bg-amber-50 px-3 py-2 text-sm leading-6 text-amber-800">
                {factorExplanation}
              </div>
            )}
            {factor.factors.length > 0 ? (
              <FactorBarStack
                rows={factor.factors.map((f) => ({
                  label: f.name,
                  value: f.contribution,
                  helper: `权重 ${(f.weight * 100).toFixed(0)}% / 置信 ${(f.confidence * 100).toFixed(0)}%`,
                  tone: f.contribution >= 0 ? 'positive' : 'negative',
                }))}
                maxAbs={1}
              />
            ) : null}
          </div>
          <div className="mt-3">
            <div className="text-xs font-medium text-slate-500 mb-1">因子簇</div>
            <div className="flex flex-wrap gap-1">{factor.factorClusters.map((c, i) => <Badge key={i} status="PASS">{c}</Badge>)}</div>
          </div>
          <div className="mt-2 text-xs text-slate-500">
            市场分类: {factor.regimeClassification}
          </div>
          <SourceNote kind={factorSourceKind} note="因子详情优先使用 Tushare stk_factor；没有可用技术因子时才由行情、财务和资金流输入规则推算。" />
        </Card>

        <Card title="QIAM 概率分布" action={<SourceBadge kind={probabilitySourceKind} />}>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={probabilityData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="name" />
                <YAxis unit="%" domain={[0, 100]} />
                <Tooltip formatter={(value: number) => `${value.toFixed(1)}%`} />
                <Bar dataKey="value" radius={[4, 4, 0, 0]} fill="#0891b2" />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-2 grid grid-cols-3 gap-2 text-xs">
            {probabilityData.map((item) => (
              <MetricTile key={item.name} label={item.name} value={`${item.value.toFixed(1)}%`} className="!rounded-md !bg-slate-50 !p-2 !text-center !shadow-none" />
            ))}
          </div>
          <SourceNote kind={probabilitySourceKind} note={probabilityView.note} />
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="折扣系数">
          <div className="text-center">
            <div className="text-4xl font-bold text-slate-950">{qiam.discountFactor.toFixed(2)}</div>
            <div className="mt-2 text-sm text-slate-500">DVG 折扣 × 当前模式适用的缺失项</div>
            <div className="mt-3 flex justify-center gap-3">
              <Badge status={qiam.discountFactor >= 0.8 ? 'PASS' : 'WARN'}>
                {qiam.discountFactor >= 0.8 ? '信号可靠' : '信号折价'}
              </Badge>
            </div>
          </div>
        </Card>

        <Card title="模型置信与风险">
          <div className="space-y-2 text-sm">
            <div className="flex items-center justify-between">
              <span className="text-slate-600">Raw 置信</span>
              <span className="font-semibold">{pct(qiam.modelConfidenceRaw)}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-600">Final 置信</span>
              <span className="font-semibold">{pct(qiam.modelConfidenceFinal)}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-600">过拟合风险</span>
              <span className="font-semibold">{pct(qiam.overfitRisk)}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-600">分布漂移</span>
              <span className="font-semibold">{pct(qiam.distributionDrift)}</span>
            </div>
          </div>
        </Card>

        <Card title="分项评分">
          <div className="space-y-2 text-sm">
            {scoreItems.map((item) => (
              <div key={item.label} className="flex items-center justify-between">
                <span className="text-slate-500">{item.label}</span>
                <div className="flex items-center gap-2">
                  <div className="h-2 w-20 rounded-full bg-slate-100">
                    <div
                      className={`h-2 rounded-full ${item.missing ? 'bg-slate-300' : 'bg-cyan-500'}`}
                      style={{ width: `${scoreBarWidth(item.value)}%` }}
                    />
                  </div>
                  <span className={`font-mono text-xs font-semibold ${item.missing ? 'text-slate-500' : 'text-slate-950'}`}>
                    {item.missing ? '缺失' : pct(item.value)}
                  </span>
                </div>
              </div>
            ))}
            {hasMissingScores && (
              <div className="rounded-md border border-amber-100 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
                QIAM 对这些字段返回 UNKNOWN，按缺失展示；不是 0 分。请以下方缺失数据和折扣原因判断为什么没有可评分输入。
              </div>
            )}
          </div>
        </Card>
      </div>

      {(qiam.downgradeReasons.length > 0 || remediationItems.length > 0 || factor.missingFactorData.length > 0) && (
        <div className="grid gap-4 lg:grid-cols-2">
          {(qiam.downgradeReasons.length > 0 || remediationItems.length > 0) && (
            <Card title="QIAM 折扣原因">
              <div className="space-y-3">
                {qiam.downgradeReasons.length > 0 && (
                  <div className="space-y-1">
                    {qiam.downgradeReasons.map((r, i) => (
                      <div key={i} className="rounded border border-amber-100 bg-amber-50 p-2 text-sm text-amber-800">{r}</div>
                    ))}
                  </div>
                )}
                {remediationItems.length > 0 && (
                  <div className="border-t border-slate-100 pt-3">
                    <div className="text-xs font-semibold text-slate-700">如何解决</div>
                    <div className="mt-2 space-y-2">
                      {remediationItems.map((item, index) => (
                        <div key={`${item.category}-${index}`} className="rounded-md border border-slate-100 bg-slate-50 px-3 py-2 text-xs leading-5 text-slate-700">
                          <div className="mb-1 flex flex-wrap items-center gap-2">
                            <Badge status={remediationStatus(item)}>{remediationCategoryLabel(item.category)}</Badge>
                            <span className="break-words font-medium text-slate-900">{item.reason}</span>
                          </div>
                          <div className="break-words">处理：{item.action}</div>
                          <div className="mt-1 break-words text-slate-500">验证：{item.verification}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </Card>
          )}
          {factor.missingFactorData.length > 0 && (
            <Card title="缺失因子数据" action={<SourceBadge kind={factorSourceKind} />}>
              <div className="mb-3 rounded-md border border-rose-100 bg-rose-50 px-3 py-2 text-sm leading-6 text-rose-800">
                {factorExplanation}
              </div>
              <div className="space-y-1">
                {factor.missingFactorData.map((f, i) => (
                  <div key={i} className="flex items-center gap-2 rounded border border-rose-100 bg-rose-50 p-2 text-sm text-rose-800">
                    <div className="h-1.5 w-1.5 rounded-full bg-rose-500" />{f}
                  </div>
                ))}
              </div>
            </Card>
          )}
        </div>
      )}
    </div>
  )
}
