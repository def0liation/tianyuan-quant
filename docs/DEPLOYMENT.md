# Deployment Guide

The 2026-09-29 changes and complete-history archive/backup commands are documented in [Audit remediation and operations](AUDIT_REMEDIATION_2026-09-29.md). The new container CI has not yet run on GitHub. Treat Compose syntax validation and isolated Windows tests separately from actual container acceptance.

This project is deployed as two services:

- `backend`: FastAPI on port `8000`
- `frontend`: static React build served by Nginx on port `5174`, proxying `/api/*` to the backend

The production compose file keeps runtime state outside the image:

- `deploy/db` stores the SQLite database.
- `deploy/backend-storage` stores runtime config, run records, knowledge iterations, and Agent profile data.
- API keys are read from `.env` or from the Settings page after deployment.
- `API_WRITE_TOKEN` is required by the production compose file so mutating API requests are protected in strict mode.

## 1. Prepare Environment

```powershell
Copy-Item .env.example .env
```

Edit `.env` and fill only the keys you need:

```text
LLM_API_KEY=
LLM_BASE_URL_ALLOWLIST=
TUSHARE_TOKEN=
MARKET_DATA_API_KEY=
MARKET_DATA_BASE_URL_ALLOWLIST=
APP_ENV=production
API_WRITE_TOKEN=
API_AUTH_MODE=strict
LOCAL_OPERATOR_ID=local_admin
LOCAL_OPERATOR_ROLE=admin
SEED_MOCK_HISTORY=0
```

Do not commit `.env`, `deploy/db`, or `deploy/backend-storage`.

## 2. Start Production Stack

```powershell
.\start-prod.ps1 -Build -Open
```

Equivalent Docker command:

```powershell
docker compose -f docker-compose.prod.yml --env-file .env up -d --build
```

Open:

- Frontend: http://localhost:5174
- Backend health: http://localhost:8000/api/health
- Backend readiness: http://localhost:8000/api/ready
- Backend metrics: http://localhost:8000/api/metrics

## 3. Stop Or Upgrade

```powershell
docker compose -f docker-compose.prod.yml down
docker compose -f docker-compose.prod.yml --env-file .env up -d --build
```

The mounted data folders are preserved by `down`.

## 4. Database Migrations

Backend startup runs Alembic `upgrade head` before serving requests. Production startup fails fast if migrations cannot complete while `APP_ENV=production` or `REQUIRE_DB_MIGRATIONS=1` is set.

Use `TIANYUAN_SKIP_ALEMBIC=1` only for controlled local development fallback. Do not use it to bypass production schema failures.

## 5. Backup

Back up these folders before upgrades:

```text
deploy/db
deploy/backend-storage
```

For the SQLite database helper, run:

```powershell
.\scripts\db-backup.ps1 -SourceDb .\deploy\db\tianyuan_quant.db -BackupDir .\deploy\backups\db
.\scripts\db-restore.ps1 -BackupFile .\deploy\backups\db\<backup-file>.db -TargetDb .\deploy\db\tianyuan_quant.db
.\scripts\db-restore.ps1 -BackupFile .\deploy\backups\db\<backup-file>.db -TargetDb .\deploy\db\tianyuan_quant.db -Force
```

Run restore without `-Force` first to validate the backup and target paths; add `-Force` only when intentionally replacing the target database.

For a non-production local drill that writes only under `.tmp\db-backup-restore-drill`, run:

```powershell
npm.cmd run smoke:db-backup-restore
```

The drill exercises `db-backup.ps1`, `db-restore.ps1 -DryRun`, `db-restore.ps1 -Force`, manifest/checksum validation, and SQLite integrity verification on temporary databases. It does not replace scheduled off-host production backups for `deploy/db` and `deploy/backend-storage`.

For a non-production off-host copy drill that writes only under `.tmp\db-offhost-backup-drill`, run:

```powershell
npm.cmd run smoke:db-offhost-backup
```

The off-host drill creates a temporary SQLite source database, runs the normal backup helper, copies the backup file plus manifest into a separate simulated off-host directory, and verifies the copied backup checksum against the manifest. This proves the copy/manifest verification workflow only; production still needs a real off-host destination, retention policy, and coverage for `deploy/backend-storage`, secret vault files, and key files.

For a non-production backend storage restore drill that writes only under `.tmp\storage-offhost-restore-drill`, run:

```powershell
npm.cmd run smoke:storage-offhost-restore
```

