import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Activity, BarChart3, Gauge, Layers, RefreshCw, Search, ShieldCheck, Target, TrendingDown, TrendingUp, WalletCards } from 'lucide-react'
import {
  getGlobalMarketOverview,
  GlobalMarketFundFlowRow,
  GlobalMarketIndex,
  GlobalMarketKlineRow,
  GlobalMarketOverview,
  GlobalMarketSourceConflict,
  GlobalMarketSectorRankRow,
} from '../../api/globalMarketClient'
import { Badge } from '../common/Badge'
import { MetricTile, SourceFreshnessPanel } from '../common/Material'

function fmtDate(value?: string) {
  if (!value) return '-'
  if (value.length === 8) return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6)}`
  return value.slice(0, 10)
}

function fmtNumber(value?: number | null, digits = 2) {
  if (typeof value !== 'number' || Number.isNaN(value)) return '-'
  return value.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits })
}

function fmtPercent(value?: number | null) {
  if (typeof value !== 'number' || Number.isNaN(value)) return '-'
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
}

function fmtMoney(value?: number | null) {
  if (typeof value !== 'number' || Number.isNaN(value)) return '-'
  return `${(value / 100000000).toLocaleString(undefined, { maximumFractionDigits: 2, minimumFractionDigits: 2 })} 亿`
}

function toneByChange(value?: number | null) {
  if (typeof value !== 'number' || Number.isNaN(value)) return 'text-slate-500'
  if (value > 0) return 'text-red-600'
  if (value < 0) return 'text-emerald-600'
  return 'text-slate-500'
}

function borderToneByChange(value?: number | null) {
  if (typeof value !== 'number' || Number.isNaN(value)) return 'border-slate-200 bg-slate-50'
  if (value > 0) return 'border-red-100 bg-red-50'
  if (value < 0) return 'border-emerald-100 bg-emerald-50'
  return 'border-slate-200 bg-slate-50'
}

function modeStatus(mode?: string, reviewOnly?: boolean) {
  if (reviewOnly) return 'REVIEW_ONLY'
  if (mode === 'LIVE') return 'PASS'
  if (mode === 'FALLBACK') return 'WARN'
  if (mode === 'STALE') return 'STALE'
  return 'WARN'
}

function formatFreshness(value?: string) {
  if (value === 'REALTIME') return '实时'
  if (value === 'POST_CLOSE_PENDING_EOD') return '盘后待日终'
  if (value === 'EOD') return '日终'
  if (value === 'STALE') return '滞后'
  return '未知'
}

function formatSourceBadge(provider?: string, freshness?: string, fallbackUsed?: boolean, reviewOnly?: boolean) {
  if (reviewOnly) return '冲突需复核'
  if (provider === 'akshare') return `AkShare ${formatFreshness(freshness)}`
  if (provider === 'tushare') return fallbackUsed ? `Tushare 回退 · ${formatFreshness(freshness)}` : `Tushare ${formatFreshness(freshness)}`
  return provider || '来源未知'
}

function formatConflictValue(value?: string | number | null) {
  if (typeof value === 'number') return Number.isFinite(value) ? value.toLocaleString(undefined, { maximumFractionDigits: 4 }) : '-'
  return value || '-'
}

function ConflictNotice({ conflicts }: { conflicts: GlobalMarketSourceConflict[] }) {
  if (!conflicts.length) return null
  return (
    <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
      {conflicts.slice(0, 2).map((conflict, index) => (
        <div key={`${conflict.field}-${conflict.primarySource}-${conflict.otherSource}-${index}`}>
          {conflict.message || `${conflict.field} 来源冲突`}：{conflict.primarySource} {formatConflictValue(conflict.primaryValue)}，{conflict.otherSource} {formatConflictValue(conflict.otherValue)}
        </div>
      ))}
    </div>
  )
}

function buildPath(points: Array<{ x: number; y: number }>) {
  return points.map((point, index) => `${index === 0 ? 'M' : 'L'} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(' ')
}

function calculateMovingAverage(rows: GlobalMarketKlineRow[], window: number) {
  let sum = 0
  return rows.map((row, index) => {
    sum += row.close
    if (index >= window) sum -= rows[index - window].close
    if (index < window - 1) return null
    return sum / window
  })
}

const MOVING_AVERAGES = [
  { label: 'MA5', window: 5, color: '#f9ab00' },
  { label: 'MA10', window: 10, color: '#1a73e8' },
  { label: 'MA20', window: 20, color: '#9334e6' },
]

function isNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

const MATERIAL_BLUE_DARK = '#0b57d0'
const MATERIAL_SURFACE = '#f8fafd'
const MATERIAL_GRID = '#dfe5ee'
const MATERIAL_TEXT_MUTED = '#5f6368'
const MATERIAL_CARD = 'rounded-md border border-[#dfe3eb] bg-white shadow-[0_1px_2px_rgba(60,64,67,0.08)]'
const MATERIAL_TONAL = 'rounded-md border border-[#e4e8f0] bg-[#f8fafd]'

type TechnicalTone = 'positive' | 'neutral' | 'negative'
type OpportunityTone = 'strong' | 'watch' | 'blocked'

interface TechnicalInterpretation {
  tone: TechnicalTone
  label: string
  summary: string
  points: string[]
  metrics: Array<{ label: string; value: string; tone?: TechnicalTone }>
}

interface AutoStockOpportunity {
  id: string
  rank: number
  stockName: string
  sectorName: string
  score: number
  tone: OpportunityTone
  label: string
  reasons: string[]
  blockers: string[]
  evidence: string
  sectorPctChange: number | null
  stockPctChange: number | null
}

function toneClass(tone?: TechnicalTone) {
  if (tone === 'positive') return 'text-red-600'
  if (tone === 'negative') return 'text-emerald-600'
  return 'text-slate-600'
}

function toneChipClass(tone?: TechnicalTone) {
  if (tone === 'positive') return 'border-red-200 bg-red-50 text-red-700'
  if (tone === 'negative') return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  return 'border-blue-200 bg-blue-50 text-blue-700'
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value))
}

function opportunityTone(score: number, blockers: string[]): OpportunityTone {
  if (blockers.length > 1 || score < 52) return 'blocked'
  if (score >= 72) return 'strong'
  return 'watch'
}

function opportunityLabel(tone: OpportunityTone) {
  if (tone === 'strong') return '优先复核'
  if (tone === 'watch') return '候选观察'
  return '等待确认'
}

function opportunityToneClass(tone: OpportunityTone) {
  if (tone === 'strong') return 'border-red-100 bg-red-50 text-red-700'
  if (tone === 'watch') return 'border-amber-100 bg-amber-50 text-amber-700'
  return 'border-slate-200 bg-slate-50 text-slate-600'
}

function opportunityScoreClass(tone: OpportunityTone) {
  if (tone === 'strong') return 'text-red-600'
  if (tone === 'watch') return 'text-amber-600'
  return 'text-slate-500'
}

