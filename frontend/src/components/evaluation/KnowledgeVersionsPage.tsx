import { useCallback, useEffect, useState } from 'react'
import { BookOpenCheck, GitBranch, GitCompare, Layers, RefreshCw, RotateCcw, Save, ShieldCheck } from 'lucide-react'
import { Badge } from '../common/Badge'
import { Card } from '../common/Card'
import { ResearchEmptyState, ResearchLoading, ResearchMetricCard, ResearchPageHeader } from '../research/ResearchLabShared'
import {
  createKnowledgeVersion,
  getKnowledgeVersionDiff,
  getKnowledgeVersions,
  rerunKnowledgeVersionRegression,
  rollbackKnowledgeVersion,
} from '../../api/caseLibraryClient'
import { KnowledgeVersionItem, PostPublishRegressionReport, VersionDiffResult } from '../../types'
import { useToastStore } from '../../store/useToastStore'
import { roleAllows, useOperatorContext } from '../../store/operatorContext'
import { formatDateTime } from '../../utils/format'

function statusBadge(status?: string) {
  if (status === 'active') return 'PASS'
  if (status === 'rolled_back' || status === 'deprecated') return 'SKIPPED'
  return 'WARN'
}

function compactId(id?: string | null) {
  if (!id) return null
  return id.length > 18 ? `${id.slice(0, 18)}...` : id
}

function evidenceCount(version: KnowledgeVersionItem) {
  const refs = version.approval_record?.evidence_refs
  return Array.isArray(refs) ? refs.length : 0
}

function regressionBadge(status?: string) {
  const normalized = String(status || '').toUpperCase()
  if (['PASS', 'PASSED', 'OK'].includes(normalized)) return 'PASS'
  if (['REGRESSION', 'REGRESSED', 'FAIL', 'FAILED', 'BLOCKED'].includes(normalized)) return 'FAIL'
  if (['REVIEW', 'WARN', 'WARNING'].includes(normalized)) return 'WARN'
  return 'SKIPPED'
}

function impactBadge(status?: string, riskLevel?: string) {
  const risk = String(riskLevel || '').toUpperCase()
  const normalized = String(status || '').toUpperCase()
  if (risk === 'HIGH' || normalized.includes('REGRESSION')) return 'FAIL'
  if (risk === 'MEDIUM' || normalized.includes('REVIEW') || normalized.includes('LIMITED')) return 'WARN'
  if (normalized === 'IMPROVING' || normalized === 'NO_MEASURABLE_CHANGE') return 'PASS'
  return 'SKIPPED'
}

function percent(value: unknown) {
  if (value == null) return '-'
  const raw = String(value).trim()
  const numeric = Number(raw.replace('%', ''))
  if (!Number.isFinite(numeric)) return '-'
  const percentValue = raw.endsWith('%') || Math.abs(numeric) > 1 ? numeric : numeric * 100
  return `${Math.round(percentValue)}%`
}

function countValue(value: unknown) {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? Math.round(numeric).toLocaleString() : '0'
}

function hasPostPublishRegressionReport(
  report: KnowledgeVersionItem['post_publish_regression'] | undefined,
): report is PostPublishRegressionReport {
  return Boolean(report?.report_id && report?.status)
}

function regressionWaiver(version: KnowledgeVersionItem) {
  const waiver = version.approval_record?.regression_waiver
  return waiver && typeof waiver === 'object' && !Array.isArray(waiver) ? waiver : null
}

function versionSourceCount(version: KnowledgeVersionItem) {
  return [
    version.source_run_id,
    version.source_case_id,
    version.source_patch_id,
    version.source_evaluation_id,
    version.source_verdict_id,
  ].filter(Boolean).length
}

function regressionQualityWarnings(report: PostPublishRegressionReport | null) {
  if (Array.isArray(report?.quality_warnings)) {
    return report.quality_warnings.map((item) => String(item)).filter(Boolean)
  }
  if (Array.isArray(report?.case_set_quality?.warnings)) {
    return report.case_set_quality.warnings.map((item) => String(item)).filter(Boolean)
  }
  return []
}

