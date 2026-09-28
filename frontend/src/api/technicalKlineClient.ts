import { request } from './httpClient'

export type TechnicalBias = 'BULLISH' | 'NEUTRAL' | 'BEARISH' | 'INSUFFICIENT_DATA'
export type TechnicalStatus = 'PASS' | 'WARN' | 'SKIPPED'

export interface TechnicalKlineAnalysis {
  agent: 'technical_kline_analyst'
  symbol: string
  status: TechnicalStatus
  technicalBias: TechnicalBias
  confidence: number
  dataQuality: {
    provider: string
    dataMode: 'LIVE' | 'UNAVAILABLE'
    dailyCount: number
    weeklyCount: number
    monthlyCount: number
    volumeMissingRatio: number
    periodStatus: Record<string, { status: string; dataMode: string; recordCount: number; apiName: string }>
    issues: string[]
  }
  trend: {
    close?: number
    ma5?: number
    ma10?: number
    ma20?: number
    return20d?: number
    return60d?: number
    structure?: string
  }
  volumePrice: {
    status: 'AVAILABLE' | 'UNAVAILABLE'
    volumeRatio5v20: number | null
    description: string
  }
  supportResistance: {
    support20d?: number
    resistance20d?: number
    support60d?: number
    resistance60d?: number
    distanceToSupport20d?: number
    distanceToResistance20d?: number
  }
  technicalIndicators: {
    macd: {
      status: 'AVAILABLE' | 'UNAVAILABLE'
      window: string
      sampleCount: number
      dif: number | null
      dea: number | null
      histogram: number | null
      signal: string
    }
    rsi: {
      status: 'AVAILABLE' | 'UNAVAILABLE'
      window: number
      sampleCount: number
      value: number | null
      signal: string
    }
    kdj: {
      status: 'AVAILABLE' | 'UNAVAILABLE'
      window: number
      sampleCount: number
      k: number | null
      d: number | null
      j: number | null
      signal: string
    }
    bollinger: {
      status: 'AVAILABLE' | 'UNAVAILABLE'
      window: number
      sampleCount: number
      mid: number | null
      upper: number | null
      lower: number | null
      bandwidth: number | null
      position: number | null
      signal: string
    }
  }
  patterns?: {
    status: 'AVAILABLE' | 'UNAVAILABLE' | 'NONE'
    sampleCount: number
    items: Array<{
      code: string
      label: string
      severity: 'INFO' | 'WARN'
      description: string
    }>
  }
  chipAnalysis?: {
    status: 'AVAILABLE' | 'UNAVAILABLE'
    source: 'TUSHARE_CYQ_CHIPS' | 'TUSHARE_CYQ_PERF' | 'KLINE_VOLUME_PRICE_PROXY' | 'UNAVAILABLE' | string
    sourceKind: 'C' | 'I' | 'U' | string
    sampleCount: number
    tradeDate?: string | null
    averageCostProxy: number | null
    closeToCostPct: number | null
    winnerRate?: number | null
    costPercentiles?: {
      cost5Pct: number | null
      cost15Pct: number | null
      cost50Pct: number | null
      cost85Pct: number | null
      cost95Pct: number | null
    }
    costZone: {
      low: number | null
      high: number | null
      volumeRatio: number | null
    }
    overheadVolumeRatio: number | null
    supportVolumeRatio: number | null
    distributionSample?: Array<{
      price: number
      percent: number
    }>
    concentrationLevel: 'HIGH' | 'MEDIUM' | 'LOW' | 'UNKNOWN' | string
    pressureLevel: 'HIGH' | 'MEDIUM' | 'LOW' | 'UNKNOWN' | string
    supportLevel: 'HIGH' | 'MEDIUM' | 'LOW' | 'UNKNOWN' | string
    signal: string
    description: string
    warnings?: string[]
  }
  multiPeriod: {
    weeklyReturn: number | null
    monthlyReturn: number | null
    alignment: string
  }
  risks: string[]
  forbiddenActions: string[]
  summaryForDownstream: string
  promptGovernance?: TechnicalKlinePromptGovernance
  analysisConfig?: TechnicalKlineAnalysisConfig
  caseClassification?: 'valid' | 'misjudge' | 'insufficient_data'
  caseClassificationDetail?: {
    classification: string
    source: string
    allowedValues: string[]
    issues: string[]
  }
  prompt: string
}

export interface TechnicalKlinePromptGovernance {
  version: string
  promptHash: string
  changedBy: string
  changeReason: string
  rollbackVersion: string
  outputMode: string
  tradeActionPolicy: string
}

export interface TechnicalKlineAnalysisConfig {
  version: string
  minimumSamples: Record<string, number>
  movingAverageWindows: Record<string, number>
  volumeWindows: Record<string, number>
  supportResistanceWindows: Record<string, number>
  riskThresholds: Record<string, number>
  configHash: string
}

export interface TechnicalKlineGovernanceConfig {
  ma_short?: number
  ma_medium?: number
  ma_long?: number
  volume_recent?: number
  volume_baseline?: number
  support_short?: number
  support_long?: number
  high_volume_ratio?: number
  near_support_distance?: number
  near_resistance_distance?: number
  case_classification?: 'valid' | 'misjudge' | 'insufficient_data' | ''
}

