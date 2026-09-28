# 数据库 Schema 文档

## 概述
当前使用 SQLAlchemy ORM + SQLite。代码侧当前约有 51 个业务 ORM 表模型，另有 Alembic 迁移元数据表；本地 `storage/tianyuan_quant.db` 抽样显示约 52 张表。

本文上半部分保留历史核心表说明；新增开发或审查时，当前事实以 `backend/app/db/models.py`、`backend/app/db/models_backtest.py`、`backend/app/db/models_case_library.py`、`backend/app/db/models_research.py` 和 Alembic migration 为准，不再使用旧的“13 张表”口径。

## 当前表域总览

| 表域 | 主要 ORM 模型 | 权威文件 |
| --- | --- | --- |
| Analysis / Runtime | `AnalysisRunDB`, `AnalysisJobDB`, `FinalReportDB`, `AgentResultDB`, `AuditLogDB` | `backend/app/db/models.py` |
| Config / Audit | `ConfigProfileDB`, `ConfigVersionDB`, `ConfigDraftDB`, `DataSnapshotDB`, `DVGResultDB`, `KillSwitchEventDB` | `backend/app/db/models.py` |
| Portfolio | `PortfolioSnapshotDB`, `HoldingPositionDB`, `HoldingImportJobDB`, `HoldingValidationIssueDB` | `backend/app/db/models.py` |
| Data Reliability Engine | `DataHealthCheckDB`, `DataAdapterEventDB` | `backend/app/db/models.py` |
| SignalOps / Paper Trading | `SignalDB`, `SignalTransitionDB`, `SignalReviewDB`, `PaperPortfolioDB`, `PaperPositionDB`, `PaperOrderDB`, `PaperExecutionDB`, `AgentSimulationCaseDB` | `backend/app/db/models.py` |
| Plugins | `PluginRegistryDB`, `PluginAuditDB` | `backend/app/db/models.py` |
| Backtest | `BacktestRunDB`, `BacktestTradeDB`, `BacktestSignalDB` | `backend/app/db/models_backtest.py` |
| Case / Knowledge / Evaluation | `CaseLibraryDB`, `ReviewTagDB`, `ErrorLedgerEntryDB`, `KnowledgePatchDB`, `EvaluationRunDB`, `KnowledgeVersionDB` | `backend/app/db/models_case_library.py` |
| Research Lab | `ResearchLoopDB`, `ResearchIterationDB`, `ResearchEvidenceLinkDB`, `ResearchFeedbackEventDB`, `ResearchArtifactMaterializationDB`, `ResearchHypothesisDraftDB` | `backend/app/db/models_research.py` |

`DataHealthCheckDB` / `DataAdapterEventDB` 对应的物理表仍沿用 `data_health_checks` 和 `data_adapter_events`。这是为避免不必要迁移风险保留的历史表名，不代表公开产品模块仍叫 Data Health；公开入口、API 和 DAG 节点均以“数据可靠性引擎”/`data_reliability_engine` 为准。

数据闭环验收时至少检查这些表是否生成可追踪记录：`portfolio_snapshots`、`analysis_runs`、`signals`、`backtest_runs`、`research_loops` / `research_iterations`、`case_library`、`knowledge_versions`、`evaluation_runs`。

---

## 1. analysis_runs

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键，自增 |
| audit_id | TEXT(128) | 审计 ID，唯一索引 |
| run_id | TEXT(128) | 运行 ID，索引 |
| symbol | TEXT(32) | 股票代码 |
| stock_name | TEXT(64) | 股票名称 |
| task_type | TEXT(64) | 任务类型 |
| run_mode | TEXT(32) | 运行模式 |
| runtime_environment | TEXT(32) | 运行环境 |
| data_mode | TEXT(16) | 数据模式 |
| final_action | TEXT(32) | 最终动作 |
| final_report | TEXT | 最终报告 |
| success | BOOLEAN | 是否成功 |
| created_at | TEXT(64) | 创建时间 |
| updated_at | TEXT(64) | 更新时间 |

