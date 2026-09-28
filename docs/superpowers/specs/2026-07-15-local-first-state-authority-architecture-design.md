# 本地优先状态权威与模块化单体架构设计

- 更新日期：2026-07-15
- 状态：交互设计已确认；书面规格待用户复核；实现未开始
- 选定方向：领域模块化单体 + 业务状态 SQLite 权威 + 零破坏渐进迁移

## 1. 决策摘要

`super` 继续保持本地优先的模块化单体，不在当前阶段拆微服务，也不引入 Postgres、Redis 或云队列。架构演进的第一目标是消除 Memory、JSON 与 SQLite 对同一业务状态的竞争解释，建立每类状态唯一、可测试、可恢复的写入权威。

目标形态：

```text
React Console / Stable REST + SSE / Legacy Adapters
  -> Application Command + Query Services
  -> Domain Modules and Explicit Ports
  -> Canonical SQLite for queryable business state
  -> Transactional materialization outbox
  -> JSON artifacts / derived caches / SSE refresh

In-process executor or Local Worker
  -> same application port
  -> same domain state machine
  -> same transaction and concurrency guards
```

业务状态主要以 SQLite 为权威；JSON 退为可导出的 artifact、兼容导入源或可重建派生物；内存只做可重建缓存。Secret、静态 manifest 等状态保留各自更合适的权威来源，不强制迁入 SQLite。

迁移按领域独立过闸。任何领域在 shadow compare、兼容合同、恢复测试或安全边界未通过时，都保持原权威模式，不影响其他领域和默认 in-process 路径。

## 2. 已验证的当前架构

### 2.1 产品与部署边界

- 产品是本地量化研究与模拟交易控制台，前端为 React，后端为 FastAPI。
- 默认执行路径是 in-process；`ANALYSIS_EXECUTION_MODE=worker` 时可使用本地 SQLite analysis worker。
- 当前安全边界保持 `simulation_only=true`、`is_real_trade=false` 和 `SIM_*`，不连接券商，不提供真实下单能力。
- API、浏览器 smoke 和数据闭环已围绕 portfolio、analysis run、SignalOps、backtest、research、case、knowledge、evaluation 建立可追踪 ID 链。

### 2.2 当前状态权威分布

| 状态类别 | 当前主要来源 | 当前问题 | 目标方向 |
| --- | --- | --- | --- |
| Portfolio / holdings | SQLite | 权威相对清晰 | 保持 SQLite 权威 |
| Backtest / Research / Case / Knowledge / Evaluation | SQLite | 仍需守住关联 ID 和兼容字段 | 保持 SQLite 权威 |
| Analysis run detail | 内存 + `backend/app/storage/runs/*.json`，SQLite 为结构化镜像 | 重启、并发写入和镜像新旧判断复杂 | SQLite 保存完整、版本化 canonical snapshot；文件 JSON 只做 artifact |
| Analysis jobs | `analysis_jobs.json` + SQLite `analysis_jobs` 镜像 | claim、complete、reconcile 存在双源漂移风险 | SQLite / `QueueBackend` 成为权威；JSON 只读导入或诊断 artifact |
| Auto-paper runtime config | 原子写 JSON | 当前权威明确，但跨进程查询与审计有限 | 先登记为显式 JSON 权威；仅在业务需要时单独迁移 |
| Agent runtime skeleton | JSON + secret refs | 配置与密钥必须分离 | 保持配置骨架，Secret 仍由 vault 权威 |
| Secrets | 加密 vault / 部署 secret volume | 不得进入普通 snapshot 或日志 | 保持 vault 权威 |
| Route manifest / schema / defaults | 代码仓库 | 不属于运行业务状态 | 保持代码权威 |
| 内存缓存、导出包、JSON artifacts | 派生状态 | 不能参与新旧权威竞争 | 允许从权威状态重建 |

### 2.3 相关现有计划

