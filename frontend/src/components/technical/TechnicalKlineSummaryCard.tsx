import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertTriangle, RefreshCw, ShieldCheck, Target, TrendingDown, TrendingUp } from 'lucide-react'
import { Card } from '../common/Card'
import { Badge } from '../common/Badge'
import { getTechnicalKlineAnalysis, TechnicalKlineAnalysis, TechnicalKlineGovernanceConfig } from '../../api/technicalKlineClient'

function pct(value?: number | null, digits = 1) {
  if (typeof value !== 'number' || Number.isNaN(value)) return 'N/A'
  return `${(value * 100).toFixed(digits)}%`
}

function num(value?: number | null, digits = 2) {
  if (typeof value !== 'number' || Number.isNaN(value)) return 'N/A'
  return value.toFixed(digits)
}

function biasLabel(value: string) {
  const labels: Record<string, string> = {
    BULLISH: '偏强',
    NEUTRAL: '中性',
    BEARISH: '偏弱',
    INSUFFICIENT_DATA: '数据不足',
  }
  return labels[value] ?? value
}

function biasStatus(value: string) {
  if (value === 'BULLISH') return 'PASS'
  if (value === 'BEARISH') return 'WARN'
  if (value === 'INSUFFICIENT_DATA') return 'SKIPPED'
  return 'REVIEW_ONLY'
}

function alignmentLabel(value: string) {
  const labels: Record<string, string> = {
    UPWARD_ALIGNED: '周月同向向上',
    DOWNWARD_ALIGNED: '周月同向向下',
    MIXED: '多周期分歧',
    UNKNOWN: '样本不足',
  }
  return labels[value] ?? value
}

function indicatorBadgeStatus(status?: string) {
  return status === 'AVAILABLE' ? 'PASS' : 'SKIPPED'
}

function concentrationStatus(level?: string) {
  if (level === 'HIGH') return 'PASS'
  if (level === 'MEDIUM') return 'REVIEW_ONLY'
  if (level === 'LOW') return 'WARN'
  return 'SKIPPED'
}

function pressureStatus(level?: string) {
  if (level === 'HIGH') return 'WARN'
  if (level === 'MEDIUM') return 'REVIEW_ONLY'
  if (level === 'LOW') return 'PASS'
  return 'SKIPPED'
}

function supportStatus(level?: string) {
  if (level === 'HIGH') return 'PASS'
  if (level === 'MEDIUM') return 'REVIEW_ONLY'
  if (level === 'LOW') return 'WARN'
  return 'SKIPPED'
}

function chipSourceLabel(source?: string, sourceKind?: string) {
  if (source === 'TUSHARE_CYQ_CHIPS') return '真实 Tushare 筹码分布'
  if (source === 'TUSHARE_CYQ_PERF') return '真实 Tushare 筹码胜率'
  if (sourceKind === 'I' || source === 'KLINE_VOLUME_PRICE_PROXY') return 'K 线代理估算'
  return source || 'N/A'
}

