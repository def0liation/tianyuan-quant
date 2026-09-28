import {
  Activity,
  AlertTriangle,
  Beaker,
  Gauge,
  ShieldAlert,
} from 'lucide-react'
import { useState, type ReactNode } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { useAnalysisStore } from '../../store/useAnalysisStore'
import type { BottomResearchResult } from '../../types'
import { Badge } from '../common/Badge'
import { Card } from '../common/Card'
import { MetricTile, TableShell } from '../common/Material'
import { SectionTitle } from '../common/SectionTitle'

const PROBABILITY_PATH_HORIZONS = [5, 20] as const

type HorizonProbabilitySeries = NonNullable<BottomResearchResult['horizonProbabilitySeries']>[number]
type HorizonProbabilityPoint = HorizonProbabilitySeries['series'][number]

function pct(value?: number | null) {
  if (typeof value !== 'number' || Number.isNaN(value)) return 'N/A'
  return `${(value * 100).toFixed(1)}%`
}

function num(value?: number | null, digits = 3) {
  if (typeof value !== 'number' || Number.isNaN(value)) return 'N/A'
  return value.toFixed(digits)
}

function statusFor(bottom?: BottomResearchResult | null) {
  const status = String(bottom?.status || '').toUpperCase()
  if (status === 'PASS') return 'PASS'
  if (status === 'SKIPPED') return 'SKIPPED'
  return 'WARN'
}

function regimeLabel(value?: string) {
  if (value === 'BOTTOM_REPAIR_ZONE') return 'MFE有利区间'
  if (value === 'BOTTOM_REPAIR_WATCH') return 'MFE观察'
  if (value === 'BREAKDOWN_RISK') return 'MAE跌破风险'
  if (value === 'SUPPORTING_ONLY') return '仅辅助证据'
  if (value === 'NEUTRAL') return '中性'
  return value || '未生成'
}

function evidenceStatus(value?: string) {
  if (value === 'MEDIUM' || value === 'HIGH') return 'PASS'
  if (value === 'LOW') return 'WARN'
  return 'SKIPPED'
}

function trendBiasLabel(value?: string) {
  if (value === 'UP') return 'MFE偏有利'
  if (value === 'DOWN') return 'MAE风险偏高'
  if (value === 'SIDEWAYS') return '震荡观察'
  if (value === 'INSUFFICIENT_DATA') return '样本不足'
  return value || '未生成'
}

function trendStatus(value?: string) {
  if (value === 'UP') return 'PASS'
  if (value === 'DOWN') return 'WARN'
  return 'REVIEW_ONLY'
}

function shortTradeDate(value?: string | null) {
  const formatted = formatTradeDate(value)
  return formatted ? formatted.slice(5) : ''
}

function isLaterTradeDate(value?: string | null, baseline?: string | null) {
  const current = formatTradeDate(value)
  const previous = formatTradeDate(baseline)
  return Boolean(current && previous && current > previous)
}

function currentPrediction(bottom?: BottomResearchResult | null) {
  if (bottom?.currentPrediction?.tradeDate) return bottom.currentPrediction
  const tradeDate = formatTradeDate(bottom?.provenance?.lastTradeDate)
  const hasProbability = typeof bottom?.bottomRepairProbability === 'number' || typeof bottom?.breakdownRiskProbability === 'number'
  if (!tradeDate || !hasProbability) return null
  return {
    tradeDate,
    bottomRepairProbability: bottom?.bottomRepairProbability,
    breakdownRiskProbability: bottom?.breakdownRiskProbability,
    regimeState: bottom?.regimeState,
    labelStatus: 'UNLABELED_NOWCAST_LEGACY',
    horizonDays: Number(bottom?.config?.horizon_days || 0),
    simulation_only: true,
    is_real_trade: false,
  }
}

