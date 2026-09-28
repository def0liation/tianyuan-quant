import { request } from './httpClient'
import {
  CaseLibraryItem,
  CaseLibrarySummary,
  ReviewTagItem,
  ReviewTagSummary,
  ErrorLedgerItem,
  ErrorLedgerSummary,
  KnowledgePatchItem,
  KnowledgePatchSummary,
  EvaluationRunItem,
  KnowledgeVersionItem,
  CreateKnowledgeVersionDraftPayload,
  StrategyExperimentReport,
  VersionDiffResult,
  RollbackResult,
} from '../types'

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
  const value = record[key]
  if (value !== undefined && value !== null && typeof value !== 'string') {
    throw new Error(`Unexpected ${label} response: invalid ${key}`)
  }
}

function assertOptionalNumber(record: Record<string, unknown>, key: string, label: string) {
  const value = record[key]
  if (value !== undefined && value !== null && (typeof value !== 'number' || Number.isNaN(value))) {
    throw new Error(`Unexpected ${label} response: invalid ${key}`)
  }
}

function assertStringArray(value: unknown, label: string) {
  ensureArray(value, label).forEach((item, index) => {
    if (typeof item !== 'string') {
      throw new Error(`Unexpected ${label} response: invalid item ${index}`)
    }
  })
}

function assertNumberRecord(value: unknown, label: string) {
  const record = ensureRecord(value, label)
  Object.entries(record).forEach(([key, item]) => {
    if (typeof item !== 'number' || Number.isNaN(item)) {
      throw new Error(`Unexpected ${label} response: invalid ${key}`)
    }
  })
}

function assertRecordArray(value: unknown, label: string) {
  ensureArray(value, label).forEach((item) => ensureRecord(item, label))
}

function assertOptionalRecord(record: Record<string, unknown>, key: string, label: string) {
  const value = record[key]
  if (value !== undefined && value !== null) {
    ensureRecord(value, `${label} ${key}`)
  }
}

function assertNullableBoolean(record: Record<string, unknown>, key: string, label: string) {
  const value = record[key]
  if (value !== null && typeof value !== 'boolean') {
    throw new Error(`Unexpected ${label} response: missing ${key}`)
  }
}

function assertNullableString(record: Record<string, unknown>, key: string, label: string) {
  const value = record[key]
  if (value !== null && typeof value !== 'string') {
    throw new Error(`Unexpected ${label} response: missing ${key}`)
  }
}

function isStrongEvidenceValue(value: unknown) {
  const normalized = String(value || '').toUpperCase()
  return (
    normalized === 'HIGH'
    || normalized === 'RESEARCH_GRADE'
    || normalized === 'PRIMARY_EVIDENCE_READY'
    || normalized.includes('STRONG')
    || normalized.includes('PRIMARY')
  )
}

const KNOWLEDGE_VERSION_APPROVAL_REF_TYPES = new Set(['backtest', 'evaluation', 'regression_waiver', 'verdict'])

function assertKnowledgeVersionApprovalEvidenceRef(value: unknown, index: number) {
  const ref = ensureRecord(value, `knowledge version evidence_ref ${index}`)
  requireString(ref, 'source_type', 'knowledge version evidence_ref')
  requireString(ref, 'source_id', 'knowledge version evidence_ref')

  const sourceType = String(ref.source_type).trim()
  const sourceId = String(ref.source_id).trim()
  if (!KNOWLEDGE_VERSION_APPROVAL_REF_TYPES.has(sourceType) || !sourceId) {
    throw new Error('Unexpected knowledge version approval evidence_ref response: source must be a validated review artifact')
  }
  assertOptionalString(ref, 'summary', 'knowledge version evidence_ref')
  assertOptionalRecord(ref, 'metrics', 'knowledge version evidence_ref')

  if (ref.evidence_usage !== undefined && ref.evidence_usage !== null) {
    if (ref.evidence_usage !== 'review_gate_only' || isStrongEvidenceValue(ref.evidence_usage)) {
      throw new Error('Unexpected knowledge version approval evidence_ref response: evidence usage must stay review_gate_only')
    }
  }
  if (ref.evidence_strength !== undefined && ref.evidence_strength !== null) {
    if (typeof ref.evidence_strength !== 'string' || isStrongEvidenceValue(ref.evidence_strength)) {
      throw new Error('Unexpected knowledge version approval evidence_ref response: evidence strength must not become strong')
    }
  }
  if (ref.simulation_only !== undefined && ref.simulation_only !== true) {
    throw new Error('Unexpected knowledge version approval evidence_ref response: simulation_only must stay true')
  }
  if (ref.is_real_trade !== undefined && ref.is_real_trade !== false) {
    throw new Error('Unexpected knowledge version approval evidence_ref response: is_real_trade must stay false')
  }
  if (ref.strong_conclusion_allowed === true) {
    throw new Error('Unexpected knowledge version approval evidence_ref response: strong conclusions are not allowed')
  }
}

