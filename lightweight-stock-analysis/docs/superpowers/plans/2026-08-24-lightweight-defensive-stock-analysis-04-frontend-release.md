# 轻量化防御性股票分析阶段四：单页工作台、验收与独立发布 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 交付一个独立、轻量、响应式的 React 单页研究工作台，完整呈现数据准备→客观扫描→Top 50 复核→最终排名，并通过真实测试 FastAPI + Vite 的 E2E、性能、独立安装、发布包和 Gate 0 文档门。

**Architecture:** 前端只做 API 边界验证、资源状态组合与展示，不实现 ObjectiveScore/DS2 公式。Unknown-first HTTP client 用 Zod 解码外部数据，token 只存内存，controller 通过 AbortSignal + request generation 阻止迟到响应覆盖新选择。React reducer 映射四阶段服务端资源，CSS Grid 负责桌面三栏和小屏步骤条/卡片/抽屉。生产包由单 worker FastAPI 同源提供预构建 SPA。

**Tech Stack:** 发布与 CI 基线固定 Node 24 LTS、pnpm 11、React 18、TypeScript、Vite 5、Zod、Vitest、Testing Library、MSW、Playwright、axe-core、原生 CSS/SVG；不得把本机 Node 26 Current 当作发布验收基线。

**Spec:** lightweight-stock-analysis/docs/superpowers/specs/2026-08-24-lightweight-defensive-stock-analysis-design.md

## Global Constraints

- 先完成计划 01–03，并在隔离 worktree 实施。前端合约以 Plan 03 OpenAPI 为权威。
- 子应用拥有自己的 `frontend/package.json` 和 `pnpm-lock.yaml`；不修改父仓库 package.json/package-lock/node_modules，不跨目录 import 父前端。
- 前端禁止出现八维加权、73 分母、锚点插值、资格过滤或排名 tie-breaker 实现；只显示 API 的原始/展示分。
- 所有 `response.json()` 先视为 `unknown`；不允许 `request<T>()` 断言或 `as CandidatePage` 绕过 schema。
- 服务端新增未知状态时，UI 显示“未知状态：”加服务端原始值，并禁用副作用，不当成成功；可空字段用明确缺失态，不崩溃。
- Bearer 只存 `MemoryTokenStore`；不进 cookie、URL、DOM、localStorage 或 sessionStorage；401 或页面重载后必须重新输入。
- 写请求不自动重试；用户明确重试时复用原幂等键。GET 轮询在选择切换或卸载时 abort。
- `NOT_CONFIGURED`、`LIVE_PARTIAL`、`LIVE_READY` 与 `acceptance_mode` 分开展示；只有 `LIVE_READY + LIVE + synthetic=false` 显示真实全市场就绪文案。
- 最终页标题固定“客观 Top 50 内部 DS2 排名”；不得写“全市场 DS2 排名”。
- 每个结果视图显示“研究用途，不构成投资建议”；S/A/G 与分数/排名分离。
- 每个前端/TypeScript 提交前运行 `pnpm lint && pnpm test`、`pnpm typecheck`；发布前额外运行 build/e2e。
- E2E 只允 localhost 测试进程间网络，每次动态端口和唯一 tmp runtime，结束后确认子进程/端口释放。
- 真实 Gate 0 需要用户另行提供凭据与联网授权；离线发布构建不执行它，不伪造真实验收。
- 本计划中 `pnpm` 命令从 `lightweight-stock-analysis/frontend` 执行；后端 Python 命令从 `lightweight-stock-analysis/backend` 执行；发布 PowerShell/Node 命令从 `lightweight-stock-analysis` 执行；`git` 暂存/提交命令从父仓库根执行。

## Frozen Frontend Types

```ts
export type KnownCapabilityState = "NOT_CONFIGURED" | "LIVE_PARTIAL" | "LIVE_READY";
export type AcceptanceMode = "LIVE" | "TEST_ONLY";
export type RankingScope = "core_entities" | "all_listings";
export type KnownJobStatus = "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED" | "INTERRUPTED";
export type KnownSnapshotStatus = "QUEUED" | "SYNCING" | "READY" | "FAILED" | "CANCELLED" | "INTERRUPTED";
export type KnownScanStatus = "QUEUED" | "RUNNING" | "REVIEW_PENDING" | "FINALIZED" | "FAILED" | "CANCELLED" | "INTERRUPTED";
export type KnownAsyncTargetStatus = "PENDING" | "RUNNING" | "READY" | "FAILED" | "CANCELLED" | "INTERRUPTED" | "SUPERSEDED";

export type ServerEnum<T extends string> =
  | { kind: "known"; value: T }
  | { kind: "unknown"; raw: string };

export interface CoverageMetric {
  numerator: number;
  denominator: number;
  ratio: number | null;
  threshold: number;
  passed: boolean;
  gap: number;
}

export interface CandidateQuery {
  scope: RankingScope;
  cursor?: string;
  limit: number;
  status?: string;
  market?: "CN" | "HK";
  industry?: string;
}
```

Zod 在边界接受 string，通过显式 decoder 转成 `ServerEnum`；这样 additive enum 不会被静默当成旧成功状态，也不会使整页因 schema 崩溃。分别实现并测试 `isTerminalJobStatus`、`isTerminalSnapshotStatus`、`isTerminalScanStatus` 和 `isTerminalAsyncTargetStatus`；未知状态一律不是成功且停止副作用，不能拿 job 的 SUCCEEDED 与 target 的 READY 混用。

## Package Baseline

Task 1 使用下列直接依赖并把完整 transitive resolution 冻结到 pnpm-lock.yaml：

- Runtime: `react@18.2.0`, `react-dom@18.2.0`, `zod@3.25.76`.
- Build/type: `vite@5.4.21`, `@vitejs/plugin-react@4.3.4`, `typescript@5.7.3`, `@types/react@18.3.18`, `@types/react-dom@18.3.5`, `@types/node@24.3.0`.
- Lint: `eslint@9.17.0`, `@eslint/js@9.17.0`, `globals@15.14.0`, `typescript-eslint@8.18.2`, `eslint-plugin-react-hooks@5.1.0`, `eslint-plugin-react-refresh@0.4.16`.
- Unit: `vitest@2.1.9`, `jsdom@25.0.1`, `@testing-library/dom@10.4.0`, `@testing-library/react@16.1.0`, `@testing-library/user-event@14.6.1`, `@testing-library/jest-dom@6.6.3`, `msw@2.7.0`.
- E2E: `@playwright/test@1.60.0`, `@axe-core/playwright@4.10.2`.

## File Structure