function fallbackTrendProbabilities(repair?: number | null, breakdown?: number | null) {
  if (typeof repair !== 'number' || typeof breakdown !== 'number') return undefined
  const up = Math.max(0.05, 0.25 + repair * 0.55 - breakdown * 0.25)
  const down = Math.max(0.05, 0.20 + breakdown * 0.65 - repair * 0.20)
  const sideways = Math.max(0.05, 0.35 + Math.max(0, 0.50 - Math.abs(repair - breakdown)) * 0.20)
  const total = up + sideways + down
  return {
    up: up / total,
    sideways: sideways / total,
    down: down / total,
  }
}

function bottomHorizonForecasts(bottom?: BottomResearchResult | null): NonNullable<BottomResearchResult['horizonForecasts']> {
  const forecasts = nativeHorizonForecasts(bottom)
  if (forecasts.length > 0) return forecasts
  const current = currentPrediction(bottom)
  if (!bottom || !current) return []
  const repair = current.bottomRepairProbability ?? bottom.bottomRepairProbability
  const breakdown = current.breakdownRiskProbability ?? bottom.breakdownRiskProbability
  return [
    {
      horizonDays: Number(current.horizonDays || bottom.config?.horizon_days || 20),
      status: bottom.status,
      bottomRepairProbability: repair,
      breakdownRiskProbability: breakdown,
      trendProbabilities: fallbackTrendProbabilities(repair, breakdown),
      trendBias: current.regimeState === 'BREAKDOWN_RISK' ? 'DOWN' : current.regimeState === 'BOTTOM_REPAIR_ZONE' ? 'UP' : 'SIDEWAYS',
      confidence: undefined,
      sampleCount: bottom.modelDiagnostics?.sampleCount,
      evidenceGrade: bottom.modelDiagnostics?.evidenceGrade,
      regimeState: current.regimeState,
      currentPrediction: current,
    },
  ]
}

function nativeHorizonForecasts(bottom?: BottomResearchResult | null): NonNullable<BottomResearchResult['horizonForecasts']> {
  return (bottom?.horizonForecasts || [])
    .filter((item) => typeof item?.horizonDays === 'number')
    .slice()
    .sort((left, right) => left.horizonDays - right.horizonDays)
}

function expectedHorizonDays(bottom?: BottomResearchResult | null) {
  const rawList = Array.isArray(bottom?.config?.horizon_days_list) ? bottom?.config?.horizon_days_list : [5, 20, 60]
  const primary = Number(bottom?.config?.horizon_days || 20)
  const values = [...rawList, primary]
    .map((item) => Number(item))
    .filter((item) => Number.isFinite(item) && item > 0)
  return Array.from(new Set(values)).sort((left, right) => left - right)
}

function horizonForecastNotice(bottom?: BottomResearchResult | null) {
  if (bottom?.trendSynthesis?.mainConclusion) return bottom.trendSynthesis.mainConclusion
  if (nativeHorizonForecasts(bottom).length === 0 && bottomHorizonForecasts(bottom).length > 0) {
    return `当前运行未保存多周期 horizonForecasts，仅能兼容展示主周期 ${bottom?.config?.horizon_days || 20} 日；重跑任务后会生成 ${expectedHorizonDays(bottom).join('/')} 日预测。`
  }
  return '当前仅生成主周期MFE/MAE路径研究概率。'
}

function nativeHorizonProbabilitySeries(bottom?: BottomResearchResult | null): HorizonProbabilitySeries[] {
  return (bottom?.horizonProbabilitySeries || [])
    .filter((item) => typeof item?.horizonDays === 'number' && Array.isArray(item.series))
    .slice()
    .sort((left, right) => left.horizonDays - right.horizonDays)
}

