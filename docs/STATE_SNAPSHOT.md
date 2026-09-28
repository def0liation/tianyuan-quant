# State Snapshot 状态快照指南

## 概述

每次分析完成后，系统自动生成 State Snapshot（状态快照），包含该次分析的完整上下文。State Snapshot 用于状态恢复、审计回放和跨版本兼容校验。

## State Snapshot 内容

```json
{
  "auditId": "AUD_KS_001",
  "runId": "RUN_MOCK_STANDARD",
  "snapshot_type": "FULL",
  "state": {
    "runMode": "STANDARD_MODE",
    "environment": "API_ORCHESTRATED",
    "dataMode": "MOCK",
    "stockCode": "603663",
    "stockName": "柯利达",
    "taskType": "持仓复核",
    "agentResults": [...],
    "dvg": {...},
    "killSwitch": {...},
    "finalAction": "WAIT",
    "dagEvents": [...],
    "auditLog": [...]
  },
  "schemaVersion": "10.2",
  "checksum": "sha256...",
  "createdAt": "2026-05-11T12:00:00"
}
```

## 校验规则

1. State Snapshot 必须有 checksum
2. checksum 不匹配时必须拒绝恢复
3. schemaVersion 不兼容时必须进入 REVIEW_ONLY
4. 恢复前必须经过 State Validation Agent
5. State Snapshot 不得覆盖当前系统规则
6. State Snapshot 只能作为恢复上下文

## 存储

State Snapshot 存储在 `state_snapshots` 表中。

## 数据库 Schema

```sql
CREATE TABLE state_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    snapshot_type TEXT DEFAULT 'FULL',
    state_json TEXT,
    schema_version TEXT DEFAULT '10.2',
    checksum TEXT,
    created_at TEXT
);
```
