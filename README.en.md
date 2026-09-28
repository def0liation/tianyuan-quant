# Tianyuan Quant · 天元量化

**A local quantitative research and paper-trading console**

[中文](README.md) · [Documentation](docs/README.md) · [Contributing](CONTRIBUTING.md) · [MIT License](LICENSE)

Tianyuan Quant connects market and portfolio inputs, multi-Agent analysis, risk checks, simulated stock pools, backtesting, and research review in a local console. It uses React / TypeScript for the frontend and FastAPI / SQLAlchemy / SQLite for the backend.

The current version is a research and simulation environment. SignalOps actions use `SIM_*`, `simulation_only=true`, and `is_real_trade=false`. It does not connect to real brokers or provide automated live orders, and it does not promise returns. Analysis output is not investment advice.

## Features

| Area | Capability |
| --- | --- |
| Analysis and Agent DAG | Analysis runs, execution nodes, event streams, run comparison, and final reports |
| Data reliability | Market adapters, provider health, freshness, and degraded-state reporting |
| Quant core | Market regimes, technical analysis, QIAM, and supporting research evidence |
| Risk and permissions | DVG evidence gates, risk checks, permission boundaries, and audit trails |
| SignalOps | Simulated stock pools, automatic paper-trading loops, and parameter review |
| Research Lab | Backtesting, research traces, and Case / Knowledge / Evaluation workflows |
| Configuration and plugins | Configuration versions, parameters, plugin registration, and constrained execution |

## Quick start

Install Node.js 20+, npm, and Python 3.11+. The Windows launcher requires PowerShell. `uv` can assist with Python environments and tests. Dependency installation accesses package registries. Live market data and LLM analysis depend on provider configuration and authorization; personal accounts are not included.

```powershell
git clone https://github.com/def0liation/tianyuan-quant.git
cd tianyuan-quant
.\start-dev.ps1 -Install -Open
```

For subsequent starts and shutdown:

```powershell
.\start-dev.ps1 -Open
.\stop-dev.ps1
```

Default URLs are `http://127.0.0.1:5174` for the frontend, `http://127.0.0.1:8000` for the backend, and `http://127.0.0.1:8000/docs` for API documentation. When a port is occupied, the launcher selects another available port; use the URLs printed in the terminal. `GET /api/startup/status` reports readiness, while some modules continue warming after the core is ready.

First launch creates local storage. Backend startup may run migrations against its local database. Do not point a development instance at a production database. If an existing virtual environment is broken, read the [launcher guide](START_DEV.md) before explicitly recreating it.

For macOS / Linux, the source entry points can be started in two terminals. These platforms were not validated during this publication task:

```bash
# Terminal 1: backend
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
cd backend
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```bash
# Terminal 2: frontend, from repository root
npm ci
npm --prefix frontend ci
npm --prefix frontend run dev
```

## APIs and personal configuration

The repository contains API implementations and [.env.example](.env.example) with blank credential fields. **Your API keys, tokens, private endpoints, portfolio data, databases, logs, and run history are excluded from publication.** Keep runtime settings, secrets, and storage in your own environment.

The backend reads process environment variables. Copying `.env.example` to `.env` alone does not automatically load all variables. Follow the [deployment guide](docs/DEPLOYMENT.md) or inject variables through your process manager. The example includes strict production authentication settings; blank tokens are not a working production configuration.

Never put secrets in `VITE_*` variables or frontend source, as they may enter browser bundles. Public provider URLs and obvious test placeholders are implementation examples rather than personal configuration. See [open-source scope](docs/OPEN_SOURCE_SCOPE.md).

## Project layout

| Path | Purpose |
| --- | --- |
| `frontend/src/` | Active frontend: pages, API clients, state, types, and components |
| `backend/app/` | Backend routes, core services, Agent modules, and database layer |
| `backend/tests/` | Backend regressions and repository hygiene checks |
| `scripts/` | Launch support, tests, smoke checks, backups, and packaging |
| `docs/` | Current guides, API contracts, rules, and historical plans |
| `tianyuan_quant_v10_2_multi_agent_files/` | Agent prompts and protocol documents required at runtime; keep this path |
| `lightweight-stock-analysis/` | Plans for an independent lightweight version; unfinished implementation is excluded |
| `storage/`, `backend/app/storage/`, `.logs/` | Local data and runtime artifacts, excluded from public files |

Existing source paths are retained to preserve runtime references. The [documentation index](docs/README.md) groups documents by purpose. Historical plans are not evidence of implemented features.

## Development and validation

On Windows, root commands delegate to the frontend or backend test wrapper:

```powershell
npm.cmd ci
npm.cmd --prefix frontend ci
$env:TIANYUAN_BACKEND_TEST_PYTHON = (Resolve-Path .\backend\.venv\Scripts\python.exe).Path
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run build
npm.cmd run test:backend
# Complete backend regression suite
npm.cmd run test:backend:all
```

`test:backend` runs the project's focused regression set; `test:backend:all` runs the complete backend suite. Set `TIANYUAN_BACKEND_TEST_PYTHON` to select a working interpreter, or use the wrapper's Python / uv environment selection. See the [testing guide](docs/TESTING_GUIDE.md) and [contributing guide](CONTRIBUTING.md).

## Current limitations

This publication validates local Windows source and tests. Linux/macOS, Docker deployment, and live data services have not been accepted as verified. The current `Dockerfile` does not copy `backend/alembic.ini`; complete the migration configuration before production startup rather than treating example deployment files as a validated production release. Some backend dependencies use version ranges, and there is no complete Python lockfile.

## License

Code and documents are released under the [MIT License](LICENSE). Dependencies retain their own licenses. Market-data services, model services, and datasets remain subject to their providers' authorization requirements. No market-data or LLM credentials are included.
