# 轻量化防御性股票分析阶段三：持久任务、扫描复核与安全 API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 将领域评分和 READY 数据快照组合成可崩溃恢复的单机工作流，交付带 fencing 的持久后台任务、原子 Top 50 冻结、证据与人工复核、AI 草稿、clone/finalize、安全导入导出和完整 FastAPI 契约。

**Architecture:** FastAPI 只提交持久资源并返回 202；lifespan 启动唯一 embedded runner。Runner 通过 writer lease、job lease、单调 epoch 和 fencing token 做 SQL CAS，所有 checkpoint/job/target 状态改变在同事务提交。扫描只读阶段二的 READY snapshot；证据和 AI 只读冻结 EvidenceBundle；最终排名只使用阶段一的未舍入领域结果。

**Tech Stack:** Python 3.12、FastAPI、Pydantic v2、SQLAlchemy 2 async、SQLite WAL、Alembic、httpx、argon2-cffi、openpyxl、pypdf、pytest/pytest-asyncio。

**Spec:** lightweight-stock-analysis/docs/superpowers/specs/2026-08-24-lightweight-defensive-stock-analysis-design.md

## Global Constraints

- 必须先完成计划 01 和 02，并在隔离 worktree 实施。
- 不使用 `FastAPI.BackgroundTasks`；所有长任务必须先持久化、再由 runner 认领。
- 首版只允许一个可写后端进程、一个 Uvicorn worker、一个 runner 和一个正在执行的 job；数据库约束与 lease 是权威。
- 网络/AI/provider 调用不得包在数据库长事务内；返回后在短事务中重新检查 fence 和目标版本。
- runner-owned 的 checkpoint、complete、fail 和 RUNNING target transition，其 SQL `WHERE` 必须包含 owner_id、lease_epoch、fencing_token、attempt_no 和 RUNNING；影响 0 行即抛 `LeaseFencedError`，旧 runner 不做补偿写。认领前 QUEUED cancel，以及 terminal target 的 resume/reacquire 没有 RUNNING claim，必须改用当前 writer lease + expected job/target state/version + 必要 activity-slot CAS；cancel-vs-claim、resume-vs-claim 竞态只能有一个提交成功。
- Objective scan 绝不调 provider；恢复时也只读原 snapshot 和最近成功 checkpoint。
- Objective candidate 进入 REVIEW_PENDING 后不可更新/删除；FINALIZED 后 scan、review 和 ranking 不可变。
- CLONE_SCAN 不排队等待一个嵌套 DATA_SNAPSHOT job，否则单 runner 自锁；handler 直接复用阶段二 workflow。
- 模型输出只能引用 evidence_id，不得创造 URL、publisher、日期或标题。AI 失败/迟到不得关闭手工复核。
- 非 loopback 启动必须是直接 TLS 或经明确 trusted proxy 的 TLS，并对 liveness 以外的全部 API 要求 Bearer。不使用 cookie/session。
- 数据迁移只生成并测试临时库，不执行生产 migration。
- 本计划中 `.\.venv\Scripts\python.exe` 命令从 `lightweight-stock-analysis/backend` 执行；以 `git` 开头的暂存/提交命令从父仓库根目录执行。

## Frozen API Refinements

为消除规格中的前端歧义，本计划固定：

```python
class RankingScope(StrEnum):
    CORE_ENTITIES = "core_entities"
    ALL_LISTINGS = "all_listings"
```

- `CandidateQuery` 固定为 `scope、cursor、limit(1..200)、status、market、industry`；响应是按冻结 `(objective_rank, listing_id)` 游标分页的 `CandidatePage(items, next_cursor)`。切换过滤条件必须从空 cursor 重查。
- `GET /api/scans/{scan_id}/candidates?scope=core_entities|all_listings` 仅在 REVIEW_PENDING/FINALIZED 可读，其他状态返回 409 `CANDIDATES_NOT_FROZEN`；默认 `core_entities`。前者是冻结 Top 50 entity 的预筛代表，后者是本 scan 中全部 ELIGIBLE+READY listing 的客观筛选 read model；两者只有 ObjectiveScore，不产生 Top 50 外 DS2。
- `GET /api/scans/{scan_id}/rankings?scope=core_entities|all_listings` 只允许 FINALIZED：前者每个已确认核心 entity 一条最终代表，后者仅展开这些冻结 Top 50 entity 的全部 READY listing。它绝不表示全市场 DS2。`FinalRankingPage` 项包含 entity/listing ID、final/objective rank、未舍入与展示 DS2、八维分、strengths、risks、role_label、eligibility/data/review status、as_of/source index、rule/config/engine/snapshot/ranking hashes，并按 `(final_rank, listing_id)` 稳定游标分页。
- `GET /api/scans/{scan_id}/exports/csv?scope=...` 和 `/xlsx?scope=...`，默认 `core_entities`。
- Preflight 资源必须返回 `capability_state`、`acceptance_mode=LIVE|TEST_ONLY`、`synthetic: bool`。
- `ScanResponse.audit_summary` 固定返回脱敏的 created/finalized 时间、父 scan、snapshot/preflight/gate0_policy/rule/ranking hashes、review/evidence/import counts 和最近事件类型；不含 token、路径或原始错误，供前端 AuditFooter 使用。
- 所有产生/重放幂等写入的 HTTP endpoint 统一只从 `Idempotency-Key` header 取键；JSON body/OpenAPI 不再含 idempotency_key。service command 可在 route 验证后携带内部 `IdempotencyContext`。
- 页面和导出不得用 `view`、`mode` 或大写别名取代 `scope`。

## Runtime and Migration Ownership

- 修改 `backend/pyproject.toml` 加入 `argon2-cffi>=23,<26`、`pypdf>=5,<7`、`defusedxml>=0.7,<1` 和 Windows 条件依赖 `pywin32>=306,<400`，然后重生成 `requirements.lock`。
- 本计划的 Alembic revision 固定接在 Plan 02 的 `20260824_04_frozen_data_snapshot` 之后：
  - `20260824_05_job_runtime.py`
  - `20260824_06_scan_workflow.py`
  - `20260824_07_evidence_ai.py`
  - `20260824_08_imports.py`
  - `20260824_09_tokens.py`
- revision 常量严格固定为 `lsa_05_jobs -> lsa_06_scans -> lsa_07_evidence_ai -> lsa_08_imports -> lsa_09_tokens`，首个 down_revision 是 Plan 02 的 `lsa_04_snapshots`；migration test 断言单一 head、无 branch 和 01→09 线性 upgrade/downgrade。迁移 05 同时拥有通用 `audit_events`；后续迁移只引用 Plan 02 的 source_artifacts，不创建第二份 artifact 权威。

## File Structure

| Area | Files |
|---|---|
| Job domain/runtime | `app/domain/jobs.py`, `app/jobs/{context,lease,registry,targets,runner}.py`, `app/jobs/handlers/*.py` |
| Workflow domain | `app/domain/scans.py`, `app/domain/evidence.py`, `app/domain/io.py` |
| Persistence | `app/db/models/{jobs,scans,evidence,io,security}.py`, matching repositories, migrations 05–09 |
| Services | `job_service.py`, `scan_service.py`, `objective_workflow.py`, `clone_service.py`, `evidence_service.py`, `ai_draft_service.py`, `import_service.py`, `export_service.py` |
| Providers/security | `providers/evidence/*.py`, `providers/ai/*.py`, `security/*.py` |
| API | `app/main.py`, `app/cli.py`, `app/api/{router,dependencies,errors,middleware}.py`, schemas and route modules |
| Tests | `tests/{domain,jobs,services,providers,security,api,db,integration,architecture}` |

---

### Task 1: 持久化 job、attempt、幂等键和目标状态机

**Files:**

- Modify: lightweight-stock-analysis/backend/pyproject.toml
- Modify: lightweight-stock-analysis/backend/requirements.lock
- Modify: lightweight-stock-analysis/backend/app/settings.py
- Create: lightweight-stock-analysis/backend/alembic/versions/20260824_05_job_runtime.py
- Create: lightweight-stock-analysis/backend/app/domain/jobs.py
- Create: lightweight-stock-analysis/backend/app/db/models/jobs.py
- Create: lightweight-stock-analysis/backend/app/db/models/audit.py
- Create: lightweight-stock-analysis/backend/app/db/repositories/audit.py
- Create: lightweight-stock-analysis/backend/app/db/repositories/idempotency.py
- Create: lightweight-stock-analysis/backend/app/db/repositories/jobs.py
- Create: lightweight-stock-analysis/backend/app/jobs/targets.py
- Create: lightweight-stock-analysis/backend/app/services/job_service.py
- Create: lightweight-stock-analysis/backend/tests/domain/test_job_state_machine.py
- Create: lightweight-stock-analysis/backend/tests/services/test_job_service.py