function assertCaseLibraryBoundary(item: Record<string, unknown>) {
  requireString(item, 'evidence_usage', 'case library item')
  requireString(item, 'evidence_strength', 'case library item')
  requireBoolean(item, 'simulation_only', 'case library item')
  requireBoolean(item, 'is_real_trade', 'case library item')
  requireBoolean(item, 'strong_conclusion_allowed', 'case library item')

  const evidenceUsage = String(item.evidence_usage)
  if (item.strong_conclusion_allowed === true || isStrongEvidenceValue(item.evidence_strength) || isStrongEvidenceValue(evidenceUsage)) {
    throw new Error('Unexpected case library item response: case evidence must not become a strong conclusion')
  }
  if (evidenceUsage !== 'supporting_only' || item.simulation_only !== true || item.is_real_trade !== false) {
    throw new Error('Unexpected case library item response: case library must stay simulation-only supporting evidence')
  }
}

function assertCaseLibraryItem(value: unknown): CaseLibraryItem {
  const item = ensureRecord(value, 'case library item')
  requireString(item, 'case_id', 'case library item')
  requireString(item, 'run_id', 'case library item')
  requireString(item, 'audit_id', 'case library item')
  requireString(item, 'symbol', 'case library item')
  requireString(item, 'stock_name', 'case library item')
  requireString(item, 'task_type', 'case library item')
  requireString(item, 'run_mode', 'case library item')
  requireString(item, 'final_action', 'case library item')
  assertNullableBoolean(item, 'final_action_correct', 'case library item')
  assertNullableBoolean(item, 'conclusion_correct', 'case library item')
  requireString(item, 'data_sufficiency', 'case library item')
  requireString(item, 'optimism_bias', 'case library item')
  assertStringArray(item.key_lessons, 'case library item key_lessons')
  requireString(item, 'market_context', 'case library item')
  assertStringArray(item.tags, 'case library item tags')
  assertNullableString(item, 'reviewer', 'case library item')
  requireString(item, 'review_note', 'case library item')
  requireString(item, 'review_status', 'case library item')
  assertCaseLibraryBoundary(item)
  requireString(item, 'created_at', 'case library item')
  requireString(item, 'updated_at', 'case library item')
  return value as CaseLibraryItem
}

function assertCaseLibraryList(value: unknown): CaseLibraryItem[] {
  return ensureArray(value, 'case library list').map(assertCaseLibraryItem)
}

function assertCaseLibrarySummary(value: unknown): CaseLibrarySummary {
  const summary = ensureRecord(value, 'case library summary')
  requireNumber(summary, 'total', 'case library summary')
  requireNumber(summary, 'pending', 'case library summary')
  requireNumber(summary, 'reviewed', 'case library summary')
  requireNumber(summary, 'correct_conclusions', 'case library summary')
  requireNumber(summary, 'accuracy_rate', 'case library summary')
  return value as CaseLibrarySummary
}

function assertReviewTagItem(value: unknown): ReviewTagItem {
  const item = ensureRecord(value, 'review tag item')
  requireString(item, 'tag_id', 'review tag item')
  requireString(item, 'case_id', 'review tag item')
  requireString(item, 'run_id', 'review tag item')
  requireString(item, 'tag_type', 'review tag item')
  requireString(item, 'tag_value', 'review tag item')
  requireString(item, 'severity', 'review tag item')
  requireString(item, 'description', 'review tag item')
  assertNullableString(item, 'node', 'review tag item')
  requireString(item, 'reviewer', 'review tag item')
  requireString(item, 'created_at', 'review tag item')
  return value as ReviewTagItem
}

function assertReviewTagList(value: unknown): ReviewTagItem[] {
  return ensureArray(value, 'review tag list').map(assertReviewTagItem)
}

function assertReviewTagSummary(value: unknown): ReviewTagSummary {
  const summary = ensureRecord(value, 'review tag summary')
  requireNumber(summary, 'total', 'review tag summary')
  assertNumberRecord(summary.by_type, 'review tag summary by_type')
  assertNumberRecord(summary.by_severity, 'review tag summary by_severity')
  return value as ReviewTagSummary
}