function buildAutoStockOpportunities(overview: GlobalMarketOverview): AutoStockOpportunity[] {
  const sector = overview.sectorRank
  const rows = (sector.top.length ? sector.top : sector.rows)
    .filter((row) => row.name || row.leadingStock)
    .slice(0, 14)
  const marketScore = overview.temperature.score || 0
  const fundNet = overview.fundFlow.netAmount ?? 0
  const reviewOnly = overview.temperature.reviewOnly || overview.fundFlow.reviewOnly || sector.arbitration?.dataQuality?.reviewOnly

  return rows
    .map((row, index) => {
      const sectorPct = row.pctChange ?? 0
      const stockPct = row.leadingStockPctChange ?? 0
      const breadthTotal = (row.risingCount ?? 0) + (row.fallingCount ?? 0)
      const breadthRatio = breadthTotal > 0 ? (row.risingCount ?? 0) / breadthTotal : 0.5
      const score = Math.round(clamp(
        50
        + clamp(sectorPct * 5.5, -18, 28)
        + clamp(stockPct * 2.4, -12, 22)
        + clamp((breadthRatio - 0.5) * 24, -10, 12)
        + clamp((marketScore - 50) * 0.22, -10, 12)
        + (fundNet > 0 ? 7 : fundNet < 0 ? -7 : 0)
        - (reviewOnly ? 6 : 0),
        0,
        100,
      ))
      const blockers = [
        reviewOnly ? '数据需复核' : '',
        fundNet < 0 ? '全市场资金净流出' : '',
        marketScore < 45 ? '市场温度偏弱' : '',
        row.leadingStock ? '' : '缺少领涨股',
      ].filter(Boolean)
      const tone = opportunityTone(score, blockers)
      const reasons = [
        `板块${fmtPercent(row.pctChange)}，排名 ${row.rank ?? index + 1}`,
        row.leadingStock ? `领涨股 ${row.leadingStock} ${fmtPercent(row.leadingStockPctChange)}` : '领涨股待确认',
        breadthTotal > 0 ? `板块内 ${row.risingCount ?? 0} 涨 / ${row.fallingCount ?? 0} 跌` : '板块涨跌面待确认',
        fundNet > 0 ? '资金流为正，顺风加分' : fundNet < 0 ? '资金流为负，降权处理' : '资金流中性',
      ]

      return {
        id: `${row.code || row.name}-${row.leadingStock || 'unknown'}-${index}`,
        rank: index + 1,
        stockName: row.leadingStock || '领涨股待确认',
        sectorName: row.name || '未知板块',
        score,
        tone,
        label: opportunityLabel(tone),
        reasons,
        blockers,
        evidence: `${formatSourceLabel(sector.selectedProvider || sector.provider, sector.selectedSource || sector.source)} · ${fmtDate(sector.tradeDate || sector.fetchedAt)}`,
        sectorPctChange: row.pctChange,
        stockPctChange: row.leadingStockPctChange,
      }
    })
    .sort((left, right) => right.score - left.score)
    .slice(0, 6)
}

function buildTechnicalInterpretation(index: GlobalMarketIndex): TechnicalInterpretation {
  const rows = index.rows
  const latest = rows[rows.length - 1]
  if (!rows.length || !latest || !isNumber(latest.close)) {
    return {
      tone: 'neutral',
      label: '数据不足',
      summary: '当前指数 K 线不足，暂不能形成稳定技术面判断。',
      points: [index.message || '等待更多交易日数据。'],
      metrics: [],
    }
  }

  const close = latest.close
  const ma5 = calculateMovingAverage(rows, 5)[rows.length - 1]
  const ma10 = calculateMovingAverage(rows, 10)[rows.length - 1]
  const ma20 = calculateMovingAverage(rows, 20)[rows.length - 1]
  const recentRows = rows.slice(-20)
  const recentHigh = Math.max(...recentRows.map((row) => row.high))
  const recentLow = Math.min(...recentRows.map((row) => row.low))
  const fiveDaysAgo = rows.length >= 6 ? rows[rows.length - 6]?.close : null
  const fiveDayChange = isNumber(fiveDaysAgo) && fiveDaysAgo !== 0 ? ((close - fiveDaysAgo) / fiveDaysAgo) * 100 : null
  const ma20Distance = isNumber(ma20) && ma20 !== 0 ? ((close - ma20) / ma20) * 100 : null
  const rangePosition = recentHigh > recentLow ? ((close - recentLow) / (recentHigh - recentLow)) * 100 : null

  const aboveMa5 = isNumber(ma5) && close >= ma5
  const aboveMa10 = isNumber(ma10) && close >= ma10
  const aboveMa20 = isNumber(ma20) && close >= ma20
  const bullishStack = isNumber(ma5) && isNumber(ma10) && isNumber(ma20) && ma5 >= ma10 && ma10 >= ma20
  const bearishStack = isNumber(ma5) && isNumber(ma10) && isNumber(ma20) && ma5 <= ma10 && ma10 <= ma20
  const supportedCount = [aboveMa5, aboveMa10, aboveMa20].filter(Boolean).length

  const tone: TechnicalTone = bullishStack && supportedCount >= 2
    ? 'positive'
    : bearishStack && supportedCount <= 1
      ? 'negative'
      : 'neutral'
  const label = tone === 'positive' ? '偏强' : tone === 'negative' ? '偏弱' : '震荡'
  const stackText = bullishStack ? 'MA5、MA10、MA20 呈多头排列' : bearishStack ? 'MA5、MA10、MA20 呈空头排列' : '短中期均线仍在交织'
  const supportText = `收盘价${aboveMa5 ? '站上' : '低于'} MA5、${aboveMa10 ? '站上' : '低于'} MA10、${aboveMa20 ? '站上' : '低于'} MA20`
  const positionText = isNumber(rangePosition)
    ? `近 20 日区间位置约 ${Math.max(0, Math.min(100, rangePosition)).toFixed(0)}%，${rangePosition >= 70 ? '接近区间上沿' : rangePosition <= 30 ? '靠近区间下沿' : '位于区间中部'}`
    : '近 20 日区间位置暂不可计算'

  return {
    tone,
    label,
    summary: `${index.name} 技术面${label}：${supportText}，${stackText}。`,
    points: [
      `${fmtDate(latest.tradeDate)} 收盘 ${fmtNumber(close)}，当日涨跌幅 ${fmtPercent(latest.pctChange)}。`,
      isNumber(ma20Distance) ? `收盘价相对 MA20 ${ma20Distance >= 0 ? '高出' : '低于'} ${Math.abs(ma20Distance).toFixed(2)}%。` : 'MA20 偏离度暂不可计算。',
      positionText,
    ],
    metrics: [
      { label: 'MA5', value: fmtNumber(ma5), tone: aboveMa5 ? 'positive' : 'negative' },
      { label: 'MA10', value: fmtNumber(ma10), tone: aboveMa10 ? 'positive' : 'negative' },
      { label: 'MA20', value: fmtNumber(ma20), tone: aboveMa20 ? 'positive' : 'negative' },
      { label: '5日涨跌', value: fmtPercent(fiveDayChange), tone: isNumber(fiveDayChange) ? (fiveDayChange >= 0 ? 'positive' : 'negative') : 'neutral' },
    ],
  }
}

