# 控制台首页“决策优先指挥台” Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 把现有控制台首页改造成 A 方案“决策优先指挥台”，让用户在 30 秒内识别当前结论、首要阻断和下一步，同时保持运行深链、刷新、证据、Agent、认证和 simulation-only 边界兼容。

**Architecture:** DashboardPage 继续作为唯一协调层，负责 store、URL 水合、刷新和既有治理计算；buildDashboardDecisionViewModel 是无副作用的保守映射器；DashboardDecisionCommandCenter 只渲染 props。实施顺序为纯映射器测试、静态守卫、首页接线、证据/Agent 收拢、响应式/无障碍加固、全量验证和 Sites 发布。

**Tech Stack:** React 18、TypeScript、Vite、Tailwind CSS、Lucide、Zustand、PowerShell smoke、Node assert、TypeScript compiler API、Codex 内置浏览器、Sites。

## Global Constraints

- 设计依据：docs/superpowers/specs/2026-07-15-dashboard-homepage-decision-command-center-design.md。
- 视觉依据：用户选定的 A 方案。临时参考 .superpowers/brainstorm/432-1784054940/content/dashboard-direction-a.html 只用于对照，保持未跟踪，不提交。
- 不新增后端接口、数据库迁移、认证/session/cookie 修改、页面或路由。
- 不移动 buildDashboardRunGovernance、dashboardRunEvidenceStrength、buildSortedAgents 或 store 请求逻辑。
- 映射器只能保持或降低结论强度，不能把 REVIEW_ONLY、REJECT、BLOCK、BLOCK_BUY、FAIL、FAILED、ERROR 提升为更积极结论。
- 过期只识别既有 STALE 运行状态或 provenance/freshness 过期标记，不新增展示层 TTL。
- 缺失值显示“—”或“未配置”；只有输入明确提供数值零时才显示 0。
- 四个机器边界值原样可见：simulationOnly、isRealTrade、evidenceUsage、strongConclusionAllowed。
- 保留 run_id 水合门禁、query/hash、刷新、自动刷新、继续分析入口和现有 data-testid。
- 保留 Core 解读、行情快照、关键核验、运行约束、K 线、QIAM、仓位、知识回归和 LLM 健康；只删除迁入命令中心后的重复证据/Agent 卡。
- 不改 lockfile、不新增测试依赖；仓库只有 npm lockfile，命令以 npm.cmd 为准。
- 未跟踪 .superpowers/ 不得清理、暂存或提交。
- 每个任务先运行指定 RED，再写最小实现达到 GREEN；提交前运行 git diff --check。

## Stable Contracts

可移动但不能删除或改名：

- dashboard-page
- dashboard-page-loading
- dashboard-load-local-sample
- dashboard-decision-workbench
- dashboard-current-run-id
- dashboard-run-governance
- dashboard-run-governance-id
- dashboard-run-evidence-strength
- dashboard-run-blocker
- dashboard-run-next-action
- dashboard-run-simulation-boundary
- dashboard-trade-boundary
- dashboard-data-provenance
- dashboard-evidence-spine
- dashboard-source-freshness
- dashboard-agent-chain
- dashboard-agent-compatibility- 动态前缀

新增稳定标识：

- dashboard-decision-command-center
- dashboard-decision-hero
- dashboard-primary-conclusion
- dashboard-primary-blockers
- dashboard-primary-next-actions
- dashboard-metric-strip
- dashboard-refresh-error
- dashboard-auto-refresh
- dashboard-refresh-now
- dashboard-evidence-table
- dashboard-agent-decision-table

dashboard-run-simulation-boundary 的可见文本继续包含：

    simulation_only=true
    is_real_trade=false
    evidence_usage=simulation_only
    strong_conclusion_allowed=false
    SIM_*

### Task 1: 用七类决策矩阵锁定纯视图模型

**Files:**

- Create: scripts/test-dashboard-decision-view-model.mjs
- Create: frontend/src/utils/dashboardDecisionViewModel.ts
- Modify: package.json
- Test: scripts/test-dashboard-decision-view-model.mjs