| Area | Files |
|---|---|
| Toolchain | `frontend/{package.json,pnpm-lock.yaml,index.html,tsconfig*.json,eslint.config.js,vite.config.ts,vitest.config.ts,playwright.config.ts}` |
| API boundary | `frontend/src/api/{client,errors,tokenStore,lsaApi,types}.ts`, `api/schemas/*.ts` |
| Workbench | `features/workbench/*`, shared `components/*`, `styles.css` |
| Stages | `features/data/*`, `features/scan/*`, `features/review/*`, `features/ranking/*` |
| Browser tests | `frontend/e2e/*`, `frontend/scripts/run-e2e.mjs` |
| Acceptance | `scripts/run-performance.ps1`, `docs/acceptance/*`, report schemas |
| Packaging | root README/.env.example, `scripts/{install,start-dev,start,build-release,verify-independent,verify-release}.ps1` |

---

### Task 1: 建立独立 React 骨架和 unknown-first API 边界

**Files:**

- Create: lightweight-stock-analysis/frontend/package.json
- Modify: lightweight-stock-analysis/.gitignore
- Create: lightweight-stock-analysis/frontend/pnpm-lock.yaml
- Create: lightweight-stock-analysis/frontend/index.html
- Create: lightweight-stock-analysis/frontend/tsconfig.json
- Create: lightweight-stock-analysis/frontend/tsconfig.node.json
- Create: lightweight-stock-analysis/frontend/eslint.config.js
- Create: lightweight-stock-analysis/frontend/vite.config.ts
- Create: lightweight-stock-analysis/frontend/vitest.config.ts
- Create: lightweight-stock-analysis/frontend/src/vite-env.d.ts
- Create: lightweight-stock-analysis/frontend/src/test/setup.ts
- Create: lightweight-stock-analysis/frontend/src/main.tsx
- Create: lightweight-stock-analysis/frontend/src/App.tsx
- Create: lightweight-stock-analysis/frontend/src/App.test.tsx
- Create: lightweight-stock-analysis/frontend/src/architecture.test.ts
- Create: lightweight-stock-analysis/frontend/src/api/client.ts
- Create: lightweight-stock-analysis/frontend/src/api/client.test.ts
- Create: lightweight-stock-analysis/frontend/src/api/openapiContract.test.ts
- Create: lightweight-stock-analysis/frontend/src/api/errors.ts
- Create: lightweight-stock-analysis/frontend/src/api/tokenStore.ts
- Create: lightweight-stock-analysis/frontend/src/api/types.ts
- Create: lightweight-stock-analysis/frontend/src/api/schemas/common.ts
- Create: lightweight-stock-analysis/frontend/src/api/schemas/data.ts
- Create: lightweight-stock-analysis/frontend/src/api/schemas/scan.ts
- Create: lightweight-stock-analysis/frontend/src/api/schemas/review.ts
- Create: lightweight-stock-analysis/frontend/src/api/schemas/export.ts
- Create: lightweight-stock-analysis/frontend/src/api/lsaApi.ts

**Interfaces:** `UnknownFirstHttpClient.json(schema, request)`、`blob(request)`、`createMemoryTokenStore`、`createLsaApi`；LsaApi 暴露 Plan 03 的每个 endpoint 方法。

- [ ] **Step 1: 写 package、架构和 API RED 测试**

package scripts 固定 `lint`、`test=vitest run`、`typecheck=tsc -b --pretty false`、`build=tsc -b && vite build`、`e2e=node scripts/run-e2e.mjs`、`e2e:performance=node scripts/run-e2e.mjs --profile performance`。tsconfig 使用 project references 同时覆盖 app、Vite/Vitest/Playwright Node config；契约测试临时破坏 vite.config.ts 类型并证明 typecheck 失败。`.gitignore` 在运行任何前端测试前覆盖 node_modules、dist、test-results、playwright-report、coverage 和临时 trace。

先验证 `node --version` 是 24.x LTS，再验证 `pnpm --version` 是 11.x；不假设 Corepack 存在。pnpm 缺失时由实施者在取得联网/全局安装授权后使用 npm 安装固定 pnpm 11 版本。创建 package/test files 后运行：

    pnpm install

Expected: 只生成 frontend/node_modules 和 frontend/pnpm-lock.yaml；浏览器 binary 到 Task 7 通过外部版本化路径显式 provision，不在此处隐式写用户缓存。如需网络，实施会话先获得授权。

API 测试覆盖：schema 必经解码、接受 additive fields、缺必需字段抛 ApiContractError、保留 code/details/request ID、FormData 不自加 JSON content-type、401 清 token、不写浏览器存储/cookie、timeout abort、blob 不解 JSON、写请求不自动重试；所有异步/幂等写只发 `Idempotency-Key` header并解析端点专用 preflight_id/snapshot_id/scan_id/collection_id/draft_id/clone_operation_id，不读 generic target_id。异步 response 对已知状态使用 status-discriminated Zod union，并在共同 envelope 校验后保留显式 UnknownStatusResponse fallback：PENDING/RUNNING preflight 没有 capability/report 字段仍通过，READY 缺任一报告字段失败，失败终态缺 safe_error 失败；QUEUED/SYNCING snapshot 没有 manifest/capability 仍通过，READY 缺任一冻结字段失败；QUEUED job 没有 attempt_no 仍通过，RUNNING/SUCCEEDED 缺 attempt_no 或缺 checkpoint 字段失败，但 `checkpoint:null` 通过；服务端新增未知 status 时解析为 `{status: ServerEnum.unknown, raw, commonFields}`，不进入任何已知成功分支。测试还要断言 UI 不会为未完成/未知分支补 `NOT_CONFIGURED`、空 hash、0 coverage 或 null manifest。HealthResponse 必须验证固定 service、api_schema_version 和 installation_id_hash。`listCandidates(query)`、`listRankings(query)` 和 downloadExport 传 scope，CandidatePage/FinalRankingPage 保留 next_cursor。openapiContract.test.ts 在测试期只读 Plan 03 手写 approved fixture，逐 schema 比对 Zod discriminant/required/nullability/status registry、Idempotency-Key 和 route；生产 bundle 不 import 测试 fixture。架构测试扫描 frontend/src 禁止父目录 import 和客户端评分实现关键字。

- [ ] **Step 2: 运行 RED**

Run:

    pnpm test -- src/App.test.tsx src/architecture.test.ts src/api/client.test.ts

Expected: FAIL because App, client, schemas and token store implementations are absent.

- [ ] **Step 3: 实现最小客户端和契约类型**

`response.json()` 赋给 `unknown`，先校验各资源共同 envelope，再由 `decodeAsyncStatus` 分派已知 literal 分支或 UnknownStatusResponse；已知成功 schema 使用 Zod 严格验证，未知 status 只保留安全共同字段并禁用动作。error body 即使不合契约也保留 header request ID 和安全 fallback message。`LsaApi.listCandidates`、`listRankings` 与 `downloadExport` 必须传 `scope`/server filters/cursor；只有 READY Preflight 分支要求 capability_state/acceptance_mode/synthetic/gate0_policy_hash，只有 READY Snapshot 分支要求逐市场 capability 三态、gate0_policy_hash 与 manifest 冻结字段，其他状态分支按 Plan 03 禁止伪造这些值。Scan schema 必须要求含 gate0_policy_hash 的 audit_summary。

