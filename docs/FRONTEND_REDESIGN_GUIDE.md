# 前端重构开发指南与验收标准

更新日期：2026-06-07

本文记录本次“量化系统前端页面重新设计”的开发基线、页面覆盖、实现规则和验收标准。后续任何前端 UI 改动都必须先对照本文，再同步 `docs/DEVELOPMENT_GUIDE.md`、`docs/TESTING_GUIDE.md` 和必要的 smoke guard。

## 1. 设计目标

本次重构目标不是单纯换皮，而是把所有页面统一到科技金融终端风格：

- 信息密度高，但层级清晰。
- 白色 surface、浅灰背景、蓝色主操作、青绿色数据强调。
- 顶部命令栏承载 run、市场、状态、安全边界和模拟交易标识。
- 左侧窄图标轨承载全局导航，不恢复宽侧栏说明式导航。
- 页面内部以 KPI、趋势图、矩阵、表格、证据链、状态队列和审计明细为主。
- 所有真实交易边界必须持续显示 `simulationOnly=true` / `isRealTrade=false` 或等价锁定状态。

当前 Figma 设计稿：

```text
Private design reference removed from the public release. / 公开版本已移除私人设计稿链接。
```

Figma 文件包含 1 个设计系统 frame 和 35 个页面设计稿 frame。图表线段已按语义命名为 `KLineCurve / 趋势曲线段`、`Sparkline / 指标趋势线段`、`VolumeBar / 成交量柱`，实现时不得把这些误解成普通 Rectangle 业务组件。

### 1.1 Figma 交接规范

设计稿交接必须记录：

- Figma 文件链接、设计系统 frame、页面 frame 覆盖数和未覆盖页面说明。
- 每个新增页面对应的 route、所属导航组、主数据区域和关键状态。
- 图层语义映射：Figma 内普通 `Rectangle` 如果位于图表区域，实际实现应按 `KLineCurve`、`Sparkline` 或 `VolumeBar` 处理，不得作为业务矩形组件硬编码。
- 截图或导出稿必须标明 viewport、生成时间和数据模式；不能把含有 secret、真实交易凭据、真实账户标识或个人敏感信息的截图提交到仓库。
- 如果 Figma MCP、导出或截图流程被限流，应在交付说明中记录已人工复核的 frame 和未复核风险。

## 2. 页面覆盖范围

页面覆盖以 `frontend/src/routeManifest.json` 为准。

### 2.1 主导航页面

工作台：

- `/global-market`：股市全局
- `/`：分析总览
- `/new-task`：新建任务
- `/portfolio`：真实持仓
- `/research-lab`：研究实验室入口
- `/run-compare`：运行对比
- `/live-run`：实时运行
- `/dag`：Agent 流程图
- `/debate`：Agent 辩论与 Token

护栏链：

- `/permission`：权限矩阵
- `/data-reliability`：数据可靠性引擎
- `/guardrail-hub`：统一护栏中枢，整合 DVG 门禁、风险熔断和交易微观
- `/quant-core`：量化核心
- `/execution`：执行复核
- `/anti-conclusion`：反结论

`/dvg-gate`、`/risk`、`/trade-micro` 继续作为 Guardrail Hub 的历史深链和 tab 入口保留，记录在 `routeManifest.legacyRoutes`，但不再出现在主侧边导航中。

审计与配置：

- `/signalops`：SignalOps
- `/audit`：审计日志
- `/final`：最终输出
- `/backend`：后端状态
- `/tuning`：后端调参
- `/config-versions`：配置版本
- `/plugins`：插件 Agent
- `/settings`：系统设置

### 2.2 Research Lab 子页面

- `/research-lab/overview`
- `/research-lab/research`
- `/research-lab/evidence`
- `/research-lab/backtest`
- `/research-lab/knowledge`
- `/research-lab/cases`
- `/research-lab/evaluation`
- `/research-lab/versions`
- `/research-lab/traces`

### 2.3 Legacy redirect

以下入口不是独立页面 UI，不单独重复设计；它们必须跳转到已覆盖的目标页面，并在设计/实现说明中保留兼容关系：