- [ ] **Step 1: 先添加测试入口，不创建生产映射器**

在 package.json 的 scripts 中加入：

    "test:frontend:dashboard-decision": "node scripts\\test-dashboard-decision-view-model.mjs",
    "test:frontend": "npm.cmd run test:frontend:dashboard-decision && npm.cmd run typecheck",

根脚本 test 保持后端测试入口。

- [ ] **Step 2: 写无新依赖的 RED harness**

脚本必须：fs.access 检查生产文件；优先 import typescript、失败时回退到 frontend/node_modules/typescript/lib/typescript.js；用 ts.transpileModule 转 ES2022；拒绝 error diagnostic 和运行时 import；写入 .tmp/dashboard-decision-view-model 后动态 import；在 finally 删除临时目录。

核心骨架：

    import assert from 'node:assert/strict'
    import fs from 'node:fs/promises'
    import path from 'node:path'
    import { fileURLToPath, pathToFileURL } from 'node:url'

    const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
    const sourcePath = path.join(repoRoot, 'frontend', 'src', 'utils', 'dashboardDecisionViewModel.ts')
    const tempDir = path.join(repoRoot, '.tmp', 'dashboard-decision-view-model')
    const outputPath = path.join(tempDir, 'dashboardDecisionViewModel.mjs')
    const sourceExists = await fs.access(sourcePath).then(() => true, () => false)
    assert.equal(sourceExists, true, 'dashboardDecisionViewModel.ts must exist')

    let tsModule
    try {
      tsModule = await import('typescript')
    } catch {
      tsModule = await import(pathToFileURL(
        path.join(repoRoot, 'frontend', 'node_modules', 'typescript', 'lib', 'typescript.js'),
      ).href)
    }
    const ts = tsModule.default ?? tsModule
    await fs.rm(tempDir, { recursive: true, force: true })

    try {
      const source = await fs.readFile(sourcePath, 'utf8')
      const transpiled = ts.transpileModule(source, {
        fileName: sourcePath,
        reportDiagnostics: true,
        compilerOptions: {
          target: ts.ScriptTarget.ES2022,
          module: ts.ModuleKind.ES2022,
          strict: true,
        },
      })
      const errors = (transpiled.diagnostics ?? []).filter(
        (item) => item.category === ts.DiagnosticCategory.Error,
      )
      assert.deepEqual(errors, [], 'view-model TypeScript transpilation must be error-free')
      assert.doesNotMatch(transpiled.outputText, /^\s*import\s/m)
      await fs.mkdir(tempDir, { recursive: true })
      await fs.writeFile(outputPath, transpiled.outputText, 'utf8')
      const module = await import(pathToFileURL(outputPath).href + '?t=' + Date.now())
      assert.equal(typeof module.buildDashboardDecisionViewModel, 'function')
      runAllCases(module.buildDashboardDecisionViewModel)
    } finally {
      await fs.rm(tempDir, { recursive: true, force: true })
    }

runAllCases 必须有七个具名场景和实际断言：

1. complete-data：WAIT 保持 WAIT；身份、更新时间、六指标、证据/Agent 行和边界正确。
2. partial-critical-fields：缺 updatedAt/evidenceScorePercent 时降级 REVIEW_ONLY；显示“—”而不是 0；阻断含“关键数据缺失”。
3. request-failure：HTTP 503 降级；错误为首要阻断、重试为第一下一步；最后证据/Agent/更新时间保留。
4. stale-data：STALE 导致 isStale、REVIEW_ONLY 和“数据已过期”。
5. empty-data：无 0、0%、0/0 伪值；表格为空；REVIEW_ONLY。
6. boundary-violation：false/true/live_trade/true 原样输出；critical；首阻断为 Analysis run simulation-only boundary violated；第一下一步为“停止移交，先修复 simulation-only boundary”。
7. does-not-upgrade-review-only：HIGH/READY 也不能升级 REVIEW_ONLY。

- [ ] **Step 3: 运行 RED**

    npm.cmd run test:frontend:dashboard-decision

