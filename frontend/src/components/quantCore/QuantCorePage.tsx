import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { useSearchParams } from 'react-router-dom'
import { useAnalysisStore } from '../../store/useAnalysisStore'
import type {
  AnalysisRun,
  BottomResearchResult,
  MfeMaeConditionalQuantileEvaluation,
  QuantCoreInterpretation,
  QuantCorePathRiskCurvePoint,
} from '../../types'
import { buildQiamProbabilityView } from '../../utils/conclusionInsights'
import { qiamProbabilityKind } from '../../utils/dataProvenance'
import { Badge } from '../common/Badge'
import { Card } from '../common/Card'
import { FactorBarStack, InlineSparkline, MatrixHeatmap, MetricTile, SourceFreshnessPanel } from '../common/Material'
import { SectionTitle } from '../common/SectionTitle'
import { SourceBadge, SourceNote } from '../common/SourceBadge'
import { TechnicalKlineCaseGovernanceCard } from '../technical/TechnicalKlineCaseGovernanceCard'

type ScenarioBranch = {
  id: 'bullish' | 'base' | 'bearish'
  label: string
  premise: string
  probability: string
}

type CompactBottomProbabilityPoint = {
  tradeDate: string
  repairProb?: number | null
  breakdownRisk?: number | null
  predictionRepairProb?: number | null
  predictionBreakdownRisk?: number | null
  labelWindowEnd?: string | null
}

type BottomHorizonForecast = NonNullable<BottomResearchResult['horizonForecasts']>[number]

type FutureTrendChartPoint = {
  horizon: string
  horizonDays: number
  up: number | null
  down: number | null
  confidence: number | null
  status: string
}

type VisualDecisionPanel = NonNullable<QuantCoreInterpretation['visualDecisionPanel']>

type QuantCoreGovernance = {
  contextId: string
  evidenceStrength: 'MEDIUM' | 'LOW'
  blocker: string
  nextAction: string
  simulationOnly: boolean
  isRealTrade: boolean
  evidenceUsage: string
  strongConclusionAllowed: boolean
}

function quantEvidenceStrength(value: unknown): QuantCoreGovernance['evidenceStrength'] | null {
  const normalized = String(value || '').toUpperCase()
  if (normalized === 'LOW' || normalized === 'MEDIUM') return normalized
  if (['RESEARCH_GRADE', 'PRIMARY_EVIDENCE_READY'].includes(normalized)) return 'MEDIUM'
  if (['STRONG', 'HIGH', 'PRIMARY', 'PRIMARY_EVIDENCE', 'PASS', 'READY'].includes(normalized)) return 'MEDIUM'
  if (['UNKNOWN', 'SUPPORTING_ONLY', 'WEAK', 'WARN', 'WARNING', 'REVIEW', 'REVIEW_ONLY'].includes(normalized)) return 'LOW'
  return null
}

const QIAM_MODES = ['HIGH_FREQ_SHORT', 'LOW_FREQ_MID_LONG'] as const

type QiamMode = typeof QIAM_MODES[number]

type QiamModeRow = {
  mode: QiamMode
  label: string
  horizon: string
  factorFocus: string
  missingPolicy: string
  active: boolean
  status: string
  qiamPermission: string
  allowedOutputLevel: string
  effectiveMissing: string
  ignoredMissingData: string[]
}

const QIAM_MODE_PROFILES: Record<QiamMode, Pick<QiamModeRow, 'label' | 'horizon' | 'factorFocus' | 'missingPolicy'>> = {
  HIGH_FREQ_SHORT: {
    label: '高频短线适宜性',
    horizon: '短线 / 盘中到数日',
    factorFocus: '动量 / 流动性 / 波动率',
    missingPolicy: '二级行情、盘口深度、分时、逐笔和资金流分解缺失会进入适宜性折扣。',
  },
  LOW_FREQ_MID_LONG: {
    label: '低频中长线适宜性',
    horizon: '中长线 / 数周到数月',
    factorFocus: '估值 / 质量 / 动量',
    missingPolicy: '高频微观结构缺失只标记为不适用，不直接压低适宜性分数。',
  },
}

const DISPLAY_LABELS: Record<string, string> = {
  UNKNOWN: '未知',
  'N/A': '不适用',
  PASS: '通过',
  WARN: '需关注',
  WARNING: '需关注',
  REVIEW_ONLY: '仅复核',
  BLOCK_BUY: '阻断买入',
  BLOCKING_CONTEXT: '解释强冲突',
  BLOCK: '阻断',
  BLOCKED: '已阻断',
  BLOCKING: '阻断项',
  FAIL: '失败',
  ERROR: '异常',
  SKIPPED: '已跳过',
  RUNNING: '运行中',
  CREATED: '已创建',
  QUEUED: '排队中',
  COMPLETED: '已完成',
  DONE: '已完成',
  READY: '已就绪',
  NOT_AVAILABLE: '暂无可用数据',
  ACTIVE: '启用中',
  INACTIVE: '未启用',
  PENDING: '等待中',
  STALE: '已过期',
  INSUFFICIENT_SAMPLE: '样本不足',
  FALLBACK: '回退估算',
  FALLBACK_UNCALIBRATED: '未校准回退估算',
  ALLOW: '允许',
  ALLOW_WITH_DISCOUNT: '折扣后允许',
  FULL: '完整输出',
  READ_ONLY: '只读',
  HIGH_FREQ_SHORT: '高频短线',
  LOW_FREQ_MID_LONG: '低频中长线',
  FAVORABLE: '有利',
  NEUTRAL: '中性',
  UNFAVORABLE: '不利',
  BULLISH: '偏多',
  BEARISH: '偏空',
  SIDEWAYS: '震荡',
  MIXED: '分歧',
  MODERATE: '中等',
  PARTIAL: '部分',
  ALIGNED: '一致',
  ALIGNED_BULLISH: '偏多一致',
  ALIGNED_BEARISH: '偏空一致',
  TECHNICAL_INSUFFICIENT_DATA: '技术面数据不足',
  TECHNICAL_KLINE_LIVE_DAILY_DATA_MISSING: '技术K线实时日线数据缺失',
  TECHNICAL_KLINE_DAILY_COUNT_BELOW_30: '技术K线日线数量少于 30 条',
  TECHNICAL_TREND_CLOSE_MISSING: '技术趋势收盘价缺失',
  SUPPORT_RESISTANCE_SUPPORT20D_MISSING: '20 日支撑位数据缺失',
  SUPPORT_RESISTANCE_SUPPORT60D_MISSING: '60 日支撑位数据缺失',
  SUPPORT_RESISTANCE_DISTANCETOSUPPORT20D_MISSING: '20 日支撑距离缺失',
  SUPPORT_RESISTANCE_DISTANCETORESISTANCE20D_MISSING: '20 日阻力距离缺失',
  NEUTRAL_OR_MIXED: '中性或分歧',
  INSUFFICIENT_DATA: '数据不足',
  DIVERGED: '背离',
  DIVERGING: '背离',
  CONFLICT: '冲突',
  SUPPORTING_ONLY: '仅辅助',
  BOTTOM_REPAIR_ZONE: 'MFE有利区间',
  BOTTOM_REPAIR_WATCH: 'MFE观察',
  BREAKDOWN_RISK: 'MAE跌破风险',
  DISABLED_BY_RUN_MODE: '当前运行模式未启用',
  NOT_RUN_IN_FAST_MODE: '快速模式未运行',
  UPWARD_ALIGNED: '上行一致',
  DOWNWARD_ALIGNED: '下行一致',
  UP: '上调',
  DOWN: '下调',
  NONE: '无',
  HIGH: '高',
  MEDIUM: '中',
  LOW: '低',
  INFO: '提示',
  WAIT: '等待',
  HOLD: '持有',
  REDUCE: '减仓',
  REJECT: '拒绝',
  LIGHT_WATCH: '轻观察',
  BUY_CANDIDATE: '买入候选',
  ADD_CANDIDATE: '加仓候选',
  DEFENSIVE: '防御',
  SIGNAL_ONLY: '仅信号',
  PAPER_TEST_ONLY: '仅纸面测试',
  PAPER_TEST: '纸面测试',
  QUALIFIED: '已合格',
  TRADE_PLAN: '交易计划',
  MANUAL_CONFIRMED: '人工确认',
  EXECUTION_REVIEW: '执行复核',
  CLOSED: '已关闭',
  PATCH_REQUIRED: '需要修正',
  SOFT: '软阻断',
  HARD: '硬阻断',
  STANDARD: '标准',
  FAST_MODE: '快速模式',
  STANDARD_MODE: '标准模式',
  DEEP_MODE: '深度模式',
  REACHABLE: '可达',
  CONDITIONALLY_REACHABLE: '有条件可达',
  UNREACHABLE: '不可达',
  QUALITATIVE: '定性',
  QUALITATIVE_ONLY: '定性',
  REVIEW_SIMULATION_ONLY_INSUFFICIENT_CALIBRATION: '校准样本不足，仅模拟复核',
  READ_ONLY_NO_REAL_TRADE_PERMISSION_CHANGE: '只读解读，不改变真实交易权限',
  READ_ONLY_NO_PERMISSION_CHANGE: '只读解读，不改变权限',
  NORMAL: '正常',
  WATCH: '观察',
  THROTTLE: '限仓观察',
  AVOID_NEW_BUY: '避免新开仓',
  PRIORITY: '优先观察',
  FILTER: '过滤',
  QUANT_CORE_VISUAL_DECISION_PANEL_V1: '量化核心概率风险面板 v1',
  FUTURE_TREND_PROBABILITY_CALIBRATED: '趋势概率校正值',
  FUTURE_TREND_PROBABILITY_RAW: '趋势概率原始值',
  PATH_RISK_FILTER_PROXY: '路径风险过滤代理',
  MFE_MAE_RESEARCH_PROXY: 'MFE/MAE研究代理',
  CALIBRATED_UP_PROBABILITY: '上涨概率',
  RISK_REWARD_PROXY: '风险收益代理',
  MFE_MAE_PATH_RISK_FILTER_V1: 'MFE/MAE路径风险过滤 v1',
  DAILY_PROXY_NO_FUTURE_LABELS_V1: '日线代理，无未来标签',
  MFE_MAE_CONDITIONAL_QUANTILE_EVALUATION_V1: 'MFE/MAE经验条件分位数评估 v1',
  WALK_FORWARD_EMPIRICAL_CONDITIONED_QUANTILE_V1: '滚动窗口经验条件分位数',
  RESEARCH_ONLY_NO_PERMISSION_CHANGE: '研究只读，不改变权限',
  LABELED_HISTORICAL_ONLY_NOWCAST_EXCLUDED: '仅历史标签，排除nowcast',
}

const SCENARIO_BRANCH_KEYS = [
  ['bullish', '乐观情景', 'bull_case'],
  ['base', '基准情景', 'base_case'],
  ['bearish', '悲观情景', 'bear_case'],
] as const

const PLACEHOLDER_TEXT = new Set(['N/A', 'NONE', 'NULL', 'UNKNOWN', 'NOT_AVAILABLE'])