- `/research-loops` -> `/research-lab/research`
- `/knowledge` -> `/research-lab/knowledge`
- `/case-library` -> `/research-lab/cases`
- `/evaluation` -> `/research-lab/evaluation`
- `/knowledge-versions` -> `/research-lab/versions`
- `/data-compression` -> `/research-lab/evidence`
- `/backtest` -> `/research-lab/backtest`
- `/market` -> `/quant-core`
- `/technical-kline` -> `/quant-core`
- `/bottom-research` -> `/quant-core`
- `/quant-engine` -> `/quant-core`
- `/scenario` -> `/quant-core`

## 3. 全局壳层标准

所有页面必须共享同一套应用壳层：

- 顶部命令栏高度约 56px。
- 左上品牌区展示“天元量化 Agent”和菜单按钮。
- 左侧图标轨宽度约 64px，图标按钮为紧凑正方形状态。
- 一级导航为 `工作台 / 护栏链 / 审计与配置`，使用蓝色下划线标识当前组。
- 二级导航为页面按钮，当前页面使用浅蓝底、蓝色文字和边框。
- 内容区从二级导航下方开始，使用浅灰背景和白色卡片。
- 页面最大内容宽度保持接近设计稿，不要恢复大幅留白的营销页布局。

禁止项：

- 不恢复暗色驾驶舱壳层。
- 不恢复宽侧栏叙述式导航。
- 不使用大面积渐变背景、装饰光斑、圆形漂浮背景。
- 不使用 16px 以上的大圆角卡片堆叠作为主视觉。
- 不把页面做成 landing page 或营销 hero。

### 3.1 响应式与截图验收矩阵

大范围 UI、壳层、导航、表格或图表改动必须按固定 viewport 复核：

| Viewport | 用途 | 必须证明 |
| --- | --- | --- |
| `1440x1000` | 主设计稿桌面基线 | 壳层、二级导航、KPI strip、主图表和表格密度接近设计稿 |
| `1280x900` | 常见笔记本 | 顶部命令栏不挤压，页面主体不出现非预期横向滚动 |
| `768x1024` | 平板/窄屏工作台 | 卡片和表格可合理堆叠，关键筛选、状态和复核入口仍可见 |
| `390x844` | 手机窄屏 | 文本不重叠，按钮文字不溢出，长表或复杂图表可横向滚动或折叠 |

验收规则：

- `body` 不得出现非预期横向滚动；长表只能在 `TableShell` 或明确的表格容器内横向滚动。
- 顶部命令栏、一级导航和二级导航在窄屏下必须可用，不能遮挡页面主体。
- 文本、状态标签、图标按钮和表格单元格不得互相覆盖；必要时换行、截断或使用容器内滚动。
- 截图验收记录应包含 viewport、页面 route、是否通过和主要风险；截图不能包含 secret 或真实账户敏感信息。

## 4. 数据呈现标准

所有页面都必须体现“专业数据终端”而不是普通管理后台。

### 4.1 KPI

KPI 应使用 `MetricTile` 或同等共享 Material 数据组件：

- 标题为 11-12px，值为 22-28px。
- 辅助信息展示较昨日、覆盖率、置信区间或运行状态。
- 可附带 sparkline，但 sparkline 语义必须是趋势线，不是装饰线。
- 正向数据默认青绿色，风险/亏损/阻断使用红色，等待/降级使用橙色。

### 4.2 图表

图表实现必须使用稳定图表组件或现有业务组件：

- K 线、价格走势、行情曲线使用 `KlineChartCard`、Recharts 或等价 chart 组件。
- Figma 中的 `KLineCurve / 趋势曲线段` 只是设计表达，实现时不得按 Rectangle 逐段硬编码。
- 迷你趋势使用 `InlineSparkline` 或等价 SVG/Chart 组件。
- 柱状数据使用 `VolumeBar` 语义，可对应 Recharts Bar 或共享图表组件。
- 热力矩阵使用 `MatrixHeatmap` 或同等数据矩阵，不要用纯色块伪装数据。
- 因子贡献/权重/置信度使用 `FactorBarStack` 或等价条形组件。