**Interfaces:**

```python
class JobType(StrEnum):
    PREFLIGHT = "PREFLIGHT"
    DATA_SNAPSHOT = "DATA_SNAPSHOT"
    OBJECTIVE_SCAN = "OBJECTIVE_SCAN"
    EVIDENCE_COLLECTION = "EVIDENCE_COLLECTION"
    AI_DRAFT = "AI_DRAFT"
    CLONE_SCAN = "CLONE_SCAN"

class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    INTERRUPTED = "INTERRUPTED"
```

- [ ] **Step 1: 写状态边和幂等 RED 测试**

`test_job_state_machine.py` 断言所有合法边和非法边，特别是只有 `FAILED(retryable)` 或 `INTERRUPTED` 可以请求新 attempt。`test_job_service.py` 覆盖同 `(operation, scope, key, request_hash)` 返回原 job，同 key 不同 hash 抛 `IDEMPOTENCY_KEY_REUSED`，重复 cancel 返回当前资源；`test_queued_job_survives_restart_with_same_payload` 关闭并重建 engine/repository 后认领同一 QUEUED job，断言 canonical payload/hash 与初次提交完全一致且可构造 JobClaim。generic JobService 不得凭 retryable 位直接恢复：本 Task 只用 fake handlers 测试 JobCommandRegistry 委托、未知类型拒绝和返回值透传；真实逐 JobType 的 guard/状态/槽位/审计等价测试等 target services 在 Tasks 2–6 落地后统一放到 Task 9 HTTP 合约门。

- [ ] **Step 2: 运行 RED**

Run:

    .\.venv\Scripts\python.exe -m pytest tests/domain/test_job_state_machine.py tests/services/test_job_service.py tests/db/test_migrations.py -v

Expected: FAIL on missing job domain and migration 05.

- [ ] **Step 3: 实现最小持久化状态机**

pyproject 追加 `argon2-cffi>=23,<26`、`pypdf>=5,<7`、`defusedxml>=0.7,<1`、Windows 条件依赖 `pywin32>=306,<400; sys_platform == 'win32'`。Settings 新增 job heartbeat=10s、lease TTL=60s、单 worker 校验、上传/抓取限额、TLS/trusted proxy 和 AI endpoint 的无密钥字段，仍只解析 LSA_* 变量。`background_jobs` 保存 type、target_type/id、status、priority、progress、canonical `payload_json`、`payload_hash`、cancel_requested_at、retryable、created_at；payload 入库前按 job_type 的 strict schema 校验，读取时重算 hash，且只允许资源 ID/哈希/安全业务参数，拒绝 token、credential、明文 URL、用户文件路径或原始错误。`job_attempts` 保存 attempt_no、checkpoint、error_code/safe_message、heartbeat、lease 字段；`job_leases` 主键/唯一键固定 `(lease_scope, lease_key)`，保存可空 job_id、owner_id、lease_epoch、fencing_token、expires_at，以 `WRITER/global` 与 `JOB/{job_id}` 区分；`idempotency_records` 唯一键 `(operation, scope, key)` 并保存 request_hash/resource_id。迁移 05 还创建 append-only audit_events。

`TargetTransition` 是唯一状态映射权威：为 PREFLIGHT、DATA_SNAPSHOT、OBJECTIVE_SCAN、EVIDENCE_COLLECTION、AI_DRAFT、CLONE_SCAN 分别列出 QUEUED/RUNNING/SUCCEEDED/FAILED/CANCELLED/INTERRUPTED 对应 target 状态及 retry/resume 规则，matrix 测试逐格覆盖。AI_DRAFT 的 job SUCCEEDED 允许且仅允许由 fenced revalidation 选择 target READY 或 SUPERSEDED 两个 outcome；其余 job/status 不得映射 SUPERSEDED。handler 不得直接改 target status。JobCommandRegistry 把 generic cancel/resume 委托给该 target 的同一 service：snapshot resume 重验 preflight/provider/policy，objective scan resume 重验冻结 rule/engine 并重占活动槽，clone resume 重占同一活动槽；禁止 generic endpoint 绕过这些 guard 自行创建 attempt。runner-owned 迁移使用 full attempt fence；QUEUED cancel 和 terminal resume 则持有 writer lease，并以 expected state/version 与 slot CAS 提交。

- [ ] **Step 4: 运行 GREEN、更新锁并提交**

Run:

    .\.venv\Scripts\python.exe -m piptools compile pyproject.toml --extra test --generate-hashes --output-file requirements.lock
    .\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.lock
    .\.venv\Scripts\python.exe -m pytest tests/domain/test_job_state_machine.py tests/services/test_job_service.py tests/db/test_migrations.py -v
    git diff --check
    git add -- lightweight-stock-analysis/backend/pyproject.toml lightweight-stock-analysis/backend/requirements.lock lightweight-stock-analysis/backend/alembic/versions/20260824_05_job_runtime.py lightweight-stock-analysis/backend/app/settings.py lightweight-stock-analysis/backend/app/domain/jobs.py lightweight-stock-analysis/backend/app/db lightweight-stock-analysis/backend/app/jobs/targets.py lightweight-stock-analysis/backend/app/services/job_service.py lightweight-stock-analysis/backend/tests
    git commit -m "feat(lsa): persist idempotent background jobs"

---

### Task 2: 实现 writer/job lease、fencing 和单任务 runner

**Files:**

- Create: lightweight-stock-analysis/backend/app/jobs/context.py
- Create: lightweight-stock-analysis/backend/app/jobs/lease.py
- Create: lightweight-stock-analysis/backend/app/jobs/registry.py
- Create: lightweight-stock-analysis/backend/app/jobs/runner.py
- Create: lightweight-stock-analysis/backend/app/jobs/handlers/__init__.py
- Create: lightweight-stock-analysis/backend/app/jobs/handlers/preflight.py
- Create: lightweight-stock-analysis/backend/app/jobs/handlers/data_snapshot.py
- Create: lightweight-stock-analysis/backend/tests/jobs/test_lease_fencing.py
- Create: lightweight-stock-analysis/backend/tests/jobs/test_runner.py
- Create: lightweight-stock-analysis/backend/tests/jobs/test_data_jobs.py

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class Fence:
    owner_id: str
    lease_epoch: int
    fencing_token: UUID

@dataclass(frozen=True, slots=True)
class JobClaim:
    job_id: UUID
    attempt_id: UUID
    attempt_no: int
    job_type: JobType
    target: JobTarget
    payload: Mapping[str, JsonValue]
    checkpoint: Mapping[str, JsonValue] | None
    fence: Fence

class EmbeddedJobRunner:
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def run_once(self) -> bool: ...
    async def run_forever(self) -> None: ...

class JobExecutionContext(PreflightExecutionContext, Protocol):
    async def checkpoint(self, payload: Mapping[str, JsonValue], progress: float) -> None: ...
    async def raise_if_cancel_requested(self) -> None: ...
    async def commit_preflight_report(self, prepared: PreparedPreflightReport) -> PreflightReport: ...
    def snapshot_context(self, mode: SnapshotCommitMode) -> SnapshotExecutionContext: ...
    async def commit_terminal(self, outcome: JobOutcome, mutation: PreparedTargetMutation) -> JobTarget: ...