export function QuantCorePage() {
  const { currentRun } = useAnalysisStore()
  const [searchParams] = useSearchParams()
  const linkedRunId = (searchParams.get('run_id') || '').trim()
  const isLinkedRunPending = Boolean(linkedRunId && currentRun?.runId !== linkedRunId)

  if (!currentRun || isLinkedRunPending) {
    return (
      <div data-testid="quant-core-page-loading" className="text-sm text-slate-500">
        加载中...
        {linkedRunId ? <span className="ml-2 font-mono">{linkedRunId}</span> : null}
      </div>
    )
  }

  const core = currentRun.quantCore
  const marketTechnical = core?.marketTechnical ?? currentRun.marketTechnical
  const technical = marketTechnical?.technicalKline ?? currentRun.technicalKline ?? {}
  const bottom = core?.mfeMaeResearch ?? currentRun.mfeMaeResearch ?? core?.bottomResearch ?? currentRun.bottomResearch
  const factor = core?.factorSlicing ?? currentRun.factorSlicing
  const qiam = {
    ...((core?.qiam as AnalysisRun['qiam'] | undefined) ?? {}),
    ...currentRun.qiam,
  } as AnalysisRun['qiam']
  const quantEngine = {
    ...((core?.quantEngine as AnalysisRun['quantEngine'] | undefined) ?? {}),
    ...(currentRun.quantEngine ?? {}),
  }
  const scenario = readScenario(currentRun)
  const branches = scenarioBranches(scenario)
  const scenarioNotice = scenarioNoticeText(scenario)
  const bottomAdjustment = qiam.mfeMaePathResearchAdjustment ?? qiam.bottomResearchAdjustment ?? bottom?.qiamAdjustmentPreview
  const fiveDayForecast = bottomForecastForHorizon(bottom, 5)
  const bottomTrendData = bottomTrendLineData(bottom)
  const bottomTrendWindow = bottomTrendWindowInfo(bottom)
  const conditionalQuantileEvaluation = bottom?.modelDiagnostics?.conditionalQuantileEvaluation
  const activeQuantMode = normalizeQiamMode(quantEngine?.mode) ?? normalizeQiamMode(qiam.quantEngineMode) ?? normalizeQiamMode(factor?.quantEngineMode)
  const qiamModeRows = buildQiamModeRows(currentRun, activeQuantMode)
  const probabilityRun: AnalysisRun = { ...currentRun, qiam }
  const qiamProbability = buildQiamProbabilityView(probabilityRun)
  const probabilitySourceKind = qiamProbabilityKind(probabilityRun)
  const downgradeView = buildQiamDowngradeView(qiam, activeQuantMode)
  const coreInterpretation = core?.coreInterpretation
  const futureTrendProbability = coreInterpretation?.futureTrendProbability
  const futureTrendData = futureTrendProbabilityChartData(coreInterpretation, bottom)
  const visualDecisionPanel = buildVisualDecisionPanelView(coreInterpretation, bottom)
  const scenarioPermission = scenario.dvgPermission ?? currentRun.dvg?.scenarioPermission
  const coreRiskPolicy = coreInterpretation?.pathRiskFilter?.riskPolicy ?? bottom?.riskPolicy ?? bottom?.regimeState
  const sourceFreshness = buildQuantSourceFreshness(currentRun, marketTechnical, bottom, factor, qiam, probabilitySourceKind)
  const mfeMaeBars = buildMfeMaeBarRows(bottom, bottomAdjustment)
  const mfeMaeHeatmap = buildMfeMaeHeatmapRows(bottom, fiveDayForecast, conditionalQuantileEvaluation)
  const factorRows = buildFactorRows(factor)
  const qiamModeHeatmap = buildQiamModeHeatmapRows(qiamModeRows, qiam, factor)
  const probabilityBars = qiamProbability.rows.map((row) => ({
    label: row.name,
    value: scoreUnit(row.value),
    helper: `${row.value.toFixed(1)}%`,
    tone: row.name.includes('下') ? 'negative' as const : row.name.includes('上') ? 'positive' as const : 'data' as const,
  }))
  const quantGovernance = buildQuantCoreGovernance(
    currentRun,
    coreInterpretation,
    core,
    qiam,
    scenarioPermission,
    coreRiskPolicy,
  )

  return (
    <div className="space-y-6">
      <SectionTitle title="量化核心" subtitle="市场状态 / K线技术面 / MFE/MAE路径研究 / 量化适宜性 / 情景引擎" dataMode={currentRun.dataMode} eyebrow="模块" />

      <div data-testid="quant-core-governance" className="grid gap-2 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600 sm:grid-cols-2 xl:grid-cols-5">
        <span className="min-w-0 break-words">
          <span className="text-slate-500">ID：</span>
          <span data-testid="quant-core-governance-id" className="font-mono">{quantGovernance.contextId}</span>
        </span>
        <span className="min-w-0 break-words">
          <span className="text-slate-500">证据强度：</span>
          <span data-testid="quant-core-evidence-strength">{quantGovernance.evidenceStrength}</span>
        </span>
        <span className="min-w-0 break-words">
          <span className="text-slate-500">阻断：</span>
          <span data-testid="quant-core-blocker">{quantGovernance.blocker}</span>
        </span>
        <span className="min-w-0 break-words">
          <span className="text-slate-500">下一步：</span>
          <span data-testid="quant-core-next-action">{quantGovernance.nextAction}</span>
        </span>
        <span className="min-w-0 break-words font-medium text-slate-900" data-testid="quant-core-simulation-boundary">
          simulation_only={String(quantGovernance.simulationOnly)} / is_real_trade={String(quantGovernance.isRealTrade)} / evidence_usage={quantGovernance.evidenceUsage} / strong_conclusion_allowed={String(quantGovernance.strongConclusionAllowed)} / SIM_*
        </span>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="核心状态" value={displayCode(core?.status ?? statusFromQiam(qiam.finalBuySuitability))} status={statusFromQiam(qiam.finalBuySuitability)} />
        <MetricCard label="市场技术一致性" value={displayCode(marketTechnical?.alignment)} status={marketTechnical?.status ?? 'WARN'} />
        <MetricCard label="最终适宜性" value={suitabilityLabel(qiam.finalBuySuitability)} status={statusFromQiam(qiam.finalBuySuitability)} />
        <MetricCard label="情景权限" value={permissionLabel(scenarioPermission)} status={scenarioPermission ?? 'WARN'} />
      </div>

      <VisualDecisionPanelCard
        panel={visualDecisionPanel}
        riskCurve={coreInterpretation?.pathRiskFilter?.riskCurve}
      />

      <CoreDashboardCard
        interpretation={coreInterpretation}
        qiam={qiam}
        scenarioPermission={scenarioPermission}
        riskPolicy={coreRiskPolicy}
      />

      <SourceFreshnessPanel sources={sourceFreshness} />

      <FutureTrendProbabilityCard
        data={futureTrendData}
        futureTrendProbability={futureTrendProbability}
      />

      <EvidenceLayerHeader
        eyebrow="第一层证据"
        title="市场、K线与路径研究"
        description="先确认市场技术背景和 MFE/MAE 路径证据，只作为只读研究输入。"
      />

      <div className="grid gap-4 xl:grid-cols-[1.05fr_1fr]">
        <Card title="市场状态与 K线技术面">
          <div className="grid gap-4 lg:grid-cols-[1fr_1fr_1fr]">
            <InfoBlock label="市场情绪" value={displayCode(currentRun.market?.marketSentiment ?? marketTechnical?.market?.marketSentiment)} />
            <InfoBlock label="市场体制" value={displayCode(currentRun.market?.regimeClassification ?? marketTechnical?.market?.regimeClassification)} />
            <InfoBlock label="K线偏向" value={displayCode(technical.technicalBias)} />
          </div>
          <div className="mt-4 rounded-md border border-slate-200 bg-slate-50 p-3 text-sm leading-6 text-slate-600">
            {displayText(marketTechnical?.summaryForDownstream, '市场与技术面等待量化核心输出。')}
          </div>
        </Card>

        <Card title="MFE/MAE路径研究">
          {bottom ? (
            <div className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-3">
                <InfoBlock label="MFE有利概率" value={pct(bottom.mfeFavorableProbability ?? bottom.bottomRepairProbability)} />
                <InfoBlock label="MAE跌破风险" value={pct(bottom.maeBreachProbability ?? bottom.breakdownRiskProbability)} />
                <InfoBlock label="风险策略" value={displayCode(bottom.riskPolicy ?? bottom.regimeState)} />
              </div>
              <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(280px,0.9fr)]">
                <div className="rounded-md border border-slate-200 bg-white p-3">
                  <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">MFE/MAE direct labels</div>
                  <FactorBarStack rows={mfeMaeBars} maxAbs={1} />
                </div>
                <div className="rounded-md border border-slate-200 bg-white p-3">
                  <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">Evaluation matrix</div>
                  <MatrixHeatmap rows={mfeMaeHeatmap} />
                </div>
              </div>
              <div className={`rounded-md border p-3 ${fiveDayForecast ? 'border-blue-100 bg-blue-50/70' : 'border-amber-200 bg-amber-50'}`}>
                {fiveDayForecast ? (
                  <>
                    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <div className="text-xs font-semibold text-blue-950">未来5日预测</div>
                        <div className="mt-0.5 text-[11px] leading-4 text-blue-800">
                          仅展示已保存的 5 日 horizonForecast，不参与当前主周期双线。
                        </div>
                      </div>
                      <Badge status={bottomForecastStatus(fiveDayForecast)}>{bottomTrendBiasLabel(fiveDayForecast.trendBias)}</Badge>
                    </div>
                    <div className="grid gap-2 sm:grid-cols-3">
                      <InlineMetric label="上涨概率" value={pct(fiveDayForecast.trendProbabilities?.up)} />
                      <InlineMetric label="MFE有利" value={pct(fiveDayForecast.mfeFavorableProbability ?? fiveDayForecast.bottomRepairProbability)} />
                      <InlineMetric label="MAE风险" value={pct(fiveDayForecast.maeBreachProbability ?? fiveDayForecast.breakdownRiskProbability)} />
                    </div>
                    <div className="mt-2 text-[11px] leading-4 text-blue-800">
                      置信 {pct(fiveDayForecast.confidence)} · 样本 {countText(fiveDayForecast.sampleCount)}
                    </div>
                  </>
                ) : (
                  <>
                  <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <div className="text-xs font-semibold text-amber-950">未来5日预测</div>
                      <div className="mt-0.5 text-[11px] leading-4 text-amber-800">
                        当前运行未保存5日预测，重跑后生成多周期预测。
                      </div>
                    </div>
                    <Badge status="SKIPPED">未保存</Badge>
                  </div>
                  </>
                )}
              </div>
              <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-sm leading-6 text-slate-600">
                {displayText(bottom.trendSynthesis?.mainConclusion, 'MFE/MAE路径研究仅作为辅助概率证据。')}
              </div>
              <ConditionalQuantilePanel evaluation={conditionalQuantileEvaluation} />
              {bottomTrendData.length > 1 ? (
                <div className="rounded-md border border-slate-200 bg-white p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="text-xs font-semibold text-slate-900">MFE/MAE历史标签与最新概率</div>
                    <div className="flex flex-wrap items-center gap-3 text-[11px] text-slate-500">
                      <span className="inline-flex items-center gap-1">
                        <span className="h-0.5 w-5 rounded-full bg-teal-700" />
                        MFE有利标签
                      </span>
                      <span className="inline-flex items-center gap-1">
                        <span className="h-0.5 w-5 rounded-full bg-red-600" />
                        MAE触发标签
                      </span>
                      {bottomTrendData.some((item) => item.repairNowcast != null || item.breakdownNowcast != null) ? (
                        <span className="inline-flex items-center gap-1">
                          <span className="h-0.5 w-5 rounded-full border-t-2 border-dashed border-slate-400" />
                        最新代理概率
                        </span>
                      ) : null}
                    </div>
                  </div>
                  <div className="mt-2 h-40">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={bottomTrendData} margin={{ top: 8, right: 10, bottom: 0, left: -18 }}>
                        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                        <XAxis dataKey="date" minTickGap={20} tick={{ fontSize: 10 }} />
                        <YAxis domain={[0, 100]} tick={{ fontSize: 10 }} tickFormatter={(value) => `${value}%`} width={42} />
                        <Tooltip
                          formatter={(value: unknown, name: unknown) => [
                            typeof value === 'number' ? `${value.toFixed(1)}%` : String(value ?? ''),
                            String(name ?? ''),
                          ]}
                          labelFormatter={(_, payload) => String(payload?.[0]?.payload?.fullDate || '')}
                        />
                        <Line type="monotone" dataKey="repairHistorical" name="历史标签（MFE有利）" stroke="#0f766e" strokeWidth={2} dot={false} isAnimationActive={false} />
                        <Line type="monotone" dataKey="repairNowcast" name="最新代理概率（MFE有利）" stroke="#0f766e" strokeWidth={2} strokeDasharray="5 4" dot={{ r: 3 }} isAnimationActive={false} />
                        <Line type="monotone" dataKey="breakdownHistorical" name="历史标签（MAE触发）" stroke="#dc2626" strokeWidth={2} dot={false} isAnimationActive={false} />
                        <Line type="monotone" dataKey="breakdownNowcast" name="最新代理概率（MAE触发）" stroke="#dc2626" strokeWidth={2} strokeDasharray="5 4" dot={{ r: 3 }} isAnimationActive={false} />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                  <div className="mt-2 text-[11px] leading-4 text-slate-500">
                    工程派生展示：历史段为论文公式生成的 MFE/MAE 标签命中（0/100），虚线为当前日线 nowcast 代理概率；不是论文原图或已训练条件分位数曲线。{bottomTrendWindow}
                  </div>
                </div>
              ) : null}
              <Badge status={bottomAdjustmentStatus(bottomAdjustment)}>{bottomAdjustmentLabel(bottomAdjustment)}</Badge>
            </div>
          ) : (
            <EmptyState text="等待MFE/MAE路径研究输出" />
          )}
        </Card>
      </div>

      <TechnicalKlineCaseGovernanceCard run={currentRun} />

      <EvidenceLayerHeader
        eyebrow="第二层证据"
        title="量化适宜性与因子"
        description="展示 QIAM 模式、缺失数据折扣、适宜性概率分布和因子状态。"
      />

      <div className="grid gap-4">
        <Card title="量化适宜性与因子" action={<SourceBadge kind={probabilitySourceKind} />}>
          <div className="grid gap-3 sm:grid-cols-2">
            <InfoBlock label="量化模式" value={quantModeLabel(quantEngine?.mode ?? qiam.quantEngineMode ?? factor?.quantEngineMode)} />
            <InfoBlock label="折扣因子" value={numberText(qiam.discountFactor)} />
            <InfoBlock label="因子稳定性" value={pct(factor?.factorStability)} />
            <InfoBlock label="模型置信" value={pct(qiam.modelConfidenceFinal)} />
          </div>
          <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(280px,0.9fr)]">
            <div className="rounded-md border border-slate-200 bg-white p-3">
              <div className="mb-3 flex items-center justify-between gap-3">
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Factor bars</div>
                <Badge status={factorRows.length ? 'PASS' : 'WARN'}>{factorRows.length ? `${factorRows.length} factors` : 'no factors'}</Badge>
              </div>
              {factorRows.length ? <FactorBarStack rows={factorRows} maxAbs={factorMaxAbs(factorRows)} /> : <EmptyState text="等待因子贡献输出" />}
            </div>
            <div className="rounded-md border border-slate-200 bg-white p-3">
              <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">QIAM mode matrix</div>
              <MatrixHeatmap rows={qiamModeHeatmap} />
            </div>
          </div>
          <div className="mt-4 grid gap-3 lg:grid-cols-2">
            {qiamModeRows.map((row) => (
              <div
                key={row.mode}
                className={`rounded-md border p-3 text-sm ${
                  row.active
                    ? 'border-[var(--md-sys-color-primary)] bg-[var(--md-sys-color-primary-container)]/35'
                    : 'border-slate-200 bg-white'
                }`}
              >
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <div className="font-semibold text-slate-950">{row.label}</div>
                    <div className="mt-0.5 text-xs text-slate-500">{row.horizon}</div>
                  </div>
                  <Badge status={row.active ? row.status : 'SKIPPED'}>{row.active ? '当前生效' : '候选保留'}</Badge>
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs text-slate-600">
                  <div>因子重点：{row.factorFocus}</div>
                  <div>有效缺失：{row.effectiveMissing}</div>
                  <div>适宜性权限：{row.qiamPermission}</div>
                  <div>输出上限：{row.allowedOutputLevel}</div>
                </div>
                <div className="mt-2 text-xs leading-5 text-slate-600">{row.missingPolicy}</div>
                {row.ignoredMissingData.length > 0 ? (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {row.ignoredMissingData.slice(0, 4).map((item, index) => (
                      <span key={`${item}-${index}`} className="rounded border border-slate-200 bg-white px-2 py-0.5 text-[11px] text-slate-600">
                        不适用：{displayText(item)}
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
            ))}
          </div>
          <div className="mt-5 border-t border-slate-200 pt-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div>
                <div className="text-xs font-medium text-slate-500">适宜性概率分布</div>
                <div className="mt-1 text-sm text-slate-600">上涨 / 震荡 / 下跌三档概率已经合并到当前量化核心页展示。</div>
              </div>
              <Badge status={qiam.finalBuySuitability === 'FAVORABLE' ? 'PASS' : qiam.finalBuySuitability === 'BLOCK_BUY' ? 'BLOCK_BUY' : 'WARN'}>
                {suitabilityLabel(qiam.finalBuySuitability)}
              </Badge>
            </div>
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_220px]">
              <div className="h-56 min-w-0">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={qiamProbability.rows}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                    <XAxis dataKey="name" />
                    <YAxis unit="%" domain={[0, 100]} />
                    <Tooltip formatter={(value: number) => `${value.toFixed(1)}%`} />
                    <Bar dataKey="value" radius={[4, 4, 0, 0]} fill="#1a73e8" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
                <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">Direct labels</div>
                <FactorBarStack rows={probabilityBars} maxAbs={1} />
              </div>
            </div>
            <SourceNote kind={probabilitySourceKind} note={displayText(qiamProbability.note)} />
          </div>
          {downgradeView.applicable.length > 0 ? (
            <div className="mt-4 flex flex-wrap gap-2">
              {downgradeView.applicable.slice(0, 5).map((item, index) => (
                <Badge key={`${item}-${index}`} status="WARN">{displayText(item)}</Badge>
              ))}
            </div>
          ) : null}
          {downgradeView.notApplicable.length > 0 ? (
            <div className="mt-3 flex flex-wrap gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
              <span className="font-semibold text-slate-700">低频不需要</span>
              {downgradeView.notApplicable.slice(0, 5).map((item, index) => (
                <span key={`${item}-${index}`} className="rounded border border-slate-200 bg-white px-2 py-0.5">
                  {displayText(item)}
                </span>
              ))}
            </div>
          ) : null}
        </Card>
      </div>

      <EvidenceLayerHeader
        eyebrow="第三层证据"
        title="核心解读与情景细节"
        description="下沉展示解释维度、路径风险过滤、冲突标记和情景分支。"
      />

      <div className="grid gap-4">
        <CoreInterpretationCard interpretation={coreInterpretation} />

        <Card title="情景引擎">
          <div className="grid gap-3 lg:grid-cols-3">
            {branches.map((branch) => (
              <div key={branch.id} className="rounded-md border border-slate-200 bg-white p-3">
                <div className="mb-2 flex items-center justify-between gap-3">
                  <div className="text-sm font-medium text-slate-900">{branch.label}</div>
                  <Badge status={scenario.status ?? 'WARN'}>{branch.probability}</Badge>
                </div>
                <div className="text-xs leading-5 text-slate-600">{displayText(branch.premise)}</div>
              </div>
            ))}
          </div>
          {scenarioNotice ? (
            <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
              {scenarioNotice}
            </div>
          ) : null}
          {core?.warnings?.length ? (
            <div className="mt-4 flex flex-wrap gap-2">
              {core.warnings.slice(0, 6).map((item, index) => (
                <Badge key={`${item}-${index}`} status="WARN">{displayText(item)}</Badge>
              ))}
            </div>
          ) : null}
        </Card>
      </div>
    </div>
  )
}

function CoreDashboardCard({
  interpretation,
  qiam,
  scenarioPermission,
  riskPolicy,
}: {
  interpretation?: QuantCoreInterpretation | null
  qiam: AnalysisRun['qiam']
  scenarioPermission?: unknown
  riskPolicy?: unknown
}) {
  const actionBoundary = interpretation?.actionBoundary ?? 'READ_ONLY_NO_PERMISSION_CHANGE'
  const summary = displayText(
    interpretation?.summary,
    '等待量化核心汇总市场、路径、适宜性和情景证据。',
  )

  return (
    <Card title="核心驾驶舱" action={<Badge status="READ_ONLY">{displayCode(actionBoundary)}</Badge>}>
      <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
        <InfoBlock label="综合分" value={scoreText(interpretation?.overallScore)} />
        <InfoBlock label="综合偏向" value={displayCode(interpretation?.overallBias)} />
        <InfoBlock label="最终适宜性" value={suitabilityLabel(qiam.finalBuySuitability)} />
        <InfoBlock label="情景权限" value={permissionLabel(scenarioPermission)} />
        <InfoBlock label="风险策略" value={displayCode(riskPolicy, '等待路径风险')} />
        <InfoBlock label="只读边界" value={displayCode(actionBoundary)} />
      </div>
      <div className="mt-4 grid gap-3 xl:grid-cols-[minmax(0,1fr)_260px]">
        <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-sm leading-6 text-slate-600">
          {summary}
        </div>
        <div className="rounded-md border border-blue-100 bg-blue-50 px-3 py-2 text-xs leading-5 text-blue-900">
          <div className="font-semibold">权限说明</div>
          <div className="mt-1">
            量化核心仅做研究解释和证据汇总，不改变 Risk、Execution、SignalOps 或最终动作权限；趋势概率和路径风险保持 simulation-only / is_real_trade=false 语义。
          </div>
        </div>
      </div>
    </Card>
  )
}

function buildQuantCoreGovernance(
  run: AnalysisRun,
  interpretation: QuantCoreInterpretation | null | undefined,
  core: AnalysisRun['quantCore'],
  qiam: AnalysisRun['qiam'],
  scenarioPermission: unknown,
  riskPolicy: unknown,
): QuantCoreGovernance {
  const provenance = asRecord(core?.provenance) ?? {}
  const warnings = [
    ...arrayText(core?.warnings),
    ...arrayText(interpretation?.weightAdjustmentReasons),
  ]
  const missingData = arrayText(core?.missingData)
  const conflicts = Array.isArray(interpretation?.conflicts) ? interpretation.conflicts : []
  const blockingConflict = conflicts.find((item) => String(item.severity || '').toUpperCase() === 'BLOCKING_CONTEXT')
  const pathRisk = interpretation?.pathRiskFilter
  const pathRiskStatus = String(pathRisk?.status || '').toUpperCase()
  const normalizedRiskPolicy = String(riskPolicy || pathRisk?.riskPolicy || '').toUpperCase()
  const interpretationStatus = String(interpretation?.status || core?.status || '').toUpperCase()
  const weakInterpretationStatus = ['', 'UNKNOWN', 'SUPPORTING_ONLY', 'WEAK', 'WARN', 'WARNING', 'REVIEW', 'REVIEW_ONLY', 'SKIPPED'].includes(interpretationStatus)
  const qiamSuitability = String(qiam.finalBuySuitability || '').toUpperCase()
  const scenarioPermissionStatus = String(scenarioPermission || '').toUpperCase()
  const confidence = numericValue(interpretation?.confidence)
  const simulationOnly = core?.simulation_only !== false && run.dashboardSummary?.tradeBoundary?.simulationOnly !== false
  const isRealTrade = core?.is_real_trade === true || run.dashboardSummary?.tradeBoundary?.isRealTrade === true
  const evidenceUsage = String(core?.evidenceUsage || 'simulation_only')
  const strongConclusionAllowed = core?.strongConclusionAllowed === true
  const evidenceBoundaryBroken = evidenceUsage !== 'simulation_only' || strongConclusionAllowed
  const boundaryBroken = !simulationOnly || isRealTrade
  const reviewGateBlocked = boundaryBroken
    || evidenceBoundaryBroken
    || weakInterpretationStatus
    || warnings.length > 0
    || missingData.length > 0
    || Boolean(blockingConflict)
    || Boolean(pathRisk && pathRiskStatus !== 'READY')
    || ['THROTTLE', 'AVOID_NEW_BUY'].includes(normalizedRiskPolicy)
    || ['BLOCK_BUY', 'REVIEW_ONLY'].includes(qiamSuitability)
    || ['BLOCKED', 'REVIEW_ONLY'].includes(scenarioPermissionStatus)

  let evidenceStrength: QuantCoreGovernance['evidenceStrength'] = quantEvidenceStrength(core?.evidenceStrength) ?? 'LOW'
  if (!interpretation) {
    evidenceStrength = 'LOW'
  } else if (reviewGateBlocked) {
    evidenceStrength = 'LOW'
  } else if (
    interpretationStatus === 'PASS'
    && (confidence ?? 0) >= 0.7
    && pathRiskStatus === 'READY'
    && !blockingConflict
    && warnings.length === 0
    && missingData.length === 0
    && !['THROTTLE', 'AVOID_NEW_BUY'].includes(normalizedRiskPolicy)
  ) {
    evidenceStrength = 'MEDIUM'
  } else if (interpretationStatus === 'PASS' || (confidence ?? 0) >= 0.4) {
    evidenceStrength = 'MEDIUM'
  }

  let blocker = ''
  if (boundaryBroken) {
    blocker = 'QuantCore simulation-only boundary violated'
  } else if (evidenceBoundaryBroken) {
    blocker = 'QuantCore read-only evidence boundary violated'
  } else if (!interpretation) {
    blocker = '缺少 canonical quant_core.coreInterpretation'
  } else if (missingData.length > 0) {
    blocker = `缺失数据：${missingData[0]}`
  } else if (blockingConflict) {
    blocker = `阻断冲突：${displayText(blockingConflict.message)}`
  } else if (interpretationStatus === 'REVIEW_ONLY' || interpretationStatus === 'SKIPPED') {
    blocker = `核心解读状态 ${interpretationStatus}`
  } else if (pathRisk && pathRiskStatus !== 'READY') {
    blocker = `路径风险过滤 ${pathRiskStatus || 'UNKNOWN'}`
  } else if (normalizedRiskPolicy === 'AVOID_NEW_BUY' || normalizedRiskPolicy === 'THROTTLE') {
    blocker = `路径风险策略 ${normalizedRiskPolicy}`
  } else if (qiamSuitability === 'BLOCK_BUY' || qiamSuitability === 'REVIEW_ONLY') {
    blocker = `QIAM 最终适宜性 ${qiamSuitability}`
  } else if (scenarioPermissionStatus === 'BLOCKED' || scenarioPermissionStatus === 'REVIEW_ONLY') {
    blocker = `情景权限 ${scenarioPermissionStatus}`
  } else if (warnings.length > 0) {
    blocker = warnings[0]
  } else {
    blocker = '无阻断，保持人工复核'
  }

  const nextAction = blocker === '无阻断，保持人工复核'
    ? '进入 SignalOps simulation / backtest 仅模拟验证'
    : '补齐量化核心证据后再进入 SignalOps / backtest'

  return {
    contextId: String(provenance.auditId || provenance.audit_id || run.runId),
    evidenceStrength,
    blocker,
    nextAction,
    simulationOnly,
    isRealTrade,
    evidenceUsage,
    strongConclusionAllowed,
  }
}

function VisualDecisionPanelCard({
  panel,
  riskCurve,
}: {
  panel: VisualDecisionPanel
  riskCurve?: QuantCorePathRiskCurvePoint[]
}) {
  const direction = panel.directionProbability
  const payoff = panel.pathPayoffProxy
  const risk = panel.riskGradient
  const matrix = panel.probabilityOddsMatrix
  const upPct = boundedPercent(probabilityPercentNumber(direction.upProbability))
  const downPct = boundedPercent(probabilityPercentNumber(direction.downProbability))
  const sidewaysPct = boundedPercent(probabilityPercentNumber(direction.sidewaysProbability))
  const directionTotal = Math.max((upPct ?? 0) + (sidewaysPct ?? 0) + (downPct ?? 0), 1)
  const upWidth = ((upPct ?? 0) / directionTotal) * 100
  const sidewaysWidth = ((sidewaysPct ?? 0) / directionTotal) * 100
  const downWidth = ((downPct ?? 0) / directionTotal) * 100
  const mfeProxy = numericValue(payoff.mfeProxy)
  const maeProxy = numericValue(payoff.maeProxy)
  const payoffScale = Math.max(Math.abs(mfeProxy ?? 0), Math.abs(maeProxy ?? 0), 0.01)
  const mfeWidth = Math.min(100, (Math.abs(mfeProxy ?? 0) / payoffScale) * 100)
  const maeWidth = Math.min(100, (Math.abs(maeProxy ?? 0) / payoffScale) * 100)
  const riskGradientValues = (riskCurve ?? [])
    .map((item) => numericValue(item.riskGradient))
    .filter((value): value is number => value != null)
  const maxRiskGradient = numericValue(risk.maxRiskGradient)
  const sparkValues = riskGradientValues.length ? riskGradientValues : maxRiskGradient != null ? [0, maxRiskGradient] : [0, 0]
  const matrixZone = text(matrix.zone)?.toUpperCase() ?? 'INSUFFICIENT_DATA'
  const matrixUpPct = boundedPercent(probabilityPercentNumber(matrix.upProbability ?? direction.upProbability))
  const matrixRiskReward = numericValue(matrix.riskRewardProxy ?? payoff.riskRewardProxy)
  const matrixLeft = Math.max(8, Math.min(92, matrixUpPct ?? 8))
  const matrixBottom = matrixRiskReward == null
    ? 8
    : Math.max(8, Math.min(92, (Math.max(0, matrixRiskReward) / 3) * 100))

  return (
    <Card
      title="概率风险决策面板"
      action={(
        <div className="flex flex-wrap items-center gap-2">
          <Badge status={matrixZoneStatus(matrixZone)}>{displayCode(matrixZone)}</Badge>
          <Badge status="READ_ONLY">{displayCode(panel.actionBoundary)}</Badge>
        </div>
      )}
    >
      <div className="grid gap-4 xl:grid-cols-[1.1fr_1fr_0.9fr_1fr]">
        <div className="rounded-md border border-slate-200 bg-white p-3">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="text-xs font-semibold text-slate-950">方向概率</div>
              <div className="mt-0.5 text-[11px] text-slate-500">{countText(direction.horizonDays)}日主周期 · {displayCode(direction.source, '概率源未知')}</div>
            </div>
            <Badge status={direction.calibrationStatus === 'READY' ? 'PASS' : 'WARN'}>{displayCode(direction.calibrationStatus, '未校准')}</Badge>
          </div>
          <div className="h-8 overflow-hidden rounded-md border border-slate-200 bg-slate-100">
            <div className="flex h-full">
              <div className="bg-teal-700" style={{ width: `${upWidth}%` }} />
              <div className="bg-slate-300" style={{ width: `${sidewaysWidth}%` }} />
              <div className="bg-red-600" style={{ width: `${downWidth}%` }} />
            </div>
          </div>
          <div className="mt-3 grid gap-2 text-xs sm:grid-cols-3">
            <InlineMetric label="上涨" value={percentText(upPct)} />
            <InlineMetric label="震荡" value={percentText(sidewaysPct)} />
            <InlineMetric label="下跌" value={percentText(downPct)} />
          </div>
          <div className="mt-3 text-[11px] leading-5 text-slate-500">
            置信度 {pct(direction.confidence)} · {displayCode(direction.actionBoundary)}
          </div>
        </div>

        <div className="rounded-md border border-slate-200 bg-white p-3">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div className="text-xs font-semibold text-slate-950">MFE/MAE 盈亏空间代理</div>
            <Badge status="READ_ONLY">{displayCode(payoff.source, '代理')}</Badge>
          </div>
          <div className="grid grid-cols-[1fr_48px_1fr] items-center gap-2">
            <div className="flex h-8 items-center justify-end rounded-l-md bg-red-50">
              <div className="h-3 rounded-l-full bg-red-600" style={{ width: `${maeWidth}%` }} />
            </div>
            <div className="text-center text-[11px] font-semibold text-slate-500">0</div>
            <div className="flex h-8 items-center rounded-r-md bg-teal-50">
              <div className="h-3 rounded-r-full bg-teal-700" style={{ width: `${mfeWidth}%` }} />
            </div>
          </div>
          <div className="mt-3 grid gap-2 text-xs sm:grid-cols-2">
            <InlineMetric label="MFE proxy" value={formatProxyPct(mfeProxy)} />
            <InlineMetric label="MAE proxy" value={formatProxyPct(maeProxy)} />
            <InlineMetric label="赔率 proxy" value={numberText(payoff.riskRewardProxy)} />
            <InlineMetric label="期望路径 proxy" value={formatProxyPct(payoff.expectedPathValueProxy)} />
          </div>
        </div>

        <div className="rounded-md border border-slate-200 bg-white p-3">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div className="text-xs font-semibold text-slate-950">风险梯度</div>
            <Badge status={riskPolicyStatus(risk.riskPolicy)}>{displayCode(risk.riskPolicy, '风险未知')}</Badge>
          </div>
          <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
            <InlineSparkline values={sparkValues} tone={riskGradientTone(risk.riskPolicy)} height={38} />
          </div>
          <div className="mt-3 grid gap-2 text-xs">
            <InlineMetric label="下行风险分" value={scoreText(risk.downsideRiskScore)} />
            <InlineMetric label="最大梯度" value={numberText(risk.maxRiskGradient)} />
            <InlineMetric label="过滤状态" value={displayCode(risk.status, '等待路径风险')} />
          </div>
        </div>

        <div className="rounded-md border border-slate-200 bg-white p-3">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div className="text-xs font-semibold text-slate-950">概率 / 赔率矩阵</div>
            <Badge status={matrixZoneStatus(matrixZone)}>{displayCode(matrixZone)}</Badge>
          </div>
          <div className="relative h-44 overflow-hidden rounded-md border border-slate-200 bg-[linear-gradient(90deg,#fee2e2_0%,#f8fafc_48%,#ccfbf1_100%)]">
            <div className="absolute left-3 top-2 text-[10px] font-medium text-slate-600">高赔率</div>
            <div className="absolute bottom-2 left-3 text-[10px] font-medium text-slate-600">低上涨概率</div>
            <div className="absolute bottom-2 right-3 text-[10px] font-medium text-slate-600">高上涨概率</div>
            <div
              className="absolute flex -translate-x-1/2 translate-y-1/2 flex-col items-center gap-1"
              style={{ left: `${matrixLeft}%`, bottom: `${matrixBottom}%` }}
            >
              <span className={`h-3 w-3 rounded-full ring-4 ring-white ${matrixZoneDotClass(matrixZone)}`} />
              <span className="rounded-md bg-white/90 px-2 py-0.5 text-[10px] font-semibold text-slate-800 shadow-sm">
                {displayCode(matrixZone)}
              </span>
            </div>
          </div>
          <div className="mt-3 grid gap-2 text-xs sm:grid-cols-2">
            <InlineMetric label={displayCode(matrix.xAxis, '上涨概率')} value={percentText(matrixUpPct)} />
            <InlineMetric label={displayCode(matrix.yAxis, '赔率代理')} value={numberText(matrixRiskReward)} />
          </div>
        </div>
      </div>
      <div className="mt-4 rounded-md border border-blue-100 bg-blue-50 px-3 py-2 text-xs leading-5 text-blue-900">
        本面板只合并方向概率、MFE/MAE代理、风险梯度和概率赔率分区用于解释展示；simulation-only / is_real_trade=false，不改变 QIAM、SignalOps、Execution 或 finalAction。
      </div>
    </Card>
  )
}

function EvidenceLayerHeader({
  eyebrow,
  title,
  description,
}: {
  eyebrow: string
  title: string
  description: string
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3 border-t border-slate-200 pt-5">
      <div>
        <div className="text-[11px] font-semibold uppercase tracking-wide text-[var(--md-sys-color-primary)]">{eyebrow}</div>
        <div className="mt-1 text-lg font-semibold text-slate-950">{title}</div>
      </div>
      <div className="max-w-2xl text-sm leading-6 text-slate-500">{description}</div>
    </div>
  )
}

function MetricCard({ label, value, status }: { label: string; value: string; status: unknown }) {
  const statusCode = String(status ?? 'WARN')
  return (
    <MetricTile
      label={label}
      value={value}
      helper={<Badge status={statusCode}>{displayCode(statusCode)}</Badge>}
      tone={metricToneForStatus(statusCode)}
      className="!rounded-lg !p-3 !shadow-none"
    />
  )
}

function metricToneForStatus(status: string): 'primary' | 'neutral' | 'success' | 'warning' | 'danger' | 'info' | 'data' {
  const normalized = status.toUpperCase()
  if (['PASS', 'READY', 'FAVORABLE', 'ALLOW'].includes(normalized)) return 'success'
  if (['FAIL', 'ERROR', 'BLOCK', 'BLOCKED', 'BLOCK_BUY'].includes(normalized)) return 'danger'
  if (['WARN', 'REVIEW_ONLY', 'NEUTRAL', 'MIXED'].includes(normalized)) return 'warning'
  return 'neutral'
}

function InfoBlock({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
      <div className="text-xs font-medium text-slate-500">{label}</div>
      <div className="mt-1 break-words text-sm font-semibold text-slate-950">{value}</div>
    </div>
  )
}

function EmptyState({ text }: { text: string }) {
  return <div className="rounded-md border border-dashed border-slate-200 bg-slate-50 p-4 text-sm text-slate-500">{text}</div>
}

function CoreInterpretationCard({ interpretation }: { interpretation?: QuantCoreInterpretation | null }) {
  const weightAdjustmentReasons = Array.isArray(interpretation?.weightAdjustmentReasons)
    ? interpretation.weightAdjustmentReasons
    : []
  const dimensions = Array.isArray(interpretation?.dimensions) ? interpretation.dimensions : []
  const conflicts = Array.isArray(interpretation?.conflicts) ? interpretation.conflicts : []
  const riskFlags = Array.isArray(interpretation?.riskFlags) ? interpretation.riskFlags : []

  return (
    <Card title="核心解读">
      {interpretation ? (
        <div className="space-y-4">
          <div className="grid gap-3 md:grid-cols-4">
            <InfoBlock label="综合分" value={scoreText(interpretation.overallScore)} />
            <InfoBlock label="综合偏向" value={displayCode(interpretation.overallBias)} />
            <InfoBlock label="证据置信度" value={pct(interpretation.confidence)} />
            <InfoBlock label="解释边界" value={displayCode(interpretation.actionBoundary)} />
          </div>
          <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-sm leading-6 text-slate-600">
            {displayText(interpretation.summary)}
          </div>
          <PathRiskFilterPanel pathRiskFilter={interpretation.pathRiskFilter} />
          {interpretation.weightAdjusted && weightAdjustmentReasons.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {weightAdjustmentReasons.slice(0, 4).map((item, index) => (
                <Badge key={`${item}-${index}`} status="WARN">{displayText(item)}</Badge>
              ))}
            </div>
          ) : null}
          <div className="grid gap-3 lg:grid-cols-5">
            {dimensions.map((item) => {
              const dimensionScore = numericValue(item.score) ?? 0
              const evidenceItems = Array.isArray(item.evidence) ? item.evidence : []
              const warningItems = Array.isArray(item.warnings) ? item.warnings : []
              return (
                <div key={item.key} className="rounded-md border border-slate-200 bg-white p-3">
                  <div className="flex min-h-[44px] items-start justify-between gap-2">
                    <div>
                      <div className="text-sm font-semibold text-slate-950">{item.label}</div>
                      <div className="mt-0.5 text-[11px] text-slate-500">权重 {pct(item.weight)} · 置信 {pct(item.confidence)}</div>
                    </div>
                    <Badge status={biasStatus(item.bias)}>{displayCode(item.bias)}</Badge>
                  </div>
                  <div className="mt-3 h-2 rounded-full bg-slate-100">
                    <div className="h-2 rounded-full bg-[var(--md-sys-color-primary)]" style={{ width: `${Math.max(0, Math.min(100, dimensionScore))}%` }} />
                  </div>
                  <div className="mt-2 text-xs font-semibold text-slate-900">{scoreText(item.score)}</div>
                  <div className="mt-2 min-h-[40px] text-[11px] leading-5 text-slate-600">
                    {displayText(evidenceItems[0], warningItems[0] ?? '等待维度证据')}
                  </div>
                </div>
              )
            })}
          </div>
          {conflicts.length > 0 ? (
            <div className="grid gap-2 lg:grid-cols-2">
              {conflicts.map((item, index) => {
                const evidenceItems = Array.isArray(item.evidence) ? item.evidence : []
                return (
                  <div key={`${item.key}-${index}`} className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-900">
                    <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
                      <span className="font-semibold">{displayText(item.message)}</span>
                      <Badge status={conflictStatus(item.severity)}>{displayCode(item.severity)}</Badge>
                    </div>
                    <div>{evidenceItems.map((evidence) => displayText(evidence)).join(' · ')}</div>
                  </div>
                )
              })}
            </div>
          ) : null}
          {riskFlags.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {riskFlags.slice(0, 8).map((item, index) => (
                <Badge key={`${item}-${index}`} status={item === 'READ_ONLY_NO_PERMISSION_CHANGE' ? 'READ_ONLY' : 'WARN'}>{displayText(item)}</Badge>
              ))}
            </div>
          ) : null}
        </div>
      ) : (
        <EmptyState text="等待核心解读输出" />
      )}
    </Card>
  )
}

