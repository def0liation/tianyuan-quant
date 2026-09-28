# 轻量化防御性股票分析阶段二：数据权威、Gate 0 与不可变快照 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 在阶段一纯领域内核之下建立类型化 SQLite 数据平面，完成证券池权威、来源追溯、Provider 契约、Gate 0 能力分类、特征预聚合和原子 READY data_snapshot。

**Architecture:** Provider 只输出规范 observation，不计算分数；内容寻址 artifact 保留原始依据，类型化 observation 保留口径和时间语义。Preflight 用独立 universe authority 作分母并产生 `capability_state + acceptance_mode` 双字段决策。Snapshot 先在 staging 中可恢复同步，再在单事务中冻结 universe、observation 选择、feature、质量状态和 manifest hash；scan 只能读 READY 快照。

**Tech Stack:** Python 3.12、SQLAlchemy 2 async、aiosqlite、Alembic、Pydantic v2、httpx、PyYAML、pytest/pytest-asyncio、SQLite WAL。

**Spec:** lightweight-stock-analysis/docs/superpowers/specs/2026-08-24-lightweight-defensive-stock-analysis-design.md

## Global Constraints

- 必须先完成阶段一；本计划复用 `RuleBook` 和评分 feature 类型，并在本阶段唯一拥有 canonical 市场/observation DTO；Provider、repository、Gate 0 和阶段三只能引用这些 DTO，不复制定义。
- 实施前用 superpowers:using-git-worktrees 创建隔离 worktree，并确认阶段一全部领域门通过。
- 默认 production provider registry 为空；本阶段不实现 Tushare、HKEX 或任何实时适配器，因此完成后真实能力仍是 `NOT_CONFIGURED`。
- fixture/fake provider 只能在 `LSA_ENV=test` 且唯一临时数据库中注册；只能产生 `acceptance_mode=TEST_ONLY`。
- `LIVE_READY` 不够；真实就绪必须同时满足 `capability_state=LIVE_READY`、`acceptance_mode=LIVE`、`synthetic=false`、报告未过期。
- 不允许 provider 自己的结果同时作唯一分母；每市场必须绑定不可变 `universe_reference_snapshot`。
- announcement_date 晚于 as_of_date 的数据不得进入 feature；只有报告期、没有公告日的记录不得用于正式评分。
- 同一时间序列默认不跨 provider 拼接；只有已提交且有完整审核轨迹的导入序列可例外。
- `0` 仅表示来源明确报告零，`NULL` 表示缺失；不得在 repository 或 feature builder 中互换。
- 迁移只生成并在每测试独立的临时 SQLite 上 upgrade/downgrade；不得对开发库或生产库执行 upgrade。
- 用精确路径暂存本子应用文件，不使用 `git add -A`，不纳入父工作区用户修改。
- 本计划中 `.\.venv\Scripts\python.exe` 命令从 `lightweight-stock-analysis/backend` 执行；以 `git` 开头的暂存/提交命令从父仓库根目录执行。
- Alembic 有意放在独立子应用的 `backend/alembic/`，不创建第二套 `app/db/migrations/`；revision 必须保持单一线性 head。

## Frozen Cross-Plan Contracts

```python
class CapabilityState(StrEnum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    LIVE_PARTIAL = "LIVE_PARTIAL"
    LIVE_READY = "LIVE_READY"

class AcceptanceMode(StrEnum):
    LIVE = "LIVE"
    TEST_ONLY = "TEST_ONLY"

@dataclass(frozen=True, slots=True)
class Gate0Decision:
    capability_state: CapabilityState
    acceptance_mode: AcceptanceMode
    synthetic: bool
    market_results: Mapping[Market, MarketCapability]
    gaps: tuple[CapabilityGap, ...]
    gate0_policy_hash: str
    report_hash: str
    expires_at: datetime

@dataclass(frozen=True, slots=True)
class ReadySnapshotRef:
    snapshot_id: UUID
    as_of_date: date
    markets: frozenset[Market]
    acceptance_mode: AcceptanceMode
    manifest_hash: str
    rule_compatible_feature_version: str
```

Plan 3 的 preflight API 必须原样返回 `capability_state`、`acceptance_mode`、`synthetic`；不能从单一状态推断另两个字段。

`Market`、MarketCapability、CapabilityGap、LicenseDeclaration、SecurityMasterRecord、AnnualFinancialObservation、DailyMarketObservation、BenchmarkTotalReturnObservation、FxRateObservation、CorporateActionObservation 和 RegulatoryCheckObservation 的唯一公开定义分别位于 `app/domain/market_data.py` 与 `app/domain/observations.py`。所有类型均为 frozen/slots dataclass 或严格 enum；Provider Pydantic 边界解析后立即转换到这些类型，其他计划不得重新声明同名 DTO。`LicenseDeclaration` 冻结 provider_id、declaration_version、allowed_usage、redistribution_boundary、source_locator、effective_from、reviewed_at/reviewer；`hash_license_declaration` 对该严格 DTO 的 canonical JSON 求 SHA-256，不接收 token/key 或任意扩展字段。

## File Structure