function legacyHorizonProbabilitySeries(bottom?: BottomResearchResult | null): HorizonProbabilitySeries[] {
  const horizonDays = Number(bottom?.currentPrediction?.horizonDays || bottom?.config?.horizon_days || 20)
  const series: HorizonProbabilityPoint[] = (bottom?.probabilitySeries || []).map((item) => ({
    date: formatTradeDate(item.tradeDate),
    repairProb: item.bottomRepairProbability ?? null,
    breakdownRisk: item.breakdownRiskProbability ?? null,
    bottomLabel: item.bottomLabel,
    breakdownLabel: item.breakdownLabel,
    regimeState: item.regimeState,
    labelWindowStart: item.labelWindowStart,
    labelWindowEnd: item.labelWindowEnd,
    horizonDays,
  }))
  const current = currentPrediction(bottom)
  if (current && (typeof current.bottomRepairProbability === 'number' || typeof current.breakdownRiskProbability === 'number')) {
    series.push({
      date: formatTradeDate(current.tradeDate),
      repairProb: null,
      breakdownRisk: null,
      predictionRepairProb: current.bottomRepairProbability ?? null,
      predictionBreakdownRisk: current.breakdownRiskProbability ?? null,
      regimeState: current.regimeState,
      labelStatus: current.labelStatus || 'UNLABELED_NOWCAST_LEGACY',
      horizonDays,
      simulation_only: true,
      is_real_trade: false,
    })
  }
  return series.length > 0 ? [{ horizonDays, series }] : []
}

function bottomHorizonProbabilitySeries(bottom?: BottomResearchResult | null): HorizonProbabilitySeries[] {
  const nativeSeries = nativeHorizonProbabilitySeries(bottom)
  return nativeSeries.length > 0 ? nativeSeries : legacyHorizonProbabilitySeries(bottom)
}

function probabilityHorizonOptions(seriesItems: HorizonProbabilitySeries[]): number[] {
  const available = new Set(seriesItems.map((item) => item.horizonDays))
  const supported = PROBABILITY_PATH_HORIZONS.filter((horizonDays) => available.has(horizonDays))
  if (supported.length > 0) return supported
  const fallback = seriesItems.find((item) => item.horizonDays === 20) || seriesItems[0]
  return fallback ? [fallback.horizonDays] : [...PROBABILITY_PATH_HORIZONS]
}

function probabilitySeriesForHorizon(seriesItems: HorizonProbabilitySeries[], horizonDays: number) {
  return seriesItems.find((item) => item.horizonDays === horizonDays)?.series || []
}

function isHistoricalProbabilityPoint(item: HorizonProbabilityPoint) {
  return typeof item.repairProb === 'number' || typeof item.breakdownRisk === 'number'
}

function isPredictionProbabilityPoint(item: HorizonProbabilityPoint) {
  return typeof item.predictionRepairProb === 'number' || typeof item.predictionBreakdownRisk === 'number'
}

function latestPredictionPoint(series: HorizonProbabilityPoint[]) {
  return series.slice().reverse().find(isPredictionProbabilityPoint)
}

function chartData(seriesItems: HorizonProbabilitySeries[], horizonDays: number) {
  const series = probabilitySeriesForHorizon(seriesItems, horizonDays)
  const historical = series
    .filter(isHistoricalProbabilityPoint)
    .slice(-80)
    .map((item) => ({
      date: shortTradeDate(item.date),
      fullDate: formatTradeDate(item.date),
      repairHistorical: typeof item.repairProb === 'number' ? item.repairProb * 100 : null,
      breakdownHistorical: typeof item.breakdownRisk === 'number' ? item.breakdownRisk * 100 : null,
      repairNowcast: null as number | null,
      breakdownNowcast: null as number | null,
      pointType: 'HISTORICAL',
    }))
  const current = latestPredictionPoint(series)
  const latest = historical[historical.length - 1]
  if (!latest || !current || !isLaterTradeDate(current.date, latest.fullDate)) {
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
      date: shortTradeDate(current.date),
      fullDate: formatTradeDate(current.date),
      repairHistorical: null,
      breakdownHistorical: null,
      repairNowcast: typeof current.predictionRepairProb === 'number' ? current.predictionRepairProb * 100 : null,
      breakdownNowcast: typeof current.predictionBreakdownRisk === 'number' ? current.predictionBreakdownRisk * 100 : null,
      pointType: current.labelStatus || 'UNLABELED_NOWCAST',
    },
  ]
}