function PathRiskFilterPanel({ pathRiskFilter }: { pathRiskFilter?: QuantCoreInterpretation['pathRiskFilter'] }) {
  if (!pathRiskFilter) return null
  const proxy = pathRiskFilter.mfeMaeProxy ?? {}
  const riskCurve = Array.isArray(pathRiskFilter.riskCurve) ? pathRiskFilter.riskCurve : []
  const chartData = riskCurve.map((item) => ({
    drawdownLabel: `${numberText(item.drawdownPct)}%`,
    riskPotential: item.riskPotential,
    riskGradient: item.riskGradient,
  }))
  const evidence = Array.isArray(pathRiskFilter.evidence) ? pathRiskFilter.evidence : []
  const warnings = Array.isArray(pathRiskFilter.warnings) ? pathRiskFilter.warnings : []
  const limitations = Array.isArray(pathRiskFilter.limitations) ? pathRiskFilter.limitations : []

  return (
    <div className="rounded-md border border-slate-200 bg-white p-3">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="text-sm font-semibold text-slate-950">MFE/MAE 路径风险过滤</div>
          <div className="mt-0.5 text-[11px] leading-4 text-slate-500">
            {displayCode(pathRiskFilter.method)} · {countText(pathRiskFilter.horizonDays)}日窗口 · 只读解释
          </div>
        </div>
        <Badge status={riskPolicyStatus(pathRiskFilter.riskPolicy)}>{displayCode(pathRiskFilter.riskPolicy)}</Badge>
      </div>
      <div className="grid gap-3 md:grid-cols-4">
        <InfoBlock label="过滤状态" value={displayCode(pathRiskFilter.status)} />
        <InfoBlock label="下行风险分" value={scoreText(pathRiskFilter.downsideRiskScore)} />
        <InfoBlock label="MFE代理" value={formatProxyPct(proxy.mfeProxy)} />
        <InfoBlock label="MAE代理" value={formatProxyPct(proxy.maeProxy)} />
      </div>
      <div className="mt-3 grid gap-3 lg:grid-cols-[minmax(0,1fr)_220px]">
        <div className="h-44 min-w-0 rounded-md border border-slate-100 bg-slate-50/60 p-2">
          {chartData.length > 0 ? (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData} margin={{ top: 8, right: 10, bottom: 0, left: -14 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                <XAxis dataKey="drawdownLabel" tick={{ fontSize: 10 }} />
                <YAxis tick={{ fontSize: 10 }} width={40} />
                <Tooltip
                  formatter={(value: unknown, name: unknown) => [
                    typeof value === 'number' ? value.toFixed(2) : String(value ?? ''),
                    String(name ?? ''),
                  ]}
                />
                <Line type="monotone" dataKey="riskPotential" name="风险势能" stroke="#dc2626" strokeWidth={2} dot={false} isAnimationActive={false} />
                <Line type="monotone" dataKey="riskGradient" name="风险梯度" stroke="#7c3aed" strokeWidth={2} dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex h-full items-center justify-center text-xs text-slate-500">等待可用日线代理输入</div>
          )}
        </div>
        <div className="space-y-2 text-xs leading-5 text-slate-600">
          <div className="rounded-md border border-slate-200 bg-slate-50 p-2">
            <div className="font-semibold text-slate-900">风险收益代理</div>
            <div className="mt-1">{numberText(proxy.riskRewardProxy)}</div>
          </div>
          <div className="rounded-md border border-slate-200 bg-slate-50 p-2">
            <div className="font-semibold text-slate-900">最大风险梯度</div>
            <div className="mt-1">{numberText(pathRiskFilter.maxRiskGradient)}</div>
          </div>
        </div>
      </div>
      {evidence.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {evidence.slice(0, 6).map((item, index) => (
            <span key={`${item}-${index}`} className="rounded border border-slate-200 bg-slate-50 px-2 py-1 text-[11px] text-slate-600">
              {displayText(item)}
            </span>
          ))}
        </div>
      ) : null}
      {[...warnings, ...limitations].length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {[...warnings, ...limitations].slice(0, 5).map((item, index) => (
            <Badge key={`${item}-${index}`} status="WARN">{displayText(item)}</Badge>
          ))}
        </div>
      ) : null}
    </div>
  )
}