- `docs/NEXT_DEVELOPMENT_PLAN.md` 已定义研究闭环、浏览器 E2E 和本地 SQLite worker 平台化。
- `docs/EXTERNAL_WORKER_QUEUE_DESIGN.md` 已定义 `QueueBackend`、lease、fencing、DLQ 和未来 Postgres 适配方向。
- 本设计与上述计划的关系是：先收敛本地状态权威和模块边界；未来外部队列只能替换执行端口，不能重新制造“队列状态与业务真相双权威”。

## 3. 目标与成功标准

### 3.1 目标

- 每类状态都能明确回答：谁可以写、写在哪里、谁只读、谁可重建。
- API、Worker、后台任务和兼容路由调用同一 Application Service，不各自实现生命周期。
- SQLite 事务成功后才宣布业务状态变化；事务失败不得以内存成功兜底。
- JSON、缓存或 SSE 更新失败时保留 SQLite 真相，并通过可追踪修复流程恢复派生物。
- 旧 API、路由、字段、ID、历史数据和默认 in-process 行为零破坏兼容。
- 每个领域可独立进入 `legacy -> shadow -> sqlite`，可独立停止或回滚。
- 新写入不再产生 legacy fallback；历史 fallback 必须带来源与原因。

### 3.2 成功标准

- 目标领域的所有写入都经过唯一 Repository / Application Port。
- shadow 模式在临时数据库和代表性运行库副本上不存在未解释差异。
- 进程重启、Worker 中断、JSON artifact 删除和缓存丢失后，可从权威源恢复。
- revision 冲突、重复请求、lease 回收和迟到 Worker 写入均有失败路径测试。
- 旧 API 和前端 nullable 类型保持兼容，缺失值不被伪装成零或成功。
- strict-auth、session 持久化、模拟交易边界和敏感日志规则不回退。

## 4. 非目标

- 本阶段不拆微服务，不引入 Postgres、Redis、SQS 或其他外部 broker。
- 不采用事件溯源，不一次性重写所有 store、route 或前端页面。
- 不执行生产迁移；只生成 additive migration、测试并说明影响。
- 不把 Secret、静态 manifest、默认配置或所有 JSON 强制迁入 SQLite。
- 不改变研究、SignalOps、Backtest 或安全门禁的业务语义。
- 不新增券商连接、真实订单、自动实盘交易或收益承诺。
- 不借架构演进重做无关 UI、视觉系统或导航结构。

## 5. 方案比较

### 5.1 方案 A：统一状态门面

在 Memory、JSON 和 SQLite 前增加 State Facade 和 Reconciler，对调用方隐藏现有双写与新旧判断。

优点：改动最小，短期风险最低。缺点：只隐藏双源，不能从根因消除漂移；调和逻辑会成为永久复杂度。适合作为迁移手段，不适合作为终局。

### 5.2 方案 B：领域模块化单体，选定

通过 Application Service、Repository Port 和明确领域边界，把可查询业务状态收敛到 SQLite。JSON、缓存和 SSE 成为事务后的派生物；in-process 与 Worker 共用同一端口。

优点：符合本地优先、低运维和渐进扩展目标；可以按领域迁移并保持 API 兼容。代价：需要分阶段引入端口、shadow compare、权威切换与旧写入退役。

### 5.3 方案 C：本地事件溯源

所有变化先写 append-only event store，再投影出 run、job、research 和 audit read model。

优点：审计与重放能力最强。缺点：迁移风险、认知成本和运维复杂度最高，且与零破坏和当前产品规模不匹配。因此不采用。

## 6. 目标架构

### 6.1 稳定入口层

- React 控制台继续消费现有 REST、SSE 和路由合同。
- FastAPI routes 只负责认证、schema 校验、HTTP 映射和调用 Application Service。
- legacy route、legacy Agent ID 和 legacy API namespace 通过 adapter 映射到 canonical command/query。
- legacy adapter 不拥有业务状态，不执行独立写入，不把旧字段反向写入新 run。

### 6.2 应用编排层

每个领域暴露明确的 command/query service：

- Command Service：校验幂等键和 revision，执行领域规则，建立事务边界，返回 typed outcome。
- Query Service：从 canonical repository 读取，组合兼容字段和只读视图，不执行隐式修复写入。
- Repository Port：隐藏 SQLite 实现，供 API、in-process executor、Worker 和测试共同调用。
- Materialization Port：消费事务 outbox，生成 JSON artifact、刷新缓存并触发 SSE。