function formatTradeDate(value?: string | null) {
  const raw = String(value || '').trim()
  if (!raw) return ''
  if (/^\d{8}$/.test(raw)) return `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}`
  if (/^\d{4}-\d{2}-\d{2}/.test(raw)) return raw.slice(0, 10)
  return raw
}

function probabilityWindow(
  bottom: BottomResearchResult | null | undefined,
  seriesItems: HorizonProbabilitySeries[],
  horizonDays: number,
) {
  const series = probabilitySeriesForHorizon(seriesItems, horizonDays)
  const historical = series.filter(isHistoricalProbabilityPoint).slice(-80)
  const first = historical[0]
  const last = historical[historical.length - 1]
  const current = latestPredictionPoint(series)
  const currentTradeDate = formatTradeDate(current?.date)
  const lastTradeDate = formatTradeDate(last?.date)
  return {
    sampleCount: historical.length,
    firstTradeDate: formatTradeDate(first?.date),
    lastTradeDate,
    labelWindowEnd: formatTradeDate(last?.labelWindowEnd),
    sourceLastTradeDate: formatTradeDate(bottom?.provenance?.lastTradeDate),
    horizonDays,
    currentTradeDate,
    hasNowcast: isLaterTradeDate(currentTradeDate, lastTradeDate),
  }
}

function walkMetric(model?: Record<string, any>) {
  const walk = model?.walkForward || {}
  return {
    folds: Number(walk.foldCount || 0),
    brier: typeof walk.brier === 'number' ? walk.brier.toFixed(4) : 'N/A',
    prAuc: typeof walk.prAuc === 'number' ? walk.prAuc.toFixed(4) : 'N/A',
  }
}

function matrixRows(matrix?: number[][]) {
  return Array.isArray(matrix) ? matrix.slice(0, 4) : []
}

function leakagePolicyText(value?: string | null) {
  const policy = String(value || '').trim()
  if (!policy) return '特征只使用 t 日及以前数据；标签仅在历史训练窗口中使用未来区间。'
  return policy
    .replace('features_use_rows_ending_at_t', '特征只使用 t 日及以前数据')
    .replace('labels_use_future_window_only_for_historical_training', '标签仅在历史训练窗口中使用未来区间')
    .replace(/;\s*/g, '；')
}