Expected:

    AssertionError [ERR_ASSERTION]: dashboardDecisionViewModel.ts must exist

- [ ] **Step 4: 实现自包含映射器**

生产文件只允许 import type：

    import type { DashboardProvenanceSummary } from './dataProvenance'

公开输出：

    export type DashboardDecisionTone = 'neutral' | 'warning' | 'critical'
    export type DashboardDisplayStatus = 'PASS' | 'WARN' | 'FAIL' | 'WAIT'
    export type DashboardMetricKey =
      | 'evidence'
      | 'sources'
      | 'blockers'
      | 'agents'
      | 'freshness'
      | 'boundary'

    export interface DashboardMetricItem {
      key: DashboardMetricKey
      label: string
      value: string
      helper: string
      status: DashboardDisplayStatus
    }

    export interface DashboardDecisionBoundary {
      simulationOnly?: boolean
      isRealTrade?: boolean
      evidenceUsage?: string
      strongConclusionAllowed?: boolean
      hasViolation: boolean
    }

    export interface DashboardDecisionViewModel {
      conclusion: {
        status: string
        label: string
        summary: string
        tone: DashboardDecisionTone
      }
      context: {
        runId: string
        symbol: string
        stockName: string
        runStatus: string
        updatedAt: string
        isStale: boolean
      }
      governance: {
        contextId: string
        evidenceStrength: 'MEDIUM' | 'LOW'
        blocker: string
        nextAction: string
      }
      metrics: DashboardMetricItem[]
      blockers: string[]
      nextActions: string[]
      evidenceRows: DashboardEvidenceRow[]
      agentRows: DashboardAgentRow[]
      boundary: DashboardDecisionBoundary
    }

输入类型精确使用现有结构的可选子集：

    export interface DashboardDecisionViewModelInput {
      run?: {
        runId?: string
        stockCode?: string
        stockName?: string
        status?: string
        updatedAt?: string
        finalAction?: string
        finalWriter?: { finalAction?: string }
      } | null
      workbench?: {
        summary?: {
          decisionState?: string
          headline?: string
          blockers?: string[]
          warnings?: string[]
          nextReview?: string[]
          metrics?: {
            evidenceScore?: number
            sourceReadyCount?: number
            sourceTotalCount?: number
            activeAgentCount?: number
            blockedAgentCount?: number
          }
        }
        evidenceScorePercent?: number
        sourceRatioLabel?: string
        primaryBlocker?: string
        primaryWarning?: string
        nextReviewRows?: string[]
      } | null
      provenance?: DashboardProvenanceSummary | null
      governance?: DashboardDecisionGovernanceInput | null
      dataSources?: DashboardDecisionDataSourceInput[]
      agents?: DashboardDecisionAgentInput[]
      requestError?: string | null
    }

    export function buildDashboardDecisionViewModel(
      input: DashboardDecisionViewModelInput,
    ): DashboardDecisionViewModel

其余接口精确为：

    export interface DashboardDecisionGovernanceInput {
      contextId?: string
      evidenceStrength?: 'MEDIUM' | 'LOW'
      blocker?: string
      nextAction?: string
      simulationOnly?: boolean
      isRealTrade?: boolean
      evidenceUsage?: string
      strongConclusionAllowed?: boolean
    }

    export interface DashboardDecisionDataSourceInput {
      key: string
      name: string
      provider: string
      status: string
      detail: string
      fetchedAt?: string
      freshness?: string
      available: boolean
      error?: string
      degradationReason?: string
      dataMode?: string
    }

    export interface DashboardDecisionAgentInput {
      node: string
      name: string
      status: string
      reason: string
      isSkipped: boolean
      isBlocked: boolean
      hardStop: boolean
      skippedReason?: string
      auditId: string
      legacyCompatibilityOnly?: boolean
      canonicalNode?: string
      activeNode?: string
    }

    export interface DashboardEvidenceRow {
      key: string
      sourceName: string
      provider: string
      status: string
      freshness: string
      fetchedAt: string
      evidenceLevel: string
      detail: string
      missingReason: string
      dataMode: string
    }

    export interface DashboardAgentRow {
      node: string
      name: string
      status: string
      summary: string
      isBlocked: boolean
      hardStop: boolean
      isSkipped: boolean
      compatibilityOnly: boolean
      auditId: string
    }

