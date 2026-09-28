import type { AnalysisRun } from '../types'

export type SourceKind = 'LIVE' | 'FALLBACK' | 'DERIVED' | 'MOCK' | 'MISSING' | 'USER_INPUT' | 'LEGACY_TEMPLATE'

export interface DashboardProvenanceItem {
  key: string
  label: string
  kind: SourceKind
  kindLabel: string
  status: 'PASS' | 'WARN' | 'FAIL' | 'WAIT'
  detail: string
  provider?: string
}

export interface DashboardProvenanceFreshnessItem {
  key: string
  label: string
  status: 'PASS' | 'WARN' | 'FAIL' | 'WAIT'
  freshness: string
  detail: string
  provider?: string
  fetchedAt?: string
}

export interface DashboardProvenanceSummary {
  level: 'HIGH' | 'MEDIUM' | 'LOW' | 'UNKNOWN'
  label: string
  status: 'PASS' | 'WARN' | 'FAIL' | 'WAIT'
  score: number
  reason: string
  headline: string
  items: DashboardProvenanceItem[]
  warnings: string[]
  fallbackChain: string[]
  missingFields: string[]
  reviewPoints: string[]
  freshnessItems: DashboardProvenanceFreshnessItem[]
  sourceCounts: Record<SourceKind, number>
}

export function sourceKindFromProvenance(value: unknown, fallback: SourceKind = 'MISSING'): SourceKind {
  if (!value || typeof value !== 'object') return fallback
  const item = value as Record<string, unknown>
  const raw = String(item.sourceType ?? item.dataMode ?? fallback).toUpperCase()
  if (raw.includes('LIVE')) return 'LIVE'
  if (raw.includes('FALLBACK') || raw.includes('DEGRAD')) return 'FALLBACK'
  if (raw.includes('DERIVED') || raw.includes('RULE')) return 'DERIVED'
  if (raw.includes('USER')) return 'USER_INPUT'
  if (raw.includes('LEGACY')) return 'LEGACY_TEMPLATE'
  if (raw.includes('MOCK') || raw.includes('TEMPLATE')) return 'MOCK'
  if (raw.includes('MISSING')) return 'MISSING'
  return fallback
}

export function isTemplateMacro(run: AnalysisRun) {
  const macro = run.market?.macroIndicators ?? {}
  return close(macro.cpi, 2.8) && close(macro.gdp, 4.5) && close(macro.policyRate, 3.65)
}

export function isTemplateMarket(run: AnalysisRun) {
  const market = run.market
  if (!market) return false
  return market.marketSentiment === 'NEUTRAL'
    && market.volatilityIndex === 52
    && market.liquidityIndex === 58
    && market.institutionalActivity === 'MEDIUM'
    && market.retailSentiment === 'NEUTRAL'
    && (market.sectorRotation ?? []).join(',') === '金融,科技'
}

export function isTemplatePortfolio(run: AnalysisRun) {
  const portfolio = run.portfolio
  return close(portfolio.themeConcentration, 0.28)
    && close(portfolio.sameRiskFactorConcentration, 0.17)
    && close(portfolio.industryExposure?.银行, 0.35)
    && close(portfolio.industryExposure?.证券, 0.15)
    && close(portfolio.industryExposure?.科技, 0.1)
}

export function isTemplateFactors(run: AnalysisRun) {
  const factors = run.factorSlicing?.factors ?? []
  const value = factors.find((factor) => factor.name === 'Value')
  const momentum = factors.find((factor) => factor.name === 'Momentum')
  const liquidity = factors.find((factor) => factor.name === 'Liquidity')
  return close(value?.weight, 0.3)
    && close(value?.contribution, 0.12)
    && close(momentum?.weight, 0.25)
    && close(momentum?.contribution, 0.09)
    && close(liquidity?.weight, 0.2)
    && close(liquidity?.contribution, 0.06)
}

export function qiamProbabilityKind(run: AnalysisRun): SourceKind {
  const source = String(run.qiam?.probabilitySource ?? '').toUpperCase()
  if (source.includes('PENDING')) return 'MISSING'
  if (!run.qiam) return 'MISSING'
  const { probabilityBandUp: up, probabilityBandSideways: sideways, probabilityBandDown: down } = run.qiam
  if ((close(up, 0.4) && close(sideways, 0.35) && close(down, 0.25)) || (close(up, 0.3) && close(sideways, 0.4) && close(down, 0.3))) {
    return 'MOCK'
  }
  if (source.includes('RULE')) return 'DERIVED'
  if (source.includes('MODEL')) return 'DERIVED'
  return 'DERIVED'
}