function TechnicalInterpretationPanel({ index }: { index: GlobalMarketIndex }) {
  const interpretation = buildTechnicalInterpretation(index)
  return (
    <div className={`${MATERIAL_TONAL} mt-4 p-4`}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2 text-sm font-semibold text-[#1f1f1f]">
            <Activity size={16} className="text-[#0b57d0]" />
            技术面解读
            <span className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${toneChipClass(interpretation.tone)}`}>
              {interpretation.label}
            </span>
          </div>
          <p className="mt-2 text-sm leading-6 text-[#3c4043]">{interpretation.summary}</p>
          <div className="mt-2 space-y-1 text-xs leading-5 text-[#5f6368]">
            {interpretation.points.map((point) => (
              <div key={point}>{point}</div>
            ))}
          </div>
        </div>
        {interpretation.metrics.length > 0 ? (
          <div className="grid w-full gap-2 text-xs sm:w-auto sm:min-w-[260px] sm:grid-cols-2">
            {interpretation.metrics.map((metric) => (
              <div key={metric.label} className="rounded-lg border border-[#e4e8f0] bg-white px-3 py-2">
                <div className="text-[11px] text-[#5f6368]">{metric.label}</div>
                <div className={`mt-1 text-sm font-semibold ${toneClass(metric.tone)}`}>{metric.value}</div>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  )
}

function MiniKline({ index }: { index: GlobalMarketIndex }) {
  const rows = index.rows
  if (!rows.length) {
    return (
      <div className="flex h-[340px] items-center justify-center rounded-lg border border-amber-200 bg-amber-50 px-4 text-center text-sm text-amber-800">
        {index.message || '指数 K 线暂不可用'}
      </div>
    )
  }

  const width = 720
  const height = 360
  const pad = { left: 74, right: 24, top: 48, bottom: 66 }
  const plotWidth = width - pad.left - pad.right
  const priceHeight = 202
  const volumeTop = pad.top + priceHeight + 34
  const volumeHeight = 48
  const movingAverages = MOVING_AVERAGES.map((item) => ({
    ...item,
    values: calculateMovingAverage(rows, item.window),
  }))
  const maValues = movingAverages.flatMap((item) => item.values.filter(isNumber))
  const minPrice = Math.min(...rows.map((row) => row.low), ...maValues)
  const maxPrice = Math.max(...rows.map((row) => row.high), ...maValues)
  const range = Math.max(maxPrice - minPrice, 0.01)
  const maxVolume = Math.max(...rows.map((row) => row.volume || 0), 1)
  const step = plotWidth / rows.length
  const candleWidth = Math.min(9, Math.max(3, step * 0.55))
  const xFor = (rowIndex: number) => pad.left + step * rowIndex + step / 2
  const yFor = (price: number) => pad.top + ((maxPrice - price) / range) * priceHeight
  const movingAveragePaths = movingAverages.map((item) => ({
    ...item,
    path: buildPath(
      item.values
        .map((value, rowIndex) => (isNumber(value) ? { x: xFor(rowIndex), y: yFor(value) } : null))
        .filter((point): point is { x: number; y: number } => point !== null),
    ),
  }))
  const latestRow = rows[rows.length - 1]
  const latestY = latestRow ? yFor(latestRow.close) : pad.top

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-[340px] w-full rounded-lg bg-[#f8fafd] sm:h-[360px]">
      {[0, 0.25, 0.5, 0.75, 1].map((ratio) => {
        const y = pad.top + ratio * priceHeight
        const price = maxPrice - ratio * range
        return (
          <g key={ratio}>
            <line x1={pad.left} x2={width - pad.right} y1={y} y2={y} stroke={MATERIAL_GRID} strokeDasharray="4 6" />
            <text x={12} y={y + 5} fill={MATERIAL_TEXT_MUTED} className="text-[14px]">{fmtNumber(price)}</text>
          </g>
        )
      })}
      <line x1={pad.left} x2={width - pad.right} y1={volumeTop + volumeHeight} y2={volumeTop + volumeHeight} stroke="#c6d0dc" />
      {movingAveragePaths.map((item) => (
        item.path ? (
          <path key={item.label} d={item.path} fill="none" stroke={item.color} strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" />
        ) : null
      ))}
      <g>
        {movingAveragePaths.map((item, legendIndex) => (
          <g key={item.label} transform={`translate(${pad.left + legendIndex * 92}, 24)`}>
            <line x1={0} x2={24} y1={0} y2={0} stroke={item.color} strokeWidth={2.6} strokeLinecap="round" />
            <text x={32} y={5} fill={MATERIAL_TEXT_MUTED} className="text-[14px]">{item.label}</text>
          </g>
        ))}
      </g>
      {rows.map((row, rowIndex) => {
        const x = xFor(rowIndex)
        const openY = yFor(row.open)
        const closeY = yFor(row.close)
        const highY = yFor(row.high)
        const lowY = yFor(row.low)
        const rising = row.close >= row.open
        const color = rising ? '#dc2626' : '#16a34a'
        const bodyTop = Math.min(openY, closeY)
        const bodyHeight = Math.max(Math.abs(openY - closeY), 1.4)
        const barHeight = ((row.volume || 0) / maxVolume) * volumeHeight
        return (
          <g key={`${row.tradeDate}-${rowIndex}`}>
            <line x1={x} x2={x} y1={highY} y2={lowY} stroke={color} strokeWidth={1.1} />
            <rect x={x - candleWidth / 2} y={bodyTop} width={candleWidth} height={bodyHeight} fill={rising ? '#fee2e2' : '#dcfce7'} stroke={color} strokeWidth={1.1} />
            <rect x={x - candleWidth / 2} y={volumeTop + volumeHeight - barHeight} width={candleWidth} height={barHeight} fill={color} opacity={0.3} />
          </g>
        )
      })}
      {[0, Math.floor(rows.length / 2), rows.length - 1].map((rowIndex) => (
        <text key={rowIndex} x={xFor(rowIndex)} y={height - 20} textAnchor="middle" fill={MATERIAL_TEXT_MUTED} className="text-[14px]">
          {fmtDate(rows[rowIndex]?.tradeDate).slice(5)}
        </text>
      ))}
      {latestRow ? (
        <g>
          <line x1={width - pad.right - 86} x2={width - pad.right} y1={latestY} y2={latestY} stroke="#1a73e8" strokeDasharray="3 4" opacity={0.65} />
          <text x={width - pad.right} y={Math.max(18, latestY - 6)} textAnchor="end" fill="#0b57d0" className="text-[13px] font-semibold">
            {fmtNumber(latestRow.close)}
          </text>
        </g>
      ) : null}
      <text x={12} y={volumeTop + 10} fill="#7c8794" className="text-[13px]">成交量</text>
    </svg>
  )
}

function IndexMiniKline({ index, active }: { index: GlobalMarketIndex; active: boolean }) {
  const rows = index.rows
    .filter((row) => isNumber(row.open) && isNumber(row.high) && isNumber(row.low) && isNumber(row.close))
    .slice(-32)

  if (rows.length < 2) {
    return (
      <div className="mt-3 flex h-[88px] items-center justify-between rounded-md border border-[#e4e8f0] bg-white/70 px-3 text-[11px] text-[#7c8794]">
        <span>日 K 待数据</span>
        <span>{formatFreshness(index.freshness)}</span>
      </div>
    )
  }

  const width = 300
  const height = 88
  const pad = { left: 10, right: 52, top: 8, bottom: 18 }
  const plotWidth = width - pad.left - pad.right
  const plotHeight = height - pad.top - pad.bottom
  const minPrice = Math.min(...rows.map((row) => row.low))
  const maxPrice = Math.max(...rows.map((row) => row.high))
  const range = Math.max(maxPrice - minPrice, 0.01)
  const step = plotWidth / rows.length
  const candleWidth = Math.min(7, Math.max(3, step * 0.58))
  const xFor = (rowIndex: number) => pad.left + step * rowIndex + step / 2
  const yFor = (price: number) => pad.top + ((maxPrice - price) / range) * plotHeight
  const latest = rows[rows.length - 1]
  const first = rows[0]
  const latestY = yFor(latest.close)
  const latestLabelY = Math.min(height - pad.bottom - 5, Math.max(pad.top + 8, latestY))

  return (
    <div className={`mt-3 overflow-hidden rounded-md border ${active ? 'border-[#b8c5d6] bg-white/85' : 'border-[#e4e8f0] bg-[#f8fafd]'}`}>
      <div className="px-2 pb-1 pt-1.5">
        <svg viewBox={`0 0 ${width} ${height}`} className="h-[88px] w-full" preserveAspectRatio="none" aria-label={`${index.name} 近${rows.length}条日K线走势`}>
          {[0.25, 0.5, 0.75].map((ratio) => {
            const y = pad.top + ratio * plotHeight
            return <line key={ratio} x1={pad.left} x2={width - pad.right} y1={y} y2={y} stroke="#dfe5ee" strokeDasharray="3 5" strokeWidth={1} />
          })}
          <line x1={pad.left} x2={width - pad.right} y1={latestY} y2={latestY} stroke="#1a73e8" strokeDasharray="3 4" opacity={0.55} vectorEffect="non-scaling-stroke" />
          {rows.map((row, rowIndex) => {
            const x = xFor(rowIndex)
            const openY = yFor(row.open)
            const closeY = yFor(row.close)
            const highY = yFor(row.high)
            const lowY = yFor(row.low)
            const rising = row.close >= row.open
            const color = rising ? '#dc2626' : '#16a34a'
            const bodyTop = Math.min(openY, closeY)
            const bodyHeight = Math.max(Math.abs(openY - closeY), 1.6)

            return (
              <g key={`${row.tradeDate}-${rowIndex}`}>
                <title>{`${fmtDate(row.tradeDate)} 开 ${fmtNumber(row.open)} 高 ${fmtNumber(row.high)} 低 ${fmtNumber(row.low)} 收 ${fmtNumber(row.close)}`}</title>
                <line x1={x} x2={x} y1={highY} y2={lowY} stroke={color} strokeWidth={1.05} vectorEffect="non-scaling-stroke" />
                <rect
                  x={x - candleWidth / 2}
                  y={bodyTop}
                  width={candleWidth}
                  height={bodyHeight}
                  fill={rising ? '#fee2e2' : '#dcfce7'}
                  stroke={color}
                  strokeWidth={1.05}
                  vectorEffect="non-scaling-stroke"
                />
              </g>
            )
          })}
          <text x={pad.left} y={height - 4} fill="#7c8794" className="text-[10px]">
            {fmtDate(first.tradeDate).slice(5)}
          </text>
          <text x={width - pad.right} y={height - 4} textAnchor="end" fill="#7c8794" className="text-[10px]">
            {fmtDate(latest.tradeDate).slice(5)}
          </text>
          <rect x={width - 49} y={latestLabelY - 10} width={45} height={13} rx={3} fill="white" stroke="#c7d7fe" strokeWidth={1} />
          <text x={width - 6} y={latestLabelY} textAnchor="end" fill="#0b57d0" className="text-[10px] font-semibold">
            {fmtNumber(latest.close)}
          </text>
        </svg>
      </div>
    </div>
  )
}

function ScoreBar({ label, value, helper }: { label: string; value: number; helper?: string }) {
  const safeValue = clamp(value, 0, 100)
  const fillClass = safeValue >= 70 ? 'bg-red-500' : safeValue >= 45 ? 'bg-amber-500' : 'bg-slate-400'
  return (
    <div className="min-w-0">
      <div className="flex items-center justify-between gap-3 text-xs">
        <span className="font-medium text-[#5f6368]">{label}</span>
        <span className="font-mono font-semibold text-[#1f1f1f]">{safeValue}</span>
      </div>
      <div className="mt-2 h-1.5 rounded-full bg-[#edf2f7]">
        <div className={`h-1.5 rounded-full ${fillClass}`} style={{ width: `${safeValue}%` }} />
      </div>
      {helper ? <div className="mt-1 truncate text-[11px] text-[#7c8794]">{helper}</div> : null}
    </div>
  )
}

function FlowBars({ rows }: { rows: GlobalMarketFundFlowRow[] }) {
  const visibleRows = rows.slice(-8)
  const maxAbs = Math.max(...visibleRows.map((row) => Math.abs(row.netAmount || 0)), 1)
  if (!visibleRows.length) {
    return <div className="mt-3 rounded-md bg-[#f8fafd] px-3 py-2 text-xs text-[#5f6368]">资金流序列待数据</div>
  }

  return (
    <div className="relative mt-3 h-[92px] overflow-hidden rounded-md border border-[#e4e8f0] bg-[#f8fafd] px-3 pb-5 pt-3">
      <div className="absolute left-3 right-3 top-[42px] border-t border-dashed border-[#c8d1dc]" />
      <div className="relative flex h-14 items-stretch gap-1.5">
        {visibleRows.map((row) => {
          const amount = row.netAmount || 0
          const positive = amount >= 0
          const height = Math.max(5, Math.min(34, (Math.abs(amount) / maxAbs) * 34))
          return (
            <div key={row.tradeDate} className="relative min-w-0 flex-1" title={`${fmtDate(row.tradeDate)} ${fmtMoney(amount)}`}>
              <div
                className={`absolute left-0 right-0 rounded-sm ${positive ? 'bottom-1/2 bg-red-500/75' : 'top-1/2 bg-emerald-500/75'}`}
                style={{ height }}
              />
              <span className="absolute -bottom-4 left-1/2 w-10 -translate-x-1/2 truncate text-center text-[10px] text-[#7c8794]">
                {fmtDate(row.tradeDate).slice(5)}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function MarketOverviewPanel({ overview }: { overview: GlobalMarketOverview }) {
  const temperature = overview.temperature
  const fundFlow = overview.fundFlow
  const strongest = overview.sectorRank.top[0] ?? overview.sectorRank.rows[0]
  const weakest = overview.sectorRank.bottom[0] ?? [...overview.sectorRank.rows].reverse()[0]
  const breadthTotal = Math.max(temperature.risingCount + temperature.fallingCount, 1)
  const risingWidth = `${Math.round((temperature.risingCount / breadthTotal) * 100)}%`
  const healthTone = temperature.status === 'PASS' ? 'text-red-600' : temperature.status === 'WARN' ? 'text-amber-600' : 'text-slate-500'

  return (
    <div className={`${MATERIAL_CARD} overflow-hidden`}>
      <div className="grid gap-0 xl:grid-cols-[minmax(0,1.1fr)_minmax(330px,0.9fr)]">
        <div className="p-4 sm:p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-sm font-semibold text-[#0b57d0]">
                <Gauge size={16} />
                市场健康度
              </div>
              <div className="mt-1 text-2xl font-semibold text-[#1f1f1f]">
                <span className={healthTone}>{temperature.score}</span>
                <span className="ml-2 text-base font-medium text-[#5f6368]">{temperature.label}</span>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Badge status={modeStatus(overview.dataMode)}>{overview.dataMode}</Badge>
              <span className="rounded-full border border-[#dfe3eb] bg-[#f8fafd] px-3 py-1 text-xs font-medium text-[#5f6368]">
                {fmtDate(overview.fetchedAt)}
              </span>
            </div>
          </div>

          <div className="mt-5 grid gap-4 md:grid-cols-3">
            <ScoreBar label="趋势" value={temperature.trendScore} helper="四大指数趋势" />
            <ScoreBar label="涨跌面" value={temperature.breadthScore} helper={`${temperature.risingCount} 涨 / ${temperature.fallingCount} 跌`} />
            <ScoreBar label="资金" value={temperature.flowScore} helper={fmtMoney(fundFlow.netAmount)} />
          </div>

          <div className="mt-5">
            <div className="flex items-center justify-between gap-3 text-xs text-[#5f6368]">
              <span>指数涨跌面</span>
              <span>{temperature.risingCount} / {breadthTotal}</span>
            </div>
            <div className="mt-2 h-2 overflow-hidden rounded-full bg-emerald-100">
              <div className="h-full rounded-full bg-red-500" style={{ width: risingWidth }} />
            </div>
          </div>
        </div>

        <div className="border-t border-[#e4e8f0] p-4 sm:p-5 xl:border-l xl:border-t-0">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className={`rounded-md border px-3 py-2 ${borderToneByChange(strongest?.pctChange)}`}>
              <div className="text-[11px] font-medium text-[#5f6368]">最强板块</div>
              <div className="mt-1 truncate text-lg font-semibold text-[#1f1f1f]">{strongest?.name || '-'}</div>
              <div className={`mt-1 text-sm font-semibold ${toneByChange(strongest?.pctChange)}`}>{fmtPercent(strongest?.pctChange)}</div>
            </div>
            <div className={`rounded-md border px-3 py-2 ${borderToneByChange(weakest?.pctChange)}`}>
              <div className="text-[11px] font-medium text-[#5f6368]">最弱板块</div>
              <div className="mt-1 truncate text-lg font-semibold text-[#1f1f1f]">{weakest?.name || '-'}</div>
              <div className={`mt-1 text-sm font-semibold ${toneByChange(weakest?.pctChange)}`}>{fmtPercent(weakest?.pctChange)}</div>
            </div>
          </div>
          <div className="mt-4 flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-1.5 text-sm font-semibold text-[#1f1f1f]">
                <WalletCards size={16} className="text-[#0b57d0]" />
                资金流
              </div>
              <div className={`mt-1 text-2xl font-semibold ${toneByChange(fundFlow.netAmount)}`}>{fmtMoney(fundFlow.netAmount)}</div>
              <div className="mt-1 text-xs text-[#5f6368]">{formatSourceBadge(fundFlow.selectedProvider, fundFlow.freshness, fundFlow.fallbackUsed, fundFlow.reviewOnly)}</div>
            </div>
            <Badge status={fundFlow.status === 'READY' ? modeStatus(fundFlow.dataMode, fundFlow.reviewOnly) : 'WARN'}>
              {fundFlow.reviewOnly ? 'REVIEW' : fundFlow.dataMode}
            </Badge>
          </div>
          <FlowBars rows={fundFlow.rows} />
        </div>
      </div>
    </div>
  )
}

function TemperaturePanel({ overview }: { overview: GlobalMarketOverview }) {
  const temperature = overview.temperature
  return (
    <div className={`${MATERIAL_CARD} p-4`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-xs font-medium text-[#5f6368]">市场温度</div>
          <div className="mt-1 flex items-end gap-2">
            <span className="text-3xl font-semibold text-[#1f1f1f]">{temperature.score}</span>
            <span className="pb-1 text-sm font-medium text-[#5f6368]">{temperature.label}</span>
          </div>
        </div>
        {temperature.reviewOnly ? <Badge status="REVIEW_ONLY">需复核</Badge> : null}
        <div className="grid h-10 w-10 place-items-center rounded-lg bg-[#e8f0fe] text-[#0b57d0]">
          <Gauge size={18} />
        </div>
      </div>
      <div className="mt-4 h-2 rounded-full bg-[#edf2f7]">
        <div
          className={`h-2 rounded-full ${temperature.status === 'PASS' ? 'bg-red-500' : temperature.status === 'WARN' ? 'bg-amber-500' : 'bg-slate-400'}`}
          style={{ width: `${Math.max(0, Math.min(100, temperature.score))}%` }}
        />
      </div>
      <div className="mt-4 space-y-3">
        <ScoreBar label="趋势" value={temperature.trendScore} />
        <ScoreBar label="涨跌面" value={temperature.breadthScore} />
        <ScoreBar label="资金" value={temperature.flowScore} />
      </div>
      <div className="mt-3 space-y-1 text-xs text-[#5f6368]">
        {temperature.reasons.slice(0, 3).map((reason) => (
          <div key={reason}>{reason}</div>
        ))}
      </div>
    </div>
  )
}

function FundFlowPanel({ overview }: { overview: GlobalMarketOverview }) {
  const flow = overview.fundFlow
  return (
    <div className={`${MATERIAL_CARD} p-4`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-xs font-medium text-[#5f6368]">资金流动</div>
          <div className={`mt-1 text-2xl font-semibold ${toneByChange(flow.netAmount)}`}>
            {fmtMoney(flow.netAmount)}
          </div>
          <div className="mt-1 text-xs text-[#5f6368]">
            {fmtDate(flow.latestDate)} · {flow.apiName} · {formatSourceBadge(flow.selectedProvider, flow.freshness, flow.fallbackUsed, flow.reviewOnly)}
          </div>
        </div>
        <Badge status={flow.status === 'READY' ? modeStatus(flow.dataMode, flow.reviewOnly) : 'WARN'}>
          {flow.reviewOnly ? 'REVIEW' : flow.dataMode}
        </Badge>
      </div>
      <ConflictNotice conflicts={flow.conflicts} />
      {flow.rows.length > 0 ? <FlowBars rows={flow.rows} /> : (
        <div className="mt-4 rounded-lg bg-[#f8fafd] px-3 py-2 text-xs leading-5 text-[#5f6368]">
          {flow.message || '资金流暂不可用'}
        </div>
      )}
    </div>
  )
}

function SectorRankList({
  title,
  rows,
  leadingLabel,
}: {
  title: string
  rows: GlobalMarketSectorRankRow[]
  leadingLabel: '领涨' | '领跌'
}) {
  const detailFor = (row: GlobalMarketSectorRankRow) => {
    if (!row.leadingStock) return row.code || '行业板块'
    if (
      leadingLabel === '领跌' &&
      typeof row.leadingStockPctChange === 'number' &&
      row.leadingStockPctChange >= 0
    ) {
      return '领跌股票待接入'
    }
    return `${leadingLabel} ${row.leadingStock} ${fmtPercent(row.leadingStockPctChange)}`
  }
  const maxAbsChange = Math.max(...rows.map((row) => Math.abs(row.pctChange || 0)), 1)

  return (
    <div className="min-w-0">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="text-sm font-semibold text-[#1f1f1f]">{title}</div>
        <div className="text-xs text-[#5f6368]">{rows.length} 项</div>
      </div>
      <div className="space-y-2">
        {rows.map((row, index) => {
          const pct = row.pctChange ?? 0
          const width = `${Math.max(4, Math.min(100, (Math.abs(pct) / maxAbsChange) * 100))}%`
          return (
            <div key={`${row.code || row.name}-${index}`} className="rounded-md border border-[#e4e8f0] bg-[#f8fafd] px-3 py-2">
              <div className="grid grid-cols-[28px_minmax(0,1fr)_76px] items-center gap-2">
                <div className="text-xs font-semibold text-[#7c8794]">{index + 1}</div>
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold text-[#1f1f1f]">{row.name}</div>
                  <div className="mt-0.5 truncate text-xs text-[#5f6368]">
                    {detailFor(row)}
                  </div>
                </div>
                <div className={`text-right text-sm font-semibold ${toneByChange(row.pctChange)}`}>
                  {fmtPercent(row.pctChange)}
                </div>
              </div>
              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white">
                <div className={`h-full rounded-full ${pct >= 0 ? 'bg-red-500' : 'bg-emerald-500'}`} style={{ width }} />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function formatSourceLabel(provider?: string, source?: string) {
  const parts = [provider, source].filter(Boolean)
  return parts.length ? parts.join(' / ') : '-'
}

function formatConsensus(value?: string) {
  if (value === 'CONSENSUS') return '多源一致'
  if (value === 'DIVERGED') return '存在冲突'
  if (value === 'SINGLE_SOURCE') return '单源可用'
  if (value === 'NO_DATA') return '无可用源'
  return value || '-'
}

function formatDailyRenderMode(index: GlobalMarketIndex) {
  if (index.dailyRenderMode === 'TUSHARE_EOD') return 'Tushare 当日日 K'
  if (index.dailyRenderMode === 'TUSHARE_STALE') return 'Tushare 最新日 K'
  return '日 K 不可用'
}

function dailyRenderTone(index: GlobalMarketIndex) {
  if (index.dailyRenderMode === 'UNAVAILABLE') return 'border-amber-200 bg-amber-50 text-amber-800'
  return 'border-[#dfe3eb] bg-[#f8fafd] text-[#5f6368]'
}

function DailyStatusNotice({ index }: { index: GlobalMarketIndex }) {
  const message = index.dailyRenderMessage
  if (!message) return null
  return (
    <div className={`mb-3 rounded-lg border px-3 py-2 text-xs leading-5 ${dailyRenderTone(index)}`}>
      <span className="font-semibold">{formatDailyRenderMode(index)}</span>
      {message ? <span> · {message}</span> : null}
    </div>
  )
}

function sourceBadgeTone(status?: string) {
  if (status === 'READY') return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  return 'border-amber-200 bg-amber-50 text-amber-700'
}

function AutoStockSelectorPanel({ overview }: { overview: GlobalMarketOverview }) {
  const opportunities = buildAutoStockOpportunities(overview)
  const top = opportunities[0]
  const readyCount = opportunities.filter((item) => item.tone !== 'blocked').length
  const boundaryText = '仅生成研究候选，不自动下单；simulation_only=true / is_real_trade=false / evidence_usage=review_gate_only / strong_conclusion_allowed=false / SIM_*，候选需进入研究实验室 / 回测 / SignalOps 复核。'

  return (
    <div className={`${MATERIAL_CARD} p-4`} data-testid="global-market-auto-stock-selector">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-[#0b57d0]">
            <Target size={16} />
            自动选股机会雷达
          </div>
          <div className="mt-1 text-xl font-semibold text-[#1f1f1f]">从板块强弱、资金流和市场温度中筛选收益机会候选</div>
          <div className="mt-1 text-xs leading-5 text-[#5f6368]" data-testid="global-market-auto-stock-boundary">
            {boundaryText}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge status="REVIEW_ONLY">仅研究</Badge>
          <span className="rounded-full border border-[#dfe3eb] bg-[#f8fafd] px-3 py-1 text-xs font-medium text-[#5f6368]">
            {overview.sectorRank.status === 'READY' ? '数据已接入' : '等待板块数据'}
          </span>
        </div>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-3">
        <div className="rounded-lg border border-[#e4e8f0] bg-[#f8fafd] p-3">
          <div className="flex items-center gap-2 text-xs font-medium text-[#5f6368]">
            <Search size={14} />
            可复核候选
          </div>
          <div className="mt-1 text-2xl font-semibold text-[#1f1f1f]">{readyCount}</div>
          <div className="mt-1 text-[11px] text-[#7c8794]">来自前 {opportunities.length || 0} 个强势板块候选</div>
        </div>
        <div className="rounded-lg border border-[#e4e8f0] bg-[#f8fafd] p-3" data-testid="global-market-auto-stock-top-score">
          <div className="text-xs font-medium text-[#5f6368]">最高机会评分</div>
          <div className={`mt-1 text-2xl font-semibold ${top ? opportunityScoreClass(top.tone) : 'text-slate-500'}`}>
            {top ? top.score : '-'}
          </div>
          <div className="mt-1 text-[11px] text-[#7c8794]">{top ? `${top.stockName} · ${top.sectorName}` : '暂无候选'}</div>
        </div>
        <div className="rounded-lg border border-[#e4e8f0] bg-[#f8fafd] p-3">
          <div className="flex items-center gap-2 text-xs font-medium text-[#5f6368]">
            <ShieldCheck size={14} />
            风控边界
          </div>
          <div className="mt-1 text-sm font-semibold text-[#1f1f1f]">研究复核优先</div>
          <div className="mt-1 text-[11px] leading-5 text-[#7c8794]">不承诺收益，不触发实盘；用于加入观察池、回测和研究闭环。</div>
        </div>
      </div>

      {opportunities.length ? (
        <div className="mt-4 grid gap-3 lg:grid-cols-2">
          {opportunities.map((item) => (
            <div
              key={item.id}
              className="rounded-lg border border-[#e4e8f0] bg-white p-3 shadow-[0_1px_2px_rgba(60,64,67,0.05)]"
              data-testid="global-market-auto-stock-candidate"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-[#e8f0fe] text-xs font-semibold text-[#0b57d0]">
                      {item.rank}
                    </span>
                    <div className="truncate text-sm font-semibold text-[#1f1f1f]">{item.stockName}</div>
                  </div>
                  <div className="mt-1 truncate text-xs text-[#5f6368]">
                    {item.sectorName} · 板块 {fmtPercent(item.sectorPctChange)} · 个股 {fmtPercent(item.stockPctChange)}
                  </div>
                </div>
                <div className="text-right">
                  <div className={`text-xl font-semibold ${opportunityScoreClass(item.tone)}`}>{item.score}</div>
                  <span className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${opportunityToneClass(item.tone)}`}>
                    {item.label}
                  </span>
                </div>
              </div>
              <div className="mt-3 grid gap-2 text-xs sm:grid-cols-2">
                <div className="rounded-lg bg-[#f8fafd] px-3 py-2">
                  <div className="font-semibold text-[#1f1f1f]">收益假设</div>
                  <div className="mt-1 space-y-1 text-[#5f6368]">
                    {item.reasons.slice(0, 3).map((reason) => (
                      <div key={reason}>{reason}</div>
                    ))}
                  </div>
                </div>
                <div className="rounded-lg bg-[#f8fafd] px-3 py-2">
                  <div className="font-semibold text-[#1f1f1f]">风险/阻断</div>
                  <div className="mt-1 space-y-1 text-[#5f6368]">
                    {(item.blockers.length ? item.blockers : ['暂无硬阻断，仍需回测复核']).slice(0, 3).map((blocker) => (
                      <div key={blocker}>{blocker}</div>
                    ))}
                  </div>
                </div>
              </div>
              <div className="mt-3 rounded-lg border border-[#e4e8f0] bg-[#f8fafd] px-3 py-2 text-[11px] leading-5 text-[#5f6368]" data-testid="global-market-auto-stock-source">
                证据来源：{item.evidence} · 市场温度 {overview.temperature.score} · 资金 {fmtMoney(overview.fundFlow.netAmount)}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
          当前板块和资金数据不足，自动选股雷达等待下一次刷新。
        </div>
      )}
    </div>
  )
}