export interface TechnicalKlinePrompt {
  agent: string
  prompt: string
  promptGovernance: TechnicalKlinePromptGovernance
  analysisConfig: TechnicalKlineAnalysisConfig
  caseClassification: {
    allowedValues: string[]
    selected: string
  }
  outputMode: string
  dataPolicy: string
  tradeActionPolicy: string
}

export interface TechnicalKlineGovernance {
  agent: string
  promptGovernance: TechnicalKlinePromptGovernance
  analysisConfig: TechnicalKlineAnalysisConfig
  caseClassification: {
    allowedValues: string[]
    selected: string
  }
  dataPolicy: string
  tradeActionPolicy: string
  savedGovernance?: TechnicalKlineSavedGovernance
}

export interface TechnicalKlineSavedGovernance {
  config: Record<string, unknown>
  caseClassification: string
  updatedAt: string
  updatedBy: string
  changeReason: string
  cases: TechnicalKlineCaseRecord[]
  caseImpact?: TechnicalKlineCaseImpact
  auditLog: Array<Record<string, unknown>>
}

export interface TechnicalKlineCaseImpact {
  policy: {
    policyId: string
    usage: string
    minimumCasesForDecision: number
    weakSampleAction: string
    tradeActionPolicy: string
  }
  status: 'NO_CASES' | 'LOW_SAMPLE' | 'READY' | string
  totalCases: number
  classificationCounts: Record<string, number>
  validRate: number | null
  misjudgeRate: number | null
  insufficientDataRate: number | null
  currentConfig: {
    configHash: string
    promptVersion: string
    status: 'NO_CASES' | 'LOW_SAMPLE' | 'READY' | string
    caseCount: number
    classificationCounts: Record<string, number>
    validRate: number | null
    misjudgeRate: number | null
    insufficientDataRate: number | null
  }
  byConfigHash: Array<{
    configHash: string
    promptVersions: string[]
    totalCases: number
    classificationCounts: Record<string, number>
    latestCaseAt: string
    validRate: number | null
    misjudgeRate: number | null
    insufficientDataRate: number | null
  }>
  representativeCaseSet?: {
    policyId: string
    status: 'NO_CASES' | 'LOW_COVERAGE' | 'READY' | string
    minimumReviewedCases: number
    minimumSymbols: number
    requiredClassifications: string[]
    reviewedCaseCount: number
    uniqueSymbolCount: number
    symbols: string[]
    missingClassifications: string[]
    blocking: boolean
    action: string
    boundary: string
    remediation?: {
      requiredReviewedCaseDelta: number
      requiredUniqueSymbolDelta: number
      missingClassifications: string[]
      nextActions: string[]
    }
  }
  parameterVersionReview?: {
    policyId: string
    status:
      | 'NO_CURRENT_CONFIG_CASES'
      | 'LOW_CURRENT_CONFIG_SAMPLE'
      | 'INCOMPLETE_REPRESENTATIVE_CASE_SET'
      | 'NO_BASELINE_CONFIG'
      | 'READY_FOR_REVIEW'
      | string
    action: string
    currentConfigHash: string
    currentConfigCaseCount: number
    currentConfigClassificationCounts: Record<string, number>
    missingCurrentConfigClassifications: string[]
    baselineConfigCount: number
    comparison?: {
      baselineConfigHash: string
      baselineCaseCount: number
      validRateDelta: number | null
      misjudgeRateDelta: number | null
      insufficientDataRateDelta: number | null
    } | null
    boundary: string
  }
  longWindowRegression?: {
    policyId: string
    status:
      | 'NO_CASES'
      | 'LOW_COVERAGE'
      | 'NO_CURRENT_CONFIG_CASES'
      | 'NO_BASELINE_CONFIG'
      | 'INCOMPLETE_REPRESENTATIVE_CASE_SET'
      | 'READY_FOR_REVIEW'
      | string
    action: string
    minimumReviewedCases: number
    minimumConfigVersions: number
    minimumSymbols: number
    reviewedCaseCount: number
    uniqueSymbolCount: number
    configVersionCount: number
    baselineConfigCount: number
    currentConfigHash: string
    currentConfigCaseCount: number
    baselineCaseCount: number
    retainedCaseLimit: number
    symbols: string[]
    missingClassifications: string[]
    windows: Array<{
      label: string
      caseCount: number
      scope: string
    }>
    blocking: boolean
    boundary: string
    dataPolicy: string
    tradeActionPolicy: string
    remediation?: {
      requiredReviewedCaseDelta: number
      requiredConfigVersionDelta: number
      requiredUniqueSymbolDelta: number
      missingClassifications: string[]
      nextActions: string[]
    }
  }
  warnings: string[]
}

export interface TechnicalKlineCaseRecord {
  caseId: string
  caseLibraryCaseId?: string
  caseLibraryStatus?: string
  caseLibraryError?: string
  symbol: string
  classification: string
  note: string
  runId: string
  analysisStatus: string
  technicalBias: string
  configHash: string
  promptVersion: string
  createdAt: string
}

