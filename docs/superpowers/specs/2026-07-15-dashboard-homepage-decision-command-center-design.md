# 控制台首页「决策优先指挥台」设计规格

- 更新日期：2026-07-15
- 状态：设计已确认；书面规格待用户复核；实现未开始
- 选定方向：A「决策优先指挥台」

## 1. 背景

现有控制台首页承载运行状态、证据、Agent、阻断和模拟边界等大量信息，但首屏缺少清晰的阅读顺序。用户需要在 30 秒内回答三个问题：

1. 当前分析结论是什么，是否可信；
2. 首要阻断是什么；
3. 下一步应该做什么。

本次改版只重排首页信息层级并建立可测试的展示模型，不改变分析业务规则、接口、路由、认证或数据库。

## 2. 已验证的现状

- 首页入口是 `frontend/src/components/dashboard/DashboardPage.tsx`，继续由它协调当前运行、URL 关联运行的水合、刷新和页面交互。
- `frontend/src/utils/dashboardWorkbench.ts` 已提供证据评分、来源覆盖、首要阻断、警告、后续复核项和模拟边界的保守 fallback。
- 首页已有运行编号、阻断、下一步和模拟边界的稳定 `data-testid`，并由 `scripts/smoke-frontend-routes.ps1` 守护。
- 现有边界要求 `simulationOnly=true`、`isRealTrade=false`、`evidenceUsage=simulation_only`、`strongConclusionAllowed=false`；首页不得暗示真实交易执行。
- URL 携带 `run_id` 时，页面必须等待对应运行完成水合，不能短暂渲染另一条旧运行。

## 3. 目标与非目标

### 3.1 目标

- 首屏优先展示结论、可信度、首要阻断和下一步。
- 将当前分散的首页数据整理为单一、纯展示用途的视图模型。
- 复用现有查询、状态、业务判定和交互处理函数。
- 对缺失、失败、过期和边界违规状态采取保守降级。
- 在桌面、平板和手机上保持一致的阅读优先级。
- 为关键映射规则、可见契约和响应式行为建立可执行验证。

### 3.2 非目标

- 不新增或修改后端接口。
- 不修改数据库 schema 或执行迁移。
- 不修改认证、session、cookie 或权限行为。
- 不新增真实交易、自动下单或强结论能力。
- 不新建页面或路由。
- 不重写整个 `DashboardPage`，也不做与首屏改版无关的组件重构。

## 4. 不可回退的安全与兼容边界

- 新布局只能展示既有结论或将其保守降级，不能把任何状态升级为更强结论。
- 任一关键数据缺失、关键请求失败、数据过期或模拟边界违规时，首屏结论降级为 `REVIEW_ONLY`，并解释原因。
- “关键数据”明确指：URL/当前运行身份匹配、运行状态与更新时间、workbench 决策摘要、证据/来源汇总，以及四个模拟边界字段。无法证明这些字段可靠时按缺失处理。
- “数据过期”只复用现有 `STALE` 运行状态或 provenance/来源新鲜度标记，不在展示层另造 TTL。
- `simulationOnly`、`isRealTrade`、`evidenceUsage` 和 `strongConclusionAllowed` 必须在页面中保持可见且使用原始机器值。
- 缺失数据显示“—”或“未配置”，不得转换为看似真实的 `0`。
- 现有 query/hash、`run_id` 深链、刷新、自动刷新和继续分析入口必须保持兼容。
- 现有测试标识不得静默移除。若标识随组件移动，先扩展 smoke guard 的读取范围，再移动实现，并保持断言语义不变。

## 5. 首屏信息架构

页面沿用现有导航、色彩、字体、Tailwind 工具类、Lucide 图标和卡片语言，不引入装饰图片或新视觉体系。

### 5.1 第一层：决策结论

首屏顶部是 `DecisionHero`：

- 大号结论标签，显示当前业务结论；安全降级时显示 `REVIEW_ONLY`。
- 一句话摘要，优先说明当前判断及主要限制。
- 运行上下文：标的、运行编号、运行状态、更新时间和过期状态。
- 模拟环境徽标始终可见。

### 5.2 第二层：关键指标

`MetricStrip` 在一行内展示六类信息；窄屏时按相同顺序换行：

1. 证据评分；
2. 数据来源就绪数/总数；
3. 阻断数量；
4. 活跃 Agent 数/总数；
5. 数据新鲜度；
6. 模拟边界摘要 `SIM`。

指标必须保留标签、值和简短解释，不能只靠颜色传达状态。