function ConditionalQuantilePanel({ evaluation }: { evaluation?: MfeMaeConditionalQuantileEvaluation }) {
  if (!evaluation) return null
  const status = text(evaluation.status) ?? 'SUPPORTING_ONLY'
  const targetCoverage = asRecord(evaluation.targetCoverage)
  const mfeCoverage = asRecord(targetCoverage?.mfe)
  const maeCoverage = asRecord(targetCoverage?.maeAbs)
  const riskRewardCoverage = asRecord(targetCoverage?.riskReward)
  const sampleQuality = asRecord(evaluation.sampleQuality)
  const rankIc = asRecord(evaluation.rankIc)
  const folds = Array.isArray(evaluation.folds) ? evaluation.folds : []

  return (
    <div className="rounded-md border border-slate-200 bg-white p-3">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="text-sm font-semibold text-slate-950">经验条件分位数评估</div>
          <div className="mt-0.5 text-[11px] leading-4 text-slate-500">
            {displayCode(evaluation.method, 'walk-forward empirical quantile')} · 历史标签训练窗 · 不是确定性预测
          </div>
        </div>
        <Badge status={status === 'READY' ? 'PASS' : 'WARN'}>{displayCode(status)}</Badge>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <InfoBlock label="评估样本" value={countText(sampleQuality?.evaluatedTestCount ?? targetCoverage?.evaluatedTestCount)} />
        <InfoBlock label="折数" value={countText(sampleQuality?.foldCount ?? folds.length)} />
        <InfoBlock label="排除样本" value={countText(sampleQuality?.excludedCount)} />
        <InfoBlock label="边界" value={displayCode(evaluation.actionBoundary)} />
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <InfoBlock label="MFE Q80覆盖" value={quantileCoverageText(mfeCoverage, 'q80')} />
        <InfoBlock label="MAE Q80覆盖" value={quantileCoverageText(maeCoverage, 'q80')} />
        <InfoBlock label="风险收益 Q50覆盖" value={quantileCoverageText(riskRewardCoverage, 'q50')} />
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <InfoBlock label="MFE Rank IC" value={numberText(rankIc?.mfeQ80ToMfe ?? rankIc?.mfeQ80RankIc)} />
        <InfoBlock label="MAE Rank IC" value={numberText(rankIc?.maeQ80ToMaeAbs ?? rankIc?.maeAbsQ80RankIc)} />
        <InfoBlock label="标签状态" value={displayCode(evaluation.labelStatus)} />
      </div>
    </div>
  )
}