export interface TechnicalSignalBacktest {
  agent: 'technical_kline_analyst'
  symbol: string
  status: 'PASS' | 'WARN' | 'SKIPPED'
  horizonDays: number
  sampleCount: number
  requiredCount: number
  totalObservations: number
  evaluatedSignals: number
  neutralSkipped: number
  hitRate: number | null
  averageForwardReturn: number | null
  byBias: Record<'BULLISH' | 'BEARISH', {
    count: number
    hitRate: number | null
    averageForwardReturn: number | null
  }>
  recentSignals: Array<{
    tradeDate: string
    bias: 'BULLISH' | 'BEARISH'
    confidence: number
    close: number
    futureClose: number
    forwardReturn: number
    hit: boolean
    basis: string
  }>
  dataPolicy: string
  tradeActionPolicy: string
  summary: string
}

function ensureRecord(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(`Unexpected ${label} response`)
  }
  return value as Record<string, unknown>
}

function ensureArray<T = unknown>(value: unknown, label: string): T[] {
  if (!Array.isArray(value)) {
    throw new Error(`Unexpected ${label} response`)
  }
  return value as T[]
}

function requireString(record: Record<string, unknown>, key: string, label: string) {
  if (typeof record[key] !== 'string') {
    throw new Error(`Unexpected ${label} response: missing ${key}`)
  }
}

function requireNumber(record: Record<string, unknown>, key: string, label: string) {
  if (typeof record[key] !== 'number' || Number.isNaN(record[key])) {
    throw new Error(`Unexpected ${label} response: missing ${key}`)
  }
}

function requireBoolean(record: Record<string, unknown>, key: string, label: string) {
  if (typeof record[key] !== 'boolean') {
    throw new Error(`Unexpected ${label} response: missing ${key}`)
  }
}

function assertOptionalString(record: Record<string, unknown>, key: string, label: string) {
  if (record[key] !== undefined && record[key] !== null && typeof record[key] !== 'string') {
    throw new Error(`Unexpected ${label} response: invalid ${key}`)
  }
}

function assertOptionalNumber(record: Record<string, unknown>, key: string, label: string) {
  if (record[key] !== undefined && record[key] !== null && (typeof record[key] !== 'number' || Number.isNaN(record[key]))) {
    throw new Error(`Unexpected ${label} response: invalid ${key}`)
  }
}

function assertStringArray(value: unknown, label: string) {
  ensureArray(value, label).forEach((item) => {
    if (typeof item !== 'string') {
      throw new Error(`Unexpected ${label} response`)
    }
  })
}

function assertNumberRecord(value: unknown, label: string) {
  const record = ensureRecord(value, label)
  Object.values(record).forEach((item) => {
    if (typeof item !== 'number' || Number.isNaN(item)) {
      throw new Error(`Unexpected ${label} response`)
    }
  })
}

function assertNoTradePolicy(value: unknown, label: string) {
  if (value !== 'NO_DIRECT_TRADE_ACTION') {
    throw new Error(`${label} broke Technical Kline no-trade boundary`)
  }
}

function assertReviewOnlyBoundary(value: unknown, label: string) {
  if (value !== 'REVIEW_ONLY_NO_TRADE_ACTION') {
    throw new Error(`${label} broke Technical Kline review-only boundary`)
  }
}

function assertTechnicalKlinePromptGovernance(value: unknown): TechnicalKlinePromptGovernance {
  const governance = ensureRecord(value, 'Technical Kline prompt governance')
  requireString(governance, 'version', 'Technical Kline prompt governance')
  requireString(governance, 'promptHash', 'Technical Kline prompt governance')
  requireString(governance, 'changedBy', 'Technical Kline prompt governance')
  requireString(governance, 'changeReason', 'Technical Kline prompt governance')
  requireString(governance, 'rollbackVersion', 'Technical Kline prompt governance')
  requireString(governance, 'outputMode', 'Technical Kline prompt governance')
  requireString(governance, 'tradeActionPolicy', 'Technical Kline prompt governance')
  assertNoTradePolicy(governance.tradeActionPolicy, 'Technical Kline prompt governance')
  return value as TechnicalKlinePromptGovernance
}

function assertTechnicalKlineAnalysisConfig(value: unknown): TechnicalKlineAnalysisConfig {
  const config = ensureRecord(value, 'Technical Kline analysis config')
  requireString(config, 'version', 'Technical Kline analysis config')
  assertNumberRecord(config.minimumSamples, 'Technical Kline minimum samples')
  assertNumberRecord(config.movingAverageWindows, 'Technical Kline moving-average windows')
  assertNumberRecord(config.volumeWindows, 'Technical Kline volume windows')
  assertNumberRecord(config.supportResistanceWindows, 'Technical Kline support/resistance windows')
  assertNumberRecord(config.riskThresholds, 'Technical Kline risk thresholds')
  requireString(config, 'configHash', 'Technical Kline analysis config')
  return value as TechnicalKlineAnalysisConfig
}

function assertTechnicalKlineCaseClassification(value: unknown) {
  const classification = ensureRecord(value, 'Technical Kline case classification')
  assertStringArray(classification.allowedValues, 'Technical Kline allowed case classifications')
  requireString(classification, 'selected', 'Technical Kline case classification')
}