### 4.3 表格

页面表格必须统一使用：

```tsx
<TableShell>
  <table className="institution-table">
    ...
  </table>
</TableShell>
```

禁止使用旧表格工具类作为主表格入口：

- `min-w-full divide-y`
- `w-full text-sm`
- `min-w-full text-left`

表格必须保留：

- 数据源、模式、状态、置信度、新鲜度、阻断原因或审计字段。
- 空值显示为明确的 `-`、`N/A` 或业务空态，不允许布局塌陷。
- 风险/降级/阻断状态必须可见，不只依赖颜色。

### 4.4 证据链与来源

涉及决策、研究、回测、SignalOps、权限、风险和最终输出的页面必须可追溯：

- 使用 `EvidenceLedger` 或同等证据表。
- 使用 `SourceFreshnessPanel` 或等价来源新鲜度展示。
- 展示 `LIVE` / `FALLBACK` / `MIXED` / `STALE` 等数据模式。
- 展示 simulation/live 边界，不允许前端隐藏真实交易锁定状态。

### 4.5 可访问性与交互标准

可访问性不是可选项，尤其是高密度金融终端：

- 图标按钮必须有 `aria-label` 或 `title`，不能只靠图标含义。
- 键盘焦点必须可见；可点击表格行、tab、菜单、切换按钮和图表控制都要能被定位。
- 状态不能只靠颜色表达；风险、降级、阻断、等待、通过都必须有文字、标签、符号或数值。
- 表单控件必须有 label、placeholder 或上下文标题；禁用状态必须展示 disabled reason。
- 表格必须保留 `th`、列标题、数值对齐和空值占位，不能为了视觉密度破坏可读语义。
- 加载、空态、错误态和重试入口必须可见，不能让页面在 API 失败时变成空白。

### 4.6 性能与依赖预算

本轮前端重构优先复用现有 React、Tailwind、Recharts、ReactFlow、SVG 和共享 Material 组件：

- 新增图表库、虚拟列表库、Canvas、WebGL、地图或 3D 依赖前，必须说明数据规模、交互需求、包体影响、许可证和为什么现有组件不足。
- 大表优先分页、分组、虚拟化或容器滚动，不能让单页渲染阻塞首屏。
- 复杂图表计算应使用 memo、预聚合或后端摘要；首屏不能等待无关重计算。
- 动画和实时刷新必须有降频、暂停或 reduced-motion 兜底；不得影响数据复核。
- 新增依赖要同步 `package.json`、锁文件、测试命令和风险说明；不能引入只服务装饰效果的重依赖。

## 5. 页面级设计要点

每个页面必须至少包含以下区域之一组组合：

- 顶部 KPI strip。
- 主要趋势图、K 线图或因子图。
- 状态矩阵、热力矩阵或路径矩阵。
- 主要明细表。
- 证据、来源、审计或队列区域。

重点页面额外要求：

- 股市全局：跨市场指数 strip、风险雷达、行业热度矩阵、宏观情绪面板、市场宽度与来源新鲜度表。
- 新建任务：任务定义、预检结果、启动影响预估、输入证据与约束清单。
- 真实持仓：持仓与暴露矩阵、因子暴露、风险贡献、调仓候选与证据来源。
- 数据源健康：可用源、新鲜度、失败适配器、延迟、覆盖率、异常归因和字段兼容性。
- Agent 流程图：DAG、链路事件、节点详情、规则触发和证据依赖。
- 研究实验室：研究假设、回测表现、闭环进度、可复现性和下一步动作。
- 权限矩阵：角色动作矩阵、权限校验链、越权审批队列、审计证据。
- SignalOps：自动模拟生命周期、确定性证据、审查队列、边界设置、模拟记录。

## 6. 实现边界

前端重构不得改变后端权威边界：

