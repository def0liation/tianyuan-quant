# 贡献指南 / Contributing

欢迎为天元量化（Tianyuan Quant）提交问题、文档和代码改进。先阅读 [README](README.md) 和 [文档索引 / Documentation index](docs/README.md)，再核对相关源码和测试。

Contributions to Tianyuan Quant are welcome. Start with the [README](README.md) and [documentation index](docs/README.md), then inspect the affected implementation and tests.

## 项目边界 / Project scope

- 本项目用于量化研究与模拟交易。SignalOps 必须保持 `SIM_*`、`simulation_only=true`、`is_real_trade=false`；不得加入真实券商下单或绕过风控的路径。
- 外部 LLM 和行情服务由使用者自行配置。存在适配器源码不代表已有凭证、已连接服务或已通过真实数据验收。
- 插件保持只读 plan 或受控 dry-run；API 的权限、审计和外联策略不能被前端状态替代。
- `lightweight-stock-analysis/` 在本发布源码中仅包含设计和实施计划，不是可安装的第二个应用。

- This project supports quantitative research and simulated trading. Preserve the `SIM_*`, `simulation_only=true`, and `is_real_trade=false` boundaries; do not add real broker orders or bypass risk controls.
- Users configure their own LLM and market-data services. Adapter source code does not establish configured credentials, live connectivity, or verified market-data coverage.
- Plugins remain read-only plans or controlled dry-runs. Frontend state must not replace server authorization, audit, or outbound-request policy.
- In this release, `lightweight-stock-analysis/` contains design and implementation plans only; it is not an installable second application.

## 环境与首装 / Environment and first setup

后端使用 Python 3.11+；前端锁文件中的 Vite 5 要求 Node.js `^18.0.0 || >=20.0.0`。Docker 文件使用 Python 3.11 和 Node.js 20。前端采用 npm，并提交了 `frontend/package-lock.json`；后端依赖以 `backend/requirements.txt` 为准，部分依赖是范围版本，尚无完整 Python 锁文件。

The backend uses Python 3.11+. Vite 5 in the frontend lockfile requires Node.js `^18.0.0 || >=20.0.0`; the Docker files use Python 3.11 and Node.js 20. The frontend uses npm with `frontend/package-lock.json`. Backend dependencies are declared in `backend/requirements.txt`; some use version ranges, and there is no complete Python lockfile.

### Windows / PowerShell

从仓库根目录运行。首次安装会创建 `backend/.venv` 并安装前后端依赖；后续启动可省略 `-Install`。如需离线演示，可先设置 mock 行情开关，演示结果不得作为真实行情验收。

Run from the repository root. First setup creates `backend/.venv` and installs backend and frontend dependencies. Omit `-Install` on later launches. The optional mock-data switch supports demonstrations; mock results do not verify live market-data capability.

```powershell
# Optional mock market data / 可选模拟行情
$env:TIANYUAN_FORCE_MOCK_MARKET_DATA = "1"
.\start-dev.ps1 -Install -Open
```

默认地址为前端 `http://127.0.0.1:5174`、后端 `http://127.0.0.1:8000`。端口占用时启动器会打印实际地址。停止使用 `.\stop-dev.ps1`；完整选项见 [START_DEV.md](START_DEV.md)。

The default frontend and backend addresses are `http://127.0.0.1:5174` and `http://127.0.0.1:8000`. The launcher prints the actual addresses if ports change. Stop with `.\stop-dev.ps1`; see [START_DEV.md](START_DEV.md) for options.

根 npm 脚本使用 `npm.cmd` 和 `powershell.exe`，属于 Windows 入口。它们不等于跨平台脚本。损坏的虚拟环境仅在明确要替换时使用 `-RecreateBackendVenv`。

Root npm scripts invoke `npm.cmd` and `powershell.exe`; they are Windows entry points. Recreate a broken virtual environment with `-RecreateBackendVenv` only when you intend to replace it.

### Linux / macOS 直接入口 / Direct commands

下面使用现有 Python 和前端入口，分别在两个终端运行。它们不提供 Windows 启动器的端口选择、进程记录和停止管理；发布验证中若未运行这些平台，不应宣称已完成平台验收。

Use the existing Python and frontend entry points in two terminals. These commands do not provide the Windows launcher's port selection, process tracking, or shutdown management. Platform support must not be claimed as verified unless it has actually been tested.

```bash
# Terminal 1, from the repository root / 终端 1，仓库根目录
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
TIANYUAN_FORCE_MOCK_MARKET_DATA=1 backend/.venv/bin/python backend/start_uvicorn.py --no-reload
```

```bash
# Terminal 2, from the repository root / 终端 2，仓库根目录
npm --prefix frontend ci
npm --prefix frontend run dev
```

本地启动会创建运行状态和 SQLite 数据库，并执行启动时的数据库准备。不要把开发启动或测试指向生产数据库。本地开发通过环境变量或 Settings 页面配置外部服务；仅复制 `.env.example` 并不使 `start-dev.ps1` 自动加载 `.env`。Docker Compose 和 portable launcher 的配置方式见各自指南。