function assertTechnicalKlineCaseRecord(value: unknown): TechnicalKlineCaseRecord {
  const record = ensureRecord(value, 'Technical Kline case record')
  requireString(record, 'caseId', 'Technical Kline case record')
  assertOptionalString(record, 'caseLibraryCaseId', 'Technical Kline case record')
  assertOptionalString(record, 'caseLibraryStatus', 'Technical Kline case record')
  assertOptionalString(record, 'caseLibraryError', 'Technical Kline case record')
  requireString(record, 'symbol', 'Technical Kline case record')
  requireString(record, 'classification', 'Technical Kline case record')
  requireString(record, 'note', 'Technical Kline case record')
  requireString(record, 'runId', 'Technical Kline case record')
  requireString(record, 'analysisStatus', 'Technical Kline case record')
  requireString(record, 'technicalBias', 'Technical Kline case record')
  requireString(record, 'configHash', 'Technical Kline case record')
  requireString(record, 'promptVersion', 'Technical Kline case record')
  requireString(record, 'createdAt', 'Technical Kline case record')
  return value as TechnicalKlineCaseRecord
}

function assertTechnicalKlineCaseImpact(value: unknown): TechnicalKlineCaseImpact {
  const impact = ensureRecord(value, 'Technical Kline case impact')
  const policy = ensureRecord(impact.policy, 'Technical Kline case impact policy')
  requireString(policy, 'policyId', 'Technical Kline case impact policy')
  requireString(policy, 'usage', 'Technical Kline case impact policy')
  requireNumber(policy, 'minimumCasesForDecision', 'Technical Kline case impact policy')
  requireString(policy, 'weakSampleAction', 'Technical Kline case impact policy')
  requireString(policy, 'tradeActionPolicy', 'Technical Kline case impact policy')
  assertNoTradePolicy(policy.tradeActionPolicy, 'Technical Kline case impact policy')
  requireString(impact, 'status', 'Technical Kline case impact')
  requireNumber(impact, 'totalCases', 'Technical Kline case impact')
  assertNumberRecord(impact.classificationCounts, 'Technical Kline classification counts')
  assertOptionalNumber(impact, 'validRate', 'Technical Kline case impact')
  assertOptionalNumber(impact, 'misjudgeRate', 'Technical Kline case impact')
  assertOptionalNumber(impact, 'insufficientDataRate', 'Technical Kline case impact')

  const currentConfig = ensureRecord(impact.currentConfig, 'Technical Kline current config impact')
  requireString(currentConfig, 'configHash', 'Technical Kline current config impact')
  requireString(currentConfig, 'promptVersion', 'Technical Kline current config impact')
  requireString(currentConfig, 'status', 'Technical Kline current config impact')
  requireNumber(currentConfig, 'caseCount', 'Technical Kline current config impact')
  assertNumberRecord(currentConfig.classificationCounts, 'Technical Kline current config classification counts')
  assertOptionalNumber(currentConfig, 'validRate', 'Technical Kline current config impact')
  assertOptionalNumber(currentConfig, 'misjudgeRate', 'Technical Kline current config impact')
  assertOptionalNumber(currentConfig, 'insufficientDataRate', 'Technical Kline current config impact')

  ensureArray(impact.byConfigHash, 'Technical Kline by-config impact').forEach((itemValue) => {
    const item = ensureRecord(itemValue, 'Technical Kline by-config impact item')
    requireString(item, 'configHash', 'Technical Kline by-config impact item')
    assertStringArray(item.promptVersions, 'Technical Kline by-config prompt versions')
    requireNumber(item, 'totalCases', 'Technical Kline by-config impact item')
    assertNumberRecord(item.classificationCounts, 'Technical Kline by-config classification counts')
    requireString(item, 'latestCaseAt', 'Technical Kline by-config impact item')
    assertOptionalNumber(item, 'validRate', 'Technical Kline by-config impact item')
    assertOptionalNumber(item, 'misjudgeRate', 'Technical Kline by-config impact item')
    assertOptionalNumber(item, 'insufficientDataRate', 'Technical Kline by-config impact item')
  })

  if (impact.representativeCaseSet !== undefined) {
    assertTechnicalKlineRepresentativeCaseSet(impact.representativeCaseSet)
  }
  if (impact.parameterVersionReview !== undefined) {
    assertTechnicalKlineParameterVersionReview(impact.parameterVersionReview)
  }
  if (impact.longWindowRegression !== undefined) {
    assertTechnicalKlineLongWindowRegression(impact.longWindowRegression)
  }
  assertStringArray(impact.warnings, 'Technical Kline case impact warnings')
  return value as TechnicalKlineCaseImpact
}