- [ ] **Step 4: 运行前端门并提交**

Run:

    pnpm lint
    pnpm test
    pnpm typecheck
    pnpm build
    git diff --check
    git add -- lightweight-stock-analysis/.gitignore lightweight-stock-analysis/frontend
    git commit -m "chore(lsa-frontend): scaffold validated standalone client"

---

### Task 2: 实现四阶段 reducer、轮询竞态保护和工作台外壳

**Files:**

- Create: lightweight-stock-analysis/frontend/src/features/workbench/model.ts
- Create: lightweight-stock-analysis/frontend/src/features/workbench/workbenchReducer.ts
- Create: lightweight-stock-analysis/frontend/src/features/workbench/workbenchReducer.test.ts
- Create: lightweight-stock-analysis/frontend/src/features/workbench/useResourcePoller.ts
- Create: lightweight-stock-analysis/frontend/src/features/workbench/useWorkbenchController.ts
- Create: lightweight-stock-analysis/frontend/src/features/workbench/useWorkbenchController.test.tsx
- Create: lightweight-stock-analysis/frontend/src/features/workbench/urlState.ts
- Create: lightweight-stock-analysis/frontend/src/features/workbench/WorkbenchPage.tsx
- Create: lightweight-stock-analysis/frontend/src/features/workbench/WorkbenchHeader.tsx
- Create: lightweight-stock-analysis/frontend/src/features/workbench/StageRail.tsx
- Create: lightweight-stock-analysis/frontend/src/features/workbench/AuditFooter.tsx
- Create: lightweight-stock-analysis/frontend/src/components/StatusBadge.tsx
- Create: lightweight-stock-analysis/frontend/src/components/CapabilityBanner.tsx
- Create: lightweight-stock-analysis/frontend/src/components/LoadingRegion.tsx
- Create: lightweight-stock-analysis/frontend/src/components/EmptyState.tsx
- Create: lightweight-stock-analysis/frontend/src/components/ErrorSummary.tsx
- Create: lightweight-stock-analysis/frontend/src/components/ResponsiveInspector.tsx
- Create: lightweight-stock-analysis/frontend/src/components/ResearchDisclaimer.tsx
- Create: lightweight-stock-analysis/frontend/src/components/ScoreBreakdownDialog.tsx
- Create: lightweight-stock-analysis/frontend/src/components/ScoreRadar.tsx
- Create: lightweight-stock-analysis/frontend/src/styles.css
- Modify: lightweight-stock-analysis/frontend/src/App.tsx

**Interfaces:** `deriveWorkbenchStage`、`deriveActionAvailability`、`workbenchReducer`、`useResourcePoller`、`useWorkbenchController`。

- [ ] **Step 1: 写状态映射与迟到响应 RED 测试**

固定映射：data preparation 覆盖 DRAFT/preflight/snapshot；objective screening 覆盖 scan QUEUED/RUNNING/FAILED/CANCELLED/INTERRUPTED；top50 review 是 REVIEW_PENDING；final ranking 是 FINALIZED。未知 status 不开启动作，FINALIZED 不可编辑。

controller 测试断言：切换 scan 立即 abort 旧轮询；即使 fake fetch 忽略 abort，generation id 也丢弃旧响应；明确重试复用原 `Idempotency-Key`；各资源使用自己的 terminal predicate 停轮询；URL 只允许保存 preflight_id/scan_id/snapshot_id，不保存 token。带 `?preflight_id=` 的深链必须精确 GET 该资源并驱动本次 ReportCard/Banner，切换 ID abort 旧响应，未知/非法 ID 显示安全错误且绝不回退旧报告。401 或非 loopback auth challenge 显示 password 型 token 输入；提交后先写入 MemoryTokenStore，再立即清空 DOM input/state，测试搜索 DOM、history、storage、cookie 和错误文本均找不到 token。

- [ ] **Step 2: 运行 RED**

Run:

    pnpm test -- src/features/workbench

Expected: FAIL on missing reducer/controller.

- [ ] **Step 3: 实现工作台和响应式基础**

桌面使用 `grid-template-columns: minmax(12rem, 16rem) minmax(0, 1fr) minmax(20rem, 26rem)`；宽表只在带 `tabIndex=0`、`role=region`、aria-label 的自身容器滚动。小于 768px 时改步骤条、卡片和 dialog 抽屉。ScoreRadar 使用语义 SVG，同时提供同值文本表格，不引入图表库。AuditFooter 只读当前选中 ScanResponse.audit_summary；尚无 scan 的 preflight 阶段只由按本次 preflight_id 获取的 PreflightReportCard 与 CapabilityBanner 展示即时结果，不允许 Footer 回退到旧 scan。状态同时使用文字+图标+颜色，`prefers-reduced-motion` 禁用非必要动画。

- [ ] **Step 4: 运行前端门并提交**

Run:

    pnpm lint
    pnpm test
    pnpm typecheck
    git diff --check
    git add -- lightweight-stock-analysis/frontend/src
    git commit -m "feat(lsa-frontend): add four-stage workbench state"

---

### Task 3: 实现数据准备与 Gate 0 真实性呈现

**Files:**

- Create: lightweight-stock-analysis/frontend/src/features/data/DataPreparationStage.tsx
- Create: lightweight-stock-analysis/frontend/src/features/data/DataPreparationStage.test.tsx
- Create: lightweight-stock-analysis/frontend/src/features/data/SourceHealthTable.tsx
- Create: lightweight-stock-analysis/frontend/src/features/data/PreflightForm.tsx
- Create: lightweight-stock-analysis/frontend/src/features/data/PreflightReportCard.tsx
- Create: lightweight-stock-analysis/frontend/src/features/data/DataSnapshotForm.tsx
- Create: lightweight-stock-analysis/frontend/src/features/data/DataSnapshotProgress.tsx
- Create: lightweight-stock-analysis/frontend/src/features/data/ImportValidationForm.tsx
- Modify: lightweight-stock-analysis/frontend/src/features/workbench/WorkbenchPage.tsx

- [ ] **Step 1: 写加载/空/缺失/测试模式 RED 测试**

断言 fresh install 无 preflight 时显示 PreflightForm；用户选择 markets/as_of/source preferences 并确认真实联网授权边界后，点击精确调用 `POST /api/data-sources/preflight`、解析 preflight_id/job_id、轮询到 terminal，再按 preflight_id 读回报告；重试复用同 Idempotency-Key。E2E 只能在 LSA_ENV=test 使用 TEST_ONLY provider，真实 provider 不因按钮自动启用网络。NOT_CONFIGURED 禁用真实 snapshot；LIVE_PARTIAL 展示每项 numerator/denominator/threshold/gap；CN-only/HK-only 即使本市场全通过也绝不显示全市场就绪；TEST_ONLY/LIVE_READY 始终醒目标 synthetic，不显示全市场就绪；只有同时含 CN+HK 的 LIVE + non-synthetic LIVE_READY 显示就绪文案。报告和 snapshot 卡片显示 gate0_policy_hash，并在 policy 漂移错误时要求重跑 preflight。导入严格 validate→复核→commit；nullable coverage 不崩溃；FAILED/INTERRUPTED 显示服务端允许的恢复动作。snapshot 变为 READY 后出现“开始客观扫描”，点击精确调用 `POST /api/scans` 并使用新的 Idempotency-Key；重复点击/重试复用同键，AcceptedScanResponse 的 scan_id 驱动下一阶段。