- 不新增真实交易路径。
- 不绕过后端 role / strict auth / write middleware。
- 不在浏览器暴露 service role、secret key、数据库连接串或私密 token。
- 不把 Supabase 或其他外部存储引入为新的 authority store，除非另有后端架构文档和权限设计。
- 不改变 API schema 的含义；字段变化必须同步 Pydantic、TypeScript type、client guard、测试和 `docs/API_CONTRACT.md`。
- 不删除 legacy redirect，除非先同步 routeManifest、文档、smoke 和历史深链策略。

### 6.1 安全与隐私

前端重构、设计稿和验收材料必须保持安全边界：

- Figma、截图、mock 数据、日志、导出文件和文档不得包含 service role、secret key、数据库连接串、broker token、真实交易凭据或真实账户标识。
- 浏览器可见状态只能展示脱敏后的 token-set、mask metadata、source name、run id、job id、evidence id 或模拟交易标识。
- `simulationOnly=true`、`isRealTrade=false`、`NO_DIRECT_TRADE_ACTION`、`SIM_*` 等安全边界不得被隐藏或弱化。
- 如果页面展示外部来源、LLM、行情 endpoint 或 provider 状态，必须展示 allowlist、fallback、stale、last updated 或错误摘要，不展示明文 secret。

## 7. 新增模块部署与后端适配

后续新项目或新版本如果增加业务模块，不能只补前端入口或设计稿。新增模块必须作为一个完整产品面交付，前端、后端、部署和验收同步完成。

### 7.1 前端必须同步

- 在 Figma 或等价设计稿中补充新模块页面，并保持本文定义的壳层、导航、KPI、表格、图表和证据链风格。
- 在 `frontend/src/routeManifest.json` 增加导航或 redirect 关系。
- 在 `frontend/src/App.tsx` 增加路由，并保持 lazy loading / Suspense / ErrorBoundary 结构。
- 新增页面必须进入 `frontend/src/components/`，不能恢复 root `src/`。
- 新增 API 调用必须进入 `frontend/src/api/*Client.ts`，使用 unknown-first response guard，不允许页面内裸 `fetch`。
- 新模块页面必须接入共享 Material 数据呈现，表格使用 `TableShell` / `institution-table`。

### 7.2 后端必须同步

- 增加或适配对应 FastAPI route、Pydantic model、service/store/repository 和必要的测试 fixture。
- 若新增持久化字段或表，必须同步 SQLAlchemy model、Alembic migration、SQLite 测试路径和 `docs/DATABASE_SCHEMA.md`。
- 若新增 API 字段或状态，必须同步 `docs/API_CONTRACT.md`、前端 TypeScript 类型、client response guard 和页面空态。
- 若模块涉及写入、配置、插件、研究、回测、SignalOps、交易或权限边界，必须同步 operator role、strict auth、disabled reason、审计日志和后端权限检查。
- 若模块产生 run、job、artifact、evidence、case、knowledge 或 portfolio 关系，必须明确 canonical authority，避免前端本地推断成为事实来源。

### 7.3 部署必须同步

- 新模块必须纳入本地启动、生产镜像或 compose 配置中需要的环境变量、依赖和初始化流程。
- 新模块如果有后台 worker、warming、queue、scheduler 或外部适配器，必须纳入 startup/readiness/health 降级策略。
- 新模块如果依赖外部数据源或 LLM/market endpoint，必须同步 egress allowlist、secret redaction、strict-mode fallback 和部署文档。
- 新模块如果有静态资产、上传、导出或报告产物，必须明确存储路径、权限、清理策略和可恢复性。
- 新模块不能要求生产环境手工执行未记录脚本；部署入口必须可重复执行。
- 新增环境变量必须同步 `.env` 示例、启动文档、部署配置和 secret 边界说明；不能只在本机临时配置。
- 新增 migration、worker、queue 或 provider sidecar 时必须说明启动顺序、失败降级和回滚影响。

### 7.4 发布、灰度与回滚

新模块或大范围 UI 上线必须能解释如何撤回：