function FutureTrendProbabilityCard({
  data,
  futureTrendProbability,
}: {
  data: FutureTrendChartPoint[]
  futureTrendProbability?: QuantCoreInterpretation['futureTrendProbability']
}) {
  const calibration = futureTrendProbability?.calibration
  const status = calibration?.status || data[0]?.status || 'FALLBACK'

  return (
    <Card
      title="未来趋势综合走势"
      action={<Badge status={status === 'READY' || status === 'PASS' ? 'PASS' : 'WARN'}>{displayCode(status)}</Badge>}
    >
      {data.length > 0 ? (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_260px]">
          <div className="min-w-0 rounded-md border border-slate-200 bg-white p-3">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <div className="text-xs font-semibold text-slate-900">上涨概率 / 下跌概率综合走势</div>
              <div className="flex flex-wrap items-center gap-3 text-[11px] text-slate-500">
                <span className="inline-flex items-center gap-1">
                  <span className="h-0.5 w-5 rounded-full bg-teal-700" />
                  校正上涨
                </span>
                <span className="inline-flex items-center gap-1">
                  <span className="h-0.5 w-5 rounded-full bg-red-600" />
                  校正下跌
                </span>
              </div>
            </div>
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                  <XAxis dataKey="horizon" minTickGap={24} tick={{ fontSize: 11 }} />
                  <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} tickFormatter={(value) => `${value}%`} width={48} />
                  <Tooltip
                    formatter={(value: unknown, name: unknown) => [
                      typeof value === 'number' ? `${value.toFixed(1)}%` : String(value ?? ''),
                      String(name ?? ''),
                    ]}
                    labelFormatter={(_, payload) => {
                      const row = payload?.[0]?.payload
                      return `${row?.horizonDays || '-'}日 / ${row?.status || 'UNKNOWN'}`
                    }}
                  />
                  <Line type="monotone" dataKey="up" name="校正上涨概率" stroke="#0f766e" strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} />
                  <Line type="monotone" dataKey="down" name="校正下跌概率" stroke="#dc2626" strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
          <div className="grid gap-2 text-xs leading-5 text-slate-600 sm:grid-cols-2 xl:grid-cols-1">
            <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
              <div className="mb-2 flex items-center justify-between gap-3">
                <span className="font-medium text-slate-900">Up path</span>
                <span className="font-mono text-slate-500">{data.filter((item) => item.up != null).length} points</span>
              </div>
              <InlineSparkline values={data.map((item) => item.up ?? 0)} tone="success" />
            </div>
            <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
              <div className="mb-2 flex items-center justify-between gap-3">
                <span className="font-medium text-slate-900">Down path</span>
                <span className="font-mono text-slate-500">{data.filter((item) => item.down != null).length} points</span>
              </div>
              <InlineSparkline values={data.map((item) => item.down ?? 0)} tone="danger" />
            </div>
            <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
              <div className="font-medium text-slate-900">校正状态</div>
              <div>{displayCode(status)}</div>
            </div>
            <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
              <div className="font-medium text-slate-900">样本数</div>
              <div>{countText(calibration?.sampleCount)}</div>
            </div>
            <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
              <div className="font-medium text-slate-900">Brier评分</div>
              <div>上涨 {numberText(calibration?.brierUp)} / 下跌 {numberText(calibration?.brierDown)}</div>
            </div>
            <div className="rounded-md border border-blue-100 bg-blue-50 px-3 py-2 text-blue-900">
              <div className="font-medium">回馈边界</div>
              <div>{displayText(futureTrendProbability?.decisionFeedback?.signalopsPolicyHint, 'simulation-only evidence')}</div>
            </div>
          </div>
        </div>
      ) : (
        <EmptyState text="等待未来趋势概率输出" />
      )}
    </Card>
  )
}

function InlineMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-blue-100 bg-white/80 px-2.5 py-2">
      <div className="text-[11px] font-medium text-blue-800">{label}</div>
      <div className="mt-0.5 text-sm font-semibold text-slate-950">{value}</div>
    </div>
  )
}