- [ ] **Step 2: 运行 RED**

Run:

    pnpm test -- src/features/data/DataPreparationStage.test.tsx

Expected: FAIL because data stage components are missing.

- [ ] **Step 3: 实现最小数据准备 UI**

展示 provider 名称、脱敏能力、最后成功日期和缓存状态，不展示凭据/密钥路径/原始错误。PreflightForm 在提交前展示“真实运行需另行凭据与联网授权”，后端拒绝时原样呈现安全状态，不偷偷切 fixture。Snapshot 表单从保存后的 preflight 资源导出市场可用性，不在前端重算 coverage 通过性。

- [ ] **Step 4: 运行前端门并提交**

Run:

    pnpm lint
    pnpm test
    pnpm typecheck
    git diff --check
    git add -- lightweight-stock-analysis/frontend/src/features/data lightweight-stock-analysis/frontend/src/features/workbench/WorkbenchPage.tsx
    git commit -m "feat(lsa-frontend): add auditable data preparation"

---

### Task 4: 实现客观扫描、质量状态与冲突解释

**Files:**

- Create: lightweight-stock-analysis/frontend/src/features/scan/ObjectiveScreeningStage.tsx
- Create: lightweight-stock-analysis/frontend/src/features/scan/ObjectiveScreeningStage.test.tsx
- Create: lightweight-stock-analysis/frontend/src/features/scan/ScreeningProgress.tsx
- Create: lightweight-stock-analysis/frontend/src/features/scan/QualityBreakdown.tsx
- Create: lightweight-stock-analysis/frontend/src/features/scan/CandidateTable.tsx
- Create: lightweight-stock-analysis/frontend/src/features/scan/CandidateCardList.tsx
- Create: lightweight-stock-analysis/frontend/src/features/scan/ConflictDetails.tsx
- Create: lightweight-stock-analysis/frontend/src/features/scan/ScanRecoveryActions.tsx
- Modify: lightweight-stock-analysis/frontend/src/features/workbench/WorkbenchPage.tsx

- [ ] **Step 1: 写进度、PARTIAL、CONFLICTED 和恢复 RED 测试**

断言显示 total/processed/excluded/partial/conflicted/remaining batches；ObjectiveScore 文案固定“全市场客观预筛、非最终分”；PARTIAL 不补 0/50；CONFLICTED 显示候选值/来源并告知当前 scan 不可就地修复；只在 QUEUED/RUNNING 可 cancel，只在 retryable FAILED/INTERRUPTED 可 resume；空资格集显式呈现。RUNNING 期间绝不请求 candidates，只显示 scan progress；状态原子变为 REVIEW_PENDING 后 Workbench 切入 ReviewStage，才组合 CandidateTable/CardList 并发出第一次 GET。修复来源后，ScanRecoveryActions 提供 clone form（新 preflight、as_of、source preferences、必填 reason），精确 POST `/api/scans/{scan_id}/clone`、解析 AcceptedCloneResponse、轮询 clone_operation，并在 child scan_id 出现后导航；失败不修改父 scan。CandidateQuery 的 scope/cursor/limit/status/market/industry 都交给服务端；筛选或 scope 改变立即 abort 旧请求、清 cursor，并从第一页加载，下一页沿用服务端 next_cursor；本地不得把当前页误当全量筛选。

- [ ] **Step 2: 运行 RED**

Run:

    pnpm test -- src/features/scan/ObjectiveScreeningStage.test.tsx

Expected: FAIL because scan stage is missing.

- [ ] **Step 3: 实现展示和状态驱动操作**

ObjectiveScreeningStage 只负责 QUEUED/RUNNING/FAILED/CANCELLED/INTERRUPTED 的进度与恢复；CandidateTable/CardList 是进入 REVIEW_PENDING 后由 ReviewStage 复用的客观候选 view。桌面用表格，小屏用卡片；两者共用同 CandidateSummary view model。默认展示 API 冻结 ObjectiveScore 顺序，前端筛选不改服务端 rank；core_entities 与 all_listings 使用 Plan 03 的不同客观 read-model 语义。clone/cancel/resume 各自持有稳定 idempotency key 和独立轮询 generation；所有 error 显示 request ID。

- [ ] **Step 4: 运行前端门并提交**

Run:

    pnpm lint
    pnpm test
    pnpm typecheck
    git diff --check
    git add -- lightweight-stock-analysis/frontend/src/features/scan lightweight-stock-analysis/frontend/src/features/workbench/WorkbenchPage.tsx
    git commit -m "feat(lsa-frontend): explain objective screening states"

---

### Task 5: 实现证据、AI 草稿与乐观人工复核

**Files:**

- Create: lightweight-stock-analysis/frontend/src/features/review/ReviewStage.tsx
- Create: lightweight-stock-analysis/frontend/src/features/review/ReviewStage.test.tsx
- Create: lightweight-stock-analysis/frontend/src/features/review/ReviewQueue.tsx
- Create: lightweight-stock-analysis/frontend/src/features/review/EvidencePanel.tsx
- Create: lightweight-stock-analysis/frontend/src/features/review/EvidenceSubmissionForm.tsx
- Create: lightweight-stock-analysis/frontend/src/features/review/AiDraftPanel.tsx
- Create: lightweight-stock-analysis/frontend/src/features/review/SubjectiveScoreForm.tsx
- Create: lightweight-stock-analysis/frontend/src/features/review/ReviewConflictDialog.tsx
- Modify: lightweight-stock-analysis/frontend/src/features/workbench/WorkbenchPage.tsx

- [ ] **Step 1: 写证据门、AI 失败和版本冲突 RED 测试**

支持证据/反证分组，展示 publisher、verification、日期和 locator；“采集证据”精确 POST evidence/collect、用 collection_id 轮询并刷新 entity evidence；提交 URL/文件精确走 validate→commit；用户选定 evidence_ids 后，“生成 AI 草稿”精确 POST ai-drafts，服务端原子冻结 EvidenceBundle，客户端从 Accepted/GET draft 读 bundle_id 并用 draft_id 轮询。证据不足禁止确认；AI FAILED/SUPERSEDED 保留手工路径且不应用迟到值；人工子分与 AI 建议相差超过 10 分先要求 reason，API 422 仍是权威；每次提交 expected_version 和相同 evidence_ids，由服务端冻结/校验 EvidenceBundle。全部 core candidates 都进入 CONFIRMED/MANUAL_CONFIRMED/SKIPPED/EXCLUDED_BY_REVIEW 且至少一项确认后，显示“冻结最终排名”；点击精确调用 `POST /api/scans/{scan_id}/finalize` 并使用 Idempotency-Key，成功后用 scan_id 查询最终 rankings。