```

- [ ] **Step 1: 写接管、双写和优先级 RED 测试**

用两个独立 async session 模拟两 runner：未过期 writer lease 下第二实例启动失败；过期接管使 epoch 严格 +1 且 token 变更；旧 claim checkpoint/complete/target transition 均影响 0 行；heartbeat 校验三元组。断言任意时刻只有一个 RUNNING job，优先级固定 `EVIDENCE_COLLECTION, AI_DRAFT, PREFLIGHT, DATA_SNAPSHOT, OBJECTIVE_SCAN, CLONE_SCAN`，同级按 created_at/job_id。显式覆盖 QUEUED cancel 与 claim、terminal resume 与 claim 的两种提交顺序：command-side 持 writer lease 并按 expected state/version CAS，runner-side 持 full attempt fence，败者不做补偿写。test_data_jobs.py 用 fake Plan 02 PreflightWorkflow/SnapshotBuildWorkflow 断言 DATA_SNAPSHOT handler 只传 `ctx.snapshot_context(TERMINAL_TARGET)`+target ID；workflow 只能通过 context 提交 prepared value。测试让旧 runner完成 prepare 后暂停，cancel 或新 runner 接管，再恢复旧 commit_snapshot_ready/commit_preflight_report，必须因 fence 影响 0 行；新 owner 的 TERMINAL_TARGET 成功时 Plan 02 aggregate、job SUCCEEDED、target READY 在同一事务出现，故障注入则三者全不出现。workflow 异常同步映射 retryable FAILED。另做进程重启测试证明 payload/target ID 能恢复；CLONE_SCAN 的 INTERMEDIATE_PARENT 语义在 Task 4 单独验证。

- [ ] **Step 2: 运行 RED**

Run:

    .\.venv\Scripts\python.exe -m pytest tests/jobs/test_lease_fencing.py tests/jobs/test_runner.py tests/jobs/test_data_jobs.py -v

Expected: FAIL because lease and runner are missing.

- [ ] **Step 3: 实现 CAS 和恢复**

heartbeat 默认 10 秒，lease TTL 60 秒；runner 启动时把租约已过期的 RUNNING attempt 及 target 在同事务改为 INTERRUPTED。JobExecutionContext 只暴露上面受控方法，handler 不持有 repository raw session。每个 commit 方法打开短 UoW，先用 owner_id/lease_epoch/fencing_token/attempt_no/RUNNING 校验 fence，再调用 Plan 02 apply_prepared_*_in_uow 或目标 mutation；TERMINAL_TARGET 才同步写 job/target terminal，INTERMEDIATE_PARENT 只写 snapshot READY 和当前父 target checkpoint/reference并保持 RUNNING，任一步失败整体回滚。context factory 拒绝 DATA_SNAPSHOT+INTERMEDIATE 或 CLONE_SCAN+TERMINAL 的错误组合。Preflight/DataSnapshot handler 分别调用 `PreflightWorkflow.run(ctx, preflight_id)` 与 `SnapshotBuildWorkflow.run(ctx.snapshot_context(TERMINAL_TARGET), snapshot_id)`，不复制 coverage、信任校验或 snapshot commit 逻辑。

- [ ] **Step 4: 运行 GREEN 并提交**

Run:

    .\.venv\Scripts\python.exe -m pytest tests/jobs/test_lease_fencing.py tests/jobs/test_runner.py tests/jobs/test_data_jobs.py tests/services/test_job_service.py -v
    git diff --check
    git add -- lightweight-stock-analysis/backend/app/jobs lightweight-stock-analysis/backend/tests/jobs
    git commit -m "feat(lsa): fence the embedded job runner"

---

### Task 3: 实现 scan 槽、批次评分和 Top 50 原子冻结

**Files:**

- Create: lightweight-stock-analysis/backend/alembic/versions/20260824_06_scan_workflow.py
- Create: lightweight-stock-analysis/backend/app/domain/scans.py
- Create: lightweight-stock-analysis/backend/app/db/models/scans.py
- Create: lightweight-stock-analysis/backend/app/db/repositories/scans.py
- Create: lightweight-stock-analysis/backend/app/services/scan_service.py
- Create: lightweight-stock-analysis/backend/app/services/objective_workflow.py
- Create: lightweight-stock-analysis/backend/app/jobs/handlers/objective_scan.py
- Create: lightweight-stock-analysis/backend/tests/services/test_scan_service.py
- Create: lightweight-stock-analysis/backend/tests/jobs/test_objective_scan_workflow.py
- Create: lightweight-stock-analysis/backend/tests/db/test_candidate_immutability.py

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class CreateScanCommand:
    snapshot_id: UUID
    idempotency: IdempotencyContext

@dataclass(frozen=True, slots=True)
class ObjectiveCandidateSeed:
    entity_id: str
    representative_listing_id: str
    objective_score_unrounded: float
    rank: int
    is_core_top50: bool
    input_snapshot_hash: str

async def commit_candidate_freeze(
    *, scan_id: UUID, candidates: Sequence[ObjectiveCandidateSeed],
    snapshot_manifest_hash: str, claim: JobClaim,
) -> CandidateFreezeResult: ...
```

- [ ] **Step 1: 写活动槽、只读快照和竞态 RED 测试**

覆盖：非 READY snapshot 拒绝；TEST_ONLY snapshot 在非 test 环境拒绝；幂等查找先于活动槽冲突；不同 key 撞槽返回 `SCAN_ALREADY_RUNNING`；每批最多 200 listing；score row、feature IDs、batch member hash、checkpoint 同事务；resume 从最近成功 batch 后开始；workflow 用哨兵 fake 断言永不调 provider。

scan 创建时必须把 preflight report/provider config/markets/as_of/manifest hashes、rule-compatible feature version，以及当前 rule content/config、formula/calibration/scorer/engine semantic 和 engine build hashes复制进 `rule_snapshots` 并逐项验证兼容；任何漂移都拒绝创建。resume 重新比对这些冻结值，不兼容时返回 `SCAN_RESUME_INCOMPATIBLE` 并要求 clone，不在原 scan 改规则或快照。

freeze 测试覆盖 entity 唯一、core 不超 50、rank 连续、candidate canonical hash，以及 cancel 与 REVIEW_PENDING 谁先提交谁获胜。OBJECTIVE_SCAN 在 RUNNING 后的 FAILED/CANCELLED/INTERRUPTED（包括启动恢复 stale RUNNING）通过 TargetTransition 在同一 runner-fenced 事务释放 scan_activity_slot；认领前 QUEUED cancel 则持 writer lease，以 expected job/scan state+version 和 activity-slot CAS 原子提交 job、target、slot。随后新 scan 可以占槽。对原 scan 的 resume 必须持 writer lease，在同一事务以 expected job/scan state+version CAS 重占空槽、创建下一 attempt、把 job/scan 推回 QUEUED；若期间新 scan 或 clone 已占槽，则返回稳定 `SCAN_ACTIVITY_SLOT_OCCUPIED`，原 scan 与旧 terminal job/attempt 完全不变。新增 queued cancel-vs-claim、cancel/fail/crash→new scan、resume 与 create/claim 竞态、旧 fence 迟到释放不影响新 owner 的测试。

- [ ] **Step 2: 运行 RED**

Run:

    .\.venv\Scripts\python.exe -m pytest tests/services/test_scan_service.py tests/jobs/test_objective_scan_workflow.py tests/db/test_candidate_immutability.py tests/db/test_migrations.py -v

Expected: FAIL on missing scan schema and workflow.

- [ ] **Step 3: 实现扫描与冻结事务**

迁移 06 同时创建 scans、clone_operations、scan_activity_slot、scan_checkpoints、eligibility_decisions、score_components、objective_candidates、final_rankings、rule_snapshots。评分唯一键是 `(scan_id, subject_type, subject_id, dimension)`，candidate 唯一键是 `(scan_id, entity_id)`。`commit_candidate_freeze` 事务（名称与 Plan 01 的纯函数 `freeze_objective_candidates` 明确区分）必须依次校验 `RUNNING/OBJECTIVE_SCREENING`、无已提交 cancel、claim fence、candidate 不变量；然后插入 candidates、写 candidate_set_hash、将 scan 改 REVIEW_PENDING、job 改 SUCCEEDED、释放 scan_activity_slot。迁移 06 的 SQLite trigger 在 REVIEW_PENDING/FINALIZED 时拒绝 candidate INSERT/UPDATE/DELETE；FINALIZED 时拒绝 scan 冻结字段和 final_rankings 的 INSERT/UPDATE/DELETE。review_decisions 尚未存在，其 FINALIZED trigger 明确归 migration 07/Task 5。repository guard 与原始 SQL 测试均覆盖本阶段已有表。

- [ ] **Step 4: 运行 GREEN 并提交**

Run:

    .\.venv\Scripts\python.exe -m pytest tests/services/test_scan_service.py tests/jobs/test_objective_scan_workflow.py tests/db/test_candidate_immutability.py tests/db/test_migrations.py -v
    git diff --check
    git add -- lightweight-stock-analysis/backend/alembic/versions/20260824_06_scan_workflow.py lightweight-stock-analysis/backend/app/domain/scans.py lightweight-stock-analysis/backend/app/db/models/scans.py lightweight-stock-analysis/backend/app/db/repositories/scans.py lightweight-stock-analysis/backend/app/services/scan_service.py lightweight-stock-analysis/backend/app/services/objective_workflow.py lightweight-stock-analysis/backend/app/jobs/handlers/objective_scan.py lightweight-stock-analysis/backend/tests
    git commit -m "feat(lsa): freeze objective top fifty scans"

