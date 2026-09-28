import { ChangeEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Activity, AlertTriangle, Database, FileUp, Layers, Play, Plus, RefreshCw, ShieldCheck, Trash2 } from 'lucide-react'
import { Badge } from '../common/Badge'
import { Card } from '../common/Card'
import { MetricTile, TableShell } from '../common/Material'
import { SectionTitle } from '../common/SectionTitle'
import { roleAllows, useOperatorContext } from '../../store/operatorContext'
import {
  createManualPortfolioSnapshot,
  deletePortfolioSnapshot,
  importPortfolioSnapshot,
  listPortfolioSnapshots,
  ManualPortfolioPayload,
  PortfolioSnapshot,
  PortfolioSnapshotSummary,
} from '../../api/portfolioClient'
import { ApiError } from '../../api/httpClient'

type PortfolioImportErrorDetail = {
  message?: string
  jobId?: string
  filename?: string
  reason?: string
  acceptedExtensions?: string[]
  expectedColumns?: {
    required?: string[]
    recommended?: string[]
  }
  observedHeaders?: string[]
  matchedFields?: string[]
  missingRequiredFields?: string[]
  rowPreview?: Array<{
    rowNumber?: number
    cells?: Record<string, string>
  }>
  brokerTemplateHint?: {
    brokerTemplateId?: string
    brokerTemplateLabel?: string
    templateConfidence?: number
    templateWarnings?: string[]
  }
  templateConfidenceNote?: string
  repairSuggestions?: string[]
  limits?: Record<string, number | string>
}

const sampleSnapshot: ManualPortfolioPayload = {
  sourceName: '最小组合样例',
  accountName: 'demo',
  cash: 32000,
  availableCash: 32000,
  totalAssets: 100000,
  positions: [
    {
      symbol: '002846',
      name: '英联股份',
      shares: 2000,
      availableShares: 2000,
      costPrice: 18.5,
      marketValue: 37000,
      pnl: 0,
      industry: '轻工制造',
      style: '中小盘',
      theme: '包装材料',
      riskFactor: '高波动',
    },
    {
      symbol: '600519',
      name: '贵州茅台',
      shares: 20,
      availableShares: 20,
      costPrice: 1550,
      marketValue: 31000,
      pnl: 0,
      industry: '食品饮料',
      style: '价值',
      theme: '消费',
      riskFactor: '大盘权重',
    },
  ],
}

const initialManualForm = {
  sourceName: '手动快照',
  accountName: '',
  symbol: '002846',
  name: '',
  shares: 1000,
  availableShares: 1000,
  costPrice: 18.5,
  marketValue: 18500,
  cash: 50000,
  availableCash: 50000,
  totalAssets: 68500,
}