409 `REVIEW_VERSION_CONFLICT` 断言保留本地草稿，聚焦 ErrorSummary，重取服务端版本，不自动覆盖。UI 永不暴露“自动确认”。

- [ ] **Step 2: 运行 RED**

Run:

    pnpm test -- src/features/review/ReviewStage.test.tsx

Expected: FAIL because review stage is missing.

- [ ] **Step 3: 实现最小复核漏斗**

用 reducer 保存每 entity 本地草稿；collect/draft 使用各自端点专用 Accepted ID 和独立 idempotency key，选择切换时 abort 旧 evidence/collection/draft 轮询。抽屉开启后设初始焦点，关闭后返回 opener。证据链接只使用 API 已校验 URL，以 `noopener noreferrer` 开新窗。

- [ ] **Step 4: 运行前端门并提交**

Run:

    pnpm lint
    pnpm test
    pnpm typecheck
    git diff --check
    git add -- lightweight-stock-analysis/frontend/src/features/review lightweight-stock-analysis/frontend/src/features/workbench/WorkbenchPage.tsx
    git commit -m "feat(lsa-frontend): add evidence-backed manual review"

---

### Task 6: 实现最终排名、两种 scope 与导出

**Files:**

- Create: lightweight-stock-analysis/frontend/src/features/ranking/FinalRankingStage.tsx
- Create: lightweight-stock-analysis/frontend/src/features/ranking/FinalRankingStage.test.tsx
- Create: lightweight-stock-analysis/frontend/src/features/ranking/RankingScopeToggle.tsx
- Create: lightweight-stock-analysis/frontend/src/features/ranking/FinalRankingTable.tsx
- Create: lightweight-stock-analysis/frontend/src/features/ranking/FinalRankingCards.tsx
- Create: lightweight-stock-analysis/frontend/src/features/ranking/ExportActions.tsx
- Modify: lightweight-stock-analysis/frontend/src/features/workbench/WorkbenchPage.tsx

- [ ] **Step 1: 写后端分值权威与 scope RED 测试**

用故意“八维简单重算不等于 API DS2”的 fixture，断言 UI 原样显示 backend DS2；FinalRankingItem 的 DS2/八维若缺失或 null，Zod 必须抛 ApiContractError，页面显示带 request ID 的可访问 ErrorSummary 且不渲染伪行，绝不能补 0。“不可用”仅用于 approved OpenAPI 明确 nullable 的 stock/detail 非正式字段。页面加载/刷新后必须调用 `GET /api/scans/{scan_id}/rankings`，而非复用 candidates 或 finalize 临时响应。两种 scope 切换必须向 rankings API 传 `core_entities|all_listings`；all_listings 只展开冻结 Top 50 entity 的 READY listings，测试拒绝任何 Top 50 外 DS2 为契约错误。导出与当前 scope 绑定。只在 FINALIZED 显示 CSV/XLSX；两视图均显示固定标题和免责声明。

- [ ] **Step 2: 运行 RED**

Run:

    pnpm test -- src/features/ranking/FinalRankingStage.test.tsx

Expected: FAIL because ranking stage is missing.

- [ ] **Step 3: 实现不重算的最终视图**

展示 final/objective rank、总分、八维、资格/数据/复核状态、优点、风险、as_of、来源索引、rule/config/engine/snapshot/ranking hashes。S/A/G 是独立人工标签列，不决定样式中的分数高低。scope/filters 改变复用 CandidateQuery 的 abort+稳定游标模式；下载失败在页面展示 request ID。

- [ ] **Step 4: 运行前端门并提交**

Run:

    pnpm lint
    pnpm test
    pnpm typecheck
    git diff --check
    git add -- lightweight-stock-analysis/frontend/src/features/ranking lightweight-stock-analysis/frontend/src/features/workbench/WorkbenchPage.tsx
    git commit -m "feat(lsa-frontend): render finalized defensive rankings"

---

### Task 7: 加入真实前后端 E2E、响应式和可访问性门

**Files:**

- Create: lightweight-stock-analysis/frontend/playwright.config.ts
- Create: lightweight-stock-analysis/frontend/scripts/run-e2e.mjs
- Create: lightweight-stock-analysis/frontend/e2e/funnel.spec.ts
- Create: lightweight-stock-analysis/frontend/e2e/responsive-accessibility.spec.ts
- Create: lightweight-stock-analysis/frontend/e2e/auth-boundary.spec.ts
- Create: lightweight-stock-analysis/frontend/e2e/support/api.ts
- Create: lightweight-stock-analysis/frontend/e2e/support/metrics.ts
- Create: lightweight-stock-analysis/scripts/start-e2e-backend.ps1
- Create: lightweight-stock-analysis/scripts/ensure-playwright-browser.ps1
- Create: lightweight-stock-analysis/scripts/tests/playwright-browser-contract.test.mjs
- Create: lightweight-stock-analysis/backend/tests/e2e_server.py
- Create: lightweight-stock-analysis/backend/tests/e2e_network_guard.py
- Create: lightweight-stock-analysis/backend/tests/test_e2e_network_guard.py
- Modify: lightweight-stock-analysis/frontend/package.json

- [ ] **Step 1: 写完整漏斗 E2E RED 测试**

精确测试名：

- `data preparation to objective screening to review to finalized ranking`
- `a fresh install creates and reads back a preflight through real POST and polling routes`
- `a preflight deep link renders the exact persisted report and never a stale scan report`
- `an interrupted objective scan resumes from its persisted checkpoint`
- `a conflicted scan clones through a new snapshot without mutating its parent`
- `an optimistic review conflict preserves the local draft`
- `AI failure leaves the manual review path usable`
- `review UI collects evidence and requests an AI draft through real POST routes`
- `finalized csv and xlsx downloads use the selected ranking scope`
- `desktop confines wide-table scrolling to its own region`
- `mobile uses a step strip candidate cards and review drawer without page overflow`
- `review drawer returns focus to its opener`
- `the complete funnel is keyboard operable with visible focus`
- `validation failure focuses the error summary`
- `all four stages have no serious axe violations`
- `a page reload clears the bearer token and requires re-entry`
- `a submitted bearer token is removed from the DOM and only held in memory`
- `a ready snapshot starts a scan and resolved reviews finalize it through real POST routes`
- `two hundred percent zoom has no page-level horizontal overflow`
- `status meaning survives forced colors and reduced motion without color-only cues`

视口至少 1440×1000、1024×768、768×1024、390×844。

- [ ] **Step 2: 运行 RED**

Run from `lightweight-stock-analysis`:

    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\ensure-playwright-browser.ps1

Run from `lightweight-stock-analysis/frontend`:

    pnpm e2e