export function marketFieldKind(run: AnalysisRun, field: string): SourceKind {
  const provenance = run.market?.provenance?.[field]
  if (provenance) return sourceKindFromProvenance(provenance)
  if (field === 'macroIndicators' && isTemplateMacro(run)) return 'MOCK'
  if (isTemplateMarket(run)) return 'MOCK'
  return run.marketData?.status === 'READY' ? 'DERIVED' : 'MISSING'
}

export function portfolioKind(run: AnalysisRun): SourceKind {
  const provenance = run.portfolio?.provenance
  if (provenance) return sourceKindFromProvenance(provenance, 'USER_INPUT')
  if (isTemplatePortfolio(run)) return 'MOCK'
  return run.portfolio?.portfolioCoverage === 'HOLDINGS_CONNECTED' ? 'DERIVED' : 'USER_INPUT'
}

export function factorKind(run: AnalysisRun): SourceKind {
  const provenance = run.factorSlicing?.provenance
  if (provenance) return sourceKindFromProvenance(provenance, 'DERIVED')
  return isTemplateFactors(run) ? 'MOCK' : 'DERIVED'
}

export function sourceKindLabel(kind: SourceKind): string {
  const labels: Record<SourceKind, string> = {
    LIVE: 'LIVE 真实接入',
    FALLBACK: 'FALLBACK 降级链',
    DERIVED: '规则推算',
    MOCK: 'MOCK 模拟/模板',
    MISSING: 'MISSING 缺失',
    USER_INPUT: 'USER_INPUT_ONLY 人工输入',
    LEGACY_TEMPLATE: '历史模板',
  }
  return labels[kind]
}

function reviewGateProvenanceLabel(level: DashboardProvenanceSummary['level']) {
  if (level === 'HIGH') return '中等证据：需复核'
  if (level === 'MEDIUM') return '中等证据'
  if (level === 'LOW') return '弱证据'
  return '不可判断'
}