Local startup creates runtime state and a SQLite database and performs startup database preparation. Never point development startup or tests at a production database. Configure external services through environment variables or Settings for local development; copying `.env.example` alone does not make `start-dev.ps1` load `.env`. See the deployment and portable-package guides for their configuration handling.

## 修改约定 / Change conventions

优先提交小而完整的修改，保留无关工作。修改 API 时同步 Pydantic 模型、前端类型和调用方的空值/错误处理；修改权限时验证角色边界和刷新后的状态。修改数据库结构时提供 migration、说明兼容性和回滚影响，只在隔离测试数据库中验证。

Prefer small, complete changes and preserve unrelated work. API changes must update Pydantic models, frontend types, and callers' null/error handling. Authorization changes must verify role boundaries and state after refresh. Database changes need a migration plus compatibility and rollback notes; validate them only against isolated test databases.

Agent prompt 包固定保留在 `tianyuan_quant_v10_2_multi_agent_files/tianyuan_quant_v10_2_multi_agent/`。[agent_framework.py](backend/app/core/agent_framework.py) 会读取它，Docker 镜像也会复制它。不要把该目录作为旧文档移动或删除；当前活跃 Agent 以代码 manifest 和 [Agent Registry](docs/AGENT_REGISTRY.md) 为准。

Keep the runtime prompt package at `tianyuan_quant_v10_2_multi_agent_files/tianyuan_quant_v10_2_multi_agent/`. [agent_framework.py](backend/app/core/agent_framework.py) reads this path, and the Docker image copies it. Do not move or remove it as historical documentation. The code manifest and [Agent Registry](docs/AGENT_REGISTRY.md) define the active agents.

## 验证 / Validation

从仓库根目录运行与变更相关的检查。Windows 首装后的后端环境位于 `backend/.venv`；下面显式指定该 Python，使测试包装器使用已安装的依赖。未指定时包装器会尝试根 `.venv` 或 Python + `uv`，可能需要额外安装 `uv`。

Run checks appropriate to the change from the repository root. Windows first setup uses `backend/.venv`; the override below makes the test wrapper use that installed environment. Without it, the wrapper tries the root `.venv` or Python plus `uv`, which may require installing `uv` separately.

```powershell
$env:TIANYUAN_BACKEND_TEST_PYTHON = (Resolve-Path .\backend\.venv\Scripts\python.exe).Path
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run build
npm.cmd run test:backend
# Full backend suite / 全量后端测试
npm.cmd run test:backend:all
```

跨平台直接检查：

Direct checks for Linux/macOS:

```bash
npm --prefix frontend run typecheck
npm --prefix frontend run lint
npm --prefix frontend run build
backend/.venv/bin/python -m pytest backend/tests -q
```

- `test:backend` 默认运行选定的后端回归集；`test:backend:all` 才运行整个 `backend/tests`。
- `test:frontend` 是 TypeScript 类型检查，不是前端单元测试。当前 `frontend/package.json` 未定义单元测试脚本。
- 前端页面改动还需 `npm.cmd run smoke:frontend`，并按 [测试指南](docs/TESTING_GUIDE.md) 做相应浏览器/响应式检查。静态 smoke 不能代替浏览器验收；浏览器脚本使用 Playwright，须先准备相应浏览器。
- 纯文档改动核对实际内容、相对链接和差异，不需要新增形式化测试。报告实际运行的检查和未验证项，不能复用旧日志中的通过数量作为本次结果。

- `test:backend` runs a selected backend regression suite; `test:backend:all` runs all of `backend/tests`.
- `test:frontend` is a TypeScript check, not a frontend unit-test suite. `frontend/package.json` currently has no unit-test script.
- Page changes also require `npm.cmd run smoke:frontend` and the relevant browser/responsive checks in the [testing guide](docs/TESTING_GUIDE.md). Static smoke does not replace browser validation. Browser scripts use Playwright and require the relevant browser installation.
- Documentation-only changes need content, relative-link, and diff checks, without new formal tests. Report checks actually run and remaining gaps; old logged pass counts are not current results.

## 提交问题与 Pull Request / Issues and pull requests

问题报告包含复现步骤、预期与实际行为、系统和运行版本，以及脱敏错误信息。PR 说明改了什么、为什么改、验证命令和结果、兼容性或未验证风险。贡献遵循仓库根目录 `LICENSE` 的 MIT 许可。

Issue reports should include reproduction steps, expected and actual behavior, OS/runtime versions, and redacted errors. PRs should explain the change, its reason, validation commands/results, and compatibility or unverified risks. Contributions follow the MIT license in the root `LICENSE` file.

不得提交真实 API key、token、私有接口地址、个人配置、账户/持仓数据、数据库、运行记录、secret vault、日志或截图中的敏感信息。使用空白模板或虚构的测试数据。发现凭证泄露时先撤销或轮换凭证，不要在公开 Issue 中粘贴秘密；详见 [开源范围](docs/OPEN_SOURCE_SCOPE.md)。

Do not commit real API keys, tokens, private endpoints, personal configuration, account/position data, databases, run records, secret vaults, or sensitive logs/screenshots. Use blank templates or fictional test data. Revoke or rotate leaked credentials before addressing publication, and never paste secrets into a public issue; see [open-source scope](docs/OPEN_SOURCE_SCOPE.md).