Expected: FAIL because e2e server/runner and at least one funnel wiring are absent.

- [ ] **Step 3: 实现唯一 tmp runtime 和进程清理**

`ensure-playwright-browser.ps1` 用 `[Environment]::GetFolderPath('LocalApplicationData')` 解析工作区外 `LSA/playwright/1.60.0`，拒绝落在 repo 内，设置 `PLAYWRIGHT_BROWSERS_PATH` 后运行 pinned package 的 `pnpm exec playwright install chromium`，写 revision marker 并读回 executable；缺 binary 且未获联网授权时明确 `BROWSER_NOT_PROVISIONED`，不宣称 E2E 已执行。release runtime 不携带也不需要浏览器。run-e2e.mjs 计算同一路径、校验 marker/revision 并设置 PLAYWRIGHT_BROWSERS_PATH，绝不隐式下载。

`run-e2e.mjs` 再占用并释放两个动态 loopback 端口，创建唯一 OS tmp 目录，并在其中分别创建 SQLite、artifact、cache、import、export、secrets、downloads 和 reports 路径，逐项设置 `LSA_ENV=test`、`LSA_TEST_REQUIRE_AUTH=true`、`LSA_E2E_DATABASE_PATH`/`LSA_DATABASE_URL`、`LSA_E2E_TOKEN_FILE` 与对应 LSA_*、`LSA_E2E_API_PORT`、`LSA_E2E_UI_PORT`，再启动 Playwright。配置 `workers: 1`、`reuseExistingServer: false`；后端 webServer 从 frontend cwd 调用 `powershell -NoProfile -ExecutionPolicy Bypass -File ..\scripts\start-e2e-backend.ps1`。该脚本用 `$PSScriptRoot` 解析项目根、验证 database/token paths 均在本次 tmp 且 database 不存在/为空、`Push-Location` 到 backend，先执行 `.\.venv\Scripts\python.exe -m app.cli init-db --database $env:LSA_E2E_DATABASE_PATH`，再执行 `.\.venv\Scripts\python.exe -m app.cli issue-token --database $env:LSA_E2E_DATABASE_PATH --output-path $env:LSA_E2E_TOKEN_FILE`，最后前台执行 `.\.venv\Scripts\python.exe -m tests.e2e_server`；stdout/report/environment 只携带 token file path，不携带 secret。finally 恢复 cwd。脚本契约测试从任意 cwd 启动并健康读回，且非空 DB/越界 token path 被拒绝。前端 webServer cwd 是 frontend 并启动 Vite。

`tests.e2e_server` 只在 test 环境注册 fixture provider/fake AI，并在 import app/httpx 前安装 `e2e_network_guard.install_loopback_only()`；guard 对 DNS 解析和 socket connect 只允许 127.0.0.1/::1，测试证明公网、私网和 metadata 目标均在连接前失败。整个 E2E server 始终启用 `LSA_TEST_REQUIRE_AUTH=true`，不按单测试切换。Playwright helper 等待 DACL token file 出现后只在内存读取：UI 用例经 token form 输入，API setup 用 Authorization header；不得 attach/log/screenshot secret，reload 后 UI 必须重新输入。该开关在非 test 环境启动必须失败。browser context 通过 request interception 拒绝 localhost 之外请求；runner 在 E2E 前后记录工作区 manifest，除本次 tmp 路径外任何写入都失败。finally 先终止子进程，确认端口无监听，再校验 resolved tmp path 位于本次创建目录后清理。可访问性自动门覆盖非颜色状态文字/图标、prefers-reduced-motion、forced-colors 和 200% zoom；发布清单另要求 Windows 高对比度与 Narrator/屏幕阅读器人工检查。

- [ ] **Step 4: 运行前端/E2E 门并提交**

Run from `lightweight-stock-analysis/backend`:

    .\.venv\Scripts\python.exe -m pytest tests/test_e2e_network_guard.py -v

Run from `lightweight-stock-analysis`:

    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\ensure-playwright-browser.ps1

Run from `lightweight-stock-analysis/frontend`:

    pnpm lint
    pnpm test
    pnpm typecheck
    pnpm build
    pnpm e2e
    git diff --check
    git add -- lightweight-stock-analysis/frontend lightweight-stock-analysis/scripts/start-e2e-backend.ps1 lightweight-stock-analysis/scripts/ensure-playwright-browser.ps1 lightweight-stock-analysis/scripts/tests/playwright-browser-contract.test.mjs lightweight-stock-analysis/backend/tests/e2e_server.py lightweight-stock-analysis/backend/tests/e2e_network_guard.py lightweight-stock-analysis/backend/tests/test_e2e_network_guard.py
    git commit -m "test(lsa): add responsive accessible end-to-end funnel"

---

### Task 8: 实现确定扫描/API/UI 性能验收

**Files:**

- Create: lightweight-stock-analysis/backend/app/benchmarks/objective_scan.py
- Create: lightweight-stock-analysis/backend/tests/performance/test_objective_benchmark.py
- Create: lightweight-stock-analysis/frontend/e2e/workbench.performance.spec.ts
- Create: lightweight-stock-analysis/frontend/e2e/support/performanceObserver.ts
- Create: lightweight-stock-analysis/scripts/run-performance.ps1
- Create: lightweight-stock-analysis/scripts/lib/acceptance-report.mjs
- Create: lightweight-stock-analysis/docs/acceptance/schemas/performance-report.schema.json
- Create: lightweight-stock-analysis/docs/acceptance/performance.md

- [ ] **Step 1: 写 manifest 拒绝和指标 RED 测试**

后端测试在 manifest 缺字段、input SHA-256 不符、listing_count 不是 10,000 或 expected_top50_hash 不匹配时拒绝运行。Playwright 测试名：

- `@performance candidate filtering and expansion stay below the UI p95 budget`
- `@performance no candidate interaction creates a main-thread task over one second`
- `@performance health and scan polling stay below the API p95 budget while scanning`

- [ ] **Step 2: 运行 RED**

Run from `lightweight-stock-analysis/backend`:

    .\.venv\Scripts\python.exe -m pytest tests/performance/test_objective_benchmark.py -v

Run from `lightweight-stock-analysis/frontend`:

    pnpm e2e:performance

Expected: FAIL because benchmark/report implementation is missing.

- [ ] **Step 3: 实现冷/热协议和资格报告**