确定性规则：

1. boundarySafe 仅四项严格等于 true/false/simulation_only/false 时成立。
2. isStale 仅来自 STALE，freshness status FAIL，或文本含 STALE、EXPIRED、过期。
3. criticalMissing 包含 runId、stockCode、status、updatedAt、headline、evidenceScorePercent、provenance、四个 boundary 字段，以及 provenance.missingFields。
4. boundary 违规、FAILED/STALE/CANCELLED、requestError 或 criticalMissing 触发降级。
5. REJECT/BLOCK/BLOCK_BUY/FAIL/FAILED/ERROR 保持原值；其他不安全状态变 REVIEW_ONLY；无原结论也为 REVIEW_ONLY。
6. blockers 优先级：边界、请求失败、失败/过期、关键缺失、workbench blockers、provenance warnings、人工复核 fallback。
7. nextActions 优先级：修复边界、重试、刷新过期、补缺失、governance.nextAction、nextReviewRows；边界违规时过滤“下单/实盘/执行交易”动作。
8. metrics 固定 evidence、sources、blockers、agents、freshness、boundary；缺失显示“—”。
9. evidenceRows 用 key 对齐 dataSources、provenance.items、freshnessItems；未匹配项不得串值。
10. agentRows 原样映射 SortedAgent；auditId 是唯一证据引用。

- [ ] **Step 5: 运行 GREEN**

    npm.cmd run test:frontend:dashboard-decision
    npm.cmd run typecheck
    node --check scripts\test-dashboard-decision-view-model.mjs

Expected 最后一行：

    ok dashboard decision view model cases=7

- [ ] **Step 6: 提交**

    git diff --check
    git add package.json scripts/test-dashboard-decision-view-model.mjs frontend/src/utils/dashboardDecisionViewModel.ts
    git commit -m "feat: add dashboard decision view model"

### Task 2: 先收紧静态守卫，再接入结论、阻断、下一步和指标

**Files:**

- Create: frontend/src/components/dashboard/DashboardDecisionCommandCenter.tsx
- Modify: frontend/src/components/dashboard/DashboardPage.tsx
- Modify: scripts/smoke-frontend-routes.ps1
- Test: scripts/smoke-frontend-routes.ps1

- [ ] **Step 1: 先扩展 smoke 的源码边界**

在 dashboard 源码读取区加入：

    $dashboardDecisionCommandCenterPath = Join-Path $frontendRoot "src\components\dashboard\DashboardDecisionCommandCenter.tsx"
    $dashboardDecisionViewModelPath = Join-Path $frontendRoot "src\utils\dashboardDecisionViewModel.ts"
    $dashboardDecisionTestPath = Join-Path $repoRoot "scripts\test-dashboard-decision-view-model.mjs"

    foreach ($requiredPath in @(
      $dashboardDecisionCommandCenterPath,
      $dashboardDecisionViewModelPath,
      $dashboardDecisionTestPath
    )) {
      if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Dashboard decision command center contract file is missing: $requiredPath"
      }
    }

    $dashboardDecisionCommandCenterSource = Get-Content -LiteralPath $dashboardDecisionCommandCenterPath -Raw -Encoding UTF8
    $dashboardDecisionViewModelSource = Get-Content -LiteralPath $dashboardDecisionViewModelPath -Raw -Encoding UTF8
    $dashboardDecisionTestSource = Get-Content -LiteralPath $dashboardDecisionTestPath -Raw -Encoding UTF8
    $dashboardPresentationSource = @(
      $dashboardSource,
      $dashboardDecisionCommandCenterSource
    ) -join [Environment]::NewLine

