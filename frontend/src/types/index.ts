export type RunMode = 'FAST_MODE' | 'STANDARD_MODE' | 'DEEP_MODE'
export type QuantEngineMode = 'HIGH_FREQ_SHORT' | 'LOW_FREQ_MID_LONG'

export type RuntimeEnvironment = 'CHAT_ONLY' | 'CHAT_WITH_WEB' | 'CHAT_WITH_CODE' | 'API_ORCHESTRATED' | 'UNKNOWN'

export type NodeStatus = 'PASS' | 'WARN' | 'REVIEW_ONLY' | 'BLOCK_BUY' | 'FAIL' | 'ERROR' | 'SKIPPED' | 'RUNNING' | 'WAIT' | 'CANCELLED'

export type FinalAction = 'REJECT' | 'REVIEW_ONLY' | 'WAIT' | 'HOLD' | 'REDUCE' | 'LIGHT_WATCH' | 'BUY_CANDIDATE' | 'ADD_CANDIDATE' | 'DEFENSIVE' | 'SIGNAL_ONLY' | 'PAPER_TEST_ONLY'

export type KillSwitchLevel = 'NONE' | 'SOFT' | 'HARD' | 'COMPLIANCE'

export type FinalWriterMode =
  | 'NORMAL'
  | 'CONSERVATIVE'
  | 'HARD_RISK_FINAL_ONLY'
  | 'COMPLIANCE_REFUSAL'
  | 'LLM_UNAVAILABLE'

export type PermissionState = 'ALLOW' | 'ALLOW_WITH_DISCOUNT' | 'REVIEW_ONLY' | 'BLOCKED'

export type SignalOpsStatus = 'IDEA' | 'WATCH' | 'PAPER_TEST' | 'QUALIFIED' | 'TRADE_PLAN' | 'MANUAL_CONFIRMED' | 'EXECUTION_REVIEW' | 'CLOSED' | 'PATCH_REQUIRED' | 'REVIEW_ONLY'

export type AuditEventType =
  | 'RUN_CREATED'
  | 'RUN_QUEUED'
  | 'RUN_STARTED'
  | 'NODE_STARTED'
  | 'NODE_FINISHED'
  | 'NODE_SKIPPED'
  | 'NODE_DOWNGRADED'
  | 'DVG_PERMISSION_CHANGED'
  | 'QIAM_DISCOUNT_APPLIED'
  | 'KILL_SWITCH_TRIGGERED'
  | 'SIGNALOPS_STATE_CHANGED'
  | 'FINAL_WRITER_MODE_CHANGED'
  | 'ERROR_LEDGER_CREATED'
  | 'PATCH_CANDIDATE_CREATED'
  | 'RUN_FINISHED'
  | 'RUN_FAILED'
  | 'RUN_CANCELLED'
  | 'RUN_STALE_RECOVERED'
  | 'RUN_NOT_FOUND'
  | 'RUN_REMOVED'
  | 'STREAM_TIMEOUT'

export type AnalysisRunStatus = 'CREATED' | 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'STALE' | 'CANCELLED'

export type AnalysisJobStatus =
  | 'PENDING'
  | 'QUEUED'
  | 'RUNNING'
  | 'CANCEL_REQUESTED'
  | 'COMPLETED'
  | 'FAILED'
  | 'CANCELLED'
  | 'STALE'

export type CapabilityKey =
  | 'FULL_REPORT'
  | 'PRECISE_SCORE'
  | 'QIAM_POSITIVE'
  | 'SIGNALOPS_WATCH'
  | 'SIGNALOPS_PAPER_TEST'
  | 'SIGNALOPS_QUALIFIED'
  | 'BUY_CANDIDATE'
  | 'ADD_CANDIDATE'
  | 'EXECUTION_PLAN'
  | 'PAPER_RESULT'
  | 'PATCH_CANDIDATE'

export interface AgentNode {
  id: string
  name: string
  status: NodeStatus
  isRunning: boolean
  isSkipped: boolean
  isBlocked: boolean
  duration: number
  auditId: string
  inputSummary?: string
  outputSummary?: string
  missingData?: string[]
  downgradeReasons?: string[]
  blockedPaths?: string[]
  allowedNextActions?: string[]
  evidenceUsage: 'simulation_only' | (string & {})
  evidenceStrength: 'LOW' | 'MEDIUM' | 'PENDING' | (string & {})
  simulationOnly: boolean
  isRealTrade: boolean
  strongConclusionAllowed: boolean
  rawJson?: any
}

export type StandardAgentStatus = 'PASS' | 'WARN' | 'REVIEW_ONLY' | 'BLOCK' | 'ERROR' | 'SKIPPED'

export type AgentOutputSource =
  | 'LLM'
  | 'LLM_DEGRADED'
  | 'LLM_FAILED'
  | 'RULE_ENGINE'
  | 'PLUGIN_OBSERVATION'
  | 'NODE_SUMMARY'
  | 'MOCK'
  | (string & {})

export type TokenUsageSource =
  | 'PROVIDER_USAGE'
  | 'PROVIDER_EMPTY'
  | 'NO_PROVIDER_USAGE'
  | 'MOCK_ESTIMATE'
  | (string & {})

export interface LLMTraceItem {
  nodeId: string
  status: 'COMPLETED' | 'FAILED' | 'SKIPPED' | 'NOT_RUN' | (string & {})
  profileId?: string
  provider?: string
  model?: string
  latencyMs?: number
  usage?: Record<string, any>
  promptTokens?: number
  completionTokens?: number
  totalTokens?: number
  finishReason?: string
  error?: string
  timestamp?: string
}

export interface AgentResult {
  node: string
  name: string
  status: StandardAgentStatus
  allowed_actions: string[]
  blocked_actions: string[]
  hard_stop: boolean
  final_decision_cap: string | null
  confidence: 'HIGH' | 'MEDIUM' | 'LOW' | 'UNKNOWN'
  reasons: string[]
  missing_data: string[]
  warnings: string[]
  data: Record<string, any>
  audit_id: string
  elapsed_ms: number
  skipped_reason?: string
  legacyCompatibilityOnly?: boolean
  canonicalNode?: string
  activeNode?: boolean
}

export interface DagEvent {
  event_type: AuditEventType | 'KILL_SWITCH_TRIGGERED'
  run_id: string
  node: string
  order?: number
  status: StandardAgentStatus
  message: string
  elapsed_ms: number
  audit_id: string
  timestamp: string
}

export interface SkippedNode {
  node: string
  name: string
  reason: string
  audit_id: string
}

export interface AgentTokenUsageRow {
  node: string
  name: string
  status: string
  provider: string
  model: string
  profile_id: string
  profileId?: string
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  latency_ms: number
  finish_reason: string
  finishReason?: string
  error: string
  llm_status?: string
  llmStatus?: string
  source?: AgentOutputSource
  degradation_reason?: string
  degradationReason?: string
  usage_source?: TokenUsageSource
  usageSource?: TokenUsageSource
  audit_id: string
}

export interface TokenUsageSummary {
  rows: AgentTokenUsageRow[]
  totals: {
    prompt_tokens: number
    completion_tokens: number
    total_tokens: number
    latency_ms: number
  }
  top_agent?: AgentTokenUsageRow | null
  metering_status: string
  note: string
}

export interface AgentDebateTurn {
  order: number
  node: string
  name: string
  stance: 'support' | 'challenge' | 'block' | 'observe'
  claim: string
  evidence: string[]
  counterpoints: string[]
  decision_impact: string
  status: StandardAgentStatus
  confidence: 'HIGH' | 'MEDIUM' | 'LOW' | 'UNKNOWN'
  source?: AgentOutputSource
  token_total: number
  latency_ms: number
  audit_id: string
}

export interface DebateArtifacts {
  run_id: string
  final_action: FinalAction
  final_decision_cap: string
  kill_switch: KillSwitch
  turns: AgentDebateTurn[]
  summary: {
    support_count: number
    challenge_count: number
    block_count: number
    dominant_constraint: string
    final_action: FinalAction
    human_confirmation_required: boolean
  }
  audit_id: string
}

export interface DVGResult {
  status: NodeStatus
  quantEngineMode?: QuantEngineMode | (string & {})
  activeModule?: string
  activeModuleLabel?: string
  parameterProfile?: Record<string, any>
  dataReliability: 'HIGH' | 'MEDIUM' | 'LOW'
  confirmedRatio: number
  inferredRatio: number
  unknownRatio: number
  coreUnknownCount: number
  freshnessStatus: string
  sourceIntegrity: string
  hallucinationRiskScore: number
  hallucinationRiskLevel: 'LOW' | 'MEDIUM' | 'HIGH'
  criticalMissingData: string[]
  ignoredMissingData?: string[]
  rawCriticalMissingData?: string[]
  rawCoreUnknownCount?: number
  dataConflicts: string[]
  allowedOutputLevel: 'FULL' | 'REVIEW_ONLY' | 'BLOCK_BUY'
  qiamPermission: 'ALLOW' | 'ALLOW_WITH_DISCOUNT' | 'REVIEW_ONLY' | 'BLOCKED'
  scenarioPermission: 'ALLOW' | 'ALLOW_WITH_DISCOUNT' | 'REVIEW_ONLY' | 'BLOCKED'
  executionPermission: 'ALLOW' | 'ALLOW_WITH_DISCOUNT' | 'REVIEW_ONLY' | 'BLOCKED'
  finalDecisionCap: FinalAction | 'BLOCK_BUY'
  hardStop: boolean
  dvgModules?: Record<string, {
    moduleId: string
    label: string
    gatePolicy?: string
    quantEngineMode?: QuantEngineMode | (string & {})
    status: NodeStatus
    dataReliability: 'HIGH' | 'MEDIUM' | 'LOW'
    confirmedRatio: number
    inferredRatio: number
    unknownRatio: number
    coreUnknownCount: number
    rawCoreUnknownCount?: number
    hallucinationRiskScore: number
    hallucinationRiskLevel: 'LOW' | 'MEDIUM' | 'HIGH'
    criticalMissingData: string[]
    ignoredMissingData?: string[]
    qiamPermission: 'ALLOW' | 'ALLOW_WITH_DISCOUNT' | 'REVIEW_ONLY' | 'BLOCKED'
    scenarioPermission: 'ALLOW' | 'ALLOW_WITH_DISCOUNT' | 'REVIEW_ONLY' | 'BLOCKED'
    executionPermission: 'ALLOW' | 'ALLOW_WITH_DISCOUNT' | 'REVIEW_ONLY' | 'BLOCKED'
    allowedOutputLevel: 'FULL' | 'REVIEW_ONLY' | 'BLOCK_BUY'
    finalDecisionCap: FinalAction | 'BLOCK_BUY'
    hardStop: boolean
    sourceIntegrity: string
  }>
  provenance?: Record<string, any>
}

export interface RiskResult {
  complianceRedLines: string[]
  f0IndividualHardRisks: string[]
  f1ExtremeChipCollapse: string[]
  f4ThreePartyFundResonanceOutflow: string[]
  l0AbsoluteLiquidityRedLine: string[]
  m0SystemicRisk: string[]
  aStockMicrostructureUnexecutable: string[]
  qiamBlockBuy: string[]
  portfolioRiskOverLimit: string[]
  executionUnreachable: string[]
}

export interface ATradeResult {
  t1Status: boolean
  sellableBottomWarehouse: boolean
  priceLimitStatus: 'NORMAL' | 'UP_LIMIT' | 'DOWN_LIMIT'
  stDelistingRisk: boolean
  level2Available: boolean
  depthAvailable: boolean
  executionReachability: 'REACHABLE' | 'CONDITIONALLY_REACHABLE' | 'NOT_REACHABLE'
  liquidityRisk: 'LOW' | 'MEDIUM' | 'HIGH'
  flashCrashVacuumStatus: boolean
  slippageLimit: number
  participationLimit: number
}

export interface GuardrailHubResult {
  status: NodeStatus | 'BLOCK' | (string & {})
  finalDecisionCap?: FinalAction | 'BLOCK_BUY' | 'REVIEW_ONLY' | 'REJECT' | 'NO_CAP' | (string & {})
  killSwitch: KillSwitch
  dvg: DVGResult
  risk: RiskResult
  atrade: ATradeResult
  gateResults?: Record<string, any>
  warnings?: string[]
  auditId?: string
  synthesizedFromLegacy?: boolean
  preflightBlock?: boolean
}

export interface MarketResult {
  marketSentiment: 'BULLISH' | 'BEARISH' | 'NEUTRAL'
  volatilityIndex: number
  liquidityIndex: number
  institutionalActivity: 'HIGH' | 'MEDIUM' | 'LOW'
  retailSentiment: 'OPTIMISTIC' | 'PESSIMISTIC' | 'NEUTRAL'
  sectorRotation: string[]
  macroIndicators: Record<string, number>
  provenance?: Record<string, any>
  regimeClassification?: string
}

export interface MarketTechnicalResult {
  agent?: 'market_technical_analyst' | string
  status?: 'PASS' | 'WARN' | 'SKIPPED' | string
  market?: MarketResult
  technicalKline?: Record<string, any>
  alignment?: 'ALIGNED_BULLISH' | 'ALIGNED_BEARISH' | 'CONFLICT' | 'TECHNICAL_INSUFFICIENT_DATA' | 'NEUTRAL_OR_MIXED' | string
  confidence?: number | null
  summaryForDownstream?: string
  warnings?: string[]
}

export interface QuantCoreInterpretationDimension {
  key: 'qiam' | 'technical' | 'mfeMaeResearch' | 'bottom' | 'factor' | 'marketScenario' | (string & {})
  label: string
  score: number
  bias: 'BULLISH' | 'BEARISH' | 'SIDEWAYS' | 'MIXED' | 'UNKNOWN' | (string & {})
  confidence: number
  weight: number
  evidence: string[]
  warnings: string[]
}

export interface QuantCoreInterpretationConflict {
  key: string
  severity: 'INFO' | 'WARN' | 'BLOCKING_CONTEXT' | (string & {})
  message: string
  evidence: string[]
}

export interface QuantCorePathRiskCurvePoint {
  drawdownPct: number
  riskPotential: number
  riskGradient: number
  components?: {
    sellPressure?: number
    liquidityGap?: number
    stopLossDensity?: number
    marketPanic?: number
    supportDensity?: number
  }
}

export interface QuantCorePathRiskFilter {
  version: 'mfe_mae_path_risk_filter_v1' | (string & {})
  status: 'READY' | 'INSUFFICIENT_DATA' | string
  method: 'daily_proxy_no_future_labels_v1' | (string & {})
  horizonDays: number
  actionBoundary?: 'READ_ONLY_NO_PERMISSION_CHANGE' | (string & {})
  labelStatus?: 'UNLABELED_NOWCAST_PROXY_ONLY' | string
  sampleQuality?: Record<string, any>
  leakagePolicy?: string
  simulation_only?: boolean
  is_real_trade?: boolean
  mfeMaeProxy: {
    mfeProxy?: number | null
    maeProxy?: number | null
    riskRewardProxy?: number | null
  }
  riskCurve: QuantCorePathRiskCurvePoint[]
  downsideRiskScore?: number | null
  maxRiskGradient?: number | null
  riskPolicy: 'NORMAL' | 'WATCH' | 'THROTTLE' | 'AVOID_NEW_BUY' | string
  evidence: string[]
  warnings: string[]
  limitations: string[]
  provenance?: Record<string, any>
}