---

### Task 4: 实现生成新快照的 clone workflow

**Files:**

- Modify: lightweight-stock-analysis/backend/app/db/models/scans.py
- Modify: lightweight-stock-analysis/backend/app/db/repositories/scans.py
- Create: lightweight-stock-analysis/backend/app/services/clone_service.py
- Create: lightweight-stock-analysis/backend/app/jobs/handlers/clone_scan.py
- Create: lightweight-stock-analysis/backend/tests/jobs/test_clone_scan_workflow.py

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class CloneScanCommand:
    parent_scan_id: UUID
    preflight_id: UUID
    as_of_date: date
    source_preferences: tuple[SourcePreference, ...]
    clone_reason: str
    idempotency: IdempotencyContext

class CloneService:
    async def create(self, command: CloneScanCommand) -> AcceptedClone: ...

class CloneScanWorkflow:
    async def run(self, ctx: JobExecutionContext, clone_operation_id: UUID) -> CloneResult: ...
```

markets 不允许由请求覆盖，只从 parent scan 的冻结 markets 继承；新 preflight 必须覆盖这些 markets 且通过 Plan 02 当前 policy/hash 验证。

- [ ] **Step 1: 写父隔离、槽转移和不可变 RED 测试**

断言 clone 创建时先占同一 activity slot，handler 直接运行 snapshot workflow 而不 enqueue/等待嵌套 job，并且只传 `ctx.snapshot_context(INTERMEDIATE_PARENT)`。snapshot READY commit 必须在同一 fenced 事务写 clone_operation.snapshot_id/checkpoint，但 clone job/operation 仍 RUNNING；随后唯一 final commit 原子创建带 parent_scan_id 的 QUEUED 子 scan 和 OBJECTIVE_SCAN job、转移槽并把 clone job/operation 改 SUCCEEDED/READY。clone_operation 首次创建便持久化 request hash；snapshot 创建后立即持久 snapshot_id/checkpoint。分别在 snapshot target 创建后、snapshot READY intermediate commit 后、child scan/job commit 前模拟退出并重启，始终复用同一 snapshot_id，最终至多一个 child scan/OBJECTIVE_SCAN job。每个边界测试旧 fence、cancel 与 takeover；父 snapshot/observation/score/candidate 哈希前后相同。RUNNING 后的失败/取消/中断通过 TargetTransition 在同一 runner-fenced 事务释放槽；认领前 QUEUED cancel 持 writer lease，以 expected job/operation state+version 和 activity-slot CAS 原子提交 job、target、slot。已原子 READY 的新 snapshot 可保留供审计/恢复，不被重复创建。恢复同一 INTERRUPTED/retryable FAILED clone_operation 时，持 writer lease并在同一事务以 expected job/operation state+version CAS 重占空槽、创建下一 attempt 并推回 QUEUED；若期间 scan/clone 已占槽，返回 `SCAN_ACTIVITY_SLOT_OCCUPIED` 且 operation/job/checkpoint 不变。测试 queued cancel-vs-claim、resume 与新 scan/clone/claim 抢槽的两种提交顺序及旧 owner 迟到提交。

- [ ] **Step 2: 运行 RED**

Run:

    .\.venv\Scripts\python.exe -m pytest tests/jobs/test_clone_scan_workflow.py -v

Expected: FAIL on missing clone service and handler.

- [ ] **Step 3: 实现最小 workflow**

Clone 只从父 scan 继承 markets；使用 command 的新 preflight_id、as_of_date、source_preferences 和审计 reason 创建新的 pending snapshot，不复制旧冻结输入/分数。所有重试先读 clone_operation 的 snapshot_id/child_scan_id，再决定从 checkpoint 恢复，禁止创建平行资源。SnapshotBuildWorkflow 返回后不得假设 clone terminal；只有 CloneScanWorkflow 的最终 fenced commit 可以创建 child/job、转槽并终止 clone。

- [ ] **Step 4: 运行 GREEN 并提交**

Run:

    .\.venv\Scripts\python.exe -m pytest tests/jobs/test_clone_scan_workflow.py -v
    git diff --check
    git add -- lightweight-stock-analysis/backend/app/db/models/scans.py lightweight-stock-analysis/backend/app/db/repositories/scans.py lightweight-stock-analysis/backend/app/services/clone_service.py lightweight-stock-analysis/backend/app/jobs/handlers/clone_scan.py lightweight-stock-analysis/backend/tests/jobs/test_clone_scan_workflow.py
    git commit -m "feat(lsa): rebuild snapshots through scan clones"

---

### Task 5: 安全采集、冻结和评估 EvidenceBundle

**Files:**

- Create: lightweight-stock-analysis/backend/alembic/versions/20260824_07_evidence_ai.py
- Create: lightweight-stock-analysis/backend/app/domain/evidence.py
- Create: lightweight-stock-analysis/backend/app/db/models/evidence.py
- Create: lightweight-stock-analysis/backend/app/db/repositories/evidence.py
- Create: lightweight-stock-analysis/backend/app/providers/evidence/base.py
- Create: lightweight-stock-analysis/backend/app/providers/evidence/safe_http.py
- Create: lightweight-stock-analysis/backend/app/providers/evidence/documents.py
- Create: lightweight-stock-analysis/backend/app/services/evidence_service.py
- Create: lightweight-stock-analysis/backend/app/jobs/handlers/evidence_collection.py
- Create: lightweight-stock-analysis/backend/tests/security/test_safe_url_fetcher.py
- Create: lightweight-stock-analysis/backend/tests/security/test_document_inspection.py
- Create: lightweight-stock-analysis/backend/tests/services/test_evidence_service.py
- Create: lightweight-stock-analysis/backend/tests/domain/test_evidence_gate.py
- Create: lightweight-stock-analysis/backend/tests/db/test_finalized_review_immutability.py

**Interfaces:** `EvidenceSourceProvider.collect(request) -> AsyncIterator[EvidenceCandidate]`；`SafeUrlFetcher.fetch`；`EvidenceService.validate_url/validate_upload/commit/freeze_bundle/create_collection/get_collection/list_entity_evidence`；`EvidenceCollectionWorkflow.run(ctx, collection_id)`；`evaluate_evidence_gate`。

- [ ] **Step 1: 写 SSRF、文档和证据门 RED 测试**

覆盖：只允 HTTPS 与 allowlist domain/path/purpose；拒绝 loopback、私网、link-local、metadata IP；DNS 解析固定到连接，每次 redirect 重新校验；最多 5 次跳转、25 MiB、30 秒。PDF 拒绝 JavaScript/OpenAction/Launch/embedded file/RichMedia；HTML 只取静态文本且不取子资源。

Evidence 测试断言 publisher identity 由服务端来源规则导出；用户上传默认 USER_DECLARED，只有与已 allowlist 官方 URL artifact hash 完全相同或有效数字签名链验证通过才升级 verification_status；更正通过 `supersedes_evidence_id` 新增，不更新旧 item。Gate 要求至少 2 个独立 verified publisher、至少 1 个 primary source、行业证据 18 个月内、日期不晚于 as_of，并有 counterevidence 或显式无反证搜寻声明；CONFLICTED 阻断确认。

collection 测试覆盖：create 在 202 前持久化 collection+job 并使用 IdempotencyContext；get 返回 PENDING/RUNNING/READY/FAILED/CANCELLED/INTERRUPTED 与新增 evidence IDs；allowlist source provider checkpoint 后重启不重复 item；取消在安全边界生效；list_entity_evidence 只返回该 scan/entity 的已提交不可变 items。非 test registry 默认无采集 provider并返回明确 NOT_CONFIGURED，不伪造证据。

迁移 07 的 raw-SQL/repository 测试在 scan=FINALIZED 时分别尝试 review_decisions INSERT/UPDATE/DELETE，全部拒绝；REVIEW_PENDING 时仅符合 optimistic version 的合法写入可通过。该测试不能提前放在 migration 06。

- [ ] **Step 2: 运行 RED**

Run:

    .\.venv\Scripts\python.exe -m pytest tests/security/test_safe_url_fetcher.py tests/security/test_document_inspection.py tests/services/test_evidence_service.py tests/domain/test_evidence_gate.py tests/db/test_finalized_review_immutability.py tests/db/test_migrations.py -v

Expected: FAIL on missing evidence schema and safe fetcher.

- [ ] **Step 3: 实现不可变 evidence 与 bundle hash**

迁移 07 创建 evidence_validations、evidence_items、evidence_collections、evidence_bundles、evidence_bundle_items、ai_drafts、review_decisions，使 Task 6 可以在不再改 schema 的前提下实现 AI/复核。Evidence item 保存 artifact_id、publisher_identity、verification_status、verification_basis、published_at、locator、direction、content_hash。Bundle hash 对排序 evidence IDs 及每项内容 hash 求 canonical SHA-256。SQLite trigger 拒绝 evidence_items UPDATE/DELETE 和 frozen bundle membership 更改。collection target 通过 EvidenceCollectionWorkflow 和通用 TargetTransition 推进，handler 不自行写状态。

- [ ] **Step 4: 运行 GREEN 并提交**

Run:

    .\.venv\Scripts\python.exe -m pytest tests/security/test_safe_url_fetcher.py tests/security/test_document_inspection.py tests/services/test_evidence_service.py tests/domain/test_evidence_gate.py tests/db/test_finalized_review_immutability.py tests/db/test_migrations.py -v
    git diff --check
    git add -- lightweight-stock-analysis/backend/alembic/versions/20260824_07_evidence_ai.py lightweight-stock-analysis/backend/app/domain/evidence.py lightweight-stock-analysis/backend/app/db/models/evidence.py lightweight-stock-analysis/backend/app/db/repositories/evidence.py lightweight-stock-analysis/backend/app/providers/evidence lightweight-stock-analysis/backend/app/services/evidence_service.py lightweight-stock-analysis/backend/app/jobs/handlers/evidence_collection.py lightweight-stock-analysis/backend/tests
    git commit -m "feat(lsa): validate and freeze evidence bundles"

---

### Task 6: 实现证据绑定 AI 草稿和乐观人工复核

**Files:**

- Create: lightweight-stock-analysis/backend/app/providers/ai/base.py
- Create: lightweight-stock-analysis/backend/app/providers/ai/openai_compatible.py
- Create: lightweight-stock-analysis/backend/app/providers/ai/prompts/defensive-review-v1.json
- Create: lightweight-stock-analysis/backend/app/services/ai_draft_service.py
- Create: lightweight-stock-analysis/backend/app/services/review_service.py
- Create: lightweight-stock-analysis/backend/app/services/finalization_service.py
- Create: lightweight-stock-analysis/backend/app/jobs/handlers/ai_draft.py
- Modify: lightweight-stock-analysis/backend/app/jobs/targets.py
- Create: lightweight-stock-analysis/backend/tests/providers/test_openai_compatible_adapter.py
- Create: lightweight-stock-analysis/backend/tests/jobs/test_ai_draft_workflow.py
- Create: lightweight-stock-analysis/backend/tests/services/test_review_service.py
- Create: lightweight-stock-analysis/backend/tests/services/test_finalization_service.py
- Modify: lightweight-stock-analysis/backend/tests/domain/test_job_state_machine.py

**Interfaces:** `AIAdapter.generate_draft(request) -> ModelDraftPayload`；`AIDraftService.create`；`ReviewService.update(expected_version, ...)`；`FinalizationService.finalize(scan_id, idempotency: IdempotencyContext) -> FinalizedScanView`。

- [ ] **Step 1: 写无检索、引用和迟到竞态 RED 测试**

`AIDraftService.create` 接受用户选择的 evidence_ids + base_review_version，在创建 draft/job 的同一事务校验这些 IDs 属于该 scan/entity、不可变且满足集合约束，调用 freeze_bundle 得到 bundle_id/hash，并把二者写入 draft；调用方不需要预先拥有 bundle_id。断言 adapter 请求只含该冻结 bundle、两个主观维度固定子项、0–100 整数、support/counter claims、uncertainties、as_of_date、evidence IDs；不包含 search/fetch/browser tool。未知 ID、模型 URL/publisher 或 bundle 外引用被拒绝。prompt asset 有固定 template_version/content_hash；模板改变必须产生新的 draft_version，旧 draft 保存 model、template version/hash、bundle hash、base_review_version 并仍可审计。

迟到响应在 review version 改变、已确认或 scan 离开 REVIEW_PENDING 时，通过唯一 TargetTransition 以 `job=SUCCEEDED,target=SUPERSEDED` 原子提交，不覆盖人工值；当前版本则 `SUCCEEDED+READY`。matrix 测试拒绝其他 job/status 进入 SUPERSEDED。Fake adapter 在非 test 环境构造或持久化验收记录均失败。ReviewService 在 expected_version 过期时返回 `REVIEW_VERSION_CONFLICT`并不修改服务端记录；每次 CONFIRMED/MANUAL_CONFIRMED 都必须关联本次提交冻结的 EvidenceBundle，人工任一主观子项与对应最新 AI 建议绝对偏差超过 10 时 reason 必填，并覆盖“aggregate 偏差不超过 10、但单个子项超过 10”仍拒绝。Finalization 测试要求每个 core entity 都是 CONFIRMED、MANUAL_CONFIRMED、SKIPPED 或 EXCLUDED_BY_REVIEW，且至少一项已确认；只有前两者进入 DS2 排名；同幂等键重放返回同一冻结资源。并发测试在排名计算期间更新 review_version，断言 finalize 要么看到更新并按新版本计算，要么整体冲突回滚，绝不冻结旧输入。

- [ ] **Step 2: 运行 RED**

Run:

    .\.venv\Scripts\python.exe -m pytest tests/providers/test_openai_compatible_adapter.py tests/jobs/test_ai_draft_workflow.py tests/services/test_review_service.py tests/services/test_finalization_service.py -v

Expected: FAIL on missing AI adapter and review service.

- [ ] **Step 3: 实现 JSON Schema adapter 和 fenced 提交**

OpenAI-compatible adapter 通过 httpx 发出结构化 JSON Schema 请求，不依赖父项目 SDK 包装。标题、URL、publisher、日期由服务端按 ID 回填。AI job 提交时在 fenced 事务重新验证 bundle hash、base_review_version、scan status 和 citation membership。ReviewService 调用阶段一主观评分，并先运行 EvidenceGate；证据不足返回 `EVIDENCE_INSUFFICIENT`。

FinalizationService 在一个短 `BEGIN IMMEDIATE` 事务内重读最多 50 个 core review 及版本、验证全部决策/evidence gate/rule hashes，调用 Plan 01 `rank_final_entities`，写 final_rankings/ranking_hash，CAS 改 FINALIZED 后提交；事务内不做网络或 AI。这样 review 更新与 finalize 串行化，不使用“先 read transaction、后独立 CAS”的 TOCTOU 结构。

- [ ] **Step 4: 运行 GREEN 并提交**

Run:

    .\.venv\Scripts\python.exe -m pytest tests/providers/test_openai_compatible_adapter.py tests/jobs/test_ai_draft_workflow.py tests/services/test_review_service.py tests/services/test_finalization_service.py -v
    git diff --check
    git add -- lightweight-stock-analysis/backend/app/providers/ai lightweight-stock-analysis/backend/app/services/ai_draft_service.py lightweight-stock-analysis/backend/app/services/review_service.py lightweight-stock-analysis/backend/app/services/finalization_service.py lightweight-stock-analysis/backend/app/jobs/handlers/ai_draft.py lightweight-stock-analysis/backend/app/jobs/targets.py lightweight-stock-analysis/backend/tests
    git commit -m "feat(lsa): confirm reviews and finalize rankings"

---

### Task 7: 实现安全导入、一致导出和公式注入防护

**Files:**

- Create: lightweight-stock-analysis/backend/alembic/versions/20260824_08_imports.py
- Create: lightweight-stock-analysis/backend/app/domain/io.py
- Create: lightweight-stock-analysis/backend/app/db/models/io.py
- Create: lightweight-stock-analysis/backend/app/db/repositories/imports.py
- Create: lightweight-stock-analysis/backend/app/security/uploads.py
- Create: lightweight-stock-analysis/backend/app/services/import_service.py
- Create: lightweight-stock-analysis/backend/app/services/export_service.py
- Create: lightweight-stock-analysis/backend/tests/security/test_uploads.py
- Create: lightweight-stock-analysis/backend/tests/services/test_import_service.py
- Create: lightweight-stock-analysis/backend/tests/services/test_export_service.py

**Interfaces:** `ImportService.validate/commit`；`CommittedImportOverrideAdapter` 实现 Plan 02 `ApprovedSeriesOverridePort`；`ExportService.freeze_view(scan_id, scope) -> FinalExportSnapshot`；`is_formula_like_text`；`export_cell`。

- [ ] **Step 1: 写两步导入和单快照导出 RED 测试**

导入覆盖服务端随机文件名、扩展名+内容签名一致、25 MiB、CSV 100,000 行、XLSX 10 sheets/解压 100 MiB，并拒绝宏、外部链接、公式单元格、嵌入对象和 zip bomb。validate 不写 canonical observation；commit 校验 validation TTL、file hash、mapping hash 并幂等写 Plan 02 source_artifact、类型化 observation、import source/series override 和 audit。集成测试证明 commit 后，新 snapshot 按明确 source_preferences 可通过 `CommittedImportOverrideAdapter` 选择该序列，并完整读回每年来源、拼接原因、单位、币种、复权、审核人、时间和备注；未提交 validation 永不可选。

导出覆盖 CSV/XLSX 从同一 `FinalExportSnapshot` 生成，非 FINALIZED 拒绝，负数数值仍是数值。文本检测副本移除开头 BOM、空白、Tab、CR/LF、U+0000–U+001F 后，若首字符是 `= + - @` 则强制文本并前置单引号。

- [ ] **Step 2: 运行 RED**

Run:

    .\.venv\Scripts\python.exe -m pytest tests/security/test_uploads.py tests/services/test_import_service.py tests/services/test_export_service.py tests/db/test_migrations.py -v

Expected: FAIL on missing import/export implementation and migration 08.

- [ ] **Step 3: 实现流式限制和 typed export schema**

`ExportColumn` 明确 `kind=NUMBER|TEXT|DATE`，不根据运行值猜测。两种 scope 都记录 scan_id、ranking_hash、rule/config/engine hashes、snapshot manifest、preflight report/gate0 policy hashes、measured_at/expires_at、每市场 capability/acceptance/synthetic、as_of_date、资格/数据状态与排除原因、ObjectiveScore/DS2/八维/子项、EvidenceBundle IDs、review decision/修改理由、来源索引和研究免责声明。测试把导出逐行与同一数据库 read transaction 的 FinalRankingPage 比对。

- [ ] **Step 4: 运行 GREEN 并提交**

Run:

    .\.venv\Scripts\python.exe -m pytest tests/security/test_uploads.py tests/services/test_import_service.py tests/services/test_export_service.py tests/db/test_migrations.py -v
    git diff --check
    git add -- lightweight-stock-analysis/backend/alembic/versions/20260824_08_imports.py lightweight-stock-analysis/backend/app/domain/io.py lightweight-stock-analysis/backend/app/db/models/io.py lightweight-stock-analysis/backend/app/db/repositories/imports.py lightweight-stock-analysis/backend/app/security/uploads.py lightweight-stock-analysis/backend/app/services/import_service.py lightweight-stock-analysis/backend/app/services/export_service.py lightweight-stock-analysis/backend/tests
    git commit -m "feat(lsa): harden research imports and exports"

---

### Task 8: 实现非 loopback TLS、Bearer、ACL 和日志脱敏

**Files:**

- Create: lightweight-stock-analysis/backend/alembic/versions/20260824_09_tokens.py
- Modify: lightweight-stock-analysis/backend/app/cli.py
- Create: lightweight-stock-analysis/backend/app/db/models/security.py
- Create: lightweight-stock-analysis/backend/app/db/repositories/tokens.py
- Create: lightweight-stock-analysis/backend/app/security/deployment.py
- Create: lightweight-stock-analysis/backend/app/security/tokens.py
- Create: lightweight-stock-analysis/backend/app/security/file_permissions.py
- Create: lightweight-stock-analysis/backend/app/security/redaction.py
- Create: lightweight-stock-analysis/backend/tests/security/test_transport.py
- Create: lightweight-stock-analysis/backend/tests/security/test_tokens.py
- Create: lightweight-stock-analysis/backend/tests/security/test_token_cli.py
- Create: lightweight-stock-analysis/backend/tests/security/test_redaction.py

**Interfaces:** `validate_deployment`、`resolve_effective_transport`、`TokenService.issue/verify/rotate/revoke`、`redact_log_fields`；CLI 精确命令 `python -m app.cli issue-token --database <absolute-db-path> --output-path <absolute-path-inside-LSA_SECRETS_DIR>` 与 `python -m app.cli rotate-token --database <absolute-db-path> --token-id <uuid> --output-path <absolute-path-inside-LSA_SECRETS_DIR>`。

- [ ] **Step 1: 写传输与密钥边界 RED 测试**

断言默认 127.0.0.1 无 Bearer；非 loopback 明文启动失败；非 trusted peer 的 `X-Forwarded-Proto` 被忽略；trusted proxy 的 https 被接受；liveness 可匿名但不豁免传输安全。数据库只存 token_id + Argon2id hash；issue/rotate 在唯一 secrets 目录原子写 Git-ignored 明文 token file，Windows DACL 只有当前用户和 SYSTEM 可读，rotate 撤销并替换旧文件；DACL 无法创建或读回确认时非 loopback 启动失败。CLI test 在刚 init 到 migration 09 的 tmp DB 上执行精确 issue-token 命令，验证 hash 可认证、明文 DACL、stdout/stderr 不含 secret，且 secrets 目录外 output path 被拒绝不写文件；随后执行 rotate-token，断言旧 secret/hash 立即不可认证、新 secret 可认证、旧明文文件被替换/失效、新文件 DACL 正确、audit 只有 token_id/action 且无 secret。

- [ ] **Step 2: 运行 RED**

Run:

    .\.venv\Scripts\python.exe -m pytest tests/security/test_transport.py tests/security/test_tokens.py tests/security/test_token_cli.py tests/security/test_redaction.py tests/db/test_migrations.py -v

Expected: FAIL on missing deployment and token services.

- [ ] **Step 3: 实现安全默认**

明文 token 默认只写入 `LSA_SECRETS_DIR/tokens/<token_id>.txt` 的同目录随机临时文件，使用 pywin32 显式设置并读回 owner/DACL 后原子 rename；issue-token/rotate-token 的 `--output-path` 只允许解析后仍位于 LSA_SECRETS_DIR 内，供隔离 E2E 固定 handoff path，越界即拒绝。rotate 先为新 token_id 写经 DACL 校验的临时/最终新文件，再在同一 DB transaction 撤销旧 hash并登记新 hash；DB 失败删除未激活新文件，commit 后删除旧文件。启动恢复会删除“DB 无有效 token 记录”的 orphan 新文件和已 revoked 的旧文件，故障注入覆盖各边界；旧 secret 从 DB commit 起立即无效。CLI stdout 只显示 token_id 和脱敏路径，不显示 secret，audit 只记 token_id/action。非 Windows 不支持首版非 loopback token-file 模式并 fail closed。只有 direct TLS 或 peer IP 命中配置 CIDR 时才信任 forwarded proto。loopback 模式不开 CORS；前端由同源后端服务。

- [ ] **Step 4: 运行 GREEN 并提交**

Run:

    .\.venv\Scripts\python.exe -m pytest tests/security/test_transport.py tests/security/test_tokens.py tests/security/test_token_cli.py tests/security/test_redaction.py tests/db/test_migrations.py -v
    git diff --check
    git add -- lightweight-stock-analysis/backend/alembic/versions/20260824_09_tokens.py lightweight-stock-analysis/backend/app/cli.py lightweight-stock-analysis/backend/app/db/models/security.py lightweight-stock-analysis/backend/app/db/repositories/tokens.py lightweight-stock-analysis/backend/app/security lightweight-stock-analysis/backend/tests/security
    git commit -m "feat(lsa): secure non-loopback api access"

---

### Task 9: 暴露完整 FastAPI 资源契约

**Files:**

- Create: lightweight-stock-analysis/backend/app/main.py
- Modify: lightweight-stock-analysis/backend/app/cli.py
- Create: lightweight-stock-analysis/backend/app/api/router.py
- Create: lightweight-stock-analysis/backend/app/api/dependencies.py
- Create: lightweight-stock-analysis/backend/app/api/errors.py
- Create: lightweight-stock-analysis/backend/app/api/middleware.py
- Create: lightweight-stock-analysis/backend/app/api/schemas/common.py
- Create: lightweight-stock-analysis/backend/app/api/schemas/jobs.py
- Create: lightweight-stock-analysis/backend/app/api/schemas/sources.py
- Create: lightweight-stock-analysis/backend/app/api/schemas/snapshots.py
- Create: lightweight-stock-analysis/backend/app/api/schemas/imports.py
- Create: lightweight-stock-analysis/backend/app/api/schemas/evidence.py
- Create: lightweight-stock-analysis/backend/app/api/schemas/scans.py
- Create: lightweight-stock-analysis/backend/app/api/schemas/reviews.py
- Create: lightweight-stock-analysis/backend/app/api/routes/health.py
- Create: lightweight-stock-analysis/backend/app/api/routes/sources.py
- Create: lightweight-stock-analysis/backend/app/api/routes/snapshots.py
- Create: lightweight-stock-analysis/backend/app/api/routes/imports.py
- Create: lightweight-stock-analysis/backend/app/api/routes/evidence.py
- Create: lightweight-stock-analysis/backend/app/api/routes/scans.py
- Create: lightweight-stock-analysis/backend/app/api/routes/reviews.py
- Create: lightweight-stock-analysis/backend/app/api/routes/jobs.py
- Create: lightweight-stock-analysis/backend/tests/api/test_workflow_endpoints.py
- Create: lightweight-stock-analysis/backend/tests/api/test_auth.py
- Create: lightweight-stock-analysis/backend/tests/api/test_scan_races.py
- Create: lightweight-stock-analysis/backend/tests/api/test_contract_snapshot.py
- Create: lightweight-stock-analysis/backend/tests/api/fixtures/openapi-approved.json
- Create: lightweight-stock-analysis/backend/tests/test_db_initialization.py

**Interfaces:**

```python
class ErrorResponse(BaseModel):
    request_id: str
    code: str
    message: str
    details: dict[str, JsonValue] = Field(default_factory=dict)
