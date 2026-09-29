# 数据存储设计文档

## 存储架构

```
super/
├── storage/
│   ├── tianyuan_quant.db          # 本地 SQLite 主数据库
│   └── super_trader.db            # 历史/兼容本地数据库
└── backend/
    └── app/
        ├── storage/
        │   ├── agent_runtime.json         # runtime 配置骨架，不保存明文密钥
        │   ├── agent_runtime.secrets.json # 本地 secret vault，必须忽略提交
        │   ├── agent_runtime.secret.key   # 本地 vault key，必须忽略提交
        │   ├── analysis_jobs.json         # analysis job 生命周期运行态
        │   ├── auto_paper_trading.json    # SignalOps 自动模拟交易运行态
        │   ├── knowledge_iterations.json  # 知识迭代运行态
        │   └── runs/                      # 本地 analysis run 历史
        └── db/
            ├── __init__.py
            ├── session.py       # 数据库连接与表创建
            ├── models.py        # 核心 ORM 模型
            ├── models_backtest.py
            ├── models_case_library.py
            ├── models_research.py
            └── repositories.py  # 数据访问层
```

生产 Docker 路径：

```text
deploy/db/               # 生产 SQLite volume
deploy/backend-storage/  # 生产 backend runtime storage volume
deploy/backups/db/       # 数据库备份目录
```

## 技术选型
- **数据库**：SQLite（via aiosqlite）
- **ORM**：SQLAlchemy 2.0（async mode）
- **迁移工具**：Alembic baseline + startup migration runner
- **Secret 存储**：`secret_store.py` 加密 vault；主 runtime JSON 只保留 `secret_refs`

## 数据写入策略

每次 analysis run 创建、启动或完成后，后端会同时维护 SQLite 业务表和本地 JSON artifact。SQLite 是结构化查询和闭环验收的优先来源；JSON 主要用于运行快照、兼容导入、调试和可导出 artifact。

分析运行完成后，通常会持久化以下数据：

1. **analysis_runs** — 分析任务记录
2. **agent_results** — 所有 Agent 执行结果
3. **audit_logs** — 审计日志
4. **data_snapshots** — 5 个数据源状态快照（market/finance/announcement/moneyflow/chip）
5. **dvg_results** — DVG 门禁结果
6. **kill_switch_events** — Kill Switch 触发记录
7. **state_snapshots** — 完整状态快照
8. **signalops_records** — SignalOps 信号记录
9. **paper_trade_records** — 纸面交易记录
10. **system_versions** — 系统版本信息

数据闭环相关的一等表还包括：

- **portfolio_snapshots / holding_positions** — 真实持仓快照和导入结果。
- **analysis_jobs** — analysis job 生命周期、重试、stale recovery 和 worker 镜像状态。
- **signals / paper_portfolios / paper_orders / paper_positions** — SignalOps 生命周期和模拟仓记录。
- **backtest_runs / backtest_trades / backtest_signals** — 回测报告、交易和信号来源。
- **research_loops / research_iterations / research_evidence_links / research_feedback_events** — Research Lab 研究闭环。
- **case_library / knowledge_patches / evaluation_runs / knowledge_versions** — 案例、知识补丁、评估和知识版本治理。

## 存储降级

如果数据库写入失败：
- run JSON artifact 已成功原子保存时，重启可从文件恢复；仅有内存对象不能视为 durable。
- 部分 SQL materialization 的失败会记录运维日志并保留 JSON 降级路径，因此 API 返回 run 不证明所有业务表均写入成功。
- JSON 写入失败不应继续报告持久化成功；参数扫描已明确在落盘失败时抛错且不调度。
- SQL 镜像与文件快照的完整性需分别检查；不要用某个空表或 API 200 单独代替闭环验收。

## 数据读取

当前读取路径是混合模式：

- analysis run 详情优先来自内存 `runs_store` 和 `backend/app/storage/runs/*.json`，同时在 SQLite 中保留结构化记录和 report asset。
- job 生命周期以 `analysis_jobs.json` + SQLite `analysis_jobs` 镜像并存，查询和 stale reconciliation 会尝试对账。
- portfolio、backtest 报告、research、case、knowledge version、evaluation 以 SQLite 为主；知识候选迭代与参数扫描任务仍分别以 `knowledge_iterations.json`、`backtest_parameter_scan_jobs.json` 为权威来源，不能用 SQL 空表推断这些模块没有历史。
- auto paper trading config 仍在 `backend/app/storage/auto_paper_trading.json`，使用 atomic replace，并在损坏 JSON 时返回可解释 warning。

新增闭环能力时，应优先把可查询状态写入 SQLite；JSON 只作为运行快照、兼容导入或可导出 artifact。不要让新能力只存在于内存对象中。

## 存储权威边界

后续平台化前必须先保持下面的权威边界，避免 SQLite + JSON 并存时产生状态漂移：

