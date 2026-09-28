# 轻量化防御性股票分析阶段一：独立骨架与评分内核 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 在独立子应用中建立可复现、无网络、无数据库依赖的 LSA-DS2 2.0.0 领域内核，完成配置哈希、硬过滤、六维客观分、实体去重 Top 50、两项主观分和最终 DS2 排名。

**Architecture:** 领域层只接收不可变、已规范化的 Python dataclass，读取一次冻结 RuleBook，并通过纯函数返回资格与评分结果。数据抓取、SQLite、FastAPI、AI 和前端都不进入本阶段；后续阶段只能调用这里公开的类型和函数，不能复制评分逻辑。

**Tech Stack:** Python 3.12、标准库 dataclasses/enum/hashlib/statistics、PyYAML、pytest 8。

**Spec:** lightweight-stock-analysis/docs/superpowers/specs/2026-08-24-lightweight-defensive-stock-analysis-design.md

## Global Constraints

- 执行前必须使用 superpowers:using-git-worktrees 创建隔离 worktree；当前主工作区已有用户修改，不在原目录直接实施。
- Python 版本固定为 3.12.x；所有后端命令从 lightweight-stock-analysis/backend 执行。
- 子应用不得 import 父项目 backend.app.*，不得读取父项目数据库、配置或 node_modules。
- 顶层公式只能是 20/18/15/12/12/8/8/7；六维 ObjectiveScore 权重只能是 18/15/12/12/8/8。
- 本阶段实现的是新增 LSA-DS2 2.0.0 校准档；不得把子权重和锚点描述为参考对话原文。
- 缺失、非有限值或无效分母返回不可评分状态，不补 0/50，不重新分配权重。
- 所有排名使用未舍入 float；只在序列化展示时保留一位小数。
- 任何配置改变都改变 SHA-256；测试不得依赖散落的生产常量。
- 每项任务先 RED、再最小 GREEN；每次提交前运行 git diff --check。

## File Structure

