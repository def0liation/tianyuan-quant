# Frontend and Backend Launcher

Use the root launcher to start the FastAPI backend and Vite frontend together.

## Start

```powershell
.\start-dev.ps1
```

Open the browser automatically:

```powershell
.\start-dev.ps1 -Open
```

First-time setup or dependency refresh:

```powershell
.\start-dev.ps1 -Install
```

If `backend\.venv` already exists but is broken, `-Install` will not remove it
implicitly. Recreate that backend virtualenv only when you mean to replace it:

```powershell
.\start-dev.ps1 -Install -RecreateBackendVenv
```

Double-click alternative:

```text
start-dev.cmd
```

## Stop

Stop the local frontend and backend launched from this workspace:

```powershell
.\stop-dev.ps1
```

Double-click alternative:

```text
stop-dev.cmd
```

NPM alternative:

```powershell
npm.cmd run dev:stop
```

The stop launcher first reads `.logs/dev-processes.json`, then checks the known
dev port ranges (`8000-8019` and `5174-5193`) so a backend left running after
the frontend closes can still be stopped. Use `.\stop-dev.ps1 -StateOnly` to
stop only processes recorded by the latest launcher state.

## URLs

- Frontend: `http://127.0.0.1:5174`
- Backend: `http://127.0.0.1:8000`
- API docs: `http://127.0.0.1:8000/docs`

If a default port is already occupied or an old process is listening but not
usable, the launcher moves to the next available port and prints the actual
Frontend, Backend, and API docs URLs.

## Options

```powershell
.\start-dev.ps1 -BackendPort 8000 -FrontendPort 5174
```

The managed launcher starts the backend without uvicorn reload by default so
`stop-dev.ps1` can close it reliably on Windows. Use `-BackendReload` when you
need backend file watching during active development.

Logs are written to `.logs/` with a per-run suffix so repeated launches do not
reuse log files that may still be held by older processes.

Press `Ctrl+C` in the launcher terminal to stop the processes started by the launcher.
If that terminal has already been closed or a child process is still running,
use `.\stop-dev.ps1`.