presentation testid 改查 $dashboardPresentationSource；fallbackToMock、dashboard-page/loading、governance helper、workbench 和 run_id 水合仍只查 $dashboardSource。

新增断言：DashboardPage import/call buildDashboardDecisionViewModel；import/render DashboardDecisionCommandCenter；package script 与七场景存在；新 hero/conclusion/blocker/next/metric/refresh testid 存在。

- [ ] **Step 2: 运行 RED**

    npm.cmd run smoke:frontend -- -Routes /

Expected:

    Dashboard decision command center contract file is missing

- [ ] **Step 3: 创建纯展示组件的第一阶段**

公开 props：

    export interface DashboardDecisionCommandCenterProps {
      model: DashboardDecisionViewModel
      autoRefreshEnabled: boolean
      showRefreshControls: boolean
      dataSourcesExpanded: boolean
      onToggleAutoRefresh: () => void
      onRefresh: () => void
      onToggleDataSources: () => void
    }

同文件定义 DecisionHero、MetricStrip、BlockerPanel、NextActionPanel、EvidenceTable、AgentDecisionTable；本任务先渲染前四个。

根节点是 dashboard-decision-command-center。基础 DOM 顺序为 Hero、Blocker、Next Action、Metrics；lg 用 order 把 Metrics 视觉提升到第二层。Hero：

- 保留唯一 h1；
- 大结论 role="status"；
- time dateTime 显示更新时间；
- 完整显示 runId；
- 保留全部 dashboard-run-governance、dashboard-trade-boundary 和 dashboard-current-run-id 标识；
- 原样显示四个边界字段和 SIM_*；
- 按钮使用 dashboard-refresh-now/dashboard-auto-refresh、min-h-11、aria-pressed、aria-hidden 图标和 focus-visible。

MetricStrip 用 dl/dt/dd；BlockerPanel 用 ul；NextActionPanel 用 ol；metric icon 根据 key 在组件内映射 Lucide。

- [ ] **Step 4: 在 DashboardPage 增加 run-scoped 刷新失败**

    type DashboardRefreshFailure = {
      runId: string
      message: string
    }

    const [refreshFailure, setRefreshFailure] = useState<DashboardRefreshFailure | null>(null)

    const handleRefresh = useCallback(async (runId: string) => {
      try {
        await refreshRun(runId)
        setRefreshFailure((current) => current?.runId === runId ? null : current)
      } catch (error) {
        setRefreshFailure({
          runId,
          message: error instanceof Error ? error.message : '刷新当前运行失败',
        })
      }
    }, [refreshRun])

把 useCallback 加入 React import。自动刷新 interval 调用 void handleRefresh(currentRunId)，依赖数组使用 currentRunId、currentRun?.status、handleRefresh、autoRefreshEnabled、autoRefreshInterval。currentRunId 变化时仅保留同 runId 错误。refreshRun 的 toast/rethrow 不变。

- [ ] **Step 5: 接线并替换旧首屏上半部**

在现有派生数据准备后：

    const decisionViewModel = buildDashboardDecisionViewModel({
      run: currentRun,
      workbench,
      provenance: provenanceSummary,
      governance: dashboardGovernance,
      dataSources: dataSourceList,
      agents: sortedAgents,
      requestError: refreshFailure?.runId === currentRun.runId
        ? refreshFailure.message
        : null,
    })

保留 dashboard-decision-workbench 外层，渲染：

    <DashboardDecisionCommandCenter
      model={decisionViewModel}
      autoRefreshEnabled={autoRefreshEnabled}
      showRefreshControls={currentRun.status === 'RUNNING'}
      dataSourcesExpanded={dataSourcesExpanded}
      onToggleAutoRefresh={() => setAutoRefresh(!autoRefreshEnabled)}
      onRefresh={() => void handleRefresh(currentRun.runId)}
      onToggleDataSources={() => setDataSourcesExpanded((value) => !value)}
    />

替换旧标题、failure notice、governance、trade boundary、下一步复核和 decisionTiles；保留 CoreInterpretationOverview、行情快照、关键核验、运行约束。删除无引用的 decisionTiles/DecisionTile，不删除仍使用的 MetricCell/StatusRow。