function assertErrorLedgerBoundary(item: Record<string, unknown>) {
  requireString(item, 'evidence_usage', 'error ledger item')
  requireString(item, 'evidence_strength', 'error ledger item')
  requireBoolean(item, 'simulation_only', 'error ledger item')
  requireBoolean(item, 'is_real_trade', 'error ledger item')
  requireBoolean(item, 'strong_conclusion_allowed', 'error ledger item')
  assertNullableBoolean(item, 'reported_simulation_only', 'error ledger item')
  assertNullableBoolean(item, 'reported_is_real_trade', 'error ledger item')

  const evidenceUsage = String(item.evidence_usage)
  if (item.strong_conclusion_allowed === true || isStrongEvidenceValue(item.evidence_strength) || isStrongEvidenceValue(evidenceUsage)) {
    throw new Error('Unexpected error ledger item response: error evidence must not become a strong conclusion')
  }
  if (evidenceUsage !== 'review_gate_only' || item.simulation_only !== true || item.is_real_trade !== false) {
    throw new Error('Unexpected error ledger item response: error ledger review must stay simulation-only')
  }
}

function assertErrorLedgerItem(value: unknown): ErrorLedgerItem {
  const item = ensureRecord(value, 'error ledger item')
  requireString(item, 'entry_id', 'error ledger item')
  requireString(item, 'run_id', 'error ledger item')
  requireString(item, 'audit_id', 'error ledger item')
  assertNullableString(item, 'node', 'error ledger item')
  requireString(item, 'error_type', 'error ledger item')
  requireString(item, 'error_reason', 'error ledger item')
  requireNumber(item, 'repeated_count', 'error ledger item')
  requireBoolean(item, 'patch_required', 'error ledger item')
  assertNullableString(item, 'patch_candidate_id', 'error ledger item')
  ensureRecord(item.attribution, 'error ledger attribution')
  requireString(item, 'status', 'error ledger item')
  assertErrorLedgerBoundary(item)
  assertNullableString(item, 'resolved_at', 'error ledger item')
  requireString(item, 'created_at', 'error ledger item')
  requireString(item, 'updated_at', 'error ledger item')
  return value as ErrorLedgerItem
}

function assertErrorLedgerList(value: unknown): ErrorLedgerItem[] {
  return ensureArray(value, 'error ledger list').map(assertErrorLedgerItem)
}

function assertErrorLedgerSummary(value: unknown): ErrorLedgerSummary {
  const summary = ensureRecord(value, 'error ledger summary')
  requireNumber(summary, 'total', 'error ledger summary')
  requireNumber(summary, 'open', 'error ledger summary')
  requireNumber(summary, 'resolved', 'error ledger summary')
  assertNumberRecord(summary.by_type, 'error ledger summary by_type')
  assertNumberRecord(summary.by_node, 'error ledger summary by_node')
  return value as ErrorLedgerSummary
}

function assertKnowledgePatchBoundary(item: Record<string, unknown>) {
  requireString(item, 'evidence_usage', 'knowledge patch item')
  requireString(item, 'evidence_strength', 'knowledge patch item')
  requireBoolean(item, 'simulation_only', 'knowledge patch item')
  requireBoolean(item, 'is_real_trade', 'knowledge patch item')
  requireBoolean(item, 'strong_conclusion_allowed', 'knowledge patch item')

  const evidenceUsage = String(item.evidence_usage)
  if (item.strong_conclusion_allowed === true || isStrongEvidenceValue(item.evidence_strength) || isStrongEvidenceValue(evidenceUsage)) {
    throw new Error('Unexpected knowledge patch item response: patch evidence must not become a strong conclusion')
  }
  if (evidenceUsage !== 'review_gate_only' || item.simulation_only !== true || item.is_real_trade !== false) {
    throw new Error('Unexpected knowledge patch item response: patch review must stay simulation-only')
  }
}

function assertKnowledgePatchItem(value: unknown): KnowledgePatchItem {
  const item = ensureRecord(value, 'knowledge patch item')
  requireString(item, 'patch_id', 'knowledge patch item')
  assertNullableString(item, 'source_error_id', 'knowledge patch item')
  assertNullableString(item, 'source_case_id', 'knowledge patch item')
  requireString(item, 'title', 'knowledge patch item')
  requireString(item, 'reason', 'knowledge patch item')
  assertStringArray(item.affected_modules, 'knowledge patch affected_modules')
  ensureRecord(item.patch_content, 'knowledge patch content')
  requireString(item, 'risk_note', 'knowledge patch item')
  requireString(item, 'rollback_plan', 'knowledge patch item')
  requireBoolean(item, 'backtest_required', 'knowledge patch item')
  ensureRecord(item.backtest_result, 'knowledge patch backtest_result')
  requireString(item, 'approval_status', 'knowledge patch item')
  assertNullableString(item, 'approved_by', 'knowledge patch item')
  assertNullableString(item, 'approved_at', 'knowledge patch item')
  assertKnowledgePatchBoundary(item)
  requireString(item, 'created_at', 'knowledge patch item')
  requireString(item, 'updated_at', 'knowledge patch item')
  return value as KnowledgePatchItem
}

function assertKnowledgePatchList(value: unknown): KnowledgePatchItem[] {
  return ensureArray(value, 'knowledge patch list').map(assertKnowledgePatchItem)
}