function SectorRankPanel({ overview }: { overview: GlobalMarketOverview }) {
  const sector = overview.sectorRank
  const topRows = (sector?.top?.length ? sector.top : sector?.rows?.slice(0, 10)) ?? []
  const bottomRows = (sector?.bottom?.length ? sector.bottom : [...(sector?.rows ?? [])].reverse().slice(0, 10)) ?? []
  const arbitration = sector?.arbitration
  const sourceCount = sector?.sourceCount
  const selectedSource = sourceCount && sourceCount.ready === 0
    ? '暂无可用来源'
    : sector?.selectedProvider
    ? formatSourceLabel(sector.selectedProvider, sector?.selectedSource || sector?.source)
    : formatSourceLabel(sector?.provider, sector?.source)
  const candidateSources = sector?.candidateSources ?? arbitration?.checkedSources ?? []
  const conflictCount = arbitration?.conflicts?.length ?? 0

  return (
    <div className={`${MATERIAL_CARD} mt-4 p-4 text-[#1f1f1f]`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-lg font-semibold">
            <Layers size={18} className="text-[#0b57d0]" />
            当日实时板块涨跌幅榜
          </div>
          <div className="mt-1 text-xs text-[#5f6368]">
            多源仲裁 · 采用 {selectedSource} · {sourceCount ? `${sourceCount.ready}/${sourceCount.total} 个来源可用` : sector?.apiName || '-'} · {fmtDate(sector?.tradeDate || sector?.fetchedAt)}
          </div>
        </div>
        <Badge status={sector?.status === 'READY' ? modeStatus(sector?.dataMode, sector?.arbitration?.dataQuality?.reviewOnly) : 'WARN'}>
          {sector?.arbitration?.dataQuality?.reviewOnly ? 'REVIEW' : sector?.dataMode || 'UNAVAILABLE'}
        </Badge>
      </div>
      {candidateSources.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-2 text-[11px]">
          {candidateSources.map((source) => (
            <span
              key={source.sourceId || `${source.provider}-${source.apiName}`}
              className={`rounded-full border px-2 py-1 font-medium ${sourceBadgeTone(source.status)}`}
              title={source.error || source.message}
            >
              {formatSourceLabel(source.provider, source.source)} · {source.status} · {source.recordCount ?? 0} 条
            </span>
          ))}
        </div>
      ) : null}

      {sector?.status === 'READY' && (topRows.length > 0 || bottomRows.length > 0) ? (
        <>
          <div className="mt-3 grid gap-2 text-xs sm:grid-cols-2 xl:grid-cols-4">
            <div className="rounded-lg border border-[#e4e8f0] bg-[#f8fafd] px-3 py-2">
              <div className="text-[#5f6368]">板块数量</div>
              <div className="mt-1 text-lg font-semibold text-[#1f1f1f]">{sector.recordCount}</div>
            </div>
            <div className="rounded-lg border border-[#e4e8f0] bg-[#f8fafd] px-3 py-2">
              <div className="text-[#5f6368]">最强板块</div>
              <div className="mt-1 truncate text-lg font-semibold text-red-600">{topRows[0]?.name || '-'}</div>
            </div>
            <div className="rounded-lg border border-[#e4e8f0] bg-[#f8fafd] px-3 py-2">
              <div className="text-[#5f6368]">最弱板块</div>
              <div className="mt-1 truncate text-lg font-semibold text-emerald-600">{bottomRows[0]?.name || '-'}</div>
            </div>
            <div className="rounded-lg border border-[#e4e8f0] bg-[#f8fafd] px-3 py-2">
              <div className="text-[#5f6368]">仲裁状态</div>
              <div className={`mt-1 truncate text-lg font-semibold ${conflictCount > 0 ? 'text-amber-600' : 'text-[#1f1f1f]'}`}>
                {formatConsensus(arbitration?.sourceConsensus)}
              </div>
              <div className="mt-1 text-[11px] text-[#7c8794]">
                {conflictCount > 0 ? `${conflictCount} 项冲突，按优先级呈现` : `质量 ${arbitration?.dataQuality?.level || '-'}`}
              </div>
            </div>
          </div>
          {conflictCount > 0 ? (
            <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
              {arbitration?.conflicts.slice(0, 2).map((conflict) => (
                <div key={`${conflict.field}-${conflict.primarySource}-${conflict.otherSource}-${conflict.sector || conflict.message}`}>
                  {conflict.message || `${conflict.sector || conflict.field}：${conflict.primarySource} 与 ${conflict.otherSource} 不一致`}
                </div>
              ))}
            </div>
          ) : null}
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <SectorRankList title="涨幅榜" rows={topRows.slice(0, 8)} leadingLabel="领涨" />
            <SectorRankList title="跌幅榜" rows={bottomRows.slice(0, 8)} leadingLabel="领跌" />
          </div>
        </>
      ) : (
        <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
          {sector?.message || '实时板块涨跌幅榜暂不可用'}
        </div>
      )}
    </div>
  )
}

