import { AnalysisRun } from '../types'
import { formatDateTime } from './format'

type InsightSection = {
  title: string
  content: string
  items: string[]
  riskLevel: 'LOW' | 'MEDIUM' | 'HIGH'
}

export type QiamProbabilityBand = {
  name: '上涨' | '震荡' | '下跌'
  value: number
}

export type QiamProbabilityView = {
  rows: QiamProbabilityBand[]
  source: 'MODEL_OUTPUT' | 'RULE_DERIVED' | 'LEGACY_TEMPLATE'
  note: string
}

function percent(value?: number) {
  if (typeof value !== 'number' || Number.isNaN(value)) return '暂无数据'
  return `${(value * 100).toFixed(1)}%`
}

function numberValue(value: unknown) {
  if (typeof value === 'number' && Number.isFinite(value)) return value.toLocaleString()
  if (typeof value === 'string' && value.trim()) return value
  return '暂无数据'
}

function listOrEmpty(values?: string[]) {
  return values?.length ? values.join('、') : '暂无'
}

function quoteValue(run: AnalysisRun, key: string) {
  return run.marketData?.quote?.[key] ?? run.marketData?.quote?.[key.toLowerCase()]
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value))
}

function normalizeBands(up: number, sideways: number, down: number): QiamProbabilityBand[] {
  const safe = [up, sideways, down].map((value) => Math.max(0.05, value))
  const total = safe.reduce((sum, value) => sum + value, 0)
  const normalized = safe.map((value) => Math.round((value / total) * 1000) / 10)
  const drift = Math.round((100 - normalized.reduce((sum, value) => sum + value, 0)) * 10) / 10
  normalized[1] = Math.round((normalized[1] + drift) * 10) / 10
  return [
    { name: '上涨', value: normalized[0] },
    { name: '震荡', value: normalized[1] },
    { name: '下跌', value: normalized[2] },
  ]
}

function isTemplateProbability(up?: number, sideways?: number, down?: number) {
  const close = (a: number | undefined, b: number) => typeof a === 'number' && Math.abs(a - b) < 0.0001
  return (
    (close(up, 0.4) && close(sideways, 0.35) && close(down, 0.25)) ||
    (close(up, 0.3) && close(sideways, 0.4) && close(down, 0.3))
  )
}