function buildQuantSourceFreshness(
  run: AnalysisRun,
  marketTechnical: Record<string, any> | null | undefined,
  bottom: BottomResearchResult | null | undefined,
  factor: AnalysisRun['factorSlicing'] | null | undefined,
  qiam: AnalysisRun['qiam'],
  probabilitySourceKind: unknown,
) {
  return [
    {
      label: 'Market / K-line',
      freshness: displayCode(marketTechnical?.status ?? run.market?.marketSentiment ?? 'UNKNOWN'),
      value: statusFreshnessValue(marketTechnical?.status ?? run.market?.marketSentiment),
      mode: displayCode(marketTechnical?.alignment ?? run.technicalKline?.technicalBias ?? 'UNKNOWN'),
    },
    {
      label: 'MFE/MAE research',
      freshness: displayCode(bottom?.status ?? bottom?.labelStatus ?? 'NOT_AVAILABLE'),
      value: bottom ? statusFreshnessValue(bottom.status ?? 'READY') : 0,
      mode: displayCode(bottom?.actionBoundary ?? bottom?.riskPolicy ?? 'RESEARCH_ONLY_NO_PERMISSION_CHANGE'),
    },
    {
      label: 'Factor slicing',
      freshness: factor?.mode ?? 'missing',
      value: scorePercent(factor?.factorStability),
      mode: `${factor?.factors?.length ?? 0} factors / ${factor?.missingFactorData?.length ?? 0} missing`,
    },
    {
      label: 'QIAM probability',
      freshness: String(probabilitySourceKind),
      value: scorePercent(qiam.modelConfidenceFinal),
      mode: displayCode(qiam.finalBuySuitability),
    },
  ]
}

function buildMfeMaeBarRows(
  bottom: BottomResearchResult | null | undefined,
  adjustment?: AnalysisRun['qiam']['bottomResearchAdjustment'],
) {
  return [
    {
      label: 'MFE favorable',
      value: scoreUnit(bottom?.mfeFavorableProbability ?? bottom?.bottomRepairProbability),
      helper: pct(bottom?.mfeFavorableProbability ?? bottom?.bottomRepairProbability),
      tone: 'positive' as const,
    },
    {
      label: 'MAE breach risk',
      value: scoreUnit(bottom?.maeBreachProbability ?? bottom?.breakdownRiskProbability),
      helper: pct(bottom?.maeBreachProbability ?? bottom?.breakdownRiskProbability),
      tone: 'negative' as const,
    },
    {
      label: 'Risk reward proxy',
      value: scoreUnit(bottom?.riskRewardProxy),
      helper: numberText(bottom?.riskRewardProxy),
      tone: 'data' as const,
    },
    {
      label: 'QIAM adjustment',
      value: adjustment?.observed ? (adjustment.applied ? 1 : 0.55) : 0.2,
      helper: bottomAdjustmentLabel(adjustment),
      tone: bottomAdjustmentStatus(adjustment) === 'PASS' ? 'positive' as const : 'data' as const,
    },
  ]
}

function buildMfeMaeHeatmapRows(
  bottom: BottomResearchResult | null | undefined,
  forecast: BottomHorizonForecast | undefined,
  evaluation: MfeMaeConditionalQuantileEvaluation | undefined,
) {
  const diagnostics = bottom?.modelDiagnostics ?? {}
  const targetCoverage = asRecord(evaluation?.targetCoverage)
  const mfeCoverage = asRecord(targetCoverage?.mfe)
  const maeCoverage = asRecord(targetCoverage?.maeAbs)
  const sampleQuality = asRecord(evaluation?.sampleQuality)
  const rankIc = asRecord(evaluation?.rankIc)
  return [
    {
      label: 'Nowcast',
      cells: [
        { label: 'MFE', value: scoreUnit(bottom?.mfeFavorableProbability ?? bottom?.bottomRepairProbability), helper: pct(bottom?.mfeFavorableProbability ?? bottom?.bottomRepairProbability) },
        { label: 'MAE', value: scoreUnit(bottom?.maeBreachProbability ?? bottom?.breakdownRiskProbability), helper: pct(bottom?.maeBreachProbability ?? bottom?.breakdownRiskProbability) },
        { label: 'Sample', value: countUnit(diagnostics.sampleCount, 120), helper: countText(diagnostics.sampleCount) },
      ],
    },
    {
      label: '5d forecast',
      cells: [
        { label: 'Up', value: scoreUnit(forecast?.trendProbabilities?.up), helper: pct(forecast?.trendProbabilities?.up) },
        { label: 'MFE', value: scoreUnit(forecast?.mfeFavorableProbability ?? forecast?.bottomRepairProbability), helper: pct(forecast?.mfeFavorableProbability ?? forecast?.bottomRepairProbability) },
        { label: 'MAE', value: scoreUnit(forecast?.maeBreachProbability ?? forecast?.breakdownRiskProbability), helper: pct(forecast?.maeBreachProbability ?? forecast?.breakdownRiskProbability) },
      ],
    },
    {
      label: 'CQ eval',
      cells: [
        { label: 'MFE Q80', value: scoreUnit(asRecord(mfeCoverage?.q80)?.coverage ?? mfeCoverage?.q80Coverage), helper: quantileCoverageText(mfeCoverage, 'q80') },
        { label: 'MAE Q80', value: scoreUnit(asRecord(maeCoverage?.q80)?.coverage ?? maeCoverage?.q80Coverage), helper: quantileCoverageText(maeCoverage, 'q80') },
        { label: 'Rank IC', value: Math.abs(signedUnit(rankIc?.mfeQ80ToMfe ?? rankIc?.mfeQ80RankIc)), helper: numberText(rankIc?.mfeQ80ToMfe ?? rankIc?.mfeQ80RankIc) },
        { label: 'Folds', value: countUnit(sampleQuality?.foldCount, 10), helper: countText(sampleQuality?.foldCount) },
      ],
    },
  ]
}

function buildFactorRows(factor: AnalysisRun['factorSlicing'] | null | undefined) {
  return (factor?.factors ?? []).slice(0, 6).map((item) => ({
    label: item.name,
    value: signedUnit(item.contribution),
    helper: `weight ${pct(item.weight)} / confidence ${pct(item.confidence)}`,
    tone: item.contribution >= 0 ? 'positive' as const : 'negative' as const,
  }))
}

function buildQiamModeHeatmapRows(
  rows: QiamModeRow[],
  qiam: AnalysisRun['qiam'],
  factor: AnalysisRun['factorSlicing'] | null | undefined,
) {
  return rows.map((row) => ({
    label: row.label,
    cells: [
      { label: 'Active', value: row.active ? 1 : 0.25, helper: row.active ? 'current' : 'candidate' },
      { label: 'Confidence', value: scoreUnit(qiam.modelConfidenceFinal), helper: pct(qiam.modelConfidenceFinal) },
      { label: 'Discount', value: scoreUnit(qiam.discountFactor), helper: numberText(qiam.discountFactor) },
      { label: 'Factor stability', value: scoreUnit(factor?.factorStability), helper: pct(factor?.factorStability) },
    ],
  }))
}

function factorMaxAbs(rows: Array<{ value: number }>) {
  return Math.max(1, ...rows.map((row) => Math.abs(row.value)))
}

function scoreUnit(value: unknown): number {
  const number = numericValue(value)
  if (number == null) return 0
  const normalized = Math.abs(number) > 1 ? number / 100 : number
  return Math.max(0, Math.min(1, normalized))
}

function scorePercent(value: unknown): number {
  return scoreUnit(value) * 100
}

function signedUnit(value: unknown): number {
  const number = numericValue(value)
  if (number == null) return 0
  const normalized = Math.abs(number) > 1 ? number / 100 : number
  return Math.max(-1, Math.min(1, normalized))
}

function countUnit(value: unknown, denominator: number): number {
  const number = numericValue(value)
  if (number == null || denominator <= 0) return 0
  return Math.max(0, Math.min(1, number / denominator))
}

function statusFreshnessValue(status: unknown): number {
  const normalized = text(status)?.toUpperCase()
  if (['PASS', 'READY', 'COMPLETED', 'FAVORABLE', 'ALIGNED', 'ALIGNED_BULLISH'].includes(normalized ?? '')) return 100
  if (['WARN', 'REVIEW_ONLY', 'NEUTRAL', 'MIXED', 'PARTIAL'].includes(normalized ?? '')) return 64
  if (['FAIL', 'ERROR', 'BLOCK', 'BLOCKED', 'BLOCK_BUY', 'BEARISH'].includes(normalized ?? '')) return 32
  return 45
}

function readScenario(run: AnalysisRun): Record<string, any> {
  const moduleData = run.agentModuleResults?.scenario_engine?.data
  const agentResultData = run.agentResults?.find((result) => result.node === 'scenario_engine')?.data
  const legacyResult = recordCandidate(run.quantCore?.legacyOutputs?.scenario_engine)
  const candidates = [
    recordCandidate(run.quantCore?.scenario),
    recordCandidate(run.agentOutputs?.scenario_engine),
    recordCandidate(moduleData),
    recordCandidate(agentResultData),
    recordCandidate(legacyResult?.data),
    recordCandidate(run.quantCore?.legacyAgentOutputs?.scenario_engine),
  ].filter((item): item is Record<string, any> => Boolean(item && Object.keys(item).length > 0))

  return candidates.find(isUsableScenarioData) ?? candidates[0] ?? {}
}

function scenarioBranches(data: Record<string, any>): ScenarioBranch[] {
  return SCENARIO_BRANCH_KEYS.map(([id, label, llmKey]) => {
    const payload = asRecord(data[id]) ?? {}
    return {
      id,
      label,
      premise: meaningfulText(data[llmKey]) ?? meaningfulText(payload.premise) ?? '等待情景输出',
      probability: displayCode(meaningfulText(payload.probability) ?? meaningfulText(data[`${id}_probability`]) ?? '定性'),
    }
  })
}

function isUsableScenarioData(data: Record<string, any>): boolean {
  return SCENARIO_BRANCH_KEYS.some(([id, , llmKey]) => {
    const payload = asRecord(data[id])
    return Boolean(meaningfulText(data[llmKey]) ?? meaningfulText(payload?.premise))
  })
}

function scenarioNoticeText(data: Record<string, any>): string | undefined {
  const raw = asRecord(data.raw)
  const llmOutput = asRecord(raw?.llmOutput)
  const reason = meaningfulText(data.blocked_reason)
    ?? meaningfulText(data.blockedReason)
    ?? meaningfulText(llmOutput?.blocked_reason)
    ?? meaningfulText(llmOutput?.blockedReason)
  return reason ? `模型情景输出被阻断：${displayText(reason)}` : undefined
}

function statusFromQiam(value?: string) {
  if (value === 'FAVORABLE') return 'PASS'
  if (value === 'BLOCK_BUY' || value === 'REVIEW_ONLY') return 'REVIEW_ONLY'
  return 'WARN'
}

function bottomAdjustmentLabel(adjustment?: AnalysisRun['qiam']['bottomResearchAdjustment']) {
  if (!adjustment?.observed) return '未参与校准'
  if (adjustment.applied) return `${displayCode(adjustment.direction)}一档校准`
  return adjustment.reason || '已观察未应用'
}

function bottomAdjustmentStatus(adjustment?: AnalysisRun['qiam']['bottomResearchAdjustment']) {
  if (!adjustment?.observed) return 'SKIPPED'
  if (adjustment.applied && adjustment.direction === 'UP') return 'PASS'
  if (adjustment.applied && adjustment.direction === 'DOWN') return 'WARN'
  return 'REVIEW_ONLY'
}

function pct(value: unknown) {
  const number = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(number) ? `${(number * 100).toFixed(1)}%` : '暂无数据'
}

function quantileCoverageText(targetCoverage: Record<string, any> | undefined, key: 'q50' | 'q80' | 'q90') {
  const bucket = asRecord(targetCoverage?.[key])
  return pct(bucket?.coverage ?? targetCoverage?.[`${key}Coverage`])
}

function numberText(value: unknown) {
  const number = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(number) ? number.toFixed(2) : '暂无数据'
}

function scoreText(value: unknown) {
  const number = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(number) ? `${number.toFixed(1)} / 100` : '暂无数据'
}

function countText(value: unknown) {
  const number = numericValue(value)
  return number == null ? '暂无数据' : String(Math.round(number))
}

function formatProxyPct(value: unknown) {
  const number = numericValue(value)
  return number == null ? '暂无数据' : `${(number * 100).toFixed(2)}%`
}

function text(value: unknown): string | undefined {
  if (typeof value === 'string') return value.trim() || undefined
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return undefined
}

function meaningfulText(value: unknown): string | undefined {
  const raw = text(value)
  if (!raw || PLACEHOLDER_TEXT.has(raw.toUpperCase())) return undefined
  return raw
}

function numericValue(value: unknown): number | undefined {
  const number = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(number) ? number : undefined
}

function probabilityPercentNumber(value: unknown): number | null {
  const number = numericValue(value)
  if (number == null) return null
  return Math.abs(number) <= 1 ? number * 100 : number
}

function probabilityUnit(value: unknown): number | null {
  const number = numericValue(value)
  if (number == null) return null
  return Math.abs(number) > 1 ? number / 100 : number
}

function boundedPercent(value: number | null | undefined): number | null {
  if (value == null || !Number.isFinite(value)) return null
  return Math.max(0, Math.min(100, value))
}

function percentText(value: number | null | undefined): string {
  return value == null ? '暂无数据' : `${value.toFixed(1)}%`
}