export interface QuantCoreFutureTrendProbabilityPoint {
  horizonDays: number
  rawUpProbability?: number | null
  rawDownProbability?: number | null
  rawSidewaysProbability?: number | null
  calibratedUpProbability?: number | null
  calibratedDownProbability?: number | null
  calibratedSidewaysProbability?: number | null
  confidence?: number | null
  calibrationStatus?: string
  sourceBreakdown?: Array<Record<string, any>>
  simulation_only?: boolean
  is_real_trade?: boolean
}

export interface QuantCoreFutureTrendProbability {
  version: 'quant_core_future_trend_probability_v1' | (string & {})
  source?: string
  points: QuantCoreFutureTrendProbabilityPoint[]
  calibration?: {
    method?: 'rolling_reliability_bins_v1' | (string & {})
    sampleCount?: number | null
    brierUp?: number | null
    brierDown?: number | null
    reliabilityBins?: Record<string, any>
    maxAdjustment?: number | null
    leakagePolicy?: string
    status?: string
  }
  decisionFeedback?: {
    target?: string
    actionBoundary?: string
    signalopsPolicyHint?: string
    simulation_only?: boolean
    is_real_trade?: boolean
  }
  actionBoundary?: string
  simulation_only?: boolean
  is_real_trade?: boolean
}

export interface QuantCoreVisualDecisionPanel {
  version: 'quant_core_visual_decision_panel_v1' | (string & {})
  status: 'READY' | 'INSUFFICIENT_DATA' | string
  directionProbability: {
    horizonDays?: number | null
    upProbability?: number | null
    downProbability?: number | null
    sidewaysProbability?: number | null
    source?: string
    calibrationStatus?: string
    confidence?: number | null
    actionBoundary?: 'READ_ONLY_NO_PERMISSION_CHANGE' | (string & {})
    simulation_only?: boolean
    is_real_trade?: boolean
  }
  pathPayoffProxy: {
    mfeProxy?: number | null
    maeProxy?: number | null
    riskRewardProxy?: number | null
    expectedPathValueProxy?: number | null
    source?: string
    actionBoundary?: 'READ_ONLY_NO_PERMISSION_CHANGE' | (string & {})
    simulation_only?: boolean
    is_real_trade?: boolean
  }
  riskGradient: {
    status?: string
    downsideRiskScore?: number | null
    maxRiskGradient?: number | null
    riskPolicy?: 'NORMAL' | 'WATCH' | 'THROTTLE' | 'AVOID_NEW_BUY' | string
    actionBoundary?: 'READ_ONLY_NO_PERMISSION_CHANGE' | (string & {})
    simulation_only?: boolean
    is_real_trade?: boolean
  }
  probabilityOddsMatrix: {
    upProbability?: number | null
    riskRewardProxy?: number | null
    expectedPathValueProxy?: number | null
    zone?: 'PRIORITY' | 'WATCH' | 'FILTER' | 'INSUFFICIENT_DATA' | string
    xAxis?: string
    yAxis?: string
    actionBoundary?: 'READ_ONLY_NO_PERMISSION_CHANGE' | (string & {})
    simulation_only?: boolean
    is_real_trade?: boolean
  }
  actionBoundary: 'READ_ONLY_NO_PERMISSION_CHANGE' | (string & {})
  simulation_only?: boolean
  is_real_trade?: boolean
}

export interface QuantCoreInterpretation {
  version: 'quant_core_interpretation_v1' | (string & {})
  status: 'PASS' | 'WARN' | 'REVIEW_ONLY' | 'SKIPPED' | string
  overallScore: number
  overallBias: 'BULLISH' | 'BEARISH' | 'SIDEWAYS' | 'MIXED' | 'UNKNOWN' | (string & {})
  confidence: number
  summary: string
  weights: Record<string, number>
  dimensions: QuantCoreInterpretationDimension[]
  conflicts: QuantCoreInterpretationConflict[]
  riskFlags: string[]
  weightAdjusted: boolean
  weightAdjustmentReasons: string[]
  actionBoundary: 'READ_ONLY_NO_PERMISSION_CHANGE' | (string & {})
  quantEngineMode?: QuantEngineMode | (string & {})
  pathRiskFilter?: QuantCorePathRiskFilter | null
  futureTrendProbability?: QuantCoreFutureTrendProbability | null
  visualDecisionPanel?: QuantCoreVisualDecisionPanel | null
}

export interface QuantCoreResult {
  agent?: 'quant_core' | string
  status?: 'PASS' | 'WARN' | 'REVIEW_ONLY' | 'SKIPPED' | string
  actionBoundary: 'READ_ONLY_NO_PERMISSION_CHANGE' | (string & {})
  evidenceUsage: 'simulation_only' | (string & {})
  evidenceStrength: 'LOW' | 'MEDIUM' | 'PENDING' | (string & {})
  simulation_only: boolean
  is_real_trade: boolean
  strongConclusionAllowed: boolean
  marketTechnical?: MarketTechnicalResult | null
  mfeMaeResearch?: BottomResearchResult | null
  bottomResearch?: BottomResearchResult | null
  factorSlicing?: FactorSlicingResult | null
  factorEngine?: Record<string, any>
  calculationAuthority?: Record<string, any>
  quantEngine?: QuantEngineMetadata | Record<string, any> | null
  qiam?: QIAMResult | Record<string, any> | null
  scenario?: Record<string, any>
  coreInterpretation?: QuantCoreInterpretation | null
  legacyOutputs?: Record<string, AgentResult>
  legacyAgentOutputs?: Record<string, any>
  warnings?: string[]
  missingData?: string[]
  provenance?: Record<string, any>
}

export interface FactorSlicingResult {
  mode: 'LITE' | 'AUTO' | 'DEEP'
  factors: Array<{
    name: string
    weight: number
    contribution: number
    confidence: number
  }>
  factorClusters: string[]
  regimeClassification: string
  factorStability: number
  missingFactorData: string[]
  factorDataSource?: string
  quantEngineMode?: QuantEngineMode | (string & {})
  parameterProfile?: Record<string, any>
  provenance?: Record<string, any>
}

export interface ChipKBResult {
  currentPool: 'A' | 'B' | 'C' | 'D' | 'E'
  suggestedPool: 'A' | 'B' | 'C' | 'D' | 'E'
  migrationDirection: 'UPGRADE' | 'DOWNGRADE' | 'STABLE'
  hitRiskPatches: string[]
  hitPositivePatches: string[]
  dataConfidenceLevel: number
  coreMissingData: string[]
  signalOpsMappingStatus: 'MAPPED' | 'PENDING' | 'FAILED'
  triggerConditions: string[]
  invalidationConditions: string[]
  reviewCycle: number
}

export interface QIAMResult {
  calculationMode: 'STANDARD' | 'CONSERVATIVE' | 'AGGRESSIVE'
  quantEngineMode?: QuantEngineMode | (string & {})
  parameterProfile?: Record<string, any>
  dvgPermission: boolean
  rawBuySuitability: 'FAVORABLE' | 'NEUTRAL' | 'REVIEW_ONLY' | 'BLOCK_BUY'
  discountFactor: number
  finalBuySuitability: 'FAVORABLE' | 'NEUTRAL' | 'REVIEW_ONLY' | 'BLOCK_BUY'
  probabilityBandUp: number
  probabilityBandSideways: number
  probabilityBandDown: number
  probabilitySource?: 'MODEL_OUTPUT' | 'RULE_DERIVED' | (string & {})
  expectedPayoffQuality: number
  regimeFit: number
  momentumQuality: number
  volatilityCondition: number
  liquidityAdjustedSignal: number
  modelConfidenceRaw: number
  modelConfidenceFinal: number
  overfitRisk: number
  distributionDrift: number
  decisionEffect: number
  missingData: string[]
  ignoredMissingData?: string[]
  downgradeReasons: string[]
  remediationItems?: QiamRemediationItem[]
  bottomResearchAdjustment?: BottomResearchAdjustment
  mfeMaePathResearchAdjustment?: BottomResearchAdjustment
  llmOutput?: Record<string, unknown>
  scoreRepairSource?: string
}

export interface BottomResearchAdjustment {
  observed?: boolean
  applied?: boolean
  direction?: 'UP' | 'DOWN' | 'NONE' | 'CONFLICT' | string
  reason?: string
  beforeFinalBuySuitability?: string
  afterFinalBuySuitability?: string
  maxStep?: number
  policy?: string
  canCreateTradeAction?: boolean
  evidence?: Record<string, any>
  blockedReasons?: string[]
}

export interface QiamRemediationItem {
  reason: string
  category: 'QIAM_INPUT' | 'DVG' | 'TECHNICAL_KLINE' | 'DATA_GAP' | (string & {})
  action: string
  verification: string
  severity: 'BLOCKING' | 'WARN' | 'INFO' | (string & {})
}

export interface QuantEngineMetadata {
  mode: QuantEngineMode | (string & {})
  label?: string
  horizon?: string
  parameterProfile?: {
    factorWeights?: Record<string, number>
    requiredFactorNames?: string[]
    discountsHighFrequencyMissingData?: boolean
    highFrequencyMissingMarkers?: string[]
    [key: string]: any
  }
  ignoredMissingData?: string[]
}

export interface MfeMaeConditionalQuantileCoverage {
  q50?: { coverage?: number | null; thresholdMean?: number | null; testCount?: number | null }
  q80?: { coverage?: number | null; thresholdMean?: number | null; testCount?: number | null }
  q90?: { coverage?: number | null; thresholdMean?: number | null; testCount?: number | null }
  q50Coverage?: number | null
  q80Coverage?: number | null
  q90Coverage?: number | null
  evaluatedTestCount?: number | null
  [key: string]: any
}

export interface MfeMaeConditionalQuantileEvaluation {
  version?: string
  status?: string
  method?: string
  conditioning?: Record<string, any>
  rankIcMode?: string
  leakagePolicy?: string
  actionBoundary?: string
  labelStatus?: string
  simulation_only?: boolean
  is_real_trade?: boolean
  folds?: Array<Record<string, any>>
  targetCoverage?: {
    mfe?: MfeMaeConditionalQuantileCoverage
    maeAbs?: MfeMaeConditionalQuantileCoverage
    riskReward?: MfeMaeConditionalQuantileCoverage
    evaluatedTestCount?: number | null
    [key: string]: any
  }
  rankIc?: Record<string, number | null | undefined>
  sampleQuality?: Record<string, any>
  [key: string]: any
}

export interface BottomResearchResult {
  agent?: string
  legacyAgent?: string
  researchType?: 'MFE_MAE_PATH_RESEARCH' | string
  status?: string
  modelVersion?: string
  actionBoundary?: 'RESEARCH_ONLY_NO_PERMISSION_CHANGE' | string
  labelStatus?: 'UNLABELED_NOWCAST' | 'INSUFFICIENT_DATA' | string
  sampleQuality?: Record<string, any>
  leakagePolicy?: string
  simulation_only?: boolean
  is_real_trade?: boolean
  mfeFavorableProbability?: number | null
  maeBreachProbability?: number | null
  mfeProxy?: number | null
  maeProxy?: number | null
  riskRewardProxy?: number | null
  downsideRiskScore?: number | null
  riskPolicy?: string
  marketProfile?: Record<string, any>
  mfeMaeFormulaConfig?: Record<string, any>
  mfeMaePathModel?: Record<string, any>
  bottomRepairProbability?: number | null
  breakdownRiskProbability?: number | null
  regimeState?: string
  riemannianFeatures?: {
    covWindow?: number
    airmDistance?: number
    logEuclideanDistance?: number
    tangentSpaceVector?: number[]
    tangentNorm?: number
    currentCovariance?: number[][]
    stateCenterCovariance?: number[][]
    featureBasis?: string[]
    [key: string]: any
  }
  modelDiagnostics?: {
    status?: string
    modelVersion?: string
    featureVersion?: string
    sampleCount?: number
    leakagePolicy?: string
    evidenceGrade?: string
    walkForward?: Record<string, any>
    bottomRepairModel?: Record<string, any>
    breakdownRiskModel?: Record<string, any>
    mfeMaePathRiskEvaluation?: Record<string, any>
    conditionalQuantileEvaluation?: MfeMaeConditionalQuantileEvaluation
    pathQuantiles?: Record<string, any>
    marketProfile?: Record<string, any>
    [key: string]: any
  }
  positionEnvelope?: {
    maxResearchPositionPct?: number
    suggestedResearchPositionPct?: number
    policy?: string
    constraints?: string[]
    simulation_only?: boolean
    is_real_trade?: boolean
    [key: string]: any
  }
  missingData?: string[]
  warnings?: string[]
  provenance?: Record<string, any>
  probabilitySeries?: Array<{
    tradeDate: string
    date?: string
    horizonDays?: number
    mfeLabel?: number | null
    maeLabel?: number | null
    maeAbsLabel?: number | null
    riskRewardLabel?: number | null
    mfeFavorableProbability?: number | null
    maeBreachProbability?: number | null
    predictionMfeFavorableProbability?: number | null
    predictionMaeBreachProbability?: number | null
    mfeProxy?: number | null
    maeProxy?: number | null
    riskRewardProxy?: number | null
    riskPolicy?: string
    bottomRepairProbability?: number | null
    breakdownRiskProbability?: number | null
    bottomLabel?: number
    breakdownLabel?: number
    regimeState?: string
    predictionUpProbability?: number | null
    predictionDownProbability?: number | null
    actualForwardReturn?: number | null
    actualUpLabel?: number | null
    actualDownLabel?: number | null
    actualDirection?: string
    labelWindowStart?: string
    labelWindowEnd?: string
  }>
  currentPrediction?: {
    tradeDate: string
    mfeFavorableProbability?: number | null
    maeBreachProbability?: number | null
    mfeProxy?: number | null
    maeProxy?: number | null
    riskRewardProxy?: number | null
    downsideRiskScore?: number | null
    riskPolicy?: string
    bottomRepairProbability?: number | null
    breakdownRiskProbability?: number | null
    regimeState?: string
    labelStatus?: 'UNLABELED_NOWCAST' | string
    horizonDays?: number
    simulation_only?: boolean
    is_real_trade?: boolean
  }
  horizonProbabilitySeries?: Array<{
    horizonDays: number
    series: Array<{
      date: string
      repairProb?: number | null
      breakdownRisk?: number | null
      predictionRepairProb?: number | null
      predictionBreakdownRisk?: number | null
      predictionMfeFavorableProbability?: number | null
      predictionMaeBreachProbability?: number | null
      mfeLabel?: number | null
      maeAbsLabel?: number | null
      riskRewardLabel?: number | null
      mfeProxy?: number | null
      maeProxy?: number | null
      riskRewardProxy?: number | null
      riskPolicy?: string
      bottomLabel?: number
      breakdownLabel?: number
      regimeState?: string
      predictionUpProbability?: number | null
      predictionDownProbability?: number | null
      actualForwardReturn?: number | null
      actualUpLabel?: number | null
      actualDownLabel?: number | null
      actualDirection?: string
      labelStatus?: string
      labelWindowStart?: string
      labelWindowEnd?: string
      horizonDays?: number
      simulation_only?: boolean
      is_real_trade?: boolean
    }>
  }>
  horizonForecasts?: Array<{
    horizonDays: number
    status?: string
    mfeFavorableProbability?: number | null
    maeBreachProbability?: number | null
    mfeProxy?: number | null
    maeProxy?: number | null
    riskRewardProxy?: number | null
    downsideRiskScore?: number | null
    riskPolicy?: string
    bottomRepairProbability?: number | null
    breakdownRiskProbability?: number | null
    trendProbabilities?: {
      up?: number | null
      sideways?: number | null
      down?: number | null
    }
    trendBias?: string
    confidence?: number
    sampleCount?: number
    evidenceGrade?: string
    regimeState?: string
    currentPrediction?: BottomResearchResult['currentPrediction']
    pathQuantiles?: Record<string, any>
    riskCurve?: Array<Record<string, any>>
    marketProfile?: Record<string, any>
    modelDiagnostics?: Record<string, any>
  }>
  trendSynthesis?: {
    primaryHorizonDays?: number
    primaryTrendBias?: string
    mainConclusion?: string
    horizonAlignment?: string
    evidenceConflict?: boolean
    keyDrivers?: string[]
    riskFlags?: string[]
    simulation_only?: boolean
    is_real_trade?: boolean
    [key: string]: any
  }
  qiamAdjustmentPreview?: BottomResearchAdjustment
  config?: Record<string, any>
}

