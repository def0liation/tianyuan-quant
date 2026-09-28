# 外部 Worker / Queue 设计（P3 生产化工程能力）

更新日期：2026-07-02
状态：设计合同（Phase A 可开工；Phase B-D 依赖前序验收）

本文是 `docs/PRODUCT_ANALYSIS_AND_ROADMAP.md` P3 中「外部 worker/queue 设计与实现」的开发合同。目标是把当前本地 SQLite worker 能力演进为可部署、可观测、仍受控的队列平台形态，同时不破坏默认 in-process 路径和 simulation-only 边界。若本文与当前代码或 `docs/DEVELOPMENT_LOG.md` 最新条目冲突，以代码和最新已验证日志为准，并同步修正本文。

## 0. 不可回退边界

- 全程保持 `simulation_only=true`、`is_real_trade=false`、`SIM_*` 语义；队列平台化不引入任何真实下单能力。
- 默认执行路径保持现状：未设置 `ANALYSIS_EXECUTION_MODE=worker` 时 in-process 执行，不回归。
- 不执行生产迁移。新增 schema 变化只生成 migration + 测试 + 影响说明。
- 验收一律使用 `.tmp` 下临时 SQLite/Postgres，不污染 `storage/tianyuan_quant.db`。
- SQLite（或 Phase C 的 Postgres）是 jobs 的权威来源；JSON 仅为 artifact/兼容镜像，且本设计逐步缩小 JSON 职责。
- 新增写接口全部纳入现有 role/strict-auth 体系（requeue/DLQ 操作 `operator+`，破坏性清理 `admin`）。

## 1. 现状盘点（已验证，2026-07-02）

已具备（`backend/app/core/analysis_job_store.py`、`backend/app/core/analysis_worker.py`）：

- `analysis_jobs` 表：`run_id`(PK)、`job_id`、`status`、`attempt/max_attempts(默认3)`、`queue_name`、`priority`、`concurrency_group/limit(默认1)`、`worker_id`、`worker_heartbeat_at`、operator 字段、`stale_reason`、时间戳、`history_json/recovery_json/payload_json`；另有 attempts 台账表。
- Claim：`BEGIN IMMEDIATE` 事务内扫描 `status='QUEUED'`（priority DESC、queued_at ASC，LIMIT 50），按 `concurrency_group` 统计 RUNNING 数做并发上限，`UPDATE ... WHERE status='QUEUED'` CAS 抢占，写 `JOB_CLAIMED` history。
- Lease：`TIANYUAN_ANALYSIS_JOB_LEASE_SECONDS`（默认 60，clamp 5..3600），由 heartbeat 推导 `lease_expires_at/lease_status`（ACTIVE/EXPIRED/UNCLAIMED/RELEASED/UNKNOWN）。worker 心跳间隔 `ANALYSIS_WORKER_HEARTBEAT_INTERVAL_SECONDS`（默认 1s）。
- 恢复：`reconcile_stale_jobs(stale_after_seconds)` 挂在 jobs API 读路径上，把 {PENDING,QUEUED,RUNNING,CANCEL_REQUESTED} 中超时无活动的 job 置为 `STALE` 并写 `recovery` 说明。
- Worker 模式：`ANALYSIS_EXECUTION_MODE=worker` 时 start 仅入队；`npm.cmd run worker:analysis` 启动轮询 claim 循环；取消为协作式（CANCEL_REQUESTED 由心跳循环感知）。
- 写保护：`_reject_if_worker_mismatch` 拒绝非持有 worker 的完成/失败写入。
- 外部只读 sidecar：`analysis_job_external_queue_status_v1`（provider/claim/lease/DLQ/visibility/worker pool 等字段），本地模式标记 `LOCAL_JSON_SQLITE_DIAGNOSTIC`。

缺口（对照 P3 验收语义）：

1. 无 DLQ：`max_attempts` 存在但失败后不自动 requeue，也没有 DEAD_LETTER 终态与重放入口。
2. Lease 过期不回收：`lease_status=EXPIRED` 只用于展示；过期 RUNNING job 只能等 stale 超时被标 STALE，不能被其他 worker 安全重抢。
3. 无队列后端抽象：claim/complete/heartbeat 逻辑与 SQLite 连接强耦合，无法替换为跨主机 broker。
4. 跨主机能力缺失：SQLite 单文件决定了 worker 只能同主机；`concurrency_group` 限制无法跨主机成立。
5. JSON/SQLite 双写仍在，状态漂移风险由 `_json_job_is_newer_or_equal` 之类的调和逻辑兜底。

## 2. 目标与非目标

目标：

- at-least-once 执行语义 + 显式 fencing（run_id, attempt, worker_id），可解释的重复执行防护。
- lease 过期自动回收：EXPIRED → 安全 requeue（attempt+1）→ 超过 max_attempts 进 DLQ。
- QueueBackend 协议抽象：本地 SQLite 参考实现 + 可插拔外部 broker 适配器。
- 跨主机 worker 池：外部 backend 下 claim/lease/并发组约束在 broker 侧事务成立。
- DLQ 可见、可重放、可审计；Backend Status 展示队列深度、最老等待时长、DLQ 计数。