export function buildDashboardProvenanceSummary(run: AnalysisRun): DashboardProvenanceSummary {
  const items: DashboardProvenanceItem[] = []
  const dataSources = Object.entries(run.dataSources?.sources ?? {})
  for (const [key, source] of dataSources) {
    const rawMode = String(source.dataMode || run.dataSources?.summary?.overallDataMode || '').toUpperCase()
    const hasFallback = (source.fallbackChain?.length ?? 0) > 0 || (source.degradationChain?.length ?? 0) > 0
    const kind: SourceKind = source.available
      ? rawMode.includes('LIVE') ? 'LIVE' : rawMode.includes('FALLBACK') || hasFallback ? 'FALLBACK' : rawMode.includes('MOCK') ? 'MOCK' : 'DERIVED'
      : source.status === 'NOT_CONFIGURED' ? 'MISSING' : 'MISSING'
    items.push({
      key: `source:${key}`,
      label: source.name || key,
      kind,
      kindLabel: sourceKindLabel(kind),
      status: source.available ? (kind === 'MOCK' || kind === 'FALLBACK' ? 'WARN' : 'PASS') : 'FAIL',
      detail: [
        source.status,
        source.freshness,
        typeof source.confidence === 'number' ? `confidence ${(source.confidence * 100).toFixed(0)}%` : '',
      ].filter(Boolean).join(' / ') || source.detail || 'No detail',
      provider: source.provider,
    })
  }

  const portfolioSource = portfolioKind(run)
  items.push({
    key: 'portfolio',
    label: '持仓 / Portfolio',
    kind: portfolioSource,
    kindLabel: sourceKindLabel(portfolioSource),
    status: portfolioSource === 'MOCK' ? 'WARN' : 'PASS',
    detail: run.portfolio?.portfolioCoverage === 'HOLDINGS_CONNECTED'
      ? `snapshot ${String((run.portfolio as any).snapshotId || '') || 'connected'}`
      : 'USER_INPUT_ONLY：持仓、成本、可承受回撤来自任务输入',
  })

  const factorSource = factorKind(run)
  items.push({
    key: 'factor',
    label: '因子 / Factor',
    kind: factorSource,
    kindLabel: sourceKindLabel(factorSource),
    status: factorSource === 'MOCK' ? 'WARN' : 'PASS',
    detail: run.factorSlicing?.factorDataSource || run.factorSlicing?.mode || 'derived',
  })

  const qiamSource = qiamProbabilityKind(run)
  items.push({
    key: 'qiam',
    label: 'QIAM 概率',
    kind: qiamSource,
    kindLabel: sourceKindLabel(qiamSource),
    status: qiamSource === 'MOCK' || qiamSource === 'LEGACY_TEMPLATE' ? 'WARN' : qiamSource === 'MISSING' ? 'FAIL' : 'PASS',
    detail: String(run.qiam?.probabilitySource || 'rule/model derived'),
  })

  const finalWriterMode = String(run.finalWriter?.mode || '').toUpperCase()
  items.push({
    key: 'final_writer',
    label: '最终结论 / Final writer',
    kind: finalWriterMode === 'LLM_UNAVAILABLE' ? 'MISSING' : 'DERIVED',
    kindLabel: sourceKindLabel(finalWriterMode === 'LLM_UNAVAILABLE' ? 'MISSING' : 'DERIVED'),
    status: finalWriterMode === 'LLM_UNAVAILABLE' ? 'WARN' : 'PASS',
    detail: run.finalWriter?.mode || 'NORMAL',
  })

  const sourceCounts = emptySourceCounts()
  for (const item of items) {
    sourceCounts[item.kind] += 1
  }

  const warnings: string[] = []
  const dataSummary = run.dataSources?.summary
  if (dataSummary?.overallStatus && dataSummary.overallStatus !== 'READY') {
    warnings.push(`数据源整体状态 ${dataSummary.overallStatus}`)
  }
  if (sourceCounts.MOCK || sourceCounts.LEGACY_TEMPLATE) {
    warnings.push('包含模板或 mock 来源')
  }
  if (sourceCounts.FALLBACK) {
    warnings.push('存在 fallback/降级链，需确认主数据源失败原因')
  }
  if (sourceCounts.MISSING) {
    warnings.push('存在缺失来源')
  }
  if (run.dvg?.dataReliability === 'LOW') {
    warnings.push('DVG 数据可靠性为 LOW')
  }
  if (finalWriterMode === 'LLM_UNAVAILABLE') {
    warnings.push('Final Writer 处于 LLM_UNAVAILABLE')
  }

  const dataSourceScore = dataSummary && dataSummary.totalCount > 0
    ? dataSummary.availableCount / dataSummary.totalCount
    : dataSources.length ? dataSources.filter(([, source]) => source.available).length / dataSources.length : 0.5
  const kindScore = items.length
    ? items.reduce((total, item) => total + sourceKindScore(item.kind), 0) / items.length
    : 0
  const dvgScore = run.dvg?.dataReliability === 'HIGH' ? 1 : run.dvg?.dataReliability === 'MEDIUM' ? 0.65 : 0.3
  const compressedQuality = qualityScore((run.compressedSummary as any)?.quality?.score)
  const score = clamp01((kindScore * 0.45) + (dataSourceScore * 0.25) + (dvgScore * 0.2) + (compressedQuality * 0.1))

  const level = score >= 0.75 ? 'HIGH' : score >= 0.45 ? 'MEDIUM' : items.length ? 'LOW' : 'UNKNOWN'
  const label = reviewGateProvenanceLabel(level)
  const status = level === 'HIGH' ? 'PASS' : level === 'MEDIUM' ? 'WARN' : level === 'LOW' ? 'FAIL' : 'WAIT'
  const reason = warnings[0] || `可用来源 ${dataSummary?.availableRatio || `${items.length}/${items.length}`}`
  const fallbackChain = collectFallbackChain(run)
  const missingFields = collectMissingFields(run)
  const reviewPoints = collectReviewPoints(run, missingFields, fallbackChain, sourceCounts, finalWriterMode)
  const freshnessItems = collectSourceFreshness(run)
  const headline = [
    `行情/K线/辅助数据可信等级：${label}`,
    `来源：${compactKindCounts(sourceCounts)}`,
    missingFields.length ? `缺失 ${missingFields.length} 项` : '无核心缺失项',
  ].join('；')

  return {
    level,
    label,
    status,
    score,
    reason,
    headline,
    items,
    warnings,
    fallbackChain,
    missingFields,
    reviewPoints,
    freshnessItems,
    sourceCounts,
  }
}

function close(value: unknown, target: number) {
  return typeof value === 'number' && Math.abs(value - target) < 0.0001
}

function emptySourceCounts(): Record<SourceKind, number> {
  return {
    LIVE: 0,
    FALLBACK: 0,
    DERIVED: 0,
    MOCK: 0,
    MISSING: 0,
    USER_INPUT: 0,
    LEGACY_TEMPLATE: 0,
  }
}

function sourceKindScore(kind: SourceKind) {
  if (kind === 'LIVE') return 1
  if (kind === 'FALLBACK') return 0.55
  if (kind === 'DERIVED') return 0.75
  if (kind === 'USER_INPUT') return 0.6
  if (kind === 'MOCK' || kind === 'LEGACY_TEMPLATE') return 0.25
  return 0
}

function qualityScore(value: unknown) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 0.5
  return clamp01(value > 1 ? value / 100 : value)
}

function clamp01(value: number) {
  return Math.max(0, Math.min(1, value))
}