### 5.3 第三层：阻断与下一步

桌面端左右并列：

- `BlockerPanel`：首要阻断置顶，其余阻断按现有顺序展示；没有硬阻断时仍显示“保持人工复核”。
- `NextActionPanel`：按既有 `nextReview` 顺序展示，第一项作为主行动；所有入口复用现有处理函数和路由。

窄屏时先显示阻断，再显示下一步。

### 5.4 首屏以下：证据和 Agent

- `EvidenceTable` 展示来源、状态、新鲜度、证据等级和缺失原因。
- `AgentDecisionTable` 展示 Agent、状态、结论摘要、阻断/硬停止和证据关联。
- 表格继续使用真实运行数据，不增加演示用假数据。

## 6. 组件边界

### 6.1 页面协调层

`DashboardPage.tsx` 保留以下职责：

- 读取 `useAnalysisStore` 与 URL 参数；
- 等待关联运行水合；
- 调用现有 provenance、workbench 和 governance 构建逻辑；
- 管理刷新、自动刷新、展开状态和现有交互；
- 将稳定输入传给新的首页展示组件。

既有 `buildDashboardRunGovernance` 和边界判定在首版实现中不搬迁，避免无关业务重构。

### 6.2 视图模型层

新增纯函数 `buildDashboardDecisionViewModel(input)`。它只组合已经计算完成的运行、workbench、governance、来源和 Agent 数据，不发请求、不读全局状态、不产生副作用。

视图模型至少包含：

```ts
type DashboardDecisionViewModel = {
  conclusion: {
    status: string
    label: string
    summary: string
    tone: 'neutral' | 'warning' | 'critical'
  }
  context: {
    runId: string
    symbol: string
    updatedAt: string
    isStale: boolean
  }
  metrics: DashboardMetricItem[]
  blockers: string[]
  nextActions: string[]
  evidenceRows: DashboardEvidenceRow[]
  agentRows: DashboardAgentRow[]
  boundary: {
    simulationOnly: boolean
    isRealTrade: boolean
    evidenceUsage: string
    strongConclusionAllowed: boolean
  }
}
```

映射器必须遵守“只能保持或降级、不能升级结论”的规则。

### 6.3 展示层

新增 `DashboardDecisionCommandCenter` 作为组合组件，其内部由六个小型展示组件构成：

- `DecisionHero`
- `MetricStrip`
- `BlockerPanel`
- `NextActionPanel`
- `EvidenceTable`
- `AgentDecisionTable`

这些组件只接收 props 并渲染，不访问 store，不自行请求数据。为避免文件碎片化，首版可将小组件放在同一个命令中心文件中；当文件职责明显增长时再拆分。

## 7. 数据流

```text
现有 API / useAnalysisStore
  → DashboardPage 当前运行与水合门禁
  → buildDashboardProvenanceSummary
  → buildDashboardWorkbench
  → buildDashboardRunGovernance
  → buildDashboardDecisionViewModel
  → DashboardDecisionCommandCenter
```

- 只有现有 store 和页面协调层触发请求。
- 展示组件不会重复刷新或建立第二份状态真相。
- 刷新、继续分析和导航事件由展示组件回调到 `DashboardPage` 的既有 handler。
- 视图模型重新计算只依赖当前运行及其派生结果，避免竞态和陈旧闭包。

## 8. 加载、错误与过期状态

### 8.1 加载

- 首次加载和 `run_id` 水合期间保留稳定骨架。
- 未完成水合前不显示其他运行的旧结论。
- 自动刷新时保留当前证据，使用非阻塞刷新提示，不让页面闪为空白。

### 8.2 部分数据缺失

- 缺失指标显示“—”或“未配置”。
- 首要缺失原因进入阻断或警告区。
- 结论在关键输入不完整时降级为 `REVIEW_ONLY`。

### 8.3 请求失败

- 保留最后一次已知证据，同时明确标注失败和数据时间。
- 提供复用现有 handler 的重试入口。
- 不使用过宽 `try/catch` 吞掉错误，也不把失败转成成功空态。

### 8.4 数据过期

- 同时显示采集时间与“数据已过期”标识。
- 过期状态进入首屏结论摘要和指标条。
- 过期数据不参与强结论展示。

### 8.5 模拟边界违规

- 立即降级为 `REVIEW_ONLY`。
- 显示具体机器字段和值。
- 下一步固定优先提示修复 simulation-only boundary，不提供任何执行型行动。

## 9. 响应式、交互与可访问性