function assertTechnicalKlineRepresentativeCaseSet(value: unknown) {
  const representative = ensureRecord(value, 'Technical Kline representative case set')
  requireString(representative, 'policyId', 'Technical Kline representative case set')
  requireString(representative, 'status', 'Technical Kline representative case set')
  requireNumber(representative, 'minimumReviewedCases', 'Technical Kline representative case set')
  requireNumber(representative, 'minimumSymbols', 'Technical Kline representative case set')
  assertStringArray(representative.requiredClassifications, 'Technical Kline representative required classifications')
  requireNumber(representative, 'reviewedCaseCount', 'Technical Kline representative case set')
  requireNumber(representative, 'uniqueSymbolCount', 'Technical Kline representative case set')
  assertStringArray(representative.symbols, 'Technical Kline representative symbols')
  assertStringArray(representative.missingClassifications, 'Technical Kline representative missing classifications')
  requireBoolean(representative, 'blocking', 'Technical Kline representative case set')
  if (representative.blocking !== false) {
    throw new Error('Technical Kline representative case set unexpectedly became blocking')
  }
  requireString(representative, 'action', 'Technical Kline representative case set')
  requireString(representative, 'boundary', 'Technical Kline representative case set')
  assertReviewOnlyBoundary(representative.boundary, 'Technical Kline representative case set')
  if (representative.remediation !== undefined) {
    assertTechnicalKlineRemediation(representative.remediation, 'Technical Kline representative remediation')
  }
}

function assertTechnicalKlineParameterVersionReview(value: unknown) {
  const review = ensureRecord(value, 'Technical Kline parameter version review')
  requireString(review, 'policyId', 'Technical Kline parameter version review')
  requireString(review, 'status', 'Technical Kline parameter version review')
  requireString(review, 'action', 'Technical Kline parameter version review')
  requireString(review, 'currentConfigHash', 'Technical Kline parameter version review')
  requireNumber(review, 'currentConfigCaseCount', 'Technical Kline parameter version review')
  assertNumberRecord(review.currentConfigClassificationCounts, 'Technical Kline current config classification counts')
  assertStringArray(review.missingCurrentConfigClassifications, 'Technical Kline missing current config classifications')
  requireNumber(review, 'baselineConfigCount', 'Technical Kline parameter version review')
  if (review.comparison !== undefined && review.comparison !== null) {
    const comparison = ensureRecord(review.comparison, 'Technical Kline parameter version comparison')
    requireString(comparison, 'baselineConfigHash', 'Technical Kline parameter version comparison')
    requireNumber(comparison, 'baselineCaseCount', 'Technical Kline parameter version comparison')
    assertOptionalNumber(comparison, 'validRateDelta', 'Technical Kline parameter version comparison')
    assertOptionalNumber(comparison, 'misjudgeRateDelta', 'Technical Kline parameter version comparison')
    assertOptionalNumber(comparison, 'insufficientDataRateDelta', 'Technical Kline parameter version comparison')
  }
  requireString(review, 'boundary', 'Technical Kline parameter version review')
  assertReviewOnlyBoundary(review.boundary, 'Technical Kline parameter version review')
}

function assertTechnicalKlineLongWindowRegression(value: unknown) {
  const regression = ensureRecord(value, 'Technical Kline long-window regression')
  requireString(regression, 'policyId', 'Technical Kline long-window regression')
  requireString(regression, 'status', 'Technical Kline long-window regression')
  requireString(regression, 'action', 'Technical Kline long-window regression')
  requireNumber(regression, 'minimumReviewedCases', 'Technical Kline long-window regression')
  requireNumber(regression, 'minimumConfigVersions', 'Technical Kline long-window regression')
  requireNumber(regression, 'minimumSymbols', 'Technical Kline long-window regression')
  requireNumber(regression, 'reviewedCaseCount', 'Technical Kline long-window regression')
  requireNumber(regression, 'uniqueSymbolCount', 'Technical Kline long-window regression')
  requireNumber(regression, 'configVersionCount', 'Technical Kline long-window regression')
  requireNumber(regression, 'baselineConfigCount', 'Technical Kline long-window regression')
  requireString(regression, 'currentConfigHash', 'Technical Kline long-window regression')
  requireNumber(regression, 'currentConfigCaseCount', 'Technical Kline long-window regression')
  requireNumber(regression, 'baselineCaseCount', 'Technical Kline long-window regression')
  requireNumber(regression, 'retainedCaseLimit', 'Technical Kline long-window regression')
  assertStringArray(regression.symbols, 'Technical Kline long-window symbols')
  assertStringArray(regression.missingClassifications, 'Technical Kline long-window missing classifications')
  ensureArray(regression.windows, 'Technical Kline long-window windows').forEach((windowValue) => {
    const window = ensureRecord(windowValue, 'Technical Kline long-window window')
    requireString(window, 'label', 'Technical Kline long-window window')
    requireNumber(window, 'caseCount', 'Technical Kline long-window window')
    requireString(window, 'scope', 'Technical Kline long-window window')
  })
  requireBoolean(regression, 'blocking', 'Technical Kline long-window regression')
  if (regression.blocking !== false) {
    throw new Error('Technical Kline long-window regression unexpectedly became blocking')
  }
  requireString(regression, 'boundary', 'Technical Kline long-window regression')
  assertReviewOnlyBoundary(regression.boundary, 'Technical Kline long-window regression')
  requireString(regression, 'dataPolicy', 'Technical Kline long-window regression')
  requireString(regression, 'tradeActionPolicy', 'Technical Kline long-window regression')
  assertNoTradePolicy(regression.tradeActionPolicy, 'Technical Kline long-window regression')
  if (regression.remediation !== undefined) {
    assertTechnicalKlineRemediation(regression.remediation, 'Technical Kline long-window remediation')
  }
}