export interface PortfolioResult {
  currentTotalPosition: number
  singleStockPosition: number
  industryExposure: Record<string, number>
  styleExposure: Record<string, number>
  industrySoftLimit?: number
  themeConcentration: number
  sameRiskFactorConcentration: number
  maxDrawdownConstraint: number
  singleStockPositionCap: number
  allowAddPosition: boolean
  allowHeavyPosition: boolean
  restrictionReasons: string[]
  portfolioCoverage?: 'HOLDINGS_CONNECTED' | 'USER_INPUT_ONLY' | (string & {})
  snapshotId?: string
  snapshotUpdatedAt?: string
  holdings?: Array<Record<string, any>>
  evidenceUsage?: 'supporting_only' | (string & {})
  evidenceStrength?: 'MEDIUM' | 'LOW' | 'MISSING' | 'PENDING' | (string & {})
  simulationOnly?: boolean
  isRealTrade?: boolean
  strongConclusionAllowed?: boolean
  provenance?: Record<string, any>
}

export interface ExecutionResult {
  allowedActions: string[]
  prohibitedActions: string[]
  executionReachability: 'REACHABLE' | 'CONDITIONALLY_REACHABLE' | 'NOT_REACHABLE'
  batchPaths: string[]
  slippageLimit: number
  participationLimit: number
  manualConfirmationItems: string[]
  forbiddenActions: string[]
}

export interface SignalOpsResult {
  signalStatus: SignalOpsStatus
  riskPassed: boolean
  dvgPassed: boolean
  qiamPassed: boolean
  executionReachable: boolean
  triggerConditions: string[]
  invalidationConditions: string[]
  reviewFields: string[]
  blockedReason: string
  auditId: string
}

export interface PaperTradingResult {
  status: 'PENDING' | 'ACTIVE' | 'WARN' | 'SKIPPED' | 'COMPLETED' | 'FAILED' | (string & {})
  observationPeriod: number
  entryAssumptions: string[]
  invalidationConditions: string[]
  simulatedProfit: number
  maxDrawdown: number
  triggeredInvalidation: boolean
  writtenToLedger: boolean
  triggeredErrorLedger: boolean
  simulation_only?: boolean
  is_real_trade?: boolean
  allowed_order_namespace?: 'SIM_*' | (string & {})
  orderNamespace?: 'SIM_*' | (string & {})
  order_namespace?: 'SIM_*' | (string & {})
  action?: `SIM_${string}` | (string & {})
  paper_action?: `SIM_${string}` | (string & {})
  latest_action?: `SIM_${string}` | (string & {})
}

export interface ReviewLedgerItem {
  runId: string
  signalId: string
  title?: string
  status?: string
  timestamp?: string
  node?: string
  description?: string
  reviewer?: string
  errorType: string
  errorNode: string
  errorReason: string
  isRepeatedError: boolean
  patchCandidate?: string
  patchStatus: 'DRAFT' | 'CANDIDATE' | 'REVIEWING' | 'ACCEPTED' | 'REJECTED' | 'ARCHIVED'
  auditId: string
}

export interface AuditLogEvent {
  timestamp: string
  runId: string
  node: string
  eventType: AuditEventType
  message: string
  statusBefore: NodeStatus
  statusAfter: NodeStatus
  inputHash: string
  outputHash: string
  auditId: string
}

export interface RunStreamEvent {
  event_type: string
  run_id?: string
  node_id?: string
  message?: string
  payload?: Record<string, any>
  audit_id?: string
  timestamp?: string
}

export interface FinalWriterResult {
  mode: FinalWriterMode
  llmFailed?: boolean
  reportId?: string
  sections: Array<{
    title: string
    content: string
    riskLevel: 'LOW' | 'MEDIUM' | 'HIGH'
    requiresConfirmation: boolean
  }>
  finalAction?: FinalAction
  humanConfirmationRequired?: boolean
  auditId?: string
}

export interface FinalReportAsset {
  report_id: string
  run_id: string
  audit_id: string
  symbol: string
  stock_name: string
  task_type: string
  data_mode: string
  final_action: string
  final_writer_mode: string
  human_confirmation_required: boolean
  summary: string
  sections: FinalWriterResult['sections']
  source_snapshot: Record<string, any>
  metadata: Record<string, any>
  created_at: string
  updated_at: string
}

export interface FinalReportAssetLink {
  reportId: string
  auditId: string
  updatedAt: string
}

export interface PermissionItem {
  capability: CapabilityKey
  state: PermissionState
  sourceNode: string
  reason: string
  requiresConfirmation: boolean
}

export interface OrchestratorStep {
  stepId: string
  nodeId: string
  status: 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'SKIPPED'
  startTime?: string
  endTime?: string
  duration?: number
  errorMessage?: string
}

export interface ScenarioConfig {
  id: string
  name: string
  description: string
  riskLevel: 'LOW' | 'MEDIUM' | 'HIGH'
  defaultRunMode: RunMode
}

export interface KillSwitch {
  active: boolean
  level: KillSwitchLevel
  triggerNode: string
  triggerRule: string
  blockedPaths: string[]
  allowedPaths: string[]
  finalWriterMode: FinalWriterMode
  auditId: string
}

export interface BackendHealth {
  status: 'ok' | 'error'
  version: string
  mode: 'mock' | 'api'
  tradingEnabled: boolean
  autoOrderEnabled: boolean
  lastCheck: string
  latency: number
}

export type StartupPhase = 'BOOTING' | 'CORE_READY' | 'WARMING' | 'READY' | 'DEGRADED'

export interface StartupComponentStatus {
  name: string
  tier: 'core' | 'optional' | string
  status: 'PENDING' | 'RUNNING' | 'OK' | 'ERROR' | 'SKIPPED' | string
  required?: boolean
  startedAt?: string
  finishedAt?: string
  elapsedMs?: number
  error?: string
  details?: Record<string, unknown>
}

export interface StartupStatus {
  phase: StartupPhase
  coreReady: boolean
  ready: boolean
  degradedComponents: string[]
  components: StartupComponentStatus[]
}

export interface ConfigProfile {
  profile_id: string
  profileId?: string
  version: number
  locked_guardrails: Record<string, any>
  lockedGuardrails?: Record<string, any>
  safe_runtime_config: Record<string, any>
  safeRuntimeConfig?: Record<string, any>
  review_required_config: Record<string, any>
  reviewRequiredConfig?: Record<string, any>
  sandbox_config: Record<string, any>
  sandboxConfig?: Record<string, any>
  created_at: string
  createdAt?: string
  updated_at: string
  updatedAt?: string
}

export interface ConfigSchemaItem {
  key: string
  label: string
  type: 'number' | 'boolean' | 'string' | 'select'
  layer: 'LOCKED' | 'SAFE_RUNTIME' | 'REVIEW_REQUIRED' | 'SANDBOX'
  min?: number
  max?: number
  options?: string[]
  default: string | number | boolean | null | undefined
  current: string | number | boolean | null | undefined
  editable: boolean
  direction: 'CONSERVATIVE_ONLY' | 'ANY'
  description: string
}

export interface ConfigDraft {
  draft_id?: string
  draftId?: string
  status: 'PENDING' | 'PENDING_REVIEW' | 'APPROVED' | 'APPLIED' | 'REJECTED'
  changes: Record<string, any>
  reason: string
  policy_check?: PolicyCheckResult
  policyCheck?: {
    passed: boolean
    level?: 'SAFE' | 'REVIEW_REQUIRED' | 'BLOCKED'
    warnings: string[]
    blocked_reasons?: string[]
    blockedReasons: string[]
    effective_changes?: Record<string, any>
    effectiveChanges: Record<string, any>
  }
  audit_id?: string
  auditId?: string
  created_at?: string
  createdAt?: string
}

export interface PolicyCheckResult {
  passed: boolean
  level: 'SAFE' | 'REVIEW_REQUIRED' | 'BLOCKED'
  warnings: string[]
  blocked_reasons?: string[]
  blockedReasons?: string[]
  effective_changes?: Record<string, any>
  effectiveChanges?: Record<string, any>
}

export type KnowledgeStatus = 'PENDING_REVIEW' | 'ACTIVE' | 'REJECTED' | 'ARCHIVED' | (string & {})
export type KnowledgeConfidence = 'HIGH' | 'MEDIUM' | 'LOW' | (string & {})
export type KnowledgeEvidenceUsage = 'supporting_only' | (string & {})
export type KnowledgeEvidenceStrength = 'MEDIUM' | 'LOW' | 'MISSING' | 'PENDING' | (string & {})

export interface KnowledgeItem {
  item_id: string
  version: number
  status: KnowledgeStatus
  category: string
  source_run_id?: string | null
  source_audit_id?: string | null
  source_run_verified: boolean
  title: string
  thesis: string
  evidence: string[]
  decision_impact: string
  guardrail_notes: string[]
  tags: string[]
  confidence: KnowledgeConfidence
  evidence_usage: KnowledgeEvidenceUsage
  evidence_strength: KnowledgeEvidenceStrength
  simulation_only: boolean
  is_real_trade: boolean
  strong_conclusion_allowed: boolean
  created_at: string
  updated_at: string
  reviewed_at?: string | null
  reviewer?: string | null
  review_note?: string | null
}

export interface KnowledgeSummary {
  total: number
  active_count: number
  pending_count: number
  rejected_count: number
  archived_count: number
  latest_version: number
  categories: Record<string, number>
  updated_at: string
}

export interface ActiveKnowledgeContextItem {
  itemId: string
  version: number
  category: string
  title: string
  thesis: string
  decisionImpact: string
  tags: string[]
  confidence: KnowledgeConfidence
  evidenceUsage: KnowledgeEvidenceUsage
  evidenceStrength: KnowledgeEvidenceStrength
  simulationOnly: boolean
  isRealTrade: boolean
  strongConclusionAllowed: boolean
}

export interface DataFingerprint {
  namespace: string
  fingerprint: string
  size_bytes: number
  canonical_keys: string[]
  created_at: string
}

export interface DataQualityScore {
  score: number
  level: 'HIGH' | 'MEDIUM' | 'LOW' | (string & {})
  issues: string[]
  strengths: string[]
  source_coverage: string
  missing_critical_fields: string[]
}

export interface RunCompressionSummary {
  run_id: string
  symbol: string
  stock_name: string
  status: string
  run_mode: string
  final_action: string
  data_fingerprint: DataFingerprint
  quality: DataQualityScore
  keep_fields: string[]
  key_metrics: Record<string, any>
  decision_summary: string
  guardrail_summary: string[]
  evidence_summary: string[]
  agent_summary: Record<string, any>
  token_budget_estimate: number
  retention_action: string
  retention_reason: string
  created_at: string
  compression_persisted?: boolean
  artifact_path?: string | null
  compressed_at?: string | null
}

export interface KnowledgeDistillationGroup {
  group_id: string
  category: string
  fingerprint: string
  item_ids: string[]
  representative_item_id: string
  duplicate_count: number
  shared_tags: string[]
  suggested_action: string
  reason: string
}

export interface CompressionOverview {
  total_runs: number
  summarized_runs: number
  average_quality_score: number
  high_quality_count: number
  medium_quality_count: number
  low_quality_count: number
  retention_actions: Record<string, number>
  latest_run_id?: string | null
}

export interface CaseLibraryItem {
  case_id: string
  run_id: string
  audit_id: string
  symbol: string
  stock_name: string
  task_type: string
  run_mode: string
  final_action: string
  final_action_correct: boolean | null
  conclusion_correct: boolean | null
  data_sufficiency: string
  optimism_bias: string
  key_lessons: string[]
  market_context: string
  tags: string[]
  reviewer: string | null
  review_note: string
  review_status: string
  evidence_usage: 'supporting_only' | (string & {})
  evidence_strength: 'MEDIUM' | 'LOW' | 'PENDING' | 'MISSING' | (string & {})
  simulation_only: boolean
  is_real_trade: boolean
  strong_conclusion_allowed: boolean
  created_at: string
  updated_at: string
}

export interface CaseLibrarySummary {
  total: number
  pending: number
  reviewed: number
  correct_conclusions: number
  accuracy_rate: number
}

export interface ReviewTagItem {
  tag_id: string
  case_id: string
  run_id: string
  tag_type: string
  tag_value: string
  severity: string
  description: string
  node: string | null
  reviewer: string
  created_at: string
}

export interface ReviewTagSummary {
  total: number
  by_type: Record<string, number>
  by_severity: Record<string, number>
}

export interface ErrorLedgerItem {
  entry_id: string
  run_id: string
  audit_id: string
  node: string | null
  error_type: string
  error_reason: string
  repeated_count: number
  patch_required: boolean
  patch_candidate_id: string | null
  attribution: Record<string, any>
  status: string
  evidence_usage: 'review_gate_only' | (string & {})
  evidence_strength: 'LOW' | 'PENDING' | 'MISSING' | (string & {})
  simulation_only: boolean
  is_real_trade: boolean
  strong_conclusion_allowed: boolean
  reported_simulation_only: boolean | null
  reported_is_real_trade: boolean | null
  resolved_at: string | null
  created_at: string
  updated_at: string
}

export interface ErrorLedgerSummary {
  total: number
  open: number
  resolved: number
  by_type: Record<string, number>
  by_node: Record<string, number>
}

export interface KnowledgePatchItem {
  patch_id: string
  source_error_id: string | null
  source_case_id: string | null
  title: string
  reason: string
  affected_modules: string[]
  patch_content: Record<string, any>
  risk_note: string
  rollback_plan: string
  backtest_required: boolean
  backtest_result: Record<string, any>
  approval_status: string
  approved_by: string | null
  approved_at: string | null
  evidence_usage: 'review_gate_only' | (string & {})
  evidence_strength: 'MEDIUM' | 'LOW' | 'MISSING' | 'PENDING' | (string & {})
  simulation_only: boolean
  is_real_trade: boolean
  strong_conclusion_allowed: boolean
  created_at: string
  updated_at: string
}

export interface KnowledgePatchSummary {
  total: number
  candidate: number
  approved: number
  rejected: number
}

export interface StrategyExperimentMetrics {
  win_rate: number
  max_drawdown: number
  misjudge_rate: number
  manual_review_pass_rate: number
  risk_trigger_rate: number
  sample_window: Record<string, any>
}

export interface StrategyExperimentReport {
  experiment_id: string
  hypothesis: string
  strategy_count: number
  baseline_config_id: string
  winner_config_id: string
  sample_window: Record<string, any>
  metrics_by_strategy: Record<string, StrategyExperimentMetrics>
  comparisons: Array<Record<string, any>>
  summary: string
  evidence_usage: 'review_gate_only' | (string & {})
  evidence_strength: 'LOW' | 'MISSING' | 'PENDING' | (string & {})
  simulation_only: boolean
  is_real_trade: boolean
  strong_conclusion_allowed: boolean
  created_at: string
}