function reviewGateEvidenceStrength(value?: string | null, fallback = 'LOW') {
  const normalized = String(value || '').trim().toUpperCase()
  if (['HIGH', 'STRONG', 'PRIMARY', 'PRIMARY_EVIDENCE', 'PASS', 'READY'].includes(normalized)) return 'MEDIUM'
  if (['RESEARCH_GRADE', 'PRIMARY_EVIDENCE_READY'].includes(normalized)) return 'MEDIUM'
  if (['UNKNOWN', 'SUPPORTING_ONLY', 'WEAK', 'WARN', 'WARNING', 'REVIEW', 'REVIEW_ONLY'].includes(normalized)) return 'LOW'
  if (['MEDIUM', 'LOW', 'MISSING', 'PENDING'].includes(normalized)) return normalized
  if (['FAIL', 'FAILED', 'BLOCKED'].includes(normalized)) return 'MISSING'
  return fallback
}

function regressionReportEvidenceStrength(report: PostPublishRegressionReport | null) {
  return reviewGateEvidenceStrength(report?.evidence_strength, 'LOW')
}

function regressionReportBlocker(report: PostPublishRegressionReport | null) {
  if (!report) return '缺少 post-publish regression report'
  if (
    report.evidence_usage !== 'review_gate_only'
    || report.simulation_only !== true
    || report.is_real_trade !== false
    || report.strong_conclusion_allowed === true
  ) {
    return 'Post-publish regression simulation-only boundary missing or violated'
  }
  if ((report.regressed_cases || 0) > 0) return `发现 ${countValue(report.regressed_cases)} 个退化案例`
  if ((report.review_required_cases || 0) > 0) return `发现 ${countValue(report.review_required_cases)} 个需人工复核案例`
  const warnings = regressionQualityWarnings(report)
  if (warnings.length > 0) return warnings[0]
  return '无阻断，保持人工复核'
}

function regressionReportNextAction(report: PostPublishRegressionReport | null) {
  const blocker = regressionReportBlocker(report)
  if (!report) return '重跑发布后回归'
  if (blocker.includes('simulation-only')) return '阻断 report 消费并修复后端边界字段'
  if ((report.regressed_cases || 0) > 0) return '复核退化案例并记录豁免或回滚'
  if ((report.review_required_cases || 0) > 0) return '补人工复核后再晋级'
  if (regressionQualityWarnings(report).length > 0) return '补代表性 case set 后再信任回归率'
  return '仅作为 review gate 输入，不升级为强结论'
}

function approvedRegressionWaiver(version: KnowledgeVersionItem) {
  return String(regressionWaiver(version)?.status || '').toUpperCase() === 'APPROVED'
}

function knowledgeVersionEvidenceStrengthLabel(version: KnowledgeVersionItem) {
  const apiStrength = reviewGateEvidenceStrength(version.evidence_strength)
  if (apiStrength === 'MEDIUM') return 'MEDIUM：版本回归证据已记录，仍需人工复核'
  if (apiStrength === 'LOW') return 'LOW：版本证据仅可作治理复核'
  if (apiStrength === 'MISSING') return 'MISSING：缺少版本发布证据'
  if (apiStrength === 'PENDING') return 'PENDING：等待版本回归/来源证据'

  const regression = hasPostPublishRegressionReport(version.post_publish_regression)
    ? version.post_publish_regression
    : null
  const regressionStatus = String(regression?.status || '').toUpperCase()
  const caseQualityStatus = String(regression?.case_set_quality?.status || '').toUpperCase()
  const impact = regression?.knowledge_impact
  const impactRisk = String(impact?.risk_level || '').toUpperCase()
  const reviewEvidenceCount = evidenceCount(version) + versionSourceCount(version)
  const policyBlocking = regression?.case_set_quality_policy?.blocking === true
  const impactBlocking = impact?.auto_blocks_promotion === true || impactRisk === 'HIGH'
  const cleanRegression = ['PASS', 'PASSED', 'OK'].includes(regressionStatus)
  const cleanCaseQuality = !['FAIL', 'FAILED', 'BLOCKED', 'INSUFFICIENT'].includes(caseQualityStatus)

  if (regression && reviewEvidenceCount > 0 && cleanRegression && cleanCaseQuality && !policyBlocking && !impactBlocking) {
    return 'MEDIUM_REGRESSION_REVIEW'
  }
  if (regression && reviewEvidenceCount > 0) return 'MEDIUM_REGRESSION_REVIEW'
  if (regression || reviewEvidenceCount > 0) return 'LOW_SUPPORTING'
  return 'LOW_SUPPORTING'
}