function collectFallbackChain(run: AnalysisRun): string[] {
  const rows: string[] = []
  for (const source of Object.values(run.dataSources?.sources ?? {})) {
    const chain = source.fallbackChain?.length ? source.fallbackChain : source.degradationChain ?? []
    if (!chain.length) continue
    const steps = chain.map((step) => {
      const provider = step.provider || step.adapterId || 'unknown'
      return `${provider}${step.success ? '(成功)' : '(失败)'}`
    })
    rows.push(`${source.name || source.provider}：${steps.join(' -> ')}`)
  }
  const marketProvider = String(run.marketData?.provider ?? '')
  const marketStatus = String(run.marketData?.status ?? '')
  if (marketProvider && marketStatus && marketStatus !== 'READY') {
    rows.push(`marketData：${marketProvider} / ${marketStatus}`)
  }
  return dedupe(rows).slice(0, 6)
}

function collectSourceFreshness(run: AnalysisRun): DashboardProvenanceFreshnessItem[] {
  const rows: DashboardProvenanceFreshnessItem[] = []
  for (const [key, source] of Object.entries(run.dataSources?.sources ?? {})) {
    const freshness = String(source.freshness || (source.fetchedAt ? 'fetched' : 'unknown'))
    const isReady = source.available && source.status === 'READY'
    rows.push({
      key: `freshness:${key}`,
      label: source.name || key,
      status: isReady ? 'PASS' : source.available ? 'WARN' : 'FAIL',
      freshness,
      provider: source.provider || source.adapterId,
      fetchedAt: source.fetchedAt,
      detail: source.error || source.degradationReason || source.detail || source.category || 'No source detail',
    })
  }

  if (rows.length === 0 && run.marketData) {
    const provider = String(run.marketData.provider || run.marketData.source || 'marketData')
    const status = String(run.marketData.status || run.dataMode || 'UNKNOWN')
    rows.push({
      key: 'freshness:marketData',
      label: 'Market data',
      status: status === 'READY' || status === 'LIVE' ? 'PASS' : status === 'UNKNOWN' ? 'WAIT' : 'WARN',
      freshness: String(run.marketData.freshness || run.marketData.fetchedAt || run.updatedAt || 'unknown'),
      provider,
      fetchedAt: String(run.marketData.fetchedAt || ''),
      detail: status,
    })
  }

  return rows.slice(0, 6)
}

function collectMissingFields(run: AnalysisRun): string[] {
  const fields: string[] = []
  for (const source of Object.values(run.dataSources?.sources ?? {})) {
    if (!source.available) fields.push(source.name || source.provider || source.category)
  }
  fields.push(...(run.dvg?.criticalMissingData ?? []))
  fields.push(...(run.factorSlicing?.missingFactorData ?? []))
  fields.push(...(run.chipKb?.coreMissingData ?? []))
  fields.push(...(run.qiam?.missingData ?? []))
  if (!run.marketData?.quote) fields.push('行情快照 quote')
  if (!run.technicalKline) fields.push('K线 technicalKline')
  if (!run.auxiliaryData) fields.push('辅助数据 auxiliaryData')
  return dedupe(fields.filter(Boolean).map(String)).slice(0, 10)
}

function collectReviewPoints(
  run: AnalysisRun,
  missingFields: string[],
  fallbackChain: string[],
  sourceCounts: Record<SourceKind, number>,
  finalWriterMode: string,
): string[] {
  const points: string[] = []
  if (fallbackChain.length) points.push('复核 fallback 链中失败的主数据源与最终采用的替代源')
  if (missingFields.length) points.push('复核缺失字段是否影响结论、仓位和执行可达性')
  if (sourceCounts.MOCK || sourceCounts.LEGACY_TEMPLATE) points.push('MOCK/模板来源只能用于演示或弱证据结论')
  if (portfolioKind(run) === 'USER_INPUT') points.push('USER_INPUT_ONLY 持仓和风险承受度需人工确认')
  if (run.finalWriter?.humanConfirmationRequired !== false) points.push('最终动作执行前需要人工确认')
  if (finalWriterMode === 'LLM_UNAVAILABLE') points.push('Final Writer 未接入 LLM，需人工阅读规则摘要')
  return dedupe(points).slice(0, 6)
}

function compactKindCounts(counts: Record<SourceKind, number>) {
  return (['LIVE', 'FALLBACK', 'MOCK', 'MISSING', 'USER_INPUT'] as SourceKind[])
    .filter((kind) => counts[kind] > 0)
    .map((kind) => `${sourceKindLabel(kind).split(' ')[0]} ${counts[kind]}`)
    .join(' / ') || '无来源'
}

function dedupe(values: string[]) {
  return Array.from(new Set(values))
}