function assertTechnicalKlineRemediation(value: unknown, label: string) {
  const remediation = ensureRecord(value, label)
  requireNumber(remediation, 'requiredReviewedCaseDelta', label)
  assertOptionalNumber(remediation, 'requiredUniqueSymbolDelta', label)
  assertOptionalNumber(remediation, 'requiredConfigVersionDelta', label)
  assertStringArray(remediation.missingClassifications, `${label} missing classifications`)
  assertStringArray(remediation.nextActions, `${label} next actions`)
}

function assertTechnicalKlineSavedGovernance(value: unknown): TechnicalKlineSavedGovernance {
  const saved = ensureRecord(value, 'Technical Kline saved governance')
  ensureRecord(saved.config, 'Technical Kline saved governance config')
  requireString(saved, 'caseClassification', 'Technical Kline saved governance')
  requireString(saved, 'updatedAt', 'Technical Kline saved governance')
  requireString(saved, 'updatedBy', 'Technical Kline saved governance')
  requireString(saved, 'changeReason', 'Technical Kline saved governance')
  ensureArray(saved.cases, 'Technical Kline saved governance cases').forEach(assertTechnicalKlineCaseRecord)
  if (saved.caseImpact !== undefined) {
    assertTechnicalKlineCaseImpact(saved.caseImpact)
  }
  ensureArray(saved.auditLog, 'Technical Kline saved governance audit log')
  return value as TechnicalKlineSavedGovernance
}

function assertTechnicalKlineAnalysis(value: unknown): TechnicalKlineAnalysis {
  const analysis = ensureRecord(value, 'Technical Kline analysis')
  if (analysis.agent !== 'technical_kline_analyst') {
    throw new Error('Unexpected Technical Kline analysis response: wrong agent')
  }
  requireString(analysis, 'symbol', 'Technical Kline analysis')
  requireString(analysis, 'status', 'Technical Kline analysis')
  requireString(analysis, 'technicalBias', 'Technical Kline analysis')
  requireNumber(analysis, 'confidence', 'Technical Kline analysis')
  const dataQuality = ensureRecord(analysis.dataQuality, 'Technical Kline data quality')
  requireString(dataQuality, 'provider', 'Technical Kline data quality')
  requireString(dataQuality, 'dataMode', 'Technical Kline data quality')
  requireNumber(dataQuality, 'dailyCount', 'Technical Kline data quality')
  requireNumber(dataQuality, 'weeklyCount', 'Technical Kline data quality')
  requireNumber(dataQuality, 'monthlyCount', 'Technical Kline data quality')
  requireNumber(dataQuality, 'volumeMissingRatio', 'Technical Kline data quality')
  ensureRecord(dataQuality.periodStatus, 'Technical Kline period status')
  assertStringArray(dataQuality.issues, 'Technical Kline data-quality issues')
  ensureRecord(analysis.trend, 'Technical Kline trend')
  const volumePrice = ensureRecord(analysis.volumePrice, 'Technical Kline volume price')
  requireString(volumePrice, 'status', 'Technical Kline volume price')
  assertOptionalNumber(volumePrice, 'volumeRatio5v20', 'Technical Kline volume price')
  requireString(volumePrice, 'description', 'Technical Kline volume price')
  ensureRecord(analysis.supportResistance, 'Technical Kline support/resistance')
  assertTechnicalIndicators(analysis.technicalIndicators)
  if (analysis.patterns !== undefined) {
    const patterns = ensureRecord(analysis.patterns, 'Technical Kline patterns')
    requireString(patterns, 'status', 'Technical Kline patterns')
    requireNumber(patterns, 'sampleCount', 'Technical Kline patterns')
    ensureArray(patterns.items, 'Technical Kline pattern items').forEach((itemValue) => {
      const item = ensureRecord(itemValue, 'Technical Kline pattern item')
      requireString(item, 'code', 'Technical Kline pattern item')
      requireString(item, 'label', 'Technical Kline pattern item')
      requireString(item, 'severity', 'Technical Kline pattern item')
      requireString(item, 'description', 'Technical Kline pattern item')
    })
  }
  if (analysis.chipAnalysis !== undefined) {
    assertTechnicalKlineChipAnalysis(analysis.chipAnalysis)
  }
  const multiPeriod = ensureRecord(analysis.multiPeriod, 'Technical Kline multi-period')
  assertOptionalNumber(multiPeriod, 'weeklyReturn', 'Technical Kline multi-period')
  assertOptionalNumber(multiPeriod, 'monthlyReturn', 'Technical Kline multi-period')
  requireString(multiPeriod, 'alignment', 'Technical Kline multi-period')
  assertStringArray(analysis.risks, 'Technical Kline risks')
  assertStringArray(analysis.forbiddenActions, 'Technical Kline forbidden actions')
  requireString(analysis, 'summaryForDownstream', 'Technical Kline analysis')
  if (analysis.promptGovernance !== undefined) {
    assertTechnicalKlinePromptGovernance(analysis.promptGovernance)
  }
  if (analysis.analysisConfig !== undefined) {
    assertTechnicalKlineAnalysisConfig(analysis.analysisConfig)
  }
  if (analysis.caseClassificationDetail !== undefined) {
    const detail = ensureRecord(analysis.caseClassificationDetail, 'Technical Kline case classification detail')
    requireString(detail, 'classification', 'Technical Kline case classification detail')
    requireString(detail, 'source', 'Technical Kline case classification detail')
    assertStringArray(detail.allowedValues, 'Technical Kline case classification detail allowed values')
    assertStringArray(detail.issues, 'Technical Kline case classification detail issues')
  }
  requireString(analysis, 'prompt', 'Technical Kline analysis')
  return value as TechnicalKlineAnalysis
}