- 如果有 feature flag、导航开关、redirect fallback 或 legacy 入口，必须记录默认状态和回退目标。
- 如果改动影响 route、API、schema、权限、worker 或部署配置，必须说明灰度范围、健康检查和回滚步骤。
- 如果涉及数据库迁移，只生成并验证 migration；不得直接执行生产迁移，且必须说明数据回滚或兼容读取策略。
- 如果新增外部依赖，必须说明依赖不可用时页面如何显示 stale、fallback、partial 或 disabled reason。

### 7.5 运行观测

新增模块上线后必须可诊断：

- 页面必须展示 loading、empty、error、stale、fallback、partial、blocked 等运行状态。
- 后端必须同步 readiness、health、metrics、structured ops log 或等价可观测入口，且日志脱敏。
- 数据类模块必须展示 freshness、last updated、source、coverage、latency 或失败适配器。
- 写入类模块必须展示权限角色、disabled reason、审计 ID、job/run/evidence ID 或失败原因。

### 7.6 新模块验收

新增模块完成时至少通过：

```powershell
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run build
npm.cmd run smoke:frontend
npm.cmd run smoke:frontend:responsive
```

如果新增或修改后端 API、存储、权限、worker、启动流程或部署配置，还必须补充并通过对应后端测试；大范围模块上线使用：

```powershell
npm.cmd run validate:premerge
```

验收报告必须说明：

- 新增模块的前端路由和设计稿位置。
- 后端 API / service / storage / permission 适配点。
- 部署新增环境变量、worker、外部依赖或降级策略。
- 已执行的验证命令和未覆盖风险。

## 8. 开发流程

执行前端重构时按以下顺序：

1. 先核对 Figma 设计稿和本文页面覆盖清单。
2. 修改共享壳层：`Sidebar.tsx`、`TopBar.tsx`、`AppShell.tsx`、`index.css`。
3. 修改共享数据组件：`frontend/src/components/common/Material.tsx`。
4. 逐页对齐页面结构，优先保留现有 API 和状态逻辑。
5. 所有表格切到 `TableShell` / `institution-table`。
6. 所有图表保留业务语义，K 线和趋势图用 chart 组件实现，不按 Figma Rectangle 硬编码。
7. 补充或更新 `smoke:frontend` 静态契约。
8. 跑完整前端验收命令。
9. 对照 PR Definition of Done 补齐设计稿、后端适配、部署、观测、安全和风险说明。

## 9. 验收标准

### 9.1 视觉验收

必须满足：

- 所有主导航页面和 Research Lab 子页风格一致。
- 顶部命令栏、一级导航、二级导航和左图标轨保持一致。
- 页面卡片半径、边框、间距、表头、状态色统一。
- 没有暗色驾驶舱、渐变大背景、宽侧栏、营销 hero 回归。
- 文本在 1440px、1280px 和移动宽度下不重叠、不溢出按钮。
- 固定复核 `1440x1000`、`1280x900`、`768x1024`、`390x844` 四个 viewport。
- 状态不能只靠颜色表达，必须有文字或标签。

### 9.2 页面覆盖验收

必须覆盖：

- `routeManifest.navGroups` 内所有页面。
- `routeManifest.researchRoutes` 内所有 Research Lab 页面。
- `routeManifest.redirects` 的目标页面必须有设计和实现；redirect 来源不需要重复 UI，但必须继续可访问。
- `routeManifest.legacyRoutes` 内的历史深链必须继续可访问，但不要求在主导航中重复出现。

### 9.3 代码契约验收

必须满足：

- 每个 `*Page.tsx` / `*Console.tsx` 接入共享 Material 数据呈现，或通过 Research Lab 共享组件间接接入。
- 页面表格使用 `institution-table`。
- 关键数据页面使用 `MetricTile`、`TableShell`、`EvidenceLedger`、`SourceFreshnessPanel`、`InlineSparkline`、`FactorBarStack`、`MatrixHeatmap` 中的至少一种或等价业务组件。
- `Sidebar.tsx` 保持窄图标轨，不出现 `lg:w-72`、`collapsed` 这类宽侧栏回归；Guardrail Hub 在侧栏中只能作为一个合并入口展示，旧 `/dvg-gate`、`/risk`、`/trade-micro` 不得重新拆成三个主导航图标。
- `TopBar.tsx` 保持 `institution-command-bar`、`institution-secondary-nav`、`simulationOnly=true`、`isRealTrade=false` 等壳层契约。
- `index.css` 保留 `--institution-data-accent`、`.institution-table`、`.institution-nav-pill`、`.institution-progress-track`、`.institution-chip-data` 等 token/class。

