# 开发指南

更新日期：2026-06-09

本文是 `super` 的当前开发入口。它只保留当前事实、边界、入口、风险规则和验证矩阵；已经完成的开发不在本文保留流水，统一压缩为“当前基线”。需要追溯 Scope、Changes、Validation、Risk 时看 `docs/DEVELOPMENT_LOG.md`。

如果本文和代码、测试或最新开发日志冲突，以代码和最新已验证日志为准，并同步修正文档。

## 0. 文档权威地图

后续开发按下面顺序取事实，避免从旧计划或历史聊天结论直接开工：

| 文档 | 当前用途 |
| --- | --- |
| `docs/DEVELOPMENT_GUIDE.md` | 主开发入口：边界、入口、当前基线、修改流程、验证矩阵 |
| `docs/DEVELOPMENT_LOG.md` | 已落地变更流水，最新条目优先级高于旧评估 |
| `docs/NEXT_DEVELOPMENT_PLAN.md` | 当前 Phase 1-3 开发合同；Phase 4 仅做实盘架构设计 |
| `docs/AGENT_REGISTRY.md` | 当前 8 个活跃 Agent、run mode 顺序、legacy Agent ID 归属 |
| `docs/FRONTEND_REDESIGN_GUIDE.md` | 本次前端重构设计稿、开发规则、响应式/Figma/可访问性/性能/发布回滚/观测和验收标准 |
| `docs/QUANT_CORE_DEVELOPMENT_GUIDE.md` | `quant_core` / `quantCore` / `/quant-core` 契约和兼容规则 |
| `docs/API_CONTRACT.md` | API 字段、canonical/legacy 路由、Research/Backtest/SignalOps 契约 |
| `docs/TESTING_GUIDE.md` | 测试入口、聚焦回归和 smoke 命令 |
| `START_DEV.md` | 本地启动、停止、端口漂移和 `.logs` 运行态 |
| `docs/PROJECT_DEVELOPMENT_ASSESSMENT.md`、`docs/QUANT_SYSTEM_IMPROVEMENT_PLAN.md` | 历史评估和路线参考，不能作为未经复核的当前事实 |

旧 `OPEN_DEVELOPMENT_BACKLOG.md`、`FULL_RUN_CHECKLIST.md`、`AUDIT_REPLAY.md` 和已完成的 `CODE_REVIEW_FIX_GUIDE_2026-05-21.md` 已删除。闭环证据保留在 `docs/DEVELOPMENT_LOG.md`，不要重新从旧 backlog 或已归档专项指南复制未复核条目。

## 1. 文档压缩规则

已完成开发只允许在本指南里留下四类信息：

- 当前事实：系统现在怎么工作。
- 当前边界：哪些行为不能回退或弱化。
- 当前入口：开发、启动、验证命令。
- 当前风险：仍需要防止的失败模式。

不要在本指南保留完成项的长篇历史、旧 checklist、逐条修复流水、旧命令 transcript 或已删除文档链接。完成项如果改变了当前契约，只更新对应契约行，并在 `docs/DEVELOPMENT_LOG.md` 追加详细记录。

已归档删除的完成项只保留当前结论：

- 2026-05-21 代码审查修复指南已完成并删除；R1-R13、T1-T3、D1-D3 均无剩余当前开发项。
- 对应当前基线：runtime secret-adjacent response redaction、SignalOps partial update、market-data cache fingerprint、shared portfolio import request、stream terminal states、Settings adapter degraded state、dev Docker port、runtime storage ignore、WebSocket stream hardening、production launcher token requirement、DB restore path guard、nullable frontend field guards、SignalOps stale-detail guard、默认后端高风险覆盖、显式 typecheck、ASGI auth/simulation boundary、Coze retired guard、UTF-8/mojibake guard、`start-dev.ps1 -Install` explicit recreate guard。
- 如未来出现新的代码审查建议，不恢复旧专项指南；在 `docs/DEVELOPMENT_LOG.md` 写新记录，并把仍影响当前契约的结论同步到本指南或对应契约文档。