function assertKnowledgePatchSummary(value: unknown): KnowledgePatchSummary {
  const summary = ensureRecord(value, 'knowledge patch summary')
  requireNumber(summary, 'total', 'knowledge patch summary')
  requireNumber(summary, 'candidate', 'knowledge patch summary')
  requireNumber(summary, 'approved', 'knowledge patch summary')
  requireNumber(summary, 'rejected', 'knowledge patch summary')
  return value as KnowledgePatchSummary
}

function assertStrategyExperimentMetrics(value: unknown) {
  const metrics = ensureRecord(value, 'strategy experiment metrics')
  assertOptionalNumber(metrics, 'win_rate', 'strategy experiment metrics')
  assertOptionalNumber(metrics, 'max_drawdown', 'strategy experiment metrics')
  assertOptionalNumber(metrics, 'misjudge_rate', 'strategy experiment metrics')
  assertOptionalNumber(metrics, 'manual_review_pass_rate', 'strategy experiment metrics')
  assertOptionalNumber(metrics, 'risk_trigger_rate', 'strategy experiment metrics')
  assertOptionalRecord(metrics, 'sample_window', 'strategy experiment metrics')
}

function assertStrategyExperimentBoundary(report: Record<string, unknown>) {
  requireString(report, 'evidence_usage', 'strategy experiment report')
  requireString(report, 'evidence_strength', 'strategy experiment report')
  requireBoolean(report, 'simulation_only', 'strategy experiment report')
  requireBoolean(report, 'is_real_trade', 'strategy experiment report')
  requireBoolean(report, 'strong_conclusion_allowed', 'strategy experiment report')

  if (
    report.strong_conclusion_allowed === true
    || isStrongEvidenceValue(report.evidence_strength)
    || isStrongEvidenceValue(report.evidence_usage)
  ) {
    throw new Error('Unexpected strategy experiment report response: strategy experiment evidence must not become a strong conclusion')
  }
  if (report.evidence_usage !== 'review_gate_only' || report.simulation_only !== true || report.is_real_trade !== false) {
    throw new Error('Unexpected strategy experiment report response: strategy experiment review must stay simulation-only')
  }
}

function assertStrategyExperimentReport(value: unknown): StrategyExperimentReport {
  const report = ensureRecord(value, 'strategy experiment report')
  requireString(report, 'experiment_id', 'strategy experiment report')
  requireString(report, 'hypothesis', 'strategy experiment report')
  requireNumber(report, 'strategy_count', 'strategy experiment report')
  requireString(report, 'baseline_config_id', 'strategy experiment report')
  requireString(report, 'winner_config_id', 'strategy experiment report')
  ensureRecord(report.sample_window, 'strategy experiment sample_window')
  const metrics = ensureRecord(report.metrics_by_strategy, 'strategy experiment metrics_by_strategy')
  Object.values(metrics).forEach(assertStrategyExperimentMetrics)
  assertRecordArray(report.comparisons, 'strategy experiment comparisons')
  requireString(report, 'summary', 'strategy experiment report')
  assertStrategyExperimentBoundary(report)
  requireString(report, 'created_at', 'strategy experiment report')
  return value as StrategyExperimentReport
}

function assertEvaluationSandboxBoundary(item: Record<string, unknown>) {
  requireString(item, 'evidence_usage', 'evaluation run item')
  requireString(item, 'evidence_strength', 'evaluation run item')
  requireBoolean(item, 'simulation_only', 'evaluation run item')
  requireBoolean(item, 'is_real_trade', 'evaluation run item')
  requireBoolean(item, 'strong_conclusion_allowed', 'evaluation run item')

  if (item.simulation_only !== true || item.is_real_trade !== false) {
    throw new Error('Unexpected evaluation run item response: evaluation sandbox must stay simulation-only')
  }
  if (
    item.strong_conclusion_allowed === true
    || isStrongEvidenceValue(item.evidence_strength)
    || isStrongEvidenceValue(item.evidence_usage)
  ) {
    throw new Error('Unexpected evaluation run item response: evaluation evidence must not become a strong conclusion')
  }
}