Application Service 不直接依赖全局内存字典或散落文件路径。旧函数可在迁移期作为 port adapter 存在，但不得被新调用方绕过。

### 6.3 领域模块

目标模块边界：

| 模块 | 责任 | 主要依赖 | 不负责 |
| --- | --- | --- | --- |
| Portfolio | 快照、持仓、导入关联 | SQLite repository | analysis run 生命周期 |
| Analysis + Jobs | run、DAG、job、执行状态与 artifact 索引 | Portfolio contract、QueueBackend、SQLite | Research verdict 规则 |
| Research + Backtest | backtest、research loop、evidence、verdict | Analysis run reference、SQLite | SignalOps 执行生命周期 |
| SignalOps | 模拟信号、paper order、position、kill switch | Analysis evidence、SQLite | 真实交易 |
| Config + Audit | 运行配置骨架、版本、权限审计、状态权威诊断 | vault refs、SQLite、代码 manifest | 保存明文 Secret |

模块通过 ID 和显式 contract 交互。跨模块关联必须使用 canonical ID，不直接访问对方内部表、JSON 文件或内存字典。

### 6.4 状态权威注册表

新增代码级只读注册表，至少包含：

```text
domain
entity_type
write_owner
canonical_store
derived_stores
shadow_targets
migration_mode          # legacy | shadow | sqlite
legacy_import_policy
recovery_strategy
```

注册表是架构守卫和 Backend Status 只读诊断的输入，不是第二份业务数据库。测试必须断言每个被管理实体只有一个逻辑 `write_owner`；`shadow_targets` 只接收校验副本，不拥有状态，也不能被正常读取路径选为权威。

### 6.5 Canonical SQLite 与 versioned snapshot

- 查询、关联、状态机、幂等与审计索引继续使用关系表。
- Analysis run 的完整 canonical detail 写入 SQLite 内的 versioned snapshot，包含 `schema_version`、`revision`、`checksum` 和 snapshot payload。
- 文件系统 `runs/*.json` 由 canonical snapshot 生成，仅作为 export/debug artifact。
- 历史 JSON 首次读取时通过幂等 importer 写入 SQLite，并记录 import ledger、源 checksum 和导入版本。
- importer 不覆盖更新的 canonical revision，不从 artifact 反向推断“谁更新”。

### 6.6 Transactional materialization outbox

迁移领域在同一 SQLite 事务中写入：

1. 业务状态；
2. revision / audit；
3. `state_materialization_outbox` 记录。

事务提交后，materializer 幂等生成 JSON artifact、刷新派生缓存并发布 SSE。派生步骤失败时 outbox 保留 pending/failed 状态、错误分类和重试信息；不得回滚已经提交的业务状态，也不得把文件系统写入放在持锁事务中。

### 6.7 执行扩展端口

- 默认 in-process 路径保持不变。
- Local Worker 和未来外部 Worker 只能调用同一 Application Port。
- analysis job 的 queue 语义复用 `docs/EXTERNAL_WORKER_QUEUE_DESIGN.md` 定义的 `QueueBackend`，不再新增平行 Queue Store 抽象。
- 业务结果落库校验 `(run_id, attempt, worker_id)` fencing token；lease 回收后的迟到写入被拒绝并记录审计。

## 7. 数据流

### 7.1 Command 写入流

```text
HTTP / Worker command
  -> auth + role + schema + idempotency validation
  -> Application Command Service
  -> Domain state machine + revision CAS
  -> SQLite transaction
       - canonical business state
       - audit / revision
       - materialization outbox
  -> commit
  -> artifact/cache/SSE materialization
  -> typed response with canonical revision and any additive warning
```

步骤在 commit 前失败时，不返回成功，不留下半成品。commit 后派生失败时，响应和只读诊断必须显示 degraded/warning 与修复状态。

### 7.2 Query 读取流

