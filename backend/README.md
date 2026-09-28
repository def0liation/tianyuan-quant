# 天元量化 Agent 工程化控制台 - 后端

## 概述

这是天元量化 Agent 工程化控制台的后端服务，提供完整的 Agent Orchestrator、配置管理、审计日志和实时事件流功能。

## 技术栈

- Python 3.11+
- FastAPI
- Pydantic
- Uvicorn
- SQLite (本地存储)

## 功能特性

### 核心功能
- Agent DAG 执行编排
- 实时事件流推送 (SSE)
- 配置版本管理和回滚
- 审计日志记录
- 决策安全守卫

### 安全特性
- 硬规则强制执行
- 配置变更策略检查
- 交易能力永久禁用
- 合规边界验证

## 安装运行

```bash
# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 启动服务
python -c "import sys, os; sys.path.insert(0, '.'); import uvicorn; from app.main import app; uvicorn.run(app, host='0.0.0.0', port=8000, reload=True)"
# 或
uvicorn app.main:app --reload --port 8000
```

## 项目结构

```
backend/
├── app/
│   ├── api/           # API 路由
│   │   ├── routes_analysis.py
│   │   ├── routes_config.py
│   │   ├── routes_audit.py
│   │   ├── routes_stream.py
│   │   └── routes_health.py
│   ├── core/          # 核心业务逻辑
│   ├── models/        # Pydantic 模型
│   ├── mock/          # Mock 数据
│   └── main.py        # 应用入口
├── requirements.txt
└── README.md
```

## API 接口

### 健康检查
- `GET /api/health` - 获取后端健康状态

### 分析任务
- `POST /api/analysis/runs` - 创建分析任务
- `POST /api/analysis/runs/{run_id}/start` - 启动分析任务
- `GET /api/analysis/runs/{run_id}` - 获取完整运行状态
- `GET /api/analysis/runs/{run_id}/nodes` - 获取节点列表
- `GET /api/analysis/runs/{run_id}/nodes/{node_id}` - 获取单节点详情

### 实时事件流
- `GET /api/analysis/runs/{run_id}/stream` - SSE 事件流

### 配置管理
- `GET /api/config/current` - 获取当前配置
- `GET /api/config/schema` - 获取配置 Schema
- `PATCH /api/config/runtime` - 保存运行时配置
- `POST /api/config/validate` - 校验配置变更
- `POST /api/config/drafts` - 创建配置草稿
- `POST /api/config/drafts/{draft_id}/apply` - 应用配置草稿
- `POST /api/config/rollback` - 回滚配置版本
- `GET /api/config/versions` - 获取配置版本历史

### 审计日志
- `GET /api/analysis/runs/{run_id}/audit` - 获取审计日志

## 安全声明

本后端服务设计为：
- 永不启用交易能力 (`trading_enabled: false`)
- 永不启用自动下单 (`auto_order_enabled: false`)
- 强制执行合规和风险控制规则
- 所有输出仅供研究参考

## 许可证

MIT License