export interface EvaluationRunItem {
  eval_id: string
  patch_id: string
  status: string
  total_cases: number
  passed_cases: number
  improved_cases: number
  regressed_cases: number
  unchanged_cases: number
  pass_rate: number
  improvement_rate: number
  elapsed_ms: number
  per_case_results: Array<Record<string, any>>
  summary: string
  strategy_experiment_report?: StrategyExperimentReport | null
  evidence_usage: 'review_gate_only' | (string & {})
  evidence_strength: 'MEDIUM' | 'LOW' | 'MISSING' | 'PENDING' | (string & {})
  simulation_only: boolean
  is_real_trade: boolean
  strong_conclusion_allowed: boolean
  error: string | null
  created_at: string
  updated_at: string
}

export type KnowledgeVersionGovernanceStatus = 'draft' | 'review' | 'active' | 'deprecated' | 'rolled_back' | (string & {})

export type KnowledgeVersionApprovalEvidenceRefType = 'backtest' | 'evaluation' | 'regression_waiver' | 'verdict'

export interface KnowledgeVersionApprovalEvidenceRef {
  source_type: KnowledgeVersionApprovalEvidenceRefType
  source_id: string
  summary?: string
  metrics?: Record<string, unknown>
  evidence_usage?: 'review_gate_only' | (string & {})
  evidence_strength?: 'MEDIUM' | 'LOW' | 'MISSING' | 'PENDING' | 'UNKNOWN' | (string & {})
  simulation_only?: boolean
  is_real_trade?: boolean
  strong_conclusion_allowed?: boolean
}

export interface PostPublishRegressionReport {
  report_id: string
  version_id?: string
  version_number?: number
  status: string
  trigger?: string
  performed_by?: string
  generated_at?: string
  representative_case_count?: number
  active_patch_count?: number
  total_checks?: number
  improved_cases?: number
  regressed_cases?: number
  unchanged_cases?: number
  review_required_cases?: number
  improvement_rate?: number
  regression_rate?: number
  review_required_rate?: number
  affected_modules?: string[]
  warnings?: string[]
  evidence_usage: 'review_gate_only' | (string & {})
  evidence_strength: 'LOW' | 'MISSING' | 'PENDING' | (string & {})
  simulation_only: boolean
  is_real_trade: boolean
  strong_conclusion_allowed: boolean
  case_set_quality?: {
    status?: string
    reviewed_case_count?: number
    unique_symbol_count?: number
    symbols?: string[]
    incorrect_case_count?: number
    insufficient_data_case_count?: number
    optimism_bias_case_count?: number
    affected_modules?: string[]
    covered_affected_modules?: string[]
    missing_affected_modules?: string[]
    warnings?: string[]
  }
  case_set_quality_policy?: {
    policy_id?: string
    mode?: string
    action?: string
    blocking?: boolean
    override_required?: boolean
    minimum_reviewed_cases?: number
    minimum_unique_symbols?: number
    requires_failure_or_boundary_case?: boolean
    requires_affected_module_coverage?: boolean
    reason?: string
    warnings?: string[]
    remediation?: {
      status?: string
      owner?: string
      required_actions?: string[]
      next_actions?: string[]
      required_reviewed_case_delta?: number
      required_unique_symbol_delta?: number
      missing_affected_modules?: string[]
      target_case_mix?: {
        minimum_reviewed_cases?: number
        minimum_unique_symbols?: number
        requires_failure_or_boundary_case?: boolean
        requires_affected_module_coverage?: boolean
      }
    }
  }
  knowledge_impact?: {
    policy_id?: string
    mode?: string
    status?: string
    source_status?: string
    risk_level?: string
    action?: string
    strongest_signal?: string
    requires_human_review?: boolean
    auto_blocks_promotion?: boolean
    evidence_basis?: string
    affected_module_count?: number
    top_affected_modules?: string[]
    active_patch_count?: number
    representative_case_count?: number
    total_checks?: number
    improved_cases?: number
    regressed_cases?: number
    review_required_cases?: number
    net_improvement_cases?: number
  }
  quality_warnings?: string[]
  per_patch?: Array<Record<string, any>>
  summary?: string
}

export interface KnowledgeVersionItem {
  version_id: string
  version_number: number
  version_label: string
  snapshot: Record<string, any>
  active_patches: string[]
  active_rules: string[]
  patch_delta: Record<string, any>
  source_patch_id: string | null
  source_run_id?: string | null
  source_case_id?: string | null
  source_evaluation_id?: string | null
  source_verdict_id?: string | null
  scope?: string
  risk_boundary?: string
  approval_record?: Record<string, any> & {
    evidence_refs?: KnowledgeVersionApprovalEvidenceRef[]
    regression_waiver?: {
      policy_id?: string
      status?: string
      approval_id?: string
      reason?: string
      approved_by?: string
      approver_role?: string
      approved_at?: string
      evaluation_id?: string
      regressed_cases?: number
      mode?: string
    }
  }
  rollback_impact?: Record<string, any>
  post_publish_regression?: PostPublishRegressionReport | null
  status?: KnowledgeVersionGovernanceStatus
  evidence_usage: 'review_gate_only' | (string & {})
  evidence_strength: 'MEDIUM' | 'LOW' | 'MISSING' | 'PENDING' | (string & {})
  simulation_only: boolean
  is_real_trade: boolean
  strong_conclusion_allowed: boolean
  created_by: string
  description: string
  created_at: string
}

export interface CreateKnowledgeVersionDraftPayload {
  description?: string
  scope?: string
  risk_boundary?: string
  approval_record?: Record<string, unknown> & {
    evidence_refs?: never
  }
  rollback_impact?: Record<string, unknown>
}

export interface VersionDiffResult {
  version_a: Record<string, any>
  version_b: Record<string, any>
  patches_added: string[]
  patches_removed: string[]
  rules_added: string[]
  rules_removed: string[]
  patch_count_diff: number
}

export interface RollbackResult {
  rollback_target: KnowledgeVersionItem
  new_version: KnowledgeVersionItem
  restored_patches: number
}

export interface DashboardSummary {
  schema: 'analysis_dashboard_summary_v1' | (string & {})
  generatedAt: string
  decisionState: string
  headline: string
  tradeBoundary: {
    simulationOnly: boolean
    isRealTrade: boolean
    humanConfirmationRequired: boolean
  }
  metrics: {
    evidenceScore: number
    sourceReadyCount: number
    sourceTotalCount: number
    activeAgentCount: number
    blockedAgentCount: number
    currentPositionPct: number
    singleStockCapPct: number
    capRemainingPct: number
  }
  blockers: string[]
  warnings: string[]
  nextReview: string[]
}

export interface AnalysisRun {
  runId: string
  runMode: RunMode
  environment: RuntimeEnvironment
  dataMode?: 'MOCK' | 'LIVE' | 'MIXED' | 'FALLBACK' | 'UNAVAILABLE'
  stockCode: string
  // Display-only label. API-created research run shells may return an empty string;
  // use runId and stockCode for identity and validity checks.
  stockName: string
  taskType: string
  userPosition: {
    currentPositionRatio: number
    currentShares?: number
    costPrice: number
    sellableBottomWarehouse: boolean
    plannedPeriod: number
    maxAcceptableDrawdown: number
  }
  nodes: AgentNode[]
  guardrailHub?: GuardrailHubResult
  dvg: DVGResult
  risk: RiskResult
  atrade: ATradeResult
  market: MarketResult
  factorSlicing: FactorSlicingResult
  quantEngine?: QuantEngineMetadata
  quantCore?: QuantCoreResult | null
  bottomResearch?: BottomResearchResult | null
  chipKb: ChipKBResult
  qiam: QIAMResult
  portfolio: PortfolioResult
  execution: ExecutionResult
  signalOps: SignalOpsResult
  paperTrading: PaperTradingResult
  marketData?: Record<string, any>
  dataReliabilityEngine?: Record<string, any>
  marketTechnical?: MarketTechnicalResult | null
  technicalKline?: Record<string, any>
  mfeMaeResearch?: BottomResearchResult | null
  auxiliaryData?: Record<string, any>
  dataSources?: DataSourcesReport
  dashboardSummary?: DashboardSummary
  agentRuntime?: AgentRuntimeSummary
  knowledgeContext?: ActiveKnowledgeContextItem[]
  compressedSummary?: RunCompressionSummary
  agentModuleResults?: Record<string, any>
  agentResults?: AgentResult[]
  dagEvents?: DagEvent[]
  skippedNodes?: SkippedNode[]
  tokenUsage?: TokenUsageSummary
  debateArtifacts?: DebateArtifacts
  orchestratorPlan?: Record<string, any>
  finalContext?: Record<string, any>
  agentOutputs?: Record<string, any>
  llmTrace?: LLMTraceItem[]
  finalAction: FinalAction
  killSwitch: KillSwitch
  auditLog: AuditLogEvent[]
  streamEvents?: RunStreamEvent[]
  reviewLedger?: ReviewLedgerItem[]
  finalWriter?: FinalWriterResult
  finalReportAsset?: FinalReportAssetLink
  rdResearch?: Record<string, any>
  job?: AnalysisJob
  retry?: Record<string, any>
  cancelRequested?: boolean
  createdAt: string
  updatedAt: string
  status: AnalysisRunStatus
  failReason?: string
  failureCategory?: string
  recovery?: Record<string, any>
  recoveryEvents?: Array<Record<string, any>>
}

export interface AnalysisJob {
  job_id: string
  run_id: string
  status: AnalysisJobStatus | (string & {})
  attempt: number
  max_attempts?: number
  queue_name?: string
  priority?: number
  concurrency_group?: string
  concurrency_limit?: number
  worker_id?: string
  worker_heartbeat_at?: string
  lease_expires_at?: string
  lease_status?: 'ACTIVE' | 'EXPIRED' | 'UNCLAIMED' | 'UNLEASED' | 'RELEASED' | 'UNKNOWN' | (string & {})
  lease_seconds?: number
  created_at: string
  updated_at: string
  queued_at?: string
  started_at?: string
  finished_at?: string
  cancel_requested_at?: string
  operator?: string
  last_operator?: string
  last_error?: string
  failed_node_id?: string
  retry_from_node_id?: string
  resume_from_node_id?: string
  retry_of_job_id?: string
  same_input_retry?: boolean
  stale_reason?: string
  history?: AnalysisJobHistoryEvent[]
}

export interface AnalysisJobSummary {
  generated_at: string
  total_count: number
  filtered_count: number
  counts_by_status: Record<string, number>
  statuses: string[]
  limit: number
  offset: number
  has_more: boolean
  source?: string
  external_queue_status?: AnalysisJobExternalQueueStatus
}

export interface AnalysisJobExternalQueueStatus {
  schema: 'analysis_job_external_queue_status_v1' | (string & {})
  checked: boolean
  reported: boolean
  status: 'NOT_CONFIGURED' | 'NOT_REPORTED' | 'READY' | 'DEGRADED' | 'FAILED' | 'UNKNOWN' | 'INVALID' | (string & {})
  sidecar_file?: string
  reported_at?: string
  source?: string
  provider?: string
  queue_name?: string
  lease_backend?: string
  claim_backend?: string
  claim_status?: string
  idempotency_scope?: string
  audit_stream?: string
  dead_letter_queue?: string
  dead_letter_count?: number
  visibility_timeout_seconds?: number | null
  lease_renewal_status?: string
  worker_pool?: string
  active_workers?: number
  pending_jobs?: number
  running_jobs?: number
  oldest_pending_age_seconds?: number | null
  message?: string
  deployment_reported?: boolean
  local_queue_mode?: string
  issues?: string[]
}

export interface AnalysisJobAttempt {
  job_id: string
  run_id: string
  status: AnalysisJobStatus | (string & {})
  attempt: number
  queue_name?: string
  concurrency_group?: string
  worker_id?: string
  worker_heartbeat_at?: string
  lease_expires_at?: string
  lease_status?: 'ACTIVE' | 'EXPIRED' | 'UNCLAIMED' | 'UNLEASED' | 'RELEASED' | 'UNKNOWN' | (string & {})
  lease_seconds?: number
  created_at: string
  updated_at: string
  queued_at?: string
  started_at?: string
  finished_at?: string
  operator?: string
  last_operator?: string
  last_error?: string
  failed_node_id?: string
  retry_from_node_id?: string
  resume_from_node_id?: string
  retry_of_job_id?: string
  same_input_retry?: boolean
  stale_reason?: string
  history?: AnalysisJobHistoryEvent[]
}

export interface AnalysisJobHistoryEvent {
  event: string
  at: string
  attempt: number
  failed_node_id?: string
  retry_from_node_id?: string
  operator?: string
}

export interface FallbackStep {
  adapterId: string
  provider: string
  attemptAt: string
  success: boolean
  error: string
  latencyMs: number
}

export interface DataSourceStatus {
  name: string
  provider: string
  icon: string
  status: 'READY' | 'FAILED' | 'NOT_CONFIGURED'
  detail: string
  fetchedAt?: string
  available: boolean
  error?: string
  category: string
  degradationReason?: string
  fallbackChain?: FallbackStep[]
  degradationChain?: FallbackStep[]
  freshness?: string
  confidence?: number
  adapterId?: string
  dataMode?: string
}

export interface DataSourcesReport {
  sources: Record<string, DataSourceStatus>
  summary: {
    availableCount: number
    totalCount: number
    availableRatio: string
    overallStatus: 'READY' | 'PARTIAL' | 'ALL_MOCK'
    overallDataMode?: string
    generatedAt: string
  }
}

export interface DataSourceHealth {
  adapterId: string
  provider: string
  label: string
  capabilities: string[]
  configured?: boolean
  healthy: boolean
  upstreamHealthy?: boolean
  liveDataUsable?: boolean
  fallbackUsed?: boolean
  lastError?: string
  freshness?: string
  lastCheckAt: string
  latencyAvgMs: number
  message: string
  enabled: boolean
  installed: boolean
  healthCheckMode?: string
}

export interface MarketDataAdapterConfig {
  adapter_id: string
  provider: string
  label: string
  enabled: boolean
  priority: number
  timeout_seconds: number
  requires_token: boolean
  capabilities?: string[]
  note: string
}

export interface UpdateMarketDataAdapterConfigPayload {
  enabled?: boolean
  priority?: number
  timeout_seconds?: number
}

export interface MarketDataStatusCategory {
  [adapterId: string]: DataSourceHealth
}

export interface MarketDataStatusMatrix {
  categories: Record<string, MarketDataStatusCategory>
  generatedAt: string
}

export interface AnalysisRunSummary {
  runId: string
  stockCode: string
  stockName?: string
  taskType: string
  runMode: RunMode
  status: AnalysisRunStatus
  failReason?: string
  failureCategory?: string
  recovery?: Record<string, any>
  job?: AnalysisJob
  finalAction: FinalAction
  createdAt: string
  updatedAt: string
  compressed?: boolean
  compressedAt?: string | null
  compressedArtifactPath?: string | null
}

export type LLMProvider = 'openai' | 'openai_compatible' | 'anthropic' | 'gemini' | 'local' | (string & {})
export type RuntimeProfileHealthStatus = 'READY' | 'CONFIGURED' | 'FAILED' | 'INCOMPLETE' | 'DISABLED' | 'BLOCKED' | (string & {})

export interface RuntimeBaseUrlSecurity {
  status?: 'TRUSTED' | 'LOCAL' | 'CUSTOM' | 'MISSING' | 'BLOCKED' | (string & {})
  allowed?: boolean
  strict_mode_required?: boolean
  message?: string
  code?: string
  host?: string
  reason?: string
  allowed_hosts?: string[]
  confirmed_at?: string | null
  confirmed_by?: string | null
}

export interface RuntimeConfigAuditInfo {
  audit_id?: string | null
  action?: string | null
  actor?: string | null
  updated_at?: string | null
  summary?: string | null
  key_material_recorded?: boolean
}