function assertEvaluationRunItem(value: unknown): EvaluationRunItem {
  const item = ensureRecord(value, 'evaluation run item')
  requireString(item, 'eval_id', 'evaluation run item')
  requireString(item, 'patch_id', 'evaluation run item')
  requireString(item, 'status', 'evaluation run item')
  requireNumber(item, 'total_cases', 'evaluation run item')
  requireNumber(item, 'passed_cases', 'evaluation run item')
  requireNumber(item, 'improved_cases', 'evaluation run item')
  requireNumber(item, 'regressed_cases', 'evaluation run item')
  requireNumber(item, 'unchanged_cases', 'evaluation run item')
  requireNumber(item, 'pass_rate', 'evaluation run item')
  requireNumber(item, 'improvement_rate', 'evaluation run item')
  requireNumber(item, 'elapsed_ms', 'evaluation run item')
  assertRecordArray(item.per_case_results, 'evaluation run per_case_results')
  requireString(item, 'summary', 'evaluation run item')
  if (item.strategy_experiment_report !== undefined && item.strategy_experiment_report !== null) {
    assertStrategyExperimentReport(item.strategy_experiment_report)
  }
  assertEvaluationSandboxBoundary(item)
  assertNullableString(item, 'error', 'evaluation run item')
  requireString(item, 'created_at', 'evaluation run item')
  requireString(item, 'updated_at', 'evaluation run item')
  return value as EvaluationRunItem
}

function assertEvaluationRunList(value: unknown): EvaluationRunItem[] {
  return ensureArray(value, 'evaluation run list').map(assertEvaluationRunItem)
}

function assertPostPublishRegressionBoundary(report: Record<string, unknown>) {
  requireString(report, 'evidence_usage', 'post-publish regression report')
  requireString(report, 'evidence_strength', 'post-publish regression report')
  requireBoolean(report, 'simulation_only', 'post-publish regression report')
  requireBoolean(report, 'is_real_trade', 'post-publish regression report')
  requireBoolean(report, 'strong_conclusion_allowed', 'post-publish regression report')

  const evidenceUsage = String(report.evidence_usage)
  if (
    report.strong_conclusion_allowed === true
    || isStrongEvidenceValue(report.evidence_strength)
    || isStrongEvidenceValue(evidenceUsage)
  ) {
    throw new Error('Unexpected post-publish regression report response: regression evidence must not become a strong conclusion')
  }
  if (evidenceUsage !== 'review_gate_only' || report.simulation_only !== true || report.is_real_trade !== false) {
    throw new Error('Unexpected post-publish regression report response: regression review must stay simulation-only')
  }
}

function assertPostPublishRegressionReport(value: unknown) {
  const report = ensureRecord(value, 'post-publish regression report')
  assertOptionalString(report, 'report_id', 'post-publish regression report')
  assertOptionalString(report, 'version_id', 'post-publish regression report')
  assertOptionalNumber(report, 'version_number', 'post-publish regression report')
  assertOptionalString(report, 'status', 'post-publish regression report')
  assertOptionalString(report, 'trigger', 'post-publish regression report')
  assertOptionalString(report, 'performed_by', 'post-publish regression report')
  assertOptionalString(report, 'generated_at', 'post-publish regression report')
  for (const key of [
    'representative_case_count',
    'active_patch_count',
    'total_checks',
    'improved_cases',
    'regressed_cases',
    'unchanged_cases',
    'review_required_cases',
    'improvement_rate',
    'regression_rate',
    'review_required_rate',
  ]) {
    assertOptionalNumber(report, key, 'post-publish regression report')
  }
  if (report.affected_modules !== undefined && report.affected_modules !== null) {
    assertStringArray(report.affected_modules, 'post-publish regression affected_modules')
  }
  if (report.warnings !== undefined && report.warnings !== null) {
    assertStringArray(report.warnings, 'post-publish regression warnings')
  }
  if (report.quality_warnings !== undefined && report.quality_warnings !== null) {
    assertStringArray(report.quality_warnings, 'post-publish regression quality_warnings')
  }
  assertOptionalRecord(report, 'case_set_quality', 'post-publish regression report')
  assertOptionalRecord(report, 'case_set_quality_policy', 'post-publish regression report')
  assertOptionalRecord(report, 'knowledge_impact', 'post-publish regression report')
  if (report.per_patch !== undefined && report.per_patch !== null) {
    assertRecordArray(report.per_patch, 'post-publish regression per_patch')
  }
  assertPostPublishRegressionBoundary(report)
  assertOptionalString(report, 'summary', 'post-publish regression report')
}

function assertApprovalRecord(value: unknown) {
  const record = ensureRecord(value, 'knowledge version approval_record')
  if (record.evidence_refs !== undefined && record.evidence_refs !== null) {
    ensureArray(record.evidence_refs, 'knowledge version evidence_refs').forEach((ref, index) => {
      assertKnowledgeVersionApprovalEvidenceRef(ref, index)
    })
  }
  if (record.regression_waiver !== undefined && record.regression_waiver !== null) {
    const waiver = ensureRecord(record.regression_waiver, 'knowledge version regression waiver')
    assertOptionalString(waiver, 'policy_id', 'knowledge version regression waiver')
    assertOptionalString(waiver, 'status', 'knowledge version regression waiver')
    assertOptionalString(waiver, 'approval_id', 'knowledge version regression waiver')
    assertOptionalString(waiver, 'reason', 'knowledge version regression waiver')
    assertOptionalString(waiver, 'approved_by', 'knowledge version regression waiver')
    assertOptionalString(waiver, 'approver_role', 'knowledge version regression waiver')
    assertOptionalString(waiver, 'approved_at', 'knowledge version regression waiver')
    assertOptionalString(waiver, 'evaluation_id', 'knowledge version regression waiver')
    assertOptionalNumber(waiver, 'regressed_cases', 'knowledge version regression waiver')
    assertOptionalString(waiver, 'mode', 'knowledge version regression waiver')
  }
}