- [ ] **Step 6: 运行 GREEN**

    npm.cmd run test:frontend:dashboard-decision
    npm.cmd run typecheck
    npm.cmd run smoke:frontend -- -Routes /
    npm.cmd run lint

Expected smoke 包含 ok frontend weak-link contracts 和 ok /。

- [ ] **Step 7: 提交**

    git diff --check
    git add frontend/src/components/dashboard/DashboardDecisionCommandCenter.tsx frontend/src/components/dashboard/DashboardPage.tsx scripts/smoke-frontend-routes.ps1
    git commit -m "feat: add dashboard decision command center"

### Task 3: 将证据与 Agent 无损迁入命令中心

**Files:**

- Modify: frontend/src/components/dashboard/DashboardDecisionCommandCenter.tsx
- Modify: frontend/src/components/dashboard/DashboardPage.tsx
- Modify: frontend/src/utils/dashboardDecisionViewModel.ts
- Modify: scripts/test-dashboard-decision-view-model.mjs
- Modify: scripts/smoke-frontend-routes.ps1
- Test: scripts/test-dashboard-decision-view-model.mjs
- Test: scripts/smoke-frontend-routes.ps1

- [ ] **Step 1: 先添加迁移 RED guard**

要求命令中心包含 dashboard-data-provenance、dashboard-evidence-spine、dashboard-source-freshness、dashboard-evidence-table、dashboard-agent-chain、dashboard-agent-decision-table、dashboard-agent-compatibility-、table、caption 和 scope="col"。

禁止页面继续渲染重复卡：

    if ($dashboardSource -match '<Card[\s\r\n]+title="证据与数据"' -or
        $dashboardSource.Contains('<Card title="Agent 执行链">')) {
      throw "DashboardPage still renders duplicate evidence or agent cards outside the command center"
    }

- [ ] **Step 2: 运行 RED**

    npm.cmd run smoke:frontend -- -Routes /

Expected 包含 duplicate evidence or agent cards。

- [ ] **Step 3: 补强表格映射测试**

complete-data 断言 dataSources 顺序、同 key provenance/freshness 联结、全部来源字段、SortedAgent 顺序、compatibilityOnly/hardStop/isSkipped/auditId。增加 key 不匹配负例，必须显示“未配置”或“—”，不能串用其他来源。

- [ ] **Step 4: 实现 EvidenceTable**

- 保留 dashboard-data-provenance/evidence-spine/source-freshness；
- 桌面 table + sr-only caption + scope="col"；
- 手机 dl 卡片；两套表现用 CSS display 互斥；
- 默认前 5 行，展开后全部，按钮 aria-expanded；
- 缺失显示“—”或 missingReason；
- 状态同时有文字与视觉；
- table 容器 overflow-x-auto，document 不横向溢出。

- [ ] **Step 5: 实现 AgentDecisionTable**

- 保留 dashboard-agent-chain；
- 桌面 table、手机 dl 均显示 Agent、状态、摘要、阻断/硬停止、auditId；
- compatibility 行使用 data-testid={"dashboard-agent-compatibility-" + row.node}；
- auditId 完整 break-all；
- SKIPPED/BLOCKED/hard stop/legacy compatibility 有文字；
- 空数组显示“暂无 Agent 执行数据”。

- [ ] **Step 6: 删除重复卡并清理死代码**

删除 DashboardPage 当前约 2325–2584 的旧证据/Agent 卡；保留仓位、知识回归、LLM 健康和研究闭环。用 rg 逐项确认后清理 visibleDataSourceList、hiddenDataSourceCount、无引用的 dataSourceReadyRatio、旧展示 helper/icon。保留 MetricCell、StatusRow、CoreInterpretationOverview、buildSortedAgents 和兼容归一化。

- [ ] **Step 7: 运行 GREEN**

    npm.cmd run test:frontend:dashboard-decision
    npm.cmd run typecheck
    npm.cmd run lint
    npm.cmd run smoke:frontend -- -Routes /