run-performance.ps1 先调用 ensure-playwright-browser 并在报告记录 browser revision/path hash；缺 browser 且未获下载授权时返回 BROWSER_NOT_PROVISIONED，而不是性能结果。普通 `pnpm e2e` 在 Playwright config 里 `grepInvert: /@performance/`；`pnpm e2e:performance` 通过 runner 转发全部 CLI 参数并设置 `LSA_E2E_PROFILE=performance`，只加载 Plan 02 的 10,000-listing manifest。冷运行用新 Python 进程和复制到唯一 tmp path 的 SQLite 执行 1 次；热运行同进程预热 1 次后运行 5 次取中位数。两者均需在 60 秒内完成快照硬过滤、六维评分和 Top 50。API 阶段只在 scan=RUNNING 时对 `/api/health` 和 `/api/scans/{id}` 各收集恰好 100 个有效样本；scan 原子冻结进入 REVIEW_PENDING 后，UI 阶段才对可读的 frozen candidates 连续做 50 次过滤/展开，两个阶段的样本和门槛分别报告，不把候选误称为 RUNNING 时可读。API p95 ≤ 500 ms，input-to-next-paint p95 ≤ 200 ms，最大 long task ≤ 1000 ms。样本不足、状态顺序错误或 profile 未加载均 FAIL。

报告保存全部原始样本，记录 Windows/CPU/逻辑核/可用内存/SSD、Python/Node/浏览器版本、SQLite 大小、峰值内存、原始/feature 行数。不满足 Windows x64、4 逻辑核、8 GB 可用内存、本地 SSD 时状态必须是 `ENVIRONMENT_NOT_QUALIFIED`，不宣称通过。该状态允许继续构建离线原型，但性能验收保持 OPEN，阶段四/发布验收不得标完成，必须在合格机器重跑并得到 PASS。

- [ ] **Step 4: 运行性能门并提交**

Run:

    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-performance.ps1
    git diff --check
    git add -- lightweight-stock-analysis/backend/app/benchmarks lightweight-stock-analysis/backend/tests/performance/test_objective_benchmark.py lightweight-stock-analysis/frontend/e2e lightweight-stock-analysis/scripts/run-performance.ps1 lightweight-stock-analysis/scripts/lib/acceptance-report.mjs lightweight-stock-analysis/docs/acceptance
    git commit -m "perf(lsa): add deterministic release benchmarks"

---

### Task 9: 实现独立安装、同源运行和可验证发布包

**Files:**

- Modify: lightweight-stock-analysis/.gitignore
- Create: lightweight-stock-analysis/.env.example
- Create: lightweight-stock-analysis/README.md
- Create: lightweight-stock-analysis/scripts/install.ps1
- Create: lightweight-stock-analysis/scripts/start-dev.ps1
- Create: lightweight-stock-analysis/scripts/start.ps1
- Create: lightweight-stock-analysis/scripts/build-release.ps1
- Create: lightweight-stock-analysis/scripts/verify-independent.ps1
- Create: lightweight-stock-analysis/scripts/verify-release.ps1
- Create: lightweight-stock-analysis/scripts/lib/release-manifest.mjs
- Create: lightweight-stock-analysis/scripts/tests/release-contract.test.mjs
- Create: lightweight-stock-analysis/backend/app/static_frontend.py
- Modify: lightweight-stock-analysis/backend/app/main.py

- [ ] **Step 1: 写 release manifest 与独立性 RED 合约测试**

Node test 断言：release manifest 对每个打包文件有 SHA-256；必含 backend/app、alembic.ini 与 01→09 revisions、requirements.lock、defensive-score/public-source 两个 YAML、frontend/dist、install/start/build/verify scripts、README/.env.example/acceptance docs；拒绝 data、SQLite/WAL/SHM、credentials/secrets/token、cache、uploads/exports、node_modules、test reports、`.env`；独立检查拒绝父源码 import；父树前后 hash 能发现意外写入；预构建前端不含 token/provider credential。

- [ ] **Step 2: 运行 RED**

Run:

    node --test scripts/tests/release-contract.test.mjs

Expected: FAIL because release scripts and manifest builder are missing.

- [ ] **Step 3: 实现安全 PowerShell 脚本契约**

- `install.ps1`: 验证 Node 24.x LTS；显式检查 pnpm 11，不假设 Corepack，缺失时给出固定版本安装指令并退出（联网安装需另行授权）；用配置 Python 3.12 在包内创建 backend/.venv，按 requirements.lock hash 安装，pnpm frozen lock 安装。可选 `-InitializeNewDatabase -DatabasePath <path>` 只调用 Plan 03 `python -m app.cli init-db --database <path>`，目标必须不存在/空；既有库永不自动迁移。
- `start-dev.ps1`: 后端单 worker/8177，Vite 使用自己依赖代理 `/api`；Ctrl+C 清理两进程。
- `start.ps1`: 生产构建由单 worker FastAPI 同源服务 frontend/dist，默认 127.0.0.1，API 路由先于 SPA fallback。
- `build-release.ps1`: 先跑离线门，再复制允许文件到唯一 tmp staging，生成逐文件 hash manifest 和带时间戳+content hash 的唯一 zip，stdout/报告返回唯一 absolute artifact path。
- `verify-independent.ps1`: 复制到父 repo 外 tmp，清 PYTHONPATH/NODE_PATH，按自身 lock 安装；调用 ensure-playwright-browser 并显式传外部 versioned browser path 后测试，父树前后清单/hash 不变。浏览器缺失是未执行，不得借同机隐式缓存通过。
- `verify-release.ps1 -PackagePath <exact-absolute-zip>`: 不搜索“最新”工件；解压到空 tmp、验 manifest、安装、以新路径走 `-InitializeNewDatabase`、启动，检查 `/api/health/live`、SPA root、非 API 未知路径的 SPA fallback、`/api/unknown` 仍为 JSON 404，关闭后检查端口释放。另以预置非空数据库运行 install 并断言拒绝且 hash 不变。

任何递归删除前先用 `Resolve-Path -LiteralPath` 确认目标是本次创建的 OS tmp 子目录，不对工作区根或未解析变量删除。

- [ ] **Step 4: 运行独立/发布验证并提交**

Run:

    node --test scripts/tests/release-contract.test.mjs
    cd backend
    .\.venv\Scripts\python.exe -m pytest tests/api tests/test_db_initialization.py -v
    cd ..
    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify-independent.ps1
    $packagePath = powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build-release.ps1
    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify-release.ps1 -PackagePath $packagePath
    git diff --check
    git add -- lightweight-stock-analysis/.gitignore lightweight-stock-analysis/.env.example lightweight-stock-analysis/README.md lightweight-stock-analysis/scripts lightweight-stock-analysis/backend/app/static_frontend.py lightweight-stock-analysis/backend/app/main.py
    git commit -m "build(lsa): package an independently verified application"

---

### Task 10: 冻结离线、Gate 0 和发布验收文档

**Files:**

- Create: lightweight-stock-analysis/docs/acceptance/offline-acceptance.md
- Create: lightweight-stock-analysis/docs/acceptance/gate-0-live-data.md
- Create: lightweight-stock-analysis/docs/acceptance/release-checklist.md
- Create: lightweight-stock-analysis/docs/acceptance/templates/gate-0-report.md
- Create: lightweight-stock-analysis/scripts/run-gate0.ps1
- Create: lightweight-stock-analysis/scripts/verify-gate0-ui.mjs
- Create: lightweight-stock-analysis/scripts/tests/acceptance-docs.test.mjs
- Create: lightweight-stock-analysis/scripts/tests/run-gate0-contract.test.mjs
- Modify: lightweight-stock-analysis/README.md