function knowledgeVersionBlocker(version: KnowledgeVersionItem, canWriteKnowledgeVersions: boolean) {
  const regression = hasPostPublishRegressionReport(version.post_publish_regression)
    ? version.post_publish_regression
    : null
  const policy = regression?.case_set_quality_policy
  const impact = regression?.knowledge_impact
  const impactRisk = String(impact?.risk_level || '').toUpperCase()
  const reviewEvidenceCount = evidenceCount(version) + versionSourceCount(version)
  const hasWaiver = approvedRegressionWaiver(version)
  const warnings = regressionQualityWarnings(regression)

  if (verStatus(version) === 'draft') return '草稿版本未发布，不能作为强证据'
  if (reviewEvidenceCount === 0) return '缺少来源 / evidence 引用'
  if (!regression) {
    return canWriteKnowledgeVersions ? '缺少发布后回归，需先重跑回归' : '缺少发布后回归且当前角色不可重跑'
  }
  if (policy?.blocking === true) return policy.reason || policy.action || 'Case set quality policy blocking'
  if (impact?.auto_blocks_promotion === true) return `知识影响自动阻断：${impact?.action || impact?.status || 'review_required'}`
  if (impactRisk === 'HIGH') return `知识影响风险 HIGH：${impact?.status || 'review_required'}`
  if ((regression.regressed_cases || 0) > 0 && !hasWaiver) return '存在回归案例且无已审计豁免'
  if ((regression.review_required_cases || 0) > 0 && !hasWaiver) return '存在人工复核案例且无已审计豁免'
  if (warnings.length > 0) return warnings[0]
  return '无阻断，保持人工复核'
}

function knowledgeVersionNextAction(
  version: KnowledgeVersionItem,
  canWriteKnowledgeVersions: boolean,
  canRollbackKnowledge: boolean,
) {
  const blocker = knowledgeVersionBlocker(version, canWriteKnowledgeVersions)
  if (verStatus(version) === 'draft') return '发布后再运行回归评估'
  if (blocker.includes('回归') && !canWriteKnowledgeVersions) return '切换 researcher 角色补跑回归'
  if (blocker !== '无阻断，保持人工复核') return '补齐版本证据 / 回归后再晋级或回滚'
  return canRollbackKnowledge ? '可作为可审计回滚点，回滚仍需人工确认' : '仅查看；回滚需 admin 复核'
}

function verStatus(version: KnowledgeVersionItem) {
  return String(version.status || 'active').toLowerCase()
}