| File | Responsibility |
|---|---|
| backend/app/db/base.py, session.py, uow.py | metadata、SQLite pragma、async session 和短事务边界 |
| backend/app/db/models/sources.py | data_sources、source_artifacts |
| backend/app/db/models/securities.py | entity、listing、A/H mapping、industry、reference universe |
| backend/app/db/models/observations.py | 财务、行情、公司行动、风险、冲突类型化行 |
| backend/app/domain/market_data.py, observations.py | 跨 Provider、持久层、Gate 0 和工作流的唯一 canonical DTO |
| backend/app/db/models/preflights.py | preflight、市场结果、coverage、readback sample |
| backend/app/db/models/snapshots.py | data_snapshot、batch、universe、input observation、feature snapshot |
| backend/app/db/repositories/*.py | 按 aggregate 封装类型化读写，service 不散落 SQL |
| backend/app/storage/artifacts.py | 内容寻址、原子写和读回校验 |
| backend/app/providers/contracts.py | universe/security/financial/price/action/risk provider Protocol |
| backend/app/providers/errors.py, resilience.py, registry.py, cache.py | 稳定错误、有界重试、环境隔离注册和不可用于正式评分的 stale 缓存 |
| backend/app/domain/gate0.py | coverage 纯计算、确定样本和能力分类 |
| backend/app/services/preflight.py | universe authority 与 provider 预检编排 |
| backend/app/services/snapshot_features.py | 截止日、口径、A/H 和统计特征预聚合 |
| backend/app/services/data_snapshots.py | snapshot 创建、batch 幂等提交和 prepared freeze |
| backend/app/services/snapshot_sync.py | provider I/O 与 staging 协调，不推进 job 状态 |
| backend/app/services/workflow_context.py | 由调用层实现的 checkpoint 与原子 terminal commit 端口 |
| backend/alembic/versions/20260824_01_market_authority.py | 来源、证券主数据和 reference universe |
| backend/alembic/versions/20260824_02_typed_observations.py | 类型化 observation 和冲突 |
| backend/alembic/versions/20260824_03_gate0_preflight.py | Gate 0 报告和防提升约束 |
| backend/alembic/versions/20260824_04_frozen_data_snapshot.py | staging、冻结成员、输入和 feature |
| backend/tests/fixtures/providers/*.json | 显式 synthetic 的固定离线 provider 页 |
| backend/tests/performance/fixtures/manifest.json | 10,000 listing 唯一可复现性 manifest |

Alembic 常量冻结为 `lsa_01_market_authority`（down_revision=None）→`lsa_02_observations`→`lsa_03_preflights`→`lsa_04_snapshots`；每个 migration test 直接断言 revision/down_revision、单一 head 和按 01→04 upgrade/downgrade，供 Plan 03 从 `lsa_04_snapshots` 继续。

---

### Task 1: 建立 SQLite 边界、来源与证券池权威

**Files:**

- Modify: lightweight-stock-analysis/backend/pyproject.toml
- Modify: lightweight-stock-analysis/backend/requirements.lock
- Create: lightweight-stock-analysis/backend/alembic.ini
- Create: lightweight-stock-analysis/backend/alembic/env.py
- Create: lightweight-stock-analysis/backend/alembic/script.py.mako
- Create: lightweight-stock-analysis/backend/alembic/versions/20260824_01_market_authority.py
- Create: lightweight-stock-analysis/backend/app/db/base.py
- Create: lightweight-stock-analysis/backend/app/db/session.py
- Create: lightweight-stock-analysis/backend/app/db/uow.py
- Create: lightweight-stock-analysis/backend/app/domain/market_data.py
- Create: lightweight-stock-analysis/backend/app/domain/observations.py
- Create: lightweight-stock-analysis/backend/app/db/models/sources.py
- Create: lightweight-stock-analysis/backend/app/db/models/securities.py
- Create: lightweight-stock-analysis/backend/app/db/repositories/provider_cache.py
- Create: lightweight-stock-analysis/backend/app/db/repositories/security_master.py
- Create: lightweight-stock-analysis/backend/tests/db/test_migrations.py
- Create: lightweight-stock-analysis/backend/tests/db/test_security_master_repository.py

**Interfaces:** `create_engine(settings) -> AsyncEngine`；`session_factory(engine) -> async_sessionmaker`；canonical Market/capability/security DTO；`SecurityMasterRepository.upsert_reference_snapshot(...)`、`replace_reference_members(...)`、`read_reference(...)`；`ProviderCacheRepository.get/put`。

- [ ] **Step 1: 先写临时库 RED 测试**

`test_migrations.py` 为每个 test 创建 `tmp_path / "lsa.sqlite3"`，断言当前 revision 从 base upgrade 后表存在，downgrade 回 base 后表消失。`test_security_master_repository.py` 断言：

- CN.SSE.600000 与 HK.HKEX.00700 的 market/exchange 组合被约束。
- A/H 关联保留 source_artifact_id、confidence_status、valid_from、valid_to。
- listing 精确保留 `security_type`、board=`SSE_MAIN|SZSE_MAIN|STAR|CHINEXT|BSE|HK_MAIN|HK_GEM`、listed/delisted status、currency、listing_date/delisting_date；只有 CN/HK 合格普通股进入 reference 分母。
- entity/listing 行业映射保存 canonical taxonomy version、provider mapping version、source code、有效期与审核记录；A/H 映射保存股份类别和正值 conversion_ratio_to_entity_fully_diluted_shares。
- reference snapshot 的 scope_rule、member_count 和 canonical members hash 不可在提交后更改。
- provider 多出的未知证券不进入 reference 分母。
- `data_sources` 保存 provider/version/parser、account permission、data class、credential_id_hash 和 license_declaration_hash；license hash 必须是已解析 LicenseDeclaration 的 canonical hash，缺失或引用不同 provider 的声明时拒绝注册。
- `provider_cache_entries` 使用完整 cache key 唯一约束，只能引用不可变 source_artifact，且 migration upgrade/downgrade 与 repository round-trip 均有测试。

- [ ] **Step 2: 运行 RED**

Run:

    .\.venv\Scripts\python.exe -m pytest tests/db/test_migrations.py tests/db/test_security_master_repository.py -v

Expected: FAIL because `app.db` and Alembic revision do not exist.

- [ ] **Step 3: 实现最小 schema 与 repository**

pyproject 追加 `aiosqlite>=0.20,<1`。SQLAlchemy metadata 使用稳定 naming convention；每个 SQLite connection 启用：

```python
cursor.execute("PRAGMA foreign_keys=ON")
cursor.execute("PRAGMA journal_mode=WAL")
cursor.execute("PRAGMA busy_timeout=5000")
```

`universe_reference_snapshots` 保存 market、authority_source_id、as_of_date、scope_rule_json、member_count、content_hash、created_at；`universe_reference_members` 唯一键是 `(reference_snapshot_id, listing_id)`。内容哈希使用按 listing_id 排序的 canonical JSON，不使用数据库自然顺序。`data_sources` 按上面的 descriptor/license 字段建列并约束 64 位哈希。migration 01 同时创建 `provider_cache_entries` 与完整唯一 cache key；Task 3 只实现使用该 repository 的 provider cache policy，不再创建表。

- [ ] **Step 4: 运行 GREEN 并提交**

Run:

    .\.venv\Scripts\python.exe -m piptools compile pyproject.toml --extra test --generate-hashes --output-file requirements.lock
    .\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.lock
    .\.venv\Scripts\python.exe -m pytest tests/db/test_migrations.py tests/db/test_security_master_repository.py -v
    git diff --check
    git add -- lightweight-stock-analysis/backend/pyproject.toml lightweight-stock-analysis/backend/requirements.lock lightweight-stock-analysis/backend/alembic.ini lightweight-stock-analysis/backend/alembic lightweight-stock-analysis/backend/app/db lightweight-stock-analysis/backend/tests/db
    git commit -m "feat(lsa): persist market authority and security master"

---

### Task 2: 保存不可变 artifact 与类型化 observation

**Files:**

- Create: lightweight-stock-analysis/backend/alembic/versions/20260824_02_typed_observations.py
- Modify: lightweight-stock-analysis/backend/app/domain/observations.py
- Create: lightweight-stock-analysis/backend/app/db/models/observations.py
- Create: lightweight-stock-analysis/backend/app/db/repositories/observations.py
- Create: lightweight-stock-analysis/backend/app/storage/artifacts.py
- Create: lightweight-stock-analysis/backend/tests/db/test_observation_repository.py
- Create: lightweight-stock-analysis/backend/tests/db/test_artifact_store.py

**Interfaces:** `ArtifactStore.put(stream, metadata) -> StoredArtifact`；`ArtifactStore.open_verified(artifact_id)`；`ObservationRepository.append_*`；`select_as_of(...)`。

- [ ] **Step 1: 写 artifact/observation RED 测试**

覆盖：同内容重复写返回同 artifact_id；读回时内容被篡改则失败；用户文件名不参与磁盘路径；财务明确零与缺失分开；修订版不覆盖旧版；`announcement_date > as_of_date` 不可被 `select_as_of` 选中。对公司行动断言 action_type、announcement/effective/completion date、amount/share class/status；对监管检查断言 `HIT|CLEAR`、authority、covered_through_date、queried_at 和 artifact；对 metric conflict 候选断言 metric/subject/period、normalized value/unit/currency/accounting basis、observation/source/artifact IDs 全部读回。跨币种值逐字段读回 original value/currency/unit、normalized value/currency/unit、fx_rate、fx_rate_observation_id/source/artifact、conversion_date；缺任何汇率追溯时不能形成 READY feature。ArtifactStore.open_verified 返回必须由 `async with` 管理的只读二进制流，退出后句柄关闭。

- [ ] **Step 2: 运行 RED**

Run:

    .\.venv\Scripts\python.exe -m pytest tests/db/test_artifact_store.py tests/db/test_observation_repository.py tests/db/test_migrations.py -v

Expected: FAIL on missing artifact store and observation models.

- [ ] **Step 3: 实现类型化列与索引**

`annual_financials` 保存 17 个 `Numeric(38,10)` 可空列：规格的 16 个必需字段组中，EBITDA 组用 `ebitda` 与 `depreciation_amortization` 两列表达，二者满足可推导关系时算同一个 coverage 字段组，不重复计入分母。表同时保存 entity_id、fiscal_year、announcement_date、report_period_end、source_id、artifact_id、parser_version、currency、original_unit、normalized_unit、retrieved_at。`daily_market_data` 至少保存复权/未复权收盘、复权因子、PE_TTM、总市值和完全摊薄股数，并建 `(listing_id, trade_date, source_id, parser_version)` 唯一索引。

`benchmark_mappings` 冻结 canonical benchmark、market、provider code、mapping_version、valid_from/to、source/review 信息；`benchmark_total_return_observations` 保存 mapping_id、trade_date、total_return_index_level、currency、source/artifact/parser/retrieved_at，并禁止把价格指数写入该表。`fx_rate_observations` 保存 base/quote、rate、conversion_date、source/artifact/parser/retrieved_at；`observation_value_provenance` 以 observation+field 唯一，保存原值/币种/单位、规范值/币种/单位和 fx observation 引用，使宽表每个换算字段都可审计。Task 5 的日/周/月特征只消费 canonical total-return observation，跨币种 A/H FCF yield 只消费带完整 provenance 的规范值。company actions、regulatory checks、metric conflict candidates 也按 Step 1 的精确字段建类型化表和索引，不把原始 JSON 当权威列。

artifact 先写同目录随机临时文件，fsync，再原子 rename 到 `<sha256[0:2]>/<sha256>`；目标已存在时校验长度与哈希后复用，不覆盖。

- [ ] **Step 4: 运行 GREEN 并提交**

Run:

    .\.venv\Scripts\python.exe -m pytest tests/db/test_artifact_store.py tests/db/test_observation_repository.py tests/db/test_migrations.py -v
    git diff --check
    git add -- lightweight-stock-analysis/backend/alembic/versions/20260824_02_typed_observations.py lightweight-stock-analysis/backend/app/db lightweight-stock-analysis/backend/app/storage lightweight-stock-analysis/backend/tests/db
    git commit -m "feat(lsa): preserve typed source observations"

---

### Task 3: 定义 Provider 端口、错误语义与有界重试

**Files:**

- Create: lightweight-stock-analysis/config/public-source-allowlist.yaml
- Create: lightweight-stock-analysis/backend/app/providers/contracts.py
- Create: lightweight-stock-analysis/backend/app/providers/errors.py
- Create: lightweight-stock-analysis/backend/app/providers/resilience.py
- Create: lightweight-stock-analysis/backend/app/providers/registry.py
- Create: lightweight-stock-analysis/backend/app/providers/cache.py
- Create: lightweight-stock-analysis/backend/tests/providers/fakes.py
- Create: lightweight-stock-analysis/backend/tests/providers/test_contracts.py
- Create: lightweight-stock-analysis/backend/tests/providers/test_resilience.py
- Create: lightweight-stock-analysis/backend/tests/providers/test_registry.py
- Create: lightweight-stock-analysis/backend/tests/providers/test_cache.py
- Create: lightweight-stock-analysis/backend/tests/fixtures/providers/cn_reference.json
- Create: lightweight-stock-analysis/backend/tests/fixtures/providers/hk_reference.json
- Create: lightweight-stock-analysis/backend/tests/fixtures/providers/cn_canonical_pages.json
- Create: lightweight-stock-analysis/backend/tests/fixtures/providers/hk_canonical_pages.json
- Create: lightweight-stock-analysis/backend/tests/fixtures/providers/parser_drift.json

**Interfaces:**

```python
class UniverseAuthorityProvider(Protocol):
    descriptor: ProviderDescriptor
    async def fetch_reference(self, request: UniverseRequest) -> UniverseReferencePage: ...

class SecurityMasterProvider(Protocol):
    descriptor: ProviderDescriptor
    def iter_security_master(self, request: SecurityMasterRequest) -> AsyncIterator[ProviderPage[SecurityMasterRecord]]: ...

class FinancialsProvider(Protocol):
    descriptor: ProviderDescriptor
    def iter_annual_financials(self, request: FinancialRequest) -> AsyncIterator[ProviderPage[AnnualFinancialObservation]]: ...

class PricesProvider(Protocol):
    descriptor: ProviderDescriptor
    def iter_daily_market_data(self, request: MarketDataRequest) -> AsyncIterator[ProviderPage[DailyMarketObservation]]: ...

class BenchmarkProvider(Protocol):
    descriptor: ProviderDescriptor
    def iter_total_return_benchmark(self, request: BenchmarkRequest) -> AsyncIterator[ProviderPage[BenchmarkTotalReturnObservation]]: ...

class FxRatesProvider(Protocol):
    descriptor: ProviderDescriptor
    def iter_fx_rates(self, request: FxRateRequest) -> AsyncIterator[ProviderPage[FxRateObservation]]: ...

class CorporateActionsProvider(Protocol):
    descriptor: ProviderDescriptor
    def iter_corporate_actions(self, request: CorporateActionRequest) -> AsyncIterator[ProviderPage[CorporateActionObservation]]: ...

class RegulatoryRiskProvider(Protocol):
    descriptor: ProviderDescriptor
    async def fetch_regulatory_checks(self, request: RegulatoryCheckRequest) -> tuple[RegulatoryCheckObservation, ...]: ...
```

- [ ] **Step 1: 写合约与重试 RED 测试**

测试精确覆盖：DTO `extra="forbid"`、无 score 字段、分页不丢数、单位/负号/币种/复权/日期保留；LicenseDeclaration canonical hash 对键顺序稳定，任一许可字段改变则 hash 改变，descriptor hash 缺失/不匹配/跨 provider 引用均拒绝；401/403 不重试；429 最多重试 3 次且遵循上限 30 秒的 Retry-After；timeout/5xx 使用注入 clock/random 后可确定断言的指数退避 0.25/0.5/1.0 秒加有界 jitter；parser shape drift 不回退旧成功数据。缓存键必须等于 provider_id + endpoint + canonical params + market_effective_date + parser_version；同交易日成功缓存可复用，force refresh 必须新请求，刷新失败时旧成功项只能标 STALE 展示，不能成为当次 snapshot 的 selected observation。

- [ ] **Step 2: 运行 RED**

Run:

    .\.venv\Scripts\python.exe -m pytest tests/providers -v

Expected: FAIL because provider contracts and registry are missing.

- [ ] **Step 3: 实现端口和 deny-by-default 注册**

`ProviderDescriptor` 必须包含 provider_id、provider_version、parser_version、account_permission、allowed_usage、redistribution_boundary、credential_id_hash、license_declaration_hash、`data_class=LIVE|TEST_ONLY`，绝不包含 token/key。LicenseDeclaration 的唯一配置权威与 provider allowlist 同在 `public-source-allowlist.yaml`；registry 先严格解析声明并计算 hash，再要求 descriptor 的 provider/usage/redistribution/hash 全部匹配，禁止 adapter 自报一个未受配置约束的 hash。production registry 默认无 provider；该文件首版是：

```yaml
version: 1
default: deny
license_declarations: []
entries: []
```

registry 在非 test 环境收到 TEST_ONLY provider 时抛 `TestProviderForbidden`。重试逻辑只包装单次 provider 调用，不得开数据库长事务。Provider cache 通过 Task 1 的 `ProviderCacheRepository` 读写 migration 01 已创建的 `provider_cache_entries`，只引用不可变 artifact；`CacheHit.usability` 显式区分 CURRENT 与 STALE_DISPLAY_ONLY。

- [ ] **Step 4: 运行 GREEN 并提交**

Run:

    .\.venv\Scripts\python.exe -m pytest tests/providers -v
    git diff --check
    git add -- lightweight-stock-analysis/config/public-source-allowlist.yaml lightweight-stock-analysis/backend/app/providers lightweight-stock-analysis/backend/tests/providers lightweight-stock-analysis/backend/tests/fixtures/providers
    git commit -m "feat(lsa): define isolated market data providers"

---

### Task 4: 实现 Gate 0 纯分类、报告哈希和持久化防提升门

**Files:**

- Create: lightweight-stock-analysis/backend/alembic/versions/20260824_03_gate0_preflight.py
- Create: lightweight-stock-analysis/backend/app/domain/gate0.py
- Create: lightweight-stock-analysis/backend/app/db/models/preflights.py
- Create: lightweight-stock-analysis/backend/app/db/repositories/preflights.py
- Create: lightweight-stock-analysis/backend/app/services/preflight.py
- Create: lightweight-stock-analysis/backend/app/services/workflow_context.py
- Create: lightweight-stock-analysis/backend/app/cli.py
- Create: lightweight-stock-analysis/backend/tests/domain/test_gate0.py
- Create: lightweight-stock-analysis/backend/tests/services/test_preflight.py
- Create: lightweight-stock-analysis/backend/tests/test_cli.py

**Interfaces:** `coverage_ratio`、`select_readback_sample`、`classify_gate0`、`PreflightService.create_pending(request) -> PendingPreflight`、`PreflightService.prepare_report(preflight_id) -> PreparedPreflightReport`、`PreflightWorkflow.run(ctx: PreflightExecutionContext, preflight_id) -> PreflightReport`。Task 4 同时在 workflow_context.py 定义 checkpoint/cancel/commit_preflight_report 的 PreflightExecutionContext，避免依赖未来 snapshot 类型。`create_pending` 在 API 返回 202 前冻结 request hash；workflow 只按 preflight_id 读回该请求并可从持久 checkpoint 恢复，最后调用 ctx.commit_preflight_report(prepared)，自己不推进 terminal status。Plan 03 的 PREFLIGHT handler 直接调用它。

- [ ] **Step 1: 写分母、样本和双状态 RED 测试**

每个 coverage 断言 numerator、denominator、ratio、threshold、passed 和 gap；样本严格按 `sha256(reference_snapshot_hash + listing_id)` 排序取前 10。测试覆盖规格全部门槛：98/95/95/90/85/100/85/95%，两市场各 10 个真实读回，24 小时失效。全局 `LIVE_READY` 的市场真值表固定：请求市场集合必须恰为 `{CN, HK}` 且两个 MarketCapability 都通过；CN-only 或 HK-only 即使本市场全通过也只能是 `LIVE_PARTIAL`，任一市场失败也为 `LIVE_PARTIAL`，空 registry 才是 `NOT_CONFIGURED`。测试名固定 `test_classify_gate0_cn_only_pass_is_live_partial`、`test_classify_gate0_hk_only_pass_is_live_partial`、`test_classify_gate0_requires_both_markets`，防止对请求子集直接 `all(...)` 误升。每个读回样本必须独立核对 security identity/type/board、fiscal_year/report_period_end、announcement_date、price trade_date、source/artifact/parser 与 reference member，不能只检查“请求成功”。分母契约固定为：

- SecurityMaster/Price：reference 的全部合格 listing。
- Valuation：reference 中 TTM 归母净利润为正的 listing；分子同时有正 PE_TTM、总市值、完全摊薄股数。
- PriceHistory：上市满 3 年的 reference listing；分子同时满足 Beta/回撤/下行捕获样本。
- PEHistory：当前 PE_TTM 为正且上市满 3 年的 reference listing；分子需 36 月且交易日覆盖至少 80%。
- Benchmark：CN/HK canonical total-return benchmark 两者都满足日/周/月样本才是 100%，否则 0%。
- FinancialCell：上市满 5 年的 reference entity × 5 财年 × 16 个必需字段组；明确零计有效，NULL 不计。
- Risk：reference entity；“命中”和“无命中”都是有效分子，未查/失败不是。

特别断言：

```python
decision = classify_gate0(
    synthetic_full_coverage_report,
    Gate0Thresholds.from_mapping(rules.gate0_thresholds),
)
assert decision.capability_state is CapabilityState.LIVE_READY
assert decision.acceptance_mode is AcceptanceMode.TEST_ONLY
assert decision.synthetic is True
```

repository 测试尝试把该报告持久化为 `AcceptanceMode.LIVE`，必须抛 `AssurancePromotionForbidden`。

另覆盖权限/许可失败：account_permission 不足、allowed_usage 缺分析用途、redistribution_boundary 未声明或 license hash 缺失都产生明确 gap 并阻止 LIVE_READY；被测 provider 若也是该市场唯一 universe authority，报告只能 TEST_ONLY/LIVE_PARTIAL，不能把自身输出当 LIVE 分母。空 registry 的 NOT_CONFIGURED 必须持久化并由后续 API 原样读回。

- [ ] **Step 2: 运行 RED**

Run:

    .\.venv\Scripts\python.exe -m pytest tests/domain/test_gate0.py tests/services/test_preflight.py tests/test_cli.py tests/db/test_migrations.py -v

Expected: FAIL on missing gate0 classifier and preflight revision.

- [ ] **Step 3: 实现规范报告与失效键**

RuleBook loader 先重算 `rules.content_hash` 并确认它与非空 `rules.declared_rules_content_sha256` 等值；声明缺失/不等时 Gate 0 拒绝运行。随后对 classifier semantic version、Gate0Thresholds、field set version、`rules.content_hash` 计算 `gate0_policy_hash`。每个 provider 的 license_declaration_hash 来自 registry 已验证声明；报告中的聚合 `license_declaration_hash` 对按 provider_id 排序的 `{provider_id, declaration_hash}` canonical JSON 再求 SHA-256。`report_hash` 对以下规范 JSON 字段求 SHA-256：gate0_policy_hash、reference_snapshot_id/hash、provider_config_hash、credential_id_hash、该聚合 license_declaration_hash、measured_at、expires_at、各分子/分母、确定样本，以及最终 capability_state、acceptance_mode、synthetic。测试证明规则声明校验后 policy 使用值等于 `rules.content_hash`，且任一 reference、provider config、credential id、许可声明或 policy 改变即失效；threshold/rule 更新后旧的宽松 LIVE_READY 不能在 TTL 内继续使用。

阶段二 CLI `python -m app.cli preflight --markets CN,HK --as-of 2026-08-24` 只支持空 registry 的安全诊断：输出不含凭据的 JSON `capability_state=NOT_CONFIGURED`、`acceptance_mode=LIVE`、`synthetic=false`，不创建 target/报告并以 2 退出。若检测到可运行 provider，则以 `WORKFLOW_RUNTIME_NOT_INSTALLED` 拒绝，不能绕过 execution context 直接持久化；Plan 03 Task 9 会把同一命令重接为 job-backed create→fenced runner→poll→持久报告。它不自动启用网络，真实运行留待另行凭据与联网授权。

- [ ] **Step 4: 运行 GREEN 并提交**

Run:

    .\.venv\Scripts\python.exe -m pytest tests/domain/test_gate0.py tests/services/test_preflight.py tests/test_cli.py tests/db/test_migrations.py -v
    git diff --check
    git add -- lightweight-stock-analysis/backend/alembic/versions/20260824_03_gate0_preflight.py lightweight-stock-analysis/backend/app/domain/gate0.py lightweight-stock-analysis/backend/app/db/models/preflights.py lightweight-stock-analysis/backend/app/db/repositories/preflights.py lightweight-stock-analysis/backend/app/services/preflight.py lightweight-stock-analysis/backend/app/services/workflow_context.py lightweight-stock-analysis/backend/app/cli.py lightweight-stock-analysis/backend/tests
    git commit -m "feat(lsa): classify and persist gate zero preflights"

---

### Task 5: 构建截止日安全的 entity/listing 特征快照

**Files:**

- Create: lightweight-stock-analysis/backend/app/services/snapshot_features.py
- Create: lightweight-stock-analysis/backend/app/services/observation_selection.py
- Create: lightweight-stock-analysis/backend/tests/services/test_snapshot_features.py
- Create: lightweight-stock-analysis/backend/tests/services/test_observation_selection.py

**Interfaces:** `select_observations_as_of(candidates, policy, approved_override_port) -> ObservationSelection`；`ApprovedSeriesOverridePort.get_committed(series_key, as_of_date) -> ApprovedSeriesOverride | None`；`build_snapshot_features(inputs, policy) -> tuple[FeatureSnapshot, ...]`。

- [ ] **Step 1: 写时间、口径和缺失 RED 测试**

测试使用乱序修订版和 A/H 双 listing，断言：

- 只选 as_of_date 前已公告的最新有效版本，不用未完成年度。
- 连续五年必需字段来自同 provider/会计口径；非审核跨源拼接返回 PARTIAL。
- entity 特征共享财务/行业，listing 特征分开估值/股东回报/低波动。
- CN/HK 分别使用各自 market_effective_date 和 canonical total-return benchmark。
- Beta 需要 130 个相邻 ISO 周对，下行捕获需 30 月且至少 8 个下跌月；Own PE 百分位始终使用截止日前 60 个月窗口，但至少需 36 个自然月且有效交易日覆盖 80%。加入同一证券 36 个月与 60 个月观测会产生不同百分位的回归，防止把最低覆盖误写成 lookback。
- 同行有效样本少于 10 时只执行一次配置的上级行业回退，仍不足则缺失。
- 字段来源按“授权 API > 已提交 CSV/XLSX 导入 > allowlist 公开页 > 缺失”尝试；低优先级有更晚公告日，或高优先级质量检查失败时，产生 candidate conflict，不静默覆盖。
- 只有 `ApprovedSeriesOverridePort` 返回的已提交 override，且保存每年来源/拼接原因/单位/币种/复权/审核人/时间/备注，才可跨源。Plan 02 测试使用严格 fake port（默认无 override）；Plan 03 的 ImportService 提交后实现该 port 的持久适配器，本计划不提前创建第二份 import ledger。

- [ ] **Step 2: 运行 RED**

Run:

    .\.venv\Scripts\python.exe -m pytest tests/services/test_observation_selection.py tests/services/test_snapshot_features.py -v

Expected: FAIL because snapshot feature builder is absent.

- [ ] **Step 3: 实现纯 builder 和追溯记录**

ObservationSelection 保存 selected observation ID、全部 candidate IDs、优先级、选择原因、质量检查和冲突结果。FeatureSnapshot 必须保存 subject_type、subject_id、feature_version、typed_payload、input_observation_ids、benchmark_mapping_version、industry_mapping_version、source_series_id、content_hash。builder 只读 repository 已选 observation，不访问 provider 或更新原行；ApprovedSeriesOverride 是阶段间 port/value object，Plan 03 只能实现适配器，不能改变其审核字段和选择语义。

- [ ] **Step 4: 运行 GREEN 并提交**

Run:

    .\.venv\Scripts\python.exe -m pytest tests/services/test_observation_selection.py tests/services/test_snapshot_features.py tests/domain -v
    git diff --check
    git add -- lightweight-stock-analysis/backend/app/services/observation_selection.py lightweight-stock-analysis/backend/app/services/snapshot_features.py lightweight-stock-analysis/backend/tests/services/test_observation_selection.py lightweight-stock-analysis/backend/tests/services/test_snapshot_features.py
    git commit -m "feat(lsa): build deterministic snapshot features"

---

### Task 6: 实现可恢复 staging 与原子 READY data_snapshot

**Files:**

- Create: lightweight-stock-analysis/backend/alembic/versions/20260824_04_frozen_data_snapshot.py
- Create: lightweight-stock-analysis/backend/app/db/models/snapshots.py
- Create: lightweight-stock-analysis/backend/app/db/repositories/snapshots.py
- Create: lightweight-stock-analysis/backend/app/services/data_snapshots.py
- Create: lightweight-stock-analysis/backend/app/services/snapshot_sync.py
- Modify: lightweight-stock-analysis/backend/app/services/workflow_context.py
- Create: lightweight-stock-analysis/backend/app/services/snapshot_workflow.py
- Create: lightweight-stock-analysis/backend/tests/services/test_data_snapshots.py
- Create: lightweight-stock-analysis/backend/tests/services/test_snapshot_pipeline.py

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class CreateDataSnapshotCommand:
    preflight_id: UUID
    as_of_date: date
    markets: frozenset[Market]
    source_preferences: tuple[SourcePreference, ...]

class DataSnapshotService:
    async def create_pending(self, command: CreateDataSnapshotCommand) -> PendingDataSnapshot: ...
    async def stage_batch(self, command: StageSnapshotBatchCommand) -> SnapshotBatchCheckpoint: ...
    async def prepare_finalize(self, snapshot_id: UUID) -> PreparedSnapshotFinalization: ...
    async def get_ready(self, snapshot_id: UUID, *, allow_test_only: bool = False) -> ReadySnapshotRef: ...

class SnapshotCommitMode(StrEnum):
    TERMINAL_TARGET = "TERMINAL_TARGET"
    INTERMEDIATE_PARENT = "INTERMEDIATE_PARENT"

class SnapshotExecutionContext(PreflightExecutionContext, Protocol):
    commit_mode: SnapshotCommitMode
    async def checkpoint(self, payload: Mapping[str, JsonValue], progress: float) -> None: ...
    async def raise_if_cancel_requested(self) -> None: ...
    async def commit_snapshot_ready(self, prepared: PreparedSnapshotFinalization) -> ReadySnapshotRef: ...

class SnapshotBuildWorkflow:
    async def run(self, ctx: SnapshotExecutionContext, snapshot_id: UUID) -> ReadySnapshotRef: ...
```

CreateDataSnapshotCommand 只接受用户业务输入。`create_pending` 必须从持久化 preflight、当前 provider registry、credential identity resolver、license declaration、universe reference repository 与当前 RuleBook 自行重算/读取 acceptance_mode、provider_config_hash、credential_id_hash、license/reference/gate0_policy hashes，并用当前 policy 重分类已保存 coverage 后做 constant-time/hash-safe 比较；调用方不能提交或覆盖任何信任字段。workflow 在恢复和 commit 前再次重算 policy/hash，漂移即失败。PREFLIGHT/DATA_SNAPSHOT/CLONE_SCAN 都只能使用上述两个 workflow，不能复制校验或 terminal commit。

Plan 02 只定义 prepared value 与 repository 的 `apply_prepared_*_in_uow`；它们要求调用上下文提供同一个 UoW，并以 expected state/version/hash CAS 写入。production context 只由 Plan 03 的 fenced JobExecutionContext 派生：TERMINAL_TARGET 在一笔事务中写 snapshot aggregate + DATA_SNAPSHOT job SUCCEEDED + snapshot target READY；INTERMEDIATE_PARENT 写 snapshot aggregate READY + 父 workflow checkpoint/reference，但保持父 job/target RUNNING，供 CLONE_SCAN 后续创建 child。SnapshotBuildWorkflow 只返回 ReadySnapshotRef，不自行假设父 job 已 terminal。为本阶段离线测试提供的 TestDataWorkflowExecutionContext 仅在 LSA_ENV=test + 本次 tmp DB 可构造并固定 TERMINAL_TARGET，明确没有生产注册路径。

- [ ] **Step 1: 写状态、隔离、幂等和原子性 RED 测试**

覆盖完整状态及合法边 `QUEUED -> SYNCING -> READY|FAILED|CANCELLED|INTERRUPTED` 与 `FAILED(retryable)|INTERRUPTED -> SYNCING`：NOT_CONFIGURED 拒绝创建；LIVE_PARTIAL 只允许请求中已配置市场；过期或 registry/credential/license/reference/policy hash 漂移拒绝；synthetic 不能建 LIVE snapshot；TEST_ONLY 需要 test 环境和 tmp 数据库；同 batch hash 重试幂等，同 batch_id 不同 hash 冲突；expected sync plan 中任一 batch、capability stream 或 terminal marker 未完成不得 READY；prepared finalize 失败时不暴露部分冻结内容；旧 READY snapshot 不被失败刷新覆盖。重启后 SnapshotBuildWorkflow.run(ctx, snapshot_id) 从已提交 checkpoint 继续，不重新接受调用方信任字段。Plan 02 test context 证明 aggregate+target 原子；Plan 03 分别证明 TERMINAL_TARGET 和 INTERMEDIATE_PARENT 带同一 claim fence 的原子语义。

- [ ] **Step 2: 运行 RED**

Run:

    .\.venv\Scripts\python.exe -m pytest tests/services/test_data_snapshots.py tests/services/test_snapshot_pipeline.py tests/db/test_migrations.py -v

Expected: FAIL because snapshot schema and service are missing.

- [ ] **Step 3: 实现 prepared freeze 与唯一原子提交端口**

Settings 固定 `snapshot_sync_batch_size=200`（配置只能调小，不能大于 200）。创建 PENDING target 时先按 reference universe 的稳定 listing_id 排序分区、市场和所需 capability/期间生成不可变 `snapshot_sync_plan`：保存 batch size、排序后的 expected batch descriptors、expected_batch_count、每个 logical stream 的 terminal marker key 和 plan hash；测试证明 200 listings 是 1 batch、201 是 2 batches，且每批不超过 200。Provider 分页只写 staging；随后按该固定计划归并为 canonical batch，因此“少抓一页”会表现为 terminal marker 或 expected batch hash 不匹配，而不是被误判完整。

`prepare_finalize` 不做网络 I/O，产出带 expected snapshot state/version、staging/sync-plan hash 和全部冻结行/hash 的不可变 PreparedSnapshotFinalization。随后只有 `ctx.commit_snapshot_ready(prepared)` 可打开写事务，并调用 repository `apply_prepared_ready_in_uow` 完成：

1. CAS 校验状态仍是 SYNCING，sync plan hash 未变，completed batch count/hash 与 expected manifest 完全一致，且每个 capability stream 有正确 terminal marker/page count/rolling hash。
2. 选择 `announcement_date <= as_of_date` 的最新 observation 版本。
3. 固定每市场 market_effective_date、universe 成员和 A/H/industry/benchmark mapping 版本。
4. 运行冲突检测，按 `CONFLICTED > UNAVAILABLE > PARTIAL > READY` 形成每 listing 唯一数据状态。
5. 写 snapshot_universe、snapshot_input_observations 和 feature_snapshots。
6. 对排序后的 manifest canonical JSON 计算 SHA-256；manifest 至少包含 preflight_id/report_hash/gate0_policy_hash/measured_at/expires_at、每市场 capability_state/acceptance_mode/synthetic/market_effective_date、provider/credential/license/reference hashes、snapshot universe member_count/member_hash、sync plan/expected batch hashes、每个选中 observation 的 observation_id/announcement_date/artifact/parser/selection_reason/retrieved_at、industry/benchmark/A-H mapping versions、data status counts 和 rule-compatible feature version。
7. CAS 将 data_snapshot 从 SYNCING 改为 READY，设 completed_at 和 manifest_hash。

READY 后，SQLite trigger 对 snapshot_universe、snapshot_input_observations、feature_snapshots、snapshot batch/terminal/manifest 行的 `INSERT/UPDATE/DELETE` 全部拒绝，并拒绝修改 READY parent 的冻结字段；repository guard 与原始 SQL 测试都要覆盖三种动词。更正数据只能创建新 snapshot。

- [ ] **Step 4: 运行 GREEN 并提交**

Run:

    .\.venv\Scripts\python.exe -m pytest tests/services/test_data_snapshots.py tests/services/test_snapshot_pipeline.py tests/db/test_migrations.py -v
    git diff --check
    git add -- lightweight-stock-analysis/backend/alembic/versions/20260824_04_frozen_data_snapshot.py lightweight-stock-analysis/backend/app/db/models/snapshots.py lightweight-stock-analysis/backend/app/db/repositories/snapshots.py lightweight-stock-analysis/backend/app/services/data_snapshots.py lightweight-stock-analysis/backend/app/services/snapshot_sync.py lightweight-stock-analysis/backend/app/services/workflow_context.py lightweight-stock-analysis/backend/app/services/snapshot_workflow.py lightweight-stock-analysis/backend/tests
    git commit -m "feat(lsa): freeze immutable ready data snapshots"

---

### Task 7: 冻结 10,000 listing 性能 fixture 和数据平面交付门

**Files:**

- Create: lightweight-stock-analysis/backend/tests/performance/generate_fixture.py
- Create: lightweight-stock-analysis/backend/tests/performance/fixtures/manifest.json
- Create: lightweight-stock-analysis/backend/tests/performance/test_fixture_manifest.py
- Create: lightweight-stock-analysis/backend/tests/integration/test_offline_snapshot_pipeline.py
- Modify: lightweight-stock-analysis/backend/README.md

**Interfaces:** manifest schema 固定 `schema_version`、`generator_version`、`random_seed=20260824`、`listing_count=10000`、`status_distribution`、`input_files[].sha256`、`expected_sync_plan_hash`、`expected_batch_count`、`expected_top50_hash`。

- [ ] **Step 1: 写 manifest RED 测试**

测试两次运行 generator 到两个不同 tmp_path，断言所有输入文件 hash、expected sync plan/batch count、数据状态分布和 expected_top50_hash 完全相同。离线集成测试依赖全局 socket guard，断言整条 fixture pipeline 不建立 socket，产生 `READY + TEST_ONLY`，且依次读回的 observation IDs 全部属于 manifest；测试前后工作区 write manifest 必须相同，所有 SQLite/cache/import/export/secrets/artifact 都位于本测试唯一 tmp 目录。

- [ ] **Step 2: 运行 RED**

Run:

    .\.venv\Scripts\python.exe -m pytest tests/performance/test_fixture_manifest.py tests/integration/test_offline_snapshot_pipeline.py -v

Expected: FAIL because deterministic generator and manifest are missing.

- [ ] **Step 3: 实现确定 generator 和交付说明**

generator 只使用 `random.Random(20260824)`，所有 UUID 从稳定 namespace UUID5 生成，日期、listing 数、市场比例、缺失/冲突分布和文件排序固定。`expected_top50_hash` 使用阶段一领域内核对 fixture 独立运行后一次性锁定；以后只能因明确规则版本升级而更新。README 明确写：本阶段验证的是离线数据平面，真实市场能力仍为 NOT_CONFIGURED。

- [ ] **Step 4: 运行阶段门并提交**

Run:

    .\.venv\Scripts\python.exe -m pytest tests/domain tests/providers tests/db tests/services tests/integration/test_offline_snapshot_pipeline.py tests/performance/test_fixture_manifest.py -v
    .\.venv\Scripts\python.exe -m compileall -q app
    git diff --check
    git add -- lightweight-stock-analysis/backend/tests/performance lightweight-stock-analysis/backend/tests/integration/test_offline_snapshot_pipeline.py lightweight-stock-analysis/backend/README.md
    git commit -m "test(lsa): lock the offline data plane fixture"

阶段二完成条件：在断网、无真实凭据、唯一临时 SQLite 下可重复生成同一 `TEST_ONLY READY` 快照和 manifest；任何 fake/synthetic 结果都无法被持久化为真实 `LIVE_READY`。
