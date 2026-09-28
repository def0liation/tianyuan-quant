# super Phase 1-3 完整开发计划

更新日期：2026-05-27

本文是 `super` 后续 Phase 1-3 的开发合同，用于把研究闭环、真实浏览器 E2E 和本地 SQLite worker 平台化拆成三段可验收交付。开发时按阶段串行推进，不把三段一次性混成大包。若本文和当前代码、测试或 `docs/DEVELOPMENT_LOG.md` 冲突，以当前代码和最新已验证开发日志为准，并同步修正文档。

## 0. 不可回退边界

- 全程保持 `simulation_only=true`、`is_real_trade=false` 和 `SIM_*` 动作语义。
- 不连接券商，不新增真实下单 API，不生成真实订单，不把 SignalOps 沙箱动作描述成实盘自动交易。
- 不污染当前 `storage/tianyuan_quant.db`；live/E2E 验收必须使用 `.tmp` 下临时 SQLite。
- Phase 3 只新增本地 SQLite analysis worker 能力；默认执行路径仍保持 in-process。
- 不新增生产迁移。若确需 schema 变化，只生成 migration、补测试并说明影响，不直接执行生产迁移命令。
- Phase 4 只做实盘架构设计，不进入本轮实现。

## 1. 开发前置检查

每段开工前先阅读相关模块、测试和最近变更：

- Portfolio：`backend/app/api/routes_portfolio.py`、`backend/app/core/portfolio_store.py`、`backend/tests/test_portfolio_store.py`
- Analysis：`backend/app/api/routes_analysis.py`、`backend/app/core/analysis_job_store.py`、`backend/tests/test_analysis_workflow.py`
- SignalOps：`backend/app/api/routes_signalops.py`、SignalOps lifecycle 相关 store/tests、`frontend/src/components/signalops/SignalOpsPage.tsx`
- Backtest / Research：`backend/app/core/backtest_store.py`、`backend/app/core/research_store.py`、`backend/app/core/research_verdict_store.py`、`backend/tests/test_research_store.py`
- Frontend：`frontend/src/App.tsx`、`frontend/src/routeManifest.json`、`frontend/src/api/`、相关页面组件
- 文档：`docs/DEVELOPMENT_GUIDE.md`、`docs/API_CONTRACT.md`、`docs/STORAGE_DESIGN.md`、`docs/TESTING_GUIDE.md`、`docs/DEVELOPMENT_LOG.md`

阶段开始前运行：

```powershell
npm.cmd run audit:baseline
git status --short
```

`audit:baseline` 用于记录当前运行库和工作树状态；它可以显示当前运行库仍为空，但不得为了验收直接写入当前运行库。

## 2. 交付节奏

| Phase | 目标 | 主要验收 |
| --- | --- | --- |
| Phase 1 | 可信研究闭环 | 同一套 `portfolio -> run -> SignalOps -> backtest -> research -> case -> knowledge -> evaluation` ID 可追踪；弱证据不能升级强结论 |
| Phase 2 | 产品 E2E 和 Research Lab 成熟度 | 临时库真实浏览器点击闭环可见；Research Lab 状态以后端 `workflow_state` 和 blocking reasons 为准 |
| Phase 3 | 本地 SQLite worker 平台化 | `ANALYSIS_EXECUTION_MODE=worker` 下只入队；worker claim/heartbeat/cancel/recovery 可验收；默认 in-process 不变 |

每段结束都更新 `docs/DEVELOPMENT_LOG.md`，记录范围、验证命令、结果和剩余风险。

## 3. Phase 1：可信研究闭环

目标：完成 `/portfolio -> /new-task -> analysis run -> SignalOps -> Backtest -> Research -> Case -> Knowledge -> Evaluation` 的同一套 ID 链路，优先复用现有 `portfolio_snapshot_id`、SignalOps lifecycle、Research Lab、Backtest fingerprint 去重和 P2 closed-loop sample 能力。

### 3.1 实现范围

- Portfolio 快照必须真实进入 `CreateAnalysisRequest.portfolio_snapshot_id`，并在 analysis run、Research iteration 和 workflow state 中可追踪。
- Analysis run 完成后继续保持 SignalOps lifecycle 衔接，且不改变 `simulation_only=true`、`is_real_trade=false`、`SIM_*`。
- Backtest 继续以 Research Lab 为可见工作台，以 Backtest store/report 为运行引擎；复用稳定 fingerprint 去重，不重复造平行闭环。
- Research evidence 和 workflow state 增加或补齐 portfolio、benchmark、out-of-sample、mock/fallback、evaluation、knowledge version 的阻塞原因。
- Case、Knowledge、Evaluation 物化必须幂等；已有 artifact 优先复用，失败时返回可见 warning 或 blocking reason。

### 3.2 Backtest 研究级输出

Backtest 输出必须带：

- benchmark 信息和不可用原因。
- 样本外 / walk-forward 验证结果。
- 成本、滑点、成交约束。
- 实验包 hash。
- mock / fallback / source 标记。
- research evidence package 或等价可追踪证据引用。

`LOW`、`SUPPORTING_ONLY`、`MOCK`、`MOCK_FALLBACK`、无样本外验证、benchmark 不可用或 source 不清晰的结果，不允许升级为强研究结论。

### 3.3 Phase 1 验收

- 临时 SQLite 中 `portfolio_snapshots > 0` 且 `holding_positions > 0`。
- run / SignalOps / backtest / research / case / knowledge / evaluation ID 可从 API 或 Research Lab 响应追踪。
- Research verdict inputs 能解释阻塞原因，不靠前端猜测。
- 弱证据路径有测试覆盖，不能被自动接受为强结论。

## 4. Phase 2：产品 E2E 和 Research Lab 成熟度