```

Accepted schemas 禁止泛化 `target_id`：`AcceptedPreflightResponse(preflight_id, job_id, status, request_id)`、`AcceptedSnapshotResponse(snapshot_id, job_id, status, request_id)`、`AcceptedScanResponse(scan_id, job_id, status, request_id)`、`AcceptedCollectionResponse(collection_id, job_id, status, request_id)`、`AcceptedDraftResponse(draft_id, job_id, status, request_id)`、`AcceptedCloneResponse(clone_operation_id, job_id, status, request_id)`，cancel/resume 也返回明确 scan_id/job_id/attempt status。每个 Location 指向对应 target GET，不指向泛化 job；job 另有自身 URL。

核心 JSON schema 在写实现前按下表手工冻结进 openapi-approved.json；所有 request `extra=forbid`，未列 optional 的字段均 required，nullable 必须显式 `type|null`：

| Schema | Required fields | Optional / nullable / constraints |
|---|---|---|
| HealthResponse | request_id、status、service、api_schema_version、installation_id_hash | service literal `lightweight-stock-analysis`；hash 为 init-db installation manifest 的安全稳定标识，不含路径/secret |
| PreflightCreateRequest | markets[CN\|HK]、as_of_date、source_preferences | markets non-empty/unique；无 idempotency_key body |
| PreflightResponse | 判别联合，共同字段 request_id、preflight_id、status、markets、as_of_date、source_preferences | PENDING/RUNNING 不得出现报告业务值；READY 额外必填 capability_state、acceptance_mode、synthetic、gate0_policy_hash、report_hash、measured_at、expires_at、market_results、coverage、readbacks、gaps；FAILED/CANCELLED/INTERRUPTED 必填 safe_error |
| SnapshotCreateRequest | preflight_id、as_of_date、markets、source_preferences | markets non-empty/unique |
| SnapshotResponse | 判别联合，共同字段 request_id、snapshot_id、status、preflight_id、as_of_date、markets | QUEUED/SYNCING 只额外必填 progress，不得伪造 manifest/capability；READY 额外必填 progress、market_capabilities（每市场 capability_state/acceptance_mode/synthetic）、market_effective_dates、counts、quality_distribution、preflight_report_hash、gate0_policy_hash、provider_config_hash、manifest_hash、completed_at；FAILED/CANCELLED/INTERRUPTED 必填 progress、safe_error |
| ScanCreateRequest | snapshot_id | body only this field |
| ScanResponse | request_id、scan_id、status、stage、counts、checkpoint、snapshot_id、rule/config/engine hashes、audit_summary | parent_scan_id、error nullable |
| CloneScanRequest | preflight_id、as_of_date、source_preferences、clone_reason | markets forbidden；reason 1..1000 |
| CloneOperationResponse | request_id、clone_operation_id、parent_scan_id、status、snapshot_id、child_scan_id | two IDs nullable until created；safe_error nullable |
| JobResponse | 判别联合，共同字段 request_id、job_id、job_type、status、target{type,id}、progress、retryable | QUEUED 不含 attempt_no/checkpoint/safe_error；RUNNING、SUCCEEDED 必填 attempt_no，checkpoint 字段必存在但值为 object|null，且不含 safe_error；FAILED/CANCELLED/INTERRUPTED 必填 safe_error，attempt_no/checkpoint 显式可空以覆盖认领前取消；JobStatus exact enum |
| ImportValidation/Commit | validation_id/import_id、status、file_hash、mapping_hash、issues/audit_summary | validation request is multipart；commit body only validation_id |
| EvidenceValidation/Commit | validation_id/evidence_id、status、publisher/verification/direction/locator/content_hash | URL-or-upload discriminated request；committed ID nullable before commit |
| EvidenceCollectionResponse | request_id、collection_id、status、evidence_ids | evidence_ids default []；safe_error nullable |
| EvidenceItem/Bundle | IDs、publisher_identity、verification_status/basis、published_at、locator、direction、content_hash、frozen | source_url nullable and already safe |
| AIDraftCreateRequest | evidence_ids、base_review_version | evidence_ids non-empty/unique；service 原子冻结 bundle；no model/provider override |
| AIDraftResponse | request_id、draft_id、status、draft_version、base_review_version、bundle/template/model metadata、payload | payload nullable until READY；safe_error nullable；status includes SUPERSEDED |
| ReviewUpdateRequest | evidence_ids、industry_subscores、moat_subscores、decision、reason、no_counterevidence_statement、role_label、expected_version | subjective groups nullable only for SKIPPED/EXCLUDED；reason rules server enforced |
| ReviewResponse | request_id、entity_id、review_version、decision、evidence_bundle_id、scores、reason、role_label、updated_at | scores nullable by decision |
| CandidatePage | request_id、items、next_cursor | query scope/cursor/limit/status/market/industry；next_cursor nullable |
| CandidateItem | entity_id、listing_id、objective_rank、objective_score、six_dimensions、eligibility_status、data_status、market、industry、rule/snapshot hashes | missing/reasons arrays；no DS2 |
| FinalRankingPage | request_id、items、next_cursor、ranking_hash | FINALIZED only；next_cursor nullable |
| FinalRankingItem | entity_id、listing_id、final_rank、objective_rank、ds2_unrounded/display、objective_score、eight_dimensions、strengths、risks、role_label、eligibility/data/review status、as_of_date、source_index、rule/config/engine/snapshot/ranking hashes | role_label nullable；DS2 non-null for included rows |

Status schema 精确冻结 CapabilityState、AcceptanceMode、JobStatus、SnapshotStatus、ScanStatus、EvidenceCollectionStatus、AIDraftStatus 和 CloneOperationStatus；新增未知 enum 对前端是 unknown-safe，但后端当前 OpenAPI 不得漏列已知值。

- [ ] **Step 1: 写 OpenAPI/HTTP RED 合约测试**

每个 202 端点必须先在同事务提交 job/target，返回上述端点专用 ID、job_id、status，并设 `Location` 到 target 资源。OpenAPI/route 测试断言所有此类请求只接受 `Idempotency-Key` header，body 出现 idempotency_key 因 extra=forbid 返回 422；缺 header、过长 key、同 key 异 payload分别返回稳定错误。每个 JSON 成功/失败响应同时含 `X-Request-ID` 和 body request_id；binary 导出至少含 header。异常只通过稳定 `code/message/details`。openapi-approved.json 在实现前依据本节手写，首个 RED 必须因 route/schema 缺失失败；禁止从生成后的 OpenAPI 反向覆盖 fixture。

必测端点：

- `GET /api/health/live`, `GET /api/health`, `GET /api/data-sources`
- `POST /api/data-sources/preflight`, `GET /api/data-sources/preflights/{preflight_id}`
- `POST /api/data-snapshots`, `GET /api/data-snapshots/{snapshot_id}`
- `POST /api/imports/validate`, `POST /api/imports/commit`
- `POST /api/evidence/validate`, `POST /api/evidence/commit`
- `POST /api/scans/{scan_id}/entities/{entity_id}/evidence/collect`、`GET /api/evidence/collections/{collection_id}`、`GET /api/scans/{scan_id}/entities/{entity_id}/evidence`
- `POST /api/scans`、`GET /api/scans/{scan_id}`、`POST /api/scans/{scan_id}/cancel|resume|clone`、`GET /api/clone-operations/{clone_operation_id}`
- `GET /api/scans/{scan_id}/candidates` 与 `/rankings`（各自两种 scope、filters、cursor）、stock detail、entity detail
- `POST /api/scans/{scan_id}/entities/{entity_id}/ai-drafts`、`GET /api/ai-drafts/{draft_id}`、PUT review、POST finalize
- `GET /api/scans/{scan_id}/exports/csv|xlsx`（必须测两种 scope）
- `GET /api/jobs/{job_id}`、`POST /api/jobs/{job_id}/cancel|resume`

`PreflightResponse`、`SnapshotResponse`、`JobResponse` 必须以 status literal 建成真正的 discriminated union，而不是把 READY 字段全部改成 nullable。契约测试逐分支断言：PENDING/RUNNING preflight 能在没有任何 capability/report 字段时解析，READY 缺 capability_state/acceptance_mode/synthetic/gate0_policy_hash 或报告字段必失败，失败终态缺 safe_error 必失败；QUEUED/SYNCING snapshot 没有 manifest/capability 时可解析，READY 缺任一冻结字段必失败；QUEUED job 没有 attempt_no 可解析，RUNNING/SUCCEEDED 缺 attempt_no 或缺 checkpoint 字段必失败，但 `checkpoint:null` 合法。禁止用 `NOT_CONFIGURED`、空 hash、0 coverage 或 null manifest 作为未完成业务结果的占位值；Job checkpoint 的 null 仅表示已认领但尚无安全边界。`GET /api/health` 必须返回可供 Gate 0 脚本先验核对的 service/api_schema_version/installation_id_hash，错误 service 或 installation 不得继续 POST。READY `PreflightResponse` 还要直接断言 coverage 分子/分母/门槛/缺口；`ScanResponse` 直接断言 audit_summary。`ReviewUpdateRequest` 包含 evidence_ids、两个可空主观维度、decision、reason、no_counterevidence_statement、role_label、expected_version。Task 9 还要逐 JobType 对比 `/jobs/{id}/cancel|resume` 与对应资源端点：两入口必须命中同一 command handler，并在 guard、expected-version/slot CAS、target/job/attempt 状态和 audit 上完全一致；未知或无安全资源命令的类型稳定拒绝。

负向表驱动 API 测试冻结：无效日期/market/scope/cursor、未知资源 404、错误状态下 cancel/resume/review/finalize 409/422、QUEUED/RUNNING candidates 返回 409 CANDIDATES_NOT_FROZEN、非 FINALIZED rankings/export 拒绝、`/api/unknown` JSON 404 且不进入 SPA fallback、health/data-sources/error 不泄漏路径/credential/license 原文/traceback。`CandidatePage` 与 `FinalRankingPage` required/nullability/next_cursor 进入 OpenAPI snapshot。

- [ ] **Step 2: 运行 RED**

Run:

    .\.venv\Scripts\python.exe -m pytest tests/api -v

Expected: FAIL because app factory and routes do not exist.

- [ ] **Step 3: 实现 schema、routes、middleware 和 lifespan**

`create_app(settings)` lifespan 依次：验证部署安全，连接并验证 schema head，认领 writer lease，启动 runner；关闭时先停止认领，等待当前安全边界，再释放 lease/engine。它绝不自动 migration。`python -m app.cli init-db --database <absolute-new-path>` 是唯一新库初始化命令：只允许目标不存在或长度为 0，在独占文件锁下把 01→09 migration 应用于该库并写 installation manifest；路径已存在且非空、已有未知表或非 current head 一律拒绝且不修改。`serve` CLI 强制 workers=1，缺库/旧 schema 给出安全错误和显式运维指引。写请求不自动重试；Idempotency-Key 必须持久化。模型可空字段在 response schema 显式可空，前后端类型同步。

Task 9 同时把 Plan 02 的 `app.cli preflight` 从空-registry 诊断升级为唯一生产路径：验证用户已配置 provider/联网授权后，连接 current-head DB、获取 writer lease、通过与 POST route 相同的 service 创建 pending preflight+PREFLIGHT job，运行 embedded runner 至该 job terminal，再输出保存后的脱敏 PreflightResponse 并释放 lease；server 已占 writer lease 时明确拒绝并提示使用 API。CLI integration test 执行命令后用 `GET /api/data-sources/preflights/{preflight_id}` 读回同一 report_hash/gate0_policy_hash/三状态，且 takeover/cancel 仍受 fence；禁止 CLI 直接调用 repository commit。

- [ ] **Step 4: 运行 API 门并提交**

Run:

    .\.venv\Scripts\python.exe -m pytest tests/api tests/test_db_initialization.py -v
    git diff --check
    git add -- lightweight-stock-analysis/backend/app/main.py lightweight-stock-analysis/backend/app/cli.py lightweight-stock-analysis/backend/app/api lightweight-stock-analysis/backend/tests/api lightweight-stock-analysis/backend/tests/test_db_initialization.py
    git commit -m "feat(lsa): expose persistent workflow api contracts"

---

### Task 10: 验证崩溃恢复、独立性和全后端门

**Files:**

- Create: lightweight-stock-analysis/backend/tests/integration/test_crash_recovery.py
- Create: lightweight-stock-analysis/backend/tests/architecture/test_runtime_independence.py
- Modify: lightweight-stock-analysis/backend/tests/api/test_contract_snapshot.py
- Modify: lightweight-stock-analysis/backend/tests/api/fixtures/openapi-approved.json
- Modify: lightweight-stock-analysis/backend/README.md

- [ ] **Step 1: 写进程退出点和契约 RED 测试**

用 subprocess 与唯一 tmp runtime 覆盖四个退出点：artifact 已写/batch 未提交，batch 提交前，batch 提交后/status 前，target status transaction 前。重启后断言无重复 observation/score/candidate，已提交 checkpoint 不重做，未提交 batch 可重做，旧 fence 不能写。

独立性测试在父 repo 外复制后 import app，清除 PYTHONPATH/NODE_PATH，所有运行时写入都在 tmp path。全套后端测试继承 Plan 01 `tests/conftest.py`：每测试唯一 SQLite/cache/import/export/secrets/artifact 目录，默认禁止 socket，网络测试只显式允许 loopback，工作区前后 write manifest 发现 allowlist 外修改即失败。Task 10 只对 Task 9 已手写批准的 OpenAPI fixture 做规范化器/非语义字段修正；固定 endpoint、method、schema required/nullability、CandidateQuery/FinalRankingPage、scope、端点专用 Accepted response、Idempotency-Key 和 preflight 三字段，不从实现重新基线。

- [ ] **Step 2: 运行 RED**

Run:

    .\.venv\Scripts\python.exe -m pytest tests/integration/test_crash_recovery.py tests/architecture/test_runtime_independence.py tests/api/test_contract_snapshot.py -v

Expected: 至少一个退出点或契约 snapshot 在未加最终 wiring 时失败。

- [ ] **Step 3: 做使系统门通过的最小修正**

不改公式、不改已批准 API；只修复崩溃恢复中暴露的事务/fence/wiring 缺口。沿用 Task 9 在实现前手写的 OpenAPI approved fixture；这里只允许修正明确列出的非语义规范化差异，并需人工审批差异，禁止用当前实现重新生成/自批准基线。以后任何语义变更必须解释兼容性。

- [ ] **Step 4: 运行全后端门并提交**

Run:

    .\.venv\Scripts\python.exe -m pytest tests/integration tests/architecture -v
    .\.venv\Scripts\python.exe -m pytest tests/api
    .\.venv\Scripts\python.exe -m pytest
    .\.venv\Scripts\python.exe -m compileall -q app
    git diff --check
    git add -- lightweight-stock-analysis/backend/tests/integration lightweight-stock-analysis/backend/tests/architecture lightweight-stock-analysis/backend/tests/api lightweight-stock-analysis/backend/README.md
    git commit -m "test(lsa): verify workflow recovery and api isolation"

阶段三完成条件：全部 API 操作通过持久化资源和 job 完成；旧 runner、迟到 AI、重放请求和 cancel/freeze 竞态都无法改写已冻结结果；`pytest tests/api` 和全量 pytest 通过，且未对任何非临时数据库执行迁移。
