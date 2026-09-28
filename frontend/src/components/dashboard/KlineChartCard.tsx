import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertTriangle, RefreshCw } from 'lucide-react'
import { Card } from '../common/Card'
import { Badge } from '../common/Badge'
import { getKline, KlinePeriod, KlineRow } from '../../api/klineClient'

const PERIODS: Array<{ key: KlinePeriod; label: string }> = [
  { key: 'daily', label: '日线' },
  { key: 'weekly', label: '周线' },
  { key: 'monthly', label: '月线' },
]

const MOVING_AVERAGES = [
  { label: 'MA5', window: 5, color: '#f59e0b' },
  { label: 'MA10', window: 10, color: '#2563eb' },
  { label: 'MA20', window: 20, color: '#9333ea' },
]

function fmtDate(value: string) {
  if (value.length === 8) return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6)}`
  return value
}

function fmtNumber(value?: number | null, digits = 2) {
  if (typeof value !== 'number' || Number.isNaN(value)) return '-'
  return value.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits })
}

function rangeLabel(range?: string) {
  if (range === '2y') return '近 2 年'
  if (range === '6m') return '近 6 个月'
  return '近 3 个月'
}

function buildPath(points: Array<{ x: number; y: number }>) {
  return points.map((point, index) => `${index === 0 ? 'M' : 'L'} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(' ')
}

function calculateMovingAverage(rows: KlineRow[], window: number) {
  let sum = 0
  return rows.map((row, index) => {
    sum += row.close
    if (index >= window) sum -= rows[index - window].close
    if (index < window - 1) return null
    return sum / window
  })
}

function isNumber(value: number | null): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function KlineSvg({ rows }: { rows: KlineRow[] }) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null)
  const width = 820
  const height = 360
  const pad = { left: 56, right: 22, top: 28, bottom: 76 }
  const plotWidth = width - pad.left - pad.right
  const priceHeight = 208
  const volumeTop = pad.top + priceHeight + 28
  const volumeHeight = 56
  const movingAverages = MOVING_AVERAGES.map((item) => ({
    ...item,
    values: calculateMovingAverage(rows, item.window),
  }))
  const movingAveragePrices = movingAverages.flatMap((item) => item.values.filter(isNumber))
  const lows = rows.map((row) => row.low)
  const highs = rows.map((row) => row.high)
  const minPrice = Math.min(...lows, ...movingAveragePrices)
  const maxPrice = Math.max(...highs, ...movingAveragePrices)
  const priceRange = Math.max(maxPrice - minPrice, 0.01)
  const maxVolume = Math.max(...rows.map((row) => row.volume || 0), 1)
  const step = plotWidth / Math.max(rows.length, 1)
  const candleWidth = Math.min(10, Math.max(3, step * 0.56))
  const active = hoverIndex == null ? rows[rows.length - 1] : rows[hoverIndex]
  const activeIndex = hoverIndex == null ? rows.length - 1 : hoverIndex

  const xFor = (index: number) => pad.left + step * index + step / 2
  const yFor = (price: number) => pad.top + ((maxPrice - price) / priceRange) * priceHeight
  const closePath = buildPath(rows.map((row, index) => ({ x: xFor(index), y: yFor(row.close) })))
  const movingAveragePaths = movingAverages.map((item) => ({
    ...item,
    path: buildPath(
      item.values
        .map((value, index) => (isNumber(value) ? { x: xFor(index), y: yFor(value) } : null))
        .filter((point): point is { x: number; y: number } => point !== null),
    ),
  }))

  return (
    <div className="grid gap-3 lg:grid-cols-[1fr_220px]">
      <svg viewBox={`0 0 ${width} ${height}`} className="h-[300px] w-full rounded-md bg-white">
        {[0, 0.25, 0.5, 0.75, 1].map((ratio) => {
          const y = pad.top + ratio * priceHeight
          const price = maxPrice - ratio * priceRange
          return (
            <g key={ratio}>
              <line x1={pad.left} x2={width - pad.right} y1={y} y2={y} stroke="#e2e8f0" strokeDasharray="3 4" />
              <text x={8} y={y + 4} className="fill-slate-500 text-[11px]">{fmtNumber(price)}</text>
            </g>
          )
        })}
        <line x1={pad.left} x2={width - pad.right} y1={volumeTop + volumeHeight} y2={volumeTop + volumeHeight} stroke="#cbd5e1" />
        <path d={closePath} fill="none" stroke="#475569" strokeWidth={1.4} opacity={0.5} />
        {movingAveragePaths.map((item) => (
          item.path ? (
            <path key={item.label} d={item.path} fill="none" stroke={item.color} strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" />
          ) : null
        ))}
        <g>
          {movingAveragePaths.map((item, index) => (
            <g key={item.label} transform={`translate(${pad.left + index * 86}, 16)`}>
              <line x1={0} x2={18} y1={0} y2={0} stroke={item.color} strokeWidth={2} strokeLinecap="round" />
              <text x={24} y={4} className="fill-slate-500 text-[11px]">{item.label}</text>
            </g>
          ))}
        </g>
        {rows.map((row, index) => {
          const x = xFor(index)
          const openY = yFor(row.open)
          const closeY = yFor(row.close)
          const highY = yFor(row.high)
          const lowY = yFor(row.low)
          const rising = row.close >= row.open
          const color = rising ? '#dc2626' : '#16a34a'
          const bodyTop = Math.min(openY, closeY)
          const bodyHeight = Math.max(Math.abs(openY - closeY), 1.5)
          const volumeHeightCurrent = ((row.volume || 0) / maxVolume) * volumeHeight
          return (
            <g key={`${row.tradeDate}-${index}`} onMouseEnter={() => setHoverIndex(index)} onMouseLeave={() => setHoverIndex(null)}>
              <line x1={x} x2={x} y1={highY} y2={lowY} stroke={color} strokeWidth={1.2} />
              <rect x={x - candleWidth / 2} y={bodyTop} width={candleWidth} height={bodyHeight} fill={rising ? '#fee2e2' : '#dcfce7'} stroke={color} strokeWidth={1.2} />
              <rect x={x - candleWidth / 2} y={volumeTop + volumeHeight - volumeHeightCurrent} width={candleWidth} height={volumeHeightCurrent} fill={color} opacity={0.35} />
              <rect x={x - step / 2} y={pad.top} width={step} height={volumeTop + volumeHeight - pad.top} fill="transparent" />
              {hoverIndex === index && (
                <line x1={x} x2={x} y1={pad.top} y2={volumeTop + volumeHeight} stroke="#0f172a" strokeDasharray="3 3" opacity={0.5} />
              )}
            </g>
          )
        })}
        {[0, Math.floor(rows.length / 2), rows.length - 1].filter((value, index, arr) => value >= 0 && arr.indexOf(value) === index).map((index) => (
          <text key={index} x={xFor(index)} y={height - 20} textAnchor="middle" className="fill-slate-500 text-[11px]">
            {fmtDate(rows[index].tradeDate).slice(5)}
          </text>
        ))}
        <text x={8} y={volumeTop + 8} className="fill-slate-400 text-[11px]">成交量</text>
      </svg>

      <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-xs">
        <div className="mb-2 font-semibold text-slate-900">{fmtDate(active.tradeDate)}</div>
        <div className="grid grid-cols-2 gap-x-3 gap-y-2 text-slate-600">
          <span>开盘</span><strong className="text-right text-slate-950">{fmtNumber(active.open)}</strong>
          <span>最高</span><strong className="text-right text-slate-950">{fmtNumber(active.high)}</strong>
          <span>最低</span><strong className="text-right text-slate-950">{fmtNumber(active.low)}</strong>
          <span>收盘</span><strong className="text-right text-slate-950">{fmtNumber(active.close)}</strong>
          {movingAverages.map((item) => (
            <span key={item.label} className="contents">
              <span style={{ color: item.color }}>{item.label}</span>
              <strong className="text-right text-slate-950">{fmtNumber(item.values[activeIndex])}</strong>
            </span>
          ))}
          <span>涨跌幅</span><strong className="text-right text-slate-950">{fmtNumber(active.pctChange)}%</strong>
          <span>成交量</span><strong className="text-right text-slate-950">{fmtNumber(active.volume, 0)}</strong>
        </div>
      </div>
    </div>
  )
}