The storage drill creates a temporary `deploy/backend-storage`-style tree with runtime JSON, run artifacts, plugin artifacts, ops logs, `agent_runtime.secrets.json`, and `agent_runtime.secret.key`, copies it to a simulated off-host directory, restores it into a separate temporary directory, and verifies every restored file by SHA-256 manifest. It proves the bundle/copy/restore verification workflow only; production still needs a real off-host destination, retention policy, schedule ownership, access controls, and recurring restore records for the actual deployment volumes.

## 6. Security Notes

Local development may create `backend/app/storage/agent_runtime.json` with API keys. The deployment image excludes the whole `backend/app/storage` directory through `.dockerignore`, so secrets are not baked into the image.

Production or strict mode protects mutating `/api` requests with the backend write-auth middleware. Set `APP_ENV=production` or `API_AUTH_MODE=strict`, and provide `API_WRITE_TOKEN` or `SUPER_API_WRITE_TOKEN`. Do not expose backend port `8000` publicly unless write requests require `Authorization: Bearer <token>`, `X-API-Key`, or `X-Super-API-Key`.

Mutating requests also carry a local operator profile. Set `LOCAL_OPERATOR_ID` and `LOCAL_OPERATOR_ROLE` on the backend host, or pass `X-Operator-ID` and `X-Operator-Role` from a trusted local client. Supported roles are `viewer`, `researcher`, `operator`, and `admin`; high-risk config/plugin/delete writes require `admin`, while SignalOps command writes require at least `operator`. This is not a login/session system.

Local development keeps auth disabled by default so the app remains easy to run on `127.0.0.1`.

Use the Settings page or `.env` to configure:

- LLM API profile
- Tushare or other market data profile
- Agent routing and enablement

### P1 Runtime Configuration Requirements

LLM and market-data profiles can send backend-held keys to `base_url`. In production, treat every profile write as a privileged configuration change:

- Keep `APP_ENV=production`, `API_AUTH_MODE=strict`, and a non-empty `API_WRITE_TOKEN` or `SUPER_API_WRITE_TOKEN`.
- Prefer the built-in provider endpoints shown in the Agent runtime UI. Custom LLM `base_url` values must be added to `LLM_BASE_URL_ALLOWLIST`/`LLM_EGRESS_ALLOWLIST`/`LLM_ALLOWED_HOSTS`, or the profile must be saved with `egress_confirmed=true` by an authenticated operator before a live outbound request is allowed, even when no API key is configured.
- Custom market-data `base_url` or absolute `quote_path` values must be added to `MARKET_DATA_BASE_URL_ALLOWLIST`/`MARKET_DATA_EGRESS_ALLOWLIST`/`MARKET_DATA_ALLOWED_HOSTS` before any strict-mode live request is allowed. UI confirmation does not bypass this backend allowlist, and localhost is blocked in strict mode unless explicitly allowlisted.
- Set `AGENT_RUNTIME_SECRET_KEY` in production and keep it outside the repository. Runtime LLM keys, Market Data keys, and the Tushare token are stored as encrypted secret references in `agent_runtime.secrets.json`; the main `agent_runtime.json` contains only `secret_refs` and masked public status.
- Use `AGENT_RUNTIME_SECRET_VAULT_FILE` and `AGENT_RUNTIME_SECRET_KEY_FILE` if the vault or local key file must live outside the app storage volume. If `AGENT_RUNTIME_SECRET_KEY` is not set, the backend creates a local `agent_runtime.secret.key` next to the runtime storage. This is acceptable for local development but not for managed production, because backup/restore and host access controls must protect both the key file and vault.
- To rotate the production runtime secret key: set `AGENT_RUNTIME_SECRET_KEY` to the new key, set `AGENT_RUNTIME_SECRET_KEY_PREVIOUS` to the old key only for the rotation command, run `python -m app._runtime_secret_admin rotate` from the backend environment, verify with `python -m app._runtime_secret_admin verify`, then remove `AGENT_RUNTIME_SECRET_KEY_PREVIOUS`.
- Do not record plaintext API keys in screenshots, logs, audit notes, browser storage, or documentation. UI surfaces must show only `api_key_set` and masked values.
- Configuration audit evidence should include actor, timestamp, profile id, old/new `base_url` host, auth mode, and whether a key is set. It must not include the key itself.
- If a production write is rejected by strict validation or write auth, fix the allowlist/token configuration rather than temporarily exposing port `8000` without auth.

## 7. Operations Readiness

Use `/api/ready` for dependency-aware readiness checks and `/api/metrics` for JSON runtime counters. Every response includes `X-Request-ID` and `X-Response-Time-ms`; operators can also pass an inbound `X-Request-ID` to correlate frontend, proxy, and backend logs.

