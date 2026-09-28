# Windows Portable Package

This project can be shared as a Windows portable zip. The receiver does not need
to install Node.js or Python because the package includes the runtime files and
dependencies needed by the launcher.

## Create The Zip

Run this from the project root:

```powershell
.\scripts\create-portable-package.ps1
```

The zip is written directly to the current user's Desktop:

```text
super-portable-<timestamp>.zip
```

Run a non-writing check first:

```powershell
.\scripts\create-portable-package.ps1 -DryRun
```

The packaging script excludes local secrets and runtime state, including `.env`,
databases, logs, `backend/app/storage`, virtual environments, caches, and build
outputs. It keeps `.env.example` so the receiver can create their own config.

## Use The Portable Package

1. Extract the zip on a Windows 64-bit computer.
2. Open the extracted project folder.
3. If `.env` does not exist, the first launcher run creates it from
   `.env.example`.
4. Fill the receiver's own values in `.env` when needed:
   `API_WRITE_TOKEN`, `LLM_API_KEY`, `TUSHARE_TOKEN`, and
   `MARKET_DATA_API_KEY`.
5. Double-click `start-portable.cmd`.

The launcher prints the local frontend and backend URLs. It uses only files
inside the package:

- `runtime/node`
- `runtime/python`
- `runtime/python-deps`
- `frontend/node_modules`

If strict API write auth is enabled and `API_WRITE_TOKEN` is empty, the app can
still start, but write APIs are blocked until the receiver fills their own token.

## Stop

Keep the launcher window open while using the app. Press `Ctrl+C` in that window
to stop the backend and frontend started by the portable launcher.

Generated logs are written to `.logs/` inside the extracted package and are not
included in future packages.

The first run also creates local SQLite/runtime storage folders inside the
extracted package. These files belong to the receiver and are not included in
the shared zip.