export function BottomResearchPage() {
  const [selectedProbabilityHorizon, setSelectedProbabilityHorizon] = useState(20)
  const { currentRun } = useAnalysisStore()
  const bottom = currentRun?.mfeMaeResearch ?? currentRun?.bottomResearch
  const diagnostics = (bottom?.modelDiagnostics ?? {}) as NonNullable<BottomResearchResult['modelDiagnostics']>
  const riemann = (bottom?.riemannianFeatures ?? {}) as NonNullable<BottomResearchResult['riemannianFeatures']>
  const envelope = (bottom?.positionEnvelope ?? {}) as NonNullable<BottomResearchResult['positionEnvelope']>
  const repairWalk = walkMetric(diagnostics.bottomRepairModel)
  const breakdownWalk = walkMetric(diagnostics.breakdownRiskModel)
  const horizonForecastItems = bottomHorizonForecasts(bottom)
  const probabilitySeriesItems = bottomHorizonProbabilitySeries(bottom)
  const probabilityHorizonTabs = probabilityHorizonOptions(probabilitySeriesItems)
  const activeProbabilityHorizon = probabilityHorizonTabs.includes(selectedProbabilityHorizon)
    ? selectedProbabilityHorizon
    : probabilityHorizonTabs.includes(20)
      ? 20
      : probabilityHorizonTabs[0] || 20
  const data = chartData(probabilitySeriesItems, activeProbabilityHorizon)
  const probabilityWindowInfo = probabilityWindow(bottom, probabilitySeriesItems, activeProbabilityHorizon)
  const usesLegacyProbabilityPath = nativeHorizonProbabilitySeries(bottom).length === 0 && probabilitySeriesItems.length > 0

  if (!currentRun) return <div className="text-sm text-slate-500">加载中...</div>

  return (
    <div className="space-y-6">
      <SectionTitle
        title="MFE/MAE路径研究"
        subtitle="mfe_mae_path_research 概率证据"
        dataMode={currentRun.dataMode}
      />

      {!bottom ? (
        <Card>
          <div className="flex items-start gap-3 text-sm text-slate-600">
            <AlertTriangle size={18} className="mt-0.5 text-amber-600" />
            <div>当前运行还没有 MFE/MAE 路径研究输出。仅 STANDARD_MODE / DEEP_MODE 会执行该节点。</div>
          </div>
        </Card>
      ) : (
        <>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <MetricCard icon={<Beaker size={18} />} label="MFE有利概率" value={pct(bottom.mfeFavorableProbability ?? bottom.bottomRepairProbability)} status={statusFor(bottom)} />
            <MetricCard icon={<ShieldAlert size={18} />} label="MAE跌破风险" value={pct(bottom.maeBreachProbability ?? bottom.breakdownRiskProbability)} status={(bottom.maeBreachProbability ?? bottom.breakdownRiskProbability ?? 0) >= 0.6 ? 'BLOCK_BUY' : 'WARN'} />
            <MetricCard icon={<Activity size={18} />} label="状态" value={regimeLabel(bottom.regimeState)} status={statusFor(bottom)} />
            <MetricCard icon={<Gauge size={18} />} label="证据等级" value={String(diagnostics.evidenceGrade || 'LOW')} status={evidenceStatus(String(diagnostics.evidenceGrade || 'LOW'))} />
          </div>

          <Card title="未来趋势多周期预测">
            <div className="mb-3 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm leading-6 text-slate-700">
              {horizonForecastNotice(bottom)}
            </div>
            <div className="grid gap-3 md:grid-cols-3">
              {horizonForecastItems.slice(0, 3).map((forecast) => (
                <div key={forecast.horizonDays} className="rounded-md border border-slate-200 bg-white p-3">
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-sm font-semibold text-slate-950">{forecast.horizonDays}日</div>
                    <Badge status={trendStatus(forecast.trendBias)}>{trendBiasLabel(forecast.trendBias)}</Badge>
                  </div>
                  <div className="mt-3 grid grid-cols-3 gap-2">
                    <InlineMetric label="上涨" value={pct(forecast.trendProbabilities?.up)} />
                    <InlineMetric label="MFE有利" value={pct(forecast.mfeFavorableProbability ?? forecast.bottomRepairProbability)} />
                    <InlineMetric label="MAE风险" value={pct(forecast.maeBreachProbability ?? forecast.breakdownRiskProbability)} />
                  </div>
                  <div className="mt-3 text-xs leading-5 text-slate-500">
                    置信 {pct(forecast.confidence)} · 样本 {forecast.sampleCount ?? 0} · 证据 {forecast.evidenceGrade || 'LOW'}
                  </div>
                </div>
              ))}
              {horizonForecastItems.length === 0 ? (
                <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                  历史运行未记录多周期预测；请重跑任务以生成 5/20/60 日趋势。
                </div>
              ) : null}
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              {(bottom.trendSynthesis?.keyDrivers || []).map((item) => <Badge key={item} status="PASS">{item}</Badge>)}
              {(bottom.trendSynthesis?.riskFlags || []).map((item) => <Badge key={item} status="WARN">{item}</Badge>)}
            </div>
          </Card>

          <Card title="概率路径">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div className="text-sm font-semibold text-slate-900">预测周期</div>
              <div className="inline-flex rounded-md border border-slate-200 bg-slate-50 p-1" role="tablist" aria-label="概率路径预测周期">
                {PROBABILITY_PATH_HORIZONS.map((horizonDays) => {
                  const available = probabilityHorizonTabs.includes(horizonDays)
                  const active = activeProbabilityHorizon === horizonDays
                  return (
                    <button
                      key={horizonDays}
                      type="button"
                      aria-pressed={active}
                      disabled={!available}
                      onClick={() => setSelectedProbabilityHorizon(horizonDays)}
                      className={`min-w-[64px] rounded px-3 py-1.5 text-sm font-semibold transition ${
                        active
                          ? 'bg-blue-600 text-white shadow-sm'
                          : 'text-slate-600 hover:bg-white hover:text-slate-950 disabled:cursor-not-allowed disabled:text-slate-300 disabled:hover:bg-transparent'
                      }`}
                    >
                      {horizonDays}日
                    </button>
                  )
                })}
              </div>
            </div>
            {usesLegacyProbabilityPath ? (
              <div className="mb-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
                当前运行未保存多周期概率路径，仅能兼容展示主周期 {probabilityWindowInfo.horizonDays || bottom?.config?.horizon_days || 20} 日；重跑任务后会生成 5/20 日路径。
              </div>
            ) : null}
            {probabilityWindowInfo.sampleCount > 0 ? (
              <div className="mb-3 rounded-md border border-blue-100 bg-blue-50 px-3 py-2 text-xs leading-5 text-blue-900">
                {activeProbabilityHorizon}日实线为最近 {probabilityWindowInfo.sampleCount} 个可回测历史样本：
                {probabilityWindowInfo.firstTradeDate} 至 {probabilityWindowInfo.lastTradeDate}。
                {probabilityWindowInfo.sourceLastTradeDate ? ` 原始K线最后交易日：${probabilityWindowInfo.sourceLastTradeDate}。` : ''}
                {probabilityWindowInfo.hasNowcast && probabilityWindowInfo.currentTradeDate
                  ? ` 虚线延伸至最新未标注预测 ${probabilityWindowInfo.currentTradeDate}；虚线不参与 Brier / PR-AUC / verdict 接受判断。`
                  : ''}
                {probabilityWindowInfo.horizonDays && probabilityWindowInfo.labelWindowEnd
                  ? ` 为避免未来函数，${probabilityWindowInfo.horizonDays} 个交易日标签窗口必须完整，所以可回测历史线最后一个样本停在 ${probabilityWindowInfo.lastTradeDate}，标签窗口延伸至 ${probabilityWindowInfo.labelWindowEnd}。`
                  : ''}
              </div>
            ) : null}
            {data.length > 0 ? (
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={data}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                    <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                    <YAxis domain={[0, 100]} unit="%" tick={{ fontSize: 11 }} />
                    <Tooltip formatter={(value: unknown) => (typeof value === 'number' ? `${value.toFixed(1)}%` : String(value ?? ''))} />
                    <Line type="monotone" dataKey="repairHistorical" name={`${activeProbabilityHorizon}日历史标签（MFE有利）`} stroke="#0f766e" strokeWidth={2} dot={false} />
                    <Line type="monotone" dataKey="breakdownHistorical" name={`${activeProbabilityHorizon}日历史标签（MAE触发）`} stroke="#dc2626" strokeWidth={2} dot={false} />
                    <Line type="monotone" dataKey="repairNowcast" name={`${activeProbabilityHorizon}日最新代理概率（MFE有利）`} stroke="#0f766e" strokeWidth={2} strokeDasharray="5 4" dot={{ r: 3 }} />
                    <Line type="monotone" dataKey="breakdownNowcast" name={`${activeProbabilityHorizon}日最新代理概率（MAE触发）`} stroke="#dc2626" strokeWidth={2} strokeDasharray="5 4" dot={{ r: 3 }} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                样本或正负样本不足，当前仅保留辅助证据。
              </div>
            )}
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="黎曼结构特征">
              <div className="grid gap-3 sm:grid-cols-3">
                <InlineMetric label="AIRM 距离" value={num(riemann.airmDistance)} />
                <InlineMetric label="Log-Euclidean" value={num(riemann.logEuclideanDistance)} />
                <InlineMetric label="切空间范数" value={num(riemann.tangentNorm)} />
              </div>
              <TableShell className="mt-4">
                <table className="institution-table">
                  <tbody>
                    {matrixRows(riemann.currentCovariance).map((row, rowIndex) => (
                      <tr key={rowIndex} className="border-t border-slate-100">
                        {row.slice(0, 4).map((value, colIndex) => (
                          <td key={colIndex} className="px-2 py-2 font-mono text-slate-600">{num(value, 5)}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableShell>
              <div className="mt-3 flex flex-wrap gap-2">
                {(riemann.featureBasis || []).map((item) => <Badge key={item} status="REVIEW_ONLY">{item}</Badge>)}
              </div>
            </Card>

            <Card title="滚动前推诊断">
              <div className="grid gap-3 sm:grid-cols-2">
                <DiagnosticBlock title="MFE有利模型" folds={repairWalk.folds} brier={repairWalk.brier} prAuc={repairWalk.prAuc} />
                <DiagnosticBlock title="MAE风险模型" folds={breakdownWalk.folds} brier={breakdownWalk.brier} prAuc={breakdownWalk.prAuc} />
              </div>
              <div className="mt-4 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs leading-5 text-slate-600">
                {leakagePolicyText(diagnostics.leakagePolicy)}
              </div>
            </Card>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="研究仓位包络">
              <div className="grid gap-3 sm:grid-cols-2">
                <InlineMetric label="研究上限" value={pct(envelope.maxResearchPositionPct)} />
                <InlineMetric label="建议研究观察仓" value={pct(envelope.suggestedResearchPositionPct)} />
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <Badge status="REVIEW_ONLY">仅研究</Badge>
                <Badge status={envelope.simulation_only !== false ? 'PASS' : 'BLOCK_BUY'}>simulation_only={String(envelope.simulation_only !== false)}</Badge>
                <Badge status={envelope.is_real_trade ? 'BLOCK_BUY' : 'PASS'}>is_real_trade={String(Boolean(envelope.is_real_trade))}</Badge>
              </div>
            </Card>

            <Card title="缺失与警告">
              <div className="space-y-2">
                {(bottom.missingData || []).length === 0 && (bottom.warnings || []).length === 0 ? (
                  <div className="text-sm text-slate-500">暂无缺失或警告。</div>
                ) : null}
                {(bottom.missingData || []).map((item) => (
                  <div key={`missing-${item}`} className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">{item}</div>
                ))}
                {(bottom.warnings || []).map((item) => (
                  <div key={`warning-${item}`} className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">{item}</div>
                ))}
              </div>
            </Card>
          </div>
        </>
      )}
    </div>
  )
}

function MetricCard({ icon, label, value, status }: { icon: ReactNode; label: string; value: string; status: string }) {
  const tone = status === 'PASS' ? 'success' : status === 'BLOCK_BUY' ? 'danger' : status === 'WARN' ? 'warning' : 'neutral'
  return (
    <MetricTile
      label={<span className="inline-flex items-center gap-2">{icon}{label}</span>}
      value={value}
      helper={<Badge status={status}>{status}</Badge>}
      tone={tone}
    />
  )
}

function InlineMetric({ label, value }: { label: string; value: string }) {
  return (
    <MetricTile label={label} value={value} className="!rounded-md !px-3 !py-2 !shadow-none" />
  )
}

function DiagnosticBlock({ title, folds, brier, prAuc }: { title: string; folds: number; brier: string; prAuc: string }) {
  return (
    <div className="rounded-md border border-slate-200 bg-white p-3">
      <div className="mb-3 text-sm font-semibold text-slate-900">{title}</div>
      <div className="grid grid-cols-3 gap-2">
        <DiagnosticMetric label="折数" value={String(folds)} />
        <DiagnosticMetric label="校准" value={brier} />
        <DiagnosticMetric label="PR面积" value={prAuc} />
      </div>
    </div>
  )
}

function DiagnosticMetric({ label, value }: { label: string; value: string }) {
  return (
    <MetricTile label={label} value={<span title={value}>{value}</span>} className="!min-h-[68px] !rounded-md !px-1.5 !py-2 !text-left !shadow-none" />
  )
}
