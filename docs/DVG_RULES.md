# DVG Evidence Gate 规则手册

## 定位
DVG (Data Verification Gate) 是天元量化系统中**唯一的数据门禁**。所有数据源必须先经过 DVG 审查，下游 Agent 才能使用。当前活跃 DAG 中 DVG 由 `guardrail_hub` 统一执行并镜像到旧字段 `run.dvg`；`dvg_gate` / `dvg_evidence_gate` 仅保留为历史读取、修复和 retry alias。

## 审查维度

### 1. 数据存在性
- 确认数据是否存在（existence）
- 缺失数据标记为 `U`（Unknown）

### 2. 数据时效性
- `LIVE`：实时数据，可用于盘中决策
- `FRESH`：当日数据，可用于当天分析
- `STALE`：过期数据，仅作参考，不得用于执行判断
- `FAILED`：获取失败
- `UNKNOWN`：无法判断时效

### 3. 数据冲突
- 当多个数据源对同一指标给出矛盾结论时，标记为冲突
- 冲突数据必须降级处理

### 4. 数据来源
- `C`（Confirmed）：有可审计来源的确证数据（如交易所行情、财报）
- `I`（Inferred）：基于模型推断的数据（如筹码分布估算）
- `U`（Unknown）：未知或缺失数据

### 5. 数据充分性
DVG 必须判断数据是否足以支持下游模块：

- 是否足以支持 QIAM（qiam_permission）
- 是否足以支持 Scenario Engine（scenario_permission）
- 是否足以支持 Execution（execution_permission）

## 权限级别

| 级别 | 含义 | 下游限制 |
|------|------|----------|
| `ALLOW` | 完全允许 | 该模块正常运行 |
| `ALLOW_WITH_DISCOUNT` | 允许但需折扣 | QIAM 折价，Scenario 降级，Execution 限制 |
| `REVIEW_ONLY` | 仅审核 | 不得输出买入计划，只能观察和补数 |
| `BLOCK_BUY` | 阻断买入 | 禁止一切买入候选和加仓计划 |
| `BLOCKED` | 完全阻断 | 该模块跳过 |

## 输出级别

| 级别 | 含义 |
|------|------|
| `FULL` | 数据足以支持完整分析 |
| `REVIEW_ONLY` | 仅允许审查级别输出 |
| `BLOCK_BUY` | 阻断买入路径 |

## 幻觉风险

- `hallucination_risk_score`：0-100 评分
- `hallucination_risk_level`：LOW / MEDIUM / HIGH
- score >= 60：最终动作不得高于 REVIEW_ONLY
- score >= 75：必须触发 Anti-Conclusion Checker

## 强制规则

### 不可绕过
1. 任何 Agent 不得绕过 DVG 直接使用原始数据
2. 所有数据必须先进入 DVG 审查

### 数据缺失拦截
3. 无 Level-2 时，不得判断封单强弱 → 必须拦截
4. 无资金/筹码时，不得判断主力控盘 → 必须拦截
5. source_tool 失败时，相关数据必须标记 U
6. timestamp 缺失时，不得用于盘中执行判断

### 阻断链路
7. DVG `hard_stop = true` 时，`guardrail_hub` 必须触发 Kill Switch，Orchestrator 必须截断正向交易链路
8. DVG `REVIEW_ONLY` 时，QIAM discount_factor 必须设为 0（禁止 QIAM 正向评分）
9. DVG `BLOCK_BUY` 时，QIAM 必须 BLOCK 或 SKIPPED
10. DVG `BLOCK_BUY` 时，Execution 不得生成买入计划

### 数据源分类
```
C 级（Confirmed）：
- 交易所行情数据
- 季报/年报财务数据
- 正式公告

I 级（Inferred）：
- 第三方筹码分布估算
- 分析师预估数据
- 模型推断数据

U 级（Unknown）：
- 缺失的 Level-2 数据
- 缺失的资金流数据
- 缺失的行业估值数据
- source_tool 失败的数据
```

## DVG 输出结构

新 run 中 canonical 路径为 `guardrailHub.dvg`，旧 `dvg` 字段必须同步回填。

```json
{
  "status": "PASS | WARN | REVIEW_ONLY | BLOCK_BUY | BLOCKED",
  "dataReliability": "HIGH | MEDIUM | LOW",
  "confirmedRatio": 0.72,
  "inferredRatio": 0.17,
  "unknownRatio": 0.11,
  "coreUnknownCount": 3,
  "freshnessStatus": "LIVE | FRESH | STALE | FAILED | UNKNOWN",
  "sourceIntegrity": "VERIFIED | PARTIAL | UNKNOWN",
  "criticalMissingData": [],
  "dataConflicts": [],
  "allowedOutputLevel": "FULL | REVIEW_ONLY | BLOCK_BUY",
  "qiamPermission": "ALLOW | ALLOW_WITH_DISCOUNT | REVIEW_ONLY | BLOCKED",
  "scenarioPermission": "ALLOW | ALLOW_WITH_DISCOUNT | REVIEW_ONLY | BLOCKED",
  "executionPermission": "ALLOW | ALLOW_WITH_DISCOUNT | REVIEW_ONLY | BLOCKED",
  "finalDecisionCap": "WAIT | REVIEW_ONLY | BLOCK_BUY",
  "hardStop": false,
  "hallucinationRiskScore": 38,
  "hallucinationRiskLevel": "LOW | MEDIUM | HIGH"
}
```