非目标：

- 不做 exactly-once 承诺（执行体为 LLM/市场数据编排，重放安全靠 run 状态 CAS 与 fencing，不靠分布式事务）。
- 不在产品内运营 broker 基础设施（Redis/SQS 的部署、监控、retention 属部署侧，沿用 sidecar readiness 汇报契约）。
- 不改变 SignalOps/Research/Backtest 的业务语义。

## 3. 架构

### 3.1 QueueBackend 协议（Phase B 落地）

新增 `backend/app/core/queue_backend.py`，定义同步协议（与现 store 一致，异步侧仍走 `asyncio.to_thread`）：

```python
class QueueBackend(Protocol):
    def enqueue(self, job: JobRecord) -> JobRecord: ...
    def claim_next(self, *, queue_name: str, worker_id: str, operator: str) -> JobRecord | None: ...
    def renew_lease(self, run_id: str, *, worker_id: str, attempt: int) -> LeaseState: ...
    def complete(self, run_id: str, *, worker_id: str, attempt: int, outcome: JobOutcome) -> JobRecord: ...
    def fail(self, run_id: str, *, worker_id: str, attempt: int, error: str, requeue: bool) -> JobRecord: ...
    def request_cancel(self, run_id: str, *, operator: str) -> JobRecord: ...
    def reclaim_expired(self, *, now: datetime) -> list[JobRecord]: ...
    def requeue_from_dead_letter(self, run_id: str, *, operator: str) -> JobRecord: ...
    def observe(self) -> QueueObservation: ...   # 深度、最老等待、DLQ 计数、active workers
```

选择由 `ANALYSIS_QUEUE_BACKEND` 决定：`local_sqlite`（默认，行为等于现状+Phase A 增强）| `postgres`（Phase C）。未设置时行为与今天完全一致。

### 3.2 后端选型决策矩阵（Phase C）

| 方案 | claim 机制 | 跨主机 | 新增运维面 | 结论 |
| --- | --- | --- | --- | --- |
| Postgres `FOR UPDATE SKIP LOCKED` | 单事务 CAS，天然支持并发组计数 | 是 | 一个 PG 实例（`TIANYUAN_QUANT_DB_URL` 已是 SQLAlchemy URL，迁移面小） | 推荐 |
| Redis Streams + consumer group | XAUTOCLAIM 视野超时 | 是 | 新增 Redis + 持久化策略 | 备选（低延迟场景） |
| SQS/云队列 | visibility timeout | 是 | 云依赖、本地开发不可用 | 仅部署侧选装，走现有 sidecar 汇报 |
| SQLite（现状） | BEGIN IMMEDIATE CAS | 否（单主机多进程） | 无 | 保留为默认参考实现 |

推荐 Postgres：与现有 SQLAlchemy/Alembic 栈同构，一套 SQL 语义同时承载 jobs 权威状态与队列操作，避免「队列在 A、真相在 B」的双源问题。

### 3.3 状态机（增量）

```
PENDING → QUEUED → RUNNING → COMPLETED
                    │  │ └→ FAILED ──(attempt < max_attempts 且可重试)→ QUEUED
                    │  │            └(attempt ≥ max_attempts 或不可重试)→ DEAD_LETTER
                    │  └→ CANCEL_REQUESTED → CANCELLED
                    └(lease EXPIRED, reclaim)→ QUEUED (attempt+1) 或 DEAD_LETTER
STALE：保留为「无 lease 信息时代的活动超时」兜底终态；DLQ 落地后 RUNNING 的超时回收优先走 reclaim 路径。
DEAD_LETTER →(operator+ 手动 requeue)→ QUEUED (attempt 归零，保留 dead_letter 历史)
```

不变式：

- 任何非持有者写入（worker_id 或 attempt 不匹配）一律拒绝并写 history（扩展现有 `_reject_if_worker_mismatch` 到 attempt 维度）。
- requeue 永远产生新 attempt 记录；attempts 台账只追加。
- DEAD_LETTER 必须携带 `dead_letter_reason`、最后一次 error、完整 attempts 链。

### 3.4 幂等与重复执行防护

- 幂等键：`run_id`（表 PK 已保证 enqueue 幂等：同 run 重复 start 返回当前 job 状态，不重复入队）。
- fencing token：`(run_id, attempt, worker_id)`。执行结果落库（run detail、final report、audit）时校验 fencing，过期 worker 的迟到写入被拒绝并记录 `LATE_WRITE_REJECTED` history 事件。
- 重放安全：executor 对同一 run 的重复执行以 run 状态 CAS 保护（RUNNING 重入直接返回），LLM/市场数据调用不产生外部副作用（simulation-only），因此 at-least-once 可接受。

## 4. 分阶段交付

### Phase A：本地 DLQ + lease 回收（先行，纯本地可测）

范围：`analysis_job_store.py` 内落地，不引入协议抽象。