export interface AgentLLMProfile {
  id: string
  label: string
  provider: LLMProvider
  base_url: string
  model: string
  egress_confirmed?: boolean
  egress_policy_status?: 'ALLOWED' | 'BLOCKED' | 'NOT_EVALUATED' | (string & {})
  egress_policy_message?: string
  configured?: boolean
  auth_available?: boolean
  api_key_set: boolean
  api_key_mask?: string | null
  health_status?: RuntimeProfileHealthStatus
  health_warnings?: string[]
  base_url_security?: RuntimeBaseUrlSecurity
  config_audit?: RuntimeConfigAuditInfo
  last_config_audit_id?: string | null
  last_call_success?: boolean | null
  last_error?: string
  last_checked_at?: string
  last_test_status?: string
  last_test_message?: string
  last_live_call_at?: string
  last_latency_ms?: number | null
  last_usage?: Record<string, any>
  temperature: number
  max_tokens: number
  timeout_seconds: number
  enabled: boolean
  extra_headers: Record<string, string>
}

export interface MarketDataProfile {
  id: string
  label: string
  provider: string
  base_url: string
  quote_path: string
  symbol_query_param: string
  auth_mode: string
  api_key_set: boolean
  api_key_mask?: string | null
  egress_confirmed?: boolean
  egress_policy_status?: 'ALLOWED' | 'BLOCKED' | 'NOT_EVALUATED' | (string & {})
  egress_policy_message?: string
  health_status?: RuntimeProfileHealthStatus
  health_warnings?: string[]
  last_call_success?: boolean | null
  last_error?: string
  last_checked_at?: string
  last_test_status?: string
  last_test_message?: string
  last_live_call_at?: string
  last_latency_ms?: number | null
  base_url_security?: RuntimeBaseUrlSecurity
  config_audit?: RuntimeConfigAuditInfo
  last_config_audit_id?: string | null
  api_key_header: string
  api_key_query_param: string
  timeout_seconds: number
  enabled: boolean
  extra_headers: Record<string, string>
  extra_query_params: Record<string, string>
  price_path: string
  name_path: string
  change_percent_path: string
  volume_path: string
  timestamp_path: string
}

export interface AgentDeployment {
  id: string
  name: string
  stage: string
  role: string
  enabled: boolean
  status: 'READY' | 'DISABLED' | (string & {})
  llm_profile_id: string
  system_prompt_ref: string
  prompt_file?: string
  prompt_hash?: string
  node_type?: string
  run_modes?: string[]
  next_nodes?: string[]
  tool_scope: string[]
}

export interface AgentRuntimeConfig {
  default_llm_profile_id: string
  default_market_data_profile_id: string
  max_parallel_agents: number
  agents: AgentDeployment[]
  llm_profiles: AgentLLMProfile[]
  market_data_profiles: MarketDataProfile[]
  updated_at: string
}

export interface UpsertLLMProfilePayload {
  label?: string
  provider?: string
  base_url?: string
  model?: string
  api_key?: string
  clear_api_key?: boolean
  egress_confirmed?: boolean
  temperature?: number
  max_tokens?: number
  timeout_seconds?: number
  enabled?: boolean
  extra_headers?: Record<string, string>
}

export interface UpsertMarketDataProfilePayload {
  label?: string
  provider?: string
  base_url?: string
  quote_path?: string
  symbol_query_param?: string
  auth_mode?: string
  api_key?: string
  clear_api_key?: boolean
  egress_confirmed?: boolean
  api_key_header?: string
  api_key_query_param?: string
  timeout_seconds?: number
  enabled?: boolean
  extra_headers?: Record<string, string>
  extra_query_params?: Record<string, string>
  price_path?: string
  name_path?: string
  change_percent_path?: string
  volume_path?: string
  timestamp_path?: string
}

export interface AgentRuntimeSummary {
  defaultLlmProfileId: string
  defaultMarketDataProfileId?: string
  maxParallelAgents: number
  marketData?: {
    defaultProfileId: string
    provider?: string | null
    enabled: boolean
    ready: boolean
  }
  agents: Array<{
    id: string
    name: string
    enabled: boolean
    llmProfileId: string
    model?: string | null
    promptFile?: string
    promptHash?: string
    nodeType?: string
    runModes?: string[]
    nextNodes?: string[]
  }>
}

export interface LLMConfigTestResult {
  profile_id: string
  status: 'READY' | 'CONFIGURED' | 'FAILED' | 'INCOMPLETE' | 'NOT_FOUND' | (string & {})
  message: string
  details: Record<string, any>
}

export interface MarketDataConfigTestResult {
  profile_id: string
  status: 'READY' | 'INCOMPLETE' | 'NOT_FOUND' | (string & {})
  message: string
  details: Record<string, any>
}

export interface BacktestRequest {
  symbol: string
  stock_name?: string
  patch_id?: string
  case_id?: string
  start_date: string
  end_date: string
  initial_capital?: number
  scenario_label?: string
  parameters?: Record<string, any>
  reuse_existing?: boolean
  force_new?: boolean
}

export interface BacktestParameterScanWindow {
  start: string
  end: string
  label?: string
}

export interface BacktestParameterScanRequest {
  symbol: string
  stock_name?: string
  patch_id?: string
  case_id?: string
  start_date: string
  end_date: string
  initial_capital?: number
  scenario_label?: string
  base_parameters?: Record<string, any>
  parameter_grid: Record<string, any[]>
  windows?: BacktestParameterScanWindow[]
  max_combinations?: number
  ranking_metric?: string
  reuse_existing?: boolean
  force_new?: boolean
}

export interface BacktestParameterScanResponse {
  scan_id: string
  status: string
  symbol: string
  start_date?: string
  end_date?: string
  ranking_metric?: string
  parameter_grid: Record<string, any[]>
  combinations: Array<Record<string, any>>
  windows?: BacktestParameterScanWindow[]
  window_count?: number
  run_ids: string[]
  best_run_id?: string | null
  best_score: number
  summary: Record<string, any>
  runs: BacktestRunItem[]
  trial_count?: number
  simulation_only: boolean
  is_real_trade: boolean
}

export interface BacktestParameterScanHistoryItem {
  scan_id: string
  status: string
  symbol: string
  stock_name?: string
  start_date?: string
  end_date?: string
  ranking_metric?: string
  parameter_grid: Record<string, any[]>
  combinations: Array<Record<string, any>>
  windows?: BacktestParameterScanWindow[]
  window_count?: number
  run_ids: string[]
  best_run_id?: string | null
  best_score: number
  summary: Record<string, any>
  trial_count: number
  created_at?: string
  updated_at?: string
  simulation_only: boolean
  is_real_trade: boolean
}

export interface BacktestParameterScanJobAttempt {
  attemptId: string
  attemptNumber?: number
  status?: string
  progressStep?: string
  startedAt?: string
  finishedAt?: string | null
  error?: string | null
  scanId?: string
  runIds?: string[]
  bestRunId?: string | null
  idempotencyKey?: string
  queueMode?: string
  leaseOwner?: string
  leaseId?: string
  leaseStatus?: string
  leaseAcquiredAt?: string | null
  leaseExpiresAt?: string | null
  leaseReleasedAt?: string | null
  leaseSeconds?: number
  recovered?: boolean
  recoveryAttemptCount?: number
  simulationOnly?: boolean
  isRealTrade?: boolean
}

export interface BacktestParameterScanJob {
  jobId: string
  status: string
  progressStep?: string
  request?: Record<string, any>
  scan?: BacktestParameterScanResponse | null
  scanId?: string
  runIds?: string[]
  bestRunId?: string | null
  totalCombinations?: number
  totalTrials?: number
  windowCount?: number
  simulationOnly: boolean
  isRealTrade: boolean
  error?: string | null
  queueMode?: string
  storageSchema?: string
  durable?: boolean
  recovered?: boolean
  recoveredAt?: string | null
  recoveryAttemptCount?: number
  idempotencyKey?: string
  attemptCount?: number
  currentAttemptId?: string | null
  lastAttemptStatus?: string | null
  attempts?: BacktestParameterScanJobAttempt[]
  leaseOwner?: string
  leaseId?: string
  leaseStatus?: string
  leaseAcquiredAt?: string | null
  leaseExpiresAt?: string | null
  leaseReleasedAt?: string | null
  leaseSeconds?: number
  handoffStatus?: Record<string, any>
  createdAt?: string
  updatedAt?: string
}

export interface BacktestParameterScanJobHandoff {
  schema?: string
  status: string
  reason?: string
  createdAt?: string
  jobId?: string
  scanId?: string
  jobStatus?: string
  handoffId?: string
  handoffDir?: string
  handoffDestination?: string
  handoffRequiresCompletedJob?: boolean
  bundleFile?: string
  manifestFile?: string
  bundleChecksum?: string
  queueMode?: string
  idempotencyKey?: string
  manifest?: Record<string, any>
  appendOnly?: boolean
  simulationOnly?: boolean
  isRealTrade?: boolean
}

export interface BacktestExperimentPackageResponse {
  package_id: string
  run_id: string
  generated_at: string
  manifest: Record<string, any>
  hashes: Record<string, any>
  reproducibility: Record<string, any>
  run: BacktestRunItem
  trades: BacktestTradeItem[]
  signals: BacktestSignalItem[]
  simulation_only: boolean
  is_real_trade: boolean
}

export interface BacktestExperimentWindow {
  start: string
  end: string
}

export interface BenchmarkComparison {
  symbol?: string
  available?: boolean
  status?: string
  reason?: string
  unavailable_reason?: string
  data_source?: string
  benchmark_return_pct?: number
  baseline_return_pct?: number
  candidate_return_pct?: number
  baseline_expectancy_pct?: number
  candidate_expectancy_pct?: number
  candidate_excess_return_pct?: number
  [key: string]: unknown
}

export interface SignalOpsExperimentPackage {
  package_id?: string
  source?: string
  experiment_package_hash?: string
  computed_experiment_package_hash?: string
  package_hash_matches_computed?: boolean
  walk_forward_run_ids?: Record<string, string>
  benchmark_comparison?: BenchmarkComparison
  walk_forward_summary?: Record<string, unknown>
  stability_evidence_package?: StabilityEvidencePackage
  stability_validation_report?: Record<string, unknown>
  triple_barrier_summary?: TripleBarrierLabelSummary | Record<string, unknown>
  review_queue_item_id?: string
  evidence_links?: Array<Record<string, unknown>>
  simulation_only?: boolean
  is_real_trade?: boolean
  [key: string]: unknown
}

export interface SignalOpsExperimentRequest {
  symbol: string
  stock_name?: string
  train_window: BacktestExperimentWindow
  validation_window: BacktestExperimentWindow
  baseline_config: Record<string, unknown>
  candidate_config: Record<string, unknown>
  experiment_package_hash: string
  initial_capital?: number
  benchmark_symbol?: string
  reviewer?: string
}

export interface SignalOpsExperimentResponse {
  status: string
  message: string
  experiment_package_hash: string
  promotion_status: string
  walk_forward_run_ids: Record<string, string>
  walk_forward_validation: Record<string, unknown>
  benchmark_comparison: BenchmarkComparison
  benchmark_unavailable_reason?: string
  review_queue_sync_status?: SignalOpsReviewQueueSyncStatus | string
  warnings?: string[]
  research_evidence_package: SignalOpsExperimentPackage
  stability_evidence_package?: StabilityEvidencePackage
  baseline_run: BacktestRunItem
  candidate_run: BacktestRunItem
  simulation_only: boolean
  is_real_trade: boolean
}

export type SignalOpsRandomValidationMode = 'VALIDATE_ONLY' | 'VALIDATE_AND_FEEDBACK'
export type SignalOpsRandomValidationStatus = 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'CANCELLED' | string

export interface SignalOpsRandomValidationJob {
  jobId: string
  status: SignalOpsRandomValidationStatus
  progressStep: string
  seed: number
  mode: SignalOpsRandomValidationMode | string
  simulationOnly: boolean
  isRealTrade: boolean
  sampleWindows: Array<Record<string, any>>
  dataQuality: Record<string, any>
  baselineResults: Record<string, any>
  candidateResults: Record<string, any>
  evidenceLevel: string
  appliedAdjustment: Record<string, any>
  rejectionReasons: string[]
  reviewQueueSyncStatus?: string
  error?: string | null
  createdAt: string
  updatedAt: string
}

export interface SignalOpsRandomValidationRequest {
  mode?: SignalOpsRandomValidationMode
  seed?: number
  history_years?: number
  min_window_days?: number
  max_window_days?: number
  min_trading_days?: number
  initial_capital?: number
  benchmark_symbol?: string
}

export interface BacktestRunItem {
  run_id: string
  patch_id?: string
  case_id?: string
  symbol: string
  stock_name: string
  scenario_label: string
  status: string
  start_date: string
  end_date: string
  initial_capital: number
  parameters: Record<string, any>
  report: BacktestReport
  comparison: BacktestComparison
  error?: string
  elapsed_ms: number
  created_at: string
  updated_at: string
}

export interface BacktestTradeItem {
  trade_id: string
  run_id: string
  direction: string
  price: number
  quantity: number
  amount: number
  slippage: number
  timestamp: string
  reason: string
  realized_pnl?: number
}

export interface BacktestSignalItem {
  signal_id: string
  run_id: string
  signal_type: string
  direction: string
  strength: number
  price: number
  timestamp: string
  source_node: string
  metadata_json: Record<string, any>
}

export interface BacktestReport {
  data_source?: string
  data_error?: string | null
  data_points?: number
  signal_source?: string
  signal_source_count?: number
  total_trades: number
  winning_trades: number
  losing_trades: number
  hit_rate: number
  false_positive_rate: number
  total_pnl: number
  max_drawdown: number
  max_drawdown_pct: number
  sharpe_ratio: number
  total_signals: number
  buy_signals: number
  sell_signals: number
  manual_review_pass_rate: number
  t_plus_one_blocked: number
  price_limit_blocked: number
  slippage_total: number
  final_capital: number
  total_return_pct: number
  benchmark?: Record<string, any>
  sampleWindow?: Record<string, any>
  tradingCost?: Record<string, any>
  slippage?: Record<string, any>
  executionConstraints?: Record<string, any>
  outOfSampleWindow?: Record<string, any>
  statisticalConfidence?: Record<string, any>
  evidenceStrength?: Record<string, any>
  researchGradeScore?: Record<string, any>
  limitations?: string[]
  provenance?: Record<string, any>
  researchContract?: Record<string, any>
  validationProtocol?: Record<string, any>
  walk_forward_run_ids?: Record<string, string>
  benchmark_comparison?: BenchmarkComparison
  research_evidence_package?: SignalOpsExperimentPackage
  equity_curve: Array<{ date: string; capital: number; position_pnl: number }>
  trade_log: BacktestTradeItem[]
  signal_log: BacktestSignalItem[]
}

export interface BacktestComparison {
  before?: BacktestReport
  after?: BacktestReport
  hit_rate_delta: number
  drawdown_delta: number
  false_positive_delta: number
  pnl_delta: number
  return_delta: number
  verdict: string
  researchContract?: Record<string, any>
  walk_forward_validation?: Record<string, any>
  benchmark_comparison?: BenchmarkComparison
}

export interface BacktestSummary {
  total_runs: number
  completed_runs: number
  pending_runs: number
}

export interface GateCheck {
  key: string
  passed: boolean
  message: string
}