function assertKnowledgeVersionBoundary(item: Record<string, unknown>) {
  requireString(item, 'evidence_usage', 'knowledge version item')
  requireString(item, 'evidence_strength', 'knowledge version item')
  requireBoolean(item, 'simulation_only', 'knowledge version item')
  requireBoolean(item, 'is_real_trade', 'knowledge version item')
  requireBoolean(item, 'strong_conclusion_allowed', 'knowledge version item')

  const evidenceUsage = String(item.evidence_usage)
  if (
    item.strong_conclusion_allowed === true
    || isStrongEvidenceValue(item.evidence_strength)
    || isStrongEvidenceValue(evidenceUsage)
  ) {
    throw new Error('Unexpected knowledge version item response: version evidence must not become a strong conclusion')
  }
  if (evidenceUsage !== 'review_gate_only' || item.simulation_only !== true || item.is_real_trade !== false) {
    throw new Error('Unexpected knowledge version item response: version review must stay simulation-only')
  }
}

function assertKnowledgeVersionItem(value: unknown): KnowledgeVersionItem {
  const item = ensureRecord(value, 'knowledge version item')
  requireString(item, 'version_id', 'knowledge version item')
  requireNumber(item, 'version_number', 'knowledge version item')
  requireString(item, 'version_label', 'knowledge version item')
  ensureRecord(item.snapshot, 'knowledge version snapshot')
  assertStringArray(item.active_patches, 'knowledge version active_patches')
  assertStringArray(item.active_rules, 'knowledge version active_rules')
  ensureRecord(item.patch_delta, 'knowledge version patch_delta')
  assertNullableString(item, 'source_patch_id', 'knowledge version item')
  assertOptionalString(item, 'source_run_id', 'knowledge version item')
  assertOptionalString(item, 'source_case_id', 'knowledge version item')
  assertOptionalString(item, 'source_evaluation_id', 'knowledge version item')
  assertOptionalString(item, 'source_verdict_id', 'knowledge version item')
  assertOptionalString(item, 'scope', 'knowledge version item')
  assertOptionalString(item, 'risk_boundary', 'knowledge version item')
  if (item.approval_record !== undefined && item.approval_record !== null) {
    assertApprovalRecord(item.approval_record)
  }
  assertOptionalRecord(item, 'rollback_impact', 'knowledge version item')
  if (item.post_publish_regression !== undefined && item.post_publish_regression !== null) {
    assertPostPublishRegressionReport(item.post_publish_regression)
  }
  assertOptionalString(item, 'status', 'knowledge version item')
  assertKnowledgeVersionBoundary(item)
  requireString(item, 'created_by', 'knowledge version item')
  requireString(item, 'description', 'knowledge version item')
  requireString(item, 'created_at', 'knowledge version item')
  return value as KnowledgeVersionItem
}

function assertKnowledgeVersionList(value: unknown): KnowledgeVersionItem[] {
  return ensureArray(value, 'knowledge version list').map(assertKnowledgeVersionItem)
}

function assertVersionDiffResult(value: unknown): VersionDiffResult {
  const result = ensureRecord(value, 'knowledge version diff result')
  ensureRecord(result.version_a, 'knowledge version diff version_a')
  ensureRecord(result.version_b, 'knowledge version diff version_b')
  assertStringArray(result.patches_added, 'knowledge version diff patches_added')
  assertStringArray(result.patches_removed, 'knowledge version diff patches_removed')
  assertStringArray(result.rules_added, 'knowledge version diff rules_added')
  assertStringArray(result.rules_removed, 'knowledge version diff rules_removed')
  requireNumber(result, 'patch_count_diff', 'knowledge version diff result')
  return value as VersionDiffResult
}

function assertRollbackResult(value: unknown): RollbackResult {
  const result = ensureRecord(value, 'knowledge version rollback result')
  assertKnowledgeVersionItem(result.rollback_target)
  assertKnowledgeVersionItem(result.new_version)
  requireNumber(result, 'restored_patches', 'knowledge version rollback result')
  return value as RollbackResult
}

function assertDeleteResult(value: unknown): { deleted: string } {
  const result = ensureRecord(value, 'delete result')
  requireString(result, 'deleted', 'delete result')
  return value as { deleted: string }
}