function assertTechnicalIndicators(value: unknown) {
  const indicators = ensureRecord(value, 'Technical Kline indicators')
  ;['macd', 'rsi', 'kdj', 'bollinger'].forEach((key) => {
    const item = ensureRecord(indicators[key], `Technical Kline ${key}`)
    requireString(item, 'status', `Technical Kline ${key}`)
    requireNumber(item, 'sampleCount', `Technical Kline ${key}`)
    requireString(item, 'signal', `Technical Kline ${key}`)
  })
}

function assertTechnicalKlineChipAnalysis(value: unknown) {
  const chip = ensureRecord(value, 'Technical Kline chip analysis')
  requireString(chip, 'status', 'Technical Kline chip analysis')
  requireString(chip, 'source', 'Technical Kline chip analysis')
  requireString(chip, 'sourceKind', 'Technical Kline chip analysis')
  requireNumber(chip, 'sampleCount', 'Technical Kline chip analysis')
  assertOptionalString(chip, 'tradeDate', 'Technical Kline chip analysis')
  assertOptionalNumber(chip, 'averageCostProxy', 'Technical Kline chip analysis')
  assertOptionalNumber(chip, 'closeToCostPct', 'Technical Kline chip analysis')
  assertOptionalNumber(chip, 'winnerRate', 'Technical Kline chip analysis')
  const costZone = ensureRecord(chip.costZone, 'Technical Kline chip cost zone')
  assertOptionalNumber(costZone, 'low', 'Technical Kline chip cost zone')
  assertOptionalNumber(costZone, 'high', 'Technical Kline chip cost zone')
  assertOptionalNumber(costZone, 'volumeRatio', 'Technical Kline chip cost zone')
  assertOptionalNumber(chip, 'overheadVolumeRatio', 'Technical Kline chip analysis')
  assertOptionalNumber(chip, 'supportVolumeRatio', 'Technical Kline chip analysis')
  if (chip.distributionSample !== undefined) {
    ensureArray(chip.distributionSample, 'Technical Kline chip distribution').forEach((rowValue) => {
      const row = ensureRecord(rowValue, 'Technical Kline chip distribution row')
      requireNumber(row, 'price', 'Technical Kline chip distribution row')
      requireNumber(row, 'percent', 'Technical Kline chip distribution row')
    })
  }
  requireString(chip, 'concentrationLevel', 'Technical Kline chip analysis')
  requireString(chip, 'pressureLevel', 'Technical Kline chip analysis')
  requireString(chip, 'supportLevel', 'Technical Kline chip analysis')
  requireString(chip, 'signal', 'Technical Kline chip analysis')
  requireString(chip, 'description', 'Technical Kline chip analysis')
  if (chip.warnings !== undefined) {
    assertStringArray(chip.warnings, 'Technical Kline chip warnings')
  }
}

function assertTechnicalKlinePrompt(value: unknown): TechnicalKlinePrompt {
  const prompt = ensureRecord(value, 'Technical Kline prompt')
  requireString(prompt, 'agent', 'Technical Kline prompt')
  requireString(prompt, 'prompt', 'Technical Kline prompt')
  assertTechnicalKlinePromptGovernance(prompt.promptGovernance)
  assertTechnicalKlineAnalysisConfig(prompt.analysisConfig)
  assertTechnicalKlineCaseClassification(prompt.caseClassification)
  requireString(prompt, 'outputMode', 'Technical Kline prompt')
  requireString(prompt, 'dataPolicy', 'Technical Kline prompt')
  requireString(prompt, 'tradeActionPolicy', 'Technical Kline prompt')
  assertNoTradePolicy(prompt.tradeActionPolicy, 'Technical Kline prompt')
  return value as TechnicalKlinePrompt
}

function assertTechnicalKlineGovernance(value: unknown): TechnicalKlineGovernance {
  const governance = ensureRecord(value, 'Technical Kline governance')
  requireString(governance, 'agent', 'Technical Kline governance')
  assertTechnicalKlinePromptGovernance(governance.promptGovernance)
  assertTechnicalKlineAnalysisConfig(governance.analysisConfig)
  assertTechnicalKlineCaseClassification(governance.caseClassification)
  requireString(governance, 'dataPolicy', 'Technical Kline governance')
  requireString(governance, 'tradeActionPolicy', 'Technical Kline governance')
  assertNoTradePolicy(governance.tradeActionPolicy, 'Technical Kline governance')
  if (governance.savedGovernance !== undefined) {
    assertTechnicalKlineSavedGovernance(governance.savedGovernance)
  }
  return value as TechnicalKlineGovernance
}