Alert on repeated readiness `degraded` status, `/api/metrics.productionHealth.alerts`, stale analysis jobs, exhausted error budget, unusually high response time, failed migrations, and backup or restore failures. SignalOps tick trend coverage is currently `latest_only`, so do not treat it as a full historical time series.

The backend provides a local durable alert outbox for production health alerts:

```powershell
Invoke-RestMethod http://localhost:8000/api/ops/alerts/status
Invoke-RestMethod -Method Post http://localhost:8000/api/ops/alerts/dispatch
```

`POST /api/ops/alerts/dispatch` records the current `/api/metrics.productionHealth.alerts` into `backend/app/storage/production_alerts.jsonl` by default, or `PRODUCTION_ALERT_OUTBOX_FILE` when set. The endpoint is admin-gated in strict/production auth. Set `PRODUCTION_ALERT_WEBHOOK_URL` to enable a generic JSON webhook provider; `PRODUCTION_ALERT_WEBHOOK_TIMEOUT_SECONDS` defaults to 3 seconds and is clamped to 0.5-30 seconds. `PRODUCTION_ALERT_WEBHOOK_MAX_ATTEMPTS` defaults to 1 and is clamped to 1-5; `PRODUCTION_ALERT_WEBHOOK_RETRY_BACKOFF_SECONDS` defaults to 0 and is clamped to 0-5 seconds. Webhook delivery failures are retried only within that bounded attempt limit, then recorded as `delivery_status="failed"` without blocking local outbox persistence. Leave the webhook unset for the default local-only mode.

The backend also writes a local structured ops event log for API requests and ops events:

```powershell
Invoke-RestMethod "http://localhost:8000/api/ops/logs/status?limit=20"
```

By default this writes to `backend/app/storage/ops_events.jsonl`; set `OPS_LOG_FILE` to place it on a deployment volume. Request events include request id, method, path without query string, status code, duration, and client host. They do not include request headers, authorization values, bodies, or query strings. The endpoint reports `channel="local_file_jsonl"` and `external_delivery_enabled=false`; production deployments still need a log shipper/provider for centralized search, retention, dashboards, and alert routing.

Plugin package uploads are stored under `backend/app/storage/plugin_artifacts` by default, or `TIANYUAN_PLUGIN_ARTIFACT_DIR` when set. Uploads are hash-verified, checked against the local known-bad SHA-256 denylist, filename-guarded, and metadata-scanned before persistence. Configure blocked artifact hashes with `TIANYUAN_PLUGIN_ARTIFACT_BLOCKED_SHA256` or `PLUGIN_ARTIFACT_BLOCKED_SHA256`; values may be comma, semicolon, or whitespace separated 64-hex SHA-256 digests, with optional `sha256:` prefix. Zip artifacts are not extracted; the scanner only inspects metadata and rejects path traversal, absolute paths, excessive entry count, excessive uncompressed size, and invalid zip uploads. Set `TIANYUAN_PLUGIN_ARTIFACT_RETENTION_DAYS` or `PLUGIN_ARTIFACT_RETENTION_DAYS` to change the recorded retention window; the value is clamped to `1..3650` days. `POST /api/plugins/artifacts/cleanup` provides admin-gated local retention cleanup and defaults to `dry_run=true`; actual deletion requires `dry_run=false` and only deletes registered relative paths that resolve inside the configured artifact root. Production still needs object-storage lifecycle rules, scheduled cleanup ownership, malware scanning, and threat-intel feed integration before plugin artifacts are treated as a managed package repository.

## 8. P1/P2/P3 Readiness

The current deployment prepares persistent volumes for the planned work:

- P1 real holdings import, data source health center, and run comparison will store imported files, health snapshots, and comparison records under the mounted storage layer.
- P2 SignalOps lifecycle, enhanced backtest, and audit replay will reuse the SQLite database plus run event storage.
- P3 plugin Agent runtime plan, strategy experiments, and knowledge version governance now have a first-version backend/API/UI path. Runtime plugins remain read-only plan entries by default; arbitrary plugin code execution and real trade actions must stay disabled until a separate sandbox design is implemented.
- P3 productization now has backend-local operator/RBAC enforcement, config operator audit binding, SQLite analysis job mirroring, worker heartbeat fields, deployable production health metrics, frontend operator context, plugin role gating, SignalOps role-aware high-risk action disabling, Backend Status production health, and Config Versions visibility for external runtime configuration changes. External Agent Runtime config versions explicitly expose secret-safe rollback blocking, `approval_gate`, immutable public vault-version refs, and an admin-only approved restore executor at `POST /api/config/external-restore`; unattended automatic restore remains disabled.