```text
HTTP query
  -> Query Service
  -> canonical SQLite repository
  -> compatibility field mapper
  -> response
```

只有历史记录在 canonical store 缺失时才允许调用幂等 legacy importer。新写入一旦进入 sqlite 模式，不得回退到 JSON 或内存读取结果。

### 7.3 Worker 流

```text
QueueBackend claim
  -> Application Command Service
  -> heartbeat / cancel observation
  -> canonical transaction with fencing
  -> complete / fail / requeue / dead letter
```

Worker 不直接修改 run JSON、全局 `runs_store` 或绕过 Repository Port。

## 8. 错误处理、恢复与并发

### 8.1 失败语义

| 失败点 | 权威状态 | 外部语义 | 恢复方式 |
| --- | --- | --- | --- |
| schema / domain validation | 无变化 | 4xx typed error | 修正输入，不自动重试 |
| revision / fencing 冲突 | 原状态不变 | `409 Conflict` | 刷新权威状态；记录 stale/late write audit |
| SQLite 不可写或事务回滚 | 无新状态 | `503` 或 typed storage error | 仅对明确 transient 错误有限重试；不得以内存成功兜底 |
| JSON、缓存或 SSE 失败 | SQLite 已成功 | additive warning/diagnostic，不静默声称派生物完整 | outbox repair 幂等重建 |
| 上游行情或 LLM 超时 | 记录阻断原因 | `BLOCKED` / `NETWORK_TIMEOUT` | 降级结论，允许受控重试 |
| shadow mismatch | 旧源继续权威 | `CUTOVER_BLOCKED` 只读诊断码，不改变业务状态枚举 | 记录 diff，禁止切换 |

### 8.2 幂等与并发护栏

- Command 使用 `idempotency_key` 和数据库唯一约束，重复请求返回同一结果。
- 可变实体使用 revision CAS；旧 revision 写入以冲突拒绝。
- Worker 使用 `(run_id, attempt, worker_id)` fencing；非持有者和迟到写入拒绝。
- SQLite 保持短事务、WAL / busy timeout 和 CAS claim；事务内禁止调用行情、LLM 或文件 I/O。
- retry 只覆盖明确 transient 分类，设置上限与退避；认证、权限、schema、业务阻断和永久错误不自动重试。
- 取消先于 lease reclaim 判断，避免回收吞掉 `CANCEL_REQUESTED`。

### 8.3 安全与日志

- 新写入口沿用 strict-auth、role gate 和审计。
- 如果触及 auth、session、cookie 或 middleware，必须检查 cookie name、sameSite、secure、domain、path 和客户端/服务端 token 来源，并更新 session 持久化测试。
- provider 错误体可以保留有用原因，但必须脱敏 `sk-`、`Bearer`、token、secret 和敏感请求体。
- 禁止过宽 try/catch；每个降级必须有 typed reason、日志和用户可见状态。

## 9. 零破坏迁移策略

### 9.1 领域级模式

每个目标领域有独立迁移模式：

```text
legacy  # 旧源权威，行为完全保持现状
shadow  # 旧源是唯一逻辑权威；SQLite 只接收校验副本并比较，不改变读取语义
sqlite  # SQLite 权威；旧源只做单向镜像或历史导入
```

模式切换必须是配置显式行为，不根据文件时间戳、内存是否存在或异常路径自动推断。

### 9.2 五阶段迁移

#### Phase 0：冻结与观测

- 建立状态权威注册表、owner guard、legacy fallback 和 mismatch 只读计数。
- 记录当前 API、route、ID、schema、auth、simulation boundary 和存储基线。
- 不修改写入权威，不写当前运行库样例数据。

退出条件：每类目标状态都有唯一 owner、canonical store、派生物和恢复策略。

#### Phase 1：端口封装

- 引入 Application Service 和 Repository / QueueBackend Port。
- 旧实现作为 adapter，行为和权威保持不变。
- API、Worker 和测试不再直接调用散落 store、JSON 文件或全局内存。

退出条件：调用方只依赖端口；现有合同测试和默认 in-process 路径通过。