export function PortfolioPage() {
  const operator = useOperatorContext()
  const [snapshots, setSnapshots] = useState<PortfolioSnapshotSummary[]>([])
  const [selectedSnapshot, setSelectedSnapshot] = useState<PortfolioSnapshot | null>(null)
  const [manualForm, setManualForm] = useState(initialManualForm)
  const [importFile, setImportFile] = useState<File | null>(null)
  const [importSourceName, setImportSourceName] = useState('导入持仓')
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [importErrorDetail, setImportErrorDetail] = useState<PortfolioImportErrorDetail | null>(null)

  const latest = snapshots[0]
  const selectedId = selectedSnapshot?.snapshotId || latest?.snapshotId || ''
  const canWritePortfolioSnapshots = roleAllows(operator.role, 'researcher')
  const writeDisabledReason = canWritePortfolioSnapshots
    ? undefined
    : `组合快照写入需要 researcher 权限。当前角色：${operator.role}。`
  const canDeletePortfolioSnapshots = roleAllows(operator.role, 'admin')
  const deleteDisabledReason = canDeletePortfolioSnapshots
    ? undefined
    : `组合快照删除需要 admin 权限。当前角色：${operator.role}。`

  const reload = useCallback(async (focusSnapshot?: PortfolioSnapshot) => {
    setLoading(true)
    setError('')
    try {
      const items = await listPortfolioSnapshots()
      setSnapshots(items)
      setSelectedSnapshot((current) => {
        if (focusSnapshot) return focusSnapshot
        if (current && items.some((item) => item.snapshotId === current.snapshotId)) return current
        return null
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载组合快照失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    reload()
  }, [reload])

  async function createSample() {
    if (!canWritePortfolioSnapshots) {
      setError(writeDisabledReason || '')
      setMessage('')
      return
    }
    setLoading(true)
    setError('')
    setMessage('')
    try {
      const snapshot = await createManualPortfolioSnapshot(sampleSnapshot)
      setSelectedSnapshot(snapshot)
      setMessage(`已创建样例快照 ${snapshot.snapshotId}`)
      await reload(snapshot)
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建样例快照失败')
    } finally {
      setLoading(false)
    }
  }

  async function createManual() {
    if (!canWritePortfolioSnapshots) {
      setError(writeDisabledReason || '')
      setMessage('')
      return
    }
    setLoading(true)
    setError('')
    setMessage('')
    try {
      const snapshot = await createManualPortfolioSnapshot({
        sourceName: manualForm.sourceName.trim() || '手动快照',
        accountName: manualForm.accountName.trim(),
        cash: manualForm.cash,
        availableCash: manualForm.availableCash,
        totalAssets: manualForm.totalAssets,
        positions: [
          {
            symbol: manualForm.symbol.trim(),
            name: manualForm.name.trim(),
            shares: manualForm.shares,
            availableShares: manualForm.availableShares,
            costPrice: manualForm.costPrice,
            marketValue: manualForm.marketValue || manualForm.shares * manualForm.costPrice,
            pnl: 0,
          },
        ],
      })
      setSelectedSnapshot(snapshot)
      setMessage(`已创建手动快照 ${snapshot.snapshotId}`)
      await reload(snapshot)
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建手动快照失败')
    } finally {
      setLoading(false)
    }
  }

  async function importFileSnapshot() {
    if (!canWritePortfolioSnapshots) {
      setError(writeDisabledReason || '')
      setMessage('')
      setImportErrorDetail(null)
      return
    }
    if (!importFile) {
      setError('请先选择 CSV 或 XLSX 文件')
      return
    }
    setLoading(true)
    setError('')
    setMessage('')
    setImportErrorDetail(null)
    try {
      const result = await importPortfolioSnapshot(importFile, importSourceName || '导入持仓')
      setSelectedSnapshot(result.snapshot)
      setMessage(`已导入 ${result.snapshot.positionCount} 条持仓，快照 ${result.snapshot.snapshotId}`)
      await reload(result.snapshot)
    } catch (err) {
      const detail = extractPortfolioImportErrorDetail(err)
      setImportErrorDetail(detail)
      setError(err instanceof Error ? err.message : '导入快照失败')
    } finally {
      setLoading(false)
    }
  }

  async function removeSnapshot(snapshotId: string) {
    if (!canDeletePortfolioSnapshots) {
      setError(`组合快照删除需要 admin 权限。当前角色：${operator.role}。`)
      return
    }
    setLoading(true)
    setError('')
    setMessage('')
    try {
      await deletePortfolioSnapshot(snapshotId)
      setMessage(`已删除快照 ${snapshotId}`)
      if (selectedSnapshot?.snapshotId === snapshotId) {
        setSelectedSnapshot(null)
      }
      await reload()
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除快照失败')
    } finally {
      setLoading(false)
    }
  }

  const selectedSummary = useMemo(
    () => snapshots.find((item) => item.snapshotId === selectedId),
    [selectedId, snapshots],
  )
  const latestRisk = useMemo(() => portfolioRiskView(latest), [latest])
  const selectedRisk = useMemo(() => portfolioRiskView(selectedSummary), [selectedSummary])
  const selectedPositions = selectedSnapshot?.positions ?? []

  return (
    <div className="space-y-5 text-slate-900">
      <SectionTitle
        title="真实持仓"
        subtitle="通过真实组合 API 创建、导入和选择组合快照，供新建任务传入组合上下文。"
      />

      {(message || error) ? (
        <div className={`rounded-md border px-4 py-3 text-sm ${error ? 'border-rose-200 bg-rose-50 text-rose-700' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>
          {error || message}
        </div>
      ) : null}

      {!canDeletePortfolioSnapshots ? (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          组合快照删除仅限 admin。当前角色：{operator.role}。
        </div>
      ) : null}

      <div className="flex flex-wrap gap-2 rounded-md border border-slate-200 bg-white px-3 py-2 text-xs text-slate-500">
        <span data-testid="portfolio-write-role">角色：{operator.role}；写入快照：{canWritePortfolioSnapshots ? 'researcher+' : '已阻断'}</span>
        {!canWritePortfolioSnapshots ? (
          <span data-testid="portfolio-write-disabled-reason" className="text-amber-700">{writeDisabledReason}</span>
        ) : null}
      </div>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <MetricTile label="快照数量" value={String(snapshots.length)} helper="已登记组合快照" icon={Database} tone="info" />
        <MetricTile label="最新持仓数" value={latest ? String(latest.positionCount) : '-'} helper={latest?.sourceName || '等待快照'} icon={Layers} tone="neutral" />
        <MetricTile label="最新仓位" value={latest ? formatPercent(latest.totalPositionRatio) : '-'} helper={latest ? `最大单票 ${formatPercent(latest.maxSinglePositionRatio)}` : '无仓位数据'} icon={Activity} tone={latestRisk.tone} />
        <MetricTile label="组合风险" value={latestRisk.label} helper={latestRisk.helper} icon={ShieldCheck} tone={latestRisk.tone} />
      </div>

      <Card
        title="最小可操作入口"
        action={
          <button
            type="button"
            onClick={() => reload()}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50 disabled:opacity-60"
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            刷新
          </button>
        }
      >
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto]">
          <div className="rounded-md border border-slate-200 bg-[#f8fafd] p-4 text-sm text-slate-600">
            <div className="font-semibold text-slate-950">一键创建样例快照</div>
            <div className="mt-1 leading-6">
              该操作会调用 <span className="font-mono text-xs">POST /portfolio/manual</span> 写入一个最小组合快照，然后可直接进入新建任务选择它。
            </div>
          </div>
          <button
            type="button"
            data-testid="portfolio-create-sample"
            onClick={createSample}
            disabled={loading || !canWritePortfolioSnapshots}
            title={writeDisabledReason}
            className="inline-flex items-center justify-center gap-2 rounded-md bg-[#0b57d0] px-4 py-3 text-sm font-semibold text-white transition hover:bg-[#0842a0] disabled:opacity-60"
          >
            <Database size={16} />
            创建样例快照
          </button>
        </div>
      </Card>

      <Card title="手动快照">
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <TextInput label="来源名称" value={manualForm.sourceName} onChange={(value) => updateManual('sourceName', value)} />
          <TextInput label="账户名称" value={manualForm.accountName} onChange={(value) => updateManual('accountName', value)} />
          <TextInput label="股票代码" value={manualForm.symbol} onChange={(value) => updateManual('symbol', value)} />
          <TextInput label="股票名称" value={manualForm.name} onChange={(value) => updateManual('name', value)} />
          <NumberInput label="持有股数" value={manualForm.shares} onChange={(value) => updateManual('shares', value)} />
          <NumberInput label="可用股数" value={manualForm.availableShares} onChange={(value) => updateManual('availableShares', value)} />
          <NumberInput label="成本价" value={manualForm.costPrice} onChange={(value) => updateManual('costPrice', value)} step="0.01" />
          <NumberInput label="持仓市值" value={manualForm.marketValue} onChange={(value) => updateManual('marketValue', value)} />
          <NumberInput label="现金" value={manualForm.cash} onChange={(value) => updateManual('cash', value)} />
          <NumberInput label="可用现金" value={manualForm.availableCash} onChange={(value) => updateManual('availableCash', value)} />
          <NumberInput label="总资产" value={manualForm.totalAssets} onChange={(value) => updateManual('totalAssets', value)} />
        </div>
        <button
          type="button"
          data-testid="portfolio-create-manual"
          onClick={createManual}
          disabled={loading || !manualForm.symbol.trim() || !canWritePortfolioSnapshots}
          title={writeDisabledReason}
          className="mt-4 inline-flex items-center gap-2 rounded-md bg-[#0b57d0] px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-[#0842a0] disabled:opacity-60"
        >
          <Plus size={16} />
          创建手动快照
        </button>
      </Card>

      <Card title="文件导入">
        <div className="grid gap-4 lg:grid-cols-[1fr_1fr_auto]">
          <TextInput label="导入来源名称" value={importSourceName} onChange={setImportSourceName} />
          <label className="space-y-2 text-sm">
            <span className="font-medium text-slate-700">CSV / XLSX 文件</span>
            <input
              data-testid="portfolio-import-file"
              type="file"
              accept=".csv,.tsv,.xlsx"
              onChange={(event) => {
                setImportFile(event.target.files?.[0] ?? null)
                setImportErrorDetail(null)
                setError('')
              }}
              className="w-full rounded-md border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-900"
            />
          </label>
          {importErrorDetail ? (
            <div data-testid="portfolio-import-error-detail" className="rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800 lg:col-span-3">
              <div className="font-semibold">Import failed: {importErrorDetail.reason || 'IMPORT_VALIDATION_ERROR'}</div>
              {importErrorDetail.jobId ? (
                <div data-testid="portfolio-import-error-job" className="mt-1 font-mono text-xs">
                  job {importErrorDetail.jobId}
                </div>
              ) : null}
              <div className="mt-2 leading-6">
                Required columns: {importErrorDetail.expectedColumns?.required?.join('; ') || 'symbol and shares'}.
              </div>
              <div className="leading-6">
                Accepted files: {(importErrorDetail.acceptedExtensions || ['.csv', '.tsv', '.xlsx']).join(', ')}.
              </div>
              {importErrorDetail.expectedColumns?.recommended?.length ? (
                <div className="mt-2 text-xs leading-5 text-rose-700">
                  Recommended: {importErrorDetail.expectedColumns.recommended.slice(0, 5).join('; ')}.
                </div>
              ) : null}
              {importErrorDetail.observedHeaders?.length ? (
                <div data-testid="portfolio-import-observed-headers" className="mt-2 text-xs leading-5 text-rose-700">
                  Observed headers: {importErrorDetail.observedHeaders.slice(0, 12).join(', ')}.
                </div>
              ) : null}
              {importErrorDetail.missingRequiredFields?.length ? (
                <div className="mt-1 text-xs leading-5 text-rose-700">
                  Missing required fields: {importErrorDetail.missingRequiredFields.join(', ')}.
                </div>
              ) : null}
              {importErrorDetail.rowPreview?.length ? (
                <div data-testid="portfolio-import-row-preview" className="mt-2 space-y-1 rounded border border-rose-200 bg-white/60 p-2 text-xs leading-5 text-rose-800">
                  {importErrorDetail.rowPreview.slice(0, 3).map((row) => (
                    <div key={row.rowNumber || JSON.stringify(row.cells)}>
                      Row {row.rowNumber || '?'}: {formatImportPreviewCells(row.cells)}
                    </div>
                  ))}
                </div>
              ) : null}
              {importErrorDetail.brokerTemplateHint ? (
                <div data-testid="portfolio-import-template-hint" className="mt-2 text-xs leading-5 text-rose-700">
                  Template hint: {importErrorDetail.brokerTemplateHint.brokerTemplateLabel || importErrorDetail.brokerTemplateHint.brokerTemplateId || 'Unknown'} · {formatPercent(importErrorDetail.brokerTemplateHint.templateConfidence ?? 0)}
                </div>
              ) : null}
              {importErrorDetail.templateConfidenceNote ? (
                <div className="mt-1 text-xs leading-5 text-rose-700">
                  {importErrorDetail.templateConfidenceNote}
                </div>
              ) : null}
              {importErrorDetail.repairSuggestions?.length ? (
                <div data-testid="portfolio-import-repair-suggestions" className="mt-2 space-y-1 rounded border border-rose-200 bg-white/60 p-2 text-xs leading-5 text-rose-800">
                  {importErrorDetail.repairSuggestions.slice(0, 4).map((suggestion) => (
                    <div key={suggestion}>{suggestion}</div>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
          <button
            type="button"
            data-testid="portfolio-import-submit"
            onClick={importFileSnapshot}
            disabled={loading || !importFile || !canWritePortfolioSnapshots}
            title={writeDisabledReason}
            className="inline-flex items-center justify-center gap-2 self-end rounded-md bg-[#0b57d0] px-4 py-3 text-sm font-semibold text-white transition hover:bg-[#0842a0] disabled:opacity-60"
          >
            <FileUp size={16} />
            导入快照
          </button>
        </div>
      </Card>

      <Card title="快照列表">
        {snapshots.length ? (
          <TableShell>
            <table className="institution-table">
              <thead className="border-b border-slate-200 bg-[#f8fafd] text-[11px] uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-3 py-2">来源 / 快照</th>
                  <th className="px-3 py-2">资产</th>
                  <th className="px-3 py-2">仓位风险</th>
                  <th className="px-3 py-2">质量</th>
                  <th className="px-3 py-2 text-right">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {snapshots.map((item) => {
                  const risk = portfolioRiskView(item)
                  const evidenceStrength = portfolioEvidenceStrengthLabel(item)
                  const blocker = portfolioSnapshotBlocker(item)
                  const nextAction = portfolioSnapshotNextAction(item)
                  return (
                    <tr key={item.snapshotId} className="align-top hover:bg-[#f8fafd]">
                      <td className="px-3 py-3">
                        <div className="font-semibold text-slate-950">{item.sourceName || item.snapshotId}</div>
                        <div className="mt-1 flex flex-wrap gap-1.5">
                          <Badge status={item.sourceType}>{item.sourceType}</Badge>
                          <span data-testid="portfolio-broker-template" className="inline-flex items-center rounded-full border border-indigo-100 bg-indigo-50 px-2 py-1 text-[11px] font-semibold text-indigo-700">
                            {item.brokerTemplateLabel || item.brokerTemplateId} · {formatPercent(item.templateConfidence)}
                          </span>
                        </div>
                        <div data-testid="portfolio-snapshot-id" className="mt-2 break-all font-mono text-[11px] text-slate-400">{item.snapshotId}</div>
                        <div data-testid={`portfolio-snapshot-governance-${item.snapshotId}`} className="mt-2 space-y-1 rounded-md border border-slate-200 bg-white px-2 py-2 text-[11px] leading-5 text-slate-600">
                          <div className="flex flex-wrap items-center gap-1">
                            <span className="font-semibold text-slate-700">ID</span>
                            <span data-testid={`portfolio-snapshot-governance-id-${item.snapshotId}`} className="break-all font-mono text-slate-500">{item.snapshotId}</span>
                          </div>
                          <div data-testid={`portfolio-snapshot-evidence-strength-${item.snapshotId}`}>证据强度：{evidenceStrength}</div>
                          <div data-testid={`portfolio-snapshot-blocker-${item.snapshotId}`}>阻断：{blocker}</div>
                          <div data-testid={`portfolio-snapshot-next-action-${item.snapshotId}`}>下一步：{nextAction}</div>
                          <div data-testid={`portfolio-snapshot-simulation-boundary-${item.snapshotId}`} className="font-medium text-slate-900">
                            边界：simulation_only={String(item.simulationOnly)} / is_real_trade={String(item.isRealTrade)} / evidence_usage={item.evidenceUsage} / strong_conclusion_allowed={String(item.strongConclusionAllowed)} / SIM_*
                          </div>
                        </div>
                      </td>
                      <td className="px-3 py-3 text-slate-700">
                        <div className="font-semibold text-slate-950">{formatMoney(item.totalAssets)}</div>
                        <div className="mt-1">市值 {formatMoney(item.stockMarketValue)} · 现金 {formatMoney(item.cash)}</div>
                        <div className="mt-1 text-slate-500">{item.positionCount} 只持仓 · {formatDateLabel(item.updatedAt || item.importedAt)}</div>
                      </td>
                      <td className="px-3 py-3">
                        <div className="flex items-center justify-between gap-2 text-slate-600">
                          <span>总仓位</span>
                          <span className="font-semibold text-slate-950">{formatPercent(item.totalPositionRatio)}</span>
                        </div>
                        <div className="mt-1 h-1.5 rounded-full bg-slate-100">
                          <div className="h-1.5 rounded-full bg-[#1a73e8]" style={{ width: `${Math.min(100, item.totalPositionRatio * 100)}%` }} />
                        </div>
                        <div className="mt-2 flex items-center justify-between gap-2 text-slate-600">
                          <span>最大单票</span>
                          <span className="font-semibold text-slate-950">{formatPercent(item.maxSinglePositionRatio)}</span>
                        </div>
                        <div className="mt-1 h-1.5 rounded-full bg-slate-100">
                          <div className={`h-1.5 rounded-full ${risk.barClass}`} style={{ width: `${Math.min(100, item.maxSinglePositionRatio * 100)}%` }} />
                        </div>
                      </td>
                      <td className="px-3 py-3">
                        <Badge status={qualityBadgeStatus(item.qualityStatus)}>{item.qualityStatus}</Badge>
                        <div className="mt-2 text-slate-600">{risk.label}</div>
                        {item.templateWarnings.length ? (
                          <div className="mt-2 rounded-md border border-amber-200 bg-amber-50 px-2 py-1.5 text-[11px] leading-5 text-amber-800">
                            {item.templateWarnings.slice(0, 2).join(' ')}
                          </div>
                        ) : null}
                      </td>
                      <td className="px-3 py-3">
                        <div className="flex flex-wrap items-center justify-end gap-2">
                          <Link
                            to={`/new-task?portfolio_snapshot_id=${encodeURIComponent(item.snapshotId)}`}
                            data-testid="portfolio-use-new-task"
                            className="inline-flex items-center gap-2 rounded-md bg-[#0b57d0] px-3 py-2 text-sm font-semibold text-white transition hover:bg-[#0842a0]"
                          >
                            <Play size={14} />
                            用于新任务
                          </Link>
                          <button
                            type="button"
                            onClick={() => removeSnapshot(item.snapshotId)}
                            disabled={loading || !canDeletePortfolioSnapshots}
                            title={deleteDisabledReason}
                            className="inline-flex items-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50 disabled:opacity-60"
                          >
                            <Trash2 size={14} />
                            删除
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </TableShell>
        ) : (
          <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 p-6 text-sm text-slate-600">
            暂无组合快照。请创建样例、手动录入或导入文件后再进入新建任务。
          </div>
        )}
      </Card>

      {selectedSummary ? (
        <Card title="当前可用于任务的快照" action={<Badge status={qualityBadgeStatus(selectedSummary.qualityStatus)}>{selectedSummary.qualityStatus}</Badge>}>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
            <MetricTile label="来源" value={selectedSummary.sourceName || selectedSummary.snapshotId} helper={selectedSummary.sourceType} icon={Database} tone="info" />
            <MetricTile label="持仓数量" value={String(selectedSummary.positionCount)} helper="传入新建任务的组合上下文" icon={Layers} tone="neutral" />
            <MetricTile label="总资产" value={formatMoney(selectedSummary.totalAssets)} helper={`现金 ${formatMoney(selectedSummary.cash)}`} icon={Activity} tone="neutral" />
            <MetricTile label="仓位" value={formatPercent(selectedSummary.totalPositionRatio)} helper={`最大单票 ${formatPercent(selectedSummary.maxSinglePositionRatio)}`} icon={ShieldCheck} tone={selectedRisk.tone} />
            <MetricTile label="导入模板" value={selectedSummary.brokerTemplateLabel || selectedSummary.brokerTemplateId} helper={formatPercent(selectedSummary.templateConfidence)} icon={FileUp} tone="info" />
          </div>
          <div className="mt-4 rounded-md border border-slate-200 bg-[#f8fafd] px-3 py-2 text-sm text-slate-600">
            <div className="flex flex-wrap items-center gap-2">
              <AlertTriangle size={15} className={selectedRisk.textClass} />
              <span className="font-semibold text-slate-950">组合风险</span>
              <span>{selectedRisk.label}</span>
            </div>
            <div className="mt-1 text-xs leading-5 text-slate-500">{selectedRisk.helper}</div>
          </div>
          {selectedPositions.length ? (
            <TableShell className="mt-4">
              <table className="institution-table">
                <thead className="border-b border-slate-200 bg-white text-[11px] uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="px-3 py-2">标的</th>
                    <th className="px-3 py-2">数量</th>
                    <th className="px-3 py-2">市值 / 权重</th>
                    <th className="px-3 py-2">风险因子</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {selectedPositions.slice(0, 8).map((position) => (
                    <tr key={`${position.symbol}-${position.updatedAt || position.marketValue}`} className="align-top">
                      <td className="px-3 py-2.5">
                        <div className="font-semibold text-slate-950">{position.symbol} {position.name}</div>
                        <div className="mt-1 text-slate-500">{[position.industry, position.style, position.theme].filter(Boolean).join(' / ') || '-'}</div>
                      </td>
                      <td className="px-3 py-2.5 text-slate-700">{position.shares.toLocaleString()} 股</td>
                      <td className="px-3 py-2.5">
                        <div className="font-semibold text-slate-950">{formatMoney(position.marketValue)}</div>
                        <div className="mt-1 h-1.5 rounded-full bg-slate-100">
                          <div className="h-1.5 rounded-full bg-[#1a73e8]" style={{ width: `${Math.min(100, (position.weight || 0) * 100)}%` }} />
                        </div>
                        <div className="mt-1 text-slate-500">{formatPercent(position.weight || 0)}</div>
                      </td>
                      <td className="px-3 py-2.5 text-slate-600">{position.riskFactor || '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableShell>
          ) : null}
        </Card>
      ) : null}
    </div>
  )

  function updateManual<K extends keyof typeof initialManualForm>(key: K, value: (typeof initialManualForm)[K]) {
    setManualForm((current) => ({ ...current, [key]: value }))
  }
}

function extractPortfolioImportErrorDetail(error: unknown): PortfolioImportErrorDetail | null {
  if (error instanceof ApiError && isPortfolioImportErrorDetail(error.detail)) {
    return error.detail
  }
  if (error && typeof error === 'object' && 'detail' in error) {
    const detail = (error as { detail?: unknown }).detail
    return isPortfolioImportErrorDetail(detail) ? detail : null
  }
  return null
}

function isPortfolioImportErrorDetail(value: unknown): value is PortfolioImportErrorDetail {
  return Boolean(
    value
      && typeof value === 'object'
      && typeof (value as PortfolioImportErrorDetail).message === 'string'
      && typeof (value as PortfolioImportErrorDetail).jobId === 'string'
      && typeof (value as PortfolioImportErrorDetail).reason === 'string',
  )
}

function formatImportPreviewCells(cells?: Record<string, string>) {
  const entries = Object.entries(cells || {}).slice(0, 6)
  if (!entries.length) return '-'
  return entries.map(([key, value]) => `${key}=${value || '-'}`).join('; ')
}

function TextInput({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="space-y-2 text-sm">
      <span className="font-medium text-slate-700">{label}</span>
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-md border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-[#1a73e8] focus:ring-2 focus:ring-[#1a73e8]/15"
      />
    </label>
  )
}

function NumberInput({
  label,
  value,
  onChange,
  step = '1',
}: {
  label: string
  value: number
  onChange: (value: number) => void
  step?: string
}) {
  return (
    <label className="space-y-2 text-sm">
      <span className="font-medium text-slate-700">{label}</span>
      <input
        type="number"
        min={0}
        step={step}
        value={value}
        onChange={(event: ChangeEvent<HTMLInputElement>) => onChange(Number(event.target.value))}
        className="w-full rounded-md border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-[#1a73e8] focus:ring-2 focus:ring-[#1a73e8]/15"
      />
    </label>
  )
}

function formatMoney(value: number) {
  return `¥${Number(value || 0).toLocaleString('zh-CN', { maximumFractionDigits: 0 })}`
}

function formatPercent(value: number) {
  return `${(Number(value || 0) * 100).toFixed(1)}%`
}

function formatDateLabel(value?: string) {
  if (!value) return '-'
  return value.slice(0, 10)
}

function qualityBadgeStatus(value: string) {
  const normalized = String(value || '').toUpperCase()
  if (['READY', 'PASS', 'OK', 'HEALTHY', 'VALID'].includes(normalized)) return 'PASS'
  if (['FAILED', 'FAIL', 'INVALID', 'ERROR'].includes(normalized)) return 'FAIL'
  return 'WARN'
}

function portfolioQualityIsUsable(snapshot: PortfolioSnapshotSummary) {
  const normalized = String(snapshot.qualityStatus || '').toUpperCase()
  return ['READY', 'PASS', 'OK', 'HEALTHY', 'VALID'].includes(normalized)
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

function portfolioEvidenceStrengthLabel(snapshot: PortfolioSnapshotSummary) {
  const apiStrength = reviewGateEvidenceStrength(snapshot.evidenceStrength)
  if (apiStrength === 'MEDIUM') return 'MEDIUM：组合快照可作辅助上下文'
  if (apiStrength === 'LOW') return 'LOW：组合质量需复核'
  if (apiStrength === 'MISSING') return 'MISSING：无持仓证据'
  if (apiStrength === 'PENDING') return 'PENDING：等待组合复核'
  const sourceType = String(snapshot.sourceType || '').toUpperCase()
  if (snapshot.positionCount <= 0) return 'MISSING：无持仓证据'
  if (!portfolioQualityIsUsable(snapshot) || snapshot.issueCount > 0) return 'LOW：质量需复核'
  if (sourceType === 'IMPORTED') {
    if (snapshot.templateConfidence >= 0.8) return 'MEDIUM：导入模板已匹配'
    return 'LOW：导入模板需复核'
  }
  if (sourceType === 'MANUAL') return 'MEDIUM：手动快照需复核'
  if (sourceType === 'SAMPLE') return 'LOW：样例快照仅限演示'
  return 'LOW：来源需复核'
}

function portfolioSnapshotBlocker(snapshot: PortfolioSnapshotSummary) {
  if (snapshot.positionCount <= 0) return '缺少持仓，不能形成有效上下文'
  if (!portfolioQualityIsUsable(snapshot)) return `质量状态：${snapshot.qualityStatus || 'UNKNOWN'}`
  if (snapshot.issueCount > 0) return `${snapshot.issueCount} 项质量问题`
  if (snapshot.totalPositionRatio > 1) return '总仓位超过资产'
  if (snapshot.maxSinglePositionRatio > 0.4) return '单票集中度超过 40%'
  return '无阻断，等待任务使用'
}

function portfolioSnapshotNextAction(snapshot: PortfolioSnapshotSummary) {
  const sourceType = String(snapshot.sourceType || '').toUpperCase()
  if (snapshot.positionCount <= 0) return '重新导入或补录持仓'
  if (!portfolioQualityIsUsable(snapshot) || snapshot.issueCount > 0) return '修复导入质量后再使用'
  if (sourceType === 'IMPORTED' && snapshot.templateConfidence < 0.7) return '复核券商模板映射'
  if (snapshot.maxSinglePositionRatio > 0.4 || snapshot.totalPositionRatio >= 0.9) return '进入新任务前复核风险'
  return '用于新任务'
}

function portfolioRiskView(snapshot?: PortfolioSnapshotSummary) {
  if (!snapshot) {
    return {
      label: '等待快照',
      helper: '创建或导入组合快照后展示仓位集中度。',
      tone: 'neutral' as const,
      barClass: 'bg-slate-300',
      textClass: 'text-slate-500',
    }
  }
  if (snapshot.issueCount > 0) {
    return {
      label: `${snapshot.issueCount} 项质量问题`,
      helper: '导入校验存在问题，进入新任务前应先复核字段映射和持仓数量。',
      tone: 'danger' as const,
      barClass: 'bg-red-500',
      textClass: 'text-red-600',
    }
  }
  if (snapshot.maxSinglePositionRatio >= 0.35 || snapshot.totalPositionRatio >= 0.9) {
    return {
      label: '集中度偏高',
      helper: `总仓位 ${formatPercent(snapshot.totalPositionRatio)}，最大单票 ${formatPercent(snapshot.maxSinglePositionRatio)}。`,
      tone: 'warning' as const,
      barClass: 'bg-amber-500',
      textClass: 'text-amber-600',
    }
  }
  return {
    label: '风险正常',
    helper: `总仓位 ${formatPercent(snapshot.totalPositionRatio)}，最大单票 ${formatPercent(snapshot.maxSinglePositionRatio)}。`,
    tone: 'success' as const,
    barClass: 'bg-[#34a853]',
    textClass: 'text-emerald-600',
  }
}