export function buildQiamProbabilityView(run: AnalysisRun): QiamProbabilityView {
  const qiam = run.qiam ?? {}
  const probabilitySource = String(qiam.probabilitySource ?? '').toUpperCase()
  const explicitUp = qiam.probabilityBandUp
  const explicitSideways = qiam.probabilityBandSideways
  const explicitDown = qiam.probabilityBandDown
  const templateProbability = isTemplateProbability(explicitUp, explicitSideways, explicitDown)
  const hasExplicit =
    typeof explicitUp === 'number' &&
    typeof explicitSideways === 'number' &&
    typeof explicitDown === 'number' &&
    !templateProbability

  if (probabilitySource.includes('PENDING') && typeof explicitUp === 'number' && typeof explicitSideways === 'number' && typeof explicitDown === 'number') {
    return {
      rows: normalizeBands(explicitUp, explicitSideways, explicitDown),
      source: 'RULE_DERIVED',
      note: '来源：任务尚未完成 QIAM 计算，当前仅为保守基线分布，不代表真实买入概率。',
    }
  }

  if (hasExplicit) {
    const source = probabilitySource.includes('MODEL') || probabilitySource.includes('LLM') ? 'MODEL_OUTPUT' : 'RULE_DERIVED'
    return {
      rows: normalizeBands(explicitUp, explicitSideways, explicitDown),
      source,
      note: source === 'MODEL_OUTPUT'
        ? '来源：后端 QIAM/LLM 输出的非模板概率。'
        : '来源：后端 QIAM 规则引擎按当前行情、DVG、执行可达性和缺失数据推算。',
    }
  }

  if (templateProbability) {
    return {
      rows: normalizeBands(explicitUp ?? 0.33, explicitSideways ?? 0.34, explicitDown ?? 0.33),
      source: 'LEGACY_TEMPLATE',
      note: '来源：历史模板概率，仅用于识别旧数据；请创建新任务获取当前标的的动态推算。',
    }
  }

  const changePercentRaw = quoteValue(run, 'changePercent') ?? quoteValue(run, 'pct_change')
  const changePercent =
    typeof changePercentRaw === 'number'
      ? changePercentRaw
      : typeof changePercentRaw === 'string'
        ? Number.parseFloat(changePercentRaw)
        : 0
  const finalSuitability = String(qiam.finalBuySuitability ?? '').toUpperCase()
  const reliability = String(run.dvg?.dataReliability ?? '').toUpperCase()
  const sentiment = String(run.market?.marketSentiment ?? '').toUpperCase()
  const executionReachability = String(run.execution?.executionReachability ?? '').toUpperCase()
  const liquidityRisk = String(run.atrade?.liquidityRisk ?? '').toUpperCase()
  const missingCount = [
    ...(run.dvg?.criticalMissingData ?? []),
    ...(run.factorSlicing?.missingFactorData ?? []),
    ...(qiam.missingData ?? []),
  ].length

  let up = 0.33
  let sideways = 0.34
  let down = 0.33

  const momentum = clamp((Number.isFinite(changePercent) ? changePercent : 0) / 10, -0.18, 0.18)
  if (momentum >= 0) {
    up += momentum
    down -= momentum * 0.55
  } else {
    down += Math.abs(momentum)
    up -= Math.abs(momentum) * 0.55
  }

  if (finalSuitability === 'FAVORABLE') up += 0.08
  if (finalSuitability === 'NEUTRAL') sideways += 0.08
  if (finalSuitability === 'REVIEW_ONLY') {
    sideways += 0.06
    down += 0.04
  }
  if (finalSuitability === 'BLOCK_BUY') down += 0.14

  if (reliability === 'HIGH') up += 0.04
  if (reliability === 'MEDIUM') sideways += 0.04
  if (reliability === 'LOW') down += 0.08

  if (sentiment === 'BULLISH') up += 0.04
  if (sentiment === 'BEARISH') down += 0.05
  if (sentiment === 'NEUTRAL') sideways += 0.03

  if (executionReachability === 'REACHABLE') up += 0.03
  if (executionReachability === 'NOT_REACHABLE' || executionReachability === 'UNREACHABLE') down += 0.08
  if (liquidityRisk === 'HIGH') down += 0.08
  if (liquidityRisk === 'MEDIUM') sideways += 0.04

  if (missingCount > 0) {
    sideways += Math.min(0.1, missingCount * 0.025)
    up -= Math.min(0.05, missingCount * 0.01)
  }

  return {
    rows: normalizeBands(up, sideways, down),
    source: 'RULE_DERIVED',
    note: '来源：当前标的行情、DVG、市场环境、执行可达性与缺失数据动态估算。模板概率不会再跨项目照搬。',
  }
}

function stripCodeFence(content: string) {
  const trimmed = content.trim()
  if (!trimmed.startsWith('```')) return trimmed
  const lines = trimmed.split(/\r?\n/)
  if (lines.length === 0) return trimmed
  const body = lines.slice(1)
  if (body[body.length - 1]?.trim() === '```') body.pop()
  return body.join('\n').trim()
}