### 9.4 命令验收

至少执行并通过：

```powershell
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run build
npm.cmd run smoke:frontend
npm.cmd run smoke:frontend:responsive
```

大范围 UI 或路由改动后执行：

```powershell
npm.cmd run validate:premerge
```

如涉及 strict auth、Research Lab、SignalOps、Portfolio、Backtest、Plugin 或 Settings 写入边界，按 `docs/TESTING_GUIDE.md` 增加对应 browser smoke。

`smoke:frontend:responsive` 会启动已构建的 `frontend/dist`，遍历 `routeManifest` 路由、legacy redirect 和 `legacyRoutes`，在 `1440x1000`、`1280x900`、`768x1024`、`390x844` 四个 viewport 检查壳层可见、React root 非空、body 无非预期横向滚动、表格在 `TableShell` 内滚动、基础按钮/标签不溢出。若只做本地定位，可以用 `FRONTEND_RESPONSIVE_ROUTES=/global-market,/portfolio` 或 `FRONTEND_RESPONSIVE_ROUTE_LIMIT=5` 缩小范围；最终验收不能缩小范围。

### 9.5 PR Definition of Done

前端重构或新增模块 PR 必须逐项说明：

- 设计稿覆盖：Figma frame、route、导航组、未覆盖页面或人工复核风险。
- 前端实现：壳层、导航、KPI、图表、表格、证据链、空态/错误态和响应式矩阵。
- 后端适配：API、model、service/store、storage、permission、audit、client guard 和类型同步情况。
- 部署适配：环境变量、worker、provider、health/readiness、feature flag、fallback 和回滚路径。
- 安全隐私：secret redaction、simulation/live 边界、真实交易禁用、日志/截图脱敏。
- 验收命令：实际运行的 typecheck、lint、build、smoke、backend tests 或 browser smoke。
- 剩余风险：未跑命令、未复核 viewport、外部依赖不可用或已知兼容限制。

## 10. Smoke guard 要求

`scripts/smoke-frontend-routes.ps1` 必须继续守住以下弱链：

- 所有 manifest 路由、legacy redirect 和 `legacyRoutes` 返回 React root。
- 所有页面 surface 有共享 Material 数据呈现证据。
- 所有页面表格使用 `institution-table`。
- 禁止旧暗色壳层、渐变壳层、宽侧栏和旧表格工具类回归。
- 保留关键页面的数据组件使用证据，例如 Quant Core、Backend Status、Portfolio、SignalOps、Research Lab。

如果新增页面或重命名路由，必须同步：

- `frontend/src/routeManifest.json`
- `frontend/src/App.tsx`
- Figma 设计稿或本文页面覆盖说明
- `scripts/smoke-frontend-routes.ps1`
- `docs/FRONTEND_REDESIGN_GUIDE.md`
- `docs/TESTING_GUIDE.md` 中的视觉/响应式验收入口

## 11. 最终交付标准

一次前端重构任务只有在以下条件都满足时才算完成：

- Figma 或等价设计稿覆盖所有独立页面。
- 本地实现与设计稿壳层、导航、数据呈现和状态语义一致。
- 所有 routeManifest 路由和 redirect 可访问。
- 新增模块完成前端、后端、权限、部署和文档同步适配。
- 四个固定 viewport 的响应式结论已记录，或说明未复核风险。
- PR Definition of Done 已覆盖设计、代码、部署、观测、安全和验收命令。
- 前端 typecheck、lint、build、smoke 全通过。
- 文档同步记录设计边界、验收命令和仍存在的风险。
- 没有引入真实交易、权限绕过、secret 暴露、API authority 漂移或未记录的 schema 变化。
