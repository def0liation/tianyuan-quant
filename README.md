# 天元量化 · Tianyuan Quant

**本地量化研究与模拟交易控制台**

[English](README.en.md) · [文档索引](docs/README.md) · [贡献指南](CONTRIBUTING.md) · [MIT 许可证](LICENSE)

天元量化把行情与持仓输入、多 Agent 分析、风险守卫、模拟股票池、回测和研究复盘连接到一个本地控制台。前端采用 React / TypeScript，后端采用 FastAPI / SQLAlchemy / SQLite。

当前版本用于研究与模拟。SignalOps 动作采用 `SIM_*`，保持 `simulation_only=true`、`is_real_trade=false`；不连接真实券商，不提供实盘自动下单，也不承诺收益。分析输出不构成投资建议。

## 功能

| 模块 | 内容 |
| --- | --- |
| 分析与 Agent DAG | 分析任务、执行节点、事件流、历史对比和最终报告 |
| 数据可靠性 | 行情适配器、数据源健康、新鲜度和降级状态 |
| 量化核心 | 市场状态、K 线技术面、QIAM 和辅助研究证据 |
| 风险与权限 | DVG 证据门、风险守卫、权限边界和审计 |
| SignalOps | 模拟股票池、自动模拟循环和候选参数审查 |
| Research Lab | 回测、研究线索、Case / Knowledge / Evaluation 闭环 |
| 配置与插件 | 配置版本、参数管理、插件登记与受限运行 |

## 快速开始

准备 Node.js 20+、npm 和 Python 3.13。Windows 启动器需要 PowerShell；`uv` 可作为 Python 环境与测试的辅助工具。安装依赖会访问软件包仓库。真实行情或 LLM 分析能力取决于各提供方的配置和授权，不附带个人账号。

```powershell
git clone https://github.com/def0liation/tianyuan-quant.git
cd tianyuan-quant
.\start-dev.ps1 -Install -Open
```

后续启动和关闭：

```powershell
.\start-dev.ps1 -Open
.\stop-dev.ps1
```

默认地址为前端 `http://127.0.0.1:5174`、后端 `http://127.0.0.1:8000`、API 文档 `http://127.0.0.1:8000/docs`。端口占用时启动器会选择后续可用端口，以终端输出为准。启动状态可查看 `GET /api/startup/status`；部分模块会在核心就绪后继续加载。

首次启动会创建本地存储；后端可能对其本地数据库执行启动迁移。不要将开发实例指向生产数据库。已有虚拟环境损坏时，先查看 [启动器说明](START_DEV.md)，再决定是否显式重建。

macOS / Linux 可在两个终端分别启动，下面是源码入口命令；本次开源整理未验证这两个平台：

```bash
# Terminal 1: backend
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install --require-hashes -r backend/requirements.lock
cd backend
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```bash
# Terminal 2: frontend, from repository root
npm ci
npm --prefix frontend ci
npm --prefix frontend run dev
```

## API 与个人配置

仓库仅包含接口实现和空凭证字段的 [.env.example](.env.example)。**你的 API Key、Token、私有接口地址、持仓、数据库、运行日志和历史记录不随源码发布。** 运行时设置、密钥与本地存储应保留在自己的环境中。

后端从进程环境读取相关变量；仅复制 `.env.example` 为 `.env` 不等于自动加载所有变量。可按 [部署说明](docs/DEPLOYMENT.md) 或自己的进程管理方式注入环境。该示例采用生产环境的严格鉴权字段，不能把空 Token 当作可用生产配置。

不要把秘密放进 `VITE_*` 变量或前端源码，因为它们可能进入浏览器构建产物。公开数据源地址与测试占位值是程序示例，不是个人配置。详见 [开源范围](docs/OPEN_SOURCE_SCOPE.md)。

## 项目结构

| 路径 | 作用 |
| --- | --- |
| `frontend/src/` | 活跃前端：页面、API 客户端、状态、类型与组件 |
| `backend/app/` | 后端：路由、业务核心、Agent 模块和数据库层 |
| `backend/tests/` | 后端回归测试与仓库规范检查 |
| `scripts/` | 启动辅助、测试、smoke、备份和打包脚本 |
| `docs/` | 当前指南、接口契约、规则与历史方案 |
| `tianyuan_quant_v10_2_multi_agent_files/` | 运行时需要的 Agent 提示词与协议文档，保留原路径 |
| `lightweight-stock-analysis/` | 独立轻量版的规划资料，本快照不含其未完成实现 |
| `storage/`、`backend/app/storage/`、`.logs/` | 本地数据和运行产物，排除在公开文件外 |

保留现有源码路径以避免破坏运行时引用。文档按用途的分类见 [文档索引](docs/README.md)，历史计划不代表当前已实现功能。

## 开发与验证

Windows 根目录命令会转发到实际前端或测试脚本：

```powershell
npm.cmd ci
npm.cmd --prefix frontend ci
$env:TIANYUAN_BACKEND_TEST_PYTHON = (Resolve-Path .\backend\.venv\Scripts\python.exe).Path
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run build
npm.cmd run test:backend
# 全部后端回归
npm.cmd run test:backend:all
```

`test:backend` 是项目定义的聚焦回归集合；`test:backend:all` 运行全部后端测试。脚本可通过 `TIANYUAN_BACKEND_TEST_PYTHON` 指定可用 Python，否则使用项目约定的 Python / uv 环境。更多说明见 [测试指南](docs/TESTING_GUIDE.md) 和 [贡献指南](CONTRIBUTING.md)。

## 当前限制

当前验证以 Windows 本地源码和隔离测试为范围。Docker 已补齐迁移配置、Python 3.13 哈希锁文件和 readiness；CI 包含 Windows 回归及 Linux 容器启动检查。新增 CI 尚未在 GitHub 执行，Linux/macOS、Docker 实际启动和真实数据服务仍未验收。运维与历史保留规则见 [审计修复与运维说明](docs/AUDIT_REMEDIATION_2026-09-29.md)。

## 许可证

源码和文档采用 [MIT License](LICENSE)。第三方依赖使用各自许可证；数据源、模型服务和数据集需遵守提供方的授权要求。本项目不附带行情或 LLM 服务凭证。