function visualMatrixZone(
  upProbability: number | null,
  downProbability: number | null,
  riskRewardProxy: number | null | undefined,
  downsideRiskScore: number | null | undefined,
  riskPolicy: unknown,
  pathStatus: unknown,
): 'PRIORITY' | 'WATCH' | 'FILTER' | 'INSUFFICIENT_DATA' {
  const riskPolicyCode = text(riskPolicy)?.toUpperCase()
  const pathStatusCode = text(pathStatus)?.toUpperCase()
  if (pathStatusCode !== 'READY' || upProbability == null || downProbability == null || riskRewardProxy == null) {
    return 'INSUFFICIENT_DATA'
  }
  if (riskPolicyCode === 'AVOID_NEW_BUY' || (downsideRiskScore != null && downsideRiskScore >= 75)) return 'FILTER'
  if (downProbability >= upProbability + 0.12 || riskRewardProxy < 1) return 'FILTER'
  if (upProbability >= 0.58 && riskRewardProxy >= 1.8 && (downsideRiskScore == null || downsideRiskScore < 60)) return 'PRIORITY'
  return 'WATCH'
}

function matrixZoneStatus(zone: unknown): string {
  const normalized = text(zone)?.toUpperCase()
  if (normalized === 'PRIORITY') return 'PASS'
  if (normalized === 'FILTER') return 'REVIEW_ONLY'
  if (normalized === 'WATCH') return 'WARN'
  return 'SKIPPED'
}

function matrixZoneDotClass(zone: unknown): string {
  const normalized = text(zone)?.toUpperCase()
  if (normalized === 'PRIORITY') return 'bg-teal-700'
  if (normalized === 'FILTER') return 'bg-red-600'
  if (normalized === 'WATCH') return 'bg-amber-500'
  return 'bg-slate-500'
}

function riskGradientTone(riskPolicy: unknown): 'primary' | 'data' | 'warning' | 'danger' | 'success' {
  const normalized = text(riskPolicy)?.toUpperCase()
  if (normalized === 'NORMAL') return 'success'
  if (normalized === 'WATCH') return 'warning'
  if (normalized === 'THROTTLE' || normalized === 'AVOID_NEW_BUY') return 'danger'
  return 'data'
}

function fallbackTrendProbabilities(repair?: number | null, breakdown?: number | null) {
  const repairValue = numericValue(repair)
  const breakdownValue = numericValue(breakdown)
  if (repairValue == null || breakdownValue == null) return undefined
  const up = Math.max(0.05, 0.25 + repairValue * 0.55 - breakdownValue * 0.25)
  const down = Math.max(0.05, 0.20 + breakdownValue * 0.65 - repairValue * 0.20)
  const sideways = Math.max(0.05, 0.35 + Math.max(0, 0.50 - Math.abs(repairValue - breakdownValue)) * 0.20)
  const total = up + sideways + down
  return {
    up: up / total,
    sideways: sideways / total,
    down: down / total,
  }
}

function futureTrendProbabilityChartData(
  interpretation?: QuantCoreInterpretation | null,
  bottom?: BottomResearchResult | null,
): FutureTrendChartPoint[] {
  const future = interpretation?.futureTrendProbability
  if (future?.points?.length) {
    return future.points
      .map((item) => ({
        horizon: `${item.horizonDays}d`,
        horizonDays: item.horizonDays,
        up: probabilityPercentNumber(item.calibratedUpProbability ?? item.rawUpProbability),
        down: probabilityPercentNumber(item.calibratedDownProbability ?? item.rawDownProbability),
        confidence: probabilityPercentNumber(item.confidence),
        status: item.calibrationStatus || future.calibration?.status || 'UNKNOWN',
      }))
      .filter((item) => item.up != null || item.down != null)
  }

  return (bottom?.horizonForecasts || [])
    .filter((forecast) => typeof forecast?.horizonDays === 'number')
    .slice()
    .sort((left, right) => left.horizonDays - right.horizonDays)
    .map((forecast) => {
      const fallback = fallbackTrendProbabilities(forecast.bottomRepairProbability, forecast.breakdownRiskProbability)
      return {
        horizon: `${forecast.horizonDays}d`,
        horizonDays: forecast.horizonDays,
        up: probabilityPercentNumber(forecast.trendProbabilities?.up ?? fallback?.up),
        down: probabilityPercentNumber(forecast.trendProbabilities?.down ?? fallback?.down),
        confidence: probabilityPercentNumber(forecast.confidence),
        status: 'FALLBACK_UNCALIBRATED',
      }
    })
    .filter((item) => item.up != null || item.down != null)
}

function buildVisualDecisionPanelView(
  interpretation?: QuantCoreInterpretation | null,
  bottom?: BottomResearchResult | null,
): VisualDecisionPanel {
  if (interpretation?.visualDecisionPanel) return interpretation.visualDecisionPanel

  const future = interpretation?.futureTrendProbability
  const primaryHorizon = primaryBottomHorizon(bottom)
  const point = future?.points?.find((item) => numericValue(item.horizonDays) === primaryHorizon) ?? future?.points?.[0]
  const pathRisk = interpretation?.pathRiskFilter
  const pathProxy = pathRisk?.mfeMaeProxy
  const upProbability = probabilityUnit(point?.calibratedUpProbability ?? point?.rawUpProbability)
  const downProbability = probabilityUnit(point?.calibratedDownProbability ?? point?.rawDownProbability)
  const sidewaysProbability = probabilityUnit(point?.calibratedSidewaysProbability ?? point?.rawSidewaysProbability)
  const mfeProxy = numericValue(pathProxy?.mfeProxy ?? bottom?.mfeProxy)
  const maeProxy = numericValue(pathProxy?.maeProxy ?? bottom?.maeProxy)
  let riskRewardProxy = numericValue(pathProxy?.riskRewardProxy ?? bottom?.riskRewardProxy)
  if (riskRewardProxy == null && mfeProxy != null && maeProxy != null) {
    riskRewardProxy = mfeProxy / (maeProxy + 0.000001)
  }
  const expectedPathValueProxy = upProbability != null && downProbability != null && mfeProxy != null && maeProxy != null
    ? (upProbability * mfeProxy) - (downProbability * maeProxy)
    : null
  const riskPolicy = text(pathRisk?.riskPolicy ?? bottom?.riskPolicy) ?? 'WATCH'
  const pathStatus = text(pathRisk?.status) ?? (pathRisk ? 'READY' : 'INSUFFICIENT_DATA')
  const zone = visualMatrixZone(
    upProbability,
    downProbability,
    riskRewardProxy,
    numericValue(pathRisk?.downsideRiskScore ?? bottom?.downsideRiskScore),
    riskPolicy,
    pathStatus,
  )

  return {
    version: 'quant_core_visual_decision_panel_v1',
    status: zone === 'INSUFFICIENT_DATA' ? 'INSUFFICIENT_DATA' : 'READY',
    directionProbability: {
      horizonDays: point?.horizonDays ?? primaryHorizon,
      upProbability,
      downProbability,
      sidewaysProbability,
      source: point?.calibratedUpProbability != null || point?.calibratedDownProbability != null
        ? 'FUTURE_TREND_PROBABILITY_CALIBRATED'
        : future?.points?.length
          ? 'FUTURE_TREND_PROBABILITY_RAW'
          : 'MFE_MAE_RESEARCH_PROXY',
      calibrationStatus: point?.calibrationStatus ?? future?.calibration?.status ?? (future?.points?.length ? 'READY' : 'INSUFFICIENT_DATA'),
      confidence: probabilityUnit(point?.confidence),
      actionBoundary: 'READ_ONLY_NO_PERMISSION_CHANGE',
      simulation_only: true,
      is_real_trade: false,
    },
    pathPayoffProxy: {
      mfeProxy,
      maeProxy,
      riskRewardProxy,
      expectedPathValueProxy,
      source: pathProxy ? 'PATH_RISK_FILTER_PROXY' : 'MFE_MAE_RESEARCH_PROXY',
      actionBoundary: 'READ_ONLY_NO_PERMISSION_CHANGE',
      simulation_only: true,
      is_real_trade: false,
    },
    riskGradient: {
      status: pathStatus,
      downsideRiskScore: numericValue(pathRisk?.downsideRiskScore ?? bottom?.downsideRiskScore),
      maxRiskGradient: numericValue(pathRisk?.maxRiskGradient),
      riskPolicy,
      actionBoundary: 'READ_ONLY_NO_PERMISSION_CHANGE',
      simulation_only: true,
      is_real_trade: false,
    },
    probabilityOddsMatrix: {
      upProbability,
      riskRewardProxy,
      expectedPathValueProxy,
      zone,
      xAxis: 'calibrated_up_probability',
      yAxis: 'risk_reward_proxy',
      actionBoundary: 'READ_ONLY_NO_PERMISSION_CHANGE',
      simulation_only: true,
      is_real_trade: false,
    },
    actionBoundary: 'READ_ONLY_NO_PERMISSION_CHANGE',
    simulation_only: true,
    is_real_trade: false,
  }
}

function formatTradeDate(value?: unknown): string {
  const raw = text(value)
  if (!raw) return ''
  if (/^\d{8}$/.test(raw)) return `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}`
  if (/^\d{4}-\d{2}-\d{2}/.test(raw)) return raw.slice(0, 10)
  return raw
}

function shortTradeDate(value?: unknown): string {
  const formatted = formatTradeDate(value)
  return formatted.length >= 10 ? formatted.slice(5) : formatted
}

function isLaterTradeDate(value?: unknown, baseline?: unknown): boolean {
  const current = formatTradeDate(value)
  const previous = formatTradeDate(baseline)
  return Boolean(current && previous && current > previous)
}

function primaryBottomHorizon(bottom?: BottomResearchResult | null): number {
  return numericValue(bottom?.trendSynthesis?.primaryHorizonDays)
    ?? numericValue(bottom?.currentPrediction?.horizonDays)
    ?? numericValue(bottom?.config?.horizon_days)
    ?? 20
}

function bottomForecastForHorizon(bottom: BottomResearchResult | null | undefined, horizonDays: number): BottomHorizonForecast | undefined {
  return (bottom?.horizonForecasts || []).find((item) => numericValue(item?.horizonDays) === horizonDays)
}

function bottomTrendBiasLabel(value: unknown): string {
  const labels: Record<string, string> = {
    UP: 'MFE偏有利',
    SIDEWAYS: '震荡观察',
    DOWN: 'MAE风险偏高',
    INSUFFICIENT_DATA: '样本不足',
  }
  const normalized = text(value)?.toUpperCase()
  return normalized ? labels[normalized] ?? displayCode(normalized) : '未识别'
}

function bottomForecastStatus(forecast: BottomHorizonForecast): string {
  const bias = text(forecast.trendBias)?.toUpperCase()
  if (bias === 'DOWN') return 'WARN'
  if (forecast.status === 'READY') return 'PASS'
  return 'WARN'
}

function bottomProbabilityPath(bottom?: BottomResearchResult | null) {
  const primaryHorizon = primaryBottomHorizon(bottom)
  const nativeSeries = (bottom?.horizonProbabilitySeries || [])
    .filter((item) => typeof item?.horizonDays === 'number' && Array.isArray(item.series))
    .slice()
    .sort((left, right) => left.horizonDays - right.horizonDays)
  const selectedNative = nativeSeries.find((item) => item.horizonDays === primaryHorizon) ?? nativeSeries[0]
  if (selectedNative?.series?.length) {
    return {
      horizonDays: selectedNative.horizonDays,
      points: selectedNative.series.map((item) => ({
        tradeDate: formatTradeDate(item.date),
        repairProb: item.repairProb,
        breakdownRisk: item.breakdownRisk,
        predictionRepairProb: item.predictionRepairProb,
        predictionBreakdownRisk: item.predictionBreakdownRisk,
        labelWindowEnd: item.labelWindowEnd,
      })),
    }
  }

  const points: CompactBottomProbabilityPoint[] = (bottom?.probabilitySeries || []).map((item) => ({
    tradeDate: formatTradeDate(item.tradeDate),
    repairProb: item.bottomRepairProbability,
    breakdownRisk: item.breakdownRiskProbability,
    labelWindowEnd: item.labelWindowEnd,
  }))
  const current = bottom?.currentPrediction
  if (current && (typeof current.bottomRepairProbability === 'number' || typeof current.breakdownRiskProbability === 'number')) {
    points.push({
      tradeDate: formatTradeDate(current.tradeDate),
      predictionRepairProb: current.bottomRepairProbability,
      predictionBreakdownRisk: current.breakdownRiskProbability,
    })
  }
  return { horizonDays: primaryHorizon, points }
}