## 2. agent_results

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| audit_id | TEXT(128) | 审计 ID，索引 |
| run_id | TEXT(128) | 运行 ID，索引 |
| agent_name | TEXT(64) | Agent 名称 |
| node | TEXT(64) | 节点 ID |
| status | TEXT(16) | 状态 |
| confidence | TEXT(8) | 置信度 |
| hard_stop | BOOLEAN | 硬阻断 |
| allowed_actions | JSON | 允许动作 |
| blocked_actions | JSON | 阻断动作 |
| missing_data | JSON | 缺失数据 |
| warnings | JSON | 警告 |
| reasons | JSON | 原因列表 |
| data_json | JSON | Agent 数据 |
| elapsed_ms | INTEGER | 耗时(ms) |
| final_decision_cap | TEXT(32) | 决策上限 |
| skipped_reason | TEXT(256) | 跳过原因 |
| created_at | TEXT(64) | 创建时间 |

## 3. audit_logs

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| audit_id | TEXT(128) | 审计 ID，索引 |
| run_id | TEXT(128) | 运行 ID，索引 |
| event_type | TEXT(32) | 事件类型 |
| node | TEXT(64) | 节点 |
| message | TEXT | 事件消息 |
| status_before | TEXT(16) | 之前状态 |
| status_after | TEXT(16) | 之后状态 |
| input_hash | TEXT(64) | 输入哈希 |
| output_hash | TEXT(64) | 输出哈希 |
| payload_json | JSON | 完整数据 |
| created_at | TEXT(64) | 创建时间 |

## 4. data_snapshots

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| audit_id | TEXT(128) | 审计 ID |
| run_id | TEXT(128) | 运行 ID |
| symbol | TEXT(32) | 股票代码 |
| data_mode | TEXT(16) | 数据模式 |
| source_name | TEXT(32) | 数据源名称 |
| adapter | TEXT(32) | 适配器 |
| provider | TEXT(32) | 提供商 |
| success | BOOLEAN | 是否成功 |
| evidence_tag | TEXT(4) | 证据标签 |
| freshness_status | TEXT(16) | 时效性 |
| timestamp | TEXT(64) | 时间戳 |
| data_json | JSON | 数据 |
| error | TEXT | 错误信息 |
| created_at | TEXT(64) | 创建时间 |

## 5. dvg_results

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| audit_id | TEXT(128) | 审计 ID |
| run_id | TEXT(128) | 运行 ID |
| status | TEXT(16) | DVG 状态 |
| data_reliability | TEXT(8) | 数据可靠性 |
| confirmed_ratio | FLOAT | 确认比例 |
| inferred_ratio | FLOAT | 推断比例 |
| unknown_ratio | FLOAT | 未知比例 |
| qiam_permission | TEXT(32) | QIAM 权限 |
| scenario_permission | TEXT(32) | Scenario 权限 |
| execution_permission | TEXT(32) | Execution 权限 |
| hallucination_risk_score | INTEGER | 幻觉风险分 |
| hard_stop | BOOLEAN | 硬阻断 |
| data_json | JSON | 完整数据 |
| created_at | TEXT(64) | 创建时间 |

## 6. kill_switch_events

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| audit_id | TEXT(128) | 审计 ID |
| run_id | TEXT(128) | 运行 ID |
| active | BOOLEAN | 是否激活 |
| level | TEXT(16) | 级别 |
| trigger_node | TEXT(64) | 触发节点 |
| trigger_rule | TEXT(256) | 触发规则 |
| blocked_paths | JSON | 阻断路径 |
| allowed_paths | JSON | 允许路径 |
| final_writer_mode | TEXT(32) | Final Writer 模式 |
| payload_json | JSON | 完整数据 |
| created_at | TEXT(64) | 创建时间 |

## 7. signalops_records

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| audit_id | TEXT(128) | 审计 ID |
| run_id | TEXT(128) | 运行 ID |
| symbol | TEXT(32) | 股票代码 |
| signal_status | TEXT(32) | 信号状态 |
| risk_passed | BOOLEAN | Risk 通过 |
| dvg_passed | BOOLEAN | DVG 通过 |
| qiam_passed | BOOLEAN | QIAM 通过 |
| execution_reachable | BOOLEAN | 执行可达 |
| trigger_conditions | JSON | 触发条件 |
| invalidation_conditions | JSON | 失效条件 |
| review_fields | JSON | 复盘字段 |
| blocked_reason | TEXT(256) | 阻断原因 |

## 8. paper_trade_records

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| signal_id | INTEGER | 关联信号 ID |
| audit_id | TEXT(128) | 审计 ID |
| run_id | TEXT(128) | 运行 ID |
| symbol | TEXT(32) | 股票代码 |
| status | TEXT(32) | 纸面状态 |
| simulated_profit | FLOAT | 模拟盈亏 |
| max_drawdown | FLOAT | 最大回撤 |
| ... | ... | ... |