| File | Responsibility |
|---|---|
| lightweight-stock-analysis/.gitignore | 隔离数据库、密钥、缓存、构建和视觉工件 |
| lightweight-stock-analysis/backend/pyproject.toml | Python 3.12 项目、运行时与测试依赖 |
| lightweight-stock-analysis/backend/requirements.lock | 由 pyproject 生成的哈希锁定依赖 |
| lightweight-stock-analysis/backend/app/__init__.py | 独立应用包标识 |
| lightweight-stock-analysis/backend/app/settings.py | 只解析本子应用环境变量和路径 |
| lightweight-stock-analysis/backend/app/domain/rulebook.py | 加载、验证、规范化和哈希规则 |
| lightweight-stock-analysis/backend/app/domain/models.py | 领域 dataclass 和 enum |
| lightweight-stock-analysis/backend/app/domain/math.py | 插值、CV、回撤、百分位和 Beta 纯函数 |
| lightweight-stock-analysis/backend/app/domain/objective.py | 六个客观维度及 ObjectiveScore |
| lightweight-stock-analysis/backend/app/domain/eligibility.py | 行业、适用性、五年、造假、商誉和冲突过滤 |
| lightweight-stock-analysis/backend/app/domain/conflicts.py | 金额/比率冲突容差与稳定候选记录 |
| lightweight-stock-analysis/backend/app/domain/ranking.py | A/H 代表 listing、Top 50、主观维度和最终 DS2 |
| lightweight-stock-analysis/backend/app/domain/contracts.py | 把领域结果序列化为后续数据层/API 共用的稳定契约 |
| lightweight-stock-analysis/backend/app/domain/build_manifest.py | 对明确源文件清单计算 engine build SHA-256 |
| lightweight-stock-analysis/scripts/stamp-score-config.py | 在提交前重算并写入 engine build hash |
| lightweight-stock-analysis/config/defensive-score-2.0.yaml | 唯一 LSA-DS2 规则源 |
| lightweight-stock-analysis/backend/tests/conftest.py | 每测试唯一运行目录、禁止外网和工作区写入清单 |
| lightweight-stock-analysis/backend/tests/test_runtime_isolation.py | 验证测试不会写父项目或共享运行目录 |
| lightweight-stock-analysis/backend/tests/test_architecture_boundaries.py | 禁止父项目依赖和散落规则 |
| lightweight-stock-analysis/backend/tests/domain/*.py | 领域 RED/GREEN 测试 |

---

### Task 1: 建立独立 Python 包与冻结 RuleBook

**Files:**

- Create: lightweight-stock-analysis/.gitignore
- Create: lightweight-stock-analysis/backend/pyproject.toml
- Create: lightweight-stock-analysis/backend/app/__init__.py
- Create: lightweight-stock-analysis/backend/app/settings.py
- Create: lightweight-stock-analysis/backend/app/domain/__init__.py
- Create: lightweight-stock-analysis/backend/app/domain/rulebook.py
- Create: lightweight-stock-analysis/config/defensive-score-2.0.yaml
- Create: lightweight-stock-analysis/backend/tests/conftest.py
- Create: lightweight-stock-analysis/backend/tests/test_runtime_isolation.py
- Create: lightweight-stock-analysis/backend/tests/test_architecture_boundaries.py
- Create: lightweight-stock-analysis/backend/tests/domain/test_rulebook.py

**Interfaces:**

- Consumes: 规格第 3、10、11、12、13、23 节。
- Produces: load_rulebook(path: Path) -> RuleBook；RuleBook.content_hash: str；Settings.from_env(root: Path) -> Settings。

- [ ] **Step 1: 写项目清单和 RED 测试**

pyproject.toml 使用以下依赖边界；requirements.lock 在 GREEN 后生成：

    [build-system]
    requires = ["setuptools>=75,<76"]
    build-backend = "setuptools.build_meta"

    [project]
    name = "lightweight-stock-analysis"
    version = "0.1.0"
    requires-python = ">=3.12,<3.13"
    dependencies = [
      "fastapi>=0.104,<1",
      "uvicorn[standard]>=0.24,<1",
      "pydantic>=2.13,<3",
      "sqlalchemy>=2.0,<3",
      "alembic>=1.18,<2",
      "httpx>=0.27,<1",
      "openpyxl>=3.1,<4",
      "python-multipart>=0.0.6,<1",
      "PyYAML>=6.0,<7",
    ]

    [project.optional-dependencies]
    test = [
      "pytest>=8,<9",
      "pytest-asyncio>=0.24,<1",
      "pytest-socket>=0.7,<1",
      "pip-tools>=7.4,<8",
    ]

    [tool.pytest.ini_options]
    testpaths = ["tests"]
    addopts = "-p no:cacheprovider --disable-socket"

test_rulebook.py 先只引用尚不存在的实现：

    from pathlib import Path
    import math
    import pytest

    def test_rulebook_loads_exact_weights_and_stable_hash() -> None:
        from app.domain.rulebook import load_rulebook

        path = Path(__file__).parents[3] / "config" / "defensive-score-2.0.yaml"
        first = load_rulebook(path)
        second = load_rulebook(path)
        assert first.version == "LSA-DS2-2.0.0"
        assert set(first.ds2_weights) == {
            "industry_prospect", "earnings_stability", "cash_flow", "balance_sheet",
            "valuation", "shareholder_return", "low_volatility", "moat",
        }
        assert set(first.objective_weights) == {
            "earnings_stability", "cash_flow", "balance_sheet",
            "valuation", "shareholder_return", "low_volatility",
        }
        assert math.isclose(sum(first.ds2_weights.values()), 1.0)
        assert math.isclose(sum(first.objective_weights.values()), 73.0)
        assert first.content_hash == second.content_hash
        assert len(first.content_hash) == 64
        assert first.config_hash == second.config_hash
        assert len(first.config_hash) == 64
        assert first.engine_semantic_version == "lsa-domain-2.0.0"
        assert first.formula_version == "defensive-reference-8d-1.0.0"
        assert first.calibration_version == "LSA-DS2-2.0.0"
        assert first.scorer_semantic_version == "lsa-scorer-2.0.0"
        assert first.industry_taxonomy_version == "DS2-CANONICAL-INDUSTRY-v1"

    def test_rulebook_rejects_wrong_weight_sum(tmp_path: Path) -> None:
        from app.domain.rulebook import RuleBookError, load_rulebook

        path = tmp_path / "bad.yaml"
        path.write_text("version: bad\nds2_weights: {industry: 0.2}\n", encoding="utf-8")
        with pytest.raises(RuleBookError, match="ds2_weights"):
            load_rulebook(path)

test_architecture_boundaries.py 必须递归检查 app 下 Python 文件不含父项目 import，并且评分权重只出现在 YAML：

    from pathlib import Path

    def test_subapp_does_not_import_parent_backend() -> None:
        app_root = Path(__file__).parents[1] / "app"
        offenders = [
            str(path)
            for path in app_root.rglob("*.py")
            if "backend.app" in path.read_text(encoding="utf-8")
        ]
        assert offenders == []

tests/conftest.py 用 autouse fixture 为每个 test 创建唯一的 SQLite、artifact、cache、import、export 和 secrets 子目录，把相应 `LSA_*` 环境变量全部指向 `tmp_path`，并设置 `PYTHONDONTWRITEBYTECODE=1`。pytest-socket 默认禁止 socket；确需 E2E loopback 的测试必须显式使用 `socket_allow_hosts(["127.0.0.1", "::1"])`，不得放开外网。`workspace_write_guard` 在测试前后对仓库内受版本控制文件和允许观察的未跟踪路径做 manifest，除显式测试工件 allowlist 外任何新增/修改都失败；test_runtime_isolation.py 断言不同测试的六类路径不共享、都位于本次 tmp_path，且父项目 tree manifest 不变。

    def test_scoring_weights_have_one_production_authority() -> None:
        app_root = Path(__file__).parents[1] / "app"
        forbidden_literals = ("0.20 * industry", "/ 73.0", "'valuation': 0.12")
        offenders = [
            str(path)
            for path in app_root.rglob("*.py")
            if any(token in path.read_text(encoding="utf-8") for token in forbidden_literals)
        ]
        assert offenders == []

创建测试后先用工作区配置的 Python 3.12 创建子应用专用环境，不复用父项目 venv：

    & '<PYTHON_3_12_EXECUTABLE>' -m venv .venv
    .\.venv\Scripts\python.exe -m pip install --upgrade pip
    .\.venv\Scripts\python.exe -m pip install -e ".[test]"

Expected: 依赖只安装到 lightweight-stock-analysis/backend/.venv；如需联网下载，由执行者在实施会话中取得授权。

- [ ] **Step 2: 运行 RED**

Run:

    .\.venv\Scripts\python.exe -m pytest tests/domain/test_rulebook.py tests/test_architecture_boundaries.py tests/test_runtime_isolation.py -v

Expected: FAIL with ModuleNotFoundError: No module named 'app.domain.rulebook'。

- [ ] **Step 3: 写最小 RuleBook 和配置**

defensive-score-2.0.yaml 必须以此顶层结构落盘，所有子项名称与后续函数签名一致：

    schema_version: 1
    version: LSA-DS2-2.0.0
    formula_version: defensive-reference-8d-1.0.0
    calibration_version: LSA-DS2-2.0.0
    scorer_semantic_version: lsa-scorer-2.0.0
    engine_semantic_version: lsa-domain-2.0.0
    industry_taxonomy_version: DS2-CANONICAL-INDUSTRY-v1
    provider_industry_mapping_version: lsa-provider-industry-map-v1
    benchmark_mapping_version: lsa-benchmark-map-v1
    rules_content_sha256: null
    engine_build_sha256: null
    engine_source_manifest:
      - app/domain/rulebook.py
      - app/domain/models.py
      - app/domain/math.py
      - app/domain/objective.py
      - app/domain/eligibility.py
      - app/domain/conflicts.py
      - app/domain/ranking.py
      - app/domain/contracts.py
    ds2_weights:
      industry_prospect: 0.20
      earnings_stability: 0.18
      cash_flow: 0.15
      balance_sheet: 0.12
      valuation: 0.12
      shareholder_return: 0.08
      low_volatility: 0.08
      moat: 0.07
    objective_weights:
      earnings_stability: 18
      cash_flow: 15
      balance_sheet: 12
      valuation: 12
      shareholder_return: 8
      low_volatility: 8
    dimension_weights:
      earnings_stability: {net_profit_cv: 0.35, earnings_drawdown: 0.25, average_roe: 0.25, minimum_roe: 0.15}
      cash_flow: {average_ocf_to_np: 0.35, positive_fcf_years: 0.25, ocf_cv: 0.20, aggregate_fcf_to_ocf: 0.20}
      balance_sheet: {net_debt_to_ebitda: 0.40, interest_coverage: 0.40, industry_leverage: 0.20}
      valuation: {own_pe_percentile: 0.50, industry_pe_percentile: 0.25, industry_fcf_yield_percentile: 0.25}
      shareholder_return: {dividend_years: 0.20, non_cut_years: 0.15, aggregate_payout: 0.25, total_shareholder_yield: 0.40}
      low_volatility: {beta: 0.40, max_drawdown_ratio: 0.35, downside_capture: 0.25}
      industry_prospect: {demand_durability: 0.30, profit_pool_quality: 0.25, policy_regulatory_resilience: 0.20, substitution_resistance: 0.15, competition_structure: 0.10}
      moat: {market_position: 0.30, durable_advantage: 0.30, return_persistence: 0.25, pricing_power_retention: 0.15}
    anchors:
      net_profit_cv: [[0.15, 100], [0.30, 75], [0.50, 40], [0.75, 0]]
      earnings_drawdown: [[0.10, 100], [0.25, 75], [0.40, 40], [0.70, 0]]
      average_roe: [[0, 0], [8, 40], [10, 60], [15, 85], [20, 100]]
      minimum_roe: [[0, 0], [5, 30], [8, 65], [12, 90], [15, 100]]
      average_ocf_to_np: [[0, 0], [0.50, 35], [0.80, 70], [1.00, 100], [1.50, 100]]
      positive_fcf_years: [[0, 0], [3, 50], [4, 80], [5, 100]]
      ocf_cv: [[0.15, 100], [0.30, 75], [0.50, 40], [0.75, 0]]
      aggregate_fcf_to_ocf: [[0, 0], [0.20, 40], [0.40, 70], [0.60, 100]]
      net_debt_to_ebitda: [[0, 100], [2, 85], [4, 30], [6, 0]]
      interest_coverage: [[1, 0], [3, 60], [5, 85], [10, 100]]
      industry_leverage: [[0, 100], [0.50, 60], [0.80, 25], [1, 0]]
      own_pe_percentile: [[0, 100], [0.20, 90], [0.50, 70], [0.70, 40], [0.90, 10], [1, 0]]
      industry_pe_percentile: [[0, 100], [0.20, 90], [0.50, 70], [0.70, 40], [0.90, 10], [1, 0]]
      industry_fcf_yield_percentile: [[0, 0], [0.30, 40], [0.50, 65], [0.80, 90], [1, 100]]
      dividend_years: [[0, 0], [3, 50], [5, 100]]
      non_cut_years: [[0, 0], [3, 60], [5, 100]]
      aggregate_payout: [[0, 0], [0.30, 80], [0.50, 100], [0.70, 90], [1.00, 50], [1.20, 0]]
      total_shareholder_yield: [[0, 0], [2.5, 60], [3, 75], [5, 95], [7, 100]]
      beta: [[0.50, 100], [0.80, 85], [0.90, 70], [1.00, 50], [1.20, 20], [1.40, 0]]
      max_drawdown_ratio: [[0.50, 100], [0.70, 80], [1.00, 50], [1.30, 20], [1.60, 0]]
      downside_capture: [[0.50, 100], [0.70, 85], [1.00, 50], [1.20, 20], [1.40, 0]]
    hard_excluded_industries:
      [BAIJIU, COAL, STEEL, MARINE_SHIPPING, REAL_ESTATE_DEVELOPMENT, REAL_ESTATE_HIGH_DEPENDENCY, SOLAR_LEGACY_LOW_EFFICIENCY, COMMODITY_CHEMICAL_PURE_CYCLICAL, BREEDING, STRUCTURAL_DECLINE, STRONG_CYCLICAL]
    model_not_applicable: [BANK, INSURANCE, SECURITIES_BROKERAGE]
    statistical_windows:
      annual_financial_years: 5
      risk_history_years: 3
      pe_history_lookback_months: 60
      pe_history_minimum_months: 36
      pe_trading_day_coverage_min: 0.80
      beta_adjacent_iso_week_pairs_min: 130
      downside_month_pairs_min: 30
      downside_negative_months_min: 8
      peer_group_min_size: 10
      peer_parent_fallbacks_max: 1
    canonical_benchmarks:
      CN: CN_CSI300_TOTAL_RETURN
      HK: HK_HSI_TOTAL_RETURN
    hard_filter_thresholds:
      goodwill_individual_year_ratio: 0.10
      goodwill_individual_year_count: 2
      goodwill_lookback_years: 3
      goodwill_cumulative_ratio: 0.20
    conflict_tolerances:
      amount_absolute_normalized_units: 1.0
      amount_relative_ratio: 0.01
      ratio_percentage_points: 0.5
    gate0_thresholds:
      security_master: 0.98
      price: 0.95
      valuation: 0.95
      price_history: 0.90
      pe_history: 0.85
      benchmark: 1.00
      financial_cells: 0.85
      regulatory_risk: 0.95
      real_readbacks_per_market: 10
      report_ttl_hours: 24
    evidence_rules:
      industry_freshness_months: 18
      independent_verified_publishers_min: 2
      primary_sources_min: 1
    objective_batch_size: 200
    score_display_decimals: 1
    objective_denominator: 73

rulebook.py 只暴露不可变结构，并以规范 JSON 计算哈希：

    class RuleBookError(ValueError):
        pass

    @dataclass(frozen=True)
    class RuleBook:
        version: str
        formula_version: str
        calibration_version: str
        scorer_semantic_version: str
        engine_semantic_version: str
        industry_taxonomy_version: str
        provider_industry_mapping_version: str
        benchmark_mapping_version: str
        ds2_weights: Mapping[str, float]
        objective_weights: Mapping[str, float]
        dimension_weights: Mapping[str, Mapping[str, float]]
        anchors: Mapping[str, tuple[tuple[float, float], ...]]
        hard_excluded_industries: frozenset[str]
        model_not_applicable: frozenset[str]
        statistical_windows: Mapping[str, int | float]
        canonical_benchmarks: Mapping[str, str]
        hard_filter_thresholds: Mapping[str, int | float]
        conflict_tolerances: Mapping[str, float]
        gate0_thresholds: Mapping[str, int | float]
        evidence_rules: Mapping[str, int]
        objective_batch_size: int
        score_display_decimals: int
        objective_denominator: float
        content_hash: str
        config_hash: str
        declared_rules_content_sha256: str | None
        engine_source_manifest: tuple[PurePosixPath, ...]
        engine_build_hash: str | None

    def load_rulebook(path: Path) -> RuleBook:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        rule_keys = (
            "version", "formula_version", "calibration_version", "scorer_semantic_version",
            "engine_semantic_version", "industry_taxonomy_version",
            "provider_industry_mapping_version", "benchmark_mapping_version",
            "ds2_weights", "objective_weights", "dimension_weights",
            "anchors", "hard_excluded_industries", "model_not_applicable",
            "statistical_windows", "canonical_benchmarks", "hard_filter_thresholds",
            "conflict_tolerances", "gate0_thresholds", "evidence_rules",
            "objective_batch_size", "score_display_decimals", "objective_denominator",
        )
        rules_payload = {key: raw[key] for key in rule_keys}
        rules_json = json.dumps(rules_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        config_json = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        content_hash = hashlib.sha256(rules_json.encode("utf-8")).hexdigest()
        config_hash = hashlib.sha256(config_json.encode("utf-8")).hexdigest()
        declared = raw.get("rules_content_sha256")
        if declared is not None and not hmac.compare_digest(declared, content_hash):
            raise RuleBookError("rules_content_sha256 does not match canonical rule content")
        _require_sum(raw["ds2_weights"], 1.0, "ds2_weights")
        _require_exact_keys(raw["ds2_weights"], EXPECTED_DS2_KEYS, "ds2_weights")
        _require_sum(raw["objective_weights"], 73.0, "objective_weights")
        _require_exact_keys(raw["objective_weights"], EXPECTED_OBJECTIVE_KEYS, "objective_weights")
        for name, weights in raw["dimension_weights"].items():
            _require_sum(weights, 1.0, f"dimension_weights.{name}")
        return _freeze(raw, content_hash, config_hash)

`content_hash` 的 canonical payload 包含全部公式、校准、taxonomy/mapping 版本与规则值，但排除自引用的 `rules_content_sha256` 和仅描述构建产物的 `engine_build_sha256`；`config_hash` 则覆盖完整 YAML。_freeze 必须把所有 mapping 递归转为 MappingProxyType，把 anchors 转为 tuple[tuple[float, float], ...]，把排除集合转为 frozenset，并解析固定 source manifest。Task 1 尚未生成最终两个声明哈希，因此 `declared_rules_content_sha256` 与 `engine_build_hash` 可为 None；Task 6 交付门会同时强制二者为 64 位 SHA-256 且与重算值一致。同时验证版本值、score_display_decimals == 1、objective_denominator == 73.0、窗口/门槛/样本值与上述结构一致。对缺键、额外键、非数值、重复/非递增锚点和非有限值统一抛 RuleBookError，不泄漏 PyYAML 底层异常。

Settings.from_env 只解析 LSA_ENV、LSA_DATA_DIR、LSA_DATABASE_URL、LSA_HOST、LSA_PORT，默认路径相对 lightweight-stock-analysis 根目录解析，不读取父仓库变量。

- [ ] **Step 4: 运行 GREEN**

Run:

    .\.venv\Scripts\python.exe -m pytest tests/domain/test_rulebook.py tests/test_architecture_boundaries.py tests/test_runtime_isolation.py -v

Expected: PASS，且没有 pytest cache 写入。

- [ ] **Step 5: 生成锁文件并提交**

Run:

    .\.venv\Scripts\python.exe -m piptools compile pyproject.toml --extra test --generate-hashes --output-file requirements.lock
    git diff --check
    git add ..\.gitignore pyproject.toml requirements.lock app tests ..\config\defensive-score-2.0.yaml
    git commit -m "chore: scaffold defensive scoring core"

Expected: commit 只包含新子应用文件。

---

### Task 2: 实现可复现数学原语

**Files:**

- Create: lightweight-stock-analysis/backend/app/domain/math.py
- Create: lightweight-stock-analysis/backend/tests/domain/test_math.py

**Interfaces:**

- Consumes: RuleBook.anchors。
- Produces: piecewise_linear_score、population_cv、series_max_drawdown、average_rank_percentile、weekly_beta、downside_capture_ratio。

- [ ] **Step 1: 写参数化 RED 测试**

test_math.py 必须直接固定边界和缺失行为：

    @pytest.mark.parametrize(
        ("value", "expected"),
        [(0.15, 100.0), (0.225, 87.5), (0.30, 75.0), (0.75, 0.0), (1.0, 0.0)],
    )
    def test_piecewise_linear_score(value: float, expected: float) -> None:
        anchors = ((0.15, 100.0), (0.30, 75.0), (0.50, 40.0), (0.75, 0.0))
        assert piecewise_linear_score(value, anchors) == pytest.approx(expected)

    def test_population_cv_uses_population_standard_deviation() -> None:
        assert population_cv((10.0, 12.0, 14.0, 16.0, 18.0)) == pytest.approx(
            statistics.pstdev((10, 12, 14, 16, 18)) / 14
        )

    def test_missing_and_non_finite_values_return_none() -> None:
        assert piecewise_linear_score(None, ((0, 0), (1, 100))) is None
        assert piecewise_linear_score(float("nan"), ((0, 0), (1, 100))) is None
        assert population_cv((0.0, 0.0)) is None

Beta 测试使用固定 130 周简单收益 fixture，并断言公式等于 covariance numerator / benchmark variance denominator；缺周不由 math.py 填充。

- [ ] **Step 2: 运行 RED**

Run:

    .\.venv\Scripts\python.exe -m pytest tests/domain/test_math.py -v

Expected: FAIL with ImportError for app.domain.math。

- [ ] **Step 3: 实现纯函数**

核心插值实现必须按锚点夹断：

    def piecewise_linear_score(
        value: float | None,
        anchors: Sequence[tuple[float, float]],
    ) -> float | None:
        if value is None or not math.isfinite(value):
            return None
        ordered = tuple(sorted(anchors))
        if value <= ordered[0][0]:
            return float(ordered[0][1])
        if value >= ordered[-1][0]:
            return float(ordered[-1][1])
        for (x0, y0), (x1, y1) in pairwise(ordered):
            if x0 <= value <= x1:
                ratio = (value - x0) / (x1 - x0)
                return min(100.0, max(0.0, y0 + ratio * (y1 - y0)))
        raise AssertionError("ordered anchors must bracket finite value")

weekly_beta 返回：

    numerator = sum((stock - stock_mean) * (market - market_mean) for stock, market in pairs)
    denominator = sum((market - market_mean) ** 2 for _, market in pairs)
    return None if len(pairs) < 130 or denominator == 0 else numerator / denominator

average_rank_percentile 对并列值使用平均秩，并精确按 `(average_rank - 1) / (n - 1)` 返回 0–1；样本小于 10 返回 None。test_math.py 还要覆盖五年盈利最大回撤、30 月/8 个下跌月门槛及 `downside_capture = mean(stock_negative_benchmark_month_returns) / mean(negative_benchmark_month_returns)`，包括零分母和刚好达到样本门槛。所有函数不舍入。

- [ ] **Step 4: 运行 GREEN**

Run:

    .\.venv\Scripts\python.exe -m pytest tests/domain/test_math.py -v

Expected: PASS。

- [ ] **Step 5: 提交**

Run:

    git diff --check
    git add app/domain/math.py tests/domain/test_math.py
    git commit -m "feat: add deterministic scoring math"

---

### Task 3: 实现六个客观维度与 ObjectiveScore

**Files:**

- Create: lightweight-stock-analysis/backend/app/domain/models.py
- Create: lightweight-stock-analysis/backend/app/domain/objective.py
- Create: lightweight-stock-analysis/backend/tests/domain/test_objective.py

**Interfaces:**

- Consumes: RuleBook、math.py。
- Produces: AnnualFinancial、ObjectiveFeatures、`ScoredDimension | UnscorableDimension`、DimensionScores、`ScoredObjective | UnscorableObjective`；缺失结果仍保留原因和追溯。

- [ ] **Step 1: 写完整六维 RED fixture**

models.py 的预期公开输入在测试中先按以下名字实例化：

    @dataclass(frozen=True)
    class AnnualFinancial:
        fiscal_year: int
        net_profit_parent: float | None
        operating_cash_flow: float | None
        capex: float | None
        roe_weighted_pct: float | None
        total_assets: float | None
        total_liabilities: float | None
        cash_and_equivalents: float | None
        short_interest_debt: float | None
        long_interest_debt: float | None
        ebit: float | None
        ebitda: float | None
        depreciation_amortization: float | None
        interest_expense: float | None
        cash_dividends: float | None
        completed_buybacks: float | None
        adjusted_dividend_per_share: float | None
        goodwill_impairment: float | None
        opening_parent_equity: float | None

    @dataclass(frozen=True)
    class ObjectiveFeatures:
        annuals: tuple[AnnualFinancial, ...]
        liabilities_to_assets_industry_percentile: float | None
        own_pe_percentile: float | None
        industry_pe_percentile: float | None
        industry_fcf_yield_percentile: float | None
        implied_entity_market_cap: float | None
        trailing_cash_dividends: float | None
        trailing_completed_buybacks: float | None
        beta_3y_weekly: float | None
        max_drawdown_ratio_3y: float | None
        downside_capture_36m: float | None

test_objective.py 必须断言：

- 五年年度 OCF/NP 取比率算术平均，不取总和比。
- FCF = OCF - capex，正 FCF 年数准确。
- 最新年度净债务/EBITDA、零利息且 EBIT 正时 coverage=100。
- 估值使用三个百分位。
- NonCutYears 停派后恢复当年不计。
- 股东回报使用股息加已完成回购。
- `ebitda` 缺失但 `ebit` 与 `depreciation_amortization` 有效时，唯一回退为 `EBITDA = EBIT + D&A`；两者均缺失、回退结果非有限或小于等于 0 时 BalanceSheet 不可评分。
- 六维缺任一必需输入时返回 `UnscorableObjective`，不按剩余维度重算；结果必须指出缺失维度、字段、原因、component trace 和 rule hash。
- ObjectiveScore 等于六维加权和 / 73。

- [ ] **Step 2: 运行 RED**

Run:

    .\.venv\Scripts\python.exe -m pytest tests/domain/test_objective.py -v

Expected: FAIL with ImportError for AnnualFinancial 或 score_objective。

- [ ] **Step 3: 写最小客观评分实现**

objective.py 公开函数固定为：

    DimensionEvaluation: TypeAlias = ScoredDimension | UnscorableDimension
    ObjectiveEvaluation: TypeAlias = ScoredObjective | UnscorableObjective

    def score_earnings(features: ObjectiveFeatures, rules: RuleBook) -> DimensionEvaluation: ...
    def score_cash_flow(features: ObjectiveFeatures, rules: RuleBook) -> DimensionEvaluation: ...
    def score_balance_sheet(features: ObjectiveFeatures, rules: RuleBook) -> DimensionEvaluation: ...
    def score_valuation(features: ObjectiveFeatures, rules: RuleBook) -> DimensionEvaluation: ...
    def score_shareholder_return(features: ObjectiveFeatures, rules: RuleBook) -> DimensionEvaluation: ...
    def score_low_volatility(features: ObjectiveFeatures, rules: RuleBook) -> DimensionEvaluation: ...
    def score_objective(features: ObjectiveFeatures, rules: RuleBook) -> ObjectiveEvaluation: ...

`ScoredDimension` 固定包含 `status="SCORED"`、dimension、raw_score、sub_scores、derived_inputs、component_trace、rule_hash；`UnscorableDimension` 固定包含 `status="UNSCORABLE"`、dimension、missing_fields、reasons、component_trace、rule_hash。DimensionScores 字段固定为 earnings_stability、cash_flow、balance_sheet、valuation、shareholder_return、low_volatility。`ScoredObjective` 保留 dimensions 的纯分值和六个完整维度结果；`UnscorableObjective` 保留全部六维 evaluation、合并去重且稳定排序的 missing_fields/reasons、component_trace 和 rule_hash。score_objective 先计算全部六维：

    results = {
        "earnings_stability": score_earnings(features, rules),
        "cash_flow": score_cash_flow(features, rules),
        "balance_sheet": score_balance_sheet(features, rules),
        "valuation": score_valuation(features, rules),
        "shareholder_return": score_shareholder_return(features, rules),
        "low_volatility": score_low_volatility(features, rules),
    }
    if any(isinstance(result, UnscorableDimension) for result in results.values()):
        return UnscorableObjective.from_dimensions(results, rule_hash=rules.content_hash)
    values = {name: result.raw_score for name, result in results.items()}
    raw = sum(values[name] * rules.objective_weights[name] for name in values) / rules.objective_denominator

不得只返回最终浮点数。测试要同时断言分值、子分、派生输入和不可评分追踪，保证后续持久化不需重算；为 YAML 中每个 anchor 至少建立参数化命中用例，并验证锚点间插值与上下夹断。

- [ ] **Step 4: 运行 GREEN 和规则回归**

Run:

    .\.venv\Scripts\python.exe -m pytest tests/domain/test_objective.py tests/domain/test_rulebook.py -v

Expected: PASS。

- [ ] **Step 5: 提交**

Run:

    git diff --check
    git add app/domain/models.py app/domain/objective.py tests/domain/test_objective.py
    git commit -m "feat: implement objective defensive scores"

---

### Task 4: 实现硬过滤、A/H 实体代表与 Top 50

**Files:**

- Create: lightweight-stock-analysis/backend/app/domain/eligibility.py
- Create: lightweight-stock-analysis/backend/app/domain/conflicts.py
- Create: lightweight-stock-analysis/backend/app/domain/ranking.py
- Create: lightweight-stock-analysis/backend/tests/domain/test_eligibility.py
- Create: lightweight-stock-analysis/backend/tests/domain/test_conflicts.py
- Create: lightweight-stock-analysis/backend/tests/domain/test_objective_ranking.py
- Create: lightweight-stock-analysis/backend/tests/domain/factories.py

**Interfaces:**

- Consumes: AnnualFinancial、ScoredObjective、RuleBook；UnscorableObjective 只能形成 PARTIAL/UNAVAILABLE 追踪，不能进入排序。
- Produces: evaluate_eligibility(facts, rules) -> EligibilityDecision；detect_metric_conflicts(candidates, tolerances) -> tuple[MetricConflict, ...]；freeze_objective_candidates(listings, limit=50) -> tuple[ObjectiveCandidate, ...]。

- [ ] **Step 1: 写过滤顺序和数据状态 RED**

EligibilityFacts 字段固定为 entity_id、listing_id、canonical_industry、financials、risk_check_complete、material_fraud_confirmed、classification_complete、has_critical_conflict、goodwill_inputs_complete、model_class。

测试必须覆盖并断言 primary_reason 顺序。除下列经营/状态原因外，再用参数化表逐一覆盖 YAML 中 11 个 `hard_excluded_industries`，证明每个 canonical code 都触发 `EXCLUDED_INDUSTRY`：

    @pytest.mark.parametrize(
        ("mutator", "expected"),
        [
            (lambda f: replace(f, canonical_industry="BAIJIU"), "EXCLUDED_INDUSTRY"),
            (lambda f: replace(f, model_class="BANK"), "MODEL_NOT_APPLICABLE"),
            (lambda f: replace(f, financials=f.financials[:4]), "INCOMPLETE_FIVE_YEARS"),
            (lambda f: replace_year(f, 2, net_profit_parent=0), "NON_POSITIVE_PROFIT"),
            (lambda f: replace_year(f, 3, operating_cash_flow=0), "NON_POSITIVE_OCF"),
            (lambda f: replace(f, material_fraud_confirmed=True), "EXCLUDED_MATERIAL_FRAUD"),
            (make_persistent_goodwill_case, "EXCLUDED_PERSISTENT_GOODWILL_IMPAIRMENT"),
            (lambda f: replace(f, has_critical_conflict=True), "CONFLICTED"),
        ],
    )
    def test_filter_primary_reason_order(mutator, expected, eligible_facts):
        assert evaluate_eligibility(mutator(eligible_facts), rules).primary_reason == expected

另构造一个同时命中行业排除、五年经营底线、重大造假、商誉减值和关键冲突的案例，断言 `all_reasons` 全部保留且 `primary_reason` 严格遵循已冻结 precedence；分别覆盖 `INDUSTRY_CLASSIFICATION_UNKNOWN`、`RISK_CHECK_UNKNOWN`、`GOODWILL_RISK_UNKNOWN` 三个 PARTIAL 原因，而不是仅验证单一 mutator。

factories.py 提供测试专用的具体帮助函数，避免隐式或未定义 fixture：

    def replace_year(facts: EligibilityFacts, index: int, **changes: float) -> EligibilityFacts:
        years = list(facts.financials)
        years[index] = replace(years[index], **changes)
        return replace(facts, financials=tuple(years))

    def make_persistent_goodwill_case(facts: EligibilityFacts) -> EligibilityFacts:
        years = list(facts.financials)
        years[-2] = replace(years[-2], goodwill_impairment=12.0, opening_parent_equity=100.0)
        years[-1] = replace(years[-1], goodwill_impairment=11.0, opening_parent_equity=100.0)
        return replace(facts, financials=tuple(years))

风险检查、行业分类或商誉输入未知必须返回 PARTIAL，不返回 ELIGIBLE。

test_conflicts.py 用固定候选值断言：金额差异只在超过 `max(1 个规范化货币单位, 1%)` 时冲突；比率差异超过 0.5 个百分点时冲突；刚好等于门槛不冲突；比较前必须同币种/单位/口径，不可比较时生成 `NORMALIZATION_MISMATCH` 冲突而非自动选值。

- [ ] **Step 2: 写 A/H 去重和 Top 50 RED**

构造 55 个 entity，其中一个 entity 有 A/H 两个 listing。断言：

- 先按 ObjectiveScore、Valuation、绝对 PE、listing_id 选择预筛代表。
- 同一 entity 只占一个核心名额。
- 排名用未舍入 ObjectiveScore，再 EarningsStability、CashFlow、listing_id。
- PARTIAL、CONFLICTED、UNAVAILABLE 和非 ELIGIBLE 不进入候选。
- all_listings 结果保留两个 listing，但不影响 core Top 50。

- [ ] **Step 3: 运行 RED**

Run:

    .\.venv\Scripts\python.exe -m pytest tests/domain/test_eligibility.py tests/domain/test_conflicts.py tests/domain/test_objective_ranking.py -v

Expected: FAIL with missing eligibility/ranking modules。

- [ ] **Step 4: 实现确定性过滤和排序**

EligibilityDecision 必须包含 status、primary_reason、all_reasons。freeze_objective_candidates 只接受已经附带 ELIGIBLE/READY 的 ListingObjectiveRecord：

    def freeze_objective_candidates(
        records: Sequence[ListingObjectiveRecord],
        limit: int = 50,
    ) -> tuple[ObjectiveCandidate, ...]:
        ready = [item for item in records if item.eligibility.status == "ELIGIBLE" and item.data_status == "READY"]
        representatives = _choose_one_listing_per_entity(ready)
        ordered = sorted(
            representatives,
            key=lambda item: (
                -item.objective.raw_score,
                -item.objective.dimensions.earnings_stability,
                -item.objective.dimensions.cash_flow,
                item.listing_id,
            ),
        )
        return tuple(ObjectiveCandidate.from_record(item, rank=index + 1) for index, item in enumerate(ordered[:limit]))

持续商誉减值使用 RuleBook 中固定的“两年各达期初净资产 10%”或“三年累计达第一个年度期初净资产 20%”两个独立条件；测试包含“各年均低于 10% 但三年累计刚好 20%”分支及刚低于门槛的反例。conflicts.py 使用 RuleBook 容差返回所有候选 observation ID、差值、门槛和 reason；不为上游选值。

- [ ] **Step 5: 运行 GREEN 并提交**

Run:

    .\.venv\Scripts\python.exe -m pytest tests/domain/test_eligibility.py tests/domain/test_conflicts.py tests/domain/test_objective_ranking.py -v
    git diff --check
    git add app/domain/eligibility.py app/domain/conflicts.py app/domain/ranking.py tests/domain/test_eligibility.py tests/domain/test_conflicts.py tests/domain/test_objective_ranking.py tests/domain/factories.py
    git commit -m "feat: add defensive eligibility and top fifty"

---

### Task 5: 实现主观维度、最终 DS2 与最终代表 listing

**Files:**

- Modify: lightweight-stock-analysis/backend/app/domain/models.py
- Modify: lightweight-stock-analysis/backend/app/domain/ranking.py
- Create: lightweight-stock-analysis/backend/tests/domain/test_final_ranking.py

**Interfaces:**

- Consumes: ObjectiveCandidate、RuleBook、已通过证据层确认的主观子分。
- Produces: score_industry_prospect、score_moat、finalize_ds2、rank_final_entities。

- [ ] **Step 1: 写主观权重和确认状态 RED**

测试输入固定为：

    industry = IndustryReviewScores(
        demand_durability=80,
        profit_pool_quality=70,
        policy_regulatory_resilience=60,
        substitution_resistance=90,
        competition_structure=75,
    )
    moat = MoatReviewScores(
        market_position=85,
        durable_advantage=80,
        return_persistence=70,
        pricing_power_retention=75,
    )

断言 IndustryProspect 和 Moat 精确按 YAML 权重计算；`EvidenceGateStatus` 的 `INSUFFICIENT`/`CONFLICTED`/`STALE` 不产生 DS2；`ReviewDecision` 的 PROVISIONAL、SKIPPED、EXCLUDED_BY_REVIEW 也不产生 DS2。只有 evidence gate 为 PASSED 且 review 为 CONFIRMED 或 MANUAL_CONFIRMED 才允许。

最终 DS2 断言：

    expected = (
        0.20 * industry_score
        + 0.18 * objective.earnings_stability
        + 0.15 * objective.cash_flow
        + 0.12 * objective.balance_sheet
        + 0.12 * objective.valuation
        + 0.08 * objective.shareholder_return
        + 0.08 * objective.low_volatility
        + 0.07 * moat_score
    )
    assert final.raw_score == pytest.approx(expected)

- [ ] **Step 2: 运行 RED**

Run:

    .\.venv\Scripts\python.exe -m pytest tests/domain/test_final_ranking.py -v

Expected: FAIL with missing review score types。

- [ ] **Step 3: 实现最终分与代表规则**

`EvidenceGateStatus` 枚举固定为 `PASSED、INSUFFICIENT、CONFLICTED、STALE`，与 `ReviewDecision` 分离；ReviewDecision 固定为 PROVISIONAL、CONFIRMED、MANUAL_CONFIRMED、SKIPPED、EXCLUDED_BY_REVIEW。`finalize_ds2` 同时接受并验证两个状态。FinalScore 包含 raw_score、display_score、objective_score、industry_prospect、moat、rule_hash。

rank_final_entities 必须先把同一 entity 的已确认主观分传播到全部 READY listing，计算每个 listing 的 DS2，再按 DS2、Valuation、ShareholderReturn、listing_id 选择最终代表，最后按 DS2、ObjectiveScore、EarningsStability、CashFlow、listing_id 排名。

display_score 只做：

    display_score = round(raw_score, rules.score_display_decimals)

不得把 display_score 用于排序。

- [ ] **Step 4: 运行 GREEN 和全领域回归**

Run:

    .\.venv\Scripts\python.exe -m pytest tests/domain -v

Expected: PASS。

- [ ] **Step 5: 提交**

Run:

    git diff --check
    git add app/domain/models.py app/domain/ranking.py tests/domain/test_final_ranking.py
    git commit -m "feat: finalize confirmed defensive rankings"

---

### Task 6: 冻结黄金案例与领域交付门

**Files:**

- Create: lightweight-stock-analysis/backend/tests/domain/fixtures/lsa_ds2_golden.json
- Create: lightweight-stock-analysis/backend/tests/domain/test_golden_cases.py
- Create: lightweight-stock-analysis/backend/app/domain/contracts.py
- Create: lightweight-stock-analysis/backend/app/domain/build_manifest.py
- Create: lightweight-stock-analysis/scripts/stamp-score-config.py
- Modify: lightweight-stock-analysis/config/defensive-score-2.0.yaml
- Modify: lightweight-stock-analysis/backend/tests/domain/test_rulebook.py
- Create: lightweight-stock-analysis/backend/README.md

**Interfaces:**

- Consumes: 阶段一全部公开接口。
- Produces: serialize_domain_result(result: DomainEvaluation) -> Mapping[str, JsonValue]；可供数据层和 API 层复用的稳定黄金输入/输出契约。

- [ ] **Step 1: 写黄金案例 RED**

lsa_ds2_golden.json 包含三个具名案例，每个案例都分为 input 和人工预先复算的 expected：

- ready_dual_listing：同一 entity 的 A/H 两个 listing，六维完整、主观确认，固定预筛代表和最终代表。
- partial_missing_beta：Beta 缺失，预期 `objective.status=UNSCORABLE`、`objective_score_unrounded=null`、missing_fields/reasons/trace 完整且 data_status=PARTIAL。
- excluded_baijiu：行业 BAIJIU，预期第一原因 EXCLUDED_INDUSTRY。

test_golden_cases.py 逐项从 JSON 构造 dataclass，并断言 eligibility、六维原始分、ObjectiveScore、DS2、代表 listing、名次和 rule_hash；测试从尚不存在的 app.domain.contracts 导入 serialize_domain_result，并将其结果与 expected 做深度等值比较。契约键固定为 eligibility、data_status、objective_status、objective_dimensions、objective_score_unrounded、missing_fields、reasons、component_trace、ds2_unrounded、representative_listing_id、rank、rule_hash、config_hash、formula_version、calibration_version、scorer_semantic_version、engine_semantic_version、engine_build_hash；缺失分值用 null，不用 0，但不可评分元数据不得为 null。

test_rulebook.py 新增 `test_committed_config_has_current_declared_hashes`：先对排除 `rules_content_sha256`/`engine_build_sha256` 后的 canonical rule payload 求 SHA-256，断言等于 YAML 的 `rules_content_sha256`；再对 engine_source_manifest 按 POSIX 路径排序，将每个“相对路径 NUL 文件字节 NUL”串联后求 SHA-256，断言等于 YAML 中 `engine_build_sha256`。

- [ ] **Step 2: 运行 RED 并记录实际差异**

Run:

    .\.venv\Scripts\python.exe -m pytest tests/domain/test_golden_cases.py -v

Expected: FAIL with ModuleNotFoundError: No module named 'app.domain.contracts' and missing/stale `rules_content_sha256`/`engine_build_sha256`；失败不是由 expected 数值临时留空造成。

- [ ] **Step 3: 实现稳定序列化并锁定 fixture**

实现 contracts.py，它只把已计算领域结果映射为固定键，不再计算分数。build_manifest.py 只接受位于 backend 源根下、与 YAML 列表完全一致的文件；拒绝绝对路径、`..`、缺失文件和重复路径。stamp-score-config.py 分别计算 rule content 与 engine build hash，原子更新 YAML 的 `rules_content_sha256`、`engine_build_sha256`，立即重读验证声明值和 config_hash；运行时代码不写配置。在写 RED fixture 时已按规格公式独立复算每个 expected 浮点值，保留至少 10 位小数；测试使用 pytest.approx(rel=1e-12, abs=1e-12)，不得用内核运行结果回写 expected。README 记录公开接口、LSA-DS2 与参考公式的边界、缺失规则和后续计划依赖。

- [ ] **Step 4: 运行阶段门**

Run:

    .\.venv\Scripts\python.exe ..\scripts\stamp-score-config.py
    .\.venv\Scripts\python.exe -m pytest tests/domain tests/test_architecture_boundaries.py -v
    .\.venv\Scripts\python.exe -m compileall -q app
    git diff --check

Expected: 全部 PASS；没有父项目 import、默认分或旧公式。

- [ ] **Step 5: 提交**

Run:

    git add app/domain/contracts.py app/domain/build_manifest.py tests/domain/fixtures/lsa_ds2_golden.json tests/domain/test_golden_cases.py tests/domain/test_rulebook.py README.md ..\config\defensive-score-2.0.yaml ..\scripts\stamp-score-config.py
    git commit -m "test: lock defensive score golden cases"

阶段一完成条件：在无网络、无数据库、无 AI 环境下，黄金案例可重复得到相同资格、客观分、Top 50 和确认后 DS2；阶段二只能消费本计划公开接口。