function assertTechnicalSignalBacktest(value: unknown): TechnicalSignalBacktest {
  const backtest = ensureRecord(value, 'Technical Kline signal backtest')
  if (backtest.agent !== 'technical_kline_analyst') {
    throw new Error('Unexpected Technical Kline signal backtest response: wrong agent')
  }
  requireString(backtest, 'symbol', 'Technical Kline signal backtest')
  requireString(backtest, 'status', 'Technical Kline signal backtest')
  requireNumber(backtest, 'horizonDays', 'Technical Kline signal backtest')
  requireNumber(backtest, 'sampleCount', 'Technical Kline signal backtest')
  requireNumber(backtest, 'requiredCount', 'Technical Kline signal backtest')
  requireNumber(backtest, 'totalObservations', 'Technical Kline signal backtest')
  requireNumber(backtest, 'evaluatedSignals', 'Technical Kline signal backtest')
  requireNumber(backtest, 'neutralSkipped', 'Technical Kline signal backtest')
  assertOptionalNumber(backtest, 'hitRate', 'Technical Kline signal backtest')
  assertOptionalNumber(backtest, 'averageForwardReturn', 'Technical Kline signal backtest')
  ensureRecord(backtest.byBias, 'Technical Kline signal backtest byBias')
  ensureArray(backtest.recentSignals, 'Technical Kline recent signals').forEach((signalValue) => {
    const signal = ensureRecord(signalValue, 'Technical Kline recent signal')
    requireString(signal, 'tradeDate', 'Technical Kline recent signal')
    requireString(signal, 'bias', 'Technical Kline recent signal')
    requireNumber(signal, 'confidence', 'Technical Kline recent signal')
    requireNumber(signal, 'close', 'Technical Kline recent signal')
    requireNumber(signal, 'futureClose', 'Technical Kline recent signal')
    requireNumber(signal, 'forwardReturn', 'Technical Kline recent signal')
    requireBoolean(signal, 'hit', 'Technical Kline recent signal')
    requireString(signal, 'basis', 'Technical Kline recent signal')
  })
  requireString(backtest, 'dataPolicy', 'Technical Kline signal backtest')
  requireString(backtest, 'tradeActionPolicy', 'Technical Kline signal backtest')
  assertNoTradePolicy(backtest.tradeActionPolicy, 'Technical Kline signal backtest')
  requireString(backtest, 'summary', 'Technical Kline signal backtest')
  return value as TechnicalSignalBacktest
}

function appendGovernanceParams(params: URLSearchParams, config?: TechnicalKlineGovernanceConfig) {
  Object.entries(config ?? {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      params.set(key, String(value))
    }
  })
}

export function getTechnicalKlineAnalysis(symbol: string, config?: TechnicalKlineGovernanceConfig) {
  const params = new URLSearchParams({ symbol })
  appendGovernanceParams(params, config)
  return request<unknown>(`/technical-kline/analysis?${params.toString()}`, { timeoutMs: 30000 }).then(assertTechnicalKlineAnalysis)
}

export function getTechnicalSignalBacktest(symbol: string, horizonDays = 5) {
  const params = new URLSearchParams({ symbol, horizon_days: String(horizonDays) })
  return request<unknown>(`/technical-kline/signal-backtest?${params.toString()}`, { timeoutMs: 30000 }).then(assertTechnicalSignalBacktest)
}

export function getTechnicalKlinePrompt() {
  return request<unknown>('/technical-kline/prompt').then(assertTechnicalKlinePrompt)
}

export function getTechnicalKlineGovernance(config?: TechnicalKlineGovernanceConfig) {
  const params = new URLSearchParams()
  appendGovernanceParams(params, config)
  const query = params.toString()
  return request<unknown>(`/technical-kline/governance${query ? `?${query}` : ''}`).then(assertTechnicalKlineGovernance)
}

export function saveTechnicalKlineGovernance(config: TechnicalKlineGovernanceConfig, changeReason = '') {
  return request<unknown>('/technical-kline/governance', {
    method: 'PUT',
    body: JSON.stringify({
      ...config,
      changed_by: 'frontend',
      change_reason: changeReason,
    }),
  }).then(assertTechnicalKlineGovernance)
}

export function rollbackTechnicalKlineGovernance(reason = '') {
  return request<unknown>('/technical-kline/governance/rollback', {
    method: 'POST',
    body: JSON.stringify({
      changed_by: 'frontend',
      reason,
    }),
  }).then(assertTechnicalKlineGovernance)
}

export function recordTechnicalKlineCase(payload: {
  symbol: string
  classification: 'valid' | 'misjudge' | 'insufficient_data'
  note?: string
  run_id?: string
  analysis_status?: string
  technical_bias?: string
  config_hash?: string
  prompt_version?: string
}) {
  return request<unknown>('/technical-kline/cases', {
    method: 'POST',
    body: JSON.stringify(payload),
  }).then(assertTechnicalKlineCaseRecord)
}