- 复用项目现有响应式断点，不引入平行断点系统。
- 桌面端：结论 → 指标 → 阻断/下一步双栏 → 证据/Agent。
- 窄屏：结论 → 阻断 → 下一步 → 指标 → 证据 → Agent。
- 页面不得产生横向滚动；表格在窄屏转换为可读的行卡片或受控横向容器。
- 关键按钮与链接支持键盘操作，保留可见焦点样式，触控区域不小于 44px。
- 状态不能只靠颜色表达；结论、阻断和新鲜度均有文字标签。
- 标题层级保持语义化；表格保留可访问列标题。
- 动效只使用轻量状态过渡，并遵循 `prefers-reduced-motion`。

## 10. 测试设计

### 10.1 先收紧回归守卫

实现前先更新现有 dashboard smoke contract，使它能读取新命令中心和视图模型文件，同时继续断言：

- 页面、结论、运行编号、阻断、下一步和模拟边界测试标识存在；
- `simulation_only=true` 与 `is_real_trade=false` fallback 仍可见；
- URL 关联运行水合门禁仍存在；
- 新视图模型和命令中心确实由 `DashboardPage` 接入。

### 10.2 视图模型决策矩阵

新增 `scripts/test-dashboard-decision-view-model.mjs`，使用项目已安装的 TypeScript compiler API 将自包含的纯映射器转译到 `.tmp`，再用 Node `assert` 执行决策矩阵；脚本结束后清理临时产物。该方案不引入新的测试框架或依赖。至少覆盖：

1. 完整数据；
2. 部分关键字段缺失；
3. 请求失败；
4. 数据过期；
5. 全空数据；
6. simulation-only 边界违规。

每个场景断言结论、首要阻断、下一步、缺失值和边界字段；同时证明映射器不会升级原结论。

### 10.3 静态与构建检查

按照仓库约定执行：

```powershell
pnpm lint
pnpm test
pnpm typecheck
npm.cmd run build
npm.cmd run smoke:frontend
npm.cmd run smoke:frontend:responsive
```

若当前环境没有 `pnpm`，在不更改 lockfile 的前提下使用仓库现有 `npm.cmd run lint`、`npm.cmd run test`、`npm.cmd run typecheck` 等价脚本，并明确记录差异。

### 10.4 浏览器验收

在用户已选择的 Codex 内置浏览器中完成：

- 将 A 方案源预览与实现截图放在同一比较输入，使用相同 viewport 和运行状态检查视觉差异；
- 覆盖桌面、平板和手机宽度；
- 检查横向溢出、裁切、间距、字号、边框、焦点、触控区域和状态文本；
- 验证真实刷新、重试、展开和现有导航入口；
- 验证用户在首屏 30 秒内可以指出当前结论、首要阻断和下一步。

## 11. 预期文件范围

实现预计只涉及：

- `frontend/src/components/dashboard/DashboardPage.tsx`
- `frontend/src/components/dashboard/DashboardDecisionCommandCenter.tsx`
- `frontend/src/utils/dashboardDecisionViewModel.ts`
- `scripts/smoke-frontend-routes.ps1`
- `scripts/test-dashboard-decision-view-model.mjs` 与对应 package script

不触碰后端、数据库、认证或无关页面。

## 12. 风险与缓解

- **业务判定被视觉层重写**：视图模型只能组合和降级现有结果，不能自行产生更强结论。
- **静态 smoke 因组件抽取失效**：先扩展 guard 的文件读取范围，再移动受保护标识。
- **自动刷新产生旧数据闪烁**：沿用 `run_id` 水合门禁，刷新时保留同一运行上下文。
- **空值被误认为零**：视图模型显式区分缺失与数值零，并为两者建立断言。
- **移动端信息顺序失真**：以 DOM 顺序实现阅读优先级，不只依赖 CSS 视觉重排。
- **大文件继续膨胀**：只抽出本次首屏展示层与纯映射器，不扩展到其他 dashboard 子系统。

## 13. 完成定义

- 首屏信息顺序与 A 方案一致。
- 结论、首要阻断和下一步无需滚动即可识别。
- 所有安全边界、机器字段、深链和既有交互保持兼容。
- 完整、缺失、失败、过期、全空和边界违规场景均有可执行断言。
- lint、测试、类型检查、构建、前端 smoke 和响应式 smoke 全部通过。
- 浏览器完成同 viewport 视觉比较与交互验收。
- 最终交付说明改了什么、为什么、检查结果和剩余风险。