export function getCaseLibrarySummary() {
  return request<unknown>('/case-library/summary').then(assertCaseLibrarySummary)
}

export function getCases(filters: {
  symbol?: string
  task_type?: string
  review_status?: string
  limit?: number
  offset?: number
} = {}) {
  const params = new URLSearchParams()
  if (filters.symbol) params.set('symbol', filters.symbol)
  if (filters.task_type) params.set('task_type', filters.task_type)
  if (filters.review_status) params.set('review_status', filters.review_status)
  if (filters.limit) params.set('limit', String(filters.limit))
  if (filters.offset) params.set('offset', String(filters.offset))
  const query = params.toString()
  return request<unknown>(`/case-library/cases${query ? `?${query}` : ''}`).then(assertCaseLibraryList)
}

export function getCase(caseId: string) {
  return request<unknown>(`/case-library/cases/${caseId}`).then(assertCaseLibraryItem)
}

export function createCase(runId: string, reviewer = 'system') {
  return request<unknown>('/case-library/cases', {
    method: 'POST',
    body: JSON.stringify({ run_id: runId, reviewer }),
  }).then(assertCaseLibraryItem)
}

export function updateCaseReview(
  caseId: string,
  payload: {
    final_action_correct?: boolean
    conclusion_correct?: boolean
    data_sufficiency?: string
    optimism_bias?: string
    key_lessons?: string[]
    market_context?: string
    tags?: string[]
    reviewer?: string
    review_note?: string
    review_status?: string
  }
) {
  return request<unknown>(`/case-library/cases/${caseId}/review`, {
    method: 'POST',
    body: JSON.stringify(payload),
  }).then(assertCaseLibraryItem)
}

export function getReviewTagSummary() {
  return request<unknown>('/case-library/tags/summary').then(assertReviewTagSummary)
}

export function getReviewTags(filters: { case_id?: string; tag_type?: string; limit?: number } = {}) {
  const params = new URLSearchParams()
  if (filters.case_id) params.set('case_id', filters.case_id)
  if (filters.tag_type) params.set('tag_type', filters.tag_type)
  if (filters.limit) params.set('limit', String(filters.limit))
  const query = params.toString()
  return request<unknown>(`/case-library/tags${query ? `?${query}` : ''}`).then(assertReviewTagList)
}

export function createReviewTag(
  caseId: string,
  payload: {
    tag_type: string
    tag_value: string
    severity?: string
    description?: string
    node?: string
    reviewer?: string
  }
) {
  return request<unknown>(`/case-library/cases/${caseId}/tags`, {
    method: 'POST',
    body: JSON.stringify(payload),
  }).then(assertReviewTagItem)
}

export function getErrorLedgerSummary() {
  return request<unknown>('/case-library/error-ledger/summary').then(assertErrorLedgerSummary)
}

export function getErrorEntries(filters: {
  status?: string
  error_type?: string
  node?: string
  limit?: number
} = {}) {
  const params = new URLSearchParams()
  if (filters.status) params.set('status', filters.status)
  if (filters.error_type) params.set('error_type', filters.error_type)
  if (filters.node) params.set('node', filters.node)
  if (filters.limit) params.set('limit', String(filters.limit))
  const query = params.toString()
  return request<unknown>(`/case-library/error-ledger${query ? `?${query}` : ''}`).then(assertErrorLedgerList)
}

export function createErrorEntry(payload: {
  node?: string
  error_type: string
  error_reason?: string
  repeated_count?: number
  patch_required?: boolean
  attribution?: Record<string, any>
}) {
  return request<unknown>('/case-library/error-ledger', {
    method: 'POST',
    body: JSON.stringify(payload),
  }).then(assertErrorLedgerItem)
}

export function updateErrorEntry(
  entryId: string,
  payload: {
    status?: string
    patch_candidate_id?: string
    repeated_count?: number
  }
) {
  return request<unknown>(`/case-library/error-ledger/${entryId}`, {
    method: 'POST',
    body: JSON.stringify(payload),
  }).then(assertErrorLedgerItem)
}

export function getKnowledgePatchSummary() {
  return request<unknown>('/case-library/patches/summary').then(assertKnowledgePatchSummary)
}

export function getKnowledgePatches(filters: { status?: string; limit?: number } = {}) {
  const params = new URLSearchParams()
  if (filters.status) params.set('status', filters.status)
  if (filters.limit) params.set('limit', String(filters.limit))
  const query = params.toString()
  return request<unknown>(`/case-library/patches${query ? `?${query}` : ''}`).then(assertKnowledgePatchList)
}

export function createKnowledgePatch(payload: {
  title: string
  reason?: string
  affected_modules?: string[]
  patch_content?: Record<string, any>
  source_error_id?: string
  source_case_id?: string
}) {
  return request<unknown>('/case-library/patches', {
    method: 'POST',
    body: JSON.stringify(payload),
  }).then(assertKnowledgePatchItem)
}