- [ ] **Step 8: 提交**

    git diff --check
    git add frontend/src/components/dashboard/DashboardDecisionCommandCenter.tsx frontend/src/components/dashboard/DashboardPage.tsx frontend/src/utils/dashboardDecisionViewModel.ts scripts/test-dashboard-decision-view-model.mjs scripts/smoke-frontend-routes.ps1
    git commit -m "feat: consolidate dashboard evidence and agents"

### Task 4: 锁定移动端顺序、触控和无障碍

**Files:**

- Modify: frontend/src/components/dashboard/DashboardDecisionCommandCenter.tsx
- Modify: scripts/smoke-frontend-routes.ps1
- Test: scripts/smoke-frontend-routes.ps1
- Verify: scripts/smoke-frontend-responsive.mjs

- [ ] **Step 1: 先添加无障碍 RED contract**

仅针对命令中心源码断言：

- 源码 DOM 顺序为 hero → blockers → next-actions → metric-strip → data-provenance → agent-chain；
- 主按钮含 min-h-11；
- 自动刷新含 aria-pressed；
- 表格含 sr-only caption 和 scope="col"；
- runId、auditId、边界值含 break-all/font-mono；
- 新 transition 含 motion-reduce:transition-none；
- 不含 outline-none；
- 状态图标含 aria-hidden。

用 IndexOf 比较标识顺序，不使用整段 JSX 快照。

- [ ] **Step 2: 运行 RED**

    npm.cmd run smoke:frontend -- -Routes /

Expected: 至少一个顺序、44px 或语义断言失败。

- [ ] **Step 3: 完成响应式与无障碍类名**

继续现有视觉语言：#1a73e8/#1967d2 主色、#f8fafd/#e8f0fe 背景、#dfe3eb 边框、现有警告/错误色、rounded-md、轻阴影；不新增 CSS 文件或平行 token。

布局：

- 390/768：Hero → Blocker → Next Action → Metrics → Evidence → Agent；
- lg：Hero → Metrics → Blocker/Next 双栏 → Evidence/Agent；
- xl 可把 Evidence/Agent 双栏；
- grid child 使用 min-w-0；
- runId/auditId/机器边界 break-all；
- table 使用受控 overflow-x-auto。

交互：

- 主按钮 min-h-11、可见 focus-visible；
- auto refresh 使用 aria-pressed；
- 展开按钮使用 aria-expanded；
- transition 同时使用 motion-reduce:transition-none；
- 状态使用文字，不能仅靠颜色。

- [ ] **Step 4: 运行静态 GREEN、构建和首页响应式门禁**

    npm.cmd run smoke:frontend -- -Routes /
    npm.cmd run typecheck
    npm.cmd run lint
    npm.cmd run build

现有 responsive smoke 使用 Playwright CLI。Product Design 约束要求执行前明确向用户请求一次许可。获许可后：

    $env:FRONTEND_RESPONSIVE_ROUTES = "/"
    npm.cmd run smoke:frontend:responsive
    Remove-Item Env:\FRONTEND_RESPONSIVE_ROUTES

Expected:

    ok frontend responsive viewports=1440x1000,1280x900,768x1024,390x844 routes=1 checks=4

若未获许可，不得运行；Task 5 用用户选定的 Codex 内置浏览器验收，并明确记录未运行此自动门禁。

- [ ] **Step 5: 提交**

    git diff --check
    git add frontend/src/components/dashboard/DashboardDecisionCommandCenter.tsx scripts/smoke-frontend-routes.ps1
    git commit -m "fix: harden dashboard command center layout"

### Task 5: 全量验证、同视口比较与 Sites 发布

**Files:**

- Verify: frontend/src/components/dashboard/DashboardPage.tsx
- Verify: frontend/src/components/dashboard/DashboardDecisionCommandCenter.tsx
- Verify: frontend/src/utils/dashboardDecisionViewModel.ts
- Verify: scripts/test-dashboard-decision-view-model.mjs
- Verify: scripts/smoke-frontend-routes.ps1
- Verify: scripts/smoke-frontend-responsive.mjs
- Reference only: .superpowers/brainstorm/432-1784054940/content/dashboard-direction-a.html