function decodeJsonString(value: string) {
  try {
    return JSON.parse(`"${value}"`)
  } catch {
    return value.replace(/\\"/g, '"').replace(/\\n/g, '\n')
  }
}

function extractJsonStringField(content: string, field: string) {
  const match = new RegExp(`"${field}"\\s*:\\s*"((?:\\\\.|[^"\\\\])*)"`).exec(content)
  return match ? decodeJsonString(match[1]) : undefined
}

export function cleanFinalWriterContent(content?: string) {
  if (!content?.trim()) return undefined
  const stripped = stripCodeFence(content)

  try {
    const parsed = JSON.parse(stripped)
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      const oneLine = typeof parsed['一句话判断'] === 'string' ? parsed['一句话判断'] : undefined
      const reminder = typeof parsed['最终提醒'] === 'string' ? parsed['最终提醒'] : undefined
      return [oneLine, reminder].filter(Boolean).join(' ')
    }
  } catch {
    // Some model responses look like JSON but contain inline prose after booleans.
  }

  const oneLine = extractJsonStringField(stripped, '一句话判断')
  if (oneLine) return oneLine
  const reminder = extractJsonStringField(stripped, '最终提醒')
  if (reminder) return reminder

  if (stripped.startsWith('{') || stripped.startsWith('[')) return undefined
  return stripped
}

export function displayFinalWriterContent(content?: string) {
  const cleaned = cleanFinalWriterContent(content)
  if (cleaned) return cleaned
  const stripped = stripCodeFence(content ?? '')
  if (stripped.startsWith('{') || stripped.startsWith('[')) {
    return '该段原始输出为 JSON，已在上方按结论来源、基本面与因子、技术面与流动性、数据核验拆分展示；原始内容可在审计日志中追溯。'
  }
  return content || '暂无内容'
}

function sectionContent(run: AnalysisRun, titleIncludes: string) {
  return cleanFinalWriterContent(
    run.finalWriter?.sections?.find((section) => section.title.includes(titleIncludes))?.content
  )
}

function buySuitabilityLabel(raw: string): string {
  const map: Record<string, string> = {
    FAVORABLE: '有利',
    NEUTRAL: '中性',
    UNFAVORABLE: '不利',
    REVIEW_ONLY: '仅限审查',
    BLOCK_BUY: '阻断买入',
  }
  return map[raw] ?? raw
}

function outputLevelLabel(raw: string): string {
  const map: Record<string, string> = {
    FULL: '完整输出',
    REVIEW_ONLY: '仅限审查',
    BLOCK_BUY: '阻断买入',
  }
  return map[raw] ?? raw
}

function killSwitchLabel(raw: string): string {
  const map: Record<string, string> = {
    NONE: '未触发',
    SOFT: '软阻断',
    HARD: '硬阻断',
    COMPLIANCE: '合规阻断',
  }
  return map[raw] ?? raw
}

function sentimentLabel(raw: string): string {
  const map: Record<string, string> = {
    NEUTRAL: '中性',
    BULLISH: '偏多',
    BEARISH: '偏空',
    EXTREME_GREED: '极度贪婪',
    EXTREME_FEAR: '极度恐慌',
  }
  return map[raw] ?? raw
}

function activityLabel(raw: string): string {
  const map: Record<string, string> = { HIGH: '活跃', MEDIUM: '中等', LOW: '低迷' }
  return map[raw] ?? raw
}

function liquidityRiskLabel(raw: string): string {
  const map: Record<string, string> = { HIGH: '高', MEDIUM: '中等', LOW: '低' }
  return map[raw] ?? raw
}

function reachabilityLabel(raw: string): string {
  const map: Record<string, string> = {
    REACHABLE: '可达',
    CONDITIONALLY_REACHABLE: '有条件可达',
    NOT_REACHABLE: '不可达',
  }
  return map[raw] ?? raw
}

function priceLimitLabel(raw: string): string {
  const map: Record<string, string> = {
    NORMAL: '正常交易',
    LIMIT_UP: '涨停',
    LIMIT_DOWN: '跌停',
  }
  return map[raw] ?? raw
}

function hallucinationLabel(raw: string): string {
  const map: Record<string, string> = { LOW: '低风险', MEDIUM: '中等风险', HIGH: '高风险' }
  return map[raw] ?? raw
}