export function KnowledgeVersionsPage() {
  const addToast = useToastStore((s) => s.addToast)
  const operator = useOperatorContext()
  const [versions, setVersions] = useState<KnowledgeVersionItem[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [diff, setDiff] = useState<VersionDiffResult | null>(null)
  const [diffing, setDiffing] = useState(false)
  const [selA, setSelA] = useState('')
  const [selB, setSelB] = useState('')
  const canWriteKnowledgeVersions = roleAllows(operator.role, 'researcher')
  const canRollbackKnowledge = roleAllows(operator.role, 'admin')
  const knowledgeVersionWriteDisabledReason = canWriteKnowledgeVersions
    ? undefined
    : `知识版本写入需要 researcher 权限。当前角色：${operator.role}。`
  const rollbackDisabledReason = canRollbackKnowledge
    ? undefined
    : `知识版本回滚需要 admin 权限。当前角色：${operator.role}。`

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setVersions(await getKnowledgeVersions(30))
    } catch {
      // Keep current page state if refresh fails.
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  async function handleCreateVersion() {
    if (!canWriteKnowledgeVersions) {
      addToast(knowledgeVersionWriteDisabledReason || '知识版本写入需要 researcher 权限。', 'error')
      return
    }
    setSaving(true)
    try {
      const v = await createKnowledgeVersion({
        description: '从知识版本页创建的人工治理快照',
        scope: 'manual_snapshot',
        risk_boundary: 'Manual snapshot only; no runtime policy change.',
        approval_record: {
          created_from: 'KnowledgeVersionsPage',
          reviewer: 'human',
        },
      })
      setVersions((prev) => [v, ...prev])
      addToast(`Version v${v.version_number} created`, 'success')
    } catch (err) {
      addToast(err instanceof Error ? err.message : 'Create version failed', 'error')
    } finally {
      setSaving(false)
    }
  }

  async function handleDiff() {
    if (!selA || !selB) {
      addToast('请选择两个版本 / Select two versions', 'error')
      return
    }
    setDiffing(true)
    try {
      const d = await getKnowledgeVersionDiff(selA, selB)
      setDiff(d)
    } catch (err) {
      addToast(err instanceof Error ? err.message : 'Diff failed', 'error')
    } finally {
      setDiffing(false)
    }
  }

  async function handleRollback(versionId: string) {
    if (!canRollbackKnowledge) {
      addToast(rollbackDisabledReason || '知识版本回滚需要 admin 权限。', 'error')
      return
    }
    if (!window.confirm('确认回滚到此版本？当前已批准补丁会归档，并恢复目标版本补丁状态。')) return
    setSaving(true)
    try {
      const result = await rollbackKnowledgeVersion(versionId)
      addToast(`Rollback completed, restored ${result.restored_patches} patch(es)`, 'success')
      await load()
    } catch (err) {
      addToast(err instanceof Error ? err.message : 'Rollback failed', 'error')
    } finally {
      setSaving(false)
    }
  }

  async function handleRerunRegression(versionId: string) {
    if (!canWriteKnowledgeVersions) {
      addToast(knowledgeVersionWriteDisabledReason || '知识版本写入需要 researcher 权限。', 'error')
      return
    }
    setSaving(true)
    try {
      const version = await rerunKnowledgeVersionRegression(versionId)
      setVersions((prev) => prev.map((item) => (item.version_id === versionId ? version : item)))
      addToast('Post-publish regression refreshed', 'success')
    } catch (err) {
      addToast(err instanceof Error ? err.message : 'Regression rerun failed', 'error')
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <ResearchLoading label="正在加载知识版本..." />

  const latestVersion = versions[0]
  const activeCount = versions.filter((item) => item.status === 'active').length
  const latestRegressionVersion = versions.find((item) => hasPostPublishRegressionReport(item.post_publish_regression))
  const latestRegression = latestRegressionVersion?.post_publish_regression

  return (
    <div data-testid="knowledge-versions-page" className="space-y-6">
      <ResearchPageHeader
        eyebrow="知识版本"
        title="知识版本"
        subtitle="管理知识库快照、版本对比、回滚动作和发布治理元数据，确保发布晋级与回滚都有可审计记录。"
        icon={GitBranch}
        tags={['Snapshot', 'Governance', 'Rollback']}
        actions={
          <>
            <button
              type="button"
              data-testid="knowledge-version-create-draft"
              onClick={handleCreateVersion}
              disabled={saving || !canWriteKnowledgeVersions}
              title={knowledgeVersionWriteDisabledReason || undefined}
              className="inline-flex items-center gap-2 rounded-md bg-cyan-400 px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-cyan-300 disabled:opacity-60"
            >
              <Save size={16} />
              创建草稿
            </button>
            <button
              type="button"
              onClick={load}
              disabled={saving}
              className="inline-flex items-center gap-2 rounded-md border border-slate-600 bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:opacity-60"
            >
              <RefreshCw size={16} />
              刷新
            </button>
          </>
        }
      />

      <div className="rounded-md border border-slate-200 bg-white px-4 py-3 text-xs text-slate-500">
        <span data-testid="knowledge-version-write-role">
          角色：{operator.role}；版本写入：{canWriteKnowledgeVersions ? 'researcher+' : '已阻断'}；回滚：{canRollbackKnowledge ? 'admin' : '已阻断'}
        </span>
        <span data-testid="knowledge-version-rollback-role" className="ml-3">
          回滚：{canRollbackKnowledge ? 'admin' : '已阻断'}
        </span>
        {!canWriteKnowledgeVersions ? (
          <span data-testid="knowledge-version-write-disabled-reason" className="ml-3 text-amber-700">{knowledgeVersionWriteDisabledReason}</span>
        ) : null}
        {!canRollbackKnowledge ? (
          <span data-testid="knowledge-version-rollback-disabled-reason" className="ml-3 text-amber-700">{rollbackDisabledReason}</span>
        ) : null}
      </div>

      {!canRollbackKnowledge ? (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          知识版本回滚仅限 admin。当前角色：{operator.role}。
        </div>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <ResearchMetricCard label="版本快照" value={versions.length} helper="Snapshots / 可回滚节点" icon={GitBranch} tone="bg-cyan-50 text-cyan-700" />
        <ResearchMetricCard label="最新版本" value={latestVersion ? `v${latestVersion.version_number}` : '-'} helper="Latest / 当前最新快照" icon={BookOpenCheck} tone="bg-emerald-50 text-emerald-700" />
        <ResearchMetricCard label="活跃版本" value={activeCount} helper="Active / 发布状态" icon={ShieldCheck} tone="bg-sky-50 text-sky-700" />
        <div data-testid="knowledge-version-regression-overview">
          <ResearchMetricCard label="发布回归" value={latestRegression?.status ?? '-'} helper={latestRegression ? `v${latestRegressionVersion?.version_number ?? '-'} / Improve ${percent(latestRegression.improvement_rate)} / Regress ${percent(latestRegression.regression_rate)} / Review ${countValue(latestRegression.review_required_cases)}` : 'No published regression yet'} icon={Layers} tone="bg-slate-100 text-slate-700" />
        </div>
      </div>

      {versions.length > 0 && (
        <Card title="版本对比">
          <div className="flex flex-wrap items-center gap-3">
            <select
              value={selA}
              onChange={(e) => setSelA(e.target.value)}
              className="rounded-md border border-slate-200 bg-white px-3 py-2 text-sm"
            >
              <option value="">选择版本 A</option>
              {versions.map((v) => (
                <option key={v.version_id} value={v.version_id}>v{v.version_number} - {v.description.slice(0, 30)}</option>
              ))}
            </select>
            <span className="text-slate-400">vs</span>
            <select
              value={selB}
              onChange={(e) => setSelB(e.target.value)}
              className="rounded-md border border-slate-200 bg-white px-3 py-2 text-sm"
            >
              <option value="">选择版本 B</option>
              {versions.map((v) => (
                <option key={v.version_id} value={v.version_id}>v{v.version_number} - {v.description.slice(0, 30)}</option>
              ))}
            </select>
            <button
              type="button"
              onClick={handleDiff}
              disabled={diffing || !selA || !selB}
              className="inline-flex items-center gap-2 rounded-md border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-60"
            >
              {diffing ? <RefreshCw size={14} className="animate-spin" /> : <GitCompare size={14} />}
              对比
            </button>
          </div>

          {diff && (
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <div className="rounded-md border border-emerald-200 bg-emerald-50 p-3">
                <div className="text-xs font-semibold text-emerald-700">新增 / Added ({diff.patches_added.length + diff.rules_added.length})</div>
                <div className="mt-1 text-xs leading-5 text-emerald-600">
                  Patches: {diff.patches_added.join(', ') || 'None'}<br />
                  Rules: {diff.rules_added.join(', ') || 'None'}
                </div>
              </div>
              <div className="rounded-md border border-red-200 bg-red-50 p-3">
                <div className="text-xs font-semibold text-red-700">移除 / Removed ({diff.patches_removed.length + diff.rules_removed.length})</div>
                <div className="mt-1 text-xs leading-5 text-red-600">
                  Patches: {diff.patches_removed.join(', ') || 'None'}<br />
                  Rules: {diff.rules_removed.join(', ') || 'None'}
                </div>
              </div>
            </div>
          )}
        </Card>
      )}

      <div className="space-y-4">
        {versions.length === 0 ? (
          <ResearchEmptyState title="暂无版本快照" description="发布晋级或手动创建后，会在这里显示治理字段、证据引用和回滚影响。" icon={GitBranch} />
        ) : (
          versions.map((ver) => {
            const sourceItems = [
              ['Run', ver.source_run_id],
              ['Case', ver.source_case_id],
              ['Patch', ver.source_patch_id],
              ['Evaluation', ver.source_evaluation_id],
              ['Verdict', ver.source_verdict_id],
            ].filter(([, value]) => value)
            const regression = hasPostPublishRegressionReport(ver.post_publish_regression)
              ? ver.post_publish_regression
              : null
            const caseSetQuality = regression?.case_set_quality
            const caseSetQualityPolicy = regression?.case_set_quality_policy
            const qualityWarnings = regressionQualityWarnings(regression)
            const remediation = caseSetQualityPolicy?.remediation
            const remediationActions = Array.isArray(remediation?.next_actions)
              ? remediation.next_actions.map((item) => String(item)).filter(Boolean)
              : []
            const knowledgeImpact = regression?.knowledge_impact
            const waiver = regressionWaiver(ver)
            const versionBlocker = knowledgeVersionBlocker(ver, canWriteKnowledgeVersions)
            const regressionBlocker = regressionReportBlocker(regression)

            return (
              <div key={ver.version_id} className="rounded-md border border-slate-200 bg-white p-4 shadow-sm">
                <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="inline-flex items-center gap-1 rounded-md bg-cyan-100 px-2 py-1 text-xs font-semibold text-cyan-700">
                        <GitBranch size={12} /> v{ver.version_number}
                      </span>
                      <Badge status={statusBadge(ver.status)}>{ver.status || 'active'}</Badge>
                      <span className="text-xs text-slate-500">{ver.created_by}</span>
                      <span className="text-xs text-slate-400">{formatDateTime(ver.created_at)}</span>
                    </div>
                    <div className="mt-2 text-sm font-medium text-slate-800">{ver.description}</div>
                    <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-500">
                      <span>Scope: {ver.scope || 'knowledge_base'}</span>
                      <span>|</span>
                      <span>Active patches: {ver.active_patches.length}</span>
                      <span>|</span>
                      <span>Active rules: {ver.active_rules.length}</span>
                      <span>|</span>
                      <span>Evidence: {evidenceCount(ver)}</span>
                    </div>
                  </div>
                  <button
                    type="button"
                    data-testid={`knowledge-version-rollback-${ver.version_id}`}
                    onClick={() => handleRollback(ver.version_id)}
                    disabled={saving || !canRollbackKnowledge}
                    title={rollbackDisabledReason}
                    className="inline-flex items-center gap-2 rounded-md border border-amber-200 px-3 py-2 text-xs font-semibold text-amber-700 transition hover:bg-amber-50 disabled:opacity-60"
                  >
                    <RotateCcw size={14} />
                    回滚
                  </button>
                  <button
                    type="button"
                    onClick={() => handleRerunRegression(ver.version_id)}
                    disabled={saving || ver.status === 'draft' || !canWriteKnowledgeVersions}
                    data-testid={`knowledge-version-rerun-regression-${ver.version_id}`}
                    title={knowledgeVersionWriteDisabledReason || (ver.status === 'draft' ? 'Draft versions can run regression after publish.' : undefined)}
                    className="inline-flex items-center gap-2 rounded-md border border-cyan-200 px-3 py-2 text-xs font-semibold text-cyan-700 transition hover:bg-cyan-50 disabled:opacity-60"
                  >
                    <RefreshCw size={14} />
                    {ver.status === 'draft' ? '发布后可回归' : '回归评估'}
                  </button>
                </div>

                <div data-testid={`knowledge-version-governance-${ver.version_id}`} className="mt-3 grid gap-2 rounded-md border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600 sm:grid-cols-2 xl:grid-cols-5">
                  <span className="min-w-0 break-words">
                    Version ID:{' '}
                    <span data-testid={`knowledge-version-governance-id-${ver.version_id}`} className="break-all font-mono">
                      {ver.version_id}
                    </span>
                  </span>
                  <span data-testid={`knowledge-version-evidence-strength-${ver.version_id}`} className="min-w-0 break-words">
                    Evidence: {knowledgeVersionEvidenceStrengthLabel(ver)}
                  </span>
                  <span data-testid={`knowledge-version-blocker-${ver.version_id}`} className="min-w-0 break-words">
                    Blocker: {versionBlocker}
                  </span>
                  <span data-testid={`knowledge-version-next-action-${ver.version_id}`} className="min-w-0 break-words">
                    Next: {knowledgeVersionNextAction(ver, canWriteKnowledgeVersions, canRollbackKnowledge)}
                  </span>
                  <span data-testid={`knowledge-version-simulation-boundary-${ver.version_id}`} className="min-w-0 break-words font-medium text-slate-900">
                    simulation_only={String(ver.simulation_only)} / is_real_trade={String(ver.is_real_trade)} / evidence_usage={ver.evidence_usage} / strong_conclusion_allowed={String(ver.strong_conclusion_allowed)} / SIM_*
                  </span>
                </div>

                <div className="mt-3 grid gap-3 lg:grid-cols-3">
                  <div className="rounded-md bg-slate-50 p-3">
                    <div className="text-xs font-semibold text-slate-700">来源证据</div>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {sourceItems.length === 0 ? (
                        <span className="text-xs text-slate-400">暂无来源引用</span>
                      ) : sourceItems.map(([label, value]) => (
                        <span key={`${label}-${value}`} className="rounded bg-white px-2 py-1 text-xs font-mono text-slate-600">
                          {label}: {compactId(value)}
                        </span>
                      ))}
                    </div>
                  </div>
                  <div className="rounded-md bg-slate-50 p-3">
                    <div className="text-xs font-semibold text-slate-700">风险边界</div>
                    <div className="mt-2 text-xs leading-5 text-slate-600">{ver.risk_boundary || 'No explicit risk boundary.'}</div>
                  </div>
                  <div className="rounded-md bg-slate-50 p-3">
                    <div className="text-xs font-semibold text-slate-700">回滚影响</div>
                    <div className="mt-2 text-xs leading-5 text-slate-600">
                      目标版本：{compactId(ver.rollback_impact?.target_version_id) || '无'}<br />
                      已恢复补丁：{ver.rollback_impact?.restored_patch_count ?? '无'}
                    </div>
                  </div>
                </div>
                {waiver ? (
                  <div data-testid={`knowledge-version-regression-waiver-${ver.version_id}`} className="mt-3 rounded-md border border-amber-200 bg-amber-50 p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="text-xs font-semibold text-amber-800">已审计回归豁免</div>
                      <Badge status={waiver.status === 'APPROVED' ? 'WARN' : 'FAIL'}>{waiver.status || 'UNKNOWN'}</Badge>
                    </div>
                    <div className="mt-2 grid gap-2 text-xs text-amber-900 sm:grid-cols-2 xl:grid-cols-4">
                      <span>策略：{waiver.policy_id || 'knowledge_promotion_regression_waiver_v1'}</span>
                      <span>Approval: {waiver.approval_id || 'N/A'}</span>
                      <span>Role: {waiver.approver_role || 'N/A'}</span>
                      <span>Regressed: {countValue(waiver.regressed_cases)}</span>
                      <span>Evaluation: {compactId(waiver.evaluation_id) || 'N/A'}</span>
                      <span>Approved by: {waiver.approved_by || 'N/A'}</span>
                      <span>Mode: {waiver.mode || 'AUDITED_OVERRIDE'}</span>
                      <span>At: {waiver.approved_at ? formatDateTime(waiver.approved_at) : 'N/A'}</span>
                    </div>
                    <div className="mt-2 text-xs leading-5 text-amber-900">
                      {waiver.reason || 'No waiver reason recorded.'}
                    </div>
                  </div>
                ) : null}
                <div data-testid={`knowledge-version-regression-${ver.version_id}`} className="mt-3 rounded-md border border-slate-200 bg-slate-50 p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="text-xs font-semibold text-slate-700">发布后回归</div>
                    <Badge status={regressionBadge(regression?.status)}>{regression?.status || 'NOT_RUN'}</Badge>
                  </div>
                  <div className="mt-2 grid gap-2 text-xs text-slate-600 sm:grid-cols-5">
                    <span>Cases: {regression?.representative_case_count ?? 0}</span>
                    <span>Patches: {regression?.active_patch_count ?? 0}</span>
                    <span>Improve: {percent(regression?.improvement_rate)}</span>
                    <span>Regress: {percent(regression?.regression_rate)}</span>
                    <span>Review: {countValue(regression?.review_required_cases)} ({percent(regression?.review_required_rate)})</span>
                  </div>
                  <div data-testid={`knowledge-version-regression-governance-${ver.version_id}`} className="mt-2 grid gap-2 rounded bg-white px-2 py-2 text-xs text-slate-600 sm:grid-cols-2 xl:grid-cols-5">
                    <span className="min-w-0 break-words">
                      Report ID:{' '}
                      <span data-testid={`knowledge-version-regression-report-id-${ver.version_id}`} className="break-all font-mono">
                        {regression?.report_id || 'NOT_RUN'}
                      </span>
                    </span>
                    <span data-testid={`knowledge-version-regression-evidence-strength-${ver.version_id}`} className="min-w-0 break-words">
                      Evidence: {regressionReportEvidenceStrength(regression)}
                    </span>
                    <span data-testid={`knowledge-version-regression-blocker-${ver.version_id}`} className="min-w-0 break-words">
                      Blocker: {regressionBlocker}
                    </span>
                    <span data-testid={`knowledge-version-regression-next-action-${ver.version_id}`} className="min-w-0 break-words">
                      Next: {regressionReportNextAction(regression)}
                    </span>
                    <span data-testid={`knowledge-version-regression-simulation-boundary-${ver.version_id}`} className="min-w-0 break-words font-medium text-slate-900">
                      simulation_only={String(regression?.simulation_only ?? true)} / is_real_trade={String(regression?.is_real_trade ?? false)} / evidence_usage={regression?.evidence_usage ?? 'review_gate_only'} / strong_conclusion_allowed={String(regression?.strong_conclusion_allowed ?? false)} / SIM_*
                    </span>
                  </div>
                  {knowledgeImpact ? (
                    <div data-testid={`knowledge-version-regression-impact-${ver.version_id}`} className="mt-2 rounded bg-white px-2 py-2 text-xs text-slate-600">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge status={impactBadge(knowledgeImpact.status, knowledgeImpact.risk_level)}>
                          {knowledgeImpact.status || 'UNKNOWN'}
                        </Badge>
                        <span>Risk: {knowledgeImpact.risk_level || 'UNKNOWN'}</span>
                        <span>Mode: {knowledgeImpact.mode || 'OBSERVATION_ONLY'}</span>
                        <span>Human review: {knowledgeImpact.requires_human_review ? 'yes' : 'no'}</span>
                        <span>Auto block: {knowledgeImpact.auto_blocks_promotion ? 'yes' : 'no'}</span>
                      </div>
                      <div className="mt-2 grid gap-2 sm:grid-cols-4">
                        <span>Net impact: {countValue(knowledgeImpact.net_improvement_cases)}</span>
                        <span>Signal: {knowledgeImpact.strongest_signal || 'unknown'}</span>
                        <span>模块：{knowledgeImpact.affected_module_count ?? 0}</span>
                        <span>动作：{knowledgeImpact.action || 'monitor_post_publish_impact'}</span>
                      </div>
                    </div>
                  ) : null}
                  <div data-testid={`knowledge-version-regression-quality-${ver.version_id}`} className="mt-2 grid gap-2 text-xs text-slate-600 sm:grid-cols-4">
                    <span>质量：{caseSetQuality?.status || 'UNKNOWN'}</span>
                    <span>标的：{caseSetQuality?.unique_symbol_count ?? 0}</span>
                    <span>失败/边界：{countValue((caseSetQuality?.incorrect_case_count ?? 0) + (caseSetQuality?.insufficient_data_case_count ?? 0) + (caseSetQuality?.optimism_bias_case_count ?? 0))}</span>
                    <span>Missing modules: {caseSetQuality?.missing_affected_modules?.length ?? 0}</span>
                  </div>
                  <div data-testid={`knowledge-version-regression-policy-${ver.version_id}`} className="mt-2 grid gap-2 rounded bg-white px-2 py-2 text-xs text-slate-600 sm:grid-cols-4">
                    <span>策略：{caseSetQualityPolicy?.mode || 'UNKNOWN'}</span>
                    <span>动作：{caseSetQualityPolicy?.action || 'N/A'}</span>
                    <span>Blocking: {caseSetQualityPolicy?.blocking ? 'yes' : 'no'}</span>
                    <span>Override: {caseSetQualityPolicy?.override_required ? 'required' : 'not required'}</span>
                  </div>
                  {remediation ? (
                    <div data-testid={`knowledge-version-regression-remediation-${ver.version_id}`} className="mt-2 rounded bg-white px-2 py-2 text-xs text-slate-600">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge status={remediation.status === 'NOT_REQUIRED' ? 'PASS' : 'WARN'}>{remediation.status || 'UNKNOWN'}</Badge>
                        <span>Owner: {remediation.owner || 'case_library_reviewer'}</span>
                        <span>Case delta: {remediation.required_reviewed_case_delta ?? 0}</span>
                        <span>Symbol delta: {remediation.required_unique_symbol_delta ?? 0}</span>
                      </div>
                      {remediationActions.length > 0 ? (
                        <div className="mt-2 space-y-1">
                          {remediationActions.slice(0, 2).map((action) => (
                            <div key={action} className="rounded bg-amber-50 px-2 py-1 text-[11px] leading-4 text-amber-800">
                              {action}
                            </div>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                  {qualityWarnings.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {qualityWarnings.slice(0, 3).map((warning) => (
                        <span key={warning} className="rounded bg-amber-100 px-2 py-1 text-[11px] text-amber-800">
                          {warning}
                        </span>
                      ))}
                    </div>
                  )}
                  <div data-testid={`knowledge-version-regression-summary-${ver.version_id}`} className="mt-2 text-xs leading-5 text-slate-500">
                    {regression?.summary || '草稿或旧版本尚无发布后回归评估。'}
                  </div>
                </div>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
