import { useCallback, useEffect, useState } from 'react'
import { BarChart3, CheckCircle2, RefreshCw, RotateCcw, Save, SlidersHorizontal } from 'lucide-react'
import { useAnalysisStore } from '../../store/useAnalysisStore'
import { roleAllows, useOperatorContext } from '../../store/operatorContext'
import {
  getTechnicalKlineGovernance,
  getTechnicalSignalBacktest,
  recordTechnicalKlineCase,
  rollbackTechnicalKlineGovernance,
  saveTechnicalKlineGovernance,
  TechnicalKlineGovernance,
  TechnicalKlineGovernanceConfig,
  TechnicalSignalBacktest,
} from '../../api/technicalKlineClient'
import { SectionTitle } from '../common/SectionTitle'
import { Card } from '../common/Card'
import { Badge } from '../common/Badge'
import { MetricTile, TableShell } from '../common/Material'
import { TechnicalKlineSummaryCard } from './TechnicalKlineSummaryCard'

function pct(value?: number | null, digits = 1) {
  if (typeof value !== 'number' || Number.isNaN(value)) return 'N/A'
  return `${(value * 100).toFixed(digits)}%`
}

function governanceToDraft(governance: TechnicalKlineGovernance): TechnicalKlineGovernanceConfig {
  const config = governance.analysisConfig
  return {
    ma_short: config.movingAverageWindows.short,
    ma_medium: config.movingAverageWindows.medium,
    ma_long: config.movingAverageWindows.long,
    volume_recent: config.volumeWindows.recent,
    volume_baseline: config.volumeWindows.baseline,
    support_short: config.supportResistanceWindows.short,
    support_long: config.supportResistanceWindows.long,
    high_volume_ratio: config.riskThresholds.highVolumeRatio,
    near_support_distance: config.riskThresholds.nearSupportDistance,
    near_resistance_distance: config.riskThresholds.nearResistanceDistance,
    case_classification: governance.caseClassification.selected === 'rule_derived'
      ? ''
      : governance.caseClassification.selected as TechnicalKlineGovernanceConfig['case_classification'],
  }
}