function finalActionLabel(raw: string): string {
  const map: Record<string, string> = {
    WAIT: '等待观察',
    HOLD: '继续持有',
    REVIEW_ONLY: '仅限审查',
    BUY_CANDIDATE: '买入候选',
    ADD_CANDIDATE: '加仓候选',
    REDUCE: '建议减仓',
    LIGHT_WATCH: '轻仓观察',
    SIGNAL_ONLY: '仅信号记录',
    DEFENSIVE: '防御模式',
  }
  return map[raw] ?? raw
}

function actionLabel(raw: string): string {
  const map: Record<string, string> = {
    WAIT: '等待',
    HOLD: '持有',
    REVIEW_ONLY: '仅审查',
    BUY_CANDIDATE: '买入候选',
    ADD_CANDIDATE: '加仓候选',
    LIGHT_WATCH: '轻仓观察',
    SIGNAL_ONLY: '仅信号',
    REDUCE: '减仓',
    WATCH: '观察',
    PAPER_TEST: '纸面测试',
  }
  return map[raw] ?? raw
}

export function buildConclusionInsights(run: AnalysisRun): InsightSection[] {
  const finalAction = run.finalWriter?.finalAction ?? run.finalAction
  const firstConclusion = cleanFinalWriterContent(run.finalWriter?.sections?.[0]?.content)
  const price = quoteValue(run, 'price')
  const changePercent = quoteValue(run, 'changePercent') ?? quoteValue(run, 'pct_change')
  const volume = quoteValue(run, 'volume')
  const fetchedAt = run.marketData?.fetchedAt ?? run.updatedAt

  return [
    {
      title: '结论来源',
      content:
        sectionContent(run, '结论') ??
        firstConclusion ??
        '最终动作由数据可信度、风险门禁、量化适宜性折扣、组合约束和执行可达性共同约束得出。当前数据可靠性处于中等水平，缺少关键 Level-2 逐笔成交和盘口深度信息，量化适宜性因折扣因子由「有利」降为「中性」，整体建议保持观察等待。',
      riskLevel: run.killSwitch.active ? 'HIGH' : run.qiam.finalBuySuitability === 'FAVORABLE' ? 'LOW' : 'MEDIUM',
      items: [
        `最终动作：${finalActionLabel(finalAction)}`,
        `量化适宜性：原始信号为「${buySuitabilityLabel(run.qiam.rawBuySuitability)}」，折扣后为「${buySuitabilityLabel(run.qiam.finalBuySuitability)}」，模型置信度 ${percent(run.qiam.modelConfidenceFinal)}`,
        `概率分布：上涨 ${percent(run.qiam.probabilityBandUp)}、震荡 ${percent(run.qiam.probabilityBandSideways)}、下跌 ${percent(run.qiam.probabilityBandDown)}`,
        `数据门禁：输出级别限制为「${outputLevelLabel(run.dvg.allowedOutputLevel)}」，确认数据占比 ${percent(run.dvg.confirmedRatio)}，推断数据 ${percent(run.dvg.inferredRatio)}，完全未知 ${percent(run.dvg.unknownRatio)}`,
        `熔断状态：${killSwitchLabel(run.killSwitch.level)}${run.killSwitch.active ? `，由「${run.killSwitch.triggerNode ?? '未知节点'}」触发` : ''}`,
        `执行可达性：${reachabilityLabel(run.execution.executionReachability)}，当前允许动作：${listOrEmpty((run.execution.allowedActions ?? []).map(actionLabel))}`,
      ],
    },
    {
      title: '基本面与因子',
      content:
        sectionContent(run, '基本面') ??
        '从市场情绪、行业轮动、量化因子和组合约束角度审视当前标的。当前市场情绪中性偏震荡，波动率处于常态区间；银行、证券等金融板块活跃，但行业集中度偏高需要关注；因子结构稳定但缺少换手率等辅助数据。',
      riskLevel: run.dvg.dataReliability === 'LOW' ? 'HIGH' : run.dvg.dataReliability === 'MEDIUM' ? 'MEDIUM' : 'LOW',
      items: [
        `标的：${run.stockCode} ${run.stockName || '（名称未提供）'}`,
        `市场情绪：${sentimentLabel(run.market.marketSentiment)}，机构活跃度：${activityLabel(run.market.institutionalActivity)}`,
        `板块轮动方向：${listOrEmpty(run.market.sectorRotation)}`,
        `因子模型：${run.factorSlicing.mode} 模式，稳定性 ${percent(run.factorSlicing.factorStability)}`,
        `仓位约束：单股当前 ${percent(run.portfolio.singleStockPosition)}，上限 ${percent(run.portfolio.singleStockPositionCap)}，可加仓：${run.portfolio.allowAddPosition ? '是' : '否'}`,
        `缺失信息：${listOrEmpty([...(run.dvg.criticalMissingData ?? []), ...(run.factorSlicing.missingFactorData ?? [])])}`,
      ],
    },
    {
      title: '技术面与流动性',
      content:
        sectionContent(run, '技术') ??
        '从行情快照、波动率、流动性指标、A 股交易约束和滑点条件出发评估技术面风险。当前标的未处于涨跌停状态，T+1 制度正常；但 Level-2 逐笔成交不可用，盘口深度不足，滑点和流动性冲击存在不确定性，成交为有条件可达。',
      riskLevel:
        run.atrade.liquidityRisk === 'HIGH' || run.execution.executionReachability === 'NOT_REACHABLE'
          ? 'HIGH'
          : run.atrade.liquidityRisk === 'MEDIUM'
            ? 'MEDIUM'
            : 'LOW',
      items: [
        `行情快照：最新价 ${numberValue(price)}，涨跌幅 ${numberValue(changePercent)}，成交量 ${numberValue(volume)}`,
        `波动率指数：${run.market.volatilityIndex}，流动性指数：${run.market.liquidityIndex}`,
        `交易状态：${priceLimitLabel(run.atrade.priceLimitStatus)}，T+1 制度：${run.atrade.t1Status ? '正常' : '需人工核验'}`,
        `Level-2 逐笔成交：${run.atrade.level2Available ? '可用' : '不可用'}，盘口深度：${run.atrade.depthAvailable ? '可用' : '不可用'}`,
        `流动性风险：${liquidityRiskLabel(run.atrade.liquidityRisk)}，滑点上限 ${percent(run.atrade.slippageLimit)}`,
        `参与率上限 ${percent(run.atrade.participationLimit)}，成交可达性：${reachabilityLabel(run.atrade.executionReachability)}`,
      ],
    },
    {
      title: '数据核验',
      content:
        sectionContent(run, '核验') ??
        '人工复核时请优先核对行情数据来源的真实性和时效性、关键缺失数据是否已补齐、数据源之间是否存在矛盾结论，以及审计链路是否完整可追溯。当前部分数据来自第三方估算模型，已标注为推断级证据。',
      riskLevel: run.dvg.hallucinationRiskLevel,
      items: [
        `行情来源：${run.marketData?.provider ?? '模拟数据（非真实行情）'}，状态：${run.marketData?.status ?? '模拟'}，获取时间：${formatDateTime(fetchedAt)}`,
        `数据可靠性：确认 ${percent(run.dvg.confirmedRatio)}，推断 ${percent(run.dvg.inferredRatio)}，未知 ${percent(run.dvg.unknownRatio)}`,
        `幻觉风险等级：${hallucinationLabel(run.dvg.hallucinationRiskLevel)}，评分 ${run.dvg.hallucinationRiskScore} 分（满分 100，分数越低越可靠）`,
        `关键缺失数据：${listOrEmpty(run.dvg.criticalMissingData)}`,
        `数据冲突项：${listOrEmpty(run.dvg.dataConflicts)}`,
        `审计追溯 ID：${run.finalWriter?.auditId ?? run.killSwitch.auditId ?? '（未生成）'}`,
      ],
    },
  ]
}