## 2. 项目边界

`super` 是本地量化研究与模拟交易控制台，目标是帮助用户完成可复核的分析、模拟、回测、研究沉淀和知识回归。

必须保留的边界：

- 当前不是生产级实盘自动交易系统。
- SignalOps 只输出 `SIM_*` 沙箱动作，`simulation_only=true` 和 `is_real_trade=false` 不能被弱化。
- 不连接真实券商账户，不新增真实下单 API，不生成非 `SIM_*` 买卖动作。
- 插件默认是只读 plan 或受控 dry-run，不允许任意代码执行和真实交易动作。
- strict auth 下 API token 决定 operator 身份；前端传入的 operator header 不能覆盖 token 角色。
- LLM/行情外联必须经过官方 host、本地 host 或服务端 allowlist；用户可写确认字段不能绕过服务端 egress 策略。
- MFE/MAE Path Research 只能提供研究证据和受控的一步 QIAM 校准，不能直接放行 BUY/ADD/SELL。
- Final Writer 只能汇总和解释已有证据，不能绕过 Guardrail Hub、Quant Core/QIAM、Execution 等门禁自行给出交易动作。
- Supabase 或其他外部 Postgres 只能作为后续显式接入的外部数据服务；当前默认权威运行库仍是本地 SQLite / storage，不得在未完成迁移设计、权限审计和回滚方案前改成 Supabase。
- Web 数据可视化必须服务于证据解释和运行复核，不做无数据含义的装饰性图形、渐变背景或动画；关键数值不能只依赖 hover 才可见。

## 3. 快速入口

### 3.1 启动和关闭

```powershell
.\start-dev.ps1 -Open
```

默认地址：

- Frontend: `http://127.0.0.1:5174`
- Backend: `http://127.0.0.1:8000`
- API docs: `http://127.0.0.1:8000/docs`

启动器会等待 `/api/startup/status` 的 `coreReady=true`；optional warmers 可以继续后台执行。默认端口被占用时，启动脚本会自动选择后续可用端口并打印实际 URL。

关闭：

```powershell
.\stop-dev.ps1
npm.cmd run dev:stop
```

需要后端热重载时显式使用：

```powershell
.\start-dev.ps1 -BackendReload
```

### 3.2 活跃代码目录

| 区域 | 入口 |
| --- | --- |
| 后端装配 | `backend/app/main.py` |
| 后端 API | `backend/app/api/` |
| 后端核心服务 | `backend/app/core/` |
| 后端模型 | `backend/app/models/` |
| 后端测试 | `backend/tests/` |
| 活跃前端 | `frontend/src/` |
| 前端路由 | `frontend/src/App.tsx`、`frontend/src/routeManifest.json` |
| 前端 API client | `frontend/src/api/` |
| 前端页面和组件 | `frontend/src/components/` |

旧根目录 `src/` 前端已删除，不能恢复成产品入口；新增或修改产品页面只进入 `frontend/src/`。

### 3.3 常用检查

Windows 本地入口优先使用根目录 `npm.cmd` 脚本，不假设 `pnpm` 一定可用。

```powershell
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run build
npm.cmd run test:backend
npm.cmd run smoke:frontend
npm.cmd run smoke:frontend:responsive
npm.cmd run chaos:isolated
```

闭环和阶段验收：

```powershell
npm.cmd run audit:baseline
npm.cmd run smoke:closed-loop-participation
npm.cmd run smoke:analysis-worker
npm.cmd run validate:premerge
npm.cmd run validate:module-participation
npm.cmd run validate:phase1-3
```

`validate:premerge` 当前默认覆盖默认后端回归、closed-loop sample、analysis worker、typecheck、lint、build、static smoke、frontend responsive smoke 和 strict-auth browser matrix；跳过项只用于本地快速定位，不能作为广泛验收口径。

Research Lab / MFE-MAE closure smoke：

