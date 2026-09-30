# CLAUDE.md — Tianyuan Quant Multi-Agent Console

## Project Overview

`super` (天元量化) is a local quantitative research and simulated trading control console. It covers analysis tasks, Agent DAG, market data & position inputs, SignalOps simulated stock pools, Research Backtest, Research Lab, Case/Knowledge/Evaluation modules, plugin registration, configuration governance, audit trails, and startup observability.

**Scope:** Research & simulation environment — NOT a production auto-trading system. No real broker connections. All SignalOps actions use `SIM_*` prefixes.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.13, FastAPI 0.104, SQLAlchemy 2.0 (async), SQLite via aiosqlite |
| Frontend | React 18, TypeScript 5.x, Vite 5.x, Tailwind CSS 3.x, Zustand 4.x, React Router 6.x |
| Charts | Recharts 2.x, ReactFlow 11.x |
| Dev tools | Alembic (migrations), Pytest (backend tests), ESLint (frontend lint), Playwright (E2E smoke) |

## Quick Start

```powershell
# Start backend + frontend (opens browser)
.\start-dev.ps1 -Open

# Stop local dev processes
.\stop-dev.ps1

# Type-check only
npm run typecheck
```

- Frontend: `http://127.0.0.1:5174`
- Backend: `http://127.0.0.1:8000`
- API docs: `http://127.0.0.1:8000/docs`

## Directory Structure

```
super/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app, lifespan, middleware, CORS, routers
│   │   ├── api/                  # Route handlers (routes_*.py) — one per domain
│   │   ├── core/                 # Business logic: agents, stores, services, adapters
│   │   ├── db/                   # SQLAlchemy models, session, migrations, repositories
│   │   ├── models/               # Pydantic models (request/response schemas)
│   │   ├── modules/              # Agent module implementations (quant_core, etc.)
│   │   ├── mock/                 # Mock data for development
│   │   └── storage/              # Runtime JSON/file storage (gitignored)
│   └── tests/                    # Pytest tests
├── frontend/
│   ├── src/
│   │   ├── App.tsx               # Root: ErrorBoundary → AppShell → Routes
│   │   ├── api/                  # HTTP client modules (one per backend domain)
│   │   ├── components/           # React components organized by domain
│   │   ├── store/                # Zustand stores (useAnalysisStore, useToastStore, etc.)
│   │   ├── types/                # TypeScript type definitions
│   │   ├── hooks/                # Custom React hooks
│   │   ├── guards/               # Runtime safety guards
│   │   └── utils/                # Utility functions
│   └── dist/                     # Build output
├── docs/                         # Architecture & rules documentation
├── scripts/                      # PowerShell/Node utility scripts
├── storage/                      # Persistent data (DB, runs, artifacts)
└── .logs/                        # Dev launcher logs
```

## Key Architectural Patterns

### Backend

- **Lifespan startup** ([main.py](backend/app/main.py)): DB migrations → schema → core ready → optional warmers (analysis history, research summary, backtest summary, plugin defaults, market data status, auto-paper loop)
- **Auth middleware** ([core/http_auth.py](backend/app/core/http_auth.py)): Role-based token auth with `secrets.compare_digest`. Supports `API_AUTH_MODE` env var (strict/write/off). Roles: admin, operator, researcher, viewer.
- **Agent execution** ([core/agent_executor.py](backend/app/core/agent_executor.py)): Orchestrates multi-agent runs through DAG nodes — module execution → LLM execution → output normalization → audit trail.
- **Store pattern**: Each domain has a store class (e.g., `BacktestStore`, `ResearchStore`) with async methods managing file-based JSON persistence + SQLite queries.
- **Route → Store → DB**: Routes delegate to stores, stores use both file I/O and SQLAlchemy (async session with aiosqlite).

### Frontend

- **Lazy loading**: All page components use `React.lazy()` with Suspense ([App.tsx](frontend/src/App.tsx)).
- **State management**: Zustand with per-domain stores. Use `useAnalysisStore`, `useToastStore`, `useBackendStore`, `useTuningStore`.
- **API clients**: Each domain has a client module wrapping `request<T>()` from [httpClient.ts](frontend/src/api/httpClient.ts) with timeout support and auth headers.
- **Error reporting**: Use `reportError()` / `reportWarning()` from [utils/errorReport.ts](frontend/src/utils/errorReport.ts) instead of raw `console.error`.
- **Error boundaries**: Global `ErrorBoundary` wraps the entire `AppShell`.

## Common Commands

```powershell
# Development
npm run dev                     # Frontend only
npm run dev:all                 # Full stack via launcher script

# Testing
npm run test:backend            # Run backend tests
npm run test:backend:all        # Run ALL backend tests
npm run test:frontend           # Type-check frontend

# Linting & Quality
npm run typecheck               # Frontend TypeScript check
npm run lint                    # Frontend ESLint (max-warnings 0)
npm run build                   # Production build

# Smoke tests
npm run smoke:frontend          # Route smoke test
npm run smoke:frontend:responsive  # Responsive smoke test
npm run smoke:analysis-worker   # Analysis worker smoke test
npm run smoke:closed-loop-participation  # Full chain smoke test
```

## Environment Variables

See [`.env.example`](.env.example) for the full list. Key variables:

| Variable | Purpose |
|----------|---------|
| `LLM_API_KEY` | LLM provider API key |
| `TUSHARE_TOKEN` | TuShare market data token |
| `API_AUTH_MODE` | Auth mode: `strict`, `write`, `off` |
| `API_WRITE_TOKEN` | Write API bearer token |
| `APP_ENV` | Environment: `production`, `staging`, `development` |
| `CORS_ORIGINS` | Comma-separated allowed origins (production) |
| `TIANYUAN_QUANT_DB_URL` | Database URL (defaults to SQLite) |

## Code Conventions

- **Python**: async/await throughout, Pydantic models for validation, `logging.getLogger(__name__)` for logging
- **TypeScript**: Strict mode, prefer explicit types over `any`, use `interface` over `type` for objects
- **CSS**: Tailwind utility classes with CSS custom properties for Material Design tokens
- **Naming**: snake_case (Python), camelCase (TypeScript), kebab-case (CSS/URLs)
- **Error handling**: Backend routes raise `HTTPException`; frontend uses `reportError()` utility