export interface SignalItem {
  signal_id: string
  symbol: string
  stock_name: string
  status: SignalOpsStatus
  source_run_id?: string | null
  latest_run_id?: string | null
  audit_id: string
  risk_passed: boolean
  dvg_passed: boolean
  dvg_status: string
  qiam_passed: boolean
  qiam_status: string
  execution_reachable: boolean
  portfolio_allowed: boolean
  trigger_conditions: string[]
  invalidation_conditions: string[]
  review_fields: string[]
  attached_runs: string[]
  blocked_reason: string
  metadata_json: Record<string, any>
  created_at: string
  updated_at: string
}

export interface CreateSignalPayload {
  symbol: string
  stock_name?: string
  source_run_id?: string
  audit_id?: string
  risk_passed?: boolean
  dvg_passed?: boolean
  dvg_status?: string
  qiam_passed?: boolean
  qiam_status?: string
  execution_reachable?: boolean
  portfolio_allowed?: boolean
  trigger_conditions?: string[]
  invalidation_conditions?: string[]
  review_fields?: string[]
  metadata_json?: Record<string, any>
}

export interface SignalTransitionPayload {
  target_status: SignalOpsStatus
  audit_id?: string
  run_id?: string
  actor?: string
  reason?: string
  gate_context?: Record<string, any>
}

export interface UpdateSignalConditionsPayload {
  audit_id?: string
  trigger_conditions: string[]
  invalidation_conditions: string[]
  review_fields?: string[]
}

export interface SignalTransitionItem {
  transition_id: string
  signal_id: string
  from_status: SignalOpsStatus
  to_status: SignalOpsStatus
  audit_id: string
  run_id?: string | null
  actor: string
  reason: string
  gate_checks: GateCheck[]
  passed: boolean
  simulation_only: boolean
  is_real_trade: boolean
  created_at: string
}

export interface SignalReviewPayload {
  audit_id?: string
  reviewer?: string
  review_type?: string
  decision?: string
  note?: string
  review_fields?: string[]
}

export interface SignalReviewItem {
  review_id: string
  signal_id: string
  audit_id: string
  reviewer: string
  review_type: string
  decision: string
  note: string
  review_fields: string[]
  simulation_only: boolean
  is_real_trade: boolean
  created_at: string
}

export interface SignalDetail {
  signal: SignalItem
  transitions: SignalTransitionItem[]
  reviews: SignalReviewItem[]
}

export interface PaperPortfolioPayload {
  audit_id?: string
  run_id?: string
  initial_cash?: number
  risk_budget?: Record<string, any>
  created_by_agent?: string
}

export interface PaperPortfolioItem {
  portfolio_id: string
  signal_id: string
  audit_id: string
  run_id?: string | null
  symbol: string
  initial_cash: number
  available_cash: number
  market_value: number
  max_drawdown: number
  risk_budget: Record<string, any>
  created_by_agent: string
  simulation_only: boolean
  is_real_trade: boolean
  created_at: string
  updated_at: string
}

export interface PaperPositionItem {
  position_id: string
  portfolio_id: string
  signal_id: string
  symbol: string
  quantity: number
  virtual_cost: number
  current_value: number
  floating_pnl: number
  max_drawdown: number
  simulation_only: boolean
  is_real_trade: boolean
  updated_at: string
}

export interface PaperOrderPayload {
  audit_id?: string
  run_id?: string
  agent_id?: string
  action: string
  action_reason?: string
  simulated_price?: number
  simulated_quantity?: number
  risk_constraints?: Record<string, any>
  data_snapshot_hash?: string
}

export interface PaperFillPayload {
  audit_id?: string
  filled_price?: number
  filled_quantity?: number
  fees?: number
  slippage?: number
  fill_status?: string
  rule_checks?: Record<string, any>[]
}

export interface PaperOrderItem {
  order_id: string
  paper_portfolio_id: string
  signal_id: string
  audit_id: string
  run_id?: string | null
  agent_id: string
  action: string
  action_reason: string
  simulated_price: number
  simulated_quantity: number
  fill_status: string
  risk_constraints: Record<string, any>
  invalidation_conditions: string[]
  data_snapshot_hash: string
  simulated_fill: Record<string, any>
  simulation_only: boolean
  is_real_trade: boolean
  created_at: string
  updated_at: string
}

export type SignalOpsReviewDecision = 'PASS_REVIEW' | 'REJECT_SUGGESTION' | 'KEEP_WATCH' | 'REQUEST_PATCH'
export type SignalOpsReviewDecisionAction = 'APPROVE_SIMULATION_CANDIDATE' | 'REJECT_CANDIDATE' | 'CONTINUE_OBSERVING' | 'REQUEST_PATCH'
export type EvidenceQuality = 'STRONG' | 'MEDIUM' | 'LOW' | 'SUPPORTING_ONLY'
export type SignalOpsReviewQueueSyncStatus = 'SYNCED' | 'FAILED' | 'NOT_SYNCED' | 'PENDING'
export type SignalOpsReviewQueueLifecycleStatus =
  | 'BACKTEST_PENDING'
  | 'READY_FOR_REVIEW'
  | 'APPLIED_TO_SIMULATION'
  | 'RECOMMENDED_ONLY'
  | 'REJECTED'
  | 'SUPERSEDED'
  | 'EXPIRED'

export interface PreBuyQuality {
  status?: string
  actionPolicy?: string
  action_policy?: string
  quality_status?: string
  confidence?: number
  score?: number
  grade?: string
  components?: Record<string, unknown> & {
    kline_signal_quality?: KlineSignalQuality
    strategy_stability_quality?: StrategyStabilityQuality
  }
  kline_signal_quality?: KlineSignalQuality
  strategy_stability_quality?: StrategyStabilityQuality
  reasons?: string[]
  blockers?: string[]
  warnings?: string[]
  [key: string]: unknown
}

export interface KlineSignalQualityComponent {
  score?: number
  status?: string
  reasons?: string[]
  [key: string]: unknown
}

export interface LadderBuyPolicy {
  stage?: string
  target_position_ratio?: number
  max_position_ratio?: number
  max_step_position_ratio?: number
  invalidate_on?: string[]
  simulation_only?: boolean
  is_real_trade?: boolean
  [key: string]: unknown
}

export interface KlineStrategyConfig {
  method?: string
  allow_actions?: string[]
  requires_backtest_before_review?: boolean
  simulation_only?: boolean
  is_real_trade?: boolean
  [key: string]: unknown
}

export interface KlineSignalQuality {
  version?: number
  symbol?: string
  status?: string
  final_score?: number
  score?: number
  grade?: string
  action_policy?: string
  actionPolicy?: string
  trend_regime?: KlineSignalQualityComponent
  bottom_stage_score?: KlineSignalQualityComponent
  volatility_compression?: KlineSignalQualityComponent
  volume_price_confirmation?: KlineSignalQualityComponent
  multi_timeframe_alignment?: KlineSignalQualityComponent
  risk_invalidation?: KlineSignalQualityComponent
  ladder_stage?: string
  ladder_buy_policy?: LadderBuyPolicy
  kline_strategy?: KlineStrategyConfig
  buyThresholdDelta?: number
  positionRatioMultiplier?: number
  metrics?: Record<string, unknown>
  reasons?: string[]
  evidence_refs?: Array<Record<string, unknown>>
  simulation_only?: boolean
  is_real_trade?: boolean
  [key: string]: unknown
}

export interface KlineEvidencePackage {
  package_id?: string
  source?: string
  symbol?: string
  kline_signal_quality?: KlineSignalQuality
  kline_strategy?: KlineStrategyConfig
  ladder_buy_policy?: LadderBuyPolicy
  score?: number
  grade?: string
  action_policy?: string
  simulation_only?: boolean
  is_real_trade?: boolean
  [key: string]: unknown
}

export interface RegimeState {
  score?: number
  status?: 'TREND_UP' | 'RANGE' | 'DOWNTREND' | 'HIGH_VOL_STRESS' | 'RECOVERY_CONFIRMED' | string
  reasons?: string[]
  [key: string]: unknown
}

export interface TripleBarrierLabelSummary {
  method?: string
  status?: string
  sample_count?: number
  vertical_barrier_days?: number
  take_profit_atr?: number
  stop_loss_atr?: number
  counts?: Record<string, number>
  hit_rate?: number
  stop_rate?: number
  avg_max_adverse_excursion?: number
  avg_max_favorable_excursion?: number
  labels?: Array<Record<string, unknown>>
  simulation_only?: boolean
  is_real_trade?: boolean
  [key: string]: unknown
}

export interface MetaLabelGate {
  method?: string
  enabled?: boolean
  model_ready?: boolean
  required_model_samples?: number
  min_gate_samples?: number
  sample_count?: number
  wins?: number
  posterior_win_rate?: number
  wilson_win_rate_lower_bound?: number
  expectancy?: number
  max_drawdown?: number
  status?: string
  score?: number
  action_policy?: string
  reasons?: string[]
  simulation_only?: boolean
  is_real_trade?: boolean
  [key: string]: unknown
}

export interface VolatilitySizingPolicy {
  method?: string
  max_position_ratio?: number
  max_step_position_ratio?: number
  position_ratio_multiplier?: number
  probe_only?: boolean
  forbid_confirm?: boolean
  simulation_only?: boolean
  is_real_trade?: boolean
  [key: string]: unknown
}

export interface StabilityStrategyConfig {
  method?: string
  uses?: string[]
  requires_backtest_before_review?: boolean
  simulation_only?: boolean
  is_real_trade?: boolean
  [key: string]: unknown
}

export interface StrategyStabilityQuality {
  version?: number
  symbol?: string
  status?: string
  stability_score?: number
  score?: number
  grade?: string
  regime_state?: RegimeState
  volatility_state?: KlineSignalQualityComponent
  drawdown_throttle?: KlineSignalQualityComponent
  confidence_floor?: number
  confidence_floor_detail?: Record<string, unknown>
  action_policy?: string
  actionPolicy?: string
  buyThresholdDelta?: number
  positionRatioMultiplier?: number
  volatility_sizing_policy?: VolatilitySizingPolicy
  stability_strategy?: StabilityStrategyConfig
  meta_label_gate?: MetaLabelGate
  triple_barrier_summary?: TripleBarrierLabelSummary | Record<string, unknown>
  metrics?: Record<string, unknown>
  reasons?: string[]
  evidence_refs?: Array<Record<string, unknown>>
  simulation_only?: boolean
  is_real_trade?: boolean
  [key: string]: unknown
}

export interface StabilityEvidencePackage {
  package_id?: string
  source?: string
  symbol?: string
  strategy_stability_quality?: StrategyStabilityQuality
  stability_strategy?: StabilityStrategyConfig
  meta_label_gate?: MetaLabelGate
  volatility_sizing_policy?: VolatilitySizingPolicy
  stability_validation_report?: Record<string, unknown>
  triple_barrier_summary?: TripleBarrierLabelSummary | Record<string, unknown>
  score?: number
  grade?: string
  action_policy?: string
  simulation_only?: boolean
  is_real_trade?: boolean
  [key: string]: unknown
}

export interface SignalOpsDecisionCard {
  action?: string
  reason?: string
  capital_before?: number
  capital_after?: number
  cash_available?: number
  position_value?: number
  budget_used?: number
  commission_fee?: number
  stamp_duty_fee?: number
  total_fee?: number
  blockers?: string[]
  research_tuning_refs?: Array<Record<string, unknown>>
  capital_attribution?: Record<string, unknown>
  pre_buy_quality?: PreBuyQuality | null
  kline_signal_quality?: KlineSignalQuality | null
  strategy_stability_quality?: StrategyStabilityQuality | null
  kline_strategy?: KlineStrategyConfig
  ladder_buy_policy?: LadderBuyPolicy
  stability_strategy?: StabilityStrategyConfig
  meta_label_gate?: MetaLabelGate
  volatility_sizing_policy?: VolatilitySizingPolicy
  quant_core_path_risk?: SignalOpsPathRiskSummary
  quant_core_path_risk_policy?: string
  quant_core_path_risk_avoids_new_buy?: boolean
  future_trend_probability?: SignalOpsFutureTrendSummary
  decision_tree?: Record<string, unknown>
  review_fields?: string[]
  simulation_only?: boolean
  is_real_trade?: boolean
  [key: string]: unknown
}

export interface SignalOpsPathRiskSummary {
  status?: string
  riskPolicy?: string
  downsideRiskScore?: number | null
  maxRiskGradient?: number | null
  mfeProxy?: number | null
  maeProxy?: number | null
  riskRewardProxy?: number | null
  actionBoundary?: string
  labelStatus?: string
  sampleQuality?: Record<string, unknown>
  leakagePolicy?: string
  simulation_only?: boolean
  is_real_trade?: boolean
  [key: string]: unknown
}

export interface SignalOpsFutureTrendSummary {
  version?: string
  source?: string
  horizonDays?: number | null
  calibratedUpProbability?: number | null
  calibratedDownProbability?: number | null
  confidence?: number | null
  calibrationStatus?: string
  sampleCount?: number | null
  brierUp?: number | null
  brierDown?: number | null
  signalopsPolicyHint?: string
  actionBoundary?: string
  simulation_only?: boolean
  is_real_trade?: boolean
  [key: string]: unknown
}

export interface SignalOpsDecisionTreeTuning {
  tuning_id?: string
  source_tree_id?: string
  review_id?: string
  created_at?: string
  before?: Record<string, unknown>
  after?: Record<string, unknown>
  applied?: boolean
  applied_parameters?: Record<string, unknown>
  reason?: string
  branch_evidence?: Array<Record<string, unknown>>
  review_counts?: Record<string, unknown>
  simulation_only?: boolean
  is_real_trade?: boolean
  [key: string]: unknown
}

export interface SignalOpsDecisionTreeBranch {
  branch_id?: string
  tree_id?: string
  sequence?: number
  created_at?: string
  trade_date?: string
  action?: string
  strategy_intent?: string
  reason?: string
  source?: string
  price?: number | null
  ma5?: number | null
  stage_low?: Record<string, unknown>
  peak?: Record<string, unknown>
  current_return_pct?: number | null
  peak_return_pct?: number | null
  portfolio_before?: Record<string, unknown>
  portfolio_after?: Record<string, unknown>
  order_summary?: Record<string, unknown>
  kline_signal_quality?: Record<string, unknown>
  strategy_stability_quality?: Record<string, unknown>
  blockers?: string[]
  decision_snapshot?: Record<string, unknown>
  simulation_only?: boolean
  is_real_trade?: boolean
  [key: string]: unknown
}

export interface SignalOpsDecisionTreeReview {
  review_id?: string
  tree_id?: string
  symbol?: string
  status?: string
  created_at?: string
  start?: Record<string, unknown>
  peak?: Record<string, unknown>
  end_context?: Record<string, unknown>
  branch_count?: number
  counts?: Record<string, number>
  correct_count?: number
  wrong_count?: number
  partial_count?: number
  skipped_count?: number
  branch_reviews?: Array<Record<string, unknown>>
  knowledge_item_id?: string
  simulation_only?: boolean
  is_real_trade?: boolean
  [key: string]: unknown
}

export interface SignalOpsDecisionTree {
  tree_id?: string
  symbol?: string
  stock_name?: string
  status?: string
  created_at?: string
  updated_at?: string
  start?: Record<string, unknown>
  peak?: Record<string, unknown>
  current?: Record<string, unknown>
  metrics?: Record<string, unknown>
  branch_count?: number
  branches?: SignalOpsDecisionTreeBranch[]
  end_context?: Record<string, unknown>
  review?: SignalOpsDecisionTreeReview
  decision_tree_tuning?: SignalOpsDecisionTreeTuning
  simulation_only?: boolean
  is_real_trade?: boolean
  [key: string]: unknown
}