export function reviewKnowledgePatch(
  patchId: string,
  payload: {
    action: 'APPROVE' | 'REJECT' | 'ARCHIVE'
    reviewer?: string
    note?: string
  }
) {
  return request<unknown>(`/case-library/patches/${patchId}/review`, {
    method: 'POST',
    body: JSON.stringify(payload),
  }).then(assertKnowledgePatchItem)
}

export function updatePatchBacktest(patchId: string, backtestResult: Record<string, any>) {
  return request<unknown>(`/case-library/patches/${patchId}/backtest`, {
    method: 'POST',
    body: JSON.stringify({ backtest_result: backtestResult }),
  }).then(assertKnowledgePatchItem)
}

export function runPatchEvaluation(patchId: string, force = false) {
  return request<unknown>(`/case-library/patches/${patchId}/evaluate`, {
    method: 'POST',
    body: JSON.stringify({ force }),
  }).then(assertEvaluationRunItem)
}

export function runPatchStrategyExperiment(
  patchId: string,
  payload: {
    hypothesis: string
    strategy_configs: Array<Record<string, any>>
    sample_window?: Record<string, any>
  }
) {
  return request<unknown>(`/case-library/patches/${patchId}/strategy-experiment`, {
    method: 'POST',
    body: JSON.stringify(payload),
  }).then(assertStrategyExperimentReport)
}

export function getEvaluation(evalId: string) {
  return request<unknown>(`/case-library/evaluations/${evalId}`).then(assertEvaluationRunItem)
}

export function getEvaluations(patchId?: string, limit = 20) {
  const params = new URLSearchParams()
  if (patchId) params.set('patch_id', patchId)
  params.set('limit', String(limit))
  return request<unknown>(`/case-library/evaluations?${params.toString()}`).then(assertEvaluationRunList)
}

export function getKnowledgeVersions(limit = 20) {
  return request<unknown>(`/case-library/knowledge-versions?limit=${limit}`).then(assertKnowledgeVersionList)
}

function sanitizeDirectDraftApprovalRecord(
  approvalRecord: CreateKnowledgeVersionDraftPayload['approval_record'] = {}
) {
  const record = { ...approvalRecord } as Record<string, unknown>
  delete record.evidence_refs
  return record
}

export function createKnowledgeVersion(payload: CreateKnowledgeVersionDraftPayload = {}) {
  return request<unknown>('/case-library/knowledge-versions', {
    method: 'POST',
    body: JSON.stringify({
      description: payload.description ?? '',
      scope: payload.scope ?? 'knowledge_base',
      risk_boundary: payload.risk_boundary ?? '',
      approval_record: sanitizeDirectDraftApprovalRecord(payload.approval_record),
      rollback_impact: payload.rollback_impact ?? {},
      status: 'draft',
    }),
  }).then(assertKnowledgeVersionItem)
}

export function getKnowledgeVersionDiff(verA: string, verB: string) {
  return request<unknown>(`/case-library/knowledge-versions/${verA}/diff/${verB}`).then(assertVersionDiffResult)
}

export function rerunKnowledgeVersionRegression(versionId: string) {
  return request<unknown>(`/case-library/knowledge-versions/${versionId}/regression`, {
    method: 'POST',
  }).then(assertKnowledgeVersionItem)
}

export function rollbackKnowledgeVersion(versionId: string) {
  return request<unknown>(`/case-library/knowledge-versions/${versionId}/rollback`, {
    method: 'POST',
    body: JSON.stringify({ performed_by: 'human' }),
  }).then(assertRollbackResult)
}

export function approvePatchWithEvaluation(
  patchId: string,
  reviewer = 'human',
  evidence: Record<string, any> = {}
) {
  return request<unknown>(`/case-library/patches/${patchId}/approve-with-evaluation`, {
    method: 'POST',
    body: JSON.stringify({ performed_by: reviewer, ...evidence }),
  }).then(assertKnowledgeVersionItem)
}

export function deleteCase(caseId: string) {
  return request<unknown>(`/case-library/cases/${caseId}`, { method: 'DELETE' }).then(assertDeleteResult)
}

export function deleteReviewTag(tagId: string) {
  return request<unknown>(`/case-library/tags/${tagId}`, { method: 'DELETE' }).then(assertDeleteResult)
}

export function deleteErrorEntry(entryId: string) {
  return request<unknown>(`/case-library/error-ledger/${entryId}`, { method: 'DELETE' }).then(assertDeleteResult)
}

export function deleteKnowledgePatch(patchId: string) {
  return request<unknown>(`/case-library/patches/${patchId}`, { method: 'DELETE' }).then(assertDeleteResult)
}
