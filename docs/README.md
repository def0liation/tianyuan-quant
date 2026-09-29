# 文档索引 / Documentation index

本页提供天元量化（Tianyuan Quant）的中英导航。原有专题文档保留各自语言与历史日期；文档中的计划、示例和历史测试记录不表示本次发布已实现或已验证。发生冲突时，核对当前源码、测试和相应发布验证记录。

This page provides bilingual navigation for Tianyuan Quant. Existing topic documents retain their original language and dates. Plans, examples, and historical test records do not establish implementation or validation for this release. Resolve conflicts against the current source, tests, and relevant release-validation evidence.

## 开始阅读 / Start here

| 入口 / Entry | 用途 / Purpose |
| --- | --- |
| [项目说明 / Project README](../README.md) | 功能、边界和快速开始 / Features, boundaries, and quick start |
| [贡献指南 / Contributing](../CONTRIBUTING.md) | 首装、修改约定和检查 / Setup, change conventions, and validation |
| [开发启动器 / Development launcher](../START_DEV.md) | Windows 启停和端口管理 / Windows startup, shutdown, and port handling |
| [后端说明 / Backend README](../backend/README.md) | 后端入口概览 / Backend entry-point overview |

## 源码目录 / Source map

| 路径 / Path | 内容与状态 / Contents and status |
| --- | --- |
| [backend/](../backend/) | FastAPI API、服务、模型、SQLite/Alembic 和 pytest / FastAPI APIs, services, models, SQLite/Alembic, and pytest |
| [frontend/](../frontend/) | 当前 React/TypeScript 前端；活跃源码是 `frontend/src/` / Current React/TypeScript app; active code is in `frontend/src/` |
| [scripts/](../scripts/) | 开发、测试、smoke 与运维辅助脚本；多数根 npm 入口依赖 Windows / Development, test, smoke, and operations helpers; most root npm wrappers require Windows |
| [runtime prompt 包 / Runtime prompt package](../tianyuan_quant_v10_2_multi_agent_files/tianyuan_quant_v10_2_multi_agent/) | 后端固定路径依赖，保留目录位置 / Fixed-path backend dependency; preserve its location |
| [lightweight-stock-analysis/](../lightweight-stock-analysis/) | 此发布中仅有设计和实施计划 / Design and implementation plans only in this release |

根 npm 脚本调用 `npm.cmd` / `powershell.exe`。Linux/macOS 的前端直接使用 `npm --prefix frontend ...`，后端直接使用 Python；具体命令见 [贡献指南](../CONTRIBUTING.md)。目录存在并不表示跨平台启动、真实数据或部署已经验收。

Root npm scripts invoke `npm.cmd` / `powershell.exe`. Linux/macOS frontend commands use `npm --prefix frontend ...`, and backend commands use Python directly; see [Contributing](../CONTRIBUTING.md). Directory presence does not establish validated platform startup, live data, or deployment.

## 开发与运行指南 / Development and operations guides

| 文档 / Document | 内容 / Contents |
| --- | --- |
| [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) | 主开发入口、架构边界和修改矩阵 / Main development entry, architectural boundaries, and change matrix |
| [TESTING_GUIDE.md](TESTING_GUIDE.md) | 测试和 smoke 入口；历史结果须按日期理解 / Tests and smoke entry points; historical results are dated evidence |
| [FRONTEND_REDESIGN_GUIDE.md](FRONTEND_REDESIGN_GUIDE.md) | 前端设计约定、响应式和可访问性验收 / Frontend conventions, responsive and accessibility validation |
| [QUANT_CORE_DEVELOPMENT_GUIDE.md](QUANT_CORE_DEVELOPMENT_GUIDE.md) | `quant_core`、输出字段和兼容规则 / `quant_core`, output fields, and compatibility |
| [MFE_MAE_PATH_RISK_FILTER_DEV_GUIDE.md](MFE_MAE_PATH_RISK_FILTER_DEV_GUIDE.md) | MFE/MAE 只读研究输出和风险过滤边界 / Read-only MFE/MAE research outputs and path-risk boundaries |
| [SIGNALOPS_DECISION_TREE_GUIDE.md](SIGNALOPS_DECISION_TREE_GUIDE.md) | 日K模拟决策生命周期、复盘和知识候选 / Daily-K simulation lifecycle, review, and knowledge candidates |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Docker、授权、备份和运行要求；部署不代表实盘能力 / Docker, authorization, backup, and operating requirements; deployment does not enable live trading |
| [AUDIT_REMEDIATION_2026-09-29.md](AUDIT_REMEDIATION_2026-09-29.md) | 审计修复、完整历史归档、备份边界和发布验证 / Audit fixes, complete history retention, recovery boundaries, and release checks |
| [PORTABLE_PACKAGE.md](PORTABLE_PACKAGE.md) | Windows portable zip 的制作和使用 / Building and using a Windows portable zip |

