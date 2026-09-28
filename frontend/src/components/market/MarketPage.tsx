import { useAnalysisStore } from '../../store/useAnalysisStore'
import { SectionTitle } from '../common/SectionTitle'
import { Badge } from '../common/Badge'
import { Card } from '../common/Card'
import { MetricTile } from '../common/Material'
import { SourceBadge, SourceNote } from '../common/SourceBadge'
import { isTemplateMacro, isTemplateMarket, marketFieldKind } from '../../utils/dataProvenance'

export function MarketPage() {
  const { currentRun } = useAnalysisStore()

  if (!currentRun) {
    return <div>加载中...</div>
  }

  const market = currentRun.market
  const marketData = currentRun.marketData
  const marketTechnical = currentRun.marketTechnical
  const fusedTechnical = marketTechnical?.technicalKline ?? currentRun.technicalKline
  const quote = marketData?.quote ?? {}
  const marketTemplate = isTemplateMarket(currentRun)
  const macroTemplate = isTemplateMacro(currentRun)
  const sentimentKind = marketFieldKind(currentRun, 'marketSentiment')
  const institutionKind = marketFieldKind(currentRun, 'institutionalActivity')
  const macroKind = marketFieldKind(currentRun, 'macroIndicators')
  const formatNumber = (value: unknown, digits = 2) => {
    const numeric = Number(value)
    return Number.isFinite(numeric) ? numeric.toFixed(digits) : 'N/A'
  }
  const macroValue = (key: string) => {
    if (macroTemplate || macroKind === 'MISSING') return '未接入'
    const value = market.macroIndicators?.[key]
    return typeof value === 'number' ? `${value}%` : '未接入'
  }

  return (
    <div className="space-y-6">
      <SectionTitle title="市场环境" subtitle="市场环境分析" dataMode={currentRun?.dataMode} />

      <Card title="Tushare 实时行情">
        <div className="grid gap-4 md:grid-cols-[1.2fr_1fr_1fr_1fr]">
          <MetricTile label="标的" value={quote.symbol ?? currentRun.stockCode} helper={quote.name ?? currentRun.stockName} tone="primary" />
          <MetricTile label="价格" value={formatNumber(quote.price)} helper={`Prev ${formatNumber(quote.preClose)}`} tone="info" />
          <MetricTile label="涨跌幅" value={formatNumber(quote.change)} helper={`${formatNumber(quote.changePercent)}%`} tone={Number(quote.changePercent) >= 0 ? 'success' : 'danger'} />
          <MetricTile label="状态" value={marketData?.status ?? 'NOT_CONFIGURED'} helper={marketData?.provider ?? 'tushare'} tone={marketData?.status === 'READY' ? 'success' : marketData?.status ? 'warning' : 'neutral'} />
        </div>
        {marketData?.error ? <div className="mt-4 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">{marketData.error}</div> : null}
      </Card>

      {marketTechnical ? (
        <Card title="市场与 K 线融合上下文">
          <div className="grid gap-4 md:grid-cols-4">
            <MetricTile label="状态" value={marketTechnical.status ?? 'UNKNOWN'} tone={marketTechnical.status === 'PASS' ? 'success' : marketTechnical.status === 'SKIPPED' ? 'neutral' : 'warning'} />
            <MetricTile label="一致性" value={marketTechnical.alignment ?? 'UNKNOWN'} />
            <MetricTile label="技术偏向" value={fusedTechnical?.technicalBias ?? 'UNKNOWN'} tone="info" />
            <MetricTile label="置信度" value={typeof marketTechnical.confidence === 'number' ? `${(marketTechnical.confidence * 100).toFixed(0)}%` : 'N/A'} tone="success" />
          </div>
          {marketTechnical.summaryForDownstream ? (
            <div className="mt-4 rounded-md border border-slate-200 bg-slate-50 p-3 text-sm leading-6 text-slate-600">
              {marketTechnical.summaryForDownstream}
            </div>
          ) : null}
        </Card>
      ) : null}

      <div className="grid gap-6 md:grid-cols-2">
        <Card title="市场情绪" action={<SourceBadge kind={sentimentKind} />}>
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div className="text-sm text-slate-700">市场情绪</div>
              <Badge status={market.marketSentiment === 'NEUTRAL' ? 'WARN' : market.marketSentiment === 'BULLISH' ? 'PASS' : 'FAIL'}>
                {market.marketSentiment}
              </Badge>
            </div>
            <div className="flex items-center justify-between">
              <div className="text-sm text-slate-700">波动率指数</div>
              <div className="text-sm font-medium text-slate-900">{market.volatilityIndex}</div>
            </div>
            <div className="flex items-center justify-between">
              <div className="text-sm text-slate-700">流动性指数</div>
              <div className="text-sm font-medium text-slate-900">{market.liquidityIndex}</div>
            </div>
          </div>
          {marketTemplate ? (
            <SourceNote kind="MOCK" note="该情绪、波动率、流动性组合命中历史模板值；新运行会改为行情推算，无法推算时显示未接入。" />
          ) : (
            <SourceNote kind={sentimentKind} note="市场情绪、波动率和流动性为规则代理指标，不是外部直接给出的真实结论。" />
          )}
        </Card>

        <Card title="机构活动" action={<SourceBadge kind={institutionKind} />}>
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div className="text-sm text-slate-700">机构活动</div>
              <Badge status={market.institutionalActivity === 'HIGH' ? 'PASS' : market.institutionalActivity === 'MEDIUM' ? 'WARN' : 'FAIL'}>
                {market.institutionalActivity}
              </Badge>
            </div>
            <div className="flex items-center justify-between">
              <div className="text-sm text-slate-700">散户情绪</div>
              <Badge status={market.retailSentiment === 'NEUTRAL' ? 'WARN' : market.retailSentiment === 'OPTIMISTIC' ? 'PASS' : 'FAIL'}>
                {market.retailSentiment}
              </Badge>
            </div>
            <div className="flex items-center justify-between">
              <div className="text-sm text-slate-700">板块轮动</div>
              <div className="text-sm text-slate-600">{market.sectorRotation.length ? market.sectorRotation.join(', ') : '未接入'}</div>
            </div>
          </div>
          <SourceNote kind={institutionKind} note="机构活动、散户情绪和板块轮动需要资金流/行业板块数据；接口缺失时不再回填固定的“金融、科技”。" />
        </Card>
      </div>

      <Card title="宏观指标" action={<SourceBadge kind={macroKind} />}>
        <div className="grid gap-4 md:grid-cols-3">
          <MetricTile label="CPI" value={macroValue('cpi')} tone="info" />
          <MetricTile label="GDP" value={macroValue('gdp')} tone="info" />
          <MetricTile label="政策利率" value={macroValue('policyRate')} tone="info" />
        </div>
        <SourceNote kind={macroKind} note="宏观指标需要在设置中启用“宏观指标”数据源；未接入时隐藏旧模板 2.8/4.5/3.65。" />
      </Card>
    </div>
  )
}