export function KlineChartCard({ symbol }: { symbol: string }) {
  const [period, setPeriod] = useState<KlinePeriod>('daily')
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<Awaited<ReturnType<typeof getKline>> | null>(null)
  const [error, setError] = useState('')

  const load = useCallback(async (nextPeriod = period) => {
    if (!symbol) return
    setLoading(true)
    setError('')
    try {
      setData(await getKline(symbol, nextPeriod))
    } catch (err) {
      setData(null)
      setError(err instanceof Error ? err.message : 'K线接口请求失败')
    } finally {
      setLoading(false)
    }
  }, [period, symbol])

  useEffect(() => {
    load(period)
  }, [load, period])

  const drawable = useMemo(() => {
    return Boolean(data && data.status === 'READY' && data.dataMode === 'LIVE' && data.provider === 'tushare' && data.rows.length > 0)
  }, [data])

  const message = error || data?.message || '等待获取 Tushare 真实 K 线数据。'

  return (
    <Card
      title="价格走势 · Tushare K线"
      action={
        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex rounded-md border border-slate-200 bg-slate-50 p-1">
            {PERIODS.map((item) => (
              <button
                key={item.key}
                type="button"
                onClick={() => setPeriod(item.key)}
                className={`rounded px-3 py-1 text-xs font-medium transition ${
                  period === item.key ? 'bg-slate-950 text-white shadow-sm' : 'text-slate-600 hover:bg-white'
                }`}
              >
                {item.label}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => load(period)}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 disabled:opacity-50"
          >
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
            刷新
          </button>
        </div>
      }
    >
      <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-slate-500">
        <Badge status={drawable ? 'PASS' : 'WARN'}>{drawable ? 'LIVE' : 'NO_CHART'}</Badge>
        <span>接口：{data?.apiName ?? period}</span>
        <span>范围：{rangeLabel(data?.range)}</span>
        {data?.recordCount != null && <span>记录：{data.recordCount}</span>}
        {data?.lastTradeDate && <span>最后交易日：{fmtDate(data.lastTradeDate)}</span>}
      </div>

      {loading && !data ? (
        <div className="flex h-[300px] items-center justify-center rounded-md border border-slate-200 bg-slate-50 text-sm text-slate-500">
          正在获取 Tushare 真实 K 线数据...
        </div>
      ) : drawable && data ? (
        <KlineSvg rows={data.rows} />
      ) : (
        <div className="flex min-h-[220px] items-center justify-center rounded-md border border-amber-200 bg-amber-50 px-4 text-center text-sm text-amber-800">
          <div>
            <AlertTriangle className="mx-auto mb-2 h-5 w-5" />
            <div className="font-semibold">未获取到真实 K 线数据，已停止绘图。</div>
            <div className="mt-1 max-w-xl text-xs leading-5 text-amber-700">{message}</div>
          </div>
        </div>
      )}
    </Card>
  )
}