## API、数据与 Agent 契约 / API, data, and agent contracts

| 文档 / Document | 内容 / Contents |
| --- | --- |
| [API_CONTRACT.md](API_CONTRACT.md) | 请求/响应及 canonical/legacy 路由 / Requests, responses, and canonical/legacy routes |
| [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md) | 数据表域与历史核心表说明；当前模型以源码和 migration 为准 / Table domains and historical core-table notes; source models and migrations define the current schema |
| [STORAGE_DESIGN.md](STORAGE_DESIGN.md) | SQLite/文件存储、降级和权威边界 / SQLite/file storage, fallback, and authority boundaries |
| [STATE_SNAPSHOT.md](STATE_SNAPSHOT.md) | 分析状态快照、恢复和兼容 / Analysis snapshots, recovery, and compatibility |
| [AGENT_REGISTRY.md](AGENT_REGISTRY.md) | 当前 8 个活跃 Agent、运行顺序和历史 ID 映射 / Current eight active agents, run order, and historical ID mapping |

Agent 包内的 [文件清单 / Package index](../tianyuan_quant_v10_2_multi_agent_files/tianyuan_quant_v10_2_multi_agent/00_README_文件清单.md) 包含早期拆分方案与 prompt。当前活跃节点以 [agent_framework.py](../backend/app/core/agent_framework.py) 的 manifest 为准；[llm_runner.py](../backend/app/core/llm_runner.py) 会实际调用 prompt loader。不要将整个 prompt 包归档或移动，否则会改变加载行为。

The prompt package's [index](../tianyuan_quant_v10_2_multi_agent_files/tianyuan_quant_v10_2_multi_agent/00_README_文件清单.md) includes earlier decomposition designs and prompts. The manifest in [agent_framework.py](../backend/app/core/agent_framework.py) defines the active nodes, and [llm_runner.py](../backend/app/core/llm_runner.py) uses the prompt loader at runtime. Archiving or moving the whole package changes loading behavior.

## 模块规则 / Module rules

| 文档 / Document | 内容 / Contents |
| --- | --- |
| [DVG_RULES.md](DVG_RULES.md) | 数据与证据门禁 / Data and evidence gates |
| [KILL_SWITCH_RULES.md](KILL_SWITCH_RULES.md) | 熔断触发、阻断和兼容输入 / Kill-switch triggers, blocking, and legacy inputs |
| [QIAM_RULES.md](QIAM_RULES.md) | 量化适宜性校准与限制 / Quantitative suitability calibration and limits |
| [SIGNALOPS_RULES.md](SIGNALOPS_RULES.md) | 信号生命周期与模拟交易边界 / Signal lifecycle and simulation boundaries |
| [FINAL_WRITER_LIMITS.md](FINAL_WRITER_LIMITS.md) | 最终报告的上游证据和表达限制 / Upstream evidence and limits on final reporting |

## 计划、评估与历史记录 / Plans, assessments, and dated records

这些材料用于理解设计意图和演进过程。历史通过数量不是本次检查结果，路线图目标不是当前功能。保留在原路径以维持引用，不将它们当作运行依赖。

These documents explain design intent and evolution. Historical pass counts are not current check results, and roadmap targets are not current features. Keep their paths to preserve references; they are not runtime dependencies.