export function TechnicalKlineSummaryCard({ symbol, compact = false, config }: { symbol: string; compact?: boolean; config?: TechnicalKlineGovernanceConfig }) {
  const [analysis, setAnalysis] = useState<TechnicalKlineAnalysis | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    if (!symbol) return
    setLoading(true)
    setError('')
    try {
      setAnalysis(await getTechnicalKlineAnalysis(symbol, config))
    } catch (err) {
      setAnalysis(null)
      setError(err instanceof Error ? err.message : '技术面 K 线 Agent 请求失败')
    } finally {
      setLoading(false)
    }
  }, [symbol, config])

  useEffect(() => {
    load()
  }, [load])

  const canUse = analysis && analysis.status !== 'SKIPPED'
  const indicators = analysis?.technicalIndicators
  const macd = indicators?.macd
  const rsi = indicators?.rsi
  const kdj = indicators?.kdj
  const bollinger = indicators?.bollinger
  const patterns = analysis?.patterns
  const chipAnalysis = analysis?.chipAnalysis
  const Icon = useMemo(() => {
    if (analysis?.technicalBias === 'BULLISH') return TrendingUp
    if (analysis?.technicalBias === 'BEARISH') return TrendingDown
    return ShieldCheck
  }, [analysis?.technicalBias])
  const evidenceStats = analysis ? [
    { label: '收盘', value: num(analysis.trend.close) },
    { label: 'MA5', value: num(analysis.trend.ma5) },
    { label: 'MA10', value: num(analysis.trend.ma10) },
    { label: 'MA20', value: num(analysis.trend.ma20) },
    ...(chipAnalysis ? [
      { label: '筹码成本', value: num(chipAnalysis.averageCostProxy) },
      { label: '距成本', value: pct(chipAnalysis.closeToCostPct) },
      ...(chipAnalysis.winnerRate != null ? [{ label: '胜率', value: pct(chipAnalysis.winnerRate) }] : []),
    ] : []),
  ] : []

  return (
    <Card
      title="技术面 K 线 Agent"
      action={
        <button
          type="button"
          onClick={load}
          disabled={loading || !symbol}
          className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 disabled:opacity-50"
        >
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
          刷新
        </button>
      }
    >
      <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-slate-500">
        <Badge status={analysis?.status ?? 'WAIT'}>{analysis?.status ?? (loading ? 'RUNNING' : 'WAIT')}</Badge>
        {analysis && <Badge status={biasStatus(analysis.technicalBias)}>{biasLabel(analysis.technicalBias)}</Badge>}
        {analysis && <span>置信度：{pct(analysis.confidence, 0)}</span>}
        {analysis && <span>日/周/月：{analysis.dataQuality.dailyCount}/{analysis.dataQuality.weeklyCount}/{analysis.dataQuality.monthlyCount}</span>}
      </div>

      {loading && !analysis ? (
        <div className="rounded-md border border-slate-200 bg-slate-50 p-4 text-sm text-slate-500">正在读取真实 Tushare K 线并计算技术面...</div>
      ) : error ? (
        <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>
      ) : analysis ? (
        <div className="space-y-4">
          <div className="flex items-start gap-3 rounded-md border border-slate-200 bg-slate-50 p-4">
            <div className="grid h-10 w-10 shrink-0 place-items-center rounded-md bg-white text-slate-700">
              <Icon size={18} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-sm font-semibold text-slate-950">{analysis.summaryForDownstream}</div>
              <div className="mt-1 text-xs leading-5 text-slate-500">
                数据策略：只使用真实 Tushare K 线；不可用时跳过分析，不生成图形或结论。
              </div>
              {canUse && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {evidenceStats.map((item) => (
                    <span key={item.label} className="inline-flex items-center gap-1 rounded border border-slate-200 bg-white px-2 py-1 text-xs text-slate-500">
                      {item.label}
                      <strong className="font-semibold text-slate-900">{item.value}</strong>
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>

          {!compact && (
            <div className="grid gap-3 md:grid-cols-3">
              <div className="rounded-md bg-slate-50 p-3">
                <div className="text-xs text-slate-500">收盘 / MA20</div>
                <div className="mt-1 text-lg font-semibold text-slate-950">{num(analysis.trend.close)} / {num(analysis.trend.ma20)}</div>
              </div>
              <div className="rounded-md bg-slate-50 p-3">
                <div className="text-xs text-slate-500">20 日收益</div>
                <div className="mt-1 text-lg font-semibold text-slate-950">{pct(analysis.trend.return20d)}</div>
              </div>
              <div className="rounded-md bg-slate-50 p-3">
                <div className="text-xs text-slate-500">多周期</div>
                <div className="mt-1 text-lg font-semibold text-slate-950">{alignmentLabel(analysis.multiPeriod.alignment)}</div>
              </div>
            </div>
          )}

          {canUse && !compact && (
            <>
              <div className="grid gap-4 lg:grid-cols-2">
                <div className="rounded-md border border-slate-200 p-4">
                  <div className="mb-2 text-sm font-semibold text-slate-950">趋势结构</div>
                  <div className="text-sm leading-6 text-slate-600">{analysis.trend.structure}</div>
                  <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-slate-500">
                    <span>MA5：{num(analysis.trend.ma5)}</span>
                    <span>MA10：{num(analysis.trend.ma10)}</span>
                    <span>MA20：{num(analysis.trend.ma20)}</span>
                    <span>60 日收益：{pct(analysis.trend.return60d)}</span>
                  </div>
                </div>
                <div className="rounded-md border border-slate-200 p-4">
                  <div className="mb-2 text-sm font-semibold text-slate-950">量价与位置</div>
                  <div className="text-sm leading-6 text-slate-600">{analysis.volumePrice.description}</div>
                  <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-slate-500">
                    <span>量比 5/20：{analysis.volumePrice.volumeRatio5v20 == null ? 'N/A' : num(analysis.volumePrice.volumeRatio5v20)}</span>
                    <span>20日支撑：{num(analysis.supportResistance.support20d)}</span>
                    <span>20日压力：{num(analysis.supportResistance.resistance20d)}</span>
                    <span>距压力：{pct(analysis.supportResistance.distanceToResistance20d)}</span>
                  </div>
                </div>
              </div>

              {chipAnalysis && (
                <div className="rounded-md border border-slate-200 p-4">
                  <div className="mb-3 flex items-center justify-between gap-3">
                    <div className="flex items-center gap-2 text-sm font-semibold text-slate-950">
                      <Target size={16} />
                      筹码分析
                    </div>
                    <div className="flex flex-wrap justify-end gap-2">
                      <Badge status={indicatorBadgeStatus(chipAnalysis.status)}>{chipAnalysis.status}</Badge>
                      <Badge status="REVIEW_ONLY">{chipAnalysis.sourceKind === 'C' ? 'C级接口' : chipAnalysis.sourceKind === 'I' ? 'I级推断' : chipAnalysis.sourceKind}</Badge>
                    </div>
                  </div>
                  <div className="text-sm leading-6 text-slate-600">{chipAnalysis.description}</div>
                  <div className="mt-3 grid gap-2 text-xs text-slate-500 sm:grid-cols-2 lg:grid-cols-4">
                    <span>来源：{chipSourceLabel(chipAnalysis.source, chipAnalysis.sourceKind)}</span>
                    <span>交易日：{chipAnalysis.tradeDate ?? 'N/A'}</span>
                    <span>平均成本：{num(chipAnalysis.averageCostProxy)}</span>
                    <span>距成本：{pct(chipAnalysis.closeToCostPct)}</span>
                    <span>胜率：{pct(chipAnalysis.winnerRate)}</span>
                    <span>P5 / P50 / P95：{num(chipAnalysis.costPercentiles?.cost5Pct)} / {num(chipAnalysis.costPercentiles?.cost50Pct)} / {num(chipAnalysis.costPercentiles?.cost95Pct)}</span>
                    <span>成本区间：{num(chipAnalysis.costZone?.low)} - {num(chipAnalysis.costZone?.high)}</span>
                    <span>区间量占比：{pct(chipAnalysis.costZone?.volumeRatio)}</span>
                    <span>上方压力：{pct(chipAnalysis.overheadVolumeRatio)}</span>
                    <span>下方支撑：{pct(chipAnalysis.supportVolumeRatio)}</span>
                    <span className="inline-flex items-center gap-1">
                      集中度
                      <Badge status={concentrationStatus(chipAnalysis.concentrationLevel)}>{chipAnalysis.concentrationLevel}</Badge>
                    </span>
                    <span className="inline-flex items-center gap-1">
                      压力/支撑
                      <Badge status={pressureStatus(chipAnalysis.pressureLevel)}>{chipAnalysis.pressureLevel}</Badge>
                      <Badge status={supportStatus(chipAnalysis.supportLevel)}>{chipAnalysis.supportLevel}</Badge>
                    </span>
                  </div>
                  {(chipAnalysis.warnings ?? []).length > 0 && (
                    <div className="mt-3 space-y-1 text-xs leading-5 text-amber-700">
                      {(chipAnalysis.warnings ?? []).map((warning) => <div key={warning}>{warning}</div>)}
                    </div>
                  )}
                </div>
              )}

              <div className="rounded-md border border-slate-200 p-4">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <div className="text-sm font-semibold text-slate-950">指标确认</div>
                  <div className="text-xs text-slate-500">每项指标均带窗口和真实样本数</div>
                </div>
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                  <div className="min-w-0 border-l-2 border-slate-300 pl-3">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-medium text-slate-500">MACD</span>
                      <Badge status={indicatorBadgeStatus(macd?.status)}>{macd?.status ?? 'WAIT'}</Badge>
                    </div>
                    <div className="mt-2 text-sm font-semibold text-slate-950">{num(macd?.histogram, 4)}</div>
                    <div className="mt-1 text-xs leading-5 text-slate-500">{macd?.signal ?? '指标数据暂未返回'}</div>
                    <div className="mt-1 text-[11px] text-slate-400">{macd?.window ?? 'N/A'} · 样本 {macd?.sampleCount ?? 0}</div>
                  </div>
                  <div className="min-w-0 border-l-2 border-slate-300 pl-3">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-medium text-slate-500">RSI</span>
                      <Badge status={indicatorBadgeStatus(rsi?.status)}>{rsi?.status ?? 'WAIT'}</Badge>
                    </div>
                    <div className="mt-2 text-sm font-semibold text-slate-950">{num(rsi?.value, 2)}</div>
                    <div className="mt-1 text-xs leading-5 text-slate-500">{rsi?.signal ?? '指标数据暂未返回'}</div>
                    <div className="mt-1 text-[11px] text-slate-400">窗口 {rsi?.window ?? 'N/A'} · 样本 {rsi?.sampleCount ?? 0}</div>
                  </div>
                  <div className="min-w-0 border-l-2 border-slate-300 pl-3">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-medium text-slate-500">KDJ</span>
                      <Badge status={indicatorBadgeStatus(kdj?.status)}>{kdj?.status ?? 'WAIT'}</Badge>
                    </div>
                    <div className="mt-2 text-sm font-semibold text-slate-950">K {num(kdj?.k, 1)} / D {num(kdj?.d, 1)}</div>
                    <div className="mt-1 text-xs leading-5 text-slate-500">{kdj?.signal ?? '指标数据暂未返回'}</div>
                    <div className="mt-1 text-[11px] text-slate-400">窗口 {kdj?.window ?? 'N/A'} · 样本 {kdj?.sampleCount ?? 0}</div>
                  </div>
                  <div className="min-w-0 border-l-2 border-slate-300 pl-3">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-medium text-slate-500">布林带</span>
                      <Badge status={indicatorBadgeStatus(bollinger?.status)}>{bollinger?.status ?? 'WAIT'}</Badge>
                    </div>
                    <div className="mt-2 text-sm font-semibold text-slate-950">{pct(bollinger?.position, 0)}</div>
                    <div className="mt-1 text-xs leading-5 text-slate-500">{bollinger?.signal ?? '指标数据暂未返回'}</div>
                    <div className="mt-1 text-[11px] text-slate-400">窗口 {bollinger?.window ?? 'N/A'} · 样本 {bollinger?.sampleCount ?? 0}</div>
                  </div>
                </div>
              </div>

              <div className="rounded-md border border-slate-200 p-4">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <div className="text-sm font-semibold text-slate-950">形态识别</div>
                  <Badge status={(patterns?.items ?? []).some((item) => item.severity === 'WARN') ? 'WARN' : 'PASS'}>{patterns?.status ?? 'WAIT'}</Badge>
                </div>
                {(patterns?.items ?? []).length > 0 ? (
                  <div className="grid gap-2 md:grid-cols-2">
                    {(patterns?.items ?? []).map((item) => (
                      <div key={item.code} className="rounded-md bg-slate-50 p-3">
                        <div className="flex items-center justify-between gap-2">
                          <div className="text-xs font-semibold text-slate-700">{item.label}</div>
                          <Badge status={item.severity === 'WARN' ? 'WARN' : 'REVIEW_ONLY'}>{item.severity}</Badge>
                        </div>
                        <div className="mt-1 text-xs leading-5 text-slate-500">{item.description}</div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="rounded-md bg-slate-50 p-3 text-xs leading-5 text-slate-500">
                    {patterns ? '未触发跳空、长上影、放量滞涨、缩量反弹等重点形态。' : '形态识别数据暂未返回。'}
                  </div>
                )}
              </div>
            </>
          )}

          {analysis.risks.length > 0 && !compact && (
            <div className="rounded-md border border-amber-200 bg-amber-50 p-4">
              <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-amber-900">
                <AlertTriangle size={16} />
                风险与数据限制
              </div>
              <div className="space-y-1 text-sm leading-6 text-amber-800">
                {analysis.risks.map((risk) => <div key={risk}>{risk}</div>)}
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="rounded-md border border-slate-200 bg-slate-50 p-4 text-sm text-slate-500">等待当前分析任务股票代码。</div>
      )}
    </Card>
  )
}