- 新增列（migration，additive）：`dead_letter_reason TEXT DEFAULT ''`、`dead_lettered_at`、`requeued_from_dead_letter_at`；status 新增合法值 `DEAD_LETTER`。
- `reclaim_expired`：claim 前置步骤内执行——lease EXPIRED 的 RUNNING/CANCEL_REQUESTED job，attempt+1 后置回 QUEUED（写 `LEASE_RECLAIMED` history）；attempt ≥ max_attempts → `DEAD_LETTER`。
- `mark_failed` 增加 requeue 判定：可重试错误（transient 分类沿用前端 `retryTransientTaskStep` 的语义做后端版）自动 requeue，否则按现状 FAILED；FAILED 不自动进 DLQ（保持人工 retry 语义），只有 reclaim 与重试耗尽走 DLQ。
- API：`GET /analysis/jobs?status=DEAD_LETTER` 复用现有过滤；新增 `POST /api/analysis/jobs/{run_id}/requeue`（`operator+`，仅 DEAD_LETTER/STALE/FAILED 可重放）；`/analysis/jobs/summary` 增加 `deadLetterCount`、`queueDepth`、`oldestQueuedAgeSeconds`。
- 前端：Backend Status 队列摘要行增加 DLQ 计数与 requeue 入口（role-aware disabled reason + smoke hook，沿用现有模式）。
- 同步：Pydantic model、`frontend/src/types`、client guard、`docs/API_CONTRACT.md`。

验收：

```powershell
npm.cmd run test:backend -- backend\tests\test_analysis_jobs_store.py backend\tests\test_analysis_worker.py -q
npm.cmd run smoke:analysis-worker
npm.cmd run typecheck; npm.cmd run lint; npm.cmd run smoke:frontend
```

- 杀死 worker 进程 → lease 过期 → job 被另一 worker reclaim 且 attempt+1，attempts 台账完整。
- 连续失败至 max_attempts → DEAD_LETTER，requeue 后 attempt 归零、历史保留。
- 默认 in-process 路径与现有 62 个测试文件不回归。

### Phase B：QueueBackend 协议抽取（无行为变化）

- 抽出 3.1 协议，`LocalSqliteQueueBackend` 封装现逻辑；`analysis_job_store` 保持公共函数签名不变（内部委派），调用方零改动。
- JSON 镜像职责收缩：镜像只在读路径补历史数据，不再参与 claim/complete 决策（对齐「SQLite 权威」原则，也是 P4 状态收敛的第一步）。
- 验收：全量 `npm.cmd run test:backend`，行为对照测试（claim 顺序、并发组、fencing 拒绝语义逐条断言不变）。

### Phase C：Postgres 适配器 + 跨主机验收

- `PostgresQueueBackend`：`FOR UPDATE SKIP LOCKED` claim、事务内并发组计数、`visibility_timeout` 即 lease、DLQ 同语义。
- Alembic migration 建 `analysis_jobs`/attempts 于 Postgres；`ANALYSIS_QUEUE_BACKEND=postgres` + `TIANYUAN_QUANT_DB_URL=postgresql+asyncpg://...` 启用。
- 本地验收 harness：`docker-compose.queue-dev.yml`（仅开发），两台（两进程模拟两主机）worker 争抢同队列，断言并发组全局成立、reclaim 跨进程可见。
- `external_queue_status` 语义分层：in-app backend 时 `source=in_app_backend`、`local_queue_mode` 替换为实际 backend 名；部署侧 broker（如 SQS）仍走 sidecar 汇报，不冲突。
- 验收：Phase A 断言在 Postgres 后端全部重放通过；SQLite 默认路径回归不变。

### Phase D：观测与浏览器闭环

- Backend Status：队列深度趋势、DLQ 表、per-worker 心跳年龄、reclaim 事件流。
- strict-auth browser 场景：viewer 只读、operator requeue、admin 清理，全部走真实页面断言。
- 文档：`docs/DEPLOYMENT.md` 增加队列部署拓扑与回滚路径（backend 切回 `local_sqlite` 即回滚）。

## 5. 风险清单

- 双写漂移：Phase B 前 JSON 镜像仍在 claim 路径上，改动时必须保留 `_json_job_is_newer_or_equal` 语义并补对照测试。
- SQLite 锁竞争：reclaim 加入 claim 事务会拉长 BEGIN IMMEDIATE 持锁时间；用 LIMIT 分批 + 现有 `_is_sqlite_locked` 降级路径。
- 迟到写入：旧 worker 在 reclaim 后完成执行并回写——fencing 必须覆盖 run detail/report/audit 全部落库口，不只 job 表。
- 取消语义：reclaim 不得吞掉 CANCEL_REQUESTED（先判取消，再判过期）。
- 权限面：requeue/清理是新的写入口，必须同步后端 strict-auth、前端 role-aware 禁用、审计记录与 smoke guard。
- 历史 auth/session 教训：新端点接入时检查 token 来源与中间件顺序，补 session 持久化测试。

## 6. Definition of Done（每阶段）

- 改了什么、为什么、跑了哪些命令与结果。
- 临时库验收数据未写入当前运行库的确认。
- 默认 in-process 与 simulation-only 边界不变的显式声明。
- 剩余风险与下一阶段入口。