## 9. paper_portfolios

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| signal_id | INTEGER | 关联 SignalOps 信号 |
| audit_id | TEXT(128) | 审计 ID |
| run_id | TEXT(128) | 来源运行 ID |
| symbol | TEXT(32) | 股票代码 |
| initial_cash | FLOAT | 初始模拟资金 |
| available_cash | FLOAT | 可用模拟现金 |
| market_value | FLOAT | 模拟持仓市值 |
| risk_budget | JSON | 模拟仓风险预算 |
| created_by_agent | TEXT(64) | 创建 Agent |
| simulation_only | BOOLEAN | 必须为 true |
| is_real_trade | BOOLEAN | 必须为 false |

## 10. paper_orders

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| paper_portfolio_id | INTEGER | 关联模拟仓 |
| signal_id | INTEGER | 关联 SignalOps 信号 |
| audit_id | TEXT(128) | 审计 ID |
| agent_id | TEXT(64) | 操作 Agent |
| action | TEXT(32) | SIM_BUY / SIM_SELL / SIM_HOLD / SIM_REBALANCE / SIM_CLOSE |
| action_reason | TEXT | Agent 操作依据 |
| simulated_price | FLOAT | 模拟委托价 |
| simulated_quantity | FLOAT | 模拟数量 |
| fill_status | TEXT(32) | 模拟成交状态 |
| risk_constraints | JSON | 风险约束快照 |
| data_snapshot_hash | TEXT(128) | 数据快照 hash |

## 11. agent_simulation_cases

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| case_source | TEXT(64) | 固定为 AGENT_SIMULATION |
| operator_type | TEXT(32) | 固定为 AGENT |
| source_signal_id | INTEGER | 来源 SignalOps 信号 |
| source_paper_order_id | INTEGER | 来源模拟委托 |
| agent_id | TEXT(64) | 操作 Agent |
| audit_id | TEXT(128) | 审计 ID |
| simulation_only | BOOLEAN | 必须为 true |
| is_real_trade | BOOLEAN | 必须为 false |
| outcome | JSON | 模拟盈亏、回撤、失效条件命中情况 |
| knowledge_candidate_status | TEXT(32) | REVIEWING / APPROVED / REJECTED |

## 12-16. review_records, error_ledger_records, meta_patch_candidates, state_snapshots, system_versions

详见 [models.py](../backend/app/db/models.py)。

## 17. config_profiles

Stores the active Backend Tuning profile.

| Field | Type | Notes |
|------|------|------|
| profile_id | TEXT(64) | Primary key, normally `default` |
| version | INTEGER | Active config version |
| locked_guardrails_json | JSON | Locked guardrail layer |
| safe_runtime_config_json | JSON | Safe runtime layer |
| review_required_config_json | JSON | Review-required layer |
| sandbox_config_json | JSON | Sandbox layer |
| created_at | TEXT(64) | Created timestamp |
| updated_at | TEXT(64) | Updated timestamp |

## 18. config_versions

Stores version snapshots for Backend Tuning rollback.

| Field | Type | Notes |
|------|------|------|
| id | INTEGER | Primary key |
| profile_id | TEXT(64) | Config profile id |
| version | INTEGER | Snapshot version |
| created_at | TEXT(64) | Snapshot timestamp |
| created_by | TEXT(64) | Actor label |
| change_summary | TEXT | Human-readable change summary |
| audit_id | TEXT(128) | Audit id written with the change |
| status | TEXT(32) | `active` or `superseded` |
| rollback_available | BOOLEAN | Whether this snapshot can be selected for rollback |
| snapshot_json | JSON | Full ConfigProfile snapshot |

## 19. config_drafts

Stores pending/applied Backend Tuning review drafts.

| Field | Type | Notes |
|------|------|------|
| draft_id | TEXT(128) | Primary key |
| profile_id | TEXT(64) | Config profile id |
| status | TEXT(32) | Draft status |
| changes_json | JSON | Proposed effective changes |
| reason | TEXT | Review reason |
| policy_check_json | JSON | Policy validation result |
| audit_id | TEXT(128) | Draft creation audit id |
| created_at | TEXT(64) | Created timestamp |
| updated_at | TEXT(64) | Updated timestamp |