| 状态类别 | 当前权威来源 | JSON 角色 | 后续方向 |
| --- | --- | --- | --- |
| Portfolio / holdings | SQLite `portfolio_snapshots`、`holding_positions` | 无权威角色 | 继续作为真实持仓闭环验收入口 |
| Backtest | SQLite `backtest_runs`、`backtest_trades`、`backtest_signals` | 可导出 report artifact | 继续以 SQLite 为主，保留稳定 fingerprint 去重 |
| Parameter scan jobs | `backtest_parameter_scan_jobs.json` 与其冷历史 manifest | 当前任务权威状态 | 落盘失败不得报告 durable 或调度；活动 lease 保留 |
| Research Lab | SQLite `research_*` 表 | trace/import artifact | 继续以 SQLite 为主，保留 evidence links 和 workflow state |
| Case / Knowledge / Evaluation | SQLite case/knowledge/evaluation 表 | 兼容 artifact | 继续以 SQLite 为主，发布后回归结果可查询 |
| Knowledge iteration candidates | `knowledge_iterations.json` 与其冷历史 manifest | 当前候选审核状态 | ACTIVE 保持热存储，历史候选保留且可审核 |
| Analysis run detail | 内存 + `backend/app/storage/runs/*.json`，SQLite 保留结构化镜像 | 当前主要 run artifact | 平台化阶段再设计更强 run snapshot 权威边界 |
| Analysis jobs | `analysis_jobs.json` + SQLite `analysis_jobs` 镜像 | 运行态兼容和恢复线索 | 引入 worker/queue 前保持对账，后续迁向 SQLite job/attempt 权威 |
| Auto paper runtime config | `backend/app/storage/auto_paper_trading.json` | 当前权威运行配置 | 后续若迁移需保留 atomic write、损坏 JSON warning 和审计 |
| Agent runtime skeleton | `backend/app/storage/agent_runtime.json` + secret refs | 非密钥配置骨架 | secret 材料仍必须留在 vault |
| Secrets | secret vault 文件或部署 secret volume | 不得导出为普通 artifact | 不得从脱敏 snapshot 还原 secret |

`npm.cmd run audit:baseline` 会输出关键表计数、`closure_required_tables`、`closure_gaps` 和这一组存储边界摘要，作为 Phase 0 基线冻结的只读证据。闭环缺口判定覆盖 portfolio、analysis/Agent、SignalOps、Backtest、Research evidence、Case、Knowledge patch/version、Evaluation 和 analysis job 参与表。

## Analysis worker queue

- Default execution remains in-process. The SQLite worker path is active only when `ANALYSIS_EXECUTION_MODE=worker`.
- In worker mode, `POST /api/analysis/runs/{run_id}/start` writes a `QUEUED` run plus a `QUEUED` `analysis_jobs` row and does not create an in-process asyncio task.
- `analysis_jobs` is now the local queue claim surface. `claim_next_job` uses SQLite `BEGIN IMMEDIATE`, `queue_name`, `concurrency_group`, and `concurrency_limit` so two local workers cannot exceed the per-group limit.
- Worker heartbeat, cancellation, completion, failure, and stale recovery continue to update both `analysis_jobs.json` and SQLite `analysis_jobs`.
- `TIANYUAN_ANALYSIS_JOBS_FILE` can redirect the JSON job mirror for isolated worker CLI smoke. `scripts/analysis-worker.ps1` exposes this as `-JobStorageFile`; pair it with `-DatabaseFile` so worker smoke stays under `.tmp`.
- Product/E2E validation must use `.tmp` SQLite DBs. Do not write `storage/tianyuan_quant.db` for live smoke acceptance.

## Backup drill boundaries

2026-09-29 的修复、历史归档配置、实际存储 bundle 工具和跨平台恢复限制见 [审计修复与运维说明](AUDIT_REMEDIATION_2026-09-29.md)。冷热归档默认不删除历史，也不替代异机备份；在线 SQLite 快照与同时复制的 JSON 不构成跨文件一致检查点。

- `npm.cmd run smoke:db-backup-restore` covers temporary SQLite backup, restore dry-run, force restore, manifest checksum, and SQLite integrity verification.
- `npm.cmd run smoke:db-offhost-backup` covers temporary SQLite backup file plus manifest copy into a separate simulated off-host directory and verifies the copied checksum against the manifest.
- `npm.cmd run smoke:storage-offhost-restore` covers a temporary `deploy/backend-storage`-style bundle, including runtime JSON, run/plugin artifacts, ops logs, secret vault, and key file, then copies/restores it through a simulated off-host directory and verifies every file by SHA-256 manifest.
- All drills write only under `.tmp` and do not touch production `deploy/db` or `deploy/backend-storage`.
- Production still needs a real off-host destination, retention policy, schedule ownership, access controls, and recurring restore records for actual deployment volumes.

## 安全
- 数据库文件不提交到 Git（.gitignore）
- `backend/app/storage/*.json` 属于本地可变运行态，默认不提交；如需示例配置，应另建模板文件并确认不含密钥
- `agent_runtime.secrets.json` 与 `agent_runtime.secret.key` 必须留在本机或受控部署 volume，不得提交、截图或写入文档
- 不存储券商账号/密码/API Token 明文
- 不在日志中输出敏感密钥

## 备份和恢复

- 本地备份优先写入 `deploy/backups/db/`。
- 恢复目标只允许位于 `storage/` 或 `deploy/db/`，避免 `-Force` 覆盖工作区外数据库。
- 恢复前优先运行 `.\scripts\db-restore.ps1 ... -DryRun`。