export interface SignalOpsDecisionTreeSymbolState {
  status?: string
  candidate_low?: Record<string, unknown>
  active_tree?: SignalOpsDecisionTree
  latest_closed_tree?: SignalOpsDecisionTree
  closed_trees?: SignalOpsDecisionTree[]
  closed_count?: number
  last_review?: SignalOpsDecisionTreeReview
  last_tuning_audit?: SignalOpsDecisionTreeTuning
  last_context?: Record<string, unknown>
  simulation_only?: boolean
  is_real_trade?: boolean
  [key: string]: unknown
}

export interface SignalOpsDecisionTreeState {
  version?: number
  updated_at?: string
  symbols?: Record<string, SignalOpsDecisionTreeSymbolState>
  tuning_audit?: SignalOpsDecisionTreeTuning[]
  simulation_only?: boolean
  is_real_trade?: boolean
  [key: string]: unknown
}

export interface PerformanceBucket {
  sample_count?: number
  trade_count?: number
  wins?: number
  failures?: number
  no_trade_count?: number
  win_rate?: number
  avg_pnl_rate?: number
  expectancy?: number
  profit_factor?: number
  max_drawdown?: number
  confidence?: number
  pnl_rate_sum?: number
  gross_win_rate?: number
  gross_loss_rate?: number
  quality_status?: string
  prior_decay?: number
  updated_at?: string
  [key: string]: unknown
}

export interface PerformanceStats {
  version?: number
  updated_at?: string
  global?: Record<string, PerformanceBucket>
  symbols?: Record<string, PerformanceBucket>
  factors?: Record<string, PerformanceBucket>
  triggers?: Record<string, PerformanceBucket>
  [key: string]: unknown
}

export interface StrategyExperiment {
  experiment_id?: string
  experiment_package_hash?: string
  baseline_config?: Record<string, unknown>
  candidate_config?: Record<string, unknown>
  parameter_diff_summary?: SignalOpsParameterDiffSummary
  candidate_reason?: string
  promotion_gate?: Record<string, unknown>
  winner_config_id?: string
  promotion_status?: string
  evidence_links?: Array<Record<string, unknown>>
  evidence_package?: Record<string, unknown>
  kline_evidence_package?: KlineEvidencePackage
  stability_evidence_package?: StabilityEvidencePackage
  walk_forward_run_ids?: Record<string, string>
  benchmark_comparison?: BenchmarkComparison
  simulation_only?: boolean
  is_real_trade?: boolean
  [key: string]: unknown
}

export interface SignalOpsParameterDiffRow {
  key: string
  baseline?: unknown
  candidate?: unknown
  change_type?: 'CHANGED' | 'ADDED' | 'REMOVED' | 'UNCHANGED' | string
}

export interface SignalOpsParameterDiffSummary {
  policy_id?: string
  status?: 'CHANGED' | 'UNCHANGED' | 'EMPTY' | string
  changed_count?: number
  added_count?: number
  removed_count?: number
  unchanged_count?: number
  total_parameter_count?: number
  visible_row_count?: number
  truncated?: boolean
  rows?: SignalOpsParameterDiffRow[]
  source?: string
  simulation_only?: boolean
  is_real_trade?: boolean
  [key: string]: unknown
}

export interface WalkForwardValidationResult {
  status?: string
  method?: string
  candidate_direction?: string
  train_window?: Record<string, unknown>
  validation_window?: Record<string, unknown>
  train_metrics?: Record<string, unknown>
  validation_metrics?: Record<string, unknown>
  checks?: Record<string, unknown>
  sample_quality?: EvidenceQuality | string
  reasons?: string[]
  benchmark_comparison?: BenchmarkComparison
  stability_validation_report?: Record<string, unknown>
  simulation_only?: boolean
  is_real_trade?: boolean
  [key: string]: unknown
}

export interface TuningUpdate {
  review_reason?: string
  adjustment_model?: string
  sample_count?: number
  current_sample_count?: number
  current_no_trade_count?: number
  compressed_observation_count?: number
  compressed_observation_history?: Record<string, unknown>
  trade_count?: number
  evidence_weight?: number
  wins?: number
  failures?: number
  risk_tightened?: boolean
  tuning_confidence?: number
  risk_pressure?: number
  opportunity_pressure?: number
  nonlinear_adjustment?: number
  avg_pnl_rate?: number
  avg_loss_rate?: number
  avg_win_rate?: number
  max_drawdown?: number
  no_trade_rate?: number
  buy_delta?: number
  close_delta?: number
  position_ratio_multiplier?: number
  performance_stats?: PerformanceStats
  performance_summary?: {
    global?: PerformanceBucket
    top_factors?: Array<PerformanceBucket & { key?: string }>
    low_quality_triggers?: Array<PerformanceBucket & { key?: string }>
    min_trade_count?: number
    min_evidence_weight?: number
    min_confidence?: number
    [key: string]: unknown
  }
  recommended_parameters?: Record<string, unknown>
  applied_parameters?: Record<string, unknown>
  application_status?: string
  application_reason?: string
  walk_forward_validation?: WalkForwardValidationResult
  strategy_experiment?: StrategyExperiment
  candidate_evidence_package?: Record<string, unknown>
  kline_evidence_package?: KlineEvidencePackage
  stability_evidence_package?: StabilityEvidencePackage
  before?: Record<string, unknown>
  next_parameters?: Record<string, unknown>
  candidate_factor_adjustments?: Record<string, unknown>
  applied_factor_adjustments?: Record<string, unknown>
  factor_adjustments?: Record<string, unknown>
  after?: Record<string, unknown>
  [key: string]: unknown
}

export interface CleanedSignalRecord {
  record_id?: string
  trading_date?: string
  signal_date?: string
  symbol?: string
  source_type?: string
  source_id?: string
  decision_id?: string
  outcome?: string
  sample_quality?: EvidenceQuality | string
  evidence_refs?: Array<Record<string, unknown>>
  signal_id?: string | null
  signal_status?: SignalOpsStatus | string
  trigger_conditions?: string[]
  invalidation_conditions?: string[]
  user_initial_buy_signal?: string
  user_final_sell_signal?: string
  order_count?: number
  all_order_count?: number
  action_counts?: Record<string, number>
  latest_action?: string
  latest_order_id?: string | null
  filled_value?: number
  total_fees?: number
  available_cash?: number
  market_value?: number
  initial_cash?: number
  floating_pnl?: number
  pnl_rate?: number
  max_drawdown?: number
  invalidation_triggered?: boolean
  factor_sources?: string[]
  failure_tags?: string[]
  simulation_only?: boolean
  is_real_trade?: boolean
  cleaned_at?: string
  [key: string]: unknown
}

export interface SignalOpsResearchReview {
  status?: string
  message?: string
  trading_date?: string
  loop_id?: string | null
  iteration_id?: string | null
  reviewed_symbols?: Array<Record<string, unknown>>
  case_ids?: string[]
  evidence_links?: Array<Record<string, unknown>>
  tuning_update?: TuningUpdate
  cleaned_records?: CleanedSignalRecord[]
  compressed_observation_history?: Record<string, unknown>
  review_queue_state?: SignalOpsReviewQueueState
  review_decisions?: SignalOpsReviewDecisionRecord[]
  experiment_validation_state?: SignalOpsExperimentValidationState
  warnings?: string[]
  decision_tree_reviews?: SignalOpsDecisionTreeReview[]
  updated_at?: string
  [key: string]: unknown
}

export interface SignalOpsReviewDecisionRecord {
  decision_id?: string
  queue_item_id?: string
  experiment_id?: string
  signal_id?: string | null
  symbol?: string
  action?: SignalOpsReviewDecisionAction | string
  result_status?: string
  reviewer?: string
  reason?: string
  review_reason?: string
  supersedes?: string
  evidence_refs?: Array<Record<string, unknown>>
  review_fields?: string[]
  applied_parameters?: Record<string, unknown>
  applied_factor_adjustments?: Record<string, unknown>
  parameter_diff_summary?: SignalOpsParameterDiffSummary
  parameter_diff_checksum?: string
  reviewed_parameter_count?: number
  reviewed_parameter_changed_count?: number
  review_decision_summary?: Record<string, unknown>
  created_at?: string
  simulation_only?: boolean
  is_real_trade?: boolean
  [key: string]: unknown
}

export interface SignalOpsReviewQueueState {
  version?: number
  updated_at?: string
  items?: Array<Record<string, unknown>>
  observations?: Array<Record<string, unknown>>
  counts?: Record<string, number>
  simulation_only?: boolean
  is_real_trade?: boolean
  [key: string]: unknown
}

export interface SignalOpsExperimentValidationAttempt {
  experiment_package_hash?: string
  status?: string
  promotion_status?: string
  walk_forward_run_ids?: Record<string, string>
  walk_forward_validation?: WalkForwardValidationResult
  benchmark_comparison?: BenchmarkComparison
  benchmark_unavailable_reason?: string
  research_evidence_package?: SignalOpsExperimentPackage
  review_queue_sync_status?: SignalOpsReviewQueueSyncStatus | string
  warnings?: string[]
  created_at?: string
  updated_at?: string
  simulation_only?: boolean
  is_real_trade?: boolean
  [key: string]: unknown
}

export interface SignalOpsExperimentValidationState {
  version?: number
  updated_at?: string
  latest_experiment_package_hash?: string
  attempts?: Record<string, SignalOpsExperimentValidationAttempt>
  counts?: Record<string, number>
  simulation_only?: boolean
  is_real_trade?: boolean
  [key: string]: unknown
}

export interface SignalOpsReviewQueueItem {
  id: string
  signal_id: string
  symbol: string
  stock_name?: string
  title: string
  status: SignalOpsStatus | string
  review_decision: SignalOpsReviewDecision
  review_label: string
  priority_score: number
  pending: boolean
  reason: string
  latest_action: string
  latest_order_id?: string | null
  latest_order_updated_at?: string
  decision_card?: SignalOpsDecisionCard
  performance_bucket?: PerformanceBucket
  cleaned_record?: CleanedSignalRecord
  candidate_status?: string
  lifecycle_status?: SignalOpsReviewQueueLifecycleStatus | string
  evidence_quality?: EvidenceQuality | string
  risk_level?: string
  factor_sources?: string[]
  walk_forward_validation?: WalkForwardValidationResult
  strategy_experiment?: StrategyExperiment
  parameter_diff_summary?: SignalOpsParameterDiffSummary
  evidence_package?: Record<string, unknown>
  kline_evidence_package?: KlineEvidencePackage
  stability_evidence_package?: StabilityEvidencePackage
  experiment_package_hash?: string
  walk_forward_run_ids?: Record<string, string>
  benchmark_comparison?: BenchmarkComparison
  research_evidence_package?: SignalOpsExperimentPackage
  experiment_validation_attempt?: SignalOpsExperimentValidationAttempt
  review_allowed?: boolean
  queue_item_id?: string
  experiment_id?: string
  expires_at?: string
  blockers: string[]
  indicators: Array<{
    label: string
    value: string
    tone?: 'default' | 'good' | 'warn' | 'bad'
  }>
  source: string[]
  simulation_only: boolean
  is_real_trade: boolean
  updated_at: string
}

export interface AgentSimulationCaseItem {
  case_id: string
  case_source: string
  operator_type: string
  source_signal_id: string
  source_paper_order_id: string
  run_id?: string | null
  agent_id: string
  audit_id: string
  simulation_only: boolean
  is_real_trade: boolean
  outcome: Record<string, any>
  failure_tags: string[]
  knowledge_candidate_status: string
  created_at: string
  updated_at: string
}

export interface AutoPaperTradingConfig {
  enabled: boolean
  automation_mode: string
  simulation_module: Record<string, any>
  live_module: Record<string, any>
  symbol: string
  stock_name: string
  signal_id?: string | null
  signal_ids: Record<string, string>
  initial_buy_signal: string
  final_sell_signal: string
  initial_buy_signals: Record<string, string>
  final_sell_signals: Record<string, string>
  initial_cash: number
  max_position_ratio: number
  min_order_value: number
  commission_rate: number
  commission_min_fee: number
  commission_min_trade_value: number
  stamp_duty_rate: number
  realtime_interval_seconds: number
  kline_interval_seconds: number
  weekly_monthly_interval_seconds: number
  tick_interval_seconds: number
  min_order_interval_seconds: number
  use_llm: boolean
  max_llm_calls_per_day: number
  min_llm_interval_minutes: number
  auto_fill: boolean
  adaptive_tuning_enabled: boolean
  buy_change_threshold_pct: number
  close_change_threshold_pct: number
  watch_position_ratio: number
  probe_position_ratio: number
  positive_position_ratio: number
  breakout_position_ratio: number
  defensive_position_ratio: number
  existing_position_ratio: number
  strength_follow_position_ratio: number
  factor_adjustments: Record<string, any>
  performance_stats: PerformanceStats
  last_research_review_date: string
  last_research_review: SignalOpsResearchReview
  cleaned_record_history?: CleanedSignalRecord[]
  compressed_observation_history?: Record<string, any>
  review_queue_state?: SignalOpsReviewQueueState
  review_decisions?: SignalOpsReviewDecisionRecord[]
  experiment_validation_state?: SignalOpsExperimentValidationState
  random_validation_state?: SignalOpsReviewQueueState | Record<string, any>
  decision_tree_state?: SignalOpsDecisionTreeState
  updated_at: string
  last_tick_at: string
  last_market_fetch_at: string
  last_kline_fetch_at: string
  last_weekly_monthly_fetch_at: string
  last_llm_at: string
  last_order_at: string
  last_market_fetch_by_symbol: Record<string, string>
  last_kline_fetch_by_symbol: Record<string, string>
  last_weekly_monthly_fetch_by_symbol: Record<string, string>
  last_kline_snapshot_by_symbol: Record<string, Record<string, any>>
  last_order_by_symbol: Record<string, string>
  llm_budget_date: string
  llm_calls_used_today: number
  llm_gate_status: string
  last_llm_close_call_date: string
  last_decision: Record<string, any>
  last_module_evidence: Record<string, any>
  last_portfolio_snapshot: Record<string, any>
  last_tick_result: Record<string, any>
  last_success_at?: string
  last_error: string
  storage_warning?: string
}

export interface UpdateAutoPaperTradingConfigPayload {
  enabled?: boolean
  automation_mode?: string
  simulation_module?: Record<string, any>
  live_module?: Record<string, any>
  symbol?: string
  stock_name?: string
  initial_buy_signal?: string
  final_sell_signal?: string
  initial_buy_signals?: Record<string, string>
  final_sell_signals?: Record<string, string>
  initial_cash?: number
  max_position_ratio?: number
  min_order_value?: number
  commission_rate?: number
  commission_min_fee?: number
  commission_min_trade_value?: number
  stamp_duty_rate?: number
  realtime_interval_seconds?: number
  kline_interval_seconds?: number
  weekly_monthly_interval_seconds?: number
  tick_interval_seconds?: number
  min_order_interval_seconds?: number
  use_llm?: boolean
  max_llm_calls_per_day?: number
  min_llm_interval_minutes?: number
  auto_fill?: boolean
  adaptive_tuning_enabled?: boolean
  buy_change_threshold_pct?: number
  close_change_threshold_pct?: number
  watch_position_ratio?: number
  probe_position_ratio?: number
  positive_position_ratio?: number
  breakout_position_ratio?: number
  defensive_position_ratio?: number
  existing_position_ratio?: number
  strength_follow_position_ratio?: number
}