```powershell
npm.cmd run smoke:research-closure
npm.cmd run smoke:research-closure:browser
```

Guardrail Hub / Agent DAG 兼容检查：

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\test_guardrail_hub.py backend\tests\test_agent_runtime.py -q
.\.venv\Scripts\python.exe -m pytest backend\tests\test_guardrail_hub.py backend\tests\test_agent_executor.py backend\tests\test_dvg_gate.py backend\tests\test_risk_agent.py backend\tests\test_kill_switch.py -q
npm.cmd run typecheck
npm.cmd run lint
```

说明：历史上 `.venv` 和 `backend/.venv` 的 Python launcher 多次失效。优先使用根目录 npm 脚本，它会走 `scripts/test-backend.ps1` 和项目约定的 `uv` / 缓存路径。

## 4. 当前系统基线

已完成的架构收敛只保留为当前基线：

| 面 | 当前事实 |
| --- | --- |
| 后端启动 | `backend/app/main.py` 装配 FastAPI；启动先完成核心数据库准备并标记 `CORE_READY`，后台再 warming analysis/research/backtest/global-market/auto-paper 摘要 |
| Readiness | `GET /api/startup/status` 是 phase-aware readiness 权威入口；`GET /api/health` 用于基础健康；`GET /api/ready` 用于依赖可用性且不得暴露本地路径或明文 secret |
| Analysis detail | 可以返回只读 `dashboardSummary` 给 Dashboard 决策工作台；projection 不写回 run storage |
| 前端产品面 | Dashboard、New Task、Live Run、Portfolio、Data Health、Quant Core、SignalOps、Research Lab、Backend Status、Config、Settings、Plugins、Case/Knowledge/Evaluation |
| 前端视觉基线 | 当前是浅色机构级科技金融工作台：68px 图标轨、顶部命令栏、二级横向页签、白色 surface、浅灰容器、蓝色主色、青绿色数据强调、6/8/10px 半径、紧凑数据表 |
| Legacy route | `/research-lab/backtest` 是当前 Backtest 工作台；`/backtest`、`/market`、`/technical-kline`、`/bottom-research`、`/quant-engine`、`/scenario` 只做 redirect 或兼容入口 |
| Agent manifest | 当前活跃 8 个 Agent；DVG、Risk、Trade Micro 相关旧节点已收敛进 `guardrail_hub`，市场、技术、研究、量化、情景和 QIAM 相关旧节点已收敛进 `quant_core` |
| Guardrail Hub 输出 | canonical 字段是 `run.guardrailHub` / `AnalysisRun.guardrailHub`；旧公共字段 `dvg`、`risk`、`atrade`、`killSwitch` 必须继续由它镜像回填 |
| Quant Core 输出 | canonical 字段是 `run.quantCore` / `AnalysisRun.quantCore`；legacy 字段只做兼容读取 |
| Guardrail legacy route | `/guardrail-hub` 是统一页面和主侧栏唯一入口；`/dvg-gate`、`/risk`、`/trade-micro` 只作为对应 tab 的兼容深链，记录在 `routeManifest.legacyRoutes` |

### 4.1 前端数据呈现基线

当前样图落地不是只换壳层。`routeManifest.json` 内所有导航入口、Research Lab 子路由、legacy redirect 入口和仍保留的 legacy 页面组件，都必须使用统一的机构级数据呈现方式：

- 核心指标使用 `MetricTile` 或同等 Material 数据组件；研究子页可通过 `ResearchMetricCard` 间接复用同一视觉系统。
- 表格使用 `TableShell` 和 `institution-table`，保持紧凑 header、右对齐数值、空值占位、状态色和来源/证据标签一致。
- 证据、来源、新鲜度、因子贡献、矩阵和 sparkline 优先使用 `EvidenceLedger`、`SourceFreshnessPanel`、`FactorBarStack`、`MatrixHeatmap`、`InlineSparkline`。
- Recharts/ReactFlow 能力保留，但标题、关键值、单位、来源、新鲜度、状态和分组 legend/直接标签必须直接可见，不能依赖 hover 才能理解。
- 页面不得新增裸 `fetch`；新增读取必须进入 `frontend/src/api/*Client.ts` 并继续使用 unknown-first response guard。
- `smoke:frontend` 会静态检查每个 `*Page.tsx` / `*Console.tsx` 是否接入共享 Material 数据呈现、是否保留 `institution-table`，并阻止旧暗色驾驶舱、渐变壳层或宽侧栏导航回归。

当前 DAG：

```text
FAST_MODE:
orchestrator -> data_reliability_engine -> guardrail_hub -> quant_core -> final_writer

STANDARD_MODE / DEEP_MODE:
orchestrator -> data_reliability_engine -> guardrail_hub -> quant_core -> execution
-> anti_conclusion -> signalops -> final_writer
```

开发 Agent 顺序或字段时必须同步：

- `backend/app/core/agent_framework.py`
- `backend/app/modules/agent_registry.py`
- 对应 module、prompt 和测试
- `frontend/src/types/index.ts`
- Dashboard、DAG、相关页面展示
- `docs/AGENT_REGISTRY.md`

### 4.2 统一护栏中枢开发指南

- `guardrail_hub` 是 DVG、Risk、Trade Micro 的唯一活跃护栏节点；`dvg_gate`、`risk_firewall`、`trade_micro`、`atrade` 仅作为 alias、历史读取、修复和 retry 映射保留。
- 修改护栏规则时必须同步检查旧字段镜像：`run.dvg`、`run.risk`、`run.atrade`、`run.killSwitch`、`run.guardrailHub`、`agentModuleResults.guardrail_hub` 以及旧 `dvg_gate/risk_firewall/trade_micro` 结果。
- 任何 HARD 或 COMPLIANCE 阻断必须立即重算 `killSwitch`、`nodes`、`agentResults`、`dagEvents`、`finalContext` 和 `orchestratorPlan`，并截断后续正向交易节点，只允许进入 `final_writer`。
- 低频中长线模式下，Level-2、盘口深度等高频微观结构缺失只能在 Trade Micro 显示 WARN 或执行可达性降级，不得重复压低 DVG/QIAM 权限。
- 新增或修改规则必须覆盖旧 run 兼容、preflight block、retry 映射、审计、SignalOps、Final Writer、Execution 和前端 `/guardrail-hub`、`/dvg-gate`、`/risk`、`/trade-micro` 路由。
- 侧边主导航只展示 `/guardrail-hub` 合并入口；旧 DVG、Risk、Trade Micro 路径只能在 Guardrail Hub 页面内作为 tab/深链表达。
- Token、辩论页和 DAG 页必须把 `guardrail_hub` 视为 `RULE_ENGINE`；LLM 输出不得覆盖 DVG/Risk/Trade Micro 的规则结果。

## 5. 当前开发重心

当前未完成开发不再从旧 backlog 计数，只按 `docs/NEXT_DEVELOPMENT_PLAN.md` 执行：3 个实现阶段，加 1 个设计-only 阶段。

| 阶段 | 状态口径 | 当前目标 |
| --- | --- | --- |
| Phase 1 | 实现阶段 | 研究可信度、真实持仓闭环、Backtest 严谨性 |
| Phase 2 | 实现阶段 | 产品 E2E、Research Lab 成熟度 UI |
| Phase 3 | 实现阶段 | 本地 SQLite worker / queue、存储权威边界、监控告警 |
| Phase 4 | 设计-only | 实盘架构设计文档，不进入本轮实现 |

主链路：

```text
Portfolio / market config / user input
-> New Task -> Agent DAG -> Guardrail Hub
-> Quant Core -> Execution boundaries -> Final Writer
-> SignalOps simulation -> Backtest / Research Lab
-> Case / Knowledge / Evaluation
```

开发时优先证明闭环证据：

- portfolio snapshot 必须真实进入 analysis run。
- run、SignalOps、backtest、Research iteration、case、knowledge item、evaluation、knowledge version 应有可追踪 ID。
- mock、fallback、弱样本或 MFE/MAE-only evidence 只能作为 `supporting_only`，并保持 `strong_conclusion_allowed=false`。
- UI 的 `PASS` / `WARN` / `WAIT` 必须能对应后端 `steps[]`、`warnings[]`、quality warnings 或 workflow blocking reason。

每个阶段开工前先运行：

```powershell
npm.cmd run audit:baseline
git status --short
```

如果当前运行库因历史数据缺失出现 `closure_gaps`，不要为了让计数好看直接污染运行库。先运行隔离验证：

```powershell
npm.cmd run smoke:closed-loop-participation
```

## 6. 高风险规则

### 6.1 API、schema 和类型

修改 API 前先读对应的：

- `backend/app/api/routes_*.py`
- `backend/app/models/*.py`
- `backend/app/core/*.py`
- `backend/tests/test_*.py`
- `frontend/src/api/*.ts`

API 响应字段变化必须同步 Pydantic model、前端 TypeScript 类型、页面空值处理、后端测试和必要的 `docs/API_CONTRACT.md`。

### 6.2 Auth、session、cookie 和权限

修改 auth、session、cookie、middleware 或 write-auth 时，必须检查：

- cookie name 是否一致
- sameSite / secure / domain / path 是否符合环境
- 服务端和客户端是否读取同一 token 来源
- session 持久化测试是否新增或更新

生产或 strict 模式下，写入 `/api` 请求受 write-auth middleware 保护。高风险写入还应检查 operator role、审计日志和前端禁用原因。

### 6.3 Secret 和外部调用

不要把 key/token/secret 写入日志、audit notes、文档、截图或浏览器可见状态。运行时密钥应通过 secret vault 和 `secret_refs` 管理。

涉及 LLM 或行情源 `base_url` 时，要检查 allowlist、strict mode、egress confirmation、last call、last error 和 READY 语义。字段完整只能代表 `CONFIGURED`；`READY` 应尽量代表真实 live call 或真实上游可用。

### 6.4 数据库和迁移

生产迁移不要直接执行。开发时如需 schema 变化：

- 生成 migration。
- 补 `backend/tests/test_db_migrations.py` 或相关迁移测试。
- 说明新增表、字段、默认值和回滚影响。
- 不要删除本地运行历史，除非用户明确要求。

相关脚本：

```powershell
.\scripts\db-backup.ps1
.\scripts\db-restore.ps1
```

### 6.5 Supabase / 外部 Postgres 接入

涉及 Supabase Database、Auth、Storage、Realtime、Edge Functions、Vectors、Cron、Queues、Supabase CLI、MCP、RLS、Data API、schema 或 migration 时，先核对 Supabase 当前 changelog 和官方文档，再动代码或文档。Supabase CLI 命令结构会变化，先运行 `supabase --help`、`supabase <group> --help` 或查官方 CLI reference，不凭记忆猜命令。

当前 `super` 不默认依赖 Supabase；如后续接入，按以下边界执行：

- 不把 `storage/tianyuan_quant.db`、Research Lab、Backtest、SignalOps、Case / Knowledge / Evaluation 的权威存储静默迁移到 Supabase。
- 不在前端暴露 `service_role`、secret key、数据库连接串、project token 或带写权限的私密凭据；浏览器侧只能使用 publishable / anon 级配置，并且必须受 RLS 和最小 grants 保护。
- 暴露到 Supabase Data API 的 schema、table、view 或 function 必须明确 grants，并对表/视图启用 RLS；RLS 控制行级访问，grants 控制角色是否能访问对象，两者不能互相替代。
- `security definer` function 不放在 exposed schema；Postgres 15+ 的 view 如需走调用者权限，使用 `security_invoker` 语义；旧版本或私有逻辑优先放未暴露 schema。
- Auth / RLS 授权不能依赖用户可编辑的 `user_metadata`；需要权限声明时用服务端可信 app metadata、独立授权表或后端 operator context。
- Storage upsert、文件替换和对象读取必须分别检查 INSERT / SELECT / UPDATE 策略，不用“上传能成功”推断替换也能成功。
- schema 变更先用隔离环境或本地 Supabase project 验证 SQL、RLS、grants、advisor 和类型生成；准备提交时才生成 migration，且不得直接执行生产迁移。
- Supabase 连接健康只作为外部依赖状态进入 Backend Status / Data Health；没有真实测试查询、advisor 或 RLS 验证时，不能把状态写成 READY。

可参考的官方入口：Supabase changelog、CLI reference、Securing your API、Product Security。文档更新时保留这些入口，不复制过时命令 transcript。

### 6.6 Web 数据可视化

涉及 Dashboard、股市全局、Quant Core、Backtest、Research Lab、Data Health、Backend Status 或任何图表/报表时，先明确分析任务和数据形状，再选最简单可信的视图。当前标准图表优先复用现有 React + Recharts / SVG / DOM 模式；只有在确有规模、拾取、地图、网络或 GPU 需求时才引入 Canvas、WebGL、地图或复杂动画。

开发规则：

- 当前重构样图基线是 `frontend/src/components/common/Material.tsx`、`frontend/src/index.css`、`Sidebar.tsx` 和 `TopBar.tsx` 所定义的浅色机构级壳层；不要恢复暗色驾驶舱、宽侧栏叙述式导航、渐变大背景或大圆角卡片堆叠。
- 页面 KPI、表格、证据账本、来源新鲜度、因子贡献、热力矩阵和内联趋势优先复用 `MetricTile`、`TableShell`、`EvidenceLedger`、`SourceFreshnessPanel`、`FactorBarStack`、`MatrixHeatmap` 和 `InlineSparkline`。
- 新项目或新版本新增模块时，不能只补前端入口；必须同步完成后端 API / model / service / storage / permission、部署配置、健康检查、文档和验收测试，细则见 `docs/FRONTEND_REDESIGN_GUIDE.md`。
- 大范围前端改动必须按 `1440x1000`、`1280x900`、`768x1024`、`390x844` 复核响应式表现，并记录未复核风险；长表只能在明确容器内横向滚动。
- Figma 交接以 `docs/FRONTEND_REDESIGN_GUIDE.md` 为准；图表区域的 `Rectangle` 语义应实现为 `KLineCurve`、`Sparkline` 或 `VolumeBar`，不能硬编码成普通矩形业务组件。
- 图表标题应表达洞察，坐标、单位、时间范围、数据来源、freshness、fallback/mock、样本外/benchmark 缺口要可见。
- 关键数值、异常、边界和结论必须在图表旁直接可读，不能只靠 hover、tooltip、颜色或动态图形解释。
- 移动端是同级目标；窄屏下优先保留结论、主指标、过滤器和复核入口，长表或复杂图表可折叠但不能丢失证据边界。
- 颜色必须有明确角色：中性上下文、主强调、风险/告警、选中/聚焦；红绿涨跌语义要配合文本、图标或正负号，不能只靠颜色。
- 对 live/stale/offline/partial 数据展示 stale-but-visible 状态，保留 last updated、来源、重试或降级原因。
- 图标按钮要有可访问名称，交互控件要有可见焦点，禁用操作要展示 disabled reason；加载、空态、错误态和重试入口不能缺失。
- 新增图表库、虚拟列表、Canvas/WebGL、地图或 3D 依赖前必须说明数据规模、包体/许可证影响和现有组件不足的理由。
- 上线或新增模块必须说明 feature flag / redirect fallback、环境变量、health/readiness、日志脱敏、外部依赖降级和回滚路径。
- 避免无证据含义的背景图、装饰渐变、粒子、3D、动效或大面积单一色系；动效必须有静态或 reduced-motion 兜底。
- 新增图表字段时同步前端类型、client unknown-first guard、空值处理和 `smoke:frontend` 静态契约；重要页面还要补 browser smoke 或 Playwright DOM 断言。
- 导出、截图或报告类图表应保持源数据、过滤条件和生成时间可追踪，避免只交付不可复核图片。

### 6.7 隔离破坏性验收

大范围 UI / API / 验收脚本改动完成后，使用隔离 chaos 入口：

```powershell
npm.cmd run chaos:isolated
```

该命令会构建前端、对所有 manifest 路由做并发压力访问、运行后端破坏性边界测试，并默认执行 strict-auth browser matrix。它必须使用 `.tmp/chaos-*`、测试临时库和隔离端口，不得修改 `storage/tianyuan_quant.db` 或真实运行历史。若只做本地故障定位，可直接运行 `.\scripts\chaos-validation.ps1 -SkipStrictAuthMatrix`，但不能作为最终验收口径。

## 7. 模块专项约定

| 模块 | 必守规则 |
| --- | --- |
| SignalOps | 始终保持 `simulation_only=true`、`is_real_trade=false`、`SIM_*`；A 股交易时段、T+1、涨跌停、100 股整数手、手续费和印花税规则不能被绕过 |
| SignalOps 日K决策树 | 涉及 lifecycle、branch、review、tuning、knowledge candidate 或 `/signalops` 决策树 UI 时，先读 `docs/SIGNALOPS_DECISION_TREE_GUIDE.md` |
| Backtest | canonical namespace 是 `/api/research/backtest/*`；可见工作台是 `/research-lab/backtest`；默认按稳定 `parameters.backtest_fingerprint` 复用 completed run |
| Research Lab | closure 依赖 iteration、run、backtest、evidence、case、knowledge、evaluation 契约；MFE/MAE evidence 和弱 backtest 仍是 `supporting_only` |
| Quant Core | `quant_core` 是活跃融合节点；写入 `run.quantCore` 和 `run.mfeMaeResearch`，legacy 字段只做兼容回填 |
| MFE/MAE Path Research | 只作为研究证据层；nowcast 不参与 verdict acceptance、Brier、PR-AUC 或交易门禁升级 |
| QIAM | 最多做一档校准，不得绕过 Guardrail Hub、Execution 或技术面冲突；低频模式下不得把高频微观结构缺失重复计为 DVG/QIAM 惩罚 |
| Frontend | 新增或修改页面先看 `frontend/src/App.tsx`、`frontend/src/routeManifest.json`、当前组件结构和 `docs/FRONTEND_REDESIGN_GUIDE.md`；所有可空字段处理 `null` / `undefined`，并完成响应式、可访问性和 PR DoD 检查 |
| Plugins | 保持只读 plan 或 dry-run 边界；artifact 不允许直接执行；上传、扫描、保留和清理必须有审计 |
| Observability | readiness、metrics、local alert、structured ops log 不得输出明文 secret 或本地敏感路径 |
| Supabase / 外部 Postgres | 默认未接入；任何接入都必须先验证官方文档、RLS、grants、secret boundary、migration 和回滚 |
| 数据可视化 | 图表必须证据导向、移动端可读、关键值可见，并同步类型 guard、空态和 smoke/browser 验证 |

不要把 `dvg_gate`、`risk_firewall`、`trade_micro`、`atrade`、`market_regime`、`technical_kline_analyst`、`market_technical_analyst`、`bottom_research`、`quant_engine`、`qiam` 或 `scenario_engine` 重新作为活跃 DAG 节点添加。

## 8. 模块修改矩阵

| 修改目标 | 重点文件 | 最小检查 |
| --- | --- | --- |
| Startup / launcher | `start-dev.ps1`、`stop-dev.ps1`、`backend/app/core/startup_status.py`、`frontend/src/store/useBackendStore.ts` | `/api/startup/status`、`START_DEV.md` 同步、必要时 live launch |
| Analysis / Live Run | `routes_analysis.py`、`analysis_job_store.py`、`LiveRunConsole.tsx` | `test_analysis_workflow.py`、`test_analysis_job_reconciliation.py` |
| Agent DAG / LLM | `agent_framework.py`、`agent_executor.py`、`llm_runner.py`、`routes_agents.py` | `test_agent_runtime.py`、`test_agent_executor.py` |
| Guardrail Hub | `modules/guardrail_hub.py`、`dvg_evidence_gate.py`、`risk_firewall.py`、`atrade.py`、`agent_framework.py`、`agent_executor.py`、`routes_analysis.py`、`GuardrailHubPage.tsx` | `test_guardrail_hub.py`、`test_agent_runtime.py`、`test_agent_executor.py`、`test_dvg_gate.py`、`test_risk_agent.py`、`test_kill_switch.py`、前端 `typecheck/lint` |
| Quant Core | `modules/quant_core.py`、`market_technical_analyst.py`、`bottom_research.py`、`qiam.py`、`scenario_engine.py`、`QuantCorePage.tsx` | `test_agent_runtime.py`、`test_agent_executor.py`、`test_analysis_workflow.py` |
| Config governance | `config_store.py`、`routes_config.py`、`ConfigVersionsPage.tsx` | `test_config_routes.py`、`test_http_auth.py` |
| SignalOps | `auto_paper_trading.py`、`routes_auto_paper_trading.py`、`SignalOpsPage.tsx` | `test_auto_paper_trading.py`、`test_auto_paper_routes.py`、`test_signalops.py` |
| Backtest | `backtest_store.py`、`routes_backtest.py`、`BacktestPage.tsx` | `test_backtest_store.py`、`test_backtest_signalops_sample.py` |
| Research Lab | `research_store.py`、`routes_research.py`、`ResearchLabPage.tsx` | `test_research_store.py`、`test_research_verdict_store.py` |
| Case / Knowledge / Evaluation | `routes_case_library.py`、`routes_evaluation.py`、stores under `core/` | `test_case_library.py`、`test_evaluation.py` |
| Market Data / Data Health | `market_data_runner.py`、adapter stores、Data/Settings pages | `test_market_data_runner.py`、adapter tests |
| Plugins | `plugin_store.py`、`routes_plugins.py`、`PluginRegistryPage.tsx` | `test_plugin_runtime.py`、`test_plugin_store.py` |
| Observability / Deploy | `routes_health.py`、middleware、`docker-compose.prod.yml` | `test_observability_routes.py`、`test_db_migrations.py` |

## 9. 推荐开发流程

1. 先读相关模块、测试、前端调用方和最近 `docs/DEVELOPMENT_LOG.md`。
2. 明确改动属于 API、UI、存储、权限、模拟交易、研究闭环、启动运维还是文档。
3. 做最小高置信度修改。
4. 同步类型、错误处理、空状态、权限禁用和文档。
5. 跑聚焦测试，再跑 lint/build 或完整后端测试。
6. 如果是可见页面或 launcher 流程，做 browser/live smoke。
7. 最终说明里写清楚改了什么、为什么改、跑了哪些检查和剩余风险。

## 10. 常见坑

- 不要恢复或使用 root `src/` 作为活跃前端。
- 不要只改后端 schema 不改前端类型。
- 不要只在后端新增请求字段而遗漏 `frontend/src/api/*Client.ts` 的 payload 类型和页面开关。
- 不要把 `/backtest` 当成当前主工作台；当前主路径是 `/research-lab/backtest`。
- 不要把 MFE/MAE supporting-only evidence 升级为强 verdict 或交易 permission。
- 不要把 SignalOps 的 `SIM_*` 动作写成真实交易。
- 不要在 audit、日志、文档或测试快照中输出明文 key。
- 不要用脱敏 config snapshot 直接恢复 secret。
- 不要删除 `.logs`、`storage`、`backend/app/storage`、数据库或运行历史，除非用户明确要求。
- 不要用过宽 try/catch 吞掉真实失败原因。
- 不要在没有解释的情况下更新测试快照。