export function GlobalMarketPage() {
  const [overview, setOverview] = useState<GlobalMarketOverview | null>(null)
  const [activeKey, setActiveKey] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const inFlightLoadRef = useRef<Promise<void> | null>(null)

  const load = useCallback(async () => {
    if (inFlightLoadRef.current) return inFlightLoadRef.current

    const request = (async () => {
      setLoading(true)
      setError('')
      try {
        const next = await getGlobalMarketOverview()
        setOverview(next)
        setActiveKey((current) => {
          const stillAvailable = next.indices.some((item) => item.key === current)
          if (current && stillAvailable) return current
          return next.indices.find((item) => item.status === 'READY')?.key ?? next.indices[0]?.key ?? current
        })
      } catch (err) {
      setError(err instanceof Error ? err.message : '股市全局数据请求失败')
      } finally {
        setLoading(false)
        inFlightLoadRef.current = null
      }
    })()

    inFlightLoadRef.current = request
    return request
  }, [])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    const intervalSeconds = Math.max(60, overview?.refreshIntervalSeconds ?? 300)
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') {
        void load()
      }
    }, intervalSeconds * 1000)
    return () => window.clearInterval(timer)
  }, [load, overview?.refreshIntervalSeconds])

  const activeIndex = useMemo(() => {
    if (!overview) return null
    return overview.indices.find((item) => item.key === activeKey) ?? overview.indices.find((item) => item.status === 'READY') ?? overview.indices[0] ?? null
  }, [overview, activeKey])

  return (
    <section
      className="overflow-hidden rounded-lg border border-[#dfe3eb] text-[#1f1f1f] shadow-[0_2px_8px_rgba(60,64,67,0.10)]"
      style={{ backgroundColor: MATERIAL_SURFACE }}
    >
      <div className="border-b border-[#dfe3eb] bg-white px-4 py-4 sm:px-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <div className="grid h-11 w-11 shrink-0 place-items-center rounded-lg bg-[#e8f0fe]" style={{ color: MATERIAL_BLUE_DARK }}>
              <BarChart3 size={21} />
            </div>
            <div className="min-w-0">
              <div className="text-sm font-semibold text-[#0b57d0]">股市全局</div>
              <h1 className="mt-0.5 text-xl font-semibold tracking-tight text-[#1f1f1f] sm:text-2xl">股市全局与自动选股雷达</h1>
              <div className="mt-1 text-xs leading-5 text-[#5f6368]">用现有市场数据筛选研究候选，不承诺收益，不触发真实下单。</div>
            </div>
          </div>
          <div className="flex flex-wrap items-center justify-end gap-2">
            {overview ? (
              <>
                <Badge status={overview.status === 'READY' ? 'PASS' : overview.status === 'PARTIAL' ? 'WARN' : 'FAIL'}>
                  {overview.status}
                </Badge>
                <Badge status={modeStatus(overview.dataMode)}>{overview.dataMode}</Badge>
                <span className="rounded-full border border-[#dfe3eb] bg-[#f8fafd] px-3 py-1 text-xs font-medium text-[#5f6368]">
                  {overview.provider} · {fmtDate(overview.fetchedAt)}
                </span>
              </>
            ) : null}
            <button
              type="button"
              onClick={load}
              disabled={loading}
              className="inline-flex h-9 items-center gap-1.5 rounded-full px-4 text-xs font-semibold text-white transition hover:bg-[#0842a0] disabled:opacity-60"
              style={{ backgroundColor: MATERIAL_BLUE_DARK }}
            >
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
              刷新
            </button>
          </div>
        </div>
      </div>

      <div className="grid gap-0 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="space-y-4 p-4 sm:p-6">
          {overview ? (
            <>
              <MarketOverviewPanel overview={overview} />
              <div className="flex flex-wrap items-end justify-between gap-3">
                <div>
                  <h2 className="text-base font-semibold text-[#1f1f1f]">四大指数对比</h2>
                  <p className="mt-1 text-xs text-[#5f6368]">用 OHLC 日 K 蜡烛图展示近 32 条走势，红涨绿跌。</p>
                </div>
                <span className="rounded-full border border-[#dfe3eb] bg-white px-3 py-1 text-xs font-medium text-[#5f6368]">
                  点击指数切换下方详情
                </span>
              </div>
              <div className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-4">
                {overview.indices.map((item) => {
                  const active = item.key === activeKey
                  const pct = item.latest?.pctChange
                  const Icon = typeof pct === 'number' && pct < 0 ? TrendingDown : TrendingUp
                  return (
                    <button
                      key={item.key}
                      type="button"
                      onClick={() => setActiveKey(item.key)}
                      className={`rounded-md border p-3 text-left transition focus:outline-none focus:ring-2 focus:ring-[#1a73e8]/35 ${
                        active
                          ? 'border-[#1a73e8] bg-[#e8f0fe] shadow-[0_1px_2px_rgba(26,115,232,0.16)]'
                          : 'border-[#dfe3eb] bg-white hover:border-[#b8c5d6] hover:bg-[#f8fafd]'
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate text-sm font-semibold text-[#1f1f1f]">{item.name}</span>
                        <Icon size={15} className={toneByChange(pct)} />
                      </div>
                      <div className="mt-2 flex items-end justify-between gap-2">
                        <span className="text-lg font-semibold text-[#1f1f1f]">{fmtNumber(item.latest?.close)}</span>
                        <span className={`text-sm font-semibold ${toneByChange(pct)}`}>{fmtPercent(pct)}</span>
                      </div>
                      <div className="mt-1 truncate text-[11px] text-[#5f6368]">
                        {formatSourceBadge(item.selectedProvider, item.freshness, item.fallbackUsed, item.reviewOnly)}
                      </div>
                      <IndexMiniKline index={item} active={active} />
                    </button>
                  )
                })}
              </div>

              {activeIndex ? (
                <div className={`${MATERIAL_CARD} p-4`}>
                  <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="text-lg font-semibold text-[#1f1f1f]">{activeIndex.name}</div>
                      <div className="mt-1 text-xs text-[#5f6368]">
                        {activeIndex.symbol} · {fmtDate(activeIndex.lastTradeDate)} · {activeIndex.recordCount} 条日 K · {formatSourceBadge(activeIndex.selectedProvider, activeIndex.freshness, activeIndex.fallbackUsed, activeIndex.reviewOnly)}
                      </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge status={activeIndex.status === 'READY' ? modeStatus(activeIndex.dataMode, activeIndex.reviewOnly) : 'WARN'}>
                        {activeIndex.reviewOnly ? 'REVIEW' : activeIndex.dataMode}
                      </Badge>
                      <span className={`text-sm font-semibold ${toneByChange(activeIndex.latest?.pctChange)}`}>
                        {fmtPercent(activeIndex.latest?.pctChange)}
                      </span>
                    </div>
                  </div>
                  <div className="mb-3 flex flex-wrap items-center justify-between gap-2 border-t border-[#eef2f6] pt-3">
                    <div className="rounded-full border border-[#dfe3eb] bg-[#f8fafd] px-3 py-1 text-xs font-semibold text-[#5f6368]">
                      {formatDailyRenderMode(activeIndex)}
                    </div>
                    <div className="w-full text-left text-xs leading-5 text-[#5f6368] sm:w-auto sm:text-right">
                      仲裁 {formatConsensus(activeIndex.sourceConsensus)}
                    </div>
                  </div>
                  <DailyStatusNotice index={activeIndex} />
                  <ConflictNotice conflicts={activeIndex.conflicts} />
                  <MiniKline index={activeIndex} />
                  <TechnicalInterpretationPanel index={activeIndex} />
                </div>
              ) : null}
              <SectorRankPanel overview={overview} />
              <AutoStockSelectorPanel overview={overview} />
            </>
          ) : (
            <div className={`${MATERIAL_CARD} flex min-h-[360px] items-center justify-center px-4 text-center text-sm text-[#5f6368]`}>
              {loading ? '正在加载股市全局数据...' : error || '等待股市全局数据'}
            </div>
          )}
        </div>

        <aside className="border-t border-[#dfe3eb] bg-[#eef3f9]/70 p-4 sm:p-6 xl:border-l xl:border-t-0">
          {overview ? (
            <div className="space-y-4">
              <TemperaturePanel overview={overview} />
              <FundFlowPanel overview={overview} />
              <div className={`${MATERIAL_CARD} p-4`}>
                <div className="mb-3 text-sm font-semibold text-[#1f1f1f]">来源新鲜度</div>
                <SourceFreshnessPanel
                  sources={[
                    {
                      label: '全局快照',
                      freshness: overview.status,
                      mode: `${overview.provider} · ${fmtDate(overview.fetchedAt)}`,
                    },
                    {
                      label: '资金流',
                      freshness: overview.fundFlow.freshness,
                      mode: `${formatSourceLabel(overview.fundFlow.selectedProvider || overview.fundFlow.provider, overview.fundFlow.selectedSource)} · ${overview.fundFlow.status}`,
                    },
                    {
                      label: '板块排行',
                      freshness: fmtDate(overview.sectorRank.tradeDate || overview.sectorRank.fetchedAt),
                      mode: `${formatSourceLabel(overview.sectorRank.selectedProvider || overview.sectorRank.provider, overview.sectorRank.selectedSource || overview.sectorRank.source)} · ${overview.sectorRank.status}`,
                    },
                  ]}
                />
              </div>
              <div className={`${MATERIAL_CARD} p-4`}>
                <div className="flex items-center gap-2 text-sm font-semibold text-[#1f1f1f]">
                  <Activity size={16} className="text-[#0b57d0]" />
                  指数涨跌面
                </div>
                <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
                  <MetricTile label="上涨" value={overview.temperature.risingCount} tone="danger" className="!rounded-lg !border-red-100 !bg-red-50 !p-3 !shadow-none" />
                  <MetricTile label="下跌" value={overview.temperature.fallingCount} tone="success" className="!rounded-lg !border-emerald-100 !bg-emerald-50 !p-3 !shadow-none" />
                </div>
                {overview.error ? <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">{overview.error}</div> : null}
              </div>
            </div>
          ) : (
            <div className={`${MATERIAL_CARD} p-4 text-sm text-[#5f6368]`}>
              {error || '市场温度与资金流等待加载'}
            </div>
          )}
        </aside>
      </div>
    </section>
  )
}