export interface AutoPaperTradingTickResult {
  status: string
  message: string
  symbol?: string | null
  signal_id?: string | null
  config: AutoPaperTradingConfig
  market_snapshot: Record<string, any>
  kline_snapshot: Record<string, any>
  decision: Record<string, any>
  decision_card?: SignalOpsDecisionCard
  module_evidence?: Record<string, any>
  portfolio_snapshot?: Record<string, any>
  order?: Record<string, any> | null
  portfolio?: Record<string, any> | null
  llm_trace?: Record<string, any> | null
  daily_review?: Record<string, any> | null
  decision_tree_branch?: SignalOpsDecisionTreeBranch
  decision_tree_review?: SignalOpsDecisionTreeReview
  warnings: string[]
  results?: Array<Record<string, any>>
}

export interface AutoPaperTradingCommandPayload {
  symbol: string
  command: 'FORCE_OPEN_BUY' | 'FORCE_CLOSE' | 'REMOVE_SYMBOL' | 'FORCE_CLOSE_AND_REMOVE'
  reason?: string
}

export interface AutoPaperTradingCommandResult {
  status: string
  message: string
  symbol: string
  signal_id?: string | null
  config: AutoPaperTradingConfig
  order?: Record<string, any> | null
  portfolio?: Record<string, any> | null
  warnings: string[]
}

export interface PluginItem {
  plugin_id: string
  version: string
  name: string
  description: string
  agents: Array<Record<string, any>>
  permissions: string[]
  input_schema: Record<string, any>
  output_schema: Record<string, any>
  risk_level: string
  enabled: boolean
  source: string
  lifecycle_status?: string
  archived_at?: string
  archived_by?: string
  upgraded_at?: string
  upgraded_by?: string
  upgrade_from_version?: string
  package_artifact_id?: string
  package_checksum?: string
  package_artifact_verified?: boolean
  package_artifact_storage_path?: string
  package_scan_status?: string
  package_hash_scan_status?: string
  package_external_scan_status?: string
  package_external_scan_provider?: string
  package_retention_expires_at?: string
  package_retention_days?: number
  manifest: Record<string, any>
  created_at: string
  updated_at: string
}

export interface PluginArtifactUploadResult {
  plugin_id: string
  version: string
  artifact_id: string
  artifact_type: string
  source: string
  filename: string
  content_type: string
  size_bytes: number
  checksum: string
  checksum_algorithm: string
  expected_checksum: string
  storage_path: string
  stored_at: string
  stored_by: string
  verified: boolean
  recorded_only: boolean
  hash_scan_status: string
  hash_scan: Record<string, any>
  scan_status: string
  scan_summary: string
  scan_warnings: string[]
  scan: Record<string, any>
  external_scan_status: string
  external_scan_provider: string
  external_scan_required: boolean
  external_scan: Record<string, any>
  retention_days: number
  retention_expires_at: string
  retention_policy: Record<string, any>
  notes: string
}

export interface PluginArtifactCleanupItem {
  plugin_id: string
  artifact_id: string
  storage_path: string
  retention_expires_at: string
  status: string
  exists: boolean
  size_bytes: number
  error: string
  resolved_path?: string
}

export interface PluginArtifactCleanupResult {
  status: string
  dry_run: boolean
  cleanup_at: string
  storage_root: string
  scanned_plugin_count: number
  expired_count: number
  candidate_count: number
  would_delete_count: number
  deleted_count: number
  missing_count: number
  skipped_count: number
  error_count: number
  items: PluginArtifactCleanupItem[]
}

export interface PluginAuditItem {
  audit_id: string
  plugin_id: string
  action: string
  actor: string
  message: string
  payload_json: Record<string, any>
  created_at: string
}

export interface PluginUsageStatsItem {
  plugin_id: string
  window_event_limit: number
  total_audit_events: number
  sandbox_run_count: number
  sandbox_block_count: number
  execute_preview_count: number
  execute_preview_failed_count: number
  validation_count: number
  lifecycle_event_count: number
  action_counts: Record<string, number>
  status_counts: Record<string, number>
  last_action: string
  last_status: string
  last_actor: string
  last_audit_id: string
  last_run_at: string
  last_elapsed_ms: number
  average_elapsed_ms: number
  max_elapsed_ms: number
}

export interface PluginUsageHistoryBucket {
  plugin_id: string
  bucket_start: string
  bucket_label: string
  total_audit_events: number
  sandbox_run_count: number
  sandbox_block_count: number
  execute_preview_count: number
  execute_preview_failed_count: number
  validation_count: number
  lifecycle_event_count: number
  action_counts: Record<string, number>
  status_counts: Record<string, number>
  last_action: string
  last_status: string
  last_actor: string
  last_audit_id: string
  last_run_at: string
  last_elapsed_ms: number
  average_elapsed_ms: number
  max_elapsed_ms: number
}

export interface PluginUsageHistoryResponse {
  generated_at: string
  bucket: string
  days: number
  plugin_count: number
  items: PluginUsageHistoryBucket[]
}

export interface PluginValidateResult {
  plugin_id: string
  valid: boolean
  failures: string[]
  warnings: string[]
  audit_id: string
}

export interface PluginRuntimeSchemaStatus {
  valid: boolean
  input_schema_declared: boolean
  output_schema_declared: boolean
  failures: string[]
}

export interface PluginPermissionSandbox {
  mode: string
  allowed: boolean
  allowed_permissions: string[]
  blocked_permissions: string[]
  code_execution: string
  filesystem_access: string
  network_access: string
}

export interface PluginExecutionSandbox {
  plugin_id: string
  agent_id: string
  mode: string
  allowed: boolean
  hot_reload_allowed: boolean
  execution_kind: string
  code_execution: string
  direct_code_execution: boolean
  filesystem_access: string
  network_access: string
  resource_limits: Record<string, any>
  custom_resource_limits: boolean
  resource_limit_warnings: string[]
  schema_validation: Record<string, any>
  permission_boundary: Record<string, any>
  risk_boundary: Record<string, any>
  audit_required: boolean
  rollback_supported: boolean
  trade_action_hard_block: boolean
  block_reasons: string[]
}

export interface PluginRiskGate {
  risk_level: string
  allowed: boolean
  required_gates: string[]
  forbidden_trade_actions: string[]
  trade_actions_allowed: boolean
  block_reasons: string[]
}

export interface PluginRuntimeAgentPlan {
  plugin_id: string
  plugin_name: string
  agent_id: string
  agent_name: string
  dag_node_id: string
  plan_step: number
  enabled: boolean
  eligible: boolean
  registration_status: string
  dag_registration: Record<string, any>
  input_schema: Record<string, any>
  output_schema: Record<string, any>
  permissions: string[]
  schema_status: PluginRuntimeSchemaStatus
  permission_sandbox: PluginPermissionSandbox
  risk_gate: PluginRiskGate
  execution_sandbox: PluginExecutionSandbox
  validation_failures: string[]
  can_execute_code: boolean
  direct_execution: boolean
}

export interface PluginRuntimePlan {
  generated_at: string
  status: string
  sandbox_status: string
  enabled_plugin_count: number
  enabled_agent_count: number
  registered_dag_node_count: number
  hot_reload_agent_count: number
  resource_summary: Record<string, any>
  agents: PluginRuntimeAgentPlan[]
  forbidden_trade_actions: string[]
  required_gates: string[]
  notes: string[]
}

export interface PluginSandboxRunResult {
  plugin_id: string
  agent_id: string
  status: string
  mode: string
  audit_id: string
  actor: string
  started_at: string
  finished_at: string
  elapsed_ms: number
  output: Record<string, any>
  errors: string[]
  policy: Record<string, any>
}

export interface LinkedProjectRef {
  project: string
  module: string
  path: string
  expected_version: string
  sync_status: string
  note: string
}

export interface ResearchEvidenceLink {
  source_type: string
  source_id: string
  label: string
  quality: string
  reportedQuality?: string | null
  reported_quality?: string | null
  created_at: string
}

export interface ResearchMetricComparisonRow {
  key: string
  label?: string
  baseline?: unknown
  current?: unknown
  delta?: unknown
  quality?: string
  warning?: string
}

export interface ResearchIterationMetrics {
  run_status?: string
  final_action?: string
  quality_score?: number | null
  quality_level?: string | null
  qiam_confidence?: number | null
  dvg_status?: string | null
  engine_verdict?: string
  suggested_feedback_verdict?: string
  confidence?: number
  blocking_reasons?: string[]
  quality_warnings?: string[]
  warnings?: string[]
  comparison?: ResearchMetricComparisonRow[]
  baseline?: Record<string, unknown>
  current?: Record<string, unknown>
  artifact_links?: {
    case_id?: string
    knowledge_item_id?: string
    error_entry_id?: string
    patch_id?: string
    evaluation_id?: string
  }
  [key: string]: unknown
}

export interface ResearchFeedbackEvent {
  event_id: string
  action: string
  verdict: string
  note: string
  reviewer: string
  created_at: string
}

export interface ResearchIteration {
  iteration_id: string
  loop_id: string
  order: number
  status: string
  hypothesis: string
  plan: string
  target_modules: string[]
  linked_run_id?: string | null
  linked_backtest_id?: string | null
  linked_case_id?: string | null
  linked_knowledge_item_id?: string | null
  linked_patch_id?: string | null
  metrics: ResearchIterationMetrics
  evidence_links: ResearchEvidenceLink[]
  feedback_events: ResearchFeedbackEvent[]
  verdict: string
  created_at: string
  updated_at: string
}

export interface ResearchLoop {
  loop_id: string
  title: string
  objective: string
  status: string
  action_target: string
  owner: string
  tags: string[]
  linked_projects: LinkedProjectRef[]
  source: string
  current_iteration_id?: string | null
  iteration_count: number
  created_at: string
  updated_at: string
}

export interface ResearchWorkflowStep {
  key: string
  label: string
  status: string
  ref_id?: string | null
  detail: string
  source: string
  source_timestamp: string
  evidence_strength: string
  evidence_usage: 'review_gate_only' | (string & {})
  simulation_only: boolean
  is_real_trade: boolean
  strong_conclusion_allowed: boolean
  missing_items: string[]
  next_action: string
  next_action_label: string
}

export interface ResearchWorkflowState {
  maturity_score: number
  maturity_level: string
  maturity_label: string
  maturity_reasons: string[]
  stage: string
  next_action: string
  next_action_label: string
  blocking_reasons: string[]
  steps: ResearchWorkflowStep[]
  evidence_strength: 'MEDIUM' | 'LOW' | 'MISSING' | 'PENDING' | 'UNKNOWN' | (string & {})
  evidence_usage: 'review_gate_only' | (string & {})
  simulation_only: boolean
  is_real_trade: boolean
  strong_conclusion_allowed: boolean
}

export interface ResearchLoopDetail {
  loop: ResearchLoop
  iterations: ResearchIteration[]
  workflow_state?: ResearchWorkflowState | null
}

export interface ResearchLoopUpdatePayload {
  title?: string
  objective?: string
  status?: string
  action_target?: string
  owner?: string
  tags?: string[]
  linked_projects?: LinkedProjectRef[]
}

export interface ResearchIterationPatchPayload {
  hypothesis?: string
  plan?: string
  target_modules?: string[]
  status?: string
  verdict?: string
  linked_run_id?: string | null
  linked_backtest_id?: string | null
  linked_case_id?: string | null
  linked_knowledge_item_id?: string | null
  linked_patch_id?: string | null
  metrics?: ResearchIterationMetrics
  evidence_links?: ResearchEvidenceLink[]
}

export interface ResearchTraceSummary {
  trace_id: string
  source: string
  title: string
  status: string
  loop_id?: string | null
  iteration_id?: string | null
  run_id?: string | null
  imported_at: string
  updated_at: string
  summary?: string
  metadata?: Record<string, unknown>
}

export interface ResearchTraceDetail extends ResearchTraceSummary {
  events: Array<Record<string, unknown>>
  artifacts: Array<Record<string, unknown>>
  raw_trace?: Record<string, unknown>
}

export interface ResearchTraceImportPayload {
  source?: string
  title?: string
  loop_id?: string
  iteration_id?: string
  run_id?: string
  trace: Record<string, unknown>
}

export interface ResearchTraceImportResult {
  trace: ResearchTraceDetail
  warnings: string[]
}

export interface ResearchSummary {
  total_loops: number
  active_loops: number
  paused_loops: number
  completed_loops: number
  total_iterations: number
  pending_iterations: number
  accepted_iterations: number
  rejected_iterations: number
  patch_required_iterations: number
  linked_project_count: number
  updated_at: string
}

export interface ResearchVerdictEvidence {
  source_type: string
  source_id: string
  label: string
  quality: string
  reportedQuality?: string | null
  reported_quality?: string | null
  summary: string
  metrics: Record<string, unknown>
  created_at: string
}

export interface ResearchVerdictInputs {
  iteration_id: string
  loop_id: string
  status: string
  current_verdict: string
  engine_verdict: string
  suggested_feedback_verdict: string
  confidence: number
  can_accept_feedback: boolean
  blocking_reasons: string[]
  quality_warnings: string[]
  metrics: ResearchIterationMetrics
  baseline: Record<string, unknown>
  current: Record<string, unknown>
  comparison: ResearchMetricComparisonRow[]
  evidence: ResearchVerdictEvidence[]
  generated_at: string
}

export interface ResearchBacktestVerdictInputsResponse {
  iteration: ResearchIteration
  verdict_inputs: ResearchVerdictInputs
  evidence_usage: 'supporting_only'
  supporting_only: true
  simulation_only: true
  is_real_trade: false
  strong_conclusion_allowed: false
}

export interface ResearchSignalOpsEvidenceResponse {
  iteration: ResearchIteration
  verdict_inputs: ResearchVerdictInputs
  evidence_usage: 'supporting_only'
  supporting_only: true
  simulation_only: true
  is_real_trade: false
  strong_conclusion_allowed: false
}

export type ResearchActionTarget =
  | 'factor'
  | 'model'
  | 'signal'
  | 'risk_rule'
  | 'portfolio_rule'
  | 'execution_rule'
  | 'data_quality_rule'
  | 'prompt_rule'
  | (string & {})

export interface ResearchActionSelection {
  action_target?: ResearchActionTarget
  target?: ResearchActionTarget
  rule_id?: string
  reason?: string
  evidence?: unknown[]
  metrics?: Record<string, unknown>
  [key: string]: unknown
}

export interface ResearchHypothesisDraft {
  draft_id?: string
  title?: string
  hypothesis?: string
  rationale?: string
  reason?: string
  plan?: string | Record<string, unknown>
  experimentPlan?: string | Record<string, unknown>
  experiment_plan?: string | Record<string, unknown>
  action_target?: ResearchActionTarget
  actionTarget?: ResearchActionTarget
  target_modules?: string[]
  targetModules?: string[]
  modules?: string[]
  source?: string
  evidence?: unknown[]
  [key: string]: unknown
}

export interface ResearchHypothesisDraftPayload {
  iteration_id?: string
  context_metrics?: Record<string, unknown>
  use_llm?: boolean
  max_drafts?: number
  reviewer?: string
}

export interface ResearchHypothesisDraftResponse {
  draft_id: string
  loop_id: string
  iteration_id?: string | null
  status: string
  action_selection: ResearchActionSelection
  drafts: ResearchHypothesisDraft[]
  prompt_provenance: Record<string, unknown>
  token_usage: TokenUsageSummary | Record<string, unknown> | null
  llm_status: string
  llm_error?: string | null
  token_usage_link?: string | null
  confirmation_required: boolean
  auto_run_started: boolean
  confirmed_iteration_id?: string | null
  created_at: string
}

export interface ResearchArtifactMaterializeResult {
  iteration: ResearchIteration
  case?: CaseLibraryItem | null
  knowledge_item?: KnowledgeItem | null
  error_entry?: ErrorLedgerItem | null
  patch?: KnowledgePatchItem | null
  evaluation?: EvaluationRunItem | null
  provenance_chain: string[]
  warnings: string[]
}