#### Phase 2：SQLite shadow 写入

- 旧源继续权威；SQLite 写入只用于比较。
- 比较 canonical fields、ID、revision、状态机、关联关系和 checksum。
- mismatch 必须带字段级 diff、来源和可复现输入。

退出条件：目标测试集、临时库和代表性运行库副本没有未解释 mismatch。

#### Phase 3：逐领域权威切换

- 目标领域切到 `sqlite`；Query Service 以 SQLite 为唯一新记录来源。
- JSON 仅单向生成；历史缺口通过幂等 importer 补齐。
- 保留完整验证周期的显式回退开关和旧格式镜像，但镜像不参与竞争判断。

退出条件：新写入零 legacy fallback；重启、Worker、浏览器和恢复检查通过。

#### Phase 4：旧写入退役

- 停止旧源写入和双向 reconciliation。
- 保留旧 API 映射、历史 importer 和 JSON export。
- 删除已经没有调用方的旧写函数、时间戳调和逻辑和过渡开关。

退出条件：全量验证通过，旧写路径静态 guard 通过，开发日志记录回滚点与剩余风险。

### 9.3 建议迁移波次

1. **Wave 0：权威注册表与只读守卫。** 不改变业务数据；建立 owner、fallback、mismatch、repair 和 stale-write 诊断。
2. **Wave 1：analysis_jobs。** 与外部 Worker 设计的 `QueueBackend` Phase B 对齐，让 SQLite 成为本地 job 权威，JSON 只做历史导入或诊断 artifact。
3. **Wave 2：analysis run detail。** 把完整、版本化 run snapshot 迁入 SQLite；文件 JSON 改为可重建 artifact。
4. **Wave 3：残余业务状态审计。** 只迁移确实需要跨进程查询、关联或审计的状态；显式保留合理的 JSON / vault / code 权威。
5. **Wave 4：删除旧调和逻辑。** 在兼容和恢复证据充分后逐项退役，不做全仓一次性清理。

本设计是全局架构合同；每个 wave 单独形成实现计划、红绿验证和提交，不把所有 wave 混成一个实施包。

## 10. 测试设计

### 10.1 固定红绿顺序

每个 wave 必须按下列顺序执行：

1. 收紧一个会在旧实现上失败的 smoke、test 或 static guard；
2. 做最小、高置信度实现；
3. 运行聚焦检查；
4. 运行受影响的跨模块、浏览器和兼容检查；
5. 记录改动、原因、命令结果、当前运行库未污染证明和剩余风险。

### 10.2 五层测试矩阵

| 层级 | 必测内容 |
| --- | --- |
| 领域契约 | Repository / Service contract、幂等、revision、nullable 兼容、业务失败路径 |
| 存储集成 | 临时 SQLite、additive migration、事务回滚、DB locked、artifact/cache repair |
| 并发与 Worker | claim、heartbeat、cancel、lease reclaim、fencing、重启、迟到写入 |
| API 与浏览器 | 旧 route/field/deep link、strict-auth、session 持久化、warning 和 blocker 可见性 |
| 迁移演练 | 只读运行库副本、ID/计数/hash 对账、切换、回滚、再次切换 |

### 10.3 权威切换验收门

一个领域从 `shadow` 切到 `sqlite` 前必须同时满足：

- 没有未解释 shadow mismatch。
- 旧 API、route、字段、nullable 类型和 canonical ID 保持兼容。
- 新写入不会触发 legacy fallback；历史 fallback 有明确 imported 来源。
- 重启、Worker 中断、artifact 删除和缓存丢失可恢复。
- revision、idempotency、fencing、timeout、retry 和 cancel 失败路径有测试。
- `simulation_only=true`、`is_real_trade=false`、`SIM_*`、strict-auth 和敏感日志边界不回退。
- 测试只使用 `.tmp` 或运行库只读副本，当前 `storage/tianyuan_quant.db` 未被写入样例数据。
- fallback、mismatch、repair backlog 和 stale write rejection 有只读诊断。

### 10.4 验证命令族

实现阶段按实际改动选择并记录：