- [ ] **Step 1: 写能力声称 RED 文档合约测试**

精确断言文档：定义 NOT_CONFIGURED/LIVE_PARTIAL/LIVE_READY 三态；说明 TEST_ONLY 不能通过 Gate 0；每市场 10 个确定真实读回；包含带必填 `-AsOfDate YYYY-MM-DD` 的离线 canonical 命令，以及显式 `-ApiBaseUrl` 的在线命令；缺报告/过期/未达门槛禁止 live-ready 声称；报告模板不要求粘贴凭据、密钥路径或原始敏感错误。

- [ ] **Step 2: 运行 RED**

Run:

    node --test scripts/tests/acceptance-docs.test.mjs

Expected: FAIL because acceptance documents are missing.

- [ ] **Step 3: 编写精确验收边界**

Gate 0 文档记录 provider 许可用途/再分发边界、reference snapshot id/hash、每项 coverage 分子/分母、10 样本读回、gate0_policy_hash、report hash、measured_at、expires_at 和本次实际 AsOfDate，不记 token/key。文档包装命令要求调用者显式提供日期；无 `-ApiBaseUrl` 是离线 CLI 模式：

    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-gate0.ps1 -AsOfDate YYYY-MM-DD

在线模式必须显式指定地址；loopback 不带 token，非 loopback 还必须指定由 Plan 03 CLI 创建、位于本 installation secrets 目录且已验证 DACL 的 token file：

    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-gate0.ps1 -AsOfDate YYYY-MM-DD -ApiBaseUrl http://127.0.0.1:PORT
    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-gate0.ps1 -AsOfDate YYYY-MM-DD -ApiBaseUrl https://HOST -TokenFile .\runtime\secrets\api-token.txt

run-gate0.ps1 用 `$PSScriptRoot` 解析 `backend\.venv\Scripts\python.exe`，验证文件存在且是 Python 3.12，再 Push-Location backend；绝不调用裸 python/Windows Store alias。它拒绝省略、未来或非法日期，并冻结两条互斥时序：传 `-ApiBaseUrl` 时只走 health identity 校验→authenticated POST→job poll→preflight GET API；未传时才执行 job-backed CLI，若发现同库 writer lease 已占用则以 `SERVER_ACTIVE_USE_API` 拒绝并要求调用者提供地址，不猜测端口。API URL 只允许 loopback HTTP 或 HTTPS；health 必须返回预期 service/api schema/installation identity，错误服务先于 POST 被拒绝。loopback 禁止要求或记录 token；非 loopback 缺 TokenFile、路径越出本 installation secrets 目录、DACL 读回失败均拒绝，脚本只在请求局部读取 bearer，不放进 argv/env/report/stdout/stderr。离线 CLI 等待 terminal 与 lease 释放，再以同库临时启动包含已构建 SPA 的单 worker 服务；API GET 与 UI readback 都结束后才关闭。

`verify-gate0-ui.mjs` 复用 Task 7 已显式 provision 的版本化 Playwright Chromium，导航到同源 `/?preflight_id=<id>`，若非 loopback则只从父脚本匿名 stdin 读取 bearer 并填写 password token form，不通过参数、环境、日志、截图或 trace 传递；随后断言 PreflightReportCard 与 CapabilityBanner 的 report/policy hash、expiry 和三状态逐项等于刚才 API GET，且页面没有旧 scan 报告。在线和离线两条路径都必须在服务仍在线时通过该 helper；浏览器未 provision、UI hash 不等或 helper 未运行均记录 `UI_READBACK_NOT_RUN/FAILED` 并阻止 Gate 0 完成。两条路径最后记录并输出同一 `preflight_id` 与 `/?preflight_id=<id>` 深链，不会重复运行 Gate 0。run-gate0-contract.test.mjs 在无外网 fixture 下用受控 fake helper 覆盖缺参/未来日期/解释器错误、NOT_CONFIGURED exit code、错误 service/identity、unsafe URL、非 loopback 缺 token 或坏 DACL、在线 API 不调用 CLI、离线 active lease 拒绝、离线 CLI 后释放 lease再启动读回、token 仅走 stdin，以及 deep link 精确加载同一报告；真实 provider 仍需另行联网授权。

文档明确真实 Gate 0 不运行交易、不写父项目。真实验收不仅检查 CLI/API，还通过保存后的 preflight GET API，以及按同一 preflight_id 渲染的 PreflightReportCard 与 CapabilityBanner，读回 capability_state/acceptance_mode/synthetic/gate0_policy_hash/report hash/expiry，确认 TEST_ONLY 没有被 UI 提升。AuditFooter 仅在之后显式创建/选择绑定该 report/policy hash 的 scan 时做二次验收，不参与尚无 scan 的即时 Gate 0 结论。Gate 0 失败不阻止离线包交付，但阻止“A 股与港股全市场能力已完成”。

- [ ] **Step 4: 运行总门并提交**

Run first from `lightweight-stock-analysis/frontend`:

    pnpm install --frozen-lockfile

Then run from `lightweight-stock-analysis`; this must succeed before the first E2E command:

    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\ensure-playwright-browser.ps1

Return to `lightweight-stock-analysis/frontend`:

    pnpm lint
    pnpm test
    pnpm typecheck
    pnpm build
    pnpm e2e

Run from `lightweight-stock-analysis/backend`:

    .\.venv\Scripts\python.exe -m pytest tests/api
    .\.venv\Scripts\python.exe -m pytest

Run from `lightweight-stock-analysis`:

    node --test scripts/tests/*.test.mjs
    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify-independent.ps1
    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-performance.ps1
    $packagePath = powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build-release.ps1
    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify-release.ps1 -PackagePath $packagePath
    git diff --check
    git add -- lightweight-stock-analysis/docs/acceptance lightweight-stock-analysis/scripts/run-gate0.ps1 lightweight-stock-analysis/scripts/verify-gate0-ui.mjs lightweight-stock-analysis/scripts/tests/acceptance-docs.test.mjs lightweight-stock-analysis/scripts/tests/run-gate0-contract.test.mjs lightweight-stock-analysis/README.md
    git commit -m "docs(lsa): define offline and gate zero acceptance"

Expected: 离线自动门全通过，性能报告必须为 PASS 才能关闭阶段四；`ENVIRONMENT_NOT_QUALIFIED` 只允许生成标有“性能验收未完成”的离线原型，随后必须在合格硬件重跑。真实 Gate 0 没有在未授权情况下运行。

阶段四完成条件：子应用可在父仓库外依自身锁文件安装、测试、构建和启动；四阶段漏斗在真实测试 API 上通过；合格硬件性能报告为 PASS；未通过真实 Gate 0 时界面、文档和发布说明都不会误称 LIVE_READY。