目标：扩展临时库 smoke，启动 backend/frontend 后用真实浏览器点击 `/portfolio -> /new-task -> /live-run -> /research-lab`，验证快照创建、任务创建、运行状态、Research Lab 证据链 ID 和阻塞原因可见。

### 4.1 实现范围

- 扩展 `npm.cmd run smoke:research-closure:browser`，使用 `.tmp` 下临时 SQLite，启动独立 backend/frontend，不依赖当前本地运行库。
- Browser smoke 需要真实点击关键 UI，而不只验证路由可访问。
- Research Lab UI 的 `PASS` / `WARN` / `WAIT` / `READY` / `BLOCKED` 以后端 `workflow_state.steps[]`、`blocking_reasons` 和 verdict inputs 为准；前端只做展示和空态兜底。
- 新用户入口保留“一键样例/闭环样例”，但样例生成默认只在 smoke 临时库中验证，不写当前运行库。
- 证据链 ID、阻塞原因、下一步动作必须在页面可见，便于用户知道缺什么。

### 4.2 Phase 2 验收

- `npm.cmd run smoke:research-closure:browser` 能在临时库中完成真实浏览器闭环。
- 页面能看到 portfolio snapshot、analysis run、backtest、research iteration、case、knowledge、evaluation 的关键 ID 或阻塞原因。
- Research Lab 成熟度状态不由前端本地规则强行推断；后端字段缺失时只展示明确空态。
- 当前 `storage/tianyuan_quant.db` 不因 smoke 增加样例数据。

## 5. Phase 3：本地 SQLite worker 平台化

目标：保留默认 in-process 执行；新增 `ANALYSIS_EXECUTION_MODE=worker` 时，`POST /api/analysis/runs/{run_id}/start` 只入队，由本地 worker loop 从 SQLite `analysis_jobs` claim 任务执行。

### 5.1 实现范围

- 新增本地命令脚本：`npm.cmd run worker:analysis`，启动本地 SQLite analysis worker。
- 复用现有 `analysis_jobs` 字段：`queue_name`、`attempt`、`concurrency_group`、`concurrency_limit`、`worker_id`、`worker_heartbeat_at`、`stale_reason`、`recovery`。
- 默认 `concurrency_limit=1`，同一 `concurrency_group` 不并发执行。
- Worker 支持 claim、heartbeat、cancel、failed / completed / stale recovery。
- `GET /api/analysis/jobs` 继续作为状态观察面，API 重启后 job/run 状态一致。
- 文档说明 SQLite 是 jobs / portfolio / research / backtest / case / knowledge / evaluation 的权威来源；JSON 只作为 run artifact / export 或兼容镜像。

### 5.2 Public Interface

- `POST /api/analysis/runs/{run_id}/start`：默认行为保持现状；worker mode 下返回 `status="QUEUED"` 或当前 job 状态。
- 前端需要显示排队、运行、取消中、失败、完成、stale/recovered 等终态或中间态。
- `npm.cmd run worker:analysis`：启动本地 worker loop。
- `npm.cmd run smoke:research-closure:browser`：继续使用临时 SQLite 验证真实浏览器闭环。

### 5.3 Phase 3 验收

- worker mode 下创建 2 个 run，确认默认 concurrency limit 生效。
- `worker_heartbeat_at` 持续更新，worker 退出或超时后 stale recovery 可见。
- cancel 可终止 queued/running job，并同步 run 状态。
- failed/completed/stale job 的 API、SQLite 和 run detail 状态一致。
- 默认 in-process 执行路径不回归。

## 6. 验证矩阵

后端聚焦：

```powershell
npm.cmd run validate:module-participation
npm.cmd run test:backend -- backend\tests\test_portfolio_store.py backend\tests\test_analysis_workflow.py backend\tests\test_signalops_routes.py backend\tests\test_backtest_store.py backend\tests\test_research_store.py backend\tests\test_research_verdict_store.py backend\tests\test_research_artifact_store.py backend\tests\test_evaluation.py -q
```

前端和类型：

```powershell
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run build
```

全量回归：

```powershell
npm.cmd run test:backend
npm.cmd run smoke:frontend
git diff --check
```

闭环验收：

```powershell
npm.cmd run audit:baseline
npm.cmd run validate:phase1-3
npm.cmd run smoke:research-closure:browser
```

闭环 smoke 必须在临时库中断言：

- `portfolio_snapshots > 0`
- `holding_positions > 0`
- run / backtest / research / case / knowledge / evaluation ID 可追踪

Worker 验收在 Phase 3 增加：

```powershell
npm.cmd run smoke:analysis-worker
```

- worker mode 创建 2 个 run。
- concurrency limit 生效。
- heartbeat 更新。
- cancel 可终止。
- stale job 可恢复。
- API 重启后 job/run 状态一致。

## 7. 风险清单

- 弱证据误升级：`LOW`、`SUPPORTING_ONLY`、`MOCK`、`MOCK_FALLBACK` 必须保持阻塞或降级。
- 存储污染：live/E2E 必须使用临时 SQLite，不写当前运行库。
- 状态漂移：run、job、Research iteration、Backtest report 和前端状态必须有单一权威解释。
- Worker 竞态：claim、heartbeat、cancel 和 stale recovery 必须覆盖并发与进程退出场景。
- API 兼容：schema 变化必须同步 Pydantic model、前端类型、调用方和测试。
- 历史 auth/session bug：涉及 auth、session、cookie、middleware 时必须检查 cookie name、sameSite、secure、domain、path 和 token 来源，并补 session 持久化测试。

## 8. Definition of Done

每个阶段完成时必须给出：

- 改了什么。
- 为什么这样改。
- 跑了哪些检查和结果。
- 哪些数据写入了临时库，确认当前运行库未被污染。
- 剩余风险和下一阶段入口。