```powershell
pnpm lint
pnpm test
pnpm typecheck
pytest tests/api

npm.cmd run test:backend -- <targeted paths>
npm.cmd run test:backend
npm.cmd run smoke:analysis-worker
npm.cmd run smoke:research-closure:browser
npm.cmd run smoke:strict-auth-browser:matrix
npm.cmd run validate:premerge
git diff --check
```

若本机没有 pnpm，在不修改 lockfile 的前提下使用仓库现有 `npm.cmd run lint`、`npm.cmd run test`、`npm.cmd run typecheck` 等价脚本，并在开发日志中记录差异。若 `tests/api` 不是当前 checkout 的真实测试路径，使用现有 `backend/tests` API 测试路径和 `npm.cmd run test:backend -- ...` 包装器，并记录映射。

## 11. 可观测性

现有 Backend Status 增加只读、additive 的 `stateAuthority` 摘要，至少展示：

- 每个领域的 migration mode 和 canonical store；
- legacy fallback 读取次数及最近原因；
- shadow mismatch 数与最近 diff 引用；
- materialization outbox pending/failed 数；
- stale/late write rejection 数；
- importer 成功、跳过、冲突和失败数。

诊断字段不包含 Secret、token、完整敏感 payload 或可反推密钥的材料。前端字段缺失时显示未配置或不可用，不伪装为零。

## 12. 兼容策略

- API schema 只做 additive 变化；新增字段必须 optional，并同步 Pydantic model、前端类型、调用方和测试。
- legacy route 和 namespace 继续映射到 canonical service，并保留 query/hash/run ID 上下文。
- legacy Agent ID 和旧字段只做读取兼容或从 canonical state 回填，不成为新写入权威。
- 历史 JSON 通过幂等 importer 导入；import ledger 防止重复导入。
- rollback 通过领域级模式开关完成，不通过手工改库、删除文件或自动猜测权威完成。

## 13. 风险与缓解

- **影子双写变成永久架构：** 每个 wave 定义退出门；Phase 4 删除旧写入和双向 reconciliation 是完成条件。
- **SQLite 锁竞争：** 短事务、批量限制、WAL/busy timeout；外部 I/O 在事务外执行。
- **迟到 Worker 污染新状态：** revision + attempt + worker fencing 覆盖 job 和 run 结果写入。
- **旧 JSON 导入覆盖新数据：** importer 校验 revision、schema_version 和 checksum，只允许创建缺失 canonical record。
- **API 空值回归：** additive optional 字段、前端 null/undefined 兜底和兼容合同测试。
- **缓存失效遗漏：** 缓存只由 materializer 更新，key 变化必须同步失效合同与测试；不得只清单一进程内缓存而遗留其他派生副本。
- **认证历史问题复发：** auth 相关 wave 必须覆盖 cookie 和 token 来源一致性及 session 持久化。
- **敏感信息进入诊断：** 统一脱敏、字段 allowlist 和日志测试。
- **范围过大：** 全局设计按 Wave 0–4 拆分，每次只实施一个可独立验收的 wave。

## 14. 每个 Wave 的完成定义

- 先说明改了什么、为什么改和未改什么。
- 聚焦 guard 在旧实现上可失败，并在新实现上通过。
- 目标领域只有一个 write owner；新调用方不能绕过 Application Port。
- API、route、ID、nullable 字段和默认 in-process 行为保持兼容。
- 失败路径覆盖竞态、重复、重试、超时、取消、恢复和派生物失败。
- 没有未清理 debug log、过宽 try/catch 或敏感信息输出。
- 若生成 migration，只提交 migration 与测试，不执行生产迁移。
- 记录验证命令、结果、临时数据位置、当前运行库未污染证明和剩余风险。
- 更新 `docs/DEVELOPMENT_LOG.md`，留下下一 wave 的明确入口。

## 15. 书面规格后的实施边界

用户复核本规格后，只为 **Wave 0：权威注册表与只读守卫** 编写第一份实施计划。后续 Wave 1–4 在前一 wave 验收完成后分别设计、计划和实施，不自动扩大到全仓重构。