- [ ] **Step 1: 重新读取执行技能**

开始本任务前读取 superpowers:verification-before-completion、sites:sites-building、sites:sites-hosting 和 browser:control-in-app-browser。Sites hosting 只能在构建和验证后使用。

- [ ] **Step 2: 运行专项与仓库检查**

    npm.cmd run test:frontend:dashboard-decision
    npm.cmd run test:frontend
    npm.cmd run lint
    npm.cmd run typecheck
    node --check scripts\test-dashboard-decision-view-model.mjs
    npm.cmd run build
    npm.cmd run smoke:frontend -- -Routes /
    npm.cmd run smoke:frontend
    npm.cmd run test

AGENTS.md 还列出 pnpm lint、pnpm test、pnpm typecheck。若环境存在 pnpm，额外执行；若不存在，记录仓库无 pnpm lockfile且已运行 npm.cmd 等价脚本，不生成 pnpm lockfile。

任何失败都先诊断；不能把旧失败描述成通过。

- [ ] **Step 3: 运行完整响应式门禁**

仅在已取得 Playwright CLI 许可时：

    npm.cmd run smoke:frontend:responsive

Expected: 1440×1000、1280×900、768×1024、390×844 的完整路由矩阵通过，document 横向 overflow 不超过 4px。

- [ ] **Step 4: 在用户选定的 Codex 内置浏览器验收**

只使用 Codex 内置浏览器。先打开 A 方案源预览，再打开本地实现；使用同一运行状态和相同 viewport 比较：

1. 1440×1000：Hero、六指标、阻断/下一步双栏、证据和 Agent 层级；
2. 1280×900：标题、按钮、指标不拥挤；
3. 768×1024：单栏顺序正确，无裁切；
4. 390×844：结论、阻断、下一步、指标、证据、Agent 顺序正确，无页面横向滚动。

把参考和实现截图放到同一比较输入，检查字号/字重/边框/圆角/间距、REVIEW_ONLY/首阻断/第一下一步可识别、状态文字、runId/边界不截断、刷新/自动刷新/证据展开/导航可操作、失败保留证据、run_id 水合不闪旧运行、44px 触控和键盘焦点。

发现差异只做局部修复；修复后重跑相关专项并重新同视口比较。

- [ ] **Step 5: 用 Sites 发布验证产物**

按 sites:sites-hosting 的真实流程发布。打开返回 URL，验证首页非空、静态资源加载、dashboard-decision-command-center 可见。若权限/连接/服务阻断，报告准确错误，不编造 URL。

- [ ] **Step 6: 最终工作树与提交检查**

    git status --short
    git diff --check
    git log -5 --oneline

确认：仅计划内文件；.superpowers/ 未跟踪且未提交；无 debug log/过宽 try-catch；无 auth/API schema/数据库/后端变更；query/hash/run_id 未破坏；刷新错误按 runId 隔离；水合门禁仍在。

若 QA 产生最后修复：

    git add frontend/src/components/dashboard/DashboardPage.tsx frontend/src/components/dashboard/DashboardDecisionCommandCenter.tsx frontend/src/utils/dashboardDecisionViewModel.ts scripts/test-dashboard-decision-view-model.mjs scripts/smoke-frontend-routes.ps1 package.json
    git commit -m "fix: polish dashboard decision command center"

没有变化时不创建空提交。

## Completion Evidence

最终交付按顺序报告：

1. Sites URL 或准确 hosting 阻断；
2. 改了什么；
3. 为什么；
4. 每条实际命令与结果；
5. 浏览器 viewport 与可见结论；
6. 剩余风险，包括未获授权而未运行的 Playwright smoke；
7. git 状态与提交哈希。

不得只凭截图或静态检查宣称完成；至少需要映射器矩阵、typecheck、lint、build、静态 smoke 和内置浏览器交互证据。