export function TechnicalKlinePage() {
  const { currentRun } = useAnalysisStore()
  const operator = useOperatorContext()
  const [horizonDays, setHorizonDays] = useState(5)
  const [governanceDraft, setGovernanceDraft] = useState<TechnicalKlineGovernanceConfig>({
    ma_short: 5,
    ma_medium: 10,
    ma_long: 20,
    volume_recent: 5,
    volume_baseline: 20,
    support_short: 20,
    support_long: 60,
    high_volume_ratio: 1.25,
    case_classification: '',
  })
  const [appliedGovernance, setAppliedGovernance] = useState<TechnicalKlineGovernanceConfig>({})
  const [governance, setGovernance] = useState<TechnicalKlineGovernance | null>(null)
  const [governanceLoading, setGovernanceLoading] = useState(false)
  const [governanceError, setGovernanceError] = useState('')
  const [governanceActionMessage, setGovernanceActionMessage] = useState('')
  const [caseNote, setCaseNote] = useState('')
  const [caseRecording, setCaseRecording] = useState(false)
  const [caseMessage, setCaseMessage] = useState('')
  const [backtest, setBacktest] = useState<TechnicalSignalBacktest | null>(null)
  const [backtestLoading, setBacktestLoading] = useState(false)
  const [backtestError, setBacktestError] = useState('')

  const loadBacktest = useCallback(async (days: number) => {
    if (!currentRun?.stockCode) return
    setBacktestLoading(true)
    setBacktestError('')
    try {
      setBacktest(await getTechnicalSignalBacktest(currentRun.stockCode, days))
    } catch (err) {
      setBacktest(null)
      const message = err instanceof Error ? err.message : '技术面信号回测读取失败'
      setBacktestError(message === 'Not Found' ? '信号回测服务暂不可用，请重启后端服务后重试。' : message)
    } finally {
      setBacktestLoading(false)
    }
  }, [currentRun?.stockCode])

  const loadGovernance = useCallback(async (config: TechnicalKlineGovernanceConfig) => {
    setGovernanceLoading(true)
    setGovernanceError('')
    try {
      const data = await getTechnicalKlineGovernance(config)
      setGovernance(data)
      setGovernanceDraft(governanceToDraft(data))
    } catch (err) {
      setGovernance(null)
      setGovernanceError(err instanceof Error ? err.message : '技术面治理配置读取失败')
    } finally {
      setGovernanceLoading(false)
    }
  }, [])

  useEffect(() => {
    loadBacktest(horizonDays)
  }, [horizonDays, loadBacktest])

  useEffect(() => {
    loadGovernance(appliedGovernance)
  }, [appliedGovernance, loadGovernance])

  const backtestBadgeStatus = backtestError ? 'SKIPPED' : (backtest?.status ?? (backtestLoading ? 'RUNNING' : 'WAIT'))
  const backtestBadgeText = backtestError ? 'UNAVAILABLE' : (backtest?.status ?? (backtestLoading ? 'RUNNING' : 'WAIT'))
  const backtestErrorClass = backtestError.includes('暂不可用')
    ? 'rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800'
    : 'rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700'
  const canManageGovernance = roleAllows(operator.role, 'admin')
  const canRecordCase = roleAllows(operator.role, 'researcher')
  const governanceDisabledReason = canManageGovernance
    ? undefined
    : `当前角色 ${operator.role} 不能保存或回滚 Technical Kline 治理配置。请切换到 admin 或使用管理员 token。`
  const caseDisabledReason = canRecordCase
    ? undefined
    : `当前角色 ${operator.role} 不能沉淀 Technical Kline 案例。`
  const technicalKlineBoundaryText = 'simulation_only=true / is_real_trade=false / evidence_usage=technical_kline_review_only / strong_conclusion_allowed=false / SIM_*'

  function updateGovernanceNumber(key: keyof TechnicalKlineGovernanceConfig, value: string) {
    setGovernanceDraft((draft) => ({
      ...draft,
      [key]: value === '' ? undefined : Number(value),
    }))
  }

  function guardGovernanceWrite(action: string) {
    if (canManageGovernance) return true
    setGovernanceError(`${action} 需要 admin 角色。当前角色：${operator.role}。`)
    return false
  }

  async function handleSaveGovernance() {
    if (!guardGovernanceWrite('保存 Technical Kline 治理配置')) return
    setGovernanceLoading(true)
    setGovernanceError('')
    setGovernanceActionMessage('')
    try {
      const data = await saveTechnicalKlineGovernance(governanceDraft, '前端保存 Technical Kline 参数与案例治理配置')
      setGovernance(data)
      setAppliedGovernance({})
      setGovernanceDraft(governanceToDraft(data))
      setGovernanceActionMessage('治理配置已保存，后续技术面分析默认使用该配置。')
    } catch (err) {
      setGovernanceError(err instanceof Error ? err.message : '技术面治理配置保存失败')
    } finally {
      setGovernanceLoading(false)
    }
  }

  async function handleRollbackGovernance() {
    if (!guardGovernanceWrite('回滚 Technical Kline 治理配置')) return
    setGovernanceLoading(true)
    setGovernanceError('')
    setGovernanceActionMessage('')
    try {
      const data = await rollbackTechnicalKlineGovernance('前端回滚 Technical Kline 治理配置到默认值')
      setGovernance(data)
      setAppliedGovernance({})
      setGovernanceDraft(governanceToDraft(data))
      setGovernanceActionMessage('治理配置已回滚到默认值。')
    } catch (err) {
      setGovernanceError(err instanceof Error ? err.message : '技术面治理配置回滚失败')
    } finally {
      setGovernanceLoading(false)
    }
  }

  async function handleRecordCase() {
    if (!canRecordCase) {
      setCaseMessage(`沉淀案例需要 researcher 及以上角色。当前角色：${operator.role}。`)
      return
    }
    if (!currentRun?.stockCode || !governance) return
    setCaseRecording(true)
    setCaseMessage('')
    try {
      const rawClassification = governanceDraft.case_classification || governance.caseClassification.selected || 'valid'
      const classification = ['valid', 'misjudge', 'insufficient_data'].includes(rawClassification)
        ? rawClassification as 'valid' | 'misjudge' | 'insufficient_data'
        : 'valid'
      const saved = await recordTechnicalKlineCase({
        symbol: currentRun.stockCode,
        classification,
        note: caseNote.trim(),
        run_id: currentRun.runId,
        analysis_status: String(currentRun.technicalKline?.status ?? ''),
        technical_bias: String(currentRun.technicalKline?.technicalBias ?? ''),
        config_hash: governance.analysisConfig.configHash,
        prompt_version: governance.promptGovernance.version,
      })
      setCaseMessage(`案例已沉淀：${saved.caseId}${saved.caseLibraryCaseId ? ` / Case Library: ${saved.caseLibraryCaseId}` : ''}`)
      setCaseNote('')
      setGovernance(await getTechnicalKlineGovernance(appliedGovernance))
    } catch (err) {
      setCaseMessage(err instanceof Error ? err.message : '案例沉淀失败')
    } finally {
      setCaseRecording(false)
    }
  }

  if (!currentRun) {
    return <div className="text-sm text-slate-500">请先创建或选择一个分析任务。</div>
  }

  return (
    <div className="space-y-6">
      <SectionTitle
        title="技术 K 线 Agent"
        subtitle="基于真实 Tushare 日线/周线/月线的技术面解释 Agent；只做证据解释，不生成交易动作。"
        dataMode={currentRun.dataMode}
      />
      <div className="rounded-md border border-slate-200 bg-white px-4 py-3 text-xs text-slate-500">
        <span data-testid="technical-kline-governance-role">
          角色：{operator.role}；治理：{canManageGovernance ? 'admin' : '已阻断'}；案例记录：{canRecordCase ? 'researcher+' : '已阻断'}
        </span>
        <span data-testid="technical-kline-simulation-boundary" className="ml-3 inline-flex min-w-0 break-words text-slate-600">
          技术 K 线仅作为复核证据；{technicalKlineBoundaryText}
        </span>
        {!canManageGovernance ? (
          <span data-testid="technical-kline-governance-disabled-reason" className="ml-3 text-amber-700">{governanceDisabledReason}</span>
        ) : null}
        {!canRecordCase ? (
          <span data-testid="technical-kline-case-disabled-reason" className="ml-3 text-amber-700">{caseDisabledReason}</span>
        ) : null}
      </div>
      {!canManageGovernance ? (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          {governanceDisabledReason}
        </div>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <MetricTile label="当前标的" value={currentRun.stockCode} helper={currentRun.stockName || '未命名'} tone="primary" />
        <MetricTile label="数据源" value="仅 Tushare 实时数据" helper="不可用时直接跳过，不补 mock" tone="success" />
        <MetricTile label="分析周期" value="3个月" helper="日线、周线、月线" tone="info" />
        <MetricTile label="交易权限" value="禁止直接交易动作" helper="仅供 DVG/QIAM/人工复核读取" tone="danger" />
      </div>

      <Card
        title="提示词与参数治理"
        action={
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => setAppliedGovernance({ ...governanceDraft })}
              disabled={governanceLoading}
              className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 disabled:opacity-50"
            >
              <SlidersHorizontal size={13} />
              试算
            </button>
            <button
              type="button"
              onClick={handleSaveGovernance}
              disabled={governanceLoading || !canManageGovernance}
              title={governanceDisabledReason}
              data-testid="technical-kline-save-governance"
              className="inline-flex items-center gap-1.5 rounded-md border border-cyan-200 bg-cyan-50 px-3 py-1.5 text-xs font-medium text-cyan-700 disabled:opacity-50"
            >
              <Save size={13} />
              保存治理
            </button>
            <button
              type="button"
              onClick={handleRollbackGovernance}
              disabled={governanceLoading || !canManageGovernance}
              title={governanceDisabledReason}
              data-testid="technical-kline-rollback-governance"
              className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 disabled:opacity-50"
            >
              <RotateCcw size={13} />
              回滚默认
            </button>
          </div>
        }
      >
        <div className="grid gap-3 md:grid-cols-4">
          {[
            ['ma_short', 'MA 短窗'],
            ['ma_medium', 'MA 中窗'],
            ['ma_long', 'MA 长窗'],
            ['high_volume_ratio', '放量阈值'],
            ['volume_recent', '近期量窗'],
            ['volume_baseline', '基准量窗'],
            ['support_short', '短支撑窗'],
            ['support_long', '长支撑窗'],
          ].map(([key, label]) => (
            <label key={key} className="space-y-1 text-xs text-slate-600">
              <span>{label}</span>
              <input
                type="number"
                value={(governanceDraft as Record<string, any>)[key] ?? ''}
                onChange={(event) => updateGovernanceNumber(key as keyof TechnicalKlineGovernanceConfig, event.target.value)}
                className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm text-slate-900"
              />
            </label>
          ))}
          <label className="space-y-1 text-xs text-slate-600 md:col-span-2">
            <span>案例分类</span>
            <select
              value={governanceDraft.case_classification ?? ''}
              onChange={(event) => setGovernanceDraft((draft) => ({ ...draft, case_classification: event.target.value as TechnicalKlineGovernanceConfig['case_classification'] }))}
              className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm text-slate-900"
            >
              <option value="">规则推导</option>
              <option value="valid">有效样本</option>
              <option value="misjudge">误判样本</option>
              <option value="insufficient_data">数据不足样本</option>
            </select>
          </label>
        </div>
        {governanceError ? (
          <div className="mt-3 rounded-md border border-red-200 bg-red-50 p-3 text-xs text-red-700">{governanceError}</div>
        ) : null}
        {governanceActionMessage ? (
          <div className="mt-3 rounded-md border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-700">{governanceActionMessage}</div>
        ) : null}
        {!governanceError && governance ? (
          <div className="mt-4 grid gap-3 md:grid-cols-3">
            <div className="rounded-md bg-slate-50 p-3">
              <div className="text-xs text-slate-500">提示词版本</div>
              <div className="mt-1 text-sm font-semibold text-slate-950">{governance.promptGovernance.version}</div>
              <div className="mt-1 font-mono text-xs text-slate-500">{governance.promptGovernance.promptHash}</div>
            </div>
            <div className="rounded-md bg-slate-50 p-3">
              <div className="text-xs text-slate-500">配置哈希</div>
              <div className="mt-1 font-mono text-sm font-semibold text-slate-950">{governance.analysisConfig.configHash}</div>
              <div className="mt-1 text-xs text-slate-500">参数随本次请求进入 Agent 输出。</div>
            </div>
            <div className="rounded-md bg-slate-50 p-3">
              <div className="text-xs text-slate-500">案例治理</div>
              <div className="mt-1 text-sm font-semibold text-slate-950">{governance.caseClassification.selected}</div>
              <div className="mt-1 text-xs text-slate-500">{governance.caseClassification.allowedValues.join(' / ')}</div>
            </div>
          </div>
        ) : !governanceError ? (
          <div className="mt-3 rounded-md bg-slate-50 p-3 text-xs text-slate-500">{governanceLoading ? '正在读取治理配置...' : '等待治理配置'}</div>
        ) : null}
        {governance ? (
          <div className="mt-4 rounded-md border border-slate-200 p-3">
            <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-950">
              <CheckCircle2 size={15} />
              技术面案例沉淀
            </div>
            <div className="grid gap-3 md:grid-cols-[1fr_auto]">
              <input
                value={caseNote}
                onChange={(event) => setCaseNote(event.target.value)}
                placeholder="记录误判、有效或数据不足原因"
                className="rounded-md border border-slate-200 px-3 py-2 text-sm text-slate-900"
              />
              <button
                type="button"
                onClick={handleRecordCase}
                disabled={caseRecording || !canRecordCase}
                title={caseDisabledReason}
                data-testid="technical-kline-record-current-case"
                className="inline-flex items-center justify-center gap-1.5 rounded-md border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 disabled:opacity-50"
              >
                <CheckCircle2 size={14} />
                沉淀案例
              </button>
            </div>
            <div className="mt-2 text-xs text-slate-500">
              已沉淀 {governance.savedGovernance?.cases.length ?? 0} 条；最近更新 {governance.savedGovernance?.updatedAt || '-'}。
            </div>
            {caseMessage ? <div className="mt-2 text-xs text-slate-600">{caseMessage}</div> : null}
          </div>
        ) : null}
      </Card>

      <TechnicalKlineSummaryCard symbol={currentRun.stockCode} config={appliedGovernance} />

      <Card
        title="信号回测"
        action={
          <button
            type="button"
            onClick={() => loadBacktest(horizonDays)}
            disabled={backtestLoading}
            className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 disabled:opacity-50"
          >
            <RefreshCw size={13} className={backtestLoading ? 'animate-spin' : ''} />
            刷新
          </button>
        }
      >
        <div className="mb-4 flex flex-wrap items-center gap-2">
          {[3, 5, 10].map((days) => (
            <button
              key={days}
              type="button"
              onClick={() => {
                setHorizonDays(days)
              }}
              className={`rounded-md border px-3 py-1.5 text-xs font-medium ${
                horizonDays === days ? 'border-cyan-500 bg-cyan-50 text-cyan-700' : 'border-slate-200 text-slate-600'
              }`}
            >
              {days} 日验证
            </button>
          ))}
          <Badge status={backtestBadgeStatus}>{backtestBadgeText}</Badge>
          <span className="text-xs text-slate-500">只验证 BULLISH / BEARISH 标签命中率，不生成交易动作</span>
        </div>

        {backtestError ? (
          <div className={backtestErrorClass}>{backtestError}</div>
        ) : !backtest ? (
          <div className="rounded-md border border-slate-200 bg-slate-50 p-4 text-sm text-slate-500">
            {backtestLoading ? '正在读取真实日线并滚动验证标签...' : '等待回测结果'}
          </div>
        ) : (
          <div className="space-y-4">
            <div className="grid gap-3 md:grid-cols-4">
              {[
                { label: '样本数', value: backtest.sampleCount },
                { label: '评估标签', value: backtest.evaluatedSignals },
                { label: '命中率', value: pct(backtest.hitRate, 0) },
                { label: '平均前瞻收益', value: pct(backtest.averageForwardReturn, 2) },
              ].map((item) => (
                <MetricTile key={item.label} label={item.label} value={item.value} className="!rounded-md !bg-slate-50 !p-3 !shadow-none" />
              ))}
            </div>

            <div className="rounded-md border border-slate-200 p-4">
              <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-950">
                <BarChart3 size={16} />
                偏向拆分
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                {(['BULLISH', 'BEARISH'] as const).map((bias) => {
                  const bucket = backtest.byBias[bias]
                  return (
                    <div key={bias} className="rounded-md bg-slate-50 p-3">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-xs font-medium text-slate-500">{bias}</span>
                        <Badge status={bucket.hitRate != null && bucket.hitRate >= 0.5 ? 'PASS' : 'REVIEW_ONLY'}>{bucket.count}</Badge>
                      </div>
                      <div className="mt-2 text-sm text-slate-600">命中率 {pct(bucket.hitRate, 0)} · 平均前瞻收益 {pct(bucket.averageForwardReturn, 2)}</div>
                    </div>
                  )
                })}
              </div>
            </div>

            <div className="rounded-md border border-slate-200 p-4">
              <div className="mb-3 text-sm font-semibold text-slate-950">最近标签样本</div>
              {backtest.recentSignals.length === 0 ? (
                <div className="rounded-md bg-slate-50 p-3 text-xs text-slate-500">{backtest.summary}</div>
              ) : (
                <TableShell>
                  <table className="institution-table">
                    <thead className="text-slate-500">
                      <tr>
                        <th className="px-2 py-2 font-medium">日期</th>
                        <th className="px-2 py-2 font-medium">标签</th>
                        <th className="px-2 py-2 font-medium">置信度</th>
                        <th className="px-2 py-2 font-medium">前瞻收益</th>
                        <th className="px-2 py-2 font-medium">命中</th>
                      </tr>
                    </thead>
                    <tbody>
                      {backtest.recentSignals.map((signal) => (
                        <tr key={`${signal.tradeDate}-${signal.bias}`} className="border-t border-slate-100">
                          <td className="px-2 py-2 font-mono text-slate-600">{signal.tradeDate}</td>
                          <td className="px-2 py-2"><Badge status={signal.bias === 'BULLISH' ? 'PASS' : 'WARN'}>{signal.bias}</Badge></td>
                          <td className="px-2 py-2 text-slate-600">{pct(signal.confidence, 0)}</td>
                          <td className="px-2 py-2 text-slate-600">{pct(signal.forwardReturn, 2)}</td>
                          <td className="px-2 py-2"><Badge status={signal.hit ? 'PASS' : 'FAIL'}>{signal.hit ? 'YES' : 'NO'}</Badge></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </TableShell>
              )}
              <div className="mt-3 text-xs leading-5 text-slate-500">{backtest.summary}</div>
            </div>
          </div>
        )}
      </Card>

    </div>
  )
}