function bottomTrendLineData(bottom?: BottomResearchResult | null) {
  const { points } = bottomProbabilityPath(bottom)
  const historical = points
    .filter((item) => typeof item.repairProb === 'number' || typeof item.breakdownRisk === 'number')
    .slice(-48)
    .map((item) => ({
      date: shortTradeDate(item.tradeDate),
      fullDate: formatTradeDate(item.tradeDate),
      repairHistorical: typeof item.repairProb === 'number' ? item.repairProb * 100 : null,
      breakdownHistorical: typeof item.breakdownRisk === 'number' ? item.breakdownRisk * 100 : null,
      repairNowcast: null as number | null,
      breakdownNowcast: null as number | null,
    }))
  const current = points
    .slice()
    .reverse()
    .find((item) => typeof item.predictionRepairProb === 'number' || typeof item.predictionBreakdownRisk === 'number')
  const latest = historical[historical.length - 1]
  if (!latest || !current || !isLaterTradeDate(current.tradeDate, latest.fullDate)) {
    return historical
  }
  return [
    ...historical.slice(0, -1),
    {
      ...latest,
      repairNowcast: latest.repairHistorical,
      breakdownNowcast: latest.breakdownHistorical,
    },
    {
      date: shortTradeDate(current.tradeDate),
      fullDate: formatTradeDate(current.tradeDate),
      repairHistorical: null,
      breakdownHistorical: null,
      repairNowcast: typeof current.predictionRepairProb === 'number' ? current.predictionRepairProb * 100 : null,
      breakdownNowcast: typeof current.predictionBreakdownRisk === 'number' ? current.predictionBreakdownRisk * 100 : null,
    },
  ]
}

function bottomTrendWindowInfo(bottom?: BottomResearchResult | null): string {
  const { horizonDays, points } = bottomProbabilityPath(bottom)
  const historical = points.filter((item) => typeof item.repairProb === 'number' || typeof item.breakdownRisk === 'number')
  const first = historical[0]
  const last = historical[historical.length - 1]
  const current = points
    .slice()
    .reverse()
    .find((item) => typeof item.predictionRepairProb === 'number' || typeof item.predictionBreakdownRisk === 'number')
  const start = formatTradeDate(first?.tradeDate) || '-'
  const end = formatTradeDate(last?.tradeDate) || '-'
  const currentDate = formatTradeDate(current?.tradeDate)
  const nowcastText = currentDate && isLaterTradeDate(currentDate, end) ? `；虚线延伸至 ${currentDate}` : ''
  return `${horizonDays}日窗口 · 最近 ${historical.length} 个可回测样本：${start} 至 ${end}${nowcastText}`
}

function displayCode(value: unknown, fallback = '未知'): string {
  const raw = text(value)
  if (!raw) return fallback
  const normalized = raw.toUpperCase()
  return DISPLAY_LABELS[normalized] ?? localizeQuantText(raw)
}

function displayText(value: unknown, fallback = '暂无内容'): string {
  const raw = text(value) ?? fallback
  const exactLabel = DISPLAY_LABELS[raw.toUpperCase()]
  return exactLabel ?? localizeQuantText(raw)
}

function localizeQuantText(value: string): string {
  return value
    .replace(/QIAM decision_effect is BLOCK_BUY, violating scenario engine input condition: QIAM must not be BLOCK_BUY\.?/g, '量化适宜性为阻断买入，情景引擎只能保留定性复核，不能生成买入升级结论')
    .replace(/\btechnical invalidation:\s*/gi, '技术失效场景：')
    .replace(/\bBreak below MA20 or 20-day support\b/g, '跌破 MA20 或 20日支撑')
    .replace(/\bWeekly\/monthly cycle divergence\b/g, '周线/月线周期背离')
    .replace(/\bQuant Engine\b/g, '量化引擎')
    .replace(/\bBottom Research\b/g, 'MFE/MAE路径研究')
    .replace(/\bsupporting-only\b/g, '辅助证据')
    .replace(/\bScenario\b/g, '情景')
    .replace(/\bDVG Gate\b/g, '数据门禁')
    .replace(/\bDVG\b/g, '数据门禁')
    .replace(/\bQIAM\b/g, '量化适宜性')
    .replace(/\bLLM\b/g, '模型')
    .replace(/\bLevel-2\b/g, '二级行情')
    .replace(/\bregime=/g, '市场体制=')
    .replace(/\btechnicalBias=/g, 'K线偏向=')
    .replace(/\balignment=/g, '一致性=')
    .replace(/\bconfidence=/g, '置信度=')
    .replace(/\bALIGNED_BULLISH\b/g, '偏多一致')
    .replace(/\bALIGNED_BEARISH\b/g, '偏空一致')
    .replace(/\bTECHNICAL_INSUFFICIENT_DATA\b/g, '技术面数据不足')
    .replace(/\bNEUTRAL_OR_MIXED\b/g, '中性或分歧')
    .replace(/\bINSUFFICIENT_DATA\b/g, '数据不足')
    .replace(/\bSUPPORTING_ONLY\b/g, '仅辅助')
    .replace(/\bBOTTOM_REPAIR_ZONE\b/g, 'MFE有利区间')
    .replace(/\bBOTTOM_REPAIR_WATCH\b/g, 'MFE观察')
    .replace(/\bBREAKDOWN_RISK\b/g, 'MAE跌破风险')
    .replace(/\bDISABLED_BY_RUN_MODE\b/g, '当前运行模式未启用')
    .replace(/\bNOT_RUN_IN_FAST_MODE\b/g, '快速模式未运行')
    .replace(/\bNOT_AVAILABLE\b/g, '暂无可用数据')
    .replace(/\bINSUFFICIENT_SAMPLE\b/g, '样本不足')
    .replace(/\bFALLBACK_UNCALIBRATED\b/g, '未校准回退估算')
    .replace(/\bREVIEW_SIMULATION_ONLY_INSUFFICIENT_CALIBRATION\b/g, '校准样本不足，仅模拟复核')
    .replace(/\bUPWARD_ALIGNED\b/g, '上行一致')
    .replace(/\bDOWNWARD_ALIGNED\b/g, '下行一致')
    .replace(/\bBULLISH\b/g, '偏多')
    .replace(/\bBEARISH\b/g, '偏空')
    .replace(/\bSIDEWAYS\b/g, '震荡')
    .replace(/\bMIXED\b/g, '分歧')
    .replace(/\bREVIEW_ONLY\b/g, '仅复核')
    .replace(/\bREAD_ONLY_NO_PERMISSION_CHANGE\b/g, '只读解读，不改变权限')
    .replace(/\bdaily_proxy_no_future_labels_v1\b/g, '日线代理，无未来标签')
    .replace(/\bmfe_mae_path_risk_filter_v1\b/g, 'MFE/MAE路径风险过滤 v1')
    .replace(/\bpath_risk_gradient_high\b/g, '路径风险梯度偏高')
    .replace(/\bpath_risk_avoid_new_buy_read_only\b/g, '路径风险提示避免新开仓（只读）')
    .replace(/\bpath_risk_qiam_divergence\b/g, '路径风险与量化适宜性分歧')
    .replace(/\bchip_distribution_is_kline_volume_price_proxy\b/g, '筹码分布为K线成交量价格代理')
    .replace(/\bMFE\/MAE fields are daily proxies, not trained conditional quantile predictions\./g, 'MFE/MAE字段是日线代理，不是已训练的条件分位数预测')
    .replace(/\bNo future high\/low labels are used at runtime\./g, '运行时不使用未来高低价标签')
    .replace(/\bLevel-2 order flow, real order book depth, full chip distribution, and valuation gap are not required in v1\./g, 'v1不要求二级行情订单流、真实盘口深度、完整筹码分布或估值缺口')
    .replace(/\bCross-market evidence from the source paper is recorded as a limitation, not as a runtime market-bias rule\./g, '论文跨市场实证差异仅记录为限制，不作为运行时市场偏置规则')
    .replace(/\bBLOCKING_CONTEXT\b/g, '解释强冲突')
    .replace(/\bALLOW_WITH_DISCOUNT\b/g, '折扣后允许')
    .replace(/\bAVOID_NEW_BUY\b/g, '避免新开仓')
    .replace(/\bTHROTTLE\b/g, '限仓观察')
    .replace(/\bWATCH\b/g, '观察')
    .replace(/\bNORMAL\b/g, '正常')
    .replace(/\bFAVORABLE\b/g, '有利')
    .replace(/\bNEUTRAL\b/g, '中性')
    .replace(/\bBLOCK_BUY\b/g, '阻断买入')
    .replace(/\bUNKNOWN\b/g, '未知')
}

function suitabilityLabel(value: unknown): string {
  return displayCode(value, '未知')
}

function permissionLabel(value: unknown): string {
  return displayCode(value, '未知')
}

function outputLevelLabel(value: unknown): string {
  return displayCode(value, '未知')
}

function quantModeLabel(value: unknown): string {
  const mode = normalizeQiamMode(value)
  if (mode) return DISPLAY_LABELS[mode]
  return displayCode(value, '未记录')
}

function biasStatus(value: unknown): string {
  const raw = text(value)?.toUpperCase()
  if (raw === 'BULLISH') return 'PASS'
  if (raw === 'BEARISH') return 'WARN'
  if (raw === 'MIXED') return 'REVIEW_ONLY'
  return 'SKIPPED'
}

function conflictStatus(value: unknown): string {
  const raw = text(value)?.toUpperCase()
  if (raw === 'BLOCKING_CONTEXT') return 'REVIEW_ONLY'
  if (raw === 'WARN') return 'WARN'
  return 'SKIPPED'
}

function riskPolicyStatus(value: unknown): string {
  const raw = text(value)?.toUpperCase()
  if (raw === 'NORMAL') return 'PASS'
  if (raw === 'WATCH') return 'WARN'
  if (raw === 'THROTTLE' || raw === 'AVOID_NEW_BUY') return 'REVIEW_ONLY'
  return 'SKIPPED'
}

function asRecord(value: unknown): Record<string, any> | undefined {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, any> : undefined
}

function recordCandidate(value: unknown): Record<string, any> | undefined {
  const record = asRecord(value)
  if (record) return record
  const raw = text(value)
  if (!raw || !raw.startsWith('{')) return undefined
  try {
    return asRecord(JSON.parse(raw))
  } catch {
    return undefined
  }
}

function normalizeQiamMode(value: unknown): QiamMode | undefined {
  const normalized = String(value ?? '').toUpperCase()
  return QIAM_MODES.find((mode) => mode === normalized)
}

function buildQiamModeRows(run: AnalysisRun, activeMode?: QiamMode): QiamModeRow[] {
  const modules = Object.values(run.dvg?.dvgModules ?? {}) as Array<Record<string, any>>
  const ignoredForActiveMode = run.quantEngine?.ignoredMissingData ?? run.qiam?.ignoredMissingData ?? []

  return QIAM_MODES.map((mode) => {
    const profile = QIAM_MODE_PROFILES[mode]
    const module = modules.find((item) => normalizeQiamMode(item.quantEngineMode) === mode)
      ?? modules.find((item) => String(item.moduleId ?? '').toLowerCase().includes(mode === 'HIGH_FREQ_SHORT' ? 'high' : 'low'))
    const moduleId = text(module?.moduleId)
    const active = activeMode === mode || (Boolean(moduleId) && moduleId === run.dvg?.activeModule)
    const ignoredMissingData = arrayText(module?.ignoredMissingData).length > 0
      ? arrayText(module?.ignoredMissingData)
      : active && mode === 'LOW_FREQ_MID_LONG'
        ? arrayText(ignoredForActiveMode)
        : []

    return {
      mode,
      ...profile,
      active,
      status: text(module?.status) ?? (active ? statusFromQiam(run.qiam?.finalBuySuitability) : 'SKIPPED'),
      qiamPermission: permissionLabel(text(module?.qiamPermission) ?? (active ? run.dvg?.qiamPermission : undefined) ?? '待触发'),
      allowedOutputLevel: outputLevelLabel(text(module?.allowedOutputLevel) ?? (active ? run.dvg?.allowedOutputLevel : undefined) ?? '待触发'),
      effectiveMissing: displayCode(text(module?.coreUnknownCount) ?? (active ? run.dvg?.coreUnknownCount : undefined) ?? 'N/A'),
      ignoredMissingData,
    }
  })
}

function arrayText(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String).filter(Boolean) : []
}

function buildQiamDowngradeView(qiam: AnalysisRun['qiam'], activeMode?: QiamMode) {
  const reasons = arrayText(qiam.downgradeReasons)
  if (activeMode !== 'LOW_FREQ_MID_LONG') {
    return { applicable: reasons, notApplicable: [] }
  }
  const ignoredReasons = arrayText(qiam.ignoredMissingData)
  for (const reason of reasons) {
    if (isHighFrequencyDowngradeReason(reason)) {
      ignoredReasons.push(reason.replace(/^缺少/, '').replace(/[:：]\s*[×*x]\s*\d+(?:\.\d+)?$/i, ''))
    }
  }
  return {
    applicable: reasons.filter((reason) => !isHighFrequencyDowngradeReason(reason)),
    notApplicable: Array.from(new Set(ignoredReasons)),
  }
}

function isHighFrequencyDowngradeReason(value: unknown) {
  const textValue = text(value) ?? ''
  return ['Level-2', 'Level2', 'L2', '二级行情', '盘口深度', '分时', '逐笔', '资金流分解']
    .some((marker) => textValue.includes(marker))
}