| 文档 / Document | 状态与用途 / Status and purpose |
| --- | --- |
| [NEXT_DEVELOPMENT_PLAN.md](NEXT_DEVELOPMENT_PLAN.md) | 分阶段开发合同 / Phased development contract |
| [EXTERNAL_WORKER_QUEUE_DESIGN.md](EXTERNAL_WORKER_QUEUE_DESIGN.md) | 外部队列演进设计；按阶段验证 / External-queue evolution design; requires phased validation |
| [PRODUCT_ANALYSIS_AND_ROADMAP.md](PRODUCT_ANALYSIS_AND_ROADMAP.md) | 产品分析和未来路线 / Product assessment and future roadmap |
| [PROJECT_DEVELOPMENT_ASSESSMENT.md](PROJECT_DEVELOPMENT_ASSESSMENT.md) | 带日期的项目评估 / Dated project assessment |
| [QUANT_SYSTEM_IMPROVEMENT_PLAN.md](QUANT_SYSTEM_IMPROVEMENT_PLAN.md) | 历史改进计划与后续记录 / Historical improvement plan and follow-ups |
| [DEVELOPMENT_LOG.md](DEVELOPMENT_LOG.md) | 变更、验证和风险的历史流水 / Historical changes, validation, and risks |
| [ENCODING_AUDIT.md](ENCODING_AUDIT.md) | 历史 UTF-8/可读性审计 / Historical UTF-8/readability audit |
| [REPO_CLEANUP_AUDIT_2026-06-04.md](REPO_CLEANUP_AUDIT_2026-06-04.md) | 2026-06-04 仓库清理记录 / Repository-cleanup record from 2026-06-04 |
| [Local-first state authority design](superpowers/specs/2026-07-15-local-first-state-authority-architecture-design.md) | 本地状态权威架构设计 / Local-state authority architecture design |
| [Dashboard command-center design](superpowers/specs/2026-07-15-dashboard-homepage-decision-command-center-design.md) | Dashboard 设计规格 / Dashboard design specification |
| [Dashboard command-center plan](superpowers/plans/2026-07-15-dashboard-homepage-decision-command-center.md) | 对应实施计划 / Corresponding implementation plan |

本地可能存在 `MODULE_INTERACTION_REVIEW_LOG.md`，这是被 Git 忽略的生成式盘点产物，不属于公开文档或发布验证依据，因此不建立公开链接。`.logs/`、数据库、缓存、secret vault、个人配置和运行状态也不属于发布源码。

A local `MODULE_INTERACTION_REVIEW_LOG.md` may exist. It is a generated, Git-ignored inventory rather than public documentation or release-validation evidence, so it has no public link here. Logs, databases, caches, secret vaults, personal configuration, and runtime state are also outside the released source.

## 轻量版设计资料 / Lightweight design material

当前发布中的轻量目录没有独立应用源码、依赖 manifest 或启动入口；以下 5 份文件是方案与计划，不能据此宣称 DefensiveScore 或真实 A/H 全市场能力已经落地。

The lightweight directory in this release has no standalone application source, dependency manifest, or launcher. The following five files are specifications and plans; they do not establish implemented DefensiveScore or live A/H-market coverage.

| 文档 / Document | 内容 / Contents |
| --- | --- |
| [Design specification](../lightweight-stock-analysis/docs/superpowers/specs/2026-08-24-lightweight-defensive-stock-analysis-design.md) | 轻量防御型股票分析设计 / Lightweight defensive-stock analysis design |
| [01 — Domain core plan](../lightweight-stock-analysis/docs/superpowers/plans/2026-08-24-lightweight-defensive-stock-analysis-01-domain-core.md) | 领域核心计划 / Domain-core plan |
| [02 — Data authority plan](../lightweight-stock-analysis/docs/superpowers/plans/2026-08-24-lightweight-defensive-stock-analysis-02-data-authority.md) | 数据权威计划 / Data-authority plan |
| [03 — Workflow/API plan](../lightweight-stock-analysis/docs/superpowers/plans/2026-08-24-lightweight-defensive-stock-analysis-03-workflow-api.md) | 工作流和 API 计划 / Workflow and API plan |
| [04 — Frontend/release plan](../lightweight-stock-analysis/docs/superpowers/plans/2026-08-24-lightweight-defensive-stock-analysis-04-frontend-release.md) | 前端和发布计划 / Frontend and release plan |
